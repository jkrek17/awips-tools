/* Cyclone Phase Space, live: reading the values.
   The readout card at a selected low (class, MSLP, the three CPS terms as
   bars on the colormaps' own ranges, the index), the hover tooltip, and
   the field legends drawn from legend.json's colormap stops. Uses the
   globals from app.js. */
'use strict';

// Bar scales: the colormaps' ranges, with ticks at the reading thresholds.
const BARS = {
  hvtl: { lo: -300, hi: 300, ticks: [-300, -100, 0, 100, 300], d: 0 },
  hvtu: { lo: -300, hi: 300, ticks: [-300, -100, 0, 100, 300], d: 0 },
  hb: { lo: -40, hi: 40, ticks: [-40, -10, 0, 10, 40], d: 1 },
  idx: { lo: -3, hi: 3, ticks: [-3, -2, -1, 0, 1, 2, 3], d: 1 },
};

/* ---------- legend ---------- */

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

// A ramp with a tick at every colormap stop and labels at chosen stops.
// The stops' own alpha is kept, so the transparent band reads as the panel.
function rampHTML(f, labels) {
  const { stops, range: [lo, hi] } = stopsOf(f);
  if (!stops) return '';
  const pct = (v) => (((v - lo) / (hi - lo)) * 100).toFixed(2);
  const grad = stops.map(([v, hex, a]) => `${rgba(hex, a ?? 1)} ${pct(v)}%`).join(', ');
  const ticks = stops.map(([v]) => `<i style="left:${pct(v)}%"></i>`).join('');
  const lab = labels.map((v) => `<span style="left:${pct(v)}%">${fmt(v, Number.isInteger(v) ? 0 : 1)}</span>`).join('');
  const onset = f === 'hb' ? `<b class="onset" style="left:${pct(10)}%"></b>` : '';
  return `<span class="ramp"><span class="ramp-fill" style="background:linear-gradient(to right, ${grad})"></span>${onset}</span>` +
    `<span class="ramp-ticks">${ticks}</span><span class="ramp-labels">${lab}</span>`;
}

function renderLegend() {
  const f = S.field;
  const inline = $('legend-inline');
  const units = S.legend?.units?.[f] || 'm';
  const cmap = /\((CPS_[A-Za-z]+)\)/.exec(S.legend?.labels?.[f] || '')?.[1];
  $('key-title').textContent = TITLES[f];
  $('key-help').textContent = HELP[f];
  if (f === 'class') {
    const list = [...S.classes.values()];
    inline.innerHTML = `<span class="classes-inline">${list.map((c) =>
      `<span><i style="--c:${c.hex}"></i>${c.code}</span>`).join('')}</span>`;
    $('key-scale').innerHTML = `<ul class="classes">${list.map((c) =>
      `<li><i style="--c:${c.hex}"></i><span class="code">${c.code}</span>${esc(c.name)}</li>`).join('')}</ul>`;
    return;
  }
  const { stops, range: [lo, hi] } = stopsOf(f);
  // Inline: the ends, the first fully opaque stops and zero; the key: every other stop.
  const solid = stops?.find(([v, , a]) => v > 0 && (a ?? 1) >= 1)?.[0];
  const short = f === 'hb' ? [lo, 0, 10, hi] : [lo, solid ? -solid : -100, 0, solid || 100, hi];
  // The key labels symmetric pairs of real stops (every other stop if the colormap differs).
  const want = f === 'hb' ? [-40, -24, -8, 8, 24, 40] : [-300, -180, -100, -20, 20, 100, 180, 300];
  const real = want.filter((w) => stops?.some(([v]) => Math.abs(v - w) < 0.01));
  const full = real.length === want.length ? real
    : (stops || []).filter((_, k) => k % 2 === 0).map(([v]) => +v.toFixed(1));
  inline.innerHTML = `<span class="ramp-wrap">${rampHTML(f, short)}</span><span class="ramp-unit">${esc(units)}</span>`;
  $('key-scale').innerHTML = `<div class="ramp-wrap big">${rampHTML(f, full)}</div>
    <p class="ramp-ends"><span>${MINUS} ${ENDS[f][0]}</span><span>${ENDS[f][1]} +</span></p>
    <p class="ramp-note">${fmt(lo)} to ${fmt(hi, 0, '', true)} ${esc(units)}${cmap ? ` on ${cmap}` : ''}; a tick at every colormap stop${f === 'hb' ? '; the bar marks Hart\'s 10 m onset line' : ''}.</p>`;
}

/* ---------- tooltip ---------- */

function lowTip(c) {
  const k = cls(c.cls);
  return `<span class="tip-cls"><i style="--c:${k.hex}"></i>${esc(k.name)}</span>
    <span class="tip-row"><b>${hpa(c.mslp)}</b><span>MSLP</span></span>
    <span class="tip-row"><b>${fmt(c.hb, 1, 'm', true)}</b><span>B</span></span>` +
    (c.terrain ? `<span class="tip-note">Terrain minimum${blank(c.psfc) ? '' : `, surface ${fmt(c.psfc, 0, 'hPa')}`}</span>` : '');
}

/* ---------- card ---------- */

function selectLow(c, { center = false, zoom } = {}) {
  const s = matchStorm(c, S.i);
  if (S.follow && (!s || s.name !== S.follow)) unfollow();
  S.sel = { lat: c.lat, lon: c.lon, c };
  if (narrow()) setStormsOpen(false);
  renderCard(c, s);
  drawSelection();
  if (center) centerOn(c.lat, c.lon, zoom);
}

// On a new frame: the followed storm's center, or the low nearest the last one.
function refreshCard() {
  if (S.follow) {
    const s = ST.byName.get(S.follow);
    const e = s?.at[S.i];
    const c = e ? nearest(S.centers, e.lat, e.lon, MATCH_KM) : null;
    if (e) Object.assign(S.sel ??= {}, { lat: e.lat, lon: e.lon });
    if (S.sel) S.sel.c = c;
    renderCard(c, s, !e);
    return;
  }
  if (!S.sel) return;
  const c = nearest(S.centers.filter(shown), S.sel.lat, S.sel.lon, 2 * MATCH_KM);
  S.sel.c = c;
  if (c) { S.sel.lat = c.lat; S.sel.lon = c.lon; }
  renderCard(c, c ? matchStorm(c, S.i) : null);
}

function closeCard() {
  if ($('card').hidden) return;
  $('card').hidden = true;
  dropInsets();
  S.sel = null;
  unfollow();
  drawSelection();
  basemap?.edges();
}

function barHTML(key, label, v, axis = true) {
  const b = BARS[key];
  const pct = (x) => ((x - b.lo) / (b.hi - b.lo)) * 100;
  const z = pct(0);
  let fill = '';
  let clip = '';
  if (!blank(v)) {
    const x = Math.max(b.lo, Math.min(b.hi, +v));
    const p = pct(x);
    const color = key === 'idx' ? rampColor('hvtl', x * 100) : rampColor(key, x);
    fill = `<span class="fill" style="left:${Math.min(p, z).toFixed(2)}%;width:${Math.abs(p - z).toFixed(2)}%;background:${color}"></span>`;
    if (x !== +v) clip = `<span class="clip ${x > 0 ? 'hi' : 'lo'}" title="beyond the scale"></span>`;
  }
  const ticks = b.ticks.map((t) => `<i class="${t === 0 ? 'z' : ''}${key === 'hb' && t === 10 ? ' onset' : ''}" style="left:${pct(t).toFixed(2)}%"></i>`).join('');
  const labs = axis ? b.ticks.filter((t) => key !== 'idx' || t % 3 === 0)
    .map((t) => `<span style="left:${pct(t).toFixed(2)}%">${fmt(t)}</span>`).join('') : '';
  const unit = key === 'idx' ? '' : 'm';
  return `<div class="brow">
      <span class="blab">${label}</span>
      <span class="btrack">${ticks}${fill}${clip}</span>
      <span class="bval">${fmt(v, b.d, unit, true)}</span>
      ${axis ? `<span class="bticks">${labs}</span>` : ''}
    </div>`;
}

function renderCard(c, s, absent = false) {
  const card = $('card');
  const link = (u, label) => (u ? `<a href="${esc(new URL(u, S.base).href)}" target="_blank" rel="noopener">${label}</a>` : '');
  const v = validAt(S.i);
  const when = `F${pad(S.index.hours[S.i], 3)}${v ? `, ${fmtDay(v)} ${pad(v.getUTCHours())} UTC` : ''}`;
  const k = c ? cls(c.cls) : null;
  const head = k
    ? `<span class="cls-chip"><i style="--c:${k.hex}"></i><span class="code">${k.code ?? ''}</span>${esc(k.name)}</span>`
    : `<span class="cls-chip muted">${absent ? 'Not tracked at this hour' : 'No closed low here at this hour'}</span>`;
  const storm = s
    ? `<p class="card-name"><b></b><span>${s.fsu != null ? `FSU ${esc(s.fsu)}` : 'not on the FSU page'}</span>
      <button type="button" class="btn small" id="card-follow" aria-pressed="${S.follow === s.name}">${S.follow === s.name ? 'Following' : 'Follow'}</button></p>`
    : `<p class="card-name"><span>${c ? 'Untracked low' : ''}</span></p>`;
  const body = c ? `
    <div class="card-main">
      <span class="mslp">${fmt(c.mslp, 1)}<small> hPa</small></span>
      <span class="where">${pos(c.lat, c.lon)}<br>${when}</span>
    </div>
    ${c.terrain ? `<p class="card-warn">Terrain minimum: surface pressure ${blank(c.psfc) ? 'under 850 hPa' : fmt(c.psfc, 0, 'hPa')}; a false low over high ground.</p>` : ''}
    <div class="bars">
      ${barHTML('hvtl', 'HVTL', c.hvtl, false)}
      ${barHTML('hvtu', 'HVTU', c.hvtu)}
      ${barHTML('hb', 'HB', c.hb)}
      ${barHTML('idx', 'Index', c.idx)}
    </div>
    <p class="card-foot">HVTL, HVTU: ${MINUS}V<sub>T</sub><sup>L</sup>, ${MINUS}V<sub>T</sub><sup>U</sup>, warm positive. HB: B, onset at 10 m.</p>`
    : `<p class="card-empty">${absent ? `${esc(s?.label)} has no tracked point at ${when}.` : `Nothing within ${2 * MATCH_KM} km of the last position at ${when}.`}</p>`;
  const links = s && (s.phase || s.compare) ? `<p class="card-links">${link(s.phase, 'Phase diagram')}${link(s.compare, 'Compare with FSU')}</p>` : '';
  card.innerHTML = `<div class="card-head">${head}
      <button type="button" class="x" id="card-close" aria-label="Close the readout"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6"/></svg></button>
    </div>${storm}${body}${links}`;
  if (s) card.querySelector('.card-name b').textContent = s.label;
  card.querySelector('#card-close').addEventListener('click', closeCard);
  card.querySelector('#card-follow')?.addEventListener('click', () => (S.follow === s.name ? unfollow() : follow(s.name)));
  const was = card.hidden;
  card.hidden = false;
  if (was || narrow()) dropInsets();
  if (was) basemap?.edges();
}
