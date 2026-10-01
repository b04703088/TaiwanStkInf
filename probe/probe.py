import pathlib, re, urllib.request
from datetime import datetime, timedelta, timezone
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
B = "https://fubon-ebrokerdj.fbs.com.tw"
log = [f"now {datetime.now(timezone(timedelta(hours=8))):%H:%M:%S}"]
for path in ["/z/zc/zco/zco.djhtm?a=2330&e=2026-10-1&f=2026-10-1", "/z/zc/zco/zco.djhtm?a=2330",
             "/z/zg/zgb/zgb0.djhtm?a=9800&b=9801&c=B&e=2026-10-1&f=2026-10-1"]:
    t = urllib.request.urlopen(urllib.request.Request(B + path, headers={"User-Agent": UA}), timeout=30).read().decode("cp950", "replace")
    log.append(f"{path}: zco0 links={len(re.findall(r'zco0/zco0', t))} upd={re.findall(r'最後更新日：([\d/]+)', t)[:1]} 資料日期={re.findall(r'資料日期：\s*(\d*)', t)[:1]} GenLink={t.count('GenLink2stk')}")
(OUT / "now.txt").write_text("\n".join(log), encoding="utf-8")
