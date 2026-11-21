# Rascunho: originalidade e contribuições

Rascunho para as seções de introdução e de contribuições do artigo, e para o slide de "o que há de novo" no pitch.
Critério atendido: **Relevância e originalidade (20 pts)**: "problema claro e real, proposta com algo de novo".

> ⚠️ Tudo que está marcado como **[confirmar]** depende do levantamento de referências. Não afirmar "nenhum estudo fez X" sem ter lido os estudos. Preferir "nos trabalhos revisados".

---

## 1. O que já existe (a confirmar com a literatura)

Linha geral esperada, a ser sustentada com referências **[confirmar]**:
- Estudos recentes mostram que LLMs conseguem reescrever laudos (principalmente de radiologia) em linguagem mais simples, com ganho de legibilidade.
- Os mesmos estudos relatam erros: afirmações sem apoio no laudo, achados omitidos ou suavizados.
- Em geral, usam modelos comerciais em nuvem, textos em inglês, geração em uma única etapa (laudo → texto) e avaliação por leitura de especialistas, sem um canal para o paciente perguntar depois.
- Estudos de 2024 com rascunhos de IA para responder mensagens de pacientes indicam menor sensação de sobrecarga nos médicos, mas sem economia clara de tempo (candidatos: Garcia et al., 2024; Tai-Seale et al., 2024).

## 2. O que este projeto acrescenta

Nenhum item isolado é inédito; a contribuição está na **combinação**, pensada para segurança e para o contexto brasileiro.

1. **O médico como etapa obrigatória e como fonte de melhoria.** Nada chega ao paciente sem aprovação. As edições dos médicos alimentam a melhoria do sistema (exemplos aprovados no prompt, ajustes de prompt e, no futuro, ajuste fino), e os **casos-sentinela** medem se a revisão é atenta antes de usá-la para ensinar o modelo.

2. **Um canal de volta controlado.** O paciente pode perguntar, mas o chatbot só responde com conteúdo já aprovado ou curado. O resto é classificado (esclarecimento, orientação, interpretação nova, alarme, fora do escopo) e encaminhado com rascunho a uma fila de triagem. As **dúvidas antecipadas** aprovadas junto com a explicação transformam perguntas que iriam para o médico em respostas imediatas.

3. **Híbrido com checagem automática de omissão.** Uma regra fixa marca os valores fora da faixa; a IA só escreve. Todo valor marcado precisa aparecer na explicação, o que ataca diretamente o erro mais grave relatado na literatura: omitir um achado.

4. **Privacidade por desenho.** Modelos de pesos abertos rodando no servidor da clínica; nenhuma busca semântica sobre dados identificáveis (o RAG só consulta a base da clínica); o WhatsApp só envia um aviso genérico, sem dado de saúde.

5. **Português e contexto brasileiro.** LGPD, legibilidade medida com índice adaptado ao português, materiais do Ministério da Saúde na base, divisão de competências entre medicina e enfermagem.

6. **Laudo em papel.** Um modelo de visão e linguagem lê a foto do exame impresso; campo ilegível é sinalizado, nunca inventado.

7. **Lacuna real de produto.** Os produtos atuais centralizam exames só para o médico e usam o WhatsApp só para enviar mensagens; o projeto cria a ponte que falta até o paciente.

## 3. Texto sugerido para o artigo (contribuições)

> Este trabalho propõe um sistema que explica laudos de exames a pacientes leigos, em português, com o médico como etapa obrigatória de aprovação. Diferentemente de abordagens que geram o texto em uma única etapa com modelos em nuvem **[confirmar]**, a proposta combina: (i) uma regra fixa que identifica valores alterados e verifica se nenhum foi omitido; (ii) modelos de pesos abertos executados localmente, sem busca semântica sobre dados identificáveis; (iii) um canal de dúvidas que responde apenas com conteúdo aprovado e encaminha as demais perguntas a uma fila de triagem; e (iv) um ciclo de melhoria baseado nas edições dos médicos, protegido por casos-sentinela que medem a atenção da revisão.

## 4. Frase para o pitch

> "A IA escreve, a regra confere, o médico decide, e cada correção do médico ensina o sistema."

## 5. A confirmar antes de usar

- [ ] Estudos sobre LLMs simplificando laudos para pacientes (o que fizeram, que modelo, que idioma, como avaliaram, que erros encontraram)
- [ ] Se algum estudo já combinou aprovação médica + canal de dúvidas + modelo local
- [ ] Garcia et al. (2024) e Tai-Seale et al. (2024), JAMA Network Open
- [ ] Martins et al. (1996), Flesch adaptado ao português
- [ ] Artigos da LGPD citados no plano (6º, III; 11; 18; 33)
