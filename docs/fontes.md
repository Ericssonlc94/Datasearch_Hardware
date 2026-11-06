# Política de fontes — DataSearch Hardware

Verificado ao vivo em **03/11/2026**; Federal Register, USGS, feeds RSS e a
remoção do GDELT conferidos em **04/11/2026**. Este documento é normativo: se
uma fonte não se encaixa nas regras abaixo, ela não entra no código — mesmo
que o dado seja útil.

## As quatro regras

1. **Nenhuma chave de API.** Fonte que exige cadastro, token ou `api_key` fica
   de fora. Não há exceção.
2. **Nenhum captcha, JS challenge ou automação de navegador.** Se a resposta é
   um interstitial anti-bot, a fonte é rejeitada. Não contornamos, não
   imitamos navegador, não usamos proxy de terceiro.
3. **Identificação honesta.** O `User-Agent` traz o projeto e um contato.
   É proibido enviar `Origin`/`Referer` de outro site para se passar por ele.
4. **Falha é evento de primeira classe.** Fonte que cai vira `stale` (último
   valor bom, visivelmente marcado) ou `unavailable`, derruba a `coverage` e
   aparece em `/api/health` e na tabela de fontes. Nunca preenchemos lacuna
   com chute.

## Detecção automática de bloqueio

`app/http.py` expõe `ChallengeDetected` e `reject_challenge()`, chamados em
`get_json`, `post_json` e `get_text`. Marcadores procurados nos primeiros 4 KB:
`captcha`, `just a moment`, `cf-chl`, `requires javascript`, `attention
required`, `checking your browser`, `enable javascript and cookies`,
`access denied`.

Quando o marcador aparece, o provider falha **antes** de gravar qualquer coisa
no cache: HTML de bloqueio nunca é promovido a dado.

## Fontes aprovadas

| Chave interna | Fonte | Formato | Observação |
|---|---|---|---|
| `bcb.*` | BCB/SGS | JSON | PTAX, IPCA, Selic, IGP-M |
| `ibge.ipca_hardware` | IBGE/SIDRA 7060 | JSON | IPCA por subitem |
| `fred.*` | FRED `fredgraph.csv` | CSV | 14 séries |
| `market.*` | Yahoo Finance chart v8 | JSON | 16 tickers |
| `comtrade.*` | UN Comtrade preview | JSON | 1 período por chamada |
| `sec.*` | SEC EDGAR XBRL `companyconcept` | JSON | 5 hyperscalers + NVDA/MU/AMD/INTC; 24 h de TTL |
| `fedreg.bis_chip_rules` | Federal Register API v1 (regras do BIS) | JSON | sentido lido no título; cache de 6 h |
| `usgs.fab_quakes` | USGS FDSN Event API | GeoJSON | magnitude ≥ 5,5 a até 150 km de polos de chips; cache de 6 h |
| `news.rss` | 43 feeds RSS/Atom dos próprios veículos | XML | 8 feeds simultâneos; cache de 30 min |
| `tsmc.monthly_revenue` | TWSE OpenAPI `t187ap05_L` (último mês, com data de publicação) + MOPS `mops/api/t05st10_ifrs` (histórico, POST JSON) | JSON | receita consolidada mensal da TSMC em NT$ milhões, desde 2019; 48 consultas espaçadas 1,5 s, uma por vez; para no 1º desafio/403/429; TTL de 24 h |
| `sec.memory_quarters`, `sec.logic_quarters` | SEC EDGAR XBRL `companyconcept` | JSON | estoque, CPV, dias do trimestre e `filed` de Micron (memória) e NVIDIA/AMD/Intel (lógica) |
| `kabum.basket` | KaBuM, busca `/busca/<termo>` limpa (`__NEXT_DATA__`) | HTML | cesta de 114 modelos (3–5 por faixa), 1 busca por modelo; preço do modelo = mediana dos anúncios; regras abaixo |

## SEC EDGAR — capex, receita e estoque

`data.sec.gov/api/xbrl/companyconcept` é público, keyless e não apresenta
challenge. Regras aplicadas:

- `User-Agent` identificável com contato (o mesmo `DSH_USER_AGENT` do projeto);
- semáforo de 4 requisições simultâneas e 120 ms entre chamadas, abaixo do
  limite documentado de 10 req/s;
- cache de 24 h, porque o dado é trimestral;
- uma empresa que falha não invalida as outras: a cobertura cai e o aviso fica
  em `note`.

O endpoint mistura trimestre isolado e acumulado do ano. Alphabet, Meta e
Oracle publicam sobretudo Q1 e YTD; por isso o parser deriva Q2/Q3/Q4 pela
diferença dos acumulados (`Q2 = H1 − Q1` etc.) e deduplica pelo `filed` mais
recente. Trimestres de anos fiscais diferentes são alinhados por
trimestre-calendário, com cobertura mínima de 3 de 5 empresas no capex e 2 de
3 na receita. TTM é sempre a soma de quatro trimestres consecutivos.

Limitação declarada: a SEC entrega capex, receita e estoque contábil — **não**
preço spot de DRAM/NAND. A fila do consumidor é heurística construída sobre
esses dados, não uma medição de alocação física por cliente.

## Notícias: digest, deduplicação e corroboração

Manchete não é medição. Por isso o painel não exibe o retorno bruto dos feeds RSS:
todo ciclo passa por `app/domain/news.py`, que aplica cinco regras — e nenhuma
delas promete detectar “fake news”, o que não existe de forma automática.

1. **Release e agregador ficam de fora.** Comunicado distribuído por agência
   paga (`prnewswire`, `businesswire`, `globenewswire`, etc.) e redirecionador
   (`news.google`, `msn`, `newsnow`, etc.) não passaram por apuração editorial
   independente. A lista é estrutural, não acusa linha editorial de ninguém.
2. **Republicação é deduplicada.** URL canônica (sem `utm_*`, `fbclid`,
   fragmento e `www.`) + impressão digital do título normalizado.
3. **A mesma história é agrupada entre veículos.** Títulos com sobreposição de
   tokens ≥ 50% (mínimo de 2 palavras em comum) formam um cluster.
4. **Cada item recebe um rótulo explícito:** `corroborated` quando ≥ 2 domínios
   distintos cobriram a história; `single-source` caso contrário. **Fonte única
   não significa falsa** — significa ausência de segunda checagem no recorte.
5. **O conjunto exibido tem um digest SHA-256 curto**, calculado sobre as
   impressões digitais ordenadas. Ele muda quando o conjunto muda, é
   independente da ordem de entrada e fica **no log do servidor** — é
   mecanismo interno de auditoria, não campo de API nem elemento de interface.

O digest roda automaticamente dentro do ciclo de coleta. Não existe botão,
endpoint ou ação do usuário que o dispare, e ele não é exibido no painel.

Limitações declaradas: o agrupamento é lexical e funciona melhor no mesmo
idioma; uma história coberta só em chinês e só em inglês pode não ser agrupada.
O digest prova integridade do conjunto, não veracidade do conteúdo. A curadoria
final continua humana — o painel mostra o domínio e a URL de cada item.

## TSMC — receita mensal

- **Último mês:** TWSE OpenAPI, com a data real de divulgação (`出表日期`).
- **Histórico:** API da tela de receita mensal do MOPS novo
  (`mops.twse.com.tw/mops/api/t05st10_ifrs`), uma empresa e um mês por
  chamada; cada resposta traz o mês e o mesmo mês do ano anterior, então 48
  chamadas cobrem 8 anos.
- **Robots (lidos em 05/11/2026):** `openapi.twse.com.tw` e `mops.twse.com.tw`
  respondem 404 (tudo permitido, RFC 9309). O MOPS antigo
  (`mopsov.twse.com.tw`) tem `User-Agent: * / Disallow: /` e não é usado.
- **Data de divulgação:** só a TWSE informa. Para os meses do MOPS vale a
  data-limite legal (dia 10 do mês seguinte), listada em
  `released_estimated`; a reconstrução histórica corta por ela.

## KaBuM — preço observado

- **T35 (05/11/2026, K5 trocada com aprovação do usuário):** só
  `GET /busca/<termo>` limpo — sem "?", sem ordenação, sem página 2 (o robots
  permite o caminho e proíbe os parâmetros). Um pedido por modelo da cesta
  (`domain.prices.BASKET`, versão `BASKET_VERSION`). O link exibido é montado
  a partir do código.
- **Filtro do anúncio:** o nome começa pelo tipo do produto e tem os termos
  obrigatórios do modelo, sem os de exclusão (kit, combo, usado, acessório e
  os da categoria); preço dentro da faixa do nível com 25% de folga e da faixa
  plausível; anormal (1,5× acima ou abaixo da mediana dos outros) sai.
- **Vendedor:** vale a "KaBuM!"; o marketplace dentro da KaBuM entra só no
  modelo sem nenhum anúncio válido da KaBuM! no dia (selo "marketplace", nome
  do vendedor como texto, K18).
- **Preço:** do modelo, a mediana do cheio dos anúncios válidos, com até 3
  anúncios de referência (os mais perto da mediana); da faixa, a média dos
  modelos; variação pareada por modelo.
- **Cache:** a entrada guarda a `cache_version` da cesta; cesta nova = coleta
  vencida. A coleta `ok` vale como preço atual por até 8 dias.
- **Busca sem lista (T35c):** página 200 sem `catalogServer.data` = modelo sem
  anúncio, e a coleta segue; 3 seguidas = layout mudou, e a coleta para.
- **Regra do preço cheio:** na busca, o cheio é `price` (igual ao `oldPrice`
  da página de produto em oferta). O à vista é o `priceWithDiscount`; durante
  a oferta relâmpago ele é o preço da oferta e vai à parte (selo).
- **Limites (Segurança §T26, K3–K21):** até 40 pedidos por dia (a rodada de
  05/11/2026 da T35 coletou a cesta inteira de uma vez, liberada pelo
  usuário; a divisão em vários dias fica para depois), um por vez,
  3–5 s entre eles, sem nova tentativa, `robots.txt` lido a cada coleta (4xx
  = permitido; 5xx, tempo esgotado ou desafio = sem coleta; bloco para agente
  de IA ou `/busca/` proibido = parar), sem seguir redirecionamento, sem
  cookies, página até 5 MB e `__NEXT_DATA__` até 4 MB, `html.parser`, JSON
  sem NaN/Infinity, tipos conferidos e textos limpos. Desafio antirrobô ou
  403/429: a coleta para no primeiro e fica 24 h sem tentar.
- **K9 — termos e robots:** lidos em **05/11/2026** (`/politicas`, sem
  cláusula sobre coleta automatizada; robots sem bloco para agente de IA,
  `/produto/` permitido). Reler a cada 90 dias — próxima leitura até
  **03/02/2027** — e antes de qualquer mudança na cesta.

## Fontes rejeitadas

| Fonte | Evidência | Decisão |
|---|---|---|
| **Stooq** | *"This site requires JavaScript to verify your browser"* | removido do código em 03/11/2026 |
| **TSMC investor relations** | HTTP 403 `cf-mitigated: challenge` (Cloudflare) para o cliente do app em 05/11/2026 | fora, sem contorno; histórico pelo MOPS |
| **MOPS antigo** (`mopsov.twse.com.tw`) | `robots.txt`: `User-Agent: *` / `Disallow: /` | fora; usar a API do MOPS novo |
| **DART** (SK hynix, Samsung) | exige chave (`등록되지 않은 인증키`); a divisão de memória da Samsung não vem na API estruturada | fora por ora; reavaliar se o usuário cadastrar a chave |
| **data.go.kr** (exportação da Coreia) | 401 `SERVICE_KEY_IS_NULL`; a prévia de 10/20 dias não separa semicondutores | fora por ora; idem |
| **Mercado Livre** | busca 403 sem token; exige app com OAuth e conta validada, sem garantia de liberar | fora |
| **Zoom e Buscapé** | `robots.txt` com `Disallow: /` para `ClaudeBot`/`Claude-User`/`Anthropic-AI`; busca e link de oferta proibidos para `*` | fora |
| **Amazon BR** | `robots.txt` com `Disallow: /` para os agentes da Anthropic | fora |
| **Pichau** | 403 `cf-mitigated: challenge` (Cloudflare) | fora, sem contorno |
| **Terabyte** | 403 "Just a moment…" (Cloudflare) no próprio `robots.txt` | fora, sem contorno |
| **Samsung, Dell e Lenovo** | termos limitam o conteúdo a uso pessoal não comercial (Samsung, Dell; Dell proíbe replicar); Lenovo monta o preço no navegador | fora: a cesta usa uma loja só (KaBuM), com regra de preço única |
| **UCDP GED** | HTTP 401 "API token required" | fora — exige token |
| **Census API** | redireciona para `missing_key.html` | fora — exige chave |
| **Frankfurter** | 301 atrás de Cloudflare | fora; FX extra via `open.er-api.com` |
| **Comex Stat** | WAF 429; exigia `Origin`/`Referer` forjados | desligado por padrão (`enable_comexstat=False`); headers removidos |
| **BLS public API** | cota de 25 req/dia | inviável para ciclo de 15 min |
| **GDELT DOC 2.0** | HTTP 429 na maior parte dos ciclos, mesmo com 5 s entre consultas | removido do código em 04/11/2026; manchetes só por RSS, controles de exportação pelo Federal Register |

## Como revalidar

```bash
python - <<'PY'
import httpx
for url in ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?formato=json",
            "https://www.federalregister.gov/api/v1/documents.json?conditions[agencies][]=industry-and-security-bureau&per_page=1",
            "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1"):
    r = httpx.get(url, timeout=20, headers={"User-Agent": "datasearch-hardware/1.0"})
    print(r.status_code, r.headers.get("content-type"), url)
PY
```

Se aparecer `text/html` com um dos marcadores acima, a fonte deve ser
**removida**, não ajustada.
