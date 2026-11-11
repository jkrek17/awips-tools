/* HSF checks and send text for the HSF editor page.

   The checks are those of Jason's Google Apps Script "OPC High Seas Forecast Validator"
   (dictionary, coordinates, wind and seas format, duplicate words) with the fixes and checks
   added on 2026-11-11 (lowercase, NONE / COLD / WARM / WHILE approved, warning level against the
   top wind, range order and steps of 5, missing periods and dot runs, stop at .FORECASTER), plus
   the map reader's own: an area the reader could not draw, or one that falls outside the
   forecast waters.

   HsfCheck.check(text, readResult) -> [{ sev: "error"|"warning"|"info", group, msg, word, at, end }]
     at/end: character offsets in `text` to select when the issue is clicked
   HsfCheck.sendText(text) -> the product as sent: paragraphs rejoined and wrapped at 66
   HsfCheck.section(sendText, ".WARNINGS.") -> the text of one editor box (no header line)
   Plain ES5; loads in the browser (window.HsfCheck) and in node (require). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.HsfCheck = factory();
})(this, function () {
  "use strict";

  var SEND_WIDTH = 66;

  // Jason's dictionary (auto-approved >= 500x across 16,735 OPC blocks) with NONE, COLD, WARM, WHILE
  var APPROVED = {};
  ("ABOVE ABSORBED ACTIVITY ADAK AFTER ALASKA ALEUTIAN ALEUTIANS ALSO AN AND ANY AREA AS ASH ASSOCIATED AT BAY BE " +
   "BELOW BERING BETWEEN BOUNDED BY CALLING CAUTION CENTER CHANGE COAST COLD COMBINED COMPLEX CONDITIONS COOK CYCLONE " +
   "DEBRIS DEG DENSE DESCRIBED DIMINISHED DISSIPATED DRIFTING EITHER ELSEWHERE EMISSIONS ENCOUNTER ENCOURAGED EXCEPT " +
   "EXERCISE EXTEND EXTENDING EXTENDS FIRST FLOATING FOG FORCE FORECAST FREEZING FROM FRONT FT GALE GREATER GREENLAND " +
   "GULF GUSTS HEAVY HIGH HIGHEST HOUR HOURS HURRICANE IF IMPROVED IN INCLUDING INLAND INLET INTENSIFYING IS ISLAND " +
   "ISLANDS JUST KT LAWRENCE LESS LEVEL LIGHT LINE LITTLE LOCATED LOW MAIN MARINERS MAXIMUM MAY MB MEAN MERGED MIXED " +
   "MODERATE MOVED MOVING NE NEAR NEARLY NEW NEXT NM NONE NOTED NW OBSERVATION OCCASIONALLY OCEAN OF OR OTHERWISE OVER " +
   "PLEASE POSITION POSSIBLE POST PREDICTION QUADRANT QUADRANTS RAPIDLY REPORT SAINT SE SEA SEAS SECOND SECONDARY " +
   "SECTION SEMICIRCLE SEMICIRCLES SEMISOPOCHNOI SHELIKOF SIDE SPRAY STATE STATIONARY STORM STRAIT SUSTAINED SW SWELL " +
   "THAN THE THEN THIRD TO TRACE TROPICAL TURN TURNING UNREST URGED UTC VICINITY VOLCANIC VOLCANO VSBY WARM WARNING " +
   "WARNINGS WELL WHERE WHILE WILL WIND WINDS WITH WITHIN YOU").split(" ").forEach(function (w) { APPROVED[w] = 1; });

  var LEVELS = [
    { re: /HURRICANE FORCE/, name: "Hurricane force", lo: 64, hi: 999 },
    { re: /STORM/, name: "Storm", lo: 48, hi: 63 },
    { re: /GALE/, name: "Gale", lo: 34, hi: 47 }
  ];

  // the checked block: .WARNINGS. down to .FORECASTER (names are not forecast words)
  function blockOf(t) {
    var a = t.search(/^[ \t]*\.WARNINGS\./mi);
    if (a < 0) a = t.search(/^[ \t]*\.SYNOPSIS AND FORECAST\./mi);
    if (a < 0) return null;
    var f = t.slice(a).search(/^[ \t]*\.FORECASTER\b/mi);
    return { a: a, b: f > -1 ? a + f : t.length };
  }
  // a pattern with spaces matches any run of white space (the text may be wrapped anywhere)
  function each(re, t, a, b, fn) {
    re.lastIndex = a;
    var m;
    while ((m = re.exec(t)) && m.index < b) {
      fn(m);
      if (re.lastIndex === m.index) re.lastIndex++;
    }
  }
  function issue(list, sev, group, msg, word, at, end) {
    list.push({ sev: sev, group: group, msg: msg, word: word || "", at: at, end: end });
  }
  function skipLine(t, i) {   // section header or warning label lines are not prose
    var s = t.lastIndexOf("\n", i - 1) + 1, e = t.indexOf("\n", i);
    var line = t.slice(s, e < 0 ? t.length : e);
    return /^\s*\.[A-Z][A-Z ]+\.\s*$/.test(line) || /^\s*\.\.\.\s*[A-Z][A-Z ]+\s*\.\.\.\s*$/.test(line);
  }

  function check(text, read) {
    var t = String(text || "").replace(/…/g, "...");
    var out = [], blk = blockOf(t);
    if (!blk) {
      issue(out, "error", "Structure", "No .WARNINGS. or .SYNOPSIS AND FORECAST. section found", "", 0, 0);
      return out;
    }
    var A = blk.a, B = blk.b, m;

    // ---- coordinates (any token mixing digits and N/S/E/W)
    each(/\b(?=[A-Za-z]*\d)(?=\d*[NSEWnsew])[\dNSEWnsew]{2,}\b/g, t, A, B, function (m) {
      var tok = m[0];
      if (/[nsew]/.test(tok)) { issue(out, "error", "Coordinates", "Lowercase coordinate (should be capitals)", tok, m.index, m.index + tok.length); return; }
      var full = /^(\d{1,2})[NS](\d{1,3})[EW]$/.exec(tok), lat = /^(\d{1,2})[NS]$/.exec(tok), lon = /^(\d{1,3})[EW]$/.exec(tok);
      if (!(full || lat || lon)) { issue(out, "warning", "Coordinates", "Unrecognized coordinate format", tok, m.index, m.index + tok.length); return; }
      if ((full && (+full[1] > 90 || +full[2] > 180)) || (lat && +lat[1] > 90) || (lon && +lon[1] > 180)) {
        issue(out, "error", "Coordinates", "Coordinate out of range", tok, m.index, m.index + tok.length);
      }
    });
    each(/\b\d{1,2}[NS]\s+\d{1,3}[EW]\b/g, t, A, B, function (m) {
      issue(out, "warning", "Coordinates", "Spaced coordinate (join it, e.g. 42N64W)", m[0].replace(/\s+/g, " "), m.index, m.index + m[0].length);
    });

    // ---- wind and seas format
    each(/\bKTS\b/g, t, A, B, function (m) { issue(out, "error", "Wind", "Use KT, not KTS", "KTS", m.index, m.index + 3); });
    each(/\bKNOTS\b/g, t, A, B, function (m) { issue(out, "error", "Wind", "Use KT, not KNOTS", "KNOTS", m.index, m.index + 5); });
    each(/\b\d+\s*-\s*\d+\s*KT\b/g, t, A, B, function (m) { issue(out, "error", "Wind", "Hyphenated wind range (write X TO Y KT)", m[0], m.index, m.index + m[0].length); });
    each(/\bMET(?:ERS|RES)\b/g, t, A, B, function (m) { issue(out, "error", "Seas", "Use M, not " + m[0], m[0], m.index, m.index + m[0].length); });
    each(/SEAS\s+[\d.]+\s*-\s*[\d.]+\s*M\b/g, t, A, B, function (m) { issue(out, "error", "Seas", "Hyphenated seas range (write X TO Y M)", m[0], m.index, m.index + m[0].length); });
    each(/SEAS\s+[\d.]+\s+TO\s+[\d.]+\s+FT\b/g, t, A, B, function (m) { issue(out, "error", "Seas", "Seas in feet (should be in M)", m[0], m.index, m.index + m[0].length); });

    each(/SEAS\s+(?:TO\s+)?[\d.]+(?:\s+TO\s+[\d.]+)?\s+KT\b/g, t, A, B, function (m) { issue(out, "error", "Seas", "Seas given in KT (should be M)", m[0].replace(/\s+/g, " "), m.index, m.index + m[0].length); });

    // ---- ranges: low before high, winds in steps of 5
    each(/\b(\d+)\s+TO\s+(\d+)\s+KT\b/g, t, A, B, function (m) {
      if (/SEAS\s+$/.test(t.slice(Math.max(0, m.index - 8), m.index))) return;   // seas in KT, flagged above
      var a = +m[1], b = +m[2], s = m[0].replace(/\s+/g, " ");
      if (a >= b) issue(out, "error", "Wind", "Wind range out of order", s, m.index, m.index + m[0].length);
      else if (a % 5 || b % 5) issue(out, "warning", "Wind", "Wind range not in steps of 5", s, m.index, m.index + m[0].length);
    });
    each(/SEAS\s+([\d.]+)\s+TO\s+([\d.]+)\s+M\b/g, t, A, B, function (m) {
      if (+m[1] >= +m[2]) issue(out, "error", "Seas", "Seas range out of order", m[0].replace(/\s+/g, " "), m.index, m.index + m[0].length);
    });

    // ---- punctuation: a sentence ends after KT and after M; "..." not ".." or "...."
    each(/\b(?:KT\s+SEAS|\d\s+M\s+(?:ALSO|ELSEWHERE|WITHIN|FROM|SEAS))\b/g, t, A, B, function (m) {
      issue(out, "error", "Punctuation", "Missing period", m[0].replace(/\s+/g, " "), m.index, m.index + m[0].length);
    });
    each(/(?:^|[^.])(\.\.)(?!\.)|\.{4,}/g, t, A, B, function (m) {
      var d = m[0].replace(/^[^.]/, ""), at = m.index + m[0].length - d.length;
      issue(out, "warning", "Punctuation", 'Dots (use "..." or ".")', d, at, at + d.length);
    });

    // ---- lowercase anywhere (the product is all capitals)
    each(/[a-z]+/g, t, A, B, function (m) {
      issue(out, "error", "Words", "Lowercase text (the product is all capitals)", m[0], m.index, m.index + m[0].length);
    });

    // ---- duplicate words
    each(/\b([A-Za-z]{3,})\s+\1\b/gi, t, A, B, function (m) {
      issue(out, "warning", "Words", "Repeated word", m[0].replace(/\s+/g, " ").toUpperCase(), m.index, m.index + m[0].length);
    });

    // ---- dictionary (first place each unknown word appears)
    var seen = {};
    each(/[A-Za-z]{2,}/g, t, A, B, function (m) {
      var w = m[0].toUpperCase(), i = m.index;
      if (/\d/.test(t.charAt(i - 1)) || /\d/.test(t.charAt(i + m[0].length))) return;   // inside a coordinate
      if (w === "ST") w = "SAINT";
      if (APPROVED[w] || skipLine(t, i)) return;
      if (seen[w]) { seen[w].n++; return; }
      seen[w] = { n: 1 };
      issue(out, "warning", "Words", "Unrecognized word", w, i, i + m[0].length);
      seen[w].issue = out[out.length - 1];
    });
    Object.keys(seen).forEach(function (w) { if (seen[w].n > 1) seen[w].issue.msg += " (" + seen[w].n + " times)"; });

    // ---- warning level against the top wind; gale or more outside the warnings
    var syn = t.slice(A, B).search(/^[ \t]*\.SYNOPSIS AND FORECAST\./m);
    syn = syn > -1 ? A + syn : B;
    var heads = [];
    each(/^[ \t]*\.\.\.\s*([A-Z ]+?)\s*\.\.\.[ \t]*$/gm, t, A, syn, function (m) { heads.push({ at: m.index, end: m.index + m[0].length, name: m[1] }); });
    heads.forEach(function (h, i) {
      var to = i + 1 < heads.length ? heads[i + 1].at : syn;
      var top = topWind(t, h.end, to);
      var lvl = null;
      for (var k = 0; k < LEVELS.length; k++) if (LEVELS[k].re.test(h.name)) { lvl = LEVELS[k]; break; }
      if (!lvl || !top.kt) return;
      var label = h.name.trim();
      if (top.kt < lvl.lo) issue(out, "warning", "Warning level", lvl.name + " warning, but the top wind is " + top.kt + " KT (needs " + lvl.lo + "+)", label, h.at, h.end);
      else if (top.kt > lvl.hi) issue(out, "error", "Warning level", lvl.name + " warning with winds to " + top.kt + " KT (above " + lvl.hi + ")", top.kt + " KT", top.at, top.end);
    });
    if (syn < B) {
      // each paragraph of the synopsis section
      var starts = [];
      each(/^[ \t]*\.(?!\.)/gm, t, syn + 1, B, function (m) { starts.push(m.index); });
      starts.push(B);
      for (var i = 0; i < starts.length - 1; i++) {
        var tw = topWind(t, starts[i], starts[i + 1]);
        if (tw.kt >= 34) issue(out, "error", "Warning level", "Winds to " + tw.kt + " KT in the synopsis section (gale or more belongs in the warnings)", tw.kt + " KT", tw.at, tw.end);
      }
    }

    // ---- across forecast times: low speed and depth, hour order, gaps between wind ranges, seas for the winds
    if (read && read.paras) acrossTimes(t, read, out);

    // ---- the map reader: areas it could not draw, or that fall outside the forecast waters
    if (read && read.paras) read.paras.forEach(function (p) {
      p.blocks.forEach(function (b) {
        (b.guessed || []).forEach(function (g) {
          var w = locate(t, g.from, p.start, p.end);
          issue(out, "warning", "Map", "Mapped as " + g.to, g.from, w[0], w[1]);
        });
        if (b.open && b.geom && b.geom.length) {
          var op = locate(t, b.area_text, p.start, p.end);
          issue(out, "warning", "Map", b.open === "lat" ? "No latitude limits, so this area runs the full height of the forecast waters"
            : "No longitude limits, so this area runs the full width of the forecast waters", short(b.area_text), op[0], op[1]);
        }
        if (b.outside && !b.unread.length) {
          var pos = locate(t, b.area_text, p.start, p.end);
          issue(out, "warning", "Map", "This area lies outside the forecast waters", short(b.area_text), pos[0], pos[1]);
        } else if (!b.ok) {
          var words = b.unread.join(" ").trim();
          var where = locate(t, words || b.area_text, p.start, p.end);
          issue(out, "info", "Map", words ? "The map could not read this part of the area" : "The map could not draw this area", short(words || b.area_text), where[0], where[1]);
        }
      });
    });

    var order = { error: 0, warning: 1, info: 2 };
    out.sort(function (a, b) { return order[a.sev] - order[b.sev] || a.at - b.at; });
    return out;
  }

  // ---- checks that read the product as a whole (thresholds from 1200 issued products per basin, 2026)
  var FAST_KT = 70;          // a low moving faster than this between steps: ~1% of steps, mostly typed positions
  var DEEPEN_6H = 15, FILL_6H = 12;   // MB per 6 h; issued lows pass these about 1 time in 1000
  var SEAS_MIN = [[64, 5], [48, 4], [34, 2.5]];   // lowest top seas (M) issued with these winds, about 1 in 200
  function nm(a, b) {
    var r = Math.PI / 180, d = Math.sin(a.lat * r) * Math.sin(b.lat * r) + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.cos((a.lon - b.lon) * r);
    return Math.acos(Math.min(1, d)) * 3440;
  }
  function hh(h) { return h ? (h < 10 ? "0" : "") + h + " HOUR" : "synopsis"; }
  function find(t, re, a, b) {
    re = new RegExp(re.source, "g");
    re.lastIndex = a;
    var m = re.exec(t);
    return m && m.index < b ? [m.index, m.index + m[0].length, m[0].replace(/\s+/g, " ")] : null;
  }
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  function acrossTimes(t, read, out) {
    var P = read.paras;
    (read.tracks || []).forEach(function (tr) {
      var flagged = {};
      for (var i = 1; i < tr.points.length; i++) {
        var a = tr.points[i - 1], b = tr.points[i], h = b.hour - a.hour;
        if (h <= 0) continue;
        var pb = P[b.para], at = pb ? find(t, new RegExp(esc(b.raw || "")), pb.start, pb.end) : null;
        if (!at) at = pb ? [pb.start, pb.start + 1, ""] : [0, 0, ""];
        var kt = nm(a, b) / h;
        if (kt > FAST_KT && !flagged[i - 1]) {
          flagged[i] = 1;
          issue(out, "warning", "Across times", "Low moves " + Math.round(kt) + " KT from " + (a.raw || "") + " (" + hh(a.hour) + ") to " + (b.raw || "") +
            " (" + hh(b.hour) + "): check the position", b.raw || "", at[0], at[1]);
        }
        if (a.mb && b.mb) {
          var d6 = (b.mb - a.mb) / h * 6, mbAt = find(t, new RegExp("\\b" + b.mb + "\\s+MB\\b"), pb.start, pb.end) || at;
          if (d6 <= -DEEPEN_6H) issue(out, "warning", "Across times", "Low deepens " + (a.mb - b.mb) + " MB in " + h + " h (" + a.mb + " to " + b.mb + " MB): check the pressure", b.mb + " MB", mbAt[0], mbAt[1]);
          else if (d6 >= FILL_6H) issue(out, "warning", "Across times", "Low fills " + (b.mb - a.mb) + " MB in " + h + " h (" + a.mb + " to " + b.mb + " MB): check the pressure", b.mb + " MB", mbAt[0], mbAt[1]);
        }
      }
    });
    // forecast hours in order inside each warning
    var last = {};
    P.forEach(function (p) {
      if (p.section !== "warnings") return;
      var k = p.system, prev = last[k];
      if (prev && p.hour && p.hour <= prev.hour) {   // several synopsis paragraphs in one warning are normal
        var w = find(t, /\d{1,2} HOUR FORECAST/, p.start, p.end) || [p.start, p.start + 1, ""];
        issue(out, "warning", "Across times", (p.hour === prev.hour ? "Second " + hh(p.hour) + " FORECAST in this warning" : hh(p.hour) + " FORECAST comes after the " + (prev.hour ? hh(prev.hour) + " FORECAST" : "synopsis")), w[2], w[0], w[1]);
      }
      last[k] = p;
    });
    // inside each paragraph: no gap between one range and the ELSEWHERE range below it; seas that fit the winds
    var WRE = /\bWINDS?\s+(?:(?:LESS THAN|UP TO|TO)\s+)?(?:(\d+)\s+TO\s+)?(\d+)\s*KT\b/;
    P.forEach(function (p) {
      var pos = p.start, prev = null;
      p.blocks.forEach(function (b) {
        if (!b.wind[1] || b.wind[1] > 150) return;
        var src = (b.wind[0] ? b.wind[0] + "\\s+TO\\s+" : "(?:(?:LESS THAN|UP TO|TO)\\s+)?") + b.wind[1] + "\\s*KT\\b";
        var w = find(t, new RegExp("\\bWINDS?\\s+" + src), pos, p.end) || find(t, new RegExp(src), pos, p.end);
        if (!w) return;
        pos = w[1];
        if (prev && b.tier === "elsewhere" && b.wind[1] < prev.wind[0]) {
          issue(out, "warning", "Wind", "Gap between wind ranges: " + (prev.wind[0] ? prev.wind[0] + " TO " : "TO ") + prev.wind[1] + " KT, then " +
            (b.wind[0] ? b.wind[0] + " TO " : "TO ") + b.wind[1] + " KT (nothing for " + b.wind[1] + " TO " + prev.wind[0] + " KT)", w[2], w[0], w[1]);
        }
        if (b.seas && b.seas[2] === "M") {
          for (var i = 0; i < SEAS_MIN.length; i++) if (b.wind[1] >= SEAS_MIN[i][0]) {
            if (b.seas[1] < SEAS_MIN[i][1]) {
              var s = find(t, /SEAS\s+(?:(?:LESS THAN|UP TO|TO)\s+)?[\d.]+(?:\s+TO\s+[\d.]+)?\s*M\b/, w[1], p.end) || w;
              issue(out, "warning", "Seas", "Seas to " + b.seas[1] + " M are low for winds to " + b.wind[1] + " KT (issued forecasts give at least " + SEAS_MIN[i][1] + " M)", s[2], s[0], s[1]);
            }
            break;
          }
        }
        prev = b;
      });
    });
  }

  function short(s) { s = s.replace(/\s+/g, " ").trim(); return s.length > 60 ? s.slice(0, 57) + "..." : s; }
  // offsets of `s` inside text[a, b), matching any run of white space
  function locate(t, s, a, b) {
    var words = s.replace(/\s+/g, " ").trim();
    if (!words) return [a, b];
    var re = new RegExp(words.split(" ").slice(0, 8).map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("\\s+"), "i");
    var m = re.exec(t.slice(a, b));
    return m ? [a + m.index, a + m.index + m[0].length] : [a, b];
  }
  // the highest "NN KT" in t[a, b), leaving out movement and gusts
  function topWind(t, a, b) {
    var re = /(\d+)\s+KT\b/g, m, top = { kt: 0, at: a, end: a };
    re.lastIndex = a;
    while ((m = re.exec(t)) && m.index < b) {
      var pre = t.slice(Math.max(a, m.index - 24), m.index).replace(/\s+/g, " ");
      if (/(?:MOVING|DRIFTING) [A-Z]+ $|GUSTS $|DEG AT $| AT $/.test(pre)) continue;
      if (+m[1] > top.kt) top = { kt: +m[1], at: m.index, end: m.index + m[0].length };
    }
    return top;
  }

  // ---- send text (as the Apps Script's "Show Text to Send")
  function wrapLine(line, width) {
    var words = line.split(" ").filter(function (w) { return w.length > 0; }), out = [], cur = "";
    for (var i = 0; i < words.length; i++) {
      if (!cur) cur = words[i];
      else if (cur.length + 1 + words[i].length <= width) cur += " " + words[i];
      else { out.push(cur); cur = words[i]; }
    }
    if (cur) out.push(cur);
    return out.join("\n");
  }
  function sendText(raw) {
    var t = String(raw || "").replace(/\r\n?/g, "\n").replace(/\u000b/g, "\n").replace(/…/g, "...").replace(/ /g, " ")
      .replace(/[ \t]+/g, " ").replace(/ +\n/g, "\n").replace(/\n +/g, "\n");
    var s = t.indexOf("SYNOPSIS VALID");
    if (s > 0) t = t.substring(s);
    var f = t.indexOf(".FORECASTER");
    if (f > 0) t = t.substring(0, f);
    t = t.replace(/ *\n* *(\.WARNINGS\.|\.SYNOPSIS AND FORECAST\.) *\n* */g, "\n\n$1\n\n");
    return t.trim().split(/\n\s*\n/).map(function (p) {
      var lines = p.replace(/\n(?!\.)(?!\d{1,2} HOUR FORECAST VALID\b)/g, " ")
        .replace(/ (?=\d{1,2} HOUR FORECAST VALID\b)/g, "\n").split("\n");
      return lines.map(function (l) { return wrapLine(l.trim(), SEND_WIDTH); }).join("\n");
    }).join("\n\n") + "\n";
  }
  function section(t, header) {
    var lines = t.split("\n"), a = lines.indexOf(header);
    if (a < 0) return "";
    var b = lines.length;
    for (var i = a + 1; i < lines.length; i++) if (/^\.(WARNINGS|SYNOPSIS AND FORECAST|FORECASTER)\b/.test(lines[i])) { b = i; break; }
    var body = lines.slice(a + 1, b).join("\n").replace(/^\s+|\s+$/g, "");
    return body ? body + "\n" : "";
  }

  return { check: check, sendText: sendText, section: section, SEND_WIDTH: SEND_WIDTH, APPROVED: APPROVED };
});
