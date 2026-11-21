"""Serviço do protótipo: API (usada pelo n8n), painel da equipe e portal do paciente.

Rodar (de dentro de prototipo/):  .venv/bin/uvicorn app.servico:app --port 8000
  Painel da equipe: http://localhost:8000/painel   (usuário e senha próprios: python -m app.usuarios criar ...)
  Portal: link enviado no aviso, /p/<token>

ORQUESTRADOR no .env:
  interno (padrão) o próprio serviço encadeia os passos (plano B da demo)
  n8n              publicação e dúvidas passam pelos fluxos do n8n (N8N_URL)
Só dados fictícios. Protótipo: sem HTTPS e com autenticação simplificada.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import chatbot
import nucleo as n
import registro
import tradutor
from regra import avaliar_laudo

from fastapi.responses import FileResponse

from . import avisos, banco, canal_whatsapp, leitura, origem, usuarios

DIR = os.path.dirname(os.path.abspath(__file__))
n.carregar_env()
CFG = {
    "base_url": os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/"),
    "orquestrador": os.environ.get("ORQUESTRADOR", "interno"),
    "n8n_url": os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/"),
    "api_key": os.environ.get("SERVICO_API_KEY", ""),
    "pausa": float(os.environ.get("LLM_PAUSA", "3")),
    # D3, 2ª revisão (14/11): o paciente é atendido pelo WhatsApp; o portal do paciente fica desligado (1 = religar)
    "portal_paciente": os.environ.get("PORTAL_PACIENTE", "0") == "1",
}

RECURSOS = {"sistema": n.ler_prompt(), "exemplos": n.carregar_exemplos(), "jargao": n.carregar_jargao(),
            "glossario": n.carregar_glossario(), "base": chatbot.carregar_base()}
ORDEM = {"critico": 0, "alterado": 1, "normal": 2}
PRAZO_DIAS = {"critico": 0, "alterado": 2, "normal": 3}   # D6 (dias corridos no protótipo)
SESSAO_MIN = 15                                          # portal: expira por inatividade
EM_ANDAMENTO = set()                                     # (token, pergunta) sendo processadas

app = FastAPI(title="Tradutor de laudos (protótipo)")
app.mount("/static", StaticFiles(directory=os.path.join(DIR, "static")), name="static")

PUBLICO_PELO_TUNEL = ("/p/", "/portal", "/webhook/whatsapp", "/static/")
PORTAL_PACIENTE = ("/p/", "/portal")


@app.middleware("http")
async def so_o_necessario_pelo_tunel(request: Request, chamar_proximo):
    """Pelo túnel público (o Cloudflare acrescenta cf-connecting-ip) só passam o portal do paciente e o webhook da Meta.
    Painel da equipe, API do n8n e documentação ficam só na máquina local.
    Com o portal do paciente desligado (padrão desde 14/11), as rotas dele só mostram que o atendimento é pelo WhatsApp."""
    caminho = request.url.path
    if "cf-connecting-ip" in request.headers and not caminho.startswith(PUBLICO_PELO_TUNEL):
        return PlainTextResponse("não encontrado", status_code=404)
    if not CFG["portal_paciente"] and caminho.startswith(PORTAL_PACIENTE):
        return tela(request, "aviso.html", titulo="Atendimento pelo WhatsApp",
                    texto="A explicação dos seus exames e as dúvidas agora são atendidas pelo WhatsApp da clínica. "
                          "Responda OI na conversa em que você recebeu o aviso.")
    return await chamar_proximo(request)
T = Jinja2Templates(directory=os.path.join(DIR, "templates"))
# Versão do CSS no link (?v=...): muda quando o arquivo muda, então o navegador nunca usa um CSS velho do cache.
T.env.globals["versao_css"] = lambda: int(os.path.getmtime(os.path.join(DIR, "static", "estilo.css")))
banco.iniciar()


def tela(request, nome, **ctx):
    s = ctx.get("s")
    if s and s["papel"] == "equipe":  # função de quem entrou e contadores das abas da barra do painel
        u = banco.um("SELECT funcao FROM usuarios WHERE login=?", s["token"] or "")
        ctx["funcao"] = usuarios.FUNCOES.get(u["funcao"], "Equipe clínica") if u else "Equipe clínica"
        ctx["eh_admin"] = bool(u and u["funcao"] == "admin")
        ctx["contagens"] = {
            "rascunhos": banco.um("SELECT COUNT(*) c FROM rascunhos WHERE status='aguardando_revisao'")["c"],
            "fila": banco.um("SELECT COUNT(*) c FROM fila WHERE status='aguardando'")["c"],
        }
    return T.TemplateResponse(request, nome, {"cfg": CFG, **ctx})

# ------------------------------------------------------------------ sessões

def criar_sessao(resp, papel, token=None, nome=None):
    s = secrets.token_urlsafe(24)
    banco.executar("INSERT INTO sessoes VALUES (?,?,?,?,?)", s, papel, token, nome, banco.agora())
    resp.set_cookie(f"sessao_{papel}", s, httponly=True, samesite="lax")  # equipe e paciente não se derrubam
    return resp


def sessao(request, papel):
    s = banco.um("SELECT * FROM sessoes WHERE sessao=? AND papel=?", request.cookies.get(f"sessao_{papel}", ""), papel)
    if not s:
        return None
    if papel == "equipe" and not banco.um("SELECT 1 x FROM usuarios WHERE login=? AND ativo=1", s["token"] or ""):
        return None  # sessão do login antigo (só nome) ou conta desativada
    if papel == "paciente" and datetime.now() - datetime.fromisoformat(s["visto_em"]) > timedelta(minutes=SESSAO_MIN):
        banco.executar("DELETE FROM sessoes WHERE sessao=?", s["sessao"])
        return None
    banco.executar("UPDATE sessoes SET visto_em=? WHERE sessao=?", banco.agora(), s["sessao"])
    return s


def exigir_api(chave):
    if CFG["api_key"] and chave != CFG["api_key"]:
        raise HTTPException(401, "chave da API inválida")

# ------------------------------------------------------------------ regras do fluxo

def alerta(tipo, descricao, paciente_id=None, referencia=None):
    """Abre um alerta no painel. Com referência, não duplica um alerta aberto igual. Devolve True se criou."""
    if referencia and banco.um("SELECT id FROM alertas WHERE tipo=? AND referencia=? AND status='aberto'",
                               tipo, referencia):
        return False
    banco.executar("INSERT INTO alertas (tipo, descricao, paciente_id, referencia, status, criado_em) "
                   "VALUES (?,?,?,?,?,?)", tipo, descricao, paciente_id, referencia, "aberto", banco.agora())
    return True


# Roteamento: o que fazer com o RESULTADO de cada pista. As regras clínicas (regra fixa, LLM, checagens,
# classificador) continuam nas pistas; aqui fica só o destino. É a mesma tabela dos nós IF/Switch dos fluxos do
# n8n: com ORQUESTRADOR=n8n quem decide é o fluxo, no modo interno (plano B) é rotear_*().
# testes/teste_rotas_n8n.py confere que os dois lados batem.
#   campo   o campo do resultado que decide o ramo
#   ramos   valor do campo → ação ("responder" e "fila" não criam nada a mais: a resposta e a fila já existem)
#   padrao  ação para qualquer outro valor (None = nada)
ROTAS = {
    "laudo": {"campo": "prioridade", "ramos": {"critico": "contato_ativo"}, "padrao": None},
    "duvida": {"campo": "tipo_final", "padrao": None,
               "ramos": {"a": "responder", "b": "responder", "c": "fila", "d": "urgencia", "e": "responder"}},
    "publicacao": {"campo": "status", "ramos": {"enviado": None, "simulado": None}, "padrao": "falha_envio"},
}


def destino(pista, resultado):
    rota = ROTAS[pista]
    return rota["ramos"].get(resultado.get(rota["campo"]), rota["padrao"])


def acao_contato_ativo(laudo_id):
    """D3: valor crítico não depende do clique do paciente. Idempotente (alerta() não duplica a referência)."""
    laudo = banco.um("SELECT * FROM laudos WHERE id=?", laudo_id)
    if not laudo:
        raise HTTPException(404, "laudo não encontrado")
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", laudo["paciente_id"])
    return alerta("contato_ativo", f"Laudo crítico ({banco.j(laudo['json'])['exame']}): ligar para {pac['nome']} ainda hoje",
           pac["id"], laudo_id)


def acao_urgencia(token, pergunta, fila_id):
    pub = banco.um("SELECT * FROM publicacoes WHERE token=?", token)
    if not pub:
        raise HTTPException(404, "publicação não encontrada")
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"])
    return alerta("urgencia", f"SINAL DE ALARME no chat de {pac['nome']}: “{pergunta[:120]}”", pac["id"], str(fila_id))


def acao_falha_envio(laudo_id, status):
    """Falha técnica (não clínica): o aviso de publicação não saiu. Sem dado de saúde no texto."""
    pub = banco.um("SELECT * FROM publicacoes WHERE laudo_id=?", laudo_id)
    if not pub:
        raise HTTPException(404, "publicação não encontrada")
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"])
    return alerta("falha_envio", f"O aviso para {pac['nome']} não foi enviado (status: {str(status)[:40]}). "
                          f"Conferir o WhatsApp e reenviar.", pac["id"], laudo_id)


def acao_falha_orquestracao(origem, detalhe):
    """Falha técnica de um fluxo do n8n (fluxo de erros). Texto curto: só a 1ª linha do detalhe, até 160 caracteres,
    para não carregar corpo de resposta (que poderia ter dado de saúde). Idempotente por origem + detalhe."""
    origem = re.sub(r"[^\w .:·-]", "", str(origem or "desconhecida"))[:60] or "desconhecida"
    detalhe = (str(detalhe or "").strip().splitlines() or [""])[0][:160]
    ref = origem + ":" + hashlib.sha1(detalhe.encode()).hexdigest()[:12]
    return alerta("falha_orquestracao", f"Falha na orquestração ({origem}): {detalhe or 'sem detalhe'}", None, ref)


def rotear_laudo(resultado):
    """resultado: {prioridade, laudo_id, ...} da pista do laudo."""
    if destino("laudo", resultado) == "contato_ativo":
        acao_contato_ativo(resultado["laudo_id"])


def rotear_duvida(resultado):
    """resultado: {tipo_final, token, pergunta, fila_id, ...} da pista da dúvida."""
    if destino("duvida", resultado) == "urgencia":
        acao_urgencia(resultado["token"], resultado["pergunta"], resultado["fila_id"])


def rotear_publicacao(resultado):
    """resultado: {status, laudo_id} do envio do aviso de publicação."""
    if destino("publicacao", resultado) == "falha_envio":
        acao_falha_envio(resultado["laudo_id"], resultado["status"])


def processar_laudo(paciente_id, laudo, efeitos=True):
    """Pista do laudo até o rascunho: regra fixa → LLM → checagens (tradutor.py) → fila de revisão.
    efeitos=False (chamada do n8n com ?efeitos=0): não cria alertas, só devolve os fatos; o fluxo decide."""
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", paciente_id)
    if not pac:
        raise HTTPException(404, f"paciente {paciente_id} não cadastrado")
    banco.executar("INSERT OR REPLACE INTO laudos VALUES (?,?,?,?)", laudo["id"], paciente_id,
                   json.dumps(laudo, ensure_ascii=False), banco.agora())
    r = tradutor.gerar_rascunho(laudo, RECURSOS["sistema"], RECURSOS["exemplos"], RECURSOS["jargao"],
                                RECURSOS["glossario"], usar_exemplo=True, verificar=laudo.get("tipo") == "imagem",
                                pausa=CFG["pausa"])
    banco.executar("INSERT INTO rascunhos VALUES (?,?,?,?,?,?,?,?)", r["rascunho_id"], laudo["id"],
                   json.dumps(r, ensure_ascii=False), "aguardando_revisao", r["prioridade"], r["prazo_revisao"],
                   banco.agora(), None)
    fatos = {"rascunho_id": r["rascunho_id"], "prioridade": r["prioridade"], "alertas": r["verificacao"]["alertas"],
             "laudo_id": laudo["id"], "paciente_id": paciente_id}
    if efeitos:
        rotear_laudo(fatos)
    return fatos


def publicar(rascunho, explicacao, duvidas, liberadas, revisor):
    laudo = banco.um("SELECT * FROM laudos WHERE id=?", rascunho["laudo_id"])
    token = secrets.token_urlsafe(16)
    banco.executar("INSERT OR REPLACE INTO publicacoes (laudo_id, paciente_id, token, exame, explicacao, duvidas_json,"
                   " duvidas_liberadas, revisor, publicado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                   laudo["id"], laudo["paciente_id"], token, banco.j(laudo["json"])["exame"], explicacao,
                   json.dumps(duvidas, ensure_ascii=False), int(liberadas), revisor, banco.agora())
    notificar_publicacao(laudo["id"])
    return token


def notificar_publicacao(laudo_id):
    """Com ORQUESTRADOR=n8n, o fluxo do n8n decide e chama /api/avisos/publicacao; senão, envia direto."""
    if CFG["orquestrador"] == "n8n" and chamar_n8n("laudo-aprovado", {"laudo_id": laudo_id}) is not None:
        return
    rotear_publicacao({"status": enviar_aviso_publicacao(laudo_id), "laudo_id": laudo_id})


def enviar_aviso_publicacao(laudo_id, lembrete=False):
    pub = banco.um("SELECT * FROM publicacoes WHERE laudo_id=?", laudo_id)
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"])
    # D3, 2ª revisão: o aviso não leva link; o paciente responde OI e passa pela triagem na própria conversa
    destino = f"{CFG['base_url']}/p/{pub['token']}" if CFG["portal_paciente"] else avisos.AVISO_CONVERSA
    texto = (f"Lembrete: há uma mensagem da clínica para você: {destino}" if lembrete
             else f"Há uma nova mensagem da clínica para você: {destino}")
    return avisos.enviar(pac, texto)


def chamar_n8n(webhook, dados, tempo=120):
    req = urllib.request.Request(f"{CFG['n8n_url']}/webhook/{webhook}", data=json.dumps(dados).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r:
            corpo = r.read().decode()
            return json.loads(corpo) if corpo.strip().startswith("{") else {}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"[n8n] {webhook} indisponível ({e}); seguindo pelo orquestrador interno")
        return None


def cenario_do_paciente(pub):
    """Exame ativo + (fonte B, 14/11) até 3 outros exames aprovados e até 3 laudos enviados e conferidos, em revisão."""
    outros = [{"exame": p["exame"], "explicacao": p["explicacao"]} for p in banco.todos(
        "SELECT exame, explicacao FROM publicacoes WHERE paciente_id=? AND laudo_id<>? ORDER BY publicado_em DESC "
        "LIMIT 3", pub["paciente_id"], pub["laudo_id"])]
    enviados = []
    for e in banco.todos("SELECT laudo_json FROM envios WHERE paciente_id=? AND status='em_revisao' AND correcao IS NULL"
                         " ORDER BY id DESC LIMIT 3", pub["paciente_id"]):
        laudo = banco.j(e["laudo_json"], {})
        if laudo.get("tipo") == "laboratorio" and laudo.get("itens"):
            enviados.append({"exame": laudo["exame"], "valores": canal_whatsapp.linhas_valores(laudo)[0]})
    return {"id": pub["token"], "exames": pub["exame"], "explicacao_aprovada": pub["explicacao"],
            "duvidas_aprovadas": banco.j(pub["duvidas_json"], []), "duvidas_liberadas": bool(pub["duvidas_liberadas"]),
            "outros_exames": outros, "laudos_enviados": enviados}


def processar_duvida(token, pergunta, efeitos=True):
    """Pista da dúvida (chatbot.py) gravando a fila no banco.
    efeitos=False (chamada do n8n com ?efeitos=0): não cria o alerta de urgência, só devolve os fatos."""
    pub = banco.um("SELECT * FROM publicacoes WHERE token=?", token)
    if not pub:
        raise HTTPException(404, "publicação não encontrada")
    banco.executar("INSERT INTO chat (token, autor, texto, tipo, criado_em) VALUES (?,?,?,?,?)",
                   token, "paciente", pergunta, None, banco.agora())

    def gravar(pergunta_, cenario, cls, rascunho, fontes, motivo):
        fid = banco.executar(
            "INSERT INTO fila (token, pergunta, tipo, destino_sugerido, prioridade, motivo, rascunho, fontes, status,"
            " criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)", token, pergunta_, cls["tipo"],
            cls.get("destino") or "enfermagem", cls.get("prioridade", "normal"), motivo, rascunho,
            json.dumps(fontes, ensure_ascii=False), "aguardando", banco.agora())
        return {"id": fid, "destino_sugerido": cls.get("destino"), "prioridade": cls.get("prioridade")}

    out = chatbot.atender(pergunta, cenario_do_paciente(pub), RECURSOS["base"], pausa=CFG["pausa"], fila_fn=gravar)
    fila_id = out["fila"]["id"] if out.get("fila") else None
    # os códigos das fontes ([A1], [P1], [E1], [G2], [B01-3]) ficam no registro e na fila, não no texto do paciente
    mensagem = chatbot.remover_codigos(out["mensagem_ao_paciente"])
    out["mensagem_ao_paciente"] = mensagem
    banco.executar("INSERT INTO chat (token, autor, texto, tipo, fila_id, criado_em) VALUES (?,?,?,?,?,?)",
                   token, "sistema", mensagem, out["tipo_final"], fila_id, banco.agora())
    fatos = {"mensagem": out["mensagem_ao_paciente"], "tipo_final": out["tipo_final"], "fila_id": fila_id,
             "chamadas_llm": out["chamadas_llm"], "token": token, "pergunta": pergunta,
             "paciente_id": pub["paciente_id"], "laudo_id": pub["laudo_id"]}
    if efeitos:
        rotear_duvida(fatos)
    return fatos


def rotinas(dias_simulados=0):
    """D6: prazos de aprovação e lembretes de leitura. dias_simulados adianta o relógio (para a demo)."""
    agora = datetime.now() + timedelta(days=dias_simulados)
    feitos = {"prazo_vencido": 0, "expirados": 0, "lembretes": 0}
    for r in banco.todos("SELECT * FROM rascunhos WHERE status='aguardando_revisao'"):
        limite = datetime.fromisoformat(r["criado_em"]) + timedelta(days=PRAZO_DIAS[r["prioridade"]])
        limite = limite.replace(hour=23, minute=59)
        laudo = banco.um("SELECT * FROM laudos WHERE id=?", r["laudo_id"])
        if agora > limite + timedelta(days=PRAZO_DIAS[r["prioridade"]] + 2):
            # expirado: o rascunho NUNCA é enviado; o paciente recebe só o aviso de que será explicado na consulta
            banco.executar("UPDATE rascunhos SET status='expirado' WHERE rascunho_id=?", r["rascunho_id"])
            rasc = {**r, "laudo_id": laudo["id"]}
            publicar(rasc, "O resultado deste exame será explicado pelo seu médico na consulta.", [], False,
                     "sistema (prazo expirado)")
            feitos["expirados"] += 1
        elif agora > limite:
            alerta("prazo_vencido", f"Rascunho {r['rascunho_id']} passou do prazo ({r['prazo']}): "
                                    f"encaminhar ao médico de referência", laudo["paciente_id"], r["rascunho_id"])
            feitos["prazo_vencido"] += 1
    for p in banco.todos("SELECT * FROM publicacoes WHERE lido_em IS NULL AND lembretes=0"):
        if agora - datetime.fromisoformat(p["publicado_em"]) > timedelta(days=3):
            enviar_aviso_publicacao(p["laudo_id"], lembrete=True)
            banco.executar("UPDATE publicacoes SET lembretes=1 WHERE laudo_id=?", p["laudo_id"])
            feitos["lembretes"] += 1
    return feitos

# ------------------------------------------------------------------ API (chamada pelo n8n)

@app.post("/api/laudos")
async def api_laudos(request: Request, efeitos: str = "1", x_api_key: str = Header(default="")):
    """?efeitos=0: o n8n decide o que fazer com a prioridade (não cria o alerta de contato ativo aqui)."""
    exigir_api(x_api_key)
    corpo = await request.json()
    return await asyncio.to_thread(processar_laudo, corpo["paciente_id"], corpo["laudo"], efeitos != "0")


@app.post("/api/avisos/publicacao")
async def api_aviso(request: Request, x_api_key: str = Header(default="")):
    exigir_api(x_api_key)
    corpo = await request.json()
    return {"status": await asyncio.to_thread(enviar_aviso_publicacao, corpo["laudo_id"])}


@app.post("/api/duvidas")
async def api_duvidas(request: Request, efeitos: str = "1", x_api_key: str = Header(default="")):
    """?efeitos=0: o n8n decide o que fazer com o tipo_final (não cria o alerta de urgência aqui)."""
    exigir_api(x_api_key)
    corpo = await request.json()
    return await asyncio.to_thread(processar_duvida, corpo["token"], corpo["pergunta"], efeitos != "0")


@app.post("/api/rotinas")
async def api_rotinas(request: Request, x_api_key: str = Header(default="")):
    exigir_api(x_api_key)
    corpo = await request.json() if (await request.body()) else {}
    return await asyncio.to_thread(rotinas, int(corpo.get("dias_simulados", 0)))


# Ações de cada ramo dos fluxos do n8n (o fluxo decide; o serviço executa). Todas idempotentes.

@app.post("/api/acoes/contato-ativo")
async def api_acao_contato_ativo(request: Request, x_api_key: str = Header(default="")):
    """{rascunho_id} (ou {laudo_id}): alerta de contato ativo do laudo crítico."""
    exigir_api(x_api_key)
    corpo = await request.json()
    laudo_id = corpo.get("laudo_id")
    if corpo.get("rascunho_id"):
        r = banco.um("SELECT laudo_id FROM rascunhos WHERE rascunho_id=?", corpo["rascunho_id"])
        if not r:
            raise HTTPException(404, "rascunho não encontrado")
        laudo_id = r["laudo_id"]
    if not laudo_id:
        raise HTTPException(422, "informe rascunho_id")
    return {"ok": True, "novo": await asyncio.to_thread(acao_contato_ativo, laudo_id)}


@app.post("/api/acoes/urgencia")
async def api_acao_urgencia(request: Request, x_api_key: str = Header(default="")):
    """{token, pergunta, fila_id}: alerta de urgência da dúvida tipo d."""
    exigir_api(x_api_key)
    corpo = await request.json()
    if not corpo.get("token") or corpo.get("fila_id") in (None, ""):
        raise HTTPException(422, "informe token, pergunta e fila_id")
    novo = await asyncio.to_thread(acao_urgencia, corpo["token"], str(corpo.get("pergunta", "")), corpo["fila_id"])
    return {"ok": True, "novo": novo}


@app.post("/api/acoes/falha")
async def api_acao_falha(request: Request, x_api_key: str = Header(default="")):
    """{origem, detalhe}: alerta de falha de orquestração. Com origem "aviso" e laudo_id (ramo "não enviado" do
    fluxo de publicação), é o alerta falha_envio da tabela ROTAS."""
    exigir_api(x_api_key)
    corpo = await request.json()
    if corpo.get("origem") == "aviso" and corpo.get("laudo_id"):
        novo = await asyncio.to_thread(acao_falha_envio, corpo["laudo_id"], corpo.get("detalhe") or corpo.get("status"))
        return {"ok": True, "tipo": "falha_envio", "novo": novo}
    novo = await asyncio.to_thread(acao_falha_orquestracao, corpo.get("origem"), corpo.get("detalhe"))
    return {"ok": True, "tipo": "falha_orquestracao", "novo": novo}


@app.get("/api/saude")
def saude():
    r = {"ok": True, "orquestrador": CFG["orquestrador"]}
    if os.environ.get("LLM_FIXA") == "1":  # só no ambiente de teste: respostas fixas, nenhuma chamada à LLM
        r["llm_fixa"] = True
    return r

# ------------------------------------------------------------------ painel da equipe

@app.get("/painel/login", response_class=HTMLResponse)
def painel_login(request: Request, erro: str = ""):
    return tela(request, "painel_login.html", erro=erro, sem_contas=not usuarios.existe_algum())


@app.post("/painel/login")
async def painel_login_post(request: Request):
    f = await request.form()
    u, erro = await asyncio.to_thread(usuarios.autenticar, f.get("login", ""), f.get("senha", ""))
    if not u:
        return RedirectResponse(f"/painel/login?erro={erro}", 303)
    # sessão da equipe: token = login (para derrubar a sessão ao trocar senha ou desativar a conta)
    return criar_sessao(RedirectResponse("/painel", 303), "equipe", token=u["login"], nome=u["nome"])


@app.post("/painel/sair")
def painel_sair(request: Request):
    banco.executar("DELETE FROM sessoes WHERE sessao=? AND papel='equipe'", request.cookies.get("sessao_equipe", ""))
    resp = RedirectResponse("/painel/login", 303)
    resp.delete_cookie("sessao_equipe")
    return resp


@app.get("/painel", response_class=HTMLResponse)
def painel(request: Request):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    rasc = banco.todos("SELECT r.*, l.paciente_id, p.nome FROM rascunhos r JOIN laudos l ON l.id=r.laudo_id "
                       "JOIN pacientes p ON p.id=l.paciente_id WHERE r.status='aguardando_revisao'")
    for r in rasc:
        d = banco.j(r["json"])
        r.update(exame=d["exame"], n_alertas=len(d["verificacao"]["alertas"]) + len(d["verificacao"]["omitidos"]),
                 tipo=d["tipo"])
    rasc.sort(key=lambda r: (ORDEM[r["prioridade"]], r["criado_em"]))  # D6: risco primeiro
    return tela(request, "painel.html", s=s, rascunhos=rasc,
                alertas=banco.todos("SELECT * FROM alertas WHERE status='aberto' ORDER BY "
                                    "CASE tipo WHEN 'urgencia' THEN 0 WHEN 'contato_ativo' THEN 1 ELSE 2 END, id"),
                n_fila=banco.um("SELECT COUNT(*) c FROM fila WHERE status='aguardando'")["c"],
                publicadas=banco.todos("SELECT pu.*, p.nome FROM publicacoes pu JOIN pacientes p ON "
                                       "p.id=pu.paciente_id ORDER BY publicado_em DESC LIMIT 10"))


@app.get("/painel/rascunho/{rid}", response_class=HTMLResponse)
def painel_rascunho(request: Request, rid: str):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    r = banco.um("SELECT * FROM rascunhos WHERE rascunho_id=?", rid)
    if not r:
        raise HTTPException(404)
    d = banco.j(r["json"])
    laudo_row = banco.um("SELECT * FROM laudos WHERE id=?", r["laudo_id"])
    laudo = banco.j(laudo_row["json"])
    av = avaliar_laudo(laudo)
    defs = n.termos_do_laudo(laudo, av, RECURSOS["glossario"])
    sem_apoio = (d["verificacao"].get("apoio") or {}).get("sem_apoio", [])
    return tela(request, "rascunho.html", s=s, r=r, d=d, laudo=laudo, avaliacao=av,
                paciente=banco.um("SELECT * FROM pacientes WHERE id=?", laudo_row["paciente_id"]),
                frases=origem.origens(d["explicacao"], laudo, av, defs, sem_apoio), sem_apoio=sem_apoio,
                aberto_em=int(time.time()))


@app.post("/painel/rascunho/{rid}")
async def painel_rascunho_post(request: Request, rid: str):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    r = banco.um("SELECT * FROM rascunhos WHERE rascunho_id=? AND status='aguardando_revisao'", rid)
    if not r:
        return RedirectResponse("/painel", 303)
    f = await request.form()
    d = banco.j(r["json"])
    tempo = max(0, int(time.time()) - int(f.get("aberto_em", time.time())))
    if f.get("acao") == "descartar":
        motivo = f.get("motivo", "").strip()
        if not motivo:
            return RedirectResponse(f"/painel/rascunho/{rid}?erro=motivo", 303)
        registro.registrar(d, "descartado", s["nome"], tempo, motivo_descarte=motivo)
        banco.executar("UPDATE rascunhos SET status='descartado' WHERE rascunho_id=?", rid)
        return RedirectResponse("/painel", 303)
    explicacao = f.get("explicacao", "").strip().replace("\r\n", "\n")
    duvidas = []
    for k in range(len(d["duvidas"])):
        if f.get(f"manter_{k}"):
            duvidas.append({"pergunta": f.get(f"p_{k}", "").strip(), "resposta": f.get(f"r_{k}", "").strip()})
    for k in range(2):  # dúvidas acrescentadas pelo profissional (F1): texto dele, sem passar pela IA
        p_, r_ = f.get(f"nova_p_{k}", "").strip(), f.get(f"nova_r_{k}", "").strip()
        if p_ and r_:
            duvidas.append({"pergunta": p_, "resposta": r_, "autor": "profissional"})
    liberadas = bool(f.get("liberar_duvidas"))
    editou = explicacao != d["explicacao"] or duvidas != d["duvidas"]
    registro.registrar(d, "editado" if editou else "aprovado", s["nome"], tempo, explicacao_final=explicacao,
                       duvidas_finais=duvidas, duvidas_liberadas=liberadas)
    banco.executar("UPDATE rascunhos SET status='publicado' WHERE rascunho_id=?", rid)
    await asyncio.to_thread(publicar, r, explicacao, duvidas, liberadas, s["nome"])
    envio = banco.j(banco.um("SELECT json FROM laudos WHERE id=?", r["laudo_id"])["json"]).get("_envio")
    if envio:  # laudo enviado pelo paciente: depois da aprovação, fica só com os valores conferidos
        leitura.apagar(envio["envio_id"])
        banco.executar("UPDATE envios SET status='aprovado' WHERE id=?", envio["envio_id"])
    return RedirectResponse("/painel?publicado=" + r["laudo_id"], 303)


@app.get("/painel/envio/{eid}")
def painel_envio_arquivo(request: Request, eid: int):
    """Arquivo original de um laudo enviado pelo paciente (só no painel; o túnel não expõe /painel)."""
    if not sessao(request, "equipe"):
        return RedirectResponse("/painel/login", 303)
    e = banco.um("SELECT * FROM envios WHERE id=?", eid)
    if not e or not e["arquivo"] or not os.path.exists(e["arquivo"]):
        return tela(request, "aviso.html", titulo="Arquivo indisponível",
                    texto="O arquivo foi apagado depois da aprovação ou não existe.")
    return FileResponse(e["arquivo"], media_type=e["mime"])


@app.get("/painel/fila", response_class=HTMLResponse)
def painel_fila(request: Request):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    itens = banco.todos("SELECT f.*, p.nome, pu.exame FROM fila f JOIN publicacoes pu ON pu.token=f.token "
                        "JOIN pacientes p ON p.id=pu.paciente_id WHERE f.status='aguardando'")
    itens.sort(key=lambda i: ({"d": 0}.get(i["tipo"], 1), 0 if i["prioridade"] == "alta" else 1, i["id"]))
    for i in itens:
        i["fontes"] = banco.j(i["fontes"], [])
    return tela(request, "fila.html", s=s, itens=itens)


@app.post("/painel/fila/{fid}")
async def painel_fila_post(request: Request, fid: int):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    f = await request.form()
    item = banco.um("SELECT * FROM fila WHERE id=?", fid)
    acao = f.get("acao")
    if acao == "encaminhar_medico":
        banco.executar("UPDATE fila SET destino_sugerido='medico' WHERE id=?", fid)
    elif acao in ("responder", "resolver"):
        resposta = f.get("resposta", "").strip()
        banco.executar("UPDATE fila SET status='respondido', resposta_final=?, respondido_por=?, destino_final=?, "
                       "respondido_em=? WHERE id=?", resposta, s["nome"], f.get("destino_final") or
                       item["destino_sugerido"], banco.agora(), fid)
        if resposta:
            banco.executar("INSERT INTO chat (token, autor, texto, tipo, fila_id, criado_em) VALUES (?,?,?,?,?,?)",
                           item["token"], "equipe", resposta, "resposta_equipe", fid, banco.agora())
            pub = banco.um("SELECT * FROM publicacoes WHERE token=?", item["token"])
            pac = banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"])
            if canal_whatsapp.consentimento(pub["paciente_id"]):  # D3 revisada: com consentimento, a resposta vai direto
                await asyncio.to_thread(avisos.enviar_conteudo, pac,
                                        f"Resposta da equipe da clínica sobre “{item['pergunta'][:80]}”:\n\n{resposta}")
            else:
                await asyncio.to_thread(enviar_aviso_publicacao, pub["laudo_id"])
    elif acao == "descartar":
        banco.executar("UPDATE fila SET status='descartado', respondido_por=?, respondido_em=? WHERE id=?",
                       s["nome"], banco.agora(), fid)
    if acao in ("responder", "resolver", "descartar"):  # fecha o alerta de urgência ligado a este item
        banco.executar("UPDATE alertas SET status='resolvido', resolvido_por=?, resolvido_em=? WHERE tipo='urgencia' "
                       "AND referencia=? AND status='aberto'", s["nome"], banco.agora(), str(fid))
    return RedirectResponse("/painel/fila", 303)


@app.post("/painel/alerta/{aid}")
def painel_alerta(request: Request, aid: int):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    banco.executar("UPDATE alertas SET status='resolvido', resolvido_por=?, resolvido_em=? WHERE id=?",
                   s["nome"], banco.agora(), aid)
    return RedirectResponse("/painel", 303)


@app.post("/painel/rotinas")
async def painel_rotinas(request: Request):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    f = await request.form()
    dias = int(f.get("dias", 0))
    if CFG["orquestrador"] == "n8n" and await asyncio.to_thread(chamar_n8n, "rotinas", {"dias_simulados": dias}) is not None:
        return RedirectResponse("/painel", 303)
    await asyncio.to_thread(rotinas, dias)
    return RedirectResponse("/painel", 303)


@app.get("/painel/whatsapp", response_class=HTMLResponse)
def painel_whatsapp(request: Request):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    return tela(request, "whatsapp.html", s=s,
                avisos=banco.todos("SELECT a.*, p.nome FROM avisos a LEFT JOIN pacientes p ON p.id=a.paciente_id "
                                   "ORDER BY a.id DESC LIMIT 100"))


@app.get("/painel/registro", response_class=HTMLResponse)
def painel_registro(request: Request):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    linhas = []
    if os.path.exists(registro.ARQUIVO):
        with open(registro.ARQUIVO, encoding="utf-8") as fh:
            linhas = [json.loads(l) for l in fh if l.strip()][-50:][::-1]
    return tela(request, "registro.html", s=s, linhas=linhas)

@app.get("/painel/equipe", response_class=HTMLResponse)
def painel_equipe(request: Request, ok: str = "", erro: str = ""):
    """Só a administração: todas as contas e funções do sistema."""
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    if not usuarios.eh_admin(s["token"]):
        raise HTTPException(403, "Só a administração acessa esta página.")
    contas = usuarios.listar()
    abertas = {r["token"] for r in banco.todos("SELECT DISTINCT token FROM sessoes WHERE papel='equipe'")}
    return tela(request, "equipe.html", s=s, contas=contas, sessoes_abertas=abertas, ok=ok[:200], erro=erro[:200],
                funcoes=usuarios.FUNCOES, descricoes=usuarios.DESCRICOES)


@app.post("/painel/equipe")
async def painel_equipe_post(request: Request):
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    if not usuarios.eh_admin(s["token"]):
        raise HTTPException(403, "Só a administração acessa esta página.")
    f = await request.form()
    acao, login = f.get("acao", ""), f.get("login", "").strip().lower()
    try:
        if login == s["token"] and acao in ("desativar", "funcao"):
            raise ValueError("Você não pode desativar nem trocar a função da sua própria conta.")
        if acao == "criar":
            if f.get("senha", "") != f.get("senha2", ""):
                raise ValueError("As senhas não conferem.")
            msg = await asyncio.to_thread(usuarios.criar, login, f.get("nome", ""), f.get("funcao", ""), f.get("senha", ""))
        elif acao == "senha":
            msg = await asyncio.to_thread(usuarios.trocar_senha, login, f.get("senha", ""))
        elif acao == "funcao":
            msg = usuarios.trocar_funcao(login, f.get("funcao", ""))
        elif acao in ("ativar", "desativar"):
            msg = usuarios.definir_ativo(login, acao == "ativar")
        else:
            raise ValueError("Ação desconhecida.")
        return RedirectResponse("/painel/equipe?" + urllib.parse.urlencode({"ok": msg}), 303)
    except ValueError as e:
        return RedirectResponse("/painel/equipe?" + urllib.parse.urlencode({"erro": str(e)}), 303)


@app.get("/painel/publicado/{token}", response_class=HTMLResponse)
def painel_publicado(request: Request, token: str):
    """O que o paciente recebeu sobre um exame publicado, e a conversa dele sobre esse exame (só leitura)."""
    s = sessao(request, "equipe")
    if not s:
        return RedirectResponse("/painel/login", 303)
    pub = banco.um("SELECT * FROM publicacoes WHERE token=?", token)
    if not pub:
        raise HTTPException(404)
    return tela(request, "publicado.html", s=s, pub=pub,
                paciente=banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"]),
                paragrafos=[p for p in (pub["explicacao"] or "").split("\n") if p.strip()],
                duvidas=banco.j(pub["duvidas_json"], []),
                consentimento=canal_whatsapp.consentimento(pub["paciente_id"]),
                chat=banco.todos("SELECT * FROM chat WHERE token=? ORDER BY id", token),
                fila=banco.todos("SELECT * FROM fila WHERE token=? ORDER BY id DESC", token))

# ------------------------------------------------------------------ portal do paciente (D3)

@app.get("/p/{token}", response_class=HTMLResponse)
def portal_entrada(request: Request, token: str, erro: str = ""):
    if not banco.um("SELECT laudo_id FROM publicacoes WHERE token=?", token):
        return tela(request, "aviso.html", titulo="Link inválido", texto="Este link não é válido ou expirou.")
    s = sessao(request, "paciente")
    if s and s["token"] == token:
        return RedirectResponse("/portal", 303)
    return tela(request, "portal_entrada.html", token=token, erro=erro)


@app.post("/p/{token}")
async def portal_entrada_post(request: Request, token: str):
    f = await request.form()
    pub = banco.um("SELECT * FROM publicacoes WHERE token=?", token)
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"]) if pub else None
    if not pac or f.get("nascimento") != pac["nascimento"]:
        return RedirectResponse(f"/p/{token}?erro=1", 303)
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    banco.executar("INSERT OR REPLACE INTO codigos VALUES (?,?,?,0)", token, codigo,
                   (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds"))
    await asyncio.to_thread(avisos.enviar, pac, f"Seu código de acesso ao portal da clínica é {codigo}. Ele vale por 10 minutos.")
    return RedirectResponse(f"/p/{token}/codigo", 303)


@app.get("/p/{token}/codigo", response_class=HTMLResponse)
def portal_codigo(request: Request, token: str, erro: str = ""):
    return tela(request, "portal_codigo.html", token=token, erro=erro)


@app.post("/p/{token}/codigo")
async def portal_codigo_post(request: Request, token: str):
    f = await request.form()
    c = banco.um("SELECT * FROM codigos WHERE token=?", token)
    if not c or datetime.now() > datetime.fromisoformat(c["expira_em"]) or c["tentativas"] >= 5:
        banco.executar("DELETE FROM codigos WHERE token=?", token)
        return RedirectResponse(f"/p/{token}?erro=expirado", 303)
    if f.get("codigo", "").strip() != c["codigo"]:
        banco.executar("UPDATE codigos SET tentativas=tentativas+1 WHERE token=?", token)
        return RedirectResponse(f"/p/{token}/codigo?erro=1", 303)
    banco.executar("DELETE FROM codigos WHERE token=?", token)  # uso único
    banco.executar("UPDATE publicacoes SET lido_em=COALESCE(lido_em, ?) WHERE token=?", banco.agora(), token)
    return criar_sessao(RedirectResponse("/portal", 303), "paciente", token=token)


@app.get("/portal", response_class=HTMLResponse)
def portal(request: Request):
    s = sessao(request, "paciente")
    if not s:
        return tela(request, "aviso.html", titulo="Sessão encerrada",
                    texto="Por segurança, a sessão expira após alguns minutos sem uso. Abra de novo o link que você recebeu.")
    pub = banco.um("SELECT * FROM publicacoes WHERE token=?", s["token"])
    return tela(request, "portal.html", pub=pub, duvidas=banco.j(pub["duvidas_json"], []),
                consentimento=canal_whatsapp.consentimento(pub["paciente_id"]), termo=canal_whatsapp.TERMO,
                numero_clinica=canal_whatsapp.numero_clinica(),
                paragrafos=[p for p in pub["explicacao"].split("\n") if p.strip()],
                chat=banco.todos("SELECT * FROM chat WHERE token=? ORDER BY id", s["token"]))


@app.post("/portal/chat")
async def portal_chat(request: Request):
    s = sessao(request, "paciente")
    if not s:
        return RedirectResponse("/portal", 303)
    pergunta = (await request.form()).get("pergunta", "").strip()[:500]
    chave = (s["token"], pergunta.lower())
    recente = banco.um("SELECT id FROM chat WHERE token=? AND autor='paciente' AND lower(texto)=? AND criado_em>=?",
                       s["token"], pergunta.lower(), (datetime.now() - timedelta(seconds=30)).isoformat(timespec="seconds"))
    if pergunta and chave not in EM_ANDAMENTO and not recente:  # evita processar a mesma pergunta duas vezes
        EM_ANDAMENTO.add(chave)
        try:
            via_n8n = CFG["orquestrador"] == "n8n" and await asyncio.to_thread(
                chamar_n8n, "duvida", {"token": s["token"], "pergunta": pergunta}) is not None
            if not via_n8n:
                await asyncio.to_thread(processar_duvida, s["token"], pergunta)
        finally:
            EM_ANDAMENTO.discard(chave)
    return RedirectResponse("/portal#chat", 303)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    return RedirectResponse("/painel", 303)


# ------------------------------------------------------------------ canal WhatsApp com consentimento (D3 revisada)

@app.post("/portal/whatsapp")
async def portal_whatsapp(request: Request):
    s = sessao(request, "paciente")
    if not s:
        return RedirectResponse("/portal", 303)
    pub = banco.um("SELECT * FROM publicacoes WHERE token=?", s["token"])
    f = await request.form()
    if f.get("acao") == "aceitar" and f.get("concordo"):
        canal_whatsapp.aceitar(pub["paciente_id"])
        pac = banco.um("SELECT * FROM pacientes WHERE id=?", pub["paciente_id"])
        # tenta já mandar a explicação (só chega se a janela de 24 h estiver aberta; senão, chega no "oi" do paciente)
        await asyncio.to_thread(canal_whatsapp.enviar_explicacao, pac, pub)
    elif f.get("acao") == "revogar":
        canal_whatsapp.revogar(pub["paciente_id"])
    return RedirectResponse("/portal#whatsapp", 303)


def _duvida_pelo_orquestrador(token, pergunta):
    if CFG["orquestrador"] == "n8n":
        r = chamar_n8n("duvida", {"token": token, "pergunta": pergunta})
        if r and r.get("mensagem"):
            return r
    return processar_duvida(token, pergunta)


@app.get("/webhook/whatsapp")
def webhook_verificacao(request: Request):
    """Verificação do webhook pela Meta (hub.challenge)."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == os.environ.get("WHATSAPP_VERIFY_TOKEN", "-"):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "token de verificação inválido")


@app.post("/webhook/whatsapp")
async def webhook_mensagens(request: Request, tarefas: BackgroundTasks):
    corpo = await request.body()
    segredo = os.environ.get("WHATSAPP_APP_SECRET", "")
    if segredo:  # garante que o evento veio mesmo da Meta
        esperado = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(esperado, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(401, "assinatura inválida")
    dados = json.loads(corpo or b"{}")
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for m in mudanca.get("value", {}).get("messages", []):
                tipo = m.get("type")
                if tipo == "text":
                    tarefas.add_task(asyncio.to_thread, canal_whatsapp.receber, m["id"], m["from"],
                                     m["text"]["body"], _duvida_pelo_orquestrador, processar_laudo)
                elif tipo == "interactive":  # toque numa lista ou num botão
                    esc = m["interactive"].get("list_reply") or m["interactive"].get("button_reply") or {}
                    tarefas.add_task(asyncio.to_thread, canal_whatsapp.receber_escolha, m["id"], m["from"],
                                     esc.get("id", ""), esc.get("title", ""), _duvida_pelo_orquestrador,
                                     processar_laudo)
                elif isinstance(m.get(tipo), dict) and m[tipo].get("id"):  # foto, PDF (e áudio, vídeo...: recusados)
                    midia = {"id": m[tipo]["id"], "mime": (m[tipo].get("mime_type") or "").split(";")[0].strip(),
                             "nome": m[tipo].get("filename")}
                    tarefas.add_task(asyncio.to_thread, canal_whatsapp.receber_anexo, m["id"], m["from"], midia,
                                     processar_laudo)
    return {"ok": True}  # responde rápido; a Meta reenvia se demorar
