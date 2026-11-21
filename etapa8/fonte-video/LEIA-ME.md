# Fonte do vídeo de demonstração (etapa 8)

Vídeo final: `../video-demo-tradutor-de-laudos.mp4` (1920×1080, 30 fps, 1 min 35 s, sem som), sem a cena 9 (avaliação) e com as pausas longas encurtadas
(telas paradas acima de 1,6 s ficaram com 1,6 s + 45% do excedente; nenhuma animação foi cortada). A versão de 2 min 8 s, com as pausas originais, está em `../video-demo-tradutor-de-laudos_2min08.mp4`.
Ele foi cortado com ffmpeg (0–120,3 s + 134–142 s, transição de 0,5 s). A versão gravada completa, com a avaliação, está em `../video-demo-tradutor-de-laudos_com-avaliacao.mp4`; regravar com `gravar.py` gera de novo a versão com a cena 9.

- `comp/index.html` — a animação (linha do tempo em `renderAt(t)`; textos e tempos de cada cena no HTML; conversa do celular em `CONVERSA`).
- `comp/telas/` — capturas reais do painel, feitas numa **cópia de cena** do banco (sem o P07, conta "Dra. Helena Souza", WhatsApp simulado).
- `preparar_cena.py`, `cena.sh` — montam a cópia de cena e sobem o serviço de cena na porta 8001 (nunca tocam o banco real).
- `capturar.py` — faz os passos no painel de cena (revisar, aprovar, responder a fila) e salva as capturas.
- `gravar.py` — grava a animação quadro a quadro com o Chrome e gera o MP4 com o ffmpeg.

`cena.sh` usa caminhos relativos ao repositório e grava a cópia de cena em `$CENA` (padrão: `/tmp/tradutor-cena`).
Requer: Playwright (`pip install playwright`, usa o Google Chrome instalado) e ffmpeg.

Origem dos textos do celular: mensagens fixas do código (`app/avisos.py`, `app/canal_whatsapp.py`, `chatbot.py`),
explicação aprovada do E001 (banco), resposta J01 da rodada 2 da avaliação do chatbot e a resposta do médico digitada na cena.
