import re, requests
H={"User-Agent":"Mozilla/5.0"}
def get(u,**k):
    r=requests.get(u,headers=H,timeout=30,**k); return r.content.decode("utf-8","replace")
t=get("https://www.tpex.org.tw/zh-tw/mainboard/trading/realtime/broker-vol.html")
b=t.find("<body"); print(re.sub(r'\s+',' ',re.sub(r'<(?!script)[^>]+>',' ',t[b:]))[:5000])
for s in ["/rsrc/js/main.js","/rsrc/js/tables.js"]:
    j=get("https://www.tpex.org.tw"+s)
    print("=====",s,len(j))
    for m in re.finditer(r'(realtime|brk|broker|/www/)',j):
        print("  ..",j[max(0,m.start()-200):m.start()+200].replace("\n"," "))
r=get("https://info.tpex.org.tw/IIH/rsrc/js/trdRank.js")
i=r.find("ajax"); print("TRD",r[-2500:])
