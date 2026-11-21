"""(Re)cadastra o webhook do WhatsApp na Meta com o BASE_URL atual do .env e mostra a situação.

O endereço do túnel rápido (cloudflared) MUDA a cada vez que ele sobe. Depois de subir o túnel:
  1. coloque o novo endereço em BASE_URL no .env e reinicie o serviço;
  2. rode (de dentro de prototipo/, com o serviço rodando):  .venv/bin/python -m app.whatsapp_webhook
A Meta verifica o endereço na hora (GET com hub.challenge); o serviço precisa estar no ar.
Usa WHATSAPP_APP_ID e WHATSAPP_APP_SECRET (token de app), WHATSAPP_VERIFY_TOKEN e WHATSAPP_WABA_ID do .env.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request


def main():
    env = dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", open(".env", encoding="utf-8").read(), flags=re.M))
    versao = env.get("WHATSAPP_API_VERSAO", "v25.0")
    token_app = f"{env['WHATSAPP_APP_ID'].strip()}|{env['WHATSAPP_APP_SECRET'].strip()}"
    url = env["BASE_URL"].rstrip("/") + "/webhook/whatsapp"
    base = f"https://graph.facebook.com/{versao}/{env['WHATSAPP_APP_ID'].strip()}/subscriptions"
    dados = urllib.parse.urlencode({"object": "whatsapp_business_account", "callback_url": url,
                                    "verify_token": env["WHATSAPP_VERIFY_TOKEN"], "fields": "messages",
                                    "access_token": token_app}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(base, data=dados), timeout=60) as r:
            print("cadastro:", json.loads(r.read()))
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        raise SystemExit(f"falhou (HTTP {e.code}): {err.get('error_user_msg') or err.get('message')}\n"
                         "Confira se o serviço e o túnel estão no ar e se BASE_URL é o endereço atual do túnel.")
    with urllib.request.urlopen(base + "?" + urllib.parse.urlencode({"access_token": token_app}), timeout=30) as r:
        for s in json.loads(r.read()).get("data", []):
            print("ativo:", s.get("active"), "| url:", s.get("callback_url"), "| campos:",
                  [f["name"] for f in s.get("fields", [])])
    # garante que o app está inscrito na conta do WhatsApp Business (idempotente)
    req = urllib.request.Request(f"https://graph.facebook.com/{versao}/{env['WHATSAPP_WABA_ID']}/subscribed_apps",
                                 data=b"", headers={"Authorization": "Bearer " + env["WHATSAPP_TOKEN"]}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("app inscrito na conta WhatsApp:", json.loads(r.read()).get("success"))
    except urllib.error.HTTPError as e:
        print("aviso: inscrição na conta falhou (token do WhatsApp expirado?):",
              json.loads(e.read() or b"{}").get("error", {}).get("message"))


if __name__ == "__main__":
    main()
