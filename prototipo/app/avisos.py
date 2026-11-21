"""Mensagens ao paciente pelo WhatsApp. Sem consentimento: SÓ textos fixos e genéricos, nunca dado de saúde.

Desde 14/11 (D3, 2ª revisão) o WhatsApp é o canal do paciente: o aviso de publicação pede para responder OI,
e a triagem (CPF + data de nascimento + termo) acontece na própria conversa. O portal ficou só para a equipe.

WHATSAPP_MODO no .env:
  simulado  (padrão) grava o aviso no banco; aparece na tela /painel/whatsapp
  meta      envia pela WhatsApp Cloud API (número de teste), com WHATSAPP_TOKEN e WHATSAPP_PHONE_ID

Mensagem iniciada pela clínica só sai por MODELO APROVADO na Meta. Nomes no .env (idioma em WHATSAPP_IDIOMA):
  WHATSAPP_MODELO_AVISO     "Há uma nova mensagem da clínica para você: {{1}}"        (utilidade; {{1}} = link)
  WHATSAPP_MODELO_LEMBRETE  "Lembrete: há uma mensagem da clínica para você: {{1}}"   (utilidade; {{1}} = link)
  WHATSAPP_MODELO_CODIGO    modelo de autenticação com botão "copiar código"           ({{1}} = código)
Sem modelo configurado, cai para texto livre, que a Meta só entrega nas 24 h após uma mensagem do paciente.
Em todos os modos o texto é conferido antes: fora dos modelos genéricos, o aviso é bloqueado.
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import banco

RESPOSTA_SEM_CONSENTIMENTO = ("Olá! Para proteger seus dados, as informações dos exames ficam no portal da clínica. "
                              "Use o link que você recebeu. Se quiser receber por aqui, autorize no portal.")
RESPOSTA_REVOGADO = ("Pronto: você não vai mais receber informações de exames pelo WhatsApp. "
                     "O resultado será explicado na sua consulta.")
AVISO_CONVERSA = "responda OI nesta conversa para ver."  # valor do {{1}} dos modelos de aviso e lembrete

# Triagem pelo WhatsApp: textos FIXOS (sem dado de saúde), enviados antes ou durante a identificação.
TRIAGEM = {
    "boas_vindas": "Olá! Este é o atendimento de exames da clínica. Para proteger os seus dados, primeiro preciso "
                   "confirmar quem é você. Digite o seu CPF (só os números).",
    "cpf_invalido": "Esse CPF não é válido. Confira e digite os 11 números do seu CPF.",
    "pede_nascimento": "Obrigado. Agora digite a sua data de nascimento (por exemplo, 25/03/1980).",
    "data_invalida": "Não reconheci a data. Digite a sua data de nascimento no formato dia/mês/ano "
                     "(por exemplo, 25/03/1980).",
    "nao_confere": "Não consegui confirmar os seus dados. Vamos tentar de novo: digite o seu CPF (só os números).",
    "bloqueado": "Não foi possível confirmar os seus dados. Por segurança, tente de novo em 30 minutos ou fale com "
                 "a recepção da clínica.",
    "identificado": "Pronto, identidade confirmada.",
    "sem_resultado": "Ainda não há resultado de exame disponível para você. Quando houver, avisaremos por aqui.",
    "termo_aceito": "Obrigado! Autorização registrada. Você pode cancelar quando quiser, respondendo SAIR.",
    "termo_recusado": "Tudo bem. Sem a sua autorização, não enviamos informações de exames pelo WhatsApp. "
                      "O resultado será explicado na sua consulta, e a recepção da clínica pode ajudar com o que "
                      "precisar. Se mudar de ideia, é só escrever OI.",
    "encerrado": "Atendimento encerrado. Quando quiser, é só escrever OI.",
    "revogado": RESPOSTA_REVOGADO,
}
TERMO_WHATSAPP = ("Para receber aqui a explicação dos seus exames e tirar dúvidas pelo WhatsApp, precisamos da sua "
                  "autorização.\n\nAs mensagens do WhatsApp passam pelos servidores da Meta (empresa dona do WhatsApp), "
                  "que podem ficar fora do Brasil, e qualquer pessoa com acesso ao seu celular poderá lê-las. Você "
                  "pode cancelar quando quiser, respondendo SAIR.\n\nVocê autoriza?")

TIPOS = [  # (tipo, padrão do texto, variável de ambiente do modelo)
    ("aviso", re.compile(r"^Há uma nova mensagem da clínica para você: (" + re.escape(AVISO_CONVERSA) + r"|\S+)$"),
     "WHATSAPP_MODELO_AVISO"),
    ("lembrete", re.compile(r"^Lembrete: há uma mensagem da clínica para você: (" + re.escape(AVISO_CONVERSA)
                            + r"|\S+)$"), "WHATSAPP_MODELO_LEMBRETE"),
    ("codigo", re.compile(r"^Seu código de acesso ao portal da clínica é (\d{6})\. Ele vale por 10 minutos\.$"),
     "WHATSAPP_MODELO_CODIGO"),
    ("resposta_generica", re.compile("^(" + re.escape(RESPOSTA_SEM_CONSENTIMENTO) + "|" + re.escape(RESPOSTA_REVOGADO)
                                     + ")$"), "WHATSAPP_MODELO_NENHUM"),
]


def classificar(texto):
    for tipo, padrao, var in TIPOS:
        m = padrao.match(texto)
        if m:
            return tipo, m.group(1), var
    return None, None, None


def enviar(paciente, texto):
    """Envia (ou simula) o aviso. Recusa qualquer texto fora dos modelos genéricos: falha segura contra vazamento."""
    tipo, valor, var = classificar(texto)
    if not tipo:
        raise ValueError("texto fora do modelo genérico: aviso bloqueado (nenhum dado de saúde no WhatsApp)")
    modo = os.environ.get("WHATSAPP_MODO", "simulado")
    status, detalhe = "simulado", ""
    if modo == "meta":
        modelo = os.environ.get(var, "").strip()
        status, detalhe = _enviar_meta(paciente["telefone"], texto, tipo, valor, modelo)
    banco.executar("INSERT INTO avisos (paciente_id, telefone, texto, canal, status, detalhe, criado_em) "
                   "VALUES (?,?,?,?,?,?,?)", paciente["id"], paciente["telefone"], texto, modo, status, detalhe,
                   banco.agora())
    return status


def enviar_conteudo(paciente, texto):
    """Conteúdo de saúde (explicação, resposta de dúvida) pelo WhatsApp: SÓ com consentimento ativo (D3 revisada).
    Sai como texto livre, que a Meta entrega na janela de 24 h aberta pela mensagem do paciente."""
    if not banco.um("SELECT id FROM consentimentos WHERE paciente_id=? AND canal='whatsapp' AND revogado_em IS NULL",
                    paciente["id"]):
        raise PermissionError("sem consentimento ativo: conteúdo de saúde bloqueado no WhatsApp")
    modo = os.environ.get("WHATSAPP_MODO", "simulado")
    status, detalhe = "simulado", "conteúdo com consentimento"
    if modo == "meta":
        status, detalhe = _enviar_meta(paciente["telefone"], texto, "conteudo", None, "")
        detalhe = "conteúdo com consentimento · " + detalhe
    banco.executar("INSERT INTO avisos (paciente_id, telefone, texto, canal, status, detalhe, criado_em) "
                   "VALUES (?,?,?,?,?,?,?)", paciente["id"], paciente["telefone"], texto, modo, status, detalhe,
                   banco.agora())
    return status


def numero_envio(numero):
    """Só dígitos. Celular brasileiro sem o 9 (a Meta às vezes manda o wa_id assim: 55 + DDD + 8 dígitos) ganha o 9 de
    volta: a lista de destinatários do número de teste só aceita o número completo."""
    d = re.sub(r"\D", "", numero or "")
    if len(d) == 12 and d.startswith("55") and d[4] in "6789":
        d = d[:4] + "9" + d[4:]
    return d


def _textos_triagem():
    import chatbot  # mensagens fixas de urgência (SAMU 192, CVV 188)
    return set(TRIAGEM.values()) | {chatbot.MSG_URGENCIA, chatbot.MSG_URGENCIA + " " + chatbot.MSG_CVV}


def _registrar(paciente_id, numero, texto, modo, status, detalhe):
    banco.executar("INSERT INTO avisos (paciente_id, telefone, texto, canal, status, detalhe, criado_em) "
                   "VALUES (?,?,?,?,?,?,?)", paciente_id, numero, texto, modo, status, detalhe, banco.agora())


def enviar_triagem(numero, texto, paciente_id=None):
    """Resposta da triagem para quem escreveu (ainda sem identificação ou sem consentimento). Só textos fixos:
    qualquer outro texto é bloqueado. Sai como texto livre, dentro da janela aberta pela mensagem do paciente."""
    if texto not in _textos_triagem():
        raise ValueError("texto fora da triagem: bloqueado (nenhum dado de saúde antes do consentimento)")
    modo = os.environ.get("WHATSAPP_MODO", "simulado")
    status, detalhe = "simulado", "triagem"
    if modo == "meta":
        status, detalhe = _enviar_meta(numero, texto, "triagem", None, "")
        detalhe = "triagem · " + detalhe
    _registrar(paciente_id, numero, texto, modo, status, detalhe)
    return status


def enviar_termo(numero, paciente_id):
    """Termo de consentimento com botões Sim / Não (texto fixo, sem dado de saúde)."""
    interativo = {"type": "button", "body": {"text": TERMO_WHATSAPP}, "action": {"buttons": [
        {"type": "reply", "reply": {"id": "termo:sim", "title": "Sim, autorizo"}},
        {"type": "reply", "reply": {"id": "termo:nao", "title": "Não autorizo"}}]}}
    modo = os.environ.get("WHATSAPP_MODO", "simulado")
    status, detalhe = "simulado", "termo"
    if modo == "meta":
        status, detalhe = _post_interativo(numero, interativo)
        detalhe = "termo · " + detalhe
    _registrar(paciente_id, numero, "[termo de consentimento: Sim / Não]", modo, status, detalhe)
    return status


def _post_interativo(numero, interativo):
    versao = os.environ.get("WHATSAPP_API_VERSAO", "v25.0")
    corpo = {"messaging_product": "whatsapp", "to": numero_envio(numero), "type": "interactive",
             "interactive": interativo}
    req = urllib.request.Request(f"https://graph.facebook.com/{versao}/{os.environ['WHATSAPP_PHONE_ID']}/messages",
                                 data=json.dumps(corpo).encode(), headers={
                                     "Content-Type": "application/json",
                                     "Authorization": "Bearer " + os.environ["WHATSAPP_TOKEN"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return "enviado", r.read().decode()[:150]
    except urllib.error.HTTPError as e:
        return "erro", e.read().decode(errors="ignore")[:300]
    except urllib.error.URLError as e:
        return "erro", str(e)[:300]


def enviar_interativo(paciente, interativo, resumo):
    """Lista ou botões do WhatsApp (só com consentimento, como o conteúdo). 'resumo' vai para o registro."""
    if not banco.um("SELECT id FROM consentimentos WHERE paciente_id=? AND canal='whatsapp' AND revogado_em IS NULL",
                    paciente["id"]):
        raise PermissionError("sem consentimento ativo: mensagem interativa bloqueada")
    modo = os.environ.get("WHATSAPP_MODO", "simulado")
    status, detalhe = "simulado", "interativo"
    if modo == "meta":
        status, detalhe = _post_interativo(paciente["telefone"], interativo)
        detalhe = "interativo · " + detalhe
    banco.executar("INSERT INTO avisos (paciente_id, telefone, texto, canal, status, detalhe, criado_em) "
                   "VALUES (?,?,?,?,?,?,?)", paciente["id"], paciente["telefone"], resumo, modo, status, detalhe,
                   banco.agora())
    return status


def _corpo(para, texto, tipo, valor, modelo):
    if not modelo:  # sem modelo: texto livre (só entregue dentro da janela de 24 h)
        return {"messaging_product": "whatsapp", "to": para, "type": "text",
                "text": {"preview_url": True, "body": texto}}
    componentes = [{"type": "body", "parameters": [{"type": "text", "text": valor}]}]
    if tipo == "codigo":  # modelo de autenticação: o botão "copiar código" recebe o mesmo código
        componentes.append({"type": "button", "sub_type": "url", "index": "0",
                            "parameters": [{"type": "text", "text": valor}]})
    return {"messaging_product": "whatsapp", "to": para, "type": "template",
            "template": {"name": modelo, "language": {"code": os.environ.get("WHATSAPP_IDIOMA", "pt_BR")},
                         "components": componentes}}


def _enviar_meta(telefone, texto, tipo, valor, modelo):
    versao = os.environ.get("WHATSAPP_API_VERSAO", "v25.0")
    url = f"https://graph.facebook.com/{versao}/{os.environ['WHATSAPP_PHONE_ID']}/messages"
    corpo = _corpo(numero_envio(telefone), texto, tipo, valor, modelo)
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["WHATSAPP_TOKEN"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return "enviado", (f"modelo {modelo}" if modelo else "texto livre") + " · " + r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return "erro", e.read().decode(errors="ignore")[:300]
    except urllib.error.URLError as e:
        return "erro", str(e)[:300]
