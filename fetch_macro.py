#!/usr/bin/env python3
"""資金水龍頭用的國際／匯率日資料：台幣匯率、美元指數、美 10 年債、VIX、美國公司債信用利差。

資料來源
  Yahoo Finance chart API  https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=2y&interval=1d
      TWD=X（美元兌台幣）、DX-Y.NYB（美元指數）、^TNX（美 10 年債殖利率）、^VIX
  FRED CSV                 https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>
      BAMLH0A0HYM2（高收益債利差 OAS）、BAMLC0A0CM（投資級債利差 OAS）
      Yahoo 抓不到時改用 FRED：DEXTAUS、DTWEXBGS（廣義美元指數）、DGS10、VIXCLS

輸出 data/macro/daily.csv：date, series, value, source
  series：usdtwd、dxy、us10y（%）、vix、hy_oas（%）、ig_oas（%）
  每次抓近 2 年並覆蓋重疊日期，所以重跑沒關係。

用法：python fetch_macro.py
"""
import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "macro" / "daily.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# series: [(來源, 代號), ...]，依序嘗試，第一個成功的就用
SERIES = {
    "usdtwd": [("yahoo", "TWD=X"), ("fred", "DEXTAUS")],
    "dxy": [("yahoo", "DX-Y.NYB"), ("fred", "DTWEXBGS")],
    "us10y": [("yahoo", "^TNX"), ("fred", "DGS10")],
    "vix": [("yahoo", "^VIX"), ("fred", "VIXCLS")],
    "hy_oas": [("fred", "BAMLH0A0HYM2")],
    "ig_oas": [("fred", "BAMLC0A0CM")],
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def yahoo(sym):
    q = urllib.parse.quote(sym)
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range=2y&interval=1d"))
    res = j["chart"]["result"][0]
    out = {}
    for ts, v in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if v is None:
            continue
        # 以交易所當地日期為準（gmtoffset），台幣報價用台北時間
        d = datetime.fromtimestamp(ts + res["meta"].get("gmtoffset", 0), timezone.utc).date().isoformat()
        out[d] = round(v, 4)
    return out


def fred(sid):
    text = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
    out = {}
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if len(row) == 2 and row[1] not in ("", "."):
            out[row[0]] = float(row[1])
    return {d: v for d, v in out.items() if d >= f"{datetime.now().year - 2}-01-01"}


def main():
    rows = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[(r["date"], r["series"])] = r
    ok = 0
    for name, tries in SERIES.items():
        for src, sym in tries:
            try:
                data = yahoo(sym) if src == "yahoo" else fred(sym)
            except Exception as e:  # noqa: BLE001  一個來源壞掉就換下一個
                print(f"{name} {src}:{sym} 失敗：{e}")
                time.sleep(2)
                continue
            if not data:
                print(f"{name} {src}:{sym} 沒資料")
                continue
            # 換來源時清掉舊的，避免兩種口徑混在一起
            rows = {k: v for k, v in rows.items() if k[1] != name or v["source"] == f"{src}:{sym}"}
            for d, v in data.items():
                rows[(d, name)] = {"date": d, "series": name, "value": v, "source": f"{src}:{sym}"}
            print(f"{name} {src}:{sym} {len(data)} 筆，最新 {max(data)} = {data[max(data)]}")
            ok += 1
            break
        time.sleep(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "series", "value", "source"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    print(f"wrote {OUT}（{ok}/{len(SERIES)} 個序列更新）")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
