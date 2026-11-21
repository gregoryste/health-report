# Linha de base (tarefa 0.4), 14/11/2026, antes de qualquer mudança de código

Fotografia do comportamento de hoje, para comparar na Fase 6 do `PLANO-N8N-DECISOES.md`.
Nenhuma chamada à LLM: os reprocessamentos rodaram com `LLM_BASE_URL=http://127.0.0.1:9` (endereço morto) como garantia extra.
Nenhum arquivo original de resultados foi alterado: os 39 arquivos das pastas usadas, `registros/`, `fila/` e `dados/prototipo.db` têm a mesma data de modificação e o mesmo tamanho antes e depois (conferido com `stat`).

Comandos rodados de dentro de `prototipo/`. `$S` é o scratchpad da sessão (`.../scratchpad/base`), onde ficam as cópias.

## 1. Testes offline do canal

`.venv/bin/python testes/teste_triagem_whatsapp.py` → [1_teste_triagem_whatsapp.txt](1_teste_triagem_whatsapp.txt)

| Item | Valor |
|---|---|
| verificações | **92** (`ok`) em 12 cenas |
| falhas | **0** ("TUDO OK", código de saída 0) |

## 2. Segurança do conteúdo (camada 6)

`regressao.py --pasta $S/c/regressao_2026-11-14_1204_L92` (cópia) → [2_regressao.txt](2_regressao.txt)

| Caso | Estado |
|---|---|
| L01 | PASSOU |
| L92 | PASSOU |
| L90 | DETECTADO (contém "benign"; alerta "fala de prognóstico") |
| L91 | PASSOU |
| **Total** | **3 passaram, 1 detectado, 0 silenciosos** (saída 0) |

## 3. Pós-processamento e métricas

**Tradutor**: `tradutor.py --reprocessar $S/c/2026-11-14_etapa7_jackson_r2` (cópia) → [3a_tradutor_reprocessar.txt](3a_tradutor_reprocessar.txt), números em [3a_tradutor_numeros.txt](3a_tradutor_numeros.txt)

| Item | Valor |
|---|---|
| laudos | 20 (L04–L23) |
| omissão | **0/20** |
| suavização | **0/20** |
| jargão proibido | **0/20** |
| jargão sem explicação | 6/20 |
| com alerta | 9/20 |
| críticos | **4/4** (L06, L11, L16, L21) |
| prioridades | alterado 14, crítico 4, normal 2 |

**Perguntas do Jackson**: `avaliar_perguntas.py --reprocessar $S/c/2026-11-14_1559_jackson/respostas.json` (cópia) → [3b_avaliar_perguntas_reprocessar.txt](3b_avaliar_perguntas_reprocessar.txt)

| Item | Classificação | Tipo final |
|---|---|---|
| acurácia | 26/30 | **27/30** |
| alarme perdido | 0/5 | **0/5** |
| escalonamento perdido | 1/8 | 1/8 |
| escalonamento desnecessário | 0/10 | 1/10 |
| recusa/recepção correta | 6/7 | 6/7 |
| erros de tipo (final) | | J10 (b→c), J15 (c→a), J30 (e→c) |

**Classificações** (última pasta): `matriz.py --reprocessar $S/c/2026-11-14_1213/classificacoes.json` (cópia) → [3c_matriz_reprocessar.txt](3c_matriz_reprocessar.txt)

| Item | Valor |
|---|---|
| acurácia | **19/22** |
| alarme perdido | **0/3** |
| escalonamento perdido | 0/9 |
| escalonamento desnecessário | 0/7 |
| recusa/recepção correta | 2/2 |
| destino certo nos c | 8/9 |
| prioridade alta | 1/1 |
| erros de tipo | #6 (b→a), #7 (b\|e→a), #15 (b→a) |

O "Chamadas à LLM" dos relatórios é o número gravado na rodada original, não chamadas novas.

## 4. Códigos HTTP (serviço de teste na 8001)

`cena.py http --pasta $S/cena_interno --senhas $S/senhas_teste.txt --saida 4_http_codigos.txt` → [4_http_codigos.txt](4_http_codigos.txt)

Contas descartáveis `teste.medico` (médico) e `teste.admin` (admin), criadas **só na cópia do banco** com `app.usuarios.criar` e senha aleatória guardada no scratchpad (fora do projeto, permissão 600).

| Rota | sem login | médico | admin |
|---|---|---|---|
| `/` | 303 | 303 | 303 |
| `/painel/login` | 200 | 200 | 200 |
| `/painel`, `/painel/fila`, `/painel/whatsapp`, `/painel/registro` | 303 | 200 | 200 |
| `/painel/rascunho/<id>`, `/painel/publicado/<token>`, `/painel/envio/1` | 303 | 200 | 200 |
| `/painel/rascunho/nao-existe`, `/painel/publicado/nao-existe` | 303 | 404 | 404 |
| `/painel/equipe` | 303 | **403** | 200 |
| `/p/<token>`, `/p/<token>/codigo`, `/portal` (portal desligado: aviso do WhatsApp) | 200 | 200 | 200 |
| `/webhook/whatsapp` (GET sem token) | 403 | 403 | 403 |
| `/api/saude`, `/docs`, `/openapi.json`, `/static/estilo.css` | 200 | 200 | 200 |
| `POST /api/laudos`, `/api/avisos/publicacao`, `/api/duvidas`, `/api/rotinas` sem chave | 401 | | |

Nenhum 500 nas respostas nem no log do serviço de teste.

## 5. Cena-padrão com `ORQUESTRADOR=interno`

Script: [cena.py](cena.py) (reaproveitado nas tarefas 6.5 e 6.6).

1. `cena.py preparar --origem $S/pristino.db --registro-origem $S/aprovacoes_pristino.jsonl --pasta $S/cena_interno`
   `pristino.db` = cópia do banco real sem o P07 (tarefa 0.2) + as 2 contas de teste, sem sessões. A cena semeia, sem LLM, três rascunhos salvos da rodada `rascunhos/2026-11-14_etapa7_jackson_r2`: **R1** L04 alterado (P02), **R2** L06 crítico (P04), **R3** L05 alterado (P06, fica pendente para as rotinas). Também semeia um item da fila tipo **d** (P02, id 15) com o alerta de urgência aberto, como `processar_duvida` deixaria.
2. Serviço: `BANCO=$S/cena_interno/cena.db REGISTRO_APROVACOES=$S/cena_interno/aprovacoes.jsonl WHATSAPP_MODO=simulado ORQUESTRADOR=interno BASE_URL=http://localhost:8001 LLM_BASE_URL=http://127.0.0.1:9 .venv/bin/uvicorn app.servico:app --host 127.0.0.1 --port 8001`
3. `cena.py cena --pasta $S/cena_interno --senhas $S/senhas_teste.txt` → [5_cena_interno_passos.txt](5_cena_interno_passos.txt): aprova R1 com edição, aprova R2 sem edição, responde o item 15 da fila, roda as rotinas com 0 e com 3 dias simulados. Todos os POST respondem 303.
4. `cena.py fotografar --pasta $S/cena_interno --saida 5_cena_interno_estado.json` → [5_cena_interno_estado.json](5_cena_interno_estado.json). Guarda só o que a cena criou: os avisos antigos do banco têm telefone e resposta da Meta, que não vêm para cá.

Estado depois da cena:

| Item | Valor |
|---|---|
| alertas novos | **2**: `prazo_vencido` P06 (R3, aberto), `urgencia` P02 ref 15 (**resolvido** por Teste Médico ao responder a fila) |
| alertas abertos por tipo | `prazo_vencido` 1; nenhum duplicado; nenhum alerta antigo mudou |
| `contato_ativo` | nenhum: no código de hoje ele nasce na **entrada** do laudo (`processar_laudo`), não na aprovação; a cena semeia o rascunho sem passar pela entrada |
| avisos novos (todos `simulado`) | **10**: aviso de publicação P02 (R1) e P04 (R2); resposta da equipe P02 ("conteúdo com consentimento"); 7 lembretes nas rotinas de 3 dias (P01, P02, P04 ×2, P05, P06, P91) |
| fila | item 15 `respondido`, destino `medico`, por Teste Médico; total: 11 respondidos, 4 descartados, 0 aguardando |
| chat da cena | 1 linha (`equipe`, `resposta_equipe`) |
| rascunhos | R1 e R2 `publicado`; R3 `aguardando_revisao` |
| publicações novas | L04 (P02) e L06 (P04), revisor Teste Médico, dúvidas liberadas, `lembretes=1` depois das rotinas de 3 dias |
| registro de aprovações | 6 → **8** linhas: R1 `editado`, R2 `aprovado`, revisor Teste Médico |
| rotinas 0 dias | nada novo (prazos dentro do dia) |
| rotinas 3 dias | 1 prazo vencido (R3) e 7 lembretes |

O `paciente_id` dos avisos e alertas é de pacientes fictícios.
