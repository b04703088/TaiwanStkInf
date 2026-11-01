import csv, sys
from collections import defaultdict
sys.path.insert(0,'research'); sys.path.insert(0,'scripts')
import cb_broker_analyze as A
rows=A.rd('research/data/cb_brokers.csv'); cases={c['id']:c for c in A.rd('data/cb/cases.csv')}
px={r['id']:r for r in A.rd('research/data/cb_cases_px.csv')}
by=defaultdict(lambda: defaultdict(dict))
for r in rows:
    if r['bid']: by[r['id']][r['win']][(r['side'],r['broker'])]=r
def net(i,w,name):
    t=0
    for side in 'BS':
        r=by[i][w].get((side,name))
        if r: t=int(r['net'])
    return t
def f(x): return f"{float(x)*100:+.0f}%" if x else '  -'
for name,side in [(a, b) for a,b in (x.split(':') for x in sys.argv[1:])]:
    print('=====',name,side)
    for i in sorted(by, key=lambda i: cases[i]['bb_start']):
        r=by[i]['pre20'].get((side,name))
        if not r or (side=='B')!=(int(r['net'])>0): continue
        c=cases[i]; p=px.get(i,{})
        lead=c['lead'].replace('綜合','').replace('股份有限公司','').replace('證券','')
        print(f"{c['bb_start']} {c['code']} {c['company'][:5]:6} {c['method'][:2]} 主辦{lead:6} pre20 {int(r['net']):+6} base{net(i,'base',name):+6} in{net(i,'in',name):+6} post{net(i,'post',name):+6} | 量比{int(r['net'])/max(float(p.get('vol_pre20') or 1),1)*100:+.1f}% 超額 pre{f(p.get('x_pre20'))} in{f(p.get('x_in'))} post{f(p.get('x_post20'))} 溢價{c['premium']}")
