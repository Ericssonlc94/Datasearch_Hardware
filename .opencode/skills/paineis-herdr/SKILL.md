---
name: paineis-herdr
description: Abre, registra, verifica e derruba os painéis fixos do projeto no herdr, com hc e opencode. Use no Coordenador quando o usuário autorizar abrir ou conferir os painéis.
---

# Painéis no herdr

Os painéis são terminais fixos do herdr, um por função. O mapa oficial fica em
`docs/agentes/registro.md`.

| Função | Terminal | Comando |
| --- | --- | --- |
| Coordenador (+Documentação) | t10 | `/painel/coordenador t10` |
| Dados | t1 | `/painel/dados` |
| Modelo | t3 | `/painel/modelo` |
| Backend | t2 | `/painel/backend` |
| Frontend | t6 | `/painel/frontend` |
| QA | t7 | `/painel/qa` |
| Segurança | aba nova | `/painel/seguranca` |

## Abrir do jeito padrão

Com autorização do usuário, rode:

```sh
python scripts/agentes/abrir.py
```

O script, para cada função:

1. cria uma sessão OpenCode com o agente já definido e a localização do repo;
2. abre `opencode --session <id>` no terminal combinado (ou cria a aba
   "Segurança" com `herdr-app do tab.new`);
3. registra `Função = terminal tN · sessão <id>` no `registro.md`;
4. envia o prompt de adoção (`/painel/<função>` equivalente) pela API.

Para abrir só alguns: `python scripts/agentes/abrir.py dados qa`.
Para conferir sem abrir: `python scripts/agentes/abrir.py --dry-run`.

## Abrir um painel manualmente

No terminal da função:

```sh
opencode
```

E, na TUI, digite:

```
/painel/<função> <tN>
```

O comando troca o agente da sessão, lê o papel e registra o terminal.

## Verificar e falar

```sh
hc ls                 # terminais vivos, com labels e status
hc get t1             # estado, foreground e cwd de um terminal
hc read t1 --lines 40 # tela + histórico
hc send t1 "texto"    # digita e dá Enter no painel
```

Respostas dos painéis chegam na sessão do Coordenador como `[<Função>] ...`.

## Cuidados

- **Não reinicie o herdr** nem mate terminais sem o usuário pedir.
- `hc send` digita no programa em foco: só mande com o painel ocioso. Se o
  terminal estiver ocupado, espere ou use `hc get` para conferir.
- No servidor compartilhado do OpenCode, `$HC_TERMINAL_ID` aponta para o
  terminal do Coordenador. Sempre passe o terminal explícito para
  `scripts/agentes/registrar.py`.
- Se o core do herdr reiniciar e os IDs mudarem, rode `/painel/<função>` de
  novo em cada aba para re-registrar.
- Um painel por terminal; não abra dois agentes no mesmo terminal.
