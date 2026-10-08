/* A local stand-in for the deployed HFArchiveExport web app, backed by the
   committed CSVs, for trying QC mode in a browser:
     node tests/qc/serve_mock.js 8766     then open docs/?qc and set the
   endpoint to http://localhost:8766/exec with token "local". Nothing is
   written to disk. */
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const { load } = require('./gas_mock');

function csv(file) {
  return fs.readFileSync(file, 'utf8').trim().split(/\r?\n/).map(l => l.split(','));
}
const dir = path.join(__dirname, '..', '..', 'data', 'hf_lows');
const env = load({ 'HF Data - Atl': csv(path.join(dir, 'HF_Data_-_Atl.csv')),
                   'HF Data - Pac': csv(path.join(dir, 'HF_Data_-_Pac.csv')) },
                 { QC_TOKEN: 'local', EXPORT_TOKEN: 'export' });

http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const send = obj => {
    res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(obj));
  };
  if (req.method === 'GET') {
    const p = {}; u.searchParams.forEach((v, k) => { p[k] = v; });
    return send(env.ctx.handleQcGet_(p));
  }
  let body = '';
  req.on('data', c => { body += c; });
  req.on('end', () => {
    try { send(env.ctx.handleQcPost_(JSON.parse(body), env.ss)); }
    catch (e) { send({ ok: false, error: String(e) }); }
  });
}).listen(Number(process.argv[2] || 8766));
