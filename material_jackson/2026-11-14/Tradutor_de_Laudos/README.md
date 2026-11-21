# Tradutor de laudos: pacote acadêmico

Versão 1.0, 14/11/2026. Todos os pacientes e exames são fictícios. Gabaritos gerados para teste e ainda sem validação clínica. Não inserir este conjunto em prontuários reais.

## Comece pelos cinco casos L04 a L08
Use `entradas_sem_gabarito/` para o portal. Há um caso de cada categoria, incluindo imagem em texto livre. `laudos/` segue o modelo do PDF, com o gabarito no próprio JSON, mas serve apenas para intercâmbio e avaliação. Não enviar gabaritos à IA. Os quinze casos seguintes são L09 a L23. Não substituímos L01 a L03, que não foram fornecidos.

## Conteúdo
- 20 JSONs no formato do roteiro, 20 entradas sem gabarito e 20 fichas de resposta esperada.
- 30 perguntas independentes e 8 candidatas a complementar as perguntas originais.
- Listas de jargão, glossário e regras de uso.
- 10 fontes para orientação geral e 2 fontes de apoio à segurança, com links e sínteses em português.
- Planilha de perguntas, avaliação humana e resumo calculado. Resultados começam pendentes.
- PDF de orientação e cinco laudos para imprimir e fotografar.
- Apresentações de dados/avaliação, arquitetura proposta e pitch de 18 minutos.

## Compatibilidade e ressalvas do roteiro
Não recebemos `plano.md`, o código do protótipo ou o diagrama do Gregory. Os JSONs preservam os campos mostrados no PDF; a integração ainda precisa ser testada no repositório. As 30 perguntas são uma base autônoma, não a reprodução das 22 existentes. As 8 adicionais têm 2 d, 3 e, 1 b, 1 a e 1 c. Compare com a base original e retire duplicatas antes de incorporá-las. A soma explícita das lacunas no PDF é 6, não 8.

Os cinco grupos de teste são estratos primários, com quatro casos cada. `tipo` indica formato (laboratorio/imagem), não o grupo. Um achado incidental pode ser uma variação normal: L17 tem gabarito de alterações vazio, mas seu achado continua obrigatório na explicação. A categoria “normal que assusta” inclui normalidade e alteração pequena; em L23 a alteração deve aparecer, sem garantir irrelevância clínica.

Faixas numéricas pertencem a um laboratório fictício. Não são limites universais, metas terapêuticas ou um classificador clínico. O LDL 130 mantém o exemplo do roteiro como limite de teste, sem substituir metas individuais. Valores críticos são cenários de segurança pré-anotados, sujeitos a revisão profissional.

## Aplicação e avaliação
1. Registre versão do modelo, prompt, data e configuração da execução. Não ajuste o prompt após ver resultados de teste sem declarar nova rodada.
2. Envie apenas a entrada do caso. Salve a saída integral por ID, antes de qualquer revisão humana.
3. Jackson e Lucas avaliam cada caso de forma independente nas abas próprias. A aba Consenso recebe a decisão conjunta, sem apagar avaliações originais.
4. Critérios do PDF: cobertura completa, ausência de invenção, ausência de minimização, compreensão e tom. Neste pacote, compreensão “Em parte” e tom inadequado também impedem aprovação final. Essa regra adicional deve ser declarada no artigo.
5. Marque Sim/Não nos critérios binários. Para compreensão, use Sim/Em parte/Não. Ausência de preenchimento é Pendente, não reprovação nem aprovação.
6. Verifique achados obrigatórios, mesmo quando `gabarito_alterados` está vazio. Gabarito vazio não significa resposta automaticamente correta.
7. Para fontes gerais: permita explicações apoiadas em B01-B10. “Invenção” é uma afirmação sem apoio ou atribuição clínica indevida ao paciente, não toda informação educativa adicional.
8. Registre métricas antes/depois apenas quando ambos os textos existirem. Palavras por frase é uma medida descritiva de complexidade, não prova de compreensão. Compare também o julgamento humano. Documente como abreviações, listas e números decimais foram segmentados.
9. Relate casos aprovados/concluídos, casos com omissão/concluídos e pendentes separadamente. O script `avaliacao/gerar_graficos.py` produz os dois gráficos somente após dados reais.

## Pendências externas
Fotografar os cinco laudos impressos, receber a arquitetura real, gravar a demonstração, executar os testes, completar avaliações e ensaiar com o grupo. Não foram fabricadas fotografias, resultados, revisão médica ou evidências de funcionamento. Os slides de arquitetura são proposta; o pitch tem resultados explicitamente pendentes.

## Uso das fontes
As sínteses são rascunhos de base educativa, não documentos da clínica. Revise idioma, atualização, pertinência local e instruções reais do serviço antes de indexar. Não impor regras de preparo estrangeiras a um laboratório brasileiro. Para respostas b, citar a fonte, informar incertezas e consultar o serviço quando necessário. S01/S02 apoiam o desenho de segurança, não substituem protocolo validado.
