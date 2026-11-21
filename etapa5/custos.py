"""Estimativa de custo (D8). Rodar: python3 custos.py
Todos os parâmetros estão no topo; as fontes e as ressalvas estão em custos.md."""

DOLAR = 5.15                 # R$/US$, 16/09/2026 (último valor encontrado; conferir PTAX na data do artigo)
KWH = 0.945 * 1.30           # R$/kWh: RGE Sul B1/B3 sem impostos (19/06/2026) + ~30% de impostos (estimativa)
ZAP_USD = 0.0068             # US$ por mensagem de utilidade, Brasil, desde 01/10/2026 (fontes secundárias; conferir Meta)
GPU_RS = 27782               # R$, RTX 5090 32 GB, mediana de 12 meses em agregador (a RTX 4090 está esgotada)
AMORTIZACAO_MESES = 36

# Tokens por chamada (medidos nas rodadas de 14/11, estimados por 3,6 caracteres/token; o servidor não informa tokens)
TRADUTOR = (1043, 348)       # entrada, saída
VERIFICADOR = (900, 200)
CLASSIFICADOR = (1150, 40)
RESPONDEDOR = (850, 100)
VERIF_CHAT = (1000, 80)
SEG_TRADUTOR, SEG_CHAMADA_CURTA = 4.1, 2.5     # segundos de GPU por chamada (medido / estimado)

# Pressupostos de uso (do grupo, ajustáveis)
FRACAO_IMAGEM = 0.3          # laudos de imagem recebem a verificação de apoio
PERGUNTAS_POR_LAUDO = 1.0
FRACAO_AB = 0.6              # perguntas respondidas pelo chatbot (a, b); o resto vira c com rascunho
LEMBRETES_POR_LAUDO = 0.3
POTENCIA_KW = 0.6            # GPU sob carga + resto do servidor (estimativa)

CLOUD = {"Claude Haiku 5.5": (0.10, 0.50), "Claude Sonnet 5.5": (2.00, 10.00)}  # US$/milhão de tokens


def por_mes(laudos):
    perg = laudos * PERGUNTAS_POR_LAUDO
    ent = laudos * (TRADUTOR[0] + FRACAO_IMAGEM * VERIFICADOR[0]) + perg * (
        CLASSIFICADOR[0] + FRACAO_AB * (RESPONDEDOR[0] + VERIF_CHAT[0]) + (1 - FRACAO_AB) * RESPONDEDOR[0])
    sai = laudos * (TRADUTOR[1] + FRACAO_IMAGEM * VERIFICADOR[1]) + perg * (
        CLASSIFICADOR[1] + FRACAO_AB * (RESPONDEDOR[1] + VERIF_CHAT[1]) + (1 - FRACAO_AB) * RESPONDEDOR[1])
    seg = laudos * (SEG_TRADUTOR + FRACAO_IMAGEM * SEG_CHAMADA_CURTA) + perg * SEG_CHAMADA_CURTA * (
        1 + FRACAO_AB * 2 + (1 - FRACAO_AB))
    msgs = laudos * (1 + LEMBRETES_POR_LAUDO) + perg * (1 - FRACAO_AB)
    return ent, sai, seg, msgs


def main():
    print(f"Câmbio R$ {DOLAR:.2f} · energia R$ {KWH:.3f}/kWh\n")
    for laudos in (200, 1000):
        ent, sai, seg, msgs = por_mes(laudos)
        kwh = POTENCIA_KW * seg / 3600
        print(f"== {laudos} laudos/mês + {laudos * PERGUNTAS_POR_LAUDO:.0f} perguntas/mês")
        print(f"   tokens: {ent / 1e6:.2f} M de entrada, {sai / 1e6:.2f} M de saída · GPU ocupada {seg / 3600:.2f} h")
        print(f"   LLM interna (energia sob carga): {kwh:.2f} kWh → R$ {kwh * KWH:.2f}/mês")
        for nome, (pi, po) in CLOUD.items():
            usd = ent / 1e6 * pi + sai / 1e6 * po
            print(f"   {nome} em nuvem: US$ {usd:.2f} → R$ {usd * DOLAR:.2f}/mês")
        print(f"   WhatsApp: {msgs:.0f} avisos → US$ {msgs * ZAP_USD:.2f} → R$ {msgs * ZAP_USD * DOLAR:.2f}/mês")
    gpu, mes = f"{GPU_RS:,.0f}".replace(",", "."), f"{GPU_RS / AMORTIZACAO_MESES:,.0f}".replace(",", ".")
    print(f"\nVisão 2 (clínica sem servidor): GPU R$ {gpu} em {AMORTIZACAO_MESES} meses = R$ {mes}/mês, "
          f"sem os demais componentes (a cotar)")


if __name__ == "__main__":
    main()
