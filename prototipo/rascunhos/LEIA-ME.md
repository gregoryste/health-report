# Rascunhos gerados

Cada pasta é uma rodada do tradutor, com o rascunho de cada laudo (`L*.json`), o resumo das checagens (`resumo.csv`)
e o registro da rodada (`rodada.json`: modelo, hash dos prompts, data e mudanças).

- `2026-11-14_etapa7_jackson/` e `2026-11-14_etapa7_jackson_r2/`: rodadas 1 e 2 da avaliação da etapa 7 (20 laudos).
- `regressao_2026-11-14_1204_L92/`: conjunto de regressão (erros reais transformados em casos fixos).

Para refazer só o pós-processamento, sem chamar a LLM: `tradutor.py --reprocessar <pasta>`.
