/* High Seas Editor: write the HSF in the text box; the map redraws the areas the text describes
   (hsf-read.js), the checks run as you type (hsf-check.js), and the copy buttons give the forecast
   editor's Warnings and Synopsis boxes at 66 characters. It starts from the last issued product
   (IEM text archive, which the browser may read) with the valid times moved on 6 hours. It never
   uses the model-written draft on /high-seas/. Plain ES2017. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var BASINS = {
    atl: { name: "Atlantic", pil: "HSFAT1", bounds: [[-84, 29], [-33, 68]] },
    pac: { name: "Pacific", pil: "HSFEP1", bounds: [[-190, 28], [-108, 68]] }
  };
  var IEM = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?fmt=text&limit=1&pil=";
  var COLOURS = { low: "#5d7fa3", gale: "#d39a1c", storm: "#c0392b", hf: "#7d3c98" };
  var q = new URLSearchParams(location.search);
  var basin = (q.get("basin") || store("hsf-editor-basin") || "atl").toLowerCase();
  if (!BASINS[basin]) basin = "atl";
  var ed = $("editor"), map = null, mapReady = false, markers = [];
  var read = null, issues = [], hour = 0, focusPara = -1, timer = 0, saveTimer = 0;

  function store(k, v) {
    try {
      if (v === undefined) return localStorage.getItem(k);
      if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v);
    } catch (e) { return null; }
    return null;
  }
  function level(kt) { return kt >= 64 ? "hf" : kt >= 48 ? "storm" : kt >= 34 ? "gale" : "low"; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  // ---------------------------------------------------------------- basin and draft
  function setBasin(b) {
    basin = b;
    store("hsf-editor-basin", b);
    $("b-atl").setAttribute("aria-pressed", b === "atl");
    $("b-pac").setAttribute("aria-pressed", b === "pac");
    var u = new URL(location.href); u.searchParams.set("basin", b); history.replaceState(null, "", u);
    var d = draft();
    hour = 0; focusPara = -1;
    if (d && d.text) {
      ed.value = d.text;
      note(d.from ? "Draft from " + d.from : "Your saved draft");
      showSaved(d.saved);
      update();
    } else {
      ed.value = "";
      update();
      loadIssued(false);
    }
    if (map) map.fitBounds(BASINS[b].bounds, { padding: 20, duration: 0 });
    drawBoundary();
  }
  function draft() {
    try { return JSON.parse(store("hsf-editor-draft-" + basin) || "null"); } catch (e) { return null; }
  }
  function save() {
    var d = draft() || {};
    d.text = ed.value; d.saved = new Date().toISOString();
    store("hsf-editor-draft-" + basin, JSON.stringify(d));
    showSaved(d.saved);
  }
  function showSaved(iso) {
    if (!iso) { $("saved").textContent = ""; return; }
    var t = new Date(iso);
    $("saved").textContent = "Saved in this browser " + String(t.getUTCHours()).padStart(2, "0") + String(t.getUTCMinutes()).padStart(2, "0") + "Z";
  }
  function note(s) { $("note").textContent = s; }

  // ---------------------------------------------------------------- last issued product
  var MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  function opcPart(prod) {
    var s = prod.indexOf("SYNOPSIS VALID");
    if (s < 0) return null;
    var t = prod.slice(s);
    var f = t.indexOf(".FORECASTER");
    if (f > -1) t = t.slice(0, f);
    return t.replace(/\r/g, "").replace(/\s+$/, "") + "\n";
  }
  // "SYNOPSIS VALID 1200 UTC NOV 11." and the forecast valid lines, 6 hours on
  function bumpTimes(t, year) {
    return t.replace(/((?:SYNOPSIS|\d{1,2} HOUR FORECAST) VALID )(\d{2})(\d{2}) UTC ([A-Z]{3}) (\d{1,2})/g, function (x, head, hh, mm, mon, dd) {
      var m = MON.indexOf(mon);
      if (m < 0) return x;
      var d = new Date(Date.UTC(year, m, +dd, +hh, +mm) + 6 * 3600e3);
      var day = dd.length === 2 && dd[0] === "0" ? String(d.getUTCDate()).padStart(2, "0") : String(d.getUTCDate());
      return head + String(d.getUTCHours()).padStart(2, "0") + String(d.getUTCMinutes()).padStart(2, "0") + " UTC " + MON[d.getUTCMonth()] + " " + day;
    });
  }
  async function loadIssued(ask) {
    var B = BASINS[basin], from = basin;
    if (ask && ed.value.trim() && !(await confirmReplace("Replace the text with the last issued " + B.name + " forecast? Your current text is lost."))) return;
    note("Fetching the last issued " + B.name + " forecast...");
    var prod;
    try {
      var r = await fetch(IEM + B.pil, { cache: "no-store" });
      if (!r.ok) throw new Error("the archive answered HTTP " + r.status);
      prod = await r.text();
    } catch (e) {
      note("Could not reach the text archive (" + (e.message || e) + ")");
      return pasteIssued("The text archive could not be reached. Paste the last issued " + B.pil + " here (from AWIPS or ocean.weather.gov) and the page moves its valid times on 6 hours.");
    }
    if (from !== basin) return;
    useIssued(prod, B);
  }
  function useIssued(prod, B) {
    var t = opcPart(prod);
    if (!t) { note("That " + B.pil + " has no SYNOPSIS VALID line"); return pasteIssued("No SYNOPSIS VALID line was found. Paste the whole " + B.pil + " here."); }
    var iss = /\n(\d{3,4}) UTC \w{3} (\w{3}) (\d+) (\d{4})/.exec(prod);
    var year = iss ? +iss[4] : new Date().getUTCFullYear();
    var label = iss ? B.pil + " issued " + iss[1] + " UTC " + iss[2] + " " + iss[3] : B.pil;
    ed.value = bumpTimes(t, year);
    store("hsf-editor-draft-" + basin, JSON.stringify({ text: ed.value, from: label, saved: new Date().toISOString() }));
    showSaved(new Date().toISOString());
    note("Started from " + label + ", valid times moved on 6 h");
    hour = 0; focusPara = -1;
    update();
  }
  // when the archive cannot be reached: paste the issued product instead
  function pasteIssued(text) {
    var dlg = $("paste"), B = BASINS[basin];
    $("pasteText").textContent = text;
    $("pasteBox").value = "";
    $("pasteUse").onclick = function () { var v = $("pasteBox").value; dlg.close(); if (v.trim()) useIssued(v.toUpperCase(), B); };
    $("pasteNo").onclick = function () { dlg.close(); };
    if (dlg.showModal) dlg.showModal();
  }
  function confirmReplace(text) {
    var dlg = $("ask");
    if (!dlg.showModal) return Promise.resolve(window.confirm(text));
    $("askText").textContent = text;
    return new Promise(function (res) {
      function done(v) { return function () { dlg.close(); $("askYes").onclick = $("askNo").onclick = null; res(v); }; }
      $("askYes").onclick = done(true); $("askNo").onclick = done(false);
      dlg.showModal();
    });
  }

  // ---------------------------------------------------------------- wrap as you type
  // The paragraph the cursor is in ("." paragraph, up to a blank line or the next ".") is rewrapped at
  // the send width on every edit, as the product will be sent. Header lines, the valid-time lines and
  // the section names are left alone. The cursor keeps its place among the words.
  var W = (window.HsfCheck && HsfCheck.SEND_WIDTH) || 66, reflowing = false;
  function wrapWords(words) {
    var out = [], cur = "";
    words.forEach(function (w) {
      if (!cur) cur = w;
      else if (cur.length + 1 + w.length <= W) cur += " " + w;
      else { out.push(cur); cur = w; }
    });
    if (cur) out.push(cur);
    return out.join("\n");
  }
  function isHeader(line) { return /^\s*\.\.\..*\.\.\.\s*$/.test(line) || /^\s*\.[A-Z ]+\.\s*$/.test(line); }
  function reflow() {
    var v = ed.value, c = ed.selectionStart;
    if (c !== ed.selectionEnd) return;
    var lines = v.split("\n"), starts = [], o = 0, i, li = 0;
    for (i = 0; i < lines.length; i++) { starts.push(o); if (c >= o) li = i; o += lines[i].length + 1; }
    if (!lines[li].trim()) return;
    var a = li, b = li;
    var PSTART = /^\s*\.(?!\.)/;   // ".LOW ..." or ".24 HOUR FORECAST ..." ("..." starts no paragraph)
    if (isHeader(lines[li])) return;
    while (a > 0 && !PSTART.test(lines[a]) && lines[a - 1].trim() && !isHeader(lines[a - 1])) a--;
    while (b + 1 < lines.length && lines[b + 1].trim() && !PSTART.test(lines[b + 1]) && !isHeader(lines[b + 1])) b++;
    if (!PSTART.test(lines[a])) return;   // the valid-time lines at the top, or loose text
    var from = starts[a], to = starts[b] + lines[b].length, old = v.slice(from, to);
    var tail = /[ \t]+$/.exec(old), words = old.split(/\s+/).filter(Boolean);
    var neu = wrapWords(words) + (tail ? " " : "");
    if (neu === old) return;
    // where the cursor goes: after the same number of non-space characters (and a space, if it followed one)
    var before = v.slice(from, c), k = before.replace(/\s+/g, "").length, sp = /\s$/.test(before), at = 0, n = 0;
    while (at < neu.length && n < k) { if (!/\s/.test(neu[at])) n++; at++; }
    if (sp && at < neu.length && /\s/.test(neu[at])) at++;
    reflowing = true;
    ed.setSelectionRange(from, to);
    var ok = false;
    try { ok = document.execCommand("insertText", false, neu); } catch (e) { ok = false; }   // keeps undo
    if (!ok || ed.value.slice(from, from + neu.length) !== neu) ed.setRangeText(neu, from, to, "end");
    ed.setSelectionRange(from + at, from + at);
    reflowing = false;
  }

  // ---------------------------------------------------------------- read, check, draw
  function schedule() {
    clearTimeout(timer); timer = setTimeout(update, 180);
    clearTimeout(saveTimer); saveTimer = setTimeout(save, 800);
  }
  function update() {
    var t = ed.value;
    try { read = HsfRead.read(t, basin); } catch (e) { read = { paras: [], valid: {} }; console.error(e); }
    try { issues = HsfCheck.check(t, read); } catch (e) { issues = []; console.error(e); }
    drawIssues();
    followCursor(true);
    drawHours();
    drawMap();
  }
  function drawIssues() {
    var list = $("issueList");
    var n = { error: 0, warning: 0, info: 0 };
    issues.forEach(function (i) { n[i.sev]++; });
    $("issueHead").textContent = issues.length ? "Checks: " + [n.error && n.error + " error" + (n.error > 1 ? "s" : ""),
      n.warning && n.warning + " warning" + (n.warning > 1 ? "s" : ""), n.info && n.info + " map note" + (n.info > 1 ? "s" : "")].filter(Boolean).join(", ") : "Checks";
    if (!ed.value.trim()) { list.innerHTML = ""; return; }
    if (!issues.length) { list.innerHTML = '<li class="clean" style="cursor:default;display:block">All clear: no problems found, and every area is on the map.</li>'; return; }
    list.innerHTML = issues.map(function (i, k) {
      return '<li class="' + i.sev + '" data-k="' + k + '"><span class="sev">' + (i.sev === "info" ? "map" : i.sev) + "</span><span>" +
        esc(i.msg) + (i.word ? ": <b>" + esc(i.word) + "</b>" : "") + "</span></li>";
    }).join("");
  }
  $("issueList").addEventListener("click", function (e) {
    var li = e.target.closest("li[data-k]");
    if (!li) return;
    var i = issues[+li.getAttribute("data-k")];
    if (i) select(i.at, i.end);
  });
  function select(a, b) {
    ed.focus();
    ed.setSelectionRange(a, b);
    var lh = parseFloat(getComputedStyle(ed).lineHeight) || 19;
    var line = ed.value.slice(0, a).split("\n").length - 1;
    ed.scrollTop = Math.max(0, line * lh - ed.clientHeight / 3);
    followCursor(false);
  }

  function hoursOf() {
    var hs = {};
    Object.keys(read.valid || {}).forEach(function (h) { hs[+h] = 1; });
    read.paras.forEach(function (p) { if (p.blocks.length || p.lows.length) hs[p.hour] = 1; });
    if (!Object.keys(hs).length) hs[0] = 1;
    return Object.keys(hs).map(Number).sort(function (a, b) { return a - b; });
  }
  function vtShort(s) {   // "1200 UTC NOV 11" -> "12Z 11"
    var m = /^(\d{2})\d{2} UTC [A-Z]{3} (\d+)/.exec(s || "");
    return m ? m[1] + "Z " + m[2] : "";
  }
  function drawHours() {
    var hs = hoursOf();
    if (hs.indexOf(hour) < 0) hour = hs[0];
    $("hours").innerHTML = hs.map(function (h) {
      var vt = read.valid[h] ? vtShort(read.valid[h]) : "";
      return '<button data-h="' + h + '" aria-pressed="' + (h === hour) + '">' + (h ? h + " h" : "Synopsis") +
        (vt ? '<span class="vt">' + vt + "</span>" : "") + "</button>";
    }).join("");
  }
  $("hours").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-h]");
    if (!b) return;
    hour = +b.getAttribute("data-h");
    drawHours(); drawMap();
  });

  // the paragraph the cursor is in: its time goes on the map and its areas are outlined
  function followCursor(quiet) {
    if (!read) return;
    var c = ed.selectionStart, k = -1;
    read.paras.forEach(function (p, i) { if (c >= p.start && c <= p.end + 1) k = i; });
    var changed = k !== focusPara;
    focusPara = k;
    if (k > -1 && read.paras[k].hour !== hour && (read.paras[k].blocks.length || read.paras[k].lows.length || (read.paras[k].hazards || []).length)) {
      hour = read.paras[k].hour;
      if (!quiet) { drawHours(); drawMap(); return; }
    }
    if (changed && !quiet) drawMap();
  }
  ["keyup", "click", "select"].forEach(function (ev) { ed.addEventListener(ev, function () { followCursor(false); }); });
  ed.addEventListener("input", function (e) {
    if (!reflowing && (!e.inputType || /^(insert|delete)/.test(e.inputType)) && e.inputType !== "insertLineBreak") reflow();
    schedule();
  });

  // ---------------------------------------------------------------- map
  function features() {
    var f = [];
    read.paras.forEach(function (p, pi) {
      if (p.hour !== hour) return;
      p.blocks.forEach(function (b, bi) {
        if (!b.geom || !b.geom.length) return;
        f.push({ type: "Feature", properties: { pid: pi, bid: bi, top: b.wind[1], lvl: level(b.wind[1]), focus: pi === focusPara ? 1 : 0,
          tip: (p.warning ? p.warning + " WARNING: " : "") + (b.wind[0] ? b.wind[0] + " TO " : "TO ") + b.wind[1] + " KT" + (b.seas ? ", SEAS " + (b.seas[0] ? b.seas[0] + " TO " : "TO ") + b.seas[1] + " " + b.seas[2] : "") },
          geometry: { type: "MultiPolygon", coordinates: basin === "pac" ? shift(b.draw || b.geom) : (b.draw || b.geom) } });
      });
    });
    f.sort(function (a, b) { return a.properties.top - b.properties.top; });
    return { type: "FeatureCollection", features: f };
  }
  // your fog and freezing spray paragraphs at the time shown (grey dashed fog, teal spray, pink heavy)
  var HAZ = { fog: "#6b7280", spray: "#0e7490", heavy: "#be185d" };
  function hazardFeatures() {
    var f = [];
    read.paras.forEach(function (p, pi) {
      if (p.hour !== hour) return;
      (p.hazards || []).forEach(function (h) {
        var g = h.draw && h.draw.length ? h.draw : h.geom;
        if (!g || !g.length) return;
        f.push({ type: "Feature", properties: { pid: pi, focus: pi === focusPara ? 1 : 0, fog: h.kind === "fog" ? 1 : 0,
          colour: h.kind === "fog" ? HAZ.fog : h.level === "heavy" ? HAZ.heavy : HAZ.spray, tip: h.words },
          geometry: { type: "MultiPolygon", coordinates: basin === "pac" ? shift(g) : g } });
      });
    });
    return { type: "FeatureCollection", features: f };
  }
  function shift(g) { return g.map(function (p) { return p.map(function (r) { return r.map(function (q) { return [q[0] - 360, q[1]]; }); }); }); }
  // each warning block's main low through its forecast hours
  function trackFeatures() {
    var f = [], X = function (lon) { return basin === "pac" ? lon - 360 : lon; };
    (read.tracks || []).forEach(function (t) {
      var lvl = /HURRICANE/.test(t.warning) ? "hf" : /STORM/.test(t.warning) ? "storm" : /GALE/.test(t.warning) ? "gale" : "low";
      f.push({ type: "Feature", properties: { lvl: lvl }, geometry: { type: "LineString", coordinates: t.points.map(function (p) { return [X(p.lon), p.lat]; }) } });
      t.points.forEach(function (p) {
        f.push({ type: "Feature", properties: { lvl: lvl, now: p.hour === hour ? 1 : 0 }, geometry: { type: "Point", coordinates: [X(p.lon), p.lat] } });
      });
    });
    return { type: "FeatureCollection", features: f };
  }
  function drawMap() {
    if (!mapReady || !read) return;
    map.getSource("areas").setData(features());
    map.getSource("tracks").setData(trackFeatures());
    if (map.getSource("haz")) map.getSource("haz").setData(hazardFeatures());
    markers.forEach(function (m) { m.remove(); });
    markers = [];
    // hour labels on the track positions away from the time shown
    (read.tracks || []).forEach(function (t) {
      t.points.forEach(function (p) {
        if (p.hour === hour) return;
        var el = document.createElement("div");
        el.className = "trackpt";
        el.textContent = p.hour ? p.hour + "h" : "0h";
        markers.push(new maplibregl.Marker({ element: el, offset: [0, -11] }).setLngLat([basin === "pac" ? p.lon - 360 : p.lon, p.lat]).addTo(map));
      });
    });
    read.paras.forEach(function (p) {
      if (p.hour !== hour) return;
      p.lows.forEach(function (l) {
        var el = document.createElement("div");
        el.className = "lowmark " + l.kind;
        el.innerHTML = l.kind + (l.mb ? "<small>" + l.mb + "</small>" : "");
        markers.push(new maplibregl.Marker({ element: el }).setLngLat([basin === "pac" ? l.lon - 360 : l.lon, l.lat]).addTo(map));
      });
    });
  }
  function graticule() {
    var f = [], lon, lat;
    for (lon = -180; lon <= 180; lon += 10) { var l = []; for (lat = 20; lat <= 75; lat += 1) l.push([lon, lat]); f.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: l } }); }
    for (lat = 20; lat <= 75; lat += 10) { var m = []; for (lon = -180; lon <= 180; lon += 2) m.push([lon, lat]); f.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: m } }); }
    return { type: "FeatureCollection", features: f };
  }
  function drawBoundary() {
    if (!mapReady) return;
    // Pacific outline in -360..0 so it draws in the same world copy as the -190..-108 view
    var o = HsfRead.OUTLINES[basin].map(function (p) { return [basin === "pac" ? p[0] - 360 : p[0], p[1]]; });
    o.push(o[0]);
    map.getSource("boundary").setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: o } });
  }
  function initMap() {
    if (!window.maplibregl) { $("tip").textContent = "The map library did not load."; return; }
    map = new maplibregl.Map({
      container: "map", attributionControl: false, renderWorldCopies: true, dragRotate: false, pitchWithRotate: false,
      bounds: BASINS[basin].bounds, fitBoundsOptions: { padding: 20 },
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#e4ecf2" } }] }
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Land: Natural Earth" }));
    map.on("load", function () {
      map.addSource("grat", { type: "geojson", data: graticule() });
      map.addLayer({ id: "grat", type: "line", source: "grat", paint: { "line-color": "#c7d3dd", "line-width": 0.7 } });
      map.addSource("areas", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      var col = ["match", ["get", "lvl"], "hf", COLOURS.hf, "storm", COLOURS.storm, "gale", COLOURS.gale, COLOURS.low];
      map.addLayer({ id: "area-fill", type: "fill", source: "areas", paint: { "fill-color": col, "fill-opacity": ["case", ["==", ["get", "focus"], 1], 0.55, 0.38] } });
      map.addLayer({ id: "area-line", type: "line", source: "areas", paint: { "line-color": col, "line-width": 1.6 } });
      map.addSource("haz", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "haz-fill", type: "fill", source: "haz", paint: { "fill-color": ["get", "colour"], "fill-opacity": ["case", ["==", ["get", "focus"], 1], 0.28, 0.14] } });
      map.addLayer({ id: "haz-fog", type: "line", source: "haz", filter: ["==", ["get", "fog"], 1], paint: { "line-color": ["get", "colour"], "line-width": ["case", ["==", ["get", "focus"], 1], 2.6, 1.6], "line-dasharray": [3, 2] } });
      map.addLayer({ id: "haz-spray", type: "line", source: "haz", filter: ["==", ["get", "fog"], 0], paint: { "line-color": ["get", "colour"], "line-width": ["case", ["==", ["get", "focus"], 1], 2.6, 1.6], "line-dasharray": [1, 1.5] } });
      map.addSource("land", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "land", type: "fill", source: "land", paint: { "fill-color": "#f3eee2" } });
      map.addLayer({ id: "land-line", type: "line", source: "land", paint: { "line-color": "#b9ae96", "line-width": 0.7 } });
      map.addLayer({ id: "area-focus", type: "line", source: "areas", filter: ["==", ["get", "focus"], 1], paint: { "line-color": "#14213d", "line-width": 2.6 } });
      map.addSource("tracks", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "track-line", type: "line", source: "tracks", filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#14213d", "line-width": 1.8, "line-dasharray": [2, 1.5], "line-opacity": 0.85 } });
      map.addLayer({ id: "track-pts", type: "circle", source: "tracks", filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": ["case", ["==", ["get", "now"], 1], 0, 3.5], "circle-color": "#ffffff", "circle-stroke-color": "#14213d", "circle-stroke-width": 1.5 } });
      map.addSource("boundary", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#7a1f2b", "line-width": 1.6, "line-dasharray": [3, 2] } });
      fetch("../globe-kit/land.json").then(function (r) { return r.json(); }).then(function (j) { map.getSource("land").setData(j); }).catch(function () {});
      mapReady = true;
      drawBoundary();
      drawMap();
    });
    map.on("mousemove", "area-fill", function (e) {
      map.getCanvas().style.cursor = "pointer";
      var f = e.features[e.features.length - 1];
      for (var i = 0; i < e.features.length; i++) if (e.features[i].properties.top >= f.properties.top) f = e.features[i];
      $("tip").textContent = f.properties.tip + " (click to find it in the text)";
    });
    map.on("mouseleave", "area-fill", function () { map.getCanvas().style.cursor = ""; $("tip").textContent = ""; });
    map.on("click", "area-fill", function (e) {
      var f = e.features[0];
      e.features.forEach(function (g) { if (g.properties.top > f.properties.top) f = g; });
      var p = read.paras[f.properties.pid];
      if (p) select(p.start, p.end);
    });
    map.on("mousemove", "haz-fill", function (e) {
      if (map.queryRenderedFeatures(e.point, { layers: ["area-fill"] }).length) return;   // wind areas first
      map.getCanvas().style.cursor = "pointer";
      $("tip").textContent = e.features[0].properties.tip + " (click to find it in the text)";
    });
    map.on("mouseleave", "haz-fill", function () { map.getCanvas().style.cursor = ""; $("tip").textContent = ""; });
    map.on("click", "haz-fill", function (e) {
      if (map.queryRenderedFeatures(e.point, { layers: ["area-fill"] }).length) return;
      var p = read.paras[e.features[0].properties.pid];
      if (p) select(p.start, p.end);
    });
  }

  // ---------------------------------------------------------------- copy
  // Copies carry two forms. text/plain is the product as sent, for AWIPS and plain editors.
  // text/html is one paragraph per line with no spacing between them, in Courier New 9 pt, so
  // Google Docs and Word keep each 66-character line as it is: no wrap, no blank gaps.
  function productHTML(t) {
    var lines = t.replace(/\n$/, "").split("\n");
    return '<meta charset="utf-8"><div style="font-family:\'Courier New\',Courier,monospace;font-size:9pt">' + lines.map(function (l) {
      return '<p style="margin-top:0pt;margin-bottom:0pt;line-height:1.0"><span style="font-family:\'Courier New\',Courier,monospace;font-size:9pt">' +
        (l ? esc(l) : "<br>") + "</span></p>";
    }).join("") + "</div>";
  }
  function copy(text, btn, label) {
    if (!text) { flash(btn, "Nothing in this section", label); return; }
    var ok = function () { flash(btn, "Copied", label, true); };
    var bad = function () { fallback(text) ? ok() : flash(btn, "Copy failed", label); };
    if (navigator.clipboard && window.ClipboardItem && navigator.clipboard.write && window.isSecureContext) {
      navigator.clipboard.write([new ClipboardItem({
        "text/plain": new Blob([text], { type: "text/plain" }),
        "text/html": new Blob([productHTML(text)], { type: "text/html" })
      })]).then(ok, bad);
    } else bad();
  }
  function fallback(text) {
    // the old copy command, with both forms set in its copy event
    var set = function (e) { e.clipboardData.setData("text/plain", text); e.clipboardData.setData("text/html", productHTML(text)); e.preventDefault(); };
    document.addEventListener("copy", set);
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    document.removeEventListener("copy", set);
    return ok;
  }
  function flash(btn, msg, label, good) {
    btn.textContent = msg;
    if (good) btn.classList.add("done");
    setTimeout(function () { btn.textContent = label; btn.classList.remove("done"); }, 1500);
  }
  $("copyWarn").onclick = function () { copy(HsfCheck.section(HsfCheck.sendText(ed.value), ".WARNINGS."), this, "Copy Warnings box"); };
  $("copySyn").onclick = function () { copy(HsfCheck.section(HsfCheck.sendText(ed.value), ".SYNOPSIS AND FORECAST."), this, "Copy Synopsis box"); };
  $("copyAll").onclick = function () { copy(HsfCheck.sendText(ed.value), this, "Copy all"); };

  $("b-atl").onclick = function () { if (basin !== "atl") { save(); setBasin("atl"); } };
  $("b-pac").onclick = function () { if (basin !== "pac") { save(); setBasin("pac"); } };
  $("load").onclick = function () { loadIssued(true); };
  $("help").onclick = function () { var d = $("howto"); if (d.showModal) d.showModal(); };
  $("howtoClose").onclick = function () { $("howto").close(); };

  // a newer copy of the page is out: offer a reload (the draft is kept in this browser)
  var mine = (/[?&]v=([\w-]+)/.exec((document.querySelector('script[src*="app.js"]') || {}).src || "") || [])[1];
  async function checkVersion() {
    if (!mine || document.hidden) return;
    try {
      var html = await (await fetch(location.pathname + "?check=" + Date.now(), { cache: "no-store" })).text();
      var live = (/app\.js\?v=([\w-]+)/.exec(html) || [])[1];
      if (live && live !== mine) $("newer").hidden = false;
    } catch (e) { /* offline: try again later */ }
  }
  $("reload").onclick = function () { save(); location.reload(); };
  setInterval(checkVersion, 10 * 60e3);
  document.addEventListener("visibilitychange", checkVersion);

  initMap();
  setBasin(basin);
  // test hook (?test=1): lets a headless check read the page state
  if (q.get("test")) window.__hsfEditor = { read: function () { return read; }, issues: function () { return issues; }, hour: function () { return hour; } };
})();
