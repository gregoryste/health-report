# Texto técnico para o artigo (proposta técnica, avaliação, riscos)

Material da implementação para o Lucas transformar em texto corrido. Os números vêm das rodadas do protótipo em 14/11/2026, com laudos fictícios. As decisões citadas (D1–D13) estão no `plano.md`.

**Redação:** usar "explica", "comunica", "traduz". Evitar "interpreta", "diagnostica", "recomenda tratamento" (D9). **Não citar o nome da empresa** (D11).

---

## 1. Arquitetura (figuras)

As figuras estão em `etapa5/diagramas/`, em PNG para o artigo e os slides e em SVG para editar.

- **Figura 1 (`1_visao_geral.png`): visão geral.**
  - O laudo chega do sistema de exames da clínica ou como foto.
  - Tudo é processado na infraestrutura própria: regra fixa, OCR, LLM interna e bases curadas rodam no serviço do protótipo; o n8n recebe os eventos e agenda as rotinas.
  - Profissionais aprovam o que vai ao paciente. O paciente é atendido pelo WhatsApp, depois de se identificar (CPF, data de nascimento e número cadastrado) e aceitar o termo (D3, 2ª revisão, a confirmar pelo grupo). O desenho anterior previa um portal com login; ele está desligado.
  - ⚠️ As figuras 1 e 2 ainda mostram o portal; precisam ser redesenhadas se a 2ª revisão da D3 for aceita.
  - Cores: verde é regra/código, azul é IA generativa, laranja é decisão humana, cinza são dados.
- **Figura 2 (`2_pista_do_laudo.png`): da chegada do laudo à publicação**, com os pontos de checagem e a aprovação obrigatória.
- **Figura 3 (`3_pista_da_duvida.png`): da pergunta no chat à resposta**, com os destinos a–e.

**Papel do n8n:** é o orquestrador e decide o **caminho** de cada resultado. As **regras** ficam num lugar só, o serviço do protótipo: regra fixa, LLM, checagens, classificador da dúvida, RAG e envio de mensagens. O serviço executa a etapa e devolve os fatos (prioridade do laudo, tipo final da dúvida, status do envio). O n8n lê esses fatos num nó IF ou Switch, visível no editor, e chama a ação do ramo escolhido. São 5 fluxos (Figura 4, `4_fluxos_n8n.png`):
- **entrada do laudo:** o sistema de exames chama o webhook `laudo` → o serviço aplica a regra, gera o rascunho, roda as checagens e devolve a prioridade → **IF crítico** → alerta de contato ativo no painel (D3: ligar no mesmo dia, sem depender do paciente);
- **publicação:** quando um profissional aprova, o serviço chama o webhook `laudo-aprovado` → aviso genérico pelo WhatsApp → **IF o aviso não saiu** → alerta "Falha no envio" no painel, para a equipe reenviar;
- **pista da dúvida:** a pergunta do paciente identificado chega ao webhook `duvida` → o serviço encadeia filtro de alarme → classificador → contexto → resposta → verificação e devolve o tipo final → **Switch com 5 saídas (a–e)**; a saída d abre o alerta de urgência, as outras só devolvem a resposta (c já está na fila de triagem);
- **rotinas:** todo dia às 8h (ou sob demanda) → prazos de aprovação e lembretes de leitura (D6) → **IF houve alerta de prazo** → "Resumo do dia" com as contagens no histórico de execuções;
- **erros:** se qualquer um dos quatro falhar (serviço fora do ar, tempo esgotado, resposta de erro), o n8n dispara este fluxo, que abre no painel o alerta "Falha de orquestração". O texto do alerta é curto: nome do fluxo, nó e 1ª linha da mensagem, sem dado de saúde. Falha técnica aparece em âmbar, separada dos alertas clínicos.

**Novas tentativas:** só nos nós que não chamam a LLM (aviso, rotinas e ações: 3 tentativas, a cada 2 s; aviso de falha: 5 tentativas, a cada 5 s). Os nós que geram o rascunho e respondem a dúvida nunca repetem, para não chamar a LLM duas vezes, e esperam até 120 s. As rotas de ação são idempotentes: repetir a chamada não duplica o alerta.

**Uma tabela, dois executores:** o mesmo roteamento existe no serviço, na tabela `ROTAS` (`app/servico.py`), usada quando `ORQUESTRADOR=interno` (plano B da demo). Assim o n8n não é indispensável: sem ele, o serviço chega exatamente ao mesmo estado (alertas, fila, avisos), o que foi conferido com a mesma cena nos dois modos. O teste `testes/teste_rotas_n8n.py` lê os JSON dos fluxos e falha se os ramos do n8n e a tabela `ROTAS` deixarem de bater.

O que o n8n acrescenta: porta de entrada padronizada para outros sistemas, agendamento, decisões e fluxo visíveis no editor para quem não programa, tratamento de erros e histórico de execuções com o caminho seguido. Ficam fora do n8n a identificação e o termo no WhatsApp, o menu de dúvidas, a leitura de foto ou PDF enviados pelo paciente e a tela de aprovação.

**Entrada do laudo (D7, proposta a confirmar):** quando o laudo é liberado, o sistema de exames chama um webhook do n8n (HTTP POST, JSON).
- Exame de laboratório: itens estruturados (analito, valor, unidade, faixa de referência).
- Laudo de imagem: texto livre.
- Se o sistema só entregar PDF, extrai-se o texto do PDF digital, sem OCR.
- Foto em papel: OCR local → texto → a LLM estrutura o laudo (seção 4).

## 2. Modelo e justificativa (ponto 3 do enunciado)

**Modelo:** `gemma3:12b-it-qat` (Google Gemma 3, 12 bilhões de parâmetros, pesos abertos, quantizado), servido por uma LLM interna em **servidor próprio**, fora da nuvem.

| Critério | Justificativa |
|---|---|
| Privacidade | Nenhum dado de saúde sai da infraestrutura própria (LGPD art. 11 e art. 33, *confirmar*). Evita a transferência internacional que um modelo em nuvem exigiria (D3) |
| Qualidade | Nos laudos de teste, citou todos os itens alterados após as correções, em bom português. Na comparação preliminar de 13/11 entre 4 modelos abertos (Qwen3 8B, Llama 3.1 8B, Gemma 3 12B, Qwen2.5-VL 7B), foi o que mais seguiu o formato pedido. *Ressalva: essa comparação usou o prompt antigo* |
| Custo | Custo marginal quase zero na infraestrutura existente (ver `custos.md`) |
| Tempo | ~4 s por explicação |

**Infraestrutura:** citar o modelo e o tipo de servidor. A especificação atual na D11 é **fictícia** e precisa ser trocada pela real antes da entrega.

## 3. Dados e como chegam ao modelo (ponto 2 do enunciado, D2)

| Dado | Como chega ao modelo | Contém dado pessoal? |
|---|---|---|
| Laudo do paciente | Inteiro, no contexto, por consulta direta | Sim, e nunca entra em busca semântica |
| Explicação e dúvidas aprovadas do paciente | No contexto do chatbot, por consulta direta | Sim, idem |
| Glossário de termos (definições aprovadas) | Só os termos presentes no laudo vão na mensagem | Não |
| Exemplos de explicações aprovadas (E1) | Busca por tipo de exame e achado; anonimizados | Não |
| Base da clínica (preparo, orientações) | RAG (busca lexical BM25 no protótipo) | Não |

**Regra derivada:** nenhuma busca semântica roda sobre dado identificável de paciente.

## 4. Pista do laudo (Figura 2)

1. **Regra fixa (D4):** compara cada valor com a faixa de referência e marca alto, baixo ou crítico. Também define a prioridade e o prazo de revisão. Num laudo de imagem, a regra não tem como saber o que está alterado; essa parte cabe à IA.
2. **Mensagem ao modelo:**
   - os resultados já marcados pela regra;
   - o tom definido pela prioridade;
   - as definições do glossário;
   - um exemplo aprovado (E1), quando houver um parecido;
   - instruções específicas para laudo de imagem e para escores, só quando se aplicam.
3. **LLM:** escreve a explicação (80–180 palavras) e 3–5 dúvidas prováveis com resposta (F1).
4. **Pós-processamento pelo código:**
   - frases fixas (fecho orientando a procurar o médico, aviso de contato no laudo crítico, menção à classificação do laudo);
   - nomes de escores ocultados ("TI-RADS 4" vira "a classificação do laudo");
   - resposta que cita causa ou prognóstico vira resposta fixa.
5. **Checagens:** omissão, números fora do laudo, posição e lado, contradição com a regra, jargão, alertas.
6. **Verificação de apoio** frase a frase por uma segunda chamada à LLM (padrão: laudos de imagem).
7. **Revisão humana obrigatória**, com motivo obrigatório no descarte. Cada ação é registrada: original, versão final, revisor, tempo e tamanho da edição. Nada vai ao paciente sem essa ação.
8. **Publicação** e aviso genérico pelo WhatsApp ("responda OI nesta conversa"); a explicação é entregue na conversa depois da identificação e do termo. No laudo crítico, a equipe faz contato ativo no mesmo dia.

**Foto ou PDF do laudo (etapa 4, implementada em 14/11, no WhatsApp):** a rota da LLM interna não aceita imagem (testado). O fluxo é:
- OCR local (Tesseract) → texto + confiança por palavra;
- a LLM estrutura o texto em JSON;
- número que não está no texto do OCR é rejeitado;
- campo de baixa confiança vira "ilegível", e o laudo não segue sozinho.

## 5. Pista da dúvida (Figura 3, D1)

| Tipo | O que é | O que o sistema faz |
|---|---|---|
| a | Esclarecer o que já foi aprovado | Responde só com o conteúdo aprovado, citando a fonte |
| b | Orientação geral | Responde com a base da clínica, citando a fonte |
| c | Diagnóstico, conduta, remédio | Rascunho → fila de triagem (enfermagem; ato médico vai ao médico). Paciente recebe mensagem fixa |
| d | Alarme | Mensagem fixa (SAMU 192; CVV 188 se houver risco de suicídio) + alerta imediato à equipe |
| e | Fora do escopo ou manipulação | Recepção ou recusa, com mensagem fixa |

**Salvaguardas:**
- uma lista de alarme sem LLM vem antes de tudo;
- o classificador da LLM também detecta alarme, como redundância;
- na resposta a ou b, uma proteção fixa contra causa e prognóstico e um verificador (apoio nas fontes e pertinência). Qualquer falha manda a pergunta para a equipe;
- sofrimento emocional recebe prioridade e mensagem acolhedora;
- logística fora da base vai para a recepção.

## 6. Defesa em camadas contra alucinação (para "riscos")

**Princípio:** não dá para impedir o modelo de errar; dá para impedir que o erro chegue ao paciente sem ser visto.

| Camada | O que faz |
|---|---|
| Regra fixa | Valores alterados, prioridade e omissão, de forma determinística |
| Glossário controlado | O modelo explica os termos com definições aprovadas, não com o próprio conhecimento |
| Checagens determinísticas | Números, posição e lado, contradição com a regra, jargão |
| Menos liberdade | Temperatura 0, frases e respostas fixas, escores ocultados |
| Verificação de apoio | Uma segunda chamada julga cada frase |
| Revisão humana | Obrigatória, com alertas destacados |
| Regressão | Erros reais viram teste fixo, avaliado em três estados: passou, detectado, silencioso |

**Métrica de segurança proposta:** zero erros **silenciosos**, ou seja, erro que chega ao revisor sem nenhum alerta. Não é zero erros.

## 7. Resultados preliminares do protótipo

*Laudos fictícios, avaliação sem médico (D10). São resultados ilustrativos, não definitivos.*

**Tradutor (6 laudos: laboratório comum, normal, crítico, imagem, achado incidental, alteração leve):**
- nenhuma omissão nem suavização depois das correções;
- legibilidade (Flesch adaptado) nos laudos de imagem: 39 → 58 e 47 → 62–68;
- **E1 (exemplo aprovado no prompt):** no L04, Flesch de 47 sem exemplo para 60 com exemplo, e o texto parou de copiar medidas e jargão;
- **regressão dos casos reais:** 3 passaram, 1 detectado, **0 silenciosos**.

**Chatbot (22 perguntas da seção 3 do plano; os exemplos do prompt são outros, sem vazamento):**

| Métrica (D5) | Resultado |
|---|---|
| Alarme perdido | **0/3**, todos pegos pela lista, sem LLM |
| Pergunta clínica respondida sem passar pela equipe | **0/9** |
| Pergunta mandada à equipe sem necessidade | 0/7 |
| Recusa (inclusive injeção de prompt) e recepção | 2/2 |
| Acolhimento com prioridade | 1/1 |
| Acurácia geral | 19/22 (os erros restantes são a×b, sem efeito na resposta) |

**Ressalva de método:** as 22 perguntas orientaram ajustes do sistema. A medida sem viés vem das perguntas novas do Jackson, usadas como conjunto separado.

## 8. Casos de alucinação observados (D13): bons exemplos para o artigo e o pitch

1. **Escore interpretado:** "TI-RADS 4 significa risco baixo, mas requer acompanhamento". O texto errou o risco e recomendou conduta.
2. **Classificação inventada:** "o laudo traz uma classificação que o médico vai explicar", num exame de sangue sem classificação. Causa: uma regra de prompt mal posicionada.
3. **Tradução errada de termo técnico:** "terço distal do ureter" virou "a parte mais distante da bexiga". Distal, no ureter, é a parte perto da bexiga. **Passou por todas as checagens que existiam na época.** Hoje é pego pela checagem de posição e evitado pelo glossário.
4. **Contaminação pelo exemplo:** num check-up normal, "a glicose está acima da faixa: 88 mg/dL, e o esperado vai até 99". O texto copiou a estrutura de um exemplo aprovado de glicose alta. Hoje é pego pela checagem de contradição com a regra.
5. **(Chatbot) Resposta fiel que não responde:** para "Esqueci o jejum, o resultado pode estar errado?", o sistema respondeu "sua glicose está dentro do esperado". É verdade, mas desvia e soa como tranquilização. O verificador do mesmo modelo aprovou. A correção foi estrutural.

**Lição:** com temperatura 0, o mesmo tipo de erro volta quando a mensagem muda pouco. Por isso a revisão humana é obrigatória, e a métrica é "zero erros silenciosos".

## 9. Limitações (declarar no artigo)

- **Sem validação clínica:** a avaliação foi feita pelo grupo, contra o gabarito (D10). A validação por profissionais de saúde fica como trabalho futuro.
- **Laudo de imagem:** a checagem automática de omissão só existe no teste, com gabarito. Em produção, quem garante é o revisor.
- **Juiz do mesmo modelo:** o verificador usa o mesmo modelo de 12B, que tem falsos positivos e negativos e foi condescendente ao julgar pertinência.
- **Glossário, base da clínica e listas de jargão:** são provisórios, escritos pelo grupo e não validados clinicamente.
- **Legibilidade:** o Flesch mede a forma do texto, não a compreensão. Em exame de sangue, o laudo original é uma tabela, então só os laudos de imagem permitem comparar o antes e o depois.
- **Especificação do servidor:** fictícia até ser substituída (D11).
- **Leitura de fotos:** desenhada (OCR local + LLM em texto), mas não implementada no protótipo.

## 10. Custo

Ver `etapa5/custos.md`. **Resumo:** o custo de IA é pequeno. Na infraestrutura existente, fica em ~R$ 12/mês para 200 laudos, e quem domina é o WhatsApp. O argumento para o servidor próprio é a privacidade, não o custo.
