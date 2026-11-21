"""Camada 5: origem de cada frase do rascunho, para a tela de aprovação (D6: "cada frase mostra sua origem").

Para cada frase da explicação devolve de onde ela parece vir:
  - frase fixa do sistema;
  - item do laudo (exame de sangue: pelo nome ou apelido do analito);
  - trecho do laudo (laudo de imagem: frase do laudo com mais palavras em comum);
  - definição aprovada do glossário;
  - sem origem clara → destacada para o revisor ler com atenção.
Também marca as frases que o verificador (camada 4) julgou sem apoio. É heurístico: orienta a leitura, não substitui.
"""
import re

import nucleo as n
from regra import normalizar

_PARADAS = set("para pela pelo como mais esta este essa esse estao seu sua seus suas que dos das nos nas com sem "
               "uma uns umas foi ser tem sobre entre quando onde muito pouco".split())


def _palavras(texto):
    return {w for w in re.findall(r"[a-z0-9]+", normalizar(texto)) if len(w) > 3 and w not in _PARADAS}


def origens(explicacao, laudo, avaliacao, definicoes, sem_apoio=()):
    fixas = {n.FECHO, n.ESCORE_FIXO} | set(n._frases(n.CONTATO_CRITICO))
    frases_laudo = [f for f in re.split(r"(?<=[.!?])\s+|\n", laudo.get("texto", "")) if f.strip()]
    sem_apoio_txt = {normalizar(s["frase"]) for s in sem_apoio}
    saida = []
    for frase in n._frases(explicacao):
        info = {"frase": frase, "origem": [], "tipo": "sem_origem", "sem_apoio": normalizar(frase) in sem_apoio_txt}
        if frase in fixas:
            info.update(tipo="fixa", origem=["frase fixa do sistema"])
            saida.append(info)
            continue
        nf = normalizar(frase)
        nums = n.numeros(frase)
        for i in avaliacao["itens"]:  # exame de sangue: pelo nome/apelido ou pelo valor citado
            nomes = [i["analito"]] + i["apelidos"]
            pelo_nome = any(re.search(r"\b" + re.escape(normalizar(x)) + r"\b", nf) for x in nomes)
            pelo_valor = any(abs(v - float(i["valor"])) < 1e-6 for v in nums)
            if pelo_nome or pelo_valor:
                marca = {"alto": "acima", "baixo": "abaixo"}.get(i["direcao"], "normal")
                info["origem"].append(f"{i['analito']}: {n.num_br(i['valor'])} {i['unidade']} "
                                      f"(ref. {n.faixa_br(i['faixa'])}) · {marca}")
        if frases_laudo:  # laudo de imagem
            pf = _palavras(frase)
            melhor, nota = None, 0.0
            for fl in frases_laudo:
                pl = _palavras(fl)
                if pf and pl:
                    j = len(pf & pl) / len(pf | pl)
                    if j > nota:
                        melhor, nota = fl, j
            if melhor and nota >= 0.12:
                info["origem"].append(f"laudo: “{melhor.strip()[:160]}”")
        for t in definicoes:  # glossário
            if len(_palavras(t["definicao"]) & _palavras(frase)) >= 3:
                info["origem"].append(f"glossário: {t['termo']}")
        if info["origem"]:
            info["tipo"] = "laudo"
        saida.append(info)
    return saida
