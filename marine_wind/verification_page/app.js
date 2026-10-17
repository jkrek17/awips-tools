/* Marine Wind Verification page. Reads data/ (marine_wind/verify/page_data.py):
     index.json                 coverage and the method / truth lists
     BASIN_REF.json             one row per (valid day, lead, method): sums and 2x2 counts
     BASIN_REF_desk.json        the same scored only where the desk's NDFD grid has data (Area: Desk grid area)
     BASIN_chances.json         reliability bins of the page's P34/P48/P64
     BASIN_storm.json           hazard lines, peaks and the low track (storm_verify.py rows)
   Every score is computed here from summed counts, so any period pools correctly.
   State lives in the URL hash so a view can be shared. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var BASINS = { natl: "North Atlantic", npac: "North Pacific" };
  var REFS = [
    ["analysis", "Analysis", "GDAS + IFS mean"], ["gdas", "GDAS", "GDAS analysis"], ["ifs", "IFS", "ECMWF analysis"],
    ["ascat", "ASCAT", "ASCAT"], ["buoys", "Buoys", "moored buoys"], ["ships+buoys", "Ships + buoys", "ships and buoys"]
  ];
  var GRID = { analysis: 1, gdas: 1, ifs: 1, ascat: 1 };
  var METHODS = [
    { k: "windcore", name: "Core Lifted", sub: "blend + 5 kt in storm cores, gale cores to 34 kt", c: "--m-windcore", ours: 1 },
    { k: "blend", name: "Blend, no core lift", c: "--m-blend", ours: 1 },
    { k: "nomem", name: "Deterministic blend", sub: "no members", c: "--m-nomem", ours: 1 },
    { k: "mean3", name: "3-model average", c: "--m-mean3" },
    { k: "gfs", name: "GFS", c: "--m-gfs" },
    { k: "ecmwf", name: "ECMWF", c: "--m-ecmwf" },
    { k: "aifs", name: "AIFS", c: "--m-aifs" },
    { k: "gefs_mean", name: "GEFS mean", c: "--m-gfs", dash: 1 },
    { k: "ens_mean", name: "ENS mean", c: "--m-ecmwf", dash: 1 },
    { k: "aifsens_mean", name: "AIFS ENS mean", c: "--m-aifs", dash: 1 },
    { k: "ndfd", name: "Desk grids", sub: "NDFD as issued", c: "--m-ndfd" }
  ];
  var MBY = {}; METHODS.forEach(function (m) { MBY[m.k] = m; });
  var LEADS = [24, 48, 72, 96, 120];
  var HOURS = [0, 6, 12, 18];
  var hh = function (h) { return (h < 10 ? "0" : "") + h; };
  // Rows carry their valid hour ("hour" column); data written before it was added has none.
  function hourOk(T, i) { return st.hour === "all" || !T.hour || T.hour[i] === +st.hour; }

  function ratio(a, b) { return function (s) { var d = b(s); return d > 0 ? a(s) / d : null; }; }
  function f(k) { return function (s) { return s[k] || 0; }; }
  function sum() { var ks = arguments; return function (s) { var t = 0; for (var i = 0; i < ks.length; i++) t += s[ks[i]] || 0; return t; }; }
  var pct = function (v) { return Math.round(100 * v) + "%"; };
  var kt = function (v) { return (v > 0 ? "+" : "") + v.toFixed(1); };
  var kt0 = function (v) { return v.toFixed(1); };
  var x2 = function (v) { return v.toFixed(2) + "×"; };

  // key, short label, chart label, value, which way is better, format, needs gridded truth, events count
  var METRICS = [
    { k: "bias", label: "Bias", unit: "kt", long: "Bias, all points (kt, + too strong)", v: ratio(f("bias"), f("n")), better: "zero", fmt: kt },
    { k: "mae25", label: "Miss at 25+", unit: "kt", long: "Average miss where 25+ kt (kt)", v: ratio(f("ae25"), f("n25")), better: "low", fmt: kt0 },
    { k: "bias25", label: "Bias at 25+", unit: "kt", long: "Bias where 25+ kt (kt)", v: ratio(f("bias25"), f("n25")), better: "zero", fmt: kt, chartOnly: 1 },
    { k: "rmse", label: "RMS error", unit: "kt", long: "RMS error, all points (kt)", v: function (s) { return s.n ? Math.sqrt(s.se / s.n) : null; }, better: "low", fmt: kt0, chartOnly: 1 }
  ];
  [[34, "Gale"], [48, "Storm"], [64, "HF"]].forEach(function (t) {
    var h = "h" + t[0], m = "m" + t[0], fa = "f" + t[0];
    METRICS.push({ k: "c" + t[0], group: t[1], label: "Caught", long: t[1] + " caught (%)", v: ratio(f(h), sum(h, m)), better: "high", fmt: pct, ev: sum(h, m) });
    METRICS.push({ k: "fa" + t[0], group: t[1], label: "False alarms", long: t[1] + " false alarms (%)", v: ratio(f(fa), sum(h, fa)), better: "low", fmt: pct });
    if (t[0] < 64) METRICS.push({ k: "a" + t[0], group: t[1], label: "Area", long: t[1] + " area, forecast ÷ observed", v: ratio(sum(h, fa), sum(h, m)), better: "one", fmt: x2 });
    METRICS.push({ k: "csi" + t[0], group: t[1], label: "CSI", long: t[1] + " critical success index", v: ratio(f(h), sum(h, m, fa)), better: "high", fmt: function (v) { return v.toFixed(2); }, chartOnly: 1 });
  });
  [[48, "Storm peaks"], [64, "HF peaks"]].forEach(function (t) {
    var h = "t" + t[0] + "h", m = "t" + t[0] + "m", fa = "t" + t[0] + "f";
    METRICS.push({ k: "tc" + t[0], group: t[1], label: "Caught", long: t[1] + " caught, 5° boxes (%)", v: ratio(f(h), sum(h, m)), better: "high", fmt: pct, grid: 1, ev: sum(h, m), chartOnly: t[0] === 64 });
    METRICS.push({ k: "tfa" + t[0], group: t[1], label: "False alarms", long: t[1] + " false alarms, 5° boxes (%)", v: ratio(f(fa), sum(h, fa)), better: "low", fmt: pct, grid: 1, chartOnly: t[0] === 64 });
  });
  METRICS.push({ k: "pk", group: "Storm peaks", label: "Peak off by", unit: "kt", long: "Strongest wind in the box, forecast minus seen (kt)", v: ratio(f("pk_sum"), f("pk_n")), better: "zero", fmt: kt, grid: 1 });
  var MET = {}; METRICS.forEach(function (m) { MET[m.k] = m; });

  var st = { basin: "natl", ref: "analysis", lead: "all", hour: "all", area: "box", from: null, to: null, preset: "last30", metric: "tc48", thr: 48,
             on: { windcore: 1, blend: 1, nomem: 1, gfs: 1, ecmwf: 1, aifs: 1, ndfd: 1 } };
  var idx = null, cache = {};

  // ------------------------------------------------------------------ state <-> URL
  function readHash() {
    var h = location.hash.replace(/^#/, "");
    h.split("&").forEach(function (kv) {
      var p = kv.split("="); if (p.length !== 2) return;
      var v = decodeURIComponent(p[1]);
      if (p[0] === "on") { st.on = {}; v.split(",").forEach(function (k) { if (MBY[k]) st.on[k] = 1; }); }
      else if (p[0] === "thr") st.thr = +v;
      else if (p[0] in st) st[p[0]] = v;
    });
  }
  function writeHash() {
    var h = ["basin", "ref", "lead", "hour", "area", "preset", "metric", "thr"].map(function (k) { return k + "=" + encodeURIComponent(st[k]); });
    if (st.preset === "custom") h.push("from=" + st.from, "to=" + st.to);
    h.push("on=" + Object.keys(st.on).join(","));
    history.replaceState(null, "", "#" + h.join("&"));
  }

  // ------------------------------------------------------------------ data
  function load(name) {
    if (!cache[name]) cache[name] = fetch("data/" + name + ".json", { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(r.status); return r.json();
    }).catch(function () { return null; });
    return cache[name];
  }
  var refFile = function (b, r, a) { return b + "_" + r.replace("+", "_") + (a === "desk" ? "_desk" : ""); };

  function ymd(d) { return d.getUTCFullYear() * 10000 + (d.getUTCMonth() + 1) * 100 + d.getUTCDate(); }
  function toDate(n) { n = +n; return new Date(Date.UTC(Math.floor(n / 10000), Math.floor(n / 100) % 100 - 1, n % 100)); }
  function iso(n) { var s = String(n); return s.slice(0, 4) + "-" + s.slice(4, 6) + "-" + s.slice(6, 8); }
  function fromIso(s) { return s ? +s.replace(/-/g, "") : null; }
  function addDays(n, k) { var d = toDate(n); d.setUTCDate(d.getUTCDate() + k); return ymd(d); }
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function nice(n) { var d = toDate(n); return d.getUTCDate() + " " + MON[d.getUTCMonth()] + " " + d.getUTCFullYear(); }

  function presets() {
    var b = idx.basins[st.basin]; if (!b) return [];
    var first = +b.first, last = +b.last, out = [
      ["last7", "Last 7 days", addDays(last, -6), last], ["last30", "Last 30 days", addDays(last, -29), last],
      ["last90", "Last 90 days", addDays(last, -89), last], ["last365", "Last 365 days", addDays(last, -364), last]];
    for (var y = Math.floor(first / 10000) - 1; y <= Math.floor(last / 10000); y++) {
      var yy = String(y + 1).slice(2);
      [["winter" + y, "Winter " + y + "-" + yy + " (Dec-Feb)", y * 10000 + 1201, (y + 1) * 10000 + 228],
       ["cold" + y, "Cold season " + y + "-" + yy + " (Oct-Mar)", y * 10000 + 1001, (y + 1) * 10000 + 331],
       ["warm" + (y + 1), "Warm season " + (y + 1) + " (Apr-Sep)", (y + 1) * 10000 + 401, (y + 1) * 10000 + 930]].forEach(function (p) {
        if (p[3] >= first && p[2] <= last) out.push(p);
      });
    }
    out.push(["all", "All days", first, last], ["custom", "Custom", null, null]);
    return out;
  }

  function aggregate(D, keep, by) {
    // D: columnar file; keep(i) -> bool; by(i) -> group key. Returns {group: {method: sums + days}}
    var out = {}, cols = D.cols.filter(function (c) { return c !== "valid" && c !== "lead" && c !== "method" && c !== "hour"; });
    var n = D.valid.length;
    for (var i = 0; i < n; i++) {
      if (!keep(i)) continue;
      var g = by(i), mk = D.methods[D.method[i]];
      var G = out[g] || (out[g] = {});
      var s = G[mk] || (G[mk] = { _days: {} });
      for (var j = 0; j < cols.length; j++) { var v = D[cols[j]][i]; if (v != null) s[cols[j]] = (s[cols[j]] || 0) + v; }
      s._days[D.valid[i]] = 1;
    }
    return out;
  }

  // ------------------------------------------------------------------ controls
  function seg(el, items, cur, onpick) {
    el.innerHTML = "";
    items.forEach(function (it) {
      var b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio"); b.dataset.v = it[0];
      b.innerHTML = it[1] + (it[2] ? " <small>" + it[2] + "</small>" : "");
      b.setAttribute("aria-checked", String(String(it[0]) === String(cur)));
      if (it[3]) b.disabled = true;
      b.onclick = function () { onpick(it[0]); };
      el.appendChild(b);
    });
  }

  function buildControls() {
    var b = idx.basins[st.basin] || { referees: [] };
    if (b.referees.indexOf(st.ref) < 0) st.ref = "analysis";
    Array.prototype.forEach.call($("basin").children, function (x) {
      x.setAttribute("aria-checked", String(x.dataset.v === st.basin));
      x.disabled = !idx.basins[x.dataset.v];
      x.onclick = function () { st.basin = x.dataset.v; refresh(); };
    });
    seg($("ref"), REFS.map(function (r) { return [r[0], r[1], "", b.referees.indexOf(r[0]) < 0]; }), st.ref, function (v) { st.ref = v; refresh(); });
    seg($("lead"), [["all", "All"]].concat(LEADS.map(function (l) { return [String(l), "+" + l + " h"]; })), st.lead, function (v) { st.lead = v; refresh(); });
    var hrs = b.hours || (b.hour != null ? [b.hour] : HOURS);
    if (st.hour !== "all" && hrs.indexOf(+st.hour) < 0) st.hour = "all";
    seg($("hour"), [["all", "All"]].concat(HOURS.map(function (h) { return [String(h), hh(h), "UTC", hrs.indexOf(h) < 0]; })), st.hour, function (v) { st.hour = v; refresh(); });
    var areas = b.areas || ["box"];
    if (areas.indexOf(st.area) < 0) st.area = "box";
    seg($("area"), [["box", "Whole chart box"], ["desk", "Desk grid area", "", areas.indexOf("desk") < 0]], st.area, function (v) { st.area = v; refresh(); });
    var ps = presets(), sel = $("preset");
    sel.innerHTML = ps.map(function (p) { return '<option value="' + p[0] + '">' + p[1] + "</option>"; }).join("");
    if (!ps.some(function (p) { return p[0] === st.preset; })) st.preset = "last30";
    sel.value = st.preset;
    var p = ps.filter(function (x) { return x[0] === st.preset; })[0];
    if (p && p[2] != null) { st.from = Math.max(p[2], +b.first); st.to = Math.min(p[3], +b.last); }
    if (st.from == null) { st.from = addDays(+b.last, -29); st.to = +b.last; }
    $("from").value = iso(st.from); $("to").value = iso(st.to);
    $("from").min = $("to").min = iso(b.first); $("from").max = $("to").max = iso(b.last);
    var mets = METRICS.filter(function (m) { return !m.grid || GRID[st.ref]; });
    if (!MET[st.metric] || (MET[st.metric].grid && !GRID[st.ref])) st.metric = GRID[st.ref] ? "tc48" : "c34";
    $("metric").innerHTML = mets.map(function (m) { return '<option value="' + m.k + '">' + m.long + "</option>"; }).join("");
    $("metric").value = st.metric;
    $("chips").innerHTML = "";
    METHODS.forEach(function (m) {
      var c = document.createElement("button");
      c.type = "button"; c.className = "chip"; c.setAttribute("aria-pressed", String(!!st.on[m.k]));
      c.innerHTML = swatch(m) + m.name;
      c.onclick = function () { if (st.on[m.k]) delete st.on[m.k]; else st.on[m.k] = 1; drawCharts(); writeHash(); c.setAttribute("aria-pressed", String(!!st.on[m.k])); };
      $("chips").appendChild(c);
    });
    seg($("thr"), [[34, "Gale 34+"], [48, "Storm 48+"], [64, "HF 64+"]], st.thr, function (v) { st.thr = v; drawChances(); writeHash(); buildThr(); });
  }
  function buildThr() { Array.prototype.forEach.call($("thr").children, function (x) { x.setAttribute("aria-checked", String(+x.dataset.v === st.thr)); }); }

  function color(m) { return getComputedStyle(document.documentElement).getPropertyValue(m.c).trim(); }
  function swatch(m) { return '<i class="swatch' + (m.dash ? " dash" : "") + '" style="background:' + color(m) + ";color:" + color(m) + '"></i>'; }

  // ------------------------------------------------------------------ table
  var D = null;
  function inPeriod(i) { var v = D.valid[i]; return v >= st.from && v <= st.to && hourOk(D, i); }
  function inLead(i) { return st.lead === "all" || D.lead[i] === +st.lead; }

  function bestOf(m, vals) {
    var ok = vals.filter(function (v) { return v != null; }); if (!ok.length) return null;
    var score = function (v) { return m.better === "high" ? -v : m.better === "low" ? v : m.better === "one" ? Math.abs(v - 1) : Math.abs(v); };
    return ok.reduce(function (a, b) { return score(b) < score(a) ? b : a; });
  }

  function drawTable() {
    var t = $("table");
    if (!D) { t.innerHTML = '<tbody><tr><td class="na">No scores for this truth source and area yet.</td></tr></tbody>'; $("tableSub").textContent = ""; return; }
    var agg = aggregate(D, function (i) { return inPeriod(i) && inLead(i); }, function () { return "x"; }).x || {};
    var cols = METRICS.filter(function (m) { return !m.chartOnly && (!m.grid || GRID[st.ref]); });
    var ref = agg.windcore || agg.blend || {};
    var groups = [], h1 = "<tr class='group'><th></th>", h2 = "<tr><th>Model or blend</th>";
    cols.forEach(function (m, j) {
      var g = m.group || "";
      if (!groups.length || groups[groups.length - 1].g !== g) groups.push({ g: g, n: 0, j: j });
      groups[groups.length - 1].n++;
    });
    groups.forEach(function (g) {
      var ev = cols[g.j].ev ? cols[g.j].ev(ref) : null;
      h1 += '<th colspan="' + g.n + '" class="sep">' + (g.g ? g.g + (ev != null ? "<small>" + ev.toLocaleString() + (GRID[st.ref] ? (cols[g.j].grid ? " boxes" : " cells") : " obs") + " seen</small>" : "") : "Wind") + "</th>";
    });
    cols.forEach(function (m, j) {
      var first = groups.some(function (g) { return g.j === j; });
      h2 += '<th class="' + (first ? "sep" : "") + '">' + m.label + (m.unit ? "<small>" + m.unit + "</small>" : "") + "</th>";
    });
    h1 += '<th class="sep"></th></tr>'; h2 += '<th class="sep">Days</th></tr>';
    var rows = METHODS.filter(function (m) { return agg[m.k]; });
    var best = cols.map(function (m) { return bestOf(m, rows.map(function (r) { return m.v(agg[r.k]); })); });
    var body = rows.map(function (r) {
      var s = agg[r.k];
      var tds = cols.map(function (m, j) {
        var v = m.v(s), first = groups.some(function (g) { return g.j === j; });
        var cls = (first ? "sep " : "") + (v == null ? "na" : (v === best[j] && rows.length > 1 ? "best" : ""));
        return '<td class="' + cls + '">' + (v == null ? "–" : m.fmt(v)) + "</td>";
      }).join("");
      return '<tr class="' + (r.ours ? "ours" : "") + '"><td><span class="mname">' + swatch(r) + r.name + (r.sub ? ' <span class="muted">' + r.sub + "</span>" : "") + "</span></td>" + tds +
        '<td class="sep">' + Object.keys(s._days).length + "</td></tr>";
    }).join("");
    t.innerHTML = "<thead>" + h1 + h2 + "</thead><tbody>" + (body || '<tr><td class="na" colspan="20">No scores in this period.</td></tr>') + "</tbody>";
    var rname = REFS.filter(function (r) { return r[0] === st.ref; })[0][2];
    $("tableSub").textContent = BASINS[st.basin] + ", valid " + (st.hour === "all" ? "all scored hours" : hh(+st.hour) + " UTC") + ", against " + rname + ", " +
      nice(st.from) + " to " + nice(st.to) + ", " + (st.lead === "all" ? "all leads +24 to +120 h" : "+" + st.lead + " h") + ".";
    var n = (agg.windcore || agg.blend || {}).n || 0;
    $("tableFoot").textContent = (n ? n.toLocaleString() + (GRID[st.ref] ? " cell" : " ob") + " comparisons per model. " : "") +
      "Underlined: the best in the column (bias and peak error nearest 0, area nearest 1). Caught and false alarms go together: a model that catches more by overdoing the wind shows it in false alarms and area.";
  }

  // ------------------------------------------------------------------ charts
  var NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }

  function lineChart(box, xs, xlabels, series, met, opts) {
    var plot = box.querySelector(".plot"); plot.innerHTML = "";
    var W = opts.w || 420, H = 230, L = 46, R = 12, T = 10, B = 26;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": met.long }, plot);
    var vals = []; series.forEach(function (s) { s.v.forEach(function (v) { if (v != null && isFinite(v)) vals.push(v); }); });
    if (!vals.length) { el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = "Nothing to show for this choice."; return; }
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (met.better === "zero") { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (met.better === "one") { lo = Math.min(lo, 1); hi = Math.max(hi, 1); }
    if (met.fmt === pct) { lo = Math.max(0, lo); hi = Math.min(1, hi); }
    if (hi - lo < 1e-6) { hi += 0.5; lo -= 0.5; }
    var pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    if (met.fmt === pct) { lo = Math.max(0, lo); hi = Math.min(1, hi); }
    var x0 = xs[0], x1 = xs[xs.length - 1]; if (x1 === x0) { x0 -= 1; x1 += 1; }
    var X = function (x) { return L + (x - x0) / (x1 - x0) * (W - L - R); };
    var Y = function (y) { return T + (hi - y) / (hi - lo) * (H - T - B); };
    var g = el("g", { class: "grid" }, svg), ax = el("g", { class: "axis" }, svg);
    var step = niceStep((hi - lo) / 4);
    for (var y = Math.ceil(lo / step) * step; y <= hi; y += step) {
      el("line", { x1: L, x2: W - R, y1: Y(y), y2: Y(y) }, g);
      el("text", { x: L - 6, y: Y(y) + 3, "text-anchor": "end" }, ax).textContent = met.fmt === pct ? Math.round(y * 100) + "%" : (Math.abs(y) < 1e-9 ? "0" : +y.toFixed(2));
    }
    var refY = met.better === "zero" ? 0 : met.better === "one" ? 1 : null;
    if (refY != null) el("line", { x1: L, x2: W - R, y1: Y(refY), y2: Y(refY), class: "zero" }, svg);
    var every = Math.max(1, Math.ceil(xs.length / (opts.ticks || 8)));
    xs.forEach(function (x, i) { if (i % every === 0 || xs.length <= 6) el("text", { x: X(x), y: H - 8, "text-anchor": "middle" }, ax).textContent = xlabels[i]; });
    series.forEach(function (s) {
      var d = "", pen = false;
      s.v.forEach(function (v, i) {
        if (v == null || !isFinite(v)) { pen = false; return; }
        d += (pen ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(v).toFixed(1); pen = true;
      });
      var p = el("path", { d: d, class: "series", stroke: s.color }, svg);
      if (s.dash) p.setAttribute("stroke-dasharray", "5 4");
      s.v.forEach(function (v, i) {
        var lone = v != null && isFinite(v) && (i === 0 || s.v[i - 1] == null) && (i === s.v.length - 1 || s.v[i + 1] == null);
        if (lone || xs.length <= 6) { if (v != null && isFinite(v)) el("circle", { cx: X(xs[i]), cy: Y(v), r: 3.5, fill: s.color, stroke: "#0f1829", "stroke-width": 2 }, svg); }
      });
    });
    // hover: crosshair + values of every line at the nearest x
    var hl = el("line", { y1: T, y2: H - B, class: "hover-line", visibility: "hidden" }, svg);
    var tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; plot.appendChild(tip);
    var hit = el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, svg);
    function move(ev) {
      var r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W;
      var i = 0, bd = Infinity; xs.forEach(function (x, j) { var d = Math.abs(X(x) - px); if (d < bd) { bd = d; i = j; } });
      hl.setAttribute("x1", X(xs[i])); hl.setAttribute("x2", X(xs[i])); hl.setAttribute("visibility", "visible");
      var rows = series.map(function (s) { return [s, s.v[i]]; }).filter(function (q) { return q[1] != null && isFinite(q[1]); });
      rows.sort(function (a, b) { return b[1] - a[1]; });
      tip.innerHTML = "<b>" + (opts.tipX ? opts.tipX(i) : xlabels[i]) + "</b>" + rows.map(function (q) {
        return '<div class="row">' + swatch(q[0].m) + "<span>" + q[0].m.name + "</span><span>" + met.fmt(q[1]) + "</span></div>";
      }).join("") + (opts.tipExtra ? opts.tipExtra(i) : "");
      tip.hidden = false;
      var tx = X(xs[i]) / W * r.width;
      tip.style.left = Math.min(tx + 12, r.width - tip.offsetWidth - 4) + "px";
      tip.style.top = "8px";
    }
    hit.addEventListener("mousemove", move);
    hit.addEventListener("mouseleave", function () { tip.hidden = true; hl.setAttribute("visibility", "hidden"); });
  }
  function niceStep(raw) {
    var p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
    return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
  }

  function drawCharts() {
    var met = MET[st.metric];
    var shown = METHODS.filter(function (m) { return st.on[m.k]; });
    if (!D) { lineChart($("chartLead"), [], [], [], met, {}); lineChart($("chartTime"), [], [], [], met, {}); return; }
    var byLead = aggregate(D, inPeriod, function (i) { return D.lead[i]; });
    lineChart($("chartLead"), LEADS, LEADS.map(function (l) { return "+" + l + " h"; }), shown.map(function (m) {
      return { m: m, color: color(m), dash: m.dash, v: LEADS.map(function (l) { var s = byLead[l] && byLead[l][m.k]; return s ? met.v(s) : null; }) };
    }), met, { w: 420 });
    // week by week (or month by month for long periods), pooled counts
    var span = (toDate(st.to) - toDate(st.from)) / 864e5, monthly = span > 200;
    var key = function (v) {
      if (monthly) return Math.floor(v / 100) * 100 + 1;
      var d = toDate(v); d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7); return ymd(d);
    };
    var byT = aggregate(D, function (i) { return inPeriod(i) && inLead(i); }, function (i) { return key(D.valid[i]); });
    var ts = Object.keys(byT).map(Number).sort();
    var xs = ts.map(function (t) { return toDate(t) / 864e5; });
    $("timeCap").textContent = (monthly ? "Month by month" : "Week by week") + ", " + (st.lead === "all" ? "all leads" : "+" + st.lead + " h");
    var ev = met.ev || (MET[st.metric.replace(/^(fa|a|csi)/, "c")] || {}).ev || (MET[st.metric.replace(/^tfa/, "tc")] || {}).ev;
    lineChart($("chartTime"), xs, ts.map(function (t) { var d = toDate(t); return monthly ? MON[d.getUTCMonth()] + " " + String(d.getUTCFullYear()).slice(2) : d.getUTCDate() + " " + MON[d.getUTCMonth()]; }), shown.map(function (m) {
      return { m: m, color: color(m), dash: m.dash, v: ts.map(function (t) { var s = byT[t][m.k]; return s ? met.v(s) : null; }) };
    }), met, {
      w: 840, ticks: 10,
      tipX: function (i) { return (monthly ? "" : "Week of ") + nice(ts[i]).replace(monthly ? /^1 / : /$/, ""); },
      tipExtra: function (i) { var s = byT[ts[i]].windcore || byT[ts[i]].blend; return ev && s ? '<div class="row muted"><span>' + ev(s) + " seen</span></div>" : ""; }
    });
  }

  // ------------------------------------------------------------------ chances
  function drawChances() {
    load(st.basin + "_chances").then(function (C) {
      var plot = $("chartRel").querySelector(".plot"), t = $("chanceTable");
      var ri = C ? C.referees.indexOf(st.ref) : -1;
      if (!C || ri < 0) { plot.innerHTML = ""; t.innerHTML = '<tbody><tr><td class="na">No chance scores yet.</td></tr></tbody>'; return; }
      var keep = function (i) { return C.referee[i] === ri && C.thr[i] === st.thr && C.valid[i] >= st.from && C.valid[i] <= st.to && hourOk(C, i); };
      var bins = [], byLead = {};
      for (var b = 0; b < 10; b++) bins.push({ n: 0, e: 0, p: 0 });
      for (var i = 0; i < C.valid.length; i++) {
        if (!keep(i)) continue;
        var L = byLead[C.lead[i]] || (byLead[C.lead[i]] = { n: 0, ev: 0, bs: 0, hn: 0, he: 0 });
        L.n += C.n[i]; L.ev += C.events[i]; L.bs += C.bs[i];
        for (var k = 5; k < 10; k++) { L.hn += C["n" + k][i]; L.he += C["e" + k][i]; }
        if (st.lead !== "all" && C.lead[i] !== +st.lead) continue;
        for (b = 0; b < 10; b++) { bins[b].n += C["n" + b][i]; bins[b].e += C["e" + b][i]; bins[b].p += C["p" + b][i]; }
      }
      // reliability: forecast chance (x) vs how often it happened (y), bins with 10+ cases
      plot.innerHTML = "";
      var W = 420, H = 300, Lm = 46, R = 12, T = 10, B = 30;
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Reliability of the chances" }, plot);
      var X = function (v) { return Lm + v * (W - Lm - R); }, Y = function (v) { return T + (1 - v) * (H - T - B); };
      var g = el("g", { class: "grid" }, svg), ax = el("g", { class: "axis" }, svg);
      for (var q = 0; q <= 1.001; q += 0.2) {
        el("line", { x1: Lm, x2: W - R, y1: Y(q), y2: Y(q) }, g);
        el("text", { x: Lm - 6, y: Y(q) + 3, "text-anchor": "end" }, ax).textContent = Math.round(q * 100) + "%";
        el("text", { x: X(q), y: H - 12, "text-anchor": "middle" }, ax).textContent = Math.round(q * 100) + "%";
      }
      el("text", { x: (Lm + W - R) / 2, y: H, "text-anchor": "middle", class: "lbl" }, svg).textContent = "Chance the page gave";
      el("line", { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), class: "zero", "stroke-dasharray": "4 4" }, svg);
      var pts = bins.map(function (bn, j) { return bn.n >= 10 ? { x: bn.p / bn.n, y: bn.e / bn.n, n: bn.n, e: bn.e, j: j } : null; }).filter(Boolean);
      var blue = color(MBY.windcore), seen = bins.reduce(function (a, bn) { return a + bn.e; }, 0);
      if (pts.length && seen) {
        el("path", { d: pts.map(function (p, j) { return (j ? "L" : "M") + X(p.x).toFixed(1) + " " + Y(p.y).toFixed(1); }).join(""), class: "series", stroke: blue }, svg);
        var tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; plot.appendChild(tip);
        pts.forEach(function (p) {
          var c = el("circle", { cx: X(p.x), cy: Y(p.y), r: 4.5, fill: blue, stroke: "#0f1829", "stroke-width": 2 }, svg);
          var hit = el("circle", { cx: X(p.x), cy: Y(p.y), r: 12, fill: "transparent" }, svg);
          hit.addEventListener("mouseenter", function () {
            tip.innerHTML = "<b>Said " + (p.j * 10) + "–" + (p.j * 10 + 10) + "% (avg " + Math.round(p.x * 100) + "%)</b>Happened " + Math.round(p.y * 100) + "%<div class='muted'>" +
              p.e.toLocaleString() + " of " + p.n.toLocaleString() + (GRID[st.ref] ? " cells" : " obs") + "</div>";
            tip.hidden = false; var r = svg.getBoundingClientRect();
            tip.style.left = Math.min(X(p.x) / W * r.width + 12, r.width - tip.offsetWidth - 4) + "px"; tip.style.top = (Y(p.y) / H * r.height - 10) + "px";
          });
          hit.addEventListener("mouseleave", function () { tip.hidden = true; });
        });
      } else el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = pts.length ? "None seen at this force in this period." : "Too few cases in this period.";
      var rows = LEADS.filter(function (l) { return byLead[l]; }).map(function (l) {
        var s = byLead[l], base = s.ev / s.n, bss = base > 0 && base < 1 ? 1 - (s.bs / s.n) / (base * (1 - base)) : null;
        return "<tr><td>+" + l + " h</td><td>" + s.ev.toLocaleString() + "</td><td>" + (bss == null ? "–" : bss.toFixed(2)) + "</td><td>" +
          (s.hn ? pct(s.he / s.hn) + ' <span class="muted">of ' + s.hn.toLocaleString() + "</span>" : "–") + "</td></tr>";
      }).join("");
      t.innerHTML = "<thead><tr><th>Lead</th><th>Seen<small>" + (GRID[st.ref] ? "cells" : "obs") + "</small></th><th>Brier skill<small>1 perfect, 0 none</small></th><th>Said 50%+<small>how often it happened</small></th></tr></thead><tbody>" +
        (rows || '<tr><td class="na" colspan="4">No chance scores in this period.</td></tr>') + "</tbody>";
    });
  }

  // ------------------------------------------------------------------ storm layers
  function drawStorm() {
    load(st.basin + "_storm").then(function (S) {
      var ref = st.ref === "ascat" ? "ascat" : "analysis";
      $("stormSub").textContent = "Hazard lines and the ensemble low track, against " + (ref === "ascat" ? "ASCAT" : "the GDAS + IFS analysis") +
        (st.ref !== ref ? " (they are scored against ASCAT and the analysis only)" : "") + ". Same period" + (st.lead === "all" ? "" : " and lead") + " as above.";
      if (!S) { $("hazTable").innerHTML = $("trackTable").innerHTML = ""; return; }
      var ri = S.referees.indexOf(ref);
      var P = function (name) { return S.products.indexOf(name); };
      var keep = function (i) { return S.valid[i] >= st.from && S.valid[i] <= st.to && hourOk(S, i); };
      var hz = { gale: [0, 0, 0], warn_gale: [0, 0, 0], storm: [0, 0, 0], warn_storm: [0, 0, 0], hf: [0, 0, 0], warn_hf: [0, 0, 0] }, tr = {};
      for (var i = 0; i < S.valid.length; i++) {
        if (!keep(i)) continue;
        var prod = S.products[S.product[i]];
        if (prod === "track") {
          var t = tr[S.lead[i]] || (tr[S.lead[i]] = { h: 0, m: 0, fa: 0, e: 0, p: 0 });
          t.h += S.hit[i]; t.m += S.miss[i]; t.fa += S.fa[i]; t.e += S.err_km[i] || 0; t.p += S.dp_hpa[i] || 0;
        } else if (hz[prod] && S.referee[i] === ri && (st.lead === "all" || S.lead[i] === +st.lead)) {
          hz[prod][0] += S.hit[i]; hz[prod][1] += S.miss[i]; hz[prod][2] += S.fa[i];
        }
      }
      var names = { gale: "Gale possible", storm: "Storm possible", hf: "Hurricane force possible",
                    warn_gale: "Gale warning area", warn_storm: "Storm warning area", warn_hf: "Hurricane force warning area" };
      $("hazTable").innerHTML = "<thead><tr><th>Line</th><th>Inside<small>of obs at the force</small></th><th>Verified<small>of outlined cells</small></th><th>Area<small>outlined ÷ observed</small></th><th>Seen<small>cells at the force</small></th></tr></thead><tbody>" +
        Object.keys(hz).filter(function (k) { return k.indexOf("warn_") || hz[k][0] + hz[k][1] + hz[k][2]; }).map(function (k) {
          var h = hz[k][0], m = hz[k][1], fa = hz[k][2];
          return "<tr><td>" + names[k] + "</td><td>" + (h + m ? pct(h / (h + m)) : "–") + "</td><td>" + (h + fa ? pct(h / (h + fa)) : "–") + "</td><td>" +
            (h + m ? x2((h + fa) / (h + m)) : "–") + "</td><td>" + (h + m).toLocaleString() + "</td></tr>";
        }).join("") + "</tbody>";
      $("trackTable").innerHTML = "<thead><tr><th>Low track</th><th>Lows matched</th><th>Position error<small>km</small></th><th>In cone<small>aim 2 in 3</small></th><th>Pressure<small>hPa, + too weak</small></th><th>No analysed low<small>within 1000 km</small></th></tr></thead><tbody>" +
        LEADS.filter(function (l) { return tr[l] && (tr[l].h + tr[l].m + tr[l].fa); }).map(function (l) {
          var t = tr[l], n = t.h + t.m;
          return "<tr><td>+" + l + " h</td><td>" + n + "</td><td>" + (n ? Math.round(t.e / n) : "–") + "</td><td>" + (n ? pct(t.h / n) : "–") + "</td><td>" +
            (n ? kt(t.p / n) : "–") + "</td><td>" + t.fa + "</td></tr>";
        }).join("") + "</tbody>";
    });
  }

  // ------------------------------------------------------------------ notes
  function drawNote() {
    var notes = [];
    if (st.basin === "natl" && st.from <= 20260331 && st.to >= 20251101)
      notes.push("This period overlaps winter 2025-26 (Nov to Mar), when the core likelihood was trained on Atlantic ASCAT and the blend was tuned. Core Lifted and blend scores there flatter them.");
    var db = idx.basins[st.basin] || {};
    if (st.area === "desk") notes.push("Desk grids are the NDFD oceanic grids as issued: the full update about 10 UTC after the 00 UTC runs and about 22 UTC after the 12 UTC runs, so the desk had about 10 hours more to work with than the model run each is paired with. Every method here is scored only where the desk grid has data, so they can be compared. Scored at 00 and 12 UTC valid only" +
      (db.desk_first ? ", from " + nice(db.desk_first) : "") + ".");
    else if (st.on.ndfd) notes.push("Desk grids are scored in the Desk grid area view.");
    // Days re-scored on or after 17 Oct 2026 are rebuilt with the page's current recipe; runs saved
    // live (forecast records, from mid-October 2026) are scored as they ran, so 16 Oct and before used the old one.
    if (st.to >= 20261010 && st.from <= 20261016) notes.push("The page changed on 17 Oct 2026: gale and storm chances adjusted to ASCAT, AIFS at half weight in the blend, and Core Lifted raised to 34 kt in gale cores. Earlier days are scored as the page is now (rebuilt from the models), except runs saved live from mid-October to 16 Oct, which are scored as they ran with the old recipe.");
    if (st.from < 20250815 && st.on.aifsens_mean) notes.push("The AIFS ensemble is on AWS only from August 2025, so the AIFS ENS mean has fewer days.");
    if (st.basin === "npac" && st.ref === "ascat") notes.push("ASCAT sees different parts of the Pacific at the four hours (about 17,000 cells a day at 06 UTC, 9,000 at 18, 8,000 at 00 and under 1,000 at 12), so an hour with few cells counts for little.");
    $("note").hidden = !notes.length; $("note").innerHTML = notes.join("<br>");
  }

  function refresh() {
    buildControls(); writeHash(); drawNote();
    load(refFile(st.basin, st.ref, st.area)).then(function (d) {
      D = d;
      drawTable(); drawCharts();
    });
    drawChances(); drawStorm();
  }

  // ------------------------------------------------------------------ boot
  function wire() {
    $("preset").onchange = function () { st.preset = this.value; if (st.preset === "custom") { st.from = fromIso($("from").value); st.to = fromIso($("to").value); } refresh(); };
    $("from").onchange = $("to").onchange = function () {
      var a = fromIso($("from").value), b = fromIso($("to").value); if (!a || !b) return;
      st.preset = "custom"; st.from = Math.min(a, b); st.to = Math.max(a, b); refresh();
    };
    $("metric").onchange = function () { st.metric = this.value; drawCharts(); writeHash(); };
    var open = function (on) { $("about").hidden = !on; $("scrim").hidden = !on; $("about-btn").setAttribute("aria-expanded", String(on)); };
    $("about-btn").onclick = function () { open($("about").hidden); };
    $("about-close").onclick = $("scrim").onclick = function () { open(false); };
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") open(false); });
  }

  readHash();
  if (st.preset === "custom") { st.from = +st.from || null; st.to = +st.to || null; } else { st.from = st.to = null; }
  wire();
  load("index").then(function (i) {
    idx = i;
    if (!idx || !Object.keys(idx.basins).length) {
      document.querySelector("main").innerHTML = '<section class="card"><p class="sub">No verification scores have been published yet.</p></section>';
      return;
    }
    if (!idx.basins[st.basin]) st.basin = Object.keys(idx.basins)[0];
    $("updated").textContent = "Updated " + idx.updated.replace("T", " ").replace("Z", " UTC");
    refresh();
  });
})();
