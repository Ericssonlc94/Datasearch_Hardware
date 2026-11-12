# Quadro de tarefas

Mantido pelo Coordenador. Status: a fazer · fazendo · pausado · feito · bloqueado · desfeita.
Atualizado em 2026-11-10 15:00. Suíte: 325 passed / 20 failed (10/11, com DSH_ENABLE_KABUM=false DSH_ENABLE_TSMC=false).

## Para retomar (11/11/2026)

- Esquema novo de painéis: uma sessão Claude Code por função (`DSH / 1`,
  `DSH / Dados`, `DSH / Modelo`, `DSH / Backend`, `DSH / Frontend`, `DSH / QA`,
  `DSH / Segurança`), com o prompt de `.claude/agentes/<função>.md` e o mapa em
  `CLAUDE.md`. Sem herdr, sem `hc`, sem scripts de registro: o Coordenador vê
  quem está vivo com `ListAgents`.
- Histórico do esquema antigo (terminais t1–t12) em `registro.md`, agora arquivo
  morto. Os relatórios de cada função continuam a fonte do histórico.
- O quadro abaixo é o de 10/11 15:00 e segue valendo. Continuam abertos: T45
  (KaBuM), T46 (QA), T43c (Frontend), T32/T33/T34, T35b–T35e e a decisão de
  reiniciar o servidor principal com o código novo.

## Em aberto

| ID | Tarefa | Função | Status | Observação |
| --- | --- | --- | --- | --- |
| T03 | Abrir as sete abas, 900/560 px, teclado, leitor de tela (+ T16a: Gráficos com CSP) | QA | feito | Brave 155 headless, 1280/900/560; sem erro de CSP/eval; 4 defeitos D1–D4 → T12/T12b; detalhes em qa.md §T03 |
| T12 | Defeitos D1, D3, D4 + acessibilidade das abas | Frontend | feito | overflow-y:hidden; resize do Plotly ao trocar de aba; detail-table min-width 0 e grade de 4 colunas; setas/Home/End, aria-controls, role=tabpanel; 345 ok; conferido no Brave a 900/560 px |
| T12b | CSP: blob: em img-src | Backend | feito | img-src 'self' data: blob:; sem unsafe-eval; 345 ok |
| T16 | Suíte completa + reabrir painel | QA | pausado | standby (usuário, 05/11); depende de T09–T15; conferir no navegador: Evolução e Gráficos com supply.queue (trecho antigo esmaecido + nota) |
| T17 | Consolidar relatórios no README/fontes.md | Coordenador (README) + Dados (fontes.md, na T30) | feito | README reescrito como visão geral do webapp (06/11); execução, testes e endpoints movidos para o PRD | no fim da onda, junto da T18; standby (usuário, 05/11); depende de T16; README §5: repasse 30/90 de 85% e nova fórmula da fila; URL do feed da Tom's Hardware agora é feeds.xml; defusedxml na lista de dependências; README:152 "Câmbio e macro Brasil" → "Dólar"; incluir Comex Stat rejeitado (GET 200 / POST 429 WAF) e preço de importação via Comtrade mensal (~2 meses de defasagem) |
| T22e | Achados C1–C4: não renomear arquivo alheio; Retry-After finito; expires_at com teto | Dados | pausado | C2/C3 já aplicados (Retry-After); faltam C1, C4–C7 em cache.py |
| T23 | Viabilidade das fontes de oferta e preço BR | Dados | feito | TSMC (TWSE OpenAPI), SEC NVIDIA/AMD/Intel (dias por CPV) e IPCA viáveis sem chave; DART, data.go.kr e Mercado Livre exigem chave do usuário; ML sem garantia mesmo com token; Micron: suspeita YTD NÃO procede (Q4 de 98 dias → normalizar a 91); prévia de 20 dias da Coreia não separa chips |
| T24 | Desenho: painel de oferta por categoria (frentes memória/lógica/demanda/geral × exposição por categoria; DIO em z; TSMC/Coreia z a/a 3m) e preço BR (mediana + P25–P75, cesta fixa de modelos) | Modelo | feito | proposta em modelo.md §T24; 7 perguntas ao usuário; implementa após respostas + T23 |
| T24b | Cesta de preços: 30 itens, 2 a 4 por categoria | Modelo | feito | proposta em modelo.md §T24b; em espera: sem o Mercado Livre não há fonte de preço em reais |
| T24c | Desenho revisado só com fontes públicas (TSMC, SEC, IPCA, Comtrade já existente) | Modelo | feito | modelo.md §T24c; aguarda sinal para implementar (Dados → Modelo → Backend → Frontend → Segurança) |
| T25 | Viabilidade do preço em reais pelos comparadores Zoom e Buscapé | Dados | bloqueado | robots.txt (mai/2026) bloqueia agentes de IA (inclui ClaudeBot/Claude-User) para "proteção do catálogo e dados de preço"; para *: busca e /lead proibidos, só URL fixa de produto liberada; só 2 pedidos (robots); decisão do usuário |
| T25b | Viabilidade de preço nas lojas | Dados | feito | KaBuM viável (__NEXT_DATA__ na busca /busca/<termo>, JSON-LD no produto; cobre componentes, notebook, monitor, console); Samsung/Dell/Lenovo viáveis com ressalva (termos "uso pessoal, não comercial"; Lenovo falta página de produto); Pichau e Terabyte: Cloudflare; Amazon: bloqueia Claude no robots |
| T26 | Revisar a política de coleta na KaBuM | Segurança | feito | seguranca.md §T26, K1–K22; altas: K1 (force=true fura o cache → a loja ignora force), K2 (falha da loja ≥ 24 h e gravada); teto de 40 pedidos/dia, 0 retentativas, só /produto/<code> no loop; mínimo para VPS registrado |
| T24d | Cesta ajustada à KaBuM | Modelo | feito | modelo.md §T24d; 37 URLs só vendidas pela KaBuM; à vista como principal, cheio na 2ª linha, oferta relâmpago fora da mediana; aguarda aprovação do usuário |
| T24e | Cesta por faixa (baixo/médio/alto) | Modelo | feito | modelo.md §T24e; 30 modelos, 38 URLs; variação por faixa; categoria publica com ≥ 2 das 3 faixas; aguarda aprovação do usuário |
| T24f | GPU com AMD + NVIDIA (mediana única) + visão por marca | Modelo | feito | modelo.md §T24f; GPU 10 URLs (2 por marca e faixa); total 40 com cortes em RAM médio e placa-mãe baixo, ou 38 sem os extras de notebook; marcas com peso igual; aguarda aprovação |
| T27 | Curadoria das URLs na KaBuM | Dados | feito (parcial) | 24/38 vagas com URL KaBuM!; 73 pedidos, nenhum bloqueio; app/providers/kabum_basket.json (proposta); JSON-LD offers.price = relâmpago quando ativo, o à vista é o priceWithDiscount do __NEXT_DATA__; faixas de memória/SSD/GPU desatualizadas |
| T24h | Rever faixas e trocar modelos sem URL KaBuM! | Modelo | feito | modelo.md §T24h; 36 URLs (22 confirmadas + 14 a buscar); console vira Nintendo sem faixa alta; 9950X no lugar do X3D2; URL em relâmpago continua válida pelo priceWithDiscount; aprovada pelo usuário |
| T27b | Nova rodada de curadoria | Dados | feito | kabum_basket.json v2; 32/36 URLs (30 ok, 2 fora por pouco); 4 sem_modelo (RAM alto, celular baixo e médio, notebook baixo); celular não publica; 26 pedidos, nenhum bloqueio; durante o relâmpago a página /produto não traz o à vista normal (só a busca) |
| T24i | Teto de consumidor médio + preço cheio | Modelo | feito | modelo.md §T24i; teto = mín(R$ 10 mil cheio; 1,3× a referência), sem linha entusiasta; 34 URLs (23 ✅ + 11 🔎); celular fora da aba; aprovada |
| T29c | prices.py ajustado à T24i | Modelo | feito | preço cheio; 53 testes pendentes ok; 345 ok |
| T27c | Buscar as 11 vagas da T24i | Dados | feito | 28/34 URLs; kabum_basket.json v3; 5070 Ti e notebook gamer não cabem em R$ 10 mil; ajustes aprovados: GPU alto só AMD, notebook fora da aba, monitor e fonte sem alto, RAM médio 1×16 |
| T29b | prices.py ajustado à T24h | Modelo | feito | 31 modelos/36 URLs; preço anormal: > 1,5× a mediana das outras URLs do modelo ou > 1,5× o teto da faixa (a ROG de R$ 60 mil sai); relâmpago só como selo; desligado; 47 testes pendentes ok, 345 ok |
| T12c | Esqueleto de Preços: sub-abas Produtos e Por marca | Frontend | feito | app/static/prices.js; testado com /api/prices simulado; 4 estados (503/404/disabled/rede); K16–K18 testados com entrada hostil; 345 ok; o Backend mantém os nomes do §T28c |
| T28a | Regras K1, K2, K7 da KaBuM | Backend | feito | is_store("kabum.") sempre force=False; falha e sucesso da loja ≥ 24 h persistidos; DSH_CONTACT validado no UA; DSH_ENABLE_KABUM=false por padrão; cache.py só ganhou failure_ttl |
| T28b | model_since por série | Backend | feito | history.model_versions() + MODEL_VERSIONS em series.py (o Modelo declara); /api/history e /api/series devolvem model_since |
| T28c | Contrato GET /api/prices | Backend | feito | backend.md §T28c; endpoint ainda não implementado |
| T29 | Contas puras: prices.py e supply_fronts.py | Modelo | feito | flags PRICES_ENABLED/FRONTS_ENABLED = False; produção intacta; 345 ok; 39 testes novos guardados em docs/agentes/testes-pendentes/ (QA move para tests/ com permissão) |
| T30 | Coleta + ligação + T31 + fontes.md | Dados e modelo | feito | TSMC via MOPS/TWSE (93 meses); KaBuM, SEC, cesta prontos; FRONTS_ENABLED; T31: valor correto (chip solto); K9: reler até 03/02/2027; tests/ 335 ok + 10 falhas (fixam o modelo antigo); 70 novos em testes-pendentes |
| T32 | GET /api/prices, jobs, 3 cards de oferta, Preços com IPCA, prices.js no endpoint real | Backend (API, jobs) + Frontend (tela) | fazendo | parcial: API e tela feitas, aguarda provider do "dados e modelo"; sem conferência no navegador (usuário) |
| T33 | Faixa alta em monitor/fonte/console (comprimir níveis) + marketplace para celular, notebook e vagas sem modelo | Dados e modelo | fazendo | 05/11; selo "marketplace"; ≤ 20 pedidos |
| T34 | Preços: sub-aba "Por marca" vira o ranking dos produtos coletados na KaBuM, no formato do ranking atual; "Produtos" intocada | Frontend | fazendo | 05/11 |
| T35 | Cesta por busca (110 modelos, 3–5 por faixa) | Dados e modelo | parcial | 92/110 com preço, 10 categorias publicadas; 124 pedidos sem bloqueio; kabum_basket.json removido; cache com version |
| T35b | Ligar a coleta nova no collector: version=kabum.P.BASKET_VERSION; series_values kabum_model.<key>; model_history ao build_prices_view | Backend | a fazer | aguarda ok do usuário |
| T35c | Busca 200 sem lista = 'sem anúncio' sem parar a coleta; coletar os 12 modelos que faltaram; RX 6600 (termo novo ou substituto AMD) | Dados e modelo | a fazer | aguarda ok do usuário |
| T35d | Confirmar tela no formato novo (tier.models[]) | Frontend | a fazer | aguarda ok do usuário |
| T35e | Dividir a coleta semanal em vários dias (K3) | Dados e modelo | a fazer | depois |
| T42 | Comtrade mensal: cauda de 3 meses, paralelo e meses fechados no cache | Dados | feito | 10/11; restart frio 16 pedidos, quente 3 (só a cauda; meses fechados do cache.db); _CONCURRENCY 3 (baixar p/ 2 se 429); antes: 1ª coleta levou 9 min 05 s, comtrade_monthly segurou 6 min; 16 pedidos seriais, 18,2 s cada, timeout 20 s + 2 retries; série devolvida continua até 16 meses |
| T43 | /api/snapshot não espera a 1ª coleta: snapshot do cache + coleta em background; timeout por provider | Backend | feito | 10/11; cache.db de 06/11 deixou a tela de carregamento 9 min; cache.peek lê sem TTL; campo aditivo de "desatualizado" |
| T44 | Timer diário de aquecimento da coleta | infraestrutura | standby | 10/11; só quando sair do host local (decisão do usuário) |
| T42b | Comtrade mensal: falha do lote memorizada no ciclo (1 lote, ≤3 pedidos); _CONCURRENCY 1 + Retry-After no 429 | Dados | feito | teste 14:40 (KaBuM off): Comtrade 16 pedidos em 28 s, 0 falha; 10/11; teste 12:06: 79 pedidos ao Comtrade em vez de 3, 429 em 5 de 9 categorias (ficaram stale, 14 meses preservados) |
| T42c | Comtrade anual (fetch_flow): anos fechados do cache, só o ano corrente pedido | Dados | feito | 10/11; 4 anos × 4 SH = 16 pedidos por ciclo |
| T43b | http.py: timeout por provider (http_timeout_for) e sem retry em TimeoutError quando retries_on_timeout_for=False | Dados | feito | 10/11; pedido do Backend na T43 |
| T43c | Aviso na tela quando snapshot.stale, com generated_at | Frontend | a fazer | 10/11; pedido do Backend na T43; aguarda ok do usuário |
| T46 | Testes sem rede: desligar lojas/TWSE em test_collect_com_fetchers_simulados_entrega_10_chaves (fazia buscas reais na KaBuM e travava a suíte); trocar test_falha_total_nao_fica_no_memo pelo de testes-pendentes/test_comtrade_t42b.py | QA | a fazer | 10/11; incidente achado pelo Dados; aguarda permissão do usuário |
| T45 | KaBuM: 112 buscas seriais (~4 s cada) seguram a coleta em 8,5 min; medir e propor paralelismo limitado ou intervalo próprio | Dados | aguarda usuário | 10/11; Comtrade 47 s, TWSE 1,5 min, KaBuM 12:06→12:14 |
| T18 | Revisar e commitar (com aprovação) | Coordenador | a fazer | depende de T16, T17 |

## Para retomar (10/11, 15:00)

- Painéis voltaram ao Claude Code (ver registro.md): Dados t1, Backend t2, Modelo t3, Frontend t6, QA t7, Segurança t12; todos ociosos. Coordenador t10.
- Comtrade (T42/T42b/T42c): pede só os 3 últimos meses + o ano corrente; meses/anos fechados vêm do cache.db. Teste ao vivo 14:40 (cópia dos bancos, KaBuM off): 16 pedidos em 28 s, 0 falha (antes 95 pedidos, 5 de 9 categorias com 429). Coleta inteira 107 s; gargalo agora TWSE (48 pedidos, 1,5 min).
- Frequência: Comtrade/TSMC/IPCA TTL 24 h; KaBuM 7 dias (terças); séries diárias 6 h; câmbio/bolsa 15 min. Reiniciar o app não refaz busca dentro do prazo (snapshot do cache na partida + coleta em background só do que venceu).
- Limpeza feita a pedido: backup em data/backup-2026-11-10/; apagada a coleta das 14:51 UTC do history.db (84 linhas); as 59 entradas do cache.db foram vencidas (depois o servidor coletou de novo).
- Servidor principal: PID 50180, porta 8000, iniciado pelo Coordenador às 12:06 com o código antigo (antes de T42b/c/T43b) e DSH_ENABLE_KABUM=true; log em scratchpad da sessão. Antes rodava no pts/10.
- KaBuM hoje passou do teto K3 (40/dia): ~100 buscas dos testes do Dados + 112 da coleta das 12:06.
- A decidir pelo usuário:
  1. T45 KaBuM: pausa fixa 3 s (~6 min) · rodízio em 3 dias (~37/dia, ~2,7 min, cabe no K3; recomendado; Backend TTL diário + Dados mescla) · 2 simultâneas (~4 min, muda K3). Detalhe em dados.md.
  2. T46 (QA) e T43c (Frontend): enviar?
  3. Reiniciar o servidor principal com o código novo e DSH_ENABLE_KABUM=false até decidir a T45?
- Pendente antigo: Selic (bcb.selic_meta) falha em toda coleta com redirect 304.

## Para retomar (06/11, fim da tarde)

- Feito hoje (frontend): T36–T41 e ajustes diretos do Coordenador. Abas: Visão Geral · Detalhes · Preços · Gráficos · Fontes. A Fila virou a seção "Consumidor vs Datacenter" em Gráficos (investimento em IA + estoque Micron); cards Micron e NVIDIA/AMD/Intel removidos; aba Técnico removida; aba Fontes nova (snap.sources); medidor semicircular na Visão Geral e termômetro de barra em Detalhes; "estimativa nossa" → "estimativa"; #ranking → #priceRanking (corrige a rolagem em Preços); troca de aba volta ao topo.
- Removidos a pedido: "O efeito no Brasil", "Por que o dólar se mexeu", "Como ler em 30 segundos", glossário, KPI "Dados disponíveis", rodapés do termômetro e textos de Gráficos. Detalhe dos ajustes de layout em frontend.md.
- Acesso: `tailscale serve` → https://cachyos-x8664.tail240e60.ts.net (só tailnet); local http://127.0.0.1:8000. DSH_ALLOWED_HOSTS inclui o host do tailnet.
- Notícias: o usuário decidiu não mexer mais (o texto diz 7 dias; os artigos de análise seguem com 30). Explicação do dólar (fx_explanation) segue no backend sem uso na tela.
- Suíte: test_ui_contract 23 ok + 9 falhas (estrutura antiga: tendência, charts_js, drill-down, visão geral, entenda "estimativa nossa", aba técnico, dashboard seis gráficos, textos catSvg, cartão do dólar). Mais as 10 do modelo antigo. QA em standby; pendências dela: adotar testes-pendentes, aposentar as 10, atualizar as 9, teste de record_model_prices, teste do NameError de prices.py.
- Decidido manter: run.py na raiz, app/ sem src/, requirements separados. Desvios Clean (Fetched em cache.py; schemas no domínio) aguardam decisão.
- Próximos: QA (com permissão), compactar Segurança antes de usá-la, T35e (coleta semanal em vários dias), 16 modelos sem preço, commit (T18) feito manualmente pelo usuário.

## A decidir pelo usuário (04/11, 17:45)

- **T22e (Dados, pausada):** retomar os achados C1–C4 da Segurança ou deixar de lado. O campo de digitação do Dados tem um texto não enviado: "derive o anual da soma dos meses no Comtrade".
- **Fonte de importação:** o UN Comtrade deu 403 por cota esgotada (volta ~17:59). Alternativas propostas: arquivos brutos do Comex Stat (oficial, mensal, sem cota; endereço atual a confirmar) como principal e Comtrade com chave gratuita como reserva.
- **Receita da Micron (sec.memory_inventory):** suspeita de valores acumulados no ano somados como trimestre (13,6 → 23,9 → 41,5 → 54,2 bi); a razão estoque/receita 0,08 (~28 dias) deve estar subestimada. Verificação pelo Dados.
- **Card "Estoque de memória":** trocar a razão 0,08 por dias de vendas com faixa normal ("N dias · o normal é X a Y"), sem tooltip. Opções: só Micron, ou Micron + SK Hynix (DART, chave gratuita), cobrindo mais da metade do mercado. Estoque só do consumidor não existe publicamente; os indicadores aproximados são a fatia de receita da Micron em PC/celular e o preço da memória no varejo.
- **Melhoria opcional:** card da Fila avisar "UN Comtrade sem cota agora" em vez de "sem dados".
- **Opcionais da T22d:** `DSH_CACHE_FAILURE_TTL` (Backend) e o anual do Comtrade derivado da soma dos meses (Dados).
- **T18:** commit só com aprovação; não há commit desde "new files".

## Decisões do usuário (05/11)

- Painéis fechados pelo usuário: Frontend, Modelo, Documentação. Ativos: Dados (Dados+Modelo), Backend (Backend+Frontend), Coordenador; Segurança e QA parados para a revisão final.
- Economia de tokens: relatórios de até 5 linhas (detalhe nos .md); compactar os painéis longos; na próxima onda, só dois painéis (Dados+Modelo e Backend+Frontend), com Segurança e QA só como revisão final; decisões fechadas com o usuário antes de despachar.

- A análise é de hardware em geral, não só de memória; o card "Estoque de memória" vira painel de oferta com TSMC mensal, estoque NVIDIA/AMD/Intel/Micron (SEC), SK Hynix + Samsung (DART) e exportação de chips da Coreia.
- A aba Preços ganha a média de preço no mercado brasileiro, com referências: Mercado Livre (API oficial) + subitem do IPCA.
- T16 e T17 em espera. T03 feita no Brave.
- Respostas à T24: preço por cesta fixa de modelos (Modelo propõe, usuário aprova, revisão trimestral ou quando sai de linha); estoque da Micron sai da fila para a frente memória (nova quebra de histórico); Samsung fora do estoque de memória; "o normal" = P25–P75 dos últimos 5 anos; anúncio internacional do ML excluído; pesos e exposições propostos valem como ponto de partida; prévia de 20 dias da Coreia fora (não separa chips).
- Sem chave nem cadastro: só informação pública. Ficam TSMC (TWSE OpenAPI), SEC (NVIDIA, AMD, Intel, Micron) e IPCA. Saem DART (SK Hynix/Samsung), data.go.kr (exportação da Coreia) e Mercado Livre. A política "sem chave" de fontes.md continua valendo.
- Preço em reais: comparadores (Zoom/Buscapé) descartados pelo bloco anti-IA no robots.txt; tentar as lojas; se nenhuma servir, o usuário cria conta no ML Developers (exceção à regra sem chave).
- Cesta aprovada (T24e/T24f, opção B): 30 modelos, 38 URLs, baixo/médio/alto por categoria; GPU baixo e médio com NVIDIA + AMD (2 URLs cada, marcas com peso igual), topo só RTX 5090; preço à vista principal, cheio na 2ª linha, oferta relâmpago fora; visão AMD × NVIDIA numa sub-aba "Por marca" em Preços; CPU AMD × Intel fica para depois.
- T24h aprovada (05/11): faixas pelo preço real, 36 URLs, console só Nintendo, Ryzen 9 9950X, relâmpago só como selo. Regra do usuário: desconsiderar produto com preço anormal em relação ao mercado consumidor (ex.: RTX 5090 ROG de R$ 60 mil).
- 05/11: só produtos com demanda do consumidor médio (GPU de R$ 10 a 60 mil fora; o mesmo nas outras categorias). Preço principal = preço cheio da página do produto (estável durante o relâmpago); à vista na 2ª linha quando não há relâmpago.
- KaBuM: DSH_CONTACT opcional (opção 2; se houver bloqueio, volta a exigir contato). Coleta semanal às terças 6 h (collector._store_ttl), preço cheio; foco em preço médio real, não em ofertas.
- Critério da cesta (05/11): item de alto consumo pelo público médio, independente da geração. GPU: baixo RTX 3050 + RX 6600, médio RTX 5060 + RX 7600, alto RTX 5070 + RX 9070 XT. RAM baixo DDR4 8 GB.
- Mercado Livre: robots.txt bloqueia ClaudeBot/Claude-User; scraping descartado; só via API com conta dev.
- Fonte de preço em reais: só a KaBuM. Samsung, Dell e Lenovo descartadas pelo usuário. Mercado Livre fica como reforço opcional (o usuário está criando a conta).

## Decisões do usuário (04/11)

- A QA só é acionada com permissão explícita do usuário.
- O teste manual do usuário substitui a T03; os defeitos que ele achar vão para a T12.
- Card "Câmbio e macro Brasil" virou "Dólar" (só o rótulo; peso 19%, sinais PTAX + IGP-M mantidos).
- Detalhes ordena os cards de causas só por pressão; Visão Geral continua por pressão × peso.
- Primeira abertura mostra só a tela de busca (sem rodapé de dica); a T20 foi desfeita.
- Cache das buscas gravado em SQLite (`data/cache.db`), não em JSON; falhas guardadas por 30 min.
- `requirements.txt` e `requirements-dev.txt` passaram a ser do Backend.

## Concluídas

| ID | Tarefa | Função | Status | Observação |
| --- | --- | --- | --- | --- |
| T01 | Corrigir `fontes.md` e README (GDELT, sete vetores, árvore, Linux) | Documentação | feito | 173 testes ok; pendências da seção 8 do README vão para T17 |
| T02 | Auditoria de segurança nas cinco categorias | Segurança | feito | 9 achados (S1–S9) em seguranca.md; history já validado |
| T04 | Testes Federal Register, USGS, SEC, detecção de bloqueio | QA | feito | test_fedreg/usgs/sec/http_challenge; achou 2 defeitos (→T09b) |
| T05 | Comex Stat: religar, substituir ou rejeitar | Dados | feito | SUBSTITUIR: Comex Stat rejeitado (POST 429 WAF); UN Comtrade mensal (fetch_monthly_imports) |
| T06 | Tirar a fila do teto de 100 | Modelo | feito | estoque em z-score; fila ~89; quebra comparação com 42 pontos antigos |
| T07 | Altas estimadas × IPCA (IBGE 7060); revisar pesos | Modelo | feito | repasse 85% passa a valer em 90 dias (30/90 no horizonte); projeção BR ~9% → ~3%; backtest aguarda IPCA de out |
| T08 | Agrupar notícia em idiomas diferentes | Modelo | feito | agrupa por empresa/ticker/país/tema; corroboradas 1 → 3 |
| T08b | build_digest junta empresas diferentes por _similar (Samsung × Micron) | Modelo → QA | feito | 344 ok, 0 xfail |
| T09 | Correções da auditoria em `http.py` | Dados | feito | S1,S3,S4,S5,S9 + body_snippet; teto 20 MB/5 MB por feed; redirect só https público; feed Tom's Hardware → feeds.xml; 206 ok |
| T09b | fedreg plural "Removals" + ChallengeDetected sem retry em 403/429/503 | Dados → QA | feito | 210 ok; xfail removidos |
| T09c | `defusedxml>=0.7.1` em requirements.txt | Backend | feito | defusedxml 0.7.1 instalado e em uso no RSS; 344 ok |
| T10 | Validar `/api/history`, limitar `/api/refresh` | Backend | feito | refresh com header+60 s+single-flight; CSP, nosniff, TrustedHost; 206 testes ok |
| T11 | Ligar UN Comtrade mensal no coletor (comtrade_monthly.*), flag própria | Backend | feito | 9 jobs comtrade_monthly.*, flag DSH_ENABLE_COMTRADE_MONTHLY; Comex Stat desligado |
| T11b | ranking._imports lê comtrade_monthly.*; casar AAAA-MM do ano anterior | Modelo | feito | Comtrade com prioridade, Comex Stat alternativa; mês do ano anterior pela string |
| T10b | /api/methodology: fórmula nova da fila + FX_PASSTHROUGH_DAYS; não apagar pontos antigos + campo source em CategoryImport | Backend | feito | methodology nova; model_since marca 42 pontos antigos (nada apagado); source em CategoryImport |
| T13b | Fórmula da fila (index.html:491) + "sete vetores" (index.html:483) + rótulo da fonte de importação | Frontend | feito | fórmula, sete vetores, fonte da importação com fallback; 206 testes ok |
| T13c | Evolução: trecho da fila antes de model_since esmaecido | Frontend | feito | trecho antigo pontilhado/esmaecido na Evolução e no Plotly; 206 testes ok |
| T11c | Apagar supply.INVENTORY_SCALE sem uso | Modelo | feito | 206 testes ok |
| T19a | Tese do câmbio como dissertação sobre o dólar (~350–450 caracteres) | Modelo | feito | 440 caracteres; 344 ok; MODEL_VERSION muda → backfill de 30 dias refeito uma vez no próximo start |
| T19b | Card do dólar no padrão dos outros; fx-why recolhível | Frontend | feito | fx-why em details recolhível; 344 ok; conferido a 900/560 px |
| T13 | Exibição segura de manchetes | Frontend | feito | safeUrl + POST refresh; 206 testes ok; CSP repassada ao Backend |
| T14 | Teste notícia em dois idiomas | QA | feito | test_news_multilang (16); achou defeito → T08b |
| T15 | Teste da nova conta da fila | QA | feito | test_queue_model (8), test_fx_passthrough (9); 343 ok, 1 xfail |
| T05t/T11b-t | Testes Comtrade mensal + ranking._imports | QA | feito | test_comtrade_monthly (13), test_ranking_imports (10) |
| T10t/T11-t | Testes refresh/headers/TrustedHost/coletor/methodology/safeUrl | QA | feito | test_api_security (24), test_collector_comtrade (7), test_safe_url (11) |
| T16c | 11 casos offline das defesas da T09 (dados.md §T09) | QA | feito | test_http_defenses.py (36); 269 ok |
| T16b | Testes offline do fetch_monthly_imports (7 casos em dados.md) + 8 casos da T11b + 7 casos da T11/T10b | QA | feito | coberto por T05t/T11b-t e T10t/T11-t |
| T20 | Busca antes da exibição: abas e gráficos só depois do primeiro snapshot | Frontend → QA | desfeita | usuário queria só a tela de busca; ver T20b |
| T20b | Primeira abertura: só a tela de busca em tela cheia (body.booting) + "Tentar de novo" | Frontend → QA | feito | test_primeira_abertura_mostra_so_a_tela_de_busca; 345 ok |
| T20c | Remover o rodapé (#loadingHint) da tela de busca | Frontend → QA | feito | contrato exige ausência do loadingHint; 345 ok |
| T21a | Vetor cambio_br vira "Dólar" (só o rótulo) | Modelo | feito | label "Dólar"; 345 ok; precisa reiniciar o servidor |
| T21b | Cards de causas ordenados por pontuação (decisão do usuário: só por pressão) | Frontend | feito | ordenado por score; no snapshot salvo logística 79,4 vem antes do dólar 70,8; 345 ok |
| T22a | Cache persistente em SQLite (data/cache.db; payload em JSON; validade em UTC) | Dados | feito | save/load síncronos; round-trip 55/55; corrompido → movido e recomeça; 345 ok |
| T22b | Ligar cache em disco no startup e após cada coleta; DSH_CACHE_PATH | Backend | feito | load no start, save após coleta e ao desligar; 2º start 42 do cache; 3º sem Comtrade 3 s |
| T22d | Cache negativo (falha 30 min, persistida) + disjuntor 403 no Comtrade (Comtrade fora do ar refazia 13 buscas a cada start) | Dados | feito | 403 era cota esgotada (volta ~17:59 local); falha guardada 30 min; disjuntor: 1 pedido em vez de 160; 2º start 0 pedidos; 345 ok |
| T22c | Revisar leitura do cache do disco (cache.py, comtrade disjuntor) | Segurança | feito | sem execução de código; C1 média, C2–C4 baixas → T22e/T22f |
| T22f | Validar cache_path ≠ history e sufixo .db | Backend | feito | erro claro na inicialização; resolve() pega link e ..; 345 ok |
