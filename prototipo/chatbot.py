"""Pista da dúvida (D1, D2, D3): o paciente pergunta no chat do portal, já autenticado.

Fluxo:
  1. filtro de alarme por lista (determinístico): se bater, tipo d sem chamar a LLM;
  2. classificador a–e pela LLM (também detecta alarme: redundância com a lista);
  3. contexto (D2): tipo a → só a explicação e as dúvidas APROVADAS deste paciente (consulta direta);
     tipo b → RAG só na base da clínica (sem dado pessoal);
  4. resposta com citação das fontes; se as fontes não cobrem, vira c;
  5. verificação de apoio (2ª chamada) + proteções (causa, prognóstico): sem apoio → vira c;
  6. destino: responde (a, b), fila de triagem com rascunho (c), mensagem de urgência + alerta (d),
     recepção ou recusa (e). Mensagens ao paciente nos casos c, d, e são FIXAS.

Uso:
  python3 chatbot.py "Preciso de jejum para o exame de glicose?"
  python3 chatbot.py --cenario duvidas/cenario_C01.json "O que é a tireoide?"
"""
import argparse
import glob
import json
import math
import os
import re
import time
from datetime import datetime

import nucleo as n
from regra import normalizar

# ---------------------------------------------------------------- mensagens fixas (nunca geradas pela LLM)

MSG_URGENCIA = ("Pelo que você escreveu, isso pode precisar de atendimento imediato. Procure agora o pronto-socorro "
                "mais próximo ou ligue para o SAMU, no 192. A equipe da clínica já foi avisada.")
MSG_CVV = ("Se você está pensando em se machucar ou sente que não aguenta mais, ligue agora para o CVV, no 188. "
           "A ligação é gratuita e funciona 24 horas. Você não precisa passar por isso sem ajuda.")
MSG_ENCAMINHADO = ("Sua pergunta foi encaminhada para a equipe da clínica, que vai responder por aqui em até "
                   "2 dias úteis. Você vai receber um aviso quando a resposta chegar.")
MSG_ACOLHIMENTO = ("Entendemos que esperar por uma resposta pode ser difícil. Sua mensagem foi encaminhada com "
                   "prioridade para a equipe da clínica, que vai responder o quanto antes. Se a angústia ficar muito "
                   "forte, você também pode ligar para o CVV, no 188, a qualquer hora.")
MSG_RECEPCAO = "Esse assunto é tratado pela recepção da clínica. Sua mensagem foi encaminhada para lá."
MSG_RECUSA = ("Não posso ajudar com esse pedido. Por aqui, eu só respondo dúvidas sobre os seus próprios exames, "
              "já revisados pela equipe da clínica.")

# ---------------------------------------------------------------- 1. filtro de alarme por lista

ALARME = [
    ("dor no peito", r"\b(dor|aperto|pressao) no peito"),
    ("falta de ar", r"falta de ar|nao consigo respirar|dificuldade (pra|para) respirar|sem ar\b"),
    ("desmaio", r"desmai"),
    ("convulsão", r"convuls"),
    ("sangramento", r"sangramento (forte|intenso|que nao para)|vomit\w* (com )?sangue"),
    ("sinais de AVC", r"boca torta|fraqueza (de um lado|no braco|na perna)|nao consigo (falar|mexer)"),
    ("glicose muito alta", r"(glicose|glicemia|dextro)\D{0,40}\b([3-9]\d\d|[1-9]\d{3})\b"),
    ("pressão muito alta", r"pressao\D{0,20}\b(2\d|1[89])\s*(por|x|/)\s*\d+"),
    ("risco de suicídio", r"suicid|me matar|tirar (a )?minha (propria )?vida|quero morrer|nao (vejo|tem) (mais )?sentido"
                          r"|nao aguento mais|quero sumir|acabar com tudo"),
]
_CVV = re.compile(ALARME[-1][1])
# assunto de logística/administração: se as fontes não respondem, vai para a recepção (não para a equipe clínica)
_LOGISTICA = re.compile(r"quanto tempo|demora|prazo|fica pronto|sai o resultado|quando (sai|fica|chega)|horario"
                        r"|agend|marcar|remarc|segunda via|convenio|pagamento|boleto|endereco|telefone|estaciona")
_ACOLHIMENTO = re.compile(r"assustad|apavorad|ansios|com (muito )?medo|nao consigo dormir|desesperad|angusti"
                          r"|muito preocupad|nervos[oa]")


def filtro_alarme(pergunta):
    texto = normalizar(pergunta)
    return [rotulo for rotulo, padrao in ALARME if re.search(padrao, texto)]

# ---------------------------------------------------------------- 2. classificador

def _json(bruto):
    try:
        return json.loads(re.sub(r"^```(?:json)?|```$", "", bruto.strip(), flags=re.M))
    except ValueError:
        return None


def contexto_do_paciente(cenario):
    linhas = [f"Exames do paciente: {cenario['exames']}", "", "Explicação aprovada:", cenario["explicacao_aprovada"]]
    if cenario.get("duvidas_aprovadas"):
        linhas += ["", "Dúvidas aprovadas:"] + [f"- {d['pergunta']} {d['resposta']}" for d in cenario["duvidas_aprovadas"]]
    for o in cenario.get("outros_exames", []):
        linhas += ["", f"Outro exame aprovado ({o['exame']}):", o["explicacao"]]
    for e in cenario.get("laudos_enviados", []):
        linhas += ["", f"Laudo enviado pelo paciente ({e['exame']}), valores conferidos por ele:"] + e["valores"]
    return "\n".join(linhas)


def classificar(pergunta, cenario):
    alarmes = filtro_alarme(pergunta)
    if alarmes:
        return {"tipo": "d", "destino": "urgencia", "prioridade": "alta", "motivo": "lista: " + ", ".join(alarmes),
                "fonte": "lista", "chamadas_llm": 0}
    msg = contexto_do_paciente(cenario) + "\n\nMensagem do paciente:\n" + pergunta
    try:
        bruto, _ = n.chamar_interna(os.environ.get("LLM_MODEL", ""), n.ler_prompt("classificador_sistema.txt"), msg,
                                    force_json=True)
        dados = _json(bruto) or {}
    except Exception as e:  # falha segura: na dúvida, vai para humanos
        dados = {"erro": str(e)}
    tipo = str(dados.get("tipo", "")).strip().lower()[:1]
    if tipo not in "abcde" or not tipo:
        return {"tipo": "c", "destino": "enfermagem", "prioridade": "normal", "fonte": "falha segura",
                "motivo": "classificador sem resposta válida → triagem", "chamadas_llm": 1}
    r = {"tipo": tipo, "destino": dados.get("destino", ""), "prioridade": dados.get("prioridade", "normal"),
         "motivo": dados.get("motivo", ""), "fonte": "llm", "chamadas_llm": 1}
    if tipo == "d":
        r["destino"], r["prioridade"] = "urgencia", "alta"
    if _ACOLHIMENTO.search(normalizar(pergunta)) and tipo in "abc":  # sofrimento: triagem com prioridade (caso 17)
        r.update(tipo="c", prioridade="alta", destino=r["destino"] if tipo == "c" else "enfermagem")
    return r

# ---------------------------------------------------------------- 3. RAG na base da clínica (busca lexical BM25)

_STOP = set("a o as os um uma uns umas de da do das dos e em no na nos nas para pra por com que se ao aos eu meu "
            "minha seu sua isso esse essa este esta ele ela ja mais muito como qual quais quando onde porque "
            "por que tem ter ser estar foi sao esta vou voce voces nao sim".split())


def _tokens(texto):
    return [w[:6] for w in re.findall(r"[a-z0-9]+", normalizar(texto)) if w not in _STOP and len(w) > 2]


def carregar_base(pasta=os.path.join(n.AQUI, "base_clinica")):
    trechos = []
    for caminho in sorted(glob.glob(os.path.join(pasta, "B*.md"))):
        doc = os.path.basename(caminho).split("_")[0]
        texto = open(caminho, encoding="utf-8").read()
        titulo = re.search(r"^# (.+)$", texto, flags=re.M).group(1)
        for k, secao in enumerate(re.split(r"^## ", texto, flags=re.M)[1:], 1):
            cab, _, corpo = secao.partition("\n")
            trechos.append({"id": f"{doc}-{k}", "titulo": f"{titulo}: {cab.strip()}", "texto": corpo.strip()})
    return trechos


def buscar_base(pergunta, base, k=3, k1=1.5, b=0.75):
    docs = [_tokens(t["titulo"] + " " + t["texto"]) for t in base]
    if not docs:
        return []
    media = sum(map(len, docs)) / len(docs)
    consulta = set(_tokens(pergunta))
    notas = []
    for t, d in zip(base, docs):
        nota = 0.0
        for termo in consulta:
            f = d.count(termo)
            if not f:
                continue
            df = sum(1 for x in docs if termo in x)
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            nota += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / media))
        if nota > 0:
            notas.append((nota, t))
    return [t for _, t in sorted(notas, key=lambda x: -x[0])[:k]]

# ---------------------------------------------------------------- 4–6. resposta, verificação e destino

def fontes_do_paciente(cenario):
    """[A] exame que o paciente está vendo; [P] outros exames aprovados dele; [E] laudos que ele enviou (valores
    conferidos por ele, ainda sem explicação da equipe). Tudo aprovado ou conferido: nada gerado pela IA."""
    fontes = [("A", cenario["explicacao_aprovada"])]
    fontes += [(f"A{k}", f"{d['pergunta']} {d['resposta']}") for k, d in enumerate(cenario.get("duvidas_aprovadas", []), 1)]
    fontes += [(f"P{k}", f"Outro exame do paciente, já explicado e aprovado ({o['exame']}): {o['explicacao']}")
               for k, o in enumerate(cenario.get("outros_exames", []), 1)]
    fontes += [(f"E{k}", f"Laudo que o paciente enviou ({e['exame']}). Valores conferidos pelo paciente: "
                         f"{' '.join(e['valores'])} A explicação completa da equipe chega depois da revisão.")
               for k, e in enumerate(cenario.get("laudos_enviados", []), 1)]
    return fontes


_GLOSSARIO = []


def definicoes_da_pergunta(pergunta, cenario, maximo=4):
    """[G] definições APROVADAS do glossário para os termos citados na pergunta (o 'requer' vale para o contexto)."""
    if not _GLOSSARIO:
        _GLOSSARIO.extend(n.carregar_glossario())
    perg = normalizar(pergunta)
    contexto = normalizar(pergunta + " " + cenario.get("explicacao_aprovada", "") + " " + cenario.get("exames", ""))
    achados = []
    for t in _GLOSSARIO:
        if t.get("requer") and not re.search(r"\b" + re.escape(normalizar(t["requer"])), contexto):
            continue
        if any(re.search(r"\b" + re.escape(normalizar(p)), perg) for p in t["padroes"]):
            achados.append(t)
    nomes = [normalizar(t["termo"]) for t in achados]  # "hemoglobina" dentro de "hemoglobina glicada": fica o específico
    achados = [t for t, nm in zip(achados, nomes) if not any(o != nm and o.startswith(nm) for o in nomes)]
    return [(f"G{k}", f"{t['termo']}: {t['definicao']}.") for k, t in enumerate(achados[:maximo], 1)]


def todas_as_fontes(pergunta, cenario, base):
    return (fontes_do_paciente(cenario) + definicoes_da_pergunta(pergunta, cenario)
            + [(t["id"], t["texto"]) for t in buscar_base(pergunta, base)])


_CODIGOS = re.compile(r"\s*\[(?:[ABEGP]\d*(?:-\d+)?)(?:\s*,\s*[ABEGP]\d*(?:-\d+)?)*\]")


def remover_codigos(texto):
    """Tira os códigos de fonte ([A], [P1], [E1], [G2], [B13-2]) do texto que o paciente lê."""
    return _CODIGOS.sub("", texto or "")


def escrever_resposta(pergunta, fontes):
    msg = "FONTES:\n" + "\n".join(f"[{cod}] {txt}" for cod, txt in fontes) + "\n\nPERGUNTA DO PACIENTE:\n" + pergunta
    bruto, _ = n.chamar_interna(os.environ.get("LLM_MODEL", ""), n.ler_prompt("respondedor_sistema.txt"), msg,
                                force_json=True)
    dados = _json(bruto) or {"sem_apoio": True}
    if dados.get("sem_apoio") or not dados.get("resposta"):
        return None, []
    return dados["resposta"].strip(), dados.get("fontes", [])


def verificar_resposta(pergunta, resposta, fontes):
    """Camada 4 no chatbot: cada frase tem apoio nas fontes? E a resposta RESPONDE à pergunta?
    (Uma frase verdadeira mas fora do assunto pode soar como tranquilização indevida: caso #15.)
    Devolve (sem_apoio, responde) ou (None, False) se o verificador falhar."""
    frases = [f for f in re.split(r"(?<=[.!?])\s+", re.sub(r"\s*\[[^\]]+\]", "", resposta)) if f.strip()]
    msg = ("FONTES:\n" + "\n".join(f"[{c}] {t}" for c, t in fontes) + "\n\nPERGUNTA DO PACIENTE:\n" + pergunta
           + "\n\nFRASES:\n" + "\n".join(f"{k}. {f}" for k, f in enumerate(frases, 1))
           + "\n\nAlém do campo \"frases\", inclua no JSON o campo \"responde\": \"sim\" se as frases, juntas, "
             "respondem diretamente à PERGUNTA DO PACIENTE, ou \"nao\" se falam de outra coisa ou desviam.")
    bruto, _ = n.chamar_interna(os.environ.get("LLM_MODEL", ""), n.ler_prompt("verificador_sistema.txt"), msg,
                                force_json=True)
    dados = _json(bruto)
    if not dados:
        return None, False  # verificador falhou: falha segura (quem chama manda para c)
    julg = {int(x["n"]): x for x in dados.get("frases", []) if str(x.get("n", "")).isdigit()}
    # frase copiada literalmente de uma fonte tem apoio por definição (o verificador de 12B às vezes reprova)
    textos = [normalizar(tx) for _, tx in fontes]
    literal = lambda f: any(normalizar(f).strip(" .") in tx for tx in textos)  # noqa: E731
    sem_apoio = [{"frase": f, "motivo": julg[k].get("motivo", "")} for k, f in enumerate(frases, 1)
                 if k in julg and str(julg[k].get("apoio", "")).lower().startswith("n") and not literal(f)]
    return sem_apoio, str(dados.get("responde", "nao")).lower().startswith("s")


def para_fila(pergunta, cenario, cls, rascunho, fontes, motivo_c, arquivo=os.path.join(n.AQUI, "fila", "fila.jsonl")):
    item = {"criado_em": datetime.now().isoformat(timespec="seconds"), "cenario": cenario["id"],
            "pergunta": pergunta, "tipo": cls["tipo"], "destino_sugerido": cls.get("destino") or "enfermagem",
            "prioridade": cls.get("prioridade", "normal"), "motivo": motivo_c, "rascunho": rascunho,
            "fontes": fontes, "status": "aguardando_triagem", "destino_final": None}
    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def atender(pergunta, cenario, base, pausa=3.0, gravar_fila=True, fila_fn=None):
    """fila_fn: função que grava o item da fila (o serviço web grava no banco); padrão: fila/fila.jsonl."""
    gravar = fila_fn or para_fila
    cls = classificar(pergunta, cenario)
    chamadas = cls["chamadas_llm"]
    out = {"pergunta": pergunta, "classificacao": cls, "tipo_final": cls["tipo"], "resposta": None,
           "mensagem_ao_paciente": None, "fontes": [], "fila": None, "observacoes": []}

    def esperar():
        if chamadas:
            time.sleep(pausa)  # uma chamada por vez, com intervalo

    tipo = cls["tipo"]
    if tipo in "ab" and not cenario.get("duvidas_liberadas", True):
        tipo, motivo_c = "c", "dúvidas não liberadas pelo revisor para este exame"
        out["observacoes"].append(motivo_c)

    if tipo == "d":
        msg = MSG_URGENCIA + (" " + MSG_CVV if _CVV.search(normalizar(pergunta)) else "")
        out.update(tipo_final="d", mensagem_ao_paciente=msg)
        if gravar_fila:
            out["fila"] = gravar(pergunta, cenario, cls, None, [], "ALERTA IMEDIATO À EQUIPE")
    elif tipo == "e":
        recusa = cls.get("destino") == "recusa"
        out.update(tipo_final="e", mensagem_ao_paciente=MSG_RECUSA if recusa else MSG_RECEPCAO)
        if gravar_fila:
            out["fila"] = gravar(pergunta, cenario, cls, None, [], "recusa registrada" if recusa else "recepção")
    else:
        if tipo in "ab":
            # D2: o conteúdo aprovado DESTE paciente (consulta direta) + trechos da base (RAG), juntos.
            # O modelo usa a fonte pertinente; a confusão a×b do classificador não afeta a resposta.
            fontes = todas_as_fontes(pergunta, cenario, base)
            aceita, motivo_c = False, "as fontes não respondem"
            esperar(); resposta, citadas = escrever_resposta(pergunta, fontes); chamadas += 1
            if resposta is not None:
                if n._CAUSA.search(normalizar(resposta)) or n._PROGNOSTICO.search(normalizar(resposta)):
                    motivo_c = "resposta cita causa ou prognóstico"
                else:
                    esperar(); sem_apoio, responde = verificar_resposta(pergunta, resposta, fontes); chamadas += 1
                    if sem_apoio is None:
                        motivo_c = "verificador falhou"
                    elif sem_apoio:
                        motivo_c = "verificação de apoio reprovou"
                        out["observacoes"].append({"sem_apoio": sem_apoio})
                    elif not responde:
                        motivo_c = "a resposta não responde à pergunta"
                    else:
                        aceita = True
                        # a: usou o conteúdo do próprio paciente (A, P, E); b: só base da clínica ou glossário (B, G)
                        do_paciente = any(str(f).startswith(("A", "P", "E")) for f in citadas)
                        tipo = "a" if do_paciente or not citadas else "b"
                        out.update(tipo_final=tipo, resposta=resposta, fontes=citadas, mensagem_ao_paciente=resposta)
            if not aceita and resposta is None and _LOGISTICA.search(normalizar(pergunta)):
                tipo = "e"  # logística que a base não cobre: recepção (decisão de 14/11)
                out["observacoes"].append(f"{cls['tipo']} → e: logística fora da base → recepção")
                out.update(tipo_final="e", mensagem_ao_paciente=MSG_RECEPCAO)
                if gravar_fila:
                    out["fila"] = gravar(pergunta, cenario, {**cls, "destino": "recepcao"}, None, [], "recepção")
            elif not aceita:
                tipo = "c"
            if tipo == "c":
                out["observacoes"].append(f"{cls['tipo']} → c: {motivo_c}")
                cls = {**cls, "destino": cls.get("destino") if cls.get("destino") in ("medico", "enfermagem")
                       else "enfermagem"}
                out.update(tipo_final="c", mensagem_ao_paciente=MSG_ENCAMINHADO)
                if gravar_fila:
                    out["fila"] = gravar(pergunta, cenario, cls, resposta, citadas, motivo_c)
        else:  # c desde a classificação: rascunho para a equipe, com todas as fontes
            fontes = todas_as_fontes(pergunta, cenario, base)
            esperar(); rascunho, citadas = escrever_resposta(pergunta, fontes); chamadas += 1
            alta = cls.get("prioridade") == "alta"
            out.update(tipo_final="c", mensagem_ao_paciente=MSG_ACOLHIMENTO if alta else MSG_ENCAMINHADO)
            if gravar_fila:
                out["fila"] = gravar(pergunta, cenario, cls, rascunho, citadas,
                                        "classificada como c" + (" (prioridade: acolhimento)" if alta else ""))
    out["chamadas_llm"] = chamadas
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pergunta")
    ap.add_argument("--cenario", default=os.path.join(n.AQUI, "duvidas", "cenario_C01.json"))
    ap.add_argument("--pausa", type=float, default=3.0)
    args = ap.parse_args()
    n.carregar_env()
    with open(args.cenario, encoding="utf-8") as f:
        cenario = json.load(f)
    r = atender(args.pergunta, cenario, carregar_base(), pausa=args.pausa)
    print(json.dumps({k: v for k, v in r.items() if k != "fila"}, ensure_ascii=False, indent=2))
    if r["fila"]:
        print(f"\n→ fila: destino sugerido {r['fila']['destino_sugerido']}, prioridade {r['fila']['prioridade']}")


if __name__ == "__main__":
    main()
