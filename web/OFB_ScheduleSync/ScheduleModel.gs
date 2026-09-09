/**
 * OFB Schedule Sync - the model layer.
 *
 * Everything in this file is pure: it takes plain arrays and strings and
 * returns plain objects. No SpreadsheetApp, no CalendarApp, no clock. That
 * is deliberate - tests/ofb_schedule_sync/test_sync_logic.js loads this
 * file directly under node and exercises it against fixtures, so the
 * date/DST/shift-code reasoning can be verified without a spreadsheet.
 *
 * Sheet I/O lives in SheetReaders.gs; calendar writes in CalendarSync.gs.
 */

var MONTH_ABBR = {
  JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6,
  JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12
};

// The board writes Thursday as "T" as well as Tuesday, and Sunday as "S"
// as well as Saturday, so a weekday check can only ever be "consistent" or
// "definitely wrong" - never a unique match.
var WEEKDAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

/**
 * "2026" + "Sep 6" -> {y: 2026, m: 9, d: 6, iso: '2026-09-06'}.
 * Returns null for section rows, blanks and anything unparseable.
 */
function parseScheduleDate(yearText, dateText) {
  var year = parseInt(String(yearText || '').trim(), 10);
  var raw = String(dateText || '').trim();
  if (!year || !raw) return null;
  var m = /^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})$/.exec(raw);
  if (!m) return null;
  var month = MONTH_ABBR[m[1].toUpperCase()];
  var day = parseInt(m[2], 10);
  if (!month || !day || day > 31) return null;
  return { y: year, m: month, d: day, iso: isoDate(year, month, day) };
}

function isoDate(y, m, d) {
  return String(y) + '-' + pad2(m) + '-' + pad2(d);
}

function pad2(n) {
  return (n < 10 ? '0' : '') + n;
}

/**
 * Day of week (0=Sunday) for a civil date, via Zeller. Avoids the Date
 * constructor so the host timezone can never shift the answer.
 */
function dayOfWeek(y, m, d) {
  var t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4];
  var yy = m < 3 ? y - 1 : y;
  return (yy + Math.floor(yy / 4) - Math.floor(yy / 100) + Math.floor(yy / 400) + t[m - 1] + d) % 7;
}

/**
 * True when the given Eastern wall-clock moment is in daylight time.
 * US rule in force since 2007: DST runs from 02:00 local on the second
 * Sunday in March to 02:00 local on the first Sunday in November.
 */
function isEasternDst(y, m, d, hour, minute) {
  if (m < 3 || m > 11) return false;
  if (m > 3 && m < 11) return true;
  var minutes = (hour || 0) * 60 + (minute || 0);
  if (m === 3) {
    var secondSunday = 8 + ((7 - dayOfWeek(y, 3, 8)) % 7);
    if (d > secondSunday) return true;
    if (d < secondSunday) return false;
    return minutes >= 120;
  }
  var firstSunday = 1 + ((7 - dayOfWeek(y, 11, 1)) % 7);
  if (d > firstSunday) return false;
  if (d < firstSunday) return true;
  return minutes < 120;
}

/** -5 for EST, -4 for EDT. */
function easternOffsetHours(y, m, d, hour, minute) {
  return isEasternDst(y, m, d, hour, minute) ? -4 : -5;
}

/**
 * Epoch milliseconds for an Eastern wall-clock time. Ambiguous and
 * non-existent times in the DST gap resolve to the standard-time reading;
 * no shift on this board starts inside the 02:00-03:00 window, so that
 * choice never actually bites.
 */
function easternToEpochMs(y, m, d, hour, minute) {
  var offset = easternOffsetHours(y, m, d, hour, minute);
  return Date.UTC(y, m - 1, d, hour, minute, 0, 0) - offset * 3600000;
}

/** "11:00:00" or "11:00" -> {h: 11, m: 0}; anything else -> null. */
function parseTimeText(text) {
  var raw = String(text == null ? '' : text).trim();
  if (!raw) return null;
  var m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(raw);
  if (!m) return null;
  var h = parseInt(m[1], 10);
  var mi = parseInt(m[2], 10);
  if (h > 23 || mi > 59) return null;
  return { h: h, m: mi };
}

function timeToMinutes(t) {
  return t.h * 60 + t.m;
}

/**
 * Builds the code lookup from the STAFF DB Shift Codes rows (display
 * values, header row already stripped).
 *
 * The same shift appears under four codes - COOP/SITE x EST/EDT - and the
 * code that lands in a schedule cell says which. Case matters: "Hra" is
 * the telework (COOP) code for Atlantic Regional Day, "HRA" the on-site
 * one, so the index is built on exact strings.
 *
 * Returns {byCode: {...}, conflicts: [...]}. A conflict is the same code
 * string pointing at two different shifts; first definition wins and the
 * clash is reported rather than silently resolved.
 */
function buildShiftCodeIndex(rows) {
  var byCode = {};
  var conflicts = [];

  var variantOf = {};
  variantOf[SHIFT_CODE_COLS.COOP_EST] = { posture: POSTURE_COOP, tz: 'EST' };
  variantOf[SHIFT_CODE_COLS.COOP_EDT] = { posture: POSTURE_COOP, tz: 'EDT' };
  variantOf[SHIFT_CODE_COLS.SITE_EST] = { posture: POSTURE_SITE, tz: 'EST' };
  variantOf[SHIFT_CODE_COLS.SITE_EDT] = { posture: POSTURE_SITE, tz: 'EDT' };
  var codeColumns = [
    SHIFT_CODE_COLS.COOP_EST, SHIFT_CODE_COLS.COOP_EDT,
    SHIFT_CODE_COLS.SITE_EST, SHIFT_CODE_COLS.SITE_EDT
  ];

  rows.forEach(function (row, i) {
    var cell = function (col) { return String(row[col - 1] == null ? '' : row[col - 1]).trim(); };
    var fullName = cell(SHIFT_CODE_COLS.FULL_NAME);
    if (!fullName) return;

    var codes = {};
    var anyCode = false;
    codeColumns.forEach(function (col) {
      codes[col] = cell(col);
      if (codes[col]) anyCode = true;
    });
    // Section headers ("Operational Shifts", "Leave Categories") carry a
    // name and nothing else.
    if (!anyCode) return;

    var startUtc = parseTimeText(cell(SHIFT_CODE_COLS.START_UTC));
    var endUtc = parseTimeText(cell(SHIFT_CODE_COLS.END_UTC));
    var hours = parseFloat(cell(SHIFT_CODE_COLS.HOURS));
    var def = {
      fullName: fullName,
      category: cell(SHIFT_CODE_COLS.CATEGORY) || 'Uncategorized',
      hours: isNaN(hours) ? null : hours,
      startUtc: startUtc,
      endUtc: endUtc,
      localStart: {
        EST: parseTimeText(cell(SHIFT_CODE_COLS.START_EST)),
        EDT: parseTimeText(cell(SHIFT_CODE_COLS.START_EDT))
      },
      timed: !!(startUtc && endUtc),
      sourceRow: i + 2
    };

    // Posture is only meaningful when this row actually distinguishes
    // telework from on-site. Leave, travel and OB8/OB12 exist only in the
    // SITE columns; X is identical in all four. Calling either of those
    // "on site" would be inventing information.
    var coopSet = [codes[SHIFT_CODE_COLS.COOP_EST], codes[SHIFT_CODE_COLS.COOP_EDT]].filter(String);
    var siteSet = [codes[SHIFT_CODE_COLS.SITE_EST], codes[SHIFT_CODE_COLS.SITE_EDT]].filter(String);
    var posturesDiffer = coopSet.length > 0 && siteSet.length > 0 &&
      coopSet.join(' ') !== siteSet.join(' ');

    codeColumns.forEach(function (col) {
      var code = codes[col];
      if (!code) return;
      var variant = variantOf[col];
      if (Object.prototype.hasOwnProperty.call(byCode, code)) {
        var existing = byCode[code];
        if (existing.fullName !== fullName) {
          conflicts.push({
            code: code, kept: existing.fullName, ignored: fullName, row: def.sourceRow
          });
          return;
        }
        // Same shift reached through a second column (e.g. a code entered
        // in both the COOP and SITE slot): widen what we know rather than
        // overwrite, and drop any posture or season claim that no longer
        // holds.
        if (existing.posture !== null &&
            (!posturesDiffer || existing.posture !== variant.posture)) {
          existing.posture = null;
        }
        if (existing.tz && existing.tz !== variant.tz) existing.tz = null;
        return;
      }
      var entry = {};
      for (var k in def) if (Object.prototype.hasOwnProperty.call(def, k)) entry[k] = def[k];
      entry.code = code;
      entry.posture = posturesDiffer ? variant.posture : null;
      entry.tz = variant.tz;
      byCode[code] = entry;
    });
  });

  return { byCode: byCode, conflicts: conflicts };
}

function isNonEventCode(code) {
  var c = String(code == null ? '' : code).trim();
  for (var i = 0; i < NON_EVENT_CODES.length; i++) {
    if (NON_EVENT_CODES[i] === c) return true;
  }
  return false;
}

/**
 * Turns one (date, member, code) assignment into the event we want to
 * exist, or null when the code is X/XX/blank.
 *
 * Shift times on this board are UTC-anchored: "Atlantic Regional Day" is
 * always 11:00-21:00Z, and the code letter changes across the DST boundary
 * (Gra in winter, Hra in summer) so the local start slides instead. So the
 * event is anchored to the code's own local start on the schedule date and
 * then checked against the table's UTC time; a one-hour disagreement means
 * the wrong seasonal variant was typed, and UTC wins because that is what
 * the desk actually runs on.
 */
function buildEventSpec(date, member, code, codeDef) {
  var trimmed = String(code == null ? '' : code).trim();
  if (isNonEventCode(trimmed)) return null;
  if (!codeDef) {
    return {
      unknownCode: true,
      date: date.iso,
      initials: member.initials,
      code: trimmed,
      diagnostics: ['unknown_code']
    };
  }

  var diagnostics = [];
  var spec = {
    date: date.iso,
    initials: member.initials,
    code: trimmed,
    shift: codeDef.fullName,
    category: codeDef.category,
    posture: codeDef.posture,
    allDay: !codeDef.timed,
    unknownCode: false
  };

  if (!codeDef.timed) {
    // Leave, focal point, official business, travel: a real assignment
    // with no fixed clock time, so an all-day entry on the schedule date.
    spec.startMs = null;
    spec.endMs = null;
    spec.diagnostics = diagnostics;
    spec.title = eventTitle(spec, false);
    spec.signature = specSignature(spec);
    return spec;
  }

  var tz = codeDef.tz;
  if (!tz) {
    // Code appears under both the EST and EDT column (a table entry error).
    // Fall back to whatever the date's actual DST status is.
    tz = isEasternDst(date.y, date.m, date.d, 12, 0) ? 'EDT' : 'EST';
    diagnostics.push('ambiguous_season_variant');
  }
  var local = codeDef.localStart[tz];
  var startMs;
  if (local) {
    startMs = easternToEpochMs(date.y, date.m, date.d, local.h, local.m);
    var wantUtcMin = timeToMinutes(codeDef.startUtc);
    var gotUtcMin = Math.floor(startMs / 60000) % 1440;
    var delta = wantUtcMin - gotUtcMin;
    if (delta > 720) delta -= 1440;
    if (delta <= -720) delta += 1440;
    if (delta !== 0) {
      if (Math.abs(delta) === 60) {
        // The seasonal variant typed on the board disagrees with the real
        // DST status of this date. Honour UTC and say so.
        startMs += delta * 60000;
        diagnostics.push('dst_variant_mismatch');
      } else {
        diagnostics.push('utc_local_mismatch');
      }
    }
  } else {
    // No local column for this variant; anchor straight off UTC, taking
    // the first occurrence of that UTC time on or after local midnight.
    var midnightUtcMs = easternToEpochMs(date.y, date.m, date.d, 0, 0);
    var dayStartUtcMin = Math.floor(midnightUtcMs / 60000) % 1440;
    var forward = (timeToMinutes(codeDef.startUtc) - dayStartUtcMin + 1440) % 1440;
    startMs = midnightUtcMs + forward * 60000;
    diagnostics.push('no_local_time_for_variant');
  }

  var durationMin = (timeToMinutes(codeDef.endUtc) - timeToMinutes(codeDef.startUtc) + 1440) % 1440;
  if (durationMin === 0) {
    durationMin = codeDef.hours ? Math.round(codeDef.hours * 60) : 600;
    diagnostics.push('zero_length_shift_defaulted');
  }

  spec.startMs = startMs;
  spec.endMs = startMs + durationMin * 60000;
  spec.durationMin = durationMin;
  spec.diagnostics = diagnostics;
  spec.title = eventTitle(spec, false);
  spec.signature = specSignature(spec);
  return spec;
}

/**
 * Master-calendar titles lead with the initials because every staffer's
 * shifts share that calendar; personal calendars don't need them.
 */
function eventTitle(spec, forMaster) {
  var suffix = spec.posture ? ' (' + spec.posture + ')' : '';
  var base = spec.shift + suffix;
  return forMaster ? spec.initials + ' - ' + base : base;
}

/**
 * The comparison key that decides whether an existing event still matches
 * the sheet. Stored verbatim in _CalendarSyncState - it is short enough to
 * read at a glance when something looks wrong, which a hash would not be.
 */
function specSignature(spec) {
  return [
    spec.code,
    spec.shift,
    spec.posture || '-',
    spec.allDay ? 'allday' : String(spec.startMs) + '/' + String(spec.endMs)
  ].join('|');
}

/**
 * Reads one schedule grid into assignments.
 *
 * values - display values including the header row
 * staffColumns - [{initials, colIndex}] from matchStaffColumns()
 * filter - optional {fromIso, toIso, keys: {key: true}} to narrow the scan
 */
function extractAssignments(values, staffColumns, filter) {
  var out = { assignments: [], rowIssues: [] };
  if (!values || values.length < 2) return out;

  for (var r = 1; r < values.length; r++) {
    var row = values[r];
    var date = parseScheduleDate(row[SCHEDULE_COLS.YEAR - 1], row[SCHEDULE_COLS.DATE - 1]);
    if (!date) continue;
    if (filter && filter.fromIso && date.iso < filter.fromIso) continue;
    if (filter && filter.toIso && date.iso > filter.toIso) continue;

    var dayLetter = String(row[SCHEDULE_COLS.DAY - 1] || '').trim().toUpperCase();
    var actual = WEEKDAY_LETTERS[dayOfWeek(date.y, date.m, date.d)];
    if (dayLetter && actual !== dayLetter) {
      out.rowIssues.push({
        row: r + 1, date: date.iso, issue: 'weekday_mismatch',
        detail: 'sheet says ' + dayLetter + ', ' + date.iso + ' is a ' + actual
      });
    }

    for (var c = 0; c < staffColumns.length; c++) {
      var sc = staffColumns[c];
      var key = date.iso + '|' + sc.initials;
      if (filter && filter.keys && !filter.keys[key]) continue;
      out.assignments.push({
        key: key,
        date: date,
        initials: sc.initials,
        code: String(row[sc.colIndex - 1] == null ? '' : row[sc.colIndex - 1]).trim(),
        sheetRow: r + 1,
        sheetCol: sc.colIndex
      });
    }
  }
  return out;
}

/**
 * Matches the schedule header row against the member roster.
 *
 * Column headers are the member initials (DCA, BAILE, VA1...). Anything in
 * the header that isn't a known member - or is a member with no email, like
 * the VA vacancy placeholders - is reported, not guessed at.
 */
function matchStaffColumns(headerRow, members) {
  var byInitials = {};
  members.forEach(function (m) {
    byInitials[m.initials.toUpperCase()] = m;
    if (m.altInitials) byInitials[m.altInitials.toUpperCase()] = m;
  });

  var columns = [];
  var unmatched = [];
  for (var c = SCHEDULE_COLS.FIRST_STAFF; c <= headerRow.length; c++) {
    var label = String(headerRow[c - 1] == null ? '' : headerRow[c - 1]).trim();
    if (!label) continue;
    if (SCHEDULE_TRAILING_HEADERS.indexOf(label.toUpperCase()) !== -1) continue;
    var member = byInitials[label.toUpperCase()];
    if (!member) {
      unmatched.push({ label: label, colIndex: c, reason: 'no_member_row' });
      continue;
    }
    if (!member.email) {
      unmatched.push({ label: label, colIndex: c, reason: 'no_email' });
      continue;
    }
    if (!member.active) {
      unmatched.push({ label: label, colIndex: c, reason: 'inactive' });
      continue;
    }
    columns.push({ initials: member.initials, colIndex: c, member: member });
  }
  return { columns: columns, unmatched: unmatched };
}

// Exported for the node test harness; ignored by Apps Script.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    parseScheduleDate: parseScheduleDate,
    isoDate: isoDate,
    dayOfWeek: dayOfWeek,
    isEasternDst: isEasternDst,
    easternOffsetHours: easternOffsetHours,
    easternToEpochMs: easternToEpochMs,
    parseTimeText: parseTimeText,
    buildShiftCodeIndex: buildShiftCodeIndex,
    buildEventSpec: buildEventSpec,
    eventTitle: eventTitle,
    specSignature: specSignature,
    extractAssignments: extractAssignments,
    matchStaffColumns: matchStaffColumns,
    isNonEventCode: isNonEventCode
  };
}
