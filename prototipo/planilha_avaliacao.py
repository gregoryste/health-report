"""Etapa 7: monta a planilha de avaliação a partir de uma rodada do tradutor.

Copia a planilha do Jackson (Avaliacao_e_perguntas.xlsx) e acrescenta:
  - aba "Explicacoes": laudo original, explicação gerada, dúvidas antecipadas e conteúdos obrigatórios do gabarito,
    para o Jackson e o Lucas lerem e preencherem as abas deles;
  - aba "Metricas_automaticas": checagens do sistema (omissão, jargão, alertas, legibilidade...), À PARTE, para não
    influenciar a avaliação humana (o README do Jackson pede avaliação independente);
  - nas abas Jackson, Lucas e Consenso: só as colunas objetivas (versão da execução, palavras por frase antes e
    depois). As colunas de julgamento ficam em branco.

Uso (de dentro de prototipo/; precisa do openpyxl):
  .venv/bin/python planilha_avaliacao.py rascunhos/2026-11-14_etapa7_jackson
Saída: <pasta da rodada>/Avaliacao_<nome da rodada>.xlsx
"""
import argparse
import glob
import json
import os
import re

try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
except ImportError:
    raise SystemExit("Falta o openpyxl. Instale com: .venv/bin/pip install openpyxl")

import nucleo as n
from regra import avaliar_laudo
from tradutor import achar_laudo

AQUI = os.path.dirname(os.path.abspath(__file__))
JACKSON = os.path.join(AQUI, "..", "material_jackson", "2026-11-14", "Tradutor_de_Laudos")
METODO_PALAVRAS = ("Palavras por frase: frase termina em . ! ? seguido de espaço (vírgula decimal, como 6,8, não "
                   "corta frase); palavra = sequência de letras/dígitos, e números como 6,8 ou 265.000 contam como "
                   "uma palavra; tópicos de lista e quebras de linha também fecham frase. Antes = texto do laudo "
                   "(imagem) ou 'analito valor unidade, referência faixa.' por item (laboratório).")


def palavras_por_frase(texto):
    frases = [f for f in re.split(r"(?<=[.!?])\s+|\n+", texto or "") if re.search(r"\w", f)]
    palavras = re.findall(r"\w+(?:[.,]\d+)*", texto or "")
    return round(len(palavras) / len(frases), 1) if frases else None


def ler_rodada(pasta):
    rascunhos = {}
    for caminho in sorted(glob.glob(os.path.join(pasta, "L*.json"))):
        r = json.load(open(caminho, encoding="utf-8"))
        rascunhos[r["laudo_id"]] = r
    return rascunhos


def gabarito(lid):
    caminho = os.path.join(JACKSON, "gabaritos", f"{lid}.json")
    return json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else {}


def texto_original(laudo):
    return n.texto_do_laudo(laudo, avaliar_laudo(laudo))


def aba(wb, nome, cabecalho, larguras):
    if nome in wb.sheetnames:
        del wb[nome]
    ws = wb.create_sheet(nome)
    ws.append(cabecalho)
    for k, c in enumerate(ws[1], 1):
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDE7F0")
        ws.column_dimensions[c.column_letter].width = larguras[k - 1]
    ws.freeze_panes = "B2"
    return ws


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rodada", help="pasta da rodada em rascunhos/")
    ap.add_argument("--modelo", default=os.path.join(JACKSON, "Avaliacao_e_perguntas.xlsx"))
    args = ap.parse_args()

    rascunhos = ler_rodada(args.rodada)
    info = {}
    if os.path.exists(os.path.join(args.rodada, "rodada.json")):
        info = json.load(open(os.path.join(args.rodada, "rodada.json"), encoding="utf-8"))
    versao = f"{os.path.basename(os.path.normpath(args.rodada))} · {info.get('modelo', '?')} · prompt {info.get('prompt_sha256', '?')}"
    wb = openpyxl.load_workbook(args.modelo)
    quebra = Alignment(wrap_text=True, vertical="top")

    ws = aba(wb, "Explicacoes", ["ID", "Categoria", "Exame", "Laudo original", "Explicação gerada (vai ao revisor)",
                                 "Dúvidas antecipadas", "Conteúdos obrigatórios (gabarito)", "Rascunho"],
             [7, 16, 22, 50, 70, 60, 45, 22])
    wm = aba(wb, "Metricas_automaticas", ["ID", "Categoria", "Prioridade (regra)", "Urgência esperada (gabarito)",
                                          "Omissão (checagem)", "Suavização", "Alertas", "Jargão proibido",
                                          "Jargão sem explicação", "Números fora do laudo", "Frases sem apoio",
                                          "Flesch antes", "Flesch depois", "Palavras/frase antes",
                                          "Palavras/frase depois", "Palavras", "Exemplo E1", "Tempo (s)"],
             [7, 16, 14, 22, 28, 18, 40, 16, 22, 16, 12, 9, 9, 10, 10, 9, 9, 8])
    medidas = {}
    for lid, r in rascunhos.items():
        laudo = achar_laudo(lid)
        g = gabarito(lid)
        v = r["verificacao"]
        antes, depois = palavras_por_frase(texto_original(laudo)), palavras_por_frase(r["explicacao"])
        medidas[lid] = (antes, depois)
        duvidas = "\n\n".join(f"P: {d['pergunta']}\nR: {d['resposta']}" for d in r["duvidas"])
        ws.append([lid, r["categoria"], r["exame"], texto_original(laudo), r["explicacao"], duvidas,
                   "\n".join("• " + c for c in g.get("conteudos_obrigatorios", [])), r["rascunho_id"]])
        apoio = v.get("apoio") or {}
        wm.append([lid, r["categoria"], r["prioridade"], g.get("urgencia_esperada", ""), "; ".join(v["omitidos"]),
                   "; ".join(v["suavizacao"]), "; ".join(v["alertas"]), "; ".join(v["jargao"]["proibidos"]),
                   "; ".join(v["jargao"]["sem_explicacao"]),
                   "; ".join(str(x) for x in v.get("numeros_fora_do_laudo", [])),
                   len(apoio.get("sem_apoio", [])) if apoio else "", r["legibilidade"]["laudo"],
                   r["legibilidade"]["explicacao"], antes, depois, r["legibilidade"]["palavras"],
                   r["exemplo_e1"] or "", r["tempo_geracao_s"]])
    for linha in ws.iter_rows(min_row=2):
        for c in linha:
            c.alignment = quebra
    wm.append([])
    wm.append([METODO_PALAVRAS])
    wm.append([f"Rodada: {versao}. Leia esta aba só DEPOIS de preencher a sua avaliação."])

    # abas de avaliação: só as colunas objetivas (I versão, K e L palavras por frase)
    for nome in ("Jackson", "Lucas", "Consenso"):
        if nome not in wb.sheetnames:
            continue
        av = wb[nome]
        for linha in av.iter_rows(min_row=2):
            lid = linha[0].value
            if lid in rascunhos:
                linha[8].value = versao
                linha[10].value, linha[11].value = medidas[lid]
    saida = os.path.join(args.rodada, f"Avaliacao_{os.path.basename(os.path.normpath(args.rodada))}.xlsx")
    wb.save(saida)
    print(f"{len(rascunhos)} laudos → {saida}")


if __name__ == "__main__":
    main()
