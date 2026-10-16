import urllib.request, json
H={"User-Agent":"Mozilla/5.0"}
B='https://www.tpex.org.tw/www/zh-tw/bulletin/'
for g in ['pvChgRslt','etfSplitRslt','etfRvsRslt']:
    u=B+g+'?startDate=2022/01/01&endDate=2026/10/16&response=json'
    with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90) as r: b=r.read().decode()
    j=json.loads(b)
    for t in j.get('tables',[]):
        print('=====',g,t.get('totalCount'),len(t.get('data',[])),t.get('fields'))
        for row in t.get('data',[]): print('  ',row)
    print({k:v for k,v in j.items() if k!='tables'})
