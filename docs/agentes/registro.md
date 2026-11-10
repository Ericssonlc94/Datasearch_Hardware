# Registro de painéis

Cada painel grava aqui a própria linha ao assumir a função. O Coordenador lê
este arquivo e `hc ls` antes de despachar. Cada painel só altera a própria
linha; não mexa nas linhas das outras funções.

Formato: `- <Função> = terminal <tN> · sessão <ses_id> (desde AAAA-MM-DD HH:MM)`

## Painéis
- Coordenador (+Documentação) = terminal t10 · sessão bfeda321-49ff-4f18-a714-277467b17cc2 (desde 2026-11-10 11:40)
- Dados = terminal t1 · sessão 45a82ff0-c3d9-41d2-a92c-a9afb6d4ee0d (desde 2026-11-10 11:40)
- Modelo = terminal t3 · sessão 597ba87c-2d5c-44c9-99aa-ef4538c64fa6 (desde 2026-11-10 11:40)
- Backend = terminal t2 · sessão 96cff875-4a3e-46b1-8f61-9d9f1b228314 (desde 2026-11-10 11:40)
- Frontend = terminal t6 · sessão 0c377e37-0701-410d-970b-31505f2d0d1f (desde 2026-11-10 11:40)
- QA = terminal t7 · sessão 18ac3ba8-6b7a-48df-8187-03e588aaaa78 (desde 2026-11-10 11:40)
- Segurança = terminal t12 · sessão 326ca5a8-1d4b-4d8f-af09-d75c92694979 (desde 2026-11-10 11:40)

Todos em Claude Code desde 10/11 11:40. Retomar num terminal fish com `hc keys`
tecla a tecla: `claude --resume <sessão>`, depois `/assumir-funcao <função>`.
As sessões OpenCode (ses_…) de 10/11 10:20 ficam só como histórico;
`scripts/agentes/retomar.py` reabre essas.

## Como retomar (herdr + OpenCode)

1. Em cada aba do herdr, abra o OpenCode:

   ```sh
   opencode
   ```

2. Na TUI, assuma a função (o terminal vai como argumento):

   ```
   /painel/<função> <tN>
   ```

   Exemplos: `/painel/coordenador t10`, `/painel/dados t1`,
   `/painel/modelo t3`, `/painel/backend t2`, `/painel/frontend t6`,
   `/painel/qa t7`, `/painel/seguranca <tN>`.

3. Para abrir todos de uma vez, com autorização do usuário, no Coordenador:

   ```
   /paineis/abrir
   ```

4. `hc ls` mostra os terminais vivos; `hc get <tN>` mostra o estado de um.

O registro é por terminal, não por sessão: se o core do herdr reiniciar e os
IDs mudarem, rode `/painel/<função>` de novo em cada aba.

## Histórico (Claude Code, até 05/11/2026)

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
