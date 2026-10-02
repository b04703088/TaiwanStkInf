import pathlib, re, json, urllib.request, urllib.parse
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
def get(url, data=None, name=None, hdr=None):
    try:
        h = {"User-Agent": UA, "Accept": "*/*"}; h.update(hdr or {})
        b = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=60).read()
        log.append(f"== {url} -> {len(b)}")
        if name: (OUT / name).write_bytes(b)
        return b
    except Exception as e:
        log.append(f"== {url} -> ERR {e}"); return b""
try:
    p = get("https://web.twsa.org.tw/Edoc2/Default.aspx?Year=2026", name="edoc2026.html")
    s = p.decode("utf-8", "ignore")
    links = re.findall(r'href="([^"]+)"', s)
    log.append("links sample: " + json.dumps([l for l in links if not l.startswith('#')][:60], ensure_ascii=False))
    # follow first PDF-like link mentioning 轉換
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]*轉換公司債[^<]*)</a>', s):
        log.append("CB link: " + m.group(2).strip()[:120] + " -> " + m.group(1))
    b = get("https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data", name="issbd5.json")
    try:
        d = json.loads(b); log.append(f"ISSBD5 n={len(d)} keys={list(d[0].keys())} last={json.dumps(d[-1], ensure_ascii=False)[:800]}")
    except Exception as e:
        log.append(f"ISSBD5 decode {e} {b[:300]!r}")
except Exception as e:
    log.append(f"FATAL {e!r}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
