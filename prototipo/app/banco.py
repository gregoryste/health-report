"""Banco do protótipo (SQLite em prototipo/dados/prototipo.db). Só dados fictícios."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.environ.get("BANCO", os.path.join(AQUI, "dados", "prototipo.db"))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pacientes (
  id TEXT PRIMARY KEY, nome TEXT, nascimento TEXT, telefone TEXT);
CREATE TABLE IF NOT EXISTS laudos (
  id TEXT PRIMARY KEY, paciente_id TEXT, json TEXT, recebido_em TEXT);
CREATE TABLE IF NOT EXISTS rascunhos (
  rascunho_id TEXT PRIMARY KEY, laudo_id TEXT, json TEXT, status TEXT, prioridade TEXT, prazo TEXT,
  criado_em TEXT, aberto_em TEXT);
CREATE TABLE IF NOT EXISTS publicacoes (
  laudo_id TEXT PRIMARY KEY, paciente_id TEXT, token TEXT UNIQUE, exame TEXT, explicacao TEXT, duvidas_json TEXT,
  duvidas_liberadas INTEGER, revisor TEXT, publicado_em TEXT, lido_em TEXT, lembretes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS codigos (
  token TEXT PRIMARY KEY, codigo TEXT, expira_em TEXT, tentativas INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS usuarios (
  login TEXT PRIMARY KEY, nome TEXT, funcao TEXT, senha_hash TEXT, ativo INTEGER DEFAULT 1, criado_em TEXT, ultimo_acesso TEXT);
CREATE TABLE IF NOT EXISTS sessoes (
  sessao TEXT PRIMARY KEY, papel TEXT, token TEXT, nome TEXT, visto_em TEXT);
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, autor TEXT, texto TEXT, tipo TEXT, fila_id INTEGER, criado_em TEXT);
CREATE TABLE IF NOT EXISTS fila (
  id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, pergunta TEXT, tipo TEXT, destino_sugerido TEXT,
  destino_final TEXT, prioridade TEXT, motivo TEXT, rascunho TEXT, fontes TEXT, status TEXT,
  resposta_final TEXT, respondido_por TEXT, criado_em TEXT, respondido_em TEXT);
CREATE TABLE IF NOT EXISTS avisos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paciente_id TEXT, telefone TEXT, texto TEXT, canal TEXT, status TEXT,
  detalhe TEXT, criado_em TEXT);
CREATE TABLE IF NOT EXISTS consentimentos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paciente_id TEXT, canal TEXT, versao TEXT, aceito_em TEXT, revogado_em TEXT,
  explicacao_enviada_em TEXT);
CREATE TABLE IF NOT EXISTS wa_recebidas (
  id TEXT PRIMARY KEY, telefone TEXT, texto TEXT, recebido_em TEXT);
CREATE TABLE IF NOT EXISTS wa_sessoes (
  numero TEXT PRIMARY KEY, estado TEXT, cpf_hash TEXT, paciente_id TEXT, tentativas INTEGER DEFAULT 0,
  bloqueado_ate TEXT, verificado_em TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS envios (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paciente_id TEXT, numero TEXT, arquivo TEXT, mime TEXT, nome_arquivo TEXT,
  texto TEXT, confianca REAL, laudo_json TEXT, status TEXT, tentativas INTEGER DEFAULT 0, correcao TEXT, laudo_id TEXT,
  criado_em TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS alertas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, descricao TEXT, paciente_id TEXT, referencia TEXT,
  status TEXT, criado_em TEXT, resolvido_por TEXT, resolvido_em TEXT);
"""


def agora():
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conexao():
    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    con = sqlite3.connect(ARQUIVO)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar():
    with conexao() as con:
        con.executescript(ESQUEMA)
        colunas = {r[1] for r in con.execute("PRAGMA table_info(pacientes)")}
        if "cpf" not in colunas:  # triagem pelo WhatsApp (14/11): CPF fictício + data de nascimento
            con.execute("ALTER TABLE pacientes ADD COLUMN cpf TEXT")
        if "ultimo_acesso" not in {r[1] for r in con.execute("PRAGMA table_info(usuarios)")}:  # 14/11
            con.execute("ALTER TABLE usuarios ADD COLUMN ultimo_acesso TEXT")
        sessao = {r[1] for r in con.execute("PRAGMA table_info(wa_sessoes)")}
        for col in ("laudo_ativo", "etapa", "envio_id", "pendente"):  # vários exames e envio de laudo (14/11)
            if col not in sessao:
                con.execute(f"ALTER TABLE wa_sessoes ADD COLUMN {col} TEXT")


def um(sql, *args):
    with conexao() as con:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else None


def todos(sql, *args):
    with conexao() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def executar(sql, *args):
    with conexao() as con:
        cur = con.execute(sql, args)
        return cur.lastrowid


def j(texto, padrao=None):
    return json.loads(texto) if texto else padrao
