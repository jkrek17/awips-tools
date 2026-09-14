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
    layer: 'tracks',
    sort: { key: 'start', dir: -1 },
    selectedKey: null
  };

  var TABLE_LIMIT = 300;
  var globeReady = false;    // the globe is heavier to spin up than the flat map, so it waits until first needed
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
      if (usingGlobe()) { ensureGlobe(); HF.globe.focus(low); }
      else HF.maps.focus(low);
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
     Both basins meet at the Arctic, and no flat projection shows that
     honestly, so "both" swaps the flat Leaflet map for a rotatable
     orthographic globe; a single basin keeps the flat tiled map. The two
     views share the same filtered lows, selection and theme - this section
     is the only place that decides which one is on screen. */

  function usingGlobe() { return state.basin === 'both'; }

  // The map's layer switcher (density/genesis/peak) and "Fit to events" only
  // make sense against the flat projection; the globe only ever draws
  // tracks, so map-note/legend text keys off this rather than state.layer
  // directly whenever the globe might be showing.
  function activeLayer() { return usingGlobe() ? 'tracks' : state.layer; }

  function ensureGlobe() {
    if (globeReady) return;
    HF.globe.init('globe', select);
    HF.globe.applyTheme();
    globeReady = true;
  }

  /** Leaflet/the globe both no-op a resize on a hidden container, so this is
      safe to call whenever the view might have just become visible; the
      timeout lets the "hidden" attribute's layout change land first. */
  function resizeActiveView() {
    setTimeout(function () {
      if (usingGlobe()) { if (globeReady) HF.globe.resize(); }
      else HF.maps.invalidate();
    }, 0);
  }

  /** Toggle the flat-map/globe containers and the controls that only apply
      to the flat map, and make sure whichever view is now current has the
      right size and is the only one animating. Call after anything that can
      change the basin or the active tab. */
  function syncMapMode() {
    var globeOn = usingGlobe();
    if (globeOn) ensureGlobe();

    document.getElementById('map').hidden = globeOn;
    document.getElementById('globeWrap').hidden = !globeOn;

    var segmented = document.querySelector('#panel-map .segmented');
    var fitBtn = document.getElementById('fitBounds');
    if (segmented) segmented.hidden = globeOn;
    if (fitBtn) fitBtn.hidden = globeOn;

    if (globeReady) HF.globe.setVisible(globeOn && state.tab === 'map');
    if (state.tab === 'map') resizeActiveView();
  }

  function applyBasinSideEffects() {
    HF.maps.setFrame(state.basin);
    HF.maps.resetView(state.basin);
    syncMapMode();
  }

  /* ------------------------------------------------------------ map chrome */

  function renderMap(lows) {
    if (usingGlobe()) {
      ensureGlobe();
      HF.globe.render(lows, state.selectedKey);
    } else {
      HF.maps.render(lows, state.layer, state.selectedKey);
    }
    renderLegend(lows);

    var layer = activeLayer();
    var note = document.getElementById('mapNote');
    if (layer === 'density') {
      note.textContent = 'Hurricane force fixes per ' + HF.maps.CELL_LAT + '° × ' +
        HF.maps.CELL_LON + '° cell, over the filtered seasons.';
    } else if (layer === 'genesis') {
      note.textContent = 'First tracked fix of each event — where the archive picked the low up, not true cyclogenesis.';
    } else if (layer === 'peak') {
      note.textContent = 'Position of each event’s lowest analyzed pressure; marker size grows as pressure falls.';
    } else {
      note.textContent = lows.length > 300
        ? lows.length.toLocaleString() + ' tracks \u2014 thinned so the overlap reads as density. ' +
          'Filter, or switch to Fix density, for a cleaner picture.'
        : lows.length.toLocaleString() + ' track' + (lows.length === 1 ? '' : 's') +
          ' shown. Click one for its fixes.';
      if (usingGlobe()) {
        note.textContent += ' Both basins meet at the pole, so this is a rotatable globe — drag to rotate, scroll to zoom, double-click to reset. Layer and fit controls apply to the flat map only.';
      }
    }
  }

  function renderLegend(lows) {
    lows = lows || [];
    var box = HF.clear(document.getElementById('mapLegend'));
    var layer = activeLayer();

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
      return;
    }

    box.appendChild(HF.el('h3', {}, 'Minimum pressure'));
    var bar = HF.el('div', { class: 'legend-scale' });
    HF.PRESSURE_BANDS.slice().reverse().forEach(function (band) {
      var seg = HF.el('span');
      seg.style.background = HF.pressureColor(band.v);
      seg.title = band.label + ' hPa';
      bar.appendChild(seg);
    });
    box.appendChild(bar);
    var ends = HF.el('div', { class: 'legend-ends' });
    ends.appendChild(HF.el('span', {}, '\u2265 1000'));
    ends.appendChild(HF.el('span', {}, '< 940 hPa'));
    box.appendChild(ends);
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
    if (state.selectedKey) {
      box.appendChild(HF.el('p', { class: 'legend-note' },
        'Markers on the selected track are coloured by category at that fix.'));
    }
  }

  /* --------------------------------------------------------- static panels */

  function renderQc() {
    var LABELS = {
      rowsRead: 'rows read', fixes: 'fixes kept', lows: 'events built',
      rowsDropped: 'rows dropped', exactDuplicates: 'duplicate rows removed',
      duplicateTimes: 'shared timestamps', datesRepaired: 'dates repaired',
      dateNotes: 'off-synoptic hours', positionNotes: 'positions questioned',
      categoriesMapped: 'categories mapped', categoriesUnknown: 'categories unknown',
      pressuresRepaired: 'pressures repaired', pressuresDropped: 'pressures dropped',
      idsSuspect: 'IDs malformed', idsReused: 'IDs reused by two events',
      lowsDropped: 'events dropped'
    };
    var box = HF.clear(document.getElementById('qcCounts'));
    Object.keys(DATA.qc.counts).forEach(function (k) {
      var cell = HF.el('div', { class: 'qc-count' });
      cell.appendChild(HF.el('b', {}, DATA.qc.counts[k].toLocaleString()));
      cell.appendChild(HF.el('span', {}, LABELS[k] || k));
      box.appendChild(cell);
    });

    var tbody = HF.clear(document.getElementById('qcTable').tBodies[0]);
    DATA.qc.notes.forEach(function (n) {
      var tr = HF.el('tr');
      tr.appendChild(HF.el('td', {}, n.basin === 'pac' ? 'Pacific' : 'Atlantic'));
      tr.appendChild(HF.el('td', { class: 'num' }, n.row == null ? '--' : String(n.row)));
      tr.appendChild(HF.el('td', {}, n.id || '--'));
      tr.appendChild(HF.el('td', {}, n.date ? HF.fmtDate(n.date) : '--'));
      tr.appendChild(HF.el('td', {}, n.kind));
      var td = HF.el('td', {}, n.detail);
      td.style.whiteSpace = 'normal';
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
  }

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
      syncMapMode();
      render();
    }

    Array.prototype.forEach.call(document.querySelectorAll('.seg'), function (seg) {
      seg.addEventListener('click', function () {
        state.layer = seg.dataset.layer;
        Array.prototype.forEach.call(document.querySelectorAll('.seg'), function (s) {
          s.classList.toggle('is-active', s === seg);
        });
        render();
      });
    });

    document.getElementById('fitBounds').addEventListener('click', function () {
      HF.maps.fitTo(filtered());
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
        if (usingGlobe()) { if (globeReady) HF.globe.resize(); }
        else HF.maps.invalidate();
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
    HF.maps.applyTheme();
    if (globeReady) HF.globe.applyTheme();
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
      renderQc();
      renderMethod();

      // Unhide before initializing the map/globe and doing the first render,
      // so Leaflet and the canvas both measure a real, laid-out container
      // instead of a hidden (zero-size) one.
      loadingEl.hidden = true;
      if (mainEl) mainEl.hidden = false;
      if (kpisEl) kpisEl.hidden = false;

      HF.maps.init('map', select);
      HF.maps.setFrame(state.basin);
      HF.maps.resetView(state.basin);
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
