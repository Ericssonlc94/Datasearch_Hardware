/* DataSearch Hardware — painel.
   Gráficos são SVG desenhados à mão: zero dependência externa, funciona offline. */

const REFRESH_MS = 15 * 60 * 1000;

let snapshot = null;
let nextRefreshAt = null;
let countdownTimer = null;
let refreshTimer = null;

/* ---------------- utilidades ---------------- */

const $ = (id) => document.getElementById(id);

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );

const fmtPct = (v, digits = 1) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;

const fmtNum = (v, digits = 2) =>
  v === null || v === undefined ? '—' : v.toLocaleString('pt-BR', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });

const fmtBRL = (v) =>
  v === null || v === undefined ? '—' :
  v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

const dirClass = (v) => (v === null || v === undefined ? 'flat' : v > 0.05 ? 'up' : v < -0.05 ? 'down' : 'flat');

function scoreColor(score) {
  if (score >= 70) return '#ff5c5c';
  if (score >= 58) return '#ff9f43';
  if (score >= 45) return '#7c8aa5';
  if (score >= 35) return '#3ec5a0';
  return '#2dd4a7';
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
    grid += `<text x="${P.l - 8}" y="${gy + 4}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${gv.toFixed(opts.decimals ?? 2)}</text>`;
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

function barChart(svg, items, opts = {}) {
  const W = 640, H = opts.height || 260, P = { t: 14, r: 14, b: 58, l: 52 };
  if (!items || !items.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="#64748b" font-size="13" text-anchor="middle">sem dados disponíveis</text>`;
    return;
  }
  const vals = items.map((i) => i.v);
  const maxAbs = Math.max(...vals.map(Math.abs), 0.1);
  const min = Math.min(0, -maxAbs * 1.05), max = Math.max(0, maxAbs * 1.05);

  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const y = (v) => P.t + ih - ((v - min) / (max - min)) * ih;
  const zero = y(0);
  const step = iw / items.length;
  const bw = Math.min(step * 0.66, 46);

  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const gy = P.t + (ih * i) / 4;
    const gv = max - ((max - min) * i) / 4;
    grid += `<line x1="${P.l}" y1="${gy}" x2="${W - P.r}" y2="${gy}" stroke="#263149" stroke-width="1"/>`;
    grid += `<text x="${P.l - 8}" y="${gy + 4}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${gv.toFixed(1)}</text>`;
  }

  const bars = items.map((it, i) => {
    const cx = P.l + step * i + step / 2;
    const top = it.v >= 0 ? y(it.v) : zero;
    const h = Math.max(1.5, Math.abs(zero - y(it.v)));
    const color = it.v >= 0 ? '#ff6b6b' : '#2dd4a7';
    const label = esc(it.t);
    const short = label.length > 15 ? label.slice(0, 14) + '…' : label;
    return `
      <rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${h}" rx="3" fill="${color}" opacity=".85">
        <title>${label}: ${it.v.toFixed(2)}%</title>
      </rect>
      <text x="${cx}" y="${(it.v >= 0 ? top - 5 : top + h + 12)}" fill="#94a3bd" font-size="10"
            text-anchor="middle" font-family="monospace">${it.v.toFixed(1)}</text>
      <text x="${cx}" y="${H - 30}" fill="#64748b" font-size="9.5" text-anchor="end"
            transform="rotate(-38 ${cx} ${H - 30})">${short}</text>`;
  }).join('');

  svg.innerHTML = `${grid}
    <line x1="${P.l}" y1="${zero}" x2="${W - P.r}" y2="${zero}" stroke="#475569" stroke-width="1.5"/>
    ${bars}`;
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

/* ---------------- render ---------------- */

function renderOverview(d) {
  renderGauge($('gauge'), d.summary.iph);
  $('iphValue').textContent = d.summary.iph.toFixed(1);
  $('iphValue').style.color = scoreColor(d.summary.iph);
  $('iphLabel').textContent = d.summary.iph_label;
  $('interpretation').textContent = d.summary.interpretation;

  const b = d.brazil;
  $('kpis').innerHTML = `
    <div class="kpi">
      <div class="kpi-label">IPH Brasil <span class="badge modeled">mod</span></div>
      <div class="kpi-value" style="color:${scoreColor(d.summary.iph_brazil)}">${d.summary.iph_brazil.toFixed(1)}</div>
      <div class="kpi-sub">ajustado por câmbio e carga local</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Dólar PTAX <span class="badge observed">obs</span></div>
      <div class="kpi-value">${b.usd_brl ? 'R$ ' + fmtNum(b.usd_brl, 4) : '—'}</div>
      <div class="kpi-sub ${dirClass(b.usd_brl_change_90d_pct)}">${fmtPct(b.usd_brl_change_90d_pct)} em 90 dias</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">IPCA 12m <span class="badge observed">obs</span></div>
      <div class="kpi-value">${fmtPct(b.ipca_12m, 2)}</div>
      <div class="kpi-sub">Selic ${b.selic ? b.selic.toFixed(2) + '%' : '—'} · IGP-M ${fmtPct(b.igpm_12m, 2)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Cobertura de dados</div>
      <div class="kpi-value">${(d.summary.coverage * 100).toFixed(0)}%</div>
      <div class="kpi-sub">${d.degraded.length} fonte(s) degradada(s)</div>
    </div>`;

  // Drivers
  $('drivers').innerHTML = d.drivers.map((dr) => {
    const color = scoreColor(dr.score);
    const signals = dr.signals.map((s) => {
      const cls = s.status === 'unavailable' ? 'flat' : dirClass(s.change_pct);
      const val = s.status === 'unavailable' ? 'indisp.' : fmtPct(s.change_pct);
      return `<div class="signal">
        <span class="signal-name" title="${esc(s.label)} (${esc(s.source_key)})">${esc(s.label)}</span>
        <span class="signal-chg ${cls}">${val}</span>
        <span class="signal-score">${s.score !== null ? s.score.toFixed(0) : '—'}</span>
      </div>`;
    }).join('');
    return `<div class="driver">
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
      <div class="signals">${signals}</div>
      <div class="coverage">Peso no índice ${(dr.weight * 100).toFixed(0)}% · cobertura ${(dr.coverage * 100).toFixed(0)}%</div>
    </div>`;
  }).join('');

  lineChart($('fxChart'), b.usd_brl_series, { color: '#4f8cff', decimals: 3 });
  barChart($('ipcaChart'), b.ipca_series.slice(-14), { height: 220 });

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
  barChart($('ipcaBars'), bars, { height: 260 });

  // Manchetes
  $('headlines').innerHTML = d.headlines.length
    ? d.headlines.map((h) => `<li>
        <a href="${esc(h.url)}" target="_blank" rel="noopener noreferrer">${esc(h.title || h.url)}</a>
        <div class="meta">${esc(h.domain || '')} ${h.country ? '· ' + esc(h.country) : ''} ${h.seen_at ? '· ' + esc(h.seen_at.slice(0, 16).replace('T', ' ')) : ''}</div>
      </li>`).join('')
    : '<li class="muted">Nenhuma manchete coletada nesta rodada (fonte GDELT indisponível ou sem resultados).</li>';

  // Fontes
  $('sources').innerHTML = d.sources.map((s) => `<tr>
      <td>${esc(s.label)}${s.note ? `<span class="u">${esc(s.note)}</span>` : ''}${s.error ? `<span class="u">${esc(s.error)}</span>` : ''}</td>
      <td>${esc(s.provider)}</td>
      <td>${s.as_of ? esc(s.as_of.slice(0, 10)) : '—'}</td>
      <td><span class="badge ${esc(s.status)}">${esc(s.status)}</span></td>
    </tr>`).join('');
}

function renderRanking(d) {
  $('ranking').innerHTML = d.ranking.map((it) => {
    const o = it.observed_br;
    const im = it.imports;
    const chips = it.top_drivers.slice(0, 4).map((c) =>
      `<span class="chip">${esc(c.driver_label)} <b>${fmtPct(c.contribution_pct, 1)}</b></span>`
    ).join('');

    return `<div class="rank-item">
      <div class="rank-num">#${it.rank}</div>
      <div>
        <div class="rank-head">
          <span class="rank-icon">${it.icon}</span>
          <h3>${esc(it.label)}</h3>
          <span class="pressure-pill" style="color:${scoreColor(it.pressure_score)}">
            pressão ${it.pressure_score.toFixed(0)}/100
          </span>
        </div>

        <div class="rank-metrics">
          <div class="metric">
            <div class="metric-label">Projeção global 90d <span class="badge modeled">mod</span></div>
            <div class="metric-value ${dirClass(it.projected_global_90d_pct)}">${fmtPct(it.projected_global_90d_pct)}</div>
            <div class="metric-note">preço em US$, sem câmbio</div>
          </div>
          <div class="metric">
            <div class="metric-label">Projeção Brasil 90d <span class="badge modeled">mod</span></div>
            <div class="metric-value ${dirClass(it.projected_brazil_90d_pct)}">${fmtPct(it.projected_brazil_90d_pct)}</div>
            <div class="metric-note">com repasse cambial</div>
          </div>
          <div class="metric">
            <div class="metric-label">IPCA 12m <span class="badge observed">obs</span></div>
            <div class="metric-value ${dirClass(o && o.var_12m_pct)}">${o ? fmtPct(o.var_12m_pct, 2) : '—'}</div>
            <div class="metric-note">${o && o.subitem_label !== '—' ? esc(o.subitem_label) + (o.period ? ' · ' + esc(o.period) : '') : 'sem subitem oficial'}</div>
          </div>
          <div class="metric">
            <div class="metric-label">US$/kg importado <span class="badge observed">obs</span></div>
            <div class="metric-value">${im && im.usd_per_kg ? fmtNum(im.usd_per_kg) : '—'}</div>
            <div class="metric-note">${im && im.usd_per_kg_change_12m_pct !== null && im.usd_per_kg_change_12m_pct !== undefined
              ? fmtPct(im.usd_per_kg_change_12m_pct) + ' em 12m · ' + esc(im.ncm_label)
              : (im ? esc(im.ncm_label) + ' · ' + esc(im.status) : '—')}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Impacto por US$100</div>
            <div class="metric-value">${fmtBRL(it.brl_impact_per_100usd)}</div>
            <div class="metric-note">câmbio × carga de desembarque ${it.tax_multiplier.toFixed(2)}×</div>
          </div>
        </div>

        <p class="narrative">${esc(it.narrative)}</p>
        <div class="contrib">${chips}</div>
        <div class="tax-note">${esc(it.tax_note)}</div>
      </div>
    </div>`;
  }).join('');
}

function render(d) {
  snapshot = d;
  $('loading').classList.add('hidden');
  $('error').classList.add('hidden');
  renderOverview(d);
  renderRanking(d);
  $('disclaimer').textContent = d.disclaimer;

  const dot = $('statusDot');
  const degraded = d.degraded.length;
  dot.className = 'dot ' + (degraded === 0 ? 'ok' : degraded > d.sources.length / 2 ? 'err' : 'warn');
  $('statusText').textContent =
    `atualizado ${new Date(d.generated_at).toLocaleTimeString('pt-BR')}` +
    (degraded ? ` · ${degraded} degradada(s)` : '');

  nextRefreshAt = new Date(d.next_refresh_at).getTime();
}

function showError(msg) {
  $('loading').classList.add('hidden');
  const el = $('error');
  el.classList.remove('hidden');
  el.textContent = `Falha ao carregar os dados: ${msg}`;
  $('statusDot').className = 'dot err';
  $('statusText').textContent = 'erro';
}

/* ---------------- ciclo de vida ---------------- */

async function load(force = false) {
  const btn = $('refreshBtn');
  btn.disabled = true;
  try {
    const res = await fetch(force ? '/api/snapshot?force=true' : '/api/snapshot');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch (err) {
    if (!snapshot) showError(err.message);
    else {
      $('statusDot').className = 'dot warn';
      $('statusText').textContent = 'falha na atualização; exibindo dado anterior';
    }
  } finally {
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

function initTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.tabpanel').forEach((p) => p.classList.add('hidden'));
      tab.classList.add('active');
      $('tab-' + tab.dataset.tab).classList.remove('hidden');
      location.hash = tab.dataset.tab;
    });
  });
  const hash = location.hash.replace('#', '');
  if (hash === 'ranking') document.querySelector('[data-tab="ranking"]').click();
}

function init() {
  initTabs();
  $('refreshBtn').addEventListener('click', () => load(true));
  load();
  refreshTimer = setInterval(() => load(false), REFRESH_MS);
  countdownTimer = setInterval(tickCountdown, 1000);

  // Se a aba ficou em segundo plano além do ciclo, recarrega ao voltar.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && nextRefreshAt && Date.now() > nextRefreshAt) load(false);
  });
}

document.addEventListener('DOMContentLoaded', init);
