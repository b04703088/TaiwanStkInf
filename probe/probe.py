import urllib.request, urllib.parse, os, http.cookiejar, re
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
os.makedirs("probe/out2", exist_ok=True)
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(u, data=None, h=None):
    hh = {"User-Agent": UA, "Accept": "*/*"}
    hh.update(h or {})
    try:
        with op.open(urllib.request.Request(u, data=data, headers=hh), timeout=30) as r:
            return r.status, r.read()
    except Exception as e:
        return "ERR", str(e).encode()
def save(f, u, **kw):
    st, b = get(u, **kw); print(f, st, len(b), flush=True); open("probe/out2/" + f, "wb").write(b); return b
for p in ["material2", "material9", "material5", "material6"]:
    save(p + ".html", f"https://www.cnyes.com/futures/{p}.aspx")
b = save("cnyes_bdi_chart.html", "https://www.cnyes.com/futures/html5chart/BDI.html")
for js in re.findall(rb'src="([^"]+\.js[^"]*)"', b)[:15]:
    js = js.decode()
    if "chart" in js.lower() or "html5" in js.lower() or not js.startswith("http"):
        u = urllib.parse.urljoin("https://www.cnyes.com/futures/html5chart/BDI.html", js)
        save("js_" + re.sub(r"[^a-zA-Z0-9.]", "_", js)[-60:], u)
for u in ["https://www.cnyes.com/futures/html5chart/BDI.html"]:
    pass
# SSE 歷史：拿 csrf 再 POST 日期
b = save("sse_scfi_get.html", "https://www.sse.net.cn/index/singleIndex?indexType=scfi")
tok = re.search(rb'name="CSRFToken" value="([^"]+)"', b)
if tok:
    for d in ["2025-10-24", "2024-10-25"]:
        save(f"sse_scfi_{d}.html", "https://www.sse.net.cn/index/singleIndex?indexType=scfi",
             data=urllib.parse.urlencode({"CSRFToken": tok.group(1).decode(), "date": d}).encode(),
             h={"Content-Type": "application/x-www-form-urlencoded", "Referer": "https://www.sse.net.cn/index/singleIndex?indexType=scfi"})
save("sse_scfilist.html", "https://www.sse.net.cn/index/scfilist")
save("sse_ccfi.html", "https://www.sse.net.cn/index/singleIndex?indexType=ccfi")
save("sse_bdi_fdi.html", "https://www.sse.net.cn/index/singleIndex?indexType=fdi")
save("dramx_spot.html", "https://www.dramexchange.com/WeeklyResearch/Post/2/0.html")
