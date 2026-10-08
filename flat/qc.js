/* QC mode: list suspect archive data and correct it in the Google Sheet.

   Off unless the page is opened with ?qc (remembered in this browser until
   ?qc=0). The page itself is static, so edits go to the sheet through the
   HFArchiveExport Apps Script's doPost (web/HFArchiveExport/Code.gs), which
   writes the cell and appends a row to the sheet's "QC log" tab. The page
   never changes its own data: a correction shows up here after the next
   publish rebuilds hf-lows.js from the sheet.

   The endpoint URL and QC token are typed into the QC tab once and kept in
   this browser's localStorage; they are never part of the published page.

   Flags come from data the build already ships: the QC notes, the High Seas
   position suspects and the collision pairs (DATA.qc), plus two checks made
   here from the tracks themselves. buildFlags() is pure so tests/qc can run
   it under node. */

window.HF = window.HF || {};

(function (HF) {
  'use strict';

  var KEY_ON = 'hfQcOn', KEY_CFG = 'hfQcConfig';
  var NM_PER_RAD = 3440.065;

  var KINDS = {
    motion:   'Implausible motion',
    position: 'Position disagrees with High Seas',
    duptime:  'Duplicate timestamp',
    nopres:   'First HF fix has no pressure',
    nohf:     'No hurricane-force fix',
    split:    'Possibly one storm with another ID',
    row:      'Sheet row repaired or dropped'
  };
  // build QC notes worth a human look; the rest (id-reused, practice-change,
  // coverage trend) describe the archive rather than a mistake in it
  var ROW_NOTES = ['pressure-dropped', 'position-bad', 'date-bad', 'id-bad',
                   'category-unknown', 'category-mapped', 'date-repaired', 'pressure-repaired'];

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch (e) { /* private window or blocked storage: QC still works for this visit */ }
    return null;
  }

  function enabledFromUrl() {
    var m = /[?&]qc(?:=([^&]*))?(?:&|$)/.exec(window.location.search || '');
    if (m) {
      var on = m[1] !== '0';
      store(KEY_ON, on ? '1' : null);
      return on;
    }
    return store(KEY_ON) === '1';
  }

  /* ------------------------------------------------------------- flags */

  function legNm(a, b) {
    var r = Math.PI / 180;
    var la1 = a.lat * r, la2 = b.lat * r, dlo = (b.lon - a.lon) * r;
    var h = Math.pow(Math.sin((la2 - la1) / 2), 2) +
            Math.cos(la1) * Math.cos(la2) * Math.pow(Math.sin(dlo / 2), 2);
    return 2 * NM_PER_RAD * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function hoursBetween(d0, d1) {
    function t(d) {
      var s = String(d);
      return Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(8, 10));
    }
    return (t(d1) - t(d0)) / 3600000;
  }

  /** The two fixes of a track's fastest leg, as [i, j, kt]; null under two fixes. */
  function fastestLeg(fixes) {
    var best = null;
    for (var i = 1; i < fixes.length; i++) {
      var a = fixes[i - 1], b = fixes[i];
      if (a.lat == null || b.lat == null) continue;
      var h = hoursBetween(a.date, b.date);
      if (h <= 0) continue;
      var kt = legNm(a, b) / h;
      if (!best || kt > best[2]) best = [i - 1, i, kt];
    }
    return best;
  }

  function flag(kind, basin, id, date, detail, extra) {
    var f = { kind: kind, basin: basin, id: id, lowKey: basin + ':' + id,
              date: date == null ? null : date, detail: detail,
              fixDates: date == null ? [] : [date], suggest: null, row: null, other: null };
    for (var k in extra || {}) f[k] = extra[k];
    f.key = [kind, basin, id, f.date == null ? '' : f.date, f.other || ''].join('|');
    return f;
  }

  /** Every QC flag for the decoded payload, in a stable order. */
  function buildFlags(data) {
    var out = [];
    var byKey = {};
    data.lows.forEach(function (l) { byKey[l.key] = l; });
    var baseKey = function (basin, id) {
      return byKey[basin + ':' + id] ? basin + ':' + id :
             (byKey[basin + ':' + id + 'a'] ? basin + ':' + id + 'a' : null);
    };
    var qc = data.qc || {};

    (qc.notes || []).forEach(function (n) {
      if (!n.id) return;
      if (n.kind === 'speed-implausible') {
        var low = byKey[n.basin + ':' + n.id];
        var leg = low ? fastestLeg(low.fixes) : null;
        out.push(flag('motion', n.basin, n.id, leg ? low.fixes[leg[1]].date : n.date,
          leg ? 'Fastest leg ' + Math.round(leg[2]) + ' kt; one of these two positions is probably mistyped.'
              : n.detail,
          { fixDates: leg ? [low.fixes[leg[0]].date, low.fixes[leg[1]].date] : [] }));
      } else if (n.kind === 'time-duplicate') {
        out.push(flag('duptime', n.basin, n.id, n.date, n.detail));
      } else if (ROW_NOTES.indexOf(n.kind) >= 0) {
        var k = baseKey(n.basin, n.id);
        out.push(flag('row', n.basin, k ? k.split(':')[1] : n.id, n.date,
          (n.row ? 'Sheet row ' + n.row + ': ' : '') + n.detail,
          { row: n.row || null, noteKind: n.kind, fixDates: n.date ? [n.date] : [] }));
      }
    });

    (qc.positionSuspects || []).forEach(function (s) {
      var k = baseKey(s.basin, s.id);
      if (!k) return;
      out.push(flag('position', s.basin, k.split(':')[1], s.date,
        'The High Seas analysis has a ' + (s.pres != null ? s.pres + ' hPa ' : '') + 'low ' + s.nm +
        ' nm away. Moving the fix there turns a ' + s.ktAsIs + ' kt leg into ' + s.ktMoved + ' kt.',
        { suggest: { lat: s.hsfLat, lon: s.hsfLon } }));
    });

    (qc.collisions || []).forEach(function (c) {
      if (c.kind !== 'sequential') return;      // concurrent pairs are a tracker issue, not the sheet's
      var k = baseKey(c.basin, c.id), o = baseKey(c.basin, c.other);
      if (!k || !o) return;
      out.push(flag('split', c.basin, k.split(':')[1], null,
        'The High Seas analyses carry one low from ' + o.split(':')[1] + ' into this event' +
        (c.gapH != null ? ' across a ' + c.gapH + ' h gap at ' + c.linkKt + ' kt' : '') +
        '. If they are one storm, give both the same ID in the sheet.',
        { other: o.split(':')[1] }));
    });

    data.lows.forEach(function (l) {
      var hf = l.fixes.filter(function (f) { return f.cat === 'HF'; });
      if (!hf.length) {
        out.push(flag('nohf', l.basin, l.id, null, 'No fix in this event is categorised HF.'));
      } else if (hf[0].pres == null) {
        out.push(flag('nopres', l.basin, l.id, hf[0].date,
          'The first hurricane-force fix has no pressure, so the event has no HF-only deepening.'));
      }
    });

    var order = Object.keys(KINDS);
    out.sort(function (a, b) {
      return order.indexOf(a.kind) - order.indexOf(b.kind) ||
             (a.lowKey < b.lowKey ? -1 : a.lowKey > b.lowKey ? 1 : 0) ||
             ((a.date || 0) - (b.date || 0));
    });
    // a note can repeat (two notes on one row); keep the first of each key
    var seen = {};
    return out.filter(function (f) { return seen[f.key] ? false : (seen[f.key] = true); });
  }

  /* ---------------------------------------------------------- endpoint */

  function config() {
    try { return JSON.parse(store(KEY_CFG) || '{}') || {}; } catch (e) { return {}; }
  }

  function configured() { var c = config(); return !!(c.url && c.token); }

  function post(body) {
    var c = config();
    body.token = c.token;
    // text/plain keeps this a "simple" request: Apps Script cannot answer a
    // CORS preflight, and it reads the body regardless of the declared type
    return fetch(c.url, { method: 'POST', body: JSON.stringify(body),
                          headers: { 'Content-Type': 'text/plain;charset=utf-8' } })
      .then(function (r) { return r.json(); });
  }

  function fetchLog() {
    var c = config();
    var url = c.url + (c.url.indexOf('?') >= 0 ? '&' : '?') +
              'qc=log&token=' + encodeURIComponent(c.token);
    return fetch(url).then(function (r) { return r.json(); });
  }

  /* -------------------------------------------------------------- state */

  var DATA = null, API = null, FLAGS = [];
  var status = {};          // flag key -> 'edited' | 'fine'
  var edits = [];           // {basin, id, date, before, after, saved, error, time}
  var view = { kind: 'all', status: 'open', basin: 'all' };

  function applyLog(entries) {
    (entries || []).forEach(function (e) {
      if (!e.flag) return;
      if (e.action === 'ok') status[e.flag] = 'fine';
      else if (e.action === 'edit' && status[e.flag] !== 'fine') status[e.flag] = 'edited';
    });
  }

  function flagsFor(low) {
    var baseId = low.id.replace(/[a-z]$/, '');
    return FLAGS.filter(function (f) {
      return f.basin === low.basin && (f.id === low.id || f.id === baseId);
    });
  }

  /* ----------------------------------------------------------- QC panel */

  function el(tag, attrs, text) { return HF.el(tag, attrs, text); }

  function renderPanel() {
    var root = document.getElementById('qcRoot');
    if (!root) return;
    HF.clear(root);
    root.appendChild(renderSettings());

    var counts = {};
    FLAGS.forEach(function (f) {
      var st = status[f.key] || 'open';
      counts[f.kind] = counts[f.kind] || { open: 0, all: 0 };
      counts[f.kind].all++;
      if (st === 'open') counts[f.kind].open++;
    });

    var tools = el('div', { class: 'panel-tools qc-tools' });
    var kindSel = el('select', { 'aria-label': 'Problem' });
    kindSel.appendChild(el('option', { value: 'all' }, 'All problems'));
    Object.keys(KINDS).forEach(function (k) {
      if (!counts[k]) return;
      kindSel.appendChild(el('option', { value: k }, KINDS[k] + ' (' + counts[k].open + ' open)'));
    });
    kindSel.value = view.kind;
    kindSel.addEventListener('change', function () { view.kind = kindSel.value; renderPanel(); });
    var stSel = el('select', { 'aria-label': 'Status' });
    [['open', 'Open'], ['edited', 'Edited'], ['fine', 'Marked fine'], ['all', 'Any status']].forEach(function (o) {
      stSel.appendChild(el('option', { value: o[0] }, o[1]));
    });
    stSel.value = view.status;
    stSel.addEventListener('change', function () { view.status = stSel.value; renderPanel(); });
    var bSel = el('select', { 'aria-label': 'Basin' });
    [['all', 'Both basins'], ['atl', 'Atlantic'], ['pac', 'Pacific']].forEach(function (o) {
      bSel.appendChild(el('option', { value: o[0] }, o[1]));
    });
    bSel.value = view.basin;
    bSel.addEventListener('change', function () { view.basin = bSel.value; renderPanel(); });
    tools.appendChild(kindSel);
    tools.appendChild(stSel);
    tools.appendChild(bSel);
    var dl = el('button', { type: 'button', class: 'btn' }, 'Download corrections CSV');
    dl.disabled = !edits.length;
    dl.addEventListener('click', downloadEdits);
    tools.appendChild(dl);

    var rows = FLAGS.filter(function (f) {
      var st = status[f.key] || 'open';
      return (view.kind === 'all' || f.kind === view.kind) &&
             (view.status === 'all' || st === view.status) &&
             (view.basin === 'all' || f.basin === view.basin);
    });
    var open = FLAGS.filter(function (f) { return !status[f.key]; }).length;
    tools.appendChild(el('p', { class: 'tool-note' },
      rows.length + ' shown · ' + open + ' of ' + FLAGS.length + ' still open'));
    root.appendChild(tools);

    var table = el('table', { class: 'data-table qc-table' });
    var hr = el('tr');
    ['Event', 'Time', 'Problem', 'Status', ''].forEach(function (h) { hr.appendChild(el('th', {}, h)); });
    var thead = el('thead'); thead.appendChild(hr); table.appendChild(thead);
    var tbody = el('tbody');
    rows.forEach(function (f) {
      var tr = el('tr');
      var open = el('button', { type: 'button', class: 'link-btn' },
        (f.basin === 'pac' ? 'Pac ' : 'Atl ') + f.id);
      open.addEventListener('click', function () { openFlag(f); });
      var td = el('td'); td.appendChild(open); tr.appendChild(td);
      tr.appendChild(el('td', {}, f.date ? HF.fmtDate(f.date) : '--'));
      var prob = el('td');
      prob.appendChild(el('b', {}, KINDS[f.kind]));
      prob.appendChild(el('div', { class: 'qc-detail' }, f.detail));
      tr.appendChild(prob);
      var st = status[f.key] || 'open';
      tr.appendChild(el('td', {}, st === 'open' ? 'Open' : st === 'edited' ? 'Edited' : 'Fine'));
      var act = el('td');
      if (st === 'open') {
        var fine = el('button', { type: 'button', class: 'btn btn-sm' }, 'Mark fine');
        fine.addEventListener('click', function () { markFine(f, fine); });
        act.appendChild(fine);
      }
      tr.appendChild(act);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var wrap = el('div', { class: 'table-wrap' });
    wrap.appendChild(table);
    root.appendChild(wrap);
  }

  function renderSettings() {
    var c = config();
    var box = el('details', { class: 'card qc-settings' });
    if (!configured()) box.open = true;
    box.appendChild(el('summary', {}, configured()
      ? 'Saving to the Google Sheet is set up'
      : 'Set up saving to the Google Sheet'));
    box.appendChild(el('p', { class: 'tool-note' },
      'Paste the HF Archive Export web app URL and the QC token that setupQc() logged. ' +
      'Both stay in this browser only.'));
    var url = el('input', { type: 'url', placeholder: 'https://script.google.com/macros/s/.../exec',
                            'aria-label': 'Web app URL', class: 'qc-input-wide' });
    url.value = c.url || '';
    var tok = el('input', { type: 'password', placeholder: 'QC token', 'aria-label': 'QC token',
                            class: 'qc-input-wide', autocomplete: 'off' });
    tok.value = c.token || '';
    var save = el('button', { type: 'button', class: 'btn' }, 'Save and test');
    var msg = el('p', { class: 'tool-note', role: 'status' });
    save.addEventListener('click', function () {
      store(KEY_CFG, JSON.stringify({ url: url.value.trim(), token: tok.value.trim() }));
      msg.textContent = 'Testing...';
      loadLog(function (err, n) {
        msg.textContent = err ? 'Could not reach the sheet: ' + err
                              : 'Connected. The QC log has ' + n + ' entries.';
        if (!err) renderPanel();
      });
    });
    var row = el('div', { class: 'qc-settings-row' });
    row.appendChild(url); row.appendChild(tok); row.appendChild(save);
    box.appendChild(row);
    box.appendChild(msg);
    return box;
  }

  function loadLog(done) {
    if (!configured()) { if (done) done('not set up'); return; }
    fetchLog().then(function (res) {
      if (!res.ok) throw new Error(res.error);
      status = {};
      applyLog(res.entries);
      if (done) done(null, res.entries.length);
    }).catch(function (e) { if (done) done(e.message || String(e)); });
  }

  function openFlag(f) {
    var map = document.querySelector('.tab[data-panel="map"]');
    if (map) map.click();
    API.select(f.lowKey);
  }

  function markFine(f, btn) {
    if (!configured()) { window.alert('Set up saving to the Google Sheet first (top of the QC tab).'); return; }
    var note = window.prompt('Why is this fine? (optional, goes in the QC log)', '') ;
    if (note === null) return;
    btn.disabled = true;
    post({ action: 'ok', flag: f.key, basin: f.basin, id: f.id, date: f.date || '', note: note })
      .then(function (res) {
        if (!res.ok) throw new Error(res.error);
        status[f.key] = 'fine';
        renderPanel();
      })
      .catch(function (e) { btn.disabled = false; window.alert('Not saved: ' + (e.message || e)); });
  }

  /* ------------------------------------------------------ detail drawer */

  var FIELDS = [['date', 'Time (YYYYMMDDHH)'], ['lat', 'Lat'], ['lon', 'Lon'], ['cat', 'Cat'], ['pres', 'hPa']];

  function asText(v) { return v == null ? '' : String(v); }

  function decorateDetail(low, body) {
    var flags = flagsFor(low);
    var box = el('section', { class: 'qc-drawer' });
    box.appendChild(el('h3', {}, 'QC'));
    if (flags.length) {
      var ul = el('ul', { class: 'qc-flaglist' });
      flags.forEach(function (f) {
        var st = status[f.key] || 'open';
        var li = el('li', {});
        li.appendChild(el('b', {}, KINDS[f.kind] + (st !== 'open' ? ' (' + (st === 'fine' ? 'fine' : 'edited') + ')' : '')));
        li.appendChild(document.createTextNode(' ' + f.detail));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    } else {
      box.appendChild(el('p', { class: 'tool-note' }, 'No QC flags on this event. Any fix can still be edited.'));
    }

    var marked = {}, suggest = {};
    flags.forEach(function (f) {
      f.fixDates.forEach(function (d) { marked[d] = f; });
      if (f.suggest) suggest[f.date] = f;
    });

    var table = el('table', { class: 'data-table qc-fixes' });
    var hr = el('tr');
    ['Time', 'Lat', 'Lon', 'Cat', 'hPa', ''].forEach(function (h) { hr.appendChild(el('th', {}, h)); });
    var thead = el('thead'); thead.appendChild(hr); table.appendChild(thead);
    var tbody = el('tbody');
    low.fixes.forEach(function (fix, i) {
      var tr = el('tr', marked[fix.date] ? { class: 'qc-marked' } : {});
      tr.appendChild(el('td', {}, HF.fmtDateShort(fix.date)));
      tr.appendChild(el('td', { class: 'num' }, asText(fix.lat)));
      tr.appendChild(el('td', { class: 'num' }, asText(fix.lon)));
      tr.appendChild(el('td', {}, asText(fix.cat)));
      tr.appendChild(el('td', { class: 'num' }, fix.pres != null ? String(fix.pres) : '--'));
      var td = el('td');
      var btn = el('button', { type: 'button', class: 'btn btn-sm' }, 'Edit');
      btn.addEventListener('click', function () {
        editForm(low, fix, i, tr, marked[fix.date] || null, suggest[fix.date] || null);
      });
      td.appendChild(btn);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var wrap = el('div', { class: 'table-wrap' });
    wrap.appendChild(table);
    box.appendChild(wrap);
    body.appendChild(box);
  }

  function editForm(low, fix, i, afterRow, flagged, suggested) {
    var next = afterRow.nextSibling;
    if (next && next.classList && next.classList.contains('qc-edit')) { next.parentNode.removeChild(next); return; }
    var tr = el('tr', { class: 'qc-edit' });
    var td = el('td', { colspan: '6' });
    var form = el('form', { class: 'qc-form' });
    var inputs = {};
    FIELDS.forEach(function (fd) {
      var lab = el('label', {});
      lab.appendChild(el('span', {}, fd[1]));
      var inp = el('input', { type: 'text', name: fd[0], inputmode: fd[0] === 'cat' ? 'text' : 'decimal',
                              size: fd[0] === 'date' ? '10' : '6' });
      inp.value = asText(fix[fd[0]]);
      inputs[fd[0]] = inp;
      lab.appendChild(inp);
      form.appendChild(lab);
    });
    if (suggested) {
      var use = el('button', { type: 'button', class: 'btn btn-sm' },
        'Use High Seas ' + HF.fmtLatLon(suggested.suggest.lat, suggested.suggest.lon));
      use.addEventListener('click', function () {
        inputs.lat.value = suggested.suggest.lat;
        inputs.lon.value = suggested.suggest.lon;
      });
      form.appendChild(use);
    }
    var note = el('input', { type: 'text', name: 'note', placeholder: 'Note for the QC log (optional)',
                             class: 'qc-input-wide' });
    form.appendChild(note);
    var save = el('button', { type: 'submit', class: 'btn' }, configured() ? 'Save to sheet' : 'Keep for download');
    form.appendChild(save);
    var msg = el('p', { class: 'tool-note', role: 'status' });
    form.appendChild(msg);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var set = {}, expect = {}, before = {}, n = 0;
      FIELDS.forEach(function (fd) {
        var k = fd[0], was = asText(fix[k]), now = inputs[k].value.trim();
        if (now === was) return;
        set[k] = now; before[k] = was; n++;
        // the cell must still hold what this page shows; category is left
        // out because the build maps a few legacy codes on the way in
        if (k !== 'cat') expect[k] = was;
      });
      if (!n) { msg.textContent = 'Nothing changed.'; return; }
      var flagKey = flagged ? flagged.key : '';
      var rec = { basin: low.basin, id: low.id, date: fix.date, before: before, after: set,
                  saved: false, error: '', time: new Date().toISOString(), note: note.value };
      edits.push(rec);
      if (!configured()) {
        msg.textContent = 'Kept for the corrections download; saving to the sheet is not set up.';
        renderPanel();
        return;
      }
      save.disabled = true;
      msg.textContent = 'Saving...';
      post({ action: 'edit', basin: low.basin, id: low.id, date: String(fix.date),
             expect: expect, set: set, flag: flagKey, note: note.value })
        .then(function (res) {
          if (!res.ok) throw new Error(res.error);
          rec.saved = true;
          if (flagKey) status[flagKey] = 'edited';
          msg.textContent = 'Saved to sheet row ' + res.row + '. It shows here after the next publish.';
          renderPanel();
        })
        .catch(function (e) {
          rec.error = e.message || String(e);
          save.disabled = false;
          msg.textContent = 'Not saved: ' + rec.error;
          renderPanel();
        });
    });
    td.appendChild(form);
    tr.appendChild(td);
    afterRow.parentNode.insertBefore(tr, afterRow.nextSibling);
    inputs[flagged && flagged.kind === 'nopres' ? 'pres' : 'lat'].focus();
  }

  function downloadEdits() {
    var lines = ['basin,id,date,field,before,after,saved,error,note'];
    function q(s) { s = asText(s); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
    edits.forEach(function (e) {
      Object.keys(e.after).forEach(function (k) {
        lines.push([e.basin, e.id, e.date, k, e.before[k], e.after[k], e.saved ? 'yes' : 'no', e.error, e.note].map(q).join(','));
      });
    });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/csv' }));
    a.download = 'hf-lows-qc-corrections.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  }

  /* --------------------------------------------------------------- init */

  var enabled = typeof window.location === 'object' && enabledFromUrl();

  // Runs before app.js wires the tabs, so a hidden QC tab never enters the
  // keyboard tab order.
  if (typeof document === 'object' && !enabled) {
    ['tab-qc-btn', 'panel-qc'].forEach(function (id) {
      var n = document.getElementById(id);
      if (n) n.parentNode.removeChild(n);
    });
  } else if (typeof document === 'object') {
    var b = document.getElementById('tab-qc-btn');
    if (b) b.hidden = false;
  }

  HF.qc = {
    enabled: enabled,
    buildFlags: buildFlags,
    fastestLeg: fastestLeg,
    /** app.js calls this once the payload is decoded. api.select(key) opens an event. */
    init: function (data, api) {
      if (!enabled) return;
      DATA = data; API = api;
      FLAGS = buildFlags(DATA);
      document.body.classList.add('qc-on');
      renderPanel();
      loadLog(function (err) { if (!err) renderPanel(); });
    },
    decorateDetail: function (low, body) { if (enabled && DATA) decorateDetail(low, body); }
  };
})(window.HF);
