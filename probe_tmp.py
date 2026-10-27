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


get("https://www.twse.com.tw/rwd/zh/fund/T86?date=20261023&selectType=ALLBUT0999&response=json")
get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=2026/10/23&response=json")
get("https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=20261023&response=json")
get("https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261023&response=json")
get("https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2026/10/23&response=json")
get("https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date=20261023&selectType=All&response=json")
get("https://www.tpex.org.tw/www/zh-tw/intraday/stat?date=2026/10/23&response=json")
get("https://www.tpex.org.tw/www/zh-tw/intraday/trading?date=2026/10/23&response=json")
get("https://www.twse.com.tw/rwd/zh/exRight/TWT48U?startDate=20261027&endDate=20261130&response=json")
get("https://www.tpex.org.tw/www/zh-tw/bulletin/exRight?startDate=2026/10/27&endDate=2026/11/30&response=json")
get("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", n=800)
get("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", n=3000)
get("https://www.taifex.com.tw/cht/3/futContractsDateDown",
    {"queryStartDate": "2026/10/20", "queryEndDate": "2026/10/23", "commodityId": "TXF"}, n=2500)
get("https://www.taifex.com.tw/cht/3/pcRatioDown", {"queryStartDate": "2026/10/01", "queryEndDate": "2026/10/23"}, n=1500)
get("https://www.taifex.com.tw/cht/3/largeTraderFutDown", {"queryStartDate": "2026/10/20", "queryEndDate": "2026/10/23"}, n=2500)
get("https://www.taifex.com.tw/cht/3/futDataDown",
    {"down_type": "1", "commodity_id": "TX", "queryStartDate": "2026/10/22", "queryEndDate": "2026/10/23"}, n=1500)
get("https://www.taifex.com.tw/cht/3/callsAndPutsDateDown",
    {"queryStartDate": "2026/10/22", "queryEndDate": "2026/10/23", "commodityId": "TXO"}, n=2000)
get("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate", n=1500)
