import urllib.request, json, re, sys
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u, n=900, enc="utf-8"):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            b = r.read()
        print("==", u, r.status, len(b), r.headers.get("Content-Type")); t = b.decode(enc, "replace"); print(t[:n]); return t
    except Exception as e:
        print("==", u, "ERR", repr(e)); return ""
get("https://www.taifex.com.tw/cht/7/getVixData?filesname=20261120", 600, "big5")
t = get("https://www.taifex.com.tw/cht/7/getVixData?filesname=20261120", 0, "big5"); print("TAIL", t[-400:])
t = get("https://www.taifex.com.tw/cht/7/vixDaily3MNew", 0)
for x in sorted(set(re.findall(r"window.open\('([^']*)'", t)))[:20]: print("open", x)
i = t.find("<table"); print(re.sub(r"\s+", " ", t[i:i+2500]))
get("https://www.taifex.com.tw/cht/7/getVixData?filesname=20250115", 300, "big5")
