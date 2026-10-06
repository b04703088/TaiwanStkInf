import io, re, json, pathlib, urllib.request, time
import pdfplumber
out = pathlib.Path("probe/out"); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read()
log = []
# 1. index list page -> find 高股息低波動 code
for u in ["https://taiwanindex.com.tw/indexes", "https://taiwanindex.com.tw/indexes?page=2", "https://taiwanindex.com.tw/indexes?page=3"]:
    try:
        h = get(u).decode("utf-8", "ignore")
        (out / ("list_" + re.sub(r"\W", "_", u[-8:]) + ".html")).write_text(h)
        for m in re.finditer(r'indexes/(IX\d+)[^>]*>\s*([^<]{2,80})<', h):
            log.append(f"LIST {m.group(1)} {m.group(2).strip()}")
    except Exception as e:
        log.append(f"ERR {u} {e!r}")
codes = ["IX0170", "IX0230", "IX0139", "IX0172", "IX0179", "IX0208", "IX0181", "IX0194", "IX0178"]
for l in log:
    if "高股息低波動" in l:
        codes.append(l.split()[1])
KEY = re.compile(r"截止|基準日|審核|生效|公告|交易日")
for c in codes:
    try:
        h = get(f"https://taiwanindex.com.tw/indexes/{c}").decode("utf-8", "ignore")
        (out / f"{c}.html").write_text(h)
        ids = list(dict.fromkeys(re.findall(r"IndexFiles/(\d+)/tw", h)))
        log.append(f"PAGE {c} files {ids}")
        for fid in ids[:3]:
            try:
                b = get(f"https://backend.taiwanindex.com.tw/api/downloadFile/IndexFiles/{fid}/tw")
                with pdfplumber.open(io.BytesIO(b)) as pdf:
                    txt = "\n".join((p.extract_text() or "") for p in pdf.pages)
                if "編製" not in txt[:3000] and "規則" not in txt[:3000]:
                    log.append(f"  {fid} not methodology: {txt[:60]!r}")
                    continue
                (out / f"{c}_{fid}.txt").write_text(txt)
                log.append(f"  {fid} methodology {len(txt)} chars")
            except Exception as e:
                log.append(f"  ERR file {fid} {e!r}")
            time.sleep(1)
    except Exception as e:
        log.append(f"ERR page {c} {e!r}")
    time.sleep(1)
# 2. TIP schedule notice 1325 (tw)
for fid in ["1325"]:
    try:
        b = get(f"https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/{fid}/tw")
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            (out / f"notice_{fid}.txt").write_text("\n".join((p.extract_text() or "") for p in pdf.pages))
    except Exception as e:
        log.append(f"ERR notice {e!r}")
(out / "log.txt").write_text("\n".join(log))
