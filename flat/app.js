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
    // Teleconnections hosts the same canvas, but only its composite view
    // shows the map; the regression view has no globe to animate.
    var showsGlobe = state.tab === 'map' || (state.tab === 'tele' && tele.view === 'composite');
    HF.globe.setVisible(showsGlobe);
    if (showsGlobe) resizeActiveView();
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
    if (state.tab === 'tele') { renderTele(); return; }
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
      // The Filters bar and KPI strip describe the filtered archive, which a
      // composite deliberately ignores (see the teleconnections section), so
      // they are hidden there rather than left to look like they apply.
      document.body.classList.toggle('tele-active', state.tab === 'tele');
      if (state.tab !== 'map') setPlaying(false, true);   // nothing to watch; do not run unseen
      placeGlobe();
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
        if (state.tab === 'tele') {
          if (tele.view === 'regress') { if (reg.shown && !reg.shown.error) { renderRegPlot(reg.shown); renderRegMjo(reg.shown); } }
          else renderTeleSeries();
        }
        HF.globe.resize();
      }, 180);
    });
  }

  /* ------------------------------------------------------- teleconnections
     "Does the storm track look different when a climate index is in a given
     state, and can that be told from noise?" This section is wiring only:
     HF.teleconnect picks the events, HF.composite.compare() decides whether
     the difference is real, HF.globe draws the cells, HF.charts draws the
     index. What lives here is the part that decides how the answer is
     SAID, because that is where a tool like this misleads people.

     The honest answer at this sample size is usually "no part of the storm
     track differs from the archive by more than chance". An unstippled map
     can look like a quiet result or like a broken one, and a reader will
     take whichever they were hoping for. So the statistics card states the
     count, in words, first - and it states what kind of null it is: eight
     El Nino winters cannot rule out a modest shift, and "not detected" is
     not "absent". The numbers come from the result object untouched; this
     file formats them and never recomputes, rounds toward significance, or
     drops a warning.

     Scope on purpose: the Filters bar does not apply on this tab (it is
     hidden, see activateTab). A composite is the archive's complete seasons
     against the subset a climate state selects, so n_events and n_seasons
     printed here are the real ones; a hand-narrowed baseline would make
     "the archive" mean something different on every click.

     Cost and feedback. compare() takes a few tenths of a second to ~0.7 s
     on the whole archive at 5,000 draws and cannot be cut into slices, so it
     is never run from an event handler. A control change marks the card
     pending at once (aria-busy, a banner, the old numbers dimmed AND labelled
     as the previous selection), and the work starts after a short debounce,
     so dragging the lag slider across five positions costs one run, not
     five. Results are kept by selection (the seed is fixed, so the same
     selection always gives the same map), which makes going back instant. */

  var TELE_DEBOUNCE_MS = 220;
  var TELE_CACHE_MAX = 30;
  var TELE_DRAWS = 5000;

  var TELE_INDEX_NAMES = {
    nao: 'North Atlantic Oscillation (NAO)',
    pna: 'Pacific/North American pattern (PNA)',
    ao: 'Arctic Oscillation (AO)'
  };
  var TELE_ENSO_NAMES = { E: 'El Niño', N: 'ENSO-neutral', L: 'La Niña' };

  var tele = {
    index: 'enso', enso: 'E', terc: 'upper', lon: null, mjoState: 'enhanced', lag: 2,
    fieldUser: null,        // 'rate' | 'shape' once the reader chooses; until then the design picks
    engine: null, failed: null,
    cache: {}, order: [],
    want: null, timer: null,
    shown: null,            // the bundle the card, map and chart are showing
    built: false,
    view: 'composite'       // 'composite' | 'regress': two ways of asking, one tab
  };

  function tEl(id) { return document.getElementById(id); }
  function tx(tag, cls, text) { return HF.el(tag, cls ? { 'class': cls } : null, text); }
  function fmtInt(n) { return Number(n).toLocaleString(); }
  function signed(v, d) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d); }
  function pentadText(lag) {
    return lag + (lag === 1 ? ' pentad' : ' pentads') + ' (' + (lag * 5) + ' days)';
  }

  /** The engine, or null (with tele.failed saying why). Created lazily so a
      load failure costs this tab only, never the rest of the site. */
  function teleEngine() {
    if (tele.engine || tele.failed) return tele.engine;
    try {
      if (!window.HF_TELECONNECTIONS || !HF.teleconnect || !HF.composite) {
        throw new Error('the index data or the teleconnection scripts did not load');
      }
      tele.engine = HF.teleconnect.create({ archive: DATA });
      if (tele.lon == null) tele.lon = tele.engine.longitudes.indexOf('120W') >= 0 ? '120W' : tele.engine.longitudes[0];
    } catch (err) {
      tele.failed = String(err && err.message ? err.message : err);
    }
    return tele.engine;
  }

  function teleSpec() {
    if (tele.index === 'enso') return { type: 'enso', phase: tele.enso };
    if (tele.index === 'mjo') {
      return { type: 'mjo', lon: tele.lon, state: tele.mjoState, lag: tele.lag };
    }
    return { type: 'tercile', index: tele.index, group: tele.terc };
  }

  function teleKey(spec) {
    return [spec.type, spec.phase, spec.index, spec.group, spec.lon, spec.state, spec.lag].join('|');
  }

  function teleLabel(spec) {
    if (spec.type === 'enso') return TELE_ENSO_NAMES[spec.phase] + ' seasons';
    if (spec.type === 'tercile') {
      return spec.group.charAt(0).toUpperCase() + spec.group.slice(1) + ' third of the ' +
             spec.index.toUpperCase();
    }
    return 'MJO ' + spec.state + ' at ' + spec.lon + ', ' + pentadText(spec.lag) + ' earlier';
  }

  /** What "in this subset" means, in one or two sentences, for the control
      card. Thresholds and cut points are read from the engine, not typed. */
  function teleDefinition(spec) {
    var tc = tele.engine;
    if (spec.type === 'enso') {
      var th = (window.HF_TELECONNECTIONS.oni.thresholds) || { elNino: 0.5, laNina: -0.5 };
      var rule = spec.phase === 'E' ? 'at or above ' + signed(th.elNino, 1)
               : spec.phase === 'L' ? 'at or below ' + signed(th.laNina, 1)
               : 'between ' + signed(th.laNina, 1) + ' and ' + signed(th.elNino, 1);
      return 'Seasons (1 June to 31 May) whose December–February Oceanic Niño Index is ' + rule +
             ' °C. Every storm in those seasons is in the subset, so this is a comparison of whole seasons.';
    }
    if (spec.type === 'tercile') {
      var cut = tc.terciles(spec.index, 'mean5');
      var rng = spec.group === 'upper' ? 'at or above ' + signed(cut.upper, 2)
              : spec.group === 'lower' ? 'at or below ' + signed(cut.lower, 2)
              : 'between ' + signed(cut.lower, 2) + ' and ' + signed(cut.upper, 2);
      return 'Storms whose first fix falls on a day when the 5-day mean ' + spec.index.toUpperCase() +
             ' (' + TELE_INDEX_NAMES[spec.index] + ') is ' + rng + '. The thirds are taken over every day of the ' +
             'complete seasons, not over the storms, so the three groups are not equal in size.';
    }
    var thr = tc.defaultThreshold;
    var cond = spec.state === 'enhanced' ? 'at or below ' + signed(-thr, 1) + ' (enhanced convection)'
             : spec.state === 'suppressed' ? 'at or above ' + signed(thr, 1) + ' (suppressed convection)'
             : 'within ' + '±' + thr.toFixed(1) + ' of zero';
    return 'Storms whose pentad (5-day period) is preceded, ' + pentadText(spec.lag) + ' earlier, by an MJO index at ' +
           spec.lon + ' ' + cond + '. This is the CPC velocity-potential index at one longitude, not RMM.';
  }

  /* ---------------------------------------------------------------- run */

  function teleCompute(spec) {
    var tc = tele.engine;
    var t0 = Date.now();
    var b = {
      spec: spec, key: teleKey(spec), label: teleLabel(spec), defn: teleDefinition(spec),
      subset: [], unattributed: 0, result: null, error: null, model: null, ms: 0
    };
    try {
      b.subset = tc.select(LOWS, spec);
      b.unattributed = tc.unattributed(LOWS, spec).length;
      // minSeason is not optional: seasons before recordStart are short-counted
      // (not quiet) and manufacture signal; see composite.js. LOWS goes in
      // whole so the exclusion is counted and reported in result.warnings.
      b.result = HF.composite.compare(LOWS, b.subset, {
        seasons: DATA.seasons, minSeason: DATA.recordStart, iterations: TELE_DRAWS, seed: 1
      });
      b.model = teleModel(b);
    } catch (err) {
      b.error = String(err && err.message ? err.message : err);
    }
    b.ms = Date.now() - t0;
    return b;
  }

  /** Called on every control change. Cached selections show at once; others
      go pending, then run after the debounce. Only the latest selection ever
      runs (tele.want), so a burst of changes is one computation. */
  function teleRequest(soon) {
    if (!teleEngine()) { renderTele(); return; }
    var spec = teleSpec(), key = teleKey(spec);
    tele.want = key;
    clearTimeout(tele.timer);
    tele.timer = null;
    syncTeleControls();
    if (tele.cache[key]) { teleShow(tele.cache[key]); return; }
    teleSetPending(true, spec);
    tele.timer = setTimeout(function () {
      tele.timer = null;
      if (tele.want !== key || state.tab !== 'tele') return;
      var b = teleCompute(spec);
      if (!b.error) {
        tele.cache[key] = b;
        tele.order.push(key);
        while (tele.order.length > TELE_CACHE_MAX) delete tele.cache[tele.order.shift()];
      }
      if (tele.want === key) teleShow(b);
    }, soon ? 30 : TELE_DEBOUNCE_MS);
  }

  function teleSetPending(on, spec) {
    var card = tEl('teleStats');
    card.setAttribute('aria-busy', on ? 'true' : 'false');
    card.classList.toggle('is-pending', on);
    tEl('teleMapCardWrap').classList.toggle('is-pending', on);
    var p = tEl('telePending');
    p.hidden = !on;
    if (!on) return;
    p.textContent = tele.shown
      ? 'Updating for ' + teleLabel(spec) + ' (resampling ' + fmtInt(TELE_DRAWS) + ' draws). ' +
        'The numbers and map below are still for ' + tele.shown.label + ' and are out of date until this finishes.'
      : 'Working on ' + teleLabel(spec) + ' (resampling ' + fmtInt(TELE_DRAWS) + ' draws)…';
  }

  function teleShow(b) {
    tele.shown = b;
    teleSetPending(false);
    if (b.error) {
      renderTeleFailure('The test could not run for ' + b.label + ': ' + b.error);
      return;
    }
    if (tele.fieldUser == null) {
      var def = b.result.design === 'events' ? 'shape' : 'rate';
      var radio = document.querySelector('input[name="teleField"][value="' + def + '"]');
      if (radio) radio.checked = true;
    }
    renderTeleStats(b);
    teleDrawMap(b);
    renderTeleSeries();
    renderTeleTable(b);
    tEl('teleDefn').textContent = b.defn;
    announceTele(b);
  }

  function teleField(b) {
    if (tele.fieldUser) return tele.fieldUser;
    return b && b.result && b.result.design === 'events' ? 'shape' : 'rate';
  }

  /* ------------------------------------------------------- the words */

  var TELE_RELIABILITY = {
    ok: ['Adequate', 'The sample is large enough for the test to run and to mean something.'],
    low: ['Low', 'Too few seasons define this subset for the absence of a result to count for much. The map is drawn washed out and marked provisional.'],
    none: ['None', 'The test did not run, so there is no result to read.']
  };

  /** The one sentence that matters, as a plain object: {tone, title, text}.
      tone: 'untested' (nothing was tested), 'null' (tested, nothing passes),
      'found' (tested, some cells pass). */
  function teleVerdict(b) {
    var r = b.result, S = r.summary;
    var ran = r.status === 'ok' && r.inference && !r.identical && S.rate.nTested > 0;
    if (!ran) {
      var why = r.reason ||
        (r.identical ? 'This subset is the whole archive, so there is nothing to compare it with.' : null) ||
        (S.rate.nTested === 0 ? 'No cell holds enough storms in the full archive to be tested.' : null) ||
        'The test did not run.';
      return {
        tone: 'untested', icon: '—', title: 'Not tested',
        text: 'No test was run, so this page makes no statement about whether the storm track differs. ' + why +
              ' The map is not drawn. This is a limit of the sample, not a result.'
      };
    }
    var nR = S.rate.nSigFDR, nS = S.shape.nSigFDR, m = S.rate.nTested;
    if (nR === 0 && nS === 0) {
      var none = 'No part of the storm track differs from the archive by more than chance would produce. ' +
                 'None of the ' + fmtInt(m) + ' cells tested passes false discovery rate control, for either activity rate or ' +
                 'track shape. ';
      if (r.reliability === 'low') {
        // Tested, but with little power: a different statement from a clean null.
        return {
          tone: 'lowpower', icon: '\u25d0', title: 'No significant difference, but low power',
          text: none + 'Only ' + r.n.seasons + ' seasons define this subset, so the test could only have found a large ' +
                'shift. This is not evidence that the climate state has no effect; the sample is too small to say.'
        };
      }
      return {
        tone: 'null', icon: '\u25cb', title: 'No significant difference',
        text: none + 'That describes this sample; it is not proof that the climate state has no effect.'
      };
    }
    var pct = Math.round((S.rate.alphaFDR != null ? S.rate.alphaFDR : 0.1) * 100);
    return {
      tone: 'found', icon: '●', title: 'Some cells differ beyond chance',
      text: 'After false discovery rate control, ' + fmtInt(nR) + (nR === 1 ? ' cell differs' : ' cells differ') +
            ' in activity rate and ' + fmtInt(nS) + ' in track shape, out of ' + fmtInt(m) +
            ' tested. The control accepts that up to about ' + pct + '% of the cells it flags could be false alarms, so ' +
            'trust a coherent patch of flagged cells more than any single one.' +
            (r.reliability === 'low' ? ' Few seasons define this subset, so treat what is flagged as provisional.' : '')
    };
  }

  function teleControlled(r) {
    if (r.design === 'seasons') {
      return 'Compared as whole seasons: the null is built by resampling seasons, the unit that shares a background state.';
    }
    if (r.design === 'events' && r.strata) {
      return r.strata.scheme === 'auto'
        ? 'Controlled for season, month and basin: labels were re-dealt only within ' + fmtInt(r.strata.n) +
          ' season-month-basin blocks, so a subset drawn heavily from October, or from one basin, is not mistaken for an index effect.'
        : 'Labels were re-dealt within ' + fmtInt(r.strata.n) + ' blocks (scheme: ' + r.strata.scheme + ').';
    }
    return null;
  }

  function telePowerNote(b) {
    var r = b.result, k = r.n.seasons;
    if (r.design === 'seasons') {
      if (k >= 10) return null;
      var head = 'Statistical power. In synthetic tests this method found a 10-degree shift in the storm track from ' +
                 '5 defining seasons upward, and did not find it at 3 or 4. This subset has ' + k + ' defining season' +
                 (k === 1 ? '' : 's') + '. ';
      if (k < 5) {
        return head + 'That is below the point where the test is allowed to run.';
      }
      return head + (k <= 7
        ? 'That sits at the edge of what the test can resolve, so low power is expected: '
        : 'That is still a small sample, so low power is expected: ') +
        'a result of “no significant cells” means “no shift large enough to detect”, not “no effect”.';
    }
    if (r.design === 'events') {
      return 'Statistical power. This subset is a slice of events spread across seasons, so there are no defining ' +
             'seasons to count; the test re-deals which events carry the label within each season, month and basin. ' +
             'It does not model dependence between storms of one episode (two storms from one MJO event, say), so ' +
             'treat a significant cell as optimistic and a null as weak evidence of no effect.';
    }
    return null;
  }

  /* ------------------------------------------------------ stats card */

  function teleTable(cap, headers, rows) {
    var t = tx('table', 'data-table tele-t');
    t.appendChild(tx('caption', 'sr-only', cap));
    var thead = tx('thead'), htr = tx('tr');
    headers.forEach(function (h, i) {
      var th = tx('th', i ? 'num' : '', h);
      th.setAttribute('scope', 'col');
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    t.appendChild(thead);
    var tbody = tx('tbody');
    rows.forEach(function (row) {
      var tr = tx('tr');
      row.forEach(function (cell, i) {
        var node = i === 0 ? tx('th', '') : tx('td', 'num');
        if (i === 0) node.setAttribute('scope', 'row');
        if (cell && cell.nodeType) node.appendChild(cell); else node.textContent = String(cell);
        tr.appendChild(node);
      });
      tbody.appendChild(tr);
    });
    t.appendChild(tbody);
    return t;
  }

  function renderTeleStats(b) {
    var body = HF.clear(tEl('teleStatsBody'));
    var r = b.result, n = r.n, S = r.summary;
    var v = teleVerdict(b);

    body.appendChild(tx('p', 'tele-showing', 'Showing: ' + b.label));

    // 1. the verdict ----------------------------------------------------
    var box = tx('div', 'tele-verdict is-' + v.tone);
    var head = tx('p', 'tele-verdict-title');
    head.appendChild(tx('span', 'tele-verdict-icon', v.icon));
    head.lastChild.setAttribute('aria-hidden', 'true');
    head.appendChild(document.createTextNode(v.title));
    box.appendChild(head);
    box.appendChild(tx('p', 'tele-verdict-text', v.text));
    body.appendChild(box);

    // What the null controls for. Surfaced beside the verdict, not left to
    // the warnings list below, because it is what makes a result defensible.
    var ctl = teleControlled(r);
    if (ctl) body.appendChild(tx('p', 'tele-controlled', ctl));

    // 2. sample sizes ---------------------------------------------------
    body.appendChild(tx('h3', '', 'Sample size'));
    var subLabel = r.design === 'seasons' ? 'seasons define it' : 'seasons contain one';
    body.appendChild(teleTable('Events and seasons in the subset and in the archive baseline',
      ['Group', 'Events', 'Seasons'],
      [['This subset', fmtInt(n.events), fmtInt(n.seasons)],
       ['Archive baseline', fmtInt(n.allEvents), fmtInt(n.allSeasons)]]));
    var sizeNote = n.events ? n.seasons + ' ' + subLabel + '. ' : '';
    sizeNote += 'The baseline is every complete season (from ' + HF.seasonLabel(DATA.recordStart) + ').';
    if (b.unattributed) {
      sizeNote += ' ' + fmtInt(b.unattributed) + ' event' + (b.unattributed === 1 ? ' has' : 's have') +
                  ' no index value for this selection and ' + (b.unattributed === 1 ? 'is' : 'are') +
                  ' in the baseline only.';
    } else {
      sizeNote += ' Every event in those seasons has an index value for this selection.';
    }
    body.appendChild(tx('p', 'tele-note', sizeNote));

    // 3. cell counts ----------------------------------------------------
    body.appendChild(tx('h3', '', 'Cells tested'));
    function fdrCell(count) {
      var s = tx('span', 'tele-fdr' + (count ? ' has-hits' : ''));
      s.appendChild(tx('strong', '', fmtInt(count)));
      s.appendChild(document.createTextNode(count ? ' flagged' : ' none'));
      return s;
    }
    var alphaPct = Math.round((S.rate.alpha != null ? S.rate.alpha : 0.05) * 100);
    var ran = v.tone !== 'untested';
    // When nothing was tested the summary holds zeros that mean "not run",
    // and a column of zeros under "Significant" would read as a null result.
    // The answer column comes first, so on a narrow screen (where the table
    // scrolls sideways) it is the part that cannot be scrolled out of view.
    var rows = ran ? [
      ['Activity rate', fdrCell(S.rate.nSigFDR), fmtInt(S.rate.nTested), fmtInt(S.rate.nSigCell), S.rate.expectedByChance.toFixed(1)],
      ['Track shape', fdrCell(S.shape.nSigFDR), fmtInt(S.shape.nTested), fmtInt(S.shape.nSigCell), S.shape.expectedByChance.toFixed(1)]
    ] : [
      ['Activity rate', 'not tested', '\u2014', '\u2014', '\u2014'],
      ['Track shape', 'not tested', '\u2014', '\u2014', '\u2014']
    ];
    var cellsTable = teleTable('Cells tested: the count significant after FDR control, then cells tested, cells passing an uncorrected test, and the number expected by chance',
      ['Measure', 'Significant after FDR', 'Cells tested', 'Pass ' + alphaPct + '% alone', 'Expected by chance'], rows);
    var wrap = tx('div', 'tele-t-wrap');
    wrap.appendChild(cellsTable);
    body.appendChild(wrap);
    var sentence;
    if (ran) {
      sentence = 'Of ' + fmtInt(S.rate.nTested) + ' cells tested, ' + fmtInt(S.rate.nSigCell) + (S.rate.nSigCell === 1 ? ' passes' : ' pass') +
        ' an uncorrected ' + alphaPct + '% test on activity rate and ' + fmtInt(S.shape.nSigCell) + ' on track shape; about ' + S.rate.expectedByChance.toFixed(1) +
        ' would pass by chance alone. ' +
        (S.rate.nSigFDR + S.shape.nSigFDR === 0
          ? 'Once the test allows for looking at ' + fmtInt(S.rate.nTested) + ' cells at once, none remain.'
          : 'After allowing for looking at ' + fmtInt(S.rate.nTested) + ' cells at once, ' +
            fmtInt(S.rate.nSigFDR) + ' remain on rate and ' + fmtInt(S.shape.nSigFDR) + ' on shape.');
    } else {
      sentence = 'No counts are given because no cell was tested; that is not the same as testing and finding nothing.';
    }
    body.appendChild(tx('p', 'tele-note', sentence));
    var measureNote = 'Activity rate is storm fixes per season in a cell, subset minus archive: busier or quieter. ' +
      'Track shape is where the subset puts its storms once its overall activity is matched to the archive’s: ' +
      'did the track move.';
    if (r.design === 'events') {
      measureNote += ' For a slice of events like this one, activity rate is lower nearly everywhere by construction, so track shape is the measure to read.';
    }
    body.appendChild(tx('p', 'tele-note', measureNote));

    // 4. reliability and power -------------------------------------------
    body.appendChild(tx('h3', '', 'Reliability'));
    var rel = TELE_RELIABILITY[r.reliability] || [String(r.reliability), ''];
    var relP = tx('p', 'tele-reliability is-' + r.reliability);
    relP.appendChild(tx('strong', '', rel[0] + '.'));
    relP.appendChild(document.createTextNode(' ' + rel[1]));
    body.appendChild(relP);
    var power = telePowerNote(b);
    if (power) body.appendChild(tx('p', 'tele-power', power));

    // 5. every warning, verbatim ------------------------------------------
    body.appendChild(tx('h3', '', 'Warnings from the test'));
    if (r.warnings && r.warnings.length) {
      var ul = tx('ul', 'tele-warnings');
      r.warnings.forEach(function (w) { ul.appendChild(tx('li', '', w)); });
      body.appendChild(ul);
    } else {
      body.appendChild(tx('p', 'tele-note', 'None.'));
    }

    // 6. what was compared ------------------------------------------------
    var design = r.design === 'seasons'
      ? 'Whole seasons are compared and the season is the unit that is resampled.'
      : r.design === 'events'
        ? 'Events are compared and labels are re-dealt within each season, month and basin.'
        : '';
    if (design) body.appendChild(tx('p', 'tele-note', design));
    if (r.design === 'seasons' && n.subsetSeasons && n.subsetSeasons.length) {
      body.appendChild(tx('p', 'tele-note',
        'Defining seasons: ' + n.subsetSeasons.map(function (s) { return HF.seasonLabel(s); }).join(', ') + '.'));
    }
    if (r.status !== 'ok' && r.reason) body.appendChild(tx('p', 'tele-note', 'Reason: ' + r.reason));
  }

  function renderTeleFailure(message) {
    var body = HF.clear(tEl('teleStatsBody'));
    var box = tx('div', 'tele-verdict is-untested');
    var head = tx('p', 'tele-verdict-title');
    head.appendChild(tx('span', 'tele-verdict-icon', '—'));
    head.lastChild.setAttribute('aria-hidden', 'true');
    head.appendChild(document.createTextNode('Not tested'));
    box.appendChild(head);
    box.appendChild(tx('p', 'tele-verdict-text', message));
    body.appendChild(box);
    HF.clear(tEl('teleSeriesCap'));
    HF.clear(tEl('chartTele'));
    tEl('teleMapCap').textContent = 'No map is drawn.';
    HF.clear(tEl('teleLegend'));
    if (HF.globe.setComposite) { HF.globe.setComposite(null); HF.globe.render(LOWS, null, 'composite'); }
    tEl('teleLive').textContent = 'Not tested. ' + message;
  }

  /** One finished-result sentence for the polite live region. Written once
      per completed run (never while pending), and it carries the answer,
      not just the sizes. */
  function announceTele(b) {
    var r = b.result, n = r.n, v = teleVerdict(b);
    var text = b.label + ': ' + fmtInt(n.events) + ' events in ' + n.seasons + ' seasons, against ' +
      fmtInt(n.allEvents) + ' events in ' + n.allSeasons + ' seasons. ' + v.title + '. ';
    if (v.tone === 'untested') {
      text += 'Nothing was tested.';
    } else {
      text += fmtInt(r.summary.rate.nSigFDR) + ' of ' + fmtInt(r.summary.rate.nTested) +
        ' cells significant on activity rate and ' + fmtInt(r.summary.shape.nSigFDR) +
        ' on track shape after false discovery rate control; about ' + r.summary.rate.expectedByChance.toFixed(1) +
        ' would pass an uncorrected test by chance. Reliability ' + (TELE_RELIABILITY[r.reliability] || [r.reliability])[0].toLowerCase() + '.';
    }
    tEl('teleLive').textContent = text;
  }

  /* --------------------------------------------------------- the map */

  function teleDrawMap(b) {
    var cap = tEl('teleMapCap');
    if (typeof HF.globe.setComposite !== 'function') {
      cap.textContent = 'This build of the map has no composite layer, so no map is drawn. The statistics beside it are unaffected.';
      HF.clear(tEl('teleLegend'));
      return;
    }
    var r = b.result;
    var field = teleField(b);
    var st = HF.globe.setComposite(r, { field: field });
    HF.globe.render(LOWS, null, 'composite');

    var n = r.n, S = r.summary[field];
    var fieldName = field === 'shape' ? 'track shape' : 'activity rate';
    var text;
    if (st && !st.drawn) {
      text = 'No map is drawn: ' + (st.reason || 'the test did not run.') + ' The statistics are the answer here.';
    } else {
      text = 'Composite of ' + fmtInt(n.events) + ' events (' + n.seasons + ' seasons) against ' + fmtInt(n.allEvents) +
        ' events (' + n.allSeasons + ' seasons). Colour is the difference in ' + fieldName + ' from the archive; ' +
        'dots mark the cells that pass false discovery rate control.';
      if (S.nSigFDR === 0) {
        text += ' None do, so no cell is dotted and nothing on this map is distinguishable from sampling noise.';
      } else {
        text += ' ' + fmtInt(S.nSigFDR) + ' of ' + fmtInt(S.nTested) + ' do.';
      }
      if (r.reliability === 'low') text += ' Provisional: few seasons define this subset.';
    }
    cap.textContent = text;
    teleRenderLegend();
    tEl('teleFieldHint').textContent = field === 'shape'
      ? 'Track shape: where the subset puts its storms once overall activity is matched to the archive. Read this to ask whether the track moved.'
      : 'Activity rate: storm fixes per season, subset minus archive. Read this to ask whether it was busier or quieter.';
  }

  /** The map's colour key as HTML, from the same table the canvas uses
      (HF.globe.compositeLegend), so the two cannot disagree. Every swatch is
      named with its range and meaning; colour is never the only carrier. */
  function teleRenderLegend() {
    var box = HF.clear(tEl('teleLegend'));
    var lg = HF.globe.compositeLegend ? HF.globe.compositeLegend() : null;
    if (!lg) return;
    box.appendChild(tx('h3', '', 'Difference from the archive' + (lg.unit ? ' (' + lg.unit + ')' : '')));
    var bar = tx('div', 'tele-scale');
    lg.bins.forEach(function (bin) {
      var seg = tx('span', 'tele-scale-seg');
      seg.style.background = bin.color;
      bar.appendChild(seg);
    });
    bar.setAttribute('aria-hidden', 'true');
    box.appendChild(bar);
    var ends = tx('div', 'tele-scale-ends');
    var first = lg.bins[0], last = lg.bins[lg.bins.length - 1];
    ends.appendChild(tx('span', '', '−' + Math.abs(first.lo).toFixed(2) + '  ' + lg.negative));
    ends.appendChild(tx('span', '', 'about the same'));
    ends.appendChild(tx('span', '', last.hi.toFixed(2) + '  ' + lg.positive));
    box.appendChild(ends);
    var ul = tx('ul', 'tele-keylist');
    ul.appendChild(tx('li', '', 'Dots: ' + lg.stipple + '.'));
    ul.appendChild(tx('li', '', 'Dotted outline, no fill: ' + lg.untested + '.'));
    if (lg.alpha < 1) ul.appendChild(tx('li', '', 'Faded colours: provisional, because few seasons define the subset.'));
    box.appendChild(ul);
  }

  /* ----------------------------------------------- index + activity chart */

  function ymdToDay(ymd) {
    return HF.teleconnect.dayNumber(Math.floor(ymd / 10000), Math.floor(ymd / 100) % 100, ymd % 100);
  }

  function dayLabel(day, withDay) {
    var ymd = HF.teleconnect.daysToYmd(day);
    var y = Math.floor(ymd / 10000), m = Math.floor(ymd / 100) % 100, d = ymd % 100;
    return (withDay ? d + ' ' : '') + HF.monthName(m) + ' ' + y;
  }

  /** Everything the chart and the table need, computed once per selection
      (not per redraw): the index over the archive period, event counts per
      month for the archive and the subset, and the season spans. Reads the
      index through the engine's own lookups (oniAt, mean5, mjoValues), so
      the line shows exactly the values the selection used. */
  function teleModel(b) {
    var tc = tele.engine, spec = b.spec, r = b.result;
    var per = tc.period;
    if (!per) return null;
    var d0 = ymdToDay(per.from), d1 = ymdToDay(per.to);
    var y0 = Math.floor(per.from / 10000), y1 = Math.floor(per.to / 10000);
    var x = [], y = [], i, ix;

    if (spec.type === 'enso') {
      var th = window.HF_TELECONNECTIONS.oni.thresholds || { elNino: 0.5, laNina: -0.5 };
      for (var yy = y0; yy <= y1; yy++) {
        for (var mm = 1; mm <= 12; mm++) {
          var ymd = yy * 10000 + mm * 100 + 15, day = ymdToDay(ymd);
          if (day < d0 || day > d1) continue;
          var e = tc.oniAt(ymd);
          x.push(day); y.push(e ? e.value : null);
        }
      }
      ix = {
        title: 'ONI (°C)', name: 'Oceanic Niño Index', line: 'normal',
        fmt: function (v) { return signed(v, 2) + ' °C'; },
        fmtTick: function (v) { return signed(v, 1).replace('+', ''); },
        fmtDay: function (d) { return dayLabel(d, false); },
        refs: [{ value: th.elNino, label: 'El Niño ≥ ' + signed(th.elNino, 1) },
               { value: th.laNina, label: 'La Niña ≤ ' + signed(th.laNina, 1) }]
      };
    } else if (spec.type === 'tercile') {
      var cut = tc.terciles(spec.index, 'mean5');
      for (var d = d0; d <= d1; d++) {
        x.push(d); y.push(tc.mean5(spec.index, HF.teleconnect.daysToYmd(d)));
      }
      ix = {
        title: spec.index.toUpperCase() + ' (5-day mean)', name: spec.index.toUpperCase() + ' 5-day mean', line: 'thin',
        fmt: function (v) { return signed(v, 2); },
        fmtTick: function (v) { return signed(v, 1).replace('+', ''); },
        fmtDay: function (dd) { return dayLabel(dd, true); },
        refs: [{ value: cut.upper, label: 'upper third ≥ ' + signed(cut.upper, 2) },
               { value: cut.lower, label: 'lower third ≤ ' + signed(cut.lower, 2) }]
      };
    } else {
      var thr = tc.defaultThreshold;
      var rowA = tc.mjoRow(per.from), rowB = tc.mjoRow(per.to);
      if (rowA == null) rowA = 0;
      for (var rw = rowA; rowB == null ? false : rw <= rowB; rw++) {
        var cd = tc.mjoPentad(rw);
        if (cd == null) break;
        var vals = tc.mjoValues(rw);
        x.push(ymdToDay(cd)); y.push(vals ? vals[spec.lon] : null);
      }
      ix = {
        title: 'MJO ' + spec.lon + ' (pentad)', name: 'MJO index at ' + spec.lon, line: 'thin',
        fmt: function (v) { return signed(v, 2); },
        fmtTick: function (v) { return signed(v, 1).replace('+', ''); },
        fmtDay: function (dd) { return dayLabel(dd, true) + ' (pentad centre)'; },
        refs: [{ value: thr, label: 'suppressed ≥ ' + signed(thr, 1) },
               { value: -thr, label: 'enhanced ≤ ' + signed(-thr, 1) }]
      };
    }
    ix.x = x; ix.y = y;

    // events per month, whole archive and subset ------------------------
    var bins = [], byYm = {};
    for (var cy = y0; cy <= y1; cy++) {
      for (var cm = 1; cm <= 12; cm++) {
        var first = cy * 12 + cm - 1;
        var bx0 = HF.teleconnect.dayNumber(cy, cm, 1);
        var ny = cm === 12 ? cy + 1 : cy, nm = cm === 12 ? 1 : cm + 1;
        var bx1 = HF.teleconnect.dayNumber(ny, nm, 1) - 1;
        if (bx1 < d0 || bx0 > d1) continue;
        byYm[cy * 100 + cm] = bins.length;
        bins.push({ x0: Math.max(bx0, d0), x1: Math.min(bx1, d1), all: 0, sub: 0, label: HF.monthName(cm) + ' ' + cy, key: first });
      }
    }
    function put(low, field) {
      if (!(low.season >= DATA.recordStart)) return;
      var ym = Math.floor(low.start / 10000);       // YYYYMM from YYYYMMDDHH
      var k = byYm[ym];
      if (k != null) bins[k][field]++;
    }
    for (i = 0; i < LOWS.length; i++) put(LOWS[i], 'all');
    for (i = 0; i < b.subset.length; i++) put(b.subset[i], 'sub');

    // season spans -------------------------------------------------------
    var defining = {};
    if (r.design === 'seasons' && r.n.subsetSeasons) {
      r.n.subsetSeasons.forEach(function (s) { defining[s] = true; });
    }
    var seasons = [];
    DATA.seasons.forEach(function (s) {
      if (s.start < DATA.recordStart) return;
      seasons.push({
        season: s.start, x0: HF.teleconnect.dayNumber(s.start, 6, 1), x1: HF.teleconnect.dayNumber(s.start + 1, 5, 31),
        tick: String(s.start).slice(2) + '/' + String(s.start + 1).slice(2), defining: !!defining[s.start]
      });
    });

    return { span: [d0, d1], index: ix, bins: bins, seasons: seasons };
  }

  function teleSeriesCaption(b) {
    var spec = b.spec, tc = tele.engine, sp = tc.spans;
    var bars = ' Below it, each bar is the storms that began in that month: the part in the chosen subset at the base, ' +
               'the rest of the archive stacked on top. Both panels share one time axis, and seasons run 1 June to 31 May.';
    if (spec.type === 'enso') {
      return 'The Oceanic Niño Index (a 3-month mean of Niño-3.4 sea-surface temperature anomalies, °C), one point per ' +
             'month, with the ±0.5 °C phase thresholds. Seasons that define the subset are shaded and capped.' + bars;
    }
    if (spec.type === 'tercile') {
      return 'The 5-day mean ' + spec.index.toUpperCase() + ' (' + TELE_INDEX_NAMES[spec.index] + '), one point per day, with the ' +
             'cut points between its lower, middle and upper thirds. The index runs to ' + sp[spec.index].end + '.' + bars;
    }
    return 'The MJO index at ' + spec.lon + ' only: one of ten longitude-keyed series from CPC 200-hPa velocity potential at pentad ' +
           'resolution, not a single global index. Negative means enhanced convection. Each storm is classified by the value ' +
           pentadText(spec.lag) + ' before its own pentad, so read the index to the left of a cluster of storms. The ' +
           'series runs to ' + sp.mjo.end + '.' + bars;
  }

  function renderTeleSeries() {
    var b = tele.shown;
    var box = tEl('chartTele');
    if (!b || !b.model) { HF.clear(box); return; }
    var m = b.model;
    tEl('teleSeriesCap').textContent = teleSeriesCaption(b);
    var defLegend = b.result.design === 'seasons';
    var legend = [{ label: m.index.name + (b.spec.type === 'mjo' ? ' (negative = enhanced)' : ''), kind: 'line' },
                  { label: b.spec.type === 'tercile' ? 'Tercile cut points' : 'Threshold', kind: 'ref' },
                  { label: 'Events in this subset', kind: 'sub' },
                  { label: 'Rest of the archive', kind: 'rest' }];
    if (defLegend) legend.push({ label: 'Seasons that define the subset (shaded, capped)', kind: 'band' });
    HF.charts.indexSeries(box, {
      span: m.span, index: m.index, bins: m.bins, seasons: m.seasons,
      countTitle: 'Events / month', legend: legend,
      ariaLabel: m.index.name + ' from ' + HF.seasonLabel(DATA.recordStart) + ' with events per month beneath; ' +
                 fmtInt(b.result.n.events) + ' of ' + fmtInt(b.result.n.allEvents) + ' events are in the subset. The table view below holds the same numbers by season.'
    });
  }

  function renderTeleTable(b) {
    var m = b.model, tc = tele.engine;
    var tbl = tEl('teleTableEl');
    var thead = HF.clear(tbl.querySelector('thead')), tbody = HF.clear(tbl.querySelector('tbody'));
    if (!m) return;
    var isEnso = b.spec.type === 'enso';
    var hasDef = b.result.design === 'seasons';
    var heads = ['Season', isEnso ? 'DJF ONI (°C)' : 'Mean of the plotted index', 'Events, archive', 'Events, subset'];
    if (hasDef) heads.push('Defines the subset');
    var tr = tx('tr');
    heads.forEach(function (h) { var th = tx('th', '', h); th.setAttribute('scope', 'col'); tr.appendChild(th); });
    thead.appendChild(tr);
    tEl('teleTableCap').textContent = 'Per-season values for ' + b.label + ': the index, events in the archive, events in the subset.';

    var all = {}, sub = {};
    m.bins.forEach(function () {});
    function seasonOfBin(bin) {
      for (var s = 0; s < m.seasons.length; s++) if (bin.x0 >= m.seasons[s].x0 && bin.x0 <= m.seasons[s].x1) return m.seasons[s].season;
      return null;
    }
    m.bins.forEach(function (bin) {
      var s = seasonOfBin(bin);
      if (s == null) return;
      all[s] = (all[s] || 0) + bin.all;
      sub[s] = (sub[s] || 0) + bin.sub;
    });
    m.seasons.forEach(function (s) {
      var idxText;
      if (isEnso) {
        var e = tc.oniDjf(s.season);
        idxText = e ? signed(e.value, 1) + ' (' + (e.phaseName || e.phase) + ')' : 'no value';
      } else {
        var sum = 0, cnt = 0, ix = m.index;
        for (var i = 0; i < ix.x.length; i++) {
          if (ix.x[i] >= s.x0 && ix.x[i] <= s.x1 && ix.y[i] != null) { sum += ix.y[i]; cnt++; }
        }
        idxText = cnt ? signed(sum / cnt, 2) : 'no value';
      }
      var row = tx('tr');
      var th = tx('th', '', HF.seasonLabel(s.season)); th.setAttribute('scope', 'row'); row.appendChild(th);
      row.appendChild(tx('td', '', idxText));
      row.appendChild(tx('td', 'num', fmtInt(all[s.season] || 0)));
      row.appendChild(tx('td', 'num', fmtInt(sub[s.season] || 0)));
      if (hasDef) row.appendChild(tx('td', '', s.defining ? 'Yes' : '—'));
      tbody.appendChild(row);
    });
  }

  /* ------------------------------------------------------ method note */

  function renderTeleMethod() {
    var tc = tele.engine;
    var box = HF.clear(tEl('teleMethodBody'));
    var partial = DATA.seasons.filter(function (s) { return s.start < DATA.recordStart; });
    var counts = {};
    LOWS.forEach(function (l) { counts[l.season] = (counts[l.season] || 0) + 1; });
    var partialText = partial.map(function (s) { return fmtInt(counts[s.start] || 0); }).join(', ');
    var full = DATA.seasons.filter(function (s) { return s.start >= DATA.recordStart; })
      .map(function (s) { return counts[s.start] || 0; });
    var lo = Math.min.apply(null, full), hi = Math.max.apply(null, full);
    var sp = tc ? tc.spans : null;

    function item(term, text) {
      box.appendChild(tx('h3', '', term));
      box.appendChild(tx('p', '', text));
    }
    item('Seasons',
      'A season runs 1 June to 31 May and is labelled by its starting year. A storm on 2 January 2015 belongs to ' +
      '2014–15. The season is also the unit that is resampled: storms in one season share a background state ' +
      '(the jet, blocking, the ENSO phase itself), so they are not independent draws, and treating 400 storms as 400 ' +
      'samples would make a chance pattern look decisive. Counts are converted to rates per season so a subset of ' +
      '8 seasons and an archive of 22 can be compared at all.');
    item('Seasons left out',
      'Seasons before ' + HF.seasonLabel(DATA.recordStart) + ' are excluded from both the subset and the baseline. ' +
      'Pacific entries begin in February 2002 and Atlantic entries in September 2003, so the ' + partial.length +
      ' earlier seasons hold ' + partialText + ' events against ' + lo + '–' + hi + ' in every complete one. ' +
      'They are short-counted, not quiet, and including them manufactures signal: in testing, comparing the twelve earliest ' +
      'seasons with the rest flagged 11 significant cells for no climatic reason, and leaving out just the three ' +
      'short-counted seasons took that to none.');
    item('Significance',
      'The map is split into equal-area cells about 4 degrees of latitude across, and every cell with enough storms in the ' +
      'archive is tested (about 150 of them). With that many tests, roughly 5% pass on pure noise, so a cell only counts ' +
      'if it survives false discovery rate control (Benjamini–Hochberg, at twice the 5% global level as Wilks 2016 ' +
      'recommends for spatially correlated fields). The “expected by chance” column is that 5% expectation, shown so ' +
      'a handful of uncorrected hits is not mistaken for a finding. Colour on the map is the size of a difference and ' +
      'dots are significance; a deep colour without dots is a big difference the test cannot tell from chance.');
    item('Events versus seasons',
      'ENSO subsets are whole seasons, so the season is resampled directly. NAO, PNA, AO and MJO subsets pick storms ' +
      'within seasons, so there is no season to resample; the test instead re-deals which storms carry the label ' +
      'within each season, month and basin. The blocking matters: the daily indices persist for a week or two, so a ' +
      'tercile or MJO subset is clustered in time and inherits a month and basin mix unlike the archive\u2019s (storms in ' +
      'the lower NAO third, for example, are about 18% October against 9% for the archive, and the storm track sits in ' +
      'a very different place in October than in February). Without blocking, a subset drawn disproportionately from ' +
      'October, or from one basin, looks like an index effect when it is only a seasonal one. Blocking is the more ' +
      'conservative choice and the result is still a floor on the real uncertainty, not the whole of it.');
    item('Looking at many selections',
      'False discovery rate control covers the cells of one map. It does not cover the choices made around the map: ' +
      'ten longitudes, three states, any lag from 0 to 6 pentads, four indices. Trying several and reporting the one ' +
      'that lights up brings the false-alarm rate back. Treat a single flagged map from a search like that as a lead ' +
      'to confirm, not a result.');
    item('Indices',
      'ENSO is the December–February Oceanic Niño Index of the storm’s season (NOAA CPC, El Niño at or ' +
      'above +0.5, La Niña at or below −0.5). NAO, PNA and AO are the CPC daily indices, averaged over the five ' +
      'days ending on the day the storm’s first fix was analyzed' +
      (sp ? ' (they run to ' + sp.nao.end + ')' : '') + '. The MJO index is the CPC 200-hPa velocity-potential ' +
      'index at pentad resolution, one series for each of ten longitudes' + (sp ? ' (to ' + sp.mjo.end + ')' : '') +
      ': it is not the Wheeler–Hendon RMM index, so there are no RMM phases 1–8 (no octants). A phase and an ' +
      'amplitude of its own are derived locally from the ten-longitude field and used by the regression view, but they are ' +
      'not comparable with a published RMM phase. Negative values of the single-longitude series are enhanced convection. “Enhanced” and “suppressed” mean at or beyond ±' +
      (tc ? tc.defaultThreshold.toFixed(1) : '0.5') + ' and “neutral” means inside it. A storm with no index value ' +
      'on its day (a missing day or pentad) is left out of the subset, never counted as zero.');
    item('Lag',
      'The extratropical response to the tropics is thought to arrive about 5–15 days later, so the MJO state is ' +
      'read a chosen number of pentads before the storm. The default is ' + (tc ? pentadText(tc.defaultLag) : '2 pentads') +
      ' as a starting point, not a finding, and each lag is another look at the data.');
  }

  /* --------------------------------------------------- controls & tab */

  function syncTeleControls() {
    tEl('teleEnsoWrap').hidden = tele.index !== 'enso';
    tEl('teleTercWrap').hidden = tele.index !== 'nao' && tele.index !== 'pna' && tele.index !== 'ao';
    tEl('teleMjoWrap').hidden = tele.index !== 'mjo';
    var lagWord = pentadText(tele.lag);
    tEl('teleLagOut').textContent = lagWord;
    tEl('teleLag').setAttribute('aria-valuetext', lagWord + ' before the storm');
  }

  function buildTele() {
    if (tele.built) return;
    tele.built = true;
    var tc = teleEngine();
    if (!tc) return;

    var lon = tEl('teleLon');
    tc.longitudes.forEach(function (name) {
      var deg = name.replace(/E$/, '°E').replace(/W$/, '°W');
      lon.appendChild(HF.el('option', { value: name }, deg));
    });
    lon.value = tele.lon;
    tEl('teleLag').value = String(tele.lag);

    function radios(name, apply) {
      Array.prototype.forEach.call(document.querySelectorAll('input[name="' + name + '"]'), function (r) {
        r.addEventListener('change', function () { if (r.checked) apply(r.value); });
      });
    }
    radios('teleView', function (v) { setTeleView(v); });
    tEl('teleViewNote').textContent = TELE_VIEW_NOTES[tele.view];
    radios('teleIndex', function (v) { tele.index = v; teleRequest(); });
    radios('teleEnso', function (v) { tele.enso = v; teleRequest(); });
    radios('teleTerc', function (v) { tele.terc = v; teleRequest(); });
    radios('teleMjoState', function (v) { tele.mjoState = v; teleRequest(); });
    lon.addEventListener('change', function () { tele.lon = lon.value; teleRequest(); });
    tEl('teleLag').addEventListener('input', function (e) {
      tele.lag = Number(e.target.value);
      teleRequest();
    });
    radios('teleField', function (v) {
      tele.fieldUser = v;
      if (tele.shown && !tele.shown.error) {
        teleDrawMap(tele.shown);
        announceTeleField(tele.shown, v);
      }
    });
    renderTeleMethod();
  }

  /** Switching the map between rate and shape changes what the map says but
      not which result is shown, so say it briefly and without re-reading the
      whole card. */
  function announceTeleField(b, field) {
    var S = b.result.summary[field];
    tEl('teleLive').textContent = 'Map now shows ' + (field === 'shape' ? 'track shape' : 'activity rate') + ': ' +
      fmtInt(S.nSigFDR) + ' of ' + fmtInt(S.nTested) + ' cells significant after false discovery rate control.';
  }

  /** Moves the single globe canvas between the Map tab and this tab.
      HF.globe is one canvas with one set of listeners; moving its wrapper
      keeps all of that intact, where a second canvas would need a second
      drawing state kept in step with the first. */
  function placeGlobe() {
    var wrap = document.querySelector('.map-wrap');
    if (!wrap) return;
    var home = tEl('panel-map'), slot = tEl('teleMapSlot');
    var want = state.tab === 'tele' ? slot : home;
    if (wrap.parentNode !== want) want.appendChild(wrap);
  }

  /** Called from render() while the tab is active, and from the resize and
      theme paths. Redraws from the result already held; asks for a
      computation only when there is none for the current selection. */
  function renderTele() {
    buildTele();
    if (tele.view === 'regress') { renderRegress(); return; }
    syncTeleControls();
    var key = tele.engine ? teleKey(teleSpec()) : null;
    if (!tele.engine) {
      renderTeleFailure('The teleconnection data or scripts did not load (' + (tele.failed || 'unknown error') + '), so nothing can be tested here.');
      return;
    }
    if (tele.shown && tele.shown.key === key && !tele.shown.error) {
      teleSetPending(false);         // a run abandoned by leaving the tab must not leave the banner up
      teleDrawMap(tele.shown);       // new theme / size: same result, redrawn
      renderTeleSeries();
      return;
    }
    teleRequest(true);
  }

  /* ------------------------------------------------- regression view
     The same question as the composite, asked a second way. The composite
     sorts storms into thirds of an index and tests ~150 map cells; this view
     keeps the index continuous and asks one question of one number: "per
     standard deviation of the NAO, how far does the average storm move?"
     HF.regress.fit does the work (season-block bootstrap, month fixed
     effects, one model per basin); this section only chooses the controls,
     draws the coefficient plot, and decides how each result is SAID.

     The sentence that matters most is not any of the coefficients. It is the
     difference between two readings of an interval that includes zero:
     "there is no effect" and "this sample could not have seen an effect that
     size". Every term carries its detection floor (the MDE80), the plot
     draws it as a band behind the interval, and the plain-language list
     never says "no effect" for a term below its floor. On this archive the
     NAO's pull on Atlantic track latitude sits far outside its floor, and
     every interaction term sits inside its own: that second half is an
     answer to "do these teleconnections interact?", and the answer is "the
     archive is too short to say", not "no".

     Nothing is recomputed here. Numbers are formatted from the result object
     untouched, every warning is printed, and a result is cached by its
     options (the seed is fixed, so the same options give the same answer),
     so going back to a previous selection is instant.

     Cost: ~0.1 s for the default model, ~0.4 s with the MJO permutation
     test. That is fast enough to run on a control change, but the card is
     still marked pending at once (aria-busy, the old numbers dimmed and
     labelled as the previous selection) and the run starts after a short
     debounce so dragging the lag slider is one fit per pause, not seven. */

  var REG_DEBOUNCE_MS = 140;
  var REG_CACHE_MAX = 40;
  var REG_BASINS = { atl: 'Atlantic', pac: 'Pacific' };
  var REG_GLYPH = { detected: '●', below: '○', unavailable: '×' };
  var REG_STATE = { detected: 'Detected', below: 'Below floor', unavailable: 'Unavailable' };

  /* What each response is, in the units that mean something. `up` / `down`
     say what a positive / negative coefficient does to the storm. */
  var REG_RESP = {
    lat: {
      title: 'track latitude', units: 'degrees', axisUnits: 'degrees of latitude',
      ends: ['equatorward (south)', 'poleward (north)'],
      hint: 'Mean latitude of the storm’s fixes. Positive means further north.',
      sentence: function (c, bas) { return bas + ' tracks sit ' + fnum(Math.abs(c), 2) + ' degrees ' + (c >= 0 ? 'further poleward (north)' : 'further equatorward (south)'); },
      up: 'further poleward', down: 'further equatorward'
    },
    lon: {
      title: 'track longitude', units: 'degrees', axisUnits: 'degrees of longitude',
      ends: ['west', 'east'],
      hint: 'Circular mean longitude of the fixes, laid on a continuous branch so the dateline is not a seam. Positive means further east.',
      sentence: function (c, bas) { return bas + ' tracks sit ' + fnum(Math.abs(c), 2) + ' degrees of longitude further ' + (c >= 0 ? 'east' : 'west'); },
      up: 'further east', down: 'further west'
    },
    minP: {
      title: 'minimum central pressure', units: 'hPa', axisUnits: 'hPa',
      ends: ['deeper (lower pressure)', 'shallower (higher pressure)'],
      hint: 'Lowest analysed central pressure; events with none (such as tip jets) are left out. Negative means deeper.',
      sentence: function (c, bas) { return bas + ' lows reach a minimum pressure ' + fnum(Math.abs(c), 2) + ' hPa ' + (c >= 0 ? 'higher (shallower)' : 'lower (deeper)'); },
      up: 'a higher (shallower) minimum pressure', down: 'a lower (deeper) minimum pressure'
    },
    hfH: {
      title: 'time at hurricane force', units: 'hours', axisUnits: 'hours',
      ends: ['less time at hurricane force', 'more time at hurricane force'],
      hint: 'Hours spent at hurricane force. The distribution is right-skewed: a few long-lived storms carry much of the mean.',
      sentence: function (c, bas) { return bas + ' lows spend ' + fnum(Math.abs(c), 2) + ' hours ' + (c >= 0 ? 'more' : 'less') + ' at hurricane force'; },
      up: 'more time at hurricane force', down: 'less time at hurricane force'
    }
  };

  var REG_INDEX_WORDS = {
    nao: 'NAO (the 5-day mean ending on the day of the storm’s first fix)',
    pna: 'PNA (the 5-day mean ending on the day of the storm’s first fix)',
    oni: 'ONI (the Oceanic Niño Index for the month the storm began)'
  };

  var REG_RELIABILITY = {
    ok: ['Adequate', 'Enough seasons for the bootstrap interval and the detection floor to mean something.'],
    low: ['Low', 'Few seasons or few events per parameter, so intervals and floors are themselves uncertain. Read the warnings.'],
    none: ['None', 'The interval could not be computed, so there is no detection floor and nothing to read.']
  };

  var reg = {
    basin: 'atl', response: 'lat', inter: false, mjo: false, lag: 0,
    cache: {}, order: [], want: null, timer: null, shown: null, built: false,
    sweepToken: 0
  };

  function rEl(id) { return document.getElementById(id); }
  /** Unsigned-plus formatting with a true minus sign, for intervals. */
  function fnum(v, d) { return (v < 0 ? '−' : '') + Math.abs(v).toFixed(d); }
  function pText(p) { return p < 0.001 ? 'p < 0.001' : 'p = ' + p.toFixed(3); }

  function regOptions() {
    return {
      basin: reg.basin, response: reg.response, interactions: reg.inter,
      mjo: reg.mjo ? { lag: reg.lag } : false,
      teleconnect: tele.engine, seed: 1
    };
  }
  function regKey() {
    return [reg.basin, reg.response, reg.inter ? 'x' : '-', reg.mjo ? 'm' + reg.lag : '-'].join('|');
  }
  function regLabel() {
    return REG_BASINS[reg.basin] + ', ' + REG_RESP[reg.response].title +
      (reg.inter ? ', with interactions' : '') +
      (reg.mjo ? ', MJO at lag ' + pentadText(reg.lag) : '');
  }

  function regCompute() {
    var b = { key: regKey(), label: regLabel(), basin: reg.basin, response: reg.response,
              inter: reg.inter, mjoOn: reg.mjo, lag: reg.lag, result: null, error: null, ms: 0 };
    var t0 = Date.now();
    try {
      if (!HF.regress) throw new Error('regress.js did not load');
      b.result = HF.regress.fit(LOWS, regOptions());
    } catch (err) {
      b.error = String(err && err.message ? err.message : err);
    }
    b.ms = Date.now() - t0;
    return b;
  }

  function regRequest(soon) {
    if (!teleEngine()) { renderRegFailure('The teleconnection data or scripts did not load (' + (tele.failed || 'unknown error') + '), so nothing can be fitted here.'); return; }
    var key = regKey();
    reg.want = key;
    clearTimeout(reg.timer);
    reg.timer = null;
    syncRegControls();
    if (reg.cache[key]) { regShow(reg.cache[key]); return; }
    regSetPending(true);
    reg.timer = setTimeout(function () {
      reg.timer = null;
      if (reg.want !== key || state.tab !== 'tele' || tele.view !== 'regress') return;
      var b = regCompute();
      if (!b.error) {
        reg.cache[key] = b;
        reg.order.push(key);
        while (reg.order.length > REG_CACHE_MAX) delete reg.cache[reg.order.shift()];
      }
      if (reg.want === key) regShow(b);
    }, soon ? 30 : REG_DEBOUNCE_MS);
  }

  function regSetPending(on) {
    var card = rEl('regMain');
    card.setAttribute('aria-busy', on ? 'true' : 'false');
    card.classList.toggle('is-pending', on);
    rEl('regLower').classList.toggle('is-pending', on);
    var p = rEl('regPending');
    p.hidden = !on;
    if (!on) return;
    p.textContent = reg.shown
      ? 'Fitting ' + regLabel() + '. The numbers below are still for ' + reg.shown.label + ' and are out of date until this finishes.'
      : 'Fitting ' + regLabel() + '…';
  }

  function regShow(b) {
    reg.shown = b;
    regSetPending(false);
    if (b.error) { renderRegFailure('The model could not be fitted for ' + b.label + ': ' + b.error); return; }
    renderRegPlot(b);
    renderRegReading(b);
    renderRegFit(b);
    renderRegMjo(b);
    renderRegWarn(b);
    renderRegTable(b);
    announceReg(b);
  }

  function renderRegFailure(message) {
    rEl('regShowing').textContent = '';
    var hl = HF.clear(rEl('regHeadline'));
    hl.textContent = message;
    HF.clear(rEl('regPlot'));
    HF.clear(rEl('regReading'));
    HF.clear(rEl('regFit'));
    HF.clear(rEl('regWarn'));
    HF.clear(rEl('regMjoBody'));
    rEl('regMjoCard').hidden = true;
    var tb = rEl('regTableEl');
    HF.clear(tb.querySelector('thead')); HF.clear(tb.querySelector('tbody'));
    rEl('teleLive').textContent = 'Not fitted. ' + message;
  }

  /* ------------------------------------------------------------ the words */

  function termState(t) {
    if (t.flag === 'detected') return 'detected';
    if (t.flag === 'below-floor') return 'below';
    return 'unavailable';
  }

  function termName(t) { return t.label.replace(/ x /g, ' × '); }

  /** "per standard deviation of the NAO, Atlantic tracks sit 1.88 degrees
      further poleward", or for a product term, what it is. */
  function termClaim(t, b) {
    var R = REG_RESP[b.response], bas = REG_BASINS[b.basin], c = t.coef;
    if (t.kind === 'interaction') {
      var parts = t.name.split('*');
      var A = parts[0].toUpperCase(), B = parts[1].toUpperCase();
      return 'Product of the ' + A + ' and the ' + B + ': for each standard deviation higher the ' + B + ', the effect of the ' + A +
             ' on ' + R.title + ' changes by ' + signed(c, 2) + ' ' + R.units + ' per standard deviation of the ' + A + '.';
    }
    var sd = t.unit && t.unit.sd != null ? ' (one SD is ' + t.unit.sd.toFixed(2) + (t.name === 'oni' ? ' °C' : '') + ' in this sample)' : '';
    return 'For each standard deviation of the ' + (REG_INDEX_WORDS[t.name] || t.label) + sd + ', ' + R.sentence(c, bas) + '.';
  }

  function termReading(t, b) {
    var R = REG_RESP[b.response];
    var st = termState(t);
    var floor = t.mde80 != null ? t.mde80.toFixed(2) : null;
    var iv = t.ci ? '[' + fnum(t.ci[0], 2) + ', ' + fnum(t.ci[1], 2) + ']' : null;
    if (st === 'unavailable') {
      return 'No interval could be computed' + (t.note ? ': ' + t.note : '.') + ' Nothing can be said about this term.';
    }
    if (st === 'detected') {
      return 'This sample could resolve an effect this large. The 95% interval is ' + iv + ', clear of zero, and the estimate is above ' +
             'the ±' + floor + ' ' + R.units + ' this sample can detect.' +
             ' It describes an association in this archive; it does not show what causes it.';
    }
    var s = 'Not resolved, which is not the same as absent. The estimate (' + signed(t.coef, 2) + ') is smaller than the ±' + floor + ' ' +
            R.units + ' per SD that this sample could detect, so it cannot tell “no effect” from an effect up to about that size. ' +
            'The interval ' + iv + ' is consistent with both.';
    if (t.excludesZero) {
      s += ' The interval does clear zero, but an estimate this small that clears it has probably been inflated by chance, ' +
           'so do not quote ' + signed(t.coef, 2) + ' as the size of the effect.';
    }
    return s;
  }

  function regRows(b) {
    var r = b.result, R = REG_RESP[b.response];
    return r.terms.map(function (t) {
      var st = termState(t);
      var hasCi = !!t.ci;
      var floor = t.mde80 != null ? t.mde80.toFixed(2) : null;
      var valueText = signed(t.coef, 2);
      var rangeText = hasCi ? '[' + fnum(t.ci[0], 2) + ', ' + fnum(t.ci[1], 2) + ']' : 'no interval';
      var floorText = floor ? 'floor ±' + floor : 'no floor';
      var aria = termName(t) + ': ' + REG_STATE[st].toLowerCase() + '. ' +
        'Estimate ' + signed(t.coef, 2) + ' ' + R.units + ' per standard deviation' +
        (hasCi ? ', 95 percent interval ' + fnum(t.ci[0], 2) + ' to ' + fnum(t.ci[1], 2) +
          ', detection floor plus or minus ' + floor + '.' : ', no interval.') +
        (st === 'below' ? ' The sample cannot resolve an effect this size.' : '');
      var tip = '<b>' + termName(t) + '</b>' +
        '<div class="t-row">' + REG_GLYPH[st] + ' ' + REG_STATE[st] + '</div>' +
        '<div class="t-row">Estimate ' + signed(t.coef, 2) + ' ' + R.units + ' per SD</div>' +
        (hasCi ? '<div class="t-row">95% interval ' + rangeText + '</div><div class="t-row">Floor ±' + floor + '</div>' : '<div class="t-row">No interval</div>') +
        (st === 'below' ? '<div class="t-row">Cannot resolve an effect this size</div>' : '');
      return {
        key: t.name, label: termName(t), est: t.coef, lo: hasCi ? t.ci[0] : null, hi: hasCi ? t.ci[1] : null,
        floor: t.mde80, floorShort: floor, state: st, stateGlyph: REG_GLYPH[st], stateText: REG_STATE[st],
        valueText: valueText, rangeText: rangeText, floorText: floorText, aria: aria, tip: tip,
        group: t.kind === 'interaction' ? 'Interactions' : 'Main effects'
      };
    });
  }

  function regHeadline(b) {
    var r = b.result, R = REG_RESP[b.response];
    if (r.status !== 'ok') {
      return 'This model could not be fully fitted (' + r.status + '). ' +
        (r.terms.length && !r.terms.some(function (t) { return t.ci; }) ? 'Estimates are shown but their intervals and detection floors are withheld, so none of them can be called detected or not. ' : '') +
        'See the warnings.';
    }
    var det = r.terms.filter(function (t) { return t.flag === 'detected'; });
    var low = r.terms.filter(function (t) { return t.flag === 'below-floor'; });
    var names = function (a) {
      var n = a.map(termName);
      return n.length > 1 ? n.slice(0, -1).join(', ') + ' and ' + n[n.length - 1] : n[0];
    };
    var s;
    if (!det.length) {
      s = 'No term clears its detection floor. For every one, this sample cannot tell “no effect” from an effect up to the width of its grey band.';
    } else {
      s = names(det) + (det.length === 1 ? ' is' : ' are') + ' detected: ' + (det.length === 1 ? 'its' : 'their') +
          ' interval ' + (det.length === 1 ? 'sits' : 'sit') + ' clear of zero and ' + (det.length === 1 ? 'its' : 'their') +
          ' estimate beyond the floor.';
      if (low.length) {
        s += ' ' + names(low) + (low.length === 1 ? ' sits' : ' sit') + ' inside ' + (low.length === 1 ? 'its own floor' : 'their own floors') +
             ': the sample cannot resolve an effect that small, which is different from showing there is none.';
      }
    }
    return s;
  }

  /* ------------------------------------------------------------ the plot */

  function renderRegPlot(b) {
    var r = b.result, R = REG_RESP[b.response];
    rEl('regShowing').textContent = 'Showing: ' + b.label;
    rEl('regHeadline').textContent = regHeadline(b);
    var rows = regRows(b);
    var bas = REG_BASINS[b.basin];
    HF.charts.coefPlot(rEl('regPlot'), {
      rows: rows,
      axisTitle: 'Change in ' + R.title + ' per 1 SD of the index (' + R.axisUnits + ')',
      ends: R.ends,
      fmtTick: function (v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + String(parseFloat(Math.abs(v).toFixed(2))); },
      floorLegend: 'Detection floor (±MDE80): the smallest true effect this sample would find 80% of the time',
      ariaLabel: 'Coefficient plot: ' + bas + ' ' + R.title + '. One row per term, each with its estimate, 95 percent interval and detection floor. ' +
                 'The table view below holds the same numbers.'
    });
  }

  function renderRegTable(b) {
    var r = b.result, R = REG_RESP[b.response];
    var tbl = rEl('regTableEl');
    var thead = HF.clear(tbl.querySelector('thead')), tbody = HF.clear(tbl.querySelector('tbody'));
    rEl('regTableCap').textContent = 'Terms of the ' + b.label + ' model: estimate per standard deviation in ' + R.units +
      ', 95% interval, detection floor and state.';
    var tr = tx('tr');
    ['Term', 'Estimate (' + R.units + ' per SD)', '95% interval, low', '95% interval, high', 'Detection floor (±)', 'State'].forEach(function (h, i) {
      var th = tx('th', i ? 'num' : '', h); th.setAttribute('scope', 'col'); tr.appendChild(th);
    });
    thead.appendChild(tr);
    r.terms.forEach(function (t) {
      var row = tx('tr');
      var th = tx('th', '', termName(t)); th.setAttribute('scope', 'row'); row.appendChild(th);
      row.appendChild(tx('td', 'num', signed(t.coef, 2)));
      row.appendChild(tx('td', 'num', t.ci ? fnum(t.ci[0], 2) : '—'));
      row.appendChild(tx('td', 'num', t.ci ? fnum(t.ci[1], 2) : '—'));
      row.appendChild(tx('td', 'num', t.mde80 != null ? t.mde80.toFixed(2) : '—'));
      row.appendChild(tx('td', '', REG_GLYPH[termState(t)] + ' ' + REG_STATE[termState(t)] + (t.flag === 'below-floor' && t.excludesZero ? ' (interval excludes 0)' : '')));
      tbody.appendChild(row);
    });
  }

  function renderRegReading(b) {
    var box = HF.clear(rEl('regReading'));
    var r = b.result;
    if (!r.terms.length) { box.appendChild(tx('p', 'tele-note', 'No terms were fitted.')); return; }
    var ul = tx('ul', 'reg-terms');
    r.terms.forEach(function (t) {
      var st = termState(t);
      var li = tx('li', 'reg-term is-' + st);
      var head = tx('p', 'reg-term-head');
      head.appendChild(tx('span', 'reg-term-glyph', REG_GLYPH[st]));
      head.lastChild.setAttribute('aria-hidden', 'true');
      head.appendChild(tx('strong', '', termName(t)));
      head.appendChild(document.createTextNode(' — ' + REG_STATE[st].toLowerCase()));
      li.appendChild(head);
      li.appendChild(tx('p', 'reg-term-claim', termClaim(t, b)));
      li.appendChild(tx('p', 'reg-term-read', termReading(t, b)));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    box.appendChild(tx('p', 'tele-note', 'Units: ' + REG_RESP[b.response].title + ' is in ' + REG_RESP[b.response].units +
      '. Each coefficient is the change in that per one standard deviation of the index, with the month held fixed and the other indices in the model.'));
  }

  function pct(v) { return (v * 100).toFixed(1) + '%'; }

  function renderRegFit(b) {
    var box = HF.clear(rEl('regFit'));
    var r = b.result, n = r.n, R = REG_RESP[b.response];
    box.appendChild(teleTable('Events and seasons in this fit',
      ['Measure', 'Value'],
      [['Events', fmtInt(n.events)], ['Seasons (the resampling unit)', fmtInt(n.seasons)],
       ['Estimated parameters', fmtInt(n.params)],
       ['Complete seasons from', r.recordStart != null ? HF.seasonLabel(r.recordStart) : '—']]));
    var rel = REG_RELIABILITY[r.reliability] || [String(r.reliability), ''];
    var relP = tx('p', 'tele-reliability is-' + r.reliability);
    relP.appendChild(tx('strong', '', 'Reliability: ' + rel[0] + '.'));
    relP.appendChild(document.createTextNode(' ' + rel[1]));
    relP.style.marginTop = 'var(--sp-3)';
    box.appendChild(relP);

    box.appendChild(tx('h3', '', 'How much the indices explain'));
    var base = r.r2Base != null ? r.r2Base : 0, full = r.r2 != null ? r.r2 : 0;
    var added = Math.max(0, full - base), rest = Math.max(0, 1 - Math.max(full, base));
    var bar = tx('div', 'reg-r2');
    bar.setAttribute('aria-hidden', 'true');
    [['reg-r2-base', base], ['reg-r2-add', added], ['reg-r2-rest', rest]].forEach(function (seg) {
      var s = tx('span', 'reg-r2-seg ' + seg[0]);
      s.style.flexGrow = String(Math.max(seg[1], 0.0001));
      bar.appendChild(s);
    });
    box.appendChild(bar);
    var ul = tx('ul', 'reg-r2-key');
    [['reg-r2-base', 'Calendar alone (month): ' + pct(base)],
     ['reg-r2-add', (b.mjoOn ? 'Added by the climate terms and MJO: ' : 'Added by the climate terms: ') + pct(added)],
     ['reg-r2-rest', 'Unexplained: ' + pct(rest)]].forEach(function (k) {
      var li = tx('li');
      li.appendChild(tx('i', 'reg-r2-swatch ' + k[0]));
      li.lastChild.setAttribute('aria-hidden', 'true');
      li.appendChild(document.createTextNode(k[1]));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    box.appendChild(tx('p', 'tele-note',
      'R² with everything in the model is ' + pct(full) + '; month alone gives ' + pct(base) + '. ' +
      'The season of the year does most of what the model explains, and ' + pct(rest) + ' of the variation in ' + R.title +
      ' is left to everything else. A detected index moves the average storm; it does not predict any one storm.'));
  }

  function renderRegWarn(b) {
    var box = HF.clear(rEl('regWarn'));
    var w = b.result.warnings || [];
    if (!w.length) { box.appendChild(tx('p', 'tele-note', 'None.')); return; }
    var ul = tx('ul', 'tele-warnings');
    w.forEach(function (x) { ul.appendChild(tx('li', '', x)); });
    box.appendChild(ul);
  }

  /* ------------------------------------------------------------ the MJO */

  function lonText(d) {
    if (d == null || !isFinite(d)) return 'unknown';
    var e = Math.round(((d % 360) + 360) % 360);
    return e + '°E' + (e > 180 ? ' (' + (360 - e) + '°W)' : '');
  }
  /** A rough name for the sector, so "316°E" can be placed on a map. */
  function lonSector(d) {
    var e = ((d % 360) + 360) % 360;
    if (e >= 340 || e < 30) return 'Africa';
    if (e < 100) return 'the Indian Ocean';
    if (e < 160) return 'the Maritime Continent';
    if (e < 220) return 'the western and central Pacific';
    if (e < 280) return 'the eastern Pacific';
    return 'South America and the tropical Atlantic';
  }

  function renderRegMjo(b) {
    var card = rEl('regMjoCard');
    var box = HF.clear(rEl('regMjoBody'));
    card.hidden = !b.mjoOn;
    if (!b.mjoOn) return;
    var r = b.result, m = r.mjo, R = REG_RESP[b.response];
    if (!m || m.status !== 'ok') {
      box.appendChild(tx('p', 'tele-note', 'The MJO term was not fitted: ' + ((m && (m.reason || m.note)) || 'no reason given') + '.'));
      return;
    }
    var st = m.flag === 'detected' ? 'detected' : m.flag === 'below-floor' ? 'below' : 'unavailable';
    var sig = m.p < 0.05;
    var lagTxt = pentadText(m.lag) + ' before the storm’s first fix';

    box.appendChild(tx('p', 'reg-mjo-lead',
      'Does the MJO phase move ' + R.title + '? ' + pText(m.p) + ' (permutation, ' + fmtInt(m.nPerm) + ' shuffles). ' +
      'Read ' + lagTxt + '.'));

    // R against its own floor, on the same one-sided scale as the coefficient plot
    var plot = tx('div', 'chart reg-mjo-plot');
    box.appendChild(plot);
    HF.charts.coefPlot(plot, {
      oneSided: true,
      rows: [{
        key: 'mjo', label: 'MJO R', est: m.R, lo: m.ciR ? m.ciR[0] : null, hi: m.ciR ? m.ciR[1] : null, floor: m.mde80,
        floorShort: m.mde80 != null ? m.mde80.toFixed(2) : '', state: st, stateGlyph: REG_GLYPH[st], stateText: REG_STATE[st],
        valueText: m.R.toFixed(2), rangeText: m.ciR ? '[' + m.ciR[0].toFixed(2) + ', ' + m.ciR[1].toFixed(2) + ']' : '',
        floorText: m.mde80 != null ? 'floor ' + m.mde80.toFixed(2) : '',
        aria: 'MJO amplitude of response R ' + m.R.toFixed(2) + ' ' + R.units + ' per unit MJO amplitude, ' + REG_STATE[st].toLowerCase() +
              '; detection floor ' + (m.mde80 != null ? m.mde80.toFixed(2) : 'unavailable') + '; ' + pText(m.p) + '.'
      }],
      marks: m.rNull95 != null ? [{ row: 'mjo', value: m.rNull95, label: 'null 95th pct' }] : [],
      axisTitle: 'R, the size of the response (' + R.units + ' per unit MJO amplitude)',
      floorWord: 'detection floor', floorLegend: 'Detection floor for R', ciLegend: '95% interval for R',
      fmtTick: function (v) { return String(parseFloat(v.toFixed(2))); },
      ariaLabel: 'MJO response amplitude R against its detection floor and the 95th percentile of the no-effect permutation distribution'
    });

    var statements = tx('ul', 'reg-mjo-list');
    function li(text) { statements.appendChild(tx('li', '', text)); }
    li('R = ' + m.R.toFixed(2) + ' ' + R.units + ' per unit MJO amplitude (95% interval ' +
       (m.ciR ? m.ciR[0].toFixed(2) + ' to ' + m.ciR[1].toFixed(2) : 'withheld') + '). Detection floor ' +
       (m.mde80 != null ? m.mde80.toFixed(2) : 'unavailable') + '. Under no effect, 95% of the shuffles stay below ' +
       (m.rNull95 != null ? m.rNull95.toFixed(2) : 'n/a') + '.');
    if (sig && m.belowFloor) {
      li('Nominally significant, but R is under the floor. The sample could not reliably resolve an amplitude this small, so ' +
         'the size is probably overstated, and this is one lag of seven you could have chosen.');
    } else if (!sig) {
      li('Not significant. With R under the floor ' + (m.belowFloor ? 'as well, ' : 'not, ') +
         'this reads as unresolved at this lag, not as no MJO effect.');
    } else {
      li('Significant and above the floor at this lag.');
    }
    box.appendChild(statements);

    // where convection is at the phase of the largest response
    if (m.convectionLonDegE != null) {
      var opp = HF.regress.convectionLonAt(m.convectionLonByPhase, m.angleDeg + 180);
      var hi = lonText(m.convectionLonDegE), lo = opp != null ? lonText(opp) : null;
      box.appendChild(tx('h3', '', 'Where the convection is'));
      var geo = tx('p', 'reg-mjo-geo');
      geo.appendChild(document.createTextNode('The response is largest (' + R.up + ') when enhanced MJO convection is near '));
      geo.appendChild(tx('strong', '', hi));
      geo.appendChild(document.createTextNode(', over ' + lonSector(m.convectionLonDegE) + '.'));
      if (lo) {
        geo.appendChild(document.createTextNode(' It is smallest (' + R.down + ') with convection near '));
        geo.appendChild(tx('strong', '', lo));
        geo.appendChild(document.createTextNode(', over ' + lonSector(opp) + '.'));
      }
      box.appendChild(geo);
      if (m.convectionLonCI && m.convectionLonCI[0] != null && m.convectionLonCI[1] != null) {
        box.appendChild(tx('p', 'tele-note',
          '95% interval for that longitude: from ' + lonText(m.convectionLonCI[0]) + ' eastward to ' + lonText(m.convectionLonCI[1]) +
          ' (an arc of about ' + Math.round(m.angleCIWidth) + '° of phase).' +
          (sig ? '' : ' Because the effect itself is not significant, the longitude at which it peaks is not reliably located; do not read it as a finding.')));
      }
    }
    box.appendChild(tx('p', 'tele-note',
      'This is a locally derived phase from the CPC 200-hPa velocity-potential field at ten longitudes, and it is NOT Wheeler–Hendon RMM. ' +
      'There are no RMM octants here. Phase 0 is enhanced convection near 314°E (46°W), not the Maritime Continent, and the phase ' +
      'advances eastward with time. Only the joint size R is a result; the cosine and sine parts depend on where phase 0 was put.'));
  }

  /* ----------------------------------------------------- lag comparison */

  function sweepLagsStart() {
    var out = HF.clear(rEl('regSweepOut'));
    var token = ++reg.sweepToken;
    var btn = rEl('regSweep');
    btn.disabled = true;
    var rows = [], lag = 0;
    var status = tx('p', 'tele-note', 'Comparing lag 0 of 7…');
    out.appendChild(status);
    out.setAttribute('aria-busy', 'true');
    function step() {
      if (token !== reg.sweepToken) return;                 // controls changed: abandon
      if (lag > 6) { finish(); return; }
      status.textContent = 'Comparing lag ' + (lag + 1) + ' of 7…';
      setTimeout(function () {
        if (token !== reg.sweepToken) return;
        var saved = reg.lag;
        reg.lag = lag;
        var key = regKey(), b = reg.cache[key];
        if (!b) {
          b = regCompute();
          if (!b.error) { reg.cache[key] = b; reg.order.push(key); }
        }
        reg.lag = saved;
        rows.push({ lag: lag, b: b });
        lag++;
        step();
      }, 0);
    }
    function finish() {
      btn.disabled = false;
      out.removeAttribute('aria-busy');
      HF.clear(out);
      var hits = 0;
      var trs = rows.map(function (x) {
        var m = x.b.result && x.b.result.mjo;
        if (!m || m.status !== 'ok') return [pentadText(x.lag), '—', '—', 'not fitted'];
        if (m.p < 0.05) hits++;
        var s = m.flag === 'detected' ? 'detected' : 'below floor';
        return [pentadText(x.lag) + (x.lag === reg.lag ? ' (shown above)' : ''), m.R.toFixed(2), m.p.toFixed(3) + (m.p < 0.05 ? ' *' : ''), s];
      });
      out.appendChild(teleTable('MJO result at each lag from 0 to 6 pentads for ' + regLabel(),
        ['Lag', 'R (' + REG_RESP[reg.response].units + ')', 'Permutation p', 'State'], trs));
      var msg = hits + ' of 7 lags have p below 0.05 (marked *). Seven lags is seven looks at the same storms: ' +
        'if the MJO did nothing, about 30% of the time at least one lag would pass anyway (a little less in practice, because neighbouring lags are correlated). ' +
        'A single p of 0.025 at the lag you happened to pick is weaker evidence than it looks.';
      out.appendChild(tx('p', 'tele-note', msg));
      rEl('teleLive').textContent = 'MJO lag comparison for ' + regLabel() + ': ' + msg;
    }
    step();
  }

  function sweepReset() {
    reg.sweepToken++;
    HF.clear(rEl('regSweepOut')).removeAttribute('aria-busy');
    var btn = rEl('regSweep');
    if (btn) btn.disabled = false;
  }

  /* ---------------------------------------------------------- live region */

  function announceReg(b) {
    var r = b.result, R = REG_RESP[b.response];
    var parts = [b.label + ': ' + fmtInt(r.n.events) + ' events in ' + r.n.seasons + ' seasons.'];
    r.terms.forEach(function (t) {
      var st = termState(t);
      if (st === 'unavailable') { parts.push(termName(t) + ' unavailable.'); return; }
      parts.push(termName(t) + ' ' + REG_STATE[st].toLowerCase() + ', ' + signed(t.coef, 2) + ' ' + R.units +
                 ' per standard deviation, floor plus or minus ' + t.mde80.toFixed(2) + '.');
    });
    if (b.mjoOn && r.mjo && r.mjo.status === 'ok') {
      parts.push('MJO at lag ' + r.mjo.lag + ': R ' + r.mjo.R.toFixed(2) + ', ' + pText(r.mjo.p) +
                 (r.mjo.convectionLonDegE != null ? ', largest response with convection near ' + lonText(r.mjo.convectionLonDegE) : '') + '.');
    }
    parts.push('R squared ' + pct(r.r2) + ', of which calendar alone ' + pct(r.r2Base) + '.');
    parts.push('A term below its floor means this sample cannot resolve an effect that size, not that there is none.');
    rEl('teleLive').textContent = parts.join(' ');
  }

  /* ------------------------------------------------------------ controls */

  function syncRegControls() {
    rEl('regLagWrap').hidden = !reg.mjo;
    var lagWord = pentadText(reg.lag);
    rEl('regLagOut').textContent = lagWord;
    rEl('regLag').setAttribute('aria-valuetext', lagWord + ' before the storm');
    rEl('regRespHint').textContent = REG_RESP[reg.response].hint;
  }

  function buildReg() {
    if (reg.built) return;
    reg.built = true;
    function radios(name, apply) {
      Array.prototype.forEach.call(document.querySelectorAll('input[name="' + name + '"]'), function (r) {
        r.addEventListener('change', function () { if (r.checked) apply(r.value); });
      });
    }
    radios('regBasin', function (v) { reg.basin = v; sweepReset(); regRequest(); });
    rEl('regResponse').addEventListener('change', function (e) { reg.response = e.target.value; sweepReset(); regRequest(); });
    rEl('regInter').addEventListener('change', function (e) { reg.inter = e.target.checked; sweepReset(); regRequest(); });
    rEl('regMjo').addEventListener('change', function (e) { reg.mjo = e.target.checked; sweepReset(); regRequest(); });
    rEl('regLag').addEventListener('input', function (e) { reg.lag = Number(e.target.value); regRequest(); });
    rEl('regSweep').addEventListener('click', sweepLagsStart);
    renderRegMethod();
  }

  function renderRegMethod() {
    var box = HF.clear(rEl('regMethodBody'));
    function item(term, text) { box.appendChild(tx('h3', '', term)); box.appendChild(tx('p', '', text)); }
    item('Two ways of asking',
      'The composite map asks where the density of storms differs when an index is in a given state: it sorts events into thirds and ' +
      'tests about 150 map cells. The regression asks whether the index moves the whole distribution: it keeps the index as a number and ' +
      'asks one question of one number, such as the average latitude of a storm. They use the same events. The regression is the more ' +
      'powerful test of the second question, because it keeps the size of the index and does not spend its power across a map, which is why ' +
      'it can find an effect the map cannot. They do not contradict each other.');
    item('The grey band',
      'Beside every interval is the smallest true effect this sample would detect 80% of the time at the 5% level (the MDE80, 2.8 standard errors). ' +
      'The estimate and its interval are drawn against it. If they sit clear of the band, an effect of that size could be resolved and was. ' +
      'If they sit inside it, the sample could not have resolved an effect that small whatever the truth is.');
    item('Below the floor is not “no effect”',
      'An interval that includes zero is often read as “there is no effect”. For a sample this size that is the wrong reading: the interval ' +
      'is wide enough to include real effects as large as the floor. This is why every interaction term is shown with its floor. On this archive ' +
      'they sit inside it, which means the archive is too short to say whether these indices interact, not that they do not.');
    item('Units and standardising',
      'Each index is standardised over the events in the fit, so a coefficient is a change in the response per one standard deviation of the index, ' +
      'in the response’s own units (degrees, hPa or hours). NAO and PNA are the 5-day mean ending on the day of the first fix; ONI is the ' +
      'value for the month the storm began.');
    item('What is held fixed and what is resampled',
      'Month is a fixed effect, because the track moves hundreds of kilometres between October and February and the indices have their own seasonal ' +
      'cycle. Intervals come from resampling whole seasons (2,000 draws, fixed seed), since storms in a season share a background state. Only complete ' +
      'seasons are used, and each basin is its own model.');
    item('Looking at many models',
      'Two basins, four responses, interactions on or off, and seven MJO lags make dozens of models from the same storms. Each fit is honest about ' +
      'itself; none of them is corrected for the others. A single detected term found by trying several is a lead to confirm. The effects that stay ' +
      'put across responses and specifications are the ones to trust.');
    item('The MJO',
      'The phase is derived locally from the CPC 200-hPa velocity potential at ten longitudes and is not Wheeler–Hendon RMM, so there are no octants. ' +
      'It enters as a cosine and sine pair weighted by amplitude, and the pair is tested jointly by shuffling phase among storms in the same season and ' +
      'month. The result is reported as the longitude of the enhanced convection at the phase where the response is largest.');
  }

  function renderRegress() {
    buildReg();
    syncRegControls();
    if (!teleEngine()) {
      renderRegFailure('The teleconnection data or scripts did not load (' + (tele.failed || 'unknown error') + '), so nothing can be fitted here.');
      return;
    }
    if (reg.shown && reg.shown.key === regKey() && !reg.shown.error) {
      regSetPending(false);
      renderRegPlot(reg.shown);          // new theme or width: same result, redrawn
      renderRegMjo(reg.shown);
      return;
    }
    regRequest(true);
  }

  var TELE_VIEW_NOTES = {
    composite: 'Composite map: asks where the density of storms differs. It sorts events into thirds (or phases) of an index and tests about 150 map ' +
      'cells, so it spends its power across the map and throws away how large the index was. On this archive it usually finds no significant cells.',
    regress: 'Regression: asks whether the index moves the whole distribution, such as the average latitude, longitude or depth of a storm. It keeps ' +
      'the index as a number and asks one question of one number, so it is the more powerful test of that question, and it says how large an effect ' +
      'this sample could have seen. Same events, a different question: a shift of the whole track can be real when no single map cell passes.'
  };

  function setTeleView(v) {
    tele.view = v;
    var comp = v === 'composite';
    tEl('teleCompView').hidden = !comp;
    tEl('teleRegView').hidden = comp;
    tEl('teleViewNote').textContent = TELE_VIEW_NOTES[v];
    syncMapMode();
    renderTele();
    // Coming back to the composite: its result is already held and redrawn,
    // so say what is on screen again (the live region still holds the
    // regression's sentence, which is no longer visible).
    if (comp && tele.shown && !tele.shown.error) announceTele(tele.shown);
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
