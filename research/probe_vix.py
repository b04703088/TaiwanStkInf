import urllib.request, re
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u, n=600, enc="big5"):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            b = r.read()
        t = b.decode(enc, "replace"); print("==", u, r.status, len(b), r.headers.get("Content-Type")); print(t[:n]); return t
    except Exception as e:
        print("==", u, "ERR", repr(e)); return ""
t = get("https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/202611new.txt", 800)
ls = t.splitlines()
for d in ("20261121", "20261124", "20261125"):
    sel = [l for l in ls if l.startswith(d)]
    print(d, len(sel)); print("\n".join(sel[:4])); print("..."); print("\n".join(sel[-6:]))
for ym in ("202607", "202606", "202601", "202501", "202301"):
    get(f"https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt", 200)
for page in ("https://www.taifex.com.tw/cht/7/vixMinNew", "https://www.taifex.com.tw/cht/7/vixDaily3MNew", "https://www.taifex.com.tw/cht/7/vixHistory"):
    t = get(page, 0, "utf-8")
    for x in sorted(set(re.findall(r"(?:href|window.open\()=?['\"]([^'\"]*(?:vix|Vix|VIX|zip|txt|csv)[^'\"]*)", t)))[:40]: print("  link", x)
get("https://openapi.taifex.com.tw/swagger.json", 0, "utf-8")
t = get("https://openapi.taifex.com.tw/swagger.json", 0, "utf-8")
print([p for p in re.findall(r'"(/v1/[^"]+)"', t) if "ola" in p.lower() or "vix" in p.lower() or "Index" in p][:40])
