/* Shared helpers: decoding the generated payload, formatting, statistics.
   Plain scripts, no modules - the page also has to work opened off disk. */

window.HF = window.HF || {};

(function (HF) {
  'use strict';

  var MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  // Cool-season order: the archive's year runs July -> June, so charts that
  // show a seasonal cycle must not start at January or they split the peak.
  HF.SEASON_MONTHS = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6];
  HF.MONTH_NAMES = MONTH_NAMES;

  HF.monthName = function (m) { return MONTH_NAMES[m - 1] || '?'; };

  /** Decode array-encoded records from the build script into objects. */
  HF.decode = function (raw) {
    var fields = raw.lowFields;
    var fixFields = raw.fixFields;
    var fixIdx = fields.indexOf('fixes');

    var lows = raw.lows.map(function (row) {
      var low = {};
      for (var i = 0; i < fields.length; i++) {
        if (i === fixIdx) continue;
        low[fields[i]] = row[i];
      }
      low.fixes = (row[fixIdx] || []).map(function (f) {
        var fix = {};
        for (var j = 0; j < fixFields.length; j++) fix[fixFields[j]] = f[j];
        return fix;
      });
      // The build script keys each low internally as "<basin>:<id>" but that
      // field never made it into lowFields on the wire (it's ~29 KB of
      // derivable strings across 1932 records) - reproduce it here so
      // selection ("low.key === selectedKey") actually singles one out
      // instead of every decoded low sharing an undefined key.
      low.key = low.basin + ':' + low.id;
      return low;
    });

    return {
      generated: raw.generated,
      basins: raw.basins,
      categories: raw.categories,
      eventClasses: raw.eventClasses || {},
      recordStart: raw.recordStart,
      seasons: raw.seasons,
      lows: lows,
      qc: raw.qc
    };
  };

  /* ------------------------------------------------------------ formatting */

  /** 2020021518 -> "15 Feb 2020 18Z" */
  HF.fmtDate = function (n) {
    if (n == null) return '--';
    var s = String(n);
    return Number(s.slice(6, 8)) + ' ' + MONTH_NAMES[Number(s.slice(4, 6)) - 1] +
           ' ' + s.slice(0, 4) + ' ' + s.slice(8) + 'Z';
  };

  /** 2020021518 -> "15 Feb 18Z" (inside a table where the year is context) */
  HF.fmtDateShort = function (n) {
    if (n == null) return '--';
    var s = String(n);
    return Number(s.slice(6, 8)) + ' ' + MONTH_NAMES[Number(s.slice(4, 6)) - 1] +
           ' ' + s.slice(8) + 'Z';
  };

  HF.fmtLatLon = function (lat, lon) {
    if (lat == null || lon == null) return '--';
    return Math.abs(lat).toFixed(1) + '°' + (lat < 0 ? 'S' : 'N') + ' ' +
           Math.abs(lon).toFixed(1) + '°' + (lon < 0 ? 'W' : 'E');
  };

  HF.fmtNum = function (v, digits) {
    if (v == null || isNaN(v)) return '--';
    return Number(v).toFixed(digits == null ? 0 : digits);
  };

  HF.seasonLabel = function (start) {
    return start + '–' + String(start + 1).slice(-2);
  };

  /* ------------------------------------------------------------ statistics */

  HF.median = function (values) {
    var v = values.filter(function (x) { return x != null && !isNaN(x); })
                  .sort(function (a, b) { return a - b; });
    if (!v.length) return null;
    var mid = Math.floor(v.length / 2);
    return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
  };

  HF.mean = function (values) {
    var v = values.filter(function (x) { return x != null && !isNaN(x); });
    if (!v.length) return null;
    var sum = 0;
    for (var i = 0; i < v.length; i++) sum += v[i];
    return sum / v.length;
  };

  HF.percentile = function (values, p) {
    var v = values.filter(function (x) { return x != null && !isNaN(x); })
                  .sort(function (a, b) { return a - b; });
    if (!v.length) return null;
    var idx = Math.min(v.length - 1, Math.max(0, Math.round((p / 100) * (v.length - 1))));
    return v[idx];
  };

  /** Bin values into fixed-width bins; returns [{x0,x1,label,count,items}]. */
  HF.histogram = function (items, accessor, width, min, max) {
    var vals = [];
    for (var i = 0; i < items.length; i++) {
      var v = accessor(items[i]);
      if (v != null && !isNaN(v)) vals.push({ v: v, item: items[i] });
    }
    if (!vals.length) return [];

    var lo = min != null ? min : Math.floor(Math.min.apply(null, vals.map(function (d) { return d.v; })) / width) * width;
    var hi = max != null ? max : Math.ceil(Math.max.apply(null, vals.map(function (d) { return d.v; })) / width) * width;
    if (hi <= lo) hi = lo + width;

    var bins = [];
    for (var x = lo; x < hi; x += width) {
      bins.push({ x0: x, x1: x + width, count: 0, items: [] });
    }
    for (var j = 0; j < vals.length; j++) {
      var k = Math.floor((vals[j].v - lo) / width);
      if (k < 0) k = 0;
      if (k >= bins.length) k = bins.length - 1;   // top edge falls in the last bin
      bins[k].count++;
      bins[k].items.push(vals[j].item);
    }
    return bins;
  };

  /* --------------------------------------------------------------- colours */

  HF.cssVar = function (name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  };

  // Upper edge of each pressure step, shallowest-last. Shared with
  // HF.PRESSURE_BANDS below (keep the two in sync) and read by map.js to
  // batch-resolve the token->hex lookup once per render instead of once per
  // fix/segment.
  HF.PRESSURE_STOPS = [945, 957, 969, 981, 993, 1005];

  /** Which --mslp-* custom property a pressure falls on, as a name (not yet
      resolved to a colour) - lets a caller that's about to look up hundreds
      or thousands of these (map.js's per-segment tracks) resolve each
      distinct token once via HF.cssVar instead of once per call. */
  HF.pressureToken = function (hpa) {
    if (hpa == null) return '--mslp-none';
    var stops = HF.PRESSURE_STOPS;
    var step = stops.length + 1;
    for (var i = 0; i < stops.length; i++) {
      if (hpa < stops[i]) { step = i + 1; break; }
    }
    // step 1 = deepest -> --mslp-7 (hottest). step 7 = shallowest -> --mslp-1.
    var names = ['--mslp-7', '--mslp-6', '--mslp-5', '--mslp-4', '--mslp-3', '--mslp-2', '--mslp-1'];
    return names[Math.min(step, names.length) - 1];
  };

  /** Warm "intensity" ramp for central pressure, applied per fix: pale amber
      (shallow) through orange and red to deep magenta (deepest). Deeper low =
      hotter step, on --mslp-1..7 (1 = shallowest, 7 = deepest - see app.css
      for the validated hex values in each theme). Used both per-fix/segment
      (map tracks, the drawer's pressure trace) and for band midpoints (the
      pressure histogram, the map legend), so it has to work on arbitrary hPa
      values, not just the seven band centres. */
  HF.pressureColor = function (hpa) {
    return HF.cssVar(HF.pressureToken(hpa));
  };

  HF.PRESSURE_BANDS = [
    { label: '< 945', v: 940 },
    { label: '945–956', v: 950 },
    { label: '957–968', v: 962 },
    { label: '969–980', v: 974 },
    { label: '981–992', v: 986 },
    { label: '993–1004', v: 998 },
    { label: '≥ 1005', v: 1010 }
  ];

  /** Per-fix category colour. Ordinal severity, so it reads as a ramp. */
  HF.categoryColor = function (code) {
    switch (code) {
      case 'HF':  return HF.cssVar('--critical');
      case 'DHF': return HF.cssVar('--serious');
      case 'S':   return HF.cssVar('--warning');
      case 'DS':  return HF.cssVar('--seq-4');
      case 'G':   return HF.cssVar('--seq-2');
      case 'TC':  return '#7a5bd0';
      default:    return HF.cssVar('--ink-muted');
    }
  };

  /** Event class colour. Terrain-forced events have no pressure, so they sit
      outside the pressure ramp entirely and need their own hue. */
  HF.classColor = function (cls) {
    // Moved off magenta (#e87ba4), which now collides with the deep end of
    // the --mslp-* pressure ramp - violet reads as "not on the pressure
    // scale" instead, which is correct: these events have no analyzed centre.
    if (cls === 'tipjet') return HF.cssVar('--terrain');
    if (cls === 'nocentre') return HF.cssVar('--ink-muted');
    return HF.cssVar('--accent');
  };

  HF.basinColor = function (key) {
    return HF.cssVar(key === 'pac' ? '--pac' : '--atl');
  };

  /* ---------------------------------------------------------------- DOM */

  HF.el = function (tag, attrs, text) {
    var node = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'html') node.innerHTML = attrs[k];
        else node.setAttribute(k, attrs[k]);
      }
    }
    if (text != null) node.textContent = text;
    return node;
  };

  HF.clear = function (node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  };

  /* ------------------------------------------------------------- tooltip */

  var tip = null;

  HF.showTip = function (html, evt) {
    if (!tip) tip = document.getElementById('tooltip');
    tip.innerHTML = html;
    tip.hidden = false;
    HF.moveTip(evt);
  };

  HF.moveTip = function (evt) {
    if (!tip || tip.hidden) return;
    var pad = 14;
    var box = tip.getBoundingClientRect();
    var x = evt.clientX + pad;
    var y = evt.clientY + pad;
    if (x + box.width > window.innerWidth - 8) x = evt.clientX - box.width - pad;
    if (y + box.height > window.innerHeight - 8) y = evt.clientY - box.height - pad;
    tip.style.left = Math.max(8, x) + 'px';
    tip.style.top = Math.max(8, y) + 'px';
  };

  HF.hideTip = function () {
    if (!tip) tip = document.getElementById('tooltip');
    if (tip) tip.hidden = true;
  };

})(window.HF);
