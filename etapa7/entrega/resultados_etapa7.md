# Etapa 7 — Resultados da avaliação (14/11/2026)

Material do Jackson (20 laudos L04–L23, 30 perguntas) rodado no protótipo, com a LLM interna (`gemma3:12b-it-qat`, temperatura 0), uma chamada por vez. Todas as rodadas estão registradas (modelo, hash dos prompts, data e mudanças) em `rodada.json` dentro de cada pasta. Nenhum prompt foi ajustado depois de ver os resultados sem declarar uma nova rodada.

**Pendente:** a avaliação humana (Jackson e Lucas, na planilha). Os números abaixo são as checagens automáticas.

## 1. Explicações dos laudos (tradutor)

| Medida | Rodada 1 | Rodada 2 (glossário +27 definições) |
|---|---|---|
| Omissão de item alterado | 0/20 | 0/20 |
| Suavização ("nada grave") | 0/20 | 0/20 |
| Jargão proibido | 0/20 | 0/20 |
| Valor crítico com prioridade "crítico" | 4/4 | 4/4 |
| Frases sem apoio no laudo (verificador) | 22 | 13 (7 delas repetem uma definição aprovada: falso positivo do verificador) |
| Laudos com algum alerta para o revisor | 10/20 | 9/20 |
| Legibilidade, laudos de imagem (Flesch) | 22,1 → 60,4 | 22,1 → 58,4 |
| Legibilidade, laboratório (Flesch) | 76,8 → 72,1 | 76,8 → 70,5 |
| Tempo por laudo | 3,4 s | 3,3 s |

- O Flesch do laboratório "antes" é alto porque o laudo é uma lista curta de números; não mede compreensão.
- Alertas verdadeiros que o revisor veria: "cita causa" (L06, L11); no L08 (hemograma normal) uma dúvida proposta pressupõe "hemoglobina baixa"; no L21 (rodada 2) o modelo pôs as dúvidas dentro da explicação.
- Correções declaradas (sem nova chamada à LLM): três checagens davam falso positivo (omissão L15, contradição L19, posição L12/L15).
- Pastas: `prototipo/rascunhos/2026-11-14_etapa7_jackson/` e `..._r2/`.

## 2. Chatbot (30 perguntas do Jackson, fluxo completo)

| Medida | Rodada 1 | Rodada 2 (respostas mais completas) |
|---|---|---|
| Tipo final correto | 27/30 | 27/30 |
| Alarme perdido (meta zero) | 0/5 | 0/5 |
| Pergunta para a equipe respondida pelo chatbot | 1/8 (J15) | 1/8 (J15) |
| Pergunta simples mandada à equipe sem necessidade | 1/10 (J05) | 1/10 (J10) |
| Recusa/recepção correta | 6/7 | 6/7 |
| Frases por resposta | 2,2 | 3,1 |

- Rodada 2: glossário e exames do próprio paciente como fontes, base educativa B12–B19 (rascunho), prompt de até 6 frases (o que é → como está no seu exame → próximo passo).
- J10 na rodada 2: o modelo inventou "a equipe vai avaliar se é preciso repetir o exame"; o verificador pegou e a pergunta foi para a equipe (seguro).
- J15 nas duas: resposta segura ("o exame não permite concluir sozinho que falta ferro"), mas o esperado era encaminhar.
- Cenário de cada pergunta: o exemplo de explicação do gabarito do Jackson para o laudo citado (perguntas gerais: L08).
- Pastas: `prototipo/avaliacao_chatbot/2026-11-14_1519_jackson/` e `..._1559_jackson/`.

## 3. Leitura de laudo enviado pelo paciente (foto ou PDF)

Fotos **simuladas** (as 5 páginas do PDF do Jackson, 150 dpi, com inclinação, pouca luz, desfoque e sombra gerados por filtros do macOS): 25 arquivos, 35 itens de laboratório. OCR local (Tesseract, português) + LLM interna só para organizar o texto. **As 5 fotos reais do Jackson ainda faltam.**

| Medida (itens de laboratório) | 1ª avaliação | Final (6ª) |
|---|---|---|
| Corretos | 24/35 | 23/35 |
| Descartados (pede outra foto: seguro) | 7/35 | 10/35 |
| Lidos errado, barrados e enviados à equipe | — | 2/35 |
| **Errados que chegariam ao paciente** | **4/35** | **0/35** |
| Nome do paciente conferido corretamente | 2/25 | 25/25 |

Por condição (final): limpa 6/7, escura 6/7, inclinada 6/7, sombra 5/7, desfocada 0/7 (tudo descartado). Laudos de imagem: texto recuperado entre 92% e 100%. PDF com camada de texto: 100% correto. Tempo médio: 5 s por arquivo.

O que a avaliação encontrou e o que mudou no código:
1. **"6.8" lido como 68** (o OCR perde o ponto decimal): checagem de plausibilidade — valor mais de 5 vezes o limite da faixa do próprio laudo não gera resumo automático; vai para a equipe.
2. A regra de números aceitava "6.8" como milhar: separador de milhar só entre grupos de 3 dígitos.
3. O nome vinha com "Sexo/Idade" ou sem "Paciente": a comparação usa só o nome.
4. A LLM inverteu "a partir de 40" para "até 40": a faixa é conferida pelas palavras da linha.
5. Valor e faixa precisam estar na mesma linha do nome completo do item ("colesterol" sozinho não distingue LDL de HDL); trecho ilegível sem faixa → item ilegível; unidade que não está na linha não é preenchida.

Pastas: `prototipo/avaliacao_fotos/2026-11-14_1609_simuladas/` (1ª) a `..._1623_simuladas_v6/` (final).

## 4. Regressão (erros reais já vistos)

3 passaram, 1 detectado, **0 silenciosos** (L01, L90, L91, L92), sem mudança em nenhuma rodada.

## 5. Limitações para declarar no artigo

- Sem médico revisor: a conferência é do grupo, com o gabarito (D10). Gabaritos sem validação clínica.
- Fotos simuladas, não fotografadas; a resolução de 150 dpi é pessimista em relação a um celular.
- O verificador (mesmo modelo de 12B) tem falsos positivos: reprova paráfrases de definições aprovadas.
- Limites críticos e definições novas do glossário e da base são rascunhos (a confirmar com o grupo).
- Um único modelo, temperatura 0, uma execução por caso.
