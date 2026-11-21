"""Teste offline da triagem pelo WhatsApp (D3, 2ª revisão). Não chama a LLM nem a Meta.

Roda num banco TEMPORÁRIO, em WHATSAPP_MODO=simulado:
  .venv/bin/python testes/teste_triagem_whatsapp.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

os.environ["BANCO"] = os.path.join(tempfile.mkdtemp(), "teste.db")
os.environ["WHATSAPP_MODO"] = "simulado"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import avisos, banco, canal_whatsapp as cw  # noqa: E402
from app.semear import cpf_ficticio  # noqa: E402

banco.iniciar()
COLEGA = "5551990000002"        # como a Meta manda o número (wa_id)
GREGORY = "555190000001"        # sem o 9: a Meta às vezes manda assim
ESTRANHO = "5511912345678"
for pid, nasc, tel in [("P01", "1972-03-14", "+55 51 99000-0001"), ("P02", "1988-07-02", "+55 51 99000-0001"),
                       ("P05", "1990-05-05", "+55 51 99000-0002")]:
    banco.executar("INSERT INTO pacientes (id, nome, nascimento, telefone, cpf) VALUES (?,?,?,?,?)",
                   pid, f"Paciente Fictício {pid[1:]}", nasc, tel, cpf_ficticio(pid))
for pid in ("P02", "P05"):
    banco.executar("INSERT INTO publicacoes (laudo_id, paciente_id, token, exame, explicacao, duvidas_json, "
                   "duvidas_liberadas, revisor, publicado_em) VALUES (?,?,?,?,?,?,?,?,?)", f"L-{pid}", pid,
                   f"tok-{pid}", "Check-up", "Explicação aprovada de teste.",
                   '[{"pergunta": "O que é LDL?", "resposta": "Resposta aprovada."}]', 1, "teste", banco.agora())

n_msg = 0
falhas = []


def msg(numero, texto):
    global n_msg
    n_msg += 1
    return cw.receber(f"m{n_msg}", numero, texto, lambda token, p: {"mensagem": "resposta", "tipo_final": "a"},
                      lambda pid, laudo: PROC_LAUDO[0](pid, laudo))


PROC_LAUDO = [lambda pid, laudo: None]  # trocado na seção 11 para guardar os rascunhos gerados


def toque(numero, escolha):
    global n_msg
    n_msg += 1
    return cw.receber_escolha(f"m{n_msg}", numero, escolha, "",
                              lambda token, p: {"mensagem": "resposta", "tipo_final": "a"},
                              lambda pid, laudo: PROC_LAUDO[0](pid, laudo))


def ultimo(numero_ou_pid):
    a = banco.um("SELECT texto FROM avisos WHERE telefone=? OR paciente_id=? ORDER BY id DESC LIMIT 1",
                 numero_ou_pid, numero_ou_pid)
    return a["texto"] if a else None


def confere(nome, obtido, esperado):
    ok = obtido == esperado if not callable(esperado) else esperado(obtido)
    print(f"  {'ok ' if ok else 'FALHOU'}  {nome}: {obtido!r}")
    if not ok:
        falhas.append(nome)


T = avisos.TRIAGEM
print("1. Colega: identificação, termo, explicação, dúvida, SAIR")
confere("oi inicia a triagem", msg(COLEGA, "Oi"), "triagem iniciada")
confere("pede CPF", ultimo(COLEGA), T["boas_vindas"])
confere("CPF curto", msg(COLEGA, "123"), "cpf inválido")
confere("dígito verificador errado", msg(COLEGA, cpf_ficticio("P05")[:-1] + "0"), "cpf inválido")
confere("CPF ok, no meio da frase", msg(COLEGA, "meu cpf é " + cpf_ficticio("P05")), "pediu nascimento")
confere("CPF não fica em texto no registro",
        banco.um("SELECT texto FROM wa_recebidas WHERE id=?", f"m{n_msg}")["texto"], "[CPF informado]")
confere("data inválida", msg(COLEGA, "5 de maio"), "data inválida")
confere("data ok, sem consentimento → termo", msg(COLEGA, "05/05/1990"), "identificado; termo enviado")
confere("termo enviado", ultimo(COLEGA), "[termo de consentimento: Sim / Não]")
confere("pergunta antes do aceite não passa", msg(COLEGA, "o que é LDL?"), "termo reenviado")
confere("Sim", toque(COLEGA, "termo:sim"), "consentimento registrado")
confere("explicação saiu", bool(banco.um("SELECT id FROM avisos WHERE paciente_id='P05' AND texto LIKE '%Explicação aprovada%'")), True)
confere("publicação marcada como lida", bool(banco.um("SELECT lido_em FROM publicacoes WHERE paciente_id='P05'")["lido_em"]), True)
confere("dúvida aprovada pelo menu", toque(COLEGA, "duv:0"), "dúvida aprovada respondida")
confere("dúvida livre", msg(COLEGA, "posso comer ovo?"), "dúvida tipo a")
confere("SAIR revoga", msg(COLEGA, "SAIR"), "revogado")
confere("sem consentimento ativo", cw.consentimento("P05"), None)
confere("depois do SAIR, recomeça", msg(COLEGA, "oi"), "triagem iniciada")

print("2. Recusa do termo")
msg(COLEGA, cpf_ficticio("P05").replace(".", "").replace("-", ""))
msg(COLEGA, "05051990")
confere("Não", toque(COLEGA, "termo:nao"), "termo recusado")
confere("texto de recusa", ultimo(COLEGA), T["termo_recusado"])
confere("nada de saúde foi enviado depois", ultimo("P05"), T["termo_recusado"])

print("3. Número compartilhado: o CPF decide o paciente")
msg(GREGORY, "oi")
msg(GREGORY, cpf_ficticio("P02"))
r = msg(GREGORY, "02/07/1988")
confere("P02 identificado", banco.um("SELECT paciente_id FROM wa_sessoes WHERE numero=?", cw._chave_numero(GREGORY))["paciente_id"], "P02")

print("4. CPF e data certos, mas de outro número: não identifica")
msg(ESTRANHO, "oi")
msg(ESTRANHO, cpf_ficticio("P05"))
confere("número errado", msg(ESTRANHO, "05/05/1990"), "não confere")
msg(ESTRANHO, cpf_ficticio("P05"))
msg(ESTRANHO, "05/05/1990")
msg(ESTRANHO, cpf_ficticio("P05"))
confere("3ª tentativa bloqueia", msg(ESTRANHO, "05/05/1990"), "bloqueado")
confere("alerta no painel", bool(banco.um("SELECT id FROM alertas WHERE tipo='identificacao'")), True)
confere("continua bloqueado", msg(ESTRANHO, "oi"), "bloqueado")

print("5. Alarme antes da identificação")
confere("dor no peito", msg("5521999990000", "estou com dor no peito"), "urgência")
confere("orientação de urgência", ultimo("5521999990000"), lambda t: "192" in t)
confere("alerta de urgência", bool(banco.um("SELECT id FROM alertas WHERE tipo='urgencia'")), True)

print("6. Sessão expira em 24 h")
velho = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
banco.executar("UPDATE wa_sessoes SET atualizado_em=? WHERE numero=?", velho, cw._chave_numero(GREGORY))
confere("pede de novo", msg(GREGORY, "oi"), "triagem iniciada")

print("7. Bloqueios do canal")
confere("aviso sem link", avisos.classificar("Há uma nova mensagem da clínica para você: " + avisos.AVISO_CONVERSA)[0], "aviso")
try:
    avisos.enviar_triagem(COLEGA, "Seu potássio está alto")
    confere("texto livre na triagem", "passou", "bloqueado")
except ValueError:
    confere("texto livre na triagem", "bloqueado", "bloqueado")

confere("regex: sem pontuação", cw.extrair_cpf("CPF 00000000515."), "00000000515")
confere("regex: com espaços", cw.extrair_cpf("000 000 005 15"), "00000000515")
confere("sequência repetida é inválida", cw.cpf_valido("11111111111"), False)
confere("CPF some da pergunta", cw.remover_cpfs("meu cpf é " + cpf_ficticio("P05") + ", tel 51 99000-0001"),
        "meu cpf é [CPF removido], tel 51 99000-0001")
print("8. Menu: dúvidas com resposta na hora primeiro")
import json as _json  # noqa: E402
import nucleo as _n  # noqa: E402
pub_mista = {"duvidas_liberadas": 1, "duvidas_json": _json.dumps([
    {"pergunta": "É grave?", "resposta": _n.RESPOSTA_CAUSA},
    {"pergunta": "O que é LDL?", "resposta": "Um tipo de gordura do sangue."},
    {"pergunta": "Vai piorar?", "resposta": "Isso será avaliado pelo médico na consulta."},
    {"pergunta": "O que é HDL?", "resposta": "Outro tipo de gordura do sangue."}])}
capturado = {}
_original = avisos.enviar_interativo
avisos.enviar_interativo = lambda pac, inter, resumo: capturado.update(inter=inter)
cw.enviar_menu({"id": "P05", "telefone": COLEGA}, pub_mista)
avisos.enviar_interativo = _original
secoes = capturado["inter"]["action"]["sections"]
confere("seções na ordem", [s["title"] for s in secoes], ["Resposta na hora", "Para ver na consulta", "Outras opções"])
confere("na hora, com o id original", [r["id"] for r in secoes[0]["rows"]], ["duv:1", "duv:3"])
confere("consulta por último", [r["id"] for r in secoes[1]["rows"]], ["duv:0", "duv:2"])
confere("total de linhas ≤ 10", sum(len(s["rows"]) for s in secoes) <= 10, True)

print("9. Dúvida para a consulta → enviar à equipe")
banco.executar("UPDATE publicacoes SET duvidas_json=? WHERE paciente_id='P05'", pub_mista["duvidas_json"])
msg(COLEGA, "oi")
msg(COLEGA, cpf_ficticio("P05"))
msg(COLEGA, "05/05/1990")
toque(COLEGA, "termo:sim")
confere("dúvida na hora: sem oferta", toque(COLEGA, "duv:1"), "dúvida aprovada respondida")
confere("dúvida para a consulta: oferece a equipe", toque(COLEGA, "duv:0"),
        "dúvida para a consulta; ofereceu enviar à equipe")
confere("botões da oferta", ultimo("P05"), "[botões] Enviar à equipe?")
r = toque(COLEGA, "equipe:0")
confere("entra na fila", r.startswith("enviada à equipe") and "já estava" not in r, True)
f = banco.um("SELECT * FROM fila ORDER BY id DESC LIMIT 1")
confere("fila: tipo c, médico, aguardando", (f["tipo"], f["destino_sugerido"], f["status"], f["pergunta"]),
        ("c", "medico", "aguardando", "É grave?"))
confere("paciente avisado", bool(banco.um("SELECT id FROM avisos WHERE paciente_id='P05' AND texto LIKE 'Sua pergunta foi encaminhada%'")), True)
confere("2º toque não duplica", "já estava" in toque(COLEGA, "equipe:0"), True)
confere("uma só na fila", banco.um("SELECT count(*) n FROM fila WHERE pergunta='É grave?'")["n"], 1)

print("10. Vários exames")
from app import leitura  # noqa: E402
banco.executar("INSERT INTO laudos VALUES (?,?,?,?)", "L-P05", "P05", _json.dumps({"exame": "Check-up", "itens": [
    {"analito": "Hemoglobina", "valor": 13, "unidade": "g/dL", "ref_min": 12, "ref_max": 16, "apelidos": ["hemoglobina"]}]}), banco.agora())
banco.executar("INSERT INTO laudos VALUES (?,?,?,?)", "L2-P05", "P05", _json.dumps({"exame": "Perfil lipídico", "itens": [
    {"analito": "Colesterol LDL", "valor": 168, "unidade": "mg/dL", "ref_max": 130, "apelidos": ["ldl", "colesterol ruim", "colesterol"]}]}), banco.agora())
banco.executar("INSERT INTO publicacoes (laudo_id, paciente_id, token, exame, explicacao, duvidas_json, duvidas_liberadas, "
               "revisor, publicado_em) VALUES (?,?,?,?,?,?,?,?,?)", "L2-P05", "P05", "tok-L2", "Perfil lipídico",
               "Explicação do perfil lipídico.", "[]", 1, "teste", "2026-10-02T10:00:00")
confere("oi com 2 exames → lista", msg(COLEGA, "oi"), "lista de exames")
confere("lista enviada", ultimo("P05").startswith("[exames] Você tem 2 exames"), True)
confere("escolhe o perfil", toque(COLEGA, "exame:L2-P05"), "exame ativo: L2-P05")
confere("exame de outro paciente é recusado", toque(COLEGA, "exame:L-P02"), "exame não encontrado")
toque(COLEGA, "exame:L-P05")
confere("pergunta sobre o outro exame", msg(COLEGA, "e o meu colesterol, melhorou?"), "pergunta sobre outro exame")
confere("continuar aqui responde a pendente", toque(COLEGA, "pergunta:continuar"), "dúvida tipo a")
confere("pergunta do próprio exame vai direto", msg(COLEGA, "a hemoglobina está boa?"), "dúvida tipo a")
confere("menu tem 'Meus exames'", toque(COLEGA, "menu:exames"), "lista de exames")

print("11. Enviar um laudo (leitura simulada, sem LLM)")
lido = {}
leitura.extrair_texto = lambda caminho, mime: (lido["texto"], 91.0, "OCR (foto)")
leitura.estruturar = lambda texto: lido["json"]
leitura.PASTA = os.path.join(tempfile.mkdtemp(), "envios")
gerados = []
proc = lambda pid, laudo: gerados.append((pid, laudo))  # noqa: E731
PROC_LAUDO[0] = proc
foto = {"mime": "image/jpeg", "nome": "laudo.jpg", "conteudo": b"foto"}
confere("pede o arquivo", toque(COLEGA, "enviar:laudo"), "aguardando anexo")
confere("pedido por texto", msg(COLEGA, "Quero mandar um novo laudo"), "aguardando anexo")
confere("'meus exames' por texto", msg(COLEGA, "quero ver meus exames"), "lista de exames")
confere("dúvida comum não vira envio", msg(COLEGA, "o que é um laudo?"), "dúvida tipo a")
confere("áudio é recusado", cw.receber_anexo(f"a{n_msg}", COLEGA, {"mime": "audio/ogg", "conteudo": b"x"}, proc), "tipo de arquivo não aceito")
lido.update(texto="Paciente: Paciente Ficticio 05\nGlicose em jejum 126 mg/dL VR 70 a 99\nHemoglobina glicada 6,1 % VR ate 5,6",
            json={"tipo": "laboratorio", "exame": "Glicose e hemoglobina glicada", "paciente": "Paciente Fictício 05",
                  "itens": [{"analito": "Glicose em jejum", "valor": 126, "unidade": "mg/dL", "ref_min": 70, "ref_max": 99},
                            {"analito": "Hemoglobina glicada", "valor": 6.1, "unidade": "%", "ref_max": 5.6}]})
confere("foto legível → resumo direto, sem conferência", cw.receber_anexo("f1", COLEGA, foto, proc), "resumo imediato enviado; em revisão")
e = banco.um("SELECT * FROM envios ORDER BY id DESC LIMIT 1")
confere("nenhuma pergunta de conferência", banco.um("SELECT id FROM avisos WHERE texto LIKE 'Li estes resultados%'"), None)
resumo = banco.um("SELECT texto FROM avisos WHERE texto LIKE '*Glicose e hemoglobina glicada*%' ORDER BY id DESC LIMIT 1")["texto"]
confere("resumo: acima da faixa do laudo", "126 mg/dL — acima da faixa do laudo (70 a 99 mg/dL)" in resumo or
        "126 mg/dL — acima da faixa do laudo" in resumo, True)
confere("resumo: sem diagnóstico", "não é, sozinho, um diagnóstico" in resumo, True)
confere("rascunho para o painel", (gerados[-1][0], gerados[-1][1]["id"], gerados[-1][1]["_envio"]["conferido_pelo_paciente"]),
        ("P05", f"E{e['id']:03d}", False))
confere("painel sabe que não houve conferência", gerados[-1][1]["_envio"]["resumo_enviado"], True)
confere("termina com navegação", ultimo("P05"), "[botões] O que você quer fazer agora?")
confere("botão antigo de conferência não reprocessa", toque(COLEGA, f"envio:ok:{e['id']}"), "envio já tratado")

lido.update(json={"tipo": "laboratorio", "exame": "Glicose e hemoglobina glicada", "paciente": "Paciente Fictício 05",
                  "itens": [{"analito": "Glicose em jejum", "valor": 6.1, "unidade": "mg/dL", "ref_min": 70, "ref_max": 99},
                            {"analito": "Hemoglobina glicada", "valor": 126, "unidade": "%", "ref_max": 5.6}]})
confere("valores trocados entre itens são pegos", cw.receber_anexo("f1b", COLEGA, foto, proc), "ilegível; pediu outra foto")
banco.executar("UPDATE envios SET status='descartado_teste' WHERE status='ilegivel'")  # não conta para a próxima tentativa

lido.update(json={"tipo": "laboratorio", "exame": "Glicose", "paciente": "Paciente Fictício 05",
                  "itens": [{"analito": "Glicose em jejum", "valor": 728, "unidade": "mg/dL", "ref_min": 70, "ref_max": 99}]})
confere("número que não está no texto é descartado", cw.receber_anexo("f2", COLEGA, foto, proc), "ilegível; pediu outra foto")
confere("2ª foto ilegível → equipe", cw.receber_anexo("f3", COLEGA, foto, proc), "ilegível; encaminhado à equipe")
confere("alerta de envio no painel", bool(banco.um("SELECT id FROM alertas WHERE tipo='envio'")), True)

lido.update(texto="Paciente: Maria Souza\nPotassio 6,8 mEq/L VR 3,5 a 5,1",
            json={"tipo": "laboratorio", "exame": "Potássio", "paciente": "Maria Souza",
                  "itens": [{"analito": "Potássio", "valor": 6.8, "unidade": "mEq/L", "ref_min": 3.5, "ref_max": 5.1}]})
confere("laudo de outra pessoa", cw.receber_anexo("f4", COLEGA, foto, proc), "laudo de outra pessoa")
confere("arquivo apagado", banco.um("SELECT arquivo FROM envios ORDER BY id DESC LIMIT 1")["arquivo"], None)

lido.update(texto="Paciente Ficticio 05\nPotassio 6,8 mEq/L VR 3,5 a 5,1",
            json={"tipo": "laboratorio", "exame": "Potássio", "paciente": "Paciente Fictício 05",
                  "itens": [{"analito": "Potássio", "valor": 6.8, "unidade": "mEq/L", "ref_min": 3.5, "ref_max": 5.1}]})
r = cw.receber_anexo("f5", COLEGA, foto, proc)
e = banco.um("SELECT * FROM envios ORDER BY id DESC LIMIT 1")
confere("crítico: equipe avisada já na leitura", bool(banco.um("SELECT id FROM alertas WHERE tipo='contato_ativo' AND referencia=?", f"envio:{e['id']}")), True)
confere("crítico: resumo direto", r, "resumo imediato enviado; em revisão")
confere("crítico: frase de contato antes do resumo", bool(banco.um("SELECT id FROM avisos WHERE paciente_id='P05' AND texto LIKE 'Há um resultado que precisa de atenção rápida%'")), True)

lido.update(texto="Paciente Ficticio 05\nULTRASSONOGRAFIA DE TIREOIDE\nNodulo solido de 0,6 cm no lobo direito. Linfonodos sem alteracoes.",
            json={"tipo": "imagem", "exame": "Ultrassonografia de tireoide", "paciente": "Paciente Fictício 05"})
confere("laudo de imagem: direto para revisão", cw.receber_anexo("f6", COLEGA, foto, proc), "resumo imediato enviado; em revisão")
confere("imagem: resumo só com definições", "precisa ser explicado por um profissional" in
        banco.um("SELECT texto FROM avisos WHERE texto LIKE '*Ultrassonografia de tireoide*%' ORDER BY id DESC LIMIT 1")["texto"], True)

print("12. Leitura: decimais e nome (falhas achadas na avaliação de fotos)")
confere("6.8 não vira 68", sorted(leitura._leituras("6.8")), [6.8])
confere("265.000 pode ser milhar", 265000.0 in leitura._leituras("265.000"), True)
confere("nome sem sexo/idade", leitura.mesmo_nome("Paciente Fictício 06 • Sexo: M • Idade: 68 anos", "Paciente Fictício 06"), True)
confere("nome com * do OCR", leitura.mesmo_nome("Paciente Ficticio 06 * Sexo: M", "Paciente Fictício 06"), True)
confere("outro paciente continua recusado", leitura.mesmo_nome("Paciente Fictício 05", "Paciente Fictício 06"), False)

confere("faixa invertida pela LLM é pega", leitura.faixa_coerente({"ref_max": 40}, "HDL 52 mg/dL a partir de 40"), False)
confere("6.8 lido como 68 é implausível", leitura.plausivel({"valor": 68, "ref_min": 3.5, "ref_max": 5.1}), False)
lido.update(texto="Paciente Ficticio 05\nPotassio 68 mEq/L 3.5 a 5.1",
            json={"tipo": "laboratorio", "exame": "Potássio", "paciente": "Fictício 05",
                  "itens": [{"analito": "Potássio", "valor": 68, "unidade": "mEq/L", "ref_min": 3.5, "ref_max": 5.1}]})
confere("valor implausível → equipe, sem resumo", cw.receber_anexo("f7", COLEGA, foto, proc), "valor muito fora da faixa; encaminhado à equipe")

confere("linha com trecho ilegível não segue", leitura.conferir({"tipo": "laboratorio", "itens": [{"analito": "Potássio", "valor": 68,
        "unidade": "mEq/L"}]}, "Potássio 68 [ilegível] [ilegível]")[1], ["Potássio (linha com trecho ilegível)"])

confere("wa_id sem o 9 ganha o 9", avisos.numero_envio("555190000001"), "5551990000001")
confere("número completo não muda", avisos.numero_envio("+55 51 99000-0002"), "5551990000002")
confere("fixo não ganha 9", avisos.numero_envio("555133334444"), "555133334444")

print(f"\n{'TUDO OK' if not falhas else 'FALHAS: ' + ', '.join(falhas)}")
sys.exit(1 if falhas else 0)
