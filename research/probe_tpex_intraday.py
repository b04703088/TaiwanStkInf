import requests
r=requests.get("https://www.tpex.org.tw/www/zh-tw/mostActive/brokerVol?response=json",headers={"User-Agent":"Mozilla/5.0","Origin":"https://tide-stk-infs.pages.dev"},timeout=30)
print("CORS", {k:v for k,v in r.headers.items() if k.lower().startswith("access-control") or k.lower() in("cache-control","date","last-modified")})
print(r.json()["tables"][0]["subtitle"])
