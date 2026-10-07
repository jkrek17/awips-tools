/* Storm-track playback: the data/time engine only. No canvas, no DOM, no
   drawing - a renderer asks "what is on screen at time t" once per frame and
   gets plain objects back; colour, width and fading are the renderer's call.

   Built on HF.decode()'s output (util.js): each low is an object whose
   `fixes` are {date, lat, lon, cat, pres}. This file never re-decodes and
   never filters. The page already narrows the archive (basin, seasons,
   months, pressure, explosive-only, event type, text) and hands every other
   view the narrowed array, so playback takes that same array and
   plays exactly what the table and the map are showing - a second copy of
   the filter logic here would drift the first time a filter was added.

   Three modes, two query shapes:

     composite  every season laid on one Jun 1 -> May 31 axis (the climatology
                product: the Pacific belt sliding south through DJF, the
                Atlantic belt tilting NE, the Cape Farewell tip-jet cluster).
     season     one season on the absolute clock, first fix to last fix.
     stepping   season by season, each season's complete tracks (static).

   Mode 3 - stepping is a static frame of each season's COMPLETE tracks, not
   a fast-forward through head and tail. Stepping exists to answer "how did
   2009-10 differ from 2010-11": a question about whole-season pattern (where
   the belt sat, how far south it reached, how many events) that the eye
   answers by comparing two finished pictures. A fast-forward would make the
   viewer hold a whole season in memory before the next began, which is
   exactly what a static frame removes - and it would be mode 2 on autoplay,
   which already exists. Head-and-tail answers "where is this storm going"
   (modes 1 and 2); it is the wrong style for "what did this season look
   like". So mode 3 needs no interpolation and no tail machinery: engine.step(s)
   returns season s's tracks from the filtered set, engine.seasons() the ordered
   list to step through. A season the filters emptied is still in that list
   and still steppable, reporting `empty: true`, so the viewer sees a filter
   remove a whole season rather than wondering why the sequence jumped.
   The crossfade between two steps lives in the RENDERER, not here: it is
   timing and compositing (and wants the prefers-reduced-motion check that
   globe.js already owns), and the engine's contribution is stable `key`s on
   every storm so the renderer can dissolve by matching storms across frames.

   Modes 1 and 2 are "clocks": clock.at(t, tailHours) -> frame. Mode 3 is a
   static frame per season: engine.step(season). Usage:

     var pb = HF.playback.create(filteredLows, { seasons: DATA.seasons });
     var c  = pb.composite();                // or pb.season(2015)
     c.domain                                // {start, end}: scrubber range, hours
     c.label(t)                              // "14 Jan"  /  "14 Jan 2016 06Z"
     var frame = c.at(t, 48);                // {t, storms: [...]}

   Each storm: { key, basin, cls, season, low, lat, lon, pres, tail } where
   lat/lon/pres are the interpolated head at exactly t, `low` is the original
   decoded object (for hit-testing / selection), and `tail` is an oldest ->
   newest array of {lat, lon, pres, age}: age is hours behind the head
   (0 at the head, up to tailHours at the far end) so the renderer can fade
   by age without redoing any time arithmetic. The tail's last point IS the
   head, point for point, so the line meets the dot with no gap.

   Performance: measured, not guessed. Every frame is a linear scan of all
   lows (one compare against a precomputed span each) followed by a binary
   search inside the few that are active. For the full 1,932-lows archive that
   costs well under a millisecond per frame in Node (numbers in the report that
   came with this file), a rounding error next to the canvas draw, so there is
   deliberately no time index to build or invalidate when filters change. */

window.HF = window.HF || {};

(function (HF) {
  'use strict';

  var DEG = Math.PI / 180;

  // Month lengths in season order (Jun ... May) for a LEAP year. The
  // composite axis is deliberately the 366-day one - see compositeHour().
  var SEASON_MONTH_DAYS = [30, 31, 31, 30, 31, 30, 31, 31, 29, 31, 30, 31];
  var SEASON_MONTH_START = [];          // day-of-axis on which each month begins
  (function () {
    var d = 0;
    for (var i = 0; i < 12; i++) { SEASON_MONTH_START.push(d); d += SEASON_MONTH_DAYS[i]; }
  })();
  var COMPOSITE_PERIOD_H = 366 * 24;

  // A fix is a 6-hourly analysis valid at a moment, but 274 of the 1,932 lows
  // (14%) have exactly one fix, and 275 have zero duration. Taken literally
  // those are "active" for an instant and a frame stepping 1 h at a time
  // would hop right over them, so the archive's single-fix events would
  // simply never appear. Treating the lone fix as valid for half an
  // analysis cycle either side (+-3 h) makes it visible for one cycle, which
  // is the honest reading of a 6-hourly analysis. Lows with two or more
  // distinct times keep their exact first-to-last span: the brief's "outside a
  // storm's span excludes it" holds for every storm that has a span.
  var LONE_FIX_HALF_H = 3;

  /* ------------------------------------------------------------- time */

  /** 2002020418 -> {year, month, day, hour}. Integer arithmetic, no Date:
      the engine must give identical answers in every browser time zone and
      Date.UTC would only add a way to be wrong. */
  function parse(n) {
    return {
      year: Math.floor(n / 1000000),
      month: Math.floor(n / 10000) % 100,
      day: Math.floor(n / 100) % 100,
      hour: n % 100
    };
  }

  /** Proleptic-Gregorian day count from 1970-01-01 (Hinnant's days_from_civil),
      exact for any date, leap years and century rules included. */
  function daysFromCivil(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = Math.floor(y / 400);
    var yoe = y - era * 400;
    var mp = (m + 9) % 12;                       // Mar = 0 ... Feb = 11
    var doy = Math.floor((153 * mp + 2) / 5) + d - 1;
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }

  function civilFromDays(z) {
    z += 719468;
    var era = Math.floor(z / 146097);
    var doe = z - era * 146097;
    var yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) -
                          Math.floor(doe / 146096)) / 365);
    var doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    var mp = Math.floor((5 * doy + 2) / 153);
    var d = doy - Math.floor((153 * mp + 2) / 5) + 1;
    var m = mp < 10 ? mp + 3 : mp - 9;
    var y = yoe + era * 400 + (m <= 2 ? 1 : 0);
    return { year: y, month: m, day: d };
  }

  /** YYYYMMDDHH -> absolute hours since 1970-01-01 00Z (the season clock). */
  function toHours(n) {
    var p = parse(n);
    return daysFromCivil(p.year, p.month, p.day) * 24 + p.hour;
  }

  /** Inverse of toHours(), floored to the hour: hours -> YYYYMMDDHH int. */
  function fromHours(h) {
    h = Math.floor(h);
    var days = Math.floor(h / 24);
    var c = civilFromDays(days);
    return c.year * 1000000 + c.month * 10000 + c.day * 100 + (h - days * 24);
  }

  /** Which Jun-May season a calendar date falls in, by the DATE (a Jan event
      belongs to the season that began the previous Jun; season "2001-02" is
      1 Jun 2001 - 31 May 2002). Used for the
      composite axis, which must put a fix where its date says regardless of
      what the archive's own `season` label says: one event (pac:2004200502,
      a mistyped year in the source) carries a label that disagrees with its
      dates, and a handful of early-June events are deliberately numbered as
      the first event of the NEW season. */
  function seasonOfDate(n) {
    var p = parse(n);
    return p.month >= 6 ? p.year : p.year - 1;
  }

  /** Composite-axis hour of a date: hours since Jun 1 00Z on a fixed 366-day
      calendar.

      Leap years: the axis always has a 29 Feb slot, so every date sits on
      the SAME slot in every season - 14 Jan is 14 Jan whether the season
      has a Feb 29 or not. Counting plain day-of-year instead would put 1 Mar
      at day 60 in a leap season and 59 in a normal one, sliding the whole
      Mar-May half of the composite by a day between the two kinds of season,
      i.e. smearing the climatology exactly where the track is changing
      fastest. The cost: the 29 Feb slot is fed by leap seasons only (1 in 4)
      so it is thin, and a storm stepping 28 Feb 18Z -> 1 Mar 00Z in a normal
      year crosses the empty slot, taking 30 axis-hours instead of 6.
      (4 storms in the archive do; they visibly pause a day, nothing else
      is touched.) The alternative that keeps motion exact - 365 days with
      29 Feb folded onto 28 Feb - was rejected because it moves real fixes
      by up to a day.

      Season boundary: a fix is placed by its own date, so a storm that
      crosses 31 May -> 1 Jun would jump from the end of the axis to the start.
      The caller (prepare()) adds one period to the later fixes to keep the
      storm's track continuous, and the clock tests it against t, t+period and
      t-period. None of the 1,932 lows does this today; the code does not
      depend on that staying true. */
  function compositeHour(n) {
    var p = parse(n);
    var idx = (p.month + 6) % 12;                // Jun = 0 ... May = 11
    return (SEASON_MONTH_START[idx] + p.day - 1) * 24 + p.hour;
  }

  /** "14 Jan", with no year - the composite is 25 seasons, not one. */
  function compositeLabel(t) {
    var day = Math.floor(t / 24);
    if (!(day >= 0)) day = 0;
    if (day > 365) day = 365;
    var idx = 11;
    while (idx > 0 && SEASON_MONTH_START[idx] > day) idx--;
    var month = ((idx + 5) % 12) + 1;
    return (day - SEASON_MONTH_START[idx] + 1) + ' ' + HF.monthName(month);
  }

  /* --------------------------------------------------------- geometry */

  /* Interpolation is on the unit sphere. Measured on this archive (6,119
     positive-duration fix pairs, 19 interior points each) by comparing the
     great-circle point with straight lat/lon interpolation (taking the short
     way round in longitude): median difference 1.6 km, 99th percentile 16 km.
     Excluding the 49 six-hour pairs that imply more than 1,000 km (over
     165 km/h, faster than any extratropical low moves) the worst case is 32 km, and the worst 6-hourly
     pair north of 60N is 29 km. 30 km is about one pixel on the globe at its
     default zoom, so for well-behaved data linear interpolation would have
     been defensible. Slerp is kept anyway for two reasons the numbers do not
     capture: the archive's bad pairs (pac:2016201716 jumps 52N 132.5W ->
     132.5E in one step, a sign slip in the source; there linear is off by
     1,165 km and slerp at least follows the short arc), and the dateline -
     146 pairs straddle +-180, where linear needs unwrapping and slerp takes
     the short arc with no special case. It is ten lines. */

  function toVec(lon, lat) {
    var a = lon * DEG, b = lat * DEG, c = Math.cos(b);
    return [c * Math.cos(a), c * Math.sin(a), Math.sin(b)];
  }

  /** Great-circle point a fraction f along fix i -> j of a flat vec array. */
  function slerpAt(vec, i, j, f) {
    var ax = vec[i * 3], ay = vec[i * 3 + 1], az = vec[i * 3 + 2];
    var bx = vec[j * 3], by = vec[j * 3 + 1], bz = vec[j * 3 + 2];
    var d = ax * bx + ay * by + az * bz;
    if (d > 1) d = 1; else if (d < -1) d = -1;
    var omega = Math.acos(d), s = Math.sin(omega);
    var wa, wb;
    if (s < 1e-9) {
      // Coincident (or antipodal, which a 6-hourly track cannot be): there is
      // no arc to follow, so fall back to a chord and renormalise below.
      wa = 1 - f; wb = f;
    } else {
      wa = Math.sin((1 - f) * omega) / s;
      wb = Math.sin(f * omega) / s;
    }
    var x = ax * wa + bx * wb, y = ay * wa + by * wb, z = az * wa + bz * wb;
    var n = Math.sqrt(x * x + y * y + z * z) || 1;
    return {
      lat: Math.asin(Math.max(-1, Math.min(1, z / n))) / DEG,
      lon: Math.atan2(y, x) / DEG
    };
  }

  /* ----------------------------------------------------- per-low index */

  /** Largest i with h[i] <= t, or -1 when t precedes the first entry. With
      duplicate timestamps this lands on the LAST of them, which is what makes
      the zero-length pairs harmless: a bracket (i, i+1) always has
      h[i+1] > t >= h[i], so the interpolation fraction never divides by 0. */
  function locate(h, n, t) {
    if (t < h[0]) return -1;
    var lo = 0, hi = n - 1;
    while (lo < hi) {
      var mid = (lo + hi + 1) >> 1;
      if (h[mid] <= t) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  /** Pre-compute everything a frame needs from one decoded low, once per
      engine (i.e. once per filter change) rather than once per frame. */
  function prepare(low) {
    var src = low && low.fixes;
    if (!src || !src.length) return null;

    // The archive's fixes are already in time order, but bracketing silently
    // breaks on a misordered track, so enforce it cheaply. Stable on ties:
    // the archive has 22 repeated timestamps and their order is the only
    // information about which way the track was going.
    var order = [], i, sorted = true;
    for (i = 0; i < src.length; i++) {
      order.push(i);
      if (i && src[i].date < src[i - 1].date) sorted = false;
    }
    if (!sorted) {
      order.sort(function (a, b) { return (src[a].date - src[b].date) || (a - b); });
    }

    var n = src.length;
    var fx = [], abs = [], comp = [], vec = [];
    var season0 = seasonOfDate(src[order[0]].date);
    for (i = 0; i < n; i++) {
      var f = src[order[i]];
      fx.push(f);
      abs.push(toHours(f.date));
      comp.push(compositeHour(f.date) +
                (seasonOfDate(f.date) - season0) * COMPOSITE_PERIOD_H);
      var v = toVec(f.lon, f.lat);
      vec.push(v[0], v[1], v[2]);
    }

    function span(h) {
      return h[n - 1] > h[0] ? [h[0], h[n - 1]] : [h[0] - LONE_FIX_HALF_H, h[0] + LONE_FIX_HALF_H];
    }
    return {
      low: low, n: n, fx: fx, vec: vec,
      abs: abs, comp: comp,
      absSpan: span(abs), compSpan: span(comp)
    };
  }

  /** Pressure at fraction f between two fixes. Both known: linear. One
      missing: use the one that exists (the same fallback globe.js's
      segmentPressure() uses, so a tail colours the way the static track
      did). None: null, and HF.pressureColor(null) gives the no-data colour. */
  function presBetween(a, b, f) {
    if (a == null && b == null) return null;
    if (a == null) return b;
    if (b == null) return a;
    return a + (b - a) * f;
  }

  /** Position and pressure of a track at axis time t. A t that lands exactly
      on a fix returns that fix's own numbers untouched (not a slerp that
      round-trips them through sin/cos and perturbs a 180 into -180 or a 52.0
      into 51.99999999999999); t past either end returns the nearest fix, which
      only happens for the lone-fix padding. */
  function pointAt(rec, h, t) {
    var n = rec.n;
    var i = locate(h, n, t);
    if (i < 0) i = 0;
    var a = rec.fx[i];
    if (i >= n - 1 || t <= h[i]) return { lat: a.lat, lon: a.lon, pres: a.pres };
    var b = rec.fx[i + 1];
    var f = (t - h[i]) / (h[i + 1] - h[i]);
    var p = slerpAt(rec.vec, i, i + 1, f);
    p.pres = presBetween(a.pres, b.pres, f);
    return p;
  }

  /** The tail: [t - tailHours, t], clipped to the track's own extent, with the
      far end cut at exactly t - tailHours (interpolated) and the near end at
      exactly t (the head). Trimming both ends, rather than keeping whole
      segments, is what makes the tail's length track tailHours smoothly
      instead of jumping a fix at a time. Fixes strictly inside the window
      are kept verbatim; fixes sharing a timestamp stay as a zero-duration
      jump (the static map draws that jump too). */
  function tailOf(rec, h, t, tailHours) {
    var n = rec.n, head = pointAt(rec, h, t);
    var pts = [];
    var ts = t - tailHours;
    if (!(ts > h[0])) ts = h[0];                 // also absorbs Infinity / NaN
    if (h[n - 1] > h[0] && ts < t) {
      var s = pointAt(rec, h, ts);
      pts.push({ lat: s.lat, lon: s.lon, pres: s.pres, age: t - ts });
      for (var k = locate(h, n, ts) + 1; k < n && h[k] < t; k++) {
        var f = rec.fx[k];
        pts.push({ lat: f.lat, lon: f.lon, pres: f.pres, age: t - h[k] });
      }
    }
    pts.push({ lat: head.lat, lon: head.lon, pres: head.pres, age: 0 });
    return pts;
  }

  function stormAt(rec, h, t, tailHours) {
    var tail = tailOf(rec, h, t, tailHours);
    var head = tail[tail.length - 1], low = rec.low;
    return {
      key: low.key, basin: low.basin, cls: low.cls, season: low.season, low: low,
      lat: head.lat, lon: head.lon, pres: head.pres, tail: tail
    };
  }

  /* ------------------------------------------------------------ clocks */

  /** One object shape for composite and season mode so the renderer's frame
      loop is written once. `axis` picks which precomputed time array to use
      and `shifts` which copies of the axis to test (composite wraps). */
  function makeClock(mode, recs, axis, shifts, domain, extra) {
    var spanKey = axis + 'Span';
    var clock = {
      mode: mode,
      domain: domain,
      count: recs.length,
      empty: recs.length === 0,

      /** What is on screen at t, with tails of tailHours (default 0: heads
          only). tailHours may be Infinity for an accumulating replay (the
          whole track so far). Never throws; unusable t -> no storms. */
      at: function (t, tailHours) {
        var storms = [];
        if (typeof t !== 'number' || t !== t) return { t: t, storms: storms };
        var tl = tailHours == null || tailHours !== tailHours || tailHours < 0 ? 0 : tailHours;
        for (var i = 0; i < recs.length; i++) {
          var rec = recs[i], sp = rec[spanKey];
          for (var k = 0; k < shifts.length; k++) {
            var tq = t + shifts[k];
            if (tq >= sp[0] && tq <= sp[1]) {
              storms.push(stormAt(rec, rec[axis], tq, tl));
              break;               // a storm cannot span a whole period
            }
          }
        }
        return { t: t, storms: storms };
      },

      clamp: function (t) {
        return Math.max(domain.start, Math.min(domain.end, t));
      }
    };
    for (var k in extra) clock[k] = extra[k];
    return clock;
  }

  /* ------------------------------------------------------------ engine */

  function monthTicksComposite() {
    var out = [];
    for (var i = 0; i < 12; i++) {
      out.push({ t: SEASON_MONTH_START[i] * 24, label: HF.monthName(((i + 5) % 12) + 1) });
    }
    return out;
  }

  function monthTicksAbsolute(start, end) {
    var out = [], c = civilFromDays(Math.floor(start / 24));
    var y = c.year, m = c.month;
    for (var guard = 0; guard < 600; guard++) {
      m++;
      if (m > 12) { m = 1; y++; }
      var t = daysFromCivil(y, m, 1) * 24;
      if (t > end) break;
      if (t >= start) out.push({ t: t, label: HF.monthName(m) });
    }
    return out;
  }

  /**
   * Index a (pre-filtered) array of decoded lows for playback.
   *
   * opts.seasons - the full list of season start years the UI steps through
   *   (HF.decode's `seasons`: [{start, label}] or plain ints). Optional, but
   *   pass it: the engine only ever sees the FILTERED lows, so without it a
   *   season the filters emptied entirely is invisible to it and stepping
   *   would skip silently. With it, that season is listed, reports
   *   `empty: true`, and the viewer sees the filter's effect.
   */
  function create(lows, opts) {
    opts = opts || {};
    var recs = [], skipped = 0, i;
    lows = lows || [];
    for (i = 0; i < lows.length; i++) {
      var r = prepare(lows[i]);
      if (r) recs.push(r); else skipped++;      // a low with no fixes has no track to play
    }

    var bySeason = {};
    for (i = 0; i < recs.length; i++) {
      var s = recs[i].low.season;
      (bySeason[s] = bySeason[s] || []).push(recs[i]);
    }

    // Season list = declared seasons + any actually present (nothing the
    // caller passed in may be dropped just because the declared list was
    // stale). With no declaration, the contiguous min..max of what is
    // present, so an emptied season in the middle is still shown.
    var seasonSet = {}, k;
    var declared = opts.seasons || [];
    for (i = 0; i < declared.length; i++) {
      var d = declared[i];
      seasonSet[typeof d === 'object' && d ? d.start : d] = true;
    }
    for (k in bySeason) seasonSet[k] = true;
    var list = Object.keys(seasonSet).map(Number).sort(function (a, b) { return a - b; });
    if (!opts.seasons && list.length) {
      var filled = [];
      for (var y = list[0]; y <= list[list.length - 1]; y++) filled.push(y);
      list = filled;
    }

    function seasonDomain(s) {
      var rs = bySeason[s] || [];
      if (!rs.length) {
        // Empty season: the nominal Jun 1 -> Jun 1 window, so a scrubber
        // built from the domain still has a sensible range to show.
        return { start: toHours(s * 1000000 + 60100), end: toHours((s + 1) * 1000000 + 60100) };
      }
      var lo = Infinity, hi = -Infinity;
      for (var j = 0; j < rs.length; j++) {
        lo = Math.min(lo, rs[j].abs[0]);
        hi = Math.max(hi, rs[j].abs[rs[j].n - 1]);
      }
      return { start: lo, end: hi };
    }

    var engine = {
      count: recs.length,
      skipped: skipped,
      empty: recs.length === 0,

      /** Mode 1. Domain is fixed (the axis exists even with no storms, so
          the scrubber does not collapse when a filter selects nothing). */
      composite: function () {
        return makeClock('composite', recs, 'comp',
          [0, COMPOSITE_PERIOD_H, -COMPOSITE_PERIOD_H],
          { start: 0, end: COMPOSITE_PERIOD_H },
          {
            label: compositeLabel,
            ticks: monthTicksComposite
          });
      },

      /** Mode 2. Always returns a clock: an unknown season, or no data,
          gives an empty clock (empty: true, nominal domain) rather than null,
          so the caller never has to branch before drawing. With no argument,
          the first season present. */
      season: function (s) {
        if (s == null) s = list.length ? list[0] : null;
        var rs = s == null ? [] : (bySeason[s] || []);
        var dom = s == null ? { start: 0, end: 0 } : seasonDomain(s);
        return makeClock('season', rs, 'abs', [0], dom, {
          season: s,
          label: function (t) { return HF.fmtDate(fromHours(t)); },
          ticks: function () { return monthTicksAbsolute(dom.start, dom.end); }
        });
      },

      /** Mode 3's season list, ascending, one entry per season INCLUDING
          ones the filters emptied. */
      seasons: function () {
        return list.map(function (s) {
          var n = (bySeason[s] || []).length;
          return {
            season: s, label: HF.seasonLabel(s), count: n, empty: n === 0,
            domain: seasonDomain(s)
          };
        });
      },

      /** Mode 3 frame: season s's complete tracks, all at once. Same storm
          fields as a clock frame so one renderer path styles both; the
          differences are that there is no head (lat/lon null; `pres` is the
          event's minimum pressure, since "pressure at the head" has no
          meaning) and tail is the whole track, age = hours before the
          track's last fix. `empty: true` with storms [] for a season the
          filters emptied. Stable `key`s let the renderer crossfade
          between two steps by matching storms rather than by position. */
      step: function (s) {
        var rs = bySeason[s] || [];
        var storms = [];
        for (var j = 0; j < rs.length; j++) {
          var rec = rs[j], h = rec.abs, last = h[rec.n - 1], tail = [];
          for (var m = 0; m < rec.n; m++) {
            var f = rec.fx[m];
            tail.push({ lat: f.lat, lon: f.lon, pres: f.pres, age: last - h[m] });
          }
          var low = rec.low;
          storms.push({
            key: low.key, basin: low.basin, cls: low.cls, season: low.season, low: low,
            lat: null, lon: null, pres: low.minP == null ? null : low.minP,
            tail: tail
          });
        }
        return { season: s, label: HF.seasonLabel(s), count: storms.length,
                 empty: storms.length === 0, storms: storms };
      }
    };
    return engine;
  }

  HF.playback = {
    create: create,
    parse: parse,
    toHours: toHours,
    fromHours: fromHours,
    seasonOfDate: seasonOfDate,
    compositeHour: compositeHour,
    compositeLabel: compositeLabel,
    COMPOSITE_PERIOD_H: COMPOSITE_PERIOD_H
  };

})(window.HF);
