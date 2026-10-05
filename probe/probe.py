import pathlib, re, json, time, urllib.request
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
def api(name, body):
    t = time.time()
    r = urllib.request.urlopen(urllib.request.Request(f"https://mops.twse.com.tw/mops/api/{name}", data=json.dumps(body).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json", "Referer": "https://mops.twse.com.tw/mops/"}), timeout=60)
    d = json.loads(r.read()); log.append(f"{name} {body} -> {d.get('code')} {d.get('message')} {time.time()-t:.1f}s")
    return d
subs = []
import datetime
day = datetime.date(2026, 7, 1)
while day <= datetime.date(2026, 10, 2):
    if day.weekday() < 5:
        try:
            d = api("t05st02", {"year": str(day.year - 1911), "month": f"{day.month:02d}", "day": f"{day.day:02d}"})
            for x in (d.get("result") or {}).get("data") or []:
                if re.search(r"[轉交]換公司債", x[4]): subs.append(x)
        except Exception as e:
            log.append(f"ERR {day} {e!r}")
        time.sleep(1.0)
    day += datetime.timedelta(days=1)
(OUT / "subjects.json").write_text(json.dumps(subs, ensure_ascii=False, indent=0), encoding="utf-8")
# 詳細內容：每種主旨類型挑幾則
pick, seen = [], set()
for x in subs:
    s = x[4]
    k = "board" if "董事會" in s and "決議" in s else "eff" if "生效" in s else "price" if "轉換價格" in s or "訂定" in s else "other"
    if "私募" in s or "海外" in s: k = "skip"
    if sum(1 for p in pick if p[0] == k) < 4 and k != "skip":
        pick.append((k, x))
for k, x in pick:
    try:
        d = api("t05st02_detail", x[5]["parameters"])
        (OUT / f"detail_{k}_{x[2]}_{x[5]['parameters']['enterDate']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log.append(f"ERR detail {x[2]} {e!r}")
    time.sleep(1.0)
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
