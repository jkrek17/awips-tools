// Offline tests of the HSF editor's reader and checks: node marine_wind/hsf_editor_page/tests/test_editor.js
// Fixtures are the issued 1630 UTC 11 Nov 2026 products (SYNOPSIS VALID to .FORECASTER).
"use strict";
var fs = require("fs"), path = require("path"), assert = require("assert");
var here = __dirname;
var R = require(path.join(here, "..", "hsf-read.js")), C = require(path.join(here, "..", "hsf-check.js"));
var atl = fs.readFileSync(path.join(here, "fixtures", "HSFAT1-2026111116.txt"), "utf8");
var pac = fs.readFileSync(path.join(here, "fixtures", "HSFEP1-2026111116.txt"), "utf8");
var n = 0;
function test(name, fn) { fn(); n++; console.log("ok  " + name); }

test("Atlantic: every area mapped, no checks fire", function () {
  var r = R.read(atl, "atl");
  var blocks = [].concat.apply([], r.paras.map(function (p) { return p.blocks; }));
  assert(blocks.length >= 7, "blocks " + blocks.length);
  blocks.forEach(function (b) { assert(b.ok, "not mapped: " + b.area_text); });
  assert.deepStrictEqual(C.check(atl, r), []);
  assert.strictEqual(r.valid[24], "1200 UTC NOV 12");
});

test("Atlantic box is the box the text names", function () {
  var g = R._areaGeom("FROM 43N TO 46N BETWEEN 46W AND 54W", "atl").geom;
  var xs = [], ys = [];
  g[0][0].forEach(function (q) { xs.push(q[0]); ys.push(q[1]); });
  assert.deepStrictEqual([Math.min.apply(0, xs), Math.max.apply(0, xs), Math.min.apply(0, ys), Math.max.apply(0, ys)], [-54, -46, 43, 46]);
});

test("Pacific: the slips in the issued product are caught", function () {
  var r = R.read(pac, "pac"), is = C.check(pac, r);
  function has(re) { return is.some(function (i) { return re.test(i.msg + ": " + i.word); }); }
  assert(has(/out of range: 51N189W/), "51N189W");
  assert(has(/Seas given in KT.*SEAS 8 TO 14 KT/), "seas in KT");
  assert(has(/Unrecognized word: SEMICIRICLE/), "SEMICIRICLE");
  assert(has(/Dots/), "dot run");
  assert(has(/map could not read.*40N133W 31N141W/), "FROM 40N133W AND 31N141W");
  // every issue points at text that holds its word
  is.forEach(function (i) { assert(i.end > i.at, "empty selection for " + i.msg); });
});

test("Pacific areas across the date line stay in 0-360", function () {
  var g = R._areaGeom("WITHIN 300 NM OF 50N180W", "pac", []).geom;
  g.forEach(function (p) { p[0].forEach(function (q) { assert(q[0] >= 172 && q[0] <= 190, q[0]); }); });
});

test("radial pieces, EXCEPT, Greenland and Bering wording", function () {
  var lows = [{ lat: 60, lon: -40, kind: "L", label: "" }];
  [["WITHIN 360 NM E...420 NM SE...AND 600 NM SW QUADRANTS", "atl", lows],
   ["BETWEEN 60 NM AND 180 NM NE...E...60 NM AND 240 NM SE AND 120 NM AND 300 NM SW QUADRANTS", "atl", lows],
   ["FROM 48N TO 63N BETWEEN 37W AND 54W...EXCEPT N OF 60N E OF GREENLAND", "atl", lows],
   ["N OF 64N E OF GREENLAND", "atl", lows],
   ["WITHIN 120 NM OF THE SE COAST OF GREENLAND N OF 60N", "atl", lows],
   ["IN THE BERING SEA N OF 61N W OF ALASKA", "pac", []],
   ["EXCEPT WHERE DESCRIBED WITH LOW 62N35W IN WARNINGS SECTION ABOVE...WITHIN 240 NM EITHER SIDE OF A LINE FROM 53N35W TO 43N60W AREA OF SW", "atl", []]
  ].forEach(function (c) {
    var a = R._areaGeom(c[0], c[1], c[2]);
    assert(a.ok && a.geom.length, "not mapped: " + c[0] + " [" + a.unread.join(" ") + "]");
  });
  var whole = R.areaOf(R._areaGeom("FROM 48N TO 63N BETWEEN 37W AND 54W", "atl").geom);
  var cut = R.areaOf(R._areaGeom("FROM 48N TO 63N BETWEEN 37W AND 54W...EXCEPT N OF 60N E OF GREENLAND", "atl").geom);
  assert(cut < whole * 0.97, "EXCEPT took nothing away");
});

test("send text: 66 characters, boxes without headers", function () {
  var s = C.sendText(pac.replace(/\n(?!\n|\.)/g, " "));   // a reflowed paste
  s.split("\n").forEach(function (l) { assert(l.length <= 66, l); });
  var w = C.section(s, ".WARNINGS."), y = C.section(s, ".SYNOPSIS AND FORECAST.");
  assert(/^\.\.\.HURRICANE FORCE WIND WARNING\.\.\./.test(w));
  assert(w.indexOf(".SYNOPSIS AND FORECAST.") < 0 && y.indexOf(".WARNINGS.") < 0);
});

test("lowercase and level checks", function () {
  var t = "SYNOPSIS VALID 1200 UTC NOV 11.\n\n.WARNINGS.\n\n...GALE WARNING...\n.LOW 47N51W 989 MB. WITHIN 120 NM s QUADRANT WINDS 50 TO 60 KT. SEAS 4 TO 6 M.\n\n.SYNOPSIS AND FORECAST.\n\n.LOW 40N50W 1000 MB. WITHIN 60 NM N QUADRANT WINDS 30 TO 35 KT. SEAS 3 TO 4 M.\n";
  var is = C.check(t, R.read(t, "atl")).map(function (i) { return i.msg; }).join("\n");
  assert(/Lowercase text/.test(is));
  assert(/Gale warning with winds to 60 KT/.test(is));
  assert(/Winds to 35 KT in the synopsis section/.test(is));
});

console.log(n + " tests passed");
