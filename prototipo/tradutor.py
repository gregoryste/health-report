"""Pista do laudo: gera um rascunho pronto para revisão para cada laudo.

Fluxo por laudo:
  1. regra fixa (regra.py) marca os alterados e define prioridade e prazo (D4);
  2. E1: busca um exemplo aprovado parecido, anonimizado (exemplos_aprovados/);
  3. a LLM interna escreve a explicação + dúvidas antecipadas (F1);
  4. o código tira avisos de contato e fechos do texto do modelo e acrescenta as frases fixas, troca respostas
     que citam causa por uma resposta fixa e oculta nomes de escores (regra de produto, D5/D13);
  5. checagens: omissão, suavização, alertas, jargão, números e posição (camada 2), legibilidade;
  6. (opcional, camada 4) 2ª chamada à LLM confere se cada frase tem apoio no laudo.
A mensagem leva as definições aprovadas do glossário (camada 1) e o tom pela prioridade (camada 3).

O rascunho NUNCA vai ao paciente sem a ação de um revisor (registro.py).

Uso:
  python3 tradutor.py                              # todos os laudos, com E1
  python3 tradutor.py --laudos "laudos/L04*.json"  # só alguns
  python3 tradutor.py --sem-exemplo                # sem E1 (para comparar na demo)
  python3 tradutor.py --pausa 5                    # mais intervalo entre chamadas à LLM interna
  python3 tradutor.py --reprocessar rascunhos/X    # refaz o pós-processamento SEM chamar a LLM

Saídas em rascunhos/<data-hora>/: um <laudo>.json por laudo + resumo.csv.
"""
import argparse
import csv
import glob
import json
import os
import time
from datetime import datetime

import nucleo as n
from regra import avaliar_laudo, checar_omissao


def gerar_rascunho(laudo, sistema, exemplos, jargao, glossario, usar_exemplo=True, verificar=False, pausa=3.0):
    avaliacao = avaliar_laudo(laudo)
    exemplo = n.buscar_exemplo(laudo, avaliacao, exemplos) if usar_exemplo else None
    definicoes = n.termos_do_laudo(laudo, avaliacao, glossario)          # camada 1
    mensagem = n.montar_mensagem(laudo, avaliacao, exemplo, definicoes)

    t0 = time.time()
    bruto, modelo_servido = n.chamar_interna(os.environ.get("LLM_MODEL", ""), sistema, mensagem)
    tempo = round(time.time() - t0, 1)

    agora = datetime.now()
    r = processar_resposta(laudo, jargao, glossario, bruto, modelo_servido, tempo, exemplo["id"] if exemplo else None,
                           mensagem, f"{laudo['id']}-{agora:%Y%m%d-%H%M%S}", agora.isoformat(timespec="seconds"))
    if verificar:                                                          # camada 4
        time.sleep(pausa)  # segunda chamada, também com intervalo
        apoio = n.verificar_apoio(laudo, avaliacao, r["explicacao"], r["duvidas"], definicoes)
        aplicar_apoio(r, apoio)
    return r


def aplicar_apoio(r, apoio):
    r["verificacao"]["apoio"] = apoio
    if apoio.get("sem_apoio"):
        r["verificacao"]["alertas"].append(f"frase sem apoio no laudo (verificador): {len(apoio['sem_apoio'])}")
    elif not apoio.get("verificado", True):
        r["verificacao"]["alertas"].append("verificador falhou (revisar manualmente)")


def processar_resposta(laudo, jargao, glossario, bruto, modelo_servido, tempo, exemplo_id, mensagem, rascunho_id,
                       gerado_em):
    """Tudo o que vem depois da LLM. Separado para poder reprocessar respostas salvas sem nova chamada."""
    avaliacao = avaliar_laudo(laudo)
    definicoes = n.termos_do_laudo(laudo, avaliacao, glossario)
    explicacao_modelo, bloco_duvidas = n.separar(bruto)
    explicacao, removidas, fixas = n.finalizar_explicacao(explicacao_modelo, avaliacao, n.tem_escore(laudo))
    duvidas, duvidas_trocadas = n.proteger_duvidas(n.lista_duvidas(bloco_duvidas))
    explicacao, duvidas, escores_ocultados = n.ocultar_escores_rascunho(explicacao, duvidas)
    texto_duvidas = " ".join(f"{d['pergunta']} {d['resposta']}" for d in duvidas)

    omitidos = checar_omissao(explicacao, avaliacao)
    itens = [{"nome": v["nome"], "origem": v["origem"], "citado": v["nome"] not in omitidos}
             for v in avaliacao["verificaveis"]]
    alertas = n.alertas(explicacao, texto_duvidas, avaliacao, laudo) + (["resposta repetida"] if n.repetida(bruto) else [])
    if len(duvidas) < 3:
        alertas.append("menos de 3 dúvidas")
    texto_paciente = explicacao + "\n" + texto_duvidas
    numeros_fora = n.checar_numeros(texto_paciente, laudo, avaliacao, definicoes)   # camada 2
    posicao = n.checar_posicao(texto_paciente, laudo)                               # camada 2
    contradicoes = n.checar_contradicao(texto_paciente, avaliacao)                 # camada 2
    alertas += [f"contradiz a regra: {c}" for c in contradicoes]
    alertas += [f"número fora do laudo: {n.num_br(v)}" for v in numeros_fora]
    alertas += [f"posição: {p}" for p in posicao]

    return {
        "rascunho_id": rascunho_id,
        "laudo_id": laudo["id"],
        "tipo": avaliacao["tipo"],
        "categoria": laudo.get("categoria"),
        "exame": laudo["exame"],
        "prioridade": avaliacao["prioridade"],
        "prazo_revisao": avaliacao["prazo_revisao"],
        "status": "aguardando_revisao",
        "gerado_em": gerado_em,
        "modelo": modelo_servido,
        "tempo_geracao_s": tempo,
        "exemplo_e1": exemplo_id,
        "explicacao": explicacao,
        "duvidas": duvidas,
        "verificacao": {
            "itens": itens,
            "omitidos": omitidos,
            "suavizacao": n.suavizacao(explicacao, avaliacao),
            "alertas": alertas,
            "jargao": n.checar_jargao(explicacao + " " + texto_duvidas, jargao),
            "numeros_fora_do_laudo": numeros_fora,
            "posicao": posicao,
            "contradicoes": contradicoes,
            "apoio": None,
        },
        "legibilidade": {
            "laudo": n.flesch_pt(n.texto_do_laudo(laudo, avaliacao)),
            "explicacao": n.flesch_pt(explicacao),
            "palavras": len(explicacao.split()),
        },
        "auditoria": {
            "frases_fixas": fixas,
            "frases_removidas_do_modelo": removidas,
            "duvidas_com_causa_trocadas": duvidas_trocadas,
            "escores_ocultados": escores_ocultados,
            "definicoes_do_glossario": [t["termo"] for t in definicoes],
            "mensagem_enviada": mensagem,
            "resposta_bruta": bruto,
        },
    }


def linha_resumo(r):
    v = r["verificacao"]
    return {
        "laudo": r["laudo_id"], "categoria": r["categoria"], "prioridade": r["prioridade"],
        "exemplo_e1": r["exemplo_e1"] or "", "omitidos": "; ".join(v["omitidos"]),
        "suavizacao": "; ".join(v["suavizacao"]), "alertas": "; ".join(v["alertas"]),
        "jargao_proibido": "; ".join(v["jargao"]["proibidos"]),
        "jargao_sem_explicacao": "; ".join(v["jargao"]["sem_explicacao"]),
        "flesch_laudo": r["legibilidade"]["laudo"], "flesch_explicacao": r["legibilidade"]["explicacao"],
        "palavras": r["legibilidade"]["palavras"], "n_duvidas": len(r["duvidas"]),
        "sem_apoio": len((v.get("apoio") or {}).get("sem_apoio", [])) if v.get("apoio") else "",
        "tempo_s": r["tempo_geracao_s"],
    }


def salvar_e_mostrar(r, pasta, linhas):
    with open(os.path.join(pasta, f"{r['laudo_id']}.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    l = linha_resumo(r)
    linhas.append(l)
    falha = l["omitidos"] or l["suavizacao"] or l["jargao_proibido"]
    status = "FALHA" if falha else ("ALERTA" if l["alertas"] or l["jargao_sem_explicacao"] else "OK")
    print(f"  {l['laudo']} {status:<6} E1={l['exemplo_e1'] or '-':<4} omitidos=[{l['omitidos']}] "
          f"alertas=[{l['alertas']}] jargão=[{l['jargao_proibido']}|sem explicação: {l['jargao_sem_explicacao']}] "
          f"flesch {l['flesch_laudo']}→{l['flesch_explicacao']} dúvidas={l['n_duvidas']} {l['tempo_s']}s")


def achar_laudo(laudo_id):
    caminhos = glob.glob(os.path.join(n.AQUI, "laudos", f"{laudo_id}_*.json"))
    if not caminhos:
        raise FileNotFoundError(f"laudo {laudo_id} não encontrado em laudos/")
    with open(caminhos[0], encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--laudos", default=os.path.join(n.AQUI, "laudos", "*.json"))
    ap.add_argument("--sem-exemplo", action="store_true", help="desliga o E1 (exemplos aprovados no prompt)")
    ap.add_argument("--pausa", type=float, default=3.0, help="segundos entre chamadas (não sobrecarregar a LLM)")
    ap.add_argument("--saida", default=os.path.join(n.AQUI, "rascunhos", datetime.now().strftime("%Y-%m-%d_%H%M")))
    ap.add_argument("--verificar-apoio", choices=["nao", "imagem", "todos"], default="imagem",
                    help="camada 4: 2ª chamada à LLM conferindo o apoio de cada frase (padrão: só laudo de imagem)")
    ap.add_argument("--reprocessar", metavar="PASTA",
                    help="refaz os rascunhos da PASTA a partir das respostas brutas salvas, SEM chamar a LLM")
    args = ap.parse_args()

    jargao, glossario = n.carregar_jargao(), n.carregar_glossario()
    linhas = []

    if args.reprocessar:
        pasta = args.reprocessar
        for caminho in sorted(glob.glob(os.path.join(pasta, "L*.json"))):
            with open(caminho, encoding="utf-8") as f:
                antigo = json.load(f)
            aud = antigo["auditoria"]
            laudo = achar_laudo(antigo["laudo_id"])
            if antigo.get("exame") and antigo["exame"] != laudo["exame"]:  # ex.: L04 antigo (tireoide) virou L92
                print(f"  {antigo['laudo_id']}: PULADO, o rascunho é de '{antigo['exame']}', mas o laudo atual é "
                      f"'{laudo['exame']}' (ver rascunhos/LEIA-ME.md)")
                continue
            r = processar_resposta(laudo, jargao, glossario, aud["resposta_bruta"],
                                   antigo["modelo"], antigo["tempo_geracao_s"], antigo["exemplo_e1"],
                                   aud["mensagem_enviada"], antigo["rascunho_id"], antigo["gerado_em"])
            if antigo["verificacao"].get("apoio"):  # mantém a verificação já feita (não chama a LLM de novo)
                aplicar_apoio(r, antigo["verificacao"]["apoio"])
            r["reprocessado_em"] = datetime.now().isoformat(timespec="seconds")
            salvar_e_mostrar(r, pasta, linhas)
    else:
        n.carregar_env()
        sistema, exemplos = n.ler_prompt(), n.carregar_exemplos()
        pasta = args.saida
        os.makedirs(pasta, exist_ok=True)
        for k, caminho in enumerate(sorted(glob.glob(args.laudos))):
            with open(caminho, encoding="utf-8") as f:
                laudo = json.load(f)
            if k:
                time.sleep(args.pausa)  # uma chamada por vez, com intervalo
            try:
                verificar = args.verificar_apoio == "todos" or (args.verificar_apoio == "imagem"
                                                                 and laudo.get("tipo") == "imagem")
                r = gerar_rascunho(laudo, sistema, exemplos, jargao, glossario, usar_exemplo=not args.sem_exemplo,
                                   verificar=verificar, pausa=args.pausa)
            except Exception as e:
                print(f"  {laudo['id']}: ERRO {e}")
                continue
            salvar_e_mostrar(r, pasta, linhas)

    if linhas:
        with open(os.path.join(pasta, "resumo.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(linhas[0]))
            w.writeheader()
            w.writerows(linhas)
    print(f"\nRascunhos em {pasta}")


if __name__ == "__main__":
    main()
