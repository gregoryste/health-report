"""Mostra a situação dos modelos de mensagem na Meta e liga no .env os que já foram aprovados.

Uso (de dentro de prototipo/):  .venv/bin/python -m app.whatsapp_modelos
Depois de ligar um modelo, reinicie o serviço para ele passar a usar o modelo.
"""
import json
import re
import urllib.request

MAPA = {"aviso_nova_mensagem": "WHATSAPP_MODELO_AVISO", "lembrete_mensagem": "WHATSAPP_MODELO_LEMBRETE",
        "codigo_acesso": "WHATSAPP_MODELO_CODIGO"}


def main():
    texto = open(".env", encoding="utf-8").read()
    env = dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", texto, flags=re.M))
    req = urllib.request.Request(
        f"https://graph.facebook.com/{env.get('WHATSAPP_API_VERSAO', 'v25.0')}/{env['WHATSAPP_WABA_ID']}"
        "/message_templates?fields=name,language,status&limit=100",
        headers={"Authorization": "Bearer " + env["WHATSAPP_TOKEN"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        modelos = {t["name"]: t["status"] for t in json.loads(r.read())["data"] if t["language"] == "pt_BR"}
    mudou = False
    for nome, var in MAPA.items():
        status = modelos.get(nome, "não criado")
        ligado = env.get(var, "") == nome
        if status == "APPROVED" and not ligado:
            texto = re.sub(rf"^{var}=.*$", f"{var}={nome}", texto, flags=re.M)
            ligado, mudou = True, True
        print(f"{nome:<22} {status:<12} {'em uso' if ligado else 'texto livre (janela de 24 h)'}")
    if mudou:
        open(".env", "w", encoding="utf-8").write(texto)
        print("\n.env atualizado: reinicie o serviço para usar os modelos aprovados.")


if __name__ == "__main__":
    main()
