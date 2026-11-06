# Relatório — Segurança

## T02 · Auditoria nas cinco categorias (04/11/2026)

**Escopo:** `app/main.py`, `app/config.py`, `run.py`, `.env.example`,
`app/http.py`, `app/providers/news_rss.py`, `app/domain/news.py`,
`app/services/history.py`, `app/static/*.js`, `app/static/index.html`,
histórico do git (fora `vendor/`).

**Stack:** Python 3.14, FastAPI + uvicorn, httpx, SQLite (`sqlite3` puro),
painel sem build (JS puro + Plotly 2.35.2 local). Sem login, sem usuários,
sem banco por usuário. O servidor escuta em `127.0.0.1` por padrão
(`app/config.py:14`).

### Categorias que não se aplicam

| Categoria | Por quê |
| --- | --- |
| 1. Isolamento de dono/inquilino | Não há usuários nem dados por pessoa; todo dado é público e igual para todos. |
| 2. Permissão decidida no navegador | Nenhuma tela esconde ação por papel; não há papéis. (O `/api/refresh` aberto está no achado S2.) |
| 3. IDOR | Nenhuma rota busca objeto por ID de dono; `/api/history` só aceita chaves de um catálogo fixo. |

### Achados

| ID | Gravidade | Onde | Problema | Correção sugerida | Dono |
| --- | --- | --- | --- | --- | --- |
| S1 | **média** | `app/providers/news_rss.py:126-135`, `:193-210`; `app/static/app.js:951` | O link da manchete vem do feed sem conferir o esquema. Um item com `<link>javascript:…</link>` (feed invadido ou veículo malicioso) vira `<a href="javascript:…">`. O `esc()` escapa aspas, mas `javascript:` não tem nada a escapar. `target="_blank"` + `noopener` reduzem o impacto na maioria dos navegadores, mas a proteção depende do navegador. | **Dados:** em `_parse_feed`, descartar o item se `urlsplit(url).scheme not in ("http", "https")` ou se não houver `hostname`. **Frontend (defesa extra):** helper `safeUrl(u)` que devolve `'#'` quando `new URL(u).protocol` não é `http:`/`https:`, usado na linha 951 e em qualquer `href` futuro com dado externo. | Dados (principal), Frontend |
| S2 | **média** | `app/main.py:212-214` (`POST /api/refresh`), `app/main.py:194-199` (`GET /api/snapshot?force=true`) | Qualquer um que alcance a porta dispara uma coleta completa que ignora o cache (cerca de 38 fontes e 43 feeds). Não há autenticação nem limite de chamadas. O lock enfileira os pedidos, mas não descarta os excedentes: N chamadas viram N coletas seguidas. Mesmo em `127.0.0.1`, qualquer site aberto no navegador do usuário consegue disparar isso: `fetch(..., {method:'POST', mode:'no-cors'})` no POST, ou um `<img src=".../api/snapshot?force=true">` no GET. Efeito: o IP do usuário passa a ser tratado como abusivo pelas fontes (SEC, Yahoo, Comtrade), os disjuntores abrem e o painel degrada. Com `DSH_HOST=0.0.0.0`, qualquer máquina da rede local faz o mesmo. | (a) Intervalo mínimo entre coletas forçadas (ex.: ignorar `force` se a última coleta tem menos de 60 s, devolvendo o snapshot atual com `429` ou `200` + aviso); (b) se já houver coleta em andamento, aguardar a mesma em vez de enfileirar outra; (c) tirar o `force` do GET, porque GET não deve ter efeito colateral, e deixar só o POST; (d) aceitar o POST só com `Content-Type: application/json` ou um header próprio (`X-Requested-With`), que um site de terceiros não consegue mandar sem preflight CORS. O botão do painel (`app/static/app.js:1482`) passa a usar o POST. | Backend (a–d), Frontend (trocar a chamada em `app.js:1482`) |
| S3 | **baixa** | `app/http.py:222-225`, `:194-206`, `:31-36` | A resposta é lida inteira na memória (`resp.text`/`resp.json()`) sem limite de tamanho. Um feed invadido ou um redirecionamento para um arquivo de gigabytes esgota a RAM do processo. | Ler com `client.stream(...)` e abortar acima de um teto por tipo (ex.: 5 MB para RSS, 20 MB para JSON da SEC); conferir também o `Content-Length` quando vier. | Dados |
| S4 | **baixa** | `app/http.py:32` | `httpx.Timeout(20)` limita cada fase (conectar, ler um pedaço), não o pedido inteiro. Um servidor que manda um byte a cada 19 s prende a conexão por tempo indefinido, ocupando uma das 24 vagas do pool e o semáforo de 8 do RSS. Isso, multiplicado pelas retentativas, segura o ciclo de coleta. | Envolver `_request` em `asyncio.timeout(total)` (ex.: 2 × `http_timeout`), além do timeout por fase. | Dados |
| S5 | **baixa** | `app/http.py:34` | `follow_redirects=True` segue redirecionamentos para qualquer host, inclusive de `https` para `http` e para IP interno (`127.0.0.1`, `192.168.x`, `169.254.169.254`). Como as URLs são fixas, explorar isso exige que uma fonte esteja comprometida. O risco é baixo, mas um redirecionamento pode fazer o app consultar a rede interna, e o trecho da resposta acaba na mensagem de erro exibida no painel. | `max_redirects=5`; hook `event_hooks={"response": [...]}` (ou checagem do `resp.history`) que recusa o redirecionamento se o destino não for `https` ou se o host resolver para um IP privado/loopback/link-local. | Dados |
| S6 | **baixa** | `app/static/index.html` (sem CSP); `app/main.py:147-158` | Não há Content-Security-Policy. Se algum `innerHTML` futuro esquecer o `esc()`, nada segura o script injetado. | Header via middleware no Backend: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`, mais `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`. Hoje não há `<script>` inline nem `on*=` no HTML, então a política passa sem mexer no painel (os `style=` inline exigem o `'unsafe-inline'` em `style-src`). | Backend |
| S7 | **baixa** | `app/main.py` (todas as rotas) | O servidor não confere o header `Host`. Um site malicioso pode usar DNS rebinding para ler `/api/*` pelo navegador do usuário. Hoje o impacto é pequeno, porque os dados são públicos, mas isso abre caminho para o S2. | `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost", ...])`, configurável por `DSH_ALLOWED_HOSTS` no `.env.example`. | Backend |
| S8 | **informativa** | `app/main.py:98`, `:368`, `:467-476`; `app/http.py:191`, `:200-206` | `/api/health`, `/api/cache` e o campo `error` das fontes mostram texto de exceção interna e até 160 caracteres da resposta da fonte. Não vaza segredo, porque não há nenhum, e o painel escapa tudo (`app.js:1107`). Mesmo assim, é conteúdo de terceiros e detalhe interno exposto. | Manter, mas truncar e não incluir o corpo da resposta de terceiros na mensagem pública. Se o S5 não for feito, este item sobe de gravidade. | Backend, Dados |
| S9 | **informativa** | `app/providers/news_rss.py:183` | `xml.etree.ElementTree.fromstring` em XML de terceiros. A expat 2.9.0 desta máquina já barra "billion laughs", e o ElementTree não resolve entidades externas. Com uma expat antiga em outra instalação, a proteção some. | Trocar por `defusedxml.ElementTree.fromstring` (pacote pequeno, sem chave) ou registrar no README a versão mínima da expat (≥ 2.4.1). | Dados |

### Itens do foco que estão corretos

| Controle | Evidência |
| --- | --- |
| Títulos de manchete escapados | `app/static/app.js:951` usa `esc(h.title)`; o `esc()` (`app.js:37-40`) cobre `& < > " '`. `_clean` (`news_rss.py:112-115`) tira as tags, mas não é a defesa; a defesa é o `esc()`, e ele está lá. |
| Escape em todo `innerHTML` com dado externo | Conferidos `app.js` (fontes, ranking, drivers, notícias, câmbio), `dashboard.js` (`dEsc`, `:38-40`) e `charts.js` (`_tipEsc`). Os textos do Plotly vêm só do catálogo do servidor, não de feed. |
| `/api/history` validado por allowlist | `range` só aceita as chaves de `_RANGES` (`main.py:255-263`); `series` só aceita chaves de `SERIES_BY_KEY`, até 12 (`:265-277`); `bucket` só aceita as chaves de `_BUCKETS` (`:279-287`); `raw` só vale em janelas de até 7 dias (`:308-312`). |
| SQL parametrizado | `services/history.py:288-291`, `:318-326`, `:404-406`: as f-strings só montam `?,?,?`; os valores vão em parâmetros. Nenhum valor do usuário entra no texto SQL. |
| Sem segredos | `.env.example` só tem host, porta, TTLs e chaves de liga/desliga; nenhuma chave de API. Busca no código e no histórico do git (fora `vendor/`): nada. `.env` e `data/` estão no `.gitignore` (linhas 156 e 10). |
| Escuta só local por padrão | `config.py:14` e `.env.example:4` usam `127.0.0.1`. |
| Sem bloqueio contornado | `http.py:61-81` detecta a página anti-robô e falha, em vez de tentar driblar. |

### Ordem sugerida de correção

1. **S1** (Dados + Frontend): conserto barato que fecha o único caminho de
   script vindo de fora.
2. **S2** (Backend + Frontend): é o T10 do PRD; protege o IP do usuário
   contra banimento pelas fontes.
3. **S6, S7** (Backend): dois middlewares, pouco código.
4. **S3, S4, S5** (Dados): é o T09 do PRD; robustez do cliente HTTP.
5. **S8, S9**: quando sobrar tempo.

Nenhum arquivo de código foi alterado por esta função.

## T22c · Cache persistido em SQLite e disjuntor do Comtrade (04/11/2026)

**Escopo:** `app/cache.py` (save/load, `_encode`/`_decode`, banco corrompido),
`app/config.py:75-87` (`cache_path`/`cache_file`), `app/main.py:97`, `:171`,
`:193`, `app/providers/comtrade.py:44-80`, `app/http.py:220-237`, `:340-356`.

**Premissa:** o `data/cache.db` é escrito só pelo próprio app. Quem consegue
alterar esse arquivo já tem acesso de escrita à pasta do projeto, e daí também
alteraria o código. Por isso, todo achado que depende de adulterar o disco
fica, no máximo, como baixa.

### Achados

| ID | Gravidade | Onde | Problema | Correção sugerida | Dono |
| --- | --- | --- | --- | --- | --- |
| C1 | **média** | `app/cache.py:252-259` | Qualquer `sqlite3.DatabaseError` move o arquivo para `.corrompido-<epoch>`, inclusive `OperationalError: no such table` e "file is not a database". Se `DSH_CACHE_PATH` apontar por engano para outro arquivo, o app o renomeia em silêncio no startup. Exemplos: `data/history.db` (o histórico some até alguém renomear de volta) ou `.env`. O banco não é apagado, mas o efeito parece perda de dados. | (a) Só mover em `"file is not a database"` / `"malformed"` e quando o arquivo não for outro banco do app; com `no such table`, apenas começar vazio. (b) Na `Settings`, recusar `cache_file == history_file` (`resolve()` dos dois). (c) Exigir sufixo `.db` no `cache_path`. | Dados (a), Backend (b, c) |
| C2 | **baixa** | `app/http.py:349`, `app/providers/comtrade.py:56`, `app/http.py:227`, `:122-125` | `Retry-After` vindo do Comtrade passa por `float()` sem limite nem checagem de `isfinite`. `"inf"` ou `"1e400"` viram `cooldown=inf`, e o disjuntor fica aberto até reiniciar o app. Pior: o `breaker_guard` faz `int(b.open_until - time.monotonic())` com `inf`, que levanta **`OverflowError`**, e não `FetchError`. Com isso, `_blocked()` devolve `False` e o laço de meses segue chamando a função, que falha toda vez com uma exceção inesperada. Um valor grande e finito (ex.: `31536000`) desliga o Comtrade por um ano. Valor negativo ou `nan` caem no fallback de 3600 s, como deveriam. Pré-condição: o Comtrade, ou quem o controlar, mandar esse header. Não dá para forjá-lo no meio do caminho, porque a conexão é `https`. | Em `http.py`, normalizar o `Retry-After` numa função só: aceitar só valores finitos em `[0, 6 h]` e tratar o formato de data HTTP (RFC 9110). No `comtrade.py`, `cooldown = min(max(retry_after, 60), 6*3600)`. No `breaker_guard`, calcular o `restante` com `max(0, …)` sobre um valor finito. | Dados |
| C3 | **baixa** | `app/http.py:230-237`, `:315` | O mesmo `float()` no sleep do 429: `min(float("nan"), 30.0)` devolve `nan`, e `asyncio.sleep(nan)` agenda um timer com `when=nan`, cujo comportamento no event loop não está definido. Não reproduzi um travamento, mas o valor não deveria chegar ali. | Usar a mesma normalização do C2 (finito, entre 0 e 30 s) antes do `sleep`. | Dados |
| C4 | **baixa** | `app/cache.py:281-283` | `expires_at` lido do disco não tem limite. Se o relógio da máquina estava adiantado quando o cache foi gravado (problema de RTC, dual boot) e depois foi corrigido, as entradas ficam "frescas" pelo tempo da diferença, e o painel mostra dado velho como atual sem refazer a busca. Além disso, o `float(expires_at)` fica **fora** do `try`: um valor não numérico aborta o `load` inteiro, e não só a linha. | `expires = min(float(expires_at), now_wall + max_ttl)`, onde `max_ttl` é o maior TTL configurado; mover a conversão para dentro do `try` da linha e descartar valores não finitos. | Dados |
| C5 | **informativa** | `app/cache.py:273`, `:102-121` | `json.loads` + `_decode` são recursivos: um payload aninhado demais levanta `RecursionError`, que não é capturado no laço e aborta o `load`. O `main.py:170-174` segura o erro, então o app sobe com o cache vazio, mas sem dizer qual linha causou o problema. Não há como isso virar execução de código: é só JSON, não pickle, e `_decode` só monta `tuple`, `float`, `datetime`, `date` e `dict`. Marcação desconhecida é recusada (`:121`). | Incluir `RecursionError` no `except` da linha (`:277`). | Dados |
| C6 | **informativa** | `app/cache.py:244` | `f"file:{db}?mode=ro"` monta a URI sem escapar o caminho. Um `DSH_CACHE_PATH` com `?`, `#` ou `%` abre o arquivo errado ou falha. Quem define o caminho é o operador, não a web, então não é path traversal explorável. | `f"file:{urllib.parse.quote(str(db))}?mode=ro"`. | Dados |
| C7 | **informativa** | `app/cache.py:217-218`, `:253` | O arquivo é criado com a umask do processo (normalmente 0644), e os `.corrompido-*` se acumulam sem limite. O conteúdo é público, então não é vazamento; é só higiene. | Opcional: `os.chmod(path, 0o600)` após criar; manter só os 3 `.corrompido-*` mais recentes. | Dados |

### Texto de terceiros persistido (manchetes, erros)

- O payload das manchetes (títulos e URLs dos feeds) e os campos `error`/`note`
  agora sobrevivem a reinícios. Como `get_or_fetch` reaproveita o último valor
  bom como `stale` enquanto a busca falhar, um título malicioso pode ficar
  mais tempo na tela. **Hoje está coberto:** o painel escapa todo o texto e
  passa o link por `safeUrl()` (`app/static/app.js:43-46`, `:972`). Assim, mesmo
  linhas gravadas antes do filtro de esquema em `news_rss.py:175` não viram
  `href` perigoso.
- Recomendação (Dados, informativa): quando um filtro de entrada novo for
  aplicado no provider, subir o `CACHE_FORMAT_VERSION` (`app/cache.py:134`)
  para que linhas antigas, que não passaram pelo filtro, sejam descartadas no
  próximo `load`.

### O que está correto

| Controle | Evidência |
| --- | --- |
| Sem desserialização perigosa | JSON puro com allowlist de marcações (`cache.py:102-121`); nada de `pickle`, `eval` ou importação dinâmica. |
| SQL parametrizado | `_UPSERT` e `SELECT` sem interpolar valores (`cache.py:155-166`, `:246-249`). |
| Leitura só-leitura | `load` abre com `mode=ro` (`:244`): ler não altera o banco. |
| Status validado | `status` fora de `SourceStatus` é descartado (`:265`). |
| Falha de cache não derruba o app | `save`/`load` capturam erro de disco/banco, e `main.py:96-100`, `:170-174`, `:192-196` envolvem as chamadas. |
| Caminho não vem da web | `cache_path` só vem de env/`.env`; nenhuma rota HTTP o recebe. |
| `Retry-After` negativo ou `nan` | Caem no fallback de 3600 s (`comtrade.py:56`). |
| Corpo de terceiro fora da mensagem pública | `FetchError.body_snippet` separado da mensagem (`http.py:65-86`), como pedido no S8. |

## T26 · Política de coleta de preço na KaBuM (05/11/2026) — revisão de desenho

**Escopo:** a política proposta pelo Dados (`dados.md` §T25b), o `app/http.py`
atual (redirect, tetos, desafio), o `safeUrl` do painel
(`app/static/app.js:43-50`) e o fluxo de cache e refresh
(`app/cache.py`, `app/services/collector.py`). Ainda não há código da loja;
os achados são requisitos para quando ele for escrito.

### 1. Política: o que falta ou sobra

A base proposta está correta (caminho permitido pelo robots, UA do projeto,
parar no primeiro bloqueio, guardar o mínimo). Faltam itens que fazem a
regra "1 pedido por produto a cada 24 h" valer de fato:

| ID | Gravidade | Problema | Requisito | Dono |
| --- | --- | --- | --- | --- |
| K1 | **alta** | `force=true` passa por cima do cache em todas as fontes (`collector.py:176-182`, `cache.py:312`). O botão "atualizar", `POST /api/refresh` e `GET /api/snapshot?force=true` refariam todos os pedidos à loja na hora, e a regra de 24 h vira letra morta. | A fonte da loja **ignora `force`**: o TTL de 24 h vale sempre. No `_tasks`, passar `force=False` fixo para a chave da loja. | Backend |
| K2 | **alta** | Os disjuntores de `http.py` ficam só em memória, e a falha guardada no cache dura 30 min (`DEFAULT_FAILURE_TTL`). Depois de um 403/429, reiniciar o app ou esperar 30 min volta a bater na loja. Isso contraria o "parar no primeiro bloqueio". | Falha da loja (403, 429, desafio, robots proibindo) fica guardada por **≥ 24 h** (ou pelo `Retry-After` normalizado, o que for maior), **persistida no `cache.db`**. Se o arquivo de cache sumir, um único pedido de sondagem (o `robots.txt`) vem antes de qualquer produto. | Dados (provider), Backend (TTL de falha por fonte) |
| K3 | **média** | Não há teto de pedidos por coleta. Uma cesta de 2 a 4 modelos × ~8 categorias dá até ~32 pedidos, que podem crescer sem ninguém notar. | Teto fixo no código: **≤ 40 pedidos de produto por dia + 1 do robots**, **em série** (concorrência 1), **3 a 5 s entre pedidos**. Acima do teto, a coleta para e marca a fonte como degradada. | Dados |
| K4 | **média** | O `_request` repete até `http_retries=2` em 5xx e erro de rede (`http.py:327+`). Numa loja, cada repetição é um pedido a mais. | Loja com **0 retentativas**. Falhou, fica para o ciclo seguinte (24 h). | Dados |
| K5 | **média** | A busca (`/busca/<termo>`) devolve 60 produtos, mistura modelos parecidos e vendedores do marketplace, e muda de layout com mais frequência. | No ciclo automático, **só URLs fixas de `/produto/<code>/…`** (JSON-LD). A busca fica para a curadoria manual da cesta, fora do loop de 15 min. | Dados, Modelo (cesta) |
| K6 | **média** | Reler o robots a cada coleta é o certo, mas faltam três regras: (a) robots inacessível; (b) robots que passa a proibir; (c) qual parser usar. | (a) Seguindo a RFC 9309: robots com **4xx → pode coletar; 5xx, timeout ou desafio → não coleta** naquele dia. (b) Se o robots passar a proibir `/produto/` para `*` ou para o nosso UA, ou se aparecer um bloco anti-IA, desligar a fonte e avisar no painel. (c) `urllib.robotparser` **no Python 3.14 desta máquina** trata os `*` (testado: `/busca/rtx` permitido, `/busca/rtx?page=2` e `?sort=` bloqueados). O projeto não declara versão mínima de Python. Fixar isso num teste com o robots real salvo como fixture, para não depender da versão. | Dados, QA (teste) |
| K7 | **baixa** | O UA diz `contato: local` (`config.py:40-42`). Isso não é identificação honesta para uma loja: ela não tem como falar com o responsável. | UA com um contato real, pela variável `DSH_CONTACT` (URL do repositório ou e-mail), definido pelo usuário. Sem contato configurado, a fonte da loja não liga. | Backend |
| K8 | **baixa** | "Guardar só preço, data e link" ainda permite gravar o `__NEXT_DATA__` inteiro no cache. | O payload do cache guarda só `{code, preço à vista, preço cheio, disponível, vendedor, data}` por produto. Nada de nome longo, imagem, descrição ou avaliação. Isso também reduz o texto de terceiros persistido. | Dados |
| K9 | **informativa** | Ninguém revisa os termos da loja com regularidade. | Registrar em `docs/fontes.md` a data da leitura de `/politicas` e do robots, e reler a cada 90 dias. | Documentação |

O que sobra: nada. Reler o robots a cada coleta custa um pedido por dia e
pode ficar.

### 2. Parse de `__NEXT_DATA__` e JSON-LD

| ID | Gravidade | Problema | Requisito | Dono |
| --- | --- | --- | --- | --- |
| K10 | **média** | O `json.loads` do Python aceita `NaN`, `Infinity` e `-Infinity` (testado). Um preço `NaN` passa por comparações e contamina médias. Números com mais de 4300 dígitos levantam `ValueError`, e aninhamento profundo levanta **`RecursionError`**, que não é `ValueError`. | `json.loads(txt, parse_constant=_reject)` (levanta em NaN/Infinity); capturar `(ValueError, RecursionError)` e converter em `FetchError` visível. | Dados |
| K11 | **média** | Tamanho: hoje o teto global é 20 MB (`http.py:35`). Uma página da KaBuM fica perto de 1 a 3 MB. | `get_text(url, max_bytes=5 MB)` na loja; o texto do `<script id="__NEXT_DATA__">` limitado a 4 MB antes do `json.loads`; no máximo 10 blocos `ld+json`, de 512 KB cada. | Dados |
| K12 | **média** | Extrair o `<script>` por regex sobre o HTML inteiro é frágil: pega o primeiro `</script>` errado, e uma regex com retrocesso em um HTML de MB custa caro. | Usar `html.parser.HTMLParser`, que pega o conteúdo do `<script id="__NEXT_DATA__" type="application/json">` e dos `<script type="application/ld+json">`. Se não encontrar, levantar `FetchError("layout mudou")` em vez de procurar em outro lugar. | Dados |
| K13 | **média** | Tipos: navegar `props.pageProps.data.catalogServer.data[]` sem checar o tipo de cada nível dá `AttributeError`/`TypeError` com JSON fora do esperado, e a mensagem que chega ao painel fica confusa. No JSON-LD, `offers` pode ser objeto, lista ou `AggregateOffer`, e às vezes vem dentro de `@graph`. | Uma função `_get_path(obj, *keys)` que confere `dict`/`list` em cada passo e devolve `None`. No JSON-LD, aceitar só `@type` `Product`, `offers` com `@type` `Offer` e `priceCurrency == "BRL"`; ignorar o resto. Qualquer exceção no parse vira `FetchError`. | Dados |
| K14 | **média** | Preço plausível: o JSON-LD traz `price` como número **ou** texto (`"9719.1"`), e um valor errado (centavos como reais, `0`, `1e9`, booleano) iria direto para o índice. | (a) Aceitar `int`/`float` que não seja `bool` ou texto que case `^\d{1,6}(\.\d{1,2})?$`, convertido com `Decimal`; nunca o formato `"1.199,00"`. (b) Faixa por categoria (ex.: placa de vídeo R$ 300 a R$ 30 000; memória R$ 50 a R$ 5 000) em `app/domain/`. (c) `priceWithDiscount ≤ price`. (d) Variação maior que 40% contra o último valor guardado vai para "suspeito", fora do índice e marcado no painel, até se confirmar no dia seguinte. (e) Indisponível (`available=false` ou `OutOfStock`) não entra na média. | Dados (a, c), Modelo (b, d, e) |
| K15 | **baixa** | Texto: o nome do produto e o `sellerName` vêm da loja ou do vendedor do marketplace. Podem trazer caracteres de controle ou de direção bidi (`U+202E`), que invertem a leitura na tela, e ter tamanho arbitrário. | Antes de guardar: remover as categorias Unicode `Cc` e `Cf` (inclui bidi), compactar espaços e cortar em 160 caracteres. O `code` só entra se for número (`^\d{1,10}$`). | Dados |

### 3. Links e textos no painel

| ID | Gravidade | Problema | Requisito | Dono |
| --- | --- | --- | --- | --- |
| K16 | **média** | O `safeUrl` atual (`app.js:43-50`) aceita qualquer `http:` ou `https:` de qualquer domínio. Um `url` vindo da página (JSON-LD `offers.url`) poderia levar a outro site. | **Não usar a URL da página.** O servidor monta o link a partir do `code` validado: `https://www.kabum.com.br/produto/<code>`. No painel, um helper `storeUrl(raw)` em cima do `safeUrl` exige `protocol === 'https:'`, `hostname === 'www.kabum.com.br'` (igualdade exata; **não** `endsWith('kabum.com.br')`, que aceitaria `evilkabum.com.br`), sem `username`/`password`/`port`. Fora disso, o nome aparece como texto, sem link. | Dados (montar a URL), Frontend (`storeUrl`) |
| K17 | **baixa** | Atributos do link. | `<a href="…" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">`. | Frontend |
| K18 | **baixa** | Nome do produto e vendedor vão para `innerHTML`. | Sempre `esc(...)`. Mostrar "vendido por X" só quando o vendedor não for a KaBuM. O recomendado, porém, é filtrar `sellerName == "KaBuM!"` na coleta (K5) e não exibir vendedor de marketplace. Se forem para o Plotly (hover, rótulo), escapar também: o Plotly interpreta `<b>`, `<br>` e `<a href>` em textos. | Frontend |

### 4. Ajustes no `http.py` para HTML de loja

| ID | Gravidade | Problema | Requisito | Dono |
| --- | --- | --- | --- | --- |
| K19 | **média** | `get_text` roda `reject_challenge` nos primeiros 4 KB de **toda** resposta 200 (`http.py:414-416`). Página de loja costuma carregar reCAPTCHA no `<head>`, e marcadores como `captcha` e `access denied` dão **falso positivo**: a fonte nunca funciona e parece bloqueio. É o lado seguro da falha, mas contamina o diagnóstico. | Uma função `get_html` para lojas: desafio = status 403/429/503 com HTML, **ou** header `cf-mitigated: challenge`, **ou** `<title>` com "Just a moment"/"Attention Required". Em 200, a prova de página boa é encontrar o `__NEXT_DATA__`/JSON-LD; sem ele, a falha é "layout mudou", não "desafio". | Dados |
| K20 | **média** | O redirect hoje só exige `https` e IP público (`http.py:160-180`). Para a loja, isso permite seguir de `/busca/rtx` para `/busca/rtx?page=1`, caminho que **o robots proíbe**, ou para outro domínio (ex.: uma página de verificação de terceiros). | Para a loja: redirect permitido só para `www.kabum.com.br`, e o destino tem que passar no mesmo teste de robots antes de ser seguido. Na prática, `follow_redirects=False` na loja, e qualquer 3xx vira `FetchError("redirecionado para …")` visível. | Dados |
| K21 | **baixa** | Cookies: o cliente `httpx` compartilhado guarda cookies entre pedidos e entre fontes. Guardar cookie de sessão da loja não é drible, mas acumula estado que não usamos. | Cliente da loja sem cookie jar persistente (`cookies=None` a cada pedido, ou um cliente separado). | Dados |
| K22 | **informativa** | O que já serve: o teto de tamanho por stream (`http.py:300-312`), o timeout total (`:314-325`), o `Retry-After` normalizado (`:237-262`), o redirect só https/IP público e o `ChallengeDetected`, que para sem driblar. | Manter. | — |

### Testes que a QA precisa cobrir (sem rede)

Fixtures locais com: página real salva (busca e produto); `__NEXT_DATA__`
ausente; JSON com `NaN`/`Infinity`; JSON aninhado em 100 000 níveis; preço
`"1.199,00"`, `0`, `true`, `1e9`; `offers.url` de outro domínio; nome com
`<script>` e `U+202E`; 403 com `cf-mitigated`; 302 para `?page=2`; robots
proibindo `/produto/`; 200 com reCAPTCHA no `<head>`, que **não** pode virar
desafio.

### Para registro: mínimo para hospedar numa VPS (sem ação agora)

1. **Login no painel.** O app não tem autenticação. Na VPS, colocar um proxy
   reverso (Caddy ou nginx) com autenticação básica sobre HTTPS, ou um túnel
   (Tailscale, WireGuard) e nada exposto. Isso também atende ao "não
   republicar" da KaBuM e aos termos de Samsung e Dell: o painel não fica
   público.
2. **HTTPS.** Caddy com certificado automático (Let's Encrypt), HTTP
   redirecionado para HTTPS, HSTS.
3. **App só local.** `DSH_HOST=127.0.0.1` (o padrão), atrás do proxy;
   `DSH_ALLOWED_HOSTS` com o domínio real.
4. **Firewall.** `ufw default deny incoming`; liberar só 22 (SSH, de
   preferência restrito por IP), 80 e 443. A porta 8000 nunca aberta.
5. **SSH.** Só chave, `PasswordAuthentication no`, `PermitRootLogin no`,
   fail2ban.
6. **Usuário sem root.** Usuário de sistema próprio (`dsh`), dono só da pasta
   do app; serviço `systemd` com `User=dsh`, `NoNewPrivileges=yes`,
   `ProtectSystem=strict`, `ReadWritePaths=<app>/data`.
7. **Arquivos.** `.env` com `chmod 600` (dono `dsh`); `data/` com `700`.
8. **Limite de chamadas.** No proxy, limitar `/api/refresh` e
   `?force=true` (ex.: 1 por minuto por IP), além do limite no app (S2).
9. **Atualizações.** `unattended-upgrades` para o sistema; dependências
   Python fixadas e revisadas.
10. **Backup** de `data/history.db` (o cache pode ser perdido sem problema).
