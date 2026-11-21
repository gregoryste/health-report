"""Leitura de laudo enviado pelo paciente (foto ou PDF), etapa 4 / D4: OCR local + LLM interna só em texto.

  1. baixa o arquivo da Meta (Media API) para dados/envios/ — o arquivo não sai do servidor da clínica;
  2. extrai o texto: PDF com camada de texto → pdftotext; PDF escaneado ou foto → tesseract (OCR local),
     com a confiança de cada palavra. Palavra com confiança baixa vira "[ilegível]": número mal lido não segue;
  3. a LLM interna (prompts/estruturador_sistema.txt) só ORGANIZA o texto no formato JSON dos laudos;
  4. o código confere: todo número do JSON (valor e faixa) precisa aparecer no texto lido; o que não aparece é
     descartado e o item fica "ilegível". Nada é completado por adivinhação.
Depois disso o paciente confere os valores (canal_whatsapp), e a explicação passa pela revisão do painel (D6).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

import nucleo as n
from regra import normalizar

from . import banco

PASTA = os.path.join(n.AQUI, "dados", "envios")
CONF_MIN = 60          # confiança mínima do tesseract (0–100) para uma palavra entrar no texto
MIMES = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
# Limites críticos da CLÍNICA (o laudo traz só a faixa de referência). PROVISÓRIOS, mesma convenção do L03 e dos
# laudos do Jackson; a confirmar com o grupo. Chave: começo do nome do item, sem acento.
CRITICOS = {"potassio": (2.8, 6.0), "sodio": (120, 160), "glicose": (40, 400), "glicemia": (40, 400)}


# ---------------------------------------------------------------- 1. arquivo

def baixar_midia(media_id):
    """Media API da Meta: GET /{media_id} devolve a URL; GET na URL (com o token) devolve o arquivo."""
    versao = os.environ.get("WHATSAPP_API_VERSAO", "v25.0")
    cab = {"Authorization": "Bearer " + os.environ["WHATSAPP_TOKEN"]}
    with urllib.request.urlopen(urllib.request.Request(f"https://graph.facebook.com/{versao}/{media_id}",
                                                       headers=cab), timeout=30) as r:
        info = json.load(r)
    with urllib.request.urlopen(urllib.request.Request(info["url"], headers=cab), timeout=60) as r:
        return r.read(), info.get("mime_type", "")


def salvar(envio_id, conteudo, mime):
    os.makedirs(PASTA, exist_ok=True)
    caminho = os.path.join(PASTA, f"{envio_id}.{MIMES.get(mime, 'bin')}")
    with open(caminho, "wb") as f:
        f.write(conteudo)
    return caminho


def apagar(envio_id):
    """Depois da aprovação (minimização): apaga o arquivo e fica só com os valores conferidos."""
    e = banco.um("SELECT arquivo FROM envios WHERE id=?", envio_id)
    if e and e["arquivo"] and os.path.exists(e["arquivo"]):
        os.remove(e["arquivo"])
    banco.executar("UPDATE envios SET arquivo=NULL, atualizado_em=? WHERE id=?", banco.agora(), envio_id)


# ---------------------------------------------------------------- 2. texto

def _idiomas():
    try:
        disp = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return "eng"
    return "por+eng" if "por" in disp else "eng"


def _ocr(imagem):
    """tesseract em TSV: reconstrói as linhas; palavra abaixo de CONF_MIN vira [ilegível]. Devolve (texto, conf média)."""
    tsv = subprocess.run(["tesseract", imagem, "stdout", "-l", _idiomas(), "--psm", "6", "tsv"],
                         capture_output=True, text=True, timeout=120).stdout
    linhas, confs = {}, []
    for l in tsv.splitlines()[1:]:
        c = l.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        conf = float(c[10])
        chave = (int(c[2]), int(c[3]), int(c[4]))  # bloco, parágrafo, linha
        palavra = c[11] if conf >= CONF_MIN else "[ilegível]"
        confs.append(conf)
        linhas.setdefault(chave, []).append(palavra)
    texto = "\n".join(" ".join(p) for _, p in sorted(linhas.items()))
    return texto, (sum(confs) / len(confs) if confs else 0.0)


def extrair_texto(caminho, mime):
    """(texto, confiança 0–100, como_foi_lido)."""
    if mime == "application/pdf":
        texto = subprocess.run(["pdftotext", "-layout", caminho, "-"], capture_output=True, text=True,
                               timeout=60).stdout
        if len(re.sub(r"\s", "", texto)) >= 40:
            return texto, 100.0, "camada de texto do PDF"
        pasta = tempfile.mkdtemp()  # PDF escaneado: vira imagem e passa no OCR
        try:
            subprocess.run(["pdftoppm", "-r", "300", "-png", "-l", "3", caminho, os.path.join(pasta, "p")],
                           capture_output=True, timeout=120)
            partes = [_ocr(os.path.join(pasta, f)) for f in sorted(os.listdir(pasta))]
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
        if not partes:
            return "", 0.0, "OCR"
        return "\n".join(p[0] for p in partes), sum(p[1] for p in partes) / len(partes), "OCR (PDF escaneado)"
    texto, conf = _ocr(caminho)
    return texto, conf, "OCR (foto)"


# ---------------------------------------------------------------- 3 e 4. estrutura e conferência

def _leituras(s):
    """Leituras possíveis de um número escrito. Separador de milhar SÓ vale entre grupos de exatamente 3 dígitos
    ("265.000" ou "265,000"); "6.8" e "6,8" só podem ser 6,8 (avaliação de fotos de 14/11: 6.8 virava 68)."""
    vals = set()
    for dec, mil in ((",", "."), (".", ",")):
        partes = s.split(dec)
        if len(partes) > 2:
            continue
        inteira = partes[0]
        if mil in inteira and not re.fullmatch(r"\d{1,3}(" + re.escape(mil) + r"\d{3})+", inteira):
            continue
        if len(partes) == 2 and mil in partes[1]:
            continue
        try:
            vals.add(round(float(inteira.replace(mil, "") + ("." + partes[1] if len(partes) == 2 else "")), 6))
        except ValueError:
            pass
    return vals


def _numeros(texto):
    """Todos os números do texto, em todas as leituras válidas."""
    vals = set()
    for s in _NUM.findall(texto):
        vals |= _leituras(s)
    return vals


def _num(v):
    """70.0 → 70 (inteiro continua inteiro, como no papel)."""
    v = float(v)
    return int(v) if v.is_integer() else v


def estruturar(texto):
    """LLM interna organiza o texto no formato dos laudos. Só texto: nenhuma imagem sai do servidor (D4)."""
    bruto, _ = n.chamar_interna(os.environ.get("LLM_MODEL", ""), n.ler_prompt("estruturador_sistema.txt"),
                                "TEXTO DO LAUDO:\n" + texto[:6000], force_json=True)
    return json.loads(re.sub(r"^```(?:json)?|```$", "", bruto.strip(), flags=re.M))


PLAUSIVEL = 5  # valor mais de 5x o limite da faixa do laudo: provável erro de leitura (6.8 lido como 68) ou caso grave


def _nome_na_linha(analito, linha):
    """Todas as palavras do nome do item na linha ("colesterol" sozinho não distingue LDL de HDL); com 3 palavras ou
    mais, tolera uma que o OCR errou."""
    palavras = [w for w in re.findall(r"[a-z0-9]+", normalizar(analito)) if len(w) >= 3]
    if not palavras:
        return False
    nl = normalizar(linha)
    acertos = sum(1 for w in palavras if re.search(r"\b" + re.escape(w), nl))
    return acertos >= (len(palavras) if len(palavras) <= 2 else len(palavras) - 1)


def _linha_do_item(analito, valor, texto):
    for linha in texto.splitlines():
        if _nome_na_linha(analito, linha) and round(float(valor), 6) in _numeros(linha):
            return linha
    return None


def faixa_coerente(item, linha):
    """A faixa da LLM bate com as palavras da linha? "até 130" só pode ser ref_max; "a partir de 40", só ref_min."""
    nl = normalizar(linha or "")
    so_max = re.search(r"\bate\b|<|≤|\bmax", nl)
    so_min = re.search(r"\ba partir de\b|>|≥|\bacima de\b|\bmin", nl)
    lo, hi = item.get("ref_min"), item.get("ref_max")
    if lo is not None and hi is None and so_max and not so_min:
        return False
    if hi is not None and lo is None and so_min and not so_max:
        return False
    return True


def plausivel(item):
    """Valor dentro de 5x a faixa do próprio laudo. Fora disso, nada de resumo automático: a equipe confere."""
    v, lo, hi = item["valor"], item.get("ref_min"), item.get("ref_max")
    if hi is not None and hi > 0 and v > hi * PLAUSIVEL:
        return False
    if lo is not None and lo > 0 and v < lo / PLAUSIVEL:
        return False
    return True


def _mesma_linha(analito, valor, texto):
    """O nome do item e o valor aparecem na mesma linha do texto lido? Evita a LLM trocar o valor de dois itens
    (sem a conferência do paciente, é a checagem que segura esse erro)."""
    return _linha_do_item(analito, valor, texto) is not None


def conferir(laudo, texto):
    """Mantém só os números que existem no texto lido E estão na mesma linha do nome do item.
    Devolve (laudo, itens_ilegiveis)."""
    presentes = _numeros(texto)
    ok = lambda v: v is None or round(float(v), 6) in presentes  # noqa: E731
    itens, ilegiveis = [], []
    for i in laudo.get("itens") or []:
        try:
            valor_ok = (i.get("valor") is not None and ok(i["valor"])
                        and _mesma_linha(str(i.get("analito") or ""), i["valor"], texto))
        except (TypeError, ValueError):
            valor_ok = False
        if not valor_ok or not i.get("analito"):
            ilegiveis.append(i.get("analito") or "item sem nome")
            continue
        item = {"analito": str(i["analito"]).strip(), "valor": _num(i["valor"]), "unidade": str(i.get("unidade") or "").strip(),
                "apelidos": [normalizar(str(i["analito"]))]}
        for chave, (cmin, cmax) in CRITICOS.items():
            if normalizar(item["analito"]).startswith(chave):
                item["critico_min"], item["critico_max"] = cmin, cmax
        for k in ("ref_min", "ref_max"):
            try:
                if i.get(k) is not None and ok(i[k]):
                    item[k] = _num(i[k])
            except (TypeError, ValueError):
                pass
        linha = _linha_do_item(item["analito"], item["valor"], texto) or ""
        nums_linha = _numeros(linha)
        for k in ("ref_min", "ref_max"):  # a faixa também precisa estar na linha do item
            if k in item and round(float(item[k]), 6) not in nums_linha:
                del item[k]
        tem_faixa = "ref_min" in item or "ref_max" in item
        if "[ilegível]" in linha and not tem_faixa:  # D4: trecho ilegível e faixa perdida → não segue sozinho
            ilegiveis.append(f"{item['analito']} (linha com trecho ilegível)")
            continue
        if item["unidade"] and normalizar(item["unidade"]).replace(" ", "") not in normalizar(linha).replace(" ", ""):
            item["unidade"] = ""  # unidade que não está na linha (ilegível no OCR) não é preenchida pela LLM
        if not faixa_coerente(item, linha):
            ilegiveis.append(f"{item['analito']} (faixa)")  # LLM trocou mínimo e máximo: não segue sozinho
            continue
        outros = _numeros(linha or "") - {round(float(item["valor"]), 6)}
        if "ref_min" not in item and "ref_max" not in item and outros:
            ilegiveis.append(f"{item['analito']} (faixa não lida)")  # a linha tem faixa, mas ela se perdeu
            continue
        itens.append(item)
    tipo = "imagem" if laudo.get("tipo") == "imagem" else "laboratorio"
    limpo = {"id": "envio", "ficticio": False, "tipo": tipo, "categoria": "enviado_pelo_paciente",
             "exame": str(laudo.get("exame") or "Laudo enviado").strip()[:80],
             "paciente": str(laudo.get("paciente") or "").strip(), "data_coleta": laudo.get("data_coleta")}
    if tipo == "laboratorio":
        limpo["itens"] = itens
    else:
        limpo["texto"] = texto.strip()  # laudo de imagem: o texto lido, sem reescrita
        limpo["achado_critico"] = False
    return limpo, ilegiveis


def _so_o_nome(nome):
    """"Paciente Fictício 06 • Sexo: M • Idade: 68 anos" → "Fictício 06" (o OCR troca • por *, + ou «; "Paciente"
    e "Nome" no começo são rótulo, e a LLM às vezes os tira: os dois lados da comparação passam por aqui)."""
    nome = re.split(r"\s[•*+«»|·]\s?|\s-\s|\[ileg|\b(?:sexo|idade|nascimento|nasc|dn|data|cpf|rg)\b", nome or "",
                    flags=re.I)[0]
    return re.sub(r"^\s*(paciente|nome)\b\s*:?\s*", "", nome, flags=re.I).strip()


def mesmo_nome(nome_laudo, nome_cadastro):
    """Primeiro e último nome iguais (sem acento). Sem nome legível no laudo → None (não dá para conferir)."""
    nome_laudo, nome_cadastro = _so_o_nome(nome_laudo), _so_o_nome(nome_cadastro)
    a = [w for w in re.findall(r"[a-z0-9]+", normalizar(nome_laudo or "")) if len(w) > 1]
    b = [w for w in re.findall(r"[a-z0-9]+", normalizar(nome_cadastro or "")) if len(w) > 1]
    if not a or not b:
        return None
    return a[0] == b[0] and a[-1] == b[-1]


def iniciais(nome):
    partes = [w for w in re.findall(r"[A-Za-zÀ-ÿ]+", nome or "") if len(w) > 2]
    return " ".join(p[0].upper() + "." for p in partes) or "não encontrado"
