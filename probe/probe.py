import json, urllib.request, urllib.parse, time, sys
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
def get(u, ref=None, n=400):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if ref: h["Referer"] = ref
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=25) as r:
            b = r.read()
            return r.status, len(b), b
    except Exception as e:
        return "ERR", 0, str(e).encode()
Y = ["CL=F","BZ=F","NG=F","MTF=F","NCF=F","QA=F","RB=F","HO=F","HG=F","ALI=F","GC=F","SI=F","PL=F","PA=F","HRC=F","TIO=F","UX=F","ZC=F","ZW=F","ZS=F","ZM=F","KC=F","SB=F","CC=F","CT=F","LE=F","HE=F","ZR=F","OJ=F","LBS=F","BDRY","BWET","URA","LIT","SEA","^BDI","BDI","SCFI"]
for s in Y:
    st, n, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}?range=5d&interval=1d")
    info = ""
    if st == 200:
        try:
            m = json.loads(b)["chart"]["result"][0]["meta"]; info = f'{m.get("shortName") or m.get("longName")} {m.get("regularMarketPrice")} {m.get("currency")}'
        except Exception as e: info = str(e)
    else: info = b[:120]
    print("YH", s, st, info, flush=True); time.sleep(0.3)
SINA = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getDailyKLine?symbol="
for s in ["RB0","HC0","I0","JM0","J0","CU0","AL0","NI0","ZN0","SN0","LC0","SI0","PS0","RU0","FG0","SA0","EC0","SC0","AU0","AG0","M0","SR0","CF0","AO0","BC0","SS0"]:
    st, n, b = get(SINA + s, "https://finance.sina.com.cn/")
    print("SINA", s, st, n, b[:60], b[-120:], flush=True); time.sleep(0.5)
for s in ["CAD","AHD","NID","ZSD","PBD","SND","XAU","CL","GC"]:
    for u in [f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={s}&_=2026_10_30&source=web"]:
        st, n, b = get(u, "https://finance.sina.com.cn/")
        print("SINAG", s, st, n, b[:60], b[-120:], flush=True)
U = [
 ("https://www.sse.net.cn/index/singleIndex?indexType=scfi", None),
 ("https://www.sse.net.cn/index/singleIndex?indexType=ccfi", None),
 ("https://en.sse.net.cn/indices/scfinew.jsp", None),
 ("https://www.sse.net.cn/", None),
 ("https://www.dramexchange.com/", None),
 ("https://www.trendforce.com/price", None),
 ("https://stooq.com/q/d/l/?s=bdi&i=d", None),
 ("https://ws.api.cnyes.com/ws/api/v1/charting/history?resolution=D&symbol=GI:BDI:INDEX&from=1761800000&to=1750000000", None),
 ("https://ws.api.cnyes.com/ws/api/v1/charting/history?resolution=D&symbol=GI:BDIY:INDEX&from=1761800000&to=1750000000", None),
 ("https://www.investing.com/indices/baltic-dry-historical-data", None),
 ("https://tradingeconomics.com/commodity/baltic", None),
 ("https://tradingeconomics.com/commodity/containerized-freight-index", None),
 ("https://fbx.freightos.com/api/lane/FBX?isDaily=true", None),
 ("https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry", None),
 ("https://www.hellenicshippingnews.com/category/shipping-news/dry-bulk-market/", None),
 ("https://markets.businessinsider.com/index/baltic_dry", None),
 ("https://www.macromicro.me/charts/946/baltic-dry-index", None),
 ("https://www.moneydj.com/z/ze/zeq/zeqa_D0400001.djhtm", None),
 ("https://www.wantgoo.com/global/bdi", None),
 ("https://index.ndc.gov.tw/", None),
 ("https://www.cnyes.com/futures/material.aspx", None),
 ("https://hq.sinajs.cn/list=hf_CAD,hf_AHD,nf_EC0", "https://finance.sina.com.cn/"),
]
for u, ref in U:
    st, n, b = get(u, ref)
    print("URL", u, st, n, b[:300].decode("utf-8","replace").replace("\n"," "), flush=True)
