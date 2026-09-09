/**
 * OFB Schedule Sync - spreadsheet I/O.
 *
 * Every read here uses getDisplayValues() rather than getValues(). The
 * schedule tabs are entirely plain-text formatted ("Sep 6", "2026"), and
 * the shift code times are time-only cells, which getValues() would hand
 * back as 1899-12-30 Date objects in the script timezone. Display values
 * sidestep both problems and are what the model layer expects.
 */

function ss_() {
  return SpreadsheetApp.getActiveSpreadsheet();
}

function requireSheet_(name) {
  var sheet = ss_().getSheetByName(name);
  if (!sheet) {
    throw new Error('Schedule Sync: required sheet "' + name + '" not found in this workbook.');
  }
  return sheet;
}

/**
 * Roster from STAFF DB Members.
 *
 * Group headings ("Senior Group", "High Seas A") sit in column A with
 * nothing beside them; they are skipped by requiring initials as well as a
 * name. Vacancy rows (VA1-VA5) survive this filter but carry no email, so
 * matchStaffColumns() drops them with reason 'no_email'.
 */
function readMembers() {
  var sheet = requireSheet_(SHEETS.MEMBERS);
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  var width = Math.max(sheet.getLastColumn(), MEMBER_COLS.ALT_INITIALS + 1);
  var values = sheet.getRange(1, 1, lastRow, width).getDisplayValues();
  var header = values[0];
  var calendarCol = header.indexOf(MEMBER_CALENDAR_HEADER) + 1;

  var members = [];
  for (var r = 1; r < values.length; r++) {
    var row = values[r];
    var name = String(row[MEMBER_COLS.NAME - 1] || '').trim();
    var initials = String(row[MEMBER_COLS.INITIALS - 1] || '').trim();
    if (!name || !initials) continue;
    var status = String(row[MEMBER_COLS.STATUS - 1] || '').trim();
    members.push({
      name: name,
      initials: initials,
      preferred: String(row[MEMBER_COLS.PREFERRED - 1] || '').trim() || name,
      email: String(row[MEMBER_COLS.EMAIL - 1] || '').trim(),
      group: String(row[MEMBER_COLS.GROUP - 1] || '').trim(),
      altInitials: String(row[MEMBER_COLS.ALT_INITIALS - 1] || '').trim(),
      // "INactive" appears in the sheet alongside "Inactive", so compare
      // case-insensitively rather than against an exact spelling.
      active: status.toLowerCase() === 'active',
      status: status,
      calendarId: calendarCol ? String(row[calendarCol - 1] || '').trim() : '',
      sheetRow: r + 1,
      calendarCol: calendarCol
    });
  }
  return members;
}

/**
 * Adds the Calendar ID column to STAFF DB Members if it isn't there yet,
 * and returns its 1-based index. This is the one structural change the
 * add-on makes to an existing tab; everything else it needs already exists.
 */
function ensureMembersCalendarColumn() {
  var sheet = requireSheet_(SHEETS.MEMBERS);
  var lastCol = Math.max(sheet.getLastColumn(), 1);
  var header = sheet.getRange(1, 1, 1, lastCol).getDisplayValues()[0];
  var existing = header.indexOf(MEMBER_CALENDAR_HEADER);
  if (existing !== -1) return existing + 1;

  // First trailing blank header cell, otherwise a new column on the end.
  var target = header.length + 1;
  for (var c = 0; c < header.length; c++) {
    if (String(header[c]).trim() === '') { target = c + 1; break; }
  }
  sheet.getRange(1, target).setValue(MEMBER_CALENDAR_HEADER);
  return target;
}

function writeMemberCalendarId(member, calendarId) {
  var col = member.calendarCol || ensureMembersCalendarColumn();
  requireSheet_(SHEETS.MEMBERS).getRange(member.sheetRow, col).setValue(calendarId);
  member.calendarId = calendarId;
  member.calendarCol = col;
}

/** Raw STAFF DB Shift Codes rows, header stripped, for buildShiftCodeIndex(). */
function readShiftCodeRows() {
  var sheet = requireSheet_(SHEETS.SHIFT_CODES);
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  var width = Math.max(sheet.getLastColumn(), SHIFT_CODE_COLS.CATEGORY);
  return sheet.getRange(2, 1, lastRow - 1, width).getDisplayValues();
}

function loadShiftCodeIndex() {
  return buildShiftCodeIndex(readShiftCodeRows());
}

/** The schedule grid the sync mirrors, header row included. */
function readScheduleValues() {
  var name = getProp(PROP.SOURCE_SHEET) || SHEETS.PUBLISHED;
  var sheet = requireSheet_(name);
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow < 2) return [];
  return sheet.getRange(1, 1, lastRow, lastCol).getDisplayValues();
}

/**
 * Loads roster, code table and grid together, plus the header match.
 * Everything downstream works off this one snapshot so a mid-run edit
 * can't produce a half-old, half-new sync.
 */
function loadScheduleContext() {
  var members = readMembers();
  var values = readScheduleValues();
  var codes = loadShiftCodeIndex();
  var match = values.length ? matchStaffColumns(values[0], members) : { columns: [], unmatched: [] };
  var byInitials = {};
  members.forEach(function (m) { byInitials[m.initials] = m; });
  return {
    members: members,
    membersByInitials: byInitials,
    values: values,
    codes: codes,
    staffColumns: match.columns,
    unmatchedColumns: match.unmatched,
    sourceSheet: getProp(PROP.SOURCE_SHEET) || SHEETS.PUBLISHED
  };
}

/**
 * New rows from STAFF DB Change Notices since the last run.
 *
 * The notices tab is the system's own record of what a publish changed
 * (member, date, old code, new code), which makes it a far better change
 * feed than onEdit: publishes are bulk script writes that onEdit never
 * sees. We only use it to learn *which* (date, member) pairs to re-check -
 * the codes themselves always come back from the schedule tab, so a stale
 * or hand-edited notice can't push a wrong shift onto anyone's calendar.
 *
 * Returns {keys: {'2026-09-06|JAK': true}, lastRow: n, reset: bool}.
 */
function readChangeNoticeKeys() {
  var sheet = ss_().getSheetByName(SHEETS.CHANGE_NOTICES);
  if (!sheet) return { keys: {}, lastRow: 0, reset: false, missing: true };

  var lastRow = sheet.getLastRow();
  var cursor = getIntProp(PROP.NOTICE_CURSOR_ROW);
  var reset = false;
  if (cursor > lastRow) {
    // The tab shrank - archived, cleared or rebuilt. The cursor no longer
    // means anything, so fall back to a full reconcile rather than
    // silently skipping whatever changed.
    cursor = 0;
    reset = true;
  }
  if (lastRow <= Math.max(cursor, 1)) {
    return { keys: {}, lastRow: lastRow, reset: reset };
  }

  var start = Math.max(cursor + 1, 2);
  var rows = sheet.getRange(start, 1, lastRow - start + 1, CHANGE_NOTICE_COLS.PUBLISHER)
    .getDisplayValues();
  var keys = {};
  rows.forEach(function (row) {
    var initials = String(row[CHANGE_NOTICE_COLS.MEMBER - 1] || '').trim();
    var iso = normalizeNoticeDate_(row[CHANGE_NOTICE_COLS.SHIFT_DATE - 1]);
    if (initials && iso) keys[iso + '|' + initials] = true;
  });
  return { keys: keys, lastRow: lastRow, reset: reset };
}

/**
 * Change Notices dates display as spreadsheet datetimes ("8/23/2026" or
 * "2026-08-23 0:00:00" depending on the cell's format), not as the
 * "Sep 6" text the schedule grid uses.
 */
function normalizeNoticeDate_(text) {
  var raw = String(text == null ? '' : text).trim();
  if (!raw) return '';
  var iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
  if (iso) return iso[1] + '-' + iso[2] + '-' + iso[3];
  var us = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(raw);
  if (us) return isoDate(parseInt(us[3], 10), parseInt(us[1], 10), parseInt(us[2], 10));
  var named = parseScheduleDate(new Date().getFullYear(), raw);
  return named ? named.iso : '';
}
