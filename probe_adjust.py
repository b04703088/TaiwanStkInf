import urllib.request, re, sys, json
H={"User-Agent":"Mozilla/5.0"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=60) as r:
            return r.status, r.read().decode('utf-8','replace')
    except Exception as e:
        return 'ERR', repr(e)
urls = sys.argv[1:]
for u in urls:
    s,b=get(u)
    print('=====',u,s,len(b))
    if u.endswith('.html') or '/zh/' in u and 'response' not in u:
        links=sorted(set(re.findall(r'(?:rwd/zh|www/zh-tw|/zh/|zh-tw/)[A-Za-z0-9_/\-\.]+',b)))
        txt=[l for l in links if re.search(r'ex|red|chan|split|par|cap|revi|right|TWT',l,re.I)]
        print('LINKS',txt[:200])
        for m in re.finditer(r'(減資|面額|分割|除權)',b):
            print('CTX',b[max(0,m.start()-200):m.end()+100].replace('\n',' ')[:300]); 
    else:
        print(b[:1500])
