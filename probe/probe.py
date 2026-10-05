import pathlib, re, urllib.request, urllib.parse, subprocess, sys, json, traceback, io
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl"], check=False)
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
try:
    def get(url):
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90).read()
    s = get("https://www.sfb.gov.tw/ch/home.jsp?id=1016&parentpath=0,6,52").decode("utf-8", "ignore")
    links = re.findall(r'href="(https://www\.fsc\.gov\.tw/userfiles/file/[^"]*\.xlsx)"', s)
    log.append("links " + " ".join(urllib.parse.unquote(u.split('/')[-1]) for u in links))
    import openpyxl
    u = [x for x in links if "1151005" in x or "115" in urllib.parse.unquote(x.split('/')[-1])[:3]][0]
    b = get(u); log.append(f"{urllib.parse.unquote(u)} {len(b)}")
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    for i, ws in enumerate(wb.worksheets):
        rows = [[("" if v is None else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
        log.append(f"sheet {ws.title} rows={len(rows)}")
        (OUT / f"sfb115_{i}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
except Exception:
    log.append(traceback.format_exc())
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
