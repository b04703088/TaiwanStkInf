# 以 CB 流程階段（實際日期）取代 T0+k：各階段相對「詢圈開始前 21 個交易日」的累積超額報酬（扣 0050）中位數
import csv, sys, statistics as st, bisect
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
cases=[c for c in A.rd('data/cb/cases.csv') if c['method'] in('詢價圈購','競價拍賣') and c['bb_start']]
td,close,_=A.load_px({c['code'] for c in cases}|{'0050'})
def k_of(d):  # 該日或之後第一個交易日
    return bisect.bisect_left(td,d)
STAGES=[('board_date','董事會決議'),('filed_date','送件申報'),('eff_date','申報生效'),('pre20','詢圈前 20 日'),
        ('bb_start','詢圈／競拍開始'),('bb_end','詢圈／競拍結束'),('done_date','訂價日'),('price_base_date','轉換價格基準日'),
        ('pay_date','繳款截止'),('list_date','掛牌'),('list20','掛牌後 20 日'),('list40','掛牌後 40 日')]
for m in ['詢價圈購','競價拍賣']:
    res={s:[] for s,_ in STAGES}; off={s:[] for s,_ in STAGES}
    n=0
    for c in cases:
        if c['method']!=m: continue
        i=k_of(c['bb_start'])
        if i<21 or i>=len(td): continue
        ref=td[i-21]; cl=close[c['code']]; b=close['0050']
        if ref not in cl: continue
        n+=1
        for s,_ in STAGES:
            if s=='pre20': k=i-20
            elif s.startswith('list') and s!='list_date':
                if not c['list_date']: continue
                k=k_of(c['list_date'])+int(s[4:])
            else:
                if not c.get(s): continue
                k=k_of(c[s])
            if k>=len(td) or k<0: continue
            d=td[k]
            if d in cl and d in b and ref in b:
                res[s].append(cl[d]/cl[ref]-b[d]/b[ref]); off[s].append(k-i)
    print(m,n)
    for s,lab in STAGES:
        v=res[s]
        if len(v)<10: continue
        print(f"  {lab}\t件{len(v)}\t距詢圈開始 {st.median(off[s]):+.0f} 日\t中位 {st.median(v)*100:+.1f}%\t上漲比 {sum(x>0 for x in v)/len(v)*100:.0f}%")
