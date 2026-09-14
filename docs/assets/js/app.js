/* Wiring: filter state -> KPIs, map, charts, table, detail drawer.
   One render() pass drives every view so the tabs can never disagree. */

(function (HF) {
  'use strict';

  var DATA = null;
  var LOWS = [];

  var state = {
    tab: 'map',
    basin: 'both',
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

  /* ------------------------------------------------------------ filtering */

  function passes(low) {
    if (state.basin !== 'both' && low.basin !== state.basin) return false;
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

  function renderKpis(lows) {
    var box = HF.clear(document.getElementById('kpis'));
    var seasons = activeSeasons().length || 1;
    var pressures = lows.map(function (l) { return l.minP; });
    var deepest = null;
    lows.forEach(function (l) {
      if (l.minP != null && (!deepest || l.minP < deepest.minP)) deepest = l;
    });
    var withBerg = lows.filter(function (l) { return l.berg != null; });
    var bombs = withBerg.filter(function (l) { return l.bomb; });

    var tiles = [
      { label: 'Events', value: lows.length.toLocaleString(),
        note: lows.length ? (lows.length / seasons).toFixed(1) + ' per season over ' + seasons + ' seasons' : 'nothing matches the filters' },
      { label: 'Median min pressure',
        value: pressures.some(function (p) { return p != null; }) ? HF.median(pressures) + ' hPa' : '--',
        note: 'lowest analyzed pressure per event' },
      { label: 'Deepest event',
        value: deepest ? deepest.minP + ' hPa' : '--',
        note: deepest ? deepest.id + ' · ' + HF.fmtDate(deepest.minPAt) : '' },
      { label: 'Median time at HF',
        value: lows.length ? HF.median(lows.map(function (l) { return l.hfH; })) + ' h' : '--',
        note: '6-hourly fixes × 6 h' },
      { label: 'Explosive share',
        value: withBerg.length ? Math.round(100 * bombs.length / withBerg.length) + '%' :  '--',
        note: withBerg.length ? bombs.length + ' of ' + withBerg.length + ' events with 24 h of pressures' : 'no qualifying events' },
      { label: 'Track length',
        value: lows.length ? HF.median(lows.map(function (l) { return l.distNm; })).toLocaleString() + ' nm' : '--',
        note: 'median distance covered while tracked' }
    ];

    tiles.forEach(function (t) {
      var card = HF.el('div', { class: 'kpi' });
      card.appendChild(HF.el('div', { class: 'k-label' }, t.label));
      card.appendChild(HF.el('div', { class: 'k-value' }, t.value));
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
    state.selectedKey = low ? low.key : null;
    if (low) {
      renderDetail(low);
      document.body.classList.add('has-detail');
      HF.maps.invalidate();
      HF.maps.focus(low);
    } else {
      document.getElementById('detail').hidden = true;
      document.body.classList.remove('has-detail');
      HF.maps.invalidate();
    }
    render();
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

  /* ------------------------------------------------------------ map chrome */

  function renderMap(lows) {
    HF.maps.render(lows, state.layer, state.selectedKey);
    renderLegend(lows);

    var note = document.getElementById('mapNote');
    if (state.layer === 'density') {
      note.textContent = 'Hurricane force fixes per ' + HF.maps.CELL_LAT + '° × ' +
        HF.maps.CELL_LON + '° cell, over the filtered seasons.';
    } else if (state.layer === 'genesis') {
      note.textContent = 'First tracked fix of each event — where the archive picked the low up, not true cyclogenesis.';
    } else if (state.layer === 'peak') {
      note.textContent = 'Position of each event’s lowest analyzed pressure; marker size grows as pressure falls.';
    } else {
      note.textContent = lows.length > 300
        ? lows.length.toLocaleString() + ' tracks \u2014 thinned so the overlap reads as density. ' +
          'Filter, or switch to Fix density, for a cleaner picture.'
        : lows.length.toLocaleString() + ' track' + (lows.length === 1 ? '' : 's') +
          ' shown. Click one for its fixes.';
    }
  }

  function renderLegend(lows) {
    var box = HF.clear(document.getElementById('mapLegend'));

    if (state.layer === 'density') {
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

    if (state.layer === 'genesis') {
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

    var sources = DATA.basins.map(function (b) {
      return b.label + ': ' + b.rows.toLocaleString() + ' rows from ' + b.source;
    }).join(' · ');
    document.getElementById('sourceLine').textContent =
      'Built ' + DATA.generated + ' — ' + sources + '.';
  }

  /* --------------------------------------------------------------- render */

  function render() {
    var lows = filtered();
    renderKpis(lows);
    if (state.tab === 'map') renderMap(lows);
    if (state.tab === 'clim') renderCharts(lows);
    if (state.tab === 'events') renderTable(lows);
  }

  /* -------------------------------------------------------------- controls */

  function syncControls() {
    document.getElementById('fBasin').value = state.basin;
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
    DATA.seasons.forEach(function (s) {
      s0.appendChild(HF.el('option', { value: s.start }, s.label));
      s1.appendChild(HF.el('option', { value: s.start }, s.label));
    });
    state.season0 = DATA.seasons[0].start;
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

    document.getElementById('fBasin').addEventListener('change', function (e) {
      state.basin = e.target.value;
      HF.maps.setFrame(state.basin);
      HF.maps.resetView(state.basin);
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
      state.season0 = DATA.seasons[0].start;
      state.season1 = DATA.seasons[DATA.seasons.length - 1].start;
      state.months = {};
      state.maxPressure = 1010;
      state.bombOnly = false;
      state.search = '';
      state.selectedKey = null;
      document.getElementById('detail').hidden = true;
      HF.maps.setFrame(state.basin);
      HF.maps.resetView(state.basin);
      syncControls();
      render();
    });

    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
      tab.addEventListener('click', function () {
        state.tab = tab.dataset.panel;
        Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) {
          var on = t === tab;
          t.classList.toggle('is-active', on);
          t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        Array.prototype.forEach.call(document.querySelectorAll('.panel'), function (p) {
          p.classList.toggle('is-active', p.id === 'panel-' + state.tab);
        });
        if (state.tab === 'map') setTimeout(function () { HF.maps.invalidate(); }, 0);
        render();
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll('.seg'), function (seg) {
      seg.addEventListener('click', function () {
        state.layer = seg.dataset.layer;
        Array.prototype.forEach.call(document.querySelectorAll('.seg'), function (s) {
          s.classList.toggle('is-active', s === seg);
        });
        render();
      });
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
        HF.maps.invalidate();
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
    if (!window.HF_DATA) {
      document.getElementById('vintage').textContent = 'data failed to load';
      return;
    }
    restoreTheme();
    DATA = HF.decode(window.HF_DATA);
    LOWS = DATA.lows;
    HF.CATEGORIES = DATA.categories;

    document.getElementById('vintage').textContent =
      DATA.lows.length.toLocaleString() + ' events, ' +
      DATA.seasons[0].label + ' to ' + DATA.seasons[DATA.seasons.length - 1].label;

    HF.maps.init('map', select);
    HF.maps.setFrame(state.basin);
    HF.maps.resetView(state.basin);

    buildControls();
    syncControls();
    renderQc();
    renderMethod();
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

})(window.HF);
