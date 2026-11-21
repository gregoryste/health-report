"""Canal WhatsApp do paciente (D3, 2ª revisão em 14/11: o WhatsApp é o canal do paciente; o portal é só da equipe).

Triagem, na própria conversa, antes de qualquer dado de saúde:
  1. o paciente escreve (por exemplo, respondendo OI ao aviso de resultado);
  2. o bot pede o CPF e depois a data de nascimento. Os dois precisam conferir com o cadastro E a mensagem precisa
     vir do número cadastrado (segundo fator). 3 erros → bloqueio de 30 min + alerta no painel;
  3. sem consentimento ativo → termo com botões Sim / Não. "Não" → nada de saúde pelo WhatsApp;
  4. identificado e com consentimento → explicação aprovada + menu de dúvidas; perguntas seguem a mesma pista da
     dúvida (alarme, classificador, fontes, verificação, fila). A identificação vale 24 h desde a última mensagem.
Sinal de alarme (dor no peito, falta de ar...) recebe a orientação de urgência na hora, mesmo antes da identificação.
"SAIR" revoga o consentimento e encerra a sessão. O consentimento fica registrado (quando, versão do termo, revogação).

Vários exames (14/11): a sessão guarda o exame ativo; com mais de um, o paciente escolhe na lista "Seus exames".
Envio de laudo (14/11, D4 + D6): foto ou PDF → leitura local (app/leitura.py; número só vale se estiver no texto
lido e na mesma linha do item) → RESUMO IMEDIATO, sem conferência do paciente, só com o que não é gerado pela IA (valores conferidos, posição em relação à faixa do próprio laudo,
definições aprovadas do glossário) → a explicação escrita pela IA passa pela revisão do painel antes de chegar.
"""
import hashlib
import json
import os
import re

from regra import normalizar

from regra import avaliar_laudo

from . import avisos, banco, leitura

from datetime import datetime, timedelta

import chatbot
import nucleo as n

VERSAO_TERMO = "2026-11-14-whatsapp"  # termo aceito na própria conversa (avisos.TERMO_WHATSAPP)
TERMO = avisos.TERMO_WHATSAPP
SESSAO_HORAS = 24        # a identificação vale 24 h desde a última mensagem
ETAPA_MIN = 30           # CPF/data pela metade: recomeça depois de 30 min parado
MAX_TENTATIVAS = 3
BLOQUEIO_MIN = 30
_SAUDACAO = re.compile(r"^(oi+|ola|bom dia|boa tarde|boa noite|explicacao|resultado|meu exame|menu|inicio)\b")
# pedidos de navegação por texto (o mesmo que os botões), sem IA
_QUER_ENVIAR = re.compile(r"\b(mandar|enviar|envio|anexar|subir|compartilhar|mando|envio)\b.{0,40}"
                          r"\b(laudo|exame|foto|pdf|resultado|arquivo)")
_QUER_EXAMES = re.compile(r"\b(meus exames|outros exames|outro exame|trocar de exame|lista de exames|ver exames)\b")


def consentimento(paciente_id):
    return banco.um("SELECT * FROM consentimentos WHERE paciente_id=? AND canal='whatsapp' AND revogado_em IS NULL "
                    "ORDER BY id DESC LIMIT 1", paciente_id)


def aceitar(paciente_id):
    if not consentimento(paciente_id):
        banco.executar("INSERT INTO consentimentos (paciente_id, canal, versao, aceito_em) VALUES (?,?,?,?)",
                       paciente_id, "whatsapp", VERSAO_TERMO, banco.agora())


def revogar(paciente_id):
    banco.executar("UPDATE consentimentos SET revogado_em=? WHERE paciente_id=? AND canal='whatsapp' "
                   "AND revogado_em IS NULL", banco.agora(), paciente_id)


def _chave_numero(n):
    """Brasil: 55 + DDD + (9) + 8 dígitos. O WhatsApp às vezes devolve sem o 9: a chave é DDD + últimos 8 dígitos."""
    d = re.sub(r"\D", "", n or "")
    if d.startswith("55") and len(d) in (12, 13):
        return d[2:4] + d[-8:]
    return d[-10:]


def _mesmo_numero(a, b):
    return bool(a and b) and _chave_numero(a) == _chave_numero(b)


# ---------------------------------------------------------------- triagem (identificação + termo)

# CPF com ou sem pontuação, sozinho ou no meio de uma frase: 02887739000, 028.877.390-00, 028 877 390 00
CPF_RE = re.compile(r"(?<!\d)(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})[-.\s]?(\d{2})(?!\d)")


def extrair_cpf(texto):
    """Primeiro CPF do texto, só os 11 dígitos (sem pontos, traço ou espaços); None se não houver."""
    m = CPF_RE.search(texto or "")
    return "".join(m.groups()) if m else None


def cpf_valido(cpf):
    """Confere os dois dígitos verificadores. Recusa sequências repetidas (000.000.000-00, 111.111.111-11...)."""
    if not re.fullmatch(r"\d{11}", cpf or "") or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):  # 1º dígito: pesos 10..2 sobre 9 dígitos; 2º: pesos 11..2 sobre 10 dígitos
        soma = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        if soma * 10 % 11 % 10 != int(cpf[n]):
            return False
    return True


def remover_cpfs(texto):
    """Troca por [CPF removido] todo CPF válido que aparecer no texto (antes de gravar ou de mandar para a LLM)."""
    return CPF_RE.sub(lambda m: "[CPF removido]" if cpf_valido("".join(m.groups())) else m.group(0), texto or "")


def _hash_cpf(cpf):
    return hashlib.sha256(("cpf:" + re.sub(r"\D", "", cpf or "")).encode()).hexdigest()


def _data(texto):
    """'25/03/1980', '25-03-1980', '25.03.1980' ou '25031980' → '1980-03-25'."""
    d = re.sub(r"\D", "", texto)
    if len(d) != 8:
        return None
    try:
        return datetime.strptime(d, "%d%m%Y").date().isoformat()
    except ValueError:
        return None


def _sessao(wa_id):
    return banco.um("SELECT * FROM wa_sessoes WHERE numero=?", _chave_numero(wa_id)) or {
        "numero": _chave_numero(wa_id), "estado": None, "cpf_hash": None, "paciente_id": None, "tentativas": 0,
        "bloqueado_ate": None, "verificado_em": None, "atualizado_em": None, "laudo_ativo": None, "etapa": None,
        "envio_id": None, "pendente": None}


def _salvar(s, **campos):
    s = {**s, **campos, "atualizado_em": banco.agora()}
    banco.executar("INSERT OR REPLACE INTO wa_sessoes (numero, estado, cpf_hash, paciente_id, tentativas, bloqueado_ate,"
                   " verificado_em, atualizado_em, laudo_ativo, etapa, envio_id, pendente) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   s["numero"], s["estado"], s["cpf_hash"], s["paciente_id"], s["tentativas"], s["bloqueado_ate"],
                   s["verificado_em"], s["atualizado_em"], s.get("laudo_ativo"), s.get("etapa"), s.get("envio_id"),
                   s.get("pendente"))
    return s


def _parado_ha(s, **delta):
    return not s["atualizado_em"] or datetime.now() - datetime.fromisoformat(s["atualizado_em"]) > timedelta(**delta)


def _identificado(s):
    """(paciente, consentimento) se a sessão está identificada e dentro das 24 h; senão (None, None)."""
    if s["estado"] != "identificado" or _parado_ha(s, hours=SESSAO_HORAS):
        return None, None
    pac = banco.um("SELECT * FROM pacientes WHERE id=?", s["paciente_id"])
    return (pac, consentimento(pac["id"])) if pac else (None, None)


def _paciente_por_dados(wa_id, cpf_hash, nascimento):
    for p in banco.todos("SELECT * FROM pacientes WHERE nascimento=?", nascimento):
        if _hash_cpf(p.get("cpf")) == cpf_hash and _mesmo_numero(p["telefone"], wa_id):
            return p
    return None


def _mascara(wa_id):
    d = re.sub(r"\D", "", wa_id)
    return d[:4] + "…" + d[-4:]


def _alerta(tipo, descricao, paciente_id, referencia):
    if banco.um("SELECT id FROM alertas WHERE tipo=? AND referencia=? AND status='aberto'", tipo, referencia):
        return
    banco.executar("INSERT INTO alertas (tipo, descricao, paciente_id, referencia, status, criado_em) "
                   "VALUES (?,?,?,?,?,?)", tipo, descricao, paciente_id, referencia, "aberto", banco.agora())


def _enviar_resultado(paciente, s):
    """Depois da identificação: 1 exame → explicação direto; mais de 1 (ou nenhum) → lista "Seus exames"."""
    pubs = publicacoes(paciente["id"])
    if len(pubs) == 1:
        _salvar(s, laudo_ativo=pubs[0]["laudo_id"])
        enviar_explicacao(paciente, pubs[0])
    else:
        enviar_lista_exames(paciente)


def _triagem(s, wa_id, texto):
    """Passos de identificação para quem ainda não está identificado. Devolve o que aconteceu (para o registro)."""
    enviar = lambda chave: avisos.enviar_triagem(wa_id, avisos.TRIAGEM[chave])  # noqa: E731
    if s["estado"] == "bloqueado":
        if datetime.now() < datetime.fromisoformat(s["bloqueado_ate"]):
            enviar("bloqueado")
            return "bloqueado"
        s = _salvar(s, estado=None, tentativas=0, bloqueado_ate=None)
    if s["estado"] in ("pede_cpf", "pede_nascimento") and _parado_ha(s, minutes=ETAPA_MIN):
        s = _salvar(s, estado=None, cpf_hash=None)
    if s["estado"] == "pede_cpf":
        cpf = extrair_cpf(texto)
        if not cpf_valido(cpf):  # erro de digitação não conta como tentativa
            enviar("cpf_invalido")
            return "cpf inválido"
        _salvar(s, estado="pede_nascimento", cpf_hash=_hash_cpf(cpf))
        enviar("pede_nascimento")
        return "pediu nascimento"
    if s["estado"] == "pede_nascimento":
        nasc = _data(texto)
        if not nasc:
            enviar("data_invalida")
            return "data inválida"
        pac = _paciente_por_dados(wa_id, s["cpf_hash"], nasc)
        if not pac:
            tent = (s["tentativas"] or 0) + 1
            if tent >= MAX_TENTATIVAS:
                ate = (datetime.now() + timedelta(minutes=BLOQUEIO_MIN)).isoformat(timespec="seconds")
                _salvar(s, estado="bloqueado", cpf_hash=None, tentativas=tent, bloqueado_ate=ate)
                _alerta("identificacao", f"{tent} tentativas de identificação sem sucesso pelo WhatsApp "
                                         f"(número {_mascara(wa_id)}); bloqueado por {BLOQUEIO_MIN} min", None,
                        f"wa:{s['numero']}:{ate}")
                enviar("bloqueado")
                return "bloqueado"
            _salvar(s, estado="pede_cpf", cpf_hash=None, tentativas=tent)
            enviar("nao_confere")
            return "não confere"
        s = _salvar(s, estado="identificado", cpf_hash=None, paciente_id=pac["id"], tentativas=0,
                    verificado_em=banco.agora(), laudo_ativo=None, etapa=None, envio_id=None, pendente=None)
        if consentimento(pac["id"]):
            avisos.enviar_triagem(wa_id, avisos.TRIAGEM["identificado"], pac["id"])
            _enviar_resultado(pac, s)
            return "identificado"
        avisos.enviar_termo(wa_id, pac["id"])
        return "identificado; termo enviado"
    _salvar(s, estado="pede_cpf", cpf_hash=None, paciente_id=None, verificado_em=None)
    enviar("boas_vindas")
    return "triagem iniciada"


def responde_na_hora(duvida):
    """Dúvida aprovada com conteúdo (True) ou que só remete ao médico, como "Isso será avaliado pelo médico na
    consulta." (False). Mesmo critério da verificação das dúvidas em nucleo.py."""
    resp = normalizar(duvida["resposta"])
    return duvida["resposta"] != n.RESPOSTA_CAUSA and "avaliado pelo medico" not in resp


def duvidas_ordenadas(pub):
    """[(índice original, dúvida)], primeiro as que têm resposta na hora. O índice original é o id do botão (duv:k)."""
    duvidas = list(enumerate(banco.j(pub["duvidas_json"], [])))
    return [x for x in duvidas if responde_na_hora(x[1])] + [x for x in duvidas if not responde_na_hora(x[1])]


def texto_explicacao(pub, interativo=False):
    duvidas = [d for _, d in duvidas_ordenadas(pub)] if pub["duvidas_liberadas"] and not interativo else []
    partes = [f"*{pub['exame']}*", "_Explicação revisada e aprovada pela equipe da clínica._", "", pub["explicacao"]]
    if duvidas:
        partes += ["", "*Dúvidas comuns*"] + [f"• {d['pergunta']}\n  {d['resposta']}" for d in duvidas]
    partes += ["", ("Toque em *Ver dúvidas* abaixo ou escreva sua pergunta." if interativo else
                    "Para tirar uma dúvida, escreva aqui.") if pub["duvidas_liberadas"] else
               "As dúvidas sobre este exame serão respondidas na sua consulta.",
               "Em caso de urgência, ligue 192 (SAMU). Para parar de receber pelo WhatsApp, responda SAIR."]
    return "\n".join(partes)


def ultima_publicacao(paciente_id):
    return banco.um("SELECT * FROM publicacoes WHERE paciente_id=? ORDER BY publicado_em DESC LIMIT 1", paciente_id)


def publicacoes(paciente_id):
    return banco.todos("SELECT * FROM publicacoes WHERE paciente_id=? ORDER BY publicado_em DESC", paciente_id)


def pub_ativa(s, paciente_id):
    """O exame escolhido na sessão; sem escolha, o mais recente."""
    if s.get("laudo_ativo"):
        p = banco.um("SELECT * FROM publicacoes WHERE laudo_id=? AND paciente_id=?", s["laudo_ativo"], paciente_id)
        if p:
            return p
    return ultima_publicacao(paciente_id)


MAX_EXAMES = 8  # lista do WhatsApp: até 10 linhas (8 exames + "Enviar um laudo")


def enviar_lista_exames(paciente, corpo=None):
    """Lista "Seus exames": novos (ainda não lidos) primeiro, depois os anteriores, e "Enviar um laudo"."""
    pubs = publicacoes(paciente["id"])[:MAX_EXAMES]

    def linha(p):
        info = datetime.fromisoformat(p["publicado_em"]).strftime("%d/%m")
        info += " · enviado por você" if p["laudo_id"].startswith("E") else ""
        td = _titulo_descricao(p["exame"])
        return {"id": f"exame:{p['laudo_id']}", "title": td["title"],
                "description": _corta(((td["description"] + " · ") if td.get("description") else "") + info, 72)}
    novos, antigos = [linha(p) for p in pubs if not p["lido_em"]], [linha(p) for p in pubs if p["lido_em"]]
    secoes = ([{"title": "Novos", "rows": novos}] if novos else []) + \
              ([{"title": "Anteriores", "rows": antigos}] if antigos else [])
    secoes.append({"title": "Outras opções", "rows": [
        {"id": "enviar:laudo", "title": "Enviar um laudo", "description": "Foto ou PDF de um exame"}]})
    if corpo is None:
        corpo = (f"Você tem {len(pubs)} exames com explicação disponível. Qual quer ver?" if len(pubs) > 1 else
                 "Escolha o exame ou envie a foto ou o PDF de um laudo." if pubs else
                 "Você ainda não tem exames com explicação. Se quiser, pode enviar a foto ou o PDF de um laudo.")
    interativo = {"type": "list", "body": {"text": corpo}, "action": {"button": "Ver exames", "sections": secoes}}
    return avisos.enviar_interativo(paciente, interativo, f"[exames] {corpo} ({len(pubs)})")


def _nomes_do_laudo(laudo_id):
    l = banco.um("SELECT json FROM laudos WHERE id=?", laudo_id)
    d = banco.j(l["json"], {}) if l else {}
    nomes = {normalizar(d.get("exame", ""))}
    for i in d.get("itens", []):
        nomes |= {normalizar(i["analito"])} | {normalizar(a) for a in i.get("apelidos", [])}
    return {x for x in nomes if len(x) >= 3}


def exame_citado(pergunta, paciente_id, pub):
    """Outro exame do paciente citado na pergunta (pelo nome do exame ou de um item), sem IA. None se não houver."""
    t = normalizar(pergunta)
    cita = lambda nomes: any(re.search(r"\b" + re.escape(x) + r"\b", t) for x in nomes)  # noqa: E731
    if cita(_nomes_do_laudo(pub["laudo_id"])):
        return None
    for p in publicacoes(paciente_id):
        if p["laudo_id"] != pub["laudo_id"] and cita(_nomes_do_laudo(p["laudo_id"])):
            return p
    return None


def interativo_ligado():
    return os.environ.get("WHATSAPP_INTERATIVO", "1") != "0"


def _corta(t, n):
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _titulo_descricao(pergunta):
    """Lista do WhatsApp: título até 24 caracteres. Se a pergunta não couber, quebra numa palavra e o resto vai
    para a descrição (a escolha aparece na conversa como título + descrição, sem repetir a pergunta)."""
    p = " ".join(pergunta.split())
    if len(p) <= 24:
        return {"title": p}
    corte = p.rfind(" ", 0, 25)
    corte = corte if corte > 0 else 24
    return {"title": p[:corte].rstrip(), "description": _corta(p[corte:].strip(), 72)}


def registrar_chat(token, autor, texto, tipo=None):
    banco.executar("INSERT INTO chat (token, autor, texto, tipo, criado_em) VALUES (?,?,?,?,?)",
                   token, autor, texto, tipo, banco.agora())


def enviar_menu(paciente, pub, corpo="O que você quer fazer agora?"):
    """Lista interativa: dúvidas aprovadas (sem IA) + outras opções. Máx. 10 linhas no total.
    Primeiro as dúvidas com resposta na hora; depois, numa seção à parte, as que ficam para a consulta."""
    duvidas = duvidas_ordenadas(pub)[:6] if pub["duvidas_liberadas"] else []  # 6 + 4 opções = 10 linhas
    linha = lambda k, d: {"id": f"duv:{k}", **_titulo_descricao(d["pergunta"])}  # noqa: E731
    na_hora = [linha(k, d) for k, d in duvidas if responde_na_hora(d)]
    consulta = [linha(k, d) for k, d in duvidas if not responde_na_hora(d)]
    linhas = na_hora + consulta
    secoes = []
    if na_hora:
        secoes.append({"title": "Resposta na hora", "rows": na_hora})
    if consulta:
        secoes.append({"title": "Para ver na consulta", "rows": consulta})
    opcoes = ([{"id": "menu:outra", "title": "Outra pergunta", "description": "Escrever a minha dúvida"}]
              if pub["duvidas_liberadas"] else [])
    opcoes += [{"id": "menu:explicacao", "title": "Rever a explicação"},
               {"id": "menu:exames", "title": "Meus exames", "description": "Trocar de exame ou enviar um laudo"},
               {"id": "menu:sair", "title": "Parar de receber", "description": "Cancelar a autorização"}]
    secoes.append({"title": "Outras opções", "rows": opcoes})
    interativo = {"type": "list", "body": {"text": corpo}, "action": {"button": "Ver dúvidas", "sections": secoes}}
    return avisos.enviar_interativo(paciente, interativo, f"[menu] {corpo} ({len(linhas)} dúvidas)")


def enviar_botoes(paciente, corpo="Posso ajudar em mais alguma coisa?"):
    interativo = {"type": "button", "body": {"text": corpo}, "action": {"buttons": [
        {"type": "reply", "reply": {"id": "menu:duvidas", "title": "Outras dúvidas"}},
        {"type": "reply", "reply": {"id": "menu:explicacao", "title": "Rever explicação"}},
        {"type": "reply", "reply": {"id": "menu:sair", "title": "Encerrar"}}]}}
    return avisos.enviar_interativo(paciente, interativo, f"[botões] {corpo}")


def oferecer_equipe(paciente, k):
    """Depois de uma dúvida que fica para a consulta: oferece mandar a pergunta para a equipe (fila do médico)."""
    interativo = {"type": "button", "body": {"text": "Quer que eu envie essa pergunta para a equipe da clínica? "
                                                     "A resposta chega por aqui."},
                  "action": {"buttons": [
                      {"type": "reply", "reply": {"id": f"equipe:{k}", "title": "Enviar à equipe"}},
                      {"type": "reply", "reply": {"id": "menu:duvidas", "title": "Outras dúvidas"}},
                      {"type": "reply", "reply": {"id": "menu:explicacao", "title": "Rever explicação"}}]}}
    return avisos.enviar_interativo(paciente, interativo, "[botões] Enviar à equipe?")


def enviar_para_equipe(pub, pergunta):
    """Põe a dúvida na fila do médico (tipo c), sem chamar a LLM. Devolve (id na fila, já estava na fila?)."""
    ja = banco.um("SELECT id FROM fila WHERE token=? AND pergunta=? AND status='aguardando'", pub["token"], pergunta)
    if ja:
        return ja["id"], True
    fid = banco.executar(
        "INSERT INTO fila (token, pergunta, tipo, destino_sugerido, prioridade, motivo, rascunho, fontes, status,"
        " criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)", pub["token"], pergunta, "c", "medico", "normal",
        "dúvida comum que fica para a consulta; o paciente pediu, pelo WhatsApp, para enviar à equipe", "", "[]",
        "aguardando", banco.agora())
    registrar_chat(pub["token"], "paciente", f"[enviar à equipe] {pergunta}", None)
    return fid, False


def enviar_explicacao(paciente, pub):
    status = avisos.enviar_conteudo(paciente, texto_explicacao(pub, interativo_ligado()))
    if interativo_ligado():
        enviar_menu(paciente, pub)
    banco.executar("UPDATE consentimentos SET explicacao_enviada_em=? WHERE paciente_id=? AND revogado_em IS NULL",
                   banco.agora(), paciente["id"])
    # no WhatsApp, receber a explicação conta como leitura (para de gerar lembrete)
    banco.executar("UPDATE publicacoes SET lido_em=COALESCE(lido_em, ?) WHERE laudo_id=?", banco.agora(), pub["laudo_id"])
    return status


# ---------------------------------------------------------------- envio de laudo (foto ou PDF)

MSG_ENVIAR = ("Pode mandar a foto ou o PDF do laudo aqui. Para dar certo:\n• página inteira, sem cortar os valores;\n"
              "• boa luz, sem sombra;\n• um laudo por vez.")
MSG_TIPO = "Por enquanto, consigo ler só foto (JPG ou PNG) ou PDF de laudo."
MSG_LENDO = "Recebi. Estou lendo o laudo, leva alguns segundos."
MSG_ILEGIVEL = ("Não consegui ler alguns valores com segurança. Pode mandar outra foto?\n• apoie o papel numa mesa;\n"
                "• tire de cima, sem inclinar;\n• evite sombra sobre os números.")
MSG_PARA_EQUIPE = ("Ainda não consegui ler tudo. Vou encaminhar o arquivo para a equipe da clínica conferir. "
                   "A resposta chega por aqui em até 2 dias úteis.")
MSG_PARA_EQUIPE_VALOR = ("Um dos valores deste laudo precisa ser conferido pela equipe da clínica antes de qualquer "
                         "explicação. Vamos olhar o arquivo e entrar em contato. Se você sentir dor no peito, falta de "
                         "ar ou fraqueza forte, ligue agora para o SAMU, no 192.")
MSG_OUTRA_PESSOA = ("Este laudo está em nome de outra pessoa. Por segurança, só explicamos laudos em seu nome. "
                    "Se você é responsável por essa pessoa, a recepção da clínica pode ajudar.")
MSG_ERRO_LEITURA = "Não consegui abrir este arquivo. Pode mandar de novo?"
MSG_REVISAO = "A explicação completa vai ser revisada pela equipe da clínica e chega aqui em até 2 dias úteis."
MSG_CORRECAO = "Qual valor está diferente? Pode escrever como está no papel."
MSG_CORRIGIDO = ("Obrigado, anotei. A equipe vai conferir com o arquivo, e a explicação chega aqui em até "
                 "2 dias úteis.")
MSG_CRITICO = (n.CONTATO_CRITICO + " Se você sentir dor no peito, falta de ar ou fraqueza forte, ligue agora para o "
               "SAMU, no 192.")
TENTATIVAS_LEITURA = 2


def enviar_navegacao(paciente, corpo="O que você quer fazer agora?"):
    """Fecho de cada desfecho do envio: o paciente nunca fica sem um próximo passo."""
    return avisos.enviar_interativo(paciente, {"type": "button", "body": {"text": corpo}, "action": {"buttons": [
        {"type": "reply", "reply": {"id": "menu:exames", "title": "Meus exames"}},
        {"type": "reply", "reply": {"id": "enviar:laudo", "title": "Enviar outro laudo"}}]}}, f"[botões] {corpo}")


def _envio(eid, **campos):
    if campos:
        sets = ", ".join(f"{k}=?" for k in campos)
        banco.executar(f"UPDATE envios SET {sets}, atualizado_em=? WHERE id=?", *campos.values(), banco.agora(), eid)
    return banco.um("SELECT * FROM envios WHERE id=?", eid)


def _faixa(item):
    """Faixa de referência como no papel: "70 a 99 mg/dL", "até 5,6 %", "a partir de 40 mg/dL"."""
    lo, hi = item.get("ref_min"), item.get("ref_max")
    if lo is not None and hi is not None:
        s = f"{n.num_br(lo)} a {n.num_br(hi)}"
    elif lo is not None:
        s = f"a partir de {n.num_br(lo)}"
    elif hi is not None:
        s = f"até {n.num_br(hi)}"
    else:
        return ""
    return f"{s} {item.get('unidade', '')}".strip()


def texto_valores(laudo):
    linhas = [f"• {i['analito']}: {n.num_br(i['valor'])} {i['unidade']}".rstrip()
              + (f" (referência {_faixa(i)})" if _faixa(i) else " (sem faixa de referência no laudo)")
              for i in laudo.get("itens", [])]
    return ("Li estes resultados. Confira se estão iguais ao papel:\n" + "\n".join(linhas)
            + f"\n\nExame: {laudo['exame']}\nNome no laudo: {leitura.iniciais(laudo.get('paciente'))}")


def linhas_valores(laudo):
    """["• LDL: 168 mg/dL — acima da faixa do laudo (até 130 mg/dL)", ...], algum_fora_da_faixa. Regra fixa, sem IA."""
    av, linhas, fora = avaliar_laudo(laudo), [], False
    for item, i in zip(laudo.get("itens", []), av["itens"]):
        if not _faixa(item):
            pos = "o laudo não traz faixa de referência para este item"
        else:
            pos = {"normal": "dentro da faixa do laudo", "alto": "acima da faixa do laudo",
                   "baixo": "abaixo da faixa do laudo"}[i["direcao"]] + f" ({_faixa(item)})"
            fora |= i["direcao"] != "normal"
        linhas.append(f"• {item['analito']}: {n.num_br(item['valor'])} {item['unidade']} — {pos}".replace("  ", " "))
    return linhas, fora


def resumo_imediato(laudo):
    """Só o que NÃO é gerado pela IA: valores conferidos pelo paciente, posição em relação à faixa do PRÓPRIO laudo
    (regra fixa) e definições APROVADAS do glossário. A explicação escrita pela IA espera a revisão (D6)."""
    av = avaliar_laudo(laudo)
    partes = [f"*{laudo['exame']}*", "_Resumo automático, feito só com o que está escrito no laudo. "
                                     "A explicação da equipe chega depois._", ""]
    fora = False
    if av["tipo"] == "laboratorio":
        linhas, fora = linhas_valores(laudo)
        partes += linhas
    else:
        partes.append("Este é um laudo de imagem: o texto do médico que fez o exame precisa ser explicado por um "
                      "profissional.")
    defs = n.termos_do_laudo(laudo, av, n.carregar_glossario())
    # "Hemoglobina" bate dentro de "hemoglobina glicada": fica só o termo mais específico, se o curto não for um item
    itens = {normalizar(i["analito"]) for i in laudo.get("itens", [])}
    nomes = [normalizar(d["termo"]) for d in defs]
    defs = [d for d, nm in zip(defs, nomes) if nm in itens or not any(o != nm and o.startswith(nm) for o in nomes)]
    if defs:
        partes += ["", "*O que é*"] + [f"• {d['termo']}: {d['definicao']}" for d in defs]
    if fora:
        partes += ["", "Estar fora da faixa do laudo não é, sozinho, um diagnóstico: o médico avalia junto com a sua "
                       "história."]
    return "\n".join(partes)


def receber_anexo(msg_id, wa_id, midia, processar_laudo):
    """Foto ou PDF recebido. midia = {"id", "mime", "nome"} (ou "conteudo" em bytes, nos testes).
    Antes da identificação e do aceite, o arquivo NÃO é baixado."""
    if banco.um("SELECT id FROM wa_recebidas WHERE id=?", msg_id):
        return "repetida"
    _registrar_recebida(msg_id, wa_id, f"[anexo] {midia.get('mime') or '?'} {midia.get('nome') or ''}".strip())
    s = _sessao(wa_id)
    pac, cons = _identificado(s)
    if not pac:
        return _triagem(_salvar(s, estado=None), wa_id, "")
    s = _salvar(s)
    if not cons:
        avisos.enviar_termo(wa_id, pac["id"])
        return "termo reenviado"
    if midia.get("mime") not in leitura.MIMES:
        avisos.enviar_conteudo(pac, MSG_TIPO)
        enviar_navegacao(pac)
        return "tipo de arquivo não aceito"
    eid = banco.executar("INSERT INTO envios (paciente_id, numero, mime, nome_arquivo, status, criado_em, atualizado_em)"
                         " VALUES (?,?,?,?,?,?,?)", pac["id"], s["numero"], midia["mime"], midia.get("nome"), "lendo",
                         banco.agora(), banco.agora())
    avisos.enviar_conteudo(pac, MSG_LENDO)
    try:
        conteudo = midia["conteudo"] if "conteudo" in midia else leitura.baixar_midia(midia["id"])[0]
        caminho = leitura.salvar(eid, conteudo, midia["mime"])
        texto, conf, como = leitura.extrair_texto(caminho, midia["mime"])
        texto = remover_cpfs(texto)  # CPF do laudo não vai para a LLM nem fica guardado
        bruto = leitura.estruturar(texto) if len(re.sub(r"\s", "", texto)) >= 20 else {}
        laudo, ilegiveis = leitura.conferir(bruto, texto)
    except Exception as e:  # noqa: BLE001 — qualquer falha de leitura vira pedido de reenvio, sem travar a conversa
        _envio(eid, status="erro", correcao=f"falha na leitura: {type(e).__name__}: {str(e)[:200]}")
        avisos.enviar_conteudo(pac, MSG_ERRO_LEITURA)
        return "erro na leitura"
    _envio(eid, arquivo=caminho, texto=texto, confianca=round(conf, 1),
           laudo_json=json.dumps({**laudo, "_como_foi_lido": como}, ensure_ascii=False))
    return _avaliar_envio(pac, s, eid, laudo, ilegiveis, processar_laudo)


def _avaliar_envio(pac, s, eid, laudo, ilegiveis, processar_laudo):
    nome_ok = leitura.mesmo_nome(laudo.get("paciente"), pac["nome"])
    if nome_ok is False:
        leitura.apagar(eid)
        _envio(eid, status="outra_pessoa")
        _salvar(s, etapa=None, envio_id=None)
        avisos.enviar_conteudo(pac, MSG_OUTRA_PESSOA)
        enviar_navegacao(pac)
        return "laudo de outra pessoa"
    vazio = (laudo["tipo"] == "laboratorio" and not laudo["itens"]) or \
            (laudo["tipo"] == "imagem" and len(re.sub(r"\s", "", laudo.get("texto", ""))) < 40)
    if ilegiveis or vazio:  # D4: laudo com campo ilegível não segue sozinho
        recentes = banco.um("SELECT COUNT(*) c FROM envios WHERE paciente_id=? AND status='ilegivel' AND "
                            "criado_em >= ?", pac["id"], (datetime.now() - timedelta(minutes=ETAPA_MIN)).isoformat())["c"]
        if recentes + 1 < TENTATIVAS_LEITURA:
            _envio(eid, status="ilegivel")
            _salvar(s, etapa="aguardando_anexo", envio_id=None)
            avisos.enviar_conteudo(pac, MSG_ILEGIVEL)
            return "ilegível; pediu outra foto"
        _envio(eid, status="equipe")
        _salvar(s, etapa=None, envio_id=None)
        _alerta("envio", f"Laudo enviado pelo WhatsApp por {pac['nome']} não pôde ser lido com segurança "
                         f"(ilegível: {', '.join(ilegiveis) or 'texto insuficiente'}): conferir o arquivo do envio {eid}",
                pac["id"], f"envio:{eid}")
        avisos.enviar_conteudo(pac, MSG_PARA_EQUIPE)
        enviar_navegacao(pac)
        return "ilegível; encaminhado à equipe"
    if laudo["tipo"] == "imagem":  # nada a conferir em número: segue direto para o resumo e a revisão
        return _finalizar_envio(pac, s, eid, processar_laudo)
    estranhos = [i["analito"] for i in laudo["itens"] if not leitura.plausivel(i)]
    if estranhos:  # 6.8 lido como 68, ou um valor muito fora: sem resumo automático, a equipe confere o arquivo
        _envio(eid, status="equipe")
        _salvar(s, etapa=None, envio_id=None)
        _alerta("contato_ativo" if avaliar_laudo(laudo)["prioridade"] == "critico" else "envio",
                f"Laudo enviado por {pac['nome']} pelo WhatsApp com valor muito fora da faixa ({', '.join(estranhos)}): "
                f"pode ser erro de leitura ou caso grave. Conferir o arquivo do envio {eid} e ligar se for o caso",
                pac["id"], f"envio:{eid}")
        avisos.enviar_conteudo(pac, MSG_PARA_EQUIPE_VALOR)
        enviar_navegacao(pac)
        return "valor muito fora da faixa; encaminhado à equipe"
    if avaliar_laudo(laudo)["prioridade"] == "critico":  # avisa a equipe já na leitura
        _alerta("contato_ativo", f"Valor crítico em laudo enviado por {pac['nome']} pelo WhatsApp (envio {eid}, "
                                 f"lido automaticamente: conferir com o arquivo)", pac["id"], f"envio:{eid}")
    # sem conferência do paciente (decisão de 14/11): os valores já passaram pelas checagens de leitura
    return _finalizar_envio(pac, s, eid, processar_laudo)


def _finalizar_envio(pac, s, eid, processar_laudo, correcao=None):
    e = _envio(eid)
    laudo = banco.j(e["laudo_json"])
    como = laudo.pop("_como_foi_lido", "")
    laudo["id"] = f"E{eid:03d}"
    laudo["_envio"] = {"envio_id": eid, "como_foi_lido": como, "confianca_ocr": e["confianca"],
                       "conferido_pelo_paciente": False, "resumo_enviado": correcao is None,
                       "correcao_do_paciente": correcao,
                       "nome_confere": leitura.mesmo_nome(laudo.get("paciente"), pac["nome"])}
    _envio(eid, status="em_revisao", laudo_id=laudo["id"], correcao=correcao)
    _salvar(s, etapa=None, envio_id=None)
    if correcao is None:
        if laudo["tipo"] == "laboratorio" and avaliar_laudo(laudo)["prioridade"] == "critico":
            avisos.enviar_conteudo(pac, MSG_CRITICO)
        avisos.enviar_conteudo(pac, resumo_imediato(laudo))
        avisos.enviar_conteudo(pac, MSG_REVISAO)
    else:
        avisos.enviar_conteudo(pac, MSG_CORRIGIDO)
    enviar_navegacao(pac)  # antes do rascunho da IA, para o paciente não esperar a LLM
    if processar_laudo:  # rascunho da IA para a fila de revisão do painel (1 a 2 chamadas à LLM interna)
        processar_laudo(pac["id"], laudo)
    return "resumo imediato enviado; em revisão" if correcao is None else "correção anotada; em revisão"


def _registrar_recebida(msg_id, wa_id, texto):
    banco.executar("INSERT INTO wa_recebidas VALUES (?,?,?,?)", msg_id, wa_id, texto[:500], banco.agora())


def receber(msg_id, wa_id, texto, processar_duvida, processar_laudo=None):
    """Trata uma mensagem de texto. processar_duvida(token, pergunta) é a pista da dúvida do serviço;
    processar_laudo(paciente_id, laudo) gera o rascunho de um laudo enviado (para a revisão)."""
    if banco.um("SELECT id FROM wa_recebidas WHERE id=?", msg_id):
        return "repetida"  # a Meta pode reenviar o mesmo evento
    s = _sessao(wa_id)
    # CPF e data de nascimento não ficam guardados em texto no registro
    guardado = {"pede_cpf": "[CPF informado]", "pede_nascimento": "[data de nascimento informada]"}.get(s["estado"])
    _registrar_recebida(msg_id, wa_id, guardado or remover_cpfs(texto))
    pac, cons = _identificado(s)
    t = normalizar(texto)

    if not (pac and cons) and chatbot.filtro_alarme(texto):  # urgência não espera a identificação
        msg = chatbot.MSG_URGENCIA + (" " + chatbot.MSG_CVV if chatbot._CVV.search(t) else "")
        avisos.enviar_triagem(wa_id, msg, pac and pac["id"])
        quem = pac["nome"] if pac else f"número {_mascara(wa_id)} (não identificado)"
        _alerta("urgencia", f"SINAL DE ALARME no WhatsApp de {quem}: “{remover_cpfs(texto)[:120]}”", pac and pac["id"], f"wa:{msg_id}")
        return "urgência"

    if t in ("sair", "parar", "cancelar"):
        if pac and cons:
            revogar(pac["id"])
            avisos.enviar_triagem(wa_id, avisos.TRIAGEM["revogado"], pac["id"])
            resultado = "revogado"
        else:
            avisos.enviar_triagem(wa_id, avisos.TRIAGEM["encerrado"], pac and pac["id"])
            resultado = "encerrado"
        banco.executar("DELETE FROM wa_sessoes WHERE numero=?", s["numero"])
        return resultado

    if not pac:
        return _triagem(s, wa_id, texto)
    s = _salvar(s)  # renova as 24 h
    if not cons:
        avisos.enviar_termo(wa_id, pac["id"])
        return "termo reenviado"

    if s.get("etapa") == "corrigindo" and s.get("envio_id"):  # correção de um valor lido do laudo enviado
        return _finalizar_envio(pac, s, int(s["envio_id"]), processar_laudo, correcao=remover_cpfs(texto)[:300])
    if s.get("etapa") in ("aguardando_anexo", "conferindo"):  # escreveu em vez de mandar o arquivo ou conferir
        s = _salvar(s, etapa=None, envio_id=None)

    if _QUER_ENVIAR.search(t):  # "quero mandar um novo laudo": o mesmo que o botão "Enviar um laudo"
        _salvar(s, etapa="aguardando_anexo", envio_id=None)
        avisos.enviar_conteudo(pac, MSG_ENVIAR)
        return "aguardando anexo"
    pubs = publicacoes(pac["id"])
    if not pubs or _QUER_EXAMES.search(t):
        enviar_lista_exames(pac, None if not pubs else "Qual exame você quer ver?")
        return "lista de exames" if pubs else "sem publicação"
    pub = pub_ativa(s, pac["id"])
    if _SAUDACAO.match(t) or not cons["explicacao_enviada_em"]:
        if len(pubs) > 1:
            enviar_lista_exames(pac)
            return "lista de exames"
        enviar_explicacao(pac, pub)
        return "explicação enviada"
    if not pub["duvidas_liberadas"]:
        avisos.enviar_conteudo(pac, "As dúvidas sobre este exame serão respondidas na sua consulta.")
        return "dúvidas não liberadas"
    outro = exame_citado(texto, pac["id"], pub)
    if outro:  # a pergunta parece ser sobre outro exame do paciente: pergunta antes de responder
        _salvar(s, pendente=remover_cpfs(texto).strip()[:500])
        avisos.enviar_interativo(pac, {"type": "button", "body": {
            "text": f"Sua pergunta parece ser sobre o *{outro['exame']}*. Quer ver esse exame?"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": f"exame:{outro['laudo_id']}", "title": "Ver esse exame"}},
                {"type": "reply", "reply": {"id": "pergunta:continuar", "title": "Continuar aqui"}}]}},
            "[botões] Pergunta sobre outro exame?")
        return "pergunta sobre outro exame"
    return _responder_duvida(pac, pub, remover_cpfs(texto).strip()[:500], processar_duvida)


def _responder_duvida(pac, pub, pergunta, processar_duvida):
    r = processar_duvida(pub["token"], pergunta)  # CPF já removido: não vai para a fila nem para a LLM
    avisos.enviar_conteudo(pac, r["mensagem"])
    if interativo_ligado() and r["tipo_final"] in ("a", "b", "c"):
        enviar_botoes(pac)
    return f"dúvida tipo {r['tipo_final']}"


def receber_escolha(msg_id, wa_id, escolha_id, titulo, processar_duvida=None, processar_laudo=None):
    """Toque num botão ou numa opção da lista. Dúvidas aprovadas são respondidas na hora, sem IA (F1)."""
    if banco.um("SELECT id FROM wa_recebidas WHERE id=?", msg_id):
        return "repetida"
    _registrar_recebida(msg_id, wa_id, f"[escolha] {escolha_id}")
    s = _sessao(wa_id)
    pac, cons = _identificado(s)
    if not pac:  # sessão expirou ou nunca houve: recomeça a identificação
        return _triagem(_salvar(s, estado=None), wa_id, "")
    s = _salvar(s)
    if escolha_id == "termo:sim":
        aceitar(pac["id"])
        avisos.enviar_triagem(wa_id, avisos.TRIAGEM["termo_aceito"], pac["id"])
        _enviar_resultado(pac, s)
        return "consentimento registrado"
    if escolha_id == "termo:nao":
        if cons:  # já tinha aceitado antes: "Não" agora vale como revogação
            revogar(pac["id"])
        avisos.enviar_triagem(wa_id, avisos.TRIAGEM["termo_recusado"], pac["id"])
        return "termo recusado"
    if not cons:
        avisos.enviar_termo(wa_id, pac["id"])
        return "termo reenviado"
    if escolha_id == "menu:sair":
        revogar(pac["id"])
        avisos.enviar_triagem(wa_id, avisos.TRIAGEM["revogado"], pac["id"])
        banco.executar("DELETE FROM wa_sessoes WHERE numero=?", s["numero"])
        return "revogado"
    if escolha_id == "menu:exames":
        enviar_lista_exames(pac, "Qual exame você quer ver?")
        return "lista de exames"
    if escolha_id == "enviar:laudo":
        _salvar(s, etapa="aguardando_anexo", envio_id=None)
        avisos.enviar_conteudo(pac, MSG_ENVIAR)
        return "aguardando anexo"
    if escolha_id.startswith("envio:"):
        _, acao, eid = escolha_id.split(":")
        e = banco.um("SELECT * FROM envios WHERE id=? AND paciente_id=?", int(eid), pac["id"])
        if not e or e["status"] != "conferir":
            return "envio já tratado"
        if acao == "ok":
            return _finalizar_envio(pac, s, int(eid), processar_laudo)
        _salvar(s, etapa="corrigindo", envio_id=eid)
        avisos.enviar_conteudo(pac, MSG_CORRECAO)
        return "aguardando correção"
    if escolha_id.startswith("exame:"):
        pub = banco.um("SELECT * FROM publicacoes WHERE laudo_id=? AND paciente_id=?", escolha_id[6:], pac["id"])
        if not pub:
            enviar_lista_exames(pac)
            return "exame não encontrado"
        _salvar(s, laudo_ativo=pub["laudo_id"], pendente=None)
        enviar_explicacao(pac, pub)
        return f"exame ativo: {pub['laudo_id']}"
    pub = pub_ativa(s, pac["id"])
    if not pub:
        enviar_lista_exames(pac)
        return "sem publicação"
    if escolha_id == "pergunta:continuar":
        pergunta = s.get("pendente")
        _salvar(s, pendente=None)
        if not pergunta or not processar_duvida:
            enviar_menu(pac, pub)
            return "sem pergunta pendente"
        return _responder_duvida(pac, pub, pergunta, processar_duvida)
    if escolha_id == "menu:explicacao":
        avisos.enviar_conteudo(pac, texto_explicacao(pub, True))
        enviar_menu(pac, pub)
        return "explicação reenviada"
    if escolha_id == "menu:duvidas":
        enviar_menu(pac, pub, "Escolha uma dúvida ou escreva a sua pergunta.")
        return "menu"
    if escolha_id == "menu:outra":
        avisos.enviar_conteudo(pac, "Pode escrever a sua pergunta aqui. Em caso de urgência, ligue 192 (SAMU).")
        return "aguardando pergunta"
    if escolha_id.startswith("duv:"):
        duvidas = banco.j(pub["duvidas_json"], [])
        k = int(escolha_id.split(":", 1)[1])
        if not pub["duvidas_liberadas"] or k >= len(duvidas):
            enviar_menu(pac, pub)
            return "opção inválida"
        d = duvidas[k]
        registrar_chat(pub["token"], "paciente", d["pergunta"], None)
        registrar_chat(pub["token"], "sistema", d["resposta"], "a")  # conteúdo aprovado pelo profissional
        avisos.enviar_conteudo(pac, d["resposta"])  # a escolha do paciente já aparece logo acima
        if responde_na_hora(d):
            enviar_botoes(pac)
            return "dúvida aprovada respondida"
        oferecer_equipe(pac, k)
        return "dúvida para a consulta; ofereceu enviar à equipe"
    if escolha_id.startswith("equipe:"):
        duvidas = banco.j(pub["duvidas_json"], [])
        k = int(escolha_id.split(":", 1)[1])
        if not pub["duvidas_liberadas"] or k >= len(duvidas):
            enviar_menu(pac, pub)
            return "opção inválida"
        fid, repetida = enviar_para_equipe(pub, duvidas[k]["pergunta"])
        avisos.enviar_conteudo(pac, "Essa pergunta já está com a equipe da clínica. A resposta chega por aqui."
                               if repetida else chatbot.MSG_ENCAMINHADO)
        enviar_botoes(pac)
        return f"enviada à equipe (fila {fid})" + (" — já estava" if repetida else "")
    return "escolha desconhecida"


def numero_clinica():
    return os.environ.get("WHATSAPP_NUMERO_CLINICA", "")
