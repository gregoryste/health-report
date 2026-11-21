"""Etapa 7: acurácia da leitura de fotos/PDF (app/leitura.py) contra o gabarito do Jackson.

Cada arquivo da pasta começa com o ID do laudo (L04_..., L06_foto.jpg). Para cada um, roda o MESMO caminho do
WhatsApp: extração (pdftotext ou OCR local) → LLM interna organiza → checagens (número no texto e na mesma linha do
item) → nome do paciente → desfecho (resumo imediato, ilegível ou outra pessoa). Uma chamada à LLM por arquivo, com pausa.

Mede, nos laudos de laboratório, item a item:
  correto      valor e faixa iguais ao gabarito
  descartado   não passou nas checagens (o paciente seria pedido de outra foto: seguro)
  ERRADO       passou nas checagens com valor diferente do gabarito → chegaria ao paciente no resumo imediato
Nos laudos de imagem: se foi reconhecido como imagem e quanto do texto do laudo o OCR recuperou.

Uso (de dentro de prototipo/):
  .venv/bin/python avaliar_fotos.py PASTA_DAS_FOTOS [--rotulo simuladas]
Saída em avaliacao_fotos/<data-hora>_<rótulo>/: resultados.json e relatorio.txt
"""
import argparse
import glob
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime

import nucleo as n
from app import leitura
from regra import normalizar

JACKSON = os.path.join(n.AQUI, "..", "material_jackson", "2026-11-14", "Tradutor_de_Laudos")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}


def gabarito(lid):
    return json.load(open(os.path.join(JACKSON, "laudos", f"{lid}.json"), encoding="utf-8"))


def _palavras(s):
    return {w for w in re.findall(r"[a-z0-9]+", normalizar(s)) if len(w) >= 3}


def _par(item_gab, lidos):
    """Item lido que corresponde ao item do gabarito (pelas palavras do nome)."""
    alvo = _palavras(item_gab["analito"])
    melhor, nota = None, 0.0
    for i in lidos:
        p = _palavras(i["analito"])
        s = len(alvo & p) / max(1, len(alvo))
        if s > nota:
            melhor, nota = i, s
    return melhor if nota == 1.0 else None  # nome inteiro: "colesterol" sozinho não liga HDL ao LDL


def _igual(a, b):
    return (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) < 1e-6)


def avaliar(caminho, pausa):
    nome = os.path.basename(caminho)
    lid = re.match(r"(L\d{2})", nome).group(1)
    condicao = os.path.splitext(nome)[0][len(lid):].strip("_") or "original"
    gab = gabarito(lid)
    t0 = time.time()
    texto, conf, como = leitura.extrair_texto(caminho, MIME[os.path.splitext(nome)[1].lower()])
    bruto = leitura.estruturar(texto) if len(re.sub(r"\s", "", texto)) >= 20 else {}
    laudo, ilegiveis = leitura.conferir(bruto, texto)
    time.sleep(pausa)
    r = {"arquivo": nome, "laudo": lid, "condicao": condicao, "tipo_gabarito": gab["tipo"], "tipo_lido": laudo["tipo"],
         "como": como, "confianca_ocr": round(conf, 1), "segundos": round(time.time() - t0, 1),
         "nome_confere": leitura.mesmo_nome(laudo.get("paciente"), gab["paciente"])}
    if gab["tipo"] == "laboratorio":
        itens = []
        for g in gab["itens"]:
            lido = _par(g, laudo.get("itens", []))
            if not lido:
                estado = "descartado"
            elif not leitura.plausivel(lido) and not _igual(lido["valor"], g["valor"]):
                estado = "barrado"  # lido errado, mas a checagem de plausibilidade segurou (não chega ao paciente)
            elif _igual(lido["valor"], g["valor"]) and _igual(lido.get("ref_min"), g.get("ref_min")) \
                    and _igual(lido.get("ref_max"), g.get("ref_max")):
                estado = "correto"
            else:
                estado = "ERRADO"
            itens.append({"analito": g["analito"], "esperado": g["valor"], "lido": lido and lido["valor"],
                          "faixa_esperada": [g.get("ref_min"), g.get("ref_max")],
                          "faixa_lida": lido and [lido.get("ref_min"), lido.get("ref_max")], "estado": estado})
        r["itens"] = itens
        if r["nome_confere"] is False:
            r["desfecho"] = "outra pessoa"
        elif ilegiveis or not laudo.get("itens"):
            r["desfecho"] = "ilegível (pede outra foto)"
        elif any(not leitura.plausivel(i) for i in laudo["itens"]):
            r["desfecho"] = "valor implausível → equipe (sem resumo)"
        else:
            r["desfecho"] = "resumo imediato"
    else:
        esperadas = _palavras(gab["texto"])
        r["recuperacao_texto"] = round(len(esperadas & _palavras(texto)) / max(1, len(esperadas)), 2)
        r["desfecho"] = ("outra pessoa" if r["nome_confere"] is False else
                         "revisão (laudo de imagem)" if laudo["tipo"] == "imagem" else "tipo errado")
    return r


def relatorio(res):
    lab = [r for r in res if r["tipo_gabarito"] == "laboratorio"]
    img = [r for r in res if r["tipo_gabarito"] == "imagem"]
    itens = [i for r in lab for i in r["itens"]]
    conta = lambda est, xs: sum(1 for i in xs if i["estado"] == est)  # noqa: E731
    out = [f"Arquivos: {len(res)} ({len(lab)} de laboratório, {len(img)} de imagem). Uma chamada à LLM por arquivo.",
           "", "LABORATÓRIO, item a item:",
           f"  corretos:   {conta('correto', itens)}/{len(itens)}",
           f"  descartados (seguro, pede outra foto): {conta('descartado', itens)}/{len(itens)}",
           f"  lidos errado, mas barrados pela plausibilidade (vão para a equipe): {conta('barrado', itens)}/{len(itens)}",
           f"  ERRADOS que passariam para o paciente: {conta('ERRADO', itens)}/{len(itens)}   ← meta: zero",
           "", "Por condição (laboratório):"]
    por = defaultdict(list)
    for r in lab:
        por[r["condicao"]].append(r)
    for cond, rs in sorted(por.items()):
        its = [i for r in rs for i in r["itens"]]
        des = defaultdict(int)
        for r in rs:
            des[r["desfecho"]] += 1
        out.append(f"  {cond:<12} corretos {conta('correto', its)}/{len(its)} · errados {conta('ERRADO', its)} · "
                   f"desfechos: {dict(des)} · confiança OCR média {sum(r['confianca_ocr'] for r in rs) / len(rs):.0f}")
    out += ["", "IMAGEM (texto livre):"]
    for r in img:
        out.append(f"  {r['arquivo']:<26} tipo lido: {r['tipo_lido']:<12} texto recuperado: {r['recuperacao_texto']:.0%} · "
                   f"nome confere: {r['nome_confere']} · {r['desfecho']}")
    erros = [(r["arquivo"], i) for r in lab for i in r["itens"] if i["estado"] == "ERRADO"]
    if erros:
        out += ["", "ITENS ERRADOS (detalhe):"] + [f"  {a}: {i['analito']} esperado {i['esperado']} {i['faixa_esperada']} · "
                                                    f"lido {i['lido']} {i['faixa_lida']}" for a, i in erros]
    nomes = [r["arquivo"] for r in res if r["nome_confere"] is not True]
    out += ["", f"Nome do paciente não conferido ou diferente: {nomes or 'nenhum'}",
            f"Tempo médio por arquivo: {sum(r['segundos'] for r in res) / len(res):.1f} s (com OCR e LLM)"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta")
    ap.add_argument("--rotulo", default="fotos")
    ap.add_argument("--pausa", type=float, default=3.0)
    args = ap.parse_args()
    n.carregar_env()
    arquivos = sorted(f for f in glob.glob(os.path.join(args.pasta, "L*"))
                      if os.path.splitext(f)[1].lower() in MIME)
    res = []
    for k, caminho in enumerate(arquivos, 1):
        try:
            r = avaliar(caminho, args.pausa)
        except Exception as e:  # noqa: BLE001
            r = {"arquivo": os.path.basename(caminho), "erro": f"{type(e).__name__}: {e}"}
            print(f"  [{k}/{len(arquivos)}] {r['arquivo']}: ERRO {r['erro']}", flush=True)
            continue
        res.append(r)
        resumo = (f"{sum(1 for i in r['itens'] if i['estado'] == 'correto')}/{len(r['itens'])} corretos"
                  if "itens" in r else f"texto {r['recuperacao_texto']:.0%}")
        print(f"  [{k}/{len(arquivos)}] {r['arquivo']:<26} {resumo:<14} {r['desfecho']} (OCR {r['confianca_ocr']:.0f})",
              flush=True)
    pasta = os.path.join(n.AQUI, "avaliacao_fotos", datetime.now().strftime("%Y-%m-%d_%H%M") + "_" + args.rotulo)
    os.makedirs(pasta, exist_ok=True)
    json.dump(res, open(os.path.join(pasta, "resultados.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    texto = relatorio(res)
    open(os.path.join(pasta, "relatorio.txt"), "w", encoding="utf-8").write(texto + "\n")
    print("\n" + texto + f"\n\nSalvo em {pasta}")


if __name__ == "__main__":
    main()
