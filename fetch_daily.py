#!/usr/bin/env python3
"""抓取台股每日收盤行情（上市 TWSE + 上櫃 TPEx），存成 CSV。

用法:
    python fetch_daily.py                       # 抓今天（台北時間）
    python fetch_daily.py --date 2026-09-23     # 抓指定日期
    python fetch_daily.py --start 2026-09-01 --end 2026-09-23   # 回補區間

輸出: data/<YYYY>/<YYYYMMDD>.csv，欄位統一如 COLUMNS。
非交易日（假日、颱風假）會自動略過。
"""
import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).resolve().parent / "data"
COLUMNS = ["date", "market", "code", "name", "open", "high", "low", "close",
           "change", "volume", "value", "transactions"]

TWSE_URL = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            "?date={d:%Y%m%d}&type=ALLBUT0999&response=json")
TPEX_URL = ("https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
            "?date={d:%Y}/{d:%m}/{d:%d}&response=json")

# TWSE 限制約 5 秒 3 次請求，超過會被暫時封鎖
REQUEST_INTERVAL = 4


def http_get_json(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def to_number(s):
    """'1,234.50' -> '1234.50'；'--'、'---'、空字串 -> ''。"""
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "---", "----", "除權息", "除權", "除息"):
        return ""
    try:
        float(s)
    except ValueError:
        return ""
    return s


def pick(fields, *names):
    """回傳第一個名稱包含任一關鍵字的欄位 index。"""
    for name in names:
        for i, f in enumerate(fields):
            if name in f:
                return i
    raise KeyError(f"找不到欄位 {names}，現有欄位: {fields}")


def parse_twse(payload, d):
    if not payload or payload.get("stat") != "OK":
        return []
    table = next((t for t in payload.get("tables", [])
                  if "每日收盤行情" in t.get("title", "") and t.get("data")), None)
    if table is None:
        return []
    f = table["fields"]
    ix = {k: pick(f, *v) for k, v in {
        "code": ("證券代號",), "name": ("證券名稱",),
        "open": ("開盤價",), "high": ("最高價",), "low": ("最低價",),
        "close": ("收盤價",), "sign": ("漲跌(+/-)",), "diff": ("漲跌價差",),
        "volume": ("成交股數",), "value": ("成交金額",),
        "transactions": ("成交筆數",),
    }.items()}
    rows = []
    for r in table["data"]:
        diff = to_number(r[ix["diff"]])
        if diff and "-" in r[ix["sign"]] and float(diff) != 0:
            diff = "-" + diff
        rows.append({
            "date": d.isoformat(), "market": "TWSE",
            "code": r[ix["code"]].strip(), "name": r[ix["name"]].strip(),
            "open": to_number(r[ix["open"]]), "high": to_number(r[ix["high"]]),
            "low": to_number(r[ix["low"]]), "close": to_number(r[ix["close"]]),
            "change": diff, "volume": to_number(r[ix["volume"]]),
            "value": to_number(r[ix["value"]]),
            "transactions": to_number(r[ix["transactions"]]),
        })
    return rows


def parse_tpex(payload, d):
    if not payload or str(payload.get("stat", "")).lower() != "ok":
        return []
    tables = payload.get("tables") or []
    table = next((t for t in tables if t.get("data")), None)
    if table is None:
        return []
    f = table["fields"]
    ix = {k: pick(f, *v) for k, v in {
        "code": ("代號",), "name": ("名稱",),
        "open": ("開盤",), "high": ("最高",), "low": ("最低",),
        "close": ("收盤",), "change": ("漲跌",),
        "volume": ("成交股數",), "value": ("成交金額",),
        "transactions": ("成交筆數",),
    }.items()}
    rows = []
    for r in table["data"]:
        rows.append({
            "date": d.isoformat(), "market": "TPEx",
            "code": r[ix["code"]].strip(), "name": r[ix["name"]].strip(),
            "open": to_number(r[ix["open"]]), "high": to_number(r[ix["high"]]),
            "low": to_number(r[ix["low"]]), "close": to_number(r[ix["close"]]),
            "change": to_number(r[ix["change"]]),
            "volume": to_number(r[ix["volume"]]),
            "value": to_number(r[ix["value"]]),
            "transactions": to_number(r[ix["transactions"]]),
        })
    return rows


def output_path(d):
    return DATA_DIR / f"{d:%Y}" / f"{d:%Y%m%d}.csv"


def fetch_day(d, force=False):
    out = output_path(d)
    if out.exists() and not force:
        print(f"{d}: 已存在，略過")
        return False
    if d.weekday() >= 5:
        print(f"{d}: 週末，略過")
        return False

    twse = parse_twse(http_get_json(TWSE_URL.format(d=d)), d)
    time.sleep(REQUEST_INTERVAL)
    tpex = parse_tpex(http_get_json(TPEX_URL.format(d=d)), d)

    if not twse and not tpex:
        print(f"{d}: 無資料（非交易日或尚未公布）")
        return False

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(twse + tpex)
    print(f"{d}: 上市 {len(twse)} 筆、上櫃 {len(tpex)} 筆 -> {out}")
    return True


def parse_date(s):
    return datetime.strptime(s.replace("/", "-"), "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", type=parse_date, help="單日 YYYY-MM-DD")
    ap.add_argument("--start", type=parse_date, help="回補起日")
    ap.add_argument("--end", type=parse_date, help="回補迄日（預設今天）")
    ap.add_argument("--force", action="store_true", help="覆寫已存在的檔案")
    args = ap.parse_args()

    today = datetime.now(TPE).date()
    if args.start:
        days = []
        d, end = args.start, args.end or today
        while d <= end:
            days.append(d)
            d += timedelta(days=1)
    else:
        days = [args.date or today]

    for i, d in enumerate(days):
        if fetch_day(d, args.force) and i < len(days) - 1:
            time.sleep(REQUEST_INTERVAL)


if __name__ == "__main__":
    main()
