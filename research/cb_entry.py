# 常客分點在 CB 流程哪一段進場：董事會→送件(s1)、送件→生效(s2)、生效→詢圈開始(s3)、詢圈開始→訂價日(s4)
import sys, statistics as st
from collections import defaultdict, Counter
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
rows=A.rd('research/data/cb_brokers.csv'); cases={c['id']:c for c in A.rd('data/cb/cases.csv')}
by=defaultdict(lambda: defaultdict(dict)); wd=defaultdict(dict)
for r in rows:
    wd[r['id']][r['win']]=(r['d1'],r['d2'],)
    if r['bid']: by[r['id']][r['win']][(r['side'],r['broker'])]=int(r['net'])
LAB={'s1':'決議→送件','s2':'送件→生效','s3':'生效→詢圈','s4':'詢圈→訂價'}
seg_len={s:[] for s in LAB}
td=A.load_px(set())[0]; pos={d:k for k,d in enumerate(td)}
for i in wd:
    for s in LAB:
        if s in wd[i]: seg_len[s].append(pos[wd[i][s][1]]-pos[wd[i][s][0]]+1)
print('各段交易日中位數',{LAB[s]:st.median(v) for s,v in seg_len.items() if v})
TARGETS=[(a,b) for a,b in (x.split(':') for x in sys.argv[1:])]
for name,side in TARGETS:
    sign=1 if side=='B' else -1
    seen=set(); entry=Counter(); det=[]
    for i in sorted(wd,key=lambda i:cases[i]['bb_start']):
        c=cases[i]; key=(c['code'],c['bb_start'][:7])
        nets={s:by[i][s].get((side,name)) for s in LAB if s in wd[i]}
        hit=[s for s in LAB if nets.get(s) is not None and nets[s]*sign>0]
        if not hit or key in seen: continue
        seen.add(key); entry[hit[0]]+=1
        tot=sum(nets[s] for s in hit)
        det.append((c['bb_start'],c['code'],c['company'][:4],c['method'][:2],LAB[hit[0]],' '.join(f"{LAB[s]}{nets[s]:+}" for s in hit),tot))
    print(f"== {name} {side} 事件{len(det)} 進場段: "+'、'.join(f"{LAB[s]} {entry[s]}" for s in LAB))
    for d in det: print('   ',*d)
