"""Regra fixa (decisão D4 do plano.md).

1. Compara cada valor do laudo com a faixa de referência e marca alto, baixo ou crítico.
2. Define a prioridade do laudo e o prazo de revisão médica (fail-safe do plano).
3. Confere se a explicação gerada pela IA cita todos os valores alterados (checagem de omissão).

A IA escreve o texto; esta regra garante que nenhum valor alterado fique de fora.
Só usa laudos fictícios. As faixas são ilustrativas, não servem para uso clínico.

Dois tipos de laudo:
  - "laboratorio": lista de "itens" com valor e faixa. A regra decide o que está alterado.
  - "imagem": campo "texto" livre. A regra NÃO tem como decidir o que está alterado (é onde a IA
    generativa entra, D4). A prioridade vem do campo "achado_critico" (marcação do laudista); sem ele,
    fica "alterado" (fail-safe: na dúvida, prazo menor). A checagem de omissão usa o gabarito de teste,
    que nunca vai para o prompt do modelo.

Uso:
  python3 regra.py laudos/L01_hemograma.json
  python3 regra.py laudos/L01_hemograma.json --explicacao exemplos/L01_completa.txt
  python3 regra.py laudos/L01_hemograma.json --json        (saída para o n8n)

Código de saída: 0 = ok, 1 = a explicação omitiu algum valor alterado.
"""
import argparse
import json
import sys
import unicodedata

PRAZO = {
    "critico": "mesmo dia + ligação",
    "alterado": "2 dias úteis",
    "normal": "3 dias úteis",
}
ORDEM = {"normal": 0, "alterado": 1, "critico": 2}


def normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def faixa_texto(item):
    rmin, rmax, un = item.get("ref_min"), item.get("ref_max"), item["unidade"]
    if rmin is not None and rmax is not None:
        return f"{rmin}–{rmax} {un}"
    if rmin is not None:
        return f"≥ {rmin} {un}"
    return f"≤ {rmax} {un}"


def classificar(item):
    v = item["valor"]
    rmin, rmax = item.get("ref_min"), item.get("ref_max")
    cmin, cmax = item.get("critico_min"), item.get("critico_max")

    if rmin is not None and v < rmin:
        direcao = "baixo"
    elif rmax is not None and v > rmax:
        direcao = "alto"
    else:
        direcao = "normal"

    if (cmin is not None and v <= cmin) or (cmax is not None and v >= cmax):
        nivel = "critico"
    elif direcao != "normal":
        nivel = "alterado"
    else:
        nivel = "normal"

    return {
        "analito": item["analito"],
        "valor": v,
        "unidade": item["unidade"],
        "faixa": faixa_texto(item),
        "direcao": direcao,
        "nivel": nivel,
        "apelidos": item.get("apelidos", []),
    }


def eh_imagem(laudo):
    return laudo.get("tipo") == "imagem"


def avaliar_laudo(laudo):
    if eh_imagem(laudo):
        return avaliar_imagem(laudo)
    itens = [classificar(i) for i in laudo["itens"]]
    pior = max((i["nivel"] for i in itens), key=ORDEM.get, default="normal")
    alterados = [i for i in itens if i["nivel"] != "normal"]
    return {
        "id": laudo["id"],
        "tipo": "laboratorio",
        "prioridade": pior,
        "prazo_revisao": PRAZO[pior],
        "itens": itens,
        "alterados": [i["analito"] for i in alterados],
        # o que a checagem de omissão procura na explicação, e de onde veio
        "verificaveis": [{"nome": i["analito"], "apelidos": i["apelidos"], "origem": "regra"} for i in alterados],
    }


def avaliar_imagem(laudo):
    pior = "critico" if laudo.get("achado_critico") else "alterado"
    verificaveis = []
    for g in laudo.get("gabarito_alterados", []):
        if isinstance(g, str):
            g = {"achado": g}
        verificaveis.append({"nome": g["achado"], "apelidos": g.get("apelidos", []), "origem": "gabarito (teste)"})
    return {
        "id": laudo["id"],
        "tipo": "imagem",
        "prioridade": pior,
        "prazo_revisao": PRAZO[pior],
        "itens": [],
        "alterados": [],  # a regra não decide alterações em texto livre
        "verificaveis": verificaveis,
    }


def checar_omissao(explicacao, avaliacao):
    """Devolve os achados verificáveis que a explicação não cita (nem pelo nome nem por apelido)."""
    texto = normalizar(explicacao)
    return [v["nome"] for v in avaliacao["verificaveis"]
            if not any(normalizar(n) in texto for n in [v["nome"]] + v["apelidos"])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("laudo")
    ap.add_argument("--explicacao", help="arquivo .txt com a explicação gerada")
    ap.add_argument("--json", action="store_true", help="saída em JSON")
    args = ap.parse_args()

    with open(args.laudo, encoding="utf-8") as f:
        laudo = json.load(f)
    avaliacao = avaliar_laudo(laudo)

    faltando = None
    if args.explicacao:
        with open(args.explicacao, encoding="utf-8") as f:
            faltando = checar_omissao(f.read(), avaliacao)
        avaliacao["omitidos"] = faltando

    gabarito = laudo.get("gabarito_alterados")
    if gabarito is not None and not eh_imagem(laudo):
        avaliacao["confere_gabarito"] = sorted(gabarito) == sorted(avaliacao["alterados"])

    if args.json:
        print(json.dumps(avaliacao, ensure_ascii=False, indent=2))
    else:
        print(f"Laudo {avaliacao['id']} ({avaliacao['tipo']}) · prioridade: {avaliacao['prioridade']}"
              f" · revisão: {avaliacao['prazo_revisao']}")
        for i in avaliacao["itens"]:
            marca = {"normal": "  ", "alterado": "! ", "critico": "!!"}[i["nivel"]]
            print(f"  {marca} {i['analito']:<18} {i['valor']:>9} {i['unidade']:<7} ref {i['faixa']:<20} {i['direcao']}")
        if eh_imagem(laudo):
            for v in avaliacao["verificaveis"]:
                print(f"  !  {v['nome']}  [{v['origem']}]")
        if "confere_gabarito" in avaliacao:
            print(f"  Gabarito confere: {'sim' if avaliacao['confere_gabarito'] else 'NÃO'}")
        if faltando is not None:
            print("  Omissão: nenhuma" if not faltando else f"  OMISSÃO: a explicação não cita {', '.join(faltando)}")

    sys.exit(1 if faltando else 0)


if __name__ == "__main__":
    main()
