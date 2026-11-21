"""Etapa 7: chatbot COMPLETO (alarme → classificação → resposta → verificação → encaminhamento) nas perguntas do Jackson.

Cenário de cada pergunta (o que o paciente já recebeu e aprovado):
  - pergunta que cita um laudo (L04–L23): o "exemplo_explicacao" do gabarito do Jackson para esse laudo. Assim a
    avaliação do chatbot não herda os erros do tradutor (as explicações geradas ainda não foram revisadas);
  - pergunta geral (jejum, urgência, recusa...): cenário neutro, o L08 (hemograma normal).
Não grava na fila do serviço. Uma chamada à LLM por vez, com pausa.

Uso (de dentro de prototipo/):
  .venv/bin/python avaliar_perguntas.py                       # roda e gera o relatório
  .venv/bin/python avaliar_perguntas.py --reprocessar avaliacao_chatbot/X/respostas.json   # só o relatório
Saída em avaliacao_chatbot/<data-hora>_jackson/: respostas.json, relatorio.txt e perguntas_para_avaliar.csv
(para o Jackson e o Lucas julgarem as respostas; abre no Excel).
"""
import argparse
import csv
import json
import os
import re
import time
from datetime import datetime

import chatbot
import nucleo as n
from matriz import acertou, relatorio

JACKSON = os.path.join(n.AQUI, "..", "material_jackson", "2026-11-14", "Tradutor_de_Laudos")
NEUTRO = "L08"


def cenario(laudo_id):
    lid = laudo_id or NEUTRO
    g = json.load(open(os.path.join(JACKSON, "gabaritos", f"{lid}.json"), encoding="utf-8"))
    return {"id": f"gabarito-{lid}", "exames": lid, "explicacao_aprovada": g["exemplo_explicacao"],
            "duvidas_aprovadas": [], "duvidas_liberadas": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--perguntas", default=os.path.join(n.AQUI, "duvidas", "perguntas_jackson.json"))
    ap.add_argument("--pausa", type=float, default=3.0)
    ap.add_argument("--reprocessar", metavar="ARQUIVO")
    args = ap.parse_args()

    if args.reprocessar:
        linhas = json.load(open(args.reprocessar, encoding="utf-8"))
        pasta = os.path.dirname(args.reprocessar)
    else:
        n.carregar_env()
        base = chatbot.carregar_base()
        perguntas = json.load(open(args.perguntas, encoding="utf-8"))["perguntas"]
        linhas, chamou = [], False
        for p in perguntas:
            if chamou:
                time.sleep(args.pausa)  # uma chamada por vez, com intervalo
            r = chatbot.atender(p["pergunta"], cenario(p["laudo"]), base, pausa=args.pausa, gravar_fila=False)
            chamou = r["chamadas_llm"] > 0
            cls = r["classificacao"]
            linhas.append({**p, "cenario": p["laudo"] or f"{NEUTRO} (neutro)", "tipo": cls["tipo"],
                           "tipo_final": r["tipo_final"], "destino": cls.get("destino") or "", "destino_esperado": "-",
                           "prioridade": cls.get("prioridade"), "prioridade_esperada": None,
                           "motivo": cls.get("motivo", ""), "fonte": cls.get("fonte", ""),
                           "chamadas_llm": r["chamadas_llm"], "mensagem": r["mensagem_ao_paciente"],
                           "fontes_citadas": r["fontes"], "observacoes": r["observacoes"]})
            ok = "ok " if acertou(p["tipo_esperado"], r["tipo_final"]) else "ERRO"
            print(f"  {p['id']} {ok} esperado {p['tipo_esperado']} → classif. {cls['tipo']} / final {r['tipo_final']}"
                  f"  {p['pergunta'][:60]}", flush=True)
        pasta = os.path.join(n.AQUI, "avaliacao_chatbot", datetime.now().strftime("%Y-%m-%d_%H%M") + "_jackson")
        os.makedirs(pasta, exist_ok=True)
        json.dump(linhas, open(os.path.join(pasta, "respostas.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    final = [{**l, "tipo": l["tipo_final"]} for l in linhas]
    texto = ("Perguntas do Jackson (30), chatbot completo. Cenário: exemplo de explicação do gabarito do laudo citado; "
             f"perguntas gerais com o {NEUTRO} (neutro). Sem destino nem prioridade esperados (o Jackson não marcou): "
             "ignore a linha 'Destino certo' e 'Prioridade alta'.\n\n"
             "== 1. Classificação (lista de alarme + LLM) ==\n" + relatorio(linhas) +
             "\n\n== 2. Tipo final (depois da resposta e da verificação: a/b sem apoio viram c) ==\n" + relatorio(final))
    open(os.path.join(pasta, "relatorio.txt"), "w", encoding="utf-8").write(texto + "\n")
    with open(os.path.join(pasta, "perguntas_para_avaliar.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Nº", "Pergunta", "Laudo (cenário)", "Tipo esperado", "Tipo final", "Resposta ao paciente",
                    "Observação do Jackson", "Resposta adequada? (Sim/Em parte/Não)", "Comentário"])
        for l in linhas:
            # como o paciente lê: sem os códigos de fonte ([A], [B01-1]), que o serviço também tira
            msg = chatbot.remover_codigos(l["mensagem"])
            w.writerow([l["id"], l["pergunta"], l["cenario"], l["tipo_esperado"], l["tipo_final"], msg,
                        l["obs"], "", ""])
    print("\n" + texto + f"\n\nSalvo em {pasta}")


if __name__ == "__main__":
    main()
