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
  // slips the map reads as meant, and still lists
  assert(has(/Mapped as LINE FROM 40N133W TO 31N141W: LINE FROM 40N133W AND 31N141W/), "FROM 40N133W AND 31N141W");
  assert(has(/Mapped as BETWEEN 128W AND 170W/), "FROM 128W AND 170W");
  assert(has(/Mapped as SEMICIRCLE: SEMICIRICLE/), "SEMICIRICLE on the map");
  assert(!has(/map could not/), "every Pacific area mapped");
  assert(has(/No latitude limits.*FROM 128W AND 170W/), "lone longitude band flagged");
  // ELSEWHERE is drawn outside the areas before it: W OF 163W loses the 163W-167W strip of E OF 167W
  var b = r.paras[0].blocks;
  assert.strictEqual(b[1].tier, "elsewhere");
  assert(R.areaOf(b[1].draw) < R.areaOf(b[1].geom) - 1, "elsewhere not cut");
  // "MB.FROM" with no space still reads the box
  var g = R.read(".WARNINGS.\n\n...GALE WARNING...\n.LOW 49N134W 996 MB.FROM 45N TO 50N BETWEEN 132W AND 142W WINDS 25 TO 35 KT. SEAS 3 TO 4 M.\n", "pac").paras[0].blocks[0];
  assert(g.ok && !g.open, "MB.FROM");
  // every issue points at text that holds its word
  is.forEach(function (i) { assert(i.end > i.at, "empty selection for " + i.msg); });
});

test("checks across forecast times", function () {
  var is = C.check(pac, R.read(pac, "pac"));
  function has(re) { return is.some(function (i) { return re.test(i.msg + ": " + i.word); }); }
  assert(has(/Low moves 96 KT from 50N174W \(synopsis\) to 51N189W/), "typed position as a jump");
  assert(has(/Gap between wind ranges: 50 TO 60 KT, then 35 TO 45 KT/), "gap between ranges");
  var t = ".WARNINGS.\n\n...STORM WARNING...\n.LOW 50N150W 990 MB. WITHIN 120 NM S SEMICIRCLE WINDS 40 TO 50 KT. SEAS 2 TO 3 M.\n" +
    ".48 HOUR FORECAST LOW 52N145W 960 MB. WITHIN 120 NM S SEMICIRCLE WINDS 40 TO 50 KT. SEAS 6 TO 9 M.\n" +
    ".24 HOUR FORECAST LOW 51N148W 975 MB. WITHIN 120 NM S SEMICIRCLE WINDS 40 TO 50 KT. SEAS 6 TO 9 M.\n";
  is = C.check(t, R.read(t, "pac"));
  assert(has(/Seas to 3 M are low for winds to 50 KT/), "seas for winds");
  assert(has(/24 HOUR FORECAST comes after the 48 HOUR FORECAST/), "hour order");
  assert(!has(/Low moves/), "slow low not flagged");
});

test("named coasts and Hecate Strait", function () {
  ["WITHIN 60 NM OF CALIFORNIA COAST FROM 34N TO 40N", "WITHIN 90 NM OF THE COAST OF VANCOUVER ISLAND", "WITHIN HECATE STRAIT",
    "WITHIN 120 NM NE AND E OF A FRONT TO EXTEND FROM 50N140W TO 45N145W", "WITHIN 60 NM ON EITHER SIDE OF A LINE FROM 50N140W TO 45N145W"
  ].forEach(function (s) { var g = R._areaGeom(s, "pac", []); assert(g.ok && g.geom.length, s); });
  var ca = R._areaGeom("WITHIN 60 NM OF CALIFORNIA COAST FROM 34N TO 40N", "pac", []).geom, ys = [];
  JSON.stringify(ca).replace(/\[(-?[\d.]+),(-?[\d.]+)\]/g, function (m, x, y) { ys.push(+y); });
  assert(Math.min.apply(0, ys) >= 34 && Math.max.apply(0, ys) <= 40, "California coast cut to 34N-40N");
  assert(R._areaGeom("WITHIN 60 NM OF THE LABRADOR COAST", "atl", []).ok, "Labrador");
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
