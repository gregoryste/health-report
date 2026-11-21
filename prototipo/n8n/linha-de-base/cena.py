"""Cena-padrão da linha de base (PLANO-N8N-DECISOES.md, tarefas 0.4, 6.5, 6.6 e 6.7). Não chama a LLM nem a Meta.

Uso (de dentro de prototipo/, com o .venv):
  python n8n/linha-de-base/cena.py preparar --origem <banco_pristino.db> --registro-origem <aprovacoes.jsonl> --pasta <dir>
      copia o banco e o registro para <dir>/cena.db e <dir>/aprovacoes.jsonl e semeia a cena:
      R1 = L04 (alterado, P02), R2 = L06 (crítico, P04), R3 = L05 (alterado, P06, fica pendente para as rotinas),
      um item da fila tipo d (P02) com o alerta de urgência aberto. Os rascunhos vêm de uma rodada salva
      (rascunhos/2026-11-14_etapa7_jackson_r2), então nada passa pela LLM.
  (subir o serviço de teste com BANCO=<dir>/cena.db REGISTRO_APROVACOES=<dir>/aprovacoes.jsonl ...)
  python n8n/linha-de-base/cena.py http --url http://127.0.0.1:8001 --senhas <arquivo> --saida <arquivo.txt>
      códigos HTTP de todas as páginas e rotas, como médico, como administração e sem login.
  python n8n/linha-de-base/cena.py cena --url http://127.0.0.1:8001 --senhas <arquivo>
      aprova R1 com edição, aprova R2 sem edição, responde o item da fila, roda rotinas com 0 e com 3 dias.
  python n8n/linha-de-base/cena.py fotografar --pasta <dir> --saida <arquivo.json>
      estado depois da cena (alertas, avisos, fila, rascunhos, publicações, registro), sem datas nem tokens.

O arquivo de senhas (fora do projeto, no scratchpad) tem uma linha "login senha" por conta de teste;
as contas teste.medico e teste.admin só existem na cópia do banco.
"""
import argparse
import http.cookiejar
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(os.path.dirname(AQUI))
RODADA = os.path.join(PROTO, "rascunhos", "2026-11-14_etapa7_jackson_r2")
SEMENTE = [("R1", "L04", "P02"), ("R2", "L06", "P04"), ("R3", "L05", "P06")]
TOKEN_FILA = "tok-cena-P02"


def agora():
    return datetime.now().isoformat(timespec="seconds")


def laudo_json(lid):
    for nome in os.listdir(os.path.join(PROTO, "laudos")):
        if nome.startswith(lid + "_"):
            return json.load(open(os.path.join(PROTO, "laudos", nome), encoding="utf-8"))
    raise FileNotFoundError(lid)


def preparar(a):
    os.makedirs(a.pasta, exist_ok=True)
    db = os.path.join(a.pasta, "cena.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(db + suf):
            os.remove(db + suf)
    origem = sqlite3.connect(f"file:{a.origem}?mode=ro", uri=True)
    destino = sqlite3.connect(db)
    origem.backup(destino)
    origem.close()
    shutil.copyfile(a.registro_origem, os.path.join(a.pasta, "aprovacoes.jsonl"))
    c = destino
    ids = {}
    # a fotografia só olha o que a cena cria (os avisos antigos têm telefone e resposta da Meta no detalhe)
    antes = {f"{t}_max_id": c.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}").fetchone()[0]
             for t in ("avisos", "alertas", "fila", "chat")}
    for rotulo, lid, pid in SEMENTE:
        d = json.load(open(os.path.join(RODADA, f"{lid}.json"), encoding="utf-8"))
        d["status"] = "aguardando_revisao"
        c.execute("INSERT OR REPLACE INTO laudos VALUES (?,?,?,?)", (lid, pid, json.dumps(laudo_json(lid), ensure_ascii=False), agora()))
        c.execute("DELETE FROM publicacoes WHERE laudo_id=?", (lid,))
        c.execute("INSERT OR REPLACE INTO rascunhos VALUES (?,?,?,?,?,?,?,?)",
                  (d["rascunho_id"], lid, json.dumps(d, ensure_ascii=False), "aguardando_revisao", d["prioridade"],
                   d["prazo_revisao"], agora(), None))
        ids[rotulo] = d["rascunho_id"]
    # item da fila tipo d com o alerta de urgência aberto (como processar_duvida deixaria), numa publicação de P02
    c.execute("INSERT OR REPLACE INTO publicacoes (laudo_id, paciente_id, token, exame, explicacao, duvidas_json, "
              "duvidas_liberadas, revisor, publicado_em, lido_em, lembretes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              ("L-CENA", "P02", TOKEN_FILA, "Exame da cena", "Explicação aprovada da cena.", "[]", 1, "cena",
               agora(), agora(), 1))
    cur = c.execute("INSERT INTO fila (token, pergunta, tipo, destino_sugerido, prioridade, motivo, rascunho, fontes, "
                    "status, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (TOKEN_FILA, "Estou com dor no peito forte agora", "d", "medico", "alta", "lista de alarme",
                     "", "[]", "aguardando", agora()))
    fid = cur.lastrowid
    c.execute("INSERT INTO alertas (tipo, descricao, paciente_id, referencia, status, criado_em) VALUES (?,?,?,?,?,?)",
              ("urgencia", "SINAL DE ALARME (cena)", "P02", str(fid), "aberto", agora()))
    c.commit()
    c.close()
    json.dump({**ids, "fila_id": fid, **antes}, open(os.path.join(a.pasta, "cena_ids.json"), "w"), indent=1)
    print(f"cena preparada em {db}: {ids}, fila_id={fid}")


# ------------------------------------------------------------------ HTTP

class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def cliente():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), SemRedirecionar())


def pedir(op, url, dados=None, cab=None):
    corpo = urllib.parse.urlencode(dados).encode() if isinstance(dados, dict) else dados
    req = urllib.request.Request(url, data=corpo, headers=cab or {})
    try:
        with op.open(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def senhas(arquivo):
    return dict(l.split(None, 1) for l in open(arquivo).read().split("\n") if l.strip())


def logar(url, login, senha):
    op = cliente()
    st, _ = pedir(op, url + "/painel/login", {"login": login, "senha": senha})
    if st != 303:
        sys.exit(f"login {login} falhou ({st})")
    return op


def alvos(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rid = c.execute("SELECT rascunho_id FROM rascunhos ORDER BY rascunho_id LIMIT 1").fetchone()
    tok = c.execute("SELECT token FROM publicacoes ORDER BY laudo_id LIMIT 1").fetchone()
    eid = c.execute("SELECT id FROM envios ORDER BY id LIMIT 1").fetchone()
    c.close()
    return (rid or ["x"])[0], (tok or ["x"])[0], (eid or [0])[0]


def http_codigos(a):
    s = senhas(a.senhas)
    rid, tok, eid = alvos(a.banco)
    paginas = ["/", "/painel/login", "/painel", f"/painel/rascunho/{rid}", "/painel/rascunho/nao-existe",
               f"/painel/envio/{eid}", "/painel/fila", "/painel/whatsapp", "/painel/registro", "/painel/equipe",
               f"/painel/publicado/{tok}", "/painel/publicado/nao-existe", f"/p/{tok}", f"/p/{tok}/codigo", "/portal",
               "/webhook/whatsapp", "/api/saude", "/docs", "/openapi.json", "/static/estilo.css"]
    # POST na API sem chave: só o código (401); com chave chamariam a LLM ou mandariam aviso
    api_post = ["/api/laudos", "/api/avisos/publicacao", "/api/duvidas", "/api/rotinas"]
    linhas = []
    for quem in ("sem_login", "teste.medico", "teste.admin"):
        op = cliente() if quem == "sem_login" else logar(a.url, quem, s[quem])
        for p in paginas:
            st, _ = pedir(op, a.url + p)
            linhas.append(f"{quem:<13} GET  {p:<40} {st}")
        if quem == "sem_login":
            for p in api_post:
                st, _ = pedir(op, a.url + p, b"{}", {"Content-Type": "application/json"})
                linhas.append(f"{quem:<13} POST {p:<40} {st}")
    mascara = lambda l: l.replace(rid, "<id>").replace(tok, "<token>")
    texto = "\n".join(mascara(l) for l in linhas)
    open(a.saida, "w").write(texto + "\n")
    print(texto)


def cena(a):
    s = senhas(a.senhas)
    ids = json.load(open(os.path.join(a.pasta, "cena_ids.json")))
    op = logar(a.url, "teste.medico", s["teste.medico"])
    passos = []
    for rotulo, editar in (("R1", True), ("R2", False)):
        st, html = pedir(op, f"{a.url}/painel/rascunho/{ids[rotulo]}")
        d = json.loads(sqlite3.connect(f"file:{a.banco}?mode=ro", uri=True).execute(
            "SELECT json FROM rascunhos WHERE rascunho_id=?", (ids[rotulo],)).fetchone()[0])
        form = {"acao": "aprovar", "explicacao": d["explicacao"] + (" (Texto revisado pela equipe.)" if editar else ""),
                "liberar_duvidas": "1", "aberto_em": "0"}
        for k, du in enumerate(d["duvidas"]):
            form.update({f"manter_{k}": "1", f"p_{k}": du["pergunta"], f"r_{k}": du["resposta"]})
        st2, _ = pedir(op, f"{a.url}/painel/rascunho/{ids[rotulo]}", form)
        passos.append(f"aprovar {rotulo} ({'com' if editar else 'sem'} edição): GET {st} POST {st2}")
    st, _ = pedir(op, f"{a.url}/painel/fila/{ids['fila_id']}",
                  {"acao": "responder", "resposta": "Procure o pronto-socorro agora. A equipe vai ligar.",
                   "destino_final": "medico"})
    passos.append(f"responder fila {ids['fila_id']}: POST {st}")
    for dias in (0, 3):
        st, _ = pedir(op, f"{a.url}/painel/rotinas", {"dias": str(dias)})
        passos.append(f"rotinas {dias} dias: POST {st}")
    print("\n".join(passos))


def fotografar(a):
    c = sqlite3.connect(f"file:{a.banco}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    marca = json.load(open(os.path.join(a.pasta, "cena_ids.json")))
    q = lambda sql, *p: [dict(r) for r in c.execute(sql, p)]
    tira = lambda t: re.sub(r"https?://\S+/p/\S+", "<link>", t or "")
    foto = {
        "alertas_novos": q("SELECT tipo, paciente_id, referencia, status, resolvido_por FROM alertas WHERE id>? "
                           "ORDER BY tipo, paciente_id, referencia, status", marca["alertas_max_id"]),
        "alertas_antigos_mudados": q("SELECT tipo, paciente_id, referencia, status FROM alertas WHERE id<=? AND "
                                     "status<>'resolvido'", marca["alertas_max_id"]),
        "alertas_abertos_por_tipo": q("SELECT tipo, COUNT(*) n FROM alertas WHERE status='aberto' GROUP BY tipo ORDER BY tipo"),
        "alertas_duplicados": q("SELECT tipo, referencia, COUNT(*) n FROM alertas WHERE status='aberto' GROUP BY tipo, referencia HAVING n>1"),
        "avisos_novos": [{**r, "texto": tira(r["texto"])} for r in
                   q("SELECT paciente_id, canal, status, detalhe, texto FROM avisos WHERE id>? ORDER BY id",
                     marca["avisos_max_id"])],
        "fila_da_cena": q("SELECT id, tipo, status, destino_final, respondido_por, resposta_final FROM fila WHERE id>? "
                          "ORDER BY id", marca["fila_max_id"]),
        "fila_status": q("SELECT status, COUNT(*) n FROM fila GROUP BY status ORDER BY status"),
        "rascunhos": q("SELECT rascunho_id, laudo_id, status, prioridade FROM rascunhos ORDER BY rascunho_id"),
        "publicacoes": q("SELECT laudo_id, paciente_id, revisor, duvidas_liberadas, lembretes, lido_em IS NOT NULL lido "
                         "FROM publicacoes ORDER BY laudo_id"),
        "chat_da_cena": q("SELECT autor, texto, tipo FROM chat WHERE token=? ORDER BY id", TOKEN_FILA),
    }
    reg = [json.loads(l) for l in open(os.path.join(a.pasta, "aprovacoes.jsonl"), encoding="utf-8") if l.strip()]
    chaves = ("rascunho_id", "laudo_id", "acao", "revisor", "duvidas_liberadas", "prioridade")
    foto["registro_aprovacoes"] = [{k: r.get(k) for k in chaves if k in r} for r in reg]
    foto["registro_aprovacoes_linhas"] = len(reg)
    foto["contagens"] = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("alertas", "avisos", "fila", "rascunhos", "publicacoes", "chat", "pacientes")}
    foto["cena_ids"] = marca
    json.dump(foto, open(a.saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(foto["contagens"]), "| abertos:", foto["alertas_abertos_por_tipo"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("--origem", required=True)
    p.add_argument("--registro-origem", required=True)
    p.add_argument("--pasta", required=True)
    for nome in ("http", "cena", "fotografar"):
        p = sub.add_parser(nome)
        p.add_argument("--pasta", required=True)
        p.add_argument("--url", default="http://127.0.0.1:8001")
        p.add_argument("--senhas")
        p.add_argument("--saida")
    a = ap.parse_args()
    if a.cmd != "preparar":
        a.banco = os.path.join(a.pasta, "cena.db")
    {"preparar": preparar, "http": http_codigos, "cena": cena, "fotografar": fotografar}[a.cmd](a)


if __name__ == "__main__":
    main()
