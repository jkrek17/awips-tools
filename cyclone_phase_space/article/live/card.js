/* Cyclone Phase Space, live: reading the values.
   The legend card (drawn from legend.json's colormap stops), the hover
   tooltip at a low, and the phase space card: the selected or followed
   low with its whole track in the 3-D phase space (space3d.js), which
   moves with the timeline. Uses the globals from app.js and storms.js. */
'use strict';

/* ---------- colormaps ---------- */

// If legend.json is missing: a subset of the shipped colormaps' stops.
const CORE_STOPS = [[-300, '#0d2699', 1], [-100, '#6695db', 1], [-60, '#99bae2', 0.4], [-20, '#ccdbeb', 0],
  [20, '#edd6c3', 0], [60, '#e6b690', 0.4], [100, '#db9564', 1], [300, '#990d0d', 1]];
const FALLBACK_STOPS = {
  hvtl: CORE_STOPS, hvtu: CORE_STOPS,
  hb: [[-40, '#006166', 1], [-13.33, '#5fb2b4', 1], [-8, '#71c2c3', 0.4], [-2.67, '#83d1d1', 0],
    [2.67, '#ecace6', 0], [8, '#da96d8', 0.4], [13.33, '#c880ca', 1], [40, '#6b0a80', 1]],
};

function stopsOf(f) {
  const stops = S.legend?.rasters?.[f]?.stops || S.legend?.stops?.[f] || FALLBACK_STOPS[f];
  const range = S.legend?.rasters?.[f]?.range || S.legend?.ranges?.[f] || S.index?.ranges?.[f] || (f === 'hb' ? [-40, 40] : [-300, 300]);
  return { stops: stops?.length ? [...stops].sort((a, b) => a[0] - b[0]) : null, range };
}

// The product's color at a value, linear between the legend stops.
function rampColor(f, v) {
  const { stops, range } = stopsOf(f);
  if (!stops || blank(v)) return '#8a8a86';
  const x = Math.max(range[0], Math.min(range[1], +v));
  let k = 0;
  while (k < stops.length - 2 && x > stops[k + 1][0]) k++;
  const [v0, h0] = stops[k];
  const [v1, h1] = stops[k + 1];
  const t = v1 === v0 ? 0 : Math.max(0, Math.min(1, (x - v0) / (v1 - v0)));
  const a = parseInt(h0.slice(1), 16);
  const b = parseInt(h1.slice(1), 16);
  const ch = (s) => Math.round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t);
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}

// The fade band of the colormaps since the WebP fields (index.json
// raster.fade, a fraction of the half range): clear within 0.3 of it of
// zero, full color from its edge. Null for older exports, whose stops carry
// their own transparent band.
function fadeBand(f) {
  const fade = +S.index?.raster?.fade;
  if (!(fade > 0)) return null;
  const { range: [lo, hi] } = stopsOf(f);
  const half = (hi - lo) / 2;
  return { clear: 0.3 * fade * half, full: fade * half };
}

// The ramp as drawn: every stop with its own alpha, and, where the fade
// band applies, its clear and full-color edges added, since the stops
// straddle zero and a gradient between them would tint the band.
function drawnStops(f) {
  const { stops } = stopsOf(f);
  if (!stops) return null;
  const out = stops.map(([v, hex, a]) => [v, rgba(hex, a ?? 1)]);
  const band = fadeBand(f);
  if (!band) return out;
  const side = (sgn) => stops.filter(([v]) => v * sgn > 0).sort((x, y) => Math.abs(x[0]) - Math.abs(y[0]));
  for (const sgn of [-1, 1]) {
    const inner = side(sgn)[0];
    if (!inner) continue;
    const full = sgn * band.full;
    const c = rampColor(f, full).replace(/^rgb\((.*)\)$/, 'rgba($1,1)');
    out.push([full, c], [sgn * band.clear, rgba(inner[1], 0)]);
  }
  const keep = out.filter(([v]) => Math.abs(v) >= band.clear - 1e-9);
  return keep.sort((x, y) => x[0] - y[0]);
}

function gradient(f) {
  const { range: [lo, hi] } = stopsOf(f);
  const st = drawnStops(f);
  if (!st) return 'transparent';
  const pct = (v) => (((v - lo) / (hi - lo)) * 100).toFixed(2);
  return `linear-gradient(to right, ${st.map(([v, c]) => `${c} ${pct(v)}%`).join(', ')})`;
}

// The clear band in words, from the fade band or the older exports' own.
function clearText(f) {
  const band = fadeBand(f);
  if (!band) return CLEAR_OLD[f];
  const m = (v) => fmt(v, Number.isInteger(+v.toFixed(1)) ? 0 : 1, 'm');
  return `Clear within ${m(band.clear)} of zero, full color from ${m(band.full)}.`;
}

/* ---------- legend ---------- */

// The small swatch of each field in the layers panel.
function paintRamps() {
  const list = [...S.classes.values()];
  document.querySelectorAll('[data-ramp]').forEach((el) => {
    const f = el.dataset.ramp;
    el.style.background = f === 'class'
      ? `linear-gradient(90deg, ${list.map((c, k) => `${c.hex} ${(k / list.length * 100).toFixed(1)}% ${((k + 1) / list.length * 100).toFixed(1)}%`).join(', ')})`
      : gradient(f);
  });
}

const RAMP_LABELS = { hb: [-40, -20, 0, 10, 20, 40], hvtl: [-300, -200, -100, 0, 100, 200, 300], hvtu: [-300, -200, -100, 0, 100, 200, 300] };

function renderLegend() {
  const f = S.field;
  const el = $('legend');
  let h;
  if (f === 'class') {
    h = `<div class="legend-head"><span>${TITLES.class}</span></div><ul class="legend-classes">${[...S.classes.values()].map((c) =>
      `<li title="${esc(c.name)}"><i style="--c:${c.hex}"></i><b>${c.code}</b>${esc(SHORT[c.code] ?? c.name)}</li>`).join('')}</ul>`;
  } else {
    const { range: [lo, hi] } = stopsOf(f);
    const units = S.legend?.units?.[f] || 'm';
    const pct = (v) => (((v - lo) / (hi - lo)) * 100).toFixed(2);
    const onset = f === 'hb' ? `<b class="onset" style="left:${pct(FIG1.onset)}%" title="Hart's onset, 10 m"></b>` : '';
    h = `<div class="legend-head"><span>${TITLES[f]}</span><span class="unit">${esc(units)}</span></div>` +
      (f === 'hb' ? `<p class="legend-sub">${B_FIELD_NOTE}</p>` : '') +
      `<div class="legend-bar ramp"><span style="background:${gradient(f)}"></span>${onset}</div>` +
      `<div class="legend-labels">${RAMP_LABELS[f].map((v) => `<span style="left:${pct(v)}%">${fmt(v)}</span>`).join('')}</div>` +
      `<p class="legend-ends"><span>${MINUS} ${ENDS[f][0]}</span><span>${ENDS[f][1]} +</span></p>`;
  }
  const help = f === 'class' ? HELP[f] : `${HELP[f]} ${clearText(f)}`;
  const dim = +S.index?.raster?.mask_dim;
  const fade = f !== 'class' && fadeOn() ? ` Faded to ${Math.round((dim > 0 ? dim : 0.35) * 100)}% beyond about 300 km from the lows.` : '';
  h += `<p class="legend-note">${esc(help)}${fade}</p>`;
  const keys = [];
  if (ST.trackB) {
    keys.push('<span class="full"><i class="k-dot"></i>Low center, by class; a tracked low\'s B is from its own motion, the field\'s from the steering flow</span>',
      '<span class="full"><i class="k-ring"></i>The field\'s class where it differs, so a dot may not match the field under it</span>');
  } else {
    keys.push('<span><i class="k-dot"></i>Low center, by class</span>');
  }
  if (S.layers.contours) keys.push(`<span><i style="height:6px;vertical-align:1px;border:0;border-radius:2px;background:linear-gradient(#cfdbe8 2px,#0b1220 2px,#0b1220 4px,#cfdbe8 4px)"></i>MSLP, ${WIDE_CINT} hPa, bold 16</span>`);
  if (S.layers.z500 && hasUpper('z500')) keys.push('<span><i style="border-top:2px solid #6b8cff"></i>500 mb height, 6 dam</span>');
  if (S.layers.thick && hasUpper('thick')) keys.push(`<span><i style="border-top:2px dashed #ef4444"></i>Thickness, red above ${THICK_LINE}, blue below</span>`);
  if (S.layers.jet && hasUpper('jet')) {
    const j = S.index.jet || { bands_kt: [70, 90, 110, 130], colors: ['#b9f6ca', '#5fdc8a', '#1f9d55', '#f5d90a'] };
    keys.push(`<span class="wide">250 mb jet, kt ${j.bands_kt.map((b, k) => `<i style="width:10px;height:8px;border:0;border-radius:2px;margin:0 3px 0 6px;vertical-align:-1px;background:${j.colors[k]}"></i>${b}${k === j.bands_kt.length - 1 ? '+' : ''}`).join('')}</span>`);
  }
  if (S.layers.circles) keys.push('<span><i class="k-halo"></i>200 km circle</span>');
  if (S.layers.tracks) keys.push('<span><i style="border-top:2px solid #fad91a"></i>Selected track, by class</span>',
    '<span><i style="border-top:1px solid rgba(231,238,248,0.55)"></i>Last 24 h of motion</span>');
  if (S.layers.footprint) keys.push('<span><i style="border-top:1px dashed #e7eef8"></i>Product footprint</span>');
  if (S.layers.terrain) keys.push('<span><i class="k-terrain"></i>Terrain minimum</span>');
  h += `<div class="legend-keys">${keys.join('')}</div>`;
  el.innerHTML = h;
}

/* ---------- tooltip ---------- */

// The class dot, with the differing-class ring and its title where the
// class from the storm's motion and the field's steering-flow class disagree.
function clsDot(e) {
  const hex = cls(clsOf(e)).hex;
  return classDiffers(e)
    ? `<i class="alt" style="--c:${hex};--c2:${cls(e.cls).hex}" title="${esc(diffTitle(e))}"></i>`
    : `<i style="--c:${hex}"></i>`;
}

// Motion as "14 kt toward NE (045°)", from spd and hdg.
function motionText(e) {
  if (blank(e?.spd)) return '';
  const v = +e.spd;
  if (v < 1) return 'nearly stationary';
  return `${fmt(v, 0, 'kt')}${blank(e.hdg) ? '' : ` toward ${compass(e.hdg)} (${pad(Math.round(+e.hdg) % 360, 3)}°)`}`;
}

function lowTip(c) {
  const k = cls(clsOf(c));
  const s = stormOf(c, S.i);
  const row = (f, d, sep = '') => `<tr${sep}><td>${TERM[f].name} (${TERM[f].sym})</td><td>${fmt(c[f], d, 'm', true)}</td></tr>`;
  const tb = trackB(c);
  // B: from the storm's motion where there is one, the field's beside it
  let b = row('hb', 1);
  if (tb) {
    b = `<tr><td>B, storm motion</td><td>${fmt(c.hbt, 1, 'm', true)}</td></tr>` +
      `<tr class="dim"><td>B, steering flow (field)</td><td>${fmt(c.hb, 1, 'm', true)}</td></tr>`;
  } else if (ST.trackB) {
    b = `<tr><td>B, steering flow (field)</td><td>${fmt(c.hb, 1, 'm', true)}</td></tr>`;
  }
  const alt = classDiffers(c)
    ? `<p class="tip-alt">Field, steering flow: ${esc(SHORT[c.cls] ?? cls(c.cls).name)} (${c.cls})</p>` : '';
  const move = blank(c.spd) ? '' : `<tr><td>Motion</td><td>${esc(motionText(c))}</td></tr>`;
  return `<div class="h">${s ? esc(s.label) : 'Untracked low'}${s?.fsu != null ? `, FSU ${esc(s.fsu)}` : ''}</div>
    <p class="tip-cls">${clsDot(c)}${esc(k.name)}</p>${alt}
    <table><tr><td>Central pressure</td><td>${hpa(c.mslp)}</td></tr>
    <tr><td>Center</td><td>${pos(c.lat, c.lon)}</td></tr>${move}
    ${row('hvtl', 0, ' class="sep"')}${row('hvtu', 0)}${b}</table>` +
    (c.terrain ? `<div class="note-line">Terrain minimum${blank(c.psfc) ? '' : `, surface ${fmt(c.psfc, 0, 'hPa')}`}: a false low over high ground</div>` : '') +
    (s ? '<div class="tip-hint">Click for its track in the phase space</div>' : '');
}

/* ---------- the phase space card ---------- */

const PH = { key: null, view: null };

function selectLow(c, { center = false, zoom } = {}) {
  const s = stormOf(c, S.i);
  if (S.follow && (!s || s.key !== S.follow)) unfollow();
  S.sel = { lat: c.lat, lon: c.lon, c };
  setSideOpen(true);
  selectStorm(s ? s.key : null);
  renderCard(c, s);
  drawSelection();
  renderDeepest();
  if (center) centerOn(c.lat, c.lon, zoom);
}

// On a new frame: the followed storm's center, or the low nearest the last one.
function refreshCard() {
  if (S.follow) {
    const s = findStorm(S.follow);
    const e = s?.at[S.i];
    const c = e ? centerOf(s, e) : null;
    if (e) Object.assign(S.sel ??= {}, { lat: e.lat, lon: e.lon });
    if (S.sel) S.sel.c = c;
    renderCard(c, s, !e);
    return;
  }
  if (!S.sel) return;
  // a selected track keeps its card through hours it is absent
  const st = findStorm(ST.selected);
  const e = st?.at[S.i];
  let c;
  if (st) c = e ? centerOf(st, e) : null;
  else c = nearest(S.centers.filter(shown), S.sel.lat, S.sel.lon, 2 * MATCH_KM);
  S.sel.c = c;
  if (c) { S.sel.lat = c.lat; S.sel.lon = c.lon; }
  const s = st || (c ? stormOf(c, S.i) : null);
  if (s && s.key !== ST.selected) selectStorm(s.key);
  renderCard(c, s, !!st && !e);
}

function closeCard() {
  S.sel = null;
  unfollow();
  selectStorm(null);
  renderCard(null, null);
  drawSelection();
  renderDeepest();
}

function phaseFrame() {
  PH.view?.frame();
}

// The low's values at this hour for the card: the map center's, with the
// track point's motion where it is the same low (the centers carry no
// heading).
function cardVals(c, s) {
  const e = s?.track ? s.at[S.i] : null;
  if (!e || (e.id != null && c.id != null && e.id !== c.id)) return c;
  return { ...c, hbt: c.hbt ?? e.hbt, clst: c.clst ?? e.clst, spd: c.spd ?? e.spd, hdg: c.hdg ?? e.hdg };
}

// B on the card: Hart's, from the storm's own motion, as the main line, and
// the field's steering-flow B under it, smaller, with its class where
// that differs; then the motion. Older exports carry only the field's B,
// which the 3-D readout shows, so they get no lines here.
function bLines(v, s) {
  if (!ST.trackB) return '';
  const short = (k) => `${esc(SHORT[k] ?? cls(k).name)} (${k})`;
  const rows = [];
  if (trackB(v)) {
    rows.push(`<dt>B, storm motion</dt><dd><b>${fmt(v.hbt, 1, 'm', true)}</b>${clsOf(v) == null ? '' : `, ${short(clsOf(v))}`}</dd>`);
    const diff = classDiffers(v);
    if (diff || fmt(v.hb, 1) !== fmt(v.hbt, 1)) {
      rows.push(`<dt class="alt">B, steering flow (field)</dt><dd class="alt"><b>${fmt(v.hb, 1, 'm', true)}</b>` +
        (diff ? `, <span class="alt-cls" title="${esc(diffTitle(v))}"><i style="--c2:${cls(v.cls).hex}"></i>${short(v.cls)}</span>` : ', same class') + '</dd>');
    }
  } else {
    rows.push(`<dt>B, steering flow (field)</dt><dd><b>${fmt(v.hb, 1, 'm', true)}</b>` +
      `${v.cls == null ? '' : `, ${short(v.cls)}`}${s?.track ? '<span class="ph-b-note">no B from the motion at this hour</span>' : ''}</dd>`);
  }
  const m = motionText(v);
  if (m) rows.push(`<dt>Motion</dt><dd>${esc(m)}</dd>`);
  return `<dl class="ph-b">${rows.join('')}</dl>`;
}

function renderCard(c, s, absent = false) {
  const body = $('ph-body');
  document.body.classList.toggle('has-sel', !!(c || s));
  if (!c && !s) {
    PH.view?.destroy();
    PH.view = null;
    PH.key = null;
    body.innerHTML = `<p class="ph-hint">Click a low on the map, or find one by name, to load its track into the 3-D phase space. ` +
      'The deepest lows at this hour are listed below.</p>';
    return;
  }
  // The head: the storm, and the low at the hour on screen.
  let head = body.querySelector('.ph-low');
  if (!head || PH.key !== (s?.key ?? null)) {
    PH.view?.destroy();
    PH.view = null;
    PH.key = s?.key ?? null;
    body.innerHTML = '<div class="ph-low"></div><div class="ph-cube"></div><p class="ph-links"></p>';
    head = body.querySelector('.ph-low');
    if (s && typeof Space3D !== 'undefined') PH.view = Space3D.create(body.querySelector('.ph-cube'), s);
  }
  const v = validAt(S.i);
  const when = `F${pad(S.index.hours[S.i], 3)}${v ? `, ${fmtDay(v)} ${pad(v.getUTCHours())} UTC` : ''}`;
  const cv = c ? cardVals(c, s) : null;
  const k = cv ? cls(clsOf(cv)) : null;
  const on = s && S.follow === s.key;
  const title = s
    ? `<div class="ph-title"><b></b>${s.fsu != null ? `<span class="tag">FSU ${esc(s.fsu)}</span>` : ''}
        <button type="button" class="btn btn-sm" id="ph-follow" aria-pressed="${on}" title="Keep this low centered as the hours change (F)">${on ? 'Following' : 'Follow'}</button></div>
       <p class="ph-sub">${esc(s.sub)}${s.generic || s.fsu != null ? '' : ', not on the FSU page'}</p>`
    : '<div class="ph-title"><b>Untracked low</b></div>';
  const now = c
    ? `<p class="ph-now"><span class="cls-chip">${clsDot(cv)}${esc(k.name)}</span>
        <span class="ph-mslp">${fmt(c.mslp, 1)}<small> hPa</small></span><span class="ph-where">${pos(c.lat, c.lon)} · ${when}</span></p>` +
      (s ? bLines(cv, s) : '') +
      (c.terrain ? `<p class="ph-warn">Terrain minimum: surface pressure ${blank(c.psfc) ? 'under 850 hPa' : fmt(c.psfc, 0, 'hPa')}; a false low over high ground.</p>` : '')
    : `<p class="ph-now muted">${absent ? `Not tracked at ${when}.` : `No closed low near the last position at ${when}.`}</p>`;
  const lone = !s && c
    ? `<p class="ph-vals">${TERM.hvtl.sym} <b>${fmt(c.hvtl, 0, '', true)}</b> ${TERM.hvtu.sym} <b>${fmt(c.hvtu, 0, '', true)}</b> B <b>${fmt(c.hb, 1, '', true)}</b> m</p>
       <p class="ph-hint">This low is not on a track in this run, so it has no path through the phase space${ST.trackB ? ', and its B is the field\'s, across the steering flow' : ''}.</p>`
    : '';
  head.innerHTML = title + now + lone;
  if (s) head.querySelector('.ph-title b').textContent = s.label;
  head.querySelector('#ph-follow')?.addEventListener('click', () => (S.follow === s.key ? unfollow() : follow(s.key)));
  const link = (u, label) => (u ? `<a href="${esc(new URL(u, S.base).href)}" target="_blank" rel="noopener">${label}</a>` : '');
  const links = body.querySelector('.ph-links');
  links.innerHTML = s && (s.phase || s.compare) ? [link(s.phase, 'Phase diagram'), link(s.compare, 'Compare with FSU')].filter(Boolean).join(' · ') : '';
  links.hidden = !links.innerHTML;
  PH.view?.frame();
}
