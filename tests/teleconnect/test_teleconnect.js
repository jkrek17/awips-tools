#!/usr/bin/env node
/* Tests for docs/assets/js/teleconnect.js (teleconnection attribution and
   event subsets). Same convention as tests/playback/test_playback.js: only
   Node, no packages, no runner - node:assert and a tiny harness below.

     node tests/teleconnect/test_teleconnect.js

   teleconnect.js and util.js are plain browser scripts that attach to
   window.HF, so they are loaded into a vm context with a fake `window`.
   docs/data/teleconnections.js is loaded the same way (it assigns
   window.HF_TELECONNECTIONS) and is compared with the plain .json copy.

   Expected values are NEVER taken from the module's own calendar arithmetic.
   Where a test needs "the slot for 29 Feb 2004" it builds the day count with
   Date.UTC (independent code) and reads the raw array out of the .json
   file, so an off-by-one in the module cannot cancel against itself. The
   last block runs the real 1,932-event archive and prints coverage. */

var fs = require('fs');
var path = require('path');
var vm = require('vm');
var assert = require('assert');

var ROOT = path.join(__dirname, '..', '..');
var ctx = { window: {} };
vm.createContext(ctx);
function load(rel) {
  var file = path.join(ROOT, rel);
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: file });
}
load('docs/assets/js/util.js');
load('docs/assets/js/teleconnect.js');
load('docs/data/teleconnections.js');
var HF = ctx.window.HF;
var TC = HF.teleconnect;
var DATA = ctx.window.HF_TELECONNECTIONS;
var RAW = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs', 'data', 'teleconnections.json'), 'utf8'));
var RECORD_START = 2004;       // what HF.decode(...).recordStart carries for the real archive

var passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('  ok   ' + name); }
  catch (e) { failed++; console.log('  FAIL ' + name + '\n       ' + (e && e.message)); }
}
function near(a, b, tol, msg) {
  assert.ok(Math.abs(a - b) <= tol, (msg || 'values differ') + ': ' + a + ' vs ' + b + ' (tol ' + tol + ')');
}
// Objects built inside the vm have that context's Object.prototype, so
// deepStrictEqual (which compares prototypes) rejects them against literals
// made out here. Compare by value instead.
function same(a, b, msg) { assert.strictEqual(JSON.stringify(a), JSON.stringify(b), msg); }

// Independent calendar maths: whole UTC days since an ISO date, via Date.UTC.
function utcDays(y, m, d) { return Math.round(Date.UTC(y, m - 1, d) / 86400000); }
function slotOf(block, y, m, d) {
  var s = block.start.split('-').map(Number);
  return utcDays(y, m, d) - utcDays(s[0], s[1], s[2]);
}
function raw(name, y, m, d) {
  var i = slotOf(RAW[name], y, m, d);
  return i >= 0 && i < RAW[name].values.length ? RAW[name].values[i] : undefined;
}
function ymd(y, m, d) { return y * 10000 + m * 100 + d; }

function low(id, start, season, extra) {
  var l = { id: id, basin: 'atl', season: season, cls: 'low', start: start, minP: 970, fixes: [] };
  l.key = l.basin + ':' + l.id;
  for (var k in extra) l[k] = extra[k];
  return l;
}
function deepFreeze(o) {
  Object.freeze(o);
  Object.keys(o).forEach(function (k) { if (o[k] && typeof o[k] === 'object' && !Object.isFrozen(o[k])) deepFreeze(o[k]); });
  return o;
}

var tc = TC.create({ data: DATA, recordStart: RECORD_START });

console.log('payload');

test('the .js and .json payloads are the same data (so tests may read either)', function () {
  assert.strictEqual(JSON.stringify(DATA), JSON.stringify(RAW));
});

console.log('calendar arithmetic');

test('dayNumber agrees with Date.UTC on every day 1950-2120 (leap and century rules)', function () {
  for (var t = utcDays(1950, 1, 1); t <= utcDays(2120, 12, 31); t++) {
    var dt = new Date(t * 86400000);
    var y = dt.getUTCFullYear(), m = dt.getUTCMonth() + 1, d = dt.getUTCDate();
    if (TC.dayNumber(y, m, d) !== t) assert.fail('dayNumber(' + y + ',' + m + ',' + d + ') = ' + TC.dayNumber(y, m, d) + ', want ' + t);
    if (TC.daysToYmd(t) !== ymd(y, m, d)) assert.fail('daysToYmd(' + t + ') = ' + TC.daysToYmd(t) + ', want ' + ymd(y, m, d));
  }
});

test('toYmd: hour dropped, off-calendar dates refused, not rolled over', function () {
  assert.strictEqual(TC.toYmd(2004022918), 20040229);
  assert.strictEqual(TC.toYmd(20040229), 20040229);
  assert.strictEqual(TC.toYmd(20030229), null);      // 2003 is not a leap year
  assert.strictEqual(TC.toYmd(21000229), null);      // 2100 is not a leap year
  assert.strictEqual(TC.toYmd(20000229), 20000229);  // 2000 is
  assert.strictEqual(TC.toYmd(20010431), null);
  assert.strictEqual(TC.toYmd(20011301), null);
  assert.strictEqual(TC.toYmd(null), null);
  assert.strictEqual(TC.toYmd(NaN), null);
  assert.strictEqual(TC.toYmd('20040229'), null);
  assert.strictEqual(TC.toYmd(low('x', 2004022918, 2003)), 20040229);
});

test('daily slot: dates either side of the 2004 and 2008 leap days map to the raw CPC value for that date', function () {
  [[2004, 2, 28], [2004, 2, 29], [2004, 3, 1], [2008, 2, 28], [2008, 2, 29], [2008, 3, 1],
   [2003, 2, 28], [2003, 3, 1], [2012, 12, 31], [2013, 1, 1]].forEach(function (d) {
    ['nao', 'pna', 'ao'].forEach(function (n) {
      var want = raw(n, d[0], d[1], d[2]);
      assert.notStrictEqual(want, undefined, 'test date outside the record');
      assert.strictEqual(tc.dailyValue(n, ymd(d[0], d[1], d[2])), want, n + ' ' + d.join('-'));
    });
  });
  // The three days are distinct values, so a one-day shift cannot pass:
  var a = raw('nao', 2004, 2, 28), b = raw('nao', 2004, 2, 29), c = raw('nao', 2004, 3, 1);
  assert.ok(a !== b && b !== c);
  assert.strictEqual(raw('nao', 2004, 2, 29), 0.049);   // literal from the CPC file, as baked
  assert.strictEqual(tc.dailyValue('nao', 20040229), 0.049);
  assert.strictEqual(tc.dailyValue('nao', 2004022923), 0.049);   // 23Z is still the 29th
});

test('slot arithmetic holds for every day of the record (module vs raw array, one-to-one)', function () {
  var n = RAW.nao.values.length, s = RAW.nao.start.split('-').map(Number);
  for (var i = 0; i < n; i += 1) {
    var dt = new Date((utcDays(s[0], s[1], s[2]) + i) * 86400000);
    var want = RAW.nao.values[i];
    var got = tc.dailyValue('nao', ymd(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate()));
    if (got !== want) assert.fail('slot ' + i + ' ' + dt.toISOString() + ': ' + got + ' vs ' + want);
  }
});

test('edges of the daily record: first and last day answer, the days outside are null', function () {
  assert.strictEqual(tc.dailyValue('nao', 20010501), RAW.nao.values[0]);
  assert.strictEqual(tc.dailyValue('nao', 20010430), null);
  assert.strictEqual(tc.dailyValue('nao', 20260930), RAW.nao.values[RAW.nao.values.length - 1]);
  assert.notStrictEqual(RAW.nao.values[RAW.nao.values.length - 1], null);
  assert.strictEqual(tc.dailyValue('nao', 20261001), null);
  assert.strictEqual(RAW.nao.end, '2026-09-30');
  assert.strictEqual(slotOf(RAW.nao, 2026, 9, 30), RAW.nao.n - 1);   // the declared end is the last slot
});

console.log('5-day antecedent mean');

test('mean5 equals the hand-computed mean of days d-4..d (NAO 2004-03-01, across the leap day)', function () {
  var days = [[2, 26], [2, 27], [2, 28], [2, 29], [3, 1]];
  var sum = 0;
  days.forEach(function (md) { sum += raw('nao', 2004, md[0], md[1]); });
  near(tc.mean5('nao', 20040301), sum / 5, 1e-12);
  // and spelled out, so the expectation is visible in the test:
  var vals = days.map(function (md) { return raw('nao', 2004, md[0], md[1]); });
  assert.strictEqual(vals.length, 5);
  near(tc.mean5('nao', 20040301), (vals[0] + vals[1] + vals[2] + vals[3] + vals[4]) / 5, 1e-12);
  // the window must contain 29 Feb: a calendar that skipped it would have 5 days ending 4 days earlier
  assert.notStrictEqual(tc.mean5('nao', 20040301), tc.mean5('nao', 20040229));
});

test('mean5 is null whenever the window holds a missing day (NAO sentinel 2006-10-26, d..d+4), and resumes after', function () {
  assert.strictEqual(raw('nao', 2006, 10, 26), null);
  assert.strictEqual(tc.dailyValue('nao', 20061026), null);
  [26, 27, 28, 29, 30].forEach(function (d) {
    assert.strictEqual(tc.mean5('nao', ymd(2006, 10, d)), null, 'window of 10-' + d + ' contains 10-26');
  });
  assert.notStrictEqual(tc.mean5('nao', 20061025), null);          // window 21..25
  var s = 0; [27, 28, 29, 30, 31].forEach(function (d) { s += raw('nao', 2006, 10, d); });
  near(tc.mean5('nao', 20061031), s / 5, 1e-12);                   // first clean window after it
});

test('mean5 is null across the AO-only sentinel 2003-04-30, while NAO and PNA (which have it) still answer', function () {
  assert.strictEqual(raw('ao', 2003, 4, 30), null);
  assert.notStrictEqual(raw('nao', 2003, 4, 30), null);
  assert.strictEqual(tc.mean5('ao', 20030430), null);
  assert.strictEqual(tc.mean5('ao', 20030504), null);
  assert.notStrictEqual(tc.mean5('ao', 20030505), null);
  assert.notStrictEqual(tc.mean5('nao', 20030504), null);
  assert.notStrictEqual(tc.mean5('pna', 20030504), null);
});

test('mean5 is null when the window runs off the front of the record (2001-05-01..04), exact from 2001-05-05', function () {
  [1, 2, 3, 4].forEach(function (d) { assert.strictEqual(tc.mean5('nao', ymd(2001, 5, d)), null, '05-0' + d); });
  var s = 0; for (var d = 1; d <= 5; d++) s += RAW.nao.values[d - 1];
  near(tc.mean5('nao', 20010505), s / 5, 1e-12);
  assert.strictEqual(tc.mean5('nao', 20010430), null);
  assert.strictEqual(tc.mean5('nao', 20261001), null);
});

console.log('ENSO');

function oniRaw(y, m) {      // ONI slot keyed by centre month, built independently
  var s = RAW.oni.start.split('-').map(Number);
  var i = (y - s[0]) * 12 + (m - s[1]);
  return { i: i, v: RAW.oni.values[i], ph: RAW.oni.phases[i], seas: RAW.oni.seas[i] };
}

test('strong El Nino: January 2016 genesis -> DJF 2016, +2.5, El Nino; DJF of its season (2015-16) the same', function () {
  var a = tc.attribute(low('a', 2016011500, 2015));
  assert.strictEqual(a.enso.genesis.season, 'DJF');
  assert.strictEqual(a.enso.genesis.value, oniRaw(2016, 1).v);
  assert.strictEqual(a.enso.genesis.value, 2.5);
  assert.strictEqual(a.enso.genesis.phase, 'E');
  assert.strictEqual(a.enso.genesis.phaseName, 'El Nino');
  assert.strictEqual(a.enso.djf.value, 2.5);
  assert.strictEqual(a.enso.djf.phase, 'E');
  assert.strictEqual(a.enso.djf.centre, '2016-01');
});

test('strong La Nina: 2010-11 DJF is -1.29 La Nina; 2020-21 is La Nina', function () {
  var a = tc.attribute(low('a', 2011010100, 2010));
  assert.strictEqual(a.enso.djf.value, -1.29);
  assert.strictEqual(a.enso.djf.phase, 'L');
  assert.strictEqual(a.enso.djf.phaseName, 'La Nina');
  assert.strictEqual(tc.attribute(low('b', 2021011500, 2020)).enso.djf.phase, 'L');
});

test('genesis season follows seasonMapping (centred on the genesis month); DJF is the season-level descriptor and can differ', function () {
  // An October 2015 genesis: ONI season centred on Oct is SON; the season's DJF is the following Jan.
  var a = tc.attribute(low('a', 2015101200, 2015));
  assert.strictEqual(a.enso.genesis.season, 'SON');
  assert.strictEqual(a.enso.genesis.value, oniRaw(2015, 10).v);
  assert.strictEqual(a.enso.genesis.centre, '2015-10');
  assert.strictEqual(a.enso.djf.value, oniRaw(2016, 1).v);
  // June 2009 genesis in season 2009: genesis is MJJ ~neutral-warming, DJF 2009-10 is El Nino. Different on purpose.
  var b = tc.attribute(low('b', 2009061000, 2009));
  assert.strictEqual(b.enso.genesis.season, 'MJJ');
  assert.strictEqual(b.enso.djf.phase, 'E');
  assert.strictEqual(b.enso.genesis.value, oniRaw(2009, 6).v);
  assert.notStrictEqual(b.enso.genesis.phase + b.enso.genesis.value, b.enso.djf.phase + b.enso.djf.value);
  // season label agrees with the calendar month for every month of a year
  var names = ['DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ', 'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ'];
  for (var m = 1; m <= 12; m++) {
    assert.strictEqual(tc.oniAt(ymd(2012, m, 15)).season, names[m - 1], 'month ' + m);
  }
});

test('ONI ends 2026-08: an August 2026 genesis has a season, September 2026 has none (null), and neither is dropped', function () {
  assert.strictEqual(RAW.oni.end, '2026-08');
  assert.notStrictEqual(tc.attribute(low('a', 2026081500, 2026)).enso.genesis, null);
  var s = tc.attribute(low('b', 2026091500, 2026));
  assert.strictEqual(s.enso.genesis, null);
  assert.strictEqual(s.enso.djf, null);                    // DJF 2026-27 does not exist yet
  assert.strictEqual(tc.attribute(low('c', 2026012000, 2025)).enso.djf.centre, '2026-01');
  assert.strictEqual(tc.attribute(low('d', 2001042000, 2000)).enso.genesis, null);   // before ONI start 2001-05
  assert.strictEqual(tc.attribute(low('e', 2001050500, 2001)).enso.genesis.season, 'AMJ');
  assert.strictEqual(tc.attribute(low('f', 2001050500, 2000)).enso.djf, null);        // DJF 2000-01 precedes the record
});

console.log('MJO pentads');

function pentadContaining(y, m, d) {
  // Independent expectation: nearest pentad centre within the calendar pentad, using the
  // rule written out by day arithmetic from Date.UTC and the raw dates array.
  var t = utcDays(y, m, d), best = null;
  RAW.mjo.dates.forEach(function (c) {
    var cy = Math.floor(c / 10000), cm = Math.floor(c / 100) % 100, cd = c % 100;
    var diff = t - utcDays(cy, cm, cd);
    if (diff >= -2 && diff <= 2) best = c;        // window centre-2 .. centre+2
  });
  return best;
}

test('pentad containing a date, either side of the leap step (27 Feb -> 4 Mar, 6 days)', function () {
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040224)), 20040222);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040225)), 20040227);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040227)), 20040227);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040228)), 20040227);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040229)), 20040227);   // the leap day sits in the 27 Feb pentad
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040301)), 20040227);   // ... and so does 1 Mar (6-day pentad)
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040302)), 20040304);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20040304)), 20040304);
  // a common year gives the same cut: 1 Mar is the last day of the 27 Feb pentad
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20030301)), 20030227);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(20030302)), 20030304);
  assert.strictEqual(tc.mjoPentad(tc.mjoRow(2004030118)), 20040227);  // hours ignored
});

test('every day 2001-05-03..2026-09-25 lands in a pentad whose centre is within +-2 days (3 only on a leap 1 Mar), and rows never go backwards', function () {
  var prev = -1, n = 0;
  for (var t = utcDays(2001, 5, 3); t <= utcDays(2026, 9, 25); t++) {
    var dt = new Date(t * 86400000);
    var y = dt.getUTCFullYear(), m = dt.getUTCMonth() + 1, d = dt.getUTCDate();
    var row = tc.mjoRow(ymd(y, m, d));
    assert.ok(row != null, 'no row for ' + dt.toISOString());
    assert.ok(row >= prev && row - prev <= 1, 'row jumped at ' + dt.toISOString());
    prev = row;
    var c = RAW.mjo.dates[row];
    var off = t - utcDays(Math.floor(c / 10000), Math.floor(c / 100) % 100, c % 100);
    var leapMar1 = m === 3 && d === 1 && (y % 4 === 0);
    assert.ok((off >= -2 && off <= 2) || (off === 3 && leapMar1), dt.toISOString() + ' off=' + off + ' centre ' + c);
    if (!leapMar1) assert.strictEqual(c, pentadContaining(y, m, d), dt.toISOString());
    n++;
  }
  assert.ok(n > 9000);
  assert.strictEqual(prev, RAW.mjo.dates.length - 1);       // reached the last row
});

test('record edges: first pentad reaches back 2 days; nothing after the last pentad\'s reach (not the last row forever)', function () {
  assert.strictEqual(RAW.mjo.dates[0], 20010503);
  assert.strictEqual(tc.mjoRow(20010430), null);
  assert.strictEqual(tc.mjoRow(20010501), 0);
  assert.strictEqual(RAW.mjo.end, '2026-09-25');
  var last = RAW.mjo.dates.length - 1;
  assert.strictEqual(tc.mjoRow(20260927), last);     // centre + 2
  assert.strictEqual(tc.mjoRow(20260928), null);     // past it
  assert.strictEqual(tc.mjoRow(20260930), null);
  assert.strictEqual(tc.mjoRow(20261201), null);
});

test('lag k returns the row k back (5, 10, 15 days; 6 across a leap day), verified against the raw series', function () {
  var m = tc.mjoAt(low('a', 2004030400, 2003), 0);              // 4 Mar 2004 -> pentad 20040304
  assert.strictEqual(m.genesisPentad, 20040304);
  assert.strictEqual(m.pentad, 20040304);
  var row = RAW.mjo.dates.indexOf(20040304);
  [0, 1, 2, 3].forEach(function (k) {
    var r = tc.mjoAt(low('a', 2004030400, 2003), k);
    assert.strictEqual(r.row, row - k);
    assert.strictEqual(r.pentad, RAW.mjo.dates[row - k]);
    RAW.mjo.longitudes.forEach(function (lon) {
      assert.strictEqual(r.values[lon], RAW.mjo.series[lon][row - k], 'lag ' + k + ' ' + lon);
    });
  });
  assert.strictEqual(tc.mjoAt(low('a', 2004030400, 2003), 1).pentad, 20040227);   // 6 days back across the leap day
  assert.strictEqual(tc.mjoAt(low('a', 2004030400, 2003), 2).pentad, 20040222);
  assert.strictEqual(tc.mjoAt(low('a', 2004030400, 2003), 2).values['120W'], 2.01);  // literal from the file
  // attribute() carries the same numbers
  var a = tc.attribute(low('a', 2004030400, 2003), { lag: 2 });
  assert.strictEqual(a.mjo.lag, 2);
  assert.strictEqual(a.mjo.lagPentad, 20040222);
  assert.strictEqual(a.mjo.genesisPentad, 20040304);
  assert.strictEqual(a.mjo.genesisValues['120W'], RAW.mjo.series['120W'][row]);
  assert.strictEqual(a.mjo.lagValues['120W'], 2.01);
});

test('lag is a parameter, not baked: different lags give different pentads; default is 2; bad lags throw', function () {
  var l = low('a', 2010011500, 2009);
  var p1 = tc.attribute(l, { lag: 1 }).mjo.lagPentad;
  var p3 = tc.attribute(l, { lag: 3 }).mjo.lagPentad;
  assert.notStrictEqual(p1, p3);
  assert.strictEqual(tc.attribute(l).mjo.lag, 2);
  assert.strictEqual(tc.defaultLag, 2);
  assert.strictEqual(TC.create({ data: DATA, recordStart: RECORD_START, lag: 3 }).attribute(l).mjo.lag, 3);
  assert.strictEqual(tc.attribute(l, { lag: 0 }).mjo.lagPentad, tc.attribute(l).mjo.genesisPentad);
  [-1, 1.5, 'a', NaN, true].forEach(function (bad) {
    assert.throws(function () { tc.attribute(l, { lag: bad }); }, /lag/);
  });
});

test('lag past the front of the record keeps the genesis pentad and nulls the lagged values; a missing pentad is null, not a quiet MJO', function () {
  var a = tc.attribute(low('a', 20010510, 2001), { lag: 3 });     // row 1; 3 back is before row 0
  assert.notStrictEqual(a.mjo, null);
  assert.strictEqual(a.mjo.lagValues, null);
  assert.strictEqual(a.mjo.lagPentad, null);
  assert.notStrictEqual(a.mjo.genesisValues, null);
  // interior all-missing pentads 2021-12-29 and 2022-12-29
  var k = RAW.mjo.dates.indexOf(20211229);
  RAW.mjo.longitudes.forEach(function (lon) { assert.strictEqual(RAW.mjo.series[lon][k], null); });
  var g = tc.attribute(low('b', 20211229, 2021));
  assert.strictEqual(g.mjo.genesisValues, null);
  assert.strictEqual(g.mjo.genesisPentad, 20211229);
  assert.notStrictEqual(g.mjo.lagValues, null);                    // 2 pentads earlier has data
  var l = tc.attribute(low('c', 20220108, 2021), { lag: 2 });      // lag 2 from the pentad after next lands on the missing one
  assert.strictEqual(RAW.mjo.dates[RAW.mjo.dates.indexOf(20220108)], 20220108);
  assert.strictEqual(l.mjo.lagPentad, 20211229);
  assert.strictEqual(l.mjo.lagValues, null);
});

console.log('honest gaps');

test('events outside every record get null attribution, are not dropped, and are counted', function () {
  var before = low('before', 2001042000, 2000), after = low('after', 2026100500, 2026), ok = low('ok', 2010011500, 2009);
  var a = tc.attribute(before), b = tc.attribute(after);
  [a, b].forEach(function (x) {
    assert.strictEqual(x.enso.genesis, null);
    assert.strictEqual(x.mjo, null);
    ['nao', 'pna', 'ao'].forEach(function (n) { assert.strictEqual(x[n].daily, null); assert.strictEqual(x[n].mean5, null); });
  });
  var lows = [before, ok, after];
  var c = tc.coverage(lows, { completeOnly: false });
  assert.strictEqual(c.total, 3);
  assert.strictEqual(c.nao.daily.ok, 1);   assert.strictEqual(c.nao.daily.missing, 2);
  assert.strictEqual(c.nao.mean5.ok, 1);   assert.strictEqual(c.nao.mean5.missing, 2);
  assert.strictEqual(c.pna.daily.missing, 2);
  assert.strictEqual(c.ao.daily.missing, 2);
  assert.strictEqual(c.mjo.genesis.ok, 1); assert.strictEqual(c.mjo.genesis.missing, 2);
  assert.strictEqual(c.mjo.lag.ok, 1);     assert.strictEqual(c.mjo.lag.missing, 2);
  assert.strictEqual(c.enso.genesis.ok, 1); assert.strictEqual(c.enso.genesis.missing, 2);
  // ok + missing always adds up to total
  ['genesis', 'djf'].forEach(function (k) { assert.strictEqual(c.enso[k].ok + c.enso[k].missing, c.total); });
  // the same events come back from unattributed(), never from select()
  var spec = { type: 'tercile', index: 'nao', group: 'upper', completeOnly: false };
  same(tc.unattributed(lows, spec).map(function (l) { return l.key; }), ['atl:before', 'atl:after']);
  assert.ok(tc.select(lows, spec).indexOf(before) < 0 && tc.select(lows, spec).indexOf(after) < 0);
});

test('daily indices end 2026-09-30 but MJO ends 2026-09-25: 28 Sep 2026 has NAO and no MJO', function () {
  var l = low('a', 20260928, 2026);
  var a = tc.attribute(l);
  assert.notStrictEqual(a.nao.daily, null);
  assert.strictEqual(a.mjo, null);
});

test('the sentinel day gives null daily (never 0): NAO 2006-10-26 and 2007-01-26, AO 2003-04-30', function () {
  assert.strictEqual(tc.attribute(low('a', 2006102612, 2006)).nao.daily, null);
  assert.strictEqual(tc.attribute(low('b', 2007012600, 2006)).pna.daily, null);
  assert.strictEqual(tc.attribute(low('c', 2003043006, 2002)).ao.daily, null);
  assert.strictEqual(tc.attribute(low('c', 2003043006, 2002)).nao.daily, raw('nao', 2003, 4, 30));
});

console.log('terciles');

function rawMean5Sample(name, from, to) {      // independent, from the raw array
  var out = [];
  for (var t = utcDays(from[0], from[1], from[2]); t <= utcDays(to[0], to[1], to[2]); t++) {
    var i = t - utcDays(2001, 5, 1), s = 0, ok = i >= 4;
    for (var k = i - 4; ok && k <= i; k++) { if (RAW[name].values[k] == null) ok = false; else s += RAW[name].values[k]; }
    if (ok) out.push(s / 5);
  }
  return out;
}

test('tercile period is the complete seasons only: 1 Jun 2004 .. 31 May 2026, not the 1950+ record or all 25 seasons', function () {
  same(tc.period, { from: 20040601, to: 20260531 });
  var c = tc.terciles('nao');
  assert.strictEqual(c.from, 20040601);
  assert.strictEqual(c.to, 20260531);
  assert.strictEqual(c.basis, 'mean5');
  // recordStart from the decoded archive object, last season from its season list
  var viaArchive = TC.create({ data: DATA, archive: { recordStart: 2004, seasons: [{ start: 2001 }, { start: 2002 }, { start: 2024 }] } });
  same(viaArchive.period, { from: 20040601, to: 20250531 });
  // no recordStart => no honest period => refuse, do not fall back to everything
  assert.throws(function () { TC.create({ data: DATA }).terciles('nao'); }, /recordStart|period/);
});

test('terciles partition the archive-period days roughly in thirds (independent count over the raw array)', function () {
  ['nao', 'pna', 'ao'].forEach(function (name) {
    var cut = tc.terciles(name, 'mean5');
    var sample = rawMean5Sample(name, [2004, 6, 1], [2026, 5, 31]);
    assert.strictEqual(cut.n, sample.length);
    var lo = 0, mid = 0, hi = 0;
    sample.forEach(function (v) { if (v <= cut.lower) lo++; else if (v >= cut.upper) hi++; else mid++; });
    [lo, mid, hi].forEach(function (c) { near(c / sample.length, 1 / 3, 0.004, name + ' third'); });
    assert.ok(cut.lower < cut.upper);
    assert.strictEqual(lo + mid + hi, sample.length);
  });
  var d = tc.terciles('nao', 'daily');
  assert.ok(d.n > tc.terciles('nao', 'mean5').n - 1);       // daily sample is at least as large
  assert.ok(d.lower < 0 && d.upper > 0);                    // a standardized index straddles zero
});

test('terciles are stable: the same on repeat, in a fresh engine, and after subsets of any size are selected', function () {
  var a = tc.terciles('pna', 'mean5');
  var b = TC.create({ data: DATA, recordStart: RECORD_START }).terciles('pna', 'mean5');
  same(a, b);
  tc.select([low('x', 20100115, 2009)], { type: 'tercile', index: 'pna', group: 'upper' });
  same(tc.terciles('pna', 'mean5'), a);
  // and are NOT a function of which events are asked about: tercileOf uses the fixed cuts
  assert.strictEqual(tc.tercileOf('pna', 'mean5', a.lower), 'lower');
  assert.strictEqual(tc.tercileOf('pna', 'mean5', a.upper), 'upper');
  assert.strictEqual(tc.tercileOf('pna', 'mean5', (a.lower + a.upper) / 2), 'middle');
  assert.strictEqual(tc.tercileOf('pna', 'mean5', null), null);
});

console.log('subsets');

function synth() {
  // a spread of synthetic events across complete seasons, with a couple of hostile ones
  var out = [], id = 0;
  for (var y = 2004; y <= 2025; y++) {
    [[12, 5], [1, 20], [2, 11], [3, 25]].forEach(function (md) {
      var yr = md[0] >= 6 ? y : y + 1;
      out.push(low('s' + (id++), ymd(yr, md[0], md[1]) * 100 + 6, y));
    });
  }
  out.push(low('gap1', 2006102618, 2006));                    // NAO sentinel day
  out.push(low('part1', 2002020418, 2001));                   // partial season
  out.push(low('part2', 2003011500, 2002));
  return out;
}

test('subsets are plain arrays of the same objects (identity), in input order, new arrays, inputs unmutated', function () {
  var lows = synth();
  deepFreeze(lows);                                            // 'use strict' module would throw on any write
  var snap = JSON.stringify(lows);
  var results = [
    tc.byEnso(lows, 'E'), tc.byEnso(lows, 'N', { basis: 'genesis' }), tc.byEnso(lows, 'La Nina'),
    tc.byTercile(lows, 'nao', 'upper'), tc.byTercile(lows, 'ao', 'lower', { basis: 'daily' }),
    tc.byMjo(lows, '120W', 'enhanced', { lag: 2, threshold: 0.5 }),
    tc.select(lows, { type: 'mjo', lon: '140E', state: 'suppressed', lag: 1, threshold: 0.3 })
  ];
  results.forEach(function (r) {
    assert.ok(Array.isArray(r));
    assert.notStrictEqual(r, lows);
    assert.ok(r.length > 0 && r.length < lows.length);
    var last = -1;
    r.forEach(function (l) {
      var i = lows.indexOf(l);
      assert.ok(i >= 0, 'not one of the input objects');
      assert.ok(i > last, 'input order lost');
      last = i;
    });
    // plain: only indices, no decoration on the array
    assert.strictEqual(Object.keys(r).join(), r.map(function (_, i) { return String(i); }).join());
  });
  tc.attribute(lows[0]); tc.coverage(lows); tc.unattributed(lows, { type: 'enso', phase: 'E' });
  assert.strictEqual(JSON.stringify(lows), snap);
  lows.forEach(function (l) { assert.strictEqual(Object.keys(l).indexOf('enso'), -1); });
});

test('ENSO subsets partition the in-scope events with the unattributed ones (E + N + L + none = scope), on either basis', function () {
  var lows = synth();
  ['djf', 'genesis'].forEach(function (basis) {
    var scope = tc.completeOnly(lows);
    var e = tc.byEnso(lows, 'E', { basis: basis }), n = tc.byEnso(lows, 'N', { basis: basis }), l = tc.byEnso(lows, 'L', { basis: basis });
    var none = tc.unattributed(lows, { type: 'enso', phase: 'E', basis: basis });
    assert.strictEqual(e.length + n.length + l.length + none.length, scope.length);
    // no event in two groups
    var seen = {};
    e.concat(n, l, none).forEach(function (x) { assert.ok(!seen[x.key], 'in two groups'); seen[x.key] = 1; });
  });
  // every El Nino-djf event really sits in an E season in the raw ONI
  tc.byEnso(lows, 'E').forEach(function (x) { assert.strictEqual(oniRaw(x.season + 1, 1).ph, 'E'); });
  tc.byEnso(lows, 'L').forEach(function (x) { assert.strictEqual(oniRaw(x.season + 1, 1).ph, 'L'); });
  // phase spellings
  same(tc.byEnso(lows, 'E').map(function (x) { return x.key; }), tc.byEnso(lows, 'El Nino').map(function (x) { return x.key; }));
  same(tc.byEnso(lows, 'N').map(function (x) { return x.key; }), tc.byEnso(lows, 'neutral').map(function (x) { return x.key; }));
});

test('tercile subsets: upper + middle + lower + none = scope; members are on the right side of the cut points (checked on raw mean5)', function () {
  var lows = synth(), scope = tc.completeOnly(lows);
  ['nao', 'pna', 'ao'].forEach(function (name) {
    var cut = tc.terciles(name, 'mean5');
    var u = tc.byTercile(lows, name, 'upper'), m = tc.byTercile(lows, name, 'middle'), lo = tc.byTercile(lows, name, 'lower');
    var none = tc.unattributed(lows, { type: 'tercile', index: name, group: 'upper' });
    assert.strictEqual(u.length + m.length + lo.length + none.length, scope.length, name);
    u.forEach(function (x) { assert.ok(tc.mean5(name, x) >= cut.upper); });
    lo.forEach(function (x) { assert.ok(tc.mean5(name, x) <= cut.lower); });
    m.forEach(function (x) { var v = tc.mean5(name, x); assert.ok(v > cut.lower && v < cut.upper); });
  });
  var nao = tc.unattributed(lows, { type: 'tercile', index: 'nao', group: 'upper' });
  assert.ok(nao.some(function (x) { return x.key === 'atl:gap1'; }), 'the sentinel-day event is unattributed, not placed');
});

test('MJO subsets: enhanced is <= -threshold, suppressed >= +threshold, neutral in between; threshold and lag are honoured', function () {
  var lows = synth();
  var lon = '120W', lag = 2, thr = 0.7;
  var en = tc.byMjo(lows, lon, 'enhanced', { lag: lag, threshold: thr });
  var su = tc.byMjo(lows, lon, 'suppressed', { lag: lag, threshold: thr });
  var ne = tc.byMjo(lows, lon, 'neutral', { lag: lag, threshold: thr });
  var none = tc.unattributed(lows, { type: 'mjo', lon: lon, state: 'enhanced', lag: lag });
  assert.strictEqual(en.length + su.length + ne.length + none.length, tc.completeOnly(lows).length);
  function rawAt(x) {                       // raw series value `lag` pentads before the genesis pentad
    var row = tc.mjoRow(x) - lag;
    return RAW.mjo.series[lon][row];
  }
  en.forEach(function (x) { assert.ok(rawAt(x) <= -thr, 'enhanced ' + rawAt(x)); });
  su.forEach(function (x) { assert.ok(rawAt(x) >= thr, 'suppressed ' + rawAt(x)); });
  ne.forEach(function (x) { assert.ok(Math.abs(rawAt(x)) < thr, 'neutral ' + rawAt(x)); });
  assert.ok(en.length > 0 && su.length > 0 && ne.length > 0);
  // a bigger threshold can only shrink the enhanced set
  var strict = tc.byMjo(lows, lon, 'enhanced', { lag: lag, threshold: 1.2 });
  strict.forEach(function (x) { assert.ok(en.indexOf(x) >= 0); });
  assert.ok(strict.length < en.length);
  // a different lag changes membership
  var other = tc.byMjo(lows, lon, 'enhanced', { lag: 0, threshold: thr });
  assert.notStrictEqual(other.map(function (x) { return x.key; }).join(), en.map(function (x) { return x.key; }).join());
  // default lag/threshold are the documented ones
  same(tc.byMjo(lows, lon, 'enhanced').map(function (x) { return x.key; }),
       tc.byMjo(lows, lon, 'enhanced', { lag: 2, threshold: 0.5 }).map(function (x) { return x.key; }));
  // convention: the data say negative = enhanced; the module must follow it, not invert it
  assert.ok(/negative = enhanced/.test(DATA.mjo.convention));
});

test('bad selection arguments throw instead of returning a convincing empty set', function () {
  var lows = synth();
  assert.throws(function () { tc.byEnso(lows, 'Elnino2'); }, /phase/);
  assert.strictEqual(tc.byEnso(lows, 'El Ni\u00f1o').length, tc.byEnso(lows, 'E').length);
  assert.throws(function () { tc.byEnso(lows, ''); }, /phase/);
  assert.throws(function () { tc.byEnso(lows, null); }, /phase/);
  assert.throws(function () { tc.byTercile(lows, 'amo', 'upper'); }, /index/);
  assert.throws(function () { tc.byTercile(lows, 'nao', 'top'); }, /group/);
  assert.throws(function () { tc.byTercile(lows, 'nao', 'upper', { basis: 'weekly' }); }, /basis/);
  assert.throws(function () { tc.byMjo(lows, '121W', 'enhanced'); }, /longitude/);
  assert.throws(function () { tc.byMjo(lows, '120W', 'wet'); }, /state/);
  assert.throws(function () { tc.byMjo(lows, '120W', 'enhanced', { threshold: -1 }); }, /threshold/);
  assert.throws(function () { tc.byMjo(lows, '120W', 'enhanced', { lag: -2 }); }, /lag/);
  assert.throws(function () { tc.select(lows, { type: 'rmm' }); }, /type/);
  assert.throws(function () { TC.create({ data: {} }); }, /index data missing/);
});

console.log('partial seasons');

test('attribute() tags EVERY event, partial seasons included, and says whether the season is complete', function () {
  var p = tc.attribute(low('p', 2002020418, 2001));
  assert.strictEqual(p.complete, false);
  assert.notStrictEqual(p.enso.djf, null);
  assert.notStrictEqual(p.nao.daily, null);
  assert.notStrictEqual(p.mjo, null);
  assert.strictEqual(tc.attribute(low('c', 2004060100, 2004)).complete, true);
  assert.strictEqual(tc.attribute(low('c', 2004053118, 2003)).complete, false);
  assert.strictEqual(tc.isComplete(low('c', 2004060100, 2004)), true);
});

test('selection defaults to complete seasons only; completeOnly:false keeps every attributable event; excluded() reports the difference', function () {
  var lows = synth();
  var parts = lows.filter(function (l) { return l.season < RECORD_START; });
  assert.strictEqual(parts.length, 2);
  var all = ['E', 'N', 'L'].reduce(function (acc, p) { return acc.concat(tc.byEnso(lows, p)); }, []);
  parts.forEach(function (p) { assert.ok(all.indexOf(p) < 0, 'partial-season event leaked into the default subset'); });
  var allOpen = ['E', 'N', 'L'].reduce(function (acc, p) { return acc.concat(tc.byEnso(lows, p, { completeOnly: false })); }, []);
  parts.forEach(function (p) { assert.ok(allOpen.indexOf(p) >= 0, 'partial event dropped despite completeOnly:false'); });
  assert.strictEqual(allOpen.length - all.length, 2);
  same(tc.excluded(lows).map(function (l) { return l.key; }), ['atl:part1', 'atl:part2']);
  same(tc.completeOnly(lows).length, lows.length - 2);
  var c = tc.coverage(lows), c2 = tc.coverage(lows, { completeOnly: false });
  assert.strictEqual(c.total, lows.length - 2);
  assert.strictEqual(c.excludedPartial, 2);
  assert.strictEqual(c2.total, lows.length);
  assert.strictEqual(c2.excludedPartial, 0);
});

test('without recordStart the safe default cannot be honoured, so it refuses; the explicit opt-out still works', function () {
  var blind = TC.create({ data: DATA });
  var lows = synth();
  assert.throws(function () { blind.byEnso(lows, 'E'); }, /recordStart/);
  assert.throws(function () { blind.coverage(lows); }, /recordStart/);
  assert.ok(blind.byEnso(lows, 'E', { completeOnly: false }).length > 0);
  assert.strictEqual(blind.attribute(lows[0]).complete, null);
});

console.log('real archive');

var realCache = null;
function realData() {
  if (!realCache) {
    var j = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs', 'data', 'hf-lows.json'), 'utf8'));
    realCache = HF.decode(j);
  }
  return realCache;
}

test('real archive: every one of the events gets an attribution record; counts per attribution, all events and complete seasons', function () {
  var D = realData();
  assert.strictEqual(D.recordStart, RECORD_START);
  var engine = TC.create({ archive: D });
  var lows = D.lows;
  assert.strictEqual(lows.length, 1932);
  lows.forEach(function (l) { assert.notStrictEqual(engine.attribute(l).date, null, l.key); });   // none dropped

  var all = engine.coverage(lows, { completeOnly: false });
  var cmp = engine.coverage(lows);
  assert.strictEqual(all.total, 1932);
  assert.strictEqual(cmp.total + cmp.excludedPartial, 1932);
  function line(label, c) {
    var parts = ['enso.genesis', 'enso.djf', 'nao.daily', 'nao.mean5', 'pna.daily', 'pna.mean5', 'ao.daily', 'ao.mean5', 'mjo.genesis', 'mjo.lag']
      .map(function (k) { var p = k.split('.'); var leaf = c[p[0]][p[1]]; return k + ' ' + leaf.ok + '/' + c.total + ' (missing ' + leaf.missing + ')'; });
    console.log('       ' + label + ' (n=' + c.total + ', MJO lag ' + c.mjoLag + '):\n         ' + parts.join('\n         '));
  }
  line('all events', all);
  line('complete seasons', cmp);
  console.log('       partial-season events excluded by default: ' + cmp.excludedPartial);

  // Everything is attributable except events that fall on a missing day or pentad.
  // 1,932 events with 5 missing source days and 2 missing pentads: a handful at most.
  ['nao', 'pna', 'ao'].forEach(function (n) {
    assert.ok(all[n].daily.missing <= 3, n + ' daily missing ' + all[n].daily.missing);
    assert.ok(all[n].mean5.missing <= 25, n + ' mean5 missing ' + all[n].mean5.missing);
  });
  assert.strictEqual(all.enso.genesis.missing, 0);
  assert.strictEqual(all.enso.djf.missing, 0);
  assert.ok(all.mjo.genesis.missing <= 5, 'mjo genesis missing ' + all.mjo.genesis.missing);
  assert.ok(all.mjo.lag.missing <= 10, 'mjo lag missing ' + all.mjo.lag.missing);
});

test('real archive: every null is explained by the raw data (a sentinel/missing day in the window, or a missing pentad) - nothing is lost silently', function () {
  var D = realData(), engine = TC.create({ archive: D });
  D.lows.forEach(function (l) {
    var a = engine.attribute(l);
    var s = String(l.start), y = +s.slice(0, 4), m = +s.slice(4, 6), d = +s.slice(6, 8);
    ['nao', 'pna', 'ao'].forEach(function (n) {
      var i = slotOf(RAW[n], y, m, d), v = RAW[n].values;
      assert.strictEqual(a[n].daily === null, v[i] == null, l.key + ' ' + n + ' daily');
      var windowBad = false;
      for (var k = i - 4; k <= i; k++) if (k < 0 || v[k] == null) windowBad = true;
      assert.strictEqual(a[n].mean5 === null, windowBad, l.key + ' ' + n + ' mean5');
    });
    var oi = oniRaw(y, m);
    assert.strictEqual(a.enso.genesis.value, oi.v, l.key);
    assert.strictEqual(a.enso.genesis.season, oi.seas, l.key);
    var dj = oniRaw(l.season + 1, 1);
    assert.strictEqual(a.enso.djf.season, 'DJF');
    assert.strictEqual(a.enso.djf.value, dj.v, l.key);
    // MJO: the pentad is within the window, values equal the raw row
    var t = utcDays(y, m, d), c = a.mjo.genesisPentad;
    var off = t - utcDays(Math.floor(c / 10000), Math.floor(c / 100) % 100, c % 100);
    assert.ok(off >= -2 && off <= 3, l.key + ' pentad offset ' + off);
    var row = RAW.mjo.dates.indexOf(c);
    var anyData = RAW.mjo.longitudes.some(function (lon) { return RAW.mjo.series[lon][row] != null; });
    assert.strictEqual(a.mjo.genesisValues !== null, anyData, l.key + ' mjo genesis');
  });
});

test('real archive: each ENSO/tercile subset is a plain subset of the archive; counts reported', function () {
  var D = realData(), engine = TC.create({ archive: D });
  var scope = engine.completeOnly(D.lows);
  var lines = [];
  ['E', 'N', 'L'].forEach(function (p) {
    var r = engine.byEnso(D.lows, p);
    r.forEach(function (x) { assert.ok(D.lows.indexOf(x) >= 0); });
    lines.push('ENSO ' + p + ' (DJF): ' + r.length);
  });
  var sum = 0; ['E', 'N', 'L'].forEach(function (p) { sum += engine.byEnso(D.lows, p).length; });
  assert.strictEqual(sum, scope.length);        // every ONI season is present for the whole archive
  ['nao', 'pna', 'ao'].forEach(function (n) {
    var u = engine.byTercile(D.lows, n, 'upper').length, m = engine.byTercile(D.lows, n, 'middle').length, l = engine.byTercile(D.lows, n, 'lower').length;
    var none = engine.unattributed(D.lows, { type: 'tercile', index: n, group: 'upper' }).length;
    assert.strictEqual(u + m + l + none, scope.length);
    lines.push(n.toUpperCase() + ' mean5 terciles upper/middle/lower: ' + u + '/' + m + '/' + l + ' (unattributed ' + none + ')');
  });
  var en = engine.byMjo(D.lows, '120W', 'enhanced').length;
  lines.push('MJO 120W enhanced (lag 2, |v|>=0.5): ' + en);
  lines.forEach(function (s) { console.log('       ' + s); });
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
