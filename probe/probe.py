import json, urllib.request, pathlib
out = pathlib.Path("probe/out"); out.mkdir(parents=True, exist_ok=True)
U = {
 "openapi": "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
 "rwd2026": "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&date=20260101",
 "rwd2027": "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&date=20270101",
}
for k, u in U.items():
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        (out / f"{k}.json").write_bytes(r)
    except Exception as e:
        (out / f"{k}.err").write_text(repr(e))
