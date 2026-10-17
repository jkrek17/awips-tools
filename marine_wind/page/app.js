/* Marine Wind: draws one layer of the newest run's global grids
   (data/global/manifest.json + fFFF/NAME.gz, made by marine_wind/pipeline/build.py
   --domain glob) on a MapLibre GL (WebGL) globe over the Esri ocean basemap, with
   pressure, the blend's 34/48 kt edges, wind arrows, lone-model storm signals and
   the area the blend was tested on, and a point readout. Styled like the site's
   /ndfd/ globe page.

   The field is coloured on the CPU into 256 px Mercator raster tiles, made on demand
   from the grid (a custom "mwfield://" tile protocol, up to zoom 7, then scaled up
   cell by cell), with land cut out of each tile so the basemap's land shows; the
   GPU wraps them onto the globe. Lines (isobars, edges, lone outlines, graticule)
   are GeoJSON layers; text (H/L, isobar values, lone labels, graticule labels) and
   arrows go on a 2D overlay canvas, because the page loads no map fonts, and skip
   anything on the far side of the globe. The map, overlay canvas, graticule, land,
   timeline rail, icons and formats come from the site's globe kit
   (../globe-kit/globe-kit.js, window.GlobeKit). */
(function () {
  "use strict";

  var K = window.GlobeKit;
  // Another page can host this one by naming where its files are:
  // <meta name="marine-wind-base" content="../marine-wind/"> (wxmap.pro's map does).
  var BASE = (document.querySelector('meta[name="marine-wind-base"]') || {}).content || "";
  var DATA = BASE + "data/global/";
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- palettes
  var WIND = {
    stops: [0, 10, 15, 20, 25, 30, 34, 41, 48, 56, 64, 80],
    colors: ["#1b1d21", "#1f2a36", "#22364b", "#28466a", "#2f5a8a", "#3f74ab",
             "#e8d27a", "#e8a93f", "#e06f2e", "#c9372c", "#9b1f5e", "#c86fd8"],
    unit: "kt", title: "10 m wind (kt)"
  };
  var PROB = {
    stops: [0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90],
    colors: ["rgba(0,0,0,0)", "#24354a", "#2c4a6a", "#2f6a8a", "#3c8a96", "#5aa58c",
             "#8fbb6e", "#c9c35a", "#e8a93f", "#e06f2e", "#c9372c"],
    unit: "%", title: "Chance (%)"
  };
  var BOOST = {
    stops: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5],
    colors: ["#1b1d21", "#262338", "#2f2a48", "#3a3159", "#47396b", "#55427d",
             "#654c8f", "#7657a1", "#8a63b2", "#9f71c2", "#b583d1"],
    unit: "kt", title: "Added wind (kt)"
  };
  var SPREAD = {
    stops: [0, 2, 4, 6, 8, 10, 12, 15],
    colors: ["#1b1d21", "#25303a", "#2f4552", "#3b5d68", "#4a787b", "#6b9479", "#a3ab64", "#d8b44c"],
    unit: "kt", title: "Member spread (kt)"
  };
  var TREND = {
    stops: [-99, -15, -10, -6, -3, 3, 6, 10, 15],
    colors: ["#2b5fa8", "#3874b8", "#5a93c6", "#8fb4d2", "rgba(0,0,0,0)",
             "#d9a274", "#d47647", "#c6512f", "#a8301f"],
    labels: ["", "-15", "-10", "-6", "-3", "+3", "+6", "+10", "+15"],
    unit: "kt", title: "Change since the run 24 h earlier (kt)"
  };
  var DIFF = {
    stops: [-99, -6, -4, -2, -1, 1, 2, 4, 6],
    colors: ["#2b5fa8", "#3874b8", "#5a93c6", "#8fb4d2", "rgba(0,0,0,0)",
             "#d9a274", "#d47647", "#c6512f", "#a8301f"],
    labels: ["", "-6", "-4", "-2", "-1", "+1", "+2", "+4", "+6"],
    unit: "kt", title: "Deterministic blend minus blended wind (kt)"
  };
  var FOCUS = {
    cats: [["Ride", "rgba(0,0,0,0)"], ["Agree", "#3a4049"], ["Focus", "#d9a640"], ["High impact", "#d2483b"]],
    title: "Where to look"
  };
  var TREND_MIN = 25;   // run change is drawn only where either run has this much wind
  // what an all-clear layer means, so a blank map doesn't read as a failed load
  var EMPTY = {
    p34: "No point reaches a 5% chance of 34 kt at this hour",
    p48: "No point reaches a 5% chance of 48 kt at this hour",
    p64: "No point reaches a 5% chance of 64 kt at this hour",
    trend: "No change of 3 kt or more in 25+ kt wind since the run 24 h earlier",
    nomemdiff: "The two blends are within 1 kt everywhere either has 25+ kt",
    focus: "Models agree everywhere at this hour"
  };
  var MODEL_COLOR = ["", "#f08a5d", "#7fb0ee", "#c3a6f0"];
  var MODEL_NAME = ["", "GFS", "ECMWF", "AIFS"];
  var TESTED_COLOR = "#e8c46a";
  var CORE = {
    stops: [0, 10, 20, 30, 35, 50, 70, 90],
    colors: ["rgba(0,0,0,0)", "#2c4a6a", "#3c8a96", "#c9c35a", "#e8a93f", "#e06f2e", "#c9372c", "#c86fd8"],
    unit: "%", title: "Storm core chance (%)"
  };
  // the storm layers' "possible" lines (hazard bits 1, 2, 4)
  var HAZARD = [[1, "Gale possible", "#fbbf24"], [2, "Storm possible", "#f97316"], [4, "HF possible", "#e879f9"]];
  // the warning areas, drawn dashed beside them (field warn, same bits and colours)
  var WARN = [[1, "Gale warning area", "#fbbf24"], [2, "Storm warning area", "#f97316"], [4, "HF warning area", "#e879f9"]];

  var LAYERS = [
    ["Forecast"],
    ["wind", "Blended wind", WIND],
    ["mean", "Model base (weighted average)", WIND],
    ["boost", "Added wind", BOOST],
    ["Storm layers (test)"],
    ["windcore", "Core Lifted", WIND],
    ["core", "Storm core chance", CORE],
    ["Where to look"],
    ["focus", "Model agreement", FOCUS],
    ["sigma", "Member spread", SPREAD],
    ["trend", "Change since yesterday's run", TREND],
    ["Deterministic blend (GFE test)"],
    ["nomem", "Deterministic blend", WIND],
    ["nomemdiff", "Difference from blended wind", DIFF],
    ["Ensemble chance"],
    ["p34", "Gale, 34 kt+", PROB],
    ["p48", "Storm, 48 kt+", PROB],
    ["p64", "Hurricane force, 64 kt+", PROB],
    ["Single models"],
    ["gfs", "GFS", WIND],
    ["ecmwf", "ECMWF", WIND],
    ["aifs", "AIFS", WIND]
  ];

  // Preset views: the OPC surface chart areas and the whole globe
  var VIEWS = {
    global: { name: "Global", center: [-45, 28] },
    natl: { name: "Atlantic", bounds: [[-95, 18], [10, 67]], basin: "natl" },
    npac: { name: "Pacific", bounds: [[135, 18], [245, 67]], basin: "npac" }
  };

  // ------------------------------------------------------------------- state
  var man = null, grid = null, fieldIx = {}, cache = {}, order = [], frame = null;
  var state = { layer: "wind", step: 0, lone: true, msl: true, arrows: false, edges: true, tested: true, view: "global", opacity: 0.85, hazard: true, warn: true, track: true };
  var map = null, ov = null, octx = null, overlay = $("overlay");
  var hover = null, playTimer = null, lines = null, areas = [], labels = [], rail = null;
  var MAXLAT = K.MAXLAT, TILE = 256, paint = null, paintVersion = 0;
  var wrapLon = K.wrapLon, lonText = K.lonText, latText = K.latText, fmtTime = K.fmtTime, isMobile = K.isMobile;

  // grid index <-> lon/lat (the global grid runs 180W..179.75E, 90N..90S)
  function gLon(i) { return grid.west + i * grid.res; }
  function gLat(j) { return grid.north - j * grid.res; }
  function cellOf(lon, lat) {
    var i = ((Math.round((wrapLon(lon) - grid.west) / grid.res) % grid.nx) + grid.nx) % grid.nx;
    var j = Math.round((grid.north - lat) / grid.res);
    return j < 0 || j >= grid.ny ? null : { i: i, j: j, k: j * grid.nx + i };
  }

  // ------------------------------------------------------------------- data
  function getField(buf, name) { return buf[name]; }
  function value(buf, name, idx) {
    var f = man.fields[fieldIx[name]], v = buf[name][idx];
    return name === "msl" ? v + 900 : v / f.scale - (f.offset || 0);
  }
  // one field: gzip of each row stored as differences from the cell to its west
  function loadField(step, name) {
    var url = DATA + "f" + ("00" + step).slice(-3) + "/" + name + ".gz?c=" + encodeURIComponent(man.cycle);
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(name + " " + r.status);
      return r.arrayBuffer();
    }).then(function (b) {
      var u = new Uint8Array(b);
      // a server that sends the file with Content-Encoding: gzip hands it over already unzipped
      if (u[0] !== 0x1f || u[1] !== 0x8b) return u;
      return new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer()
        .then(function (x) { return new Uint8Array(x); });
    }).then(function (d) {
      var nx = grid.nx;
      for (var j = 0; j < grid.ny; j++) {
        var o = j * nx, acc = 0;
        for (var i = 0; i < nx; i++) { acc = (acc + d[o + i]) & 255; d[o + i] = acc; }
      }
      return d;
    });
  }
  function loadStep(i) {
    var st = man.steps[i];
    if (cache[st.step]) return cache[st.step];
    var p = Promise.all(man.fields.map(function (f) { return loadField(st.step, f.name); })).then(function (arrs) {
      var b = {};
      man.fields.forEach(function (f, k) { b[f.name] = arrs[k]; });
      return b;
    });
    p.catch(function () { delete cache[st.step]; });
    cache[st.step] = p;
    // a lead is about 20 MB unpacked: keep the newest three
    order = order.filter(function (s) { return s !== st.step; }).concat([st.step]);
    while (order.length > 3) delete cache[order.shift()];
    return p;
  }

  // -------------------------------------------------------------- field image
  function colorTable(pal) {
    // 256 entries indexed by the stored byte for this layer
    var t = new Uint8ClampedArray(256 * 4), f = man.fields[fieldIx[state.layer]];
    var tmp = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    function rgba(c) { tmp.clearRect(0, 0, 1, 1); tmp.fillStyle = c; tmp.fillRect(0, 0, 1, 1); return tmp.getImageData(0, 0, 1, 1).data; }
    var cols = pal.cats ? pal.cats.map(function (c) { return rgba(c[1]); }) : pal.colors.map(rgba);
    for (var b = 0; b < 256; b++) {
      var c;
      if (pal.cats) c = cols[Math.min(b, cols.length - 1)];
      else {
        var v = b / f.scale - (f.offset || 0), k = 0;
        while (k + 1 < pal.stops.length && v >= pal.stops[k + 1]) k++;
        c = cols[k];
      }
      t.set(c, b * 4);
    }
    return t;
  }
  // what the field tiles draw: the layer's bytes, colour table and the cells to leave clear
  function paintField(buf) {
    var pal = layerDef(state.layer)[2], data = buf[state.layer], tab = colorTable(pal);
    // run change and blend difference: only where either has 25 kt or more
    var keep = null;
    if (state.layer === "nomemdiff") {
      var wf = buf.wind, nf = buf.nomem, ws = man.fields[fieldIx.wind].scale, ns = man.fields[fieldIx.nomem].scale;
      keep = function (i) { return wf[i] / ws >= TREND_MIN || nf[i] / ns >= TREND_MIN; };
    }
    if (state.layer === "trend") {
      var g = buf.gfs, e = buf.ecmwf, a = buf.aifs;
      var ms = man.fields[fieldIx.gfs].scale, tf = man.fields[fieldIx.trend];
      keep = function (i) {
        var now = (g[i] + e[i] + a[i]) / (3 * ms), was = now - (data[i] / tf.scale - (tf.offset || 0));
        return now >= TREND_MIN || was >= TREND_MIN;
      };
    }
    // does anything show at all (for the empty-layer note)
    var shown = 0, n = grid.nx * grid.ny;
    for (var c = 0; c < n && !shown; c++) if (tab[data[c] * 4 + 3] && (!keep || keep(c))) shown++;
    paint = { data: data, tab: tab, keep: keep };
    paintVersion++;
    var src = map.getSource("field");
    if (src) src.setTiles(["mwfield://{z}/{x}/{y}?v=" + paintVersion]);
    var note = EMPTY[state.layer], el = $("empty");
    el.textContent = note && !shown ? note : "";
    el.hidden = !(note && !shown);
  }

  // land in Mercator world units, cut out of each tile so the basemap's land shows
  // through and the coast stays sharp
  var landRings = null;
  function loadLand() {
    return K.land().then(function (g) {
      landRings = K.landRings(g);
      paintVersion++;
      var src = map && map.getSource("field");
      if (src) src.setTiles(["mwfield://{z}/{x}/{y}?v=" + paintVersion]);
    }).catch(function () { /* the field then also covers land */ });
  }
  var tileCanvas = null;
  // one 256 px tile of the field, as an ImageBitmap made straight from the colours
  function fieldTile(z, x, y) {
    var d = new Uint8ClampedArray(TILE * TILE * 4), nx = grid.nx, n = Math.pow(2, z);
    if (paint) {
      var col = new Int32Array(TILE), tab = paint.tab, data = paint.data, keep = paint.keep;
      for (var p = 0; p < TILE; p++) {
        var lon = ((x + (p + 0.5) / TILE) / n) * 360 - 180;
        col[p] = ((Math.round((lon - grid.west) / grid.res) % nx) + nx) % nx;
      }
      for (var q = 0; q < TILE; q++) {
        var lat = (2 * Math.atan(Math.exp(Math.PI * (1 - 2 * (y + (q + 0.5) / TILE) / n))) - Math.PI / 2) * 180 / Math.PI;
        var j = Math.max(0, Math.min(grid.ny - 1, Math.round((grid.north - lat) / grid.res))), base = j * nx, o = q * TILE * 4;
        for (var r = 0; r < TILE; r++, o += 4) {
          var k = base + col[r], t = data[k] * 4, al = tab[t + 3];
          if (al && keep && !keep(k)) al = 0;
          d[o] = tab[t]; d[o + 1] = tab[t + 1]; d[o + 2] = tab[t + 2]; d[o + 3] = al;
        }
      }
    }
    var img = new ImageData(d, TILE, TILE);
    if (!landRings || !paint || typeof OffscreenCanvas === "undefined") return createImageBitmap(img);
    if (!tileCanvas) tileCanvas = new OffscreenCanvas(TILE, TILE);
    var cx = tileCanvas.getContext("2d"), s = n * TILE, tx0 = x / n, ty0 = y / n, tx1 = (x + 1) / n, ty1 = (y + 1) / n;
    cx.globalCompositeOperation = "source-over";
    cx.putImageData(img, 0, 0);
    cx.globalCompositeOperation = "destination-out";
    cx.beginPath();
    landRings.forEach(function (r) {
      var b = r.box;
      if (b[2] < tx0 || b[0] > tx1 || b[3] < ty0 || b[1] > ty1) return;
      cx.moveTo((r.xs[0] - tx0) * s, (r.ys[0] - ty0) * s);
      for (var i = 1; i < r.xs.length; i++) cx.lineTo((r.xs[i] - tx0) * s, (r.ys[i] - ty0) * s);
      cx.closePath();
    });
    cx.fill("evenodd");
    return createImageBitmap(tileCanvas);
  }

  // --------------------------------------------------------------- contours
  // marching squares over the cells (i0..i1, j0..j1); i wraps round the date line.
  // levels: sorted array; returns {lev: segments}, each [x0, y0, x1, y1, e0, e1] in grid
  // units, where e0, e1 number the cell edges the ends lie on (a level crosses an edge once)
  function contour(get, levels, i0, j0, i1, j1, wrap) {
    var out = {}, nx = grid.nx;
    levels.forEach(function (l) { out[l] = []; });
    var lo = levels[0], hi = levels[levels.length - 1];
    for (var j = j0; j < j1; j++) {
      for (var i = i0; i < i1; i++) {
        var i2 = i + 1;
        if (i2 >= nx) { if (!wrap) continue; i2 -= nx; }
        var a = get(i, j), b = get(i2, j), c = get(i2, j + 1), d = get(i, j + 1);
        var mn = Math.min(a, b, c, d), mx = Math.max(a, b, c, d);
        if (mx < lo || mn > hi) continue;
        // edge numbers: 2 x cell for its top edge, 2 x cell + 1 for its west edge
        var eT = 2 * (j * nx + i), eB = 2 * ((j + 1) * nx + i), eL = eT + 1, eR = 2 * (j * nx + i2) + 1;
        for (var q = 0; q < levels.length; q++) {
          var lev = levels[q];
          if (lev <= mn || lev > mx) continue;
          var k = (a >= lev ? 8 : 0) | (b >= lev ? 4 : 0) | (c >= lev ? 2 : 0) | (d >= lev ? 1 : 0);
          var tx = i + (lev - a) / (b - a), ry = j + (lev - b) / (c - b), bx = i + (lev - d) / (c - d), ly = j + (lev - a) / (d - a), s = out[lev];
          switch (k) {
            case 1: case 14: s.push([i, ly, bx, j + 1, eL, eB]); break;
            case 2: case 13: s.push([bx, j + 1, i + 1, ry, eB, eR]); break;
            case 3: case 12: s.push([i, ly, i + 1, ry, eL, eR]); break;
            case 4: case 11: s.push([tx, j, i + 1, ry, eT, eR]); break;
            case 6: case 9: s.push([tx, j, bx, j + 1, eT, eB]); break;
            case 7: case 8: s.push([i, ly, tx, j, eL, eT]); break;
            case 5: s.push([i, ly, tx, j, eL, eT]); s.push([bx, j + 1, i + 1, ry, eB, eR]); break;
            case 10: s.push([tx, j, i + 1, ry, eT, eR]); s.push([i, ly, bx, j + 1, eL, eB]); break;
          }
        }
      }
    }
    return out;
  }
  // join segments that share an edge into polylines, in lon/lat
  function polylines(segs) {
    var at = new Map(), used = new Uint8Array(segs.length), out = [];
    segs.forEach(function (s, n) {
      [s[4], s[5]].forEach(function (e) { var l = at.get(e); if (l) l.push(n); else at.set(e, [n]); });
    });
    function other(e) {   // an unused segment touching edge e
      var c = at.get(e);
      if (c) for (var m = 0; m < c.length; m++) if (!used[c[m]]) return c[m];
      return -1;
    }
    for (var n = 0; n < segs.length; n++) {
      if (used[n]) continue;
      used[n] = 1;
      var s = segs[n], pts = [[s[0], s[1]], [s[2], s[3]]], head = s[4], tail = s[5], m, t;
      while ((m = other(tail)) >= 0) {
        used[m] = 1; t = segs[m];
        if (t[4] === tail) { pts.push([t[2], t[3]]); tail = t[5]; } else { pts.push([t[0], t[1]]); tail = t[4]; }
      }
      while ((m = other(head)) >= 0) {
        used[m] = 1; t = segs[m];
        if (t[5] === head) { pts.unshift([t[0], t[1]]); head = t[4]; } else { pts.unshift([t[2], t[3]]); head = t[5]; }
      }
      // grid units -> lon/lat; keep longitudes continuous across the date line
      var ll = [], prev = null;
      pts.forEach(function (p) {
        var lon = gLon(p[0]), lat = gLat(p[1]);
        if (prev !== null) { while (lon - prev > 180) lon -= 360; while (prev - lon > 180) lon += 360; }
        prev = lon;
        ll.push([lon, lat]);
      });
      out.push(ll);
    }
    return out;
  }
  function featureColl(feats) { return { type: "FeatureCollection", features: feats }; }
  function multiLine(coords, props) { return { type: "Feature", properties: props || {}, geometry: { type: "MultiLineString", coordinates: coords } }; }

  // the rows inside the Mercator map
  var J0 = 0, J1 = 0;
  function computeLines(buf) {
    var nx = grid.nx;
    J0 = Math.ceil((grid.north - MAXLAT) / grid.res); J1 = Math.floor((grid.north + MAXLAT) / grid.res);
    var m = buf.msl, levs = [];
    for (var lev = 940; lev <= 1052; lev += 4) levs.push(lev - 0.5);
    var iso = contour(function (i, j) { return m[j * nx + i] + 900; }, levs, 0, J0, nx, J1, true);
    var w = buf.wind, sc = man.fields[fieldIx.wind].scale;
    var ed = contour(function (i, j) { return w[j * nx + i] / sc; }, [34, 48], 0, J0, nx, J1, true);
    var isoLines = {};
    levs.forEach(function (l) { if (iso[l].length) isoLines[l + 0.5] = polylines(iso[l]); });
    var hz = {}, h = buf.hazard;
    if (h) HAZARD.forEach(function (d) {
      hz[d[0]] = polylines(contour(function (i, j) { return h[j * nx + i] & d[0] ? 1 : 0; }, [0.5], 0, J0, nx, J1, true)[0.5]);
    });
    var wz = {}, wb = buf.warn;
    if (wb) WARN.forEach(function (d) {
      wz[d[0]] = polylines(contour(function (i, j) { return wb[j * nx + i] & d[0] ? 1 : 0; }, [0.5], 0, J0, nx, J1, true)[0.5]);
    });
    return { iso: isoLines, e34: polylines(ed[34]), e48: polylines(ed[48]), hz: hz, wz: wz };
  }

  // lone-model areas: connected components of each (model, threshold) mask
  function loneAreas(buf) {
    var lone = buf.lone, nx = grid.nx, ny = grid.ny, out = [];
    var any = false;
    for (var q = 0; q < lone.length; q++) if (lone[q]) { any = true; break; }
    if (!any) return out;
    [[0, 48], [2, 64]].forEach(function (sh) {
      for (var m = 1; m <= 3; m++) {
        var seen = new Uint8Array(nx * ny), mf = buf[MODEL_NAME[m].toLowerCase()];
        for (var k = 0; k < nx * ny; k++) {
          if (seen[k] || ((lone[k] >> sh[0]) & 3) !== m) continue;
          var stack = [k], cells = [], best = k, bestV = -1, mn = [nx, ny], mx = [-1, -1];
          seen[k] = 1;
          while (stack.length) {
            var c = stack.pop(); cells.push(c);
            if (mf[c] > bestV) { bestV = mf[c]; best = c; }
            var ci = c % nx, cj = (c / nx) | 0;
            mn = [Math.min(mn[0], ci), Math.min(mn[1], cj)]; mx = [Math.max(mx[0], ci), Math.max(mx[1], cj)];
            for (var dd = 0; dd < 4; dd++) {
              var ii = ci + [1, -1, 0, 0][dd], jj = cj + [0, 0, 1, -1][dd];
              if (jj < 0 || jj >= ny) continue;
              ii = (ii + nx) % nx;
              var p = jj * nx + ii;
              if (!seen[p] && ((lone[p] >> sh[0]) & 3) === m) { seen[p] = 1; stack.push(p); }
            }
          }
          if (cells.length < 8) continue; // under ~4000 km2: grid noise, not a storm signal
          // this component's outline: the mask contoured over its bounding box only
          var shf = sh[0], mm = m, set = {};
          cells.forEach(function (c) { set[c] = 1; });
          var segs = contour(function (i, j) {
            if (i < 0 || j < 0 || i >= nx || j >= ny) return 0;
            return set[j * nx + i] ? 1 : 0;
          }, [0.5], Math.max(0, mn[0] - 1), Math.max(0, mn[1] - 1), Math.min(nx - 1, mx[0] + 1), Math.min(ny - 1, mx[1] + 1), false)[0.5];
          out.push({ model: mm, thr: sh[1], cells: cells, peak: best, lines: polylines(segs), shift: shf,
                     speed: value(buf, MODEL_NAME[mm].toLowerCase(), best), prob: value(buf, "p" + sh[1], best) });
        }
      }
    });
    return out.sort(function (a, b) { return b.speed - a.speed; });
  }

  function setData(id, fc) { var s = map.getSource(id); if (s) s.setData(fc); }
  function updateLines() {
    var isoF = [];
    if (state.msl) Object.keys(lines.iso).forEach(function (l) { isoF.push(multiLine(lines.iso[l], { lev: +l })); });
    setData("isobars", featureColl(isoF));
    var showEdges = state.edges && state.layer !== "focus";
    setData("edges", featureColl(showEdges ? [multiLine(lines.e34, { lev: 34 }), multiLine(lines.e48, { lev: 48 })] : []));
    setData("lone", featureColl(state.lone ? areas.map(function (a) { return multiLine(a.lines, { thr: a.thr, color: MODEL_COLOR[a.model] }); }) : []));
    setData("hazard", featureColl(state.hazard && hasStorm() ? HAZARD.map(function (d) { return multiLine(lines.hz[d[0]] || [], { bit: d[0], color: d[2] }); }) : []));
    setData("warn", featureColl(state.warn && hasWarn() ? WARN.map(function (d) { return multiLine(lines.wz[d[0]] || [], { bit: d[0], color: d[2] }); }) : []));
    updateTracks();
  }
  function hasStorm() { return fieldIx.hazard !== undefined; }
  function hasWarn() { return fieldIx.warn !== undefined; }

  // ------------------------------------------------------- ensemble low tracks
  // tracks.json: each track a list of 24-hourly points {step, lat, lon, hpa, cone_km, ...}.
  // At the shown lead: solid line up to it, dashed beyond, dots every 24 h with the
  // central pressure, and the cone (radius cone_km) round the dashed part.
  var tracks = [];
  function trackAt(t, step) {   // position at a lead, between two points
    if (step < t[0].step || step > t[t.length - 1].step) return null;
    for (var k = 1; k < t.length; k++) if (step <= t[k].step) {
      var a = t[k - 1], b = t[k], f = (step - a.step) / (b.step - a.step);
      return { step: step, lat: a.lat + f * (b.lat - a.lat), lon: a.lon + f * (b.lon - a.lon), cone_km: a.cone_km + f * (b.cone_km - a.cone_km) };
    }
    return t[0];
  }
  // the cone: a band of half-width cone_km along the track (sampled every 6 h), with round ends
  function cone(pts) {
    var dense = [];
    for (var k = 0; k + 1 < pts.length; k++) {
      var a = pts[k], b = pts[k + 1];
      for (var f = 0; f < 1; f += 0.25) dense.push({ lat: a.lat + f * (b.lat - a.lat), lon: a.lon + f * (b.lon - a.lon), r: a.cone_km + f * (b.cone_km - a.cone_km) });
    }
    var e = pts[pts.length - 1];
    dense.push({ lat: e.lat, lon: e.lon, r: e.cone_km });
    if (dense.length < 2) return null;
    function off(p, brg, r) {   // the point r km from p on bearing brg (radians)
      var dlat = r * Math.cos(brg) / 111.2, dlon = r * Math.sin(brg) / (111.2 * Math.max(0.2, Math.cos(p.lat * Math.PI / 180)));
      return [p.lon + dlon, Math.max(-85, Math.min(85, p.lat + dlat))];
    }
    function brg(a, b) { return Math.atan2((b.lon - a.lon) * Math.cos((a.lat + b.lat) * Math.PI / 360), b.lat - a.lat); }
    var left = [], right = [], n = dense.length;
    dense.forEach(function (p, k) {
      var h = brg(dense[Math.max(0, k - 1)], dense[Math.min(n - 1, k + 1)]);
      left.push(off(p, h - Math.PI / 2, p.r)); right.push(off(p, h + Math.PI / 2, p.r));
    });
    var hEnd = brg(dense[n - 2], dense[n - 1]), hStart = brg(dense[0], dense[1]), ring = left.slice();
    for (var q = 1; q < 12; q++) ring.push(off(dense[n - 1], hEnd - Math.PI / 2 + q * Math.PI / 12, dense[n - 1].r));
    ring = ring.concat(right.reverse());
    for (var q2 = 1; q2 < 12; q2++) ring.push(off(dense[0], hStart + Math.PI / 2 + q2 * Math.PI / 12, dense[0].r));
    ring.push(ring[0]);
    return ring;
  }
  function updateTracks() {
    var on = state.track && tracks.length, step = man.steps[state.step].step, past = [], ahead = [], cones = [], dots = [];
    if (on) tracks.forEach(function (t) {
      var now = trackAt(t, step), done = t.filter(function (p) { return p.step <= step; }), next = t.filter(function (p) { return p.step > step; });
      if (now && done.length && done[done.length - 1].step !== step) done.push(now);
      if (done.length > 1) past.push(done.map(function (p) { return [p.lon, p.lat]; }));
      var fut = (now ? [now] : []).concat(next);
      if (fut.length > 1) {
        ahead.push(fut.map(function (p) { return [p.lon, p.lat]; }));
        var c = cone(fut);
        if (c) cones.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [c] } });
      }
      t.forEach(function (p) { dots.push({ type: "Feature", properties: { past: p.step <= step ? 1 : 0 }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } }); });
      if (now) dots.push({ type: "Feature", properties: { now: 1 }, geometry: { type: "Point", coordinates: [now.lon, now.lat] } });
    });
    setData("cone", featureColl(cones));
    setData("track", featureColl([multiLine(past, { past: 1 }), multiLine(ahead, { past: 0 })]));
    setData("trackpts", featureColl(dots));
  }

  // ------------------------------------------------------------- map setup
  function testedArea() {
    return featureColl((grid.tested || []).map(function (b) {
      return multiLine([[[b.west, b.south], [b.east, b.south], [b.east, b.north], [b.west, b.north], [b.west, b.south]]], { name: b.name });
    }));
  }
  function inTested(lon, lat) {
    return (grid.tested || []).some(function (b) {
      return lat >= b.south && lat <= b.north && ((lon - b.west) % 360 + 360) % 360 <= b.east - b.west;
    });
  }

  function buildMap(start) {
    if (start.bounds) start.padding = viewPadding();
    map = K.createMap({ start: start, credits: "NOAA GFS, GEFS &middot; ECMWF open data &middot; Natural Earth" });
    window.MW_map = map;   // for console diagnostics
    ov = K.overlay(map, overlay); octx = ov.ctx;
    map.on("load", function () {
      map.addSource("field", { type: "raster", tiles: ["mwfield://{z}/{x}/{y}?v=" + paintVersion], tileSize: TILE, maxzoom: 7 });
      map.addLayer({ id: "field", type: "raster", source: "field", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0, "raster-opacity": state.opacity } });
      map.addSource("graticule", { type: "geojson", data: K.graticule() });
      map.addLayer({ id: "graticule", type: "line", source: "graticule", paint: K.GRATICULE_PAINT });
      map.addSource("tested", { type: "geojson", data: testedArea() });
      map.addLayer({ id: "tested", type: "line", source: "tested", paint: { "line-color": TESTED_COLOR, "line-opacity": 0.85, "line-width": 1.4, "line-dasharray": [1, 2.5] } });
      ["cone", "isobars", "edges", "hazard", "warn", "lone", "track", "trackpts"].forEach(function (id) { map.addSource(id, { type: "geojson", data: featureColl([]), tolerance: 0.2 }); });
      map.addLayer({ id: "cone", type: "fill", source: "cone", paint: { "fill-color": "#e7eef8", "fill-opacity": 0.2 } });
      map.addLayer({ id: "cone-edge", type: "line", source: "cone", paint: { "line-color": "rgba(255,255,255,0.8)", "line-width": 1.1 } });
      // every 8 hPa zoomed out, every 4 hPa once zoomed in
      var iso = { "line-color": "rgba(231,238,248,0.55)", "line-width": 0.9 };
      map.addLayer({ id: "isobars8", type: "line", source: "isobars", filter: ["==", ["%", ["get", "lev"], 8], 0], paint: iso });
      map.addLayer({ id: "isobars4", type: "line", source: "isobars", minzoom: 2.5, filter: ["!=", ["%", ["get", "lev"], 8], 0], paint: iso });
      map.addLayer({ id: "edge34", type: "line", source: "edges", filter: ["==", ["get", "lev"], 34], paint: { "line-color": "rgba(255,255,255,0.9)", "line-width": 1, "line-dasharray": [4, 3] } });
      map.addLayer({ id: "edge48", type: "line", source: "edges", filter: ["==", ["get", "lev"], 48], paint: { "line-color": "rgba(255,255,255,0.9)", "line-width": 1.6 } });
      map.addLayer({ id: "hazard-halo", type: "line", source: "hazard", paint: { "line-color": "rgba(5,10,20,0.7)", "line-width": 3.4 } });
      map.addLayer({ id: "hazard", type: "line", source: "hazard", paint: { "line-color": ["get", "color"], "line-width": 1.6 } });
      map.addLayer({ id: "warn-halo", type: "line", source: "warn", paint: { "line-color": "rgba(5,10,20,0.7)", "line-width": 3.4 } });
      map.addLayer({ id: "warn", type: "line", source: "warn", paint: { "line-color": ["get", "color"], "line-width": 1.8, "line-dasharray": [2.5, 1.5] } });
      // dark halo first so the outline reads on top of the warm wind colours
      map.addLayer({ id: "lone-halo", type: "line", source: "lone", paint: { "line-color": "rgba(5,10,20,0.85)", "line-width": ["case", ["==", ["get", "thr"], 64], 4.8, 4] } });
      map.addLayer({ id: "lone48", type: "line", source: "lone", filter: ["==", ["get", "thr"], 48], paint: { "line-color": ["get", "color"], "line-width": 1.6, "line-dasharray": [3, 2] } });
      map.addLayer({ id: "lone64", type: "line", source: "lone", filter: ["==", ["get", "thr"], 64], paint: { "line-color": ["get", "color"], "line-width": 2.4 } });
      // the ensemble low track: solid up to the shown lead, dashed beyond (OPC style)
      map.addLayer({ id: "track-halo", type: "line", source: "track", layout: { "line-cap": "round" }, paint: { "line-color": "rgba(5,10,20,0.8)", "line-width": 4.2 } });
      map.addLayer({ id: "track-past", type: "line", source: "track", filter: ["==", ["get", "past"], 1], layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": 2.2 } });
      map.addLayer({ id: "track-ahead", type: "line", source: "track", filter: ["==", ["get", "past"], 0], paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [2, 1.6] } });
      map.addLayer({ id: "trackpts", type: "circle", source: "trackpts", paint: {
        "circle-radius": ["case", ["has", "now"], 5.5, 3.5],
        "circle-color": ["case", ["has", "now"], "#38bdf8", ["==", ["get", "past"], 1], "#ffffff", "#0f1829"],
        "circle-stroke-color": "#ffffff", "circle-stroke-width": ["case", ["has", "now"], 2, 1.5] } });
      setTested();
      loadLand();
      ready();
    });
    map.on("render", drawOverlay);
    map.on("moveend", function () { placeLabels(); drawOverlay(); summary(); writeHash(); });
    map.on("movestart", function (e) { if (e.originalEvent) setView(null); });
    map.on("mousemove", function (e) { readout(e.point, e.lngLat); });
    map.on("click", function (e) { readout(e.point, e.lngLat); });
    map.on("error", function (e) {
      var sid = e.sourceId || (e.source && e.source.id);
      if (sid === "ocean") note("Basemap tiles failed to load; the wind field still shows.");
      else if (e && e.error) console.error(e.error);
    });
    map.getCanvas().addEventListener("mouseleave", function () { $("readout").hidden = true; $("coords").textContent = ""; hover = null; drawOverlay(); });
  }
  // room for the floating cards round the map when fitting a view
  function viewPadding() {
    var r = document.documentElement.getBoundingClientRect(), tb = document.querySelector(".topbar").getBoundingClientRect();
    var tl = document.querySelector(".timeline").getBoundingClientRect(), panelOpen = document.body.classList.contains("panel-open") && r.width > 760;
    return { top: tb.bottom + 8, bottom: r.height - tl.top + 8, left: panelOpen ? 312 + 24 : 16, right: r.width > 760 ? 56 : 12 };
  }
  var note = K.note;
  function setTested() { if (map.getLayer("tested")) map.setLayoutProperty("tested", "visibility", state.tested ? "visible" : "none"); }

  // -------------------------------------------------------------- overlay
  // screen position of a lon/lat, as a list: empty when it is off screen or on the far side of the globe
  function proj(lon, lat) { return ov.proj(lon, lat); }

  function drawOverlay() {
    if (!map || !frame) return;
    var w = overlay.clientWidth, h = overlay.clientHeight, fam = getComputedStyle(document.body).fontFamily;
    octx.clearRect(0, 0, w, h);
    drawGraticuleLabels(w, h, fam);
    if (state.arrows) drawArrows(w, h);
    if (state.msl) drawCentres(fam);
    if (state.msl) drawIsobarLabels(fam);
    if (state.lone) drawLoneLabels(fam);
    if (state.track) drawTrackLabels(fam);
    emit("mw:overlay", { ctx: octx, proj: proj, font: fam, width: w, height: h });
    if (hover) {
      proj(hover.lon, hover.lat).forEach(function (p) {
        octx.strokeStyle = "#fff"; octx.lineWidth = 1.2;
        octx.beginPath(); octx.arc(p.x, p.y, 4, 0, 2 * Math.PI); octx.stroke();
      });
    }
  }
  function drawGraticuleLabels(w, h, fam) {
    K.graticuleLabels(map, ov, document.querySelector(".topbar").getBoundingClientRect().bottom,
      document.querySelector(".timeline").getBoundingClientRect().top, fam);
  }
  function drawArrows(w, h) {
    var dir = frame.dir, sp = frame.wind, sc = man.fields[fieldIx.wind].scale, gap = 28;
    octx.strokeStyle = "rgba(233,232,227,0.7)"; octx.lineWidth = 1;
    octx.beginPath();
    for (var y = gap / 2; y < h; y += gap) for (var x = gap / 2; x < w; x += gap) {
      if (!map.transform.isPointOnMapSurface(new maplibregl.Point(x, y))) continue;
      var ll = map.unproject([x, y]);
      if (Math.abs(ll.lat) > 84) continue;
      var c = cellOf(ll.lng, ll.lat);
      if (!c) continue;
      var kt = sp[c.k] / sc;
      if (kt < 5) continue;
      // the screen direction of a short step downwind, so arrows follow the globe's curve and any rotation
      var to = (dir[c.k] * 2 + 180) * Math.PI / 180, L = 6 + Math.min(kt, 60) / 6, st = 0.05;
      var q = map.project([ll.lng + Math.sin(to) * st / Math.max(0.1, Math.cos(ll.lat * Math.PI / 180)), ll.lat + Math.cos(to) * st]);
      var ex = q.x - x, ey = q.y - y, el = Math.hypot(ex, ey) || 1;
      var dx = ex / el * L, dy = ey / el * L, hx = x + dx / 2, hy = y + dy / 2, a = Math.atan2(dy, dx);
      octx.moveTo(x - dx / 2, y - dy / 2); octx.lineTo(hx, hy);
      octx.lineTo(hx - 4 * Math.cos(a - 0.5), hy - 4 * Math.sin(a - 0.5));
      octx.moveTo(hx, hy); octx.lineTo(hx - 4 * Math.cos(a + 0.5), hy - 4 * Math.sin(a + 0.5));
    }
    octx.stroke();
  }
  function drawCentres(fam) {
    // H and L centres found by build.py on the full-precision field; only once zoomed in enough to read them
    var st = man.steps[state.step], z = map.getZoom();
    if (z < 1.2) return;
    octx.textAlign = "center"; octx.textBaseline = "middle"; octx.fillStyle = "rgba(231,238,248,0.95)";
    (st.centres || []).forEach(function (c) {
      // the whole globe in view: only the deep lows and strong highs
      if (z < 2.5 && (c[0] === "L" ? c[3] > 1000 : c[3] < 1030)) return;
      proj(c[2], c[1]).forEach(function (p) {
        octx.font = "600 14px " + fam; octx.fillText(c[0], p.x, p.y);
        octx.font = "10px " + fam; octx.fillText(Math.round(c[3]), p.x, p.y + 13);
      });
    });
  }
  // a few labels per isobar on screen, kept apart from each other, the H/L centres, the
  // map edge and any 30+ kt wind, so a label never sits on a gale area. Placed when the
  // map stops moving; drawn at their lon/lat while it moves.
  function placeLabels() {
    labels = [];
    if (!lines || !state.msl || map.getZoom() < 1.5) return;
    var w = overlay.clientWidth, h = overlay.clientHeight, small = w < 600, gap = small ? 120 : 160, most = small ? 2 : 4;
    var wf = frame.wind, sc = man.fields[fieldIx.wind].scale, st = man.steps[state.step], placed = [];
    var avoid = [];
    (st.centres || []).forEach(function (c) { proj(c[2], c[1]).forEach(function (p) { avoid.push(p); }); });
    Object.keys(lines.iso).forEach(function (l) {
      if (+l % 8) return;
      var n = 0;
      lines.iso[l].forEach(function (line) {
        for (var k = 0; k < line.length && n < most; k += 9) {
          var ps = proj(line[k][0], line[k][1]);
          for (var q = 0; q < ps.length && n < most; q++) {
            var a = ps[q];
            if (a.x < 36 || a.x > w - 24 || a.y < 12 || a.y > h - 18) continue;
            var c = cellOf(line[k][0], line[k][1]);
            if (!c || wf[c.k] / sc >= 30) continue;
            var near = function (o, r) { return Math.abs(o.x - a.x) < r && Math.abs(o.y - a.y) < r; };
            if (avoid.some(function (o) { return near(o, 40); })) continue;
            if (placed.some(function (o) { return near(o, o.lev === +l ? gap : 28); })) continue;
            placed.push({ x: a.x, y: a.y, lev: +l });
            labels.push({ lon: line[k][0], lat: line[k][1], lev: +l });
            n++;
          }
        }
      });
    });
  }
  function drawIsobarLabels(fam) {
    octx.font = "10px " + fam; octx.textAlign = "center"; octx.textBaseline = "middle";
    labels.forEach(function (l) {
      var ps = proj(l.lon, l.lat), t = String(l.lev), w = octx.measureText(t).width + 4;
      ps.forEach(function (p) {
        octx.fillStyle = "rgba(10,17,32,0.82)"; octx.fillRect(p.x - w / 2, p.y - 6, w, 12);
        octx.fillStyle = "rgba(231,238,248,0.85)"; octx.fillText(t, p.x, p.y);
      });
    });
  }
  // the central pressure by each 24 h dot, with the day when zoomed in
  function drawTrackLabels(fam) {
    var z = map.getZoom();
    octx.textAlign = "left"; octx.textBaseline = "middle";
    var step = man.steps[state.step].step;
    tracks.forEach(function (t) {
      var nextPt = t.filter(function (p) { return p.step >= step; })[0] || t[t.length - 1];
      t.forEach(function (p) {
        if (z < 3 && p !== nextPt) return;   // the whole globe in view: one label a track
        proj(p.lon, p.lat).forEach(function (q) {
          var tx = Math.round(p.hpa) + (z >= 3 ? "  " + fmtTime(man.steps.filter(function (s) { return s.step === p.step; }).map(function (s) { return s.valid; })[0] || man.cycle, true).replace(/ \d+ \w+$/, "") : "");
          octx.font = "700 11px " + fam;
          var w = octx.measureText(tx).width + 8;
          octx.fillStyle = "rgba(10,17,32,0.85)"; octx.fillRect(q.x + 7, q.y - 8, w, 16);
          octx.fillStyle = "#ffffff"; octx.fillText(tx, q.x + 11, q.y);
        });
      });
    });
  }
  function drawLoneLabels(fam) {
    octx.font = "600 11px " + fam; octx.textAlign = "left"; octx.textBaseline = "bottom";
    var boxes = [];
    areas.forEach(function (a) {   // strongest first; skip a label that would overlap one already drawn
      var i = a.peak % grid.nx, j = (a.peak / grid.nx) | 0;
      proj(gLon(i), gLat(j)).forEach(function (p) {
        var label = MODEL_NAME[a.model] + " alone " + Math.round(a.speed) + " kt";
        var w = octx.measureText(label).width + 8, bx = [p.x + 6, p.y - 22, w, 16];
        if (boxes.some(function (o) { return bx[0] < o[0] + o[2] && o[0] < bx[0] + bx[2] && bx[1] < o[1] + o[3] && o[1] < bx[1] + bx[3]; })) return;
        boxes.push(bx);
        octx.fillStyle = "rgba(10,17,32,0.88)"; octx.fillRect(bx[0], bx[1], bx[2], bx[3]);
        octx.fillStyle = MODEL_COLOR[a.model]; octx.fillText(label, p.x + 10, p.y - 4);
      });
    });
  }

  // ----------------------------------------------------------------- legend
  function layerDef(name) { for (var i = 0; i < LAYERS.length; i++) if (LAYERS[i][0] === name) return LAYERS[i]; return null; }

  // what each chance layer's percentage counts (one line under its legend)
  var LEGEND_NOTE = {
    p34: "Share of members at 34 kt+, adjusted to how often ASCAT saw 34 kt+ in a box about 75 km across",
    p48: "Share of members at 48 kt+, adjusted to how often ASCAT saw 48 kt+ in a box about 75 km across",
    p64: "Share of members at 64 kt+, adjusted to how often model analyses had 64 kt+",
    core: "Chance that ASCAT sees 48 kt+ within about 50 km"
  };
  var CHANCE_FIT = "; fitted inside the tested area on November to March, untested elsewhere and in other months";
  var CHANCE_MONTHS = [10, 11, 0, 1, 2];   // getUTCMonth of Nov-Mar
  function legend() {
    var def = layerDef(state.layer), pal = def[2], el = $("legend"), h;
    if (pal.cats) {
      h = '<div class="legend-head"><span>' + pal.title + '</span></div><div class="legend-cats">' + pal.cats.map(function (c, k) {
        return '<span><i style="background:' + (k ? c[1] : "transparent") + ';box-shadow:0 0 0 1px var(--border-strong) inset"></i>' + c[0] + "</span>";
      }).join("") + "</div>";
    } else {
      var title = def[1] === "Blended wind" || pal !== WIND ? pal.title.replace(/ \((kt|%)\)$/, "") : def[1];
      var cond = state.layer === "trend" ? ", where either run has " + TREND_MIN + "+ kt" : state.layer === "nomemdiff" ? ", where either has " + TREND_MIN + "+ kt" : "";
      var labs = pal.labels || pal.stops, n = pal.colors.length;
      h = '<div class="legend-head"><span>' + title + cond + '</span><span class="unit">' + pal.unit + "</span></div>" +
        '<div class="legend-bar">' + pal.colors.map(function (c) { return '<span style="background:' + c + '"></span>'; }).join("") + "</div>" +
        '<div class="legend-labels">' + labs.map(function (t, k) {
          return k && t !== "" ? '<span style="left:' + (k / n * 100).toFixed(2) + '%">' + t + "</span>" : "";
        }).join("") + "</div>";
    }
    if (LEGEND_NOTE[state.layer]) h += '<div class="legend-note">' + LEGEND_NOTE[state.layer] + (state.layer === "core" ? "; trained inside the tested area on winter 2025-26" : CHANCE_FIT) + "</div>";
    var keys = [];
    if (state.edges && state.layer !== "focus") keys.push('<span><i style="border-top:1px dashed #fff"></i>34 kt edge</span>',
      '<span><i style="border-top:2px solid #fff"></i>48 kt edge</span>');
    if (state.msl) keys.push('<span><i style="border-top:1px solid rgba(231,238,248,0.6)"></i>Isobars, 4 hPa</span>');
    if (state.tested) keys.push('<span><i style="border-top:2px dotted ' + TESTED_COLOR + '"></i>Tested area</span>');
    if (state.hazard && hasStorm()) {
      keys.push.apply(keys, HAZARD.map(function (d) { return '<span><i style="border-top:2px solid ' + d[2] + '"></i>' + d[1] + "</span>"; }));
      keys.push('<span class="wide">Possible lines use the raw member shares (gale 30%+ at 34 kt) and the storm core chance</span>');
    }
    if (state.warn && hasWarn()) {
      keys.push.apply(keys, WARN.map(function (d) { return '<span><i style="border-top:2px dashed ' + d[2] + '"></i>' + d[1] + "</span>"; }));
      keys.push('<span class="wide">Warning areas: gale where the strongest model has 30 kt, storm where Core Lifted has 39 kt, HF where the strongest model has 44 kt and 1% of members 64 kt nearby (most false HF areas are storm cores); tested at 24-48 h in winter</span>');
    }
    if (state.track && tracks.length) keys.push('<span><i style="border-top:2px dashed #fff"></i>Low track, hPa</span>',
      '<span><i style="border:0;height:9px;vertical-align:-1px;background:rgba(231,238,248,0.3);box-shadow:0 0 0 1px rgba(255,255,255,0.8) inset"></i>Cone, 2 in 3</span>');
    if (state.lone) keys.push('<span><i style="border-top:2px dashed var(--text)"></i>Lone 48 kt</span>',
      '<span><i style="border-top:2px solid var(--text)"></i>Lone 64 kt</span>',
      '<span class="wide">Lone outline colour: ' + [1, 2, 3].map(function (m) { return '<b style="color:' + MODEL_COLOR[m] + ';font-weight:600">' + MODEL_NAME[m] + "</b>"; }).join(" / ") + "</span>");
    if (keys.length) h += '<div class="legend-keys">' + keys.join("") + "</div>";
    el.innerHTML = h;
  }

  // the cells of the grid inside the map view (whole rows of longitude when the view wraps the globe)
  function viewCells(fn) {
    var nx = grid.nx;
    if (map.getZoom() < 4) {
      // zoomed out on the globe: whole degrees whose centre is on screen and on the near side
      var w = overlay.clientWidth, h = overlay.clientHeight, per = Math.round(1 / grid.res);
      for (var la = -85; la < 85; la++) for (var lo = -180; lo < 180; lo++) {
        var p = proj(lo + 0.5, la + 0.5)[0];
        if (!p || p.x < 0 || p.y < 0 || p.x > w || p.y > h) continue;
        var jt = Math.round((grid.north - la - 1) / grid.res), it = Math.round((lo - grid.west) / grid.res);
        for (var dj = 0; dj < per; dj++) for (var di = 0; di < per; di++) {
          var jj = jt + dj; fn(jj * nx + ((it + di) % nx + nx) % nx, jj);
        }
      }
      return;
    }
    var b = map.getBounds();
    var j0 = Math.max(J0, Math.floor((grid.north - Math.min(b.getNorth(), MAXLAT)) / grid.res));
    var j1 = Math.min(J1, Math.ceil((grid.north - Math.max(b.getSouth(), -MAXLAT)) / grid.res));
    var span = b.getEast() - b.getWest(), i0, n;
    if (span >= 360) { i0 = 0; n = nx; } else { i0 = Math.floor((wrapLon(b.getWest()) - grid.west) / grid.res); n = Math.ceil(span / grid.res) + 1; }
    for (var j = j0; j <= j1; j++) for (var q = 0; q < n; q++) { var i = (i0 + q + nx) % nx; fn(j * nx + i, j); }
  }
  function inView(lon, lat) { return proj(lon, lat).some(function (p) { return p.x >= 0 && p.y >= 0 && p.x <= overlay.clientWidth && p.y <= overlay.clientHeight; }); }

  function summary() {
    if (!frame || !map) return;
    var w = frame.wind, f = frame.focus, sc = man.fields[fieldIx.wind].scale, mx = 0, gale = 0, storm = 0, foc = 0, mxk = -1;
    viewCells(function (k, j) {
      var cell = 27.8 * 27.8 * Math.cos(gLat(j) * Math.PI / 180), v = w[k] / sc;
      if (v > mx) { mx = v; mxk = k; } if (v >= 34) gale += cell; if (v >= 48) storm += cell; if (f[k] >= 2) foc += cell;
    });
    var area = function (a) { return a < 5000 ? (a > 0 ? "small" : "none") : "about " + (Math.round(a / 10000) * 10000).toLocaleString("en-US") + " km²"; };
    var where = mxk >= 0 ? " near " + latText(gLat((mxk / grid.nx) | 0), 0) + " " + lonText(gLon(mxk % grid.nx), 0) : "";
    var h = "<h3>In view at this hour</h3>" +
      "<p>Highest blended wind <b>" + Math.round(mx) + " kt</b>" + where + "</p>" +
      "<p>Gale area <b>" + area(gale) + "</b>, storm area <b>" + area(storm) + "</b></p>" +
      "<p>Focus or high-impact area <b>" + area(foc) + "</b></p>";
    if (hasStorm()) {
      var hzA = { 2: 0, 4: 0 };
      viewCells(function (k, j) { var hb = frame.hazard[k]; if (hb & 2) hzA[2] += 27.8 * 27.8 * Math.cos(gLat(j) * Math.PI / 180); if (hb & 4) hzA[4] += 27.8 * 27.8 * Math.cos(gLat(j) * Math.PI / 180); });
      h += "<p>Storm possible <b>" + area(hzA[2]) + "</b>, hurricane force possible <b>" + area(hzA[4]) + "</b></p>";
    }
    if (tracks.length) {
      var step = man.steps[state.step].step, tv = tracks.map(function (t) { return trackAt(t, step); }).filter(function (p) { return p && inView(p.lon, p.lat); });
      var deep = tracks.map(function (t) { var p = t.filter(function (q) { return q.step >= step; })[0]; return p && inView(p.lon, p.lat) ? p : null; }).filter(Boolean).sort(function (a, b) { return a.hpa - b.hpa; })[0];
      h += "<p>Tracked lows <b>" + tv.length + "</b>" + (deep ? ", deepest <b>" + Math.round(deep.hpa) + " hPa</b> at +" + deep.step + " h" : "") + "</p>";
    }
    var vis = areas.filter(function (a) { return inView(gLon(a.peak % grid.nx), gLat((a.peak / grid.nx) | 0)); });
    if (vis.length) {
      h += "<p>Lone-model signals, strongest first:</p>" + vis.slice(0, 5).map(function (a) {
        return '<p class="sub"><span style="color:' + MODEL_COLOR[a.model] + '">' + MODEL_NAME[a.model] + "</span> " + Math.round(a.speed) +
          " kt alone at " + a.thr + " kt; <b>" + Math.round(a.prob) + "%</b> of members agree</p>";
      }).join("") + (vis.length > 5 ? '<p class="sub">and ' + (vis.length - 5) + " more</p>" : "");
    } else h += "<p>No lone-model storm signals.</p>";
    $("summary").innerHTML = h;
  }

  // ---------------------------------------------------------------- readout
  function readout(pt, ll) {
    if (!frame) return;
    var box = $("readout"), onGlobe = map.transform.isPointOnMapSurface(pt);
    var c = onGlobe && Math.abs(ll.lat) <= MAXLAT ? cellOf(ll.lng, ll.lat) : null;
    $("coords").textContent = onGlobe ? latText(ll.lat, 2) + " " + lonText(ll.lng, 2) : "";
    if (!c) { box.hidden = true; hover = null; drawOverlay(); return; }
    var k = c.k, b = frame, V = function (n) { return value(b, n, k); };
    var lat = gLat(c.j), lon = gLon(c.i);
    hover = { lon: lon, lat: lat };
    var fmt = function (v) { return Math.round(v); };
    var lone = b.lone[k], notes = [];
    if (lone & 3) notes.push(MODEL_NAME[lone & 3] + " alone at 48 kt");
    if ((lone >> 2) & 3) notes.push(MODEL_NAME[(lone >> 2) & 3] + " alone at 64 kt");
    if (!inTested(lon, lat)) notes.push(Math.abs(lat) < 25 ? "Outside the tested area; tropical cyclones are beyond this blend" : "Outside the area the blend and chances were tested on");
    else if (CHANCE_MONTHS.indexOf(new Date(man.steps[state.step].valid).getUTCMonth()) < 0) notes.push("Chances were fitted on November to March only");
    var foc = FOCUS.cats[b.focus[k]][0];
    var tr = man.steps[state.step].trend ? '<tr><td>Since run 24 h earlier</td><td>' + (V("trend") >= 0 ? "+" : "") + V("trend").toFixed(1) + " kt</td></tr>" : "";
    box.innerHTML = '<div class="h">' + latText(lat, 2) + " " + lonText(lon, 2) + "</div><table>" +
      "<tr><td>Blended wind</td><td>" + fmt(V("wind")) + " kt " + Math.round(V("dir") / 10) * 10 + "°</td></tr>" +
      "<tr><td>Model base</td><td>" + fmt(V("mean")) + " kt</td></tr>" +
      "<tr><td>Added</td><td>+" + V("boost").toFixed(1) + " kt</td></tr>" +
      "<tr><td>Deterministic blend</td><td>" + fmt(V("nomem")) + " kt</td></tr>" +
      '<tr class="sep"><td>GFS</td><td>' + fmt(V("gfs")) + " kt</td></tr>" +
      "<tr><td>ECMWF</td><td>" + fmt(V("ecmwf")) + " kt</td></tr>" +
      "<tr><td>AIFS</td><td>" + fmt(V("aifs")) + " kt</td></tr>" +
      '<tr class="sep"><td>Member spread</td><td>' + V("sigma").toFixed(1) + " kt</td></tr>" +
      "<tr><td>Chance 34 / 48 / 64</td><td>" + fmt(V("p34")) + " / " + fmt(V("p48")) + " / " + fmt(V("p64")) + "%</td></tr>" +
      (fieldIx.p34raw != null ? "<tr><td>Raw members 34 / 48 / 64</td><td>" + fmt(V("p34raw")) + " / " + fmt(V("p48raw")) + " / " + fmt(V("p64raw")) + "%</td></tr>"
        : "<tr><td>Raw members 48 / 64</td><td>" + fmt(V("p48raw")) + " / " + fmt(V("p64raw")) + "%</td></tr>") + tr +
      "<tr><td>Agreement</td><td>" + foc + "</td></tr>" +
      "<tr><td>Pressure</td><td>" + V("msl") + " hPa</td></tr>" +
      (hasStorm() ? '<tr class="sep"><td>Core Lifted</td><td>' + fmt(V("windcore")) + " kt</td></tr>" +
        "<tr><td>Storm core chance</td><td>" + (Math.abs(lat) < 25 ? "not made" : fmt(V("core")) + "%") + "</td></tr>" +
        (b.hazard[k] ? "<tr><td>Possible</td><td>" + HAZARD.filter(function (d) { return b.hazard[k] & d[0]; }).map(function (d) { return d[1].replace(" possible", ""); }).join(", ") + "</td></tr>" : "") +
        (b.warn && b.warn[k] ? "<tr><td>Warning area</td><td>" + WARN.filter(function (d) { return b.warn[k] & d[0]; }).map(function (d) { return d[1].replace(" warning area", ""); }).join(", ") + "</td></tr>" : "") : "") +
      "</table>" +
      (notes.length ? '<div class="note-line">' + notes.join("; ") + "</div>" : "");
    box.hidden = false;
    var r = $("map").getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight;
    box.style.left = (pt.x + 14 + bw > r.width ? Math.max(4, pt.x - 14 - bw) : pt.x + 14) + "px";
    var top = document.querySelector(".topbar").getBoundingClientRect().bottom + 6;
    var bot = document.querySelector(".timeline").getBoundingClientRect().top - 6;
    box.style.top = Math.max(top, Math.min(bot - bh, pt.y - bh / 2)) + "px";
    drawOverlay();
  }

  // ---------------------------------------------------------------- controls
  var icon = K.icon;

  function show(b) {
    frame = b;
    lines = computeLines(b);
    areas = loneAreas(b);
    paintField(b);
    updateLines();
    placeLabels();
    drawOverlay();
    summary();
  }
  // Events for a page that hosts this one and adds its own layers:
  // mw:ready {map}, mw:step {valid, step, cycle}, mw:overlay {ctx, proj, font, width, height}
  function emit(name, detail) { document.dispatchEvent(new CustomEvent(name, { detail: detail })); }
  function busy(on) { $("progress").classList.toggle("active", on); }
  function setStep(i) {
    state.step = Math.max(0, Math.min(man.steps.length - 1, i));
    $("lead").value = state.step;
    var st = man.steps[state.step];
    $("validTime").textContent = K.fmtValid(st.valid);
    $("validRel").textContent = "+" + st.step + " h · " + fmtTime(man.cycle) + " run";
    $("tlHour").textContent = "+" + st.step + " h";
    $("tlCycle").textContent = fmtTime(st.valid, true);
    $("prev").disabled = state.step === 0;
    $("next").disabled = state.step === man.steps.length - 1;
    if (rail) rail.done(state.step);
    emit("mw:step", { valid: st.valid, step: st.step, cycle: man.cycle });
    busy(true);
    loadStep(state.step).then(function (b) {
      if (man.steps[state.step].step !== st.step) return;
      busy(false); $("status").textContent = "";
      show(b); writeHash();
      if (state.step + 1 < man.steps.length) loadStep(state.step + 1).catch(function () {});
    }).catch(function (e) { busy(false); note("Could not load +" + st.step + " h (" + e.message + ")"); });
  }
  function setLayer(name) {
    state.layer = name;
    Array.prototype.forEach.call($("layers").querySelectorAll("button"), function (b) { b.setAttribute("aria-checked", b.dataset.layer === name ? "true" : "false"); });
    legend();
    if (frame) { paintField(frame); updateLines(); }
    writeHash();
  }
  function setView(key) {
    state.view = key;
    Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (a) {
      a.setAttribute("aria-checked", a.dataset.view === key ? "true" : "false");
    });
  }
  function goView(key) {
    var v = VIEWS[key];
    if (v.center) map.flyTo({ center: v.center, zoom: globalZoom(), bearing: 0, pitch: 0, duration: 900 });
    else map.fitBounds(v.bounds, { padding: viewPadding(), bearing: 0, pitch: 0, duration: 900 });
    setView(key);
  }
  var globalZoom = K.globalZoom;
  // the scorecard follows the basin the map is centred on
  window.MW_scoreBasin = function () {
    if (!map) return "natl";
    var lon = wrapLon(map.getCenter().lng);
    return lon >= 100 || lon < -100 ? "npac" : "natl";
  };
  function writeHash() {
    if (!man || !map) return;
    var c = map.getCenter();
    try {
      history.replaceState(null, "", location.pathname + location.search.replace(/[?&]basin=\w+/, "").replace(/^&/, "?") +
        "#" + state.layer + "/" + man.steps[state.step].step + "/" + map.getZoom().toFixed(2) + "/" + c.lat.toFixed(2) + "/" + wrapLon(c.lng).toFixed(2));
    } catch (e) { /* file:// */ }
  }
  // #layer/step[/zoom/lat/lon]; ?basin=natl|npac (older links) opens that OPC area
  function readHash() {
    var start = { center: VIEWS.global.center, zoom: globalZoom(), key: "global" };
    var b = /[?&]basin=(natl|npac)\b/.exec(location.search);
    if (b) start = { bounds: VIEWS[b[1]].bounds, key: b[1] };
    var m = /^#(\w+)\/(\d+)(?:\/([\d.]+)\/(-?[\d.]+)\/(-?[\d.]+))?$/.exec(location.hash);
    if (m) {
      if (layerDef(m[1]) && layerDef(m[1]).length > 1) state.layer = m[1];
      man.steps.forEach(function (s, i) { if (s.step === +m[2]) state.step = i; });
      if (m[3]) start = { center: [+m[5], +m[4]], zoom: +m[3], key: null };
    }
    return start;
  }

  var setPanelOpen = K.setPanelOpen;
  function togglePlay() {
    var btn = $("play");
    if (playTimer) { clearInterval(playTimer); playTimer = null; }
    else playTimer = setInterval(function () { setStep(state.step + 1 >= man.steps.length ? 0 : state.step + 1); }, 1500);
    btn.innerHTML = icon(playTimer ? "pause" : "play");
    btn.setAttribute("aria-label", playTimer ? "Pause" : "Play");
  }
  // a small swatch of each layer's colours for the layer list
  function ramp(pal) {
    if (pal.cats) return "linear-gradient(90deg," + pal.cats.slice(1).map(function (c, k, a) { return c[1] + " " + (k / a.length * 100) + "% " + ((k + 1) / a.length * 100) + "%"; }).join(",") + ")";
    var cs = pal.colors.filter(function (c) { return c.indexOf("rgba(0,0,0,0)") < 0; });
    return "linear-gradient(90deg," + cs.join(",") + ")";
  }
  var HOTKEYS = { wind: "1", focus: "2", p34: "3", p48: "4" };
  function buildControls() {
    var box = $("layers");
    LAYERS.filter(function (L, i) {
      // only the layers this run has (older runs lack the storm fields)
      if (L.length > 1) return fieldIx[L[0]] !== undefined;
      var nxt = LAYERS[i + 1];
      return nxt && nxt.length > 1 && fieldIx[nxt[0]] !== undefined;
    }).forEach(function (L) {
      if (L.length === 1) { var g = document.createElement("div"); g.className = "grp"; g.textContent = L[0]; box.appendChild(g); return; }
      var b = document.createElement("button");
      b.type = "button"; b.className = "product"; b.setAttribute("role", "radio"); b.dataset.layer = L[0];
      b.innerHTML = '<i class="product-ramp" style="background:' + ramp(L[2]) + '"></i><span class="product-name">' + L[1] + "</span>" +
        (HOTKEYS[L[0]] ? '<kbd class="on">' + HOTKEYS[L[0]] + "</kbd>" : "<kbd>0</kbd>");
      b.addEventListener("click", function () { setLayer(L[0]); if (isMobile()) setPanelOpen(false); });
      box.appendChild(b);
    });
    $("btnLayers").innerHTML = icon("layers");
    $("btnHelp").innerHTML = icon("help");
    ["btnPanelClose", "btnHelpClose", "about-close", "sc-close"].forEach(function (id) { $(id).innerHTML = icon("close"); });
    $("prev").innerHTML = icon("prev"); $("next").innerHTML = icon("next"); $("play").innerHTML = icon("play");
    $("btnLayers").addEventListener("click", function () { setPanelOpen(!document.body.classList.contains("panel-open")); });
    $("btnPanelClose").addEventListener("click", function () { setPanelOpen(false); });
    $("scrim").addEventListener("click", function () { setPanelOpen(false); });
    $("btnHelp").addEventListener("click", function () { $("helpDialog").showModal(); });
    $("btnHelpClose").addEventListener("click", function () { $("helpDialog").close(); });
    $("opacity").value = state.opacity;
    $("opacity").addEventListener("input", function () {
      state.opacity = +this.value; $("opacityOut").textContent = Math.round(state.opacity * 100) + "%";
      if (map && map.getLayer("field")) map.setPaintProperty("field", "raster-opacity", state.opacity);
    });
    $("opacityOut").textContent = Math.round(state.opacity * 100) + "%";

    $("lead").max = man.steps.length - 1;
    $("lead").addEventListener("input", function () { setStep(+this.value); });
    $("prev").addEventListener("click", function () { setStep(state.step - 1); });
    $("next").addEventListener("click", function () { setStep(state.step + 1); });
    $("play").addEventListener("click", togglePlay);
    var OV = [["ov-lone", "lone", "s"], ["ov-msl", "msl", "i"], ["ov-arrows", "arrows", "a"], ["ov-edges", "edges", "e"], ["ov-tested", "tested", "t"],
              ["ov-hazard", "hazard", "h"], ["ov-warn", "warn", "w"], ["ov-track", "track", "c"]];
    if (!hasStorm()) { $("storm-sec").hidden = true; OV = OV.slice(0, 5); }
    else if (!hasWarn()) { $("warn-row").hidden = true; OV = OV.filter(function (p) { return p[1] !== "warn"; }); }
    function overlayChanged() { legend(); setTested(); if (frame) { updateLines(); placeLabels(); drawOverlay(); } }
    OV.forEach(function (p) {
      $(p[0]).checked = state[p[1]];
      $(p[0]).addEventListener("change", function () { state[p[1]] = this.checked; overlayChanged(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (a) {
      a.addEventListener("click", function () { goView(a.dataset.view); });
    });
    document.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target.tagName === "INPUT" && e.target.type !== "range" && e.target.type !== "checkbox") return;
      if (e.key === "Escape") {
        if (!$("about").hidden) closeAbout();
        else if (!$("scorecard").hidden) $("sc-close").click();
        else if (isMobile()) setPanelOpen(false);
        return;
      }
      if ($("helpDialog").open || !$("about").hidden || !$("scorecard").hidden) return;
      if (e.target.closest && e.target.closest("#map")) return;   // the map pans with the arrow keys
      var k = e.key.toLowerCase(), hit = true;
      if (e.key === "ArrowRight") setStep(state.step + 1);
      else if (e.key === "ArrowLeft") setStep(state.step - 1);
      else if (e.key === "Home") setStep(0);
      else if (e.key === "End") setStep(man.steps.length - 1);
      else if (e.key === " " && e.target.tagName !== "BUTTON") togglePlay();
      else if (k === "l") setPanelOpen(!document.body.classList.contains("panel-open"));
      else if (e.key === "?") $("helpDialog").showModal();
      else if (k === "g") goView("global");
      else if (k === "n") goView("natl");
      else if (k === "p") goView("npac");
      else {
        var lay = Object.keys(HOTKEYS).filter(function (n) { return HOTKEYS[n] === e.key; })[0];
        var ov = OV.filter(function (p) { return p[2] === k; })[0];
        if (lay) setLayer(lay);
        else if (ov) { $(ov[0]).checked = !$(ov[0]).checked; state[ov[1]] = $(ov[0]).checked; overlayChanged(); }
        else hit = false;
      }
      if (hit) e.preventDefault();
    });
    $("about-btn").addEventListener("click", function () { $("about").hidden = false; this.setAttribute("aria-expanded", "true"); });
    $("about-close").addEventListener("click", closeAbout);
    $("about").addEventListener("click", function (e) { if (e.target === this) closeAbout(); });
    rail = K.timeline(man.steps.map(function (st) { return st.valid; }));
  }
  // builds run about 8.5 h after each cycle, so a run is up to ~21 h old in normal service;
  // past a day a build has been missed
  // The next run (cycle + 6 h) is built once its ECMWF ensemble reaches +120 h on AWS, which posts
  // about 7 h after 06Z/18Z and 7.7 h after 00Z/12Z; the job checks hourly at :30 and takes ~10 min.
  var NEXT_LAG_MIN = { 0: 510, 6: 460, 12: 510, 18: 460 };
  function nextRun(cycle) {
    var c = new Date(cycle.getTime() + 6 * 3600000);
    return { cycle: c, due: new Date(c.getTime() + NEXT_LAG_MIN[c.getUTCHours()] * 60000) };
  }
  function runAge(cycle) {
    var h = Math.floor((Date.now() - cycle.getTime()) / 3600000), chip = $("chipRun");
    if (h < 0) return;
    var nx = nextRun(cycle), late = Date.now() > nx.due.getTime() + 45 * 60000;
    var hhmm = ("0" + nx.due.getUTCHours()).slice(-2) + ":" + ("0" + nx.due.getUTCMinutes()).slice(-2);
    var nxt = ("0" + nx.cycle.getUTCHours()).slice(-2) + "Z";
    chip.dataset.state = h > 24 ? "warn" : "ok";
    chip.title = "The newest run on this page is " + h + " h old" + (h > 24 ? " (a newer run is overdue)" : "") + ". " +
      "The next one, " + nxt + ", is expected about " + hhmm + " UTC: it is built once the ECMWF ensemble reaches +120 h " +
      "(about 7 h after 06/18Z, 8 h after 00/12Z), checked hourly at :30.";
    chip.lastChild.textContent = fmtTime(cycle.toISOString()) + " run · next " + (late ? nxt + " late" : "~" + hhmm + "Z");
  }
  function closeAbout() { $("about").hidden = true; $("about-btn").setAttribute("aria-expanded", "false"); }

  function ready() {
    document.body.classList.remove("loading");
    emit("mw:ready", { map: map });
    setLayer(state.layer);
    setStep(state.step);
  }

  // ------------------------------------------------------------------- start
  function fatal(msg) { $("fatalMsg").textContent = msg; $("fatal").hidden = false; }
  setPanelOpen(!isMobile());
  if (!K.webgl()) {
    fatal("This page needs a browser with WebGL enabled.");
    return;
  }
  maplibregl.addProtocol("mwfield", function (params) {
    var m = /mwfield:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url);
    return fieldTile(+m[1], +m[2], +m[3]).then(function (data) { return { data: data }; });
  });
  fetch(DATA + "manifest.json", { cache: "no-cache" }).then(function (r) {
    if (!r.ok) throw new Error("manifest " + r.status);
    return r.json();
  }).then(function (m) {
    man = m; grid = m.grid;
    m.fields.forEach(function (f, i) { fieldIx[f.name] = i; });
    var c = new Date(m.cycle);
    $("runInfo").textContent = "GFS, ECMWF, AIFS + " + m.steps[0].members + " members" +
      (m.steps[0].prob_members > m.steps[0].members ? " (" + m.steps[0].prob_members + " for chances)" : "");
    runAge(c); setInterval(function () { runAge(c); }, 60000);
    if (m.tracks) fetch(DATA + m.tracks + "?c=" + encodeURIComponent(m.cycle)).then(function (r) { return r.ok ? r.json() : null; }).then(function (t) {
      tracks = (t && t.tracks || []).filter(function (x) { return x.length; });
      if (map && frame) { updateTracks(); legend(); summary(); drawOverlay(); }
    }).catch(function () {});
    var start = readHash();
    buildControls();
    setView(start.key);
    buildMap(start);
  }).catch(function (e) {
    var chip = $("chipRun"); chip.dataset.state = "error"; chip.lastChild.textContent = "No run available";
    fatal("Could not load the forecast (" + e.message + ").");
  });
})();
