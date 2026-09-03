/**
 * JTWC Tropical Cyclone Wind - web preview: SERVER SIDE
 *
 * *** EXPERIMENTAL. NOT OPERATIONALLY VETTED. ***
 *
 * Server half of a Google Apps Script web app that mirrors the GFE
 * procedure GFE/procedures/TCWind_JTWC.py.  It does four things and
 * nothing else:
 *
 *   1. fetches real-time tropical cyclone bulletins across three basins -
 *      JTWC's five West Pacific WTPN warnings from the NWS
 *      Telecommunications Gateway, and NHC's five Atlantic + five East
 *      Pacific TCM Forecast/Advisories from NHC's own text server (see
 *      NHC_TEXT_BASE's comment for why that is a different source from
 *      JTWC's) - parses them, and reports slot health
 *      (getBulletins / parsePasted);
 *   2. serves the best-track archive, one storm at a time
 *      (getArchiveIndex / getArchiveStorm);
 *   3. serves the verification numbers the Findings page renders
 *      (getFindings);
 *   4. routes ?page= to the right HTML template (doGet).
 *
 * It does NOT do vortex math.  All wind-field math lives in exactly one
 * place, Vortex.html, and runs client-side.  See "PARSER DUPLICATION"
 * below for the one function that is deliberately duplicated here and how
 * the two copies are kept honest.  Theme.html (design tokens) and
 * Help.html (the shared glossary: term tooltips plus one drop-in
 * <details> glossary block) are two more single-copy client includes -
 * Code.gs never touches either, it only has to keep shipping them so the
 * pages that `<?!= HtmlService.createHtmlOutputFromFile(...) ?>` them do
 * not break. See PAGES below for the top-level templates doGet() serves;
 * Vortex/Theme/Help are partials, included BY those, never routed to
 * directly.
 *
 * Deploy with clasp (see README.md), or Extensions > Apps Script >
 * Deploy > New deployment > Web app.
 *
 * ---------------------------------------------------------------------
 * MANIFEST NOTES (appsscript.json cannot carry comments, so they live here)
 * ---------------------------------------------------------------------
 * - webapp.access is DOMAIN and webapp.executeAs is USER_DEPLOYING.
 *   DOMAIN lets colleagues in the same Workspace domain open the live
 *   tool, the archive and the findings page.  MYSELF would restrict all
 *   three to the deploying account; ANYONE_ANONYMOUS would make them
 *   public.  Changing that is the owner's call, not this file's - it is
 *   deliberately left as found.
 * - executeAs USER_DEPLOYING means every visitor's UrlFetchApp traffic is
 *   billed to the DEPLOYER's quota (see QUOTAS below), and no visitor
 *   needs to grant any scope of their own.  That is the right trade for a
 *   read-only public-data viewer; it also means one deployer's quota is
 *   the ceiling for the whole office.
 * - oauthScopes is deliberately NOT declared.  Apps Script infers the
 *   scope set from the code (script.external_request for UrlFetchApp).
 *   Pinning the list by hand risks omitting a scope some API needs and
 *   failing at runtime instead of at push time.
 *
 * ---------------------------------------------------------------------
 * QUOTAS that actually bite here (Apps Script published limits)
 * ---------------------------------------------------------------------
 * - UrlFetch calls: 20,000/day.  getBulletins(force=true) spends FIFTEEN of
 *   them per call, one per bulletin slot across all three basins (five
 *   WP + five AT + five EP - see BULLETIN_SLOTS). A page that auto-
 *   refreshed every 30 s with force=true would burn 43,200/day on its own;
 *   that is why the 30-minute CacheService layer exists and why force is
 *   opt-in.
 * - CacheService: 100 KB per value, 250-char keys, 6 h (21600 s) maximum
 *   TTL.  Real WTPN/TCM bulletins are 2-5 KB, so they fit with room to
 *   spare.  The best-track archive (~2 MB) does NOT fit in cache under any
 *   slicing worth doing, so it is not cached: it is a script global in
 *   BestTrackData.gs, already resident in the execution.
 * - Script runtime: 6 minutes per execution.  Fifteen sequential fetches
 *   are the only slow path; each has no explicit timeout of its own.
 * - Simultaneous executions: 30 per user.
 * - Apps Script loads and compiles EVERY .gs file in the project for
 *   EVERY execution.  BestTrackData.gs is a ~2 MB JSON literal, so every
 *   call - getBulletins included - pays its parse cost.  That is the
 *   price of serving the archive without an external datastore; if cold
 *   latency becomes a complaint, the fix is to move the archive to Drive
 *   or a Sheet and read it on demand, not to shard it into the cache.
 *
 * ---------------------------------------------------------------------
 * PARSER DUPLICATION - read before touching parseJTWC() or parseTCM() below
 * ---------------------------------------------------------------------
 * parseJTWC() AND parseTCM() each exist TWICE in this repo on the
 * JavaScript side: here, and in Vortex.html.  That is not an oversight
 * and it is not free.  Everything below applies equally to both parsers
 * unless it says otherwise; parseTCM() additionally has no Python side at
 * all (GFE/procedures/TCWind_JTWC.py is JTWC-only by design), so for it
 * the tiebreak at the bottom of this comment is just "Vortex.html wins".
 *
 * Why it cannot be deduplicated by including the shared file: Apps Script
 * server code cannot `include` an HTML file's <script> at load time.  The
 * only ways to reach Vortex.html's code from the server are to read the
 * file and eval it (done below, for the parity check - fine for a
 * verification routine, not something to put on the request path of every
 * bulletin fetch), or to move parsing off the server entirely.
 *
 * Why parsing was NOT moved entirely client-side, which was the other
 * option:
 *   - getBulletins() must keep returning what it returns today: per-slot
 *     {ok, error, stale, ageHours, storm}.  Staleness is judged from the
 *     bulletin's OWN analysis time (storm.taus[0].epoch), exactly as the
 *     GFE tool does, so the server cannot classify a slot without
 *     parsing it.  Returning raw text and having the client decide would
 *     change the contract of getBulletins and move slot triage into three
 *     separate pages.
 *   - A slot that parses to fewer than two usable forecast times is a
 *     retrieval-layer error ("only N usable forecast times"), reported
 *     next to HTTP failures, not a rendering problem.
 *   - The parse is cheap: 0.14 ms for the 4.6 KB WTPN31 fixture and
 *     0.08 ms for the 2.0 KB PARITY_FIXTURE, measured over 200 runs on
 *     Node 22. Apps Script's V8 is slower than that, but not by enough
 *     for anything to be saved by shipping the parse to the browser.
 *
 * What keeps the two copies honest - use it, it is mechanical:
 *
 *   checkParserParity()   Loads Vortex.html, evaluates its script into a
 *                         private sandbox, runs BOTH parsers over the
 *                         same bulletins (an embedded synthetic product
 *                         that exercises every branch, plus every live
 *                         slot when asked), and diffs the results field
 *                         by field.  This is a BEHAVIOURAL check: it
 *                         catches drift no matter how the two copies are
 *                         formatted.  Run it from the editor after
 *                         touching either copy.
 *
 *   parserFingerprint()   SHA-256 of Vortex.html's parser section with
 *                         whole-line comments stripped and whitespace
 *                         collapsed, compared against VORTEX_PARSER_SHA
 *                         pinned below.  A TRIPWIRE, not a test: when it
 *                         says CHANGED, re-run checkParserParity() and
 *                         re-pin the constant in the same commit.
 *
 * Vortex.html is canonical.  TCWind_JTWC.py is canonical over both.  If
 * the three disagree: Python wins, then Vortex.html, then this file.
 */

var VERSION = '2026-09-03a';

var BULLETIN_BASE = 'https://tgftp.nws.noaa.gov/data/raw/wt/';

// NHC's own text server. tgftp does NOT mirror the Atlantic/East Pacific
// TCM (Forecast/Advisory) product class - verified directly against real,
// currently active storms: every wtnt2N.knhc../wtpz2N.knhc..txt path under
// BULLETIN_BASE 404s even while a live advisory is being issued, because
// tgftp simply does not carry this product there, not because the slot is
// empty. NHC's refresh server DOES carry it, confirmed live (Hurricane
// Karina, EP112026): https://www.nhc.noaa.gov/text/refresh/MIATCMEP1+shtml/
// See fetchNhcText_() for the small HTML-unwrap this needs that a plain
// tgftp fetch does not. JTWC's fetch (BULLETIN_BASE, below) is completely
// unchanged by this.
var NHC_TEXT_BASE = 'https://www.nhc.noaa.gov/text/refresh/';

// Every bulletin slot this tool watches, across three basins. Each basin
// has its own file-naming and pil scheme, but source/basin/file/pil fully
// determine how a slot is fetched, parsed and labelled - nothing past this
// table string-sniffs a pil to figure any of that out.
//
//   WP (JTWC, West Pacific): the same five NFDTCPWP1-5 bins as before,
//     under their WMO headings, fetched straight off tgftp exactly as
//     always - source/file/pil/parser for these five entries are BYTE FOR
//     BYTE what BULLETIN_FILES used to produce, on purpose: nothing about
//     the JTWC path may change here.
//   AT (NHC, Atlantic) and EP (NHC, East Pacific): five bins each, WTNT21-
//     25/WTPZ21-25 KNHC, AWIPS ids TCMAT1-5/TCMEP1-5 - the bin number
//     rotates by cyclone number within the season exactly like JTWC's WP
//     slots, so an empty bin outside/between storms is normal. `file` is
//     the WMO-style label these slots are shown under (matching what the
//     product's OWN WMO header line reads, regardless of the NHC-text-
//     server transport actually used to fetch it - see NHC_TEXT_BASE
//     above); it is not literally fetched as a filename the way the WP
//     entries are.
function buildBulletinSlots_() {
  var slots = [], i;
  for (i = 1; i <= 5; i++) {
    slots.push({ basin: 'WP', source: 'tgftp',
                 file: 'wtpn3' + i + '.pgtw..txt', pil: 'NFDTCPWP' + i });
  }
  for (i = 1; i <= 5; i++) {
    slots.push({ basin: 'AT', source: 'nhctext',
                 file: 'wtnt2' + i + '.knhc..txt', pil: 'TCMAT' + i });
  }
  for (i = 1; i <= 5; i++) {
    slots.push({ basin: 'EP', source: 'nhctext',
                 file: 'wtpz2' + i + '.knhc..txt', pil: 'TCMEP' + i });
  }
  return slots;
}
var BULLETIN_SLOTS = buildBulletinSlots_();

// Human-readable basin name for status/hint text, keyed by the `basin`
// field above.
var BASIN_NAME = { WP: 'NW Pacific', AT: 'Atlantic', EP: 'East Pacific' };

var CACHE_SECONDS = 1800;             // 30 min; CacheService caps at 21600
var CACHE_PREFIX = 'wtpn:v1:';        // namespaced so nothing else collides
var MAX_CACHE_VALUE_BYTES = 90000;    // CacheService cap is 100 KB; stay under
var MAX_BULLETIN_AGE_HOURS = 12;

// Templates doGet() is allowed to serve. Anything not in here is unknown.
var PAGES = {
  live:     { file: 'Index',    title: 'JTWC TC Wind preview (EXPERIMENTAL)' },
  archive:  { file: 'Archive',  title: 'JTWC TC Wind - Best-track archive (EXPERIMENTAL)' },
  findings: { file: 'Findings', title: 'JTWC TC Wind - Findings (EXPERIMENTAL)' }
};
var DEFAULT_PAGE = 'live';

var VORTEX_FILE = 'Vortex';

// SHA-256 of the normalised parser section of Vortex.html. Regenerate with
// parserFingerprint() and paste the value it reports - in the same commit
// as the Vortex.html change, after checkParserParity() passes.
var VORTEX_PARSER_SHA =
  '713f94e79b531cce74218ca28d4e9b3ba9aebadcb6ad5895ff4d3812bb179541';

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

// NHC's own system-type vocabulary, mapped to the same CONF_* ladder as
// JTWC's SUPER TYPHOON/TYPHOON/TROPICAL STORM/TROPICAL DEPRESSION words -
// same spirit, different words. See parseTCM()'s docstring below.
var TCM_TYPE_CONF = {
  'HURRICANE': CONF_TROPICAL,
  'TROPICAL STORM': CONF_TROPICAL,
  'TROPICAL DEPRESSION': CONF_TROPICAL,
  'POTENTIAL TROPICAL CYCLONE': CONF_TROPICAL,
  'SUBTROPICAL STORM': CONF_SUBTROPICAL,
  'SUBTROPICAL DEPRESSION': CONF_SUBTROPICAL,
  'POST-TROPICAL CYCLONE': CONF_BECOMING
};


// ---------------------------------------------------------------------------
// Web app entry point
// ---------------------------------------------------------------------------

/**
 * Route ?page= to a template.
 *
 *   absent | live   -> Index.html
 *   archive         -> Archive.html
 *   findings        -> Findings.html
 *   anything else   -> Index.html, carrying a VISIBLE note that the
 *                      requested page does not exist. Not a silent
 *                      fallback (a forecaster who typo'd a bookmark must
 *                      be told they are not looking at what they asked
 *                      for) and not an error page (the live tool is the
 *                      useful thing to show them).
 *
 * Every template is handed the same four variables, ALWAYS, whether it
 * uses them or not - a template referencing an unset variable throws and
 * takes the whole page down:
 *
 *   baseUrl   String  the /exec URL, for cross-page links
 *   page      String  the resolved page key: live | archive | findings
 *   pageNote  String  '' normally; a one-line notice to display otherwise
 *   version   String  this file's VERSION, for the footer
 *
 * Everything is interpolated with <?= ?> (escaping) on the page side.
 * pageNote is additionally hard-filtered here because it can contain a
 * caller-supplied string.
 */
function doGet(e) {
  var raw = (e && e.parameter && e.parameter.page) || '';
  var page = String(raw).toLowerCase();
  var note = '';

  if (!page) {
    page = DEFAULT_PAGE;
  } else if (!Object.prototype.hasOwnProperty.call(PAGES, page)) {
    note = 'Unknown page "' + safeLabel_(raw) + '" - showing the live tool. ' +
           'Valid values are page=live, page=archive, page=findings.';
    page = DEFAULT_PAGE;
  }

  var spec = PAGES[page];
  var tmpl;
  try {
    tmpl = HtmlService.createTemplateFromFile(spec.file);
  } catch (err) {
    // The template file is not in the deployment (e.g. Archive.html was
    // never pushed). Say which file, rather than showing a raw stack.
    return missingTemplatePage_(spec.file, page, err);
  }

  tmpl.baseUrl = ScriptApp.getService().getUrl();
  tmpl.page = page;
  tmpl.pageNote = note;
  tmpl.version = VERSION;

  var out;
  try {
    out = tmpl.evaluate();
  } catch (err2) {
    return missingTemplatePage_(spec.file, page, err2);
  }

  // Belt and braces on the unknown-page note: if Index.html renders
  // <?= pageNote ?> the banner below is a duplicate, which is why it is
  // marked data-server-note and can be hidden by the page. If Index.html
  // ignores pageNote - a page author is not obliged to know about it -
  // this is what keeps the notice from vanishing silently.
  if (note) {
    out = HtmlService.createHtmlOutput(injectNote_(out.getContent(), note));
  }

  return out
    .setTitle(spec.title)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}


/** Reduce a caller-supplied string to something safe to show verbatim. */
function safeLabel_(s) {
  var t = String(s).substring(0, 40).replace(/[^A-Za-z0-9 ._-]/g, '?');
  return t.length ? t : '(empty)';
}


/** HTML-escape. Used for the server-injected banner only; page-side
 *  interpolation uses <?= ?>, which escapes on its own. */
function escapeHtml_(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}


/**
 * Put a plain, unmissable banner immediately after <body>. Deliberately
 * inline-styled and colour-independent (it leads with the word "Note:"
 * and is a bordered block, so it does not rely on colour to be read) and
 * deliberately NOT dependent on any page's CSS, because the whole point
 * is that it survives a page that knows nothing about it.
 */
function injectNote_(html, note) {
  var banner =
    '<div data-server-note="1" role="status" style="' +
    'margin:0;padding:10px 14px;border-bottom:2px solid #6b4d00;' +
    'background:#fff4d6;color:#3d2c00;font:600 14px/1.4 ' +
    'system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">' +
    'Note: ' + escapeHtml_(note) + '</div>';
  var m = /<body[^>]*>/i.exec(html);
  if (m) {
    var at = m.index + m[0].length;
    return html.substring(0, at) + banner + html.substring(at);
  }
  return banner + html;   // no <body> tag: still show it, at the top
}


/** Minimal, self-contained page for "the template is not deployed". */
function missingTemplatePage_(file, page, err) {
  var html =
    '<!DOCTYPE html><html><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<title>JTWC TC Wind - page unavailable</title></head>' +
    '<body style="margin:0;background:#ffffff;color:#111827;font:15px/1.5 ' +
    'system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">' +
    '<div style="max-width:44rem;margin:3rem auto;padding:0 1.25rem;">' +
    '<p style="font-weight:700;letter-spacing:.04em;">' +
    'EXPERIMENTAL - NOT OPERATIONALLY VETTED</p>' +
    '<h1 style="font-size:1.4rem;">Page "' + escapeHtml_(page) +
    '" is not available in this deployment</h1>' +
    '<p>It needs the file <code>' + escapeHtml_(file) +
    '.html</code>, which is not part of the pushed Apps Script project.</p>' +
    '<p>Fix: push it (<code>clasp push</code> from <code>web/TCWind_JTWC</code>) ' +
    'and cut a new deployment (<code>clasp deploy</code>). A <code>clasp push</code> ' +
    'alone updates @HEAD, not the /exec URL.</p>' +
    '<p style="color:#4b5563;">Underlying error: <code>' +
    escapeHtml_(String(err)) + '</code></p>' +
    '<p><a href="' + escapeHtml_(ScriptApp.getService().getUrl()) +
    '">Back to the live tool</a></p></div></body></html>';
  return HtmlService.createHtmlOutput(html)
    .setTitle('JTWC TC Wind - page unavailable')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}


// ---------------------------------------------------------------------------
// Retrieval
// ---------------------------------------------------------------------------

/**
 * Fetch one AT/EP slot's product off NHC's own text server and unwrap it.
 *
 * tgftp does not carry this product class (see NHC_TEXT_BASE's comment),
 * so this is a second, small fetch helper alongside the plain tgftp fetch
 * getBulletins() still uses for WP - JTWC's path is untouched by this.
 *
 * The page is HTML: `<pre>...</pre>` wraps the raw product, preceded by a
 * bare line-count number on its own line before the WMO header (the same
 * kind of leading artifact tgftp's own raw files can carry). Both are
 * stripped here so the parser sees exactly the WMO-header-first text it
 * already expects from tgftp.
 *
 * Returns {ok, httpStatus, text}. `text` is null when !ok.
 */
function fetchNhcText_(pil) {
  var url = NHC_TEXT_BASE + 'MIA' + pil + '+shtml/';
  var resp = UrlFetchApp.fetch(url, {
    muteHttpExceptions: true,
    followRedirects: true,
    validateHttpsCertificates: true
  });
  var code = resp.getResponseCode();
  if (code !== 200) return { ok: false, httpStatus: code, text: null };

  var html = resp.getContentText();
  var m = /<pre[^>]*>([\s\S]*?)<\/pre>/i.exec(html);
  if (!m) return { ok: false, httpStatus: code, text: null };

  var body = m[1]
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, '\'').replace(/&nbsp;/g, ' ');

  var lines = body.split(/\r?\n/);
  while (lines.length && lines[0].replace(/\s/g, '') === '') lines.shift();
  if (lines.length && /^\d+\s*$/.test(lines[0])) lines.shift();   // line-count token
  return { ok: true, httpStatus: code, text: lines.join('\n') };
}


/**
 * Fetch and parse every bulletin slot across all three basins (WP/AT/EP -
 * see BULLETIN_SLOTS).
 *
 * Returns an array of {file, pil, basin, ok, error, errorKind, hint,
 * stale, ageHours, storm}. `ok`, `error`, `stale`, `ageHours` and `storm`
 * are unchanged from previous versions - existing callers keep working.
 * `errorKind` (machine-readable) and `hint` (what to do about it) let the
 * UI say what failed without string-matching `error`. `basin` ('WP'/'AT'/
 * 'EP') lets callers dispatch on it directly instead of string-sniffing
 * `pil`.
 *
 * errorKind is one of: http | fetch | empty | thin | parse.
 */
function getBulletins(force) {
  var cache = CacheService.getScriptCache();
  var nowSecs = Math.floor(new Date().getTime() / 1000);
  var out = [];

  for (var i = 0; i < BULLETIN_SLOTS.length; i++) {
    var slot = BULLETIN_SLOTS[i];
    var file = slot.file, pil = slot.pil, basin = slot.basin;
    var basinName = BASIN_NAME[basin] || basin;
    var entry = { file: file, pil: pil, basin: basin, ok: false, error: null,
                  errorKind: null, hint: null, stale: false, cached: false };

    var key = CACHE_PREFIX + file;
    var text = force ? null : cache.get(key);
    if (text) {
      entry.cached = true;
    } else {
      try {
        var code, fetchFailHint;
        if (slot.source === 'tgftp') {
          var resp = UrlFetchApp.fetch(BULLETIN_BASE + file, {
            muteHttpExceptions: true,    // never throw on 4xx/5xx; we report
            followRedirects: true,
            validateHttpsCertificates: true
          });
          code = resp.getResponseCode();
          if (code === 200) text = resp.getContentText();
          fetchFailHint = (code === 404)
            ? 'The gateway has no product in this slot right now. Normal ' +
              'when fewer than five ' + basinName + ' systems are active.'
            : 'tgftp.nws.noaa.gov returned ' + code + '. Retry; if it ' +
              'persists, paste the bulletin text instead.';
        } else {   // 'nhctext'
          var nr = fetchNhcText_(pil);
          code = nr.httpStatus;
          if (nr.ok) text = nr.text;
          fetchFailHint = (code === 404)
            ? 'NHC\'s text server has no current product for this bin. ' +
              'Normal when fewer than five ' + basinName + ' systems are ' +
              'active.'
            : 'nhc.noaa.gov returned ' + code + '. Retry; if it persists, ' +
              'paste the bulletin text instead.';
        }
        if (!text) {
          entry.error = 'HTTP ' + code;
          entry.errorKind = 'http';
          entry.httpStatus = code;
          entry.hint = fetchFailHint;
          out.push(entry);
          continue;
        }
        // Caching must never be able to fail a good fetch: a value over
        // the 100 KB CacheService cap, or a cache hiccup, costs us the
        // next 30 minutes of speed and nothing else.
        try {
          if (text.length < MAX_CACHE_VALUE_BYTES) {
            cache.put(key, text, CACHE_SECONDS);
          }
        } catch (errCache) {
          // deliberately ignored; see above
        }
      } catch (err) {
        entry.error = String(err);
        entry.errorKind = 'fetch';
        entry.hint = (slot.source === 'tgftp')
          ? 'Could not reach tgftp.nws.noaa.gov. Check the network path, ' +
            'or paste the bulletin text instead.'
          : 'Could not reach nhc.noaa.gov. Check the network path, or ' +
            'paste the bulletin text instead.';
        out.push(entry);
        continue;
      }
    }

    if (!text || text.replace(/\s/g, '').length < 200) {
      entry.error = 'slot empty';
      entry.errorKind = 'empty';
      entry.hint = 'The slot exists but holds no usable product.';
      out.push(entry);
      continue;
    }

    try {
      var parseFn = (basin === 'WP') ? parseJTWC : parseTCM;
      var storm = parseFn(text);
      if (storm.taus.length < 2) {
        entry.error = 'only ' + storm.taus.length + ' usable forecast times';
        entry.errorKind = 'thin';
        entry.hint = 'The product parsed but carries fewer than two ' +
                     'positions; there is nothing to interpolate between.';
        out.push(entry);
        continue;
      }
      // textdb/tgftp/NHC's refresh server all serve the last product
      // stored, so a dissipated storm sits in its slot indefinitely. Judge
      // by the bulletin's own analysis time, exactly as the GFE tool does.
      var ageHours = (nowSecs - storm.taus[0].epoch) / 3600.0;
      entry.ageHours = ageHours;
      entry.stale = (ageHours > MAX_BULLETIN_AGE_HOURS) ||
                    (storm.taus[storm.taus.length - 1].epoch <= nowSecs);
      storm.file = file;
      storm.pil = pil;
      storm.basin = basin;
      entry.storm = storm;
      entry.ok = true;
    } catch (err2) {
      entry.error = String(err2);
      entry.errorKind = 'parse';
      entry.hint = (basin === 'WP')
        ? 'The text was retrieved but did not parse as a WTPN warning. ' +
          'Check the raw product; the parser may need to learn a new ' +
          'line format.'
        : 'The text was retrieved but did not parse as a TCM Forecast/' +
          'Advisory. Check the raw product; the parser may need to learn ' +
          'a new line format.';
    }
    out.push(entry);
  }
  return out;
}


/**
 * Parse pasted bulletin text. Used when tgftp/NHC's text server is
 * unreachable, or to preview a bulletin that isn't in any live slot.
 *
 * Tries parseJTWC() first, then parseTCM() if that fails to produce a
 * usable result - a forecaster can paste either a JTWC WTPN warning or an
 * NHC TCM Forecast/Advisory and have it just work, with no basin flag to
 * pick. "Fails" means either parser threw (parseJTWC() throws immediately
 * when it cannot find a DDMMMYY reference date anywhere in the text, which
 * is exactly what happens on real NHC text - it has no REMARKS block and
 * no DDMMMYY-shaped substring anywhere) or it parsed with zero usable
 * taus. The error surfaced on a DOUBLE failure is parseJTWC()'s, since a
 * WTPN warning is the more common paste and its error message is the more
 * actionable one for that case.
 *
 * The returned envelope matches getBulletins()'s per-slot shape exactly
 * (top-level file/pil/basin/ok/error/errorKind/hint/stale/ageHours/storm)
 * so the client can push it into the same `slots` array getBulletins()
 * fills, instead of needing a special case. `pil` is the literal string
 * 'PASTED' (there is no real product id for hand-pasted text) so chip/
 * status code that does `sl.pil.replace(...)` never sees an undefined
 * field.
 */
function parsePasted(text) {
  var storm = null, primaryErr = null;
  try {
    storm = parseJTWC(text);
    if (!storm.taus || !storm.taus.length) storm = null;
  } catch (e1) {
    primaryErr = e1;
  }
  if (!storm) {
    try {
      storm = parseTCM(text);
    } catch (e2) {
      throw primaryErr || e2;
    }
    if (!storm.taus || !storm.taus.length) throw primaryErr || new Error('no usable taus');
  }
  storm.file = 'pasted';
  storm.pil = 'PASTED';
  // parseJTWC()'s header carries no basin field at all (it only ever
  // parses West Pacific WTPN text); parseTCM()'s does ('AT'/'EP'/other).
  storm.basin = (storm.header && storm.header.basin) ? storm.header.basin : 'WP';
  var ageHours = null;
  if (storm.taus && storm.taus.length) {
    var nowSecs = Math.floor(new Date().getTime() / 1000);
    ageHours = (nowSecs - storm.taus[0].epoch) / 3600.0;
  }
  return { file: 'pasted', pil: 'PASTED', basin: storm.basin, ok: true,
           error: null, errorKind: null, hint: null, stale: false,
           ageHours: ageHours, cached: false, storm: storm };
}


// ---------------------------------------------------------------------------
// Best-track archive + verification numbers
//
// Backing data is in BestTrackData.gs, which is GENERATED by
// tests/tcwind_jtwc/prep_besttrack_data.py. Never hand-edit it.
//
// Payload discipline: getArchiveIndex() serves metadata only (~70 KB);
// getArchiveStorm() serves ONE storm's records (~5-25 KB). There is no
// call that returns every storm's records, and there must not be - the
// full ARCHIVE_STORMS literal is ~2 MB.
//
// None of this is cached in CacheService. It is already a script global,
// resident in the execution, and the 100 KB per-value cap means the
// archive could only be cached by shredding it into dozens of keys - all
// cost, no benefit.
// ---------------------------------------------------------------------------

function missingDataError_(what, symbol) {
  return new Error(
    what + ' is not available: ' + symbol + ' is missing from this ' +
    'deployment. BestTrackData.gs is generated by ' +
    'tests/tcwind_jtwc/prep_besttrack_data.py; regenerate it, clasp push, ' +
    'and cut a new deployment.');
}


/**
 * Light metadata for every archived storm, all basins.
 * [{sid, basin, agency, name, season, n, peakVmax, minLat, maxLat,
 *   minLon, maxLon, startIso, endIso, radiiRecords}, ...]
 * Times are UTC. Throws if the generated data is not deployed.
 */
function getArchiveIndex() {
  if (typeof ARCHIVE_INDEX === 'undefined' || !ARCHIVE_INDEX) {
    throw missingDataError_('The best-track archive index', 'ARCHIVE_INDEX');
  }
  return ARCHIVE_INDEX;
}


/**
 * One storm's records, or null if the sid is not in the archive.
 * Record shape is exactly besttrack_common.build_storm_records():
 * {iso, epoch, lat, lon, vmax, rmw, roci, pres, radii, nature,
 *  dist2land, motionDir, motionSpd}. Times are UTC.
 *
 * null - not an exception - for an unknown sid: "no such storm" is a
 * normal answer for a browser with a stale link, and the page shows an
 * empty state for it.
 */
function getArchiveStorm(sid) {
  if (typeof ARCHIVE_STORMS === 'undefined' || !ARCHIVE_STORMS) {
    throw missingDataError_('The best-track archive', 'ARCHIVE_STORMS');
  }
  if (typeof sid !== 'string' || !sid) return null;
  // hasOwnProperty, not `in` and not a bare lookup: ARCHIVE_STORMS is a
  // plain object, so '__proto__', 'constructor' and 'toString' would all
  // otherwise "resolve" to something that is not a storm.
  if (!Object.prototype.hasOwnProperty.call(ARCHIVE_STORMS, sid)) return null;
  return ARCHIVE_STORMS[sid];
}


/**
 * Contents of tests/tcwind_jtwc/data/gtcm_findings.json, as bundled into
 * BestTrackData.gs. Every number the Findings page shows comes from here;
 * the page hardcodes none of them.
 *
 * Throws - rather than returning null - when the findings have not been
 * generated. A thrown error reaches the page's withFailureHandler with a
 * message saying what to run; a null would have to be defended against by
 * every reader, and the failure mode of forgetting is a blank page with
 * no explanation.
 */
function getFindings() {
  if (typeof GTCM_FINDINGS === 'undefined' || GTCM_FINDINGS === null) {
    throw new Error(
      'GTCM findings are not available: GTCM_FINDINGS is null in ' +
      'BestTrackData.gs. It is populated from ' +
      'tests/tcwind_jtwc/data/gtcm_findings.json, which is written by ' +
      'tests/tcwind_jtwc/verify_gtcm.py. Run verify_gtcm.py, re-run ' +
      'prep_besttrack_data.py, clasp push, and redeploy.');
  }
  return GTCM_FINDINGS;
}


// ===========================================================================
// PARSER - MIRROR COPY. Vortex.html holds the canonical JavaScript parser.
// ===========================================================================
//
//   !! Do not "fix" anything below without making the identical change in
//   !! Vortex.html and re-running checkParserParity(). The header comment
//   !! at the top of this file explains why the copy exists and what its
//   !! job is (server-side slot triage: staleness, thin products, parse
//   !! failures). GFE/procedures/TCWind_JTWC.py is canonical over both.
//
// ===========================================================================

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


/**
 * MIRROR COPY of parseTCM() - canonical in Vortex.html. See the big
 * comment above Vortex.html's own parseTCM() for the nine WTPN/TCM format
 * differences this handles and the header field-mapping notes; both are
 * reproduced there in full and are not repeated here. There is no Python
 * side to this parser at all (GFE/procedures/TCWind_JTWC.py is JTWC-only),
 * so unlike parseJTWC() the tiebreak is just "Vortex.html wins".
 */
function parseTCM(text) {
  var lines = String(text).split(/\r?\n/);
  var full = lines.join('\n');

  var mi = /(\d{3,4})\s+UTC\s+[A-Z]{3}\s+([A-Z]{3})\s+(\d{1,2})\s+(\d{4})/.exec(full);
  if (!mi || !MONTHS[mi[2]]) {
    throw new Error('no "<time> UTC <dow> <mon> <day> <year>" issuance line; cannot resolve DTGs');
  }
  var refDay = parseInt(mi[3], 10);
  var refMonth = MONTHS[mi[2]];
  var refYear = parseInt(mi[4], 10);

  var TYPE = 'HURRICANE|TROPICAL STORM|TROPICAL DEPRESSION|POTENTIAL TROPICAL CYCLONE|SUBTROPICAL STORM|SUBTROPICAL DEPRESSION|POST-TROPICAL CYCLONE';
  var reCurpos = new RegExp('^\\s*(' + TYPE + ')\\s+CENTER LOCATED NEAR\\s+(\\d+(?:\\.\\d+)?)\\s*([NS])\\s+(\\d+(?:\\.\\d+)?)\\s*([EW])\\s+AT\\s+(\\d{2})\\/(\\d{4})Z');
  var reBackfill = /^\s*AT\s+(\d{2})\/(\d{4})Z\s+CENTER WAS LOCATED NEAR\s+(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])/;
  var reFcst = /^\s*(FORECAST|OUTLOOK)\s+VALID\s+(\d{2})\/(\d{4})Z\s+(\d+(?:\.\d+)?)\s*([NS])\s+(\d+(?:\.\d+)?)\s*([EW])(?:\.\.\.([A-Z][A-Z\- ]*))?/;
  var reTerm = /^\s*\$\$\s*$/;

  var taus = [];
  var cur = null;
  var curThreshold = null;
  var priorPos = null;

  for (var j = 0; j < lines.length; j++) {
    var ln = lines[j];
    if (reTerm.test(ln)) break;

    var mc = reCurpos.exec(ln);
    if (mc) {
      cur = { tau: 0, epoch: null, lat: null, lon: null, vmax: null,
              gust: null, radii: {}, motionDir: null, motionSpd: null,
              conf: CONF_TROPICAL };
      cur.epoch = dtgToEpoch(mc[6] + mc[7], refDay, refMonth, refYear);
      var cla = parseFloat(mc[2]); if (mc[3] === 'S') cla = -cla;
      var clo = parseFloat(mc[4]); if (mc[5] === 'W') clo = -clo;
      cur.lat = cla; cur.lon = clo;
      if (TCM_TYPE_CONF[mc[1]] !== undefined) cur.conf = TCM_TYPE_CONF[mc[1]];
      taus.push(cur);
      curThreshold = null;
      continue;
    }

    var mf = reFcst.exec(ln);
    if (mf) {
      cur = { tau: 0, epoch: null, lat: null, lon: null, vmax: null,
              gust: null, radii: {}, motionDir: null, motionSpd: null,
              conf: CONF_TROPICAL };
      cur.epoch = dtgToEpoch(mf[2] + mf[3], refDay, refMonth, refYear);
      var fla = parseFloat(mf[4]); if (mf[5] === 'S') fla = -fla;
      var flo = parseFloat(mf[6]); if (mf[7] === 'W') flo = -flo;
      cur.lat = fla; cur.lon = flo;
      if (mf[8]) {
        var status = mf[8].toUpperCase();
        if (status.indexOf('POST-TROPICAL') >= 0 || status.indexOf('EXTRATROPICAL') >= 0) {
          cur.conf = CONF_BECOMING;
        } else if (status.indexOf('SUBTROPICAL') >= 0) {
          cur.conf = CONF_SUBTROPICAL;
        }
      }
      taus.push(cur);
      curThreshold = null;
      continue;
    }

    var mb = reBackfill.exec(ln);
    if (mb) {
      var pla = parseFloat(mb[3]); if (mb[4] === 'S') pla = -pla;
      var plo = parseFloat(mb[5]); if (mb[6] === 'W') plo = -plo;
      priorPos = { lat: pla, lon: plo,
                   epoch: dtgToEpoch(mb[1] + mb[2], refDay, refMonth, refYear) };
      continue;
    }

    if (!cur) continue;

    var mw1 = /MAX SUSTAINED WINDS\s+(\d+)\s*KT WITH GUSTS TO\s+(\d+)\s*KT/.exec(ln);
    if (mw1) { cur.vmax = parseFloat(mw1[1]); cur.gust = parseFloat(mw1[2]); continue; }

    var mw2 = /MAX WIND\s+(\d+)\s*KT\.*\s*GUSTS\s+(\d+)\s*KT/.exec(ln);
    if (mw2) { cur.vmax = parseFloat(mw2[1]); cur.gust = parseFloat(mw2[2]); continue; }

    var mr = /^\s*(\d+)\s*KT\.+\s*(.+?)\.?\s*$/.exec(ln);
    if (mr) {
      curThreshold = parseInt(mr[1], 10);
      if (!cur.radii[curThreshold]) cur.radii[curThreshold] = emptyQuads();
      var toks = mr[2].match(/\d+\s*(?:NE|SE|SW|NW)/g) || [];
      for (var ti = 0; ti < toks.length; ti++) {
        var tm = /(\d+)\s*(NE|SE|SW|NW)/.exec(toks[ti]);
        if (tm) cur.radii[curThreshold][tm[2]] = parseFloat(tm[1]);
      }
      continue;
    }

    var mm = /PRESENT MOVEMENT.*?(\d+)\s*DEGREES AT\s+(\d+)\s*KT/.exec(ln);
    if (mm) { cur.motionDir = parseFloat(mm[1]); cur.motionSpd = parseFloat(mm[2]); continue; }

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

  if (!taus.length) {
    throw new Error('no usable FORECAST/ADVISORY position blocks parsed from this bulletin');
  }

  var t0epoch = taus[0].epoch;
  for (var ti2 = 0; ti2 < taus.length; ti2++) {
    taus[ti2].tau = Math.round((taus[ti2].epoch - t0epoch) / 3600);
  }

  var worst = CONF_TROPICAL;
  for (var k = 0; k < taus.length; k++) {
    worst = Math.min(worst, taus[k].conf);
    taus[k].conf = worst;
  }

  if (taus[0].motionSpd === null && priorPos !== null) {
    var bsp = bearingSpeed(priorPos, taus[0]);
    taus[0].motionDir = bsp[0];
    taus[0].motionSpd = bsp[1];
  }
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

  var header = {
    refDate: [refDay, refMonth, refYear],
    systemType: null, stormId: null, stormName: null,
    warningNumber: null, pressureMb: null, basin: null
  };

  var mt = new RegExp('^\\s*(' + TYPE + ')\\s+(.+?)\\s+FORECAST\\/ADVISORY NUMBER\\s+(\\d+)', 'm').exec(full);
  if (mt) {
    header.systemType = mt[1];
    header.stormName = mt[2].replace(/\s+$/, '');
    header.warningNumber = parseInt(mt[3], 10);
  }
  var ma = /\b(AL|EP|CP)(\d{2})(\d{4})\b/.exec(full);
  if (ma) {
    header.stormId = ma[1] + ma[2];
    header.basin = (ma[1] === 'AL') ? 'AT' : ma[1];
  }
  var mp = /(?:ESTIMATED\s+)?MINIMUM\s+CENTRAL\s+PRESSURE\s+(\d+)\s*MB/.exec(full);
  if (mp) header.pressureMb = parseInt(mp[1], 10);

  return { header: header, taus: taus, text: text };
}


// ===========================================================================
// Parser parity - the mechanical drift check for the duplication above
// ===========================================================================

/**
 * A synthetic WTPN product, embedded so parity can be checked with no
 * network and no live storms. It is not a real bulletin; it is built to
 * hit every branch the two parsers share:
 *
 *   - DDMMMYY reference date found in REMARKS, at the END of the product
 *   - WARNING POSITION block, with "NEAR", plus MOVEMENT PAST SIX HOURS
 *   - forecast blocks WITHOUT "NEAR"
 *   - all three radii thresholds, each with three continuation lines
 *   - a forecast block with NO vector line (motion backfill path)
 *   - the last block with no vector line (carry-back path)
 *   - BECOMING EXTRATROPICAL (confidence downgrade, sticky downstream)
 *   - a day rollover across the end of the month AND the year
 *     (31DEC26 reference, 010600Z and 011800Z forecast DTGs)
 *   - MINIMUM CENTRAL PRESSURE in the remarks
 *
 * Verified to parse identically in all THREE implementations - the Python
 * reference (tools_py.py parse), Vortex.html, and the mirror below:
 * header {refDate [31,12,2026], TYPHOON 30W PARITY, warning 12, 958 mb},
 * four taus at 2026-12-31T06Z/18Z and 2027-01-01T06Z/18Z, vmax
 * 85/90/80/60 kt, conf 1/1/1/0.6, motion 285@9 / 300@10 / 341.9@9
 * (backfilled) / 341.9@9 (carried back).
 */
var PARITY_FIXTURE = [
  'WTPN35 PGTW 310900',
  'MSGID/GENADMIN/JOINT TYPHOON WRNCEN PEARL HARBOR HI//',
  'SUBJ/TYPHOON 30W (PARITY) WARNING NR 012//',
  'RMKS/',
  '1. TYPHOON 30W (PARITY) WARNING NR 012',
  '   MAX SUSTAINED WINDS BASED ON ONE-MINUTE AVERAGE',
  '    ---',
  '   WARNING POSITION:',
  '   310600Z --- NEAR 18.4N 134.2E',
  '     MOVEMENT PAST SIX HOURS - 285 DEGREES AT 09 KTS',
  '     POSITION ACCURATE TO WITHIN 030 NM',
  '   PRESENT WIND DISTRIBUTION:',
  '   MAX SUSTAINED WINDS - 085 KT, GUSTS 105 KT',
  '   RADIUS OF 064 KT WINDS - 035 NM NORTHEAST QUADRANT',
  '                            030 NM SOUTHEAST QUADRANT',
  '                            025 NM SOUTHWEST QUADRANT',
  '                            030 NM NORTHWEST QUADRANT',
  '   RADIUS OF 050 KT WINDS - 070 NM NORTHEAST QUADRANT',
  '                            060 NM SOUTHEAST QUADRANT',
  '                            045 NM SOUTHWEST QUADRANT',
  '                            055 NM NORTHWEST QUADRANT',
  '   RADIUS OF 034 KT WINDS - 150 NM NORTHEAST QUADRANT',
  '                            120 NM SOUTHEAST QUADRANT',
  '                            090 NM SOUTHWEST QUADRANT',
  '                            110 NM NORTHWEST QUADRANT',
  '   REPEAT POSIT: 18.4N 134.2E',
  '    ---',
  '   FORECASTS:',
  '   12 HRS, VALID AT:',
  '   311800Z --- 19.1N 132.9E',
  '   MAX SUSTAINED WINDS - 090 KT, GUSTS 110 KT',
  '   RADIUS OF 034 KT WINDS - 155 NM NORTHEAST QUADRANT',
  '                            125 NM SOUTHEAST QUADRANT',
  '                            095 NM SOUTHWEST QUADRANT',
  '                            115 NM NORTHWEST QUADRANT',
  '   VECTOR TO 24 HR POSIT: 300 DEG/ 10 KTS',
  '    ---',
  '   24 HRS, VALID AT:',
  '   010600Z --- 20.3N 131.4E',
  '   MAX SUSTAINED WINDS - 080 KT, GUSTS 100 KT',
  '    ---',
  '   36 HRS, VALID AT:',
  '   011800Z --- 22.0N 130.8E',
  '   MAX SUSTAINED WINDS - 060 KT, GUSTS 075 KT',
  '   BECOMING EXTRATROPICAL',
  '    ---',
  'REMARKS:',
  '310900Z POSITION NEAR 18.5N 134.3E. 31DEC26. TYPHOON 30W (PARITY) IS A',
  'SYNTHETIC PRODUCT EMBEDDED IN THE SERVER SOURCE SOLELY TO DRIVE THE',
  'PARSER PARITY CHECK. MINIMUM CENTRAL PRESSURE AT 310600Z IS 958 MB.//',
  'NNNN'
].join('\n');


/**
 * A synthetic NHC TCM (Forecast/Advisory) product, parseTCM()'s own
 * embedded parity fixture, mirroring PARITY_FIXTURE's role above but for
 * the TCM format. Built to hit every branch parseTCM() and its Vortex.html
 * twin share:
 *
 *   - the issuance line's reference date, read directly (no REMARKS hunt)
 *   - "<TYPE> CENTER LOCATED NEAR ... AT DD/HHMMZ" plus PRESENT MOVEMENT
 *   - the "AT DD/HHMMZ CENTER WAS LOCATED NEAR ..." backfill line (present
 *     but unused here, since PRESENT MOVEMENT already supplies motion -
 *     this only proves it does not spawn a spurious extra tau)
 *   - multi-quadrant radii on one line, at only ONE threshold per block
 *     for two of the four blocks (fewer than 3 KT lines - a weakening
 *     forecast/outlook)
 *   - the seas-radii line, which must NOT be read as wind radii
 *   - a trailing "...POST-TROPICAL" status riding on an OUTLOOK VALID
 *     line with no line break (confidence downgrade, sticky downstream)
 *   - a day rollover across the end of the month AND the year (issuance
 *     31DEC25, forecast DTGs 01/0600Z and 01/1800Z, outlook 02/1800Z)
 *   - (ESTIMATED )MINIMUM CENTRAL PRESSURE
 *   - the "$$" hard stop (forecaster sign-off past it is never scanned)
 *
 * Verified (see the Node fixture-parsing harness referenced in this
 * change's commit message) to parse identically in Vortex.html and the
 * mirror below: header {refDate [31,12,2025], TROPICAL STORM AL09
 * (PARITY), warning 9, 995 mb, basin AT}, four taus at 2025-12-31T21Z,
 * 2026-01-01T06Z/18Z and 2026-01-02T18Z, vmax 55/60/50/35 kt, conf
 * 1/1/1/0.6.
 */
var PARITY_FIXTURE_TCM = [
  'WTNT99 KNHC 312100',
  'TCMAT9',
  '',
  'TROPICAL STORM PARITY FORECAST/ADVISORY NUMBER  9',
  'NWS NATIONAL HURRICANE CENTER MIAMI FL       AL092025',
  '2100 UTC WED DEC 31 2025',
  '',
  'TROPICAL STORM CENTER LOCATED NEAR 18.0N  55.0W AT 31/2100Z',
  'POSITION ACCURATE WITHIN  20 NM',
  '',
  'PRESENT MOVEMENT TOWARD THE NORTH OR 010 DEGREES AT   8 KT',
  '',
  'ESTIMATED MINIMUM CENTRAL PRESSURE  995 MB',
  'MAX SUSTAINED WINDS 55 KT WITH GUSTS TO 70 KT.',
  '50 KT....... 20NE  15SE  10SW  20NW.',
  '34 KT.......100NE  80SE  60SW  90NW.',
  '4 M SEAS....150NE 120SE 100SW 140NW.',
  'WINDS AND SEAS VARY GREATLY IN EACH QUADRANT. THIS IS A SYNTHETIC',
  'PRODUCT (NOTE: PARITY) EMBEDDED SOLELY TO DRIVE THE PARSER SELF TEST -',
  'IT IS NOT A REAL NHC ADVISORY.',
  '',
  'REPEAT...CENTER LOCATED NEAR 18.0N  55.0W AT 31/2100Z',
  'AT 31/1800Z CENTER WAS LOCATED NEAR 17.6N  55.2W',
  '',
  'FORECAST VALID 01/0600Z 18.9N  54.6W',
  'MAX WIND  60 KT...GUSTS  75 KT.',
  '50 KT... 25NE  20SE  15SW  25NW.',
  '34 KT...110NE  90SE  70SW 100NW.',
  '',
  'FORECAST VALID 01/1800Z 19.8N  54.0W',
  'MAX WIND  50 KT...GUSTS  65 KT.',
  '34 KT...100NE  80SE  60SW  90NW.',
  '',
  'OUTLOOK VALID 02/1800Z 21.5N  53.0W...POST-TROPICAL',
  'MAX WIND  35 KT...GUSTS  45 KT.',
  '34 KT... 70NE  50SE  40SW  60NW.',
  '',
  'REQUEST FOR 3 HOURLY SHIP REPORTS WITHIN 300 MILES OF 18.0N  55.0W',
  '',
  'NEXT ADVISORY AT 01/0300Z',
  '',
  '$$',
  'FORECASTER PARITY',
  '',
  'NNNN'
].join('\n');


/** Raw text of Vortex.html's single <script> block. */
function vortexScriptSource_() {
  var html = HtmlService.createHtmlOutputFromFile(VORTEX_FILE).getContent();
  var open = html.indexOf('<script');
  if (open < 0) throw new Error(VORTEX_FILE + '.html has no <script> block');
  var bodyStart = html.indexOf('>', open) + 1;
  var close = html.lastIndexOf('<\/script>');
  if (close < bodyStart) throw new Error(VORTEX_FILE + '.html has no <\/script>');
  return html.substring(bodyStart, close);
}


/**
 * Evaluate Vortex.html's script into a private object and return its API.
 *
 * The file exports onto `window` when one exists. Passing our own object
 * in as a parameter NAMED `window` makes `typeof window` truthy inside,
 * so the exports land in the sandbox instead of on the script's globals -
 * which matters, because Vortex.html and this file define functions with
 * the same names.
 *
 * Not on any request path. Only checkParserParity() calls it.
 */
function loadVortexApi_() {
  var js = vortexScriptSource_();
  var sandbox = {};
  // No "use strict": the browser loads this file as a plain <script>, and
  // parity means matching THAT execution, not a stricter one.
  var factory = new Function('window', js + '\nreturn window;');
  return factory(sandbox);
}


/**
 * Normalise JavaScript for fingerprinting: drop whole-line comments, then
 * collapse every run of whitespace to one space.
 *
 * Line-oriented on purpose. A general comment stripper has to understand
 * string and regex literals to avoid mangling things like /a\/b/ and
 * 'http://x', and getting that wrong here would silently change the
 * digest. Trailing comments survive into the digest; that makes the
 * tripwire slightly noisier and never quieter, which is the right way for
 * it to be wrong.
 */
function normaliseJs_(src) {
  var lines = String(src).split(/\r?\n/);
  var keep = [];
  for (var i = 0; i < lines.length; i++) {
    var t = lines[i].replace(/^\s+/, '');
    if (t.indexOf('//') === 0) continue;
    if (t.indexOf('/*') === 0) continue;
    if (t.indexOf('*/') === 0) continue;
    if (t.indexOf('*') === 0) continue;   // continuation of a /** block
    keep.push(lines[i]);
  }
  return keep.join('\n').replace(/\s+/g, ' ').replace(/^ | $/g, '');
}


/** Hex SHA-256 of a string, via Utilities.computeDigest (signed bytes). */
function sha256Hex_(s) {
  var bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8);
  var hex = '';
  for (var i = 0; i < bytes.length; i++) {
    var b = bytes[i] < 0 ? bytes[i] + 256 : bytes[i];
    hex += (b < 16 ? '0' : '') + b.toString(16);
  }
  return hex;
}


/**
 * Fingerprint the canonical parser(s).
 *
 * Slices Vortex.html's script between its "JTWC warning parser" and
 * "Exports" section banners. If either banner has moved or been renamed,
 * the whole script is fingerprinted instead and `scope` says so - a
 * coarser tripwire, never a silently passing one. parseTCM() lives inside
 * that same span (right after describeStorm(), before the Exports banner),
 * so this ONE fingerprint already covers both parsers - no second anchor
 * pair was needed.
 *
 * Returns {scope, digest, pinned, matches, chars}.
 */
function parserFingerprint() {
  var js = vortexScriptSource_();
  var startAnchor = '// JTWC warning parser';
  var endAnchor = '// Exports';
  var a = js.indexOf(startAnchor);
  var b = js.indexOf(endAnchor, a >= 0 ? a : 0);
  var scope, region;
  if (a >= 0 && b > a) {
    scope = 'parser-section';
    region = js.substring(a, b);
  } else {
    scope = 'whole-file (section banners not found - anchors moved?)';
    region = js;
  }
  var norm = normaliseJs_(region);
  var digest = sha256Hex_(norm);
  return {
    scope: scope,
    digest: digest,
    pinned: VORTEX_PARSER_SHA,
    matches: (digest === VORTEX_PARSER_SHA),
    chars: norm.length
  };
}


/** Field-by-field diff of two parser results (parseJTWC() or parseTCM(),
 *  same shape either way). Returns [] when equal. */
function diffParseResults_(a, b, tol) {
  var diffs = [];
  var HEADER_FIELDS = ['systemType', 'stormId', 'stormName',
                       'warningNumber', 'pressureMb', 'basin'];
  var TAU_FIELDS = ['tau', 'epoch', 'lat', 'lon', 'vmax', 'gust',
                    'conf', 'motionDir', 'motionSpd'];

  function num(x) { return typeof x === 'number' && isFinite(x); }
  function cmp(path, x, y) {
    if (num(x) && num(y)) {
      if (Math.abs(x - y) > tol) {
        diffs.push(path + ': server ' + x + ' vs Vortex ' + y);
      }
    } else if (x !== y) {
      diffs.push(path + ': server ' + JSON.stringify(x) +
                 ' vs Vortex ' + JSON.stringify(y));
    }
  }

  for (var h = 0; h < HEADER_FIELDS.length; h++) {
    cmp('header.' + HEADER_FIELDS[h],
        a.header[HEADER_FIELDS[h]], b.header[HEADER_FIELDS[h]]);
  }
  for (var r = 0; r < 3; r++) {
    cmp('header.refDate[' + r + ']', a.header.refDate[r], b.header.refDate[r]);
  }

  if (a.taus.length !== b.taus.length) {
    diffs.push('taus.length: server ' + a.taus.length +
               ' vs Vortex ' + b.taus.length);
    return diffs;
  }

  for (var i = 0; i < a.taus.length; i++) {
    var ta = a.taus[i], tb = b.taus[i];
    for (var f = 0; f < TAU_FIELDS.length; f++) {
      cmp('taus[' + i + '].' + TAU_FIELDS[f],
          ta[TAU_FIELDS[f]], tb[TAU_FIELDS[f]]);
    }
    var thresholds = {}, key;
    for (key in ta.radii) thresholds[key] = 1;
    for (key in tb.radii) thresholds[key] = 1;
    for (key in thresholds) {
      var qa = ta.radii[key], qb = tb.radii[key];
      if (!qa || !qb) {
        diffs.push('taus[' + i + '].radii[' + key + ']: server ' +
                   (qa ? 'present' : 'absent') + ' vs Vortex ' +
                   (qb ? 'present' : 'absent'));
        continue;
      }
      for (var q = 0; q < QUADS.length; q++) {
        cmp('taus[' + i + '].radii[' + key + '].' + QUADS[q],
            qa[QUADS[q]], qb[QUADS[q]]);
      }
    }
  }
  return diffs;
}


/**
 * THE drift check for the duplicated parsers (parseJTWC() AND parseTCM()).
 * Run it from the Apps Script editor after touching either parser in
 * either file, and after any change to Vortex.html that the fingerprint
 * flags.
 *
 * @param {boolean} includeLive also run every live bulletin slot (all
 *        three basins) through both parsers (15 UrlFetch calls,
 *        cache-first). The two embedded fixtures (one per parser) always
 *        run.
 * @return {string} a report; also written to the log.
 */
function checkParserParity(includeLive) {
  var TOL = 1e-9;
  var lines = ['parser parity check, Code.gs v' + VERSION,
               'canonical: ' + VORTEX_FILE + '.html   mirror: Code.gs', ''];
  var failures = 0;

  // 1. fingerprint (covers parseJTWC() and parseTCM() together - see
  // parserFingerprint()'s docstring)
  try {
    var fp = parserFingerprint();
    lines.push('fingerprint scope : ' + fp.scope);
    lines.push('fingerprint       : ' + fp.digest + ' (' + fp.chars + ' chars)');
    lines.push('pinned            : ' + fp.pinned);
    if (fp.matches) {
      lines.push('                    MATCHES pin');
    } else {
      lines.push('                    CHANGED since the pin. Re-run this ' +
                 'check, then set VORTEX_PARSER_SHA to the value above.');
    }
  } catch (errFp) {
    failures++;
    lines.push('fingerprint       : FAILED - ' + errFp);
  }
  lines.push('');

  // 2. behavioural comparison
  var api;
  try {
    api = loadVortexApi_();
  } catch (errLoad) {
    lines.push('BEHAVIOURAL CHECK COULD NOT RUN: ' + errLoad);
    lines.push('It evaluates ' + VORTEX_FILE + '.html server-side via ' +
               'new Function(). If that is unavailable, the fingerprint ' +
               'above is the only remaining tripwire - treat any CHANGED ' +
               'as a hard stop and diff the two parsers by hand.');
    Logger.log(lines.join('\n'));
    return lines.join('\n');
  }
  if (typeof api.parseJTWC !== 'function' || typeof api.parseTCM !== 'function') {
    lines.push('BEHAVIOURAL CHECK COULD NOT RUN: ' + VORTEX_FILE +
               '.html did not export both parseJTWC and parseTCM on window.');
    Logger.log(lines.join('\n'));
    return lines.join('\n');
  }

  var cases = [
    { name: 'embedded synthetic JTWC fixture', text: PARITY_FIXTURE, parser: 'JTWC' },
    { name: 'embedded synthetic TCM fixture', text: PARITY_FIXTURE_TCM, parser: 'TCM' }
  ];
  if (includeLive) {
    var slots = getBulletins(false);
    for (var s = 0; s < slots.length; s++) {
      if (slots[s].ok && slots[s].storm && slots[s].storm.text) {
        cases.push({ name: 'live ' + slots[s].basin + ' ' + slots[s].file,
                     text: slots[s].storm.text,
                     parser: (slots[s].basin === 'WP') ? 'JTWC' : 'TCM' });
      } else {
        lines.push('live ' + slots[s].file + ': skipped (' +
                   (slots[s].error || 'no data') + ')');
      }
    }
  }

  for (var c = 0; c < cases.length; c++) {
    var name = cases[c].name;
    var isTcm = (cases[c].parser === 'TCM');
    var localFn = isTcm ? parseTCM : parseJTWC;
    var apiFn = isTcm ? api.parseTCM : api.parseJTWC;
    var mine, theirs, mineErr = null, theirsErr = null;
    try { mine = localFn(cases[c].text); } catch (e1) { mineErr = String(e1); }
    try { theirs = apiFn(cases[c].text); } catch (e2) { theirsErr = String(e2); }

    if (mineErr || theirsErr) {
      if (mineErr === theirsErr) {
        lines.push('OK    ' + name + ': both threw the same error');
      } else {
        failures++;
        lines.push('FAIL  ' + name + ': server threw ' + mineErr +
                   ', Vortex threw ' + theirsErr);
      }
      continue;
    }

    var diffs = diffParseResults_(mine, theirs, TOL);
    if (!diffs.length) {
      lines.push('OK    ' + name + ': ' + mine.taus.length +
                 ' taus, identical on every compared field');
    } else {
      failures++;
      lines.push('FAIL  ' + name + ': ' + diffs.length + ' difference(s)');
      for (var d = 0; d < diffs.length && d < 25; d++) {
        lines.push('        ' + diffs[d]);
      }
      if (diffs.length > 25) lines.push('        ... and more');
    }
  }

  lines.push('');
  lines.push(failures ? ('PARITY FAILED (' + failures + ')') : 'PARITY OK');
  Logger.log(lines.join('\n'));
  return lines.join('\n');
}


// ---------------------------------------------------------------------------
// Self tests, run from the editor
// ---------------------------------------------------------------------------

/**
 * Fetch every live slot and report what parsed, so a parser change can be
 * checked against real products before anyone looks at the map.
 */
function runSelfTest() {
  var res = getBulletins(true);
  var lines = ['bulletin parser self test (WP/AT/EP), v' + VERSION, ''];
  for (var i = 0; i < res.length; i++) {
    var r = res[i];
    if (!r.ok) {
      lines.push(r.basin + ' ' + r.file + ': ' + (r.error || 'no data') +
                 (r.hint ? '  [' + r.hint + ']' : ''));
      continue;
    }
    var s = r.storm;
    lines.push(r.basin + ' ' + r.file + ': ' + describeStorm(s.header) +
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


/**
 * Check that the generated data actually landed in the deployment, and
 * how big the payloads are. Cheap; no network.
 */
function runDataSelfTest() {
  var lines = ['data self test, v' + VERSION, ''];

  try {
    var idx = getArchiveIndex();
    var basins = {};
    for (var i = 0; i < idx.length; i++) {
      basins[idx[i].basin] = (basins[idx[i].basin] || 0) + 1;
    }
    var parts = [];
    for (var b in basins) parts.push(b + ' ' + basins[b]);
    lines.push('ARCHIVE_INDEX  : ' + idx.length + ' storms (' +
               parts.sort().join(', ') + '), ' +
               JSON.stringify(idx).length + ' chars serialised');
    if (idx.length) {
      var sid = idx[0].sid;
      var st = getArchiveStorm(sid);
      lines.push('getArchiveStorm: ' + sid + ' -> ' +
                 (st ? st.length + ' records, ' +
                       JSON.stringify(st).length + ' chars' : 'null'));
    }
    lines.push('unknown sid    : ' +
               JSON.stringify(getArchiveStorm('no-such-storm')));
    lines.push('__proto__ guard: ' +
               JSON.stringify(getArchiveStorm('__proto__')));
  } catch (errIdx) {
    lines.push('ARCHIVE        : FAILED - ' + errIdx);
  }

  try {
    var f = getFindings();
    lines.push('GTCM_FINDINGS  : generated ' + (f.generated || '?') +
               ', ' + JSON.stringify(f).length + ' chars');
  } catch (errF) {
    lines.push('GTCM_FINDINGS  : FAILED - ' + errF);
  }

  Logger.log(lines.join('\n'));
  return lines.join('\n');
}
