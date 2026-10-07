/* Composite statistics: "does the storm track shift between two sets of
   events, and is that shift distinguishable from noise?" No DOM, no canvas,
   no knowledge of what DEFINED the subset (ENSO phase, MJO phase, an NAO
   tercile, an arbitrary filter) - it takes the events, bins them, and answers
   the one question honestly. Built on HF.decode()'s output (util.js): each
   low is {season, fixes:[{lat, lon, cat, pres}], ...}. Plain script, ES5 style,
   attaches to window.HF like its neighbours.

     var r = HF.composite.compare(allLows, subsetLows, {
       seasons: DATA.seasons,          // the archive's season list (see below)
       seed: 1                         // reproducible; same seed, same answer
     });
     r.status          // 'ok' | 'insufficient' | 'empty' | 'invalid'
     r.reliability     // 'ok' | 'low' | 'none' (read this before drawing anything)
     r.n               // {events, seasons, fixes, allEvents, allSeasons, ...}
     r.cells[i]        // one equal-area cell: geometry, sample sizes, and for
                       // each field ('rate', 'shape') {subset, all, diff,
                       // ratio, p, q, sigCell, sigFDR}
     r.summary.rate    // {nTested, nSigCell, expectedByChance, nSigFDR, ...}

   Four decisions carry the whole thing. Each is argued where it is made;
   this is the map.

   1. EQUAL-AREA GRID (makeGrid). Constant-height latitude bands, each cut
      into as many longitude cells as keeps the cell area as near constant as
      an integer allows. Not a regular lat/lon grid, not a cos(lat) weight.
   2. RATES, NEVER COUNTS. Every field is "per season". A subset of 8 seasons
      and an archive of 25 differ by a factor of three in raw counts before
      any physics happens.
   3. THE SEASON IS THE UNIT OF RESAMPLING. Events within a season share a
      background state (the jet, the blocking, the ENSO phase itself), so
      they are not independent draws and a test that treats 80 events as 80
      samples has error bars about as wide as it should have been narrow.
      The null is built by drawing whole seasons.
   4. FALSE DISCOVERY RATE (Benjamini-Hochberg) over the tested cells, not
      per-cell stippling. With ~150 tested cells, ~5% of them light up on pure noise.

   One assumption to know about before reading results: the null treats
   SEASONS as exchangeable draws, so it is the right test when the subset is a
   set of whole seasons (ENSO, a seasonal-mean NAO tercile). A subset of
   EVENTS that cuts across seasons (MJO phase at the time of the storm) has no
   season-level unit to resample; compare() detects that case and switches to
   a within-season label permutation instead (see "two designs" below) rather
   than quietly applying the wrong test.

   Season membership is whatever each low's `season` field says (the build
   script's 1 June boundary). This file does not re-derive it from dates:
   two modules disagreeing about which season a June storm belongs to would
   be a worse bug than either answer. */

window.HF = window.HF || {};

(function (HF) {
  'use strict';

  var DEG = Math.PI / 180;
  var EARTH_R_KM = 6371.0088;           // mean radius, same constant the other modules use for great circles

  /* ------------------------------------------------------------ options */

  // Every default below was picked for the archive this site holds (1,932
  // events, 25 seasons, 24-67N, 8,073 fixes); the reasoning is next to each.
  var DEFAULTS = {
    // 4 degrees of latitude (~440 km, ~200,000 km^2 a cell) is about the
    // finest cell this archive can support. Its 8,073 fixes occupy 246 cells
    // at this size, 154 of them with >= 10 fixes over the 25 seasons - about
    // 1.5 fixes per season in the busiest. A 2 degree cell (globe.js's
    // choice, right for DRAWING the density) would quarter every count: most
    // cells would hold a handful of fixes in total, so no subset could ever
    // differ from the archive there, and the empty ones would only inflate
    // the multiple-comparisons burden. A coarser cell (6-8 degrees) is
    // available through opts.latStep if a small subset needs more fixes per
    // cell, at the price of blurring a 10-degree shift.
    latStep: 4,

    // Longitude of the cell-index seam. Cells wrap, so a seam has to sit
    // somewhere; 20E is over Eurasia, where the archive has no fixes (Atlantic
    // max is +10E, the Pacific straddles 180 and never gets near 20E), so no
    // populated cell is ever adjacent to the seam. 180 itself is NOT a seam:
    // cell indices are computed modulo 360, so a cell that spans the
    // dateline is one cell, not two.
    lonOrigin: 20,

    // 'fixes'  : every fix counts. Reads as "time spent in the cell" (a slow,
    //            deepening low leaves more fixes) and matches the density layer.
    // 'events' : an event counts once per cell it visits ("how many storms
    //            passed through"), insensitive to how long each lingered.
    unit: 'fixes',

    // Restrict to these fix categories (e.g. ['HF']); null counts every fix of
    // every event in the archive. Never filtered on pressure: terrain-forced
    // 'tipjet' events have pres == null and are real events.
    cats: null,

    // Null-distribution size. Two things set it. The smallest p-value a
    // B-draw null can produce is 1/(B+1), and BH needs the best cell to beat
    // alphaFDR/m, so a lone, very strong cell can only be flagged if
    // B+1 >= m/alphaFDR. For this archive m is ~150 tested cells and
    // alphaFDR is 0.10, so the floor is ~1,500 draws; 5,000 clears it more
    // than threefold (and compare() warns if a finer grid pushes m past what
    // B can resolve). It also holds the Monte Carlo error on a p of 0.01 to
    // about +-0.0014. Cost is ~0.6 s for the full archive in Node, so the
    // page should run it on a button press, not on every filter change.
    iterations: 5000,

    // The default seed is a constant, not the clock: the same two sets give
    // the same map every time, which is what lets a forecaster compare a map
    // today with the one in last week's briefing. Pass another seed to see
    // how much the stippling depends on it (it should hardly move).
    seed: 1,

    // alpha is the GLOBAL level the map is meant to be read at. Wilks (2016,
    // BAMS 97, 2263) recommends running BH at alphaFDR = 2 * alpha_global:
    // spatial correlation makes BH conservative, and doubling restores the
    // intended global false-positive rate. Null here means 2 * alpha.
    alpha: 0.05,
    alphaFDR: null,

    // A cell is only TESTED if the full set has this many counts in it. A
    // cell with 4 fixes in 25 seasons cannot produce a distinguishable
    // subset-minus-all difference whatever the subset does, and leaving it in
    // the family would only raise m. It is a property of the full archive,
    // not of the subset, so it cannot be tuned toward a result.
    minCellCount: 10,

    // Sample-size guards (see the 'insufficient' branches in compare()).
    minSeasons: 5,
    cautionSeasons: 8,
    minPoolSeasons: 8,
    minEvents: 20,

    // Season bookkeeping (see compare()).
    seasons: null,
    subsetSeasons: null,

    // Seasons before this are dropped from BOTH the subset and the baseline
    // before anything is binned. This exists because a partially observed
    // season is not a quiet season, and nothing downstream can tell the
    // difference: this archive's Pacific record starts in Feb 2002 and its
    // Atlantic record in Sep 2003, so its first three seasons hold 1, 22 and
    // 38 events against 62-115 for every complete one. Left in, they do not
    // merely add noise, they manufacture signal - compositing the 12 earliest
    // seasons against the whole archive flags 11 FDR-significant cells in the
    // shape field on a split with no physical reason to differ, and dropping
    // just those three seasons takes it to 0. Pass the archive's own
    // recordStart (HF_DATA.recordStart); null means "use everything", which
    // is only right for an archive with no ramp-up, and says so in warnings.
    minSeason: null,

    // How the events design permutes labels. 'auto' (the default) shuffles
    // only WITHIN a (season, month, basin) block; 'season' shuffles anywhere
    // in the season, which is what this file did before and is almost always
    // wrong for an index-defined subset.
    //
    // Why: the events design asks "if these events had been labelled at
    // random, how often would the track look this different?" Permuting
    // freely within a season answers that only if every event in the season
    // is exchangeable - and they are not. The daily indices persist for 1-2
    // weeks, so a tercile subset is clustered in time, and it inherits a
    // month and basin mix that differs from the archive's: NAO-lower events
    // are 18.4% October against the archive's 9.1%, and 8.4% February
    // against 17.2%. The storm track moves a long way between October and
    // February, so a free permutation attributes that seasonal difference to
    // the index. Blocking by month and basin holds both fixed under the null,
    // so what remains is the index's own effect rather than when and where
    // its events happened to fall.
    //
    // The cost is power: blocks are smaller, so fewer distinct permutations
    // exist and the test is more conservative. That is the right trade - a
    // confounded significant result is worse than an honest null.
    stratify: 'auto',
    design: 'auto'
  };

  function resolveOptions(opts) {
    var o = {}, k;
    for (k in DEFAULTS) o[k] = DEFAULTS[k];
    if (opts) for (k in opts) if (opts[k] !== undefined) o[k] = opts[k];
    if (o.alphaFDR == null) o.alphaFDR = 2 * o.alpha;
    if (o.unit !== 'fixes' && o.unit !== 'events') throw new Error("unit must be 'fixes' or 'events'");
    if (o.design !== 'auto' && o.design !== 'seasons' && o.design !== 'events') {
      throw new Error("design must be 'auto', 'seasons' or 'events'");
    }
    if (!(o.latStep > 0 && o.latStep <= 90)) throw new Error('latStep must be in (0, 90]');
    if (o.stratify !== 'auto' && o.stratify !== 'season' && typeof o.stratify !== 'function') {
      throw new Error("stratify must be 'auto', 'season' or a function(low) -> key");
    }
    if (o.minSeason != null && !isFinite(o.minSeason)) throw new Error('minSeason must be a number or null');
    if (!isFinite(o.seed)) throw new Error('seed must be a finite number');
    if (!(o.iterations >= 1) || o.iterations !== Math.floor(o.iterations)) {
      throw new Error('iterations must be a positive integer');
    }
    return o;
  }

  /* --------------------------------------------------------------- PRNG */

  /** mulberry32: 32 bits of state, passes the usual small-battery tests, and
      is a dozen lines, which is why it is here instead of anything fancier.
      The bootstrap draws ~10^6 integers per run, far below where its period
      or quality could matter. Same seed -> same sequence in every browser and
      in Node, which Math.random() cannot promise and a test cannot use. */
  function makeRng(seed) {
    var a = Math.floor(seed) >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* --------------------------------------------------------- equal-area grid */

  /** Build the grid. WHY this scheme and not the alternatives:

      A regular lat/lon grid has cells whose area shrinks as cos(lat). A
      5-degree-wide cell at 60N is half the area of one at 30N, so a map of
      raw counts per cell understates the high-latitude storm belt by that
      factor, and (worse for a DIFFERENCE map) the noise level changes with
      latitude too: a cell at 65N sees a quarter of the fixes a cell at 30N
      does, for the same true density. This archive lives at 40-70N, where
      the distortion is a factor of ~2.

      Weighting each regular cell by 1/cos(lat) fixes the density estimate
      but not the noise: the small cells are still small samples, so their
      weighted values are the noisy ones and the field's variance is no longer
      uniform, which muddies both the eye and the multiple-comparisons
      correction. Cells that actually have equal area have equal expected
      counts under uniform density and comparable noise everywhere.

      So: bands of constant latitude height, each cut into
      round(bandArea / targetArea) longitude cells. The area of a band is
      exact (2*pi*R^2*(sin lat1 - sin lat0)), so the only departure from
      equal area is the integer rounding of the cell count: <= 0.5/n of the
      cell area, under 1% in the storm belt (the occupied cells run
      196,000-200,000 km^2), larger only in the polar caps (n = 3 near the
      pole), which hold no fixes. Each cell's exact area is
      reported so a caller that cares can divide by it. The alternatives that
      are exactly equal-area (HEALPix, icosahedral) have non-rectangular cells
      with no clean rows, which would make drawing and hit-testing a project
      of its own for a gain of one percent.

      Cell index spaces are global and stable: the same lat/lon maps to the
      same integer for given (latStep, lonOrigin), so two comparisons can be
      overlaid or differenced cell by cell. */
  function makeGrid(latStep, lonOrigin) {
    if (latStep == null) latStep = DEFAULTS.latStep;
    if (lonOrigin == null) lonOrigin = DEFAULTS.lonOrigin;
    var nBands = Math.max(1, Math.round(180 / latStep));
    var step = 180 / nBands;                            // snap so bands tile pole to pole exactly
    var target = (step * DEG) * (step * DEG);           // steradians: a step x step square at the equator
    var bands = [], offset = 0, b;
    for (b = 0; b < nBands; b++) {
      var lat0 = -90 + b * step;
      var lat1 = b === nBands - 1 ? 90 : lat0 + step;
      var sr = 2 * Math.PI * (Math.sin(lat1 * DEG) - Math.sin(lat0 * DEG));
      var n = Math.max(1, Math.round(sr / target));
      bands.push({ lat0: lat0, lat1: lat1, n: n, dlon: 360 / n, offset: offset,
                   areaKm2: (sr / n) * EARTH_R_KM * EARTH_R_KM });
      offset += n;
    }
    var nCells = offset;

    /** Cell for a point, or -1 for a point with unusable coordinates. */
    function cellIndex(lat, lon) {
      if (typeof lat !== 'number' || typeof lon !== 'number' ||
          !isFinite(lat) || !isFinite(lon) || lat < -90 || lat > 90) return -1;
      var bi = Math.floor((lat + 90) / step);
      if (bi >= nBands) bi = nBands - 1;                // lat == 90 exactly
      if (bi < 0) bi = 0;
      var band = bands[bi];
      // Longitude is reduced modulo 360 relative to the seam BEFORE it is
      // divided into cells. +179.9 and -179.9 are 0.2 degrees apart; in the
      // seam's frame they are 159.9 and 160.1, adjacent or inside one cell,
      // as they should be. 180 and -180 are the same meridian and land in the
      // same cell. The cell that contains the dateline is a single cell.
      var l = lon - lonOrigin;
      l -= 360 * Math.floor(l / 360);                   // [0, 360)
      var j = Math.floor(l / band.dlon);
      if (j >= band.n) j = band.n - 1;                  // float edge: l a hair under 360
      return band.offset + j;
    }

    /** Geometry of cell `id`. lon0 is the WEST edge in [-180, 180); the east
        edge is lon0 + dlon and may exceed 180 (a dateline cell), so a
        renderer can draw it as one polygon in unwrapped longitude. */
    function cellInfo(id) {
      var bi = 0;
      while (bi < nBands - 1 && id >= bands[bi + 1].offset) bi++;
      var band = bands[bi], j = id - band.offset;
      var west = lonOrigin + j * band.dlon;
      west -= 360 * Math.floor((west + 180) / 360);     // -> [-180, 180)
      var c = west + band.dlon / 2;
      c -= 360 * Math.floor((c + 180) / 360);
      return { id: id, band: bi, lat0: band.lat0, lat1: band.lat1,
               latC: (band.lat0 + band.lat1) / 2, lon0: west, dlon: band.dlon,
               lonC: c, areaKm2: band.areaKm2,
               crossesDateline: west < 180 && west + band.dlon > 180 };
    }

    return { latStep: step, nBands: nBands, nCells: nCells, lonOrigin: lonOrigin,
             bands: bands, cellIndex: cellIndex, cellInfo: cellInfo };
  }

  /* ------------------------------------------------------------- binning */

  function seasonKey(s) { return typeof s === 'object' && s ? s.start : s; }

  /** Season ids from either [2001, 2002, ...] or HF_DATA.seasons'
      [{start: 2001, label: '2001-02'}, ...], sorted and de-duplicated. */
  function normaliseSeasons(list) {
    var seen = {}, out = [];
    for (var i = 0; i < list.length; i++) {
      var s = seasonKey(list[i]);
      if (typeof s === 'number' && isFinite(s) && !seen[s]) { seen[s] = true; out.push(s); }
    }
    out.sort(function (a, b) { return a - b; });
    return out;
  }

  /** Turn lows into per-event sparse cell counts. Returns
      {events: [{season, ids[], counts[], total}], droppedFixes, noSeason}.
      Events with no usable fixes are KEPT (they still count as events, just
      with no cells), because dropping them would make n_events disagree with
      the table the user is looking at. */
  /** The block a permutation may move an event within. Month comes from the
      event's own start date rather than its season, because the season says
      nothing about where in the cool season the storm sat - which is exactly
      the thing being held fixed. Basin is included because the two basins'
      tracks are in different places, so a subset drawn disproportionately
      from one would differ from the archive wherever the other one lives. */
  function stratumKey(low, o) {
    if (o.stratify === 'season' || !o.stratify) return String(low.season);
    if (typeof o.stratify === 'function') return String(o.stratify(low));
    var mo = Math.floor((low.start || 0) / 10000) % 100;
    return low.season + '|' + (mo || 0) + '|' + (low.basin || '?');
  }

  function binLows(lows, grid, o) {
    var catSet = null, i, f;
    if (o.cats) { catSet = {}; for (i = 0; i < o.cats.length; i++) catSet[o.cats[i]] = true; }
    var events = [], dropped = 0, noSeason = 0;
    for (i = 0; i < lows.length; i++) {
      var low = lows[i];
      if (typeof low.season !== 'number' || !isFinite(low.season)) { noSeason++; continue; }
      var counts = {}, fixes = low.fixes || [];
      for (f = 0; f < fixes.length; f++) {
        var fx = fixes[f];
        if (catSet && !catSet[fx.cat]) continue;
        var id = grid.cellIndex(fx.lat, fx.lon);
        if (id < 0) { dropped++; continue; }
        // 'events' counts a cell once per event however many fixes sit in it.
        counts[id] = o.unit === 'events' ? 1 : (counts[id] || 0) + 1;
      }
      var ids = Object.keys(counts).map(Number).sort(function (a, b) { return a - b; });
      var cnt = [], total = 0;
      for (var k = 0; k < ids.length; k++) { cnt.push(counts[ids[k]]); total += counts[ids[k]]; }
      events.push({ season: low.season, stratum: stratumKey(low, o),
                    ids: ids, counts: cnt, total: total });
    }
    return { events: events, droppedFixes: dropped, noSeason: noSeason };
  }

  function distinctSeasons(events) {
    var seen = {}, out = [];
    for (var i = 0; i < events.length; i++) {
      if (!seen[events[i].season]) { seen[events[i].season] = true; out.push(events[i].season); }
    }
    return out.sort(function (a, b) { return a - b; });
  }

  /** Single-set gridded density: counts per equal-area cell, per season.
      `rate` is counts per season (the denominator is the number of seasons
      in `opts.seasons` if given, else the distinct seasons that appear in
      `lows` - pass the archive's list when the set might not touch every
      season, or a set that skipped three quiet winters would look busier
      than it is). `perMkm2` is rate per million km^2, the unit that stays
      comparable if someone changes latStep. */
  function density(lows, opts) {
    var o = resolveOptions(opts);
    var grid = makeGrid(o.latStep, o.lonOrigin);
    var b = binLows(lows, grid, o);
    var seasons = o.seasons ? normaliseSeasons(o.seasons) : distinctSeasons(b.events);
    var nSeasons = seasons.length;
    var byCell = {}, e, j;
    for (e = 0; e < b.events.length; e++) {
      var ev = b.events[e];
      for (j = 0; j < ev.ids.length; j++) {
        var c = byCell[ev.ids[j]] || (byCell[ev.ids[j]] = { count: 0, events: 0, seasons: {} });
        c.count += ev.counts[j];
        c.events++;
        c.seasons[ev.season] = true;
      }
    }
    var cells = [], total = 0;
    Object.keys(byCell).map(Number).sort(function (a, b2) { return a - b2; }).forEach(function (id) {
      var info = grid.cellInfo(id), c = byCell[id];
      info.count = c.count;
      info.events = c.events;
      info.seasons = Object.keys(c.seasons).length;
      info.rate = nSeasons ? c.count / nSeasons : null;
      info.perMkm2 = nSeasons ? info.rate * 1e6 / info.areaKm2 : null;
      total += c.count;
      cells.push(info);
    });
    return { grid: grid, unit: o.unit, cells: cells, nEvents: b.events.length,
             nSeasons: nSeasons, total: total, droppedFixes: b.droppedFixes,
             droppedEvents: b.noSeason };
  }

  /* ----------------------------------------------------------------- FDR */

  /** Benjamini-Hochberg step-up procedure.

      Sort the m p-values ascending; find the LARGEST rank i with
      p_(i) <= (i/m) * alphaFDR; flag every cell with p <= p_(i). Step-up
      (not "flag p_(i) while it passes") matters: a cell that misses its own
      line is still flagged if a larger-ranked p clears the line above it.
      `q` is the BH-adjusted p-value (the smallest alphaFDR at which the cell
      would be flagged), so a UI can offer a slider without re-running
      anything, and q <= alphaFDR holds exactly for the flagged cells.

      Why FDR and not something else, for THIS field:
        - Per-cell p < alpha is what the brief warns about: ~alpha*m cells
          light up on pure noise (the tests measure it).
        - Bonferroni/Holm control the chance of ANY false cell. With ~150
          cells and a 4-5 cell-wide feature that is a threshold of p < 3e-4;
          a real 10-degree southward shift in a middling subset would never
          clear it. It answers "is every starred cell real", which is not the
          forecaster's question; theirs is "is the pattern real".
        - A global/field-level test (Livezey & Chen) says whether the field
          as a whole is distinguishable from noise but not WHERE, and the
          where is the product. FDR keeps the where and bounds the fraction
          of stippled cells that are false.
        - BH is valid for independent and positively dependent tests
          (Benjamini-Yekutieli 2001); neighbouring cells share their storms,
          so dependence is positive, which is the case it was proved for.
          Wilks (2016) shows it stays well-behaved for spatially correlated
          climate fields; with alphaFDR = 2*alpha_global it matches the
          intended global level. Its documented weakness (conservative under
          strong correlation) errs in the direction of fewer stipples.

      `p` may contain NaN/null for cells that were not tested; they are
      skipped and come back NaN / false and do not count toward m. */
  function fdr(p, alphaFDR) {
    var n = p.length, idx = [], i;
    for (i = 0; i < n; i++) {
      if (typeof p[i] === 'number' && isFinite(p[i])) idx.push(i);
    }
    idx.sort(function (a, b) { return p[a] - p[b] || a - b; });
    var m = idx.length;
    var q = new Array(n), reject = new Array(n);
    for (i = 0; i < n; i++) { q[i] = NaN; reject[i] = false; }
    var run = 1, r, kmax = -1;
    for (r = m - 1; r >= 0; r--) {                         // adjusted p: running min from the top
      run = Math.min(run, p[idx[r]] * m / (r + 1));
      q[idx[r]] = run;
    }
    for (r = 0; r < m; r++) {
      if (p[idx[r]] <= alphaFDR * (r + 1) / m + 1e-12) kmax = r;
    }
    var threshold = kmax >= 0 ? p[idx[kmax]] : 0;
    for (r = 0; r <= kmax; r++) reject[idx[r]] = true;
    return { q: q, reject: reject, threshold: threshold, m: m, nReject: kmax + 1,
             alphaFDR: alphaFDR };
  }

  /* ------------------------------------------------------------- compare */

  /** Compare `subsetLows` against `allLows`. Both are arrays of decoded lows;
      the subset must be CONTAINED in the full set (it is subset-minus-all, and
      the null depends on the subset being part of the whole). Options are
      DEFAULTS above, plus:

        seasons        the archive's season list ([2001, ...] or
                       HF_DATA.seasons). Sets N, the pool the null draws from.
                       Omit it and N is the number of seasons that have events.
        subsetSeasons  the seasons that DEFINE the subset (e.g. the 8 El Nino
                       winters). Optional; without it they are the seasons the
                       subset's events fall in. Pass it when a defining season
                       might have produced no events, so that season still
                       counts in the per-season denominator.
        design         'auto' | 'seasons' | 'events' (below)

      Returns an object whose shape is documented at the top of this file.

      THE FIELDS. Two are computed, with the same machinery, because the
      question "has the track shifted?" has two halves and a single field
      confuses them.

        rate   fixes (or events) per season per cell. diff = subset - all.
               Answers "is this cell busier or quieter". Difference rather
               than ratio is the primary, deliberately: the question is WHERE
               the extra storms are, and absolute counts rank that. A ratio
               turns 0.2 vs 0.1 fixes per season (noise) into "2x", and the
               busiest part of the belt (where the shift matters) into a
               modest number. `ratio` is reported but is null in cells the
               full set barely visits.
        shape  the subset's PATTERN at the archive's overall activity:
               (subset cell / subset total) * (all total / N). The difference
               from `all` is what is left once "this subset has more storms
               overall" is divided out, so a dipole (more here, fewer there)
               reads as a dipole instead of being buried under a uniform
               positive offset. Use `shape` to answer "did the track MOVE";
               use `rate` to answer "was it busier". For an events-design
               subset (a slice of the archive, so rate is trivially lower
               everywhere) `shape` is the meaningful one.

      TWO DESIGNS (chosen by `design`, default detected):

        'seasons'  The subset is whole seasons. Null (Efron & Tibshirani's
                   two-sample bootstrap test): pool the N seasons; each draw
                   builds a pseudo-subset of k seasons AND a pseudo-rest of
                   N-k, both sampled WITH replacement from the pool, forms the
                   pseudo-all from the two, and recomputes the field. The
                   pseudo-all contains the pseudo-subset, as the real all
                   contains the real subset, which is what makes the null's
                   spread right: Var(subset - all) is (1 - k/N) times what
                   comparing against an independent sample would give. A null
                   that ignored the overlap would be too wide and miss real
                   shifts.
                   Why a NULL (resample under "no difference") and not a
                   bootstrap confidence interval around the observed
                   difference: a CI is built by resampling the subset's own
                   seasons, and a cell where the subset happens to have zero
                   fixes then has zero in every resample and "excludes 0" for
                   free. Counts here are sparse, so that is not a corner case.
                   A null resampled from the pool can show the cell nonzero.
        'events'   The subset is a slice of events that cuts across seasons
                   (MJO phase). There is no season to resample, and drawing
                   the subset's own events with replacement would be exactly
                   the independence error this module exists to avoid. The
                   null instead keeps every season's event count and its
                   number of subset events, and re-deals which of that
                   season's events are labelled "subset" (a within-season
                   permutation). That holds the season's background state
                   fixed and asks only whether the label matters. It does not
                   model dependence BETWEEN events of one season beyond that
                   (two storms from one MJO episode), so treat it as a
                   floor on the real uncertainty. */
  function compare(allLows, subsetLows, opts) {
    var o = resolveOptions(opts);
    var grid = makeGrid(o.latStep, o.lonOrigin);

    // Drop incomplete early seasons from both sides before any binning, so the
    // baseline, the subset and the resampling pool all see the same period.
    // Filtering later would leave the bootstrap drawing from seasons the
    // observed field never contained.
    var excluded = 0, allIn = allLows, subIn = subsetLows, poolIn = o.seasons, subSeasIn = o.subsetSeasons;
    if (o.minSeason != null) {
      var keep = function (l) { return l && isFinite(l.season) && l.season >= o.minSeason; };
      allIn = []; for (var ai = 0; ai < (allLows ? allLows.length : 0); ai++) {
        if (keep(allLows[ai])) allIn.push(allLows[ai]); else excluded++;
      }
      subIn = []; for (var si = 0; si < (subsetLows ? subsetLows.length : 0); si++) {
        if (keep(subsetLows[si])) subIn.push(subsetLows[si]);
      }
      var keepSeason = function (x) { var v = seasonKey(x); return isFinite(v) && v >= o.minSeason; };
      if (poolIn) poolIn = poolIn.filter(keepSeason);
      if (subSeasIn) subSeasIn = subSeasIn.filter(keepSeason);
    }
    o = (function (base) { var c = {}, k; for (k in base) c[k] = base[k];
                           c.seasons = poolIn; c.subsetSeasons = subSeasIn; return c; })(o);

    var allB = binLows(allIn, grid, o);
    var subB = binLows(subIn, grid, o);
    var allEv = allB.events, subEv = subB.events;
    var i, j, e;

    var out = {
      status: 'ok', reason: null, reliability: 'ok', warnings: [],
      design: null, identical: false,
      options: { latStep: grid.latStep, lonOrigin: o.lonOrigin, unit: o.unit, cats: o.cats,
                 iterations: o.iterations, seed: o.seed, alpha: o.alpha, alphaFDR: o.alphaFDR,
                 minCellCount: o.minCellCount, minSeason: o.minSeason },
      n: null, cells: [],
      summary: { rate: emptySummary(o), shape: emptySummary(o) },
      grid: { latStep: grid.latStep, nBands: grid.nBands, nCells: grid.nCells,
              lonOrigin: o.lonOrigin }
    };
    if (o.minSeason != null) {
      out.excludedBelowMinSeason = excluded;
      if (excluded) {
        out.warnings.push(excluded + ' event(s) in seasons before ' + o.minSeason +
                          ' were excluded as incompletely observed.');
      }
    } else {
      out.excludedBelowMinSeason = 0;
      out.warnings.push('No minSeason given: any partially observed early seasons are included, ' +
                        'which can manufacture apparent signal. Pass the archive\'s recordStart.');
    }
    if (allB.noSeason || subB.noSeason) {
      out.warnings.push((allB.noSeason + subB.noSeason) + ' event(s) have no numeric season and were ignored.');
    }
    if (allB.droppedFixes || subB.droppedFixes) {
      out.warnings.push((allB.droppedFixes + subB.droppedFixes) + ' fix(es) with unusable lat/lon were ignored.');
    }

    /* ---- season bookkeeping ---- */
    var pool = o.seasons ? normaliseSeasons(o.seasons) : distinctSeasons(allEv);
    var inPool = {};
    for (i = 0; i < pool.length; i++) inPool[pool[i]] = true;
    var extra = distinctSeasons(allEv).concat(distinctSeasons(subEv));
    for (i = 0; i < extra.length; i++) {
      if (!inPool[extra[i]]) {
        inPool[extra[i]] = true; pool.push(extra[i]);
        out.warnings.push('Season ' + extra[i] + ' has events but is not in the season list; added to the pool.');
      }
    }
    pool.sort(function (a, b) { return a - b; });
    var N = pool.length;
    var seasonIdx = {};
    for (i = 0; i < N; i++) seasonIdx[pool[i]] = i;

    var allPer = zeros(N), subPer = zeros(N);
    for (e = 0; e < allEv.length; e++) allPer[seasonIdx[allEv[e].season]]++;
    for (e = 0; e < subEv.length; e++) subPer[seasonIdx[subEv[e].season]]++;

    var nSubFix = 0, nAllFix = 0;
    for (e = 0; e < subEv.length; e++) nSubFix += subEv[e].total;
    for (e = 0; e < allEv.length; e++) nAllFix += allEv[e].total;
    var contributing = 0;
    for (i = 0; i < N; i++) if (subPer[i] > 0) contributing++;

    out.n = { events: subEv.length, seasons: contributing, fixes: nSubFix,
              allEvents: allEv.length, allSeasons: N, allFixes: nAllFix,
              subsetSeasons: null, unit: o.unit };

    if (!subEv.length || !allEv.length) {
      out.status = 'empty'; out.reliability = 'none';
      out.reason = !allEv.length ? 'The full set has no events.' : 'The subset has no events.';
      return out;
    }

    /* ---- is the subset really inside the full set? ---- */
    for (i = 0; i < N; i++) {
      if (subPer[i] > allPer[i]) {
        return invalid(out, 'Season ' + pool[i] + ' has more subset events (' + subPer[i] +
                       ') than full-set events (' + allPer[i] + '): the subset is not contained in the full set.');
      }
    }

    /* ---- which design? ---- */
    var subSeasonList = null;
    if (o.subsetSeasons) {
      subSeasonList = normaliseSeasons(o.subsetSeasons);
      for (i = 0; i < subSeasonList.length; i++) {
        if (!inPool[subSeasonList[i]]) {
          return invalid(out, 'subsetSeasons names season ' + subSeasonList[i] + ', which is not in the season list.');
        }
      }
    } else {
      subSeasonList = [];
      for (i = 0; i < N; i++) if (subPer[i] > 0) subSeasonList.push(pool[i]);
    }
    var isDefining = {};
    for (i = 0; i < subSeasonList.length; i++) isDefining[subSeasonList[i]] = true;
    var whole = true;
    for (i = 0; i < N; i++) {
      var want = isDefining[pool[i]] ? allPer[i] : 0;
      if (subPer[i] !== want) { whole = false; break; }
    }
    var design = o.design === 'auto' ? (whole ? 'seasons' : 'events') : o.design;
    if (design === 'seasons' && !whole) {
      return invalid(out, "design 'seasons' needs the subset to be every event of its seasons, but at least one " +
                     "season is only partly in it. Use design 'events' (or leave it on 'auto').");
    }
    out.design = design;
    var k = design === 'seasons' ? subSeasonList.length : contributing;
    out.n.seasons = k;
    out.n.subsetSeasons = subSeasonList.map(function (s) { return s; });
    var denom = design === 'seasons' ? k : N;           // seasons of EXPOSURE for the subset's rate

    // The full set, trivially.
    var identical = design === 'seasons' && k === N;

    /* ---- compact the grid to the cells anyone ever visited ---- */
    var active = {}, ids = [];
    for (e = 0; e < allEv.length; e++) {
      for (j = 0; j < allEv[e].ids.length; j++) active[allEv[e].ids[j]] = true;
    }
    for (e = 0; e < subEv.length; e++) {
      for (j = 0; j < subEv[e].ids.length; j++) active[subEv[e].ids[j]] = true;
    }
    ids = Object.keys(active).map(Number).sort(function (a, b) { return a - b; });
    var C = ids.length, compact = {};
    for (i = 0; i < C; i++) compact[ids[i]] = i;

    var T = zeros(C), S = zeros(C), Tevents = zeros(C), Sevents = zeros(C);
    var Ttot = 0, Stot = 0;
    for (e = 0; e < allEv.length; e++) {
      for (j = 0; j < allEv[e].ids.length; j++) {
        T[compact[allEv[e].ids[j]]] += allEv[e].counts[j];
        Tevents[compact[allEv[e].ids[j]]]++;
      }
      Ttot += allEv[e].total;
    }
    var subSeasonsInCell = [];
    for (i = 0; i < C; i++) subSeasonsInCell.push(null);
    for (e = 0; e < subEv.length; e++) {
      for (j = 0; j < subEv[e].ids.length; j++) {
        var ci = compact[subEv[e].ids[j]];
        S[ci] += subEv[e].counts[j];
        Sevents[ci]++;
        if (!subSeasonsInCell[ci]) subSeasonsInCell[ci] = {};
        subSeasonsInCell[ci][subEv[e].season] = true;
      }
      Stot += subEv[e].total;
    }
    for (i = 0; i < C; i++) {
      if (S[i] > T[i]) {
        return invalid(out, 'Cell ' + ids[i] + ' has more subset counts than full-set counts: ' +
                       'the subset is not contained in the full set.');
      }
    }

    // Every season is a defining season, so the "rest" the null would resample
    // is empty and the subset IS the full set - provided it really is the same
    // events. Same season counts with fewer fixes means different events,
    // which this design cannot test; refuse rather than call it identical.
    if (identical && Stot !== Ttot) {
      return invalid(out, 'The subset spans every season but is not the full set; ' +
                     "there is no season-level contrast to resample. Use design 'events'.");
    }
    out.identical = identical;

    /* ---- observed fields ---- */
    var tested = [], testedIdx = [], tpos = {};
    for (i = 0; i < C; i++) {
      var t = T[i] >= o.minCellCount;
      tested.push(t);
      if (t) { tpos[i] = testedIdx.length; testedIdx.push(i); }
    }
    var CT = testedIdx.length;
    var shapeOk = Stot > 0;
    var allRate = [], subRate = [], dRate = [], subShape = [], dShape = [];
    for (i = 0; i < C; i++) {
      allRate.push(T[i] / N);
      subRate.push(S[i] / denom);
      dRate.push(S[i] / denom - T[i] / N);
      var sh = shapeOk ? (S[i] / Stot) * (Ttot / N) : null;
      subShape.push(sh);
      dShape.push(shapeOk ? sh - T[i] / N : null);
    }

    /* ---- guards: say so rather than return a confident-looking map ---- */
    var pRate = null, pShape = null, inference = !identical;
    if (!identical) {
      var why = guard(design, N, k, subEv.length, o);
      if (why) {
        out.status = 'insufficient'; out.reliability = 'none'; out.reason = why;
        inference = false;
      } else if (design === 'seasons' && k < o.cautionSeasons) {
        out.reliability = 'low';
        out.warnings.push('Only ' + k + ' seasons define this subset. The test is valid, but only a large shift ' +
                          'can be distinguished from noise; absence of stippling is weak evidence of no shift.');
      }
      if (inference && CT === 0) {
        inference = false;
        out.warnings.push('No cell has ' + o.minCellCount + ' or more counts in the full set; nothing was tested.');
      }
    }
    if (inference && o.iterations + 1 < CT / o.alphaFDR) {
      out.warnings.push('iterations (' + o.iterations + ') is below tested cells / alphaFDR (' +
                        Math.ceil(CT / o.alphaFDR) + '): a single very strong cell could not be flagged by FDR. ' +
                        'Raise iterations.');
    }

    var cellP = { rate: nanArr(C), shape: nanArr(C) };
    if (identical) {
      for (i = 0; i < CT; i++) { cellP.rate[testedIdx[i]] = 1; cellP.shape[testedIdx[i]] = 1; }
    } else if (inference) {
      // The events design permutes within strata, so it needs its own index
      // and its own per-stratum subset counts. The season-based subPer above
      // stays as it is: the season design, the whole-season detection and the
      // validation checks all still reason in seasons.
      var stratumIdx = {}, nStrata = 0, subPerStratum = null, ei;
      if (design !== 'seasons') {
        for (ei = 0; ei < allEv.length; ei++) {
          if (stratumIdx[allEv[ei].stratum] === undefined) stratumIdx[allEv[ei].stratum] = nStrata++;
        }
        subPerStratum = zeros(nStrata);
        for (ei = 0; ei < subEv.length; ei++) {
          var sk = stratumIdx[subEv[ei].stratum];
          if (sk !== undefined) subPerStratum[sk]++;
        }
        out.strata = { n: nStrata, scheme: (typeof o.stratify === 'function' ? 'custom' : o.stratify) };
        if (o.stratify !== 'season') {
          out.warnings.push('Labels were permuted within (season, month, basin) blocks, so the null holds the ' +
                            "subset's seasonal and basin mix fixed. Without that, a subset drawn disproportionately " +
                            'from one month or basin looks like an index effect.');
        }
      }
      var res = design === 'seasons'
        ? nullSeasons(allEv, seasonIdx, N, k, testedIdx, compact, tpos, CT, dRate, dShape, shapeOk, o)
        : nullEvents(allEv, subPerStratum, stratumIdx, N, testedIdx, compact, tpos, CT, T, Ttot, dRate, dShape, shapeOk, o);
      for (i = 0; i < CT; i++) {
        cellP.rate[testedIdx[i]] = (1 + res.exRate[i]) / (o.iterations + 1);
        cellP.shape[testedIdx[i]] = shapeOk ? (1 + res.exShape[i]) / (o.iterations + 1) : NaN;
      }
    }

    var fdrRate = fdr(cellP.rate, o.alphaFDR);
    var fdrShape = fdr(cellP.shape, o.alphaFDR);

    /* ---- assemble ---- */
    var areas = [];
    for (i = 0; i < C; i++) {
      var info = grid.cellInfo(ids[i]);
      areas.push(info.areaKm2);
      var cell = info;
      cell.nSubset = S[i];                 // counts in the subset (unit: fixes or events)
      cell.nAll = T[i];
      cell.nSubsetEvents = Sevents[i];     // distinct subset events that touched the cell
      cell.nSubsetSeasons = subSeasonsInCell[i] ? Object.keys(subSeasonsInCell[i]).length : 0;
      cell.nAllEvents = Tevents[i];
      cell.tested = tested[i];
      cell.rate = fieldCell(subRate[i], allRate[i], dRate[i], T[i], cellP.rate[i], fdrRate, i, o, inference, identical, info.areaKm2);
      cell.shape = fieldCell(subShape[i], allRate[i], dShape[i], T[i], cellP.shape[i], fdrShape, i, o, inference, identical, info.areaKm2);
      out.cells.push(cell);
    }
    out.summary.rate = summarise(cellP.rate, fdrRate, o, inference || identical);
    out.summary.shape = summarise(cellP.shape, fdrShape, o, (inference && shapeOk) || identical);
    out.grid.nActive = C;
    out.grid.nTested = CT;
    out.grid.cellAreaKm2 = { min: Math.min.apply(null, areas), max: Math.max.apply(null, areas) };
    out.inference = inference || identical;
    return out;
  }

  /* ------------------------------------------------------------ the nulls */

  /** The decision rule for "too few to mean anything". It is a decision with
      numbers behind it, not a theorem; the numbers come from the synthetic
      power runs in tests/composite (reported with the module).

      seasons design, k < minSeasons (5): the subset's field is the mean of k
      season fields, so one unusual winter is 1/k of it, and at k <= 4 a single
      season is a quarter or more of the answer: whatever the map shows
      cannot be told apart from "those particular seasons" versus "the phase".
      Calibration also degrades as k shrinks, because the sampling
      distribution of a mean of k heavy-tailed season counts is nowhere near
      Normal and the cells' thresholds sit in a tail that k draws barely
      visit. The pool must also be big enough to stand in for the population
      of seasons (minPoolSeasons, 8).
      events design: the null is exact for any size, but a subset that has
      fewer than minEvents events, or that lives in fewer than minSeasons
      seasons, has too little to say. */
  function guard(design, N, k, nEvents, o) {
    if (N < o.minPoolSeasons) {
      return 'Only ' + N + ' seasons are available to resample from (need ' + o.minPoolSeasons +
             '): a season-level bootstrap has nothing to draw from.';
    }
    if (k < o.minSeasons) {
      return 'Only ' + k + ' season' + (k === 1 ? '' : 's') + ' ' + (design === 'seasons' ? 'define' : 'contribute to') +
             ' this subset (need ' + o.minSeasons + '): a season-level bootstrap on ' + k +
             ' season' + (k === 1 ? '' : 's') + ' cannot separate the effect from those seasons.';
    }
    if (design === 'events' && nEvents < o.minEvents) {
      return 'Only ' + nEvents + ' events in the subset (need ' + o.minEvents + ').';
    }
    return null;
  }

  /** Seasons design null. Returns exceedance counts, per TESTED cell, of
      |null difference| >= |observed difference| for both fields. */
  function nullSeasons(allEv, seasonIdx, N, k, testedIdx, compact, tpos, CT, dRate, dShape, shapeOk, o) {
    var W = [], tot = zeros(N), s, e, j, c;
    for (s = 0; s < N; s++) W.push(zeros(CT));
    for (e = 0; e < allEv.length; e++) {
      s = seasonIdx[allEv[e].season];
      tot[s] += allEv[e].total;
      for (j = 0; j < allEv[e].ids.length; j++) {
        var cc = compact[allEv[e].ids[j]];
        if (tpos[cc] !== undefined) W[s][tpos[cc]] += allEv[e].counts[j];
      }
    }
    var obsR = zeros(CT), obsS = zeros(CT);
    for (c = 0; c < CT; c++) {
      obsR[c] = Math.abs(dRate[testedIdx[c]]);
      obsS[c] = shapeOk ? Math.abs(dShape[testedIdx[c]]) : Infinity;
    }
    var exR = new Float64Array(CT), exS = new Float64Array(CT);
    var rng = makeRng(o.seed), B = o.iterations, EPS = 1e-9;
    var SS = new Float64Array(CT), GG = new Float64Array(CT);
    var rest = N - k;
    for (var b = 0; b < B; b++) {
      var stot = 0, gtot = 0, row;
      for (c = 0; c < CT; c++) { SS[c] = 0; GG[c] = 0; }
      for (j = 0; j < k; j++) {
        s = Math.floor(rng() * N); row = W[s]; stot += tot[s];
        for (c = 0; c < CT; c++) SS[c] += row[c];
      }
      for (j = 0; j < rest; j++) {
        s = Math.floor(rng() * N); row = W[s]; gtot += tot[s];
        for (c = 0; c < CT; c++) GG[c] += row[c];
      }
      var ttot = stot + gtot, scale = stot > 0 ? ttot / (N * stot) : 0;
      for (c = 0; c < CT; c++) {
        var tc = (SS[c] + GG[c]) / N;
        if (Math.abs(SS[c] / k - tc) >= obsR[c] - EPS) exR[c]++;
        if (shapeOk && Math.abs(SS[c] * scale - tc) >= obsS[c] - EPS) exS[c]++;
      }
    }
    return { exRate: exR, exShape: exS };
  }

  /** Events design null: within-season permutation of the subset label. */
  /** `subPer` counts subset events per STRATUM, and N is the number of
      SEASONS. The two are deliberately different: strata bound what a
      permutation may move (see the `stratify` option), while rates stay per
      season because that is the unit the whole module reports in. Dividing a
      stratified count by the stratum count instead would silently rescale
      every rate. */
  function nullEvents(allEv, subPer, stratumIdx, N, testedIdx, compact, tpos, CT, T, Ttot, dRate, dShape, shapeOk, o) {
    var byStratum = [], s, e, j, c;
    var S = 0, kkey;
    for (kkey in stratumIdx) if (stratumIdx[kkey] + 1 > S) S = stratumIdx[kkey] + 1;
    for (s = 0; s < S; s++) byStratum.push([]);
    for (e = 0; e < allEv.length; e++) byStratum[stratumIdx[allEv[e].stratum]].push(e);
    var evC = [], evN = [];                           // tested-cell ids / counts per event
    for (e = 0; e < allEv.length; e++) {
      var cs = [], ns = [];
      for (j = 0; j < allEv[e].ids.length; j++) {
        var cc = compact[allEv[e].ids[j]];
        if (tpos[cc] !== undefined) { cs.push(tpos[cc]); ns.push(allEv[e].counts[j]); }
      }
      evC.push(cs); evN.push(ns);
    }
    var tT = zeros(CT), obsR = zeros(CT), obsS = zeros(CT);
    for (c = 0; c < CT; c++) {
      tT[c] = T[testedIdx[c]] / N;
      obsR[c] = Math.abs(dRate[testedIdx[c]]);
      obsS[c] = shapeOk ? Math.abs(dShape[testedIdx[c]]) : Infinity;
    }
    var exR = new Float64Array(CT), exS = new Float64Array(CT);
    var rng = makeRng(o.seed), B = o.iterations, EPS = 1e-9;
    var SS = new Float64Array(CT);
    for (var b = 0; b < B; b++) {
      var stot = 0;
      for (c = 0; c < CT; c++) SS[c] = 0;
      for (s = 0; s < S; s++) {
        var arr = byStratum[s], want = subPer[s], m = arr.length;
        // Partial Fisher-Yates: the first `want` slots of a uniformly dealt
        // permutation are a uniformly random `want`-subset. Reusing the array
        // in whatever order the last draw left it is fine for the same reason.
        for (j = 0; j < want; j++) {
          var pick = j + Math.floor(rng() * (m - j));
          var tmp = arr[j]; arr[j] = arr[pick]; arr[pick] = tmp;
          var ev = arr[j], cs2 = evC[ev], ns2 = evN[ev];
          stot += allEv[ev].total;
          for (var q = 0; q < cs2.length; q++) SS[cs2[q]] += ns2[q];
        }
      }
      var scale = stot > 0 ? Ttot / (N * stot) : 0;
      for (c = 0; c < CT; c++) {
        if (Math.abs(SS[c] / N - tT[c]) >= obsR[c] - EPS) exR[c]++;
        if (shapeOk && Math.abs(SS[c] * scale - tT[c]) >= obsS[c] - EPS) exS[c]++;
      }
    }
    return { exRate: exR, exShape: exS };
  }

  /* ------------------------------------------------------------- helpers */

  function zeros(n) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = 0; return a; }
  function nanArr(n) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = NaN; return a; }

  function invalid(out, reason) {
    out.status = 'invalid'; out.reliability = 'none'; out.reason = reason;
    return out;
  }

  function emptySummary(o) {
    return { nTested: 0, nSigCell: 0, expectedByChance: 0, nSigFDR: 0,
             fdrThreshold: 0, alpha: o.alpha, alphaFDR: o.alphaFDR };
  }

  function fieldCell(subset, all, diff, allCount, p, fd, i, o, inference, identical, areaKm2) {
    var has = typeof p === 'number' && isFinite(p);
    return {
      subset: subset,
      all: all,
      diff: diff,
      diffPerMkm2: diff == null ? null : diff * 1e6 / areaKm2,
      // A ratio against a cell the full set barely visits is noise
      // dressed as a number; null there rather than a huge, confident 3.1x.
      ratio: allCount >= o.minCellCount && subset != null ? subset / all : null,
      p: has ? p : null,
      q: has ? fd.q[i] : null,
      sigCell: has && (inference || identical) ? p <= o.alpha : false,
      sigFDR: has && (inference || identical) ? fd.reject[i] : false
    };
  }

  function summarise(p, fd, o, valid) {
    var m = 0, nCell = 0;
    for (var i = 0; i < p.length; i++) {
      if (typeof p[i] === 'number' && isFinite(p[i])) { m++; if (p[i] <= o.alpha) nCell++; }
    }
    return { nTested: m, nSigCell: valid ? nCell : 0, expectedByChance: o.alpha * m,
             nSigFDR: valid ? fd.nReject : 0, fdrThreshold: valid ? fd.threshold : 0,
             alpha: o.alpha, alphaFDR: o.alphaFDR };
  }

  HF.composite = {
    compare: compare,
    density: density,
    grid: makeGrid,
    rng: makeRng,
    fdr: fdr,
    DEFAULTS: DEFAULTS
  };

})(window.HF);
