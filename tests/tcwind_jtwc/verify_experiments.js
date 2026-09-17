#!/usr/bin/env node
/**
 * Checks on the two EXPERIMENTAL extratropical-transition terms in
 * Vortex.html - the eq. (5)/(6) prior and the wavenumber-2 elongation -
 * which ?page=lab exists to measure.
 *
 *   node tests/tcwind_jtwc/verify_experiments.js
 *
 * These terms live only in the JavaScript.  GFE/procedures/TCWind_JTWC.py
 * has no counterpart and deliberately so: the Python is the reference
 * implementation, nothing default-on may exist here first, and the point of
 * the lab is to find out whether either term earns the port.  That makes
 * ONE invariant load-bearing above all others:
 *
 *     with no opts, or with empty or zeroed opts, the field must be exactly
 *     what it was before these terms existed.
 *
 * compare_py_js.py cannot catch a violation of that on its own - it has no
 * knowledge of opts, and its 0.5 kt tolerance would swallow a small
 * systematic shift anyway.  So the first group below compares BIT PATTERNS,
 * not values within a tolerance.
 *
 * Exits 0 if everything passes, 1 otherwise.  No dependencies.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const VORTEX = path.join(__dirname, '..', '..', 'web', 'TCWind_JTWC', 'Vortex.html');

function loadVortex(file) {
  const html = fs.readFileSync(file, 'utf8');
  const m = /<script>([\s\S]*?)<\/script>/.exec(html);
  if (!m) throw new Error('no <script> block in ' + path.basename(file));
  const ctx = { window: {}, console, Math, Number, String, Object, Array, JSON,
                isNaN, parseInt, parseFloat, Infinity, NaN };
  vm.createContext(ctx);
  vm.runInContext(m[1], ctx, { filename: file });
  return ctx.window;
}

const V = loadVortex(VORTEX);

let failures = 0;
function group(name) { console.log('\n' + name); }
function ok(cond, msg) {
  console.log((cond ? '  pass  ' : '  FAIL  ') + msg);
  if (!cond) failures++;
}
function info(msg) { console.log('        ' + msg); }

/** Exact bit pattern of a double, so 0 and -0, and two NaNs, compare as the
 *  same thing they are.  A tolerance would defeat the purpose here. */
function bits(x) {
  if (typeof x !== 'number') return typeof x + ':' + String(x);
  if (Number.isNaN(x)) return 'NaN';
  const b = Buffer.alloc(8);
  b.writeDoubleLE(x);
  return b.toString('hex');
}

function quads(ne, se, sw, nw) { return { NE: ne, SE: se, SW: sw, NW: nw }; }

// A spread chosen to reach every freeParams branch, both hemispheres, zero
// motion, and the fast-and-weakening case where Vm - a drops below the
// thresholds the bulletin reports.
const SNAPS = [
  { name: 'cat3, R34+R50+R64 (6+ targets)', lat: 22.0, lon: -60.0, vmax: 105,
    motionDir: 310, motionSpd: 12,
    radii: { 34: quads(180, 150, 110, 140), 50: quads(90, 80, 55, 70),
             64: quads(50, 45, 30, 40) } },
  { name: 'TS, R34 all quadrants (4 targets)', lat: 18.5, lon: 132.0, vmax: 45,
    motionDir: 285, motionSpd: 10, radii: { 34: quads(90, 80, 60, 70) } },
  { name: 'TS, R34 two quadrants (2 targets)', lat: 21.3, lon: 116.8, vmax: 40,
    motionDir: 300, motionSpd: 14, radii: { 34: quads(75, 0, 0, 60) } },
  { name: 'no radii at all (climatology only)', lat: 14.0, lon: 145.0, vmax: 30,
    motionDir: 270, motionSpd: 8, radii: {} },
  { name: 'southern hemisphere', lat: -17.0, lon: 95.0, vmax: 85,
    motionDir: 240, motionSpd: 11,
    radii: { 34: quads(140, 120, 100, 130), 50: quads(70, 60, 45, 65) } },
  { name: 'stationary (no asymmetry)', lat: 30.0, lon: -75.0, vmax: 65,
    motionDir: null, motionSpd: 0,
    radii: { 34: quads(150, 130, 90, 110), 50: quads(60, 55, 35, 45) } },
  { name: 'fast and marginal', lat: 41.0, lon: -52.0, vmax: 50,
    motionDir: 45, motionSpd: 33, radii: { 34: quads(240, 200, 150, 210) } },
  { name: 'high-latitude hurricane', lat: 46.5, lon: -48.0, vmax: 70,
    motionDir: 30, motionSpd: 28,
    radii: { 34: quads(300, 260, 180, 240), 50: quads(120, 100, 70, 90) } }
];

const BEARINGS = [];
for (let a = 0; a < 360; a += 7) BEARINGS.push(a);
const RANGES = [3, 12, 30, 55, 90, 140, 210, 300, 420, 600];
const FIT_KEYS = ['rm', 'ri', 'x1', 'x2', 'ax', 'ay', 'a', 'n', 'freeParams', 'rms'];
const AT_KEYS = ['mag', 'dir', 'r', 'r34', 'az', 'u', 'v'];

function ringPoint(snap, azDeg, distNm) {
  const dr = distNm / 60.0, azr = azDeg * Math.PI / 180;
  return [snap.lat + dr * Math.cos(azr),
          snap.lon + dr * Math.sin(azr) / Math.cos(snap.lat * Math.PI / 180)];
}

/** Every value the two option sets produce, as bit patterns, in one flat
 *  list so the comparison cannot silently skip a field. */
function fingerprint(snap, opts) {
  const out = [];
  const fit = opts === undefined ? V.fitGTCM(snap) : V.fitGTCM(snap, opts);
  for (const k of FIT_KEYS) out.push('fit.' + k + '=' + bits(fit[k]));
  const fld = opts === undefined ? V.vortexFieldGTCM(snap)
                                 : V.vortexFieldGTCM(snap, opts);
  for (const az of BEARINGS) out.push('r34@' + az + '=' + bits(fld.r34At(az)));
  for (const az of BEARINGS) {
    for (const d of RANGES) {
      const p = ringPoint(snap, az, d);
      const a = fld.at(p[0], p[1]);
      for (const k of AT_KEYS) out.push('at' + az + ',' + d + '.' + k + '=' + bits(a[k]));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
group('1. the default path is untouched (bit patterns, not tolerances)');
// Three spellings of "no experiment": absent, empty, and explicitly zeroed.
// The third is the one that catches an unguarded `x * opts.rmScale` creeping
// in, because 0 and undefined take different branches.
{
  const VARIANTS = [
    ['opts omitted vs {}', {}],
    ['opts omitted vs all-zero opts',
     { rmScale: 0, xShift: 0, fitE: false, wn2: { e: 0, phi: null, phiOffset: 0 } }]
  ];
  let compared = 0, diffs = 0;
  for (const snap of SNAPS) {
    const ref = fingerprint(snap, undefined);
    for (const [label, opts] of VARIANTS) {
      const got = fingerprint(snap, opts);
      for (let i = 0; i < ref.length; i++) {
        compared++;
        if (ref[i] !== got[i]) {
          diffs++;
          if (diffs <= 10) {
            info('DIFF ' + snap.name + ' [' + label + '] ' + ref[i] + ' vs ' + got[i]);
          }
        }
      }
    }
  }
  info(compared.toLocaleString('en-US') + ' values compared across ' +
       SNAPS.length + ' storm-times');
  ok(diffs === 0, 'no-opts, {} and zeroed opts are bit-for-bit identical');
}

// ---------------------------------------------------------------------------
group('2. scale covariance - the identity the wn2 term is built on');
// gtcmProfile(r/s, rm, ri) === gtcmProfile(r, rm*s, ri*s).  If this ever
// stops holding, elongation is no longer a coordinate transform and the
// shared radial profile array in vortexFieldGTCM() is wrong.
{
  let worst = 0, pairs = 0;
  for (const s of [0.55, 0.7, 0.85, 1.0, 1.15, 1.3, 1.45]) {
    for (const r of [1, 5, 17, 33, 48, 90, 175, 400, 880]) {
      const A = V.gtcmProfile(r / s, 95, 8, 30, 95, 0.55, 0.40);
      const B = V.gtcmProfile(r, 95, 8, 30 * s, 95 * s, 0.55, 0.40);
      worst = Math.max(worst, Math.abs(A - B));
      pairs++;
    }
  }
  info('max |difference| over ' + pairs + ' (s, r) pairs: ' + worst.toExponential(3) + ' kt');
  ok(worst < 1e-9, 'the two spellings agree to floating-point noise');
}

// ---------------------------------------------------------------------------
group('3. rThresholdAt generalises r34At without moving it');
{
  const snap = SNAPS[0];
  const fld = V.vortexFieldGTCM(snap);
  let same = true;
  for (let az = 0; az < 360; az += 3) {
    if (bits(fld.rThresholdAt(az, 34.0)) !== bits(fld.r34At(az))) same = false;
  }
  ok(same, 'rThresholdAt(az, 34) is bit-identical to r34At(az) on 120 bearings');

  let ordered = true;
  for (let az = 0; az < 360; az += 3) {
    const r34 = fld.rThresholdAt(az, 34, true);
    const r50 = fld.rThresholdAt(az, 50, true);
    const r64 = fld.rThresholdAt(az, 64, true);
    if (!Number.isNaN(r50) && !(r50 < r34)) ordered = false;
    if (!Number.isNaN(r64) && !Number.isNaN(r50) && !(r64 < r50)) ordered = false;
  }
  ok(ordered, 'R64 < R50 < R34 wherever each is reached');
}

// ---------------------------------------------------------------------------
group('4. strict mode reports unreachable thresholds instead of inventing one');
// The taper needs a radius even when the field never reaches the threshold,
// and both ports fall back to rm*3 for it.  Scoring that fallback as though
// it were a radius manufactures agreement out of nothing, so a caller
// measuring residuals has to be able to tell the two apart.
{
  const snap = { lat: 42.0, lon: -55.0, vmax: 65, motionDir: 40, motionSpd: 26,
                 radii: { 34: quads(260, 220, 160, 210), 50: quads(110, 90, 60, 80) } };
  const fld = V.vortexFieldGTCM(snap);
  const peak = snap.vmax - fld.fit.a;
  let miss64 = 0, miss50 = 0, n = 0;
  for (let az = 0; az < 360; az += 5) {
    n++;
    if (Number.isNaN(fld.rThresholdAt(az, 64, true))) miss64++;
    if (Number.isNaN(fld.rThresholdAt(az, 50, true))) miss50++;
  }
  info('Vmax ' + snap.vmax + ' kt at ' + snap.motionSpd + ' kt of motion: a = ' +
       fld.fit.a.toFixed(1) + ' kt, so the symmetric peak is Vm - a = ' +
       peak.toFixed(1) + ' kt');
  info('bearings with no 50 kt crossing: ' + miss50 + '/' + n +
       ';  no 64 kt crossing: ' + miss64 + '/' + n);
  ok(peak < 64 && miss64 === n,
     'a 65 kt storm moving 26 kt has NO 64 kt radius at any azimuth');
  ok(!Number.isNaN(fld.rThresholdAt(0, 64, false)),
     'non-strict still returns the rm*3 fallback, so r34At keeps working');
}

// ---------------------------------------------------------------------------
group('5. the ET prior has leverage exactly where the bulletin runs thin');
// This is the design, not an accident.  With R34, R50 and R64 all reported,
// freeParams is 3 and the rm bounds are absolute, so weighted least squares
// answers to the radii and the prior washes out.  As a system transitions its
// R64 goes to zero, then its R50; freeParams falls to 2 and then 1, and at 1
// the exponent IS the climatological value.  The prior is not a nudge to the
// answer during transition, it is most of the answer.
{
  const eps = V.etFractionFromNature('ET');
  const prior = V.gtcmEtPrior(eps, 2.0, 0.25);
  info('NATURE=ET -> eps ' + eps.toFixed(2) + ',  kappa 2.0 / beta 0.25 -> rmScale ' +
       prior.rmScale.toFixed(3) + ', xShift ' + prior.xShift.toFixed(4));
  const opts = { rmScale: prior.rmScale, xShift: prior.xShift };
  const BASE = { lat: 42, lon: -55, vmax: 65, motionDir: 40, motionSpd: 26 };
  const LADDER = [
    ['R34+R50 (6 targets)', { 34: quads(260, 220, 160, 210), 50: quads(110, 90, 60, 80) }],
    ['R34 only (4 targets)', { 34: quads(260, 220, 160, 210) }],
    ['R34 x2   (2 targets)', { 34: quads(260, 0, 0, 210) }]
  ];
  function meanR34(fld) {
    let t = 0, n = 0;
    for (let az = 0; az < 360; az += 5) { t += fld.r34At(az); n++; }
    return t / n;
  }
  info('bulletin              free        rm nm            x2        mean R34 nm');
  const ratios = [];
  for (const [label, radii] of LADDER) {
    const snap = Object.assign({}, BASE, { radii: radii });
    const b = V.vortexFieldGTCM(snap);
    const e = V.vortexFieldGTCM(snap, opts);
    const rb = meanR34(b), re = meanR34(e);
    ratios.push(re / rb);
    info(label.padEnd(22) + String(b.fit.freeParams).padEnd(8) +
         (b.fit.rm.toFixed(1) + ' -> ' + e.fit.rm.toFixed(1)).padEnd(18) +
         (b.fit.x2.toFixed(3) + ' -> ' + e.fit.x2.toFixed(3)).padEnd(18) +
         rb.toFixed(1) + ' -> ' + re.toFixed(1) +
         '  (x' + (re / rb).toFixed(2) + ')');
  }
  ok(Math.abs(ratios[0] - 1) < 0.02,
     'a fully reported bulletin is essentially unmoved (freeParams 3)');
  ok(ratios[2] > 1.2,
     'a two-quadrant bulletin expands substantially (freeParams 1)');
  ok(ratios[2] > ratios[0],
     'leverage increases as the reported radii thin out');
}

// ---------------------------------------------------------------------------
group('6. the wavenumber-2 term is a wavenumber 2, oriented as documented');
{
  const snap = { lat: 42, lon: -55, vmax: 65, motionDir: 40, motionSpd: 26,
                 radii: { 34: quads(260, 220, 160, 210), 50: quads(110, 90, 60, 80) } };
  const e = 0.30;
  const fld = V.vortexFieldGTCM(snap, { wn2: { e: e } });
  ok(fld.fit.phi === snap.motionDir,
     'phi falls back to the motion vector when not given (' + snap.motionDir + ' deg)');
  ok(Math.abs(fld.wn2ScaleAt(snap.motionDir) - (1 + e)) < 1e-12 &&
     Math.abs(fld.wn2ScaleAt(snap.motionDir + 90) - (1 - e)) < 1e-12,
     'the scale is 1+e on the long axis and 1-e across it');
  let periodic = true;
  for (let az = 0; az < 180; az += 11) {
    if (Math.abs(fld.wn2ScaleAt(az) - fld.wn2ScaleAt(az + 180)) > 1e-12) periodic = false;
  }
  ok(periodic, 'period is 180 deg - a wavenumber 2, not a second wavenumber 1');

  const along = (fld.r34At(snap.motionDir) + fld.r34At(snap.motionDir + 180)) / 2;
  const across = (fld.r34At(snap.motionDir + 90) + fld.r34At(snap.motionDir + 270)) / 2;
  info('R34 along the axis ' + along.toFixed(1) + ' nm, across it ' +
       across.toFixed(1) + ' nm  (ratio ' + (along / across).toFixed(2) + ')');
  ok(along > across, 'the footprint elongates along phi, not across it');

  // Signed e must mirror the shape rather than do nothing.
  const neg = V.vortexFieldGTCM(snap, { wn2: { e: -e } });
  ok(Math.abs(neg.wn2ScaleAt(snap.motionDir) - (1 - e)) < 1e-12,
     'negative e rotates the long axis 90 deg rather than being clamped away');

  // An explicit phi must win over the motion vector, and phiOffset must add.
  ok(V.fitGTCM(snap, { wn2: { e: e, phi: 137 } }).phi === 137, 'explicit phi is used as given');
  ok(V.fitGTCM(snap, { wn2: { e: e, phiOffset: 90 } }).phi === snap.motionDir + 90,
     'phiOffset shifts whichever axis was chosen');
}

// ---------------------------------------------------------------------------
group('7. guards on the tunables');
{
  ok(Math.abs(V.gtcmWn2Scale(0, 9.0, 0) - (1 + V.GTCM_WN2_E_MAX)) < 1e-12 &&
     Math.abs(V.gtcmWn2Scale(0, -9.0, 0) - (1 - V.GTCM_WN2_E_MAX)) < 1e-12,
     '|e| is clamped to GTCM_WN2_E_MAX, so the short axis cannot fold');
  ok(V.gtcmEtPrior(1.0, 99, 99).rmScale === 1 + (V.GTCM_ET_KAPPA_MAX - 1) &&
     V.gtcmEtPrior(1.0, 99, 99).xShift === -V.GTCM_ET_BETA_MAX,
     'kappa and beta are clamped to their ceilings');
  ok(V.gtcmEtPrior(-5, 2, 0.2).eps === 0 && V.gtcmEtPrior(9, 2, 0.2).eps === 1,
     'eps is clamped to [0, 1]');
  ok(V.gtcmEtPrior(0.75, 1.0, 0.0).rmScale === 1.0 &&
     V.gtcmEtPrior(0.75, 1.0, 0.0).xShift === 0.0,
     'kappa 1 / beta 0 is the identity prior at any eps');
  ok(V.etFractionFromNature('TS') === 0 && V.etFractionFromNature('DS') === 0 &&
     V.etFractionFromNature('') === 0 && V.etFractionFromNature(null) === 0 &&
     V.etFractionFromNature('NOT_A_FLAG') === 0,
     'tropical, empty and unrecognised NATURE all give eps 0');
  ok(V.etFractionFromNature('ET') === 1 - V.CONF_SUBTROPICAL &&
     V.etFractionFromNature('SS') === 1 - V.CONF_SUBTROPICAL &&
     V.etFractionFromNature('MX') === 1 - V.CONF_BECOMING,
     'ET/SS/MX map onto 1 - the parser CONF_* levels, not a second scale');
}

// ---------------------------------------------------------------------------
group('8. fitting e is gated on the data supporting it');
{
  const rich = { lat: 42, lon: -55, vmax: 65, motionDir: 40, motionSpd: 26,
                 radii: { 34: quads(260, 220, 160, 210), 50: quads(110, 90, 60, 80) } };
  const base = V.fitGTCM(rich);
  const fitted = V.fitGTCM(rich, { wn2: { e: 0.15 }, fitE: true });
  info('freeParams ' + base.freeParams + ': e 0.150 -> ' + fitted.e.toFixed(3) +
       ',  weighted RMS ' + base.rms.toFixed(3) + ' -> ' + fitted.rms.toFixed(3) + ' kt');
  ok(fitted.eFitted === true, 'fitE engages at freeParams 3');
  ok(fitted.rms <= base.rms + 1e-9,
     'releasing a parameter cannot worsen the weighted fit');
  ok(Math.abs(fitted.e) <= V.GTCM_WN2_E_MAX + 1e-12, 'the fitted e respects the ceiling');

  const thin = { lat: 40, lon: -50, vmax: 45, motionDir: 60, motionSpd: 20,
                 radii: { 34: quads(120, 0, 0, 90) } };
  const thinFit = V.fitGTCM(thin, { wn2: { e: 0.2 }, fitE: true });
  ok(thinFit.eFitted === false,
     'and refuses on a two-target bulletin - a fourth unknown on two ' +
     'constraints is the wedge failure with more arithmetic');
  ok(thinFit.e === 0.2, 'the prescribed e is still applied there, just not fitted');
}

console.log('\n' + (failures
  ? failures + ' check(s) FAILED'
  : 'all checks passed'));
process.exit(failures ? 1 : 0);
