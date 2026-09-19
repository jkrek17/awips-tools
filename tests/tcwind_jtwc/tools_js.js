#!/usr/bin/env node
/**
 * CLI wrapper around the JavaScript side of the tool, mirroring tools_py.py
 * so the two can be diffed fixture-by-fixture by compare_py_js.py.
 *
 *   node tools_js.js parse   <bulletin.txt>            Code.gs parser
 *   node tools_js.js parsev  <bulletin.txt>            Vortex.html parser
 *   node tools_js.js gtcm    <snapshot.json> <points.json>
 *   node tools_js.js perquad <snapshot.json> <points.json>
 *
 * Vortex.html is the single source of truth for the client vortex math and
 * loads cleanly: it is one <script> block of pure functions with no DOM, no
 * Leaflet and no Apps Script services, so it runs as-is in a vm context
 * with nothing but a `window` object to export onto.  No truncation, no
 * marker hunting - that hack existed only because the math used to live in
 * the middle of Index.html's page code.
 *
 * `perquad` is the retired per-quadrant construction, whose only JS copy is
 * still inside Index.html's page script.  That one DOES need the old
 * truncate-before-Leaflet trick, and it is deliberately kept quarantined in
 * loadIndexPerquad() rather than shared with anything else.  If Index.html
 * stops carrying vortexAt() - which is expected once the page is rebuilt on
 * top of Vortex.html - this command exits 3 and compare_py_js.py reports the
 * group as SKIPPED with a reason instead of failing.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO_ROOT = path.join(__dirname, '..', '..');
const CODE_GS = path.join(REPO_ROOT, 'web', 'TCWind_JTWC', 'Code.gs');
const INDEX_HTML = path.join(REPO_ROOT, 'web', 'TCWind_JTWC', 'Index.html');
const VORTEX_HTML = path.join(REPO_ROOT, 'web', 'TCWind_JTWC', 'Vortex.html');

const EXIT_UNAVAILABLE = 3;   // "this construction no longer exists in JS"

function fail(msg) {
  process.stderr.write(msg + '\n');
  process.exit(EXIT_UNAVAILABLE);
}

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------

function scriptBlock(file) {
  const html = fs.readFileSync(file, 'utf8');
  const m = /<script>([\s\S]*?)<\/script>/.exec(html);
  if (!m) throw new Error('no <script> block in ' + path.basename(file));
  return m[1];
}

/** Vortex.html in its own vm context. Its export block writes onto `window`,
 *  and here `window` IS the sandbox, so everything lands as a sandbox
 *  property and is reachable from Node. */
function loadVortex() {
  const sandbox = { console: console };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(scriptBlock(VORTEX_HTML), sandbox, { filename: 'Vortex.html' });
  if (typeof sandbox.fitGTCM !== 'function') {
    throw new Error('Vortex.html did not export fitGTCM');
  }
  return sandbox;
}

function loadCodeGs() {
  const sandbox = { console: console };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(CODE_GS, 'utf8'), sandbox, { filename: 'Code.gs' });
  return sandbox;
}

/** Legacy: the per-quadrant vortex, which only exists inside Index.html's
 *  page script. Everything after the "Map" section touches Leaflet and the
 *  DOM at load time, so the source is cut there. The driver is appended to
 *  the SAME runInContext call because Index.html's tunables are `const` -
 *  lexical bindings that never become sandbox properties, so a second,
 *  separate call could not see them. */
function loadIndexPerquad(driver) {
  const full = scriptBlock(INDEX_HTML);
  if (full.indexOf('function vortexAt(') < 0) {
    fail('Index.html no longer defines vortexAt(); the per-quadrant vortex has ' +
         'no JavaScript implementation left to compare against.');
  }
  let cut = full.search(/\n\/\/ -{10,}\n\/\/ Map\n/);
  if (cut < 0) cut = full.indexOf('const map = L.map(');
  if (cut < 0) {
    fail('Index.html: could not find the Map-section marker to truncate at.');
  }
  const sandbox = { console: console };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(full.slice(0, cut) + '\n' + driver, sandbox,
                  { filename: 'Index.html:perquad' });
  return sandbox;
}

// ---------------------------------------------------------------------------
// Shared shaping
// ---------------------------------------------------------------------------

function tauToObj(t) {
  const radii = {};
  for (const k of Object.keys(t.radii).sort()) radii[k] = t.radii[k];
  return {
    tau: t.tau, epoch: t.epoch, lat: t.lat, lon: t.lon, vmax: t.vmax,
    gust: t.gust, radii: radii, motionDir: t.motionDir,
    motionSpd: t.motionSpd, conf: t.conf,
  };
}

/** JSON has no NaN. Python's json.dumps emits a bare NaN token, JS's emits
 *  null; normalising to null on this side and on the Python side keeps the
 *  radii-less fit (rms = NaN) comparable instead of a parse error. */
function jnum(x) {
  return (typeof x === 'number' && !isFinite(x)) ? null : x;
}

function readSnap(file) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const radii = {};
  Object.keys(raw.radii || {}).forEach(function (k) { radii[k] = raw.radii[k]; });
  return {
    raw: raw,
    snap: {
      lat: raw.lat, lon: raw.lon, vmax: raw.vmax, radii: radii,
      motionDir: raw.motionDir || 0, motionSpd: raw.motionSpd || 0,
    },
  };
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function cmdParse(file) {
  const sandbox = loadCodeGs();
  if (typeof sandbox.parseJTWC !== 'function') {
    fail('Code.gs no longer defines parseJTWC().');
  }
  const result = sandbox.parseJTWC(fs.readFileSync(file, 'utf8'));
  process.stdout.write(JSON.stringify(
    { header: result.header, taus: result.taus.map(tauToObj) }));
}

function cmdParseVortex(file) {
  const sandbox = loadVortex();
  const result = sandbox.parseJTWC(fs.readFileSync(file, 'utf8'));
  process.stdout.write(JSON.stringify(
    { header: result.header, taus: result.taus.map(tauToObj) }));
}

function cmdGtcm(snapshotFile, pointsFile) {
  const V = loadVortex();
  const { raw, snap } = readSnap(snapshotFile);
  const points = JSON.parse(fs.readFileSync(pointsFile, 'utf8'));

  const rmax = V.resolveRmax(snap, raw.rmaxOverride || 0);
  const field = V.vortexFieldGTCM(snap);
  const f = field.fit;

  process.stdout.write(JSON.stringify({
    rmax: rmax,
    fit: { rm: jnum(f.rm), ri: jnum(f.ri), x1: jnum(f.x1), x2: jnum(f.x2),
           ax: jnum(f.ax), ay: jnum(f.ay), a: jnum(f.a), n: f.n,
           freeParams: f.freeParams, rmSource: f.rmSource,
           rms: jnum(f.rms) },
    points: points.map(function (p) {
      const s = field.at(p[0], p[1]);
      return { lat: p[0], lon: p[1], mag: jnum(s.mag), dir: jnum(s.dir),
               r: jnum(s.r), r34: jnum(s.r34), az: jnum(s.az) };
    }),
  }));
}

function cmdPerquad(snapshotFile, pointsFile) {
  const { raw, snap } = readSnap(snapshotFile);
  const points = JSON.parse(fs.readFileSync(pointsFile, 'utf8'));
  const driver = `
    var __snap__ = ${JSON.stringify(snap)};
    var __points__ = ${JSON.stringify(points)};
    var __rmax__ = resolveRmax(__snap__, ${JSON.stringify(raw.rmaxOverride || 0)});
    var __out__ = { rmax: __rmax__, points: __points__.map(function (p) {
      var res = vortexAt(p[0], p[1], __snap__, __rmax__,
        MOTION_ASYMMETRY_FRACTION, INFLOW_ANGLE_DEG);
      return { lat: p[0], lon: p[1], mag: res.mag, dir: res.dir,
               r: res.r, r34: res.r34 };
    }) };
  `;
  const sandbox = loadIndexPerquad(driver);
  process.stdout.write(JSON.stringify(sandbox.__out__));
}

// ---------------------------------------------------------------------------

const [, , cmd, ...rest] = process.argv;
if (cmd === 'parse') {
  cmdParse(rest[0]);
} else if (cmd === 'parsev') {
  cmdParseVortex(rest[0]);
} else if (cmd === 'gtcm') {
  cmdGtcm(rest[0], rest[1]);
} else if (cmd === 'perquad' || cmd === 'vortex') {
  // "vortex" kept as an alias: it is what the command was called before the
  // GTCM port, and nothing is served by breaking a name in a test harness.
  cmdPerquad(rest[0], rest[1]);
} else {
  console.error('usage: tools_js.js parse|parsev <file>');
  console.error('       tools_js.js gtcm|perquad <snapshot.json> <points.json>');
  process.exit(2);
}
