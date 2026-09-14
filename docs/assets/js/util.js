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

  /** Sequential ramp for central pressure: deeper low = darker step. */
  HF.pressureColor = function (hpa) {
    if (hpa == null) return HF.cssVar('--ink-muted');
    var stops = [940, 952, 964, 976, 988, 1000];     // upper edge of each step
    var step = stops.length + 1;
    for (var i = 0; i < stops.length; i++) {
      if (hpa < stops[i]) { step = i + 1; break; }
    }
    // step 1 = deepest. Darkest sequential step for the deepest low.
    var names = ['--seq-7', '--seq-6', '--seq-5', '--seq-4', '--seq-3', '--seq-2', '--seq-1'];
    return HF.cssVar(names[Math.min(step, names.length) - 1]);
  };

  HF.PRESSURE_BANDS = [
    { label: '< 940', v: 935 },
    { label: '940–951', v: 945 },
    { label: '952–963', v: 957 },
    { label: '964–975', v: 969 },
    { label: '976–987', v: 981 },
    { label: '988–999', v: 993 },
    { label: '≥ 1000', v: 1005 }
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
    if (cls === 'tipjet') return '#e87ba4';        // categorical slot 5
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
