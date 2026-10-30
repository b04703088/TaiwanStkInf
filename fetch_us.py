#!/usr/bin/env python3
"""美股連動頁用的美股日資料與財報日期。

資料來源
  Yahoo Finance chart API  https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=5y&interval=1d
      抓 config/us_supply.csv、config/us_peers.csv 用到的美股，加上 SPY、QQQ、^SOX、TSM、TWD=X
  Nasdaq 財報行事曆        https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
      每天公布財報的公司與時間（盤後／盤前）。平日重查 10 天前到 45 天後；未來日期是預估，會改期。
      （SEC EDGAR 從 GitHub runner 回 403，所以不用）

輸出
  data/us/daily.csv     date, symbol, open, high, low, close, volume（日期為交易所當地日期；每次抓近 5 年並覆蓋）
  data/us/earnings.csv  symbol, date, time, source   time：amc 盤後／bmo 盤前／空白＝不確定

用法：python fetch_us.py [--no-earnings] [--earnings-since 2022-01-01]
"""
import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "us"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BASE = ["SPY", "QQQ", "^SOX", "TSM", "TWD=X"]
NO_EARNINGS = {"SPY", "QQQ", "^SOX", "TWD=X"}
TIME = {"time-after-hours": "amc", "time-pre-market": "bmo"}


def symbols():
    out = list(BASE)
    for f, col in (("us_supply.csv", "us"), ("us_peers.csv", "us")):
        p = ROOT / "config" / f
        if p.exists():
            with p.open(encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    if r[col] and r[col] not in out:
                        out.append(r[col])
    return out


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def yahoo(sym):
    q = urllib.parse.quote(sym)
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range=5y&interval=1d"))
    res = j["chart"]["result"][0]
    qt = res["indicators"]["quote"][0]
    off = res["meta"].get("gmtoffset", 0)
    out = []
    for i, ts in enumerate(res["timestamp"]):
        c = qt["close"][i]
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + off, timezone.utc).date().isoformat()
        o, h, lo = (qt[k][i] for k in ("open", "high", "low"))
        out.append({"date": d, "symbol": sym, "open": round(o if o is not None else c, 4),
                    "high": round(h if h is not None else c, 4), "low": round(lo if lo is not None else c, 4),
                    "close": round(c, 4), "volume": qt["volume"][i] or 0})
    # 收盤後幾小時內，當天的 K 棒常還沒進 timestamp，只在 meta 裡
    m = res["meta"]
    if m.get("regularMarketTime") and m.get("regularMarketPrice"):
        d = datetime.fromtimestamp(m["regularMarketTime"] + off, timezone.utc).date().isoformat()
        if out and d > out[-1]["date"]:
            c = m["regularMarketPrice"]
            r4 = lambda k: round(m[k], 4) if m.get(k) else ""  # noqa: E731  meta 常沒有開盤價，留空
            out.append({"date": d, "symbol": sym, "open": r4("regularMarketOpen"),
                        "high": r4("regularMarketDayHigh"), "low": r4("regularMarketDayLow"), "close": round(c, 4),
                        "volume": m.get("regularMarketVolume") or 0})
    return out


def fetch_prices(syms):
    p = OUT / "daily.csv"
    rows = {}
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                rows[(r["date"], r["symbol"])] = r
    ok = 0
    for s in syms:
        try:
            data = yahoo(s)
        except Exception as e:  # noqa: BLE001  一檔失敗不影響其他
            print(f"{s} 失敗：{e}")
            time.sleep(2)
            continue
        # Yahoo 的價格會因分割回溯調整，所以整檔換掉
        rows = {k: v for k, v in rows.items() if k[1] != s}
        for r in data:
            rows[(r["date"], s)] = r
        print(f"{s} {len(data)} 筆，最新 {data[-1]['date']} {data[-1]['close']}" if data else f"{s} 沒資料")
        ok += bool(data)
        time.sleep(0.5)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=["date", "symbol", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    print(f"wrote {p}（{ok}/{len(syms)} 檔更新）")
    return ok


def nasdaq_day(d):
    """Nasdaq 財報行事曆某一天：{代號: amc／bmo／空白}。"""
    j = json.loads(get(f"https://api.nasdaq.com/api/calendar/earnings?date={d}", timeout=30))
    rows = ((j.get("data") or {}).get("rows")) or []
    return {r.get("symbol", "").upper(): TIME.get(r.get("time"), "") for r in rows}


def fetch_earnings(syms, since, ahead=45):
    """從 since 到今天之後 ahead 天，逐日查 Nasdaq 行事曆。未來的日期每次重抓（公司會改期）。"""
    p = OUT / "earnings.csv"
    rows = {}
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                rows[(r["symbol"], r["date"])] = r
    want = {s.upper() for s in syms} - NO_EARNINGS
    today = datetime.now(timezone.utc).date()
    rows = {k: v for k, v in rows.items() if k[1] < since.isoformat()}  # 查詢範圍內整段重建
    d, n, fail = since, 0, 0
    while d <= today + timedelta(days=ahead):
        if d.weekday() < 5:
            try:
                got = nasdaq_day(d.isoformat())
                for s in want & set(got):
                    rows[(s, d.isoformat())] = {"symbol": s, "date": d.isoformat(), "time": got[s], "source": "nasdaq"}
                    n += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                print(f"{d} 失敗：{e}")
                if fail >= 10 and n == 0:
                    print("Nasdaq 連續失敗，保留舊資料")
                    return
            time.sleep(0.4)
        d += timedelta(days=1)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=["symbol", "date", "time", "source"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    print(f"wrote {p}（{len(rows)} 筆，這次查到 {n} 筆，失敗 {fail} 天）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-earnings", action="store_true")
    ap.add_argument("--earnings-since", help="財報日從哪天開始重查（預設 10 天前；回補用 2022-01-01）")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    syms = symbols()
    ok = fetch_prices(syms)
    if not a.no_earnings:
        since = (datetime.fromisoformat(a.earnings_since).date() if a.earnings_since
                 else datetime.now(timezone.utc).date() - timedelta(days=10))
        fetch_earnings(syms, since)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
