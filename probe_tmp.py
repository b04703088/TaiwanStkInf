"""暫時用：檢查新資料來源的格式（GitHub 主機才連得到交易所）。"""
import json
import ssl
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url, data=None, n=1500):
    print("=" * 30, url, data or "")
    try:
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            print("status", r.status, r.headers.get("Content-Type"), len(raw))
    except Exception as e:  # noqa: BLE001
        print("ERR", repr(e))
        return
    for enc in ("utf-8", "big5", "cp950"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        txt = raw.decode("utf-8", "replace")
    try:
        j = json.loads(txt)
    except ValueError:
        print(txt[:n])
        return
    def show(o, ind=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, list):
                    print(ind, k, f"list[{len(v)}]")
                    for x in v[:3]:
                        if isinstance(x, dict) and ("data" in x or "fields" in x):
                            show(x, ind + "    ")
                        else:
                            print(ind, "   ", json.dumps(x, ensure_ascii=False)[:600])
                    if v and isinstance(v[-1], list):
                        print(ind, "   last:", json.dumps(v[-1], ensure_ascii=False)[:600])
                elif isinstance(v, dict):
                    print(ind, k, "{")
                    show(v, ind + "    ")
                else:
                    print(ind, k, "=", json.dumps(v, ensure_ascii=False)[:300])
        else:
            print(json.dumps(o, ensure_ascii=False)[:n])
    show(j)



get("https://www.twse.com.tw/rwd/zh/fund/T86?date=20261022&selectType=ALLBUT0999&response=json")
get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=2026/10/22&response=json")
get("https://www.twse.com.tw/rwd/zh/fund/T86?date=20220103&selectType=ALLBUT0999&response=json", n=300)
get("https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261022&response=json")
get("https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2026/10/22&response=json")
get("https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date=20261022&selectType=All&response=json")
for q in ["type=Daily&date=2026/10/22", "date=2026/10/22&type=AL", "date=2026/10/22&sect=AL&type=Daily", "d=2026/10/22", "date=2026/10/22&stkno=&type=all"]:
    get("https://www.tpex.org.tw/www/zh-tw/intraday/stat?" + q + "&response=json")
get("https://www.tpex.org.tw/www/zh-tw/intraday/statist?date=2026/10/22&response=json")
get("https://www.tpex.org.tw/www/zh-tw/afterTrading/dayTrading?date=2026/10/22&response=json")
get("https://www.tpex.org.tw/web/stock/trading/intraday_trading/intraday_trading_list_result.php?l=zh-tw&d=115/10/22&s=0,asc", n=800)
get("https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=2026/10/27&endDate=2026/11/30&response=json", n=800)
get("https://www.tpex.org.tw/www/zh-tw/bulletin/exRightPre?response=json", n=800)
get("https://www.taifex.com.tw/cht/3/futContractsDateDown",
    {"queryStartDate": "2026/10/01", "queryEndDate": "2026/10/22", "commodityId": "TXF"}, n=1500)
get("https://www.taifex.com.tw/cht/3/futContractsDateDown",
    {"queryStartDate": "2026/10/01", "queryEndDate": "2026/10/22", "commodityId": ""}, n=1500)
get("https://www.taifex.com.tw/cht/3/callsAndPutsDateDown",
    {"queryStartDate": "2026/10/01", "queryEndDate": "2026/10/22", "commodityId": "TXO"}, n=1500)
get("https://www.taifex.com.tw/cht/3/totalTableDateDown",
    {"queryStartDate": "2026/10/01", "queryEndDate": "2026/10/22"}, n=1500)
get("https://www.taifex.com.tw/cht/3/pcRatioDown", {"queryStartDate": "2022/01/01", "queryEndDate": "2026/10/22"}, n=300)
get("https://www.taifex.com.tw/cht/3/largeTraderFutDown", {"queryStartDate": "2025/10/20", "queryEndDate": "2026/10/22"}, n=300)
