/* Scatterometer Passes: the latest NOAA STAR scatterometer passes (OSCAT-3, Metop-B and Metop-C ASCAT)
   over the two OPC basins, set against the marine wind page's Best Wind and warning lines, with a score
   per pass. Reads data/index.json and data/pass/*.bin (written by marine_wind/scat/build.py, published
   with the site). Shared globe kit: ../globe-kit/. Plain ES2020.

   Pass .bin (gzip, little-endian): uint32 n; uint32 idx[n] (global 0.25 deg cell, iy * 1440 + ix, ascending);
   uint8 obs[n] (kt), dir[n] (deg / 2), flag[n] (1 = rain-flagged); then for latest, f24, f48:
   uint8 grid[n] (kt, 255 none), warn[n] (bits 1 gale, 2 storm, 4 HF; 255 none). */
(function () {
  "use strict";
  var K, map = null, ov = null, index = null;
  var $ = function (id) { return document.getElementById(id); };
  var NX = 1440, NY = 721, RES = 0.25, TILE = 256;
  var LEADS = [["latest", "Latest run"], ["f24", "+24 h"], ["f48", "+48 h"]];
  var BASIN = { atl: { name: "Atlantic", start: [-45, 45], mobile: [-45, 42] }, pac: { name: "Pacific", start: [175, 45], mobile: [175, 42] } };
  var LEVELS = [[34, "gale", "#fbbf24", 7], [48, "storm", "#f97316", 6], [64, "HF", "#e879f9", 4]];
  var WIND = { // the marine wind page's 10 m wind scale
    stops: [0, 10, 15, 20, 25, 30, 34, 41, 48, 56, 64, 80],
    colors: ["#1b1d21", "#1f2a36", "#22364b", "#28466a", "#2f5a8a", "#3f74ab", "#e8d27a", "#e8a93f", "#e06f2e", "#c9372c", "#9b1f5e", "#c86fd8"]
  };
  var state = { basin: "atl", lead: "latest", pass: null, older: false, layers: { scat: true, best: true, warn: true } };

  // ----------------------------------------------------------------- hash
  function readHash() {
    var h = new URLSearchParams(location.hash.replace(/^#/, ""));
    if (BASIN[h.get("basin")]) state.basin = h.get("basin");
    if (LEADS.some(function (l) { return l[0] === h.get("lead"); })) state.lead = h.get("lead");
    state.pass = h.get("pass") || null;
    state.older = h.get("older") === "1";
  }
  function writeHash() {
    var h = "#basin=" + state.basin + "&lead=" + state.lead + (state.pass ? "&pass=" + encodeURIComponent(state.pass) : "") + (state.older ? "&older=1" : "");
    try { history.replaceState(null, "", h); } catch (e) { /* the hash stays as it was */ }
  }

  // ------------------------------------------------------------- formats
  function basinOf(p) { return /pac/i.test(p.basin) ? "pac" : "atl"; }
  function satShort(s) { return s === "OSCAT-3" ? "OSCAT-3" : s; }
  function isAscat(p) { return /^Metop/.test(p.sat); }
  function hhmm(d) { return K.pad(d.getUTCHours()) + ":" + K.pad(d.getUTCMinutes()) + "Z"; }
  function dayTime(iso) { var d = new Date(iso); return K.DAYS[d.getUTCDay()] + " " + d.getUTCDate() + " " + hhmm(d); }
  function dayHour(iso) { var d = new Date(iso); return K.pad(d.getUTCHours()) + "Z " + K.DAYS[d.getUTCDay()] + " " + d.getUTCDate() + " " + K.MONS[d.getUTCMonth()]; }
  function cycleDate(c) { return new Date(Date.UTC(+c.slice(0, 4), +c.slice(4, 6) - 1, +c.slice(6, 8), +c.slice(8, 10))).toISOString(); }
  function ago(iso) {
    var h = (Date.now() - new Date(iso).getTime()) / 3600000;
    return h < 1 ? Math.max(0, Math.round(h * 60)) + " min ago" : h < 48 ? h.toFixed(1).replace(/\.0$/, "") + " h ago" : Math.round(h / 24) + " days ago";
  }
  function leadWords(l) { return l === "latest" ? "latest-run" : leadName(l); }
  function leadName(l) { return l === "latest" ? "Latest run" : l === "f24" ? "+24 h" : "+48 h"; }
  function plural(n, w) { return n + " " + (n === 1 ? w : w === "pass" ? "passes" : w + "s"); }
  function num(n) { return Math.round(n).toLocaleString("en-US"); }
  function ratio(g, o) { return o > 0 ? g / o : null; }

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

  // dense 0.25 degree arrays of the selected pass, for the tiles, lines, barbs and readout
  var obsD = new Uint8Array(NX * NY).fill(255), dirD = new Uint8Array(NX * NY), flagD = new Uint8Array(NX * NY);
  var gridD = new Uint8Array(NX * NY).fill(255), warnD = new Uint8Array(NX * NY).fill(255);
  function clearDense() {
    if (!cur) return;
    for (var i = 0; i < cur.n; i++) { var k = cur.idx[i]; obsD[k] = 255; flagD[k] = 0; gridD[k] = 255; warnD[k] = 255; }
  }
  function fillObs() {
    for (var i = 0; i < cur.n; i++) { var k = cur.idx[i]; obsD[k] = cur.obs[i]; dirD[k] = cur.dir[i]; flagD[k] = cur.flag[i]; }
  }
  function fillLead() {
    var L = cur && state.lead && selected() && selected().fc[state.lead] ? cur.leads[state.lead] : null;
    for (var i = 0; i < cur.n; i++) { var k = cur.idx[i]; gridD[k] = L ? L.grid[i] : 255; warnD[k] = L ? L.warn[i] : 255; }
  }

  // ------------------------------------------------------------- selection
  function basinPasses() { return index.passes.filter(function (p) { return basinOf(p) === state.basin; }); }
  function selected() { return state.pass ? index.passes.filter(function (p) { return p.id === state.pass && basinOf(p) === state.basin; })[0] || null : null; }

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

  function scoreText(p, L) {
    var s = p.score[L], f = p.fc[L], names = ["gale", "storm", "hurricane force"];
    var parts = [];
    var om = Math.round(s.obs_max), gm = Math.round(s.grid_max);
    var out = "<p>Highest wind: observed <b>" + om + " kt</b>, grid <b>" + gm + " kt</b>" +
      (gm === om ? "." : " (grid " + Math.abs(gm - om) + " kt " + (gm > om ? "high" : "low") + ").") + "</p>";
    if (!s.obs[0] && !s.grid[0]) out += "<p>No gale-force wind in the observed cells or the grid.</p>";
    else {
      for (var i = 0; i < 3; i++) {
        var r = ratio(s.grid[i], s.obs[i]);
        if (r !== null) parts.push("<b>" + r.toFixed(1) + "x</b> the observed " + (i === 0 ? "gale area" : i === 1 ? "storm" : "HF"));
        else parts.push(s.grid[i] ? "<b>" + plural(s.grid[i], "cell") + "</b> of " + (i === 1 ? "storm" : "HF") + " with none observed" : "no " + (i === 1 ? "storm" : "HF") + " in either");
      }
      out += "<p>Grid has " + parts.join(", ") + ".</p>";
      var cp = [];
      for (var j = 0; j < 3; j++) {
        var o = s.obs[j], c = s.catch[j], lab = j === 0 ? "observed gale cells" : j === 1 ? "storm" : "HF";
        if (!o) { cp.push("no observed " + (j === 0 ? "gale cells" : j === 1 ? "storm" : "HF") + " to catch"); continue; }
        cp.push(o < 10 ? "<b>" + c + " of " + o + "</b> " + lab : "<b>" + Math.round(100 * c / o) + "%</b> of " + lab);
      }
      out += "<p>Lines caught " + cp.join(", ") + ".</p>";
    }
    if (p.sat === "OSCAT-3") out += '<p class="warnnote">OSCAT-3 reads low at high winds: against ASCAT it ran about 3 kt low at 20-34 kt, 5 kt low at 34-48 kt and 15-20 kt low above 48 kt (few storms), and saw a tenth of ASCAT\'s storm area (13 Oct-7 Nov 2026). A grid above OSCAT in a storm is not necessarily too high; judge storm and HF by ASCAT.</p>';
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

  function renderLeads() {
    var p = selected();
    document.querySelectorAll("#leads button").forEach(function (b) {
      var ok = !p || !!p.fc[b.dataset.lead];
      b.setAttribute("aria-pressed", String(b.dataset.lead === state.lead));
      b.disabled = !ok;
      b.title = ok ? b.title.replace(/ \(.*$/, "") : "Not available for this pass (+24 h and +48 h fill in over the two days after the page starts)";
    });
  }
  function renderTop() {
    var p = selected();
    $("validTime").textContent = p ? K.fmtValid(p.mid).replace(/:00 UTC$/, "") + ":" + K.pad(new Date(p.mid).getUTCMinutes()) + " UTC" : "—";
    $("validRel").textContent = p ? satShort(p.sat) + " · " + ago(p.mid) : "";
    document.querySelectorAll("#basins button").forEach(function (b) { b.setAttribute("aria-checked", String(b.dataset.basin === state.basin)); });
    var ps = basinPasses();
    $("cardTitle").textContent = BASIN[state.basin].name + " passes" + (ps.length ? " · " + ps.length + " in 7 days" : "");
  }
  function renderLegend() {
    var n = WIND.colors.length, top = 80;
    $("legend").innerHTML = '<div class="bar">' + WIND.colors.map(function (c, i) { return '<span style="background:' + c + ';flex:' + ((WIND.stops[i + 1] || top) - WIND.stops[i]) + '"></span>'; }).join("") + "</div>" +
      '<div class="labs">' + [0, 20, 34, 48, 64, 80].map(function (v) { return '<span style="left:' + (v / top * 100) + '%">' + v + "</span>"; }).join("") + "</div>" +
      '<div class="keys"><span>Observed wind, kt (faded: rain flag)</span><span><i style="border-top:3px solid #fff"></i>Best Wind 34/48/64 kt, thin to thick</span>' +
      '<span><i style="border-top:2px dashed ' + LEVELS[0][2] + '"></i>gale <i style="border-top:2px dashed ' + LEVELS[1][2] + '"></i>storm <i style="border-top:2px dashed ' + LEVELS[2][2] + '"></i>HF line</span></div>';
  }
  function renderAll() { renderTop(); renderLeads(); renderList(); renderDetail(); renderSummary(); }

  // -------------------------------------------------------------- choosing
  var token = 0;
  function choose(id, keepView) {
    state.pass = id;
    var q = index.passes.filter(function (p) { return p.id === id; })[0];
    if (q && new Date(q.start).getTime() < Date.now() - 24 * 3600000) state.older = true;
    writeHash();
    apply(!keepView);
  }
  function apply(fit) {
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
    writeHash(); apply(true);
    if (!ps.length) map && map.flyTo({ center: K.isMobile() ? BASIN[b].mobile : BASIN[b].start, zoom: K.isMobile() ? 1.8 : 2.4 });
  }
  function setLead(l) {
    state.lead = l; writeHash();
    if (cur) fillLead();
    renderLeads(); renderList(); renderDetail(); updateMap(false);
  }

  // ------------------------------------------------------------------ map
  var paintVersion = 0, landRings = null, tileCanvas = null, colTab = null, colTabFlag = null;
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function makeTables() {
    var cols = WIND.colors.map(hex);
    colTab = new Uint8ClampedArray(256 * 4); colTabFlag = new Uint8ClampedArray(256 * 4);
    for (var b = 0; b < 255; b++) {
      var k = 0; while (k + 1 < WIND.stops.length && b >= WIND.stops[k + 1]) k++;
      colTab.set([cols[k][0], cols[k][1], cols[k][2], 235], b * 4);
      colTabFlag.set([cols[k][0], cols[k][1], cols[k][2], 70], b * 4);
    }
  }
  function fieldTile(z, x, y) {
    var d = new Uint8ClampedArray(TILE * TILE * 4), n = Math.pow(2, z), col = new Int32Array(TILE);
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

  // outline of the cells where inFn is true, along edges that meet a cell of the pass where it is false
  // (the swath's own edge and the coast are not drawn). Collinear edges are joined.
  function outline(inFn) {
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
    for (i = 0; i < cur.n; i++) {
      k = cur.idx[i];
      if (!inFn(k)) continue;
      var iy = (k / NX) | 0, ix = k - iy * NX, kn;
      if (iy > 0) { kn = k - NX; if (obsD[kn] !== 255 && !inFn(kn)) push("N", iy, ix); }
      if (iy < NY - 1) { kn = k + NX; if (obsD[kn] !== 255 && !inFn(kn)) push("S", iy, ix); }
      kn = ix > 0 ? k - 1 : k + NX - 1; if (obsD[kn] !== 255 && !inFn(kn)) V.push([ix * 2, iy]);
      kn = ix < NX - 1 ? k + 1 : k - NX + 1; if (obsD[kn] !== 255 && !inFn(kn)) V.push([ix * 2 + 1, iy]);
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
    var best = [], warn = [];
    if (cur && selected() && selected().fc[state.lead]) {
      LEVELS.forEach(function (lv, i) {
        best.push(feature(outline(function (k) { return gridD[k] !== 255 && gridD[k] >= lv[0]; }), { thr: lv[0] }));
        warn.push(feature(outline(function (k) { return warnD[k] !== 255 && (warnD[k] & lv[3]) !== 0; }), { level: lv[1], color: lv[2] }));
      });
    }
    var sb = map.getSource("best"), sw = map.getSource("warn");
    if (sb) sb.setData({ type: "FeatureCollection", features: best });
    if (sw) sw.setData({ type: "FeatureCollection", features: warn });
  }
  function bounds() {
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
  function updateMap(fit) {
    if (!map || !mapReady) return;
    repaint(); drawLines(); applyVisibility(); map.triggerRepaint();
    if (fit && cur && cur.n) {
      var b = bounds();
      map.fitBounds(b, { padding: padding(), maxZoom: 6, duration: fit === "now" ? 0 : 900 });
    }
  }
  function applyVisibility() {
    var L = state.layers;
    [["scat", L.scat], ["best-halo", L.best], ["best", L.best], ["warn-halo", L.warn], ["warn", L.warn]].forEach(function (a) {
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
    if (!cur || !state.layers.scat || map.getZoom() < 4.2) return;
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
  function hoverAt(pt, ll) {
    var box = $("readout");
    if (!cur || !state.layers.scat && !state.layers.best && !state.layers.warn || !map.transform.isPointOnMapSurface(pt)) { box.hidden = true; return; }
    var lon = K.wrapLon(ll.lng), iy = Math.round((90 - ll.lat) / RES), ix = ((Math.round((lon + 180) / RES) % NX) + NX) % NX;
    if (iy < 0 || iy >= NY) { box.hidden = true; return; }
    var k = iy * NX + ix;
    if (obsD[k] === 255) { box.hidden = true; return; }
    var p = selected(), g = gridD[k], w = warnD[k], dirDeg = dirD[k] * 2;
    var inside = w === 255 ? null : (w & 4) ? "HF warning line" : (w & 2) ? "Storm warning line" : (w & 1) ? "Gale warning line" : "outside the warning lines";
    var h = '<div class="h"><b>' + obsD[k] + " kt</b> from " + ("00" + dirDeg).slice(-3) + "&deg;</div><table>" +
      "<tr><td>" + K.latText(90 - iy * RES, 2) + " " + K.lonText(ix * RES - 180, 2) + "</td><td>" + satShort(p.sat) + "</td></tr>" +
      "<tr><td>Observed (cell mean)</td><td>" + obsD[k] + " kt, " + dirDeg + "&deg;</td></tr>" +
      "<tr class=\"sep\"><td>Best Wind, " + leadName(state.lead) + "</td><td>" + (g === 255 ? "none" : g + " kt") + "</td></tr>" +
      (g !== 255 ? "<tr><td>Grid minus observed</td><td>" + (g - obsD[k] > 0 ? "+" : "") + (g - obsD[k]) + " kt</td></tr>" : "") +
      (inside ? "<tr><td>Inside</td><td>" + inside + "</td></tr>" : "") + "</table>" +
      (flagD[k] ? '<div class="note-line">Rain flag: likely rain-affected, left out of the scores</div>' : "");
    box.innerHTML = h; box.hidden = false;
    var W = ov.w(), H = ov.h(), bw = box.offsetWidth, bh = box.offsetHeight;
    box.style.left = Math.max(8, Math.min(pt.x + 16, W - bw - 8)) + "px";
    box.style.top = Math.max(8, Math.min(pt.y + 16, H - bh - 8)) + "px";
    if (pt.y + 16 + bh > H - 8) box.style.top = Math.max(8, pt.y - bh - 12) + "px";
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
      map.addSource("best", { type: "geojson", data: empty, tolerance: 0 });
      map.addSource("warn", { type: "geojson", data: empty, tolerance: 0 });
      map.addLayer({ id: "best-halo", type: "line", source: "best", layout: { "line-cap": "round" }, paint: { "line-color": "rgba(5,10,20,0.8)", "line-width": ["match", ["get", "thr"], 34, 3, 48, 4.4, 5.8] } });
      map.addLayer({ id: "best", type: "line", source: "best", layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": ["match", ["get", "thr"], 34, 1, 48, 2, 3.2] } });
      map.addLayer({ id: "warn-halo", type: "line", source: "warn", paint: { "line-color": "rgba(5,10,20,0.7)", "line-width": 3.6 } });
      map.addLayer({ id: "warn", type: "line", source: "warn", paint: { "line-color": ["get", "color"], "line-width": 1.9, "line-dasharray": [2.5, 1.5] } });
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
    $("older").addEventListener("click", function () { state.older = !state.older; writeHash(); renderList(); });
    $("cardToggle").addEventListener("click", function () {
      var closed = $("card").classList.toggle("closed");
      this.textContent = closed ? "Show passes" : "Hide"; this.setAttribute("aria-expanded", String(!closed));
    });
    window.addEventListener("hashchange", function () { if (!index) return; readHash(); var sel = selected(); if (!sel) { var ps = basinPasses(); state.pass = ps.length ? ps[0].id : null; } apply(true); });
    window.addEventListener("keydown", function (e) {
      if (e.target.closest && e.target.closest("input, textarea")) return;
      var key = e.key, ps = index ? basinPasses() : [];
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
      var ps = basinPasses();
      // a hash naming a pass in the other basin switches to it; nothing named means the newest in the basin
      var named = state.pass && index.passes.filter(function (p) { return p.id === state.pass; })[0];
      if (named) { state.basin = basinOf(named); if (new Date(named.start).getTime() < Date.now() - 24 * 3600000) state.older = true; }
      else { state.pass = ps.length ? ps[0].id : null; if (!ps.length && index.passes.length) { state.basin = basinOf(index.passes[0]); state.pass = basinPasses()[0].id; } }
      writeHash(); apply(true);
      if (mapReady) updateMap(selected() ? "now" : false);
    }, function () {
      index = { passes: [] };
      $("cardTitle").textContent = "No scatterometer data yet";
      $("passes").innerHTML = '<p class="empty">The pass list is written by an hourly job that starts after the first STAR files are processed. Nothing is published yet; check back after the next hour.</p>';
      $("summaryBox").hidden = true;
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
