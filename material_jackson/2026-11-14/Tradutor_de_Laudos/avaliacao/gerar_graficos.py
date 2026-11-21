"""Gráficos apenas de avaliações reais. Requer Python 3 e matplotlib.
Uso: python gerar_graficos.py consenso.csv --saida resultados
Exporte a aba Consenso da planilha como CSV, preservando os cabeçalhos.
"""
import argparse,csv,json,pathlib,statistics,math

def status(r):
    binary=['Citou tudo?','Inventou?','Minimizou?','Tom adequado?']
    required=binary+['Leigo entende?','Versão da execução','Data da avaliação']
    if any(not r.get(k,'').strip() for k in required):return 'Pendente'
    for k in binary:
        if r[k] not in ['Sim','Não']:raise ValueError(f"{r['ID']}: valor inválido em {k}")
    if r['Leigo entende?'] not in ['Sim','Em parte','Não']:raise ValueError('Compreensão inválida')
    return 'Aprovado' if all(r[k]==v for k,v in [('Citou tudo?','Sim'),('Inventou?','Não'),('Minimizou?','Não'),('Leigo entende?','Sim'),('Tom adequado?','Sim')]) else 'Reprovado'

def main():
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--saida',default='resultados');args=p.parse_args()
    content=pathlib.Path(args.csv).read_text(encoding='utf-8-sig')
    dialect=csv.Sniffer().sniff(content[:8192],delimiters=',;\t')
    rows=[{k:(v or '').strip() for k,v in r.items()} for r in csv.DictReader(content.splitlines(),dialect=dialect)]
    rows=[r for r in rows if r.get('ID')]
    ids=[r['ID']for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError('IDs duplicados. Uma linha por caso e rodada.')
    expected={f'L{n:02}'for n in range(4,24)}
    if set(ids)!=expected:raise ValueError('O CSV deve conter os 20 IDs L04 a L23, incluindo os pendentes.')
    rounds={r.get('Versão da execução')for r in rows if status(r)!='Pendente'}
    if len(rounds)>1:raise ValueError('Há versões de execução diferentes. Gere um CSV por rodada.')
    done=[r for r in rows if status(r)!='Pendente']
    if not done:raise SystemExit('Nenhuma avaliação concluída. Nenhum gráfico de desempenho foi gerado.')
    approved=sum(status(r)=='Aprovado'for r in done);omissions=sum(r['Citou tudo?']=='Não'for r in done)
    out=pathlib.Path(args.saida);out.mkdir(parents=True,exist_ok=True)
    summary=dict(previstos=20,concluidos=len(done),pendentes=20-len(done),aprovados=approved,reprovados=len(done)-approved,casos_com_omissao=omissions,taxa_aprovacao=approved/len(done),taxa_omissao=omissions/len(done),versao=next(iter(rounds)))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(8,4.8))
    labels=['Aprovados','Reprovados','Com omissão'];values=[approved,len(done)-approved,omissions]
    bars=ax.bar(labels,values,color=['#176C78','#A85942','#D59E4B']);ax.bar_label(bars)
    ax.set_ylim(0,20);ax.set_ylabel('Casos');ax.set_yticks(range(0,21,2))
    ax.set_title(f'Avaliação de {len(done)} casos concluídos ({20-len(done)} pendentes)')
    fig.text(.05,.01,'Omissões são um subconjunto dos reprovados. Não somar as três barras.',fontsize=9)
    fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(out/'01_resultados.png',dpi=180);plt.close(fig)
    pairs=[]
    for r in done:
        a,b=r.get('Palavras/frase antes',''),r.get('Palavras/frase depois','')
        if not a or not b:continue
        a,b=float(a.replace(',','.')),float(b.replace(',','.'))
        if not all(math.isfinite(v) and v>0 for v in [a,b]):raise ValueError('Palavras por frase precisa ser um número positivo.')
        pairs.append((r['ID'],a,b))
    summary['pares_legibilidade']=len(pairs)
    if pairs:
        fig,ax=plt.subplots(figsize=(8,4.8))
        for id,a,b in pairs:ax.plot([0,1],[a,b],color='#A7BAC2',alpha=.7,linewidth=1)
        means=[statistics.mean(r[1]for r in pairs),statistics.mean(r[2]for r in pairs)]
        ax.plot([0,1],means,'o-',color='#176C78',linewidth=3,label='Média dos pares')
        ax.set_xticks([0,1],['Antes','Depois']);ax.set_ylabel('Palavras por frase');ax.set_ylim(bottom=0)
        ax.set_title(f'Complexidade textual em {len(pairs)} pares completos');ax.legend()
        fig.text(.05,.01,'Medida descritiva. Não comprova compreensão ou segurança clínica.',fontsize=9)
        fig.tight_layout(rect=[0,.04,1,1]);fig.savefig(out/'02_linguagem.png',dpi=180);plt.close(fig)
        summary['media_antes'],summary['media_depois']=means
    (out/'resumo.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if not pairs:print('Sem pares completos: o segundo gráfico permanece pendente.')

if __name__=='__main__':main()
