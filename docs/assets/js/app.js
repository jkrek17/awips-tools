/* Wiring: filter state -> KPIs, map, charts, table, detail drawer.
   One render() pass drives every view so the tabs can never disagree. */

(function (HF) {
  'use strict';

  var DATA = null;
  var LOWS = [];

  var state = {
    tab: 'map',
    basin: 'both',
    cls: 'all',
    season0: null,
    season1: null,
    months: {},            // month number -> true when active; empty = all
    maxPressure: 1010,
    bombOnly: false,
    search: '',
    layer: 'tracks',       // 'tracks' | 'density' | 'genesis' | 'peak' | 'playback'
    currents: false,   // ocean currents background layer - independent of `layer`, off by default
    sort: { key: 'start', dir: -1 },
    selectedKey: null
  };

  var TABLE_LIMIT = 300;
  var detailTrigger = null;  // element to return focus to when the detail drawer closes
  var announceTimer = null;  // debounces the aria-live result-count text

  /* ------------------------------------------------------------ filtering */

  function passes(low) {
    if (state.basin !== 'both' && low.basin !== state.basin) return false;

    if (state.cls === 'low' && low.cls !== 'low') return false;
    // "No analyzed centre" covers both pressure-less classes; "tipjet" is the
    // Greenland subset of it.
    if (state.cls === 'nopres' && low.cls === 'low') return false;
    if (state.cls === 'tipjet' && low.cls !== 'tipjet') return false;

    if (state.season0 != null && low.season < state.season0) return false;
    if (state.season1 != null && low.season > state.season1) return false;

    var months = Object.keys(state.months);
    if (months.length && !state.months[low.month]) return false;

    if (state.maxPressure < 1010) {
      if (low.minP == null || low.minP > state.maxPressure) return false;
    }
    if (state.bombOnly && !low.bomb) return false;

    if (state.search) {
      var q = state.search.toLowerCase();
      var hay = low.id + ' ' + HF.seasonLabel(low.season) + ' ' + low.basin;
      if (hay.toLowerCase().indexOf(q) < 0) return false;
    }
    return true;
  }

  function filtered() {
    return LOWS.filter(passes);
  }

  function activeSeasons() {
    return DATA.seasons.filter(function (s) {
      return (state.season0 == null || s.start >= state.season0) &&
             (state.season1 == null || s.start <= state.season1);
    });
  }

  /* ----------------------------------------------------------------- KPIs */

  /** Tiny inline trend line for a KPI tile - a dozen lines of SVG rather
      than pulling in HF.charts for something this small. Colours come from
      CSS custom properties so it reads correctly in both themes. */
  function sparklineSvg(values) {
    var w = 52, h = 18;
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('class', 'k-spark');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('aria-hidden', 'true');

    var max = Math.max.apply(null, values);
    var min = Math.min.apply(null, values);
    var range = (max - min) || 1;
    var stepX = values.length > 1 ? w / (values.length - 1) : 0;
    var pad = 2;

    var pts = values.map(function (v, i) {
      var x = i * stepX;
      var y = pad + (1 - (v - min) / range) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    });

    var poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    poly.setAttribute('points', pts.join(' '));
    poly.setAttribute('fill', 'none');
    poly.setAttribute('stroke', HF.cssVar('--accent'));
    poly.setAttribute('stroke-width', '1.5');
    poly.setAttribute('stroke-linejoin', 'round');
    poly.setAttribute('stroke-linecap', 'round');
    svg.appendChild(poly);

    var lastPt = pts[pts.length - 1].split(',');
    var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('cx', lastPt[0]);
    dot.setAttribute('cy', lastPt[1]);
    dot.setAttribute('r', '1.7');
    dot.setAttribute('fill', HF.cssVar('--accent'));
    svg.appendChild(dot);

    return svg;
  }

  function renderKpis(lows) {
    var box = HF.clear(document.getElementById('kpis'));
    var seasonList = activeSeasons();
    var seasons = seasonList.length || 1;
    var bySeasonCount = {};
    lows.forEach(function (l) { bySeasonCount[l.season] = (bySeasonCount[l.season] || 0) + 1; });
    var sparkValues = seasonList.map(function (s) { return bySeasonCount[s.start] || 0; });
    var pressures = lows.map(function (l) { return l.minP; });
    var deepest = null;
    lows.forEach(function (l) {
      if (l.minP != null && (!deepest || l.minP < deepest.minP)) deepest = l;
    });
    var withBerg = lows.filter(function (l) { return l.berg != null; });
    var bombs = withBerg.filter(function (l) { return l.bomb; });
    var noCentre = lows.filter(function (l) { return l.cls !== 'low'; });
    var tipjets = lows.filter(function (l) { return l.cls === 'tipjet'; });

    var tiles = [
      { label: 'Events', value: lows.length.toLocaleString(), spark: sparkValues,
        note: lows.length ? (lows.length / seasons).toFixed(1) + ' per season over ' + seasons + ' seasons' : 'nothing matches the filters' },
      { label: 'Median min pressure',
        value: pressures.some(function (p) { return p != null; }) ? HF.median(pressures) + ' hPa' : '--',
        note: lows.length - noCentre.length
          ? 'over the ' + (lows.length - noCentre.length).toLocaleString() +
            ' events with an analyzed centre'
          : 'none of these events has an analyzed centre' },
      { label: 'Deepest event',
        value: deepest ? deepest.minP + ' hPa' : '--',
        note: deepest ? deepest.id + ' · ' + HF.fmtDate(deepest.minPAt) : '' },
      { label: 'Median time at HF',
        value: lows.length ? HF.median(lows.map(function (l) { return l.hfH; })) + ' h' : '--',
        note: '6-hourly fixes × 6 h' },
      { label: 'Explosive share',
        value: withBerg.length ? Math.round(100 * bombs.length / withBerg.length) + '%' :  '--',
        note: withBerg.length ? bombs.length + ' of ' + withBerg.length + ' events with 24 h of pressures' : 'no qualifying events' },
      { label: 'No analyzed centre',
        value: noCentre.length.toLocaleString(),
        note: tipjets.length
          ? tipjets.length + ' are Greenland tip jet candidates'
          : 'events with no central pressure at any fix' }
    ];

    tiles.forEach(function (t) {
      var card = HF.el('div', { class: 'kpi' });
      card.appendChild(HF.el('div', { class: 'k-label' }, t.label));
      card.appendChild(HF.el('div', { class: 'k-value' }, t.value));
      if (t.spark && t.spark.length > 1) card.appendChild(sparklineSvg(t.spark));
      if (t.note) card.appendChild(HF.el('div', { class: 'k-note' }, t.note));
      box.appendChild(card);
    });
  }

  /* --------------------------------------------------------------- charts */

  function basinSeries() {
    var series = [];
    DATA.basins.forEach(function (b) {
      if (state.basin === 'both' || state.basin === b.key) {
        series.push({ key: b.key, label: b.label, color: HF.basinColor(b.key) });
      }
    });
    return series;
  }

  function noCentreCount(lows) {
    return lows.filter(function (l) { return l.cls !== 'low'; }).length;
  }

  function renderCharts(lows) {
    var series = basinSeries();

    // Events per season -------------------------------------------------
    var seasons = activeSeasons();
    var bySeason = {};
    lows.forEach(function (l) {
      bySeason[l.season] = bySeason[l.season] || {};
      bySeason[l.season][l.basin] = (bySeason[l.season][l.basin] || 0) + 1;
    });
    var seasonData = seasons.map(function (s) {
      var parts = bySeason[s.start] || {};
      var total = series.reduce(function (sum, sr) { return sum + (parts[sr.key] || 0); }, 0);
      return {
        label: s.label, tick: String(s.start).slice(2) + '/' + String(s.start + 1).slice(2),
        tickRotate: seasons.length > 14,
        parts: parts, total: total, season: s.start,
        tip: '<b>' + s.label + '</b>' + series.map(function (sr) {
          return '<div class="t-row">' + sr.label + ': ' + (parts[sr.key] || 0) + '</div>';
        }).join('') + (series.length > 1 ? '<div class="t-row"><b>Total: ' + total + '</b></div>' : '')
      };
    });
    var mean = HF.mean(seasonData.map(function (d) { return d.total; }));
    HF.charts.columns(document.getElementById('chartSeason'), {
      data: seasonData, series: series, yTitle: 'Events',
      meanLine: mean != null ? { value: mean, label: 'mean ' + mean.toFixed(1) } : null,
      onClick: function (d) {
        state.season0 = state.season1 = d.season;
        syncControls();
        render();
      }
    });

    // Seasonal cycle -----------------------------------------------------
    var byMonth = {};
    lows.forEach(function (l) {
      byMonth[l.month] = byMonth[l.month] || {};
      byMonth[l.month][l.basin] = (byMonth[l.month][l.basin] || 0) + 1;
    });
    var monthData = HF.SEASON_MONTHS.map(function (m) {
      var parts = byMonth[m] || {};
      var total = series.reduce(function (sum, sr) { return sum + (parts[sr.key] || 0); }, 0);
      return {
        label: HF.monthName(m), tick: HF.monthName(m).slice(0, 1),
        parts: parts, total: total,
        tip: '<b>' + HF.monthName(m) + '</b>' + series.map(function (sr) {
          return '<div class="t-row">' + sr.label + ': ' + (parts[sr.key] || 0) + '</div>';
        }).join('')
      };
    });
    HF.charts.columns(document.getElementById('chartMonth'), {
      data: monthData, series: series, yTitle: 'Events', xTitle: 'Month of first fix'
    });

    // Minimum pressure ---------------------------------------------------
    var presBins = HF.histogram(lows, function (l) { return l.minP; }, 5, 915, 1010);
    HF.charts.histogram(document.getElementById('chartPressure'), {
      bins: presBins,
      color: function (b) { return HF.pressureColor((b.x0 + b.x1) / 2); },
      xTitle: 'Minimum central pressure (hPa)', yTitle: 'Events',
      fmtBin: function (b) { return b.x0 + '–' + (b.x1 - 1) + ' hPa'; }
    });

    // Time at hurricane force --------------------------------------------
    var hfBins = HF.histogram(lows, function (l) { return l.hfH; }, 6, 0, 78);
    HF.charts.histogram(document.getElementById('chartDuration'), {
      bins: hfBins, color: HF.cssVar('--critical'),
      xTitle: 'Hours at hurricane force', yTitle: 'Events',
      fmtBin: function (b) { return b.x0 + '–' + b.x1 + ' h'; }
    });

    // Deepening ----------------------------------------------------------
    var bergBins = HF.histogram(lows, function (l) { return l.berg; }, 0.25, -1, 3.5);
    HF.charts.histogram(document.getElementById('chartBergeron'), {
      bins: bergBins, color: HF.cssVar('--seq-5'),
      xTitle: 'Bergerons over the best 18\u201324 h window (negative = filled)',
      yTitle: 'Events',
      threshold: { x: 1, label: 'bomb' },
      fmtBin: function (b) { return b.x0.toFixed(2) + '–' + b.x1.toFixed(2) + ' B'; },
      fmtTick: function (v) { return v.toFixed(1); }
    });

    // Events with no analyzed centre ---------------------------------------
    var ncSeries = [
      { key: 'tipjet', label: 'Tip jet candidate', color: HF.classColor('tipjet') },
      { key: 'nocentre', label: 'Elsewhere', color: HF.classColor('nocentre') }
    ];
    var ncBySeason = {};
    lows.forEach(function (l) {
      if (l.cls === 'low') return;
      ncBySeason[l.season] = ncBySeason[l.season] || {};
      ncBySeason[l.season][l.cls] = (ncBySeason[l.season][l.cls] || 0) + 1;
    });
    var ncData = seasons.map(function (s) {
      var parts = ncBySeason[s.start] || {};
      var total = (parts.tipjet || 0) + (parts.nocentre || 0);
      return {
        label: s.label, tick: String(s.start).slice(2), tickRotate: seasons.length > 14,
        parts: parts, total: total, season: s.start,
        tip: '<b>' + s.label + '</b>' +
             '<div class="t-row">Tip jet candidates: ' + (parts.tipjet || 0) + '</div>' +
             '<div class="t-row">Elsewhere: ' + (parts.nocentre || 0) + '</div>'
      };
    });
    HF.charts.columns(document.getElementById('chartNoCentre'), {
      data: ncData, series: ncSeries, yTitle: 'Events', xTitle: 'Season'
    });

    // Peak intensity by latitude ------------------------------------------
    var pts = [];
    lows.forEach(function (l) {
      if (l.minP == null || l.minPLat == null) return;
      pts.push({
        x: l.minPLat, y: l.minP, color: HF.basinColor(l.basin), item: l,
        tip: '<b>' + l.id + '</b> · ' + HF.seasonLabel(l.season) +
             '<div class="t-row">' + l.minP + ' hPa at ' + l.minPLat.toFixed(1) + '°N</div>' +
             '<div class="t-row">' + HF.fmtDate(l.minPAt) + '</div>'
      });
    });
    HF.charts.scatter(document.getElementById('chartScatter'), {
      points: pts, xTitle: 'Latitude of minimum pressure (°N)',
      yTitle: 'Minimum pressure (hPa)', yInvert: true,
      xDomain: [20, 70], series: series,
      onClick: select
    });
  }

  /* ---------------------------------------------------------------- table */

  var COLUMNS = [
    { key: 'id', label: 'Event', get: function (l) { return l.id; } },
    { key: 'basin', label: 'Basin', get: function (l) { return l.basin; },
      render: function (l) {
        var span = HF.el('span', { class: 'pill' });
        var dot = HF.el('span', { class: 'legend-dot' });
        dot.style.background = HF.basinColor(l.basin);
        span.appendChild(dot);
        span.appendChild(document.createTextNode(l.basin === 'pac' ? 'Pacific' : 'Atlantic'));
        return span;
      } },
    { key: 'season', label: 'Season', get: function (l) { return l.season; },
      render: function (l) { return document.createTextNode(HF.seasonLabel(l.season)); } },
    { key: 'start', label: 'First fix', get: function (l) { return l.start; },
      render: function (l) { return document.createTextNode(HF.fmtDate(l.start)); } },
    { key: 'durH', label: 'Tracked (h)', num: true, get: function (l) { return l.durH; } },
    { key: 'hfH', label: 'At HF (h)', num: true, get: function (l) { return l.hfH; } },
    { key: 'minP', label: 'Min hPa', num: true, get: function (l) { return l.minP; },
      render: function (l) { return document.createTextNode(l.minP != null ? l.minP : '--'); } },
    { key: 'minPLat', label: 'Peak position', get: function (l) { return l.minPLat; },
      render: function (l) { return document.createTextNode(HF.fmtLatLon(l.minPLat, l.minPLon)); } },
    { key: 'berg', label: 'Max 24 h (B)', num: true, get: function (l) { return l.berg; },
      render: function (l) {
        if (l.berg == null) return document.createTextNode('--');
        var span = HF.el('span', {}, l.berg.toFixed(2));
        if (l.bomb) span.style.color = HF.cssVar('--critical');
        return span;
      } },
    { key: 'spdKt', label: 'Mean kt', num: true, get: function (l) { return l.spdKt; } },
    { key: 'distNm', label: 'Track nm', num: true, get: function (l) { return l.distNm; } }
  ];

  function renderTable(lows) {
    var table = document.getElementById('eventsTable');
    var thead = HF.clear(table.tHead || table.createTHead());
    var tbody = HF.clear(table.tBodies[0]);

    var headRow = HF.el('tr');
    COLUMNS.forEach(function (col) {
      var th = HF.el('th', { class: col.num ? 'num' : '' }, col.label);
      th.setAttribute('scope', 'col');
      if (state.sort.key === col.key) {
        th.appendChild(HF.el('span', { class: 'sort-caret' }, state.sort.dir > 0 ? '▲' : '▼'));
      }
      th.addEventListener('click', function () {
        if (state.sort.key === col.key) state.sort.dir *= -1;
        else state.sort = { key: col.key, dir: col.num || col.key === 'start' ? -1 : 1 };
        render();
      });
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);

    var col = COLUMNS.filter(function (c) { return c.key === state.sort.key; })[0] || COLUMNS[3];
    var sorted = lows.slice().sort(function (a, b) {
      var av = col.get(a), bv = col.get(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;                 // missing values sink
      if (bv == null) return -1;
      if (av < bv) return -state.sort.dir;
      if (av > bv) return state.sort.dir;
      return 0;
    });

    sorted.slice(0, TABLE_LIMIT).forEach(function (low) {
      var tr = HF.el('tr');
      if (low.key === state.selectedKey) tr.className = 'is-selected';
      COLUMNS.forEach(function (c) {
        var td = HF.el('td', { class: c.num ? 'num' : '' });
        if (c.render) td.appendChild(c.render(low));
        else td.textContent = c.get(low) == null ? '--' : c.get(low);
        tr.appendChild(td);
      });
      tr.addEventListener('click', function () { select(low); });
      tbody.appendChild(tr);
    });

    document.getElementById('tableNote').textContent =
      lows.length.toLocaleString() + ' event' + (lows.length === 1 ? '' : 's') + ' match the filters';
    document.getElementById('tableMore').textContent =
      lows.length > TABLE_LIMIT
        ? 'Showing the first ' + TABLE_LIMIT + ' by ' + col.label.toLowerCase() +
          '. Narrow the filters, or download the CSV for all ' + lows.length.toLocaleString() + '.'
        : '';
  }

  function exportCsv() {
    var lows = filtered();
    var head = ['id', 'basin', 'season', 'first_fix', 'last_fix', 'tracked_h', 'hf_h',
                'min_pressure_hpa', 'min_pressure_at', 'min_pressure_lat', 'min_pressure_lon',
                'max_24h_deepening_hpa', 'max_24h_bergerons', 'explosive', 'mean_speed_kt',
                'track_nm', 'fixes'];
    var rows = lows.map(function (l) {
      return [l.id, l.basin, HF.seasonLabel(l.season), l.start, l.end, l.durH, l.hfH,
              l.minP == null ? '' : l.minP, l.minPAt == null ? '' : l.minPAt,
              l.minPLat == null ? '' : l.minPLat, l.minPLon == null ? '' : l.minPLon,
              l.deep24 == null ? '' : l.deep24, l.berg == null ? '' : l.berg,
              l.bomb ? 'yes' : 'no', l.spdKt == null ? '' : l.spdKt, l.distNm, l.n].join(',');
    });
    var blob = new Blob([head.join(',') + '\n' + rows.join('\n')], { type: 'text/csv' });
    var a = HF.el('a', { href: URL.createObjectURL(blob), download: 'hf-lows-filtered.csv' });
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  }

  /* --------------------------------------------------------------- detail */

  function select(low) {
    if (low) {
      // Remember what had focus only when the drawer is opening, not on
      // every subsequent selection change while it stays open.
      if (state.selectedKey == null) detailTrigger = document.activeElement;
      state.selectedKey = low.key;
      renderDetail(low);
      document.body.classList.add('has-detail');
      resizeActiveView();
      HF.globe.focus(low);
    } else {
      // Escape is also wired globally and fires even with nothing selected;
      // only steal focus back when a drawer was actually open to close.
      var wasOpen = state.selectedKey != null;
      state.selectedKey = null;
      document.getElementById('detail').hidden = true;
      document.body.classList.remove('has-detail');
      resizeActiveView();
      if (wasOpen) returnFocusAfterClose();
    }
    render();
  }

  /** Escape and the close button both hide the drawer; land focus back on
      whatever opened it (a table row, a track, a chart point) when that
      element still exists, or on the active tab otherwise. */
  function returnFocusAfterClose() {
    var el = detailTrigger;
    detailTrigger = null;
    if (el && el !== document.body && document.contains(el) && typeof el.focus === 'function') {
      el.focus();
      return;
    }
    var activeTab = document.querySelector('.tab[aria-selected="true"]');
    if (activeTab) activeTab.focus();
  }

  function renderDetail(low) {
    var drawer = document.getElementById('detail');
    drawer.hidden = false;
    document.getElementById('detailTitle').textContent =
      low.id + '  ·  ' + (low.basin === 'pac' ? 'Pacific' : 'Atlantic');

    var body = HF.clear(document.getElementById('detailBody'));

    body.appendChild(HF.el('h3', {}, 'Summary'));
    var grid = HF.el('div', { class: 'stat-grid' });
    [
      ['Season', HF.seasonLabel(low.season)],
      ['Minimum pressure', low.minP != null ? low.minP + ' hPa' : 'not analyzed'],
      ['Tracked', low.durH + ' h (' + low.n + ' fixes)'],
      ['At hurricane force', low.hfH + ' h'],
      ['Max 24 h deepening', low.deep24 != null ? low.deep24.toFixed(1) + ' hPa' : 'n/a'],
      ['Normalized', low.berg != null ? low.berg.toFixed(2) + ' B' + (low.bomb ? ' — explosive' : '') : 'n/a'],
      ['Mean speed', low.spdKt != null ? low.spdKt + ' kt' : 'n/a'],
      ['Track length', low.distNm.toLocaleString() + ' nm']
    ].forEach(function (pair) {
      var stat = HF.el('div', { class: 'stat' });
      stat.appendChild(HF.el('b', {}, pair[1]));
      stat.appendChild(HF.el('span', {}, pair[0]));
      grid.appendChild(stat);
    });
    body.appendChild(grid);

    body.appendChild(HF.el('h3', {}, 'Central pressure'));
    var trace = HF.el('div', { class: 'chart' });
    body.appendChild(trace);
    HF.charts.trace(trace, low.fixes);

    body.appendChild(HF.el('h3', {}, 'Fixes'));
    var table = HF.el('table', { class: 'data-table' });
    var thead = HF.el('thead');
    var hr = HF.el('tr');
    ['Time', 'Position', 'Cat', 'hPa'].forEach(function (h) { hr.appendChild(HF.el('th', {}, h)); });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = HF.el('tbody');
    low.fixes.forEach(function (fix) {
      var tr = HF.el('tr');
      tr.appendChild(HF.el('td', {}, HF.fmtDateShort(fix.date)));
      tr.appendChild(HF.el('td', {}, HF.fmtLatLon(fix.lat, fix.lon)));

      var catCell = HF.el('td');
      var pill = HF.el('span', { class: 'pill' });
      var dot = HF.el('span', { class: 'legend-dot' });
      dot.style.background = HF.categoryColor(fix.cat);
      pill.appendChild(dot);
      pill.appendChild(document.createTextNode(fix.cat));
      pill.title = (DATA.categories[fix.cat] || {}).label || fix.cat;
      catCell.appendChild(pill);
      tr.appendChild(catCell);

      tr.appendChild(HF.el('td', { class: 'num' }, fix.pres != null ? String(fix.pres) : '--'));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var wrap = HF.el('div', { class: 'table-wrap' });
    wrap.appendChild(table);
    body.appendChild(wrap);

    // Split events keep the archive ID plus a letter ("...a"), so match that
    // base ID exactly. A plain prefix test would attach a note about ID "2" to
    // every event whose ID happens to start with a 2.
    var baseId = low.id.replace(/[a-z]$/, '');
    var notes = DATA.qc.notes.filter(function (n) {
      return n.id && (n.id === low.id || n.id === baseId);
    });
    if (notes.length || low.split || low.timesSuspect) {
      var note = HF.el('div', { class: 'drawer-note' });
      note.appendChild(HF.el('b', {}, 'Data quality'));
      var ul = HF.el('ul');
      if (low.split) {
        ul.appendChild(HF.el('li', {}, 'This event was split out of a reused archive ID.'));
      }
      if (low.timesSuspect) {
        ul.appendChild(HF.el('li', {}, 'Two fixes share a timestamp; the tracked duration is approximate.'));
      }
      notes.forEach(function (n) { ul.appendChild(HF.el('li', {}, n.detail)); });
      note.appendChild(ul);
      body.appendChild(note);
    }
  }

  /* ------------------------------------------------------------- view mode
     The globe is the only map view - both basins meet at the Arctic and no
     flat projection shows that honestly, so there is no flat-map fallback
     for a single basin either. Tracks, fix density, first fix and peak
     intensity are all layers HF.globe knows how to draw; this section just
     keeps the globe's size/visibility/rotation in step with the active tab
     and the basin filter. */

  /** The globe no-ops a resize on a hidden panel, so this is safe to call
      whenever the map tab might have just become visible; the timeout lets
      the "hidden" attribute's layout change land first. */
  function resizeActiveView() {
    setTimeout(function () { HF.globe.resize(); }, 0);
  }

  /** Only animate while the map tab is actually on screen. Call after
      anything that can change the active tab. */
  function syncMapMode() {
    HF.globe.setVisible(state.tab === 'map');
    if (state.tab === 'map') resizeActiveView();
  }

  /** Selecting a basin re-points the globe at it, derived from that basin's
      own filtered events rather than a guessed centre; "Both basins" returns
      to the default pole-centred view that shows the whole storm track belt. */
  function applyBasinSideEffects() {
    if (state.basin === 'both') HF.globe.resetView();
    else HF.globe.fitTo(filtered());
  }

  /* ------------------------------------------------------------ map chrome */

  /** "2011-12-06 to 2014-09-26" style label for the actual period the
      currents mean covers - read from the generated payload rather than
      hardcoded, so it can never drift out of sync with tools/build_currents.py.
      Returns null when currents.js failed to load, so callers can fall back
      to omitting the layer entirely instead of printing "undefined". */
  function currentsPeriodLabel() {
    var c = window.HF_CURRENTS;
    if (!c || !c.period) return null;
    return c.period.start + ' to ' + c.period.end;
  }

  function renderMap(lows) {
    HF.globe.render(lows, state.selectedKey, state.layer);
    HF.globe.setCurrentsVisible(state.currents);
    renderPlayback(lows);
    renderLegend(lows);

    var layer = state.layer;
    var note = document.getElementById('mapNote');
    if (layer === 'playback') {
      note.textContent = playbackNote(lows);
    } else if (layer === 'density') {
      note.textContent = 'Hurricane force fixes per ' + HF.globe.CELL_LAT + '° × ' +
        HF.globe.CELL_LON + '° cell, over the filtered seasons.';
    } else if (layer === 'genesis') {
      note.textContent = 'First tracked fix of each event — where the archive picked the low up, not true cyclogenesis.';
    } else if (layer === 'peak') {
      note.textContent = 'Position of each event’s lowest analyzed pressure; marker size grows as pressure falls.';
    } else {
      note.textContent = lows.length > 300
        ? lows.length.toLocaleString() + ' tracks — thinned so the overlap reads as density. ' +
          'Filter, or switch to Fix density, for a cleaner picture.'
        : lows.length.toLocaleString() + ' track' + (lows.length === 1 ? '' : 's') +
          ' shown. Click one for its fixes.';
      note.textContent += ' Drag to rotate, scroll to zoom, double-click to reset.';
    }
    if (state.currents) {
      var period = currentsPeriodLabel();
      note.textContent += ' Ocean currents: OSCAR mean surface flow' +
        (period ? ', ' + period : '') + ', shown as background.';
    }

    var attrib = document.getElementById('globeAttrib');
    if (attrib) {
      attrib.textContent = 'Coastlines: Natural Earth (public domain)' +
        (state.currents ? ' · Currents: OSCAR/NASA JPL via NOAA CoastWatch (public domain)' : '');
    }
  }

  /** Small swatch explaining the currents background layer, appended after
      whichever per-layer legend content renderLegend built - it applies
      regardless of state.layer, since currents can sit under any of them. */
  function appendCurrentsLegend(box) {
    if (!state.currents) return;
    var color = HF.globe.currentsColor && HF.globe.currentsColor();
    if (!color) return;
    var h = HF.el('h3', {}, 'Ocean currents');
    h.style.marginTop = '10px';
    box.appendChild(h);
    var scale = HF.el('div', { class: 'legend-scale' });
    [0.15, 0.35, 0.55, 0.75, 1].forEach(function (a) {
      var seg = HF.el('span');
      seg.style.background = color;
      seg.style.opacity = String(a);
      scale.appendChild(seg);
    });
    box.appendChild(scale);
    var ends = HF.el('div', { class: 'legend-ends' });
    ends.appendChild(HF.el('span', {}, 'weak'));
    ends.appendChild(HF.el('span', {}, 'strong'));
    box.appendChild(ends);
    box.appendChild(HF.el('p', { class: 'legend-note' },
      'Streamlet length and shade scale with mean current speed; orientation follows the flow. ' +
      'Multi-year OSCAR mean, not current conditions — see Method.'));
  }

  function renderLegend(lows) {
    lows = lows || [];
    var box = HF.clear(document.getElementById('mapLegend'));
    var layer = state.layer;

    if (layer === 'density') {
      box.appendChild(HF.el('h3', {}, 'HF fixes per cell'));
      var scale = HF.el('div', { class: 'legend-scale' });
      ['--seq-1', '--seq-2', '--seq-3', '--seq-4', '--seq-5', '--seq-6', '--seq-7'].forEach(function (v) {
        var seg = HF.el('span');
        seg.style.background = HF.cssVar(v);
        scale.appendChild(seg);
      });
      box.appendChild(scale);
      var ends = HF.el('div', { class: 'legend-ends' });
      ends.appendChild(HF.el('span', {}, 'few'));
      ends.appendChild(HF.el('span', {}, 'many'));
      box.appendChild(ends);
      box.appendChild(HF.el('p', { class: 'legend-note' },
        'Shaded on a square-root scale; counts are strongly skewed toward the storm track.'));
      appendCurrentsLegend(box);
      return;
    }

    if (layer === 'genesis') {
      box.appendChild(HF.el('h3', {}, 'Basin'));
      basinSeries().forEach(function (s) {
        var row = HF.el('div', { class: 'legend-row' });
        var dot = HF.el('span', { class: 'legend-dot' });
        dot.style.background = s.color;
        row.appendChild(dot);
        row.appendChild(document.createTextNode(s.label));
        box.appendChild(row);
      });
      appendCurrentsLegend(box);
      return;
    }

    // Each track segment is coloured by the MSLP at that point, not by the
    // event's lifetime minimum - the heading and note below must say so, or
    // this reads as the (now wrong) old one-colour-per-event legend.
    box.appendChild(HF.el('h3', {}, layer === 'playback' ? 'Central pressure' : 'Pressure along track'));
    // Ascending (weakest -> deepest) so the bar and its end labels always
    // match HF.PRESSURE_BANDS's own breakpoints and text, whatever they
    // currently are - never hardcode a specific hPa value here.
    var bandsAsc = HF.PRESSURE_BANDS.slice().reverse();
    var bar = HF.el('div', { class: 'legend-scale' });
    bandsAsc.forEach(function (band) {
      var seg = HF.el('span');
      seg.style.background = HF.pressureColor(band.v);
      seg.title = band.label + ' hPa';
      bar.appendChild(seg);
    });
    box.appendChild(bar);
    var ends = HF.el('div', { class: 'legend-ends' });
    ends.appendChild(HF.el('span', {}, bandsAsc[0].label + ' hPa'));
    ends.appendChild(HF.el('span', {}, bandsAsc[bandsAsc.length - 1].label + ' hPa'));
    box.appendChild(ends);
    if (layer === 'playback') {
      appendPlaybackLegend(box, lows);
      appendCurrentsLegend(box);
      return;
    }
    var terrain = lows.filter(function (l) { return l.cls !== 'low'; }).length;
    if (terrain) {
      var row = HF.el('div', { class: 'legend-row' });
      var sw = HF.el('span', { class: 'legend-swatch' });
      // Match the dashed stroke used on the map, so the legend reads the same.
      sw.style.background = 'repeating-linear-gradient(90deg, ' +
        HF.classColor('tipjet') + ' 0 5px, transparent 5px 8px)';
      row.appendChild(sw);
      row.appendChild(document.createTextNode('No analyzed centre'));
      row.style.marginTop = '6px';
      box.appendChild(row);
    }
    box.appendChild(HF.el('p', { class: 'legend-note' },
      'Colour is the analyzed MSLP at each point along the track, not the event’s overall minimum.'));
    if (state.selectedKey) {
      box.appendChild(HF.el('p', { class: 'legend-note' },
        'Markers on the selected track are coloured by category at that fix.'));
    }
    appendCurrentsLegend(box);
  }

  /* --------------------------------------------------------- static panels */

  // The Data quality tab was removed from the public UI (it duplicated the
  // per-event notes already surfaced in the detail drawer, and the raw QC
  // report was never meant to be a public page). DATA.qc.counts/notes still
  // arrive in the payload - renderDetail()'s per-event note block below and
  // docs/data/qc-report.txt both depend on that data staying put - only the
  // #qcCounts/#qcTable rendering here was deleted along with the panel.

  function renderMethod() {
    var dl = HF.clear(document.getElementById('catDefs'));
    Object.keys(DATA.categories).forEach(function (code) {
      var cat = DATA.categories[code];
      var dt = HF.el('dt');
      var pill = HF.el('span', { class: 'pill' });
      var dot = HF.el('span', { class: 'legend-dot' });
      dot.style.background = HF.categoryColor(code);
      pill.appendChild(dot);
      pill.appendChild(document.createTextNode(code));
      dt.appendChild(pill);
      dt.appendChild(document.createTextNode('  ' + cat.label));
      dl.appendChild(dt);
      dl.appendChild(HF.el('dd', {}, cat.desc));
    });

    var classDl = HF.clear(document.getElementById('classDefs'));
    Object.keys(DATA.eventClasses || {}).forEach(function (key) {
      var cls = DATA.eventClasses[key];
      var dt = HF.el('dt');
      var pill = HF.el('span', { class: 'pill' });
      var dot = HF.el('span', { class: 'legend-dot' });
      dot.style.background = HF.classColor(key);
      pill.appendChild(dot);
      pill.appendChild(document.createTextNode(cls.label));
      dt.appendChild(pill);
      classDl.appendChild(dt);
      classDl.appendChild(HF.el('dd', {}, cls.desc));
    });

    var sources = DATA.basins.map(function (b) {
      return b.label + ': ' + b.rows.toLocaleString() + ' rows from ' + b.source;
    }).join(' · ');
    document.getElementById('sourceLine').textContent =
      'Built ' + DATA.generated + ' — ' + sources + '.';

    renderBuildProvenance();
    renderCurrentsCredit();
  }

  /** Fills in the actual OSCAR period the currents mean covers, read from
      the generated payload rather than typed by hand in index.html - if
      tools/build_currents.py is ever rerun against a longer archive, this
      updates itself instead of quietly going stale. Degrades to a plain
      statement if currents.js failed to load, rather than leaving
      "undefined" in the credits. */
  function renderCurrentsCredit() {
    var el = document.getElementById('currentsPeriod');
    if (!el) return;
    var period = currentsPeriodLabel();
    var c = window.HF_CURRENTS;
    if (!period) {
      el.textContent = '(currents data unavailable)';
      return;
    }
    el.textContent = period + ' (' + c.period.nTimeSteps + ' five-day fields)';
  }

  // HF.decode() (util.js) whitelists which top-level fields of the raw
  // payload survive into DATA, and "build" (added after that list was
  // written) isn't one of them - so this reads window.HF_DATA.build
  // directly rather than DATA.build, which would always be undefined.
  function renderBuildProvenance() {
    var el = document.getElementById('buildProvenance');
    if (!el) return;
    var build = (window.HF_DATA && window.HF_DATA.build) || null;

    var commitText;
    if (!build || !build.commit) {
      // Null on the production server: it's a plain copy of the code with
      // no .git directory, not a checkout - see docs/README.md.
      commitText = 'commit unknown (no .git at build time)';
    } else {
      commitText = 'commit ' + build.commit + (build.dirty ? ' (dirty working tree)' : '');
    }

    var sourceLabel = { fetched: 'fetched from the archive sheet via Apps Script',
                         local: 'CSVs on disk (manual export or already committed)' };
    var sourceText = build && build.dataSource
      ? 'data ' + (sourceLabel[build.dataSource] || build.dataSource)
      : 'data source unrecorded';

    el.textContent = 'Provenance: ' + commitText + ' · ' + sourceText + '.';
  }

  // The page can't know for certain which of the two published copies it
  // is - see README.md - but the hostname is a good enough proxy: a
  // *.github.io host is always the GitHub Pages preview (built from the
  // CSVs committed to the repo), localhost/127.0.0.1 is a local dev server,
  // and anything else is treated as the NOAA production server and gets no
  // marker at all.
  function renderEnvBadge() {
    var el = document.getElementById('envBadge');
    if (!el) return;
    var host = window.location.hostname || '';
    var label = null, title = '';
    if (/(^|\.)github\.io$/i.test(host)) {
      label = 'Preview build';
      title = 'GitHub Pages preview, built from the CSVs committed to this repo. ' +
              'Production is served separately from the NOAA web server and may show different data.';
    } else if (host === 'localhost' || host === '127.0.0.1') {
      label = 'Local build';
      title = 'Local development server, not the production site. ' +
              'Production is served from the NOAA web server via tools/publish.py.';
    }
    if (label) {
      el.textContent = label;
      el.title = title;
      el.hidden = false;
    } else {
      el.hidden = true;
    }
  }

  /* ------------------------------------------------------- active filters */

  function seasonLabelFor(start) {
    var match = DATA.seasons.filter(function (s) { return s.start === start; })[0];
    return match ? match.label : String(start);
  }

  function addFilterChip(box, label, onRemove) {
    var chip = HF.el('span', { class: 'filter-chip' });
    chip.appendChild(document.createTextNode(label));
    var btn = HF.el('button', {
      type: 'button', class: 'filter-chip-remove', 'aria-label': 'Remove filter: ' + label
    }, '×');
    btn.addEventListener('click', onRemove);
    chip.appendChild(btn);
    box.appendChild(chip);
  }

  var CLASS_CHIP_LABELS = {
    low: 'Synoptic lows only', nopres: 'No analyzed centre', tipjet: 'Tip jet candidates'
  };

  /** One removable chip per non-default filter, kept in sync with the
      controls in both directions: the controls write state and call
      render(), which calls this; each chip's own remove button writes state
      the same way and calls render() again. */
  function renderActiveFilters() {
    var box = HF.clear(document.getElementById('activeFilters'));

    if (state.basin !== 'both') {
      addFilterChip(box, state.basin === 'atl' ? 'Atlantic' : 'Pacific', function () {
        state.basin = 'both';
        applyBasinSideEffects();
        syncControls();
        render();
      });
    }

    if (state.cls !== 'all') {
      addFilterChip(box, CLASS_CHIP_LABELS[state.cls] || state.cls, function () {
        state.cls = 'all';
        syncControls();
        render();
      });
    }

    var defS0 = defaultSeasonStart();
    var defS1 = DATA.seasons[DATA.seasons.length - 1].start;
    if (state.season0 !== defS0 || state.season1 !== defS1) {
      var seasonLabel = state.season0 === state.season1
        ? 'Season ' + seasonLabelFor(state.season0)
        : 'Seasons ' + seasonLabelFor(state.season0) + '–' + seasonLabelFor(state.season1);
      addFilterChip(box, seasonLabel, function () {
        state.season0 = defS0;
        state.season1 = defS1;
        syncControls();
        render();
      });
    }

    Object.keys(state.months).sort(function (a, b) { return a - b; }).forEach(function (m) {
      addFilterChip(box, HF.monthName(Number(m)), function () {
        delete state.months[m];
        syncControls();
        render();
      });
    });

    if (state.maxPressure < 1010) {
      addFilterChip(box, '≤ ' + state.maxPressure + ' hPa', function () {
        state.maxPressure = 1010;
        syncControls();
        render();
      });
    }

    if (state.bombOnly) {
      addFilterChip(box, 'Explosive only', function () {
        state.bombOnly = false;
        syncControls();
        render();
      });
    }

    if (state.search) {
      addFilterChip(box, 'Search "' + state.search + '"', function () {
        state.search = '';
        syncControls();
        render();
      });
    }
  }

  /** Debounced so dragging the pressure slider (which re-renders on every
      'input' tick) doesn't spam the screen-reader live region. */
  function announceResults(n) {
    clearTimeout(announceTimer);
    announceTimer = setTimeout(function () {
      document.getElementById('resultCount').textContent =
        n.toLocaleString() + ' event' + (n === 1 ? '' : 's') + ' match the current filters.';
    }, 400);
  }

  /* --------------------------------------------------------------- render */

  function render() {
    var lows = filtered();
    renderActiveFilters();
    renderKpis(lows);
    if (state.tab === 'map') renderMap(lows);
    if (state.tab === 'clim') renderCharts(lows);
    if (state.tab === 'events') renderTable(lows);
    announceResults(lows.length);
  }

  /* ------------------------------------------------------------- playback
     The transport for the Playback layer: owns the clock (what time is it
     on the axis, is it running, how fast) and every control. It does no
     drawing and no time arithmetic of its own - HF.playback says what is on
     screen at t, HF.globe draws it - so this file is only state, controls
     and announcements.

     Time model. composite and season replay are "clocks" with a domain in
     hours; `play.t` is a point on it. Season step is not a clock, it is a
     list of seasons, so there `play.season` is the position and the same
     scrubber becomes a season slider. Playing advances `play.t` by real
     elapsed time x speed (days of storm time per second), or, in step, one
     season per dwell. The advance runs inside the globe's own animation
     frame (HF.globe.setAnimator), so there is a single rAF loop.

     Accessibility notes live next to the code they explain. */

  var PB_SPEEDS = [
    { dps: 4,  dwell: 4.0 },
    { dps: 8,  dwell: 2.5 },
    { dps: 16, dwell: 1.5 },
    { dps: 32, dwell: 0.8 }
  ];
  var PB_DAY_H = 24, PB_FINE_H = 6, PB_WEEK_H = 168;   // keyboard step sizes, hours
  var PB_LIVE_GAP_MS = 1500;     // least gap between spoken updates while playing
  var PB_LIVE_DEBOUNCE_MS = 350; // settle time before speaking a user-driven change

  var play = {
    mode: 'composite',           // 'composite' | 'season' | 'step'
    season: null,                // season start year; replay + step
    t: 0,                        // hours on the current clock's axis
    playing: false,
    speed: 1,                    // index into PB_SPEEDS
    tail: 96,                    // hours or Infinity
    engine: null, lows: null,    // engine is rebuilt only when the filtered set changes
    clock: null, seasons: [],
    ticks: [], tickKey: '',
    monthIdx: -1, stepDwell: 0, lastNow: 0,
    active: 0,                   // storms in the current frame
    scrubbing: false, resumeAfterScrub: false,
    liveTimer: null, liveLast: 0, hasPlayed: false
  };

  function pbEl(id) { return document.getElementById(id); }
  function isPlayback() { return state.layer === 'playback'; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  function sameLows(a, b) {
    if (!a || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  function firstFilledSeason() {
    for (var i = 0; i < play.seasons.length; i++) if (!play.seasons[i].empty) return play.seasons[i].season;
    return play.seasons.length ? play.seasons[0].season : null;
  }

  /** Index the filtered set for playback - and ONLY when it changed. render()
      runs on every selection, theme flip and tab change as well as every
      filter change, and building the index is the one expensive step (a
      few ms), so it is skipped when the filtered array holds the very same
      events as last time. The array itself is always a fresh one. */
  function ensureEngine(lows) {
    if (play.engine && sameLows(play.lows, lows)) return;
    play.engine = HF.playback.create(lows, { seasons: DATA.seasons });
    play.lows = lows;
    play.seasons = play.engine.seasons();
    play.clock = null;
    var known = play.seasons.some(function (s) { return s.season === play.season; });
    if (!known) play.season = firstFilledSeason();
    syncSeasonPicker();
  }

  function currentClock() {
    if (play.mode === 'step') return null;
    if (!play.clock) {
      play.clock = play.mode === 'composite' ? play.engine.composite() : play.engine.season(play.season);
      play.t = play.clock.clamp(play.t);
    }
    return play.clock;
  }

  function seasonEntry() {
    for (var i = 0; i < play.seasons.length; i++) if (play.seasons[i].season === play.season) return play.seasons[i];
    return null;
  }

  function seasonIndex() {
    for (var i = 0; i < play.seasons.length; i++) if (play.seasons[i].season === play.season) return i;
    return 0;
  }

  /** Is there anything for Play to do? Composite needs any event; replay
      needs the chosen season to have one; step needs any non-empty season. */
  function canPlay() {
    if (!play.engine) return false;
    if (play.mode === 'composite') return !play.engine.empty;
    if (play.mode === 'season') { var e = seasonEntry(); return !!e && !e.empty; }
    return play.seasons.some(function (s) { return !s.empty; });
  }

  /* ---- frames ---- */

  function pushFrame() {
    if (play.mode === 'step') {
      var e = seasonEntry();
      play.active = e ? e.count : 0;
      HF.globe.setPlaybackFrame(play.engine.step(play.season), { kind: 'step' });
      return;
    }
    var frame = currentClock().at(play.t, play.tail);
    play.active = frame.storms.length;
    HF.globe.setPlaybackFrame(frame, { kind: 'clock', tailHours: play.tail });
  }

  /** One-line description of where playback is - used for the slider's
      aria-valuetext and for the live region, so both say the same thing. */
  function stateText() {
    if (play.mode === 'step') {
      var e = seasonEntry();
      if (!e) return 'No season';
      return 'Season ' + e.label + ', ' +
        (e.empty ? 'no events match the current filters' : plural(e.count, 'event', 'events'));
    }
    var n = play.active;
    return currentClock().label(play.t) + ', ' +
      (n === 0 ? 'no active storms' : plural(n, 'active storm', 'active storms'));
  }

  function setText(el, text) { if (el.textContent !== text) el.textContent = text; }

  function updateReadout() {
    var date, count;
    if (play.mode === 'step') {
      var e = seasonEntry();
      date = e ? e.label : '--';
      count = e ? (e.empty ? 'no events' : plural(e.count, 'event', 'events')) : '';
    } else {
      date = currentClock().label(play.t);
      count = play.active + ' active';
    }
    setText(pbEl('pbDate'), date);
    setText(pbEl('pbCount'), count);
  }

  function updateScrub() {
    var scrub = pbEl('pbScrub'), pct;
    if (play.mode === 'step') {
      scrub.value = String(seasonIndex());
      pct = play.seasons.length > 1 ? seasonIndex() / (play.seasons.length - 1) : 0;
    } else {
      var d = currentClock().domain;
      scrub.value = String(play.t);
      pct = d.end > d.start ? (play.t - d.start) / (d.end - d.start) : 0;
    }
    scrub.style.setProperty('--pb-fill', (Math.max(0, Math.min(1, pct)) * 100).toFixed(1) + '%');
  }

  /* ---- announcements ---- */

  /** Speak `text` through the polite live region - rate-limited.
      A screen reader speaks every change to a live region, so writing the
      date every frame (or even every day: at 8 days/s that is eight
      announcements a second) would drown out everything else. So:
        - a change the user made (scrub, key, picker, mode) is spoken once
          it has settled for 350 ms, so holding an arrow key says where it
          ended up rather than every stop on the way;
        - while playing, only a coarse landmark is spoken - a new month, or
          a new season in Season step - and never closer together than
          1.5 s; faster playback just skips landmarks;
        - a pending announcement is replaced, not queued.
      The visible date readout is not a live region and updates freely. */
  function announcePlayback(text, settleMs, minGapMs) {
    play.liveText = text;
    clearTimeout(play.liveTimer);
    var now = performance.now();
    var due = Math.max(now + settleMs, play.liveLast + minGapMs);
    play.liveTimer = setTimeout(function () {
      play.liveLast = performance.now();
      pbEl('pbLive').textContent = play.liveText;
    }, due - now);
  }

  function monthIndexAt(t) {
    var n = 0;
    for (var i = 0; i < play.ticks.length; i++) if (play.ticks[i].t <= t) n = i + 1;
    return n;
  }

  /** Everything that follows a change of position. `byUser` is false for
      the playing clock's own advance. */
  function onTimeChanged(byUser) {
    pushFrame();
    updateScrub();
    updateReadout();
    if (byUser) {
      pbEl('pbScrub').setAttribute('aria-valuetext', stateText());
      announcePlayback(stateText(), PB_LIVE_DEBOUNCE_MS, 0);
      play.monthIdx = play.mode === 'step' ? -1 : monthIndexAt(play.t);
    } else if (play.mode === 'step') {
      announcePlayback(stateText(), 0, PB_LIVE_GAP_MS);
    } else {
      var m = monthIndexAt(play.t);
      if (m !== play.monthIdx) {
        play.monthIdx = m;
        announcePlayback(stateText(), 0, PB_LIVE_GAP_MS);
      }
    }
  }

  /* ---- transport sync ---- */

  function syncSeasonPicker() {
    var sel = pbEl('pbSeason');
    var same = sel.options.length === play.seasons.length;
    for (var i = 0; same && i < play.seasons.length; i++) {
      if (sel.options[i].value !== String(play.seasons[i].season)) same = false;
    }
    if (!same) {
      HF.clear(sel);
      play.seasons.forEach(function (s) { sel.appendChild(HF.el('option', { value: s.season }, '')); });
    }
    // A season the filters emptied stays in the list and says so in words.
    play.seasons.forEach(function (s, idx) {
      sel.options[idx].textContent = s.label + (s.empty ? ' (no events)' : ' (' + plural(s.count, 'event', 'events') + ')');
    });
    if (play.season != null) sel.value = String(play.season);
  }

  function syncSpeedOptions() {
    var sel = pbEl('pbSpeed'), step = play.mode === 'step';
    if (sel.options.length !== PB_SPEEDS.length) {
      HF.clear(sel);
      PB_SPEEDS.forEach(function (s, i) { sel.appendChild(HF.el('option', { value: i }, '')); });
    }
    PB_SPEEDS.forEach(function (s, i) {
      sel.options[i].textContent = step ? s.dwell + ' s per season' : s.dps + ' days per second';
    });
    sel.value = String(play.speed);
  }

  function buildTicks(entries) {
    var box = HF.clear(pbEl('pbTicks'));
    entries.forEach(function (tk) {
      var span = HF.el('span', { class: 'pb-tick' }, tk.label);
      span.style.left = (tk.pct * 100).toFixed(2) + '%';
      box.appendChild(span);
    });
  }

  /** Scrubber range, labels and month ticks for the current mode. The ticks
      come from clock.ticks() - the engine knows where its months fall - and
      are only rebuilt when the axis itself changes. */
  function configScrub() {
    var scrub = pbEl('pbScrub'), key, entries = [];
    if (play.mode === 'step') {
      var n = play.seasons.length;
      key = 'step|' + n;
      scrub.min = '0'; scrub.max = String(Math.max(0, n - 1)); scrub.step = '1';
      scrub.setAttribute('aria-label', 'Season');
      if (play.tickKey !== key) {
        play.seasons.forEach(function (s, i) {
          if (i % 4 === 0) entries.push({ pct: n > 1 ? i / (n - 1) : 0, label: String(s.season) });
        });
      }
      play.ticks = [];
    } else {
      var c = currentClock(), d = c.domain;
      key = play.mode + '|' + play.season + '|' + d.start + '|' + d.end;
      scrub.min = String(d.start); scrub.max = String(d.end); scrub.step = '1';
      scrub.setAttribute('aria-label', play.mode === 'composite'
        ? 'Time of year, all seasons overlaid' : 'Date within the season');
      play.ticks = c.ticks();
      if (play.tickKey !== key) {
        var span = d.end - d.start || 1;
        entries = play.ticks.map(function (tk) { return { pct: (tk.t - d.start) / span, label: tk.label }; });
      }
    }
    if (play.tickKey !== key) { buildTicks(entries); play.tickKey = key; }
  }

  function syncPlayButton() {
    var btn = pbEl('pbPlay');
    // The accessible name IS the visible text, so it can never disagree
    // with what a sighted user reads, and it changes with the state. No
    // aria-pressed on top of it: a button whose name flips between Play and
    // Pause is already a complete toggle, and adding a pressed state would
    // read as "Pause, pressed".
    setText(pbEl('pbPlayText'), play.playing ? 'Pause' : 'Play');
    btn.classList.toggle('is-playing', play.playing);
    btn.disabled = !canPlay() && !play.playing;
  }

  function syncStatus() {
    var msg = '';
    if (play.mode === 'composite') {
      if (play.engine.empty) msg = 'No events match the current filters, so there is nothing to play.';
    } else {
      var e = seasonEntry();
      if (e && e.empty && play.mode === 'season') msg = 'No events in ' + e.label + ' match the current filters.';
      else if (e && e.empty) msg = 'No events in ' + e.label + ' match the current filters - the season is empty, not missing.';
      else if (!e) msg = 'No seasons to show.';
    }
    if (!play.playing && !play.hasPlayed && HF.globe.prefersReducedMotion()) {
      msg += (msg ? ' ' : '') + 'Autoplay is off because your system asks for reduced motion. Press Play to start.';
    }
    setText(pbEl('pbStatus'), msg);
  }

  function syncTransport() {
    var radios = document.querySelectorAll('input[name="pbMode"]');
    Array.prototype.forEach.call(radios, function (r) { r.checked = r.value === play.mode; });
    pbEl('pbSeasonWrap').hidden = play.mode === 'composite';
    pbEl('pbTailWrap').hidden = play.mode === 'step';
    pbEl('pbSpeedLabel').textContent = play.mode === 'step' ? 'Season dwell' : 'Speed';
    syncSpeedOptions();
    configScrub();
    syncPlayButton();
    syncStatus();
  }

  /* ---- running ---- */

  function setPlaying(on, quiet) {
    on = !!on && isPlayback() && canPlay();
    if (on === play.playing) { if (play.engine) syncPlayButton(); return; }
    play.playing = on;
    if (on) {
      play.hasPlayed = true;
      // Replay and step stop at their end; pressing Play there starts over
      // rather than sitting on the last frame doing nothing.
      if (play.mode === 'season') {
        var d = currentClock().domain;
        if (play.t >= d.end - 1) play.t = d.start;
      } else if (play.mode === 'step') {
        if (seasonIndex() >= play.seasons.length - 1) play.season = firstFilledSeason();
      }
      play.lastNow = 0;
      play.stepDwell = 0;
      HF.globe.setAnimator(animate);
    } else {
      HF.globe.setAnimator(null);
    }
    if (play.engine) {
      syncPlayButton();
      syncStatus();
      if (!on) pbEl('pbScrub').setAttribute('aria-valuetext', stateText());
      if (!quiet) announcePlayback(on ? 'Playing' : 'Paused. ' + stateText(), 0, 0);
      if (on) { pushFrame(); updateScrub(); updateReadout(); }
    }
  }

  /** The playing clock, called once per frame from inside the globe's own
      rAF loop. dt is capped at 100 ms so returning to a backgrounded tab
      resumes where it left off rather than leaping ahead. */
  function animate(now) {
    if (!play.playing) return false;
    var dt = play.lastNow ? Math.min(100, now - play.lastNow) : 0;
    play.lastNow = now;
    var sp = PB_SPEEDS[play.speed];

    if (play.mode === 'step') {
      play.stepDwell += dt / 1000;
      if (play.stepDwell < sp.dwell) return true;
      play.stepDwell = 0;
      var i = seasonIndex();
      if (i >= play.seasons.length - 1) { setPlaying(false); return false; }
      play.season = play.seasons[i + 1].season;
      syncSeasonPicker();
      onTimeChanged(false);
      return true;
    }

    var d = currentClock().domain;
    play.t += dt / 1000 * sp.dps * 24;
    if (play.t >= d.end) {
      if (play.mode === 'composite') {
        // The composite axis is a year laid end to end, so it loops.
        play.t = d.start + (play.t - d.end) % ((d.end - d.start) || 1);
      } else {
        play.t = d.end;
        onTimeChanged(false);
        setPlaying(false);
        return false;
      }
    }
    onTimeChanged(false);
    return true;
  }

  /** Switching to the Playback layer starts playing - unless the user asked
      their system for reduced motion, in which case nothing moves until they
      press Play themselves. */
  function startPlaybackOnEntry() {
    if (HF.globe.prefersReducedMotion()) { syncStatus(); return; }
    setPlaying(true, false);
  }

  /** Called from renderMap() on every render: show/hide the strip and keep
      the engine, clock and controls consistent with the filtered set. The
      time position survives a filter change (clamped to the new domain),
      and so does playing. */
  function renderPlayback(lows) {
    var on = isPlayback();
    var bar = pbEl('pbBar');
    var changed = bar.hidden === on;
    bar.hidden = !on;
    document.body.classList.toggle('pb-active', on);
    if (changed) resizeActiveView();
    if (!on) {
      if (play.playing) setPlaying(false, true);
      return;
    }
    ensureEngine(lows);
    play.clock = null;                       // domain may have moved with the filters
    currentClock();                          // re-clamps t
    syncTransport();
    if (play.playing && !canPlay()) setPlaying(false);
    pushFrame();
    updateScrub();
    updateReadout();
    pbEl('pbScrub').setAttribute('aria-valuetext', stateText());
  }

  function playbackNote(lows) {
    var tail = ' Drag to rotate, scroll to zoom, hover a storm to identify it.';
    var seasons = play.seasons.filter(function (s) { return !s.empty; }).length;
    if (play.mode === 'composite') {
      return 'All ' + (seasons || 0) + ' seasons overlaid on one season-year: where the storm track sits at each time of year. ' +
        'Circle size grows as pressure falls; tails fade with age.' + tail;
    }
    if (play.mode === 'season') {
      return 'One season on its own calendar. Circle size grows as pressure falls; tails fade with age.' + tail;
    }
    return 'Each season’s complete tracks. Circles mark each event’s lowest analyzed pressure; seasons cross-fade.' + tail;
  }

  function appendPlaybackLegend(box, lows) {
    var step = play.mode === 'step';
    var row = HF.el('div', { class: 'legend-row' });
    row.style.marginTop = '6px';
    var dot = HF.el('span', { class: 'legend-dot' });
    dot.style.background = HF.pressureColor(960);
    row.appendChild(dot);
    row.appendChild(document.createTextNode(step ? 'Lowest pressure; larger = deeper' : 'Storm now; larger = deeper'));
    box.appendChild(row);

    if (lows.some(function (l) { return l.cls !== 'low'; })) {
      var row2 = HF.el('div', { class: 'legend-row' });
      var dia = HF.el('span', { class: 'legend-diamond' });
      dia.style.background = HF.classColor('tipjet');
      row2.appendChild(dia);
      row2.appendChild(document.createTextNode('Diamond, dashed: no analyzed centre'));
      box.appendChild(row2);
    }
    if (!step) {
      var row3 = HF.el('div', { class: 'legend-row' });
      var fade = HF.el('span', { class: 'legend-fade' });
      fade.style.background = 'linear-gradient(90deg, transparent, ' + HF.cssVar('--ink-2') + ')';
      row3.appendChild(fade);
      row3.appendChild(document.createTextNode('Tail fades with age'));
      box.appendChild(row3);
    }
    box.appendChild(HF.el('p', { class: 'legend-note' },
      step ? 'Line colour is the analyzed pressure along each track.'
           : 'Line colour is the analyzed pressure along the tail.'));
  }

  /* ---- controls ---- */

  function buildPlaybackControls() {
    var scrub = pbEl('pbScrub');

    // Mode: native radios - arrow keys move between them and select, which
    // is the browser's own radio-group behaviour.
    Array.prototype.forEach.call(document.querySelectorAll('input[name="pbMode"]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) setPlayMode(r.value); });
    });

    pbEl('pbSeason').addEventListener('change', function (e) {
      play.season = Number(e.target.value);
      play.clock = null;
      if (play.mode === 'season') play.t = currentClock().domain.start;
      syncTransport();
      onTimeChanged(true);
    });

    pbEl('pbTail').addEventListener('change', function (e) {
      play.tail = e.target.value === 'inf' ? Infinity : Number(e.target.value);
      if (play.mode !== 'step') onTimeChanged(true);
    });

    pbEl('pbSpeed').addEventListener('change', function (e) {
      play.speed = Number(e.target.value);
      play.stepDwell = 0;
    });

    pbEl('pbPlay').addEventListener('click', function () { setPlaying(!play.playing); });

    // The scrubber is a native <input type=range>: focusable, with the
    // platform's own slider semantics for assistive technology and Home/End
    // to the ends for free. Only the arrows and Page keys are overridden, to
    // step in whole days rather than the one-hour granularity the range
    // needs for smooth dragging.
    scrub.addEventListener('input', function () {
      if (play.playing && !play.scrubbing) setPlaying(false, true);
      if (play.mode === 'step') {
        var s = play.seasons[Number(scrub.value)];
        if (s) play.season = s.season;
      } else {
        play.t = currentClock().clamp(Number(scrub.value));
      }
      onTimeChanged(true);
    });

    scrub.addEventListener('keydown', function (e) {
      if (play.mode === 'step') return;            // native: one season per key press
      var dh = 0;
      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') dh = e.shiftKey ? PB_FINE_H : PB_DAY_H;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') dh = -(e.shiftKey ? PB_FINE_H : PB_DAY_H);
      else if (e.key === 'PageUp') dh = PB_WEEK_H;
      else if (e.key === 'PageDown') dh = -PB_WEEK_H;
      else return;
      e.preventDefault();
      if (play.playing) setPlaying(false, true);
      play.t = currentClock().clamp(play.t + dh);
      onTimeChanged(true);
    });

    // Dragging the thumb pauses for the drag and resumes afterwards if it
    // was running, as a video scrubber does; a keyboard step just pauses.
    scrub.addEventListener('pointerdown', function () {
      play.scrubbing = true;
      play.resumeAfterScrub = play.playing;
      if (play.playing) setPlaying(false, true);
    });
    function endScrub() {
      if (!play.scrubbing) return;
      play.scrubbing = false;
      if (play.resumeAfterScrub) setPlaying(true, true);
      play.resumeAfterScrub = false;
    }
    window.addEventListener('pointerup', endScrub);
    window.addEventListener('pointercancel', endScrub);

    // If the system setting flips to reduced motion while playing, stop.
    var mq = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mq) {
      var onMq = function () { if (mq.matches) setPlaying(false); };
      if (mq.addEventListener) mq.addEventListener('change', onMq);
      else if (mq.addListener) mq.addListener(onMq);
    }
  }

  function setPlayMode(mode) {
    if (mode === play.mode) return;
    var was = play.playing;
    if (was) setPlaying(false, true);
    play.mode = mode;
    play.clock = null;
    play.monthIdx = -1;
    if (play.season == null) play.season = firstFilledSeason();
    if (mode === 'composite') play.t = 0;
    else if (mode === 'season') play.t = currentClock().domain.start;
    syncTransport();
    // The note and legend describe the mode (heads and tails vs whole tracks).
    pbEl('mapNote').textContent = playbackNote(play.lows);
    renderLegend(play.lows);
    onTimeChanged(true);
    var names = { composite: 'Composite', season: 'Season replay', step: 'Season step' };
    announcePlayback(names[mode] + '. ' + stateText(), PB_LIVE_DEBOUNCE_MS, 0);
    if (was) setPlaying(true, true);
  }

  /* -------------------------------------------------------------- controls */

  function defaultSeasonStart() {
    var first = DATA.seasons[0].start;
    var start = DATA.recordStart == null ? first : DATA.recordStart;
    return Math.max(first, Math.min(start, DATA.seasons[DATA.seasons.length - 1].start));
  }

  function syncControls() {
    document.getElementById('fBasin').value = state.basin;
    document.getElementById('fClass').value = state.cls;
    document.getElementById('fSeason0').value = String(state.season0);
    document.getElementById('fSeason1').value = String(state.season1);
    document.getElementById('fPressure').value = String(state.maxPressure);
    document.getElementById('fPressureOut').textContent =
      state.maxPressure >= 1010 ? 'any' : state.maxPressure;
    document.getElementById('fBomb').checked = state.bombOnly;
    document.getElementById('fCurrents').checked = state.currents;
    document.getElementById('fSearch').value = state.search;
    Array.prototype.forEach.call(document.querySelectorAll('#fMonths .chip'), function (chip) {
      var on = !!state.months[chip.dataset.month];
      chip.classList.toggle('is-on', on);
      chip.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function buildControls() {
    var s0 = document.getElementById('fSeason0');
    var s1 = document.getElementById('fSeason1');
    // Seasons before the period of record are partial; keep them selectable
    // but say so, and start the default view at the first complete season.
    DATA.seasons.forEach(function (s) {
      var label = s.start < DATA.recordStart ? s.label + ' (partial)' : s.label;
      s0.appendChild(HF.el('option', { value: s.start }, label));
      s1.appendChild(HF.el('option', { value: s.start }, label));
    });
    state.season0 = defaultSeasonStart();
    state.season1 = DATA.seasons[DATA.seasons.length - 1].start;

    var chips = document.getElementById('fMonths');
    HF.SEASON_MONTHS.forEach(function (m) {
      var chip = HF.el('button', { type: 'button', class: 'chip', 'aria-pressed': 'false' },
                       HF.monthName(m));
      chip.dataset.month = m;
      chip.addEventListener('click', function () {
        if (state.months[m]) delete state.months[m];
        else state.months[m] = true;
        syncControls();
        render();
      });
      chips.appendChild(chip);
    });

    s0.addEventListener('change', function () {
      state.season0 = Number(s0.value);
      if (state.season1 < state.season0) { state.season1 = state.season0; syncControls(); }
      render();
    });
    s1.addEventListener('change', function () {
      state.season1 = Number(s1.value);
      if (state.season0 > state.season1) { state.season0 = state.season1; syncControls(); }
      render();
    });

    document.getElementById('fClass').addEventListener('change', function (e) {
      state.cls = e.target.value;
      render();
    });

    document.getElementById('fBasin').addEventListener('change', function (e) {
      state.basin = e.target.value;
      applyBasinSideEffects();
      render();
    });

    var pressure = document.getElementById('fPressure');
    pressure.addEventListener('input', function () {
      state.maxPressure = Number(pressure.value);
      document.getElementById('fPressureOut').textContent =
        state.maxPressure >= 1010 ? 'any' : state.maxPressure;
      render();
    });

    document.getElementById('fBomb').addEventListener('change', function (e) {
      state.bombOnly = e.target.checked;
      render();
    });

    var search = document.getElementById('fSearch');
    var searchTimer = null;
    search.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { state.search = search.value.trim(); render(); }, 150);
    });

    document.getElementById('fReset').addEventListener('click', function () {
      state.basin = 'both';
      state.cls = 'all';
      state.season0 = defaultSeasonStart();
      state.season1 = DATA.seasons[DATA.seasons.length - 1].start;
      state.months = {};
      state.maxPressure = 1010;
      state.bombOnly = false;
      state.search = '';
      state.selectedKey = null;
      detailTrigger = null;
      document.getElementById('detail').hidden = true;
      document.body.classList.remove('has-detail');
      applyBasinSideEffects();
      syncControls();
      render();
    });

    // Roving tabindex (WAI-ARIA "Tabs" pattern, automatic activation): only
    // the selected tab sits in the page tab order, and Left/Right/Home/End
    // both move focus and switch panels.
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
    tabs.forEach(function (tab) {
      if (!tab.id) tab.id = 'tab-' + tab.dataset.panel;
      var panel = document.getElementById('panel-' + tab.dataset.panel);
      if (panel) {
        tab.setAttribute('aria-controls', panel.id);
        panel.setAttribute('aria-labelledby', tab.id);
      }
      tab.tabIndex = tab.classList.contains('is-active') ? 0 : -1;
      tab.addEventListener('click', function () { activateTab(tab); });
      tab.addEventListener('keydown', function (e) {
        var i = tabs.indexOf(tab), next = null;
        if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
        else if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
        else if (e.key === 'Home') next = tabs[0];
        else if (e.key === 'End') next = tabs[tabs.length - 1];
        if (next) { e.preventDefault(); activateTab(next); next.focus(); }
      });
    });

    function activateTab(tab) {
      state.tab = tab.dataset.panel;
      tabs.forEach(function (t) {
        var on = t === tab;
        t.classList.toggle('is-active', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
      });
      Array.prototype.forEach.call(document.querySelectorAll('.panel'), function (p) {
        p.classList.toggle('is-active', p.id === 'panel-' + state.tab);
      });
      // The footer is dead weight on the Map tab (the globe wants the room,
      // and nothing in the footer is map-specific) - hide it there via a
      // body class instead of a per-panel rule, see assets/app.css. The
      // body starts with this class already set in the HTML, matching the
      // Map tab being the default active one.
      document.body.classList.toggle('map-active', state.tab === 'map');
      if (state.tab !== 'map') setPlaying(false, true);   // nothing to watch; do not run unseen
      syncMapMode();
      render();
    }

    Array.prototype.forEach.call(document.querySelectorAll('.seg'), function (seg) {
      seg.addEventListener('click', function () {
        var prev = state.layer;
        state.layer = seg.dataset.layer;
        Array.prototype.forEach.call(document.querySelectorAll('.seg'), function (s) {
          s.classList.toggle('is-active', s === seg);
          // The active layer used to be shown by colour alone; aria-pressed
          // says the same thing to assistive technology.
          s.setAttribute('aria-pressed', s === seg ? 'true' : 'false');
        });
        render();
        if (state.layer === 'playback' && prev !== 'playback') startPlaybackOnEntry();
      });
    });
    buildPlaybackControls();

    document.getElementById('fitBounds').addEventListener('click', function () {
      HF.globe.fitTo(filtered());
    });

    // Independent of the .seg layer switch above - can be shown under any
    // of Tracks/Fix density/First fix/Peak intensity, so it just flips its
    // own bit of state and re-renders rather than touching state.layer.
    document.getElementById('fCurrents').addEventListener('change', function (e) {
      state.currents = e.target.checked;
      render();
    });
    document.getElementById('exportCsv').addEventListener('click', exportCsv);
    document.getElementById('detailClose').addEventListener('click', function () { select(null); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') select(null);
    });
    document.getElementById('themeToggle').addEventListener('click', toggleTheme);

    // Charts are drawn at their container's pixel width, so a resize needs a
    // redraw rather than CSS scaling.
    var resizeTimer = null;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        if (state.tab === 'clim') renderCharts(filtered());
        HF.globe.resize();
      }, 180);
    });
  }

  /* ----------------------------------------------------------------- theme */

  function currentlyDark() {
    var set = document.documentElement.getAttribute('data-theme');
    if (set) return set === 'dark';
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  function toggleTheme() {
    var next = currentlyDark() ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('hf-theme', next); } catch (err) { /* private mode */ }
    HF.globe.applyTheme();
    render();
  }

  function restoreTheme() {
    try {
      var saved = localStorage.getItem('hf-theme');
      if (saved) document.documentElement.setAttribute('data-theme', saved);
    } catch (err) { /* private mode */ }
  }

  /* ------------------------------------------------------------------ boot */

  function boot() {
    var loadingEl = document.getElementById('loading');
    var mainEl = document.querySelector('main');
    var kpisEl = document.getElementById('kpis');

    // Not data-dependent - runs even if the payload below fails to load.
    renderEnvBadge();

    if (!window.HF_DATA) {
      loadingEl.hidden = true;
      document.getElementById('vintage').textContent = 'data failed to load';
      showLoadFailure(mainEl);
      return;
    }

    // The payload is ~600 KB and decoding it plus the first render (charts,
    // ~1900 map tracks, the events table) takes real, visible time - show
    // the skeleton and defer the heavy work one tick so the browser actually
    // paints it before the main thread blocks, rather than a token flash.
    loadingEl.hidden = false;
    if (mainEl) mainEl.hidden = true;
    if (kpisEl) kpisEl.hidden = true;

    setTimeout(function () {
      restoreTheme();
      DATA = HF.decode(window.HF_DATA);
      LOWS = DATA.lows;
      HF.CATEGORIES = DATA.categories;

      document.getElementById('vintage').textContent =
        DATA.lows.length.toLocaleString() + ' events, ' +
        DATA.seasons[0].label + ' to ' + DATA.seasons[DATA.seasons.length - 1].label;

      buildControls();
      syncControls();
      renderMethod();

      // Unhide before initializing the globe and doing the first render, so
      // the canvas measures a real, laid-out container instead of a hidden
      // (zero-size) one.
      loadingEl.hidden = true;
      if (mainEl) mainEl.hidden = false;
      if (kpisEl) kpisEl.hidden = false;

      HF.globe.init('globe', select);
      HF.globe.applyTheme();
      syncMapMode();
      render();
    }, 0);
  }

  /** window.HF_DATA is baked into data/hf-lows.js at build time; its total
      absence (script blocked, wrong path, opened some other way) means
      there is nothing to show, so say that plainly instead of leaving a
      page that looks broken. */
  function showLoadFailure(mainEl) {
    var box = HF.el('div', { class: 'card prose' });
    box.style.margin = 'var(--sp-5)';
    box.appendChild(HF.el('h2', {}, 'Data failed to load'));
    box.appendChild(HF.el('p', {},
      'window.HF_DATA is missing, so the archive has nothing to show. Reload the page, ' +
      'or confirm docs/data/hf-lows.js is being served alongside this page.'));
    if (mainEl && mainEl.parentNode) mainEl.parentNode.insertBefore(box, mainEl);
    else document.body.appendChild(box);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

})(window.HF);
