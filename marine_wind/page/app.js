/* Marine Wind: draws one layer of the newest run's grids for the North Atlantic
   (data/) or, with ?basin=npac, the North Pacific (data/npac/)
   (manifest.json + fFFF.bin, made by marine_wind/pipeline/build.py)
   on a Mercator canvas, with pressure, the blend's 34/48 kt edges, wind
   arrows and lone-model storm signals on top, and a point readout. */
(function () {
  "use strict";

  var BASIN = /[?&]basin=npac\b/.test(location.search) ? "npac" : "natl";
  var DATA = BASIN === "npac" ? "data/npac/" : "data/";
  var BASIN_NAME = { natl: "North Atlantic", npac: "North Pacific" };
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
    focus: "Models agree everywhere at this hour"
  };
  var MODEL_COLOR = ["", "#f08a5d", "#7fb0ee", "#c3a6f0"];
  var MODEL_NAME = ["", "GFS", "ECMWF", "AIFS"];

  var LAYERS = [
    ["Forecast"],
    ["wind", "Blended wind", WIND],
    ["mean", "Model base (weighted average)", WIND],
    ["boost", "Added wind", BOOST],
    ["Where to look"],
    ["focus", "Model agreement", FOCUS],
    ["sigma", "Member spread", SPREAD],
    ["trend", "Change since yesterday's run", TREND],
    ["Ensemble chance"],
    ["p34", "Gale, 34 kt+", PROB],
    ["p48", "Storm, 48 kt+", PROB],
    ["p64", "Hurricane force, 64 kt+", PROB],
    ["Single models"],
    ["gfs", "GFS", WIND],
    ["ecmwf", "ECMWF", WIND],
    ["aifs", "AIFS", WIND]
  ];

  // ------------------------------------------------------------------- state
  var man = null, grid = null, fieldIx = {}, cache = {}, frame = null;
  var state = { layer: "wind", step: 0, lone: true, msl: true, arrows: false, edges: true };
  var canvas = $("map"), ctx = canvas.getContext("2d");
  var view = null, off = document.createElement("canvas"), offCtx = off.getContext("2d");
  var hover = null, playTimer = null;

  // -------------------------------------------------------------- projection
  function mercY(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); }
  function invMercY(y) { return (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI; }

  function fit() {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var g = grid, pad = 8;
    var lonSpan = (g.east + 0.25 - g.west) * Math.PI / 180;
    var yN = mercY(g.north + 0.125), yS = mercY(g.south - 0.125);
    var s = Math.min((w - 2 * pad) / lonSpan, (h - 2 * pad) / (yN - yS));
    var mw = lonSpan * s, mh = (yN - yS) * s;
    view = { s: s, x0: (w - mw) / 2, y0: (h - mh) / 2, w: mw, h: mh, yN: yN, w0: g.west - 0.125, cw: w, ch: h };
  }
  function px(lon, lat) {
    return [view.x0 + (lon - view.w0) * Math.PI / 180 * view.s, view.y0 + (view.yN - mercY(lat)) * view.s];
  }
  function lonlat(x, y) {
    return [view.w0 + (x - view.x0) / view.s * 180 / Math.PI, invMercY(view.yN - (y - view.y0) / view.s)];
  }
  // grid index (fractional) -> screen
  function gpx(i, j) { return px(grid.west + i * grid.res, grid.north - j * grid.res); }

  // ------------------------------------------------------------------- data
  function getField(buf, name) {
    var k = fieldIx[name], n = grid.nx * grid.ny;
    return new Uint8Array(buf, k * n, n);
  }
  function value(buf, name, idx) {
    var f = man.fields[fieldIx[name]];
    var v = getField(buf, name)[idx];
    return name === "msl" ? v + 900 : v / f.scale - (f.offset || 0);
  }
  function loadStep(i) {
    var st = man.steps[i];
    if (cache[st.step]) return Promise.resolve(cache[st.step]);
    var name = "f" + ("00" + st.step).slice(-3) + ".bin";
    return fetch(DATA + name + "?c=" + encodeURIComponent(man.cycle)).then(function (r) {
      if (!r.ok) throw new Error(name + " " + r.status);
      return r.arrayBuffer();
    }).then(function (b) { cache[st.step] = b; return b; });
  }

  // -------------------------------------------------------------- rendering
  function colorTable(pal) {
    // 256 entries indexed by the stored byte for this layer
    var t = new Uint8ClampedArray(256 * 4), f = man.fields[fieldIx[state.layer]];
    var tmp = document.createElement("canvas").getContext("2d");
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

  function drawField(buf) {
    var pal = layerDef(state.layer)[2];
    var nx = grid.nx, ny = grid.ny, data = getField(buf, state.layer), tab = colorTable(pal);
    // run change: only where either run has 25 kt or more (3-model mean now, or now minus the change)
    var keep = null;
    if (state.layer === "trend") {
      var g = getField(buf, "gfs"), e = getField(buf, "ecmwf"), a = getField(buf, "aifs");
      var ms = man.fields[fieldIx.gfs].scale, tf = man.fields[fieldIx.trend];
      keep = function (i) {
        var now = (g[i] + e[i] + a[i]) / (3 * ms), was = now - (data[i] / tf.scale - (tf.offset || 0));
        return now >= TREND_MIN || was >= TREND_MIN;
      };
    }
    off.width = nx; off.height = ny;
    var img = offCtx.createImageData(nx, ny), d = img.data, shown = 0;
    for (var i = 0; i < nx * ny; i++) {
      var o = data[i] * 4, al = keep && !keep(i) ? 0 : tab[o + 3];
      d[i * 4] = tab[o]; d[i * 4 + 1] = tab[o + 1]; d[i * 4 + 2] = tab[o + 2]; d[i * 4 + 3] = al;
      if (al) shown++;
    }
    offCtx.putImageData(img, 0, 0);
    var note = EMPTY[state.layer], el = $("empty");
    el.textContent = note && !shown ? note : "";
    el.hidden = !(note && !shown);
    ctx.imageSmoothingEnabled = false;
    // one screen row at a time so the lat-lon grid lands on Mercator rows
    var top = Math.floor(view.y0), bot = Math.ceil(view.y0 + view.h);
    for (var y = top; y < bot; y++) {
      var lat = lonlat(0, y + 0.5)[1];
      var j = Math.round((grid.north - lat) / grid.res);
      if (j < 0 || j >= ny) continue;
      ctx.drawImage(off, 0, j, nx, 1, view.x0, y, view.w, 1);
    }
  }

  function drawLand() {
    var rings = (BASIN === "npac" ? window.MW_COAST_NPAC : window.MW_COAST) || [];
    ctx.save();
    ctx.beginPath();
    ctx.rect(view.x0, view.y0, view.w, view.h);
    ctx.clip();
    ctx.beginPath();
    rings.forEach(function (r) {
      r.forEach(function (p, k) { var q = px(p[0], p[1]); if (k) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]); });
      ctx.closePath();
    });
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--land");
    ctx.fill();
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--coast");
    ctx.lineWidth = 0.7;
    ctx.stroke();
    ctx.restore();
  }

  function drawGraticule() {
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.07)"; ctx.lineWidth = 1;
    ctx.fillStyle = "rgba(233,232,227,0.45)"; ctx.font = "10px " + getComputedStyle(document.body).fontFamily;
    for (var lon = Math.ceil(grid.west / 10) * 10; lon <= grid.east; lon += 10) {
      var a = px(lon, grid.north + 0.125), b = px(lon, grid.south - 0.125);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.fillText(lonText(lon, 0), b[0] + 3, b[1] - 4);
    }
    for (var lat = 30; lat <= 65; lat += 5) {
      var c = px(grid.west - 0.125, lat), e = px(grid.east + 0.125, lat);
      ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(e[0], e[1]); ctx.stroke();
      if (lat > 30) ctx.fillText(lat + "N", c[0] + 3, c[1] - 3);
    }
    ctx.restore();
  }

  function lonText(lon, dp) {
    var l = ((lon + 540) % 360) - 180;   // -180..180
    return Math.abs(l).toFixed(dp) + (l < 0 ? "W" : l > 0 && l < 180 ? "E" : "");
  }

  // marching squares: segments of the level-`lev` contour of values f(i,j)
  function contour(get, lev) {
    var nx = grid.nx, ny = grid.ny, segs = [];
    function lerp(a, b) { return (lev - a) / (b - a); }
    for (var j = 0; j < ny - 1; j++) {
      for (var i = 0; i < nx - 1; i++) {
        var a = get(i, j), b = get(i + 1, j), c = get(i + 1, j + 1), d = get(i, j + 1);
        var k = (a >= lev ? 8 : 0) | (b >= lev ? 4 : 0) | (c >= lev ? 2 : 0) | (d >= lev ? 1 : 0);
        if (k === 0 || k === 15) continue;
        var T = [i + lerp(a, b), j], R = [i + 1, j + lerp(b, c)], B = [i + lerp(d, c), j + 1], L = [i, j + lerp(a, d)];
        switch (k) {
          case 1: case 14: segs.push([L, B]); break;
          case 2: case 13: segs.push([B, R]); break;
          case 3: case 12: segs.push([L, R]); break;
          case 4: case 11: segs.push([T, R]); break;
          case 6: case 9: segs.push([T, B]); break;
          case 7: case 8: segs.push([L, T]); break;
          case 5: segs.push([L, T]); segs.push([B, R]); break;
          case 10: segs.push([T, R]); segs.push([L, B]); break;
        }
      }
    }
    return segs;
  }
  function strokeSegs(segs) {
    ctx.beginPath();
    segs.forEach(function (s) { var a = gpx(s[0][0], s[0][1]), b = gpx(s[1][0], s[1][1]); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); });
    ctx.stroke();
  }

  function drawMsl(buf) {
    var m = getField(buf, "msl"), nx = grid.nx;
    var get = function (i, j) { return m[j * nx + i] + 900; };
    ctx.save();
    ctx.strokeStyle = "rgba(233,232,227,0.42)"; ctx.lineWidth = 0.8;
    var labels = [];
    for (var lev = 940; lev <= 1052; lev += 4) {
      var segs = contour(get, lev - 0.5);
      strokeSegs(segs);
      if (lev % 8 === 0) labels = labels.concat(isobarLabels(buf, segs, lev, labels));
    }
    drawIsobarLabels(labels);
    // H and L centres found by build.py on the full-precision field
    var fam = getComputedStyle(document.body).fontFamily, st = man.steps[state.step];
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillStyle = "rgba(233,232,227,0.85)";
    (st.centres || []).forEach(function (c) {
      var p = px(c[2], c[1]);
      ctx.font = "600 14px " + fam; ctx.fillText(c[0], p[0], p[1]);
      ctx.font = "10px " + fam; ctx.fillText(Math.round(c[3]), p[0], p[1] + 13);
    });
    ctx.restore();
  }

  // a few labels per isobar, kept apart from each other, the H/L centres, the map edge
  // and any 30+ kt wind, so a label never sits on a gale area
  function isobarLabels(buf, segs, lev, placed) {
    var out = [], st = man.steps[state.step], small = view.w < 600, gap = small ? 120 : 160, most = small ? 2 : 4;
    var w = getField(buf, "wind"), sc = man.fields[fieldIx.wind].scale;
    var avoid = (st.centres || []).map(function (c) { return px(c[2], c[1]); });
    for (var k = 0; k < segs.length && out.length < most; k += 7) {
      var gi = Math.round(segs[k][0][0]), gj = Math.round(segs[k][0][1]), a = gpx(segs[k][0][0], segs[k][0][1]);
      if (a[0] < view.x0 + 36 || a[0] > view.x0 + view.w - 24 || a[1] < view.y0 + 12 || a[1] > view.y0 + view.h - 18) continue;
      if (w[gj * grid.nx + gi] / sc >= 30) continue;
      var near = function (q, r) { return Math.abs(q[0] - a[0]) < r && Math.abs(q[1] - a[1]) < r; };
      if (avoid.some(function (q) { return near(q, 40); })) continue;
      if (placed.concat(out).some(function (q) { return near(q, q[2] === lev ? gap : 28); })) continue;
      out.push([a[0], a[1], lev]);
    }
    return out;
  }
  function drawIsobarLabels(labels) {
    ctx.font = "10px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    labels.forEach(function (l) {
      var t = String(l[2]), w = ctx.measureText(t).width + 4;
      ctx.fillStyle = "rgba(23,24,27,0.8)"; ctx.fillRect(l[0] - w / 2, l[1] - 6, w, 12);
      ctx.fillStyle = "rgba(233,232,227,0.75)"; ctx.fillText(t, l[0], l[1]);
    });
  }

  function drawEdges(buf) {
    var f = getField(buf, "wind"), nx = grid.nx, sc = man.fields[fieldIx.wind].scale;
    var get = function (i, j) { return f[j * nx + i] / sc; };
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = 1; ctx.setLineDash([4, 3]); strokeSegs(contour(get, 34));
    ctx.lineWidth = 1.6; ctx.setLineDash([]); strokeSegs(contour(get, 48));
    ctx.restore();
  }

  function drawArrows(buf) {
    var dir = getField(buf, "dir"), sp = getField(buf, "wind"), nx = grid.nx;
    var stepC = Math.max(4, Math.round(26 / (view.w / nx)));
    ctx.save();
    ctx.strokeStyle = "rgba(233,232,227,0.7)"; ctx.lineWidth = 1;
    for (var j = stepC / 2 | 0; j < grid.ny; j += stepC) for (var i = stepC / 2 | 0; i < nx; i += stepC) {
      var k = j * nx + i, kt = sp[k] / 2;
      if (kt < 5) continue;
      var to = (dir[k] * 2 + 180) * Math.PI / 180, L = 6 + Math.min(kt, 60) / 6;
      var p = gpx(i, j), dx = Math.sin(to) * L, dy = -Math.cos(to) * L;
      ctx.beginPath();
      ctx.moveTo(p[0] - dx / 2, p[1] - dy / 2); ctx.lineTo(p[0] + dx / 2, p[1] + dy / 2);
      var hx = p[0] + dx / 2, hy = p[1] + dy / 2, a = Math.atan2(dy, dx);
      ctx.lineTo(hx - 4 * Math.cos(a - 0.5), hy - 4 * Math.sin(a - 0.5));
      ctx.moveTo(hx, hy); ctx.lineTo(hx - 4 * Math.cos(a + 0.5), hy - 4 * Math.sin(a + 0.5));
      ctx.stroke();
    }
    ctx.restore();
  }

  // lone-model areas: connected components of each (model, threshold) mask
  function loneAreas(buf) {
    var lone = getField(buf, "lone"), nx = grid.nx, ny = grid.ny, out = [];
    [[0, 48], [2, 64]].forEach(function (sh) {
      for (var m = 1; m <= 3; m++) {
        var seen = new Uint8Array(nx * ny);
        for (var k = 0; k < nx * ny; k++) {
          if (seen[k] || ((lone[k] >> sh[0]) & 3) !== m) continue;
          var stack = [k], cells = [], best = k, bestV = -1, mf = getField(buf, MODEL_NAME[m].toLowerCase());
          seen[k] = 1;
          while (stack.length) {
            var c = stack.pop(); cells.push(c);
            if (mf[c] > bestV) { bestV = mf[c]; best = c; }
            var ci = c % nx, cj = (c / nx) | 0;
            [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) {
              var ii = ci + d[0], jj = cj + d[1];
              if (ii < 0 || jj < 0 || ii >= nx || jj >= ny) return;
              var q = jj * nx + ii;
              if (!seen[q] && ((lone[q] >> sh[0]) & 3) === m) { seen[q] = 1; stack.push(q); }
            });
          }
          if (cells.length < 8) continue; // under ~4000 km2: grid noise, not a storm signal
          out.push({ model: m, thr: sh[1], cells: cells, peak: best,
                     speed: value(buf, MODEL_NAME[m].toLowerCase(), best), prob: value(buf, "p" + sh[1], best) });
        }
      }
    });
    return out.sort(function (a, b) { return b.speed - a.speed; });
  }

  function drawLone(buf, areas) {
    var lone = getField(buf, "lone"), nx = grid.nx;
    ctx.save();
    areas.forEach(function (a) {
      var sh = a.thr === 48 ? 0 : 2;
      var get = function (i, j) { return ((lone[j * nx + i] >> sh) & 3) === a.model ? 1 : 0; };
      var lw = a.thr === 64 ? 2.4 : 1.6;
      // only this component's outline: contour the mask restricted to its bounding box
      var mn = [1e9, 1e9], mx = [-1, -1];
      a.cells.forEach(function (c) { var i = c % nx, j = (c / nx) | 0; mn = [Math.min(mn[0], i), Math.min(mn[1], j)]; mx = [Math.max(mx[0], i), Math.max(mx[1], j)]; });
      var segs = contour(function (i, j) {
        return i < mn[0] - 1 || j < mn[1] - 1 || i > mx[0] + 1 || j > mx[1] + 1 ? 0 : get(i, j);
      }, 0.5);
      // dark halo first so the outline reads on top of the warm wind colors
      ctx.setLineDash([]); ctx.strokeStyle = "rgba(10,10,12,0.85)"; ctx.lineWidth = lw + 2.4; strokeSegs(segs);
      ctx.setLineDash(a.thr === 64 ? [] : [5, 3]); ctx.strokeStyle = MODEL_COLOR[a.model]; ctx.lineWidth = lw; strokeSegs(segs);
    });
    ctx.setLineDash([]);
    ctx.font = "600 11px " + getComputedStyle(document.body).fontFamily;
    ctx.textBaseline = "bottom";
    var boxes = [];
    areas.forEach(function (a) {   // strongest first; skip a label that would overlap one already drawn
      var p = gpx(a.peak % nx, (a.peak / nx) | 0);
      var label = MODEL_NAME[a.model] + " alone " + Math.round(a.speed) + " kt";
      var w = ctx.measureText(label).width + 8, bx = [p[0] + 6, p[1] - 22, w, 16];
      if (boxes.some(function (o) { return bx[0] < o[0] + o[2] && o[0] < bx[0] + bx[2] && bx[1] < o[1] + o[3] && o[1] < bx[1] + bx[3]; })) return;
      boxes.push(bx);
      ctx.fillStyle = "rgba(23,24,27,0.88)"; ctx.fillRect(bx[0], bx[1], bx[2], bx[3]);
      ctx.fillStyle = MODEL_COLOR[a.model]; ctx.fillText(label, p[0] + 10, p[1] - 8);
    });
    ctx.restore();
  }

  function draw() {
    if (!view || !frame) return;
    var buf = frame;
    ctx.clearRect(0, 0, view.cw, view.ch);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--sea");
    ctx.fillRect(0, 0, view.cw, view.ch);
    drawField(buf);
    drawLand();
    drawGraticule();
    if (state.msl) drawMsl(buf);
    if (state.edges && state.layer !== "focus") drawEdges(buf);
    if (state.arrows) drawArrows(buf);
    var areas = loneAreas(buf);
    if (state.lone) drawLone(buf, areas);
    if (hover) drawHoverMark();
    summary(buf, areas);
  }
  function drawHoverMark() {
    var p = gpx(hover.i, hover.j);
    ctx.save(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.arc(p[0], p[1], 4, 0, 2 * Math.PI); ctx.stroke(); ctx.restore();
  }

  // ----------------------------------------------------------------- legend
  function layerDef(name) { for (var i = 0; i < LAYERS.length; i++) if (LAYERS[i][0] === name) return LAYERS[i]; return null; }

  function legend() {
    var def = layerDef(state.layer), pal = def[2], el = $("legend"), h = "";
    if (pal.cats) {
      h = '<div class="scale"><div class="t">' + pal.title + '</div><div class="keys">' + pal.cats.map(function (c, k) {
        return '<span><i style="background:' + (k ? c[1] : "transparent") + ';border:1px solid var(--rule-strong)"></i>' + c[0] + "</span>";
      }).join("") + "</div></div>";
    } else {
      h = '<div class="scale"><div class="t">' + (def[1] === "Blended wind" || pal !== WIND ? pal.title : def[1] + " (kt)") +
        (state.layer === "trend" ? ", where either run has " + TREND_MIN + "+ kt" : "") + '</div><div class="bar">' +
        pal.colors.map(function (c) { return '<span style="background:' + c + '"></span>'; }).join("") +
        '</div><div class="ticks">' + (pal.labels || pal.stops).map(function (s) { return "<span>" + s + "</span>"; }).join("") + "</div></div>";
    }
    var keys = [];
    if (state.edges && state.layer !== "focus") keys.push('<span><i class="ln" style="border-top:1px dashed #fff"></i>34 kt edge</span>',
      '<span><i class="ln" style="border-top:2px solid #fff"></i>48 kt edge</span>');
    if (state.msl) keys.push('<span><i class="ln" style="border-top:1px solid rgba(233,232,227,0.5)"></i>Isobars, 4 hPa</span>');
    if (state.lone) keys.push('<span><i class="ln" style="border-top:2px dashed var(--text)"></i>Lone 48 kt</span>',
      '<span><i class="ln" style="border-top:2px solid var(--text)"></i>Lone 64 kt</span>',
      '<span class="m">outline colour: ' + [1, 2, 3].map(function (m) { return '<span style="color:' + MODEL_COLOR[m] + '">' + MODEL_NAME[m] + "</span>"; }).join(" / ") + "</span>");
    if (keys.length) h += '<div class="keys">' + keys.join("") + "</div>";
    el.innerHTML = h;
  }

  function summary(buf, areas) {
    var w = getField(buf, "wind"), f = getField(buf, "focus"), sc = man.fields[fieldIx.wind].scale, mx = 0, gale = 0, storm = 0, foc = 0;
    for (var k = 0; k < w.length; k++) {
      var cell = 27.8 * 27.8 * Math.cos((grid.north - ((k / grid.nx) | 0) * grid.res) * Math.PI / 180), v = w[k] / sc;
      if (v > mx) mx = v; if (v >= 34) gale += cell; if (v >= 48) storm += cell; if (f[k] >= 2) foc += cell;
    }
    var area = function (a) { return a < 5000 ? (a > 0 ? "small" : "none") : "about " + (Math.round(a / 10000) * 10000).toLocaleString("en-US") + " km\u00b2"; };
    var h = "<h2>This forecast hour</h2>" +
      "<p>Highest blended wind <b>" + Math.round(mx) + " kt</b></p>" +
      "<p>Gale area <b>" + area(gale) + "</b>, storm area <b>" + area(storm) + "</b></p>" +
      "<p>Focus or high-impact area <b>" + area(foc) + "</b></p>";
    if (areas.length) {
      h += "<p>Lone-model signals, strongest first:</p>" + areas.slice(0, 5).map(function (a) {
        return '<p style="margin-left:8px"><span style="color:' + MODEL_COLOR[a.model] + '">' + MODEL_NAME[a.model] + "</span> " + Math.round(a.speed) +
          " kt alone at " + a.thr + " kt; <b>" + Math.round(a.prob) + "%</b> of members agree</p>";
      }).join("") + (areas.length > 5 ? '<p style="margin-left:8px">and ' + (areas.length - 5) + " more</p>" : "");
    } else h += "<p>No lone-model storm signals.</p>";
    $("summary").innerHTML = h;
  }

  // ---------------------------------------------------------------- readout
  function readout(ev) {
    if (!frame || !view) return;
    var r = canvas.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top, ll = lonlat(x, y);
    var i = Math.round((ll[0] - grid.west) / grid.res), j = Math.round((grid.north - ll[1]) / grid.res);
    var box = $("readout");
    if (i < 0 || j < 0 || i >= grid.nx || j >= grid.ny) { box.hidden = true; hover = null; draw(); return; }
    hover = { i: i, j: j };
    var k = j * grid.nx + i, b = frame, V = function (n) { return value(b, n, k); };
    var fmt = function (v) { return Math.round(v); };
    var lone = getField(b, "lone")[k], notes = [];
    if (lone & 3) notes.push(MODEL_NAME[lone & 3] + " alone at 48 kt");
    if ((lone >> 2) & 3) notes.push(MODEL_NAME[(lone >> 2) & 3] + " alone at 64 kt");
    var foc = FOCUS.cats[getField(b, "focus")[k]][0];
    var lat = grid.north - j * grid.res, lon = grid.west + i * grid.res;
    var p48r = fieldIx.p48raw !== undefined ? fmt(V("p48raw")) + " / " + fmt(V("p64raw")) + "%" : "";
    var tr = fieldIx.trend !== undefined && man.steps[state.step].trend ? '<tr><td>Since run 24 h earlier</td><td>' + (V("trend") >= 0 ? "+" : "") + V("trend").toFixed(1) + " kt</td></tr>" : "";
    box.innerHTML = '<div class="h">' + Math.abs(lat).toFixed(2) + "N " + lonText(lon, 2) + "</div><table>" +
      "<tr><td>Blended wind</td><td>" + fmt(V("wind")) + " kt " + Math.round(V("dir") / 10) * 10 + "°</td></tr>" +
      "<tr><td>Model base</td><td>" + fmt(V("mean")) + " kt</td></tr>" +
      "<tr><td>Added</td><td>+" + V("boost").toFixed(1) + " kt</td></tr>" +
      '<tr class="sep"><td>GFS</td><td>' + fmt(V("gfs")) + " kt</td></tr>" +
      "<tr><td>ECMWF</td><td>" + fmt(V("ecmwf")) + " kt</td></tr>" +
      "<tr><td>AIFS</td><td>" + fmt(V("aifs")) + " kt</td></tr>" +
      '<tr class="sep"><td>Member spread</td><td>' + V("sigma").toFixed(1) + " kt</td></tr>" +
      "<tr><td>Chance 34 / 48 / 64</td><td>" + fmt(V("p34")) + " / " + fmt(V("p48")) + " / " + fmt(V("p64")) + "%</td></tr>" +
      (p48r ? "<tr><td>Raw members 48 / 64</td><td>" + p48r + "</td></tr>" : "") + tr +
      "<tr><td>Agreement</td><td>" + foc + "</td></tr>" +
      "<tr><td>Pressure</td><td>" + V("msl") + " hPa</td></tr></table>" +
      (notes.length ? '<div class="note">' + notes.join("; ") + "</div>" : "");
    box.hidden = false;
    var bw = box.offsetWidth, bh = box.offsetHeight;
    box.style.left = (x + 14 + bw > r.width ? x - 14 - bw : x + 14) + "px";
    box.style.top = Math.max(4, Math.min(r.height - bh - 4, y - bh / 2)) + "px";
    draw();
  }

  // ---------------------------------------------------------------- controls
  function fmtTime(iso, withDay) {
    var d = new Date(iso);
    var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], mons = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return ("0" + d.getUTCHours()).slice(-2) + "Z " + (withDay ? days[d.getUTCDay()] + " " : "") + d.getUTCDate() + " " + mons[d.getUTCMonth()];
  }
  function setStep(i) {
    state.step = Math.max(0, Math.min(man.steps.length - 1, i));
    $("lead").value = state.step;
    var st = man.steps[state.step];
    $("valid").textContent = "+" + st.step + " h, valid " + fmtTime(st.valid, true);
    $("status").textContent = cache[st.step] ? "" : "Loading +" + st.step + " h";
    loadStep(state.step).then(function (b) {
      if (man.steps[state.step].step !== st.step) return;
      frame = b; $("status").textContent = ""; draw(); writeHash();
      if (state.step + 1 < man.steps.length) loadStep(state.step + 1).catch(function () {});
    }).catch(function (e) { $("status").textContent = "Could not load +" + st.step + " h (" + e.message + ")"; });
  }
  function setLayer(name) {
    state.layer = name;
    Array.prototype.forEach.call($("layers").querySelectorAll("button"), function (b) { b.setAttribute("aria-checked", b.dataset.layer === name ? "true" : "false"); });
    legend(); draw(); writeHash();
  }
  function writeHash() {
    try { history.replaceState(null, "", "#" + state.layer + "/" + man.steps[state.step].step); } catch (e) { /* file:// */ }
  }
  function readHash() {
    var m = /^#(\w+)\/(\d+)$/.exec(location.hash);
    if (!m) return;
    if (layerDef(m[1]) && layerDef(m[1]).length > 1) state.layer = m[1];
    man.steps.forEach(function (s, i) { if (s.step === +m[2]) state.step = i; });
  }

  function buildBasin() {
    document.title = BASIN_NAME[BASIN] + " Marine Wind";
    $("title").textContent = BASIN_NAME[BASIN] + " Marine Wind";
    $("map").setAttribute("aria-label", "Map of the selected wind layer over the " + BASIN_NAME[BASIN]);
    Array.prototype.forEach.call(document.querySelectorAll("[data-basin]"), function (a) {
      a.setAttribute("aria-current", a.dataset.basin === BASIN ? "page" : "false");
      a.href = (a.dataset.basin === "npac" ? "?basin=npac" : "./") + location.hash;
    });
  }
  buildBasin();

  function buildControls() {
    var box = $("layers");
    LAYERS.forEach(function (L) {
      if (L.length === 1) { var g = document.createElement("div"); g.className = "grp"; g.textContent = L[0]; box.appendChild(g); return; }
      var b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio"); b.dataset.layer = L[0]; b.textContent = L[1];
      b.addEventListener("click", function () { setLayer(L[0]); });
      box.appendChild(b);
    });
    $("lead").max = man.steps.length - 1;
    $("lead").addEventListener("input", function () { setStep(+this.value); });
    $("prev").addEventListener("click", function () { setStep(state.step - 1); });
    $("next").addEventListener("click", function () { setStep(state.step + 1); });
    $("play").addEventListener("click", function () {
      if (playTimer) { clearInterval(playTimer); playTimer = null; this.innerHTML = "&#9654;"; return; }
      this.innerHTML = "&#10074;&#10074;";
      playTimer = setInterval(function () { setStep(state.step + 1 >= man.steps.length ? 0 : state.step + 1); }, 1200);
    });
    [["ov-lone", "lone"], ["ov-msl", "msl"], ["ov-arrows", "arrows"], ["ov-edges", "edges"]].forEach(function (p) {
      $(p[0]).checked = state[p[1]];
      $(p[0]).addEventListener("change", function () { state[p[1]] = this.checked; legend(); draw(); });
    });
    document.addEventListener("keydown", function (e) {
      if (e.target.tagName === "INPUT" && e.target.type !== "range" && e.target.type !== "checkbox") return;
      if (e.key === "ArrowRight") { setStep(state.step + 1); e.preventDefault(); }
      if (e.key === "ArrowLeft") { setStep(state.step - 1); e.preventDefault(); }
      if (e.key === "Escape") closeAbout();
    });
    canvas.addEventListener("pointermove", readout);
    canvas.addEventListener("pointerdown", readout);
    canvas.addEventListener("pointerleave", function () { $("readout").hidden = true; hover = null; draw(); });
    window.addEventListener("resize", function () { fit(); draw(); });
    $("about-btn").addEventListener("click", function () { $("about").hidden = false; this.setAttribute("aria-expanded", "true"); });
    $("about-close").addEventListener("click", closeAbout);
    $("about").addEventListener("click", function (e) { if (e.target === this) closeAbout(); });
  }
  // builds run about 8.5 h after each cycle, so a run is up to ~21 h old in normal service;
  // past a day a build has been missed
  function runAge(cycle) {
    var h = Math.floor((Date.now() - cycle.getTime()) / 3600000), el = $("age");
    if (!el || h < 0) return;
    el.textContent = "(" + h + " h old" + (h > 24 ? ", a newer run is overdue" : "") + ")";
    el.className = h > 24 ? "old" : "";
  }
  function closeAbout() { $("about").hidden = true; $("about-btn").setAttribute("aria-expanded", "false"); }

  // ------------------------------------------------------------------- start
  fetch(DATA + "manifest.json", { cache: "no-cache" }).then(function (r) {
    if (!r.ok) throw new Error("manifest " + r.status);
    return r.json();
  }).then(function (m) {
    man = m; grid = m.grid;
    if (layerDef("trend") && !m.fields.some(function (f) { return f.name === "trend"; })) LAYERS.splice(LAYERS.indexOf(layerDef("trend")), 1);
    m.fields.forEach(function (f, i) { fieldIx[f.name] = i; });
    var c = new Date(m.cycle);
    $("run").innerHTML = fmtTime(m.cycle, true) + " " + c.getUTCFullYear() + ' run <span id="age"></span> · GFS, ECMWF, AIFS + ' + m.steps[0].members + " members" +
      (m.steps[0].prob_members > m.steps[0].members ? " (" + m.steps[0].prob_members + " with the AIFS ensemble for chances)" : "");
    runAge(c); setInterval(function () { runAge(c); }, 60000);
    readHash();
    buildControls();
    document.body.classList.remove("loading");
    fit();
    setLayer(state.layer);
    setStep(state.step);
  }).catch(function (e) {
    $("run").textContent = "No run available";
    $("status").textContent = "Could not load the forecast (" + e.message + ")";
  });
})();
