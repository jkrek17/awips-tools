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
    // Tracked so the mean line's own label (below) can defensively clear
    // out from underneath any value label its backing would otherwise
    // half-cover, without a live layout query.
    var valueLabels = [];

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
          var labelY = Math.max(PAD.top + 9, topY - 5);
          var lbl = svgEl('text', {
            class: 'c-value', x: cx, y: labelY, 'text-anchor': 'middle'
          });
          lbl.textContent = text;
          g.appendChild(lbl);
          lastLabelRight = cx + half;
          // Cap-height/descender of a 10.5px label (padded a couple of px
          // for font-metric slop), used only to check the mean label's
          // backing against this box later.
          valueLabels.push({ el: lbl, x0: cx - half, x1: cx + half, y0: labelY - 11, y1: labelY + 4 });
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

      // A fixed edge (say, always the right) eventually sits on top of
      // whichever column happens to land there - which is exactly how this
      // collided originally, with a recent/tall season pinned to the right.
      // Bias to whichever edge's outermost column currently clears the
      // line by the widest margin, then - since a chart can have every
      // column hovering near the mean, with no edge reliably clear - fall
      // back to removing any value label the backing still ends up over,
      // rather than trying to hunt for a guaranteed-empty spot. A hidden
      // number under an opaque "mean" tag reads as deliberate; overlapping
      // text does not.
      var clearGap = 16;
      var mlblText = spec.meanLine.label;
      var mlblW = textWidth(mlblText, 11);
      var lastD = spec.data[spec.data.length - 1], firstD = spec.data[0];
      var lastTopY = lastD.total ? PAD.top + f.plotH - (lastD.total / scale.max) * f.plotH : PAD.top + f.plotH;
      var firstTopY = firstD.total ? PAD.top + f.plotH - (firstD.total / scale.max) * f.plotH : PAD.top + f.plotH;
      var onRight = (lastTopY - y) >= (firstTopY - y) || (firstTopY - y) < clearGap;

      // Flip above/below the line based on how close it sits to the plot's
      // top so the label is never pushed off the frame at that end either.
      var nearTop = (y - PAD.top) < 16;
      var mlblY = nearTop ? y + 14 : y - 6;
      var mlblX = onRight ? PAD.left + f.plotW - mlblW - 6 : PAD.left + 6;

      var bg = { x0: mlblX - 3, x1: mlblX - 3 + mlblW + 6, y0: mlblY - 11, y1: mlblY - 11 + 14 };
      valueLabels.forEach(function (v) {
        if (v.x0 < bg.x1 && bg.x0 < v.x1 && v.y0 < bg.y1 && bg.y0 < v.y1) v.el.remove();
      });

      // A surface-coloured backing keeps the label legible against whatever
      // bar colour still sits beneath it, sized from the same text-measuring
      // helper so it fits any label at any width.
      g.appendChild(svgEl('rect', {
        class: 'c-label-bg', x: bg.x0, y: bg.y0, width: mlblW + 6, height: 14,
        fill: HF.cssVar('--surface'), opacity: 0.92, rx: 2
      }));
      var mlbl = svgEl('text', { class: 'c-label', x: mlblX, y: mlblY, 'text-anchor': 'start' });
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

    // Colour the line itself by the same per-fix MSLP ramp as the dots (and
    // the map tracks), rather than a flat accent stroke, so a trace that
    // deepens visibly ramps along its length the same way everywhere else
    // pressure is encoded. Every point here already has an analyzed
    // pressure (pts was filtered above), so each segment always resolves to
    // a real ramp colour, never --mslp-none.
    for (var si = 1; si < pts.length; si++) {
      var segColor = HF.pressureColor((pts[si - 1].pres + pts[si].pres) / 2);
      svg.appendChild(svgEl('line', {
        x1: xOf(si - 1), y1: yOf(pts[si - 1].pres), x2: xOf(si), y2: yOf(pts[si].pres),
        stroke: segColor, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }));
    }

    // The deepest analyzed fix is the headline number of the trace - call it
    // out directly rather than making the reader hover for it.
    var minFix = pts.reduce(function (a, b) { return b.pres < a.pres ? b : a; });

    var crosshair = svgEl('line', { class: 'c-crosshair' });
    svg.appendChild(crosshair);

    pts.forEach(function (f, i) {
      var isMin = f === minFix;
      var cx = xOf(i), cy = yOf(f.pres);
      var dot = svgEl('circle', {
        cx: cx, cy: cy, r: isMin ? 5 : 4, fill: HF.pressureColor(f.pres),
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

  /* --------------------------------------------- index + activity (stacked) */

  /**
   * One climate index above the storm activity it is being compared with,
   * on a SHARED time axis. Two panels, not two y-axes: the index (degC, a
   * standardized value, a pentad value) and the event count have nothing in
   * common but the calendar, and a dual-axis chart would let the eye find a
   * correlation the scaling invented. Stacked panels with one x scale and
   * one crosshair keep every vertical line meaning the same date in both.
   *
   * The lower panel is a single-unit stack: events in the chosen subset
   * (accent) with the rest of the archive on top of them (muted), so the bar
   * height is always "events that month" and the accent part is "how many of
   * those are in the subset" - the same measure, one axis.
   *
   * spec: {
   *   span:   [firstDay, lastDay]            day numbers on one common scale
   *   index:  {x:[day...], y:[value|null...], // null breaks the line
   *            title, fmt(v), fmtDay(day), unit,
   *            refs:[{value,label}], line: 'thin' | 'normal'}
   *   bins:   [{x0, x1, all, sub, label}]    event counts, x0..x1 inclusive days;
   *                                          merged in groups when too narrow
   *   seasons:[{x0, x1, tick, defining}]     1 Jun .. 31 May; defining ones are
   *                                          shaded and capped
   *   countTitle, ariaLabel,
   *   legend: [{label, kind:'line'|'ref'|'sub'|'rest'|'band'}]   (styled in charts.css)
   * }
   *
   * Hover shows the nearest index sample and the count for that bin. It
   * enhances; the same numbers are in the table view the page offers.
   */
  charts.indexSeries = function (container, spec) {
    if (!spec.index || !spec.index.x.length) {
      return empty(container, 'No index values cover this period.', 200);
    }
    var IDX_H = 150, GAP = 20, CNT_H = 104, AXIS_H = 26;
    var totalH = PAD.top + IDX_H + GAP + CNT_H + AXIS_H;
    var f = frame(container, totalH);
    var plotW = f.plotW;
    f.svg.setAttribute('aria-label', spec.ariaLabel || 'Climate index and event counts over time');
    var g = svgEl('g', {});
    f.svg.appendChild(g);

    var d0 = spec.span[0], d1 = spec.span[1];
    var xOf = function (d) { return PAD.left + ((d - d0) / (d1 - d0)) * plotW; };
    var idxTop = PAD.top, idxBot = PAD.top + IDX_H;
    var cntTop = idxBot + GAP, cntBot = cntTop + CNT_H;

    // ---- index scale: cover the data and every reference line, with air
    var ix = spec.index, vmin = Infinity, vmax = -Infinity, i;
    for (i = 0; i < ix.y.length; i++) {
      if (ix.y[i] == null) continue;
      if (ix.y[i] < vmin) vmin = ix.y[i];
      if (ix.y[i] > vmax) vmax = ix.y[i];
    }
    (ix.refs || []).forEach(function (r) {
      if (r.value < vmin) vmin = r.value;
      if (r.value > vmax) vmax = r.value;
    });
    if (!isFinite(vmin)) { vmin = -1; vmax = 1; }
    if (vmin > 0) vmin = 0;
    if (vmax < 0) vmax = 0;
    var vstep = niceStep(vmax - vmin, Math.max(2, Math.floor(IDX_H / 36)));
    var lo = Math.floor(vmin / vstep - 1e-9) * vstep, hi = Math.ceil(vmax / vstep - 1e-9) * vstep;
    var yIdx = function (v) { return idxBot - ((v - lo) / (hi - lo)) * IDX_H; };

    // ---- count scale
    var cmax = 0;
    spec.bins.forEach(function (b) { if (b.all > cmax) cmax = b.all; });

    // ---- merge bins until each is wide enough to read as a bar
    var bins = spec.bins, group = 1;
    if (bins.length) {
      var perBin = plotW / bins.length;
      group = Math.max(1, Math.ceil(3 / perBin));
    }
    if (group > 1) {
      var merged = [];
      for (i = 0; i < bins.length; i += group) {
        var chunk = bins.slice(i, i + group), m = {
          x0: chunk[0].x0, x1: chunk[chunk.length - 1].x1, all: 0, sub: 0,
          label: chunk.length > 1 ? chunk[0].label + ' to ' + chunk[chunk.length - 1].label : chunk[0].label
        };
        chunk.forEach(function (b) { m.all += b.all; m.sub += b.sub; });
        merged.push(m);
      }
      bins = merged;
      cmax = 0;
      bins.forEach(function (b) { if (b.all > cmax) cmax = b.all; });
    }
    var cscale = niceScale(Math.max(cmax, 1), 3);
    var yCnt = function (n) { return cntBot - (n / cscale.max) * CNT_H; };

    // ---- seasons: defining ones shaded across both panels and capped, so the
    // shading is never the only carrier (the cap is a shape; the table view
    // and the legend say the same in words)
    var seasons = spec.seasons || [];
    seasons.forEach(function (s) {
      if (!s.defining) return;
      var x0 = Math.max(PAD.left, xOf(s.x0)), x1 = Math.min(PAD.left + plotW, xOf(s.x1 + 1));
      g.appendChild(svgEl('rect', {
        class: 'c-band', x: x0, y: idxTop, width: Math.max(1, x1 - x0), height: cntBot - idxTop
      }));
      g.appendChild(svgEl('rect', {
        class: 'c-band-cap', x: x0, y: idxTop, width: Math.max(1, x1 - x0), height: 3
      }));
    });

    // ---- grid: horizontal for each panel, vertical at every season start
    for (var v = lo; v <= hi + 1e-9; v += vstep) {
      var gy = yIdx(v);
      g.appendChild(svgEl('line', { class: v === 0 ? 'c-axis' : 'c-grid', x1: PAD.left, x2: PAD.left + plotW, y1: gy, y2: gy }));
      var lab = svgEl('text', { class: 'c-tick', x: PAD.left - 7, y: gy + 3.5, 'text-anchor': 'end' });
      lab.textContent = ix.fmtTick ? ix.fmtTick(v) : String(Math.round(v * 100) / 100);
      g.appendChild(lab);
    }
    for (var cv = 0; cv <= cscale.max + 1e-9; cv += cscale.step) {
      var cy = yCnt(cv);
      g.appendChild(svgEl('line', { class: cv === 0 ? 'c-axis' : 'c-grid', x1: PAD.left, x2: PAD.left + plotW, y1: cy, y2: cy }));
      var clab = svgEl('text', { class: 'c-tick', x: PAD.left - 7, y: cy + 3.5, 'text-anchor': 'end' });
      clab.textContent = String(Math.round(cv));
      g.appendChild(clab);
    }
    seasons.forEach(function (s) {
      var sx = xOf(s.x0);
      if (sx <= PAD.left + 0.5) return;
      g.appendChild(svgEl('line', { class: 'c-grid c-grid-v', x1: sx, x2: sx, y1: idxTop, y2: cntBot }));
    });

    // ---- reference lines (thresholds, tercile cuts): labelled, never red -
    // red is this site's "critical" status colour and these are not alarms
    (ix.refs || []).forEach(function (r) {
      var ry = yIdx(r.value);
      g.appendChild(svgEl('line', { class: 'c-ref', x1: PAD.left, x2: PAD.left + plotW, y1: ry, y2: ry }));
      // Above the line for a positive reference, below for a negative one, so
      // the label sits on the side away from zero and clear of the index line.
      var rl = svgEl('text', { class: 'c-label c-ref-label', x: PAD.left + plotW - 4,
                               y: r.value >= 0 ? ry - 4 : ry + 12, 'text-anchor': 'end' });
      rl.textContent = r.label;
      g.appendChild(rl);
    });

    // ---- the index line, broken wherever a value is missing
    var path = [], pen = false;
    for (i = 0; i < ix.x.length; i++) {
      if (ix.y[i] == null) { pen = false; continue; }
      path.push((pen ? 'L' : 'M') + xOf(ix.x[i]).toFixed(1) + ' ' + yIdx(ix.y[i]).toFixed(1));
      pen = true;
    }
    g.appendChild(svgEl('path', {
      class: 'c-line' + (ix.line === 'thin' ? ' c-line-thin' : ''), d: path.join('')
    }));

    // ---- event counts: subset at the base, the rest stacked on it
    var barG = svgEl('g', {});
    g.appendChild(barG);
    bins.forEach(function (b) {
      if (!b.all) return;
      var bx0 = xOf(b.x0), bx1 = xOf(b.x1 + 1);
      var w = Math.max(1, bx1 - bx0 - (bx1 - bx0 > 3 ? 1 : 0));
      var hSub = (b.sub / cscale.max) * CNT_H, hAll = (b.all / cscale.max) * CNT_H;
      if (b.sub) {
        barG.appendChild(svgEl('rect', {
          class: 'c-bar c-bar-sub', x: bx0, y: cntBot - hSub, width: w, height: Math.max(1, hSub)
        }));
      }
      if (b.all > b.sub) {
        var hRest = hAll - hSub;
        // 2px surface gap between the two fills only when both can afford it
        var gap = b.sub && hRest > 3 ? 1.5 : 0;
        barG.appendChild(svgEl('rect', {
          class: 'c-bar c-bar-rest', x: bx0, y: cntBot - hAll, width: w, height: Math.max(1, hRest - gap)
        }));
      }
    });

    // ---- x axis: season labels centred in their season, thinned to fit
    var tickW = 0;
    seasons.forEach(function (s) { tickW = Math.max(tickW, textWidth(s.tick, 10.5)); });
    var tstep = tickStep(seasons.length, tickW, plotW, 8);
    seasons.forEach(function (s, k) {
      if (k % tstep !== 0) return;
      var cx = (Math.max(PAD.left, xOf(s.x0)) + Math.min(PAD.left + plotW, xOf(s.x1 + 1))) / 2;
      var t = svgEl('text', { class: 'c-tick', x: cx, y: cntBot + 15, 'text-anchor': 'middle' });
      t.textContent = s.tick;
      g.appendChild(t);
    });
    axisTitle(g, ix.title || 'Index', 12, idxTop + IDX_H / 2, 'middle', true, IDX_H * 0.96);
    axisTitle(g, spec.countTitle || 'Events', 12, cntTop + CNT_H / 2, 'middle', true, CNT_H * 0.96);

    // ---- one crosshair, one tooltip: nearest index sample + the bin's counts
    var crosshair = svgEl('line', { class: 'c-crosshair' });
    g.appendChild(crosshair);
    var hit = svgEl('rect', {
      class: 'c-hit', x: PAD.left, y: idxTop, width: plotW, height: cntBot - idxTop
    });
    g.appendChild(hit);

    function nearestIndex(day) {
      var a = 0, b = ix.x.length - 1;
      while (a < b) {
        var mid = (a + b) >> 1;
        if (ix.x[mid] < day) a = mid + 1; else b = mid;
      }
      if (a > 0 && Math.abs(ix.x[a - 1] - day) <= Math.abs(ix.x[a] - day)) a--;
      return a;
    }
    function binAt(day) {
      for (var k = 0; k < bins.length; k++) if (day >= bins[k].x0 && day <= bins[k].x1) return bins[k];
      return null;
    }
    function tipAt(e) {
      var rect = f.svg.getBoundingClientRect();
      var px = (e.clientX - rect.left) * (f.w / rect.width);
      var day = d0 + ((px - PAD.left) / plotW) * (d1 - d0);
      var k = nearestIndex(day);
      var bin = binAt(day);
      var html = '<b>' + (ix.fmtDay ? ix.fmtDay(ix.x[k]) : ix.x[k]) + '</b>';
      html += '<div class="t-row">' + (ix.name || 'Index') + ': ' +
              (ix.y[k] == null ? 'no value' : (ix.fmt ? ix.fmt(ix.y[k]) : ix.y[k])) + '</div>';
      if (bin) {
        html += '<div class="t-row">' + bin.label + ': ' + bin.all + ' event' + (bin.all === 1 ? '' : 's') +
                ', ' + bin.sub + ' in this subset</div>';
      }
      var cxp = xOf(ix.x[k]);
      crosshair.setAttribute('x1', cxp); crosshair.setAttribute('x2', cxp);
      crosshair.setAttribute('y1', idxTop); crosshair.setAttribute('y2', cntBot);
      crosshair.classList.add('is-visible');
      return html;
    }
    hit.addEventListener('mouseenter', function (e) { HF.showTip(tipAt(e), e); });
    hit.addEventListener('mousemove', function (e) {
      var tip = document.getElementById('tooltip');
      if (tip) tip.innerHTML = tipAt(e);
      HF.moveTip(e);
    });
    hit.addEventListener('mouseleave', function () {
      crosshair.classList.remove('is-visible');
      HF.hideTip();
    });

    // ---- legend: a key for every mark, so nothing rests on colour alone
    if (spec.legend && spec.legend.length) {
      var box = HF.el('p', { class: 'chart-legend' });
      spec.legend.forEach(function (it) {
        var span = HF.el('span');
        var key = HF.el('i', { class: 'c-key c-key-' + it.kind });
        span.appendChild(key);
        span.appendChild(document.createTextNode(it.label));
        box.appendChild(span);
      });
      container.appendChild(box);
    }
  };

  /* ------------------------------------------------------- coefficient plot */

  function escHtml(v) {
    return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /** A dot-and-whisker plot of regression coefficients, each with its own
      detection floor. The floor is the point of the chart.

      WHY A FLOOR ON THE PLOT. An interval that includes zero reads as "no
      effect" to almost everyone, and for an underpowered sample that is the
      wrong reading: the honest one is "an effect this big could not have been
      seen here". So every row carries, behind its interval, a band from
      -floor to +floor (the MDE80: the smallest true effect this sample would
      find 80% of the time). The reader's whole job is then one glance per
      row: is the dot, and the interval around it, inside its own band
      (cannot be resolved) or clear of it (could be, and was)? Because the
      floor differs row by row (it is 2.8 standard errors, and an interaction
      term has a larger one than a main effect), each row's band is its own.

      THREE STATES, NEVER COLOUR ALONE. Detected is a filled dot in the
      accent colour; below-floor is a hollow ring in the muted ink; unavailable
      has no dot at all, only the words "no interval". The state is also
      spelled in the row's own label, with a glyph, and again in the aria-label
      and the table view. Colour is the third channel here, not the first:
      (accent vs muted ink: contrast >= 3:1 on both surfaces, normal-vision
      delta E 28.1 light / 17.2 dark, CVD 25.6 / 16.6, from the dataviz
      validator; the lightness-band and chroma checks it also prints are
      categorical-palette tests and fail a gray by design.) A single signed
      axis carries direction and size, so no second hue is needed for sign.

      spec: {
        rows: [{ key, label, sub, est, lo, hi, floor,
                 state: 'detected' | 'below' | 'unavailable',
                 stateText, valueText, rangeText, floorText, group, aria, tip }],
        oneSided: false,        // true: axis starts at 0 and the band runs 0..floor (a magnitude, e.g. MJO R)
        axisTitle: '',          // what x measures, with units
        ends: ['', ''],         // plain-language meaning of the two directions (two-sided only)
        fmtTick: fn(v),
        marks: [{ row: key, value, label }],   // extra labelled tick on one row (oneSided: the null's 95th percentile)
        legend: true, ariaLabel: '', floorWord: 'Detection floor'
      }                                                                                    */
  charts.coefPlot = function (container, spec) {
    var rows = spec.rows || [];
    if (!rows.length) return empty(container, spec.emptyText || 'Nothing to plot.', 120);
    HF.clear(container);

    var w = widthOf(container);
    var wide = w >= 560;
    var ROW = 54, GROUP = 26, TOP = 6;
    var oneSided = !!spec.oneSided;

    // Left gutter: wide enough for the longest label and its state line.
    var gl = 0;
    rows.forEach(function (r) {
      gl = Math.max(gl, textWidth(r.label, 12.5, 650), textWidth((r.stateGlyph || '') + ' ' + (r.stateText || ''), 11, 500) + 4);
    });
    var LG = Math.min(Math.max(72, Math.ceil(gl) + 12), Math.floor(w * 0.34));
    var RG = wide ? 104 : 8;
    var plotX0 = LG, plotX1 = w - RG - 10, plotW = Math.max(120, plotX1 - plotX0);

    // Domain: symmetric about zero so left and right have the same scale, and
    // wide enough for every interval AND every floor.
    var m = 0;
    rows.forEach(function (r) {
      [r.est, r.lo, r.hi, r.floor].forEach(function (v) { if (v != null && isFinite(v)) m = Math.max(m, Math.abs(v)); });
    });
    (spec.marks || []).forEach(function (k) { if (isFinite(k.value)) m = Math.max(m, Math.abs(k.value)); });
    if (!(m > 0)) m = 1;
    var step = niceStep(m * (oneSided ? 1 : 2), 5);
    var dmax = Math.ceil(m * 1.06 / step) * step;
    var dmin = oneSided ? 0 : -dmax;
    function X(v) { return plotX0 + ((v - dmin) / (dmax - dmin)) * plotW; }

    // Axis furniture, measured first so a narrow card wraps instead of
    // clipping: the title breaks onto two lines when it is wider than the
    // plot, and the two direction labels stack when they would touch.
    var titleLines = [], xt = spec.axisTitle || '';
    if (xt) {
      if (textWidth(xt, 11, 600) <= plotW) titleLines = [xt];
      else {
        var cut = xt.lastIndexOf(' (');
        titleLines = cut > 0 ? [xt.slice(0, cut), xt.slice(cut + 1)] : [xt];
      }
    }
    var hasEnds = !oneSided && spec.ends && spec.ends[0];
    var stackEnds = hasEnds && textWidth('← ' + spec.ends[0], 11) + textWidth(spec.ends[1] + ' →', 11) + 16 > plotW;
    var AXIS = 20 + titleLines.length * 14 + (hasEnds ? (stackEnds ? 32 : 18) : 4);

    // vertical layout, with a header row whenever the group changes
    var y = TOP, layout = [], lastGroup = null, nGroups = 0;
    rows.forEach(function (r) { if (r.group && (r.group !== lastGroup)) { nGroups++; lastGroup = r.group; } });
    lastGroup = null;
    rows.forEach(function (r) {
      if (nGroups > 1 && r.group && r.group !== lastGroup) {
        layout.push({ header: r.group, y: y });
        y += GROUP;
      }
      lastGroup = r.group;
      layout.push({ row: r, y: y });
      y += ROW;
    });
    var plotBot = y, H2 = plotBot + AXIS;

    var svg = svgEl('svg', { viewBox: '0 0 ' + w + ' ' + H2, width: w, height: H2, role: 'group', 'class': 'c-coef' });
    svg.setAttribute('aria-label', spec.ariaLabel || 'Coefficient plot');
    svg.style.width = '100%';
    svg.style.height = H2 + 'px';
    container.appendChild(svg);
    var g = svgEl('g', {});
    svg.appendChild(g);

    // gridlines and tick labels
    var t, fmt = spec.fmtTick || function (v) { return String(Math.round(v * 100) / 100); };
    for (t = dmin; t <= dmax + 1e-9; t += step) {
      var tv = Math.abs(t) < 1e-9 ? 0 : t;
      g.appendChild(svgEl('line', { 'class': tv === 0 && !oneSided ? 'c-grid c-grid-zero-ghost' : 'c-grid', x1: X(tv), x2: X(tv), y1: TOP, y2: plotBot }));
      var tl = svgEl('text', { 'class': 'c-tick', x: X(tv), y: plotBot + 14, 'text-anchor': 'middle' });
      tl.textContent = fmt(tv);
      g.appendChild(tl);
    }
    // the zero line: solid, heavier than the grid, because "no effect" lives here
    g.appendChild(svgEl('line', { 'class': 'c-zero-line', x1: X(0), x2: X(0), y1: TOP, y2: plotBot }));
    g.appendChild(svgEl('line', { 'class': 'c-axis', x1: plotX0, x2: plotX0 + plotW, y1: plotBot, y2: plotBot }));

    titleLines.forEach(function (ln, k) {
      axisTitle(g, ln, plotX0 + plotW / 2, plotBot + 30 + k * 14, 'middle', false, plotW);
    });
    if (hasEnds) {
      var ey = plotBot + 30 + titleLines.length * 14 + 2;
      var eL = svgEl('text', { 'class': 'c-ends', x: plotX0, y: ey, 'text-anchor': 'start' });
      eL.textContent = '← ' + spec.ends[0];
      var eR = svgEl('text', { 'class': 'c-ends', x: plotX0 + plotW, y: ey + (stackEnds ? 14 : 0), 'text-anchor': 'end' });
      eR.textContent = spec.ends[1] + ' →';
      g.appendChild(eL); g.appendChild(eR);
    }

    var labelledFloor = false;
    layout.forEach(function (it) {
      if (it.header) {
        var hd = svgEl('text', { 'class': 'c-group', x: 4, y: it.y + 17 });
        hd.textContent = it.header;
        g.appendChild(hd);
        g.appendChild(svgEl('line', { 'class': 'c-grid', x1: 0, x2: w - 8, y1: it.y + GROUP - 4, y2: it.y + GROUP - 4 }));
        return;
      }
      var r = it.row, cy = it.y + ROW / 2;
      var rg = svgEl('g', { 'class': 'c-coef-row is-' + r.state, tabindex: '0', role: 'img' });
      rg.setAttribute('aria-label', r.aria || (r.label + ': ' + (r.stateText || '')));
      g.appendChild(rg);

      rg.appendChild(svgEl('rect', { 'class': 'c-coef-hit', x: 0, y: it.y, width: w - 4, height: ROW, rx: 4 }));

      // left: name, then the state in words with its glyph
      var nm = svgEl('text', { 'class': 'c-coef-label', x: 4, y: cy - 2 });
      nm.textContent = r.label;
      rg.appendChild(nm);
      var st = svgEl('text', { 'class': 'c-coef-state', x: 4, y: cy + 13 });
      st.textContent = (r.stateGlyph ? r.stateGlyph + ' ' : '') + (r.stateText || '');
      rg.appendChild(st);

      // the detection floor: a band, with a firm tick at each end
      if (r.floor != null && isFinite(r.floor) && r.floor > 0) {
        var fx0 = oneSided ? X(0) : X(-r.floor), fx1 = X(r.floor);
        rg.appendChild(svgEl('rect', { 'class': 'c-floor', x: fx0, y: cy - 15, width: Math.max(1, fx1 - fx0), height: 30 }));
        rg.appendChild(svgEl('line', { 'class': 'c-floor-end', x1: fx1, x2: fx1, y1: cy - 18, y2: cy + 18 }));
        if (!oneSided) rg.appendChild(svgEl('line', { 'class': 'c-floor-end', x1: fx0, x2: fx0, y1: cy - 18, y2: cy + 18 }));
        if (!labelledFloor && spec.floorWord !== false) {
          labelledFloor = true;
          var flText = (spec.floorWord || 'detection floor') + (oneSided ? '' : ' ±' + (r.floorShort || ''));
          var flW = textWidth(flText, 10);
          var fl = svgEl('text', { 'class': 'c-floor-label', x: Math.max(4, Math.min(fx1 + 4, w - 6 - flW)), y: it.y + 9, 'text-anchor': 'start' });
          fl.textContent = flText;
          rg.appendChild(fl);
        }
      }

      // an extra labelled tick (the permutation null's 95th percentile)
      (spec.marks || []).forEach(function (k) {
        if (k.row !== r.key || !isFinite(k.value)) return;
        rg.appendChild(svgEl('line', { 'class': 'c-mark', x1: X(k.value), x2: X(k.value), y1: cy - 20, y2: cy + 20 }));
        var mt = svgEl('text', { 'class': 'c-floor-label', x: X(k.value) + 3, y: it.y + ROW - 4, 'text-anchor': 'start' });
        mt.textContent = k.label;
        rg.appendChild(mt);
      });

      if (r.state === 'unavailable' || r.est == null || !isFinite(r.est) || r.lo == null) {
        var na = svgEl('text', { 'class': 'c-na', x: X(0) + 8, y: cy + 4, 'text-anchor': 'start' });
        na.textContent = 'no interval';
        rg.appendChild(na);
      } else {
        // the interval, with end caps, then the estimate on top
        rg.appendChild(svgEl('line', { 'class': 'c-ci', x1: X(r.lo), x2: X(r.hi), y1: cy, y2: cy }));
        rg.appendChild(svgEl('line', { 'class': 'c-ci-cap', x1: X(r.lo), x2: X(r.lo), y1: cy - 5, y2: cy + 5 }));
        rg.appendChild(svgEl('line', { 'class': 'c-ci-cap', x1: X(r.hi), x2: X(r.hi), y1: cy - 5, y2: cy + 5 }));
        rg.appendChild(svgEl('circle', { 'class': 'c-pt', cx: X(r.est), cy: cy, r: 5.5 }));
      }

      // right: the numbers, as text, so the plot is never the only place to read them
      if (wide) {
        var v1 = svgEl('text', { 'class': 'c-value c-coef-val', x: w - RG + 2, y: cy - 6, 'text-anchor': 'start' });
        v1.textContent = r.valueText || '';
        rg.appendChild(v1);
        var v2 = svgEl('text', { 'class': 'c-coef-sub', x: w - RG + 2, y: cy + 8, 'text-anchor': 'start' });
        v2.textContent = r.rangeText || '';
        rg.appendChild(v2);
        var v3 = svgEl('text', { 'class': 'c-coef-sub', x: w - RG + 2, y: cy + 21, 'text-anchor': 'start' });
        v3.textContent = r.floorText || '';
        rg.appendChild(v3);
      }

      // hover and keyboard focus show the same details
      var tipHtml = r.tip ? r.tip : '<b>' + escHtml(r.label) + '</b><div class="t-row">' + escHtml(r.aria || '') + '</div>';
      rg.addEventListener('mouseenter', function (e) { HF.showTip(tipHtml, e); });
      rg.addEventListener('mousemove', HF.moveTip);
      rg.addEventListener('mouseleave', HF.hideTip);
      rg.addEventListener('focus', function () {
        var bb = rg.getBoundingClientRect();
        HF.showTip(tipHtml, { clientX: bb.left + Math.min(bb.width, 260), clientY: bb.top });
      });
      rg.addEventListener('blur', HF.hideTip);
    });

    // legend: a key for every mark in use (shape first, colour second)
    if (spec.legend !== false) {
      var used = {};
      rows.forEach(function (r) { used[r.state] = true; });
      var box = HF.el('p', { 'class': 'chart-legend c-coef-legend' });
      function key(cls, text) {
        var span = HF.el('span');
        span.appendChild(HF.el('i', { 'class': 'c-key ' + cls }));
        span.appendChild(document.createTextNode(text));
        box.appendChild(span);
      }
      if (used.detected) key('c-key-pt-on', 'Detected: interval excludes zero and the estimate is above the floor');
      if (used.below) key('c-key-pt-off', 'Below floor: this sample cannot resolve an effect this size');
      key('c-key-floor', spec.floorLegend || 'Detection floor: the smallest true effect this sample would find 80% of the time');
      key('c-key-ci', spec.ciLegend || '95% interval');
      container.appendChild(box);
    }
  };

})(window.HF.charts = window.HF.charts || {}, window.HF);
