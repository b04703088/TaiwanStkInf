import json, urllib.request, re, time
def raw(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")
def show(u):
    print("=====", u)
    try: j = json.loads(raw(u))
    except Exception as e: print("ERR", e); return
    print({k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in j.items()})
    for t in j.get("tables", []) or [j]:
        print("title", t.get("title")); print("fields", t.get("fields"))
        for r in (t.get("data") or [])[:3]: print("  ", r)
        print("  n", len(t.get("data") or [])); print("summary", t.get("summary")); print("notes", t.get("notes"))
show("https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261016&response=json")
time.sleep(4)
for p in ["sbl", "transactions"]:
    h = raw(f"https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/{p}.html")
    print(p, set(re.findall(r'(?:bulletin|www/zh-tw)/[A-Za-z/]+', h)), set(re.findall(r'["\'](/[^"\']*\.js)["\']', h)))
    time.sleep(3)
show("https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2026/10/16&response=json")
time.sleep(4)
show("https://www.twse.com.tw/rwd/zh/lending/TWT72U?date=20261016&response=json")
