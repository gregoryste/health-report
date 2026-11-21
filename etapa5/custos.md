# Custo estimado (D8)

Para a seção de proposta técnica e para "Aplicabilidade e impacto" do artigo. O cálculo está em [custos.py](custos.py): todos os parâmetros ficam no topo e dá para rodar de novo com outros valores.

Data do levantamento: 14/11/2026.

## Conclusão em uma frase

**O custo de IA é pequeno em qualquer cenário. O que justifica rodar o modelo na infraestrutura própria é a privacidade (LGPD), não o custo.** Para uma clínica que já tem o servidor, o custo marginal é quase zero. Para uma clínica sem servidor, comprar uma GPU custa mais do que usar um modelo em nuvem nesses volumes, mas a nuvem exigiria tratar a transferência de dado de saúde para fora da clínica (D3).

## Volume considerado

Dois cenários, com pressupostos do grupo:
- **200 laudos/mês**, o exemplo do plano;
- **1.000 laudos/mês**.

Em ambos, 1 pergunta no chat por laudo e 30% de laudos de imagem, que recebem a verificação de apoio. 60% das perguntas são respondidas pelo chatbot; as outras viram rascunho para a equipe.

Tokens por chamada **medidos** nas rodadas do protótipo:
- o tradutor usa ~1.040 tokens de entrada e ~350 de saída por laudo;
- uma chamada leva ~4 s.

O servidor interno não informa tokens, então foram estimados a partir dos caracteres, com cerca de 3,6 caracteres por token.

| | 200 laudos/mês | 1.000 laudos/mês |
|---|---|---|
| Tokens de entrada | 0,78 milhão | 3,91 milhões |
| Tokens de saída | 0,12 milhão | 0,60 milhão |
| Tempo de GPU ocupada | 0,6 h | 3,2 h |

## Visão 1: infraestrutura atual (servidor próprio já existente)

| Item | Custo mensal (200 / 1.000 laudos) | Observação |
|---|---|---|
| LLM interna: energia sob carga | R$ 0,46 / R$ 2,32 | ~0,6 kW enquanto gera, a R$ 1,23/kWh |
| GPU e servidor | R$ 0 marginal | Já existem; o consumo ocioso já é pago hoje |
| n8n | R$ 0 | Edição comunitária, instalada no próprio servidor, uso interno |
| OCR (Tesseract) | R$ 0 | Software livre, roda local |
| WhatsApp (avisos genéricos) | R$ 11,91 / R$ 59,53 | 340 / 1.700 mensagens de utilidade a US$ 0,0068 (aviso por laudo, lembretes, aviso de resposta da fila) |
| **Total de infraestrutura** | **~R$ 12 / ~R$ 62** | Dominado pelo WhatsApp, não pela IA |
| Tempo da equipe | **principal custo, não estimado** | Revisão dos rascunhos e fila de triagem. Medir em produção (D6, D10) |

## Visão 2: clínica sem infraestrutura

| Item | Valor | Observação |
|---|---|---|
| GPU (RTX 5090, 32 GB) | ~R$ 27.800 → **R$ 772/mês** em 36 meses | A RTX 4090 está esgotada no varejo. Mediana de 12 meses num agregador de preços |
| Demais componentes do servidor | **a cotar** | CPU, 64 GB de RAM, SSD, fonte, nobreak. Não estimado para não inventar valor |
| Energia ociosa (24 h) | a estimar com o servidor escolhido | Passa a ser custo da clínica |
| n8n, OCR, WhatsApp | iguais à visão 1 | |

## Comparação: o mesmo volume com um modelo em nuvem

Preços por milhão de tokens (entrada / saída), tabela da Anthropic de 03/11/2026: Claude Haiku 5.5 a US$ 0,10 / 0,50; Claude Sonnet 5.5 a US$ 2 / 10.

| Modelo em nuvem | 200 laudos/mês | 1.000 laudos/mês |
|---|---|---|
| Claude Haiku 5.5 | R$ 0,71 | R$ 3,55 |
| Claude Sonnet 5.5 | R$ 14,20 | R$ 71,00 |

**Leitura para o artigo:**
- Nesses volumes, a nuvem é mais barata do que comprar uma GPU (R$ 772/mês só de amortização).
- O argumento a favor do servidor próprio, portanto, **não é custo**. É que o laudo e a explicação são dado de saúde (LGPD, art. 11). Mandar esses dados para um provedor em nuvem, em geral fora do país, seria transferência internacional de dado sensível (art. 33) e exigiria base legal, contrato e consentimento específicos. O servidor próprio elimina esse problema.
- Para uma clínica que já tem o servidor (visão 1), a escolha é ao mesmo tempo a mais barata e a mais segura.
- *Confirmar os artigos da LGPD antes de citar (pendente do Lucas).*

## Fontes e ressalvas

| Valor | Fonte | Ressalva |
|---|---|---|
| Câmbio R$ 5,15 | [Meelion, 16/09/2026](https://www.meelion.com/indicadores-financeiros/dolar-hoje/) | Último valor encontrado. Usar a PTAX do Banco Central na data do artigo |
| Energia R$ 0,945/kWh sem impostos | [Calculadora Energia: RGE Sul](https://calculadoraenergia.com.br/tarifa/rge-sul), vigente desde 19/06/2026; [reajuste da RGE (Jornal do Comércio)](https://www.jornaldocomercio.com/economia/2026/06/1252633-aneel-confirma-reajuste-medio-de-1606-nas-contas-de-luz-da-cpfl-rge.html) | Tarifa B1. A fonte afirma que o B3 comercial é igual; não confirmado na ANEEL. Somados ~30% de impostos (estimativa). Confirmar a distribuidora de São Leopoldo. Efeito desprezível no resultado |
| WhatsApp US$ 0,0068 por mensagem de utilidade (Brasil, desde 01/10/2026) | [Hyperleap](https://hyperleap.ai/whatsapp-pricing-calculator-brazil); [AiSensy](https://m.aisensy.com/blog/pt/atualizacao-preco-whatsapp-api-outubro-2026/); [Zenvia](https://zenvia.movidesk.com/kb/en/article/600343/frequently-asked-questions-new-whatsapp-business-pricing-rules-2) | Fontes de provedores, não a tabela oficial da Meta. Provedores cobram 10–30% a mais |
| RTX 5090 ~R$ 27.800 | [GPUPrix: RTX 5090 no Brasil](https://gpuprix.com/pt/br/gpus/geforce-rtx-5090); [Hardware.com.br](https://www.hardware.com.br/noticias/rtx-5090-preco-sugerido-brasil.html) | Mediana de 12 meses. O preço atual varia entre ~R$ 27 mil e R$ 34,5 mil |
| n8n gratuito para uso interno | [FAQ da licença do n8n](https://docs.n8n.io/n8n-community-license/community-license/license-faq) | Uso interno da clínica está coberto. Revender o n8n hospedado para terceiros, não |
| Preços do Claude | Documentação da Anthropic (cache de 03/11/2026) | Escolhidos só como referência de nuvem |

**Pressupostos a declarar no artigo:**
- os volumes (200 e 1.000 laudos/mês);
- 1 pergunta por laudo;
- 30% de laudos de imagem;
- 60% de perguntas respondidas pelo chatbot;
- 0,3 lembrete por laudo;
- potência de 0,6 kW sob carga;
- tokens estimados por caracteres;
- **especificação do servidor fictícia (D11)**: a visão 1 não depende dela, mas a visão 2 sim.
