#!/usr/bin/env python3
"""抓取台股每日收盤行情（上市 TWSE + 上櫃 TPEx），存成 CSV。

用法:
    python fetch_daily.py                       # 抓今天（台北時間）
    python fetch_daily.py --date 2026-09-23     # 抓指定日期
    python fetch_daily.py --start 2026-09-01 --end 2026-09-23   # 回補區間

輸出: data/<YYYY>/<YYYYMMDD>.csv，欄位統一如 COLUMNS。
已抓過的日期（已有 CSV）和已確認的非交易日（記在 data/no_trading_days.txt）
都會直接跳過、不再連線；加 --force 可強制重抓。
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
            "?date={d:%Y}/{d:%m}/{d:%d}&type=EW&response=json")  # EW = 不含權證

# TWSE 限制約 5 秒 3 次請求，超過會被暫時封鎖
REQUEST_INTERVAL = 4


def http_get_json(url, retries=5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001  (含 IncompleteRead：伺服器中途斷線)
            if attempt == retries - 1:
                raise
            wait = 10 * 2 ** attempt
            print(f"  retry {attempt + 1}/{retries - 1} in {wait}s: {e!r}", file=sys.stderr)
            time.sleep(wait)


def is_warrant(code):
    """權證、牛熊證：6 碼且以 7（上櫃）或 03~08（上市）開頭。"""
    return len(code) == 6 and (code[0] == "7" or code[:2] in
                               ("03", "04", "05", "06", "07", "08"))


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
        if is_warrant(r[ix["code"]].strip()):
            continue
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
        if is_warrant(r[ix["code"]].strip()):
            continue
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


def holidays_path():
    return DATA_DIR / "no_trading_days.txt"


def load_holidays():
    try:
        return {parse_date(line) for line in holidays_path().read_text().split() if line}
    except FileNotFoundError:
        return set()


def save_holidays(days):
    holidays_path().parent.mkdir(parents=True, exist_ok=True)
    holidays_path().write_text("".join(f"{d}\n" for d in sorted(days)))


# fetch_day 回傳值
SKIPPED, FETCHED, NO_DATA = "skipped", "fetched", "no_data"


def should_skip(d, force=False, holidays=frozenset()):
    """已抓過、週末、已知非交易日 -> 不需連線。"""
    return not force and (output_path(d).exists() or d.weekday() >= 5 or d in holidays)


def fetch_day(d, force=False, holidays=frozenset()):
    """抓單日資料。SKIPPED 表示沒有連線。"""
    if should_skip(d, force, holidays):
        return SKIPPED
    out = output_path(d)

    twse = parse_twse(http_get_json(TWSE_URL.format(d=d)), d)
    time.sleep(REQUEST_INTERVAL)
    tpex = parse_tpex(http_get_json(TPEX_URL.format(d=d)), d)
    if twse and not tpex:
        # 交易日但上櫃沒資料：可能 type 參數不被接受，改抓全部再自行過濾
        time.sleep(REQUEST_INTERVAL)
        tpex = parse_tpex(http_get_json(TPEX_URL.format(d=d).replace("&type=EW", "")), d)
    if twse and not tpex:
        raise RuntimeError("上市有資料但上櫃沒有，稍後重試")

    if not twse and not tpex:
        print(f"{d}: 無資料（非交易日或尚未公布）")
        return NO_DATA

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(twse + tpex)
    print(f"{d}: 上市 {len(twse)} 筆、上櫃 {len(tpex)} 筆 -> {out}")
    return FETCHED


def parse_date(s):
    return datetime.strptime(s.replace("/", "-"), "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", type=parse_date, help="單日 YYYY-MM-DD")
    ap.add_argument("--start", type=parse_date, help="回補起日")
    ap.add_argument("--end", type=parse_date, help="回補迄日（預設今天）")
    ap.add_argument("--force", action="store_true", help="覆寫已存在的檔案")
    ap.add_argument("--max-minutes", type=float, default=0,
                    help="回補時最多執行幾分鐘就停（0 = 不限），沒抓完的下次重跑會接著抓")
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

    holidays = load_holidays()
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    failed, counts = [], {SKIPPED: 0, FETCHED: 0, NO_DATA: 0}
    need_sleep = False
    for d in days:
        if deadline and time.monotonic() > deadline:
            print(f"已達 {args.max_minutes:g} 分鐘上限，停在 {d}；重跑同樣指令會從這裡接著抓")
            break
        if need_sleep and not should_skip(d, args.force, holidays):
            time.sleep(REQUEST_INTERVAL)  # 只在兩次連線之間等待
        try:
            result = fetch_day(d, args.force, holidays)
        except Exception as e:  # noqa: BLE001  單日失敗不中斷整個回補
            print(f"{d}: 失敗 {e!r}", file=sys.stderr)
            failed.append(d)
            need_sleep = True
            continue
        counts[result] += 1
        need_sleep = result != SKIPPED
        # 今天可能只是還沒公布，不記成非交易日
        if result == NO_DATA and d < today and d not in holidays:
            holidays.add(d)
            save_holidays(holidays)

    print(f"完成：新抓 {counts[FETCHED]} 天、跳過 {counts[SKIPPED]} 天（已抓過/週末/非交易日）、"
          f"新發現非交易日 {counts[NO_DATA]} 天、失敗 {len(failed)} 天")
    if failed:
        print(f"共 {len(failed)} 天失敗: {', '.join(map(str, failed))}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
