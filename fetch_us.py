#!/usr/bin/env python3
"""美股連動頁用的美股日資料與財報日期。

資料來源
  Yahoo Finance chart API  https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=5y&interval=1d
      抓 config/us_supply.csv、config/us_peers.csv 用到的美股，加上 SPY、QQQ、^SOX、TSM、TWD=X
  SEC EDGAR submissions    https://data.sec.gov/submissions/CIK<10 碼>.json
      過去財報日：8-K 申報且 items 含 2.02（Results of Operations）；受理時間 16:00（美東）以後＝盤後公布
  Nasdaq                   https://api.nasdaq.com/api/analyst/<symbol>/earnings-date
      下一次財報日（預估或已公告）；SEC 抓不到時改用 /api/company/<symbol>/earnings-surprise 的最近 4 季
      下一次財報日（預估或已公告）；抓不到就只有過去的

輸出
  data/us/daily.csv     date, symbol, open, high, low, close, volume（日期為交易所當地日期；每次抓近 5 年並覆蓋）
  data/us/earnings.csv  symbol, date, time, source   time：amc 盤後／bmo 盤前／空白＝不確定；source：sec／nasdaq

用法：python fetch_us.py [--no-earnings]
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "us"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# SEC 要求 User-Agent 帶聯絡方式
SEC_UA = "TaiwanStkInf research 41898282+github-actions[bot]@users.noreply.github.com"
BASE = ["SPY", "QQQ", "^SOX", "TSM", "TWD=X"]
NO_EARNINGS = {"SPY", "QQQ", "^SOX", "TWD=X"}


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


def get(url, ua=UA, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
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
            out.append({"date": d, "symbol": sym, "open": round(m.get("regularMarketOpen") or c, 4),
                        "high": round(m.get("regularMarketDayHigh") or c, 4),
                        "low": round(m.get("regularMarketDayLow") or c, 4), "close": round(c, 4),
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


def sec_dates(sym, ciks):
    cik = ciks.get(sym.upper())
    if not cik:
        return []
    j = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", ua=SEC_UA))
    rec = j["filings"]["recent"]
    out = []
    for form, items, acc, fd in zip(rec["form"], rec["items"], rec["acceptanceDateTime"], rec["filingDate"]):
        if form != "8-K" or "2.02" not in (items or "").split(","):
            continue
        # acceptanceDateTime 例：2025-11-19T16:20:31.000Z（實際是美東時間）
        m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", acc or "")
        if not m:
            out.append({"symbol": sym, "date": fd, "time": "", "source": "sec"})
            continue
        hm = int(m.group(2)) * 100 + int(m.group(3))
        t = "amc" if hm >= 1600 else "bmo" if hm < 930 else ""
        out.append({"symbol": sym, "date": m.group(1), "time": t, "source": "sec"})
    return out


def nasdaq_past(sym):
    """SEC 抓不到時的備援：Nasdaq 最近 4 季公布日。"""
    j = json.loads(get(f"https://api.nasdaq.com/api/company/{urllib.parse.quote(sym)}/earnings-surprise", timeout=20))
    rows = (((j.get("data") or {}).get("earningsSurpriseTable") or {}).get("rows")) or []
    out = []
    for r in rows:
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", r.get("dateReported") or "")
        if m:
            out.append({"symbol": sym, "date": f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                        "time": "", "source": "nasdaq"})
    return out


def nasdaq_next(sym):
    j = json.loads(get(f"https://api.nasdaq.com/api/analyst/{urllib.parse.quote(sym)}/earnings-date", timeout=20))
    txt = ((j.get("data") or {}).get("announcement") or "")
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", txt)
    if not m:
        return None
    d = datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat()
    t = "amc" if "after" in txt.lower() else "bmo" if "before" in txt.lower() or "pre" in txt.lower() else ""
    return {"symbol": sym, "date": d, "time": t, "source": "nasdaq"}


def fetch_earnings(syms):
    p = OUT / "earnings.csv"
    rows = {}
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                rows[(r["symbol"], r["date"])] = r
    try:
        tick = json.loads(get("https://www.sec.gov/files/company_tickers.json", ua=SEC_UA))
        ciks = {v["ticker"].upper(): int(v["cik_str"]) for v in tick.values()}
    except Exception as e:  # noqa: BLE001
        print(f"SEC 代號表失敗：{e}")
        ciks = {}
    today = datetime.now(timezone.utc).date().isoformat()
    for s in syms:
        if s in NO_EARNINGS:
            continue
        try:
            got = sec_dates(s, ciks)
            print(f"{s} SEC 財報 {len(got)} 次，最近 {max((g['date'] for g in got), default='-')}")
            for g in got:
                rows[(s, g["date"])] = g
            if not got:
                for g in nasdaq_past(s):
                    rows.setdefault((s, g["date"]), g)
        except Exception as e:  # noqa: BLE001
            print(f"{s} SEC／Nasdaq 過去財報失敗：{e}")
        time.sleep(0.3)  # SEC 限每秒 10 次
        try:
            n = nasdaq_next(s)
            if n and n["date"] >= today:
                # 預估日可能改，先清掉舊的未來預估
                rows = {k: v for k, v in rows.items() if not (k[0] == s and v["source"] == "nasdaq" and k[1] >= today)}
                rows[(s, n["date"])] = n
                print(f"{s} 下次財報 {n['date']} {n['time']}")
        except Exception as e:  # noqa: BLE001
            print(f"{s} Nasdaq 失敗：{e}")
        time.sleep(0.5)
    # 同一季 SEC 已經有實際日期，就拿掉相差 10 天內的 Nasdaq 日期
    sec = {(k[0], k[1]) for k, v in rows.items() if v["source"] == "sec"}
    for k, v in list(rows.items()):
        if v["source"] == "nasdaq":
            d = datetime.fromisoformat(k[1]).date()
            if any(s == k[0] and x != k[1] and abs((datetime.fromisoformat(x).date() - d).days) <= 10 for s, x in sec):
                del rows[k]
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=["symbol", "date", "time", "source"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    print(f"wrote {p}（{len(rows)} 筆）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-earnings", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    syms = symbols()
    ok = fetch_prices(syms)
    if not a.no_earnings:
        fetch_earnings(syms)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
