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

  var curLayer = 'tracks';               // 'tracks' | 'density' | 'genesis' | 'peak'

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
      current: readColor('--current', isDarkTheme() ? '#5fb6bf' : '#2c6c73')
    };
  }

  globe.applyTheme = function () {
    computePalette();
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
    return drawTracks();
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

    // 2. ocean currents - background context, independent of curLayer (see
    // globe.setCurrentsVisible), drawn on the ocean before the graticule/
    // land/features so it reads as quiet backdrop rather than competing
    // with the reference grid or whatever the active layer draws on top.
    if (showCurrents) drawCurrents();

    // 3. graticule
    drawGraticule();

    // 4. land
    drawLand();

    // 5. the active layer's features (selected/hovered drawn last within it)
    drawFeatures();

    // 6. sphere outline, always on top and always a full circle
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

    var animating = dragging || !!inertia || !!transition;
    if (dirty || animating) {
      if (inertia) stepInertia();
      if (transition) stepTransition();
      // window.HF_DEBUG_TIMING flips this on for perf investigation (e.g. the
      // hover-emphasis redraw path below) without adding a console.log that
      // fires on every normal frame/drag.
      if (window.HF_DEBUG_TIMING) {
        var t0 = performance.now();
        draw();
        console.log('[globe] draw() took ' + (performance.now() - t0).toFixed(2) + ' ms, ' + lows.length + ' tracks');
      } else {
        draw();
      }
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

  function handleHover(evt, rect) {
    var now = performance.now();
    if (now - lastHoverT < HOVER_THROTTLE_MS) return;
    lastHoverT = now;

    var px = evt.clientX - rect.left, py = evt.clientY - rect.top;

    if (curLayer === 'density') { handleDensityHover(px, py, evt); return; }

    var hit = nearestHit(px, py);
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
      if (hit) HF.showTip(fixTip(hit.low), evt); else HF.hideTip();
    } else if (hit) {
      HF.moveTip(evt);
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
    if (!dragging) {
      if (hoveredKey != null || hoveredCellKey != null) {
        hoveredKey = undefined;
        hoveredCellKey = null;
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
    lows = lowsArg || [];
    selectedKey = selKey || null;
    var newLayer = layer || 'tracks';
    if (newLayer !== curLayer) {
      hoveredKey = undefined;
      hoveredCellKey = null;
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

  // Read by app.js for the "Fix density" map-note text, same as the flat
  // map exposed them (HF.maps.CELL_LAT/CELL_LON) before it was removed.
  globe.CELL_LAT = CELL_LAT;
  globe.CELL_LON = CELL_LON;

})(window.HF.globe = window.HF.globe || {}, window.HF);
