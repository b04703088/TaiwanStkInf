import urllib.request, os, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
os.makedirs("probe/out", exist_ok=True)
def get(u, h=None):
    hh = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    hh.update(h or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=hh), timeout=30) as r:
            return r.status, r.read()
    except Exception as e:
        return "ERR", str(e).encode()
U = {
 "sse_scfi.html": ("https://www.sse.net.cn/index/singleIndex?indexType=scfi", None),
 "sse_en_scfi.html": ("https://en.sse.net.cn/indices/scfinew.jsp", None),
 "sse_home.html": ("https://www.sse.net.cn/", None),
 "dramx.html": ("https://www.dramexchange.com/", None),
 "tf_price.html": ("https://www.trendforce.com/price", None),
 "inv_bdi.html": ("https://www.investing.com/indices/baltic-dry-historical-data", None),
 "inv_api.json": ("https://api.investing.com/api/financialdata/historical/940793?start-date=2026-01-01&end-date=2026-10-30&time-frame=Daily&add-missing-rows=false", {"domain-id": "www", "Referer": "https://www.investing.com/"}),
 "te_bdi.html": ("https://tradingeconomics.com/commodity/baltic", None),
 "te_cfi.html": ("https://tradingeconomics.com/commodity/containerized-freight-index", None),
 "moneydj.html": ("https://www.moneydj.com/z/ze/zeq/zeqa_D0400001.djhtm", None),
 "cnyes_mat.html": ("https://www.cnyes.com/futures/material.aspx", None),
 "drewry.html": ("https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry", None),
 "sina_bdi.txt": ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=BDI&source=web", {"Referer": "https://finance.sina.com.cn/"}),
 "cnyes_search.json": ("https://ws.api.cnyes.com/ws/api/v1/universal/search?q=BDI", None),
}
for f, (u, h) in U.items():
    st, b = get(u, h)
    print(f, st, len(b), flush=True)
    open("probe/out/" + f, "wb").write(b)
