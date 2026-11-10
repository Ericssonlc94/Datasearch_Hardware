---
name: coordenar
description: Divide um pedido do usuário por função, mostra o plano, despacha aos painéis com hc send depois da autorização e devolve um resumo único. Use no painel Coordenador quando o usuário digitar /coordenar <pedido>.
---

# Coordenar os painéis

Pedido: `$ARGUMENTS`

Você é o Coordenador (+Documentação). Não edite código e não crie subagentes.

## 1. Ver quem está disponível

1. Leia `docs/agentes/registro.md` (função → terminal).
2. Rode `hc ls` e cruze: a função só está disponível se o terminal registrado
   está `live`. `hc get <tN>` mostra o estado de um terminal.

## 2. Dividir o pedido

1. Use a tabela "As oito funções" de `docs/PRD.md` para saber o dono de cada
   pasta. Abra os arquivos se precisar entender o pedido.
2. Monte as subtarefas, uma por função, com os arquivos que ela vai tocar. Uma
   subtarefa nunca inclui arquivos de outra função.
3. Dependência padrão: **Dados → Modelo → Backend → Frontend**. QA por último.
   Segurança revisa quando houver entrada externa; Documentação (você) entra
   quando o comportamento visível ou as fontes mudarem.

## 3. Mostrar o plano e esperar autorização

Mostre uma tabela curta: `# · Função · O que faz · Arquivos · Depois de`.

**Pare aqui.** Só despache depois que o usuário autorizar explicitamente nesta
sessão. Se faltar o painel de alguma função, diga qual abrir
(`/painel/<função>` no terminal) e espere; não invente agente.

## 4. Enviar

Para cada subtarefa liberada:

```sh
hc send <tN> "[Coordenador → <Função>] <resumo em uma linha>
Contexto: <pedido original, em uma frase>
Sua parte: <o que fazer>
Arquivos: <somente os da área dela>
Pronto quando: <critério objetivo>
Responda no formato do /assumir-funcao."
```

Registre a subtarefa em `docs/agentes/quadro.md` como "fazendo".

## 5. Acompanhar

- As respostas chegam como `[<Função>] ...` na sua sessão. Não fique em loop de
  `hc ls`; o painel responde quando termina.
- A cada resposta, atualize o quadro e libere o que dependia dela.
- "Pedidos" na resposta viram nova subtarefa para o dono (volte ao passo 4,
  com autorização se for uma mudança nova).
- Painel ocioso sem responder: cobre uma vez; sem retorno, marque "bloqueado" e
  avise o usuário.

## 6. Fechar

1. Peça à QA `python -m pytest tests/ -q` e, se a tela mudou, a conferência das
   abas afetadas.
2. Responda ao usuário num resumo único: o que cada função fez, arquivos,
   testes e pendências (≤5 linhas + tabela se precisar).
3. Commit só com aprovação explícita, depois de mostrar `git status` e
   `git diff --stat`.
