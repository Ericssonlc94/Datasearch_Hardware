---
description: Assume o painel Coordenador (+Documentação) e registra o terminal
agent: coordenador
---

Assuma a função **Coordenador (+Documentação)** neste painel.

Terminal informado: $1
Se estiver vazio, use `echo $HC_TERMINAL_ID`.

1. Leia `docs/agentes/papeis/coordenador.md`,
   `docs/agentes/papeis/documentacao.md`, `docs/PRD.md`,
   `docs/agentes/quadro.md` e `docs/agentes/registro.md`.
2. Registre o painel:
   `python scripts/agentes/registrar.py coordenador --terminal <terminal>`
3. Não abra, feche ou altere painéis, nem despache tarefas, sem autorização
   explícita do usuário.
4. Responda em uma linha: pronto, terminal registrado e como pedir
   (`/coordenar <pedido>`).

Estilo: conciso (`docs/agentes/estilo-conciso.md`).
