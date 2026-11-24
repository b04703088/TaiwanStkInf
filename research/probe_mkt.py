import urllib.request, json, re, sys
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u, n=900, enc="utf-8"):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            b = r.read()
        print("==", u, r.status, len(b)); t = b.decode(enc, "replace"); print(t[:n]); return t
    except Exception as e:
        print("==", u, "ERR", repr(e)); return ""
for u in ["https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date=20261101&response=json",
          "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=json&date=20261101",
          "https://www.twse.com.tw/exchangeReport/MI_5MINS_HIST?response=json&date=20261101",
          "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20160108&type=ALLBUT0999&response=json",
          "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20100108&selectType=ALL&response=json",
          "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20050107&selectType=ALL&response=json",
          "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=20230105&response=json",
          "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date=2016/01/01&response=json"]:
    get(u, 700)
t = get("https://www.taifex.com.tw/cht/7/vixMinNew", 0)
for x in sorted(set(re.findall(r'(?:href|value|onclick)=["\']([^"\']*(?:vix|VIX|txt|zip|csv)[^"\']*)', t)))[:40]: print("link", x)
i = t.find("<table"); print(re.sub(r"\s+", " ", t[i:i+4000]))
