# Relatório — Dados

## T05 — Comex Stat: decisão **substituir** pelo UN Comtrade mensal (04/11/2026)

### Teste do Comex Stat

Feito em 04/11/2026, das 18:22 às 18:30 UTC, com o User-Agent do projeto
(`datasearch-hardware/1.0 (+pesquisa de precos de hardware; contato: local)`),
sem `Origin`/`Referer` e sem nada que contorne bloqueio. Foram 8 pedidos, um
por vez, com 3 a 60 s entre eles.

| Pedido | Status | Observação |
| --- | --- | --- |
| `GET https://api-comexstat.mdic.gov.br/docs` | 200 | página da documentação (app JS, servidor `cloudflare`) |
| `GET …/tables/ncm?page=1&perPage=1` | 200 | JSON válido, 13 746 NCMs |
| `GET …/general/dates/updated` | 200 | último mês publicado: 2026-09 (atualizado em 2026-10-06) |
| `POST …/general` (filtro `sh6` 854232) | 429 | `"Você excedeu o limite de solicitações. Por favor, tente novamente em 10 segundos."` |
| `POST …/general` (sh6, após 30 s parado) | 429 | mesma mensagem |
| `POST …/general` (ncm 85423239, após 30 s) | 429 | mesma mensagem |
| `POST …/general` (sh6, um mês, após 60 s parado) | 429 | mesma mensagem |
| `GET …/general?filter=<json>` | 200 | ignora o filtro e devolve só a lista de anos; não serve |

O que mudou desde 03/11: os GETs não estão mais bloqueados. Mas todo POST de
consulta volta 429, inclusive o primeiro depois de 60 s parado, quando a
mensagem pede para esperar 10 s. Isso é regra de WAF para POST, não limite de
taxa. Como nenhum POST passou, **não foi possível conferir `PAYLOAD_VARIANTS`
contra a resposta real**: o contrato segue sem validação ao vivo. A
documentação é um app em JavaScript, sem OpenAPI público
(`/docs/swagger.json` e `/docs/openapi.json` devolvem 500 "No route found").

### Substituto testado: UN Comtrade, preview mensal

`GET https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=76&partnerCode=0&flowCode=M&period=AAAAMM&cmdCode=<sh6,sh6,…>`

- Sem chave; o mesmo host que o projeto já usa para o dado anual.
- O Brasil reporta ao Comtrade os números da própria SECEX: o FOB
  (`primaryValue`) e o peso líquido (`netWgt`) são o mesmo dado do Comex Stat.
- Aceita **vários SH6 numa chamada** (testado: 854232, 847130 e 852351 juntos);
  continua com um período por chamada.
- Defasagem: último mês disponível em 04/11/2026 é **2026-08**, um mês a mais
  que o Comex Stat (2026-09).
- Rodada completa ao vivo: 16 chamadas em fila, cerca de 1 min, e as **10
  categorias** voltaram com 13 meses contínuos (2025-08 → 2026-08). Exemplos de
  US$/kg em 2026-08: memória 44 268,9; processador 2 640,2; celular 2 996,0;
  notebook 244,6.

### O que fiz

- `app/providers/comtrade.py`: nova `fetch_monthly_imports(category_key, sh6,
  label, all_sh6)`. Devolve `Fetched` com chave `comtrade_monthly.<categoria>`
  e payload `{"months": [{period "AAAA-MM", fob_usd, kg, usd_per_kg}], "sh6"}`,
  o mesmo formato que `ranking._imports` já lê do Comex Stat. Uma única coleta
  de 16 meses serve todos os SH6 (memorizada no mês-calendário; falha não é
  memorizada). Mês com valor ou peso zero fica de fora; SH6 sem dado levanta
  erro, então o slot vira `unavailable` em vez de número estimado.
- `app/providers/comexstat.py`: comentário atualizado com a evidência de hoje.
  O código segue intacto e desligado.
- Não mexi em `app/config.py`, `app/services/` nem `app/domain/`.

Testes: `python -m pytest tests/ -q` → 206 passed, 4 xfailed.

### Pedidos para outras funções

- **Backend (T11):** em `collector._tasks`, quando `enable_comtrade` estiver
  ativo, registrar um job por SH6 distinto (como já faz para o Comex Stat) com
  `comtrade.fetch_monthly_imports(cat.key, cat.sh6, cat.label, [c.sh6 for c in
  CATEGORIES])`, TTL `ttl_monthly`. Depois, ou gravar o resultado no slot que
  o ranking lê, ou combinar com o Modelo uma chave nova
  (`comtrade_monthly.<cat>`). Copiar também a herança por SH6 compartilhado
  (placa de vídeo e placa-mãe usam 847330). Manter `enable_comexstat=False`.
  Sugestão: flag própria, `enable_comtrade_monthly=True`.
- **Modelo:** `ranking._imports` lê `comexstat.{cat.key}`; precisa ler também
  (ou só) `comtrade_monthly.{cat.key}`. Atenção: `months[-13]` supõe meses
  contínuos. Se faltar um mês, a comparação de 12 meses pega o mês errado. É
  mais seguro procurar o mesmo período do ano anterior pela string `AAAA-MM`.
  O rótulo `ncm_label`/provider deve dizer "UN Comtrade (dado SECEX)".
- **Documentação:** em `fontes.md` e no README, o Comex Stat continua
  rejeitado com a evidência acima (GET 200, POST 429 por WAF). O preço de
  importação passa a vir do Comtrade mensal, com dois meses de defasagem.
- **QA:** casos para teste offline de `fetch_monthly_imports`: (1) várias
  linhas do mesmo SH6 no mesmo mês são somadas; (2) mês com `netWgt` 0 ou
  ausente fica fora; (3) SH6 ausente da resposta levanta `ValueError`; (4)
  meses saem em ordem e com período `AAAA-MM`; (5) dez categorias em paralelo
  fazem uma única rodada de chamadas (memo); (6) rodada que falha por inteiro
  não fica memorizada; (7) `_recent_periods` vira o ano corretamente em
  janeiro.

### Pergunta em aberto

Apagar `comexstat.py`? Recomendo manter, desligado, por enquanto: se o WAF
liberar POST, dá para comparar os dois e usar o Comex Stat, que tem um mês a
menos de defasagem.

## T09 — correções da auditoria (04/11/2026): **feito**

| Achado | Onde | O que mudou |
| --- | --- | --- |
| S1 (média) | `news_rss._safe_link`, usado em `_parse_feed` | Item cujo link não seja `http`/`https` com host é descartado. Cobre `javascript:`, `data:`, maiúsculas misturadas e TAB no meio do esquema (`urlsplit` já tira o TAB). URL malformada (`ValueError`) também sai. |
| S3 (baixa) | `http._send_capped` / `_read_capped` | Corpo lido em streaming. Aborta com `ResponseTooLarge` acima do teto, que vale para o `Content-Length` declarado e para os bytes reais já descomprimidos (um gzip bomba também para). Teto padrão `MAX_BODY_BYTES` = 20 MB; RSS usa 5 MB (`_MAX_FEED_BYTES`). Erro definitivo: não repete e não vai para o cache. |
| S4 (baixa) | `http._request` + `_total_timeout` | `asyncio.timeout` por tentativa = 2 × timeout de fase (40 s padrão; 24 s no RSS), além do `httpx.Timeout`. Estourar vira `FetchError` "tempo total de Ns esgotado" e segue as retentativas normais. |
| S5 (baixa) | `http.build_client`, `http.check_redirect` | `max_redirects=5`. Um hook de resposta recusa (`RedirectRefused`, sem retry) redirecionamento cujo destino não seja `https`, ou cujo host seja ou resolva para IP privado, loopback, link-local, reservado, multicast ou não especificado. `build_client(transport=…)` deixa a QA testar com as defesas ativas. |
| S9 (info) | `news_rss._parse_xml` | Usa `defusedxml.ElementTree.fromstring` quando instalado. Sem ele, usa `ElementTree` só se a expat for ≥ 2.4.1; senão falha visível. Esta máquina: expat 2.9.0, defusedxml ausente. |
| Complemento S8 | `http.FetchError(body_snippet=…)`, `_decode_json` | A mensagem passa a levar só a URL e o status HTTP; o trecho do corpo de terceiros fica no atributo `body_snippet`, fora de `str(exc)`. |

Efeito colateral encontrado e corrigido: o feed da **Tom's Hardware**
(`https://www.tomshardware.com/feeds/all`) responde `301 → http://…/feeds.xml`
e passou a ser recusado pelo S5. Troquei a URL para
`https://www.tomshardware.com/feeds.xml`, que responde 200 direto.

Verificação:
- `python -m pytest tests/ -q` → 206 passed, 4 xfailed.
- Checagem offline (MockTransport, script fora da suíte): `Content-Length`
  30 MB, streaming 30 MB e RSS acima de 5 MB → `ResponseTooLarge`. gzip
  continua decodificado. Redirecionamentos para `http://`, `127.0.0.1`,
  `169.254.169.254` e `localhost` → `RedirectRefused`. Para `https` público,
  segue. Laço de redirecionamento → `TooManyRedirects` em `FetchError`. Corpo
  gotejando com timeout 0,5 s → falha em 1 s. `body_snippet` fora da
  mensagem. Feed com `javascript:`/`data:` → só o link `https` fica.
- Ciclo ao vivo: `collector.collect(force=True)` → 55/55 fontes ok em 128 s.
  Feeds: 42/43, e o que faltava (Tom's Hardware) está ok após a troca de URL.

### Ficou de fora (de propósito)

- **ChallengeDetected repetido em 403/429/503**: o xfail estrito
  `test_desafio_com_status_de_bloqueio_nao_repete` aponta um defeito real do
  `_request`. A correção é uma linha (`except ChallengeDetected: raise` antes do
  `except Exception`), mas ela transforma o xfail em XPASS e quebra a suíte até
  a QA tirar o marcador. Aplico junto com a QA quando o Coordenador liberar.

### Pedidos para outras funções

- **Coordenador/Backend:** adicionar `defusedxml>=0.7.1` ao
  `requirements.txt` (S9). O código já usa a biblioteca se ela estiver
  instalada.
- **QA:** testes offline com `http._client = http.build_client(transport=httpx.MockTransport(h))`:
  (1) `Content-Length` acima do teto; (2) corpo em streaming acima do teto
  sem `Content-Length`; (3) `get_text(max_bytes=…)` respeita o teto; (4) gzip
  ainda decodifica; (5) redirect para `http://`, IP privado, loopback,
  link-local e `localhost` → `RedirectRefused` com 1 pedido só (sem retry);
  (6) redirect `https` público segue; (7) mais de 5 redirecionamentos →
  `FetchError`; (8) corpo lento com `settings.http_timeout` pequeno → `FetchError`
  por tempo total; (9) `str(FetchError)` não contém o corpo e `body_snippet`
  contém; (10) `_parse_feed` descarta `javascript:`, `JaVa\tScript:`, `data:`,
  `https:` sem host, e mantém `https://…`; (11) `_parse_xml` recusa expat
  antiga (monkeypatch em `pyexpat.version_info` e `_defused_fromstring=None`).
- **Frontend:** o S1 tem uma defesa extra opcional no painel (`safeUrl`),
  sugerida pela Segurança. A origem já está filtrada.

## T09b — defeitos apontados pela QA (04/11/2026): **feito**

- `app/providers/fedreg.py`: `_EASE` passa a casar `removals?`. "Removals of …
  From the Entity List" agora vale −1 (alívio), não +0,5.
- `app/http.py`: `ChallengeDetected` entra no grupo de erros definitivos do
  `_request`, junto de `RedirectRefused` e `ResponseTooLarge`. O desafio
  anti-robô com 403/429/503 falha na hora, com o tipo certo e um pedido só.
- `python -m pytest tests/ -q` → 206 passed e 4 failed por **XPASS(strict)**
  (`test_alivio_no_plural_removals` e
  `test_desafio_com_status_de_bloqueio_nao_repete[403|429|503]`). É o
  esperado: a QA tira os marcadores xfail.

## T22a — cache persistido em SQLite (04/11/2026): **feito**

Pedido inicial em JSON; o usuário pediu "grave como db". Ficou em SQLite
(`sqlite3` da stdlib), num arquivo próprio, separado do `data/history.db`.

### Assinatura (app/cache.py)

```python
CACHE_FORMAT_VERSION = 1
TTLCache.save(path: str | os.PathLike[str]) -> int   # linhas gravadas; 0 se falhou
TTLCache.load(path: str | os.PathLike[str]) -> int   # entradas carregadas
```

Uso esperado pelo Backend: `cache.load("data/cache.db")` no startup, antes da
primeira coleta, e `cache.save("data/cache.db")` depois de cada coleta. Os
dois são síncronos; o `save` de 55 entradas (~2,6 MB) levou 0,22 s. Se
incomodar no loop, dá para chamar com `await asyncio.to_thread(cache.save, path)`.

### Formato

Tabela `cache_entries`, uma linha por `key` (PRIMARY KEY): `label`,
`provider`, `url`, `status`, `as_of`/`fetched_at` (ISO 8601 com fuso),
`expires_at` (epoch UTC, REAL), `error`, `note`, `payload` (TEXT em JSON) e
`format_version`. O `save` faz UPSERT de todas as entradas numa transação.

- O prazo é convertido de relógio monotônico para epoch no `save` e de volta
  no `load` (desvio medido: 0,000 s). Entrada vencida volta vencida: a
  próxima coleta busca de novo, e se a busca falhar ela vira `stale`.
- `load` não sobrescreve chave que já esteja em memória.
- Banco ausente → 0 entradas, log INFO. Banco ilegível → movido para
  `<path>.corrompido-<epoch>`, 0 entradas, log WARNING; o próximo `save`
  recria o arquivo. Linha com `format_version` diferente ou `status` fora de
  `SourceStatus` → ignorada (e sobrescrita no próximo `save`). Erro de disco
  ou de SQLite no `save` → log WARNING e retorno 0, sem derrubar a coleta.

### Tipos de payload

Levantados numa coleta real (55 fontes): `str`, `int`, `float`, `None`,
listas, dicts com chave texto e **tuplas** (as séries `(período, valor)` de
bcb, comtrade, fedreg, fred, ibge, markets, sec, usgs). Nenhum `datetime`
dentro de payload hoje. O que o JSON não tem nativamente vai marcado como
`{"__t": tipo, "v": …}` e volta com o mesmo tipo: `tuple`, `datetime`,
`date`, float NaN/inf, dict com chave não-texto ou com chave `"__t"`. Tipo
fora dessa lista (ex.: `set`, dataclass) faz **a entrada inteira não ser
persistida**, com aviso no log. Hoje nenhuma fonte cai nesse caso. Não usei
pickle.

### Verificação

- Coleta real (122 s, 55 entradas) → `save` → `load` num `TTLCache` novo:
  **55/55 `Fetched` iguais** (a igualdade de dataclass compara o payload com
  tipos, tupla ≠ lista).
- Entrada no prazo: `get_or_fetch` não chama a fonte. Entrada vencida com a
  fonte falhando → `stale` com o payload salvo.
- Versão 99 numa linha → 54 carregadas. Banco ausente → 0. Arquivo-lixo → 0
  e movido para `.corrompido-…`. Re-save sobre banco existente → 55.
- `set` no payload → entrada não persistida, com log. Tupla, datetime, date,
  NaN, chave int e chave `"__t"` → voltam com o mesmo tipo.
- `python -m pytest tests/ -q` → 345 passed.

### Para o Backend

- Incluir `data/cache.db` no que já ignora `data/` (o `.gitignore` já cobre
  `data/`).
- Limite conhecido: linhas de fontes que deixaram de existir ficam no banco e
  voltam no `load` como entradas que ninguém consulta. Não fazem mal; se
  quiser limpar, peça um `prune(keys)`.

## T22d — cache negativo e disjuntor de cota do Comtrade (04/11/2026): **feito**

### Cache negativo (app/cache.py)

- `TTLCache(failure_ttl: int = DEFAULT_FAILURE_TTL)`, com
  `DEFAULT_FAILURE_TTL = 30 * 60`. A instância global `cache = TTLCache()`
  usa o padrão; o Backend pode expor o valor em config e criar o cache com ele.
- Falha em `get_or_fetch` → a entrada resultante fica guardada por
  `min(ttl, failure_ttl)`. Pode ser `stale`, mantendo o **último payload bom**
  (uma falha nunca o apaga), ou `unavailable`, sem payload, com o erro. Dentro
  desse prazo a fonte não é consultada; `force=True` continua ignorando isso.
- Mudança de comportamento: o `stale` antes esperava 5 min para tentar de
  novo; agora espera o mesmo prazo de falha (30 min).
- `save`/`load` já persistem essas entradas: `unavailable` grava payload
  `null` e volta `None`.

### O 403 do Comtrade: é **cota esgotada**

Pedido único em 04/11/2026, 20:21 UTC:

```
HTTP/1.1 403 Quota Exceeded
Retry-After: 2285
{ "statusCode": 403, "message": "Out of call volume quota. Quota will be replenished in 00:38:05." }
```

Não é bloqueio de rede nem de IP, e o preview não passou a exigir chave: sem
User-Agent customizado o resultado é o mesmo, e a API diz quando a cota
volta. A cota foi consumida pelos ciclos ao vivo de hoje (os meus testes da
T05/T09/T22a e os starts do Backend). O agravante estava no código: a rodada
mensal que falha não fica memorizada, então cada um dos 9 SH6 refazia os 16
meses. Com o anual, eram 160 pedidos recusados por start.

### Disjuntor (app/providers/comtrade.py, app/http.py)

- `http.FetchError` ganhou `status_code` e `retry_after` (sem o teto de 30 s
  do retry).
- `comtrade._get` centraliza os pedidos: `breaker_guard("comtrade")` dentro do
  semáforo. O primeiro 403 abre o disjuntor **compartilhado por todas as 13
  chaves** até o `Retry-After` da API (sem o cabeçalho, 1 h). Sucesso fecha o
  disjuntor.
- Anual e mensal param a rodada no primeiro 403 ou com o disjuntor aberto,
  em vez de seguir ano a ano ou mês a mês.

### Verificação (ao vivo, com o Comtrade em 403)

- 1º start, 13 chaves: **1 pedido** ao Comtrade, 1,6 s, todas `unavailable`
  com o erro 403 (antes: 160 pedidos, ~75 s).
- `save` → `load` → 2º start: **0 pedidos**, 0,0 s.
- Cache negativo com fonte falsa: ok → falha (com `force`) → `stale` com o
  payload anterior; 2ª chamada no prazo não chama a fonte; `unavailable`
  guardado por 1800 s; após `save`/`load` continua sem chamar; `force=True`
  chama.
- `python -m pytest tests/ -q` → 345 passed.

### Sugestão para a fonte de importação

O Comtrade continua sendo a melhor fonte sem chave (dado da SECEX). O
problema é volume, não acesso. Com o TTL mensal (24 h), o cache persistido e
o disjuntor, um dia normal faz cerca de 32 pedidos (16 anuais + 16 mensais),
bem dentro da cota. Recomendo manter e não repetir coletas forçadas em
sequência nos testes. Se a cota voltar a apertar, dá para cortar pela metade
derivando o anual da soma dos meses, num ajuste no provider, sem mudar o
contrato. A cota volta por volta de 20:59 UTC de 04/11.

## T23 — viabilidade de fontes de oferta e de preço BR (05/11/2026): **feito (só pesquisa)**

Nenhum código do app mudou. Cada fonte teve um pedido de teste real, feito
em 05/11/2026 com o User-Agent do projeto. O que não pude testar sem cadastro
está marcado como **documentado, não verificado**.

### Resumo

| # | Fonte | Chave? | Testado | Veredito |
| --- | --- | --- | --- | --- |
| 1 | TSMC: TWSE OpenAPI + página de RI | não | ✅ 200 | **viável já** |
| 2 | SEC: NVIDIA, AMD, Intel (+ Micron) | não | ✅ 200 | **viável já**; reaproveita `sec.py` |
| 3 | DART (SK hynix, Samsung) | **sim**, grátis | ⚠️ sem chave: "등록되지 않은 인증키" | viável com a chave do usuário; divisão DS da Samsung não vem na API estruturada |
| 4 | Exportação de semicondutores da Coreia | **sim** (data.go.kr), grátis | ⚠️ 401 `SERVICE_KEY_IS_NULL` | viável com a chave; a prévia de 10/20 dias não separa semicondutores |
| 5 | Mercado Livre | **sim** (app + OAuth) | ❌ busca 403 sem token | depende de cadastro, e **não há garantia** de que a busca libere com token |
| 6 | IPCA 7060 (IBGE) | não | ✅ 200 | **viável já**; já está no app |

### 1. TSMC — receita mensal

- **TWSE OpenAPI (JSON, sem chave):**
  `GET https://openapi.twse.com.tw/v1/opendata/t187ap05_L`. Traz a receita
  mensal de todas as 1 088 listadas na TWSE; filtrar `公司代號 == "2330"`.
  Valores em **NT$ mil**. Só o **último mês** (snapshot), sem histórico.
  Exemplo real:
  `{"資料年月":"11509","公司代號":"2330","營業收入-當月營收":"511857399","營業收入-去年當月營收":"330980920","營業收入-去年同月增減(%)":"54.65","累計營業收入-當月累計營收":"3898726974","備註":"因先進製程產品需求增加所致。"}`.
  Ano no calendário Minguo: 115 = 2026, então `11509` = set/2026.
  Swagger em `/v1/swagger.json`. Licença: dados abertos do governo de Taiwan.
- **Histórico:** `https://investor.tsmc.com/english/monthly-revenue/<ano>`
  (HTML, uma tabela por ano, NT$ milhões). Ex. 2026: jan 401 255; ago 514 806;
  set 511 857 (+54,6% a/a); acumulado 3 898 727 (+41,1%). Bate com a TWSE.
- **Frequência e defasagem:** mensal, divulgada até o dia 10 do mês seguinte.
  set/2026 saiu em 17/10 na TWSE (`出表日期 1151017`).
- **Sugestão:** TWSE para o mês corrente; para o histórico, carga única da
  página de RI (parse de HTML, ano a ano) gravada no `history.db`.

### 2. SEC — NVIDIA, AMD, Intel e a suspeita da Micron

Todas via `companyconcept`, sem chave, com as funções que já existem
(`_flow_rows`, `_instant_rows`). Intel: CIK **50863**. Último trimestre:

| Empresa | Fecho | Receita | CPV | Estoque | Dias de estoque (estoque ÷ CPV × 91) |
| --- | --- | --- | --- | --- | --- |
| NVIDIA (`Revenues`, `CostOfRevenue`) | 2026-07-26 | 96,22 bi | 24,08 bi | 31,57 bi | **119** |
| AMD (`RevenueFromContract…`, `CostOfGoodsAndServicesSold`) | 2026-09-26 | 13,38 bi | 6,17 bi | 11,46 bi | **169** |
| Intel (`RevenueFromContract…`, `CostOfGoodsAndServicesSold`) | 2026-09-26 | 16,51 bi | 9,42 bi | 13,07 bi | **126** |

- **Dias de estoque** devem usar o **CPV**, não a receita: a margem da NVIDIA
  (~75%) faria estoque ÷ receita dar 30 dias, quando o giro real é de 119.
  O tag do CPV varia por empresa (`CostOfRevenue` ou
  `CostOfGoodsAndServicesSold`): usar `_first_tag` com os dois.
- **Limites:** até 10 req/s, com UA identificável (já atendido). Defasagem de
  ~4 a 6 semanas após o fim do trimestre (prazo do 10-Q).

**Suspeita da Micron (13,6 → 23,9 → 41,5 → 54,2 bi): não é acumulado.** As
linhas brutas do XBRL mostram:

| Período | Dias | Valor | Origem |
| --- | --- | --- | --- |
| 2025-08-29 → 2025-11-27 | 90 | 13,64 | 10-Q Q1, trimestre isolado |
| 2025-11-28 → 2026-02-26 | 90 | 23,86 | 10-Q Q2, trimestre isolado (o acumulado H1 é 37,50) |
| 2026-02-27 → 2026-05-28 | 90 | 41,46 | 10-Q Q3, trimestre isolado (o acumulado 9M é 78,96) |
| 2026-05-28 → 2026-09-03 | 98 | 54,23 | derivado: FY 133,19 − 9M 78,96 |

13,64 + 23,86 + 41,46 = 78,96, exatamente o acumulado de 9 meses. Os números
são trimestres reais: a receita da Micron é que cresceu muito. A única
ressalva é que **o FY2026 teve 53 semanas** (370 dias), então o Q4 tem 98
dias, contra 91 nos demais, e fica cerca de 8% inflado na comparação.
**Correção sugerida (Modelo/Dados):** normalizar o fluxo trimestral para 91
dias (`val × 91 / dias`) antes de comparar trimestres; 54,23 vira ~50,4 bi.
O TTM não muda, porque a soma dos 4 trimestres continua sendo o ano fiscal.

### 3. DART (Coreia): SK hynix e Samsung

- **Endpoint:** `GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key=<40 caracteres>&corp_code=<8 dígitos>&bsns_year=2026&reprt_code=<código>&fs_div=CFS`.
  `reprt_code`: 11013 = 1º tri, 11012 = semestre, 11014 = 3º tri, 11011 =
  anual. Traz as demonstrações consolidadas completas (receita, estoque,
  CPV etc.) em JSON.
- **Teste:** sem chave → `302` para `error1.html`; com chave inválida →
  `{"status":"010","message":"등록되지 않은 인증키입니다."}` (chave não
  registrada). O endpoint está vivo.
- **corp_code** (documentado, a conferir no `corpCode.xml`, que a própria API
  baixa): SK hynix `00164779`, Samsung Electronics `00126380`.
- **Samsung DS (memória):** a API estruturada só traz o consolidado, sem
  segmento. A receita da divisão DS aparece na nota de segmentos do relatório
  trimestral; dá para tentar pelo XBRL completo (`/api/fnlttXbrl.xml`, um zip
  por relatório), mas não testei. Alternativa: o release de resultados da
  Samsung (PDF), que não é automatizável de forma limpa. A SK hynix é
  praticamente só memória, então o consolidado já serve.
- **Frequência:** trimestral, ~45 dias após o fim do trimestre (prazo
  coreano). **Limite** (documentado): 20 000 pedidos por dia por chave.
- **Como o usuário obtém a chave (grátis, aprovação automática):**
  1. Abrir https://opendart.fss.or.kr e clicar em **회원가입** (cadastro).
  2. Cadastrar com e-mail e confirmar o link enviado.
  3. Entrar e ir em **인증키 신청/관리 → 인증키 신청** (pedido de chave),
     escolhendo uso pessoal/pesquisa.
  4. A chave de 40 caracteres aparece em **오픈API 이용현황**.
  5. Pôr a chave no `.env` (ex.: `DSH_DART_KEY=...`), **nunca no código**.
     Os termos pedem uma chave por usuário: não compartilhar.

### 4. Exportação de semicondutores da Coreia

- **Mensal por HS (o que serve):** Korea Customs Service no data.go.kr,
  "관세청_품목별 국가별 수출입실적(GW)":
  `GET https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList?serviceKey=…&strtYymm=AAAAMM&endYymm=AAAAMM&hsSgn=8542`.
  Teste sem chave → `401` `SERVICE_KEY_IS_NULL` (o endpoint existe). XML.
  Mensal, publicado por volta do dia 15 do mês seguinte.
- **Prévia de 10/20 dias:** "수출 주요국가별 10일 단위 잠정치"
  (`https://apis.data.go.kr/1220000/cntyMmUtPrviExpAcrs`, `strtYymm`,
  `endYymm`). Saídas nos dias 11 (1–10), 21 (1–20) e 1º (mês fechado),
  desde 2016, em US$ mil. **Não separa semicondutores**: só o total e 10
  países (China, EUA, UE, Vietnã, Hong Kong, Japão, Taiwan, Índia, Singapura
  e Malásia). Serve como termômetro da exportação total da Coreia, não de
  chips. O número "semicondutores nos primeiros 20 dias" só aparece no
  comunicado de imprensa da alfândega (HTML/HWP), que não é automatizável de
  forma limpa.
- **Sem chave, testado:** UN Comtrade com a Coreia como país informante
  (`reporterCode=410`, `flowCode=X`, `cmdCode=8542`). dez/2025 →
  **16,73 bi US$**; ago/2026 → vazio. **Defasagem de mais de 8 meses**,
  inútil para o painel de oferta.
- **Como o usuário obtém a chave do data.go.kr (grátis):**
  1. Cadastrar em https://www.data.go.kr (회원가입; aceita estrangeiro com
     e-mail).
  2. Abrir a página do dataset (ex.: `data.go.kr/data/15157941/openapi.do`
     para a prévia e a do "품목별 국가별 수출입실적" para o mensal por HS) e
     clicar em **활용신청** (pedido de uso). A conta de desenvolvimento é
     aprovada automaticamente, com 10 000 pedidos de tráfego.
  3. A chave (`serviceKey`) aparece em **마이페이지 → 데이터활용 → Open API**.
     Usar a versão "Decoding" na URL, codificada pelo `httpx`.
  4. Pôr no `.env` (ex.: `DSH_DATAGOKR_KEY=...`).

### 5. Mercado Livre — preço médio no Brasil

- **Busca:** `GET https://api.mercadolibre.com/sites/MLB/search?category=<id>`
  → **403 `forbidden` sem token** (testado). `/products/search` e
  `/trends` → 403 `PA_UNAUTHORIZED_RESULT_FROM_POLICIES`;
  `/highlights/MLB/category/<id>` → 401 `unspecified_token`; até
  `/sites/MLB/categories` → 403.
- **Sem token funciona:** `/sites/MLB/domain_discovery/search?q=…` e
  `/categories/<id>` (ex.: MLB1658 → "Placas de Vídeo", 14 161 anúncios).
  Servem para mapear categorias, não para preço.
- **Com token:** não verificado. O guia oficial de erro 403 lista token,
  escopo, app bloqueado, IP fora da lista e conta não validada como causas.
  Há relatos de que a busca foi restringida até para apps cadastrados. É
  preciso cadastrar e testar antes de prometer o recurso na aba Preços.
- **Campos documentados da busca** (não verificados): `id`, `title`,
  `price`, `original_price`, `currency_id`, `condition` (`new`/`used`),
  `permalink` (link do anúncio), `seller.id`/`seller.nickname`,
  `available_quantity`, `shipping.free_shipping`, `official_store_id`.
  `sold_quantity` deixou de vir exato na busca pública (faixas ou ausente):
  não contar com "vendidos".
- **Como cadastrar o app:**
  1. Ter uma conta no Mercado Livre com os dados validados.
  2. Em https://developers.mercadolivre.com.br, abrir **Minhas aplicações →
     Criar aplicação**: nome, descrição, **URI de redirecionamento https** e
     escopo só de leitura.
  3. Anotar o `client_id` (App ID) e o `client_secret`.
  4. Obter o token por OAuth (`authorization_code`, com login no navegador
     uma vez): o `access_token` dura 6 h e o `refresh_token` renova. Os dois
     ficam no `.env`, nunca no código.
  5. Testar `GET /sites/MLB/search?category=MLB1658&condition=new` com
     `Authorization: Bearer <token>`. Se ainda der 403, a fonte fica
     rejeitada, com a evidência registrada.
- **Mapa das 10 categorias** (via `domain_discovery`, testado):

| `catalog.py` | `category_id` ML | Nome ML | Domínio |
| --- | --- | --- | --- |
| gpu | **MLB1658** | Placas de Vídeo | MLB-GRAPHICS_CARDS |
| ram | **MLB1694** (alt. MLB3582) | Memórias RAM | MLB-RAM_MEMORY_MODULES |
| storage | **MLB1672** | HDs e SSDs | MLB-HARD_DRIVES_AND_SSDS |
| cpu | **MLB1693** | Processadores | MLB-COMPUTER_PROCESSORS (não MLB31674, que é processador de alimentos) |
| motherboard | **MLB1692** | Placas-Mãe | MLB-COMPUTER_MOTHERBOARDS |
| psu | **MLB6777** | Fontes | MLB-DESKTOP_COMPUTER_POWER_SUPPLIES |
| smartphone | **MLB1055** | Celulares e Smartphones | MLB-CELLPHONES |
| notebook | **MLB1652** | Notebooks | MLB-NOTEBOOKS |
| monitor | **MLB99245** | Monitores | MLB-COMPUTER_MONITORS |
| console | **MLB11172** | Consoles | MLB-GAME_CONSOLES |

  Média de preço: filtrar `condition=new` e usar **mediana**, não média
  simples, porque acessório e kit poluem a categoria.

### 6. IPCA por subitem (IBGE/SIDRA 7060)

- `GET https://servicodados.ibge.gov.br/api/v3/agregados/7060/periodos/<AAAAMM>/variaveis/63|2265?localidades=N1[all]&classificacao=315[<ids>]`.
  Sem chave, JSON, mensal desde 2020-01. Último disponível: **2026-09**
  (divulgação por volta do dia 10 do mês seguinte). Variáveis: 63 = mensal,
  69 = no ano, 2265 = 12 meses, 66 = peso.
- **Subitens e itens ligados a hardware** (classificação 315):

| id | Código IBGE | Nome | Set/2026 mês / 12 m |
| --- | --- | --- | --- |
| 7541 | 3202 | **Tv, som e informática** (item) | +1,19% / +8,89% |
| 47641 | 3202028 | Computador pessoal | −0,51% / +10,58% |
| 7794 | 9101019 | Aparelho telefônico | +0,41% / +1,19% |
| 47640 | 3202008 | Videogame (console) | +1,30% / +11,85% |
| 7542 | 3202001 | Televisor | +2,43% / +8,01% |
| 7543 | 3202003 | Aparelho de som | — |
| 47642 | 3301088 | Conserto de aparelho celular | — |

  **O IPCA não tem subitem para componentes** (placa de vídeo, memória,
  SSD, processador, placa-mãe, fonte) nem para monitor.

- **Casamento com o catálogo:**

| Categoria | Subitem | Tipo |
| --- | --- | --- |
| smartphone | 7794 Aparelho telefônico | direto |
| console | 47640 Videogame (console) | direto |
| notebook | 47641 Computador pessoal | direto (inclui desktop) |
| gpu, ram, storage, cpu, motherboard, psu | 47641 Computador pessoal | proxy (como hoje) |
| monitor | **7541 Tv, som e informática** | proxy; melhor que o 7542 Televisor usado hoje |

  Sugestão ao Modelo: trocar o proxy do monitor de 7542 para 7541, e exibir
  o 7541 como linha de referência geral de "eletrônicos" na aba Preços.

### O que depende do usuário

1. **Chave DART** (grátis, automática): cadastro em opendart.fss.or.kr.
   Necessária para SK hynix e Samsung.
2. **Chave data.go.kr** (grátis, automática): cadastro mais "활용신청" nos
   dois datasets da alfândega coreana. Necessária para a exportação de
   semicondutores da Coreia.
3. **App no Mercado Livre** (grátis; exige conta validada e URI https) mais
   um login OAuth no navegador. Sem isso não há preço de mercado. Mesmo com
   o app, a busca pode continuar em 403; só o teste dirá.
4. Decidir se aceita guardar chaves e tokens no `.env` (o padrão do projeto
   até aqui é "nenhuma chave"; a política em `docs/fontes.md` precisa mudar,
   via Documentação).

Sem depender de ninguém: TSMC (TWSE + RI), SEC (NVIDIA/AMD/Intel com CPV) e
IPCA (com 7541) podem ser implementados já.

## T25 — comparadores públicos (Zoom e Buscapé) (05/11/2026): **parado no robots.txt**

Só **2 pedidos** no total: o `robots.txt` de cada site, com o UA do
projeto, 3 s de pausa, ambos `200 text/plain`, servidor `openresty`. Nenhuma
busca, página de produto ou oferta foi pedida.

### O que os dois robots.txt dizem

Os arquivos são idênticos, salvo o nome do site e dois comentários
(atualização "Maio de 2026"). Os pontos que importam:

```
# Bloqueio de Scrapers de Inteligencia Artificial (Protecao do catalogo e dados de preco)
User-agent: GPTBot
User-agent: ChatGPT-User
User-agent: OAI-SearchBot
User-agent: ClaudeBot
User-agent: Claude-User
User-agent: Google-Extended
User-agent: PerplexityBot
User-agent: Anthropic-AI
User-agent: Amazonbot
Disallow: /
```

No Buscapé o comentário é "Bloqueio de Scrapers de Inteligencia Artificial
(Protecao de Dados)". Para `User-agent: *`, onde cairia o UA do app:

| Caminho | Regra para `*` |
| --- | --- |
| Busca por query string (`/search?q=…`, qualquer `?q=`) | **proibido** (`Disallow: *?q=`) |
| Link de oferta/redirecionamento para a loja (`/lead…`) | **proibido** (`Disallow: /lead*`) |
| Página de loja (`…/loja`), comparar (`/*/compare`), `?viewSimilar=`, `*onlyBestDeals`, `*unavailable` | **proibido** |
| Alerta de preço e AJAX (`/ajax/pricealert`, `/ajax/ajaxservice`, `/dynamic-resource/*`) | **proibido** |
| Página de produto e de categoria (caminho sem `?q=`) | não proibida |
| Sitemaps (categorias, buscas, landing pages) | declarados, não proibidos |

### Por que parei

A regra da T25 é respeitar o `robots.txt`. Os dois sites proíbem
**`Claude-User`** em tudo, e esse é o identificador de um agente Claude que
busca a pedido de um usuário: é o que esta sessão é. Pedir as páginas com o
UA do projeto para cair na regra `*` contornaria a intenção que o site
escreveu ("proteção do catálogo e dados de preço" contra IA). Por isso as
perguntas 2 a 5 (ponto de entrada, JSON-LD/`__NEXT_DATA__`, campos, exemplo
de resposta) **ficaram sem teste**.

### Veredito

| Site | Veredito | Motivo |
| --- | --- | --- |
| Zoom | **rejeitado para coleta por agente de IA**; para o app, **decisão do usuário e da Segurança** | `Claude-User`/`ClaudeBot`/`Anthropic-AI` com `Disallow: /`; para `*`, a busca (`?q=`) e o link de oferta (`/lead`) estão proibidos |
| Buscapé | idem | robots.txt idêntico |

Se a decisão for o app (UA próprio, sem IA no caminho) ler os comparadores,
o que o robots.txt deixa para `*` é: **página de produto já conhecida**
(URL fixa por modelo da cesta, montada à mão ou a partir dos sitemaps), **sem
busca** e **sem seguir o link de oferta**. Isso tem três consequências:

1. as 30 URLs da cesta precisam ser escolhidas por uma pessoa e revisadas
   quando o produto sair do ar;
2. o preço por loja só serve como informação na página: o link de cada
   oferta passa por `/lead` e não pode ser seguido;
3. o comentário explícito de "proteção dos dados de preço" indica que o site
   não quer esse uso. Recomendo ler os termos de uso antes de decidir. Eu não
   os li, porque também estão sob o `Disallow: /` para `Claude-User`.

Minha recomendação é **não usar Zoom nem Buscapé**. Para preço observado,
fica o IPCA por subitem (já no app). Para preço de mercado sem chave, resta
procurar loja ou fabricante com dado aberto e robots.txt sem esse bloqueio.
Posso levantar candidatos, sempre lendo o robots.txt primeiro.

## T25b — lojas (KaBuM, Pichau, Terabyte, Amazon BR, Samsung, Dell, Lenovo) (05/11/2026): **feito (só pesquisa)**

Regras da T25: robots.txt primeiro, UA do projeto, pausa de 3–4 s, no
máximo 5 pedidos por site, nenhum drible. Pedidos feitos: KaBuM 4, Pichau 2,
Terabyte 1, Amazon 1, Samsung 3, Dell 4, Lenovo 5. Os termos de uso foram
localizados por buscador (sem gastar pedido no site) e lidos no próprio site
quando o robots permitia.

### Veredito

| Loja | robots.txt | Termos de uso | Dado de preço | Veredito |
| --- | --- | --- | --- | --- |
| **KaBuM** | sem bloco anti-IA; `/produto/…` e `/busca/<termo>` (sem `?`) permitidos | `/politicas`: nenhuma cláusula sobre robô, coleta automatizada ou propriedade intelectual | `__NEXT_DATA__` na busca; JSON-LD `Product`/`Offer` no produto | **viável** |
| **Samsung BR** | grupo `*` (inclusive GPTBot e ChatGPT-User) só proíbe `/*/search/` e afins | loja: "uso pessoal e não comercial" do conteúdo; `/br/info/legal/`: nada sobre robôs | JSON-LD `ItemList` com 30 `Product`/`Offer` na página de categoria | **viável com ressalva** (uso não comercial) |
| **Dell BR** | sem bloco anti-IA; proíbe `/*/buy/*`, `/*/cart/*` e `outlet/*?` | material "unicamente para uso pessoal, não comercial"; "não é permitido replicar em outro servidor" | JSON embutido (`dellPrice`, `dellPriceWithoutTax`) na categoria | **viável com ressalva** (uso não comercial; não republicar) |
| **Lenovo BR** | sem bloco anti-IA; publica `llms.txt`; proíbe só `/*/search` | `/br/outlet/pt/legal/`: nada sobre robôs | categoria monta o preço no navegador; sem JSON-LD de oferta | **viável com ressalva**: falta testar a página de produto (limite de pedidos atingido) |
| **Pichau** | sem bloco anti-IA; `Disallow: /*?*` e `/api/` | — | — | **rejeitado**: `403` com `cf-mitigated: challenge` (Cloudflare) na página de termos |
| **Terabyte** | — | — | — | **rejeitado**: `403` "Just a moment…" (Cloudflare) no próprio `robots.txt` |
| **Amazon BR** | `Claude-User`, `ClaudeBot`, `Claude-SearchBot` e `Claude-Web` com `Disallow: /` | — | — | **rejeitado** (bloco anti-IA) |

### KaBuM (a melhor para componentes)

- **Entrada:** `GET https://www.kabum.com.br/busca/<termo-com-hífens>`, ex.:
  `/busca/rtx-5060`. O robots proíbe `/busca/*?` e `*?query=*`, não o caminho
  limpo. Não usar `?sort=…` (vários `Disallow`). Para a cesta, depois de
  escolher o produto, usar a URL fixa
  `/produto/<code>/<friendlyName>`, mais estável que a busca.
- **Busca:** `<script id="__NEXT_DATA__">` →
  `props.pageProps.data.catalogServer.data[]`, 60 produtos por página.
  Campos: `code`, `name`, `price` (cheio/parcelado), `priceWithDiscount` (à
  vista), `oldPrice`, `maxInstallment` ("10x de R$ 333,33"), `available`,
  `quantity`, `sellerName` ("KaBuM!" ou loja do marketplace), `sellerId`,
  `manufacturer.name`, `friendlyName` (slug do link), `offer` (oferta
  relâmpago: `priceWithDiscount`, `startsAt`/`endsAt`, `quantityAvailable`),
  `prime*`, `rating`/`ratingCount`, `warranty`. **Sem histórico de preço.**
  Trecho real:
  `{"code":988706,"name":"Placa de Video Palit GeForce RTX 5060 8GB INFINITY 2 OC …","price":3736.07,"priceWithDiscount":3250.38,"maxInstallment":"10x de R$ 333,33","available":true,"sellerName":"KaBuM!","offer":{"name":"ESQUENTA 11DO11","priceWithDiscount":2899.99,"quantityAvailable":38}}`.
- **Produto:** JSON-LD `Product` → `offers`
  `{"@type":"Offer","priceCurrency":"BRL","price":2899.99,"availability":"https://schema.org/InStock","url":"…/produto/988706/…"}`.
  O `price` do JSON-LD é o menor vigente (aqui, o da oferta relâmpago).
- **Cuidados:** a busca mistura modelos parecidos (RTX 5060 × 5060 Ti) e
  vendedores do marketplace. Filtrar por `sellerName == "KaBuM!"` e por nome
  exato, ou usar só URLs fixas de produto. Separar preço à vista
  (`priceWithDiscount`) do parcelado (`price`).

### Samsung BR (celular; monitor/TV no mesmo formato)

- **Entrada:** página de categoria, ex.
  `https://www.samsung.com/br/smartphones/all-smartphones/`.
- **Dado:** JSON-LD `ItemList` (30 itens) com `Product` → `offers`
  (`price`, `priceCurrency`, `availability`) e `url` com `modelCode`.
  Trecho real:
  `{"name":"Galaxy Z Flip8","offers":{"@type":"Offer","priceCurrency":"BRL","price":"9719.1","availability":"…/InStock"},"url":"…/galaxy-z-flip8/?modelCode=SM-F776BLIXZTO"}`.
  Não traz parcelado, vendedor (é a loja oficial) nem histórico.
- **Ressalva:** os termos da loja limitam o uso do conteúdo a "pessoal e
  não comercial". Ler um número de preço para um painel local de pesquisa é
  compatível com isso; republicar a lista não é.

### Dell BR (notebook e monitor)

- **Entrada:** `https://www.dell.com/pt-br/shop/pc-accessories/ar/computer-monitors`
  (o `/pt-br/shop/notebooks/ar/8605` redireciona para cá). Notebooks: a
  categoria equivalente.
- **Dado:** JSON escapado no HTML, com `dellPrice` ("R$ 1.199,00"),
  `dellPriceWithoutTax` ("R$ 892,24"), `marketPrice`, `showMarketPrice` e o
  título. Ex.: "Monitor Dell Pro 24 Plus — P2425H" → R$ 1.199,00. Não há
  JSON-LD de oferta: o parse é mais frágil, por regex sobre o JSON escapado.
- **Ressalva:** os termos permitem o material "unicamente para uso pessoal,
  não comercial" e proíbem "replicar em outro servidor".

### O que levar para a Segurança e o usuário

1. KaBuM cobre bem os componentes (placa de vídeo, memória, SSD,
   processador, placa-mãe, fonte) e também notebook, monitor e console.
   Samsung (celular), Dell (notebook/monitor) e Lenovo (notebook) completam
   como lojas oficiais.
2. Proposta de política para o código: só URL fixa de produto (ou
   `/busca/<termo>` limpo na KaBuM); 1 pedido por produto a cada 24 h; UA do
   projeto; parar no primeiro 403/429/desafio (o `http.py` já faz isso);
   reler o robots.txt a cada coleta; guardar só preço, data e link, nunca
   descrição ou imagem; não republicar.
3. Riscos: a KaBuM pode mudar o `__NEXT_DATA__` sem aviso (o JSON-LD do
   produto é mais estável); Samsung e Dell restringem o uso a "não
   comercial".

### Se nenhuma loja for aprovada: o que preciso do usuário para o Mercado Livre

1. Conta no Mercado Livre com os dados validados.
2. Aplicação criada em https://developers.mercadolivre.com.br (Minhas
   aplicações → Criar), com uma **URI de redirecionamento https** e escopo só
   de leitura.
3. O `client_id` e o `client_secret`, num `.env` local, nunca no chat nem no
   código.
4. Um login OAuth no navegador, uma vez, para gerar o `refresh_token`.
5. Aceitar que, mesmo com token, a busca `/sites/MLB/search` pode continuar
   em 403. Nesse caso o ML fica rejeitado, com a evidência registrada.

## T27 — curadoria das URLs fixas da cesta na KaBuM (05/11/2026): **parcial — 24 de 38 vagas com URL**

Arquivo proposto: **`app/providers/kabum_basket.json`**, ainda não ligado a
nada. Não usei `data/`: a pasta está no `.gitignore`, então a curadoria se
perderia do controle de versão, e ela fica fora da área do Dados.

### Como foi feito (regras de `seguranca.md` §T26)

- 3 rodadas, **73 pedidos** no total, todos com o UA do projeto, em série, 4 s
  de pausa, sem retentativa, sem cookies (jar zerado a cada pedido) e sem
  seguir redirecionamento:
  - rodada 1: robots + 32 buscas;
  - rodada 1b: robots + 14 buscas com termo mais específico;
  - rodada 2: robots + 24 páginas `/produto/<code>/<slug>`.
- O robots.txt foi relido no início de cada rodada (sem bloco anti-IA, igual
  ao da T25b), e **cada URL passou pelo `urllib.robotparser` antes do
  pedido**. Nenhuma foi proibida.
- **Nenhum 403, 429 ou desafio.** Houve 10 redirecionamentos de busca
  (`301`/`308` para categoria com `?search-term=`, `?facet_filters=` ou
  `?redirect_terms=`), registrados e **não seguidos**.
- Busca só para achar; a confirmação foi feita na página do produto
  (JSON-LD `Product`/`Offer`, `priceCurrency=BRL`) e no `sellerName` do
  `__NEXT_DATA__` da própria página. **As 24 URLs confirmadas são vendidas
  por "KaBuM!" e estão `InStock`.**

### Descoberta que muda a regra de preço (para o Modelo)

O **`offers.price` do JSON-LD é o preço da oferta relâmpago** quando ela
está ativa, e não o "à vista" normal. Hoje, 20 das 24 URLs estavam em
relâmpago (campanha "ESQUENTA 11DO11"). Ex.: a placa-mãe X870E sai a
R$ 2.899,99 à vista no `__NEXT_DATA__` e a R$ 1.879,99 no JSON-LD. Para
"preço à vista sem relâmpago", a fonte precisa ser o `priceWithDiscount` do
`__NEXT_DATA__` da página do produto, com o `offer` lido à parte. Usar só o
JSON-LD poria o relâmpago dentro da mediana, contra a regra da T24d. O JSON
guarda os dois (`preco_avista` e `preco_jsonld`).

### Lista (38 vagas da opção B)

Preços de 05/11/2026, por volta de 11:18. ⚡ = oferta relâmpago ativa (o
JSON-LD mostra esse preço).

| vaga | code | produto | à vista | cheio | JSON-LD | faixa da cesta | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpu.baixo NVIDIA 1 | 988706 | Palit RTX 5060 8GB Infinity 2 OC | 3.250,38 | 3.736,07 | 2.799,99 ⚡ | 1.500–2.800 | **fora** |
| gpu.baixo NVIDIA 2 | 777056 | Inno3D RTX 5060 Twin X2 8GB | 3.195,99 | 3.759,99 | 2.779,99 ⚡ | 1.500–2.800 | **fora** |
| gpu.baixo AMD 1 e 2 | — | RX 9060 XT 16 GB | — | — | — | 1.500–2.800 | **sem URL**: só marketplace (TERABYTE, Importline), R$ 4.485–5.980 |
| gpu.medio NVIDIA 1 | 714574 | Gigabyte RTX 5070 Windforce OC SFF 12G | 6.185,99 | 7.277,64 | 6.079,99 ⚡ | 3.500–6.000 | **fora** |
| gpu.medio NVIDIA 2 | 725587 | MSI RTX 5070 12G Ventus 2X OC | 6.999,99 | 7.608,68 | 6.082,99 ⚡ | 3.500–6.000 | **fora** |
| gpu.medio AMD 1 | 921271 | ASRock RX 9070 XT Challenger 16GB | 6.999,99 | 8.045,96 | 6.999,99 | 3.500–6.000 | **fora** |
| gpu.medio AMD 2 | — | RX 9070 XT | — | — | — | 3.500–6.000 | **sem URL**: só 1 montadora vendida pela KaBuM! |
| gpu.alto NVIDIA 1 | 1052409 | ASUS ROG RTX 5090 Edition 20 32GB | 59.999,99 | 66.666,66 | 59.999,99 | ≥ 12.000 | ok (ver nota) |
| gpu.alto NVIDIA 2 | — | RTX 5090 | — | — | — | ≥ 12.000 | **sem URL**: as outras 5 são marketplace |
| ram.baixo | 110769 | Corsair Vengeance LPX 16GB (2x8) **2400** DDR4 | 1.220,99 | 1.436,46 | 1.199,99 ⚡ | 250–800 | **fora**; e é 2400, não 3200 |
| ram.medio | 616576 | Kingston Fury Beast Expo 32GB (2x16) 6000 DDR5 | 5.199,99 | 6.117,64 | 5.199,99 | 800–2.200 | **fora** |
| ram.alto | — | DDR5 64 GB (2x32) ≥ 6000 | — | — | — | ≥ 2.200 | **sem URL**: só marketplace (TRUEX), R$ 13.841–19.510 |
| ssd.baixo | 100016 | Adata SU630 480GB SATA | 649,99 | 764,69 | 599,99 ⚡ | 150–450 | **fora** |
| ssd.medio | 621162 | Kingston NV3 1TB PCIe 4.0 | 1.299,99 | 1.529,40 | 1.149,99 ⚡ | 400–1.000 | **fora** |
| ssd.alto | 752218 | Kingston FURY Renegade G5 2TB PCIe 5.0 | 3.999,99 | 4.705,87 | 3.999,99 | ≥ 1.200 | ok |
| cpu.baixo | — | Ryzen 5 5600 | — | — | — | 500–900 | **sem URL**: a busca redireciona; o termo longo não traz o 5600 |
| cpu.medio | 904658 | Intel Core i5-14400F | 1.399,98 | 1.647,04 | 1.099,99 ⚡ | 900–1.800 | ok |
| cpu.alto | 1028554 | AMD Ryzen 9 **9950X3D2** | 9.999,99 | 11.764,69 | 6.499,99 ⚡ | ≥ 4.000 | ok, mas é o **X3D2**: o 9950X3D original não está à venda pela KaBuM! |
| placa_mae.baixo | 280890 | MSI A520M-A PRO | 525,60 | 584,00 | 365,99 ⚡ | 400–750 | ok |
| placa_mae.medio 1 | 525050 | ASRock B650M-HDV/M.2 | 988,99 | 1.098,88 | 816,99 ⚡ | 900–1.700 | ok |
| placa_mae.medio 2 | 523145 | ASUS TUF Gaming B650M-E WiFi | 1.460,00 | 1.622,22 | 1.149,99 ⚡ | 900–1.700 | ok |
| placa_mae.alto | 941248 | MSI X870E Gaming Plus WiFi | 2.899,99 | 3.222,21 | 1.879,99 ⚡ | ≥ 2.500 | ok |
| fonte.baixo | 369658 | MSI MAG A650BN **650 W** Bronze | 349,99 | 388,88 | 279,99 ⚡ | 250–450 | ok no preço; **650 W**, não 550–600 W |
| fonte.medio | 910241 | be quiet! Pure Power 13M 750 W Gold ATX 3.1 | 759,99 | 844,43 | 669,99 ⚡ | 500–1.000 | ok |
| fonte.alto | 910925 | Montech TITAN PLA 1000 W Platinum ATX 3.1 | 1.499,99 | 1.666,66 | 1.299,98 ⚡ | ≥ 1.300 | ok |
| celular.baixo | — | Galaxy A1x | — | — | — | 800–1.400 | **sem URL**: o vigente é o **Galaxy A17** (4G e 5G), só no marketplace, R$ 842–1.889 |
| celular.medio | — | Galaxy A57 5G 256 GB | — | — | — | 1.800–3.000 | **sem URL**: só marketplace (Magalu, MIRANDA), R$ 2.654–2.666 |
| celular.alto | 925347 | iPhone 17 Pro 256GB | 11.499,00 | 12.776,67 | 8.999,99 ⚡ | ≥ 8.000 | ok |
| notebook.baixo | — | i3/Ryzen 3, 8 GB, 256 GB | — | — | — | 2.000–3.200 | **sem URL**: 24 anúncios, todos marketplace, R$ 3.284–4.479 |
| notebook.medio | 952233 | Acer Aspire 5 Ryzen 5 5500U 16GB 512GB | 5.745,60 | 6.759,53 | 3.349,99 ⚡ | 3.500–5.500 | **fora** |
| notebook.alto | — | gamer RTX 5080/5090 | — | — | — | ≥ 15.000 | **sem URL**: nenhum nas duas buscas |
| monitor.baixo | — | 24" 1080p IPS 100 Hz | — | — | — | 500–900 | **sem URL**: só marketplace, R$ 521–828 |
| monitor.medio | 911990 | ASRock Phantom 27" QHD 180 Hz IPS | 1.799,99 | 1.999,99 | 999,99 ⚡ | 1.200–2.300 | ok |
| monitor.alto | 886905 | Cooler Master Tempest OLED 27" QHD 240 Hz | 5.999,99 | 6.666,66 | 4.999,99 ⚡ | ≥ 4.000 | ok |
| console.baixo | — | Xbox Series S 512 GB | — | — | — | 2.500–3.500 | **sem URL**: só marketplace (MEGA GIFTS), R$ 4.799 |
| console.medio | — | PS5 Slim digital | — | — | — | 3.500–4.700 | **sem URL**: só Magalu, R$ 4.749 |
| console.alto | — | PS5 Pro | — | — | — | ≥ 5.500 | **sem URL**: a busca só traz acessórios |

**Conta:** 38 vagas → 14 ok, 10 com URL mas fora da faixa, 14 sem URL vendida
pela KaBuM!.

### Os pontos que o Coordenador pediu para conferir

- **RTX 5090:** existe, vendida pela KaBuM! e em estoque, mas só **1**
  anúncio: ASUS ROG Edition 20 a **R$ 59.999,99**. É edição especial, cerca
  de 4× o piso da faixa; uma 5090 "comum" vendida pela loja não existe hoje.
  A 2ª URL não tem candidato.
- **Ryzen 9 9950X3D:** o vendido pela KaBuM! é o **9950X3D2** (outro
  produto: cache 208 MB). O 9950X3D original só aparece no marketplace. É
  preciso decidir se o X3D2 vale como o "topo de CPU".
- **iPhone 17 Pro 256 GB:** ok, KaBuM!, R$ 11.499,00 à vista (R$ 8.999,99
  no relâmpago).
- **PS5 Pro:** não há console à venda, nem no marketplace; a busca só traz
  acessórios. **Sem URL.**
- **Monitor OLED:** ok, Cooler Master Tempest 27" QHD 240 Hz, R$ 5.999,99.
  Há também o Gigabyte AORUS QD-OLED 500 Hz (R$ 8.000,00), outro candidato.
- **RX 9070 XT na faixa média:** está **fora**: R$ 6.999,99, contra o teto de
  R$ 6.000, e só 1 montadora. A RTX 5070 também passou do teto
  (R$ 6.186–7.000).
- **Galaxy A1x vigente:** é o **Galaxy A17** (A17 4G e A17 5G), mas nenhum é
  vendido pela própria KaBuM!.

### O que sugiro ao Modelo (não troquei nada)

1. **As faixas em R$ estão desatualizadas para memória, SSD e GPU.** Os
   preços reais de hoje são 1,5× a 6× maiores (DDR4 16 GB R$ 1.221; DDR5
   32 GB R$ 5.200; RTX 5060 R$ 3.196–3.250). Isso é a própria crise de
   memória que o painel quer medir: rever as faixas pelo preço real, não
   trocar os modelos.
2. **Categorias sem estoque próprio da KaBuM!** (console inteira; celular
   baixo e médio; notebook baixo e alto; monitor baixo; RAM alto; RX 9060
   XT): a K18 (só KaBuM!) zera essas vagas. As opções são (a) aceitar o
   marketplace nessas vagas, com o vendedor registrado e uma regra de
   estabilidade; (b) usar a outra loja oficial da T25b (Samsung para
   celular, Dell/Lenovo para notebook e monitor); ou (c) publicar a
   categoria com menos faixas. O console não tem saída na KaBuM.
3. **Substitutos com URL KaBuM! já vista:**
   - fonte baixo: 650 W no lugar de 550–600 W, porque não há 600 W Bronze
     vendida pela loja;
   - RAM baixo: aceitar a DDR4 2400/2666 (Corsair), porque não há 3200
     vendida pela KaBuM!;
   - GPU médio AMD: só 1 URL; publicar a marca com "1 de 2 anúncios";
   - GPU alto: 1 URL, com "anúncio único".
4. A regra de preço precisa usar o `priceWithDiscount` do `__NEXT_DATA__`
   com o `offer` separado, não o JSON-LD (veja acima).

### Pedidos para outras funções

- **Modelo:** decidir as faixas novas, os itens sem URL KaBuM!, o
  9950X3D2 e a RTX 5090 ROG; ajustar a regra "à vista" para o
  `priceWithDiscount` sem relâmpago.
- **Segurança:** a leitura do `__NEXT_DATA__` da página de produto já está
  prevista na K12/K13. Confirmar que ela vale também na coleta diária, e não
  só o JSON-LD.
- **Backend:** quando for ligar, ler a cesta de `app/providers/kabum_basket.json`.

## T27b — curadoria da cesta T24h na KaBuM (05/11/2026): **feito — 32 de 36 URLs; 4 vagas sem modelo**

Arquivo: `app/providers/kabum_basket.json` (versão 2, ainda não ligado).
Aplica a §6 da T24h: `faixa_avista_brl` com as faixas novas (inclusive o
teto do alto), `candidatos`, `planejadas`, `oferta`/`preco_relampago`, o
status `sem_modelo_na_faixa` e a ROG 1052409 em `descartados` como
`descartado_preco_anormal`.

### Execução

**26 pedidos**, todos com o UA do projeto, em série, 4 s de pausa, sem
retentativa, sem cookies e sem seguir redirecionamento, com o robots.txt
relido no início de cada rodada:
- rodada A: robots + 13 buscas;
- rodada B: robots + 10 páginas `/produto/<code>/<slug>`;
- 1 página de produto a mais, salva para examinar a estrutura de preço.

Nenhum 403, 429 ou desafio. Um redirecionamento (`/busca/console-nintendo-switch-2`,
`308` para categoria com `?search-term=`), não seguido. Parte dos
candidatos saiu das 46 buscas já salvas na T27, sem pedido novo.

Regra do usuário aplicada: só a versão comum do modelo, dentro da faixa com
teto. **Descartada:** RTX 5090 ASUS ROG Edition 20 (R$ 59.999,99, edição
especial, cerca de 2× o teto do alto). **Não há RTX 5090 comum vendida pela
KaBuM!**, então o topo ficou com a RTX 5080, o 1º candidato.

### Correção na regra de preço (afeta T24h §5 e a T30)

A §5 diz que `price_cash` vem do `priceWithDiscount` do `__NEXT_DATA__` da
**página do produto**. Isso **não vale durante a oferta relâmpago**. Na
página, `props.pageProps.product.prices` vira o preço da oferta, e o à vista
normal **não aparece em lugar nenhum**. Exemplo real (monitor Acer, 1061382):

| fonte | à vista | parcelado | "de" |
| --- | --- | --- | --- |
| busca, item do catálogo (`priceWithDiscount`/`price`) | **699,99** | 777,77 | — |
| busca, `offer.priceWithDiscount` | 459,99 (relâmpago) | — | — |
| página, `product.prices` | 459,99 | 511,10 | `oldPrice` 777,77 |
| página, JSON-LD `offers.price` | 459,99 | — | — |

O à vista normal só existe no **item da busca** (`catalogServer.data[]`),
que traz o bloco `offer` separado. Na página do produto, durante a oferta,
dá para ler o relâmpago (`prices.priceWithDiscount`), o parcelado da oferta
(`prices.price`) e o cheio normal (`prices.oldPrice`), mas não o à vista
normal. O à vista não é uma fração fixa do cheio: varia de 87% a 90%
conforme o produto.

Opções para a T30 (decisão do Modelo e da Segurança):
1. **Página do produto; em oferta, sem à vista no dia:** guardar o
   relâmpago e o `oldPrice`, e a URL fica fora da mediana enquanto a oferta
   durar. Na campanha 11.11, isso tiraria 20 de 24 URLs do ar.
2. **Página do produto; em oferta, repetir o último à vista sem oferta**,
   marcado como "à vista de <data>". Contraria a regra "nunca o preço de
   ontem" da T24e.
3. **Ler o à vista na busca** `/busca/<termo>` uma vez por dia, só para as
   URLs em oferta. A K5 da Segurança limita a busca à curadoria; seria
   preciso reabrir essa regra.
4. **Usar o `oldPrice` (cheio normal) como série principal** em vez do à
   vista: ele não muda com a oferta e está na página. Mas muda o rótulo da
   aba para "preço cheio".

Recomendo a **4**, com o relâmpago exibido à parte. É a única que usa só a
página do produto (K5), não apaga a aba em campanha e não repete o preço de
ontem. O cheio acompanha o à vista em proporção quase constante por
produto, então a variação pareada fica praticamente igual.

### Tabela final (36 vagas)

Preços de 05/11/2026. À vista e cheio vêm do item da busca (sem relâmpago);
relâmpago = JSON-LD, quando ativo. Todas as URLs abaixo: vendedor "KaBuM!",
`InStock`.

| vaga | code | produto | à vista | cheio | relâmpago | faixa (R$) | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GPU baixo NVIDIA 1 | 988706 | Palit RTX 5060 8GB Infinity 2 OC | 3.250,38 | 3.736,07 | 2.799,99 | 2.500–4.200 | ok |
| GPU baixo NVIDIA 2 | 777056 | Inno3D RTX 5060 Twin X2 | 3.195,99 | 3.759,99 | 2.779,99 | 2.500–4.200 | ok |
| GPU baixo AMD 1 | 760993 | ASUS Dual RX 7600 O8G EVO | 2.628,99 | 3.021,83 | — | 2.500–4.200 | ok |
| GPU baixo AMD 2 | 907814 | ASRock RX 7600 Challenger PRO OC | 2.499,99 | 2.941,16 | 1.999,99 | 2.500–4.200 | **fora** (R$ 0,01 abaixo) |
| GPU médio NVIDIA 1 | 714574 | Gigabyte RTX 5070 Windforce OC SFF | 6.185,99 | 7.277,64 | 6.079,99 | 5.500–8.500 | ok |
| GPU médio NVIDIA 2 | 725587 | MSI RTX 5070 12G Ventus 2X OC | 6.999,99 | 7.608,68 | 6.082,99 | 5.500–8.500 | ok |
| GPU médio AMD | 921271 | ASRock RX 9070 XT Challenger | 6.999,99 | 8.045,96 | — | 5.500–8.500 | ok (anúncio único) |
| GPU alto NVIDIA 1 | 697891 | Inno3D RTX 5080 X3 16GB | 15.999,99 | 17.777,77 | 10.199,99 | 9.500–30.000 | ok |
| GPU alto NVIDIA 2 | 1070647 | MSI RTX 5080 Inspire 3X OC Black | 15.999,99 | 17.777,77 | 14.432,99 | 9.500–30.000 | ok |
| RAM baixo | 110769 | Corsair Vengeance LPX 16GB (2x8) 2400 | 1.220,99 | 1.436,46 | 1.199,99 | 900–1.800 | ok |
| RAM médio | 616576 | Kingston Fury Beast 32GB (2x16) 6000 | 5.199,99 | 6.117,64 | — | 3.500–7.500 | ok |
| RAM alto | — | DDR5 64 GB 5600 → 48 GB 6000 | — | — | — | 8.500–25.000 | **sem_modelo_na_faixa** |
| SSD baixo | 100016 | Adata SU630 480GB SATA | 649,99 | 764,69 | 599,99 | 450–900 | ok |
| SSD médio | 621162 | Kingston NV3 1TB PCIe 4.0 | 1.299,99 | 1.529,40 | 1.149,99 | 1.000–2.200 | ok |
| SSD alto | 752218 | Kingston FURY Renegade G5 2TB PCIe 5.0 | 3.999,99 | 4.705,87 | — | 2.800–10.000 | ok |
| CPU baixo | 320799 | AMD Ryzen 5 5500 | 951,30 | 1.119,18 | 509,99 | 400–900 | **fora** (R$ 51,30 acima) |
| CPU médio | 904658 | Intel Core i5-14400F | 1.399,98 | 1.647,04 | 1.099,99 | 1.000–2.500 | ok |
| CPU alto | 609951 | AMD Ryzen 9 9950X | 4.073,66 | 4.792,54 | 3.099,99 | 3.500–15.000 | ok |
| Placa-mãe baixo | 280890 | MSI A520M-A PRO | 525,60 | 584,00 | 365,99 | 400–750 | ok |
| Placa-mãe médio 1 | 525050 | ASRock B650M-HDV/M.2 | 988,99 | 1.098,88 | 816,99 | 900–1.700 | ok |
| Placa-mãe médio 2 | 523145 | ASUS TUF Gaming B650M-E WiFi | 1.460,00 | 1.622,22 | 1.149,99 | 900–1.700 | ok |
| Placa-mãe alto | 941248 | MSI X870E Gaming Plus WiFi | 2.899,99 | 3.222,21 | 1.879,99 | 2.500–6.000 | ok |
| Fonte baixo | 369658 | MSI MAG A650BN 650 W Bronze | 349,99 | 388,88 | 279,99 | 250–450 | ok |
| Fonte médio | 910241 | be quiet! Pure Power 13M 750 W Gold | 759,99 | 844,43 | 669,99 | 500–1.000 | ok |
| Fonte alto | 910925 | Montech TITAN PLA 1000 W Platinum | 1.499,99 | 1.666,66 | 1.299,98 | 1.300–3.500 | ok |
| Celular baixo | — | Moto G 128 GB → Redmi 128 GB | — | — | — | 700–1.600 | **sem_modelo_na_faixa** |
| Celular médio | — | Motorola 256 GB → Redmi Note 256 GB | — | — | — | 1.800–3.800 | **sem_modelo_na_faixa** |
| Celular alto | 925347 | iPhone 17 Pro 256GB | 11.499,00 | 12.776,67 | 8.999,99 | 7.000–16.000 | ok |
| Notebook baixo | — | i3/Ryzen 3, 8 GB, 256–512 GB | — | — | — | 2.500–3.900 | **sem_modelo_na_faixa** |
| Notebook médio | 952233 | Acer Aspire 5 Ryzen 5 5500U 16/512 | 5.745,60 | 6.759,53 | 3.349,99 | 4.000–7.500 | ok |
| Notebook alto | 1074333 | Acer Predator Helios PHN16-73 RTX 5070 | 19.999,00 | 23.528,23 | 14.790,00 | 9.000–30.000 | ok |
| Monitor baixo | 1061382 | Acer EK241Y 23,8" FHD IPS 120 Hz | 699,99 | 777,77 | 459,99 | 500–1.100 | ok |
| Monitor médio | 911990 | ASRock Phantom 27" QHD 180 Hz | 1.799,99 | 1.999,99 | 999,99 | 1.200–2.800 | ok |
| Monitor alto | 886905 | Cooler Master Tempest OLED 27" 240 Hz | 5.999,99 | 6.666,66 | 4.999,99 | 4.000–12.000 | ok |
| Console baixo | 940533 | Switch OLED + Super Mario Bros. Wonder + 3 meses NSO (**bundle**) | 2.699,00 | 2.699,00 | 2.499,00 | 1.800–3.200 | ok, com ressalva |
| Console médio | 777177 | Nintendo Switch 2 256GB (comum) | 4.499,00 | 4.499,00 | — | 3.300–5.000 | ok |
| *descartado* | 1052409 | ASUS ROG RTX 5090 Edition 20 | 59.999,99 | 66.666,66 | — | — | **descartado_preco_anormal** |

**Conta:** 36 vagas → 30 ok, 2 fora da faixa (com URL), 4
`sem_modelo_na_faixa`. São 32 URLs, dentro do teto de 40.

### Notas por vaga

- **RTX 5080:** escolhidas as duas versões comuns (Inno3D X3 e MSI Inspire)
  a R$ 15.999,99. A ASUS TUF (690383, R$ 19.999,99) fica como reserva.
- **RX 7600:** a RX 9060 XT 8 GB (Gigabyte 734679) está a R$ 5.154,99,
  acima do teto do baixo. A 2ª RX 7600 está R$ 0,01 abaixo do piso. Sugiro
  ao Modelo **baixar o piso do baixo para R$ 2.300**, o que também inclui a
  ASRock 459144 (R$ 2.399,99).
- **CPU baixo:** o Ryzen 5 5500 (R$ 951,30) e o i3-12100F (R$ 999,99) passam
  do teto de R$ 900. Sugiro **subir o teto para R$ 1.000**; a CPU médio
  começa em R$ 1.000 e o i5-14400F está a R$ 1.400, então sobra folga.
- **Console baixo:** o único Switch vendido pela KaBuM! é um bundle (OLED +
  jogo + 3 meses de assinatura). O preço (R$ 2.699) é o de um console comum,
  não anormal, então não descartei. O risco é o bundle sair de linha e a
  série trocar de produto. O Switch Lite não é vendido pela KaBuM!.
- **Switch 2:** escolhida a versão sem bundle; os bundles EA FC 27
  (R$ 4.370,07) e Sports Resort (R$ 4.463,07) ficam fora.
- **Monitor baixo:** Acer EK241Y; reservas AOC 24G50F (R$ 799,90) e Husky
  Boreal 25" (R$ 699,99).
- **Notebook alto:** Acer Predator; reserva Gigabyte Gaming A18 RTX 5070
  (R$ 20.599,99).

### Sem modelo na faixa (4 vagas)

| vaga | o que foi buscado | o que existe |
| --- | --- | --- |
| RAM alto | DDR5 64 GB 5600; DDR5 48 GB 6000 | só marketplace (TRUEX): 64 GB R$ 13.841–19.510; 48 GB R$ 10.462 |
| Celular baixo | Moto G 128 GB; Redmi 128 GB | só marketplace (Magalu, GAZIN, NOVA ERA, Xiaomi Oficial): R$ 854–1.606 |
| Celular médio | Motorola 256 GB; Redmi Note 256 GB | só marketplace: Edge 70 R$ 2.429; Redmi Note 14 R$ 1.369–1.889 |
| Notebook baixo | i3/Ryzen 3, 8 GB | 60 anúncios, nenhum KaBuM!: lojas LENOVO, Vaio Oficial, Magalu; R$ 2.991–3.279 |

Consequência pela regra da T24h §3: o **celular fica só com o iPhone e não
publica** (regra de ≥ 2 de 3). A RAM e o notebook publicam com 2 de 3.

### Pedidos para outras funções

- **Modelo:**
  - decidir a regra de preço durante a oferta (recomendo a opção 4,
    `oldPrice`);
  - piso do GPU baixo em R$ 2.300;
  - teto do CPU baixo em R$ 1.000;
  - aceitar ou não o Switch OLED em bundle;
  - o celular fora da aba.
- **Segurança:** se a opção 3 (busca diária para itens em oferta) for a
  escolhida, rever a K5.
- **T30** (não liberada): o provider lê `app/providers/kabum_basket.json`.

## T27c — cesta T24i em preço cheio (05/11/2026): **feito — 28 de 34 URLs; 6 vagas sem modelo**

Arquivo: `app/providers/kabum_basket.json` v3, com `faixa_cheio_brl`, a
`regra_preco` e 10 `descartados` com motivo. **19 pedidos**: robots + 9
buscas; robots + 1 busca + 5 `/produto`; robots + 1 `/produto`. Em série,
4 s, sem retry, sem cookies, sem seguir redirect. Nenhum bloqueio. Um
redirect (`/busca/processador-amd-ryzen-7-9700x`, `301`) não foi seguido.

### Correção da regra do `oldPrice` (T24i §4)

| caso | `oldPrice` | `price` | cheio correto |
| --- | --- | --- | --- |
| **com oferta** (CPU 999558, placa-mãe 725580, fonte 659742, monitor 1061382) | = cheio da busca (3.058,81; 2.088,78; 1.333,32; 777,77) | parcelado da oferta | **`oldPrice`** |
| **sem oferta**, SSD 621163 | 2.764,69 (preço "de", riscado) | 2.705,87 (= cheio da busca) | **`price`** |
| **sem oferta**, RAM 708329 | 0 | 3.058,81 | **`price`** |

Regra: **cheio = `oldPrice` se `product.offer` existir; senão,
`prices.price`**. Usar `oldPrice` sempre inflaria o SSD em 2,2% e daria 0 na
RAM. Ela está gravada em `regra_preco` no JSON.

### Tabela (preço cheio; todas as URLs: "KaBuM!", em estoque)

| vaga | code | produto | cheio | faixa cheio | status |
| --- | --- | --- | --- | --- | --- |
| GPU baixo NVIDIA ×2 | 988706 · 777056 | Palit / Inno3D RTX 5060 | 3.736,07 · 3.759,99 | 2.500–4.500 | ok |
| GPU baixo AMD ×2 | 760993 · 907814 | ASUS / ASRock RX 7600 | 3.021,83 · 2.941,16 | 2.500–4.500 | ok |
| GPU médio NVIDIA ×2 | 714574 · 725587 | Gigabyte / MSI RTX 5070 | 7.277,64 · 7.608,68 | 5.000–7.900 | ok |
| GPU médio AMD | — | RX 9060 XT 16 GB | — | 5.000–7.900 | **sem modelo** (não vendida pela KaBuM!) |
| GPU alto NVIDIA ×2 | — | RTX 5070 Ti | — | 8.000–10.000 | **sem modelo**: a única KaBuM! (Palit 988703) custa **12.946,45** |
| GPU alto AMD | 921271 | ASRock RX 9070 XT | 8.045,96 | 8.000–10.000 | ok (anúncio único) |
| RAM baixo | 110769 | Corsair DDR4 16 GB 2×8 2400 | 1.436,46 | 1.000–2.200 | ok |
| RAM médio | 708329 | Kingston Fury Beast DDR5 **1×16** 6000 | 3.058,81 | 2.300–4.500 | ok; **não há kit 2×8 da KaBuM!** |
| RAM alto | 616576 | Kingston Fury Beast DDR5 32 GB 2×16 6000 | 6.117,64 | 4.600–8.000 | ok |
| SSD baixo / médio / alto | 100016 · 621162 · 621163 | Adata 480 SATA / NV3 1 TB / NV3 2 TB PCIe 4 | 764,69 · 1.529,40 · 2.705,87 | 500–1.100 · 1.200–2.300 · 2.400–4.000 | ok |
| CPU baixo / médio | 320799 · 904658 | Ryzen 5 5500 / i5-14400F | 1.119,18 · 1.647,04 | 500–1.300 · 1.400–2.600 | ok |
| CPU alto | 999558 | Ryzen 7 **7700** | 3.058,81 | 2.700–5.000 | ok (o 9700X não foi achado: a busca redireciona) |
| Placa-mãe baixo / médio ×2 | 280890 · 525050 · 523145 | A520 / B650 ×2 | 584,00 · 1.098,88 · 1.622,22 | 450–900 · 1.000–1.900 | ok |
| Placa-mãe alto | 725580 | ASUS PRIME B850-PLUS WiFi | 2.088,78 | 2.000–3.500 | ok |
| Fonte baixo / médio | 369658 · 910241 | 650 W Bronze / 750 W Gold | 388,88 · 844,43 | 300–600 · 650–1.000 | ok |
| Fonte alto | 659742 | Deepcool PN850D 850 W Gold | 1.333,32 | 1.050–1.800 | ok (a Corsair RM850x 1031690 ficou indisponível) |
| Notebook baixo | — | i3/Ryzen 3 | — | 2.800–4.500 | **sem modelo** (T27b: nenhum KaBuM!) |
| Notebook médio | 952233 | Acer Aspire 5 R5 16/512 | 6.759,53 | 4.600–7.500 | ok |
| Notebook alto | — | gamer RTX 5050/5060 | — | 7.600–10.000 | **sem modelo**: nenhum KaBuM! até R$ 10 mil (o RTX 5060 KaBuM! custa 18.823,52) |
| Monitor baixo / médio | 1061382 · 911990 | Acer 23,8" 120 Hz / ASRock 27" QHD 180 Hz | 777,77 · 1.999,99 | 600–1.300 · 1.400–2.800 | ok |
| Monitor alto | — | 27" QHD IPS 240 Hz → 27" 4K IPS 144–160 Hz | — | 2.900–5.000 | **sem modelo**: QHD 240 Hz custa 1.444–1.889 (abaixo do piso); o 4K custa 5.111,10 (acima do teto) |
| Console baixo / médio | 940533 · 777177 | Switch OLED bundle / Switch 2 | 2.699,00 · 4.499,00 | 2.000–3.500 · 3.600–5.500 | ok |

**Descartados** (em `descartados`, com motivo): ROG RTX 5090 (preço
anormal), RTX 5080 ×2, Predator, iPhone 17 Pro, Ryzen 9 9950X, X870E,
1000 W Platinum, PCIe 5.0 2 TB e OLED 240 Hz (critério T24i).

### Faixas que não batem com o mercado (para o Modelo)

- **Monitor alto:** o 27" QHD IPS 240 Hz ficou mais barato que o médio de
  180 Hz (R$ 1.444–1.889 × R$ 2.000). Sugiro um alto de R$ 1.400–2.800 com o
  240 Hz, ou trocar a definição do alto.
- **Fonte alto:** 8 das 10 fontes de 850 W Gold da KaBuM! custam R$ 667–778
  cheio, abaixo do piso de R$ 1.050 e até do médio (750 W Gold a R$ 844). O
  piso está alto demais para 850 W.
- **RAM médio:** a spec 2×8 não existe na KaBuM! em DDR5; aceitar 1×16 GB.

## T30 — coleta (TSMC, SEC, KaBuM) + ligação das contas + T31 + fontes.md (05/11/2026): **feito**

Este painel fez Dados e Modelo.

**Cesta (aprovada):** alto da GPU só AMD (9070 XT, anúncio único), NVIDIA
"sem modelo"; notebook fora da aba (só IPCA), como o celular; monitor e fonte
sem faixa alta; RAM médio DDR5 1×16. 24 itens, 26 anúncios ativos.
`PRICES_ENABLED = True`; regra do preço cheio em `listing_from_prices`.

**Provedores:**
- `kabum.fetch_basket()` → `kabum.basket` (K3–K21; teste offline na página
  salva: cheio 777,77, relâmpago 459,99; código trocado → `StoreBlocked`).
- `tsmc.fetch_monthly_revenue()` → `tsmc.monthly_revenue`. O RI deu desafio do
  Cloudflare e o MOPS antigo proíbe tudo no robots; o histórico vem da API do
  MOPS novo (`t05st10_ifrs`, 48 POSTs, para no 1º desafio/403/429) e o último
  mês da TWSE, com a data real. Ao vivo: 93 meses (2019-01…2026-09).
- `sec.fetch_memory_quarters()`/`fetch_logic_quarters()` → MU / NVDA, AMD,
  INTC com `end, days, inventory, cogs, filed`.

**Ligação (passo único, `FRONTS_ENABLED = True`):**
- `drivers.alocacao_chips`: sai `memory_inventory`; entram `tsmc_revenue`,
  `dio_memory`, `dio_logic` (`mode="front"`), pesos = `FRONT_SIGNALS`.
  `analyzer._front_signal` usa `supply_fronts.read_front` (z contra a própria
  história; dado vencido fica sem nota).
- `ranking._category_scores`: `front_score(sinais, cat.key)` no lugar da nota
  do vetor.
- `supply.build_supply`: fila = `demand_queue(z capex, z receita de chips)`.
- `supply_fronts`: `group_dio` alinha pelo trimestre civil mais próximo
  (NVIDIA fecha em jul/out, AMD/Intel em set/dez); `build_fronts(collected,
  today)` devolve os 3 cards do contrato da T32. Ao vivo: Memória 141,5 dias
  (normal 121–160), Chips 121,1 (98–124), Demanda +50,9% a/a (17–42).
- `backfill`: corte das frentes pela publicação (`released` da TSMC, `filed`
  da SEC); `MODEL_VERSION` inclui `FRONT_SIGNALS` e `EXPOSURE`.
- `series`: `MODEL_VERSIONS` = `t30-2026-11-05` em `supply.queue`,
  `driver.alocacao_chips`, `iph`, `iph_br`, `cat.`; 30 séries `price.*`
  (grupo "Preços na loja").

**T31 (RAM 44.268,87 US$/kg, +443,5% em 12 m):** não é erro de conta. SH6
854232 é chip de memória solto (muito leve). 2026-08: US$ 452,1 mi ÷ 10.213 kg
= 44.268,87; 2025-08: US$ 110,2 mi ÷ 13.532 kg = 8.145,55. O valor importado
quadruplicou com o peso caindo 25% — alta real do preço da memória somada à
troca de mix. Sugestão para o Frontend: rotular "US$/kg de chip de memória".

**fontes.md:** TSMC (TWSE + MOPS), SEC trimestral, KaBuM (regra do preço
cheio, limites, K9: termos e robots lidos em 05/11/2026, reler até
03/02/2027); rejeitadas com motivo: RI da TSMC, MOPS antigo, DART,
data.go.kr, Mercado Livre, Zoom/Buscapé, Amazon, Pichau, Terabyte,
Samsung/Dell/Lenovo.

**Testes:** `pytest tests/ -q` → 335 passed, 10 failed — todos fixam o modelo
antigo (sinal `memory_inventory`, estoque na fila, `MODEL_VERSIONS` vazio).
Substitutos em `docs/agentes/testes-pendentes/test_t30_ligacao.py`; os da T29
foram atualizados para a cesta nova. Pendentes: 70 passed.

## T33 — cesta por volume, alto em todas as categorias, marketplace (05/11/2026): **feito**

Busca: 28 pedidos (robots a cada rodada, 3–5 s, sem retentativa); 5 buscas
deram 308 (`ps5-pro`, `iphone`, `notebook`, `ryzen-5-4600g`, `fonte-500w`) e
não foram seguidas. Nenhum bloqueio.

| Categoria | Baixo | Médio | Alto |
|---|---|---|---|
| GPU | RTX 3050 2.011,65 / RX 6600 LE 3.176,46 | RTX 5060 ×2 3.736–3.760 / RX 7600 ×2 2.941–3.022 | RTX 5070 ×2 7.278–7.609 / RX 9070 XT 8.045,96 |
| RAM | DDR4 8 GB Fury Beast 952,74 | DDR5 16 GB 3.058,81 | DDR5 32 GB 6.117,64 |
| SSD | A400 240 GB 517,64 | NV3 1 TB 1.529,40 | NV3 2 TB 2.705,87 |
| CPU | Ryzen 5 5500 1.119,18 | i5-14400F 1.647,04 | Ryzen 7 7700 3.058,81 |
| Placa-mãe | A520M-A PRO 584 | B650 ×2 1.099–1.622 | B850 2.088,78 |
| Fonte | 650 W Bronze 388,88 | 750 W Gold 844,43 | 1000 W Gold UD1000GM 1.111,10 |
| Monitor | 24" 120 Hz 777,77 | 27" QHD 180 Hz 1.999,99 | 27" QHD 240 Hz 2.222,22 |
| Console | Switch OLED 2.699 | Switch 2 4.499 | PS5 com leitor 1 TB 5.697,85 |
| Celular (mkt) | Galaxy A07 1.081,90 (WebContinental) | A57 2.110 (Magalu) | S25 FE 256 GB 4.199 (Magalu) |
| Notebook (mkt) | IdeaPad Slim 3 R3 3.399 (LENOVO) | Vivobook Go R5 16 GB 4.299 (Magalu) | Nitro V15 R7 RTX 4050 7.999 (Acer) |

37 URLs. Código: `prices.py` (cesta, faixas, `NO_HIGH_BAND`/`OUT_OF_PRICE_TAB`
vazios, `screen_listing(..., seller)`, oferta com `marketplace`/`seller`, aviso
`marketplace` na faixa); `kabum.py` (`seller_expected`, `marketplace` na linha);
`kabum_basket.json` v5 (v4 salva no scratchpad). Mais baratos levantados e não
trocados: fonte 500 W Bronze ~233 (só marketplace), monitor 21,5" ~303–400 (só
marketplace, sem avaliações), H610 566,66 (KaBuM!, 0 avaliações), i3-12100F
767 (só marketplace). Testes: tests/ 335 passed / 10 failed (as mesmas da
T30); pendentes 72 passed.

## T33c/T33b — faixa exibida sem sobreposição + revisão de médio e alto (05/11/2026): **feito**

- `prices.display_range(cat, faixa)`: o `range_brl` da tela usa o máximo do
  nível limitado ao mínimo do nível de cima; a curadoria por item continua.
  Só a GPU sobrepunha: baixo exibido agora 1.500–2.500 (RX 6600 segue na
  curadoria até 4.150). `validate_basket` acusa sobreposição exibida.
- Revisão por volume (avaliações na KaBuM!, 12 pedidos, 3 buscas com 308 não
  seguidas): fonte médio Be Quiet 750 W (0 aval.) → Husky Sledger 750 W Gold
  777,67 (74); monitor médio ASRock Phantom (15) → Samsung Odyssey G5 27" QHD
  165 Hz 1.777,77 (87); monitor alto Rise Mode 240 Hz (47) → ASUS TUF 27" QHD
  210 Hz 2.352,94 (348); CPU alto Ryzen 7 7700 (fora da lista) → Ryzen 7 5700X
  2.153,66 (1.172); placa-mãe alto ASUS Prime B850 (1) → MSI B850 Tomahawk Max
  2.666,66 (19). Mantidos: RAM, SSD, GPU (decisão do usuário), B650, console,
  celular e notebook. Faixas: CPU médio 1.400–2.100 / alto 2.110–2.800;
  monitor médio 1.100–2.300 / alto 2.310–3.050; fonte médio 600–990.
- Testes: tests/ 335 passed / 10 failed (as mesmas da T30); pendentes 74 passed.

## T35 — cesta por modelo, 1 busca por modelo (05/11/2026): **feito, com pendências**

K5 trocada com aprovação do usuário (via Coordenador): a coleta agora é
`GET /busca/<termo>` limpo, sem "?" nem ordenação. Teto de 40/dia liberado
só nesta rodada.

- **Cesta** (`domain.prices.BASKET`, `BASKET_VERSION = "t35-2026-11-05"`):
  110 modelos, de 3 a 5 por faixa, cada um com termo, obrigatórios e
  exclusões. O nome precisa começar pelo tipo do produto (tira tampa,
  leitor, PC montado, "kit upgrade"). A chave não leva a faixa, para o
  modelo mudar de nível sem perder o histórico. `kabum_basket.json`
  saiu de uso e foi removido. As cópias v4–v6 estavam no rascunho da sessão, que foi limpo em 06/11, e não existem mais.
- **Conta**: o anúncio é válido se está disponível, é da KaBuM! (o
  marketplace entra só sem KaBuM! válida), passa no K14b e fica na faixa do
  nível com 25% de folga. Anormal (1,5× acima ou abaixo da mediana dos
  outros) sai. O modelo vale a mediana do cheio, com até 3 referências; a
  faixa é a média dos modelos, com variação pareada por modelo
  (`model_history`).
- **Cache**: `get_or_fetch(..., version=)` trata outra `cache_version` como
  vencida, e o domínio ignora o payload de outra cesta.
- **Coleta**: 1 robots + 114 buscas (534 s), sem bloqueio. 14 buscas
  redirecionadas e não seguidas. Repescagem com termo curto: 1 robots + 9
  buscas; 8 lidas, a Arc B580 redirecionou de novo, e a busca
  `crucial-p3-plus-1tb` veio 200 sem `catalogServer.data`. A coleta parou ali
  (regra do layout), e 12 modelos ficaram `not_run`. Gravado em
  `data/cache.db` com o prazo da loja.
- **Remanejados pela mediana medida**: NV3 500 GB e i5-12400F foram para o
  médio; B550 e 750 W Bronze para o baixo; notebook R5/8 GB para o médio e
  i5/16 GB para o alto. Saíram a RTX 5070 Ti e os notebooks RTX 4050/4060
  (acima de R$ 10 mil) e a Arc B580.
- **Resultado**: 92 de 110 modelos com preço, e as 10 categorias publicadas.
  A RX 6600 fica sem preço: os 60 primeiros resultados da busca são só PC
  montado. Por isso o baixo da GPU não tem AMD na visão por marca.
- **Pendências**:
  - 12 modelos `not_run`: SSD P3 Plus 1/2 TB e SN850X; Ryzen 5 5500, 5600 e
    5600G; Switch, Switch 2, Series X e ROG Ally; S25 e iPhone 15.
  - Saber como a busca sem resultado aparece no `__NEXT_DATA__`, para ela não
    parar a coleta.
  - Dividir a cesta em vários dias, por causa da K3.

## T35c — busca vazia, modelos faltantes e AMD no baixo (06/11/2026): **feito, com pendências**

- **Busca 200 sem `catalogServer.data`**: agora é `status: "empty"`, o
  modelo fica sem anúncio e a coleta segue. Três vazias seguidas param a
  coleta (layout mudou?). Página sem `__NEXT_DATA__` continua parando.
- **Coleta em vigor**: o domínio aceita a coleta `ok` de até 8 dias
  (`MAX_COLLECTION_AGE_DAYS`), porque a loja coleta 1 vez por semana e a cesta
  foi completada em dois dias. `stale` continua sem preço.
- **Pedidos (06/11)**: 1 robots + 15 buscas, sem bloqueio. Lidas: SN850X,
  Ryzen 5 5500, Switch 2, mais 2 testes da RX 6600 (`radeon-rx-6600` e
  `rx-6600-8gb`, só PC montado). Vazias: P3 Plus 1 TB e 2 TB. Redirecionadas
  e não seguidas: Ryzen 5 5600 e 5600G, Switch, Series X, ROG Ally, S25,
  iPhone 15 e `rx-580`.
- **Resultado**: 94 de 110 modelos com preço.
- **AMD no baixo**: nenhum termo traz RX 6600 avulsa. O candidato mais
  próximo é descer a RX 7600 (mediana de R$ 2.941, 3 anúncios da KaBuM!)
  para o baixo, mas isso desfaz a escada da T33 e deixa o médio sem AMD.
  Fica para decisão do usuário.

## T35d — faixa exibida observada, GPU baixo nova e iPhone (06/11/2026): **feito, com pendências**

- **Faixa exibida**: `range_brl` agora vai da menor à maior mediana dos modelos
  com preço no dia (`observed_range`), e a média sempre fica dentro. Sem
  modelo com preço, `range_brl` é `null`. A faixa fixa virou
  `curation_range`, usada só na curadoria e no filtro do anúncio, e o
  `validate_basket` não confere mais sobreposição.
- **GPU baixo**: GTX 1650, RX 6500 XT, RTX 3050 e Arc A380. A RTX 3060 e a Arc
  B570 subiram para o médio. Saíram a RX 6600 (só PC montado) e a RTX 4060,
  para o médio ficar com 5 modelos.
- **iPhone**: entrou o iPhone 16 de 128 GB no celular alto, no lugar do
  iPhone 15 (que redirecionava). O nome do celular agora pode começar por
  "iPhone". O preço é R$ 5.332,22 cheio, por marketplace (Magalu): a KaBuM!
  não vende.
- **Pedidos**: GPU com 1 robots + 3 buscas. A GTX 1650 redirecionou; a Arc A380
  trouxe 6 itens, nenhum avulso. iPhone com 1 robots + 3 buscas
  (`iphone-16-128gb` lido; `apple-iphone-16-128gb` igual; `iphone-17-128gb`
  sem anúncio que case).
- **Resultado**: 95 de 111 modelos com preço. A média do GPU baixo é
  R$ 1.819,15 (RTX 3050 R$ 2.222,21 e RX 6500 XT R$ 1.416,10), na faixa
  exibida de 1.416 a 2.222.
- **Pendência**: GTX 1650 e Arc A380 sem preço.

## T42 — Comtrade mensal: cauda de 3 meses, paralela e com meses fechados no cache (10/11/2026): **feito**

1ª coleta de 10/11 levou 9 min 05 s; `comtrade_monthly.console` segurou 6 min
porque `_monthly_batch` pedia 16 meses em fila a 18,2 s por pedido.

### O que mudou (`app/providers/comtrade.py`, `app/http.py`)

- `_TAIL_MONTHS = 3`: a cada ciclo só a cauda é pedida — 2 meses de defasagem
  de publicação + 1 de revisão. `_MONTHS_BACK` continua 16: define a janela da
  série devolvida, não o que se pede à API.
- Meses fechados vêm de `_previous_months(category_key)`, que lê
  `cache.peek("comtrade_monthly.<categoria>")` — inclusive entrada vencida,
  porque mês fechado não muda. A persistência é a própria `cache.db` que o
  coletor já grava; não precisou de API nova em `app/cache.py`. Só os meses
  anteriores à cauda são aproveitados; os da cauda são sempre re-pedidos.
  Mês fechado que falhou não fica em lugar nenhum, então é tentado de novo.
- Lote em paralelo: `asyncio.gather` sobre os períodos pedidos, com
  `_CONCURRENCY = 3` no semáforo `comtrade` (antes 1). Mesmo endpoint, mesmos
  parâmetros, mesmo User-Agent; sem `Origin`/`Referer`.
- Memo mantido por (último mês, SH6, períodos pedidos); falha não é
  memorizada.
- `http.limiter` passou a recriar o semáforo quando o event loop muda:
  `asyncio.Semaphore` preso a um loop fechado levanta `RuntimeError` ao ser
  disputado no loop seguinte (um `asyncio.run` por teste). Sem isso, 3 vagas
  com 16 pedidos travariam a suíte.

### Verificação

- `python -m pytest tests/test_comtrade_monthly.py tests/test_http_defenses.py
  tests/test_http_challenge.py -q` → 59 passed. Suíte inteira: **325 passed,
  19 failed, 1 deselected**; as 19 falhas são as mesmas de antes da mudança
  (Modelo/Frontend em andamento, conferidas com `git stash`).
- Restart simulado, duas execuções com `cache.db` em `/tmp`: processo frio
  **16 pedidos** (13 fechados + 3 da cauda); processo novo com o `cache.db`
  gravado **3 pedidos** (`202608`, `202609`, `202610`) e série **idêntica**
  (14 meses, 2025-07 → 2026-08; 2026-09/10 vazios por não publicados).
- Lote com a latência real medida (18,2 s por pedido, rede falsa): **18,2 s**
  para os 3 pedidos da cauda; em fila seriam 54,6 s.
- **Risco:** 3 pedidos simultâneos ao preview não foram testados ao vivo
  (cota do Comtrade). Se aparecer 429 recorrente, baixar `_CONCURRENCY` para 2
  — o disjuntor de cota (403) continua valendo.
- **Pendência de outro dono:** `tests/test_collector_comtrade.py::test_collect_com_fetchers_simulados_entrega_10_chaves`
  trava a suíte (não termina em 90 s) **também no código anterior à mudança**;
  reproduzido com `git stash`. Precisa da QA.

## T42b, T42c, T43b e T45 — 10/11/2026

**Causa dos 79 pedidos (teste 12:06).** O memo do lote mensal tinha os
períodos pedidos na chave: categorias com meses fechados diferentes no cache
viravam lotes separados. E a falha não era guardada, então cada 429 era
repetido pela categoria seguinte (com o retry do http.py, 2 pedidos por
período). A série anual somava mais 16 pedidos (4 anos × 4 SH).

**T42b — mensal.** `_CONCURRENCY = 1`. O ciclo (`_MonthlyCycle`, em
`_monthly_memo`) guarda por período o resultado bom ou a falha por
`_CYCLE_S` = 15 min: cada período sai no máximo uma vez por ciclo para as 9
categorias. 403, 429 ou disjuntor aberto param o ciclo todo. 429 abre o
disjuntor `comtrade` pelo `Retry-After` (piso 5 s, padrão 60 s, teto 6 h); o
http.py já espera o `Retry-After` (até 30 s) e repete uma vez antes disso.
Com cache quente: 3 pedidos no total (teste
`test_cache_quente_nove_categorias_fazem_tres_pedidos`).

**T42c — anual.** `fetch_flow` lê os anos de `cache.peek("comtrade.<key>")`
(mesmo vencido, mesmo SH e reporter) e só pede o último ano completo
(`_TAIL_YEARS = 1`) e os anos que faltam. Ano da cauda que volta vazio mantém
o valor anterior. Com cache: 4 pedidos por ciclo em vez de 16. O payload
ganhou `reporter`. Os SH não foram juntados numa chamada só porque isso só
foi confirmado ao vivo no endpoint mensal.

**T43b — http.py.** `get_json/get_text/post_json(..., provider=)`: usa
`settings.http_timeout_for(provider)` quando o pedido não traz `timeout`, e
não repete tempo esgotado (`TimeoutError` do teto total ou
`httpx.TimeoutException` de fase) quando `retries_on_timeout_for` é falso.
`comtrade._get` passa `provider="comtrade"`.

**T45 — KaBuM (medido, não alterado).** 112 pedidos = 1 robots + 111 buscas,
uma por modelo da cesta T35 (desenho aprovado: busca limpa por modelo). Cada
pedido custa a pausa de 3–5 s (média 4 s) mais ~0,3 s de resposta: 8 min, e
~93% é a pausa obrigatória da regra K3. Paralelismo fere a K3 ("um por vez")
e não foi feito. Opções para o usuário decidir:
- A. Pausa fixa de 3 s (dentro da K3): ~6 min (−25%).
- B. Cesta em rodízio de 3 dias, ~37 buscas por dia (cabe no teto K3 de
  40/dia): ~2,7 min por dia; cada modelo renovado a cada 3 dias, dentro da
  validade de 8 dias. Exige TTL diário no collector (Backend) e mesclar a
  coleta nova com a anterior no provider (Dados).
- C. 2 buscas simultâneas: ~4 min, mas muda a K3 (precisa do usuário e da
  Segurança).
- Em qualquer caso, a coleta da loja não deveria segurar o ciclo (Backend,
  coleta em segundo plano da T43).
Ponto aberto: a rodada semanal inteira (112 pedidos) já passa do teto de
40/dia da K3; a liberação foi só para 05/11.

**Incidente — coleta real durante os testes.** O `.env` tem
`DSH_ENABLE_KABUM=true`, e
`tests/test_collector_comtrade.py::test_collect_com_fetchers_simulados_entrega_10_chaves`
roda `collector.collect()` sem desligar a KaBuM nem a TWSE. É essa a causa do
"trava a suíte" anotado na T42: o teste faz a coleta real da loja (pausa de
3–5 s por busca). Hoje, rodando a suíte, isso gerou buscas reais à KaBuM (três
execuções, duas sobrepostas, interrompidas; estimativa de até ~100 buscas,
sem contagem exata) e pedidos à TWSE. Desde então rodo os testes com
`DSH_ENABLE_KABUM=false DSH_ENABLE_TSMC=false`. Correção fica com a QA:
desligar as lojas nesse teste (ou num conftest).

**Testes.** `docs/agentes/testes-pendentes/test_comtrade_t42b.py` (16, passam).
`tests/` com as lojas desligadas: 325 passam, 20 falham; só
`test_comtrade_monthly.py::test_falha_total_nao_fica_no_memo` é desta tarefa
(a regra mudou de propósito; o teste novo `test_falha_total_fica_no_ciclo_e_vence_depois`
o substitui). As outras 19 (api_security, backfill, queue_model, supply,
ui_contract) estão fora destes arquivos. Pendentes: 103 passam.
