/* charts.js — gráfico de tendência multi-série em SVG puro.
   Sem biblioteca, sem canvas: cada ponto é um nó do DOM e a linha quebra em
   lacuna. A interação (crosshair, tooltip, teclado) vive aqui; o app.js só
   fornece os dados e o estado. */

const TREND_COLORS = [
  '#4f8cff', '#2dd4a7', '#ff9f43', '#ff5c5c',
  '#c084fc', '#38bdf8', '#f472b6', '#a3e635',
];

const trendColor = (i) => TREND_COLORS[i % TREND_COLORS.length];

const clamp01 = (v) => Math.max(0, Math.min(1, v));

const fmtAxisDate = (ms, spanMs) => {
  const d = new Date(ms);
  if (!Number.isFinite(ms)) return '';
  if (spanMs > 300 * 864e5) {
    return d.toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
  }
  if (spanMs > 2 * 864e5) {
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  }
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
};

const fmtTipDate = (ms) =>
  new Date(ms).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });

const fmtPointDate = (ms, spanMs) => {
  const d = new Date(ms);
  if (spanMs > 90 * 864e5) return d.toLocaleDateString('pt-BR');
  return d.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
};

function _trendNum(v, decimals) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toLocaleString('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function _trendPrepared(cfg) {
  const series = (cfg.series || [])
    .filter((s) => !s.hidden)
    .map((s) => ({
      ...s,
      pts: (s.points || [])
        .map((p) => ({
          ms: Date.parse(p.t),
          t: p.t,
          v: p.v === null || p.v === undefined ? null : Number(p.v),
        }))
        .filter((p) => Number.isFinite(p.ms))
        .sort((a, b) => a.ms - b.ms),
    }));
  return series;
}

function _trendDomain(series, cfg) {
  const stamps = series.flatMap((s) => s.pts.map((p) => p.ms));
  const values = series.flatMap((s) => s.pts.filter((p) => p.v !== null).map((p) => p.v));
  let t0 = cfg.t0 ? Date.parse(cfg.t0) : NaN;
  let t1 = cfg.t1 ? Date.parse(cfg.t1) : NaN;
  if (!Number.isFinite(t0)) t0 = stamps.length ? Math.min(...stamps) : Date.now() - 864e5;
  if (!Number.isFinite(t1)) t1 = stamps.length ? Math.max(...stamps) : Date.now();
  if (t1 <= t0) t1 = t0 + 864e5;

  // O período pedido manda no eixo. Só ajustamos ao trecho com dados quando
  // a própria tela escolhe "Tudo"; assim 24h, 7d e 30d nunca desenham a mesma
  // janela por acidente.
  let zoomed = false;
  if (cfg.zoomToData && stamps.length) {
    const dataT0 = Math.min(...stamps);
    const dataT1 = Math.max(...stamps);
    const dataSpan = dataT1 - dataT0;
    const pad = dataSpan > 0 ? Math.max(dataSpan * 0.05, 60_000) : 30 * 60_000;
    t0 = Math.max(t0, dataT0 - pad);
    t1 = Math.min(t1, dataT1 + pad);
    if (t1 <= t0) {
      t0 = dataT0 - pad;
      t1 = dataT1 + pad;
    }
    zoomed = true;
  }
  if (t1 <= t0) t1 = t0 + 864e5;

  let min = values.length ? Math.min(...values) : 0;
  let max = values.length ? Math.max(...values) : 1;
  if (max === min) {
    const bump = Math.abs(max) * 0.05 || 1;
    min -= bump;
    max += bump;
  } else {
    const pad = (max - min) * 0.08;
    min -= pad;
    max += pad;
  }
  return { t0, t1, min, max, zoomed };
}

const _DAY_MS = 86400000;

function _trendPath(pts, x, y, bucketSeconds, rebuiltMs) {
  // Lacuna explícita (bucket vazio → null) já quebra a linha no laço abaixo.
  // Sem nulls, o limite é generoso com o calendário real: mercado não abre no
  // fim de semana e série mensal tem ~30 dias entre pontos.
  // Até `rebuiltMs` a série é recálculo diário (um ponto por dia): ali a
  // tolerância é de dia, e o trecho sai num caminho próprio (tracejado).
  const hasNulls = pts.some((p) => p.v === null);
  const diffs = [];
  for (let i = 1; i < pts.length; i++) {
    const d = pts[i].ms - pts[i - 1].ms;
    if (d > 0) diffs.push(d);
  }
  diffs.sort((a, b) => a - b);
  const median = diffs.length ? diffs[diffs.length >> 1] : 86400000;
  const gapMs = hasNulls
    ? Infinity
    : Math.max(bucketSeconds ? bucketSeconds * 1000 * 1.8 : 0, median * 4);
  const rebuiltGap = Math.max(gapMs === Infinity ? 0 : gapMs, _DAY_MS * 1.8);
  const isRebuilt = (p) => Number.isFinite(rebuiltMs) && p.ms <= rebuiltMs;
  let live = '';
  let rebuilt = '';
  let pen = false;
  let prev = null;
  for (const p of pts) {
    if (p.v === null) { pen = false; prev = null; continue; }
    const xy = `${x(p.ms).toFixed(1)},${y(p.v).toFixed(1)}`;
    if (isRebuilt(p)) {
      if (prev !== null && p.ms - prev.ms > rebuiltGap) pen = false;
      rebuilt += `${pen ? 'L' : 'M'}${xy} `;
    } else if (prev !== null && isRebuilt(prev)) {
      // Passagem do recálculo para a medição: a ponte fica no tracejado.
      if (p.ms - prev.ms <= rebuiltGap) rebuilt += `L${xy} `;
      live += `M${xy} `;
    } else {
      if (prev !== null && p.ms - prev.ms > gapMs) pen = false;
      live += `${pen ? 'L' : 'M'}${xy} `;
    }
    pen = true;
    prev = p;
  }
  return { live: live.trim(), rebuilt: rebuilt.trim() };
}

function _lastAtOrBefore(pts, ms) {
  let lo = 0;
  let hi = pts.length - 1;
  let best = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].ms <= ms) { best = pts[mid]; lo = mid + 1; }
    else hi = mid - 1;
  }
  return best;
}

/* ---------------- desenho ---------------- */

function trendChart(svg, cfg) {
  const W = 900;
  const H = cfg.height || 340;
  const P = { t: 18, r: 18, b: cfg.bottomPad || 34, l: 64 };
  const iw = W - P.l - P.r;
  const ih = H - P.t - P.b;
  const decimals = cfg.decimals ?? 1;
  const series = _trendPrepared(cfg);

  if (!series.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="#64748b" font-size="13" text-anchor="middle">nenhuma série selecionada</text>`;
    svg._trend = null;
    return;
  }

  const { t0, t1, min, max, zoomed } = _trendDomain(series, cfg);
  const span = t1 - t0;
  const x = (ms) => P.l + clamp01((ms - t0) / span) * iw;
  const y = (v) => P.t + ih - ((v - min) / (max - min)) * ih;

  const hasData = series.some((s) => s.pts.some((p) => p.v !== null));
  if (!hasData) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="#64748b" font-size="13" text-anchor="middle">histórico ainda vazio — os primeiros pontos aparecem após o próximo ciclo</text>`;
    svg._trend = { cfg, series, t0, t1, x, y, P, W, H, iw, ih, span, decimals, zoomed, empty: true };
    _trendBind(svg);
    return;
  }

  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const gy = P.t + (ih * i) / 4;
    const gv = max - ((max - min) * i) / 4;
    grid += `<line x1="${P.l}" y1="${gy.toFixed(1)}" x2="${W - P.r}" y2="${gy.toFixed(1)}" stroke="#263149" stroke-width="1"/>`;
    grid += `<text x="${P.l - 8}" y="${(gy + 4).toFixed(1)}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${_trendNum(gv, decimals)}</text>`;
  }

  let ticks = '';
  for (let i = 0; i <= 3; i++) {
    const ms = t0 + (span * i) / 3;
    const gx = x(ms);
    ticks += `<line x1="${gx.toFixed(1)}" y1="${P.t}" x2="${gx.toFixed(1)}" y2="${P.t + ih}" stroke="#1b2437" stroke-width="1"/>`;
    ticks += `<text x="${gx.toFixed(1)}" y="${H - 10}" fill="#64748b" font-size="10" text-anchor="middle" font-family="monospace">${fmtAxisDate(ms, span)}</text>`;
  }

  const lines = series.map((s) => {
    const rebuiltMs = s.rebuiltUntil ? Date.parse(s.rebuiltUntil) : NaN;
    // Antes de `modelSince` a série usa uma versão antiga da conta: o trecho
    // continua visível, mas esmaecido e pontilhado, sem ponte para o novo.
    const sinceMs = s.modelSince ? Date.parse(s.modelSince) : NaN;
    const hasOld = Number.isFinite(sinceMs);
    const oldPts = hasOld ? s.pts.filter((p) => p.ms < sinceMs) : [];
    const newPts = hasOld ? s.pts.filter((p) => p.ms >= sinceMs) : s.pts;
    const o = _trendPath(oldPts, x, y, cfg.bucketSeconds, NaN);
    const oldPath = o.live
      ? `<path class="trend-old-model" d="${o.live}" fill="none" stroke="${s.color}" stroke-width="1.6" stroke-dasharray="2 4" stroke-opacity="0.4" stroke-linejoin="round" stroke-linecap="round" data-key="${s.key}"/>`
      : '';
    const d = _trendPath(newPts, x, y, cfg.bucketSeconds, rebuiltMs);
    if (!d.live && !d.rebuilt && !oldPath) return '';
    const last = [...s.pts].reverse().find((p) => p.v !== null);
    const dot = last
      ? `<circle cx="${x(last.ms).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="3.2" fill="${s.color}"/>`
      : '';
    const rebuilt = d.rebuilt
      ? `<path class="trend-rebuilt" d="${d.rebuilt}" fill="none" stroke="${s.color}" stroke-width="1.6" stroke-dasharray="5 4" stroke-opacity="0.8" stroke-linejoin="round" stroke-linecap="round" data-key="${s.key}"/>`
      : '';
    const live = d.live
      ? `<path d="${d.live}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" data-key="${s.key}"/>`
      : '';
    return `${oldPath}${rebuilt}${live}${dot}`;
  }).join('');

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = `
    ${grid}${ticks}
    <line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${P.t + ih}" stroke="#475569" stroke-width="1"/>
    <line x1="${P.l}" y1="${P.t + ih}" x2="${W - P.r}" y2="${P.t + ih}" stroke="#475569" stroke-width="1"/>
    ${lines}
    <g class="trend-cross" style="display:none">
      <line class="cross-line" y1="${P.t}" y2="${P.t + ih}" stroke="#94a3bd" stroke-width="1" stroke-dasharray="3 3"/>
      <g class="cross-dots"></g>
    </g>`;

  svg._trend = { cfg, series, t0, t1, x, y, P, W, H, iw, ih, span, decimals, zoomed, empty: false };
  _trendBind(svg);
}

/* ---------------- interação ---------------- */

function _trendBind(svg) {
  if (svg._trendBound) return;
  svg._trendBound = true;
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('aria-label', 'Gráfico de tendência. Use as setas para navegar e Enter para fixar.');

  svg.addEventListener('pointermove', (ev) => {
    const st = svg._trend;
    if (!st || st.empty) return;
    const rect = svg.getBoundingClientRect();
    if (!rect.width) return;
    const px = ((ev.clientX - rect.left) / rect.width) * st.W;
    const ms = st.t0 + clamp01((px - st.P.l) / st.iw) * st.span;
    svg._trendCursorMs = ms;
    _trendShow(svg, ms, ev);
  });

  svg.addEventListener('pointerleave', () => {
    if (!svg._trendPinned) _trendHide(svg);
  });

  svg.addEventListener('focus', () => {
    const st = svg._trend;
    if (st && !st.empty && svg._trendCursorMs === undefined) {
      svg._trendCursorMs = st.t1;
      _trendShow(svg, st.t1);
    }
  });

  svg.addEventListener('blur', () => {
    if (!svg._trendPinned) _trendHide(svg);
  });

  svg.addEventListener('keydown', (ev) => {
    const st = svg._trend;
    if (!st || st.empty) return;
    const step = Math.max(st.span / 60, 3600 * 1000);
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
      ev.preventDefault();
      const base = svg._trendCursorMs ?? st.t1;
      const next = Math.max(st.t0, Math.min(st.t1, base + (ev.key === 'ArrowRight' ? step : -step)));
      svg._trendCursorMs = next;
      _trendShow(svg, next);
    } else if (ev.key === 'Enter') {
      svg._trendPinned = !svg._trendPinned;
      if (svg._trendPinned) _trendShow(svg, svg._trendCursorMs ?? st.t1);
      else _trendHide(svg);
    } else if (ev.key === 'Escape') {
      svg._trendPinned = false;
      _trendHide(svg);
    }
  });

  svg.addEventListener('click', () => {
    svg._trendPinned = !svg._trendPinned;
  });
}

function _trendHide(svg) {
  const cross = svg.querySelector('.trend-cross');
  if (cross) cross.style.display = 'none';
  const wrap = svg.parentElement;
  const tip = wrap && wrap.querySelector('.trend-tip');
  if (tip) tip.classList.add('hidden');
}

function _trendShow(svg, ms, ev) {
  const st = svg._trend;
  if (!st || st.empty) return;
  const cross = svg.querySelector('.trend-cross');
  if (!cross) return;

  const cx = st.x(ms);
  const line = cross.querySelector('.cross-line');
  line.setAttribute('x1', cx.toFixed(1));
  line.setAttribute('x2', cx.toFixed(1));

  const rows = [];
  let dots = '';
  for (const s of st.series) {
    const p = _lastAtOrBefore(s.pts, ms);
    if (!p || p.v === null) continue;
    dots += `<circle cx="${st.x(p.ms).toFixed(1)}" cy="${st.y(p.v).toFixed(1)}" r="3.6" fill="${s.color}" stroke="#0b0f17" stroke-width="1.5"/>`;
    const dec = s.decimals ?? st.decimals;
    const when = st.span > 40 * 864e5 ? fmtPointDate(p.ms, st.span) : '';
    const sinceMs = s.modelSince ? Date.parse(s.modelSince) : NaN;
    const oldNote = Number.isFinite(sinceMs) && p.ms < sinceMs ? ' · conta antiga' : '';
    rows.push(
      `<div class="tip-row"><span class="tip-dot" style="background:${s.color}"></span>` +
      `<span class="tip-label">${_tipEsc(s.label)}</span>` +
      `<b>${_trendNum(p.v, dec)}</b>` +
      `<span class="tip-unit">${_tipEsc(s.unit || '')}${when ? ' · ' + _tipEsc(when) : ''}${oldNote}</span></div>`
    );
  }
  cross.querySelector('.cross-dots').innerHTML = dots;
  cross.style.display = '';

  const { wrap, tip } = { wrap: svg.parentElement, tip: svg.parentElement.querySelector('.trend-tip') };
  if (!tip) return;  tip.innerHTML = `<div class="tip-head">${fmtTipDate(ms)}</div>${rows.join('')}`;
  tip.classList.remove('hidden');

  const wrapRect = wrap.getBoundingClientRect();
  const svgRect = svg.getBoundingClientRect();
  let ax;
  let ay;
  if (ev && ev.clientX !== undefined) {
    ax = ev.clientX - wrapRect.left;
    ay = ev.clientY - wrapRect.top;
  } else {
    ax = svgRect.left - wrapRect.left + (st.x(ms) / st.W) * svgRect.width;
    ay = svgRect.top - wrapRect.top + svgRect.height * 0.3;
  }
  const tw = tip.offsetWidth;
  const th = tip.offsetHeight;
  let left = ax + 16;
  if (left + tw > wrapRect.width - 8) left = Math.max(8, ax - tw - 16);
  let top = ay - th - 12;
  if (top < 8) top = ay + 18;
  if (top + th > wrapRect.height - 8) top = Math.max(8, wrapRect.height - th - 8);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

function _tipEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
}
