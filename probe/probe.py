import pathlib, re, json, urllib.request, urllib.parse, http.cookiejar, traceback
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
log = []
def req(url, data=None, headers=None, name=None):
    h = {"User-Agent": UA, "Accept": "*/*"}; h.update(headers or {})
    if isinstance(data, dict): data = urllib.parse.urlencode(data).encode()
    try:
        r = op.open(urllib.request.Request(url, data=data, headers=h), timeout=60)
        b = r.read()
        log.append(f"OK {r.status} {len(b)} {r.headers.get('content-type')} {url}")
        if name: (OUT / name).write_bytes(b)
        return b
    except Exception as e:
        log.append(f"ERR {url}: {e!r}")
        return b""
KW = ("轉換公司債", "交換公司債")
# 1. OpenAPI 每日重大訊息
for url, name in [("https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "twse_ap04.json"),
                  ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O", "tpex_ap04.json"),
                  ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_R", "tpex_ap04R.json")]:
    b = req(url, name=name)
    try:
        d = json.loads(b); log.append(f"  n={len(d)} keys={list(d[0].keys()) if d else None}")
        hits = [x for x in d if any(k in json.dumps(x, ensure_ascii=False) for k in KW)]
        log.append(f"  CB hits={len(hits)}"); (OUT / ("hits_" + name)).write_text(json.dumps(hits[:8], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log.append(f"  parse {e!r}")
# 2. 觀測站舊版：依日期查詢、全文檢索表單頁
for host in ["https://mopsov.twse.com.tw", "https://mops.twse.com.tw"]:
    for pg in ["t05st02", "t51sb10", "t05sr01_1"]:
        req(f"{host}/mops/web/{pg}", name=f"{host.split('//')[1].split('.')[0]}_{pg}.html")
# 依日期查詢重訊（115/09/30）
for host in ["https://mopsov.twse.com.tw", "https://mops.twse.com.tw"]:
    b = req(f"{host}/mops/web/ajax_t05st02", data={"encodeURIComponent": "1", "step": "1", "step00": "0", "firstin": "1", "off": "1",
             "TYPEK": "all", "year": "115", "month": "09", "day": "30"}, headers={"Referer": f"{host}/mops/web/t05st02"},
             name=f"{host.split('//')[1].split('.')[0]}_ajax_t05st02.html")
    s = b.decode("utf-8", "ignore"); log.append(f"  t05st02 rows~{s.count('<tr')} cb={sum(s.count(k) for k in KW)} snippet={re.sub(r'<[^>]+>|\\s+',' ',s)[:300]}")
# 3. 新版觀測站 API 猜測
for url, body in [("https://mops.twse.com.tw/mops/api/t05st02", {"year": "115", "month": "09", "day": "30"}),
                  ("https://mops.twse.com.tw/mops/api/t05sr01_1", {})]:
    b = req(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Referer": "https://mops.twse.com.tw/mops/"},
            name="new_" + url.split("/")[-1] + ".json")
    log.append("  " + b[:300].decode("utf-8", "ignore"))
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
