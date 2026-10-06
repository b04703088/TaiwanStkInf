import pathlib, re, json, urllib.request, http.cookiejar
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
log = []
def get(url, name, enc="utf-8"):
    try:
        r = op.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60); b = r.read()
        (OUT / name).write_bytes(b)
        s = b.decode(enc, "ignore")
        t = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S))
        i = t.find("產業")
        log.append(f"OK {len(b)} {url}\n   {t[max(0,i-150):i+600] if i>=0 else t[:300]}")
        return s
    except Exception as e:
        log.append(f"ERR {url} {e!r}"); return ""
# 1 官方產業別
for url, n in [("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "twse.json"), ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "tpex.json")]:
    s = get(url, n)
    try:
        d = json.loads(s); x = [r for r in d if r.get("公司代號") == "2330" or r.get("SecuritiesCompanyCode") == "5347"]
        log.append("   sample " + json.dumps(x[:1], ensure_ascii=False)[:600])
    except Exception as e: log.append(f"   {e!r}")
# 2 櫃買 產業價值鏈
get("https://ic.tpex.org.tw/index.php", "ic_index.html")
get("https://ic.tpex.org.tw/introduce.php?ic=D000", "ic_D000.html")
get("https://ic.tpex.org.tw/company_chain.php?stk_code=2330", "ic_chain_2330.html")
# 3 MoneyDJ（富邦）
B = "https://fubon-ebrokerdj.fbs.com.tw"
for u, n in [("/z/zc/zca/zca_2330.djhtm", "dj_zca_2330.html"), ("/z/zc/zca/zca.djhtm?a=2330", "dj_zca_q.html"),
             ("/z/zh/zha/zha.djhtm", "dj_zha.html"), ("/z/zh/zhb/zhb.djhtm", "dj_zhb.html"), ("/z/zh/zhc/zhc.djhtm", "dj_zhc.html"),
             ("/z/zc/zcx/zcx_2330.djhtm", "dj_zcx.html")]:
    get(B + u, n, "cp950")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
