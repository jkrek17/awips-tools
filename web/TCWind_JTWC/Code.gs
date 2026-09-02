/**
 * JTWC Tropical Cyclone Wind - web preview
 *
 * *** EXPERIMENTAL. NOT OPERATIONALLY VETTED. ***
 *
 * Server side of a Google Apps Script web app that mirrors the GFE
 * procedure TCWind_JTWC.py. It fetches JTWC warnings from the NWS
 * Telecommunications Gateway, parses them, and hands the result to the
 * Leaflet page for display.
 *
 * The parser here is a line-for-line port of parseJTWC() in the Python
 * tool. If you change one, change the other, and re-run runSelfTest().
 *
 * Deploy: Extensions > Apps Script, add Code.gs and Index.html, then
 * Deploy > New deployment > Web app.
 */

var VERSION = '2026-09-02a';

var BULLETIN_BASE = 'https://tgftp.nws.noaa.gov/data/raw/wt/';

// NW Pacific tropical cyclone warnings, storms 1-5. These are the same
// products as the NFDTCPWP1-5 bins in the AWIPS text database, under their
// WMO headings instead of the AWIPS PIL.
var BULLETIN_FILES = [
  'wtpn31.pgtw..txt',
  'wtpn32.pgtw..txt',
  'wtpn33.pgtw..txt',
  'wtpn34.pgtw..txt',
  'wtpn35.pgtw..txt'
];

var CACHE_SECONDS = 1800;
var MAX_BULLETIN_AGE_HOURS = 12;

var MONTHS = {
  JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6,
  JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12
};

var QUADS = ['NE', 'SE', 'SW', 'NW'];
var QUAD_WORD = {
  NORTHEAST: 'NE', SOUTHEAST: 'SE', SOUTHWEST: 'SW', NORTHWEST: 'NW'
};

var CONF_TROPICAL = 1.0;
var CONF_BECOMING = 0.6;
var CONF_SUBTROPICAL = 0.25;


// ---------------------------------------------------------------------------
// Web app entry point
// ---------------------------------------------------------------------------

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('JTWC TC Wind preview (EXPERIMENTAL)')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}


// ---------------------------------------------------------------------------
// Retrieval
// ---------------------------------------------------------------------------

/**
 * Fetch and parse all five NW Pacific warning slots.
 * Returns an array of {file, ok, error, stale, ageHours, storm}.
 */
function getBulletins(force) {
  var cache = CacheService.getScriptCache();
  var nowSecs = Math.floor(new Date().getTime() / 1000);
  var out = [];

  for (var i = 0; i < BULLETIN_FILES.length; i++) {
    var file = BULLETIN_FILES[i];
    var entry = { file: file, ok: false, error: null, stale: false };

    var text = force ? null : cache.get(file);
    if (!text) {
      try {
        var resp = UrlFetchApp.fetch(BULLETIN_BASE + file, {
          muteHttpExceptions: true,
          followRedirects: true,
          validateHttpsCertificates: true
        });
        if (resp.getResponseCode() !== 200) {
          entry.error = 'HTTP ' + resp.getResponseCode();
          out.push(entry);
          continue;
        }
        text = resp.getContentText();
        if (text && text.length < 100000) {
          cache.put(file, text, CACHE_SECONDS);
        }
      } catch (err) {
        entry.error = String(err);
        out.push(entry);
        continue;
      }
    }

    if (!text || text.replace(/\s/g, '').length < 200) {
      entry.error = 'slot empty';
      out.push(entry);
      continue;
    }

    try {
      var storm = parseJTWC(text);
      if (storm.taus.length < 2) {
        entry.error = 'only ' + storm.taus.length + ' usable forecast times';
        out.push(entry);
        continue;
      }
      // textdb and tgftp both serve the last product stored, so a
      // dissipated storm sits in its slot indefinitely. Judge by the
      // bulletin's own analysis time, exactly as the GFE tool does.
      var ageHours = (nowSecs - storm.taus[0].epoch) / 3600.0;
      entry.ageHours = ageHours;
      entry.stale = (ageHours > MAX_BULLETIN_AGE_HOURS) ||
                    (storm.taus[storm.taus.length - 1].epoch <= nowSecs);
      storm.file = file;
      storm.pil = 'NFDTCPWP' + (i + 1);
      entry.storm = storm;
      entry.ok = true;
    } catch (err2) {
      entry.error = String(err2);
    }
    out.push(entry);
  }
  return out;
}


/** Parse pasted bulletin text. Used when tgftp is unreachable. */
function parsePasted(text) {
  var storm = parseJTWC(text);
  storm.file = 'pasted';
  storm.pil = 'pasted';
  return { file: 'pasted', ok: true, error: null, stale: false, storm: storm };
}


// ---------------------------------------------------------------------------
// Parser - port of parseJTWC() in TCWind_JTWC.py
// ---------------------------------------------------------------------------

function dtgToEpoch(ddhhmm, refDay, refMonth, refYear) {
  var dd = parseInt(ddhhmm.substring(0, 2), 10);
  var hh = parseInt(ddhhmm.substring(2, 4), 10);
  var mm = parseInt(ddhhmm.substring(4, 6), 10);

  var month = refMonth, year = refYear;
  if (dd < refDay && (refDay - dd) > 15) {
    month += 1;
    if (month > 12) { month = 1; year += 1; }
  } else if (dd > refDay && (dd - refDay) > 15) {
    month -= 1;
    if (month < 1) { month = 12; year -= 1; }
  }
  return Date.UTC(year, month - 1, dd, hh, mm, 0) / 1000;
}


function emptyQuads() {
  return { NE: 0, SE: 0, SW: 0, NW: 0 };
}


function parseJTWC(text) {
  var lines = text.split(/\r?\n/);

  var refDay = null, refMonth = null, refYear = null;
  for (var i = 0; i < lines.length; i++) {
    var m = /\b(\d{2})([A-Z]{3})(\d{2})\b/.exec(lines[i]);
    if (m && MONTHS[m[2]]) {
      refDay = parseInt(m[1], 10);
      refMonth = MONTHS[m[2]];
      refYear = 2000 + parseInt(m[3], 10);
      break;
    }
  }
  if (refDay === null) {
    throw new Error('no DDMMMYY reference date in remarks; cannot resolve DTGs');
  }

  var taus = [];
  var cur = null;
  var curThreshold = null;
  var inRemarks = false;

  for (var j = 0; j < lines.length; j++) {
    var ln = lines[j];

    if (/^\s*REMARKS:/.test(ln)) inRemarks = true;

    if (!inRemarks) {
      if (/^\s*WARNING POSITION:/.test(ln)) {
        cur = { tau: 0, epoch: null, lat: null, lon: null, vmax: null,
                gust: null, radii: {}, motionDir: null, motionSpd: null,
                conf: CONF_TROPICAL };
        taus.push(cur);
        curThreshold = null;
        continue;
      }
      var mt = /^\s*(\d+)\s+HRS,\s+VALID AT:/.exec(ln);
      if (mt) {
        cur = { tau: parseInt(mt[1], 10), epoch: null, lat: null, lon: null,
                vmax: null, gust: null, radii: {}, motionDir: null,
                motionSpd: null, conf: CONF_TROPICAL };
        taus.push(cur);
        curThreshold = null;
        continue;
      }
    }

    if (!cur) continue;
    if (inRemarks) continue;

    var mp = /(\d{6})Z\s*---\s*(?:NEAR\s+)?(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])/.exec(ln);
    if (mp && cur.lat === null) {
      cur.epoch = dtgToEpoch(mp[1], refDay, refMonth, refYear);
      var lat = parseFloat(mp[2]); if (mp[3] === 'S') lat = -lat;
      var lon = parseFloat(mp[4]); if (mp[5] === 'W') lon = -lon;
      cur.lat = lat; cur.lon = lon;
      continue;
    }

    var mw = /MAX SUSTAINED WINDS\s*-\s*(\d+)\s*KT(?:\s*,\s*GUSTS\s*(\d+)\s*KT)?/.exec(ln);
    if (mw) {
      cur.vmax = parseFloat(mw[1]);
      if (mw[2]) cur.gust = parseFloat(mw[2]);
      continue;
    }

    var mrs = /RADIUS OF\s+(\d+)\s*KT WINDS\s*-\s*(\d+)\s*NM\s+(\w+)\s+QUADRANT/.exec(ln);
    if (mrs) {
      curThreshold = parseInt(mrs[1], 10);
      if (!cur.radii[curThreshold]) cur.radii[curThreshold] = emptyQuads();
      var q1 = QUAD_WORD[mrs[3].toUpperCase()];
      if (q1) cur.radii[curThreshold][q1] = parseFloat(mrs[2]);
      continue;
    }

    var mrc = /^\s*(\d+)\s*NM\s+(\w+)\s+QUADRANT/.exec(ln);
    if (mrc && curThreshold !== null) {
      var q2 = QUAD_WORD[mrc[2].toUpperCase()];
      if (q2) cur.radii[curThreshold][q2] = parseFloat(mrc[1]);
      continue;
    }

    var mm2 = /MOVEMENT PAST SIX HOURS\s*-\s*(\d+)\s*DEGREES AT\s*(\d+)\s*KTS/.exec(ln);
    if (mm2) {
      cur.motionDir = parseFloat(mm2[1]);
      cur.motionSpd = parseFloat(mm2[2]);
      continue;
    }

    var mv = /VECTOR TO\s+(\d+)\s*HR POSIT:\s*(\d+)\s*DEG\/\s*(\d+)\s*KTS/.exec(ln);
    if (mv) {
      cur.motionDir = parseFloat(mv[2]);
      cur.motionSpd = parseFloat(mv[3]);
      continue;
    }

    if (ln.indexOf('BECOMING SUBTROPICAL') >= 0 ||
        ln.indexOf('BECOMING EXTRATROPICAL') >= 0) {
      cur.conf = CONF_BECOMING;
    } else if (/^\s*(SUB|EXTRA)TROPICAL\s*$/.test(ln)) {
      cur.conf = CONF_SUBTROPICAL;
    }
  }

  taus = taus.filter(function (t) {
    return t.lat !== null && t.epoch !== null && t.vmax !== null;
  });
  taus.sort(function (a, b) { return a.epoch - b.epoch; });

  // Once flagged, a system stays flagged downstream.
  var worst = CONF_TROPICAL;
  for (var k = 0; k < taus.length; k++) {
    worst = Math.min(worst, taus[k].conf);
    taus[k].conf = worst;
  }

  // Backfill motion where a block had no vector line.
  for (var n = 0; n < taus.length; n++) {
    if (taus[n].motionSpd === null) {
      if (n + 1 < taus.length) {
        var bs = bearingSpeed(taus[n], taus[n + 1]);
        taus[n].motionDir = bs[0];
        taus[n].motionSpd = bs[1];
      } else if (n > 0) {
        taus[n].motionDir = taus[n - 1].motionDir;
        taus[n].motionSpd = taus[n - 1].motionSpd;
      } else {
        taus[n].motionDir = 0; taus[n].motionSpd = 0;
      }
    }
  }

  var full = lines.join('\n');
  var header = {
    refDate: [refDay, refMonth, refYear],
    systemType: null, stormId: null, stormName: null,
    warningNumber: null, pressureMb: null
  };

  var ms = /(SUPER TYPHOON|TYPHOON|TROPICAL STORM|TROPICAL DEPRESSION|SUBTROPICAL STORM|SUBTROPICAL DEPRESSION)\s+(\d{1,2}[A-Z])\s*(?:\(([^)]+)\))?/.exec(full);
  if (ms) {
    header.systemType = ms[1];
    header.stormId = ms[2];
    header.stormName = ms[3] || null;
  }
  var mn = /WARNING\s+NR\s+(\d+)/.exec(full);
  if (mn) header.warningNumber = parseInt(mn[1], 10);

  // \s+ between words, not a literal space: REMARKS text is word-wrapped at
  // ~72 columns and "MINIMUM CENTRAL PRESSURE" does land split across a
  // line break in real bulletins, which a literal space would silently miss.
  var mpr = /MINIMUM\s+CENTRAL\s+PRESSURE[\s\S]*?(\d+)\s*MB/.exec(full);
  if (mpr) header.pressureMb = parseInt(mpr[1], 10);

  return { header: header, taus: taus, text: text };
}


function bearingSpeed(t1, t2) {
  var R = 3440.065;
  var lat1 = t1.lat * Math.PI / 180, lon1 = t1.lon * Math.PI / 180;
  var lat2 = t2.lat * Math.PI / 180, lon2 = t2.lon * Math.PI / 180;
  var dlon = lon2 - lon1;
  var y = Math.sin(dlon) * Math.cos(lat2);
  var x = Math.cos(lat1) * Math.sin(lat2) -
          Math.sin(lat1) * Math.cos(lat2) * Math.cos(dlon);
  var brg = ((Math.atan2(y, x) * 180 / Math.PI) % 360 + 360) % 360;

  var a = Math.pow(Math.sin((lat2 - lat1) / 2), 2) +
          Math.cos(lat1) * Math.cos(lat2) * Math.pow(Math.sin(dlon / 2), 2);
  var dist = 2 * R * Math.asin(Math.sqrt(Math.min(Math.max(a, 0), 1)));
  var dt = Math.max(t2.epoch - t1.epoch, 1) / 3600.0;
  return [brg, dist / dt];
}


function describeStorm(header) {
  var bits = [];
  if (header.systemType) bits.push(header.systemType);
  if (header.stormId) bits.push(header.stormId);
  if (header.stormName) bits.push('(' + header.stormName + ')');
  var label = bits.length ? bits.join(' ') : 'unidentified system';
  if (header.warningNumber !== null) label += ' warning ' + header.warningNumber;
  return label;
}


// ---------------------------------------------------------------------------
// Self test
// ---------------------------------------------------------------------------

/**
 * Run from the editor. Fetches every live slot and reports what parsed,
 * so a parser change can be checked against real products before anyone
 * looks at the map.
 */
function runSelfTest() {
  var res = getBulletins(true);
  var lines = ['JTWC parser self test, v' + VERSION, ''];
  for (var i = 0; i < res.length; i++) {
    var r = res[i];
    if (!r.ok) {
      lines.push(r.file + ': ' + (r.error || 'no data'));
      continue;
    }
    var s = r.storm;
    lines.push(r.file + ': ' + describeStorm(s.header) +
               ', ' + s.taus.length + ' forecast times' +
               ', age ' + r.ageHours.toFixed(1) + ' h' +
               (r.stale ? ' [STALE]' : ''));
    for (var j = 0; j < s.taus.length; j++) {
      var t = s.taus[j];
      var rr = Object.keys(t.radii).sort().join('/');
      lines.push('   ' + t.tau + 'h  ' + t.lat.toFixed(1) + ' ' +
                 t.lon.toFixed(1) + '  ' + t.vmax + ' kt  radii ' +
                 (rr || 'none'));
    }
    lines.push('');
  }
  Logger.log(lines.join('\n'));
  return lines.join('\n');
}
