# Resultado dos testes: n8n com decisões (opção 2)

14/11/2026. Plano e registro passo a passo: [`PLANO-N8N-DECISOES.md`](PLANO-N8N-DECISOES.md). Linha de base, tirada antes de qualquer mudança: [`linha-de-base/`](linha-de-base/LEIA-ME.md). Saídas depois da mudança: [`depois/`](depois/).

**Resumo:** nenhum item piorou. Todos os números e estados da linha de base ficaram **iguais**. Nenhuma diferença inesperada para melhor. O que mudou foi só o que se pretendia mudar: o n8n passou a decidir o caminho, ganhou um fluxo de erros, e o serviço ganhou as rotas de ação e a tabela `ROTAS`.

## Linha de base × depois

| Item | Linha de base (0.4) | Depois (Fase 6) | Situação |
|---|---|---|---|
| **6.1** Teste do canal WhatsApp | 92 verificações, 0 falhas | 92 verificações, 0 falhas (saída idêntica) | igual |
| **6.2** Regressão de segurança (camada 6) | 3 passaram, 1 detectado (L90), **0 silenciosos** | 3 passaram, 1 detectado (L90), **0 silenciosos** (saída idêntica) | igual |
| **6.3** Tradutor, 20 laudos: omissão / suavização / jargão proibido | 0/20 · 0/20 · 0/20 | 0/20 · 0/20 · 0/20 | igual |
| **6.3** Tradutor: críticos | 4/4 (L06, L11, L16, L21) | 4/4 (L06, L11, L16, L21) | igual |
| **6.3** Perguntas do Jackson: tipo final / alarme perdido | 27/30 · 0/5 | 27/30 · 0/5 (relatório idêntico) | igual |
| **6.3** Classificações: acurácia / alarme perdido | 19/22 · 0/3 | 19/22 · 0/3 (relatório idêntico) | igual |
| **6.4** Teste novo das rotas (`testes/teste_rotas_n8n.py`) | não existia | 33 verificações, 0 falhas | novo, passando |
| **6.5** Cena-padrão no modo interno (14 itens: alertas, duplicados, avisos, fila, rascunhos, publicações, chat, registro, contagens) | 2 alertas novos, 10 avisos simulados, registro 6 → 8 | 14 de 14 itens iguais | igual |
| **6.6** Mesma cena com o n8n decidindo | não havia | 14 de 14 itens iguais ao interno e à linha de base; 4 execuções no n8n, todas `success` | igual (a única diferença são as execuções no n8n) |
| **6.7** Códigos HTTP: 20 páginas × sem login / médico / admin + API sem chave | 64 códigos, nenhum 500 | 64 códigos iguais; rotas novas `/api/acoes/*` → 401 sem chave; painel com os alertas novos → 200; nenhum 500 | igual |
| **6.8** n8n fora do ar | (plano B existente) | a cena conclui pelo caminho interno; 14 de 14 itens iguais à 6.5 | igual |
| **6.8** Serviço fora do ar | não existia | fluxo 4 falha depois de 3 tentativas; o fluxo 5 registra "Falha de orquestração" quando o serviço volta | novo, passando |
| **6.9** Real: n8n | 4 fluxos ativos | 5 fluxos ativos, nenhum duplicado, log sem "malformed" nem erro | mudança pretendida |
| **6.9** Real: serviço, painel, contas, banco | saúde 200; 3 contas; 9 pacientes; 9 publicações | saúde 200, painel abre, mesmas 3 contas e funções, mesmos 9 pacientes e 9 publicações | igual (+1 alerta: o teste da 4.5, já resolvido) |

Nenhuma chamada à LLM nas Fases 0–3 e 6. Na Fase 4 (validação com a LLM real, só no ambiente de teste) foram **4 chamadas**, contra o limite de 6. Nenhuma mensagem real de WhatsApp saiu durante o plano.

## O que mudou de propósito

- **O n8n decide o caminho; o serviço decide o conteúdo.** Com `?efeitos=0`, `/api/laudos` e `/api/duvidas` só devolvem os fatos (prioridade, tipo final, `fila_id`, paciente, laudo). Os fluxos decidem com nós IF e Switch:
  - **1. Entrada do laudo:** IF crítico → `/api/acoes/contato-ativo`.
  - **2. Publicação:** IF o aviso não saiu → `/api/acoes/falha` (alerta "Falha no envio").
  - **3. Dúvida:** Switch com 5 saídas (a–e) mais "outro tipo"; d → `/api/acoes/urgencia`.
  - **4. Rotinas:** IF houve alerta de prazo → "Resumo do dia"; senão → "Dia sem alerta novo".
- **Fluxo 5, de erros (novo):** qualquer falha dos fluxos 1–4 vira o alerta âmbar "Falha de orquestração" no painel. O texto é curto e não leva dado de saúde.
- **Rotas de ação novas** (`/api/acoes/contato-ativo`, `/urgencia`, `/falha`): exigem a chave da API e não duplicam alerta.
- **Tabela `ROTAS` no serviço:** o mesmo roteamento no modo interno (plano B). O teste de coerência lê os JSON do n8n e falha se o n8n e a tabela deixarem de bater.
- **Novas tentativas só sem LLM:** 3 tentativas a cada 2 s nos nós sem LLM; 5 a cada 5 s no fluxo 5. Laudo e dúvida nunca repetem e esperam até 120 s.
- **Alerta "Falha no envio" no modo interno:** novo. Com o WhatsApp simulado ele nunca dispara.
- **`LLM_FIXA=1`**, só para teste: respostas fixas, sem chamar a LLM.
- **Material atualizado:** artifact "Fluxos do n8n", `etapa5/diagramas/4_fluxos_n8n.png`, `etapa5/texto_tecnico.md`, `COMO_RODAR.md`, `plano-gregory.md` e os prints em `etapa8/prints-n8n/`.
- **Serviço real:** reiniciado com o código novo e rodando com `nohup`. O log agora fica em `prototipo/dados/servico_8000.log`.

## Pendências e limites

- **WhatsApp real (Meta):** o ramo "Falha no envio" só foi testado offline e com status forçado, porque nenhuma mensagem real podia sair. Vale testar uma vez com o número de teste.
- **Aviso repetido:** a nova tentativa do aviso pode mandar o mesmo aviso duas vezes se o envio passar de 30 s e a resposta se perder. Hoje o envio leva poucos segundos; o risco foi aceito.
- **Serviço fora por muito tempo:** o fluxo 5 tenta por cerca de 25 s. Se o serviço ficar fora mais do que isso, a falha fica só no histórico de execuções do n8n, sem alerta no painel.
- **Print do fluxo 3:** algumas linhas passam por trás do nó de urgência, por causa da posição dele no JSON. É só estética; corrigir exige reimportar no real.
- **Artifact "Fluxos do n8n":** é privado. Compartilhe pelo menu Share se o grupo precisar.
- **Ambiente de teste:** desligado, mas guardado:
  - contêiner `n8n-teste` e volume `n8n_teste_dados`;
  - conta de teste `teste@example.com`, que só existe no n8n de teste;
  - cópias de banco no scratchpad da sessão.

  Pode ficar como está ou ser removido. Nada disso toca o real.
- **Backups antes da mudança:**
  - `n8n/backup/2026-11-14/`: fluxos e código, tirados na 0.1;
  - `n8n/backup/2026-11-14-fase4/`: fluxos, banco do n8n com WAL/SHM e o PNG antigo do diagrama.

  A pasta da Fase 4 guarda o hash da conta de administrador do n8n real; não compartilhar.
- **Pendências anteriores, não mexidas:** paciente P07 no banco real e `testes/teste_fluxo.py` ainda usando o portal (ver `plano-gregory.md`).
