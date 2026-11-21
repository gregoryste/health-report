"""Cadastra pacientes fictícios e envia laudos de teste ao serviço (ou ao n8n).

Uso (de dentro de prototipo/, com o serviço rodando):
  .venv/bin/python -m app.semear                     # pacientes + laudos L03, L92, L91 pela API do serviço
  .venv/bin/python -m app.semear L01 L90             # escolhe os laudos
  .venv/bin/python -m app.semear --via n8n L01       # entra pelo webhook do n8n (pista do laudo)
  .venv/bin/python -m app.semear --so-pacientes
Cada laudo gera 1 chamada à LLM interna (2 se for de imagem), uma por vez, com pausa.
"""
import argparse
import glob
import json
import os
import time
import urllib.request

import nucleo as n

from . import banco

# Pacientes FICTÍCIOS (nomes, datas e telefones inventados). Telefone real só por .env, no teste de homologação.
PACIENTES = [
    ("P01", "Paciente Fictício 01", "1972-03-14", "L01"), ("P02", "Paciente Fictício 02", "1988-07-02", "L02"),
    ("P03", "Paciente Fictício 03", "1955-11-23", "L03"), ("P04", "Paciente Fictício 04", "1987-05-09", "L92"),
    ("P90", "Paciente Fictício 90", "1982-01-30", "L90"), ("P91", "Paciente Fictício 91", "1997-09-18", "L91"),
]


def cpf_ficticio(pid):
    """CPF FICTÍCIO com dígitos verificadores válidos (a triagem confere): base 000.000.0NN + os 2 dígitos calculados.
    P05 -> 000.000.005-15. Números tão baixos dificilmente foram emitidos; ainda assim, só para teste."""
    base = f"0000000{pid[1:]}"
    for n in (9, 10):
        soma = sum(int(base[i]) * (n + 1 - i) for i in range(n))
        base += str(soma * 10 % 11 % 10)
    return f"{base[:3]}.{base[3:6]}.{base[6:9]}-{base[9:]}"


def _telefones_por_paciente():
    """WHATSAPP_TELEFONES no .env: "P03=+55 51 9xxxx-xxxx; P04=+55 51 9yyyy-yyyy" (um número por paciente fictício).
    Cada número precisa estar na lista de destinatários do número de teste da Meta."""
    mapa = {}
    for par in os.environ.get("WHATSAPP_TELEFONES", "").split(";"):
        if "=" in par:
            pid, tel = par.split("=", 1)
            mapa[pid.strip().upper()] = tel.strip()
    return mapa


def semear_pacientes():
    banco.iniciar()
    tel_teste = os.environ.get("WHATSAPP_TELEFONE_TESTE", "")
    por_paciente = _telefones_por_paciente()
    for pid, nome, nasc, _ in PACIENTES:
        tel = por_paciente.get(pid) or tel_teste or f"+55 51 90000-00{pid[1:]}"
        banco.executar("INSERT OR REPLACE INTO pacientes (id, nome, nascimento, telefone, cpf) VALUES (?,?,?,?,?)",
                       pid, nome, nasc, tel, cpf_ficticio(pid))
    return {lid: pid for pid, _, _, lid in PACIENTES}


def enviar(url, dados, chave=""):
    req = urllib.request.Request(url, data=json.dumps(dados).encode(), headers={
        "Content-Type": "application/json", "X-Api-Key": chave})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode() or "{}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("laudos", nargs="*", default=["L03", "L92", "L91"])
    ap.add_argument("--via", choices=["servico", "n8n"], default="servico")
    ap.add_argument("--so-pacientes", action="store_true")
    args = ap.parse_args()
    n.carregar_env()
    mapa = semear_pacientes()
    print(f"{len(mapa)} pacientes fictícios cadastrados")
    if args.so_pacientes:
        return
    base = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
    n8n = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
    for k, lid in enumerate(args.laudos):
        laudo = json.load(open(glob.glob(os.path.join(n.AQUI, "laudos", f"{lid}_*.json"))[0], encoding="utf-8"))
        corpo = {"paciente_id": mapa[lid], "laudo": laudo}
        if k:
            time.sleep(float(os.environ.get("LLM_PAUSA", "3")))
        url = f"{n8n}/webhook/laudo" if args.via == "n8n" else f"{base}/api/laudos"
        r = enviar(url, corpo, os.environ.get("SERVICO_API_KEY", ""))
        print(f"  {lid} → {r}")


if __name__ == "__main__":
    main()
