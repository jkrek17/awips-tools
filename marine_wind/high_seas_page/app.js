/* High Seas Draft: the newest first-guess HSF text (marine_wind/hsf/build_hsf.py, published with
   the marine wind data) and its areas on the shared globe (../globe-kit/). Plain ES2020. */
(function () {
  "use strict";
  var K, map, ov, doc = null, hour = 0;
  var $ = function (id) { return document.getElementById(id); };
  var DATA = "../marine-wind/data/hsf/pac.json";

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
    if (K.webgl()) {
      map = K.createMap({ start: { center: K.isMobile() ? [-160, 40] : [165, 45], zoom: K.isMobile() ? 1.6 : 2.4 }, credits: "Draft: marine wind blend, GFS-Wave" });
      ov = K.overlay(map, $("overlay"));
      map.on("render", labels);
      map.on("load", function () {
        map.addSource("areas", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "area-fill", type: "fill", source: "areas", paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.14 } });
        map.addLayer({ id: "area-line", type: "line", source: "areas", paint: { "line-color": ["get", "colour"], "line-width": 2 } });
        data.then(function () { show(hour); });
      });
    }
    data.then(function (d) { doc = d; render(); }, function () {
      $("runLine").textContent = "No draft published yet";
      $("text").textContent = "The draft is written after each marine wind data build. None is available right now.";
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
