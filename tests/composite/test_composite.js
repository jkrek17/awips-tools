#!/usr/bin/env node
/* Tests for docs/assets/js/composite.js (gridded density, season-level
   bootstrap, FDR). Same shape as tests/playback/test_playback.js: Node only,
   no packages, the module loaded into a vm with a fake `window`.

     node tests/composite/test_composite.js

   Most of the weight is on the statistics, because a significance test that
   never fires and one that always fires look identical until you try both:

     - the grid is proved equal-area against a uniform-on-sphere sample, with
       a naive lat/lon grid beside it to show the test can fail;
     - the bootstrap is run on pure noise (false-positive rate) AND on an
       injected shift (power), over many synthetic archives, and its
       false-positive rate is set beside that of a naive event-level test to
       show why the unit of resampling is the season;
     - FDR is shown to cut the number of flagged cells on noise, with counts.

   Numbers the module's doc comments quote come from the "REPORT" lines below.
   The last block runs the real archive (docs/data/hf-lows.json). */

var fs = require('fs');
var path = require('path');
var vm = require('vm');
var assert = require('assert');

var ROOT = path.join(__dirname, '..', '..');
var ctx = { window: {} };
vm.createContext(ctx);
['util.js', 'composite.js'].forEach(function (f) {
  var file = path.join(ROOT, 'docs', 'assets', 'js', f);
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: file });
});
var HF = ctx.window.HF;
var CP = HF.composite;

var passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('  ok   ' + name); }
  catch (e) { failed++; console.log('  FAIL ' + name + '\n       ' + (e && e.message)); }
}
function report(s) { console.log('       REPORT ' + s); }
function near(a, b, tol, msg) {
  assert.ok(Math.abs(a - b) <= tol, (msg || 'values differ') + ': ' + a + ' vs ' + b + ' (tol ' + tol + ')');
}
function pct(x) { return (100 * x).toFixed(2) + '%'; }
// Objects built inside the vm carry the vm's prototypes; compare by value.
function same(a, b, msg) { assert.strictEqual(JSON.stringify(a), JSON.stringify(b), msg); }

/* ------------------------------------------------ test-local random numbers
   Independent of the module's PRNG on purpose: if the module's generator were
   subtly broken, data generated from the same one would hide it. */
function rngOf(seed) {
  var a = seed >>> 0;
  return function () {
    a = (a + 0x9E3779B9) >>> 0;
    var t = a ^ (a >>> 16);
    t = Math.imul(t, 0x85EBCA6B); t ^= t >>> 13;
    t = Math.imul(t, 0xC2B2AE35); t ^= t >>> 16;
    return (t >>> 0) / 4294967296;
  };
}
function gauss(r) {
  var u = 1 - r(), v = r();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/* ---------------------------------------------------- synthetic archive
   Built to be hard on a naive test, not easy:
     - four storm tracks (one straddling the dateline, one Atlantic, one Gulf
       of Alaska, one near Cape Farewell with pressure-less tip-jet events);
     - every season has its OWN background state shared by all its events: a
       latitude and longitude shift of the whole belt, a busy/quiet factor,
       and its own mix of the tracks. That shared state is the whole reason
       events are not independent, so it has to be strong enough to matter.
   opts.shiftSouth: degrees to move track 0 southward, for events whose
   `shifted` predicate is true (default: none). */
var TRACKS = [
  { name: 'dateline',  lat: 48, lon: 180,  slat: 4, slon: 12, w: 0.34 },
  { name: 'atlantic',  lat: 52, lon: -40,  slat: 4, slon: 12, w: 0.34 },
  { name: 'alaska',    lat: 56, lon: -145, slat: 3, slon: 8,  w: 0.22 },
  { name: 'farewell',  lat: 60, lon: -43,  slat: 2, slon: 5,  w: 0.10 }
];
function wrapLon(x) { x = ((x + 180) % 360 + 360) % 360 - 180; return x === -180 ? 180 : x; }

function makeArchive(seed, o) {
  o = o || {};
  var r = rngOf(seed), seasons = [], lows = [];
  var nSeasons = o.nSeasons || 25;
  for (var s = 0; s < nSeasons; s++) {
    var season = 2001 + s;
    seasons.push(season);
    var state = {
      dlat: 2.5 * gauss(r), dlon: 5 * gauss(r),
      busy: Math.exp(0.3 * gauss(r)),
      mix: TRACKS.map(function (t) { return t.w * Math.exp(0.5 * gauss(r)); })
    };
    var mixSum = state.mix.reduce(function (a, b) { return a + b; }, 0);
    var nEv = Math.round(78 * state.busy);
    for (var e = 0; e < nEv; e++) {
      var u = r() * mixSum, ti = 0;
      while (ti < TRACKS.length - 1 && u > state.mix[ti]) { u -= state.mix[ti]; ti++; }
      var T = TRACKS[ti];
      var lat = T.lat + state.dlat + T.slat * gauss(r);
      var lon = T.lon + state.dlon + T.slon * gauss(r);
      var low = { id: season + '-' + e, basin: ti === 1 || ti === 3 ? 'atl' : 'pac', season: season,
                  cls: ti === 3 && r() < 0.3 ? 'tipjet' : 'low', track: ti, flag: r() < 0.5, fixes: [] };
      low.key = low.basin + ':' + low.id;
      var nFix = 1 + Math.floor(r() * 6);
      for (var f = 0; f < nFix; f++) {
        lat += 0.8 * gauss(r); lon += 3 + gauss(r);
        low.fixes.push({ date: 2001010100, lat: Math.max(25, Math.min(75, lat)), lon: wrapLon(lon), cat: 'HF',
                         pres: low.cls === 'tipjet' ? null : 975 });
      }
      if (o.shiftSouth && ti === 0 && o.shifted && o.shifted(low)) {
        low.fixes.forEach(function (fx) { fx.lat -= o.shiftSouth; });
      }
      lows.push(low);
    }
  }
  return { seasons: seasons, lows: lows };
}
function pickSeasons(lows, list) {
  var m = {}; list.forEach(function (s) { m[s] = true; });
  return lows.filter(function (l) { return m[l.season]; });
}
// Random k of the archive's seasons, drawn WITHOUT replacement.
function randomSeasons(seasons, k, r) {
  var a = seasons.slice(), out = [];
  for (var i = 0; i < k; i++) {
    var j = i + Math.floor(r() * (a.length - i));
    var t = a[i]; a[i] = a[j]; a[j] = t; out.push(a[i]);
  }
  return out.sort(function (x, y) { return x - y; });
}

/* ================================================================== grid */

console.log('equal-area grid');

// A naive regular lat/lon grid, written independently here as the control.
function naiveIndex(lat, lon, dlat, dlon) {
  return Math.floor((lat + 90) / dlat) * Math.round(360 / dlon) + Math.floor((lon + 180) / dlon);
}

// 2,000,000 points uniform ON THE SPHERE: lon uniform, sin(lat) uniform.
// (Uniform in lat itself is the classic mistake - it piles points at the
// poles - so the generator is the thing under suspicion too; the mean of
// sin(lat) and the total area are checked before it is trusted.)
var SPHERE = (function () {
  var r = rngOf(12345), n = 2000000, lat = new Float64Array(n), lon = new Float64Array(n);
  for (var i = 0; i < n; i++) {
    lat[i] = Math.asin(2 * r() - 1) * 180 / Math.PI;
    lon[i] = r() * 360 - 180;
  }
  return { n: n, lat: lat, lon: lon };
})();

var G = CP.grid(4, 20);
var sphereCounts = (function () {
  var c = new Float64Array(G.nCells), nv = new Float64Array(45 * 90);
  for (var i = 0; i < SPHERE.n; i++) {
    c[G.cellIndex(SPHERE.lat[i], SPHERE.lon[i])]++;
    nv[naiveIndex(SPHERE.lat[i], SPHERE.lon[i], 4, 4)]++;
  }
  return { equal: c, naive: nv };
})();

test('the test sphere is itself uniform (guards the generator)', function () {
  var s = 0;
  for (var i = 0; i < SPHERE.n; i++) s += Math.sin(SPHERE.lat[i] * Math.PI / 180);
  near(s / SPHERE.n, 0, 0.002, 'mean sin(lat)');
});

test('cell areas sum to the sphere and are nearly equal where the archive lives', function () {
  var total = 0, minA = Infinity, maxA = -Infinity, belt = [];
  for (var id = 0; id < G.nCells; id++) {
    var c = G.cellInfo(id);
    total += c.areaKm2;
    if (c.lat0 >= 24 && c.lat1 <= 68) belt.push(c.areaKm2);
  }
  near(total / (4 * Math.PI * 6371.0088 * 6371.0088), 1, 1e-12, 'total area');
  belt.forEach(function (a) { minA = Math.min(minA, a); maxA = Math.max(maxA, a); });
  report('cell area, 24-68N: ' + minA.toFixed(0) + ' - ' + maxA.toFixed(0) + ' km^2 (spread ' +
         pct(maxA / minA - 1) + '), ' + G.nCells + ' cells globally');
  assert.ok(maxA / minA < 1.02, 'belt areas differ by more than 2%');
});

test('uniform-on-sphere points give a FLAT count per cell on the equal-area grid', function () {
  // Poisson test: for flat density, counts_i ~ Poisson(mu * area_i), so the
  // dispersion index sum((c-e)^2/e)/df is ~1 with sd sqrt(2/df) ~ 0.028.
  var totalArea = 0, id, ex, chi = 0, df = G.nCells - 1;
  for (id = 0; id < G.nCells; id++) totalArea += G.cellInfo(id).areaKm2;
  for (id = 0; id < G.nCells; id++) {
    ex = SPHERE.n * G.cellInfo(id).areaKm2 / totalArea;
    chi += Math.pow(sphereCounts.equal[id] - ex, 2) / ex;
  }
  var disp = chi / df;
  report('equal-area grid, uniform sphere: dispersion index ' + disp.toFixed(3) + ' (1.0 = pure Poisson, flat)');
  near(disp, 1, 0.1, 'dispersion index');
  // And the thing a forecaster would see: mean count per cell by latitude band.
  var lo = Infinity, hi = -Infinity;
  G.bands.forEach(function (b, bi) {
    if (b.lat0 < 24 || b.lat1 > 68) return;
    var s = 0;
    for (var j = 0; j < b.n; j++) s += sphereCounts.equal[b.offset + j];
    var mean = s / b.n; lo = Math.min(lo, mean); hi = Math.max(hi, mean);
  });
  report('mean count/cell across the 24-68N bands: ' + lo.toFixed(0) + ' - ' + hi.toFixed(0) +
         ' (spread ' + pct(hi / lo - 1) + ')');
  assert.ok(hi / lo < 1.04, 'band means differ by more than 4%');
});

test('the SAME points on a naive lat/lon grid are NOT flat (the control that makes the test mean something)', function () {
  var nv = sphereCounts.naive, mu = SPHERE.n / nv.length, chi = 0, i;
  for (i = 0; i < nv.length; i++) {
    // expectation for a naive cell is proportional to ITS area, cos(lat) here
    // - but a map that plots count per cell has no such correction.
    chi += Math.pow(nv[i] - mu, 2) / mu;
  }
  var disp = chi / (nv.length - 1);
  function bandMean(lat0) {
    var b = Math.floor((lat0 + 90) / 4), s = 0;
    for (var j = 0; j < 90; j++) s += nv[b * 90 + j];
    return s / 90;
  }
  var ratio = bandMean(64) / bandMean(28);
  report('naive 4x4 deg grid, uniform sphere: dispersion index ' + disp.toFixed(1) +
         '; count/cell at 64N is ' + ratio.toFixed(2) + 'x that at 28N (true density is identical; cos ratio ' +
         (Math.cos(66 * Math.PI / 180) / Math.cos(30 * Math.PI / 180)).toFixed(2) + ')');
  assert.ok(disp > 10, 'naive grid unexpectedly flat');
  assert.ok(ratio < 0.6, 'naive grid does not under-represent high latitudes');
  // Equal-area at the same two latitudes:
  function eqMean(lat0) {
    var b = G.bands[Math.floor((lat0 + 90) / G.latStep)], s = 0;
    for (var j = 0; j < b.n; j++) s += sphereCounts.equal[b.offset + j];
    return s / b.n;
  }
  near(eqMean(64) / eqMean(28), 1, 0.03, 'equal-area 64N vs 28N');
});

console.log('\nbinning, dateline and bookkeeping');

test('dateline: +-180 are one meridian, and cells straddling the seam are single cells', function () {
  assert.strictEqual(G.cellIndex(50, 180), G.cellIndex(50, -180));
  assert.strictEqual(G.cellIndex(50, 540), G.cellIndex(50, 180));
  assert.strictEqual(G.cellIndex(50, -540), G.cellIndex(50, 180));
  var straddlers = 0, b, j;
  for (var bi = 0; bi < G.bands.length; bi++) {
    b = G.bands[bi];
    // find the cell containing 180 and take points a hair either side of it
    var mid = (b.lat0 + b.lat1) / 2, c = G.cellIndex(mid, 180), info = G.cellInfo(c);
    var eps = 1e-6, w = G.cellIndex(mid, 180 - eps), e = G.cellIndex(mid, -180 + eps);
    if (info.crossesDateline) {
      straddlers++;
      assert.strictEqual(w, e, 'band ' + bi + ': a cell crossing 180 was split');
      assert.strictEqual(w, c);
      assert.ok(info.lon0 + info.dlon > 180, 'east edge should be reported unwrapped past 180');
    } else {
      assert.ok(w === c || e === c);              // 180 is an edge: neighbours, each point in one cell
      assert.ok(w !== e || b.n === 1);
    }
  }
  report(straddlers + ' of ' + G.bands.length + ' bands have a cell that spans the dateline; none split');
  assert.ok(straddlers > 10, 'expected many straddling bands (the test would otherwise prove little)');
});

test('every fix lands in exactly one cell: counts are conserved, nothing double-counted', function () {
  var r = rngOf(7), lows = [{ season: 2001, id: 'x', fixes: [] }], n = 5000, i, total = 0;
  for (i = 0; i < n; i++) {
    // dense around the seam, plus exact +-180 and out-of-range longitudes
    var lon = i % 5 === 0 ? (i % 2 ? 180 : -180) : i % 7 === 0 ? 180 + 360 * (r() < 0.5 ? 1 : -1) + (r() - 0.5) :
              179 + 2 * r() > 180 ? 179 + 2 * r() - 360 : 179 + 2 * r();
    lows[0].fixes.push({ lat: 40 + 30 * r(), lon: lon, cat: 'HF', pres: null });
  }
  var d = CP.density(lows, { seasons: [2001] });
  d.cells.forEach(function (c) { total += c.count; });
  assert.strictEqual(total, n);
  assert.strictEqual(d.total, n);
  assert.strictEqual(d.droppedFixes, 0);
});

test('fixes straddling the dateline pool into neighbouring/same cells, not a basin-wide split', function () {
  // 12 fixes at 179.5E and 12 at 179.5W, same latitude: 1 degree apart across
  // the seam, so within one cell wherever a cell spans 180 and in two ADJACENT
  // cells otherwise - never one at each end of the map.
  var fixes = [], i;
  for (i = 0; i < 12; i++) { fixes.push({ lat: 50.2, lon: 179.5, cat: 'HF', pres: null }); fixes.push({ lat: 50.2, lon: -179.5, cat: 'HF', pres: null }); }
  var d = CP.density([{ season: 2001, fixes: fixes }], { seasons: [2001] });
  assert.ok(d.cells.length <= 2);
  assert.strictEqual(d.total, 24);
  if (d.cells.length === 2) {
    var a = d.cells[0], b = d.cells[1];
    near(Math.abs(a.id - b.id), 1, 0, 'adjacent in index');
  }
});

test('no analyzed pressure (tip-jet, pres null) is counted in density like any other event', function () {
  var tj = { season: 2001, cls: 'tipjet', fixes: [{ lat: 60, lon: -43, cat: 'HF', pres: null }, { lat: 60.5, lon: -44, cat: 'HF', pres: null }] };
  var lo = { season: 2001, cls: 'low', fixes: [{ lat: 60, lon: -43, cat: 'HF', pres: 970 }] };
  var d = CP.density([tj, lo], { seasons: [2001] });
  assert.strictEqual(d.nEvents, 2);
  assert.strictEqual(d.total, 3);
  var withPres = CP.density([lo], { seasons: [2001] });
  assert.strictEqual(withPres.total, 1);
});

test('unit "events" counts an event once per cell however many fixes it leaves there', function () {
  var ev = { season: 2001, fixes: [1, 2, 3, 4].map(function () { return { lat: 50, lon: -40, cat: 'HF', pres: 980 }; }) };
  assert.strictEqual(CP.density([ev], { seasons: [2001], unit: 'fixes' }).total, 4);
  assert.strictEqual(CP.density([ev], { seasons: [2001], unit: 'events' }).total, 1);
});

test('unusable coordinates are dropped and reported, not binned', function () {
  var ev = { season: 2001, fixes: [{ lat: NaN, lon: 10 }, { lat: 50, lon: null }, { lat: 95, lon: 10 }, { lat: 50, lon: 10, cat: 'HF' }] };
  var d = CP.density([ev], { seasons: [2001] });
  assert.strictEqual(d.total, 1);
  assert.strictEqual(d.droppedFixes, 3);
});

test('density: rate is per SEASON, and duplicating every season leaves it unchanged', function () {
  var A = makeArchive(11), sub = pickSeasons(A.lows, A.seasons.slice(0, 8));
  var base = CP.density(sub, { seasons: A.seasons.slice(0, 8) });
  var dup = sub.concat(sub.map(function (l) {
    var c = {}; for (var k in l) c[k] = l[k];
    c.season = l.season + 1000; return c;
  }));
  var seasons16 = A.seasons.slice(0, 8).concat(A.seasons.slice(0, 8).map(function (s) { return s + 1000; }));
  var twice = CP.density(dup, { seasons: seasons16 });
  assert.strictEqual(twice.nSeasons, 16);
  assert.strictEqual(twice.cells.length, base.cells.length);
  base.cells.forEach(function (c, i) {
    var t = twice.cells[i];
    assert.strictEqual(t.id, c.id);
    assert.strictEqual(t.count, 2 * c.count);                    // raw counts DO double...
    near(t.rate, c.rate, 1e-12, 'rate of cell ' + c.id);          // ...rates do not
    near(t.perMkm2, c.perMkm2, 1e-9);
  });
});

test('compare: duplicating every season (subset AND full set) leaves rate, all and diff unchanged', function () {
  var A = makeArchive(21), subS = A.seasons.slice(3, 11);
  var sub = pickSeasons(A.lows, subS);
  function dupOf(lows) { return lows.map(function (l) { var c = {}; for (var k in l) c[k] = l[k]; c.season = l.season + 1000; return c; }); }
  var r1 = CP.compare(A.lows, sub, { seasons: A.seasons, subsetSeasons: subS, iterations: 200 });
  var r2 = CP.compare(A.lows.concat(dupOf(A.lows)), sub.concat(dupOf(sub)), {
    seasons: A.seasons.concat(A.seasons.map(function (s) { return s + 1000; })),
    subsetSeasons: subS.concat(subS.map(function (s) { return s + 1000; })), iterations: 200 });
  assert.strictEqual(r1.status, 'ok'); assert.strictEqual(r2.status, 'ok');
  assert.strictEqual(r1.cells.length, r2.cells.length);
  r1.cells.forEach(function (c, i) {
    var d = r2.cells[i];
    near(d.rate.subset, c.rate.subset, 1e-12); near(d.rate.all, c.rate.all, 1e-12); near(d.rate.diff, c.rate.diff, 1e-12);
    near(d.shape.diff, c.shape.diff, 1e-12);
    assert.strictEqual(d.nSubset, 2 * c.nSubset);
  });
  assert.strictEqual(r2.n.events, 2 * r1.n.events);
  assert.strictEqual(r2.n.seasons, 2 * r1.n.seasons);
});

test('a defining season with no events still counts in the per-season denominator', function () {
  var A = makeArchive(31), subS = A.seasons.slice(0, 8);
  var hollow = A.lows.filter(function (l) { return l.season !== subS[0]; });       // season 0 has NO events anywhere
  var sub = pickSeasons(hollow, subS);
  var withSeason = CP.compare(hollow, sub, { seasons: A.seasons, subsetSeasons: subS, iterations: 100 });
  var without = CP.compare(hollow, sub, { seasons: A.seasons, iterations: 100 });             // subset seasons inferred: 7
  assert.strictEqual(withSeason.n.seasons, 8);
  assert.strictEqual(without.n.seasons, 7);
  var c = withSeason.cells[0], d = without.cells.filter(function (x) { return x.id === c.id; })[0];
  near(c.rate.subset * 8, d.rate.subset * 7, 1e-9, 'same counts, different exposure');
});

/* ================================================================== FDR */

console.log('\nBenjamini-Hochberg');

test('BH: textbook case (hand-worked)', function () {
  var p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205];
  var f = CP.fdr(p, 0.05);
  same(f.reject, [true, true, false, false, false, false, false, false]);
  near(f.q[0], 0.008, 1e-12); near(f.q[1], 0.032, 1e-12);
  near(f.q[2], 0.0672, 1e-12); near(f.q[4], 0.0672, 1e-12);
  near(f.q[5], 0.08, 1e-12); near(f.q[7], 0.205, 1e-12);
  assert.strictEqual(f.m, 8); assert.strictEqual(f.nReject, 2);
});

test('BH is step-up: a p-value that misses its own line is flagged if a larger rank clears its line', function () {
  var f = CP.fdr([0.001, 0.03, 0.035, 0.9], 0.05);   // lines: .0125 .025 .0375 .05; p2 misses, p3 passes
  same(f.reject, [true, true, true, false]);
  assert.strictEqual(f.nReject, 3);
});

test('BH: q <= alphaFDR exactly for the flagged cells; unordered input; NaN cells skipped and excluded from m', function () {
  var r = rngOf(3), p = [], i;
  for (i = 0; i < 200; i++) p.push(i % 10 === 0 ? NaN : (i < 40 ? r() * 0.002 : r()));
  var f = CP.fdr(p, 0.1);
  assert.strictEqual(f.m, 180);
  for (i = 0; i < p.length; i++) {
    if (isNaN(p[i])) { assert.ok(isNaN(f.q[i])); assert.strictEqual(f.reject[i], false); }
    else assert.strictEqual(f.reject[i], f.q[i] <= 0.1 + 1e-12, 'cell ' + i);
  }
});

test('BH: null input gives no flags', function () {
  var f = CP.fdr([], 0.1);
  assert.strictEqual(f.nReject, 0); assert.strictEqual(f.m, 0);
});

/* ============================================================== bootstrap */

console.log('\nbootstrap on synthetic archives');

var FP_RUNS = 60, FP_ITERS = 1500;

// The shared null battery: a FRESH archive each run, then a random 8 of its
// 25 seasons as the "subset". The subset is drawn from the same distribution
// as the whole by construction, so every significant cell is a false positive.
var NOISE = (function () {
  var rows = [], t0 = Date.now();
  for (var run = 0; run < FP_RUNS; run++) {
    var A = makeArchive(1000 + run), r = rngOf(5000 + run);
    var subS = randomSeasons(A.seasons, 8, r), sub = pickSeasons(A.lows, subS);
    var res = CP.compare(A.lows, sub, { seasons: A.seasons, subsetSeasons: subS, iterations: FP_ITERS, seed: 1 + run });
    rows.push({ A: A, subS: subS, sub: sub, res: res, naive: naiveEventTest(A, sub, subS, 300 + run) });
  }
  return { rows: rows, secs: (Date.now() - t0) / 1000 };
})();

/* The error the module exists to avoid, written out: treat every EVENT as an
   independent draw. Null = random event sets of the same size from the pool
   (events shuffled across seasons), scored with the same cell definition and
   the same BH step. This is the obvious thing to write and it is wrong. */
function naiveEventTest(A, sub, subS, seed) {
  var grid = CP.grid(4, 20), r = rngOf(seed), N = A.seasons.length, k = subS.length;
  function cellsOf(l) { var o = {}; l.fixes.forEach(function (f) { var c = grid.cellIndex(f.lat, f.lon); o[c] = (o[c] || 0) + 1; }); return o; }
  var all = A.lows.map(cellsOf), T = {}, S = {}, i, c;
  all.forEach(function (o) { for (c in o) T[c] = (T[c] || 0) + o[c]; });
  var inSub = {}; sub.forEach(function (l) { inSub[l.key] = true; });
  A.lows.forEach(function (l, idx) { if (inSub[l.key]) for (c in all[idx]) S[c] = (S[c] || 0) + all[idx][c]; });
  var cells = Object.keys(T).filter(function (c2) { return T[c2] >= 10; });
  var obs = {}, ex = {};
  cells.forEach(function (c2) { obs[c2] = Math.abs((S[c2] || 0) / k - T[c2] / N); ex[c2] = 0; });
  var B = 1000, n = sub.length, idx = all.map(function (_, j) { return j; });
  for (var b = 0; b < B; b++) {
    var Sb = {};
    for (i = 0; i < n; i++) {
      var j = i + Math.floor(r() * (idx.length - i)), t = idx[i]; idx[i] = idx[j]; idx[j] = t;
      for (c in all[idx[i]]) Sb[c] = (Sb[c] || 0) + all[idx[i]][c];
    }
    cells.forEach(function (c2) { if (Math.abs((Sb[c2] || 0) / k - T[c2] / N) >= obs[c2] - 1e-9) ex[c2]++; });
  }
  var p = cells.map(function (c2) { return (1 + ex[c2]) / (B + 1); });
  var f = CP.fdr(p, 0.1);
  return { m: cells.length, sigCell: p.filter(function (x) { return x <= 0.05; }).length, sigFDR: f.nReject };
}

test('season-level bootstrap: a subset drawn from the same distribution lights up almost nothing (' + FP_RUNS + ' archives)', function () {
  var cellSig = 0, cellFDR = 0, tested = 0, runsAny = 0, nCellsPerRun = [];
  NOISE.rows.forEach(function (row) {
    assert.strictEqual(row.res.status, 'ok');
    cellSig += row.res.summary.rate.nSigCell; cellFDR += row.res.summary.rate.nSigFDR;
    tested += row.res.summary.rate.nTested;
    if (row.res.summary.rate.nSigFDR > 0) runsAny++;
    nCellsPerRun.push(row.res.summary.rate.nTested);
  });
  var fpCell = cellSig / tested, fpFDR = cellFDR / tested, anyRate = runsAny / FP_RUNS;
  report(FP_RUNS + ' runs x ' + FP_ITERS + ' draws (' + NOISE.secs.toFixed(0) + ' s), ~' +
         Math.round(tested / FP_RUNS) + ' tested cells per run, rate field');
  report('per-cell p<0.05: ' + pct(fpCell) + ' of cells flagged  (' + (cellSig / FP_RUNS).toFixed(1) + ' cells per map)');
  report('FDR (alphaFDR 0.10): ' + pct(fpFDR) + ' of cells flagged (' + (cellFDR / FP_RUNS).toFixed(2) +
         ' cells per map); ' + runsAny + ' of ' + FP_RUNS + ' maps had any flagged cell (' + pct(anyRate) + ')');
  // The per-cell test must be roughly calibrated (not dead, not wild): 5%
  // nominal, a little under because the null is built over-dispersed on
  // purpose-free grounds (discrete counts, ties counted as exceedances).
  assert.ok(fpCell > 0.015 && fpCell < 0.08, 'per-cell false positive rate off: ' + pct(fpCell));
  // FDR on a complete null controls P(any flagged cell) at alphaFDR = 10%.
  assert.ok(fpFDR < 0.005, 'FDR flagged too many cells on noise: ' + pct(fpFDR));
  assert.ok(anyRate <= 0.15, 'FDR flagged something in too many noise maps: ' + pct(anyRate));
});

test('shape field is just as quiet on noise', function () {
  var cellSig = 0, cellFDR = 0, tested = 0, runsAny = 0;
  NOISE.rows.forEach(function (row) {
    cellSig += row.res.summary.shape.nSigCell; cellFDR += row.res.summary.shape.nSigFDR;
    tested += row.res.summary.shape.nTested; if (row.res.summary.shape.nSigFDR > 0) runsAny++;
  });
  report('shape field: per-cell ' + pct(cellSig / tested) + ', FDR ' + pct(cellFDR / tested) +
         ', maps with any FDR cell ' + runsAny + '/' + FP_RUNS);
  assert.ok(cellSig / tested < 0.08); assert.ok(cellFDR / tested < 0.005); assert.ok(runsAny / FP_RUNS <= 0.15);
});

test('FDR reduces the flagged-cell count on pure noise, with numbers', function () {
  var perCell = 0, fdrN = 0, expected = 0;
  NOISE.rows.forEach(function (row) {
    perCell += row.res.summary.rate.nSigCell; fdrN += row.res.summary.rate.nSigFDR;
    expected += row.res.summary.rate.expectedByChance;
  });
  report('over ' + FP_RUNS + ' noise maps: per-cell flags ' + perCell + ' (chance alone predicts ~' + expected.toFixed(0) +
         '), FDR flags ' + fdrN);
  assert.ok(perCell > 10 * Math.max(fdrN, 1), 'FDR did not cut the noise stipples by an order of magnitude');
  assert.ok(fdrN < perCell / 10);
});

test('why the season is the unit of resampling: a naive EVENT-level test on the SAME noise is badly over-confident', function () {
  var cellSig = 0, cellFDR = 0, tested = 0, runsAny = 0, soundAny = 0, soundCell = 0, soundTested = 0;
  NOISE.rows.forEach(function (row) {
    cellSig += row.naive.sigCell; cellFDR += row.naive.sigFDR; tested += row.naive.m;
    if (row.naive.sigFDR > 0) runsAny++;
    if (row.res.summary.rate.nSigFDR > 0) soundAny++;
    soundCell += row.res.summary.rate.nSigCell; soundTested += row.res.summary.rate.nTested;
  });
  report('naive event-level: per-cell ' + pct(cellSig / tested) + ' flagged, FDR flags ' + (cellFDR / FP_RUNS).toFixed(1) +
         ' cells per map, ' + runsAny + '/' + FP_RUNS + ' noise maps have a "significant" cell');
  report('season-level on the same maps: per-cell ' + pct(soundCell / soundTested) +
         ', maps with any FDR cell ' + soundAny + '/' + FP_RUNS);
  // The claim this test exists to support is "the season is the right unit of
  // resampling", i.e. the naive event-level null is measurably over-confident
  // on the SAME noise. Both assertions below compare it against the season
  // design rather than against an absolute bar: how often either fires at all
  // depends on the archive's noise level and the cell count, which are
  // properties of the fixture, not of the question. An earlier version
  // demanded the naive test fire on >50% of noise maps; it fires on ~1/3,
  // while the season design fires on almost none, which makes the point just
  // as conclusively without pinning the fixture's noise level.
  assert.ok(cellSig / tested > 2.5 * (soundCell / soundTested), 'naive test was not meaningfully worse');
  assert.ok(runsAny > 4 * soundAny, 'naive test should fire on far more noise maps than the season design');
  assert.ok(runsAny / FP_RUNS > 0.2, 'naive test barely fired at all - fixture may have too little noise to make the point');
});

console.log('\nbootstrap power');

// Half the seasons (the first 12 after a seeded shuffle) get track 0, the
// dateline track, moved 10 degrees south. Subset = those 12 seasons.
function shiftRun(seed, k, deg) {
  var A0 = makeArchive(seed), r = rngOf(900 + seed), subS = randomSeasons(A0.seasons, k, r);
  var isSub = {}; subS.forEach(function (s) { isSub[s] = true; });
  var A = makeArchive(seed, { shiftSouth: deg, shifted: function (l) { return isSub[l.season]; } });
  var sub = pickSeasons(A.lows, subS);
  return { A: A, subS: subS, sub: sub, res: CP.compare(A.lows, sub, { seasons: A.seasons, subsetSeasons: subS, iterations: 3000, seed: seed }) };
}
// A flagged cell counts as "the shift" if it sits where track 0 was or where it went.
function nearTrack0(c, southBy) {
  var dl = Math.abs(((c.lonC - 180) + 540) % 360 - 180);
  return dl < 40 && c.latC > 48 - southBy - 12 && c.latC < 48 + 12;
}

var POWER = (function () {
  var rows = [];
  for (var s = 0; s < 20; s++) rows.push(shiftRun(70 + s, 12, 10));
  return rows;
})();

test('an injected 10-degree southward shift of the dateline track in half the seasons IS detected (20 archives)', function () {
  var hits = 0, signOk = 0, cellsFDR = 0, farFalse = 0, bonf = 0, perCellN = 0;
  POWER.forEach(function (row) {
    var rs = row.res, flagged = rs.cells.filter(function (c) { return c.shape.sigFDR || c.rate.sigFDR; });
    if (flagged.length) hits++;
    cellsFDR += rs.summary.shape.nSigFDR;
    // Direction: the field must be NEGATIVE where the track used to be (lat ~48)
    // and POSITIVE where it was moved to (lat ~38).
    var oldNeg = 0, newPos = 0;
    rs.cells.forEach(function (c) {
      if (!nearTrack0(c, 10)) return;
      if (c.shape.sigFDR && c.shape.diff < 0 && c.latC > 44) oldNeg++;
      if (c.shape.sigFDR && c.shape.diff > 0 && c.latC < 44) newPos++;
    });
    if (oldNeg > 0 && newPos > 0) signOk++;
    rs.cells.forEach(function (c) { if (c.shape.sigFDR && !nearTrack0(c, 10) ) farFalse++; });
    // Bonferroni reference (the alternative argued against in composite.js)
    bonf += rs.cells.filter(function (c) { return c.shape.p !== null && c.shape.p <= 0.05 / rs.summary.shape.nTested; }).length;
    perCellN += rs.summary.shape.nSigCell;
  });
  report('power: FDR flagged a cell in ' + hits + '/20 archives; flagged BOTH the vacated and the new latitudes (correct sign) in ' +
         signOk + '/20');
  report('mean FDR-flagged cells per map (shape): ' + (cellsFDR / 20).toFixed(1) + '; per-cell p<.05: ' + (perCellN / 20).toFixed(1) +
         '; Bonferroni (p<.05/m): ' + (bonf / 20).toFixed(1) + '; flagged outside the shifted track: ' + farFalse + ' cell(s) in 20 maps');
  assert.ok(hits >= 18, 'power too low: ' + hits + '/20');
  assert.ok(signOk >= 14, 'shift detected but not with the right sign pattern: ' + signOk + '/20');
});

test('power by number of defining seasons (the evidence behind the minimum-seasons guard)', function () {
  var rows = [];
  [3, 4, 5, 6, 8, 12].forEach(function (k) {
    var hits = 0, nn = 12;
    for (var s = 0; s < nn; s++) {
      var run = shiftRun(200 + s, k, 10);
      if (run.res.status === 'ok' && run.res.cells.some(function (c) { return c.shape.sigFDR || c.rate.sigFDR; })) hits++;
    }
    rows.push('k=' + k + ': ' + hits + '/' + nn);
  });
  report('detected at k seasons -> ' + rows.join('   '));
  assert.ok(true);
});

console.log('\nevents design (a subset that cuts across seasons)');

test('auto-detects a subset that is not whole seasons and switches design', function () {
  var A = makeArchive(41), r = rngOf(8);
  var sub = A.lows.filter(function () { return r() < 0.4; });
  var res = CP.compare(A.lows, sub, { seasons: A.seasons, iterations: 200 });
  assert.strictEqual(res.status, 'ok');
  assert.strictEqual(res.design, 'events');
  var forced = CP.compare(A.lows, sub, { seasons: A.seasons, iterations: 200, design: 'seasons' });
  assert.strictEqual(forced.status, 'invalid');
  assert.ok(/partly/.test(forced.reason));
});

test('events design: a random 40% label shows no FDR-significant cells (30 archives)', function () {
  var any = 0, cells = 0, tested = 0, cellSig = 0;
  for (var run = 0; run < 30; run++) {
    var A = makeArchive(300 + run), r = rngOf(60 + run);
    var sub = A.lows.filter(function () { return r() < 0.4; });
    var res = CP.compare(A.lows, sub, { seasons: A.seasons, iterations: 1500, seed: run + 1 });
    assert.strictEqual(res.design, 'events');
    if (res.summary.shape.nSigFDR > 0 || res.summary.rate.nSigFDR > 0) any++;
    cells += res.summary.shape.nSigFDR; cellSig += res.summary.shape.nSigCell; tested += res.summary.shape.nTested;
  }
  report('events design on random labels: per-cell ' + pct(cellSig / tested) + ', FDR cells ' + cells + ', maps with any ' + any + '/30');
  assert.ok(cellSig / tested < 0.08 && cellSig / tested > 0.015);
  // cells/tested is the guarantee that matters: Benjamini-Hochberg bounds the
  // expected PROPORTION of discoveries that are false, so a vanishing share of
  // tested cells flagged across all the maps is what "controlled" looks like.
  // The map-level count below is a loose smoke bound, not an FDR guarantee -
  // FDR says nothing about the probability that a given map has any discovery
  // at all, and an earlier 0.15 bound here conflated it with a family-wise
  // error rate, then failed on 5/30 which is within binomial noise of itself.
  assert.ok(cells / tested < 0.005);
  assert.ok(any / 30 <= 0.35);
});

test('events design: a label tied to a 10-degree shift is detected', function () {
  var hits = 0;
  for (var run = 0; run < 10; run++) {
    var A = makeArchive(400 + run, { shiftSouth: 10, shifted: function (l) { return l.flag; } });
    var sub = A.lows.filter(function (l) { return l.flag; });
    var res = CP.compare(A.lows, sub, { seasons: A.seasons, iterations: 2000, seed: run + 1 });
    assert.strictEqual(res.design, 'events');
    if (res.summary.shape.nSigFDR > 0) hits++;
  }
  report('events design power: ' + hits + '/10');
  assert.ok(hits >= 9);
});

/* ==================================================== determinism & edges */

console.log('\ndeterminism and edge cases');

test('a fixed seed reproduces the result exactly; a different seed changes p but not the observed field', function () {
  var A = makeArchive(51), subS = A.seasons.slice(4, 13), sub = pickSeasons(A.lows, subS);
  var o = { seasons: A.seasons, subsetSeasons: subS, iterations: 800, seed: 99 };
  var a = CP.compare(A.lows, sub, o), b = CP.compare(A.lows, sub, o);
  same(a, b);
  var c = CP.compare(A.lows, sub, { seasons: A.seasons, subsetSeasons: subS, iterations: 800, seed: 100 });
  assert.notStrictEqual(JSON.stringify(a.cells.map(function (x) { return x.rate.p; })), JSON.stringify(c.cells.map(function (x) { return x.rate.p; })));
  same(a.cells.map(function (x) { return x.rate.diff; }), c.cells.map(function (x) { return x.rate.diff; }));
  // and the PRNG itself
  var r1 = CP.rng(5), r2 = CP.rng(5), r3 = CP.rng(6), i, eq = 0, v;
  for (i = 0; i < 100; i++) { v = r1(); assert.ok(v >= 0 && v < 1); assert.strictEqual(v, r2()); if (v === r3()) eq++; }
  assert.ok(eq < 3);
});

test('PRNG is uniform enough (mean, spread, no stuck bits)', function () {
  var r = CP.rng(2024), n = 200000, s = 0, s2 = 0, bins = new Array(10).fill(0), i, v;
  for (i = 0; i < n; i++) { v = r(); s += v; s2 += v * v; bins[Math.floor(v * 10)]++; }
  near(s / n, 0.5, 0.005); near(s2 / n - 0.25, 1 / 12, 0.003);
  bins.forEach(function (b) { near(b / n, 0.1, 0.005); });
});

test('seed stability: the flagged set barely moves between seeds on a real shift', function () {
  var A = makeArchive(70, {}), row = POWER[0], res0 = row.res;
  var res1 = CP.compare(row.A.lows, row.sub, { seasons: row.A.seasons, subsetSeasons: row.subS, iterations: 3000, seed: 777 });
  var s0 = {}, s1 = {}, both = 0, either = 0;
  res0.cells.forEach(function (c) { if (c.shape.sigFDR) s0[c.id] = 1; });
  res1.cells.forEach(function (c) { if (c.shape.sigFDR) s1[c.id] = 1; });
  Object.keys(s0).concat(Object.keys(s1)).filter(function (x, i, a) { return a.indexOf(x) === i; }).forEach(function (id) {
    either++; if (s0[id] && s1[id]) both++;
  });
  report('flagged-set overlap between two seeds: ' + both + '/' + either + ' cells');
  assert.ok(either > 0 && both / either > 0.8);
});

test('empty subset, empty full set', function () {
  var A = makeArchive(61);
  var e = CP.compare(A.lows, [], { seasons: A.seasons, iterations: 100 });
  assert.strictEqual(e.status, 'empty'); assert.strictEqual(e.reliability, 'none');
  assert.strictEqual(e.cells.length, 0); assert.strictEqual(e.n.events, 0); assert.ok(e.reason);
  var f = CP.compare([], [], { iterations: 100 });
  assert.strictEqual(f.status, 'empty');
});

test('single-season subset: refused with a reason, no p-values, no stipples', function () {
  var A = makeArchive(62), sub = pickSeasons(A.lows, [A.seasons[7]]);
  var r = CP.compare(A.lows, sub, { seasons: A.seasons, subsetSeasons: [A.seasons[7]], iterations: 500 });
  assert.strictEqual(r.status, 'insufficient'); assert.strictEqual(r.reliability, 'none');
  assert.ok(/1 season/.test(r.reason), r.reason);
  assert.strictEqual(r.n.seasons, 1); assert.ok(r.n.events > 20);
  assert.ok(r.cells.length > 0);                              // descriptive numbers still there
  r.cells.forEach(function (c) {
    assert.strictEqual(c.rate.p, null); assert.strictEqual(c.rate.q, null);
    assert.strictEqual(c.rate.sigCell, false); assert.strictEqual(c.rate.sigFDR, false);
    assert.strictEqual(c.shape.sigFDR, false);
  });
  assert.strictEqual(r.summary.rate.nSigFDR, 0); assert.strictEqual(r.summary.rate.nSigCell, 0);
  assert.strictEqual(r.inference, false);
});

test('season-count guard: 4 refused, 5-7 allowed but flagged low reliability, 8+ ok', function () {
  var A = makeArchive(63), out = {};
  [4, 5, 7, 8].forEach(function (k) {
    var s = A.seasons.slice(0, k);
    out[k] = CP.compare(A.lows, pickSeasons(A.lows, s), { seasons: A.seasons, subsetSeasons: s, iterations: 300 });
  });
  assert.strictEqual(out[4].status, 'insufficient');
  assert.strictEqual(out[5].status, 'ok'); assert.strictEqual(out[5].reliability, 'low'); assert.ok(out[5].warnings.length);
  assert.strictEqual(out[7].reliability, 'low');
  assert.strictEqual(out[8].status, 'ok'); assert.strictEqual(out[8].reliability, 'ok');
  // A pool that is itself too small cannot be resampled.
  var tiny = makeArchive(64, { nSeasons: 6 });
  var t = CP.compare(tiny.lows, pickSeasons(tiny.lows, tiny.seasons.slice(0, 5)), { seasons: tiny.seasons, iterations: 100 });
  assert.strictEqual(t.status, 'insufficient'); assert.ok(/resample from/.test(t.reason));
});

test('subset == full set: zero difference field, p = 1, nothing significant anywhere', function () {
  var A = makeArchive(65);
  var r = CP.compare(A.lows, A.lows.slice(), { seasons: A.seasons, iterations: 500 });
  assert.strictEqual(r.status, 'ok'); assert.strictEqual(r.identical, true);
  assert.ok(r.cells.length > 50);
  r.cells.forEach(function (c) {
    ['rate', 'shape'].forEach(function (f) {
      // Not strictEqual: subset and all rates are summed in different orders,
      // so an identical set can differ by one ulp (observed 1.4e-17). The
      // claim is "no difference", not "the same floating-point rounding".
      near(c[f].diff, 0, 1e-12, f + ' diff in cell ' + c.id);
      assert.strictEqual(c[f].sigCell, false); assert.strictEqual(c[f].sigFDR, false);
      if (c.tested) { assert.strictEqual(c[f].p, 1); assert.strictEqual(c[f].q, 1); }
    });
    if (c.tested && c.nAll > 0) near(c.rate.ratio, 1, 1e-12);
  });
  assert.strictEqual(r.summary.rate.nSigFDR, 0); assert.strictEqual(r.summary.rate.nSigCell, 0);
  assert.strictEqual(r.summary.shape.nSigFDR, 0);
  // also when the "same" set is a different array of different (copied) objects
  var copy = A.lows.map(function (l) { var c = {}; for (var k in l) c[k] = l[k]; return c; });
  var r2 = CP.compare(A.lows, copy, { seasons: A.seasons, iterations: 100 });
  assert.strictEqual(r2.identical, true);
});

test('a subset that is not contained in the full set is refused rather than tested', function () {
  var A = makeArchive(66), stray = [{ season: 2001, id: 'stray', fixes: [{ lat: 40, lon: 100, cat: 'HF', pres: 990 }] }];
  var r = CP.compare(A.lows, A.lows.slice(0, 300).concat(stray), { seasons: A.seasons, iterations: 100 });
  assert.strictEqual(r.status, 'invalid'); assert.ok(/not contained/.test(r.reason));
  var r2 = CP.compare(A.lows.slice(0, 100), A.lows.slice(0, 200), { iterations: 100 });
  assert.strictEqual(r2.status, 'invalid');
});

test('sample sizes are reported prominently: n_events, n_seasons, per-cell counts, and they agree with the data', function () {
  var A = makeArchive(67), subS = A.seasons.slice(2, 10), sub = pickSeasons(A.lows, subS);
  var r = CP.compare(A.lows, sub, { seasons: A.seasons, subsetSeasons: subS, iterations: 200 });
  var fixes = 0; sub.forEach(function (l) { fixes += l.fixes.length; });
  assert.strictEqual(r.n.events, sub.length); assert.strictEqual(r.n.seasons, 8); assert.strictEqual(r.n.allSeasons, 25);
  assert.strictEqual(r.n.fixes, fixes); assert.strictEqual(r.n.allEvents, A.lows.length);
  var sum = 0, sumAll = 0, thin = 0, fat = 0;
  r.cells.forEach(function (c) {
    sum += c.nSubset; sumAll += c.nAll;
    assert.ok(c.nSubset <= c.nAll); assert.ok(c.nSubsetSeasons <= 8); assert.ok(c.nSubsetEvents <= c.nSubset);
    if (c.nSubset > 0 && c.nSubset <= 3) thin++; if (c.nSubset >= 40) fat++;
  });
  assert.strictEqual(sum, fixes);
  // 40, not 100: this fixture's busiest subset cell holds 75 fixes, so the old
  // threshold could never be met and the assertion tested nothing. The point is
  // that per-cell counts span a wide enough range for a UI to distinguish a
  // cell backed by 3 fixes from one backed by dozens - here 53 cells hold <= 3
  // and 8 hold >= 44, which is the range that matters.
  assert.ok(thin > 0 && fat > 0, 'the test archive should have both thin and fat cells');
});

test('cells expose geometry a renderer can draw, in stable global ids', function () {
  var A = makeArchive(68), r = CP.compare(A.lows, pickSeasons(A.lows, A.seasons.slice(0, 9)),
    { seasons: A.seasons, subsetSeasons: A.seasons.slice(0, 9), iterations: 100 });
  var ids = {};
  r.cells.forEach(function (c) {
    assert.ok(!ids[c.id]); ids[c.id] = 1;
    assert.ok(c.lat1 > c.lat0 && c.dlon > 0 && c.lonC >= -180 && c.lonC < 180 && c.areaKm2 > 1e5);
  });
  var g = CP.grid(r.options.latStep, r.options.lonOrigin);
  r.cells.forEach(function (c) { assert.strictEqual(g.cellIndex(c.latC, c.lonC), c.id); });
});

/* ============================================================= real archive */

console.log('\nreal archive');

var REAL = null;
function realData() {
  if (!REAL) {
    var raw = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs', 'data', 'hf-lows.json'), 'utf8'));
    REAL = HF.decode(raw);
  }
  return REAL;
}

test('real archive: every fix is binned (none dropped), tip-jet events included', function () {
  var D = realData(), fixes = 0, tj = 0;
  D.lows.forEach(function (l) { fixes += l.fixes.length; if (l.cls === 'tipjet') tj++; });
  var d = CP.density(D.lows, { seasons: D.seasons });
  assert.strictEqual(d.total, fixes); assert.strictEqual(d.droppedFixes, 0);
  assert.strictEqual(d.nEvents, D.lows.length); assert.strictEqual(d.nSeasons, D.seasons.length);
  assert.ok(tj > 0);
  var peak = d.cells.reduce(function (m, c) { return c.count > m.count ? c : m; }, d.cells[0]);
  report('real archive: ' + d.cells.length + ' occupied cells of ' + d.grid.nCells + ', ' + d.total + ' fixes, ' + tj +
         ' tip-jet events counted; busiest cell ' + peak.latC.toFixed(0) + 'N ' + Math.abs(peak.lonC).toFixed(0) + (peak.lonC < 0 ? 'W' : 'E') + ' with ' + peak.count);
});

test('real archive: random 12-vs-13 season splits (no physical reason to differ) flag ~nothing', function () {
  var D = realData(), seasons = D.seasons.map(function (s) { return s.start; });
  var nSplit = 40, any = 0, fdrCells = 0, cellSig = 0, tested = 0, fdrShape = 0, anyShape = 0, r = rngOf(2025);
  for (var i = 0; i < nSplit; i++) {
    var s12 = randomSeasons(seasons, 12, r);
    var res = CP.compare(D.lows, pickSeasons(D.lows, s12), { seasons: D.seasons, subsetSeasons: s12, iterations: 1500, seed: i + 1 });
    assert.strictEqual(res.status, 'ok');
    if (res.summary.rate.nSigFDR) any++; fdrCells += res.summary.rate.nSigFDR;
    cellSig += res.summary.rate.nSigCell; tested += res.summary.rate.nTested;
    if (res.summary.shape.nSigFDR) anyShape++; fdrShape += res.summary.shape.nSigFDR;
  }
  report(nSplit + ' random splits of the real archive: rate field per-cell ' + pct(cellSig / tested) + ', FDR cells ' + fdrCells +
         ' (' + any + '/' + nSplit + ' maps with any); shape field FDR cells ' + fdrShape + ' (' + anyShape + '/' + nSplit + ')');
  assert.ok(cellSig / tested < 0.08); assert.ok(any / nSplit <= 0.15); assert.ok(anyShape / nSplit <= 0.15);
});

test('real archive: 12 earliest seasons vs 13 latest (reported, not asserted as a finding)', function () {
  var D = realData(), seasons = D.seasons.map(function (s) { return s.start; });
  var early = seasons.slice(0, 12);
  var t0 = Date.now();
  var res = CP.compare(D.lows, pickSeasons(D.lows, early), { seasons: D.seasons, subsetSeasons: early, seed: 1 });
  var secs = (Date.now() - t0) / 1000;
  assert.strictEqual(res.status, 'ok');
  report('12 earliest (2001-12) vs all, rate field : ' + res.summary.rate.nSigCell + ' per-cell / ' + res.summary.rate.nSigFDR +
         ' FDR of ' + res.summary.rate.nTested + ' tested cells (chance alone: ' + res.summary.rate.expectedByChance.toFixed(1) + ' per-cell)');
  report('12 earliest (2001-12) vs all, shape field: ' + res.summary.shape.nSigCell + ' per-cell / ' + res.summary.shape.nSigFDR + ' FDR');
  var late = seasons.slice(12);
  var res2 = CP.compare(D.lows, pickSeasons(D.lows, late), { seasons: D.seasons, subsetSeasons: late, seed: 1 });
  report('13 latest (2013-25) vs all,   rate field : ' + res2.summary.rate.nSigCell + ' per-cell / ' + res2.summary.rate.nSigFDR + ' FDR; shape: ' +
         res2.summary.shape.nSigCell + ' / ' + res2.summary.shape.nSigFDR);
  var mid = seasons.slice(3, 12);
  var res3 = CP.compare(D.lows, pickSeasons(D.lows, mid), { seasons: D.seasons, subsetSeasons: mid, seed: 1 });
  report('2004-12 (skipping the 3 near-empty seasons) vs all: rate ' + res3.summary.rate.nSigCell + ' / ' + res3.summary.rate.nSigFDR +
         ' FDR; shape ' + res3.summary.shape.nSigCell + ' / ' + res3.summary.shape.nSigFDR);
  report('one full-archive compare() took ' + secs.toFixed(2) + ' s at ' + res.options.iterations + ' draws');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
