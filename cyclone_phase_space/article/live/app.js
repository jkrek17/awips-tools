/* Cyclone Phase Space, live.
   A Leaflet map of the daily CPS export: class blobs, low centers, MSLP
   contours, the HB / HVTL / HVTU rasters and storm tracks, animated over
   the forecast hours of the latest cycle. Plain ES2020, no build step. */
'use strict';

const DEFAULT_DATA = 'https://raw.githubusercontent.com/jkrek17/awips-tools/cps-live/latest/';
const LABEL_ZOOM = 4;           // MSLP labels at centers from this zoom
const SPEED = 700;               // ms per frame while playing
const MAX_RASTER_FRAMES = 12;    // decoded raster frames kept in memory
const MATCH_KM = 300;            // center to tracked storm matching radius
const OFFSETS = [-360, 0, 360];  // world copies, so overlays wrap the dateline
const RASTERS = ['hb', 'hvtl', 'hvtu'];
const FIELDS = ['class', ...RASTERS];

// Display names for the class codes; hex always comes from legend.json.
const CLASS_NAMES = [
  'Symmetric deep warm core', 'Symmetric shallow warm core',
  'Asymmetric deep warm core', 'Asymmetric shallow warm core',
  'Asymmetric cold core', 'Symmetric cold core', 'Shallow cold core',
];
const FALLBACK_HEX = ['#d92626', '#cc33bf', '#fad91a', '#33ad40', '#2680e6', '#5938b8', '#b8b8b2'];

const TITLES = {
  class: 'Class at the low center',
  hb: 'HB, thermal asymmetry',
  hvtl: 'HVTL, lower thermal wind',
  hvtu: 'HVTU, upper thermal wind',
};
const ENDS = {
  hb: ['warm air left', 'warm air right'],
  hvtl: ['cold core', 'warm core'],
  hvtu: ['cold aloft', 'warm aloft'],
};
// One line of reading help per mode, from the user guide.
const HELP = {
  class: 'Read the class at the center dot, never the blob edge. A transition runs red, yellow, green, blue (codes 0, 2, 3, 4).',
  hb: 'Magenta: warm air to the right of the deep-layer flow, the frontal geometry; teal: warm air on the left. More than 10 m at a low center is asymmetric.',
  hvtl: 'Red is a warm lower core, blue a cold one. A hurricane reads +100 to +300; a center falling below 0 marks transition complete.',
  hvtu: 'Red is a warm upper core, blue is cold aloft. The upper core usually turns blue first as a transition gets under way.',
};

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const $ = (id) => document.getElementById(id);
const pad = (n, w = 2) => String(n).padStart(w, '0');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const S = {
  base: dataBase(), index: null, legend: null, classes: new Map(),
  i: 0, field: 'class', playing: false, timer: 0, token: 0,
  opacity: 0.7, basemap: 'plain', openId: null, redrawing: false, bust: '',
};

/* ---------- small utilities ---------- */

function dataBase() {
  const q = new URLSearchParams(location.search).get('data');
  let u = new URL(q || DEFAULT_DATA, location.href).href;
  if (/\.json$/i.test(u)) u = u.replace(/[^/]*$/, '');
  return u.endsWith('/') ? u : u + '/';
}

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

// GeoJSON is small enough to keep for the whole session.
const jsonCache = new Map();
function getJSON(url) {
  if (!jsonCache.has(url)) {
    const p = fetchJSON(url);
    p.catch(() => jsonCache.delete(url));
    jsonCache.set(url, p);
  }
  return jsonCache.get(url);
}

// Preloaded raster images, evicted by frame beyond MAX_RASTER_FRAMES.
const imgCache = new Map();
const imgFrames = [];
function loadImg(url, h) {
  let e = imgCache.get(url);
  if (!e) {
    const im = new Image();
    im.decoding = 'async';
    const p = new Promise((res, rej) => {
      im.onload = () => res(url);
      im.onerror = () => rej(new Error(`image ${url}`));
    });
    im.src = url;
    e = { h, im, p };
    imgCache.set(url, e);
    p.catch(() => imgCache.delete(url));
  }
  const k = imgFrames.indexOf(h);
  if (k >= 0) imgFrames.splice(k, 1);
  imgFrames.push(h);
  while (imgFrames.length > MAX_RASTER_FRAMES) {
    const old = imgFrames.shift();
    for (const [u, v] of imgCache) if (v.h === old) imgCache.delete(u);
  }
  return e.p;
}

function frameDir(h) {
  const tpl = S.index.frames || 'frames/f{hhh}/';
  const dir = /\{h+\}/.test(tpl)
    ? tpl.replace(/\{(h+)\}/, (_, w) => pad(h, w.length))
    : `${tpl.replace(/\/?$/, '/')}f${pad(h, 3)}/`;
  return new URL(dir, S.base).href;
}
const fileUrl = (h, name) => frameDir(h) + name + S.bust;
const rasterUrl = (h, f) => fileUrl(h, `${f}.png`);

function km(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const dl = ((((lon2 - lon1) % 360) + 540) % 360 - 180) * r;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dl / 2) ** 2;
  return 12742 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function mixWhite(hex, t) {
  const n = parseInt(hex.slice(1), 16);
  const ch = (s) => Math.round(((n >> s) & 255) * (1 - t) + 255 * t);
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}
function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const cls = (code) => S.classes.get(code) || { code, name: 'No class (blank)', hex: '#8a8a86' };
const blank = (v) => v == null || Number.isNaN(+v);
const num = (v, d = 0) => (blank(v) ? 'blank' : (+v).toFixed(d));
const sgn = (v, d = 0) => (blank(v) ? 'blank' : `${+v > 0 ? '+' : ''}${(+v).toFixed(d)}`);
const unit = (s, u) => (s === 'blank' ? s : `${s} ${u}`);

function utc(d) {
  if (!d) return '';
  if (typeof d === 'string' && /^\d{10}$/.test(d)) {
    d = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T${d.slice(8, 10)}:00:00Z`;
  }
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? null : t;
}
function fmtValid(d) {
  return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}, ${pad(d.getUTCHours())} UTC`;
}
function fmtCycle(c) {
  const d = utc(c);
  return d ? `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${pad(d.getUTCHours())}Z` : String(c ?? '');
}
function fmtGenerated(g) {
  const d = utc(g);
  if (!d) return '';
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  const ago = mins < 90 ? `${Math.max(mins, 0)} min ago` : mins < 2880 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} days ago`;
  return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC (${ago})`;
}
function validAt(i) {
  const v = S.index.valid?.[i] && utc(S.index.valid[i]);
  if (v) return v;
  const c = utc(S.index.cycle);
  return c ? new Date(c.getTime() + S.index.hours[i] * 3600e3) : null;
}

let toastTimer = 0;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
}

/* ---------- map ---------- */

let map, basemap, contourG, blobG, centerG, trackG, nowG, contourR, blobR, trackR;
const rasterLayers = {};
const centerIndex = new Map();

function initMap(zoom) {
  map = L.map('map', {
    worldCopyJump: true, minZoom: 1, maxZoom: 10, zoomControl: false,
    center: [30, -40], zoom, zoomSnap: 0.5,
    maxBounds: [[-88, -1e5], [88, 1e5]], maxBoundsViscosity: 1,
  });
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  L.control.zoom({ position: 'bottomright' }).addTo(map);

  // Panes, bottom to top: rasters, contours, blobs, tracks, labels, centers.
  [['rasters', 350], ['contours', 380], ['blobs', 410], ['tracks', 420], ['labels', 450]]
    .forEach(([n, z]) => { map.createPane(n).style.zIndex = z; });
  map.getPane('labels').style.pointerEvents = 'none';

  basemap = CPSBasemap.create(map, { insets: chromeInsets });

  contourR = L.canvas({ pane: 'contours', padding: 0.3 });
  blobR = L.svg({ pane: 'blobs', padding: 0.3 });
  trackR = L.svg({ pane: 'tracks', padding: 0.3 });
  contourG = L.layerGroup().addTo(map);
  blobG = L.layerGroup().addTo(map);
  trackG = L.layerGroup().addTo(map);
  nowG = L.layerGroup().addTo(map);
  centerG = L.layerGroup().addTo(map);

  map.on('popupopen', (e) => { S.openId = e.popup._source?.options.cps ?? null; });
  map.on('popupclose', () => { if (!S.redrawing) S.openId = null; });
  const zoomClass = () => map.getContainer().classList.toggle('labels-off', map.getZoom() < LABEL_ZOOM);
  map.on('zoomend', zoomClass);
  zoomClass();
  map.on('dragstart', () => document.querySelectorAll('.basins .chip.on').forEach((c) => c.classList.remove('on')));
}

const shift = (o) => (c) => L.latLng(c[1], c[0] + o);

function setRaster(url) {
  for (const f of RASTERS) {
    const on = f === S.field && url;
    if (on && !rasterLayers[f]) {
      const [[s, w], [n, e]] = S.index.raster?.bounds || [[-85, -180], [85, 180]];
      rasterLayers[f] = OFFSETS.map((o) => L.imageOverlay(url, [[s, w + o], [n, e + o]],
        { pane: 'rasters', opacity: S.opacity, interactive: false, alt: `${TITLES[f]} field` }));
    }
    for (const ov of rasterLayers[f] || []) {
      if (on) {
        if (ov._url !== url) ov.setUrl(url);
        if (!map.hasLayer(ov)) ov.addTo(map);
      } else if (map.hasLayer(ov)) {
        map.removeLayer(ov);
      }
    }
  }
}

function drawContours(fc) {
  contourG.clearLayers();
  if (!fc) return;
  const style = (f) => {
    const major = Math.round(f.properties.level) % 16 === 0;
    return major
      ? { color: '#e9e8e3', weight: 1.2, opacity: 0.55 }
      : { color: '#e9e8e3', weight: 1, opacity: 0.22 };
  };
  for (const o of OFFSETS) {
    contourG.addLayer(L.geoJSON(fc, { renderer: contourR, interactive: false, style, coordsToLatLng: shift(o) }));
  }
}

function drawBlobs(fc) {
  blobG.clearLayers();
  if (!fc) return;
  const blobs = { type: 'FeatureCollection', features: fc.features.filter((f) => f.geometry?.type !== 'Point') };
  for (const o of OFFSETS) {
    blobG.addLayer(L.geoJSON(blobs, {
      renderer: blobR,
      coordsToLatLng: shift(o),
      style: (f) => {
        const hex = cls(f.properties.cls).hex;
        return { color: mixWhite(hex, 0.35), weight: 1.5, opacity: 1, fillColor: hex, fillOpacity: 0.55, className: 'blob' };
      },
      onEachFeature: (f, l) => {
        l.on('add', () => { const el = l.getElement(); if (el) el.style.color = cls(f.properties.cls).hex; });
        l.on('click', () => { const m = centerIndex.get(`${f.properties.id}|${o}`); if (m) m.openPopup(); });
      },
    }));
  }
}

function centerIcon(p) {
  const hex = cls(p.cls).hex;
  return L.divIcon({
    className: 'ctr', iconSize: [10, 10], iconAnchor: [5, 5], popupAnchor: [0, -6],
    html: `<i style="--c:${hex}"></i>${blank(p.mslp) ? '' : `<b>${num(p.mslp)}</b>`}`,
  });
}

function drawCenters(fc, i) {
  centerG.clearLayers();
  centerIndex.clear();
  if (!fc) return;
  const bar = $('bar').getBoundingClientRect();
  const head = document.querySelector('.chiprow').getBoundingClientRect();
  const popupOpts = {
    maxWidth: 280, minWidth: 220,
    autoPanPaddingTopLeft: L.point(16, head.bottom + 16),
    autoPanPaddingBottomRight: L.point(16, innerHeight - bar.top + 16),
  };
  for (const f of fc.features) {
    if (f.geometry?.type !== 'Point') continue;
    const p = { ...f.properties };
    p.lon ??= f.geometry.coordinates[0];
    p.lat ??= f.geometry.coordinates[1];
    for (const o of OFFSETS) {
      const m = L.marker([p.lat, p.lon + o], {
        icon: centerIcon(p), riseOnHover: true, cps: { lat: p.lat, lon: p.lon, o },
        title: `${cls(p.cls).name}, ${num(p.mslp)} hPa`,
      }).bindPopup(() => card(p, i), popupOpts);
      centerG.addLayer(m);
      centerIndex.set(`${p.id}|${o}`, m);
    }
  }
}

function nearestCenter({ lat, lon, o }) {
  let best = null;
  let bd = 600;
  centerG.eachLayer((m) => {
    const c = m.options.cps;
    const d = c.o === o ? km(lat, lon, c.lat, c.lon) : Infinity;
    if (d < bd) { bd = d; best = m; }
  });
  return best;
}

// Storm points carry their own run's fhr, so match on valid time.
function atFrame(pt, i) {
  const v = validAt(i);
  const t = pt.valid && utc(pt.valid);
  return t && v ? Math.abs(t - v) < 60e3 : pt.fhr === S.index.hours[i];
}

function matchStorm(p, i) {
  let best = null;
  let bd = MATCH_KM;
  for (const s of S.index.storms || []) {
    for (const pt of s.points || []) {
      if (!atFrame(pt, i)) continue;
      const d = km(p.lat, p.lon, pt.lat, pt.lon);
      if (d <= bd) { bd = d; best = s; }
    }
  }
  return best;
}

function card(p, i) {
  const c = cls(p.cls);
  const s = matchStorm(p, i);
  const link = (u, label) => (u ? `<a href="${esc(new URL(u, S.base).href)}" target="_blank" rel="noopener">${label}</a>` : '');
  const storm = s ? `<div class="card-storm">
      <strong>${esc(s.name)}</strong>
      <span class="card-code">${s.fsu != null ? `FSU number ${esc(s.fsu)}` : 'Not on the FSU page'}</span>
      <div class="card-links">${link(s.phase_png, 'phase diagram')}${link(s.compare_png, 'compare with FSU')}</div>
    </div>` : '';
  return `<div class="card">
    <div class="card-cls"><span class="swatch" style="--c:${c.hex}"></span><span>${esc(c.name)}
      <span class="card-code">class ${p.cls ?? 'none'}</span></span></div>
    <dl>
      <dt>MSLP</dt><dd>${unit(num(p.mslp, 1), 'hPa')}</dd>
      <dt>HVTL</dt><dd>${unit(sgn(p.hvtl), 'm')}</dd>
      <dt>HVTU</dt><dd>${unit(sgn(p.hvtu), 'm')}</dd>
      <dt>HB</dt><dd>${unit(num(p.hb, 1), 'm')}</dd>
      <dt>Index</dt><dd>${sgn(p.idx, 1)}</dd>
      <dt>Position</dt><dd>${Math.abs(p.lat).toFixed(1)}&deg;${p.lat >= 0 ? 'N' : 'S'} ${Math.abs(p.lon).toFixed(1)}&deg;${p.lon >= 0 ? 'E' : 'W'}</dd>
    </dl>${storm}</div>`;
}

// Storm tracks: dashed segments colored by the class at their start point.
function drawTracks() {
  trackG.clearLayers();
  for (const s of S.index.storms || []) {
    const pts = (s.points || []).map((p) => ({ ...p }));
    for (let k = 1; k < pts.length; k++) {  // unwrap across the dateline
      while (pts[k].lon - pts[k - 1].lon > 180) pts[k].lon -= 360;
      while (pts[k].lon - pts[k - 1].lon < -180) pts[k].lon += 360;
    }
    for (const o of OFFSETS) {
      for (let k = 0; k < pts.length; k++) {
        const a = pts[k];
        const hex = cls(a.cls).hex;
        if (k + 1 < pts.length) {
          const b = pts[k + 1];
          trackG.addLayer(L.polyline([[a.lat, a.lon + o], [b.lat, b.lon + o]], {
            renderer: trackR, color: hex, weight: 1.5, opacity: 0.9, dashArray: '4 4',
          }).bindTooltip(esc(s.name), { sticky: true, className: 'track-tip' }));
        }
        trackG.addLayer(L.circleMarker([a.lat, a.lon + o], {
          renderer: trackR, radius: 2, stroke: false, fillColor: hex, fillOpacity: 1, interactive: false,
        }));
      }
    }
  }
}

function drawTrackNow(i) {
  nowG.clearLayers();
  for (const s of S.index.storms || []) {
    const pt = (s.points || []).find((p) => atFrame(p, i));
    if (!pt) continue;
    for (const o of OFFSETS) {
      nowG.addLayer(L.circleMarker([pt.lat, pt.lon + o], {
        renderer: trackR, radius: 5, color: '#ffffff', weight: 1.5, opacity: 0.9,
        fill: false, interactive: false,
      }));
    }
  }
}

/* ---------- frames ---------- */

async function show(i) {
  const hours = S.index.hours;
  const n = hours.length;
  S.i = ((i % n) + n) % n;
  const h = hours[S.i];
  syncTime();
  const tok = ++S.token;
  const raster = S.field === 'class' ? Promise.resolve(null) : loadImg(rasterUrl(h, S.field), h);
  const [lows, mslp, img] = await Promise.allSettled(
    [getJSON(fileUrl(h, 'lows.geojson')), getJSON(fileUrl(h, 'mslp.geojson')), raster]);
  if (tok !== S.token) return true;  // a newer frame was asked for

  const val = (r) => (r.status === 'fulfilled' ? r.value : null);
  const openId = S.openId;
  S.redrawing = true;
  setRaster(val(img));
  drawContours(val(mslp));
  drawBlobs(val(lows));
  drawCenters(val(lows), S.i);
  drawTrackNow(S.i);
  S.redrawing = false;
  // Ids are per frame, so follow the open low to the nearest center.
  if (openId) nearestCenter(openId)?.openPopup();

  prefetch(S.i + 1);
  if (S.playing) prefetch(S.i + 2);
  const failed = [lows, mslp, img].some((r) => r.status === 'rejected');
  if (failed) toast(`Part of forecast hour ${h} could not be loaded`);
  return !failed;
}

function prefetch(i) {
  const n = S.index.hours.length;
  const h = S.index.hours[((i % n) + n) % n];
  const quiet = (p) => p.catch(() => {});
  quiet(getJSON(fileUrl(h, 'lows.geojson')));
  quiet(getJSON(fileUrl(h, 'mslp.geojson')));
  if (S.field !== 'class') quiet(loadImg(rasterUrl(h, S.field), h));
}

function syncTime() {
  const slider = $('frame');
  const n = S.index.hours.length;
  const h = S.index.hours[S.i];
  const v = validAt(S.i);
  const label = v ? fmtValid(v) : `Hour ${h}`;
  slider.value = S.i;
  slider.style.setProperty('--fill', `${n > 1 ? (S.i / (n - 1)) * 100 : 0}%`);
  slider.setAttribute('aria-valuetext', `${label}, forecast hour ${h}`);
  $('when-valid').textContent = label;
  $('when-fhr').textContent = `F${pad(h, 3)}  ${S.i + 1} of ${n}`;
}

function play(on) {
  S.playing = on;
  const b = $('play');
  b.setAttribute('aria-pressed', String(on));
  b.setAttribute('aria-label', on ? 'Pause' : 'Play');
  clearTimeout(S.timer);
  if (on) S.timer = setTimeout(tick, SPEED);
}

async function tick() {
  const t0 = performance.now();
  await show(S.i + 1);
  if (!S.playing) return;
  S.timer = setTimeout(tick, Math.max(0, SPEED - (performance.now() - t0)));
}

/* ---------- legend and field ---------- */

function renderLegend() {
  const f = S.field;
  const box = $('legend-scale');
  const units = S.legend?.units?.[f] || 'm';
  $('legend-title').textContent = TITLES[f];
  $('legend-help').textContent = HELP[f];
  if (f === 'class') {
    box.innerHTML = `<ul class="classes">${[...S.classes.values()].map((c) =>
      `<li><span class="swatch" style="--c:${c.hex}"></span><span class="code">${c.code}</span>${esc(c.name)}</li>`).join('')}</ul>`;
    return;
  }
  const stops = S.legend?.rasters?.[f]?.stops || S.legend?.stops?.[f];
  const [lo, hi] = S.legend?.rasters?.[f]?.range || S.legend?.ranges?.[f] || S.index.ranges?.[f] || [-1, 1];
  if (!stops?.length) { box.innerHTML = ''; return; }
  const pct = (v) => ((v - lo) / (hi - lo)) * 100;
  const grad = [...stops].sort((a, b) => a[0] - b[0])
    .map(([v, hex, a]) => `${rgba(hex, a ?? 1)} ${pct(v).toFixed(1)}%`).join(', ');
  const ticks = f === 'hb' ? [lo, -10, 0, 10, hi] : [lo, lo / 2, 0, hi / 2, hi];
  const mark = f === 'hb' ? `<span class="ramp-mark" style="left:calc(${pct(10)}% - 1px)" title="Hart's 10 m onset line"></span>` : '';
  box.innerHTML = `
    <div class="ramp"><div class="ramp-fill" style="background:linear-gradient(to right, ${grad})"></div>${mark}</div>
    <div class="ticks">${ticks.map((t) => `<span style="left:${pct(t)}%">${sgn(t)}</span>`).join('')}</div>
    <div class="ramp-ends"><span>${ENDS[f][0]}</span><span class="units">${esc(units)}</span><span>${ENDS[f][1]}</span></div>`;
}

function setField(f, redraw = true) {
  if (!FIELDS.includes(f)) return;
  S.field = f;
  const input = document.querySelector(`input[name="field"][value="${f}"]`);
  if (input) input.checked = true;
  $('opacity-wrap').classList.toggle('off', f === 'class');
  document.body.classList.toggle('raster-on', f !== 'class');
  $('opacity').disabled = f === 'class';
  renderLegend();
  if (redraw) show(S.i);
}

/* ---------- basins, hash, share ---------- */

function basinView(key) {
  const wide = map.getSize().x;
  const world = Math.max(1, Math.floor(Math.log2(wide / 256) * 2) / 2);
  return {
    global: [[20, -30], world],
    natl: [[40, -45], wide < 700 ? 2 : 3],
    npac: [[42, -170], wide < 700 ? 2 : 3],
    south: [[-52, 40], wide < 700 ? 1.5 : 2],
  }[key];
}

// Basemap choice; basemap.js draws it, this keeps the chips in step.
function setBasemap(key) {
  S.basemap = basemap.set(key);
  document.querySelectorAll('.basemaps .chip').forEach((c) =>
    c.setAttribute('aria-pressed', String(c.dataset.base === S.basemap)));
}

function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const out = {};
  if (q.has('t')) out.hour = +q.get('t');
  if (FIELDS.includes(q.get('f'))) out.field = q.get('f');
  const v = (q.get('v') || '').split(',').map(Number);
  if (v.length === 3 && v.every(Number.isFinite)) out.view = v;
  return out;
}

function viewHash() {
  const c = map.getCenter().wrap();
  return `#t=${S.index.hours[S.i]}&f=${S.field}&b=${S.basemap}&v=${c.lat.toFixed(2)},${c.lng.toFixed(2)},${map.getZoom()}`;
}

async function share() {
  if (!S.index) return;
  history.replaceState(null, '', viewHash());
  try {
    await navigator.clipboard.writeText(location.href);
    toast('Link to this view copied');
  } catch {
    toast('Link to this view is in the address bar');
  }
}

/* ---------- layout ---------- */

// Map space hidden by the page chrome, for the graticule edge labels.
function chromeInsets() {
  const narrow = innerWidth <= 760;
  const row = document.querySelector('.chiprow').getBoundingClientRect();
  return { top: narrow ? Math.round(row.bottom + 4) : 6, left: Math.round(row.bottom), bottom: Math.round(innerHeight - $('bar').getBoundingClientRect().top) };
}

// Keep Leaflet's corner controls, the legend sheet and toasts clear of the bar.
function measure() {
  const root = document.documentElement.style;
  const bar = $('bar').getBoundingClientRect();
  root.setProperty('--bar-h', `${Math.round(innerHeight - bar.top)}px`);
  root.setProperty('--head-h', `${Math.round(document.querySelector('.masthead').offsetHeight)}px`);
  basemap?.edges();
}

/* ---------- boot ---------- */

function noData(title, msg) {
  document.body.classList.add('empty');
  $('run-meta').textContent = 'No cycle loaded';
  $('nodata-title').textContent = title;
  $('loading').classList.add('hidden');
  $('nodata-text').innerHTML = msg;
  $('nodata').classList.remove('hidden');
}

function bindControls() {
  $('frame').addEventListener('input', (e) => { play(false); show(+e.target.value); });
  $('play').addEventListener('click', () => play(!S.playing));
  document.querySelectorAll('input[name="field"]').forEach((r) =>
    r.addEventListener('change', () => setField(r.value)));
  $('opacity').addEventListener('input', (e) => {
    S.opacity = +e.target.value;
    Object.values(rasterLayers).flat().forEach((ov) => ov.setOpacity(S.opacity));
  });
  const toggle = (id, groups) => $(id).addEventListener('change', (e) =>
    groups().forEach((g) => (e.target.checked ? g.addTo(map) : map.removeLayer(g))));
  toggle('t-contours', () => [contourG]);
  toggle('t-blobs', () => [blobG]);
  toggle('t-tracks', () => [trackG, nowG]);
  document.querySelectorAll('.basins .chip').forEach((b) => b.addEventListener('click', () => {
    const [c, z] = basinView(b.dataset.basin);
    map.flyTo(c, z, { duration: 1.1 });
    document.querySelectorAll('.basins .chip').forEach((x) => x.classList.toggle('on', x === b));
  }));
  document.querySelectorAll('.basemaps .chip').forEach((c) =>
    c.addEventListener('click', () => setBasemap(c.dataset.base)));
  $('share').addEventListener('click', share);
  $('retry').addEventListener('click', () => boot());

  // Left and right step frames (captured before Leaflet pans); space plays.
  document.addEventListener('keydown', (e) => {
    if (!S.index || e.altKey || e.ctrlKey || e.metaKey) return;
    const t = e.target;
    if (t.matches?.('input[type="range"], input[type="text"], textarea')) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      play(false);
      show(S.i + (e.key === 'ArrowRight' ? 1 : -1));
    } else if (e.key === ' ' && !t.closest?.('button, a, summary, label, .leaflet-popup')) {
      e.preventDefault();
      play(!S.playing);
    }
  }, true);

  new ResizeObserver(measure).observe($('bar'));
  new ResizeObserver(measure).observe(document.querySelector('.masthead'));
  addEventListener('resize', measure);
}

async function boot() {
  $('nodata').classList.add('hidden');
  document.body.classList.remove('empty');
  $('loading').classList.remove('hidden');
  try {
    S.index = await fetchJSON(new URL('index.json', S.base).href, { cache: 'no-cache' });
    if (!Array.isArray(S.index.hours) || !S.index.hours.length) throw new Error('no forecast hours');
  } catch (err) {
    S.index = null;
    noData('No live data yet', `The daily run has not published a cycle yet, or it could not be reached. Looked for <code>${esc(S.base)}index.json</code>.`);
    return;
  }
  try {
    S.legend = await fetchJSON(new URL('legend.json', S.base).href, { cache: 'no-cache' });
  } catch {
    S.legend = null;  // fall back to the built-in class palette
  }
  S.bust = `?v=${encodeURIComponent(S.index.cycle || S.index.generated || '')}`;
  S.classes.clear();
  const list = S.legend?.classes?.length ? S.legend.classes
    : FALLBACK_HEX.map((hex, code) => ({ code, hex }));
  for (const c of list) S.classes.set(c.code, { code: c.code, hex: c.hex, name: CLASS_NAMES[c.code] || c.name });

  const ix = S.index;
  $('run-meta').innerHTML = `<span>${esc(ix.model || 'Model')}, ${esc(fmtCycle(ix.cycle))} cycle</span>` +
    (ix.generated ? `<span>Generated ${esc(fmtGenerated(ix.generated))}</span>` : '');
  const slider = $('frame');
  slider.max = ix.hours.length - 1;
  slider.disabled = ix.hours.length < 2;
  $('play').disabled = ix.hours.length < 2;

  const want = readHash();
  if (want.view) map.setView([want.view[0], want.view[1]], want.view[2], { animate: false });
  const hi = ix.hours.indexOf(want.hour);
  S.i = hi >= 0 ? hi : 0;
  setField(want.field || S.field, false);
  drawTracks();
  await show(S.i);
  $('loading').classList.add('hidden');
  measure();
}

function start() {
  if (!window.L) {
    noData('The map could not start', 'The map library could not be loaded. Check the connection, or read the <a href="../index.html">article</a> in the meantime.');
    $('retry').addEventListener('click', () => location.reload());
    return;
  }
  const narrow = matchMedia('(max-width: 760px)').matches;
  if (narrow) $('legend').open = false;
  initMap(narrow ? 2 : 3);
  setBasemap(CPSBasemap.saved());
  bindControls();
  measure();
  boot();
}

start();
