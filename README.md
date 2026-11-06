# DataSearch Hardware

Coletor e analisador de **pressão geopolítica sobre o preço de hardware para o
consumidor doméstico brasileiro**. FastAPI + painel estático, sem nenhuma chave
de API — todas as fontes são públicas e abertas.

Estado: **funcional e testado end-to-end** em 03/11/2026, com ressalvas
documentadas na seção [Estado real da coleta](#estado-real-da-coleta).

---

## 1. O que o projeto faz

Traduz sete vetores geopolíticos/econômicos em sinais mensuráveis com dado
público, agrega num **Índice de Pressão de Hardware (IPH, 0–100)** e projeta o
impacto por categoria de hardware, separando o efeito global (em dólar) do
efeito Brasil (câmbio + carga de importação).

O painel tem sete abas e abre na leitura simples:

- **Visão Geral** — leitura de 1 minuto: o que a pressão está dizendo, os três
  fatores que mais pesam hoje, os produtos com maior alta estimada e quatro
  sinais para acompanhar. Há um guia de “como ler em 30 segundos” e um glossário
  curto; os detalhes técnicos ficam na aba Técnico.
- **Detalhes** — gauge da pressão, indicadores do Brasil, os sete fatores com
  seus sinais, camada Brasil (dólar e inflação), inflação de eletrônicos por
  subitem e manchetes (filtro interno de release/agregador e selo de
  corroboração). Clicar num sinal abre a série dele na aba Evolução.
- **Gráficos** — seis gráficos Plotly: pressão global e Brasil, fila ×
  investimento em IA, alta estimada por produto, detalhe por produto com
  inflação oficial, radar dos fatores e dispersão pressão × estimativa.
  Período 7d/30d/90d/1a, hover unificado, legenda clicável, clique no produto
  para abrir o detalhe e download PNG pelo modebar. Plotly vem de uma cópia
  local e só carrega nesta aba.
- **Evolução** — histórico gravado a cada ciclo em SQLite, com gráfico
  interativo (crosshair, tooltip, legenda clicável e períodos
  Tudo/24h/7d/30d/90d/1a). O botão **Tudo** usa o primeiro ponto real de cada
  série. Os demais períodos só ficam clicáveis quando o banco já cobre a
  janela; o eixo mostra a janela pedida e a série mais curta aparece só no
  trecho em que existe. Lacuna de dado quebra a linha; nada é interpolado.
- **Fila** — investimento dos cinco maiores compradores de capacidade de IA,
  receita de NVIDIA/Micron/AMD, estoque de memória da Micron e volume importado
  de memória pelo Brasil. Um índice de 0 a 100 coloca o consumidor doméstico no
  fim da fila quando o investimento acelera e o estoque cai. A nota é uma
  **estimativa nossa**; os dados de investimento e estoque são oficiais.
- **Preços** — variação por tipo de hardware (placa de vídeo, memória,
  HD/SSD, processador, placa-mãe, fonte, celular, notebook, monitor, console),
  ordenado pela estimativa de 30 dias para o Brasil, com o cálculo completo
  por fator e a carga tributária em `<details>`.
- **Técnico** — metodologia, fórmula da fila, limites do modelo, tabela de
  fontes/frescor e vocabulário técnico. É a aba para quem quer auditar pesos,
  betas e links da API; a leitura simples não depende dela.

A página se atualiza **a cada 15 minutos** (loop no backend + polling no
frontend, com contagem regressiva visível). O histórico sobrevive ao restart.

No primeiro carregamento, a tela mostra o **percentual de buscas concluídas**
(`/api/progress`) e quantas ainda faltam. O número é uma contagem real, não uma
previsão de tempo: como as fontes rodam em paralelo, ele pode avançar em saltos
e ficar parado nas consultas mais lentas. Ao atualizar com o painel já aberto,
o mesmo percentual aparece na barra de status.

**O que fica salvo:** o snapshot completo (IPH, filas, ranking, textos) vive em
memória. O que vai para `data/history.db` são as séries que alimentam a aba
Evolução — pontos observados e agregados modelados. Reiniciar o app **não**
transforma esse histórico em cache da coleta: o próximo ciclo refaz as janelas
configuradas de cada fonte (Yahoo ~1 ano, BCB 3 anos, Comtrade 4 anos etc.).
O banco serve para consultar o passado, não para pular a coleta do presente.

---

## 2. Princípio de honestidade do painel

Todo número exibido é marcado como **observado** ou **modelado**, e toda
métrica rastreia até uma fonte com data de referência e status. Na leitura
simples, a interface traduz esses rótulos para **dado oficial** e **estimativa
nossa**; a aba Técnico mantém os termos originais.

| Tipo | Significado | Exemplos |
|---|---|---|
| `observado` | Medição oficial de terceiro | IPCA/IBGE, PTAX/BCB, PPI/FRED, Comtrade |
| `modelado` | Saída da nossa heurística | IPH, projeções de 30 dias, pressão por categoria |

Quando uma fonte cai, o cache serve o último valor bom marcado como `stale` e
a `coverage` do índice cai — **nunca preenchemos buraco com chute**. A lista
`degraded` no `/api/health` e na tabela da aba Técnico mostra exatamente o que
faltou.

---

## 3. Fontes públicas usadas

Pesquisadas e validadas ao vivo. Nenhuma exige cadastro ou chave.

### Brasil

| Fonte | O que entrega | Verificação |
|---|---|---|
| **BCB / SGS** `api.bcb.gov.br` | PTAX USD/BRL (série 1), IPCA (433), Selic meta (432), IGP-M (189) | ✅ confirmado |
| **IBGE / SIDRA agregado 7060** | IPCA **por subitem**: `Computador pessoal` (47641), `Aparelho telefônico` (7794), `Videogame/console` (47640), `Televisor` (7542) | ✅ confirmado |
| **Comex Stat (MDIC/SECEX)** | Importação por NCM/SH6: valor FOB e peso → US$/kg importado | ⏸️ desligado por padrão (WAF 429) |

> **Por que o IBGE serve.** A dúvida levantada durante o desenvolvimento era
> pertinente: o agregado genérico (1737) só dá o IPCA cheio. O dado de hardware
> está no **agregado 7060**, que abre o IPCA até subitem. Confirmado ao vivo em
> 04/08/2026: `Computador pessoal` acumulava **+6,58% em 12 meses** e
> `Videogame (console)` **+13,18%**, com a série mensal acelerando
> (2,82 / 2,94 / 1,42 / 1,77 nos meses anteriores). É a evidência oficial
> brasileira da tese do projeto.

### Internacionais

| Fonte | O que entrega | Verificação |
|---|---|---|
| **FRED** (St. Louis Fed), CSV keyless | PPI semicondutores (`PCU334413334413`), índice de preço de importação (`IZ3344`), Brent (`DCOILBRENTEU`), cobre (`PCOPPUSDM`), alumínio (`PALUMUSDM`), gás natural EU (`PNGASEUUSDM`), CPI computadores EUA (`CUSR0000SEEE01`), USD/BRL (`DEXBZUS`), Fed funds (`DFF`), PPI de frete marítimo (`PCU483111483111`), tarifas alfandegárias arrecadadas pelos EUA (`B235RC1Q027SBEA`) | ✅ confirmado |
| **FMI / PCPS via FRED** | Índices globais de metais (`PMETAINDEXM`), energia (`PNRGINDEXM`) e todas as commodities (`PALLFNFINDEXM`) | ✅ confirmado |
| **Federal Register (BIS)** | Regras do Bureau of Industry and Security sobre chips, China e Entity List; sentido (aperto +1, revisão +0,5, alívio −1) lido no título; série diária líquida | ✅ confirmado (04/11/2026) |
| **USGS (FDSN Event API)** | Terremotos ≥ 5,5 a até 150 km de polos de chips (Hsinchu, Tainan, Kumamoto, Kitakami, Yokkaichi, Pyeongtaek/Icheon); série diária da maior magnitude, 0 em dia sem evento | ✅ confirmado (04/11/2026) |
| **RSS público** | 43 feeds: tecnologia (Tom's Hardware, TechPowerUp, Wccftech, Ars Technica, The Register); Vale do Silício (TechCrunch, The Verge, CNBC, Wired, Bloomberg); imprensa geral (Guardian, Al Jazeera, BBC, Bloomberg mercados); Europa (FT, Euronews, DW, Politico Europe); leste europeu (Kyiv Independent, Notes from Poland, Balkan Insight, Emerging Europe); Ásia (Nikkei Asia, SCMP, DigiTimes, The Diplomat, CNA); Brasil (Tecnoblog, Canaltech, Olhar Digital, Gazeta do Povo, Brasil 247); análise (EE Times, Semiconductor Engineering, IEEE Spectrum, Stratechery, The Conversation, Lowy Interpreter, Project Syndicate, ChinaTalk). Fora, com motivo, no código: Reuters, AP e AFP (sem RSS público acessível: 401/403), Washington Post, CNN, Euractiv e outros. Tudo passa por `is_price_relevant` (impacto no preço no Brasil), notícia 7 dias / análise 30 dias, no máximo 2 por veículo, até 3 análises, até 15 itens (3 páginas de 5) | ✅ testado em 04/11/2026 |
| **UN Comtrade** (preview público) | Fluxo físico de importação: HS 280429 (gases raros/hélio), 280530 (terras raras), 854232 (memórias), 854231 (processadores) | ✅ confirmado |
| **SEC EDGAR — XBRL `companyconcept`** | Capex trimestral de MSFT/AMZN/GOOGL/META/ORCL, receita de NVDA/MU/AMD e estoque ÷ receita da Micron — a base da aba **Fila** | ✅ confirmado |
| **Yahoo Finance v8** | 16 tickers: SOXX, NVDA, MU, TSM, REMX, Brent, cobre, USD/BRL; bolsa de Taiwan (`^TWII`) e USD/TWD; DXY, VIX e as moedas de pares emergentes (MXN, CLP, ZAR, COP) do cartão do dólar | ✅ confirmado |

### Fontes descartadas na pesquisa

A política completa, com marcadores de detecção e data de verificação, está em
[`docs/fontes.md`](docs/fontes.md).

- **Stooq** — passou a devolver *"This site requires JavaScript to verify your
  browser"*. Removido do código; o Yahoo é fonte única e, em falha, o cache
  serve `stale`.
- **IMF SDMX próprio** — `dataservices.imf.org` **não resolve mais DNS**. O
  sucessor `api.imf.org/external/sdmx/2.1/` responde, mas a estrutura de chaves
  do PCPS v9 mudou e todas as variantes testadas retornaram dataset vazio
  (0 observações). Substituído pelo espelho do FRED, que é o mesmo dado do FMI.
- **World Bank Pink Sheet** — distribuído só como PDF/XLSX, sem API JSON.
- **BLS public API v1** — keyless, mas com cota de 25 requisições/dia; inviável
  para um ciclo de 15 minutos.
- **GDELT DOC 2.0** — removido do código em 04/11/2026: respondia `HTTP 429` na
  maior parte dos ciclos, mesmo com 5 s entre consultas. Manchetes vêm só dos
  feeds RSS; controles de exportação, do Federal Register.

---

## 4. Os sete vetores de pressão

Definidos em `app/domain/drivers.py`, com pesos auditáveis via `/api/methodology`.

| Vetor | Peso | Tese | Sinais |
|---|---|---|---|
| **Alocação de chips: datacenter × consumidor** | 22% | HBM para IA e DRAM de consumo dividem as mesmas linhas; cada lote desviado para hyperscaler reduz oferta no varejo. | capex (SEC), estoque de memória, PPI, MU, SOXX, TSM, NVDA, importação BR de memória e processadores |
| **Câmbio e macro Brasil** | 19% | Hardware é importado e cotado em dólar; o câmbio é o canal mais rápido e forte de repasse. | PTAX, IGP-M |
| **Estreito de Ormuz e hélio** | 15% | Catar responde por ~⅓ do hélio mundial e escoa por Ormuz. Hélio é insumo sem substituto em litografia e gravação. | Brent, gás natural, energia FMI, valor unitário importado de hélio |
| **Terras raras e ímãs** | 13% | Neodímio e disprósio em motores de HD, alto-falantes e vibração; cadeia concentrada e já usada como instrumento de política externa. | REMX, valor unitário importado |
| **Metais industriais e energia** | 11% | Cobre em trilhas e dissipadores, alumínio em gabinetes — o piso físico de custo. | cobre, alumínio, metais FMI |
| **Frete, tarifas e logística** | 10% | Desvios de rota e tarifas encarecem o frete, que no Brasil entra na base de cálculo do imposto. | preço de importação de semicondutores, PPI de frete marítimo (FRED), tarifas alfandegárias arrecadadas pelos EUA (FRED), CPI de computadores EUA |
| **Taiwan e disputa EUA–China por chips** | 10% | Quase toda a fabricação de ponta está em Taiwan, sob risco militar e sísmico; memória depende de Japão e Coreia; os controles de exportação dos EUA reorganizam a oferta. | bolsa de Taiwan contra SOXX (invertido), dólar/TWD, maior terremoto perto de fábricas (USGS), regras do BIS no Federal Register (`mode="sum"`) |

**Janelas.** Sinais diários (mercado, câmbio, terremotos) olham os últimos
**30 dias**; ao encurtar de 90 para 30, a escala dos sinais de mercado foi
multiplicada por √(30/90) ≈ 0,58. Séries mensais, trimestrais e anuais mantêm
janelas longas. Todo sinal é medido: as contagens de notícias do GDELT saíram
do índice em 04/11/2026 (a fonte respondia 429 na maior parte dos ciclos).
Terremoto usa `mode="peak"`: pressão pelo pico acima de 5,5 na janela, nunca
alívio.

---

## 5. Metodologia do índice

```
sinal      → variação % na janela → pressão 0-100 via  50 + 50·tanh(Δ%/escala)
driver     → média ponderada dos sinais disponíveis (pesos renormalizados)
IPH        → média ponderada dos drivers
IPH-Brasil → mesma média com peso 1,6× no vetor câmbio
```

A saturação por `tanh` impede que um único choque domine o índice inteiro. A
`escala` de cada sinal é o parâmetro de calibração e está exposto no código de
propósito, para poder ser auditado e ajustado.

**Projeção por categoria:**

```
proj_global_30d = Σ (beta_renormalizado · (score_driver − 50)/50) · sensibilidade_categoria · 30/90
proj_brasil_30d = ((1 + proj_global/100) · (1 + Δcâmbio_30d · 0,85/100) − 1) · 100
```

A sensibilidade de cada categoria foi calibrada para 90 dias; o horizonte
exibido é 30 dias, convertido linearmente (`ranking.HORIZON_FACTOR`).

**Por que o dólar se mexeu** (`app/domain/fx.py`, cartão do dólar em
Detalhes). Comparação medida em 30 dias, fora do índice: real contra pares
emergentes (peso mexicano, peso chileno, rand, peso colombiano — Yahoo), DXY,
diferencial Selic − Fed funds (BCB/FRED `DFF`), VIX e commodities do FMI. A
"parte brasileira" é o quanto o real se moveu além dos pares — indica de onde
veio a pressão, não prova a causa. Impacto: variação × repasse de 85% e custo
de desembarque de US$ 100 com a carga mediana de importação.

**Histórico reconstruído.** Os dias anteriores ao primeiro ciclo ao vivo (até
30) são recalculados com as séries cortadas em cada data e gravados como
`kind='reconstructed'`; a Evolução os desenha tracejados. Séries mensais entram
pela data de referência, não pela de publicação — limite declarado. Só ciclos
com cobertura ≥ 90% reconstroem, e mudar o modelo refaz a reconstrução.

Duas decisões metodológicas importantes:

1. **O câmbio não entra na projeção global.** A projeção global é em dólar; os
   betas são renormalizados excluindo o vetor Brasil. Há teste garantindo isso
   (`test_cambio_nao_entra_na_projecao_global`).
2. **Imposto ad valorem não multiplica variação percentual.** Se o custo de
   desembarque sobe 10% em reais, o preço final sobe ~10% — os tributos escalam
   proporcionalmente. Multiplicar a variação % pela carga tributária seria
   inflar o número. A carga aparece onde de fato importa: no campo
   `brl_impact_per_100usd`, o impacto **absoluto** em reais.

**Repasse cambial assumido:** 85% em um trimestre.

---

## 6. Estrutura

```
datasearch_hardware/
├── app/
│   ├── main.py              # FastAPI, lifespan, loop de 15 min, endpoints
│   ├── config.py            # settings (env DSH_*), TTLs por classe de fonte
│   ├── schemas.py           # Pydantic — todo campo carrega proveniência
│   ├── http.py              # httpx, retry, semáforos, disjuntor, ChallengeDetected
│   ├── cache.py             # TTL com degradação para 'stale'
│   ├── series_utils.py      # variação %, composição, tanh de pressão
│   ├── providers/           # bcb, ibge, comexstat, fred, comtrade, markets, sec, usgs, fedreg, news_rss
│   ├── services/
│   │   ├── collector.py     # orquestra a coleta e monta o Snapshot
│   │   ├── news.py          # coleta de manchetes RSS e digest
│   │   ├── progress.py      # percentual de buscas concluídas para a tela de loading
│   │   └── history.py       # SQLite: gravação, bucketing, retenção, consulta
│   ├── domain/
│   │   ├── drivers.py       # os 7 vetores e seus sinais
│   │   ├── catalog.py       # 10 categorias: betas, NCM/SH6, subitem IPCA, tributos
│   │   ├── analyzer.py      # IPH e camada Brasil
│   │   ├── supply.py        # fila do consumidor (capex x estoque)
│   │   ├── ranking.py       # ranking por categoria (projeção de 30 dias)
│   │   ├── fx.py            # "por que o dólar se mexeu"
│   │   ├── news.py          # filtro de relevância, deduplicação, corroboração, digest
│   │   ├── backfill.py      # reconstrução diária do IPH (até 30 dias)
│   │   └── series.py        # catálogo de séries do /api/series
│   └── static/              # index.html, styles.css, editorial.css, app.js, charts.js, dashboard.js, icons.js
│       └── vendor/          # plotly-2.35.2.min.js (MIT), carregado sob demanda
├── docs/
│   ├── fontes.md            # política de fontes (normativa)
│   ├── PRD.md               # plano de trabalho por função
│   └── agentes/             # papéis, registro e relatórios dos agentes
├── tests/                   # sem rede: analyzer, backfill, fx, history, news_digest,
│                            #   news_rss, progress, source_policy, supply, ui_contract
├── requirements.txt         # runtime
├── requirements-dev.txt     # + pytest
├── .env.example
└── run.py
```

### Endpoints

| Rota | Função |
|---|---|
| `GET /` | Painel |
| `GET /api/snapshot` | Payload completo (`?force=true` ignora cache) |
| `GET /api/progress` | Percentual e contagem de buscas do ciclo em andamento |
| `POST /api/refresh` | Força nova coleta |
| `GET /api/health` | Cobertura, fontes ok/total, degradadas (503 enquanto aquece) |
| `GET /api/sources` | Proveniência de cada fonte |
| `GET /api/methodology` | Pesos, betas e escalas — para auditoria |
| `GET /api/series` | Catálogo do histórico, com pontos e primeiro/último instante por série |
| `GET /api/history` | Histórico: `?range=90d&series=iph,iph_br&bucket=auto` (aceita `range=all`) |
| `GET /api/cache` | Diagnóstico do cache |
| `GET /docs` | OpenAPI |

---

## 7. Como rodar

**Windows (PowerShell)**, na pasta do projeto:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe run.py
```

**Linux / macOS**, na pasta do projeto:

```bash
python3 -m venv venv
source venv/bin/activate        # no fish: source venv/bin/activate.fish
python -m pip install -r requirements.txt
python run.py
```

Abre em `http://127.0.0.1:8000`. Para outra porta: `$env:DSH_PORT="8077"`
(PowerShell) ou `DSH_PORT=8077 python run.py` (bash/zsh).

A primeira coleta leva de 40s a 3min dependendo da rede — o painel mostra o
estado de aquecimento e o percentual de buscas concluídas. Fontes individuais
podem ser desligadas via `.env` (veja `.env.example`) se a sua rede bloquear
algum domínio.

A aba **Gráficos** usa Plotly 2.35.2 vendorizado em `app/static/vendor/` (MIT):
não há CDN no boot e o arquivo só é solicitado quando a aba é aberta. O
restante do painel continua em SVG puro, sem build step.

Testes (offline — nenhum toca a rede):

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

---

## 8. Estado real da coleta

Última execução verificada nesta máquina (03/11/2026, Comex Stat desligado):

```
34 / 38 fontes OK  ·  cobertura do índice 92%
IPH 56,9  ·  IPH-Brasil 57,0
Fila do consumidor 100,0 (crítica)  ·  capex TTM US$ 691,0 bi (+93,5% a/a)
```

**O que está confirmado funcionando:** BCB (3/4 nesta rodada), IBGE (1/1), FRED (11/11),
Comtrade (4/4), mercados Yahoo (8/8), SEC EDGAR (3/3). Em 04/11/2026: USGS e os 43 feeds RSS (43/43).

**Ressalvas honestas:**

1. **Comex Stat — desligado por padrão.** Todas as 9 categorias retornavam
   `HTTP 429` nesta rede, inclusive `GET /docs`; o endpoint fica atrás de um WAF.
   A implementação chegou a enviar `Origin`/`Referer` do painel oficial para se
   identificar — headers **removidos** por não serem identificação honesta. A
   fonte agora vem com `enable_comexstat=False`; a coluna "Preço de importação"
   de Preços fica vazia até validação em rede sem WAF. O contrato do payload
   segue não validado ao vivo (`PAYLOAD_VARIANTS` em `app/providers/comexstat.py`).

2. **GDELT — removido (04/11/2026).** Respondia 429 na maior parte dos
   ciclos mesmo com 5 s entre consultas. Os sinais de cobertura noticiosa
   foram trocados por dados medidos (bolsa e moeda de Taiwan, terremotos do
   USGS, PPI de frete, tarifas arrecadadas) e as manchetes passaram a vir só do
   RSS. Controles de exportação EUA–China passaram a vir do Federal Register
   (regras do BIS). Reavaliado em 04/11/2026 só para as lacunas: consultas por
   domínio de Reuters/AP/AFP voltaram vazias e a de controles levou 429 — o
   GDELT segue fora. Reuters, AP e AFP não aparecem (sem RSS público
   acessível: 401/403).

3. **A fila saturou em 100,0 na primeira execução.** Capex TTM +93,5% a/a e
   estoque/receita −65,2% a/a levam o `tanh` a 0,9996. Não é bug de arredondamento
   nem dado inventado: é o limite declarado do modelo. O valor continua
   monotônico e a fórmula está em `/api/methodology`.

4. **O frontend foi verificado em Firefox 158 headless** via WebDriver, em
   03/11/2026, na versão de seis abas: seis gráficos Plotly, troca de período
   (24h a 1 ano), drill-down por `<select>` e por clique na barra, zero erro JS
   e zero container vazio. A aba de evolução (então chamada Tendência) foi
   conferida com histórico curto: o eixo agora mostra o trecho observado em vez
   de espremer os pontos na borda da janela de 90 dias. Depois disso, a
   simplificação para sete abas (nova aba
   **Técnico** e textos de consumidor) foi validada por **92 testes estáticos**
   e `node --check`; a checagem visual não foi refeita nesta etapa. A tela de
   loading com percentual também foi validada por contrato estático e testes
   offline, sem abrir navegador. A camada editorial (`editorial.css`) é
   carregada depois do CSS base e cobre capa, ranking, evolução, detalhe e
   estados de foco; o visual final ainda depende de conferência manual. O que
   **não** foi testado: leitores de tela,
   navegadores muito antigos e o comportamento em janela estreita real (o CSS
   tem breakpoints em 900 px e 560 px).

5. **Os betas, pesos e multiplicadores tributários são heurísticos.** São
   estimativas de ordem de grandeza feitas para explicar mecanismo, não
   apuração fiscal nem modelo econométrico calibrado. Estão todos expostos em
   `/api/methodology` justamente para serem contestados e ajustados.

---

## 9. Aviso

Índices e projeções deste painel são resultado de um modelo heurístico próprio.
**Não são previsão validada nem recomendação de compra.** Os campos marcados
como observados são medições oficiais de terceiros; os marcados como modelados
são estimativa nossa.
