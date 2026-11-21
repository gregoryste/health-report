"""[Precisa de PORTAL_PACIENTE=1 no .env: usa o portal do paciente, desligado desde 14/11.] Teste de ponta a ponta do serviço (rodar de dentro de prototipo/ com o venv e o serviço no ar). Aprova L92 e L03, entra no portal do L92 e faz as perguntas passadas como argumento. ATENÇÃO: chama a LLM interna (1 chamada por pergunta tipo c, até 3 por pergunta a/b) e, com WHATSAPP_MODO=meta, envia mensagens reais."""
import http.cookiejar, json, re, sqlite3, sys, time, urllib.parse, urllib.request

B = "http://127.0.0.1:8000"
DB = "dados/prototipo.db"
ENV = dict(l.strip().split("=", 1) for l in open(".env", encoding="utf-8") if "=" in l and not l.startswith("#"))
login, senha = ENV["PAINEL_TESTE_LOGIN"], ENV["PAINEL_TESTE_SENHA"]  # conta criada com: python -m app.usuarios criar


class SemRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def cliente():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(op, url, dados):
    return op.open(urllib.request.Request(B + url, data=urllib.parse.urlencode(dados).encode()), timeout=600)


def sql(q, *a):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    r = [dict(x) for x in con.execute(q, a).fetchall()]; con.close(); return r


eq = cliente()
post(eq, "/painel/login", {"login": login, "senha": senha})

for laudo_id, editar in [("L92", False), ("L03", True)]:
    r = sql("SELECT * FROM rascunhos WHERE laudo_id=? AND status='aguardando_revisao'", laudo_id)[0]
    d = json.loads(r["json"])
    form = {"aberto_em": int(time.time()) - 40, "explicacao": d["explicacao"], "liberar_duvidas": "on", "acao": "aprovar"}
    if editar:
        form["explicacao"] = d["explicacao"].replace("Converse com o seu médico", "Converse com a sua médica, Dra. Fictícia,")
    for k, q in enumerate(d["duvidas"]):
        form.update({f"manter_{k}": "on", f"p_{k}": q["pergunta"], f"r_{k}": q["resposta"]})
    post(eq, f"/painel/rascunho/{r['rascunho_id']}", form)
    print(f"{laudo_id}: aprovado{' com edição' if editar else ''} → status", sql(
        "SELECT status FROM rascunhos WHERE rascunho_id=?", r["rascunho_id"])[0]["status"])

print("\n== avisos (WhatsApp simulado)")
for a in sql("SELECT paciente_id, texto FROM avisos ORDER BY id"):
    print("  ", a["paciente_id"], "→", a["texto"])
print("\n== registro de aprovações")
for l in open("registros/aprovacoes.jsonl", encoding="utf-8").read().splitlines()[-2:]:
    l = json.loads(l); print(f"   {l['laudo_id']} {l['acao']} por {l['revisor']} em {l['tempo_revisao_s']}s · edição {l['tamanho_edicao']}")

# ---- portal do paciente do L92
pub = sql("SELECT * FROM publicacoes WHERE laudo_id='L92'")[0]
pac = sql("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"])[0]
pa = cliente()
print("\n== portal: link sozinho não abre:", "Data de nascimento" in pa.open(B + f"/p/{pub['token']}").read().decode())
try:
    post(pa, f"/p/{pub['token']}", {"nascimento": "2000-01-01"})
except Exception:
    pass
print("   data errada recusada:", not sql("SELECT * FROM codigos WHERE token=?", pub["token"]))
post(pa, f"/p/{pub['token']}", {"nascimento": pac["nascimento"]})
codigo = sql("SELECT codigo FROM codigos WHERE token=?", pub["token"])[0]["codigo"]
post(pa, f"/p/{pub['token']}/codigo", {"codigo": "000000" if codigo != "000000" else "111111"})
print("   código errado recusado (tentativas):", sql("SELECT tentativas FROM codigos WHERE token=?", pub["token"])[0]["tentativas"])
h = post(pa, f"/p/{pub['token']}/codigo", {"codigo": codigo}).read().decode()
print("   entrou no portal:", pub["exame"] in h, "| código de uso único apagado:", not sql("SELECT * FROM codigos WHERE token=?", pub["token"]))
print("   explicação visível:", "nódulo" in h, "| dúvidas aprovadas visíveis:", h.count("<details>"))

perguntas = sys.argv[1:] or ["O que é a tireoide?"]
for p in perguntas:
    t0 = time.time()
    h = post(pa, "/portal/chat", {"pergunta": p}).read().decode()
    ult = sql("SELECT autor, texto, tipo FROM chat WHERE token=? ORDER BY id DESC LIMIT 1", pub["token"])[0]
    print(f"\n   P: {p}\n   R ({ult['tipo']}, {time.time() - t0:.1f}s): {ult['texto']}")
print("\n== fila:", [(f["tipo"], f["destino_sugerido"], f["prioridade"], f["pergunta"][:40]) for f in sql("SELECT * FROM fila")])
print("== alertas abertos:", [(a["tipo"], a["descricao"][:60]) for a in sql("SELECT * FROM alertas WHERE status='aberto'")])
