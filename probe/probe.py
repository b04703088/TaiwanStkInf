import pathlib, re, urllib.request, http.cookiejar
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
log = []
def get(url, name):
    try:
        r = op.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60); b = r.read()
        (OUT / name).write_bytes(b); s = b.decode("utf-8", "ignore")
        log.append(f"OK {len(b)} {r.headers.get('content-type')} {url}")
        for m in re.findall(r'<(?:iframe|form|a)[^>]+(?:src|action|href)="([^"]+)"[^>]*>([^<]{0,40})', s):
            if any(k in (m[0] + m[1]) for k in ("申報", "案件", "case", "Case", "iframe", "query", "Query", "xls", "ods", "csv", "1016", "sfbcase")):
                log.append(f"   link {m[0]} | {m[1].strip()}")
        for m in re.findall(r'<iframe[^>]+src="([^"]+)"', s): log.append(f"   IFRAME {m}")
        return s
    except Exception as e:
        log.append(f"ERR {url} {e!r}"); return ""
get("https://www.sfb.gov.tw/ch/home.jsp?id=1016&parentpath=0,6,52", "sfb_1016.html")
get("https://www.sfb.gov.tw/ch/home.jsp?id=54&parentpath=0,6,52", "sfb_54.html")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
