"""Conjunto de regressão (camada 6): confere os erros reais já vistos (regressao/casos.json).

Uso:
  python3 regressao.py --pasta rascunhos/X     # confere rascunhos já gerados (não chama a LLM)
  python3 regressao.py --gerar                 # gera os rascunhos dos casos (chama a LLM, uma vez por vez) e confere

Resultado por caso:
  PASSOU     o erro não apareceu;
  DETECTADO  o erro apareceu, mas o sistema alertou (o revisor vê). Segurança ok, qualidade a melhorar;
  SILENCIOSO o erro apareceu SEM alerta. É o resultado perigoso.

Código de saída: 0 = nenhum caso silencioso, 1 = algum caso silencioso.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from regra import normalizar

AQUI = os.path.dirname(os.path.abspath(__file__))


def conferir(r, caso):
    v = r["verificacao"]
    texto = normalizar(r["explicacao"] + " " + " ".join(d["pergunta"] + " " + d["resposta"] for d in r["duvidas"]))
    falhas = []
    if v["omitidos"]:
        falhas.append(f"omitiu {v['omitidos']}")
    if v["suavizacao"]:
        falhas.append(f"suavizou {v['suavizacao']}")
    if v["jargao"]["proibidos"]:
        falhas.append(f"jargão proibido {v['jargao']['proibidos']}")
    if v.get("numeros_fora_do_laudo"):
        falhas.append(f"número fora do laudo {v['numeros_fora_do_laudo']}")
    falhas += [f"contém '{t}'" for t in caso.get("nao_contem", []) if normalizar(t) in texto]
    falhas += [f"alerta '{a}'" for a in v["alertas"]
               if any(normalizar(s) in normalizar(a) for s in caso.get("sem_alertas", []))]
    return falhas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pasta", help="pasta de rascunhos já gerados")
    g.add_argument("--gerar", action="store_true", help="gera os rascunhos dos casos agora (chama a LLM)")
    ap.add_argument("--pausa", type=float, default=3.0)
    args = ap.parse_args()

    with open(os.path.join(AQUI, "regressao", "casos.json"), encoding="utf-8") as f:
        casos = json.load(f)["casos"]

    pasta = args.pasta
    if args.gerar:
        pasta = os.path.join(AQUI, "rascunhos", "regressao_" + datetime.now().strftime("%Y-%m-%d_%H%M"))
        for k, c in enumerate(casos):  # um laudo por vez, com intervalo entre as chamadas
            if k:
                time.sleep(args.pausa)
            subprocess.run([sys.executable, os.path.join(AQUI, "tradutor.py"), "--laudos",
                            os.path.join(AQUI, "laudos", f"{c['laudo']}_*.json"), "--saida", pasta,
                            "--pausa", str(args.pausa)], check=True)
        print()

    contagem = {"PASSOU": 0, "DETECTADO": 0, "SILENCIOSO": 0}
    for c in casos:
        caminho = os.path.join(pasta, f"{c['laudo']}.json")
        if not os.path.exists(caminho):
            print(f"  {c['laudo']}  --     sem rascunho em {pasta}")
            continue
        with open(caminho, encoding="utf-8") as f:
            r = json.load(f)
        falhas = conferir(r, c)
        # detectado = alguma checagem já sinaliza o rascunho ao revisor (alerta, omissão, suavização ou jargão)
        v = r["verificacao"]
        sinalizado = bool(v["alertas"] or v["omitidos"] or v["suavizacao"] or v["jargao"]["proibidos"])
        estado = "PASSOU" if not falhas else ("DETECTADO" if sinalizado else "SILENCIOSO")
        contagem[estado] += 1
        print(f"  {c['laudo']}  {estado:<10} ({c['erro_original']})")
        for x in falhas:
            print(f"          - {x}")
    print(f"\n{contagem['PASSOU']} passaram, {contagem['DETECTADO']} detectados, "
          f"{contagem['SILENCIOSO']} silenciosos, de {len(casos)} ({pasta})")
    sys.exit(1 if contagem["SILENCIOSO"] else 0)


if __name__ == "__main__":
    main()
