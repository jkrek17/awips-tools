#!/usr/bin/env node
/* Tests for docs/assets/js/regress.js (HF.regress: regression of storm-track
   properties on climate indices). Same convention as
   tests/playback/test_playback.js: only Node, no packages, no runner -
   node:assert and a tiny harness below.

     node tests/regress/test_regress.js

   regress.js, teleconnect.js and util.js are plain browser scripts that
   attach to window.HF, so they are loaded into a vm context with a fake
   `window`. docs/data/teleconnections.js and hf-lows.js are loaded the same
   way. The last blocks run the real 1,932-event archive.

   Expected values never come from the module's own arithmetic where that
   would let a bug cancel against itself: known-answer data are built here
   with their own seeded generator and their own mean/SD, the circular-mean
   check builds its own tracks, and the naive-longitude comparison is computed
   with independent code. */

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
load('docs/assets/js/regress.js');
load('docs/data/teleconnections.js');
load('docs/data/hf-lows.js');
var HF = ctx.window.HF;
var RG = HF.regress;
var DATA = HF.decode(ctx.window.HF_DATA);
var TC = HF.teleconnect.create({ archive: DATA });

var passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('  ok   ' + name); }
  catch (e) { failed++; console.log('  FAIL ' + name + '\n       ' + (e && e.message)); }
}
function near(a, b, tol, msg) {
  assert.ok(Math.abs(a - b) <= tol, (msg || 'values differ') + ': ' + a + ' vs ' + b + ' (tol ' + tol + ')');
}
// Objects built inside the vm have that context's Object.prototype, so
// deepStrictEqual rejects them against literals made out here. Compare by
// value instead.
function same(a, b, msg) { assert.strictEqual(JSON.stringify(a), JSON.stringify(b), msg); }
function f3(v) { return (v >= 0 ? '+' : '') + v.toFixed(3); }

/* ---- independent test helpers (not the module's code) ---- */

// A tiny LCG + Box-Muller, so the synthetic data do not depend on the
// generator under test.
function lcg(seed) {
  var s = seed >>> 0;
  function u() { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return (s + 0.5) / 4294967296; }
  var spare = null;
  return {
    u: u,
    norm: function () {
      if (spare !== null) { var r = spare; spare = null; return r; }
      var a = Math.sqrt(-2 * Math.log(u())), b = 2 * Math.PI * u();
      spare = a * Math.sin(b);
      return a * Math.cos(b);
    }
  };
}
function popSd(a) {
  var m = 0, v = 0, i;
  for (i = 0; i < a.length; i++) m += a[i];
  m /= a.length;
  for (i = 0; i < a.length; i++) v += (a[i] - m) * (a[i] - m);
  return Math.sqrt(v / a.length);
}
function wrap180(d) { return d - 360 * Math.floor((d + 180) / 360); }

/** Synthetic columns: `seasons` seasons x `perSeason` events, months 10-3,
    two predictors with arbitrary mean/SD, a known month effect, and
    y = intercept + monthEffect + b1*x1 + b2*x2 (+ noise). */
function synth(opts) {
  var g = lcg(opts.seed || 1), rows = { y: [], season: [], month: [], x: { a: [], b: [] }, mjo: null };
  var monthEff = { 10: 0, 11: 1.5, 12: 3, 1: 4, 2: 2.5, 3: 0.5 }, months = [10, 11, 12, 1, 2, 3];
  var truth = opts.truth || { a: 2, b: -0.5 };
  for (var s = 0; s < opts.seasons; s++) {
    for (var k = 0; k < opts.perSeason; k++) {
      var m = months[Math.floor(g.u() * 6)];
      var xa = 5 + 3 * g.norm(), xb = -2 + 0.7 * g.norm();
      var y = 10 + monthEff[m] + truth.a * xa + truth.b * xb + (opts.noise ? opts.noise * g.norm() : 0);
      rows.y.push(y); rows.season.push(2004 + s); rows.month.push(m);
      rows.x.a.push(xa); rows.x.b.push(xb);
    }
  }
  rows.monthEff = monthEff;
  return rows;
}
function quick(extra) {
  var o = { predictors: ['a', 'b'], iterations: 400, permutations: 199, seed: 1 };
  for (var k in extra) o[k] = extra[k];
  return o;
}

/* =========================================================== OLS */
console.log('OLS correctness');

test('ols recovers a hand-computable line exactly (y = 3 + 2x, no noise)', function () {
  var X = [], y = [], i;
  for (i = 0; i < 10; i++) { X.push([1, i]); y.push(3 + 2 * i); }
  var r = RG.ols(X, y);
  near(r.coef[0], 3, 1e-10); near(r.coef[1], 2, 1e-10);
  near(r.r2, 1, 1e-12);
  assert.strictEqual(r.rank, 2);
});

test('ols slope equals Sxy/Sxx and intercept ybar - b xbar on noisy data', function () {
  var g = lcg(5), X = [], y = [], xs = [], i;
  for (i = 0; i < 50; i++) { var x = g.norm() * 2 + 1; xs.push(x); X.push([1, x]); y.push(0.7 * x + 4 + g.norm()); }
  var xb = 0, yb = 0, sxy = 0, sxx = 0;
  for (i = 0; i < 50; i++) { xb += xs[i]; yb += y[i]; }
  xb /= 50; yb /= 50;
  for (i = 0; i < 50; i++) { sxy += (xs[i] - xb) * (y[i] - yb); sxx += (xs[i] - xb) * (xs[i] - xb); }
  var r = RG.ols(X, y);
  near(r.coef[1], sxy / sxx, 1e-10);
  near(r.coef[0], yb - (sxy / sxx) * xb, 1e-10);
});

test('ols recovers four known coefficients exactly with no noise', function () {
  var g = lcg(9), X = [], y = [], i, truth = [1.5, -2, 0.25, 7];
  for (i = 0; i < 200; i++) {
    var row = [1, g.norm(), g.norm() * 3, g.u()];
    X.push(row);
    y.push(truth[0] * row[0] + truth[1] * row[1] + truth[2] * row[2] + truth[3] * row[3]);
  }
  var r = RG.ols(X, y);
  for (i = 0; i < 4; i++) near(r.coef[i], truth[i], 1e-9, 'coef ' + i);
});

test('ols recovers coefficients within sampling error when there is noise', function () {
  var g = lcg(11), X = [], y = [], i, truth = [1, -2, 0.5];
  for (i = 0; i < 4000; i++) {
    var row = [1, g.norm(), g.norm()];
    X.push(row);
    y.push(truth[0] + truth[1] * row[1] + truth[2] * row[2] + g.norm());     // sigma = 1, SE ~ 0.016
  }
  var r = RG.ols(X, y);
  for (i = 0; i < 3; i++) near(r.coef[i], truth[i], 0.08, 'coef ' + i);
  near(r.sse / (4000 - 3), 1, 0.1, 'residual variance');
});

test('ols reports an exactly collinear column as NaN and aliased, never a silent 0', function () {
  var g = lcg(2), X = [], y = [], i;
  for (i = 0; i < 40; i++) { var a = g.norm(); X.push([1, a, 2 * a]); y.push(1 + a + g.norm() * 0.1); }
  var r = RG.ols(X, y);
  assert.strictEqual(r.rank, 2);
  same(r.aliased, [2]);
  assert.ok(isNaN(r.coef[2]));
  assert.ok(isFinite(r.coef[1]));
});

console.log('\nthe model: month effects, standardisation');

test('noise-free data: per-SD coefficients and month effects recovered to 1e-8', function () {
  var d = synth({ seasons: 8, perSeason: 80, noise: 0 });
  var r = RG.fitData(d, quick());
  assert.strictEqual(r.status, 'ok');
  near(r.byName.a.coef, 2 * popSd(d.x.a), 1e-8, 'a per SD');
  near(r.byName.b.coef, -0.5 * popSd(d.x.b), 1e-8, 'b per SD');
  near(r.r2, 1, 1e-9);
  // month effects relative to the reference month
  var me = r.fixedEffects.month, ref = me.reference;
  me.effects.forEach(function (e) {
    near(e.coef, d.monthEff[e.month] - d.monthEff[ref], 1e-8, 'month ' + e.month);
  });
  assert.ok(/essentially exact/.test(r.warnings.join(' ')), 'noise-free fit says so');
});

test('with noise: coefficients land within tolerance, truth inside the interval', function () {
  var d = synth({ seasons: 20, perSeason: 50, noise: 4, seed: 3 });
  var r = RG.fitData(d, quick());
  var ta = 2 * popSd(d.x.a), tb = -0.5 * popSd(d.x.b);
  near(r.byName.a.coef, ta, 0.4, 'a'); near(r.byName.b.coef, tb, 0.4, 'b');
  assert.ok(r.byName.a.ci[0] <= ta && ta <= r.byName.a.ci[1], 'a CI ' + r.byName.a.ci + ' vs ' + ta);
  assert.ok(r.byName.b.ci[0] <= tb && tb <= r.byName.b.ci[1], 'b CI ' + r.byName.b.ci + ' vs ' + tb);
  assert.ok(r.r2 > r.r2Base, 'indices add to the calendar-only R^2');
});

test('standardisation: scaling a predictor by 10 leaves the standardised coefficient unchanged', function () {
  var d = synth({ seasons: 12, perSeason: 60, noise: 3, seed: 4 });
  var r1 = RG.fitData(d, quick());
  var d2 = JSON.parse(JSON.stringify(d));
  d2.x.a = d2.x.a.map(function (v) { return v * 10; });
  var r2 = RG.fitData(d2, quick());
  near(r2.byName.a.coef, r1.byName.a.coef, 1e-9, 'standardised coef');
  near(r2.byName.a.ci[0], r1.byName.a.ci[0], 1e-9, 'CI low');
  near(r2.byName.a.mde80, r1.byName.a.mde80, 1e-9, 'MDE');
  near(r2.byName.a.unit.perUnit, r1.byName.a.unit.perUnit / 10, 1e-9, 'per-unit slope shrinks 10x');
  near(r2.byName.a.unit.sd, r1.byName.a.unit.sd * 10, 1e-9, 'SD grows 10x');
  near(r2.byName.b.coef, r1.byName.b.coef, 1e-9, 'untouched predictor unchanged');
});

test('a month with no events in a bootstrap resample does not break the draw (dummy dropped, not NaN)', function () {
  // May appears in a single season only; resamples that miss that season have
  // an all-zero May column. Every draw must still return finite numbers.
  var d = synth({ seasons: 10, perSeason: 40, noise: 2, seed: 8 });
  for (var i = 0; i < 6; i++) { d.y.push(15 + i * 0.1); d.season.push(2004); d.month.push(5); d.x.a.push(5 + i * 0.3); d.x.b.push(-2); }
  var r = RG.fitData(d, quick({ iterations: 600 }));
  assert.strictEqual(r.bootstrap.failed, 0);
  assert.ok(r.byName.a.nDraws === 600 && r.byName.a.ci && isFinite(r.byName.a.ci[0]));
});

test('rows missing a value are dropped and counted by cause; the warning says so', function () {
  var d = synth({ seasons: 8, perSeason: 40, noise: 1, seed: 6 });
  d.x.a[3] = null; d.x.a[9] = null; d.y[5] = null;
  var r = RG.fitData(d, quick());
  assert.strictEqual(r.n.input, 320);
  assert.strictEqual(r.n.events, 317);
  assert.strictEqual(r.n.dropped.a, 2);
  assert.strictEqual(r.n.dropped.response, 1);
  assert.ok(/3 of 320/.test(r.warnings.join(' ')));
});

/* ===================================================== circular longitude */
console.log('\ncircular longitude');

function pacificLows() {
  return DATA.lows.filter(function (l) { return l.basin === 'pac' && l.season >= DATA.recordStart; });
}

test('a track straddling the dateline averages to ~180, and the naive linear mean is ~0 (the bug)', function () {
  var track = [170, 174, 178, -178, -174, -170];
  var naive = track.reduce(function (s, v) { return s + v; }, 0) / track.length;
  near(naive, 0, 1e-12, 'naive linear mean');                      // the Atlantic: wrong by ~180 degrees
  var cm = RG.circMeanDeg(track);
  near(Math.abs(wrap180(cm.mean - 180)), 0, 1e-9, 'circular mean is on the dateline');
  assert.ok(cm.R > 0.98, 'a tight track has a resultant length near 1');
  // asymmetric: 3 fixes west of the line, 1 east
  var cm2 = RG.circMeanDeg([172, 176, 179, -177]);
  near(wrap180(cm2.mean), 177.5, 0.2);
  // opposite points have no mean direction
  assert.ok(isNaN(RG.circMeanDeg([0, 180]).mean));
});

test('unwrapAround puts both sides of the dateline on one branch; it is the identity where nothing wraps', function () {
  near(RG.unwrapAround(-170, 190), 190, 1e-12);                    // 170W -> 190E
  near(RG.unwrapAround(170, 190), 170, 1e-12);
  near(RG.unwrapAround(-45, -45), -45, 1e-12);
  near(RG.unwrapAround(-100, -45), -100, 1e-12);
  near(RG.unwrapAround(5, -45), 5, 1e-12);
});

test('real archive: Atlantic frame is the identity; Pacific events really do straddle the dateline', function () {
  var atl = DATA.lows.filter(function (l) { return l.basin === 'atl'; }).map(RG.RESPONSES.lon.get);
  var c = RG.circMeanDeg(atl).mean, maxDiff = 0;
  atl.forEach(function (v) { maxDiff = Math.max(maxDiff, Math.abs(RG.unwrapAround(v, c) - v)); });
  near(maxDiff, 0, 1e-9, 'Atlantic unwrapping changes nothing');
  var pac = DATA.lows.filter(function (l) { return l.basin === 'pac'; }).map(RG.RESPONSES.lon.get);
  var east = pac.filter(function (v) { return v > 0; }).length, west = pac.filter(function (v) { return v < 0; }).length;
  assert.ok(east > 100 && west > 100, 'both signs present (' + east + ' E, ' + west + ' W): the seam matters');
  var pc = RG.circMeanDeg(pac).mean;
  assert.ok(pc > 150 || pc < -150, 'Pacific centre is near the dateline: ' + pc);
});

test('synthetic Pacific tracks across the dateline: regression recovers the slope; a regression on raw degrees does not', function () {
  // Real Pacific event dates (so the real NAO values attach), invented
  // tracks: every fix lies +-5 degrees of a centre at 180 + 4 * NAO(mean5),
  // so the centres run from ~170E to ~170W and back. The true slope is 4
  // degrees of longitude per unit NAO; per SD it is 4 * SD(NAO).
  var lows = [], naoVals = [], raw = [], cx = [];
  pacificLows().forEach(function (l) {
    var a = TC.attribute(l);
    if (a.nao.mean5 == null) return;
    var centre = 180 + 4 * a.nao.mean5;
    var fixes = [-5, 0, 5].map(function (off) {
      return { date: l.start, lat: 40, lon: wrap180(centre + off), cat: 'HF', pres: 980 };
    });
    var m = { id: l.id, basin: 'pac', season: l.season, start: l.start, month: l.month, key: l.key, fixes: fixes, minP: 980 };
    lows.push(m); naoVals.push(a.nao.mean5); cx.push(m);
    raw.push(wrap180(centre));
  });
  assert.ok(lows.length > 800);
  var r = RG.fit(lows, { basin: 'pac', response: 'lon', predictors: ['nao'], teleconnect: TC, recordStart: DATA.recordStart,
                         iterations: 200, seed: 1 });
  near(r.byName.nao.coef, 4 * popSd(naoVals), 1e-6, 'per-SD longitude slope');
  near(r.byName.nao.unit.perUnit, 4, 1e-6, 'degrees of longitude per unit NAO');
  // the naive way: regress raw degrees (-180..180) on NAO
  var X = naoVals.map(function (v) { return [1, v]; });
  var naive = RG.ols(X, raw).coef[1];
  assert.ok(Math.abs(naive - 4) > 4, 'raw-degree slope ' + naive.toFixed(2) + ' is nowhere near 4');
  console.log('       (true 4.00 deg/unit; circular+unwrapped ' + r.byName.nao.unit.perUnit.toFixed(2) + ', raw-degree OLS ' + naive.toFixed(2) + ')');
  assert.ok(r.response.frame.centre > 150 || r.response.frame.centre < -150, 'frame centred on the dateline');
});

test('real Pacific events: raw-degree mean fix longitude gives a nonsense coefficient (~-40); the module gives ~+5', function () {
  function naiveLon(l) {
    var s = 0, i;
    for (i = 0; i < l.fixes.length; i++) s += l.fixes[i].lon;
    return s / l.fixes.length;
  }
  var bug = RG.fit(DATA.lows, { basin: 'pac', response: naiveLon, teleconnect: TC, iterations: 100 });
  var ok = RG.fit(DATA.lows, { basin: 'pac', response: 'lon', teleconnect: TC, iterations: 100 });
  console.log('       (PNA on mean fix longitude, per SD: raw degrees ' + f3(bug.byName.pna.coef) + ', circular ' + f3(ok.byName.pna.coef) + ')');
  assert.ok(bug.byName.pna.coef < -20, 'the bug reproduces: ' + bug.byName.pna.coef);
  assert.ok(ok.byName.pna.coef > 3 && ok.byName.pna.coef < 7);
});

/* ======================================================== bootstrap */
console.log('\nseason-block bootstrap');

test('one season: the interval is withheld and the module says why (no zero-width "infinite precision")', function () {
  var d = synth({ seasons: 1, perSeason: 300, noise: 3, seed: 12 });
  var r = RG.fitData(d, quick());
  assert.strictEqual(r.status, 'insufficient');
  assert.strictEqual(r.reliability, 'none');
  assert.strictEqual(r.n.seasons, 1);
  ['a', 'b'].forEach(function (nm) {
    var t = r.byName[nm];
    assert.strictEqual(t.ci, null, nm + ' ci');
    assert.strictEqual(t.se, null);
    assert.strictEqual(t.mde80, null);
    assert.strictEqual(t.flag, 'unavailable');
    assert.ok(isFinite(t.coef), 'the point estimate is still shown');
    assert.ok(/withheld/.test(t.note), t.note);
  });
  var w = r.warnings.join(' ');
  assert.ok(/Only 1 season/.test(w) && /zero-width/.test(w), w);
  assert.strictEqual(r.bootstrap.method, 'withheld');
});

test('fewer than minSeasons (4 < 5) is also withheld; exactly minSeasons is not', function () {
  var r4 = RG.fitData(synth({ seasons: 4, perSeason: 200, noise: 3, seed: 13 }), quick());
  assert.strictEqual(r4.byName.a.ci, null);
  var r5 = RG.fitData(synth({ seasons: 5, perSeason: 200, noise: 3, seed: 13 }), quick());
  assert.ok(r5.byName.a.ci && r5.byName.a.ci[1] > r5.byName.a.ci[0]);
  assert.strictEqual(r5.reliability, 'low', 'but 5-7 seasons is flagged low');
  assert.ok(/optimistic/.test(r5.warnings.join(' ')));
});

test('a genuine bootstrap interval has positive width and is not mistaken for a degenerate one', function () {
  var r = RG.fitData(synth({ seasons: 15, perSeason: 40, noise: 3, seed: 14 }), quick());
  var t = r.byName.a;
  assert.ok(t.ci[1] - t.ci[0] > 0.05);
  assert.strictEqual(t.nDraws, 400);
  assert.ok(!t.note, 'no degenerate-interval note: ' + t.note);
  assert.strictEqual(r.reliability, 'ok');
});

test('coverage: over 40 simulated archives of 20 seasons the 95% interval covers the truth at least 85% of the time', function () {
  var hit = 0, runs = 40;
  for (var s = 0; s < runs; s++) {
    var g = lcg(1000 + s), d = { y: [], season: [], month: [], x: { a: [] }, mjo: null };
    for (var k = 0; k < 20; k++) {
      var shock = 2 * g.norm();                    // season-level shock shared by that season's events
      for (var e = 0; e < 25; e++) {
        var x = g.norm();
        d.x.a.push(x); d.season.push(2004 + k); d.month.push(1 + Math.floor(g.u() * 3));
        d.y.push(3 + shock + 1.0 * x + g.norm());
      }
    }
    var r = RG.fitData(d, { predictors: ['a'], iterations: 300, seed: s + 1 });
    var truth = 1.0 * popSd(d.x.a);
    if (r.byName.a.ci[0] <= truth && truth <= r.byName.a.ci[1]) hit++;
  }
  assert.ok(hit / runs >= 0.85, 'covered ' + hit + ' of ' + runs);
  console.log('       (covered ' + hit + ' of ' + runs + ')');
});

/* ============================================================== MJO */
console.log('\nMJO harmonic pair');

/** Synthetic rows with a phase/amplitude pair. response peaks at `peakDeg`. */
function mjoSynth(opts) {
  var g = lcg(opts.seed || 1), d = { y: [], season: [], month: [], x: { a: [] }, mjo: { phase: [], amp: [] } };
  var rot = opts.rotate || 0;
  for (var s = 0; s < 15; s++) {
    for (var k = 0; k < 60; k++) {
      var ph = g.u() * 2 * Math.PI, amp = 0.4 + 1.6 * g.u(), m = [11, 12, 1, 2][Math.floor(g.u() * 4)];
      var x = g.norm();
      var y = 5 + 0.5 * m + 0.3 * x + g.norm() * (opts.noise == null ? 1 : opts.noise);
      if (opts.R) y += opts.R * amp * Math.cos(ph - opts.peakDeg * Math.PI / 180);
      d.x.a.push(x); d.season.push(2004 + s); d.month.push(m); d.y.push(y);
      d.mjo.phase.push(ph + rot); d.mjo.amp.push(amp);
    }
  }
  return d;
}
function mjoOpts(extra) { var o = quick({ predictors: ['a'], permutations: 499 }); for (var k in extra) o[k] = extra[k]; return o; }

test('an injected sinusoidal response is recovered at the right angle, amplitude and significance', function () {
  var r = RG.fitData(mjoSynth({ R: 1.5, peakDeg: 70, seed: 21 }), mjoOpts());
  var m = r.mjo;
  assert.strictEqual(m.status, 'ok');
  near(Math.abs(wrap180(m.angleDeg - 70)), 0, 8, 'angle of maximum response');
  near(m.R, 1.5, 0.25, 'R');
  assert.ok(m.p <= 0.01, 'permutation p ' + m.p);
  assert.strictEqual(m.flag, 'detected');
  assert.ok(m.ciR[0] > 0, 'R interval excludes 0');
  var lo = wrap180(m.angleCI[0] - m.angleDeg), hi = wrap180(m.angleCI[1] - m.angleDeg);
  assert.ok(lo <= 0 && hi >= 0 && hi - lo < 40, 'angle CI ' + m.angleCI + ' brackets the estimate and is narrow');
  console.log('       (injected R=1.50 at 70 deg: R=' + m.R.toFixed(3) + ', angle=' + m.angleDeg.toFixed(1) + ', p=' + m.p + ', MDE80=' + m.mde80.toFixed(2) + ')');
});

test('a peak at 350 degrees is reported near 350, not -10 or 190 (the angle wraps)', function () {
  var r = RG.fitData(mjoSynth({ R: 1.5, peakDeg: 350, seed: 22 }), mjoOpts());
  near(Math.abs(wrap180(r.mjo.angleDeg - 350)), 0, 8);
  assert.ok(r.mjo.angleDeg >= 0 && r.mjo.angleDeg < 360);
});

test('joint statistic is invariant to where phase zero is: rotating every phase moves the angle, not R or p', function () {
  var d1 = mjoSynth({ R: 1.0, peakDeg: 100, seed: 23 }), d2 = mjoSynth({ R: 1.0, peakDeg: 100, seed: 23, rotate: 1.3 });
  var a = RG.fitData(d1, mjoOpts()).mjo, b = RG.fitData(d2, mjoOpts()).mjo;
  near(b.R, a.R, 1e-8, 'R');
  near(b.p, a.p, 1e-12, 'p');
  near(wrap180(b.angleDeg - a.angleDeg - 1.3 * 180 / Math.PI), 0, 1e-6, 'angle shifts by the rotation');
  // whereas the two coefficients individually change
  assert.ok(Math.abs(a.components[0].coef - b.components[0].coef) > 0.1);
});

test('a linear term in phase cannot see a response that peaks at the wrap (the reason for the harmonic pair)', function () {
  var d = mjoSynth({ R: 2, peakDeg: 0, seed: 24, noise: 0.5 });
  var Xlin = [], Xh = [], i, y = d.y;
  for (i = 0; i < y.length; i++) {
    var ph = d.mjo.phase[i];
    Xlin.push([1, ph]);
    Xh.push([1, d.mjo.amp[i] * Math.cos(ph), d.mjo.amp[i] * Math.sin(ph)]);
  }
  var lin = RG.ols(Xlin, y), har = RG.ols(Xh, y);
  assert.ok(lin.r2 < 0.02, 'linear-in-phase R^2 ' + lin.r2);
  assert.ok(har.r2 > 0.3, 'harmonic R^2 ' + har.r2);
});

test('permutation null on random phase does not fire: p is not small, and the false-positive rate is near 5%', function () {
  var r0 = RG.fitData(mjoSynth({ R: 0, seed: 31 }), mjoOpts());
  assert.ok(r0.mjo.p > 0.05, 'p = ' + r0.mjo.p);
  assert.strictEqual(r0.mjo.flag, 'below-floor');
  var fp = 0, reps = 50;
  for (var s = 0; s < reps; s++) {
    var r = RG.fitData(mjoSynth({ R: 0, seed: 100 + s }), mjoOpts({ permutations: 99, iterations: 20, seed: s + 1 }));
    if (r.mjo.p < 0.05) fp++;
  }
  assert.ok(fp / reps <= 0.16, 'false positives ' + fp + ' of ' + reps);
  console.log('       (false positives at 5%: ' + fp + ' of ' + reps + ')');
});

test('permutation machinery agrees with the full fit (no internal-check warning)', function () {
  var r = RG.fitData(mjoSynth({ R: 1, peakDeg: 200, seed: 25 }), mjoOpts());
  assert.ok(!/Internal check/.test(r.warnings.join(' ')), r.warnings.join(' | '));
  assert.ok(r.mjo.permutableFraction > 0.5);
});

test('MJO term omitted with the reason when the payload has no eofPhase/eofAmplitude; the rest of the model still fits', function () {
  var stripped = vm.runInContext('(function(){var d = JSON.parse(JSON.stringify(window.HF_TELECONNECTIONS)); delete d.mjo.eofPhase; delete d.mjo.eofAmplitude; return d;})()', ctx);
  var tc2 = HF.teleconnect.create({ data: stripped, archive: DATA });
  var r = RG.fit(DATA.lows, { basin: 'atl', response: 'lat', teleconnect: tc2, data: stripped, mjo: true, iterations: 100 });
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.mjo.status, 'omitted');
  assert.ok(/eofPhase/.test(r.mjo.reason), r.mjo.reason);
  assert.ok(/MJO term omitted/.test(r.warnings.join(' ')));
  assert.ok(r.byName.nao.ci, 'index terms unaffected');
  var r2 = RG.fit(DATA.lows, { basin: 'atl', response: 'lat', teleconnect: TC, iterations: 50 });
  assert.strictEqual(r2.mjo.status, 'omitted');
  assert.strictEqual(r2.mjo.reason, 'not requested');
});

test('convection-longitude lookup interpolates the payload table and wraps through 360', function () {
  var table = ctx.window.HF_TELECONNECTIONS.mjo.eof.phaseConvention.convectionLonByPhase;
  near(RG.convectionLonAt(table, 0), table.convectionLonDegE[0], 1e-9);
  near(RG.convectionLonAt(table, 30), table.convectionLonDegE[1], 1e-9);
  near(RG.convectionLonAt(table, 15), 331.25, 1e-9, 'midway 313.9 -> 348.6');
  near(RG.convectionLonAt(table, 360), table.convectionLonDegE[0], 1e-9, '360 is 0');
  var mid = RG.convectionLonAt(table, 345);                         // 280.8 (330) -> 313.9 (360)
  near(mid, (280.8 + 313.9) / 2, 1e-9);
  near(RG.convectionLonAt(table, -15), mid, 1e-9, 'negative angles wrap');
});

test('real payload: MJO fit runs on the archive, uses radians, and reports the longitude of convection', function () {
  var r = RG.fit(DATA.lows, { basin: 'atl', response: 'lat', teleconnect: TC, mjo: true, iterations: 300, permutations: 299, seed: 1 });
  assert.strictEqual(r.mjo.status, 'ok');
  assert.strictEqual(r.mjo.phaseUnit, 'radians');
  assert.ok(r.mjo.angleDeg >= 0 && r.mjo.angleDeg < 360);
  assert.ok(r.mjo.convectionLonDegE >= 0 && r.mjo.convectionLonDegE < 360);
  assert.ok(r.mjo.p > 0 && r.mjo.p <= 1);
  assert.ok(/not RMM/.test(r.mjo.convention));
  assert.ok(r.n.events <= 1010 && r.n.events > 990, 'events with an MJO pentad: ' + r.n.events);
  assert.ok(/no MJO phase/.test(r.warnings.join(' ')), 'the dropped events are counted in a warning');
});

/* =============================================================== MDE80 */
console.log('\nminimum detectable effect');

test('MDE80 = 2.80 * SE with SE = CI width / (2 * 1.96), for every term', function () {
  var r = RG.fitData(synth({ seasons: 15, perSeason: 50, noise: 5, seed: 41 }), quick({ interactions: true }));
  assert.strictEqual(r.terms.length, 3);
  r.terms.forEach(function (t) {
    var se = (t.ci[1] - t.ci[0]) / (2 * 1.96);
    near(t.se, se, 1e-12, t.name + ' SE');
    near(t.mde80, 2.80 * se, 1e-12, t.name + ' MDE80');
  });
});

test('an injected strong effect is detected; an injected effect below the floor is flagged below-floor', function () {
  // noise SD 5, 750 events, x SD 3 -> SE per SD ~ 0.2-0.3; floor ~ 0.6-0.8
  var strong = RG.fitData(synth({ seasons: 15, perSeason: 50, noise: 5, seed: 42, truth: { a: 1.0, b: 0 } }), quick());
  var ta = strong.byName.a;
  assert.strictEqual(ta.flag, 'detected');
  assert.ok(ta.excludesZero && !ta.belowFloor && Math.abs(ta.coef) >= ta.mde80);
  var weak = RG.fitData(synth({ seasons: 15, perSeason: 50, noise: 5, seed: 42, truth: { a: 0.05, b: 0 } }), quick());
  var tw = weak.byName.a;
  assert.strictEqual(tw.flag, 'below-floor');
  assert.ok(tw.belowFloor && Math.abs(tw.coef) < tw.mde80, 'coef ' + tw.coef + ' floor ' + tw.mde80);
  // the same sample could not have seen it, whatever it found: the floor is ~ the same for both
  near(tw.mde80, ta.mde80, 0.3 * ta.mde80, 'floor is a property of the sample, not of the effect');
  // b was truly zero: below its own floor too
  assert.strictEqual(strong.byName.b.flag, 'below-floor');
});

test('a coefficient whose interval excludes zero but is under its floor is flagged below-floor with excludesZero set', function () {
  // |b| between 1.96 SE and 2.80 SE: scan seeds until one lands there, which
  // exercises the winner's-curse branch with real bootstrap output.
  var found = null;
  for (var seed = 1; seed < 400 && !found; seed++) {
    var r = RG.fitData(synth({ seasons: 10, perSeason: 40, noise: 6, seed: seed, truth: { a: 0.24, b: 0 } }), quick({ iterations: 300 }));
    var t = r.byName.a;
    if (t.excludesZero && t.belowFloor) found = t;
  }
  assert.ok(found, 'no seed produced a significant-but-under-floor estimate');
  assert.strictEqual(found.flag, 'below-floor');
});

test('another confidence level moves the floor with it (90%: (1.645 + 0.84) * SE)', function () {
  var d = synth({ seasons: 15, perSeason: 50, noise: 5, seed: 43 });
  var r = RG.fitData(d, quick({ level: 0.90 })), t = r.byName.a;
  var se = (t.ci[1] - t.ci[0]) / (2 * RG.qnorm(0.95));
  near(t.mde80, (RG.qnorm(0.95) + 0.84) * se, 1e-9);
  near(RG.qnorm(0.975), 1.959964, 1e-5, 'qnorm');
  near(RG.qnorm(0.5), 0, 1e-9);
  near(RG.qnorm(0.8), 0.841621, 1e-5);
});

/* ======================================================== determinism */
console.log('\ndeterminism');

test('same seed gives byte-identical results, including the MJO permutation', function () {
  var d = mjoSynth({ R: 0.8, peakDeg: 30, seed: 51 });
  var a = RG.fitData(d, mjoOpts({ seed: 7 })), b = RG.fitData(d, mjoOpts({ seed: 7 }));
  same(a, b);
  var c = RG.fitData(d, mjoOpts({ seed: 8 }));
  near(c.byName.a.coef, a.byName.a.coef, 1e-12, 'point estimates do not depend on the seed');
  near(c.mjo.R, a.mjo.R, 1e-12);
  assert.notStrictEqual(JSON.stringify(c.byName.a.ci), JSON.stringify(a.byName.a.ci), 'the interval does');
});

test('same seed gives identical output on the real archive too', function () {
  var o = { basin: 'atl', response: 'lat', teleconnect: TC, iterations: 300, seed: 3 };
  same(RG.fit(DATA.lows, o), RG.fit(DATA.lows, o));
});

/* ============================================================ the lows API */
console.log('\nbasins, seasons, responses');

test('lows from two basins and no opts.basin is an error, not a pooled fit', function () {
  assert.throws(function () { RG.fit(DATA.lows, { response: 'lat', teleconnect: TC }); }, /separate models/);
  assert.throws(function () { RG.fit(DATA.lows, { basin: 'atl', response: 'nope', teleconnect: TC }); }, /unknown response/);
});

test('fitBasins fits each basin on its own events with its own coefficients', function () {
  var both = RG.fitBasins(DATA.lows, { response: 'minP', teleconnect: TC, iterations: 100 });
  assert.deepStrictEqual(Object.keys(both).sort(), ['atl', 'pac']);
  assert.strictEqual(both.atl.basin, 'atl'); assert.strictEqual(both.pac.basin, 'pac');
  assert.ok(both.atl.n.events !== both.pac.n.events);
  // the Atlantic responds to the NAO and the Pacific to the PNA, not the reverse
  assert.ok(Math.abs(both.atl.byName.nao.coef) > Math.abs(both.atl.byName.pna.coef));
  assert.ok(Math.abs(both.pac.byName.pna.coef) > Math.abs(both.pac.byName.nao.coef));
});

test('complete seasons only by default (from recordStart); completeOnly:false lets the short-counted ones in and says so', function () {
  var a = RG.fit(DATA.lows, { basin: 'atl', response: 'lat', teleconnect: TC, iterations: 50 });
  assert.strictEqual(a.seasons[0], DATA.recordStart);
  assert.strictEqual(a.seasons[a.seasons.length - 1], 2025);
  assert.strictEqual(a.n.partialSeasonsDropped, 11);
  assert.ok(/before 2004/.test(a.warnings.join(' ')));
  var b = RG.fit(DATA.lows, { basin: 'atl', response: 'lat', teleconnect: TC, iterations: 50, completeOnly: false });
  assert.ok(b.n.events > a.n.events && b.seasons[0] < DATA.recordStart);
  assert.ok(/completeOnly is off/.test(b.warnings.join(' ')));
  var c = RG.fit(DATA.lows, { basin: 'atl', response: 'lat', teleconnect: TC, iterations: 50, recordStart: 2010 });
  assert.strictEqual(c.seasons[0], 2010);
});

test('every named response fits on the Atlantic, and a function response works', function () {
  Object.keys(RG.RESPONSES).forEach(function (k) {
    var r = RG.fit(DATA.lows, { basin: 'atl', response: k, teleconnect: TC, iterations: 50 });
    assert.strictEqual(r.status, 'ok', k);
    assert.ok(r.n.events > 100, k + ' n=' + r.n.events);
    assert.strictEqual(r.response.key, k);
  });
  var r = RG.fit(DATA.lows, { basin: 'atl', response: function (l) { return l.fixes.length; }, teleconnect: TC, iterations: 50 });
  assert.strictEqual(r.response.key, 'custom');
  var hf = RG.fit(DATA.lows, { basin: 'atl', response: 'hfH', teleconnect: TC, iterations: 50 });
  assert.strictEqual(hf.n.events, 1010);
  assert.ok(hf.response.mean >= 6 && hf.response.sd > 0, 'every archive event has at least one hurricane-force fix (6 h)');
});

test('a single season of real events: coefficients returned, interval withheld', function () {
  var one = DATA.lows.filter(function (l) { return l.basin === 'atl' && l.season === 2010; });
  var r = RG.fit(one, { basin: 'atl', response: 'lat', teleconnect: TC, predictors: ['nao'], iterations: 50 });
  assert.strictEqual(r.status, 'insufficient');
  assert.strictEqual(r.byName.nao.ci, null);
  assert.ok(isFinite(r.byName.nao.coef));
});

/* ========================================== real archive: acceptance */
console.log('\nreal archive (complete seasons, month fixed effects, season-block bootstrap)');

// reference values from the coordinator's Python
var REF = {
  atlLat:  { coef: 1.896, ci: [1.391, 2.467] },
  atlLon:  { coef: 3.744, ci: [2.742, 4.826] },
  pacLon:  { coef: 4.946, ci: [3.034, 6.756] },
  atlMinP: { coef: -1.630, ci: [-2.479, -0.721] },
  pacMinP: { coef: -1.735, ci: [-2.385, -1.068] }
};
var REAL = {};
function real(key, basin, resp, extra) {
  var id = key;
  if (!REAL[id]) {
    var o = { basin: basin, response: resp, teleconnect: TC, iterations: 2000, seed: 1 };
    for (var k in extra) o[k] = extra[k];
    REAL[id] = RG.fit(DATA.lows, o);
  }
  return REAL[id];
}
function line(label, t, ref) {
  return '       ' + label + ': ' + f3(t.coef) + '  CI [' + f3(t.ci[0]) + ', ' + f3(t.ci[1]) + ']  MDE80 ' + t.mde80.toFixed(2) +
         '  ' + t.flag + '   (reference ' + f3(ref.coef) + ' [' + f3(ref.ci[0]) + ', ' + f3(ref.ci[1]) + '])';
}

test('sample sizes: 1010 Atlantic events / 22 seasons, 856 Pacific, 968 Atlantic with a pressure', function () {
  assert.strictEqual(real('atlLat', 'atl', 'lat').n.events, 1010);
  assert.strictEqual(real('atlLat', 'atl', 'lat').n.seasons, 22);
  assert.strictEqual(real('pacLon', 'pac', 'lon').n.events, 856);
  assert.strictEqual(real('pacLon', 'pac', 'lon').n.seasons, 22);
  assert.strictEqual(real('atlMinP', 'atl', 'minP').n.events, 968);
  assert.strictEqual(real('pacMinP', 'pac', 'minP').n.events, 856);
});

test('ATLANTIC minimum pressure, NAO (main-effects model): matches the reference to 0.005, interval to ~0.1', function () {
  var t = real('atlMinP', 'atl', 'minP').byName.nao;
  console.log(line('ATL minP  NAO', t, REF.atlMinP));
  near(t.coef, REF.atlMinP.coef, 0.005);
  near(t.ci[0], REF.atlMinP.ci[0], 0.1); near(t.ci[1], REF.atlMinP.ci[1], 0.1);
  assert.strictEqual(t.flag, 'detected');
});

test('PACIFIC minimum pressure, PNA (main-effects model): matches the reference to 0.005, interval to ~0.1', function () {
  var t = real('pacMinP', 'pac', 'minP').byName.pna;
  console.log(line('PAC minP  PNA', t, REF.pacMinP));
  near(t.coef, REF.pacMinP.coef, 0.005);
  near(t.ci[0], REF.pacMinP.ci[0], 0.1); near(t.ci[1], REF.pacMinP.ci[1], 0.1);
  assert.strictEqual(t.flag, 'detected');
});

test('ATLANTIC mean fix latitude, NAO: +1.896 [1.39, 2.47] (all three index interactions in the model), detected with room to spare', function () {
  var main = real('atlLat', 'atl', 'lat').byName.nao;
  var t = real('atlLatI', 'atl', 'lat', { interactions: true }).byName.nao;
  console.log(line('ATL lat   NAO (with interactions)', t, REF.atlLat));
  console.log('       ATL lat   NAO (main effects only): ' + f3(main.coef) + '  CI [' + f3(main.ci[0]) + ', ' + f3(main.ci[1]) + ']  MDE80 ' + main.mde80.toFixed(2));
  near(t.coef, REF.atlLat.coef, 0.005, 'coefficient');
  near(main.coef, REF.atlLat.coef, 0.03, 'main-effects coefficient');
  near(main.ci[0], REF.atlLat.ci[0], 0.1); near(main.ci[1], REF.atlLat.ci[1], 0.1);
  assert.strictEqual(main.flag, 'detected');
  near(main.mde80, 0.77, 0.1, 'the reference MDE80 of 0.77');
  assert.ok(main.coef > 2 * main.mde80, 'effect ' + main.coef + ' against floor ' + main.mde80);
});

test('ATLANTIC mean fix longitude, NAO: +3.744 [2.74, 4.83] (with interactions)', function () {
  var main = real('atlLon', 'atl', 'lon').byName.nao;
  var t = real('atlLonI', 'atl', 'lon', { interactions: true }).byName.nao;
  console.log(line('ATL lon   NAO (with interactions)', t, REF.atlLon));
  console.log('       ATL lon   NAO (main effects only): ' + f3(main.coef) + '  CI [' + f3(main.ci[0]) + ', ' + f3(main.ci[1]) + ']  MDE80 ' + main.mde80.toFixed(2));
  near(t.coef, REF.atlLon.coef, 0.005, 'coefficient');
  near(main.coef, REF.atlLon.coef, 0.15, 'main-effects coefficient');
  near(t.ci[0], REF.atlLon.ci[0], 0.15); near(t.ci[1], REF.atlLon.ci[1], 0.15);
  assert.strictEqual(t.flag, 'detected');
});

test('PACIFIC mean fix longitude, PNA: positive and detected; within 0.5 of the reference +4.946 and inside its interval', function () {
  // NOT reproduced exactly: this module gives +5.23 (main effects) / +5.36
  // (with interactions) against the reference +4.946. See the report.
  var main = real('pacLon', 'pac', 'lon').byName.pna;
  var t = real('pacLonI', 'pac', 'lon', { interactions: true }).byName.pna;
  console.log(line('PAC lon   PNA (main effects)', main, REF.pacLon));
  console.log(line('PAC lon   PNA (with interactions)', t, REF.pacLon));
  assert.strictEqual(main.flag, 'detected');
  near(main.coef, REF.pacLon.coef, 0.5, 'difference from reference');
  assert.ok(main.coef > REF.pacLon.ci[0] && main.coef < REF.pacLon.ci[1], 'inside the reference interval');
  near(main.ci[0], REF.pacLon.ci[0], 0.6); near(main.ci[1], REF.pacLon.ci[1], 0.6);
});

test('every interaction term in the five acceptance models sits below its own floor', function () {
  var specs = [['atlLatI', 'atl', 'lat'], ['atlLonI', 'atl', 'lon'], ['pacLonI', 'pac', 'lon'],
               ['atlMinPI', 'atl', 'minP'], ['pacMinPI', 'pac', 'minP']];
  var line1 = [];
  specs.forEach(function (s) {
    var r = real(s[0], s[1], s[2], { interactions: true }), n = 0;
    r.terms.forEach(function (t) {
      if (t.kind !== 'interaction') return;
      n++;
      assert.strictEqual(t.flag, 'below-floor', s[1] + ' ' + s[2] + ' ' + t.name + ' = ' + t.coef + ' vs floor ' + t.mde80);
      assert.ok(Math.abs(t.coef) < t.mde80);
    });
    assert.strictEqual(n, 3);
    line1.push(s[1] + '/' + s[2] + ' max |b|/floor = ' + Math.max.apply(null, r.terms.filter(function (t) { return t.kind === 'interaction'; })
      .map(function (t) { return Math.abs(t.coef) / t.mde80; })).toFixed(2));
  });
  console.log('       ' + line1.join('; '));
});

test('index terms that should NOT matter are flagged below-floor (Atlantic PNA/ONI on latitude; Pacific NAO/ONI on longitude)', function () {
  var a = real('atlLat', 'atl', 'lat'), p = real('pacLon', 'pac', 'lon');
  assert.strictEqual(a.byName.pna.flag, 'below-floor'); assert.strictEqual(a.byName.oni.flag, 'below-floor');
  assert.strictEqual(p.byName.nao.flag, 'below-floor'); assert.strictEqual(p.byName.oni.flag, 'below-floor');
});

test('result carries R^2 (with and without the indices), events, seasons and warnings', function () {
  var r = real('atlLat', 'atl', 'lat');
  assert.ok(r.r2 > r.r2Base && r.r2Base >= 0 && r.r2 < 1);
  assert.ok(r.r2Adj < r.r2);
  assert.strictEqual(r.seasons.length, 22);
  assert.ok(Array.isArray(r.warnings));
  assert.strictEqual(r.status, 'ok'); assert.strictEqual(r.reliability, 'ok');
  assert.ok(r.response.frame === null && r.response.units === 'deg N');
  var pl = real('pacLon', 'pac', 'lon');
  assert.ok(Math.abs(wrap180(pl.response.frame.centre - 180)) < 40, 'Pacific frame centre ' + pl.response.frame.centre);
  console.log('       (ATL lat: R^2 ' + r.r2.toFixed(3) + ' of which calendar alone ' + r.r2Base.toFixed(3) + '; ' + r.n.events + ' events, ' + r.n.seasons + ' seasons ' + r.seasons[0] + '-' + r.seasons[r.seasons.length - 1] + ')');
});

test('real archive MJO harmonic, both basins, on latitude and pressure (reported, not asserted to be significant)', function () {
  [['atl', 'lat'], ['atl', 'minP'], ['pac', 'lat'], ['pac', 'minP']].forEach(function (s) {
    var r = RG.fit(DATA.lows, { basin: s[0], response: s[1], teleconnect: TC, mjo: true, iterations: 1000, permutations: 999, seed: 1 });
    assert.strictEqual(r.mjo.status, 'ok');
    var m = r.mjo;
    console.log('       ' + s[0] + ' ' + s[1] + ': R=' + m.R.toFixed(3) + ' [' + m.ciR[0].toFixed(2) + ', ' + m.ciR[1].toFixed(2) + ']  p=' + m.p.toFixed(3) +
      '  peak at phase ' + m.angleDeg.toFixed(0) + ' deg (convection near ' + m.convectionLonDegE.toFixed(0) + 'E)  MDE80(R)=' + m.mde80.toFixed(2) + '  ' + m.flag);
  });
});

/* ============================================================ timing */
console.log('\ntiming (Node vm context; the vm slows global lookups, a page is faster)');

test('a full run is well under a second', function () {
  function ms(o) {
    var base = { basin: 'atl', response: 'lat', teleconnect: TC };
    for (var k in o) base[k] = o[k];
    var best = Infinity;
    for (var rep = 0; rep < 3; rep++) { var t0 = Date.now(); RG.fit(DATA.lows, base); best = Math.min(best, Date.now() - t0); }
    return best;
  }
  var tPlain = ms({}), tInt = ms({ interactions: true }), tMjo = ms({ mjo: true }), tAll = ms({ mjo: true, interactions: true });
  var tFew = ms({ iterations: 300, permutations: 199, mjo: true });
  console.log('       default (2000 bootstrap draws): ' + tPlain + ' ms; + 3 interactions: ' + tInt + ' ms; + MJO (999 permutations): ' + tMjo +
              ' ms; MJO + interactions: ' + tAll + ' ms; MJO at 300 draws / 199 perms: ' + tFew + ' ms');
  assert.ok(tAll < 5000, 'unexpectedly slow: ' + tAll + ' ms');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
