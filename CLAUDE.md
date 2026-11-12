# DataSearch Hardware — mapa para sessões do Claude

Painel web local (FastAPI + JS puro, sem build) que estima a variação de preços
de hardware no Brasil. Visão geral: `README.md`. Partes do app: `docs/PRD.md`.
Estado das tarefas e decisões do usuário: `docs/agentes/quadro.md`. Histórico
por função: `docs/agentes/<função>.md`.

## Painéis (uma sessão por função)

| Função | Dono de | Relatório |
|---|---|---|
| Dados | `app/providers/`, `app/http.py`, `app/cache.py` | `docs/agentes/dados.md` |
| Modelo | `app/domain/`, `app/series_utils.py` | `docs/agentes/modelo.md` |
| Backend | `app/main.py`, `app/config.py`, `app/schemas.py`, `app/services/`, `run.py`, `.env.example`, `requirements*.txt` | `docs/agentes/backend.md` |
| Frontend | `app/static/` | `docs/agentes/frontend.md` |
| QA | `tests/` (e `docs/agentes/testes-pendentes/`) | `docs/agentes/qa.md` |
| Segurança | nada: só leitura + o próprio relatório | `docs/agentes/seguranca.md` |

O **Coordenador** (sessão `DSH / 1`) não edita código; também cuida da
documentação: `README.md`, `docs/fontes.md`, `docs/agentes/quadro.md`,
`docs/agentes/documentacao.md`.

A Documentação ficou com o Coordenador em 10/11/2026. O prompt avulso
`.claude/agentes/documentacao.md` continua válido se o usuário abrir uma sessão
só para isso; nesse caso o Coordenador não edita `README.md` nem
`docs/fontes.md` na mesma onda.

## Como abrir e retomar

1. Uma sessão do Claude Code por função, nomeada `DSH / <Função>`.
2. Primeira mensagem de cada painel: o conteúdo de `.claude/agentes/<função>.md`.
   O painel fica parado até receber tarefa.
3. O Coordenador descobre quem está vivo com `ListAgents` e despacha com
   `SendMessage` (`notify_when_idle: true`), uma tarefa por painel.
4. Não há herdr, terminal fixo, `hc`, script de registro nem arquivo de sessão:
   quem existe é quem aparece no `ListAgents`. O antigo esquema está só em
   `docs/agentes/registro.md` (arquivo morto).

## Como ler sem gastar tokens

Nunca leia arquivo grande inteiro. Localize com `grep -n "<símbolo>" <arquivo>`
e leia o trecho com `Read` + `offset`/`limit`.

| Arquivo | Linhas | Como fatiar |
|---|---|---|
| `app/static/app.js` | 1.662 | `grep -n "^function\|^async function"`; seção por aba |
| `app/domain/prices.py` | 1.058 | `grep -n "^class\|^def"`; a cesta fica no topo |
| `app/domain/news.py` | 784 | `grep -n "^class\|^def"` |
| `app/services/history.py` | 640 | leia só a função que a tarefa cita |
| `app/main.py` | 634 | `grep -n "@app\\."` para achar a rota |
| `app/providers/sec.py` | 623 | um provider por arquivo; leia o arquivo da fonte |

Os relatórios são longos (`dados.md` tem 1.345 linhas): leia só a seção
`## T##` da tarefa, o "Pedidos" da seção e as "Pendências" do fim.

## Regras

- Edite **só** a sua fatia. Precisa de mudança fora dela? Peça ao Coordenador na
  resposta; não faça.
- Nunca rode git que altere estado (commit, push, checkout, reset, stash) sem
  autorização explícita do usuário.
- Segredos só via `app/config.py` + `.env`. Nenhuma rota devolve token ou senha.
- Nenhuma fonte com chave de API; não contornar captcha, bloqueio nem
  `robots.txt`; falha vira `stale`/`unavailable` e não inventa número.
- `app/domain/` não acessa internet, banco nem framework; a rota só traduz
  HTTP ↔ domínio.
- Não crie subagentes nem painéis temporários.
- Se mexeu em código ou teste: `python -m pytest tests/ -q`; se mexeu em JS:
  `node --check` no arquivo. Defeito fora da sua fatia vira pedido, não conserto.
- Ao terminar, atualize o seu relatório e responda em até 5 linhas: status,
  arquivos, testes, pendências, pedidos.

## Coordenação (sessão `DSH / 1`)

- Mostre o plano (`# · Função · O que faz · Arquivos · Depois de`) e **pare**
  para autorização explícita antes de qualquer `SendMessage`.
- Ordem padrão: Dados → Modelo → Backend → Frontend; QA por último; Segurança
  revisa quando o pedido tocar entrada externa (`app/http.py`, `app/main.py`,
  texto de terceiros na tela).
- Uma tarefa por vez por painel; dependências liberam a próxima. Atualize
  `docs/agentes/quadro.md` a cada resposta (a fazer → fazendo → feito/bloqueado).
- "Pedidos" de uma resposta viram subtarefa do dono.
- Não repasse a um painel nada que esta sessão já negou ou bloqueou.
- Painel ocioso sem responder: cobre uma vez; sem retorno, marque bloqueado.
- Feche com um resumo único (≤5 linhas + tabela, se precisar) e a suíte da QA.
- Commit só com aprovação, depois de mostrar `git status` e `git diff --stat`.

## Estilo

Conciso, conforme `docs/agentes/estilo-conciso.md`: responda primeiro o que foi
pedido em 1–3 frases; relatório ≤5 linhas; sem preâmbulo, sem emoji, sem
bajulação; detalhe só quando o usuário pedir ou houver risco de perda de dado.
