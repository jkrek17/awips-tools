/* Regression of storm-track properties on climate indices: "how far does the
   mean latitude / longitude / depth of an event move per standard deviation
   of the NAO, PNA or ONI, and is this archive big enough to see an effect of
   that size at all?" No DOM, no canvas, no network. Built on the same decoded
   lows as HF.composite (util.js: {season, start, month, minP, hfH,
   fixes:[{lat, lon, ...}], ...}) and on HF.teleconnect's attribution for the
   index values; this file never re-derives which day or which ONI season an
   event belongs to. Plain script, ES5 style, attaches to window.HF.

     var tc  = HF.teleconnect.create({ archive: DATA });
     var r   = HF.regress.fit(DATA.lows, {
       basin: 'atl',                 // REQUIRED: one model per basin (see 3)
       response: 'lat',              // 'lat' | 'lon' | 'minP' | 'hfH' | ... | function(low)
       teleconnect: tc,              // the engine; built for you if omitted
       seed: 1                       // reproducible; same seed, same answer
     });
     r.status        // 'ok' | 'insufficient' | 'empty'
     r.reliability   // 'ok' | 'low' | 'none' (read this before drawing anything)
     r.n             // {events, seasons, input, dropped, params, df}
     r.terms[i]      // {name, coef, ci, se, mde80, flag, excludesZero, ...}
     r.byName.nao    // the same objects by name
     r.mjo           // the harmonic pair's joint test, or {status:'omitted', reason}
     r.r2, r.r2Base  // R^2 with and without the climate terms
     r.warnings      // strings, in the spirit of HF.composite's

     HF.regress.fitBasins(lows, opts)   // {atl: result, pac: result}, two separate fits

   WHY THIS EXISTS. HF.composite bins events by climate phase and tests a
   gridded track-density difference with FDR control. On this archive that
   returns almost nothing, because cutting a continuous index into terciles
   throws away most of its information and then spreads what is left across
   ~150 cells. A regression on the same events asks one question of one number
   (the mean latitude of the event) and finds a large, physically coherent
   NAO effect. The two answers do not contradict each other: they measure
   different things, and the regression's power comes from asking less.

   Six decisions carry the whole thing. Each is argued where it is made; this
   is the map.

   1. ONE MODEL PER BASIN (fit). Never a dummy variable.
   2. LONGITUDE IS CIRCULAR (circMeanDeg, unwrapAround). Averaged raw, a track
      from 170E to 170W is "about 0 degrees", i.e. the Atlantic.
   3. MJO PHASE IS CIRCULAR TOO (the harmonic pair, permuteMjo). It enters as
      A*cos(phi) and A*sin(phi), and the pair is tested JOINTLY.
   4. THE SEASON IS THE UNIT OF RESAMPLING (bootstrapFit). Same argument as
      composite.js, same consequence: a single season cannot be bootstrapped
      and the module says so instead of returning a zero-width interval.
   5. MONTH IS A FIXED EFFECT, ALWAYS. The track moves hundreds of km between
      October and February and the indices have their own seasonal cycle.
   6. THE MINIMUM DETECTABLE EFFECT IS REPORTED NEXT TO EVERY CONFIDENCE
      INTERVAL (finishTerm). "The interval includes zero" and "this sample
      could not have seen an effect of the size you care about" are different
      statements and a UI must be able to tell them apart.

   Partial seasons are dropped by default for the same reason composite.js
   drops them: this archive's first three seasons are short-counted (1, 22 and
   38 events against 62-115 for every complete one), not quiet, and a season
   with a quarter of its storms missing is not a season with a quarter of the
   activity. Nothing downstream can tell the two apart. */

window.HF = window.HF || {};

(function (HF) {
  'use strict';

  var DEG = Math.PI / 180;
  var imul = Math.imul;    // local alias: a global lookup per call is the slow part when run in a Node vm context

  /* ------------------------------------------------------------ options */

  var DEFAULTS = {
    // Which of HF.teleconnect's indices enter, in this order. Order matters
    // in one place only: if two columns are exactly collinear the LATER one is
    // the one dropped (see cholSkip), and index terms come after the month
    // dummies so the fixed effects are never the casualty.
    predictors: ['nao', 'pna', 'oni'],

    // false | true | [['nao', 'pna'], ...]. true means every pair of the
    // chosen predictors. An interaction is the product of two STANDARDISED
    // columns, so its coefficient reads "change in the slope on A per SD of
    // B" and is directly comparable with the main effects. Off by default:
    // with ~1,000 events and 22 seasons, a product term's minimum detectable
    // effect is typically larger than any plausible interaction, and the
    // honest report on this archive is that every one sits below its own
    // floor (ask for them, and each carries the flag that says so).
    interactions: false,

    // 'mean5' = mean of the 5 days ending on genesis day (teleconnect's
    // derived.mean5), 'daily' = the genesis day alone. mean5 is the default
    // because a single day's NAO value is noisy relative to the pattern that
    // steers a storm over its 2-4 day life, and because it is the basis the
    // composite tercile cuts use. NAO/PNA only; ONI has its own switch.
    indexBasis: 'mean5',

    // 'genesis' = the ONI season centred on the genesis month (the ocean
    // state AT the event); 'djf' = the DJF value of the event's season (a
    // season-level descriptor, which for a June event describes an ocean
    // state that had not happened yet - teleconnect.js argues why that is
    // wrong as a cause). genesis is the default for that reason.
    oniBasis: 'genesis',

    // Season-block bootstrap draws. The resampling works on per-season sums
    // of X'X and X'y (bootstrapFit), so a draw costs ~one small Cholesky and
    // 2,000 of them take tens of milliseconds, not the seconds a row-level
    // resample of 1,000 x 20 would. 2,000 puts ~50 draws beyond each end of
    // a 95% interval, enough that the endpoints do not wander with the seed.
    iterations: 2000,

    // MJO permutation draws; the smallest p it can report is 1/(B+1).
    permutations: 999,

    // The default seed is a constant, not the clock, for composite.js's
    // reason: the same events must give the same table on every visit.
    seed: 1,

    // Confidence level of the bootstrap interval AND the level the minimum
    // detectable effect is computed against (see finishTerm).
    level: 0.95,

    // Power the MDE is quoted at. 0.80 is the convention; it is what "80" in
    // MDE80 means, so it is a constant here and a field name there.
    power: 0.80,

    // Sample-size guards. minSeasons is composite.js's number. With k seasons
    // a block bootstrap has C(2k-1, k) distinct resamples: 1 for k = 1 (every
    // draw IS the data, so the interval has zero width and looks like
    // infinite precision), 126 for k = 5, 24,310 for k = 8. Below minSeasons
    // the interval is withheld.
    minSeasons: 5,
    cautionSeasons: 8,

    // Rows per estimated parameter below which the fit is flagged. 10 is the
    // usual rule of thumb; with month dummies, 4 climate terms and an
    // intercept this archive has ~60 rows per parameter, so this guards a
    // filtered subset, not the full archive.
    minRowsPerParam: 10,

    // Seasons before HF_DATA.recordStart are dropped before anything else.
    // true is the default for the reason in the header; false lets the early
    // seasons in, and says so in warnings.
    completeOnly: true,
    recordStart: null,

    // false, true, or {lag, source, phaseUnit}. See mjoAccessor. Needs
    // mjo.eofPhase / mjo.eofAmplitude in the index payload.
    mjo: false,

    // Caller-supplied fixed standardisation {nao: {mean, sd}}. Omit it and
    // each predictor is standardised by its own mean and SD over the events
    // in the fit (see standardise for why that is the default).
    scale: null
  };

  var LABELS = { nao: 'NAO', pna: 'PNA', oni: 'ONI', ao: 'AO' };

  function bad(msg) { throw new Error('HF.regress: ' + msg); }

  function label(name) {
    if (name.indexOf('*') >= 0) return name.split('*').map(label).join(' x ');
    return LABELS[name] || name.toUpperCase();
  }

  function resolveOptions(opts) {
    var o = {}, k;
    for (k in DEFAULTS) o[k] = DEFAULTS[k];
    if (opts) for (k in opts) if (opts[k] !== undefined) o[k] = opts[k];
    if (!Array.isArray(o.predictors)) bad('predictors must be an array of index names');
    var seen = {}, i;
    for (i = 0; i < o.predictors.length; i++) {
      if (typeof o.predictors[i] !== 'string' || o.predictors[i].indexOf('*') >= 0) bad('predictor names are plain strings');
      if (seen[o.predictors[i]]) bad('duplicate predictor ' + o.predictors[i]);
      seen[o.predictors[i]] = true;
    }
    if (o.indexBasis !== 'mean5' && o.indexBasis !== 'daily') bad("indexBasis must be 'mean5' or 'daily'");
    if (o.oniBasis !== 'genesis' && o.oniBasis !== 'djf') bad("oniBasis must be 'genesis' or 'djf'");
    if (!(o.level > 0 && o.level < 1)) bad('level must be in (0, 1)');
    if (!(o.power > 0 && o.power < 1)) bad('power must be in (0, 1)');
    if (!(o.iterations >= 1) || o.iterations !== Math.floor(o.iterations)) bad('iterations must be a positive integer');
    if (!(o.permutations >= 1) || o.permutations !== Math.floor(o.permutations)) bad('permutations must be a positive integer');
    if (!isFinite(o.seed)) bad('seed must be a finite number');
    if (!(o.minSeasons >= 2)) bad('minSeasons must be >= 2 (one block cannot be resampled)');
    return o;
  }

  /* --------------------------------------------------------------- PRNG */

  /** mulberry32, the same generator and the same constants as
      HF.composite.rng (composite.js has the argument for it). It is copied
      rather than borrowed so this file loads on its own; the two produce
      identical streams for one seed. */
  function makeRng(seed) {
    // Signed 32-bit state (`| 0`), the canonical form of the generator: it
    // stays in V8's small-integer representation, where the `>>> 0` form
    // allocates a heap number per call and was 5x slower in the permutation
    // loop (1M draws per run). Same output stream as composite.js's.
    var a = Math.floor(seed) | 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = imul(a ^ (a >>> 15), 1 | a);
      t = (t + imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ------------------------------------------------------ normal quantile */

  /** Inverse standard-normal CDF (Acklam's rational approximation, relative
      error < 1.2e-9). Needed only because the confidence level is a parameter:
      the conventional 95% / 80% pair is special-cased in zFor so the headline
      numbers use the textbook 1.96 and 0.84, and 2.80 = 1.96 + 0.84. */
  function qnorm(p) {
    if (!(p > 0 && p < 1)) return NaN;
    var a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    var b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01];
    var c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    var d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00];
    var pl = 0.02425, q, r;
    if (p < pl) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
             ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > 1 - pl) return -qnorm(1 - p);
    q = p - 0.5;
    r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  /** Critical z for a two-sided interval at `level`, and the z for `power`.
      Rounded to two places for the 95% / 80% pair so MDE80 = 2.80 * SE comes
      out as written everywhere it is quoted. */
  function zFor(level, power) {
    var zc = Math.abs(level - 0.95) < 1e-12 ? 1.96 : qnorm(1 - (1 - level) / 2);
    var zp = Math.abs(power - 0.80) < 1e-12 ? 0.84 : qnorm(power);
    return { zCrit: zc, zPower: zp, k: zc + zp };
  }

  /* ------------------------------------------------------- circular maths */

  function wrap180(d) { return d - 360 * Math.floor((d + 180) / 360); }
  function wrap360(d) { return d - 360 * Math.floor(d / 360); }

  /** Circular mean of angles in degrees, via the summed unit vectors. Returns
      {mean, R} where mean is in [-180, 180) and R in [0, 1] is the mean
      resultant length (1 = all identical, 0 = no preferred direction, where
      `mean` means nothing and is returned as NaN).

      This is the whole of pitfall 1. The arithmetic mean of 170E and 170W
      (+170 and -170) is 0; the circular mean is 180. A Pacific track that
      sits on the dateline, averaged in raw degrees, lands on the Greenwich
      meridian - in the Atlantic - and every event that crosses the line
      becomes an outlier in the regression. It is not a small error: with the
      archive's Pacific events it turns a +5 degree per SD NAO/PNA effect
      into a coefficient of about -41. */
  function circMeanDeg(deg) {
    var s = 0, c = 0, n = 0, i;
    for (i = 0; i < deg.length; i++) {
      var v = deg[i];
      if (typeof v !== 'number' || !isFinite(v)) continue;
      s += Math.sin(v * DEG); c += Math.cos(v * DEG); n++;
    }
    if (!n) return { mean: NaN, R: NaN, n: 0 };
    var r = Math.sqrt(s * s + c * c) / n;
    return { mean: r < 1e-9 ? NaN : Math.atan2(s, c) / DEG, R: r, n: n };
  }

  /** Express `deg` on the continuous branch centred on `centre`:
      centre + wrap180(deg - centre), so every value lies within 180 of the
      centre and nothing straddles a seam. With the centre at the Pacific
      events' own circular mean (~190E) the dateline is in the middle of the
      range, not at the edge, and "5 degrees further east" means the same
      thing on both sides of it. For the Atlantic (centre ~45W, nothing within
      100 degrees of +/-180) this is the identity, which the tests assert, so
      applying it to both basins is the same as applying it to the Pacific
      alone and needs no special case. */
  function unwrapAround(deg, centre) {
    return centre + wrap180(deg - centre);
  }

  /* ------------------------------------------------------- linear algebra */

  /** Cholesky factor of the symmetric p x p matrix A (flat, row-major),
      SKIPPING any column whose pivot is numerically zero relative to its own
      diagonal. A skipped column is exactly collinear with earlier ones (or
      all zero); it gets coefficient 0 and is reported, instead of the
      factorisation dividing by zero.

      This matters in the bootstrap, not just for bad inputs: a season-block
      resample can omit a month that only a handful of seasons have (May has
      3 events in this archive), and the month's dummy column is then all
      zeros. Skipping it is exactly right - the fit is the one that never had
      that month - where a plain Cholesky would produce NaN and poison the
      draw.

      Precision: columns are standardised or 0/1, so diagonals are O(1)..O(n)
      and 1e-8 of the diagonal is far above rounding (1e-16) and far below any
      collinearity a real pair of indices has (NAO vs AO, r ~ 0.8, leaves a
      relative pivot of ~0.35). */
  function cholSkip(A, p) {
    var L = new Float64Array(p * p), keep = new Uint8Array(p), j, k, i;
    for (j = 0; j < p; j++) {
      var d = A[j * p + j];
      for (k = 0; k < j; k++) if (keep[k]) d -= L[j * p + k] * L[j * p + k];
      if (!(d > 1e-8 * A[j * p + j]) || !(A[j * p + j] > 0)) continue;
      var ljj = Math.sqrt(d);
      L[j * p + j] = ljj;
      keep[j] = 1;
      for (i = j + 1; i < p; i++) {
        var s = A[i * p + j];
        for (k = 0; k < j; k++) if (keep[k]) s -= L[i * p + k] * L[j * p + k];
        L[i * p + j] = s / ljj;
      }
    }
    return { L: L, keep: keep, p: p };
  }

  /** Solve A x = b with a cholSkip factor; skipped columns get 0. */
  function cholSolve(f, b, out) {
    var p = f.p, L = f.L, keep = f.keep, x = out || new Float64Array(p), i, k;
    var z = new Float64Array(p);
    for (i = 0; i < p; i++) {
      if (!keep[i]) { z[i] = 0; continue; }
      var s = b[i];
      for (k = 0; k < i; k++) if (keep[k]) s -= L[i * p + k] * z[k];
      z[i] = s / L[i * p + i];
    }
    for (i = p - 1; i >= 0; i--) {
      if (!keep[i]) { x[i] = 0; continue; }
      var t = z[i];
      for (k = i + 1; k < p; k++) if (keep[k]) t -= L[k * p + i] * x[k];
      x[i] = t / L[i * p + i];
    }
    return x;
  }

  /** Ordinary least squares on a design matrix the caller built.

        HF.regress.ols(X, y)   X: array of rows (each an array of p numbers,
                                  include a column of 1s for an intercept),
                                  y: array of n numbers.

      Returns {coef, rank, aliased, sse, sst, r2, n, p}: `coef[j]` is NaN for
      a column that was dropped as collinear (listed in `aliased`), never a
      silent 0. Normal equations with the pivot-skipping Cholesky above, which
      is what the bootstrap uses, so what is tested here is what runs there.
      Exposed so the arithmetic can be checked against a known answer on its
      own, apart from standardisation, month dummies and resampling. */
  function ols(X, y) {
    var n = X.length;
    if (!n || n !== y.length) bad('ols needs n rows of X and n values of y');
    var p = X[0].length, i, j, r;
    var A = new Float64Array(p * p), b = new Float64Array(p);
    for (r = 0; r < n; r++) {
      var row = X[r];
      for (i = 0; i < p; i++) {
        var xi = row[i];
        b[i] += xi * y[r];
        for (j = 0; j <= i; j++) A[i * p + j] += xi * row[j];
      }
    }
    for (i = 0; i < p; i++) for (j = i + 1; j < p; j++) A[i * p + j] = A[j * p + i];
    var f = cholSkip(A, p), x = cholSolve(f, b), aliased = [], rank = 0;
    for (j = 0; j < p; j++) { if (f.keep[j]) rank++; else aliased.push(j); }
    var sse = 0, ybar = 0, sst = 0;
    for (r = 0; r < n; r++) ybar += y[r];
    ybar /= n;
    for (r = 0; r < n; r++) {
      var fit = 0;
      for (j = 0; j < p; j++) fit += x[j] * X[r][j];
      sse += (y[r] - fit) * (y[r] - fit);
      sst += (y[r] - ybar) * (y[r] - ybar);
    }
    var coef = [];
    for (j = 0; j < p; j++) coef.push(f.keep[j] ? x[j] : NaN);
    return { coef: coef, rank: rank, aliased: aliased, sse: sse, sst: sst,
             r2: sst > 0 ? 1 - sse / sst : NaN, n: n, p: p };
  }

  /* ---------------------------------------------------------- small stats */

  function quantileSorted(sorted, p) {
    var n = sorted.length;
    if (!n) return NaN;
    var pos = p * (n - 1), lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  function finiteSorted(arr) {
    var out = [], i;
    for (i = 0; i < arr.length; i++) if (isFinite(arr[i])) out.push(arr[i]);
    var f = new Float64Array(out);
    f.sort();                      // typed-array sort is numeric
    return f;
  }

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  /* --------------------------------------------------------------- terms */

  /** Fold a coefficient and its bootstrap draws into the reported object.

      THE MINIMUM DETECTABLE EFFECT (pitfall 3). The interval says how well
      the sample pinned the coefficient DOWN; it cannot say what the sample
      could have seen. With SE = (width of the CI) / (2 * 1.96), the smallest
      true effect a two-sided 5% test detects 80% of the time is

          MDE80 = (1.96 + 0.84) * SE = 2.80 * SE.

      The reason for printing it beside every term: a coefficient of 0.3 with
      a CI of [-0.9, +1.5] is, read alone, "no effect". Its MDE80 is 2.6 -
      this archive could not have seen anything under about 2.6 per SD -
      so the right reading is "unresolved", not "absent". Conversely, on this
      archive the NAO latitude effect is ~1.9 against a floor of ~0.8: it is
      far above what the sample can resolve, so it is detected with room to
      spare, and a product term at 0.2 against a floor of 1.0 is not, and
      says so.

      The SE is read off the bootstrap interval rather than taken from a
      model formula on purpose. It inherits the season-block resampling, so
      it already prices in that events within a season are not independent;
      an OLS standard error would not, and would give a floor several times
      too optimistic. (`seBoot`, the SD of the draws, is reported beside it;
      the two agree to ~10% when the draws are roughly normal.)

      `flag`:
        'detected'     the interval excludes zero AND |coef| >= MDE80.
        'below-floor'  |coef| < MDE80, or the interval includes zero. The
                       sample could not resolve an effect this size. Note
                       this includes a coefficient whose interval EXCLUDES
                       zero but whose size is under the floor (`excludesZero`
                       says which): such an estimate cleared the 5% bar
                       partly by luck - winner's curse - so its magnitude is
                       probably inflated and should not be quoted as the
                       effect.
        'unavailable'  there is no interval (too few seasons, aliased term).

      A zero-width interval with a nonzero SE-free fit (every draw identical)
      is reported as such rather than as an infinitely precise estimate. */
  function finishTerm(name, kind, coef, draws, o, nSeasons, sd) {
    var t = { name: name, label: label(name), kind: kind, coef: coef,
              ci: null, se: null, seBoot: null, mde80: null,
              flag: 'unavailable', excludesZero: null, belowFloor: null,
              nDraws: 0, unit: null };
    if (sd != null) t.unit = { sd: sd, perUnit: coef / sd };
    if (!isFinite(coef)) { t.note = 'aliased: collinear with an earlier column, no coefficient'; return t; }
    if (nSeasons < o.minSeasons || !draws) {
      t.note = 'interval withheld: ' + nSeasons + ' season' + (nSeasons === 1 ? '' : 's') +
               ' (need ' + o.minSeasons + ' for a season-block bootstrap)';
      return t;
    }
    var s = finiteSorted(draws);
    t.nDraws = s.length;
    if (s.length < 0.5 * draws.length || s.length < 20) {
      t.note = 'interval withheld: this term was undefined in most bootstrap resamples';
      return t;
    }
    var a = (1 - o.level) / 2;
    var lo = quantileSorted(s, a), hi = quantileSorted(s, 1 - a);
    var z = zFor(o.level, o.power);
    var m = 0, i, v = 0;
    for (i = 0; i < s.length; i++) m += s[i];
    m /= s.length;
    for (i = 0; i < s.length; i++) v += (s[i] - m) * (s[i] - m);
    t.seBoot = Math.sqrt(v / (s.length - 1));
    t.ci = [lo, hi];
    t.se = (hi - lo) / (2 * z.zCrit);
    t.mde80 = z.k * t.se;
    t.excludesZero = lo > 0 || hi < 0;
    t.belowFloor = Math.abs(coef) < t.mde80;
    t.flag = t.excludesZero && !t.belowFloor ? 'detected' : 'below-floor';
    if (hi - lo <= 1e-12 * Math.max(1, Math.abs(coef))) {
      t.note = 'zero-width interval: every resample gave the same coefficient (noise-free data, or too little between-season variation); this is not infinite precision';
    }
    return t;
  }

  /* ------------------------------------------------------- the generic fit */

  /** Fit one model on plain columns. This is the engine; fit() below only
      turns decoded lows into these columns.

        data = {
          y:      [numbers or null],       the response
          season: [season id],             the resampling unit
          month:  [1..12],                 fixed effect
          x:      {nao: [..], pna: [..]},  raw predictor columns (null = missing)
          mjo:    {phase: [radians], amp: [..]} | null   optional harmonic pair
        }

      Rows with a missing response, predictor or (when MJO is on) phase or
      amplitude are dropped, and counted by cause. Returns the object
      documented at the top of this file. */
  function fitData(data, opts) {
    var o = resolveOptions(opts);
    var preds = o.predictors.filter(function (nm) { return data.x && data.x[nm]; });
    var warnings = [];
    if (o.predictors.length && preds.length < o.predictors.length) {
      bad('no data column for predictor(s): ' + o.predictors.filter(function (nm) {
        return !(data.x && data.x[nm]);
      }).join(', '));
    }
    var nIn = data.y.length, i, j, k;
    var useMjo = !!(data.mjo && data.mjo.phase && data.mjo.amp);

    /* -- listwise deletion, counted by cause -- */
    var dropped = { response: 0, season: 0, month: 0, mjo: 0 }, keepRow = [];
    preds.forEach(function (nm) { dropped[nm] = 0; });
    for (i = 0; i < nIn; i++) {
      var ok = true;
      if (!isNum(data.y[i])) { dropped.response++; ok = false; }
      if (data.season[i] == null || !isNum(Number(data.season[i]))) { dropped.season++; ok = false; }
      if (!(data.month[i] >= 1 && data.month[i] <= 12)) { dropped.month++; ok = false; }
      for (j = 0; j < preds.length; j++) {
        if (!isNum(data.x[preds[j]][i])) { dropped[preds[j]]++; ok = false; }
      }
      if (useMjo && !(isNum(data.mjo.phase[i]) && isNum(data.mjo.amp[i]))) { dropped.mjo++; ok = false; }
      if (ok) keepRow.push(i);
    }
    var n = keepRow.length;
    var res = {
      status: 'ok', reliability: 'ok',
      n: { events: n, input: nIn, seasons: 0, dropped: dropped, params: 0, df: 0 },
      seasons: [], terms: [], byName: {}, mjo: null,
      r2: null, r2Adj: null, r2Base: null, sigma: null,
      fixedEffects: null, bootstrap: null, warnings: warnings
    };
    var droppedTotal = nIn - n;
    if (droppedTotal) {
      var causes = [];
      Object.keys(dropped).forEach(function (kk) { if (dropped[kk]) causes.push(dropped[kk] + ' ' + (kk === 'response' ? 'with no response value' : kk === 'mjo' ? 'with no MJO phase/amplitude' : 'with no ' + kk)); });
      warnings.push(droppedTotal + ' of ' + nIn + ' events left out (' + causes.join(', ') + '; counts overlap).');
    }
    if (!n) { res.status = 'empty'; res.reliability = 'none'; warnings.push('No events with every needed value; nothing to fit.'); return res; }

    /* -- columns -- */
    var y = new Float64Array(n), seasonOf = new Array(n), monthOf = new Array(n);
    var ybar = 0;
    for (i = 0; i < n; i++) {
      y[i] = data.y[keepRow[i]];
      seasonOf[i] = Number(data.season[keepRow[i]]);
      monthOf[i] = data.month[keepRow[i]];
      ybar += y[i];
    }
    ybar /= n;

    var seasonIds = [], seasonIdx = {};
    for (i = 0; i < n; i++) {
      if (seasonIdx[seasonOf[i]] === undefined) { seasonIdx[seasonOf[i]] = seasonIds.length; seasonIds.push(seasonOf[i]); }
    }
    var sortedSeasons = seasonIds.slice().sort(function (a, b) { return a - b; });
    var G = seasonIds.length;
    res.seasons = sortedSeasons;
    res.n.seasons = G;
    var gOf = new Int32Array(n);
    for (i = 0; i < n; i++) gOf[i] = seasonIdx[seasonOf[i]];

    /* Month fixed effects. The reference month is the most populated one
       (arbitrary, and slope-neutral; the most populated is simply the one
       whose intercept is best determined). Months with no events get no
       column. */
    var monthCount = {};
    for (i = 0; i < n; i++) monthCount[monthOf[i]] = (monthCount[monthOf[i]] || 0) + 1;
    var months = Object.keys(monthCount).map(Number).sort(function (a, b) { return a - b; });
    var refMonth = months[0];
    months.forEach(function (m) { if (monthCount[m] > monthCount[refMonth]) refMonth = m; });
    var dummyMonths = months.filter(function (m) { return m !== refMonth; });
    if (months.length === 1) warnings.push('Every event is in month ' + refMonth + ': no month fixed effects to estimate.');
    var thin = months.filter(function (m) { return monthCount[m] < 5; });
    if (thin.length) warnings.push('Month' + (thin.length > 1 ? 's' : '') + ' ' + thin.join(', ') + ' hold fewer than 5 events; their fixed effects are barely estimated (they absorb those events, which is the point, but the effect is not otherwise informative).');

    /* Standardise. Each predictor by its own mean and SD over the events IN
       THE FIT (population SD, n in the denominator: at n ~ 1,000 the (n-1)
       version differs by 0.05%, and this one is what numpy's default and
       most people's reference scripts give). "Per standard deviation" then
       means per SD of the index as these storms experienced it - for the
       NAO at genesis, ~0.78 against ~0.80 for every day of the record -
       which is the scale a forecaster reading "the NAO was +1 SD" has in
       mind. It does mean the unit shifts slightly with the subset; the
       unstandardised slope (`unit.perUnit`) is reported next to it, and
       opts.scale pins the units if two fits must be comparable. The scale
       factor cancels from t-ratios and p-values, and it is applied to the
       predictor only: a coefficient reads "response units per SD". */
    var zcols = {}, scaleInfo = {};
    preds.forEach(function (nm) {
      var raw = new Float64Array(n), m = 0, v = 0;
      for (i = 0; i < n; i++) { raw[i] = data.x[nm][keepRow[i]]; m += raw[i]; }
      m /= n;
      for (i = 0; i < n; i++) v += (raw[i] - m) * (raw[i] - m);
      var sdv = Math.sqrt(v / n);
      if (o.scale && o.scale[nm]) { m = o.scale[nm].mean; sdv = o.scale[nm].sd; }
      scaleInfo[nm] = { mean: m, sd: sdv };
      if (!(sdv > 0)) { zcols[nm] = null; return; }
      var z = new Float64Array(n);
      for (i = 0; i < n; i++) z[i] = (raw[i] - m) / sdv;
      zcols[nm] = z;
    });
    preds = preds.filter(function (nm) {
      if (zcols[nm]) return true;
      warnings.push(label(nm) + ' has no variation across these events; left out of the model.');
      return false;
    });

    /* Interactions: product of two standardised columns. */
    var inter = [];
    if (o.interactions) {
      var pairs = o.interactions === true ? [] : o.interactions;
      if (o.interactions === true) {
        for (i = 0; i < preds.length; i++) for (j = i + 1; j < preds.length; j++) pairs.push([preds[i], preds[j]]);
      }
      pairs.forEach(function (pr) {
        if (!zcols[pr[0]] || !zcols[pr[1]]) bad('interaction ' + pr.join('*') + ' names a predictor that is not in the model');
        var col = new Float64Array(n);
        for (i = 0; i < n; i++) col[i] = zcols[pr[0]][i] * zcols[pr[1]][i];
        inter.push({ name: pr[0] + '*' + pr[1], col: col });
      });
    }

    /* MJO harmonic pair: A*cos(phi), A*sin(phi), raw (amplitude units). */
    var mjoCols = null, mjoPhase = null, mjoAmp = null;
    if (useMjo) {
      mjoPhase = new Float64Array(n); mjoAmp = new Float64Array(n);
      var cc = new Float64Array(n), ss = new Float64Array(n);
      for (i = 0; i < n; i++) {
        mjoPhase[i] = data.mjo.phase[keepRow[i]];
        mjoAmp[i] = data.mjo.amp[keepRow[i]];
        cc[i] = mjoAmp[i] * Math.cos(mjoPhase[i]);
        ss[i] = mjoAmp[i] * Math.sin(mjoPhase[i]);
      }
      mjoCols = { c: cc, s: ss };
    }

    /* -- the design matrix: intercept | months | indices | interactions | mjo -- */
    var colNames = ['(intercept)'], colKind = ['intercept'], colData = [null];
    dummyMonths.forEach(function (m) {
      var col = new Float64Array(n);
      for (i = 0; i < n; i++) col[i] = monthOf[i] === m ? 1 : 0;
      colNames.push('month' + m); colKind.push('month'); colData.push(col);
    });
    var iFirstTerm = colNames.length;
    preds.forEach(function (nm) { colNames.push(nm); colKind.push('index'); colData.push(zcols[nm]); });
    inter.forEach(function (t) { colNames.push(t.name); colKind.push('interaction'); colData.push(t.col); });
    var iMjo = -1;
    if (mjoCols) { iMjo = colNames.length; colNames.push('mjo_cos', 'mjo_sin'); colKind.push('mjo', 'mjo'); colData.push(mjoCols.c, mjoCols.s); }
    var p = colNames.length;
    res.n.params = p;
    res.n.df = n - p;

    var X = new Float64Array(n * p);       // row-major: row i is X[i*p .. i*p+p)
    for (i = 0; i < n; i++) {
      X[i * p] = 1;
      for (j = 1; j < p; j++) X[i * p + j] = colData[j][i];
    }
    // y is centred before any sums of squares are formed, so that SSE is not
    // the difference of two ~1e9 numbers (minimum pressure is ~980 hPa).
    // The intercept absorbs the shift; no slope sees it.
    var yc = new Float64Array(n);
    for (i = 0; i < n; i++) yc[i] = y[i] - ybar;

    if (n <= p) {
      res.status = 'insufficient'; res.reliability = 'none';
      warnings.push(n + ' events cannot support ' + p + ' parameters (intercept, month effects and climate terms); the fit is not identified.');
      return res;
    }

    /* -- per-season sufficient statistics: X'X, X'y for each season -- */
    var SA = new Array(G), Sb = new Array(G);
    for (k = 0; k < G; k++) { SA[k] = new Float64Array(p * p); Sb[k] = new Float64Array(p); }
    for (i = 0; i < n; i++) {
      var A = SA[gOf[i]], b = Sb[gOf[i]], xo = i * p, yi = yc[i], a1, a2;
      for (a1 = 0; a1 < p; a1++) {
        var xa = X[xo + a1];
        if (xa === 0) continue;                 // month dummies are mostly zero
        b[a1] += xa * yi;
        for (a2 = 0; a2 <= a1; a2++) A[a1 * p + a2] += xa * X[xo + a2];
      }
    }
    for (k = 0; k < G; k++) {
      for (i = 0; i < p; i++) for (j = i + 1; j < p; j++) SA[k][i * p + j] = SA[k][j * p + i];
    }
    var tA = new Float64Array(p * p), tb = new Float64Array(p);
    for (k = 0; k < G; k++) {
      for (i = 0; i < p * p; i++) tA[i] += SA[k][i];
      for (i = 0; i < p; i++) tb[i] += Sb[k][i];
    }

    var f0 = cholSkip(tA, p), beta = cholSolve(f0, tb);
    var aliased = [];
    for (j = 0; j < p; j++) if (!f0.keep[j]) aliased.push(colNames[j]);
    if (aliased.length) warnings.push('Dropped as collinear: ' + aliased.join(', ') + ' (later columns lose to earlier ones).');

    /* -- fit quality, from the residuals themselves -- */
    var sse = 0, sst = 0;
    for (i = 0; i < n; i++) {
      var fv = 0;
      for (j = 0; j < p; j++) fv += beta[j] * X[i * p + j];
      sse += (yc[i] - fv) * (yc[i] - fv);
      sst += yc[i] * yc[i];
    }
    res.r2 = sst > 0 ? Math.max(0, 1 - sse / sst) : null;
    var rank0 = 0;
    for (j = 0; j < p; j++) if (f0.keep[j]) rank0++;
    res.r2Adj = sst > 0 && n > rank0 ? 1 - (sse / (n - rank0)) / (sst / (n - 1)) : null;
    res.sigma = n > rank0 ? Math.sqrt(sse / (n - rank0)) : null;
    if (sse <= 1e-9 * Math.max(1, sst)) warnings.push('The fit is essentially exact (R^2 ~ 1): no residual noise, so every interval will be zero-width. This is what noise-free test data looks like; real storm data never does.');

    /* R^2 of the intercept + month model alone: how much of the response the
       calendar already explains, so a caller can say what the climate terms
       ADD instead of quoting a number dominated by the seasonal cycle. */
    var base = [], bj;
    for (j = 0; j < iFirstTerm; j++) base.push(j);
    var bp = base.length, bA = new Float64Array(bp * bp), bb = new Float64Array(bp);
    for (i = 0; i < bp; i++) { for (j = 0; j < bp; j++) bA[i * bp + j] = tA[base[i] * p + base[j]]; bb[i] = tb[base[i]]; }
    var fb = cholSkip(bA, bp), betaB = cholSolve(fb, bb), fitB = 0;
    for (bj = 0; bj < bp; bj++) fitB += betaB[bj] * bb[bj];
    res.r2Base = sst > 0 ? Math.max(0, fitB / sst) : null;     // explained SS / total SS (y is centred)

    res.fixedEffects = { month: { reference: refMonth, counts: monthCount, effects: [] } };
    dummyMonths.forEach(function (m, idx) {
      res.fixedEffects.month.effects.push({ month: m, coef: f0.keep[1 + idx] ? beta[1 + idx] : NaN });
    });
    res.intercept = beta[0] + ybar;

    /* -- reliability, before any interval is drawn -- */
    var rowsPerParam = n / p;
    if (G < o.minSeasons) {
      res.status = 'insufficient';
      res.reliability = 'none';
      warnings.push('Only ' + G + ' season' + (G === 1 ? '' : 's') + ' in the fit. A season-block bootstrap resamples whole seasons; with ' +
        (G === 1 ? 'one it returns the same estimate in every draw, a zero-width interval that would read as infinite precision' :
                   'so few the resamples barely differ') +
        '. Coefficients are shown, confidence intervals and minimum detectable effects are withheld (need ' + o.minSeasons + ' seasons).');
    } else if (G < o.cautionSeasons) {
      res.reliability = 'low';
      warnings.push('Only ' + G + ' seasons: a season-block bootstrap with this few blocks understates uncertainty. Treat the intervals as optimistic.');
    }
    if (rowsPerParam < o.minRowsPerParam) {
      if (res.reliability === 'ok') res.reliability = 'low';
      warnings.push('Only ' + rowsPerParam.toFixed(1) + ' events per parameter (' + n + ' events, ' + p + ' parameters); the fit is close to overfitting.');
    }

    /* -- season-block bootstrap -- */
    var termIdx = [];
    for (j = iFirstTerm; j < (iMjo >= 0 ? iMjo : p); j++) termIdx.push(j);
    var doBoot = G >= o.minSeasons;
    var drawsByCol = null, rDraws = null, angDraws = null, failed = 0;
    if (doBoot) {
      var rng = makeRng(o.seed);
      var wantCols = termIdx.slice();
      if (iMjo >= 0) wantCols.push(iMjo, iMjo + 1);
      drawsByCol = {};
      wantCols.forEach(function (c) { drawsByCol[c] = new Float64Array(o.iterations); });
      if (iMjo >= 0) { rDraws = new Float64Array(o.iterations); angDraws = new Float64Array(o.iterations); }
      var bA2 = new Float64Array(p * p), bb2 = new Float64Array(p), xb = new Float64Array(p);
      var it, g, w;
      for (it = 0; it < o.iterations; it++) {
        for (i = 0; i < p * p; i++) bA2[i] = 0;
        for (i = 0; i < p; i++) bb2[i] = 0;
        for (g = 0; g < G; g++) {
          var pick = Math.floor(rng() * G), sa = SA[pick], sb = Sb[pick];
          for (i = 0; i < p * p; i++) bA2[i] += sa[i];
          for (i = 0; i < p; i++) bb2[i] += sb[i];
        }
        var fb2 = cholSkip(bA2, p);
        cholSolve(fb2, bb2, xb);
        var anyBad = false;
        for (w = 0; w < wantCols.length; w++) {
          var cj = wantCols[w];
          if (fb2.keep[cj]) drawsByCol[cj][it] = xb[cj];
          else { drawsByCol[cj][it] = NaN; anyBad = true; }
        }
        if (anyBad) failed++;
        if (iMjo >= 0) {
          var bc = fb2.keep[iMjo] ? xb[iMjo] : NaN, bs = fb2.keep[iMjo + 1] ? xb[iMjo + 1] : NaN;
          rDraws[it] = Math.sqrt(bc * bc + bs * bs);
          angDraws[it] = Math.atan2(bs, bc) / DEG;
        }
      }
      if (failed > 0.05 * o.iterations) {
        warnings.push(failed + ' of ' + o.iterations + ' bootstrap resamples could not estimate every term (a term was collinear or absent in the resampled seasons); those draws are skipped for that term.');
      }
    }
    res.bootstrap = doBoot ? { method: 'season-block percentile', iterations: o.iterations, seed: o.seed,
                               level: o.level, failed: failed, blocks: G } :
                             { method: 'withheld', iterations: 0, seed: o.seed, level: o.level, failed: 0, blocks: G };

    /* -- terms -- */
    termIdx.forEach(function (c) {
      var nm = colNames[c];
      var sdv = colKind[c] === 'index' ? scaleInfo[nm].sd : null;
      var t = finishTerm(nm, colKind[c], f0.keep[c] ? beta[c] : NaN, doBoot ? drawsByCol[c] : null, o, G, sdv);
      res.terms.push(t);
      res.byName[nm] = t;
    });

    /* -- the MJO pair, jointly -- */
    if (iMjo >= 0) {
      res.mjo = mjoResult(o, {
        n: n, p: p, X: X, yc: yc, tA: tA, tb: tb, iMjo: iMjo, beta: beta, f0: f0,
        phase: mjoPhase, amp: mjoAmp, seasonOf: seasonOf, monthOf: monthOf,
        colNames: colNames, colKind: colKind, drawsByCol: drawsByCol, rDraws: rDraws, angDraws: angDraws,
        doBoot: doBoot, G: G, warnings: warnings
      });
    }

    res.scale = scaleInfo;
    return res;
  }

  /* ----------------------------------------------------------- the MJO pair */

  /** The MJO harmonic pair, tested jointly (pitfall 2).

      WHY A PAIR. The MJO phase is an angle: phase 8 is next to phase 1. A
      linear term in "phase" says the response climbs steadily through phases
      1..8 and then falls off a cliff back to phase 1, which is nothing the
      atmosphere does and which cannot represent the one shape that matters,
      a response that peaks in some phases and troughs in the opposite ones.
      The first harmonic does: y = b_c * A cos(phi) + b_s * A sin(phi)
      = A * R * cos(phi - phi*), with R = hypot(b_c, b_s) the amplitude of
      the response (per unit MJO amplitude) and phi* = atan2(b_s, b_c) the
      phase at which it is largest. Weighting by the MJO amplitude A means a
      weak, ill-defined MJO (A near 0, phase meaningless) contributes
      almost nothing, instead of voting with the same weight as a strong one.

      WHY NOT TEST THE TWO COEFFICIENTS SEPARATELY. b_c and b_s depend on
      where phase zero was put: rotate the phase axis by 45 degrees and the
      two coefficients trade places, though nothing physical changed. Either
      could be small while R is large (an effect centred between them), and
      two separate 5% tests spend twice the false-positive budget. Only R is
      invariant to the rotation, so it is the statistic.

      THE NULL. Not b_c and b_s each against a t-distribution: R is positive,
      and its distribution under no effect is Rayleigh-like, not normal. It
      comes from a permutation instead: shuffle PHASE among events in the
      same (season, month) block, refit, and record R. Season, because
      events within a season share a background state and shuffling across
      seasons would let a quiet year's storms borrow a busy year's MJO;
      month, because the MJO has its own seasonal cycle and the track moves
      hundreds of km between October and February, so shuffling across months
      would attribute the calendar to the MJO (composite.js found the same
      thing for NAO terciles: free permutation put 18% of one subset's
      events in October against 9% for the archive). The amplitude stays
      attached to its own event, so the null changes the PHASE relationship
      and nothing else. The other climate terms stay in the model, unchanged,
      exactly as in the real fit.

      EFFICIENT. Refitting the whole 20-column model 999 times would cost
      999 x (n p^2). Instead the other columns Z are partialled out once
      (Frisch-Waugh): with ry = y residualised on Z, a candidate (c, s) pair
      needs only Z'c and Z's (n q multiply-adds each), one back-solve against
      the cached Z factor, and a 2x2 solve. The observed R recomputed this
      way must equal the full fit's R; if it does not, a warning says so.

      MDE FOR R. R has no CI-width-based SE (it is a magnitude, not a signed
      coefficient). Its null supplies the equivalent: r95, the 95th percentile
      of R under no effect, is the bar R must clear, and sigma, the null's
      per-component SD, is the noise. The floor is the true amplitude A at
      which a noisy estimate, (A + sigma*e1, sigma*e2) with e ~ N(0,1),
      clears r95 80% of the time - a Rice-distribution power calculation,
      solved by bisection on a fixed set of 4,000 normal pairs. Same meaning
      as MDE80 for the scalar terms: the effect size below which a failure to
      detect is uninformative. */
  function mjoResult(o, c) {
    var n = c.n, p = c.p, q = p - 2, X = c.X, i, k, b;
    var out = { status: 'ok', n: n, components: [], R: null, angleDeg: null,
                p: null, nPerm: 0, rNull95: null, mde80: null, ciR: null,
                angleCI: null, flag: 'unavailable', permutableFraction: null,
                phaseUnit: 'radians' };
    if (!c.f0.keep[c.iMjo] || !c.f0.keep[c.iMjo + 1]) {
      out.status = 'aliased';
      out.note = 'MJO columns are collinear with the other terms (constant phase or amplitude?); no estimate.';
      c.warnings.push(out.note);
      return out;
    }
    var bc = c.beta[c.iMjo], bs = c.beta[c.iMjo + 1];
    out.R = Math.sqrt(bc * bc + bs * bs);
    out.angleDeg = wrap360(Math.atan2(bs, bc) / DEG);

    // Components, for completeness: each with its own interval and floor, but
    // deliberately NOT flagged (their sign and size depend on where phase 0
    // is; only the joint statistic below is a result).
    ['mjo_cos', 'mjo_sin'].forEach(function (nm, idx) {
      var t = finishTerm(nm, 'mjo', c.beta[c.iMjo + idx], c.doBoot ? c.drawsByCol[c.iMjo + idx] : null, o, c.G, null);
      t.flag = 'joint-test-only';
      out.components.push(t);
    });

    if (c.doBoot) {
      var rs = finiteSorted(c.rDraws);
      var a = (1 - o.level) / 2;
      out.ciR = [quantileSorted(rs, a), quantileSorted(rs, 1 - a)];
      // Interval for the angle: deviations from the point angle, wrapped, so
      // an angle near 0/360 does not split into two clusters. Meaningful only
      // when R is clearly above zero; at R ~ 0 the phase is undefined.
      var dev = [];
      for (i = 0; i < c.angDraws.length; i++) if (isFinite(c.angDraws[i])) dev.push(wrap180(c.angDraws[i] - out.angleDeg));
      var ds = new Float64Array(dev); ds.sort();
      out.angleCI = [wrap360(out.angleDeg + quantileSorted(ds, a)), wrap360(out.angleDeg + quantileSorted(ds, 1 - a))];
      out.angleCIWidth = quantileSorted(ds, 1 - a) - quantileSorted(ds, a);
    }

    // Blocks: (season, month). Singletons carry no permutation information.
    var blockMap = {}, blocks = [], key, singles = 0;
    for (i = 0; i < n; i++) {
      key = c.seasonOf[i] + '|' + c.monthOf[i];
      if (blockMap[key] === undefined) { blockMap[key] = blocks.length; blocks.push([]); }
      blocks[blockMap[key]].push(i);
    }
    for (b = 0; b < blocks.length; b++) if (blocks[b].length < 2) singles++;
    var movable = 0;
    for (b = 0; b < blocks.length; b++) if (blocks[b].length >= 2) movable += blocks[b].length;
    out.permutableFraction = movable / n;
    out.nBlocks = blocks.length;
    if (out.permutableFraction < 0.5) {
      c.warnings.push('Only ' + Math.round(100 * out.permutableFraction) + '% of events share a (season, month) block with another event, so the MJO permutation can move few of them; its p-value is conservative.');
    }

    // Partial out Z (everything but the pair).
    var ZA = new Float64Array(q * q), Zb = new Float64Array(q), j;
    for (i = 0; i < q; i++) { for (j = 0; j < q; j++) ZA[i * q + j] = c.tA[i * p + j]; Zb[i] = c.tb[i]; }
    var fz = cholSkip(ZA, q), bZ = cholSolve(fz, Zb);
    var ry = new Float64Array(n);
    for (i = 0; i < n; i++) {
      var fv = 0;
      for (j = 0; j < q; j++) fv += bZ[j] * X[i * p + j];
      ry[i] = c.yc[i] - fv;
    }
    var cosP = new Float64Array(n), sinP = new Float64Array(n);
    for (i = 0; i < n; i++) { cosP[i] = Math.cos(c.phase[i]); sinP[i] = Math.sin(c.phase[i]); }

    var src = new Int32Array(n), Zc = new Float64Array(q), Zs = new Float64Array(q);
    var wC = new Float64Array(q), wS = new Float64Array(q);
    var cv = new Float64Array(n), sv = new Float64Array(n);
    // Z'c and Z's dominate the cost, and most of Z is month dummies, whose
    // inner products are just per-month sums of c and s. Only the index and
    // interaction columns need the row-by-row multiply-add.
    var denseCols = [], dummyCol = new Int32Array(n);
    for (j = 0; j < q; j++) if (c.colKind[j] !== 'intercept' && c.colKind[j] !== 'month') denseCols.push(j);
    for (i = 0; i < n; i++) {
      dummyCol[i] = -1;
      for (j = 1; j < q; j++) if (c.colKind[j] === 'month' && X[i * p + j] === 1) { dummyCol[i] = j; break; }
    }
    var nDense = denseCols.length;
    function pairStat() {      // R for the pair currently in cv / sv, or NaN
      var cc = 0, ss = 0, cs = 0, cy = 0, sy = 0, r, jj;
      for (jj = 0; jj < q; jj++) { Zc[jj] = 0; Zs[jj] = 0; }
      for (r = 0; r < n; r++) {
        var ci = cv[r], si = sv[r], xo = r * p, dc = dummyCol[r];
        cc += ci * ci; ss += si * si; cs += ci * si; cy += ci * ry[r]; sy += si * ry[r];
        Zc[0] += ci; Zs[0] += si;
        if (dc >= 0) { Zc[dc] += ci; Zs[dc] += si; }
        for (jj = 0; jj < nDense; jj++) { var dj = denseCols[jj], z = X[xo + dj]; Zc[dj] += z * ci; Zs[dj] += z * si; }
      }
      cholSolve(fz, Zc, wC); cholSolve(fz, Zs, wS);
      var gcc = cc, gss = ss, gcs = cs;
      for (jj = 0; jj < q; jj++) { gcc -= Zc[jj] * wC[jj]; gss -= Zs[jj] * wS[jj]; gcs -= Zc[jj] * wS[jj]; }
      var det = gcc * gss - gcs * gcs;
      if (!(det > 1e-10 * Math.max(1e-300, gcc * gss))) return null;
      var pc = (gss * cy - gcs * sy) / det, ps = (gcc * sy - gcs * cy) / det;
      return { bc: pc, bs: ps, R: Math.sqrt(pc * pc + ps * ps) };
    }
    for (i = 0; i < n; i++) { cv[i] = c.amp[i] * cosP[i]; sv[i] = c.amp[i] * sinP[i]; }
    var chk = pairStat();
    if (!chk || Math.abs(chk.R - out.R) > 1e-6 * Math.max(1, out.R)) {
      c.warnings.push('Internal check failed: the permutation machinery gives R = ' + (chk ? chk.R : 'n/a') + ' for the observed data against ' + out.R + ' from the full fit. The p-value is not trustworthy.');
    }

    var rng = makeRng(o.seed + 7919);
    var B = o.permutations, rNull = new Float64Array(B), nBad = 0, ge = 0, sumSq = 0, nOk = 0, t, m, e;
    var tmp = [];
    for (t = 0; t < B; t++) {
      for (b = 0; b < blocks.length; b++) {
        var blk = blocks[b], len = blk.length;
        if (len < 2) { src[blk[0]] = blk[0]; continue; }
        tmp.length = len;
        for (m = 0; m < len; m++) tmp[m] = blk[m];
        for (m = len - 1; m > 0; m--) {                 // Fisher-Yates
          e = Math.floor(rng() * (m + 1));
          var sw = tmp[m]; tmp[m] = tmp[e]; tmp[e] = sw;
        }
        for (m = 0; m < len; m++) src[blk[m]] = tmp[m];
      }
      for (i = 0; i < n; i++) { cv[i] = c.amp[i] * cosP[src[i]]; sv[i] = c.amp[i] * sinP[src[i]]; }
      var st = pairStat();
      if (!st) { rNull[t] = NaN; nBad++; continue; }
      rNull[t] = st.R;
      sumSq += (st.bc * st.bc + st.bs * st.bs) / 2;
      nOk++;
      if (st.R >= out.R - 1e-12) ge++;
    }
    out.nPerm = nOk;
    if (nBad > 0.05 * B) c.warnings.push(nBad + ' of ' + B + ' MJO permutations were singular and are left out of the null.');
    out.p = (1 + ge) / (nOk + 1);
    var ns = finiteSorted(rNull);
    out.rNull95 = quantileSorted(ns, 1 - (1 - o.level));
    out.rNullMedian = quantileSorted(ns, 0.5);
    out.sigmaNull = Math.sqrt(sumSq / Math.max(1, nOk));

    // MDE for R by Rice-distribution power at the null's own noise level.
    var zr = makeRng(o.seed + 104729), Z1 = new Float64Array(4000), Z2 = new Float64Array(4000);
    for (i = 0; i < 4000; i++) {
      var u1 = Math.max(zr(), 1e-12), u2 = zr(), rad = Math.sqrt(-2 * Math.log(u1));
      Z1[i] = rad * Math.cos(2 * Math.PI * u2); Z2[i] = rad * Math.sin(2 * Math.PI * u2);
    }
    var thr = out.rNull95, sg = out.sigmaNull;
    function power(A) {
      var hit = 0, ii;
      for (ii = 0; ii < 4000; ii++) {
        var x1 = A + sg * Z1[ii], x2 = sg * Z2[ii];
        if (x1 * x1 + x2 * x2 > thr * thr) hit++;
      }
      return hit / 4000;
    }
    var lo = 0, hi = Math.max(thr, 10 * sg), it2;
    if (isFinite(thr) && sg > 0) {
      for (it2 = 0; it2 < 40; it2++) {
        var mid = (lo + hi) / 2;
        if (power(mid) < o.power) lo = mid; else hi = mid;
      }
      out.mde80 = (lo + hi) / 2;
    }
    // The permutation's alpha is 1 - level, consistent with the scalar terms.
    var sig = out.p < 1 - o.level;
    out.excludesNull = sig;
    out.belowFloor = out.mde80 != null ? out.R < out.mde80 : null;
    out.flag = out.mde80 == null ? 'unavailable' : (sig && !out.belowFloor ? 'detected' : 'below-floor');
    return out;
  }

  /* ------------------------------------------------------- lows -> columns */

  /** The responses a caller can name. `get(low)` returns a number or null
      (null = this event has no value and is left out, counted). `circular`
      responses are angles in degrees: they are averaged and then put on a
      continuous branch before regression (pitfall 1), and are never subjected
      to ordinary arithmetic on raw degrees. */
  function eventLatMean(low) {
    var fx = low.fixes || [], s = 0, n = 0, i;
    for (i = 0; i < fx.length; i++) if (isNum(fx[i].lat)) { s += fx[i].lat; n++; }
    return n ? s / n : null;
  }

  /** Circular mean of an event's fix longitudes (degrees, [-180, 180)).
      Null when the fixes have no preferred direction (resultant length ~0),
      which no real track does; a track long enough to wrap the globe would. */
  function eventLonMean(low) {
    var fx = low.fixes || [], lons = [], i;
    for (i = 0; i < fx.length; i++) if (isNum(fx[i].lon)) lons.push(fx[i].lon);
    if (!lons.length) return null;
    var cm = circMeanDeg(lons);
    return isNaN(cm.mean) ? null : cm.mean;
  }

  function field(name) { return function (low) { return isNum(low[name]) ? low[name] : null; }; }

  var RESPONSES = {
    lat:     { label: 'Mean fix latitude',  units: 'deg N',  get: eventLatMean,
               desc: 'Mean latitude of the event\'s fixes' },
    lon:     { label: 'Mean fix longitude', units: 'deg E',  get: eventLonMean, circular: true,
               desc: 'Circular mean longitude of the event\'s fixes, on a continuous branch so the dateline is not a seam' },
    minP:    { label: 'Minimum central pressure', units: 'hPa', get: field('minP'),
               desc: 'Lowest analysed central pressure (events with none, e.g. terrain-forced tip jets, are left out)' },
    hfH:     { label: 'Time at hurricane force', units: 'h', get: field('hfH'),
               desc: 'Hours spent at hurricane force (6 h per hurricane-force fix). Every event in the archive has at least one, and the distribution is right-skewed, so the coefficients describe the mean and a few long-lived storms carry much of it' },
    durH:    { label: 'Event duration', units: 'h', get: field('durH'), desc: 'Hours from first to last fix' },
    distNm:  { label: 'Track length', units: 'nm', get: field('distNm'), desc: 'Great-circle track length' },
    latMax:  { label: 'Northernmost fix latitude', units: 'deg N', get: field('latMax'), desc: 'Highest latitude reached' },
    minPLat: { label: 'Latitude of minimum pressure', units: 'deg N', get: field('minPLat'), desc: 'Where the event was deepest (latitude)' },
    minPLon: { label: 'Longitude of minimum pressure', units: 'deg E', get: field('minPLon'), circular: true,
               desc: 'Where the event was deepest (longitude, continuous branch)' },
    deep24:  { label: 'Peak 24 h deepening', units: 'hPa/24 h', get: field('deep24'), desc: 'As stored in the archive' }
  };

  /* ------------------------------------------------------------ MJO source */

  /** Resolve how an event gets its MJO phase and amplitude.

      The index payload's `mjo` block carries `eofPhase[]` (radians, atan2
      range [-pi, pi]) and `eofAmplitude[]` (dimensionless, 1 = one SD of each
      principal component), ALIGNED WITH `mjo.dates`: one value per pentad
      row, null where any of the ten longitudes is missing. They are indexed
      like the longitude series, so HF.teleconnect.mjoRow picks the row and
      `lag` counts rows back from the genesis pentad exactly as it does
      everywhere else. The names are deliberately not `phase` / `amplitude`:
      this is a phase space DERIVED LOCALLY from the ten-longitude field, not
      Wheeler-Hendon RMM, and the build refuses those names so nobody labels
      it RMM. This file does the same: it never says "RMM", never bins into
      octants, and reports the angle with the longitude it corresponds to.

      WHAT AN ANGLE MEANS. Phase 0 is NOT over the Maritime Continent: at
      phase 0 the enhanced convection sits near 314E (46W) and suppressed
      convection near 100-120E; phase increases eastward with time. The
      payload's eof.phaseConvention.convectionLonByPhase tabulates the
      longitude of enhanced convection every 30 degrees of phase, and
      convectionLonAt() interpolates it, so a result can say "deepest lows
      when convection is near 100E" instead of a bare 250 degrees. The EOFs
      are computed over the whole 2001-onward span and shift slightly when
      data are appended (the sign convention is re-derived each build, so the
      meaning is stable): nothing here caches loadings, and the angle is not
      comparable with a published RMM phase.

      Degrades, never throws, when the arrays are missing or the wrong
      length: the term is omitted and the reason goes in the result and in
      warnings. opts.mjo.source(low) -> {phase, amplitude} overrides all of
      this for a caller (or a test) that has phase some other way; it
      answers in opts.mjo.phaseUnit ('radians', the default, or 'degrees'). */
  function mjoAccessor(tc, data, mo) {
    var lag = mo.lag != null ? mo.lag : (tc ? tc.defaultLag : 2);
    var unit = mo.phaseUnit || 'radians';
    if (unit !== 'radians' && unit !== 'degrees') return { ok: false, reason: 'phaseUnit must be radians or degrees' };
    var mj = data && data.mjo, source = typeof mo.source === 'function' ? mo.source : null, table = null;
    if (mj && mj.eof && mj.eof.phaseConvention && mj.eof.phaseConvention.convectionLonByPhase) {
      table = mj.eof.phaseConvention.convectionLonByPhase;
      if (!Array.isArray(table.phaseDeg) || !Array.isArray(table.convectionLonDegE) ||
          table.phaseDeg.length !== table.convectionLonDegE.length || table.phaseDeg.length < 2) table = null;
    }
    if (!source) {
      if (!mj) return { ok: false, reason: 'the teleconnection payload has no mjo block' };
      if (!Array.isArray(mj.eofPhase) || !Array.isArray(mj.eofAmplitude)) {
        return { ok: false, reason: 'the payload\'s mjo block has no eofPhase[] / eofAmplitude[] arrays (not in this build of docs/data/teleconnections.js)' };
      }
      if (!Array.isArray(mj.dates) || mj.eofPhase.length !== mj.dates.length || mj.eofAmplitude.length !== mj.dates.length) {
        return { ok: false, reason: 'mjo.eofPhase / mjo.eofAmplitude are not aligned with mjo.dates (lengths ' + mj.eofPhase.length + ' / ' + mj.eofAmplitude.length + ' vs ' + (mj.dates ? mj.dates.length : 'none') + ')' };
      }
      if (!tc || typeof tc.mjoRow !== 'function') return { ok: false, reason: 'no teleconnect engine to map events to MJO pentads' };
      source = function (low) {
        var row0 = tc.mjoRow(low);
        if (row0 == null) return null;
        var row = row0 - lag;
        if (row < 0) return null;
        var ph = mj.eofPhase[row], am = mj.eofAmplitude[row];
        return isNum(ph) && isNum(am) ? { phase: ph, amplitude: am } : null;
      };
    }
    var toRad = unit === 'radians' ? function (v) { return v; } : function (v) { return v * DEG; };
    return {
      ok: true, lag: lag, unit: unit, table: table,
      get: function (low) {
        var r = source(low);
        if (!r || !isNum(r.phase) || !isNum(r.amplitude)) return null;
        return { phase: toRad(r.phase), amp: r.amplitude };
      }
    };
  }

  /** Longitude (deg E, [0, 360)) of enhanced convection at phase angle
      `deg`, by linear interpolation of the payload's 30-degree table. The
      table's longitudes increase with phase and wrap through 360, so the
      interpolation runs on an unwrapped copy. Null without a table. */
  function convectionLonAt(table, deg) {
    if (!table || !isNum(deg)) return null;
    var ph = table.phaseDeg, lon = table.convectionLonDegE, n = ph.length, i, u = [lon[0]];
    for (i = 1; i < n; i++) u.push(u[i - 1] + wrap360(lon[i] - lon[i - 1]));
    var wrapEnd = u[n - 1] + wrap360(lon[0] - lon[n - 1]);       // value at phase ph[0] + 360
    var a = wrap360(deg - ph[0]) + ph[0], k;
    for (k = n - 1; k >= 0; k--) if (ph[k] <= a) break;
    var p0 = ph[k], v0 = u[k], p1 = k + 1 < n ? ph[k + 1] : ph[0] + 360, v1 = k + 1 < n ? u[k + 1] : wrapEnd;
    return wrap360(v0 + (v1 - v0) * (a - p0) / (p1 - p0));
  }

  /* ----------------------------------------------------- the lows interface */

  var engineCache = { data: null, recordStart: null, tc: null };

  function engineFor(o, recordStart) {
    if (o.teleconnect) return o.teleconnect;
    var data = o.data || (typeof window !== 'undefined' ? window.HF_TELECONNECTIONS : null);
    if (!HF.teleconnect) bad('load teleconnect.js first (HF.teleconnect), or pass opts.teleconnect');
    if (engineCache.tc && engineCache.data === data && engineCache.recordStart === recordStart) return engineCache.tc;
    var tc = HF.teleconnect.create({ data: data, recordStart: recordStart });
    engineCache = { data: data, recordStart: recordStart, tc: tc };
    return tc;
  }

  /** Fit one basin's model on decoded lows.

      opts, on top of DEFAULTS:
        basin       'atl' | 'pac' | any basin key in the lows. REQUIRED unless
                    every low is from one basin. A mixed set with no basin
                    is an error, not a pooled fit (see below).
        response    a key of HF.regress.RESPONSES, or function(low) -> number|null
        teleconnect an HF.teleconnect engine (create it once, reuse it)
        data        the index payload, if not window.HF_TELECONNECTIONS
        recordStart first complete season (default: the engine's, else
                    window.HF_DATA.recordStart)

      WHY SEPARATE BASINS, never a dummy variable. A basin dummy shifts the
      intercept and nothing else, i.e. it assumes the NAO moves an Atlantic
      storm and a Pacific storm by the same amount. They do not: the Atlantic
      track is steered by the NAO and has nothing to do with the PNA, the
      Pacific the reverse, and both slopes (and their signs) differ. Worse for
      a POSITION response: the two basins' mean longitudes differ by ~230
      degrees, so a pooled model's intercept and error variance are dominated
      by which basin an event is in and the slope estimates come from the
      residual. Month effects differ by basin for the same reason. So the
      model is fitted separately and a pooled fit is not offered. */
  function fit(lows, opts) {
    var o = resolveOptions(opts);
    if (!Array.isArray(lows)) bad('fit needs an array of decoded lows (HF.decode(...).lows)');
    var warnings = [];

    // basin
    var basins = {}, i;
    for (i = 0; i < lows.length; i++) basins[lows[i].basin || '?'] = true;
    var keys = Object.keys(basins);
    var basin = opts && opts.basin;
    if (!basin) {
      if (keys.length > 1) {
        bad('lows from ' + keys.length + ' basins (' + keys.join(', ') + ') and no opts.basin. The basins are fitted as separate models, ' +
            'never pooled: their tracks are in different places and respond to different indices. Pass {basin: \'atl\'} or use fitBasins().');
      }
      basin = keys[0];
    }
    var inBasin = lows.filter(function (l) { return l.basin === basin; });

    // response
    var rdef = typeof o.response === 'function' ? { label: 'custom response', units: '', get: o.response } :
               RESPONSES[o.response == null ? 'lat' : o.response];
    if (!rdef) bad('unknown response ' + o.response + '; one of ' + Object.keys(RESPONSES).join(', ') + ' or a function');
    var rkey = typeof o.response === 'function' ? 'custom' : (o.response == null ? 'lat' : o.response);

    // complete seasons
    var recordStart = o.recordStart != null ? o.recordStart :
                      (o.teleconnect && o.teleconnect.recordStart != null ? o.teleconnect.recordStart :
                       (typeof window !== 'undefined' && window.HF_DATA ? window.HF_DATA.recordStart : null));
    var scope = inBasin;
    var nPartial = 0;
    if (o.completeOnly) {
      if (recordStart == null) {
        bad('cannot tell complete seasons from partial ones without recordStart - pass {recordStart: DATA.recordStart} ' +
            '(or {completeOnly: false} to opt out). Partial seasons are short-counted, not quiet.');
      }
      scope = inBasin.filter(function (l) { return l.season >= recordStart; });
      nPartial = inBasin.length - scope.length;
    } else {
      warnings.push('completeOnly is off: the archive\'s early seasons are short-counted, not quiet (1, 22 and 38 events against 62-115), and are in this fit.');
    }

    var tc = engineFor(o, recordStart);
    var mjoAcc = null, mjoWhy = null;
    if (o.mjo) {
      var mo = o.mjo === true ? {} : o.mjo;
      mjoAcc = mjoAccessor(tc, o.data || (typeof window !== 'undefined' ? window.HF_TELECONNECTIONS : null), mo);
      if (!mjoAcc.ok) { mjoWhy = mjoAcc.reason; mjoAcc = null; warnings.push('MJO term omitted: ' + mjoWhy + '.'); }
    }

    // columns
    var yRaw = [], season = [], month = [], x = {}, ph = [], am = [];
    o.predictors.forEach(function (nm) { x[nm] = []; });
    var lowsUsed = [];
    for (i = 0; i < scope.length; i++) {
      var low = scope[i];
      var a = tc.attribute(low);
      yRaw.push(rdef.get(low));
      season.push(low.season);
      var mo2 = low.month != null ? low.month : Math.floor((low.start || 0) / 10000) % 100;
      month.push(mo2);
      o.predictors.forEach(function (nm) {
        var v = null;
        if (nm === 'oni') {
          var e = o.oniBasis === 'djf' ? a.enso.djf : a.enso.genesis;
          v = e ? e.value : null;
        } else if (a[nm]) {
          v = o.indexBasis === 'daily' ? a[nm].daily : a[nm].mean5;
        } else {
          bad('unknown predictor ' + nm + ' (HF.teleconnect provides nao, pna, ao, oni)');
        }
        x[nm].push(v);
      });
      if (mjoAcc) {
        var mv = mjoAcc.get(low);
        ph.push(mv ? mv.phase : null);
        am.push(mv ? mv.amp : null);
      }
      lowsUsed.push(low);
    }

    // circular responses: unwrap on the centre of the events that have one
    var frame = null;
    if (rdef.circular) {
      var centre = circMeanDeg(yRaw.filter(isNum));
      if (isNaN(centre.mean)) {
        bad('the events\' longitudes have no preferred direction; cannot choose a frame');
      }
      frame = { centre: centre.mean, R: centre.R, spreadDeg: null };
      var lo2 = Infinity, hi2 = -Infinity;
      for (i = 0; i < yRaw.length; i++) {
        if (!isNum(yRaw[i])) continue;
        yRaw[i] = unwrapAround(yRaw[i], centre.mean);
        if (yRaw[i] < lo2) lo2 = yRaw[i];
        if (yRaw[i] > hi2) hi2 = yRaw[i];
      }
      frame.spreadDeg = hi2 - lo2;
      frame.range = [lo2, hi2];
      if (frame.spreadDeg > 300) warnings.push('The ' + rkey + ' values span ' + frame.spreadDeg.toFixed(0) + ' degrees even on the continuous branch; no frame can make them one cluster, and a linear model of them is not meaningful.');
    }
    var fdata = { y: yRaw, season: season, month: month, x: x,
                  mjo: mjoAcc ? { phase: ph, amp: am } : null };
    var res = fitData(fdata, o);

    // decorate
    var yv = yRaw.filter(isNum), ym = 0, ys = 0;
    yv.forEach(function (v) { ym += v; });
    ym = yv.length ? ym / yv.length : null;
    yv.forEach(function (v) { ys += (v - ym) * (v - ym); });
    res.basin = basin;
    res.response = { key: rkey, label: rdef.label, units: rdef.units, desc: rdef.desc || '',
                     mean: ym, sd: yv.length > 1 ? Math.sqrt(ys / (yv.length - 1)) : null,
                     circular: !!rdef.circular, frame: frame };
    if (frame) res.response.meanLon = wrap180(ym);
    res.n.partialSeasonsDropped = nPartial;
    res.n.basinEvents = inBasin.length;
    res.completeOnly = o.completeOnly;
    res.recordStart = recordStart;
    res.options = { predictors: o.predictors.slice(), indexBasis: o.indexBasis, oniBasis: o.oniBasis,
                    interactions: o.interactions, iterations: o.iterations, permutations: o.permutations,
                    seed: o.seed, level: o.level, power: o.power, mjo: !!mjoAcc };
    if (res.mjo && mjoAcc) {
      res.mjo.lag = mjoAcc.lag;
      res.mjo.phaseUnit = 'radians';
      res.mjo.convention = 'Derived EOF phase space, not RMM. Phase 0 = enhanced convection near 314E (46W); phase increases eastward with time.';
      if (mjoAcc.table) {
        res.mjo.convectionLonByPhase = mjoAcc.table;
        res.mjo.convectionLonDegE = convectionLonAt(mjoAcc.table, res.mjo.angleDeg);
        if (res.mjo.angleCI) {
          res.mjo.convectionLonCI = [convectionLonAt(mjoAcc.table, res.mjo.angleCI[0]), convectionLonAt(mjoAcc.table, res.mjo.angleCI[1])];
        }
      }
    }
    if (!res.mjo) {
      res.mjo = o.mjo ? { status: 'omitted', reason: mjoWhy || 'no events had both MJO phase and amplitude' } :
                        { status: 'omitted', reason: 'not requested' };
    }
    if (nPartial && o.completeOnly) {
      res.warnings.unshift(nPartial + ' event' + (nPartial === 1 ? '' : 's') + ' in seasons before ' + recordStart + ' left out (short-counted seasons, not quiet ones).');
    }
    res.warnings.unshift.apply(res.warnings, warnings);
    if (res.status === 'ok' && res.terms.length === 0 && res.mjo.status === 'omitted') {
      res.warnings.push('No climate terms in the model: only the intercept and month effects were fitted.');
    }
    return res;
  }

  /** One model per basin, same options: {atl: result, pac: result}. The
      basins found in `lows` are fitted independently; this is the only
      sanctioned way to get both. */
  function fitBasins(lows, opts) {
    var seen = {}, out = {}, i, k;
    for (i = 0; i < lows.length; i++) seen[lows[i].basin || '?'] = true;
    var keys = Object.keys(seen);
    for (k = 0; k < keys.length; k++) {
      var op = {}, key;
      if (opts) for (key in opts) op[key] = opts[key];
      op.basin = keys[k];
      out[keys[k]] = fit(lows, op);
    }
    return out;
  }

  HF.regress = {
    fit: fit,
    fitBasins: fitBasins,
    fitData: fitData,
    ols: ols,
    RESPONSES: RESPONSES,
    DEFAULTS: DEFAULTS,
    // exposed for tests and for callers that need the same maths
    circMeanDeg: circMeanDeg,
    unwrapAround: unwrapAround,
    wrap180: wrap180,
    qnorm: qnorm,
    convectionLonAt: convectionLonAt,
    rng: makeRng
  };

})(window.HF);
