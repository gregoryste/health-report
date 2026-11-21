# Correções do artigo para ficar fiel ao protótipo

Data: 15/11/2026. Base: esboço do artigo (PDF de 5 páginas), comparado com o protótipo e com os registros.

O esboço descreve o projeto **como ele estava planejado em 12/11**. Em 14/11, três coisas mudaram no que foi construído:

1. **Canal do paciente:** o paciente usa o próprio WhatsApp (com identificação e consentimento). O portal do paciente ficou desligado.
2. **Leitura de fotos:** quem lê a foto é um OCR local (Tesseract), não um VLM.
3. **Modelo:** foi escolhido um modelo único, o Gemma 3 12B, que o artigo não cita.

Além disso, faltam no artigo o custo e os resultados, que já existem.

Cada item abaixo traz **onde** mexer, **o que está escrito hoje**, **o que colocar** e **por quê**. Os textos sugeridos podem ser colados direto e ajustados ao estilo do grupo.

> **Decisões ainda abertas no grupo (resolver antes de editar):**
>
> - **D3, 2ª revisão (WhatsApp como canal do paciente):** foi proposta pelo Gregory e é o que está no protótipo e na demo. Este documento parte do princípio de que o grupo aceita. Se não aceitar, o pitch e a demo é que precisam mudar, não o artigo.
> - **Nomes de produto no artigo** (por exemplo, o nome comercial do sistema de exames): sugestão neutra é "o sistema de exames da clínica". **Nunca citar o nome da empresa** dona do servidor.
> - **Resumo imediato sem IA** para laudo enviado pelo paciente: está implementado, mas ainda depende do aceite do grupo.

---

## 1a. Canal do paciente: de "Portal" para "WhatsApp com consentimento"

### O que o protótipo faz (para conferência)

- **Aviso sem link e sem dado clínico:** "Há uma nova mensagem da clínica para você: responda OI nesta conversa para ver."
- **Identificação na conversa, antes de qualquer dado de saúde:**
  - o paciente informa CPF e data de nascimento;
  - os dois precisam bater com o cadastro, e a mensagem precisa vir do número cadastrado (esse é o segundo fator);
  - 3 erros → bloqueio de 30 min e alerta no painel da equipe;
  - a identificação vale 24 h desde a última mensagem;
  - CPF e data não ficam em texto no registro, e CPF digitado numa pergunta livre vira "[CPF removido]".
- **Termo de consentimento na conversa:**
  - informa que as mensagens passam pelos servidores da Meta, possivelmente fora do Brasil, e que quem tiver acesso ao celular pode lê-las;
  - tem os botões "Sim, autorizo" e "Não autorizo";
  - o aceite fica registrado com data e versão do termo;
  - responder **SAIR** revoga o aceite.
- **Se o paciente não aceita:** nenhum conteúdo de saúde é enviado (o serviço bloqueia) e o resultado é explicado na consulta.
- **Urgência não espera a identificação:** mensagem com sinal de alarme recebe na hora a orientação do SAMU 192 (e do CVV 188, quando for o caso) e gera alerta no painel.
- **Depois do aceite:** o paciente recebe a explicação aprovada e um menu.
  - O menu mostra primeiro as dúvidas antecipadas que têm resposta na hora.
  - As dúvidas que ficam para a consulta oferecem o botão "Enviar à equipe".
  - Perguntas livres passam pelo classificador (tipos a–e).
- **Respostas da fila de triagem** voltam pelo próprio WhatsApp.
- O **painel da equipe** (revisão e aprovação) continua na web, fora do túnel público.

### Trechos a alterar

**Resumo (seção 1)**

- Hoje: "a arquitetura assegura que nenhuma informação de saúde transite pelo WhatsApp (restrito a avisos genéricos), concentrando a interação em um Portal seguro."
- Trocar por: "o paciente recebe a explicação aprovada e tira dúvidas pelo próprio WhatsApp, mas só depois de se identificar (CPF, data de nascimento e número cadastrado) e de autorizar, de forma explícita e revogável, o tráfego dos dados por esse canal. O modelo de linguagem e todo o processamento do laudo ficam na infraestrutura própria, fora da nuvem."

**Objetivos (seção 3), 3º e 4º itens**

- Hoje: "Disponibilizar um chatbot no Portal do paciente…" e "Garantir o sigilo e a LGPD, restringindo o WhatsApp apenas ao envio de avisos genéricos…"
- Trocar por:
  - "Disponibilizar, no WhatsApp do paciente, um chatbot que classifica as dúvidas em cinco tipos (a–e) para responder com base no laudo aprovado e na base da clínica (RAG), encaminhar à equipe ou recusar."
  - "Tratar os dados de saúde conforme a LGPD: processamento e modelo locais; no WhatsApp, só conteúdo já aprovado, depois de identificação e de consentimento específico e destacado (Art. 11, I), com revogação a qualquer momento."

**Fundamentação teórica (seção 4), item "LGPD e Segurança na Saúde"**

- A partir de "O tráfego de laudos via aplicativos de mensageria…" até o fim, trocar por:

> O uso de aplicativos de mensageria como o WhatsApp traz um risco específico: as mensagens enviadas pela API oficial são processadas nos servidores da Meta, possivelmente fora do Brasil, o que configura transferência internacional de dados (Art. 33). Por isso, o sistema separa as duas coisas. O processamento do laudo e o modelo de linguagem ficam na infraestrutura própria. O WhatsApp só recebe conteúdo já aprovado por um profissional, e apenas depois de duas condições:
>
> - **identificação com segundo fator:** CPF e data de nascimento, conferidos com o cadastro, e a mensagem vinda do número cadastrado;
> - **consentimento específico e destacado (Art. 11, I):** o termo informa a passagem pelos servidores da Meta e o fato de que quem tiver acesso ao celular pode ler as mensagens, e o aceite pode ser revogado a qualquer momento.
>
> Sem consentimento, nenhum dado de saúde é enviado.

- **Por quê:** o texto atual diz o contrário do que foi feito. O argumento de **minimização** (Art. 6º, III), "nenhum dado de saúde passa pela Meta", **não vale mais** e precisa sair. No lugar entra o argumento do **consentimento**, com o risco declarado. Conferir a redação exata dos artigos 6º, 11, 33 e 46 antes de citar.

**Proposta técnica (seção 5)**

- Frase de abertura. Hoje: "O sistema repensa a comunicação para eliminar o tráfego de dados no WhatsApp, operando em dois fluxos principais contidos no Portal". Trocar por: "O sistema opera em dois fluxos: o do laudo, que vai da chegada do exame até a aprovação pelo profissional, e o das dúvidas, que acontece no WhatsApp do paciente depois da identificação e do consentimento."
- Fluxo do Laudo, passo "Aviso". Hoje: "Um aviso genérico… é enviado pelo WhatsApp para atrair o paciente ao Portal." Trocar por: "Um aviso genérico, sem link e sem dado clínico, convida o paciente a responder OI. Só depois da identificação e do consentimento ele recebe a explicação aprovada."
- Fluxo de Dúvidas, passo 1. Hoje: "O paciente acessa o Portal e envia perguntas." Trocar por: "O paciente envia perguntas no WhatsApp ou escolhe uma das dúvidas antecipadas no menu. Antes de tudo, uma lista fixa de sinais de alarme verifica a mensagem; urgência recebe na hora a orientação do SAMU 192 e gera alerta à equipe, mesmo sem identificação."
- Mudar o título "Fluxo de Dúvidas (Chatbot no Portal)" para "Fluxo de Dúvidas (Chatbot no WhatsApp)".

**Riscos (seção 7), item "Vazamento de Dados Sensíveis"**

- Hoje: "Sanado pela transferência do fluxo conversacional do WhatsApp para o Portal."
- Trocar por: "Reduzido, não eliminado. O laudo e o modelo nunca saem da infraestrutura própria. No WhatsApp, o paciente só recebe conteúdo aprovado, depois de se identificar com segundo fator (número cadastrado) e de consentir de forma revogável. CPF e data de nascimento não são guardados em texto. Risco que permanece: a passagem pelos servidores da Meta e o acesso de terceiros ao celular, ambos declarados no termo. O portal com login próprio fica como alternativa para quem não quiser usar o WhatsApp."

---

## 1b. "Sem nuvem" × WhatsApp Cloud API

- Em todo o artigo, trocar frases do tipo "nenhum dado sai da clínica" ou "sem nuvem" por **"o modelo e o processamento do laudo rodam na infraestrutura própria"**.
- Deixar explícito que **o canal de entrega (WhatsApp Cloud API) é um serviço de terceiro**, coberto pelo consentimento.
- **Por quê:** a afirmação "elimina o tráfego de dados de saúde em nuvens de terceiros" é falsa com o WhatsApp como canal. O mesmo ajuste vale para os slides 4 e 10 do pitch.

---

## 1c. Leitura de fotos: de VLM para OCR local + LLM

### O que o protótipo faz

```
foto ou PDF ─► texto (PDF com texto: pdftotext; foto/escaneado: Tesseract em português, com confiança por palavra)
            ─► LLM local só organiza o texto em JSON (não lê a imagem)
            ─► checagens determinísticas ─► regra fixa ─► mesmo fluxo dos laudos digitais
```

Checagens determinísticas antes de qualquer resumo:

- todo número precisa existir no texto lido, na mesma linha do nome completo do item;
- a faixa também precisa estar nessa linha e ser coerente com as palavras ("até", "a partir de");
- valor mais de 5 vezes o limite da faixa → nenhum resumo automático; a equipe confere (pega o OCR que perde o ponto decimal, como "6.8" lido como 68);
- trecho ilegível → item marcado como ilegível, nunca inventado;
- o nome no laudo precisa ser o do paciente.

**Por que não VLM:** a rota da LLM interna aceita só texto. Foi testado em 14/11: o campo de imagem é descartado. Usar o Gemma como modelo de visão dependeria de mudar a rota no servidor. O OCR é genérico (não precisa de um modelo por layout), e quem lida com a variação de layout é a LLM, então o argumento contra "um OCR por layout" continua valendo.

### Trechos a alterar

- **Resumo:** "Utilizando VLMs locais para leitura de laudos em papel" → "Utilizando OCR local para leitura de laudos em papel e um LLM local para organizar o texto lido e para gerar as explicações".
- **Palavras-chave:** trocar "VLM" por "OCR".
- **Objetivos, 2º item:** "…usando um VLM local" → "…usando OCR local (Tesseract) e um LLM local apenas para organizar o texto, com checagens determinísticas que impedem valor inventado".
- **Fundamentação, item "Modelos Multimodais (VLM) e LLMs Locais":** mudar o título para "Modelos de Linguagem Locais e Leitura de Documentos". Manter um parágrafo curto sobre VLMs (com a referência Das Joy et al.) como **alternativa avaliada e trabalho futuro**, e explicar o desenho em duas etapas (OCR + LLM) usado no protótipo.
- **Fluxo do Laudo, passo "Entrada e Leitura":** "O VLM local lê a imagem" → "O laudo digital chega do sistema de exames da clínica (no protótipo, laudos fictícios enviados pelo n8n). Se o paciente enviar foto ou PDF pelo WhatsApp, o texto é extraído por OCR local e organizado pelo LLM local, com as checagens descritas acima."
- **Métricas (seção 6):** "Fidelidade da extração das fotos pelo VLM" → "Fidelidade da leitura de fotos (OCR + LLM): valores errados que chegariam ao paciente".
- **Próximos passos:** incluir "testar um VLM local na leitura de fotos e comparar com o OCR".

---

## 1d. Modelo escolhido e justificativa (falta no artigo)

**Onde:** criar uma subseção na seção 5, "Modelo e componentes", logo antes dos fluxos.

**Texto sugerido:**

> **Modelo.** O sistema usa um único modelo de linguagem, o Gemma 3 12B (Google), de pesos abertos, na versão quantizada (`gemma3:12b-it-qat`). Ele roda num servidor próprio, fora da nuvem, com temperatura 0. A escolha considerou:
>
> - **privacidade:** os pesos abertos permitem rodar o modelo localmente, sem enviar o laudo a uma API comercial;
> - **custo:** a infraestrutura já existe, então só há custo marginal;
> - **qualidade:** bom português e nenhuma omissão nos testes;
> - **tempo:** cerca de 3,4 s por laudo.
>
> Numa comparação preliminar entre quatro modelos locais (Qwen3 8B, Llama 3.1 8B, Gemma 3 12B e Qwen2.5-VL 7B), feita em 13/11 com uma versão anterior do prompt, o Gemma foi o que mais seguiu o formato pedido.
>
> **Componentes:**
>
> - **serviço central em FastAPI**, com banco SQLite e o painel da equipe para revisão e aprovação;
> - **n8n como orquestrador**, com 5 fluxos: entrada do laudo, publicação, dúvidas, rotinas (lembretes e prazos) e tratamento de erros. O n8n decide o caminho; o serviço decide o conteúdo;
> - **OCR local** (Tesseract);
> - **WhatsApp Cloud API** como canal do paciente.

**Também acrescentar na seção 5 as camadas de segurança do fluxo do laudo** (hoje só a regra fixa aparece no artigo):  
0. regra fixa (valores alterados e prioridade, sem IA);

1. glossário de definições aprovadas;
2. checagem numérica (bloqueia número que não existe no laudo);
3. baixa liberdade: temperatura 0, frases fixas e escores técnicos ocultados pelo código (por exemplo, "TI-RADS 4" vira "a classificação do laudo");
4. verificação de apoio: uma segunda chamada ao LLM confere se cada frase tem apoio no laudo (no protótipo, só em laudos de imagem);
5. revisão humana obrigatória;
6. testes de regressão com erros reais já vistos.

**RAG:** dizer como funciona.

- A base da clínica (textos educativos B01–B19) e o glossário são buscados por **busca lexical BM25**.
- Os dados do próprio paciente (laudo aprovado e exames) entram **direto no contexto**, sem busca semântica sobre dados identificáveis.

**Matriz de Competências:** acrescentar uma frase de fidelidade.

- No protótipo, o classificador sugere o destino (enfermagem ou médico) e o painel tem as funções médico(a), enfermagem e administrador(a).
- Hoje as três funções veem e fazem o mesmo no painel, e a avaliação do destino é provisória.
- A matriz é o **desenho proposto** para a operação real.

---

## 1e. Custo e resultados (faltam no artigo)

### Custo: nova subseção no fim da seção 5 (ou dentro de "Viabilidade")

> **Custo estimado** (cálculo reproduzível em `etapa5/custos.py`; câmbio de R$ 5,15 e energia a R$ 1,23/kWh). Pressupostos: 1 pergunta por laudo; tokens medidos no protótipo (cerca de 1.040 de entrada e 350 de saída por laudo).
>
> | | 200 laudos/mês | 1.000 laudos/mês |
> |---|---|---|
> | LLM local (energia sob carga) | R$ 0,46 | R$ 2,32 |
> | n8n e OCR (software livre, no próprio servidor) | R$ 0 | R$ 0 |
> | WhatsApp (mensagens de utilidade) | R$ 11,91 | R$ 59,53 |
> | **Total** | **R$ 12,37** | **R$ 61,85** |
> | Comparação: mesmo volume no Claude Haiku 5.5 (nuvem) | R$ 0,71 | R$ 3,55 |
>
> O custo de IA é pequeno em qualquer cenário: **o que justifica rodar o modelo localmente é a privacidade, não o custo.** Uma clínica sem servidor precisaria de uma GPU (cerca de R$ 772/mês em 36 meses, sem os demais componentes). O maior custo, o tempo da equipe na revisão, não foi estimado e deve ser medido em uso real.

Antes de entregar, conferir câmbio (PTAX), tarifa de energia e preço do WhatsApp na tabela oficial da Meta (pendência registrada em `custos.md`).

### Avaliação: reescrever a seção 6 com conjunto de teste, métrica principal e resultados

**Conjunto de teste:**

- 20 laudos fictícios (L04–L23, quatro por categoria, com gabarito);
- 30 perguntas de pacientes;
- 4 erros reais já vistos (regressão);
- 25 fotos **simuladas** (as 5 páginas de um PDF, degradadas com inclinação, pouca luz, desfoque e sombra).

**Métrica principal:** itens alterados omitidos na explicação (meta: zero).

**Resultados (rodada 2, 14/11/2026, Gemma 3 12B, temperatura 0):**

| Medida | Resultado |
|---|---|
| Omissão de item alterado (**métrica principal**) | **0/20** |
| Suavização ("nada grave") / jargão proibido | 0/20 / 0/20 |
| Valores críticos priorizados como "crítico" | 4/4 |
| Legibilidade dos laudos de imagem (Flesch adaptado) | 22,1 → 58,4 |
| Chatbot: tipo final correto | 27/30 |
| Chatbot: alarme perdido (meta zero) | 0/5 |
| Fotos: valores errados que chegariam ao paciente | 0/35 (23 corretos, 10 descartados, 2 barrados) |
| Regressão: erros reais | 3 passaram, 1 detectado, 0 silenciosos |
| Tempo por laudo | 3,3 s |

**Avaliação qualitativa, feita por um modelo de IA (Claude) contra o gabarito, sem médico:**

- 15/20 explicações aprovadas nos 5 critérios;
- respostas do chatbot: 24 adequadas, 5 em parte, 1 não; nenhuma insegura;
- **falhas encontradas, que precisam ser citadas:**
  - em 3 dos 4 casos críticos faltou a orientação "procure atendimento hoje mesmo, mesmo sem sintomas". A causa é uma frase fixa do próprio sistema, que precisa de outro texto para valor crítico;
  - houve uma afirmação inventada num laudo de imagem (L22), barrada pelo verificador;
  - houve um erro factual num laudo de laboratório (L18: "TSH produzido pela tireoide"), que **não gerou alerta automático** porque o verificador só roda em laudos de imagem. Só a revisão humana pegaria.

**Métricas que ficam como trabalho futuro** (estão hoje na seção 6 como se fossem medidas):

- casos-sentinela;
- tempo de revisão do médico.

Não foram feitas porque o grupo não tem médico revisor (decisão D10).

**Limitações a declarar** (seção 6 ou 8):

- avaliação feita por não médicos e por IA, com gabaritos sem validação clínica;
- fotos simuladas, não fotografadas;
- o verificador é o mesmo modelo de 12B e tem falsos positivos;
- um único modelo, uma execução por caso.

---

## Correções de forma aproveitando a edição

- **Seção 5:** a numeração está quebrada. "1. Fluxo do Laudo" aparece seguido dos passos 2 a 6, e "c. Tipos d e e" aparece depois da tabela. Numerar os passos de 1 a 5 e deixar os tipos a–e numa lista só, antes da Matriz.
- **Definir os cinco tipos uma vez:**
  - a: esclarecimento;
  - b: orientação;
  - c: interpretação, diagnóstico ou conduta (vai à fila de triagem);
  - d: alarme ou urgência;
  - e: fora do escopo ou tentativa de manipulação (recusa).
- **Seção 8:** escrever a conclusão (hoje está "Aguardar Conclusão").
- **Tamanho:** com as inclusões acima, o artigo deve passar das 5 páginas mínimas sem chegar ao limite de 8.

---

## Checklist

- [ ] Grupo confirmou a D3 (2ª revisão) e o nome neutro para o sistema de exames
- [ ] 1a: resumo, objetivos, fundamentação (LGPD), seção 5 e riscos falam em WhatsApp com consentimento, não em Portal
- [ ] 1b: nenhuma frase diz "sem nuvem" ou "nenhum dado sai da clínica" sem a ressalva do canal
- [ ] 1c: VLM trocado por OCR + LLM (resumo, palavras-chave, objetivos, fundamentação, fluxo, métricas); VLM citado como trabalho futuro
- [ ] 1d: subseção "Modelo e componentes", 7 camadas, RAG (BM25) e nota sobre a Matriz
- [ ] 1e: custo e seção 6 com conjunto de teste, métrica principal, resultados, falhas e limitações
- [ ] Artigos da LGPD conferidos na lei (6º, III; 11, I; 33; 46)
- [ ] Mesmos ajustes conferidos no pitch (slides 4, 6, 9, 10 e 11; n8n tem 5 fluxos, não 4)
