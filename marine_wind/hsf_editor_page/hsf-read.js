/* HSF reader: turns High Seas Forecast text (OPC HSFAT1 / HSFEP1) into map areas.

   Shared by the HSF editor page (in the browser, needs lib/polygon-clipping.min.js loaded first)
   and its tests (node: require("./hsf-read.js")). Plain ES5 so it runs anywhere.

   HsfRead.read(text, basin) -> {
     basin, valid: {0: "1200 UTC NOV 11", 24: ...},
     paras: [{ start, end,          // character offsets of the paragraph in `text`
               section,             // "warnings" | "synopsis"
               warning,             // "GALE" | "STORM" | "HURRICANE FORCE" | ... | "" (synopsis)
               hour,                // 0 = synopsis time, else the NN of "NN HOUR FORECAST"
               lows: [{lat, lon, mb, kind: "L"|"H", label}],
               blocks: [{ tier, area_text, wind: [lo, hi], seas: [lo, hi, unit] | null,
                          geom,       // polygon-clipping MultiPolygon, lon/lat (Pacific 0-360)
                          ok,         // every word of the area text was understood
                          unread }]   // the words that were not
            }] }

   Shape rules (the desk's, as in the issued-forecast reader marine_wind/hsf/issued.py):
     quadrant = bearing +-45 deg about the named direction, semicircle +-90
     WITHIN R NM <dirs> OF A LINE/FRONT ... = the line moved R nm toward each named side
     WITHIN R NM OF A LINE/FRONT ...         = R nm either side
     <dirs> OF A LINE FROM ...               = everything on that side of the line, in the area
     FROM aN TO bN BETWEEN x AND y           = a lat/lon box; open sides run to the area edge
     AREA BOUNDED BY p1 TO p2 ...            = that polygon
   Pieces joined by "..." or "," are added together; limits written back to back
   ("N OF 60N E OF GREENLAND") narrow each other; a plain AND narrows only when it adds a
   new kind of limit to a piece built of open limits ("FROM 30N TO 56N AND W OF A LINE").
   EXCEPT takes the next piece away. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./lib/polygon-clipping.min.js"));
  else root.HsfRead = factory(root.polygonClipping);
})(this, function (pc) {
  "use strict";

  var R_EARTH_NM = 3440.065;
  var DIRS = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315 };
  // forecast areas, (lon, lat); Pacific longitudes 0-360 east
  var OUTLINES = {
    pac: [[180, 30], [180, 50], [172, 53], [191.2, 65.7], [191.2, 67], [250, 67], [250, 30]],
    atl: [[-82, 31], [-82, 37], [-75, 37], [-75, 46], [-71, 46], [-71, 67], [-35, 67], [-35, 31]]
  };
  var BOUNDARY_TEXT = {
    pac: "S OF 67N AND N OF 30N E OF A LINE FROM THE BERING STRAIT TO 53N172E TO 50N180W TO 30N180W",
    atl: "N OF 31N TO 67N AND W OF 35W"
  };
  // Bering Sea north of the Aleutian chain and west of Alaska (Pacific 0-360)
  var BERING = [[165, 51], [180, 51.2], [187, 51.6], [192, 52.9], [195.5, 53.9], [198.5, 54.6], [201, 55.4],
    [203.5, 56.6], [203.5, 68], [165, 68]];
  var GULF_ST_LAWRENCE = [[-66.6, 50.4], [-64.5, 46.0], [-61.0, 45.5], [-60.2, 46.4], [-59.3, 47.6], [-57.2, 51.6],
    [-60.0, 52.3], [-66.6, 52.0]];
  // Greenland (Natural Earth 50 m, simplified to 0.15 deg)
  var GREENLAND = [[-29.95,83.56],[-25.8,83.26],[-31.99,83.09],[-32.03,82.98],[-25.12,83.16],[-24.47,82.88],[-21.52,82.6],[-23.12,82.32],[-29.89,82.05],[-25.15,82.0],[-24.29,81.7],[-22.94,82.03],[-21.13,81.93],[-21.5,81.44],[-23.07,80.93],[-23.12,80.78],[-19.63,81.64],[-17.46,81.4],[-15.45,81.84],[-11.43,81.46],[-14.45,80.99],[-14.23,80.87],[-14.5,80.76],[-16.76,80.57],[-15.93,80.4],[-16.49,80.25],[-19.43,80.26],[-20.15,80.01],[-20.07,79.77],[-19.28,79.68],[-19.41,79.35],[-18.99,79.18],[-21.13,78.66],[-20.96,78.56],[-21.73,77.71],[-20.86,77.91],[-19.49,77.72],[-19.3,77.59],[-20.68,77.62],[-19.3,77.22],[-18.44,77.26],[-18.34,76.92],[-22.61,76.68],[-21.49,76.27],[-19.86,76.12],[-19.96,76.0],[-19.4,75.49],[-19.53,75.18],[-20.48,75.31],[-21.65,75.02],[-22.23,75.12],[-21.7,74.96],[-20.93,75.05],[-20.8,74.81],[-21.04,74.65],[-19.98,74.98],[-19.27,74.34],[-21.13,74.11],[-21.95,74.24],[-21.76,74.48],[-21.98,74.57],[-22.33,74.29],[-22.13,73.99],[-20.37,73.85],[-20.64,73.46],[-22.35,73.27],[-24.16,73.76],[-24.68,73.6],[-25.52,73.85],[-24.79,73.51],[-26.06,73.25],[-27.27,73.44],[-26.54,73.25],[-27.56,73.14],[-27.35,73.07],[-24.13,73.41],[-22.04,72.92],[-22.29,72.12],[-24.07,72.5],[-24.63,73.04],[-26.66,72.72],[-24.81,72.9],[-24.7,72.51],[-25.2,72.39],[-24.57,72.42],[-21.96,71.74],[-22.48,71.38],[-21.75,71.48],[-21.52,70.53],[-22.38,70.46],[-22.44,70.86],[-22.69,70.44],[-23.33,70.45],[-24.78,71.29],[-25.89,71.57],[-27.09,71.63],[-25.84,71.48],[-25.67,71.27],[-26.72,70.95],[-28.4,70.99],[-27.98,70.84],[-29.07,70.44],[-26.51,70.4],[-27.63,70.03],[-27.38,69.99],[-25.62,70.35],[-22.21,70.11],[-23.87,69.74],[-23.74,69.59],[-24.3,69.59],[-26.34,68.7],[-30.72,68.25],[-30.61,68.12],[-30.98,68.06],[-32.33,68.44],[-32.16,67.99],[-33.16,67.63],[-34.63,66.43],[-35.19,66.25],[-35.87,66.44],[-35.63,66.14],[-37.75,65.59],[-38.0,65.71],[-37.29,66.32],[-38.16,66.39],[-37.75,66.26],[-38.14,65.9],[-38.52,66.01],[-38.2,65.71],[-40.17,65.56],[-39.58,65.34],[-40.25,65.05],[-41.09,65.04],[-40.18,64.48],[-40.78,64.22],[-41.58,64.3],[-40.62,64.13],[-40.55,63.73],[-41.39,63.06],[-42.17,63.21],[-41.63,62.97],[-41.91,62.74],[-42.94,62.72],[-42.15,62.57],[-42.32,62.15],[-42.11,61.86],[-42.59,61.72],[-42.32,61.68],[-43.04,60.52],[-43.92,60.6],[-43.21,60.39],[-43.12,60.06],[-43.96,60.03],[-43.66,59.86],[-43.91,59.82],[-44.41,59.92],[-44.22,60.27],[-44.61,60.02],[-45.38,60.2],[-44.74,60.66],[-45.38,60.44],[-46.05,60.62],[-45.87,61.22],[-46.87,60.82],[-48.18,60.77],[-47.77,61.0],[-48.39,61.0],[-49.29,61.59],[-49.38,61.89],[-48.83,62.08],[-49.62,62.0],[-49.55,62.23],[-50.32,62.47],[-50.3,62.72],[-49.79,63.04],[-50.39,62.82],[-51.54,63.76],[-51.55,64.01],[-50.26,64.21],[-51.68,64.16],[-51.4,64.46],[-50.49,64.69],[-50.01,64.45],[-50.12,64.7],[-50.96,65.2],[-50.78,64.75],[-51.26,64.76],[-51.83,64.23],[-52.06,64.35],[-52.26,65.15],[-52.54,65.33],[-51.09,65.78],[-52.35,65.46],[-53.2,65.59],[-53.11,65.98],[-53.36,66.07],[-51.23,66.88],[-53.61,66.15],[-53.42,66.65],[-52.39,66.88],[-53.69,66.99],[-53.8,67.42],[-52.51,67.76],[-50.61,67.53],[-51.17,67.69],[-50.97,67.81],[-52.34,67.84],[-53.74,67.55],[-53.15,68.21],[-51.6,68.05],[-51.17,68.39],[-53.38,68.3],[-52.6,68.71],[-51.62,68.53],[-50.95,68.68],[-50.81,68.82],[-51.25,68.74],[-51.08,69.13],[-50.3,69.17],[-51.08,69.21],[-50.29,70.01],[-52.25,70.06],[-54.5,70.66],[-53.09,70.77],[-51.52,70.44],[-50.66,70.42],[-51.32,70.59],[-51.26,70.85],[-51.77,71.01],[-51.02,71.0],[-51.38,71.12],[-53.01,71.18],[-53.12,71.31],[-52.89,71.46],[-51.77,71.67],[-53.44,71.58],[-53.14,71.81],[-53.81,72.29],[-53.65,72.36],[-53.93,72.32],[-53.46,71.89],[-54.02,71.66],[-53.96,71.46],[-55.59,71.55],[-55.32,72.11],[-54.84,72.38],[-55.58,72.18],[-55.3,72.35],[-55.6,72.45],[-54.92,72.57],[-54.74,72.87],[-55.67,73.01],[-55.29,73.33],[-56.1,73.56],[-55.84,73.76],[-56.23,74.13],[-57.23,74.13],[-56.26,74.53],[-58.57,75.35],[-58.25,75.51],[-58.52,75.69],[-61.19,76.16],[-63.29,76.35],[-67.08,76.19],[-66.67,75.98],[-66.83,75.97],[-68.32,76.09],[-69.48,76.4],[-68.11,76.65],[-69.89,76.83],[-69.69,76.99],[-70.61,76.82],[-71.15,77.07],[-68.14,77.38],[-66.39,77.28],[-66.27,77.52],[-66.82,77.69],[-69.35,77.47],[-70.56,77.72],[-70.11,77.84],[-71.27,77.81],[-72.82,78.19],[-72.47,78.48],[-71.52,78.64],[-65.83,79.17],[-64.79,80.0],[-64.18,80.1],[-66.84,80.08],[-67.19,80.28],[-64.52,81.0],[-63.03,80.89],[-63.24,81.08],[-62.99,81.21],[-61.44,81.13],[-61.1,81.4],[-61.2,81.75],[-60.43,81.92],[-56.62,81.36],[-59.27,81.98],[-54.55,82.35],[-53.67,82.16],[-53.56,81.65],[-53.04,81.87],[-53.02,82.32],[-50.89,81.9],[-49.54,81.92],[-50.99,82.46],[-50.04,82.47],[-44.73,81.78],[-44.53,81.85],[-44.55,82.26],[-44.24,82.37],[-45.56,82.75],[-41.37,82.75],[-46.48,82.95],[-43.19,83.26],[-41.3,83.1],[-40.36,83.33],[-38.16,83.0],[-37.93,83.16],[-38.75,83.37],[-29.95,83.56]];

  // outer coasts the desk names (0.5 deg sketch, for "WITHIN 60 NM OF THE CALIFORNIA COAST" and the like)
  var COASTS = {
    pac: [[244.2, 30], [242.9, 32.5], [241.5, 34], [239.5, 34.45], [239, 35.5], [238.1, 36.6], [237.5, 37.8], [237, 38.3], [236.3, 39], [235.6, 40.4], [235.8, 41.7], [235.5, 42.8], [235.9, 44], [236, 46.2], [235.6, 47.5], [235.3, 48.4], [235, 48.6], [234.2, 49], [233.4, 49.6], [232.5, 50.1], [231.6, 50.8], [232, 51.5], [231, 52.5], [229.7, 53.5], [229.4, 54.7], [226.5, 55.5], [225.2, 56.5], [224, 57.5], [223.2, 58.2], [221.5, 59], [219, 59.8], [216.5, 60.1], [214, 60.3], [210.5, 59.5], [208.3, 59.1], [206, 57.5], [201.5, 56], [198, 55], [195.5, 54.5]],
    atl: [[-65.7, 43.4], [-63.5, 44.5], [-61, 45.3], [-59.8, 46], [-53.1, 46.6], [-52.7, 47.6], [-53.6, 49], [-55.5, 50], [-55.5, 51.6], [-55.7, 52.5], [-55.8, 53.5], [-57.5, 54.5], [-59.5, 55.5], [-61.5, 56.5], [-61.8, 57.5], [-62.8, 58.5], [-64, 59.5], [-64.6, 60.3]]
  };
  var COAST_NAMES = {
    pac: { CALIFORNIA: [32.5, 42], OREGON: [42, 46.25], WASHINGTON: [46.25, 48.5], "VANCOUVER ISLAND": [48.3, 50.9],
      "BRITISH COLUMBIA": [48.3, 54.8], ALASKA: [54.7, 61], "ALASKA PENINSULA": [54, 59.2], "": [0, 90] },
    atl: { "NOVA SCOTIA": [43, 46.1], NEWFOUNDLAND: [46.5, 51.7], LABRADOR: [51.8, 61], "": [0, 90] }
  };
  var HECATE_STRAIT = [[228.5, 52.0], [231.0, 52.0], [230.6, 54.6], [228.3, 54.6]];

  var LL = "\\d{1,2}(?:\\.\\d+)?[NS]\\d{1,3}(?:\\.\\d+)?[EW]";
  var D = "(?:NE|NW|SE|SW|N|E|S|W)";
  var DLIST = D + "(?:(?:\\s*(?:,|\\.\\.\\.|AND|TO)\\s*|\\s+)" + D + ")*";
  var ORD = "(?:ORIGINAL |COMBINED )?(?:MAIN |FIRST |FIST |SECOND |SECONDARY |THIRD |NEW |SECOND NEW |NEW SECOND |NEWER |MEAN |WESTERN |EASTERN |NORTHERN |SOUTHERN |ORIGINAL )?";
  var CREF = "(?:THE )?" + ORD + "(?:LOW|CENTER|CYCLONE)(?: CENTER)?";
  var ENDNAME = "(?:THE )?(?:(?:" + D + ") )?(?:COAST OF )?(?:LABRADOR|ALASKA|GREENLAND|NEWFOUNDLAND|BRITISH COLUMBIA|CANADA|THE COAST|COAST)(?: COAST)?";
  var PTOK = "(?:" + LL + "|" + CREF + "|" + ENDNAME + ")";
  var PLIST = PTOK + "(?:(?: TO |\\s*\\.\\.\\.\\s*|\\s*-\\s*)" + PTOK + ")+";
  var LINEKW = "(?:A |THE |ENTIRE |THE ENTIRE )?(?:LINE|(?:COLD |WARM |OCCLUDED |STATIONARY )?FRONT|TROUGH|RIDGE|ENTIRE FRONT)(?: (?:THAT |TO |WILL )?(?:EXTENDING|EXTENDS|EXTENDED|EXTEND))?";

  // ---------------------------------------------------------------- geometry
  function rad(d) { return d * Math.PI / 180; }
  function deg(r) { return r * 180 / Math.PI; }
  function dest(lat, lon, brg, nm) {
    var p1 = rad(lat), l1 = rad(lon), b = rad(brg), d = nm / R_EARTH_NM;
    var p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
    var l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
    var lo = deg(l2);
    while (lo - lon > 180) lo -= 360;
    while (lo - lon < -180) lo += 360;
    return [deg(p2), lo];
  }
  function ring(pts) {   // [[lon, lat], ...] closed
    var r = pts.slice();
    if (r.length && (r[0][0] !== r[r.length - 1][0] || r[0][1] !== r[r.length - 1][1])) r.push(r[0].slice());
    return r;
  }
  function poly(pts) { return [[ring(pts)]]; }
  function safe(fn, a, b) {
    try { return fn(a, b); } catch (e) { return null; }
  }
  function union(list) {
    list = list.filter(function (g) { return g && g.length; });
    if (!list.length) return [];
    if (list.length === 1) return list[0];
    try { return pc.union.apply(null, list); } catch (e) {
      var out = list[0];
      for (var i = 1; i < list.length; i++) out = safe(pc.union, out, list[i]) || out;
      return out;
    }
  }
  function inter(a, b) { return (a && b) ? (safe(pc.intersection, a, b) || []) : []; }
  function diff(a, b) { return (a && b && b.length) ? (safe(pc.difference, a, b) || a) : a; }
  function bbox(g) {
    var b = [1e9, 1e9, -1e9, -1e9];
    g.forEach(function (p) { p.forEach(function (r) { r.forEach(function (q) {
      b[0] = Math.min(b[0], q[0]); b[1] = Math.min(b[1], q[1]); b[2] = Math.max(b[2], q[0]); b[3] = Math.max(b[3], q[1]);
    }); }); });
    return b;
  }
  function boxg(w, s, e, n) { return poly([[w, s], [e, s], [e, n], [w, n]]); }
  function sector(lat, lon, nm, a0, a1, inner) {
    var pts = [], i, n = 36, p;
    for (i = 0; i <= n; i++) { p = dest(lat, lon, a0 + (a1 - a0) * i / n, nm); pts.push([p[1], p[0]]); }
    if (inner > 0) {
      for (i = n; i >= 0; i--) { p = dest(lat, lon, a0 + (a1 - a0) * i / n, inner); pts.push([p[1], p[0]]); }
    } else if (a1 - a0 < 360) pts.unshift([lon, lat]);
    return poly(pts);
  }
  // area in square degrees on the sinusoidal (equal-area) projection: enough to compare shapes
  function areaOf(g) {
    var t = 0;
    (g || []).forEach(function (p) { p.forEach(function (r, k) {
      var s = 0;
      for (var i = 0; i < r.length - 1; i++) {
        var x0 = r[i][0] * Math.cos(rad(r[i][1])), x1 = r[i + 1][0] * Math.cos(rad(r[i + 1][1]));
        s += x0 * r[i + 1][1] - x1 * r[i][1];
      }
      t += (k === 0 ? 1 : -1) * Math.abs(s) / 2;
    }); });
    return t;
  }

  // ---------------------------------------------------------------- basin context
  function Basin(name) {
    this.name = name;
    this.area = poly(OUTLINES[name]);
    this.b = bbox(this.area);
    this.greenland = name === "atl" ? poly(GREENLAND) : null;
  }
  Basin.prototype.lon = function (v, h) {
    v = +v;
    if (this.name === "pac") return h === "W" ? 360 - v : v;
    return h === "W" ? -v : (v > 180 ? v - 360 : v);
  };
  Basin.prototype.pt = function (s) {
    var m = /(\d+(?:\.\d+)?)([NS])\s?(\d+(?:\.\d+)?)([EW])/.exec(s);
    if (!m) return null;
    return [(m[2] === "N" ? 1 : -1) * +m[1], this.lon(m[3], m[4])];
  };
  Basin.prototype.clip = function (g) { return inter(g, this.area); };

  // ---------------------------------------------------------------- lows
  var LOW_RE = new RegExp("(" + LL + ")\\s+(\\d{3,4})(?:\\s*MB)?\\b", "g");
  function lowsOf(p, B) {
    var out = [], m;
    LOW_RE.lastIndex = 0;
    while ((m = LOW_RE.exec(p))) {
      var mb = +m[2];
      if (mb < 900 || mb > 1070) continue;
      var pre = p.slice(Math.max(0, m.index - 60), m.index);
      var kinds = pre.match(/\b(LOW|HIGH|CENTER|CYCLONE|STORM|HURRICANE|DEPRESSION|TROPICAL|REMNANTS?|RIDGE)\b/g) || [];
      var kind = kinds.length && kinds[kinds.length - 1] === "HIGH" ? "H" : "L";
      if (!kinds.length && /\bHIGH\b/.test(pre)) kind = "H";
      var lab = (pre.match(/\b(FIRST|FIST|MAIN|SECOND|SECONDARY|THIRD|NEW|MEAN|ORIGINAL|COMBINED)\b(?!.*\b(?:FIRST|MAIN|SECOND|SECONDARY|THIRD|MEAN|ORIGINAL)\b)/) || [])[1] || "";
      var c = B.pt(m[1]);
      out.push({ lat: c[0], lon: c[1], mb: mb, kind: kind, label: lab === "FIST" ? "FIRST" : lab, raw: m[1] });
    }
    // tropical cyclones are often placed without a pressure: "TROPICAL STORM FAY NEAR 31.3N34.7W."
    if (!out.length) {
      var tm = new RegExp("(?:TROPICAL|HURRICANE|CYCLONE|REMNANTS?|DEPRESSION)[^.]*? NEAR (" + LL + ")").exec(p);
      if (tm) { var tc = B.pt(tm[1]); out.push({ lat: tc[0], lon: tc[1], mb: null, kind: "L", label: "", raw: tm[1] }); }
    }
    return out;
  }
  function centre(ref, lows, B) {
    ref = ref || "";
    var m = new RegExp(LL).exec(ref);
    if (m) return B.pt(m[0]);
    var L = lows.filter(function (l) { return l.kind === "L"; });
    if (!L.length) return null;
    function find(labels, idx) {
      for (var i = 0; i < L.length; i++) if (labels.indexOf(L[i].label) > -1) return L[i];
      return L[idx] || null;
    }
    var l = /THIRD/.test(ref) ? find(["THIRD"], 2)
      : /SECOND|SECONDARY|NEWER|NEW (?:LOW|CENTER)/.test(ref) ? find(["SECOND", "SECONDARY", "NEW"], 1)
      : /FIRST|FIST|MAIN|ORIGINAL|MEAN/.test(ref) ? find(["FIRST", "MAIN", "ORIGINAL", "MEAN"], 0)
      : L[0];
    l = l || L[0];
    return [l.lat, l.lon];
  }

  // ---------------------------------------------------------------- line helpers
  function linePts(s, ctx) {
    var out = [], B = ctx.B;
    s.split(/\s+TO\s+|\s*\.\.\.\s*|\s+-\s+/).forEach(function (tok) {
      tok = tok.trim();
      if (!tok) return;
      var m = new RegExp(LL).exec(tok);
      if (m) { out.push(B.pt(m[0])); return; }
      if (new RegExp("^" + CREF + "$").test(tok)) {
        var c = centre(tok, ctx.lows, B);
        if (c) out.push(c);
      }
      // a coast name at an end: the line is carried on to the coast (see extend)
    });
    return out;
  }
  function bearing(a, b) {   // [lat, lon] -> deg
    var p1 = rad(a[0]), p2 = rad(b[0]), dl = rad(b[1] - a[1]);
    return (deg(Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl))) + 360) % 360;
  }
  function meanBrg(dirs) {
    var x = 0, y = 0;
    dirs.forEach(function (d) { x += Math.sin(rad(DIRS[d])); y += Math.cos(rad(DIRS[d])); });
    return (deg(Math.atan2(x, y)) + 360) % 360;
  }
  // <dirs> OF A LINE: the ground the line sweeps when moved 40 deg toward that side on the chart
  // (the desk's lines run to a coast or the area edge, which close the area off)
  function sidePoly(pts, dirs) {
    if (pts.length < 2) return null;
    var b = rad(meanBrg(dirs)), dx = Math.sin(b), dy = Math.cos(b);
    var line = pts.map(function (p) { return [p[1], p[0]]; });
    var far = line.slice().reverse().map(function (p) { return [p[0] + dx * 40, p[1] + dy * 40]; });
    try { return pc.union(poly(line.concat(far))); } catch (e) { return null; }
  }
  function bufferLine(pts, nm, dirs) {
    if (pts.length < 2) return null;
    var segs = [];
    for (var i = 0; i < pts.length - 1; i++) {
      var a = pts[i], b = pts[i + 1], hull = [];
      [a, b].forEach(function (p) {
        hull.push([p[1], p[0]]);
        if (dirs.length) dirs.forEach(function (d) { [-20, 0, 20].forEach(function (o) { var q = dest(p[0], p[1], DIRS[d] + o, nm); hull.push([q[1], q[0]]); }); });
        else for (var t = 0; t < 360; t += 15) { var q = dest(p[0], p[1], t, nm); hull.push([q[1], q[0]]); }
      });
      segs.push(poly(convexHull(hull)));
    }
    return union(segs);
  }
  function convexHull(p) {
    p = p.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    if (p.length < 3) return p;
    function cr(o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }
    var lo = [], up = [], i;
    for (i = 0; i < p.length; i++) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p[i]) <= 0) lo.pop(); lo.push(p[i]); }
    for (i = p.length - 1; i >= 0; i--) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p[i]) <= 0) up.pop(); up.push(p[i]); }
    up.pop(); lo.pop();
    return lo.concat(up);
  }
  // R nm out from a coast: the coast's segments buffered (land is drawn over the inland half)
  function coastBuffer(ringPts, nm, B) {
    var segs = [], bb = B.b;
    for (var i = 0; i < ringPts.length - 1; i++) {
      var a = ringPts[i], b = ringPts[i + 1];
      if (Math.max(a[1], b[1]) < bb[1] - 6 || Math.min(a[1], b[1]) > bb[3] + 4) continue;
      var hull = [];
      [a, b].forEach(function (q) { for (var t = 0; t < 360; t += 30) { var d = dest(q[1], q[0], t, nm); hull.push([d[1], d[0]]); } });
      segs.push(poly(convexHull(hull)));
    }
    return union(segs);
  }

  // ---------------------------------------------------------------- area constructs
  // each: [name, regex source, kind] kind: lat | lon | shape | line | region
  var C = [];
  function add(name, src, kind) { C.push({ name: name, re: new RegExp(src, "y"), kind: kind }); }
  add("circle", "WITHIN (\\d+) NM (?:OF|FROM) (?:THE |BOTH )?(?:(" + LL + ")|" + ORD + "(?:LOW|CENTER|CYCLONE|CENTERS)(?: CENTER)?(?: (" + LL + "))?)(?! TO)", "shape");
  add("dirlow", "WITHIN (\\d+) NM (" + DLIST + ") OF (" + CREF + "|" + LL + ")(?! TO)", "shape");
  add("coast", "WITHIN (\\d+) NM (?:(" + D + ") )?OF (?:THE )?(?:(" + D + ") )?(?:COAST OF )?GREENLAND(?: COAST)?", "shape");
  add("coast2", "WITHIN (\\d+) NM (?:(" + D + ") )?OF (?:THE )?(?:(" + D + ") )?(?:(?:COAST|COASTS) OF )?(?:(CALIFORNIA|OREGON|WASHINGTON|VANCOUVER ISLAND|BRITISH COLUMBIA|ALASKA PENINSULA|ALASKA|NOVA SCOTIA|NEWFOUNDLAND|LABRADOR)(?: (?:COAST|COASTS|COASTLINE))?|(COAST|COASTLINE))\\b", "shape");
  add("hecate", "(?:(?:IN|WITHIN|OVER|INCLUDING) )?(?:THE )?HECATE STRAIT", "region");
  add("linebuf_side", "(?:WITHIN )?(\\d+) NM (" + DLIST + ") OF (?:" + LINEKW + ")?\\s*(?:(?:FROM )?(" + PLIST + "))?", "shape");
  add("linebuf", "WITHIN (\\d+) NM (?:ON )?(?:EITHER SIDE )?OF (?:" + LINEKW + ")\\s*(?:(?:FROM )?(" + PLIST + "))?", "shape");
  add("linebuf2", "WITHIN (\\d+) NM (?:ON )?(?:EITHER SIDE )?OF (?:A |THE )?(?:LINE )?(?:FROM )?(" + PLIST + ")", "shape");
  add("bounded", "(?:WITHIN )?(?:AN )?(?:AREA )?BOUNDED BY (?:A LINE )?(?:FROM )?(" + PLIST + ")", "shape");
  add("between_lat_line", "BETWEEN (\\d+(?:\\.\\d+)?)N AND (?:" + LINEKW + " )?(?:FROM )?(" + PLIST + ")", "line");
  add("between_lon_line", "BETWEEN (\\d+(?:\\.\\d+)?)([EW]) AND (?:" + LINEKW + " )?(?:FROM )?(" + PLIST + ")", "line");
  add("side", "(" + DLIST + ") OF (?:" + LINEKW + ")? ?(?:FROM )?(" + PLIST + ")", "line");
  add("side_named", "(" + DLIST + ") OF (?:" + LINEKW + ")(?=$|[ .,]|$)", "line");
  add("box", "FROM (\\d+(?:\\.\\d+)?)N TO (\\d+(?:\\.\\d+)?)N BETWEEN (\\d+(?:\\.\\d+)?)([EW]) AND (\\d+(?:\\.\\d+)?)([EW])", "shape");
  add("latband", "(?:FROM|BETWEEN) (\\d+(?:\\.\\d+)?)N (?:TO|AND) (\\d+(?:\\.\\d+)?)N", "lat");
  add("lonband", "BETWEEN (\\d+(?:\\.\\d+)?)([EW]) (?:AND|TO) (\\d+(?:\\.\\d+)?)([EW])", "lon");
  add("lonband2", "FROM (\\d+(?:\\.\\d+)?)([EW]) TO (\\d+(?:\\.\\d+)?)([EW])", "lon");
  add("half_lat", "([NS]) OF (\\d+(?:\\.\\d+)?)N\\b", "lat");
  add("half_lon", "([EW]) OF (\\d+(?:\\.\\d+)?)([EW])\\b", "lon");
  add("greenland", "(" + DLIST + ") OF (?:THE )?(?:(?:E|W|SE|SW) COAST OF )?GREENLAND(?: COAST)?", "region");
  add("alaska", "(" + DLIST + ") OF (?:THE )?(?:BRITISH COLUMBIA AND )?ALASKA(?:N)?(?: COAST)?", "region");
  add("between_alaska", "BETWEEN (?:THE )?(?:(?:W|E|S|SW|SE) )?(?:COAST OF )?ALASKA(?:N)?(?: COAST)? AND (\\d+(?:\\.\\d+)?)([EW])", "lon");
  add("between_greenland", "BETWEEN (?:THE )?(?:(W|E|SE|SW) )?(?:COAST OF )?GREENLAND(?: COAST)? AND (\\d+(?:\\.\\d+)?)([EW])", "lon");
  add("between_greenland2", "BETWEEN (\\d+(?:\\.\\d+)?)([EW]) AND (?:THE )?(?:(?:W|E|SE|SW) )?(?:COAST OF )?GREENLAND(?: COAST)?", "lon");
  add("between_line_lat", "BETWEEN (?:" + LINEKW + " )?(?:FROM )?(" + PLIST + ") AND (\\d+(?:\\.\\d+)?)N", "line");
  add("bering_in", "(?:(?:IN|WITHIN|OVER|INCLUDING) )?THE BERING(?: SEA)?|N OF THE ALEUTIANS?(?: ISLANDS)?", "region");
  add("bering_out", "(?:EXCLUDING|OUTSIDE|EXCEPT|NOT INCLUDING) THE BERING SEA|S OF THE ALEUTIANS?(?: ISLANDS)?", "region");
  add("gsl", "(?:(?:IN|WITHIN|INCLUDING|OVER) )?(?:THE )?(?:[NSEW]{1,2} )?GULF OF (?:SAINT|ST\\.?) LAWRENCE", "region");

  function radial(s, pos, ctx) {
    // WITHIN/BETWEEN ... QUADRANT(S)/SEMICIRCLE(S) [OF <centre>], any mix of radii and directions
    var T = {
      within: /WITHIN\s+/y, between: /(?:BETWEEN\s+)?(\d+)\s*NM\s+AND\s+(\d+)\s*NM\s+/y, r: /(\d+)\s*NM\s+/y,
      dir: new RegExp("(" + D + ")(?![A-Z])\\s*", "y"), sep: /(?:\.\.\.\s*AND|\.\.\.|,|AND|TO)\s*/y,
      type: /(QUADRANTS?|QUARANTS?|QUADSRANTS?|QUADRANT|SEMI-?CIRCLES?)\b\s*/y,
      of: new RegExp("OF (" + CREF + "|" + LL + "|(?:EACH|BOTH) (?:CENTERS?|LOWS?))\\s*", "y")
    };
    var p = pos, entries = [], pend = [], rIn = 0, rOut = null, end = -1, ref = null, any = false;
    var started = false;
    for (var guard = 0; guard < 80; guard++) {
      var m, hit = false;
      for (var k in T) {
        T[k].lastIndex = p;
        if (k === "of" && !entries.length) continue;
        if ((m = T[k].exec(s))) {
          if (k === "within") { if (started && !pend.length && end < 0 && !entries.length) {} started = true; }
          else if (k === "between") { rIn = +m[1]; rOut = +m[2]; started = true; }
          else if (k === "r") { rIn = 0; rOut = +m[1]; started = true; }
          else if (k === "dir") { if (rOut === null) { hit = false; break; } pend.push({ d: m[1], rIn: rIn, rOut: rOut }); }
          else if (k === "type") {
            if (!pend.length) { hit = false; break; }
            var semi = /SEMI/.test(m[1]);
            pend.forEach(function (e) { e.half = semi ? 90 : 45; entries.push(e); });
            pend = []; any = true;
          } else if (k === "of") { ref = m[1]; end = T[k].lastIndex; hit = true; p = end; break; }
          else if (k === "sep") { /* keep going */ }
          hit = true; p = T[k].lastIndex;
          if (k === "type") end = p;
          break;
        }
      }
      if (!hit || ref !== null) break;
    }
    if (!any || end < 0) return null;
    var cs = /EACH|BOTH/.test(ref || "") ? ctx.lows.filter(function (l) { return l.kind === "L"; }).map(function (l) { return [l.lat, l.lon]; })
      : [centre(ref, ctx.lows, ctx.B)].filter(Boolean);
    if (!cs.length) return { end: end, geom: null, why: "no low to measure from" };
    var shapes = [];
    cs.forEach(function (c) { entries.forEach(function (e) { shapes.push(sector(c[0], c[1], e.rOut, DIRS[e.d] - e.half, DIRS[e.d] + e.half, e.rIn)); }); });
    return { end: end, geom: union(shapes) };
  }

  function construct(c, m, ctx) {
    var B = ctx.B, bb = B.b, g, pts, la, lo;
    var W = bb[0] - 1, S = bb[1] - 1, E = bb[2] + 1, N = bb[3] + 1;
    switch (c.name) {
      case "circle": {
        var cc = m[2] ? B.pt(m[2]) : (m[3] ? B.pt(m[3]) : centre(m[0], ctx.lows, B));
        return cc ? sector(cc[0], cc[1], +m[1], 0, 360, 0) : null;
      }
      case "dirlow": {
        var c2 = centre(m[3], ctx.lows, B);
        if (!c2) return null;
        return union(dirsOf(m[2]).map(function (d) { return sector(c2[0], c2[1], +m[1], DIRS[d] - 45, DIRS[d] + 45, 0); }));
      }
      case "coast": {
        if (!B.greenland) return null;
        g = coastBuffer(GREENLAND, +m[1], B);
        var side = m[2] || m[3];
        if (side) g = inter(g, greenSide(dirsOf(side), B));
        return g;
      }
      case "coast2": {
        var rng = COAST_NAMES[B.name][m[4] || ""];
        if (!rng) return null;
        var cp = COASTS[B.name].filter(function (q) { return q[1] >= rng[0] - 0.6 && q[1] <= rng[1] + 0.6; });
        return cp.length >= 2 ? coastBuffer(cp, +m[1], B) : null;
      }
      case "hecate": return B.name === "pac" ? poly(HECATE_STRAIT) : null;
      case "linebuf_side":
        pts = m[3] ? linePts(m[3], ctx) : ctx.line;
        return pts && pts.length >= 2 ? bufferLine(pts, +m[1], dirsOf(m[2])) : null;
      case "linebuf": case "linebuf2":
        pts = m[2] ? linePts(m[2], ctx) : ctx.line;
        return pts && pts.length >= 2 ? bufferLine(pts, +m[1], []) : null;
      case "bounded":
        pts = linePts(m[1], ctx);
        if (pts.length < 3) return null;
        try { return pc.union(poly(pts.map(function (p) { return [p[1], p[0]]; }))); } catch (e) { return null; }
      case "between_lat_line": {
        pts = linePts(m[2], ctx); la = +m[1];
        if (pts.length < 2) return null;
        var mean = pts.reduce(function (s, p) { return s + p[0]; }, 0) / pts.length;
        var toward = la > mean ? "N" : "S";
        return inter(sidePoly(pts, [toward]), toward === "N" ? boxg(W, S, E, la) : boxg(W, la, E, N));
      }
      case "between_lon_line": {
        pts = linePts(m[3], ctx); lo = B.lon(m[1], m[2]);
        if (pts.length < 2) return null;
        var ml = pts.reduce(function (s, p) { return s + p[1]; }, 0) / pts.length;
        var tw = lo > ml ? "E" : "W";
        return inter(sidePoly(pts, [tw]), tw === "E" ? boxg(W, S, lo, N) : boxg(lo, S, E, N));
      }
      case "side":
        pts = linePts(m[2], ctx);
        return pts.length >= 2 ? sidePoly(pts, dirsOf(m[1])) : null;
      case "side_named":
        return ctx.line && ctx.line.length >= 2 ? sidePoly(ctx.line, dirsOf(m[1])) : null;
      case "box": {
        var a = [+m[1], +m[2]].sort(function (x, y) { return x - y; });
        var x = [B.lon(m[3], m[4]), B.lon(m[5], m[6])].sort(function (p, q) { return p - q; });
        return boxg(x[0], a[0], x[1], a[1]);
      }
      case "latband": {
        var a2 = [+m[1], +m[2]].sort(function (x, y) { return x - y; });
        return boxg(W, a2[0], E, a2[1]);
      }
      case "lonband": case "lonband2": {
        var x2 = [B.lon(m[1], m[2]), B.lon(m[3], m[4])].sort(function (p, q) { return p - q; });
        return boxg(x2[0], S, x2[1], N);
      }
      case "half_lat":
        la = +m[2];
        return m[1] === "N" ? boxg(W, la, E, N) : boxg(W, S, E, la);
      case "half_lon":
        lo = B.lon(m[2], m[3]);
        return m[1] === "E" ? boxg(lo, S, E, N) : boxg(W, S, lo, N);
      case "greenland":
        return B.greenland ? greenSide(dirsOf(m[1]), B) : null;
      case "alaska":
        // W OF ALASKA: the Bering side; S OF ALASKA: the Gulf of Alaska side
        if (B.name !== "pac") return null;
        return union(dirsOf(m[1]).map(function (d) {
          return /W/.test(d) ? poly(BERING) : /S/.test(d) ? diff(boxg(W, S, E, N), poly(BERING)) : boxg(W, S, E, N);
        }));
      case "between_alaska":
        lo = B.lon(m[1], m[2]);
        return lo < 200 ? inter(poly(BERING), boxg(lo, S, E, N)) : boxg(W, S, lo, N);
      case "between_greenland": {
        if (!B.greenland) return null;
        lo = B.lon(m[2], m[3]);
        return lo < -43.5 ? boxg(lo, 58.5, -43.5, N) : boxg(-43.5, 58.5, lo, N);
      }
      case "between_greenland2": {
        if (!B.greenland) return null;
        lo = B.lon(m[1], m[2]);
        return lo < -43.5 ? boxg(lo, 58.5, -43.5, N) : boxg(-43.5, 58.5, lo, N);
      }
      case "between_line_lat": {
        pts = linePts(m[1], ctx); la = +m[2];
        if (pts.length < 2) return null;
        var mean2 = pts.reduce(function (s, p) { return s + p[0]; }, 0) / pts.length;
        var tw2 = la > mean2 ? "N" : "S";
        return inter(sidePoly(pts, [tw2]), tw2 === "N" ? boxg(W, S, E, la) : boxg(W, la, E, N));
      }
      case "bering_in": return B.name === "pac" ? poly(BERING) : null;
      case "bering_out": return B.name === "pac" ? diff(boxg(W, S, E, N), poly(BERING)) : null;
      case "gsl": return B.name === "atl" ? poly(GULF_ST_LAWRENCE) : null;
    }
    return null;
  }
  function dirsOf(s) { return s.match(new RegExp(D + "(?![A-Z])", "g")) || []; }
  // E OF GREENLAND / W OF GREENLAND: split at the island's spine (about 43W south of 67N)
  function greenSide(dirs, B) {
    var bb = B.b, out = [];
    dirs.forEach(function (d) {
      if (/E/.test(d)) out.push(boxg(-43.5, 58.5, bb[2] + 1, bb[3] + 1));
      else if (/W/.test(d)) out.push(boxg(bb[0] - 1, 58.5, -43.5, bb[3] + 1));
      else out.push(boxg(bb[0] - 1, bb[1] - 1, bb[2] + 1, bb[3] + 1));
    });
    return union(out);
  }

  var NOISE = [
    /^\s*(?:\.\.\.|\.|,)?\s*/,
    new RegExp("(?:\\.\\.\\.)?\\s*EXCEPT (?:WHERE|AS) (?:OTHERWISE )?(?:DESCRIBED|NOTED|STATED)(?: ABOVE| BELOW| AND| IN (?:THE )?(?:WARNINGS?|SYNOPSIS)(?: SECTION)?| IN (?:THE )?(?:GALE|STORM|HURRICANE FORCE)(?: WIND)? WARNING| IN PART II| (?:WITH|BY) (?:THE )?(?:(?:COMPLEX |NEW )?LOW(?: " + LL + ")?|(?:POST-)?TROPICAL (?:STORM|CYCLONE|DEPRESSION) [A-Z-]+|HURRICANE [A-Z-]+|(?:GALE|STORM|HURRICANE FORCE)(?: WIND)? WARNING|" + LL + "))*\\s*(?:\\.\\.\\.)?", "g"),
    new RegExp("^(?:[A-Z ]*?)(?:LOW|HIGH|CENTER) " + LL + " \\d{3,4}(?: MB)?(?: (?:MOVING|DRIFTING) [A-Z]+(?: \\d+ KT)?| (?:NEARLY )?STATIONARY)?\\s+(?=WITHIN|FROM|BETWEEN|[NSEW]{1,2} OF)"),
    new RegExp("\\bTO (?:THE )?(?:(?:NE|NW|SE|SW|N|E|S|W) )?(?:COAST OF )?(?:GREENLAND|ALASKA|LABRADOR)(?: COAST)?\\b(?! TO)", "g"),
    /(?:WITHIN )?AN AREA (?=[NSEW]+ OF|OF)/g,
    /\bINCLUDING (?:THE )?(?:SHELIKOF STRAIT|COOK INLET|GULF OF ALASKA)\b/g,
    /\b(?:IN|OVER) THE GULF OF ALASKA\b/g,
    /\s+(?:AREA\s+(?:OF\s+)?)?(?:MIXED\s+)?(?:NE|NW|SE|SW|N|E|S|W)(?:\s+(?:TO|AND)\s+(?:NE|NW|SE|SW|N|E|S|W))?(?:\s+(?:WINDS?|SWELL))?\s*$/,
    /\s*\bAREA(?:\s+OF)?\s*$/,
    /\bAREA\s+(?:OF\s+)?(?:MIXED\s+)?(?:NE|NW|SE|SW|N|E|S|W)(?:\s+(?:TO|AND)\s+(?:NE|NW|SE|SW|N|E|S|W))?(?:\s+(?:WINDS?|SWELL))?\b(?! OF\b)/g
  ];
  var SEP_RE = /^(?:\s|\.\.\.|\.|,|;|AND\b|ALSO\b|ELSEWHERE\b|AS WELL AS\b|PLUS\b|ADDITIONALLY\b|OTHERWISE\b|INCLUDING\b(?! THE BERING| THE (?:[NSEW]{1,2} )?GULF OF)|EXCEPT(?: FOR)?\b(?! THE BERING))*/;
  var FILLER_RE = /^(?:THE|IN|OVER|AREA|WATERS|FORECAST|WITHIN(?= AN AREA| THE)|AN|NEAR(?=\s*$))\b\s*/;

  // slips the map reads the way they were meant (the checks still list each one)
  var SLIPS = [
    [/\b(?:SEMI-?C[A-Z]*|SEMCIRCLES?|SEMI-?CIRLCES?)\b/g, function (w) { return /S$/.test(w) && !/SEMICIRCLE$/.test(w) ? "SEMICIRCLES" : "SEMICIRCLE"; }, /^SEMICIRCLES?$/],
    [/\b(?:QUA[A-Z]*NT|QUA[A-Z]*NTS|QUDRANTS?|QAUDRANTS?)\b/g, function (w) { return /S$/.test(w) ? "QUADRANTS" : "QUADRANT"; }, /^QUADRANTS?$/],
    [new RegExp("\\b((?:LINE|FRONT|TROUGH)(?: FROM)? " + LL + ") AND (" + LL + ")", "g"), "$1 TO $2"],
    [/\bFROM (\d+(?:\.\d+)?[EW]) AND (\d+(?:\.\d+)?[EW])\b/g, "BETWEEN $1 AND $2"],
    [/\bAMD\b/g, "AND"],
    [/\b(\d+) MM\b/g, "$1 NM"],
    [/\bNM NM\b/g, "NM"],
    [/\b(\d+)O\b/g, "$10"],
    [/\b(\d{2,4}) N (?=(?:NE|NW|SE|SW|N|E|S|W)\b)/g, "$1 NM "],
    [/\b(\d{2,4}) (?=(?:NE|NW|SE|SW|N|E|S|W) (?:QUADRANTS?|SEMICIRCLES?)\b)/g, "$1 NM "],
    [/\b(FROM|TO) (\d{1,2})M\b/g, "$1 $2N"]
  ];
  function fixSlips(s, out) {
    SLIPS.forEach(function (f) {
      s = s.replace(f[0], function () {
        var args = arguments, m = args[0];
        if (f[2] && f[2].test(m)) return m;
        var r = typeof f[1] === "function" ? f[1](m) : f[1].replace(/\$(\d)/g, function (x, k) { return args[+k] || ""; });
        if (r !== m) out.push({ from: m, to: r });
        return r;
      });
    });
    return s;
  }

  function areaGeom(text, ctx) {
    var guessed = [];
    var s = fixSlips(text.replace(/\s+/g, " ").trim(), guessed), i;
    for (i = 0; i < NOISE.length; i++) s = s.replace(NOISE[i], function (x) { return i === 0 ? "" : " "; });
    s = s.replace(/\s+/g, " ").trim().replace(/[.\s]+$/, "");
    var groups = [], cur = null, pos = 0, unread = [], prevKind = null;
    while (pos < s.length) {
      SEP_RE.lastIndex = 0;
      var gap = SEP_RE.exec(s.slice(pos))[0];
      pos += gap.length;
      if (pos >= s.length) break;
      var except = /EXCEPT/.test(gap) || (/\b(?:EXCLUDING|OUTSIDE)\b/.test(s.slice(pos, pos + 10)) && false);
      var hit = null, rr = radial(s, pos, ctx);
      if (rr) hit = { kind: "shape", end: rr.end, geom: rr.geom, name: "radial" };
      if (!hit) {
        for (var k = 0; k < C.length; k++) {
          C[k].re.lastIndex = pos;
          var m = C[k].re.exec(s);
          if (m && m[0].trim()) { hit = { kind: C[k].kind, end: C[k].re.lastIndex, geom: construct(C[k], m, ctx), name: C[k].name }; break; }
        }
      }
      if (!hit) {
        var fw = FILLER_RE.exec(s.slice(pos));
        if (fw) { pos += fw[0].length; continue; }
        var w = /^\S+\s*/.exec(s.slice(pos))[0];
        unread.push(w.trim());
        pos += w.length;
        continue;
      }
      if (!hit.geom || !hit.geom.length) unread.push(s.slice(pos, hit.end));
      // how this piece joins the one before
      var unionSep = /\.\.\.|,|ALSO|ELSEWHERE/.test(gap) || cur === null;
      var andSep = /\bAND\b/.test(gap) && !unionSep;
      if (!unionSep && andSep && cur) {
        if (cur.kinds.shape || hit.kind === "shape" || cur.kinds[hit.kind] || Object.keys(cur.kinds).length >= 2) unionSep = true;
      }
      if (except) {
        cur = { geom: hit.geom, kinds: {}, op: "except", names: [] };
        cur.kinds[hit.kind] = 1;
        groups.push(cur);
      } else if (unionSep && !(cur && cur.op === "except" && !/\.\.\.|,|AND/.test(gap))) {
        cur = { geom: hit.geom, kinds: {}, op: "add", names: [] };
        cur.kinds[hit.kind] = 1;
        groups.push(cur);
      } else {
        cur.geom = cur.geom && hit.geom ? inter(cur.geom, hit.geom) : (cur.geom || hit.geom);
        cur.kinds[hit.kind] = 1;
      }
      cur.names.push(hit.name);
      pos = hit.end;
      prevKind = hit.kind;
    }
    var add = union(groups.filter(function (g) { return g.op === "add"; }).map(function (g) { return g.geom; }));
    var sub = union(groups.filter(function (g) { return g.op === "except"; }).map(function (g) { return g.geom; }));
    var g = sub && sub.length ? diff(add, sub) : add;
    var built = !!(g && g.length);
    g = built ? ctx.B.clip(g) : [];
    // a lone "BETWEEN 128W AND 170W" or "FROM 40N TO 50N" has no limits on the other axis: drawn edge to edge
    var open = null;
    groups.forEach(function (gr) {
      if (gr.op !== "add" || gr.names.length !== 1) return;
      if (/^lonband/.test(gr.names[0])) open = "lat";
      else if (gr.names[0] === "latband" && !open) open = "lon";
    });
    return { geom: g, ok: unread.length === 0 && groups.length > 0, unread: unread, outside: built && !g.length, guessed: guessed, open: open };
  }

  // ---------------------------------------------------------------- paragraphs
  var WIND_RE = /\bWINDS?\s+(?:(?:LESS THAN|UP TO|TO)\s+)?(?:(\d+)\s+TO\s+)?(\d+)\s*KT\b\.?\s*/g;
  var SEAS_RE = /^SEAS\s+(?:(?:LESS THAN|UP TO|TO)\s+)?(\d+(?:\.\d+)?)(?:\s+TO\s+(\d+(?:\.\d+)?))?\s*(M|FT)\b\.?/;
  var QUAL_RE = /^(?:\.\.\.|\s)*(?:HIGHEST|EXCEPT|LOCALLY|WITH|IN MIXED|IN [NSEW]+ (?:TO [NSEW]+ )?SWELL|PRIMARILY|MAINLY|NEAR|SE OF|SW OF|NE OF|NW OF)/;

  // tropical cyclone paragraphs in the NHC form: rewrite to "<area> WINDS a TO b KT."
  function tropical(p) {
    var mx = /MAXIMUM SUSTAINED WINDS (\d+) KT(?: GUSTS (\d+) KT)?\.?\s*/.exec(p);
    if (!mx) return p;
    var top = +mx[1];
    p = p.replace(mx[0], " ");
    p = p.replace(/\b(HURRICANE|TROPICAL STORM|STORM) FORCE WINDS (WITHIN [^.]*?)(?:\.(?!\.)|$)/g, function (x, kind, area) {
      var lo = kind === "HURRICANE" ? 64 : 34;
      return " " + area + " WINDS " + lo + " TO " + Math.max(top, lo) + " KT. ";
    });
    // "SEAS 12 FT OR GREATER WITHIN ..." / "SEAS 4 M OR GREATER WITHIN ...": context, not an area
    p = p.replace(/\bSEAS [\d.]+ (?:FT|M) OR GREATER WITHIN [^.]*\./g, " ");
    return p;
  }

  // the system sentence(s) before the first area: lows, fronts, motion
  function lastSentence(t) {
    // a sentence ends at "." not part of "..." and not inside a decimal
    var re = /(?:^|[^.\d])\.(?!\.)(?=\s|$)/g, m, cut = -1;
    while ((m = re.exec(t))) cut = m.index + m[0].length;
    return cut >= 0 ? t.slice(cut) : t;
  }
  var FRONT_RE = new RegExp("(?:(?:COLD |WARM |OCCLUDED |STATIONARY )?FRONT|TROUGH|LINE) (?:TO |WILL )?(?:EXT?EN(?:D|DS|DING) )?FROM (" + PLIST + ")", "g");

  function readPara(p, B, sysLows, hourDefault) {
    var flat = p.replace(/…/g, "...").replace(/\s+/g, " ").trim().toUpperCase();
    flat = flat.replace(/\bNEAR (\d+(?:\.\d+)?[NS]) (\d+(?:\.\d+)?[EW])/g, "NEAR $1$2")
      .replace(/\b(\d+\.\d+[NS]) (\d+(?:\.\d+)?[EW])\b/g, "$1$2")
      .replace(/(\d MB)\.(?=[A-Z])/g, "$1. ");
    var hour = hourDefault;
    var hm = /^\.?\s*(\d{1,2}) HOUR FORECAST\s*/.exec(flat);
    var body = flat;
    if (hm) { hour = +hm[1]; body = flat.slice(hm[0].length); }
    body = body.replace(/^\.\s*/, "");
    var lows = lowsOf(body, B);
    var useLows = lows.length ? lows : (/DISSIPATED|INLAND|MOVED|ABSORBED/.test(body) ? [] : sysLows);
    var ctx = { B: B, lows: useLows, line: null };
    FRONT_RE.lastIndex = 0;
    var fm = FRONT_RE.exec(body);
    if (fm) ctx.line = linePts(fm[1], ctx);
    body = tropical(body);
    var blocks = [], pos = 0, m;
    WIND_RE.lastIndex = 0;
    while ((m = WIND_RE.exec(body))) {
      var seg = body.slice(pos, m.index);
      var after = body.slice(WIND_RE.lastIndex);
      var sm = SEAS_RE.exec(after), seas = null, end = WIND_RE.lastIndex;
      if (sm) {
        seas = [sm[2] ? +sm[1] : 0, sm[2] ? +sm[2] : +sm[1], sm[3]];
        end += sm[0].length;
      }
      var rest = body.slice(end);
      if (QUAL_RE.test(rest)) {
        var se = /(?:^|[^.\d])\.(?!\.)(?=\s|$)/.exec(rest);
        end += se ? se.index + se[0].length : rest.length;
      }
      pos = end;
      WIND_RE.lastIndex = end;
      seg = seg.replace(/[\s.]+$/, "");
      var last = lastSentence(seg).trim();
      // "S OF 34N BETWEEN 48W AND 59W. AREA NE TO E WINDS": a bare direction belongs to the area before it
      if (/^(?:AREA\b[A-Z ]*|(?:MIXED )?[NSEW]{1,2}(?: TO [NSEW]{1,2})?)$/.test(last) && seg.length > last.length) {
        last = lastSentence(seg.slice(0, seg.length - last.length).replace(/[\s.]+$/, "")).trim() + " " + last;
      }
      seg = last;
      var tier = "first";
      var t0 = /^(?:\.\.\.\s*)?(ALSO|ELSEWHERE|ESLEWHERE)\b\s*/.exec(seg);
      if (t0) { tier = t0[1] === "ALSO" ? "also" : "elsewhere"; seg = seg.slice(t0[0].length); }
      // movement or fronts in the same sentence are not areas ("MOVING NE 25 KT")
      if (/MOVING [A-Z]+ ?$/.test(seg)) continue;
      var a = areaGeom(seg, ctx);
      blocks.push({ tier: tier, area_text: seg, wind: [m[1] ? +m[1] : 0, +m[2]], seas: seas, geom: a.geom, ok: a.ok && (a.geom.length > 0 || a.outside), outside: !!a.outside, unread: a.unread, guessed: a.guessed, open: a.open });
    }
    // ELSEWHERE means outside the areas already given in the paragraph: draw it that way
    var before = [];
    blocks.forEach(function (b) {
      b.draw = b.geom;
      if (b.tier === "elsewhere" && before.length && b.geom.length) {
        var d = diff(b.geom, union(before));
        if (d && d.length) b.draw = d;
      }
      if (b.geom.length) before.push(b.geom);
    });
    return { hour: hour, lows: lows, blocks: blocks, flat: flat, hazards: blocks.length ? [] : hazards(body, ctx) };
  }

  // fog and freezing spray paragraphs (no winds): ".DENSE FOG. VSBY OCCASIONALLY LESS THAN 1 NM <area>.",
  // ".24 HOUR FORECAST MODERATE TO HEAVY FREEZING SPRAY <area>. ELSEWHERE LIGHT TO MODERATE
  // FREEZING SPRAY <area>." -> [{kind: fog|spray, level: dense|light|moderate|heavy, words, area_text, geom, draw, ok}]
  function hazards(body, ctx) {
    var out = [], m;
    var one = function (kind, lvl, words, area) {
      area = area.replace(/[\s.,]+$/, "").trim();
      if (!area) return;
      var a = areaGeom(area, ctx);
      out.push({ kind: kind, level: lvl, words: words, area_text: area, geom: a.geom, draw: a.geom, ok: a.ok && a.geom.length > 0, unread: a.unread });
    };
    if ((m = /^DENSE FOG\b\.?\s*(?:VSBY\s+(?:OCCASIONALLY\s+)?(?:LESS THAN|BELOW|UNDER)\s+\d+(?:\.\d+)?\s*NM\.?\s*)?([\s\S]*)$/.exec(body))) {
      one("fog", "dense", "DENSE FOG", m[1]);
    } else if (/^(?:AREAS OF\s+)?(?:LIGHT|MODERATE|HEAVY)\b[A-Z ]*?FREEZING SPRAY\b/.test(body)) {
      body.split(/\.?\s*\bELSEWHERE\s+/).forEach(function (part) {
        var k = /^((?:AREAS OF\s+)?(?:LIGHT|MODERATE|HEAVY)(?:\s+TO\s+(?:MODERATE|HEAVY))?)\s+FREEZING SPRAY\s*([\s\S]*)$/.exec(part.trim());
        if (!k) return;
        one("spray", /HEAVY/.test(k[1]) ? "heavy" : /MODERATE/.test(k[1]) ? "moderate" : "light", k[1] + " FREEZING SPRAY", k[2]);
      });
      // ELSEWHERE: outside the areas already given
      for (var i = 1; i < out.length; i++) {
        var prev = union(out.slice(0, i).map(function (h) { return h.geom; }).filter(function (g) { return g.length; }));
        if (out[i].geom.length && prev && prev.length) { var d = diff(out[i].geom, prev); if (d && d.length) out[i].draw = d; }
      }
    }
    return out;
  }

  // ---------------------------------------------------------------- product
  function read(text, basin) {
    var B = new Basin(basin === "atl" ? "atl" : "pac");
    var t = String(text || "").replace(/\r/g, "").replace(/…/g, "...");
    var out = { basin: B.name, valid: {}, paras: [] };
    var vre = /(?:^|\n)\s*(?:SYNOPSIS|(\d{1,2}) HOUR FORECAST) VALID (\d{4} UTC [A-Z]{3} \d{1,2})/gi, vm;
    while ((vm = vre.exec(t))) out.valid[vm[1] ? +vm[1] : 0] = vm[2].toUpperCase();
    var w0 = t.search(/^\s*\.WARNINGS\./mi);
    var s0 = t.search(/^\s*\.SYNOPSIS AND FORECAST\./mi);
    var f0 = t.search(/^\s*\.FORECASTER\b/mi);
    var endAll = f0 > -1 ? f0 : t.length;
    if (w0 < 0 && s0 < 0) return out;
    // paragraph starts: "." at a line start (not "..."), a warning header, a section header, a
    // blank line, and ". NN HOUR FORECAST" run on mid-line
    var starts = [], re = /(^|\n)([ \t]*)(?=(\.\.\.[A-Z ]+?\.\.\.|\.(?!\.)|\n))/g, m;
    while ((m = re.exec(t))) {
      var at = m.index + m[1].length + m[2].length;
      if (at >= endAll) break;
      starts.push(at);
      if (re.lastIndex === m.index) re.lastIndex++;
    }
    var mid = /\.\s+(?=\d{1,2} HOUR FORECAST\b)/g;
    while ((m = mid.exec(t))) if (m.index < endAll) starts.push(m.index + 1 + (m[0].length - 1));
    starts.push(endAll);
    starts = starts.filter(function (v, i, a) { return a.indexOf(v) === i; }).sort(function (a, b) { return a - b; });
    var warning = "", sysLows = [], sys = -1, lastHour = -1;
    for (var i = 0; i < starts.length - 1; i++) {
      var a = starts[i], b = starts[i + 1];
      var chunk = t.slice(a, b);
      if (!chunk.trim()) continue;
      if (a < (w0 > -1 ? w0 : s0)) continue;
      var section = s0 > -1 && a >= s0 ? "synopsis" : "warnings";
      var hd = /^\s*\.\.\.\s*([A-Z ]+?)\s*\.\.\.\s*$/m.exec(chunk);
      if (/^\s*\.(WARNINGS|SYNOPSIS AND FORECAST)\./.test(chunk)) { warning = ""; sysLows = []; lastHour = -1; continue; }
      if (hd && chunk.trim().indexOf("...") === 0) {
        warning = hd[1].replace(/\s*WARNING$/, "").trim();
        sysLows = []; sys++; lastHour = -1;
        continue;
      }
      if (section === "synopsis") warning = "";
      // a paragraph that starts a new system resets the lows carried into later hours
      var hour0 = /^\s*\.?\s*(\d{1,2}) HOUR FORECAST/.exec(chunk);
      // a system: one warning block, or in the synopsis section a run of paragraphs whose hours rise
      if (section === "synopsis" && (lastHour < 0 || (hour0 ? +hour0[1] : 0) <= lastHour)) { sys++; sysLows = []; }
      if (sys < 0) sys = 0;
      var r = readPara(chunk, B, sysLows, 0);
      lastHour = r.hour;
      if (r.lows.length) sysLows = r.lows;
      var trimEnd = b;
      while (trimEnd > a && /\s/.test(t[trimEnd - 1])) trimEnd--;
      out.paras.push({ start: a, end: trimEnd, section: section, warning: warning, system: sys, hour: r.hour, lows: r.lows, blocks: r.blocks, hazards: r.hazards, text: r.flat });
    }
    out.tracks = tracks(out.paras);
    return out;
  }

  // the track of each system's main low through its forecast hours (two or more positions)
  function tracks(paras) {
    var by = {};
    paras.forEach(function (p, pi) {
      var L = p.lows.filter(function (l) { return l.kind === "L"; });
      if (!L.length) return;
      var main = L.filter(function (l) { return /MAIN|FIRST|MEAN|ORIGINAL/.test(l.label); })[0] || L[0];
      var t = by[p.system] || (by[p.system] = { system: p.system, section: p.section, warning: p.warning, points: [] });
      if (!t.points.some(function (q) { return q.hour === p.hour; })) t.points.push({ hour: p.hour, lat: main.lat, lon: main.lon, mb: main.mb, para: pi, raw: main.raw });
    });
    return Object.keys(by).map(function (k) { return by[k]; }).filter(function (t) { return t.points.length > 1; })
      .map(function (t) { t.points.sort(function (a, b) { return a.hour - b.hour; }); return t; });
  }

  // the official limits text of each basin and its outline
  function boundary(basin) { return { text: BOUNDARY_TEXT[basin], outline: OUTLINES[basin].slice() }; }

  return { read: read, boundary: boundary, areaOf: areaOf, OUTLINES: OUTLINES, _areaGeom: function (s, basin, lows) {
    var B = new Basin(basin); return areaGeom(s, { B: B, lows: lows || [], line: null });
  } };
});
