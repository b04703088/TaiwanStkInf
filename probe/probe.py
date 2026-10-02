import pathlib, re, subprocess, sys, json, urllib.request
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
def get(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=40)
        b = r.read(); log.append(f"== {url} -> {r.status} {len(b)}"); return b
    except Exception as e:
        log.append(f"== {url} -> ERR {e}"); return b""
B = "https://app2.msci.com"
try:
    (OUT / "ir_dates.csv").write_bytes(get(B + "/eqb/pressreleases/archive/ir_dates.csv"))
    page = get(B + "/eqb/gimi/stdindex/index_review.html").decode("utf-8", "ignore")
    links = sorted(set(re.findall(r'href="(/eqb/gimi/(?:stdindex|smallcap)/MSCI_\w+?_(?:ST|SC)PublicList\.pdf)"', page)))
    log.append(f"{len(links)} list links: {links[:60]}")
    for l in links:
        b = get(B + l)
        if b[:4] == b"%PDF":
            (OUT / l.rsplit("/", 1)[1]).write_bytes(b)
    (OUT / "twse_co.json").write_bytes(get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L"))
    (OUT / "tpex_co.json").write_bytes(get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"))
except Exception as e:
    log.append(f"FATAL {e!r}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
