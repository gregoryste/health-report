"""Teste offline do roteamento: os ramos dos fluxos do n8n batem com a tabela ROTAS do serviço. Não chama a LLM, nem a Meta, nem o n8n de verdade.

  .venv/bin/python testes/teste_rotas_n8n.py

Sobe o serviço num thread (porta livre, banco TEMPORÁRIO, WHATSAPP_MODO=simulado) e um "n8n falso" que faz o que os
fluxos 1–3 vão fazer: chama o serviço com ?efeitos=0 e decide o ramo (IF prioridade = crítico, IF status enviado/
simulado, Switch tipo_final). Os ramos do n8n falso estão escritos à mão, de propósito, e não lidos de ROTAS: assim o
teste compara duas implementações. A coerência com os JSON dos fluxos fica na parte 2.7.

Cobre: laudo crítico/alterado e dúvidas d/c/a nos modos interno e n8n (estado final igual); falha de envio;
idempotência das rotas de ação; chave da API; compatibilidade de /api/laudos sem ?efeitos.
A LLM é substituída por respostas fixas, e qualquer chamada a nucleo.chamar_interna derruba o teste.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASTA = tempfile.mkdtemp()
CHAVE = "chave-de-teste"
os.environ.update(BANCO=os.path.join(PASTA, "inicial.db"), REGISTRO_APROVACOES=os.path.join(PASTA, "registro.jsonl"),
                  WHATSAPP_MODO="simulado", ORQUESTRADOR="interno", SERVICO_API_KEY=CHAVE, LLM_PAUSA="0",
                  LLM_BASE_URL="http://127.0.0.1:9", LLM_TOKEN="teste", PORTAL_PACIENTE="0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chatbot  # noqa: E402
import nucleo  # noqa: E402
import tradutor  # noqa: E402

CHAMADAS_LLM = []


def llm_proibida(*a, **k):
    CHAMADAS_LLM.append(a[:1])
    raise RuntimeError("teste offline: chamada à LLM bloqueada")


nucleo.chamar_interna = llm_proibida
N_RASCUNHO = [0]


def rascunho_fixo(laudo, *a, **k):
    N_RASCUNHO[0] += 1
    return {"rascunho_id": f"R{N_RASCUNHO[0]}-{laudo['id']}", "prioridade": laudo["_prioridade"],
            "prazo_revisao": "teste", "verificacao": {"alertas": []}, "explicacao": "e", "duvidas": []}


TIPO_POR_PALAVRA = {"peito": "d", "consulta": "c", "LDL": "a"}


def atender_fixo(pergunta, cenario, base, pausa=3.0, gravar_fila=True, fila_fn=None):
    tipo = next(t for k, t in TIPO_POR_PALAVRA.items() if k in pergunta)
    fila = (fila_fn(pergunta, cenario, {"tipo": tipo, "destino": "medico", "prioridade": "alta"}, "", [], "teste")
            if tipo in "cd" else None)
    return {"tipo_final": tipo, "mensagem_ao_paciente": f"resposta {tipo} [A1]", "fila": fila, "chamadas_llm": 0}


tradutor.gerar_rascunho = rascunho_fixo
chatbot.atender = atender_fixo

from app import avisos, banco, servico as s  # noqa: E402

STATUS_PROXIMO = [None]     # status que o próximo envio simulado devolve (None: o do envio simulado de verdade)
_enviar_original = avisos.enviar


def enviar_controlado(pac, texto):
    status = _enviar_original(pac, texto)
    return STATUS_PROXIMO[0] or status


avisos.enviar = enviar_controlado

falhas = []
n_ok = [0]


def confere(cond, rotulo):
    if cond:
        n_ok[0] += 1
        print(f"  ok   {rotulo}")
    else:
        falhas.append(rotulo)
        print(f"  FALHA {rotulo}")


def porta_livre():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def http(url, corpo=None, chave=CHAVE):
    cab = {"Content-Type": "application/json"}
    if chave:
        cab["X-API-Key"] = chave
    req = urllib.request.Request(url, data=json.dumps(corpo or {}).encode(), headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


# ------------------------------------------------------------------ serviço e n8n falso

import uvicorn  # noqa: E402

P_SERVICO, P_N8N = porta_livre(), porta_livre()
SERVICO = f"http://127.0.0.1:{P_SERVICO}"
s.CFG["n8n_url"] = f"http://127.0.0.1:{P_N8N}"
servidor = uvicorn.Server(uvicorn.Config(s.app, host="127.0.0.1", port=P_SERVICO, log_level="warning"))
threading.Thread(target=servidor.run, daemon=True).start()
EXECUCOES = []               # (webhook, ramo) seguidos pelo n8n falso


class N8nFalso(BaseHTTPRequestHandler):
    """Os ramos planejados para os fluxos 1, 2 e 3 (Fase 2), escritos à mão."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        nome = self.path.rsplit("/", 1)[-1]
        if nome == "laudo":                                     # fluxo 1: IF prioridade = crítico
            _, r = http(SERVICO + "/api/laudos?efeitos=0", corpo)
            ramo = "critico" if r.get("prioridade") == "critico" else "outro"
            if ramo == "critico":
                http(SERVICO + "/api/acoes/contato-ativo", {"rascunho_id": r["rascunho_id"]})
        elif nome == "laudo-aprovado":                          # fluxo 2: IF status é enviado ou simulado
            _, r = http(SERVICO + "/api/avisos/publicacao", corpo)
            ramo = "ok" if r.get("status") in ("enviado", "simulado") else "falha"
            if ramo == "falha":
                http(SERVICO + "/api/acoes/falha", {"origem": "aviso", "laudo_id": corpo["laudo_id"],
                                                     "detalhe": r.get("status")})
        elif nome == "duvida":                                  # fluxo 3: Switch tipo_final
            _, r = http(SERVICO + "/api/duvidas?efeitos=0", corpo)
            ramo = r.get("tipo_final")
            if ramo == "d":
                http(SERVICO + "/api/acoes/urgencia", {"token": r["token"], "pergunta": r["pergunta"],
                                                        "fila_id": r["fila_id"]})
        else:
            self.send_response(404)
            self.end_headers()
            return
        EXECUCOES.append((nome, ramo))
        dados = json.dumps(r).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)


n8n = ThreadingHTTPServer(("127.0.0.1", P_N8N), N8nFalso)
threading.Thread(target=n8n.serve_forever, daemon=True).start()
for _ in range(100):
    try:
        urllib.request.urlopen(SERVICO + "/api/saude", timeout=1)
        break
    except Exception:
        time.sleep(0.1)


# ------------------------------------------------------------------ a cena, igual nos dois modos

def novo_banco(nome):
    banco.ARQUIVO = os.path.join(PASTA, nome + ".db")
    banco.iniciar()
    for pid, nome_p in (("P01", "Paciente Fictício Um"), ("P02", "Paciente Fictício Dois")):
        banco.executar("INSERT INTO pacientes (id, nome, nascimento, telefone, cpf) VALUES (?,?,?,?,?)",
                       pid, nome_p, "1970-01-01", "+55 51 90000-000" + pid[-1], "000")
    for lid, pid, tok in (("L-DUV", "P01", "tok-duvida"), ("L-AV", "P02", "tok-aviso"), ("L-FALHA", "P01", "tok-falha")):
        banco.executar("INSERT INTO publicacoes (laudo_id, paciente_id, token, exame, explicacao, duvidas_json, "
                       "duvidas_liberadas, revisor, publicado_em) VALUES (?,?,?,?,?,?,?,?,?)", lid, pid, tok,
                       "Exame de teste", "Explicação aprovada.", "[]", 1, "teste", "2026-01-01T00:00:00")


def entrar_laudo(modo, lid, prioridade):
    laudo = {"paciente_id": "P01", "laudo": {"id": lid, "exame": "Exame " + lid, "_prioridade": prioridade}}
    if modo == "n8n":
        return http(s.CFG["n8n_url"] + "/webhook/laudo", laudo, chave=None)
    return http(SERVICO + "/api/laudos", laudo)              # modo interno: o serviço cria o alerta sozinho


def cena(modo):
    novo_banco(modo)
    s.CFG["orquestrador"] = modo
    EXECUCOES.clear()
    entrar_laudo(modo, "L1", "critico")
    entrar_laudo(modo, "L2", "alterado")
    entrar_laudo(modo, "L1", "critico")                      # o mesmo laudo crítico de novo: sem alerta duplicado
    respostas = {p: s._duvida_pelo_orquestrador("tok-duvida", p)
                 for p in ("Estou com dor no peito", "Quero ver isso na consulta", "O que é LDL?")}
    STATUS_PROXIMO[0] = None
    s.notificar_publicacao("L-AV")                           # envio ok (simulado)
    STATUS_PROXIMO[0] = "erro 131026"
    s.notificar_publicacao("L-FALHA")                        # envio falhou
    STATUS_PROXIMO[0] = None
    q = lambda sql: [tuple(r.values()) for r in banco.todos(sql)]
    return {
        "alertas": q("SELECT tipo, descricao, paciente_id, referencia, status FROM alertas ORDER BY tipo, referencia"),
        "fila": q("SELECT token, pergunta, tipo, status FROM fila ORDER BY id"),
        "chat": q("SELECT autor, texto, tipo, fila_id FROM chat ORDER BY id"),
        "avisos": q("SELECT paciente_id, texto, status FROM avisos ORDER BY id"),
        "rascunhos": q("SELECT laudo_id, status, prioridade FROM rascunhos ORDER BY rascunho_id"),
        "respostas": {p: (r["mensagem"], r["tipo_final"]) for p, r in respostas.items()},
        "execucoes": list(EXECUCOES),
    }


print("1. Modo interno (plano B: o serviço decide pela tabela ROTAS)")
interno = cena("interno")
tipos = [a[0] for a in interno["alertas"]]
confere(tipos.count("contato_ativo") == 1, "laudo crítico → 1 alerta de contato ativo (repetido não duplica)")
confere(not any(a[0] == "contato_ativo" and a[3] == "L2" for a in interno["alertas"]), "laudo alterado → sem alerta")
confere(tipos.count("urgencia") == 1, "dúvida d → 1 alerta de urgência")
confere([f[2] for f in interno["fila"]] == ["d", "c"], "dúvidas d e c na fila; a fora da fila")
confere(interno["respostas"]["O que é LDL?"] == ("resposta a", "a"), "dúvida a → só a resposta (sem código da fonte)")
confere(tipos.count("falha_envio") == 1 and any(a[3] == "L-FALHA" for a in interno["alertas"]),
        "envio com erro → 1 alerta de falha no envio")
confere(not any(a[3] == "L-AV" for a in interno["alertas"]), "envio simulado → sem alerta")
confere(interno["execucoes"] == [], "modo interno não passa pelo n8n")

print("2. Modo n8n (o serviço só devolve fatos; o n8n falso decide o ramo e chama as ações)")
modo_n8n = cena("n8n")
confere(modo_n8n["execucoes"] == [("laudo", "critico"), ("laudo", "outro"), ("laudo", "critico"), ("duvida", "d"),
                                  ("duvida", "c"), ("duvida", "a"), ("laudo-aprovado", "ok"),
                                  ("laudo-aprovado", "falha")], "cada chamada seguiu o ramo esperado no n8n")
for chave in ("alertas", "fila", "chat", "avisos", "rascunhos", "respostas"):
    confere(modo_n8n[chave] == interno[chave], f"{chave}: igual ao modo interno")

print("3. Rotas de ação: idempotência e chave da API (banco do modo n8n)")
conta = lambda t: banco.um("SELECT COUNT(*) c FROM alertas WHERE tipo=?", t)["c"]
rid = banco.um("SELECT rascunho_id FROM rascunhos WHERE laudo_id='L1' ORDER BY rascunho_id")["rascunho_id"]
fid = banco.um("SELECT id FROM fila WHERE tipo='d'")["id"]
antes = {t: conta(t) for t in ("contato_ativo", "urgencia", "falha_envio", "falha_orquestracao")}
st, r = http(SERVICO + "/api/acoes/contato-ativo", {"rascunho_id": rid})
confere(st == 200 and r == {"ok": True, "novo": False} and conta("contato_ativo") == antes["contato_ativo"],
        "contato-ativo repetido → novo:false, sem alerta a mais")
st, r = http(SERVICO + "/api/acoes/urgencia", {"token": "tok-duvida", "pergunta": "Estou com dor no peito",
                                               "fila_id": fid})
confere(st == 200 and r["novo"] is False and conta("urgencia") == antes["urgencia"], "urgência repetida → novo:false")
st, r = http(SERVICO + "/api/acoes/falha", {"origem": "aviso", "laudo_id": "L-FALHA", "detalhe": "erro 131026"})
confere(st == 200 and r == {"ok": True, "tipo": "falha_envio", "novo": False}, "falha de envio repetida → novo:false")
corpo_falha = {"origem": "Pista da dúvida", "detalhe": "Nó Serviço: timeout\n{\"explicacao\": \"dado do paciente\"}"}
st1, r1 = http(SERVICO + "/api/acoes/falha", corpo_falha)
st2, r2 = http(SERVICO + "/api/acoes/falha", corpo_falha)
desc = banco.um("SELECT descricao FROM alertas WHERE tipo='falha_orquestracao'")["descricao"]
confere(r1["novo"] is True and r2["novo"] is False and conta("falha_orquestracao") == 1,
        "falha de orquestração: 1 alerta, a repetição não duplica")
confere("explicacao" not in desc and len(desc) < 220, "texto da falha só com a 1ª linha (sem corpo de resposta)")
confere(http(SERVICO + "/api/acoes/contato-ativo", {"rascunho_id": "nao-existe"})[0] == 404, "rascunho inexistente → 404")
confere(http(SERVICO + "/api/acoes/urgencia", {"token": "tok-duvida"})[0] == 422, "urgência sem fila_id → 422")
confere(all(http(SERVICO + r, {}, chave=None)[0] == 401 for r in
            ("/api/acoes/contato-ativo", "/api/acoes/urgencia", "/api/acoes/falha", "/api/laudos", "/api/duvidas")),
        "sem X-API-Key → 401 nas rotas da API")

print("4. Compatibilidade e fatos")
novo_banco("compat")
st, r = http(SERVICO + "/api/laudos", {"paciente_id": "P01", "laudo": {"id": "LX", "exame": "X", "_prioridade": "critico"}})
confere(st == 200 and conta("contato_ativo") == 1, "/api/laudos sem ?efeitos cria o alerta como antes")
st, r = http(SERVICO + "/api/laudos?efeitos=0",
             {"paciente_id": "P01", "laudo": {"id": "LY", "exame": "Y", "_prioridade": "critico"}})
confere(st == 200 and conta("contato_ativo") == 1, "/api/laudos?efeitos=0 não cria alerta")
confere({"rascunho_id", "prioridade", "laudo_id", "paciente_id"} <= set(r), "fatos do laudo completos")
st, r = http(SERVICO + "/api/duvidas?efeitos=0", {"token": "tok-duvida", "pergunta": "dor no peito"})
confere(st == 200 and conta("urgencia") == 0 and r["tipo_final"] == "d", "/api/duvidas?efeitos=0 não cria alerta")
confere({"tipo_final", "fila_id", "token", "pergunta", "paciente_id", "laudo_id", "mensagem"} <= set(r),
        "fatos da dúvida completos")

print("5. Coerência n8n × Python: os IF/Switch dos fluxos (JSON) batem com a tabela ROTAS")
import copy  # noqa: E402
import glob  # noqa: E402
import re  # noqa: E402

FLUXOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "n8n", "fluxos")
PISTAS = {"laudo": "/api/laudos", "duvida": "/api/duvidas", "publicacao": "/api/avisos/publicacao"}
ACOES = {"contato_ativo", "urgencia", "falha_envio"}       # destinos da ROTAS que fazem algo a mais (um alerta)


def acao_do_no(no):
    url = no["parameters"].get("url", "")
    if "/api/acoes/contato-ativo" in url:
        return "contato_ativo"
    if "/api/acoes/urgencia" in url:
        return "urgencia"
    if "/api/acoes/falha" in url:
        return "falha_envio" if "'aviso'" in no["parameters"].get("jsonBody", "") else "falha_orquestracao"
    return None


def acao_da_saida(fluxo, no_nome, saida):
    """Ação (rota /api/acoes/*) alcançável a partir de uma saída de um nó, até a resposta ou o fim."""
    nos = {n["name"]: n for n in fluxo["nodes"]}
    ligacoes = fluxo["connections"].get(no_nome, {}).get("main", [])
    fila = [c["node"] for c in (ligacoes[saida] if saida < len(ligacoes) else [])]
    vistos, acoes = set(), set()
    while fila:
        nome = fila.pop(0)
        if nome in vistos:
            continue
        vistos.add(nome)
        a = acao_do_no(nos[nome])
        if a:
            acoes.add(a)
        for saidas in fluxo["connections"].get(nome, {}).get("main", []):
            fila += [c["node"] for c in saidas]
    if len(acoes) > 1:
        raise AssertionError(f"saída {saida} de '{no_nome}' leva a mais de uma ação: {acoes}")
    return acoes.pop() if acoes else None


def campo_da_condicao(cond):
    m = re.fullmatch(r"=\{\{\s*\$json\.(\w+)\s*\}\}", cond["leftValue"])
    if not m or cond["operator"]["operation"] != "equals":
        raise AssertionError(f"condição inesperada: {cond}")
    return m.group(1)


def rotas_dos_fluxos(pasta):
    """Reconstrói, a partir dos JSON, uma tabela no formato de ROTAS (só com as ações que geram alerta)."""
    fluxos = [json.load(open(c, encoding="utf-8")) for c in sorted(glob.glob(os.path.join(pasta, "*.json")))]
    rotas = {}
    for pista, rota in PISTAS.items():
        achados = [(f, n) for f in fluxos for n in f["nodes"]
                   if n["type"].endswith("httpRequest") and rota in n["parameters"].get("url", "")]
        if len(achados) != 1:
            raise AssertionError(f"{pista}: esperado 1 nó chamando {rota}, achei {len(achados)}")
        fluxo, http_no = achados[0]
        seguintes = fluxo["connections"][http_no["name"]]["main"][0]
        decisao = {n["name"]: n for n in fluxo["nodes"]}[seguintes[0]["node"]]
        if decisao["type"].endswith(".if"):
            conds = decisao["parameters"]["conditions"]
            campos = {campo_da_condicao(c) for c in conds["conditions"]}
            valores = [c["rightValue"] for c in conds["conditions"]]
            if len(valores) > 1 and conds["combinator"] != "or":
                raise AssertionError(f"{pista}: IF com várias igualdades precisa de 'or'")
            sim, nao = acao_da_saida(fluxo, decisao["name"], 0), acao_da_saida(fluxo, decisao["name"], 1)
            rotas[pista] = {"campo": campos.pop() if len(campos) == 1 else campos,
                            "ramos": {v: sim for v in valores}, "padrao": nao, "url": http_no["parameters"]["url"]}
        elif decisao["type"].endswith(".switch"):
            regras = decisao["parameters"]["rules"]["values"]
            campos = {campo_da_condicao(c) for r in regras for c in r["conditions"]["conditions"]}
            ramos = {r["conditions"]["conditions"][0]["rightValue"]: acao_da_saida(fluxo, decisao["name"], i)
                     for i, r in enumerate(regras)}
            extra = decisao["parameters"].get("options", {}).get("fallbackOutput") == "extra"
            rotas[pista] = {"campo": campos.pop() if len(campos) == 1 else campos, "ramos": ramos,
                            "padrao": acao_da_saida(fluxo, decisao["name"], len(regras)) if extra else None,
                            "url": http_no["parameters"]["url"]}
        else:
            raise AssertionError(f"{pista}: depois de {rota} vem '{decisao['type']}', e não um IF/Switch")
    return rotas


def rotas_do_python(rotas):
    so_acao = lambda a: a if a in ACOES else None
    return {p: {"campo": r["campo"], "ramos": {v: so_acao(a) for v, a in r["ramos"].items()},
                "padrao": so_acao(r["padrao"])} for p, r in rotas.items()}


def diferencas(do_n8n, do_python):
    erros = []
    for pista in PISTAS:
        a, b = do_n8n.get(pista), do_python.get(pista)
        if a is None or b is None:
            erros.append(f"{pista}: falta de um dos lados")
            continue
        for k in ("campo", "ramos", "padrao"):
            if a[k] != b[k]:
                erros.append(f"{pista}.{k}: n8n={a[k]} × Python={b[k]}")
    return erros


do_n8n = rotas_dos_fluxos(FLUXOS)
do_python = rotas_do_python(s.ROTAS)
erros = diferencas(do_n8n, do_python)
confere(not erros, "fluxos do n8n e ROTAS iguais (mesmo campo, mesmos valores, mesmos destinos)" +
        ("" if not erros else ": " + "; ".join(erros)))
confere(all("efeitos=0" in do_n8n[p]["url"] for p in ("laudo", "duvida")),
        "laudo e dúvida chamam o serviço com ?efeitos=0 (senão o alerta sairia duas vezes)")

# prova de que a comparação pega quem mudar só um lado: cópias temporárias, uma de cada lado
copia = tempfile.mkdtemp()
for c in glob.glob(os.path.join(FLUXOS, "*.json")):
    d = json.load(open(c, encoding="utf-8"))
    for n in d["nodes"]:
        if n["type"].endswith(".switch"):               # o ramo d do Switch passa a ir direto para a junção
            ligacoes = d["connections"][n["name"]]["main"]
            idx = [r["conditions"]["conditions"][0]["rightValue"] for r in n["parameters"]["rules"]["values"]].index("d")
            ligacoes[idx] = [{"node": "Juntar os caminhos", "type": "main", "index": idx}]
    json.dump(d, open(os.path.join(copia, os.path.basename(c)), "w", encoding="utf-8"), ensure_ascii=False)
confere(bool(diferencas(rotas_dos_fluxos(copia), do_python)), "mudar só o fluxo (d sem alerta) → o teste acusa")
rotas_mudadas = copy.deepcopy(s.ROTAS)
rotas_mudadas["laudo"]["ramos"]["alterado"] = "contato_ativo"
confere(bool(diferencas(do_n8n, rotas_do_python(rotas_mudadas))), "mudar só a ROTAS (alterado → contato ativo) → o teste acusa")

print("6. Nenhuma chamada à LLM")
confere(CHAMADAS_LLM == [], "nucleo.chamar_interna nunca foi chamada")

servidor.should_exit = True
n8n.shutdown()
print(f"\n{n_ok[0]} verificações, {len(falhas)} falhas")
print("TUDO OK" if not falhas else "FALHAS:\n  " + "\n  ".join(falhas))
sys.exit(1 if falhas else 0)
