/* Research Scores page. Reads data/ (copied in by .github/workflows/site_publish.yml from the
   `scores` release of jkrek17/marine-research-data, written by that repository's scores.yml):
     standing_scores.csv   study, week, basin, method, metric, value, n, truth
     drift_flags.csv       study, method, metric, weeks_used, recent_mean, ci_lo, ci_hi, source, drift
     preset_status.csv     study, status, exit_code, message (missing inputs are listed in the message)
     scores_meta.json      generated time, kit commit, weeks scored
   The browser never fetches the release itself (no CORS headers there). Everything shown is computed
   here from the weekly rows: the mean is weighted by n, so any basin choice pools correctly.
   The basin choice lives in the URL hash. */
(function () {
  "use strict";

  var FILES = ["standing_scores.csv", "drift_flags.csv", "preset_status.csv", "scores_meta.json"];
  var BASINS = { natl: "Atlantic", npac: "Pacific" };
  var LATEST = 4;
  var NS = "http://www.w3.org/2000/svg";

  // Study names in forecaster language; an unlisted study falls back to its folder name.
  var STUDIES = {
    "2026-10-16-pressure-d5-7": "Day 5-7 pressure",
    "2026-10-16-warning-forecast": "Warning forecast"
  };
  // Per-study note, shown as a tag beside the heading with its line beneath.
  var STUDY_NOTES = {
    "2026-10-16-warning-forecast": { tag: "Provisional", text: "Rules and intervals are placeholders until the study picks its final rules; the interval used a different ASCAT matching." }
  };
  // Known "missing input" notes from preset_status.csv, in plain words. First match wins; an unmatched
  // note is shown as reported, minus paths and function names.
  var MISSING_WORDS = [
    [/\+(144|168) h MSLP/, "Day 6 and 7 model pressure are not in the shared store yet."],
    [/^vote\b/, "The member vote needs every ensemble member's lows; the store keeps member statistics only."],
    [/^desk\b/, "The desk's issued warning areas have no reader yet, so there is no desk comparison."],
    [/every member's 10 m speed/, "Rules built from every member's wind need member winds in the store."]
  ];
  var STUDY_ORDER = ["2026-10-16-pressure-d5-7", "2026-10-16-warning-forecast"];

  // Metric families. A trailing _dN is the forecast day. better: which way is good.
  var kmFmt = function (v) { return Math.round(v).toLocaleString("en-US"); };
  var METRICS = {
    position_km: { label: function (d) { return "Low position error (km), day " + d; }, fmt: kmFmt, better: "lower" },
    depth_hpa: { label: function (d) { return "Low pressure error (hPa), day " + d; }, fmt: function (v) { return v.toFixed(1); }, better: "lower" },
    hit_300km: { label: function (d) { return "Lows found within 300 km, day " + d; }, fmt: pct, better: "higher" },
    false_lows: { label: function (d) { return "False lows per map, day " + d; }, fmt: function (v) { return v.toFixed(2); }, better: "lower" },
    gale_catch: { label: function () { return "Gale catch"; }, fmt: pct, better: "higher" },
    gale_fa_area: { label: function () { return "Gale false-alarm share"; }, fmt: pct, better: "lower" },
    gale_area_nm2: { label: function () { return "Gale warned area (nm²)"; }, fmt: kmFmt, better: "lower" },
    storm_catch: { label: function () { return "Storm catch"; }, fmt: pct, better: "higher" },
    storm_fa_area: { label: function () { return "Storm false-alarm share"; }, fmt: pct, better: "lower" },
    storm_area_nm2: { label: function () { return "Storm warned area (nm²)"; }, fmt: kmFmt, better: "lower" }
  };
  var METRIC_ORDER = Object.keys(METRICS);
  function pct(v) { return (100 * v).toFixed(1) + "%"; }
  function metricInfo(m) {
    var mt = /^(.*)_d(\d)$/.exec(m), base = mt ? mt[1] : m, day = mt ? +mt[2] : 0;
    var info = METRICS[base];
    if (!info) return { base: base, day: day, label: m.replace(/_/g, " "), fmt: function (v) { return String(+v.toPrecision(4)); }, better: "" };
    return { base: base, day: day, label: info.label(day), fmt: info.fmt, better: info.better };
  }
  function metricCmp(a, b) {
    var A = metricInfo(a), B = metricInfo(b);
    var ia = METRIC_ORDER.indexOf(A.base), ib = METRIC_ORDER.indexOf(B.base);
    ia = ia < 0 ? 99 : ia; ib = ib < 0 ? 99 : ib;
    return ia - ib || A.day - B.day || (a < b ? -1 : a > b ? 1 : 0);
  }

  // Methods: the model colours of /verification/ (css --m-*). The wind method, if it ever appears, is
  // "Core Lifted", never "Page wind".
  var MODEL_ORDER = ["gfs", "ifs", "aifs", "model_ifs", "pmem", "windcore"];
  var SPARE = ["#0f766e", "#b45309", "#7c3aed", "#be123c"];
  function methodInfo(k, spare) {
    var base = k.split("@")[0], arg = k.indexOf("@") >= 0 ? k.split("@")[1] : "";
    var name, c;
    if (base === "gfs") { name = "GFS"; c = "--m-gfs"; }
    else if (base === "ifs" || base === "ecmwf") { name = "ECMWF IFS"; c = "--m-ecmwf"; }
    else if (base === "aifs") { name = "AIFS"; c = "--m-aifs"; }
    else if (base === "model_ifs") { name = "IFS wind + " + arg + " kt"; c = "--m-ecmwf"; }
    else if (base === "pmem") { name = "Ensemble share ≥ " + Math.round(100 * arg) + "%"; c = "--m-mean3"; }
    else if (base === "windcore") { name = "Core Lifted"; c = "--m-windcore"; }
    else { name = k.replace(/page[ _]?wind/i, "Core Lifted"); c = null; }
    var color = c ? getComputedStyle(document.documentElement).getPropertyValue(c).trim() : SPARE[spare % SPARE.length];
    return { name: name, color: color, order: MODEL_ORDER.indexOf(base) };
  }
  function methodCmp(a, b) {
    var ia = methodInfo(a, 0).order, ib = methodInfo(b, 0).order;
    ia = ia < 0 ? 99 : ia; ib = ib < 0 ? 99 : ib;
    return ia - ib || (a < b ? -1 : a > b ? 1 : 0);
  }

  // ------------------------------------------------------------------ small helpers
  var $ = function (id) { return document.getElementById(id); };
  function h(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) { if (k === "text") e.textContent = attrs[k]; else if (attrs[k] != null) e.setAttribute(k, attrs[k]); }
    for (var i = 2; i < arguments.length; i++) { var c = arguments[i]; if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); }
    return e;
  }
  function s(tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }

  // RFC 4180 parser (the notes and sources hold commas and quotes).
  function parseCSV(text) {
    var rows = [], row = [], field = "", q = false, i = 0, c;
    text = text.replace(/^﻿/, "");
    for (; i < text.length; i++) {
      c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; } else field += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); field = ""; rows.push(row); row = [];
      } else field += c;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    var head = rows.shift() || [];
    return rows.filter(function (r) { return r.length > 1 || r[0] !== ""; }).map(function (r) {
      var o = {}; head.forEach(function (k, j) { o[k] = r[j] === undefined ? "" : r[j]; }); return o;
    });
  }

  function load(name) {
    return fetch("data/" + name, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(name + " " + r.status);
      return name.slice(-5) === ".json" ? r.json() : r.text().then(parseCSV);
    }).catch(function () { return null; });
  }

  // ISO week "2025-W45" -> UTC ms of its Monday
  function weekStart(w) {
    var m = /^(\d{4})-W(\d{1,2})$/.exec(w); if (!m) return NaN;
    var jan4 = new Date(Date.UTC(+m[1], 0, 4)), dow = (jan4.getUTCDay() + 6) % 7;
    return jan4.getTime() - dow * 864e5 + (+m[2] - 1) * 7 * 864e5;
  }
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function dayLabel(ms) { var d = new Date(ms); return d.getUTCDate() + " " + MON[d.getUTCMonth()]; }

  // ------------------------------------------------------------------ state
  var state = { basin: "both" };
  var D = { scores: [], flags: {}, status: {}, meta: null, basins: [] };

  function readHash() {
    var m = /basin=(natl|npac|both)/.exec(location.hash); if (m) state.basin = m[1];
  }
  function writeHash() { try { history.replaceState(null, "", "#basin=" + state.basin); } catch (e) { /* file:// */ } }

  // ------------------------------------------------------------------ computing
  // weeks (sorted) of a study over the chosen basins; n-weighted mean per (method, metric, week)
  function studyData(study) {
    var rows = D.scores.filter(function (r) { return r.study === study && (state.basin === "both" || r.basin === state.basin); });
    var acc = {}, weeks = {};
    rows.forEach(function (r) {
      var v = parseFloat(r.value), n = parseFloat(r.n);
      if (!isFinite(v) || !(n > 0)) return;
      weeks[r.week] = 1;
      var k = r.metric + "\t" + r.method;
      var a = acc[k] || (acc[k] = { metric: r.metric, method: r.method, by: {} });
      var w = a.by[r.week] || (a.by[r.week] = { sv: 0, n: 0 });
      w.sv += v * n; w.n += n;
    });
    var all = Object.keys(weeks).sort(function (a, b) { return weekStart(a) - weekStart(b); });
    return { acc: acc, weeks: all, latest: all.slice(-LATEST) };
  }
  function recent(a, latest) {
    var sv = 0, n = 0;
    latest.forEach(function (wk) { var w = a.by[wk]; if (w) { sv += w.sv; n += w.n; } });
    return n > 0 ? { mean: sv / n, n: n } : null;
  }

  // ------------------------------------------------------------------ render
  function renderBasin() {
    var el = $("basin");
    if (D.basins.length < 2) { el.hidden = true; return; }
    el.hidden = false; el.textContent = "";
    [["natl", "Atlantic"], ["npac", "Pacific"], ["both", "Both"]].forEach(function (b) {
      var btn = h("button", { type: "button", role: "radio", "aria-checked": String(state.basin === b[0]), text: b[1] });
      btn.addEventListener("click", function () { state.basin = b[0]; writeHash(); renderBasin(); renderStudies(); });
      el.appendChild(btn);
    });
  }

  function studyTitle(id) { return STUDIES[id] || id.replace(/^\d{4}-\d{2}-\d{2}-/, "").replace(/-/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }

  function renderStudies() {
    var host = $("studies"); host.textContent = "";
    var ids = [];
    D.scores.forEach(function (r) { if (ids.indexOf(r.study) < 0) ids.push(r.study); });
    Object.keys(D.status).forEach(function (k) { if (ids.indexOf(k) < 0) ids.push(k); });
    ids.sort(function (a, b) {
      var ia = STUDY_ORDER.indexOf(a), ib = STUDY_ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || (a < b ? -1 : 1);
    });
    ids.forEach(function (id) { host.appendChild(studySection(id)); });
  }

  function studySection(id) {
    var sec = h("section", { class: "card", "aria-labelledby": "h-" + id });
    var head = h("div", { class: "card-head" }, h("h2", { id: "h-" + id, text: studyTitle(id) }));
    var sn = STUDY_NOTES[id];
    if (sn) head.appendChild(h("span", { class: "tag", text: sn.tag }));
    sec.appendChild(head);
    if (sn) sec.appendChild(h("p", { class: "sub", text: sn.text }));
    var sd = studyData(id);
    if (!sd.weeks.length) {
      sec.appendChild(h("p", { class: "sub", text: "No scores for this choice yet." }));
      sec.appendChild(missingBlock(id));
      return sec;
    }
    var span = sd.weeks.length > 1 ? sd.weeks[0] + " to " + sd.weeks[sd.weeks.length - 1] : sd.weeks[0];
    var truth = ""; D.scores.some(function (r) { if (r.study === id && r.truth) { truth = r.truth.replace(/\s*\(rk\.[^)]*\)/, ""); return true; } });
    head.appendChild(h("p", { class: "sub", text: "Latest " + sd.latest.length + " of " + sd.weeks.length + " scored weeks (" + sd.latest.join(", ") + ")" +
      (sd.latest.length < LATEST ? ": fewer than " + LATEST + " weeks scored so far" : "") }));
    if (truth) sec.appendChild(h("p", { class: "sub", text: "Scored against: " + truth + ". Weeks " + span + "." }));

    // metrics and methods present
    var metrics = [], methodsOf = {}, allMethods = [];
    Object.keys(sd.acc).forEach(function (k) {
      var a = sd.acc[k];
      if (metrics.indexOf(a.metric) < 0) metrics.push(a.metric);
      (methodsOf[a.metric] = methodsOf[a.metric] || []).push(a.method);
      if (allMethods.indexOf(a.method) < 0) allMethods.push(a.method);
    });
    metrics.sort(metricCmp);
    allMethods.sort(methodCmp);
    var spare = {}; var nSpare = 0;
    allMethods.forEach(function (m) { var o = methodInfo(m, nSpare); if (o.order < 0) nSpare++; spare[m] = o; });

    // table
    var tbl = h("table", { class: "score" });
    tbl.appendChild(h("thead", null, h("tr", null,
      h("th", { scope: "col", text: "Method" }), h("th", { scope: "col", text: "Latest " + sd.latest.length + (sd.latest.length === 1 ? " week" : " weeks") }),
      h("th", { scope: "col", text: "Original interval" }), h("th", { scope: "col", text: "Drift (both basins)" }), h("th", { scope: "col", text: "n" }))));
    var body = h("tbody");
    var sources = {};
    metrics.forEach(function (m) {
      var mi = metricInfo(m);
      body.appendChild(h("tr", { class: "group" }, h("th", { colspan: "5", scope: "colgroup" }, mi.label, mi.better ? h("small", { text: mi.better + " is better" }) : null)));
      methodsOf[m].sort(methodCmp).forEach(function (meth) {
        var a = sd.acc[m + "\t" + meth], r = recent(a, sd.latest), fl = (D.flags[id] || {})[m + "\t" + meth];
        var mn = spare[meth];
        var tr = h("tr");
        tr.appendChild(h("td", null, h("span", { class: "mname" }, h("span", { class: "swatch", style: "background:" + mn.color }), mn.name)));
        tr.appendChild(h("td", r ? null : { class: "na" }, r ? mi.fmt(r.mean) : "–"));
        var lo = fl ? parseFloat(fl.ci_lo) : NaN, hi = fl ? parseFloat(fl.ci_hi) : NaN;
        tr.appendChild(h("td", isFinite(lo) && isFinite(hi) ? { title: fl.source } : { class: "na" }, isFinite(lo) && isFinite(hi) ? mi.fmt(lo) + " to " + mi.fmt(hi) : "–"));
        if (fl && fl.source) sources[fl.source] = 1;
        var d = fl ? fl.drift : "";
        var lab = d === "ok" ? ["ok", "ok"] : d === "drift" ? ["drift", "drift"] : d ? ["few", "not enough weeks"] : ["few", "–"];
        tr.appendChild(h("td", null, h("span", { class: "flag " + lab[0], text: lab[1] })));
        tr.appendChild(h("td", r ? null : { class: "na" }, r ? Math.round(r.n).toLocaleString("en-US") : "–"));
        body.appendChild(tr);
      });
    });
    tbl.appendChild(body);
    sec.appendChild(h("div", { class: "table-wrap" }, tbl));
    var src = Object.keys(sources);
    if (src.length) sec.appendChild(h("p", { class: "foot", text: "Original interval: " + src.join("; ") + "." }));

    // trend lines: one per metric, one colour per method, one y axis
    var legend = h("div", { class: "legend", "aria-label": "Methods" });
    allMethods.forEach(function (m) { legend.appendChild(h("span", null, h("span", { class: "swatch", style: "background:" + spare[m].color }), spare[m].name)); });
    sec.appendChild(legend);
    var charts = h("div", { class: "charts" });
    metrics.forEach(function (m) { charts.appendChild(trendChart(sd, m, methodsOf[m].sort(methodCmp), spare)); });
    sec.appendChild(charts);
    sec.appendChild(missingBlock(id));
    return sec;
  }

  function niceMax(v) {
    if (!(v > 0)) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), f = v / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }

  function trendChart(sd, metric, methods, spare) {
    var mi = metricInfo(metric);
    var fig = h("figure", { class: "chart" }, h("figcaption", null, mi.label));
    var W = 420, H = 190, L = 46, R = 10, T = 8, B = 24, iw = W - L - R, ih = H - T - B;
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": mi.label + " by week" });
    var t0 = weekStart(sd.weeks[0]), t1 = weekStart(sd.weeks[sd.weeks.length - 1]);
    var x = function (wk) { return t1 === t0 ? L + iw / 2 : L + iw * (weekStart(wk) - t0) / (t1 - t0); };
    var ymax = 0;
    methods.forEach(function (meth) { var a = sd.acc[metric + "\t" + meth]; Object.keys(a.by).forEach(function (wk) { ymax = Math.max(ymax, a.by[wk].sv / a.by[wk].n); }); });
    ymax = mi.fmt === pct ? Math.min(1, niceMax(ymax * 1.05)) : niceMax(ymax * 1.05);
    var y = function (v) { return T + ih * (1 - v / ymax); };
    var grid = s("g", { class: "grid" }), axis = s("g", { class: "axis" });
    for (var i = 0; i <= 4; i++) {
      var v = ymax * i / 4;
      grid.appendChild(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      axis.appendChild(s("text", { x: L - 6, y: y(v) + 3, "text-anchor": "end" }, mi.fmt(v)));
    }
    // x ticks: at most about 6, on scored weeks
    var step = Math.max(1, Math.ceil(sd.weeks.length / 6));
    sd.weeks.forEach(function (wk, j) {
      if (j % step && j !== sd.weeks.length - 1) return;
      axis.appendChild(s("text", { x: x(wk), y: H - 7, "text-anchor": j === 0 && sd.weeks.length > 1 ? "start" : j === sd.weeks.length - 1 && sd.weeks.length > 1 ? "end" : "middle" }, dayLabel(weekStart(wk))));
    });
    svg.appendChild(grid); svg.appendChild(axis);
    methods.forEach(function (meth) {
      var a = sd.acc[metric + "\t" + meth], col = spare[meth].color, d = "", prev = -2;
      var pts = [];
      sd.weeks.forEach(function (wk, j) {
        var w = a.by[wk]; if (!w) return;
        var val = w.sv / w.n;
        d += (prev === j - 1 ? "L" : "M") + x(wk).toFixed(1) + " " + y(val).toFixed(1);
        prev = j; pts.push([wk, val, w.n]);
      });
      svg.appendChild(s("path", { class: "series", d: d, stroke: col }));
      pts.forEach(function (p) {
        svg.appendChild(s("circle", { cx: x(p[0]).toFixed(1), cy: y(p[1]).toFixed(1), r: 3, fill: col, stroke: "#fff", "stroke-width": 1 }))
          .appendChild(s("title", null, spare[meth].name + ", " + p[0] + ": " + mi.fmt(p[1]) + " (n " + Math.round(p[2]).toLocaleString("en-US") + ")"));
      });
    });
    fig.appendChild(svg);
    fig.appendChild(h("p", { class: "foot", text: "Week starting. " + (mi.better ? mi.better.charAt(0).toUpperCase() + mi.better.slice(1) + " is better." : "") }));
    return fig;
  }

  function missingBlock(id) {
    var st = D.status[id], items = [];
    var box = h("div", { class: "missing" });
    if (!st) return box;
    (st.message || "").split(" | ").forEach(function (part) {
      var mm = /^MISSING INPUT \([^)]*\):\s*(.*)$/.exec(part.trim());
      if (mm) items.push(mm[1]);
    });
    if (st.status && st.status !== "ok") {
      box.appendChild(h("p", { class: "note", text: "The last run of this study's scoring failed (exit " + (st.exit_code || "?") + "), so its rows may be older than the other studies'." }));
    }
    if (!items.length) { box.hidden = !box.children.length; return box; }
    box.appendChild(h("h3", { text: "Not scored yet" }));
    var ul = h("ul", { class: "plain" });
    var shown = [];
    items.forEach(function (t) {
      var txt = null;
      MISSING_WORDS.some(function (w) { if (w[0].test(t)) { txt = w[1]; return true; } });
      // fallback: the raw text without parenthesised paths, file names and RK_* / rk.* names
      if (!txt) txt = t.replace(/\s*\([^)]*\)/g, "").replace(/\/[\w.\-\/<>]+/g, "").replace(/\b(RK_\w+|rk\.[\w.]+|\w+\.(py|csv|json|npz))\b/g, "").replace(/\s+([,.;:])/g, "$1").replace(/\s{2,}/g, " ").trim();
      if (shown.indexOf(txt) < 0) shown.push(txt);
    });
    shown.forEach(function (txt) { ul.appendChild(h("li", { text: txt })); });
    box.appendChild(ul);
    return box;
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    readHash();
    Promise.all(FILES.map(load)).then(function (res) {
      var scores = res[0], flags = res[1], status = res[2], meta = res[3];
      if (!scores || !scores.length) {
        var n = $("note"); n.hidden = false;
        n.textContent = "No scores are published yet. The weekly job writes them on Mondays; check back after the next run.";
        $("intro").textContent = "";
        return;
      }
      D.scores = scores;
      (flags || []).forEach(function (r) { (D.flags[r.study] = D.flags[r.study] || {})[r.metric + "\t" + r.method] = r; });
      (status || []).forEach(function (r) { D.status[r.study] = r; });
      D.meta = meta;
      scores.forEach(function (r) { if (D.basins.indexOf(r.basin) < 0) D.basins.push(r.basin); });
      if (D.basins.length < 2 && state.basin !== "both") state.basin = "both";
      var nWeeks = {}; scores.forEach(function (r) { nWeeks[r.week] = 1; });
      $("intro").textContent = "How the desk's finished research studies keep scoring on new weeks, in forecaster terms. Each study is re-scored every Monday over its newest weeks; the tables compare the latest " + LATEST + " weeks with the study's original interval.";
      if (meta && meta.generated_utc) {
        var t = new Date(meta.generated_utc);
        $("updated").textContent = "Generated " + (isNaN(t) ? meta.generated_utc : t.toISOString().slice(0, 16).replace("T", " ") + " UTC");
      }
      var f = $("files"); f.textContent = "";
      f.appendChild(document.createTextNode("Data, copied at publish time from the scores release of jkrek17/marine-research-data: "));
      FILES.forEach(function (n) { f.appendChild(h("a", { href: "data/" + n, text: n })); f.appendChild(document.createTextNode(" ")); });
      if (meta) f.appendChild(document.createTextNode(" Kit " + (meta.kit_sha || "").slice(0, 7) + (meta.start ? ", last run scored " + meta.start + " to " + meta.end : "") + "."));
      renderBasin();
      renderStudies();
    });
  }
  boot();
})();
