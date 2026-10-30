import urllib.request, urllib.parse, os, http.cookiejar, re
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
os.makedirs("probe/out3", exist_ok=True)
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(u, h=None):
    hh = {"User-Agent": UA, "Accept": "*/*"}; hh.update(h or {})
    try:
        with op.open(urllib.request.Request(u, headers=hh), timeout=40) as r:
            return r.status, r.read()
    except Exception as e:
        return "ERR", str(e).encode()
def save(f, u, h=None):
    st, b = get(u, h); print(f, st, len(b), b[:300], flush=True); open("probe/out3/" + f, "wb").write(b); return b
save("sse_home.html", "https://www.sse.net.cn/index/scfilist")
save("scfi_multi.json", "https://www.sse.net.cn/index/mutipleIndex?indexType=scfi&columns=T,L1,L3&startDate=2018-01-01&endDate=2026-10-30", {"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.sse.net.cn/index/scfilist"})
save("ccfi_list.html", "https://www.sse.net.cn/index/ccfilist")
save("ccfi_multi.json", "https://www.sse.net.cn/index/mutipleIndex?indexType=ccfi&columns=T&startDate=2024-01-01&endDate=2026-10-30", {"X-Requested-With": "XMLHttpRequest"})
save("fdi_multi.json", "https://www.sse.net.cn/index/mutipleIndex?indexType=fdi&columns=T&startDate=2024-01-01&endDate=2026-10-30", {"X-Requested-With": "XMLHttpRequest"})
b = save("cnyes_study.html", "https://so.cnyes.com/JavascriptGraphic/chartstudy.aspx?country=future&market=future&code=BDI&divwidth=650&divheight=330", {"Referer": "https://www.cnyes.com/futures/html5chart/BDI.html"})
for u in set(re.findall(rb'["\']([^"\']*(?:\.ashx|\.aspx|\.js)[^"\']*)["\']', b)):
    u = u.decode()
    if any(w in u.lower() for w in ("data", "chart", "ashx", "json", "his", "quote")):
        full = urllib.parse.urljoin("https://so.cnyes.com/JavascriptGraphic/chartstudy.aspx", u)
        save("cs_" + re.sub(r"[^a-zA-Z0-9.]", "_", u)[-70:], full, {"Referer": "https://so.cnyes.com/JavascriptGraphic/chartstudy.aspx"})
