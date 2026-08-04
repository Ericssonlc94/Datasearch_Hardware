<<<<<<< HEAD
# Datasearch_Hardware
Projeto webapp de coleta e analise de dados de tendencias de preço de Hardware no mercado.
=======
# DataSearch Hardware

Coletor e analisador de **pressão geopolítica sobre o preço de hardware para o
consumidor doméstico brasileiro**. FastAPI + painel estático, sem nenhuma chave
de API — todas as fontes são públicas e abertas.

Estado: **funcional e testado end-to-end** em 04/08/2026, com ressalvas
documentadas na seção [Estado real da coleta](#estado-real-da-coleta).

---

## 1. O que o projeto faz

Traduz seis vetores geopolíticos/econômicos em sinais mensuráveis com dado
público, agrega num **Índice de Pressão de Hardware (IPH, 0–100)** e projeta o
impacto por categoria de hardware, separando o efeito global (em dólar) do
efeito Brasil (câmbio + carga de importação).

O painel tem duas abas, conforme especificado:

- **Visão Geral** — gauge do IPH, KPIs, os seis vetores com seus sinais,
  camada Brasil (PTAX e IPCA), IPCA de eletrônicos por subitem, manchetes e
  tabela de proveniência das fontes.
- **Ranking** — variação por tipo de hardware (placa de vídeo, memória,
  HD/SSD, processador, placa-mãe, fonte, celular, notebook, monitor, console),
  ordenado pela projeção de 90 dias para o Brasil.

A página se atualiza **a cada 15 minutos** (loop no backend + polling no
frontend, com contagem regressiva visível).

---

## 2. Princípio de honestidade do painel

Todo número exibido é marcado como **observado** ou **modelado**, e toda
métrica rastreia até uma fonte com data de referência e status.

| Tipo | Significado | Exemplos |
|---|---|---|
| `observado` | Medição oficial de terceiro | IPCA/IBGE, PTAX/BCB, PPI/FRED, Comtrade |
| `modelado` | Saída da nossa heurística | IPH, projeções de 90 dias, pressão por categoria |

Quando uma fonte cai, o cache serve o último valor bom marcado como `stale` e
a `coverage` do índice cai — **nunca preenchemos buraco com chute**. A lista
`degraded` no `/api/health` e na aba de fontes mostra exatamente o que faltou.

---

## 3. Fontes públicas usadas

Pesquisadas e validadas ao vivo. Nenhuma exige cadastro ou chave.

### Brasil

| Fonte | O que entrega | Verificação |
|---|---|---|
| **BCB / SGS** `api.bcb.gov.br` | PTAX USD/BRL (série 1), IPCA (433), Selic meta (432), IGP-M (189) | ✅ confirmado |
| **IBGE / SIDRA agregado 7060** | IPCA **por subitem**: `Computador pessoal` (47641), `Aparelho telefônico` (7794), `Videogame/console` (47640), `Televisor` (7542) | ✅ confirmado |
| **Comex Stat (MDIC/SECEX)** | Importação por NCM/SH6: valor FOB e peso → US$/kg importado | ⚠️ ver ressalva |

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
| **FRED** (St. Louis Fed), CSV keyless | PPI semicondutores (`PCU334413334413`), índice de preço de importação (`IZ3344`), Brent (`DCOILBRENTEU`), cobre (`PCOPPUSDM`), alumínio (`PALUMUSDM`), gás natural EU (`PNGASEUUSDM`), CPI computadores EUA (`CUSR0000SEEE01`), USD/BRL (`DEXBZUS`) | ✅ confirmado |
| **FMI / PCPS via FRED** | Índices globais de metais (`PMETAINDEXM`), energia (`PNRGINDEXM`) e todas as commodities (`PALLFNFINDEXM`) | ✅ confirmado |
| **GDELT DOC 2.0** | Intensidade de cobertura noticiosa por tema geopolítico (Ormuz, hélio, terras raras, demanda de chips, tarifas, frete) | ✅ confirmado |
| **UN Comtrade** (preview público) | Fluxo físico de importação: HS 280429 (gases raros/hélio), 280530 (terras raras), 854232 (memórias), 854231 (processadores) | ✅ confirmado |
| **Yahoo Finance v8** + **Stooq** (fallback) | SOXX, NVDA, MU, TSM, REMX, Brent, cobre, USD/BRL | ✅ confirmado |

### Fontes descartadas na pesquisa

- **IMF SDMX próprio** — `dataservices.imf.org` **não resolve mais DNS**. O
  sucessor `api.imf.org/external/sdmx/2.1/` responde, mas a estrutura de chaves
  do PCPS v9 mudou e todas as variantes testadas retornaram dataset vazio
  (0 observações). Substituído pelo espelho do FRED, que é o mesmo dado do FMI.
- **World Bank Pink Sheet** — distribuído só como PDF/XLSX, sem API JSON.
- **BLS public API v1** — keyless, mas com cota de 25 requisições/dia; inviável
  para um ciclo de 15 minutos.

---

## 4. Os seis vetores de pressão

Definidos em `app/domain/drivers.py`, com pesos auditáveis via `/api/methodology`.

| Vetor | Peso | Tese |
|---|---|---|
| **Demanda de datacenter por microchips** | 24% | HBM para IA e DRAM de consumo dividem as mesmas linhas; cada lote desviado para hyperscaler reduz oferta no varejo. |
| **Câmbio e macro Brasil** | 20% | Hardware é importado e cotado em dólar; o câmbio é o canal mais rápido e forte de repasse. |
| **Estreito de Ormuz e hélio** | 16% | Catar responde por ~⅓ do hélio mundial e escoa por Ormuz. Hélio é insumo sem substituto em litografia e gravação. |
| **Terras raras e ímãs** | 14% | Neodímio e disprósio em motores de HD, alto-falantes e vibração; cadeia concentrada e já usada como instrumento de política externa. |
| **Metais industriais e energia** | 14% | Cobre em trilhas e dissipadores, alumínio em gabinetes — o piso físico de custo. |
| **Frete, tarifas e logística** | 12% | Desvios de rota e tarifas encarecem o frete, que no Brasil entra na base de cálculo do imposto. |

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
proj_global_90d = Σ (beta_renormalizado · (score_driver − 50)/50) · sensibilidade_categoria
proj_brasil_90d = ((1 + proj_global/100) · (1 + Δcâmbio_90d · 0,85/100) − 1) · 100
```

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
│   ├── http.py              # cliente httpx, retry, semáforos, disjuntor
│   ├── cache.py             # TTL com degradação para 'stale'
│   ├── series_utils.py      # variação %, composição, tanh de pressão
│   ├── providers/           # bcb, ibge, comexstat, fred, comtrade, gdelt, markets
│   ├── domain/
│   │   ├── drivers.py       # os 6 vetores e seus sinais
│   │   ├── catalog.py       # 10 categorias: betas, NCM/SH6, subitem IPCA, tributos
│   │   ├── analyzer.py      # IPH e camada Brasil
│   │   └── ranking.py       # ranking por categoria
│   └── static/              # index.html, styles.css, app.js (SVG à mão, zero dep)
├── tests/test_analyzer.py   # 11 testes, rodam sem rede
├── requirements.txt
├── .env.example
└── run.py
```

### Endpoints

| Rota | Função |
|---|---|
| `GET /` | Painel |
| `GET /api/snapshot` | Payload completo (`?force=true` ignora cache) |
| `POST /api/refresh` | Força nova coleta |
| `GET /api/health` | Cobertura, fontes ok/total, degradadas (503 enquanto aquece) |
| `GET /api/sources` | Proveniência de cada fonte |
| `GET /api/methodology` | Pesos, betas e escalas — para auditoria |
| `GET /api/cache` | Diagnóstico do cache |
| `GET /docs` | OpenAPI |

---

## 7. Como rodar

```powershell
cd C:\Users\ericssonlc\dev\datasearch_hardware
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe run.py
```

Abre em `http://127.0.0.1:8000`. Para outra porta: `$env:DSH_PORT="8077"`.

A primeira coleta leva de 40s a 3min dependendo da rede — o painel mostra o
estado de aquecimento. Fontes individuais podem ser desligadas via `.env`
(veja `.env.example`) se a sua rede bloquear algum domínio.

Testes:

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 8. Estado real da coleta

Última execução verificada nesta máquina (04/08/2026):

```
32 / 44 fontes OK  ·  cobertura do índice 90,7%
IPH 62,1  ·  IPH-Brasil 61,3   (execução anterior, com 28/44)
```

**O que está confirmado funcionando:** BCB (4/4), IBGE (1/1), FRED (11/11),
Comtrade (4/4), mercados Yahoo/Stooq (8/8), GDELT (parcial).

**Ressalvas honestas:**

1. **Comex Stat — bloqueado nesta rede.** Todas as 9 categorias retornam
   `HTTP 429` desde a primeira requisição, inclusive `GET /docs`. Não é limite
   de taxa da nossa parte (serialização com 1 req/vez e espaçamento não mudou
   nada) — é o WAF do MDIC rejeitando esta origem. **Consequência: o contrato
   exato do payload não pôde ser validado ao vivo.** A implementação tenta duas
   variantes (`filter: sh6` e `filter: ncm`) e degrada em silêncio; a coluna
   "US$/kg importado" do Ranking aparece vazia. Um disjuntor evita queimar
   ~80s por ciclo insistindo. Em rede sem esse bloqueio, ajuste
   `PAYLOAD_VARIANTS` em `app/providers/comexstat.py` se o schema divergir.

2. **GDELT — 429 intermitente.** Ele limita por taxa em janela deslizante, e as
   várias reinicializações durante o desenvolvimento consumiram a cota. Em
   operação normal (7 consultas a cada 15 min, com cache) o comportamento é
   diferente. Há espaçamento de 2,5s entre consultas e disjuntor com cooldown
   de 10 min.

3. **O frontend não foi verificado visualmente em navegador.** O HTML, CSS e JS
   estão escritos e o JSON que eles consomem foi validado por schema Pydantic,
   mas ninguém abriu a página para conferir o resultado renderizado. Vale uma
   passada de olho na primeira execução.

4. **Os betas, pesos e multiplicadores tributários são heurísticos.** São
   estimativas de ordem de grandeza feitas para explicar mecanismo, não
   apuração fiscal nem modelo econométrico calibrado. Estão todos expostos em
   `/api/methodology` justamente para serem contestados e ajustados.

---

## 9. Aviso

Índices e projeções deste painel são resultado de um modelo heurístico próprio.
**Não são previsão validada nem recomendação de compra.** Os campos marcados
como observados são medições oficiais de terceiros; os marcados como modelados
são estimativa nossa.
>>>>>>> c4d8c7d (new files)
