# Relatório — QA

## T04 — testes das fontes novas (2026-11-04): **feito**

Arquivos novos, todos offline (`get_json` ou transporte HTTP simulados):

| Arquivo | Testes | O que cobre |
| --- | --- | --- |
| `tests/test_fedreg.py` | 16 | aperto +1, revisão +0,5, alívio −1 (inclui o plural "Removals"), regra fora do tema → `None`, soma diária com 0 em dia vazio, coleta com parâmetros do BIS, resposta sem `results` falha visível |
| `tests/test_usgs.py` | 4 | limites 5,5 e 150 km, pedido com esses limites para cada um dos seis polos, pico diário = maior magnitude, 0 sem evento, evento fora da janela ignorado, mesmo evento visto por dois polos conta uma vez |
| `tests/test_sec.py` | 6 | Q2 = H1 − Q1 e Q3 = 9M − H1, trimestre publicado direto vence o derivado, dedup por `filed` (fluxo e estoque), anual/curto/acumulado que cai descartados, agregação por trimestre-calendário e TTM com cobertura mínima |
| `tests/test_http_challenge.py` | 10 | `ChallengeDetected` em `get_json`, `post_json` e `get_text`; HTML comum ≠ desafio; resposta legítima passa; marcador após 4 KB não dispara; 403/429/503 com desafio não repete (1 pedido). Cliente via `http.build_client(transport=MockTransport)` |

Defeitos encontrados (Dados) e já corrigidos na T09b:

1. `app/providers/fedreg.py` — `_EASE` não casava o plural "removals"; o título
   caía como revisão (+0,5).
2. `app/http.py` — `ChallengeDetected` em 403/429/503 era capturado pelo
   `except Exception`, repetido 3 vezes e embrulhado em `FetchError` genérico.

Os 4 marcadores `xfail(strict=True)` que documentavam esses defeitos foram
retirados depois da correção. Suíte: `.venv/bin/python -m pytest tests/ -q`
→ 210 passed.

## T03 / T16a — painel no navegador (2026-11-05): **feito, com 4 defeitos**

Navegador: **Brave 155.0.8059.85** (`/opt/brave-origin-bin/brave-origin`),
headless pelo Playwright, CSP do servidor ativa; servidor de teste próprio na
porta 8011 com cópia do `history.db`. Larguras 1280, 900 e 560 px.
Capturas (pasta temporária da sessão): `/tmp/claude-1000/-mnt-Dados-Dev-datasearch-hardware/18ac3ba8-6b7a-48df-8187-03e588aaaa78/scratchpad/qa/shots/`.

**Funciona:** as sete abas abrem nas três larguras; tela de busca em tela
cheia antes do primeiro snapshot; nenhum `pageerror`; os seis gráficos da aba
Gráficos renderizam com dados; **nenhum erro de eval/CSP do Plotly** (o
`new Function` não é acionado, então `'unsafe-eval'` não é necessário); foco
visível nas abas (contorno 2 px na cor de destaque); Tab + Enter troca de aba;
`lang="pt-BR"`, um `h1`, nenhum botão sem nome, nenhum select sem rótulo;
o leitor de tela recebe `tablist` com sete `tab` e a ativa como `selected`.

| # | Defeito | Onde aparece | Causa e arquivo provável (Frontend, T12) |
| --- | --- | --- | --- |
| D1 | Faixa à direita da barra de abas depois de "TÉCN…" | todas as abas, ≤ 900 px (visível a 560) | É uma **barra de rolagem vertical** de 15 px dentro de `.tabs`. Em `editorial.css:959` o `.tabs` ganha `overflow-x: auto`, o que torna `overflow-y` `auto` também; o sublinhado `.tab::after { bottom: -1px }` (`editorial.css:136`) passa 1 px da altura (scrollHeight 43 > clientHeight 42). Injetar `.tabs { overflow-y: hidden }` remove a barra (conferido). Não é largura fixa. Junto, há a barra horizontal de 16 px: conteúdo de 619 px numa faixa de 560. Capturas: `tabs-560-com-scrollbar.png`, `visao-geral-560-com-scrollbar.png`, `tabs-560-com-correcao.png`. |
| D2 | Baixar PNG pelo modebar do Plotly não funciona | Gráficos | A CSP bloqueia `blob:` em `img-src` (console: "Loading the image 'blob:…' violates … img-src 'self' data:"). Solução: incluir `blob:` em `img-src` (`app/main.py`, CSP; Backend). |
| D3 | Gráficos ficam com a largura antiga e a página rola para o lado | Gráficos, depois de redimensionar a janela com outra aba aberta | Redimensionar com a aba visível funciona; com ela oculta o Plotly não recalcula. A 900 px os gráficos ficam com 1174 px num cartão de 814 px, e a página com 1217 px. Provável: `dashboard.js`, `activate()` não chama `Plotly.Plots.resize` ao reabrir. Captura: `dashboard-900-apos-redimensionar.png`. |
| D4 | Rolagem lateral e coluna IPCA cortada | Preços a 560 px (12 px a mais) e a 900 px (8 px) | A 560 px, as `.detail-table` (620 px) dentro dos `<details>` fechados dos produtos estouram a largura, e a coluna "IPCA 12M" corta o valor ("+10.58%"). A 900 px não achei o elemento visível que causa os 8 px. Captura: `ranking-560.png`. Arquivos: `styles.css:303` / `editorial.css` (ranking). |

Acessibilidade (melhoria, não quebra):
- As setas ← → não trocam de aba (padrão ARIA de abas). Só Tab + Enter.
- Os botões `role="tab"` não têm `id` nem `aria-controls`; os painéis não têm
  `role="tabpanel"` nem `aria-labelledby`; o `nav.tabs` não tem `aria-label`.
- Não foi testado com o Orca de verdade; a árvore de acessibilidade foi lida
  pelo Playwright.

Obs.: a CSP também bloqueia o `eval` do próprio Playwright
(`wait_for_function`); os roteiros usam `page.evaluate`.

## T16c — defesas da T09 em `http.py` e RSS (2026-11-04): **feito**

`tests/test_http_defenses.py`, 36 testes, todos offline (`http.build_client` com
`MockTransport`; DNS falso via monkeypatch de `getaddrinfo`). Cobre os 11 casos
da seção T09 de `dados.md`: teto por `Content-Length`, streaming e gzip bomba;
`get_text(max_bytes=…)` e `_MAX_FEED_BYTES`; gzip normal decodifica; redirect
para `http://`, IP privado/loopback/link-local/`[::1]`/`localhost`/nome que
resolve para IP privado → `RedirectRefused` em 1 pedido; `https` público,
relativo e exatamente 5 saltos seguem; 6 saltos → `FetchError`; tempo total
esgotado; `body_snippet` fora de `str(exc)`; `_parse_feed` descarta
`javascript:`, `JaVa\tScript:`, `data:` e `https:` sem host; `_parse_xml`
recusa expat antiga e prefere defusedxml.

Defeitos: nenhum. Observações:
- `MAX_BODY_BYTES` é o padrão do parâmetro `max_bytes` em `_request`/`get_text`,
  avaliado no carregamento do módulo: mudar a constante em tempo de execução
  não tem efeito. Não é defeito; os testes passam `max_bytes=` direto.
- Timeout de fase do httpx (connect/read) não é exercitado: o `MockTransport`
  não abre socket. Só o teto `asyncio.timeout` é testado.
- defusedxml não está no `.venv`; o caminho com ele usa um substituto falso.

## T05 / T11b — importação mensal pelo Comtrade (2026-11-04): **feito**

- `tests/test_comtrade_monthly.py` (13): os 7 casos de `fetch_monthly_imports`
  em `dados.md`: soma de linhas do mesmo SH6/mês, peso 0 excluído, SH6 ausente
  → `ValueError`, meses em ordem e formato AAAA-MM com parâmetros da chamada,
  memo de uma rodada (10 categorias = 16 chamadas, em série e em paralelo),
  falha não memorizada, virada de ano em `_recent_periods`.
- `tests/test_ranking_imports.py` (10): os 8 casos da T11b de `ranking._imports`,
  com `source` ("UN Comtrade (dado SECEX)" / "Comex Stat (MDIC/SECEX)" / `None`),
  mais status `disabled` e Comtrade `stale` com prioridade sobre o Comex Stat.

Defeitos: nenhum. Não cobertos: `fetch_flow` (anual), `primaryValue` não
numérico, memo invalidado na virada do mês, `period` inválido em `_imports`,
`months` vazio com status ok.

## T10 / T11 / T10b — servidor, coleta Comtrade e marca da fila (2026-11-04): **feito**

- `tests/test_api_security.py` (24): T10 1–8 (`/api/refresh` 403 sem header,
  429 com `Retry-After`, single-flight com N POST = 1 coleta, TrustedHost 400
  para `evil.example`, GET sem `force`, CSP/nosniff/Referrer-Policy em `/` e
  `/api/*` e ausente em `/docs`, `public_error`, 503 sem snapshot e
  `last_error` sem o texto da exceção) e T10b (`model_breaks` anda com a
  versão, `model_since` só em `supply.queue`, `/api/methodology` sem "/10" e
  com 90/30 dias, `imports.source` = "UN Comtrade (dado SECEX)").
- `tests/test_collector_comtrade.py` (7): 9 jobs `comtrade_monthly.*` e
  nenhum `comexstat.*`; flag desligada → nenhum; `_share_by_sh6` (gpu →
  motherboard); `collect()` simulado → 10 chaves.
- `tests/test_safe_url.py` (11): `safeUrl` de `app/static/app.js` executado
  com node; recusa `javascript:`, `data:`, relativo e `//host`. Pula se não
  houver node.

Isolamento: `ASGITransport` com `base_url="http://127.0.0.1"`, estado de
`app.main` zerado por fixture, histórico em `tmp_path`. Defeitos: nenhum.
Não cobertos: CSP no navegador (Plotly/eval — teste manual), cancelamento por
desconexão com `asyncio.shield`, loop de 15 min, `/api/cache` pela rota.

## T14 / T15 — fila, repasse do câmbio, notícias multilíngues (2026-11-04): **feito, com 1 defeito**

- `tests/test_queue_model.py` (8): casos 1–5 do `modelo.md`. Três componentes
  em +1σ → 81,8; em +2σ → 95,3; estoque caindo mais = fila maior (estrito);
  estoque sem 7 pontos fica fora da conta sem virar zero. Caso 3 com série
  sintética (0,511 → 0,078, −65% a/a, capex +93%) → 92,8, entre 75 e 99: o
  `data/history.db` só guarda o último ponto, não os 29 trimestres.
- `tests/test_fx_passthrough.py` (9): casos 6–8. Dólar +10% em 30 dias com
  global neutro → BR 2,83% e global 0,0; repasse de 85% em 90 dias e texto
  do "primeiro mês". `test_cambio_nao_entra_na_projecao_global` segue passando.
- `tests/test_news_multilang.py` (16): casos 9–15 (mesma notícia em en/pt/es
  junta; empresas diferentes não juntam; "us" minúsculo não vira EUA; > 72 h
  não junta; selos "confirmada"/"fonte única"). Caso 11 testado só nas
  chaves, porque o título é descartado pelo filtro de relevância. No caso 12
  completei os títulos que vieram com reticências.

**Defeito (Modelo), `xfail(strict=True)`:**
`test_news_multilang.py::test_digest_nao_junta_empresas_diferentes_com_titulo_parecido`.
Em `app/domain/news.py:720`, a 2ª passada do `build_digest` junta pelo
`_similar` (títulos quase iguais) **antes** de consultar `same_story_by_keys`.
"Samsung raises DRAM prices" + "Micron raises DRAM prices" (reuters + ft)
viram 1 item `corroborated`, com `merged_by_keys = 0`. Reproduzido fora da
suíte. Correção sugerida: quando as duas manchetes nomeiam empresas e os
conjuntos não se cruzam, não aplicar o `_similar`. Ao corrigir, o teste dá
XPASS: avisar a QA para tirar o marcador.

Suíte: `.venv/bin/python -m pytest tests/ -q` → 343 passed, 1 xfailed.

## T08b — marcador retirado (2026-11-04)

O Modelo corrigiu o `build_digest`. Tirei o `xfail` de
`test_digest_nao_junta_empresas_diferentes_com_titulo_parecido`.
Suíte: `.venv/bin/python -m pytest tests/ -q` → 344 passed, nenhum xfail.

## T20 / T20b — tela de busca em tela cheia (2026-11-04): **feito**

A T20 foi desfeita (pedido mal entendido): `tests/test_ui_first_render.py`
apagado. No lugar, `test_ui_contract.py::test_primeira_abertura_mostra_so_a_tela_de_busca`
confere: `<body class="booting">` no `index.html`; regra do `editorial.css`
que esconde `.topbar`, `.tabs`, `.tabpanel` e `footer` sob `body.booting`;
`render()` remove a classe `booting`; `#retryBtn` existe e chama `load(true)`.

Suíte: `.venv/bin/python -m pytest tests/ -q` → 345 passed.

## T20c — rodapé da tela de busca (2026-11-04): **feito**

`test_loading_mostra_percentual_da_coleta` não exige mais `#loadingHint` e
passa a conferir que o id saiu do `index.html` e do `app.js`.
Suíte: 345 passed.
