"""Contrato estático entre HTML e JS — pega id quebrado sem abrir navegador.

Não substitui um teste visual, mas cobre a classe de erro mais chata: um
`$('algum-id')` que não existe no HTML (ou um painel de aba sem botão).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
CHARTS_JS = (STATIC / "charts.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _ids() -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', HTML))


def _referenced_ids(source: str) -> set[str]:
    return set(re.findall(r"\$\('([^']+)'\)", source))


def test_todo_id_usado_no_js_existe_no_html():
    faltando = _referenced_ids(APP_JS) - _ids()
    assert not faltando, f"id(s) referenciado(s) no JS e ausente(s) no HTML: {sorted(faltando)}"


def test_toda_aba_tem_botao_e_painel():
    botoes = set(re.findall(r'data-tab="([^"]+)"', HTML))
    paineis = set(re.findall(r'id="tab-([^"]+)"', HTML))
    assert botoes == paineis, f"abas sem par botão/painel: {botoes ^ paineis}"


def test_aba_tendencia_tem_os_dois_graficos_e_periodos():
    for element_id in (
        "trendChart",
        "trendCatChart",
        "trendLegend",
        "trendCatLegend",
        "trendSeriesPicker",
        "trendCategory",
        "trendMeta",
        "trendCatMeta",
        "trendNotice",
        "trendTip",
        "trendCatTip",
    ):
        assert f'id="{element_id}"' in HTML, f"faltou #{element_id}"
    for period in ("24h", "7d", "30d", "90d", "1y"):
        assert f'data-range="{period}"' in HTML, f"faltou o botão de período {period}"


def test_charts_js_carrega_antes_do_app_js():
    i_charts = HTML.find("/static/charts.js")
    i_app = HTML.find("/static/app.js")
    assert i_charts != -1 and i_app != -1
    assert i_charts < i_app, "app.js usa trendChart(); charts.js precisa vir antes"


def test_icones_carregam_antes_do_app_js():
    i_icons = HTML.find("/static/icons.js")
    i_app = HTML.find("/static/app.js")
    assert i_icons != -1 and i_app != -1
    assert i_icons < i_app, "app.js usa window.Icons; icons.js precisa vir antes"
    icons_js = (STATIC / "icons.js").read_text(encoding="utf-8")
    assert "window.Icons" in icons_js
    assert "gpu" in icons_js and "motherboard" in icons_js and "console" in icons_js


def test_interface_nao_usa_emoji():
    emoji = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
    paths = [
        STATIC / "index.html",
        STATIC / "app.js",
        STATIC / "charts.js",
        STATIC / "dashboard.js",
        STATIC / "icons.js",
        ROOT / "app" / "domain" / "catalog.py",
    ]
    for path in paths:
        found = emoji.findall(path.read_text(encoding="utf-8"))
        assert not found, f"emoji encontrado em {path.name}: {found[:5]}"


def test_charts_js_nao_quebra_linha_sem_lacuna():
    """Sem nulls, a linha conecta; o calendário (fim de semana) não é lacuna."""
    assert "hasNulls" in CHARTS_JS
    assert "median * 4" in CHARTS_JS
    assert "trend-cross" in CHARTS_JS
    assert "tabindex" in CHARTS_JS


def test_drill_down_de_sinal_aponta_para_a_aba_de_tendencia():
    assert 'data-signal=' in APP_JS
    assert "signal.${key}" in APP_JS or "signal.${" in APP_JS
    assert "activateTab('tendencia')" in APP_JS


def test_aba_visao_geral_tem_leitura_simples_e_navegacao():
    for element_id in (
        "simpleLead",
        "simpleScore",
        "simpleScoreLabel",
        "simpleBrazil",
        "simpleReasons",
        "simpleCategories",
        "simpleWatch",
    ):
        assert f'id="{element_id}"' in HTML, f"faltou #{element_id}"
    assert 'data-goto="tendencia"' in HTML
    assert 'data-goto="overview"' in HTML
    assert 'data-goto="tecnico"' in HTML
    # A aba simples é a porta de entrada, mas não substitui os detalhes.
    assert 'data-tab="visao-geral"' in HTML
    assert 'data-tab="overview"' in HTML
    assert "simpleScore" in APP_JS and "simpleReasons" in APP_JS
    # Link antigo continua funcionando sem mudar a URL de quem já o salvou.
    assert "entenda: 'visao-geral'" in APP_JS
    assert "let activeTab = 'visao-geral'" in APP_JS


def test_detalhes_usa_lista_compacta_e_detalhes_expansiveis():
    assert '<details class="driver-more">' in APP_JS
    assert 'class="driver-more"' in APP_JS
    assert "Ver sinais e fontes" in APP_JS
    assert "#tab-overview .block" in (STATIC / "editorial.css").read_text(encoding="utf-8")
    hero_css = (STATIC / "editorial.css").read_text(encoding="utf-8")
    assert "clamp(32px, 4.4vw, 48px)" in hero_css


def test_entenda_usa_os_limiares_reais_e_nao_promete_queda():
    # Os limiares do texto precisam bater com _iph_label() em analyzer.py.
    assert "47 a 52" in HTML
    assert "60 a 71" in HTML
    assert "45 a 58" not in HTML
    assert "A pressão está baixa; isso não significa queda automática." in APP_JS
    assert "estimativa nossa" in HTML
    assert "dado oficial" in HTML


def test_aba_tecnico_concentra_metodologia_fontes_e_limites():
    assert 'data-tab="tecnico"' in HTML
    assert 'id="tab-tecnico"' in HTML
    assert 'id="interpretation"' in HTML
    assert 'id="sources"' in HTML
    assert "/api/methodology" in HTML
    assert "Não é um índice oficial" in HTML
    assert "Fontes e frescor do dado" in HTML
    assert "Limites do modelo" in HTML


def test_tendencia_oferece_tudo_e_so_libera_periodos_cobertos():
    assert 'data-range="all"' in HTML
    assert 'id="trendHistory"' in HTML
    assert 'id="trendSummary"' in HTML
    assert "first_observation" in APP_JS
    assert "rangeAvailable" in APP_JS
    assert "btn.disabled = !ok" in APP_JS
    assert "todo o histórico" in APP_JS


def test_tendencia_nao_espreme_periodos_maiores_que_o_historico():
    # O eixo só acompanha o trecho com dados em "Tudo". Nos demais períodos,
    # a janela pedida manda no desenho e o botão fica indisponível se o banco
    # ainda não cobre o período.
    assert "zoomToData" in CHARTS_JS
    assert "dataSpan < requestedSpan" not in CHARTS_JS
    assert "Ainda não há" in APP_JS


def test_precos_prioriza_a_estimativa_brasil_e_o_detalhe_expansivel():
    assert 'id="rankingSummary"' in HTML
    assert 'class="rank-list-head"' in HTML
    assert "rank-value-num" in APP_JS
    assert '<details class="rank-item"' in APP_JS
    assert "rank-detail-body" in APP_JS


def test_camada_editorial_carrega_depois_da_base():
    i_base = HTML.find("/static/styles.css")
    i_editorial = HTML.find("/static/editorial.css")
    assert i_base != -1 and i_editorial != -1
    assert i_base < i_editorial, "editorial.css precisa vir depois de styles.css"
    css = (STATIC / "editorial.css").read_text(encoding="utf-8")
    assert "--display:" in css
    assert ".rank-row" in css
    assert "prefers-reduced-motion" in css


def test_api_history_aceita_tudo_com_primeiro_ponto_real():
    assert 'is_all = range_ == "all"' in MAIN
    assert 'description="all | 24h | 7d | 30d | 90d | 1y"' in MAIN
    assert "history.first_ts" in MAIN
    assert '"first_observation"' in MAIN


def test_loading_mostra_percentual_da_coleta():
    for element_id in (
        "loadingTitle",
        "loadingMeter",
        "loadingBar",
        "loadingPct",
        "loadingCount",
    ):
        assert f'id="{element_id}"' in HTML, f"faltou #{element_id}"
    # O rodapé da tela de busca saiu (T20c): nem o elemento nem quem o preenchia.
    assert 'id="loadingHint"' not in HTML
    assert "loadingHint" not in APP_JS
    assert 'role="progressbar"' in HTML
    assert 'aria-valuenow="0"' in HTML
    assert "/api/progress" in APP_JS
    assert "setLoadingProgress" in APP_JS
    assert "loadingBar" in APP_JS
    # O endpoint é de operação e não deve exigir snapshot pronto.
    assert 'app.get("/api/progress"' in MAIN


# ---------------- dashboard SVG ----------------

DASH_JS = (STATIC / "dashboard.js").read_text(encoding="utf-8")


def test_todo_id_usado_no_dashboard_existe_no_html():
    referenciados = set(re.findall(r"d\$\('([^']+)'\)", DASH_JS))
    faltando = referenciados - _ids()
    assert not faltando, f"id(s) do dashboard ausente(s) no HTML: {sorted(faltando)}"


def test_aba_dashboard_tem_kpis_e_seis_graficos():
    for element_id in (
        "dashRanges",
        "dashStatus",
        "dashKpis",
        "dashIndex",
        "dashSupply",
        "dashRanking",
        "dashCategory",
        "dashCategoryChart",
        "dashCategorySrc",
        "dashRadar",
        "dashScatter",
        "dashNote",
    ):
        assert f'id="{element_id}"' in HTML, f"faltou #{element_id}"
    for period in ("24h", "7d", "30d", "90d", "1y"):
        assert f'data-range="{period}"' in HTML


def test_dashboard_js_carrega_antes_do_app_js():
    i_dash = HTML.find("/static/dashboard.js")
    i_app = HTML.find("/static/app.js")
    assert i_dash != -1 and i_app != -1
    assert i_dash < i_app, "app.js chama window.Dash; dashboard.js precisa vir antes"


def test_dashboard_e_svg_inline_sem_plotly_nem_cdn():
    for texto in (DASH_JS, APP_JS, HTML):
        assert "plotly" not in texto.lower()
    assert "cdn." not in DASH_JS
    assert "document.createElement('script')" not in DASH_JS
    assert "/static/vendor" not in HTML
    # cada gráfico é um <svg role=img> com aria-label
    assert 'role="img"' in DASH_JS
    assert "aria-label" in DASH_JS
    assert "<title>" not in DASH_JS  # balão nativo duplicaria o tooltip
    assert "ResizeObserver" in DASH_JS


def test_dashboard_nao_interpola_lacuna_e_tem_drill_down():
    # lacuna (null) quebra a linha em segmentos: nunca vira zero
    assert "segmentsOf" in DASH_JS
    assert "selectCategory" in DASH_JS
    assert "dash:category" in DASH_JS
    assert "dash-hit" in DASH_JS
    # o eixo duplo da fila: fila à esquerda, inflação à direita
    assert "y2" in DASH_JS


def test_dashboard_usa_series_que_existem_no_catalogo():
    from app.domain.catalog import CATEGORIES
    from app.domain.series import SERIES_BY_KEY

    for key in (
        "iph",
        "iph_br",
        "coverage",
        "supply.queue",
        "supply.capex_ttm",
        "supply.inventory_ratio",
        "supply.diversion",
    ):
        assert key in SERIES_BY_KEY, key
    for cat in CATEGORIES:
        assert f"cat.{cat.key}.proj30_br" in SERIES_BY_KEY, cat.key
        assert f"cat.{cat.key}.proj30_global" in SERIES_BY_KEY, cat.key


def test_evolucao_abre_em_30_dias_e_marca_o_trecho_reconstruido():
    assert "['30d', '7d', '24h'].find(" in APP_JS
    assert "rebuiltUntil: s.reconstructed_until" in APP_JS
    assert "Trecho tracejado" in APP_JS
    assert '"reconstructed_until": rebuilt.get(key)' in MAIN
    assert '"rebuilt_days": rebuilt_days.get(key, [])' in MAIN
    assert "trend-rebuilt" in CHARTS_JS and "stroke-dasharray" in CHARTS_JS
    # 30 dias em bucket diário, alinhado com um ponto reconstruído por dia.
    assert '"30d": 86_400' in MAIN


def test_estimativas_usam_horizonte_de_30_dias():
    dashboard = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    for name, text in (("index.html", HTML), ("app.js", APP_JS), ("dashboard.js", dashboard)):
        assert "_90d_pct" not in text, name
        assert "estimativa de 90 dias" not in text.lower(), name
        assert "próximos 90 dias" not in text, name
    assert "Brasil · 30 dias" in APP_JS


def test_noticias_paginadas_em_5_ate_3_paginas():
    assert 'id="headlinesPager"' in HTML
    assert "const HEADLINES_PER_PAGE = 5;" in APP_JS
    assert "const HEADLINES_MAX_PAGES = 3;" in APP_JS
    assert "bindHeadlinePager();" in APP_JS
    assert ".pager-btn" in (STATIC / "editorial.css").read_text(encoding="utf-8")
    news_service = (ROOT / "app" / "services" / "news.py").read_text(encoding="utf-8")
    assert "HEADLINES_LIMIT = 15" in news_service


def test_ipca_por_item_mostra_nome_inteiro():
    assert '<ul class="ipca-list" id="ipcaBars"' in HTML
    assert "renderIpcaList($('ipcaBars'), bars);" in APP_JS
    css = (STATIC / "editorial.css").read_text(encoding="utf-8")
    assert ".ipca-label" in css and "overflow-wrap: anywhere" in css


def test_menus_select_legiveis_no_tema_escuro():
    css = (STATIC / "editorial.css").read_text(encoding="utf-8")
    assert "color-scheme: dark;" in css
    assert "select option," in css and "select optgroup {" in css
    # Fundo sólido: a lista aberta herda a cor do <select> em vários navegadores.
    assert ".dash-select { background-color: var(--bg-2); }" in css


def test_textos_da_evolucao_por_produto_seguem_o_periodo():
    assert 'id="trendCatLead"' in HTML
    assert "renderCatTexts(series, catData, catSvg._trend?.zoomed);" in APP_JS
    assert "rangePhrase(catData.range)" in APP_JS
    # O texto fixo antigo, que sempre dizia 30 dias, saiu.
    assert "a estimativa cobre 30 dias a partir de hoje" not in APP_JS
    for phrase in ("nas últimas 24 horas", "nos últimos 7 dias", "nos últimos 90 dias", "no último ano"):
        assert phrase in APP_JS


def test_cartao_do_dolar_explica_movimento_e_impacto():
    assert "fxExplanationHtml(b.fx_explanation)" in APP_JS
    assert "Por que o dólar se mexeu" in APP_JS
    assert "O que isso faz com o preço" in APP_JS
    assert ".fx-why" in (STATIC / "editorial.css").read_text(encoding="utf-8")


def test_primeira_abertura_mostra_so_a_tela_de_busca():
    # A página nasce em modo "booting": só a tela de busca, em tela cheia.
    assert '<body class="booting">' in HTML
    css = (STATIC / "editorial.css").read_text(encoding="utf-8")
    regra = re.search(r"((?:body\.booting [^,{]+,\s*)*body\.booting [^,{]+)\{\s*display:\s*none;", css)
    assert regra, "editorial.css sem regra que esconde o painel em body.booting"
    escondidos = {s.strip().removeprefix("body.booting ").strip() for s in regra.group(1).split(",")}
    assert {".topbar", ".tabs", ".tabpanel", "footer"} <= escondidos
    # O primeiro render libera o painel; a falha oferece nova tentativa.
    render = re.search(r"^function render\(.*?^\}", APP_JS, re.S | re.M).group(0)
    assert "document.body.classList.remove('booting');" in render
    assert 'id="retryBtn"' in HTML
    assert "$('retryBtn').addEventListener('click', () => load(true));" in APP_JS


def test_ponto_reconstruido_antes_do_marco_do_modelo_entra_no_grafico():
    # model_since descarta ponto ao vivo da conta antiga, mas não o dia
    # reconstruído (já recalculado com a conta atual).
    trecho = APP_JS[APP_JS.index("function currentPoints"):]
    trecho = trecho[:trecho.index("\n}\n")]
    assert "rebuilt_days" in trecho and ">= since" in trecho
