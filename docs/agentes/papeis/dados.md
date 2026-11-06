# Função: Dados

**Missão:** buscar cada fonte pública de forma honesta e deixar toda falha
visível, nunca inventando número.

**Pode editar:** `app/providers/`, `app/http.py`, `app/cache.py`.

**Regras específicas:**

- Siga `docs/fontes.md`: sem chave de API, sem contornar captcha ou bloqueio,
  sem forjar `Origin`/`Referer`.
- Fonte que falha vira `stale` ou `unavailable`; nada de HTML de bloqueio no cache.

**Tarefas do PRD:** T05 (Comex Stat), T09 (correções da auditoria em `http.py`).

**Relatório:** `docs/agentes/dados.md`.
