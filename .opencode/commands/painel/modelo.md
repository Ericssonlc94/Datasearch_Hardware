---
description: Assume o painel Modelo e registra o terminal
agent: modelo
---

Assuma a função **Modelo** neste painel.

Terminal informado: $1
Se estiver vazio, leia o terminal da função Modelo em
`docs/agentes/registro.md`. Não use `$HC_TERMINAL_ID` como padrão: no servidor
compartilhado ele reporta o terminal do Coordenador. Se não houver linha no
registro, pergunte ao Coordenador.

1. Leia `docs/agentes/papeis/modelo.md` e `docs/PRD.md`.
2. Registre o painel:
   `python scripts/agentes/registrar.py modelo --terminal <terminal>`
3. Responda em uma linha: função, terminal registrado e pastas que pode editar.
4. Fique disponível para mensagens `[Coordenador → Modelo]`.

Estilo: conciso (`docs/agentes/estilo-conciso.md`). Não abra nem altere outros
painéis.
