/* High Seas Draft: the newest first-guess HSF text (marine_wind/hsf/build_hsf.py, published with
   the marine wind data) and its areas on the shared globe (../globe-kit/). Plain ES2020. */
(function () {
  "use strict";
  var K, map, ov, doc = null, hour = 0;
  var $ = function (id) { return document.getElementById(id); };
  // one draft per basin, each on the marine wind page's own box (the draft's own wind); ?basin=atl
  var BASINS = {
    pac: { name: "Pacific", box: "../marine-wind/data/npac/", start: [165, 45], mobile: [-160, 40] },
    atl: { name: "Atlantic", box: "../marine-wind/data/", start: [-52, 48], mobile: [-50, 45] }
  };
  // the wind grid each draft is written from (same pressure and seas): ?src=gfs
  var SOURCES = { corelift: "Core Lifted", gfs: "GFS", ecmwf: "ECMWF", aifs: "AIFS", ndfd: "NDFD" };
  var q = new URLSearchParams(location.search);
  var basin = (q.get("basin") || "pac").toLowerCase();
  if (!BASINS[basin]) basin = "pac";
  var src = (q.get("src") || "corelift").toLowerCase();
  if (!SOURCES[src]) src = "corelift";
  var B = BASINS[basin];
  // ?view=compare: the previous run's draft against the forecast the desk issued for it
  var compare = q.get("view") === "compare";
  var FILE = src === "corelift" ? basin : basin + "-" + src;
  var DATA = "../marine-wind/data/hsf/" + (compare ? "compare-" + basin : FILE) + ".json";
  function link(b, s, c) { return "?basin=" + b + (s === "corelift" ? "" : "&src=" + s) + (c ? "&view=compare" : ""); }
  var cmp = null, textTab = "issued";
  var LEVELS = { 34: "Gale", 48: "Storm", 64: "Hurricane force" };

  // the comparison file -> the shape the page draws (the chosen grid's draft) plus the issued areas
  function fromCompare(c) {
    cmp = c;
    var d = c.drafts[src] || c.drafts.corelift;
    return { cycle: d.cycle, synopsis: c.synopsis, hours: [0, 24, 48], text: c.issued_text, areas: d.areas,
             lows: d.lows, tracks: d.tracks, boundary: c.boundary, draft_text: d.text };
  }
  function k(n) { return Math.round(n / 1000) + "k"; }
  function statsHTML() {
    var rows = (cmp.stats[src] || []).filter(function (r) { return r.issued || r.draft; });
    if (!rows.length) return "<p>Neither the issued forecast nor the draft has gale force or more.</p>";
    return "<table><tr><th>Time</th><th>Level</th><th>Issued</th><th>Draft</th><th>Both</th></tr>" + rows.map(function (r) {
      return "<tr><td>" + (r.hour ? r.hour + " h" : "Synopsis") + "</td><td>" + LEVELS[r.level] + "</td><td>" + k(r.issued) +
        "</td><td>" + k(r.draft) + "</td><td>" + k(r.both) + "</td></tr>";
    }).join("") + "</table><p>Warned area in nm\u00b2 over open water, by the highest wind each area names.</p>";
  }
  function issuedFeatures(h) {
    return { type: "FeatureCollection", features: (cmp ? cmp.issued_areas : []).filter(function (a) { return a.hour === h; }).map(function (a) {
      return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: a.rings.map(function (r) { return r.map(function (p) { return [lon(p[0]), p[1]]; }); }) } };
    }) };
  }
  var BOX = B.box;
  var man = null, windCache = {};

  // wind classes as the text uses them, faint so the drawn areas stay on top
  function windRGBA(kt) {
    return kt >= 64 ? [168, 85, 247, 150] : kt >= 48 ? [239, 68, 68, 140] : kt >= 34 ? [245, 158, 11, 120]
      : kt >= 25 ? [56, 189, 248, 70] : null;
  }
  function mercY(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); }

  // the box's wind with storm cores kept at one lead, as a canvas in Mercator rows (an image
  // source is stretched linearly in Mercator)
  function windImage(lead) {
    if (windCache[lead]) return windCache[lead];
    windCache[lead] = fetch(BOX + "f" + ("00" + lead).slice(-3) + ".bin?t=" + encodeURIComponent(man.built)).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.arrayBuffer();
    }).then(function (buf) {
      var field = doc.wind_field || "windcore";
      var g = man.grid, k = man.fields.findIndex(function (f) { return f.name === field; }), f = man.fields[k];
      var raw = new Uint8Array(buf, k * g.ny * g.nx, g.ny * g.nx);
      var H = g.ny * 2, c = document.createElement("canvas");
      c.width = g.nx; c.height = H;
      var ctx = c.getContext("2d"), img = ctx.createImageData(g.nx, H);
      var y0 = mercY(g.north), y1 = mercY(g.south);
      for (var y = 0; y < H; y++) {
        var m = y0 + (y1 - y0) * (y + 0.5) / H;
        var lat = (2 * Math.atan(Math.exp(m)) - Math.PI / 2) * 180 / Math.PI;
        var row = Math.min(g.ny - 1, Math.max(0, Math.round((g.north - lat) / g.res)));
        for (var x = 0; x < g.nx; x++) {
          var c4 = windRGBA(raw[row * g.nx + x] / f.scale - (f.offset || 0));
          if (c4) img.data.set(c4, (y * g.nx + x) * 4);
        }
      }
      ctx.putImageData(img, 0, 0);
      return c.toDataURL();
    });
    return windCache[lead];
  }
  function showWind(h) {
    if (!map || !man || !doc || !map.getSource("wind")) return;
    if (doc.wind_source && !doc.wind_field) return;   // NDFD: no shading (its grid is not in the box)
    var lead = doc.box_leads ? doc.box_leads[String(h)] : 6 + h;
    windImage(lead).then(function (url) {
      if (hour !== h) return;
      var g = man.grid;
      map.getSource("wind").updateImage({ url: url, coordinates: [[lon(g.west), g.north], [lon(g.east), g.north], [lon(g.east), g.south], [lon(g.west), g.south]] });
    }, function () { K.note("Wind for this time is not available"); });
  }

  function colour(top) { return top >= 64 ? "#a855f7" : top >= 48 ? "#ef4444" : top >= 34 ? "#f59e0b" : "#38bdf8"; }
  // keep longitudes continuous: the Pacific box crosses the date line (0-360 east, drawn as
  // west of 0 = negative); the Atlantic already comes as -180..180
  function lon(x) { return basin === "pac" ? x - 360 : x; }

  function features(h) {
    return {
      type: "FeatureCollection",
      features: doc.areas.map(function (a, i) { return [a, i]; }).filter(function (x) { return x[0].hour === h; }).map(function (x) {
        var a = x[0];
        return { type: "Feature", properties: { colour: colour(a.wind[1]), letter: a.letter, i: x[1] },
                 geometry: { type: "Polygon", coordinates: a.rings.map(function (r) { return r.map(function (p) { return [lon(p[0]), p[1]]; }); }) } };
      })
    };
  }

  function labels() {
    if (!ov || !doc) return;
    ov.clear();
    var ctx = ov.ctx;
    ctx.font = "700 12px " + getComputedStyle(document.body).getPropertyValue("--mono");
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    (doc.lows || []).forEach(function (l) {
      if (l.hour !== hour) return;
      ov.proj(lon(l.lon), l.lat).forEach(function (p) {
        ctx.font = "800 20px " + getComputedStyle(document.body).getPropertyValue("--font");
        ctx.lineWidth = 3; ctx.strokeStyle = "rgba(7,13,25,0.9)"; ctx.strokeText("L", p.x, p.y);
        ctx.fillStyle = "#ef4444"; ctx.fillText("L", p.x, p.y);
        ctx.font = "700 11px " + getComputedStyle(document.body).getPropertyValue("--mono");
        ctx.strokeText(String(l.mb), p.x, p.y + 17); ctx.fillStyle = "#e7eef8"; ctx.fillText(String(l.mb), p.x, p.y + 17);
      });
    });
    ctx.font = "700 12px " + getComputedStyle(document.body).getPropertyValue("--mono");
    doc.areas.forEach(function (a) {
      if (a.hour !== hour || !a.rings.length) return;
      var r = a.rings[0], x = 0, y = 0;
      r.forEach(function (p) { x += p[0]; y += p[1]; });
      ov.proj(lon(x / r.length), y / r.length).forEach(function (p) {
        // each area labelled with its wind range, as in the text
        var t = a.wind[0] ? a.wind[0] + "-" + a.wind[1] : "TO " + a.wind[1], w = ctx.measureText(t).width + 10;
        ctx.fillStyle = "rgba(7,13,25,0.85)"; ctx.fillRect(p.x - w / 2, p.y - 9, w, 18);
        ctx.strokeStyle = colour(a.wind[1]); ctx.strokeRect(p.x - w / 2, p.y - 9, w, 18);
        ctx.fillStyle = "#e7eef8"; ctx.fillText(t, p.x, p.y + 0.5);
      });
    });
  }

  function show(h) {
    hour = h;
    document.querySelectorAll("#steps button").forEach(function (b) { b.setAttribute("aria-pressed", String(+b.dataset.h === h)); });
    if (map && map.getSource("areas")) map.getSource("areas").setData(features(h));
    if (map && map.getSource("issued")) map.getSource("issued").setData(issuedFeatures(h));
    showWind(h);
    var t = new Date(new Date(doc.synopsis).getTime() + h * 3600e3).toISOString();
    $("validTime").textContent = K.fmtValid(t);
    $("validRel").textContent = h ? "+" + h + " h from the synopsis" : "synopsis";
    labels();
  }

  // each area's phrase in the text, linked to its polygon: "<phrase> WINDS a TO b KT" (or
  // "<phrase>...AND" when areas with one wind range share a sentence), across line breaks;
  // hovering it shows that time and lights the polygon
  function esc(t) { return t.replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); }
  function linkText(text) {
    var spans = [];
    doc.areas.forEach(function (a, i) {
      var words = (a.text + " WINDS " + a.wind[0] + " TO " + a.wind[1] + " KT").split(/\s+/)
        .map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); });
      var n = words.length - 5;   // the phrase without "WINDS a TO b KT"
      var re = new RegExp(words.slice(0, n).join("\\s+") + "(?=\\s+(?:WINDS\\s+" + a.wind[0] + "\\s+TO\\s+" + a.wind[1] + "\\b|\\.\\.\\.AND))", "g"), m;
      while ((m = re.exec(text))) {
        var s = m.index, e = s + m[0].length;
        if (!spans.some(function (x) { return s < x.e && x.s < e; })) { spans.push({ s: s, e: e, i: i }); break; }
      }
    });
    spans.sort(function (x, y) { return x.s - y.s; });
    var html = "", pos = 0;
    spans.forEach(function (x) {
      html += esc(text.slice(pos, x.s)) + '<span class="hs-ar" data-i="' + x.i + '">' + esc(text.slice(x.s, x.e)) + "</span>";
      pos = x.e;
    });
    $("text").innerHTML = html + esc(text.slice(pos));
    document.querySelectorAll("#text .hs-ar").forEach(function (el) {
      el.addEventListener("mouseenter", function () { focusArea(+el.dataset.i, el); });
      el.addEventListener("mouseleave", function () { focusArea(-1, el); });
      el.addEventListener("click", function () { focusArea(+el.dataset.i, el, true); });
    });
  }
  function focusArea(i, el, fly) {
    document.querySelectorAll("#text .hs-ar.on").forEach(function (x) { x.classList.remove("on"); });
    ["area-focus", "area-focus-fill"].forEach(function (id) { if (map && map.getLayer(id)) map.setFilter(id, ["==", ["get", "i"], i]); });
    if (i < 0) return;
    el.classList.add("on");
    var a = doc.areas[i];
    if (a.hour !== hour) show(a.hour);
    if (fly && map && a.rings.length) {
      var xs = [], ys = [];
      a.rings[0].forEach(function (p) { xs.push(lon(p[0])); ys.push(p[1]); });
      map.fitBounds([[Math.min.apply(null, xs), Math.min.apply(null, ys)], [Math.max.apply(null, xs), Math.max.apply(null, ys)]], { padding: 120, maxZoom: 5, duration: 600 });
    }
  }

  function render() {
    $("runLine").textContent = compare ? "Issued vs draft from the " + K.fmtTime(doc.cycle) + " run"
      : "Draft from the " + K.fmtTime(doc.cycle) + " run";
    var shown = compare && textTab === "draft" ? doc.draft_text : doc.text;
    if (compare && textTab !== "draft") $("text").textContent = shown;
    else linkText(shown);
    if (compare) {
      $("cmpStats").innerHTML = statsHTML();
      $("textTabs").innerHTML = ["issued", "draft"].map(function (t) {
        return '<button type="button" data-t="' + t + '" aria-pressed="' + (t === textTab) + '">' + (t === "issued" ? "Issued text" : "Draft text") + "</button>";
      }).join("");
      document.querySelectorAll("#textTabs button").forEach(function (b) { b.addEventListener("click", function () { textTab = b.dataset.t; render(); }); });
    }
    var hours = doc.hours.filter(function (h) { return h === 0 || doc.areas.some(function (a) { return a.hour === h; }); });
    $("steps").innerHTML = hours.map(function (h) {
      return '<button type="button" data-h="' + h + '">' + (h ? h + " H" : "SYNOPSIS") + "</button>";
    }).join("");
    document.querySelectorAll("#steps button").forEach(function (b) { b.addEventListener("click", function () { show(+b.dataset.h); }); });
    show(0);
  }

  function start() {
    K = window.GlobeKit;
    document.title = "High Seas Draft · " + B.name;
    $("basinName").textContent = B.name;
    $("plainLink").href = "../marine-wind/data/hsf/" + FILE + ".txt";
    $("plainLink").hidden = compare;
    $("cmpLink").href = link(basin, src, !compare);
    $("cmpLink").textContent = compare ? "Back to the new draft" : "Compare with issued";
    $("cmpBox").hidden = !compare;
    document.querySelectorAll("#basins a").forEach(function (a) { a.href = link(a.dataset.basin, src, compare); a.setAttribute("aria-current", String(a.dataset.basin === basin)); });
    $("sources").innerHTML = Object.keys(SOURCES).map(function (s) {
      return '<a href="' + link(basin, s, compare) + '" aria-current="' + (s === src) + '">' + SOURCES[s] + "</a>";
    }).join("");
    $("shadeName").textContent = src === "ndfd" ? "none for NDFD" : SOURCES[src] + " wind";
    $("copyBtn").addEventListener("click", function () {
      if (!doc) return;
      navigator.clipboard.writeText(doc.text).then(function () { $("copyBtn").textContent = "Copied"; setTimeout(function () { $("copyBtn").textContent = "Copy text"; }, 1500); },
        function () { var r = document.createRange(); r.selectNodeContents($("text")); var s = getSelection(); s.removeAllRanges(); s.addRange(r); });
    });
    var data = fetch(DATA + "?t=" + Date.now()).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    // the box manifest, for the wind underneath; the draft must come from the same run
    var box = fetch(BOX + "manifest.json?t=" + Date.now()).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    data = Promise.all([data, box]).then(function (v) {
      var d = compare ? fromCompare(v[0]) : v[0];
      if (v[1] && v[1].cycle === d.cycle && !compare) man = v[1];
      return d;
    });
    if (K.webgl()) {
      map = K.createMap({ start: { center: K.isMobile() ? B.mobile : B.start, zoom: K.isMobile() ? 1.6 : 2.4 }, credits: "Draft: marine wind blend, GFS-Wave" });
      ov = K.overlay(map, $("overlay"));
      map.on("render", labels);
      map.on("load", function () {
        map.addSource("wind", { type: "image", url: (function () { var c = document.createElement("canvas"); c.width = c.height = 1; return c.toDataURL(); })(), coordinates: [[-95, 67], [10, 67], [10, 18], [-95, 18]] });
        map.addLayer({ id: "wind", type: "raster", source: "wind", paint: { "raster-opacity": 0.9, "raster-fade-duration": 0, "raster-resampling": "nearest" } });
        map.addSource("boundary", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#facc15", "line-width": 2.2, "line-dasharray": [3, 2], "line-opacity": 0.95 } });
        // each warning low's track through the page steps (the lows the text names)
        map.addSource("tracks", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "tracks", type: "line", source: "tracks", paint: { "line-color": "#f8fafc", "line-width": 1.6, "line-opacity": 0.85 } });
        map.addLayer({ id: "track-pts", type: "circle", source: "tracks", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 3, "circle-color": "#f8fafc", "circle-stroke-color": "#0a1120", "circle-stroke-width": 1 } });
        map.addSource("areas", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        // outlines only (a dark casing keeps them clear over the shading)
        map.addLayer({ id: "area-casing", type: "line", source: "areas", paint: { "line-color": "#0a1120", "line-width": 4.5, "line-opacity": 0.8 } });
        map.addLayer({ id: "area-line", type: "line", source: "areas", paint: { "line-color": ["get", "colour"], "line-width": 2.2 } });
        // the area whose phrase is under the pointer in the text
        map.addLayer({ id: "area-focus-fill", type: "fill", source: "areas", filter: ["==", ["get", "i"], -1], paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.12 } });
        map.addLayer({ id: "area-focus", type: "line", source: "areas", filter: ["==", ["get", "i"], -1], paint: { "line-color": "#ffffff", "line-width": 4 } });
        // the issued forecast's areas (compare view)
        map.addSource("issued", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "issued-line", type: "line", source: "issued", paint: { "line-color": "#f8fafc", "line-width": 2, "line-dasharray": [1.5, 1.5] } });
        data.then(function () {
          if (doc.boundary) {
            var b = doc.boundary.map(function (p) { return [lon(p[0]), p[1]]; });
            map.getSource("boundary").setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: b.concat([b[0]]) } });
          }
          var tf = [];
          (doc.tracks || []).forEach(function (t) {
            tf.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: t.points.map(function (p) { return [lon(p.lon), p.lat]; }) } });
            t.points.forEach(function (p) { tf.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon(p.lon), p.lat] } }); });
          });
          map.getSource("tracks").setData({ type: "FeatureCollection", features: tf });
          show(hour);
        });
      });
    }
    data.then(function (d) { doc = d; render(); }, function () {
      $("runLine").textContent = compare ? "No comparison yet" : "No draft published yet";
      $("text").textContent = "The draft is written after each marine wind data build. None is available right now.";
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
