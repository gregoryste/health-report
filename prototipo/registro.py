"""Registro de aprovações (plano.md, seção 5): o sinal útil é "o que o revisor mudou".

Cada ação na tela de aprovação vira uma linha em registros/aprovacoes.jsonl com:
rascunho original, versão final, quem revisou, tempo de revisão, ação e motivo do descarte.
Também guarda o tamanho da edição, para medir a melhora (aprovação sem edição sobe, edição média cai).

Uso pelo código da tela (etapa 6):
  from registro import registrar
  registrar(rascunho, acao="editado", revisor="Lucas", tempo_revisao_s=95,
            explicacao_final="...", duvidas_liberadas=True)
"""
import difflib
import json
import os
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.environ.get("REGISTRO_APROVACOES") or os.path.join(AQUI, "registros", "aprovacoes.jsonl")
ACOES = {"aprovado", "editado", "descartado"}


def tamanho_edicao(original, final):
    """Fração do texto que mudou (0 = igual, 1 = tudo diferente), por palavras."""
    if final is None:
        return None
    return round(1 - difflib.SequenceMatcher(None, original.split(), final.split()).ratio(), 3)


def registrar(rascunho, acao, revisor, tempo_revisao_s, explicacao_final=None, duvidas_finais=None,
              duvidas_liberadas=True, motivo_descarte=None, arquivo=ARQUIVO):
    if acao not in ACOES:
        raise ValueError(f"ação deve ser uma de {sorted(ACOES)}")
    if acao == "descartado" and not motivo_descarte:
        raise ValueError("descarte exige motivo")
    if acao == "aprovado":
        explicacao_final, duvidas_finais = rascunho["explicacao"], rascunho["duvidas"]
    linha = {
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
        "rascunho_id": rascunho["rascunho_id"],
        "laudo_id": rascunho["laudo_id"],
        "modelo": rascunho["modelo"],
        "exemplo_e1": rascunho.get("exemplo_e1"),
        "acao": acao,
        "revisor": revisor,
        "tempo_revisao_s": tempo_revisao_s,
        "explicacao_original": rascunho["explicacao"],
        "explicacao_final": explicacao_final,
        "duvidas_originais": rascunho["duvidas"],
        "duvidas_finais": duvidas_finais,
        "duvidas_liberadas": duvidas_liberadas if acao != "descartado" else False,
        "tamanho_edicao": tamanho_edicao(rascunho["explicacao"], explicacao_final),
        "motivo_descarte": motivo_descarte,
    }
    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha
