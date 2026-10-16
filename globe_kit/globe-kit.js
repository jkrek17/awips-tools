/* Globe kit: the shared parts of the site's globe pages (marine-wind, cyclone),
   in the look of the /ndfd/ globe page. Served at /globe-kit/ beside the pages,
   which load it as ../globe-kit/globe-kit.js after ../globe-kit/lib/maplibre-gl.js
   and use it through window.GlobeKit:

   - createMap: a MapLibre GL globe over the Esri ocean basemap with the sky glow,
     zoom buttons, folded credits and a nautical scale;
   - overlay: a 2D canvas over the map for text and symbols, with a projection that
     skips points on the far side of the globe and near its rim when zoomed out
     (the pages load no map fonts, so all text goes here);
   - graticule and graticuleLabels: 10 degree lines and their labels;
   - land: the Natural Earth 50m land outline (land.json), and landRings, the same
     in Mercator world units for cutting land out of field tiles;
   - timeline: the ticks, the day labels and the "now" mark of the bottom bar;
   - icons, time and position formats, the panel toggle and the status note.

   The page keeps its own data, layers, legend and readout. Plain ES2020. */
(function () {
  "use strict";

  var K = {};
  var script = document.currentScript;
  K.base = script ? script.src.replace(/[^/]*$/, "") : "../globe-kit/";
  K.MAXLAT = 85.0511;
  K.ESRI_OCEAN = "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}";

  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- formats
  K.wrapLon = function (lon) { return ((lon + 180) % 360 + 360) % 360 - 180; };
  K.lonText = function (lon, dp) {
    var l = K.wrapLon(lon);
    if (Math.abs(Math.abs(l) - 180) < 1e-6) return "180";
    return Math.abs(l).toFixed(dp) + (l < 0 ? "W" : l > 0 ? "E" : "");
  };
  K.latText = function (lat, dp) { return Math.abs(lat).toFixed(dp) + (lat > 0 ? "N" : lat < 0 ? "S" : ""); };
  K.DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  K.MONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  K.pad = function (n) { return ("0" + n).slice(-2); };
  // "12Z 15 Oct", or "12Z Thu 15 Oct"
  K.fmtTime = function (iso, withDay) {
    var d = new Date(iso);
    return K.pad(d.getUTCHours()) + "Z " + (withDay ? K.DAYS[d.getUTCDay()] + " " : "") + d.getUTCDate() + " " + K.MONS[d.getUTCMonth()];
  };
  // "Thu 15 Oct · 12:00 UTC", the top bar's valid time
  K.fmtValid = function (iso) {
    var d = new Date(iso);
    return K.DAYS[d.getUTCDay()] + " " + K.pad(d.getUTCDate()) + " " + K.MONS[d.getUTCMonth()] + " · " + K.pad(d.getUTCHours()) + ":00 UTC";
  };
  K.isMobile = function () { return window.matchMedia("(max-width: 760px)").matches; };

  // ------------------------------------------------------------------ icons
  // as on /ndfd/
  K.ICONS = {
    layers: '<path d="M12 3 2 8l10 5 10-5-10-5Z"/><path d="m2 13 10 5 10-5"/><path d="m2 18 10 5 10-5" opacity=".5"/>',
    help: '<circle cx="12" cy="12" r="9.5"/><path d="M9.5 9.2a2.6 2.6 0 0 1 5 1c0 1.8-2.5 2.2-2.5 3.8"/><circle cx="12" cy="17.3" r=".6" fill="currentColor"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    prev: '<path d="M15 6l-6 6 6 6"/>',
    next: '<path d="M9 6l6 6-6 6"/>',
    play: '<path d="M8 5.5v13l10.5-6.5L8 5.5Z" fill="currentColor"/>',
    pause: '<path d="M8 5v14M16 5v14" stroke-width="3"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.8-4.8"/>'
  };
  K.icon = function (name) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round">' + K.ICONS[name] + "</svg>";
  };

  // -------------------------------------------------------------------- map
  K.webgl = function () {
    var c = document.createElement("canvas");
    return !!(window.maplibregl && (c.getContext("webgl2") || c.getContext("webgl")));
  };
  // the whole disc of the globe, between the top bar and the timeline
  K.globalZoom = function () {
    var h = window.innerHeight - (K.isMobile() ? 190 : 230), w = window.innerWidth - 24;
    return Math.max(0, Math.log2(Math.min(h, w) * 0.95 / 163));
  };
  // opts: container, start ({center, zoom} or {bounds, padding}), credits (data
  // credits beside the basemap's), nav (corner of the zoom buttons, default
  // top-right), maxZoom. Returns the map; listen for "load" to add layers.
  K.createMap = function (opts) {
    var o = {
      container: opts.container || "map",
      style: {
        version: 8,
        projection: { type: "globe" },
        // atmosphere glow round the globe, faded out before it hazes zoomed-in views (as on /ndfd/)
        sky: { "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 2.5, 1, 4, 0] },
        sources: { ocean: { type: "raster", tiles: [K.ESRI_OCEAN], tileSize: 256, maxzoom: 13, attribution: "Basemap &copy; Esri" } },
        layers: [{ id: "ocean", type: "raster", source: "ocean", paint: { "raster-saturation": -0.15, "raster-brightness-max": 0.95 } }]
      },
      minZoom: 0, maxZoom: opts.maxZoom || 9, attributionControl: false, keyboard: true, fadeDuration: 0
    };
    var s = opts.start || {};
    if (s.bounds) { o.bounds = s.bounds; o.fitBoundsOptions = { padding: s.padding || 20 }; }
    else { o.center = s.center || [-45, 28]; o.zoom = s.zoom != null ? s.zoom : K.globalZoom(); }
    var map = new maplibregl.Map(o);
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), opts.nav || "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: opts.credits || "" }), "bottom-left");
    map.addControl(new maplibregl.ScaleControl({ unit: "nautical" }), "bottom-left");
    map.on("load", function () {
      // the data credits start folded to the (i) button, so they never cover the map
      var at = map.getContainer().querySelector(".maplibregl-ctrl-attrib");
      if (at) at.classList.remove("maplibregl-compact-show");
    });
    return map;
  };

  // 10 degree lines to 80N and 80S, as one GeoJSON line feature
  K.graticule = function () {
    var f = [];
    for (var lon = -180; lon <= 180; lon += 10) { var c = []; for (var lat = -80; lat <= 80; lat += 2) c.push([lon, lat]); f.push(c); }
    for (var la = -80; la <= 80; la += 10) { var d = []; for (var lo = -180; lo <= 180; lo += 2) d.push([lo, la]); f.push(d); }
    return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: f } }] };
  };
  K.GRATICULE_PAINT = { "line-color": "rgba(231,238,248,0.12)", "line-width": 0.8 };

  // ---------------------------------------------------------------- overlay
  // A 2D canvas over the map (CSS #overlay), sized to it and redrawn by the page.
  K.overlay = function (map, canvas) {
    var ctx = canvas.getContext("2d");
    var ov = {
      canvas: canvas, ctx: ctx,
      w: function () { return canvas.clientWidth; },
      h: function () { return canvas.clientHeight; },
      size: function () {
        var box = map.getContainer(), dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(box.clientWidth * dpr); canvas.height = Math.round(box.clientHeight * dpr);
        canvas.style.width = box.clientWidth + "px"; canvas.style.height = box.clientHeight + "px";
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      },
      clear: function () { ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight); },
      // on the far side of the globe
      hidden: function (lon, lat) { return map.transform.isLocationOccluded(new maplibregl.LngLat(lon, lat)); },
      // zoomed out on the globe, text near the rim is foreshortened into a pile-up: leave it off
      nearRim: function (lon, lat) {
        if (map.getZoom() >= 3) return false;
        var c = map.getCenter(), r = Math.PI / 180;
        return Math.sin(c.lat * r) * Math.sin(lat * r) + Math.cos(c.lat * r) * Math.cos(lat * r) * Math.cos((lon - c.lng) * r) < 0.42;
      },
      // screen position of a lon/lat, as a list: empty when it is off screen, on the far
      // side of the globe or near its rim
      proj: function (lon, lat) {
        var w = canvas.clientWidth, h = canvas.clientHeight, c = map.getCenter().lng;
        lon = c + K.wrapLon(lon - c);
        if (ov.hidden(lon, lat) || ov.nearRim(lon, lat)) return [];
        var p = map.project([lon, lat]);
        return p.x > -60 && p.x < w + 60 && p.y > -30 && p.y < h + 30 ? [p] : [];
      }
    };
    map.on("resize", ov.size);
    ov.size();
    return ov;
  };

  // each graticule line labelled once, where it first shows from the left (parallels)
  // or the bottom (meridians) of the view, so the labels work on the globe and zoomed
  // in; top and bottom are the screen rows the labels stay between
  K.graticuleLabels = function (map, ov, top, bottom, fam) {
    var ctx = ov.ctx, w = ov.w(), h = ov.h();
    var z = map.getZoom(), stp = z >= 4 ? 10 : z >= 2 ? 20 : 30, c = map.getCenter();
    ctx.font = "10px " + fam; ctx.fillStyle = "rgba(231,238,248,0.6)";
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    var bot = Math.min(h, bottom);
    var span = z < 3 ? 180 : 90, d = z < 3 ? 2 : 0.5, cr = Math.PI / 180;
    var ok = function (p, ln, lt) {
      if (!(p.x >= 4 && p.x <= w - 40 && p.y >= top + 12 && p.y <= bot - 6)) return false;
      if (z >= 3) return true;
      // zoomed out, keep labels off the crowded rim of the globe
      var cosd = Math.sin(c.lat * cr) * Math.sin(lt * cr) + Math.cos(c.lat * cr) * Math.cos(lt * cr) * Math.cos((ln - c.lng) * cr);
      return cosd > 0.42;
    };
    for (var lat = -80; lat <= 80; lat += stp) {
      var best = null;
      for (var lo = -span; lo <= span; lo += d) {
        var ln = c.lng + lo;
        if (ov.hidden(ln, lat)) continue;
        var p = map.project([ln, lat]);
        if (ok(p, ln, lat) && (!best || p.x < best.x)) best = p;
      }
      if (best) ctx.fillText(K.latText(lat, 0), best.x + 3, best.y - 3);
    }
    for (var lon = Math.round((c.lng - span) / stp) * stp; lon <= c.lng + span; lon += stp) {
      var b2 = null;
      for (var la = -80; la <= 80; la += d) {
        if (ov.hidden(lon, la)) continue;
        var q = map.project([lon, la]);
        if (ok(q, lon, la) && (!b2 || q.y > b2.y)) b2 = q;
      }
      if (b2) ctx.fillText(K.lonText(lon, 0), b2.x + 3, b2.y - 3);
    }
  };

  // ------------------------------------------------------------------- land
  var landP = null;
  // Natural Earth 50m land (a GeoJSON MultiPolygon feature), fetched once
  K.land = function () {
    if (!landP) landP = fetch(K.base + "land.json").then(function (r) {
      if (!r.ok) throw new Error("land " + r.status);
      return r.json();
    });
    return landP;
  };
  // land in Mercator world units (0..1), ring by ring with its bounding box, to cut out
  // of field tiles so the basemap's land shows through and the coast stays sharp
  K.landRings = function (g) {
    var rings = [];
    g.geometry.coordinates.forEach(function (poly) {
      poly.forEach(function (ring) {
        var xs = [], ys = [], x0 = 1, x1 = 0, y0 = 1, y1 = 0;
        ring.forEach(function (c) {
          var lat = Math.max(-K.MAXLAT, Math.min(K.MAXLAT, c[1]));
          var x = (c[0] + 180) / 360, y = (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
          xs.push(x); ys.push(y);
          if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
        });
        rings.push({ xs: xs, ys: ys, box: [x0, y0, x1, y1] });
      });
    });
    return rings;
  };

  // --------------------------------------------------------------- timeline
  // The bottom bar's rail: a tick per valid time (ISO strings), days labelled at
  // 00 UTC and 12Z marked, the "now" mark where the clock falls inside the run.
  // Returns {done(i)}, which fills the rail up to step i.
  K.timeline = function (valid) {
    var ticks = $("tlTicks"), n = valid.length - 1;
    ticks.innerHTML = "";
    $("tlAvail").innerHTML = '<div class="done"></div>';
    valid.forEach(function (v, k) {
      var d = new Date(v), t = document.createElement("div");
      t.className = "tick";
      t.style.left = (n ? k / n * 100 : 0) + "%";
      if (d.getUTCHours() === 0) { t.classList.add("tick-day"); t.innerHTML = "<span>" + K.DAYS[d.getUTCDay()] + "<em> " + K.pad(d.getUTCDate()) + "</em></span>"; }
      else if (d.getUTCHours() === 12) { t.classList.add("tick-mid"); t.innerHTML = "<span>12Z</span>"; }
      ticks.appendChild(t);
    });
    function now() {
      var a = new Date(valid[0]).getTime(), b = new Date(valid[n]).getTime(), t = Date.now(), el = $("tlNow");
      el.hidden = !(t >= a && t <= b && b > a);
      if (!el.hidden) el.style.left = ((t - a) / (b - a) * 100) + "%";
    }
    now();
    setInterval(now, 60000);
    return {
      done: function (i) {
        var el = $("tlAvail").firstChild;
        if (el) el.style.width = (n > 0 ? i / n * 100 : 100) + "%";
      }
    };
  };

  // ------------------------------------------------------- panel and notes
  K.setPanelOpen = function (open) {
    document.body.classList.toggle("panel-open", open);
    var b = $("btnLayers");
    if (b) b.setAttribute("aria-expanded", String(open));
    var s = $("scrim");
    if (s) s.hidden = !(open && K.isMobile());
  };
  K.panelOpen = function () { return document.body.classList.contains("panel-open"); };
  // a passing message under the top bar (#status), cleared after 8 s
  var noteTimer = null;
  K.note = function (t) {
    var el = $("status");
    if (!el) return;
    el.textContent = t;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(function () { if (el.textContent === t) el.textContent = ""; }, 8000);
  };

  window.GlobeKit = K;
})();
