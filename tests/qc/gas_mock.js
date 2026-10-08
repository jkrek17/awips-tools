/* Loads web/HFArchiveExport/Code.gs under node with in-memory stand-ins for
   the Apps Script services, so its QC write path can be tested without a
   deployment. Used by test_qc.js and by serve_mock.js (a local stand-in for
   the deployed web app). */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function fakeSheet(name, rows) {
  const sheet = {
    rows: rows.map(r => r.map(String)),
    getName: () => name,
    getDataRange: () => ({ getDisplayValues: () => sheet.rows.map(r => r.slice()) }),
    getRange: (r, c) => ({ setValue: v => {
      while (sheet.rows.length < r) sheet.rows.push([]);
      sheet.rows[r - 1][c - 1] = String(v);
    } }),
    appendRow: vals => { sheet.rows.push(vals.map(String)); },
    setFrozenRows: () => {}
  };
  return sheet;
}

function load(tabs, props) {
  const sheets = Object.keys(tabs).map(n => fakeSheet(n, tabs[n]));
  const ss = {
    getSheets: () => sheets,
    getSheetByName: n => sheets.find(s => s.getName() === n) || null,
    insertSheet: n => { const s = fakeSheet(n, []); sheets.push(s); return s; }
  };
  const store = Object.assign({}, props);
  const ctx = {
    SpreadsheetApp: { openById: () => ss },
    PropertiesService: { getScriptProperties: () => ({
      getProperty: k => (k in store ? store[k] : null),
      setProperty: (k, v) => { store[k] = v; } }) },
    LockService: { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) },
    ContentService: {
      MimeType: { JSON: 'json', TEXT: 'text', CSV: 'csv' },
      createTextOutput: s => ({ text: s, setMimeType() { return this; } })
    },
    Utilities: { getUuid: () => 'uuid' },
    Logger: { log: () => {} },
    JSON, Date, Math, String, Number, isNaN
  };
  vm.createContext(ctx);
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'HFArchiveExport', 'Code.gs'), 'utf8');
  vm.runInContext(src, ctx);
  return { ctx, ss, sheets };
}

module.exports = { load };
