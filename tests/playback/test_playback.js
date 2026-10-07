#!/usr/bin/env node
/* Tests for docs/assets/js/playback.js (the storm-track playback engine).
   The rest of tests/ is Python; this needs only Node (no packages, no test
   runner - node:assert and a tiny harness below).

     node tests/playback/test_playback.js

   playback.js and util.js are plain browser scripts that attach to
   window.HF, so they are loaded into a vm context with a fake `window`
   rather than being modified to export anything. The last block runs the
   engine over the real archive (docs/data/hf-lows.json) as a smoke test. */

var fs = require('fs');
var path = require('path');
var vm = require('vm');
var assert = require('assert');

var ROOT = path.join(__dirname, '..', '..');
var ctx = { window: {} };
vm.createContext(ctx);
['util.js', 'playback.js'].forEach(function (f) {
  var file = path.join(ROOT, 'docs', 'assets', 'js', f);
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: file });
});
var HF = ctx.window.HF;
var PB = HF.playback;

var passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('  ok   ' + name); }
  catch (e) { failed++; console.log('  FAIL ' + name + '\n       ' + (e && e.message)); }
}
function near(a, b, tol, msg) {
  assert.ok(Math.abs(a - b) <= tol, (msg || 'values differ') + ': ' + a + ' vs ' + b + ' (tol ' + tol + ')');
}
function fix(date, lat, lon, pres) { return { date: date, lat: lat, lon: lon, cat: 'HF', pres: pres === undefined ? 980 : pres }; }
function low(id, season, fixes, extra) {
  var l = { id: id, basin: 'atl', season: season, cls: 'low', fixes: fixes, minP: 970,
            start: fixes[0].date, end: fixes[fixes.length - 1].date };
  l.key = l.basin + ':' + l.id;
  for (var k in extra) l[k] = extra[k];
  return l;
}
// great-circle distance in km, independent of the code under test
function distKm(lat1, lon1, lat2, lon2) {
  var r = Math.PI / 180, p1 = lat1 * r, p2 = lat2 * r, dl = (lon2 - lon1) * r;
  var c = Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(dl);
  return 6371.0088 * Math.acos(Math.max(-1, Math.min(1, c)));
}
var H = function (n) { return PB.toHours(n); };
// Objects built inside the vm context have that context's Object.prototype,
// so assert.deepStrictEqual (which compares prototypes) rejects them against
// literals made out here. Compare by value instead.
function same(a, b, msg) { assert.strictEqual(JSON.stringify(a), JSON.stringify(b), msg); }

console.log('time parsing');

test('parse YYYYMMDDHH including hour 00', function () {
  same(PB.parse(2002020400), { year: 2002, month: 2, day: 4, hour: 0 });
  same(PB.parse(2020123123), { year: 2020, month: 12, day: 31, hour: 23 });
  same(PB.parse(2001070100), { year: 2001, month: 7, day: 1, hour: 0 });
});

test('toHours is exact across month, year and leap-day boundaries', function () {
  assert.strictEqual(H(2001010200) - H(2001010100), 24);
  assert.strictEqual(H(2001020100) - H(2001013123), 1);          // month boundary, 31 -> 1
  assert.strictEqual(H(2001030100) - H(2001022818), 6);          // non-leap Feb has 28 days
  assert.strictEqual(H(2004030100) - H(2004022818), 30);         // leap Feb has 29
  assert.strictEqual(H(2100030100) - H(2100022818), 6);          // 2100 is NOT leap (century rule)
  assert.strictEqual(H(2000030100) - H(2000022818), 30);         // 2000 IS leap
  assert.strictEqual(H(2002010100) - H(2001123123), 1);          // year boundary
  assert.strictEqual(H(1970010100), 0);
});

test('fromHours inverts toHours', function () {
  [1970010100, 2001123123, 2004022900, 2016122006, 2026013018, 2100030100].forEach(function (n) {
    assert.strictEqual(PB.fromHours(H(n)), n);
  });
  assert.strictEqual(PB.fromHours(H(2002020418) + 0.9), 2002020418);   // floors to the hour
});

console.log('season assignment');

test('a January event belongs to the season that began the previous July', function () {
  assert.strictEqual(PB.seasonOfDate(2002011500), 2001);
  assert.strictEqual(PB.seasonOfDate(2002063018), 2001);
  assert.strictEqual(PB.seasonOfDate(2001070100), 2001);
  assert.strictEqual(PB.seasonOfDate(2001123100), 2001);
});

test('every archive event starting Jan-May has season = year - 1 (June is checked separately: see report, 6 early-June events are labelled with the NEXT season)', function () {
  var D = realData();
  var bad = 0;
  D.lows.forEach(function (l) {
    var m = Math.floor(l.start / 10000) % 100;
    if (m <= 5 && PB.seasonOfDate(l.start) !== l.season) bad++;
  });
  assert.strictEqual(bad, 0);
});

console.log('composite axis, leap years');

test('1 Jul 00Z is the axis origin and 30 Jun 18Z is the last slot', function () {
  assert.strictEqual(PB.compositeHour(2001070100), 0);
  assert.strictEqual(PB.compositeHour(2002063018), 366 * 24 - 6);
  assert.strictEqual(PB.COMPOSITE_PERIOD_H, 8784);
});

test('the same calendar date lands on the same slot in leap and non-leap seasons', function () {
  // 2003-04 has no 29 Feb, 2007-08 does (Feb 2008). Everything from 1 Mar on
  // must NOT slide by a day between them - that is the smear to avoid.
  [114, 228, 301, 415, 630].forEach(function (md) {
    var normal = PB.compositeHour(2004 * 1000000 + Number(md) * 100 + 6);       // season 2003 (no leap day)
    var leap = PB.compositeHour(2008 * 1000000 + Number(md) * 100 + 6);         // season 2007 (leap day)
    assert.strictEqual(normal, leap, md + ' slides between leap and non-leap seasons');
  });
});

test('29 Feb has its own slot, between 28 Feb and 1 Mar', function () {
  var d28 = PB.compositeHour(2008022800), d29 = PB.compositeHour(2008022900), m1 = PB.compositeHour(2008030100);
  assert.strictEqual(d29 - d28, 24);
  assert.strictEqual(m1 - d29, 24);
  // and a normal year's 28 Feb -> 1 Mar skips that slot (30 axis hours for a 6 h step)
  assert.strictEqual(PB.compositeHour(2005030100) - PB.compositeHour(2005022818), 30);
});

test('composite labels have no year and show 29 Feb', function () {
  assert.strictEqual(PB.compositeLabel(0), '1 Jul');
  assert.strictEqual(PB.compositeLabel(PB.compositeHour(2002011406)), '14 Jan');
  assert.strictEqual(PB.compositeLabel(PB.compositeHour(2008022912)), '29 Feb');
  assert.strictEqual(PB.compositeLabel(PB.COMPOSITE_PERIOD_H), '30 Jun');   // clamped, not wrapped to 1 Jul
  var c = PB.create([]).composite();
  assert.strictEqual(c.label(PB.compositeHour(2002011406)), '14 Jan');
  assert.ok(!/\d{4}/.test(c.label(1234)));
});

test('composite: storms from different seasons are active together, and a normal- and leap-year storm on the same date coincide', function () {
  var a = low('a', 2003, [fix(2004030100, 40, -50), fix(2004030200, 42, -48)]);
  var b = low('b', 2007, [fix(2008030100, 41, -30), fix(2008030200, 43, -28)]);
  var c = PB.create([a, b]).composite();
  var f = c.at(PB.compositeHour(2004030112), 0);
  assert.strictEqual(f.storms.length, 2);
  near(f.storms[0].lat, 41, 0.05);
  near(f.storms[1].lat, 42, 0.05);
});

test('composite: a storm crossing 30 Jun -> 1 Jul stays continuous across the wrap', function () {
  var s = low('w', 2001, [fix(2002063012, 50, -40), fix(2002063018, 50, -38), fix(2002070100, 50, -36), fix(2002070106, 50, -34)]);
  var c = PB.create([s]).composite();
  var late = c.at(8784 - 3, 0), early = c.at(3, 0);        // 30 Jun 21Z and 1 Jul 03Z
  assert.strictEqual(late.storms.length, 1);
  assert.strictEqual(early.storms.length, 1);
  near(late.storms[0].lon, -37, 0.05);
  near(early.storms[0].lon, -35, 0.05);
  // tail at 1 Jul 03Z reaches back across the seam to 30 Jun
  var ft = c.at(3, 12);
  assert.strictEqual(ft.storms[0].tail[0].age, 12);
  near(ft.storms[0].tail[0].lon, -39, 0.05);
});

console.log('interpolation');

var TRACK = low('t', 2001, [fix(2001120100, 40, -50, 980), fix(2001120106, 44, -46, 970), fix(2001120112, 46, -40, 960)]);

test('a point exactly on a fix returns that fix, untouched', function () {
  var s = PB.create([TRACK]).season(2001);
  var st = s.at(H(2001120106), 0).storms[0];
  assert.strictEqual(st.lat, 44);
  assert.strictEqual(st.lon, -46);
  assert.strictEqual(st.pres, 970);
  var first = s.at(H(2001120100), 0).storms[0], last = s.at(H(2001120112), 0).storms[0];
  assert.strictEqual(first.lat, 40);
  assert.strictEqual(last.lon, -40);
});

test('exact fix at lon = -180 is not perturbed by the slerp round trip', function () {
  var l = low('e', 2001, [fix(2002010100, 50, -180), fix(2002010106, 50, 179)]);
  var st = PB.create([l]).season(2001).at(H(2002010100), 0).storms[0];
  assert.strictEqual(st.lon, -180);
});

test('midpoint between two fixes lands on the great-circle midpoint', function () {
  var s = PB.create([TRACK]).season(2001);
  var st = s.at(H(2001120103), 0).storms[0];
  // independent check: the midpoint is equidistant from both ends, and
  // both halves sum to the full arc (it lies ON the arc).
  var d1 = distKm(40, -50, st.lat, st.lon), d2 = distKm(st.lat, st.lon, 44, -46), full = distKm(40, -50, 44, -46);
  near(d1, d2, 0.01, 'not equidistant');
  near(d1 + d2, full, 0.01, 'off the arc');
  near(st.pres, 975, 1e-9);                       // pressure interpolates linearly
});

test('fraction other than a half interpolates proportionally (not nearest fix)', function () {
  var st = PB.create([TRACK]).season(2001).at(H(2001120100) + 1.5, 0).storms[0];   // 25% of the way
  var full = distKm(40, -50, 44, -46);
  near(distKm(40, -50, st.lat, st.lon), full * 0.25, 0.05);
  near(st.pres, 977.5, 1e-9);
});

test('a t outside a storm span excludes it, inclusive at both ends', function () {
  var s = PB.create([TRACK]).season(2001);
  assert.strictEqual(s.at(H(2001120100) - 0.01, 0).storms.length, 0);
  assert.strictEqual(s.at(H(2001120100), 0).storms.length, 1);
  assert.strictEqual(s.at(H(2001120112), 0).storms.length, 1);
  assert.strictEqual(s.at(H(2001120112) + 0.01, 0).storms.length, 0);
});

test('a single-fix storm is visible for one analysis cycle, not one instant', function () {
  var l = low('one', 2001, [fix(2002010112, 55, -30)]);
  var s = PB.create([l]).season(2001);
  assert.strictEqual(s.at(H(2002010112) - 2, 0).storms.length, 1);
  assert.strictEqual(s.at(H(2002010112) + 2, 0).storms.length, 1);
  assert.strictEqual(s.at(H(2002010112) + 4, 0).storms.length, 0);
  var st = s.at(H(2002010112) + 2, 12).storms[0];
  assert.strictEqual(st.lat, 55);
  assert.strictEqual(st.tail.length, 1);
});

test('duplicate timestamps never produce NaN; head moves on to the later fix', function () {
  var l = low('dup', 2001, [fix(2002010100, 40, -50), fix(2002010106, 41, -49), fix(2002010106, 44, -45), fix(2002010112, 45, -44)]);
  var s = PB.create([l]).season(2001);
  var on = s.at(H(2002010106), 0).storms[0];
  assert.strictEqual(on.lat, 44);
  var before = s.at(H(2002010106) - 3, 0).storms[0], after = s.at(H(2002010106) + 3, 0).storms[0];
  [before, after].forEach(function (st) { assert.ok(isFinite(st.lat) && isFinite(st.lon)); });
  assert.ok(before.lat > 40 && before.lat < 41);
  assert.ok(after.lat > 44 && after.lat < 45);
});

test('missing pressure: falls back to the known end, null when both are missing', function () {
  var l = low('np', 2001, [fix(2002010100, 40, -50, null), fix(2002010106, 41, -49, 970), fix(2002010112, 42, -48, null)]);
  var s = PB.create([l]).season(2001);
  assert.strictEqual(s.at(H(2002010100), 0).storms[0].pres, null);
  assert.strictEqual(s.at(H(2002010103), 0).storms[0].pres, 970);
  var tj = low('tj', 2001, [fix(2002010100, 61, -40, null), fix(2002010106, 62, -39, null)], { cls: 'tipjet' });
  var st = PB.create([tj]).season(2001).at(H(2002010103), 6).storms[0];
  assert.strictEqual(st.pres, null);
  assert.strictEqual(st.cls, 'tipjet');
  st.tail.forEach(function (p) { assert.strictEqual(p.pres, null); });
});

test('identity fields for styling and hit-testing', function () {
  var st = PB.create([TRACK]).season(2001).at(H(2001120103), 0).storms[0];
  assert.strictEqual(st.key, 'atl:t');
  assert.strictEqual(st.basin, 'atl');
  assert.strictEqual(st.cls, 'low');
  assert.strictEqual(st.low, TRACK);
});

console.log('dateline');

test('178E -> 178W interpolates the short way (4 degrees), not 356 backwards', function () {
  var l = low('d', 2001, [fix(2002010100, 45, 178), fix(2002010112, 45, -178)]);
  var s = PB.create([l]).season(2001);
  var mid = s.at(H(2002010106), 0).storms[0];
  var offDateline = Math.abs(Math.abs(mid.lon) - 180);
  assert.ok(offDateline < 1, 'midpoint lon ' + mid.lon + ' is not near the dateline');
  assert.ok(mid.lat >= 45, 'great circle bows poleward, never equatorward of the endpoints');
  // every sampled point is within the 4-degree gap (~315 km at 45N), never 178 degrees from an end
  for (var h = 0; h <= 12; h += 0.5) {
    var p = s.at(H(2002010100) + h, 0).storms[0];
    assert.ok(distKm(45, 178, p.lat, p.lon) < 400, 'strayed at +' + h + ' h: ' + p.lon);
  }
});

test('dateline tail points all stay on the short arc', function () {
  var l = low('d2', 2001, [fix(2002010100, 60, 179), fix(2002010106, 60, -179), fix(2002010112, 60, -177)]);
  var st = PB.create([l]).season(2001).at(H(2002010110), 12).storms[0];
  for (var i = 1; i < st.tail.length; i++) {
    assert.ok(distKm(st.tail[i - 1].lat, st.tail[i - 1].lon, st.tail[i].lat, st.tail[i].lon) < 500);
  }
});

console.log('tail');

var LONG = low('L', 2001, [
  fix(2002010100, 40, -50, 990), fix(2002010106, 42, -48, 980), fix(2002010112, 44, -46, 970),
  fix(2002010118, 46, -44, 960), fix(2002010200, 48, -42, 950)]);

test('tail leading end is exactly the head, mid-segment', function () {
  var st = PB.create([LONG]).season(2001).at(H(2002010109), 12).storms[0];
  var last = st.tail[st.tail.length - 1];
  assert.strictEqual(last.lat, st.lat);
  assert.strictEqual(last.lon, st.lon);
  assert.strictEqual(last.pres, st.pres);
  assert.strictEqual(last.age, 0);
  // head is 3 h into the 06->12 segment, so it must not have jumped to the 06Z fix
  assert.ok(st.lat > 42 && st.lat < 44);
});

test('tail covers exactly [t - tailHours, t]: both ends trimmed, fixes inside kept', function () {
  var s = PB.create([LONG]).season(2001);
  var st = s.at(H(2002010109), 6).storms[0];       // window 03Z .. 09Z
  assert.strictEqual(st.tail.length, 3);           // 03Z (interp), 06Z (fix), 09Z (head)
  assert.strictEqual(st.tail[0].age, 6);
  assert.strictEqual(st.tail[1].age, 3);
  assert.strictEqual(st.tail[1].lat, 42);          // the 06Z fix verbatim
  near(st.tail[0].lat, 41, 0.02);                  // 03Z is halfway 00Z -> 06Z
  near(st.tail[0].pres, 985, 1e-9);
  var ages = st.tail.map(function (p) { return p.age; });
  same(ages.slice().sort(function (a, b) { return b - a; }), ages);   // oldest first
});

test('tail window starting before the first fix is clipped to the first fix', function () {
  var st = PB.create([LONG]).season(2001).at(H(2002010109), 48).storms[0];
  assert.strictEqual(st.tail[0].lat, 40);          // the first fix itself, not extrapolated
  assert.strictEqual(st.tail[0].lon, -50);
  assert.strictEqual(st.tail[0].age, 9);           // 9 h of track exists, not 48
  assert.strictEqual(st.tail.length, 3);           // 00Z, 06Z, head
});

test('tail with a fix exactly at the window start or at t has no duplicate points', function () {
  var st = PB.create([LONG]).season(2001).at(H(2002010112), 6).storms[0];   // window 06Z..12Z, both on fixes
  assert.strictEqual(st.tail.length, 2);
  assert.strictEqual(st.tail[0].lat, 42);
  assert.strictEqual(st.tail[1].lat, 44);
});

test('tailHours 0 gives just the head; negative and NaN behave the same; Infinity gives the track so far', function () {
  var s = PB.create([LONG]).season(2001);
  assert.strictEqual(s.at(H(2002010109), 0).storms[0].tail.length, 1);
  assert.strictEqual(s.at(H(2002010109), -5).storms[0].tail.length, 1);
  assert.strictEqual(s.at(H(2002010109), NaN).storms[0].tail.length, 1);
  assert.strictEqual(s.at(H(2002010109)).storms[0].tail.length, 1);
  assert.strictEqual(s.at(H(2002010109), Infinity).storms[0].tail.length, 3);
});

test('at the very start of a storm the tail is just the head', function () {
  var st = PB.create([LONG]).season(2001).at(H(2002010100), 24).storms[0];
  assert.strictEqual(st.tail.length, 1);
});

console.log('domains, labels, stepping');

test('season clock: domain is first fix to last fix, label is a real date and hour', function () {
  var a = low('a', 2001, [fix(2001113006, 40, -50), fix(2001113012, 41, -49)]);
  var b = low('b', 2001, [fix(2002020418, 50, 170), fix(2002020506, 51, 171)]);
  var c = low('c', 2002, [fix(2002120100, 50, 170), fix(2002120106, 51, 171)]);
  var s = PB.create([a, b, c]).season(2001);
  assert.strictEqual(s.domain.start, H(2001113006));
  assert.strictEqual(s.domain.end, H(2002020506));
  assert.strictEqual(s.count, 2);
  assert.strictEqual(s.label(H(2002020418)), '4 Feb 2002 18Z');
  assert.strictEqual(s.label(H(2002010100)), '1 Jan 2002 00Z');
  assert.strictEqual(s.at(H(2002120103), 0).storms.length, 0);      // season 2002 is not in this clock
  var ticks = s.ticks();
  assert.ok(ticks.length >= 2 && ticks[0].label === 'Dec');
});

test('composite clock: domain is the fixed 366-day axis', function () {
  var c = PB.create([TRACK]).composite();
  same(c.domain, { start: 0, end: 8784 });
  assert.strictEqual(c.ticks().length, 12);
  assert.strictEqual(c.ticks()[0].label, 'Jul');
  assert.strictEqual(c.ticks()[11].label, 'Jun');
  assert.strictEqual(c.clamp(-5), 0);
  assert.strictEqual(c.clamp(99999), 8784);
});

test('stepping: complete tracks per season, no head, ascending order', function () {
  var a = low('a', 2001, [fix(2001113006, 40, -50, 990), fix(2001113012, 41, -49, 980), fix(2001113018, 42, -48, 970)]);
  var b = low('b', 2002, [fix(2002120100, 50, 170), fix(2002120106, 51, 171)], { minP: 955 });
  var pb = PB.create([b, a]);
  var fr = pb.step(2001);
  assert.strictEqual(fr.count, 1);
  assert.strictEqual(fr.storms[0].tail.length, 3);
  assert.strictEqual(fr.storms[0].tail[0].age, 12);
  assert.strictEqual(fr.storms[0].tail[2].age, 0);
  assert.strictEqual(fr.storms[0].lat, null);
  assert.strictEqual(fr.storms[0].key, 'atl:a');
  assert.strictEqual(pb.step(2002).storms[0].pres, 955);
  same(pb.seasons().map(function (s) { return s.season; }), [2001, 2002]);
});

test('stepping: a season emptied by the filters is still listed and steppable, reported empty', function () {
  var a = low('a', 2001, [fix(2001113006, 40, -50), fix(2001113012, 41, -49)]);
  var c = low('c', 2003, [fix(2003113006, 40, -50), fix(2003113012, 41, -49)]);
  // with the declared season list (what app.js has: DATA.seasons)
  var pb = PB.create([a, c], { seasons: [{ start: 2001 }, { start: 2002 }, { start: 2003 }, { start: 2004 }] });
  var list = pb.seasons();
  same(list.map(function (s) { return s.season; }), [2001, 2002, 2003, 2004]);
  same(list.map(function (s) { return s.empty; }), [false, true, false, true]);
  assert.strictEqual(list[1].label, '2002–03');
  var fr = pb.step(2002);
  assert.strictEqual(fr.empty, true);
  assert.strictEqual(fr.storms.length, 0);
  assert.strictEqual(fr.label, '2002–03');
  var sc = pb.season(2002);
  assert.strictEqual(sc.empty, true);
  assert.strictEqual(sc.at(sc.domain.start + 100, 12).storms.length, 0);
  assert.ok(sc.domain.end > sc.domain.start);
  // without a declared list, the gap between present seasons is still filled
  var pb2 = PB.create([a, c]);
  same(pb2.seasons().map(function (s) { return s.season; }), [2001, 2002, 2003]);
  assert.strictEqual(pb2.seasons()[1].empty, true);
});

console.log('empty / degenerate input');

test('empty input: no throw anywhere, empty flags set', function () {
  [PB.create([]), PB.create(), PB.create(null), PB.create([], { seasons: [] })].forEach(function (pb) {
    assert.strictEqual(pb.empty, true);
    assert.strictEqual(pb.count, 0);
    var c = pb.composite();
    assert.strictEqual(c.empty, true);
    assert.strictEqual(c.at(100, 48).storms.length, 0);
    assert.strictEqual(c.label(100), '5 Jul');
    same(c.domain, { start: 0, end: 8784 });
    var s = pb.season();
    assert.strictEqual(s.empty, true);
    assert.strictEqual(s.at(100, 48).storms.length, 0);
    assert.strictEqual(typeof s.label(100), 'string');
    same(pb.seasons(), []);
    assert.strictEqual(pb.step(2005).empty, true);
    assert.ok(Array.isArray(s.ticks()));
  });
});

test('lows without fixes are skipped (counted), bad t returns no storms', function () {
  var pb = PB.create([low('x', 2001, [fix(2002010100, 1, 1)], { fixes: [] }), TRACK]);
  assert.strictEqual(pb.skipped, 1);
  assert.strictEqual(pb.count, 1);
  var c = pb.composite();
  assert.strictEqual(c.at(NaN, 12).storms.length, 0);
  assert.strictEqual(c.at(undefined, 12).storms.length, 0);
});

test('out-of-order fixes are sorted rather than mis-bracketed', function () {
  var l = low('o', 2001, [fix(2002010106, 41, -49), fix(2002010100, 40, -50), fix(2002010112, 42, -48)]);
  var st = PB.create([l]).season(2001).at(H(2002010103), 0).storms[0];
  assert.ok(st.lat > 40 && st.lat < 41);
});

console.log('real archive (smoke)');

var realCache = null;
function realData() {
  if (!realCache) {
    var raw = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs', 'data', 'hf-lows.json'), 'utf8'));
    realCache = HF.decode(raw);
  }
  return realCache;
}

test('real archive: every low gets a finite head wherever it is active, in both clocks', function () {
  var D = realData();
  var pb = PB.create(D.lows, { seasons: D.seasons });
  assert.strictEqual(pb.count, D.lows.length);
  var c = pb.composite(), seen = 0;
  for (var t = 0; t <= 8784; t += 6) {
    c.at(t, 48).storms.forEach(function (st) {
      seen++;
      assert.ok(isFinite(st.lat) && isFinite(st.lon), st.key + ' non-finite at ' + t);
      assert.ok(st.lon >= -180 && st.lon <= 180);
      st.tail.forEach(function (p) { assert.ok(isFinite(p.lat) && isFinite(p.lon) && p.age >= 0); });
      var last = st.tail[st.tail.length - 1];
      assert.ok(last.lat === st.lat && last.lon === st.lon);
    });
  }
  assert.ok(seen > 5000);       // ~4.4 active storms per 6-hourly frame x 1,465 frames
  assert.strictEqual(pb.seasons().length, 25);
  var total = 0;
  pb.seasons().forEach(function (s) { total += pb.step(s.season).count; });
  assert.strictEqual(total, D.lows.length);
});

test('real archive: every low is visible at some composite frame (none hidden by the axis mapping)', function () {
  var D = realData(), c = PB.create(D.lows).composite(), shown = {};
  for (var t = 0; t <= 8784; t += 1) {
    c.at(t, 0).storms.forEach(function (st) { shown[st.key] = true; });
  }
  assert.strictEqual(Object.keys(shown).length, D.lows.length);
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
