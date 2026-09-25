/* Cyclone Phase Space, live: the storm panel.
   Every tracked low of the run from index.json, each with its class strip
   on the cycle's time axis and two small phase diagrams on the article's
   Figure 1 axes; a filter by name, depth and hemisphere; the five deepest
   lows of the frame; tracks and names on the map; and follow mode.

   Track entries (source "track") carry the run's own center id at every
   point, and the centers in each frame's lows.geojson carry the track id,
   so a map mark joins its track exactly. Entries without ids (an older
   cycle's collection storms, or an index.json from before the tracks)
   are matched to the nearest center within MATCH_KM, and their diagram
   values are read from every frame's lows.geojson when the points lack
   them. The list is long (about 130 entries), so each entry's strip and
   diagrams are drawn only as it nears the visible part of the panel.
   Uses the globals from app.js. */
'use strict';

// Figure 1's axis limits (article/figures/diagram_style.py), in m.
const FIG1 = { vtl: [-300, 300], vtu: [-300, 300], b: [-20, 80], onset: 10 };
// Figure 1's quadrant colors: panel (a) B vs -VTL, panel (b) -VTU vs -VTL.
const QUAD = {
  b: [[0, 300, -20, 10, '#c3c2b7'], [0, 300, 10, 80, '#eb6834'], [-300, 0, 10, 80, '#2a78d6'], [-300, 0, -20, 10, '#4a3aa7']],
  u: [[0, 300, 0, 300, '#e34948'], [0, 300, -300, 0, '#eb6834'], [-300, 0, -300, 0, '#2a78d6'], [-300, 0, 0, 300, '#4a3aa7']],
};
const SHORT = ['sym deep warm', 'sym shallow warm', 'asym deep warm', 'asym shallow warm', 'asym cold', 'sym cold', 'shallow cold'];
// Quadrant names as on the article's Figure 1: [corner, full name, short name]
// with the corner as (0 left / 1 right, 0 top / 1 bottom).
const QUAD_NAMES = {
  b: [[0, 0, 'asymmetric cold core', 'asym cold'], [1, 0, 'asymmetric warm core', 'asym warm'],
      [0, 1, 'symmetric cold core', 'sym cold'], [1, 1, 'symmetric warm core', 'sym warm']],
  u: [[0, 0, 'shallow cold core', 'shallow cold'], [1, 0, 'deep warm core', 'deep warm'],
      [0, 1, 'deep cold core', 'deep cold'], [1, 1, 'shallow warm core', 'shallow warm']],
};
// Mini diagram geometry, in px at 1:1 (the panel sizes them to 150 px).
const MW = 150;
const MH = 136;
const PX = [34, 140];
const PY = [18, 100];
const SMALL = { w: MW, h: MH, px: PX, py: PY };  // the mini diagram geometry of a listed storm
const BIG_W = 312;  // the selected storm's diagrams fill the panel width, one above the other

// The large geometry for a panel this wide: the same margins, the plot
// scaled to the width, the small diagram's aspect kept.
function bigGeom(w) {
  const pw = w - PX[0] - (MW - PX[1]);
  const ph = Math.round(pw * (PY[1] - PY[0]) / (PX[1] - PX[0]));
  return { w, h: ph + PY[0] + (MH - PY[1]), px: [PX[0], PX[0] + pw], py: [PY[0], PY[0] + ph] };
}
const SVGNS = 'http://www.w3.org/2000/svg';
const TAIL_STEPS = 4;            // map tail: the last 24 h, at 6 h steps
const DEPTHS = ['all', '1000', '980', 'fsu'];
const HEMIS = ['all', 'N', 'S'];

const ST = {
  list: [], byKey: new Map(), shown: [], built: false, t0: 0, dt: 216e5, span: 1,
  filter: { q: '', depth: '1000', hemi: 'all' }, hover: null, selected: null, io: null, scrollTo: null,
};

function stormLabel(name) {
  const m = /^AUTO_\d{6}_(\d+)$/.exec(name);
  return m ? `AUTO ${m[1]}` : String(name).replace(/_/g, ' ');
}

// "15N 155E": whole degrees, for the entry's subtitle.
function place(lat, lon) {
  const w = ((((lon + 180) % 360) + 360) % 360) - 180;
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

const xPct = (t) => ((t - ST.t0 + ST.dt / 2) / ST.span) * 100;
const hasTerms = (e) => !blank(e.hvtl) && !blank(e.hvtu) && !blank(e.hb);

/* ---------- the list from index.json ---------- */

function initStorms() {
  const hours = S.index.hours;
  const n = hours.length;
  ST.list = [];
  ST.byKey.clear();
  ST.hover = null;
  ST.io?.disconnect();
  ST.io = 'IntersectionObserver' in window
    ? new IntersectionObserver(onVisible, { root: $('storms-body'), rootMargin: '600px 0px' })
    : null;
  ST.t0 = validAt(0)?.getTime() ?? 0;
  ST.dt = n > 1 ? (validAt(1) - validAt(0)) || 216e5 : 216e5;
  ST.span = (validAt(n - 1)?.getTime() ?? ST.t0) - ST.t0 + ST.dt;
  const cycle = String(S.index.cycle ?? '');
  (S.index.storms || []).forEach((s, order) => {
    const pts = s.points || [];
    const at = new Array(n).fill(null);
    const seq = Array.isArray(s.cls_seq) && s.cls_seq.length === pts.length ? s.cls_seq : null;
    pts.forEach((pt, j) => {
      const k = frameIndex(pt);
      if (k < 0) return;
      at[k] = {
        lat: +pt.lat, lon: +pt.lon, mslp: pt.mslp, cls: seq ? seq[j] : pt.cls, id: pt.id,
        hvtl: pt.hvtl, hvtu: pt.hvtu, hb: pt.hb, idx: pt.idx, c: null,
      };
    });
    const live = [];
    at.forEach((e, k) => { if (e) live.push(k); });
    const ms = live.map((k) => +at[k].mslp).filter(Number.isFinite);
    const name = String(s.name ?? s.id ?? `storm ${order + 1}`);
    const id = s.id != null ? String(s.id) : null;
    const generic = /^L\d+$/.test(name);
    const lat0 = live.length ? live.reduce((a, k) => a + at[k].lat, 0) / live.length : +pts[0]?.lat || 0;
    const f = (k) => `f${pad(hours[k], 3)}`;
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
      at, min: ms.length ? Math.min(...ms) : (+s.min_mslp || Infinity), hemi: lat0 >= 0 ? 'N' : 'S', sub, order,
      share: generic && id ? id : name,
      text: [name.replace(/_/g, ' '), stormLabel(name), id, s.fsu != null ? `fsu ${s.fsu}` : ''].join(' | ').toLowerCase(),
      el: null, filled: false,
    };
    ST.list.push(st);
    for (const k of [st.key, id, name]) if (k != null && !ST.byKey.has(k)) ST.byKey.set(k, st);
  });
  ST.list.sort((a, b) => a.min - b.min || a.order - b.order);
  ST.built = !ST.list.some((s) => s.at.some((e) => e && !hasTerms(e)));
  if (ST.built) document.body.classList.add('storms-built');
  $('storms-count').textContent = ST.list.length ? String(ST.list.length) : '';
  renderTimeAxis();
  applyFilter();
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
    if (first) {
      const v0 = validAt(0), v1 = validAt(n - 1);
      const span = v0 && v1 ? `${v0.getUTCDate()} ${MON[v0.getUTCMonth()]} ${String(v0.getUTCHours()).padStart(2, '0')} UTC to ${v1.getUTCDate()} ${MON[v1.getUTCMonth()]} ${String(v1.getUTCHours()).padStart(2, '0')} UTC` : 'this run';
      $('axis-note').textContent = `Class at each 6 h point against valid time, ${span}; day ticks at 00 UTC. Diagrams in m on the article's Figure 1 axes; the ring marks this hour.`;
    }
    if (x > (mon ? 86 : 94)) continue;
    html += `<span${x < 8 ? ' class="start"' : ''} style="left:${x.toFixed(2)}%">${d}${mon}</span>`;
    first = false;
  }
  $('time-axis').innerHTML = html;
}

/* ---------- filter ---------- */

function passes(s) {
  const f = ST.filter;
  if (S.follow === s.key || ST.selected === s.key) return true;
  if (f.depth === 'fsu' ? s.fsu == null : f.depth !== 'all' && !(s.min < +f.depth)) return false;
  if (f.hemi !== 'all' && s.hemi !== f.hemi) return false;
  const q = f.q.trim().toLowerCase().replace(/[\s_]+/g, ' ');
  return !q || s.text.includes(q) || s.sub.toLowerCase().includes(q);
}

function applyFilter() {
  const ol = $('storm-list');
  ST.shown = ST.list.filter(passes);
  $('sf-count').textContent = `${ST.shown.length} of ${ST.list.length}`;
  if (!ST.list.length) {
    ol.innerHTML = '<li class="empty-row">No storms tracked in this cycle.</li>';
  } else if (!ST.shown.length) {
    ol.innerHTML = '<li class="empty-row">No tracked low matches the filter.</li>';
  } else {
    ol.replaceChildren(...ST.shown.map(entry));
  }
  if (S.index && map) stormsFrame(S.i);
}

function setFilter(k, v) {
  ST.filter[k] = v;
  if (k !== 'q') {
    document.querySelectorAll(`[data-sf-${k}]`).forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset[`sf${k[0].toUpperCase()}${k.slice(1)}`] === v)));
  }
  $('storms-body').scrollTop = 0;
  applyFilter();
}

function bindStormFilter() {
  let t = 0;
  $('sf-q').addEventListener('input', (e) => {
    clearTimeout(t);
    t = setTimeout(() => setFilter('q', e.target.value), 120);
  });
  $('sf-q').addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && e.target.value) { e.stopPropagation(); e.target.value = ''; setFilter('q', ''); }
  });
  document.querySelectorAll('[data-sf-depth]').forEach((b) => b.addEventListener('click', () => setFilter('depth', b.dataset.sfDepth)));
  document.querySelectorAll('[data-sf-hemi]').forEach((b) => b.addEventListener('click', () => setFilter('hemi', b.dataset.sfHemi)));
}

/* ---------- entries, drawn lazily ---------- */

// The head (name, place and hours, pressure now) is built at once; the
// strip and the two diagrams when the entry comes within 600 px of view.
function entry(s) {
  if (s.el) return s.el;
  const li = document.createElement('li');
  li.className = 'storm';
  li.innerHTML = `<button type="button" class="storm-hit" aria-pressed="false">
      <span class="st-top"><span class="st-name"></span><span class="st-fsu"></span><span class="st-mslp"></span></span>
      <span class="st-sub"></span>
    </button>
    <div class="st-body pending"></div>`;
  const nm = li.querySelector('.st-name');
  nm.textContent = s.label;
  nm.classList.toggle('generic', s.generic);
  if (s.label !== s.name) nm.title = s.name;
  const fsu = li.querySelector('.st-fsu');
  if (s.fsu != null) fsu.textContent = `FSU ${s.fsu}`;
  else fsu.remove();
  li.querySelector('.st-sub').textContent = s.sub;
  const hit = li.querySelector('.storm-hit');
  hit.addEventListener('click', () => (S.follow === s.key ? unfollow() : follow(s.key)));
  li.addEventListener('mouseenter', () => hoverStorm(s.key));
  li.addEventListener('mouseleave', () => hoverStorm(null));
  hit.addEventListener('focus', () => hoverStorm(s.key));
  hit.addEventListener('blur', () => hoverStorm(null));
  s.el = li;
  s.hit = hit;
  s.mslpEl = li.querySelector('.st-mslp');
  s.body = li.querySelector('.st-body');
  s.body.dataset.key = s.key;
  if (ST.io) ST.io.observe(s.body);
  else fill(s);
  return li;
}

function onVisible(entries) {
  let any = false;
  for (const en of entries) {
    if (!en.isIntersecting) continue;
    const s = ST.byKey.get(en.target.dataset.key);
    if (s && !s.filled) { fill(s); any = true; }
    ST.io.unobserve(en.target);
  }
  // Entries drawn above a scroll target can shift it: settle it again.
  if (any && ST.scrollTo) reveal(ST.scrollTo, false);
}

function fill(s) {
  s.filled = true;
  s.body.classList.remove('pending');
  s.body.innerHTML = `<span class="strip" aria-hidden="true">${stripHTML(s)}</span><div class="minis"></div>`;
  s.nowLine = s.body.querySelector('.strip .now');
  s.body.querySelector('.minis').append(miniSVG(s, 'b'), miniSVG(s, 'u'));
  updateEntry(s, S.i);
}

// The selected storm's diagrams are rebuilt at the panel width, one
// above the other; deselecting restores the small pair.
function resize(s, big) {
  if (!s.filled || !!s.big === big) return;
  s.big = big;
  const m = s.body.querySelector('.minis');
  m.classList.toggle('big', big);
  const G = big ? bigGeom(Math.max(240, m.clientWidth || BIG_W)) : SMALL;
  m.replaceChildren(miniSVG(s, 'b', G), miniSVG(s, 'u', G));
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

function updateEntry(s, i) {
  if (!s.el) return;
  resize(s, ST.selected === s.key);
  const e = s.at[i];
  const on = S.follow === s.key;
  s.el.classList.toggle('absent', !e);
  s.el.classList.toggle('following', on);
  s.el.classList.toggle('hovered', ST.hover === s.key);
  s.el.classList.toggle('selected', ST.selected === s.key);
  s.hit.setAttribute('aria-pressed', String(on));
  const txt = e ? hpa(e.mslp) : 'not at this hour';
  if (s.mslpEl.textContent !== txt) s.mslpEl.textContent = txt;
  if (!s.filled) return;
  const cur = validAt(i);
  s.nowLine.style.left = `${(cur ? xPct(cur.getTime()) : 0).toFixed(2)}%`;
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

// Scroll the storm panel to an entry, below the sticky time axis.
function reveal(key, smooth = true) {
  const s = findStorm(key);
  if (!s?.el?.isConnected || !document.body.classList.contains('storms-open')) return;
  const body = $('storms-body');
  const top = s.el.offsetTop - $('time-axis').offsetHeight - 4;
  const bottom = s.el.offsetTop + s.el.offsetHeight - body.clientHeight;
  const target = body.scrollTop > top ? top : body.scrollTop < bottom ? Math.min(top, bottom) : null;
  ST.scrollTo = key;
  clearTimeout(reveal.t);
  reveal.t = setTimeout(() => { ST.scrollTo = null; }, 800);
  if (target == null) return;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  body.scrollTo({ top: target, behavior: smooth && !reduce ? 'smooth' : 'auto' });
}

/* ---------- mini phase diagrams ---------- */

function svgEl(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}

// "Lower thermal wind (-V_T^L)" and friends, as SVG text with a sub- and superscript.
function vtLabel(parent, x, y, sup, anchor) {
  const t = svgEl('text', { x, y, 'text-anchor': anchor, class: 'ax-t' });
  t.append(`${sup === 'L' ? 'Lower' : 'Upper'} thermal wind (${MINUS}V`);
  t.append(svgEl('tspan', { dy: 3, class: 'ss' }, 'T'));
  t.append(svgEl('tspan', { dy: -7, class: 'ss' }, sup));
  t.append(svgEl('tspan', { dy: 4 }, ')'));
  parent.append(t);
}

function miniSVG(s, kind, G = SMALL) {
  const { w: MW, h: MH, px: PX, py: PY } = G;
  const big = G !== SMALL;
  const yl = kind === 'b' ? FIG1.b : FIG1.vtu;
  const xl = FIG1.vtl;
  const X = (v) => PX[0] + ((v - xl[0]) / (xl[1] - xl[0])) * (PX[1] - PX[0]);
  const Y = (v) => PY[1] - ((v - yl[0]) / (yl[1] - yl[0])) * (PY[1] - PY[0]);
  const title = kind === 'b' ? 'thermal asymmetry against lower thermal wind' : 'upper against lower thermal wind';
  const svg = svgEl('svg', { viewBox: `0 0 ${MW} ${MH}`, width: MW, height: MH, class: `mini mini-${kind}${big ? ' big' : ''}`,
    role: 'img', 'aria-label': `${s.label}, phase diagram, ${title}` });
  for (const [x0, x1, y0, y1, c] of QUAD[kind]) {
    svg.append(svgEl('rect', { x: X(x0), y: Y(y1), width: X(x1) - X(x0), height: Y(y0) - Y(y1), fill: c, class: `quad q-${kind}` }));
  }
  const thr = kind === 'b' ? FIG1.onset : 0;
  svg.append(svgEl('line', { x1: X(0), x2: X(0), y1: PY[0], y2: PY[1], class: 'zero' }));
  svg.append(svgEl('line', { x1: PX[0], x2: PX[1], y1: Y(thr), y2: Y(thr), class: 'zero' }));
  svg.append(svgEl('rect', { x: PX[0], y: PY[0], width: PX[1] - PX[0], height: PY[1] - PY[0], class: 'frame' }));
  for (const [right, bottom, full, short] of QUAD_NAMES[kind]) {
    const pad = big ? 6 : 3;
    svg.append(svgEl('text', { x: right ? PX[1] - pad : PX[0] + pad, y: bottom ? PY[1] - pad : PY[0] + pad + (big ? 9 : 6.5),
      'text-anchor': right ? 'end' : 'start', class: 'ql' }, big ? full : short));
  }
  // Ticks and labels.
  for (const v of [-300, 0, 300]) {
    svg.append(svgEl('line', { x1: X(v), x2: X(v), y1: PY[1], y2: PY[1] + 3, class: 'tick' }));
    svg.append(svgEl('text', { x: X(v), y: PY[1] + 14, 'text-anchor': v < 0 ? 'start' : v > 0 ? 'end' : 'middle', class: 'tl', dx: v < 0 ? -6 : v > 0 ? 6 : 0 }, fmt(v)));
  }
  const yt = kind === 'b' ? [-20, 10, 40, 80] : [-300, 0, 300];
  for (const v of yt) {
    svg.append(svgEl('line', { x1: PX[0] - 3, x2: PX[0], y1: Y(v), y2: Y(v), class: 'tick' }));
    svg.append(svgEl('text', { x: PX[0] - 5, y: Y(v) + 3.5, 'text-anchor': 'end', class: 'tl' }, fmt(v)));
  }
  vtLabel(svg, MW / 2, MH - 3, 'L', 'middle');
  if (kind === 'b') svg.append(svgEl('text', { x: 0, y: 10, class: 'ax-t' }, 'Thermal asymmetry (B)'));
  else vtLabel(svg, 0, 10, 'U', 'start');

  const g = svgEl('g', { class: 'traj' });
  svg.append(g);
  const now = svgEl('circle', { r: big ? 6 : 4, class: 'now', visibility: 'hidden' });
  svg.append(now);
  if (kind === 'b') s.nowB = now; else s.nowU = now;
  s[`traj_${kind}`] = { g, X, Y, xl, yl, r: big ? 3 : 2 };
  if (ST.built) drawTrajectory(s, kind);
  return svg;
}

const clamp = (v, [lo, hi]) => Math.max(lo, Math.min(hi, v));

function pointXY(s, kind, e) {
  const yv = kind === 'b' ? e?.hb : e?.hvtu;
  if (!e || blank(e.hvtl) || blank(yv)) return null;
  const t = s[`traj_${kind}`];
  const x = clamp(+e.hvtl, t.xl);
  const y = clamp(+yv, t.yl);
  return { x: t.X(x), y: t.Y(y), clipped: x !== +e.hvtl || y !== +yv, hex: cls(e.cls).hex };
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
    t.g.append(svgEl('circle', { cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: t.r, fill: p.clipped ? 'none' : p.hex, stroke: p.clipped ? p.hex : '#0d0d0f', class: 'dot' }));
  }
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
      });
    }
    ST.built = true;
    for (const s of ST.list) {
      if (s.traj_b) drawTrajectory(s, 'b');
      if (s.traj_u) drawTrajectory(s, 'u');
    }
    document.body.classList.add('storms-built');
  }
  stormsFrame(S.i);
}

/* ---------- per frame ---------- */

function stormsFrame(i) {
  for (const s of ST.shown) updateEntry(s, i);
  drawTails();
  drawNames();
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
    const s = stormOf(c, S.i);
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

/* ---------- tracks on the map ---------- */

// The followed, the selected (clicked) and the hovered storm get the
// whole track, colored by class with a dot at each point; every other
// listed storm present at this hour gets only its last 24 h, thin and
// faint, as a motion cue.
const focusKeys = () => [S.follow, ST.selected, ST.hover].filter(Boolean);

function unwrap(pts) {
  for (let k = 1; k < pts.length; k++) {
    while (pts[k].lon - pts[k - 1].lon > 180) pts[k].lon -= 360;
    while (pts[k].lon - pts[k - 1].lon < -180) pts[k].lon += 360;
  }
  return pts;
}

function drawTracks() {
  trackG.clearLayers();
  if (S.layers.tracks) {
    for (const key of new Set(focusKeys())) {
      const s = findStorm(key);
      if (!s) continue;
      const pts = unwrap(s.at.filter(Boolean).map((e) => ({ ...e })));
      const on = S.follow === key;
      for (const o of OFFSETS) {
        for (let k = 0; k + 1 < pts.length; k++) {
          const a = pts[k];
          const b = pts[k + 1];
          trackG.addLayer(L.polyline([[a.lat, a.lon + o], [b.lat, b.lon + o]], {
            renderer: trackR, color: cls(a.cls).hex, weight: on ? 2 : 1.75, opacity: 1, interactive: false,
          }));
        }
        for (const a of pts) {
          trackG.addLayer(L.circleMarker([a.lat, a.lon + o], {
            renderer: trackR, radius: 2, weight: 0.75, color: '#0d0d0f', fillColor: cls(a.cls).hex, fillOpacity: 1, interactive: false,
          }));
        }
      }
    }
  }
  if (S.index) stormsFrame(S.i);
}

function drawTails() {
  tailG.clearLayers();
  if (!S.layers.tracks || !S.index) return;
  const i = S.i;
  const focus = focusKeys();
  const byHex = new Map();
  for (const s of ST.shown) {
    if (!s.at[i] || focus.includes(s.key)) continue;
    const pts = [];
    for (let k = i; k >= 0 && k >= i - TAIL_STEPS && s.at[k]; k--) pts.unshift({ ...s.at[k] });
    if (pts.length < 2) continue;
    unwrap(pts);
    for (let k = 0; k + 1 < pts.length; k++) {
      const hex = cls(pts[k].cls).hex;
      if (!byHex.has(hex)) byHex.set(hex, []);
      byHex.get(hex).push([pts[k], pts[k + 1]]);
    }
  }
  for (const [hex, segs] of byHex) {
    for (const o of S.offs) {
      tailG.addLayer(L.polyline(segs.map(([a, b]) => [[a.lat, a.lon + o], [b.lat, b.lon + o]]), {
        renderer: tailR, color: hex, weight: 1.25, opacity: 0.55, interactive: false, lineCap: 'round',
      }));
    }
  }
}

// Names at the storms' positions: the daily collection's names and the
// followed or hovered storm always; the L numbers only from LABEL_ZOOM.
function drawNames() {
  nameG.clearLayers();
  if (!S.layers.tracks || !S.index) return;
  const focus = focusKeys();
  for (const s of ST.shown) {
    const e = s.at[S.i];
    if (!e) continue;
    const on = focus.includes(s.key);
    const cl = `storm-name${s.generic && !on ? ' generic' : ''}${on ? ' on' : ''}`;
    for (const o of S.offs) {
      nameG.addLayer(L.marker([e.lat, e.lon + o], {
        icon: L.divIcon({ className: cl, iconSize: [0, 0], html: `<span>${esc(s.label)}</span>` }),
        interactive: false, keyboard: false, zIndexOffset: -100,
      }));
    }
  }
}

function hoverStorm(key, fromMap = false) {
  if (key === ST.hover) return;
  const was = ST.hover;
  ST.hover = key;
  for (const k of [was, key]) {
    const s = findStorm(k);
    if (s) updateEntry(s, S.i);
  }
  drawTracks();
  if (key && fromMap && !ST.selected) reveal(key);  // a selection keeps the panel where it is
}

// A click on a low selects its storm: the whole track on the map, and
// its entry highlighted and scrolled into view in the panel (opened on a
// wide screen). The selection moves with the card as frames advance and
// clears with it.
function selectStorm(key, { show: reveal_ = true } = {}) {
  const was = ST.selected;
  if (key !== was) {
    ST.selected = key;
    const s = findStorm(key);
    if (s && !ST.shown.includes(s)) applyFilter();
    else if (!key && was && findStorm(was) && !passes(findStorm(was))) applyFilter();
    for (const k of [was, key]) {
      const t = findStorm(k);
      if (t) updateEntry(t, S.i);
    }
    drawTracks();
  }
  if (!key || !reveal_) return;
  if (!narrow() && !document.body.classList.contains('storms-open')) setStormsOpen(true);
  requestAnimationFrame(() => reveal(key));
}

/* ---------- follow mode ---------- */

function follow(q, { quiet = false } = {}) {
  const s = findStorm(q);
  if (!s) return false;
  S.follow = s.key;
  $('follow-name').textContent = s.label;
  $('follow').hidden = false;
  if (narrow()) setStormsOpen(false);
  if (!ST.shown.includes(s)) applyFilter();
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
  requestAnimationFrame(() => reveal(s.key, false));
  writeHash();
  return true;
}

function unfollow() {
  if (!S.follow) return;
  const s = findStorm(S.follow);
  S.follow = null;
  $('follow').hidden = true;
  if (s && !passes(s)) applyFilter();
  drawTracks();
  if (!$('card').hidden && S.sel?.c) renderCard(S.sel.c, stormOf(S.sel.c, S.i));
  writeHash();
}

function followFrame() {
  const e = findStorm(S.follow)?.at[S.i];
  if (e) centerOn(e.lat, e.lon);
}

function toggleFollow() {
  if (S.follow) { unfollow(); return; }
  const s = (S.sel?.c && stormOf(S.sel.c, S.i)) || findStorm(ST.hover) ||
    ST.shown.find((x) => x.at[S.i]) || ST.shown[0];
  if (s) follow(s.key);
}
