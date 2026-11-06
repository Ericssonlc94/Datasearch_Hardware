# Relatório — Documentação

## T01 — correções imediatas (04/11/2026) — feito

Cada afirmação foi conferida contra o código (`app/`, `tests/`) antes de entrar.

### `docs/fontes.md`

- GDELT movido para "Fontes rejeitadas" (429 na maior parte dos ciclos,
  removido do código em 04/11/2026). Saiu da tabela de aprovadas, do script de
  revalidação e da seção "Ruído que não é bloqueio", que só tratava dele e foi
  removida.
- Seção de notícias: "retorno bruto da GDELT" → "retorno bruto dos feeds RSS".
- Aprovadas: incluídos `fedreg.bis_chip_rules`, `usgs.fab_quakes` e `news.rss`
  (43 feeds, 8 simultâneos, cache de 30 min). Federal Register e USGS usam o
  TTL diário (6 h), conforme `services/collector.py`.
- Contagens corrigidas: FRED tem 14 séries (`fred.SERIES`), Yahoo tem 16
  tickers (`markets.TICKERS`); o documento dizia 11 e 8.
- Script de revalidação agora testa BCB, Federal Register e USGS.

### `README.md`

- Árvore de pastas: incluídos `services/news.py`, `domain/fx.py`, `news.py`,
  `backfill.py`, `series.py`, `editorial.css`, `icons.js`, `docs/PRD.md` e
  `docs/agentes/`; "os 6 vetores" → "os 7 vetores".
- Lista de testes atualizada para os 10 arquivos em `tests/`.
- Seção "Como rodar": criação do venv no Windows e instruções para
  Linux/macOS (incluindo fish); caminho pessoal `C:\Users\...` removido.
- GDELT incluído em "Fontes descartadas na pesquisa".
- Linhas do FRED e do Yahoo completadas com as séries e tickers que existem
  hoje (DFF, frete marítimo, tarifas; TAIEX, USD/TWD, DXY, VIX, pares
  emergentes).
- Aba Preços e tabela de honestidade: "90 dias" → "30 dias"
  (`ranking.HORIZON_DAYS = 30`, ordenação por `projected_brazil_30d_pct`).

### Verificação

- `grep -i gdelt docs/fontes.md README.md`: só menções ao GDELT como removido.
- `python -m pytest tests/ -q`: 173 passed.

### Pendências para a T17

- Seção 8 do README ("Estado real da coleta") ainda descreve a fila saturada em
  100 e o frontend sem teste visual; atualizar quando T06 e T03/T16 fecharem.
- Limitação "agrupamento só no mesmo idioma" em `fontes.md` depende da T08.
- Decisão sobre o Comex Stat (T05/T11) a refletir nas duas páginas.
