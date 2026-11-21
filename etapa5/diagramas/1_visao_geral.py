"""Gera 1_visao_geral.svg (diagrama de arquitetura, posições fixas). Rodar: python3 1_visao_geral.py"""
import html

W, H = 1440, 830
COR = {  # fundo, borda, texto
    "regra": ("#e3f2e1", "#2d6a2f", "#123d14"),
    "ia": ("#dbeafe", "#1e5aa8", "#0b2545"),
    "humano": ("#fde7c8", "#b8650a", "#3a2200"),
    "dado": ("#f1f1f1", "#777777", "#222222"),
    "externo": ("#ffffff", "#999999", "#333333"),
}
out = []


def texto(x, y, linhas, cor="#222", tam=15, peso="normal", ancora="middle", halo=False):
    estilo = "paint-order:stroke;stroke:#fff;stroke-width:5px;stroke-linejoin:round;" if halo else ""
    dy0 = -(len(linhas) - 1) * tam * 0.6
    spans = "".join(f'<tspan x="{x}" dy="{dy0 if i == 0 else tam * 1.2:.1f}">{html.escape(l)}</tspan>'
                    for i, l in enumerate(linhas))
    out.append(f'<text x="{x}" y="{y}" fill="{cor}" font-size="{tam}" font-weight="{peso}" text-anchor="{ancora}" '
               f'dominant-baseline="middle" style="{estilo}">{spans}</text>')


def caixa(x, y, w, h, linhas, tipo, tracejada=False, grossa=False):
    f, b, t = COR[tipo]
    traco = ' stroke-dasharray="5 4"' if tracejada else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{f}" stroke="{b}" '
               f'stroke-width="{2.2 if grossa else 1.4}"{traco}/>')
    texto(x + w / 2, y + h / 2, linhas, cor=t)


def cilindro(x, y, w, h, linhas):
    f, b, t = COR["dado"]
    ry = 10
    out.append(f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0,1 {w},0 v{h - 2 * ry} a{w / 2},{ry} 0 0,1 {-w},0 z" '
               f'fill="{f}" stroke="{b}" stroke-width="1.4"/>')
    out.append(f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0,0 {w},0" fill="none" stroke="{b}" stroke-width="1.4"/>')
    texto(x + w / 2, y + h / 2 + 6, linhas, cor=t)


def grupo(x, y, w, h, titulo):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="none" stroke="#c9ced3" '
               f'stroke-width="1.4" stroke-dasharray="6 5"/>')
    texto(x + 14, y + 20, [titulo], cor="#55606a", tam=14, peso="bold", ancora="start")


def seta(x1, y1, x2, y2, dupla=False, rotulo=None, rx=None, ry=None):
    ini = ' marker-start="url(#ini)"' if dupla else ""
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#555" stroke-width="1.8" '
               f'marker-end="url(#fim)"{ini}/>')
    if rotulo:
        texto(rx if rx is not None else (x1 + x2) / 2, ry if ry is not None else (y1 + y2) / 2, [rotulo],
              cor="#333", tam=13.5, halo=True)


# ---- grupos
grupo(20, 90, 260, 320, "Entrada")
grupo(300, 60, 790, 740, "Infraestrutura própria: nenhum dado de saúde vai para a nuvem")
grupo(1110, 60, 310, 390, "Profissionais (aprovação humana)")
grupo(1110, 480, 310, 320, "Paciente")

# ---- nós
caixa(40, 130, 220, 70, ["Sistema de exames", "da clínica (laudo digital)"], "externo", tracejada=True)
caixa(40, 300, 220, 70, ["Foto do laudo em papel", "(enviada no portal)"], "externo", tracejada=True)
caixa(330, 302, 150, 66, ["OCR local", "(Tesseract)"], "regra")
caixa(400, 110, 250, 84, ["Regra fixa e checagens", "faixas, prioridade, prazos,", "omissão, números, posição"], "regra")
caixa(760, 110, 280, 84, ["LLM interna", "gemma3 12B, pesos abertos", "servidor próprio"], "ia")
# n8n (hexágono)
cx, cy = 700, 405
out.append(f'<polygon points="{cx - 95},{cy} {cx - 70},{cy - 42} {cx + 70},{cy - 42} {cx + 95},{cy} '
           f'{cx + 70},{cy + 42} {cx - 70},{cy + 42}" fill="#e3f2e1" stroke="#2d6a2f" stroke-width="2"/>')
texto(cx, cy, ["n8n", "orquestrador"], cor="#123d14", tam=16, peso="bold")
caixa(320, 610, 250, 110, ["Bases curadas, sem dado pessoal", "glossário aprovado", "exemplos aprovados (E1)",
                           "base da clínica (RAG)"], "dado")
cilindro(610, 610, 240, 110, ["Banco", "laudos, rascunhos, aprovações,", "registro, fila de triagem"])

caixa(1130, 100, 270, 64, ["Tela de aprovação", "(médico)"], "humano", grossa=True)
caixa(1130, 220, 270, 64, ["Fila de triagem", "(enfermagem → médico)"], "humano", grossa=True)
caixa(1130, 340, 270, 64, ["Recepção"], "humano", grossa=True)
caixa(1130, 520, 270, 70, ["Portal com login", "explicação, dúvidas, chat"], "externo", tracejada=True)
caixa(1130, 690, 270, 70, ["WhatsApp", "só aviso genérico"], "externo", tracejada=True)

# ---- setas
seta(260, 175, 622, 380)
seta(260, 335, 330, 335)
seta(480, 345, 605, 400)
seta(560, 194, 665, 363, dupla=True)
seta(880, 194, 740, 363, dupla=True)
seta(470, 610, 650, 447)
seta(715, 610, 705, 447, dupla=True)
seta(795, 392, 1130, 135, dupla=True, rotulo="rascunhos ⇄ aprovação", rx=980, ry=245)
seta(795, 400, 1130, 252, dupla=True, rotulo="dúvidas tipo c ⇄ respostas", rx=1000, ry=318)
seta(795, 408, 1130, 372, rotulo="administrativo", rx=1010, ry=390)
seta(795, 418, 1130, 555, dupla=True, rotulo="só conteúdo aprovado ⇄ dúvidas", rx=985, ry=476)
seta(785, 440, 1130, 722, rotulo="aviso: “há uma nova mensagem” + link", rx=950, ry=600)

# ---- legenda
lx, ly = 330, 765
for i, (tipo, nome) in enumerate([("regra", "regra/código"), ("ia", "IA generativa"), ("humano", "decisão humana"),
                                  ("dado", "dados")]):
    f, b, _ = COR[tipo]
    x = lx + i * 175
    out.append(f'<rect x="{x}" y="{ly - 9}" width="18" height="18" rx="3" fill="{f}" stroke="{b}" stroke-width="1.4"/>')
    texto(x + 26, ly, [nome], cor="#444", tam=13.5, ancora="start")

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
       f'font-family="Helvetica, Arial, sans-serif">'
       '<defs><marker id="fim" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
       '<path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker>'
       '<marker id="ini" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
       '<path d="M10,0 L0,5 L10,10 z" fill="#555"/></marker></defs>'
       f'<rect width="{W}" height="{H}" fill="#fff"/>' + "".join(out) + "</svg>")
open("1_visao_geral.svg", "w", encoding="utf-8").write(svg)
print("1_visao_geral.svg")
