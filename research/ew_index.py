# 等權市場指數：每日所有普通股（4 碼）漲跌幅的平均連乘，排除 ±11% 以外（除權、減資等）
import csv, statistics as st
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
files=sorted(p for p in (ROOT/'data').glob('[0-9][0-9][0-9][0-9]/[0-9]*.csv') if len(p.stem)==8)
prev={}; idx=1.0; out=[]
for p in files:
    d=f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}"; cur={}; rets=[]
    with open(p,encoding='utf-8') as fp:
        for r in csv.DictReader(fp):
            c=r['code']
            if len(c)!=4 or not c.isdigit(): continue
            try: x=float(r['close'])
            except ValueError: continue
            cur[c]=x
            if c in prev and prev[c]>0:
                g=x/prev[c]-1
                if abs(g)<0.11: rets.append(g)
    if rets: idx*=1+st.mean(rets)
    prev.update(cur); out.append((d,idx))
with open(ROOT/'research'/'data'/'ew_index.csv','w') as fp:
    fp.write('date,close\n'+''.join(f'{d},{v:.6f}\n' for d,v in out))
print(out[0],out[-1])
