import pathlib, re, subprocess, sys, json, io, urllib.request
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=False)
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
def get(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=40)
        b = r.read(); log.append(f"== {url} -> {r.status} {len(b)} {r.headers.get('content-type')}"); return b
    except Exception as e:
        log.append(f"== {url} -> ERR {e}"); return b""
try:
    h = get("https://app2.msci.com/eqb/gimi/stdindex/index_review.html").decode("utf-8", "ignore")
    (OUT / "msci_review.html").write_text(h, encoding="utf-8")
    log.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))[:3000])
    import pdfplumber
    for mon in ["Aug26", "May26", "Feb26", "Nov25"]:
        for kind in ("ST", "SC"):
            b = get(f"https://app2.msci.com/eqb/gimi/stdindex/MSCI_{mon}_{kind}PublicList.pdf")
            if b[:4] == b"%PDF":
                with pdfplumber.open(io.BytesIO(b)) as pdf:
                    txt = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
                (OUT / f"msci_{mon}_{kind}.txt").write_text(txt, encoding="utf-8")
                i = txt.find("TAIWAN")
                log.append(f"{mon} {kind} first lines: {txt[:300]!r} ... TAIWAN@{i}: {txt[i-100:i+900]!r}")
    for u in ["https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]:
        b = get(u)
        try:
            d = json.loads(b); log.append(f"{u}: n={len(d)} keys={list(d[0].keys())} sample={json.dumps(d[0], ensure_ascii=False)[:600]}")
        except Exception as e:
            log.append(f"{u}: decode ERR {e} {b[:200]!r}")
    for u in ["https://research.ftserussell.com/products/index-notices/home/search?searchText=Taiwan",
              "https://research.ftserussell.com/products/index-notices/home"]:
        b = get(u); log.append(b[:1500].decode("utf-8", "ignore"))
except Exception as e:
    log.append(f"FATAL {e!r}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
