# Registro de painéis

Cada painel que roda `/assumir-funcao <função>` grava aqui uma linha com o nome
da própria sessão. O `/coordenar` usa este arquivo para saber para quem mandar.
Os nomes mudam a cada sessão nova; a linha antiga da mesma função é substituída.

Formato: `- <Função> = <nome da sessão> (desde AAAA-MM-DD HH:MM)`

## Painéis
- Coordenador = coordenador (desde 2026-11-05 09:28)
- Dados + Modelo = dados e modelo (desde 2026-11-05 15:14)
- Modelo = fechado em 2026-11-05 (absorvido por "dados e modelo")
- Backend = backend (desde 2026-11-05 15:14)
- Frontend = frontend (desde 2026-11-05 15:14)
- QA = qa (desde 2026-11-05 15:14)
- Documentação = fechado em 2026-11-05 (fontes.md com Dados; README com o Coordenador)
- Segurança = seguranca (desde 2026-11-05 15:14)

## Como retomar (herdr)

Cada painel retoma a própria conversa com `claude --resume <id>` e depois roda
`/assumir-funcao <função>` e `/rename <função>` (digitado, não colado).

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
