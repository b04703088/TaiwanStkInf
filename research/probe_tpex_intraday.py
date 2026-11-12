import re, requests, json
H={"User-Agent":"Mozilla/5.0"}
def show(u, n=4000, method="GET", data=None):
    print("=====",method,u,data,flush=True)
    try:
        r=requests.request(method,u,headers=H,timeout=30,data=data)
        t=r.content.decode("utf-8","replace")
        print(r.status_code,r.headers.get("content-type"),len(t))
        return t
    except Exception as e: print("ERR",e); return ""
for p in ["broker-vol","broker-amt","amount"]:
    t=show(f"https://www.tpex.org.tw/zh-tw/mainboard/trading/realtime/{p}.html")
    for m in set(re.findall(r'''["']([^"'\s]*(?:\.js|/www/|api|response=json)[^"'\s]*)["']''',t)): print("  E",m)
    i=t.find("<main"); print(re.sub(r'\s+',' ',t[i:i+6000]))
t=show("https://info.tpex.org.tw/IIH/rsrc/js/trdRank.js"); print(t[:5000])
t=show("https://mis.tpex.org.tw/Quote.asmx/GETQ40",method="POST",data={"RankingType":"1","ProductType":"01"}); print(t[:1500])
# guessed new-site json endpoints
for g in ["https://www.tpex.org.tw/www/zh-tw/realtime/brokerVol?response=json",
          "https://www.tpex.org.tw/www/zh-tw/realtime/brokerVol",
          "https://www.tpex.org.tw/www/zh-tw/realtime/brkVol?response=json"]:
    print(show(g)[:1500])
