/* Cyclone Phase Space, live: the tracked lows.
   Every tracked low of the run from index.json, each with its point at
   every forecast hour; their tracks and names on the map; the deepest
   lows of the hour; finding a low by name; selection and follow mode.
   The selected or followed low's whole track goes into the 3-D phase
   space on the phase space card (card.js, space3d.js).

   Track entries (source "track") carry the run's own center id at every
   point, and the centers in each frame's lows.geojson carry the track id,
   so a map dot joins its track exactly. Entries without ids (an older
   cycle's collection storms, or an index.json from before the tracks)
   are matched to the nearest center within MATCH_KM, and their phase
   space values are read from every frame's lows.geojson when the points
   lack them.

   B, two ways. The gridded field's B (hb, and the class cls from it) has
   to take the storm's motion from the model's steering flow, since a
   gridded field sees one frame and has no track. Hart's
   (2003) B uses the storm's own motion; the exporter computes it for every
   tracked low from the motion between fixes (hbt, the class clst, the
   motion spd in kt and hdg in degrees toward, on the track points; hbt,
   clst and spd on the map centers). Wherever the page shows a tracked
   low's B or class it uses hbt and clst (bOf, clsOf), and falls back to
   hb and cls where they are missing: untracked lows, points without
   motion, the collection's storms and older exports. Where the two
   classes differ the page marks it quietly (classDiffers): a thin ring in
   the field's class color round the map dot and the list dot, a line on
   the card. Uses the globals from app.js. */
'use strict';

// Figure 1's axis limits (article/figures/diagram_style.py), in m.
const FIG1 = { vtl: [-300, 300], vtu: [-300, 300], b: [-20, 80], onset: 10 };
const SHORT = ['sym deep warm', 'sym shallow warm', 'asym deep warm', 'asym shallow warm', 'asym cold', 'sym cold', 'shallow cold'];
const TAIL_STEPS = 4;            // map tail: the last 24 h, at 6 h steps

const ST = { list: [], byKey: new Map(), built: false, hover: null, selected: null, trackB: false };

function stormLabel(name) {
  const m = /^AUTO_\d{6}_(\d+)$/.exec(name);
  return m ? `AUTO ${m[1]}` : String(name).replace(/_/g, ' ');
}

// "15N 155E": whole degrees, for a storm's subtitle.
function place(lat, lon) {
  const w = K.wrapLon(lon);
  const d = (v, p, n) => `${Math.abs(Math.round(v))}${Math.round(v) >= 0 ? p : n}`;
  return `${d(lat, 'N', 'S')} ${d(w, 'E', 'W')}`;
}

function frameIndex(pt) {
  const t = pt.valid && utc(pt.valid);
  const n = S.index.hours.length;
  for (let k = 0; k < n; k++) {
    const v = validAt(k);
    if (t && v ? Math.abs(t - v) < 60e3 : pt.fhr === S.index.hours[k]) return k;
  }
  return -1;
}

function nearest(centers, lat, lon, maxKm) {
  let best = null;
  let bd = maxKm;
  for (const c of centers) {
    const d = km(lat, lon, c.lat, c.lon);
    if (d <= bd) { bd = d; best = c; }
  }
  return best;
}

const hasTerms = (e) => !blank(e.hvtl) && !blank(e.hvtu) && !blank(e.hb);

// B and class of a low or a track point: Hart's, from the storm's own
// motion, where the export has it; else the field's steering-flow values.
const trackB = (e) => !!e && !blank(e.hbt);
const bOf = (e) => (trackB(e) ? e.hbt : e?.hb);
const clsOf = (e) => (e && e.clst != null && !blank(e.clst) ? +e.clst : e?.cls);
// The two classes disagree at this point (both known).
const classDiffers = (e) => trackB(e) && e.clst != null && e.cls != null && !blank(e.clst) && !blank(e.cls) && +e.clst !== +e.cls;

// The title of the differing-class mark.
const diffTitle = (e) => `Classes differ: ${SHORT[clsOf(e)] ?? cls(clsOf(e)).name} (${clsOf(e)}) with B from the storm's motion; ` +
  `${SHORT[e.cls] ?? cls(e.cls).name} (${e.cls}) in the field, with B from the steering flow`;

// 16 compass points, for a heading in degrees toward.
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compass = (d) => COMPASS[Math.round((((+d % 360) + 360) % 360) / 22.5) % 16];

/* ---------- the storms from index.json ---------- */

function initStorms() {
  const hours = S.index.hours;
  const n = hours.length;
  ST.list = [];
  ST.byKey.clear();
  ST.hover = null;
  const cycle = String(S.index.cycle ?? '');
  (S.index.storms || []).forEach((s, order) => {
    const pts = s.points || [];
    const at = new Array(n).fill(null);
    const seq = Array.isArray(s.cls_seq) && s.cls_seq.length === pts.length ? s.cls_seq : null;
    const seqt = Array.isArray(s.clst_seq) && s.clst_seq.length === pts.length ? s.clst_seq : null;
    pts.forEach((pt, j) => {
      const k = frameIndex(pt);
      if (k < 0) return;
      at[k] = {
        lat: +pt.lat, lon: +pt.lon, mslp: pt.mslp, cls: seq ? seq[j] : pt.cls, id: pt.id,
        hvtl: pt.hvtl, hvtu: pt.hvtu, hb: pt.hb, idx: pt.idx, c: null,
        hbt: pt.hbt ?? null, clst: seqt ? seqt[j] : pt.clst ?? null, spd: pt.spd ?? null, hdg: pt.hdg ?? null,
      };
    });
    const live = [];
    at.forEach((e, k) => { if (e) live.push(k); });
    const ms = live.map((k) => +at[k].mslp).filter(Number.isFinite);
    const name = String(s.name ?? s.id ?? `storm ${order + 1}`);
    const id = s.id != null ? String(s.id) : null;
    const generic = /^L\d+$/.test(name);
    const f = (k) => `F${pad(hours[k], 3)}`;
    let sub = 'no points in this run';
    if (live.length) {
      const a = live[0];
      const b = live[live.length - 1];
      sub = `${place(at[a].lat, at[a].lon)}, ${a === b ? `${f(a)} only` : `${f(a)} to ${f(b)}`}`;
    }
    if (s.cycle && String(s.cycle) !== cycle) sub += `, ${fmtCycle(s.cycle)} run`;
    const st = {
      key: id ?? name, id, name, label: stormLabel(name), generic,
      track: s.source === 'track', fsu: s.fsu ?? null, phase: s.phase_png, compare: s.compare_png,
      at, min: ms.length ? Math.min(...ms) : (+s.min_mslp || Infinity), sub, order,
      share: generic && id ? id : name,
      text: [name.replace(/_/g, ' '), stormLabel(name), id, s.fsu != null ? `fsu ${s.fsu}` : ''].join(' | ').toLowerCase(),
    };
    ST.list.push(st);
    for (const k of [st.key, id, name]) if (k != null && !ST.byKey.has(k)) ST.byKey.set(k, st);
  });
  ST.list.sort((a, b) => a.min - b.min || a.order - b.order);
  ST.built = !ST.list.some((s) => s.at.some((e) => e && !hasTerms(e)));
  // Does this export carry Hart's B from the track motion at all?
  ST.trackB = !!S.index.track_b || ST.list.some((s) => s.at.some(trackB));
  $('runInfo').textContent = `${S.index.model || 'GFS'} · ${ST.list.length} tracked low${ST.list.length === 1 ? '' : 's'}`;
}

// A share key, a track id or a name, in any case.
function findStorm(q) {
  if (q == null || q === '') return null;
  q = String(q);
  if (ST.byKey.has(q)) return ST.byKey.get(q);
  const l = q.toLowerCase().replace(/[\s_]+/g, ' ');
  return ST.list.find((s) => s.name.toLowerCase().replace(/_/g, ' ') === l || s.label.toLowerCase() === l || s.id?.toLowerCase() === l) || null;
}
const followShare = () => findStorm(S.follow)?.share ?? S.follow;

// The storm a map center belongs to: by the track id it carries, else,
// for entries without run ids only, the nearest point within MATCH_KM.
function stormOf(c, i = S.i) {
  if (!c) return null;
  if (c.track != null) {
    const s = ST.byKey.get(String(c.track));
    if (s) return s;
  }
  let best = null;
  let bd = MATCH_KM;
  for (const s of ST.list) {
    const e = s.track ? null : s.at[i];
    if (!e) continue;
    const d = km(c.lat, c.lon, e.lat, e.lon);
    if (d <= bd) { bd = d; best = s; }
  }
  return best;
}

// The map center of a storm's point: joined by id, else the nearest one.
function centerOf(s, e) {
  if (!e) return null;
  if (s.track) {
    const c = S.centers.find((x) => (e.id != null ? x.id === e.id : x.track != null && String(x.track) === s.id));
    if (c) return c;
    if (hasTerms(e)) return { ...e, c: undefined, terrain: false };
  }
  return nearest(S.centers, e.lat, e.lon, MATCH_KM);
}

/* ---------- entries without values: every frame's lows, once ---------- */

async function loadAllLows() {
  if (!ST.built) {
    const hours = S.index.hours;
    const res = await Promise.allSettled(hours.map((h) => getJSON(lowsUrl(h))));
    const centers = res.map((r) => (r.status === 'fulfilled' ? centersOf(r.value) : []));
    for (const s of ST.list) {
      s.at.forEach((e, k) => {
        if (!e || hasTerms(e)) return;
        e.c = s.track && e.id != null ? centers[k].find((c) => c.id === e.id) : nearest(centers[k], e.lat, e.lon, MATCH_KM);
        for (const f of ['hvtl', 'hvtu', 'hb', 'idx']) if (blank(e[f]) && e.c) e[f] = e.c[f];
        // the track's own B, only from a center of this same track
        if (s.track && e.c && e.c.track != null && String(e.c.track) === s.id) {
          for (const f of ['hbt', 'clst', 'spd']) if (e[f] == null && e.c[f] != null) e[f] = e.c[f];
        }
      });
    }
    ST.built = true;
    phaseFrame();
  }
}

/* ---------- per frame ---------- */

function stormsFrame() {
  drawTracks();
  renderDeepest();
}

function renderDeepest() {
  const ol = $('deep-list');
  if (!S.ready) return;
  const list = S.centers.filter((c) => shown(c) && !blank(c.mslp)).sort((a, b) => a.mslp - b.mslp).slice(0, 5);
  ol.textContent = '';
  if (!list.length) {
    ol.innerHTML = '<li class="empty-row">No closed lows at this hour.</li>';
    return;
  }
  for (const c of list) {
    const s = stormOf(c, S.i);
    const li = document.createElement('li');
    const on = S.sel?.c === c;
    const alt = classDiffers(c);
    li.innerHTML = `<button type="button" class="deep-row"${on ? ' aria-current="true"' : ''}><i${alt ? ` class="alt" style="--c:${cls(clsOf(c)).hex};--c2:${cls(c.cls).hex}" title="${esc(diffTitle(c))}"` : ` style="--c:${cls(clsOf(c)).hex}"`}></i>
      <span class="d-mslp">${hpa(c.mslp)}</span><span class="d-name"></span><span class="d-where">${pos(c.lat, c.lon)}</span></button>`;
    li.querySelector('.d-name').textContent = s ? s.label : SHORT[clsOf(c)] ?? 'untracked';
    li.querySelector('button').addEventListener('click', () => {
      if (S.follow) unfollow();
      selectLow(c, { center: true, zoom: Math.max(map.getZoom(), 3) });
    });
    ol.append(li);
  }
}

/* ---------- tracks on the map ---------- */

// The followed, the selected (clicked) and the hovered storm get the
// whole track, colored by class with a dot at each point; every other
// storm present at this hour gets only its last 24 h, thin and faint, as
// a motion cue.
const focusKeys = () => [S.follow, ST.selected, ST.hover].filter(Boolean);

// Longitudes made continuous along a track, so a line crossing the date
// line takes the short way.
function unwrap(pts) {
  for (let k = 1; k < pts.length; k++) {
    while (pts[k].lon - pts[k - 1].lon > 180) pts[k].lon -= 360;
    while (pts[k].lon - pts[k - 1].lon < -180) pts[k].lon += 360;
  }
  return pts;
}

const seg = (a, b, props) => ({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: [[a.lon, a.lat], [b.lon, b.lat]] } });

function drawTracks() {
  const lines = [];
  const dots = [];
  if (S.layers.tracks && S.index) {
    for (const key of new Set(focusKeys())) {
      const s = findStorm(key);
      if (!s) continue;
      const pts = unwrap(s.at.filter(Boolean).map((e) => ({ ...e })));
      const w = S.follow === key || ST.selected === key ? 2.2 : 1.8;
      for (let k = 0; k + 1 < pts.length; k++) lines.push(seg(pts[k], pts[k + 1], { hex: cls(clsOf(pts[k])).hex, w }));
      for (const a of pts) dots.push({ type: 'Feature', properties: { hex: cls(clsOf(a)).hex }, geometry: { type: 'Point', coordinates: [a.lon, a.lat] } });
    }
  }
  setData('track', { type: 'FeatureCollection', features: lines });
  setData('trackpts', { type: 'FeatureCollection', features: dots });
  drawTails();
  drawOverlay();
}

function drawTails() {
  const segs = [];
  if (S.layers.tracks && S.index && S.ready) {
    const i = S.i;
    const focus = focusKeys();
    for (const s of ST.list) {
      if (!s.at[i] || focus.includes(s.key)) continue;
      const pts = [];
      for (let k = i; k >= 0 && k >= i - TAIL_STEPS && s.at[k]; k--) pts.unshift({ ...s.at[k] });
      if (pts.length < 2) continue;
      unwrap(pts);
      for (let k = 0; k + 1 < pts.length; k++) segs.push(seg(pts[k], pts[k + 1], { hex: cls(clsOf(pts[k])).hex }));
    }
  }
  setData('tails', { type: 'FeatureCollection', features: segs });
}

// Names at the storms' positions on the overlay: the daily collection's
// names and the followed, selected or hovered storm always; the L numbers
// only from LABEL_ZOOM. With them, from LABEL_ZOOM, each low's pressure
// beside its dot. Names never overlap each other, a dot or its pressure:
// each tries above right, above left, then below right, in order of
// priority (focus, named, deepest now), and a name with no free place is
// left out at this zoom. A focused name is always drawn.
function drawNames(ctx, z) {
  if (!S.ready) return;
  const wide = z < LABEL_ZOOM;
  const taken = [];
  const at = new Map();   // screen position of each center drawn
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  for (const c of S.centers) {
    if (!shown(c)) continue;
    const p = ov.proj(c.lon, c.lat)[0];
    if (!p) continue;
    at.set(c, p);
    // a dot with the differing-class ring (app.js, lows-alt) is wider
    const ring = !c.terrain && classDiffers(c) ? 3 : 0;
    taken.push([p.x - 6 - ring, p.y - 6 - ring, p.x + 6 + ring, p.y + 6 + ring]);
    if (!wide && !blank(c.mslp)) {
      const t = String(Math.round(+c.mslp));
      ctx.font = `600 10.5px ${FAM}`;
      const w = ctx.measureText(t).width;
      const x = p.x + (isDeep(c) ? 10 : 8) + ring;
      taken.push([x - 2, p.y - 7, x + w + 2, p.y + 7]);
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(7,13,25,0.85)';
      ctx.strokeText(t, x, p.y);
      ctx.fillStyle = 'rgba(231,238,248,0.92)';
      ctx.fillText(t, x, p.y);
    }
  }
  if (!S.layers.tracks || !S.index) return;
  const focus = focusKeys();
  const GAP = 4;  // names keep this far apart, so two never read as one
  const free = (r) => !taken.some((q) => r[0] - GAP < q[2] && r[2] + GAP > q[0] && r[1] < q[3] && r[3] > q[1]);
  const list = [];
  for (const s of ST.list) {
    const e = s.at[S.i];
    if (!e) continue;
    const on = focus.includes(s.key);
    if (wide && s.generic && !on) continue;
    list.push({ s, e, on, rank: on ? 0 : s.generic ? 2 : 1, p: blank(e.mslp) ? 9999 : +e.mslp });
  }
  list.sort((a, b) => a.rank - b.rank || a.p - b.p);
  for (const { s, e, on } of list) {
    const p = ov.proj(e.lon, e.lat)[0];
    if (!p) continue;
    const generic = s.generic && !on;
    ctx.font = generic ? `500 10.5px ${FAM}` : `700 11.5px ${FAM}`;
    const w = ctx.measureText(s.label).width + 8;
    const rg = classDiffers(e) ? 3 : 0;  // clear of the differing-class ring
    const spots = [[p.x + 6, p.y - 22 - rg], [p.x - 6 - w, p.y - 22 - rg], [p.x + 6, p.y + 8 + rg]].map(([x, y]) => [x, y, x + w, y + 15]);
    const r = spots.find(free) || (on ? spots[0] : null);
    if (!r) continue;
    taken.push(r);
    ctx.fillStyle = on ? 'rgba(15,24,41,0.95)' : 'rgba(10,17,32,0.78)';
    ctx.fillRect(r[0], r[1], w, 15);
    if (on) {
      ctx.strokeStyle = 'rgba(231,238,248,0.7)';
      ctx.lineWidth = 1;
      ctx.strokeRect(r[0] + 0.5, r[1] + 0.5, w - 1, 14);
    }
    ctx.fillStyle = generic ? 'rgba(163,179,201,0.9)' : '#e7eef8';
    ctx.fillText(s.label, r[0] + 4, r[1] + 8);
  }
}

/* ---------- selection and follow ---------- */

function hoverStorm(key) {
  if (key === ST.hover) return;
  ST.hover = key;
  drawTracks();
}

// A click on a low selects its storm: its whole track on the map and in
// the phase space. The selection moves with the low as frames advance and
// clears when the card is closed.
function selectStorm(key) {
  if (key === ST.selected) return;
  ST.selected = key;
  drawTracks();
}

function follow(q, { quiet = false } = {}) {
  const s = findStorm(q);
  if (!s) return false;
  S.follow = s.key;
  ST.selected = s.key;
  $('follow-name').textContent = s.label;
  $('follow').hidden = false;
  let k = S.i;
  if (!s.at[k]) {  // not at this hour: go to its nearest hour
    let bd = Infinity;
    s.at.forEach((e, j) => { if (e && Math.abs(j - S.i) < bd) { bd = Math.abs(j - S.i); k = j; } });
  }
  const e = s.at[k];
  setSideOpen(true);
  if (e && !quiet) centerOn(e.lat, e.lon, Math.max(map.getZoom(), 3));
  S.sel = { lat: e?.lat, lon: e?.lon, c: null };
  drawTracks();
  if (k !== S.i) show(k);
  else { refreshCard(); drawSelection(); }
  writeHash();
  return true;
}

function unfollow() {
  if (!S.follow) return;
  S.follow = null;
  $('follow').hidden = true;
  drawTracks();
  if (S.sel?.c) renderCard(S.sel.c, stormOf(S.sel.c, S.i));
  writeHash();
}

function followFrame() {
  const e = findStorm(S.follow)?.at[S.i];
  if (e) centerOn(e.lat, e.lon);
}

function toggleFollow() {
  if (S.follow) { unfollow(); return; }
  const s = (S.sel?.c && stormOf(S.sel.c, S.i)) || findStorm(ST.selected) || findStorm(ST.hover);
  if (s) follow(s.key);
  else K.note('Click a low first, then press F to follow it.');
}

/* ---------- finding a low by name ---------- */

function bindSearch() {
  const q = $('ph-q');
  const hits = $('ph-hits');
  let found = [];
  let cur = -1;
  const close = () => { hits.hidden = true; cur = -1; q.setAttribute('aria-expanded', 'false'); };
  const pick = (s) => { close(); q.value = ''; q.blur(); follow(s.key); };
  const mark = () => hits.querySelectorAll('li').forEach((li, k) => li.setAttribute('aria-selected', String(k === cur)));
  q.addEventListener('input', () => {
    const t = q.value.trim().toLowerCase().replace(/[\s_]+/g, ' ');
    if (!t || !S.index) { close(); return; }
    found = ST.list.filter((s) => s.text.includes(t) || s.sub.toLowerCase().includes(t)).slice(0, 8);
    hits.innerHTML = found.length ? '' : '<li class="none">No tracked low matches</li>';
    found.forEach((s, k) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.innerHTML = `<b></b>${s.fsu != null ? `<span class="tag">FSU ${esc(s.fsu)}</span>` : ''}<span class="sub"></span>`;
      li.querySelector('b').textContent = s.label;
      li.querySelector('.sub').textContent = `${Number.isFinite(s.min) ? `${Math.round(s.min)} hPa · ` : ''}${s.sub}`;
      li.addEventListener('pointerdown', (e) => { e.preventDefault(); pick(found[k]); });
      hits.append(li);
    });
    cur = found.length ? 0 : -1;
    mark();
    hits.hidden = false;
    q.setAttribute('aria-expanded', 'true');
  });
  q.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { if (q.value) { e.stopPropagation(); q.value = ''; } close(); return; }
    if (hits.hidden || !found.length) return;
    if (e.key === 'ArrowDown') { cur = (cur + 1) % found.length; mark(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { cur = (cur - 1 + found.length) % found.length; mark(); e.preventDefault(); }
    else if (e.key === 'Enter' && cur >= 0) { pick(found[cur]); e.preventDefault(); }
  });
  q.addEventListener('blur', () => setTimeout(close, 100));
}
