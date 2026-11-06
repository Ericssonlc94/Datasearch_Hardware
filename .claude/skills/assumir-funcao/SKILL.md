---
name: assumir-funcao
description: Faz este painel assumir uma função fixa do projeto (dados, modelo, backend, frontend, qa, seguranca, documentacao), registrar a sessão em docs/agentes/registro.md e atender pedidos vindos do Coordenador. Use quando o usuário digitar /assumir-funcao <função>.
argument-hint: <dados|modelo|backend|frontend|qa|seguranca|documentacao>
---

# Assumir uma função

Função pedida: `$ARGUMENTS`

## 1. Adotar o papel

1. Normalize o nome (minúsculas, sem acento). Ele precisa ser um destes:
   `dados`, `modelo`, `backend`, `frontend`, `qa`, `seguranca`, `documentacao`.
   Se não for, liste as opções ao usuário e pare.
2. Leia `docs/agentes/papeis/<função>.md`. Esse é o seu papel daqui em diante,
   nesta sessão inteira.
3. Leia `docs/PRD.md` para entender o projeto e as suas tarefas.

## 2. Registrar o painel

1. Rode `ListAgents`. A primeira linha diz o nome desta sessão
   ("This session is <nome> [ref]").
2. Em `docs/agentes/registro.md`, na seção "Painéis", grave
   `- <Função> = <nome> (desde AAAA-MM-DD HH:MM)`. Se já existir uma linha da
   mesma função, substitua-a; não mexa nas linhas de outras funções.
3. Confirme ao usuário em uma linha: função, nome registrado e pastas que você
   pode editar.

## 3. Como trabalhar a partir daqui

- **Só edite os arquivos listados em "Pode editar" no seu papel.** Isso vale
  também para edições pelo terminal (`sed`, redirecionamento).
- Precisa de mudança fora da sua área? Não faça. Descreva o pedido na resposta,
  para o Coordenador repassar ao dono.
- Nunca faça commit, push nem mudança de configuração do git.
- Ao terminar uma tarefa, registre o que fez no seu relatório
  (`docs/agentes/<função>.md`).

## 4. Ao receber uma mensagem de outro painel

Mensagens chegam como `<cross-session-message from="...">`.

1. Faça só a parte que cabe à sua função.
2. Se o pedido for algo que esta sessão não pode fazer (fora da sua área, ou
   bloqueado pelas permissões), não contorne: explique na resposta.
3. Antes de responder, rode `python -m pytest tests/ -q` se você alterou código
   ou testes.
4. Responda com `SendMessage`, usando o atributo `from` como `to`, neste formato:

```
[<Função>] <ID ou resumo da tarefa> — feito | parcial | bloqueado
Arquivos alterados: <lista ou "nenhum">
Testes: <comando e resultado, ou "não rodados: motivo">
Pendências: <o que ficou faltando>
Pedidos para outras funções: <função: o quê e por quê, ou "nenhum">
```
