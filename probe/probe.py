import pathlib, re, urllib.request, urllib.parse, subprocess, sys, json
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl"], check=False)
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90); return r.read()
s = get("https://www.sfb.gov.tw/ch/home.jsp?id=1016&parentpath=0,6,52").decode("utf-8", "ignore")
links = re.findall(r'href="(https://www\.fsc\.gov\.tw/userfiles/file/[^"]*%E7%94%B3%E5%A0%B1%E6%A1%88%E4%BB%B6%E5%BD%99%E7%B8%BD%E8%A1%A8\.xlsx)"', s)
log.append(f"links {links}")
import openpyxl, io
for u in links:
    b = get(u); name = urllib.parse.unquote(u.split("/")[-1]); log.append(f"{name} {len(b)}")
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = [[("" if v is None else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
        log.append(f"  sheet {ws.title} rows={len(rows)}")
        for r in rows[:6]: log.append("   " + " | ".join(r))
        cb = [r for r in rows if any("轉換" in c or "交換" in c for c in r)]
        log.append(f"  CB rows {len(cb)}")
        for r in cb[:12] + cb[-12:]: log.append("   CB " + " | ".join(r))
        (OUT / (name + "." + ws.title + ".json")).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
