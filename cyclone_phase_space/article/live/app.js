/* Cyclone Phase Space, live: the map, frames, timeline and controls.
   The low centers, MSLP contours, the thermal asymmetry and thermal wind
   rasters and the storm tracks, animated over the forecast hours of the
   latest cycle, on a MapLibre GL (WebGL) globe from the site's globe kit
   (globe-kit/globe-kit.js, window.GlobeKit), in the look of the /ndfd/
   globe page.

   The rasters (Mercator images of the whole map, 85N to 85S) are one
   image layer; the contours, footprints, circles, tracks and low dots are
   GeoJSON layers; names and numbers go on the kit's 2D overlay canvas,
   since the page loads no map fonts, skipping the far side of the globe.
   storms.js (tracks, names, selection, follow mode), card.js (legend,
   tooltip and the phase space card) and space3d.js (the 3-D phase space)
   use the globals defined here; this file loads last and starts the page.
   Plain ES2020, no build step. */
'use strict';

const K = window.GlobeKit;
const FALLBACK_DATA = 'https://raw.githubusercontent.com/jkrek17/awips-tools/cps-live/latest/';
const LOCAL_DATA = 'data/latest/';  // beside the page when served from the web repository
const ARTICLE_URL = 'article/';  // published beside this page, which is the site root
const GUIDE_URL = 'forecasters/';  // the plain-language explainer, published beside this page
const LABEL_ZOOM = 3;            // pressures at the lows and every isobar from this zoom
const WIDE_CINT = 8;             // below LABEL_ZOOM, isobars thinned to every 8 hPa
const CLABEL_ZOOM = 2;           // labels on the bold isobars from this zoom
const HALO_ZOOM = 1;             // 200 km circles from this zoom (below it they shrink under the dot)
const SPEEDS = { slow: 1200, normal: 700, fast: 350 };  // ms per frame
const MAX_RASTER_FRAMES = 12;    // decoded raster frames kept in memory
const MATCH_KM = 300;            // center to storm matching radius, for entries without run ids
const HALO_KM = 200;             // radius of the circle drawn at each low
const DEEP_HPA = 980;            // lows below this get a larger dot
const TERRAIN_HPA = 850;         // surface pressure below this: a false low over high ground
const STALE_H = 12;              // hours before the data is called stale
const RASTERS = ['hb', 'hvtl', 'hvtu'];
const FIELDS = ['class', ...RASTERS];
const LAYER_KEYS = { contours: 'c', circles: 'h', footprint: 'p', tracks: 'k', terrain: 'g', fade: 'x', z500: 'z', thick: 'n', jet: 'j' };
// Keys present in the link when the layer is off: the fade is on by default
// and older links never carried it.
const INVERTED_KEYS = new Set(['fade']);
const HOTKEYS = { i: 'contours', k: 'tracks', o: 'circles', p: 'footprint', g: 'terrain', x: 'fade', z: 'z500', n: 'thick', j: 'jet' };
// The upper-air overlays: layer -> the frame file and the index.json layers flag.
const UPPER = { z500: 'z500', thick: 'thick', jet: 'jet250' };
const THICK_LINE = 540;          // dam; the bold rain/snow guide line

const CLASS_NAMES = [
  'Symmetric deep warm core', 'Symmetric shallow warm core',
  'Asymmetric deep warm core', 'Asymmetric shallow warm core',
  'Asymmetric cold core', 'Symmetric cold core', 'Shallow cold core',
];
const FALLBACK_HEX = ['#d92626', '#cc33bf', '#fad91a', '#33ad40', '#2680e6', '#5938b8', '#b8b8b2'];

const MINUS = '−';

const TERM = {
  hb: { name: 'Thermal asymmetry', sym: 'B', band: '900 to 600 hPa' },
  hvtl: { name: 'Lower thermal wind', sym: `${MINUS}V<sub>T</sub><sup>L</sup>`, band: '900 to 600 hPa' },
  hvtu: { name: 'Upper thermal wind', sym: `${MINUS}V<sub>T</sub><sup>U</sup>`, band: '600 to 300 hPa' },
};
const termHTML = (f) => `${TERM[f].name} (${TERM[f].sym})`;

// The field list in the layers panel: [key, name, hotkey].
const FIELD_LIST = [['class', 'Class at the low center', '1'], ['hb', `${termHTML('hb')}`, '2'],
  ['hvtl', `${termHTML('hvtl')}`, '3'], ['hvtu', `${termHTML('hvtu')}`, '4']];
// The B field takes the motion from the steering flow, since one frame has no
// track; a tracked low's own B comes from its motion (storms.js, bOf).
const B_FIELD_NOTE = 'Across the steering flow; tracked lows use their own motion';
const TITLES = {
  class: 'Hart class at the low center',
  hb: `${termHTML('hb')}, ${TERM.hb.band}`,
  hvtl: `${termHTML('hvtl')}, ${TERM.hvtl.band}`,
  hvtu: `${termHTML('hvtu')}, ${TERM.hvtu.band}`,
};
const ENDS = {
  hb: ['warm air left', 'warm air right'],
  hvtl: ['cold core', 'warm core'],
  hvtu: ['cold aloft', 'warm aloft'],
};
// Reading notes per field, from the user guide; the clear band at zero is
// added from the export (card.js, clearText), else CLEAR_OLD.
const HELP = {
  class: 'Read the class at the center dot, never the footprint edge. A transition runs red, yellow, green, blue (codes 0, 2, 3, 4).',
  hb: 'Magenta: warm air to the right of the deep-layer flow, the frontal geometry; teal: warm air on the left. More than 10 m at a low center is asymmetric (Hart\'s onset line, marked).',
  hvtl: 'Red is a warm lower core, blue a cold one. A hurricane reads +100 to +300 m; a center falling below 0 marks transition complete.',
  hvtu: 'Red is a warm upper core, blue is cold aloft. The upper core usually turns blue first as a transition gets under way.',
};
const CLEAR_OLD = {
  hb: 'Transparent within 5 m of zero.',
  hvtl: 'Transparent within about 37 m of zero.',
  hvtu: 'Transparent within about 37 m of zero.',
};

const DOW = K.DAYS;
const MON = K.MONS;

const $ = (id) => document.getElementById(id);
const pad = (n, w = 2) => String(n).padStart(w, '0');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const narrow = () => K.isMobile();

const S = {
  base: null, index: null, legend: null, classes: new Map(),
  i: 0, field: 'class', playing: false, timer: 0, token: 0,
  speed: 'normal', bust: '',
  opacity: { hb: 0.7, hvtl: 0.7, hvtu: 0.7 },  // the ramps are opaque from 10% of the half range
  layers: { contours: true, circles: true, footprint: false, tracks: true, terrain: false, fade: true,
    z500: false, thick: false, jet: false },
  centers: [], lows: null, mslp: null, z500: null, thick: null, sel: null, follow: null, ready: false, sideOpen: true,
};

/* ---------- small utilities ---------- */

function dirUrl(u) {
  u = new URL(u, location.href).href;
  if (/\.json$/i.test(u)) u = u.replace(/[^/]*$/, '');
  return u.endsWith('/') ? u : u + '/';
}

// Data base, in order: ?data=, then data/latest/ beside the page if its
// index.json answers, then the published branch on GitHub.
async function resolveBase() {
  const q = new URLSearchParams(location.search).get('data');
  if (q) return dirUrl(q);
  const local = dirUrl(LOCAL_DATA);
  for (const method of ['HEAD', 'GET']) {
    try {
      const r = await fetch(local + 'index.json', { method, cache: 'no-cache' });
      if (r.ok) return local;
      if (r.status !== 405 && r.status !== 501) break;
    } catch {
      break;
    }
  }
  return FALLBACK_DATA;
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
// Each entry is { h, p, drop }: p resolves to the URL to display, and
// drop() frees what the entry holds when its frame is evicted.
const imgCache = new Map();
const imgFrames = [];
function cached(key, h, make) {
  let e = imgCache.get(key);
  if (!e) {
    e = make();
    e.h = h;
    imgCache.set(key, e);
    const mine = e;
    e.p.catch(() => { if (imgCache.get(key) === mine) imgCache.delete(key); });
  }
  const k = imgFrames.indexOf(h);
  if (k >= 0) imgFrames.splice(k, 1);
  imgFrames.push(h);
  while (imgFrames.length > MAX_RASTER_FRAMES) {
    const old = imgFrames.shift();
    for (const [u, v] of imgCache) {
      if (v.h === old) { imgCache.delete(u); v.drop?.(); }
    }
  }
  return e.p;
}

function loadImg(url, h) {
  return cached(url, h, () => {
    const im = new Image();
    im.decoding = 'async';
    const p = new Promise((res, rej) => {
      im.onload = () => res(url);
      im.onerror = () => rej(new Error(`image ${url}`));
    });
    im.src = url;
    return { im, p };
  });
}

/* The fade: a field's alpha multiplied by the frame's mask.png (1 inside
   the closed-low footprints, raster.mask_dim far from them). The field is
   drawn on a canvas at its own size, the mask scaled over it with
   "destination-in", and the result encoded to a blob URL that the map
   loads like any image. Decoding is createImageBitmap's (off the main
   thread), the canvas an OffscreenCanvas where there is one, the encoding
   asynchronous; each (frame, field) is composited once and cached with
   the plain images, its blob URL revoked when the frame is evicted. */
const fadeOn = () => S.layers.fade && !!S.index?.raster?.mask;

async function fetchBlob(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.blob();
}

async function decodeBlob(blob) {
  if (typeof createImageBitmap === 'function') return createImageBitmap(blob);
  const u = URL.createObjectURL(blob);
  const im = new Image();
  im.src = u;
  try { await im.decode(); } finally { URL.revokeObjectURL(u); }
  return im;
}

function newCanvas(w, h) {
  if (typeof OffscreenCanvas === 'function') {
    const c = new OffscreenCanvas(w, h);
    if (c.getContext('2d')) return c;
  }
  return Object.assign(document.createElement('canvas'), { width: w, height: h });
}

// PNG: lossless and several times faster to encode than WebP (about 0.1 s
// against 0.7 s for a field); the blob stays in memory, never on the wire.
function canvasBlob(c) {
  if (c.convertToBlob) return c.convertToBlob({ type: 'image/png' });
  return new Promise((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error('canvas encode'))), 'image/png'));
}

// The mask's bytes, once per frame (a small PNG, decoded per use).
function maskBlob(h) {
  const url = fileUrl(h, S.index.raster.mask);
  return cached(url, h, () => ({ p: fetchBlob(url) }));
}

function fadedImg(h, f) {
  const url = rasterUrl(h, f);
  return cached(`${url}#fade`, h, () => {
    const e = { url: null, im: null, gone: false };
    e.drop = () => {
      e.gone = true;
      if (e.url && e.url !== RS.url) URL.revokeObjectURL(e.url);
    };
    e.p = (async () => {
      const [field, mask] = await Promise.all([fetchBlob(url).then(decodeBlob), maskBlob(h).then(decodeBlob)]);
      const w = field.width;
      const ht = field.height;
      const c = newCanvas(w, ht);
      const ctx = c.getContext('2d');
      ctx.drawImage(field, 0, 0, w, ht);
      ctx.globalCompositeOperation = 'destination-in';
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(mask, 0, 0, w, ht);
      field.close?.();
      mask.close?.();
      const blob = await canvasBlob(c);
      e.url = URL.createObjectURL(blob);
      if (e.gone) { URL.revokeObjectURL(e.url); throw new Error('evicted'); }
      return e.url;
    })();
    return e;
  });
}

// The image to display for a field at a frame: faded when the option is on
// and the export has a mask, else the plain file (also if compositing fails).
function fieldImg(h, f) {
  if (!fadeOn()) return loadImg(rasterUrl(h, f), h);
  return fadedImg(h, f).catch(() => loadImg(rasterUrl(h, f), h));
}

function frameDir(h) {
  const tpl = S.index.frames || 'frames/f{hhh}/';
  const dir = /\{h+\}/.test(tpl)
    ? tpl.replace(/\{(h+)\}/, (_, w) => pad(h, w.length))
    : `${tpl.replace(/\/?$/, '/')}f${pad(h, 3)}/`;
  return new URL(dir, S.base).href;
}
const fileUrl = (h, name) => frameDir(h) + name + S.bust;
const rasterUrl = (h, f) => fileUrl(h, `${f}.${S.index.raster?.format || 'png'}`);  // the class raster is not loaded
const lowsUrl = (h) => fileUrl(h, 'lows.geojson');

function km(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const dl = ((((lon2 - lon1) % 360) + 540) % 360 - 180) * r;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dl / 2) ** 2;
  return 12742 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const cls = (code) => S.classes.get(code) || { code, name: 'No class (blank)', hex: '#8a8a86' };
const blank = (v) => v == null || v === '' || Number.isNaN(+v);
// Numbers: a true minus sign, fixed decimals per quantity, a unit on every value.
function fmt(v, d = 0, u = '', signed = false) {
  if (blank(v)) return 'blank';
  const x = +(+v).toFixed(d);
  const s = Math.abs(x).toFixed(d);
  const sign = x < 0 ? MINUS : signed && x > 0 ? '+' : '';
  return `${sign}${s}${u ? ` ${u}` : ''}`;
}
const hpa = (v) => fmt(v, 1, 'hPa');
function pos(lat, lon) {
  const w = K.wrapLon(lon);
  return `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(w).toFixed(1)}°${w >= 0 ? 'E' : 'W'}`;
}

function utc(d) {
  if (!d) return null;
  if (typeof d === 'string' && /^\d{10}$/.test(d)) {
    d = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T${d.slice(8, 10)}:00:00Z`;
  }
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? null : t;
}
const fmtDay = (d) => `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`;
function fmtCycle(c) {
  const d = utc(c);
  return d ? `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()} ${pad(d.getUTCHours())} UTC` : String(c ?? '');
}
function ago(d) {
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  return mins < 90 ? `${Math.max(mins, 0)} min ago` : mins < 2880 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} days ago`;
}
function validAt(i) {
  const v = S.index.valid?.[i] && utc(S.index.valid[i]);
  if (v) return v;
  const c = utc(S.index.cycle);
  return c ? new Date(c.getTime() + S.index.hours[i] * 3600e3) : null;
}

/* ---------- map ---------- */

let map, ov, rail;
const EMPTY = { type: 'FeatureCollection', features: [] };
const setData = (id, fc) => map?.getSource(id)?.setData(fc);

// Room for the floating cards round the map: the top bar, the timeline, the
// layers panel on the left and the phase space on the right (wide screens).
function viewPadding() {
  const r = document.documentElement.getBoundingClientRect();
  const tb = document.querySelector('.topbar').getBoundingClientRect();
  const tl = $('timeline').getBoundingClientRect();
  const wide = r.width > 760;
  const panel = wide && K.panelOpen() ? $('panel').getBoundingClientRect().right + 12 : 16;
  const side = wide && S.sideOpen ? r.width - $('side').getBoundingClientRect().left + 12 : 16;
  return { top: tb.bottom + 8, bottom: r.height - tl.top + 8, left: panel, right: side };
}

// Center a point in the part of the map not covered by the cards, without animation.
function centerOn(lat, lon, zoom) {
  const p = viewPadding();
  const off = [(p.left - p.right) / 2, (p.top - p.bottom) / 2];
  // keep near the current center's longitude, so the globe turns the short way
  const c = map.getCenter().lng;
  const lng = c + K.wrapLon(lon - c);
  map.easeTo({ center: [lng, lat], zoom: zoom ?? map.getZoom(), offset: off, duration: 0 });
}

function buildMap(start) {
  map = K.createMap({ start, credits: 'NOAA GFS &middot; Natural Earth', nav: 'bottom-left', maxZoom: 9 });
  window.CPS_map = map;   // for console checks
  ov = K.overlay(map, $('overlay'));
  map.on('load', () => {
    const r = S.index.raster || {};
    const [[s, w], [n, e]] = r.bounds || [[-85, -180], [85, 180]];
    map.addSource('field', { type: 'image', url: blankImage(), coordinates: [[w, n], [e, n], [e, s], [w, s]] });
    map.addLayer({ id: 'field', type: 'raster', source: 'field', layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0.7, 'raster-fade-duration': 0, 'raster-resampling': 'linear' } });
    map.addSource('jet', { type: 'image', url: blankImage(), coordinates: [[w, n], [e, n], [e, s], [w, s]] });
    map.addLayer({ id: 'jet', type: 'raster', source: 'jet', layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0.5, 'raster-fade-duration': 0, 'raster-resampling': 'linear' } });
    map.addSource('coast', { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'coast', type: 'line', source: 'coast', paint: { 'line-color': 'rgba(231,238,248,0.35)', 'line-width': 0.6 } });
    K.land().then((g) => setData('coast', g)).catch(() => {});
    map.addSource('graticule', { type: 'geojson', data: K.graticule() });
    map.addLayer({ id: 'graticule', type: 'line', source: 'graticule', paint: K.GRATICULE_PAINT });
    for (const id of ['thick', 'z500', 'contours', 'footprints', 'halos', 'tails', 'track', 'trackpts', 'lows', 'sel']) {
      map.addSource(id, { type: 'geojson', data: EMPTY, tolerance: 0.2 });
    }
    // 1000-500 hPa thickness: dashed, red above THICK_LINE, blue at and below it, that line bold
    map.addLayer({ id: 'thick', type: 'line', source: 'thick', layout: { 'line-join': 'round' }, paint: {
      'line-color': ['case', ['>', ['get', 'level'], THICK_LINE], '#d42a20', '#2f7ff0'],
      'line-width': ['case', ['==', ['get', 'level'], THICK_LINE], 2.2, 1.1],
      'line-dasharray': [3, 2] } });
    // 500 hPa height: solid blue
    map.addLayer({ id: 'z500', type: 'line', source: 'z500', layout: { 'line-join': 'round' },
      paint: { 'line-color': '#0f2d9c', 'line-width': 1.8, 'line-opacity': 0.9 } });
    // isobars: bold every 16 hPa; every 8 hPa zoomed out, all of them from LABEL_ZOOM
    const lev = ['get', 'level'];
    // dark lines, as on a surface analysis, so they read on the pale ocean
    // basemap and over the fields alike
    const iso = (op, w) => ({ 'line-color': `rgba(8,14,28,${op})`, 'line-width': w });
    map.addLayer({ id: 'iso-minor8', type: 'line', source: 'contours',
      filter: ['all', ['==', ['%', lev, WIDE_CINT], 0], ['!=', ['%', lev, 16], 0]], paint: iso(0.6, 1) });
    map.addLayer({ id: 'iso-minor', type: 'line', source: 'contours', minzoom: LABEL_ZOOM,
      filter: ['!=', ['%', lev, WIDE_CINT], 0], paint: iso(0.6, 1) });
    map.addLayer({ id: 'iso-major', type: 'line', source: 'contours', filter: ['==', ['%', lev, 16], 0], paint: iso(0.85, 1.7) });
    map.addLayer({ id: 'footprints', type: 'line', source: 'footprints',
      paint: { 'line-color': ['get', 'hex'], 'line-width': 1, 'line-opacity': 0.9, 'line-dasharray': [2, 2] } });
    map.addLayer({ id: 'halos-fill', type: 'fill', source: 'halos', minzoom: HALO_ZOOM, paint: { 'fill-color': ['get', 'hex'], 'fill-opacity': 0.06 } });
    map.addLayer({ id: 'halos', type: 'line', source: 'halos', minzoom: HALO_ZOOM,
      paint: { 'line-color': ['get', 'hex'], 'line-opacity': 0.7, 'line-width': ['case', ['get', 'deep'], 1.5, 1] } });
    map.addLayer({ id: 'tails', type: 'line', source: 'tails', layout: { 'line-cap': 'round' },
      paint: { 'line-color': ['get', 'hex'], 'line-width': 1.25, 'line-opacity': 0.55 } });
    map.addLayer({ id: 'track-casing', type: 'line', source: 'track', layout: { 'line-cap': 'round' },
      paint: { 'line-color': 'rgba(5,10,20,0.75)', 'line-width': ['+', ['get', 'w'], 2.2] } });
    map.addLayer({ id: 'track', type: 'line', source: 'track', layout: { 'line-cap': 'round' },
      paint: { 'line-color': ['get', 'hex'], 'line-width': ['get', 'w'] } });
    map.addLayer({ id: 'trackpts', type: 'circle', source: 'trackpts',
      paint: { 'circle-radius': 2.4, 'circle-color': ['get', 'hex'], 'circle-stroke-color': '#0b1220', 'circle-stroke-width': 0.8 } });
    // Where a tracked low's class from its own motion (the dot) differs from
    // the field's steering-flow class: a thin ring in the field's color
    // just outside the dot, a dark band between the two.
    map.addLayer({ id: 'lows-alt', type: 'circle', source: 'lows', filter: ['has', 'alt'], paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, ['case', ['get', 'deep'], 6.8, 5.2], LABEL_ZOOM, ['case', ['get', 'deep'], 8.8, 7]],
      'circle-color': 'rgba(11,18,32,0.85)',
      'circle-stroke-color': ['get', 'alt'],
      'circle-stroke-width': 1.4,
    } });
    map.addLayer({ id: 'lows', type: 'circle', source: 'lows', paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, ['case', ['get', 'deep'], 4.8, 3.2], LABEL_ZOOM, ['case', ['get', 'deep'], 6.5, 4.8]],
      'circle-color': ['case', ['get', 'terrain'], 'rgba(0,0,0,0)', ['get', 'hex']],
      'circle-stroke-color': ['case', ['get', 'terrain'], '#a3b3c9', '#0b1220'],
      'circle-stroke-width': ['case', ['get', 'terrain'], 1.2, 1],
    } });
    map.addLayer({ id: 'sel', type: 'circle', source: 'sel',
      paint: { 'circle-radius': 12, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#e7eef8', 'circle-stroke-width': 1.6 } });
    S.mapReady = true;
    ready();
  });
  map.on('render', drawOverlay);
  map.on('moveend', () => { placeContourLabels(); drawOverlay(); writeHash(); });
  map.on('movestart', (e) => { if (e.originalEvent) setView(null); });
  map.on('mousemove', (e) => hoverAt(e.point, e.lngLat));
  map.on('click', (e) => {
    const c = lowAt(e.point);
    if (c) selectLow(c);
  });
  map.on('error', (e) => {
    const sid = e.sourceId || e.source?.id;
    if (sid === 'ocean') K.note('Basemap tiles failed to load; the products still show.');
    else if (e?.error) console.error(e.error);
  });
  map.getCanvas().addEventListener('mouseleave', () => {
    $('readout').hidden = true;
    $('coords').textContent = '';
    hoverStorm(null);
  });
}

// A transparent pixel for the image source before the first raster arrives.
function blankImage() {
  const c = document.createElement('canvas');
  c.width = c.height = 1;
  return c.toDataURL('image/png');
}

/* ---------- the field raster ---------- */

const RS = { url: null };

function swapRaster(url) {
  if (!map?.getLayer('field')) return;
  if (!url) {
    map.setLayoutProperty('field', 'visibility', 'none');
    RS.url = null;
    return;
  }
  map.setPaintProperty('field', 'raster-opacity', S.opacity[S.field] ?? 0.7);
  // a faded image's blob URL stays valid until its frame leaves the cache
  if (url !== RS.url) {
    RS.url = url;
    map.getSource('field').updateImage({ url });
  }
  map.setLayoutProperty('field', 'visibility', 'visible');
}

function setOpacity(v) {
  if (S.field === 'class') return;
  S.opacity[S.field] = v;
  $('opacityOut').textContent = `${Math.round(v * 100)}%`;
  if (map?.getLayer('field')) map.setPaintProperty('field', 'raster-opacity', v);
}

/* ---------- contours ---------- */

// The contour interval in the data (the smallest gap between levels).
function cstep(fc) {
  const lv = [...new Set((fc?.features || []).map((f) => Math.round(f.properties?.level)))].sort((a, b) => a - b);
  let step = Infinity;
  for (let k = 1; k < lv.length; k++) step = Math.min(step, lv[k] - lv[k - 1]);
  return Number.isFinite(step) ? step : null;
}

function drawContours() {
  setData('contours', S.layers.contours && S.mslp ? S.mslp : EMPTY);
  S.cstep = cstep(S.mslp);
  setData('z500', S.layers.z500 && S.z500 ? S.z500 : EMPTY);
  setData('thick', S.layers.thick && S.thick ? S.thick : EMPTY);
  placeContourLabels();
}

const hasUpper = (k) => !!S.index?.layers?.[UPPER[k]];

// The 250 hPa jet image of hour h, or hidden.
function drawJet(h) {
  if (!map?.getLayer('jet')) return;
  const on = S.layers.jet && hasUpper('jet');
  if (on) map.getSource('jet').updateImage({ url: fileUrl(h, 'jet250.png') });
  map.setLayoutProperty('jet', 'visibility', on ? 'visible' : 'none');
}

// The upper-air switches need an export that carries them.
function syncUpperBoxes() {
  for (const k of Object.keys(UPPER)) {
    const box = document.querySelector(`[data-layer="${k}"]`);
    if (!box) continue;
    box.disabled = !hasUpper(k);
    box.closest('.switch-row')?.classList.toggle('off', box.disabled);
    box.closest('.switch-row').title = box.disabled ? 'This cycle was exported without this layer' : '';
  }
}

// One label per labelled line at its middle vertex, from CLABEL_ZOOM: the
// bold (16 hPa) isobars, every 500 hPa height and every other thickness line,
// kept clear of the lows, the map edge and each other. Placed when the
// map stops moving; drawn at their lon/lat while it moves.
let clabels = [];
function contourSets() {
  const sets = [];
  if (S.layers.contours && S.mslp) sets.push({ fc: S.mslp, keep: (lv) => lv % 16 === 0, ink: () => '#0b1220' });
  if (S.layers.z500 && S.z500) sets.push({ fc: S.z500, keep: () => true, ink: () => '#0f2d9c' });
  if (S.layers.thick && S.thick) sets.push({ fc: S.thick, keep: (lv) => (lv - THICK_LINE) % 12 === 0, ink: (lv) => (lv > THICK_LINE ? '#c0261d' : '#1f5fd0') });
  return sets;
}
function placeContourLabels() {
  clabels = [];
  if (!map || map.getZoom() < CLABEL_ZOOM) return;
  const w = ov.w(), h = ov.h(), placed = [];
  const lows = S.centers.filter(shown);
  for (const set of contourSets()) for (const f of set.fc.features) {
    const lv = Math.round(f.properties?.level);
    if (!set.keep(lv) || !f.geometry) continue;
    const parts = f.geometry.type === 'MultiLineString' ? f.geometry.coordinates : [f.geometry.coordinates];
    for (const p of parts) {
      if (p.length < 8) continue;
      const m = p[Math.floor(p.length / 2)];
      if (lows.some((c) => Math.abs(c.lat - m[1]) < 3 && km(c.lat, c.lon, m[1], m[0]) < 250)) continue;
      const q = ov.proj(m[0], m[1])[0];
      if (!q || q.x < 30 || q.x > w - 30 || q.y < 12 || q.y > h - 12) continue;
      if (placed.some((o) => Math.abs(o.x - q.x) < 60 && Math.abs(o.y - q.y) < 24)) continue;
      placed.push(q);
      clabels.push({ lon: m[0], lat: m[1], lv, ink: set.ink(lv) });
      if (clabels.length >= 200) return;
    }
  }
}

/* ---------- lows ---------- */

function centersOf(fc) {
  const out = [];
  for (const f of fc?.features || []) {
    if (f.geometry?.type !== 'Point') continue;
    const p = { ...f.properties };
    p.lon ??= f.geometry.coordinates[0];
    p.lat ??= f.geometry.coordinates[1];
    p.terrain = p.terrain === true || (!blank(p.psfc) && +p.psfc < TERRAIN_HPA);
    out.push(p);
  }
  return out;
}
const shown = (c) => S.layers.terrain || !c.terrain;
const isDeep = (c) => !blank(c.mslp) && +c.mslp < DEEP_HPA;

// A circle of radius r km round a point, as a polygon ring.
function circle(lat, lon, r) {
  const ring = [];
  const d = r / 6371;
  const la = lat * Math.PI / 180;
  for (let k = 0; k <= 48; k++) {
    const b = (k / 48) * 2 * Math.PI;
    const la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(b));
    const lo2 = lon * Math.PI / 180 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(la2));
    ring.push([lo2 * 180 / Math.PI, la2 * 180 / Math.PI]);
  }
  return ring;
}

function drawLows() {
  const lows = [];
  const halos = [];
  S.centers.forEach((c, k) => {
    if (!shown(c)) return;
    // a tracked low by its class from its own motion, else the field's
    const hex = cls(clsOf(c)).hex;
    const deep = isDeep(c);
    const props = { k, hex, deep, terrain: c.terrain };
    if (!c.terrain && classDiffers(c)) props.alt = cls(c.cls).hex;
    lows.push({ type: 'Feature', properties: props, geometry: { type: 'Point', coordinates: [c.lon, c.lat] } });
    if (S.layers.circles && !c.terrain) {
      halos.push({ type: 'Feature', properties: { hex, deep }, geometry: { type: 'Polygon', coordinates: [circle(c.lat, c.lon, +c.radius_km || HALO_KM)] } });
    }
  });
  setData('lows', { type: 'FeatureCollection', features: lows });
  setData('halos', { type: 'FeatureCollection', features: halos });
}

// The product's own square footprint, as CAVE draws it: a dashed outline.
function drawFootprints() {
  const feats = !S.lows || !S.layers.footprint ? [] : S.lows.features.filter((f) => f.geometry?.type !== 'Point')
    .map((f) => ({ ...f, properties: { hex: cls(f.properties?.cls).hex } }));
  setData('footprints', { type: 'FeatureCollection', features: feats });
}

function drawSelection() {
  const c = S.sel?.c;
  setData('sel', c ? { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [c.lon, c.lat] } } : EMPTY);
}

// The low under the pointer: the nearest dot within a few pixels.
function lowAt(pt) {
  if (!map?.getLayer('lows')) return null;
  const fs = map.queryRenderedFeatures([[pt.x - 9, pt.y - 9], [pt.x + 9, pt.y + 9]], { layers: ['lows'] });
  let best = null;
  let bd = Infinity;
  for (const f of fs) {
    const c = S.centers[f.properties.k];
    if (!c) continue;
    const p = map.project([c.lon, c.lat]);
    const d = Math.hypot(p.x - pt.x, p.y - pt.y);
    if (d < bd) { bd = d; best = c; }
  }
  return best;
}

function hoverAt(pt, ll) {
  const onGlobe = map.transform.isPointOnMapSurface(pt);
  $('coords').textContent = onGlobe ? `${K.latText(ll.lat, 2)} ${K.lonText(ll.lng, 2)}` : '';
  const c = onGlobe ? lowAt(pt) : null;
  map.getCanvas().style.cursor = c ? 'pointer' : '';
  const box = $('readout');
  hoverStorm(c ? stormOf(c)?.key ?? null : null, true);
  if (!c) { box.hidden = true; return; }
  box.innerHTML = lowTip(c);
  box.hidden = false;
  const r = $('map').getBoundingClientRect();
  const bw = box.offsetWidth;
  const bh = box.offsetHeight;
  box.style.left = `${pt.x + 14 + bw > r.width ? Math.max(4, pt.x - 14 - bw) : pt.x + 14}px`;
  const top = document.querySelector('.topbar').getBoundingClientRect().bottom + 6;
  const bot = $('timeline').getBoundingClientRect().top - 6;
  box.style.top = `${Math.max(top, Math.min(bot - bh, pt.y - bh / 2))}px`;
}

/* ---------- overlay text ---------- */

let FAM = 'system-ui, sans-serif';
function drawOverlay() {
  if (!map || !S.ready) return;
  ov.clear();
  const ctx = ov.ctx;
  K.graticuleLabels(map, ov, document.querySelector('.topbar').getBoundingClientRect().bottom,
    $('timeline').getBoundingClientRect().top, FAM);
  const z = map.getZoom();
  // contour labels
  if (clabels.length && z >= CLABEL_ZOOM) {
    ctx.font = `600 10.5px ${FAM}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const l of clabels) {
      for (const p of ov.proj(l.lon, l.lat)) {
        const t = String(l.lv);
        const w = ctx.measureText(t).width + 4;
        ctx.fillStyle = 'rgba(255,255,255,0.88)';
        ctx.fillRect(p.x - w / 2, p.y - 6.5, w, 13);
        ctx.fillStyle = l.ink;
        ctx.fillText(t, p.x, p.y);
      }
    }
  }
  drawNames(ctx, z);
}

/* ---------- frames ---------- */

async function show(i) {
  const hours = S.index.hours;
  const n = hours.length;
  S.i = ((i % n) + n) % n;
  const h = hours[S.i];
  syncTime();
  const tok = ++S.token;
  $('progress').classList.add('active');
  const raster = S.field === 'class' ? Promise.resolve(null) : fieldImg(h, S.field);
  const upper = (k) => (S.layers[k] && hasUpper(k) ? getJSON(fileUrl(h, `${UPPER[k]}.geojson`)) : Promise.resolve(null));
  const [lows, mslp, img, z500, thick] = await Promise.allSettled(
    [getJSON(lowsUrl(h)), getJSON(fileUrl(h, 'mslp.geojson')), raster, upper('z500'), upper('thick')]);
  if (tok !== S.token) return true;  // a newer frame was asked for
  $('progress').classList.remove('active');

  const val = (r) => (r.status === 'fulfilled' ? r.value : null);
  S.lows = val(lows);
  S.mslp = val(mslp);
  S.z500 = val(z500);
  S.thick = val(thick);
  S.centers = centersOf(S.lows);
  S.ready = true;
  drawContours();
  drawFootprints();
  drawLows();
  stormsFrame(S.i);
  followFrame();
  refreshCard();
  drawSelection();
  swapRaster(val(img));
  drawJet(h);
  drawOverlay();
  writeHash();

  prefetch(S.i + 1);
  prefetch(S.i + 2);
  const failed = [lows, mslp, img, z500, thick].some((r) => r.status === 'rejected');
  if (failed) K.note(`Part of forecast hour ${h} could not be loaded; showing what arrived.`);
  return !failed;
}

function prefetch(i) {
  const n = S.index.hours.length;
  const h = S.index.hours[((i % n) + n) % n];
  const quiet = (p) => p.catch(() => {});
  quiet(getJSON(lowsUrl(h)));
  quiet(getJSON(fileUrl(h, 'mslp.geojson')));
  for (const k of ['z500', 'thick']) if (S.layers[k] && hasUpper(k)) quiet(getJSON(fileUrl(h, `${UPPER[k]}.geojson`)));
  if (S.layers.jet && hasUpper('jet')) new Image().src = fileUrl(h, 'jet250.png');
  if (S.field !== 'class') quiet(fieldImg(h, S.field));
}

/* ---------- timeline ---------- */

function syncTime() {
  const h = S.index.hours[S.i];
  const v = validAt(S.i);
  const c = utc(S.index.cycle);
  $('lead').value = S.i;
  $('lead').setAttribute('aria-valuetext', `${v ? K.fmtValid(v.toISOString()) : `Hour ${h}`}, forecast hour ${h}`);
  $('validTime').textContent = v ? K.fmtValid(v.toISOString()) : `Hour ${h}`;
  $('validRel').textContent = `+${h} h · ${c ? `${K.fmtTime(c.toISOString())} run` : 'this run'}`;
  $('tlHour').textContent = `+${h} h`;
  $('tlCycle').textContent = v ? K.fmtTime(v.toISOString(), true) : '';
  $('prev').disabled = S.i === 0;
  $('next').disabled = S.i === S.index.hours.length - 1;
  rail?.done(S.i);
}

function play(on) {
  S.playing = on;
  const b = $('play');
  b.innerHTML = K.icon(on ? 'pause' : 'play');
  b.setAttribute('aria-label', on ? 'Pause' : 'Play');
  clearTimeout(S.timer);
  if (on) S.timer = setTimeout(tick, SPEEDS[S.speed]);
}

async function tick() {
  const t0 = performance.now();
  await show(S.i + 1);
  if (!S.playing) return;
  S.timer = setTimeout(tick, Math.max(0, SPEEDS[S.speed] - (performance.now() - t0)));
}

function step(d) {
  play(false);
  const n = S.index.hours.length;
  const k = Math.max(0, Math.min(n - 1, S.i + d));
  if (k !== S.i) show(k);
}

function setSpeed(k) {
  if (!SPEEDS[k]) return;
  S.speed = k;
  document.querySelectorAll('[data-speed]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.speed === k)));
}

/* ---------- field and layers ---------- */

function setField(f, redraw = true) {
  if (!FIELDS.includes(f)) return;
  S.field = f;
  document.querySelectorAll('#fields .product').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.field === f)));
  const raster = f !== 'class';
  $('opacity-row').classList.toggle('off', !raster);
  $('opacity').disabled = !raster;
  if (raster) {
    $('opacity').value = S.opacity[f];
    $('opacityOut').textContent = `${Math.round(S.opacity[f] * 100)}%`;
  }
  $('field-hint').textContent = raster ? 'm, over the whole map' : 'at the low centers';
  syncFadeBox();
  renderLegend();
  if (redraw && S.index) show(S.i);
}

// The fade option applies to the three fields, and only when the export has a mask.
function syncFadeBox() {
  const box = document.querySelector('[data-layer="fade"]');
  if (!box) return;
  const has = !S.index || !!S.index.raster?.mask;
  box.disabled = S.field === 'class' || !has;
  $('fade-row').classList.toggle('off', box.disabled);
  $('fade-row').title = has ? '' : 'This cycle was exported without the fade mask';
}

function setLayer(k, on) {
  if (!(k in S.layers)) return;
  S.layers[k] = on;
  const box = document.querySelector(`[data-layer="${k}"]`);
  if (box) box.checked = on;
  renderLegend();
  if (!S.ready) return;
  if (k === 'contours') drawContours();
  if (k === 'footprint') drawFootprints();
  if (k === 'circles' || k === 'terrain') { drawLows(); renderDeepest(); }
  if (k === 'tracks') drawTracks();
  if (k === 'jet') drawJet(S.index.hours[S.i]);
  if (k === 'z500' || k === 'thick') {
    if (on) { show(S.i); return; }  // fetches this hour's lines
    S[k] = null;
    drawContours();
  }
  if (k === 'fade' && S.field !== 'class') show(S.i);
  drawOverlay();
  writeHash();
}

/* ---------- views, hash, share ---------- */

// Centers, and zoom beyond the whole-globe view (fitting bounds on a globe
// tilts the view toward the pole).
const VIEWS = {
  global: { center: [-40, 30], zoomAdd: 0 },
  natl: { center: [-45, 42], zoomAdd: 0.9 },
  npac: { center: [-170, 42], zoomAdd: 0.9 },
  south: { center: [50, -50], zoomAdd: 0.5 },
};

function setView(key) {
  document.querySelectorAll('[data-view]').forEach((a) => a.setAttribute('aria-checked', String(a.dataset.view === key)));
}

function goView(key) {
  const v = VIEWS[key];
  unfollow();
  const p = viewPadding();
  map.flyTo({ center: v.center, zoom: K.globalZoom() + v.zoomAdd, offset: [(p.left - p.right) / 2, (p.top - p.bottom) / 2],
    bearing: 0, pitch: 0, duration: 900 });
  setView(key);
}

// #t=hour&f=field&v=lat,lon,zoom&l=layers[&s=storm]. Links from the older
// flat map also carry b= (its basemap) and a zoom one step deeper, since
// its tiles were half the size.
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const out = {};
  if (q.has('t')) out.hour = +q.get('t');
  if (FIELDS.includes(q.get('f'))) out.field = q.get('f');
  const v = (q.get('v') || '').split(',').map(Number);
  if (v.length === 3 && v.every(Number.isFinite)) out.view = [v[0], v[1], q.has('b') ? Math.max(0, v[2] - 1) : v[2]];
  if (q.get('s')) out.storm = q.get('s');
  if (q.has('l')) out.layers = q.get('l');
  return out;
}

let hashTimer = 0;
function writeHash() {
  if (!S.index || !map) return;
  clearTimeout(hashTimer);
  hashTimer = setTimeout(() => { try { history.replaceState(null, '', viewHash()); } catch { /* file:// */ } }, 250);
}

function viewHash() {
  const c = map.getCenter();
  const l = Object.entries(LAYER_KEYS).filter(([k]) => (INVERTED_KEYS.has(k) ? !S.layers[k] : S.layers[k])).map(([, v]) => v).join('');
  return `#t=${S.index.hours[S.i]}&f=${S.field}&v=${c.lat.toFixed(2)},${K.wrapLon(c.lng).toFixed(2)},${map.getZoom().toFixed(2)}` +
    `&l=${l || '-'}${S.follow ? `&s=${encodeURIComponent(followShare())}` : ''}`;
}

async function share() {
  if (!S.index) return;
  clearTimeout(hashTimer);
  history.replaceState(null, '', viewHash());
  const b = $('share');
  try {
    await navigator.clipboard.writeText(location.href);
    b.innerHTML = K.icon('check');
    b.setAttribute('aria-label', 'Link copied');
    clearTimeout(share.t);
    share.t = setTimeout(() => { b.innerHTML = K.icon('link'); b.setAttribute('aria-label', 'Copy a link to this view'); }, 1800);
    K.note('Link to this view copied');
  } catch {
    K.note('Link to this view is in the address bar');
  }
}

/* ---------- the phase space card ---------- */

function setSideOpen(open) {
  S.sideOpen = open;
  document.body.classList.toggle('side-open', open);
  $('phase-btn').setAttribute('aria-expanded', String(open));
}

/* ---------- boot ---------- */

function fatal(title, msg, retry) {
  document.body.classList.remove('loading');
  $('fatalTitle').textContent = title;
  $('fatalMsg').innerHTML = msg;
  $('retry').hidden = !retry;
  $('fatal').hidden = false;
}

function closeAbout() {
  $('about').hidden = true;
  $('about-btn').setAttribute('aria-expanded', 'false');
}

function buildControls() {
  const box = $('fields');
  for (const [f, name, key] of FIELD_LIST) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'product';
    b.setAttribute('role', 'radio');
    b.dataset.field = f;
    b.innerHTML = `<i class="product-ramp" data-ramp="${f}"></i><span class="product-name">${name}</span><kbd class="on">${key}</kbd>`;
    b.addEventListener('click', () => { setField(f); if (narrow()) K.setPanelOpen(false); });
    box.append(b);
  }
  $('btnLayers').innerHTML = K.icon('layers');
  $('btnHelp').innerHTML = K.icon('help');
  $('share').innerHTML = K.icon('link');
  $('ph-find-i').innerHTML = K.icon('search');
  for (const id of ['btnPanelClose', 'btnHelpClose', 'about-close', 'phase-close', 'unfollow']) $(id).innerHTML = K.icon('close');
  $('prev').innerHTML = K.icon('prev');
  $('next').innerHTML = K.icon('next');
  $('play').innerHTML = K.icon('play');

  $('btnLayers').addEventListener('click', () => K.setPanelOpen(!K.panelOpen()));
  $('btnPanelClose').addEventListener('click', () => K.setPanelOpen(false));
  $('scrim').addEventListener('click', () => K.setPanelOpen(false));
  $('btnHelp').addEventListener('click', () => $('helpDialog').showModal());
  $('btnHelpClose').addEventListener('click', () => $('helpDialog').close());
  $('about-btn').addEventListener('click', () => { $('about').hidden = false; $('about-btn').setAttribute('aria-expanded', 'true'); });
  $('about-close').addEventListener('click', closeAbout);
  $('about').addEventListener('click', (e) => { if (e.target === $('about')) closeAbout(); });
  $('phase-btn').addEventListener('click', () => setSideOpen(!S.sideOpen));
  $('phase-close').addEventListener('click', () => { closeCard(); if (narrow()) setSideOpen(false); });
  $('share').addEventListener('click', share);
  $('unfollow').addEventListener('click', () => unfollow());
  $('retry').addEventListener('click', () => location.reload());

  $('lead').addEventListener('input', (e) => { play(false); show(+e.target.value); });
  $('prev').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  $('play').addEventListener('click', () => play(!S.playing));
  document.querySelectorAll('[data-speed]').forEach((b) => b.addEventListener('click', () => setSpeed(b.dataset.speed)));
  $('opacity').addEventListener('input', (e) => setOpacity(+e.target.value));
  document.querySelectorAll('[data-layer]').forEach((c) => c.addEventListener('change', () => setLayer(c.dataset.layer, c.checked)));
  document.querySelectorAll('[data-view]').forEach((a) => a.addEventListener('click', () => goView(a.dataset.view)));
  bindSearch();

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (e.target.id === 'ph-q' && e.target.value) return;  // the search clears itself first
      if (!$('about').hidden) closeAbout();
      else if (!$('readout').hidden) $('readout').hidden = true;
      else if (S.sel || S.follow) closeCard();
      else if (narrow()) { K.setPanelOpen(false); setSideOpen(false); }
      return;
    }
    if (!S.index || e.altKey || e.ctrlKey || e.metaKey) return;
    if ($('helpDialog').open || !$('about').hidden) return;
    const t = e.target;
    if (t.matches?.('input[type="text"], input[type="search"], textarea')) return;
    if (t.closest?.('.s3d-canvas')) return;  // the 3-D view rotates with the arrows
    if (t.closest?.('#map')) return;          // the map pans with the arrows
    const k = e.key.toLowerCase();
    let hit = true;
    if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'Home') { play(false); show(0); }
    else if (e.key === 'End') { play(false); show(S.index.hours.length - 1); }
    else if (e.key === ' ' && !t.closest?.('button, a, label')) play(!S.playing);
    else if (/^[1-4]$/.test(e.key)) setField(FIELDS[+e.key - 1]);
    else if (k === 'f') toggleFollow();
    else if (k === 'l') K.setPanelOpen(!K.panelOpen());
    else if (e.key === '?') $('helpDialog').showModal();
    else if (HOTKEYS[k]) setLayer(HOTKEYS[k], !S.layers[HOTKEYS[k]]);
    else hit = false;
    if (hit) e.preventDefault();
  });
}

function showRunMeta(ix) {
  const gen = utc(ix.generated);
  const cyc = utc(ix.cycle);
  const model = ix.model ? ix.model.replace(/\s*deg(ree)?$/i, '').replace(/ 0\.25$/, ' 0.25°') : 'GFS 0.25°';
  $('brand-sub').textContent = `Hart parameters · ${model}`;
  $('foot-model').textContent = model;
  $('about-model').textContent = model;
  const ref = gen || cyc;
  const stale = ref && Date.now() - ref.getTime() > STALE_H * 3600e3;
  const chip = $('chipRun');
  if (cyc) {
    const h = Math.max(0, Math.floor((Date.now() - cyc.getTime()) / 3600e3));
    chip.dataset.state = stale ? 'warn' : 'ok';
    chip.lastChild.textContent = `${K.fmtTime(cyc.toISOString())} run · ${h} h old`;
    chip.title = (gen ? `Generated ${gen.getUTCDate()} ${MON[gen.getUTCMonth()]} ${pad(gen.getUTCHours())}:${pad(gen.getUTCMinutes())} UTC (${ago(gen)})` : 'Age of the model run on this page') +
      (stale ? '; a newer run is overdue' : '');
  }
  $('stale').hidden = !stale;
  if (stale) $('stale').textContent = `Data may be stale; last cycle ${fmtCycle(ix.cycle)}, ${gen ? `generated ${ago(gen)}` : 'no generation time'}.`;
}

// Map and data both in: draw the first frame.
let want = {};
async function ready() {
  if (!S.mapReady || !S.index) return;
  syncUpperBoxes();
  await show(S.i);
  document.body.classList.remove('loading');
  loadAllLows().then(() => { if (want.storm) follow(want.storm, { quiet: !!want.view }); });
}

async function boot() {
  S.base ??= await resolveBase();
  try {
    S.index = await fetchJSON(new URL('index.json', S.base).href, { cache: 'no-cache' });
    if (!Array.isArray(S.index.hours) || !S.index.hours.length) throw new Error('no forecast hours');
  } catch {
    S.index = null;
    const chip = $('chipRun');
    chip.dataset.state = 'error';
    chip.lastChild.textContent = 'No run available';
    fatal('No live data yet', `The run has not published a cycle yet, or it could not be reached. The map will show the latest cycle as soon as one is published. Looked for <code>${esc(S.base)}index.json</code>.`, true);
    return;
  }
  try {
    S.legend = await fetchJSON(new URL('legend.json', S.base).href, { cache: 'no-cache' });
  } catch {
    S.legend = null;  // fall back to the built-in class palette
  }
  S.bust = `?v=${encodeURIComponent(S.index.cycle || S.index.generated || '')}`;
  S.classes.clear();
  const list = S.legend?.classes?.length ? S.legend.classes : FALLBACK_HEX.map((hex, code) => ({ code, hex }));
  for (const c of list) S.classes.set(c.code, { code: c.code, hex: c.hex, name: CLASS_NAMES[c.code] || c.name });

  const ix = S.index;
  showRunMeta(ix);
  setInterval(() => showRunMeta(ix), 60e3);
  $('lead').max = ix.hours.length - 1;
  $('lead').disabled = ix.hours.length < 2;
  $('play').disabled = ix.hours.length < 2;
  rail = K.timeline(ix.hours.map((h, k) => (validAt(k) || new Date()).toISOString()));

  want = readHash();
  if (want.layers) {
    for (const [k, v] of Object.entries(LAYER_KEYS)) setLayer(k, INVERTED_KEYS.has(k) ? !want.layers.includes(v) : want.layers.includes(v));
  }
  const hi = ix.hours.indexOf(want.hour);
  S.i = hi >= 0 ? hi : 0;
  setField(want.field || S.field, false);
  paintRamps();
  initStorms();
  $('foot-b').hidden = !ST.trackB;
  renderLegend();  // its keys depend on the tracks' B
  syncTime();
  const start = want.view ? { center: [want.view[1], want.view[0]], zoom: want.view[2] } : { center: VIEWS.global.center, zoom: K.globalZoom() };
  setView(want.view ? null : 'global');
  buildMap(start);
}

function start() {
  document.querySelectorAll('[data-link]').forEach((a) => {
    a.href = { article: ARTICLE_URL, guide: GUIDE_URL }[a.dataset.link] || a.href;
  });
  FAM = getComputedStyle(document.body).fontFamily;
  // The class legend at once, from the built-in palette, so nothing reflows on load.
  FALLBACK_HEX.forEach((hex, code) => S.classes.set(code, { code, hex, name: CLASS_NAMES[code] }));
  buildControls();
  K.setPanelOpen(!narrow());
  setSideOpen(!narrow());
  setField(S.field, false);
  renderCard(null, null);
  if (!K.webgl()) {
    fatal('Map could not start', `This page needs a browser with WebGL enabled. The <a href="${ARTICLE_URL}">article</a> explains the products.`, false);
    return;
  }
  boot();
}

start();
