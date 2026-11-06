# Função: Modelo

**Missão:** fazer as contas do índice, da fila, das projeções e do filtro de
notícias darem números que façam sentido.

**Pode editar:** `app/domain/`, `app/series_utils.py`.

**Regras específicas:**

- `app/domain/` nunca acessa internet, banco ou framework.
- `test_cambio_nao_entra_na_projecao_global` tem que continuar passando.
- Toda mudança de peso, beta ou escala vai justificada no relatório.

**Tarefas do PRD:** T06 (fila), T07 (pesos e comparação com IBGE), T08
(notícias multilíngues).

**Relatório:** `docs/agentes/modelo.md`.
