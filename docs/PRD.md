# PRD e plano de agentes — DataSearch Hardware

Data: 04/11/2026 · Versão para comentar: https://claude.ai/artifact/GTaFBrkKg95TRHukQDyXJU

## Em uma frase

O painel já funciona. Este plano divide o trabalho que falta entre **oito
funções**, cada uma com um agente dono de uma parte do app, para que vários
agentes editem ao mesmo tempo sem pisar no trabalho um do outro.

## O que o projeto faz

O DataSearch Hardware responde a uma pergunta: **o preço de hardware no Brasil
tende a subir nos próximos 30 dias, e por quê?**

Ele busca números públicos (dólar, inflação, petróleo, ações de fabricantes de
chips, investimento em IA, terremotos perto de fábricas, notícias), transforma
esses números num índice de 0 a 100 e mostra tudo num painel com cinco abas.
Não usa nenhuma chave de API e marca todo número como **dado oficial** ou
**estimativa**.

Situação em 03/11/2026: 34 de 38 fontes funcionando, cobertura de 92%, índice
em 56,9.

O que falta, em resumo: a documentação contradiz o código (GDELT); uma fonte
do governo está bloqueada (Comex Stat); ninguém abriu o painel depois das
últimas mudanças; a "fila do consumidor" travou em 100; as fontes novas não
têm testes; falta uma revisão de segurança; notícias em idiomas diferentes não
são agrupadas.

---

## Mapa do projeto

```
  1. Buscadores        busca os números nas fontes públicas
         ↓
  2. Coordenação       dispara a busca a cada 15 min e guarda o histórico
         ↓  ↑
  3. Cálculos          transforma os números em índice, projeções e fila
         ↓
  4. Servidor          entrega os resultados para o painel
         ↓
  5. Painel            o que a pessoa vê no navegador

  6. Testes            conferem as partes 1 a 4 sem acessar a internet
  7. Documentação      explica tudo isso para quem chega
```

| # | Parte | O que faz | Onde fica |
| --- | --- | --- | --- |
| 1 | Buscadores | Um arquivo por fonte; se a fonte cai ou bloqueia, avisa em vez de inventar número | `app/providers/`, `app/http.py`, `app/cache.py` |
| 2 | Coordenação | Chama os buscadores a cada 15 min e grava o histórico | `app/services/` |
| 3 | Cálculos | Índice, alta estimada por produto, fila, dólar, filtro de notícias; sem internet nem banco | `app/domain/`, `app/series_utils.py` |
| 4 | Servidor | Liga tudo e responde em `/api/...`; configurações | `app/main.py`, `app/config.py`, `app/schemas.py`, `run.py` |
| 5 | Painel | Sete abas, gráficos e textos | `app/static/` |
| 6 | Testes | Conferem contas e buscadores automaticamente | `tests/` |
| 7 | Documentação | README e política de fontes | `README.md`, `docs/fontes.md` |

---

## As oito funções

Cada função é um agente (uma sessão Claude Code). A função **é dona** de algumas
pastas: só ela edita esses arquivos. Precisa de mudança fora da sua área? Faz
um pedido ao dono (veja "Como os agentes conversam").

| Função | É dona de | Parte do projeto | Edita código? |
| --- | --- | --- | --- |
| **Coordenador** | `docs/agentes/quadro.md`, `README.md`, `docs/fontes.md` | — | não edita o app; despacha com `SendMessage` e só faz commit com sua aprovação |
| **Dados** | `app/providers/`, `app/http.py`, `app/cache.py` | 1 Buscadores | sim |
| **Modelo** | `app/domain/`, `app/series_utils.py` | 3 Cálculos | sim |
| **Backend** | `app/main.py`, `app/config.py`, `app/schemas.py`, `app/services/`, `run.py`, `.env.example`, `requirements.txt`, `requirements-dev.txt` | 2 Coordenação, 4 Servidor | sim |
| **Frontend** | `app/static/` | 5 Painel | sim |
| **QA** | `tests/` | 6 Testes | só testes |
| **Segurança** | nenhum arquivo de código | revisa 1, 4 e 5 | não; só relata |
| **Documentação** | `README.md`, `docs/fontes.md` | 7 Documentação | só docs; desde 10/11/2026 fica com o Coordenador, salvo se você abrir a sessão só para ela |

Se você tiver menos agentes, junte funções vizinhas: **Dados + Backend**,
**Frontend + QA visual**, **Segurança + Documentação**. O Coordenador pode ser
você.

### Como montar os painéis

Cada função é uma sessão do Claude Code nomeada `DSH / <Função>` na pasta do
projeto. Não há herdr, terminal fixo, script de registro nem comando de
assunção.

1. Abra uma sessão por função e cole como primeira mensagem o conteúdo de
   `.claude/agentes/<função>.md`. O painel fica parado até receber tarefa.
2. Abra a sessão do Coordenador (`DSH / 1`). Ele lê `CLAUDE.md` e não precisa
   de comando ao abrir.
3. Para qualquer pedido, fale só com o Coordenador. Ele descobre quem está vivo
   com `ListAgents`, divide o pedido por função, mostra o plano e manda cada
   parte ao painel dono com `SendMessage`. Quando uma parte depende de outra,
   ele espera a primeira terminar. No fim, pede os testes à QA e devolve um
   resumo único. Se faltar o painel de alguma função, ele avisa qual abrir e
   espera; não cria agentes temporários.

Ao abrir sessões novas, basta colar de novo o prompt da função: quem existe é
quem aparece no `ListAgents`, sem registro a atualizar.

### Arquivos de apoio em `docs/agentes/`

| Arquivo | Quem escreve | Para quê |
| --- | --- | --- |
| `../../CLAUDE.md` | humano | Mapa do projeto, fatias, regras gerais e protocolo do Coordenador |
| `../../.claude/agentes/<funcao>.md` | humano | Prompt curto que transforma a sessão em painel daquela função |
| `quadro.md` | Coordenador | Status de cada tarefa (a fazer, fazendo, feito, bloqueado) |
| `<funcao>.md` (ex.: `dados.md`) | a própria função | Relatório: o que fez, o que descobriu, o que ficou pendente |
| `registro.md` | — | Arquivo morto: histórico do esquema antigo de terminais |

Regras de convivência:

1. Só edite os arquivos da sua função.
2. Precisa de algo fora dela? Peça na resposta ao Coordenador, que repassa ao dono.
3. Ninguém faz commit; o Coordenador só faz com aprovação explícita do usuário.
4. Antes de dizer "feito", rode `python -m pytest tests/ -q`.
5. Ao terminar uma tarefa, atualize seu relatório `docs/agentes/<funcao>.md`.

---

## Ordem de trabalho em três ondas

Na **Onda 1**, todos trabalham em paralelo, sem depender de ninguém. A **Onda 2**
corrige o que a Onda 1 descobriu. A **Onda 3** confere tudo e fecha.

```
Onda 1  ┬ Dados: Comex Stat ─────────────────────┐
        ├ Modelo: fila, pesos, notícias ─────────┤
        ├ QA: testes novos + abrir o painel ─────┼─→ Onda 2 ─→ Onda 3
        ├ Segurança: auditoria ──────────────────┤   correções   QA confere
        └ Documentação: corrigir GDELT ──────────┘               Docs consolida
                                                                 Coordenador integra
```

| ID | Tarefa | Função | Onda | Depende de |
| --- | --- | --- | --- | --- |
| T01 | Corrigir `fontes.md` e README (GDELT, sete vetores, árvore, Linux) | Documentação | 1 | — |
| T02 | Auditoria de segurança nas cinco categorias | Segurança | 1 | — |
| T03 | Abrir as sete abas, testar 900 px e 560 px, teclado e leitor de tela | QA | 1 | — |
| T04 | Testes para Federal Register, USGS, SEC e detecção de bloqueio | QA | 1 | — |
| T05 | Testar o Comex Stat e decidir: religar, substituir ou rejeitar | Dados | 1 | — |
| T06 | Tirar a fila do teto de 100 sem inverter a leitura | Modelo | 1 | — |
| T07 | Comparar altas estimadas com a inflação oficial (IBGE) e revisar pesos | Modelo | 1 | — |
| T08 | Agrupar a mesma notícia em idiomas diferentes | Modelo | 1 | — |
| T09 | Corrigir em `http.py` o que a auditoria apontar | Dados | 2 | T02 |
| T10 | Validar filtros de `/api/history` e limitar `/api/refresh` | Backend | 2 | T02 |
| T11 | Ligar, desligar ou trocar o Comex Stat na configuração | Backend | 2 | T05 |
| T12 | Corrigir os defeitos visuais encontrados | Frontend | 2 | T03 |
| T13 | Corrigir exibição de manchetes se a auditoria apontar | Frontend | 2 | T02 |
| T14 | Teste com a mesma notícia em dois idiomas | QA | 2 | T08 |
| T15 | Teste da nova conta da fila | QA | 2 | T06 |
| T16 | Rodar todos os testes e reabrir o painel | QA | 3 | T09–T15 |
| T17 | Juntar os relatórios no README e no `fontes.md` | Documentação | 3 | T16 |
| T18 | Revisar as mudanças e fazer o commit | Coordenador | 3 | T16, T17 |

Na Onda 1, o Backend e o Frontend ficam livres. Use esse tempo para que leiam
o código da sua área, ou deixe para abrir esses dois painéis só na Onda 2.

---

## Fichas das funções

Resumo de cada papel. O prompt que abre cada painel está em
`.claude/agentes/<funcao>.md`; o mapa e as regras gerais, em `CLAUDE.md`.

### Coordenador

**Missão:** manter o quadro atualizado, repassar pedidos, revisar os diffs e
fazer o commit.
**Tarefas:** T18, além de manter `quadro.md` em dia a cada `/coordenar`.
**Pronto quando:** todas as tarefas estão "feito" e os testes passam.

### Dados

**Missão:** garantir que cada fonte pública seja buscada de forma honesta e
que falhas fiquem visíveis.
**Pode editar:** `app/providers/`, `app/http.py`, `app/cache.py`.
**Tarefas:** T05 (Comex Stat), T09 (correções da auditoria).
**Regras específicas:** nunca contornar bloqueio nem forjar `Origin`/`Referer`
(veja `docs/fontes.md`).
**Pronto quando:** a decisão sobre o Comex Stat está registrada em
`docs/agentes/dados.md` e as correções da auditoria foram feitas.

### Modelo

**Missão:** fazer as contas do índice, da fila e das projeções darem números
que façam sentido.
**Pode editar:** `app/domain/`, `app/series_utils.py`.
**Tarefas:** T06 (fila), T07 (pesos e comparação com IBGE), T08 (notícias
multilíngues).
**Regras específicas:** `app/domain/` nunca acessa internet, banco ou
framework. O teste `test_cambio_nao_entra_na_projecao_global` tem que
continuar passando. Justifique toda mudança de peso.
**Pronto quando:** os valores novos aparecem em `/api/methodology` e a
justificativa está em `docs/agentes/modelo.md`.

### Backend

**Missão:** manter o servidor, a configuração e a coleta periódica estáveis e
protegidas.
**Pode editar:** `app/main.py`, `app/config.py`, `app/schemas.py`,
`app/services/`, `run.py`.
**Tarefas:** T10 (filtros e limite de chamadas), T11 (Comex Stat na
configuração).
**Pronto quando:** os achados da auditoria na sua área estão corrigidos e
registrados em `docs/agentes/backend.md`.

### Frontend

**Missão:** deixar as sete abas corretas, legíveis no celular e acessíveis.
**Pode editar:** `app/static/`.
**Tarefas:** T12 (defeitos visuais), T13 (exibição segura de manchetes).
**Regras específicas:** sem etapa de build; todo texto vindo de fora precisa
ser escapado antes de ir para a tela.
**Pronto quando:** os defeitos dos relatórios da QA e da Segurança estão
corrigidos.

### QA

**Missão:** provar que as coisas funcionam, com testes automáticos e abrindo o
painel de verdade.
**Pode editar:** `tests/`.
**Tarefas:** T03 (abrir o painel), T04 (testes das fontes novas), T14 e T15
(testes das mudanças do Modelo), T16 (verificação final).
**Regras específicas:** nenhum teste pode acessar a internet; use dados de
exemplo locais.
**Pronto quando:** a suíte passa e o relatório tem uma captura de cada aba.

### Segurança

**Missão:** encontrar brechas e explicar como corrigir, sem editar código.
**Pode editar:** só `docs/agentes/seguranca.md`.
**Tarefas:** T02.
**Foco:** títulos e links de notícias exibidos no painel; filtros de
`/api/history`; `/api/refresh` sem limite; segredos no `.env.example`.
**Pronto quando:** cada achado tem gravidade, arquivo, linha e a função dona
da correção.

### Documentação

**Missão:** fazer a documentação dizer a verdade sobre o código.
**Pode editar:** `README.md`, `docs/fontes.md`.
**Tarefas:** T01 (correções imediatas), T17 (consolidação final).
**Pronto quando:** `grep -i gdelt docs/ README.md` só mostra o GDELT como
fonte removida e os relatórios das outras funções estão refletidos no README.

---

## Detalhe das tarefas

**T01 Documentação.** Mover o GDELT para as fontes rejeitadas (bloqueio 429,
04/11/2026); tirá-lo do script de revalidação e da seção "Ruído que não é
bloqueio"; trocar "GDELT" por "feeds RSS" na seção de notícias; incluir Federal
Register, USGS e os 43 feeds RSS nas aprovadas; corrigir "os 6 vetores" para
sete; atualizar a árvore de pastas e a lista de testes; adicionar como rodar
no Linux/macOS.

**T02 Segurança.** As cinco categorias; com atenção a manchetes RSS exibidas
no painel, aos parâmetros `range`, `series` e `bucket` de `/api/history` e ao
`POST /api/refresh` sem autenticação.

**T03 QA visual.** Nenhum erro no console e nenhum gráfico vazio nas sete abas;
sem rolagem lateral em 900 px e 560 px; visual de `editorial.css` em capa,
ranking, evolução e detalhe; navegação por teclado e leitor de tela (Orca).

**T04 QA testes.** Federal Register: aperto (+1), revisão (+0,5) e alívio (−1)
lidos no título. USGS: magnitude ≥ 5,5, raio de 150 km, pico na janela. SEC:
trimestre derivado dos acumulados (Q2 = H1 − Q1) e deduplicação por `filed`.
Detecção de página anti-robô em `get_json`, `post_json` e `get_text`.

**T05 Dados.** Testar a fonte com identificação honesta; conferir se o formato
de pedido do código (`PAYLOAD_VARIANTS`) bate com a resposta real; se seguir
bloqueada, avaliar o UN Comtrade como substituto.

**T06 Modelo.** A fila está em 0,9996 da curva e não mostra mais variação.
Propor escala ou transformação que preserve a regra "mais pressão = número
maior".

**T07 Modelo.** Comparar as altas estimadas com o IPCA de computador, celular
e console (IBGE, agregado 7060) no histórico disponível; revisar pesos e
sensibilidades por produto.

**T08 Modelo.** Medir quantas notícias deixam de ser agrupadas por idioma;
agrupar também por empresas, siglas na bolsa e países, sem serviço pago;
manter os selos "confirmada" e "fonte única".

---

## Como saber se deu certo

As metas são propostas; nenhuma estava definida antes.

| O que medir | Hoje | Meta |
| --- | --- | --- |
| Parte do índice com dado real | 92% | ≥ 90% em quase todos os ciclos da semana |
| Fontes funcionando | 34 de 38 | ≥ 36, com Comex Stat decidido |
| Tempo da primeira coleta | 40 s a 3 min | ≤ 3 min |
| Erros no painel | não medido | nenhum |
| Testes | passando | passando, cobrindo as fontes novas |
| Documentação contradiz o código | sim (GDELT) | não |

## O que pode dar errado

| Risco | O que fazemos |
| --- | --- |
| Dois agentes editam o mesmo arquivo | cada pasta tem uma única função dona |
| Um agente espera outro e fica parado | Onda 1 sem dependências; o Coordenador libera cada parte quando a anterior responde |
| Correções de uma função quebram outra | QA roda a suíte inteira na Onda 3, antes do commit |
| Yahoo é a única fonte de cotações e não é oficial | mostra o último valor marcado como desatualizado |
| Alguém lê o painel como conselho de compra | aviso fixo na tela |

**Perguntas em aberto:** mudar a conta da fila atrapalha comparar com o
histórico antigo? Qual cobertura mínima torna um ciclo confiável? Se o Comex
Stat for rejeitado, apagamos o código?

---

## Apêndice técnico

| ID | Requisito | Onde |
| --- | --- | --- |
| RF-01 | Pressão 0–100 por `50 + 50·tanh(Δ%/escala)`; janela de 30 dias nos sinais diários | `series_utils.py`, `domain/drivers.py` |
| RF-02 | Sete vetores (22/19/15/13/11/10/10%); IPH-Brasil pesa 1,6× o câmbio | `domain/analyzer.py` |
| RF-03 | Projeção 30 dias; câmbio fora da projeção global; repasse de 85% | `domain/ranking.py`, `domain/catalog.py` |
| RF-04 | Fila do consumidor (capex SEC × estoque Micron) | `domain/supply.py`, `providers/sec.py` |
| RF-05 | Cartão "por que o dólar se mexeu" | `domain/fx.py` |
| RF-06 | Manchetes RSS com filtro, deduplicação, corroboração e digest | `providers/news_rss.py`, `domain/news.py`, `services/news.py` |
| RF-07 | Histórico SQLite e reconstrução de até 30 dias | `services/history.py`, `domain/backfill.py` |
| RF-08 | Painel de sete abas, atualização a cada 15 min | `static/*`, `services/progress.py` |
| RF-09 | Endpoints `/api/*` | `main.py` |
| RF-10 | Preço de importação via Comex Stat (desligado) | `providers/comexstat.py` |

Política de fontes (detalhe em `docs/fontes.md`): sem chave de API; sem
captcha; identificação honesta; falha sempre visível; respeito aos limites de
cada fonte; testes sem rede; painel sem etapa de build.

## Como executar e testar

Instale as dependências de `requirements.txt` num ambiente virtual Python e
rode `python run.py`. O painel abre em `http://127.0.0.1:8000`; a porta muda
com `DSH_PORT`. A primeira coleta leva de 40 s a 3 min.

Configuração no `.env` (modelo em `.env.example`): `DSH_ENABLE_KABUM=true`
liga a coleta semanal de preços da KaBuM; `DSH_CONTACT` (opcional) entra no
User-Agent; fontes individuais podem ser desligadas se a rede bloquear algum
domínio.

Testes, todos sem rede: instale `requirements-dev.txt` e rode
`python -m pytest tests/ -q`. Testes ainda não adotados pela QA ficam em
`docs/agentes/testes-pendentes/`.

### Endpoints

| Rota | Função |
| --- | --- |
| `GET /` | Painel |
| `GET /api/snapshot` | Payload completo |
| `GET /api/progress` | Progresso da coleta em andamento |
| `POST /api/refresh` | Nova coleta (não vale para a loja) |
| `GET /api/health` | Cobertura e fontes degradadas |
| `GET /api/sources` | Proveniência de cada fonte |
| `GET /api/supply` | Frentes de oferta (memória, chips, demanda) |
| `GET /api/prices` | Preços da KaBuM por faixa e IPCA por categoria |
| `GET /api/methodology` | Pesos, betas e fórmulas, para auditoria |
| `GET /api/series` | Catálogo do histórico |
| `GET /api/history` | Histórico das séries (`?range=90d&series=iph,iph_br`) |
| `GET /api/cache` | Diagnóstico do cache |
| `GET /docs` | OpenAPI |
