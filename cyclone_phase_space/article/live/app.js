/* Cyclone Phase Space, live: the map, frames, timeline and controls.
   The low centers, MSLP contours, the thermal asymmetry and thermal wind
   rasters and the storm tracks, animated over the forecast hours of the
   latest cycle.
   storms.js (storm panel, follow mode) and card.js (readout at a low) use
   the globals defined here; this file loads last and starts the page.
   Plain ES2020, no build step. */
'use strict';

const FALLBACK_DATA = 'https://raw.githubusercontent.com/jkrek17/awips-tools/cps-live/latest/';
const LOCAL_DATA = 'data/latest/';  // beside the page when served from the web repository
const ARTICLE_URL = 'https://jkrek17.github.io/awips-tools/cps/';
const SPACE_URL = ARTICLE_URL + 'figures/phase_space_3d.html';
const LABEL_ZOOM = 4;            // MSLP labels at centers and on contours from this zoom
const SPEEDS = { slow: 1200, normal: 700, fast: 350 };  // ms per frame
const MAX_RASTER_FRAMES = 12;    // decoded raster frames kept in memory
const MATCH_KM = 300;            // center to storm matching radius, for entries without run ids
const HALO_KM = 200;             // radius of the circle drawn at each low
const DEEP_HPA = 980;            // lows below this get a larger dot
const TERRAIN_HPA = 850;         // surface pressure below this: a false low over high ground
const STALE_H = 12;              // hours before the data is called stale
const OFFSETS = [-360, 0, 360];  // world copies, so overlays wrap the dateline
const RASTERS = ['hb', 'hvtl', 'hvtu'];
const FIELDS = ['class', ...RASTERS];
const LAYER_KEYS = { contours: 'c', circles: 'h', footprint: 'p', tracks: 'k', terrain: 'g' };

// Display names for the class codes; hex always comes from legend.json.
const CLASS_NAMES = [
  'Symmetric deep warm core', 'Symmetric shallow warm core',
  'Asymmetric deep warm core', 'Asymmetric shallow warm core',
  'Asymmetric cold core', 'Symmetric cold core', 'Shallow cold core',
];
const FALLBACK_HEX = ['#d92626', '#cc33bf', '#fad91a', '#33ad40', '#2680e6', '#5938b8', '#b8b8b2'];

const MINUS = '−';

// The three Hart terms: a plain name, the symbol (HTML), and the layer.
const TERM = {
  hb: { name: 'Thermal asymmetry', sym: 'B', band: '900 to 600 hPa' },
  hvtl: { name: 'Lower thermal wind', sym: `${MINUS}V<sub>T</sub><sup>L</sup>`, band: '925 to 700 hPa' },
  hvtu: { name: 'Upper thermal wind', sym: `${MINUS}V<sub>T</sub><sup>U</sup>`, band: '500 to 300 hPa' },
};
const termHTML = (f) => `${TERM[f].name} (${TERM[f].sym})`;

// Legend titles (HTML).
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
// Reading notes per field, from the user guide.
const HELP = {
  class: 'Read the class at the center dot, never the footprint edge. A transition runs red, yellow, green, blue (codes 0, 2, 3, 4).',
  hb: 'Magenta: warm air to the right of the deep-layer flow, the frontal geometry; teal: warm air on the left. More than 10 m at a low center is asymmetric (Hart\'s onset line, marked). Transparent within 5 m of zero.',
  hvtl: 'Red is a warm lower core, blue a cold one. A hurricane reads +100 to +300 m; a center falling below 0 marks transition complete. Transparent within about 37 m of zero.',
  hvtu: 'Red is a warm upper core, blue is cold aloft. The upper core usually turns blue first as a transition gets under way. Transparent within about 37 m of zero.',
};

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const $ = (id) => document.getElementById(id);
const pad = (n, w = 2) => String(n).padStart(w, '0');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const narrow = () => innerWidth <= 760;

const S = {
  base: null, index: null, legend: null, classes: new Map(),
  i: 0, field: 'class', playing: false, timer: 0, token: 0,
  speed: 'normal', loop: true, basemap: 'plain', bust: '',
  opacity: { hb: 0.7, hvtl: 0.8, hvtu: 0.8 },
  layers: { contours: true, circles: true, footprint: false, tracks: true, terrain: false },
  centers: [], offs: OFFSETS, sel: null, follow: null, perf: [], cint: null,
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
  return `${sign}${s}${u ? ` ${u}` : ''}`;
}
const hpa = (v) => fmt(v, 1, 'hPa');
function pos(lat, lon) {
  const w = ((((lon + 180) % 360) + 360) % 360) - 180;
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
const fmtValid = (d) => `${fmtDay(d)} ${d.getUTCFullYear()}, ${pad(d.getUTCHours())} UTC`;
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

let toastTimer = 0;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3600);
}

/* ---------- map ---------- */

let map, basemap, contourG, clabelG, haloG, footG, lowG, nameG, selG, trackG, tailG;
let contourR, haloR, footR, trackR, tailR;

function initMap(zoom) {
  map = L.map('map', {
    worldCopyJump: true, minZoom: 1, maxZoom: 10, zoomControl: false,
    center: [30, -40], zoom, zoomSnap: 0.5,
    maxBounds: [[-88, -1e5], [88, 1e5]], maxBoundsViscosity: 1,
  });
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  map.attributionControl.setPosition('bottomleft');
  L.control.zoom({ position: 'bottomleft' }).addTo(map);

  // Panes, bottom to top: rasters, contours, footprints, circles, tracks,
  // tile labels, contour labels; markers and tooltips sit above.
  [['rasters', 350], ['contours', 380], ['footprints', 400], ['halos', 405],
    ['tracks', 420], ['labels', 450], ['clabels', 460]]
    .forEach(([n, z]) => { map.createPane(n).style.zIndex = z; });
  map.getPane('labels').style.pointerEvents = 'none';
  map.getPane('clabels').style.pointerEvents = 'none';

  basemap = CPSBasemap.create(map, { insets: chromeInsets });

  contourR = L.canvas({ pane: 'contours', padding: 0.3 });
  footR = L.svg({ pane: 'footprints', padding: 0.3 });
  haloR = L.svg({ pane: 'halos', padding: 0.3 });
  trackR = L.svg({ pane: 'tracks', padding: 0.3 });
  tailR = L.canvas({ pane: 'tracks', padding: 0.3 });
  contourG = L.layerGroup().addTo(map);
  clabelG = L.layerGroup().addTo(map);
  footG = L.layerGroup().addTo(map);
  haloG = L.layerGroup().addTo(map);
  tailG = L.layerGroup().addTo(map);
  trackG = L.layerGroup().addTo(map);
  selG = L.layerGroup().addTo(map);
  lowG = L.layerGroup().addTo(map);
  nameG = L.layerGroup().addTo(map);

  const zoomClass = () => map.getContainer().classList.toggle('labels-off', map.getZoom() < LABEL_ZOOM);
  map.on('zoomend', zoomClass);
  zoomClass();
  map.on('moveend', () => { checkOffsets(); drawContourLabels(); writeHash(); });
  map.on('dragstart', () => document.querySelectorAll('[data-basin]').forEach((c) => c.removeAttribute('aria-pressed')));
}

const shift = (o) => (c) => L.latLng(c[1], c[0] + o);

// World copies that touch the view, padded by up to 30 degrees; frame
// layers draw only these, and a pan that needs another copy redraws them.
function viewOffsets() {
  const b = map.getBounds();
  const pad = Math.min((b.getEast() - b.getWest()) / 2, 30);
  const w = b.getWest() - pad;
  const e = b.getEast() + pad;
  return OFFSETS.filter((o) => o - 180 < e && o + 180 > w);
}
function checkOffsets() {
  const offs = viewOffsets();
  if (!S.index || offs.join() === S.offs.join()) return;
  S.offs = offs;
  drawContours(S.mslp);
  drawFootprints(S.lows);
  drawLows();
  drawSelection();
  drawTails();
  drawNames();
}

// Center a point in the part of the map not covered by panels, without
// animation, on the world copy nearest the current view.
function centerOn(lat, lon, zoom) {
  const z = zoom ?? map.getZoom();
  const c = map.getCenter();
  const lng = lon + 360 * Math.round((c.lng - lon) / 360);
  const ins = visibleInsets();
  const p = map.project([lat, lng], z).add(L.point((ins.right - ins.left) / 2, (ins.bottom - ins.top) / 2));
  map.setView(map.unproject(p, z), z, { animate: false });
}

/* ---------- rasters: two overlay sets, crossfaded ---------- */

const RS = { sets: [], front: 0, url: null, tok: 0 };

function rasterSets(url) {
  if (RS.sets.length) return;
  const [[s, w], [n, e]] = S.index.raster?.bounds || [[-85, -180], [85, 180]];
  RS.sets = [0, 1].map(() => OFFSETS.map((o) => L.imageOverlay(url, [[s, w + o], [n, e + o]],
    { pane: 'rasters', opacity: 0, interactive: false, alt: '', className: 'raster' }).addTo(map)));
  RS.sets[1].forEach((ov) => { ov._cpsBlank = true; });
}

function overlayReady(ov, url) {
  const im = ov.getElement();
  if (ov._url === url && !ov._cpsBlank && im?.complete && im.naturalWidth) return Promise.resolve();
  ov._cpsBlank = false;
  return new Promise((res) => {
    ov.once('load error', res);
    if (ov._url === url && im && !im.complete) return;
    ov.setUrl(url);
  });
}

// Swap the displayed raster: load the hidden set, then crossfade (CSS, 150 ms).
function swapRaster(url) {
  const tok = ++RS.tok;
  const op = S.opacity[S.field] ?? 0.8;
  if (!url) {
    RS.sets.flat().forEach((ov) => ov.setOpacity(0));
    RS.url = null;
    return;
  }
  rasterSets(url);
  if (url === RS.url) {
    RS.sets[RS.front].forEach((ov) => ov.setOpacity(op));
    return;
  }
  const back = RS.front === 0 && RS.url === null && !RS.sets[0][0]._cpsShown ? 0 : 1 - RS.front;
  Promise.all(RS.sets[back].map((ov) => overlayReady(ov, url))).then(() => {
    if (tok !== RS.tok) return;
    RS.sets[back].forEach((ov) => { ov.setOpacity(op); ov._cpsShown = true; });
    if (back !== RS.front) RS.sets[RS.front].forEach((ov) => ov.setOpacity(0));
    RS.front = back;
    RS.url = url;
  });
}

function setOpacity(v) {
  if (S.field === 'class') return;
  S.opacity[S.field] = v;
  $('opacity-out').textContent = v.toFixed(2);
  if (RS.url) RS.sets[RS.front].forEach((ov) => ov.setOpacity(v));
}

/* ---------- contours ---------- */

// Contours come as many short LineStrings; draw them as two polylines per
// world copy (major every 16 hPa, minor between) to keep the frame swap cheap.
function drawContours(fc) {
  contourG.clearLayers();
  S.cmids = [];
  if (!fc || !S.layers.contours) { drawContourLabels(); return; }
  const lines = { major: [], minor: [] };
  const levels = new Set();
  for (const f of fc.features) {
    const lv = Math.round(f.properties?.level);
    const g = f.geometry;
    if (!g) continue;
    levels.add(lv);
    const parts = g.type === 'MultiLineString' ? g.coordinates : [g.coordinates];
    const major = lv % 16 === 0;
    for (const p of parts) {
      (major ? lines.major : lines.minor).push(p);
      if (major && p.length >= 8) {
        const m = p[Math.floor(p.length / 2)];
        S.cmids.push({ lat: m[1], lon: m[0], lv });
      }
    }
  }
  const lv = [...levels].sort((a, b) => a - b);
  let step = Infinity;
  for (let k = 1; k < lv.length; k++) step = Math.min(step, lv[k] - lv[k - 1]);
  if (Number.isFinite(step) && step !== S.cint) {
    S.cint = step;
    $('cint').textContent = `MSLP every ${step} hPa, bold every 16 hPa`;
  }
  const style = {
    major: { color: '#dcdcd8', weight: 1.2, opacity: 0.62 },
    minor: { color: '#dcdcd8', weight: 0.8, opacity: 0.3 },
  };
  for (const o of S.offs) {
    for (const k of ['minor', 'major']) {
      const ll = lines[k].map((p) => p.map(shift(o)));
      contourG.addLayer(L.polyline(ll, { ...style[k], renderer: contourR, interactive: false, smoothFactor: 1 }));
    }
  }
  drawContourLabels();
}

// One label per major contour line, at its middle vertex, zoom 4 and up.
function drawContourLabels() {
  clabelG.clearLayers();
  if (!S.cmids?.length || !S.layers.contours || map.getZoom() < LABEL_ZOOM) return;
  const b = map.getBounds().pad(0.05);
  const lows = S.centers.filter(shown);
  let n = 0;
  for (const m of S.cmids) {
    if (lows.some((c) => Math.abs(c.lat - m.lat) < 3 && km(c.lat, c.lon, m.lat, m.lon) < 250)) continue;  // keep clear of low labels
    for (const o of S.offs) {
      const ll = L.latLng(m.lat, m.lon + o);
      if (!b.contains(ll)) continue;
      clabelG.addLayer(L.tooltip({ permanent: true, direction: 'center', className: 'clabel', pane: 'clabels', interactive: false })
        .setLatLng(ll).setContent(String(m.lv)));
      if (++n >= 120) return;
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

function lowIcon(c) {
  const hex = cls(c.cls).hex;
  const deep = !blank(c.mslp) && +c.mslp < DEEP_HPA;
  return L.divIcon({
    className: `low${deep ? ' deep' : ''}${c.terrain ? ' terrain' : ''}`,
    iconSize: [24, 24], iconAnchor: [12, 12],
    html: `<i style="--c:${hex}"></i>${blank(c.mslp) ? '' : `<b>${Math.round(+c.mslp)}</b>`}`,
  });
}

function drawLows() {
  lowG.clearLayers();
  haloG.clearLayers();
  for (const c of S.centers) {
    if (!shown(c)) continue;
    const hex = cls(c.cls).hex;
    const deep = !blank(c.mslp) && +c.mslp < DEEP_HPA;
    for (const o of S.offs) {
      if (S.layers.circles && !c.terrain) {
        haloG.addLayer(L.circle([c.lat, c.lon + o], {
          renderer: haloR, radius: (+c.radius_km || HALO_KM) * 1e3, interactive: false,
          color: hex, weight: deep ? 1.5 : 1, opacity: 0.7, fillColor: hex, fillOpacity: 0.06,
        }));
      }
      const m = L.marker([c.lat, c.lon + o], {
        icon: lowIcon(c), keyboard: o === 0, riseOnHover: true,
        alt: `${cls(c.cls).name}, ${hpa(c.mslp)}`,
      });
      m.bindTooltip(() => lowTip(c), { direction: 'top', offset: [0, -8], className: 'low-tip', opacity: 1 });
      m.on('click', () => selectLow(c));
      m.on('mouseover', () => hoverStorm(stormOf(c)?.key ?? null, true));
      m.on('mouseout', () => hoverStorm(null));
      lowG.addLayer(m);
    }
  }
}

// The product's own square footprint, as CAVE draws it: a dashed outline.
function drawFootprints(fc) {
  footG.clearLayers();
  if (!fc || !S.layers.footprint) return;
  const blobs = { type: 'FeatureCollection', features: fc.features.filter((f) => f.geometry?.type !== 'Point') };
  for (const o of S.offs) {
    footG.addLayer(L.geoJSON(blobs, {
      renderer: footR, coordsToLatLng: shift(o), interactive: false,
      style: (f) => ({ color: cls(f.properties.cls).hex, weight: 1, opacity: 0.9, dashArray: '3 3', fill: false }),
    }));
  }
}

function drawSelection() {
  selG.clearLayers();
  const c = S.sel?.c;
  if (!c) return;
  for (const o of S.offs) {
    selG.addLayer(L.circleMarker([c.lat, c.lon + o], {
      renderer: trackR, radius: 10, color: '#f2f1ec', weight: 1.5, opacity: 1, fill: false, interactive: false,
    }));
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
    [getJSON(lowsUrl(h)), getJSON(fileUrl(h, 'mslp.geojson')), raster]);
  if (tok !== S.token) return true;  // a newer frame was asked for

  const val = (r) => (r.status === 'fulfilled' ? r.value : null);
  const t0 = performance.now();
  S.offs = viewOffsets();
  S.lows = val(lows);
  S.mslp = val(mslp);
  S.centers = centersOf(S.lows);
  drawContours(S.mslp);
  drawFootprints(S.lows);
  drawLows();
  stormsFrame(S.i);
  followFrame();
  refreshCard();
  drawSelection();
  S.perf.push(performance.now() - t0);
  if (S.perf.length > 200) S.perf.shift();
  swapRaster(val(img));
  writeHash();

  prefetch(S.i + 1);
  prefetch(S.i + 2);
  const failed = [lows, mslp, img].some((r) => r.status === 'rejected');
  if (failed) toast(`Part of forecast hour ${h} could not be loaded; showing what arrived.`);
  return !failed;
}

function prefetch(i) {
  const n = S.index.hours.length;
  if (!S.loop && i >= n) return;
  const h = S.index.hours[((i % n) + n) % n];
  const quiet = (p) => p.catch(() => {});
  quiet(getJSON(lowsUrl(h)));
  quiet(getJSON(fileUrl(h, 'mslp.geojson')));
  if (S.field !== 'class') quiet(loadImg(rasterUrl(h, S.field), h));
}

/* ---------- timeline ---------- */

function syncTime() {
  const slider = $('frame');
  const h = S.index.hours[S.i];
  const v = validAt(S.i);
  const label = v ? fmtValid(v) : `Hour ${h}`;
  slider.value = S.i;
  slider.setAttribute('aria-valuetext', `${label}, forecast hour ${h}`);
  $('when-valid').textContent = label;
  $('when-fhr').textContent = `F${pad(h, 3)}, ${h} h after the ${fmtCycle(S.index.cycle)} run`;
}

// Day ticks under the scrubber: a tall tick and label at each 00 UTC frame.
function buildScrubTicks() {
  if (!S.index) return;
  const n = S.index.hours.length;
  const box = $('scrub-ticks');
  if (n < 2) { box.innerHTML = ''; return; }
  const w = box.getBoundingClientRect().width || 600;
  const days = [];
  let html = '';
  for (let k = 0; k < n; k++) {
    const v = validAt(k);
    const f = k / (n - 1);
    const day = v && v.getUTCHours() === 0;
    html += `<i class="${day ? 'day' : ''}" style="left:calc(6px + (100% - 12px) * ${f.toFixed(4)})"></i>`;
    if (day) days.push({ f, v });
  }
  const gap = days.length > 1 ? (days[1].f - days[0].f) * (w - 12) : w;
  const long = gap >= 52;
  for (const { f, v } of days) {
    if (f > 0.97) continue;
    html += `<span style="left:calc(6px + (100% - 12px) * ${f.toFixed(4)})">${long ? `${DOW[v.getUTCDay()]} ${v.getUTCDate()}` : v.getUTCDate()}</span>`;
  }
  box.innerHTML = html;
}

function play(on) {
  if (on && !S.loop && S.i >= S.index.hours.length - 1) show(0);
  S.playing = on;
  const b = $('play');
  b.setAttribute('aria-pressed', String(on));
  b.setAttribute('aria-label', on ? 'Pause' : 'Play');
  clearTimeout(S.timer);
  if (on) S.timer = setTimeout(tick, SPEEDS[S.speed]);
}

async function tick() {
  const t0 = performance.now();
  if (!S.loop && S.i >= S.index.hours.length - 1) { play(false); return; }
  await show(S.i + 1);
  if (!S.playing) return;
  S.timer = setTimeout(tick, Math.max(0, SPEEDS[S.speed] - (performance.now() - t0)));
}

function setSpeed(k) {
  if (!SPEEDS[k]) return;
  S.speed = k;
  document.querySelectorAll('[data-speed]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.speed === k)));
}

/* ---------- field and legend ---------- */

function setField(f, redraw = true) {
  if (!FIELDS.includes(f)) return;
  S.field = f;
  const input = document.querySelector(`input[name="field"][value="${f}"]`);
  if (input) input.checked = true;
  const raster = f !== 'class';
  $('opacity-wrap').classList.toggle('off', !raster);
  $('opacity').disabled = !raster;
  if (raster) {
    $('opacity').value = S.opacity[f];
    $('opacity-out').textContent = S.opacity[f].toFixed(2);
  }
  document.body.classList.toggle('raster-on', raster);
  renderLegend();
  if (redraw) show(S.i);
}

function setLayer(k, on) {
  if (!(k in S.layers)) return;
  S.layers[k] = on;
  const box = document.querySelector(`[data-layer="${k}"]`);
  if (box) box.checked = on;
  if (!S.index) return;
  if (k === 'contours') drawContours(S.mslp);
  if (k === 'footprint') drawFootprints(S.lows);
  if (k === 'circles' || k === 'terrain') { drawLows(); stormsFrame(S.i); }
  if (k === 'tracks') drawTracks();
  writeHash();
}

/* ---------- regions, basemap, hash, share ---------- */

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

function setBasemap(key) {
  S.basemap = basemap.set(key);
  document.querySelectorAll('[data-base]').forEach((c) =>
    c.setAttribute('aria-pressed', String(c.dataset.base === S.basemap)));
  writeHash();
}

function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const out = {};
  if (q.has('t')) out.hour = +q.get('t');
  if (FIELDS.includes(q.get('f'))) out.field = q.get('f');
  const v = (q.get('v') || '').split(',').map(Number);
  if (v.length === 3 && v.every(Number.isFinite)) out.view = v;
  if (q.get('s')) out.storm = q.get('s');
  if (q.has('l')) out.layers = q.get('l');
  return out;
}

let hashTimer = 0;
function writeHash() {
  if (!S.index || !map) return;
  clearTimeout(hashTimer);
  hashTimer = setTimeout(() => history.replaceState(null, '', viewHash()), 250);
}

function viewHash() {
  const c = map.getCenter().wrap();
  const l = Object.entries(LAYER_KEYS).filter(([k]) => S.layers[k]).map(([, v]) => v).join('');
  return `#t=${S.index.hours[S.i]}&f=${S.field}&b=${S.basemap}&v=${c.lat.toFixed(2)},${c.lng.toFixed(2)},${map.getZoom()}` +
    `&l=${l || '-'}${S.follow ? `&s=${encodeURIComponent(followShare())}` : ''}`;
}

async function share() {
  if (!S.index) return;
  clearTimeout(hashTimer);
  history.replaceState(null, '', viewHash());
  try {
    await navigator.clipboard.writeText(location.href);
    toast('Link to this view copied');
  } catch {
    toast('Link to this view is in the address bar');
  }
}

/* ---------- popovers ---------- */

const pops = [];
function popover(btn, pop) {
  pops.push([btn, pop]);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = pop.hidden;
    closePops();
    pop.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
  });
}
function closePops(except) {
  let closed = false;
  for (const [b, p] of pops) {
    if (p === except || p.hidden) continue;
    p.hidden = true;
    b.setAttribute('aria-expanded', 'false');
    closed = true;
  }
  return closed;
}

/* ---------- layout ---------- */

function rect(el) {
  return el && !el.hidden && getComputedStyle(el).display !== 'none' ? el.getBoundingClientRect() : null;
}

// Map space covered by the page chrome, for centering and the edge labels.
// Cached between layout changes so a frame swap never forces a layout.
let insetCache = null;
const dropInsets = () => { insetCache = null; };
function visibleInsets() {
  return (insetCache ??= readInsets());
}
function readInsets() {
  const top = rect($('topbar'));
  const bar = rect($('bar'));
  const st = document.body.classList.contains('storms-open') ? rect($('storms')) : null;
  const card = rect($('card'));
  const wide = !narrow();
  return {
    top: top ? top.bottom : 0,
    bottom: Math.max(bar ? innerHeight - bar.top : 0, !wide && card ? innerHeight - card.top : 0),
    left: wide && card ? card.right : 0,
    right: wide && st ? innerWidth - st.left : 0,
  };
}

function chromeInsets() {
  const ins = visibleInsets();
  return { top: Math.round(ins.top + 4), left: Math.round(ins.top), bottom: Math.round(ins.bottom) };
}

// Keep Leaflet's corner controls and toasts clear of the bottom bar.
function measure() {
  dropInsets();
  const root = document.documentElement.style;
  const bar = $('bar').getBoundingClientRect();
  root.setProperty('--bar-h', `${Math.round(innerHeight - bar.top)}px`);
  root.setProperty('--top-h', `${Math.round($('topbar').getBoundingClientRect().bottom)}px`);
  basemap?.edges();
}

function setStormsOpen(open) {
  dropInsets();
  document.body.classList.toggle('storms-open', open);
  $('storms-btn').setAttribute('aria-expanded', String(open));
  if (open && narrow()) closeCard();
  basemap?.edges();
}

/* ---------- boot ---------- */

function noData(title, msg) {
  document.body.classList.remove('loading');
  document.body.classList.add('empty');
  $('run-meta').textContent = 'No cycle loaded';
  $('nodata-title').textContent = title;
  $('nodata-text').innerHTML = msg;
  $('nodata').classList.remove('hidden');
}

function bindControls() {
  $('frame').addEventListener('input', (e) => { play(false); show(+e.target.value); });
  $('play').addEventListener('click', () => play(!S.playing));
  $('loop').addEventListener('change', (e) => { S.loop = e.target.checked; });
  document.querySelectorAll('[data-speed]').forEach((b) => b.addEventListener('click', () => setSpeed(b.dataset.speed)));
  document.querySelectorAll('input[name="field"]').forEach((r) =>
    r.addEventListener('change', () => setField(r.value)));
  $('opacity').addEventListener('input', (e) => setOpacity(+e.target.value));
  document.querySelectorAll('[data-layer]').forEach((c) =>
    c.addEventListener('change', () => setLayer(c.dataset.layer, c.checked)));
  document.querySelectorAll('[data-basin]').forEach((b) => b.addEventListener('click', () => {
    const [c, z] = basinView(b.dataset.basin);
    unfollow();
    map.setView(c, z, { animate: false });
    document.querySelectorAll('[data-basin]').forEach((x) =>
      (x === b ? x.setAttribute('aria-pressed', 'true') : x.removeAttribute('aria-pressed')));
  }));
  document.querySelectorAll('[data-base]').forEach((c) =>
    c.addEventListener('click', () => setBasemap(c.dataset.base)));
  $('share').addEventListener('click', share);
  $('retry').addEventListener('click', () => { S.base = null; boot(); });
  $('storms-btn').addEventListener('click', () => setStormsOpen(!document.body.classList.contains('storms-open')));
  $('storms-close').addEventListener('click', () => setStormsOpen(false));
  $('unfollow').addEventListener('click', () => unfollow());
  bindStormFilter();

  popover($('menu-btn'), $('menu'));
  popover($('layers-btn'), $('layers'));
  popover($('legend-btn'), $('key'));
  document.addEventListener('pointerdown', (e) => {
    if (!e.target.closest('.popover, .pop-wrap')) closePops();
  });

  // Left and right step frames (captured before Leaflet pans); space plays.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!closePops()) closeCard();
      return;
    }
    if (!S.index || e.altKey || e.ctrlKey || e.metaKey) return;
    const t = e.target;
    if (t.matches?.('input[type="range"], input[type="text"], input[type="search"], textarea')) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      play(false);
      const n = S.index.hours.length;
      const next = S.i + (e.key === 'ArrowRight' ? 1 : -1);
      if (S.loop || (next >= 0 && next < n)) show(next);
    } else if (e.key === ' ' && !t.closest?.('button, a, label, .leaflet-marker-icon')) {
      e.preventDefault();
      play(!S.playing);
    } else if (/^[1-4]$/.test(e.key) && !t.closest?.('input')) {
      setField(FIELDS[+e.key - 1]);
    } else if ((e.key === 'f' || e.key === 'F') && !t.closest?.('input')) {
      toggleFollow();
    }
  }, true);

  // Phones: speed and loop move into the Layers popover to keep the bar short.
  const mq = matchMedia('(max-width: 760px)');
  const placePlayOpts = () => {
    const opts = $('play-opts');
    const home = mq.matches ? $('layers-play') : $('layers-btn').parentElement;
    if (opts.parentElement !== home) (mq.matches ? home.append(opts) : home.before(opts));
  };
  mq.addEventListener('change', placePlayOpts);
  placePlayOpts();

  const ro = new ResizeObserver(() => { measure(); buildScrubTicks(); });
  ro.observe($('bar'));
  ro.observe($('topbar'));
  addEventListener('resize', measure);
}

function showRunMeta(ix) {
  const gen = utc(ix.generated);
  $('run-meta').innerHTML =
    `<span>${esc(ix.model || 'Model')}</span><span>run ${esc(fmtCycle(ix.cycle))}</span>` +
    (gen ? `<span class="gen">generated ${gen.getUTCDate()} ${MON[gen.getUTCMonth()]} ${pad(gen.getUTCHours())}:${pad(gen.getUTCMinutes())} UTC (${ago(gen)})</span>` : '');
  $('methods-model').textContent = ix.model ? ix.model.replace(/\s*deg(ree)?$/i, '') : 'GFS 0.25';
  const ref = gen || utc(ix.cycle);
  const stale = ref && Date.now() - ref.getTime() > STALE_H * 3600e3;
  $('stale').hidden = !stale;
  if (stale) $('stale').textContent = `Data may be stale; last cycle ${fmtCycle(ix.cycle)}, ${gen ? `generated ${ago(gen)}` : 'no generation time'}.`;
}

async function boot() {
  $('nodata').classList.add('hidden');
  document.body.classList.remove('empty');
  document.body.classList.add('loading');
  S.base ??= await resolveBase();
  try {
    S.index = await fetchJSON(new URL('index.json', S.base).href, { cache: 'no-cache' });
    if (!Array.isArray(S.index.hours) || !S.index.hours.length) throw new Error('no forecast hours');
  } catch (err) {
    S.index = null;
    noData('No live data yet', `The daily run has not published a cycle yet, or it could not be reached. The map will show the latest cycle as soon as one is published. Looked for <code>${esc(S.base)}index.json</code>.`);
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
  const slider = $('frame');
  slider.max = ix.hours.length - 1;
  slider.disabled = ix.hours.length < 2;
  $('play').disabled = ix.hours.length < 2;

  const want = readHash();
  if (want.view) map.setView([want.view[0], want.view[1]], want.view[2], { animate: false });
  if (want.layers) {
    for (const [k, v] of Object.entries(LAYER_KEYS)) setLayer(k, want.layers.includes(v));
  }
  const hi = ix.hours.indexOf(want.hour);
  S.i = hi >= 0 ? hi : 0;
  setField(want.field || S.field, false);
  initStorms();
  drawTracks();
  buildScrubTicks();
  await show(S.i);
  document.body.classList.remove('loading');
  measure();
  loadAllLows().then(() => { if (want.storm) follow(want.storm, { quiet: !!want.view }); });
}

function start() {
  document.querySelectorAll('[data-link]').forEach((a) => {
    a.href = { article: ARTICLE_URL, space: SPACE_URL }[a.dataset.link];
  });
  if (!window.L) {
    noData('The map could not start', `The map library could not be loaded. Check the connection, or read the <a href="${ARTICLE_URL}">article</a> in the meantime.`);
    $('retry').addEventListener('click', () => location.reload());
    return;
  }
  initMap(narrow() ? 2 : innerWidth < 1200 ? 2.5 : 3);
  setBasemap(CPSBasemap.saved());
  setStormsOpen(innerWidth >= 1000);
  bindControls();
  measure();
  boot();
}

start();
