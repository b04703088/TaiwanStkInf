# 常客分點：張數 × 期間平均收盤價 → 金額（億元）；來回損益 = 反向張數 × (出場期間均價 − 進場期間均價)
import csv, sys, statistics as st
from collections import defaultdict
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
rows=A.rd('research/data/cb_brokers.csv'); cases={c['id']:c for c in A.rd('data/cb/cases.csv')}
td,close,_=A.load_px({c['code'] for c in cases.values()})
by=defaultdict(lambda: defaultdict(dict)); wd=defaultdict(dict)
for r in rows:
    wd[r['id']][r['win']]=(r['d1'],r['d2'])
    if r['bid']: by[r['id']][r['win']][(r['side'],r['broker'])]=int(r['net'])
def avgp(code,w):
    d1,d2=w; v=[p for d,p in close[code].items() if d1<=d<=d2]
    return st.mean(v) if v else None
out=[]
for name,side in [('元大-松江','B'),('凱基-興隆','B'),('兆豐-復興','B'),('台新','S'),('光和-溪湖','S'),('合庫-高雄','S')]:
    seen=set(); amts=[]; pnl=0; rt=0; det=[]
    for i in sorted(by,key=lambda i:cases[i]['bb_start']):
        v=by[i]['pre20'].get((side,name))
        if v is None or (v>0)!=(side=='B'): continue
        c=cases[i]; key=(c['code'],c['bb_start'][:7])
        if key in seen: continue
        seen.add(key)
        p0=avgp(c['code'],wd[i]['pre20'])
        if not p0: continue
        amt=abs(v)*p0*1000; amts.append(amt)
        # 反向出場：in + post 的反向張數，最多到進場張數
        g=0
        for w in ('in','post'):
            n=by[i][w].get(('S' if side=='B' else 'B',name),0)
            if w in wd[i] and ((side=='B' and n<0) or (side=='S' and n>0)):
                q=min(abs(n),abs(v)); p1=avgp(c['code'],wd[i][w])
                if p1: g+= q*(p1-p0)*1000*(1 if side=='B' else -1); rt+=1 if w else 0
        pnl+=g
        det.append((c['bb_start'],c['code'],c['company'][:4],v,amt/1e6,g/1e6))
    print(f"== {name} {side} 件{len(amts)} 合計{sum(amts)/1e8:.2f}億 中位{st.median(amts)/1e6:.0f}百萬 最大{max(amts)/1e6:.0f}百萬 來回損益合計{pnl/1e6:+.1f}百萬")
    for d in det[-6:]: print('   ',d[0],d[1],d[2],f"{d[3]:+}張 {d[4]:.1f}百萬 損益{d[5]:+.1f}百萬")
