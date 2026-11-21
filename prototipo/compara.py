"""Compara modelos no tradutor de laudos (texto cru do modelo, sem as frases fixas do tradutor.py).

Desde a D11 só a LLM interna é usada; o Ollama local fica como opção (--sem-interna --modelos ...).
A rodada de 13/11/2026 (4 modelos locais, prompt antigo) está em saidas/2026-11-13_1102.

Para cada laudo e cada modelo: regra fixa (D4) → modelo escreve explicação + dúvidas (F1) →
omissão, suavização, alertas heurísticos, legibilidade e tempo.

Uso:
  python3 compara.py                                   # LLM interna (rota e token no .env), todos os laudos
  python3 compara.py --laudos "laudos/L04*.json"       # só alguns laudos
  python3 compara.py --pausa 5                         # mais intervalo entre chamadas
  python3 compara.py --sem-interna --modelos qwen3:8b  # Ollama local (não usado desde a D11)

Saídas em saidas/<data-hora>/: um .txt por modelo e laudo + resumo.csv.
"""
import argparse
import csv
import glob
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime

import nucleo as n
from regra import avaliar_laudo, checar_omissao

MODELOS_LOCAIS_13_11 = ["qwen3:8b", "llama3.1:8b", "gemma3:12b-it-qat", "qwen2.5vl:7b"]
PREFIXO_INTERNA = "interna:"


def chamar_ollama(host, modelo, sistema, mensagem):
    corpo = {"model": modelo, "stream": False, "think": False, "options": {"temperature": 0.2},
             "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": mensagem}]}
    for tentativa in range(2):
        req = urllib.request.Request(f"{host}/api/chat", data=json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)["message"]["content"]
        except urllib.error.HTTPError as e:
            erro = e.read().decode(errors="ignore")
            if tentativa == 0 and "think" in erro:
                corpo.pop("think")  # modelo sem modo de raciocínio
                continue
            raise RuntimeError(f"{modelo}: {erro}") from e


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelos", nargs="*", default=[],
                    help=f"modelos do Ollama local (rodada de 13/11: {MODELOS_LOCAIS_13_11})")
    ap.add_argument("--sem-interna", dest="interna", action="store_false",
                    help="não usa a LLM interna (padrão: usa; rota e token no .env)")
    ap.add_argument("--laudos", default=os.path.join(n.AQUI, "laudos", "*.json"))
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--pausa", type=float, default=3.0,
                    help="segundos de espera entre chamadas à LLM interna (não sobrecarregar o servidor)")
    args = ap.parse_args()

    modelos = list(args.modelos)
    if args.interna:
        n.carregar_env()
        modelos.insert(0, PREFIXO_INTERNA + os.environ.get("LLM_MODEL", ""))

    sistema = n.ler_prompt()
    laudos = []
    for caminho in sorted(glob.glob(args.laudos)):
        with open(caminho, encoding="utf-8") as f:
            laudo = json.load(f)
        laudos.append((laudo, avaliar_laudo(laudo)))

    pasta = os.path.join(n.AQUI, "saidas", datetime.now().strftime("%Y-%m-%d_%H%M"))
    os.makedirs(pasta, exist_ok=True)
    linhas = []

    for modelo in modelos:
        print(f"\n== {modelo}")
        interna = modelo.startswith(PREFIXO_INTERNA)
        for laudo, avaliacao in laudos:
            msg = n.montar_mensagem(laudo, avaliacao)
            if interna and linhas:
                time.sleep(args.pausa)  # uma chamada por vez, com intervalo
            t0 = time.time()
            try:
                if interna:
                    texto, _ = n.chamar_interna(modelo[len(PREFIXO_INTERNA):], sistema, msg)
                else:
                    texto = chamar_ollama(args.host, modelo, sistema, msg)
            except Exception as e:
                print(f"  {laudo['id']}: ERRO {e}")
                continue
            tempo = round(time.time() - t0, 1)
            explicacao, duvidas = n.separar(texto)
            omitidos = checar_omissao(explicacao, avaliacao)
            suaviza = n.suavizacao(explicacao, avaliacao)
            avisos = n.alertas(explicacao, duvidas, avaliacao, laudo) + (["resposta repetida"] if n.repetida(texto) else [])
            linha = {
                "modelo": modelo, "laudo": laudo["id"], "prioridade": avaliacao["prioridade"],
                "omitidos": "; ".join(omitidos), "suavizacao": "; ".join(suaviza), "alertas": "; ".join(avisos),
                "flesch_pt": n.flesch_pt(explicacao), "palavras": len(explicacao.split()),
                "n_duvidas": len(re.findall(r"^\s*\**P\s*[:.)]", duvidas, flags=re.M)),
                "formato_ok": bool(explicacao and duvidas), "tempo_s": tempo,
            }
            linhas.append(linha)
            nome = f"{modelo.replace(':', '_').replace('/', '_')}__{laudo['id']}.txt"
            with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
                f.write(f"# {modelo} · {laudo['id']}\n\n## Entrada\n{msg}\n\n## Resposta\n{texto}\n")
            status = "FALHA" if omitidos or suaviza else ("ALERTA" if avisos else "OK")
            print(f"  {laudo['id']} {status:<6} omitidos=[{linha['omitidos']}] suaviza=[{linha['suavizacao']}] "
                  f"alertas=[{linha['alertas']}] flesch={linha['flesch_pt']} dúvidas={linha['n_duvidas']} {tempo}s")

    if linhas:
        with open(os.path.join(pasta, "resumo.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(linhas[0]))
            w.writeheader()
            w.writerows(linhas)
    print(f"\nSaídas em {pasta}")


if __name__ == "__main__":
    main()
