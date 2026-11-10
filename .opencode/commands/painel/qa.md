---
description: Assume o painel QA e registra o terminal
agent: qa
---

Assuma a função **QA** neste painel.

Terminal informado: $1
Se estiver vazio, leia o terminal da função QA em
`docs/agentes/registro.md`. Não use `$HC_TERMINAL_ID` como padrão: no servidor
compartilhado ele reporta o terminal do Coordenador. Se não houver linha no
registro, pergunte ao Coordenador.

1. Leia `docs/agentes/papeis/qa.md` e `docs/PRD.md`.
2. Registre o painel:
   `python scripts/agentes/registrar.py qa --terminal <terminal>`
3. Responda em uma linha: função, terminal registrado e pastas que pode editar.
4. Fique disponível para mensagens `[Coordenador → QA]`.

Estilo: conciso (`docs/agentes/estilo-conciso.md`). Não abra nem altere outros
painéis.
