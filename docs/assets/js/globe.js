/* Orthographic globe for the "both basins" view: the Atlantic and Pacific
   tracks meet at the pole, and no flat projection shows that honestly, so
   this draws a rotatable sphere instead.

   Projection: hand-rolled orthographic, parameterized by a view centre
   (lambda, phi) in radians - no roll/gamma, which keeps the trigonometry to
   the textbook two-angle case (Snyder, "Map Projections - A Working
   Manual", the orthographic azimuthal formulas). A point is visible when the
   cosine of its angular distance from the view centre is >= 0; every line
   (track, coastline ring, graticule meridian/parallel) is walked once per
   draw and split at that horizon rather than being allowed to draw a chord
   straight across the disc between a visible and a hidden point. The split
   point itself is found with a bisection along the great-circle arc (via
   3D unit-vector slerp) between the two endpoints, so it lands exactly on
   the horizon circle instead of approximating it in lon/lat space.

   Canvas 2D, no third-party library. */

window.HF = window.HF || {};

(function (globe, HF) {
  'use strict';

  var DEG = Math.PI / 180;

  // Default view: both basins splayed symmetrically around the pole rather
  // than one sitting near the horizon. Picked empirically from the archive
  // itself, not guessed: the circular mean fix longitude is -39.7 for the
  // Atlantic and -179.5 (essentially the dateline) for the Pacific - about
  // 140 apart the short way round, over Canada and the Arctic (the other
  // way round, over Eurasia, is the wide ~220 gap and would foreshorten
  // both basins badly). Centring on the midpoint of the short gap puts
  // each basin about 70 of longitude off-axis, comfortably on the near
  // side rather than crowding the horizon. Phi is pulled up near the pole
  // (rather than the ~50N the tracks are centred on) so both belts curve
  // away from the centre symmetrically instead of one filling the middle.
  var DEFAULT_LAMBDA_DEG = -110;
  var DEFAULT_PHI_DEG = 68;

  var MIN_ZOOM = 0.6, MAX_ZOOM = 6;
  var MAX_PHI = 89 * DEG;               // clamp shy of the exact pole

  var HIT_RADIUS = 9;                    // px, hover/click pick tolerance
  var CLICK_SLOP = 4;                    // px of movement still counted as a click
  var HOVER_THROTTLE_MS = 30;

  var GRATICULE_LON_STEP = 30;
  var GRATICULE_LAT_STEP = 15;
  var GRATICULE_SAMPLE_DEG = 3;          // sampling interval along each graticule line

  /* ------------------------------------------------------------- state */

  var canvas = null, ctx = null, onSelect = null;
  var cssW = 0, cssH = 0, dpr = 1, cx = 0, cy = 0, baseR = 0;

  var view = {
    lambda: DEFAULT_LAMBDA_DEG * DEG,
    phi: DEFAULT_PHI_DEG * DEG,
    zoom: 1
  };

  var lows = [];
  var selectedKey = null;

  var visible = false;
  var dirty = true;
  var rafId = null;

  var pal = null;                        // theme colours, refreshed by applyTheme()

  var dragging = false;
  var dragLast = null;
  var dragMoved = 0;
  var pointerId = null;

  // Inertia: a short decaying spin after a fast drag release.
  var inertia = null;                    // {vx, vy} in rad/ms, or null
  var lastMoveT = 0, lastMoveDx = 0, lastMoveDy = 0;

  var hitPoints = [];                    // rebuilt each draw(): [{x, y, low}]
  var lastHoverT = 0;
  var hoveredKey = undefined;            // undefined = "not computed yet"

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* ------------------------------------------------------------ geometry */

  function toXYZ(lonDeg, latDeg) {
    var lon = lonDeg * DEG, lat = latDeg * DEG;
    var cosLat = Math.cos(lat);
    return [cosLat * Math.cos(lon), cosLat * Math.sin(lon), Math.sin(lat)];
  }

  function fromXYZ(v) {
    var lat = Math.asin(Math.max(-1, Math.min(1, v[2])));
    return [Math.atan2(v[1], v[0]) / DEG, lat / DEG];
  }

  function dot3(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

  function slerp(a, b, t) {
    var d = Math.max(-1, Math.min(1, dot3(a, b)));
    var omega = Math.acos(d);
    if (omega < 1e-6) return a;
    var s = Math.sin(omega);
    var wa = Math.sin((1 - t) * omega) / s, wb = Math.sin(t * omega) / s;
    return [a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb, a[2] * wa + b[2] * wb];
  }

  function viewVector() {
    var c = Math.cos(view.phi);
    return [c * Math.cos(view.lambda), c * Math.sin(view.lambda), Math.sin(view.phi)];
  }

  /** Orthographic projection of one geographic point against the current
      view. x depends only on the longitude offset; y carries the tilt. */
  function project(lonDeg, latDeg) {
    var lambda = lonDeg * DEG, phi = latDeg * DEG;
    var dl = lambda - view.lambda;
    var cosPhi = Math.cos(phi), sinPhi = Math.sin(phi);
    var cosDl = Math.cos(dl);
    var x = cosPhi * Math.sin(dl);
    var y = Math.cos(view.phi) * sinPhi - Math.sin(view.phi) * cosPhi * cosDl;
    var c = Math.sin(view.phi) * sinPhi + Math.cos(view.phi) * cosPhi * cosDl;
    var R = baseR * view.zoom;
    return { x: cx + x * R, y: cy - y * R, visible: c >= 0 };
  }

  /** Point where the great-circle arc a->b crosses the horizon (cos = 0),
      found by bisection along a 3D slerp so it lands exactly on the disc's
      rim in screen space, whatever the two endpoints' longitudes. */
  function horizonCrossing(a, b) {
    var vv = viewVector();
    var pa = toXYZ(a[0], a[1]), pb = toXYZ(b[0], b[1]);
    var signA = dot3(pa, vv) >= 0;
    var lo = 0, hi = 1;
    for (var i = 0; i < 24; i++) {
      var mid = (lo + hi) / 2;
      var pm = slerp(pa, pb, mid);
      if ((dot3(pm, vv) >= 0) === signA) lo = mid; else hi = mid;
    }
    return fromXYZ(slerp(pa, pb, (lo + hi) / 2));
  }

  /** Walk a polyline/ring of [lon, lat] points and return the visible
      pieces as arrays of projected {x, y}, cut at the horizon rather than
      drawing a chord between a visible and a hidden point. Rings in the
      coastline data are already closed (first point repeats as last), so a
      ring needs no special wrap-around handling here. */
  function visibleSegments(coords) {
    var segments = [];
    var current = null;
    var prevCoord = null, prevVisible = null;

    for (var i = 0; i < coords.length; i++) {
      var pt = coords[i];
      var proj = project(pt[0], pt[1]);

      if (proj.visible) {
        if (!current) {
          current = [];
          if (prevCoord && prevVisible === false) {
            var enter = horizonCrossing(prevCoord, pt);
            current.push(project(enter[0], enter[1]));
          }
        }
        current.push(proj);
      } else if (current) {
        var exit = horizonCrossing(prevCoord, pt);
        current.push(project(exit[0], exit[1]));
        segments.push(current);
        current = null;
      }

      prevCoord = pt;
      prevVisible = proj.visible;
    }
    if (current) segments.push(current);
    return segments;
  }

  /* -------------------------------------------------------------- theme */

  function readColor(name, fallback) {
    var v = HF.cssVar(name);
    return v || fallback;
  }

  function computePalette() {
    // Track/fix colours (pressure ramp, event class, category) are read on
    // demand via HF.pressureColor/classColor/categoryColor, which already
    // pull from --seq-*, --critical, --ink-muted etc; this palette only
    // covers the globe's own chrome - sphere, graticule, land - and stays
    // strictly neutral so it never competes with the blue pressure ramp or
    // the magenta terrain-forced tracks.
    //
    // --surface and --surface-sunk alone are too close in value to read as
    // land vs. ocean at this size (a few percent lightness apart), so the
    // ocean disc gets an extra low-alpha wash toward --ink on top of its
    // base tone - a compositing trick, not a new hardcoded colour: --ink is
    // near-black in light mode and near-white in dark mode, so the wash
    // pushes the ocean away from the land tone in whichever direction each
    // theme needs. The coastline itself is stroked in --ink-2 (a mid-value
    // token meant for secondary text) so it reads as a firm line against
    // both fills in both themes, not a hairline.
    pal = {
      ocean: readColor('--surface-sunk', '#f2f2ee'),
      oceanWash: readColor('--ink', '#0b0b0b'),
      land: readColor('--surface', '#fcfcfb'),
      coast: readColor('--ink-2', '#52514e'),
      grid: readColor('--grid', '#e1e0d9'),
      outline: readColor('--border-strong', '#c3c2b7')
    };
  }

  globe.applyTheme = function () {
    computePalette();
    dirty = true;
    scheduleFrame();
  };

  /* --------------------------------------------------------------- draw */

  function styleForCount(n) {
    // Mirrors map.js: thousands of overlapping tracks saturate into a solid
    // blob, so strokes thin out as the count grows and overplotting itself
    // carries the sense of density.
    if (n > 800) return { weight: 0.7, opacity: 0.22 };
    if (n > 300) return { weight: 0.9, opacity: 0.4 };
    return { weight: 1.3, opacity: 0.7 };
  }

  function strokePath(segments, lineWidth, strokeStyle, dash) {
    ctx.lineWidth = lineWidth;
    ctx.strokeStyle = strokeStyle;
    ctx.setLineDash(dash || []);
    for (var i = 0; i < segments.length; i++) {
      var seg = segments[i];
      if (seg.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(seg[0].x, seg[0].y);
      for (var j = 1; j < seg.length; j++) ctx.lineTo(seg[j].x, seg[j].y);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  function drawGraticule() {
    var lines = [];
    var lon;
    for (lon = -180; lon < 180; lon += GRATICULE_LON_STEP) {
      var meridian = [];
      for (var lat = -90; lat <= 90; lat += GRATICULE_SAMPLE_DEG) meridian.push([lon, lat]);
      lines.push(meridian);
    }
    for (var lat0 = -90 + GRATICULE_LAT_STEP; lat0 < 90; lat0 += GRATICULE_LAT_STEP) {
      var parallel = [];
      for (lon = -180; lon <= 180; lon += GRATICULE_SAMPLE_DEG) parallel.push([lon, lat0]);
      lines.push(parallel);
    }
    ctx.globalAlpha = 0.6;
    for (var i = 0; i < lines.length; i++) {
      strokePath(visibleSegments(lines[i]), 0.6, pal.grid);
    }
    ctx.globalAlpha = 1;
  }

  function drawLand() {
    var coast = window.HF_COAST;
    if (!coast || !coast.polygons) return;
    var polys = coast.polygons;
    var R = baseR * view.zoom;
    var i;
    var allSegments = new Array(polys.length);
    for (i = 0; i < polys.length; i++) allSegments[i] = visibleSegments(polys[i]);

    // Fill each ring as a single closed path per visible arc, bridging the
    // hidden gaps along the horizon circle itself (the short way round)
    // rather than a straight line - a landmass whose ring dips off the
    // visible hemisphere and back must not fill a chord across the ocean
    // between its two horizon crossings.
    ctx.fillStyle = pal.land;
    for (i = 0; i < allSegments.length; i++) fillClippedRing(allSegments[i], R);

    // The coastline itself is stroked separately, per visible arc with no
    // closing edge - the horizon bridge above is not a real coastline, and
    // the sphere outline drawn later already marks the disc's rim.
    for (i = 0; i < allSegments.length; i++) strokePath(allSegments[i], 0.9, pal.coast);
  }

  /** Fill one ring's visible arcs as a single closed path, connecting the
      end of each arc to the start of the next along the horizon circle
      (the shorter way round) instead of a straight chord. With one fully
      visible arc the bridge collapses to a zero-length no-op, so this
      also handles an unclipped ring with no special-casing. */
  function fillClippedRing(segments, R) {
    if (!segments.length) return;
    ctx.beginPath();
    ctx.moveTo(segments[0][0].x, segments[0][0].y);
    for (var i = 0; i < segments.length; i++) {
      var seg = segments[i];
      for (var j = (i === 0 ? 1 : 0); j < seg.length; j++) ctx.lineTo(seg[j].x, seg[j].y);
      var next = segments[(i + 1) % segments.length][0];
      bridgeHorizon(seg[seg.length - 1], next, R);
    }
    ctx.closePath();
    ctx.fill();
  }

  function bridgeHorizon(from, to, R) {
    var a1 = Math.atan2(from.y - cy, from.x - cx);
    var a2 = Math.atan2(to.y - cy, to.x - cx);
    var delta = a2 - a1;
    while (delta > Math.PI) delta -= Math.PI * 2;
    while (delta < -Math.PI) delta += Math.PI * 2;
    if (Math.abs(delta) < 1e-9) return;
    ctx.arc(cx, cy, R, a1, a1 + delta, delta < 0);
  }

  /** Mean pressure of a segment's two endpoint fixes, for HF.pressureColor.
      Falls back to whichever endpoint has a value if only one does, or null
      (letting HF.pressureColor pick its own no-data colour) if neither. */
  function segmentPressure(a, b) {
    if (a.pres != null && b.pres != null) return (a.pres + b.pres) / 2;
    if (a.pres != null) return a.pres;
    if (b.pres != null) return b.pres;
    return null;
  }

  /** Stroke one fix-to-fix edge, clipped to the visible hemisphere, in the
      given colour. Horizon clipping is per-edge here (rather than the
      shared visibleSegments() arc-batching used for coastlines/graticule)
      because each edge can carry its own colour off the pressure ramp - a
      deepening track visibly ramps warmer along its length instead of
      drawing as one flat colour for the whole event. */
  function strokeEdge(a, b, color) {
    var pa = project(a.lon, a.lat), pb = project(b.lon, b.lat);
    if (!pa.visible && !pb.visible) return;
    var p0 = pa, p1 = pb;
    if (pa.visible !== pb.visible) {
      var cross = horizonCrossing([a.lon, a.lat], [b.lon, b.lat]);
      var pc = project(cross[0], cross[1]);
      if (pa.visible) p1 = pc; else p0 = pc;
    }
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.moveTo(p0.x, p0.y);
    ctx.lineTo(p1.x, p1.y);
    ctx.stroke();
  }

  function drawTracks() {
    hitPoints = [];
    var style = styleForCount(lows.length);
    var selected = null;

    ctx.lineCap = 'round';    // smooths the join between adjacent-colour segments
    for (var i = 0; i < lows.length; i++) {
      var low = lows[i];
      if (low.key === selectedKey) { selected = low; continue; }
      drawOneTrack(low, style, false);
    }
    if (selected) drawOneTrack(selected, style, true);
    ctx.lineCap = 'butt';
  }

  function drawOneTrack(low, style, isSelected) {
    var fixes = low.fixes;
    var terrain = low.cls && low.cls !== 'low';
    var weight = isSelected ? Math.max(2.4, style.weight + 1.6) : (terrain ? style.weight + 0.3 : style.weight);
    var opacity = isSelected ? 1 : Math.min(1, style.opacity + (terrain ? 0.15 : 0));
    var terrainColor = terrain ? HF.classColor(low.cls) : null;

    ctx.globalAlpha = opacity;
    ctx.lineWidth = weight;
    ctx.setLineDash(terrain ? [4, 3] : []);
    var i;
    for (i = 0; i < fixes.length - 1; i++) {
      var a = fixes[i], b = fixes[i + 1];
      // Terrain-forced events have no analyzed pressure at all, so they stay
      // one flat classColor; synoptic lows ramp per segment off the mean
      // pressure of each edge's two endpoints, so a deepening track visibly
      // warms along its length rather than drawing as one flat colour.
      var color = terrain ? terrainColor : HF.pressureColor(segmentPressure(a, b));
      strokeEdge(a, b, color);
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // Hit points from every fix, visible ones only - built once here and
    // reused for every hover/click test until the next draw().
    for (i = 0; i < low.fixes.length; i++) {
      var f = low.fixes[i];
      var p = project(f.lon, f.lat);
      if (p.visible) hitPoints.push({ x: p.x, y: p.y, low: low });
    }

    if (isSelected) {
      for (i = 0; i < low.fixes.length; i++) {
        var fix = low.fixes[i];
        var pp = project(fix.lon, fix.lat);
        if (!pp.visible) continue;
        ctx.beginPath();
        ctx.arc(pp.x, pp.y, fix.cat === 'HF' ? 3 : 2.3, 0, Math.PI * 2);
        ctx.fillStyle = HF.categoryColor(fix.cat);
        ctx.fill();
      }
    }
  }

  function draw() {
    if (!ctx || !cssW || !cssH || !pal) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var R = baseR * view.zoom;

    // 1. ocean disc - base tone plus a low-alpha ink wash (see computePalette)
    // so it reads as a distinct value from the land fill in both themes.
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.fillStyle = pal.ocean;
    ctx.fill();
    ctx.fillStyle = pal.oceanWash;
    ctx.globalAlpha = 0.12;
    ctx.fill();
    ctx.globalAlpha = 1;

    // 2. graticule
    drawGraticule();

    // 3. land
    drawLand();

    // 4. tracks (selected highlighted last within this pass)
    drawTracks();

    // 5. sphere outline, always on top and always a full circle
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = pal.outline;
    ctx.stroke();
  }

  /* ---------------------------------------------------------- animation
     Redraw only when something changed (dirty) or while actively dragging
     or coasting on inertia - never a permanent background loop. */

  function scheduleFrame() {
    if (rafId || !visible) return;
    rafId = window.requestAnimationFrame(tick);
  }

  function tick() {
    rafId = null;
    if (!visible) return;

    var animating = dragging || !!inertia;
    if (dirty || animating) {
      if (inertia) stepInertia();
      draw();
      dirty = false;
    }
    if (animating) scheduleFrame();
  }

  function stepInertia() {
    view.lambda += inertia.vx;
    view.phi = clampPhi(view.phi + inertia.vy);
    inertia.vx *= 0.94;
    inertia.vy *= 0.94;
    if (Math.abs(inertia.vx) < 0.00005 && Math.abs(inertia.vy) < 0.00005) inertia = null;
  }

  function clampPhi(p) { return Math.max(-MAX_PHI, Math.min(MAX_PHI, p)); }

  /* ------------------------------------------------------------ hit test */

  function nearestHit(px, py) {
    var best = null, bestD = HIT_RADIUS * HIT_RADIUS;
    for (var i = 0; i < hitPoints.length; i++) {
      var hp = hitPoints[i];
      var dx = hp.x - px, dy = hp.y - py;
      var d = dx * dx + dy * dy;
      if (d <= bestD) { bestD = d; best = hp; }
    }
    return best;
  }

  function fixTip(low) {
    return '<b>' + low.id + '</b> &middot; ' + HF.seasonLabel(low.season) +
      '<div class="t-row">' + HF.fmtDate(low.start) + '</div>' +
      (low.cls === 'tipjet'
        ? '<div class="t-row">Tip jet candidate &mdash; no analyzed centre</div>'
        : low.cls === 'nocentre'
          ? '<div class="t-row">No analyzed centre</div>' : '') +
      '<div class="t-row">Min ' + (low.minP != null ? low.minP + ' hPa' : 'not analyzed') +
      ' &middot; ' + low.hfH + ' h at HF</div>';
  }

  function handleHover(evt, rect) {
    var now = performance.now();
    if (now - lastHoverT < HOVER_THROTTLE_MS) return;
    lastHoverT = now;

    var px = evt.clientX - rect.left, py = evt.clientY - rect.top;
    var hit = nearestHit(px, py);
    var key = hit ? hit.low.key : null;

    if (key !== hoveredKey) {
      hoveredKey = key;
      if (hit) HF.showTip(fixTip(hit.low), evt); else HF.hideTip();
    } else if (hit) {
      HF.moveTip(evt);
    }
  }

  /* --------------------------------------------------------- interaction */

  function onPointerDown(evt) {
    if (evt.button != null && evt.button !== 0) return;
    dragging = true;
    dragMoved = 0;
    dragLast = { x: evt.clientX, y: evt.clientY };
    lastMoveDx = 0; lastMoveDy = 0; lastMoveT = performance.now();
    inertia = null;
    pointerId = evt.pointerId;
    canvas.classList.add('is-dragging');
    if (canvas.setPointerCapture) {
      try { canvas.setPointerCapture(evt.pointerId); } catch (err) { /* ignore */ }
    }
    evt.preventDefault();
  }

  function onPointerMove(evt) {
    var rect = canvas.getBoundingClientRect();

    if (dragging && dragLast) {
      var dx = evt.clientX - dragLast.x, dy = evt.clientY - dragLast.y;
      dragLast = { x: evt.clientX, y: evt.clientY };
      dragMoved += Math.abs(dx) + Math.abs(dy);

      var R = baseR * view.zoom;
      var k = 1 / Math.max(1, R);
      view.lambda -= dx * k;
      view.phi = clampPhi(view.phi + dy * k);

      var now = performance.now();
      var dt = Math.max(1, now - lastMoveT);
      lastMoveDx = -dx * k * (16 / dt);   // per-frame-ish velocity for inertia
      lastMoveDy = dy * k * (16 / dt);
      lastMoveT = now;

      dirty = true;
      scheduleFrame();
      HF.hideTip();
      hoveredKey = undefined;
    } else {
      handleHover(evt, rect);
    }
  }

  function endDrag(evt) {
    if (!dragging) return;
    dragging = false;
    canvas.classList.remove('is-dragging');
    if (pointerId != null && canvas.releasePointerCapture) {
      try { canvas.releasePointerCapture(pointerId); } catch (err) { /* ignore */ }
    }
    pointerId = null;

    if (dragMoved <= CLICK_SLOP) {
      var rect = canvas.getBoundingClientRect();
      var px = evt.clientX - rect.left, py = evt.clientY - rect.top;
      var hit = nearestHit(px, py);
      if (hit && onSelect) onSelect(hit.low);
    } else if (!reducedMotion() && (Math.abs(lastMoveDx) > 0.0003 || Math.abs(lastMoveDy) > 0.0003)) {
      inertia = { vx: lastMoveDx, vy: lastMoveDy };
      scheduleFrame();
    }
    dirty = true;
    scheduleFrame();
  }

  function onWheel(evt) {
    evt.preventDefault();
    var factor = Math.pow(1.0016, -evt.deltaY);
    view.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom * factor));
    dirty = true;
    scheduleFrame();
  }

  function onDblClick() {
    view.lambda = DEFAULT_LAMBDA_DEG * DEG;
    view.phi = DEFAULT_PHI_DEG * DEG;
    view.zoom = 1;
    inertia = null;
    dirty = true;
    scheduleFrame();
  }

  function onLeave() {
    if (!dragging) { hoveredKey = undefined; HF.hideTip(); }
  }

  /* ------------------------------------------------------------- public */

  globe.init = function (elementId, onSelectCb) {
    canvas = document.getElementById(elementId);
    if (!canvas || !canvas.getContext) return null;
    ctx = canvas.getContext('2d');
    onSelect = onSelectCb;
    computePalette();

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('mouseleave', onLeave);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', onDblClick);

    globe.resize();
    return canvas;
  };

  globe.render = function (lowsArg, selKey) {
    lows = lowsArg || [];
    selectedKey = selKey || null;
    dirty = true;
    scheduleFrame();
  };

  /** Rotate so this event's track faces the viewer. The centre is the
      circular mean of its fixes' unit vectors, not a plain lon/lat average,
      so a track that crosses the antimeridian centres correctly instead of
      averaging to the wrong side of the world. */
  globe.focus = function (low) {
    if (!low || !low.fixes || !low.fixes.length) return;
    var sum = [0, 0, 0];
    for (var i = 0; i < low.fixes.length; i++) {
      var v = toXYZ(low.fixes[i].lon, low.fixes[i].lat);
      sum[0] += v[0]; sum[1] += v[1]; sum[2] += v[2];
    }
    var len = Math.sqrt(dot3(sum, sum)) || 1;
    var center = fromXYZ([sum[0] / len, sum[1] / len, sum[2] / len]);

    view.lambda = center[0] * DEG;
    view.phi = clampPhi(center[1] * DEG);
    view.zoom = Math.max(view.zoom, 1.4);
    inertia = null;
    dirty = true;
    scheduleFrame();
  };

  globe.resize = function () {
    if (!canvas) return;
    cssW = canvas.clientWidth;
    cssH = canvas.clientHeight;
    if (!cssW || !cssH) return;             // hidden panel; next resize() will catch up
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    cx = cssW / 2;
    cy = cssH / 2;
    baseR = Math.min(cssW, cssH) / 2 * 0.92;
    dirty = true;
    scheduleFrame();
  };

  globe.setVisible = function (isVisible) {
    visible = !!isVisible;
    if (visible) {
      globe.resize();
      dirty = true;
      scheduleFrame();
    } else if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
  };

})(window.HF.globe = window.HF.globe || {}, window.HF);
