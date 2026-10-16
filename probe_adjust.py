import urllib.request, re, sys, json
H={"User-Agent":"Mozilla/5.0"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90) as r:
            return r.status, r.read().decode('utf-8','replace')
    except Exception as e:
        return 'ERR', repr(e)
def cnt(u):
    s,b=get(u)
    try:
        j=json.loads(b)
    except Exception:
        print('=====',u,s,'NOTJSON',b[:200].replace('\n',' ')); return
    if 'tables' in j:
        for t in j['tables']:
            print('=====',u,'totalCount',t.get('totalCount'),'len',len(t.get('data',[])),'fields',t.get('fields'))
            if t.get('data'): print('  first',t['data'][0][:10],'last',t['data'][-1][:10])
        print('  keys',list(j.keys()), {k:j[k] for k in j if k not in('tables',)})
    else:
        print('=====',u,j.get('stat'),'len',len(j.get('data',[])),j.get('total'))
        if j.get('data'): print('  first',j['data'][0],'last',j['data'][-1])
B='https://www.tpex.org.tw/www/zh-tw/bulletin/'
cnt('https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20220101&endDate=20221231&response=json')
cnt(B+'exDailyQ?startDate=2022/01/01&endDate=2022/12/31&response=json')
cnt(B+'revivt?startDate=2022/01/01&endDate=2026/10/16&response=json')
cnt('https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?startDate=20220101&endDate=20261016&response=json')
for g in ['parValue','parvalue','faceValue','chgParValue','parValueRevivt','pvc','etfSplit','split','etfsplit','revivtPar','changePar','exParValue','parValueChg']:
    s,b=get(B+g+'?startDate=2022/01/01&endDate=2026/10/16&response=json')
    print('GUESS',g,s,b[:150].replace('\n',' ') if not b.startswith('<!DOCTYPE') else 'HTML404?')
for page in ['https://www.tpex.org.tw/zh-tw/index.html','https://www.tpex.org.tw/zh-tw/mainboard/listed/exright/exdailyq.html','https://www.tpex.org.tw/zh-tw/announce/market/exdailyq.html']:
    s,b=get(page)
    links=sorted(set(re.findall(r'["\'](/?[^"\'\s]*?(?:exright|bulletin|revivt|exDaily|split|par)[^"\'\s]*)["\']',b,re.I)))
    print('PAGE',page,s,len(b),links[:200])
    js=sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"',b)))
    print('  JS',js)
    for j in js:
        if 'menu' in j.lower() or 'nav' in j.lower() or 'main' in j.lower():
            u=j if j.startswith('http') else 'https://www.tpex.org.tw'+(j if j.startswith('/') else '/'+j)
            s2,b2=get(u)
            print('  JSFILE',u,s2,sorted(set(re.findall(r'[A-Za-z0-9_/\-]*(?:exright|revivt|split|par[vV]alue|denomin|facevalue)[A-Za-z0-9_/\-\.]*',b2)))[:100])
