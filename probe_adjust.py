import urllib.request, re, json
H={"User-Agent":"Mozilla/5.0"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90) as r:
            return r.status, r.read().decode('utf-8','replace')
    except Exception as e:
        return 'ERR', repr(e)
T='https://www.tpex.org.tw'
s,b=get(T+'/zh-tw/index.html')
hrefs=sorted(set(re.findall(r'href="([^"#]+)"',b)))
print('HREFS',len(hrefs)); print('\n'.join(hrefs))
for js in ['/rsrc/asset/js/global.js','/rsrc/js/main.js','/rsrc/asset/js/index.js']:
    s,b2=get(T+js)
    print('JS',js,s,sorted(set(re.findall(r'["\'`](/[A-Za-z0-9_\-/\.]*(?:www|json|menu|api)[A-Za-z0-9_\-/\.]*)["\'`]',b2)))[:80])
B=T+'/www/zh-tw/bulletin/'
for g in ['etfSplitRst','etfSplitResult','etfSplitRevivt','etfRevivt','parRevivt','revivtPar','chgFv','fv','faceValue','parvalueChange','parValueChange','parChange','revivtFV','denomination','exParvalue','chgparvalue','pvChange','etfReverseSplit','splitRevivt','revivtEtf','revivtSplit','parValueRevivt','revivtParValue']:
    for q in ['?startDate=2024/01/01&endDate=2026/10/16&response=json','?response=json']:
        s,b=get(B+g+q)
        if not b.lstrip().startswith('<'):
            print('GUESS',g,q,s,b[:300]); break
    else:
        print('miss',g)
