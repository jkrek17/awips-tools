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

  // Default view: both basins splayed symmetrically left/right rather than
  // one sitting near the horizon. Lambda is picked empirically from the
  // archive itself, not guessed: the circular mean fix longitude is -39.7
  // for the Atlantic and -179.5 (essentially the dateline) for the Pacific -
  // about 140 apart the short way round, over Canada and the Arctic (the
  // other way round, over Eurasia, is the wide ~220 gap and would
  // foreshorten both basins badly). Centring on the midpoint of the short
  // gap puts each basin about 70 of longitude off-axis, comfortably on the
  // near side rather than crowding the horizon.
  //
  // Phi used to be pulled up near the pole (68) so both belts curved away
  // from the centre symmetrically - technically tidy, but forecasters found
  // it "too polar": a straight-down view of the Arctic rather than a globe.
  // The circular mean fix *latitude* is ~54N (Atlantic) and ~48N (Pacific),
  // so 50 centres the view on the storm track belts themselves - both
  // basins still land at a comfortable ~45 of angular separation from the
  // view centre (well inside the visible hemisphere), but the vantage now
  // reads as "looking at the North Atlantic/Pacific" rather than "looking
  // down at the pole".
  var DEFAULT_LAMBDA_DEG = -110;
  var DEFAULT_PHI_DEG = 50;

  var MIN_ZOOM = 0.6, MAX_ZOOM = 6;
  var MAX_PHI = 89 * DEG;               // clamp shy of the exact pole

  var HIT_RADIUS = 9;                    // px, hover/click pick tolerance
  var CLICK_SLOP = 4;                    // px of movement still counted as a click
  var HOVER_THROTTLE_MS = 30;

  // Graticule spacing adapts to zoom (see graticuleStep()) rather than being
  // one fixed constant - 10 degrees is the standard-view default, coarser
  // when zoomed well out so 36 meridians don't turn into a cage, finer when
  // zoomed well in.
  var GRATICULE_SAMPLE_DEG = 3;          // sampling interval along each graticule line

  // Fix density grid: ported from the flat map's HF.maps.densityGrid (now
  // removed) rather than reimplemented - same cell size, same counting, so
  // the numbers don't change just because the rendering moved to a sphere.
  // 2 deg of latitude is ~120 nm; 5 deg of longitude is ~210 nm at 45N, so
  // cells are roughly square through the storm track belt.
  var CELL_LAT = 2;
  var CELL_LON = 5;
  // The flat map needed a per-view longitude frame so a single basin's cells
  // never split across the map's own seam. A sphere has no seam to avoid,
  // but the *binning* still shouldn't split a populated cell across +-180 -
  // Atlantic fixes never reach this origin (max observed +10) so they shift
  // uniformly with no effect on grouping, while Pacific fixes (which do
  // straddle the antimeridian) bin contiguously. One fixed origin, always
  // applied, replaces the old basin-dependent frame argument.
  var DENSITY_LON_ORIGIN = 20;

  /* ------------------------------------------------------------- state */

  var canvas = null, ctx = null, onSelect = null, readoutEl = null;
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

  var curLayer = 'tracks';               // 'tracks' | 'density' | 'genesis' | 'peak' | 'playback' | 'composite'

  // Ocean currents: a background context layer, independent of curLayer -
  // see the "ocean currents" block below for the rest of it. Off by default
  // (globe.setCurrentsVisible is only ever called with true by an explicit
  // user toggle in app.js).
  var showCurrents = false;
  var currentBins = null;                // built lazily from window.HF_CURRENTS, see buildCurrentSegments()
  var curGrid = null;                    // cached computeDensityGrid() result, layer 'density' only
  var hoveredCellKey = null;             // "latIdx:lonIdx", density layer only
  var densityRamp = null;                // --seq-1..7, resolved lazily and reset on theme change

  // Rotate/zoom transition (basin switches, "fit to events", double-click
  // reset) - a short tween layered onto the same dirty/scheduleFrame loop
  // drags and inertia already drive, rather than a second animation path.
  var transition = null;                 // {fromLambda, dl, fromPhi, toPhi, fromZoom, toZoom, t0, dur}

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* Playback state (see the "playback" section below) and the static-layer
     cache (see drawStaticLayers()). Kept together here, beside the other
     module state, rather than next to the code that uses them, so the whole
     of what survives between frames is readable in one place. */
  var PB_FADE_MS = 380;                  // Season step crossfade length
  var pbLayers = [];                     // [{frame, a0, t0, dir}] - one entry normally, two or more mid-crossfade
  var pbKind = 'clock';                  // 'clock' (heads + tails) | 'step' (whole-season tracks)
  var pbTail = 48;                       // hours, or Infinity; fixes the shape of the tail fade
  var animator = null;                   // fn(now) -> keep-going; the app's playback clock, driven from tick()
  var lastPointer = null;                // {px, py, clientX, clientY} while the cursor is over the canvas
  var lastTipHtml = '';                  // so a moving storm only re-writes the tooltip when its text changed
  var themeGen = 0;                      // bumped by applyTheme(); part of the static-layer cache key
  var pressCache = {};                   // pressure token -> resolved colour, cleared with the theme
  var bg = { canvas: null, ctx: null, key: '' };   // offscreen copy of ocean + graticule + land

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

  /** Inverse of project(): screen point (canvas-relative px) -> [lonDeg,
      latDeg], or null when the point falls outside the sphere's disc. Solved
      directly from project()'s own formulas (a pure rotation of the point's
      unit vector by view.phi about the "east" axis) rather than the generic
      Snyder inverse-orthographic equations, so it is guaranteed consistent
      with the forward projection above, sign conventions included. */
  function unproject(px, py) {
    var R = baseR * view.zoom;
    if (!R) return null;
    var X = (px - cx) / R;
    var Y = (cy - py) / R;
    var rho2 = X * X + Y * Y;
    if (rho2 > 1) return null;
    var c = Math.sqrt(Math.max(0, 1 - rho2));
    var cosPhiV = Math.cos(view.phi), sinPhiV = Math.sin(view.phi);
    var x0 = cosPhiV * c - sinPhiV * Y;
    var z0 = sinPhiV * c + cosPhiV * Y;
    var lat = Math.asin(Math.max(-1, Math.min(1, z0)));
    var dl = Math.atan2(X, x0);
    var lon = view.lambda + dl;
    return [normLonDeg(lon / DEG), lat / DEG];
  }

  /** view.lambda drifts arbitrarily far from [-180, 180) over a long drag
      session (nothing ever wraps it, since project()'s trig is 360-periodic
      and doesn't care) - so any lon *displayed* to a person, rather than fed
      back into project(), needs normalizing first. */
  function normLonDeg(deg) {
    var d = deg % 360;
    if (d < -180) d += 360;
    else if (d >= 180) d -= 360;
    return d;
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

  /** No app.css token exists for the currents layer's colour (out of scope
      here - see the file ownership note this was built against), so its
      fallback is picked directly rather than through a variable that would
      never resolve. It still needs to flip with the theme the way every
      other token on the page does, so this reads the one thing that
      reliably flips (--page, near-white in light mode / near-black in dark)
      and picks a light-vs-dark teal fallback accordingly - same effect as a
      real custom property, without inventing one in a file this task does
      not own. */
  function parseHex(s) {
    var m = /^#?([0-9a-f]{6})$/i.exec((s || '').trim());
    if (!m) return null;
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function isDarkTheme() {
    var rgb = parseHex(HF.cssVar('--page')) || [249, 249, 247];
    var lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
    return lum < 0.5;
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
    // The graticule used to read --grid, a token meant for hairline UI
    // borders - it sits within a couple percent of lightness of the ocean
    // fill in both themes, which is why it read as a ghost ("I can barely
    // see it"). --ink-muted/--ink-2 are text-contrast tokens instead, so the
    // grid now holds real contrast against the ocean disc in both palettes
    // while staying strictly neutral grey - never mistaken for the blue/
    // orange track or pressure-ramp colours drawn on top of it.
    pal = {
      ocean: readColor('--surface-sunk', '#f2f2ee'),
      oceanWash: readColor('--ink', '#0b0b0b'),
      land: readColor('--surface', '#fcfcfb'),
      coast: readColor('--ink-2', '#52514e'),
      grid: readColor('--ink-muted', '#898781'),
      gridMajor: readColor('--ink-2', '#52514e'),
      outline: readColor('--border-strong', '#c3c2b7'),
      // Ocean currents: a muted teal/blue-grey, deliberately off the
      // amber-through-magenta pressure ramp (--mslp-*) that owns the warm
      // end of the palette, and away from the brighter blue --seq-*/--atl
      // already mean "data" elsewhere on this map (fix density, Atlantic
      // basin colour) - this should read as quiet context, never as a
      // series of its own.
      current: readColor('--current', isDarkTheme() ? '#5fb6bf' : '#2c6c73'),
      // Colour for events with no analyzed centre, resolved once per theme
      // rather than once per storm per frame during playback.
      terrain: HF.classColor('tipjet')
    };
  }

  globe.applyTheme = function () {
    computePalette();
    themeGen++;                 // the cached ocean/land/graticule bitmap is the old theme's
    pressCache = {};
    densityRamp = null;         // --seq-* are themed too; resolved again on the next density draw
    compRamp = null;            // --div-* likewise
    dirty = true;
    scheduleFrame();
  };

  /* --------------------------------------------------------------- draw */

  function styleForCount(n) {
    // Thousands of overlapping tracks saturate into a solid blob, so strokes
    // thin out as the count grows and overplotting itself carries the sense
    // of density.
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

  /** 10 degrees is the standard-view default the user asked for, but 36
      meridians x 17 parallels at that spacing reads as a cage once zoomed
      well out - so this coarsens at low zoom and, since 10 degrees leaves
      room to spare once zoomed well in, tightens back up there too. Every
      step still keeps the same minor/major structure (see drawGraticule) so
      the grid reads consistently as zoom changes. */
  function graticuleStep() {
    if (view.zoom < 0.85) return { lon: 30, lat: 30 };
    if (view.zoom >= 2.5) return { lon: 5, lat: 5 };
    return { lon: 10, lat: 10 };
  }

  /** True for the equator and every meridian/parallel at a 30-degree
      multiple - the lines a forecaster actually orients off of. Drawn
      heavier and darker than the rest so the grid has structure (a coarse
      reference lattice plus finer in-between lines) instead of being
      uniformly busy at whatever step graticuleStep() picks. */
  function isMajorGratLine(deg) {
    var m = Math.round(deg) % 30;
    if (m < 0) m += 30;
    return m === 0;
  }

  /** The grid was reported "barely visible": --grid (a hairline-border
      token) sits within a couple percent lightness of the ocean fill in
      both themes. Fixed by reading text-contrast tokens instead (see
      computePalette) and by pushing width/alpha together rather than either
      alone - a wider, more opaque stroke reads as a firm line rather than a
      soft smudge at these thin canvas widths. Minor (10 deg) lines carry
      the base contrast; major lines (equator, 30 deg multiples) go a step
      further on both axes so the grid has a coarse structure to read at a
      glance, with land drawn on top afterward so none of this ever
      competes with the track/pressure colours drawn later still. */
  function drawGraticule() {
    var step = graticuleStep();
    var minor = [], major = [];
    var lon;
    for (lon = -180; lon < 180; lon += step.lon) {
      var meridian = [];
      for (var lat = -90; lat <= 90; lat += GRATICULE_SAMPLE_DEG) meridian.push([lon, lat]);
      (isMajorGratLine(lon) ? major : minor).push(meridian);
    }
    for (var lat0 = -90 + step.lat; lat0 < 90; lat0 += step.lat) {
      var parallel = [];
      for (lon = -180; lon <= 180; lon += GRATICULE_SAMPLE_DEG) parallel.push([lon, lat0]);
      (isMajorGratLine(lat0) ? major : minor).push(parallel);
    }
    var i;
    ctx.globalAlpha = 0.62;
    for (i = 0; i < minor.length; i++) strokePath(visibleSegments(minor[i]), 0.8, pal.grid);
    ctx.globalAlpha = 0.88;
    for (i = 0; i < major.length; i++) strokePath(visibleSegments(major[i]), 1.2, pal.gridMajor);
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
    var selected = null, hovered = null;

    ctx.lineCap = 'round';    // smooths the join between adjacent-colour segments
    for (var i = 0; i < lows.length; i++) {
      var low = lows[i];
      var isSel = low.key === selectedKey;
      var isHov = hoveredKey != null && low.key === hoveredKey;
      if (isSel) selected = low;
      if (isHov) hovered = low;
      if (isSel || isHov) continue;
      drawOneTrack(low, style, false, false);
    }
    // Selected is drawn before hovered so hover - a transient, pointer-driven
    // emphasis - always ends up the topmost stroke; when the two coincide,
    // one combined-emphasis pass is enough.
    if (selected && selected !== hovered) drawOneTrack(selected, style, true, false);
    if (hovered) drawOneTrack(hovered, style, hovered === selected, true);
    ctx.lineCap = 'butt';
  }

  function drawOneTrack(low, style, isSelected, isHovered) {
    var fixes = low.fixes;
    var terrain = low.cls && low.cls !== 'low';
    var emphasized = isSelected || isHovered;
    var weight = isSelected ? Math.max(2.4, style.weight + 1.6)
      : isHovered ? Math.max(2.2, style.weight + 1.4)
      : (terrain ? style.weight + 0.3 : style.weight);
    var opacity = emphasized ? 1 : Math.min(1, style.opacity + (terrain ? 0.15 : 0));
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

  /* ---------------------------------------------------------- point layers
     "First fix" and "peak intensity" both plot one point per low, culled at
     the horizon like everything else, sized/coloured exactly as the flat
     map drew them and sharing the same hover/click machinery as tracks (via
     hitPoints + hoveredKey) rather than a second interaction path. */

  function radiusForPressure(hpa) {
    if (hpa == null) return 3;
    var t = Math.max(0, Math.min(1, (1000 - hpa) / 70));
    return 3 + t * 6;
  }

  function drawPoints(kind) {
    hitPoints = [];
    var selected = null, hovered = null;
    for (var i = 0; i < lows.length; i++) {
      var low = lows[i];
      var isSel = low.key === selectedKey;
      var isHov = hoveredKey != null && low.key === hoveredKey;
      if (isSel) selected = low;
      if (isHov) hovered = low;
      if (isSel || isHov) continue;
      drawOnePoint(low, kind, false, false);
    }
    if (selected && selected !== hovered) drawOnePoint(selected, kind, true, false);
    if (hovered) drawOnePoint(hovered, kind, hovered === selected, true);
  }

  function drawOnePoint(low, kind, isSelected, isHovered) {
    var lat = kind === 'peak' ? low.minPLat : low.lat0;
    var lon = kind === 'peak' ? low.minPLon : low.lon0;
    if (lat == null || lon == null) return;
    var p = project(lon, lat);
    if (!p.visible) return;

    var color = kind === 'peak'
      ? (low.cls !== 'low' ? HF.classColor(low.cls) : HF.pressureColor(low.minP))
      : HF.basinColor(low.basin);
    var baseRad = kind === 'peak' ? radiusForPressure(low.minP) : 4;
    var emphasized = isSelected || isHovered;
    var r = emphasized ? baseRad + 2.5 : baseRad;

    ctx.globalAlpha = emphasized ? 1 : 0.82;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    if (emphasized) {
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = pal.oceanWash;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    hitPoints.push({ x: p.x, y: p.y, low: low });
  }

  /* ------------------------------------------------------------ playback
     One frame of HF.playback (playback.js) drawn as storms: a head marker
     plus a tail that fades with age. The engine is pure data and does all
     the time arithmetic - which storms are alive at t, where they are,
     how far behind the head each tail point sits (`age`, in hours) - so
     nothing here ever looks at a clock; colour, width and fade are this
     file's call, as the engine's header says.

     Two kinds of frame:
       'clock'  composite and season replay: head + tail per storm.
       'step'   Season step: each storm's COMPLETE track, no head. A small
                marker at the event's lowest pressure carries intensity,
                since a whole track has no "now" to hang a head on.

     Everything reuses what the other layers already do: pressure colour
     per edge off the same --mslp-* ramp, dashed terrain-class strokes,
     radiusForPressure() for marker size, strokeEdge()'s horizon clipping,
     hitPoints/hoveredKey/selectedKey for hover and click. */

  /** Resolve a pressure colour once per ramp step per theme instead of
      once per tail edge per frame. HF.pressureColor does the lookup (a
      getComputedStyle read); this only remembers it. */
  function pressureColorCached(hpa) {
    var tok = HF.pressureToken(hpa);
    var c = pressCache[tok];
    if (c === undefined) c = pressCache[tok] = HF.pressureColor(hpa);
    return c;
  }

  /** 1 at the head, falling to 0 at the far end of the tail. A finite tail
      fades linearly over exactly its own length, so a 24 h tail and a 96 h
      tail both taper to nothing at their ends. The accumulating "track so
      far" tail has no end to fade towards, so it decays exponentially
      instead (72 h e-folding, about a typical event's whole life) and
      tailAlpha() gives it a high floor: the point of that view is to read
      the whole path, so its oldest part must stay visible. */
  function tailFraction(age) {
    if (isFinite(pbTail) && pbTail > 0) {
      var f = 1 - age / pbTail;
      return f < 0 ? 0 : f;
    }
    return Math.exp(-age / 72);
  }

  function tailAlpha(f) {
    return isFinite(pbTail) ? 0.05 + 0.95 * f : 0.4 + 0.6 * f;
  }

  /** Move the crossfade along: once the newest frame is fully in, the
      older ones are dropped and the layer stack collapses back to one. */
  function layerAlpha(l, now) {
    if (!l.dir) return l.a0;
    var a = l.a0 + l.dir * (now - l.t0) / PB_FADE_MS;
    return a < 0 ? 0 : a > 1 ? 1 : a;
  }

  function stepFade(now) {
    var n = pbLayers.length;
    if (!n || (n === 1 && !pbLayers[0].dir)) return;
    var newest = pbLayers[n - 1];
    if (layerAlpha(newest, now) >= 1) {
      newest.a0 = 1; newest.dir = 0;
      pbLayers = [newest];
      return;
    }
    var keep = [];
    for (var i = 0; i < n; i++) {
      if (i === n - 1 || layerAlpha(pbLayers[i], now) > 0) keep.push(pbLayers[i]);
    }
    pbLayers = keep;
  }

  /** Flatten the layer stack into one entry per storm key: [{storm, alpha}].
      This is the crossfade's "dissolve by matching storms": a storm present
      in both the outgoing and incoming frame is drawn once at the larger of
      its two alphas - so it stays solid instead of dipping to ~75% mid-fade
      the way two stacked half-transparent copies would - while a storm in
      only one frame fades out or in. The newest frame's geometry wins. */
  function pbDrawList(now) {
    var byKey = {}, list = [];
    for (var li = 0; li < pbLayers.length; li++) {
      var l = pbLayers[li], a = layerAlpha(l, now);
      if (a <= 0) continue;
      var storms = l.frame.storms;
      for (var i = 0; i < storms.length; i++) {
        var s = storms[i], e = byKey[s.key];
        if (!e) { e = byKey[s.key] = { storm: s, alpha: a }; list.push(e); }
        else { e.storm = s; if (a > e.alpha) e.alpha = a; }
      }
    }
    return list;
  }

  function isTerrain(s) { return !!s.cls && s.cls !== 'low'; }

  /** One storm's tail (clock) or whole track (step), edge by edge. Clock
      tails are cut into short pieces whose alpha and width follow `age`, so
      the fade is a smooth taper along the line rather than one flat value
      per 6-hour edge (a 24 h tail is only four edges). Dashed terrain
      strokes and horizon-clipped edges are drawn whole, at their mid-age:
      cutting a dashed line into pieces restarts the dash pattern in each,
      and a clipped edge's age at the cut is not known. */
  function drawStormLine(e, step, style, isSel, isHov) {
    var s = e.storm, tail = s.tail, n = tail.length;
    if (n < 2) return;
    var terrain = isTerrain(s);
    var emph = isSel || isHov;
    ctx.setLineDash(terrain ? [4, 3] : []);

    for (var i = 0; i < n - 1; i++) {
      var a = tail[i], b = tail[i + 1];           // oldest -> newest
      var pa = project(a.lon, a.lat), pb = project(b.lon, b.lat);
      if (!pa.visible && !pb.visible) continue;
      var p0 = pa, p1 = pb, whole = true;
      if (pa.visible !== pb.visible) {
        var cross = horizonCrossing([a.lon, a.lat], [b.lon, b.lat]);
        var pc = project(cross[0], cross[1]);
        if (pa.visible) p1 = pc; else p0 = pc;
        whole = false;
      }
      ctx.strokeStyle = terrain ? pal.terrain : pressureColorCached(segmentPressure(a, b));

      var dx = p1.x - p0.x, dy = p1.y - p0.y;
      var pieces = 1;
      if (!step && !terrain && whole) {
        pieces = Math.max(1, Math.min(6, Math.ceil(Math.sqrt(dx * dx + dy * dy) / 5)));
      }
      for (var k = 0; k < pieces; k++) {
        var u0 = k / pieces, u1 = (k + 1) / pieces;
        var alpha, width;
        if (step) {
          alpha = Math.max(style.opacity, 0.6);
          width = style.weight + (terrain ? 0.6 : 0.3);
        } else {
          var f = tailFraction(a.age + (b.age - a.age) * (u0 + u1) / 2);
          alpha = tailAlpha(f);
          width = 1.1 + 2.3 * f + (terrain ? 0.3 : 0);
        }
        if (emph) {
          alpha = step ? 1 : Math.min(1, alpha + 0.35);
          width += isHov ? 1.2 : 1;
        }
        ctx.globalAlpha = alpha * e.alpha;
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.moveTo(p0.x + dx * u0, p0.y + dy * u0);
        ctx.lineTo(p0.x + dx * u1, p0.y + dy * u1);
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  /** The storm's marker, plus its hit points.

      Shape and size carry the information that colour also carries, so
      nothing depends on telling two hues apart: pressure is the disc's
      SIZE (radiusForPressure, as the peak-intensity layer does) as well as
      its colour, and an event with no analyzed centre is a DIAMOND of fixed
      size where a low is a circle. A clock head also gets a thin outer ring
      so it reads as a storm with extent, not a dot; a step marker is
      smaller and has none, since up to ~100 of them share one globe. */
  function drawStormMark(e, step, isSel, isHov) {
    var s = e.storm, tail = s.tail, low = s.low, i, tp, pt;
    var terrain = isTerrain(s);
    var emph = isSel || isHov;

    // Hit points first, from every visible tail vertex (the head is the last
    // one), so hover works on the line as well as the marker - but only for
    // a storm that is mostly faded in, or a dissolving storm stays hoverable.
    if (e.alpha >= 0.5) {
      for (i = 0; i < tail.length; i++) {
        tp = project(tail[i].lon, tail[i].lat);
        if (tp.visible) hitPoints.push({ x: tp.x, y: tp.y, low: low, storm: s });
      }
    }

    var lat, lon;
    if (step) {
      if (low.minPLat != null && low.minPLon != null) { lat = low.minPLat; lon = low.minPLon; }
      else { pt = tail[(tail.length - 1) >> 1]; lat = pt.lat; lon = pt.lon; }
    } else {
      lat = s.lat; lon = s.lon;
    }
    if (lat == null || lon == null) return;
    var p = project(lon, lat);
    if (!p.visible) return;
    if (step && e.alpha >= 0.5) hitPoints.push({ x: p.x, y: p.y, low: low, storm: s });

    var base = terrain ? 5 : radiusForPressure(s.pres);
    if (step) base = terrain ? 4 : Math.max(2.5, base * 0.75);
    var r = emph ? base + 2.5 : base;
    var color = terrain ? pal.terrain : pressureColorCached(s.pres);

    ctx.globalAlpha = e.alpha * (step && !emph ? 0.85 : 1);
    ctx.fillStyle = color;
    ctx.strokeStyle = pal.oceanWash;
    ctx.lineWidth = emph ? 2 : 1.2;
    ctx.beginPath();
    if (terrain) {
      var d = r * 1.3;
      ctx.moveTo(p.x, p.y - d); ctx.lineTo(p.x + d, p.y);
      ctx.lineTo(p.x, p.y + d); ctx.lineTo(p.x - d, p.y);
      ctx.closePath();
    } else {
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.stroke();
    if (!terrain && !step) {
      ctx.globalAlpha = e.alpha * 0.55;
      ctx.lineWidth = 1;
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 3.5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  function drawPlayback() {
    hitPoints = [];
    if (!pbLayers.length) return;
    var list = pbDrawList(performance.now());
    var step = pbKind === 'step';
    var style = styleForCount(list.length);
    var selected = null, hovered = null, i, e;

    // Selected, then hovered, are drawn last (hover is the transient pointer
    // emphasis and must end up on top), exactly as drawTracks() orders them.
    // Lines for every storm go down before any marker, so a head is never
    // buried under another storm's tail.
    var normal = [];
    for (i = 0; i < list.length; i++) {
      e = list[i];
      var isSel = e.storm.key === selectedKey;
      var isHov = hoveredKey != null && e.storm.key === hoveredKey;
      if (isSel) selected = e;
      if (isHov) hovered = e;
      if (!isSel && !isHov) normal.push(e);
    }
    ctx.lineCap = 'round';
    for (i = 0; i < normal.length; i++) drawStormLine(normal[i], step, style, false, false);
    if (selected && selected !== hovered) drawStormLine(selected, step, style, true, false);
    if (hovered) drawStormLine(hovered, step, style, hovered === selected, true);
    ctx.lineCap = 'butt';

    for (i = 0; i < normal.length; i++) drawStormMark(normal[i], step, false, false);
    if (selected && selected !== hovered) drawStormMark(selected, step, true, false);
    if (hovered) drawStormMark(hovered, step, hovered === selected, true);
  }

  /** The storms move under a stationary cursor, so the hover result from
      the last mousemove goes stale: the hovered storm can end, or another
      can drift under the pointer. Re-test against the freshly built hit
      points after every playback draw (a few hundred distance checks). */
  function afterPlaybackDraw() {
    if (dragging || !lastPointer) return;
    updateHover(nearestHit(lastPointer.px, lastPointer.py), lastPointer);
  }

  /* -------------------------------------------------------------- density
     Gridded hurricane-force fix counts. Binning is ported unchanged from
     the flat map's HF.maps.densityGrid (see DENSITY_LON_ORIGIN above for why
     the per-view longitude frame argument it took is gone); each populated
     cell is drawn as a lat/lon quad, projected and horizon-clipped exactly
     like a coastline ring. */

  function densityLon(lon) { return lon < DENSITY_LON_ORIGIN ? lon + 360 : lon; }

  /** Count fixes per grid cell. Returns {cells:[...], byKey:{...}, max, seasons} */
  function computeDensityGrid(lowsArg) {
    var cells = {};
    var seasons = {};
    lowsArg.forEach(function (low) {
      seasons[low.season] = true;
      low.fixes.forEach(function (fix) {
        var latIdx = Math.floor(fix.lat / CELL_LAT);
        var lonIdx = Math.floor(densityLon(fix.lon) / CELL_LON);
        var key = latIdx + ':' + lonIdx;
        if (!cells[key]) {
          cells[key] = { key: key, latIdx: latIdx, lonIdx: lonIdx, count: 0, hf: 0, events: {} };
        }
        cells[key].count++;
        if (fix.cat === 'HF') cells[key].hf++;
        cells[key].events[low.key] = true;
      });
    });
    var list = Object.keys(cells).map(function (k) { return cells[k]; });
    var max = 0;
    list.forEach(function (c) {
      c.events = Object.keys(c.events).length;
      if (c.hf > max) max = c.hf;
    });
    return { cells: list, byKey: cells, max: max, seasons: Object.keys(seasons).length };
  }

  function densityRampColors() {
    if (!densityRamp) {
      densityRamp = ['--seq-1', '--seq-2', '--seq-3', '--seq-4', '--seq-5', '--seq-6', '--seq-7']
        .map(function (v) { return HF.cssVar(v); });
    }
    return densityRamp;
  }

  function fmtLonBand(lon0) {
    function one(v) {
      var x = v > 180 ? v - 360 : v;
      return Math.abs(x) + '°' + (x < 0 ? 'W' : 'E');
    }
    return one(lon0) + '–' + one(lon0 + CELL_LON);
  }

  function densityTip(cell) {
    var lat0 = cell.latIdx * CELL_LAT, lon0 = cell.lonIdx * CELL_LON;
    var perSeason = curGrid.seasons ? cell.hf / curGrid.seasons : cell.hf;
    return '<b>' + Math.abs(lat0) + '–' + Math.abs(lat0 + CELL_LAT) + '°N, ' +
      fmtLonBand(lon0) + '</b>' +
      '<div class="t-row">' + cell.hf + ' hurricane force fixes</div>' +
      '<div class="t-row">' + perSeason.toFixed(1) + ' per season &middot; ' +
      cell.events + ' event' + (cell.events === 1 ? '' : 's') + '</div>';
  }

  /** One cell's quad in the grid's shifted-frame degrees, projected exactly
      like a coastline ring - trig is 360-periodic, so passing e.g. 190
      instead of -170 projects identically and needs no unwinding. */
  function cellRing(cell) {
    var lon0 = cell.lonIdx * CELL_LON, lat0 = cell.latIdx * CELL_LAT;
    return [[lon0, lat0], [lon0 + CELL_LON, lat0], [lon0 + CELL_LON, lat0 + CELL_LAT],
      [lon0, lat0 + CELL_LAT], [lon0, lat0]];
  }

  function drawOneCell(cell, ramp, hovered) {
    var segs = visibleSegments(cellRing(cell));
    if (!segs.length) return;
    var frac = cell.hf / curGrid.max;
    // Perceptual step: counts are heavily skewed, so rank on a square root.
    var step = Math.min(ramp.length - 1, Math.floor(Math.sqrt(frac) * ramp.length));
    var R = baseR * view.zoom;

    ctx.globalAlpha = hovered ? Math.min(1, 0.16 + 0.62 * Math.sqrt(frac) + 0.2) : 0.16 + 0.62 * Math.sqrt(frac);
    ctx.fillStyle = ramp[step];
    fillClippedRing(segs, R);
    if (hovered) {
      ctx.globalAlpha = 1;
      strokePath(segs, 1.25, pal.oceanWash);
    }
    ctx.globalAlpha = 1;
  }

  function drawDensity() {
    hitPoints = [];
    if (!curGrid || !curGrid.max) return;
    var ramp = densityRampColors();
    var cells = curGrid.cells.filter(function (c) { return c.hf > 0; });
    var hoveredCell = null;
    for (var i = 0; i < cells.length; i++) {
      var c = cells[i];
      if (hoveredCellKey && c.key === hoveredCellKey) { hoveredCell = c; continue; }
      drawOneCell(c, ramp, false);
    }
    if (hoveredCell) drawOneCell(hoveredCell, ramp, true);
  }

  /* ----------------------------------------------------------- composite
     "Did the storm track move, and can that be told from noise?" - the
     HF.composite.compare() result drawn as a diverging map. The statistics
     live in composite.js; this section only decides how much of that answer
     a picture is allowed to say, and says it no louder.

     Four encodings, each on its own channel so none has to stand in for
     another (and none rests on colour alone - Section 508):

       FILL COLOUR  how big the difference is, and which way (more / fewer
                    storms than the baseline). Diverging scale, symmetric
                    about zero, neutral grey at zero.
       STIPPLE      FDR significance (sigFDR) and nothing else. Dots, not a
                    colour change, so "big" and "believable" cannot be
                    confused: a deep-blue cell with no dots is a big
                    difference that the test cannot tell from chance, which
                    is the usual outcome with 8-9 seasons.
       NO FILL,     the cell was visited but the full archive has too few
       HATCH AND    fixes in it to test (r.cells[i].tested === false). A cell
       DOTTED RING  with 3 fixes must not look like a cell with 300 fixes
                    whose subset happened to match - the second is
                    information ("no difference found, and we could have
                    found one"), the first is its absence. This is the
                    distinction that matters most on the usual map, where
                    almost nothing is stippled, so it gets three separate
                    cues rather than one: no colour fill (the strongest
                    contrast the canvas has - the neutral class IS a fill),
                    a 45-degree line hatch (the conventional "no data"
                    texture, and a different texture from the stipple), and
                    a dotted outline (the only thing visible where the
                    hatch is cut by the horizon or by a very small cell).
       HOVER        every number behind the cell (see compositeTip()).

     Per-cell significance without FDR correction (sigCell) is NEVER drawn.
     With ~150 tested cells about 5% of them carry it on pure noise, and a
     map stippled by it reliably shows "patterns" in random data. It appears
     only as a muted, separately labelled "uncorrected p" line in the hover.

     What is refused. compare() can return status 'insufficient' / 'empty' /
     'invalid' or reliability 'none'; every one of those means the cells are
     not a finding, and a map drawn from them would look exactly as
     authoritative as a good one. They draw nothing (a one-line caption says
     why) and compositeState() reports the reason so the tab can explain at
     length. reliability 'low' (few defining seasons) draws, but washed out
     under a "PROVISIONAL" caption, because absence of stippling is weak
     evidence there and the map should not read as confident.

     Colour. Diverging blue <-> vermilion with a neutral grey midpoint (the
     dataviz skill's diverging method: two hues that read as opposite plus a
     grey that reads as "nothing", equal steps per arm). Blue is "more storms
     than the baseline", the same direction blue already means on the Fix
     density layer (more = deeper blue); vermilion is "fewer". Blue/orange is
     the pair that survives protan and deutan best. The arms are matched in
     OKLCH lightness step for step, so a blue and an orange of the same
     magnitude are equally dark and the sign is readable in greyscale as
     well as hue. Four steps an arm (nine classes with the neutral one): few
     enough that the legend can name every class, and the exact value is in
     the hover anyway. Values live in app.css as --div-pos-1..4,
     --div-neg-1..4 and --div-mid (themed like --mslp-*); the DIV_FALLBACK
     tables below are the same validated hexes, used only until those tokens
     exist, so the layer works either way. */

  var COMP_STEPS = 4;                    // colour classes per arm; class 0 is the neutral one
  var COMP_THIN = 5;                     // subset counts below this get a "thin" warning in the hover
  var COMP_PROVISIONAL_ALPHA = 0.62;     // fill opacity when reliability is 'low'
  var COMP_DOT_SPACING = 8;              // px between stipple dots at any zoom
  var COMP_HATCH_SPACING = 5;            // px between hatch lines on untested cells
  var COMP_RING_STEP = 2;                // degrees of longitude per segment when walking a cell's parallels

  // Validated in the dataviz method (diverging: monotone lightness, arms
  // matched in OKLCH L, every step >= 9 deltaE from its neighbour under
  // protan/deutan/normal, neighbouring-step contrast against each theme's
  // surface). Arms run weakest -> strongest. Light steps get darker with
  // magnitude, dark steps get lighter, as --seq-* and --mslp-* do.
  var DIV_FALLBACK = {
    light: {
      pos: ['#b7d3f6', '#6da7ec', '#2a78d6', '#184f95'],
      neg: ['#f4c4b3', '#e38869', '#c44f21', '#882f08'],
      mid: '#f0efec'
    },
    dark: {
      pos: ['#1c5cab', '#3987e5', '#86b6ef', '#b7d3f6'],
      neg: ['#983e1b', '#d45e32', '#ee9a7c', '#ffbfa9'],
      mid: '#383835'
    }
  };

  var comp = null;                       // null, or {result, state, reason, cells, byId, grid, max, ...}
  var compField = 'rate';                // 'rate' | 'shape'
  var compScaleMax = null;               // caller's fixed scale, or null for "fit to the data"
  var compRamp = null;                   // resolved colours, reset with the theme
  var hoveredCompId = null;              // cell id under the cursor, composite layer only

  function compColors() {
    if (compRamp) return compRamp;
    var fb = DIV_FALLBACK[isDarkTheme() ? 'dark' : 'light'];
    var pos = [], neg = [];
    for (var i = 0; i < COMP_STEPS; i++) {
      pos.push(readColor('--div-pos-' + (i + 1), fb.pos[i]));
      neg.push(readColor('--div-neg-' + (i + 1), fb.neg[i]));
    }
    compRamp = {
      pos: pos, neg: neg,
      mid: readColor('--div-mid', fb.mid),
      surface: readColor('--surface', '#fcfcfb'),
      ink: readColor('--ink', '#0b0b0b'),
      inkMuted: readColor('--ink-muted', '#898781'),
      ink2: readColor('--ink-2', '#52514e'),
      border: readColor('--border-strong', '#c3c2b7')
    };
    return compRamp;
  }

  /** Round a magnitude UP to a 1-1.5-2-2.5-3-4-5-6-8-10 number, so the scale
      ends on a value a person can say out loud. Rounding up (never down)
      keeps the extreme cell inside the top class. */
  function niceCeil(x) {
    if (!(x > 0) || !isFinite(x)) return 1;
    var e = Math.pow(10, Math.floor(Math.log(x) / Math.LN10));
    var f = x / e, nice = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < nice.length; i++) if (f <= nice[i] * (1 + 1e-9)) return nice[i] * e;
    return 10 * e;
  }

  /** Signed class -COMP_STEPS..+COMP_STEPS for a difference on a scale that
      runs -max..+max. 2*COMP_STEPS+1 equal-width classes, the middle one
      centred on zero, so +d and -d always land in mirror-image classes. */
  function compClass(diff, max) {
    var w = 2 * max / (2 * COMP_STEPS + 1), a = Math.abs(diff);
    if (a < w / 2) return 0;
    var k = Math.min(COMP_STEPS, Math.ceil((a - w / 2) / w - 1e-9));
    return diff < 0 ? -k : k;
  }

  function compColorFor(cls, ramp) {
    if (cls === 0) return ramp.mid;
    return cls > 0 ? ramp.pos[cls - 1] : ramp.neg[-cls - 1];
  }

  /** A cell's outline as [lon, lat] points. The two parallels are walked in
      <= 2 degree steps so they follow the curve of the latitude circle
      instead of cutting a chord: neighbouring bands have different numbers
      of cells, so their corners do not line up along the shared parallel,
      and two different chords would leave slivers of bare globe or double
      cover between them once zoomed in. The meridian edges are great
      circles already and need no help. Longitudes run past 180 for a cell
      that crosses the dateline; the trig is 360-periodic. */
  function compRing(c) {
    var n = Math.max(1, Math.ceil(c.dlon / COMP_RING_STEP)), i, pts = [];
    for (i = 0; i <= n; i++) pts.push([c.lon0 + c.dlon * i / n, c.lat0]);
    pts.push([c.lon0 + c.dlon, (c.lat0 + c.lat1) / 2]);
    for (i = n; i >= 0; i--) pts.push([c.lon0 + c.dlon * i / n, c.lat1]);
    pts.push([c.lon0, (c.lat0 + c.lat1) / 2]);
    pts.push([c.lon0, c.lat0]);
    return pts;
  }

  function compFieldOf(cell, field) { return cell[field] || null; }

  /** (Re)derive everything that depends on the field choice or the scale:
      which cells are drawable, the symmetric scale limit, the counts the
      state report quotes. Cheap (a few hundred cells). */
  function compRefresh() {
    if (!comp || !comp.drawable) return;
    var max = 0, nTested = 0, nUntested = 0, nFDR = 0, i;
    for (i = 0; i < comp.cells.length; i++) {
      var w = comp.cells[i], f = compFieldOf(w.cell, compField);
      w.drawn = !!(w.cell.tested && f && typeof f.diff === 'number' && isFinite(f.diff));
      if (w.drawn) {
        nTested++;
        if (f.sigFDR) nFDR++;
        if (Math.abs(f.diff) > max) max = Math.abs(f.diff);
      } else if (!w.cell.tested) {
        nUntested++;
      }
    }
    comp.fieldMax = max;
    comp.max = compScaleMax > 0 ? compScaleMax : niceCeil(max || 0.1);
    comp.nTested = nTested;
    comp.nUntested = nUntested;
    comp.nSigFDR = nFDR;
  }

  function compUnitLabel() {
    var u = comp && comp.result.options && comp.result.options.unit;
    return u === 'events' ? 'storm visits per season' : 'fixes per season';
  }

  function compSetResult(result) {
    comp = null;
    hoveredCompId = null;
    HF.hideTip();
    if (!result) { dirty = true; scheduleFrame(); return; }

    var refuse = null;
    if (result.status !== 'ok') {
      refuse = result.reason || ('The comparison returned status "' + result.status + '".');
    } else if (result.reliability === 'none') {
      refuse = result.reason || 'The comparison is not reliable enough to draw.';
    } else if (result.inference === false) {
      refuse = 'No test was run (no cell had enough fixes), so there is nothing to show.';
    }
    comp = {
      result: result,
      drawable: !refuse,
      refusal: refuse,
      provisional: !refuse && result.reliability === 'low',
      cells: [], byId: {}, grid: null
    };
    if (!refuse) {
      var g = result.grid || {};
      comp.grid = HF.composite.grid(g.latStep, g.lonOrigin);
      var cells = result.cells || [];
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        var w = { id: c.id, cell: c, ring: compRing(c), drawn: false };
        comp.cells.push(w);
        comp.byId[c.id] = w;
      }
      compRefresh();
      if (!comp.nTested) {
        // Nothing testable: a map of zero coloured cells would read as
        // "no difference anywhere", the opposite of "nothing was tested".
        comp.drawable = false;
        comp.refusal = 'No cell has enough fixes in the full archive to be tested.';
      }
    }
    dirty = true;
    scheduleFrame();
  }

  /** What the tab needs to explain the map. Plain data, safe to call any time. */
  function compState() {
    var r = comp && comp.result;
    var s = {
      state: !comp ? 'none' : !comp.drawable ? 'refused' : comp.provisional ? 'provisional' : 'ok',
      drawn: !!(comp && comp.drawable),
      reason: !comp ? null : comp.refusal,
      status: r ? r.status : null,
      reliability: r ? r.reliability : null,
      warnings: r && r.warnings ? r.warnings.slice() : [],
      field: compField,
      unit: comp && comp.drawable ? compUnitLabel() : null,
      scaleMax: comp && comp.drawable ? comp.max : null,
      fieldMax: comp && comp.drawable ? comp.fieldMax : null,
      nTested: comp && comp.drawable ? comp.nTested : 0,
      nUntested: comp && comp.drawable ? comp.nUntested : 0,
      nSigFDR: comp && comp.drawable ? comp.nSigFDR : 0,
      expectedByChance: null,
      n: r ? r.n : null
    };
    if (comp && comp.drawable && r.summary && r.summary[compField]) {
      s.summary = r.summary[compField];
      s.expectedByChance = r.summary[compField].expectedByChance;
    }
    return s;
  }

  /** The legend as data, with colours resolved for the current theme, so the
      tab can paint swatches that are guaranteed to match the canvas (it is
      the same table the canvas reads). bins run most negative -> most
      positive; neutral is the middle one. */
  function compLegend() {
    if (!comp || !comp.drawable) return null;
    var ramp = compColors(), M = comp.max, w = 2 * M / (2 * COMP_STEPS + 1), bins = [];
    for (var cls = -COMP_STEPS; cls <= COMP_STEPS; cls++) {
      var lo, hi;
      if (cls === 0) { lo = -w / 2; hi = w / 2; }
      else if (cls > 0) { lo = w / 2 + (cls - 1) * w; hi = cls === COMP_STEPS ? M : lo + w; }
      else { hi = -(w / 2 + (-cls - 1) * w); lo = cls === -COMP_STEPS ? -M : hi - w; }
      bins.push({ cls: cls, lo: lo, hi: hi, color: compColorFor(cls, ramp),
                  meaning: cls === 0 ? 'about the same' : cls > 0 ? 'more than baseline' : 'fewer than baseline' });
    }
    return {
      field: compField, unit: compUnitLabel(), max: M, bins: bins,
      alpha: comp.provisional ? COMP_PROVISIONAL_ALPHA : 1,
      positive: 'more than baseline', negative: 'fewer than baseline',
      stipple: 'FDR-significant (q <= ' + (comp.result.options && comp.result.options.alphaFDR != null
        ? comp.result.options.alphaFDR : 0.1) + ')',
      untested: 'too few fixes in the full archive to test (hatched, dotted outline, no fill)',
      neutralColor: ramp.mid
    };
  }

  /* ---- drawing ---- */

  /** Cosine of the angular distance from the view centre: 1 at the middle of
      the disc, 0 on the limb. Stipple skips the last sliver before the limb,
      where dots would pile up into a smear. */
  function facing(lon, lat) {
    return dot3(toXYZ(lon, lat), viewVector());
  }

  function drawStipple(w, ramp) {
    var c = w.cell, R = baseR * view.zoom;
    var latPx = R * (c.lat1 - c.lat0) * DEG;
    var lonPx = R * c.dlon * DEG * Math.max(0.15, Math.cos(c.latC * DEG));
    // At least a 3 x 3 lattice so a small cell still reads as stippled, and
    // never so many dots that they merge into hatching and bury the fill
    // colour (the magnitude) of the cell they are meant to annotate.
    var rows = Math.max(3, Math.min(14, Math.round(latPx / COMP_DOT_SPACING)));
    var cols = Math.max(3, Math.min(24, Math.round(lonPx / COMP_DOT_SPACING)));
    var r = Math.min(1.6, 1.05 + 0.08 * view.zoom);
    var pts = [], i, j;
    for (i = 0; i < rows; i++) {
      // Offset alternate rows by half a column: a hex lattice reads as a
      // texture, a square one as a grid of dots (a second graticule).
      var lat = c.lat0 + (i + 0.5) * (c.lat1 - c.lat0) / rows;
      for (j = 0; j < cols; j++) {
        var lon = c.lon0 + (j + 0.25 + (i % 2) * 0.5) * c.dlon / cols;
        var p = project(lon, lat);
        if (p.visible && facing(lon, lat) > 0.12) pts.push(p);
      }
    }
    if (!pts.length) return;
    // Surface-coloured halo first, ink dot on top: the dot is legible on the
    // palest and the darkest class alike, so one stipple style serves the
    // whole scale and never has to be re-coloured per fill.
    ctx.fillStyle = ramp.surface;
    ctx.beginPath();
    for (i = 0; i < pts.length; i++) { ctx.moveTo(pts[i].x + r + 0.7, pts[i].y); ctx.arc(pts[i].x, pts[i].y, r + 0.7, 0, Math.PI * 2); }
    ctx.fill();
    ctx.fillStyle = ramp.ink;
    ctx.beginPath();
    for (i = 0; i < pts.length; i++) { ctx.moveTo(pts[i].x + r, pts[i].y); ctx.arc(pts[i].x, pts[i].y, r, 0, Math.PI * 2); }
    ctx.fill();
  }

  /** Coastlines again, on top of the fills. The cells are opaque (a diverging
      scale only means what its legend says if the fill is the colour on the
      legend - a translucent fill over ocean and land would be two different
      colours for one class), so they would otherwise hide the land under
      them. Thin and half-strength: orientation, not decoration. */
  function drawCoastOverlay(ramp) {
    var coast = window.HF_COAST;
    if (!coast || !coast.polygons) return;
    ctx.globalAlpha = 0.55;
    for (var i = 0; i < coast.polygons.length; i++) {
      strokePath(visibleSegments(coast.polygons[i]), 0.8, ramp.ink2);
    }
    ctx.globalAlpha = 1;
  }

  /** One short caption, wrapped to the disc: the refusal reason, the
      provisional notice. Canvas text has no layout engine, so this is the
      minimum that keeps a long reason from running off the sphere. */
  function drawCaption(lines, ramp, tone) {
    var R = baseR * view.zoom, size = 12, lh = 16, pad = 8, maxW = Math.min(R * 1.5, cssW - 32);
    ctx.font = '600 ' + size + 'px system-ui, -apple-system, "Segoe UI", sans-serif';
    var wrapped = [], i, j;
    for (i = 0; i < lines.length; i++) {
      var words = String(lines[i]).split(/\s+/), cur = '';
      for (j = 0; j < words.length; j++) {
        var t = cur ? cur + ' ' + words[j] : words[j];
        if (cur && ctx.measureText(t).width > maxW - 2 * pad) { wrapped.push(cur); cur = words[j]; } else cur = t;
      }
      if (cur) wrapped.push(cur);
    }
    if (wrapped.length > 5) { wrapped.length = 5; wrapped[4] += '...'; }
    var w = 0;
    for (i = 0; i < wrapped.length; i++) w = Math.max(w, ctx.measureText(wrapped[i]).width);
    w += 2 * pad;
    var h = wrapped.length * lh + 2 * pad - 4;
    var x = cx - w / 2, y = tone === 'refused' ? cy - h / 2 : Math.min(cssH - h - 12, cy + R * 0.82 - h);
    ctx.fillStyle = ramp.surface;
    ctx.strokeStyle = tone === 'refused' ? ramp.border : ramp.ink2;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = ramp.ink;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (i = 0; i < wrapped.length; i++) ctx.fillText(wrapped[i], cx, y + pad - 2 + lh / 2 + i * lh);
    ctx.textAlign = 'start';
    ctx.textBaseline = 'alphabetic';
  }

  /** 45-degree hatch clipped to one untested cell. The clip path is the same
      closed, horizon-bridged outline fillClippedRing() fills, so a cell cut
      by the limb is hatched only where it is visible. The lines are drawn in
      screen space (they do not rotate with the globe): a texture that says
      "nothing here", not a data mark. */
  function hatchCell(segs, R, ramp) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, i, j;
    for (i = 0; i < segs.length; i++) for (j = 0; j < segs[i].length; j++) {
      var p = segs[i][j];
      if (p.x < x0) x0 = p.x; if (p.x > x1) x1 = p.x;
      if (p.y < y0) y0 = p.y; if (p.y > y1) y1 = p.y;
    }
    if (!(x1 - x0 > 1) || !(y1 - y0 > 1)) return;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(segs[0][0].x, segs[0][0].y);
    for (i = 0; i < segs.length; i++) {
      var seg = segs[i];
      for (j = (i === 0 ? 1 : 0); j < seg.length; j++) ctx.lineTo(seg[j].x, seg[j].y);
      bridgeHorizon(seg[seg.length - 1], segs[(i + 1) % segs.length][0], R);
    }
    ctx.closePath();
    ctx.clip();
    ctx.strokeStyle = ramp.inkMuted;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    // lines of constant (x + y): from the cell's top-left to bottom-right
    // diagonal sweep, spaced COMP_HATCH_SPACING apart perpendicular to them.
    var step = COMP_HATCH_SPACING * Math.SQRT2;
    for (var k = Math.floor((x0 + y0) / step) * step; k <= x1 + y1; k += step) {
      ctx.moveTo(k - y0, y0);
      ctx.lineTo(k - y1, y1);
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawComposite() {
    hitPoints = [];                       // nothing here is a storm: clicks must not select one
    var ramp = compColors();
    if (!comp) {
      drawCaption(['No composite has been computed yet.'], ramp, 'refused');
      return;
    }
    if (!comp.drawable) {
      drawCaption(['Composite not drawn.', comp.refusal], ramp, 'refused');
      return;
    }
    var R = baseR * view.zoom, M = comp.max, i, w, segs;
    var alpha = comp.provisional ? COMP_PROVISIONAL_ALPHA : 1;
    var hovered = null, stip = [];

    // 1. fills, opaque (or washed, if provisional), with a hairline in the
    // surface colour between cells so the class boundaries (which are also
    // the hover targets) can be seen.
    for (i = 0; i < comp.cells.length; i++) {
      w = comp.cells[i];
      if (!w.drawn) continue;
      segs = visibleSegments(w.ring);
      if (!segs.length) continue;
      var f = w.cell[compField];
      ctx.globalAlpha = alpha;
      ctx.fillStyle = compColorFor(compClass(f.diff, M), ramp);
      fillClippedRing(segs, R);
      ctx.globalAlpha = 0.7;
      strokePath(segs, 0.8, ramp.surface);
      ctx.globalAlpha = 1;
      if (f.sigFDR) stip.push(w);
      if (w.id === hoveredCompId) hovered = { w: w, segs: segs };
    }

    drawCoastOverlay(ramp);

    // 2. untested cells: no fill, hatch, dotted ring (see the section
    // header). Drawn after the coast so they are not lost under it.
    for (i = 0; i < comp.cells.length; i++) {
      w = comp.cells[i];
      if (w.cell.tested) continue;
      segs = visibleSegments(w.ring);
      if (!segs.length) continue;
      hatchCell(segs, R, ramp);
      ctx.globalAlpha = 0.9;
      strokePath(segs, 1, ramp.inkMuted, [2, 3]);
      ctx.globalAlpha = 1;
      if (w.id === hoveredCompId) hovered = { w: w, segs: segs };
    }

    // 3. stipple: FDR-significant cells only.
    for (i = 0; i < stip.length; i++) drawStipple(stip[i], ramp);

    // 4. the hovered cell, outlined last.
    if (hovered) strokePath(hovered.segs, 2, ramp.ink);

    if (comp.provisional) {
      drawCaption(['PROVISIONAL: few seasons define this subset, so only a large shift could be detected. ' +
                   'No stippling is weak evidence of no shift.'], ramp, 'provisional');
    }
  }

  /* ---- hover ---- */

  function fmtLatBand(c) {
    // Bands never straddle the equator at the default 4 degree step, but a
    // coarser latStep can, so the two edges are named separately then.
    function one(v) { return Math.abs(Math.round(v * 10) / 10) + '\u00b0' + (v < 0 ? 'S' : 'N'); }
    if (c.lat0 < 0 && c.lat1 > 0) return one(c.lat0) + ' to ' + one(c.lat1);
    var lo = Math.min(Math.abs(c.lat0), Math.abs(c.lat1)), hi = Math.max(Math.abs(c.lat0), Math.abs(c.lat1));
    return lo + '\u2013' + hi + '\u00b0' + (c.lat1 <= 0 ? 'S' : 'N');
  }

  function fmtLonSpan(c) {
    if (c.dlon >= 359.9) return 'all longitudes';
    function one(v) {
      var x = normLonDeg(v);
      x = Math.round(x * 10) / 10;
      return Math.abs(x) + '°' + (x < 0 ? 'W' : x > 0 && x < 180 ? 'E' : '');
    }
    return one(c.lon0) + '–' + one(c.lon0 + c.dlon);
  }

  function fmtNum(v, d) {
    var s = v.toFixed(d == null ? 2 : d);
    return s === '-0.00' ? '0.00' : s;
  }

  function fmtSigned(v, d) {
    var s = fmtNum(v, d);
    return v > 0 && s !== fmtNum(0, d) ? '+' + s : s;
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many || one + 's'); }

  /** "3 fixes" / "1 storm visit", in the unit the comparison was run in. */
  function countWord(n) {
    return comp.result.options && comp.result.options.unit === 'events'
      ? plural(n, 'storm visit') : plural(n, 'fix', 'fixes');
  }

  /** The honest part. Everything the colour cannot say: both rates, the
      difference, how many fixes and seasons stand behind it, whether it
      survives FDR correction, and a plain-words warning when the cell is
      thin. All numbers come from composite.js untouched. */
  function compositeTip(w) {
    var c = w.cell, r = comp.result, n = r.n || {};
    var unit = compUnitLabel();
    var head = '<b>' + fmtLatBand(c) + ', ' + fmtLonSpan(c) + '</b>';
    if (!c.tested) {
      return head + '<div class="t-row">Not tested: ' + countWord(c.nAll) +
        ' in the full archive here (a cell needs ' +
        ((r.options && r.options.minCellCount) || 10) + ').</div>' +
        '<div class="t-row">Too few to say anything about this cell, either way.</div>';
    }
    var f = c[compField];
    if (!f) return head;
    var html = head +
      '<div class="t-row">Subset ' + fmtNum(f.subset) + ' vs baseline ' + fmtNum(f.all) + ' ' + unit +
      (compField === 'shape' ? ' (pattern only: total activity held at baseline)' : '') + '</div>' +
      '<div class="t-row"><b>' + fmtSigned(f.diff) + '</b> ' + unit +
      (f.ratio != null ? ' (' + fmtNum(f.ratio, 2) + '&times; baseline)' : '') +
      ' &middot; ' + (f.diff > 0 ? 'more' : f.diff < 0 ? 'fewer' : 'no change') + '</div>' +
      '<div class="t-row">Subset: ' + countWord(c.nSubset) + ', in ' + c.nSubsetSeasons + ' of its ' +
      (n.seasons != null ? n.seasons : '?') + ' seasons. Baseline: ' + countWord(c.nAll) + ' over ' +
      (n.allSeasons != null ? n.allSeasons : '?') + ' seasons.</div>';
    if (f.p == null) {
      html += '<div class="t-row"><b>Significance not assessed</b></div>';
    } else {
      html += '<div class="t-row"><b>' + (f.sigFDR ? 'FDR-significant' : 'Not FDR-significant') + '</b>' +
        (f.q != null ? ' (q = ' + fmtNum(f.q, 3) + ')' : '') +
        (f.sigFDR ? ' &middot; stippled' : ' &middot; no stipple') + '</div>';
      // Secondary and separately labelled by design - see the section header.
      html += '<div class="t-row" style="opacity:.75">Uncorrected p = ' + fmtNum(f.p, 3) +
        ' (not adjusted for ' + (r.summary && r.summary[compField] ? r.summary[compField].nTested : 'many') +
        ' cells tested; do not read as significance)</div>';
    }
    if (c.nSubset < COMP_THIN) {
      html += '<div class="t-row"><b>Thin:</b> only ' + countWord(c.nSubset) +
        ' from the subset here. A large-looking difference on this little is easily chance.</div>';
    }
    if (comp.provisional) {
      html += '<div class="t-row"><b>Provisional:</b> few seasons define this subset.</div>';
    }
    return html;
  }

  function handleCompositeHover(px, py, evt) {
    var w = null;
    if (comp && comp.drawable && comp.grid) {
      var geo = unproject(px, py);
      if (geo) {
        var id = comp.grid.cellIndex(geo[1], geo[0]);
        w = id >= 0 ? comp.byId[id] || null : null;
        if (w && !w.drawn && w.cell.tested) w = null;     // tested but no value for this field
      }
    }
    var id2 = w ? w.id : null;
    if (id2 !== hoveredCompId) {
      hoveredCompId = id2;
      dirty = true;
      scheduleFrame();
      canvas.style.cursor = w ? 'crosshair' : '';
      if (w) HF.showTip(compositeTip(w), evt); else HF.hideTip();
    } else if (w) {
      HF.moveTip(evt);
    }
  }

  /* ------------------------------------------------------------- currents
     Background context layer (see globe.setCurrentsVisible), independent of
     curLayer - it can sit under Tracks, Fix density or either point layer.
     window.HF_CURRENTS (tools/build_currents.py) is a multi-year *mean*
     OSCAR surface velocity field: u/v averaged separately over time, not an
     average of instantaneous speeds, so a persistently-directed flow (Gulf
     Stream, Kuroshio) keeps a strong mean while a patch of open ocean
     dominated by short-lived eddies averages down toward zero - which is
     exactly the "boundary currents stand out, open ocean recedes" effect
     this layer is asked to show.

     Rendering one arrow per ~2 deg cell over the whole globe would be pure
     noise, so each cell instead becomes a short flow-oriented streamlet
     (length and opacity scale with speed, direction follows atan2(v, u))
     and every streamlet is bucketed by speed into a handful of bins so the
     whole layer draws as a few beginPath()/stroke() pairs rather than one
     per cell - the same batching strokePath() already does for graticule
     lines, applied here because currents run into the thousands of
     segments where the graticule runs into dozens. */

  var CURRENT_BIN_COUNT = 6;
  var CURRENT_MIN_SPEED = 0.02;    // m/s - skip near-still cells; land is already null, not 0
  var CURRENT_HALF_MIN_DEG = 0.35; // streamlet half-length at the weak end of the ramp
  var CURRENT_HALF_MAX_DEG = 1.05; // ...and at/above the reference "strong" speed

  /** Perceptual (square-root) ramp from a faint, thin stroke for the common
      weak case up to a firm, opaque one for the strong tail - the same idea
      as densityRampColors()/drawOneCell's sqrt(frac) step, so a few strong
      cells (the boundary currents) don't get lost among many weak ones. */
  function currentBinStyle(i) {
    var t = i / (CURRENT_BIN_COUNT - 1);
    return { alpha: 0.08 + t * 0.80, width: 0.6 + t * 1.2 };
  }

  /** Turn window.HF_CURRENTS's u/v grid into per-bin arrays of short lon/lat
      segments, built once (geometry doesn't depend on view or theme) and
      cached in currentBins until the page reloads. Speed is normalized
      against the data's own p99 rather than a hardcoded constant, so the
      ramp adapts to whatever the archive's mean field actually contains
      instead of a guessed reference that could clip nothing, or everything,
      depending on the run. */
  function buildCurrentSegments() {
    currentBins = [];
    for (var b = 0; b < CURRENT_BIN_COUNT; b++) currentBins.push([]);

    var data = window.HF_CURRENTS;
    if (!data || !data.grid || !data.u || !data.v) return;
    var g = data.grid;
    var ref = (data.stats && data.stats.p99Speed) || 0.4;
    if (!(ref > 0)) ref = 0.4;

    for (var i = 0; i < g.nlat; i++) {
      var lat = g.lat0 + i * g.latStep;
      // Meridians converge toward the poles, so the same angular u-offset
      // covers more longitude there; dividing by cos(lat) keeps a
      // streamlet's on-screen orientation matching its true flow direction
      // instead of skewing toward "due east/west" at high latitude. OSCAR's
      // own coverage stops at +-80, so this never approaches the pole.
      var cosLat = Math.max(0.12, Math.cos(lat * DEG));
      var uRow = data.u[i], vRow = data.v[i];
      for (var j = 0; j < g.nlon; j++) {
        var u = uRow[j], v = vRow[j];
        if (u == null || v == null) continue;         // land, or no data - never treated as 0
        var speed = Math.sqrt(u * u + v * v);
        if (speed < CURRENT_MIN_SPEED) continue;

        var t = Math.min(1, speed / ref);
        var perceptual = Math.sqrt(t);
        var bin = Math.min(CURRENT_BIN_COUNT - 1, Math.floor(perceptual * CURRENT_BIN_COUNT));
        var half = CURRENT_HALF_MIN_DEG + perceptual * (CURRENT_HALF_MAX_DEG - CURRENT_HALF_MIN_DEG);

        var lon = g.lon0 + j * g.lonStep;
        var theta = Math.atan2(v, u);
        var dLat = half * Math.sin(theta);
        var dLon = (half * Math.cos(theta)) / cosLat;

        currentBins[bin].push({
          lon0: lon - dLon, lat0: lat - dLat,
          lon1: lon + dLon, lat1: lat + dLat
        });
      }
    }
  }

  /** project() + horizon-crossing clip of one lon/lat segment - the same
      logic strokeEdge() uses per track edge, factored out here because
      currents batch many segments into one path/stroke() call instead of
      stroking each edge individually. */
  function clipSegment(lon0, lat0, lon1, lat1) {
    var p0 = project(lon0, lat0), p1 = project(lon1, lat1);
    if (!p0.visible && !p1.visible) return null;
    if (p0.visible !== p1.visible) {
      var cross = horizonCrossing([lon0, lat0], [lon1, lat1]);
      var pc = project(cross[0], cross[1]);
      if (p0.visible) p1 = pc; else p0 = pc;
    }
    return [p0, p1];
  }

  function drawCurrents() {
    if (!currentBins) buildCurrentSegments();
    ctx.lineCap = 'round';
    for (var b = 0; b < currentBins.length; b++) {
      var list = currentBins[b];
      if (!list.length) continue;
      var style = currentBinStyle(b);
      ctx.globalAlpha = style.alpha;
      ctx.lineWidth = style.width;
      ctx.strokeStyle = pal.current;
      ctx.beginPath();
      for (var i = 0; i < list.length; i++) {
        var seg = list[i];
        var clipped = clipSegment(seg.lon0, seg.lat0, seg.lon1, seg.lat1);
        if (!clipped) continue;
        ctx.moveTo(clipped[0].x, clipped[0].y);
        ctx.lineTo(clipped[1].x, clipped[1].y);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.lineCap = 'butt';
  }

  /* ------------------------------------------------------------ dispatch */

  function drawFeatures() {
    if (curLayer === 'density') return drawDensity();
    if (curLayer === 'genesis') return drawPoints('genesis');
    if (curLayer === 'peak') return drawPoints('peak');
    if (curLayer === 'playback') return drawPlayback();
    if (curLayer === 'composite') return drawComposite();
    return drawTracks();
  }

  /** Everything under the features: ocean disc, currents, graticule, land.
      None of it depends on anything but the view (lambda, phi, zoom), the
      canvas size, the theme and the currents toggle - and during playback
      the view does not change from one frame to the next, only the storms
      do. Measured, this is the ~17 ms per-frame floor (see the report that
      came with the playback layer): the graticule and ~60 coastline rings
      are projected, horizon-clipped and stroked point by point. So
      paintStatic() renders it once into an offscreen canvas and blits that
      for every frame until the view, size or theme actually changes. */
  function drawStaticLayers() {
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

    // 2. ocean currents - background context, independent of curLayer (see
    // globe.setCurrentsVisible), drawn on the ocean before the graticule/
    // land/features so it reads as quiet backdrop rather than competing
    // with the reference grid or whatever the active layer draws on top.
    if (showCurrents) drawCurrents();

    // 3. graticule
    drawGraticule();

    // 4. land
    drawLand();
  }

  function staticKey() {
    // Exact numbers, not rounded: a rounded key would let a slow drag show a
    // stale background for a few frames; the string is cheap to build.
    return view.lambda + '|' + view.phi + '|' + view.zoom + '|' + canvas.width + 'x' +
      canvas.height + '@' + dpr + '|' + themeGen + '|' + (showCurrents ? 1 : 0);
  }

  /** Put the static layers on the main canvas - from the cache when it is
      current, drawn directly otherwise. Returns true when it blitted.
      Only the playback layer uses the cache: it is the one layer that
      redraws every frame with a still view, so it is the one that gains,
      and the other layers keep exactly the code path they always had.
      window.HF_NO_STATIC_CACHE switches the cache off, for the same
      measure-before-and-after use as HF_DEBUG_TIMING. */
  function paintStatic() {
    if (curLayer !== 'playback' || window.HF_NO_STATIC_CACHE) {
      ctx.clearRect(0, 0, cssW, cssH);
      drawStaticLayers();
      return false;
    }
    var key = staticKey();
    if (bg.key !== key) {
      if (!bg.canvas) {
        bg.canvas = document.createElement('canvas');
        bg.ctx = bg.canvas.getContext('2d');
      }
      // Assigning width/height reallocates and clears, so only do it when
      // the size really changed; otherwise clear in place.
      if (bg.canvas.width !== canvas.width || bg.canvas.height !== canvas.height) {
        bg.canvas.width = canvas.width;
        bg.canvas.height = canvas.height;
      }
      // The draw helpers all use the module-level `ctx`, so point it at the
      // offscreen context for the duration rather than threading a context
      // argument through ten functions that have no other reason to take one.
      var main = ctx;
      ctx = bg.ctx;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);
      drawStaticLayers();
      ctx = main;
      bg.key = key;
    }
    // Device pixels 1:1, so no transform and no resampling. 'copy' replaces
    // the destination outright, which saves the separate clearRect.
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = 'copy';
    ctx.drawImage(bg.canvas, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return true;
  }

  function draw() {
    if (!ctx || !cssW || !cssH || !pal) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    var dbg = window.HF_DEBUG_TIMING;
    var t0 = dbg ? performance.now() : 0;
    var R = baseR * view.zoom;

    var cached = paintStatic();
    var t1 = dbg ? performance.now() : 0;

    // 5. the active layer's features (selected/hovered drawn last within it)
    drawFeatures();
    var t2 = dbg ? performance.now() : 0;

    // 6. sphere outline, always on top and always a full circle
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = pal.outline;
    ctx.stroke();

    if (dbg) {
      // Canvas 2D records commands and rasterizes later, so the clock above
      // can read near zero for a frame that is expensive to paint. With
      // HF_DEBUG_SYNC also set, read one pixel back to force the pending
      // raster to finish and make the numbers the true per-frame cost.
      // Debug only: the readback itself stalls the pipeline.
      if (window.HF_DEBUG_SYNC) ctx.getImageData(0, 0, 1, 1);
      globe.lastDraw = { layer: curLayer, cached: cached, staticMs: t1 - t0,
                         featureMs: t2 - t1, totalMs: performance.now() - t0 };
    }
  }

  /* ---------------------------------------------------------- animation
     Redraw only when something changed (dirty) or while actively dragging
     or coasting on inertia - never a permanent background loop. */

  function scheduleFrame() {
    if (rafId || !visible) return;
    rafId = window.requestAnimationFrame(tick);
  }

  function pbFading() {
    return pbLayers.length > 1 || (pbLayers.length === 1 && pbLayers[0].dir !== 0);
  }

  function tick() {
    rafId = null;
    if (!visible) return;

    var now = performance.now();
    var animating = dragging || !!inertia || !!transition || pbFading() || !!animator;
    if (dirty || animating) {
      if (inertia) stepInertia();
      if (transition) stepTransition();
      // The app's playback clock runs here, inside the one rAF loop, rather
      // than on a second loop of its own: a second requestAnimationFrame
      // would be queued behind this one and land its frame a whole display
      // frame late. It sets the new frame (which marks us dirty) and says
      // whether to keep going.
      if (animator && !animator(now)) animator = null;
      if (pbLayers.length) stepFade(now);
      // window.HF_DEBUG_TIMING flips this on for perf investigation (e.g. the
      // hover-emphasis redraw path below) without adding a console.log that
      // fires on every normal frame/drag.
      if (window.HF_DEBUG_TIMING) {
        var t0 = performance.now();
        draw();
        var ld = globe.lastDraw || {};
        console.log('[globe] draw() took ' + (performance.now() - t0).toFixed(2) + ' ms, ' + lows.length +
          ' tracks, layer ' + curLayer + (ld.cached ? ' (static cached)' : '') +
          ' [static ' + (ld.staticMs || 0).toFixed(2) + ' ms, features ' + (ld.featureMs || 0).toFixed(2) + ' ms]');
      } else {
        draw();
      }
      dirty = false;
      if (curLayer === 'playback') afterPlaybackDraw();
    }
    if (dragging || !!inertia || !!transition || pbFading() || !!animator) scheduleFrame();
  }

  function stepInertia() {
    view.lambda += inertia.vx;
    view.phi = clampPhi(view.phi + inertia.vy);
    inertia.vx *= 0.94;
    inertia.vy *= 0.94;
    if (Math.abs(inertia.vx) < 0.00005 && Math.abs(inertia.vy) < 0.00005) inertia = null;
  }

  function clampPhi(p) { return Math.max(-MAX_PHI, Math.min(MAX_PHI, p)); }

  function easeInOutCubic(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

  /** Animate the view to (lambda, phi, zoom) over `dur` ms - basin switches,
      "fit to events" and the double-click reset all go through this so
      there is exactly one rotate/zoom transition in the file. Respects
      prefers-reduced-motion by jumping straight there instead. lambda's
      delta is taken the short way round so a basin near +-180 doesn't spin
      the long way to get there. */
  function startTransition(toLambda, toPhi, toZoom, dur) {
    inertia = null;
    if (reducedMotion()) {
      view.lambda = toLambda;
      view.phi = clampPhi(toPhi);
      view.zoom = toZoom;
      transition = null;
      dirty = true;
      scheduleFrame();
      return;
    }
    var dl = toLambda - view.lambda;
    while (dl > Math.PI) dl -= Math.PI * 2;
    while (dl < -Math.PI) dl += Math.PI * 2;
    transition = {
      fromLambda: view.lambda, dl: dl,
      fromPhi: view.phi, toPhi: clampPhi(toPhi),
      fromZoom: view.zoom, toZoom: toZoom,
      t0: performance.now(), dur: dur || 650
    };
    dirty = true;
    scheduleFrame();
  }

  function stepTransition() {
    var t = (performance.now() - transition.t0) / transition.dur;
    if (t >= 1) {
      view.lambda = transition.fromLambda + transition.dl;
      view.phi = transition.toPhi;
      view.zoom = transition.toZoom;
      transition = null;
      return;
    }
    var e = easeInOutCubic(t);
    view.lambda = transition.fromLambda + transition.dl * e;
    view.phi = transition.fromPhi + (transition.toPhi - transition.fromPhi) * e;
    view.zoom = transition.fromZoom + (transition.toZoom - transition.fromZoom) * e;
  }

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
      ' &middot; ' + low.hfH + ' h at HF</div>' +
      (low.bomb ? '<div class="t-row">Explosive: ' + low.berg.toFixed(2) + ' B</div>' : '');
  }

  /** Tooltip text for a hit. In playback a storm is moving, so the event's
      summary alone ("Min 962 hPa") would not say what it is doing right now;
      a clock frame adds its current pressure and position. */
  function tipFor(hit) {
    var html = fixTip(hit.low);
    var s = hit.storm;
    if (curLayer === 'playback' && pbKind === 'clock' && s) {
      html += '<div class="t-row">Now: ' +
        (s.pres != null ? Math.round(s.pres) + ' hPa' : 'no analyzed centre') +
        ' &middot; ' + HF.fmtLatLon(s.lat, s.lon) + '</div>';
    }
    return html;
  }

  /** Lat/lon readout under the cursor, in the site's own HF.fmtLatLon format
      so it matches the tables and every other tooltip. Hidden whenever the
      cursor isn't actually over the sphere. */
  function updateReadout(px, py) {
    if (!readoutEl) return;
    var geo = unproject(px, py);
    if (!geo) { readoutEl.hidden = true; return; }
    readoutEl.hidden = false;
    readoutEl.textContent = HF.fmtLatLon(geo[1], geo[0]);
  }

  function hideReadout() { if (readoutEl) readoutEl.hidden = true; }

  /* A throttle that only ever DROPS moves leaves the tooltip on whatever the
     last accepted move saw: the pointer stops inside the 30 ms window, the
     final position is discarded, and the readout names the neighbouring cell
     until the mouse moves again. On the storm layers that is a missed hover;
     on the composite layer it is a tooltip quoting the wrong cell's numbers,
     which is worse than none. So a dropped move is remembered and replayed
     once, when the window closes (a trailing edge). */
  var pendingHover = null, hoverTimer = null;

  function replayHover() {
    hoverTimer = null;
    var e = pendingHover;
    pendingHover = null;
    if (!e || dragging || !canvas || !lastPointer) return;
    handleHover(e, canvas.getBoundingClientRect());
  }

  function handleHover(evt, rect) {
    var now = performance.now();
    if (now - lastHoverT < HOVER_THROTTLE_MS) {
      pendingHover = { clientX: evt.clientX, clientY: evt.clientY };
      if (!hoverTimer) hoverTimer = window.setTimeout(replayHover, HOVER_THROTTLE_MS - (now - lastHoverT) + 2);
      return;
    }
    pendingHover = null;
    lastHoverT = now;

    var px = evt.clientX - rect.left, py = evt.clientY - rect.top;

    if (curLayer === 'density') { handleDensityHover(px, py, evt); return; }
    if (curLayer === 'composite') { handleCompositeHover(px, py, evt); return; }

    updateHover(nearestHit(px, py), evt);
  }

  /** Apply a hit-test result to the hover state. Shared by the mousemove
      path above and by afterPlaybackDraw(), which has to re-run it when the
      storms move under a stationary cursor. `evt` only needs clientX/Y. */
  function updateHover(hit, evt) {
    var key = hit ? hit.low.key : null;

    if (key !== hoveredKey) {
      hoveredKey = key;
      // Only the ~1,870-track redraw needs to happen on a hover *change*,
      // not on every mousemove tick - dirty/scheduleFrame is the same
      // mechanism drags and renders already use, so this doesn't add a
      // second animation path.
      dirty = true;
      scheduleFrame();
      canvas.style.cursor = key ? 'pointer' : '';
      if (hit) { lastTipHtml = tipFor(hit); HF.showTip(lastTipHtml, evt); }
      else { lastTipHtml = ''; HF.hideTip(); }
    } else if (hit) {
      if (curLayer === 'playback') {
        // The storm under the cursor keeps moving, so its "Now:" row changes
        // every few frames - rewrite the tooltip only when the text did.
        var html = tipFor(hit);
        if (html !== lastTipHtml) { lastTipHtml = html; HF.showTip(html, evt); }
        else HF.moveTip(evt);
      } else {
        HF.moveTip(evt);
      }
    }
  }

  /** Density cells have no `low` to key hover off, so this hit-tests via the
      inverse projection instead of the hitPoints/nearestHit machinery the
      other layers share - unprojecting the cursor and re-running the same
      bin math computeDensityGrid used keeps the two in lockstep. */
  function handleDensityHover(px, py, evt) {
    var geo = curGrid ? unproject(px, py) : null;
    var cell = null, key = null;
    if (geo) {
      var latIdx = Math.floor(geo[1] / CELL_LAT);
      var lonIdx = Math.floor(densityLon(geo[0]) / CELL_LON);
      key = latIdx + ':' + lonIdx;
      cell = curGrid.byKey[key];
      if (!cell || !cell.hf) { cell = null; key = null; }
    }
    if (key !== hoveredCellKey) {
      hoveredCellKey = key;
      dirty = true;
      scheduleFrame();
      canvas.style.cursor = key ? 'pointer' : '';
      if (cell) HF.showTip(densityTip(cell), evt); else HF.hideTip();
    } else if (cell) {
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
    // An inline style has higher specificity than the .is-dragging class's
    // cursor:grabbing rule, so a lingering hover pointer would otherwise
    // survive into the drag; clear it and let the CSS class take over.
    canvas.style.cursor = '';
    if (canvas.setPointerCapture) {
      try { canvas.setPointerCapture(evt.pointerId); } catch (err) { /* ignore */ }
    }
    evt.preventDefault();
  }

  function onPointerMove(evt) {
    var rect = canvas.getBoundingClientRect();
    var px = evt.clientX - rect.left, py = evt.clientY - rect.top;
    updateReadout(px, py);
    lastPointer = dragging ? null : { px: px, py: py, clientX: evt.clientX, clientY: evt.clientY };

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
      hoveredCellKey = null;
      hoveredCompId = null;
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

    // A scroll mid-transition would otherwise fight startTransition()'s
    // tween every animation frame, each pulling the view a different way -
    // treat wheel input as the user taking the camera back.
    transition = null;

    var rect = canvas.getBoundingClientRect();
    var px = evt.clientX - rect.left, py = evt.clientY - rect.top;
    var anchor = unproject(px, py);   // [lonDeg, latDeg] under the cursor, pre-zoom

    var factor = Math.pow(1.0016, -evt.deltaY);
    var newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom * factor));

    // Re-aim the view so the same geographic point ends up back under the
    // cursor at the new zoom, instead of the zoom just scaling about the
    // view centre. unproject() holds the view fixed and solves for the
    // point under a screen pixel; here it's the reverse - the point (the
    // anchor above) and its pixel are the known quantities, and the view's
    // (lambda, phi) is what we solve for.
    //
    // Project's x/y/c are just the anchor's unit vector re-expressed in an
    // orthonormal frame built from the view (east/north/"out of the
    // screen"), so (X, Y, c) below are exactly that triple for the pixel
    // we want the anchor to land on at the new zoom. Recovering the view
    // from a point and its coordinates in the view's own frame comes out
    // to two candidate solutions (the quadratic in K below) rather than
    // one - picking the wrong one would still land the anchor on the
    // right pixel (both roots satisfy the same X/Y/c) but could flip the
    // camera to a wild, discontinuous orientation, so the branch is chosen
    // by which one stays on the same side of the anchor's meridian as the
    // *current* (pre-zoom) view - a scroll only ever nudges the view a
    // little, so that side can't have flipped.
    //
    // Falls back to the plain centre-anchored zoom below (no rotation
    // change) when: the cursor was off the sphere's disc to begin with
    // (anchor is null); the zoom didn't actually move because it was
    // already sitting on MIN_ZOOM/MAX_ZOOM (newZoom === view.zoom, checked
    // against the post-clamp value so repeated scrolling at a clamp can't
    // drift the view at all); the anchor point falls outside the disc at
    // the new zoom (rho2 > 1, e.g. zooming out shrank the sphere past the
    // cursor); or the anchor's own latitude can't reach that far off its
    // meridian at that pixel regardless of view (k2 < 0 - every point's
    // east/west screen offset is capped by cos(latitude), so a pixel can
    // demand more than a given parallel can ever supply). Any of these
    // means there's no view that puts the anchor back under the cursor, so
    // the old rotation is left alone and only the zoom takes effect.
    if (anchor && newZoom !== view.zoom) {
      var R = baseR * newZoom;
      if (R) {
        var X = (px - cx) / R, Y = (cy - py) / R;
        var rho2 = X * X + Y * Y;
        if (rho2 <= 1) {
          var c = Math.sqrt(Math.max(0, 1 - rho2));
          var lat = anchor[1] * DEG, lon = anchor[0] * DEG;
          var sinPhi = Math.sin(lat), cosPhi = Math.cos(lat);
          var k2 = cosPhi * cosPhi - X * X;
          if (k2 >= 0) {
            var kMag = Math.sqrt(k2);
            var kSign = Math.cos(lon - view.lambda) < 0 ? -1 : 1;
            var k = kSign * kMag;
            var denom = k * k + sinPhi * sinPhi;
            if (denom > 1e-9) {
              var sinPhiV = (sinPhi * c - k * Y) / denom;
              var cosPhiV = (k * c + sinPhi * Y) / denom;
              view.phi = clampPhi(Math.atan2(sinPhiV, cosPhiV));
              view.lambda = lon - Math.atan2(X, k);
            }
          }
        }
      }
    }

    view.zoom = newZoom;
    dirty = true;
    scheduleFrame();
  }

  function onDblClick() {
    globe.resetView();
  }

  function onLeave() {
    lastPointer = null;
    pendingHover = null;
    if (!dragging) {
      if (hoveredKey != null || hoveredCellKey != null || hoveredCompId != null) {
        hoveredKey = undefined;
        hoveredCellKey = null;
        hoveredCompId = null;
        dirty = true;
        scheduleFrame();
      }
      canvas.style.cursor = '';
      HF.hideTip();
    }
    hideReadout();
  }

  /* ------------------------------------------------------------- public */

  globe.init = function (elementId, onSelectCb) {
    canvas = document.getElementById(elementId);
    if (!canvas || !canvas.getContext) return null;
    ctx = canvas.getContext('2d');
    onSelect = onSelectCb;
    readoutEl = document.getElementById('globeReadout');
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

  /** lows/selectedKey/layer for the next draw(). Switching layers clears any
      hover state left over from the previous one (a hovered-cell key means
      nothing once density stops being the layer, etc.) and recomputes the
      density grid only when that layer is actually active. */
  globe.render = function (lowsArg, selKey, layer) {
    // render('composite'): a lone string is a layer name, and the lows and
    // selection from the last full call stay as they were.
    if (typeof lowsArg === 'string' && selKey === undefined && layer === undefined) {
      layer = lowsArg; lowsArg = lows; selKey = selectedKey;
    }
    lows = lowsArg || [];
    selectedKey = selKey || null;
    var newLayer = layer || 'tracks';
    if (newLayer !== curLayer) {
      hoveredKey = undefined;
      hoveredCellKey = null;
      hoveredCompId = null;
      if (canvas) canvas.style.cursor = '';
      HF.hideTip();
    }
    curLayer = newLayer;
    curGrid = curLayer === 'density' ? computeDensityGrid(lows) : null;
    dirty = true;
    scheduleFrame();
  };

  /** Circular mean of a set of fixes' unit vectors - shared by focus() (one
      event) and fitTo() (a whole filtered set) - not a plain lon/lat
      average, so a cluster that crosses the antimeridian centres correctly
      instead of averaging to the wrong side of the world. */
  function circularMean(fixes) {
    var sum = [0, 0, 0];
    for (var i = 0; i < fixes.length; i++) {
      var v = toXYZ(fixes[i].lon, fixes[i].lat);
      sum[0] += v[0]; sum[1] += v[1]; sum[2] += v[2];
    }
    var len = Math.sqrt(dot3(sum, sum)) || 1;
    return [sum[0] / len, sum[1] / len, sum[2] / len];
  }

  /** Rotate so this event's track faces the viewer. */
  globe.focus = function (low) {
    if (!low || !low.fixes || !low.fixes.length) return;
    var center = fromXYZ(circularMean(low.fixes));
    startTransition(center[0] * DEG, center[1] * DEG, Math.max(view.zoom, 1.4), 500);
  };

  /** Rotate/zoom to frame a whole filtered set of events - "Fit to events",
      and also how selecting a single basin points the globe at it (its
      centre is derived from that basin's own fixes here, not a hardcoded
      lon/lat). Does nothing when the set is empty, leaving the current view
      in place rather than throwing or snapping to some default. */
  globe.fitTo = function (lowsArg) {
    var list = lowsArg || [];
    var allFixes = [];
    for (var i = 0; i < list.length; i++) allFixes = allFixes.concat(list[i].fixes);
    if (!allFixes.length) return;

    var centerVec = circularMean(allFixes);
    var center = fromXYZ(centerVec);
    var maxAngle = 0;
    for (i = 0; i < allFixes.length; i++) {
      var v = toXYZ(allFixes[i].lon, allFixes[i].lat);
      var ang = Math.acos(Math.max(-1, Math.min(1, dot3(v, centerVec))));
      if (ang > maxAngle) maxAngle = ang;
    }
    // Orthographic projection puts a point at angular separation theta from
    // the view centre at planar distance R*sin(theta) from the disc centre
    // (see project()) - so this solves for the zoom that lands the single
    // farthest fix at ~82% of the disc radius, with a little padding, and
    // clamps to the normal zoom range so one nearby event doesn't zoom to
    // street level.
    var capped = Math.min(maxAngle, Math.PI / 2 - 0.05);
    var z = capped > 0.01 ? 0.82 / Math.sin(capped) : MAX_ZOOM;
    z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
    startTransition(center[0] * DEG, center[1] * DEG, z, 700);
  };

  /** Back to the default pole-centred view that shows both basins - used by
      "Both basins" in the filter and the double-click reset. */
  globe.resetView = function () {
    startTransition(DEFAULT_LAMBDA_DEG * DEG, DEFAULT_PHI_DEG * DEG, 1, 650);
  };

  globe.resize = function () {
    if (!canvas) return;
    // Measure the wrapper, not the canvas itself: #globe is sized in CSS to
    // fill #globeWrap (position:absolute; inset:0 - see assets/globe.css),
    // but reading the canvas's own clientWidth/clientHeight here would read
    // back the backing-store size this function just wrote to canvas.width/
    // height a moment ago (canvas.width/height are content attributes that
    // also set the element's intrinsic, and in some layouts effective,
    // client size) - a feedback loop that can drift away from the real
    // container size instead of converging on it. The parent element's box
    // has no such circularity.
    var wrap = canvas.parentElement;
    var rect = wrap ? wrap.getBoundingClientRect() : canvas.getBoundingClientRect();
    cssW = rect.width;
    cssH = rect.height;
    if (!cssW || !cssH) return;             // hidden panel; next resize() will catch up
    dpr = window.devicePixelRatio || 1;
    // Pin the canvas's CSS box explicitly (belt-and-suspenders alongside the
    // inset:0 rule in assets/globe.css) so canvas box == wrapper box holds
    // even if something upstream changes how #globeWrap lays out its child.
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
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

  /** Hand the globe the frame to draw for layer 'playback'.

      frame  an HF.playback frame: a clock's at(t, tail) result, or the
             engine's step(season) result.
      opts   {kind: 'clock' | 'step', tailHours: number | Infinity,
              crossfade: false to cut instead of dissolve}

      Clock frames replace each other instantly - the heads already move
      smoothly, there is nothing to dissolve. A step frame arriving over
      another step frame crossfades (PB_FADE_MS), matched by storm key; under
      prefers-reduced-motion it cuts. A fade interrupted by yet another frame
      continues from its current alpha instead of popping. */
  globe.setPlaybackFrame = function (frame, opts) {
    opts = opts || {};
    var kind = opts.kind === 'step' ? 'step' : 'clock';
    var now = performance.now();
    var wasKind = pbKind;
    pbKind = kind;
    pbTail = opts.tailHours == null ? 48 : opts.tailHours;
    if (!frame) { pbLayers = []; }
    else if (kind === 'step' && wasKind === 'step' && pbLayers.length &&
             opts.crossfade !== false && !reducedMotion()) {
      for (var i = 0; i < pbLayers.length; i++) {
        var l = pbLayers[i];
        l.a0 = layerAlpha(l, now); l.t0 = now; l.dir = -1;
      }
      pbLayers.push({ frame: frame, a0: 0, t0: now, dir: 1 });
    } else {
      pbLayers = [{ frame: frame, a0: 1, t0: now, dir: 0 }];
    }
    dirty = true;
    scheduleFrame();
  };

  /** Install (or, with null, remove) the callback that advances playback.
      It is called once per animation frame, before drawing, with the frame
      timestamp, and returns true to keep running. Lives in the globe's own
      loop - see tick() for why. */
  globe.setAnimator = function (fn) {
    animator = fn || null;
    if (animator) scheduleFrame();
  };

  // app.js needs the same answer for "do not autoplay"; one definition here.
  globe.prefersReducedMotion = reducedMotion;

  /** Toggle the ocean currents background layer - independent of
      globe.render's layer argument, so it can be shown under Tracks, Fix
      density or either point layer. Off by default; app.js calls this only
      from an explicit checkbox change. */
  globe.setCurrentsVisible = function (isVisible) {
    showCurrents = !!isVisible;
    dirty = true;
    scheduleFrame();
  };

  // Read by app.js to colour the currents legend swatch with the exact
  // shade drawCurrents() strokes with, rather than duplicating the
  // isDarkTheme()/fallback logic in two files.
  globe.currentsColor = function () { return pal ? pal.current : null; };

  /** Composite-anomaly layer (see the "composite" section).

        HF.globe.setComposite(result [, opts])   result from HF.composite.compare(), or null to clear
        HF.globe.render('composite')             show it (the full render(lows, sel, layer) form works too)

      opts.field     'rate' (default) | 'shape'. Which difference to colour.
      opts.scaleMax  fix the colour scale at +-scaleMax instead of fitting it
                     to the data, so two maps can share one scale.

      Returns compositeState(). Nothing is drawn for a result that is not
      status 'ok' or has reliability 'none'; the state says so and why. */
  globe.setComposite = function (result, opts) {
    opts = opts || {};
    compField = opts.field === 'shape' ? 'shape' : 'rate';
    compScaleMax = opts.scaleMax > 0 ? Number(opts.scaleMax) : null;
    compSetResult(result);
    return compState();
  };

  /** Switch between 'rate' and 'shape' on the result already set. */
  globe.setCompositeField = function (field) {
    compField = field === 'shape' ? 'shape' : 'rate';
    hoveredCompId = null;
    HF.hideTip();
    compRefresh();
    dirty = true;
    scheduleFrame();
    return compState();
  };

  /** Fix (or, with null, release) the +-max of the colour scale. */
  globe.setCompositeScale = function (max) {
    compScaleMax = max > 0 ? Number(max) : null;
    compRefresh();
    dirty = true;
    scheduleFrame();
    return compState();
  };

  /** {state: 'none'|'refused'|'provisional'|'ok', drawn, reason, warnings,
      field, unit, scaleMax, nTested, nUntested, nSigFDR, expectedByChance,
      summary, n, status, reliability} - what the tab needs to explain the map. */
  globe.compositeState = compState;

  /** The colour scale as data ({bins: [{cls, lo, hi, color, meaning}], max,
      unit, alpha, stipple, untested, ...}) with colours resolved for the
      current theme, or null when nothing is drawn. Same table the canvas uses. */
  globe.compositeLegend = compLegend;

  // Read by app.js for the "Fix density" map-note text, same as the flat
  // map exposed them (HF.maps.CELL_LAT/CELL_LON) before it was removed.
  globe.CELL_LAT = CELL_LAT;
  globe.CELL_LON = CELL_LON;

})(window.HF.globe = window.HF.globe || {}, window.HF);
