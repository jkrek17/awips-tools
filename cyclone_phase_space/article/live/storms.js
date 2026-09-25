/* Cyclone Phase Space, live: the storm panel.
   The tracked storms from index.json, each with its class strip on the
   cycle's time axis and two small phase diagrams on the article's
   Figure 1 axes, the five deepest lows of the frame, storm tracks and
   names on the map, and follow mode. The diagrams need HVTL, HVTU and B
   per point, which index.json's points lack, so every frame's
   lows.geojson is fetched once and each point is matched to the nearest
   center within MATCH_KM. Uses the globals from app.js. */
'use strict';

// Figure 1's axis limits (article/figures/diagram_style.py), in m.
const FIG1 = { vtl: [-300, 300], vtu: [-300, 300], b: [-20, 80], onset: 10 };
// Figure 1's quadrant colors: panel (a) B vs -VTL, panel (b) -VTU vs -VTL.
const QUAD = {
  b: [[0, 300, -20, 10, '#c3c2b7'], [0, 300, 10, 80, '#eb6834'], [-300, 0, 10, 80, '#2a78d6'], [-300, 0, -20, 10, '#4a3aa7']],
  u: [[0, 300, 0, 300, '#e34948'], [0, 300, -300, 0, '#eb6834'], [-300, 0, -300, 0, '#2a78d6'], [-300, 0, 0, 300, '#4a3aa7']],
};
const SHORT = ['sym deep warm', 'sym shallow warm', 'asym deep warm', 'asym shallow warm', 'asym cold', 'sym cold', 'shallow cold'];
// Mini diagram geometry, in px at 1:1 (the panel sizes them to 150 px).
const MW = 150;
const MH = 136;
const PX = [34, 138];
const PY = [18, 100];
const SVGNS = 'http://www.w3.org/2000/svg';

const ST = { list: [], byName: new Map(), built: false, t0: 0, dt: 216e5, span: 1 };

function stormLabel(name) {
  const m = /^AUTO_\d{6}_(\d+)$/.exec(name);
  return m ? `AUTO ${m[1]}` : String(name).replace(/_/g, ' ');
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

const xPct = (t) => ((t - ST.t0 + ST.dt / 2) / ST.span) * 100;

function initStorms() {
  const n = S.index.hours.length;
  ST.list = [];
  ST.byName.clear();
  ST.built = false;
  ST.t0 = validAt(0)?.getTime() ?? 0;
  ST.dt = n > 1 ? (validAt(1) - validAt(0)) || 216e5 : 216e5;
  ST.span = (validAt(n - 1)?.getTime() ?? ST.t0) - ST.t0 + ST.dt;
  for (const s of S.index.storms || []) {
    const at = new Array(n).fill(null);
    const seq = Array.isArray(s.cls_seq) && s.cls_seq.length === (s.points || []).length ? s.cls_seq : null;
    (s.points || []).forEach((pt, j) => {
      const k = frameIndex(pt);
      if (k >= 0) at[k] = { lat: pt.lat, lon: pt.lon, mslp: pt.mslp, cls: seq ? seq[j] : pt.cls, c: null };
    });
    const ms = at.filter(Boolean).map((e) => +e.mslp).filter(Number.isFinite);
    const st = {
      name: s.name, label: stormLabel(s.name), fsu: s.fsu, phase: s.phase_png, compare: s.compare_png,
      at, min: ms.length ? Math.min(...ms) : Infinity, el: null, nowB: null, nowU: null,
    };
    ST.list.push(st);
    ST.byName.set(s.name, st);
  }
  ST.list.sort((a, b) => a.min - b.min);
  $('storms-count').textContent = ST.list.length ? String(ST.list.length) : '';
  renderTimeAxis();
  renderStormList();
}

// Day labels at 00 UTC, with the month on the first label and at a change of month.
function renderTimeAxis() {
  const n = S.index.hours.length;
  let html = '';
  let first = true;
  for (let k = 0; k < n; k++) {
    const v = validAt(k);
    if (!v || v.getUTCHours() !== 0) continue;
    const x = xPct(v.getTime());
    const d = v.getUTCDate();
    const mon = !first && d === 1 ? ` ${MON[v.getUTCMonth()]}` : '';
    if (first) $('axis-note').textContent = `Class at each 6 h point against valid time, days from ${d} ${MON[v.getUTCMonth()]} (UTC). Diagrams on the article's Figure 1 axes; the ring marks this hour.`;
    if (x > (mon ? 86 : 94)) continue;
    html += `<span${x < 8 ? ' class="start"' : ''} style="left:${x.toFixed(2)}%">${d}${mon}</span>`;
    first = false;
  }
  $('time-axis').innerHTML = html;
}

function stripHTML(s) {
  const w = (ST.dt / ST.span) * 100;
  let html = '';
  s.at.forEach((e, k) => {
    if (!e) return;
    const x = xPct(validAt(k).getTime()) - w / 2;
    const none = e.cls == null;  // no class at this point: an empty cell
    html += `<i${none ? ' class="none"' : ''} style="left:${x.toFixed(2)}%;width:${w.toFixed(2)}%;--c:${none ? 'transparent' : cls(e.cls).hex}"></i>`;
  });
  return html + '<b class="now"></b>';
}

function renderStormList() {
  const ol = $('storm-list');
  ol.innerHTML = '';
  if (!ST.list.length) {
    ol.innerHTML = '<li class="empty-row">No storms tracked in this cycle.</li>';
    return;
  }
  for (const s of ST.list) {
    const li = document.createElement('li');
    li.className = 'storm';
    li.innerHTML = `<button type="button" class="storm-hit" aria-pressed="false">
        <span class="storm-top"><span class="storm-name"></span><span class="storm-fsu"></span><span class="storm-mslp"></span></span>
        <span class="strip">${stripHTML(s)}</span>
      </button>
      <div class="minis"></div>`;
    li.querySelector('.storm-name').textContent = s.label;
    li.querySelector('.storm-name').title = s.name;
    li.querySelector('.storm-fsu').textContent = s.fsu != null ? `FSU ${s.fsu}` : 'not on FSU';
    li.querySelector('.storm-hit').addEventListener('click', () => (S.follow === s.name ? unfollow() : follow(s.name)));
    s.el = li;
    s.minis = li.querySelector('.minis');
    s.minis.append(miniSVG(s, 'b'), miniSVG(s, 'u'));
    ol.append(li);
  }
}

/* ---------- mini phase diagrams ---------- */

function svgEl(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}

// "-V_T^L (m)" and friends, as SVG text with a sub- and superscript.
function vtLabel(parent, x, y, sup, anchor) {
  const t = svgEl('text', { x, y, 'text-anchor': anchor, class: 'ax-t' });
  t.append(`${MINUS}V`);
  t.append(svgEl('tspan', { dy: 3, class: 'ss' }, 'T'));
  t.append(svgEl('tspan', { dy: -7, class: 'ss' }, sup));
  t.append(svgEl('tspan', { dy: 4 }, ' (m)'));
  parent.append(t);
}

function miniSVG(s, kind) {
  const yl = kind === 'b' ? FIG1.b : FIG1.vtu;
  const xl = FIG1.vtl;
  const X = (v) => PX[0] + ((v - xl[0]) / (xl[1] - xl[0])) * (PX[1] - PX[0]);
  const Y = (v) => PY[1] - ((v - yl[0]) / (yl[1] - yl[0])) * (PY[1] - PY[0]);
  const title = kind === 'b' ? 'B against minus V T L' : 'minus V T U against minus V T L';
  const svg = svgEl('svg', { viewBox: `0 0 ${MW} ${MH}`, width: MW, height: MH, class: `mini mini-${kind}`, role: 'img',
    'aria-label': `${s.label}, phase diagram, ${title}` });
  for (const [x0, x1, y0, y1, c] of QUAD[kind]) {
    svg.append(svgEl('rect', { x: X(x0), y: Y(y1), width: X(x1) - X(x0), height: Y(y0) - Y(y1), fill: c, class: `quad q-${kind}` }));
  }
  const thr = kind === 'b' ? FIG1.onset : 0;
  svg.append(svgEl('line', { x1: X(0), x2: X(0), y1: PY[0], y2: PY[1], class: 'zero' }));
  svg.append(svgEl('line', { x1: PX[0], x2: PX[1], y1: Y(thr), y2: Y(thr), class: 'zero' }));
  svg.append(svgEl('rect', { x: PX[0], y: PY[0], width: PX[1] - PX[0], height: PY[1] - PY[0], class: 'frame' }));
  // Ticks and labels.
  for (const v of [-300, 0, 300]) {
    svg.append(svgEl('line', { x1: X(v), x2: X(v), y1: PY[1], y2: PY[1] + 3, class: 'tick' }));
    svg.append(svgEl('text', { x: X(v), y: PY[1] + 16, 'text-anchor': 'middle', class: 'tl' }, fmt(v)));
  }
  const yt = kind === 'b' ? [-20, 10, 40, 80] : [-300, 0, 300];
  for (const v of yt) {
    svg.append(svgEl('line', { x1: PX[0] - 3, x2: PX[0], y1: Y(v), y2: Y(v), class: 'tick' }));
    svg.append(svgEl('text', { x: PX[0] - 5, y: Y(v) + 4, 'text-anchor': 'end', class: 'tl' }, fmt(v)));
  }
  vtLabel(svg, (PX[0] + PX[1]) / 2, MH - 4, 'L', 'middle');
  if (kind === 'b') svg.append(svgEl('text', { x: 0, y: 10, class: 'ax-t' }, 'B (m)'));
  else vtLabel(svg, 0, 10, 'U', 'start');

  const g = svgEl('g', { class: 'traj' });
  svg.append(g);
  const now = svgEl('circle', { r: 4, class: 'now', visibility: 'hidden' });
  svg.append(now);
  if (kind === 'b') s.nowB = now; else s.nowU = now;
  s[`traj_${kind}`] = { g, X, Y, xl, yl };
  if (ST.built) drawTrajectory(s, kind);
  return svg;
}

const clamp = (v, [lo, hi]) => Math.max(lo, Math.min(hi, v));

function pointXY(s, kind, e) {
  const c = e?.c;
  const yv = kind === 'b' ? c?.hb : c?.hvtu;
  if (!c || blank(c.hvtl) || blank(yv)) return null;
  const t = s[`traj_${kind}`];
  const x = clamp(+c.hvtl, t.xl);
  const y = clamp(+yv, t.yl);
  return { x: t.X(x), y: t.Y(y), clipped: x !== +c.hvtl || y !== +yv, hex: cls(e.cls).hex };
}

function drawTrajectory(s, kind) {
  const t = s[`traj_${kind}`];
  t.g.textContent = '';
  let d = '';
  let pen = false;
  const dots = [];
  for (const e of s.at) {
    const p = pointXY(s, kind, e);
    if (!p) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
    pen = true;
    dots.push(p);
  }
  t.g.append(svgEl('path', { d, class: 'path' }));
  for (const p of dots) {
    t.g.append(svgEl('circle', { cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: 2, fill: p.clipped ? 'none' : p.hex, stroke: p.clipped ? p.hex : '#0d0d0f', class: 'dot' }));
  }
}

/* ---------- all frames' lows, once ---------- */

async function loadAllLows() {
  const hours = S.index.hours;
  const res = await Promise.allSettled(hours.map((h) => getJSON(lowsUrl(h))));
  const centers = res.map((r) => (r.status === 'fulfilled' ? centersOf(r.value) : []));
  for (const s of ST.list) {
    s.at.forEach((e, k) => { if (e) e.c = nearest(centers[k], e.lat, e.lon, MATCH_KM); });
  }
  ST.built = true;
  for (const s of ST.list) {
    if (s.traj_b) drawTrajectory(s, 'b');
    if (s.traj_u) drawTrajectory(s, 'u');
  }
  document.body.classList.add('storms-built');
  stormsFrame(S.i);
}

/* ---------- per frame ---------- */

function stormsFrame(i) {
  const cur = validAt(i);
  const nowX = cur ? xPct(cur.getTime()) : 0;
  nameG.clearLayers();
  for (const s of ST.list) {
    const e = s.at[i];
    if (s.el) {
      s.el.classList.toggle('absent', !e);
      s.el.classList.toggle('following', S.follow === s.name);
      s.el.querySelector('.storm-hit').setAttribute('aria-pressed', String(S.follow === s.name));
      s.el.querySelector('.storm-mslp').textContent = e ? hpa(e.mslp) : 'not at this hour';
      s.el.querySelector('.now').style.left = `${nowX.toFixed(2)}%`;
      for (const [kind, ring] of [['b', s.nowB], ['u', s.nowU]]) {
        const p = ST.built && e ? pointXY(s, kind, e) : null;
        ring.setAttribute('visibility', p ? 'visible' : 'hidden');
        if (p) {
          ring.setAttribute('cx', p.x.toFixed(1));
          ring.setAttribute('cy', p.y.toFixed(1));
          ring.setAttribute('fill', p.hex);
        }
      }
    }
    if (e && S.layers.tracks) {
      for (const o of OFFSETS) {
        nameG.addLayer(L.marker([e.lat, e.lon + o], {
          icon: L.divIcon({ className: 'storm-name', iconSize: [0, 0], html: `<span>${esc(s.label)}</span>` }),
          interactive: false, keyboard: false, zIndexOffset: -100,
        }));
      }
    }
  }
  renderDeepest();
}

function renderDeepest() {
  const ol = $('deep-list');
  const list = S.centers.filter((c) => shown(c) && !blank(c.mslp)).sort((a, b) => a.mslp - b.mslp).slice(0, 5);
  ol.textContent = '';
  if (!list.length) {
    ol.innerHTML = '<li class="empty-row">No closed lows at this hour.</li>';
    return;
  }
  for (const c of list) {
    const s = matchStorm(c, S.i);
    const li = document.createElement('li');
    li.innerHTML = `<button type="button" class="deep-row"><i style="--c:${cls(c.cls).hex}"></i>
      <span class="d-mslp">${hpa(c.mslp)}</span><span class="d-where">${pos(c.lat, c.lon)}</span><span class="d-name"></span></button>`;
    li.querySelector('.d-name').textContent = s ? s.label : `${c.cls ?? ''} ${SHORT[c.cls] ?? ''}`.trim();
    li.querySelector('button').addEventListener('click', () => {
      if (S.follow) unfollow();
      selectLow(c, { center: true, zoom: Math.max(map.getZoom(), 4) });
    });
    ol.append(li);
  }
}

function matchStorm(c, i) {
  let best = null;
  let bd = MATCH_KM;
  for (const s of ST.list) {
    const e = s.at[i];
    if (!e) continue;
    const d = km(c.lat, c.lon, e.lat, e.lon);
    if (d <= bd) { bd = d; best = s; }
  }
  return best;
}

/* ---------- tracks ---------- */

function drawTracks() {
  trackG.clearLayers();
  if (!S.layers.tracks) { if (S.index) stormsFrame(S.i); return; }
  for (const s of ST.list) {
    const pts = s.at.filter(Boolean).map((e) => ({ ...e }));
    for (let k = 1; k < pts.length; k++) {  // unwrap across the dateline
      while (pts[k].lon - pts[k - 1].lon > 180) pts[k].lon -= 360;
      while (pts[k].lon - pts[k - 1].lon < -180) pts[k].lon += 360;
    }
    const on = S.follow === s.name;
    for (const o of OFFSETS) {
      for (let k = 0; k + 1 < pts.length; k++) {
        const a = pts[k];
        const b = pts[k + 1];
        trackG.addLayer(L.polyline([[a.lat, a.lon + o], [b.lat, b.lon + o]], {
          renderer: trackR, color: cls(a.cls).hex, weight: on ? 2 : 1.25, opacity: on ? 1 : 0.7, interactive: false,
        }));
      }
      for (const a of pts) {
        trackG.addLayer(L.circleMarker([a.lat, a.lon + o], {
          renderer: trackR, radius: on ? 2 : 1.5, stroke: false, fillColor: cls(a.cls).hex, fillOpacity: 1, interactive: false,
        }));
      }
    }
  }
  if (S.index) stormsFrame(S.i);
}

/* ---------- follow mode ---------- */

function follow(name, { quiet = false } = {}) {
  const s = ST.byName.get(name);
  if (!s) return;
  S.follow = name;
  $('follow-name').textContent = s.label;
  $('follow').hidden = false;
  if (narrow()) setStormsOpen(false);
  drawTracks();
  let k = S.i;
  if (!s.at[k]) {  // not at this hour: go to its nearest hour
    let bd = Infinity;
    s.at.forEach((e, j) => { if (e && Math.abs(j - S.i) < bd) { bd = Math.abs(j - S.i); k = j; } });
  }
  const e = s.at[k];
  if (e && !quiet) centerOn(e.lat, e.lon, Math.max(map.getZoom(), 4));
  S.sel = { lat: e?.lat, lon: e?.lon, c: null };
  if (k !== S.i) show(k);
  else { refreshCard(); drawSelection(); stormsFrame(S.i); }
  writeHash();
}

function unfollow() {
  if (!S.follow) return;
  S.follow = null;
  $('follow').hidden = true;
  drawTracks();
  if (!$('card').hidden && S.sel?.c) renderCard(S.sel.c, matchStorm(S.sel.c, S.i));
  writeHash();
}

function followFrame() {
  const s = S.follow && ST.byName.get(S.follow);
  const e = s?.at[S.i];
  if (e) centerOn(e.lat, e.lon);
}

function toggleFollow() {
  if (S.follow) { unfollow(); return; }
  const fromCard = S.sel?.c && matchStorm(S.sel.c, S.i);
  const s = fromCard || ST.list.find((x) => x.at[S.i]) || ST.list[0];
  if (s) follow(s.name);
}
