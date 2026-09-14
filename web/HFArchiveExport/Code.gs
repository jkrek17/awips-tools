/**
 * HF Archive Export - CSV endpoint for the HF-force extratropical low archive
 *
 * Server side of a Google Apps Script web app bound to the "HF Lows"
 * spreadsheet: two hand-maintained tabs, "HF Data - Atl" and "HF Data -
 * Pac", of hurricane-force extratropical low events (columns ID, date,
 * Latitude, Longitude, Category, Pressure). `tools/build_hf_lows.py` reads
 * CSV exports of those two tabs and does all the normalization,
 * classification and QC work that turns them into the published site data.
 *
 * WHY THIS EXISTS: the spreadsheet lives in a NOAA Google Workspace and can
 * only be shared "anyone in NOAA" - it can NOT be made link-readable to the
 * public. That means there is no ordinary unauthenticated CSV export URL,
 * and the site's Linux publishing box holds no Google credentials to
 * authenticate as a NOAA user and fetch one. This script is deployed to
 * execute AS THE SHEET OWNER but be reachable by ANYONE who holds the
 * deployment URL and a shared token; running with the owner's permissions
 * lets it read the restricted sheet and re-serve just these two tabs, as
 * plain CSV, to whoever presents the token. It does nothing else: no
 * writes, no other tabs, no other spreadsheets. See README.md for the full
 * security tradeoff (short version: the token is obfuscation, not
 * authentication - do not put anything in this sheet that isn't fit for
 * anyone with the URL to read).
 *
 * This endpoint is deliberately a thin exporter. It returns the sheet's
 * rows essentially as-is (see sheetToCsv_) and does NOT reimplement any of
 * build_hf_lows.py's normalization, category aliasing, or QC logic -
 * that stays the single place those rules live.
 *
 * Deploy: Extensions > Apps Script, add Code.gs and appsscript.json, run
 * setup() once from the editor to mint EXPORT_TOKEN, then
 * Deploy > New deployment > Web app. See README.md for the full walkthrough.
 */

var VERSION = '2026-09-14a';

// The spreadsheet this endpoint reads. Set explicitly (rather than relying
// on SpreadsheetApp.getActiveSpreadsheet(), which only works for a script
// bound to the file it's opened from) so the export keeps working even if
// this project is ever detached into a standalone script.
var SPREADSHEET_ID = '1ncqcxbCokCRmf6npv4tXAODLWZlYEzYtMrEigHdkTe4';

// tab= query param -> loose substring alias matched against the tab name
// (see findSheet_). Keeping these short and generic means a rename like
// "HF Data - Atl" -> "Atlantic" still matches, since "atlantic" contains
// "atl".
var TAB_ALIASES = {
  atl: 'atl',
  pac: 'pac'
};

var TOKEN_PROPERTY = 'EXPORT_TOKEN';


// ---------------------------------------------------------------------------
// Web app entry point
// ---------------------------------------------------------------------------

function doGet(e) {
  try {
    return handleGet_(e);
  } catch (err) {
    return errorOutput_('HFArchiveExport error: ' + String(err));
  }
}


/**
 * Request contract:
 *   ?token=<shared token>&tab=atl|pac      -> 200, CSV body, text/csv
 *   ?token=<shared token>&tab=list         -> 200, newline-separated tab
 *                                              names, text/plain (setup aid)
 *   anything else (bad/missing token, unset EXPORT_TOKEN, unknown tab,
 *   no matching sheet, unexpected exception) -> 200, plain-text body
 *   starting with "HFArchiveExport error: ", text/plain
 *
 * Apps Script's ContentService cannot set an HTTP status code - every
 * response is HTTP 200 regardless of outcome. The publishing script must
 * therefore detect failure by sniffing the body rather than the status
 * code, which is why every error path below returns a fixed, unmistakable
 * "HFArchiveExport error: " prefix that can never be confused with a CSV
 * data row, and successful CSV responses never start with that string.
 */
function handleGet_(e) {
  var params = (e && e.parameter) || {};

  var expected = PropertiesService.getScriptProperties().getProperty(TOKEN_PROPERTY);
  if (!expected) {
    return errorOutput_(
      'HFArchiveExport error: EXPORT_TOKEN is not set. Run setup() once ' +
      'from the Apps Script editor to mint a token, note it down, then ' +
      'redeploy.');
  }

  var supplied = params.token || '';
  if (!tokensEqual_(String(supplied), String(expected))) {
    return errorOutput_('HFArchiveExport error: invalid or missing token.');
  }

  var tabParam = (params.tab || '').toString();
  if (!tabParam) {
    return errorOutput_(
      'HFArchiveExport error: missing tab parameter. Use tab=atl, tab=pac, ' +
      'or tab=list.');
  }

  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);

  if (tabParam.toLowerCase() === 'list') {
    var names = ss.getSheets().map(function (sh) { return sh.getName(); });
    return ContentService.createTextOutput(names.join('\n'))
      .setMimeType(ContentService.MimeType.TEXT);
  }

  var alias = TAB_ALIASES[tabParam.toLowerCase()];
  if (!alias) {
    return errorOutput_(
      'HFArchiveExport error: unknown tab "' + tabParam + '". Use tab=atl, ' +
      'tab=pac, or tab=list.');
  }

  var sheet = findSheet_(ss, alias);
  if (!sheet) {
    return errorOutput_(
      'HFArchiveExport error: no sheet tab matching "' + alias + '" was ' +
      'found in the spreadsheet. Use tab=list to see the available tab ' +
      'names.');
  }

  var csv = sheetToCsv_(sheet);
  return ContentService.createTextOutput(csv)
    .setMimeType(ContentService.MimeType.CSV);
}


// ---------------------------------------------------------------------------
// Tab lookup - loose, so renaming a tab doesn't silently break the export
// ---------------------------------------------------------------------------

/** Lowercase and collapse everything but letters/digits to single spaces,
 * so "HF Data - Atl", "hf_data_atl" and "HF DATA ATL!" all normalize the
 * same way. */
function normalizeName_(name) {
  return String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}


/** Find the first sheet whose normalized name contains `alias` as a
 * substring (e.g. alias "atl" matches "HF Data - Atl" and, if the tab is
 * ever renamed, "Atlantic" too). Returns null if nothing matches. */
function findSheet_(ss, alias) {
  var wanted = normalizeName_(alias);
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (normalizeName_(sheets[i].getName()).indexOf(wanted) >= 0) {
      return sheets[i];
    }
  }
  return null;
}


// ---------------------------------------------------------------------------
// CSV rendering
// ---------------------------------------------------------------------------

/**
 * Render a sheet's used range as RFC 4180-style CSV text.
 *
 * Reads getDisplayValues() rather than getValues() on purpose: display
 * values are exactly the string each cell shows on screen, using the
 * sheet's own formatting, and are never coerced by Apps Script's type
 * mapping. getValues() would hand back a JS Date object for a formatted
 * date/time cell - which Apps Script/JSON would then render as a full ISO
 * instant in some other zone, not the "yyyymmddhh" string the archive
 * actually uses - and a JS Number for a long numeric ID, which silently
 * flips into scientific notation or loses trailing digits once it is large
 * enough. Reading display strings means every field survives as the exact
 * literal a human editing the sheet sees, with zero reinterpretation.
 */
function sheetToCsv_(sheet) {
  var values = sheet.getDataRange().getDisplayValues();
  var lines = [];
  for (var r = 0; r < values.length; r++) {
    var row = values[r];
    var fields = new Array(row.length);
    for (var c = 0; c < row.length; c++) {
      fields[c] = csvField_(row[c]);
    }
    lines.push(fields.join(','));
  }
  // CRLF per RFC 4180; a comma/quote/newline-only quoting rule (below)
  // still round-trips fine through readers that expect bare \n.
  return lines.length ? lines.join('\r\n') + '\r\n' : '';
}


/** Quote a single CSV field only if it needs it (contains a comma, a
 * double quote, or a line break), doubling any internal double quotes. */
function csvField_(value) {
  var s = (value === null || value === undefined) ? '' : String(value);
  if (/[",\r\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}


// ---------------------------------------------------------------------------
// Token check
// ---------------------------------------------------------------------------

/**
 * Compare two strings without an early-exit on the first differing
 * character, so a wrong guess doesn't come back measurably faster than a
 * right one. This is a modest hardening, not a cryptographic guarantee -
 * network jitter alone dwarfs the timing signal here, and (per README) the
 * token is obfuscation against casual discovery rather than real
 * authentication. Costs nothing to do properly, so it's done properly.
 */
function tokensEqual_(a, b) {
  var maxLen = Math.max(a.length, b.length);
  var diff = a.length === b.length ? 0 : 1;
  for (var i = 0; i < maxLen; i++) {
    var ca = i < a.length ? a.charCodeAt(i) : 0;
    var cb = i < b.length ? b.charCodeAt(i) : 0;
    diff |= (ca ^ cb);
  }
  return diff === 0;
}


// ---------------------------------------------------------------------------
// Error output
// ---------------------------------------------------------------------------

/**
 * Plain-text error body. Apps Script's ContentService has no way to set an
 * HTTP status code - every doGet() response is served as HTTP 200 no
 * matter what happens inside it. The publishing script therefore cannot
 * tell success from failure by status code and must sniff the body
 * instead, so every error here is plain prose carrying the fixed
 * "HFArchiveExport error: " prefix - never anything shaped like a CSV
 * header or data row - so a "does this look like our CSV" sniff on the
 * fetch side can't mistake one for real output.
 */
function errorOutput_(message) {
  return ContentService.createTextOutput(message)
    .setMimeType(ContentService.MimeType.TEXT);
}


// ---------------------------------------------------------------------------
// One-time setup
// ---------------------------------------------------------------------------

/**
 * Run once from the Apps Script editor (select setup, click Run). Mints a
 * random token, stores it in this script's Script Properties (Project
 * Settings > Script Properties in the editor UI), and logs it so the
 * deployer can copy it into the publishing script's config. The token
 * never needs to be typed into source.
 *
 * Safe to re-run: it overwrites whatever token was stored before, which is
 * exactly how you rotate it (see README.md).
 */
function setup() {
  // Two UUIDs concatenated for cheap extra length/entropy against casual
  // guessing; this is typed/copied once by a human, not something anyone
  // needs to type twice, so there's no reason to keep it short.
  var token = Utilities.getUuid() + Utilities.getUuid();
  PropertiesService.getScriptProperties().setProperty(TOKEN_PROPERTY, token);
  Logger.log(
    'EXPORT_TOKEN set. Copy this into the publishing script\'s config, ' +
    'then close this log - the token is not stored anywhere else:\n' +
    token);
  return token;
}


// ---------------------------------------------------------------------------
// Self test
// ---------------------------------------------------------------------------

/**
 * Run from the editor. Exercises tab matching (including a simulated tab
 * rename), CSV quoting of awkward values, and the token comparison, all
 * against fake in-memory stand-ins for the Sheets objects - it does not
 * open the real spreadsheet or require a web app deployment, so it can be
 * run immediately after pushing code, before setup() or any deploy.
 */
function runSelfTest() {
  var lines = ['HFArchiveExport self test, v' + VERSION, ''];
  var pass = true;

  // --- tab matching, exact tab names --------------------------------------
  var fakeSs = {
    getSheets: function () {
      return ['HF Data - Atl', 'HF Data - Pac'].map(function (n) {
        return { getName: function () { return n; } };
      });
    }
  };
  var atlHit = findSheet_(fakeSs, TAB_ALIASES.atl);
  var pacHit = findSheet_(fakeSs, TAB_ALIASES.pac);
  var exactOk = !!atlHit && atlHit.getName() === 'HF Data - Atl' &&
                !!pacHit && pacHit.getName() === 'HF Data - Pac';
  lines.push('tab match, exact names: ' + (exactOk ? 'PASS' : 'FAIL'));
  pass = pass && exactOk;

  // --- tab matching survives a rename -------------------------------------
  var renamedSs = {
    getSheets: function () {
      return ['Atlantic (2026 season)', 'Pacific Basin'].map(function (n) {
        return { getName: function () { return n; } };
      });
    }
  };
  var atlRen = findSheet_(renamedSs, TAB_ALIASES.atl);
  var pacRen = findSheet_(renamedSs, TAB_ALIASES.pac);
  var renameOk = !!atlRen && atlRen.getName() === 'Atlantic (2026 season)' &&
                 !!pacRen && pacRen.getName() === 'Pacific Basin';
  lines.push('tab match, survives rename: ' + (renameOk ? 'PASS' : 'FAIL'));
  pass = pass && renameOk;

  var missing = findSheet_(fakeSs, 'nope');
  lines.push('tab match, unknown alias -> null: ' +
             (missing === null ? 'PASS' : 'FAIL'));
  pass = pass && (missing === null);

  // --- CSV quoting ---------------------------------------------------------
  var fakeSheet = {
    getDataRange: function () {
      return {
        getDisplayValues: function () {
          return [
            ['ID', 'date', 'Latitude', 'Longitude', 'Category', 'Pressure'],
            ['1', '2026010400', '52.9', '-48.2', 'DHF', '991'],
            ['2', 'has, comma', 'has "quote"', 'line\nbreak', 'X', '1000']
          ];
        }
      };
    }
  };
  var csv = sheetToCsv_(fakeSheet);
  var csvOk =
    csv.indexOf('"has, comma"') >= 0 &&
    csv.indexOf('"has ""quote"""') >= 0 &&
    csv.indexOf('"line\nbreak"') >= 0 &&
    csv.indexOf('52.9,-48.2') >= 0 &&
    csv.indexOf('\r\n') >= 0;
  lines.push('csv quoting: ' + (csvOk ? 'PASS' : 'FAIL'));
  pass = pass && csvOk;

  // --- token comparison ----------------------------------------------------
  var tokenOk =
    tokensEqual_('abc', 'abc') === true &&
    tokensEqual_('abc', 'abd') === false &&
    tokensEqual_('abc', 'abcd') === false &&
    tokensEqual_('', '') === true;
  lines.push('token compare: ' + (tokenOk ? 'PASS' : 'FAIL'));
  pass = pass && tokenOk;

  lines.push('');
  lines.push(pass ? 'ALL PASS' : 'SOME FAILED');
  Logger.log(lines.join('\n'));
  return lines.join('\n');
}
