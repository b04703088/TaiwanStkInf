import pathlib, re, json, urllib.request
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
try:
    def get(url):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=40)
            return r.read()
        except Exception as e:
            log.append(f"ERR {url} {e}"); return b""
    try:
        d = json.loads(get("https://openapi.twse.com.tw/v1/opendata/t187ap47_L") or b"[]")
    except Exception as e:
        log.append(f"t187 decode ERR {e}"); d = []
    log.append("t187ap47_L keys: " + json.dumps(list(d[0].keys()) if d else [], ensure_ascii=False))
    log.append(json.dumps([x for x in d if x.get("基金代號", "").strip() in ("00940", "00947", "00946", "00878", "0050")], ensure_ascii=False)[:3000])
    # tpex etf info
    for u in ["https://www.tpex.org.tw/openapi/v1/tpex_etf_basic_info", "https://www.tpex.org.tw/openapi/v1/etf_info"]:
        b = get(u); log.append(f"{u}: {b[:400].decode('utf-8','ignore')}")
    for p in range(1, 7):
        page = get(f"https://taiwanindex.com.tw/downloads/technical_notice?category_id=3&page={p}").decode("utf-8", "ignore")
        ids = re.findall(r"TechnicalNotices/(\d+)/tw", page)
        titles = re.findall(r"(20\d\d\s*年\s*\d+\s*月指數定期審核日程表)", page)
        log.append(f"page {p}: {ids} {titles[:12]}")
    # index list page for ETF mapping
    page = get("https://taiwanindex.com.tw/indexes").decode("utf-8", "ignore")
    log.append("indexes page len %d, IX ids %d" % (len(page), len(set(re.findall(r"IX\d{4}", page)))))
    pg = get("https://taiwanindex.com.tw/indexes/IX0124").decode("utf-8", "ignore")
    i = pg.find("ETF"); log.append("IX0124: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", pg))[:1500])
except Exception as e:
    log.append(f"FATAL {e!r}")
(OUT / "dbg2.txt").write_text("\n".join(log), encoding="utf-8")
