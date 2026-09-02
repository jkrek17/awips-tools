#!/usr/bin/env node
/**
 * CLI wrapper around Code.gs's parser and Index.html's vortex math, mirroring
 * tools_py.py so the two can be diffed fixture-by-fixture.
 *
 *   node tools_js.js parse <bulletin.txt>
 *   node tools_js.js vortex <snapshot.json> <points.json>
 *
 * Code.gs has no DOM/Apps-Script-service references at parse time, so it can
 * run as-is. Index.html's <script> block, though, builds the Leaflet map as
 * a side effect of loading (`const map = L.map(...)` etc.), which throws in
 * a plain Node vm context - so for the vortex path we cut the script off
 * right before the "Map" section (everything before that point is pure
 * tunables + math functions) and run the truncated source with a small
 * driver appended in the SAME vm.runInContext call, so the driver shares
 * the same top-level scope (including the `const` tunables, which a second,
 * separate runInContext call would not see).
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO_ROOT = path.join(__dirname, '..', '..');
const CODE_GS = path.join(REPO_ROOT, 'web', 'TCWind_JTWC', 'Code.gs');
const INDEX_HTML = path.join(REPO_ROOT, 'web', 'TCWind_JTWC', 'Index.html');

function tauToObj(t) {
  const radii = {};
  for (const k of Object.keys(t.radii).sort()) radii[k] = t.radii[k];
  return {
    tau: t.tau, epoch: t.epoch, lat: t.lat, lon: t.lon, vmax: t.vmax,
    gust: t.gust, radii: radii, motionDir: t.motionDir,
    motionSpd: t.motionSpd, conf: t.conf,
  };
}

function cmdParse(file) {
  const code = fs.readFileSync(CODE_GS, 'utf8');
  const sandbox = { console };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: 'Code.gs' });

  const text = fs.readFileSync(file, 'utf8');
  const result = sandbox.parseJTWC(text);
  const out = { header: result.header, taus: result.taus.map(tauToObj) };
  process.stdout.write(JSON.stringify(out));
}

function extractIndexScript() {
  const html = fs.readFileSync(INDEX_HTML, 'utf8');
  const m = /<script>([\s\S]*)<\/script>/.exec(html);
  if (!m) throw new Error('could not find <script> block in Index.html');
  const full = m[1];
  const cut = full.indexOf('const map = L.map(');
  if (cut < 0) throw new Error('could not find the Map-section marker to truncate at');
  return full.slice(0, cut);
}

function cmdVortex(snapshotFile, pointsFile) {
  const mathSrc = extractIndexScript();
  const snapIn = JSON.parse(fs.readFileSync(snapshotFile, 'utf8'));
  const points = JSON.parse(fs.readFileSync(pointsFile, 'utf8'));

  const driver = `
    var __snapIn__ = ${JSON.stringify(snapIn)};
    var __points__ = ${JSON.stringify(points)};
    var __radii__ = {};
    Object.keys(__snapIn__.radii).forEach(function (k) {
      __radii__[k] = __snapIn__.radii[k];
    });
    var __snap__ = {
      lat: __snapIn__.lat, lon: __snapIn__.lon, vmax: __snapIn__.vmax,
      radii: __radii__,
      motionDir: __snapIn__.motionDir || 0, motionSpd: __snapIn__.motionSpd || 0,
    };
    var __rmax__ = resolveRmax(__snap__, __snapIn__.rmaxOverride || 0);
    var __out__ = { rmax: __rmax__, points: __points__.map(function (p) {
      var res = vortexAt(p[0], p[1], __snap__, __rmax__,
        MOTION_ASYMMETRY_FRACTION, INFLOW_ANGLE_DEG);
      return { lat: p[0], lon: p[1], mag: res.mag, dir: res.dir,
               r: res.r, r34: res.r34 };
    }) };
  `;

  const sandbox = { console };
  vm.createContext(sandbox);
  vm.runInContext(mathSrc + '\n' + driver, sandbox, { filename: 'Index.html:vortex' });
  process.stdout.write(JSON.stringify(sandbox.__out__));
}

const [, , cmd, ...rest] = process.argv;
if (cmd === 'parse') {
  cmdParse(rest[0]);
} else if (cmd === 'vortex') {
  cmdVortex(rest[0], rest[1]);
} else {
  console.error('usage: tools_js.js parse <file> | vortex <snapshot.json> <points.json>');
  process.exit(2);
}
