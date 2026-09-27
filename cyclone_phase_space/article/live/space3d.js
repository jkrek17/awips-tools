/* Cyclone Phase Space, live: the selected low in Hart's 3-D phase space.
   The third view of the selected low's entry in the storm panel (storms.js
   switches between it and the two 2-D diagrams). The axes and cells are
   those of the article's 3-D figure (article/figures/phase_space_3d.py):
   x = -V_T^L, y = B, z = -V_T^U (vertical), box aspect 1 : 1 : 0.9, on the
   Figure 1 ranges of the 2-D diagrams (FIG1). The planes B = 10 m,
   -V_T^L = 0 and -V_T^U = 0 cut the space into eight boxes; the two with a
   cold lower and warm upper layer (either B) are one cell, class 6, so
   there are seven, in legend.json's class colors.

   Drawn on a canvas by hand: a rotation about the vertical (azimuth, as
   matplotlib's azim) and a tilt (elevation), then a mild perspective
   (DIST, the eye's distance in half box widths). Back to front: the far
   panes' grid, the cell faces (translucent, sorted by depth), the box
   edges and the dividing planes, the class numbers, the axes, then the
   track on top, colored by class per segment as on the map, with a dot
   every 6 h, the start and end marked, a label every 24 h and a ring at
   the hour on screen (S.i). Points with a missing value are skipped, and
   values beyond the box are drawn on its wall as hollow dots, as the 2-D
   diagrams do.

   Drag rotates, a pinch zooms, a double click or double tap resets; once
   the view has focus the wheel zooms and the arrow keys rotate (app.js
   leaves the arrows to it). A click on a dot shows that hour. The camera
   is shared by every low for the session. Uses the globals of app.js and
   storms.js. */
'use strict';

const Space3D = (() => {
  const DEFAULT = { az: -50, el: 25, zoom: 1 };
  const EL = [-10, 90];           // elevation limits, degrees
  const ZOOM = [0.8, 1.8];        // modest
  const DIST = 9;                 // eye distance: a mild perspective
  const ASPECT_Z = 0.9;           // the article's box aspect (1, 1, 0.9)
  const FACE_A = 0.085;           // cell face alpha
  const cam = { ...DEFAULT };     // shared by every view, for the session
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rad = Math.PI / 180;
  const clampv = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  // Data (m) to the unit box: x, y in [-1, 1], z in [-0.9, 0.9].
  const lim = () => ({ x: FIG1.vtl, y: FIG1.b, z: FIG1.vtu });
  function norm(x, y, z) {
    const L = lim();
    const n = (v, [a, b]) => (2 * (v - a)) / (b - a) - 1;
    return [n(x, L.x), n(y, L.y), ASPECT_Z * n(z, L.z)];
  }

  // The seven cells as [code, [x0, x1], [y0, y1], [z0, z1]] in m,
  // phase_space_3d.class_cells.
  function cells() {
    const { x: [xa, xb], y: [ya, yb], z: [za, zb] } = lim();
    const B = FIG1.onset;
    return [
      [0, [0, xb], [ya, B], [0, zb]],
      [1, [0, xb], [ya, B], [za, 0]],
      [2, [0, xb], [B, yb], [0, zb]],
      [3, [0, xb], [B, yb], [za, 0]],
      [4, [xa, 0], [B, yb], [za, 0]],
      [5, [xa, 0], [ya, B], [za, 0]],
      [6, [xa, 0], [ya, yb], [0, zb]],
    ];
  }

  // Where each dividing plane meets the box, only where it separates two
  // classes (phase_space_3d.dividing_plane_outlines): B = 10 m is L-shaped,
  // since class 6 spans both sides of it.
  function planes() {
    const { x: [xa, xb], y: [ya, yb], z: [za, zb] } = lim();
    const B = FIG1.onset;
    return [
      [[0, ya, za], [0, yb, za], [0, yb, zb], [0, ya, zb], [0, ya, za]],
      [[xa, ya, 0], [xb, ya, 0], [xb, yb, 0], [xa, yb, 0], [xa, ya, 0]],
      [[0, B, zb], [xb, B, zb], [xb, B, za], [xa, B, za], [xa, B, 0], [0, B, 0], [0, B, zb]],
    ];
  }

  // Where a cell's class number may go, best first: its centroid in -V_T^L
  // and -V_T^U, pushed along B toward its outer B face
  // (phase_space_3d.label_position), then a 3 x 3 x 3 lattice inside the
  // cell by distance from that point (as place_cell_labels, which keeps
  // the numbers clear of the paths and of each other).
  function labelSpots(c, [x0, x1], [y0, y1], [z0, z1]) {
    const [ya, yb] = lim().y;
    let y = (y0 + y1) / 2;
    if (c !== 6) y = y1 <= FIG1.onset ? y0 + 0.1 * (yb - ya) : y1 - 0.1 * (yb - ya);
    const first = [(x0 + x1) / 2, y, (z0 + z1) / 2];
    const fr = [0.2, 0.5, 0.8];
    const rel = (p) => [(p[0] - x0) / (x1 - x0), (p[1] - y0) / (y1 - y0), (p[2] - z0) / (z1 - z0)];
    const r0 = rel(first);
    const out = [];
    for (const a of fr) for (const b of fr) for (const e of fr) out.push([x0 + a * (x1 - x0), y0 + b * (y1 - y0), z0 + e * (z1 - z0)]);
    const dist = (p) => { const r = rel(p); return Math.hypot(r[0] - r0[0], r[1] - r0[1], r[2] - r0[2]); };
    out.sort((p, q) => dist(p) - dist(q));
    return [first, ...out];
  }

  /* ---------- text with the thermal wind symbols ---------- */

  // parts: strings and {v: 'L' | 'U'} for -V_T^L and -V_T^U, the T and the
  // L or U stacked as sub- and superscript.
  function richWidth(ctx, parts, size) {
    let w = 0;
    for (const p of parts) {
      if (typeof p === 'string') { ctx.font = `${size}px ${FONT.sans}`; w += ctx.measureText(p).width; continue; }
      ctx.font = `${size}px ${FONT.sans}`;
      w += ctx.measureText(`${MINUS}V`).width;
      ctx.font = `${Math.round(size * 0.72)}px ${FONT.sans}`;
      w += Math.max(ctx.measureText('T').width, ctx.measureText(p.v).width) + 1;
    }
    return w;
  }
  function drawRich(ctx, parts, x, y, align, size, color) {
    const w = richWidth(ctx, parts, size);
    let cx = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    ctx.textAlign = 'left';
    ctx.fillStyle = color;
    for (const p of parts) {
      ctx.font = `${size}px ${FONT.sans}`;
      if (typeof p === 'string') { ctx.fillText(p, cx, y); cx += ctx.measureText(p).width; continue; }
      const head = `${MINUS}V`;
      ctx.fillText(head, cx, y);
      cx += ctx.measureText(head).width;
      const s = Math.round(size * 0.72);
      ctx.font = `${s}px ${FONT.sans}`;
      ctx.fillText('T', cx + 0.5, y + s * 0.42);
      ctx.fillText(p.v, cx + 0.5, y - s * 0.62);
      cx += Math.max(ctx.measureText('T').width, ctx.measureText(p.v).width) + 1;
    }
    return w;
  }

  const FONT = { sans: '"IBM Plex Sans", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif', mono: '"IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace' };
  const TITLE = {
    x: ['Lower thermal wind (', { v: 'L' }, ')'],
    y: ['Thermal asymmetry (B)'],
    z: ['Upper thermal wind (', { v: 'U' }, ')'],
  };
  const TICKS = {
    x: { every: [-300, -200, -100, 0, 100, 200, 300], label: [-300, 0, 300] },
    y: { every: [-20, 0, 10, 20, 40, 60, 80], label: [-20, 10, 40, 80] },
    z: { every: [-300, -200, -100, 0, 100, 200, 300], label: [-300, 0, 300] },
  };

  /* ---------- one view ---------- */

  function create(host, s) {
    const css = getComputedStyle(document.documentElement);
    const C = {
      text: css.getPropertyValue('--text').trim() || '#e9e8e3',
      muted: css.getPropertyValue('--muted').trim() || '#a8a6a0',
      faint: css.getPropertyValue('--faint').trim() || '#94928c',
      bg: css.getPropertyValue('--raise').trim() || '#222328',
    };
    const wrap = document.createElement('div');
    wrap.className = 's3d';
    const hintId = `s3d-hint-${String(s.key).replace(/[^\w-]/g, '_')}`;
    wrap.innerHTML = `<p class="s3d-read" aria-live="off"></p>
      <canvas class="s3d-canvas" tabindex="0" role="img"></canvas>
      <ul class="s3d-key"></ul>
      <p class="s3d-note" id="${hintId}">Cells cut by B = 10&nbsp;m, ${TERM.hvtl.sym} = 0 and ${TERM.hvtu.sym} = 0; class 6 spans both sides of B = 10&nbsp;m. Values in m.
        Drag to rotate, double click to reset; once selected, the wheel zooms and the arrow keys rotate. Click a dot for its hour.</p>`;
    host.append(wrap);
    const canvas = wrap.querySelector('canvas');
    const read = wrap.querySelector('.s3d-read');
    canvas.setAttribute('aria-label', `${s.label}, track in the three-dimensional phase space: lower thermal wind across, thermal asymmetry in depth, upper thermal wind up`);
    canvas.setAttribute('aria-describedby', hintId);
    const key = wrap.querySelector('.s3d-key');
    for (let c = 0; c < 7; c++) {
      const li = document.createElement('li');
      li.innerHTML = `<i style="--c:${cls(c).hex}"></i><b>${c}</b><span></span>`;
      li.querySelector('span').textContent = SHORT[c];
      li.title = cls(c).name;
      key.append(li);
    }

    let W = 0;           // CSS px, square
    let dpr = 1;
    let pending = 0;
    let hover = -1;      // frame index of the dot under the pointer
    let proj = [];       // [{k, x, y}] of the drawn dots, for picking
    let tween = 0;
    let gone = false;

    const ctx = canvas.getContext('2d');

    function size() {
      const w = Math.round(wrap.clientWidth);
      const d = window.devicePixelRatio || 1;
      if (!w || (w === W && d === dpr)) return;
      W = w;
      dpr = d;
      canvas.style.height = `${W}px`;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(W * dpr);
      draw();
    }
    const ro = new ResizeObserver(size);
    ro.observe(wrap);
    let mq = null;
    const onDpr = () => { armDpr(); size(); };
    function armDpr() {
      mq?.removeEventListener('change', onDpr);
      mq = matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
      mq.addEventListener('change', onDpr);
    }
    armDpr();
    document.fonts?.ready.then(() => { if (!gone) schedule(); });

    function schedule() {
      if (pending || gone) return;
      pending = requestAnimationFrame(() => { pending = 0; draw(); });
    }

    // The camera for this draw: screen x, screen y (up), depth (toward the eye).
    function camera() {
      const a = cam.az * rad;
      const e = cam.el * rad;
      const ca = Math.cos(a), sa = Math.sin(a), ce = Math.cos(e), se = Math.sin(e);
      const k = 0.285 * W * cam.zoom;
      const cx = W / 2;
      const cy = 0.4 * W;
      const eye = [ce * ca, ce * sa, se];
      const P = ([X, Y, Z]) => {
        const sx = -sa * X + ca * Y;
        const sy = -se * ca * X - se * sa * Y + ce * Z;
        const d = eye[0] * X + eye[1] * Y + eye[2] * Z;
        const f = DIST / (DIST - d);
        return { x: cx + k * f * sx, y: cy - k * f * sy, d, f };
      };
      return { P, eye };
    }

    function draw() {
      if (!W || gone) return;
      const { P, eye } = camera();
      const N = (x, y, z) => P(norm(x, y, z));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, W);
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      const L = lim();
      const line = (pts, color, w) => {
        ctx.beginPath();
        pts.forEach((p, j) => (j ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.strokeStyle = color;
        ctx.lineWidth = w;
        ctx.stroke();
      };

      // Far panes: the walls opposite the eye, with a faint grid at the ticks.
      const far = { x: eye[0] >= 0 ? L.x[0] : L.x[1], y: eye[1] >= 0 ? L.y[0] : L.y[1], z: eye[2] >= 0 ? L.z[0] : L.z[1] };
      const grid = 'rgba(233,232,227,0.07)';
      for (const v of TICKS.y.every) { line([N(far.x, v, L.z[0]), N(far.x, v, L.z[1])], grid, 1); line([N(L.x[0], v, far.z), N(L.x[1], v, far.z)], grid, 1); }
      for (const v of TICKS.x.every) { line([N(v, far.y, L.z[0]), N(v, far.y, L.z[1])], grid, 1); line([N(v, L.y[0], far.z), N(v, L.y[1], far.z)], grid, 1); }
      for (const v of TICKS.z.every) { line([N(far.x, L.y[0], v), N(far.x, L.y[1], v)], grid, 1); line([N(L.x[0], far.y, v), N(L.x[1], far.y, v)], grid, 1); }

      // Cells: every face of every cell, back to front.
      const faces = [];
      const cellList = cells();
      for (const [c, [x0, x1], [y0, y1], [z0, z1]] of cellList) {
        const v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]].map((p) => N(...p));
        for (const f of [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 3, 7, 4]]) {
          const q = f.map((j) => v[j]);
          faces.push({ q, d: q.reduce((a, p) => a + p.d, 0) / 4, hex: cls(c).hex });
        }
      }
      faces.sort((a, b) => a.d - b.d);
      for (const { q, hex } of faces) {
        ctx.beginPath();
        q.forEach((p, j) => (j ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.closePath();
        ctx.fillStyle = rgba(hex, FACE_A);
        ctx.fill();
      }

      // Box edges, the far ones fainter; then the dividing planes.
      const farv = [far.x, far.y, far.z];
      const corners = [];
      for (const x of L.x) for (const y of L.y) for (const z of L.z) corners.push([x, y, z]);
      for (let a = 0; a < 8; a++) {
        for (let b = a + 1; b < 8; b++) {
          const diff = [0, 1, 2].filter((j) => corners[a][j] !== corners[b][j]).length;
          if (diff !== 1) continue;
          const [p, q] = [N(...corners[a]), N(...corners[b])];
          // Behind everything: both of the edge's fixed coordinates on far panes.
          const back = [0, 1, 2].every((j) => corners[a][j] !== corners[b][j] || corners[a][j] === farv[j]);
          line([p, q], back ? 'rgba(233,232,227,0.16)' : 'rgba(233,232,227,0.3)', 1);
        }
      }
      for (const pl of planes()) line(pl.map((p) => N(...p)), 'rgba(233,232,227,0.42)', 1);

      // Class numbers, with a halo of the panel color.
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.font = `600 ${W < 330 ? 12 : 13}px ${FONT.sans}`;
      ctx.lineWidth = 3;
      ctx.strokeStyle = rgba(C.bg, 0.85);
      const pts = trackPoints(N);
      const avoid = [];
      for (let k = 0; k < pts.length; k++) {
        const a = pts[k];
        if (!a) continue;
        avoid.push(a);
        const b = pts[k + 1];
        if (b) for (const t of [0.25, 0.5, 0.75]) avoid.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
      }
      const nums = [];
      for (const [c, ...box] of cellList) {
        const spots = labelSpots(c, ...box).map((q) => N(...q));
        const clear = (p) => nums.every((q) => Math.hypot(p.x - q.x, p.y - q.y) >= 26) &&
          avoid.every((q) => Math.hypot(p.x - q.x, p.y - q.y) >= 12);
        const p = spots.find(clear) || spots.find((q) => nums.every((n) => Math.hypot(q.x - n.x, q.y - n.y) >= 26)) || spots[0];
        nums.push(p);
        ctx.strokeText(String(c), p.x, p.y);
        ctx.fillStyle = cls(c).hex;
        ctx.fillText(String(c), p.x, p.y);
      }

      drawAxes(N, far);
      drawAxes.placed.push(...nums.map((p) => [p.x - 5, p.y - 7, p.x + 5, p.y + 7]));
      drawTrack(pts);
      readout();
    }

    // Axes on the near bottom edges (x and B) and the right-hand vertical
    // edge (as the article's panel a), ticks and labels outward.
    function drawAxes(N, far) {
      const L = lim();
      const zE = cam.el >= 0 ? L.z[0] : L.z[1];
      const yN = far.y === L.y[0] ? L.y[1] : L.y[0];
      const xN = far.x === L.x[0] ? L.x[1] : L.x[0];
      const mid = N((L.x[0] + L.x[1]) / 2, (L.y[0] + L.y[1]) / 2, (L.z[0] + L.z[1]) / 2);
      // The vertical edge furthest right on screen.
      let zx = L.x[0], zy = L.y[0], best = -Infinity;
      for (const x of L.x) for (const y of L.y) { const p = N(x, y, 0); if (p.x > best) { best = p.x; zx = x; zy = y; } }
      const axes = {
        x: { at: (v) => [v, yN, zE] },
        y: { at: (v) => [xN, v, zE] },
        z: { at: (v) => [zx, zy, v] },
      };
      const placed = [];
      ctx.lineWidth = 1;
      // The vertical axis before B, so that B gives way where they meet.
      for (const ax of ['x', 'z', 'y']) {
        const A = axes[ax];
        const lo = N(...A.at(L[ax][0]));
        const hi = N(...A.at(L[ax][1]));
        // Outward: from the box center's projection, perpendicular to the edge on screen.
        let ex = hi.x - lo.x, ey = hi.y - lo.y;
        const el = Math.hypot(ex, ey) || 1;
        const endOn = el < 72;  // seen nearly end on: ticks only, no labels
        ex /= el; ey /= el;
        let ox = -ey, oy = ex;
        const m = { x: (lo.x + hi.x) / 2, y: (lo.y + hi.y) / 2 };
        if ((m.x - mid.x) * ox + (m.y - mid.y) * oy < 0) { ox = -ox; oy = -oy; }
        ctx.strokeStyle = 'rgba(233,232,227,0.5)';
        ctx.beginPath(); ctx.moveTo(lo.x, lo.y); ctx.lineTo(hi.x, hi.y); ctx.stroke();
        ctx.font = `9.5px ${FONT.mono}`;
        ctx.fillStyle = C.faint;
        ctx.textAlign = ox < -0.35 ? 'right' : ox > 0.35 ? 'left' : 'center';
        ctx.textBaseline = oy < -0.35 ? 'bottom' : oy > 0.35 ? 'top' : 'middle';
        let reach = 0;
        for (const v of TICKS[ax].every) {
          const p = N(...A.at(v));
          const major = TICKS[ax].label.includes(v);
          ctx.strokeStyle = ax === 'y' && v === FIG1.onset ? 'rgba(233,232,227,0.8)' : 'rgba(233,232,227,0.45)';
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + ox * (major ? 4 : 2.5), p.y + oy * (major ? 4 : 2.5)); ctx.stroke();
          if (!major || endOn) continue;
          const t = fmt(v);
          const tx = p.x + ox * 7;
          const ty = p.y + oy * 7;
          const w = ctx.measureText(t).width;
          const r = box(tx, ty, w, 11, ctx.textAlign, ctx.textBaseline);
          if (placed.some((q) => overlap(q, r, q.ax === ax ? 2 : 8))) continue;
          r.ax = ax;
          placed.push(r);
          ctx.fillText(t, tx, ty);
          reach = Math.max(reach, Math.abs(ox) * w + Math.abs(oy) * 11);
        }
        // The title beyond the tick labels.
        if (endOn) continue;
        const size = 10;
        const off = 7 + reach + 5;
        ctx.textBaseline = 'middle';
        // An edge steeper than 45 degrees on screen gets its title turned along it.
        if (Math.abs(ey) > Math.abs(ex)) {
          const w = richWidth(ctx, TITLE[ax], size);
          const tx = clampv(m.x + ox * (off + 6), 8, W - 8);
          const ty = clampv(m.y + oy * (off + 6), w / 2 + 4, W - w / 2 - 4);
          const r = [tx - 7, ty - w / 2, tx + 7, ty + w / 2];
          if (placed.some((q) => overlap(q, r, 2))) continue;
          ctx.save();
          ctx.translate(tx, ty);
          ctx.rotate(ox >= 0 ? Math.PI / 2 : -Math.PI / 2);
          drawRich(ctx, TITLE[ax], 0, 0, 'center', size, C.muted);
          ctx.restore();
          placed.push(r);
        } else {
          const w = richWidth(ctx, TITLE[ax], size);
          const align = ox < -0.3 ? 'right' : ox > 0.3 ? 'left' : 'center';
          let tx = m.x + ox * (off + 4);
          let ty = m.y + oy * (off + 8);
          const left = align === 'right' ? tx - w : align === 'center' ? tx - w / 2 : tx;
          tx += clampv(left, 4, W - 4 - w) - left;
          ty = clampv(ty, 8, W - 8);
          let r = box(tx, ty, w, 14, align, 'middle');
          for (let n = 0; n < 3 && placed.some((q) => overlap(q, r, 2)); n++) { ty += oy >= 0 ? 8 : -8; r = box(tx, ty, w, 14, align, 'middle'); }
          if (placed.some((q) => overlap(q, r, 2)) || r[1] < 0 || r[3] > W) continue;
          placed.push(r);
          drawRich(ctx, TITLE[ax], tx, ty, align, size, C.muted);
        }
      }
      drawAxes.placed = placed;
    }

    // The track: segments by class, dots, start and end, labels every 24 h, the ring.
    // Each hour's point on screen, null where a value is missing; values
    // beyond the box are held on its wall and flagged.
    function trackPoints(N) {
      const L = lim();
      return s.at.map((e, k) => {
        if (!e || blank(e.hvtl) || blank(e.hvtu) || blank(e.hb)) return null;
        const x = clampv(+e.hvtl, ...L.x), y = clampv(+e.hb, ...L.y), z = clampv(+e.hvtu, ...L.z);
        const p = N(x, y, z);
        return { k, ...p, hex: cls(e.cls).hex, clipped: x !== +e.hvtl || y !== +e.hb || z !== +e.hvtu };
      });
    }

    function drawTrack(pts) {
      const hours = S.index.hours;
      const live = pts.filter(Boolean);
      proj = live;
      if (!live.length) {
        ctx.font = `11px ${FONT.sans}`;
        ctx.fillStyle = C.muted;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(ST.built ? 'No point of this track has all three values.' : 'Loading the values of this track', W / 2, 14);
        return;
      }
      // Segments between consecutive hours, a dark casing under each.
      const segs = [];
      for (let k = 0; k + 1 < pts.length; k++) if (pts[k] && pts[k + 1]) segs.push([pts[k], pts[k + 1]]);
      ctx.lineCap = 'round';
      for (const [a, b] of segs) {
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = 'rgba(13,13,15,0.75)'; ctx.lineWidth = 3.5; ctx.stroke();
      }
      for (const [a, b] of segs) {
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = a.hex; ctx.lineWidth = 1.75; ctx.stroke();
      }
      const r0 = W < 330 ? 2.4 : 2.7;
      for (const p of [...live].sort((a, b) => a.d - b.d)) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, r0 * p.f, 0, 2 * Math.PI);
        ctx.fillStyle = p.clipped ? rgba(C.bg, 1) : p.hex;
        ctx.fill();
        ctx.lineWidth = p.clipped ? 1.25 : 0.75;
        ctx.strokeStyle = p.clipped ? p.hex : '#0d0d0f';
        ctx.stroke();
      }
      // Start: an open square. End: an arrowhead along the last step.
      const first = live[0];
      const last = live[live.length - 1];
      ctx.strokeStyle = C.text;
      ctx.lineWidth = 1.25;
      ctx.strokeRect(first.x - 5, first.y - 5, 10, 10);
      if (last !== first) {
        const prev = live[live.length - 2];
        let dx = last.x - prev.x, dy = last.y - prev.y;
        const dl = Math.hypot(dx, dy);
        if (dl > 0.5) {
          dx /= dl; dy /= dl;
          const tip = { x: last.x + dx * 11, y: last.y + dy * 11 };
          const base = { x: last.x + dx * 4, y: last.y + dy * 4 };
          ctx.beginPath();
          ctx.moveTo(tip.x, tip.y);
          ctx.lineTo(base.x - dy * 3.5, base.y + dx * 3.5);
          ctx.lineTo(base.x + dy * 3.5, base.y - dx * 3.5);
          ctx.closePath();
          ctx.fillStyle = C.text;
          ctx.fill();
        } else {
          ctx.beginPath(); ctx.arc(last.x, last.y, 6, 0, 2 * Math.PI); ctx.stroke();
        }
      }
      // Hour labels: start and end first, then every 24 h where there is room.
      const placed = [...(drawAxes.placed || [])];
      const dots = live.map((p) => [p.x - 3, p.y - 3, p.x + 3, p.y + 3]);
      for (let k = 0; k + 1 < pts.length; k++) {
        const a = pts[k], b = pts[k + 1];
        if (!a || !b) continue;
        for (const t of [0.2, 0.4, 0.6, 0.8]) { const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t; dots.push([x - 1, y - 1, x + 1, y + 1]); }
      }
      const want = [first, last, ...live.filter((p) => p !== first && p !== last && hours[p.k] % 24 === 0)];
      const seen = new Set();
      for (const p of want) {
        if (seen.has(p)) continue;
        seen.add(p);
        const end = p === first || p === last;
        const t = `F${pad(hours[p.k], 3)}`;
        ctx.font = `${end ? 500 : 400} 9.5px ${FONT.mono}`;
        const w = ctx.measureText(t).width;
        const spots = [[p.x + 7, p.y - 7, 'left', 'bottom'], [p.x - 7, p.y - 7, 'right', 'bottom'],
          [p.x + 7, p.y + 7, 'left', 'top'], [p.x - 7, p.y + 7, 'right', 'top']];
        let spot = null;
        // The start and end are labelled even over the track, if not over another label.
        for (const loose of end ? [false, true] : [false]) {
          for (const sp of spots) {
            const r = box(sp[0], sp[1], w, 11, sp[2], sp[3]);
            if (r[0] < 2 || r[2] > W - 2 || r[1] < 2 || r[3] > W - 2) continue;
            if (placed.some((q) => overlap(q, r, 1)) || (!loose && dots.some((q) => overlap(q, r, 0)))) continue;
            spot = [sp, r];
            break;
          }
          if (spot) break;
        }
        if (!spot) continue;
        placed.push(spot[1]);
        const [x, y, al, bl] = spot[0];
        ctx.textAlign = al;
        ctx.textBaseline = bl;
        ctx.lineWidth = 3;
        ctx.strokeStyle = rgba(C.bg, 0.85);
        ctx.strokeText(t, x, y);
        ctx.fillStyle = end ? C.text : C.muted;
        ctx.fillText(t, x, y);
      }
      // The hour on screen, and the dot under the pointer.
      const cur = pts[S.i];
      if (cur) {
        ctx.beginPath();
        ctx.arc(cur.x, cur.y, 6.5 * cur.f, 0, 2 * Math.PI);
        ctx.lineWidth = 1.75;
        ctx.strokeStyle = C.text;
        ctx.stroke();
      }
      const hv = hover >= 0 ? pts[hover] : null;
      if (hv && hv !== cur) {
        ctx.beginPath();
        ctx.arc(hv.x, hv.y, 5.5 * hv.f, 0, 2 * Math.PI);
        ctx.lineWidth = 1;
        ctx.strokeStyle = C.muted;
        ctx.stroke();
      }
    }

    // The line above the view: the hour on screen (or the hovered one), its class and values.
    function readout() {
      const k = hover >= 0 ? hover : S.i;
      const e = s.at[k];
      const h = `F${pad(S.index.hours[k], 3)}`;
      const term = (f, d) => `<span class="s3d-t">${TERM[f].sym} <b>${fmt(e[f], d, '', true)}</b></span>`;
      const html = e
        ? `<span class="s3d-h">${h}${hover >= 0 && hover !== S.i ? ' <span class="s3d-at">under the pointer</span>' : ''}</span>` +
          `<span class="s3d-c"><i style="--c:${cls(e.cls).hex}"></i>${esc(e.cls == null ? 'no class' : SHORT[e.cls] ?? cls(e.cls).name)}</span>` +
          `<span class="s3d-v">${term('hvtl', 0)}${term('hvtu', 0)}${term('hb', 1)}<span class="s3d-u">m</span></span>`
        : `<span class="s3d-h">${h}</span><span class="s3d-c muted">not tracked at this hour</span>`;
      if (read.innerHTML !== html) read.innerHTML = html;
    }

    /* ---------- interaction ---------- */

    const ptrs = new Map();
    let drag = null;
    let pinch = null;
    let lastTap = null;

    function setCam(az, el, zoom = cam.zoom) {
      cam.az = ((((az + 180) % 360) + 360) % 360) - 180;
      cam.el = clampv(el, ...EL);
      cam.zoom = clampv(zoom, ...ZOOM);
      schedule();
    }

    function reset() {
      cancelAnimationFrame(tween);
      if (reduce()) { setCam(DEFAULT.az, DEFAULT.el, DEFAULT.zoom); return; }
      const from = { ...cam };
      const daz = ((((DEFAULT.az - from.az) + 540) % 360) - 180);
      const t0 = performance.now();
      const step = (t) => {
        const u = Math.min(1, (t - t0) / 260);
        const q = u * (2 - u);
        setCam(from.az + daz * q, from.el + (DEFAULT.el - from.el) * q, from.zoom + (DEFAULT.zoom - from.zoom) * q);
        if (u < 1) tween = requestAnimationFrame(step);
      };
      tween = requestAnimationFrame(step);
    }

    const local = (e) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    function pick(x, y) {
      let best = -1, bd = 9;
      for (const p of proj) {
        const d = Math.hypot(p.x - x, p.y - y);
        if (d < bd) { bd = d; best = p.k; }
      }
      return best;
    }

    canvas.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      cancelAnimationFrame(tween);
      canvas.setPointerCapture(e.pointerId);
      const p = local(e);
      ptrs.set(e.pointerId, p);
      if (ptrs.size === 1) {
        drag = { ...p, az: cam.az, el: cam.el, moved: false };
      } else if (ptrs.size === 2) {
        const [a, b] = [...ptrs.values()];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, zoom: cam.zoom };
        drag = null;
      }
      canvas.classList.add('grabbing');
    });
    canvas.addEventListener('pointermove', (e) => {
      const p = local(e);
      if (!ptrs.has(e.pointerId)) {
        if (e.pointerType !== 'mouse') return;
        const k = pick(p.x, p.y);
        canvas.classList.toggle('on-dot', k >= 0);
        if (k !== hover) { hover = k; schedule(); }
        return;
      }
      ptrs.set(e.pointerId, p);
      if (pinch && ptrs.size >= 2) {
        const [a, b] = [...ptrs.values()];
        setCam(cam.az, cam.el, pinch.zoom * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.d));
      } else if (drag) {
        const dx = p.x - drag.x, dy = p.y - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) < 4) return;
        drag.moved = true;
        setCam(drag.az - dx * 0.5, drag.el + dy * 0.5);
      }
    });
    const up = (e) => {
      if (!ptrs.has(e.pointerId)) return;
      ptrs.delete(e.pointerId);
      const p = local(e);
      if (e.type === 'pointerup' && drag && !drag.moved && !pinch) {
        const k = pick(p.x, p.y);
        const now = performance.now();
        if (e.pointerType !== 'mouse' && lastTap && now - lastTap.t < 320 && Math.hypot(p.x - lastTap.x, p.y - lastTap.y) < 24) {
          lastTap = null;
          reset();
        } else {
          lastTap = { t: now, ...p };
          if (k >= 0 && k !== S.i) { play(false); show(k); }
        }
      }
      if (ptrs.size < 2) pinch = null;
      if (!ptrs.size) { drag = null; canvas.classList.remove('grabbing'); }
      else if (ptrs.size === 1) { const [q] = ptrs.values(); drag = { ...q, az: cam.az, el: cam.el, moved: true }; }
    };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    canvas.addEventListener('pointerleave', (e) => {
      if (e.pointerType === 'mouse' && hover >= 0 && !ptrs.size) { hover = -1; canvas.classList.remove('on-dot'); schedule(); }
    });
    canvas.addEventListener('dblclick', (e) => { e.preventDefault(); reset(); });
    // The wheel zooms only once the view has focus (else it scrolls the
    // panel); a trackpad pinch (ctrlKey) always zooms.
    canvas.addEventListener('wheel', (e) => {
      if (!e.ctrlKey && document.activeElement !== canvas) return;
      e.preventDefault();
      const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      setCam(cam.az, cam.el, cam.zoom * Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)));
    }, { passive: false });
    canvas.addEventListener('keydown', (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const st = e.shiftKey ? 15 : 5;
      const act = {
        ArrowLeft: () => setCam(cam.az + st, cam.el),
        ArrowRight: () => setCam(cam.az - st, cam.el),
        ArrowUp: () => setCam(cam.az, cam.el + st),
        ArrowDown: () => setCam(cam.az, cam.el - st),
        '+': () => setCam(cam.az, cam.el, cam.zoom * 1.1),
        '=': () => setCam(cam.az, cam.el, cam.zoom * 1.1),
        '-': () => setCam(cam.az, cam.el, cam.zoom / 1.1),
        0: reset,
        Home: reset,
      }[e.key];
      if (!act) return;
      e.preventDefault();
      act();
    });

    size();
    return {
      el: wrap,
      frame() { schedule(); },
      destroy() {
        gone = true;
        cancelAnimationFrame(pending);
        cancelAnimationFrame(tween);
        ro.disconnect();
        mq?.removeEventListener('change', onDpr);
        wrap.remove();
      },
    };
  }

  // A text box [x0, y0, x1, y1] for an anchor, alignment and baseline.
  function box(x, y, w, h, align, base) {
    const x0 = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;
    const y0 = base === 'bottom' ? y - h : base === 'middle' ? y - h / 2 : y;
    return [x0, y0, x0 + w, y0 + h];
  }
  const overlap = (a, b, g) => a[0] - g < b[2] && a[2] + g > b[0] && a[1] - g < b[3] && a[3] + g > b[1];

  return { create };
})();
