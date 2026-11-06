# DataSearch Hardware

Painel web de **análise de tendência de preços de hardware no Brasil**: indica
as variações de alta e baixa de preços com base em fatores econômicos e
geopolíticos. Para isso, são englobados dados públicos sobre chips, dólar,
energia, metais, frete e geopolítica, transformados num índice de pressão de 0 a 100 (acima de 50, tendência de
alta; abaixo, de queda) e estima a variação de preço por tipo de produto nos
próximos 30 dias.

Todas as fontes são públicas. Nenhuma exige cadastro ou chave.

---

## O que o painel responde

- **Os preços vão subir ou cair?** O Índice de Pressão de Hardware (IPH) resume
  a tendência em um número de 0 a 100, com uma versão própria para o Brasil, que
  inclui o efeito do dólar e da importação.
- **Por quê?** Sete fatores explicam a tendência, cada um podendo pressionar
  para cima ou aliviar: alocação de chips entre
  datacenter e consumidor, dólar, Estreito de Ormuz e hélio, terras raras,
  metais e energia, frete e tarifas, e a disputa EUA–China por chips em Taiwan.
- **O que deve subir ou cair?** Um ranking estima a variação em 30 dias para placa de
  vídeo, memória, armazenamento, processador, placa-mãe, fonte, celular,
  notebook, monitor e console.
- **Quanto custa hoje?** Preços reais da KaBuM por faixa (baixo, médio e alto)
  para produtos de grande procura, ao lado da inflação oficial (IPCA) de cada
  categoria.

## As abas

| Aba | Para quê |
| --- | --- |
| **Visão Geral** | Leitura de um minuto: a pressão de hoje, os fatores que mais pesam e os produtos com maior variação estimada. |
| **Detalhes** | Cada fator explicado, com os sinais que o compõem, o dólar, a inflação de eletrônicos e as manchetes relevantes. |
| **Gráficos** | Gráficos interativos da pressão, dos fatores e das estimativas por produto. |
| **Evolução** | O histórico de cada número ao longo do tempo. |
| **Fila** | Se o consumidor está no fim da fila: investimento em IA, receita dos fabricantes de chips e estoque de memória e de chips. |
| **Preços** | **Produtos**: a variação estimada por categoria. **Produtos no mercado**: o preço atual na KaBuM por faixa, com até 3 anúncios de referência por modelo. |
| **Técnico** | Metodologia, pesos, fórmulas e o estado de cada fonte, para quem quer auditar. |

O painel se atualiza sozinho a cada 15 minutos. Os preços da loja são lidos
uma vez por semana.

## De onde vêm os dados

| Assunto | Fontes |
| --- | --- |
| Brasil | Banco Central (dólar, juros, inflação) e IBGE (IPCA por subitem) |
| Economia e commodities | FRED e FMI (preços ao produtor, petróleo, metais, energia, frete) |
| Chips e fabricantes | Relatórios na SEC (NVIDIA, AMD, Intel, Micron e grandes compradores de IA), receita mensal da TSMC e importação de chips (UN Comtrade) |
| Geopolítica | Regras de exportação dos EUA (Federal Register), terremotos perto de fábricas (USGS) e manchetes de veículos selecionados |
| Mercado | Ações e moedas ligadas ao setor (Yahoo Finance) |
| Preço no varejo | KaBuM, por busca pública de produto |

A lista completa, as regras de uso de cada fonte e as fontes descartadas, com
o motivo de cada uma, estão em [`docs/fontes.md`](docs/fontes.md).

## Como ler os números

Todo número do painel é de um destes dois tipos:

- **Dado oficial**: medição de terceiros, como IPCA, cotação do dólar ou
  balanço de empresa.
- **Estimativa nossa**: resultado do modelo do painel, como o índice de
  pressão e as projeções de 30 dias.

Quando uma fonte falha, o painel mostra o último valor válido marcado como
desatualizado e informa quais fontes faltaram. Nenhum buraco é preenchido com
suposição.

## Limites

- O preço de varejo vem de **uma única loja**. É um termômetro do mercado, não
  a média de todas as lojas.
- Os pesos e as sensibilidades do modelo são estimativas de ordem de grandeza.
  Estão expostos na aba Técnico justamente para serem questionados.
- A variação de preço na loja só aparece depois de algumas semanas de coleta.

## Para quem desenvolve

Estrutura do projeto, papéis da equipe, como executar e testar: [`docs/PRD.md`](docs/PRD.md).
Registros de cada área: [`docs/agentes/`](docs/agentes/).

---

**Aviso.** Índices e projeções deste painel vêm de um modelo próprio. Não são
previsão validada nem recomendação de compra.
