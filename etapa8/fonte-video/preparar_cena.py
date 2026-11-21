"""Prepara a cópia de cena do banco (numa pasta temporária, ver cena.sh). Nada aqui toca o banco real."""
import os, secrets, sys
sys.path.insert(0, sys.argv[1])
from app import banco, usuarios
banco.iniciar()
x = banco.executar
# 1. sem dados reais: remove o P07 e tudo ligado a ele
toks = [r["token"] for r in banco.todos("SELECT token FROM publicacoes WHERE paciente_id='P07'")]
for t in toks:
    x("DELETE FROM chat WHERE token=?", t); x("DELETE FROM fila WHERE token=?", t)
x("DELETE FROM rascunhos WHERE laudo_id IN (SELECT id FROM laudos WHERE paciente_id='P07')")
for tab in ("publicacoes", "laudos", "consentimentos", "avisos", "envios", "alertas"):
    x(f"DELETE FROM {tab} WHERE paciente_id='P07'")
x("DELETE FROM pacientes WHERE id='P07'")
# 2. contas: só a de cena
x("DELETE FROM usuarios"); x("DELETE FROM sessoes WHERE papel='equipe'")
senha = secrets.token_urlsafe(12)
usuarios.criar("dra.helena", "Dra. Helena Souza", "medico", senha)
open(os.path.join(os.path.dirname(os.environ["BANCO"]), "senha_cena.txt"), "w").write(senha)
# 3. fila de revisão: crítico primeiro (rascunhos reais voltando ao estado anterior à aprovação)
for rid in ("L03-20261114-124437", "E001-20261114-154607", "L01-20261114-125023"):
    lid = banco.um("SELECT laudo_id FROM rascunhos WHERE rascunho_id=?", rid)["laudo_id"]
    x("UPDATE rascunhos SET status='aguardando_revisao' WHERE rascunho_id=?", rid)
    x("DELETE FROM publicacoes WHERE laudo_id=?", lid)
# 4. alertas: só o de urgência real do P04, aberto
x("UPDATE alertas SET status='resolvido'"); x("UPDATE alertas SET status='aberto' WHERE id=2")
# 5. fila de triagem: só a pergunta do remédio (J12), como o chatbot grava
x("DELETE FROM fila")
pub = banco.um("SELECT token FROM publicacoes WHERE laudo_id='L92'")  # exame já publicado do P04
x("INSERT INTO fila (token, pergunta, tipo, destino_sugerido, prioridade, motivo, rascunho, fontes, status, criado_em) "
  "VALUES (?,?,?,?,?,?,?,?,?,?)", pub["token"], "Com o LDL alto, qual remédio devo tomar?", "c", "medico", "normal",
  "pedido de remédio", "", "[]", "aguardando", banco.agora())
print("cena pronta:", banco.um("SELECT COUNT(*) c FROM rascunhos WHERE status='aguardando_revisao'")["c"], "rascunhos,",
      banco.um("SELECT COUNT(*) c FROM fila WHERE status='aguardando'")["c"], "na fila,",
      banco.um("SELECT COUNT(*) c FROM alertas WHERE status='aberto'")["c"], "alerta;",
      "P07 removido:", not banco.um("SELECT 1 x FROM pacientes WHERE id='P07'"))
