# Relatório — Modelo

Sessão: `datasearch-hardware-36` · 04/11/2026 · Onda 1 (T06, T07, T08)

Arquivos alterados: `app/domain/supply.py`, `app/domain/analyzer.py`,
`app/domain/fx.py`, `app/domain/backfill.py`, `app/domain/news.py`.
Testes: `python -m pytest tests/ -q` → 206 passed, 4 xfailed.

Todos os números abaixo saíram de `data/history.db` (histórico real gravado)
e de uma leitura dos 43 feeds RSS em 04/11/2026.

---

## T06 — Fila do consumidor saiu do teto

**Diagnóstico.** A fila ficou em 100,0 nos 42 ciclos gravados. Argumento do
`tanh` ≈ 4,46:

| termo | valor | × peso | contribuição |
| --- | --- | --- | --- |
| desvio = z(capex) + z(receita) | 1,37 + ~1,52 = 2,90 | 0,75 | 2,18 |
| estoque = −Δ% estoque/receita ÷ 10 | 65,2 ÷ 10 = 6,52 | 0,35 | 2,28 |

O defeito era de unidade. O capex e a receita entravam em desvios-padrão,
mas o estoque entrava em % bruto. Uma queda de 65% pesava 3× mais que o
capex num ano de capex recorde.

**Mudança.** O estoque também passou para z-score: −z da variação a/a do
estoque/receita da Micron, contra a própria série de 29 trimestres. Os pesos
são iguais por componente:

```
fila = 50 + 50·tanh(0,25·[z(capex) + z(receita)] + 0,25·(−z(Δ estoque a/a)))
```

| parâmetro | antes | depois | por quê |
| --- | --- | --- | --- |
| `QUEUE_A` | 0,75 | 0,25 | três termos na mesma unidade; cada z vale 0,25 |
| `QUEUE_B` | 0,35 | 0,25 | idem; antes a escala do estoque dependia de um ÷10 arbitrário |
| `INVENTORY_SCALE` | 10 | `None` (obsoleto) | substituído pelo z-score |

**Leitura nova** (mesmos dados): z(estoque) = −1,25 → argumento ≈ 1,04 →
**fila ≈ 89**, ainda "crítica" (≥ 75). Referências: três componentes a +1σ
dão 82; a +2σ, 95; a +3σ, 98. A fila continua monotônica: mais capex, mais
receita ou menos estoque sempre aumentam o número.

Sem os pontos trimestrais (`ratio_points`) não há z-score, e o termo de
estoque fica de fora. Nunca vira zero.

**Comparação com o histórico antigo: quebra.** Os 42 pontos de `supply.queue`
(03–04/11, todos 100,0) usam a fórmula antiga, e a fila não é reconstruída
pelo backfill. A Evolução vai mostrar um degrau de 100 para ~89 na primeira
coleta nova. Sugestão ao Backend/Coordenador: apagar esses 42 pontos ou
marcá-los, já que é só um dia de histórico.

## T07 — Projeções contra o IPCA (IBGE, agregado 7060)

**Não dá para fazer backtest ainda.** As projeções gravadas cobrem
05/10 a 04/11/2026. O último IPCA publicado é de setembro/2026. Não há nenhum
mês com projeção e inflação observada ao mesmo tempo. O primeiro par chega
com o IPCA de outubro.

**Comparação de tamanho (o que dá para fazer):**

| | valor |
| --- | --- |
| IPCA mensal, 24 meses: computador / celular / console | média +0,47 / −0,08 / +0,73%; desvio 1,3–1,4 p.p.; máximo 2,94 / 2,61 / 2,62% |
| Projeção Brasil 30 dias (todas as categorias) | **+8,4% a +9,4%** |
| … parte global (sem câmbio) | 0,0% a 0,7% |
| … parte do câmbio | ~8,5% (dólar +10,2% em 30 dias × 85%) |

A projeção era ~3× o maior mês de 24 anos-mês de IPCA desses subitens, e 97%
dela vinha do câmbio. A alta do dólar é real: PTAX, spot e Fed H.10 pularam
de ~5,04 para ~5,44 em 26/10.

**Causa: incoerência interna, não peso.** O código e o README dizem
"repasse de 85% **em um trimestre**", mas o ranking somava os 85% inteiros no
horizonte de 30 dias. A sensibilidade das categorias já era convertida de 90
para 30 dias (`HORIZON_FACTOR`); o câmbio não.

**Mudança.** `analyzer.fx_price_effect` agora aplica a fração linear do
trimestre, Δdólar_30d × 0,85 × 30/90, com `FX_PASSTHROUGH_DAYS = 90` e
`FX_HORIZON_DAYS = 30`. Com os dados de hoje, a projeção Brasil cai de ~9%
para **~3%**, dentro da faixa já vista no IPCA. O cartão do dólar (`fx.py`)
continua mostrando o repasse completo de 8,5% e agora diz que ele leva "uns
três meses, perto de 2,9% no primeiro mês". O 85% em si não mudou.
`MODEL_VERSION` do backfill passou a incluir o repasse, então a reconstrução
dos 30 dias é refeita sozinha.

**Correlação dólar × IPCA mensal (mar–set/2026, n = 5 a 7):** os betas vão
de −0,5 a +0,4 e o sinal muda conforme a defasagem. Sete meses não permitem
calibrar o repasse. O dado não confirma nem os 85% nem outro valor.

**Pesos e sensibilidades por produto: sem mudança.** Motivos:
1. Cinco categorias (GPU, RAM, SSD, CPU, notebook) usam o mesmo subitem
   (`47641 Computador pessoal`), e o monitor usa o televisor como proxy. O
   IBGE não separa essas categorias, então não dá para estimar beta por
   produto com ele.
2. A parte global da projeção (0–2,7% em 30 dias no histórico reconstruído)
   já está na ordem de grandeza do desvio mensal do IPCA (~1,3 p.p.). Não há
   evidência de exagero.

**Próximo passo:** quando sair o IPCA de outubro, comparar com a projeção
reconstruída de ~05/10 (ainda com a regra antiga; a nova reconstrução
substitui). Com 3–6 meses de pares já dá para calibrar o repasse de verdade.

## T08 — Notícias em idiomas diferentes

**Medição (04/11/2026, 43 feeds):** 995 títulos nos últimos 7 dias (871 em
inglês, 124 em português, 0 em espanhol). Depois do filtro de preço sobram
38, **todos em inglês**. Os 124 títulos em português eram promoção, Black
November, política e streaming; o filtro rejeitou certo. Hoje, portanto,
**0 matérias deixam de ser agrupadas por causa do idioma**, porque nenhuma em
pt/es chega ao digest.

Achado mais útil: **7 matérias em inglês da mesma história não eram
agrupadas** porque o título usava outras palavras. Eram três histórias:
Apple e custo de memória (4 veículos), Team Group e escassez (3) e HBM
contrabandeado para a China (2). Antes havia 1 matéria corroborada; agora há
3.

**Mudança** (`news.py`). `story_keys(title)` extrai chaves que não dependem
do idioma: empresas (28, com aliases), tickers (só em maiúsculas), países (14,
em en/pt/es; "US"/"U.S." só em maiúsculas para não casar com o pronome) e
temas (genéricos: chip, memória, preço; específicos: HBM, GPU, escassez,
controle de exportação, tarifa, contrabando, balanço, terremoto, terras
raras, hélio, Ormuz, capacidade). `same_story_by_keys` junta duas matérias
só se todas as condições valerem:

- títulos que citam empresas precisam ter pelo menos uma em comum
  (empresas diferentes = histórias diferentes);
- sem empresa em comum, é preciso ter 2 países em comum;
- é preciso ter pelo menos um tema em comum;
- a pontuação do que é comum chega a 3 (empresa 2; país e tema específico 1;
  tema genérico 0,5);
- as chaves comuns são pelo menos metade da união (Jaccard ≥ 0,5);
- as datas ficam a até 72 h uma da outra.

A comparação é feita só com a primeira matéria do grupo, sem encadeamento. A
regra prefere perder um agrupamento a errar, porque um agrupamento errado
daria o selo "confirmada" a uma notícia de fonte única. Exemplo de perda
aceita: "Apple earnings beat expectations…" (Euronews) ficou sozinha.

Os selos "corroborated" (≥ 2 domínios) e "single-source" não mudaram. As
estatísticas ganharam `merged_by_keys` e `cross_language`.

## Casos de teste para a QA (T14, T15)

**T15 — fila**
1. Três componentes em +1σ dão uma fila entre 75 e 90 (não saturada); com
   +2σ, a fila sobe mais que com +1σ (monotônica).
2. Estoque caindo mais (z mais negativo), com o resto igual, aumenta a fila.
3. O caso real (`ratio_points` 0,511…0,078 e capex em +93% a/a) dá uma fila
   menor que 99.
4. `ratio_points` com menos de 7 pontos (z indisponível): a fila sai só do
   desvio, `= 50 + 50·tanh(QUEUE_A·desvio)`, e o estoque não vira zero.
5. `inventory_yoy_changes` compara o ponto i com o ponto i−4 e ignora a base
   zero.

**T15 — câmbio (T07)**
6. Com o dólar +10% em 30 dias e o global neutro, `projected_brazil_30d_pct`
   ≈ 10 × 0,85 × 30/90 ≈ 2,83, não 8,5.
7. `fx_price_effect(x, horizon_days=90) == x * 0.85` e `horizon_days=180`
   não passa de 85%.
8. `test_fx` continua: `price_effect_pct == 8.5` (repasse completo) e o
   texto cita "85%" e "primeiro mês".

**T14 — notícias**
9. Mesma história em en/pt/es ("Apple warns of unprecedented rise in memory
   chip prices" / "Apple alerta para alta sem precedentes no preço de chips
   de memória" / "Apple advierte… precio de los chips de memoria"): três
   domínios formam um grupo, `corroboration == 3` e `cross_language == 2`.
10. Países sem empresa: "Decoy processors carry Korean HBM past US export
    controls into China" junta com "Contrabandistas levam HBM da Coreia para
    a China driblando controles de exportação dos EUA".
11. Ticker = empresa: "NVDA shares fall as China export curbs tighten" junta
    com "Nvidia: China endurece controles de exportação".
12. Não junta: empresas diferentes ("Samsung raises DRAM prices" × "Micron
    raises DRAM prices"); a mesma empresa sem tema em comum ("Nvidia tells
    data centers to limit business from Chinese customers" × "Nvidia can only
    fulfill 1% of China GPU order"); "US chip curbs… SK Hynix" × "CXMT… US
    chip curbs"; só temas genéricos ("DRAM prices double" × "Memory prices
    soar").
13. "us" minúsculo não vira EUA: `story_keys("Let us know…")["countries"]`
    vazio.
14. Mais de 72 h entre as datas: não junta. Sem data: pode juntar.
15. O item exibido não carrega o campo interno `_keys`.

## T11b — Importação por categoria lida do UN Comtrade mensal

`ranking._imports` agora lê as fontes na ordem de `IMPORT_SOURCES`: primeiro
`comtrade_monthly.<cat>` ("UN Comtrade (dado SECEX)") e, se não houver
resultado bom, `comexstat.<cat>`. Quando nenhuma das duas responde, o item
mostra o status da falha.

- **Variação de 12 meses:** compara com o mesmo `AAAA-MM` do ano anterior,
  achado pela string. Se esse mês não existe, fica `None`. Antes era
  `months[-13]`, que com mês faltando comparava com o mês errado.
- **FOB de 12 meses:** só é somado se os 12 meses da janela estiverem
  presentes. Uma soma parcial pareceria queda de importação.
- **Data de referência:** `period` é o último mês com dado (a defasagem é de
  ~2 meses), nunca a data da coleta.
- **Rótulo da fonte:** o código preenche `CategoryImport.source` só se o
  schema tiver esse campo. Hoje ele não tem (pedido ao Backend abaixo).

**Casos para a QA (T11b):** use `months` sintéticos com `usd_per_kg`
crescente.
1. Série completa de 2025-01 a 2026-08: `period == "2026-08"`, a variação
   compara 2026-08 com 2025-08, e `fob_usd_12m` soma 2025-09 a 2026-08.
2. Falta o mês do ano anterior (sem 2025-08): variação `None`. O FOB de 12
   meses continua, porque a janela está completa.
3. Falta um mês dentro da janela (sem 2026-03): a variação existe, mas
   `fob_usd_12m` é `None`.
4. Série curta (2026-07 e 2026-08): `period` e `usd_per_kg` preenchidos,
   variação e FOB `None`.
5. Chave ausente (`{}`): `status == "unavailable"` e todos os números `None`.
6. Comtrade `unavailable` e Comex Stat ok: usa o Comex Stat.
7. Comtrade `unavailable` e Comex Stat ausente: `status == "unavailable"`,
   sem números.
8. Os dois ok: o Comtrade tem prioridade.

## T08b — Título parecido não junta empresas diferentes

Defeito achado pela QA: a regra "empresas diferentes = histórias diferentes"
só valia no agrupamento por entidades. O agrupamento antigo por semelhança de
título (`_similar`) roda antes e juntava "Samsung raises DRAM prices" com
"Micron raises DRAM prices" como uma só notícia "confirmada".

A regra virou a função `different_companies(a, b)`, usada nos dois caminhos.
A mesma URL canônica continua juntando sempre, porque é a mesma matéria.

Teste: `test_digest_nao_junta_empresas_diferentes_com_titulo_parecido` agora
dá XPASS (strict). O resto da suíte passa (343). Não refiz a medição com a
amostra de 04/11 porque ela não ficou salva. Pelo desenho, a mudança só
separa grupos que tinham empresas diferentes, e os 3 grupos daquela amostra
eram todos da mesma empresa ou sem empresa.

## T19a — Tese do vetor `cambio_br`

A tese foi reescrita em 440 caracteres; antes tinha 617, e as outras teses
têm entre 216 e 522. O texto agora explica:
- como o dólar se comporta: sobe com juro Brasil–EUA menos atraente, risco
  fiscal e medo global; cai com commodities em alta; anda junto com o peso
  mexicano, o chileno e o rand;
- como ele afeta o hardware: produto importado ou cotado em dólar, repasse ao
  varejo em semanas (85% em um trimestre) e imposto sobre o valor em reais.

Saíram as frases do IGP-M e do "segundo maior peso". Label, peso e sinais
não mudaram.

Efeito colateral: `backfill.MODEL_VERSION` faz hash de `repr(DRIVERS)`, que
inclui o texto da tese. Por isso a reconstrução dos 30 dias será refeita uma
vez, com os mesmos números. Os testes passam (344).

## T21a — Vetor `cambio_br` passa a se chamar "Dólar"

Em `app/domain/drivers.py`, o `label` passou de "Câmbio e macro Brasil" para
"Dólar". Continuam iguais: a key `cambio_br`, o peso de 0,19, o ×1,6 do
IPH-Brasil, os sinais e a tese da T19a. Nenhum outro texto em `app/domain/`
citava o rótulo antigo. Os testes passam (345).

O `/api/snapshot` só mostra o rótulo novo depois que o servidor reinicia (o
processo em execução é anterior à mudança). Como o `label` também entra no
hash do `MODEL_VERSION`, a reconstrução de 30 dias é refeita uma vez, com os
mesmos números.

## T24 — Proposta: painel de oferta por categoria e preço médio no Brasil

> **Versão aprovada da cesta: T24h**, em revisão pela **T24i** (teto do consumidor médio e preço cheio).

> **Revisada em 05/11/2026 pela T24c** (só fontes públicas sem chave): onde
> houver diferença, vale a T24c. A cesta (T24b) está em espera.

Status: **só proposta, sem código.** As fontes dependem do levantamento do
Dados (T23). Os pontos que dependem do usuário estão no fim da seção.

### Parte 1 — Painel de oferta (substitui o card "Estoque de memória")

**Problema de desenho.** Hoje cada categoria tem um beta por *vetor*, e o
vetor `alocacao_chips` dá a mesma nota para RAM e para fonte de alimentação.
Para "TSMC pesa em GPU/CPU e memória pesa em RAM/SSD", a categoria precisa
pesar os *sinais* dentro do vetor.

**Proposta: cada sinal ganha uma frente, e cada categoria ganha uma
exposição por frente.**

| frente | sinais | o que mede |
| --- | --- | --- |
| `memoria` | dias de estoque Micron + SK Hynix (+ Samsung, ver pergunta 1); exportação de semicondutores da Coreia; ação da Micron; Comtrade memória | aperto na oferta de DRAM/NAND |
| `logica` | receita mensal da TSMC; dias de estoque NVIDIA + AMD + Intel; ações TSMC e NVIDIA; Comtrade processadores | foundry e chips lógicos (GPU, CPU, SoC) |
| `demanda` | capex dos hyperscalers; receita de chips | o tamanho da fila de IA |
| geral (sem frente) | PPI de semicondutores, SOXX | setor inteiro; vale para todas |

Nota do vetor para a categoria *c*:

```
nota_c = Σ_s w_s · e(c, frente_s) · nota_s  /  Σ_s w_s · e(c, frente_s)
```

Aqui `e = 1` para sinal geral, e só entram os sinais disponíveis. Com todas
as exposições em 1, a conta volta à nota global do vetor. **O IPH continua
usando a nota global**; a exposição só muda o ranking e a pressão por
categoria. Isso preserva a leitura do índice.

**Exposição inicial proposta** (0 a 1; heurística, como os betas, e
editável no `catalog.py`):

| categoria | memória | lógica | demanda | motivo |
| --- | --- | --- | --- | --- |
| RAM | 1,0 | 0,2 | 1,0 | DRAM; HBM disputa wafer com DDR |
| SSD/HD | 1,0 | 0,2 | 0,6 | NAND |
| GPU | 0,6 | 1,0 | 1,0 | chip TSMC + GDDR; mesma linha do datacenter |
| CPU | 0,2 | 1,0 | 0,6 | TSMC (AMD) e Intel |
| celular | 0,7 | 0,8 | 0,3 | SoC + LPDDR/UFS |
| notebook | 0,7 | 0,8 | 0,5 | CPU + RAM + SSD |
| console | 0,6 | 0,9 | 0,4 | SoC AMD/TSMC + GDDR |
| placa-mãe | 0,2 | 0,6 | 0,3 | chipset; o peso do vetor já é baixo (0,14) |
| monitor | 0,1 | 0,4 | 0,2 | quase nada de chip avançado |
| fonte | 0,0 | 0,4 | 0,2 | chip de nó maduro; o peso do vetor é 0,06 |

**Como cada sinal vira pressão.** Mantém a regra "50 = neutro, saturação
por tanh", com dois modos novos no `SignalSpec`:

| sinal | modo | conta | normal exibido |
| --- | --- | --- | --- |
| dias de estoque (DIO) | `zlevel`, invertido | DIO = estoque ÷ CPV do trimestre × 91,25; z do último trimestre contra os 20 anteriores (5 anos); pressão = 50 + 50·tanh(−z/1,5) | P25–P75 dos mesmos 20 trimestres |
| receita TSMC | `zyoy` | variação a/a da soma de 3 meses (tira o ruído do mês), z contra a própria história; 50 + 50·tanh(z/1,5) | P25–P75 da variação a/a |
| exportação de chips da Coreia | `zyoy` | igual à TSMC, em US$ | idem |
| capex, receita de chips | como na fila (T06) | — | — |

Por que z-score e não variação %: são unidades diferentes (dias, % a/a,
US$). A T06 mostrou que misturar % bruto com z prende a nota no teto. A
escala 1,5 faz z = ±1,5 valer ~12/88, como a escala dos outros sinais.

**O card pedido**, "N dias · o normal é X a Y", sem tooltip:
- "Estoque de memória: **84 dias** · o normal é 95 a 130" (agregado:
  Σ estoque ÷ Σ CPV das empresas da frente, com o mesmo ×91,25);
- "Estoque de chips lógicos: N dias · o normal é X a Y";
- "Receita da TSMC: +X% a/a · o normal é A% a B%";
- "Exportação de chips da Coreia: +X% a/a · o normal é A% a B%".
- Abaixo do número, uma linha com a referência: "2º tri/2026 · SEC/DART".

O normal é o intervalo interquartil (metade central) dos últimos 5 anos da
própria série. É fácil de dizer e não depende de média nem desvio-padrão.
(Os números do exemplo são ilustrativos.)

**Fila e vetor atual.**
- O estoque da Micron **sai da fila** e vai para a frente `memoria`, para
  não contar duas vezes. A fila passa a ser só demanda:
  `50 + 50·tanh(0,25·[z(capex) + z(receita de chips)])`. Pergunta 4.
- O peso do vetor `alocacao_chips` continua **22%**. Pesos dos sinais dentro
  dele (somam 1): capex 0,18; DIO memória 0,14; Coreia 0,10; Comtrade
  memória 0,05; TSMC receita 0,12; DIO lógica 0,10; Comtrade processadores
  0,04; PPI 0,09; ação Micron 0,07; NVIDIA 0,05; SOXX 0,03; ação TSMC 0,03.
  Hoje o estoque é um único sinal (0,18) e não há dado de foundry. As ações
  caem de 0,35 para 0,18, porque passam a existir medidas físicas de oferta.
- **Quebra de histórico:** sim, como na T06. Ficam sem comparação direta
  `supply.queue` (sem o estoque), `driver.alocacao_chips`, `iph`, `iph_br`
  e `cat.*`. Proposta ao Backend: generalizar o `queue_model_since` para
  `model_since` por série (o `/api/series` já tem o campo) e registrar a
  data da troca. A reconstrução de 30 dias se refaz sozinha (muda o
  `MODEL_VERSION`), se as fontes novas trouxerem histórico.

**Frequência diferente e falta de dado.**
- Cada sinal é calculado na própria frequência; o índice diário usa o
  último valor conhecido (degrau), sem interpolar entre trimestres.
- Validade máxima depois da data de referência: mensal 75 dias, trimestral
  150 dias. Passou disso, o sinal sai da conta, a `coverage` cai e o card
  mostra "último dado: 2º tri/2026 — desatualizado".
- Sinal ausente: os pesos se renormalizam entre os presentes. Frente sem
  nenhum sinal: a categoria fica só com os sinais gerais e os das outras
  frentes. Nunca vira 50.
- **Reconstrução:** hoje `_known_on` usa a data de referência. Para dado
  trimestral isso adianta ~40 dias (o 10-Q sai depois do fim do trimestre).
  Proposta: o Dados manda a data de publicação (`filed` da SEC, data de
  divulgação da TSMC e do MOTIE), e o backfill usa essa data.
- **Prévia de 20 dias da Coreia:** recomendo só exibir no card ("prévia:
  +X% a/a nos 20 primeiros dias"), sem entrar na conta até o mês fechar.
  Prévia muda e mistura base diferente. Pergunta 3.

### Parte 2 — Preço médio no Brasil por categoria (aba Preços)

**Mediana, não média aparada.** Anúncio tem cauda pesada (kit, acessório
com título de produto, preço "isca") e a mediana resiste a isso sem um
parâmetro de corte. Também é fácil de dizer: "metade dos anúncios custa
menos que isso". Mostrar junto a faixa P25–P75.

**O risco maior é a composição, não a estatística.** A mediana de "placa de
vídeo" sobe só porque entraram mais anúncios de RTX 5090. Proposta: uma
**cesta fixa de 2 a 4 modelos de referência por categoria** (ex.: RTX 5060
8 GB; DDR5 32 GB 2×16 6000; SSD NVMe 1 TB; Ryzen 5 7600). Cada modelo tem
sua mediana; a variação da categoria é a média das variações dos modelos.
É o mesmo princípio de "modelo pareado" dos índices oficiais. Pergunta 5.

**Filtros, nesta ordem:**
1. Só novo: condição "novo" e nada de usado, recondicionado, vitrine ou
   open box no título.
2. Só nacional, ou anúncio internacional à parte (pergunta 6): o preço do
   internacional não inclui o mesmo imposto e distorce a mediana.
3. Título com os termos obrigatórios do modelo e sem os de exclusão: kit,
   combo, "pc gamer", "notebook" (para GPU), cabo, suporte, cooler,
   dissipador, adaptador, riser, capa, película, "compatível com".
4. Faixa plausível em duas passadas: piso absoluto por categoria contra
   acessório (ex.: GPU ≥ R$ 300; RAM ≥ R$ 80) e, depois, descarte do que
   ficar fora de 0,5× a 2× a mediana preliminar do modelo. É relativo, então
   não envelhece com a inflação.
5. Um anúncio por vendedor e modelo (o mais barato), para um vendedor com 20
   anúncios não decidir a mediana.

**Mínimo de anúncios (depois dos filtros), por modelo:**
- ≥ 15: publica.
- 8 a 14: publica com o aviso "poucos anúncios".
- < 8: não publica.

A categoria só é exibida com pelo menos 2 modelos válidos.

**Links de referência:** 3 por modelo. São os anúncios mais próximos da
mediana, de vendedores diferentes, nacionais e novos; o desempate é pelo
maior número de vendas. Nunca "o mais barato", que puxa golpe e anúncio sem
estoque. Mostrar título, preço, vendedor e data da coleta, com o texto
escapado (é dado de terceiro).

**IPCA ao lado:**

| categoria | IPCA (IBGE, agregado 7060) |
| --- | --- |
| GPU, RAM, SSD, CPU | "Computador pessoal" com o selo "proxy" |
| notebook | "Computador pessoal" |
| celular | "Aparelho telefônico" |
| console | "Videogame" |
| monitor | "Televisor" com o selo "proxy" |
| placa-mãe, fonte | "sem subitem no IPCA" |

- Formato: "IPCA de set/2026: +1,7% no mês · +6,6% em 12 meses".
- Cada número traz o próprio período. Nada de subtrair o preço do Mercado
  Livre do IPCA num número único até haver ≥ 3 meses de coleta: as bases e
  as janelas são diferentes.

**Rótulo honesto:** "amostra de anúncios do Mercado Livre em <data>", tipo
`observado`, com a nota "não é índice oficial". A conta (filtros, mediana,
cesta) fica em `app/domain/prices.py`, pura e testável; a coleta é do Dados.

**Ganho extra para a T07:** com preço do Mercado Livre por modelo, dá para
conferir a projeção de 30 dias todo mês, sem esperar o IPCA (que tem ~40
dias de atraso e mistura categorias).

### Perguntas que dependem do usuário

1. **Samsung entra no estoque de memória?** O estoque do DART é consolidado
   (celular, TV, chip). Recomendo deixar a Samsung fora da conta e mostrá-la
   só como referência, se o Dados não achar estoque por segmento.
2. **"O normal" = últimos 5 anos** (recomendado; acompanha mudança de
   negócio, como a da NVIDIA) **ou desde 2015?**
3. **Prévia de 20 dias da Coreia:** só exibir (recomendado) ou entrar na
   conta como provisória?
4. **Tirar o estoque da fila** (a fila passa a ser só demanda; nova quebra
   de histórico com `model_since`)? Recomendo sim.
5. **Preço por cesta de modelos fixos** (recomendado) ou mediana da
   categoria inteira? Se for cesta: quem escolhe os modelos e com que
   frequência a lista é revista (lançamentos)?
6. **Anúncio internacional** (compra internacional do Mercado Livre):
   excluir (recomendado) ou mostrar à parte?
7. **Pesos e exposições iniciais** das tabelas acima: aprovar como ponto de
   partida (heurístico, como os betas) ou revisar antes?

### T24 — Decisões do usuário (05/11/2026)

Ainda sem implementar; aguardando o sinal do Coordenador.

1. **Samsung:** fica fora do estoque de memória. A frente memória usa
   Micron + SK Hynix.
2. **"O normal":** P25–P75 dos últimos 5 anos (20 trimestres ou 60 meses).
3. **Prévia de 20 dias da Coreia:** fora. Ela não separa semicondutores (nota
   do Dados). A exportação coreana entra só pelo mensal HS 8542, que depende
   de chave do data.go.kr; sem a chave, o sinal fica ausente e o peso se
   renormaliza.
4. **Estoque da Micron:** sai da fila e vai para a frente memória, com
   quebra de histórico registrada por `model_since` em cada série.
5. **Preço:** cesta fixa (proposta abaixo), revista a cada trimestre ou
   quando um modelo sai de linha.
6. **Anúncio internacional do ML:** excluído.
7. **Pesos e exposições** da T24: valem como ponto de partida.

**Ajustes ao desenho, vindos do Dados (T23):**
- **DIO normalizado pela duração do trimestre:**
  `DIO = estoque ÷ (CPV do trimestre ÷ dias do trimestre)`, em vez de ×91,25
  fixo. O Q4 FY2026 da Micron tem 98 dias e inflaria o número em ~7%. O CPV
  é por trimestre, e a Micron não traz o problema de acumulado no ano.
- **Referência atual do Dados:** NVIDIA 119, AMD 169 e Intel 126 dias. A
  frente lógica agrega por Σ estoque ÷ Σ CPV diário. A AMD tem DIO
  estruturalmente maior; por isso o z é calculado contra a história de cada
  empresa e o card mostra o agregado.
- **Monitor:** passa a usar o IPCA 7541 "TV, som e informática" no lugar de
  7542 "Televisor", ainda com o selo de proxy.
- **Links de referência sem "vendidos":** a ordem é a distância à mediana;
  no empate vem primeiro a loja oficial (se a API informar) e depois o
  anúncio mais recente. Nunca o mais barato.
- **Chaves pendentes** (DART, data.go.kr, ML): cada fonte entra quando a
  chave existir. Sem ela, o card mostra "fonte não configurada" e o sinal
  fica fora da conta (nunca vira 50). O ML pode seguir bloqueado mesmo com
  token, e então a aba Preços fica só com o IPCA.

### T24b — Proposta de cesta de preços (substituída pela T24d: fonte única KaBuM)

**Critérios para escolher um item:**
- muito anunciado no Brasil, para chegar a 15 anúncios ou mais depois dos
  filtros;
- representa o comprador doméstico (entrada e intermediário, não o topo);
- cobre fornecedores diferentes quando isso muda a exposição (TSMC × Intel,
  NVIDIA × AMD);
- definido **por especificação** sempre que possível ("SSD NVMe 1 TB PCIe
  4.0"), para durar mais que um modelo exato.

O modelo exato só aparece quando a especificação não identifica o produto
(CPU, console, celular).

| categoria | item da cesta | por quê |
| --- | --- | --- |
| **GPU** | RTX 5060 8 GB | entrada mais vendida da NVIDIA; chip TSMC + GDDR7 |
| | RTX 5070 12 GB | intermediária; disputa a mesma linha que atende datacenter |
| | Radeon RX 9060 XT 16 GB | outro fornecedor (AMD), GDDR6; mostra se a alta é da NVIDIA ou do setor |
| **RAM** | DDR5 32 GB (2×16) 6000 MHz, desktop | configuração padrão de PC novo |
| | DDR4 16 GB (2×8) 3200 MHz, desktop | base instalada no Brasil (AM4/LGA1200); a DDR4 sai de linha e sobe antes |
| | DDR5 SODIMM 16 GB 5600 MHz, notebook | upgrade de notebook; memória de consumo mais exposta |
| **SSD/HD** | SSD NVMe 1 TB PCIe 4.0 | o SSD mais vendido; NAND |
| | SSD NVMe 2 TB PCIe 4.0 | mostra se a alta da NAND cresce com a capacidade |
| | SSD SATA 480/512 GB 2,5" | entrada muito comum no Brasil (PC de escritório, upgrade) |
| | HD 3,5" 2 TB 7200 rpm | ímã de terras raras; HD de alta capacidade tem hélio, mas é pouco anunciado |
| **CPU** | Ryzen 5 5600 (AM4) | o processador mais vendido no Brasil, de plataforma antiga |
| | Ryzen 5 7600 (AM5) | intermediário atual; TSMC |
| | Core i5-14400F (LGA1700) | Intel com fábrica própria; separa TSMC de Intel |
| **Placa-mãe** | B650 (AM5), mATX ou ATX | par do Ryzen 7600 |
| | B760 (LGA1700), DDR4 ou DDR5 | par do i5-14400F |
| | A520 (AM4) | par do Ryzen 5600; entrada |
| **Fonte** | 650 W 80 Plus Bronze | a mais comum em PC intermediário; quase só cobre e frete |
| | 850 W 80 Plus Gold, ATX 3.x | PC com GPU nova (conector 12V-2×6) |
| **Celular** | Galaxy A57 5G 256 GB | intermediário Samsung, o volume do mercado; montado em Manaus |
| | Galaxy A37 5G 128 GB | entrada Samsung |
| | Motorola Moto G intermediário vigente (modelo a confirmar com o Dados) | segunda marca do mercado brasileiro |
| | iPhone 17 256 GB | importado, cotado em dólar, sem a Zona Franca; contraponto ao Galaxy |
| **Notebook** | 15,6", Core i5 ou Ryzen 5 atual, 16 GB, SSD 512 GB | configuração modal do varejo; tem RAM e SSD dentro |
| | notebook gamer com RTX 5050 ou 5060, 16 GB | GPU + memória no mesmo produto |
| | MacBook Air 13" (chip vigente), 16 GB / 256 GB | importado, preço em dólar, outra cadeia (Apple/TSMC) |
| **Monitor** | 24" 1080p IPS, 75–100 Hz | escritório; painel quase commodity |
| | 27" 1440p, 144–180 Hz | gamer intermediário |
| **Console** | PlayStation 5 Slim, edição digital | console mais vendido; SoC AMD/TSMC + GDDR6 |
| | Xbox Series S 512 GB | entrada; reajustes recentes por custo |
| | Nintendo Switch 2 | outra cadeia (NVIDIA, Samsung foundry) |

Total: 30 itens, entre 2 e 4 por categoria.

**Fica fora de propósito:**
- RTX 5080/5090 e topo de linha: cauda de preço e especulação;
- kits de PC montado: composição variável;
- celular dobrável: volume baixo.

**Regras de manutenção:**
- Para cada item: termos obrigatórios (ex.: "5060" e "8gb", sem "ti" para a
  RTX 5060), termos de exclusão por categoria e piso de preço. A lista
  completa vai para `app/domain/prices.py` com a implementação.
- **Saída de linha:** um item com menos de 8 anúncios em duas coletas
  seguidas vira "em revisão". O substituto (o sucessor, ex.: Galaxy A57 →
  A58) entra **encadeado**: a variação da categoria compara cada item com ele
  mesmo, e a troca não cria salto no índice.
- **Revisão trimestral:** o Modelo propõe trocas e o usuário aprova. A data
  da revisão fica registrada em `model_since` da série de preços.
- **Item por especificação:** tem mais dispersão que um modelo exato. Por
  isso o painel mostra também a faixa P25–P75, e o corte de 0,5×–2× da
  mediana segura o resto.

**Para o usuário decidir na aprovação:**
- confirmar ou trocar os itens marcados "a confirmar" (Motorola);
- confirmar se celular e notebook ficam com 3 a 4 itens. São as categorias
  mais heterogêneas; com 2 itens, a mediana fica mais sensível a um único
  modelo.

### T24c — Revisão: só fontes públicas, sem chave nem cadastro (05/11/2026)

**Decisão do usuário:** nenhuma fonte com chave ou cadastro. Saem DART (SK
Hynix e Samsung), data.go.kr (exportação da Coreia) e Mercado Livre. Ficam a
TSMC (TWSE OpenAPI), a SEC (NVIDIA, AMD, Intel, Micron) e o IPCA. **Esta
seção substitui** o que a T24 e as "Decisões do usuário" dizem sobre essas
fontes. Ainda sem implementar.

**Frentes:**

| frente | sinais | card |
| --- | --- | --- |
| memória | dias de estoque da **Micron** (SEC); Comtrade memória; ação da Micron | "Estoque de memória (Micron): N dias · o normal é X a Y" |
| lógica | dias de estoque de **NVIDIA + AMD + Intel** (SEC, Σ estoque ÷ Σ CPV diário; z por empresa); Comtrade processadores; ações NVIDIA e TSMC | "Estoque de chips lógicos: N dias · o normal é X a Y" |
| demanda | capex dos hyperscalers (SEC); **receita mensal da TSMC** (TWSE, z da variação a/a da soma de 3 meses) | "Receita da TSMC: +X% a/a · o normal é A% a B%" |
| geral | PPI de semicondutores; SOXX | — |

A fila (`supply.py`) vira só demanda: z(capex) + z(receita de chips), com
o estoque da Micron fora, como decidido. A receita da TSMC entra no vetor
pela frente demanda, mas não na fila, para a fila continuar comparável com
a T06 além da retirada do estoque.

**Limite declarado:** a frente memória depende de uma empresa só. O card diz
"(Micron)" no título. Se a SEC falhar, a frente fica sem dado de estoque e
os pesos se renormalizam entre Comtrade e ação, sem inventar número.

**Pesos dentro de `alocacao_chips`** (o vetor segue com 22%; somam 1,00):

| frente | sinal | peso | antes (T24) |
| --- | --- | --- | --- |
| demanda | capex hyperscalers | 0,20 | 0,18 |
| demanda | receita TSMC | 0,13 | 0,12 (era lógica) |
| memória | dias de estoque Micron | 0,15 | 0,14 (com SK Hynix) |
| memória | Comtrade memória | 0,06 | 0,05 |
| memória | ação Micron | 0,08 | 0,07 |
| lógica | dias de estoque NVIDIA/AMD/Intel | 0,12 | 0,10 |
| lógica | Comtrade processadores | 0,05 | 0,04 |
| lógica | ação NVIDIA | 0,05 | 0,05 |
| lógica | ação TSMC | 0,03 | 0,03 |
| geral | PPI semicondutores | 0,10 | 0,09 |
| geral | SOXX | 0,03 | 0,03 |

O peso da Coreia (0,10) foi distribuído aos sinais vizinhos. Os medidos (DIO,
capex, TSMC) receberam mais que as ações. Medidas por frente: demanda 0,33;
memória 0,29; lógica 0,25; geral 0,13.

**Exposição por categoria:** a da T24 continua, com um ajuste. A TSMC agora
está na frente demanda, então categorias com SoC da TSMC sobem nessa frente:
celular 0,3 → 0,5; console 0,4 → 0,6; notebook 0,5 → 0,6. As demais não
mudam.

**Fontes ausentes:** só sobram fontes públicas, então não existe mais estado
"não configurado". Uma falha (rede, 429, mudança de formato) segue a regra de
sempre: `stale` com o último valor bom, depois fora da conta com `coverage`
menor. Os prazos de validade continuam: mensal 75 dias, trimestral 150 dias.

**Aba Preços: só o IPCA do subitem, por enquanto.**

| categoria | IPCA (IBGE, agregado 7060) |
| --- | --- |
| GPU, RAM, SSD, CPU | "Computador pessoal" com o selo "proxy" |
| notebook | "Computador pessoal" |
| celular | "Aparelho telefônico" |
| console | "Videogame" |
| monitor | 7541 "TV, som e informática" com o selo "proxy" |
| placa-mãe, fonte | "sem subitem no IPCA" |

- Formato: "IPCA de set/2026: +1,7% no mês · +6,6% em 12 meses", com o
  período em cada número.
- A projeção de 30 dias do modelo fica ao lado, rotulada "estimativa nossa".
  Não há diferença entre as duas num número único (janelas e bases
  diferentes).

**Sai do desenho:**
- prévia e mensal da Coreia;
- SK Hynix e Samsung;
- mediana do Mercado Livre, filtros, mínimo de anúncios e links de
  referência.

**T24b (cesta de preços): em espera.** Sem o Mercado Livre não há fonte
pública de preço em reais por modelo. A proposta fica no relatório para o
caso de aparecer uma fonte sem chave.

**Quebra de histórico:** a mesma da T24. Ficam sem comparação direta
`supply.queue` (sai o estoque), `driver.alocacao_chips`, `iph`, `iph_br` e
`cat.*`, registradas com `model_since` por série.

### T24d — Cesta ajustada à KaBuM, fonte única (05/11/2026; só documento)

> **A cesta desta seção foi substituída pela T24e** (baixo, médio e alto).
> Os outros pontos (preço à vista, oferta, mínimos, K14 d/e e rótulo)
> continuam valendo, com os ajustes da T24e.

**Decisão do usuário:** o preço em reais vem só da KaBuM. Ficam fora Samsung,
Dell, Lenovo, Zoom, Buscapé e Amazon; o Mercado Livre talvez entre depois como
reforço. Valem as regras da Segurança (`seguranca.md` §T26):
- K5: o loop diário usa só `/produto/<code>`; a busca serve só para a
  curadoria;
- K3: no máximo 40 pedidos por dia;
- K14b/d/e: estas três são do Modelo e estão detalhadas abaixo.

**O que muda em relação à T24b:**
- Com uma loja só, a mediana deixa de ser "de vários vendedores" e passa a
  ser **dos anúncios do mesmo modelo** (marcas de placa diferentes, por
  exemplo).
- Modelo de SKU único (processador, console, celular) tem 1 URL, e o preço
  é o daquele anúncio.
- Só entra produto **vendido pela KaBuM** (`sellerName == "KaBuM!"`, K18).
  Anúncio de marketplace fica fora, inclusive na curadoria.

#### Cesta final (37 URLs; teto de 40; sobram 3 para troca na curadoria)

| categoria | modelo | URLs | por quê |
| --- | --- | --- | --- |
| **GPU** (8) | RTX 5060 8 GB | 3 (marcas diferentes) | entrada mais vendida; chip TSMC + GDDR7 |
| | RTX 5070 12 GB | 3 | intermediária, mesma linha que atende datacenter |
| | Radeon RX 9060 XT 16 GB | 2 | outro fornecedor (AMD) e GDDR6 |
| **RAM** (4) | DDR5 32 GB (2×16) 6000 MHz | 2 | configuração padrão de PC novo |
| | DDR4 16 GB (2×8) 3200 MHz | 2 | base instalada; DDR4 saindo de linha |
| **SSD** (4) | NVMe 1 TB PCIe 4.0 | 2 | o SSD mais vendido; NAND |
| | NVMe 2 TB PCIe 4.0 | 2 | mostra se a alta cresce com a capacidade |
| **CPU** (3) | Ryzen 5 5600 | 1 | o mais vendido; AM4 |
| | Ryzen 5 7600 | 1 | intermediário atual; TSMC |
| | Core i5-14400F | 1 | Intel, fábrica própria |
| **Placa-mãe** (4) | B650 (AM5) | 2 | par do 7600 |
| | B760 (LGA1700) | 1 | par do 14400F |
| | A520 (AM4) | 1 | par do 5600; entrada |
| **Fonte** (3) | 650 W 80 Plus Bronze | 2 | a mais comum; quase só cobre e frete |
| | 850 W 80 Plus Gold ATX 3.x | 1 | PC com GPU nova |
| **Celular** (3) | Galaxy A57 5G 256 GB | 1 | intermediário de volume; Manaus |
| | Moto G intermediário vigente | 1 | segunda marca do mercado; o Dados confirma o modelo |
| | iPhone 17 256 GB | 1 | importado, cotado em dólar |
| **Notebook** (3) | 15,6" Core i5/Ryzen 5, 16 GB, SSD 512 GB | 2 (marcas diferentes) | configuração mais comum no varejo |
| | gamer com RTX 5050/5060, 16 GB | 1 | GPU + memória no mesmo produto |
| **Monitor** (2) | 24" 1080p IPS 75–100 Hz | 1 | escritório |
| | 27" 1440p 144–180 Hz | 1 | gamer intermediário |
| **Console** (3) | PlayStation 5 Slim digital | 1 | o mais vendido |
| | Xbox Series S 512 GB | 1 | entrada |
| | Nintendo Switch 2 | 1 | outra cadeia (NVIDIA/Samsung) |

**Saíram da T24b para caber em 40:**
- DDR5 SODIMM, SSD SATA, HD 2 TB e Galaxy A37;
- MacBook Air (só volta se a KaBuM vender pela própria loja).

Consequência: a categoria SSD/HD perde a exposição a terras raras pelo HD.
Isso continua medido no vetor `terras_raras`.

**Mais URLs onde há mais variação entre marcas:** GPU e placa-mãe, onde o
preço muda muito de uma montadora para outra. Onde o produto é igual em
qualquer anúncio (CPU, console), basta 1 URL.

#### Mínimo para publicar (substitui os 15 anúncios do ML)

Uma URL é **válida** no dia quando cumpre tudo:
- está disponível (K14e);
- é vendida pela KaBuM;
- está na faixa da categoria (K14b);
- não está "suspeita" (K14d).

| nível | regra |
| --- | --- |
| modelo com 2–3 URLs | publica com **≥ 2 válidas** (mediana; com 2, é a média das duas); com 1 válida, publica com o aviso "1 de N anúncios" |
| modelo com 1 URL | publica se ela for válida, com o aviso "anúncio único" |
| categoria | publica com **pelo menos metade dos modelos válidos** (arredondado para cima; ≥ 1) |

Na tela, **cada modelo mostra o próprio preço**, porque a média entre RTX
5060 e RTX 5070 não significa nada. A categoria mostra só a variação: a
média das variações dos modelos válidos, cada um contra ele mesmo (modelo
pareado). A variação de 30 dias só aparece com ≥ 30 dias de coleta.

#### Proteções K14 do Modelo

- **K14b — faixa por categoria (R$):**

  | categoria | mínimo | máximo |
  | --- | --- | --- |
  | GPU | 300 | 30 000 |
  | RAM | 50 | 5 000 |
  | SSD | 80 | 5 000 |
  | CPU | 200 | 15 000 |
  | placa-mãe | 250 | 8 000 |
  | fonte | 150 | 4 000 |
  | celular | 400 | 20 000 |
  | notebook | 1 500 | 30 000 |
  | monitor | 300 | 10 000 |
  | console | 1 000 | 10 000 |

  Fora da faixa, a URL é descartada no dia e marcada "fora da faixa".
- **K14d — salto:** variação maior que 40% contra o último valor válido
  daquela URL vira "suspeito", fora da mediana e marcado no painel. Se no
  dia seguinte o preço ficar a até ±5% do valor suspeito, ele é confirmado e
  passa a valer **a partir do dia da confirmação**; o dia suspeito continua
  fora. Se não ficar, o suspeito é descartado.
- **K14e — indisponível** (`available=false` ou `OutOfStock`): fora da
  mediana do dia. O último preço não é repetido; a série tem lacuna.
- Todas as três são funções puras em `app/domain/prices.py`, testáveis sem
  rede.

#### Qual preço usar

**Recomendo o preço à vista (`priceWithDiscount`, Pix/boleto)** como
principal. É o que a maioria paga, e é o que a loja mais anuncia. O preço
cheio (parcelado) aparece numa segunda linha: "R$ 2.199 à vista · R$ 2.499
em até 10×". As duas séries são guardadas, para dar para conferir se o
desconto à vista mudou.

**Oferta relâmpago:** fica fora da mediana e da variação, como no K14d. Ela
mede promoção, não tendência. O painel mostra o preço com o selo "oferta
relâmpago". Para isso o cache precisa guardar um campo `oferta` (true/false)
além do que o K8 lista. Fica como pedido ao Dados e à Segurança. Sem esse
campo, sobra o K14d, que só pega salto maior que 40%.

#### Rótulo na aba Preços

- **Título:** "Preço na KaBuM (à vista)".
- **Linha fixa:** "Uma loja, 37 anúncios acompanhados por dia. Não é média
  de mercado."
- Por item: "coletado em <data>", com link montado do `code` validado (K16).
- Tipo `observado`, com a nota "uma loja; não é índice oficial". O IPCA do
  subitem continua ao lado, com o próprio período (T24c).

#### Para o usuário aprovar

1. A cesta acima (37 URLs), com as saídas listadas.
2. Preço à vista como principal e o parcelado na segunda linha.
3. Oferta relâmpago fora da mediana (depende do campo `oferta`).

A curadoria das URLs (via `/busca`, manual) fica com o Dados depois da
aprovação.

### T24e — Cesta por faixa: baixo, médio e alto (05/11/2026; só documento)

> **A linha de GPU foi revista na T24f** (duas marcas por faixa); para
> fechar em 40 URLs, RAM médio e placa-mãe baixo passam a ter 1 URL.

**Pedido do usuário:** cada categoria com 1 produto de baixo custo, 1 de
médio e 1 de alto, incluindo o topo de linha que a T24d deixou fora. Esta
seção **substitui a cesta da T24d**. O resto da T24d continua:
- preço à vista como principal, cheio na 2ª linha;
- oferta relâmpago fora da mediana;
- K14 b/d/e;
- rótulo "Preço na KaBuM (à vista)".

Só entra produto vendido pela própria KaBuM (K18).

#### Critério de faixa

Cada faixa é um **intervalo de preço à vista em R$**, definido por
categoria. O modelo escolhido precisa estar dentro do intervalo no dia da
curadoria. O substituto de um modelo que sai de linha precisa estar na
**mesma faixa**, e não só ser "o sucessor". Assim a faixa mede sempre o mesmo
tipo de compra.
- Os intervalos são estimativas para guiar a curadoria. O Dados confere com
  o preço real da KaBuM antes da aprovação, e o Modelo ajusta o intervalo se
  um modelo típico cair fora dele.
- Revisão a cada trimestre, junto com a cesta. Uma troca de intervalo fica
  registrada em `model_since` da série da faixa.
- Entre faixas há folga de propósito, para um modelo perto da borda não
  mudar de faixa por causa de uma promoção.

#### Cesta (30 modelos, 38 URLs; teto de 40; sobram 2 para troca na curadoria)

| categoria | baixo | médio | alto |
| --- | --- | --- | --- |
| **GPU** | RTX 5060 8 GB · *R$ 1.500–2.800* · **2 URLs** | RTX 5070 12 GB · *R$ 3.500–6.000* · **2 URLs** | RTX 5090 32 GB · *≥ R$ 12.000* · **2 URLs** |
| **RAM** | DDR4 16 GB (2×8) 3200 · *R$ 250–800* | DDR5 32 GB (2×16) 6000 · *R$ 800–2.200* · **2 URLs** | DDR5 64 GB (2×32) ≥ 6000 · *≥ R$ 2.200* |
| **SSD** | SATA 480/512 GB 2,5" · *R$ 150–450* | NVMe 1 TB PCIe 4.0 · *R$ 400–1.000* | NVMe 2 TB PCIe 5.0 · *≥ R$ 1.200* |
| **CPU** | Ryzen 5 5600 · *R$ 500–900* | Core i5-14400F · *R$ 900–1.800* | Ryzen 9 9950X3D · *≥ R$ 4.000* |
| **Placa-mãe** | A520 (AM4) · *R$ 400–750* · **2 URLs** | B650 (AM5) · *R$ 900–1.700* · **2 URLs** | X870E (AM5) · *≥ R$ 2.500* |
| **Fonte** | 550–600 W 80 Plus Bronze · *R$ 250–450* | 750 W 80 Plus Gold ATX 3.x · *R$ 500–1.000* | 1000 W+ 80 Plus Platinum ATX 3.1 · *≥ R$ 1.300* |
| **Celular** | Galaxy A1x vigente 128 GB · *R$ 800–1.400* | Galaxy A57 5G 256 GB · *R$ 1.800–3.000* | iPhone 17 Pro 256 GB · *≥ R$ 8.000* |
| **Notebook** | Core i3/Ryzen 3, 8 GB, SSD 256 GB · *R$ 2.000–3.200* · **2 URLs** | Core i5/Ryzen 5, 16 GB, SSD 512 GB · *R$ 3.500–5.500* · **2 URLs** | gamer com RTX 5080/5090 Laptop · *≥ R$ 15.000* |
| **Monitor** | 24" 1080p IPS 100 Hz · *R$ 500–900* | 27" 1440p 165–180 Hz · *R$ 1.200–2.300* | 27" OLED 1440p ≥ 240 Hz · *≥ R$ 4.000* |
| **Console** | Xbox Series S 512 GB · *R$ 2.500–3.500* | PlayStation 5 Slim digital · *R$ 3.500–4.700* | PlayStation 5 Pro · *≥ R$ 5.500* |

Os itens sem "URLs" marcadas têm 1 URL. Conta: 30 modelos × 1 URL = 30,
mais 8 URLs extras = **38**.

**Onde foram as 8 URLs extras:**
- GPU: +3, uma por faixa, porque a marca da placa muda muito o preço;
- placa-mãe: +2 (baixo e médio, onde há mais marcas no mesmo chipset);
- notebook: +2 (baixo e médio, configurações parecidas de marcas
  diferentes);
- RAM médio: +1.

Não recebem URL extra:
- processador e console: o produto é igual em qualquer anúncio;
- topo de RAM, SSD, fonte e monitor: há pouca oferta na própria loja.

**Saíram em relação à T24d:**
- RX 9060 XT, Ryzen 5 7600, B760, Moto G e Switch 2: não cabem em 3 por
  categoria;
- NVMe 2 TB PCIe 4.0: virou PCIe 5.0 no alto.

A AMD continua na CPU (baixo e alto), e a Intel fica no médio.

**Por que cada alto:**
- RTX 5090, Ryzen 9 9950X3D e X870E: o topo que mais sente a alocação para
  IA e a memória;
- DDR5 64 GB e PCIe 5.0: as configurações onde a crise de memória aparece
  primeiro;
- iPhone 17 Pro: importado, cotado em dólar;
- notebook gamer de topo: GPU + memória juntos;
- monitor OLED: painel caro, de outra cadeia;
- PS5 Pro: topo de console.

#### Variação: cada faixa com a própria

Recomendo **cada faixa ter a própria variação**, como o Coordenador
sugeriu. O topo costuma andar diferente: na falta de memória ele sobe antes
e mais; em promoção de lançamento, cai. Uma média das três esconderia isso.

Na aba, a categoria mostra:

```
Placa de vídeo     baixo R$ 2.199   ·   médio R$ 4.799   ·   alto R$ 15.999
30 dias            +3,1%            ·   +5,4%            ·   +12,0%
```

Valores ilustrativos. A variação é **pareada**: cada modelo contra ele mesmo,
e com troca de modelo encadeada. A média das três faixas aparece só na aba
Técnico, com o rótulo "média simples das três faixas". Ela não é o "preço da
categoria".

#### Mínimos (ajuste da T24d para 3 faixas)

| nível | regra |
| --- | --- |
| faixa com 2 URLs | publica com 2 válidas (mediana = média das duas); com 1, publica com o aviso "1 de 2 anúncios" |
| faixa com 1 URL | publica se for válida, com o aviso "anúncio único" |
| categoria | publica com **≥ 2 das 3 faixas** válidas; a faixa sem dado aparece como "sem preço hoje", nunca com o preço de ontem |

#### K14b — faixas plausíveis revistas para caber o topo

As faixas da T24d não comportavam o topo de notebook e de RAM.

| categoria | mínimo (R$) | máximo (R$) | mudança |
| --- | --- | --- | --- |
| GPU | 300 | 40 000 | máx. 30 000 → 40 000 (RTX 5090) |
| RAM | 50 | 10 000 | máx. 5 000 → 10 000 (64 GB DDR5 na crise de memória) |
| SSD | 80 | 8 000 | máx. 5 000 → 8 000 |
| CPU | 200 | 15 000 | — |
| placa-mãe | 250 | 10 000 | máx. 8 000 → 10 000 |
| fonte | 150 | 5 000 | máx. 4 000 → 5 000 |
| celular | 400 | 20 000 | — |
| notebook | 1 500 | 60 000 | máx. 30 000 → 60 000 |
| monitor | 300 | 15 000 | máx. 10 000 → 15 000 |
| console | 1 000 | 10 000 | — |

As faixas baixo, médio e alto são um critério de **curadoria** (que modelo
entra). As faixas K14b são **proteção** contra preço absurdo no dia (centavos
lidos como reais, `0`, `1e9`). Não se confundem: um modelo pode sair da faixa
de curadoria por promoção e continuar válido no dia.

#### Para o usuário aprovar (junto com os pontos que vieram da T24d)

1. A cesta acima: 30 modelos, 38 URLs, com as faixas em R$.
2. Variação própria por faixa, com a média das três só na aba Técnico.
3. Mínimo da categoria: 2 das 3 faixas.
4. Da T24d, ainda pendentes:
   - preço à vista como principal e cheio na 2ª linha;
   - oferta relâmpago fora da mediana (depende do campo `oferta`);
   - rótulo "Preço na KaBuM (à vista)", com a linha "Uma loja, 38 anúncios
     acompanhados por dia. Não é média de mercado.".

### T24f — GPU com duas marcas por faixa e visão AMD × NVIDIA (05/11/2026; só documento)

**Decisão do usuário:**
- baixo = RTX 5060 8 GB + RX 9060 XT 16 GB;
- médio = RTX 5070 12 GB + RX 9070 XT 16 GB;
- alto = RTX 5090 32 GB (a AMD não tem concorrente no topo).

Na aba Preços cada faixa mostra **um preço único**, com as duas marcas
juntas. Uma visão à parte mostra AMD e NVIDIA separadas. Esta seção
**substitui só a linha de GPU** da T24e; o resto continua.

#### 1. URLs de GPU (teto de 40 no total)

| faixa | NVIDIA | AMD | URLs |
| --- | --- | --- | --- |
| baixo · *R$ 1.500–2.800* | RTX 5060 8 GB ×2 | RX 9060 XT 16 GB ×2 | 4 |
| médio · *R$ 3.500–6.000* | RTX 5070 12 GB ×2 | RX 9070 XT 16 GB ×2 | 4 |
| alto · *≥ R$ 12.000* | RTX 5090 32 GB ×2 | — | 2 |
| **GPU** | | | **10** (antes 6) |

Cada marca fica com **2 URLs** (montadoras diferentes) para não cair em
"anúncio único" na visão separada. Com 1 URL, uma placa mais cara de uma só
montadora viraria "o preço da AMD".

**Conta:** a T24e tinha 38 URLs. A GPU pede +4, o que daria 42. Proposta:
- **usar as 2 sobras** aqui;
- tirar 2 URLs extras de onde a diferença entre marcas importa menos:
  - RAM médio, de 2 para 1 (kits DDR5 32 GB 6000 variam pouco entre
    marcas);
  - placa-mãe baixo, de 2 para 1 (A520 é chipset de entrada, com pouca
    variação).

Os 2 extras de notebook ficam, porque é a categoria mais heterogênea. Total:
**40**, exatamente o teto (K3), sem folga. Uma troca de modelo na curadoria
precisa ser troca de URL, não acréscimo.

**Alternativa**, se o usuário quiser manter folga: tirar também os 2 extras
de notebook. O total fica em 38, com 2 livres.

#### 2. Preço único da faixa: cada marca pesa igual

Recomendo **marcas com peso igual**, como o Coordenador sugeriu. Calcular
URL por URL faria a marca com mais anúncios dominar. Com 2 URLs para cada,
hoje dá o mesmo resultado, mas a regra precisa valer quando uma URL fica
indisponível.

```
preço da marca  = mediana das URLs válidas daquela marca (com 2, é a média)
preço da faixa  = média dos preços das marcas válidas no dia
variação faixa  = média das variações das marcas válidas nos dois dias
                  (pareada: cada marca contra ela mesma)
```

**Marca ausente no dia** (todas as URLs dela indisponíveis ou suspeitas):
- o preço da faixa sai só da outra marca, com o aviso "só NVIDIA hoje" (ou
  "só AMD");
- a **variação** continua pareada e usa só a marca presente nos dois dias,
  para a falta de uma marca não aparecer como salto de preço;
- com as duas marcas ausentes, a faixa fica "sem preço hoje".

Mínimo para publicar a faixa: pelo menos 1 marca com 1 URL válida, com os
avisos acima.

#### 3. Visão AMD × NVIDIA

Uma tabela por faixa (o lugar na interface fica com o Frontend: aba nova ou
sub-aba em Preços):

| faixa | NVIDIA | AMD | diferença | variação 30 dias |
| --- | --- | --- | --- | --- |
| baixo | RTX 5060 · R$ 2.199 | RX 9060 XT · R$ 2.499 | AMD +13,6% | NVIDIA +2,0% · AMD +4,1% |
| médio | RTX 5070 · R$ 4.799 | RX 9070 XT · R$ 4.999 | AMD +4,2% | NVIDIA +5,4% · AMD +3,0% |
| alto | RTX 5090 · R$ 15.999 | sem concorrente nesta faixa | — | NVIDIA +12,0% |

Valores ilustrativos.

- **Diferença** = preço AMD ÷ preço NVIDIA − 1, sempre na mesma direção, com
  o rótulo "AMD +X%" ou "AMD −X%".
- **Nota fixa:** "Compara o preço dos modelos escolhidos em cada faixa, não o
  custo por desempenho. A RX 9060 XT tem 16 GB e a RTX 5060 tem 8 GB."
- **Histórico:** uma linha por faixa com a diferença ao longo do tempo
  ("prêmio de uma marca sobre a outra"). Com ≥ 30 dias, dá para ver se a
  alta da memória pegou uma marca antes da outra.
- **Topo:** só NVIDIA. A célula AMD diz "sem concorrente nesta faixa", sem
  diferença calculada e sem trocar por uma AMD de outra faixa.
- **Aviso por marca:** "1 de 2 anúncios" quando só uma URL da marca for
  válida, como na T24e.

**Séries a gravar:** `price.gpu.<faixa>.<marca>`, `price.gpu.<faixa>` e
`price.gpu.<faixa>.diff_amd_pct`, todas do tipo observado (uma loja).

#### 4. CPU (AMD × Intel) como opção para o usuário

Dá para fazer o mesmo:

| faixa | AMD | Intel |
| --- | --- | --- |
| baixo | Ryzen 5 5600 | Core i5-12400F ou i3-14100F |
| médio | Ryzen 5 7600 | Core i5-14400F |
| alto | Ryzen 9 9950X3D | Core Ultra 9 285K |

Com 1 URL por modelo (o processador é igual em qualquer anúncio), são
**+3 URLs**. Com o teto em 40 e sem folga, seria preciso tirar 3 de outro
lugar:
- os 2 extras de notebook + 1 extra de placa-mãe médio; ou
- reduzir o topo de GPU para 1 URL.

**Recomendo deixar para depois.** Na CPU a diferença AMD × Intel mede mais a
plataforma (soquete, geração) do que a oferta de chips. O custo é tirar
variação de marca do notebook, que pesa mais na leitura do consumidor. Se o
Mercado Livre voltar como reforço, o teto da KaBuM deixa de apertar e a CPU
entra sem cortes.

#### Para o usuário aprovar

1. GPU com 10 URLs (2 por marca por faixa) e os cortes em RAM médio e
   placa-mãe baixo, para fechar em 40. Ou a alternativa de 38, sem os extras
   de notebook.
2. Preço da faixa com as marcas pesando igual, e a variação pareada por
   marca.
3. A visão AMD × NVIDIA como descrita (diferença, variação por marca,
   histórico da diferença, topo só NVIDIA).
4. CPU AMD × Intel: agora (com quais cortes) ou depois (recomendado).

### T24g — Cesta aprovada (05/11/2026)

**Aprovado pelo usuário (via Coordenador).** Esta é a versão de referência
para a curadoria (T27, Dados) e para a implementação, que ainda **não está
liberada**. Quando houver diferença com T24b–T24f, vale esta seção.

**Decisões:**
1. **Opção B:** 38 URLs, com 2 livres no teto de 40 (K3). Saem os extras de
   notebook, de RAM médio e de placa-mãe baixo.
2. **GPU:** marcas com peso igual no preço da faixa e variação pareada por
   marca.
3. **Visão AMD × NVIDIA:** fica na sub-aba "Por marca", dentro de Preços.
4. **CPU AMD × Intel:** fica para depois.
5. **Preço:**
   - à vista (`priceWithDiscount`) como principal, com o cheio na 2ª linha;
   - oferta relâmpago fora da mediana;
   - rótulo "Preço na KaBuM (à vista)", com a linha "Uma loja, 38 anúncios
     acompanhados por dia. Não é média de mercado.".

**Cesta final** (faixa = preço à vista em R$ na curadoria; o número entre
parênteses é de URLs, e onde não aparece é 1 URL):

| categoria | baixo | médio | alto | URLs |
| --- | --- | --- | --- | --- |
| GPU | RTX 5060 8 GB (2) + RX 9060 XT 16 GB (2) · 1.500–2.800 | RTX 5070 12 GB (2) + RX 9070 XT 16 GB (2) · 3.500–6.000 | RTX 5090 32 GB (2) · ≥ 12.000 | 10 |
| RAM | DDR4 16 GB 2×8 3200 · 250–800 | DDR5 32 GB 2×16 6000 · 800–2.200 | DDR5 64 GB 2×32 ≥ 6000 · ≥ 2.200 | 3 |
| SSD | SATA 480/512 GB · 150–450 | NVMe 1 TB PCIe 4.0 · 400–1.000 | NVMe 2 TB PCIe 5.0 · ≥ 1.200 | 3 |
| CPU | Ryzen 5 5600 · 500–900 | Core i5-14400F · 900–1.800 | Ryzen 9 9950X3D · ≥ 4.000 | 3 |
| Placa-mãe | A520 · 400–750 | B650 (2) · 900–1.700 | X870E · ≥ 2.500 | 4 |
| Fonte | 550–600 W Bronze · 250–450 | 750 W Gold ATX 3.x · 500–1.000 | 1000 W+ Platinum ATX 3.1 · ≥ 1.300 | 3 |
| Celular | Galaxy A1x vigente 128 GB · 800–1.400 | Galaxy A57 5G 256 GB · 1.800–3.000 | iPhone 17 Pro 256 GB · ≥ 8.000 | 3 |
| Notebook | i3/Ryzen 3, 8 GB, 256 GB · 2.000–3.200 | i5/Ryzen 5, 16 GB, 512 GB · 3.500–5.500 | gamer RTX 5080/5090 Laptop · ≥ 15.000 | 3 |
| Monitor | 24" 1080p IPS 100 Hz · 500–900 | 27" 1440p 165–180 Hz · 1.200–2.300 | 27" OLED 1440p ≥ 240 Hz · ≥ 4.000 | 3 |
| Console | Xbox Series S 512 GB · 2.500–3.500 | PS5 Slim digital · 3.500–4.700 | PS5 Pro · ≥ 5.500 | 3 |
| **Total** | | | | **38** (32 modelos) |

**Regras que acompanham a cesta** (detalhe nas seções citadas):

| tema | regra | onde |
| --- | --- | --- |
| URL válida | disponível, vendida pela KaBuM, dentro do K14b e não "suspeita" | T24d |
| preço da faixa | mediana das URLs válidas; na GPU, média das marcas válidas | T24e, T24f |
| variação | por faixa, pareada e encadeada na troca; na GPU, pareada por marca | T24e, T24f |
| publicação da faixa | 1 válida com o aviso "anúncio único" ou "1 de 2"; na GPU, "só NVIDIA/AMD hoje" | T24d, T24f |
| publicação da categoria | ≥ 2 das 3 faixas; a faixa sem dado mostra "sem preço hoje" | T24e |
| K14b | faixas plausíveis revistas para caber o topo | T24e |
| K14d | salto > 40% vira "suspeito"; confirmado se o dia seguinte ficar a ±5% | T24d |
| K14e | indisponível fica fora, sem repetir o último preço | T24d |
| exibição | três faixas lado a lado; a média das três só na aba Técnico; IPCA do subitem ao lado | T24e, T24c |

**Curadoria (T27):** os problemas de faixa (modelo fora do intervalo em R$)
ou de vendedor (não vendido pela própria KaBuM) voltam para o Modelo
ajustar. O ajuste deve trocar por um modelo da **mesma faixa**, ou rever o
intervalo se o modelo típico daquela faixa estiver fora dele.

## T29 — Contas puras de preço e de oferta (prontas, desligadas)

**Status:** implementado e desligado. Nenhum módulo do app importa os dois
arquivos novos (`grep` vazio), então `ranking.py`, `supply.py`, os
números em produção e o `MODEL_VERSION` (`b8b59bd7ca33`) continuam iguais.
A troca será feita num passo só, quando o Dados entregar TSMC e SEC, junto
com `MODEL_VERSION` e o `model_since` por série (T28b).

### `app/domain/prices.py` (§T24g) — flag `PRICES_ENABLED = False`

- `BASKET`: os 32 modelos e as 38 URLs, com a faixa de curadoria em R$.
  `validate_basket()` confere o teto de 40, as 3 faixas por categoria e se
  toda categoria tem faixa K14b. `in_curation_band()` serve para a troca de
  modelo.
- `screen_listing()` decide se a URL vale no dia:
  - disponível (K14e);
  - vendedor `"KaBuM!"`;
  - fora de oferta relâmpago;
  - preço finito e > 0, sem `bool`;
  - à vista ≤ cheio;
  - dentro da faixa K14b.
- `screen_series()` aplica o K14d: salto > 40% vira "suspeito". Se o dia
  seguinte ficar a ±5%, o preço passa a valer a partir dele e o dia suspeito
  fica fora. Se não ficar, o suspeito é descartado. Indisponível vira
  lacuna, sem repetir o último preço.
- `band_day()` calcula o preço da faixa: mediana por marca e média simples
  das marcas. Avisos: "anúncio único", "N de M anúncios" (com o prefixo da
  marca na GPU), "só NVIDIA hoje" e "sem preço hoje".
- `diff_amd_pct()` = AMD ÷ NVIDIA − 1, em %. Sem uma das marcas (no topo,
  por exemplo), devolve `None`.
- `band_change()` calcula a variação de 30 dias pareada por marca, com as
  marcas presentes nas duas datas. Sem 30 dias de história, `None`.
- `category_day()` só publica a categoria com ≥ 2 das 3 faixas.
- **Ainda não implementado:** o encadeamento na troca de modelo, que precisa
  do identificador do modelo na série (vem com a coleta).

### `app/domain/supply_fronts.py` (§T24c) — flag `FRONTS_ENABLED = False`

- `dio()` = estoque ÷ (CPV ÷ dias do trimestre). `aggregate_dio()` =
  Σ estoque ÷ Σ CPV diário.
- `company_dio()`: o último trimestre contra os 20 anteriores. "O normal" é
  o P25–P75 desses 20, e a pressão = 50 + 50·tanh(−z/1,5).
- `group_dio()` (frente lógica): o z é a média simples dos z por empresa, e
  o card usa o DIO agregado nos trimestres que todas as empresas têm.
- `rolling_3m_yoy()` acha os 6 meses pelo `AAAA-MM` e não interpola: mês
  faltando derruba o ponto. `tsmc_growth()` compara o último a/a com os 60
  meses anteriores.
- `FRONT_SIGNALS` traz os pesos da §T24c (somam 1,00) e `EXPOSURE` as
  exposições das 10 categorias. `validate_fronts()` confere os dois.
- `front_score(signal_scores, category)` = Σ w·e·nota ÷ Σ w·e, só com os
  sinais presentes. Sinal geral tem e = 1, e com `category=None` sai a nota
  global, que é a do IPH. Sem nenhum sinal, devolve `None`.
- `is_fresh()`: mensal vale até 75 dias depois do fim do mês, trimestral até
  150 dias.
- `demand_queue()`: a fila só de demanda, sem o estoque, já preparada para a
  troca.

### Testes

O meu papel não edita `tests/` (é área da QA) e o Coordenador pediu para
não acionar a QA. Por isso os testes com dados de exemplo ficaram fora da
pasta do projeto:
- `/tmp/claude-1000/-mnt-Dados-Dev-datasearch-hardware/597ba87c-2d5c-44c9-99aa-ef4538c64fa6/scratchpad/t29/test_prices_t29.py`
- `/tmp/claude-1000/-mnt-Dados-Dev-datasearch-hardware/597ba87c-2d5c-44c9-99aa-ef4538c64fa6/scratchpad/t29/test_supply_fronts_t29.py`

Resultado: **39 passed**, sem rede. A suíte do projeto continua com **345
passed**. Para a QA adotar, é só mover os dois arquivos para `tests/` quando
o usuário autorizar.

### Para a troca (passo único, depois do Dados)

1. `drivers.alocacao_chips` passa a usar `front_score(...)` global, e
   `ranking` passa a usar `front_score(..., cat.key)` no lugar da nota do
   vetor.
2. `supply.build_supply` troca a fórmula pela `demand_queue`; o card de
   estoque passa a vir de `company_dio`/`group_dio`.
3. `backfill.MODEL_VERSION` passa a incluir `FRONT_SIGNALS` e `EXPOSURE`;
   o Backend registra `model_since` em `supply.queue`,
   `driver.alocacao_chips`, `iph`, `iph_br` e `cat.*`.

## T24h — Cesta ajustada à curadoria real da KaBuM (T27) — proposta

**Status:** só documento; nada ligado. Substitui a tabela da T24g onde as
duas divergirem. O Dados faz a nova rodada de curadoria (≤ 40 pedidos)
depois da aprovação.

**Decisões do usuário que entram aqui:**
- As vagas sem URL vendida por "KaBuM!" são resolvidas **trocando o modelo**
  por um substituto que a própria KaBuM vende, na mesma faixa. Nada de
  marketplace nem de loja oficial.
- A RTX 5090 ROG Edition 20 (R$ 59.999,99) fica fora, por preço anormal.

### 1. Faixas revistas pelo preço real (T27)

Os preços reais ficaram 1,5× a 6× acima das faixas da T24e em memória, SSD
e GPU. Isso é a própria crise que o painel mede. Por isso as **faixas sobem
para o preço real, e os modelos não são trocados por mais baratos**.
- Cada faixa mantém uma folga em relação às vizinhas.
- O **alto passa a ter teto de curadoria**, para edição especial (como a ROG
  de R$ 60 mil) não entrar como "topo comum".

| categoria | baixo (R$) | médio (R$) | alto (R$) | referência real T27 |
| --- | --- | --- | --- | --- |
| GPU | 2.500–4.200 | 5.500–8.500 | 9.500–30.000 | 5060 3.196–3.250; 5070 6.186–7.000; 9070 XT 7.000 |
| RAM | 900–1.800 | 3.500–7.500 | 8.500–25.000 | DDR4 16 GB 1.221; DDR5 32 GB 5.200; 64 GB no marketplace 13.841–19.510 |
| SSD | 450–900 | 1.000–2.200 | 2.800–10.000 | SATA 480 650; NVMe 1 TB 1.300; PCIe 5 2 TB 4.000 |
| CPU | 400–900 | 1.000–2.500 | 3.500–15.000 | i5-14400F 1.400; 9950X3D2 10.000 |
| Placa-mãe | 400–750 | 900–1.700 | 2.500–6.000 | A520 526; B650 989–1.460; X870E 2.900 (sem mudança) |
| Fonte | 250–450 | 500–1.000 | 1.300–3.500 | 350; 760; 1.500 (sem mudança, só o teto do alto) |
| Celular | 700–1.600 | 1.800–3.800 | 7.000–16.000 | iPhone 17 Pro 11.499 |
| Notebook | 2.500–3.900 | 4.000–7.500 | 9.000–30.000 | Aspire 5 R5 16/512 5.746; marketplace de entrada 3.284–4.479 |
| Monitor | 500–1.100 | 1.200–2.800 | 4.000–12.000 | 27" QHD 180 Hz 1.800; OLED 27" 240 Hz 6.000 |
| Console | 1.800–3.200 | 3.300–5.000 | — | sem console vendido pela KaBuM! (ver §3) |

**K14b** (proteção contra preço absurdo): passa a acompanhar as faixas.

| categoria | máximo antes | máximo agora |
| --- | --- | --- |
| RAM | R$ 10.000 | R$ 25.000 |
| SSD | R$ 8.000 | R$ 12.000 |

Os outros limites não mudam; GPU já ia até R$ 40.000 e notebook até
R$ 60.000.

### 2. Cesta revista (36 URLs; teto de 40; 4 livres)

✅ = URL da T27, já confirmada como "KaBuM!" e agora dentro da faixa nova.
🔎 = vaga que o Dados precisa achar na nova rodada; os candidatos vêm em
ordem de preferência.

| categoria | baixo | médio | alto | URLs |
| --- | --- | --- | --- | --- |
| **GPU NVIDIA** | ✅ RTX 5060 8 GB ×2 (988706, 777056) | ✅ RTX 5070 12 GB ×2 (714574, 725587) | 🔎 **RTX 5080 16 GB ×2** (ou uma 5090 comum, se a KaBuM! vender) | 6 |
| **GPU AMD** | 🔎 RX 9060 XT **8 GB** ×2 → RX 7600 8 GB | ✅ RX 9070 XT ×1 (921271), "anúncio único" | — (sem concorrente) | 3 |
| **RAM** | ✅ DDR4 16 GB (2×8) **2400**–3200 (110769) | ✅ DDR5 32 GB (2×16) 6000 (616576) | 🔎 DDR5 64 GB (2×32) **5600** → DDR5 48 GB (2×24) 6000 | 3 |
| **SSD** | ✅ SATA 480 GB (100016) | ✅ NVMe 1 TB PCIe 4.0 (621162) | ✅ NVMe 2 TB PCIe 5.0 (752218) | 3 |
| **CPU** | 🔎 Ryzen 5 5500 → Core i3-12100F | ✅ Core i5-14400F (904658) | 🔎 **Ryzen 9 9950X** → Core Ultra 9 285K (ver §4) | 3 |
| **Placa-mãe** | ✅ A520M-A PRO (280890) | ✅ B650 ×2 (525050, 523145) | ✅ X870E Gaming Plus (941248) | 4 |
| **Fonte** | ✅ **650 W** Bronze (369658) | ✅ 750 W Gold ATX 3.1 (910241) | ✅ 1000 W Platinum ATX 3.1 (910925) | 3 |
| **Celular** | 🔎 Motorola Moto G de entrada 128 GB → Xiaomi Redmi de entrada 128 GB | 🔎 Motorola intermediário 256 GB → Xiaomi Redmi Note 256 GB | ✅ iPhone 17 Pro 256 GB (925347) | 3 |
| **Notebook** | 🔎 entrada i3/Ryzen 3, 8 GB, 256–512 GB (Acer, Lenovo, Positivo… vendido pela KaBuM!) | ✅ Acer Aspire 5 R5 16/512 (952233) | 🔎 gamer com RTX 5070/5070 Ti Laptop → RTX 5060 Laptop topo de linha | 3 |
| **Monitor** | 🔎 23,8–24" 1080p IPS, 100–180 Hz (marca vendida pela KaBuM!) | ✅ ASRock 27" QHD 180 Hz (911990) | ✅ Cooler Master OLED 27" 240 Hz (886905) | 3 |
| **Console** | 🔎 Nintendo Switch (OLED ou Lite) | 🔎 Nintendo Switch 2 | — | 2 |
| **Total** | | | | **36** |

São 22 URLs já confirmadas e 14 a buscar, nas 12 vagas 🔎 (RTX 5080 e
RX 9060 XT pedem 2 URLs cada).

**Specs do Dados:** **aceito as duas.**
- Fonte baixo de 650 W: na faixa de entrada, 600 e 650 W Bronze são a mesma
  compra.
- RAM baixo DDR4 2400: a velocidade pouco muda o preço de um kit DDR4 de
  entrada, e a categoria mede memória, não desempenho.

A spec passa a ser "DDR4 16 GB (2×8) 2400–3200".

**Notebook e monitor:** "sem loja oficial" significa sem a loja Dell ou
Lenovo. Um Lenovo **vendido pela KaBuM!** é aceito.

### 3. Onde não há substituto

- **Console:**
  - PS5 Pro não existe à venda, nem no marketplace. Xbox Series S e PS5
    Slim estão só no marketplace.
  - Proposta: a categoria passa a ser **Nintendo** (Switch no baixo,
    Switch 2 no médio) e fica **sem faixa alta**.
  - Se as duas vagas forem achadas, a categoria publica com 2 de 3 faixas.
    Se só uma for, **não publica** (regra ≥ 2) e a aba mostra "sem console
    vendido pela KaBuM!", com o IPCA "Videogame" ao lado.
  - Se nenhuma aparecer, a categoria fica fora da aba de preço (só IPCA),
    e as 2 URLs viram folga.
- **GPU AMD:**
  - no **médio** há só 1 montadora vendida pela KaBuM! e a marca publica
    com "anúncio único";
  - se o **baixo** não achar 9060 XT 8 GB nem RX 7600 vendidas pela
    KaBuM!, o baixo fica só NVIDIA. A visão "Por marca" mostra "sem AMD
    vendida pela KaBuM! nesta faixa" e não calcula diferença;
  - o **alto** é só NVIDIA, como antes.
  - O preço da faixa continua com as marcas pesando igual onde houver as
    duas.
- **Celular baixo e médio:** sem Samsung vendido pela KaBuM!, a troca é por
  Motorola ou Xiaomi. Se nenhum aparecer, o celular **não** publica só com
  o iPhone: a regra é ≥ 2 de 3, e a categoria fica fora da aba de preço até
  achar.
- **Regra geral:** uma vaga sem substituto fica "sem modelo nesta faixa"
  (não é lacuna do dia). A categoria segue a regra de ≥ 2 faixas. A busca é
  refeita na revisão trimestral.

### 4. Topo de CPU: troco o 9950X3D2 pelo Ryzen 9 9950X

**Recomendação: Ryzen 9 9950X**, com o Core Ultra 9 285K como alternativa.
O 9950X3D2 só entra se nenhum dos dois for vendido pela KaBuM!.
- **Lançamento recente:** o X3D2 tende a cair de preço nos primeiros meses
  por queda natural de lançamento, e isso pareceria alívio de oferta.
- **Promoção agressiva:** já está em relâmpago a R$ 6.500 contra
  R$ 10.000 à vista (−35%). É uma série instável para medir tendência.
- **Faixa:** o 9950X e o 285K são o topo "comum" de consumo, maduros,
  normalmente com estoque próprio na loja, e ficam dentro da faixa alta
  nova (≥ R$ 3.500).
- **Fornecedor:** o 285K mantém Intel no topo, caso se queira separar
  fornecedor depois (CPU AMD × Intel ficou para depois).

### 5. Preço à vista e oferta relâmpago (regra corrigida)

**Fonte do preço:**
- `price_cash` = **`priceWithDiscount` do `__NEXT_DATA__` da página
  `/produto/<code>`**.
- `price_full` = o preço cheio, do mesmo bloco.
- O **`offers.price` do JSON-LD é o preço relâmpago** quando há oferta
  ativa, e não serve como à vista.

**Campo `oferta`** (vem do Dados):
- `oferta = true` quando o `__NEXT_DATA__` traz o bloco de oferta ativa, ou
  quando `offers.price` do JSON-LD ficar mais de 1% abaixo do
  `priceWithDiscount`;
- junto vem `preco_relampago` = `offers.price`.

**Correção na regra da T24d** (afeta `prices.screen_listing`, que é meu, a
ser feito na implementação):
- Hoje a URL em oferta sai do dia inteiro. Na T27, **20 de 24 URLs estavam
  em relâmpago** (campanha 11.11). Excluir a URL apagaria a aba em toda
  campanha.
- Como o `priceWithDiscount` continua sendo o à vista normal durante a
  oferta, a URL **continua válida com o `priceWithDiscount`**. O relâmpago só
  é guardado à parte e exibido com o selo "oferta relâmpago: R$ X".
- O preço relâmpago nunca entra na mediana. O K14d (salto > 40%) segue
  valendo como proteção, caso a loja mexa no à vista durante a campanha.

### 6. Proposta para o `kabum_basket.json` (o arquivo é do Dados)

Campos novos ou alterados por item:

| campo | mudança |
| --- | --- |
| `faixa_avista_brl` | `[min, max]` com os valores da §1, inclusive o teto do alto |
| `modelo_cesta` | o modelo revisto (ex.: "RTX 5080 16 GB", "Ryzen 9 9950X") |
| `candidatos` (novo) | lista em ordem de preferência para as vagas 🔎, ex.: `["Ryzen 9 9950X", "Core Ultra 9 285K"]` |
| `planejadas` (novo) | URLs planejadas na vaga (2 na RTX 5080 e na RX 9060 XT, 1 nas outras), para os avisos "1 de 2" e "anúncio único" |
| `oferta`, `preco_relampago` | conforme a §5 |
| `status` | `"sem_modelo_na_faixa"` para a vaga sem substituto, separado de `"fora_da_faixa"` |

A RTX 5090 ROG Edition 20 (1052409) sai da cesta com
`status: "descartado_preco_anormal"`.

### Para o usuário aprovar

1. As faixas novas em R$ (com o teto do alto) e o K14b de RAM e SSD.
2. A cesta de 36 URLs e os substitutos:
   - RTX 5080 no topo da GPU;
   - RX 9060 XT 8 GB ou RX 7600 na AMD baixo;
   - DDR5 64 GB 5600 ou 48 GB no topo da RAM;
   - Ryzen 5 5500 ou i3-12100F na CPU baixo;
   - Motorola ou Xiaomi no celular baixo e médio;
   - notebook gamer com RTX 5070 no alto;
   - monitor 24" de marca vendida pela KaBuM!.
3. Console como Nintendo (Switch e Switch 2), sem faixa alta, ou fora da aba
   de preço.
4. Ryzen 9 9950X no lugar do 9950X3D2.
5. A correção da oferta relâmpago: a URL continua válida com o
   `priceWithDiscount`, e o relâmpago é só exibido.
6. Specs do Dados aceitas: fonte de 650 W e DDR4 2400–3200.

## T29b — `prices.py` ajustado à T24h e proteção contra preço anormal

**Status:** implementado e ainda desligado (`PRICES_ENABLED = False`). Nada
no app importa `prices.py` (`grep` vazio); os números em produção não mudam.

**Mudanças em `app/domain/prices.py`:**
- **Cesta (§T24h):** 31 modelos e 36 URLs, com as faixas de curadoria
  revistas e teto no alto. Substitutos aprovados: RTX 5080, RX 9060 XT 8 GB,
  DDR5 64 GB 5600, Ryzen 5 5500, Ryzen 9 9950X, Motorola, notebook gamer RTX
  5070, Nintendo Switch e Switch 2. Specs do Dados: fonte de 650 W e DDR4
  2400–3200.
- **K14b:** RAM vai até R$ 25.000 e SSD até R$ 12.000.
- **Console sem faixa alta:** `NO_HIGH_BAND = {"console"}`. As funções
  `expected_bands()`, `validate_basket()` e `category_day()` usam isso, e o
  console precisa das duas faixas para publicar.
- **Oferta relâmpago:** não tira mais a URL do dia. O à vista
  (`priceWithDiscount` do `__NEXT_DATA__`) continua valendo; o preço
  relâmpago (`Listing.flash_price`, o `offers.price` do JSON-LD) vai só para
  `ScreenedDay.flash_price`, como selo, e nunca entra na mediana. O motivo
  `"flash"` saiu de `REASONS`.
- **"Sem modelo na faixa":**
  - `BasketItem.status` aceita `"sem_modelo_na_faixa"`. Um item com esse
    status não conta em `planned_urls()`, e por isso não gera o aviso "só
    NVIDIA hoje".
  - `BandDay.status` separa `"ok"`, `"sem_preco_hoje"` (lacuna do dia) e
    `"sem_modelo_na_faixa"` (o aviso "sem modelo nesta faixa").

**Proteção contra preço anormal na conta diária** (`screen_abnormal`).
Critério, por modelo e por dia, aplicado depois do K14b, K14d e K14e: a URL
sai da mediana com o aviso "suspeito: preço anormal" se cumprir qualquer uma
das duas regras.

| regra | motivo |
| --- | --- |
| à vista > **1,5×** a mediana das **outras** URLs do mesmo modelo | Montadoras diferentes do mesmo chip ficam a até ~30–40% umas das outras; edição especial fica a 2–4×. Com 2 URLs, só a mais cara pode sair, e só se for 1,5× a outra. Testado: 5060 a 3.196 × 3.250 fica; 5070 a 6.186 × 9.000 fica. |
| à vista > **1,5×** o teto da faixa de curadoria | Pega o modelo de URL única com preço fora do mercado. Passar do teto, por si, não basta, porque na crise de memória isso é alta real. O teto já tem folga sobre o preço real (alto da GPU até R$ 30 mil para uma 5080 de ~R$ 12 mil). Com 2× o teto, a ROG de R$ 59.999,99 escaparia (2 × 30 mil = 60 mil); com 1,5×, ela sai. |

A comparação com o mercado vem da faixa de curadoria, que foi definida pelo
preço real (T27). Com uma loja só, não há outra referência de mercado sem
fonte com chave. `band_ceiling()` devolve o teto de cada modelo.

**Testes** (`docs/agentes/testes-pendentes/test_prices_t29.py`; o usuário
ainda não autorizou a QA a movê-los para `tests/`):
- 11 casos novos ou revistos: cesta de 36 URLs; console sem a faixa alta;
  relâmpago como selo; K14b novo; preço anormal contra as outras URLs e
  contra o teto, com o caso da ROG e as bordas de 1,5×; "sem modelo na
  faixa" diferente de "sem preço hoje"; item sem modelo fora do planejado;
  console precisando das duas faixas; teto de curadoria do topo.
- Resultado: `docs/agentes/testes-pendentes/` com **47 passed**; `tests/`
  com **345 passed** (sem mudança).

**Fica para a ligação:**
- montar `Listing` a partir do `kabum_basket.json` e da coleta, com
  `flash_offer`/`flash_price` e o id do modelo;
- encadear a troca de modelo;
- gravar as séries `price.*`.

## T24i — Teto de "consumidor médio" e preço cheio como principal (proposta)

**Status:** só documento. O `prices.py` (desligado) é ajustado depois da
aprovação. Substitui a T24h onde as duas divergirem.

**Decisões do usuário que entram aqui:**
1. Só produtos com demanda real do consumidor médio. Placa de vídeo de
   R$ 10 a 60 mil fica fora, e vale o mesmo para as outras categorias.
2. **Preço principal = preço cheio** (`oldPrice` / cheio da página
   `/produto`). Ele fica estável durante o relâmpago e dispensa a busca (K5).
   O à vista vai na 2ª linha quando não há relâmpago; o relâmpago, só como
   selo. Rótulo: "Preço na KaBuM (preço cheio)".

**Dados do Coordenador usados no critério:**
- renda média do trabalhador: R$ 3.722/mês (PNAD 1T26), e ~69% ganham até 2
  salários mínimos;
- no Steam, as GPUs mais usadas são RTX 5070, 3060 e 4060; a 5090 tem ~0,4%
  e a 4090 ~0,7%;
- guias de compra (KaBuM, 15/10): RX 7600 ~R$ 2.000; RTX 5070 e RX 9070 XT
  ~R$ 5.300–5.500.

### 1. Critério de teto, o mesmo para as 10 categorias

Duas regras, aplicadas em todas as categorias:

**(a) Teto de renda: preço cheio ≤ R$ 10.000.**
- O preço cheio da KaBuM é o parcelado em 10× sem juros.
- R$ 10.000 = 10 parcelas de R$ 1.000 ≈ **27% da renda média mensal**
  (R$ 3.722) durante 10 meses. Acima disso, o bem deixa de ser compra do
  consumidor médio, que é quem o painel quer descrever.
- É o mesmo número para todas as categorias. Ele só corta onde o produto de
  massa chega perto dele (GPU, notebook, celular).

**(b) O alto é o degrau de mercado de massa acima do médio, não o
entusiasta.**
- Fica fora, em toda categoria, o que o próprio fabricante posiciona como
  entusiasta: xx80/xx90, Ryzen 9/Core i9, chipset "E", fonte de 1000 W+ e
  Platinum, PCIe 5.0, 64 GB, OLED ≥ 240 Hz e iPhone Pro.
- O alto é o degrau seguinte de spec que ainda aparece nas configurações de
  "custo-benefício" e no topo de uso do Steam, onde houver esse dado.

**Teto da faixa alta = mínimo entre R$ 10.000 e 1,3 × o preço cheio do
modelo de referência do alto.** O 1,3 é a folga para alta real (crise de
memória) sem abrir espaço para o degrau de cima.

As faixas baixa e média seguem a T24h, convertidas para preço cheio (o cheio
fica ~1,10–1,18× o à vista, conforme o produto), com folga entre faixas.

### 2. Cesta revisada (34 URLs; teto de 40; 6 livres)

Faixas em **R$ de preço cheio**. ✅ = URL da T27b, já confirmada como
"KaBuM!" (o cheio entre parênteses). 🔎 = a buscar, com os candidatos em
ordem de preferência.

| categoria | baixo | médio | alto (teto do consumidor médio) | URLs |
| --- | --- | --- | --- | --- |
| **GPU** | 2.500–4.500 · ✅ RTX 5060 ×2 (3.736; 3.760) + ✅ RX 7600 ×2 (3.022; 2.941) | 5.000–7.900 · ✅ RTX 5070 ×2 (7.278; 7.609) + 🔎 RX 9060 XT 16 GB ×1 | 8.000–**10.000** · 🔎 RTX 5070 Ti 16 GB ×2 + ✅ RX 9070 XT ×1 (8.046) | 10 |
| **RAM** | 1.000–2.200 · ✅ DDR4 16 GB 2400–3200 (1.436) | 2.300–4.500 · 🔎 DDR5 16 GB (2×8) 5600–6000 | 4.600–8.000 · ✅ DDR5 32 GB (2×16) 6000 (6.118) | 3 |
| **SSD** | 500–1.100 · ✅ SATA 480 GB (765) | 1.200–2.300 · ✅ NVMe 1 TB PCIe 4.0 (1.529) | 2.400–4.000 · 🔎 NVMe 2 TB **PCIe 4.0** | 3 |
| **CPU** | 500–1.300 · ✅ Ryzen 5 5500 (1.119) | 1.400–2.600 · ✅ i5-14400F (1.647) | 2.700–5.000 · 🔎 Ryzen 7 9700X → Ryzen 7 7700 | 3 |
| **Placa-mãe** | 450–900 · ✅ A520M-A PRO (584) | 1.000–1.900 · ✅ B650 ×2 (1.099; 1.622) | 2.000–3.500 · 🔎 B850 → X870 (sem "E") | 4 |
| **Fonte** | 300–600 · ✅ 650 W Bronze (389) | 650–1.000 · ✅ 750 W Gold (844) | 1.050–1.800 · 🔎 850 W Gold ATX 3.1 | 3 |
| **Celular** | — | — | — | 0 (**fora da aba**, ver §3) |
| **Notebook** | 2.800–4.500 · 🔎 entrada i3/Ryzen 3 vendido pela KaBuM! | 4.600–7.500 · ✅ Acer Aspire 5 R5 16/512 (6.760) | 7.600–**10.000** · 🔎 gamer RTX 5050/5060 Laptop (Acer Nitro, Lenovo LOQ…) | 3 |
| **Monitor** | 600–1.300 · ✅ Acer EK241Y 23,8" 120 Hz (778) | 1.400–2.800 · ✅ ASRock 27" QHD 180 Hz (2.000) | 2.900–5.000 · 🔎 27" QHD IPS 240 Hz → 27" 4K IPS 144–160 Hz | 3 |
| **Console** | 2.000–3.500 · ✅ Switch OLED bundle (2.699) | 3.600–5.500 · ✅ Switch 2 256 GB (4.499) | — | 2 |
| **Total** | | | | **34** |

São 23 URLs já confirmadas e 11 a buscar, em 10 vagas 🔎 (a RTX 5070 Ti
pede 2 URLs).

**Saem pelo critério novo:**

| item | preço cheio | motivo |
| --- | --- | --- |
| RTX 5080 ×2 | R$ 17.778 | > R$ 10 mil; xx80 |
| Acer Predator RTX 5070 | R$ 23.528 | > R$ 10 mil |
| iPhone 17 Pro | R$ 12.777 | > R$ 10 mil; Pro |
| Ryzen 9 9950X | R$ 4.793 | entusiasta (Ryzen 9) |
| X870E | R$ 3.222 | chipset "E" |
| 1000 W Platinum | R$ 1.667 | entusiasta |
| SSD PCIe 5.0 2 TB | R$ 4.706 | entusiasta |
| Monitor OLED 240 Hz | R$ 6.667 | entusiasta |
| DDR5 64 GB | — | entusiasta; já sem modelo |

**Efeito na GPU:**
- A RX 9070 XT sobe do médio para o **alto**, onde passa a ter a RTX 5070
  Ti como par. O mercado de massa fica com as duas marcas nas três faixas.
- A visão "Por marca" passa a calcular a diferença AMD × NVIDIA também no
  alto; o "topo só NVIDIA" deixa de existir.
- A RTX 5070, a mais usada no Steam, fica no médio.
- RAM e SSD descem um degrau de capacidade: o alto agora é DDR5 32 GB e
  NVMe 2 TB PCIe 4.0, porque 64 GB e PCIe 5.0 são compra de entusiasta.

**Ponto de atenção:**
- Na crise de memória, a RTX 5070 Ti pode estar acima de R$ 10 mil cheio.
  Se estiver, o alto da GPU fica só com a RX 9070 XT ("anúncio único") e com
  a NVIDIA marcada "sem modelo nesta faixa". Não se sobe o teto para caber
  um modelo.
- O mesmo vale para o notebook gamer: o teto não sobe para encaixar.

### 3. Pedidos do Dados (T27b), recalculados em preço cheio

| pedido | decisão |
| --- | --- |
| piso do GPU baixo → R$ 2.300 (à vista) | **atendido em preço cheio**: piso de R$ 2.500 cheio. As RX 7600 (2.941 e 3.022 cheio) e a ASRock 459144 (à vista 2.399,99, cerca de 2.800 cheio) entram. |
| teto do CPU baixo → R$ 1.000 (à vista) | **atendido em preço cheio**: teto de R$ 1.300 cheio. O Ryzen 5 5500 (1.119) e o i3-12100F (~1.180 cheio) cabem, e o médio começa em 1.400. |
| Switch OLED em bundle | **aceito, com ressalva.** É o único Switch vendido pela KaBuM!, e o preço (R$ 2.699, igual ao console sozinho) não é anormal. Se o bundle sair de linha, o substituto é outro Switch da mesma faixa, encadeado, sem salto. |
| celular fora da aba | **aceito.** Pelo critério novo o iPhone 17 Pro sai, e sobram 0 URLs. A aba mostra só o IPCA "Aparelho telefônico". Na revisão trimestral, buscar Motorola, Xiaomi ou um iPhone base ≤ R$ 10 mil vendido pela própria KaBuM!. |

### 4. Preço cheio como principal

| campo | fonte | uso |
| --- | --- | --- |
| **principal** | `product.prices.oldPrice` da página `/produto` (o cheio normal, estável na oferta). Sem oferta, quando `oldPrice` não vier, usar `product.prices.price` (o parcelado sem relâmpago, que é o cheio). | mediana, variação, K14b/d, anormal |
| 2ª linha | `product.prices.priceWithDiscount` **só quando não há relâmpago** (é o à vista normal) | exibição: "R$ X à vista" |
| selo | durante o relâmpago, `priceWithDiscount` (= JSON-LD `offers.price`) | "oferta relâmpago: R$ X"; nunca entra na mediana |

Com isso, a URL em relâmpago **continua na conta** pelo cheio. A §5 da T24h
e a opção 4 do Dados ficam unificadas, e a coleta segue só em `/produto`
(K5).

**Consequências:**
- **Rótulo:** "Preço na KaBuM (preço cheio)", com a linha "Uma loja,
  34 anúncios acompanhados por dia. Não é média de mercado. Preço cheio =
  parcelado em até 10× sem juros."
- **Variação pareada:** o cheio acompanha o à vista em proporção quase
  constante por produto (87–90% segundo o Dados), então a variação fica
  praticamente igual.
- **K14b, K14d e preço anormal:** passam a ser aplicados ao cheio. As faixas
  plausíveis do K14b não mudam, porque são largas. O preço anormal
  (1,5× os pares ou o teto) usa o teto da faixa em preço cheio.
- **Validade:** "cheio > 0" passa a ser obrigatório. "À vista ≤ cheio" vira
  verificação de consistência: se falhar, a URL fica "preço inválido" no
  dia.

### Para o usuário aprovar

1. O critério de teto: (a) preço cheio ≤ R$ 10 mil (10× ≈ 27% da renda
   média); (b) alto = degrau de massa acima do médio, sem entusiasta; teto do
   alto = mín(R$ 10 mil; 1,3 × o modelo de referência).
2. A cesta de 34 URLs com as faixas em preço cheio. Saem RTX 5080, Predator,
   iPhone 17 Pro, Ryzen 9, X870E, 1000 W Platinum, PCIe 5.0 e OLED. Entram,
   a buscar: RTX 5070 Ti, RX 9060 XT 16 GB, DDR5 16 GB, NVMe 2 TB PCIe 4.0,
   Ryzen 7, B850, 850 W Gold, notebook gamer RTX 5050/5060, monitor 27" QHD
   240 Hz e notebook de entrada.
3. Celular fora da aba por enquanto; Switch OLED em bundle aceito.
4. Preço cheio como principal, à vista na 2ª linha (só sem relâmpago),
   relâmpago como selo.

## T29c — `prices.py` em preço cheio e com o teto do consumidor médio (T24i)

**Status:** implementado e desligado (`PRICES_ENABLED = False`); nada no app
importa `prices.py`.

- **Cesta §T24i:** 29 modelos e 34 URLs, com as faixas em preço cheio.
  `INCOME_CEILING_BRL = 10.000`, e `validate_basket()` rejeita teto acima
  disso ou sem teto. Celular está em `OUT_OF_PRICE_TAB`: não tem faixas e
  `category_day` nunca o publica. Console segue sem a faixa alta.
- **Preço principal = cheio.** `Listing.price_full` é obrigatório.
  `listing_from_prices()` monta o `Listing` a partir de `product.prices`:
  - cheio = `oldPrice`, ou `price` quando não houver `oldPrice`;
  - à vista = `priceWithDiscount`, só sem oferta;
  - relâmpago = `priceWithDiscount`, só com oferta.
  `ScreenedDay` passou a ter `cash_price` (2ª linha, só sem relâmpago) e
  mantém o selo `flash_price`.
- **Regras sobre o cheio:** K14b, K14d e `screen_abnormal` passam a usar o
  cheio. À vista ou relâmpago acima do cheio deixa a URL "inválida" no dia.
  No alto da GPU, o teto anormal é 1,5 × R$ 10 mil = R$ 15 mil.
- **Rótulo:** `PRICE_LABEL = "Preço na KaBuM (preço cheio)"`, e `PRICE_NOTE`
  com o número de anúncios e "Preço cheio = parcelado em até 10× sem juros".
- **Testes** (`docs/agentes/testes-pendentes/test_prices_t29.py`): os casos
  novos cobrem 34 URLs, teto do consumidor médio, celular fora, rótulo,
  `listing_from_prices` em oferta e sem oferta (exemplo real do Dados),
  relâmpago pelo cheio com o à vista só sem oferta, consistência à
  vista/relâmpago ≤ cheio, teto anormal de R$ 15 mil e o alto da GPU com as
  duas marcas ("só AMD hoje" se a 5070 Ti não couber).
  Resultado: pendentes **53 passed**; `tests/` **345 passed**.

## Pedidos para outras funções

- **Backend** (`app/main.py`, `/api/methodology`):
  - em `"queue"`, usar `supply.QUEUE_METHODOLOGY`, porque a fórmula fixa no
    código ainda diz "/10" e `inventory_scale` agora é `None`;
  - expor `analyzer.FX_PASSTHROUGH_DAYS` e `FX_HORIZON_DAYS` ao lado de
    `fx_passthrough`;
  - decidir o que fazer com os 42 pontos antigos de `supply.queue`;
  - opcional: incluir `merged_by_keys` e `cross_language` no log de
    `services/news.py`;
  - T11b: adicionar `source: str | None = None` em `CategoryImport`
    (`app/schemas.py`) e corrigir a docstring "(Comex Stat)". O ranking já
    preenche o campo quando ele existir.
- **Frontend** (`app/static/index.html:491`): o texto da fórmula da fila ainda
  mostra `0.75·desvio + 0.35·(−Δestoque/receita/10)`. Trocar por
  `50 + 50·tanh(0,25·desvio + 0,25·(−z(Δestoque a/a)))`.
- **Documentação** (README §5): "Repasse cambial assumido: 85% em um
  trimestre" continua certo. Acrescentar que a projeção de 30 dias aplica
  30/90 desse repasse, e atualizar a fórmula da fila.
- **QA**: casos 1–15 acima.

## Pendências

- Backtest de verdade só depois do IPCA de outubro (e vale mais com 3–6
  meses).
- O repasse de 85% e a linearidade em 90 dias continuam como hipótese, sem
  calibração.
