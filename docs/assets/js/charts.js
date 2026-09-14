/* Minimal SVG charting: column, histogram and scatter, drawn straight into the
   DOM. No chart library - the whole site is plain scripts on a static host.

   Everything is drawn into a fixed viewBox and scaled by CSS, so the charts
   stay crisp at any width without resize handling. Colours come from CSS
   custom properties so the light and dark palettes both apply. */

window.HF = window.HF || {};

(function (charts, HF) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var H = 260;                                  // default plot height, px
  var PAD = { top: 14, right: 14, bottom: 38, left: 46 };
  var MIN_W = 280;

  // Charts are drawn at the container's real pixel width rather than into one
  // fixed viewBox scaled by CSS: a shared viewBox makes 10 px axis text render
  // at 6 px in a narrow card and 18 px in a full-width one.
  function widthOf(container) {
    var w = container.clientWidth || container.parentNode.clientWidth || 640;
    return Math.max(MIN_W, Math.floor(w));
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS(NS, tag);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  function frame(container, height) {
    HF.clear(container);
    var h = height || H;
    var w = widthOf(container);
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + w + ' ' + h,
      width: w, height: h,
      preserveAspectRatio: 'xMinYMin meet',
      role: 'img'
    });
    svg.style.width = '100%';
    svg.style.height = h + 'px';
    container.appendChild(svg);
    return { svg: svg, w: w, h: h,
             plotW: w - PAD.left - PAD.right, plotH: h - PAD.top - PAD.bottom };
  }

  /** Sized to match the chart it stands in for, so switching a filter on and
      off doesn't jolt the card's height, with a quiet dashed marker so an
      empty result reads as "confirmed: nothing here" rather than a glitch. */
  function empty(container, message, height) {
    HF.clear(container);
    var box = HF.el('div', { class: 'chart-empty', style: 'min-height:' + (height || H) + 'px' });
    box.appendChild(HF.el('p', {}, message || 'No events match the current filters.'));
    container.appendChild(box);
  }

  /** Round a maximum up to a readable axis top, and pick a tick step aimed at
      roughly `ticks` gridlines (default 5). */
  function niceStep(range, ticks) {
    if (range <= 0) return 1;
    var raw = range / Math.max(1, ticks || 5);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  }

  function niceScale(max, ticks) {
    if (max <= 0) return { max: 1, step: 1 };
    var step = niceStep(max, ticks);
    return { max: Math.ceil(max / step) * step, step: step };
  }

  // Text-width measurement so tick density can adapt to the chart's real
  // pixel width instead of a fixed "every Nth label" rule that overlaps on a
  // narrow card and leaves a wide one sparser than it needs to be.
  var measureCtx = null;
  function textWidth(str, sizePx, weight) {
    if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
    measureCtx.font = (weight || 400) + ' ' + (sizePx || 10.5) + 'px ' + (HF.cssVar('--font') || 'sans-serif');
    return measureCtx.measureText(String(str)).width;
  }

  /** How many of `n` evenly-spaced labels of (up to) `labelPx` width fit in
      `availPx` without touching; returns a step so every step-th is shown. */
  function tickStep(n, labelPx, availPx, gapPx) {
    var perTick = availPx / Math.max(1, n);
    return Math.max(1, Math.ceil((labelPx + (gapPx || 6)) / perTick));
  }

  function yAxis(g, scale, plotH, plotW, fmt) {
    for (var v = 0; v <= scale.max + 1e-9; v += scale.step) {
      var y = PAD.top + plotH - (v / scale.max) * plotH;
      g.appendChild(svgEl('line', {
        class: v === 0 ? 'c-axis' : 'c-grid',
        x1: PAD.left, x2: PAD.left + plotW, y1: y, y2: y
      }));
      var label = svgEl('text', { class: 'c-tick', x: PAD.left - 7, y: y + 3.5, 'text-anchor': 'end' });
      label.textContent = fmt ? fmt(v) : String(Math.round(v * 100) / 100);
      g.appendChild(label);
    }
  }

  // maxWidth (optional): shrink the font just enough to fit a long caption
  // into a narrow card instead of letting it spill over the card edge -
  // some captions ("Bergerons over the best 18-24 h window...") are long
  // enough that at 11px they overflow a ~330px card.
  function axisTitle(g, text, x, y, anchor, rotate, maxWidth) {
    var node = svgEl('text', {
      class: 'c-axis-title', x: x, y: y, 'text-anchor': anchor || 'middle'
    });
    if (rotate) node.setAttribute('transform', 'rotate(-90 ' + x + ' ' + y + ')');
    node.textContent = text;
    if (maxWidth) {
      var tw = textWidth(text, 11, 600);
      // An inline style, not a presentation attribute: .c-axis-title's own
      // font-size in app.css otherwise wins the cascade over an attribute.
      if (tw > maxWidth) node.style.fontSize = Math.max(8, 11 * (maxWidth / tw)).toFixed(1) + 'px';
    }
    g.appendChild(node);
  }

  function legend(container, series) {
    var box = HF.el('p', { class: 'chart-legend' });
    series.forEach(function (s) {
      var span = HF.el('span');
      var swatch = HF.el('i');
      swatch.style.background = s.color;
      span.appendChild(swatch);
      span.appendChild(document.createTextNode(s.label));
      box.appendChild(span);
    });
    container.appendChild(box);
  }

  function attachTip(node, html) {
    node.addEventListener('mouseenter', function (e) { HF.showTip(html, e); });
    node.addEventListener('mousemove', HF.moveTip);
    node.addEventListener('mouseleave', HF.hideTip);
  }

  /** Wires one interactive slot (a column or a histogram bin): dims every
      other group's bars, lights up this one, slides a crosshair to it, and
      shows the tooltip - all from a single hit rect. `groups` is a flat
      array of bar-element arrays, one per slot, so a stacked column's whole
      stack highlights together. */
  function hookHover(hit, groups, idx, crosshair, cx, top, bottom, html) {
    hit.addEventListener('mouseenter', function (e) {
      for (var j = 0; j < groups.length; j++) {
        var dim = j !== idx;
        for (var k = 0; k < groups[j].length; k++) groups[j][k].classList.toggle('is-dim', dim);
      }
      if (crosshair) {
        crosshair.setAttribute('x1', cx); crosshair.setAttribute('x2', cx);
        crosshair.setAttribute('y1', top); crosshair.setAttribute('y2', bottom);
        crosshair.classList.add('is-visible');
      }
      HF.showTip(html, e);
    });
    hit.addEventListener('mousemove', HF.moveTip);
    hit.addEventListener('mouseleave', function () {
      for (var j = 0; j < groups.length; j++) {
        for (var k = 0; k < groups[j].length; k++) groups[j][k].classList.remove('is-dim');
      }
      if (crosshair) crosshair.classList.remove('is-visible');
      HF.hideTip();
    });
  }

  /* -------------------------------------------------------------- columns */

  /**
   * Stacked column chart.
   * spec: {data:[{label, tick, tickRotate, parts:{key:count}, total, tip, season}],
   *        series:[{key,label,color}], yTitle, xTitle, meanLine:{value,label}, onClick}
   */
  charts.columns = function (container, spec) {
    if (!spec.data.length) return empty(container);
    var f = frame(container);
    var g = svgEl('g', {});
    f.svg.appendChild(g);

    var max = Math.max.apply(null, spec.data.map(function (d) { return d.total; }));
    var scale = niceScale(max);
    yAxis(g, scale, f.plotH, f.plotW);

    var slot = f.plotW / spec.data.length;
    var barW = Math.max(3, Math.min(slot - 3, 34));

    // Tick density adapts to the real pixel width: measure the widest tick
    // label and thin (or, if still tight, rotate) so labels never collide.
    var maxTickW = 0;
    spec.data.forEach(function (d) { if (d.tick) maxTickW = Math.max(maxTickW, textWidth(d.tick, 10.5)); });
    var wantsRotate = spec.data.some(function (d) { return d.tickRotate; });
    var rotate = wantsRotate || (maxTickW + 8 > slot && slot < 46);
    var step = tickStep(spec.data.length, rotate ? 12 : maxTickW, f.plotW, rotate ? 3 : 8);
    var canLabelTotals = slot >= 24;

    // Direct value labels are suppressed pairwise, not thinned by a blanket
    // Nth rule: walk left to right and only draw a label once it clears the
    // previous one's measured right edge, so a run of narrow numbers (say,
    // most months) still all get labelled while only the specific pair whose
    // widths actually collide (a wide "395" next to a wide "367") drops one.
    // The first candidate always draws, so labels never vanish entirely on a
    // chart where they'd comfortably fit.
    var labelGap = 4;
    var lastLabelRight = -Infinity;

    var crosshair = svgEl('line', { class: 'c-crosshair' });
    var groups = spec.data.map(function () { return []; });

    spec.data.forEach(function (d, i) {
      var cx = PAD.left + slot * i + slot / 2;
      var x = cx - barW / 2;
      var yCursor = PAD.top + f.plotH;
      var topY = d.total ? PAD.top + f.plotH - (d.total / scale.max) * f.plotH : null;

      spec.series.forEach(function (s) {
        var value = d.parts[s.key] || 0;
        if (!value) return;
        var h = (value / scale.max) * f.plotH;
        yCursor -= h;
        // 2px surface gap between stacked segments so they read as separate.
        var drawH = Math.max(1, h - (yCursor > PAD.top ? 2 : 0));
        var rect = svgEl('rect', {
          class: 'c-bar', x: x, y: yCursor, width: barW, height: drawH,
          fill: s.color, rx: 2
        });
        g.appendChild(rect);
        groups[i].push(rect);
      });

      if (canLabelTotals && d.total) {
        var text = String(d.total);
        var half = textWidth(text, 10.5, 600) / 2;
        if (cx - half >= lastLabelRight + labelGap) {
          var lbl = svgEl('text', {
            class: 'c-value', x: cx, y: Math.max(PAD.top + 9, topY - 5), 'text-anchor': 'middle'
          });
          lbl.textContent = text;
          g.appendChild(lbl);
          lastLabelRight = cx + half;
        }
      }

      var hit = svgEl('rect', {
        class: 'c-hit', x: PAD.left + slot * i, y: PAD.top,
        width: slot, height: f.plotH
      });
      hookHover(hit, groups, i, crosshair, cx, PAD.top, PAD.top + f.plotH, d.tip);
      if (spec.onClick) hit.addEventListener('click', function () { spec.onClick(d); });
      g.appendChild(hit);

      if (d.tick && i % step === 0) {
        var t = svgEl('text', {
          class: 'c-tick', x: cx, y: PAD.top + f.plotH + 14, 'text-anchor': 'middle'
        });
        t.textContent = d.tick;
        if (rotate) {
          t.setAttribute('transform', 'rotate(-60 ' + cx + ' ' + (PAD.top + f.plotH + 14) + ')');
          t.setAttribute('text-anchor', 'end');
        }
        g.appendChild(t);
      }
    });

    g.appendChild(crosshair);

    if (spec.meanLine && spec.meanLine.value != null) {
      var y = PAD.top + f.plotH - (spec.meanLine.value / scale.max) * f.plotH;
      g.appendChild(svgEl('line', { class: 'c-mean', x1: PAD.left, x2: PAD.left + f.plotW, y1: y, y2: y }));

      // Anchored at the left edge, inset from the axis, instead of the right:
      // the right edge is where the last column - often the tallest, most
      // recent season - and its own value label live, so a right-aligned
      // label there is bound to collide with real data sooner or later.
      // Flip above/below the line based on how close it sits to the plot's
      // top or bottom so the label is never pushed off the frame either.
      var nearTop = (y - PAD.top) < 16;
      var mlblY = nearTop ? y + 14 : y - 6;
      var mlblText = spec.meanLine.label;
      var mlblW = textWidth(mlblText, 11);

      // A small surface-coloured backing keeps the label legible even if it
      // still lands over a bar or another label - sized from the same
      // text-measuring helper rather than a fixed guess, so it fits any
      // mean label at any width.
      g.appendChild(svgEl('rect', {
        class: 'c-label-bg', x: PAD.left + 3, y: mlblY - 11, width: mlblW + 6, height: 14,
        fill: HF.cssVar('--surface'), opacity: 0.85, rx: 2
      }));
      var mlbl = svgEl('text', { class: 'c-label', x: PAD.left + 6, y: mlblY, 'text-anchor': 'start' });
      mlbl.textContent = mlblText;
      g.appendChild(mlbl);
    }

    axisTitle(g, spec.yTitle || 'Events', 12, PAD.top + f.plotH / 2, 'middle', true, f.plotH * 0.92);
    if (spec.xTitle) axisTitle(g, spec.xTitle, PAD.left + f.plotW / 2, f.h - 4, undefined, false, f.plotW * 0.96);
    if (spec.series.length > 1) legend(container, spec.series);
  };

  /* ------------------------------------------------------------ histogram */

  /**
   * spec: {bins:[{x0,x1,count,items}], color (string or fn(bin)), xTitle,
   *        yTitle, fmtBin, fmtTick, threshold:{x,label}, footnote}
   */
  charts.histogram = function (container, spec) {
    if (!spec.bins.length) return empty(container);
    var f = frame(container);
    var g = svgEl('g', {});
    f.svg.appendChild(g);

    var max = Math.max.apply(null, spec.bins.map(function (b) { return b.count; }));
    var scale = niceScale(max);
    yAxis(g, scale, f.plotH, f.plotW);

    var lo = spec.bins[0].x0;
    var hi = spec.bins[spec.bins.length - 1].x1;
    var xOf = function (v) { return PAD.left + ((v - lo) / (hi - lo)) * f.plotW; };
    var slot = f.plotW / spec.bins.length;

    // A handful of bins is few enough to label every one directly; past that,
    // only the tallest bar earns a callout so a dense histogram stays clean.
    var labelAll = spec.bins.length <= 8;

    var maxTickW = 0;
    spec.bins.forEach(function (b) {
      maxTickW = Math.max(maxTickW, textWidth(spec.fmtTick ? spec.fmtTick(b.x0) : b.x0, 10.5));
    });
    var step = tickStep(spec.bins.length, maxTickW, f.plotW, 10);

    var crosshair = svgEl('line', { class: 'c-crosshair' });
    var groups = spec.bins.map(function () { return []; });

    spec.bins.forEach(function (b, i) {
      var h = (b.count / scale.max) * f.plotH;
      var x = xOf(b.x0);
      var cx = x + slot / 2;
      if (b.count) {
        var fill = typeof spec.color === 'function'
          ? spec.color(b)
          : (spec.color || HF.cssVar('--accent'));
        var bar = svgEl('rect', {
          class: 'c-bar', x: x + 1, y: PAD.top + f.plotH - h,
          width: Math.max(1, slot - 2), height: Math.max(1, h),
          fill: fill, rx: 2
        });
        g.appendChild(bar);
        groups[i].push(bar);
        if (labelAll || b.count === max) {
          var lbl = svgEl('text', {
            class: 'c-value', x: cx, y: Math.max(PAD.top + 9, PAD.top + f.plotH - h - 5), 'text-anchor': 'middle'
          });
          lbl.textContent = b.count;
          g.appendChild(lbl);
        }
      }
      var hit = svgEl('rect', { class: 'c-hit', x: x, y: PAD.top, width: slot, height: f.plotH });
      var label = spec.fmtBin ? spec.fmtBin(b) : (b.x0 + '–' + b.x1);
      hookHover(hit, groups, i, crosshair, cx, PAD.top, PAD.top + f.plotH,
        '<b>' + label + '</b><div class="t-row">' + b.count +
        ' event' + (b.count === 1 ? '' : 's') + '</div>');
      g.appendChild(hit);

      if (i % step === 0) {
        var t = svgEl('text', {
          class: 'c-tick', x: xOf(b.x0), y: PAD.top + f.plotH + 14, 'text-anchor': 'middle'
        });
        t.textContent = spec.fmtTick ? spec.fmtTick(b.x0) : b.x0;
        g.appendChild(t);
      }
    });

    g.appendChild(crosshair);

    // A domain that crosses zero (deepening vs. filling, say) gets its own
    // quiet reference line - the sign change is the meaningful boundary, not
    // just another gridline.
    if (lo < 0 && hi > 0) {
      var zx = xOf(0);
      g.appendChild(svgEl('line', { class: 'c-zero', x1: zx, x2: zx, y1: PAD.top, y2: PAD.top + f.plotH }));
    }

    if (spec.threshold && spec.threshold.x >= lo && spec.threshold.x <= hi) {
      var tx = xOf(spec.threshold.x);
      g.appendChild(svgEl('line', { class: 'c-threshold', x1: tx, x2: tx, y1: PAD.top, y2: PAD.top + f.plotH }));
      var tl = svgEl('text', { class: 'c-label', x: tx + 4, y: PAD.top + 10 });
      tl.textContent = spec.threshold.label;
      tl.setAttribute('fill', HF.cssVar('--critical'));
      g.appendChild(tl);
    }

    axisTitle(g, spec.yTitle || 'Events', 12, PAD.top + f.plotH / 2, 'middle', true, f.plotH * 0.92);
    if (spec.xTitle) axisTitle(g, spec.xTitle, PAD.left + f.plotW / 2, f.h - 4, undefined, false, f.plotW * 0.96);
    if (spec.footnote) {
      container.appendChild(HF.el('p', { class: 'chart-footnote' }, spec.footnote));
    }
  };

  /* -------------------------------------------------------------- scatter */

  /**
   * spec: {points:[{x,y,color,tip,item}], xTitle, yTitle, xDomain, yDomain,
   *        yInvert, series, height, onClick, showMedian}
   */
  charts.scatter = function (container, spec) {
    var h = spec.height || 320;
    if (!spec.points.length) return empty(container, null, h);
    var f = frame(container, h);
    var g = svgEl('g', {});
    f.svg.appendChild(g);

    var xs = spec.points.map(function (p) { return p.x; });
    var ys = spec.points.map(function (p) { return p.y; });
    var xDom = spec.xDomain || [Math.min.apply(null, xs), Math.max.apply(null, xs)];
    var yDom = spec.yDomain || [Math.min.apply(null, ys), Math.max.apply(null, ys)];

    var xOf = function (v) { return PAD.left + ((v - xDom[0]) / (xDom[1] - xDom[0])) * f.plotW; };
    var yOf = function (v) {
      var t = (v - yDom[0]) / (yDom[1] - yDom[0]);
      return PAD.top + (spec.yInvert ? t : 1 - t) * f.plotH;
    };

    // Gridlines on both axes, recessive - tick counts scale to the plot's
    // real pixel size so a narrow card doesn't crowd its labels.
    var yTicks = Math.max(2, Math.min(8, Math.floor(f.plotH / 34)));
    var yStep = niceStep(yDom[1] - yDom[0], yTicks);
    for (var v = Math.ceil(yDom[0] / yStep) * yStep; v <= yDom[1]; v += yStep) {
      var y = yOf(v);
      g.appendChild(svgEl('line', { class: 'c-grid', x1: PAD.left, x2: PAD.left + f.plotW, y1: y, y2: y }));
      var lab = svgEl('text', { class: 'c-tick', x: PAD.left - 7, y: y + 3.5, 'text-anchor': 'end' });
      lab.textContent = Math.round(v);
      g.appendChild(lab);
    }
    var xTicks = Math.max(2, Math.min(9, Math.floor(f.plotW / 56)));
    var xStep = niceStep(xDom[1] - xDom[0], xTicks);
    for (var u = Math.ceil(xDom[0] / xStep) * xStep; u <= xDom[1]; u += xStep) {
      var x = xOf(u);
      g.appendChild(svgEl('line', { class: 'c-grid', x1: x, x2: x, y1: PAD.top, y2: PAD.top + f.plotH }));
      var xlab = svgEl('text', { class: 'c-tick', x: x, y: PAD.top + f.plotH + 14, 'text-anchor': 'middle' });
      xlab.textContent = Math.round(u);
      g.appendChild(xlab);
    }
    g.appendChild(svgEl('line', {
      class: 'c-axis', x1: PAD.left, x2: PAD.left + f.plotW,
      y1: PAD.top + f.plotH, y2: PAD.top + f.plotH
    }));

    // The median is honest to compute and worth showing given how heavily
    // this many points overlap; it is labelled as exactly that, never as a
    // fitted trend.
    var showMedian = spec.showMedian !== false && spec.points.length >= 5;
    if (showMedian) {
      var mx = HF.median(xs), my = HF.median(ys);
      if (my != null) {
        var myPix = yOf(my);
        g.appendChild(svgEl('line', { class: 'c-median', x1: PAD.left, x2: PAD.left + f.plotW, y1: myPix, y2: myPix }));
        var myLbl = svgEl('text', { class: 'c-label', x: PAD.left + f.plotW - 4, y: myPix - 5, 'text-anchor': 'end' });
        myLbl.textContent = 'median ' + Math.round(my);
        g.appendChild(myLbl);
      }
      if (mx != null) {
        var mxPix = xOf(mx);
        g.appendChild(svgEl('line', { class: 'c-median', x1: mxPix, x2: mxPix, y1: PAD.top, y2: PAD.top + f.plotH }));
      }
    }

    var guideX = svgEl('line', { class: 'c-guide' });
    var guideY = svgEl('line', { class: 'c-guide' });
    g.appendChild(guideX); g.appendChild(guideY);

    // Overplotted by design (~1900 points): small marks, a surface ring so
    // overlaps stay separable, and a state class on the <svg> (rather than a
    // per-point loop) so hovering one point dims the rest cheaply.
    spec.points.forEach(function (p) {
      var cx = xOf(p.x), cy = yOf(p.y);
      var dot = svgEl('circle', {
        class: 'c-dot', cx: cx, cy: cy, r: 2.3, fill: p.color,
        'fill-opacity': 0.62, stroke: HF.cssVar('--surface'), 'stroke-width': 0.8
      });
      g.appendChild(dot);

      var hit = svgEl('circle', { class: 'c-dot-hit', cx: cx, cy: cy, r: 6.5 });
      hit.style.cursor = spec.onClick ? 'pointer' : 'default';
      hit.addEventListener('mouseenter', function (e) {
        f.svg.classList.add('is-hovering');
        dot.classList.add('is-hover');
        dot.setAttribute('r', 5);
        g.appendChild(dot);
        g.appendChild(hit);
        guideX.setAttribute('x1', PAD.left); guideX.setAttribute('x2', cx);
        guideX.setAttribute('y1', cy); guideX.setAttribute('y2', cy);
        guideY.setAttribute('x1', cx); guideY.setAttribute('x2', cx);
        guideY.setAttribute('y1', PAD.top + f.plotH); guideY.setAttribute('y2', cy);
        guideX.classList.add('is-visible'); guideY.classList.add('is-visible');
        HF.showTip(p.tip, e);
      });
      hit.addEventListener('mousemove', HF.moveTip);
      hit.addEventListener('mouseleave', function () {
        f.svg.classList.remove('is-hovering');
        dot.classList.remove('is-hover');
        dot.setAttribute('r', 2.3);
        guideX.classList.remove('is-visible'); guideY.classList.remove('is-visible');
        HF.hideTip();
      });
      if (spec.onClick) hit.addEventListener('click', function () { spec.onClick(p.item); });
      g.appendChild(hit);
    });

    axisTitle(g, spec.yTitle || '', 12, PAD.top + f.plotH / 2, 'middle', true, f.plotH * 0.92);
    if (spec.xTitle) axisTitle(g, spec.xTitle, PAD.left + f.plotW / 2, f.h - 4, undefined, false, f.plotW * 0.96);
    if (spec.series) legend(container, spec.series);
  };

  /* ------------------------------------------------- pressure trace (detail) */

  /** Small line chart of central pressure through one event's track. */
  charts.trace = function (container, fixes) {
    var pts = fixes.filter(function (f) { return f.pres != null; });
    if (pts.length < 2) return empty(container, 'Not enough analyzed pressures to plot a trace.', 130);

    HF.clear(container);
    var w = Math.max(260, container.clientWidth || 380);
    var h = 130, pad = { top: 12, right: 10, bottom: 22, left: 36 };
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + w + ' ' + h, width: w, height: h,
      preserveAspectRatio: 'xMinYMin meet'
    });
    svg.style.width = '100%';
    container.appendChild(svg);

    var plotW = w - pad.left - pad.right, plotH = h - pad.top - pad.bottom;
    var ps = pts.map(function (f) { return f.pres; });
    var lo = Math.floor((Math.min.apply(null, ps) - 4) / 5) * 5;
    var hi = Math.ceil((Math.max.apply(null, ps) + 4) / 5) * 5;

    var xOf = function (i) { return pad.left + (i / (pts.length - 1)) * plotW; };
    var yOf = function (p) { return pad.top + (1 - (p - lo) / (hi - lo)) * plotH; };

    [lo, (lo + hi) / 2, hi].forEach(function (v) {
      svg.appendChild(svgEl('line', { class: 'c-grid', x1: pad.left, x2: pad.left + plotW, y1: yOf(v), y2: yOf(v) }));
      var lab = svgEl('text', { class: 'c-tick', x: pad.left - 5, y: yOf(v) + 3.5, 'text-anchor': 'end' });
      lab.textContent = Math.round(v);
      svg.appendChild(lab);
    });

    var d = pts.map(function (f, i) { return (i ? 'L' : 'M') + xOf(i) + ' ' + yOf(f.pres); }).join(' ');
    svg.appendChild(svgEl('path', {
      d: d, fill: 'none', stroke: HF.cssVar('--accent'), 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));

    // The deepest analyzed fix is the headline number of the trace - call it
    // out directly rather than making the reader hover for it.
    var minFix = pts.reduce(function (a, b) { return b.pres < a.pres ? b : a; });

    var crosshair = svgEl('line', { class: 'c-crosshair' });
    svg.appendChild(crosshair);

    pts.forEach(function (f, i) {
      var isMin = f === minFix;
      var cx = xOf(i), cy = yOf(f.pres);
      var dot = svgEl('circle', {
        cx: cx, cy: cy, r: isMin ? 5 : 4, fill: HF.categoryColor(f.cat),
        stroke: HF.cssVar('--surface'), 'stroke-width': isMin ? 2 : 1.5
      });
      svg.appendChild(dot);
      var hit = svgEl('circle', { class: 'c-dot-hit', cx: cx, cy: cy, r: 9 });
      hit.addEventListener('mouseenter', function (e) {
        crosshair.setAttribute('x1', cx); crosshair.setAttribute('x2', cx);
        crosshair.setAttribute('y1', pad.top); crosshair.setAttribute('y2', pad.top + plotH);
        crosshair.classList.add('is-visible');
        HF.showTip('<b>' + HF.fmtDateShort(f.date) + '</b>' +
          '<div class="t-row">' + f.pres + ' hPa &middot; ' + f.cat + '</div>', e);
      });
      hit.addEventListener('mousemove', HF.moveTip);
      hit.addEventListener('mouseleave', function () {
        crosshair.classList.remove('is-visible');
        HF.hideTip();
      });
      svg.appendChild(hit);

      if (isMin) {
        var lbl = svgEl('text', {
          class: 'c-value', x: cx, y: cy - 9, 'text-anchor': cx > w - 40 ? 'end' : (cx < 40 ? 'start' : 'middle')
        });
        lbl.textContent = f.pres + ' hPa min';
        svg.appendChild(lbl);
      }
    });

    var xlab = svgEl('text', { class: 'c-tick', x: pad.left, y: h - 5 });
    xlab.textContent = HF.fmtDateShort(pts[0].date);
    svg.appendChild(xlab);
    var xlab2 = svgEl('text', { class: 'c-tick', x: pad.left + plotW, y: h - 5, 'text-anchor': 'end' });
    xlab2.textContent = HF.fmtDateShort(pts[pts.length - 1].date);
    svg.appendChild(xlab2);
  };

})(window.HF.charts = window.HF.charts || {}, window.HF);
