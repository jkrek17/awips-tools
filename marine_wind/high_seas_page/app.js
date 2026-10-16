/* High Seas Draft: the newest first-guess HSF text (marine_wind/hsf/build_hsf.py, published with
   the marine wind data) and its areas on the shared globe (../globe-kit/). Plain ES2020. */
(function () {
  "use strict";
  var K, map, ov, doc = null, hour = 0;
  var $ = function (id) { return document.getElementById(id); };
  var DATA = "../marine-wind/data/hsf/pac.json";
  var BOX = "../marine-wind/data/npac/";   // the marine wind page's Pacific box (the draft's own wind)
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
      var g = man.grid, k = man.fields.findIndex(function (f) { return f.name === "windcore"; }), f = man.fields[k];
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
    var lead = doc.box_leads ? doc.box_leads[String(h)] : 12 + h;
    windImage(lead).then(function (url) {
      if (hour !== h) return;
      var g = man.grid;
      map.getSource("wind").updateImage({ url: url, coordinates: [[lon(g.west), g.north], [lon(g.east), g.north], [lon(g.east), g.south], [lon(g.west), g.south]] });
    }, function () { K.note("Wind for this time is not available"); });
  }

  function colour(top) { return top >= 64 ? "#a855f7" : top >= 48 ? "#ef4444" : top >= 34 ? "#f59e0b" : "#38bdf8"; }
  // the Pacific box crosses the date line: keep longitudes continuous (west of 0 = negative)
  function lon(x) { return x - 360; }

  function features(h) {
    return {
      type: "FeatureCollection",
      features: doc.areas.filter(function (a) { return a.hour === h; }).map(function (a) {
        return { type: "Feature", properties: { colour: colour(a.wind[1]), letter: a.letter },
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
    showWind(h);
    var t = new Date(new Date(doc.synopsis).getTime() + h * 3600e3).toISOString();
    $("validTime").textContent = K.fmtValid(t);
    $("validRel").textContent = h ? "+" + h + " h from the synopsis" : "synopsis";
    labels();
  }

  function render() {
    $("runLine").textContent = "Draft from the " + K.fmtTime(doc.cycle) + " run";
    $("text").textContent = doc.text;
    var hours = doc.hours.filter(function (h) { return h === 0 || doc.areas.some(function (a) { return a.hour === h; }); });
    $("steps").innerHTML = hours.map(function (h) {
      return '<button type="button" data-h="' + h + '">' + (h ? h + " H" : "SYNOPSIS") + "</button>";
    }).join("");
    document.querySelectorAll("#steps button").forEach(function (b) { b.addEventListener("click", function () { show(+b.dataset.h); }); });
    show(0);
  }

  function start() {
    K = window.GlobeKit;
    $("copyBtn").addEventListener("click", function () {
      if (!doc) return;
      navigator.clipboard.writeText(doc.text).then(function () { $("copyBtn").textContent = "Copied"; setTimeout(function () { $("copyBtn").textContent = "Copy text"; }, 1500); },
        function () { var r = document.createRange(); r.selectNodeContents($("text")); var s = getSelection(); s.removeAllRanges(); s.addRange(r); });
    });
    var data = fetch(DATA + "?t=" + Date.now()).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    // the box manifest, for the wind underneath; the draft must come from the same run
    var box = fetch(BOX + "manifest.json?t=" + Date.now()).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    data = Promise.all([data, box]).then(function (v) {
      if (v[1] && v[1].cycle === v[0].cycle) man = v[1];
      return v[0];
    });
    if (K.webgl()) {
      map = K.createMap({ start: { center: K.isMobile() ? [-160, 40] : [165, 45], zoom: K.isMobile() ? 1.6 : 2.4 }, credits: "Draft: marine wind blend, GFS-Wave" });
      ov = K.overlay(map, $("overlay"));
      map.on("render", labels);
      map.on("load", function () {
        map.addSource("wind", { type: "image", url: (function () { var c = document.createElement("canvas"); c.width = c.height = 1; return c.toDataURL(); })(), coordinates: [[-225, 67], [-115, 67], [-115, 18], [-225, 18]] });
        map.addLayer({ id: "wind", type: "raster", source: "wind", paint: { "raster-opacity": 0.9, "raster-fade-duration": 0, "raster-resampling": "nearest" } });
        map.addSource("boundary", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#e7eef8", "line-width": 1.2, "line-dasharray": [3, 2], "line-opacity": 0.7 } });
        map.addSource("areas", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "area-fill", type: "fill", source: "areas", paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.14 } });
        map.addLayer({ id: "area-line", type: "line", source: "areas", paint: { "line-color": ["get", "colour"], "line-width": 2 } });
        data.then(function () {
          if (doc.boundary) {
            var b = doc.boundary.map(function (p) { return [lon(p[0]), p[1]]; });
            map.getSource("boundary").setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: b.concat([b[0]]) } });
          }
          show(hour);
        });
      });
    }
    data.then(function (d) { doc = d; render(); }, function () {
      $("runLine").textContent = "No draft published yet";
      $("text").textContent = "The draft is written after each marine wind data build. None is available right now.";
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
