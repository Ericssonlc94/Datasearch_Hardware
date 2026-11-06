/* prices.js — aba Preços: preço na loja por faixa (sub-aba Produtos no
   mercado), a partir de GET /api/prices.
   O brand_view da API não é exibido. Só busca
   quando a aba está aberta; o ranking de estimativas (app.js) não depende daqui.
   Todo texto vindo do servidor passa por pEsc(); link só com storeUrl(). */

(function () {
  const P = {
    active: false,
    data: null,     // último JSON 200 de /api/prices
    gen: null,      // generated_at do snapshot para o qual o dado vale
    snapGen: null,  // generated_at do snapshot atual do painel
    inflight: null,
    token: 0,
  };

  const p$ = (id) => document.getElementById(id);

  function pEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }

  // K16: link de oferta só para https://www.kabum.com.br, sem usuário,
  // senha ou porta. Qualquer outra coisa vira texto sem link.
  function storeUrl(raw) {
    try {
      const u = new URL(String(raw ?? ''));
      if (u.protocol !== 'https:') return null;
      if (u.hostname !== 'www.kabum.com.br') return null;
      if (u.username || u.password || u.port) return null;
      return u.href;
    } catch {
      return null;
    }
  }

  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

  const brl = (v) => (num(v) === null ? '—'
    : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }));

  const brlRound = (v) => (num(v) === null ? null
    : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }));

  // Mesmo formato do fmtPct do app.js (ponto decimal), com sinal explícito.
  const pct = (v, digits = 1) => (num(v) === null ? '—'
    : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)}%`);

  // Principal = preço cheio (T24i): é o parcelado em até 10× sem juros e não
  // muda na oferta relâmpago. O à vista vai na 2ª linha.
  const priceMain = (v) => (num(v) === null
    ? '<div class="price-main is-empty">sem preço hoje</div>'
    : `<div class="price-main">${brl(v)} <span>preço cheio</span></div>`);

  const cashLine = (v) => (num(v) === null ? ''
    : `<div class="price-full">${brl(v)} à vista</div>`);

  const STORE_LABEL = 'Preço na KaBuM (preço cheio) · parcelado em até 10× sem juros';

  const dir = (v) => (num(v) === null ? 'flat' : v > 0.05 ? 'up' : v < -0.05 ? 'down' : 'flat');

  // Classe por código de aviso: allowlist, o code nunca vai direto para o HTML.
  const WARN_CLASS = {
    partial: 'stale',
    brand_only: 'stale',
    suspect: 'stale',
    no_price: 'unavailable',
    category_unpublished: 'unavailable',
    no_competitor: 'neutral',
    no_model: 'neutral',
    marketplace: 'neutral',
  };

  const OFFER_STATUS = {
    valid: { text: 'válido', cls: 'observed' },
    suspect: { text: 'suspeito', cls: 'stale' },
    unavailable: { text: 'indisponível', cls: 'unavailable' },
    out_of_range: { text: 'fora da faixa', cls: 'stale' },
    flash: { text: 'relâmpago', cls: 'stale' },
  };

  function warningsHtml(list) {
    return (list || [])
      .map((w) => `<span class="badge ${WARN_CLASS[w && w.code] || 'stale'}">${pEsc(w && w.text)}</span>`)
      .join(' ');
  }

  function listingsText(l) {
    if (!l || num(l.tracked) === null) return '';
    const valid = num(l.valid) ?? 0;
    // T35: a cesta é por modelo; tracked/valid contam modelos, não anúncios.
    return `${valid} de ${l.tracked} modelo${l.tracked === 1 ? '' : 's'} com preço`;
  }

  function rangeText(r) {
    if (!r) return '';
    const lo = brlRound(r.min);
    const hi = brlRound(r.max);
    if (lo && hi) return `${lo} a ${hi}`;
    if (lo) return `acima de ${lo}`;
    if (hi) return `até ${hi}`;
    return '';
  }

  /* ---------------- estado vazio e rótulo ---------------- */

  function setMessage(text) {
    const el = p$('storeProducts');
    if (el) el.innerHTML = `<p class="price-empty">${pEsc(text)}</p>`;
  }

  function renderLabel(src) {
    const tracked = src && num(src.listings_tracked);
    const head = pEsc(STORE_LABEL) + (tracked
      ? ` · ${tracked} modelo${tracked === 1 ? '' : 's'} acompanhado${tracked === 1 ? '' : 's'} por dia, numa loja só; não é média de mercado`
      : '');
    let when = '';
    if (src && src.as_of) {
      const d = new Date(src.as_of);
      if (!Number.isNaN(d.getTime())) {
        when = ` <span class="price-asof">coleta de ${pEsc(d.toLocaleString('pt-BR', {
          day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
        }))}</span>`;
      }
    }
    document.querySelectorAll('.store-label').forEach((el) => { el.innerHTML = head + when; });
  }

  /* ---------------- Produtos: categoria × faixa ---------------- */

  function ipcaHtml(ipca) {
    if (!ipca || !ipca.subitem) {
      return '<p class="price-ipca">IPCA <span class="badge stale">sem subitem</span></p>';
    }
    const bits = [pEsc(ipca.label || `subitem ${ipca.subitem}`)];
    if (ipca.period) bits.push(pEsc(ipca.period));
    if (num(ipca.change_12m_pct) !== null) bits.push(`${pct(ipca.change_12m_pct)} em 12 meses`);
    const proxy = ipca.is_proxy
      ? ' <span class="badge stale" title="O IBGE não tem subitem só desta categoria; usamos o mais próximo.">proxy</span>'
      : '';
    return `<p class="price-ipca">IPCA · ${bits.join(' · ')}${proxy}</p>`;
  }

  function offerHtml(o) {
    const href = storeUrl(o && o.url);
    const name = pEsc((o && o.name) || 'anúncio');
    const link = href
      ? `<a href="${pEsc(href)}" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">${name}</a>`
      : `<span>${name}</span>`;
    const st = OFFER_STATUS[o && o.status] || { text: (o && o.status) || '', cls: 'stale' };
    const badge = st.text ? ` <span class="badge ${st.cls}">${pEsc(st.text)}</span>` : '';
    // Relâmpago é só selo: o cheio, que entra na conta, não muda na campanha.
    const flash = o && o.flash_offer
      ? ` <span class="badge stale">relâmpago${num(o.flash_price_brl) === null ? '' : ' ' + brl(o.flash_price_brl)}</span>`
      : '';
    // Marketplace (T33): o seller vem da loja; entra só como texto escapado (K18).
    const market = o && o.marketplace
      ? ` <span class="badge neutral">marketplace${o.seller ? ' · vendido por ' + pEsc(o.seller) : ''}</span>`
      : '';
    return `<li>${link}<span class="price-offer-meta">${brl(o && o.price_full_brl)} cheio${badge}${flash}${market}</span></li>`;
  }

  const MODEL_STATUS = {
    no_price: { text: 'sem preço', cls: 'unavailable' },
    no_data: { text: 'sem dados', cls: 'unavailable' },
  };

  // T35: um item por modelo (mediana), com até 3 anúncios de referência.
  // As refs vêm de offers[] pelo model_key, porque lá a url já vem montada.
  function modelHtml(m, offers) {
    const name = pEsc([m.brand, m.model].filter(Boolean).join(' ') || m.key || 'modelo');
    const st = MODEL_STATUS[m.status];
    const badge = st ? ` <span class="badge ${st.cls}">${pEsc(st.text)}</span>` : '';
    const price = num(m.price_full_brl) === null ? '' : `${brl(m.price_full_brl)} cheio (mediana)`;
    const refs = offers.filter((o) => o.model_key && o.model_key === m.key).slice(0, 3);
    const refList = refs.length ? `<ul>${refs.map(offerHtml).join('')}</ul>` : '';
    return `<li><span>${name}</span><span class="price-offer-meta">${price}${badge}</span>${refList}</li>`;
  }

  function tierHtml(tierMeta, t) {
    const label = pEsc(tierMeta.label || tierMeta.key);
    if (!t) {
      return `<div class="price-tier is-empty">
        <div class="price-tier-head"><span class="price-tier-name">${label}</span></div>
        <p class="price-empty">sem faixa na cesta</p>
      </div>`;
    }
    const range = rangeText(t.range_brl);
    const offers = (t.offers || []).filter(Boolean);
    const models = (t.models || []).filter(Boolean);
    const list = models.length ? models.map((m) => modelHtml(m, offers)).join('') : offers.map(offerHtml).join('');
    const offersBlock = list
      ? `<details class="price-offers">
          <summary>${models.length ? `Modelos (${models.length})` : `Anúncios (${offers.length})`}</summary>
          <ul>${list}</ul>
        </details>`
      : '';
    const chg = num(t.change_30d_pct) === null
      ? '<span class="price-chg flat">sem variação de 30 dias</span>'
      : `<span class="price-chg ${dir(t.change_30d_pct)}">${pct(t.change_30d_pct)} em 30 dias</span>`;
    return `<div class="price-tier">
      <div class="price-tier-head">
        <span class="price-tier-name">${label}</span>
        ${range ? `<span class="price-range">${pEsc(range)}</span>` : ''}
      </div>
      ${priceMain(t.price_full_brl)}
      ${cashLine(t.price_cash_brl)}
      ${chg}
      <div class="price-listings">${pEsc(listingsText(t.listings))}</div>
      ${(t.warnings || []).length ? `<div class="price-warn">${warningsHtml(t.warnings)}</div>` : ''}
      ${offersBlock}
    </div>`;
  }

  // Ordena as categorias como o ranking de Produtos; as sem posição vão ao fim.
  function byRankOrder(cats) {
    const pos = new Map((P.order || []).map((k, i) => [k, i]));
    const at = (c) => (pos.has(c.key) ? pos.get(c.key) : Infinity);
    return [...cats].sort((a, b) => at(a) - at(b));
  }

  function renderProducts(d) {
    const el = p$('storeProducts');
    if (!el) return;
    const tiers = d.tiers || [];
    const cats = byRankOrder(d.categories || []);
    if (!cats.length) {
      el.innerHTML = '<p class="price-empty">Nenhuma categoria com preço na loja hoje.</p>';
      return;
    }
    el.innerHTML = cats.map((c) => {
      // Celular e notebook (e todas, com a loja desligada): só o IPCA.
      if (c.ipca_only || !tiers.length) {
        return `<article class="price-cat is-ipca-only">
          <header class="price-cat-head">
            <h4>${pEsc(c.label || c.key)}</h4>
            ${ipcaHtml(c.ipca)}
          </header>
        </article>`;
      }
      const byTier = new Map((c.tiers || []).map((t) => [t.tier, t]));
      const unpublished = c.published === false;
      return `<article class="price-cat${unpublished ? ' is-unpublished' : ''}">
        <header class="price-cat-head">
          <h4>${pEsc(c.label || c.key)}</h4>
          ${ipcaHtml(c.ipca)}
          ${(c.warnings || []).length ? `<div class="price-warn">${warningsHtml(c.warnings)}</div>` : ''}
        </header>
        <div class="price-tiers">${tiers.map((tm) => tierHtml(tm, byTier.get(tm.key))).join('')}</div>
      </article>`;
    }).join('');
  }

  /* ---------------- ciclo ---------------- */

  function render(d) {
    renderLabel(d.source);
    if (d.source && d.source.status === 'disabled') {
      const why = d.source.status_reason ? ` ${d.source.status_reason}` : '';
      setMessage(`A coleta de preços da loja está desligada neste servidor.${why}`);
      // O IPCA do subitem continua: é dado oficial e não depende da loja.
      const el = p$('storeProducts');
      if (el && (d.categories || []).length) {
        const msg = el.innerHTML;
        renderProducts({ ...d, tiers: [] });
        el.insertAdjacentHTML('afterbegin', msg);
      }
      return;
    }
    renderProducts(d);
  }

  async function load() {
    const token = ++P.token;
    const gen = P.snapGen;
    setMessage('Carregando preços da loja…');
    try {
      const res = await fetch('/api/prices', { cache: 'no-store' });
      if (token !== P.token) return;
      if (res.status === 503) {
        renderLabel(null);
        setMessage('Os preços da loja aparecem depois da primeira coleta.');
        return;
      }
      if (res.status === 404) {
        renderLabel(null);
        setMessage('Os preços da loja ainda não estão disponíveis neste servidor.');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      if (token !== P.token) return;
      P.data = d;
      P.gen = gen;
      render(d);
    } catch (err) {
      if (token !== P.token) return;
      renderLabel(null);
      setMessage(`Não foi possível carregar os preços da loja agora (${err.message}).`);
    }
  }

  function activate() {
    P.active = true;
    if (P.data && P.gen === P.snapGen) render(P.data);
    else load();
  }

  function deactivate() {
    P.active = false;
  }

  function onSnapshot(snap) {
    P.snapGen = snap && snap.generated_at;
    // Mesma ordem da sub-aba Produtos: estimativa Brasil · 30 dias, maior primeiro.
    P.order = [...((snap && snap.ranking) || [])]
      .sort((a, b) => (Number(b.projected_brazil_30d_pct) || 0) - (Number(a.projected_brazil_30d_pct) || 0))
      .map((it) => it.key);
    if (P.active && P.gen !== P.snapGen) load();
  }

  window.Prices = { activate, deactivate, onSnapshot, storeUrl };
})();
