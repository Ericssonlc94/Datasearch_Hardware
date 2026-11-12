/* DataSearch Hardware — gráficos da aba Gráficos em SVG inline, sem
   biblioteca. O resumo (KPIs, radar e ranking) vem só do snapshot e não
   depende do período. A evolução (séries escolhidas e produto) é desenhada
   aqui com dados e estado do app.js. Cada gráfico é refeito quando o
   contêiner muda de tamanho (ResizeObserver), para o texto não escalar. */

(function () {
  'use strict';

  const COLOR = {
    blue: '#4f8cff',
    orange: '#ff9f43',
    green: '#2dd4a7',
    red: '#ff5c5c',
    muted: '#7c8aa5',
    grid: '#263149',
    zero: '#475569',
    txt: '#94a3bd',
    dim: '#64748b',
  };

  const DASH = {
    active: false,
    snapshot: null,
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

  const f1 = (n) => Number(n).toFixed(1);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const isNum = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

  /* ---------------- base SVG ---------------- */

  // Cada gráfico registra uma função (el, largura, altura) que devolve o
  // HTML; ela roda de novo a cada mudança de tamanho do contêiner.
  const REG = new Map();
  const pending = new Set();
  let observer = null;

  function renderOne(id) {
    const el = d$(id);
    const fn = REG.get(id);
    if (!el || !fn) return;
    const w = Math.floor(el.clientWidth);
    const h = Math.floor(el.clientHeight);
    if (w < 40 || h < 40) return; // aba oculta: refaz quando aparecer
    el.style.position = 'relative';
    // O papel e o rótulo passam para o <svg>; no contêiner, role=img
    // esconderia o conteúdo para leitores de tela.
    el.removeAttribute('role');
    el.removeAttribute('aria-label');
    try {
      fn(el, w, h);
    } catch (err) {
      console.error('dashboard', id, err);
      el.innerHTML = '<p class="dash-error">Falha ao desenhar o gráfico.</p>';
    }
  }

  function scheduleRender(id) {
    if (pending.has(id)) return;
    pending.add(id);
    requestAnimationFrame(() => {
      pending.delete(id);
      renderOne(id);
    });
  }

  function paint(id, fn) {
    const el = d$(id);
    if (!el) return;
    REG.set(id, fn);
    if (!observer && window.ResizeObserver) {
      observer = new ResizeObserver((entries) => {
        entries.forEach((e) => { if (e.target.id) scheduleRender(e.target.id); });
      });
    }
    if (observer && el.dataset.ro !== '1') {
      el.dataset.ro = '1';
      observer.observe(el);
    }
    renderOne(id);
  }

  function resizeVisible() {
    if (!DASH.active) return;
    requestAnimationFrame(() => REG.forEach((_, id) => renderOne(id)));
  }
  window.addEventListener('resize', resizeVisible);

  // Sem elemento title: o navegador o mostraria como balão nativo sobre o gráfico.
  // O nome acessível fica no aria-label do role=img.
  function svgDoc(w, h, label, inner) {
    const t = dEsc(label);
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${t}" ` +
      'style="display:block;font-family:system-ui,-apple-system,\'Segoe UI\',Roboto,sans-serif">' +
      `${inner}</svg><div class="trend-tip hidden"></div>`;
  }

  const txt = (x, y, s, o = {}) => (
    `<text x="${f1(x)}" y="${f1(y)}" fill="${o.fill || COLOR.dim}" font-size="${o.size || 10}"` +
    `${o.anchor ? ` text-anchor="${o.anchor}"` : ''}${o.mono ? ' font-family="monospace"' : ''}` +
    `${o.rotate ? ` transform="rotate(${o.rotate} ${f1(x)} ${f1(y)})"` : ''}>${dEsc(s)}</text>`
  );

  function drawEmpty(id, message) {
    paint(id, (el, w, h) => {
      el.innerHTML = svgDoc(w, h, message, txt(w / 2, h / 2, message, { anchor: 'middle', size: 12.5 }));
    });
  }

  function niceScale(lo, hi, count = 5) {
    let a = lo;
    let b = hi;
    if (!(b > a)) { const c = a || 0; a = c - 1; b = c + 1; }
    const raw = (b - a) / count;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const n = raw / mag;
    const step = (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
    const nlo = Math.floor(a / step + 1e-9) * step;
    const nhi = Math.ceil(b / step - 1e-9) * step;
    const ticks = [];
    const steps = Math.round((nhi - nlo) / step);
    for (let i = 0; i <= steps; i += 1) {
      const v = nlo + i * step;
      ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    }
    return { lo: nlo, hi: nhi, ticks, dec: Math.min(3, Math.max(0, -Math.floor(Math.log10(step) + 1e-9))) };
  }

  function placeTip(el, tip, cx, cy) {
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    let left = cx + 14;
    if (left + tw > el.clientWidth - 6) left = Math.max(6, cx - tw - 14);
    let top = cy - th - 10;
    if (top < 6) top = cy + 16;
    if (top + th > el.clientHeight - 6) top = Math.max(6, el.clientHeight - th - 6);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }

  function showTip(el, html, ev) {
    const tip = el.querySelector('.trend-tip');
    if (!tip) return;
    tip.innerHTML = html;
    tip.classList.remove('hidden');
    const r = el.getBoundingClientRect();
    placeTip(el, tip, ev.clientX - r.left, ev.clientY - r.top);
  }

  function hideTip(el) {
    const tip = el.querySelector('.trend-tip');
    if (tip) tip.classList.add('hidden');
  }

  const tipRow = (color, label, value, unit = '') => (
    `<div class="tip-row"><span class="tip-dot" style="background:${dEsc(color)}"></span>` +
    `<span class="tip-label">${dEsc(label)}</span><b>${dEsc(value)}</b>` +
    `${unit ? `<span class="tip-unit">${dEsc(unit)}</span>` : ''}</div>`
  );

  const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

  // Verde → cinza → vermelho conforme a pressão (0–100).
  function scoreFill(score) {
    const t = clamp((Number(score) || 0) / 100, 0, 1);
    const stops = [COLOR.green, COLOR.muted, COLOR.red].map(hexRgb);
    const k = t * 2;
    const i = Math.min(1, Math.floor(k));
    const u = k - i;
    const c = stops[i].map((v, j) => Math.round(v + (stops[i + 1][j] - v) * u));
    return `rgb(${c.join(',')})`;
  }

  function setStatus(text, cls = '') {
    const el = d$('dashStatus');
    if (!el) return;
    el.textContent = text;
    el.className = `dash-status${cls ? ` ${cls}` : ''}`;
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
      (a, b) => (Number(b.projected_brazil_30d_pct) || 0) - (Number(a.projected_brazil_30d_pct) || 0),
    );
    const label = 'Barras horizontais da estimativa de 30 dias por produto, global e Brasil: ' +
      items.map((i) => `${i.label} ${dPct(i.projected_brazil_30d_pct)} no Brasil`).join('; ');
    paint('dashRanking', (el, w, h) => {
      const P = { l: Math.min(150, Math.round(w * 0.36)), r: 22, t: 30, b: 42 };
      const iw = w - P.l - P.r;
      const ih = h - P.t - P.b;
      const vals = items.flatMap((i) => [i.projected_global_30d_pct, i.projected_brazil_30d_pct])
        .filter(isNum).map(Number);
      const sc = niceScale(Math.min(0, ...vals), Math.max(0, ...vals), Math.max(2, Math.floor(iw / 80)));
      const x = (v) => P.l + ((v - sc.lo) / (sc.hi - sc.lo)) * iw;
      const rowH = ih / items.length;
      const barH = Math.min(16, (rowH * 0.74) / 2);
      let g = '';
      sc.ticks.forEach((t) => {
        const gx = x(t);
        g += `<line x1="${f1(gx)}" y1="${P.t}" x2="${f1(gx)}" y2="${P.t + ih}" stroke="${t === 0 ? COLOR.zero : COLOR.grid}"/>`;
        g += txt(gx, P.t + ih + 14, dNum(t, sc.dec), { anchor: 'middle', mono: true });
      });
      g += txt(P.l + iw / 2, h - 6, 'variação projetada 30d (%)', { anchor: 'middle' });
      // legenda
      g += `<rect x="${P.l}" y="6" width="10" height="10" rx="2" fill="${COLOR.muted}" fill-opacity=".55"/>`;
      g += txt(P.l + 15, 15, 'Global (US$)');
      g += `<rect x="${P.l + 100}" y="6" width="10" height="10" rx="2" fill="url(#dashRankGrad)"/>`;
      g += txt(P.l + 115, 15, 'Brasil (câmbio + carga)');
      const x0 = x(0);
      const bar = (v, y, fill, op) => {
        if (!isNum(v)) return '';
        const bx = x(Number(v));
        return `<rect x="${f1(Math.min(x0, bx))}" y="${f1(y)}" width="${f1(Math.max(1, Math.abs(bx - x0)))}" ` +
          `height="${f1(barH)}" fill="${fill}"${op ? ` fill-opacity="${op}"` : ''}/>`;
      };
      items.forEach((it, i) => {
        const top = P.t + i * rowH;
        const mid = top + rowH / 2;
        const y0 = mid - barH;
        g += `<rect class="dash-hit" data-i="${i}" x="0" y="${f1(top)}" width="${w}" height="${f1(rowH)}" ` +
          'fill="transparent" style="cursor:pointer"/>';
        g += bar(it.projected_global_30d_pct, y0, COLOR.muted, 0.55);
        g += bar(it.projected_brazil_30d_pct, y0 + barH, scoreFill(it.pressure_score));
        g += txt(P.l - 8, mid + 3.5, short(it.label, Math.max(8, Math.floor((P.l - 12) / 6.2))), {
          anchor: 'end', size: 10.5, fill: COLOR.txt,
        });
      });
      const defs = '<defs><linearGradient id="dashRankGrad" x1="0" x2="1">' +
        `<stop offset="0" stop-color="${COLOR.green}"/><stop offset=".5" stop-color="${COLOR.muted}"/>` +
        `<stop offset="1" stop-color="${COLOR.red}"/></linearGradient></defs>`;
      el.innerHTML = svgDoc(w, h, label, defs + g);
      const svg = el.querySelector('svg');
      const hits = svg.querySelectorAll('.dash-hit');
      const clear = () => { hits.forEach((r) => r.setAttribute('fill', 'transparent')); hideTip(el); };
      svg.addEventListener('pointermove', (ev) => {
        const hit = ev.target.closest && ev.target.closest('.dash-hit');
        if (!hit) { clear(); return; }
        hits.forEach((r) => r.setAttribute('fill', r === hit ? 'rgba(255,255,255,.05)' : 'transparent'));
        const it = items[Number(hit.dataset.i)];
        showTip(el,
          `<div class="tip-head">${dEsc(it.label)}</div>` +
          tipRow(COLOR.muted, 'Global (US$)', dPct(it.projected_global_30d_pct)) +
          tipRow(scoreFill(it.pressure_score), 'Brasil', dPct(it.projected_brazil_30d_pct)) +
          '<div class="tip-unit">clique para ver a evolução</div>', ev);
      });
      svg.addEventListener('pointerleave', clear);
      svg.addEventListener('click', (ev) => {
        const hit = ev.target.closest && ev.target.closest('.dash-hit');
        if (hit) selectCategory(items[Number(hit.dataset.i)].key);
      });
    });
  }

  function renderRadar() {
    const snap = DASH.snapshot;
    if (!snap || !(snap.drivers || []).length) {
      drawEmpty('dashRadar', 'Vetores indisponíveis.');
      return;
    }
    const drivers = snap.drivers.map((d) => ({
      full: String(d.label || ''),
      name: short(String(d.label || '').split(':')[0].split('—')[0].trim(), 18),
      score: clamp(Number(d.score) || 0, 0, 100),
    }));
    const label = 'Radar dos fatores de pressão (0 a 100): ' +
      drivers.map((d) => `${d.name} ${dNum(d.score, 0)}`).join('; ');
    paint('dashRadar', (el, w, h) => {
      const n = drivers.length;
      const cx = w / 2;
      const cy = h / 2 + 4;
      const R = Math.max(30, Math.min(w / 2 - 70, h / 2 - 28));
      const ang = (i) => -Math.PI / 2 + (2 * Math.PI * i) / n;
      const pt = (i, r) => [cx + Math.cos(ang(i)) * r, cy + Math.sin(ang(i)) * r];
      let g = '';
      [25, 50, 75, 100].forEach((v) => {
        const ring = drivers.map((_, i) => pt(i, (R * v) / 100).map(f1).join(',')).join(' ');
        g += `<polygon points="${ring}" fill="none" stroke="${COLOR.grid}"/>`;
        g += txt(cx + 3, cy - (R * v) / 100 - 2, String(v), { size: 9 });
      });
      drivers.forEach((d, i) => {
        const [ex, ey] = pt(i, R);
        g += `<line x1="${f1(cx)}" y1="${f1(cy)}" x2="${f1(ex)}" y2="${f1(ey)}" stroke="${COLOR.grid}"/>`;
        const [lx, ly] = pt(i, R + 12);
        const c = Math.cos(ang(i));
        g += txt(lx, ly + 3.5, d.name, {
          anchor: Math.abs(c) < 0.2 ? 'middle' : (c > 0 ? 'start' : 'end'), size: 9.5, fill: COLOR.txt,
        });
      });
      const poly = drivers.map((d, i) => pt(i, (R * d.score) / 100).map(f1).join(',')).join(' ');
      g += `<polygon points="${poly}" fill="rgba(255,159,67,.12)" stroke="${COLOR.orange}" stroke-width="2" stroke-linejoin="round"/>`;
      drivers.forEach((d, i) => {
        const [px, py] = pt(i, (R * d.score) / 100);
        g += `<circle cx="${f1(px)}" cy="${f1(py)}" r="3" fill="${COLOR.orange}"/>`;
        g += `<circle class="dash-hit" data-i="${i}" cx="${f1(px)}" cy="${f1(py)}" r="14" fill="transparent"/>`;
      });
      el.innerHTML = svgDoc(w, h, label, g);
      const svg = el.querySelector('svg');
      svg.addEventListener('pointermove', (ev) => {
        const hit = ev.target.closest && ev.target.closest('.dash-hit');
        if (!hit) { hideTip(el); return; }
        const d = drivers[Number(hit.dataset.i)];
        showTip(el, `<div class="tip-head">${dEsc(d.full)}</div>${tipRow(COLOR.orange, 'agora', dNum(d.score, 0))}`, ev);
      });
      svg.addEventListener('pointerleave', () => hideTip(el));
    });
  }

  /* ---------------- interação ---------------- */

  // O produto da evolução é estado do app.js: o clique só avisa.
  function selectCategory(key) {
    if (!key) return;
    window.dispatchEvent(new CustomEvent('dash:category', { detail: { key } }));
  }

  /* ---------------- ciclo ---------------- */

  function refresh() {
    if (!DASH.snapshot || !DASH.active) return;
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

  function activate() {
    DASH.active = true;
    if (!DASH.snapshot) {
      setStatus('aguardando o primeiro snapshot…');
      return;
    }
    refresh();
    // A aba estava oculta: os contêineres podem ter mudado de largura.
    resizeVisible();
  }

  /* ---------------- evolução (dados vêm do app.js) ---------------- */

  const DAY_MS = 86400000;

  // Sem null, a linha só quebra em salto bem maior que o passo normal
  // (fim de semana e série mensal não são lacuna). Com null, o próprio
  // null quebra. Até `rebuiltUntil` a série é recálculo diário e sai
  // tracejada, com a ponte para a medição ao vivo.
  function trendLists(s, bucketSeconds) {
    const pts = (s.points || [])
      .map((p) => ({ t: p.t, ms: Date.parse(p.t), v: isNum(p.v) ? Number(p.v) : null }))
      .filter((p) => Number.isFinite(p.ms))
      .sort((a, b) => a.ms - b.ms);
    const old = [];
    const live = [];
    if (!pts.length) return { old, live, isRebuilt: () => false };
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
    // Com a lista de dias da API só esses dias saem tracejados (buraco no
    // meio da série ao vivo incluído); sem ela, vale tudo até rebuiltUntil.
    const days = Array.isArray(s.rebuiltDays) ? new Set(s.rebuiltDays) : null;
    const isRebuilt = (p) => (days
      ? days.has(String(p.t).slice(0, 10))
      : Number.isFinite(rebuiltMs) && p.ms <= rebuiltMs);

    // Cada lista guarda só pontos vizinhos; salto entre eles vira null.
    const st = { old: null, live: null };
    const push = (list, key, i) => {
      if (st[key] === i) return;
      if (st[key] !== null && i !== st[key] + 1) list.push({ t: pts[i].t, ms: pts[i].ms, v: null });
      list.push(pts[i]);
      st[key] = i;
    };
    for (let i = 0; i < pts.length; i += 1) {
      const p = pts[i];
      const prev = i ? pts[i - 1] : null;
      const rebuilt = isRebuilt(p);
      // O trecho entre um ponto reconstruído e um ao vivo (nos dois sentidos)
      // é tracejado e liga os dois.
      if (prev && prev.v !== null && p.v !== null && isRebuilt(prev) !== rebuilt
        && p.ms - prev.ms <= rebuiltGap) {
        push(old, 'old', i - 1);
        push(old, 'old', i);
      }
      const gap = rebuilt ? rebuiltGap : gapMs;
      if (prev && prev.v !== null && p.v !== null && st[rebuilt ? 'old' : 'live'] === i - 1
        && p.ms - prev.ms > gap) {
        (rebuilt ? old : live).push({ t: prev.t, ms: prev.ms, v: null });
        st[rebuilt ? 'old' : 'live'] = null;
      }
      push(rebuilt ? old : live, rebuilt ? 'old' : 'live', i);
    }
    return { old, live, isRebuilt };
  }

  function segmentsOf(list) {
    const segs = [];
    let cur = [];
    for (const p of list) {
      if (p.v === null) {
        if (cur.length) segs.push(cur);
        cur = [];
      } else {
        cur.push(p);
      }
    }
    if (cur.length) segs.push(cur);
    return segs;
  }

  // Ponto mais próximo de `ms` em lista ordenada por `ms`.
  function nearest(arr, ms) {
    let lo = 0;
    let hi = arr.length - 1;
    if (hi < 0) return null;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (arr[mid].ms < ms) lo = mid; else hi = mid;
    }
    return Math.abs(arr[lo].ms - ms) <= Math.abs(arr[hi].ms - ms) ? arr[lo] : arr[hi];
  }

  function fmtTick(ms, span) {
    const d = new Date(ms);
    if (span < 2 * DAY_MS) return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    if (span > 300 * DAY_MS) return d.toLocaleDateString('pt-BR', { month: '2-digit', year: '2-digit' });
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  }

  const fmtTipDate = (ms) => new Date(ms).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });

  // cfg: { series, bars, from, to, range, bucketSeconds, zoomToData,
  // showLegend, empty, yTitle, zeroLabel }. Barras vão no eixo da direita;
  // zeroLabel marca a linha de zero com um rótulo.
  function drawTrend(id, cfg) {
    const lists = (cfg.series || [])
      .map((s) => ({ s, ...trendLists(s, cfg.bucketSeconds) }))
      .filter((l) => l.old.length || l.live.length);
    const bars = (cfg.bars || []).map((b) => ({
      b,
      pts: (b.points || [])
        .map((p) => ({ ms: Date.parse(p.t), v: isNum(p.v) ? Number(p.v) : null }))
        .filter((p) => Number.isFinite(p.ms) && p.v !== null)
        .sort((a, c) => a.ms - c.ms),
    })).filter((b) => b.pts.length);
    if (!lists.length && !bars.length) {
      drawEmpty(id, cfg.empty || 'Ainda não há histórico para mostrar.');
      return;
    }
    lists.forEach((l) => {
      l.all = [...l.old, ...l.live].filter((p) => p.v !== null).sort((a, b) => a.ms - b.ms);
    });

    const stamps = [
      ...lists.flatMap((l) => [...l.old, ...l.live].map((p) => p.ms)),
      ...bars.flatMap((b) => b.pts.map((p) => p.ms)),
    ];
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
    if (!(Number.isFinite(x0) && Number.isFinite(x1) && x1 > x0)) {
      const lo = Math.min(...stamps);
      const hi = Math.max(...stamps);
      const pad = hi > lo ? (hi - lo) * 0.05 : 30 * 60000;
      x0 = lo - pad;
      x1 = hi + pad;
    }
    const span = x1 - x0;

    const label = `Séries históricas: ${[...lists.map((l) => l.s.label), ...bars.map((b) => b.b.label)].join(', ')}`;
    paint(id, (el, w, h) => {
      const P = {
        l: 54, r: bars.length ? 52 : 18, t: cfg.showLegend ? 34 : 16, b: 38,
      };
      const iw = w - P.l - P.r;
      const ih = h - P.t - P.b;
      const x = (ms) => P.l + ((ms - x0) / span) * iw;

      const lineVals = lists.flatMap((l) => l.all.map((p) => p.v));
      if (cfg.zeroLabel) lineVals.push(0);
      let vlo = lineVals.length ? Math.min(...lineVals) : 0;
      let vhi = lineVals.length ? Math.max(...lineVals) : 1;
      const padV = (vhi - vlo) * 0.08;
      vlo -= padV;
      vhi += padV;
      if (cfg.zeroLabel && lineVals.length) { vlo = Math.min(vlo, 0); vhi = Math.max(vhi, 0); }
      const ys = niceScale(vlo, vhi, Math.max(2, Math.floor(ih / 55)));
      const y = (v) => P.t + ih - ((v - ys.lo) / (ys.hi - ys.lo)) * ih;
      let y2 = null;
      if (bars.length) {
        const bv = bars.flatMap((b) => b.pts.map((p) => p.v));
        const sc = niceScale(Math.min(0, ...bv), Math.max(0, ...bv), Math.max(2, Math.floor(ih / 55)));
        y2 = { sc, f: (v) => P.t + ih - ((v - sc.lo) / (sc.hi - sc.lo)) * ih };
      }

      const clipId = `dashClip-${id}`;
      let g = `<defs><clipPath id="${clipId}"><rect x="${P.l}" y="${P.t}" width="${iw}" height="${ih}"/></clipPath></defs>`;
      ys.ticks.forEach((t) => {
        g += `<line x1="${P.l}" y1="${f1(y(t))}" x2="${w - P.r}" y2="${f1(y(t))}" stroke="${t === 0 ? COLOR.zero : COLOR.grid}"/>`;
        g += txt(P.l - 7, y(t) + 3.5, dNum(t, ys.dec), { anchor: 'end', mono: true });
      });
      if (y2) {
        y2.sc.ticks.forEach((t) => g += txt(w - P.r + 7, y2.f(t) + 3.5, dNum(t, y2.sc.dec), { mono: true }));
        g += txt(w - 12, P.t + ih / 2, 'inflação do mês (%)', { anchor: 'middle', rotate: 90 });
      }
      const nx = Math.max(2, Math.floor(iw / 90));
      for (let i = 0; i <= nx; i += 1) {
        const ms = x0 + (span * i) / nx;
        g += txt(x(ms), P.t + ih + 15, fmtTick(ms, span), {
          anchor: i === 0 ? 'start' : (i === nx ? 'end' : 'middle'), mono: true,
        });
      }
      if (cfg.yTitle) g += txt(12, P.t + ih / 2, cfg.yTitle, { anchor: 'middle', rotate: -90 });

      // barras (eixo da direita), atrás das linhas
      let bw = 14;
      if (bars.length) {
        let gap = Infinity;
        bars.forEach((b) => b.pts.forEach((p, i) => {
          if (i) gap = Math.min(gap, x(p.ms) - x(b.pts[i - 1].ms));
        }));
        if (Number.isFinite(gap)) bw = clamp(gap * 0.55, 2, 40);
      }
      g += `<g clip-path="url(#${clipId})">`;
      bars.forEach((b) => b.pts.forEach((p) => {
        const top = y2.f(Math.max(0, p.v));
        const bot = y2.f(Math.min(0, p.v));
        g += `<rect x="${f1(x(p.ms) - bw / 2)}" y="${f1(top)}" width="${f1(bw)}" height="${f1(Math.max(1, bot - top))}" fill="rgba(45,212,167,.45)"/>`;
      }));
      if (cfg.zeroLabel && ys.lo <= 0 && ys.hi >= 0) {
        g += `<line x1="${P.l}" y1="${f1(y(0))}" x2="${w - P.r}" y2="${f1(y(0))}" stroke="${COLOR.zero}" stroke-dasharray="2 3"/>`;
      }
      lists.forEach((l) => {
        [[l.old, true], [l.live, false]].forEach(([list, dashed]) => {
          if (!list.length) return;
          const segs = segmentsOf(list);
          const count = segs.reduce((n, sg) => n + sg.length, 0);
          segs.forEach((sg) => {
            if (sg.length > 1) {
              const d = sg.map((p, i) => `${i ? 'L' : 'M'}${f1(x(p.ms))},${f1(y(p.v))}`).join('');
              g += `<path d="${d}" fill="none" stroke="${dEsc(l.s.color)}" stroke-width="${dashed ? 1.6 : 2.2}" ` +
                `stroke-linejoin="round" stroke-linecap="round"${dashed ? ' stroke-dasharray="5 4" opacity=".8"' : ''}/>`;
            }
            if (sg.length === 1 || count < 3) {
              sg.forEach((p) => {
                g += `<circle cx="${f1(x(p.ms))}" cy="${f1(y(p.v))}" r="3" fill="${dEsc(l.s.color)}"/>`;
              });
            }
          });
        });
      });
      g += '</g>';
      if (cfg.zeroLabel && ys.lo <= 0 && ys.hi >= 0) {
        g += txt(P.l + 4, y(0) - 4, cfg.zeroLabel);
      }
      if (cfg.showLegend) {
        let lx = P.l;
        [...lists.map((l) => [l.s.color, l.s.label]), ...bars.map((b) => ['rgba(45,212,167,.6)', b.b.label])]
          .forEach(([c, name]) => {
            g += `<rect x="${f1(lx)}" y="8" width="12" height="4" rx="2" fill="${dEsc(c)}"/>`;
            g += txt(lx + 17, 13, name, { size: 10.5, fill: COLOR.txt });
            lx += 17 + String(name).length * 6.2 + 16;
          });
      }
      g += `<line class="dash-cross" x1="0" y1="${P.t}" x2="0" y2="${P.t + ih}" stroke="${COLOR.dim}" ` +
        'stroke-dasharray="3 3" style="display:none"/><g class="dash-dots"></g>';
      g += `<rect class="dash-overlay" x="${P.l}" y="${P.t}" width="${iw}" height="${ih}" fill="transparent" style="touch-action:pan-y"/>`;
      el.innerHTML = svgDoc(w, h, label, g);

      const svg = el.querySelector('svg');
      const cross = svg.querySelector('.dash-cross');
      const dots = svg.querySelector('.dash-dots');
      const times = [...new Set(stamps)].sort((a, b) => a - b).map((ms) => ({ ms }));
      const leave = () => {
        cross.style.display = 'none';
        dots.innerHTML = '';
        hideTip(el);
      };
      svg.addEventListener('pointerleave', leave);
      svg.addEventListener('pointermove', (ev) => {
        const r = svg.getBoundingClientRect();
        const mx = ev.clientX - r.left;
        if (mx < P.l || mx > P.l + iw) { leave(); return; }
        const snap = nearest(times, x0 + ((mx - P.l) / iw) * span);
        if (!snap) { leave(); return; }
        const rows = [];
        let dotsHtml = '';
        lists.forEach((l) => {
          const p = nearest(l.all, snap.ms);
          if (!p || Math.abs(x(p.ms) - x(snap.ms)) > 24) return;
          const rebuilt = l.isRebuilt(p);
          const unit = l.s.unit && l.s.unit !== '0-100' ? l.s.unit : '';
          rows.push(tipRow(l.s.color, l.s.label, dNum(p.v, l.s.decimals ?? 1),
            [unit, rebuilt ? 'recalculado' : ''].filter(Boolean).join(' · ')));
          dotsHtml += `<circle cx="${f1(x(p.ms))}" cy="${f1(y(p.v))}" r="3.6" fill="${dEsc(l.s.color)}" stroke="#0b0f17" stroke-width="1.5"/>`;
        });
        bars.forEach((b) => {
          const p = nearest(b.pts, snap.ms);
          if (!p || Math.abs(x(p.ms) - x(snap.ms)) > Math.max(24, bw)) return;
          rows.push(tipRow('rgba(45,212,167,.6)', b.b.label, dPct(p.v, 2)));
        });
        if (!rows.length) { leave(); return; }
        const cx = x(snap.ms);
        cross.setAttribute('x1', f1(cx));
        cross.setAttribute('x2', f1(cx));
        cross.style.display = '';
        dots.innerHTML = dotsHtml;
        showTip(el, `<div class="tip-head">${dEsc(fmtTipDate(snap.ms))}</div>${rows.join('')}`, ev);
      });
    });
  }

  function onSnapshot(snap) {
    const changed = !DASH.snapshot || DASH.snapshot.generated_at !== snap.generated_at;
    DASH.snapshot = snap;
    if (changed && DASH.active) refresh();
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
