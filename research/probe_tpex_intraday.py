import re, requests, json
H={"User-Agent":"Mozilla/5.0"}
def try_(m,u,**k):
    print("=====",m,u,k,flush=True)
    try:
        r=requests.request(m,u,headers=H,timeout=30,**k); t=r.content.decode("utf-8","replace")
        print(r.status_code,r.headers.get("content-type"),len(t)); print(t[:3500]); return t
    except Exception as e: print("ERR",e)
for a in ["brokerVol","brokerAmt"]:
    try_("POST",f"https://www.tpex.org.tw/www/zh-tw/mostActive/{a}",data={"response":"json"})
    try_("GET",f"https://www.tpex.org.tw/www/zh-tw/mostActive/{a}?response=json")
m=requests.get("https://info.tpex.org.tw/IIH/rsrc/js/main.js",headers=H,timeout=30).text
for x in re.finditer(r'apiHost',m): print("APIHOST",m[max(0,x.start()-100):x.start()+200])
for host in ["https://info.tpex.org.tw","https://info.tpex.org.tw/IIH","https://info.tpex.org.tw/IIHAPI"]:
    try_("POST",host+"/api/trdRank")
