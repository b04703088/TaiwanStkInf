# 董事會決議前 20 日：哪些分點特別常進買超／賣超前 15 名（對照 = T0 前 100～81 日 plc2，同樣 20 日長）
import sys
from collections import defaultdict
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
rows=A.rd('research/data/cb_brokers.csv'); cases={c['id']:c for c in A.rd('data/cb/cases.csv')}
ev={}; have=defaultdict(set); hit=defaultdict(lambda: defaultdict(set))
for r in rows:
    c=cases[r['id']]; k=(c['code'],c['board_date'] or c['bb_start'][:7]); ev[r['id']]=k
    have[r['win']].add(k)
    if r['bid'] and r['win'] in ('s0','plc2'):
        n=int(r['net'])
        if (r['side']=='B' and n>0) or (r['side']=='S' and n<0):
            hit[(r['broker'],r['side'])][r['win']].add(k)
N0,NP=len(have['s0']),len(have['plc2']); print('事件',N0,NP)
out=[]
for (b,s),h in hit.items():
    n=len(h['s0']); 
    if n<4: continue
    p0=max(len(h['plc2'])/NP,0.5/NP)
    out.append((A.binom_sf(n,N0,p0),b,s,n,len(h['plc2']),round(n/N0/p0,1)))
out.sort(); M=len(out)
for p,b,s,n,np_,lift in out[:20]: print(f"{b} {s} 決議前{n} 對照{np_} 倍數{lift} p={p} 校正{min(1,p*M):.3g}")
