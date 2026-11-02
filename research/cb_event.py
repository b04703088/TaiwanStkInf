# 日報酬事件研究：T0（詢圈開始）前後與基準日前後的平均累積超額報酬（減 0050）
import csv, sys, statistics as st
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
cases=[c for c in A.rd('data/cb/cases.csv') if c['method'] in('詢價圈購','競價拍賣') and c['bb_start'] and c['bb_start']<='2026-10-01']
td,close,vol=A.load_px({c['code'] for c in cases}|{'0050'})
pos={d:k for k,d in enumerate(td)}
def idx(d):
    return next((k for k,x in enumerate(td) if x>=d),None)
for m in ['詢價圈購','競價拍賣']:
    paths=[]
    for c in cases:
        if c['method']!=m: continue
        i=idx(c['bb_start'])
        if i is None or i<25 or i+40>=len(td): continue
        cl=close[c['code']]; b=close['0050']
        ref=td[i-21]
        if ref not in cl: continue
        p=[]
        for k in range(-20,41):
            d=td[i+k]
            if d in cl and d in b and ref in b: p.append(cl[d]/cl[ref]-b[d]/b[ref])
            else: p.append(None)
        paths.append(p)
    print(m,len(paths))
    for k in [-20,-15,-10,-5,-1,0,2,4,6,8,10,15,20,30,40]:
        v=[p[k+20] for p in paths if p[k+20] is not None]
        print(f'  T0{k:+d}: CAR {st.mean(v)*100:+.1f}% med {st.median(v)*100:+.1f}%')
