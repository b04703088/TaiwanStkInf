"""實測富邦分點資料每天幾點公布：台北 15:15 起每 10 分鐘查一次 10/1 的資料，到 18:50 為止。"""
import pathlib, re, time, urllib.request
from datetime import datetime, timedelta, timezone
TPE = timezone(timedelta(hours=8))
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DATE = "2026-10-1"
CODES = ["2330", "6488", "2409", "8069"]
log = OUT / "timing.txt"
def now(): return datetime.now(TPE)
def write(s):
    with log.open("a", encoding="utf-8") as f: f.write(s + "\n")
def check(code):
    url = f"https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={code}&e={DATE}&f={DATE}"
    try:
        t = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read().decode("cp950", "replace")
    except Exception as e:
        return f"ERR {e}"
    n = len(re.findall(r'zco0\.djhtm\?a=', t))
    upd = re.findall(r"最後更新日：([\d/]+)", t)
    return f"rows={n} upd={upd[:1]}"
start = now().replace(hour=15, minute=15, second=0, microsecond=0)
end = now().replace(hour=18, minute=50, second=0, microsecond=0)
write(f"job start {now():%H:%M:%S}, waiting until {start:%H:%M}")
while now() < start:
    time.sleep(30)
first_full = None
while now() < end:
    res = {c: check(c) for c in CODES}
    full = all(r.startswith("rows=") and not r.startswith("rows=0") for r in res.values())
    write(f"{now():%H:%M:%S} " + " | ".join(f"{c} {r}" for c, r in res.items()) + ("  <== 全部有資料" if full else ""))
    if full and first_full is None:
        first_full = now()
    if first_full and now() - first_full > timedelta(minutes=25):
        break
    time.sleep(600 if not first_full else 300)
write(f"first full: {first_full:%H:%M:%S}" if first_full else "until 18:50 still no data")
