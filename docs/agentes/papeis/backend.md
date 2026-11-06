# Função: Backend

**Missão:** manter o servidor, a configuração e a coleta periódica estáveis e
protegidas.

**Pode editar:** `app/main.py`, `app/config.py`, `app/schemas.py`,
`app/services/`, `run.py`, `.env.example`, `requirements.txt`, `requirements-dev.txt`.

**Regras específicas:**

- Erro interno nunca vaza stack trace para o cliente.
- Parâmetro de rota é validado contra lista permitida antes de chegar ao banco.

**Tarefas do PRD:** T10 (filtros de `/api/history` e limite de `/api/refresh`),
T11 (Comex Stat na configuração).

**Relatório:** `docs/agentes/backend.md`.
