/* Basemaps for the live CPS map. "Plain" is self-hosted Natural Earth
   drawn on canvas (land, lakes, coastlines, borders) and is the default;
   Dark, Satellite and Night are keyless tile services with Esri's dark
   reference labels on top. A 10 degree graticule with edge labels is drawn
   under every basemap. Plain ES2020, used by app.js. */
'use strict';

const CPSBasemap = (() => {
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
  const GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/';
  const ESRI_ATTR = 'Tiles: Esri, HERE, Garmin, FAO, NOAA, USGS';
  const NE_ATTR = 'Basemap: <a href="https://www.naturalearthdata.com">Natural Earth</a>';
  const TILES = {
    dark: { url: `${ESRI}World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, maxNativeZoom: 16, attribution: ESRI_ATTR },
    sat: { url: `${GIBS}BlueMarble_ShadedRelief_Bathymetry/default/2004-08-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`,
      maxNativeZoom: 8, attribution: `NASA GIBS &middot; Labels: ${ESRI_ATTR}` },
    night: { url: `${GIBS}VIIRS_CityLights_2012/default/2012-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg`,
      maxNativeZoom: 8, attribution: `NASA GIBS &middot; Labels: ${ESRI_ATTR}` },
  };
  const LABELS = `${ESRI}World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;
  const KEYS = ['plain', ...Object.keys(TILES)];
  const STORE = 'cps-live-basemap';
  const DETAIL_ZOOM = 4;          // 50m land from this zoom, 110m below
  const EDGE_ZOOM = 3;            // graticule edge labels from this zoom
  const OFFSETS = [-360, 0, 360];

  const STYLE = {
    land: { stroke: false, fillColor: '#1c2129', fillOpacity: 1 },
    lakes: { stroke: false, fillColor: '#0a1120', fillOpacity: 1 },
    coast: { color: '#a3acba', weight: 0.8, opacity: 0.5, fill: false },
    borders: { color: '#a3acba', weight: 0.6, opacity: 0.22, fill: false },
    grat: { color: '#c9d1dd', weight: 0.6, opacity: 0.09, fill: false },
  };

  const files = new Map();
  function load(name) {
    if (!files.has(name)) {
      const url = new URL(`basemap/${name}.json`, document.baseURI).href;
      const p = fetch(url).then((r) => { if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); });
      p.catch(() => files.delete(name));
      files.set(name, p);
    }
    return files.get(name);
  }

  // Remembered choice: share hash first, then this browser, then Plain.
  function saved() {
    const h = new URLSearchParams(location.hash.slice(1)).get('b');
    if (KEYS.includes(h)) return h;
    try {
      const v = localStorage.getItem(STORE);
      return KEYS.includes(v) ? v : 'plain';
    } catch {
      return 'plain';
    }
  }

  // insets() gives the lon label row, the top of the free left edge, and the bar height.
  function create(map, { insets }) {
    [['base-land', 230], ['base-lakes', 235], ['base-lines', 240]]
      .forEach(([n, z]) => { map.createPane(n).style.zIndex = z; });
    const r = (pane) => L.canvas({ pane, padding: 0.3 });
    const R = { land: r('base-land'), lakes: r('base-lakes'), lines: r('base-lines') };
    const G = { land: L.layerGroup(), lakes: L.layerGroup(), coast: L.layerGroup(), borders: L.layerGroup() };
    const plain = L.layerGroup(Object.values(G));
    const labels = L.tileLayer(LABELS, { pane: 'labels', maxNativeZoom: 16, maxZoom: 19 });
    let key = null;
    let tile = null;
    let landRes = null;

    const geo = (fc, style, renderer) => OFFSETS.map((o) => L.geoJSON(fc, {
      style, renderer, interactive: false, coordsToLatLng: (c) => L.latLng(c[1], c[0] + o),
    }));
    const fill = (group, name, style, renderer) => load(name)
      .then((fc) => { group.clearLayers(); geo(fc, style, renderer).forEach((l) => group.addLayer(l)); });

    function detail() {
      const res = map.getZoom() >= DETAIL_ZOOM ? '50m' : '110m';
      if (key !== 'plain' || res === landRes) return;
      landRes = res;
      fill(G.land, `land_${res}`, STYLE.land, R.land).catch(() => { landRes = null; });
    }

    let started = false;
    function startPlain() {
      if (started) return;
      started = true;
      const quiet = (p) => p.catch(() => { started = false; });
      quiet(fill(G.lakes, 'lakes_50m', STYLE.lakes, R.lakes));
      quiet(fill(G.coast, 'coast_50m', STYLE.coast, R.lines));
      quiet(fill(G.borders, 'borders_50m', STYLE.borders, R.lines));
    }

    // Graticule every 10 degrees, three world copies wide.
    const lines = [];
    for (let lat = -80; lat <= 80; lat += 10) lines.push([[lat, -540], [lat, 540]]);
    for (let lon = -540; lon < 540; lon += 10) lines.push([[-85, lon], [85, lon]]);
    L.polyline(lines, { ...STYLE.grat, renderer: R.lines, interactive: false }).addTo(map);

    // Edge labels for the graticule, kept clear of the page chrome.
    const box = L.DomUtil.create('div', 'grat-labels', map.getContainer());
    const deg = (v, pos, neg) => (v === 0 ? '0°' : `${Math.abs(v)}°${v > 0 ? pos : neg}`);
    function edges() {
      const z = map.getZoom();
      box.hidden = z < EDGE_ZOOM;
      if (box.hidden) return;
      const size = map.getSize();
      const { top, left, bottom } = insets();
      const step = z < DETAIL_ZOOM ? 20 : 10;
      const c = map.getCenter();
      const b = map.getBounds();
      let html = '';
      for (let lat = -80; lat <= 80; lat += step) {
        const y = map.latLngToContainerPoint([lat, c.lng]).y;
        if (y > Math.max(top + 24, left + 12) && y < size.y - bottom - 8) html += `<span class="gl-lat" style="top:${y.toFixed(0)}px">${deg(lat, 'N', 'S')}</span>`;
      }
      for (let lon = Math.ceil(b.getWest() / step) * step; lon <= b.getEast(); lon += step) {
        const x = map.latLngToContainerPoint([c.lat, lon]).x;
        const w = ((lon + 540) % 360) - 180;
        if (x > 48 && x < size.x - 48) html += `<span class="gl-lon" style="left:${x.toFixed(0)}px;top:${top}px">${w === -180 ? '180°' : deg(w, 'E', 'W')}</span>`;
      }
      box.innerHTML = html;
    }
    map.on('move zoom resize', edges);
    map.on('zoomend', detail);

    function set(k) {
      if (!KEYS.includes(k)) k = 'plain';
      if (k === key) return key;
      key = k;
      if (tile) map.removeLayer(tile);
      tile = null;
      const ac = map.attributionControl;
      ac.removeAttribution(NE_ATTR);
      if (k === 'plain') {
        map.removeLayer(labels);
        plain.addTo(map);
        ac.addAttribution(NE_ATTR);
        startPlain();
        detail();
      } else {
        map.removeLayer(plain);
        const { url, ...opts } = TILES[k];
        tile = L.tileLayer(url, { ...opts, maxZoom: 19 }).addTo(map);
        labels.addTo(map);
      }
      map.getContainer().dataset.basemap = k;
      try { localStorage.setItem(STORE, k); } catch { /* storage blocked */ }
      return key;
    }

    edges();
    return { set, key: () => key, edges };
  }

  return { create, saved, KEYS };
})();
