"""實測富邦分點資料公布時間（修正版）：台北 15:15 起每 10 分鐘查一次，到 20:30 為止。
判斷「有資料」：
  前 15 大（zco）：最後更新日 = 當天（含年份），且有 30 個分點連結
  分點明細（zgb）：資料日期 = 當天
用法：把本檔複製成 probe.py 後推送到 probe/timing 分支。"""
import pathlib, re, time, urllib.request
from datetime import datetime, timedelta, timezone
TPE = timezone(timedelta(hours=8))
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
B = "https://fubon-ebrokerdj.fbs.com.tw"
log = OUT / "timing2.txt"
def now(): return datetime.now(TPE)
today = now().date()
DS = f"{today.year}-{today.month}-{today.day}"
def write(s):
    with log.open("a", encoding="utf-8") as f: f.write(s + "\n")
def get(path):
    return urllib.request.urlopen(urllib.request.Request(B + path, headers={"User-Agent": UA}), timeout=30).read().decode("cp950", "replace")
def zco(code):
    t = get(f"/z/zc/zco/zco.djhtm?a={code}&e={DS}&f={DS}")
    return len(re.findall(r"zco0/zco0", t)) >= 20 and f"{today:%Y/%m/%d}" in t
def zgb():
    t = get(f"/z/zg/zgb/zgb0.djhtm?a=9800&b=9801&c=B&e={DS}&f={DS}")
    return f"資料日期：{today:%Y%m%d}" in t.replace(" ", "")
start = now().replace(hour=15, minute=15, second=0, microsecond=0)
end = now().replace(hour=20, minute=30, second=0, microsecond=0)
write(f"{today} job start {now():%H:%M:%S}")
while now() < start:
    time.sleep(30)
first = {}
while now() < end and len(first) < 3:
    try:
        st = {"zco_2330": zco("2330"), "zco_8069": zco("8069"), "zgb_9801": zgb()}
    except Exception as e:
        st = {"err": str(e)}
    write(f"{now():%H:%M:%S} {st}")
    for k, v in st.items():
        if v is True and k not in first:
            first[k] = f"{now():%H:%M}"
    time.sleep(600)
write(f"first available: {first}")
