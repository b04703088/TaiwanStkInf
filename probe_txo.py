import urllib.request, urllib.parse, csv, collections
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
def post(path, form):
    req=urllib.request.Request("https://www.taifex.com.tw/cht/3/"+path, data=urllib.parse.urlencode(form).encode(), headers={"User-Agent":UA})
    raw=urllib.request.urlopen(req,timeout=120).read()
    return raw.decode("cp950","replace")
t=post("optDataDown",{"down_type":"1","commodity_id":"TXO","queryStartDate":"2026/11/12","queryEndDate":"2026/11/13"})
lines=t.splitlines(); print(len(lines)); print("\n".join(lines[:4]))
rows=list(csv.reader(lines[1:]))
c=collections.Counter((r[0],r[2].strip(),r[-2] if len(r)>17 else '') for r in rows if len(r)>5)
for k,v in sorted(c.items()): print(k,v)
for r in rows[:3]+rows[-3:]: print(len(r), r)
g=[r for r in rows if len(r)>17 and r[17].strip()=="一般"]
print("ex general", g[:2])
