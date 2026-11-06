# Relatório — Frontend

## 2026-11-04 · T13 (achados S1 e S2 da auditoria)

### S1 — `safeUrl` nas manchetes
- `app/static/app.js`: nova função `safeUrl(raw)`. Ela só aceita URL absoluta
  com `http:` ou `https:` (via `new URL`, sem URL base). Rejeita `javascript:`,
  `data:`, `ftp:`, vazio, caminho relativo e `//host`.
- `headlineHtml`: o `href` vem de `safeUrl` e continua passando por `esc()`. Um
  link inválido vira `<span class="headline-text">` com o título escapado, sem
  link.
- `app/static/editorial.css`: `.headline-text` usa a mesma cor dos links das
  manchetes.
- Conferido com `node -e` em dez casos, entre eles `JaVaScRiPt:` e URL com
  tabulação.

### S2 — botão Atualizar via `POST /api/refresh`
- `load(true)` agora chama `fetch('/api/refresh', {method: 'POST', headers:
  {'X-DSH-Refresh': '1'}})`. O carregamento normal continua em
  `GET /api/snapshot`.
- Resposta 429: a barra de status mostra "atualização recente; aguarde um pouco
  para pedir outra". Resposta 403: mostra "atualização manual recusada pelo
  servidor". O painel continua com o dado anterior. Se ainda não existir
  snapshot, ele busca `GET /api/snapshot` para não ficar vazio.
- O painel não usa mais `?force=true`. O Backend pode remover o parâmetro.

### Observações sobre CSP (S6)
- O HTML não tem `<script>` inline nem handler `on*=`. Todos os scripts são
  arquivos de `/static/`, então dá para usar `script-src 'self'`.
- Estilo inline: há cerca de 15 atributos `style="..."` gerados em template
  strings (`app.js`, `dashboard.js`, `charts.js`), para larguras de barra e
  cores de pontuação. Plotly também injeta `<style>` e estilos inline. Por
  isso a política precisa de `style-src 'self' 'unsafe-inline'`, a menos que eu
  troque os atributos por `el.style` (tarefa à parte; o Plotly continuaria
  precisando).
- O favicon é um `data:` SVG. Use `img-src 'self' data:`.
- O Plotly 2.35.2 minificado contém dois `new Function`. Os gráficos SVG
  provavelmente não chegam a esse código, mas isso falta testar com
  `script-src 'self'` sem `'unsafe-eval'` na aba Gráficos.

### Testes
- `node --check app/static/app.js`: ok.
- `python -m pytest tests/ -q`: 206 passaram, 4 xfailed.

## 2026-11-04 · T13b (fórmula da fila e repasse cambial)
- `app/static/index.html:491`, aba Técnico, cartão "Fila do consumidor": a
  fórmula passou a ser `50 + 50·tanh(0,25·desvio + 0,25·(−z(Δestoque a/a)))`.
  O texto explica que z(Δestoque a/a) é o z-score da variação anual do estoque
  da Micron.
- Repasse cambial: nenhum texto em `app/static/` fala em "85% em 30 dias". A
  única menção é a dica `cambio_br` em `app.js:96` ("o repasse é rápido"), que
  é qualitativa, e ficou como estava.
- Achado para a T12: `index.html:483`, cartão "2. Vetores", diz "Seis vetores",
  mas o cartão "3. IPH" e o PRD (RF-02) falam em sete. Falta confirmar com o
  Modelo qual é o sétimo vetor (terremotos?) antes de mudar o texto.
- Testes: `python -m pytest tests/ -q` com 206 passaram e 4 xfailed.
- `index.html:483`: o cartão "2. Vetores" passou de "Seis" para "Sete vetores"
  e agora inclui "Taiwan e disputa EUA–China por chips" (`geopolitica_chips`),
  como confirmou o Coordenador. Testes: 206 passaram e 4 xfailed.
- Preço de importação (`app.js`, detalhe do ranking): nenhum texto dizia
  "Comex Stat" fixo, e a nota não mostrava fonte. Agora ela termina com
  `esc(im.source || 'importação oficial')`.
- `index.html:519` (Técnico, limitações): o texto agora diz que o preço de
  importação vem do UN Comtrade mensal (dado da SECEX).
- `node --check app/static/app.js` ok; testes: 206 passaram e 4 xfailed.

## 2026-11-04 · T13c (pontos da fila com a conta antiga)
- `charts.js` (`trendChart`): cada série pode trazer `modelSince`. Os pontos
  anteriores saem num `<path class="trend-old-model">` pontilhado (`2 4`) e
  esmaecido (opacidade 0,4), sem ligar ao trecho novo. Nenhum ponto é cortado.
  No tooltip, esses pontos recebem a nota "· conta antiga".
- `app.js`: os dois gráficos da Evolução (principal e categoria) passam
  `model_since` adiante como `modelSince`. A nota `#trendNotice` ganha a linha
  "<série>: o trecho esmaecido e pontilhado, até dd/mm, usa a conta antiga e
  não é comparável com os pontos seguintes". Ela só aparece se houver ponto
  antes do corte e convive com a nota do trecho reconstruído.
- `dashboard.js` (aba Gráficos, gráfico Plotly da fila): a fila virou duas
  séries, "Fila (conta antiga, até dd/mm)" pontilhada com opacidade 0,45 e
  "Fila do consumidor" normal.
- Sem `model_since`, nada muda. Conferido com um teste em node que simula o
  SVG: um trecho antigo quando há `modelSince`, nenhum quando não há.
- `node --check` ok em charts.js, app.js e dashboard.js; testes: 206 passaram
  e 4 xfailed.

## 2026-11-04 · T19b (card do dólar no padrão dos outros)
- `app.js` (`fxExplanationHtml`): o conteúdo agora fica dentro de
  `<details class="driver-more">`, com o resumo "Por que o dólar se mexeu e o
  efeito no preço (30 dias)" e a `.fx-why` por dentro. No card, a ordem ficou
  título, medidor, tese, peso/cobertura, o recolhível do dólar e depois "Ver
  sinais e fontes", igual aos outros cards mais um recolhível. O nome
  `fxExplanationHtml`, a classe `.fx-why` e os textos verificados em
  `test_ui_contract.py` continuam os mesmos.
- `editorial.css`: a `.fx-why` perdeu a borda e o bloco destacado e segue a tese
  (12,5px, altura de linha 1,62, `--txt-2`, até 76ch). Os subtítulos h4 usam o
  traço mono 10px do resumo. Com `.driver-more + .driver-more`, sai a linha
  dupla entre os dois recolhíveis.
- Conferido em Firefox headless a 900 e 560 px, numa página de teste com os
  cards reais do `/api/snapshot` e os dois CSS do painel: o padrão está igual e
  não há rolagem lateral. A captura da página inteira saiu antes de os dados
  carregarem, por isso usei a página de teste.
- Testes: `.venv/bin/python -m pytest tests/ -q` com 344 passaram.

## 2026-11-04 · T20 (a busca precede a exibição) — DESFEITA, veja T20b
- `app.js`: novos `firstRenderDone` e `pendingTab`. Antes do primeiro render:
  - `activateTab()` só guarda a aba pedida (hash, clique, `data-goto`,
    `openSignal`) e não busca nada;
  - `refreshTrend()` e `ensureTrendLoaded()` retornam sem fazer nada;
  - o `Dash.activate()` (aba Gráficos) nem é chamado.
- `render()` chama `startAfterFirstRender()` na primeira vez. Essa função abre
  a aba pendente (ou a do hash), o que dispara `/api/series`, `/api/history` e
  o Plotly, e só então liga o `refreshTimer` de 15 min e o `countdownTimer`.
- `init()` aplica os parâmetros da URL sem fetch e depois chama `load()`.
- Primeira coleta com falha (`showError`): `firstRenderDone` fica falso, as
  abas não carregam nada e não há timer. O botão Atualizar pode tentar de novo,
  e se der certo o fluxo normal começa.
- Nas atualizações seguintes nada muda: o dado anterior fica na tela e o
  progresso aparece inline.
- `dashboard.js` não mudou: ele só é ativado pelo `activateTab` e já não buscava
  nada sem snapshot.
- Verificado com um servidor de teste que segura `/api/snapshot` por 4 s, com
  Firefox headless:
  - `#tendencia`: `/api/series` e `/api/history` só depois de "SNAPSHOT
    RESPONDED"; antes, só `/api/progress`;
  - `#dashboard`: o Plotly e o `/api/history` só depois do snapshot;
  - snapshot com 500: nenhuma chamada a `/api/series` ou `/api/history`.
- `node --check` ok; testes: 344 passaram.
- Para a QA (teste de contrato em `app.js`): `let firstRenderDone = false`,
  `function startAfterFirstRender()`, `if (!firstRenderDone) return;` em
  `refreshTrend` e `ensureTrendLoaded`, `pendingTab = { name, syncHash }` em
  `activateTab`, e os `setInterval(` de `refreshTimer`/`countdownTimer` dentro
  de `startAfterFirstRender` (não mais em `init`).

## 2026-11-04 · T20 desfeita + T20b (primeira abertura só com a tela de busca)
- Rollback da T20 em `app.js`: saíram `firstRenderDone`, `pendingTab`,
  `startAfterFirstRender` e as guardas em `activateTab`, `refreshTrend` e
  `ensureTrendLoaded`. Os `setInterval` de refresh e countdown e o
  `activateTab(tab)` do hash voltaram ao `init()`, como antes. A T19b ficou
  como estava.
- T20b:
  - `index.html`: `<body class="booting">`. O `#error` agora tem
    `<p id="errorText">` e `<button id="retryBtn">Tentar de novo</button>`.
  - `editorial.css`: com `body.booting`, somem `.topbar`, `.tabs`, `.tabpanel`
    e `footer`. O `main` ocupa 100vh/100dvh e centraliza o `#loading` (até
    560px) ou o `#error`. O botão "Tentar de novo" só aparece sob `booting`.
  - `app.js`: o fim de `render()` faz `document.body.classList.remove('booting')`.
    `showError` escreve em `#errorText`, e `#retryBtn` chama `load(true)`.
- Conferido em Firefox headless a 900 e 560 px, com um servidor de teste
  (snapshot atrasado, snapshot 500 e snapshot normal):
  - carregando: só o spinner, a barra e o percentual, centralizados;
  - 500: só a caixa de erro com "Tentar de novo", centralizada;
  - ok: o painel inteiro aparece de uma vez.
- Testes: só `tests/test_ui_first_render.py` falha, como esperado (a QA vai
  reescrever). As outras 345 passam. `node --check` ok.
- Achado para a T12: a 560 px há uma faixa branca à direita da barra de abas,
  depois de "TÉCN…". Já aparecia antes desta mudança.

## 2026-11-04 · T20c (fim da dica na tela de busca)
- `index.html`: saiu o `<p id="loadingHint">`.
- `app.js` (`setLoadingProgress`): saiu o bloco `let hint …` até
  `$('loadingHint').textContent = hint;`. Título, barra, percentual e contagem
  ficaram como estavam.
- CSS: não havia regra só para a dica. A `.loading p` também vale para o título
  e o percentual, então ficou.
- `node --check` ok. Testes: só
  `test_ui_contract.py::test_loading_mostra_percentual_da_coleta` falha, porque
  ainda lista "loadingHint". A QA vai ajustar. As outras 344 passam.

## 2026-11-04 · T21b (cards de "O que está por trás do número" por score)
- `app.js`: o render de `$('drivers')` usa uma cópia `driversByScore`, ordenada
  por `score` do maior para o menor. O `sort` é estável, então em empate fica a
  ordem do servidor. `d.drivers` não muda e a estrutura dos cards ficou como
  estava.
- Outras listas de vetores ficaram como estavam:
  - Visão Geral (`simpleReasons` e "fator que mais pesa"): `rankedDrivers`, por
    score × peso;
  - Gráficos (radar, `dashboard.js`): ordem do servidor;
  - Técnico (`index.html:485`): texto fixo, na ordem do código.
- `node --check` ok; testes passaram.

## 2026-11-05 · T12 (defeitos da T03)
- **D1** (`editorial.css`, `@media 900px`): `.tabs` ganhou
  `overflow-y: hidden`, e saiu a barra vertical de 15 px. A rolagem horizontal
  das abas a 560 px continua, como esperado.
- **D3** (`dashboard.js`): o `activate()` chama `resizeVisible()` depois do
  `refresh()`, com `Plotly.Plots.resize` em cada `.js-plotly-plot` de
  `#tab-dashboard` (num `requestAnimationFrame`). Teste: abrir Gráficos a
  1280, trocar de aba, ir a 900 e voltar. Antes os gráficos ficavam com
  1174 px e a página com 1217 px; agora ficam com 814 px num cartão de 864 px,
  e a página com 900 px.
- **D4** (`editorial.css`):
  - `.detail-table { min-width: 0 }`. A tabela herdava o `table { min-width:
    620px }` global de `styles.css:235`, que é para as tabelas em `.table-wrap`.
  - A 900 px, os 8 px vinham do IPCA: na grade `≤1040px` ele caía na coluna de
    24 px do chevron (conteúdo de 50 px). A grade passou a 4 colunas, `num main
    main chevron / . value value value / . pressure ipca ipca`, e o mesmo vale
    a 560 px. "+10.58%" aparece inteiro.
- **Acessibilidade**:
  - `nav.tabs` com `aria-label="Seções do painel"`;
  - cada aba com `id="tabbtn-<aba>"`, `aria-controls="tab-<aba>"`,
    `aria-selected` e tabindex móvel (0 na ativa, −1 nas outras);
  - painéis com `role="tabpanel"`, `aria-labelledby` e `tabindex="0"`;
  - `onTabKeydown`: ← → circulam, Home/End vão às pontas, e a aba é ativada e
    rolada para a vista.
- Verificado com o Brave headless (Playwright do ambiente da QA), no servidor em
  8000, a 900 e 560 px, nas sete abas:
  - largura do documento igual à da janela em todas;
  - fora da janela só a aba "TÉCNICO" (dentro da faixa rolável) e a
    `src-table` (dentro de `.table-wrap`, que rola);
  - teclado: → de Gráficos vai a Evolução (o hash muda), End vai a Técnico,
    → de Técnico volta a Visão Geral, ← de Visão Geral vai a Técnico.
- `node --check` ok em app.js e dashboard.js; testes: 345 passaram.
- Fora da minha área, visto nas capturas:
  - "Preço de importação 44.268,87 · +443.5% em 12m" (SH6 854232) parece valor
    errado ou unidade trocada (Dados/Modelo);
  - os percentuais usam ponto decimal ("+10.58%") em vez de vírgula. Isso é
    formatação do frontend (fmtPct), e falta decidir se troca.

### T12c — ideia de layout para "Por marca" (não implementado)
- Uma barra de sub-abas dentro de `#tab-ranking`, logo abaixo do título:
  `[Produtos] [Por marca]`. Usaria o mesmo `.seg`/`.seg-btn` que já existe
  (botões em linha, `flex-wrap: wrap`) e não o `.tabs`. Assim não há
  `overflow-x` nem `::after` com `bottom: -1px`, e o D1 não volta.
- ARIA: um `role="tablist"` aninhado com `aria-label="Visões de preço"` e as
  mesmas setas (o `onTabKeydown` fica genérico por container). A sub-aba entra
  no hash como `#ranking?view=marca`.
- "Por marca": uma linha por faixa de GPU, com as colunas AMD e NVIDIA lado a
  lado. A 560 px, cada faixa vira um bloco com AMD em cima e NVIDIA embaixo. A
  estrutura depende do contrato da API.

## 2026-11-05 · T12c (esqueleto de Preços com sub-abas Produtos e Por marca)
Contrato: `GET /api/prices` (`backend.md` §T28c). O endpoint ainda não existe;
testei com a fixture do contrato servida pelo próprio navegador.
- `index.html`, aba Preços:
  - logo abaixo do título, `.seg.price-views` com `role="tablist"` e
    `aria-label="Visões de preço"`, e os botões `#pvbtn-produtos` e
    `#pvbtn-marca` (`role="tab"`, `aria-controls`, tabindex móvel);
  - `#pv-produtos` (`role="tabpanel"`) tem o ranking de estimativas, sem
    mudança, e embaixo "Preço na loja, por faixa" (`#storeProducts`);
  - `#pv-marca` tem "Placa de vídeo: AMD × NVIDIA por faixa" (`#storeBrand`) e
    a nota `#brandNote`;
  - novo `<script src="/static/prices.js">` antes do `app.js`.
- `app.js`:
  - `priceView` e `setPriceView()`; `buildHash('ranking')` gera
    `ranking?view=marca`; `applyPriceParams()` no init e no hashchange;
  - `activateTab` chama `Prices.activate()` e `Prices.deactivate()`, e o
    `render()` chama `Prices.onSnapshot()`;
  - o teclado virou `bindTabKeys(list, activate)`, usado na barra principal e
    nas sub-abas (← → Home End).
- `prices.js` (novo, IIFE no estilo do `dashboard.js`):
  - busca `/api/prices` só com a aba aberta e de novo a cada snapshot novo;
  - estados: 503 ("aparecem depois da primeira coleta"), 404 ("ainda não estão
    disponíveis neste servidor"), `source.status="disabled"` (mensagem e
    `status_reason`) e erro de rede. O ranking continua na tela em todos;
  - rótulo: `source.label · source.note` e a hora de `as_of`;
  - Produtos: por categoria, IPCA (subitem, período, 12 meses) com o selo
    "proxy" (`is_proxy`) ou "sem subitem". Cada faixa mostra à vista, preço
    cheio, 30 dias, "N de M anúncios válidos", avisos e o recolhível
    "Anúncios" com o status de cada oferta. Categoria com `published=false`
    fica esmaecida e mostra o aviso `category_unpublished`;
  - Por marca: AMD primeiro (a 560 px, AMD em cima e NVIDIA embaixo), modelo,
    preço, 30 dias, anúncios, `diff_amd_pct` como "AMD +13.6% mais cara que a
    NVIDIA" (sinal −), avisos da faixa no topo (`no_competitor`) e a nota do
    servidor, com a frase fixa como reserva;
  - segurança: `storeUrl()` (K16) aceita só `https:`, hostname exatamente
    `www.kabum.com.br`, sem usuário, senha ou porta. Os links usam
    `rel="noopener noreferrer nofollow"` e `referrerpolicy="no-referrer"` (K17).
    `pEsc()` vale para nome, modelo, rótulos, avisos e status (K18). Classes de
    aviso e status saem de allowlist. Ainda não há Plotly nesta aba.
- `editorial.css`: estilos `.price-*` e `.brand-*`. Abaixo de 640 px, faixas e
  marcas em uma coluna. As sub-abas usam `flex-wrap` e o sublinhado é
  box-shadow, sem `overflow-x` nem `::after`, então o D1 não volta
  (scrollHeight = clientHeight).
- Verificado no Brave headless (Playwright do ambiente da QA, sem acionar a QA),
  com `/api/prices` simulado:
  - fixture do contrato com casos hostis: `<img onerror>` e `<script>` no
    nome e no modelo, `<b>` no rótulo, URLs `evil.example`, `javascript:`,
    porta 8443 e `a@`. Só o link legítimo virou `<a>`, todo o resto saiu como
    texto e não houve elemento injetado nem diálogo;
  - a 900 e 560 px, nas duas sub-abas e nos estados ok, disabled, 503 e 404
    real: largura do documento igual à da janela, nenhum `pageerror`, e o
    ranking com as 10 categorias sempre presente;
  - hash direto `#ranking?view=marca` abre "Por marca"; ← volta para
    Produtos (hash `#ranking`), End vai para "Por marca".
- `node --check` ok em app.js e prices.js; testes: 345 passaram.
- Percentuais seguem com ponto decimal; a troca por vírgula espera a decisão.

## T32 — tela com os dados reais (2026-11-05)

Conferido contra a T30 sem navegador: os cards das frentes já batem com as
unidades reais ("dias" e "% a/a"), o grupo "Preços na loja" entra no seletor
genérico (escapado) e o `lineTraces` não precisou mudar. Único ajuste: o
rótulo "Preço de importação" ganhou a unidade (`US$/kg`) em `app.js`.
Testes: 335 passaram e 10 falharam, todos de fila/oferta/API (fora da tela).

## T34 — Preços: "Por marca" vira "Produtos no mercado" (2026-11-05)

A primeira versão mexia em Produtos; foi desfeita pela correção do
Coordenador. Produtos ficou como estava. A sub-aba "Por marca" virou
"Produtos no mercado" (`#ranking?view=mercado`, `pvbtn-mercado`/`pv-mercado`,
mesmas setas e ARIA). Ela mostra o ranking das faixas da cesta KaBuM com preço
hoje, ordenadas pela variação de 30 dias, no visual `rank-row`: modelo,
categoria · faixa, variação, preço cheio e anúncios. O `brand_view` não é mais
exibido: saíram `renderBrand` e o CSS `.brand-*`. O hash antigo `?view=marca`
cai em Produtos.

T33: selo "marketplace · vendido por <seller>" nas ofertas (escapado, K18) e
o aviso `marketplace` na allowlist. Suíte: 335 passaram e 10 falharam, as
mesmas de antes, todas fora da tela.

## T34b — "Preço na loja, por faixa" vai para "Produtos no mercado" (2026-11-05)

O bloco `store-prices`/`#storeProducts` saiu de Produtos e substituiu o ranking
da cesta da T34 (saíram `renderMarket` e `#storeRanking`). Produtos ficou só
com o ranking de estimativas. Mantidos o hash `?view=mercado`, o selo
marketplace e K16–K18. Suíte: 335 passaram e 10 falharam, as mesmas de antes,
todas fora da tela.

## T34c — ordem das categorias em "Produtos no mercado" (2026-11-05)

`prices.js` guarda, no `onSnapshot`, a ordem do ranking (estimativa Brasil ·
30 dias, decrescente, o mesmo critério de `app.js`). `renderProducts` ordena
as categorias por ela; as que não estão no ranking vão para o fim. Suíte: 335
passaram e 10 falharam, as mesmas de antes, fora da tela.

## T35 — cesta por modelo (2026-11-05)
- prices.js: a contagem por faixa agora diz "x de y modelos com preço", e o rótulo diz "y modelos acompanhados por dia". O single_listing saiu do WARN_CLASS. O aviso partial continua com a classe stale.
- O campo tier.models[] e o brand_view não são exibidos. As ofertas (offers) continuam iguais.
- Testes: node --check ok; pytest 335 passaram e 10 falharam, as mesmas falhas de antes, fora do frontend.

## T35d — tier.models[] (2026-11-06)
- prices.js: quando tier.models[] existe, a faixa lista "Modelos (n)". Cada modelo mostra marca e nome, a mediana do preço cheio, o selo sem preço/sem dados e até 3 anúncios de referência, ligados pelo model_key em offers[], onde a url já vem pronta. Sem models[], a faixa volta à lista plana de anúncios.
- Testes: node --check ok; pytest 335 passaram e 10 falharam, as mesmas falhas de antes, fora do frontend.

## T35e — range_brl null (2026-11-06)
- Sem mudança. rangeText(null) devolve '' e tierHtml só mostra a faixa quando há texto; um nível sem preço já some sem faixa. Testes: node --check ok; pytest 335 passaram e 10 falharam, as mesmas falhas de antes. A suíte levou 8 min e meio nesta rodada.

## Remoção da "conta antiga" nos gráficos (2026-11-06, pedido do usuário)
- app.js, charts.js e dashboard.js: os pontos antes de model_since não são mais desenhados. Saíram a série "Fila (conta antiga)", o trecho pontilhado da Evolução, a nota "conta antiga" e o rótulo no tooltip. O filtro está em currentPoints(), em app.js e em dashboard.js. A API e o banco não mudaram.

## Junção Gráficos + Evolução em Plotly (2026-11-06, pedido do usuário)
- index.html: a aba Evolução saiu, e a aba Gráficos ficou com, em ordem:
  - um período só (#trendRanges, com Tudo);
  - os KPIs;
  - "A pressão ao longo do tempo", agora #trendChart, com seletor de indicadores e legenda;
  - "Evolução por produto", agora #trendCatChart, com Brasil, global e as barras de IPCA;
  - a fila com o investimento em IA;
  - o ranking, as bolhas e o radar.
  O charts.js deixou de ser carregado.
- Removidos dashIndex, dashCategory, dashCategoryChart, dashCategorySrc, dashRanges, trendTip, trendCatTip e trendCatLegend, porque eram duplicados ou ficaram sem uso.
- dashboard.js: Dash.drawTrend(id, cfg) desenha a evolução em Plotly, com quebra em lacuna e trecho recalculado tracejado, e Dash.setRange(range) recebe o período do app. Um clique em barra ou bolha dispara o evento 'dash:category'.
- app.js: o estado e os textos da evolução continuam aqui. O alias tendencia→dashboard mantém os links antigos, e o hash #dashboard?range=&series=&cat= guarda o estado.
- O charts.js ficou no disco sem uso, porque test_ui_contract.py lê o arquivo. Ele pode ser apagado quando os testes forem ajustados.

## Painel-resumo acima do seletor de período (2026-11-06, Coordenador)
- A aba Gráficos ficou dividida em duas partes:
  - Acima do seletor: os KPIs, o ranking de 30 dias e as bolhas. Os KPIs agora vêm só do snapshot (summary.iph, iph_brazil e iph_label); saíram os deltas "no período", que dependiam do histórico.
  - Abaixo do título "Ao longo do tempo", o #trendRanges e só os gráficos que ele altera: a evolução, o produto, a fila e o radar.
- Testes: 6 testes de test_ui_contract.py ainda exigem a estrutura antiga. São eles: aba_tendencia, charts_js_carrega, drill_down tendencia, visao_geral data-goto=tendencia, dashboard seis gráficos e textos catSvg._trend. As outras 10 falhas são as mesmas de antes.

## Produto e fila na aba Gráficos (2026-11-06, Coordenador, aprovado pelo usuário)
- Produto: o título passou a ser "Para onde a nossa estimativa de preço aponta nos próximos 30 dias".
  - O gráfico mostra só as duas estimativas, global e Brasil, com a linha de zero marcada "estável" (opção zeroLabel do drawTrend).
  - As barras do IBGE saíram do eixo. Em #trendCatIpca aparece "IBGE, último mês: X%, mês AAAA-MM", buscado com range=all.
  - O eixo x usa só a janela das estimativas.
- Fila: a linha de 50 ficou marcada "neutro". A faixa acima, sombreada, diz "consumidor perdendo espaço para a IA"; a de baixo, "sobrando capacidade". Entrou a frase fixa pedida.
- Testes: node --check ok; pytest 329 passaram e 16 falharam (as 10 de antes e os 6 de test_ui_contract já relatados).

## T36 — abas reorganizadas e cards Micron/NVIDIA fora (2026-11-06)
- index.html: a ordem das abas passou a ser Visão Geral · Detalhes · Preços · Gráficos · Técnico.
  - A aba Fila saiu da barra. Gráficos ganhou as sub-abas .seg.chart-views "Geral | Consumidor vs IA" (#cv-geral, #cv-fila), no mesmo padrão de Preços.
  - O conteúdo inteiro de #tab-fila foi para #cv-fila.
- app.js:
  - chartView/CHART_VIEWS, setChartView e applyChartParams controlam a sub-aba; o hash fica #dashboard?view=fila. O link antigo #fila abre Gráficos já em Consumidor vs IA.
  - Ao voltar para Geral, Dash.activate() refaz a medida dos gráficos Plotly.
  - "Ver a evolução" e o drill-down de sinal abrem Geral.
- FRONT_CARDS ficou só com "Demanda (capex + TSMC)", e isso vale para a Visão Geral e para Consumidor vs IA.
- editorial.css: .chart-views reaproveita o estilo de .price-views.
- Testes: só test_ui_contract.py, a pedido; 26 passaram e falharam os mesmos 6 de antes, que não foram corrigidos. O README fica com o Coordenador.
- Atenção: a pendência anterior já está nos arquivos, embora o comando tenha aparecido como recusado. São três mudanças: a regra de 1200 px em editorial.css, o redimensionamento via matchMedia em dashboard.js e o texto "clique numa barra" em index.html e app.js. O usuário vai decidir se fica ou se é revertida.

## T37 — seção "Consumidor vs Datacenter" no lugar da sub-aba (2026-11-06)
- index.html:
  - As sub-abas de Gráficos saíram.
  - A seção #consumidorDatacenter, com o subtítulo pedido, fica abaixo de radar + ranking e acima de "Ao longo do tempo". Ela tem lado a lado #capexChart e #inventoryChart, os SVG da antiga Fila.
  - O resto da antiga Fila saiu: medidor, KPIs, nota, Comtrade, explicação em passos e o card Demanda dali.
- app.js:
  - renderQueue só desenha os dois gráficos.
  - Saíram chartView e setChartView. #fila e #dashboard?view=fila abrem Gráficos e rolam até a seção (scrollToSupply).
- editorial.css: estilo .dash-supply; .chart-views saiu.
- Conferido e completo: a regra de 1200 px (.dash-now em uma coluna abaixo disso), o matchMedia que chama resizeVisible() no dashboard.js e o texto "clique numa barra" em index.html e app.js. Ficou mantido, como pedido.
- Testes: test_ui_contract.py com 26 passando e os mesmos 6 falhando. A pendência registrada na T36 está resolvida.

## T38 — limpeza de Detalhes, rolagem e fim da aba Técnico (2026-11-06)
- Detalhes: a seção "O efeito no Brasil" (#fxChart e #ipcaChart) saiu, junto com o código que desenhava esses gráficos e a função barChart, que só eles usavam. O dólar continua na Visão Geral.
- Preços: o id "ranking" virou "priceRanking", e o hash #ranking não rola mais a página. Nenhum outro hash de aba (visao-geral, overview, dashboard, fila, tecnico) coincide com um id.
- Rolagem: clicar numa aba ou num botão data-goto volta ao topo com window.scrollTo(0, 0). #fila continua rolando até #consumidorDatacenter.
- Técnico:
  - Saíram o botão, #tab-tecnico, o JS de #interpretation e #sources e os dois links data-goto="tecnico" da Visão Geral.
  - O alias tecnico→visao-geral cobre o hash antigo.
  - CSS removido (só a Técnico usava): .tech-*, .interpretation, .table-wrap, .glossary-link e .linkbtn. As regras globais de table/th/td ficaram, porque a .detail-table usa.
  - Ordem das abas: Visão Geral · Detalhes · Preços · Gráficos.
- Testes: test_ui_contract.py com 25 passando e 7 falhando. São os 6 de antes e mais test_aba_tecnico_concentra_metodologia_fontes_e_limites, que espera a aba removida.

## T39 — aba Fontes (2026-11-06)
- index.html: nova aba "Fontes" no fim (#tab-fontes; ordem Visão Geral · Detalhes · Preços · Gráficos · Fontes).
  - No topo, o texto "Todas as fontes são públicas e nenhuma exige cadastro ou chave."
  - No fim, uma nota em texto sobre o docs/fontes.md, sem link.
  - O hash #fontes não coincide com nenhum id.
- app.js: renderSources(d), chamado em render(), agrupa snap.sources por provedor. Cada fonte mostra:
  - o nome com link, via safeUrl e com target=_blank e rel=noopener;
  - o selo (ok, desatualizada, indisponível ou desligada), por allowlist SOURCE_STATUS;
  - a data de referência, a última coleta e a nota.
  Todo texto dinâmico passa por esc().
- editorial.css: .src-*. É uma lista com flex-wrap e overflow-wrap:anywhere, não uma tabela, para não ter rolagem lateral no celular.
- Testes: test_ui_contract.py com 25 passando e os mesmos 7 falhando de antes.

## T40 — medidor e termômetro trocados (2026-11-06)
- Visão Geral: o .simple-thermo deu lugar ao medidor semicircular (#simpleGauge, com #simpleScore, #simpleScoreLabel = iph_label e o selo "estimativa nossa"). O rodapé #simpleBrazil e o código que o montava saíram.
- Detalhes: o medidor deu lugar ao termômetro .simple-thermo.detail-thermo (#iphValue, "Pressão sobre o preço (0 a 100)", #iphMarker e as legendas), sem rodapé. O KPI "Dados disponíveis" saiu.
- Os ids são únicos em cada aba; renderGauge e as classes CSS são compartilhados.
- CSS: regras .simple-gauge e .detail-thermo, com versão para celular; as regras .simple-br saíram.
- Testes: test_ui_contract.py com 25 passando e os mesmos 7 falhando.

## T41 — "estimativa nossa" → "estimativa" (2026-11-06)
- index.html: 6 ocorrências trocadas, mantendo a maiúscula ("Estimativa:" no glossário). As frases continuam fazendo sentido, como "A nota é uma estimativa." e "estimativa é o que o modelo calcula". O JS não tinha nenhuma ocorrência.
- app/services/collector.py:45 ficou de fora porque não é da área do Frontend. O pedido foi para o Coordenador repassar ao dono.
- Testes: test_ui_contract.py com 24 passando e 8 falhando. São os 7 de antes e mais test_entenda_usa_os_limiares_reais_e_nao_promete_queda, que exige "estimativa nossa" no HTML.

## Ajustes diretos do Coordenador (06/11, após a T41)
- Visão Geral: removido "Como ler em 30 segundos" (HTML + CSS); a nota de "não é recomendação" segue no rodapé.
- Divisórias: uma linha única abaixo do hero e outra acima de "O que vale acompanhar"; sem linha vertical ao lado do medidor nem linha acima dele no celular.
- Medidor da Visão Geral: coluna clamp(340px, 34vw, 380px); número em max(56px, 24cqi) (container query); até 900 px, máx. 380 px.
- Visão Geral: itens de "O que mais pesa hoje" e "O que pode ficar mais caro" alinhados por subgrid (listas em display: contents); botões do hero presos à base (flex coluna, align-items: flex-start); botão "?"/glossário criado e removido a pedido.
- Detalhes: divisória antes de cada bloco e entre as causas; sem linhas internas; espaçamento padronizado (40/24/20/12/10 px); linha vertical entre termômetro e KPIs; KPIs em grade fixa de 3 colunas (1 até 560 px) com selo abaixo do nome; textos de "O que está por trás do número" e de Notícias trocados; "Por que o dólar se mexeu" removido (fxExplanationHtml + CSS fx-*).
- Gráficos: texto de abertura reduzido a "Veja como a pressão e os preços estimados mudaram com o tempo." (sem selos).
