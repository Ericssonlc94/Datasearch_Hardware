/* DataSearch Hardware — gráficos Plotly, carregados sob demanda.
   Nenhuma dependência de CDN: Plotly vem de /static/vendor. O arquivo só é
   injetado quando a aba Gráficos é aberta pela primeira vez. O resumo
   (KPIs, radar e ranking) vem só do snapshot e não depende do período. A
   evolução (séries escolhidas e produto) é desenhada aqui com dados e
   estado do app.js. */

(function () {
  'use strict';

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
    loading: null,
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

  function xTickFormat(range) {
    if (range === '24h') return '%H:%M';
    return range === '1y' ? '%m/%y' : '%d/%m';
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

  /* ---------------- render: KPIs ---------------- */

  function renderKpis() {
    const snap = DASH.snapshot;
    if (!snap) return;
    // O painel-resumo fica acima do seletor de período e não depende dele:
    // tudo aqui vem do snapshot, nada do histórico.
    const sum = snap.summary || {};
    const iph = sum.iph ?? null;
    const iphBr = sum.iph_brazil ?? null;
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
        dEsc(sum.iph_label || 'índice global'),
        iph === null ? null : dColor(iph),
        '<span class="badge modeled">estimativa</span>',
      ),
      card(
        'Pressão no Brasil',
        iphBr === null ? '—' : dNum(iphBr, 1),
        'dólar + impostos',
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

  function renderRadar() {
    const snap = DASH.snapshot;
    if (!snap || !(snap.drivers || []).length) {
      drawEmpty('dashRadar', 'Vetores indisponíveis.');
      return;
    }
    const drivers = snap.drivers;
    const labels = drivers.map((d) => short(d.label.split(':')[0].split('—')[0].trim(), 18));
    const now = drivers.map((d) => d.score);
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
      showlegend: false,
      margin: { l: 30, r: 30, t: 20, b: 20 },
    });
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

  // O produto da evolução é estado do app.js: o clique só avisa.
  function selectCategory(key) {
    if (!key) return;
    window.dispatchEvent(new CustomEvent('dash:category', { detail: { key } }));
  }

  /* ---------------- ciclo ---------------- */

  function refresh() {
    if (!DASH.snapshot || !window.Plotly || !DASH.active) return;
    renderKpis();
    renderRadar();
    renderRanking();
    const when = new Date(DASH.snapshot.generated_at);
    setStatus(Number.isNaN(when.getTime())
      ? 'dados da última coleta'
      : `coleta de ${when.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`);
    const note = d$('dashNote');
    if (note) {
      note.textContent =
        'Os gráficos usam os dados da última coleta. Quando falta um dado, a linha ' +
        'quebra; não preenchemos o buraco com zero.';
    }
  }

  async function activate() {
    DASH.active = true;
    if (!DASH.snapshot) {
      setStatus('aguardando o primeiro snapshot…');
      return;
    }
    setStatus('carregando Plotly local…');
    try {
      await loadPlotly();
      if (!DASH.active) return;
      refresh();
      // Se a janela mudou com a aba oculta, o Plotly guardou a largura antiga.
      resizeVisible();
    } catch (err) {
      setStatus(`Plotly indisponível: ${err.message}`, 'err');
      ['dashRanking', 'dashRadar', 'trendChart', 'trendCatChart']
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

  /* ---------------- evolução (dados vêm do app.js) ---------------- */

  const DAY_MS = 86400000;

  // Sem null, a linha só quebra em salto bem maior que o passo normal
  // (fim de semana e série mensal não são lacuna). Com null, o próprio
  // null quebra. Até `rebuiltUntil` a série é recálculo diário e sai
  // tracejada, com a ponte para a medição ao vivo.
  function trendTraces(s, bucketSeconds) {
    const pts = (s.points || [])
      .map((p) => ({ t: p.t, ms: Date.parse(p.t), v: p.v === null || p.v === undefined ? null : Number(p.v) }))
      .filter((p) => Number.isFinite(p.ms))
      .sort((a, b) => a.ms - b.ms);
    if (!pts.length) return [];
    const hasNulls = pts.some((p) => p.v === null);
    const diffs = [];
    for (let i = 1; i < pts.length; i += 1) {
      const d = pts[i].ms - pts[i - 1].ms;
      if (d > 0) diffs.push(d);
    }
    diffs.sort((a, b) => a - b);
    const median = diffs.length ? diffs[diffs.length >> 1] : DAY_MS;
    const gapMs = hasNulls ? Infinity : Math.max(bucketSeconds ? bucketSeconds * 1800 : 0, median * 4);
    const rebuiltGap = Math.max(gapMs === Infinity ? 0 : gapMs, DAY_MS * 1.8);
    const rebuiltMs = s.rebuiltUntil ? Date.parse(s.rebuiltUntil) : NaN;
    const isRebuilt = (p) => Number.isFinite(rebuiltMs) && p.ms <= rebuiltMs;

    const old = [];
    const live = [];
    let prev = null;
    for (const p of pts) {
      const list = isRebuilt(p) ? old : live;
      const gap = isRebuilt(p) ? rebuiltGap : gapMs;
      if (prev && prev.v !== null && p.v !== null && list.length && p.ms - prev.ms > gap) {
        list.push({ t: prev.t, v: null });
      }
      if (!isRebuilt(p) && prev && isRebuilt(prev) && p.ms - prev.ms <= rebuiltGap) old.push(p);
      list.push(p);
      prev = p;
    }
    const name = dEsc(s.label);
    const unit = s.unit && s.unit !== '0-100' ? ` ${dEsc(s.unit)}` : '';
    const fmt = `%{y:.${s.decimals ?? 1}f}`;
    const trace = (list, extra) => ({
      x: list.map((p) => p.t),
      y: list.map((p) => p.v),
      type: 'scatter',
      mode: modeFor(list.filter((p) => p.v !== null)),
      name,
      legendgroup: s.key,
      connectgaps: false,
      line: { color: s.color, width: 2.2 },
      hovertemplate: `${fmt}${unit}<extra>${name}</extra>`,
      ...extra,
    });
    const out = [];
    if (old.length) {
      out.push(trace(old, {
        showlegend: false,
        line: { color: s.color, width: 1.6, dash: 'dash' },
        opacity: 0.8,
        hovertemplate: `${fmt}${unit}<extra>${name} · recalculado</extra>`,
      }));
    }
    if (live.length) out.push(trace(live, {}));
    return out;
  }

  // cfg: { series, bars, from, to, range, bucketSeconds, zoomToData,
  // showLegend, empty, yTitle, zeroLabel }. Barras vão no eixo da direita;
  // zeroLabel marca a linha de zero com um rótulo.
  async function drawTrend(id, cfg) {
    try {
      await loadPlotly();
    } catch (err) {
      const el = d$(id);
      if (el) el.innerHTML = `<p class="dash-error">Plotly não carregou da cópia local: ${dEsc(err.message)}</p>`;
      return;
    }
    const traces = (cfg.series || []).flatMap((s) => trendTraces(s, cfg.bucketSeconds));
    const bars = (cfg.bars || []).filter((b) => (b.points || []).length);
    bars.forEach((b) => traces.push({
      x: b.points.map((p) => p.t),
      y: b.points.map((p) => p.v),
      type: 'bar',
      name: dEsc(b.label),
      yaxis: 'y2',
      marker: { color: 'rgba(45,212,167,.45)' },
      hovertemplate: `%{y:+.2f}%<extra>${dEsc(b.label)}</extra>`,
    }));
    if (!traces.length) {
      drawEmpty(id, cfg.empty || 'Ainda não há histórico para mostrar.');
      return;
    }
    const stamps = traces.flatMap((t) => t.x.map((x) => Date.parse(x))).filter(Number.isFinite);
    let x0 = Date.parse(cfg.from);
    let x1 = Date.parse(cfg.to);
    // O período pedido manda no eixo; só "Tudo" e o gráfico por produto
    // acompanham o trecho com dados, para não espremer os pontos na borda.
    if (cfg.zoomToData && stamps.length) {
      const lo = Math.min(...stamps);
      const hi = Math.max(...stamps);
      const pad = hi > lo ? Math.max((hi - lo) * 0.05, 60000) : 30 * 60000;
      x0 = Number.isFinite(x0) ? Math.max(x0, lo - pad) : lo - pad;
      x1 = Number.isFinite(x1) ? Math.min(x1, hi + pad) : hi + pad;
      if (x1 <= x0) { x0 = lo - pad; x1 = hi + pad; }
    }
    const xaxis = { type: 'date', tickformat: xTickFormat(cfg.range), hoverformat: '%d/%m/%Y %H:%M' };
    if (Number.isFinite(x0) && Number.isFinite(x1) && x1 > x0) {
      xaxis.range = [new Date(x0).toISOString(), new Date(x1).toISOString()];
    }
    const extra = {
      showlegend: Boolean(cfg.showLegend),
      xaxis,
      yaxis: { title: { text: cfg.yTitle || '', font: { size: 10 } }, zerolinecolor: COLOR.zero },
    };
    if (bars.length) {
      extra.margin = { l: 52, r: 52, t: 30, b: 38 };
      extra.bargap = 0.55;
      extra.yaxis2 = {
        overlaying: 'y',
        side: 'right',
        showgrid: false,
        zerolinecolor: COLOR.zero,
        tickfont: { size: 10, color: '#64748b' },
        title: { text: 'inflação do mês (%)', font: { size: 10 } },
      };
    }
    if (cfg.zeroLabel) {
      extra.shapes = [{
        type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0,
        line: { color: '#475569', width: 1, dash: 'dot' },
      }];
      extra.annotations = [{
        xref: 'paper', x: 0.005, xanchor: 'left', y: 0, yref: 'y', yanchor: 'bottom',
        text: dEsc(cfg.zeroLabel), showarrow: false, font: { size: 10, color: '#64748b' },
      }];
    }
    if (!cfg.showLegend) extra.margin = { ...(extra.margin || {}), l: 54, r: bars.length ? 52 : 18, t: 16, b: 38 };
    draw(id, traces, extra);
  }

  // Radar e ranking trocam entre lado a lado e empilhados em 1200 px: o
  // Plotly precisa medir de novo a largura do cartão.
  if (window.matchMedia) {
    const wide = window.matchMedia('(min-width: 1200px)');
    const onChange = () => resizeVisible();
    if (wide.addEventListener) wide.addEventListener('change', onChange);
    else if (wide.addListener) wide.addListener(onChange);
  }

  function onSnapshot(snap) {
    const changed = !DASH.snapshot || DASH.snapshot.generated_at !== snap.generated_at;
    DASH.snapshot = snap;
    if (changed && DASH.active) {
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
    drawTrend,
    get snapshot() { return DASH.snapshot; },
  };
})();
