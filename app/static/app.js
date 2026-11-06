/* DataSearch Hardware — painel.
   Os gráficos pequenos usam SVG desenhado à mão, sem dependência externa.
   A aba Gráficos (que inclui a evolução) usa Plotly local, carregado sob
   demanda por dashboard.js; aqui ficam os dados, o estado e os textos. */

const REFRESH_MS = 15 * 60 * 1000;
const RANGES = ['all', '24h', '7d', '30d', '90d', '1y'];
const RANGE_MS = {
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
  '90d': 90 * 24 * 60 * 60 * 1000,
  '1y': 365 * 24 * 60 * 60 * 1000,
};
const RANGE_LABEL = {
  all: 'todo o histórico',
  '24h': '24 horas',
  '7d': '7 dias',
  '30d': '30 dias',
  '90d': '90 dias',
  '1y': '1 ano',
};

let snapshot = null;
let nextRefreshAt = null;
let countdownTimer = null;
let refreshTimer = null;
let progressTimer = null;
let progressMode = 'overlay';
let progressActive = false;
let loadInFlight = false;

/* ---------------- utilidades ---------------- */

const $ = (id) => document.getElementById(id);

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );

// Defesa extra além do esc(): só http(s) vira href; javascript:, data: etc. viram texto.
function safeUrl(raw) {
  try {
    const u = new URL(String(raw ?? ''));
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : null;
  } catch {
    return null;
  }
}

const categoryIcon = (name) =>
  window.Icons && typeof window.Icons.svg === 'function'
    ? window.Icons.svg(name)
    : '';

const fmtPct = (v, digits = 1) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;

const fmtNum = (v, digits = 2) =>
  v === null || v === undefined ? '—' : v.toLocaleString('pt-BR', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });

const fmtBRL = (v) =>
  v === null || v === undefined ? '—' :
  v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

const fmtUsdCompact = (v) => {
  if (v === null || v === undefined) return '—';
  if (Math.abs(v) >= 1e12) return `US$ ${fmtNum(v / 1e12, 2)} tri`;
  if (Math.abs(v) >= 1e9) return `US$ ${fmtNum(v / 1e9, 1)} bi`;
  if (Math.abs(v) >= 1e6) return `US$ ${fmtNum(v / 1e6, 1)} mi`;
  return `US$ ${fmtNum(v, 0)}`;
};

const dirClass = (v) => (v === null || v === undefined ? 'flat' : v > 0.05 ? 'up' : v < -0.05 ? 'down' : 'flat');

function scoreColor(score) {
  if (score >= 72) return '#ff5c5c';
  if (score >= 60) return '#ff9f43';
  if (score >= 53) return '#e6b450';
  if (score >= 47) return '#7c8aa5';
  if (score >= 40) return '#3ec5a0';
  return '#2dd4a7';
}

/* Tradução curta dos vetores para as abas de leitura simples. O texto técnico
   completo continua disponível em Detalhes, Preços e Gráficos. */
const PLAIN_DRIVER = {
  alocacao_chips: 'Mais capacidade vai para datacenter e IA, e sobra menos chip para o consumidor.',
  ormuz_helio: 'Risco no Estreito de Ormuz e na oferta de hélio pode encarecer insumos e transporte.',
  terras_raras: 'Restrições a terras raras e ímãs permanentes afetam componentes e motores.',
  commodities: 'Metais industriais e energia entram no custo de produção e de transporte.',
  logistica: 'Frete e custos de importação mais altos chegam ao preço final.',
  cambio_br: 'Dólar mais alto encarece o hardware importado, e o repasse é rápido.',
};

const PLAIN_DRIVER_LABEL = {
  alocacao_chips: 'Disputa por chips e memória',
  ormuz_helio: 'Energia e hélio',
  terras_raras: 'Terras raras e ímãs',
  commodities: 'Metais e energia',
  logistica: 'Frete e importação',
  cambio_br: 'Dólar',
};

const plainDriverLabel = (key, fallback = '') => PLAIN_DRIVER_LABEL[key] || fallback;

function simpleTrend(score) {
  if (score >= 60) return 'A tendência é de alta.';
  if (score >= 53) return 'O viés é de alta, mas ainda moderado.';
  if (score >= 47) return 'O cenário está equilibrado.';
  return 'A pressão está baixa; isso não significa queda automática.';
}

function firstSentence(text, max = 210) {
  const raw = String(text || '').replace(/\s+/g, ' ').trim();
  if (!raw) return '';
  // Só quebra quando a próxima frase começa com maiúscula: assim “p.p. do
  // projetado” e “US$ 691.0 bi” não viram fim de frase por engano.
  const sentence = raw.split(/(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])/)[0] || raw;
  return sentence.length > max
    ? `${sentence.slice(0, max - 1).trimEnd()}…`
    : sentence;
}

function durationLabel(ms) {
  const minutes = Math.max(1, ms / 60000);
  if (minutes < 120) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} dias`;
}

function fmtDateTimeShort(ms) {
  if (!Number.isFinite(ms)) return '—';
  return new Date(ms).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

function rangeLabel(range) {
  return RANGE_LABEL[range] || range;
}

// "nos últimos 7 dias", "nas últimas 24 horas"… — para frases sobre o
// período exibido, que é diferente do horizonte da estimativa (30 dias).
const RANGE_PHRASE = {
  all: 'em todo o histórico disponível',
  '24h': 'nas últimas 24 horas',
  '7d': 'nos últimos 7 dias',
  '30d': 'nos últimos 30 dias',
  '90d': 'nos últimos 90 dias',
  '1y': 'no último ano',
};

function rangePhrase(range) {
  return RANGE_PHRASE[range] || `em ${rangeLabel(range)}`;
}

function elapsedLabel(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return `${minutes} min${rest ? ` ${rest} s` : ''}`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

function setLoadingProgress(p) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(p?.percent) || 0)));
  const total = Math.max(0, Number(p?.total) || 0);
  const done = Math.max(0, Math.min(total || Infinity, Number(p?.completed) || 0));
  const stage = String(p?.stage || 'idle');

  $('loadingBar').style.width = `${pct}%`;
  $('loadingMeter').setAttribute('aria-valuenow', String(pct));
  $('loadingPct').textContent = `${pct}%`;

  const bits = [];
  if (total) bits.push(`${done} de ${total} buscas`);
  if (Number(p?.elapsed_seconds) >= 1) bits.push(elapsedLabel(p.elapsed_seconds));
  $('loadingCount').textContent = bits.length
    ? bits.join(' · ')
    : 'conectando às fontes…';

  const titles = {
    idle: 'Preparando a coleta…',
    collecting: 'Buscando dados públicos…',
    building: 'Organizando a leitura…',
    ready: 'Leitura pronta. Abrindo o painel…',
    error: 'A coleta não terminou.',
  };
  $('loadingTitle').textContent = titles[stage] || titles.collecting;
}

async function pollProgress() {
  try {
    const res = await fetch('/api/progress', { cache: 'no-store' });
    if (!res.ok || !progressActive) return;
    const p = await res.json();
    if (!progressActive) return;
    if (progressMode === 'inline' && snapshot) {
      const pct = Math.max(0, Math.min(100, Math.round(Number(p?.percent) || 0)));
      $('statusText').textContent = `atualizando… ${pct}%`;
      $('statusDot').className = 'dot warn';
      return;
    }
    if (!snapshot) setLoadingProgress(p);
  } catch {
    // A tela de carregamento não pode falhar por causa do endpoint auxiliar.
  }
}

function startProgressPolling(mode) {
  progressMode = mode;
  progressActive = true;
  if (progressTimer) return;
  pollProgress();
  progressTimer = setInterval(pollProgress, 1000);
}

function stopProgressPolling() {
  progressActive = false;
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

/* ---------------- gráficos SVG ---------------- */

function lineChart(svg, points, opts = {}) {
  const W = 640, H = 220, P = { t: 14, r: 14, b: 26, l: 52 };
  if (!points || points.length < 2) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="#64748b" font-size="13" text-anchor="middle">sem dados disponíveis</text>`;
    return;
  }
  const vals = points.map((p) => p.v);
  let min = Math.min(...vals), max = Math.max(...vals);
  const pad = (max - min) * 0.12 || Math.abs(max) * 0.05 || 1;
  min -= pad; max += pad;

  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const x = (i) => P.l + (i / (points.length - 1)) * iw;
  const y = (v) => P.t + ih - ((v - min) / (max - min)) * ih;

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(points.length - 1).toFixed(1)},${P.t + ih} L${P.l},${P.t + ih} Z`;
  const color = opts.color || '#4f8cff';

  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const gy = P.t + (ih * i) / 4;
    const gv = max - ((max - min) * i) / 4;
    grid += `<line x1="${P.l}" y1="${gy}" x2="${W - P.r}" y2="${gy}" stroke="#263149" stroke-width="1"/>`;
    grid += `<text x="${P.l - 8}" y="${gy + 4}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${gv.toFixed(opts.axisDecimals ?? opts.decimals ?? 2)}</text>`;
  }

  const ticks = [0, Math.floor(points.length / 2), points.length - 1]
    .map((i) => `<text x="${x(i)}" y="${H - 8}" fill="#64748b" font-size="10" text-anchor="middle" font-family="monospace">${esc(points[i].t)}</text>`)
    .join('');

  const last = points[points.length - 1];
  svg.innerHTML = `
    <defs><linearGradient id="g-${svg.id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity=".28"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}
    <path d="${area}" fill="url(#g-${svg.id})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="${x(points.length - 1)}" cy="${y(last.v)}" r="3.5" fill="${color}"/>
    ${ticks}`;
}

// Lista horizontal: o nome do item do IPCA aparece inteiro (quebra linha se
// precisar), e a barra é proporcional ao maior movimento do conjunto.
function renderIpcaList(list, items) {
  if (!items.length) {
    list.innerHTML = '<li class="muted">Sem dado oficial disponível neste ciclo.</li>';
    return;
  }
  const maxAbs = Math.max(...items.map((it) => Math.abs(it.v)), 0.1);
  list.innerHTML = items.map((it) => {
    const tone = it.v > 0 ? 'up' : it.v < 0 ? 'down' : 'flat';
    const width = Math.max(2, (Math.abs(it.v) / maxAbs) * 100);
    return `<li class="ipca-row">
      <span class="ipca-label">${esc(it.t)}</span>
      <span class="ipca-track" aria-hidden="true"><span class="ipca-fill ${tone}" style="width:${width.toFixed(1)}%"></span></span>
      <span class="ipca-value ${tone}">${fmtPct(it.v, 1)}</span>
    </li>`;
  }).join('');
}

function renderGauge(svg, score) {
  const W = 220, H = 132, cx = 110, cy = 112, r = 86;
  const polar = (deg) => {
    const rad = ((180 - deg) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
  };
  const arc = (from, to, color, width) => {
    const [x1, y1] = polar(from), [x2, y2] = polar(to);
    const large = to - from > 180 ? 1 : 0;
    return `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)}"
             fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round"/>`;
  };

  const deg = (score / 100) * 180;
  const [nx, ny] = polar(deg);

  svg.innerHTML = `
    ${arc(0, 180, '#1b2437', 15)}
    ${arc(0, 36, '#2dd4a7', 15)}
    ${arc(36, 72, '#7c8aa5', 15)}
    ${arc(72, 126, '#ff9f43', 15)}
    ${arc(126, 180, '#ff5c5c', 15)}
    <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"
          stroke="${scoreColor(score)}" stroke-width="3.5" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="7" fill="${scoreColor(score)}"/>
    <circle cx="${cx}" cy="${cy}" r="3" fill="#0b0f17"/>
    <text x="24" y="128" fill="#64748b" font-size="10" font-family="monospace">0</text>
    <text x="196" y="128" fill="#64748b" font-size="10" font-family="monospace">100</text>`;
}

/* ---------------- tendência: estado ---------------- */

const trendState = {
  range: 'all',
  rangeExplicit: false,
  visible: ['iph', 'iph_br'],
  known: ['iph', 'iph_br'],
  category: 'gpu',
  catalog: null,
  mainData: null,
  catData: null,
  ipcaData: null,
  lit: false,
};
const trendCache = new Map();
const trendColors = new Map();
let trendToken = 0;
const TREND_COLORS = [
  '#4f8cff', '#2dd4a7', '#ff9f43', '#ff5c5c',
  '#c084fc', '#38bdf8', '#f472b6', '#a3e635',
];

function colorFor(key) {
  if (!trendColors.has(key)) {
    trendColors.set(key, TREND_COLORS[trendColors.size % TREND_COLORS.length]);
  }
  return trendColors.get(key);
}

function seriesMeta(key) {
  const all = (trendState.catalog?.groups || []).flatMap((g) => g.series);
  return all.find((s) => s.key === key) || { key, label: key, unit: '' };
}

function visibleHistoryBounds() {
  const metas = trendState.visible.map(seriesMeta);
  const firsts = metas
    .map((s) => Date.parse(s.first_observation))
    .filter((v) => Number.isFinite(v));
  const lasts = metas
    .map((s) => Date.parse(s.last_observation))
    .filter((v) => Number.isFinite(v));
  if (!firsts.length || !lasts.length) return null;
  const first = Math.min(...firsts);
  const last = Math.max(...lasts);
  return { first, last, span: Math.max(0, last - first) };
}

function rangeAvailable(range, span) {
  if (range === 'all') return true;
  if (!Number.isFinite(span) || span <= 0) return false;
  return span >= (RANGE_MS[range] || 0) * 0.9;
}

function chooseDefaultRange() {
  const bounds = visibleHistoryBounds();
  if (trendState.rangeExplicit && rangeAvailable(trendState.range, bounds?.span)) {
    return;
  }
  // A leitura padrão é o último mês; com menos histórico, o maior período
  // que o banco cobre, e "Tudo" só quando nem 24 h existem.
  const preferred = ['30d', '7d', '24h'].find(
    (range) => bounds && rangeAvailable(range, bounds.span)
  );
  trendState.range = preferred || 'all';
}

function renderTrendHistory() {
  const el = $('trendHistory');
  if (!el) return;
  if (!trendState.catalog) {
    el.textContent = 'Lendo o histórico disponível…';
    return;
  }
  const bounds = visibleHistoryBounds();
  if (!bounds || !bounds.span) {
    el.textContent = 'Ainda não há histórico para as séries selecionadas.';
    return;
  }
  const visible = (trendState.catalog?.groups || [])
    .flatMap((g) => g.series)
    .filter((s) => trendState.visible.includes(s.key));
  const total = visible.reduce((acc, s) => acc + (s.points || 0), 0);
  const seriesSpans = visible
    .map((s) => {
      const first = Date.parse(s.first_observation);
      const last = Date.parse(s.last_observation);
      return Number.isFinite(first) && Number.isFinite(last)
        ? Math.max(0, last - first)
        : null;
    })
    .filter((value) => value !== null);
  const shortest = seriesSpans.length ? Math.min(...seriesSpans) : bounds.span;
  const spanText = shortest < bounds.span * 0.98
    ? `${durationLabel(bounds.span)} no total (${durationLabel(shortest)} na série mais curta)`
    : durationLabel(bounds.span);
  const missing = ['24h', '7d', '30d', '90d', '1y']
    .filter((range) => !rangeAvailable(range, bounds.span));
  const nextStep = missing.length
    ? `Períodos maiores são liberados automaticamente.`
    : 'Todos os períodos estão disponíveis.';
  el.textContent =
    `Histórico disponível: ${spanText} · ` +
    `de ${fmtDateTimeShort(bounds.first)} a ${fmtDateTimeShort(bounds.last)} · ` +
    `${total} ponto(s). ${nextStep}`;
}

function bucketLabel(seconds) {
  if (!seconds) return 'sem agrupamento';
  const m = seconds / 60;
  if (m < 60) return `${Math.round(m)} min`;
  const h = m / 60;
  return h < 24 ? `${h} h` : `${h / 24} d`;
}

function trendError(message) {
  const meta = $('trendMeta');
  if (meta) meta.textContent = `Falha ao carregar o histórico: ${message}`;
  const notice = $('trendNotice');
  if (notice) {
    notice.textContent = '';
    notice.classList.add('hidden');
  }
}

async function fetchHistory(range, keys) {
  if (!keys.length) return null;
  const cacheKey = `${range}|${keys.join(',')}`;
  if (trendCache.has(cacheKey)) return trendCache.get(cacheKey);
  const url = `/api/history?range=${encodeURIComponent(range)}` +
    `&series=${encodeURIComponent(keys.join(','))}&bucket=auto`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* corpo não-JSON */ }
    throw new Error(detail);
  }
  const data = await res.json();
  trendCache.set(cacheKey, data);
  return data;
}

/* ---------------- tendência: controles ---------------- */

function syncTrendControls() {
  const bounds = visibleHistoryBounds();
  const catalogLoaded = Boolean(trendState.catalog);
  document.querySelectorAll('#trendRanges .seg-btn').forEach((btn) => {
    const range = btn.dataset.range;
    // Antes do catálogo, não bloqueia nada. Depois dele, "Tudo" é a única
    // opção garantida; as demais só aparecem quando o banco cobre o período.
    const ok = !catalogLoaded ||
      (range === 'all' ? true : Boolean(bounds) && rangeAvailable(range, bounds.span));
    btn.classList.toggle('active', range === trendState.range);
    btn.disabled = !ok;
    btn.setAttribute('aria-disabled', String(!ok));
    btn.title = ok
      ? `Ver ${rangeLabel(range)}`
      : `Ainda não há ${rangeLabel(range)} de histórico`;
  });
  renderTrendHistory();
  const picker = $('trendSeriesPicker');
  if (picker) picker.value = '';
}

function buildSeriesPicker() {
  const picker = $('trendSeriesPicker');
  if (!picker || !trendState.catalog) return;
  const groups = (trendState.catalog.groups || []).filter(
    (g) => g.key === 'index' || g.key === 'driver'
  );
  picker.innerHTML = '<option value="">＋ selecionar…</option>' + groups.map((g) =>
    `<optgroup label="${esc(g.label)}">` + g.series.map((s) =>
      `<option value="${esc(s.key)}">${esc(s.label)}${s.points === 0 ? ' (sem histórico)' : ''}</option>`
    ).join('') + '</optgroup>'
  ).join('');
}

function populateTrendCategories() {
  const sel = $('trendCategory');
  if (!sel || !snapshot) return;
  const keys = snapshot.ranking.map((it) => it.key);
  const signature = keys.join(',');
  if (sel.dataset.signature !== signature) {
    sel.innerHTML = snapshot.ranking.map((it) =>
      `<option value="${esc(it.key)}">${esc(it.label)}</option>`
    ).join('');
    sel.dataset.signature = signature;
  }
  if (!keys.includes(trendState.category)) trendState.category = keys[0] || trendState.category;
  sel.value = trendState.category;
}

function renderLegend(container, items) {
  container.innerHTML = items.map((s) =>
    `<button class="legend-chip${s.on ? ' on' : ''}" data-key="${esc(s.key)}"
              aria-pressed="${s.on}" title="Mostrar/ocultar ${esc(s.label)}">
      <span class="swatch" style="background:${s.color}"></span>${esc(s.label)}
    </button>`
  ).join('');
}

/* ---------------- tendência: render ---------------- */

function renderTrendSummary(series, mainData) {
  const el = $('trendSummary');
  if (!el) return;
  const bits = [];
  for (const s of series) {
    const pts = (s.points || []).filter((p) => p.v !== null && p.v !== undefined);
    if (pts.length < 2) continue;
    const first = Number(pts[0].v);
    const last = Number(pts[pts.length - 1].v);
    if (!Number.isFinite(first) || !Number.isFinite(last)) continue;
    const unit = s.unit || '';
    const dec = unit === '%' ? 2 : 1;
    const delta = last - first;
    let change;
    if (unit === '%') {
      change = `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} p.p.`;
    } else if (unit === '0-100') {
      change = `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} ` +
        `ponto${Math.abs(delta) === 1 ? '' : 's'}`;
    } else if (Math.abs(first) > 1e-9) {
      change = `${delta >= 0 ? '+' : ''}${((delta / first) * 100).toFixed(1)}%`;
    } else {
      change = `${delta >= 0 ? '+' : ''}${fmtNum(delta, 2)} ${unit}`.trim();
    }
    bits.push(`${s.label}: ${fmtNum(first, dec)} → ${fmtNum(last, dec)} (${change})`);
  }
  const period = mainData.range === 'all'
    ? 'No histórico disponível'
    : `Em ${rangeLabel(mainData.range)}`;
  el.textContent = bits.length
    ? `${period}: ${bits.slice(0, 3).join(' · ')}.`
    : '';
}

// Pontos antes de `model_since` usam a conta antiga da série e não entram
// no gráfico: não são comparáveis com os seguintes.
function currentPoints(s) {
  const since = Date.parse(s.model_since);
  const pts = s.points || [];
  return Number.isFinite(since) ? pts.filter((p) => Date.parse(p.t) >= since) : pts;
}

function renderRebuiltNotice(series) {
  const notice = $('trendNotice');
  if (!notice) return;
  const until = series
    .map((s) => Date.parse(s.rebuiltUntil))
    .filter((ms) => Number.isFinite(ms));
  const parts = [];
  if (until.length) {
    const last = new Date(Math.max(...until)).toLocaleDateString('pt-BR', {
      day: '2-digit', month: '2-digit', timeZone: 'UTC',
    });
    parts.push(
      `Trecho tracejado: até ${last}, o índice foi recalculado dia a dia com as ` +
      'séries de mercado, câmbio e dados oficiais de cada data. Depois disso, a linha ' +
      'cheia é a medição ao vivo, a cada 15 minutos.'
    );
  }
  if (!parts.length) {
    notice.textContent = '';
    notice.classList.add('hidden');
    return;
  }
  notice.textContent = parts.join(' ');
  notice.classList.remove('hidden');
}

function drawTrend(id, cfg) {
  if (window.Dash) window.Dash.drawTrend(id, cfg);
}

function renderTrend() {
  const mainData = trendState.mainData;

  const labels = new Map(
    (mainData ? mainData.series : []).map((s) => [s.key, s.label])
  );
  const mainItems = trendState.known.map((key) => ({
    key,
    label: labels.get(key) || seriesMeta(key).label,
    color: colorFor(key),
    on: trendState.visible.includes(key),
  }));
  renderLegend($('trendLegend'), mainItems);

  if (mainData && mainData.series.length) {
    const series = mainData.series.map((s) => ({
      key: s.key,
      label: s.label,
      unit: s.unit,
      color: colorFor(s.key),
      points: currentPoints(s),
      rebuiltUntil: s.reconstructed_until,
      decimals: s.unit === '%' ? 2 : 1,
    }));
    drawTrend('trendChart', {
      series,
      from: mainData.from,
      to: mainData.to,
      range: mainData.range,
      bucketSeconds: mainData.bucket_seconds,
      zoomToData: mainData.range === 'all',
    });
    const total = series.reduce((acc, s) => acc + s.points.length, 0);
    const bucketText = mainData.raw
      ? 'cada ponto é uma coleta'
      : `média a cada ${bucketLabel(mainData.bucket_seconds)}`;
    $('trendMeta').textContent =
      `${bucketText} · ${total} ponto(s) · ` +
      `período: ${rangeLabel(mainData.range)} · sem inventar dados`;
    renderTrendSummary(series, mainData);
    renderRebuiltNotice(series);
  } else {
    drawTrend('trendChart', {
      series: [],
      empty: trendState.visible.length ? 'Carregando histórico…' : 'Nenhuma série selecionada.',
    });
    $('trendMeta').textContent = trendState.visible.length
      ? 'Carregando histórico…'
      : 'Nenhuma série selecionada.';
    const summary = $('trendSummary');
    if (summary) summary.textContent = '';
    const notice = $('trendNotice');
    if (notice) {
      notice.textContent = '';
      notice.classList.add('hidden');
    }
  }

  const catData = trendState.catData;
  if (catData) {
    const series = catData.series.map((s) => ({
      key: s.key,
      label: s.label.replace(/ — .*$/, ''),
      unit: s.unit,
      color: colorFor(s.key),
      points: currentPoints(s),
      rebuiltUntil: s.reconstructed_until,
      decimals: 2,
    }));
    // Só as duas estimativas no gráfico. O eixo acompanha o trecho com
    // estimativa; o IPCA mensal (anos de história) vai em texto ao lado.
    drawTrend('trendCatChart', {
      series,
      from: catData.from,
      to: catData.to,
      range: catData.range,
      bucketSeconds: catData.bucket_seconds,
      zoomToData: true,
      showLegend: true,
      yTitle: 'estimativa 30d (%)',
      zeroLabel: 'estável',
      empty: 'Ainda não há histórico deste produto.',
    });
    renderCatIpca(trendState.ipcaData);
    const zoomed = series.some((s) => s.points.length);
    renderCatTexts(series, catData, zoomed);
  }
}

// Último IPCA oficial do produto, em texto: a série mensal não entra no eixo.
function renderCatIpca(data) {
  const el = $('trendCatIpca');
  if (!el) return;
  const pts = ((data && data.series[0] && data.series[0].points) || [])
    .filter((p) => p.v !== null && p.v !== undefined);
  const last = pts[pts.length - 1];
  el.textContent = last
    ? `IBGE, último mês: ${fmtPct(Number(last.v), 2)}, mês ${String(last.t).slice(0, 7)}`
    : 'IBGE: sem inflação oficial para este produto.';
}

// Cada ponto do gráfico por produto é uma estimativa para os 30 dias
// seguintes; o período escolhido diz quanto tempo dessas estimativas aparece.
function renderCatTexts(series, catData, zoomed) {
  const lead = $('trendCatLead');
  if (lead) {
    lead.textContent =
      `Como a estimativa de preço para os 30 dias seguintes mudou ` +
      `${rangePhrase(catData.range)}, em dólar e no Brasil.`;
  }
  const meta = $('trendCatMeta');
  if (!meta) return;
  const bits = series.map((s) => {
    const pts = (s.points || []).filter((p) => p.v !== null && p.v !== undefined);
    if (pts.length < 2) return null;
    const first = Number(pts[0].v);
    const last = Number(pts[pts.length - 1].v);
    const delta = last - first;
    return `${s.label.replace(/ — .*$/, '')}: ${fmtPct(first, 2)} → ${fmtPct(last, 2)} ` +
      `(${delta >= 0 ? '+' : ''}${delta.toFixed(2)} p.p.)`;
  }).filter(Boolean);
  const period = rangePhrase(catData.range);
  const head = bits.length
    ? `${period.charAt(0).toUpperCase()}${period.slice(1)}: ${bits.join(' · ')}.`
    : `Ainda não há dois pontos ${period} para comparar.`;
  meta.textContent = zoomed
    ? `${head} O eixo mostra só o trecho com histórico.`
    : head;
}

async function refreshTrend() {
  const token = ++trendToken;
  try {
    const catKeys = [
      `cat.${trendState.category}.proj30_global`,
      `cat.${trendState.category}.proj30_br`,
    ];
    // O IPCA é mensal: busca o histórico inteiro para achar o último mês,
    // qualquer que seja o período escolhido.
    const ipcaKey = `obs.${trendState.category}.ipca`;
    const inCatalog = (trendState.catalog?.groups || []).some((g) => g.series.some((x) => x.key === ipcaKey));
    const [mainData, catData, ipcaData] = await Promise.all([
      fetchHistory(trendState.range, trendState.visible),
      fetchHistory(trendState.range, catKeys),
      inCatalog ? fetchHistory('all', [ipcaKey]) : null,
    ]);
    if (token !== trendToken) return; // uma troca de período mais nova venceu
    trendState.mainData = mainData;
    trendState.catData = catData;
    trendState.ipcaData = ipcaData;
    renderTrend();
  } catch (err) {
    if (token === trendToken) trendError(err.message);
  }
}

async function loadSeriesCatalog(force = false) {
  if (trendState.catalog && !force) return;
  const res = await fetch('/api/series', { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  trendState.catalog = await res.json();
  const known = new Set(
    (trendState.catalog.groups || []).flatMap((g) => g.series.map((s) => s.key))
  );
  trendState.visible = trendState.visible.filter((k) => known.has(k));
  trendState.known = trendState.known.filter((k) => known.has(k));
  if (!trendState.visible.length) trendState.visible = ['iph', 'iph_br'];
  if (!trendState.known.length) trendState.known = [...trendState.visible];
  buildSeriesPicker();
  chooseDefaultRange();
  syncTrendControls();
  if (activeTab === 'dashboard') syncTrendHash();
}

async function ensureTrendLoaded() {
  try {
    await loadSeriesCatalog();
    populateTrendCategories();
    trendState.lit = true;
    chooseDefaultRange();
    syncTrendControls();
    await refreshTrend();
  } catch (err) {
    trendError(err.message);
  }
}

/* ---------------- drill-down ---------------- */

function openSignal(key) {
  const seriesKey = `signal.${key}`;
  trendState.visible = [seriesKey];
  trendState.known = [seriesKey];
  trendState.range = 'all';
  trendState.rangeExplicit = true;
  syncTrendControls();
  activateTab('dashboard');
  const card = $('trendChart');
  if (card) card.scrollIntoView({ block: 'center' });
}

function toggleTrendSeries(key) {
  const has = trendState.visible.includes(key);
  trendState.visible = has
    ? trendState.visible.filter((k) => k !== key)
    : [...trendState.visible, key];
  if (!trendState.known.includes(key)) trendState.known = [...trendState.known, key];
  chooseDefaultRange();
  syncTrendControls();
  syncTrendHash();
  refreshTrend();
}

function syncTrendHash() {
  history.replaceState(null, '', '#' + buildHash('dashboard'));
}

/* ---------------- abas e URL ---------------- */

let activeTab = 'visao-geral';
// Sub-aba de Preços: 'produtos' (padrão) ou 'mercado'; vai no hash como ?view=mercado.
let priceView = 'produtos';
const PRICE_VIEWS = ['produtos', 'mercado'];
// Link antigo da Fila (#fila ou #dashboard?view=fila): ao abrir Gráficos,
// rola até a seção Consumidor vs Datacenter.
let scrollToSupply = false;

// Links antigos: "entenda" e "tecnico" caem na Visão Geral; "tendencia"
// (Evolução) e "fila" foram juntadas à aba Gráficos.
const TAB_ALIASES = {
  entenda: 'visao-geral',
  tendencia: 'dashboard',
  fila: 'dashboard',
  tecnico: 'visao-geral', // aba removida na T38
};
const normalizeTab = (name) => TAB_ALIASES[name] || name;

function buildHash(tab) {
  if (tab === 'ranking') return priceView === 'mercado' ? 'ranking?view=mercado' : 'ranking';
  if (tab !== 'dashboard') return tab;
  const p = new URLSearchParams();
  p.set('range', trendState.range);
  if (trendState.visible.length) p.set('series', trendState.visible.join(','));
  p.set('cat', trendState.category);
  return `dashboard?${p.toString()}`;
}

function parseHash() {
  const raw = location.hash.replace(/^#/, '');
  const [tab, query] = raw.split('?');
  const params = new URLSearchParams(query || '');
  // Link antigo da aba Fila: abre Gráficos na seção Consumidor vs Datacenter.
  if (tab === 'fila') params.set('view', 'fila');
  return { tab: normalizeTab(tab || 'visao-geral'), params };
}

function applyPriceParams(params) {
  const view = params.get('view');
  priceView = PRICE_VIEWS.includes(view) ? view : 'produtos';
}

function setPriceView(view, { syncHash = true } = {}) {
  priceView = PRICE_VIEWS.includes(view) ? view : 'produtos';
  document.querySelectorAll('.price-views .seg-btn').forEach((b) => {
    const on = b.dataset.view === priceView;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll('.price-view').forEach((p) => {
    p.classList.toggle('hidden', p.id !== `pv-${priceView}`);
  });
  if (syncHash && activeTab === 'ranking') {
    history.replaceState(null, '', '#' + buildHash('ranking'));
  }
}

function applyChartParams(params) {
  scrollToSupply = params.get('view') === 'fila';
}

function applyTrendParams(params) {
  const range = params.get('range');
  if (range && RANGES.includes(range)) {
    trendState.range = range;
    trendState.rangeExplicit = true;
  }
  const series = params.get('series');
  if (series) {
    trendState.visible = series.split(',').map((s) => s.trim()).filter(Boolean);
    trendState.known = [...trendState.visible];
  }
  const cat = params.get('cat');
  if (cat) trendState.category = cat;
}

function activateTab(name, { syncHash = true } = {}) {
  const requested = normalizeTab(name);
  const target = document.querySelector(`[data-tab="${requested}"]`) ? requested : 'visao-geral';
  activeTab = target;
  document.querySelectorAll('.tab').forEach((t) => {
    const on = t.dataset.tab === target;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll('.tabpanel').forEach((p) => {
    p.classList.toggle('hidden', p.id !== `tab-${target}`);
  });

  if (target === 'dashboard') {
    ensureTrendLoaded();
    if (scrollToSupply) {
      scrollToSupply = false;
      const section = $('consumidorDatacenter');
      if (section) requestAnimationFrame(() => section.scrollIntoView({ block: 'start' }));
    }
  }
  if (window.Prices) {
    if (target === 'ranking') {
      setPriceView(priceView, { syncHash: false });
      window.Prices.activate();
    } else window.Prices.deactivate();
  }
  if (window.Dash) {
    if (target === 'dashboard') window.Dash.activate();
    else window.Dash.deactivate();
  }
  if (syncHash) {
    const next = '#' + buildHash(target);
    if (location.hash !== next) location.hash = next;
  }
}

// Padrão ARIA de abas: ← → circulam, Home/End vão às pontas, e a aba focada
// já é ativada (só a ativa fica no Tab da página: tabindex móvel). Serve à
// barra principal e às sub-abas de Preços.
function bindTabKeys(list, activate) {
  list.addEventListener('keydown', (ev) => {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(ev.target);
    if (i < 0) return;
    let next = null;
    if (ev.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
    else if (ev.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
    else if (ev.key === 'Home') next = tabs[0];
    else if (ev.key === 'End') next = tabs[tabs.length - 1];
    if (!next) return;
    ev.preventDefault();
    activate(next);
    next.focus();
    next.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  });
}

function bindTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      activateTab(tab.dataset.tab);
      // Troca de aba pelo clique começa no topo; deep links (#fila) rolam
      // até a seção no próprio activateTab.
      window.scrollTo(0, 0);
    });
  });
  bindTabKeys(document.querySelector('.tabs'), (b) => activateTab(b.dataset.tab));
  const views = document.querySelector('.price-views');
  if (views) {
    views.addEventListener('click', (ev) => {
      const b = ev.target.closest('.seg-btn');
      if (b) setPriceView(b.dataset.view);
    });
    bindTabKeys(views, (b) => setPriceView(b.dataset.view));
  }
  window.addEventListener('hashchange', () => {
    const { tab, params } = parseHash();
    applyTrendParams(params);
    applyPriceParams(params);
    applyChartParams(params);
    syncTrendControls();
    activateTab(tab, { syncHash: false });
  });
}

/* ---------------- render ---------------- */

/* ---------------- notícias: 5 por página, até 3 páginas ---------------- */

const HEADLINES_PER_PAGE = 5;
const HEADLINES_MAX_PAGES = 3;
let headlineItems = [];
let headlinePage = 0;

function headlineHtml(h) {
  const n = Number(h.corroboration || 0);
  const badge = n >= 2
    ? `<span class="badge observed" title="A mesma história apareceu em ${n} domínios distintos neste recorte de 7 dias.">corroborada · ${n} veículos</span>`
    : `<span class="badge stale" title="Nenhum segundo veículo cobriu esta matéria no recorte. Fonte única não significa falsa — significa sem segunda checagem.">fonte única</span>`;
  const others = (h.sources || []).filter((s) => s && s !== h.domain).slice(0, 3);
  const meta = [h.domain || '', h.country || '', h.seen_at ? h.seen_at.slice(0, 16).replace('T', ' ') : '']
    .filter(Boolean).map(esc).join(' · ');
  const kind = h.kind === 'analysis'
    ? '<span class="badge modeled" title="Artigo de análise: interpreta o cenário em vez de noticiar um fato do dia.">análise</span> '
    : '';
  const href = safeUrl(h.url);
  const title = esc(h.title || h.url);
  const link = href
    ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${title}</a>`
    : `<span class="headline-text">${title}</span>`;
  return `<li>
    ${link}
    <div class="meta">${kind}${meta} ${badge}${others.length ? ' · também em ' + others.map(esc).join(', ') : ''}</div>
  </li>`;
}

function headlinePageCount() {
  return Math.min(
    HEADLINES_MAX_PAGES,
    Math.ceil(headlineItems.length / HEADLINES_PER_PAGE)
  );
}

function renderHeadlinePage() {
  const list = $('headlines');
  const pager = $('headlinesPager');
  const pages = headlinePageCount();
  if (!pages) {
    list.innerHTML = '<li class="muted">Nenhuma notícia recente ligada a preço ou oferta de hardware passou pelo filtro nesta rodada. As fontes podem estar temporariamente indisponíveis.</li>';
    pager.innerHTML = '';
    pager.classList.add('hidden');
    return;
  }
  headlinePage = Math.max(0, Math.min(headlinePage, pages - 1));
  const start = headlinePage * HEADLINES_PER_PAGE;
  list.innerHTML = headlineItems
    .slice(start, start + HEADLINES_PER_PAGE)
    .map(headlineHtml)
    .join('');
  if (pages < 2) {
    pager.innerHTML = '';
    pager.classList.add('hidden');
    return;
  }
  const buttons = Array.from({ length: pages }, (_, i) => `
    <button type="button" class="pager-btn${i === headlinePage ? ' active' : ''}"
      data-page="${i}" aria-label="Página ${i + 1} de ${pages}"
      ${i === headlinePage ? 'aria-current="page"' : ''}>${i + 1}</button>`).join('');
  pager.innerHTML = `
    <button type="button" class="pager-btn" data-page="${headlinePage - 1}"
      aria-label="Página anterior" ${headlinePage === 0 ? 'disabled' : ''}>‹</button>
    ${buttons}
    <button type="button" class="pager-btn" data-page="${headlinePage + 1}"
      aria-label="Próxima página" ${headlinePage === pages - 1 ? 'disabled' : ''}>›</button>`;
  pager.classList.remove('hidden');
}

function renderHeadlines(list) {
  // O filtro (relevância para preço, idioma, release/agregador, dedup,
  // corroboração e variedade de veículos) roda na coleta.
  headlineItems = list.slice(0, HEADLINES_PER_PAGE * HEADLINES_MAX_PAGES);
  renderHeadlinePage();
}

function bindHeadlinePager() {
  const pager = $('headlinesPager');
  if (!pager) return;
  pager.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.pager-btn');
    if (!btn || btn.disabled) return;
    const page = Number(btn.dataset.page);
    if (!Number.isInteger(page) || page === headlinePage) return;
    headlinePage = page;
    renderHeadlinePage();
    // Os botões são redesenhados: o foco volta para a página ativa.
    pager.querySelector('.pager-btn.active')?.focus();
  });
}

function renderOverview(d) {
  // Termômetro simples do índice total (T40), sem rodapé.
  const iph = Number(d.summary.iph) || 0;
  $('iphValue').textContent = iph.toFixed(0);
  $('iphValue').style.color = scoreColor(iph);
  $('iphLabel').textContent = 'Pressão sobre o preço (0 a 100)';
  $('iphMarker').style.left = `${Math.max(0, Math.min(100, iph))}%`;

  const b = d.brazil;
  $('kpis').innerHTML = `
    <div class="kpi">
      <div class="kpi-label">Pressão no Brasil <span class="badge modeled">estimativa</span></div>
      <div class="kpi-value" style="color:${scoreColor(d.summary.iph_brazil)}">${d.summary.iph_brazil.toFixed(1)}</div>
      <div class="kpi-sub">com dólar e impostos de importação</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Dólar <span class="badge observed">oficial</span></div>
      <div class="kpi-value">${b.usd_brl ? 'R$ ' + fmtNum(b.usd_brl, 4) : '—'}</div>
      <div class="kpi-sub ${dirClass(b.usd_brl_change_30d_pct)}">${fmtPct(b.usd_brl_change_30d_pct)} em 30 dias</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Inflação em 12 meses <span class="badge observed">oficial</span></div>
      <div class="kpi-value">${fmtPct(b.ipca_12m, 2)}</div>
      <div class="kpi-sub">Selic ${b.selic ? b.selic.toFixed(2) + '%' : '—'} · IGP-M ${fmtPct(b.igpm_12m, 2)}</div>
    </div>
`;

  // Drivers — cada sinal é um atalho para a série dele na aba Evolução.
  // Exibição do maior para o menor score; sort é estável, então empate mantém a
  // ordem do servidor. d.drivers fica intacto para os outros usos.
  const driversByScore = [...d.drivers].sort((a, b2) => b2.score - a.score);
  $('drivers').innerHTML = driversByScore.map((dr) => {
    const color = scoreColor(dr.score);
    const signalList = dr.signals || [];
    const signals = signalList.map((s) => {
      const cls = s.status === 'unavailable' ? 'flat' : dirClass(s.change_pct);
      const val = s.status === 'unavailable' ? 'indisp.' : fmtPct(s.change_pct);
      return `<div class="signal" role="button" tabindex="0" data-signal="${esc(s.key)}"
                   title="Ver o histórico de ${esc(s.label)} (${esc(s.source_key)})">
        <span class="signal-name">${esc(s.label)}</span>
        <span class="signal-chg ${cls}">${val}</span>
        <span class="signal-score">${s.score !== null ? s.score.toFixed(0) : '—'}</span>
      </div>`;
    }).join('');
    const more = signalList.length
      ? `<details class="driver-more">
          <summary>Ver sinais e fontes (${signalList.length})</summary>
          <div class="signals">${signals}</div>
          <p class="muted small">Clique em um sinal para abrir a série correspondente na aba Evolução.</p>
        </details>`
      : '';
    return `<article class="driver">
      <div class="driver-head">
        <h3>${esc(dr.label)}</h3>
        <span class="driver-score" style="color:${color}">${dr.score.toFixed(0)}</span>
      </div>
      <div class="meter">
        <div class="meter-fill" style="width:${dr.score}%;background:${color}"></div>
        <div class="meter-mid"></div>
      </div>
      <div class="meter-scale"><span>alívio</span><span>neutro 50</span><span>pressão</span></div>
      <p class="thesis">${esc(dr.thesis)}</p>
      <div class="coverage" title="Peso deste driver no índice e parcela dos sinais com dado disponível no ciclo.">Peso no índice ${(dr.weight * 100).toFixed(0)}% · cobertura ${(dr.coverage * 100).toFixed(0)}%</div>
      ${more}
    </article>`;
  }).join('');

  // IPCA 12m por subitem, deduplicado.
  const seen = new Set();
  const bars = [];
  for (const item of d.ranking) {
    const o = item.observed_br;
    if (!o || o.var_12m_pct === null || o.var_12m_pct === undefined) continue;
    if (seen.has(o.subitem_code)) continue;
    seen.add(o.subitem_code);
    bars.push({ t: o.subitem_label, v: o.var_12m_pct });
  }
  bars.sort((a, b2) => b2.v - a.v);
  renderIpcaList($('ipcaBars'), bars);

  renderHeadlines(d.headlines || []);
}

// Oferta por frente (§T24c): dias de estoque na memória e nos chips, % a/a na
// demanda. Formato "N dias · o normal é X a Y", sem tooltip. Até o domínio
// ligar as frentes, cada card diz que não há dado.
// T36: só a frente de demanda aparece; memória e lógica saíram dos cards.
const FRONT_CARDS = [
  { key: 'demanda', label: 'Demanda (capex + TSMC)' },
];

function frontNumber(v, unit) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  return unit === 'dias' ? `${fmtNum(Number(v), 0)} dias` : `${fmtPct(Number(v))} a/a`;
}

function frontCards(d) {
  const byKey = new Map((d.supply_fronts || []).map((f) => [f.key, f]));
  return FRONT_CARDS.map((card) => {
    const f = byKey.get(card.key);
    const ok = f && f.status !== 'unavailable' && f.value !== null && f.value !== undefined;
    const value = ok ? frontNumber(f.value, f.unit) : '—';
    const range = ok && Array.isArray(f.normal) && f.normal.length === 2
      ? `o normal é ${frontNumber(f.normal[0], f.unit)} a ${frontNumber(f.normal[1], f.unit)}`
        .replace(/ dias a /, ' a ').replace(/ a\/a a /, ' a ')
      : '';
    const note = ok
      ? [range, f.period ? `ref. ${f.period}` : ''].filter(Boolean).join(' · ')
      : 'sem dado nesta rodada';
    return { ...card, value, note, stale: ok && f.status === 'stale' };
  });
}

// Consumidor vs Datacenter (aba Gráficos): só os dois gráficos oficiais
// que ficaram da antiga aba Fila.
function renderQueue(d) {
  const s = d.supply || {};
  const capex = (s.capex_series || []).map((p) => ({ t: p.t, v: p.v / 1e9 }));
  lineChart($('capexChart'), capex, {
    color: '#ff9f43', decimals: 0, axisDecimals: 0,
  });
  lineChart($('inventoryChart'), s.inventory_series || [], {
    color: '#2dd4a7', decimals: 2, axisDecimals: 2,
  });
}

/* ---------------- fontes ---------------- */

// Mesmos selos do resto do painel; o status nunca vai direto para o HTML.
const SOURCE_STATUS = {
  ok: { text: 'ok', cls: 'ok' },
  stale: { text: 'desatualizada', cls: 'stale' },
  unavailable: { text: 'indisponível', cls: 'unavailable' },
  disabled: { text: 'desligada', cls: 'neutral' },
};

function fmtSourceDate(raw, withTime) {
  const d = raw ? new Date(raw) : null;
  if (!d || Number.isNaN(d.getTime())) return '—';
  return withTime
    ? d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('pt-BR');
}

function sourceItemHtml(s) {
  const href = safeUrl(s.url);
  const name = href
    ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(s.label)}</a>`
    : esc(s.label);
  const st = SOURCE_STATUS[s.status] || SOURCE_STATUS.unavailable;
  return `<li class="src-item">
      <div class="src-item-head"><span class="src-name">${name}</span>
        <span class="badge ${st.cls}">${esc(st.text)}</span></div>
      <div class="src-dates">referência ${esc(fmtSourceDate(s.as_of, false))} · última coleta ${esc(fmtSourceDate(s.fetched_at, true))}</div>
      ${s.note ? `<div class="src-note">${esc(s.note)}</div>` : ''}
    </li>`;
}

// Aba Fontes: snap.sources agrupado por provedor, na ordem em que aparecem.
function renderSources(d) {
  const el = $('sourceGroups');
  if (!el) return;
  const groups = new Map();
  for (const s of d.sources || []) {
    const key = s.provider || 'Outros';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }
  el.innerHTML = groups.size
    ? [...groups].map(([provider, list]) => `<section class="src-group">
        <h3>${esc(provider)}</h3>
        <ul class="src-list">${list.map(sourceItemHtml).join('')}</ul>
      </section>`).join('')
    : '<p class="muted">Nenhuma fonte nesta coleta.</p>';
}

function renderRanking(d) {
  const items = [...(d.ranking || [])].sort(
    (a, b) => (Number(b.projected_brazil_30d_pct) || 0) -
      (Number(a.projected_brazil_30d_pct) || 0)
  );
  const summary = $('rankingSummary');
  if (summary) {
    if (!items.length) {
      summary.textContent = 'Sem estimativa disponível neste ciclo.';
    } else {
      const first = items[0];
      const last = items[items.length - 1];
      const topDriver = (first.top_drivers || [])[0];
      const driverText = topDriver
        ? ` O que mais pesa em ${esc(first.label)}: ` +
          `<strong>${esc(plainDriverLabel(topDriver.driver_key, topDriver.driver_label))}</strong>.`
        : '';
      summary.innerHTML =
        `<span class="ranking-kicker">Maior estimativa</span> ` +
        `<strong>${esc(first.label)} ${fmtPct(first.projected_brazil_30d_pct)}</strong>` +
        (items.length > 1
          ? `<span class="ranking-sep">·</span>` +
            `<span class="ranking-kicker">Menor estimativa</span> ` +
            `<strong>${esc(last.label)} ${fmtPct(last.projected_brazil_30d_pct)}</strong>`
          : '') +
        driverText;
    }
  }

  const maxAbs = Math.max(
    1,
    ...items.map((it) => Math.abs(Number(it.projected_brazil_30d_pct) || 0))
  );

  $('priceRanking').innerHTML = items.map((it, index) => {
    const o = it.observed_br;
    const im = it.imports;
    const drivers = it.top_drivers || [];
    const top = drivers[0];
    const pct = Number(it.projected_brazil_30d_pct) || 0;
    const width = Math.max(3, Math.min(100, (Math.abs(pct) / maxAbs) * 100));
    const why = top
      ? `O que mais pesa: <strong>${esc(plainDriverLabel(top.driver_key, top.driver_label))}</strong>.`
      : '';
    const chips = drivers.slice(0, 4).map((c) =>
      `<span class="chip">${esc(c.driver_label)} <b>${fmtPct(c.contribution_pct, 1)}</b></span>`
    ).join('');
    const detailRows = drivers.map((c) => `<tr>
        <td>${esc(c.driver_label)}</td>
        <td class="mono">${fmtNum(c.beta, 3)}</td>
        <td class="mono ${dirClass(c.contribution_pct)}">${fmtPct(c.contribution_pct, 2)}</td>
      </tr>`).join('');

    const tax = Number(it.tax_multiplier);
    return `<details class="rank-item" id="rank-${esc(it.key)}">
      <summary class="rank-row">
        <span class="rank-num">${String(index + 1).padStart(2, '0')}</span>
        <span class="rank-main">
          <span class="rank-title">
            <span class="rank-icon" aria-hidden="true">${categoryIcon(it.icon)}</span>
            <span class="rank-name">${esc(it.label)}</span>
          </span>
          <span class="rank-why">${why}</span>
        </span>
        <span class="rank-value ${dirClass(pct)}">
          <span class="rank-value-num">${fmtPct(pct)}</span>
          <span class="rank-value-label">Brasil · 30 dias</span>
          <span class="rank-bar" aria-hidden="true"><span style="width:${width}%"></span></span>
        </span>
        <span class="rank-stat rank-stat-pressure">
          <span class="rank-stat-label">Pressão</span>
          <span class="rank-stat-value" style="color:${scoreColor(Number(it.pressure_score) || 0)}">
            ${(Number(it.pressure_score) || 0).toFixed(0)}/100
          </span>
        </span>
        <span class="rank-stat rank-stat-ipca">
          <span class="rank-stat-label">IPCA 12m</span>
          <span class="rank-stat-value ${dirClass(o && o.var_12m_pct)}">
            ${o ? fmtPct(o.var_12m_pct, 2) : '—'}
          </span>
        </span>
        <span class="rank-chevron" aria-hidden="true">⌄</span>
      </summary>

      <div class="rank-detail-body">
        <p class="narrative">${esc(it.narrative)}</p>

        <div class="rank-metrics">
          <div class="metric">
            <div class="metric-label">Estimativa em dólar · 30d</div>
            <div class="metric-value ${dirClass(it.projected_global_30d_pct)}">${fmtPct(it.projected_global_30d_pct)}</div>
            <div class="metric-note">sem câmbio e sem impostos</div>
          </div>
          <div class="metric">
            <div class="metric-label">Inflação oficial · 12m <span class="badge observed">oficial</span></div>
            <div class="metric-value ${dirClass(o && o.var_12m_pct)}">${o ? fmtPct(o.var_12m_pct, 2) : '—'}</div>
            <div class="metric-note">${o && o.subitem_label !== '—' ? esc(o.subitem_label) + (o.period ? ' · ' + esc(o.period) : '') : 'sem item oficial'}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Preço de importação · US$/kg <span class="badge observed">oficial</span></div>
            <div class="metric-value">${im && im.usd_per_kg ? fmtNum(im.usd_per_kg) : '—'}</div>
            <div class="metric-note">${im && im.usd_per_kg_change_12m_pct !== null && im.usd_per_kg_change_12m_pct !== undefined
              ? fmtPct(im.usd_per_kg_change_12m_pct) + ' em 12m · ' + esc(im.ncm_label)
              : (im ? esc(im.ncm_label) + ' · ' + esc(im.status) : '—')}${im ? ' · ' + esc(im.source || 'importação oficial') : ''}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Custo por US$100</div>
            <div class="metric-value">${fmtBRL(it.brl_impact_per_100usd)}</div>
            <div class="metric-note">câmbio + impostos (${Number.isFinite(tax) ? tax.toFixed(2) : '—'}×)</div>
          </div>
        </div>

        <div class="contrib">${chips}</div>
        <table class="detail-table">
          <thead><tr><th>Fator</th><th>Peso</th><th>Efeito</th></tr></thead>
          <tbody>${detailRows}</tbody>
        </table>
        <p class="tax-note">${esc(it.tax_note)}</p>
      </div>
    </details>`;
  }).join('');
}

function renderSimple(d) {
  const s = d.summary || {};
  const b = d.brazil || {};
  const sup = d.supply || {};
  const score = Number(s.iph) || 0;
  const color = scoreColor(score);

  // Medidor semicircular (T40: veio de Detalhes).
  renderGauge($('simpleGauge'), score);
  $('simpleScore').textContent = score.toFixed(1);
  $('simpleScore').style.color = color;
  $('simpleScoreLabel').textContent = s.iph_label || 'Pressão sobre o preço de hardware';

  const rankedDrivers = [...(d.drivers || [])].sort(
    (a, b2) => (b2.score * b2.weight) - (a.score * a.weight)
  );
  const top = rankedDrivers[0];
  const topText = top
    ? ` O fator que mais pesa hoje é <strong>${esc(plainDriverLabel(top.key, top.label))}</strong> (${Number(top.score).toFixed(0)}/100).`
    : '';
  $('simpleLead').innerHTML =
    `O termômetro marca <strong>${score.toFixed(0)}/100</strong> — ` +
    `${esc((s.iph_label || 'sem leitura').toLowerCase())}. ` +
    `${esc(simpleTrend(score))} ` +
    'Quanto maior a nota, mais forte é a pressão sobre o preço de hardware.' + topText;


  $('simpleReasons').innerHTML = rankedDrivers.slice(0, 3).map((dr, i) => {
    const ds = Number(dr.score) || 0;
    const plain = PLAIN_DRIVER[dr.key] || firstSentence(dr.thesis);
    return `<div class="reason">
      <div class="reason-head">
        <span class="reason-num">${i + 1}</span>
        <strong>${esc(plainDriverLabel(dr.key, dr.label))}</strong>
        <span class="reason-score" style="color:${scoreColor(ds)}">${ds.toFixed(0)}/100</span>
      </div>
      <div class="mini-meter" aria-hidden="true"><span style="width:${Math.max(2, Math.min(100, ds))}%;background:${scoreColor(ds)}"></span></div>
      <p>${esc(plain)}</p>
    </div>`;
  }).join('') || '<p class="muted small">Sem dados suficientes neste ciclo.</p>';

  const cats = [...(d.ranking || [])]
    .sort((a, b2) => (b2.projected_brazil_30d_pct || 0) - (a.projected_brazil_30d_pct || 0))
    .slice(0, 3);
  $('simpleCategories').innerHTML = cats.map((it) => {
    const pct = Number(it.projected_brazil_30d_pct);
    const ps = Number(it.pressure_score) || 0;
    const tone = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    const topDriver = (it.top_drivers || [])[0];
    const why = topDriver
      ? `O que mais pesa: ${plainDriverLabel(topDriver.driver_key, topDriver.driver_label)}.`
      : firstSentence(it.narrative, 190);
    return `<div class="simple-cat">
      <div class="simple-cat-head">
        <span class="simple-cat-icon" aria-hidden="true">${categoryIcon(it.icon)}</span>
        <strong>${esc(it.label)}</strong>
        <span class="simple-cat-pct ${tone}">${fmtPct(pct)}</span>
      </div>
      <div class="mini-meter" aria-hidden="true"><span style="width:${Math.max(2, Math.min(100, ps))}%;background:${scoreColor(ps)}"></span></div>
      <p>${esc(why)}</p>
      <span class="muted small">pressão ${ps.toFixed(0)}/100 · estimativa para 30 dias</span>
    </div>`;
  }).join('') || '<p class="muted small">Sem estimativa disponível neste ciclo.</p>';

  const watch = [
    {
      label: 'Dólar',
      value: b.usd_brl != null ? `R$ ${fmtNum(b.usd_brl, 2)}` : '—',
      note: `${fmtPct(b.usd_brl_change_30d_pct)} em 30 dias`,
      tone: (b.usd_brl_change_30d_pct || 0) > 0 ? 'up' : 'down',
    },
    ...frontCards(d).map((f) => ({ label: f.label, value: f.value, note: f.note, tone: 'flat' })),
    {
      label: 'Fila do consumidor',
      value: sup.queue_pressure != null ? `${Number(sup.queue_pressure).toFixed(0)}/100` : '—',
      note: 'quanto maior, mais o consumidor espera',
      tone: (sup.queue_pressure || 0) >= 62 ? 'up' : (sup.queue_pressure || 0) >= 47 ? 'flat' : 'down',
    },
    {
      label: 'Investimento em IA',
      value: fmtUsdCompact(sup.capex_ttm_usd),
      note: `${fmtPct(sup.capex_growth_pct)} a/a · mais investimento, mais disputa por chips`,
      tone: (sup.capex_growth_pct || 0) > 0 ? 'up' : 'down',
    },
  ];
  $('simpleWatch').innerHTML = watch.map((w) => `<div class="watch-card">
    <div class="watch-label">${esc(w.label)}</div>
    <div class="watch-value ${w.tone}">${esc(w.value)}</div>
    <div class="watch-note">${esc(w.note)}</div>
  </div>`).join('');
}

function render(d) {
  const changed = !snapshot || snapshot.generated_at !== d.generated_at;
  snapshot = d;
  if (window.Dash) window.Dash.onSnapshot(d);
  if (window.Prices) window.Prices.onSnapshot(d);
  $('loading').classList.add('hidden');
  $('error').classList.add('hidden');
  renderSimple(d);
  renderOverview(d);
  renderQueue(d);
  renderRanking(d);
  renderSources(d);
  populateTrendCategories();
  $('disclaimer').textContent = d.disclaimer;

  const dot = $('statusDot');
  const degraded = d.degraded.length;
  dot.className = 'dot ' + (degraded === 0 ? 'ok' : degraded > d.sources.length / 2 ? 'err' : 'warn');
  $('statusText').textContent =
    `atualizado ${new Date(d.generated_at).toLocaleTimeString('pt-BR')}` +
    (degraded ? ` · ${degraded} fonte(s) com problema` : '');

  nextRefreshAt = new Date(d.next_refresh_at).getTime();

  // Novo ciclo = novos pontos no histórico. Invalida o cache e atualiza os
  // limites de disponibilidade para liberar períodos maiores.
  if (changed && trendState.lit) {
    trendCache.clear();
    loadSeriesCatalog(true)
      .then(() => {
        if (activeTab === 'dashboard') refreshTrend();
      })
      .catch(() => {
        if (activeTab === 'dashboard') refreshTrend();
      });
  }
  // Primeira abertura: o painel inteiro aparece de uma vez, só agora.
  document.body.classList.remove('booting');
}

function showError(msg) {
  $('loading').classList.add('hidden');
  const el = $('error');
  el.classList.remove('hidden');
  $('errorText').textContent = `Falha ao carregar os dados: ${msg}`;
  $('statusDot').className = 'dot err';
  $('statusText').textContent = 'erro';
}

/* ---------------- ciclo de vida ---------------- */

async function load(force = false) {
  if (loadInFlight) return;
  loadInFlight = true;
  const btn = $('refreshBtn');
  btn.disabled = true;
  if (!snapshot) {
    $('loading').classList.remove('hidden');
    $('error').classList.add('hidden');
  }
  startProgressPolling(snapshot ? 'inline' : 'overlay');
  try {
    const res = force
      ? await fetch('/api/refresh', { method: 'POST', headers: { 'X-DSH-Refresh': '1' } })
      : await fetch('/api/snapshot');
    if (force && (res.status === 403 || res.status === 429)) {
      $('statusDot').className = 'dot warn';
      $('statusText').textContent = res.status === 429
        ? 'atualização recente; aguarde um pouco para pedir outra'
        : 'atualização manual recusada pelo servidor';
      if (!snapshot) {
        const fallback = await fetch('/api/snapshot');
        if (!fallback.ok) throw new Error(`HTTP ${fallback.status}`);
        render(await fallback.json());
      }
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch (err) {
    if (!snapshot) showError(err.message);
    else {
      $('statusDot').className = 'dot warn';
      $('statusText').textContent = 'falha na atualização; exibindo dado anterior';
    }
  } finally {
    stopProgressPolling();
    loadInFlight = false;
    btn.disabled = false;
  }
}

function tickCountdown() {
  if (!nextRefreshAt) return;
  const left = Math.max(0, nextRefreshAt - Date.now());
  const m = Math.floor(left / 60000);
  const s = Math.floor((left % 60000) / 1000);
  $('countdown').textContent = `· próxima em ${m}:${String(s).padStart(2, '0')}`;
}

function initTrendControls() {
  $('trendRanges').addEventListener('click', (ev) => {
    const btn = ev.target.closest('.seg-btn');
    if (!btn || btn.disabled) return;
    trendState.range = btn.dataset.range;
    trendState.rangeExplicit = true;
    syncTrendControls();
    syncTrendHash();
    refreshTrend();
  });

  $('trendSeriesPicker').addEventListener('change', (ev) => {
    const key = ev.target.value;
    ev.target.value = '';
    if (!key || trendState.visible.includes(key)) return;
    trendState.visible = [...trendState.visible, key];
    if (!trendState.known.includes(key)) trendState.known = [...trendState.known, key];
    chooseDefaultRange();
    syncTrendControls();
    syncTrendHash();
    refreshTrend();
  });

  $('trendLegend').addEventListener('click', (ev) => {
    const chip = ev.target.closest('.legend-chip');
    if (chip) toggleTrendSeries(chip.dataset.key);
  });

  $('trendCategory').addEventListener('change', (ev) => selectTrendCategory(ev.target.value));

  // Clique numa barra do ranking Plotly (dashboard.js).
  window.addEventListener('dash:category', (ev) => {
    selectTrendCategory(ev.detail && ev.detail.key);
    const chart = $('trendCatChart');
    if (chart) chart.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });
}

function selectTrendCategory(key) {
  if (!key || !snapshot || !snapshot.ranking.some((it) => it.key === key)) return;
  trendState.category = key;
  const sel = $('trendCategory');
  if (sel) sel.value = key;
  syncTrendHash();
  refreshTrend();
}

function initDrillDown() {
  const onSignal = (ev) => {
    if (ev.type === 'keydown' && ev.key !== 'Enter' && ev.key !== ' ') return;
    const el = ev.target.closest('[data-signal]');
    if (!el) return;
    ev.preventDefault();
    openSignal(el.dataset.signal);
  };
  $('drivers').addEventListener('click', onSignal);
  $('drivers').addEventListener('keydown', onSignal);
}

function init() {
  bindTabs();
  initTrendControls();
  initDrillDown();
  bindHeadlinePager();
  document.addEventListener('click', (ev) => {
    const jump = ev.target.closest('[data-goto]');
    if (!jump) return;
    activateTab(jump.dataset.goto);
    window.scrollTo(0, 0);
  });
  $('refreshBtn').addEventListener('click', () => load(true));
  $('retryBtn').addEventListener('click', () => load(true));
  load();
  refreshTimer = setInterval(() => load(false), REFRESH_MS);
  countdownTimer = setInterval(tickCountdown, 1000);

  // Estado inicial vem da URL (aba + período + séries + categoria).
  const { tab, params } = parseHash();
  applyTrendParams(params);
  applyPriceParams(params);
  applyChartParams(params);
  syncTrendControls();
  activateTab(tab, { syncHash: false });

  // Se a aba ficou em segundo plano além do ciclo, recarrega ao voltar.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && nextRefreshAt && Date.now() > nextRefreshAt) load(false);
  });
}

document.addEventListener('DOMContentLoaded', init);
