/* Teleconnection attribution: joins the baked climate indices
   (window.HF_TELECONNECTIONS, docs/data/teleconnections.js) to storm events
   and builds the event subsets a filter UI or a composite asks for. No DOM,
   no network, no drawing; plain objects and arrays in and out.

   Built on HF.decode()'s lows (util.js). It reads `start` (the first fix,
   YYYYMMDDHH, taken as genesis), `season` (start year, 1 June boundary) and
   `key`, and nothing else. It never writes to a low, never decorates one
   with attribution fields and never copies one: the map, the table and the
   charts all hold these same objects, so a subset is an ordinary array of
   the very objects it was given (identity preserved) and
   HF.composite / the existing filters consume it unchanged.

   What the data are, because it decides what the lookups mean (the build
   script, tools/build_teleconnections.py, has the long version):

     ONI          monthly array, each slot a 3-month season keyed by its
                  CENTRE month (DJF 2016 is the 2016-01 slot).
     NAO/PNA/AO   DAILY dense arrays, slot i = start + i calendar days.
     MJO          PENTAD rows with an explicit centre-date array, one series
                  per longitude. NOT Wheeler-Hendon RMM: no phase 1-8, no
                  amplitude. Negative = enhanced convection (mjo.convention).

   Per-event attribution is "at genesis plus a short antecedent mean":

     enso.genesis  the ONI season centred on the genesis month - what
                   oni.seasonMapping prescribes. An October genesis gets
                   SON, a January one gets DJF. This is the ocean state AT
                   the event.
     enso.djf      the DJF ONI of the event's SEASON (Dec of the start year
                   through Feb of the next, centred on the January that
                   follows the 1 June boundary: season 2009 -> DJF 2009-10).
                   This is the season-level ENSO descriptor most compositing
                   wants ("El Nino winters"). It is deliberately a separate
                   field from the genesis one: for a June-September event it
                   describes an ocean state that had not happened yet, which
                   is exactly right for classifying the season and exactly
                   wrong as a cause of the event, so the two must never be
                   confused. Subsets default to djf; pass basis: 'genesis'
                   for the other.
     nao/pna/ao    .daily  value on the genesis UTC calendar day
                   .mean5  mean of days d-4..d inclusive (derived.mean5),
                           null unless all five are present
     mjo           the pentad containing genesis (derived.mjoRow) and the
                   values at it and at `lag` rows back (derived.mjoLag).

   Every lookup that cannot be answered returns null: before the record
   starts, after it ends, a sentinel day, a missing pentad, an antecedent
   window that runs off the front of the array. Never 0, never the nearest
   neighbour - a zero NAO is a real, common value and a quiet MJO is a
   physical state, so a substituted number would silently join a composite.
   coverage() counts the nulls per index so a UI can say "412 events have no
   MJO value at this lag" instead of just drawing a smaller sample.

   Usage:

     var tc = HF.teleconnect.create({ archive: DATA });   // reads recordStart + seasons
     tc.attribute(low)                      // {enso, nao, pna, ao, mjo, ...}
     tc.attribute(low, { lag: 3 })          // same, MJO 3 pentads back
     tc.byEnso(lows, 'L')                   // La Nina DJF seasons
     tc.byTercile(lows, 'nao', 'lower')     // NAO in the archive's lower third
     tc.byMjo(lows, '120W', 'enhanced', { lag: 2, threshold: 0.5 })
     tc.coverage(lows)                      // per-index counts of attributed / not

   Partial seasons. The archive's early seasons are SHORT-COUNTED, not quiet
   (Pacific data begin Feb 2002, Atlantic Sep 2003; the 2001-02 season has
   1 event, 2002-03 has 22, 2003-04 has 38, against 62-115 for every complete
   season) and DATA.recordStart (2004) is the first complete one. Counting
   events per season across all 25 seasons turns two partial neutral seasons
   into a plausible-looking "neutral years are 20% quieter" signal that
   vanishes (p 0.24 -> 0.78) once they are dropped. So the two jobs are kept
   apart:
     attribute()   tags EVERY event, partial seasons included - a 2002 storm
                   is a real storm with a real NAO value - and says
                   `complete` so the caller can tell.
     tercile cuts  are computed over the complete-season period only.
     select / unattributed / coverage  take `completeOnly`, which DEFAULTS TO
                   TRUE: a subset built for statistics leaves partial seasons
                   out unless the caller asks otherwise ({completeOnly:false}
                   for "show every attributed event on the map"). The unsafe
                   behaviour fails silently, so it is the opt-in. excluded()
                   returns what the default dropped so a UI can say so.
   This needs recordStart; with no recordStart the engine cannot know which
   seasons are complete and throws rather than guess (pass archive: DATA, or
   recordStart: DATA.recordStart).

   The same selections as plain data, for a UI that stores its filter state:
   tc.select(lows, { type: 'tercile', index: 'nao', group: 'lower' }) and
   tc.unattributed(lows, spec) - the lows that spec could not place. */

window.HF = window.HF || {};

(function (HF) {
  'use strict';

  // The extratropical response to the MJO arrives roughly 5-15 days after the
  // tropical signal, and which lag matters is the research question, so every
  // call takes it as a parameter. The default only has to be a sensible
  // place to start: 2 pentad rows back is ~10 days, the middle of that
  // window, and sits between the "barely moved yet" lag 1 and the "has
  // already decayed or been overtaken by the next phase" lag 3. It is NOT a
  // finding.
  var DEFAULT_MJO_LAG = 2;

  // |index| below this is "neutral" and at or beyond it is "enhanced" (<= -t)
  // or "suppressed" (>= +t). The MJO series are normalized, so 0.5 is half a
  // standard deviation: large enough that "enhanced" means something, small
  // enough that a 25-season archive still leaves a usable sample. Again a
  // starting point; callers pass their own.
  var DEFAULT_MJO_THRESHOLD = 0.5;

  var DAILY_INDICES = ['nao', 'pna', 'ao'];

  var PHASE_NAMES = { E: 'El Nino', N: 'Neutral', L: 'La Nina' };

  /* ------------------------------------------------------------ calendar */

  function isLeap(y) {
    return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  }

  var MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

  function daysInMonth(y, m) {
    return m === 2 && isLeap(y) ? 29 : MONTH_DAYS[m - 1];
  }

  /** Proleptic-Gregorian day count from 1970-01-01 (Hinnant's
      days_from_civil): exact for any date, leap years and the century rules
      included. Integer arithmetic on purpose - these are UTC calendar
      dates, so Date (whose methods answer in the viewer's time zone unless
      every call is the UTC variant) could only add a way to be wrong. Every
      positional lookup in this file is a difference of two of these, so it
      is written once, here, and tested hard (an off-by-one would shift every
      attribution by a day and nothing downstream would notice). */
  function dayNumber(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = Math.floor(y / 400);
    var yoe = y - era * 400;
    var mp = (m + 9) % 12;                       // Mar = 0 ... Feb = 11
    var doy = Math.floor((153 * mp + 2) / 5) + d - 1;
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }

  /** Normalise a date to its UTC calendar day as YYYYMMDD, or null.
      Accepts a low (its genesis, `start`), a YYYYMMDD integer, or a
      YYYYMMDDHH integer (the hour is dropped: the daily indices are
      one-value-per-UTC-day, so 18Z on the 3rd is day 3, not "0.75 of day 3").
      A date that is not on the calendar (31 Apr, 29 Feb 2003) is null rather
      than silently rolled into the next month. */
  function toYmd(x) {
    if (x != null && typeof x === 'object') x = x.start;
    if (typeof x !== 'number' || !isFinite(x) || Math.floor(x) !== x) return null;
    if (x >= 1000000000) x = Math.floor(x / 100);
    if (x < 10000000 || x > 99999999) return null;
    var y = Math.floor(x / 10000), m = Math.floor(x / 100) % 100, d = x % 100;
    if (m < 1 || m > 12 || d < 1 || d > daysInMonth(y, m)) return null;
    return x;
  }

  function ymdDay(ymd) {
    return dayNumber(Math.floor(ymd / 10000), Math.floor(ymd / 100) % 100, ymd % 100);
  }

  /** 'YYYY-MM-DD' (the payload's own format) or YYYYMMDD -> YYYYMMDD. */
  function parseDate(s) {
    if (typeof s === 'string') {
      var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
      return m ? toYmd(Number(m[1] + m[2] + m[3])) : null;
    }
    return toYmd(s);
  }

  /* ------------------------------------------------------------- engine */

  function bad(msg) { throw new Error('HF.teleconnect: ' + msg); }

  function oneOf(value, allowed, what) {
    var v = typeof value === 'string' ? value.toLowerCase() : value;
    if (allowed.indexOf(v) < 0) bad(what + ' must be one of ' + allowed.join(', ') + ' (got ' + value + ')');
    return v;
  }

  function checkLag(lag) {
    if (typeof lag !== 'number' || Math.floor(lag) !== lag || lag < 0) {
      bad('lag must be a whole number of pentad rows >= 0 (got ' + lag + ')');
    }
    return lag;
  }

  function checkThreshold(t) {
    if (typeof t !== 'number' || !isFinite(t) || t < 0) bad('threshold must be a number >= 0 (got ' + t + ')');
    return t;
  }

  function normPhase(p) {
    if (typeof p === 'string') {
      // Spelling slack (case, spaces, hyphens, the n-tilde) but nothing else:
      // stripping every non-letter would let 'Elnino2' through as El Nino.
      var k = p.toLowerCase().replace(/\u00f1/g, 'n').replace(/[\s_-]+/g, '');
      if (k === 'e' || k === 'elnino') return 'E';
      if (k === 'n' || k === 'neutral') return 'N';
      if (k === 'l' || k === 'lanina') return 'L';
    }
    return bad('ENSO phase must be E / N / L (or El Nino / Neutral / La Nina), got ' + p);
  }

  /** Build an engine over the index payload. The data are read once into
      day-number form here; nothing is recomputed per event.

      opts.data     the payload (default window.HF_TELECONNECTIONS)
      opts.lag      default MJO lag in pentad rows (default 2)
      opts.archive      the decoded archive (HF.decode's result): supplies
                        recordStart and seasons below
      opts.recordStart  first COMPLETE season (start year; DATA.recordStart)
      opts.seasons      DATA.seasons ([{start}] or [2001, ...]): the last
                        season bounds the tercile period (default: the last
                        season that ends inside the index data)
      opts.period       {from, to} ('YYYY-MM-DD' or YYYYMMDD), replacing the
                        derived period (an explicit override; the caller
                        owns the partial-season question then)

      The tercile period is a property of the ARCHIVE, never of whatever
      filtered array a caller later passes in: the cut points must not move
      when the user narrows the basin or the month, or "upper third" would
      mean a different thing on every click. Hence it is fixed here, at
      creation: 1 Jun of recordStart to 31 May after the last season. With
      no recordStart and no explicit period there is no honest period, so
      terciles() throws; it does not fall back to the whole record. */
  function create(opts) {
    opts = opts || {};
    var data = opts.data || (typeof window !== 'undefined' ? window.HF_TELECONNECTIONS : null);
    if (!data || !data.oni || !data.mjo || !data.nao || !data.pna || !data.ao) {
      bad('index data missing - load data/teleconnections.js first (window.HF_TELECONNECTIONS)');
    }
    var defaultLag = checkLag(opts.lag == null ? DEFAULT_MJO_LAG : opts.lag);
    var archive = opts.archive || {};
    var recordStart = opts.recordStart != null ? opts.recordStart : archive.recordStart;
    if (recordStart != null && (typeof recordStart !== 'number' || Math.floor(recordStart) !== recordStart)) {
      bad('recordStart must be a season start year (got ' + recordStart + ')');
    }
    var seasonList = opts.seasons || archive.seasons;

    /** Is this low's season a complete one? null if recordStart is unknown. */
    function isComplete(low) {
      if (recordStart == null || typeof low.season !== 'number') return null;
      return low.season >= recordStart;
    }

    /** The complete-season lows, input order (new array, same objects). */
    function completeOnly(lows) {
      if (recordStart == null) {
        bad('cannot tell complete seasons from partial ones without recordStart - ' +
            'pass create({archive: DATA}) or {recordStart: DATA.recordStart}, ' +
            'or {completeOnly: false} to opt out');
      }
      var out = [];
      for (var i = 0; i < lows.length; i++) if (lows[i].season >= recordStart) out.push(lows[i]);
      return out;
    }

    /** The lows completeOnly() would drop. */
    function excluded(lows) {
      if (recordStart == null) bad('excluded() needs recordStart');
      var out = [];
      for (var i = 0; i < lows.length; i++) if (!(lows[i].season >= recordStart)) out.push(lows[i]);
      return out;
    }

    /** `completeOnly` option -> the lows to work on. Default true. */
    function scope(lows, flag) {
      return flag === false ? lows : completeOnly(lows);
    }

    /* --- daily blocks: slot = days since block.start --- */
    var daily = {};
    DAILY_INDICES.forEach(function (name) {
      var b = data[name];
      var s = parseDate(b.start);
      if (s == null) bad(name + '.start is not a date: ' + b.start);
      daily[name] = { values: b.values, day0: ymdDay(s), n: b.values.length, start: b.start, end: b.end };
    });

    /** Slot of a YYYYMMDD in a daily block, or -1 if outside the array. The
        declared end is not consulted: array length is the truth (a build
        that trims or pads the array moves both together, and a mismatch
        would be a build bug the tests below catch). */
    function slot(name, ymd) {
      if (ymd == null) return -1;
      var i = ymdDay(ymd) - daily[name].day0;
      return i >= 0 && i < daily[name].n ? i : -1;
    }

    function dailyValue(name, date) {
      var i = slot(name, toYmd(date));
      if (i < 0) return null;
      var v = daily[name].values[i];
      return v == null ? null : v;
    }

    /** Mean of the five days ending on `date` (d-4..d inclusive), null
        unless every one is present and inside the record. The window is
        refused whole rather than averaged over what is there: a 4-day mean
        is a different statistic and would join the sample unlabelled. */
    function mean5(name, date) {
      var i = slot(name, toYmd(date));
      if (i < 4) return null;                     // -1 (outside) or window runs off the front
      var vals = daily[name].values, sum = 0;
      for (var k = i - 4; k <= i; k++) {
        if (vals[k] == null) return null;
        sum += vals[k];
      }
      return sum / 5;
    }

    /* --- ONI: slot = months since oni.start, keyed by the centre month --- */
    var oni = data.oni;
    var oniY0 = Number(oni.start.slice(0, 4));
    var oniM0 = Number(oni.start.slice(5, 7));

    function oniSlot(year, month) {
      var i = (year - oniY0) * 12 + (month - oniM0);
      return i >= 0 && i < oni.values.length ? i : -1;
    }

    function oniEntry(i) {
      if (i < 0 || oni.values[i] == null) return null;
      var ph = oni.phases[i];
      return {
        season: oni.seas[i],
        value: oni.values[i],
        phase: ph,
        phaseName: PHASE_NAMES[ph] || null,
        episode: oni.episodes[i] == null ? null : oni.episodes[i]   // null = cannot tell yet
      };
    }

    /** ONI season centred on the month of `date` (oni.seasonMapping). */
    function oniAtDate(date) {
      var ymd = toYmd(date);
      if (ymd == null) return null;
      var e = oniEntry(oniSlot(Math.floor(ymd / 10000), Math.floor(ymd / 100) % 100));
      if (e) e.centre = String(Math.floor(ymd / 100)).replace(/^(\d{4})/, '$1-');
      return e;
    }

    /** DJF ONI of archive season `season` (start year): the season centred
        on the January after the 1 June boundary, i.e. January of season+1. */
    function oniDjf(season) {
      if (typeof season !== 'number' || Math.floor(season) !== season) return null;
      var e = oniEntry(oniSlot(season + 1, 1));
      if (e) {
        e.centre = (season + 1) + '-01';
        e.eventSeason = season;
      }
      return e;
    }

    /* --- MJO: pentad rows with explicit centre dates --- */
    var mjo = data.mjo;
    var mjoDays = mjo.dates.map(function (d) {
      var y = toYmd(d);
      if (y == null) bad('mjo.dates holds a non-date: ' + d);
      return ymdDay(y);
    });
    var mjoLons = mjo.longitudes.slice();

    /** Row of the pentad containing `date` (derived.mjoRow): the last row
        whose centre label is <= date + 2 days. Labels are pentad CENTRES
        and steps are 5 days except 6 across a leap day (27 Feb -> 4 Mar), so
        the row is found by search on the real dates, never by dividing days
        by five. 29 Feb lands in the 27 Feb pentad, as does 1 Mar; 2 Mar is
        already the 4 Mar pentad - the same answer in leap and common years.

        Two ends. Before the first row's reach (centre - 2 days) there is no
        row. And the rule as worded would also hand the LAST row to every
        later date forever, because no later label exists to rule it out; a
        pentad only covers centre +- 2 days, so a date beyond that is past
        the end of the record and gets null, not the final pentad. */
    function mjoRow(date) {
      var ymd = toYmd(date);
      if (ymd == null) return null;
      var d = ymdDay(ymd);
      var lo = 0, hi = mjoDays.length - 1, found = -1;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (mjoDays[mid] <= d + 2) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
      }
      if (found < 0) return null;
      if (found === mjoDays.length - 1 && d > mjoDays[found] + 2) return null;
      return found;
    }

    function mjoValue(row, lon) {
      var s = mjo.series[lon];
      if (!s) bad('unknown MJO longitude ' + lon + ' (have ' + mjoLons.join(', ') + ')');
      if (row == null || row < 0 || row >= s.length) return null;
      return s[row] == null ? null : s[row];
    }

    /** All ten longitudes at a row, or null if the pentad has no data at
        all (the two interior all-missing pentads, 2021-12-29 and 2022-12-29). */
    function mjoValues(row) {
      if (row == null || row < 0 || row >= mjoDays.length) return null;
      var out = {}, any = false;
      for (var i = 0; i < mjoLons.length; i++) {
        var v = mjoValue(row, mjoLons[i]);
        out[mjoLons[i]] = v;
        if (v != null) any = true;
      }
      return any ? out : null;
    }

    function mjoCentre(row) {
      return row == null || row < 0 || row >= mjoDays.length ? null : mjo.dates[row];
    }

    /** Pentad `lag` rows before genesis' pentad: {lag, row, pentad, values}
        or null when genesis is outside the MJO record. Lag 0 is the
        genesis pentad itself. A lag that runs off the front of the array
        keeps its place in the answer with values null. */
    function mjoAt(low, lag) {
      lag = checkLag(lag == null ? defaultLag : lag);
      var row0 = mjoRow(low);
      if (row0 == null) return null;
      var row = row0 - lag;
      return {
        lag: lag,
        genesisRow: row0,
        genesisPentad: mjoCentre(row0),
        row: row >= 0 ? row : null,
        pentad: mjoCentre(row),
        values: mjoValues(row)
      };
    }

    /* --- per-event attribution --- */

    /** Everything known about one event. Returns a fresh object and touches
        nothing on `low`. opts.lag overrides the engine's default MJO lag.

        {
          key, date,                     // genesis UTC day, YYYYMMDD
          season, complete,              // complete: season >= recordStart (false = short-counted)
          enso: { genesis, djf },        // each {season,value,phase,phaseName,episode,centre} | null
          nao: { daily, mean5 },         // each number | null (pna, ao alike)
          mjo: {
            lag, genesisPentad, genesisValues,   // {lon: v} at the genesis pentad, or null
            lagPentad, lagValues                 // the same `lag` rows back
          } | null                       // null: genesis outside the MJO record
        }                                                                    */
    function attribute(low, aopts) {
      var lag = checkLag(aopts && aopts.lag != null ? aopts.lag : defaultLag);
      var ymd = toYmd(low);
      var out = {
        key: low.key,
        date: ymd,
        season: low.season,
        complete: isComplete(low),     // false = partial season; null = recordStart unknown
        enso: { genesis: ymd == null ? null : oniAtDate(ymd), djf: oniDjf(low.season) },
        mjo: null
      };
      DAILY_INDICES.forEach(function (name) {
        out[name] = { daily: dailyValue(name, ymd), mean5: mean5(name, ymd) };
      });
      var m = mjoAt(low, lag);
      if (m) {
        out.mjo = {
          lag: lag,
          genesisPentad: m.genesisPentad,
          genesisValues: mjoValues(m.genesisRow),
          lagPentad: m.pentad,
          lagValues: m.values
        };
      }
      return out;
    }

    /* --- terciles --- */

    // Cut points are computed over the ARCHIVE PERIOD's days (every day from
    // 1 Jun of the first season to 31 May after the last, all months), not
    // over the index's whole 1950-on history and not over the events'
    // own values. Two reasons. History: the daily files are baked from 2001
    // on, but a consumer who later bakes a longer record must not see the
    // thirds shift under the same archive. Events: terciling the events'
    // own values would force a third of them into each bin by construction
    // and erase the very question ("do these storms favour one NAO state?"),
    // whereas terciles of the days make the bins climatological and the
    // event counts per bin informative. A consequence worth knowing: the
    // event counts per tercile are NOT thirds.
    //
    // And over COMPLETE seasons only (recordStart on): the early seasons are
    // short-counted, and although the INDEX days in them are perfectly good,
    // the thirds must describe the same period the statistics will use, or
    // "upper third" is defined by years the sample then ignores.
    var period = null;
    if (opts.period) {
      var f = parseDate(opts.period.from), t = parseDate(opts.period.to);
      if (f == null || t == null || f > t) bad('opts.period needs a valid from <= to');
      period = { from: f, to: t };
    } else if (recordStart != null) {
      var last;
      if (seasonList && seasonList.length) {
        var ys = seasonList.map(function (s) { return typeof s === 'number' ? s : s.start; });
        last = Math.max.apply(null, ys);
      } else {
        // No season list: the last season whose 31 May is inside the data.
        var endYmd = parseDate(daily.nao.end);
        last = Math.floor(endYmd / 10000) - (endYmd % 10000 >= 531 ? 1 : 2);
      }
      if (last < recordStart) bad('last season ' + last + ' is before recordStart ' + recordStart);
      period = { from: recordStart * 10000 + 601, to: (last + 1) * 10000 + 531 };
    }

    var cutCache = {};

    /** Linear-interpolation quantile of an ascending array (p in 0..1). */
    function quantile(sorted, p) {
      var pos = p * (sorted.length - 1);
      var lo = Math.floor(pos), hi = Math.ceil(pos);
      return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
    }

    /** Tercile cut points of an index over the archive period.
        basis 'mean5' (default) or 'daily'. Returns
        {index, basis, lower, upper, n, from, to}: a value <= lower is the
        lower third, >= upper the upper third, between is the middle.
        Computed once per (index, basis) and cached. The sample is the complete
        seasons only (see create). Days with no value for
        the basis (sentinels; for mean5 also the four days after one) are
        left out of the sample, not counted as zero. */
    function terciles(index, basis) {
      index = oneOf(index, DAILY_INDICES, 'index');
      basis = oneOf(basis == null ? 'mean5' : basis, ['mean5', 'daily'], 'basis');
      var ck = index + ':' + basis;
      if (cutCache[ck]) return cutCache[ck];

      if (!period) {
        bad('no archive period for the terciles - pass recordStart (create({archive: DATA})) ' +
            'or an explicit period; the whole record would include the short-counted early seasons');
      }
      var d = daily[index];
      var iFrom = Math.max(0, ymdDay(period.from) - d.day0);
      var iTo = Math.min(d.n - 1, ymdDay(period.to) - d.day0);
      var sample = [];
      for (var i = iFrom; i <= iTo; i++) {
        var v;
        if (basis === 'daily') {
          v = d.values[i];
        } else {
          v = null;
          if (i >= 4) {
            var s = 0, k;
            for (k = i - 4; k <= i; k++) {
              if (d.values[k] == null) break;
              s += d.values[k];
            }
            if (k > i) v = s / 5;
          }
        }
        if (v != null) sample.push(v);
      }
      if (sample.length < 3) bad('no ' + index + ' days inside the archive period - cannot form terciles');
      sample.sort(function (a, b) { return a - b; });
      var cut = {
        index: index, basis: basis,
        lower: quantile(sample, 1 / 3), upper: quantile(sample, 2 / 3),
        n: sample.length,
        from: iFrom <= iTo ? daysToYmd(d.day0 + iFrom) : null,
        to: iFrom <= iTo ? daysToYmd(d.day0 + iTo) : null
      };
      cutCache[ck] = cut;
      return cut;
    }

    /** Which third a value is in: 'lower' | 'middle' | 'upper' (null in,
        null out). */
    function tercileOf(index, basis, v) {
      if (v == null) return null;
      var c = terciles(index, basis);
      if (v <= c.lower) return 'lower';
      if (v >= c.upper) return 'upper';
      return 'middle';
    }

    /* --- selection --- */

    /** A spec is plain data a UI can keep as its filter state:
          {type:'enso', phase:'E'|'N'|'L', basis:'djf'|'genesis'}
          {type:'tercile', index:'nao'|'pna'|'ao', group:'upper'|'middle'|'lower',
             basis:'mean5'|'daily'}
          {type:'mjo', lon:'120W', state:'enhanced'|'suppressed'|'neutral',
             lag:2, threshold:0.5}
        Resolved once into {value(low) -> x|null, test(x) -> bool}. A null
        from value() means "cannot attribute": such a low is in no group and
        is reported by unattributed() instead. Bad input throws - an empty
        result from a typo'd phase would look like a finding. */
    function resolve(spec) {
      if (!spec || typeof spec !== 'object') bad('selection spec must be an object');
      var type = oneOf(spec.type, ['enso', 'tercile', 'mjo'], 'spec.type');

      if (type === 'enso') {
        var phase = normPhase(spec.phase);
        var basis = oneOf(spec.basis == null ? 'djf' : spec.basis, ['djf', 'genesis'], 'basis');
        return {
          value: function (low) {
            var e = basis === 'djf' ? oniDjf(low.season) : oniAtDate(low);
            return e ? e.phase : null;
          },
          test: function (p) { return p === phase; }
        };
      }

      if (type === 'tercile') {
        var index = oneOf(spec.index, DAILY_INDICES, 'index');
        var tb = oneOf(spec.basis == null ? 'mean5' : spec.basis, ['mean5', 'daily'], 'basis');
        var group = oneOf(spec.group, ['upper', 'middle', 'lower'], 'group');
        terciles(index, tb);            // fail here, not mid-filter, if the period is empty
        return {
          value: function (low) {
            var ymd = toYmd(low);
            return tb === 'daily' ? dailyValue(index, ymd) : mean5(index, ymd);
          },
          test: function (v) { return tercileOf(index, tb, v) === group; }
        };
      }

      var lon = spec.lon;
      if (mjoLons.indexOf(lon) < 0) bad('unknown MJO longitude ' + lon + ' (have ' + mjoLons.join(', ') + ')');
      var state = oneOf(spec.state, ['enhanced', 'suppressed', 'neutral'], 'state');
      var lag = checkLag(spec.lag == null ? defaultLag : spec.lag);
      var thr = checkThreshold(spec.threshold == null ? DEFAULT_MJO_THRESHOLD : spec.threshold);
      return {
        value: function (low) {
          var row0 = mjoRow(low);
          return row0 == null ? null : mjoValue(row0 - lag, lon);
        },
        test: function (v) {
          if (state === 'enhanced') return v <= -thr;       // negative = enhanced convection
          if (state === 'suppressed') return v >= thr;
          return Math.abs(v) < thr;
        }
      };
    }

    /** Lows matching the spec, in input order. A new plain array of the
        same objects; `lows` is not touched. spec.completeOnly (default
        true) leaves out partial-season lows - see the file header; pass
        false to keep every attributable event. */
    function select(lows, spec) {
      var r = resolve(spec), out = [];
      lows = scope(lows, spec.completeOnly);
      for (var i = 0; i < lows.length; i++) {
        var v = r.value(lows[i]);
        if (v != null && r.test(v)) out.push(lows[i]);
      }
      return out;
    }

    /** Lows the spec could not place at all (no value to classify), within
        the same completeOnly scope as select(): a partial-season low is
        excluded, not unattributed, and is reported by excluded(). */
    function unattributed(lows, spec) {
      var r = resolve(spec), out = [];
      lows = scope(lows, spec.completeOnly);
      for (var i = 0; i < lows.length; i++) {
        if (r.value(lows[i]) == null) out.push(lows[i]);
      }
      return out;
    }

    function merge(spec, extra) {
      var o = {};
      for (var k in spec) o[k] = spec[k];
      for (var j in extra) o[j] = extra[j];
      return o;
    }

    /** How many of `lows` have each attribution. {total, enso:{genesis,djf},
        nao:{daily,mean5}, pna, ao, mjo:{genesis,lag}} where each leaf
        is {ok, missing} (ok + missing = total), where total counts the lows
        in scope: copts.completeOnly (default true) drops partial seasons
        first, and `excludedPartial` says how many went. The MJO leaves: `genesis`
        - the genesis pentad has data; `lag` - the pentad opts.lag rows back
        has data. Computed fresh from `lows` each call. */
    function coverage(lows, copts) {
      var lag = checkLag(copts && copts.lag != null ? copts.lag : defaultLag);
      var all = lows.length;
      lows = scope(lows, copts && copts.completeOnly);
      function leaf() { return { ok: 0, missing: 0 }; }
      function bump(l, v) { if (v == null) l.missing++; else l.ok++; }
      var c = {
        total: lows.length,
        excludedPartial: all - lows.length,
        mjoLag: lag,
        enso: { genesis: leaf(), djf: leaf() },
        nao: { daily: leaf(), mean5: leaf() },
        pna: { daily: leaf(), mean5: leaf() },
        ao: { daily: leaf(), mean5: leaf() },
        mjo: { genesis: leaf(), lag: leaf() }
      };
      for (var i = 0; i < lows.length; i++) {
        var a = attribute(lows[i], { lag: lag });
        bump(c.enso.genesis, a.enso.genesis);
        bump(c.enso.djf, a.enso.djf);
        for (var k = 0; k < DAILY_INDICES.length; k++) {
          var n = DAILY_INDICES[k];
          bump(c[n].daily, a[n].daily);
          bump(c[n].mean5, a[n].mean5);
        }
        bump(c.mjo.genesis, a.mjo ? a.mjo.genesisValues : null);
        bump(c.mjo.lag, a.mjo ? a.mjo.lagValues : null);
      }
      return c;
    }

    return {
      defaultLag: defaultLag,
      recordStart: recordStart,
      isComplete: isComplete,
      completeOnly: completeOnly,
      excluded: excluded,
      defaultThreshold: DEFAULT_MJO_THRESHOLD,
      longitudes: mjoLons,
      /** Spans of each block as stated by the data, for "index ends ..." text. */
      spans: {
        oni: { start: oni.start, end: oni.end },
        nao: { start: daily.nao.start, end: daily.nao.end },
        pna: { start: daily.pna.start, end: daily.pna.end },
        ao: { start: daily.ao.start, end: daily.ao.end },
        mjo: { start: mjo.start, end: mjo.end }
      },
      /** Archive period the terciles use ({from, to}, YYYYMMDD): complete seasons only. Null if undeterminable (terciles() then throws). */
      period: period ? { from: period.from, to: period.to } : null,

      attribute: attribute,

      // Low-level lookups (the same ones attribute() is built from). Dates
      // are a low, a YYYYMMDD or a YYYYMMDDHH.
      dailyValue: dailyValue,
      mean5: mean5,
      oniAt: oniAtDate,
      oniDjf: oniDjf,
      mjoRow: mjoRow,
      mjoAt: mjoAt,
      mjoValues: mjoValues,
      mjoPentad: mjoCentre,

      terciles: terciles,
      tercileOf: tercileOf,

      select: select,
      unattributed: unattributed,
      byEnso: function (lows, phase, o) {
        return select(lows, merge(o || {}, { type: 'enso', phase: phase }));
      },
      byTercile: function (lows, index, group, o) {
        return select(lows, merge(o || {}, { type: 'tercile', index: index, group: group }));
      },
      byMjo: function (lows, lon, state, o) {
        return select(lows, merge(o || {}, { type: 'mjo', lon: lon, state: state }));
      },
      coverage: coverage
    };
  }

  // YYYYMMDD from a day count (inverse of dayNumber).
  function daysToYmd(z) {
    z += 719468;
    var era = Math.floor(z / 146097);
    var doe = z - era * 146097;
    var yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    var y = yoe + era * 400;
    var doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    var mp = Math.floor((5 * doy + 2) / 153);
    var d = doy - Math.floor((153 * mp + 2) / 5) + 1;
    var m = mp < 10 ? mp + 3 : mp - 9;
    return (m <= 2 ? y + 1 : y) * 10000 + m * 100 + d;
  }

  HF.teleconnect = {
    create: create,
    DEFAULT_MJO_LAG: DEFAULT_MJO_LAG,
    DEFAULT_MJO_THRESHOLD: DEFAULT_MJO_THRESHOLD,
    // exposed for tests and for callers that need the same calendar maths
    dayNumber: dayNumber,
    daysToYmd: daysToYmd,
    toYmd: toYmd
  };

})(window.HF);
