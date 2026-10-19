import json, urllib.request, time
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))
j = get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20261016&selectType=ALL&response=json")
t0, t1 = j["tables"]
print("T0", t0["fields"]); [print(" ", r) for r in t0["data"]]; print(t0.get("notes"))
print("T1", t1["fields"]); [print(" ", r) for r in t1["data"][:4]]; print(t1["data"][-2:]); print(t1.get("notes"))
codes=[r[0] for r in t1["data"]]; print("2330" in codes, "0050" in codes, len([c for c in codes if c.startswith("0")]))
time.sleep(4)
j = get("https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2026/10/16&response=json")
t = j["tables"][0]; print("TP", t["fields"]); [print(" ", r) for r in t["data"][:4]]; print("SUM", t["summary"])
time.sleep(4)
j = get("https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2026/10/18&response=json"); print("tpex holiday", j.get("stat"), len(j["tables"][0]["data"]) if j.get("tables") else None)
time.sleep(4)
j = get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20261018&selectType=ALL&response=json"); print("twse holiday", j.get("stat"), j.get("tables") and len(j["tables"]))
time.sleep(4)
j = get("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20261001&response=json"); print("FMTQIK", j.get("fields"), j.get("data", [])[:2])
time.sleep(4)
j = get("https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2024/10/16&response=json"); print("tpex 2024", len(j["tables"][0]["data"]))
time.sleep(4)
j = get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20241016&selectType=ALL&response=json"); print("twse 2024", len(j["tables"][1]["data"]))
