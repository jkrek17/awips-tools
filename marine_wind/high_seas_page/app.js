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
  // ?layout=block (one block, copy per paragraph), cards (a card per storm), list (storm list over the block)
  var LAYOUTS = { block: "One block", cards: "Storm cards", list: "Storm list" };
  var layout = (q.get("layout") || "block").toLowerCase();
  if (!LAYOUTS[layout]) layout = "block";
  var FILE = src === "corelift" ? basin : basin + "-" + src;
  var DATA = "../marine-wind/data/hsf/" + (compare ? "compare-" + basin : FILE) + ".json";
  function link(b, s, c, l) { l = l || layout; return "?basin=" + b + (s === "corelift" ? "" : "&src=" + s) + (c ? "&view=compare" : "") + (l === "block" ? "" : "&layout=" + l); }
  var cmp = null, textTab = "issued";
  var LEVELS = { 34: "Gale", 48: "Storm", 64: "Hurricane force" };

  // the comparison file -> the shape the page draws (the chosen grid's draft) plus the issued areas
  function fromCompare(c) {
    cmp = c;
    var d = c.drafts[src] || c.drafts.corelift;
    return { cycle: d.cycle, synopsis: c.synopsis, hours: [0, 24, 48], text: c.issued_text, areas: d.areas, hazards: d.hazards || [],
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
      features: doc.areas.map(function (a, i) { return [a, i]; }).filter(function (x) { return x[0].hour === h && inFocus(x[1]); }).map(function (x) {
        var a = x[0];
        return { type: "Feature", properties: { colour: colour(a.wind[1]), letter: a.letter, i: x[1] },
                 geometry: { type: "Polygon", coordinates: a.rings.map(function (r) { return r.map(function (p) { return [lon(p[0]), p[1]]; }); }) } };
      })
    };
  }

  // fog and freezing spray areas (synopsis, 24 h, 48 h), one switch for both; while a paragraph is
  // picked only that paragraph's kind is drawn
  var HAZ = { fog: "#d4d4d8", spray: "#67e8f9", heavy: "#f472b6" };
  var hazOn = true;
  try { hazOn = localStorage.getItem("hs-haz") !== "0"; } catch (e) { /* default on */ }
  function hazColour(a) { return a.kind === "fog" ? HAZ.fog : a.level === "heavy" ? HAZ.heavy : HAZ.spray; }
  function hazShown(a) { return hazOn && (focus < 0 || (paras[focus] && paras[focus].haz === a.kind)); }
  function hazFeatures(h) {
    return { type: "FeatureCollection", features: (doc.hazards || []).filter(function (a) { return a.hour === h && hazShown(a); }).map(function (a) {
      return { type: "Feature", properties: { colour: hazColour(a), fog: a.kind === "fog" },
               geometry: { type: "Polygon", coordinates: a.rings.map(function (r) { return r.map(function (p) { return [lon(p[0]), p[1]]; }); }) } };
    }) };
  }

  function labels() {
    if (!ov || !doc) return;
    ov.clear();
    var ctx = ov.ctx;
    ctx.font = "700 12px " + getComputedStyle(document.body).getPropertyValue("--mono");
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    (doc.lows || []).forEach(function (l) {
      if (l.hour !== hour) return;
      if (focus >= 0 && !paras[focus].lows[Math.round(l.lat) + "," + ((Math.round(l.lon) % 360) + 360) % 360]) return;
      ov.proj(lon(l.lon), l.lat).forEach(function (p) {
        ctx.font = "800 20px " + getComputedStyle(document.body).getPropertyValue("--font");
        ctx.lineWidth = 3; ctx.strokeStyle = "rgba(7,13,25,0.9)"; ctx.strokeText("L", p.x, p.y);
        ctx.fillStyle = "#ef4444"; ctx.fillText("L", p.x, p.y);
        ctx.font = "700 11px " + getComputedStyle(document.body).getPropertyValue("--mono");
        ctx.strokeText(String(l.mb), p.x, p.y + 17); ctx.fillStyle = "#e7eef8"; ctx.fillText(String(l.mb), p.x, p.y + 17);
      });
    });
    ctx.font = "700 11px " + getComputedStyle(document.body).getPropertyValue("--mono");
    (doc.hazards || []).forEach(function (a) {
      if (a.hour !== hour || !a.rings.length || !hazShown(a)) return;
      var r = a.rings[0], x = 0, y = 0;
      r.forEach(function (p) { x += p[0]; y += p[1]; });
      ov.proj(lon(x / r.length), y / r.length).forEach(function (p) {
        var t = a.kind === "fog" ? "FOG" : a.level === "heavy" ? "HVY SPRAY" : "SPRAY", w = ctx.measureText(t).width + 8;
        ctx.fillStyle = "rgba(7,13,25,0.8)"; ctx.fillRect(p.x - w / 2, p.y - 8, w, 16);
        ctx.fillStyle = hazColour(a); ctx.fillText(t, p.x, p.y + 0.5);
      });
    });
    ctx.font = "700 12px " + getComputedStyle(document.body).getPropertyValue("--mono");
    doc.areas.forEach(function (a, i) {
      if (a.hour !== hour || !a.rings.length || !inFocus(i)) return;
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
    if (map && map.getSource("hazards")) map.getSource("hazards").setData(hazFeatures(h));
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
    // the text in paragraphs (blocks between blank lines), each wrapped so it can be copied on
    // its own; the characters inside the <pre> stay exactly the product text
    var html = "", pos = 0, si = 0, re2 = /\n\n/g, m2, cuts = [0];
    while ((m2 = re2.exec(text))) cuts.push(m2.index + 1, m2.index + 2);
    cuts.push(text.length);
    function piece(a, b) {   // text a..b with its area spans
      var out = "";
      while (si < spans.length && spans[si].s >= a && spans[si].e <= b) {
        var x = spans[si++];
        out += esc(text.slice(a, x.s)) + '<span class="hs-ar" data-i="' + x.i + '">' + esc(text.slice(x.s, x.e)) + "</span>";
        a = x.e;
      }
      return out + esc(text.slice(a, b));
    }
    paras = [];
    var parts = [];   // in text order: {gap: html} or {p: index, html}
    for (var c = 0; c + 1 < cuts.length; c += 2) {
      var a = cuts[c], b = cuts[c + 1], body = text.slice(a, b), pi = paras.length;
      if (pos < a) parts.push({ gap: piece(pos, a) });   // the blank line between paragraphs
      // buttons only on forecast paragraphs, not the valid-time lines or section headers
      var own = /^(\.\.\.|\.)/.test(body) && !/^\.(WARNINGS|SYNOPSIS AND FORECAST)\.\s*$/.test(body);
      var hz = /^(?:\.\.\.HEAVY FREEZING SPRAY WARNING\.\.\.\s*)?\.(?:\d+ HOUR FORECAST )?(DENSE FOG|(?:LIGHT|MODERATE)[A-Z ]*FREEZING SPRAY)/.exec(body.replace(/\s+/g, " "));
      paras.push({ haz: hz ? (/FOG/.test(hz[1]) ? "fog" : "spray") : null, text: body.replace(/\n*$/, "") + "\n", own: own, track: own ? trackFor(body) : -1, info: own ? paraInfo(body) : null,
                   a: a, b: b, lows: lowsIn(body) });
      parts.push({ p: pi, html: piece(a, b) });
      pos = b;
    }
    var tail = piece(pos, text.length);
    // each area's paragraph: where its phrase sits in the text; an area whose phrase was not
    // found goes with the area before it (the areas come in text order)
    areaPara = doc.areas.map(function (a, i) {
      var sp = spans.filter(function (x) { return x.i === i; })[0];
      if (!sp) return -1;
      for (var k = 0; k < paras.length; k++) if (sp.s >= paras[k].a && sp.s < paras[k].b) return k;
      return -1;
    });
    for (var q2 = 1; q2 < areaPara.length; q2++) if (areaPara[q2] < 0) areaPara[q2] = areaPara[q2 - 1];
    function btns(pi) {
      return (paras[pi].own ? '<button type="button" class="hs-cp" data-p="' + pi + '" title="Copy this paragraph" aria-label="Copy this paragraph"></button>' : "") +
        (paras[pi].own ? '<button type="button" class="hs-go" data-p="' + pi + '" title="Show only this on the map (again for all)" aria-label="Show only this on the map"></button>' : "");
    }
    var el = $("text");
    el.className = "hs-text hs-lay-" + layout;
    if (layout === "cards") {
      // one card per paragraph: a header (level, low, peak wind, buttons) over the paragraph's text;
      // the header is not part of any copy
      html = parts.map(function (x) {
        if (x.gap !== undefined) return "";
        var P = paras[x.p];
        if (!P.own) return '<div class="hs-plain" data-p="' + x.p + '">' + x.html + "</div>";
        var I = P.info;
        return '<div class="hs-cardp hs-para" style="--lvl:' + I.colour + '" data-p="' + x.p + '"><div class="hs-ch" aria-hidden="false">' +
          '<b class="hs-lvl" style="--lvl:' + I.colour + '">' + I.level + "</b><span>" + esc(I.low) + "</span>" +
          (I.peak ? "<span>peak " + I.peak + " kt</span>" : "") + '<span class="hs-chb">' + btns(x.p) + "</span></div>" +
          '<div class="hs-cb">' + x.html.replace(/\n$/, "") + "</div></div>";
      }).join("") + (tail ? '<div class="hs-plain">' + tail + "</div>" : "");
    } else if (layout === "list") {
      // a short list of the storms at the top, then the product text as one block
      var rows = paras.map(function (P, i) { return [P, i]; }).filter(function (x) { return x[0].own; }).map(function (x) {
        var I = x[0].info;
        return '<div class="hs-ix" data-p="' + x[1] + '"><b class="hs-lvl" style="--lvl:' + I.colour + '">' + I.level + "</b>" +
          '<a href="#" class="hs-jump" data-p="' + x[1] + '">' + esc(I.low) + "</a>" + (I.peak ? "<span>peak " + I.peak + " kt</span>" : "<span></span>") +
          '<span class="hs-chb">' + btns(x[1]) + "</span></div>";
      }).join("");
      $("index").innerHTML = rows;
      html = parts.map(function (x) { return x.gap !== undefined ? x.gap : '<span class="hs-para" data-p="' + x.p + '">' + x.html + "</span>"; }).join("") + tail;
    } else {
      html = parts.map(function (x) { return x.gap !== undefined ? x.gap : '<span class="hs-para" data-p="' + x.p + '">' + btns(x.p) + x.html + "</span>"; }).join("") + tail;
    }
    $("index").hidden = layout !== "list";
    el.innerHTML = html;
    document.querySelectorAll("#index .hs-jump").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        var t = el.querySelector('.hs-para[data-p="' + a.dataset.p + '"]');
        var p = +a.dataset.p;
        setFocus(focus === p ? -1 : p);
        if (t && focus >= 0) el.scrollTop = t.offsetTop - el.offsetTop - 8;
      });
    });
    document.querySelectorAll("#text .hs-cp, #index .hs-cp").forEach(function (el) {
      el.addEventListener("click", function () { copyText(paras[+el.dataset.p].text, el); });
    });
    document.querySelectorAll("#text .hs-go, #index .hs-go").forEach(function (el) {
      el.addEventListener("click", function () { var p = +el.dataset.p; setFocus(focus === p ? -1 : p); });
    });
    document.querySelectorAll("#text .hs-ar").forEach(function (el) {
      el.addEventListener("mouseenter", function () { focusArea(+el.dataset.i, el); });
      el.addEventListener("mouseleave", function () { focusArea(-1, el); });
      el.addEventListener("click", function () { focusArea(+el.dataset.i, el, true); });
    });
  }
  var paras = [], shown = "";
  // a paragraph without a low: "AREA NEAR 38N36W", with the hour it starts if not the synopsis
  function areaName(flat) {
    var t = flat.replace(/^\.\.\..+?\.\.\. ?/, ""), h = /^\.(\d+) HOUR FORECAST/.exec(t);
    var pt = /(\d+N\d+[EW])/.exec(t), la = /(\d+N)\b/.exec(t), lo = /(\d+[EW])\b/.exec(t);
    var at = pt ? pt[1] : la && lo ? la[1] + lo[1] : "";
    return (at ? "AREA NEAR " + at : "AREA") + (h ? " FROM " + h[1] + " H" : "");
  }
  // a paragraph's level, first low and highest wind, for the card and list headers
  function paraInfo(body) {
    var fl = body.replace(/\s+/g, " ");
    if (/^\.(?:\d+ HOUR FORECAST )?DENSE FOG/.test(fl)) return { level: "FOG", colour: HAZ.fog, low: "DENSE FOG", peak: 0 };
    if (/FREEZING SPRAY/.test(fl.split(" ").slice(0, 8).join(" "))) {
      var hv = /HEAVY FREEZING SPRAY WARNING/.test(fl);
      return { level: hv ? "HVY SPRAY" : "SPRAY", colour: hv ? HAZ.heavy : HAZ.spray, low: "FREEZING SPRAY", peak: 0 };
    }
    var w = /^\.\.\.(.+?) WARNING\.\.\./.exec(body), hdr = w ? w[1] : "";
    // "HURRICANE FORCE WIND WARNING", "STORM WARNING", "GALE WARNING"
    var lvl = /HURRICANE/.test(hdr) ? "HURRICANE FORCE" : /STORM/.test(hdr) ? "STORM" : /GALE/.test(hdr) ? "GALE" : "SYNOPSIS";
    var m = /((?:NEW )?(?:COMPLEX )?LOW(?: WITH MAIN CENTER)? \d+N\d+[EW](?: \d+ MB)?)/.exec(body.replace(/\s+/g, " "));
    var peak = 0, re = /(\d+) KT/g, k;
    var flat = body.replace(/\s+/g, " ");
    while ((k = re.exec(flat))) if (!/MOVING \w+ $/.test(flat.slice(Math.max(0, k.index - 20), k.index))) peak = Math.max(peak, +k[1]);
    var colour = lvl === "HURRICANE FORCE" ? "#a855f7" : lvl === "STORM" ? "#ef4444" : lvl === "GALE" ? "#f59e0b" : "#94a3b8";
    var label = { "HURRICANE FORCE": "HF", STORM: "STORM", GALE: "GALE" }[lvl] || "NO WARN";
    return { level: label, colour: colour, low: m ? m[1] : areaName(flat), peak: peak };
  }
  // the warning low a paragraph is about: its first named centre, matched to a track point
  function trackFor(body) {
    var m = /LOW(?: WITH MAIN CENTER)? (\d+)N(\d+)([EW])/.exec(body);
    if (!m) return -1;
    var la = +m[1], lo = m[3] === "W" ? 360 - +m[2] : +m[2];
    return (doc.tracks || []).findIndex(function (t) {
      return t.points.some(function (p) { return Math.round(p.lat) === la && ((Math.round(p.lon) % 360) + 360) % 360 === lo % 360; });
    });
  }
  // ---- one storm at a time: the picker, the map buttons and the list rows set the focus
  var focus = -1, areaPara = [];
  function inFocus(i) { return focus < 0 || areaPara[i] === focus; }
  function posKey(la, lo, ew) { var x = ew === "W" ? 360 - lo : lo; return la + "," + ((x % 360) + 360) % 360; }
  function lowsIn(body) {   // the centres a paragraph names, as "lat,lon east"
    var out = {}, re = /(\d+)N(\d+)([EW]) \d+ MB/g, m, flat = body.replace(/\s+/g, " ");
    while ((m = re.exec(flat))) out[posKey(+m[1], +m[2], m[3])] = 1;
    return out;
  }
  function drawTracks() {
    if (!map || !map.getSource("tracks") || !doc) return;
    var tf = [];
    (doc.tracks || []).forEach(function (t, k) {
      if (focus >= 0 && paras[focus].track !== k) return;
      tf.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: t.points.map(function (p) { return [lon(p.lon), p.lat]; }) } });
      t.points.forEach(function (p) { tf.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon(p.lon), p.lat] } }); });
    });
    map.getSource("tracks").setData({ type: "FeatureCollection", features: tf });
  }
  function stormChips() {
    var list = paras.map(function (P, i) { return [P, i]; }).filter(function (x) { return x[0].own; });
    $("storms").innerHTML = '<button type="button" data-p="-1">All</button>' + list.map(function (x) {
      var I = x[0].info, at = /(\d+N\d+[EW])/.exec(I.low);
      return '<button type="button" data-p="' + x[1] + '" style="--lvl:' + I.colour + '"><i></i>' + (x[0].haz ? I.level : (I.level === "NO WARN" ? "" : I.level + " ") + (at ? at[1] : I.low)) + "</button>";
    }).join("");
    document.querySelectorAll("#storms button").forEach(function (b) { b.addEventListener("click", function () { setFocus(+b.dataset.p); }); });
  }
  function setFocus(p) {
    focus = p;
    document.querySelectorAll("#storms button").forEach(function (b) { b.setAttribute("aria-pressed", String(+b.dataset.p === p)); });
    $("text").classList.toggle("hs-focusing", p >= 0);
    document.querySelectorAll("#text [data-p].hs-para, #text .hs-plain, #index .hs-ix").forEach(function (x) {
      x.classList.toggle("off", p >= 0 && +x.dataset.p !== p);
    });
    document.querySelectorAll("#text .hs-go, #index .hs-go").forEach(function (b) { b.classList.toggle("on", +b.dataset.p === p); });
    // the times this storm has areas at; the others are hidden while it is picked
    var hrs = {};
    doc.areas.forEach(function (a, i) { if (inFocus(i)) hrs[a.hour] = 1; });
    var hzp = p >= 0 && paras[p] ? paras[p].haz : null;
    if (hzp) { hrs = {}; (doc.hazards || []).forEach(function (a) { if (a.kind === hzp) hrs[a.hour] = 1; }); }
    document.querySelectorAll("#steps button").forEach(function (b) { b.hidden = p >= 0 && !hrs[b.dataset.h] && +b.dataset.h !== 0; });
    drawTracks();
    var first = p >= 0 ? Math.min.apply(null, Object.keys(hrs).map(Number).concat([999])) : 0;
    show(p >= 0 && first < 999 ? (hrs[hour] ? hour : first) : hour);
    if (map) {
      var xs = [], ys = [];
      doc.areas.forEach(function (a, i) { if (p >= 0 && !hzp && inFocus(i)) a.rings.forEach(function (r) { r.forEach(function (q) { xs.push(lon(q[0])); ys.push(q[1]); }); }); });
      (doc.hazards || []).forEach(function (a) { if (hzp && a.kind === hzp) a.rings.forEach(function (r) { r.forEach(function (q) { xs.push(lon(q[0])); ys.push(q[1]); }); }); });
      var tr = p >= 0 ? (doc.tracks || [])[paras[p].track] : null;
      if (tr) tr.points.forEach(function (q) { xs.push(lon(q.lon)); ys.push(q.lat); });
      if (xs.length) map.fitBounds([[Math.min.apply(null, xs), Math.min.apply(null, ys)], [Math.max.apply(null, xs), Math.max.apply(null, ys)]], { padding: { top: 100, bottom: 60, left: Math.min(640, innerWidth / 2), right: 60 }, maxZoom: 5, duration: 600 });
    }
  }
  // plain text only on the clipboard (no page colours, padding or line spacing), so a paste
  // into email, an editor or AWIPS gets the product lines as written
  function copyText(t, btn) {
    function done() { if (!btn) return; btn.classList.add("ok"); setTimeout(function () { btn.classList.remove("ok"); }, 1500); }
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = t; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { if (document.execCommand("copy")) done(); } catch (e) { /* the text stays selected */ }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && window.isSecureContext && window.ClipboardItem && navigator.clipboard.write) {
      navigator.clipboard.write([new ClipboardItem({
        "text/plain": new Blob([t], { type: "text/plain" }),
        "text/html": new Blob([productHTML(t)], { type: "text/html" })
      })]).then(done, function () { navigator.clipboard.writeText(t).then(done, fallback); });
    } else if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(done, fallback);
    else fallback();
  }
  // The same text for word processors (Google Docs, Word, email): one paragraph per product line,
  // no spacing between them, in a monospace font small enough that a 68-character line fits a
  // page with wide margins (68 x 0.6 x 9 pt = 5.1 in), so the editor never wraps a line itself.
  // Plain-text targets (AWIPS, editors, paste without formatting) take the text/plain copy.
  function warningSection(t) {
    var a = t.search(/^\.WARNINGS\.\s*$/m);
    if (a < 0) return "";
    var b = t.slice(a).search(/^\.SYNOPSIS AND FORECAST\.\s*$/m);
    var sec = (b < 0 ? t.slice(a) : t.slice(a, a + b)).replace(/\s+$/, "");
    return /^\.\.\./m.test(sec) ? sec + "\n" : "";
  }
  function productHTML(t) {
    var lines = t.replace(/\n$/, "").split("\n");
    return '<meta charset="utf-8"><div style="font-family:\'Courier New\',Courier,monospace;font-size:9pt">' + lines.map(function (l) {
      return '<p style="margin-top:0pt;margin-bottom:0pt;line-height:1.0"><span style="font-family:\'Courier New\',Courier,monospace;font-size:9pt">' +
        (l ? esc(l) : "<br>") + "</span></p>";
    }).join("") + "</div>";
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
    shown = compare && textTab === "draft" ? doc.draft_text : doc.text;
    if (compare && textTab !== "draft") { $("text").className = "hs-text"; $("index").hidden = true; $("text").textContent = shown; }
    else linkText(shown);
    if (compare) {
      $("cmpStats").innerHTML = statsHTML();
      $("textTabs").innerHTML = ["issued", "draft"].map(function (t) {
        return '<button type="button" data-t="' + t + '" aria-pressed="' + (t === textTab) + '">' + (t === "issued" ? "Issued text" : "Draft text") + "</button>";
      }).join("");
      document.querySelectorAll("#textTabs button").forEach(function (b) { b.addEventListener("click", function () { textTab = b.dataset.t; render(); }); });
    }
    var hours = doc.hours.filter(function (h) { return h === 0 || doc.areas.concat(doc.hazards || []).some(function (a) { return a.hour === h; }); });
    $("steps").innerHTML = hours.map(function (h) {
      return '<button type="button" data-h="' + h + '">' + (h ? h + " H" : "SYNOPSIS") + "</button>";
    }).join("");
    document.querySelectorAll("#steps button").forEach(function (b) { b.addEventListener("click", function () { show(+b.dataset.h); }); });
    var ownText = !(compare && textTab !== "draft");
    $("stormRow").hidden = !ownText;
    if (ownText) { stormChips(); if (focus >= paras.length) focus = -1; setFocus(focus); }
    else { focus = -1; drawTracks(); show(0); }
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
    $("layouts").innerHTML = Object.keys(LAYOUTS).map(function (l) {
      return '<a href="' + link(basin, src, compare, l) + '" aria-current="' + (l === layout) + '">' + LAYOUTS[l] + "</a>";
    }).join("");
    $("shadeName").textContent = src === "ndfd" ? "none for NDFD" : SOURCES[src] + " wind";
    $("hazBtn").setAttribute("aria-pressed", String(hazOn));
    $("hazBtn").addEventListener("click", function () {
      hazOn = !hazOn;
      try { localStorage.setItem("hs-haz", hazOn ? "1" : "0"); } catch (e) { /* this visit only */ }
      $("hazBtn").setAttribute("aria-pressed", String(hazOn));
      if (doc) show(hour);
    });
    $("copyBtn").addEventListener("click", function () {
      if (!doc) return;
      var t = compare && textTab === "draft" ? doc.draft_text : doc.text, b = $("copyBtn");
      copyText(t, null);
      b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy all"; }, 1500);
    });
    // the warning section alone: from ".WARNINGS." up to ".SYNOPSIS AND FORECAST." (or the end)
    $("copyWarn").addEventListener("click", function () {
      if (!doc) return;
      var t = warningSection(compare && textTab === "draft" ? doc.draft_text : doc.text), b = $("copyWarn");
      if (!t) { b.textContent = "No warnings"; setTimeout(function () { b.textContent = "Copy warnings"; }, 1500); return; }
      copyText(t, null);
      b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy warnings"; }, 1500);
    });
    // a copy by hand from the text: plain text only (the buttons add nothing to it)
    // a copy by hand from the text: the product's own characters for the part selected, as plain
    // text only. The browser's own copy of a selection rebuilds the text from the layout and can
    // drop or add line breaks, so the selection is mapped back onto the product text instead.
    $("text").addEventListener("copy", function (e) {
      var sel = getSelection();
      if (!sel.rangeCount || sel.isCollapsed || !e.clipboardData || !shown) return;
      var r = sel.getRangeAt(0), el = $("text"), t;
      function off(box, node, o) {   // characters of box's text before (node, o)
        var x = document.createRange();
        x.selectNodeContents(box);
        try { x.setEnd(node, o); } catch (err) { return 0; }
        return x.toString().length;
      }
      function within(box, src) {
        var a = box.contains(r.startContainer) ? off(box, r.startContainer, r.startOffset) : 0;
        var b = box.contains(r.endContainer) ? off(box, r.endContainer, r.endOffset) : src.length;
        return src.slice(a, b);
      }
      if (!el.querySelector(".hs-cardp")) {
        t = el.textContent === shown ? within(el, shown) : String(sel);
      } else {
        var hit = [];
        el.querySelectorAll(".hs-cardp, .hs-plain").forEach(function (x) { if (r.intersectsNode(x) && x.dataset.p !== undefined) hit.push(x); });
        if (hit.length === 1) {
          var box = hit[0].querySelector(".hs-cb") || hit[0], src = paras[+hit[0].dataset.p].text.replace(/\n$/, "");
          t = box.textContent === src ? within(box, src) : String(sel);
        } else {
          // across cards: the whole paragraphs touched, with the product's blank lines between them
          t = hit.map(function (x) { return paras[+x.dataset.p].text; }).join("\n");
        }
      }
      t = t.replace(/\r\n?/g, "\n").replace(/[ \t\u00a0]+$/gm, "");
      e.clipboardData.setData("text/plain", t);
      e.clipboardData.setData("text/html", productHTML(t));
      e.preventDefault();
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
        // fog (dashed grey) and freezing spray (cyan; heavy pink) outlines
        map.addSource("hazards", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "haz-casing", type: "line", source: "hazards", paint: { "line-color": "#0a1120", "line-width": 3.5, "line-opacity": 0.7 } });
        map.addLayer({ id: "haz-fog", type: "line", source: "hazards", filter: ["==", ["get", "fog"], true], paint: { "line-color": ["get", "colour"], "line-width": 1.8, "line-dasharray": [2, 1.5] } });
        map.addLayer({ id: "haz-spray", type: "line", source: "hazards", filter: ["==", ["get", "fog"], false], paint: { "line-color": ["get", "colour"], "line-width": 1.8, "line-dasharray": [0.6, 1.2] } });
        // the issued forecast's areas (compare view)
        map.addSource("issued", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "issued-line", type: "line", source: "issued", paint: { "line-color": "#f8fafc", "line-width": 2, "line-dasharray": [1.5, 1.5] } });
        data.then(function () {
          if (doc.boundary) {
            var b = doc.boundary.map(function (p) { return [lon(p[0]), p[1]]; });
            map.getSource("boundary").setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: b.concat([b[0]]) } });
          }
          drawTracks();
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
