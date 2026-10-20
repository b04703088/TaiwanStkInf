import json, urllib.request, time
def raw(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")
def show(u):
    print("=====", u)
    try: t = raw(u)
    except Exception as e: print("ERR", e); return
    try: j = json.loads(t)
    except Exception: print(t[:800]); return
    print({k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in j.items()})
    for t in j.get("tables", []) or [j]:
        print("title", t.get("title")); print("fields", t.get("fields")); print("groups", t.get("groups"))
        for r in (t.get("data") or [])[:3]: print("  ", r)
        print("  n", len(t.get("data") or [])); print("notes", t.get("notes"))
        d = t.get("data") or []
        for r in d:
            if r and str(r[0]).strip() in ("2330", "2317", "3231"): print("  >>", r)
for u in ["https://www.twse.com.tw/rwd/zh/marginTrading/TWTA1U?date=20261016&response=json",
          "https://www.twse.com.tw/rwd/zh/marginTrading/TWTA1U?date=20261016&selectType=STOCK&response=json",
          "https://www.twse.com.tw/rwd/zh/marginTrading/TWTA1U?date=20250102&response=json"]:
    show(u); time.sleep(4)
