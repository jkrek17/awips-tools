/* Scatterometer: ASCAT winds (RSS, NESDIS Metop-B, KNMI Metop-C, STAR coastal) over the two OPC basins, set against the marine wind page's
   Best Wind grid (34/48/64 kt) and warning lines. The page asks one question, "How did yesterday's Best Wind forecast compare with ASCAT?":
   a plain 2-3 line answer for the chosen 12 h mosaic (areas seen against drawn, ratio 0.8-1.25 = "about right"; clusters of at least 4
   seen cells at the level that the cell's own forecast had below it = misses, found here from the mosaic .bin), a map of right / missed /
   too much at a chosen level (Gale 34, Storm 48, HF 64), a strip of the week's 14 mosaics coloured by the storm-level verdict, and under
   "More" the single-pass view (Passes) and the OSCAT-3 switch. OSCAT-3 is never scored. The default forecast is the one made 24 h earlier.
   Reads data/index.json, data/mosaic/*.bin and data/pass/*.bin (written by marine_wind/scat/build.py, published with the site).
   Shared globe kit: ../globe-kit/. Plain ES2020.

   Mosaic .bin, index format 2 (gzip, little-endian): uint32 n; uint32 idx[n]; uint8 obs[n], dir[n], flag[n] as below;
   uint8 pass[n] (index into the entry's passes list); then for latest, f24, f48: uint8 grid[n], warn[n] of the cell's own
   pass (255 none); then for each lead whose entry fc has a cycle, over the basin box at V (entry.box: iy0, ny, ix0, nx;
   rows north first, columns west first): uint8 grid[ny*nx] (kt, 255 none), warn[ny*nx] (bits, 255 none).

   Pass .bin (gzip, little-endian): uint32 n; uint32 idx[n] (global 0.25 deg cell, iy * 1440 + ix, ascending);
   uint8 obs[n] (kt), dir[n] (deg / 2), flag[n] (1 = rain-flagged); then for latest, f24, f48:
   uint8 grid[n] (kt, 255 none), warn[n] (bits 1 gale, 2 storm, 4 HF; 255 none). */
(function () {
  "use strict";
  var K, map = null, ov = null, index = null;
  var $ = function (id) { return document.getElementById(id); };
  var NX = 1440, NY = 721, RES = 0.25, TILE = 256;
  var LEADS = [["latest", "Latest run"], ["f24", "24 h earlier"], ["f48", "48 h earlier"]];   // the order of the .bin files: do not reorder
  var LEADS_UI = ["f24", "latest", "f48"];
  var BASIN = { atl: { name: "Atlantic", start: [-45, 45], mobile: [-45, 42] }, pac: { name: "Pacific", start: [175, 45], mobile: [175, 42] } };
  var LEVELS = [[34, "gale", "#fbbf24", 7], [48, "storm", "#f97316", 6], [64, "HF", "#e879f9", 4]];
  var WIND = { // the marine wind page's 10 m wind scale
    stops: [0, 10, 15, 20, 25, 30, 34, 41, 48, 56, 64, 80],
    colors: ["#1b1d21", "#1f2a36", "#22364b", "#28466a", "#2f5a8a", "#3f74ab", "#e8d27a", "#e8a93f", "#e06f2e", "#c9372c", "#9b1f5e", "#c86fd8"]
  };
  var state = { tab: "mosaic", basin: "atl", lead: "f24", level: 48, winds: false, pass: null, v: null, oscat: false, focus: null, older: false, layers: { scat: true, best: true, warn: true } };

  // ----------------------------------------------------------------- hash
  function readHash() {
    var h = new URLSearchParams(location.hash.replace(/^#/, ""));
    state.tab = h.get("tab") === "passes" || (!h.get("tab") && h.get("pass")) ? "passes" : "mosaic";
    state.v = h.get("v") || null;
    state.oscat = h.get("oscat") === "1";
    state.winds = h.get("winds") === "1";
    if (["34", "48", "64"].indexOf(h.get("level")) >= 0) state.level = +h.get("level");
    if (BASIN[h.get("basin")]) state.basin = h.get("basin");
    if (LEADS.some(function (l) { return l[0] === h.get("lead"); })) state.lead = h.get("lead");
    state.pass = h.get("pass") || null;
    state.older = h.get("older") === "1";
  }
  function writeHash() {
    var h = "#tab=" + state.tab + "&basin=" + state.basin + "&lead=" + state.lead + "&level=" + state.level + (state.v ? "&v=" + state.v : "") + (state.winds ? "&winds=1" : "") + (state.oscat ? "&oscat=1" : "") +
      (state.pass ? "&pass=" + encodeURIComponent(state.pass) : "") + (state.older ? "&older=1" : "");
    try { history.replaceState(null, "", h); } catch (e) { /* the hash stays as it was */ }
  }

  // ------------------------------------------------------------- formats
  function basinOf(p) { return /pac/i.test(p.basin) ? "pac" : "atl"; }
  function satShort(s) { return /^RSS /.test(s) ? s.slice(4) + " (RSS)" : s; }
  function isAscat(p) { return /^(RSS )?Metop/.test(p.sat); }
  var RSS_NOTE = "NESDIS Metop-B arrives about an hour after the pass; RSS (Metop-B and -C) replaces it 2 to 5 days later. KNMI Metop-C (via NASA PO.DAAC) arrives about 2.5-4 hours after the pass.";
  function hhmm(d) { return K.pad(d.getUTCHours()) + ":" + K.pad(d.getUTCMinutes()) + "Z"; }
  function dayTime(iso) { var d = new Date(iso); return K.DAYS[d.getUTCDay()] + " " + d.getUTCDate() + " " + hhmm(d); }
  function dayHour(iso) { var d = new Date(iso); return K.pad(d.getUTCHours()) + "Z " + K.DAYS[d.getUTCDay()] + " " + d.getUTCDate() + " " + K.MONS[d.getUTCMonth()]; }
  function cycleDate(c) { return new Date(Date.UTC(+c.slice(0, 4), +c.slice(4, 6) - 1, +c.slice(6, 8), +c.slice(8, 10))).toISOString(); }
  function ago(iso) {
    var h = (Date.now() - new Date(iso).getTime()) / 3600000;
    return h < 1 ? Math.max(0, Math.round(h * 60)) + " min ago" : h < 48 ? h.toFixed(1).replace(/\.0$/, "") + " h ago" : Math.round(h / 24) + " days ago";
  }
  function leadWords(l) { return l === "latest" ? "latest-run" : leadName(l); }
  function leadName(l) { return l === "latest" ? "Latest run" : l === "f24" ? "24 h earlier" : "48 h earlier"; }
  function plural(n, w) { return n + " " + (n === 1 ? w : w === "pass" ? "passes" : w + "s"); }
  function num(n) { return Math.round(n).toLocaleString("en-US"); }
  function ratio(g, o) { return o > 0 ? g / o : null; }
  function vKey(iso) { return iso.replace(/[-:TZ]/g, "").slice(0, 10); }
  function hourDiff(a, b) { return Math.abs(new Date(a) - new Date(b)) / 3600000; }
  function h1(x) { return x.toFixed(1).replace(/\.0$/, ""); }
  function pct(x) { return x > 0 && x < 0.005 ? "<1" : String(Math.round(100 * x)); }

  // --------------------------------------------------------- pass data
  var cache = {}, cur = null;   // cur: the decoded selected pass
  function gunzip(buf) {
    var u = new Uint8Array(buf);
    if (!(u[0] === 0x1f && u[1] === 0x8b)) return Promise.resolve(buf);      // a server may have unzipped it
    var s = new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip")));
    return s.arrayBuffer();
  }
  function decode(buf) {
    var dv = new DataView(buf), n = dv.getUint32(0, true), o = 4, out = { n: n, leads: {} };
    out.idx = new Uint32Array(buf.slice(o, o + 4 * n)); o += 4 * n;
    out.obs = new Uint8Array(buf, o, n); o += n;
    out.dir = new Uint8Array(buf, o, n); o += n;
    out.flag = new Uint8Array(buf, o, n); o += n;
    LEADS.forEach(function (l) {
      if (o + 2 * n <= buf.byteLength) { out.leads[l[0]] = { grid: new Uint8Array(buf, o, n), warn: new Uint8Array(buf, o + n, n) }; o += 2 * n; }
    });
    return out;
  }
  function loadPass(p) {
    if (!cache[p.id + p.basin]) {
      cache[p.id + p.basin] = fetch("data/" + p.file).then(function (r) { if (!r.ok) throw new Error(p.file + " " + r.status); return r.arrayBuffer(); }).then(gunzip).then(decode);
    }
    return cache[p.id + p.basin];
  }

  function decodeM(buf, m) {
    var dv = new DataView(buf), n = dv.getUint32(0, true), o = 4, out = { n: n, mosaic: true, entry: m, leads: {}, boxCells: null };
    out.idx = new Uint32Array(buf.slice(o, o + 4 * n)); o += 4 * n;
    out.obs = new Uint8Array(buf, o, n); o += n;
    out.dir = new Uint8Array(buf, o, n); o += n;
    out.flag = new Uint8Array(buf, o, n); o += n;
    out.pass = new Uint8Array(buf, o, n); o += n;
    out.cell = {};
    LEADS.forEach(function (l) { out.cell[l[0]] = { grid: new Uint8Array(buf, o, n), warn: new Uint8Array(buf, o + n, n) }; o += 2 * n; });
    var sz = m.box.ny * m.box.nx;
    LEADS.forEach(function (l) {
      if (m.fc[l[0]] && m.fc[l[0]].cycle && o + 2 * sz <= buf.byteLength) { out.leads[l[0]] = { grid: new Uint8Array(buf, o, sz), warn: new Uint8Array(buf, o + sz, sz) }; o += 2 * sz; }
    });
    out.members = m.passes.map(function (id) { return index.passes.filter(function (p) { return p.id === id && basinOf(p) === basinOf(m); })[0] || null; });
    return out;
  }
  function loadMosaic(m) {
    if (!cache[m.file]) {
      cache[m.file] = fetch("data/" + m.file).then(function (r) { if (!r.ok) throw new Error(m.file + " " + r.status); return r.arrayBuffer(); }).then(gunzip).then(function (b) { var d = decodeM(b, m); decoded[m.file] = d; return d; });
    }
    return cache[m.file].then(function (d) { return d; });
  }

  // dense 0.25 degree arrays of the selected pass, for the tiles, lines, barbs and readout
  var obsD = new Uint8Array(NX * NY).fill(255), dirD = new Uint8Array(NX * NY), flagD = new Uint8Array(NX * NY);
  var gridD = new Uint8Array(NX * NY).fill(255), warnD = new Uint8Array(NX * NY).fill(255);
  var passD = new Uint8Array(NX * NY), posD = new Int32Array(NX * NY);
  var clsD = new Uint8Array(NX * NY);   // mosaic verdict per cell: 0 none, 1 right, 2 missed, 3 too much, 4 seen below the level
  function clearDense() {
    if (!cur) return;
    for (var i = 0; i < cur.n; i++) { var k = cur.idx[i]; obsD[k] = 255; flagD[k] = 0; gridD[k] = 255; warnD[k] = 255; clsD[k] = 0; }
    if (cur.boxCells) for (var j = 0; j < cur.boxCells.length; j++) { gridD[cur.boxCells[j]] = 255; warnD[cur.boxCells[j]] = 255; }
  }
  function fillObs() {
    var i, k;
    if (cur.mosaic) {   // OSCAT-3 cells stay unset while it is switched off
      for (i = 0; i < cur.n; i++) {
        k = cur.idx[i]; obsD[k] = 255;
        var q = cur.members[cur.pass[i]];
        if (!state.oscat && q && q.sat === "OSCAT-3") continue;
        obsD[k] = cur.obs[i]; dirD[k] = cur.dir[i]; flagD[k] = cur.flag[i]; passD[k] = cur.pass[i]; posD[k] = i;
      }
      return;
    }
    for (i = 0; i < cur.n; i++) { k = cur.idx[i]; obsD[k] = cur.obs[i]; dirD[k] = cur.dir[i]; flagD[k] = cur.flag[i]; }
  }
  function fillLead() {
    if (cur.mosaic) { fillBox(); fillClass(); return; }
    var L = cur && state.lead && selected() && selected().fc[state.lead] ? cur.leads[state.lead] : null;
    for (var i = 0; i < cur.n; i++) { var k = cur.idx[i]; gridD[k] = L ? L.grid[i] : 255; warnD[k] = L ? L.warn[i] : 255; }
  }
  // right / missed / too much at the chosen level, on the cells ASCAT saw (each against the forecast its own pass was given)
  function fillClass() {
    var C = cur.entry.fc[state.lead] && cur.entry.fc[state.lead].cycle ? cur.cell[state.lead] : null, T = state.level;
    for (var i = 0; i < cur.n; i++) {
      var c = 0;
      if (C && isScored(cur, i)) { var g = C.grid[i], o = cur.obs[i]; if (g !== 255) c = o >= T ? (g >= T ? 1 : 2) : (g >= T ? 3 : 4); }
      clsD[cur.idx[i]] = c;
    }
  }
  // the lead's Best Wind and warning bytes over the whole basin box, into the dense arrays
  function fillBox() {
    var j, B = cur.entry.box, L = cur.entry.fc[state.lead] ? cur.leads[state.lead] : null, cells = [];
    if (cur.boxCells) for (j = 0; j < cur.boxCells.length; j++) { gridD[cur.boxCells[j]] = 255; warnD[cur.boxCells[j]] = 255; }
    if (L) {
      for (var r = 0; r < B.ny; r++) {
        for (var c = 0; c < B.nx; c++) {
          var o = r * B.nx + c, g = L.grid[o];
          if (g === 255) continue;
          var k = (B.iy0 + r) * NX + (B.ix0 + c) % NX;
          gridD[k] = g; warnD[k] = L.warn[o]; cells.push(k);
        }
      }
    }
    cur.boxCells = Uint32Array.from(cells);
  }

  // ------------------------------------------------------------- selection
  function basinPasses() { return index.passes.filter(function (p) { return basinOf(p) === state.basin; }); }
  function selected() { return state.pass ? index.passes.filter(function (p) { return p.id === state.pass && basinOf(p) === state.basin; })[0] || null : null; }

  function basinMosaics() { return (index.mosaics || []).filter(function (m) { return basinOf(m) === state.basin; }); }   // newest first
  function selectedM() { return state.v ? basinMosaics().filter(function (m) { return vKey(m.valid) === state.v; })[0] || null : null; }
  function leadOK(l) {
    if (state.tab === "mosaic") { var m = selectedM(); return !m || !!m.fc[l]; }
    var p = selected(); return !p || !!p.fc[l];
  }
  function curHasLead() { return !!(cur && (cur.mosaic ? cur.entry.fc[state.lead] && cur.entry.fc[state.lead].cycle : selected() && selected().fc[state.lead])); }
  function mScore(m, L) { return (m.score_ascat || m.score)[L]; }   // OSCAT-3 is never scored
  function mCoverage(m) { var n = (m.sats && m.sats.ASCAT) || 0; return m.water ? n / m.water : 0; }

  // ---------------------------------------------------------------- card
  function areaLine(p) {
    var s = p.score[state.lead];
    if (!s) return '<span class="dim">no ' + leadWords(state.lead) + ' forecast for this pass</span>';
    return [34, 48, 64].map(function (t, i) { return "<span><em>" + t + "</em> <b>" + s.obs[i] + "</b>/" + s.grid[i] + "</span>"; }).join("");
  }
  function rowHTML(p) {
    var s = p.score[state.lead];
    return '<button type="button" class="prow" role="listitem" data-id="' + p.id + '" aria-current="' + (p.id === state.pass) + '">' +
      '<div class="l1"><span>' + dayTime(p.mid) + '</span><span class="sat">' + satShort(p.sat) + '</span><span class="mx">' + Math.round(p.obs_max) + " / " + (s ? Math.round(s.grid_max) : "&ndash;") + " kt</span></div>" +
      '<div class="l2">' + areaLine(p) + "</div></button>";
  }
  function renderList() {
    var ps = basinPasses(), box = $("passes"), cut = Date.now() - 24 * 3600000;
    var recent = ps.filter(function (p) { return new Date(p.start).getTime() >= cut; }), older = ps.filter(function (p) { return recent.indexOf(p) < 0; });
    var sel = selected(), showOld = state.older || !recent.length;
    var list = showOld ? ps : recent;
    box.innerHTML = list.length ? list.map(rowHTML).join("") : '<p class="empty">No ' + BASIN[state.basin].name + ' passes yet. The page fills in after the first STAR files are processed, about 3 to 4 h after a pass.</p>';
    var ob = $("older");
    ob.hidden = !older.length || (!recent.length);
    ob.textContent = showOld ? "Show last 24 h only" : "Older (" + older.length + ", to 7 days)";
    $("listNote").textContent = showOld ? "last 7 days" : "last 24 h";
    box.querySelectorAll(".prow").forEach(function (b) { b.addEventListener("click", function () { choose(b.dataset.id); }); });
  }

  var OSCAT_NOTE = '<p class="warnnote">OSCAT-3 reads low at high winds: against ASCAT it ran about 3 kt low at 20-34 kt, 5 kt low at 34-48 kt and 15-20 kt low above 48 kt (few storms), and saw a tenth of ASCAT\'s storm area (13 Oct-7 Nov 2026). A grid above OSCAT in a storm is not necessarily too high; judge storm and HF by ASCAT.</p>';
  function scoreText(p, L) { return scoreWords(p.score[L]) + (p.sat === "OSCAT-3" ? OSCAT_NOTE : ""); }
  function scoreWords(s) {
    var parts = [];
    var om = Math.round(s.obs_max), gm = Math.round(s.grid_max);
    var out = "<p>Highest wind: observed <b>" + om + " kt</b>, grid <b>" + gm + " kt</b>" +
      (gm === om ? "." : " (grid " + Math.abs(gm - om) + " kt " + (gm > om ? "high" : "low") + ").") + "</p>";
    if (!s.obs[0] && !s.grid[0]) out += "<p>No gale-force wind in the observed cells or the grid.</p>";
    else {
      for (var i = 0; i < 3; i++) {
        var T = [34, 48, 64][i], r = ratio(s.grid[i], s.obs[i]), nm = i === 0 ? "gale" : i === 1 ? "storm" : "HF";
        if (r === null) parts.push(s.grid[i] ? "<b>" + plural(s.grid[i], "cell") + "</b> of " + nm + " where none was seen" : "no " + nm + " in either");
        else if (s.obs[i] < 10) parts.push(nm + ": only " + plural(s.obs[i], "cell") + " seen, too little to judge");
        else { var v = areaVerdict(Math.max(s.obs[i], MIN_SEEN), s.grid[i] * Math.max(s.obs[i], MIN_SEEN) / s.obs[i]); parts.push("<b>" + nm + "</b> " + (v.k === "ok" ? "about right" : "drawn " + v.words)); }
      }
      out += "<p>Best Wind: " + parts.join("; ") + ".</p>";
      var cp = [];
      for (var j = 0; j < 3; j++) {
        var o = s.obs[j], c = s.catch[j], lab = j === 0 ? "observed gale cells" : j === 1 ? "storm" : "HF";
        if (!o) { cp.push("no observed " + (j === 0 ? "gale cells" : j === 1 ? "storm" : "HF") + " to catch"); continue; }
        cp.push(o < 10 ? "<b>" + c + " of " + o + "</b> " + lab : "<b>" + Math.round(100 * c / o) + "%</b> of " + lab);
      }
      out += "<p>Warning lines covered " + cp.join(", ") + ".</p>";
    }
    return out;
  }
  function renderDetail() {
    var p = selected(), box = $("detail");
    if (!p) { box.innerHTML = ""; return; }
    var s = new Date(p.start), e = new Date(p.end), L = state.lead, f = p.fc[L], sc = p.score[L];
    var h = "<h3>" + satShort(p.sat) + ", " + dayTime(p.mid) + "</h3>" +
      "<p>Passed between " + hhmm(s) + " and " + hhmm(e) + " (STAR posts the file time, so this is a bracket). " + num(p.n) + " cells over the " + BASIN[basinOf(p)].name + " box" +
      (p.flagged ? ", " + num(p.flagged) + " flagged for rain" : "") + ".</p>";
    if (!f || !sc) {
      h += '<p class="warnp">No ' + leadWords(L) + ' forecast for this pass' + (L === "f48" || L === "f24" ? ": that model run was not saved yet. The " + leadWords(L) + " comparison fills in as saved runs build up (+48 h takes two days after the page starts)." : ": no saved run falls within 6 to 54 h of the pass.") + "</p>";
    } else {
      var dh = Math.abs(new Date(f.valid) - new Date(p.mid)) / 3600000;
      var cyc = cycleDate(f.cycle), cd = new Date(cyc);
      h += "<p>Forecast: <b>" + dayHour(cyc).replace(/^(\d\dZ) (\S+ \d+ \S+)$/, "$1 $2") + " run</b>" + (L === "latest" ? " (the run the desk had), +" + f.step + " h" : ", +" + f.step + " h") +
        ", valid <b>" + dayHour(f.valid) + "</b>, " + (dh < 0.5 ? "at the pass time" : (dh < 10 ? dh.toFixed(1).replace(/\.0$/, "") : Math.round(dh)) + " h from the pass") + ".</p>";
      h += '<div class="scores">' + scoreText(p, L) + "</div>";
      h += '<table class="mini"><tr><th></th><th>Observed</th><th>Grid</th><th>In lines</th><th>Caught</th></tr>' +
        LEVELS.map(function (lv, i) {
          return "<tr><td>" + lv[0] + " kt</td><td>" + sc.obs[i] + "</td><td>" + sc.grid[i] + "</td><td>" + sc.line[i] + "</td><td>" + sc.catch[i] + "</td></tr>";
        }).join("") + "</table><p class=\"fine\" style=\"font-size:11px;color:var(--text-3)\">Counts are 0.25&deg; cells without a rain flag (one cell is about 550 sq km at 45N). Lines: gale = any warning line, storm = storm or HF line, HF = HF line.</p>";
    }
    box.innerHTML = h;
  }

  // 7-day summary: pooled over the passes, per lead and satellite group
  function groupSum(ps, L, test) {
    var g = { n: 0, obs: [0, 0, 0], grid: [0, 0, 0], catch: [0, 0, 0] };
    ps.forEach(function (p) {
      var s = p.score[L];
      if (!s || !test(p)) return;
      g.n++;
      for (var i = 0; i < 3; i++) { g.obs[i] += s.obs[i]; g.grid[i] += s.grid[i]; g.catch[i] += s.catch[i]; }
    });
    return g;
  }
  function renderSummary() {
    var ps = basinPasses(), rows = "";
    LEADS.forEach(function (l) {
      [["ASCAT (B + C)", isAscat], ["OSCAT-3", function (p) { return !isAscat(p); }]].forEach(function (grp, gi) {
        var g = groupSum(ps, l[0], grp[1]);
        var cells = "<td>" + g.n + "</td>";
        for (var i = 0; i < 3; i++) { var r = ratio(g.grid[i], g.obs[i]); cells += "<td>" + (r === null ? "&ndash;" : r.toFixed(2)) + "<small>" + num(g.obs[i]) + "</small></td>"; }
        for (var j = 0; j < 3; j++) cells += "<td>" + (g.obs[j] ? Math.round(100 * g.catch[j] / g.obs[j]) + "%" : "&ndash;") + "<small>" + num(g.obs[j]) + "</small></td>";
        rows += "<tr>" + (gi === 0 ? '<td rowspan="2" class="lead">' + l[1] + "</td>" : "") + "<td>" + grp[0] + "</td>" + cells + "</tr>";
      });
    });
    $("summary").innerHTML = '<p class="sumnote" style="margin-top:8px">' + BASIN[state.basin].name + ", " + plural(ps.length, "pass") + " in the last 7 days, pooled (cells summed over passes, rain-flagged cells left out). Under each figure: observed cells.</p>" +
      '<div class="sw-scroll"><table class="mini" id="sumtab"><tr><th rowspan="2">Forecast</th><th rowspan="2">Satellite</th><th rowspan="2">Passes</th><th colspan="3">Grid / observed area</th><th colspan="3">Line catch</th></tr>' +
      "<tr><th>34</th><th>48</th><th>64</th><th>34</th><th>48</th><th>64</th></tr>" + rows + "</table></div>" +
      '<p class="sumnote">Ratio above 1 means the grid has more area than the satellite saw. Catch is the share of observed cells (34 kt in any line, 48 kt in a storm or HF line, 64 kt in an HF line). OSCAT-3 reads well below ASCAT at gale force and above (storm area about a tenth of ASCAT\'s, 13 Oct-7 Nov 2026), so its ratios over-state the grid; judge storm and HF by the ASCAT rows.</p>';
  }

  // ---- the plain answer: right / missed / too much at a level, clusters of misses, verdict words
  var MIN_SEEN = 50, MIN_CLUSTER = 4;
  var NAME = { 34: "gale", 48: "storm", 64: "HF" }, LIDX = { 34: 0, 48: 1, 64: 2 };
  var scratch = new Uint8Array(NX * NY), posS = new Int32Array(NX * NY);
  function round5(x) { return Math.max(5, Math.round(x / 5) * 5); }
  function cap1(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function isScored(d, i) { var q = d.members[d.pass[i]]; return !!q && isAscat(q) && !d.flag[i]; }   // ASCAT only, no rain flag: OSCAT-3 is never scored
  function latLonText(lat, lon) { var w = ((lon + 540) % 360) - 180; return Math.round(Math.abs(lat)) + (lat < 0 ? "S" : "N") + " " + Math.round(Math.abs(w)) + (w < 0 ? "W" : "E"); }
  // connected clusters (8 neighbours, wrapping at the date line) of the cells ASCAT saw at or above T where the cell's own forecast was below T
  function missClusters(d, C, T) {
    var cells = [], i, k, res = [];
    for (i = 0; i < d.n; i++) {
      if (!isScored(d, i)) continue;
      var g = C.grid[i];
      if (d.obs[i] >= T && g !== 255 && g < T) { k = d.idx[i]; scratch[k] = 1; posS[k] = i; cells.push(i); }
    }
    for (var a = 0; a < cells.length; a++) {
      k = d.idx[cells[a]];
      if (scratch[k] !== 1) continue;
      scratch[k] = 2;
      var stack = [k], n = 0, sy = 0, sx = 0, ix0 = k % NX, pobs = -1, pgrid = 0;
      while (stack.length) {
        var c = stack.pop(), iy = (c / NX) | 0, ix = c - iy * NX, dx = ix - ix0;
        if (dx > NX / 2) dx -= NX; else if (dx < -NX / 2) dx += NX;
        n++; sy += iy; sx += dx;
        var pi = posS[c];
        if (d.obs[pi] > pobs) { pobs = d.obs[pi]; pgrid = C.grid[pi]; }
        for (var ey = -1; ey <= 1; ey++) {
          var ny = iy + ey; if (ny < 0 || ny >= NY) continue;
          for (var ex = -1; ex <= 1; ex++) {
            if (!ey && !ex) continue;
            var nk = ny * NX + ((ix + ex + NX) % NX);
            if (scratch[nk] === 1) { scratch[nk] = 2; stack.push(nk); }
          }
        }
      }
      if (n >= MIN_CLUSTER) res.push({ n: n, lat: 90 - (sy / n) * RES, lon: (ix0 + sx / n) * RES - 180, peak: pobs, grid: pgrid });
    }
    for (a = 0; a < cells.length; a++) scratch[d.idx[cells[a]]] = 0;
    return res.sort(function (x, y) { return y.n - x.n; });
  }
  function analyze(d, lead) {   // null when the mosaic has no such forecast
    d.an = d.an || {};
    if (!(lead in d.an)) {
      var F = d.entry.fc[lead], out = null;
      if (F && F.cycle) { out = { miss: {} }; [34, 48, 64].forEach(function (T) { out.miss[T] = missClusters(d, d.cell[lead], T); }); }
      d.an[lead] = out;
    }
    return d.an[lead];
  }
  function areaVerdict(o, g) {   // seen cells at a level and the Best Wind cells on those same cells
    if (o < MIN_SEEN) return { k: "few" };
    var r = g / o;
    if (r >= 0.8 && r <= 1.25) return { k: "ok", r: r };
    if (r > 1.25) return { k: "big", r: r, words: r >= 2.5 ? "about " + Math.round(r) + " times as big" : r >= 1.8 ? "about twice as big" : "about " + round5((r - 1) * 100) + "% too big" };
    return { k: "small", r: r, words: "about " + round5((1 - r) * 100) + "% too small" };
  }
  function clause(T, v, first) {   // "Gale area about right", "storm drawn about 40% too big", "too little storm seen to judge"
    var nm = NAME[T], c;
    if (v.k === "few") c = "too little " + nm + " seen to judge";
    else if (v.k === "ok") c = nm + " area about right";
    else c = nm + " drawn " + v.words;
    return first ? cap1(c) : c;
  }
  function areasSentence(sc) {
    var Ts = [34, 48, 64], vs = Ts.map(function (T) { return areaVerdict(sc.obs[LIDX[T]], sc.grid[LIDX[T]]); }), parts = [], first = true;
    var judged = vs.map(function (v, i) { return i < 2 || v.k !== "few"; });   // HF only when there is enough of it
    if (vs[0].k === "ok" && vs[1].k === "ok") { parts.push("Gale and storm areas about right"); first = false; if (judged[2]) parts.push(clause(64, vs[2], false)); }
    else Ts.forEach(function (T, i) { if (judged[i]) { parts.push(clause(T, vs[i], first)); first = false; } });
    var bad = vs.some(function (v, i) { return judged[i] && (v.k === "big" || v.k === "small"); });
    var good = vs.some(function (v) { return v.k === "ok"; });
    return { text: parts.join("; ") + ".", tone: bad ? "amber" : good ? "green" : "grey" };
  }
  function missSentence(an, sc, T) {
    var cl = an.miss[T], nm = NAME[T], word = T === 64 ? "HF" : nm;
    if (!cl.length) return { text: sc.obs[LIDX[T]] ? "Nothing missed at " + (T === 64 ? "HF" : nm + " force") + "." : "No " + (T === 64 ? "HF" : nm + "-force") + " winds seen.", tone: "green" };
    function one(c) { return latLonText(c.lat, c.lon) + " (" + c.peak + " kt seen, grid " + c.grid + ")"; }
    if (cl.length === 1) return { text: "Missed one " + word + " area near " + one(cl[0]) + ".", tone: "red" };
    return { text: "Missed " + cl.length + " " + word + " areas. Biggest near " + one(cl[0]) + (cl[1] ? " and " + one(cl[1]) : "") + ".", tone: "red" };
  }
  function leadPhrase(l) { return l === "latest" ? "latest-run forecast" : l === "f24" ? "24-hour forecast" : "48-hour forecast"; }
  function leadShort(l) { return l === "latest" ? "Latest run" : l === "f24" ? "24 h" : "48 h"; }
  function mHasLead(m, l) { return !!(m && m.fc[l] && m.fc[l].cycle && (m.score_ascat || m.score || {})[l]); }
  function curMatches() { var m = selectedM(); return !!(m && cur && cur.mosaic && cur.entry === m); }
  function renderAnswer() {
    var box = $("answer"), m = selectedM(), L = state.lead, bn = BASIN[state.basin].name;
    if (!m) { box.innerHTML = '<p class="a-line">No ' + bn + ' map for this time: no ASCAT pass fell in its 12 hours.</p>'; return; }
    if (!mHasLead(m, L)) {
      var alts = LEADS_UI.filter(function (l) { return l !== L && mHasLead(m, l); }).map(function (l) { return [l]; });
      box.innerHTML = '<p class="a-line"><i class="dot grey"></i>There is no ' + leadPhrase(L) + ' for this map.</p>' +
        (alts.length ? '<p class="a-alt">Try ' + alts.map(function (l) { return '<button type="button" class="chip" data-lead="' + l[0] + '">' + (l[0] === "latest" ? "the latest run" : "the " + leadShort(l[0]) + " forecast") + "</button>"; }).join(" or ") + ".</p>" : "<p class=\"a-alt\">No forecast was saved for this map.</p>");
      box.querySelectorAll(".chip").forEach(function (b) { b.addEventListener("click", function () { setLead(b.dataset.lead); }); });
      return;
    }
    var sc = (m.score_ascat || m.score)[L], T = state.level, cov = mCoverage(m);
    var h = '<p class="a-line a-cov"><i class="dot ' + (cov < 0.2 ? "amber" : "grey") + '"></i>ASCAT saw <b>' + pct(cov) + "%</b> of the " + bn + "." + (m.open ? ' <span class="badge">still filling</span>' : "") + "</p>";
    var a = areasSentence(sc);
    h += '<p class="a-line"><i class="dot ' + a.tone + '"></i>' + a.text + "</p>";
    if (curMatches()) {
      var an = analyze(cur, L);
      if (an) { var ms = missSentence(an, sc, T); h += '<p class="a-line"><i class="dot ' + ms.tone + '"></i>' + ms.text + "</p>"; }
    } else h += '<p class="a-line dim"><i class="dot grey"></i>Looking for misses&hellip;</p>';
    box.innerHTML = h;
  }

  // ---- the week: 14 boxes, one per 00Z / 12Z map
  var decoded = {}, stripFor = null, stripToken = 0;
  function boxVerdict(m) {   // storm-level verdict (gale when too little storm was seen); null when this map has no such forecast
    var L = state.lead;
    if (!mHasLead(m, L)) return { c: "none", why: "no " + leadPhrase(L) + " for this map" };
    var d = decoded[m.file], sc = (m.score_ascat || m.score)[L];
    if (!d) return { c: "pend", why: "checking" };
    var an = analyze(d, L), nm = an.miss[48].length;
    if (nm) return { c: "red", why: nm === 1 ? "one storm area missed" : nm + " storm areas missed", miss: nm };
    var v = areaVerdict(sc.obs[1], sc.grid[1]), g = false, nmT = "storm";
    if (v.k === "few") { v = areaVerdict(sc.obs[0], sc.grid[0]); g = true; nmT = "gale"; }
    if (v.k === "few") return { c: "grey", why: "too little seen to judge", miss: 0 };
    return { c: v.k === "ok" ? "green" : "amber", g: g, miss: 0, why: (g ? "too little storm seen; " : "") + nmT + (v.k === "ok" ? " area about right" : " drawn " + v.words) };
  }
  function renderStrip() {
    var ms = basinMosaics(), box = $("strip");
    var newest = (index.mosaics || []).reduce(function (a, m) { return m.valid > a ? m.valid : a; }, "");
    $("weekHead").textContent = BASIN[state.basin].name + ", " + leadShort(state.lead) + (state.lead === "latest" ? "" : " forecast") + ", oldest at the left";
    if (!newest) { box.innerHTML = ""; $("stripKey").innerHTML = ""; return; }
    var byV = {}; ms.forEach(function (m) { byV[m.valid] = m; });
    var t0 = new Date(newest).getTime(), html = "", anyOpen = false;
    for (var i = 13; i >= 0; i--) {
      var t = new Date(t0 - i * 12 * 3600000), iso = t.toISOString().slice(0, 16) + "Z", m = byV[iso], z = t.getUTCHours() === 0 ? "00" : "12";
      var vd = m ? boxVerdict(m) : { c: "none", why: "no pass" };
      if (m && m.open) anyOpen = true;
      var ttl = dayHour(iso) + ": " + vd.why + (m && m.open ? " (still filling)" : "");
      html += '<button type="button" class="sb' + (z === "00" ? " day" : "") + (m && m.open ? " open" : "") + '" data-v="' + vKey(iso) + '"' + (m ? "" : " disabled") + ' aria-current="' + (!!m && vKey(iso) === state.v) + '" title="' + ttl + '" aria-label="' + ttl + '">' +
        '<i class="bx c-' + vd.c + '">' + (vd.g ? "G" : "") + "</i><b>" + z + "Z</b><u>" + t.getUTCDate() + "</u></button>";
    }
    box.innerHTML = html;
    box.querySelectorAll(".sb").forEach(function (b) { b.addEventListener("click", function () { chooseM(b.dataset.v); }); });
    $("stripKey").innerHTML = '<span><i class="sq c-green"></i>about right</span><span><i class="sq c-amber"></i>too big or small</span><span><i class="sq c-red"></i>storm missed</span><span><i class="sq c-grey"></i>too little seen</span><span class="gnote"><b>G</b> judged on gale</span>' + (anyOpen ? '<span><i class="sq open"></i>filling</span>' : "");
    renderWeekSentence();
  }
  function renderWeekSentence() {
    var box = $("weekSent"), L = state.lead, S = index.summary && index.summary[basinKey()];
    S = S && S[L] && S[L].ascat;
    if (!S || !S.mosaics) { box.innerHTML = "This week: no " + leadPhrase(L) + " scored yet."; return; }
    function wk(T) {
      var i = LIDX[T], nm = NAME[T];
      if (!S.enough[i]) return "too little " + nm + " seen to judge";
      var v = areaVerdict(S.obs[i], S.grid[i]);
      return v.k === "ok" ? nm + " area about right" : nm + " drawn too " + (v.k === "big" ? "big" : "small");
    }
    var parts = [wk(34), wk(48)], miss = 0, all = true, ms = basinMosaics().filter(function (m) { return !m.open && mHasLead(m, L); });
    ms.forEach(function (m) { var d = decoded[m.file]; if (!d) { all = false; return; } miss += analyze(d, L).miss[48].length; });
    if (all) parts.push(miss ? miss + " storm miss" + (miss === 1 ? "" : "es") : "no storm misses");
    box.innerHTML = "<b>This week:</b> " + parts.join(", ") + ".";
  }
  function loadStripData() {
    var my = ++stripToken, ms = basinMosaics();
    Promise.all(ms.map(function (m) { return loadMosaic(m).catch(function () { return null; }); })).then(function () { if (my === stripToken && state.tab === "mosaic") { renderStrip(); renderWeek(); } });
  }

  // ---- mosaic card
  function offset(p, v) { return h1(hourDiff(p.mid, v)) + " h from " + K.pad(new Date(v).getUTCHours()) + "Z"; }
  function hrZ(v, d) { return K.pad(new Date(new Date(v).getTime() + d * 3600000).getUTCHours()); }
  function winLabel(v) { return hrZ(v, -6) + "-" + hrZ(v, 6) + "Z"; }
  function validLabel(v) { return dayHour(v) + ", passes " + winLabel(v); }
  function basinKey() { return state.basin === "pac" ? "npac" : "natl"; }
  function lineName(w) { return w === 255 ? "no forecast" : (w & 4) ? "HF line" : (w & 2) ? "storm line" : (w & 1) ? "gale line" : "no line"; }
  function membersOf(m) { return (cur && cur.mosaic && cur.entry === m ? cur.members : m.passes.map(function (id) { return index.passes.filter(function (p) { return p.id === id && basinOf(p) === basinOf(m); })[0] || null; })); }
  function renderMosaicDetail() {
    var m = selectedM(), box = $("mdetail");
    if (!m) { box.innerHTML = '<p class="empty">No ' + BASIN[state.basin].name + ' map for this time: no pass fell in its 12 hours.</p>'; return; }
    var L = state.lead, f = m.fc[L], sc = mScore(m, L), cov = mCoverage(m);
    var A = (m.sats.ASCAT || 0) / m.water, R = (m.sats.RSS || 0) / m.water, N = (m.sats.NESDIS || 0) / m.water, KN = (m.sats.KNMI || 0) / m.water, AS = A - R - N - KN;   // RSS, NESDIS, KNMI, and STAR's coastal ASCAT (what is left of ASCAT)
    var members = membersOf(m);
    var h = "<h3>" + BASIN[state.basin].name + ", valid " + validLabel(m.valid) + "</h3>";
    if (m.open) h += '<p class="warnp">Still filling: STAR posts a pass 3 to 4 h after it flies, so the later passes of these 12 hours are not in yet.</p>';
    var split = [[N, "NESDIS Metop-B"], [KN, "KNMI Metop-C"], [R, "RSS"], [AS, "STAR coastal"]].filter(function (x) { return x[0] > 0; }).map(function (x) { return "<b>" + pct(x[0]) + "%</b> " + x[1]; }).join(", ") || "<b>0%</b> STAR coastal";
    h += "<p>ASCAT saw <b>" + pct(cov) + "%</b> of the basin&rsquo;s water in these 12 hours (" + num(m.sats.ASCAT || 0) + " of " + num(m.water) + " cells): " + split + ". OSCAT-3 is never scored. Unseen water is left uncoloured.</p>" +
      '<div class="covbar" aria-hidden="true"><span style="width:' + (100 * R) + '%;background:#c9821a"></span><span style="width:' + (100 * N) + '%;background:#d9a566"></span><span style="width:' + (100 * KN) + '%;background:#cf8f6b"></span><span style="width:' + (100 * AS) + '%;background:#e8d27a"></span></div>' +
      (R > 0 && !m.open ? "" : '<p class="fine">' + RSS_NOTE + "</p>");
    if (!f || !sc) {
      h += '<p class="warnp">No ' + leadPhrase(L) + " score for this map: " + (L === "latest" ? "no saved run built before the passes falls within 6 to 54 h of them" : "that model run was not saved for most of the passes (the saved runs build up over the days)") + ".</p>";
    } else {
      var v = m.valid, uns = (m.unscored_ascat || {})[L] || 0, NM = ["gale", "storm", "HF"];
      h += "<p>Forecast: " + (f.cycle ? "<b>" + dayHour(cycleDate(f.cycle)) + " run</b>" + (L === "latest" ? " (the run the desk had)" : "") + ", +" + f.step + " h, drawn for <b>" + hrZ(v, 0) + "Z</b>" : "none for " + hrZ(v, 0) + "Z") +
        ". Each cell is scored against the forecast hour nearest its own pass (" + hrZ(v, -6) + ", " + hrZ(v, 0) + " or " + hrZ(v, 6) + "Z).</p>";
      h += "<ul class=\"wkfa\">" + [0, 1, 2].map(function (i) {
        return "<li>" + (sc.obs[i] ? "Warning lines covered <b>" + Math.round(100 * sc.catch[i] / sc.obs[i]) + "%</b> of the " + NM[i] + (i < 2 ? "-force" : "") + " winds seen" : "No " + NM[i] + (i < 2 ? "-force" : "") + " winds seen") + "</li>";
      }).join("") + "</ul>";
      h += '<table class="mini"><tr><th>Level</th><th>Seen</th><th>Best Wind on those cells</th><th>Caught by lines</th><th>Best Wind, whole basin</th></tr>' +
        LEVELS.map(function (lv, i) {
          return "<tr><td>" + lv[0] + " kt</td><td>" + num(sc.obs[i]) + "</td><td>" + num(sc.grid[i]) + "</td><td>" + num(sc.catch[i]) + "</td><td>" + (m.grid_area_box && m.grid_area_box[L] ? num(m.grid_area_box[L][i]) : "&ndash;") + "</td></tr>";
        }).join("") + '</table><p class="fine">Counts are 0.25&deg; cells (about 550 sq km at 45N) that ASCAT saw, without a rain flag: ' + num(sc.n) + " scored of " + num(m.sats.ASCAT || 0) + " seen" +
        (uns ? "; " + num(uns) + " more have no " + leadPhrase(L) + " for their pass and are left out" : "") +
        ". &ldquo;Seen&rdquo; = ASCAT at or above the level; &ldquo;Best Wind on those cells&rdquo; = the grid at or above it on the same cells; &ldquo;caught&rdquo; = seen cells inside the warning line (gale: any line, storm: storm or HF line, HF: HF line). The last column counts the grid&rsquo;s water cells in the whole basin at " + hrZ(v, 0) + "Z, seen or not. Right / missed / too much on the map use the same cells.</p>";
    }
    h += '<table class="mini mtable"><tr><th>Pass</th><th>Middle</th><th>From ' + hrZ(m.valid, 0) + "Z</th></tr>" +
      members.map(function (p, i) {
        if (!p) return "<tr><td>" + m.passes[i] + "</td><td></td><td></td></tr>";
        var off = (new Date(p.mid) - new Date(m.valid)) / 3600000;
        return "<tr" + (p.sat === "OSCAT-3" ? ' style="opacity:.4"' : "") + "><td>" + satShort(p.sat) + (p.sat === "OSCAT-3" ? " (not scored)" : "") + "</td><td>" + hhmm(new Date(p.mid)) + "</td><td>" + (off < 0 ? "&minus;" : "+") + h1(Math.abs(off)) + " h</td></tr>";
      }).join("") + '</table><p class="fine">Where swaths overlap, RSS ASCAT is shown over NESDIS Metop-B and KNMI Metop-C over STAR ASCAT, then the pass nearest the valid time.</p>';
    box.innerHTML = h;
  }

  // ---- 7-day numbers (computed in build.py: index.summary), in the Details fold
  function weekS() {
    var S = index.summary && index.summary[basinKey()];
    S = S && S[state.lead];
    return S ? S.ascat : null;
  }
  function renderWeek() {
    var box = $("week"), S = weekS(), sat = "ASCAT", lw = leadPhrase(state.lead);
    if (!S || !S.times) { box.innerHTML = '<h4>Last 7 days</h4><p class="sumnote">The week&rsquo;s numbers appear once the first 12 h window of this basin has closed.</p>'; return; }
    var oc = [["RSS ASCAT", S.with_rss], ["NESDIS Metop-B", S.with_nesdis], ["KNMI Metop-C", S.with_knmi]].filter(function (x) { return x[1]; }).map(function (x) { return x[1] + " with " + x[0]; });
    var h = '<h4>Last 7 days, ' + BASIN[state.basin].name + ", " + lw + '</h4><p class="sumnote">ASCAT saw on average <b>' + pct(S.cov_mean) + "%</b> of the basin&rsquo;s water per 12 h (" + S.times + " maps, " + pct(S.cov_min) + " to " + pct(S.cov_max) + "%). " +
      (oc.length ? "Of the " + S.times + " maps, " + oc.join(", ") + " (open-ocean swaths); the others have STAR&rsquo;s coastal ASCAT only." : "None of the " + S.times + " maps includes RSS, NESDIS or KNMI open-ocean ASCAT yet.") + " " + RSS_NOTE + "</p>";
    if (!S.mosaics) { box.innerHTML = h + '<p class="sumnote">No ' + lw + ' score yet: the saved runs for most of the passes are not there (they build up over the days).</p>'; return; }
    var NAMES = ["gale", "storm", "HF"], few = '<span class="dim">too little seen to judge</span>';
    h += '<table class="mini wk"><tr><th>Level</th><th>Best Wind area</th><th>Lines caught</th></tr>' +
      LEVELS.map(function (lv, i) {
        var ok = S.enough[i], v = areaVerdict(S.obs[i], S.grid[i]);
        return "<tr><td>" + lv[0] + " kt</td><td>" + (ok ? "<b>" + (v.k === "ok" ? "about right" : "drawn " + v.words) + "</b><small>" + num(S.grid[i]) + " Best Wind / " + num(S.obs[i]) + " seen</small>" : few + "<small>" + num(S.obs[i]) + " seen in " + plural(S.nmos_obs[i], "map") + "</small>") + "</td>" +
          "<td>" + (ok ? "<b>" + Math.round(100 * S.catch[i] / S.obs[i]) + "%</b><small>" + num(S.catch[i]) + " of " + num(S.obs[i]) + "</small>" : few) + "</td></tr>";
      }).join("") + "</table>";
    h += '<p class="sumnote">Cells are 0.25&deg; cells without a rain flag that ASCAT saw; the Best Wind count is on those same cells. Lines caught: the share of the seen cells at the level that lie inside a warning line (gale: any line, storm: storm or HF line, HF: HF line).</p>';
    h += "<h4>Of the line cells ASCAT saw, how many reached the level</h4><ul class=\"wkfa\">" + LEVELS.map(function (lv, i) {
      return "<li>" + (S.enough_line[i] ? "Of " + NAMES[i] + "-line cells ASCAT saw, <b>" + pct(S.catch[i] / S.line[i]) + "%</b> had " + lv[0] + " kt <small>(" + num(S.catch[i]) + " of " + num(S.line[i]) + ")</small>"
        : "<span class=\"dim\">" + NAMES[i] + " line: too little seen (" + num(S.line[i]) + " cells in " + plural(S.nmos_line[i], "map") + ")</span>") + "</li>";
    }).join("") + "</ul>";
    h += "<h4>Strongest winds seen: one per map, top 8 of the week</h4>";
    if (!S.worst.length) h += '<p class="sumnote">None.</p>';
    else {
      h += '<div class="wlist" role="list"><div class="whead" aria-hidden="true"><span>Map</span><span>Seen</span><span>Best Wind there</span><span>Line</span></div>' +
        S.worst.map(function (w, i) {
          return '<button type="button" class="wrow" role="listitem" data-i="' + i + '" title="Show this map and zoom to the strongest cell"><span class="t">' + dayHour(w.valid) + "</span><span><b>" + w.obs + " kt</b></span><span>" + w.grid + " <small>(max " + Math.round(w.grid_max) + ")</small></span><span>" + lineName(w.warn) + "</span></button>";
        }).join("") + '</div><p class="sumnote">Best Wind there: the grid at that cell for its pass, and in brackets the highest grid over all seen cells. Click a row to open the map.</p>';
    }
    box.innerHTML = h;
    box.querySelectorAll(".wrow").forEach(function (b) {
      b.addEventListener("click", function () { var w = S.worst[+b.dataset.i]; chooseM(vKey(w.valid), w.idx); });
    });
  }
  function renderStepper() {
    var ms = basinMosaics(), m = selectedM(), i = ms.indexOf(m);
    $("tLabel").innerHTML = m ? "<b>" + BASIN[state.basin].name + "</b> &middot; " + dayHour(m.valid) + (m.open ? ' <span class="badge">filling</span>' : "") : "&mdash;";
    $("tPrev").disabled = !m || i >= ms.length - 1;
    $("tNext").disabled = !m || i <= 0;
    $("oscatBtn").setAttribute("aria-pressed", String(state.oscat));
    $("windsBtn").setAttribute("aria-pressed", String(state.winds));
    document.querySelectorAll("#levels button").forEach(function (b) { b.setAttribute("aria-pressed", String(+b.dataset.level === state.level)); });
    renderStrip();
  }

  function renderLeads() {
    var p = state.tab === "mosaic" ? selectedM() : selected();
    document.querySelectorAll("#leads button").forEach(function (b) {
      var ok = !p || !!p.fc[b.dataset.lead];
      b.setAttribute("aria-pressed", String(b.dataset.lead === state.lead));
      b.disabled = !ok && b.dataset.lead !== state.lead;
      b.title = ok ? b.title.replace(/ \(.*$/, "") : "Not available for this " + (state.tab === "mosaic" ? "map" : "pass") + " (the saved runs build up over the days)";
    });
    $("leadLabel").textContent = state.tab === "mosaic" ? (state.lead === "latest" ? "Forecast: latest run" : "Forecast made " + leadShort(state.lead) + " earlier") : "Forecast compared";
  }
  function renderTop() {
    var p = selected(), m = selectedM();
    $("card").dataset.tab = state.tab;
    document.querySelectorAll("#basins button").forEach(function (b) { b.setAttribute("aria-checked", String(b.dataset.basin === state.basin)); });
    if (state.tab === "mosaic") {
      $("validEyebrow").textContent = "Valid";
      $("validTime").textContent = m ? dayHour(m.valid) : "—";
      $("validRel").textContent = m ? "passes " + winLabel(m.valid) + " · " + pct(mCoverage(m)) + "% seen" : "";
      $("cardTitle").textContent = "How did yesterday’s Best Wind forecast compare with ASCAT?";
      return;
    }
    $("validEyebrow").textContent = "Pass (mid)";
    $("validTime").textContent = p ? K.fmtValid(p.mid).replace(/:00 UTC$/, "") + ":" + K.pad(new Date(p.mid).getUTCMinutes()) + " UTC" : "—";
    $("validRel").textContent = p ? satShort(p.sat) + " · " + ago(p.mid) : "";
    var ps = basinPasses();
    $("cardTitle").textContent = "Single passes";
    $("passTitle").textContent = BASIN[state.basin].name + (ps.length ? ", " + ps.length + " in 7 days" : "");
  }
  function renderLegend() {
    var box = $("legend"), T = state.level, nm = NAME[T], lv = LEVELS[LIDX[T]];
    var windBar = function () {
      var top = 80;
      return '<div class="bar">' + WIND.colors.map(function (c, i) { return '<span style="background:' + c + ';flex:' + ((WIND.stops[i + 1] || top) - WIND.stops[i]) + '"></span>'; }).join("") + "</div>" +
        '<div class="labs">' + [0, 20, 34, 48, 64, 80].map(function (v) { return '<span style="left:' + (v / top * 100) + '%">' + v + "</span>"; }).join("") + "</div>";
    };
    if (state.tab === "passes") {
      box.innerHTML = windBar() + '<div class="keys"><span>Wind seen, kt (faded: rain flag)</span><span><i style="border-top:3px solid #fff"></i>Best Wind 34/48/64 kt, thin to thick</span>' +
        '<span><i style="border-top:2px dashed ' + LEVELS[0][2] + '"></i>gale <i style="border-top:2px dashed ' + LEVELS[1][2] + '"></i>storm <i style="border-top:2px dashed ' + LEVELS[2][2] + '"></i>HF warning line</span></div>';
      return;
    }
    var line = '<span><i class="ln"></i>' + cap1(nm) + " warning line</span>";
    if (state.winds) {
      box.innerHTML = windBar() + '<div class="keys"><span>ASCAT wind, kt (faded: rain flag)</span><span><i style="border-top:3px solid #fff"></i>Best Wind ' + T + ' kt</span>' + line.replace('class="ln"', 'class="ln" style="border-top-color:' + lv[2] + '"') + "</div>";
      return;
    }
    box.innerHTML = '<ul class="lk">' +
      '<li><i class="sq k-right"></i><b>Right</b> ASCAT and Best Wind both ' + T + ' kt or more</li>' +
      '<li><i class="sq k-miss"></i><b>Missed</b> ASCAT ' + T + ' kt or more, Best Wind lower</li>' +
      '<li><i class="sq k-much"></i><b>Too much</b> Best Wind ' + T + ' kt or more, ASCAT lower</li>' +
      '<li><i class="sq k-below"></i>ASCAT saw it, below ' + T + ' kt</li>' +
      "<li>" + line.replace(/^<span>|<\/span>$/g, "") + "</li>" +
      '<li class="dim">No colour: ASCAT did not see it</li></ul>';
  }
  function renderAll() {
    renderTop(); renderLeads(); renderLegend();
    if (state.tab === "mosaic") {
      renderStepper(); renderAnswer(); renderWeek(); renderMosaicDetail();
      if (stripFor !== state.basin && index) { stripFor = state.basin; loadStripData(); }
    } else { renderList(); renderDetail(); renderSummary(); }
  }

  // -------------------------------------------------------------- choosing
  var token = 0;
  function choose(id, keepView) {
    state.pass = id;
    var q = index.passes.filter(function (p) { return p.id === id; })[0];
    if (q && new Date(q.start).getTime() < Date.now() - 24 * 3600000) state.older = true;
    writeHash();
    apply(!keepView);
  }
  function chooseM(key, focusIdx) {
    state.v = key; state.focus = focusIdx == null ? null : focusIdx; writeHash(); apply(false);
  }
  function stepM(d) {   // d = +1 later, -1 earlier
    var ms = basinMosaics(), i = ms.indexOf(selectedM());
    if (i < 0) return;
    var j = i - d;
    if (j >= 0 && j < ms.length) chooseM(vKey(ms[j].valid));
  }
  function pickM() {   // the named time if this basin has it, else the newest
    var ms = basinMosaics(), closed = ms.filter(function (m) { return !m.open; });   // the newest finished map; the one still filling is a click away
    if (!selectedM()) state.v = ms.length ? vKey((closed[0] || ms[0]).valid) : null;
  }
  function setTab(t) {
    if (t === state.tab) return;
    state.tab = t;
    if (t === "mosaic") pickM(); else if (!selected()) { var ps = basinPasses(); state.pass = ps.length ? ps[0].id : null; }
    writeHash(); apply(true);
  }
  function applyMosaic(fit) {
    var m = selectedM(), my = ++token;
    if (!m) { clearDense(); cur = null; renderAll(); updateMap(); return; }
    $("progress").classList.add("active");
    loadMosaic(m).then(function (d) {
      if (my !== token) return;
      clearDense(); cur = d; fillObs(); fillLead();
      renderAll(); updateMap(fit);
      if (state.focus != null) focusCell(state.focus);
      $("progress").classList.remove("active");
    }, function () {
      if (my !== token) return;
      $("progress").classList.remove("active");
      K.note("This mosaic could not be loaded");
    });
  }
  function setOscat(on) {
    state.oscat = on; writeHash();
    if (cur && cur.mosaic) { fillObs(); fillClass(); }
    renderAll(); updateMap(false);
  }
  function setLevel(t) {
    state.level = t; writeHash();
    if (cur && cur.mosaic) fillClass();
    renderAll(); updateMap(false);
  }
  function setWinds(on) {
    state.winds = on; writeHash();
    renderAll(); updateMap(false);
  }
  function apply(fit) {
    if (state.tab === "mosaic") { applyMosaic(fit); return; }
    var p = selected(), my = ++token;
    if (!p) { clearDense(); cur = null; renderAll(); updateMap(); return; }
    $("progress").classList.add("active");
    loadPass(p).then(function (d) {
      if (my !== token) return;
      clearDense(); cur = d; fillObs(); fillLead();
      renderAll(); updateMap(fit);
      $("progress").classList.remove("active");
    }, function () {
      if (my !== token) return;
      $("progress").classList.remove("active");
      K.note("This pass could not be loaded");
    });
  }
  function setBasin(b, auto) {
    state.basin = b;
    var ps = basinPasses(), sel = selected();
    if (!sel) state.pass = ps.length ? ps[0].id : null;
    pickM();
    writeHash(); apply(true);
    if (!ps.length && !basinMosaics().length) map && map.flyTo({ center: K.isMobile() ? BASIN[b].mobile : BASIN[b].start, zoom: K.isMobile() ? 1.8 : 2.4 });
  }
  function setLead(l) {
    state.lead = l; writeHash();
    if (cur) fillLead();
    renderAll(); updateMap(false);
  }

  // ------------------------------------------------------------------ map
  var paintVersion = 0, landRings = null, tileCanvas = null, colTab = null, colTabFlag = null, clsTab = null;
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function makeTables() {
    var cols = WIND.colors.map(hex);
    colTab = new Uint8ClampedArray(256 * 4); colTabFlag = new Uint8ClampedArray(256 * 4);
    for (var b = 0; b < 255; b++) {
      var k = 0; while (k + 1 < WIND.stops.length && b >= WIND.stops[k + 1]) k++;
      colTab.set([cols[k][0], cols[k][1], cols[k][2], 235], b * 4);
      colTabFlag.set([cols[k][0], cols[k][1], cols[k][2], 70], b * 4);
    }
    clsTab = new Uint8ClampedArray(5 * 4);   // right, missed, too much, seen below the level
    clsTab.set([34, 197, 94, 240, 225, 29, 72, 245, 255, 166, 43, 235, 71, 85, 105, 110], 4);
  }
  function fieldTile(z, x, y) {
    var d = new Uint8ClampedArray(TILE * TILE * 4), n = Math.pow(2, z), col = new Int32Array(TILE), byVerdict = state.tab === "mosaic" && !state.winds;
    for (var p = 0; p < TILE; p++) {
      var lon = ((x + (p + 0.5) / TILE) / n) * 360 - 180;
      col[p] = ((Math.round((lon + 180) / RES) % NX) + NX) % NX;
    }
    for (var q = 0; q < TILE; q++) {
      var lat = (2 * Math.atan(Math.exp(Math.PI * (1 - 2 * (y + (q + 0.5) / TILE) / n))) - Math.PI / 2) * 180 / Math.PI;
      var j = Math.round((90 - lat) / RES);
      if (j < 0 || j >= NY) continue;
      var base = j * NX, o = q * TILE * 4;
      for (var r = 0; r < TILE; r++, o += 4) {
        var k = base + col[r], v = obsD[k];
        if (byVerdict) { var cc = clsD[k]; if (cc) { var ct = cc * 4; d[o] = clsTab[ct]; d[o + 1] = clsTab[ct + 1]; d[o + 2] = clsTab[ct + 2]; d[o + 3] = clsTab[ct + 3]; } continue; }
        if (v === 255) continue;
        var t = v * 4, tab = flagD[k] ? colTabFlag : colTab;
        d[o] = tab[t]; d[o + 1] = tab[t + 1]; d[o + 2] = tab[t + 2]; d[o + 3] = tab[t + 3];
      }
    }
    var img = new ImageData(d, TILE, TILE);
    if (!landRings || typeof OffscreenCanvas === "undefined") return createImageBitmap(img);
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
  function repaint() {
    paintVersion++;
    var src = map && map.getSource("scat");
    if (src) src.setTiles(["scatfield://{z}/{x}/{y}?v=" + paintVersion]);
  }

  // outline of the cells where inFn is true, along edges that meet a known cell where it is false. cells: ascending
  // flat indices to look at (default: the pass's cells), known(k): the cell is part of the area drawn (default: a pass
  // cell; the mosaic passes the basin's water). The swath's own edge and the coast are not drawn. Collinear edges are joined.
  function outline(inFn, cells, known) {
    cells = cells || cur.idx;
    var nc = cells.length;
    known = known || function (k) { return obsD[k] !== 255; };
    var lines = [], h = RES / 2, i, k, runs = { N: null, S: null }, V = [];
    function cl(iy) { return 90 - iy * RES; }
    function cx(ix) { return ix * RES - 180; }
    function flush(side) {
      var r = runs[side]; if (!r) return;
      var lat = cl(r.iy) + (side === "N" ? h : -h);
      lines.push([[cx(r.ix0) - h, lat], [cx(r.ix1) + h, lat]]); runs[side] = null;
    }
    function push(side, iy, ix) {
      var r = runs[side];
      if (r && r.iy === iy && ix === r.ix1 + 1) r.ix1 = ix; else { flush(side); runs[side] = { iy: iy, ix0: ix, ix1: ix }; }
    }
    for (i = 0; i < nc; i++) {
      k = cells[i];
      if (!inFn(k)) continue;
      var iy = (k / NX) | 0, ix = k - iy * NX, kn;
      if (iy > 0) { kn = k - NX; if (known(kn) && !inFn(kn)) push("N", iy, ix); }
      if (iy < NY - 1) { kn = k + NX; if (known(kn) && !inFn(kn)) push("S", iy, ix); }
      kn = ix > 0 ? k - 1 : k + NX - 1; if (known(kn) && !inFn(kn)) V.push([ix * 2, iy]);
      kn = ix < NX - 1 ? k + 1 : k - NX + 1; if (known(kn) && !inFn(kn)) V.push([ix * 2 + 1, iy]);
    }
    flush("N"); flush("S");
    V.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    for (i = 0; i < V.length;) {
      var j = i;
      while (j + 1 < V.length && V[j + 1][0] === V[i][0] && V[j + 1][1] === V[j][1] + 1) j++;
      var ixv = V[i][0] >> 1, east = V[i][0] & 1, lon = cx(ixv) + (east ? h : -h);
      lines.push([[lon, cl(V[i][1]) + h], [lon, cl(V[j][1]) - h]]);
      i = j + 1;
    }
    return lines;
  }
  function feature(lines, props) { return { type: "Feature", properties: props, geometry: { type: "MultiLineString", coordinates: lines } }; }
  function drawLines() {
    var best = [], warn = [], edge = [];
    // pass view: along the pass's cells; mosaic: over the whole basin box (water cells with a forecast)
    var cells = cur && cur.mosaic ? cur.boxCells : undefined, known = cur && cur.mosaic ? function (k) { return gridD[k] !== 255; } : undefined;
    if (curHasLead()) {
      LEVELS.forEach(function (lv, i) {
        if (cur.mosaic && lv[0] !== state.level) return;   // the mosaic draws the chosen level only
        if (!cur.mosaic || state.winds) best.push(feature(outline(function (k) { return gridD[k] !== 255 && gridD[k] >= lv[0]; }, cells, known), { thr: lv[0] }));
        warn.push(feature(outline(function (k) { return warnD[k] !== 255 && (warnD[k] & lv[3]) !== 0; }, cells, known), { level: lv[1], color: cur.mosaic && !state.winds ? "#ffffff" : lv[2] }));
      });
    }
    if (cur && cur.mosaic && state.winds && curHasLead()) {   // the edge of what the satellites saw, where unseen water lies beyond it
      edge.push(feature(outline(function (k) { return obsD[k] !== 255; }, cur.idx, function (k) { return gridD[k] !== 255; }), {}));
    }
    var sb = map.getSource("best"), sw = map.getSource("warn"), se = map.getSource("edge");
    if (sb) sb.setData({ type: "FeatureCollection", features: best });
    if (sw) sw.setData({ type: "FeatureCollection", features: warn });
    if (se) se.setData({ type: "FeatureCollection", features: edge });
  }
  function bounds() {
    if (cur.mosaic) {
      var B = cur.entry.box, w = B.ix0 * RES - 180, n = 90 - B.iy0 * RES;
      return [[w, n - (B.ny - 1) * RES], [w + (B.nx - 1) * RES, n]];
    }
    var la0 = 999, la1 = -999, lo0 = 999, lo1 = -999;
    for (var i = 0; i < cur.n; i++) {
      var k = cur.idx[i], iy = (k / NX) | 0, ix = k - iy * NX, lat = 90 - iy * RES, lon = ix * RES - 180;
      if (state.basin === "pac" && lon < 0) lon += 360;
      if (lat < la0) la0 = lat; if (lat > la1) la1 = lat; if (lon < lo0) lo0 = lon; if (lon > lo1) lo1 = lon;
    }
    return [[lo0, la0], [lo1, la1]];
  }
  function padding() {
    var m = K.isMobile(), tb = document.querySelector(".topbar").getBoundingClientRect();
    if (m) {
      var card = $("card").getBoundingClientRect();
      return { top: tb.bottom + 14, bottom: window.innerHeight - card.top + 12, left: 14, right: 56 };
    }
    return { top: tb.bottom + 24, bottom: 40, left: $("card").getBoundingClientRect().right + 24, right: 70 };
  }
  var mapReady = false;
  function cellLngLat(idx) { var iy = (idx / NX) | 0, ix = idx - iy * NX; return [ix * RES - 180, 90 - iy * RES]; }
  function setFocus() {
    var src = map && map.getSource("focus");
    if (src) src.setData({ type: "FeatureCollection", features: state.focus != null && state.tab === "mosaic" ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: cellLngLat(state.focus) } }] : [] });
  }
  function focusCell(idx) {   // zoom to a cell (the Worst seen rows)
    if (!map || !mapReady) return;
    setFocus();
    map.easeTo({ center: cellLngLat(idx), zoom: 5.2, padding: padding(), duration: 1200 });
  }
  function updateMap(fit) {
    if (!map || !mapReady) return;
    repaint(); drawLines(); setFocus(); applyVisibility(); map.triggerRepaint();
    if (fit && cur && (cur.n || cur.mosaic)) {
      var b = bounds();
      map.fitBounds(b, { padding: padding(), maxZoom: 6, duration: fit === "now" ? 0 : 900 });
    }
  }
  function applyVisibility() {
    var L = state.tab === "mosaic" ? { scat: true, best: state.winds, warn: true } : state.layers;
    [["scat", L.scat], ["edge", L.scat], ["best-halo", L.best], ["best", L.best], ["warn-halo", L.warn], ["warn", L.warn]].forEach(function (a) {
      if (map.getLayer(a[0])) map.setLayoutProperty(a[0], "visibility", a[1] ? "visible" : "none");
    });
    drawOverlay();
  }

  // ------------------------------------------------- barbs on the overlay
  function barb(ctx, x, y, dirFrom, kt, alpha) {
    var r = Math.round(kt / 5) * 5, th = dirFrom * Math.PI / 180, L = 20;
    var sx = Math.sin(th), sy = -Math.cos(th);              // toward where the wind comes from
    function path() {
      ctx.beginPath();
      if (r < 5) { ctx.arc(x, y, 3, 0, 6.283); return; }
      var ex = x + sx * L, ey = y + sy * L, px = -sy, py = sx, pos = L, a;
      ctx.moveTo(x, y); ctx.lineTo(ex, ey);
      var rem = r;
      function at(d) { return [x + sx * d, y + sy * d]; }
      while (rem >= 50) { a = at(pos); var b = at(pos - 5); ctx.moveTo(a[0], a[1]); ctx.lineTo(a[0] + px * 8 - sx * 0, a[1] + py * 8); ctx.lineTo(b[0], b[1]); rem -= 50; pos -= 6; }
      while (rem >= 10) { a = at(pos); ctx.moveTo(a[0], a[1]); ctx.lineTo(a[0] + px * 8 - sx * 3, a[1] + py * 8 - sy * 3); rem -= 10; pos -= 3.4; }
      if (rem >= 5) { if (pos === L) pos -= 3.4; a = at(pos); ctx.moveTo(a[0], a[1]); ctx.lineTo(a[0] + px * 4 - sx * 1.5, a[1] + py * 4 - sy * 1.5); }
    }
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(5,10,20," + (0.75 * alpha) + ")"; ctx.lineWidth = 3.6; path(); ctx.stroke();
    ctx.strokeStyle = "rgba(248,250,252," + alpha + ")"; ctx.lineWidth = 1.5; path(); ctx.stroke();
  }
  function drawOverlay() {
    if (!ov || !map) return;
    ov.clear();
    if (!cur || !(state.tab === "mosaic" ? state.winds : state.layers.scat) || map.getZoom() < 4.2) return;
    var c = map.getCenter(), z = map.getZoom(), b = map.getBounds();
    var p0 = map.project([c.lng, c.lat]), p1 = map.project([c.lng + RES, c.lat]);
    var cellPx = Math.max(1, Math.abs(p1.x - p0.x)), step = Math.max(1, Math.ceil(30 / cellPx));
    var iy0 = Math.max(0, Math.floor((90 - Math.min(85, b.getNorth())) / RES)), iy1 = Math.min(NY - 1, Math.ceil((90 - Math.max(-85, b.getSouth())) / RES));
    var lo0 = b.getWest(), lo1 = b.getEast(); if (lo1 - lo0 > 120) { lo0 = c.lng - 60; lo1 = c.lng + 60; }
    var ix0 = Math.floor((lo0 + 180) / RES), ix1 = Math.ceil((lo1 + 180) / RES), ctx = ov.ctx, cnt = 0;
    iy0 -= iy0 % step; ix0 -= ((ix0 % step) + step) % step;
    for (var iy = iy0; iy <= iy1; iy += step) {
      for (var ix = ix0; ix <= ix1; ix += step) {
        var wx = ((ix % NX) + NX) % NX, k = iy * NX + wx;
        if (obsD[k] === 255) continue;
        var lon = ix * RES - 180, lat = 90 - iy * RES, pr = ov.proj(lon, lat);
        if (!pr.length) continue;
        barb(ctx, pr[0].x, pr[0].y, dirD[k] * 2, obsD[k], flagD[k] ? 0.35 : 0.95);
        if (++cnt > 2500) return;
      }
    }
  }

  // --------------------------------------------------------------- readout
  function insidePlain(w) { return w === 255 ? "" : (w & 4) ? "inside HF line" : (w & 2) ? "inside storm line" : (w & 1) ? "inside gale line" : "outside the warning lines"; }
  function hoverLine(who, o, dirDeg, g, w) {   // "ASCAT 52 kt from 280 · Best Wind 44 kt · inside storm line"
    var parts = [o == null ? "Not seen by ASCAT" : who + " <b>" + o + " kt</b> from " + ("00" + dirDeg).slice(-3), "Best Wind " + (g === 255 ? "none" : "<b>" + g + " kt</b>")];
    var ins = insidePlain(w); if (ins) parts.push(ins);
    return '<div class="h">' + parts.join(" &middot; ") + "</div>";
  }
  function verdictNote(o, g) {   // the chosen level, only where the cell matters to it
    var T = state.level, nm = NAME[T] + " (" + T + " kt)";
    if (g === 255) return "";
    if (o >= T) return g >= T ? '<div class="note-line v-right">Right: both ' + T + ' kt or more</div>' : '<div class="note-line v-miss">Missed ' + nm + ": Best Wind is " + g + " kt</div>";
    return g >= T ? '<div class="note-line v-much">Too much ' + nm + ": ASCAT saw " + o + " kt</div>" : "";
  }
  function hoverAt(pt, ll) {
    var box = $("readout");
    if (!cur || state.tab === "passes" && !state.layers.scat && !state.layers.best && !state.layers.warn || !map.transform.isPointOnMapSurface(pt)) { box.hidden = true; return; }
    var lon = K.wrapLon(ll.lng), iy = Math.round((90 - ll.lat) / RES), ix = ((Math.round((lon + 180) / RES) % NX) + NX) % NX;
    if (iy < 0 || iy >= NY) { box.hidden = true; return; }
    var k = iy * NX + ix, here = '<div class="where">' + K.latText(90 - iy * RES, 2) + " " + K.lonText(ix * RES - 180, 2) + "</div>";
    if (cur.mosaic) { hoverMosaic(box, pt, k, here); return; }
    if (obsD[k] === 255) { box.hidden = true; return; }
    var p = selected();
    place(box, hoverLine(satShort(p.sat), obsD[k], dirD[k] * 2, gridD[k], warnD[k]) + here + (flagD[k] ? '<div class="note-line">Rain flag: likely rain-affected, left out of the scores</div>' : ""), pt);
  }
  function place(box, h, pt) {
    box.innerHTML = h; box.hidden = false;
    var W = ov.w(), H = ov.h(), bw = box.offsetWidth, bh = box.offsetHeight;
    box.style.left = Math.max(8, Math.min(pt.x + 16, W - bw - 8)) + "px";
    box.style.top = Math.max(8, Math.min(pt.y + 16, H - bh - 8)) + "px";
    if (pt.y + 16 + bh > H - 8) box.style.top = Math.max(8, pt.y - bh - 12) + "px";
  }
  function hoverMosaic(box, pt, k, here) {
    var seen = obsD[k] !== 255, g = gridD[k], w = warnD[k], L = state.lead;
    if (!seen && g === 255) { box.hidden = true; return; }
    var m = cur.entry, pp = seen ? cur.members[passD[k]] : null, h;
    if (seen) {
      var i = posD[k], cg = m.fc[L] ? cur.cell[L].grid[i] : 255, cw = m.fc[L] ? cur.cell[L].warn[i] : 255, asc = pp && isAscat(pp);
      h = hoverLine(pp && !isAscat(pp) ? "OSCAT-3" : "ASCAT", obsD[k], dirD[k] * 2, cg, cw) + here;
      if (asc && !flagD[k]) h += verdictNote(obsD[k], cg);
      if (pp) h += '<div class="note-line">' + satShort(pp.sat) + " " + hhmm(new Date(pp.mid)) + (g !== 255 && g !== cg ? " &middot; Best Wind drawn for " + hrZ(m.valid, 0) + "Z: " + g + " kt" : "") + "</div>";
      if (!asc) h += '<div class="note-line">OSCAT-3 is never scored</div>';
      else if (flagD[k]) h += '<div class="note-line">Rain flag: likely rain-affected, left out of the scores</div>';
    } else h = hoverLine("", null, 0, g, w) + here;
    place(box, h, pt);
  }

  // ------------------------------------------------------------------ start
  function setupMap() {
    maplibregl.addProtocol("scatfield", function (params) {
      var m = /scatfield:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url);
      return fieldTile(+m[1], +m[2], +m[3]).then(function (data) { return { data: data }; });
    });
    var B = BASIN[state.basin];
    map = K.createMap({ start: { center: K.isMobile() ? B.mobile : B.start, zoom: K.isMobile() ? 1.8 : 2.4 }, credits: "Scatterometer: NOAA STAR; grid: marine wind blend" });
    window.SCAT_map = map;
    ov = K.overlay(map, $("overlay"));
    map.on("render", drawOverlay);
    map.on("load", function () {
      map.addSource("scat", { type: "raster", tiles: ["scatfield://{z}/{x}/{y}?v=0"], tileSize: TILE, maxzoom: 7 });
      map.addLayer({ id: "scat", type: "raster", source: "scat", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0, "raster-opacity": 0.92 } });
      var empty = { type: "FeatureCollection", features: [] };
      map.addSource("edge", { type: "geojson", data: empty, tolerance: 0 });
      map.addLayer({ id: "edge", type: "line", source: "edge", paint: { "line-color": "rgba(255,255,255,0.5)", "line-width": 0.8 } });
      map.addSource("best", { type: "geojson", data: empty, tolerance: 0 });
      map.addSource("warn", { type: "geojson", data: empty, tolerance: 0 });
      map.addLayer({ id: "best-halo", type: "line", source: "best", layout: { "line-cap": "round" }, paint: { "line-color": "rgba(5,10,20,0.8)", "line-width": ["match", ["get", "thr"], 34, 3, 48, 4.4, 5.8] } });
      map.addLayer({ id: "best", type: "line", source: "best", layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": ["match", ["get", "thr"], 34, 1, 48, 2, 3.2] } });
      map.addLayer({ id: "warn-halo", type: "line", source: "warn", paint: { "line-color": "rgba(5,10,20,0.7)", "line-width": 3.6 } });
      map.addLayer({ id: "warn", type: "line", source: "warn", paint: { "line-color": ["get", "color"], "line-width": 1.9, "line-dasharray": [2.5, 1.5] } });
      map.addSource("focus", { type: "geojson", data: empty });
      map.addLayer({ id: "focus-halo", type: "circle", source: "focus", paint: { "circle-radius": 15, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "rgba(5,10,20,0.85)", "circle-stroke-width": 5 } });
      map.addLayer({ id: "focus", type: "circle", source: "focus", paint: { "circle-radius": 15, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#38bdf8", "circle-stroke-width": 2.2 } });
      mapReady = true;
      K.land().then(function (g) { landRings = K.landRings(g); repaint(); }).catch(function () { /* cells then also cover land */ });
      if (index) updateMap(selected() ? "now" : false);
    });
    map.on("mousemove", function (e) { hoverAt(e.point, e.lngLat); });
    map.on("click", function (e) { hoverAt(e.point, e.lngLat); });
    map.getCanvas().addEventListener("mouseleave", function () { $("readout").hidden = true; });
  }

  function start() {
    K = window.GlobeKit;
    makeTables(); renderLegend();
    readHash();
    $("homeLink").hidden = false;
    document.querySelectorAll("#basins button").forEach(function (b) { b.addEventListener("click", function () { setBasin(b.dataset.basin); }); });
    document.querySelectorAll("#leads button").forEach(function (b) { b.addEventListener("click", function () { if (!b.disabled) setLead(b.dataset.lead); }); });
    document.querySelectorAll("#toggles button").forEach(function (b) {
      b.addEventListener("click", function () {
        state.layers[b.dataset.layer] = !state.layers[b.dataset.layer];
        b.setAttribute("aria-pressed", String(state.layers[b.dataset.layer]));
        if (mapReady) applyVisibility();
      });
    });
    document.querySelectorAll("#levels button").forEach(function (b) { b.addEventListener("click", function () { setLevel(+b.dataset.level); }); });
    $("windsBtn").addEventListener("click", function () { setWinds(!state.winds); });
    $("passesBtn").addEventListener("click", function () { if (index) setTab("passes"); });
    $("backBtn").addEventListener("click", function () { if (index) setTab("mosaic"); });
    $("tPrev").addEventListener("click", function () { stepM(-1); });
    $("tNext").addEventListener("click", function () { stepM(1); });
    $("oscatBtn").addEventListener("click", function () { setOscat(!state.oscat); });
    $("older").addEventListener("click", function () { state.older = !state.older; writeHash(); renderList(); });
    $("cardToggle").addEventListener("click", function () {
      var closed = $("card").classList.toggle("closed");
      this.textContent = closed ? "Show" : "Hide"; this.setAttribute("aria-expanded", String(!closed));
    });
    window.addEventListener("hashchange", function () { if (!index) return; readHash(); var sel = selected(); if (!sel) { var ps = basinPasses(); state.pass = ps.length ? ps[0].id : null; } pickM(); apply(true); });
    window.addEventListener("keydown", function (e) {
      if (e.target.closest && e.target.closest("input, textarea")) return;
      var key = e.key, ps = index ? basinPasses() : [];
      if (index && state.tab === "mosaic") {
        if (key === "ArrowLeft") stepM(-1); else if (key === "ArrowRight") stepM(1); else return;
        e.preventDefault(); return;
      }
      if (!ps.length) return;
      var i = ps.findIndex(function (p) { return p.id === state.pass; });
      if (key === "ArrowDown" || key === "j") { if (i < ps.length - 1) choose(ps[i + 1].id); }
      else if (key === "ArrowUp" || key === "k") { if (i > 0) choose(ps[i - 1].id); }
      else return;
      e.preventDefault();
    });
    if (K.webgl()) setupMap(); else $("fatal").hidden = false;
    fetch("data/index.json?t=" + Date.now(), { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
      index = d;
      index.mosaics = (index.mosaics || []).filter(function (m) { return m.format === 2; });   // older 6-hourly mosaics are not shown
      var ps = basinPasses();
      // a hash naming a pass in the other basin switches to it; nothing named means the newest in the basin
      var named = state.pass && index.passes.filter(function (p) { return p.id === state.pass; })[0];
      if (named) { state.basin = basinOf(named); if (new Date(named.start).getTime() < Date.now() - 24 * 3600000) state.older = true; }
      else { state.pass = ps.length ? ps[0].id : null; if (!ps.length && index.passes.length) { state.basin = basinOf(index.passes[0]); state.pass = basinPasses()[0].id; } }
      // mosaic view: a hash naming a time this basin lacks falls to the newest; a basin without passes or mosaics tries the other
      if (!index.mosaics.length) state.tab = "passes";   // data published before the mosaics existed
      if (!basinMosaics().length && index.mosaics.length) state.basin = basinOf(index.mosaics[0]);
      pickM();
      writeHash(); apply(true);
      if (mapReady) updateMap(selected() || selectedM() ? "now" : false);
    }, function () {
      index = { passes: [], mosaics: [] };
      $("cardTitle").textContent = "No scatterometer data yet";
      $("answer").innerHTML = '<p class="a-line">No ASCAT data yet. Check back after the next hour.</p>';
      $("mdetail").innerHTML = '<p class="empty">The mosaics are written by an hourly job that starts after the first STAR files are processed. Nothing is published yet; check back after the next hour.</p>';
      $("passes").innerHTML = '<p class="empty">The pass list is written by an hourly job that starts after the first STAR files are processed. Nothing is published yet; check back after the next hour.</p>';
      $("summaryBox").hidden = true; $("detailsBox").hidden = true; $("moreBox").hidden = true;
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
