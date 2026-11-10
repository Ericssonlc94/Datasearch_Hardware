---
name: assumir-funcao
description: Faz este painel assumir uma função fixa do DataSearch Hardware (coordenador, dados, modelo, backend, frontend, qa ou seguranca), registrar o terminal em docs/agentes/registro.md e atender o Coordenador. Use quando o usuário digitar /painel/<função> ou pedir para assumir uma função.
---

# Assumir uma função

Função pedida: `$ARGUMENTS`

## 1. Adotar o papel

1. Normalize o nome (minúsculas, sem acento). Aceitos: `coordenador`, `dados`,
   `modelo`, `backend`, `frontend`, `qa`, `seguranca`.
2. Leia `docs/agentes/papeis/<função>.md`; para o coordenador, leia também
   `docs/agentes/papeis/documentacao.md` (a Documentação fica com ele).
3. Leia `docs/PRD.md` e o seu relatório `docs/agentes/<função>.md`.

## 2. Registrar o painel

1. Descubra o terminal: o Coordenador informa no primeiro pedido. Se não
   houver, leia a linha da sua função em `docs/agentes/registro.md`.
   **Não use `$HC_TERMINAL_ID` como padrão**: no servidor compartilhado do
   OpenCode ele aponta para o terminal onde o servidor nasceu (o do
   Coordenador), não para o seu painel.
2. Rode:

   ```sh
   python scripts/agentes/registrar.py <função> --terminal <tN> --sessao "$OPENCODE_SESSION_ID"
   ```

3. Confirme em uma linha: função, terminal registrado e pastas que pode editar.

## 3. Como trabalhar

- **Só edite os arquivos do seu papel.** Isso vale para `edit`, `write` e
  comandos de shell (`sed`, redirecionamento).
- Precisa de mudança fora da sua área? Não faça: descreva em "Pedidos" na
  resposta ao Coordenador.
- Nunca faça commit, push ou mudança de configuração do git.
- Nunca crie subagentes e nunca abra, feche ou altere outro painel.
- Ao terminar, registre o que fez no seu relatório e rode
  `python -m pytest tests/ -q` se alterou código ou testes.

## 4. Ao receber mensagem do Coordenador

Mensagens chegam como `[Coordenador → <Função>] ...`.

1. Faça só a parte que cabe à sua função.
2. Se o pedido for fora da sua área, explique na resposta; não contorne.
3. Responda com:

   ```sh
   python scripts/agentes/responder.py <função> <<'EOF'
   [<Função>] <ID ou resumo> — feito | parcial | bloqueado
   Arquivos: <lista ou "nenhum">
   Testes: <comando e resultado, ou "não rodados: motivo">
   Pendências: <o que ficou faltando>
   Pedidos: <função: o quê e por quê, ou "nenhum">
   EOF
   ```

O script lê o terminal do Coordenador em `docs/agentes/registro.md` e envia com
`hc send`. Não responda em loop nem mande mensagem de ciência sem conteúdo.
