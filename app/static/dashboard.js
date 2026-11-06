/* DataSearch Hardware — gráficos Plotly, carregados sob demanda.
   Nenhuma dependência de CDN: Plotly vem de /static/vendor. O arquivo só é
   injetado quando a aba Gráficos é aberta pela primeira vez. */

(function () {
  'use strict';

  const RANGES = ['24h', '7d', '30d', '90d', '1y'];
  const PLOTLY_URL = '/static/vendor/plotly-2.35.2.min.js';
  const COLOR = {
    blue: '#4f8cff',
    orange: '#ff9f43',
    green: '#2dd4a7',
    red: '#ff5c5c',
    muted: '#7c8aa5',
    grid: '#263149',
    zero: '#475569',
    txt: '#94a3bd',
  };

  const DASH = {
    active: false,
    snapshot: null,
    core: null,
    driverHist: null,
    catData: null,
    catalog: null,
    range: '24h',
    category: null,
    cache: new Map(),
    loading: null,
    token: 0,
    error: null,
  };

  const d$ = (id) => document.getElementById(id);

  const dEsc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  const dNum = (v, digits = 1) => (
    v === null || v === undefined ? '—' : Number(v).toLocaleString('pt-BR', {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    })
  );

  const dPct = (v, digits = 1) => (
    v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(digits)}%`
  );

  const dColor = (score) => {
    if (score >= 70) return COLOR.red;
    if (score >= 58) return COLOR.orange;
    if (score >= 45) return COLOR.muted;
    if (score >= 35) return '#3ec5a0';
    return COLOR.green;
  };

  const short = (s, n = 26) => {
    const t = String(s || '');
    return t.length > n ? `${t.slice(0, n - 1)}…` : t;
  };

  function xTickFormat() {
    return DASH.range === '24h' ? '%H:%M' : '%d/%m';
  }

  function axis(extra = {}) {
    return {
      gridcolor: COLOR.grid,
      zerolinecolor: COLOR.zero,
      linecolor: COLOR.grid,
      tickfont: { size: 10, color: '#64748b' },
      ...extra,
    };
  }

  function layout(extra = {}) {
    const base = {
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', color: COLOR.txt, size: 11 },
      margin: { l: 54, r: 18, t: 34, b: 38 },
      hovermode: 'x unified',
      hoverlabel: { bgcolor: '#161d2e', bordercolor: '#3b4a68', font: { color: '#e8edf7', size: 12 } },
      legend: { orientation: 'h', x: 0, y: 1.12, font: { size: 10.5 } },
      colorway: [COLOR.blue, COLOR.orange, COLOR.green, COLOR.red, '#c084fc', '#facc15', '#38bdf8', '#fb7185'],
      xaxis: axis(),
      yaxis: axis(),
    };
    return {
      ...base,
      ...extra,
      xaxis: { ...base.xaxis, ...(extra.xaxis || {}) },
      yaxis: { ...base.yaxis, ...(extra.yaxis || {}) },
    };
  }

  const CONFIG = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
    toImageButtonOptions: {
      format: 'png',
      filename: 'datasearch-hardware',
      scale: 2,
    },
  };

  function draw(id, traces, extraLayout) {
    const el = d$(id);
    if (!el || !window.Plotly) return;
    window.Plotly.react(el, traces, layout(extraLayout), CONFIG).catch((err) => {
      console.error('plotly', id, err);
      el.innerHTML = `<p class="dash-error">Falha ao desenhar o gráfico: ${dEsc(err.message)}</p>`;
    });
  }

  function drawEmpty(id, message) {
    draw(
      id,
      [],
      {
        xaxis: { visible: false },
        yaxis: { visible: false },
        margin: { l: 10, r: 10, t: 10, b: 10 },
        annotations: [{
          text: message,
          showarrow: false,
          xref: 'paper',
          yref: 'paper',
          x: 0.5,
          y: 0.5,
          font: { size: 12.5, color: '#64748b' },
        }],
      },
    );
  }

  function modeFor(points) {
    return points && points.length < 3 ? 'lines+markers' : 'lines';
  }

  function points(series) {
    return (series && series.points) || [];
  }

  // Linha de uma série com `model_since`: o trecho antes do marco usa a conta
  // antiga e vira uma linha própria, esmaecida e pontilhada (como a fila).
  // Sem marco, devolve uma linha só, igual a antes.
  function lineTraces(series, base) {
    const all = points(series);
    if (!all.length) return [];
    const sinceMs = series && series.model_since ? Date.parse(series.model_since) : NaN;
    const old = Number.isFinite(sinceMs) ? all.filter((p) => Date.parse(p.t) < sinceMs) : [];
    const cur = Number.isFinite(sinceMs) ? all.filter((p) => Date.parse(p.t) >= sinceMs) : all;
    const trace = (pts, extra) => ({
      ...base,
      x: pts.map((p) => p.t),
      y: pts.map((p) => p.v),
      type: 'scatter',
      mode: modeFor(pts),
      connectgaps: false,
      ...extra,
    });
    const out = [];
    if (old.length) {
      const day = new Date(sinceMs).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
      out.push(trace(old, {
        name: `${base.name} (conta antiga, até ${day})`,
        line: { ...base.line, width: 1.6, dash: 'dot' },
        opacity: 0.45,
        hovertemplate: (base.hovertemplate || '').replace('<extra>', '<extra>conta antiga · '),
      }));
    }
    if (cur.length) out.push(trace(cur, {}));
    return out;
  }

  function lastValue(series) {
    const pts = points(series);
    for (let i = pts.length - 1; i >= 0; i -= 1) {
      if (pts[i].v !== null && pts[i].v !== undefined) return pts[i].v;
    }
    return null;
  }

  function firstValue(series) {
    for (const p of points(series)) {
      if (p.v !== null && p.v !== undefined) return p.v;
    }
    return null;
  }

  function delta(series) {
    const first = firstValue(series);
    const last = lastValue(series);
    if (first === null || last === null) return null;
    return last - first;
  }

  function setStatus(text, cls = '') {
    const el = d$('dashStatus');
    if (!el) return;
    el.textContent = text;
    el.className = `dash-status${cls ? ` ${cls}` : ''}`;
  }

  /* ---------------- Plotly sob demanda ---------------- */

  function loadPlotly() {
    if (window.Plotly) return Promise.resolve(window.Plotly);
    if (DASH.loading) return DASH.loading;
    DASH.loading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = PLOTLY_URL;
      script.async = true;
      script.onload = () => resolve(window.Plotly);
      script.onerror = () => reject(new Error('não foi possível carregar o Plotly local'));
      document.head.appendChild(script);
    });
    return DASH.loading;
  }

  /* ---------------- dados ---------------- */

  async function ensureCatalog() {
    if (DASH.catalog) return;
    const res = await fetch('/api/series');
    if (!res.ok) throw new Error(`HTTP ${res.status} em /api/series`);
    const data = await res.json();
    DASH.catalog = new Set(
      (data.groups || []).flatMap((g) => (g.series || []).map((s) => s.key)),
    );
  }

  function seriesUrl(keys) {
    return `/api/history?range=${encodeURIComponent(DASH.range)}&series=${encodeURIComponent(keys.join(','))}&bucket=auto`;
  }

  async function fetchHistory(keys) {
    const valid = DASH.catalog ? keys.filter((k) => DASH.catalog.has(k)) : keys;
    const cacheKey = `${DASH.range}|${valid.join(',')}`;
    if (DASH.cache.has(cacheKey)) return DASH.cache.get(cacheKey);
    const res = await fetch(seriesUrl(valid));
    if (!res.ok) throw new Error(`HTTP ${res.status} em /api/history`);
    const data = await res.json();
    const map = Object.fromEntries((data.series || []).map((s) => [s.key, s]));
    map.__meta = {
      bucket_seconds: data.bucket_seconds,
      from: data.from,
      to: data.to,
      interpolated: data.interpolated,
    };
    DASH.cache.set(cacheKey, map);
    return map;
  }

  async function ensureData() {
    await ensureCatalog();
    const coreKeys = [
      'iph', 'iph_br', 'coverage',
      'supply.queue', 'supply.capex_ttm', 'supply.inventory_ratio', 'supply.diversion',
    ];
    const driverKeys = (DASH.snapshot.drivers || []).map((d) => `driver.${d.key}`);
    const [core, driverHist] = await Promise.all([
      fetchHistory(coreKeys),
      fetchHistory(driverKeys),
    ]);
    DASH.core = core;
    DASH.driverHist = driverHist;
    if (!DASH.category) {
      DASH.category = (DASH.snapshot.ranking[0] || {}).key || null;
    }
    await ensureCategory(DASH.category);
  }

  async function ensureCategory(key) {
    if (!key) {
      DASH.catData = null;
      return;
    }
    const keys = [`cat.${key}.proj30_br`, `cat.${key}.proj30_global`];
    const ipcaKey = `obs.${key}.ipca`;
    if (!DASH.catalog || DASH.catalog.has(ipcaKey)) keys.push(ipcaKey);
    DASH.catData = await fetchHistory(keys);
    DASH.catData.__category = key;
  }

  /* ---------------- render: KPIs ---------------- */

  function renderKpis() {
    const snap = DASH.snapshot;
    if (!snap) return;
    const core = DASH.core || {};
    const iph = lastValue(core.iph);
    const iphBr = lastValue(core.iph_br);
    const dIph = delta(core.iph);
    const dBr = delta(core.iph_br);
    const supply = snap.supply || {};
    const top = (snap.ranking || [])[0];
    const ok = (snap.sources || []).filter((s) => s.status === 'ok').length;
    const total = (snap.sources || []).length;

    const card = (label, value, sub, color, badge = '') => `
      <div class="kpi">
        <div class="kpi-label">${dEsc(label)} ${badge}</div>
        <div class="kpi-value"${color ? ` style="color:${color}"` : ''}>${value}</div>
        <div class="kpi-sub">${sub}</div>
      </div>`;

    d$('dashKpis').innerHTML = [
      card(
        'Pressão agora',
        iph === null ? '—' : dNum(iph, 1),
        `${dPct(dIph)} no período`,
        iph === null ? null : dColor(iph),
        '<span class="badge modeled">estimativa</span>',
      ),
      card(
        'Pressão no Brasil',
        iphBr === null ? '—' : dNum(iphBr, 1),
        `${dPct(dBr)} no período · dólar + impostos`,
        iphBr === null ? null : dColor(iphBr),
        '<span class="badge modeled">estimativa</span>',
      ),
      card(
        'Fila do consumidor',
        supply.queue_pressure === null || supply.queue_pressure === undefined ? '—' : dNum(supply.queue_pressure, 1),
        dEsc(supply.queue_label || 'sem dados'),
        supply.queue_pressure === null || supply.queue_pressure === undefined ? null : dColor(supply.queue_pressure),
        '<span class="badge modeled">estimativa</span>',
      ),
      card(
        'Dados disponíveis',
        `${Math.round((snap.summary.coverage || 0) * 100)}%`,
        `${ok}/${total} fontes disponíveis · ${(snap.degraded || []).length} com problema`,
        null,
      ),
      card(
        'Maior alta estimada',
        top ? dPct(top.projected_brazil_30d_pct) : '—',
        top ? `${dEsc(top.label)} em 30 dias` : 'sem lista de produtos',
        top ? dColor(top.pressure_score) : null,
        '<span class="badge modeled">estimativa</span>',
      ),
      card(
        'Investimento em IA',
        supply.capex_ttm_usd ? `US$ ${dNum(supply.capex_ttm_usd / 1e9, 1)} bi` : '—',
        `${dPct(supply.capex_growth_pct)} a/a · SEC`,
        null,
        '<span class="badge observed">oficial</span>',
      ),
    ].join('');
  }

  /* ---------------- render: gráficos ---------------- */

  function renderIndex() {
    const core = DASH.core || {};
    const iph = core.iph;
    const iphBr = core.iph_br;
    if (!points(iph).length && !points(iphBr).length) {
      drawEmpty('dashIndex', 'O histórico começa no primeiro ciclo de coleta. Volte em alguns minutos.');
      return;
    }
    const traces = [
      ...lineTraces(iph, {
        name: 'Pressão global',
        line: { color: COLOR.blue, width: 2.4 },
        hovertemplate: '%{y:.1f}<extra>Pressão global</extra>',
      }),
      ...lineTraces(iphBr, {
        name: 'Pressão no Brasil',
        line: { color: COLOR.orange, width: 2.4 },
        hovertemplate: '%{y:.1f}<extra>Pressão no Brasil</extra>',
      }),
    ];
    draw('dashIndex', traces, {
      xaxis: { type: 'date', tickformat: xTickFormat(), hoverformat: '%d/%m/%Y %H:%M' },
      yaxis: { range: [0, 100], title: { text: '0-100', font: { size: 10 } } },
      shapes: [{
        type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 50, y1: 50,
        line: { color: '#475569', width: 1, dash: 'dot' },
      }],
    });
  }

  function renderSupply() {
    const core = DASH.core || {};
    const queue = core['supply.queue'];
    const capex = core['supply.capex_ttm'];
    if (!points(queue).length && !points(capex).length) {
      drawEmpty('dashSupply', 'A fila é gravada a cada ciclo. Ainda não há histórico suficiente.');
      return;
    }
    const traces = [];
    // Antes de `model_since` a fila usava a conta antiga (presa em 100): os
    // pontos ficam no gráfico, esmaecidos e pontilhados, numa série própria.
    const sinceMs = queue && queue.model_since ? Date.parse(queue.model_since) : NaN;
    const qAll = points(queue);
    const qOld = Number.isFinite(sinceMs) ? qAll.filter((p) => Date.parse(p.t) < sinceMs) : [];
    const qNew = Number.isFinite(sinceMs) ? qAll.filter((p) => Date.parse(p.t) >= sinceMs) : qAll;
    if (qOld.length) {
      const day = new Date(sinceMs).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
      traces.push({
        x: qOld.map((p) => p.t),
        y: qOld.map((p) => p.v),
        type: 'scatter',
        mode: modeFor(qOld),
        name: `Fila (conta antiga, até ${day})`,
        line: { color: COLOR.green, width: 1.6, dash: 'dot' },
        opacity: 0.45,
        connectgaps: false,
        hovertemplate: '%{y:.1f}<extra>Fila · conta antiga</extra>',
      });
    }
    if (qNew.length) {
      traces.push({
        x: qNew.map((p) => p.t),
        y: qNew.map((p) => p.v),
        type: 'scatter',
        mode: modeFor(qNew),
        name: 'Fila do consumidor',
        line: { color: COLOR.green, width: 2.6 },
        connectgaps: false,
        hovertemplate: '%{y:.1f}<extra>Fila</extra>',
      });
    }
    if (points(capex).length) {
      traces.push({
        x: points(capex).map((p) => p.t),
        y: points(capex).map((p) => p.v / 1e9),
        type: 'scatter',
        mode: modeFor(points(capex)),
        name: 'Investimento em IA (US$ bi)',
        yaxis: 'y2',
        line: { color: COLOR.orange, width: 2 },
        fill: 'tozeroy',
        fillcolor: 'rgba(255,159,67,.08)',
        connectgaps: false,
        hovertemplate: 'US$ %{y:.1f} bi<extra>Investimento em IA</extra>',
      });
    }
    draw('dashSupply', traces, {
      xaxis: { type: 'date', tickformat: xTickFormat(), hoverformat: '%d/%m/%Y %H:%M' },
      yaxis: { range: [0, 100], title: { text: 'fila', font: { size: 10 } } },
      yaxis2: {
        overlaying: 'y',
        side: 'right',
        showgrid: false,
        zerolinecolor: COLOR.zero,
        tickfont: { size: 10, color: '#64748b' },
        title: { text: 'US$ bi', font: { size: 10 } },
      },
      shapes: [{
        type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 50, y1: 50,
        line: { color: '#475569', width: 1, dash: 'dot' },
      }],
    });
  }

  function renderRanking() {
    const snap = DASH.snapshot;
    if (!snap || !(snap.ranking || []).length) {
      drawEmpty('dashRanking', 'Estimativa por produto indisponível nesta rodada.');
      return;
    }
    const items = [...snap.ranking].sort(
      (a, b) => a.projected_brazil_30d_pct - b.projected_brazil_30d_pct,
    );
    const y = items.map((i) => short(i.label, 24));
    const custom = items.map((i) => i.key);
    const colors = items.map((i) => i.pressure_score);
    draw('dashRanking', [
      {
        x: items.map((i) => i.projected_global_30d_pct),
        y,
        type: 'bar',
        orientation: 'h',
        name: 'Global (US$)',
        marker: { color: 'rgba(124,138,165,.55)' },
        customdata: custom,
        hovertemplate: '%{y}<br>global %{x:+.1f}%<extra></extra>',
      },
      {
        x: items.map((i) => i.projected_brazil_30d_pct),
        y,
        type: 'bar',
        orientation: 'h',
        name: 'Brasil (câmbio + carga)',
        marker: {
          color: colors,
          colorscale: [[0, COLOR.green], [0.5, COLOR.muted], [1, COLOR.red]],
          cmin: 0,
          cmax: 100,
        },
        customdata: custom,
        hovertemplate: '%{y}<br>Brasil %{x:+.1f}%<extra></extra>',
      },
    ], {
      barmode: 'group',
      margin: { l: 150, r: 20, t: 24, b: 38 },
      xaxis: { zeroline: true, zerolinecolor: COLOR.zero, title: { text: 'variação projetada 30d (%)', font: { size: 10 } } },
      yaxis: { automargin: true, tickfont: { size: 10.5, color: COLOR.txt } },
    });
    bindCategoryClick('dashRanking');
  }

  function renderCategory() {
    const data = DASH.catData;
    const key = DASH.category;
    const src = d$('dashCategorySrc');
    if (!data || !key) {
      if (src) src.textContent = '—';
      drawEmpty('dashCategoryChart', 'Selecione um produto.');
      return;
    }
    const item = (DASH.snapshot.ranking || []).find((i) => i.key === key);
    if (src) src.textContent = item ? item.label : key;

    const br = data[`cat.${key}.proj30_br`];
    const global = data[`cat.${key}.proj30_global`];
    const ipca = data[`obs.${key}.ipca`];
    if (src && !points(ipca).length) {
      src.textContent += ' · sem inflação no período';
    }
    if (!points(br).length && !points(global).length && !points(ipca).length) {
      drawEmpty('dashCategoryChart', 'Ainda não há histórico deste produto.');
      return;
    }
    const traces = [
      ...lineTraces(br, {
        name: 'Estimativa Brasil 30d',
        line: { color: COLOR.orange, width: 2.4 },
        hovertemplate: '%{y:+.2f}%<extra>Brasil 30d</extra>',
      }),
      ...lineTraces(global, {
        name: 'Estimativa global 30d',
        line: { color: COLOR.blue, width: 2, dash: 'dash' },
        hovertemplate: '%{y:+.2f}%<extra>Global 30d</extra>',
      }),
    ];
    if (points(ipca).length) {
      traces.push({
        x: points(ipca).map((p) => p.t),
        y: points(ipca).map((p) => p.v),
        type: 'bar',
        name: 'Inflação mensal (oficial)',
        yaxis: 'y2',
        marker: { color: 'rgba(45,212,167,.45)' },
        hovertemplate: '%{y:+.2f}%<extra>Inflação do mês</extra>',
      });
    }
    draw('dashCategoryChart', traces, {
      margin: { l: 52, r: 52, t: 30, b: 38 },
      xaxis: { type: 'date', tickformat: xTickFormat(), hoverformat: '%d/%m/%Y %H:%M' },
      yaxis: { title: { text: 'estimativa 30d (%)', font: { size: 10 } }, zerolinecolor: COLOR.zero },
      yaxis2: {
        overlaying: 'y',
        side: 'right',
        showgrid: false,
        zerolinecolor: COLOR.zero,
        tickfont: { size: 10, color: '#64748b' },
        title: { text: 'inflação do mês (%)', font: { size: 10 } },
      },
      bargap: 0.55,
    });
  }

  function renderRadar() {
    const snap = DASH.snapshot;
    if (!snap || !(snap.drivers || []).length) {
      drawEmpty('dashRadar', 'Vetores indisponíveis.');
      return;
    }
    const drivers = snap.drivers;
    const labels = drivers.map((d) => short(d.label.split(':')[0].split('—')[0].trim(), 18));
    const now = drivers.map((d) => d.score);
    const hist = DASH.driverHist || {};
    const start = drivers.map((d) => firstValue(hist[`driver.${d.key}`]));
    const traces = [{
      type: 'scatterpolar',
      r: now,
      theta: labels,
      fill: 'toself',
      name: 'agora',
      line: { color: COLOR.orange, width: 2 },
      fillcolor: 'rgba(255,159,67,.12)',
      hovertemplate: '%{theta}: %{r:.0f}<extra>agora</extra>',
    }];
    if (start.every((v) => v !== null && v !== undefined)) {
      traces.push({
        type: 'scatterpolar',
        r: start,
        theta: labels,
        fill: 'toself',
        name: 'início da janela',
        line: { color: COLOR.blue, width: 1.8, dash: 'dot' },
        fillcolor: 'rgba(79,140,255,.08)',
        hovertemplate: '%{theta}: %{r:.0f}<extra>início</extra>',
      });
    }
    draw('dashRadar', traces, {
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        radialaxis: {
          range: [0, 100],
          gridcolor: COLOR.grid,
          linecolor: COLOR.grid,
          tickfont: { size: 9, color: '#64748b' },
        },
        angularaxis: { gridcolor: COLOR.grid, linecolor: COLOR.grid, tickfont: { size: 9.5, color: COLOR.txt } },
      },
      showlegend: true,
      margin: { l: 30, r: 30, t: 20, b: 20 },
    });
  }

  function renderScatter() {
    const snap = DASH.snapshot;
    if (!snap || !(snap.ranking || []).length) {
      drawEmpty('dashScatter', 'Lista de produtos indisponível.');
      return;
    }
    const items = snap.ranking;
    draw('dashScatter', [{
      x: items.map((i) => i.pressure_score),
      y: items.map((i) => i.projected_brazil_30d_pct),
      text: items.map((i) => i.label),
      customdata: items.map((i) => i.key),
      type: 'scatter',
      mode: 'markers+text',
      textposition: 'top center',
      textfont: { size: 8.5, color: COLOR.txt },
      name: 'produtos',
      marker: {
        size: items.map((i) => 10 + i.pressure_score / 9),
        color: items.map((i) => i.projected_brazil_30d_pct),
        colorscale: [[0, COLOR.green], [0.5, COLOR.muted], [1, COLOR.red]],
        cmin: -2,
        cmax: 12,
        showscale: true,
        colorbar: {
          title: { text: 'estimativa 30d', font: { size: 9 } },
          thickness: 10,
          tickfont: { size: 9, color: '#64748b' },
          outlinewidth: 0,
        },
        line: { color: 'rgba(232,237,247,.25)', width: 1 },
      },
      hovertemplate: '<b>%{text}</b><br>pressão %{x:.0f}<br>Brasil %{y:+.1f}%<extra></extra>',
    }], {
      margin: { l: 52, r: 48, t: 16, b: 40 },
      xaxis: { title: { text: 'pressão (0-100)', font: { size: 10 } }, range: [0, 100] },
      yaxis: { title: { text: 'estimativa Brasil 30d (%)', font: { size: 10 } }, zerolinecolor: COLOR.zero },
      shapes: [
        {
          type: 'line', xref: 'paper', x0: 0.5, x1: 0.5, y0: 0, y1: 1,
          line: { color: '#475569', width: 1, dash: 'dot' },
        },
        {
          type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0,
          line: { color: '#475569', width: 1, dash: 'dot' },
        },
      ],
    });
    bindCategoryClick('dashScatter');
  }

  /* ---------------- interação ---------------- */

  function bindCategoryClick(id) {
    const el = d$(id);
    if (!el || el.dataset.bound === '1') return;
    el.dataset.bound = '1';
    el.on('plotly_click', (ev) => {
      const key = ev && ev.points && ev.points[0] && ev.points[0].customdata;
      if (key) selectCategory(key);
    });
  }

  async function selectCategory(key) {
    if (!key || key === DASH.category) return;
    DASH.category = key;
    const sel = d$('dashCategory');
    if (sel) sel.value = key;
    const token = ++DASH.token;
    try {
      await ensureCategory(key);
      if (token !== DASH.token) return;
      renderCategory();
      setStatus(`detalhe: ${(DASH.snapshot.ranking.find((i) => i.key === key) || {}).label || key}`);
    } catch (err) {
      setStatus(`falha ao abrir o detalhe: ${err.message}`, 'err');
    }
  }

  function bindRanges() {
    const box = d$('dashRanges');
    if (!box || box.dataset.bound === '1') return;
    box.dataset.bound = '1';
    box.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.seg-btn');
      if (!btn) return;
      DASH.range = btn.dataset.range;
      box.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.range === DASH.range));
      refresh();
    });
  }

  function bindCategorySelect() {
    const sel = d$('dashCategory');
    if (!sel || sel.dataset.bound === '1') return;
    sel.dataset.bound = '1';
    sel.addEventListener('change', () => {
      selectCategory(sel.value);
    });
  }

  function fillCategorySelect() {
    const sel = d$('dashCategory');
    if (!sel || !DASH.snapshot) return;
    const keys = DASH.snapshot.ranking.map((i) => i.key);
    const sig = keys.join(',');
    if (sel.dataset.signature !== sig) {
      sel.innerHTML = DASH.snapshot.ranking.map(
        (i) => `<option value="${dEsc(i.key)}">${dEsc(i.label)}</option>`,
      ).join('');
      sel.dataset.signature = sig;
    }
    if (!keys.includes(DASH.category)) DASH.category = keys[0] || null;
    if (DASH.category) sel.value = DASH.category;
  }

  /* ---------------- ciclo ---------------- */

  async function refresh() {
    if (!DASH.snapshot || !window.Plotly) return;
    const token = ++DASH.token;
    setStatus('carregando histórico…');
    try {
      await ensureData();
      if (token !== DASH.token || !DASH.active) return;
      renderKpis();
      fillCategorySelect();
      renderIndex();
      renderSupply();
      renderRanking();
      renderCategory();
      renderRadar();
      renderScatter();
      const meta = (DASH.core && DASH.core.__meta) || {};
      const count = (DASH.core ? Object.keys(DASH.core).filter((k) => k !== '__meta').length : 0)
        + (DASH.driverHist ? Object.keys(DASH.driverHist).filter((k) => k !== '__meta').length : 0);
      const bucket = meta.bucket_seconds
        ? `média a cada ${meta.bucket_seconds >= 86400
          ? `${Math.round(meta.bucket_seconds / 86400)}d`
          : meta.bucket_seconds >= 3600
            ? `${Math.round(meta.bucket_seconds / 3600)}h`
            : `${Math.round(meta.bucket_seconds / 60)}min`}`
        : 'média automática';
      setStatus(`período ${DASH.range} · ${bucket} · ${count} indicadores · sem inventar dados`);
      const note = d$('dashNote');
      if (note) {
        note.textContent =
          'Os gráficos usam os dados da última coleta. Quando falta um dado, a linha ' +
          'quebra; não preenchemos o buraco com zero.';
      }
      bindCategorySelect();
    } catch (err) {
      if (token !== DASH.token) return;
      DASH.error = err;
      setStatus(`falha ao carregar os gráficos: ${err.message}`, 'err');
      ['dashIndex', 'dashSupply', 'dashRanking', 'dashCategoryChart', 'dashRadar', 'dashScatter']
        .forEach((id) => drawEmpty(id, 'Não foi possível carregar o histórico agora.'));
    }
  }

  async function activate() {
    DASH.active = true;
    bindRanges();
    if (!DASH.snapshot) {
      setStatus('aguardando o primeiro snapshot…');
      return;
    }
    setStatus('carregando Plotly local…');
    try {
      await loadPlotly();
      if (!DASH.active) return;
      await refresh();
      // Se a janela mudou com a aba oculta, o Plotly guardou a largura antiga.
      resizeVisible();
    } catch (err) {
      setStatus(`Plotly indisponível: ${err.message}`, 'err');
      ['dashIndex', 'dashSupply', 'dashRanking', 'dashCategoryChart', 'dashRadar', 'dashScatter']
        .forEach((id) => drawEmpty(id, 'Plotly não carregou da cópia local.'));
    }
  }

  function resizeVisible() {
    if (!window.Plotly || !DASH.active) return;
    requestAnimationFrame(() => {
      document.querySelectorAll('#tab-dashboard .js-plotly-plot').forEach((el) => {
        window.Plotly.Plots.resize(el);
      });
    });
  }

  function onSnapshot(snap) {
    const changed = !DASH.snapshot || DASH.snapshot.generated_at !== snap.generated_at;
    DASH.snapshot = snap;
    if (changed) DASH.cache.clear();
    if (DASH.active) {
      if (window.Plotly) refresh();
      else activate();
    }
  }

  function deactivate() {
    DASH.active = false;
  }

  window.Dash = {
    activate,
    deactivate,
    onSnapshot,
    get snapshot() { return DASH.snapshot; },
    get range() { return DASH.range; },
  };
})();
