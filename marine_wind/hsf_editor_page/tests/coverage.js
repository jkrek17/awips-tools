// How much of the issued HSF the map reader can draw: node marine_wind/hsf_editor_page/tests/coverage.js [N] [show]
// Fetches the last N (default 400) HSFAT1 and HSFEP1 from the IEM text archive and prints, per basin, the share
// of areas mapped, of forecast times with every area mapped, and the commonest wording it could not read.
"use strict";
var path = require("path"), R = require(path.join(__dirname, "..", "hsf-read.js"));
var N = +(process.argv[2] || 400), show = +(process.argv[3] || 15);
var IEM = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?fmt=text&limit=";
(async function () {
  for (var x of [["HSFAT1", "atl"], ["HSFEP1", "pac"]]) {
    var raw = await (await fetch(IEM + N + "&pil=" + x[0])).text();
    var prods = raw.split("\x01").map(function (p) { return p.split("\x03")[0].trim(); }).filter(Boolean);
    var nb = 0, ok = 0, times = 0, timesOk = 0, bad = {}, nh = 0, okh = 0, badh = {};
    prods.forEach(function (p) {
      var byh = {};
      R.read(p.split(".FORECASTER")[0], x[1]).paras.forEach(function (pa) {
        (pa.hazards || []).forEach(function (h) {
          nh++; if (h.ok) okh++;
          else { var k = h.area_text.replace(/\d+(\.\d+)?[NS]\d+(\.\d+)?[EW]|\d+/g, "#").slice(0, 100); badh[k] = (badh[k] || 0) + 1; }
        });
        pa.blocks.forEach(function (b) {
          nb++; if (b.ok) ok++;
          byh[pa.hour] = (byh[pa.hour] || 0) + (b.ok ? 0 : 1);
          if (!b.ok) { var k = b.area_text.replace(/\d+(\.\d+)?[NS]\d+(\.\d+)?[EW]|\d+/g, "#").slice(0, 100); bad[k] = (bad[k] || 0) + 1; }
        });
      });
      Object.keys(byh).forEach(function (h) { times++; if (!byh[h]) timesOk++; });
    });
    console.log(x[0] + ": " + prods.length + " products, " + nb + " areas, " + (100 * ok / nb).toFixed(1) + "% mapped; " +
      (100 * timesOk / times).toFixed(1) + "% of forecast times fully mapped");
    console.log("  fog / freezing spray: " + nh + " areas, " + (100 * okh / Math.max(nh, 1)).toFixed(1) + "% mapped");
    Object.keys(badh).sort(function (a, b) { return badh[b] - badh[a]; }).slice(0, 5).forEach(function (k) { console.log("    " + badh[k] + "  " + k); });
    Object.keys(bad).sort(function (a, b) { return bad[b] - bad[a]; }).slice(0, show).forEach(function (k) { console.log("  " + bad[k] + "  " + k); });
  }
})();
