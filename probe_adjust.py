import urllib.request, re, json
H={"User-Agent":"Mozilla/5.0"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90) as r:
            return r.status, r.read().decode('utf-8','replace')
    except Exception as e:
        return 'ERR', repr(e)
T='https://www.tpex.org.tw'
s,b=get(T+'/data/menu/zh-tw/menu.json')
print('MENU',s,len(b))
hits=[]
def walk(o,path=''):
    if isinstance(o,dict):
        name=str(o.get('name') or o.get('title') or o.get('text') or '')
        url=str(o.get('url') or o.get('link') or o.get('href') or '')
        if re.search('面額|分割|減資|除權|除息|恢復買賣',name+url): hits.append((path+'/'+name,url,{k:v for k,v in o.items() if not isinstance(v,(list,dict))}))
        for k,v in o.items(): walk(v,path+'/'+name)
    elif isinstance(o,list):
        for v in o: walk(v,path)
try: walk(json.loads(b))
except Exception as e: print('ERR',e); print(b[:2000])
for h in hits: print('HIT',h)
for _,url,_o in hits:
    if not url: continue
    u=url if url.startswith('http') else T+(url if url.startswith('/') else '/'+url)
    s,p=get(u)
    apis=sorted(set(re.findall(r'["\'`](/?www/[A-Za-z0-9_\-/]+|/?api/[A-Za-z0-9_\-/]+|bulletin/[A-Za-z0-9_\-/]+)',p)))
    js=sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"',p)))
    print('PAGE',u,s,apis,[j for j in js if 'asset/js' not in j and 'jquery' not in j])
    for j in js:
        if 'jquery' in j or 'cloudflare' in j or 'gsap' in j: continue
        ju=j if j.startswith('http') else T+(j if j.startswith('/') else '/'+j)
        s2,jb=get(ju)
        a2=sorted(set(re.findall(r'["\'`](/?www/[A-Za-z0-9_\-/]+|/?api/[A-Za-z0-9_\-/]+|bulletin/[A-Za-z0-9_\-/]+)',jb)))
        if a2: print('   JS',ju,a2[:20])
