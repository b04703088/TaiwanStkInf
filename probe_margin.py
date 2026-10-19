import json, urllib.request, re
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")
def show(u):
    print("=====", u)
    try:
        t = get(u)
    except Exception as e:
        print("ERR", e); return
    try:
        j = json.loads(t)
    except Exception:
        print(t[:1500]); return
    def walk(o, p=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (dict, list)): walk(v, p+"."+k)
                else: print(p+"."+k, "=", str(v)[:200])
        elif isinstance(o, list):
            print(p, "len", len(o))
            for i, v in enumerate(o[:3]): walk(v, f"{p}[{i}]")
    walk(j)
show("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20261016&selectType=ALL&response=json")
show("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260102&selectType=MS&response=json")
m = get("https://www.tpex.org.tw/data/menu/zh-tw/menu.json")
for line in set(re.findall(r'"[^"]*margin[^"]*"', m)): print("menu:", line)
show("https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2026/10/16&response=json")
show("https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2026/10/16&id=&response=json")
show("https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=json&d=115/10/16")
for path in ["margin/balance", "margin/sbl", "margin/marginBalance"]:
    try:
        h = get("https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/transactions.html")
        print(set(re.findall(r'(?:bulletin|www/zh-tw)/[A-Za-z/]+', h)))
    except Exception as e: print("page ERR", e)
    break
