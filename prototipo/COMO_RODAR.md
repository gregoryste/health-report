# Como rodar o protótipo (etapa 6)

Tudo roda no Mac do Gregory. A LLM é a interna da empresa (rota e token no `.env`). Só dados fictícios.

## 1. Serviço (telas + API)

```bash
cd prototipo
.venv/bin/uvicorn app.servico:app --host 127.0.0.1 --port 8000
```

Para deixar rodando sem depender do terminal (como está desde 14/11), com o log em `dados/servico_8000.log`:
`nohup .venv/bin/uvicorn app.servico:app --host 127.0.0.1 --port 8000 >> dados/servico_8000.log 2>&1 < /dev/null & disown`. Para parar: `kill $(lsof -tiTCP:8000 -sTCP:LISTEN)`.

- **Painel da equipe:** http://localhost:8000/painel. Cada profissional entra com **usuário e senha próprios**. Para criar uma conta (a senha é digitada no terminal e fica só como hash no banco):
  `.venv/bin/python -m app.usuarios criar --login helena --nome "Dra. Helena Souza" --funcao medico` (ou `--funcao enfermagem`, ou `--funcao admin`). A **administração** vê a aba "Equipe e acessos": todas as contas e funções, e nela cria contas, troca função e senha, ativa e desativa (sempre sobra um admin ativo).
  Outros comandos: `listar`, `senha --login X` (troca a senha), `funcao --login X --funcao admin` (troca a função), `desativar --login X`, `ativar --login X`. Nome e função entram no registro de aprovações; 5 senhas erradas bloqueiam o usuário por 5 min.
- **Portal do paciente:** pelo link do aviso (tela "Avisos enviados" no painel). Use a data de nascimento do paciente fictício e o código de 6 dígitos, que também aparece em "Avisos enviados" enquanto o WhatsApp está simulado.

Datas de nascimento dos pacientes fictícios (`app/semear.py`):

| Paciente | Data |
|---|---|
| P01 | 1972-03-14 |
| P02 | 1988-07-02 |
| P03 | 1955-11-23 |
| P04 | 1987-05-09 |
| P90 | 1982-01-30 |
| P91 | 1997-09-18 |

## 2. n8n (orquestrador)

Precisa do Docker Desktop aberto.

```bash
cd prototipo/n8n
docker compose --env-file ../.env up -d      # sobe o n8n em http://localhost:5678
```

**Quem decide o quê.** O serviço executa cada etapa e devolve os fatos: prioridade do laudo, tipo final da dúvida, status do envio. O n8n decide o caminho num nó IF ou Switch e chama a ação do ramo (`/api/acoes/contato-ativo`, `/api/acoes/urgencia`, `/api/acoes/falha`). As regras clínicas não saem do serviço. O desenho está em `etapa5/diagramas/4_fluxos_n8n.png`.

Os 5 fluxos estão em `n8n/fluxos/`, importados e publicados no n8n real:

| Fluxo | `id` | Decisão |
|---|---|---|
| 1. entrada do laudo | `t2H4HUAtc1G06gz1` | IF prioridade = crítico → alerta de contato ativo |
| 2. publicação e aviso | `jCg6mbxcal42Ckc2` | IF aviso não saiu → alerta "Falha no envio" |
| 3. pista da dúvida | `2gSg3VUB1HO37RrF` | Switch a–e (+ "outro tipo"); d → alerta de urgência |
| 4. rotinas (8h e webhook demo) | `HqqLDillJx7uMjsU` | IF houve alerta de prazo → "Resumo do dia" |
| 5. erros | `Xf5ErrosOrq0001a` | sem decisão: qualquer falha dos fluxos 1–4 vira o alerta âmbar "Falha de orquestração" |

- Os fluxos 1–4 apontam para o fluxo 5 em Configurações → Error workflow (`settings.errorWorkflow` no JSON).
- **Novas tentativas:** só nos nós que não chamam a LLM (3 vezes, a cada 2 s; o fluxo 5 tenta 5 vezes, a cada 5 s). Os nós de `/api/laudos` e `/api/duvidas` nunca repetem e esperam até 120 s.
- **Para reimportar depois de mudar um fluxo** (os 5 de uma vez):
  ```bash
  docker compose --env-file ../.env exec -T n8n n8n import:workflow --separate --input=/fluxos
  for id in t2H4HUAtc1G06gz1 jCg6mbxcal42Ckc2 2gSg3VUB1HO37RrF HqqLDillJx7uMjsU Xf5ErrosOrq0001a; do
    docker compose --env-file ../.env exec -T n8n n8n publish:workflow --id=$id; done
  docker compose --env-file ../.env restart n8n
  docker compose --env-file ../.env exec -T n8n n8n list:workflow     # devem ser 5, sem repetidos
  ```
  Depois do `publish`, o n8n leva alguns segundos para usar a versão nova.
- Os JSON têm o `id` de cada fluxo: a reimportação **atualiza** o fluxo existente. Sem o `id`, o n8n cria uma cópia inativa (aconteceu em 14/11).
- **Mudou um ramo? Mude também a tabela `ROTAS` em `app/servico.py`** e rode `testes/teste_rotas_n8n.py`: ele lê os JSON e falha se o n8n e a tabela deixarem de bater.
- **Não copiar só o `database.sqlite` do n8n:** ele usa o modo WAL. Para mexer no banco, parar o n8n e levar junto (ou descartar, se for repor um banco limpo) os arquivos `database.sqlite-wal` e `-shm`; senão o n8n acusa "database disk image is malformed".
- **Para ver os fluxos no editor** (prints para os slides), abra http://localhost:5678 e crie a conta de administrador local na primeira vez.

`ORQUESTRADOR` no `.env`:
- `n8n`: publicação, dúvidas e rotinas passam pelos fluxos do n8n.
- `interno`: o serviço faz tudo sozinho, com o mesmo roteamento da tabela `ROTAS` (plano B da demo). Conferido em 14/11: a mesma cena dá o mesmo resultado nos dois modos.

Se o n8n estiver fora do ar, o serviço segue pelo caminho interno sozinho e registra isso no log.

### Ambiente de teste (n8n 5679 + serviço 8001)

Para testar mudanças nos fluxos sem tocar no real: um segundo n8n (`n8n-teste`, porta **5679**, volume próprio `n8n_teste_dados`) chama um segundo serviço (porta **8001**) que usa **cópias** do banco e do registro, WhatsApp simulado e, de preferência, `LLM_FIXA=1`.

```bash
cd prototipo/n8n
docker compose -f docker-compose.teste.yml --env-file ../.env up -d      # ou: … start (depois de um stop)
docker exec n8n-teste n8n import:workflow --separate --input=/fluxos     # e publish:workflow nos 5 ids, como acima

cd prototipo
BANCO=<cópia do banco> REGISTRO_APROVACOES=<cópia do registro> WHATSAPP_MODO=simulado \
  ORQUESTRADOR=n8n N8N_URL=http://localhost:5679 BASE_URL=http://localhost:8001 LLM_FIXA=1 \
  .venv/bin/uvicorn app.servico:app --host 127.0.0.1 --port 8001
```

Para desligar: parar o uvicorn da 8001 e `docker compose -f docker-compose.teste.yml --env-file ../.env stop` (o volume fica). Nunca usar `WHATSAPP_MODO=meta` no teste.

**`LLM_FIXA=1` (só para teste; nunca no `.env` do serviço real).** O serviço não chama a LLM interna: o tradutor, o classificador, o respondedor e os verificadores devolvem respostas fixas. O resto da pista roda de verdade: regra fixa, checagens, lista de alarme e roteamento. Serve para testar os fluxos do n8n sem gastar chamadas. O `/api/saude` mostra `"llm_fixa": true` quando está ligado. Com a resposta fixa, o classificador decide pela palavra na pergunta: "consulta" vai para **c**; "recepção", "horário" ou "agendar" vão para **e**; o resto vai para **a**. Sinal de alarme continua indo para **d** pela lista de alarme, sem LLM.

Testes offline (sem LLM, sem n8n, sem WhatsApp): `.venv/bin/python testes/teste_rotas_n8n.py` (roteamento nos dois modos, rotas de ação e coerência n8n × `ROTAS`) e `.venv/bin/python testes/teste_triagem_whatsapp.py`.

## 3. Mandar laudos de teste

Com o serviço rodando:

```bash
cd prototipo
.venv/bin/python -m app.semear L03 L92 L91            # pela API do serviço
.venv/bin/python -m app.semear --via n8n L01          # pela entrada do n8n (como o sistema de exames faria)
```

Cada laudo faz 1 chamada à LLM interna (2 se for de imagem), uma por vez, com pausa.

## 4. Roteiro de demo (sugestão)

1. Mandar um laudo crítico (L03) e um de imagem (L92) → o painel mostra o alerta de **contato ativo** e a fila ordenada por risco.
2. Abrir o L92 → a tela mostra a **origem de cada frase**, os alertas e os itens citados. Editar uma frase e aprovar.
3. "Avisos enviados" → só o texto genérico com o link.
4. Abrir o link → data de nascimento → código → explicação + dúvidas.
5. Perguntar no chat:
   - "O que significa hipoecoico?" → resposta pelo conteúdo aprovado (a);
   - "Esse nódulo é câncer?" → vai para a fila (c);
   - "Estou com dor no peito" → urgência (d), alerta no painel.
6. Fila de triagem → responder a pergunta c → a resposta aparece no chat do paciente.
7. Rotinas → "simular 4 dias" → prazo vencido e lembrete de leitura.

## WhatsApp real (número de teste da Meta)

Configurado em 14/11 com `WHATSAPP_MODO=meta`. Todos os pacientes fictícios recebem no número de teste, definido em `WHATSAPP_TELEFONE_TESTE`.

- **Outros números (colegas):** primeiro, adicione o número na Meta, em **WhatsApp → Configuração da API → Para → Gerenciar lista de números**. A conta de teste aceita até 5 números, e cada um confirma com o código que recebe no WhatsApp. Depois, ponha `WHATSAPP_TELEFONES=P03=+55 51 9xxxx-xxxx; P04=+55 51 9yyyy-yyyy` no `.env` e rode `.venv/bin/python -m app.semear --so-pacientes`. Esse comando não chama a LLM.

- **Avisos e lembretes** saem pelos modelos `aviso_nova_mensagem` e `lembrete_mensagem`, enviados à Meta em 14/11 e **em análise**.
- Para ver a situação e ligar os modelos aprovados no `.env`, rode:
  ```bash
  .venv/bin/python -m app.whatsapp_modelos
  ```
  Depois, reinicie o serviço.
- **Código de acesso:** o modelo de autenticação foi recusado para a conta de teste, porque exige a empresa verificada. O código sai como **texto livre**, que a Meta só entrega nas **24 h depois de o paciente escrever para a clínica**. Antes da demo, mande qualquer mensagem para o número de teste. Fora dessa janela, o código aparece em "Avisos enviados" no painel.
- Enquanto os modelos não forem aprovados, os avisos também saem como texto livre, valendo a mesma janela de 24 h.
- **Token:** o atual é temporário e vale 24 h. Para a apresentação, gere o permanente (usuário do sistema) e cole direto no `.env`.
- **Link no celular:** `http://localhost:8000/...` só abre no Mac. Para abrir o portal pelo celular, o serviço precisaria de um endereço público temporário.
- **Volta ao modo simulado:** `WHATSAPP_MODO=simulado` no `.env`. O serviço bloqueia qualquer texto fora dos modelos genéricos nos dois modos.

## WhatsApp como canal do paciente (D3, 2ª revisão, 14/11)

O paciente é atendido só pelo WhatsApp; o portal do paciente fica desligado (`PORTAL_PACIENTE=0` no `.env`).

1. Ao aprovar um laudo, o paciente recebe: "Há uma nova mensagem da clínica para você: responda OI nesta conversa para ver."
2. Ele responde OI → o bot pede o **CPF** e depois a **data de nascimento**. Os dois precisam conferir com o cadastro, e a mensagem precisa vir do número cadastrado.
3. Sem aceite anterior → chega o **termo** com os botões Sim / Não. Com "Sim" → explicação + menu de dúvidas.
4. "SAIR" revoga o aceite. Mensagem com sinal de alarme recebe a orientação do SAMU na hora, mesmo antes da identificação.

CPFs fictícios (dígitos verificadores válidos; a triagem confere): P01 000.000.001-91, P02 000.000.002-72, P03 000.000.003-53, P04 000.000.004-34, P05 000.000.005-15, P06 000.000.006-04, P90 000.000.090-67, P91 000.000.091-48. O CPF pode vir com ou sem pontuação, até no meio de uma frase; um CPF escrito numa pergunta vira "[CPF removido]" antes de ir para a fila e para a LLM. Teste offline: `.venv/bin/python testes/teste_triagem_whatsapp.py`.
A seção abaixo (túnel e webhook) continua valendo; os passos do portal só se aplicam com `PORTAL_PACIENTE=1`.

## Vários exames e envio de laudo pelo WhatsApp (14/11)

- **Vários exames:** com mais de um exame, o "oi" mostra a lista *Seus exames* (novos primeiro, até 8) e "Enviar um laudo". O exame escolhido fica ativo na conversa; o menu tem "Meus exames". Pergunta que cita outro exame do paciente → o bot oferece trocar.
- **Enviar um laudo (foto JPG/PNG ou PDF):** `app/leitura.py` lê no próprio Mac (`pdftotext` para PDF com texto; `pdftoppm` + `tesseract` para foto ou PDF escaneado). A LLM interna só organiza o texto (`prompts/estruturador_sistema.txt`), e todo número precisa existir no texto lido.
  1. sem conferência do paciente: cada número precisa estar no texto lido e na mesma linha do nome do item;
  2. **resumo imediato**, sem IA: valores, posição em relação à faixa do próprio laudo e definições aprovadas do glossário;
  3. o rascunho da IA vai para a revisão do painel (laudo `E001`, `E002`…), com o arquivo original e o aviso "enviado pelo paciente";
  4. ao aprovar, o arquivo é apagado (fica só o valor conferido).
  Ilegível → pede outra foto; na 2ª, vai para a equipe (alerta "LAUDO ENVIADO"). Nome diferente do cadastro → recusa e apaga. Valor crítico → alerta de contato ativo já na leitura.
- **Limites críticos dos laudos enviados:** provisórios, em `app/leitura.py` (`CRITICOS`).
- **Tesseract só em inglês:** números saem certos, acentos não. Para português: `brew install tesseract-lang`.
- **Teste offline:** `.venv/bin/python testes/teste_triagem_whatsapp.py` (80 verificações, sem LLM nem Meta).

## WhatsApp com consentimento (D3 revisada)

1. **Subir o túnel** e copiar o endereço `https://….trycloudflare.com`:
   ```bash
   cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000
   ```
2. Colocar esse endereço em `BASE_URL` no `.env` e **reiniciar o serviço**.
3. **Cadastrar o webhook na Meta (automático):** `.venv/bin/python -m app.whatsapp_webhook`, com o serviço no ar. Ele usa `WHATSAPP_APP_ID` e `WHATSAPP_APP_SECRET` do `.env` e já assina o campo `messages`. Na interface nova da Meta, esse campo não aparece; o caminho manual abaixo fica só como referência.
   No app da Meta → **WhatsApp → Configuração → Webhook → Editar**:
   - **URL de callback:** `<BASE_URL>/webhook/whatsapp`;
   - **Token de verificação:** o valor de `WHATSAPP_VERIFY_TOKEN` do `.env`;
   - **Verificar e salvar**, depois **assinar o campo `messages`**.
4. **Configurações do app → Básico → Chave secreta do app** → colar em `WHATSAPP_APP_SECRET` no `.env` e reiniciar o serviço. A partir daí, só eventos assinados pela Meta são aceitos.
5. **Na demo:**
   - no portal, autorizar o WhatsApp;
   - no celular, mandar "oi" para o número da clínica → chega a explicação;
   - fazer perguntas → as respostas chegam no WhatsApp;
   - responder "SAIR" → o consentimento é revogado.

O endereço do túnel rápido muda a cada vez que ele sobe, então os passos 2 e 3 precisam ser refeitos. Pelo túnel só passam o portal e o webhook; o painel fica só no Mac.
