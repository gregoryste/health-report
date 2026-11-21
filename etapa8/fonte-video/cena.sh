#!/bin/zsh
# Refaz a cópia de cena do banco e sobe o serviço de cena na porta 8001.
# Nunca toca o banco real: tudo vai para $CENA (padrão: uma pasta temporária).
#   ./cena.sh                 # usa /tmp/tradutor-cena
#   CENA=/outro/lugar ./cena.sh
set -e
AQUI="${0:A:h}"
PROTOTIPO="${AQUI}/../../prototipo"
CENA="${CENA:-${TMPDIR:-/tmp}/tradutor-cena}"
mkdir -p "$CENA"

kill $(lsof -t -nP -iTCP:8001 -sTCP:LISTEN) 2>/dev/null || true; sleep 1
cp "$PROTOTIPO/dados/prototipo.db" "$CENA/p.db" && : > "$CENA/aprovacoes.jsonl"
cd "$PROTOTIPO"
BANCO="$CENA/p.db" .venv/bin/python "$AQUI/preparar_cena.py" "$PROTOTIPO"
sqlite3 "$CENA/p.db" "update publicacoes set revisor='Dra. Helena Souza';"
BANCO="$CENA/p.db" REGISTRO_APROVACOES="$CENA/aprovacoes.jsonl" WHATSAPP_MODO=simulado ORQUESTRADOR=interno PORTAL_PACIENTE=0 \
  nohup .venv/bin/uvicorn app.servico:app --host 127.0.0.1 --port 8001 > "$CENA/u.log" 2>&1 &
disown
for i in $(seq 1 30); do curl -s -o /dev/null http://localhost:8001/api/saude && break; sleep 0.5; done
