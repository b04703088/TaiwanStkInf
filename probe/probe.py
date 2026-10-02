import pathlib, re, subprocess, sys, json, urllib.request
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=False)
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
def get(url, name=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=40)
        b = r.read(); log.append(f"== {url} -> {r.status} {len(b)} {r.headers.get('content-type')}")
        if name: (OUT / name).write_bytes(b)
        return b
    except Exception as e:
        log.append(f"== {url} -> ERR {e}"); return b""
page = get("https://taiwanindex.com.tw/downloads/technical_notice?category_id=3", "list.html").decode("utf-8", "ignore")
for m in sorted(set(re.findall(r'(?:src|href)="([^"]+\.js)"', page)))[:30]: log.append("js " + m)
for m in sorted(set(re.findall(r'https?://backend\.taiwanindex\.com\.tw/[^"\'\s<]+', page)))[:30]: log.append("be " + m)
# try likely list APIs
for u in ["https://backend.taiwanindex.com.tw/api/TechnicalNotices?category_id=3",
          "https://backend.taiwanindex.com.tw/api/technicalNotices?categoryId=3&lang=tw",
          "https://backend.taiwanindex.com.tw/api/TechnicalNotice/list?category_id=3"]:
    b = get(u); log.append(b[:300].decode("utf-8", "ignore"))
for i in (1325, 1311):
    b = get(f"https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/{i}/tw", f"tn{i}.bin")
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            txt = []
            for pg in pdf.pages:
                txt.append(pg.extract_text() or "")
                for t in pg.extract_tables():
                    txt.append("TABLE: " + json.dumps(t, ensure_ascii=False))
            (OUT / f"tn{i}.txt").write_text("\n".join(txt), encoding="utf-8")
    except Exception as e:
        log.append(f"pdf {i} ERR {e}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
