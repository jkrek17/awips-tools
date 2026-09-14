/* Leaflet layers for the archive: tracks, gridded fix density, first-fix and
   peak-intensity points.

   Longitude frames: the Pacific tracks cross the dateline, so every view other
   than Atlantic-only is drawn in a 0-360 frame centred on 180. Within a track,
   consecutive longitudes are then unwrapped so a crossing draws as one
   continuous line instead of a full-width horizontal streak. */

window.HF = window.HF || {};

(function (maps, HF) {
  'use strict';

  var TILES = {
    light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
  };
  var ATTRIB = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

  // Density grid cell size. 2 deg of latitude is ~120 nm; 5 deg of longitude is
  // ~210 nm at 45N, so cells are roughly square through the storm track belt.
  var CELL_LAT = 2;
  var CELL_LON = 5;

  var map = null;
  var tileLayer = null;
  var layerGroup = null;
  var state = { frame: 'pacific', onSelect: null };

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
      minZoom: 2,
      maxZoom: 8,
      zoomControl: true,
      attributionControl: true
    });
    map.setView([48, 180], 3);
    maps.applyTheme();
    layerGroup = L.layerGroup().addTo(map);
    return map;
  };

  /** Swap the basemap when the colour theme changes. */
  maps.applyTheme = function () {
    if (!map) return;
    var dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.getAttribute('data-theme') &&
        window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (tileLayer) map.removeLayer(tileLayer);
    tileLayer = L.tileLayer(dark ? TILES.dark : TILES.light, {
      attribution: ATTRIB, subdomains: 'abcd', maxZoom: 8, crossOrigin: true
    });
    tileLayer.addTo(map);
    tileLayer.bringToBack();
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

  maps.resetView = function (basin) {
    if (!map) return;
    if (basin === 'atl') map.setView([50, -38], 3);
    else if (basin === 'pac') map.setView([45, 185], 3);
    else map.setView([50, 225], 2);
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

    // Draw unselected tracks first so the selected one is never buried.
    var selected = null;
    lows.forEach(function (low) {
      if (low.key === selectedKey) { selected = low; return; }
      layerGroup.addLayer(trackLine(low, false, style));
    });
    if (selected) {
      layerGroup.addLayer(trackLine(selected, true, style));
      selected.fixes.forEach(function (fix) {
        layerGroup.addLayer(fixMarker(fix, selected));
      });
    }
  }

  function trackLine(low, isSelected, style) {
    var base = style || { weight: 2, opacity: 0.78 };
    // No pressure means no place on the pressure ramp: terrain-forced events
    // get their own hue plus a dash pattern, so they stay distinguishable
    // without relying on colour alone.
    var terrain = low.cls && low.cls !== 'low';
    var line = L.polyline(trackLatLngs(low.fixes, state.frame), {
      color: terrain ? HF.classColor(low.cls) : HF.pressureColor(low.minP),
      dashArray: terrain ? '5 4' : null,
      weight: isSelected ? 4 : (terrain ? base.weight + 0.5 : base.weight),
      opacity: isSelected ? 1 : Math.min(1, base.opacity + (terrain ? 0.2 : 0)),
      lineJoin: 'round',
      interactive: true
    });
    line.on('mouseover', function (e) {
      line.setStyle({ weight: isSelected ? 5 : Math.max(3, base.weight + 2), opacity: 1 });
      HF.showTip(trackTip(low), e.originalEvent);
    });
    line.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
    line.on('mouseout', function () {
      line.setStyle({ weight: isSelected ? 4 : base.weight, opacity: isSelected ? 1 : base.opacity });
      HF.hideTip();
    });
    line.on('click', function () { if (state.onSelect) state.onSelect(low); });
    return line;
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
    var marker = L.circleMarker(pt, {
      radius: fix.cat === 'HF' ? 5.5 : 4.5,
      color: HF.cssVar('--surface'),
      weight: 1.5,
      fillColor: HF.categoryColor(fix.cat),
      fillOpacity: 1
    });
    marker.on('mouseover', function (e) {
      HF.showTip('<b>' + HF.fmtDate(fix.date) + '</b>' +
        '<div class="t-row">' + (HF.CATEGORIES[fix.cat] || { label: fix.cat }).label + '</div>' +
        '<div class="t-row">' + (fix.pres != null ? fix.pres + ' hPa' : 'pressure not analyzed') +
        ' &middot; ' + HF.fmtLatLon(fix.lat, fix.lon) + '</div>', e.originalEvent);
    });
    marker.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
    marker.on('mouseout', HF.hideTip);
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
        var lonIdx = Math.floor(toFrame(fix.lon, 'pacific') / CELL_LON);
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

      var color = kind === 'peak'
        ? (low.cls !== 'low' ? HF.classColor(low.cls) : HF.pressureColor(low.minP))
        : HF.basinColor(low.basin);
      var marker = L.circleMarker([lat, toFrame(lon, state.frame)], {
        radius: kind === 'peak' ? radiusForPressure(low.minP) : 4,
        color: HF.cssVar('--surface'),
        weight: 0.8,
        fillColor: color,
        fillOpacity: 0.78
      });
      marker.on('mouseover', function (e) { HF.showTip(trackTip(low), e.originalEvent); });
      marker.on('mousemove', function (e) { HF.moveTip(e.originalEvent); });
      marker.on('mouseout', HF.hideTip);
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

})(window.HF.maps = window.HF.maps || {}, window.HF);
