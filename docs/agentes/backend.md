# Relatório — Backend

## T43 — snapshot do cache no start e timeout por provider (2026-11-10)

Arquivos: `app/main.py`, `app/services/collector.py`, `app/config.py`,
`app/schemas.py`, `.env.example`.

### Snapshot de partida sem rede (feito)

- `collector.build_cached_snapshot()` lê `cache.peek()` de cada job de
  `_tasks()` — sem rede — e monta o `Snapshot` no `lifespan`, logo após
  `cache.load`. `/api/snapshot` passa a responder na hora, mesmo com o cache
  vencido; a coleta em background substitui o objeto quando termina.
- Marcação: campo aditivo `stale: bool` e `stale_reason: str | None` no
  `Snapshot`; `generated_at` recebe o `fetched_at` mais novo do cache (idade do
  dado, não a hora da leitura). `/api/health` devolve `status: "stale"` e
  `"stale": true`, mantendo HTTP 200.
- Fonte com valor fora do TTL entra como `status="stale"` (nota "valor do
  cache em disco; fora do prazo"), então `degraded` mostra o que está velho.
- Piso: só monta se ao menos 50% das fontes (`CACHE_SNAPSHOT_MIN_SHARE`) têm
  valor no cache; abaixo disso o índice sairia de quase nada e vale mais
  esperar a coleta. Sem cache, nada muda: `/api/snapshot` espera a 1ª coleta e
  devolve 503 se ela falhar (tela de carregamento preservada).
- Não grava histórico, preço de loja nem cache: é só leitura.

### Timeout por provider (parcial — precisa de `app/http.py`)

- `settings.http_timeout_providers` (`DSH_HTTP_TIMEOUT_PROVIDERS`, padrão
  `comtrade=60`) e `settings.http_timeout_for(provider)`;
  `settings.http_no_retry_timeout` (`DSH_HTTP_NO_RETRY_TIMEOUT`, padrão
  `comtrade`) e `settings.retries_on_timeout_for(provider)`. Valor inválido
  falha no start.
- Falta o consumo: `http._request` ainda usa `settings.http_timeout` fixo e
  repete em `TimeoutError` para todo provider. Pedido ao Dados em
  `docs/agentes/dados.md`/retorno ao Coordenador.

### Medição (cache de 06/11, 59 entradas, `DSH_AUTOREFRESH=false`)

- `GET /api/snapshot`: 200 em 0,042 s, `stale: true`, `generated_at`
  2026-11-06T18:55:55Z, 58 fontes em `degraded`.
- Cache fresco: 200 em 0,040 s; `/api/health` `status: "stale"`.
- Coleta simulada depois do start: snapshot novo com `stale: false` e
  `/api/health` `status: "ok"`.

### Testes

- `python -m pytest tests/ -q`: 326 passaram, 19 falharam — todas as 19 já
  falham no HEAD (`git worktree` de 291be2d): fila/`model_breaks` (Modelo) e
  contrato visual (Frontend). Nenhuma em arquivo desta função.
- `tests/test_api_security.py -k "snapshot or refresh or coleta"`: 9 passaram,
  1 falha (a de `model_breaks`, já vermelha no HEAD).

### Pedidos

- **Dados** (`app/http.py`): usar `settings.http_timeout_for(provider)` no
  `_total_timeout`/`build_client` e não repetir `TimeoutError` quando
  `settings.retries_on_timeout_for(provider)` for falso; `comtrade._get`
  precisa informar `provider="comtrade"` (ou `timeout=60`).
- **Frontend**: mostrar aviso quando `snapshot.stale` (ex.: "dados de
  <generated_at>, coleta em andamento") em vez de só a data.

## T10 — `/api/refresh` e achados S2, S6, S7, S8 (2026-11-04)

Arquivos: `app/main.py`, `app/config.py`, `app/schemas.py`, `.env.example`.

### S2 — coleta forçada sem limite (corrigido)

- **Single-flight:** `_refresh()` guarda a coleta em andamento numa `Task`
  (`_inflight`). Quem chega durante ela (loop de 15 min, GET, POST) espera a
  mesma em vez de enfileirar outra. O `asyncio.shield` impede que um cliente que
  desconecta cancele a coleta dos outros. O `_snapshot_lock` saiu.
- **Intervalo mínimo:** `POST /api/refresh` aceita uma coleta forçada a cada
  `DSH_REFRESH_MIN_INTERVAL_SECONDS` (padrão 60 s, contado do início da última
  forçada). Antes disso: `429` com `Retry-After`. Se já há coleta em andamento,
  o POST espera por ela e devolve `200` (não conta como nova forçada).
- **GET sem efeito colateral:** `GET /api/snapshot` não aceita mais `force`
  (o parâmetro é ignorado). Só coleta se ainda não houver snapshot.
- **CSRF:** o POST exige `X-DSH-Refresh: 1`; sem ele, `403`. Não há CORS, então
  site de terceiros não manda esse header.
- Coleta que falha sem snapshot anterior agora vira `503` com mensagem curta, em
  vez de `500`.

### S6 — headers de segurança (corrigido)

Middleware `security_headers` em todas as respostas:

- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`
  (a política pedida pelo Frontend). Fica fora de `/docs` e `/redoc`, porque o
  Swagger carrega JS de CDN.
- `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`.

**Ponto aberto (eval):** sem `'unsafe-eval'`. Os quatro usos de `Function` no
`plotly-2.35.2.min.js` são fallbacks: dois `new Function("return this")` dentro
de `try/catch` após checar `globalThis`, um polyfill de `Function.prototype.bind`
e uma detecção de generator em `try/catch`. Não devem rodar num navegador atual.
A QA vai abrir a aba Gráficos com a CSP ativa. Se o console acusar eval, a
decisão volta ao Coordenador. Se o download de imagem do Plotly falhar, o
candidato é incluir `blob:` em `img-src`.

### S7 — DNS rebinding (corrigido)

`TrustedHostMiddleware` é o middleware mais externo e recusa com `400` quem
mandar um `Host` fora da lista. A lista vem de `DSH_ALLOWED_HOSTS` (padrão
`127.0.0.1,localhost`); o `DSH_HOST` entra sozinho quando não é curinga. Com
`DSH_HOST=0.0.0.0`, é preciso incluir o IP/nome da máquina.

### S8 — corpo de resposta de terceiros (corrigido no Backend)

- `schemas.public_error()` troca o trecho entre aspas no fim da mensagem (o
  `snippet!r` que `http.py` anexa) por `[corpo da resposta omitido]`, junta
  espaços e corta em 200 caracteres. Aplicado no validador de
  `SourceInfo.error` (snapshot e `/api/sources`) e em `/api/cache`.
- `/api/health` `last_error` agora traz só o tipo da exceção; o texto completo
  fica no log.
- A mensagem original continua no log e no cache interno. Tirar o snippet na
  origem (`http.py`) é com o Dados, se quiserem.

### Para a QA testar

Use `base_url="http://127.0.0.1"` no cliente de teste: o `testserver` padrão do
`TestClient` agora toma `400` do TrustedHost.

1. `POST /api/refresh` sem header, ou com valor ≠ `1` → `403`.
2. Dois POST com header separados por menos de 60 s (sem coleta em andamento) → o
   segundo dá `429` com `Retry-After` > 0. Com `DSH_REFRESH_MIN_INTERVAL_SECONDS=0`
   → `200`.
3. Single-flight: N POST simultâneos com `collector.collect_and_build` simulado
   (com `sleep`) → uma única chamada ao coletor e todos `200`.
4. `Host: evil.example` em qualquer rota → `400`; `Host: localhost:8000` → ok.
5. `GET /api/snapshot?force=true` com snapshot existente → não chama o coletor.
6. Headers CSP, nosniff e Referrer-Policy presentes em `/` e `/api/*`; CSP
   ausente em `/docs`.
7. `public_error("resposta nao-JSON de https://x: '<html>…'")` não contém
   `<html>`; mensagem > 200 caracteres é cortada.
8. Coleta simulada que levanta exceção sem snapshot → `GET /api/snapshot` dá
   `503` e `/api/health.last_error` não contém o texto da exceção.

Testes: `.venv/bin/python -m pytest tests/ -q` → 206 passed, 4 xfailed. Fiz um
teste de fumaça manual com `httpx.ASGITransport` cobrindo 1–4 e 6; não
acrescentei esse teste à suíte porque `tests/` é da QA.

## T11 — importação mensal pelo UN Comtrade no lugar do Comex Stat (2026-11-04)

Decisão: o Comex Stat segue **rejeitado** (T05 do Dados: o WAF devolve 429 a
todo POST). `enable_comexstat=False` continua, e o código dele fica no lugar. A
importação mensal por SH6 passa a vir de
`comtrade.fetch_monthly_imports`, ligada por `enable_comtrade_monthly=True`
(`DSH_ENABLE_COMTRADE_MONTHLY`, documentada no `.env.example`).

Arquivos: `app/services/collector.py`, `app/config.py`, `.env.example`.

- `_tasks`: um job `comtrade_monthly.<cat.key>` por SH6 distinto (9 jobs; o
  provider junta todos os SH6 num pedido só), com TTL `ttl_monthly`.
- `collect`: depois da coleta, `_share_by_sh6` faz a categoria sem coleta
  própria herdar a de outra com o mesmo SH6. Hoje, `motherboard` herda de `gpu`
  (847330). Resultado: as 10 categorias ficam em `comtrade_monthly.*`. A mesma
  função (`_share_by_sh6`/`_one_per_sh6`) atende o Comex Stat, se for religado.
- Rótulo: o `label`/`provider` do `Fetched` vem do provider, que é do Dados
  ("UN Comtrade — importação mensal de …", provider "United Nations Comtrade
  (preview público), dado da SECEX"). O rótulo "UN Comtrade (dado SECEX)" na
  tela de ranking é do Modelo (`ranking._imports`). O Backend não sobrescreve
  rótulo de outra função.
- (Resolvido pelo Modelo na T11b: `ranking._imports` lê `comtrade_monthly.*` e usa o Comex Stat como alternativa.) Antes, `app/domain/ranking.py:74` lia
  `comexstat.{cat.key}`. Enquanto o Modelo não trocar para
  `comtrade_monthly.{cat.key}`, a coluna de importação segue vazia.

Para a QA testar:
1. `_tasks()` com padrão: 9 chaves `comtrade_monthly.*` (uma por SH6) e nenhuma
   `comexstat.*`; com `enable_comtrade_monthly=False`: nenhuma.
2. `_share_by_sh6(collected, "comtrade_monthly")` com `gpu` ok → `motherboard`
   recebe o mesmo `Fetched`; com `gpu` `unavailable` → `motherboard` não é
   criado (ou fica como veio).
3. `collect()` com fetchers simulados → 10 chaves `comtrade_monthly.*`.

## T10b — `/api/methodology`, log das notícias e marcação da fila antiga (2026-11-04)

Arquivos: `app/main.py`, `app/services/history.py`, `app/services/news.py`.

- `/api/methodology.queue` agora é `supply.QUEUE_METHODOLOGY` (fórmula em
  z-score), com o campo `model_version` acrescentado. A fórmula fixa com "/10" e o
  `inventory_scale` saíram (o `main.py` não importa mais `INVENTORY_SCALE`; o
  Modelo pode apagar a constante).
- `/api/methodology` expõe `fx_passthrough` (agora lido de
  `analyzer.FX_PASSTHROUGH`), `fx_passthrough_days` (90) e `fx_horizon_days` (30).
- `services/news.py`: o log do digest conta também as manchetes agrupadas por
  entidade (`merged_by_keys`) e quantas dessas cruzam idiomas (`cross_language`).

### Pontos antigos de `supply.queue` (os 42 em 100,0 de 03–04/11)

**Não foram apagados.** A marcação é esta:

- `history.QUEUE_MODEL_VERSION = "zscore-2026-11-04"`. Na primeira gravação de
  snapshot com a versão nova, `record_snapshot` grava no `meta`
  `queue_model` = versão e `queue_model_since` = instante desse snapshot.
- `/api/history` devolve, em cada série, `model_since`: para `supply.queue`, o
  instante em que a conta atual começou; para as outras, `null`. Pontos com
  `t < model_since` são da conta antiga. O Frontend pode usar isso para
  esmaecê-los ou cortar a linha. O Backend não mexe nisso.
- Trocar a conta de novo = mudar `QUEUE_MODEL_VERSION`; o marco anda sozinho.

Opções para o usuário decidir (nenhuma aplicada):
(a) manter e sinalizar, que é o estado atual;
(b) apagar só os pontos antigos:
    `DELETE FROM metric WHERE key='supply.queue' AND ts < (SELECT value FROM meta WHERE key='queue_model_since')`;
(c) filtrar em `/api/history`, escondendo da resposta os pontos antes de
    `model_since` sem apagar do banco.

Para a QA testar:
1. Banco temporário: dois `record_snapshot` com fila → `model_breaks()` devolve
   o `ts` do primeiro; mudar `QUEUE_MODEL_VERSION` (monkeypatch) e gravar de
   novo → o marco passa para o novo `ts`.
2. `/api/history?series=supply.queue,iph` → `model_since` preenchido só na fila.
3. `/api/methodology` → `queue.formula` sem "/10", `queue.model_version`,
   `fx_passthrough_days == 90`, `fx_horizon_days == 30`.

Testes: `.venv/bin/python -m pytest tests/ -q` → 206 passed, 4 xfailed. Fumaça
manual com `httpx.ASGITransport` e banco temporário confirmou 1–3.

### T10b, complemento: `CategoryImport.source`

`app/schemas.py`: o `CategoryImport` ganhou `source: str | None = None`, que o
`ranking._imports` preenche com o rótulo da fonte usada. A docstring agora diz
"UN Comtrade/SECEX ou Comex Stat". QA: no snapshot, `ranking[].imports.source`
vem como "UN Comtrade (dado SECEX)" quando a coleta `comtrade_monthly` está ok.

## T09c — `defusedxml` nas dependências (2026-11-04)

O usuário passou ao Backend a posse de `requirements.txt` e `requirements-dev.txt`.
Acrescentei `defusedxml>=0.7.1` ao `requirements.txt` (achado S9) e instalei no
`.venv` (`defusedxml 0.7.1`). Conferido: `news_rss._defused_fromstring is not
None`, ou seja, o parser de RSS usa o defusedxml em vez do ElementTree puro.
Testes: `.venv/bin/python -m pytest tests/ -q` → 344 passed.

## T22b — cache persistido em SQLite (2026-11-04)

Arquivos: `app/config.py`, `app/main.py`, `.env.example`. Usa
`TTLCache.save/load` da T22a (Dados).

- `config.cache_path = "data/cache.db"` (`DSH_CACHE_PATH`, no `.env.example`).
  A propriedade `settings.cache_file` resolve o caminho relativo à raiz do
  projeto, como o `history_path`.
- `lifespan`: `cache.load` antes de disparar a 1ª coleta, com log de quantas
  entradas vieram. Ao desligar, `cache.save` de novo.
- `_collect`: `cache.save` depois do histórico e antes de `progress.ready()`,
  num try/except que só registra no log.
- Por que salvar também ao desligar: o `/api/health` fica 200 assim que o
  snapshot existe, e a gravação do histórico vem depois. Fechar o app nesse
  intervalo perdia o cache da 1ª coleta, e o 1º teste caiu exatamente nisso.

### Prova (porta 8765, cache e histórico no scratchpad)

| Start | Cache carregado | Pedidos HTTP | Tempo até o cache gravado |
| --- | --- | --- | --- |
| 1º (vazio) | 0 | 262 | 62 s |
| 2º | 42 | 160, **todos ao Comtrade (403)** | 78 s |
| 3º, Comtrade desligado | 42 | **0** | **3 s** |

Todas as fontes no prazo foram reaproveitadas. O que ainda vai à rede no 2º
start são as 13 chaves do Comtrade (`comtrade.*` e `comtrade_monthly.*`), que
hoje respondem **403** a todo pedido. Falha não entra no cache (não há valor bom
para guardar), então cada start tenta de novo, e as retentativas somam cerca de
75 s. Isso é com o Dados: o Comtrade passou a recusar esta rede (o mensal da
T11 também está sem dados), e talvez valha um cache negativo curto para fonte
em 403.

## T22f — validação do `cache_path` (achado C1 b/c da Segurança, 2026-11-04)

Arquivos: `app/config.py`, `.env.example`.

- `Settings` ganhou o `model_validator` `_cache_path_is_own_db`, que recusa
  (b) um `cache_file` que, depois de `resolve()`, seja o mesmo arquivo do novo
  `history_file` (pega `./data/../data/history.db` e link simbólico) e (c) um
  `cache_path` sem sufixo `.db` (sem diferenciar maiúsculas).
- `cache_file` e `history_file` usam o mesmo `_resolve` (relativo à raiz do
  projeto).
- **Escolha: erro na inicialização, não volta ao padrão.** Motivos: o operador
  vê o erro ao subir o app, em vez de um WARNING que passa despercebido; e o
  padrão `data/cache.db` também pode colidir, se alguém pôs
  `DSH_HISTORY_PATH=data/cache.db`. Voltar ao padrão em silêncio poderia
  recriar o problema que a validação evita.
- O `.env.example` explica as duas regras.

Conferido: padrão → ok; `data/history.db`, `./data/../data/history.db`, link
simbólico para o histórico, cache e histórico em `/tmp/x.db` → erro de
mesmo arquivo; `.env` → erro de sufixo; `cache.DB` → ok. Suíte: 345 passed.
O item (a) do C1 (só mover o arquivo quando o erro for de banco corrompido) é
do Dados.

## T12b — `blob:` na CSP (2026-11-05)

`app/main.py`: `img-src 'self' data: blob:`. Libera o download em PNG pelo menu
do Plotly (D2 da QA, §T03). Continua sem `'unsafe-eval'`, porque a QA
confirmou que o Plotly roda sem ele. Política completa:
`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`.

## T28a — regras K1, K2 e K7 da Segurança para a KaBuM (2026-11-05)

Ainda não existe provider da loja. O que segue são as regras prontas no
coletor e na configuração, que passam a valer assim que o Dados criar a fonte
com chaves `kabum.*`.

Arquivos: `app/services/collector.py`, `app/config.py`, `.env.example` e
`app/cache.py` (mínimo, ver abaixo).

- **K1, `force` não vale para a loja.** `collector.is_store(key)` reconhece
  `STORE_PREFIXES = ("kabum.",)`. No `_run`, a loja recebe sempre
  `force=False`. Assim, o botão "atualizar" e o `POST /api/refresh` não a
  refazem. O `GET /api/snapshot?force=true` já não força nada desde a T10.
- **K2, falha da loja guardada por 24 h e persistida.** A loja recebe
  `failure_ttl=STORE_FAILURE_TTL` (24 h) e TTL de sucesso de pelo menos
  `STORE_TTL` (24 h), mesmo que o job declare menos. Os prazos ficam fixos no
  código, sem variável de ambiente, para ninguém encurtá-los. A entrada de
  falha já vai para o `cache.db` pelo `save` (T22b), então reiniciar o app não
  volta a bater. As outras fontes continuam com `min(ttl, 30 min)`.
- **Mudança mínima em `app/cache.py`:** só o parâmetro opcional
  `failure_ttl: int | None = None` em `get_or_fetch`, que troca o
  `min(ttl, self.failure_ttl)` daquela chamada. Não mexi em `load`/`save` nem
  nos pontos da T22e (C1, C4–C7). Atenção para o Dados na T22e: o teto do C4
  (`max_ttl`) precisa ser de pelo menos 24 h, senão corta a falha da loja ao
  carregar.
- **K2, o que não cabe ao Backend:** "ou pelo `Retry-After` normalizado, o
  que for maior" e "sondar o `robots.txt` antes de qualquer produto quando o
  cache sumir" ficam no provider (Dados), porque o coletor não vê o
  `Retry-After`.
- **K7, contato no User-Agent.** `DSH_CONTACT` (vazio por padrão, presente
  sem valor no `.env.example`). Quando preenchido, o UA padrão passa a ser
  `datasearch-hardware/1.0 (+pesquisa de precos de hardware; contato: <contato>)`.
  Um `DSH_USER_AGENT` escrito à mão não é alterado. O contato precisa ser um
  e-mail ou uma URL http(s), sem espaços e com até 200 caracteres; fora disso,
  o app não sobe. Isso também barra CR/LF, que viraria injeção de header.
- **K7, a loja só liga com contato.** `DSH_ENABLE_KABUM` (padrão `false`) e
  `settings.kabum_enabled = enable_kabum and contact`. O job da loja em
  `_tasks` deve usar `settings.kabum_enabled`; eu o acrescento quando o
  provider existir.

Conferido manualmente: com `force=True`, só a fonte comum refez o pedido; a
falha da `kabum.gpu` ficou guardada por 24,0 h contra 0,02 h da comum, e
continuou em 24,0 h depois de `save`/`load`; o UA leva o contato;
`kabum_enabled` fica `False` sem contato; um contato com `\r\n` foi recusado.

## T28b — `model_since` por série (2026-11-05)

Arquivos: `app/services/history.py`, `app/main.py`.

- `history.model_versions()` monta o mapa série → versão da conta. A chave é
  o nome exato da série ou um prefixo terminado em `.` (`cat.` cobre
  `cat.gpu.pressure` etc.). A base tem só `supply.queue: QUEUE_MODEL_VERSION`.
  Por cima dela entra **`app.domain.series.MODEL_VERSIONS`**, se o Modelo a
  declarar; assim, quando a T24 entrar, o Modelo marca a troca sem precisar do
  Backend.
- `record_snapshot` → `_mark_models`: para cada versão cuja série aparece no
  snapshot, se a versão gravada no `meta` (`model.<série>`) for outra ou não
  existir, grava a nova e `model_since.<série>` = instante do snapshot. Nada é
  apagado.
- Série sem versão declarada não tem marco. Por isso nada aparece hoje em
  `iph`, `iph_br`, `driver.alocacao_chips` e `cat.*`: o marco nasce no 1º
  snapshot depois que o Modelo declarar a versão da T24.
- Migração: o `init_db` copia o marco da T10b (`queue_model` e
  `queue_model_since`) para o formato novo, sem perder o instante já gravado.
  As chaves antigas continuam no `meta`.
- `model_breaks()` devolve `{série ou prefixo: instante}`, e
  `model_since_for(key, breaks)` resolve uma série concreta: o nome exato
  ganha do prefixo mais longo.
- `/api/history` e **`/api/series`** (campo novo em cada item) devolvem
  `model_since`. `/api/methodology.queue.model_version` lê a versão efetiva.

Conferido: marco da T10b migrado (`2026-11-04T18:00:00Z`) e mantido com a
mesma versão; com `MODEL_VERSIONS` da T24 simulado, `supply.queue`,
`driver.alocacao_chips`, `iph`, `iph_br` e `cat.*` passam para o instante do
snapshot, enquanto `obs.gpu.ipca` e `driver.ormuz_helio` continuam `null`. Os
testes da T10b (`tests/test_api_security.py`) seguem verdes.

**Para o Modelo, quando implementar a T24:** em `app/domain/series.py`,
```python
MODEL_VERSIONS = {
    "supply.queue": "t24-AAAA-MM-DD",
    "driver.alocacao_chips": "t24-AAAA-MM-DD",
    "iph": "t24-AAAA-MM-DD",
    "iph_br": "t24-AAAA-MM-DD",
    "cat.": "t24-AAAA-MM-DD",
}
```
(com a data da troca; só muda a string quando a conta mudar de novo).

## T28c — contrato da API de preços (proposta, 2026-11-05; não implementado)

Base: `modelo.md` §T24d–§T24g (cesta aprovada, 38 URLs) e as regras K14–K18
da Segurança. É só o contrato, para o Frontend montar o esqueleto da sub-aba
"Por marca".

### Onde

- O dado é montado no ciclo de coleta, como a fila: `Snapshot.prices:
  PricesView | None`, com schemas em `app/schemas.py`.
- `GET /api/prices` devolve só esse pedaço, como o `/api/supply`. Sem
  parâmetros, porque não há nada a validar. Responde `503` enquanto não houver
  snapshot, igual às outras rotas.
- Fonte desligada (sem `DSH_CONTACT` ou `DSH_ENABLE_KABUM=false`) responde
  `200` com `source.status = "disabled"` e as faixas vazias, para o painel
  explicar por quê em vez de quebrar.
- Histórico em `/api/history` (o Modelo precisa acrescentar as chaves ao
  catálogo `SERIES_BY_KEY`, tipo `observed`):
  - `price.<categoria>.<faixa>`: preço à vista da faixa;
  - `price.gpu.<faixa>.<marca>`, com `marca` ∈ `nvidia`, `amd`;
  - `price.gpu.<faixa>.diff_amd_pct`.

### JSON

Valores ilustrativos. Dinheiro em reais, como número com até 2 casas; `null`
quando não há valor (nunca 0).

```json
{
  "generated_at": "2026-11-05T12:00:00Z",
  "source": {
    "key": "kabum",
    "label": "Preço na KaBuM (à vista)",
    "note": "Uma loja, 38 anúncios acompanhados por dia. Não é média de mercado.",
    "status": "ok",
    "status_reason": null,
    "as_of": "2026-11-05T06:10:00Z",
    "listings_tracked": 38,
    "listings_valid": 33
  },
  "tiers": [
    {"key": "baixo", "label": "Baixo"},
    {"key": "medio", "label": "Médio"},
    {"key": "alto", "label": "Alto"}
  ],
  "categories": [
    {
      "key": "gpu",
      "label": "Placa de vídeo",
      "published": true,
      "warnings": [],
      "ipca": {
        "subitem": "47641",
        "label": "Computador pessoal",
        "is_proxy": true,
        "period": "2026-09",
        "change_12m_pct": 2.1,
        "status": "ok"
      },
      "tiers": [
        {
          "tier": "baixo",
          "range_brl": {"min": 1500, "max": 2800},
          "price_cash_brl": 2349.0,
          "price_full_brl": 2599.0,
          "change_30d_pct": 3.0,
          "listings": {"tracked": 4, "valid": 4},
          "warnings": [],
          "series": "price.gpu.baixo",
          "offers": [
            {
              "code": "123456",
              "name": "Placa de Vídeo RTX 5060 8 GB …",
              "brand": "nvidia",
              "price_cash_brl": 2199.0,
              "price_full_brl": 2449.0,
              "status": "valid",
              "url": "https://www.kabum.com.br/produto/123456"
            }
          ]
        },
        {
          "tier": "alto",
          "range_brl": {"min": 12000, "max": null},
          "price_cash_brl": 15999.0,
          "price_full_brl": 17699.0,
          "change_30d_pct": 12.0,
          "listings": {"tracked": 2, "valid": 1},
          "warnings": [{"code": "partial", "text": "1 de 2 anúncios"}],
          "series": "price.gpu.alto",
          "offers": []
        }
      ]
    },
    {
      "key": "ram",
      "label": "Memória RAM",
      "published": false,
      "warnings": [{"code": "category_unpublished", "text": "menos de 2 faixas com preço hoje"}],
      "ipca": {"subitem": "47641", "label": "Computador pessoal", "is_proxy": true, "period": "2026-09", "change_12m_pct": 2.1, "status": "ok"},
      "tiers": [
        {"tier": "baixo", "range_brl": {"min": 250, "max": 800}, "price_cash_brl": null, "price_full_brl": null,
         "change_30d_pct": null, "listings": {"tracked": 1, "valid": 0},
         "warnings": [{"code": "no_price", "text": "sem preço hoje"}], "series": "price.ram.baixo", "offers": []}
      ]
    }
  ],
  "brand_view": {
    "category": "gpu",
    "brands": [{"key": "nvidia", "label": "NVIDIA"}, {"key": "amd", "label": "AMD"}],
    "note": "Compara o preço dos modelos escolhidos em cada faixa, não o custo por desempenho. A RX 9060 XT tem 16 GB e a RTX 5060 tem 8 GB.",
    "tiers": [
      {
        "tier": "baixo",
        "nvidia": {"model": "RTX 5060 8 GB", "price_cash_brl": 2199.0, "change_30d_pct": 2.0,
                    "listings": {"tracked": 2, "valid": 2}, "warnings": [],
                    "series": "price.gpu.baixo.nvidia"},
        "amd": {"model": "RX 9060 XT 16 GB", "price_cash_brl": 2499.0, "change_30d_pct": 4.1,
                 "listings": {"tracked": 2, "valid": 1}, "warnings": [{"code": "partial", "text": "1 de 2 anúncios"}],
                 "series": "price.gpu.baixo.amd"},
        "diff_amd_pct": 13.6,
        "diff_series": "price.gpu.baixo.diff_amd_pct",
        "warnings": []
      },
      {
        "tier": "alto",
        "nvidia": {"model": "RTX 5090 32 GB", "price_cash_brl": 15999.0, "change_30d_pct": 12.0,
                    "listings": {"tracked": 2, "valid": 1}, "warnings": [{"code": "partial", "text": "1 de 2 anúncios"}],
                    "series": "price.gpu.alto.nvidia"},
        "amd": null,
        "diff_amd_pct": null,
        "diff_series": null,
        "warnings": [{"code": "no_competitor", "text": "sem concorrente nesta faixa"}]
      }
    ]
  },
  "technical": {
    "mean_of_tiers_brl": {"gpu": 7516.0}
  }
}
```

### Campos e regras

| campo | regra (origem) |
| --- | --- |
| `price_cash_brl` | Preço à vista (`priceWithDiscount`) da faixa: mediana das URLs válidas. Na GPU, média das marcas válidas, cada marca pesando igual (T24f §2). |
| `price_full_brl` | Preço cheio (`price`) pela mesma regra; vai na 2ª linha (T24g). |
| `change_30d_pct` | Variação pareada da faixa; na GPU, pareada por marca (T24e, T24f). `null` sem dois pontos comparáveis. |
| `listings.tracked` / `valid` | URLs da cesta na faixa / URLs que passaram em disponível, vendida pela KaBuM, dentro do K14b, fora de "suspeito" e fora de oferta relâmpago (T24d, T24g). |
| `published` (categoria) | `true` com ≥ 2 das 3 faixas com preço (T24e). |
| `offers[].status` | `valid`, `suspect` (salto > 40%, K14d), `unavailable` (K14e), `out_of_range` (K14b), `flash` (relâmpago, fora da mediana). Todas aparecem, para o painel mostrar o motivo; só `valid` entra no preço. |
| `offers[].url` | Montada **no servidor** a partir do `code` (`^\d{1,10}$`): `https://www.kabum.com.br/produto/<code>` (K16). Nunca a URL da página. |
| `offers[].name` | Já limpo no servidor: sem `Cc`/`Cf`, espaços compactados, até 160 caracteres (K15). O painel ainda faz `esc()`. |
| `offers[].brand` | Só na GPU (`nvidia` ou `amd`); `null` nas outras categorias. |
| vendedor | Não vai no JSON: a coleta só aceita `sellerName == "KaBuM!"` (K5, K18). |
| `ipca` | Subitem do catálogo (`ipca_subitem`), com `period` (AAAA-MM) e o selo `is_proxy` (T24c). `status` segue a fonte IBGE. |
| `brand_view.tiers[].diff_amd_pct` | `preço AMD ÷ preço NVIDIA − 1`, em %. `null` sem as duas marcas no dia ou no topo (T24f §3). |
| `technical.mean_of_tiers_brl` | Média das três faixas por categoria; só para a aba Técnico (T24e). |

### Avisos (`warnings`)

Lista de `{code, text}`. O `code` é estável para o Frontend decidir ícone e
estilo; o `text` já vem pronto em português.

| `code` | `text` | quando |
| --- | --- | --- |
| `single_listing` | "anúncio único" | faixa com 1 URL na cesta e ela válida |
| `partial` | "N de M anúncios" (ex.: "1 de 2 anúncios") | parte das URLs da faixa ou da marca válida |
| `brand_only` | "só NVIDIA hoje" / "só AMD hoje" | GPU com uma das marcas sem URL válida no dia |
| `no_price` | "sem preço hoje" | faixa sem URL válida |
| `no_competitor` | "sem concorrente nesta faixa" | célula AMD no topo |
| `suspect` | "preço suspeito, aguardando confirmação" | alguma oferta da faixa em `suspect` |
| `category_unpublished` | "menos de 2 faixas com preço hoje" | categoria com `published=false` |

### Segurança do contrato (lembrete para o Frontend)

- Link só com `storeUrl(raw)`: `https:`, `hostname === 'www.kabum.com.br'`,
  sem usuário, senha ou porta; fora disso, o nome aparece como texto (K16).
  Atributos: `target="_blank" rel="noopener noreferrer nofollow"
  referrerpolicy="no-referrer"` (K17).
- `esc()` em todo texto, inclusive em hover e rótulos do Plotly (K18).

### Pontos em aberto

1. Nomes das faixas no JSON: `baixo`/`medio`/`alto` (sem acento, para usar
   em chave de série). O rótulo com acento vem em `tiers[].label`.
2. Quem monta o `PricesView`: proposta de que o `app/domain/` (Modelo) faça
   as contas e o coletor (Backend) só junte e exponha.
3. Os IDs de série `price.*` entram em `SERIES_BY_KEY` (Modelo) junto com a
   implementação.

## T32 — preços, frentes de oferta e tela (Backend + Frontend, 2026-11-05)

Interface combinada com "dados e modelo": `kabum.fetch_basket()` →
`kabum.basket`; `tsmc.fetch_monthly_revenue()` → `tsmc.monthly_revenue`;
`sec.fetch_memory_quarters()`/`fetch_logic_quarters()` →
`sec.memory_quarters`/`sec.logic_quarters`;
`prices.build_prices_view(collected, listings_by_code, today)` e
`supply_fronts.build_fronts(collected, today)`.

**API:** jobs com import tolerante (entram quando a função existe); a KaBuM
só com `kabum_enabled`; `enable_tsmc` novo. O histórico grava
`kabum.<code>.full/.cash/.avail` por dia (vendedor de marketplace vira
`avail=0` sem preço) e devolve 60 dias por `code`. `Snapshot.prices`,
`Snapshot.supply_fronts` e `GET /api/prices` (503 sem snapshot; com a fonte
desligada, 200 `disabled` com o motivo e as 10 categorias só com o IPCA). As
séries `price.*` vão para o histórico a cada snapshot.

**Tela:** `prices.js` com o cheio como principal e o à vista na 2ª linha;
rótulo fixo "Preço na KaBuM (preço cheio) · parcelado em até 10× sem juros";
selo de relâmpago; `no_model`; categorias `ipca_only` (e todas, com a loja
desligada) mostram só o IPCA com o selo proxy ou "sem subitem". Os 3 cards de
oferta (Memória, Chips, Demanda) substituem "Estoque de memória" na Fila e na
Visão Geral ("N dias", "o normal é X a Y", sem tooltip; "sem dado nesta
rodada" até o domínio ligar). Gráficos: `lineTraces` esmaece o trecho antes
do `model_since` em iph, iph_br e cat.* (a Evolução já fazia isso). K16–K18
mantidos; `fmtPct` intocado.

**Não verificado no navegador:** o Chromium do Playwright não abre dentro do
sandbox desta sessão, rodar fora dele foi negado, e o Firefox headless tira o
screenshot antes de a página carregar os dados. Suíte: 345 passed; `node
--check` ok; `/api/prices` respondeu 200 `disabled` com 10 categorias no
servidor de teste.

## T30 — ligação dos provedores (2026-11-05)
- Jobs `sec.memory_quarters`, `sec.logic_quarters`, `tsmc.monthly_revenue` (ttl_monthly) e `kabum.basket` (24 h, só com DSH_ENABLE_KABUM+DSH_CONTACT) já estavam ligados por getattr e entram agora; `/api/prices` e `supply_fronts` usam o `build_*` real. Sem mudança de código.
- `sec.memory_inventory` continua no coletor: `domain/supply.py:153` ainda o lê.
- pytest: 335 passed, 10 failed (3 previstos em test_api_security + 7 de modelo: queue_model, supply, backfill, methodology). Substitutos em testes-pendentes/test_t30_ligacao.py: 17 passed.
- As 10 falhas foram confirmadas pelo "dados e modelo" como esperadas pela T30 (a fila passou a usar só a demanda, são 11 sinais, os dio_*/tsmc usam mode="front" e MODEL_VERSIONS não está mais vazio); os testes substitutos vão para a QA pelo Coordenador.

## T33 — vendedor fixado no histórico (2026-11-05)
- `history.record_listings`: `own` aceita `seller_expected` (vendedor da curadoria) e, sem ele, a KaBuM. Vendedor diferente do fixado continua com avail=0 e sem preço.
- pytest: 335 passed, 10 failed (as mesmas falhas esperadas da T30).
- O teste de regressão `test_historico_grava_preco_do_vendedor_fixado` está pronto em testes-pendentes/test_t30_ligacao.py (feito pelo "dados e modelo"); a QA move para tests/ com a permissão do usuário.

## T35b — coleta nova da KaBuM no coletor (2026-11-06)
- `_run`: loja passa `version=prices.BASKET_VERSION` ao `get_or_fetch` (cesta nova vence o cache).
- Saiu `_listing_history` (payload["listings"] não existe mais). Entram `_model_history` (lê `kabum_model.*` dos últimos 60 dias → `model_history` do `build_prices_view`) e `_record_model_prices` (grava os `kabum_model.*` de `series_values` e tira `series_values` da resposta da API; `price.*` seguem pelo `record_snapshot`).
- history: `record_model_prices(values, day)` e `model_price_history(keys, days)`. `record_listings`/`listing_history` ficam (testes pendentes usam).
- pytest: 335 passed, 10 failed (as mesmas da T30); testes-pendentes: 86 passed.

## T-Plotly (remoção)
- Apagados `app/static/vendor/plotly-2.35.2*` (js + LICENSEs) e a pasta `vendor/`; comentário da CSP em `app/main.py` reescrito (diretivas intactas); títulos de seção em `styles.css`/`editorial.css` sem "Plotly". `index.html` e `tests/` já não citavam Plotly (`test_ui_contract` já cobre "sem plotly nem cdn").
- pytest (KaBuM/TSMC off): 325 passed, 20 failed — em test_api_security(4), backfill(1), comtrade_monthly(1), queue_model(4), supply(1), ui_contract(9); nenhuma ligada ao Plotly.
