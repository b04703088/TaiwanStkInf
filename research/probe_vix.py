import urllib.request, urllib.parse, re, io, zipfile
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u, n=600, enc="big5", data=None):
    try:
        req = urllib.request.Request(u, headers=UA, data=urllib.parse.urlencode(data).encode() if data else None)
        with urllib.request.urlopen(req, timeout=90) as r:
            b = r.read()
        print("==", u, r.status, len(b), r.headers.get("Content-Type"), r.headers.get("Content-Disposition"))
        t = b.decode(enc, "replace"); print(t[:n]); return b
    except Exception as e:
        print("==", u, "ERR", repr(e)); return b""
b = get("https://www.taifex.com.tw/cht/7/getVixData?filesname=20261124", 300)
t = b.decode("big5", "replace").splitlines(); print("N", len(t)); print("\n".join(t[::300][:40])); print("\n".join(t[-5:]))
for s, e in (("2023/01/03", "2023/01/06"), ("2016/01/04", "2016/01/05")):
    b = get("https://www.taifex.com.tw/cht/3/optDataDown", 800, data={"down_type": "1", "commodity_id": "TXO", "commodity_id2": "", "queryStartDate": s, "queryEndDate": e})
    t = b.decode("big5", "replace").splitlines(); print("LINES", len(t)); print("\n".join(t[-3:]))
get("https://www.taifex.com.tw/cht/3/dlOptDataDown", 0, "utf-8")
for u in ("https://ws.api.cnyes.com/ws/api/v1/charting/history?resolution=D&symbol=TWS:VIX:INDEX&from=1764000000&to=1672500000",
          "https://ws.api.cnyes.com/ws/api/v1/charting/history?resolution=D&symbol=TWF:VIX:INDEX&from=1764000000&to=1672500000",
          "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWVIX?range=5y&interval=1d"):
    get(u, 400, "utf-8")
