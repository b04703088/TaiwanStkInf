import csv, statistics as st, sys
from collections import defaultdict, Counter
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
rows=A.rd('research/data/cb_brokers.csv'); cases={c['id']:c for c in A.rd('data/cb/cases.csv')}
kinds={r['bid']:(r['broker_id'],r['broker']) for r in A.rd('data/broker/branches.csv')}
ids=sorted({r['id'] for r in rows})
by=defaultdict(lambda: defaultdict(dict)); wd=defaultdict(dict)
for r in rows:
    wd[r['id']][r['win']]=(r['d1'],r['d2'])
    if r['bid']: by[r['id']][r['win']][(r['side'],r['bid'])]=r
# lead underwriter mapping: firm short name
def firm(bid): return kinds.get(bid,('',''))[1]
def lead_short(s):
    for a,b in [('元大','元大'),('凱基','凱基'),('富邦','富邦'),('永豐','永豐金'),('統一','統一'),('群益','群益金鼎'),('國泰','國泰'),('兆豐','兆豐'),('華南','華南永昌'),('台新','台新'),('元富','元富'),('中國信託','中國信託'),('第一金','第一金'),('福邦','福邦'),('康和','康和'),('玉山','玉山'),('宏遠','宏遠'),('日盛','日盛'),('新光','新光'),('合庫','合庫'),('土銀','台銀'),('台銀','台銀'),('大華','大華國際'),('德信','德信'),('亞東','亞東'),('國票','國票'),('凱基','凱基'),('永興','永興')]:
        if a in s: return b
    return s[:2]
print(Counter(lead_short(cases[i]['lead']) for i in ids if cases[i]['method']=='詢價圈購').most_common())
# For each bb case, lead firm HQ / any branch of lead firm net in pre20 and in
for win in ['pre20','in','post']:
  for m in ['詢價圈購','競價拍賣']:
    res=Counter()
    for i in ids:
        c=cases[i]
        if c['method']!=m or win not in wd[i]: continue
        L=lead_short(c['lead'])
        hq_b=hq_s=0
        for (side,bid),r in by[i][win].items():
            k=kinds.get(bid)
            if not k: continue
            if L in k[1] and k[0]==bid:
                if side=='B' and float(r['net'])>0: hq_b=1
                if side=='S' and float(r['net'])<0: hq_s=1
        res['n']+=1; res['hqB']+=hq_b; res['hqS']+=hq_s
    print(win,m,res['n'],'主辦承銷商總公司 在買超前15: %d%%  賣超前15: %d%%'%(100*res['hqB']/res['n'],100*res['hqS']/res['n']))
