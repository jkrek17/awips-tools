/* Leaflet layers for the archive: tracks, gridded fix density, first-fix and
   peak-intensity points.

   Basemap: Esri's hosted REST tile services (see TILES below). Those are the
   only runtime network calls this file makes; everything else is vendored.
   Esri's ocean/dark-canvas tile endpoints are addressed z/y/x, which reads
   oddly against Leaflet's usual z/x/y examples but is unrelated to it -
   L.TileLayer substitutes {x}/{y}/{z} by name wherever they appear in the
   template, so the template below is correct as written.

   Longitude frames: the Pacific tracks cross the dateline, so every view other
   than Atlantic-only is drawn in a 0-360 frame centred on 180. Within a track,
   consecutive longitudes are then unwrapped so a crossing draws as one
   continuous line instead of a full-width horizontal streak. */

window.HF = window.HF || {};

(function (maps, HF) {
  'use strict';

  /* ------------------------------------------------------------- basemap */

  var ESRI = 'https://services.arcgisonline.com/ArcGIS/rest/services/';

  var OCEAN_ATTRIB = 'Esri, GEBCO, NOAA, National Geographic, Garmin, HERE, ' +
    'Geonames.org, and other contributors';
  var DARK_ATTRIB = 'Esri, HERE, Garmin, &copy; OpenStreetMap contributors';

  // The app only ever needs z2-z8 (single-basin ocean views); both services
  // support far higher native zoom (Ocean Base tops out at 13), so the map's
  // own maxZoom is clamped well below what either service could serve.
  var MIN_ZOOM = 2;
  var MAX_ZOOM = 8;

  var TILES = {
    light: {
      base: { url: ESRI + 'Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}', attribution: OCEAN_ATTRIB },
      ref: { url: ESRI + 'Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}', attribution: OCEAN_ATTRIB }
    },
    dark: {
      base: { url: ESRI + 'Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', attribution: DARK_ATTRIB }
    }
  };

  // Ensure a request repeatedly fails (rather than one dropped tile) before
  // giving up on a layer - avoids flashing the fallback note on a single
  // blip, and avoids retrying a truly unreachable host forever.
  var TILE_FAIL_LIMIT = 5;

  /* ---------------------------------------------------------- density grid */

  // 2 deg of latitude is ~120 nm; 5 deg of longitude is ~210 nm at 45N, so
  // cells are roughly square through the storm track belt.
  var CELL_LAT = 2;
  var CELL_LON = 5;

  var map = null;
  var baseLayer = null;
  var refLayer = null;
  var layerGroup = null;
  var tileNote = null;
  var state = { frame: 'pacific', onSelect: null, selectedKey: null };

  maps.init = function (elementId, onSelect) {
    if (typeof L === 'undefined') {      // vendored Leaflet missing or blocked
      var host = document.getElementById(elementId);
      if (host) {
        host.innerHTML = '<p class="chart-empty">The map library could not be loaded, ' +
          'so tracks cannot be drawn. The Climatology, Events and Data quality tabs ' +
          'still work.</p>';
      }
      return null;
    }
    state.onSelect = onSelect;
    map = L.map(elementId, {
      worldCopyJump: false,
      preferCanvas: true,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      zoomControl: true,
      attributionControl: true
    });
    map.attributionControl.setPosition('bottomleft');
    map.attributionControl.setPrefix(false);
    map.setView([48, 180], 3);

    L.control.scale({ position: 'bottomleft', metric: true, imperial: false, maxWidth: 110 }).addTo(map);
    new HF_NauticalScale({ position: 'bottomleft', maxWidth: 110 }).addTo(map);
    tileNote = new HF_TileNote({ position: 'topright' }).addTo(map);

    maps.applyTheme();
    layerGroup = L.layerGroup().addTo(map);
    return map;
  };

  /* --------------------------------------------------------- tile fallback */

  /** Wire load/error tracking onto one tile layer; `onGiveUp` fires once the
      layer has failed enough times in a row that it is not worth keeping. */
  function watchTiles(layer, onGiveUp) {
    var fails = 0;
    var gaveUp = false;
    layer.on('tileload', function () { fails = 0; });
    layer.on('tileerror', function () {
      if (gaveUp) return;              // layer already removed; ignore stragglers
      fails++;
      if (fails >= TILE_FAIL_LIMIT) {
        gaveUp = true;
        onGiveUp(layer);
      }
    });
  }

  /** Swap the basemap when the colour theme changes. */
  maps.applyTheme = function () {
    if (!map) return;
    var dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.getAttribute('data-theme') &&
        window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);

    if (baseLayer) map.removeLayer(baseLayer);
    if (refLayer) { map.removeLayer(refLayer); refLayer = null; }
    if (tileNote) tileNote.hide();

    var set = dark ? TILES.dark : TILES.light;
    baseLayer = L.tileLayer(set.base.url, {
      attribution: set.base.attribution, maxZoom: MAX_ZOOM, crossOrigin: true
    });
    baseLayer.addTo(map);
    baseLayer.bringToBack();
    watchTiles(baseLayer, function (layer) {
      if (map.hasLayer(layer)) map.removeLayer(layer);
      if (tileNote) tileNote.show();
    });

    // Place-label overlay only exists for the ocean (light) basemap, and only
    // matters cosmetically - a failure here degrades quietly with no note.
    if (set.ref) {
      refLayer = L.tileLayer(set.ref.url, {
        attribution: set.ref.attribution, maxZoom: MAX_ZOOM, crossOrigin: true, opacity: 0.9
      });
      refLayer.addTo(map);
      watchTiles(refLayer, function (layer) {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      });
    }
  };

  /* ----------------------------------------------------------- projection */

  // Everything outside the Atlantic-only view is drawn in a [20, 380) frame:
  // the Pacific then spans 100-260 unbroken across the dateline and the
  // Atlantic 275-370 unbroken across the prime meridian, so neither basin is
  // split down the middle of the map.
  var FRAME_ORIGIN = 20;

  function toFrame(lon, frame) {
    if (frame === 'atlantic') return lon;
    return lon < FRAME_ORIGIN ? lon + 360 : lon;
  }

  /** Unwrap a track's longitudes so consecutive fixes never jump 360 degrees. */
  function trackLatLngs(fixes, frame) {
    var out = [];
    var prev = null;
    for (var i = 0; i < fixes.length; i++) {
      var lon = toFrame(fixes[i].lon, frame);
      if (prev !== null) {
        while (lon - prev > 180) lon -= 360;
        while (prev - lon > 180) lon += 360;
      }
      prev = lon;
      out.push([fixes[i].lat, lon]);
    }
    return out;
  }

  maps.setFrame = function (basin) {
    var frame = basin === 'atl' ? 'atlantic' : 'pacific';
    var changed = frame !== state.frame;
    state.frame = frame;
    return changed;
  };

  // A flat map now only ever has to frame a single basin - when both are
  // selected the app swaps in a separate globe view instead - so "both" just
  // needs a sane fallback rather than a carefully tuned centre.
  maps.resetView = function (basin) {
    if (!map) return;
    if (basin === 'atl') map.setView([50, -36], 3);
    else if (basin === 'pac') map.setView([44, 190], 3);
    else map.setView([45, 230], 2);
  };

  /** Zoom to whatever the filters currently select. */
  maps.fitTo = function (lows) {
    if (!map || !lows || !lows.length) return;
    var pts = [];
    lows.forEach(function (low) {
      trackLatLngs(low.fixes, state.frame).forEach(function (p) { pts.push(p); });
    });
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.08));
  };

  maps.focus = function (low) {
    if (!map || !low) return;
    var pts = trackLatLngs(low.fixes, state.frame);
    if (pts.length === 1) map.setView(pts[0], 5);
    else map.fitBounds(L.latLngBounds(pts).pad(0.35));
  };

  /* --------------------------------------------------------------- layers */

  maps.render = function (lows, layer, selectedKey) {
    if (!map) return;
    state.selectedKey = selectedKey;
    layerGroup.clearLayers();

    if (layer === 'density') return renderDensity(lows);
    if (layer === 'genesis') return renderPoints(lows, 'genesis');
    if (layer === 'peak') return renderPoints(lows, 'peak');
    return renderTracks(lows, selectedKey);
  };

  function renderTracks(lows, selectedKey) {
    // Thousands of overlapping tracks saturate into a solid blob, so thin the
    // strokes as the count grows and let the overplotting itself carry density.
    var n = lows.length;
    var style = n > 800 ? { weight: 1, opacity: 0.3 }
              : n > 300 ? { weight: 1.5, opacity: 0.5 }
              : { weight: 2, opacity: 0.78 };

    // --mslp-* resolves through getComputedStyle, so resolve each of the 8
    // possible tokens (7 bands + none) once per render instead of once per
    // segment - with ~1870 tracks and ~8000 fixes that's the difference
    // between ~8 style reads and several thousand.
    var colorCache = {};
    function resolveToken(token) {
      if (!(token in colorCache)) colorCache[token] = HF.cssVar(token);
      return colorCache[token];
    }

    // Draw unselected tracks first so the selected one is never buried.
    var selected = null;
    lows.forEach(function (low) {
      if (low.key === selectedKey) { selected = low; return; }
      addTrack(low, false, style, resolveToken);
    });
    if (selected) {
      addTrack(selected, true, style, resolveToken);
      selected.fixes.forEach(function (fix) {
        layerGroup.addLayer(fixMarker(fix, selected));
      });
    }
  }

  /** Split a 'low' track into runs of consecutive fixes whose segment colour
      (mean MSLP of the two endpoints, per-segment) falls on the same
      --mslp-* step. Adjacent fixes usually deepen/fill gradually, so most
      tracks collapse to 1-3 runs rather than one per fix - drawing one
      polyline per run keeps the fixes.length-1 segments Leaflet actually has
      to render down near the fixes.length-1 -> low-single-digits ratio that
      makes per-fix colour affordable at this scale. A segment where either
      endpoint has no analyzed pressure gets --mslp-none rather than being
      skipped, so a gap in the analysis doesn't break the line in two. */
  function pressureRuns(low, frame) {
    var pts = trackLatLngs(low.fixes, frame);
    var fixes = low.fixes;
    if (pts.length < 2) return pts.length ? [{ token: tokenFor(fixes[0].pres), points: [pts[0], pts[0]] }] : [];

    var runs = [];
    var curToken = null, curPts = null;
    for (var i = 0; i < fixes.length - 1; i++) {
      var p0 = fixes[i].pres, p1 = fixes[i + 1].pres;
      var token = (p0 == null || p1 == null) ? '--mslp-none' : HF.pressureToken((p0 + p1) / 2);
      if (token !== curToken) {
        if (curPts) runs.push({ token: curToken, points: curPts });
        curToken = token;
        curPts = [pts[i]];
      }
      curPts.push(pts[i + 1]);
    }
    if (curPts) runs.push({ token: curToken, points: curPts });
    return runs;
  }

  function tokenFor(pres) { return pres == null ? '--mslp-none' : HF.pressureToken(pres); }

  function addTrack(low, isSelected, style, resolveToken) {
    var base = style || { weight: 2, opacity: 0.78 };
    // No pressure means no place on the pressure ramp: terrain-forced events
    // get their own hue plus a dash pattern, so they stay distinguishable
    // without relying on colour alone. They're a single flat colour for the
    // whole track (there's nothing to ramp), so one polyline is enough.
    var terrain = low.cls && low.cls !== 'low';
    var lines = terrain
      ? [L.polyline(trackLatLngs(low.fixes, state.frame), {
          color: HF.classColor(low.cls),
          dashArray: '5 4',
          weight: isSelected ? 4 : base.weight + 0.5,
          opacity: isSelected ? 1 : Math.min(1, base.opacity + 0.2),
          lineJoin: 'round',
          interactive: true
        })]
      : pressureRuns(low, state.frame).map(function (run) {
          return L.polyline(run.points, {
            color: resolveToken(run.token),
            weight: isSelected ? 4 : base.weight,
            opacity: isSelected ? 1 : base.opacity,
            lineJoin: 'round',
            interactive: true
          });
        });

    // Hovering/selecting acts on the whole track, so every run belonging to
    // one low is wired to thicken and front-raise together, and the tooltip
    // is the same regardless of which segment triggered it.
    lines.forEach(function (line) {
      line.on('mouseover', function (e) {
        lines.forEach(function (l) {
          l.setStyle({ weight: isSelected ? 5.5 : Math.max(3.5, base.weight + 2.5), opacity: 1 });
          l.bringToFront();
        });
        HF.showTip(trackTip(low), e.originalEvent);
      });
      line.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
      line.on('mouseout', function () {
        lines.forEach(function (l) {
          l.setStyle({
            weight: isSelected ? 4 : (terrain ? base.weight + 0.5 : base.weight),
            opacity: isSelected ? 1 : Math.min(1, base.opacity + (terrain ? 0.2 : 0))
          });
        });
        HF.hideTip();
      });
      line.on('click', function () { if (state.onSelect) state.onSelect(low); });
      layerGroup.addLayer(line);
    });
  }

  function trackTip(low) {
    return '<b>' + low.id + '</b> &middot; ' + HF.seasonLabel(low.season) +
      '<div class="t-row">' + HF.fmtDate(low.start) + '</div>' +
      (low.cls === 'tipjet'
        ? '<div class="t-row">Tip jet candidate &mdash; no analyzed centre</div>'
        : low.cls === 'nocentre'
          ? '<div class="t-row">No analyzed centre</div>' : '') +
      '<div class="t-row">Min ' + (low.minP != null ? low.minP + ' hPa' : 'not analyzed') +
      ' &middot; ' + low.hfH + ' h at HF</div>' +
      (low.bomb ? '<div class="t-row">Explosive: ' + low.berg.toFixed(2) + ' B</div>' : '');
  }

  function fixMarker(fix, low) {
    var pt = trackLatLngs([fix], state.frame)[0];
    var baseR = fix.cat === 'HF' ? 5.5 : 4.5;
    var marker = L.circleMarker(pt, {
      radius: baseR,
      color: HF.cssVar('--surface'),
      weight: 1.5,
      fillColor: HF.categoryColor(fix.cat),
      fillOpacity: 1
    });
    marker.on('mouseover', function (e) {
      marker.setStyle({ radius: baseR + 2, weight: 2 });
      marker.bringToFront();
      HF.showTip('<b>' + HF.fmtDate(fix.date) + '</b>' +
        '<div class="t-row">' + (HF.CATEGORIES[fix.cat] || { label: fix.cat }).label + '</div>' +
        '<div class="t-row">' + (fix.pres != null ? fix.pres + ' hPa' : 'pressure not analyzed') +
        ' &middot; ' + HF.fmtLatLon(fix.lat, fix.lon) + '</div>', e.originalEvent);
    });
    marker.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
    marker.on('mouseout', function () { marker.setStyle({ radius: baseR, weight: 1.5 }); HF.hideTip(); });
    marker.on('click', function () { if (state.onSelect) state.onSelect(low); });
    return marker;
  }

  /* -------------------------------------------------------------- density */

  /** Count fixes per grid cell. Returns {cells:[...], max, seasons} */
  maps.densityGrid = function (lows) {
    var cells = {};
    var seasons = {};
    lows.forEach(function (low) {
      seasons[low.season] = true;
      low.fixes.forEach(function (fix) {
        var latIdx = Math.floor(fix.lat / CELL_LAT);
        // Bin in whatever frame the map is currently drawn in - not always
        // 'pacific' - so cells line up with the tracks/points layers when the
        // Atlantic-only (unshifted) frame is active.
        var lonIdx = Math.floor(toFrame(fix.lon, state.frame) / CELL_LON);
        var key = latIdx + ':' + lonIdx;
        if (!cells[key]) {
          cells[key] = { latIdx: latIdx, lonIdx: lonIdx, count: 0, hf: 0, events: {} };
        }
        cells[key].count++;
        if (fix.cat === 'HF') cells[key].hf++;
        cells[key].events[low.key] = true;
      });
    });
    var list = Object.keys(cells).map(function (k) { return cells[k]; });
    var max = 0;
    list.forEach(function (c) {
      c.events = Object.keys(c.events).length;
      if (c.hf > max) max = c.hf;
    });
    return { cells: list, max: max, seasons: Object.keys(seasons).length };
  };

  function renderDensity(lows) {
    var grid = maps.densityGrid(lows);
    if (!grid.max) return;

    var ramp = ['--seq-1', '--seq-2', '--seq-3', '--seq-4', '--seq-5', '--seq-6', '--seq-7']
      .map(HF.cssVar);

    grid.cells.forEach(function (cell) {
      if (!cell.hf) return;
      var lat0 = cell.latIdx * CELL_LAT, lon0 = cell.lonIdx * CELL_LON;
      var frac = cell.hf / grid.max;
      // Perceptual step: counts are heavily skewed, so rank on a square root.
      var step = Math.min(ramp.length - 1, Math.floor(Math.sqrt(frac) * ramp.length));
      var perSeason = grid.seasons ? cell.hf / grid.seasons : cell.hf;

      var rect = L.rectangle([[lat0, lon0], [lat0 + CELL_LAT, lon0 + CELL_LON]], {
        stroke: false,
        fillColor: ramp[step],
        fillOpacity: 0.16 + 0.62 * Math.sqrt(frac),
        interactive: true
      });
      rect.on('mouseover', function (e) {
        rect.setStyle({ stroke: true, color: HF.cssVar('--ink'), weight: 1 });
        HF.showTip('<b>' + Math.abs(lat0) + '–' + Math.abs(lat0 + CELL_LAT) + '°N, ' +
          fmtLonBand(lon0) + '</b>' +
          '<div class="t-row">' + cell.hf + ' hurricane force fixes</div>' +
          '<div class="t-row">' + perSeason.toFixed(1) + ' per season &middot; ' +
          cell.events + ' event' + (cell.events === 1 ? '' : 's') + '</div>', e.originalEvent);
      });
      rect.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
      rect.on('mouseout', function () { rect.setStyle({ stroke: false }); HF.hideTip(); });
      layerGroup.addLayer(rect);
    });
    return grid;
  }

  function fmtLonBand(lon0) {
    function one(v) {
      var x = v > 180 ? v - 360 : v;
      return Math.abs(x) + '°' + (x < 0 ? 'W' : 'E');
    }
    return one(lon0) + '–' + one(lon0 + CELL_LON);
  }

  /* --------------------------------------------------------------- points */

  function renderPoints(lows, kind) {
    lows.forEach(function (low) {
      var lat = kind === 'peak' ? low.minPLat : low.lat0;
      var lon = kind === 'peak' ? low.minPLon : low.lon0;
      if (lat == null || lon == null) return;

      var isSelected = low.key === state.selectedKey;
      var color = kind === 'peak'
        ? (low.cls !== 'low' ? HF.classColor(low.cls) : HF.pressureColor(low.minP))
        : HF.basinColor(low.basin);
      var baseR = kind === 'peak' ? radiusForPressure(low.minP) : 4;
      var marker = L.circleMarker([lat, toFrame(lon, state.frame)], {
        radius: isSelected ? baseR + 2.5 : baseR,
        color: isSelected ? HF.cssVar('--ink') : HF.cssVar('--surface'),
        weight: isSelected ? 2.5 : 0.8,
        fillColor: color,
        fillOpacity: isSelected ? 1 : 0.78
      });
      if (isSelected) marker.bringToFront();
      marker.on('mouseover', function (e) {
        marker.setStyle({ radius: (isSelected ? baseR + 2.5 : baseR) + 2, fillOpacity: 1 });
        marker.bringToFront();
        HF.showTip(trackTip(low), e.originalEvent);
      });
      marker.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
      marker.on('mouseout', function () {
        marker.setStyle({ radius: isSelected ? baseR + 2.5 : baseR, fillOpacity: isSelected ? 1 : 0.78 });
        HF.hideTip();
      });
      marker.on('click', function () { if (state.onSelect) state.onSelect(low); });
      layerGroup.addLayer(marker);
    });
  }

  function radiusForPressure(hpa) {
    if (hpa == null) return 3;
    var t = Math.max(0, Math.min(1, (1000 - hpa) / 70));
    return 3 + t * 6;
  }

  /** Leaflet needs a nudge after the map's panel is unhidden. */
  maps.invalidate = function () {
    if (map) map.invalidateSize();
  };

  maps.CELL_LAT = CELL_LAT;
  maps.CELL_LON = CELL_LON;

  /* ------------------------------------------------------- custom controls */

  // Leaflet ships metric/imperial scale bars but not nautical miles, which is
  // what a marine product actually wants; this mirrors L.Control.Scale's own
  // "round to a tidy number, size the bar to match" approach.
  var HF_NauticalScale = L.Control.extend({
    options: { position: 'bottomleft', maxWidth: 110 },
    onAdd: function (theMap) {
      this._map = theMap;
      var container = L.DomUtil.create('div', 'leaflet-control-scale hf-scale-nm');
      this._line = L.DomUtil.create('div', 'leaflet-control-scale-line', container);
      theMap.on('moveend', this._update, this);
      this._update();
      return container;
    },
    onRemove: function (theMap) { theMap.off('moveend', this._update, this); },
    _update: function () {
      var size = this._map.getSize();
      var y = size.y / 2;
      var maxMeters = this._map.distance(
        this._map.containerPointToLatLng([0, y]),
        this._map.containerPointToLatLng([this.options.maxWidth, y]));
      var maxNm = maxMeters / 1852;
      var nm = this._round(maxNm);
      if (!nm) { this._line.style.width = '0'; this._line.innerHTML = ''; return; }
      this._line.style.width = Math.round(this.options.maxWidth * (nm / maxNm)) + 'px';
      this._line.innerHTML = nm + ' nm';
    },
    _round: function (num) {
      if (!isFinite(num) || num <= 0) return 0;
      var pow10 = Math.pow(10, Math.floor(Math.log(num) / Math.LN10));
      var d = num / pow10;
      d = d >= 5 ? 5 : d >= 2 ? 2 : 1;
      return pow10 * d;
    }
  });

  // Quiet, corner-anchored notice for when the tile services can't be
  // reached (restricted networks are a real deployment target) - data layers
  // keep working regardless, this just explains the blank/grey basemap.
  var HF_TileNote = L.Control.extend({
    options: { position: 'topright' },
    onAdd: function () {
      this._el = L.DomUtil.create('div', 'hf-tile-note');
      this._el.textContent = 'Basemap unavailable — showing tracks only';
      this._el.hidden = true;
      L.DomEvent.disableClickPropagation(this._el);
      return this._el;
    },
    show: function () { if (this._el) this._el.hidden = false; },
    hide: function () { if (this._el) this._el.hidden = true; }
  });

})(window.HF.maps = window.HF.maps || {}, window.HF);
