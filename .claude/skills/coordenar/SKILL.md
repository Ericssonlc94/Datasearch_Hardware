---
name: coordenar
description: Coordena os painéis fixos do projeto (um agente por função). Divide um pedido do usuário por função, envia cada parte ao painel dono com SendMessage, acompanha as respostas e devolve um resumo único. Use quando o usuário digitar /coordenar <pedido> ou pedir uma mudança que envolva mais de uma função.
argument-hint: <pedido em linguagem natural>
---

# Coordenar os painéis

Pedido: `$ARGUMENTS`

Leia `docs/agentes/papeis/coordenador.md`: esse é o seu papel. Você **não edita
código** e **não cria subagentes**. Os agentes de cada função são painéis fixos
que o usuário abriu.

## 1. Ver quem está disponível

1. Leia `docs/agentes/registro.md` (função → nome da sessão).
2. Rode `ListAgents` e cruze: uma função só está disponível se o nome
   registrado aparece vivo na lista.

## 2. Dividir o pedido

1. Leia a tabela "As oito funções" em `docs/PRD.md` para saber o dono de cada
   pasta. Se precisar, abra os arquivos para entender o que o pedido envolve.
2. Monte as subtarefas, uma por função, cada uma com os arquivos que ela vai
   tocar. Uma subtarefa nunca inclui arquivos de outra função.
3. Ordem padrão de dependência: **Dados → Modelo → Backend → Frontend**. A QA
   vem sempre por último. Inclua a Segurança como revisora quando o pedido
   mexer com entrada externa (`app/http.py`, `app/main.py`, texto de terceiros
   exibido no painel). Inclua a Documentação quando o comportamento visível
   ou as fontes mudarem.
4. Subtarefas sem dependência entre si podem ir em paralelo.

## 3. Mostrar o plano

Antes de enviar, mostre ao usuário uma tabela curta:
`# · Função · O que faz · Arquivos · Depois de`. Em seguida, siga sem esperar
confirmação, a menos que o pedido seja ambíguo ou destrutivo.

Se alguma função necessária não tiver painel disponível, diga qual abrir
(`/assumir-funcao <função>` num painel novo) e **pare até o usuário avisar**.

## 4. Enviar

Para cada subtarefa liberada, use `SendMessage` com `to` = nome registrado e
`notify_when_idle: true`. A primeira linha da mensagem resume a tarefa. Modelo:

```
[Coordenador → <Função>] <resumo em uma linha>
Contexto: <pedido original do usuário, em uma frase>
Sua parte: <o que fazer>
Arquivos: <somente os da sua área>
Pronto quando: <critério objetivo>
Responda no formato do /assumir-funcao.
```

Registre a subtarefa em `docs/agentes/quadro.md` como "fazendo".

## 5. Acompanhar

- As respostas chegam como `<cross-session-message>`. Não fique perguntando
  "terminou?" nem rodando `ListAgents` em loop; o aviso de ociosidade chega sozinho.
- Ao receber cada resposta, atualize o quadro e libere as subtarefas que
  dependiam dela.
- "Pedidos para outras funções" na resposta viram novas subtarefas para o dono
  (volte ao passo 4).
- Painel ficou ocioso sem responder? Peça a resposta uma única vez. Sem retorno,
  marque como "bloqueado" e avise o usuário.

## 6. Fechar

1. Envie à QA: rodar `python -m pytest tests/ -q` e, se o painel visual mudou,
   conferir as abas afetadas.
2. Responda ao usuário com um resumo único: o que cada função fez, os arquivos
   alterados, o resultado dos testes e o que ficou pendente.
3. Commit só se o usuário aprovar explicitamente, mostrando antes o
   `git status` e o `git diff --stat`.
