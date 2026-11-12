# Registro de painéis — arquivo morto

Histórico do esquema antigo, em que cada painel era um terminal do herdr com
sessão registrada à mão em `docs/agentes/registro.md`. Desde 11/11/2026 os
painéis são sessões do Claude Code nomeadas `DSH / <Função>`, com o prompt de
`.claude/agentes/<função>.md` e o mapa em `CLAUDE.md`. Não há mais terminal,
`hc`, script de registro nem `SendMessage` por nome de sessão registrado: o
Coordenador usa `ListAgents` para ver quem está vivo.

O que existia e foi removido em 11/11/2026: `scripts/agentes/` (abrir,
herdr_status, registrar, responder, retomar), `.opencode/agents/`,
`.opencode/commands/painel/*`, `.opencode/commands/paineis/abrir.md`,
`.opencode/skills/` e as skills `.claude/skills/assumir-funcao` e
`.claude/skills/coordenar`. O histórico de trabalho de cada função continua nos
relatórios `docs/agentes/<função>.md` e no `docs/agentes/quadro.md`.

## Último estado do esquema herdr (10/11/2026 11:40)

- Coordenador (+Documentação) = terminal t10 · sessão bfeda321-49ff-4f18-a714-277467b17cc2
- Dados = terminal t1 · sessão 45a82ff0-c3d9-41d2-a92c-a9afb6d4ee0d
- Modelo = terminal t3 · sessão 597ba87c-2d5c-44c9-99aa-ef4538c64fa6
- Backend = terminal t2 · sessão 96cff875-4a3e-46b1-8f61-9d9f1b228314
- Frontend = terminal t6 · sessão 0c377e37-0701-410d-970b-31505f2d0d1f
- QA = terminal t7 · sessão 18ac3ba8-6b7a-48df-8187-03e588aaaa78
- Segurança = terminal t12 · sessão 326ca5a8-1d4b-4d8f-af09-d75c92694979

Todos em Claude Code. As sessões OpenCode (`ses_…`) de 10/11 10:20 e o script
`scripts/agentes/retomar.py` ficaram só como histórico; o script foi removido.

## Sessões Claude Code anteriores (até 05/11/2026)

| Função | Painel herdr | Terminal | Sessão (id) |
| --- | --- | --- | --- |
| Coordenador | 1 | t10 | ef5a40c7-f52c-41b7-a2a2-e148f39069e3 |
| Dados e modelo | 2 | t1 | 45a82ff0-c3d9-41d2-a92c-a9afb6d4ee0d |
| Modelo | 3 | t5 | 597ba87c-2d5c-44c9-99aa-ef4538c64fa6 |
| Backend | 4 | t2 | 96cff875-4a3e-46b1-8f61-9d9f1b228314 |
| Frontend | 3 | t3 | 0c377e37-0701-410d-970b-31505f2d0d1f |
| QA | 6 | t6 | 18ac3ba8-6b7a-48df-8187-03e588aaaa78 |
| Segurança | 7 | t7 | 326ca5a8-1d4b-4d8f-af09-d75c92694979 |
| Documentação | 8 | t8 | ca51e4f4-d70d-4d69-beaa-ba969b183509 |

Sessões do Claude Code não são retomadas pelo OpenCode; ficam como referência.
