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

  function empty(container, message) {
    HF.clear(container);
    container.appendChild(HF.el('p', { class: 'chart-empty' }, message || 'No events match the current filters.'));
  }

  /** Round a maximum up to a readable axis top, and pick a tick step. */
  function niceScale(max) {
    if (max <= 0) return { max: 1, step: 1 };
    var raw = max / 5;
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    var step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    return { max: Math.ceil(max / step) * step, step: step };
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

  function axisTitle(g, text, x, y, anchor, rotate) {
    var node = svgEl('text', {
      class: 'c-axis-title', x: x, y: y, 'text-anchor': anchor || 'middle'
    });
    if (rotate) node.setAttribute('transform', 'rotate(-90 ' + x + ' ' + y + ')');
    node.textContent = text;
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

  /* -------------------------------------------------------------- columns */

  /**
   * Stacked column chart.
   * spec: {data:[{label, tick, parts:{key:count}, total, tip}],
   *        series:[{key,label,color}], yTitle, meanLine:{value,label}, onClick}
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

    spec.data.forEach(function (d, i) {
      var cx = PAD.left + slot * i + slot / 2;
      var x = cx - barW / 2;
      var yCursor = PAD.top + f.plotH;

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
      });

      var hit = svgEl('rect', {
        class: 'c-hit', x: PAD.left + slot * i, y: PAD.top,
        width: slot, height: f.plotH
      });
      attachTip(hit, d.tip);
      if (spec.onClick) hit.addEventListener('click', function () { spec.onClick(d); });
      g.appendChild(hit);

      if (d.tick) {
        var t = svgEl('text', {
          class: 'c-tick', x: cx, y: PAD.top + f.plotH + 14, 'text-anchor': 'middle'
        });
        t.textContent = d.tick;
        if (d.tickRotate) {
          t.setAttribute('transform', 'rotate(-60 ' + cx + ' ' + (PAD.top + f.plotH + 14) + ')');
          t.setAttribute('text-anchor', 'end');
        }
        g.appendChild(t);
      }
    });

    if (spec.meanLine && spec.meanLine.value != null) {
      var y = PAD.top + f.plotH - (spec.meanLine.value / scale.max) * f.plotH;
      g.appendChild(svgEl('line', { class: 'c-mean', x1: PAD.left, x2: PAD.left + f.plotW, y1: y, y2: y }));
      var lbl = svgEl('text', { class: 'c-label', x: PAD.left + f.plotW - 6, y: y - 6, 'text-anchor': 'end' });
      lbl.textContent = spec.meanLine.label;
      g.appendChild(lbl);
    }

    axisTitle(g, spec.yTitle || 'Events', 12, PAD.top + f.plotH / 2, 'middle', true);
    if (spec.xTitle) axisTitle(g, spec.xTitle, PAD.left + f.plotW / 2, f.h - 4);
    if (spec.series.length > 1) legend(container, spec.series);
  };

  /* ------------------------------------------------------------ histogram */

  /**
   * spec: {bins:[{x0,x1,count}], color, xTitle, yTitle, fmtBin, threshold:{x,label}}
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

    spec.bins.forEach(function (b) {
      var h = (b.count / scale.max) * f.plotH;
      var x = xOf(b.x0);
      if (b.count) {
        var fill = typeof spec.color === 'function'
          ? spec.color(b)
          : (spec.color || HF.cssVar('--accent'));
        g.appendChild(svgEl('rect', {
          class: 'c-bar', x: x + 1, y: PAD.top + f.plotH - h,
          width: Math.max(1, slot - 2), height: Math.max(1, h),
          fill: fill, rx: 2
        }));
      }
      var hit = svgEl('rect', { class: 'c-hit', x: x, y: PAD.top, width: slot, height: f.plotH });
      var label = spec.fmtBin ? spec.fmtBin(b) : (b.x0 + '–' + b.x1);
      attachTip(hit, '<b>' + label + '</b><div class="t-row">' + b.count +
                     ' event' + (b.count === 1 ? '' : 's') + '</div>');
      g.appendChild(hit);
    });

    // Ticks every Nth bin edge so labels never collide.
    var every = Math.ceil(spec.bins.length / 9);
    spec.bins.forEach(function (b, i) {
      if (i % every) return;
      var t = svgEl('text', {
        class: 'c-tick', x: xOf(b.x0), y: PAD.top + f.plotH + 14, 'text-anchor': 'middle'
      });
      t.textContent = spec.fmtTick ? spec.fmtTick(b.x0) : b.x0;
      g.appendChild(t);
    });

    if (spec.threshold && spec.threshold.x >= lo && spec.threshold.x <= hi) {
      var tx = xOf(spec.threshold.x);
      g.appendChild(svgEl('line', { class: 'c-threshold', x1: tx, x2: tx, y1: PAD.top, y2: PAD.top + f.plotH }));
      var tl = svgEl('text', { class: 'c-label', x: tx + 4, y: PAD.top + 10 });
      tl.textContent = spec.threshold.label;
      tl.setAttribute('fill', HF.cssVar('--critical'));
      g.appendChild(tl);
    }

    axisTitle(g, spec.yTitle || 'Events', 12, PAD.top + f.plotH / 2, 'middle', true);
    if (spec.xTitle) axisTitle(g, spec.xTitle, PAD.left + f.plotW / 2, f.h - 4);
    if (spec.footnote) {
      container.appendChild(HF.el('p', { class: 'chart-footnote' }, spec.footnote));
    }
  };

  /* -------------------------------------------------------------- scatter */

  /**
   * spec: {points:[{x,y,color,tip,item}], xTitle, yTitle, xDomain, yDomain,
   *        yInvert, onClick}
   */
  charts.scatter = function (container, spec) {
    if (!spec.points.length) return empty(container);
    var f = frame(container, spec.height || 320);
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

    // Gridlines on both axes, recessive.
    var yStep = niceScale(yDom[1] - yDom[0]).step;
    for (var v = Math.ceil(yDom[0] / yStep) * yStep; v <= yDom[1]; v += yStep) {
      var y = yOf(v);
      g.appendChild(svgEl('line', { class: 'c-grid', x1: PAD.left, x2: PAD.left + f.plotW, y1: y, y2: y }));
      var lab = svgEl('text', { class: 'c-tick', x: PAD.left - 7, y: y + 3.5, 'text-anchor': 'end' });
      lab.textContent = Math.round(v);
      g.appendChild(lab);
    }
    var xStep = niceScale(xDom[1] - xDom[0]).step;
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

    spec.points.forEach(function (p) {
      var dot = svgEl('circle', {
        cx: xOf(p.x), cy: yOf(p.y), r: 3.1, fill: p.color,
        'fill-opacity': 0.72, stroke: HF.cssVar('--surface'), 'stroke-width': 0.8
      });
      dot.style.cursor = spec.onClick ? 'pointer' : 'default';
      attachTip(dot, p.tip);
      if (spec.onClick) dot.addEventListener('click', function () { spec.onClick(p.item); });
      g.appendChild(dot);
    });

    axisTitle(g, spec.yTitle || '', 12, PAD.top + f.plotH / 2, 'middle', true);
    if (spec.xTitle) axisTitle(g, spec.xTitle, PAD.left + f.plotW / 2, f.h - 4);
    if (spec.series) legend(container, spec.series);
  };

  /* ------------------------------------------------- pressure trace (detail) */

  /** Small line chart of central pressure through one event's track. */
  charts.trace = function (container, fixes) {
    var pts = fixes.filter(function (f) { return f.pres != null; });
    if (pts.length < 2) return empty(container, 'Not enough analyzed pressures to plot a trace.');

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

    pts.forEach(function (f, i) {
      var dot = svgEl('circle', {
        cx: xOf(i), cy: yOf(f.pres), r: 4, fill: HF.categoryColor(f.cat),
        stroke: HF.cssVar('--surface'), 'stroke-width': 1.5
      });
      attachTip(dot, '<b>' + HF.fmtDateShort(f.date) + '</b>' +
                     '<div class="t-row">' + f.pres + ' hPa &middot; ' + f.cat + '</div>');
      svg.appendChild(dot);
    });

    var xlab = svgEl('text', { class: 'c-tick', x: pad.left, y: h - 5 });
    xlab.textContent = HF.fmtDateShort(pts[0].date);
    svg.appendChild(xlab);
    var xlab2 = svgEl('text', { class: 'c-tick', x: pad.left + plotW, y: h - 5, 'text-anchor': 'end' });
    xlab2.textContent = HF.fmtDateShort(pts[pts.length - 1].date);
    svg.appendChild(xlab2);
  };

})(window.HF.charts = window.HF.charts || {}, window.HF);
