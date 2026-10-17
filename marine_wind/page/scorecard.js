/* Model scorecard sheet for the marine wind page: how GFS, ECMWF and AIFS have
   handled sea-level pressure and 500 mb height over the last 7 and 30 days, for
   the basin the map is centred on (app.js sets window.MW_scoreBasin). Reads data/scorecard.json (marine_wind/scorecard/scorecard.py),
   one file for both basins, rows of one 12 UTC valid day x basin x model x lead. */
(function () {
  "use strict";

  var BASIN = "natl";
  var BASIN_NAME = { natl: "North Atlantic", npac: "North Pacific" };
  var MODELS = ["GFS", "ECMWF", "AIFS"];
  var $ = function (id) { return document.getElementById(id); };
  var data = null, loading = null;
  var st = { tab: "msl", lead: 72 };

  // Rows of the table: label, unit note, how to aggregate, which way is better.
  var METRICS = {
    msl: [
      { key: "msl_rmse", label: "Pressure error", unit: "hPa", agg: mean("msl_rmse"), dp: 2, better: -1 },
      { key: "pos", label: "Low position error", unit: "km", agg: ratio("pos_sum", "low_hit"), dp: 0, better: -1 },
      { key: "dp", label: "Low central pressure", unit: "hPa, + too weak", agg: ratio("dp_sum", "low_hit"), dp: 1, better: 0 },
      { key: "miss", label: "Lows missed", unit: "%", agg: missed, dp: 0, better: -1 },
      { key: "csi34", label: "Gale hit score", unit: "CSI 34 kt", agg: csi("34"), dp: 2, better: 1 },
      { key: "csi48", label: "Storm hit score", unit: "CSI 48 kt", agg: csi("48"), dp: 2, better: 1 }
    ],
    z: [
      { key: "z_acc", label: "Anomaly correlation", unit: "1 = perfect", agg: mean("z_acc"), dp: 3, better: 1 },
      { key: "z_rmse", label: "Height error", unit: "m", agg: mean("z_rmse"), dp: 0, better: -1 }
    ]
  };
  var STRIP = { msl: METRICS.msl[0], z: METRICS.z[0] };

  function mean(k) { return function (rs) { var s = 0, n = 0; rs.forEach(function (r) { if (r[k] != null) { s += r[k]; n++; } }); return n ? s / n : null; }; }
  function sum(rs, k) { var s = 0; rs.forEach(function (r) { s += r[k] || 0; }); return s; }
  function ratio(a, b) { return function (rs) { var d = sum(rs, b); return d ? sum(rs, a) / d : null; }; }
  function missed(rs) { var n = sum(rs, "low_n"); return n ? 100 * (1 - sum(rs, "low_hit") / n) : null; }
  function csi(t) { return function (rs) { var h = sum(rs, "h" + t), d = h + sum(rs, "f" + t) + sum(rs, "m" + t); return d >= 20 ? h / d : null; }; }

  function dayNum(ymd) { return Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8)) / 864e5; }
  function fmtDay(ymd) { return new Date(dayNum(ymd) * 864e5).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }); }

  function load() {
    if (!loading) {
      loading = fetch(((document.querySelector('meta[name="marine-wind-base"]') || {}).content || "") + "data/scorecard.json", { cache: "no-cache" }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).then(function (d) {
        data = d;
        data.all = d.rows.map(function (row) { var o = {}; d.cols.forEach(function (c, i) { o[c] = row[i]; }); return o; });
      });
    }
    return loading.then(function () {
      data.recs = data.all.filter(function (r) { return r.basin === BASIN; });
      data.days = Array.from(new Set(data.recs.map(function (r) { return r.valid; }))).sort();
    });
  }

  function rowsFor(model, lead, ndays) {
    var last = dayNum(data.days[data.days.length - 1]);
    return data.recs.filter(function (r) { return r.model === model && r.lead === lead && dayNum(r.valid) > last - ndays; });
  }

  function table() {
    var mets = METRICS[st.tab];
    var h = '<div class="sc-scroll"><table class="sc-table"><thead><tr><th rowspan="2"></th>' +
      MODELS.map(function (m) { return '<th colspan="2" class="sc-model"><i class="sc-key sc-' + m.toLowerCase() + '"></i>' + m + "</th>"; }).join("") +
      "</tr><tr>" + MODELS.map(function () { return "<th>7 d</th><th>30 d</th>"; }).join("") + "</tr></thead><tbody>";
    mets.forEach(function (M) {
      var vals = {};
      [7, 30].forEach(function (n) { vals[n] = MODELS.map(function (m) { return M.agg(rowsFor(m, st.lead, n)); }); });
      var best = {};
      [7, 30].forEach(function (n) {
        var v = vals[n], b = null;
        if (M.better) v.forEach(function (x, i) { if (x != null && (b === null || (x - v[b]) * M.better > 0)) b = i; });
        else v.forEach(function (x, i) { if (x != null && (b === null || Math.abs(x) < Math.abs(v[b]))) b = i; });
        // no highlight when the leader is tied (for example every model at 0.00)
        var tie = b !== null && v.filter(function (x) { return x != null && x.toFixed(M.dp) === v[b].toFixed(M.dp); }).length > 1;
        best[n] = tie ? null : b;
      });
      h += '<tr><th scope="row">' + M.label + '<span class="sc-unit">' + M.unit + "</span></th>";
      MODELS.forEach(function (m, i) {
        [7, 30].forEach(function (n) {
          var v = vals[n][i], s = v == null ? "&ndash;" : (M.key === "dp" && v > 0 ? "+" : "") + v.toFixed(M.dp);
          h += '<td class="' + (best[n] === i ? "sc-best" : "") + (n === 7 ? " sc-first" : "") + '">' + s + "</td>";
        });
      });
      h += "</tr>";
    });
    h += "</tbody></table></div>";
    var ref = data.reference && data.reference[BASIN];
    if (st.tab === "msl" && ref && ref.msl_rmse) {
      var li = data.leads.indexOf(st.lead);
      h += '<p class="sc-ref">' + ref.label + ", pressure error at day " + (st.lead / 24) + ": " +
        MODELS.map(function (m) { return m + " " + ref.msl_rmse[m][li].toFixed(2); }).join(", ") + " hPa.</p>";
    }
    return h;
  }

  // 30-day strip: one line per model for the tab's headline metric at this lead,
  // with days shaded where all three models did worse than their own usual.
  function strip() {
    var M = STRIP[st.tab], last = dayNum(data.days[data.days.length - 1]);
    var days = data.days.filter(function (d) { return dayNum(d) > last - 30; });
    if (days.length < 2) return '<p class="sc-ref">The 30-day strip appears once two days are scored.</p>';
    var ser = MODELS.map(function (m) {
      return days.map(function (d) {
        var r = data.recs.filter(function (x) { return x.model === m && x.lead === st.lead && x.valid === d; })[0];
        return r ? r[M.key] : null;
      });
    });
    var all = [].concat.apply([], ser).filter(function (v) { return v != null; });
    if (!all.length) return "";
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    if (M.key === "z_acc") { hi = 1; lo = Math.min(lo, 0.9); }
    else lo = 0;
    var pad = (hi - lo) * 0.08 || 0.1; if (M.key !== "z_acc") hi += pad;
    // drawn at the sheet's own width so the axis text stays readable on a phone
    var W = Math.max(300, Math.min(720, $("sc-content").clientWidth || 640)), H = W < 480 ? 150 : 170, L = 40, R = 56, T = 10, B = 24;
    var x = function (i) { return L + (W - L - R) * i / (days.length - 1); };
    var y = function (v) { return T + (H - T - B) * (hi - v) / (hi - lo); };
    // shared bad days: every model worse than its own 75th percentile over the strip
    var q = ser.map(function (s) {
      var v = s.filter(function (z) { return z != null; }).sort(function (a, b) { return a - b; });
      return v.length ? (M.better < 0 ? v[Math.floor(0.75 * (v.length - 1))] : v[Math.ceil(0.25 * (v.length - 1))]) : null;
    });
    var bad = days.map(function (d, i) {
      return ser.every(function (s, k) { return s[i] != null && q[k] != null && (M.better < 0 ? s[i] > q[k] : s[i] < q[k]); });
    });
    var bw = (W - L - R) / Math.max(days.length - 1, 1);
    var svg = '<svg class="sc-strip" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + M.label + " by day, last 30 days, day " + (st.lead / 24) + ' forecasts">';
    bad.forEach(function (b, i) { if (b) svg += '<rect class="sc-bust" x="' + (x(i) - bw / 2) + '" y="' + T + '" width="' + bw + '" height="' + (H - T - B) + '"/>'; });
    var ticks = 4;
    for (var t = 0; t <= ticks; t++) {
      var v = lo + (hi - lo) * t / ticks;
      svg += '<line class="sc-grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>' +
        '<text class="sc-axis" x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + v.toFixed(M.key === "z_acc" ? 2 : M.dp > 1 ? 1 : 0) + "</text>";
    }
    [0, Math.floor((days.length - 1) / 2), days.length - 1].forEach(function (i) {
      svg += '<text class="sc-axis" x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? "start" : i === days.length - 1 ? "end" : "middle") + '">' + fmtDay(days[i]) + "</text>";
    });
    var ends = [];
    ser.forEach(function (s, k) {
      var d = "", pen = false;
      s.forEach(function (v, i) { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true; });
      svg += '<path class="sc-line sc-' + MODELS[k].toLowerCase() + '" d="' + d + '"/>';
      for (var i = s.length - 1; i >= 0; i--) if (s[i] != null) { ends.push([k, y(s[i])]); break; }
    });
    ends.sort(function (a, b) { return a[1] - b[1]; });
    for (var e = 1; e < ends.length; e++) if (ends[e][1] - ends[e - 1][1] < 12) ends[e][1] = ends[e - 1][1] + 12;
    ends.forEach(function (en) { svg += '<text class="sc-label" x="' + (W - R + 6) + '" y="' + (en[1] + 4) + '">' + MODELS[en[0]] + "</text>"; });
    svg += '<line class="sc-cross" id="sc-cross" x1="0" x2="0" y1="' + T + '" y2="' + (H - B) + '" visibility="hidden"/>';
    svg += '<rect class="sc-hit" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '"/></svg>';
    var h = '<div class="sc-stripwrap"><h3>' + M.label + ", day " + (st.lead / 24) + " forecasts, last 30 days</h3>" + svg +
      '<div class="sc-tip" id="sc-tip" hidden></div></div>' +
      '<p class="sc-ref"><span class="sc-bustkey"></span>Shaded: days all three models did worse than their own usual (their worst quarter). These are shared misses, which point to a hard pattern rather than one bad model.</p>';
    setTimeout(function () { hover(days, ser, M, x, W); }, 0);
    return h;
  }

  function hover(days, ser, M, x, W) {
    var svg = document.querySelector("#scorecard .sc-strip"), tip = $("sc-tip"), cross = $("sc-cross");
    if (!svg) return;
    function move(ev) {
      var b = svg.getBoundingClientRect(), sx = (ev.clientX - b.left) * W / b.width;
      var i = Math.round((sx - x(0)) / (x(1) - x(0)));
      i = Math.max(0, Math.min(days.length - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      tip.innerHTML = '<div class="h">' + fmtDay(days[i]) + " 12 UTC</div>" + MODELS.map(function (m, k) {
        var v = ser[k][i];
        return '<div><i class="sc-key sc-' + m.toLowerCase() + '"></i>' + m + "<b>" + (v == null ? "&ndash;" : v.toFixed(M.dp)) + "</b></div>";
      }).join("");
      tip.hidden = false;
      var px = x(i) * b.width / W;
      tip.style.left = Math.min(Math.max(px - tip.offsetWidth / 2, 0), b.width - tip.offsetWidth) + "px";
    }
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerdown", move);
    svg.addEventListener("pointerleave", function () { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
  }

  function render() {
    var body = $("sc-content");
    if (!data || !data.days.length) { body.innerHTML = '<p class="sc-ref">No scores yet for the ' + BASIN_NAME[BASIN] + ". They are added once a day after the 12 UTC analyses.</p>"; return; }
    Array.prototype.forEach.call(document.querySelectorAll("#scorecard [data-tab]"), function (b) { b.setAttribute("aria-selected", b.dataset.tab === st.tab ? "true" : "false"); });
    Array.prototype.forEach.call(document.querySelectorAll("#scorecard [data-lead]"), function (b) { b.setAttribute("aria-pressed", +b.dataset.lead === st.lead ? "true" : "false"); });
    var n30 = data.days.filter(function (d) { return dayNum(d) > dayNum(data.days[data.days.length - 1]) - 30; }).length;
    body.innerHTML = table() + strip() +
      '<p class="sc-fine">' + n30 + " of the last 30 days scored, newest valid " + fmtDay(data.days[data.days.length - 1]) + " 12 UTC. " +
      (st.tab === "msl" ? "Pressure over the high seas, 30&ndash;67N, " + (BASIN === "natl" ? "75W&ndash;0" : "160E&ndash;115W") + " (the area the blend was tested on); lows are analysed centres under 1000 hPa, matched within 800 km. Hit scores are for 10 m wind on open water."
        : "500 mb over 25&ndash;75N, " + (BASIN === "natl" ? "130W&ndash;10E (North America upstream)" : "100E&ndash;110W (East Asia and the west Pacific upstream)") + ", against the ERA5 1990&ndash;2019 climatology.") +
      " Truth: the mean of the GFS and ECMWF analyses, so no model is scored against its own. Best value in each column is brighter.</p>";
  }

  function open() {
    BASIN = window.MW_scoreBasin ? window.MW_scoreBasin() : (/[?&]basin=npac\b/.test(location.search) ? "npac" : "natl");
    $("scorecard").hidden = false; $("score-btn").setAttribute("aria-expanded", "true");
    $("sc-title").textContent = "Model scorecard · " + BASIN_NAME[BASIN];
    $("sc-content").innerHTML = '<p class="sc-ref">Loading scores</p>';
    load().then(render, function () { $("sc-content").innerHTML = '<p class="sc-ref">The scorecard isn’t available yet.</p>'; });
  }
  function close() { $("scorecard").hidden = true; $("score-btn").setAttribute("aria-expanded", "false"); }

  document.addEventListener("DOMContentLoaded", function () {
    $("score-btn").addEventListener("click", open);
    $("sc-close").addEventListener("click", close);
    $("scorecard").addEventListener("click", function (e) { if (e.target === this) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("scorecard").hidden) close(); });
    Array.prototype.forEach.call(document.querySelectorAll("#scorecard [data-tab]"), function (b) {
      b.addEventListener("click", function () { st.tab = b.dataset.tab; render(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll("#scorecard [data-lead]"), function (b) {
      b.addEventListener("click", function () { st.lead = +b.dataset.lead; render(); });
    });
  });
})();
