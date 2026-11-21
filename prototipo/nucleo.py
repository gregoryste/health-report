"""Peças compartilhadas da pista do laudo: chamada à LLM, montagem da mensagem, frases fixas e checagens.

Usado por tradutor.py (gera os rascunhos) e compara.py (compara modelos).
"""
import glob
import json
import os
import re
import urllib.error
import urllib.request

from regra import normalizar

AQUI = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- LLM

def carregar_env(caminho=os.path.join(AQUI, ".env")):
    """Lê KEY=VALOR do .env (aceita comentário no fim da linha). Não sobrescreve o ambiente."""
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            valor = re.split(r"\s+#", valor, maxsplit=1)[0].strip().strip('"').strip("'")
            os.environ.setdefault(chave.strip(), valor)


def resposta_fixa(sistema, mensagem):
    """LLM_FIXA=1 (SÓ PARA TESTE, padrão desligado): devolve respostas fixas no formato de cada tarefa, sem chamar a
    LLM. O resto da pista (regra fixa, checagens, classificação final, roteamento) roda de verdade.
      tradutor     explicação + 3 dúvidas genéricas (as checagens podem acusar omissão: é esperado)
      classificador tipo pela palavra na mensagem: "consulta" → c; "recepção"/"horário"/"agendar" → e; senão → a
                    (sinais de alarme nem chegam aqui: a lista de alarme decide d antes, sem LLM)
      respondedor  uma frase citando a 1ª fonte recebida
      verificador  todas as frases com apoio e "responde: sim"
      estruturador {} (leitura de foto não é testada assim)"""
    def eh(nome):
        try:
            return sistema == ler_prompt(nome)
        except OSError:
            return False
    if eh("classificador_sistema.txt"):
        texto = normalizar(mensagem.rsplit("Mensagem do paciente:", 1)[-1])
        tipo = "c" if "consulta" in texto else ("e" if re.search(r"recepcao|horario|agendar", texto) else "a")
        destino = {"c": "medico", "e": "recepcao", "a": ""}[tipo]
        return json.dumps({"tipo": tipo, "destino": destino, "prioridade": "normal", "motivo": "LLM_FIXA"})
    if eh("respondedor_sistema.txt"):
        cod = (re.findall(r"^\[([^\]]+)\]", mensagem, flags=re.M) or ["A"])[0]
        return json.dumps({"resposta": f"Resposta fixa de teste sobre o seu exame. [{cod}]", "fontes": [cod],
                           "sem_apoio": False})
    if eh("verificador_sistema.txt"):
        frases = mensagem.split("FRASES:", 1)[-1]
        ns = re.findall(r"^\s*(\d+)\.", frases, flags=re.M)
        return json.dumps({"frases": [{"n": int(k), "apoio": "sim", "motivo": ""} for k in ns], "responde": "sim"})
    if eh("estruturador_sistema.txt"):
        return "{}"
    return ("EXPLICAÇÃO:\nTexto fixo de teste (LLM_FIXA): este rascunho não foi escrito pela LLM.\n\n"
            "DÚVIDAS:\nP: O que é este exame?\nR: Resposta fixa de teste.\n"
            "P: Quando falo com o médico?\nR: Resposta fixa de teste.\n"
            "P: Preciso fazer algo agora?\nR: Resposta fixa de teste.")


def chamar_interna(modelo, sistema, mensagem, temperatura=0.0, force_json=False):
    """LLM interna (D11): recebe prompt + system_prompt e devolve {"response", "model"}.
    Temperatura 0 (camada 3): saída mais previsível e reprodutível na avaliação.
    Devolve (texto, modelo_servido). Com LLM_FIXA=1 (só teste) não chama a LLM: ver resposta_fixa()."""
    if os.environ.get("LLM_FIXA") == "1":
        return resposta_fixa(sistema, mensagem), "LLM_FIXA"
    url =os.environ["LLM_BASE_URL"].rstrip("/") + os.environ.get("LLM_API", "")
    corpo = {"prompt": mensagem, "system_prompt": sistema, "model": modelo,
             "temperature": temperatura, "force_json": force_json}
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["LLM_TOKEN"]})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM interna HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}") from e
    return resp["response"], resp.get("model")


def ler_prompt(nome="tradutor_sistema.txt"):
    with open(os.path.join(AQUI, "prompts", nome), encoding="utf-8") as f:
        return f.read()

# ---------------------------------------------------------------- mensagem para o modelo

def num_br(v):
    """6.8 -> '6,8'; 12800 -> '12.800' (o paciente lê no formato brasileiro)."""
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(v):,}".replace(",", ".")


def faixa_br(faixa):
    return re.sub(r"(\d)\.(\d)", r"\1,\2", faixa)


INSTRUCAO_IMAGEM = (
    "Instruções para este laudo de imagem: cite cada achado alterado, com o local e o tamanho quando o laudo "
    "informar, e traduza os termos técnicos. Estruturas normais: diga só que estão normais, sem repetir medidas, "
    "dimensões ou volumes.")
INSTRUCAO_ESCORE = (
    "Este laudo traz um escore ou classificação. Na explicação e nas dúvidas, não escreva o nome nem o número "
    "dele, não diga o que significa nem se o risco é alto ou baixo. Não escreva nada sobre ela na explicação: "
    "o sistema acrescenta uma frase sobre isso.")
_ESCORE_NO_LAUDO = re.compile(r"(?i)\b(ti|bi|li|pi|lung|o)-?rads\b|\bbosniak\b|\bfleischner\b|\bgrau [i\d]")

# Camada 3: tom pela PRIORIDADE (calculada pela regra fixa, existe em produção).
# Não usar a "categoria" do laudo: é rótulo do conjunto de teste, seria dar o gabarito ao sistema.
TOM = {
    "normal": "Tom: todos os itens estão dentro da faixa. Diga isso com clareza, sem falar de doenças.",
    "alterado": ("Tom: há itens fora da faixa. Descreva-os com clareza e calma, sem esconder. Não suponha "
                 "problemas, doenças ou causas que o laudo não mostra."),
    "critico": ("Tom: há um resultado crítico. Seja claro e sério, sem alarmar e sem descrever consequências "
                "para a saúde."),
}

# ---------------------------------------------------------------- camada 1: glossário controlado

def carregar_glossario(caminho=os.path.join(AQUI, "glossario", "glossario.json")):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)["termos"]


def termos_do_laudo(laudo, avaliacao, glossario):
    """Busca no glossário só os termos que aparecem neste laudo (RAG numa base curada, sem dado pessoal: D2)."""
    base = normalizar(" ".join([laudo["exame"], laudo.get("texto", "")] + [i["analito"] for i in avaliacao["itens"]]))
    achados = []
    for t in glossario:
        if t.get("requer") and not re.search(r"\b" + re.escape(normalizar(t["requer"])), base):
            continue
        if any(re.search(r"\b" + re.escape(normalizar(p)), base) for p in t["padroes"]):
            achados.append(t)
    return achados


def montar_mensagem(laudo, avaliacao, exemplo=None, definicoes=None):
    """Mensagem do usuário. O gabarito nunca entra aqui."""
    sexo = {"M": "masculino", "F": "feminino"}.get(laudo.get("sexo"), "não informado")
    linhas = [f"Exame: {laudo['exame']}. Paciente: sexo {sexo}, {laudo.get('idade', '?')} anos."]
    if avaliacao["tipo"] == "imagem":
        linhas.append("Tipo: laudo de imagem (texto livre).")
        if avaliacao["prioridade"] == "critico":
            linhas.append("O laudista marcou ACHADO CRÍTICO.")
        linhas.append(INSTRUCAO_IMAGEM)
        if tem_escore(laudo):
            linhas.append(INSTRUCAO_ESCORE)
        linhas += ["Texto do laudo:", laudo["texto"]]
    else:
        linhas.append("Resultados:")
        for i in avaliacao["itens"]:
            if i["nivel"] == "normal":
                marca = "NORMAL"
            else:
                lado = "ACIMA" if i["direcao"] == "alto" else "ABAIXO"
                marca = f"{lado} da faixa, {'CRÍTICO' if i['nivel'] == 'critico' else 'ALTERADO'}"
            linhas.append(f"- {i['analito']}: {num_br(i['valor'])} {i['unidade']} "
                          f"(referência {faixa_br(i['faixa'])}) → {marca}")
    linhas.append(TOM[avaliacao["prioridade"]])
    if definicoes:
        linhas += ["", "DEFINIÇÕES APROVADAS (use estas definições para explicar estes termos, com as mesmas ideias; "
                       "não explique estes termos de outro jeito):"]
        linhas += [f"- {t['termo']}: {t['definicao']}" for t in definicoes]
    if exemplo:
        linhas += ["",
                   "Exemplo de explicação já aprovada por um profissional, para um caso parecido de OUTRO paciente. "
                   "Use como referência de tom, estrutura e nível de linguagem. Não copie dados dele.",
                   "<<<", exemplo["explicacao"], ">>>"]
    return "\n".join(linhas)


def tem_escore(laudo):
    return bool(_ESCORE_NO_LAUDO.search(laudo.get("texto", "")))


def texto_do_laudo(laudo, avaliacao):
    """Texto do laudo original, para medir a legibilidade 'antes'."""
    if avaliacao["tipo"] == "imagem":
        return laudo["texto"]
    return " ".join(f"{i['analito']} {num_br(i['valor'])} {i['unidade']}, referência {faixa_br(i['faixa'])}."
                    for i in avaliacao["itens"])

# ---------------------------------------------------------------- E1: exemplos aprovados

def carregar_exemplos(pasta=os.path.join(AQUI, "exemplos_aprovados")):
    exemplos = []
    for caminho in sorted(glob.glob(os.path.join(pasta, "*.json"))):
        with open(caminho, encoding="utf-8") as f:
            exemplos.append(json.load(f))
    return exemplos


def buscar_exemplo(laudo, avaliacao, exemplos):
    """E1: escolhe o exemplo aprovado mais parecido (mesmo tipo obrigatório; prioridade e palavras-chave somam).
    Busca por tipo de exame e achado, só em exemplos anonimizados (D2). Não usa a 'categoria' (rótulo de teste)."""
    contexto = normalizar(" ".join([laudo["exame"], laudo.get("texto", "")]
                                   + [i["analito"] for i in avaliacao["itens"]]))
    melhor, nota_melhor = None, 0
    for ex in exemplos:
        if ex["tipo"] != avaliacao["tipo"]:
            continue
        palavras = sum(1 for p in ex.get("palavras_chave", []) if normalizar(p) in contexto)
        if palavras < 2:  # precisa ser parecido de verdade (exame/achado); prioridade só desempata
            continue
        nota = palavras + (0.5 if ex.get("prioridade") == avaliacao["prioridade"] else 0)
        if nota > nota_melhor:
            melhor, nota_melhor = ex, nota
    return melhor

# ---------------------------------------------------------------- resposta do modelo

def separar(texto):
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()
    partes = re.split(r"\n\s*\**\s*D[ÚU]VIDAS\s*:?\**", texto, maxsplit=1, flags=re.I)
    explicacao = re.sub(r"^\s*\**\s*EXPLICA[ÇC][ÃA]O\s*:?\**", "", partes[0], flags=re.I).strip()
    duvidas = partes[1].strip() if len(partes) > 1 else ""
    # se o modelo repetiu a resposta, descarta a partir da segunda "EXPLICAÇÃO:"
    duvidas = re.split(r"\n\s*\**\s*EXPLICA[ÇC][ÃA]O\s*:?", duvidas, maxsplit=1, flags=re.I)[0].strip()
    return explicacao, duvidas


def repetida(texto):
    return len(re.findall(r"EXPLICA[ÇC][ÃA]O\s*:", texto, flags=re.I)) > 1


def lista_duvidas(bloco):
    """'P: ... R: ...' -> [{"pergunta", "resposta"}]. Linhas soltas fora dos pares são ignoradas."""
    pares = re.findall(r"^\s*\**P\s*[:.)]\**\s*(.+?)\s*\n\s*\**R\s*[:.)]\**\s*(.+?)\s*$", bloco, flags=re.M)
    return [{"pergunta": p.strip(), "resposta": r.strip()} for p, r in pares]

# ---------------------------------------------------------------- frases fixas (D4/D13: o código garante)

FECHO = "Converse com o seu médico sobre estes resultados."
ESCORE_FIXO = "O laudo também traz uma classificação, que o médico vai explicar na consulta."
CONTATO_CRITICO = ("Há um resultado que precisa de atenção rápida. "
                   "A equipe da clínica vai entrar em contato com você ainda hoje.")
_FRASE_CONTATO = re.compile(r"entr\w*\s+em\s+contato", re.I)
_FRASE_ESCORE = re.compile(r"(traz|tem|apresenta|possui|inclui)\s+(tambem\s+)?uma\s+classifica|classifica\w*\s+que\s+o\s+medico", re.I)
_FRASE_FECHO = re.compile(r"\b(converse|conversar|fale|falar|procure|procurar|consulte)\b[^.!?]*\bm[ée]dic", re.I)


def finalizar_explicacao(explicacao, avaliacao, com_escore=False):
    """Tira do texto do modelo os avisos de contato e as frases de fecho, e acrescenta as frases fixas.
    Devolve (texto_final, frases_removidas, frases_fixas)."""
    removidas, paragrafos = [], []
    for par in re.split(r"\n\s*\n", explicacao.strip()):
        manter = []
        for frase in re.split(r"(?<=[.!?])\s+", par.strip()):
            sem_acento = normalizar(frase)
            if frase and (_FRASE_CONTATO.search(frase) or _FRASE_FECHO.search(frase)
                          or (com_escore and _FRASE_ESCORE.search(sem_acento))):
                removidas.append(frase)
            elif frase:
                manter.append(frase)
        if manter:
            paragrafos.append(" ".join(manter))
    fixas = (([ESCORE_FIXO] if com_escore else []) + ([CONTATO_CRITICO] if avaliacao["prioridade"] == "critico" else [])
             + [FECHO])
    return "\n\n".join(paragrafos + fixas), removidas, fixas

# ---------------------------------------------------------------- checagens

SUAVIZACAO = ["nada grave", "nao se preocupe", "esta tudo bem", "tudo normal", "nao e motivo de preocupacao",
              "tranquil", "sem importancia"]
ESCORES = r"(ti-?rads|bi-?rads|bosniak|lung-?rads|pi-?rads|li-?rads)"


def suavizacao(explicacao, avaliacao):
    if avaliacao["prioridade"] == "normal":
        return []
    texto = normalizar(explicacao)
    return [s for s in SUAVIZACAO if s in texto]


_ESC = r"(?:\bACR\s+)?\b(?:(?:TI|BI|LI|PI|O|Lung)-?RADS|Bosniak)(?:[\s®]*(?:\d+[A-Za-z]?|[IVX]+F?)\b)?"
_SUBST_ESCORE = [
    # "(TI-RADS 4)" entre parênteses: some
    (re.compile(r"\s*\(\s*" + _ESC + r"\s*\)", re.I), ""),
    # "cisto, chamado Bosniak I, tem" -> "cisto tem"; "cisto chamado Bosniak I" -> "cisto"
    (re.compile(r",\s*(?:chamad|denominad|conhecid)[oa]s?\s+(?:como\s+|de\s+)?" + _ESC + r"\s*,", re.I), ""),
    (re.compile(r"\s*,?\s*(?:chamad|denominad|conhecid)[oa]s?\s+(?:como\s+|de\s+)?" + _ESC, re.I), ""),
    # "classificada como Bosniak IIF" -> "com uma classificação"
    (re.compile(r"\bclassificad[oa]s?\s+como\s+" + _ESC, re.I), "com uma classificação"),
    # "uma classificação (chamada) ACR TI-RADS 4" -> "uma classificação"
    (re.compile(r"\b(uma|a)\s+classifica[çc][ãa]o\s+(?:chamada\s+|de\s+|do tipo\s+)?" + _ESC, re.I), r"\1 classificação"),
    # artigo + escore
    (re.compile(r"\b([Oo]|[Aa])\s+" + _ESC, re.I), lambda m: ("A" if m.group(1).isupper() else "a") + " classificação do laudo"),
    (re.compile(r"\b(d|n)[oa]\s+" + _ESC, re.I), lambda m: m.group(1) + "a classificação do laudo"),
    # escore solto
    (re.compile(_ESC, re.I), "a classificação do laudo"),
]


def ocultar_escores(texto):
    """Regra de produto (D5): nenhum escore na tela do paciente. Troca o nome do escore por
    'a classificação do laudo'. Devolve (texto, trechos_trocados)."""
    trocados = [m.group(0) for m in re.finditer(_ESC, texto, flags=re.I)]
    for padrao, troca in _SUBST_ESCORE:
        texto = padrao.sub(troca, texto)
    # concordância: "a classificação do laudo será explicado" -> "explicada"
    texto = re.sub(r"(classificação do laudo (?:será|foi|é|está|vai ser) \w+?)o\b", r"\1a", texto)
    return texto, trocados


def ocultar_escores_rascunho(explicacao, duvidas):
    explicacao, trocados = ocultar_escores(explicacao)
    saida = []
    for d in duvidas:
        p, t1 = ocultar_escores(d["pergunta"])
        r, t2 = ocultar_escores(d["resposta"])
        trocados += t1 + t2
        saida.append({**d, "pergunta": p, "resposta": r})
    return explicacao, saida, trocados


_CAUSA = re.compile(r"pode(m)? indicar|pode(m)? ser causad|causas? (possive|comu)|pode(m)? ser sinal"
                    r"|pode(m)? ter (varias |muitas |diversas )?causas"
                    r"|pode(m)? ser (por|devido|de um|de uma|consequencia|resultado)"
                    r"|(quando|se) (ha|houver|existe|existir) (um |algum |uma |alguma )?(problema|doenca|alteracao)"
                    r"|identificar o problema|problema (no|na|nos|nas) ")
_PROGNOSTICO = re.compile(r"benign|malign|cancer|tumor|\bgrave\b|perigos")
RESPOSTA_CAUSA = "O motivo desse resultado será avaliado pelo médico na consulta."


def proteger_duvidas(duvidas):
    """D4/D13: o modelo insiste em citar causas e prognóstico nas dúvidas. Resposta que cita causa ou fala de
    prognóstico (benigno, maligno, grave...) vira a resposta fixa. Devolve (duvidas, trocadas)."""
    saida, trocadas = [], []
    for d in duvidas:
        resp = normalizar(d["resposta"])
        if _CAUSA.search(resp) or (_PROGNOSTICO.search(resp) and "medico" not in resp):
            trocadas.append(dict(d))
            d = {**d, "resposta": RESPOSTA_CAUSA}
        saida.append(d)
    return saida, trocadas


def alertas(explicacao, duvidas, avaliacao, laudo=None):
    """Heurísticos: apontam o que o revisor deve ler com atenção. Não substituem a conferência."""
    tudo = normalizar(explicacao + " " + duvidas)
    lista = []
    if laudo is not None and not tem_escore(laudo) and re.search(r"classifica", tudo):
        lista.append("cita classificação que o laudo não tem")
    if avaliacao["prioridade"] != "critico" and re.search(r"entr\w* em contato", tudo):
        lista.append("promete contato")
    for frase in re.split(r"(?<=[.!?\n])", tudo):
        if frase.strip().endswith("?"):
            continue  # pergunta do paciente ("o que significa ...?") não é interpretação
        menciona = re.search(ESCORES, frase) or "classificacao do laudo" in frase
        if menciona and re.search(r"risco|signific|benign|malign|cancer|acompanha", frase):
            lista.append("interpreta escore")
            break
    # causa e prognóstico só em frase afirmativa (a pergunta do paciente "é grave?" não conta)
    afirmativas = [f for f in re.split(r"(?<=[.!?\n])", tudo) if not f.strip().endswith("?")]
    if any(_CAUSA.search(f) for f in afirmativas):
        lista.append("cita causa")
    if any(_PROGNOSTICO.search(f) and "medico" not in f for f in afirmativas):
        lista.append("fala de prognóstico")
    return lista


def _ler_lista(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def carregar_jargao(pasta=os.path.join(AQUI, "jargao")):
    return {"proibidos": _ler_lista(os.path.join(pasta, "proibidos.txt")),
            "permitidos": _ler_lista(os.path.join(pasta, "permitidos_se_explicados.txt"))}


def _padrao(termo):
    if termo.startswith("re:"):
        return re.compile(termo[3:].split("::", 1)[-1])
    return re.compile(r"\b" + re.escape(normalizar(termo)) + r"\w*")


def _rotulo(termo):
    """'re:código CID::regex' -> 'código CID'; termo comum fica igual."""
    return termo[3:].split("::", 1)[0] if termo.startswith("re:") else termo


def checar_jargao(texto, listas):
    """Proibidos: não podem aparecer. Permitidos: na primeira vez que aparecem, precisam de explicação ao lado
    (parênteses, 'que ...', aposto ', as células ...', ':') ou vir entre parênteses depois da explicação.
    Heurístico: ' é ' não entra porque, sem acento, não se distingue de ' e '."""
    norm = normalizar(texto)
    proibidos = []
    for t in listas["proibidos"]:
        alvo = texto if t.startswith("re:") else norm  # regex roda no texto original (maiúsculas, pontos)
        if _padrao(t).search(alvo):
            proibidos.append(_rotulo(t))
    sem_explicacao = []
    for t in listas["permitidos"]:
        m = _padrao(t).search(norm)
        if not m:
            continue
        depois, antes = norm[m.end():m.end() + 60], norm[max(0, m.start() - 2):m.start()]
        explicado = ("(" in antes or re.match(r"\s*(\w+\s+){0,2}\(", depois)  # "nodulo solido (..."
                     or re.match(r"\s*, (o|a|os|as|um|uma) ", depois)
                     or re.search(r"^[^.!?]*?(, que | que | sao |: )", depois))
        if not explicado:
            sem_explicacao.append(t)
    return {"proibidos": proibidos, "sem_explicacao": sem_explicacao}

# ---------------------------------------------------------------- legibilidade

def silabas(palavra):
    return max(1, len(re.findall(r"[aeiouáéíóúâêôãõàü]+", palavra.lower())))


def flesch_pt(texto):
    """Flesch adaptado ao português (Martins et al., 1996). Quanto maior, mais fácil."""
    frases = [f for f in re.split(r"[.!?]+", texto) if f.strip()]
    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", texto)
    if not frases or not palavras:
        return None
    return round(248.835 - 1.015 * (len(palavras) / len(frases))
                 - 84.6 * (sum(silabas(p) for p in palavras) / len(palavras)), 1)

# ---------------------------------------------------------------- camada 2: checagens determinísticas

_NUM_MILHAR = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_NUM = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


def _valor(s):
    s = s.replace(".", "").replace(",", ".") if _NUM_MILHAR.fullmatch(s) else s.replace(",", ".")
    return float(s)


def numeros(texto):
    return {_valor(m) for m in _NUM.findall(texto)}


def checar_numeros(texto_paciente, laudo, avaliacao, definicoes=()):
    """Todo número que vai ao paciente precisa existir no laudo (valores, faixas, medidas) ou numa definição usada.
    Pega número inventado, trocado ou copiado do exemplo E1."""
    permitidos = numeros(texto_do_laudo(laudo, avaliacao)) | numeros(laudo.get("texto", ""))
    for i in avaliacao["itens"]:
        permitidos.add(float(i["valor"]))
    for t in definicoes:
        permitidos |= numeros(t["definicao"])
    return sorted(v for v in numeros(texto_paciente) if not any(abs(v - p) < 1e-6 for p in permitidos))


POSICOES = ["direit", "esquerd", "superior", "inferior", "anterior", "posterior", "proximal", "distal",
            "medial", "lateral"]


def checar_posicao(texto_paciente, laudo):
    """Laudo de imagem: lado/posição que o laudo não usa, e 'distal' traduzido como 'distante/longe' (caso L90)."""
    if laudo.get("tipo") != "imagem":
        return []
    lt, tp = normalizar(laudo.get("exame", "") + " " + laudo["texto"]), normalizar(texto_paciente)  # "abdome superior"
    problemas = [f"'{p}...' não aparece no laudo" for p in POSICOES
                 if re.search(r"\b" + p, tp) and not re.search(r"\b" + p, lt)]
    if re.search(r"\bdistal", lt) and re.search(r"\bdistante|\blonge d", tp):
        problemas.append("'distal' traduzido como distante/longe (no ureter, distal = perto da bexiga)")
    return problemas

# ---------------------------------------------------------------- camada 4: verificação de apoio pela LLM

def _frases(texto):
    return [f.strip() for par in re.split(r"\n\s*\n", texto) for f in re.split(r"(?<=[.!?])\s+", par) if f.strip()]


def frases_para_verificar(explicacao, duvidas):
    """Frases escritas pelo modelo (as fixas e as respostas padrão não precisam de verificação)."""
    fixas = {FECHO, RESPOSTA_CAUSA, ESCORE_FIXO} | set(_frases(CONTATO_CRITICO))
    itens = [("explicação", f) for f in _frases(explicacao) if f not in fixas]
    for d in duvidas:
        if d["resposta"] != RESPOSTA_CAUSA and "avaliado pelo medico" not in normalizar(d["resposta"]):
            itens.append((f"dúvida: {d['pergunta']}", d["resposta"]))
    return itens


def verificar_apoio(laudo, avaliacao, explicacao, duvidas, definicoes):
    """Segunda chamada à LLM: cada frase tem apoio no laudo ou nas definições aprovadas?
    Devolve {"verificado", "sem_apoio": [{"onde", "frase", "motivo"}], "resposta_bruta"}."""
    itens = frases_para_verificar(explicacao, duvidas)
    if not itens:
        return {"verificado": True, "sem_apoio": [], "resposta_bruta": ""}
    msg = ["LAUDO:", texto_do_laudo(laudo, avaliacao)]
    if definicoes:
        msg += ["", "DEFINIÇÕES APROVADAS:"] + [f"- {t['termo']}: {t['definicao']}" for t in definicoes]
    msg += ["", "FRASES:"] + [f"{k}. {f}" for k, (_, f) in enumerate(itens, 1)]
    bruto, _ = chamar_interna(os.environ.get("LLM_MODEL", ""), ler_prompt("verificador_sistema.txt"),
                              "\n".join(msg), force_json=True)
    try:
        dados = json.loads(re.sub(r"^```(?:json)?|```$", "", bruto.strip(), flags=re.M))
        julg = {int(x["n"]): x for x in dados.get("frases", [])}
    except (ValueError, KeyError, TypeError):
        return {"verificado": False, "sem_apoio": [], "resposta_bruta": bruto, "erro": "JSON inválido do verificador"}
    sem_apoio = [{"onde": onde, "frase": f, "motivo": julg[k].get("motivo", "")}
                 for k, (onde, f) in enumerate(itens, 1)
                 if k in julg and str(julg[k].get("apoio", "")).lower().startswith("n")]
    return {"verificado": True, "sem_apoio": sem_apoio, "resposta_bruta": bruto}


_DIZ_ALTERADO = re.compile(r"\b(alt[oa]s?|acima|elevad\w*|aumentad\w*|baix[oa]s?|abaixo|reduzid\w*|diminuid\w*)\b")
_DIZ_NORMAL = re.compile(r"(?<!acima do )(?<!abaixo do )\bnorma(l|is)\b|dentro d[ao] (faixa|valor|esperado|limite)")
_CLAUSULAS = re.compile(r"[.;!?\n]|,\s*(?:mas|e|enquanto|ja|porem)\s|\s+enquanto\s")


def checar_contradicao(texto_paciente, avaliacao):
    """Camada 2, exame de sangue: o texto não pode chamar de alterado um item que a regra marcou como normal
    (ex.: 'Gama-GT alta' com Gama-GT normal), nem o contrário. Vale também para as perguntas das dúvidas."""
    problemas = []
    for clausula in _CLAUSULAS.split(normalizar(texto_paciente)):
        if not clausula or not clausula.strip():
            continue
        for i in avaliacao["itens"]:
            nomes = [normalizar(i["analito"])] + [normalizar(a) for a in i["apelidos"]]
            if not any(re.search(r"\b" + re.escape(nm) + r"\b", clausula) for nm in nomes):
                continue
            if i["nivel"] == "normal" and _DIZ_ALTERADO.search(clausula):
                problemas.append(f"{i['analito']} está normal, mas o texto diz alterado")
            elif (i["nivel"] != "normal" and _DIZ_NORMAL.search(clausula) and not _DIZ_ALTERADO.search(clausula)
                  and not re.search(r"\bfora d[ao]", clausula)):  # "fora do que é considerado normal" (L19)
                problemas.append(f"{i['analito']} está alterado, mas o texto diz normal")
    return sorted(set(problemas))
