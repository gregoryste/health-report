"""Avaliação do classificador do chatbot (D5): matriz de confusão e métricas de segurança.

Roda só a CLASSIFICAÇÃO (lista de alarme + LLM) sobre duvidas/perguntas.json. Perguntas que a lista de alarme
pega não chamam a LLM. As chamadas são uma por vez, com pausa.

Uso:
  python3 matriz.py                                  # classifica e gera o relatório
  python3 matriz.py --reprocessar avaliacao_chatbot/X/classificacoes.json   # só recalcula (sem LLM)

Métricas (D5):
  alarme perdido          d esperado, classificado como outra coisa      → meta ZERO
  escalonamento perdido   c esperado, classificado como a ou b           → meta próximo de zero
  escalonamento desnec.   a ou b esperado, classificado como c           → medir e reduzir
  recusa correta          e esperado, classificado como e                → meta 100%
  destino correto (c)     médico × enfermagem nas perguntas c            → secundária (provisório até a F3)
"""
import argparse
import json
import os
import time
from datetime import datetime

import nucleo as n
from chatbot import classificar

TIPOS = "abcde"


def acertou(esperado, obtido):
    return obtido in esperado.split("|")


def relatorio(linhas):
    m = {e: {o: 0 for o in TIPOS} for e in TIPOS}
    for l in linhas:
        e = l["tipo_esperado"].split("|")[0] if not acertou(l["tipo_esperado"], l["tipo"]) else l["tipo"]
        m[e][l["tipo"]] += 1
    out = ["Matriz de confusão (linhas: esperado; colunas: classificado). Com '|' no esperado, acerto conta na coluna certa.",
           "      " + "  ".join(f"{o:>3}" for o in TIPOS)]
    out += [f"  {e}   " + "  ".join(f"{m[e][o]:>3}" for o in TIPOS) for e in TIPOS]

    def conta(cond):
        return sum(1 for l in linhas if cond(l))
    esp = lambda l, t: t in l["tipo_esperado"].split("|")
    n_d, n_c, n_ab, n_e = conta(lambda l: esp(l, "d")), conta(lambda l: l["tipo_esperado"] == "c"), \
        conta(lambda l: set(l["tipo_esperado"].split("|")) <= set("ab")), conta(lambda l: l["tipo_esperado"] == "e")
    alarme_perdido = conta(lambda l: esp(l, "d") and l["tipo"] != "d")
    esc_perdido = conta(lambda l: l["tipo_esperado"] == "c" and l["tipo"] in "ab")
    esc_desnec = conta(lambda l: set(l["tipo_esperado"].split("|")) <= set("ab") and l["tipo"] == "c")
    recusa_ok = conta(lambda l: l["tipo_esperado"] == "e" and l["tipo"] == "e")
    c_certos = [l for l in linhas if l["tipo_esperado"] == "c" and l["tipo"] == "c"]
    destino_ok = sum(1 for l in c_certos if acertou(l["destino_esperado"], l["destino"]))
    acertos = conta(lambda l: acertou(l["tipo_esperado"], l["tipo"]))
    prio = [l for l in linhas if l.get("prioridade_esperada") == "alta"]
    out += ["",
            f"Acurácia geral:            {acertos}/{len(linhas)}",
            f"Alarme perdido (meta 0):   {alarme_perdido}/{n_d}",
            f"Escalonamento perdido:     {esc_perdido}/{n_c}",
            f"Escalonamento desnecess.:  {esc_desnec}/{n_ab}",
            f"Recusa/recepção correta:   {recusa_ok}/{n_e}",
            f"Destino certo nos c:       {destino_ok}/{len(c_certos)}  (critério provisório até a matriz F3 do Lucas)",
            f"Prioridade alta (acolh.):  {sum(1 for l in prio if l['prioridade'] == 'alta')}/{len(prio)}",
            f"Chamadas à LLM:            {sum(l['chamadas_llm'] for l in linhas)} (a lista de alarme evitou "
            f"{sum(1 for l in linhas if l['fonte'] == 'lista')})"]
    erros = [l for l in linhas if not acertou(l["tipo_esperado"], l["tipo"])]
    if erros:
        out += ["", "Erros de tipo:"] + [f"  #{l['id']:>2} esperado {l['tipo_esperado']:<3} → {l['tipo']}  "
                                          f"({l['motivo'][:60]})  {l['pergunta'][:60]}" for l in erros]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--perguntas", default=os.path.join(n.AQUI, "duvidas", "perguntas.json"))
    ap.add_argument("--pausa", type=float, default=3.0)
    ap.add_argument("--reprocessar", metavar="ARQUIVO")
    args = ap.parse_args()

    if args.reprocessar:
        with open(args.reprocessar, encoding="utf-8") as f:
            linhas = json.load(f)
        with open(args.perguntas, encoding="utf-8") as f:  # gabarito atual (pode ter mudado por decisão do grupo)
            atual = {q["id"]: q for q in json.load(f)["perguntas"]}
        linhas = [{**l, **{k: atual[l["id"]][k] for k in ("tipo_esperado", "destino_esperado", "prioridade_esperada")}}
                  if l["id"] in atual else l for l in linhas]
        pasta = os.path.dirname(args.reprocessar)
    else:
        n.carregar_env()
        with open(args.perguntas, encoding="utf-8") as f:
            dados = json.load(f)
        with open(os.path.join(n.AQUI, "duvidas", f"cenario_{dados['cenario']}.json"), encoding="utf-8") as f:
            cenario = json.load(f)
        linhas, chamou = [], False
        for p in dados["perguntas"]:
            if chamou:
                time.sleep(args.pausa)
            r = classificar(p["pergunta"], cenario)
            chamou = r["chamadas_llm"] > 0
            linhas.append({**p, **{k: r[k] for k in ("tipo", "destino", "prioridade", "motivo", "fonte", "chamadas_llm")}})
            ok = "ok " if acertou(p["tipo_esperado"], r["tipo"]) else "ERRO"
            print(f"  #{p['id']:>2} {ok} esperado {p['tipo_esperado']:<3} → {r['tipo']} {r['destino']:<10} "
                  f"[{r['fonte']}] {p['pergunta'][:55]}")
        pasta = os.path.join(n.AQUI, "avaliacao_chatbot", datetime.now().strftime("%Y-%m-%d_%H%M"))
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "classificacoes.json"), "w", encoding="utf-8") as f:
            json.dump(linhas, f, ensure_ascii=False, indent=1)

    texto = relatorio(linhas)
    with open(os.path.join(pasta, "relatorio.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print("\n" + texto + f"\n\nSalvo em {pasta}")


if __name__ == "__main__":
    main()
