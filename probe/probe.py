import pathlib, re, json, urllib.request, urllib.parse, http.cookiejar, io, subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=False)
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
log = []
URL = "https://web.twsa.org.tw/Edoc2/Default.aspx?Year=2026"
def req(url, data=None):
    r = op.open(urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Referer": URL}), timeout=60)
    return r.read(), r.headers.get("content-type"), r.headers.get("content-disposition")
try:
    page, ct, _ = req(URL); s = page.decode("utf-8", "ignore")
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', s))
    rb = re.findall(r'name="ctl00\$cphMain\$rblReportType" value="([^"]+)" checked', s)
    log.append(f"hidden {list(hidden)} rb={rb}")
    rows = re.findall(r'<tr style="color:#[0-9A-F]+;background-color:#[0-9A-F]+;font-size:12px;">(.*?)</tr>', s, re.S)
    targets = []
    for r in rows:
        tds = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        btn = re.search(r'name="([^"]+imgbtnFileName)"', r)
        if "轉換" in tds[6] and btn:
            targets.append((tds[0], tds[3], tds[7], btn.group(1)))
    log.append(f"{len(targets)} CB rows; using {targets[-3:]}")
    import pdfplumber
    for sn, name, method, btn in targets[-3:] + targets[:1]:
        form = dict(hidden); form["ctl00$cphMain$ddlYear"] = "2026"
        if rb: form["ctl00$cphMain$rblReportType"] = rb[0]
        form[btn + ".x"] = "8"; form[btn + ".y"] = "8"
        body, ct, cd = req(URL, urllib.parse.urlencode(form).encode())
        log.append(f"{sn} {name} {method}: ct={ct} cd={cd} len={len(body)} head={body[:8]!r}")
        if body[:4] == b"%PDF":
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                txt = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
            (OUT / f"cb_{sn}.txt").write_text(txt, encoding="utf-8")
        else:
            (OUT / f"cb_{sn}.bin").write_bytes(body[:200000])
except Exception as e:
    log.append(f"FATAL {e!r}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
