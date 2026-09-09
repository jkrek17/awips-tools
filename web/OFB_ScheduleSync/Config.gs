/**
 * OFB Schedule Sync - configuration and shared constants.
 *
 * Drop-in add-on for the Apps Script project bound to the OFB Schedule
 * Modernization workbook. It mirrors the published schedule into an Admin
 * Master Google Calendar and into one admin-owned calendar per staff
 * member, and pushes the same changes to the web portal.
 *
 * Nothing in this file (or any file in this add-on) defines doGet(),
 * onOpen(), or any other reserved Apps Script entry point - the host
 * project already owns those. See README.md for how to wire the web
 * endpoint and the menu rows in.
 *
 * All tunables live in Script Properties so this code carries no calendar
 * IDs, URLs or secrets. Run setupScheduleSync() once to seed them.
 */

var SYNC_VERSION = '2026-09-09a';

// ---------------------------------------------------------------- sheets

var SHEETS = {
  PUBLISHED: 'Published_Schedule',
  LIVE: 'Live_Schedule',
  MEMBERS: 'STAFF DB Members',
  SHIFT_CODES: 'STAFF DB Shift Codes',
  CHANGE_NOTICES: 'STAFF DB Change Notices',
  STATE: '_CalendarSyncState'
};

// Published_Schedule / Live_Schedule layout. The staff columns are not
// fixed - they are whatever the header row lists between HOL/EDT and the
// trailing DAY/DATE/PP repeat, matched against STAFF DB Members initials.
var SCHEDULE_COLS = {
  PP: 1,        // A - pay period
  YEAR: 2,      // B - "2026"
  DAY: 3,       // C - S/M/T/W/T/F/S, used as a consistency check
  DATE: 4,      // D - "Sep 6"
  HOL_EDT: 5,   // E - X / HOL / EST / EDT
  FIRST_STAFF: 6 // F - first staff column
};

// Header labels that appear after the staff block and must not be treated
// as staff columns.
var SCHEDULE_TRAILING_HEADERS = ['DAY', 'DATE', 'PP', 'DIAGNOSTICS'];

var MEMBER_COLS = {
  NAME: 1,          // A - "Jason Krekeler"
  INITIALS: 2,      // B - "JAK", matches the schedule column header
  EMAIL: 3,         // C
  GROUP: 4,         // D
  SEAT: 5,          // E
  STATUS: 6,        // F - Active / Inactive
  ACCESS: 7,        // G
  DISPLAY_ORDER: 8, // H
  SPECIAL: 9,       // I
  PREFERRED: 10,    // J - "Jason"
  ALT_INITIALS: 11  // K
  // Calendar ID is appended by ensureMembersCalendarColumn().
};

var MEMBER_CALENDAR_HEADER = 'Calendar ID';

var SHIFT_CODE_COLS = {
  FULL_NAME: 1,   // A
  COOP_EST: 2,    // B
  COOP_EDT: 3,    // C
  SITE_EST: 4,    // D
  SITE_EDT: 5,    // E
  START_UTC: 9,   // I
  END_UTC: 10,    // J
  START_EST: 11,  // K
  END_EST: 12,    // L
  START_EDT: 13,  // M
  END_EDT: 14,    // N
  HOURS: 15,      // O
  CATEGORY: 16    // P
};

var CHANGE_NOTICE_COLS = {
  LOGGED_AT: 1,  // A - when the change was published
  SHIFT_DATE: 2, // B - the schedule date that changed
  MEMBER: 3,     // C - initials
  ORIGINAL: 4,   // D
  NEW: 5,        // E
  PUBLISHER: 6   // F
};

// _CalendarSyncState layout. Key is "<ISO date>|<INITIALS>".
var STATE_COLS = {
  KEY: 1,
  DATE: 2,
  INITIALS: 3,
  CODE: 4,
  HASH: 5,
  MASTER_EVENT_ID: 6,
  STAFF_EVENT_ID: 7,
  STAFF_CALENDAR_ID: 8,
  LAST_SYNCED: 9,
  STATUS: 10
};

var STATE_HEADERS = [
  'Key', 'Date', 'Initials', 'Code', 'Hash',
  'Master Event ID', 'Staff Event ID', 'Staff Calendar ID',
  'Last Synced', 'Status'
];

// ------------------------------------------------------------ shift codes

// Codes that never produce a calendar event. Everything else in the shift
// code table does, including leave - see README on who can see the master
// calendar before turning that on for a wider audience.
var NON_EVENT_CODES = ['X', 'XX', ''];

var POSTURE_SITE = 'SITE';
var POSTURE_COOP = 'COOP';

// ------------------------------------------------------- script properties

var PROP = {
  MASTER_CALENDAR_ID: 'SYNC_MASTER_CALENDAR_ID',
  PORTAL_WEBHOOK_URL: 'SYNC_PORTAL_WEBHOOK_URL',
  PORTAL_SHARED_SECRET: 'SYNC_PORTAL_SHARED_SECRET',
  PORTAL_READ_TOKEN: 'SYNC_PORTAL_READ_TOKEN',
  SOURCE_SHEET: 'SYNC_SOURCE_SHEET',
  WINDOW_BACK_DAYS: 'SYNC_WINDOW_BACK_DAYS',
  WINDOW_FORWARD_DAYS: 'SYNC_WINDOW_FORWARD_DAYS',
  CREATE_STAFF_CALENDARS: 'SYNC_CREATE_STAFF_CALENDARS',
  NOTICE_CURSOR_ROW: 'SYNC_NOTICE_CURSOR_ROW',
  BACKFILL_CURSOR: 'SYNC_BACKFILL_CURSOR',
  DRY_RUN: 'SYNC_DRY_RUN',
  ENABLED: 'SYNC_ENABLED'
};

var DEFAULTS = {};
DEFAULTS[PROP.SOURCE_SHEET] = SHEETS.PUBLISHED;
DEFAULTS[PROP.WINDOW_BACK_DAYS] = '7';
DEFAULTS[PROP.WINDOW_FORWARD_DAYS] = '180';
DEFAULTS[PROP.CREATE_STAFF_CALENDARS] = 'true';
DEFAULTS[PROP.DRY_RUN] = 'true';
DEFAULTS[PROP.ENABLED] = 'false';

// --------------------------------------------------------------- budgets

// One Apps Script execution gets 6 minutes; stop well short so the state
// sheet is always written back cleanly and the next trigger picks up.
var BUDGET = {
  MAX_RUNTIME_MS: 4.5 * 60 * 1000,
  MAX_CALENDAR_WRITES: 700
};

var TIMEZONE = 'America/New_York';

/**
 * Reads a Script Property, falling back to the documented default.
 */
function getProp(key) {
  var v = PropertiesService.getScriptProperties().getProperty(key);
  if (v === null || v === '') {
    return Object.prototype.hasOwnProperty.call(DEFAULTS, key) ? DEFAULTS[key] : '';
  }
  return v;
}

function setProp(key, value) {
  PropertiesService.getScriptProperties().setProperty(key, String(value));
}

function getBoolProp(key) {
  return String(getProp(key)).toLowerCase() === 'true';
}

function getIntProp(key) {
  var n = parseInt(getProp(key), 10);
  return isNaN(n) ? 0 : n;
}

/**
 * Seeds every Script Property this add-on reads, leaving values that are
 * already set alone. Safe to re-run. Starts in DRY_RUN with ENABLED off:
 * nothing touches a calendar until you deliberately flip both.
 */
function setupScheduleSync() {
  var props = PropertiesService.getScriptProperties();
  var seeded = [];
  var keys = [
    PROP.MASTER_CALENDAR_ID, PROP.PORTAL_WEBHOOK_URL, PROP.PORTAL_SHARED_SECRET,
    PROP.PORTAL_READ_TOKEN, PROP.SOURCE_SHEET, PROP.WINDOW_BACK_DAYS,
    PROP.WINDOW_FORWARD_DAYS, PROP.CREATE_STAFF_CALENDARS, PROP.DRY_RUN,
    PROP.ENABLED
  ];
  keys.forEach(function (k) {
    if (props.getProperty(k) === null) {
      props.setProperty(k, Object.prototype.hasOwnProperty.call(DEFAULTS, k) ? DEFAULTS[k] : '');
      seeded.push(k);
    }
  });
  ensureStateSheet();
  ensureMembersCalendarColumn();
  var msg = 'Schedule Sync ' + SYNC_VERSION + ' set up.\n' +
    'Seeded properties: ' + (seeded.length ? seeded.join(', ') : '(none - all already set)') + '\n' +
    'Next: set ' + PROP.MASTER_CALENDAR_ID + ', run runSelfTest(), then flip ' +
    PROP.DRY_RUN + '=false and ' + PROP.ENABLED + '=true.';
  Logger.log(msg);
  return msg;
}
