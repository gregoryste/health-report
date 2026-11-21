"""Contas do painel da equipe: usuário e senha individuais, com função.

Funções: médico(a), enfermagem e administrador(a). Hoje as três veem e fazem o mesmo no painel clínico;
só a administração vê a aba "Equipe e acessos" (todas as contas e funções) e gerencia as contas.

A senha nunca é guardada: só o hash PBKDF2-SHA256 com sal aleatório, no banco do protótipo.
Cinco tentativas erradas seguidas bloqueiam o usuário por 5 minutos (na memória do serviço).
Sempre sobra pelo menos uma conta de administração ativa.

Uso (de dentro de prototipo/, com o venv):
  .venv/bin/python -m app.usuarios criar --login admin --nome "Gregory Stein" --funcao admin
  .venv/bin/python -m app.usuarios criar --login helena --nome "Dra. Helena Souza" --funcao medico
  .venv/bin/python -m app.usuarios listar
  .venv/bin/python -m app.usuarios senha --login helena                 # troca a senha
  .venv/bin/python -m app.usuarios funcao --login helena --funcao admin  # troca a função
  .venv/bin/python -m app.usuarios desativar --login helena
  .venv/bin/python -m app.usuarios ativar --login helena
A senha é digitada no terminal (não aparece na tela nem fica no histórico).
"""
import argparse
import getpass
import hashlib
import hmac
import re
import secrets
import sys
import time

from . import banco

FUNCOES = {"medico": "Médico(a)", "enfermagem": "Enfermagem", "admin": "Administrador(a)"}
DESCRICOES = {
    "admin": "Tudo o que a equipe faz, mais a aba Equipe e acessos: vê todas as contas e funções, cria contas, "
             "troca função e senha, ativa e desativa.",
    "medico": "Revisa e aprova explicações, responde a fila de triagem (ato médico), resolve alertas.",
    "enfermagem": "Revisa e aprova explicações, responde a fila no que é cuidado e encaminha ao médico o que é ato médico.",
}
ITERACOES = 240_000
MIN_SENHA = 8
TENTATIVAS, BLOQUEIO_S = 5, 300
_falhas = {}  # login -> (quantidade, bloqueado_até)


def gerar_hash(senha):
    sal = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES)
    return f"pbkdf2_sha256${ITERACOES}${sal.hex()}${h.hex()}"


def confere(senha, guardado):
    try:
        _, it, sal, h = guardado.split("$")
        novo = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(novo.hex(), h)
    except (ValueError, AttributeError):
        return False


_FALSO = gerar_hash("sem-usuario")


def bloqueado(login):
    return _falhas.get(login, (0, 0))[1] > time.time()


def autenticar(login, senha):
    """Devolve (usuario, erro). erro: None, 'invalido' ou 'bloqueado'."""
    login = (login or "").strip().lower()
    if bloqueado(login):
        return None, "bloqueado"
    u = banco.um("SELECT * FROM usuarios WHERE login=? AND ativo=1", login)
    # confere mesmo sem usuário, para o tempo de resposta não revelar quais logins existem
    ok = confere(senha or "", u["senha_hash"] if u else _FALSO)
    if u and ok:
        _falhas.pop(login, None)
        banco.executar("UPDATE usuarios SET ultimo_acesso=? WHERE login=?", banco.agora(), login)
        return u, None
    n = _falhas.get(login, (0, 0))[0] + 1
    _falhas[login] = (n, time.time() + BLOQUEIO_S if n >= TENTATIVAS else 0)
    return None, "bloqueado" if n >= TENTATIVAS else "invalido"


def existe_algum():
    return bool(banco.um("SELECT 1 x FROM usuarios WHERE ativo=1 LIMIT 1"))


def eh_admin(login):
    return bool(banco.um("SELECT 1 x FROM usuarios WHERE login=? AND ativo=1 AND funcao='admin'", login or ""))


# ------------------------------------------------------------------ operações (terminal e aba Equipe e acessos)
# Cada uma devolve uma frase de sucesso ou levanta ValueError com a frase do problema.

def _conta(login):
    u = banco.um("SELECT * FROM usuarios WHERE login=?", (login or "").strip().lower())
    if not u:
        raise ValueError(f"Não existe a conta '{login}'.")
    return u


def _sobra_admin(login_saindo):
    """Impede ficar sem nenhuma conta de administração ativa."""
    outros = banco.um("SELECT COUNT(*) c FROM usuarios WHERE funcao='admin' AND ativo=1 AND login<>?", login_saindo)["c"]
    if not outros:
        raise ValueError("Esta é a única conta de administração ativa. Crie ou ative outra antes.")


def _valida_senha(senha):
    if len(senha or "") < MIN_SENHA:
        raise ValueError(f"A senha precisa de pelo menos {MIN_SENHA} caracteres.")


def _derruba_sessoes(login):
    banco.executar("DELETE FROM sessoes WHERE papel='equipe' AND token=?", login)


def criar(login, nome, funcao, senha):
    login, nome = (login or "").strip().lower(), (nome or "").strip()
    if not re.fullmatch(r"[a-z0-9._-]{3,32}", login):
        raise ValueError("Login: 3 a 32 caracteres, só letras minúsculas, números, ponto, hífen e sublinhado.")
    if not nome:
        raise ValueError("Informe o nome que aparece no painel.")
    if funcao not in FUNCOES:
        raise ValueError("Função inválida.")
    _valida_senha(senha)
    if banco.um("SELECT 1 x FROM usuarios WHERE login=?", login):
        raise ValueError(f"Já existe a conta '{login}'.")
    banco.executar("INSERT INTO usuarios (login, nome, funcao, senha_hash, ativo, criado_em) VALUES (?,?,?,?,1,?)",
                   login, nome, funcao, gerar_hash(senha), banco.agora())
    return f"Conta '{login}' criada ({FUNCOES[funcao]})."


def trocar_senha(login, senha):
    u = _conta(login)
    _valida_senha(senha)
    banco.executar("UPDATE usuarios SET senha_hash=? WHERE login=?", gerar_hash(senha), u["login"])
    _derruba_sessoes(u["login"])
    _falhas.pop(u["login"], None)
    return f"Senha de '{u['login']}' trocada; as sessões abertas dessa conta foram encerradas."


def trocar_funcao(login, funcao):
    u = _conta(login)
    if funcao not in FUNCOES:
        raise ValueError("Função inválida.")
    if u["funcao"] == "admin" and funcao != "admin" and u["ativo"]:
        _sobra_admin(u["login"])
    banco.executar("UPDATE usuarios SET funcao=? WHERE login=?", funcao, u["login"])
    return f"'{u['login']}' agora é {FUNCOES[funcao]}."


def definir_ativo(login, ativo):
    u = _conta(login)
    if not ativo:
        if u["funcao"] == "admin" and u["ativo"]:
            _sobra_admin(u["login"])
        _derruba_sessoes(u["login"])
    banco.executar("UPDATE usuarios SET ativo=? WHERE login=?", int(bool(ativo)), u["login"])
    return f"Conta '{u['login']}' {'reativada' if ativo else 'desativada'}."


def listar():
    return banco.todos("SELECT login, nome, funcao, ativo, criado_em, ultimo_acesso FROM usuarios "
                       "ORDER BY ativo DESC, CASE funcao WHEN 'admin' THEN 0 WHEN 'medico' THEN 1 ELSE 2 END, nome")


# ------------------------------------------------------------------ linha de comando

def _pedir_senha():
    for _ in range(3):
        s1 = getpass.getpass(f"Senha (mínimo {MIN_SENHA} caracteres): ")
        if len(s1) < MIN_SENHA:
            print("Senha curta demais.")
            continue
        if getpass.getpass("Repita a senha: ") != s1:
            print("As senhas não conferem.")
            continue
        return s1
    sys.exit("Desisti depois de 3 tentativas.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar", help="cria uma conta")
    c.add_argument("--login", required=True)
    c.add_argument("--nome", required=True, help="nome que aparece no painel e no registro")
    c.add_argument("--funcao", required=True, choices=FUNCOES)
    sub.add_parser("listar", help="lista as contas")
    f = sub.add_parser("funcao", help="troca a função de uma conta")
    f.add_argument("--login", required=True)
    f.add_argument("--funcao", required=True, choices=FUNCOES)
    for nome in ("senha", "desativar", "ativar"):
        sub.add_parser(nome).add_argument("--login", required=True)
    a = ap.parse_args()
    banco.iniciar()
    try:
        if a.cmd == "listar":
            for u in listar():
                print(f"{u['login']:<16} {u['nome']:<28} {FUNCOES.get(u['funcao'], u['funcao']):<17} "
                      f"{'ativa' if u['ativo'] else 'DESATIVADA':<11} criada em {u['criado_em'][:10]}")
            return
        if a.cmd == "criar":
            if banco.um("SELECT 1 x FROM usuarios WHERE login=?", a.login.strip().lower()):
                sys.exit(f"Já existe a conta '{a.login}'. Para trocar a senha: python -m app.usuarios senha --login {a.login}")
            print(criar(a.login, a.nome, a.funcao, _pedir_senha()))
        elif a.cmd == "senha":
            _conta(a.login)
            print(trocar_senha(a.login, _pedir_senha()))
        elif a.cmd == "funcao":
            print(trocar_funcao(a.login, a.funcao))
        else:
            print(definir_ativo(a.login, a.cmd == "ativar"))
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
