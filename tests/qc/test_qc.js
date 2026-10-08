/* QC mode: flag building in docs/assets/js/qc.js and the sheet write path
   in web/HFArchiveExport/Code.gs.   node tests/qc/test_qc.js */
'use strict';
const path = require('path');
const { load } = require('./gas_mock');

let pass = 0, fail = 0;
function ok(cond, name) { if (cond) pass++; else { fail++; console.log('FAIL ' + name); } }

// ---------------------------------------------------------------- qc.js
global.window = {};
require(path.join(__dirname, '..', '..', 'docs', 'assets', 'js', 'qc.js'));
const QC = global.window.HF.qc;
ok(QC.enabled === false, 'off without a page URL');

const fixes = [
  { date: 2007010500, lat: 41.0, lon: -60, cat: 'S', pres: 990 },
  { date: 2007010506, lat: 43.0, lon: -58, cat: 'HF', pres: null },
  { date: 2007010512, lat: 56.3, lon: -55, cat: 'HF', pres: 975 },
  { date: 2007010518, lat: 46.9, lon: -52, cat: 'HF', pres: 972 }
];
const leg = QC.fastestLeg(fixes);
ok(leg && leg[0] === 1 && leg[1] === 2 && leg[2] > 100, 'fastest leg is the mistyped latitude');

const data = {
  lows: [
    { key: 'atl:2006200703', basin: 'atl', id: '2006200703', fixes: fixes },
    { key: 'atl:2006200704', basin: 'atl', id: '2006200704',
      fixes: [{ date: 2007010800, lat: 50, lon: -40, cat: 'S', pres: 990 }] },
    { key: 'pac:2004200502a', basin: 'pac', id: '2004200502a',
      fixes: [{ date: 2005010100, lat: 40, lon: 170, cat: 'HF', pres: 970 }] }
  ],
  qc: {
    notes: [
      { basin: 'atl', id: '2006200703', date: 2007010500, kind: 'speed-implausible', detail: 'x' },
      { basin: 'atl', id: '2006200703', date: 2007010500, kind: 'speed-implausible', detail: 'x' },
      { basin: 'pac', id: '2004200502', row: 77, date: 2005010100, kind: 'pressure-dropped', detail: 'p' },
      { basin: 'atl', id: '2006200703', date: null, kind: 'id-reused', detail: 'ignored' }
    ],
    positionSuspects: [{ basin: 'atl', id: '2006200703', date: 2007010512, lat: 56.3, lon: -55,
                         pres: 975, hsfLat: 46.3, hsfLon: -55, nm: 600, ktAsIs: 133, ktMoved: 38 }],
    collisions: [
      { basin: 'atl', id: '2006200704', other: '2006200703', kind: 'sequential', gapH: 18, linkKt: 20 },
      { basin: 'atl', id: '2006200704', other: '2006200703', kind: 'concurrent' }
    ]
  }
};
const flags = QC.buildFlags(data);
const kinds = flags.map(f => f.kind);
ok(kinds.filter(k => k === 'motion').length === 1, 'duplicate note gives one motion flag');
const motion = flags.find(f => f.kind === 'motion');
ok(motion.fixDates.join() === '2007010506,2007010512', 'motion flag marks both fixes of the leg');
const pos = flags.find(f => f.kind === 'position');
ok(pos && pos.suggest.lat === 46.3 && pos.date === 2007010512, 'position flag carries the High Seas fix');
ok(kinds.includes('nopres'), 'first HF fix without pressure is flagged');
ok(flags.find(f => f.kind === 'nohf' && f.id === '2006200704'), 'event with no HF fix is flagged');
ok(flags.filter(f => f.kind === 'split').length === 1, 'only sequential collisions become split flags');
const row = flags.find(f => f.kind === 'row');
ok(row && row.id === '2004200502a' && row.row === 77, 'row note maps to the split event id');
ok(!kinds.includes('undefined') && flags.every(f => f.key), 'every flag has a key');
ok(new Set(flags.map(f => f.key)).size === flags.length, 'flag keys are unique');

// ---------------------------------------------------------------- Code.gs
const header = ['ID', 'date', 'Latitude', 'Longitude', 'Category', 'Pressure'];
function fresh() {
  return load({
    'HF Data - Atl': [header,
      ['2006200703', '2007010506', '43', '-58', 'HF', ''],
      ['2006200703', '2007010512', '56.3', '-55', 'HF', '975'],
      ['2006200799', '2007020100', '50', '-40', 'HF', '980'],
      ['2006200799', '2007020100', '51', '-41', 'HF', '978']],
    'HF Data - Pac': [header]
  }, { QC_TOKEN: 'secret', EXPORT_TOKEN: 'export' });
}
function call(env, body) { return env.ctx.handleQcPost_(body, env.ss); }

let env = fresh();
let r = call(env, { token: 'export', action: 'edit', basin: 'atl', id: '2006200703', date: '2007010512',
                    set: { lat: 46.3 } });
ok(!r.ok && /QC token/.test(r.error), 'the export token cannot write');

r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200703', date: '2007010512',
                expect: { lat: '56.3' }, set: { lat: '46.3' }, flag: 'position|atl|2006200703|2007010512|' });
ok(r.ok && r.row === 3, 'edit lands on the matching row');
ok(env.sheets[0].rows[2][2] === '46.3', 'cell is written');
const log = env.sheets.find(s => s.getName() === 'QC log');
ok(log && log.rows.length === 2 && log.rows[1][1] === 'edit' && /56.3/.test(log.rows[1][7]), 'edit is logged with before value');

r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200703', date: '2007010512',
                expect: { lat: '56.3' }, set: { lat: '46.0' } });
ok(!r.ok && r.conflict, 'stale expect value is refused');

r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200703a', date: '2007010506',
                set: { pres: '981' } });
ok(r.ok && env.sheets[0].rows[1][5] === '981', 'split-letter id resolves to the sheet id');

r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200799', date: '2007020100',
                set: { date: '2007020106' } });
ok(!r.ok && /more than one/.test(r.error), 'duplicate timestamp needs disambiguation');
r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200799', date: '2007020100',
                expect: { lat: '51' }, set: { date: '2007020106' } });
ok(r.ok && r.row === 5 && env.sheets[0].rows[4][1] === '2007020106', 'expect values pick the duplicate row');

r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200703', date: '2007010506',
                set: { lat: '95' } });
ok(!r.ok && /out of range/.test(r.error), 'out-of-range latitude refused');
r = call(env, { token: 'secret', action: 'edit', basin: 'atl', id: '2006200703', date: '2007010506',
                set: { id: '1' } });
ok(!r.ok && /cannot be edited/.test(r.error), 'only fix fields are editable');

r = call(env, { token: 'secret', action: 'ok', flag: 'nohf|atl|1||', basin: 'atl', id: '1', note: 'checked' });
ok(r.ok && log.rows[log.rows.length - 1][1] === 'ok', 'mark fine is logged');
const got = env.ctx.handleQcGet_({ qc: 'log', token: 'secret' });
ok(got.ok && got.entries.length === 4 && got.entries[3].action === 'ok', 'log reads back as JSON');
ok(!env.ctx.handleQcGet_({ qc: 'log', token: 'export' }).ok, 'log needs the QC token');

env = load({ 'HF Data - Atl': [header] }, { EXPORT_TOKEN: 'export' });
r = call(env, { token: '', action: 'ok' });
ok(!r.ok && /setupQc/.test(r.error), 'writes refused until setupQc has run');

console.log(pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
