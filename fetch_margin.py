#!/usr/bin/env python3
"""抓取融資融券餘額（上市 TWSE MI_MARGN + 上櫃 TPEx margin/balance）、不限用途款項借貸擔保品與加權指數。

用法:
    python fetch_margin.py                       # 抓今天（台北時間）
    python fetch_margin.py --start 2025-07-01    # 回補區間（已抓過的日期跳過）

輸出:
  data/margin/<YYYY>/<YYYYMMDD>.csv  個股融資融券（單位：張），欄位見 COLUMNS
  data/margin/summary.csv            大盤：上市／上櫃融資張數、融資金額（元）、融券張數
  data/margin/index.csv              加權指數收盤、成交金額（FMTQIK，每月一次請求）
  data/pledge/<YYYY>/<YYYYMMDD>.csv  個股借貸款項擔保品（TWTA1U，上市櫃得融資融券股票，單位：張）：
                                     證券商不限用途款項借貸、證金擔保放款、證券商證券業務借貸款項
非交易日沿用 data/no_trading_days.txt（與 fetch_daily.py 共用）。
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timedelta

from fetch_daily import (DATA_DIR, REQUEST_INTERVAL, TPE, http_get_json, load_holidays,
                         parse_date, save_holidays, to_number)

MARGIN_DIR = DATA_DIR / "margin"
COLUMNS = ["date", "market", "code", "name",
           "fin_buy", "fin_sell", "fin_cash", "fin_prev", "fin_bal", "fin_limit",
           "sht_buy", "sht_sell", "sht_cash", "sht_prev", "sht_bal", "sht_limit", "offset", "note"]
SUMMARY_COLS = ["date", "market", "fin_lots", "fin_amount", "sht_lots"]
INDEX_COLS = ["date", "taiex", "value"]

TWSE_URL = ("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
            "?date={d:%Y%m%d}&selectType=ALL&response=json")
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance?date={d:%Y}/{d:%m}/{d:%d}&response=json"
PLEDGE_COLUMNS = ["date", "market", "code", "name", "ul_prev", "ul_new", "ul_sell", "ul_cash", "ul_swap", "ul_bal",
                  "ul_limit", "sf_bal", "bl_bal", "note"]
PLEDGE_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/TWTA1U?date={d:%Y%m%d}&response=json"
PLEDGE_DIR = DATA_DIR / "pledge"
FMTQIK_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={d:%Y%m}01&response=json"


def _int(s):
    v = to_number(s)
    return str(int(float(v))) if v != "" else ""


def parse_twse(payload, d):
    """回傳 (個股 rows, summary row 或 None)。"""
    if not payload or payload.get("stat") != "OK":
        return [], None
    tables = payload.get("tables") or []
    stat = next((t for t in tables if "信用交易統計" in t.get("title", "")), None)
    detail = next((t for t in tables if "融資融券彙總" in t.get("title", "")), None)
    if not detail or not detail.get("data"):
        return [], None
    rows = []
    for r in detail["data"]:
        if len(r) < 16:
            continue
        rows.append({"date": d.isoformat(), "market": "TWSE", "code": r[0].strip(), "name": r[1].strip(),
                     "fin_buy": _int(r[2]), "fin_sell": _int(r[3]), "fin_cash": _int(r[4]),
                     "fin_prev": _int(r[5]), "fin_bal": _int(r[6]), "fin_limit": _int(r[7]),
                     "sht_buy": _int(r[8]), "sht_sell": _int(r[9]), "sht_cash": _int(r[10]),
                     "sht_prev": _int(r[11]), "sht_bal": _int(r[12]), "sht_limit": _int(r[13]),
                     "offset": _int(r[14]), "note": r[15].strip()})
    summary = None
    if stat:
        by = {x[0]: x for x in stat.get("data", [])}
        fin = next((v for k, v in by.items() if k.startswith("融資(")), None)
        sht = next((v for k, v in by.items() if k.startswith("融券(")), None)
        amt = next((v for k, v in by.items() if k.startswith("融資金額")), None)
        if fin and amt:
            summary = {"date": d.isoformat(), "market": "TWSE", "fin_lots": _int(fin[5]),
                       "fin_amount": str(int(float(to_number(amt[5]))) * 1000),
                       "sht_lots": _int(sht[5]) if sht else ""}
    return rows, summary


def parse_tpex(payload, d):
    if not payload or not payload.get("tables"):
        return [], None
    t = payload["tables"][0]
    if not t.get("data"):
        return [], None
    f = t["fields"]

    def col(name):
        return f.index(name)
    ix = {k: col(n) for k, n in [("fin_prev", "前資餘額(張)"), ("fin_buy", "資買"), ("fin_sell", "資賣"),
                                  ("fin_cash", "現償"), ("fin_bal", "資餘額"), ("fin_limit", "資限額"),
                                  ("sht_prev", "前券餘額(張)"), ("sht_sell", "券賣"), ("sht_buy", "券買"),
                                  ("sht_cash", "券償"), ("sht_bal", "券餘額"), ("sht_limit", "券限額"),
                                  ("offset", "資券相抵(張)")]}
    rows = []
    for r in t["data"]:
        row = {"date": d.isoformat(), "market": "TPEx", "code": r[0].strip(), "name": r[1].strip(),
               "note": (r[-1] or "").strip()}
        row.update({k: _int(r[i]) for k, i in ix.items()})
        rows.append(row)
    summary = None
    sm = {(x[1] or "").strip(): x for x in t.get("summary") or []}
    tot, amt = sm.get("合計(張)"), next((v for k, v in sm.items() if k.startswith("融資金")), None)
    if tot and amt:
        summary = {"date": d.isoformat(), "market": "TPEx", "fin_lots": _int(tot[ix["fin_bal"]]),
                   "fin_amount": str(int(float(to_number(amt[ix["fin_bal"]]))) * 1000),
                   "sht_lots": _int(tot[ix["sht_bal"]])}
    return rows, summary


def parse_pledge(payload, d):
    """借貸款項擔保品餘額表：依 groups 找各類別起始欄（融資／證券業務借貸款項／不限用途／證金擔保放款／證金交割融資）。"""
    if not payload or payload.get("stat") != "OK" or not payload.get("data"):
        return []
    starts = {g.get("title", ""): g["start"] for g in payload.get("groups") or []}
    ul = next((v for k, v in starts.items() if "不限用途" in k), 15)
    bl = next((v for k, v in starts.items() if "證券業務借貸" in k), 8)
    sf = next((v for k, v in starts.items() if "擔保放款" in k), 22)
    f = payload.get("fields") or []
    mkt = f.index("市場別") if "市場別" in f else None
    rows = []
    for r in payload["data"]:
        if len(r) < ul + 7:
            continue
        m = r[mkt] if mkt is not None else ""
        rows.append({"date": d.isoformat(), "market": "TWSE" if "集中" in m else "TPEx",
                     "code": r[0].strip(), "name": r[1].strip(),
                     "ul_prev": _int(r[ul]), "ul_new": _int(r[ul + 1]), "ul_sell": _int(r[ul + 2]),
                     "ul_cash": _int(r[ul + 3]), "ul_swap": _int(r[ul + 4]), "ul_bal": _int(r[ul + 5]),
                     "ul_limit": _int(r[ul + 6]), "sf_bal": _int(r[sf + 5]), "bl_bal": _int(r[bl + 5]),
                     "note": (r[-1] or "").strip()})
    return rows


def pledge_path(d):
    return PLEDGE_DIR / f"{d:%Y}" / f"{d:%Y%m%d}.csv"


def output_path(d):
    return MARGIN_DIR / f"{d:%Y}" / f"{d:%Y%m%d}.csv"


def _read_csv(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write_csv(p, cols, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def upsert(path, cols, new_rows, key):
    rows = {key(r): r for r in _read_csv(path)}
    rows.update({key(r): r for r in new_rows})
    _write_csv(path, cols, [rows[k] for k in sorted(rows)])


SKIPPED, FETCHED, NO_DATA = "skipped", "fetched", "no_data"


def fetch_day(d, force=False, holidays=frozenset()):
    if not force and (d.weekday() >= 5 or d in holidays):
        return SKIPPED
    need_m = force or not output_path(d).exists()
    need_p = force or not pledge_path(d).exists()
    if not need_m and not need_p:
        return SKIPPED
    if need_m:
        if fetch_margin_day(d) == NO_DATA:
            return NO_DATA
        if need_p:
            time.sleep(REQUEST_INTERVAL)
    if need_p and fetch_pledge_day(d) == NO_DATA and not need_m:
        return NO_DATA
    return FETCHED


def fetch_pledge_day(d):
    rows = parse_pledge(http_get_json(PLEDGE_URL.format(d=d)), d)
    if not rows:
        print(f"{d}: 擔保品餘額無資料")
        return NO_DATA
    _write_csv(pledge_path(d), PLEDGE_COLUMNS, rows)
    print(f"{d}: 不限用途借貸擔保品 {len(rows)} 筆")
    return FETCHED


def fetch_margin_day(d):
    twse, s1 = parse_twse(http_get_json(TWSE_URL.format(d=d)), d)
    time.sleep(REQUEST_INTERVAL)
    tpex, s2 = parse_tpex(http_get_json(TPEX_URL.format(d=d)), d)
    if not twse and not tpex:
        print(f"{d}: 無資料（非交易日或尚未公布）")
        return NO_DATA
    if not twse or not tpex:
        raise RuntimeError(f"上市 {len(twse)} 筆、上櫃 {len(tpex)} 筆，只有一邊有資料，稍後重試")
    _write_csv(output_path(d), COLUMNS, twse + tpex)
    sums = [s for s in (s1, s2) if s]
    if sums:
        upsert(MARGIN_DIR / "summary.csv", SUMMARY_COLS, sums, lambda r: (r["date"], r["market"]))
    print(f"{d}: 上市 {len(twse)} 筆、上櫃 {len(tpex)} 筆、大盤 {len(sums)} 筆")
    return FETCHED


def fetch_index(months):
    """加權指數：FMTQIK 一次回傳整個月。"""
    rows = []
    for m in months:
        p = http_get_json(FMTQIK_URL.format(d=m))
        for r in (p or {}).get("data") or []:
            y, mo, dd = r[0].split("/")
            rows.append({"date": f"{int(y) + 1911}-{mo}-{dd}", "taiex": to_number(r[4]), "value": to_number(r[2])})
        time.sleep(REQUEST_INTERVAL)
    if rows:
        upsert(MARGIN_DIR / "index.csv", INDEX_COLS, rows, lambda r: r["date"])
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", type=parse_date, help="單日 YYYY-MM-DD")
    ap.add_argument("--start", type=parse_date, help="回補起日")
    ap.add_argument("--end", type=parse_date, help="回補迄日（預設今天）")
    ap.add_argument("--force", action="store_true", help="覆寫已存在的檔案")
    ap.add_argument("--max-minutes", type=float, default=0, help="最多執行幾分鐘（0 = 不限）")
    args = ap.parse_args()

    today = datetime.now(TPE).date()
    if args.start:
        days, d, end = [], args.start, args.end or today
        while d <= end:
            days.append(d)
            d += timedelta(days=1)
    else:
        days = [args.date or today]

    holidays = load_holidays()
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    failed, counts, fetched_months = [], {SKIPPED: 0, FETCHED: 0, NO_DATA: 0}, set()
    for d in days:
        if deadline and time.monotonic() > deadline:
            print(f"已達 {args.max_minutes:g} 分鐘上限，停在 {d}；重跑會接著抓")
            break
        try:
            result = fetch_day(d, args.force, holidays)
        except Exception as e:  # noqa: BLE001  單日失敗不中斷整個回補
            print(f"{d}: 失敗 {e!r}", file=sys.stderr)
            failed.append(d)
            time.sleep(REQUEST_INTERVAL)
            continue
        counts[result] += 1
        if result != SKIPPED:
            time.sleep(REQUEST_INTERVAL)
        if result == FETCHED:
            fetched_months.add(d.replace(day=1))
        if result == NO_DATA and d < today and d not in holidays:
            holidays.add(d)
            save_holidays(holidays)

    # 指數：本次有新資料的月份；index.csv 缺的月份也補
    have = {r["date"][:7] for r in _read_csv(MARGIN_DIR / "index.csv")}
    for p in MARGIN_DIR.glob("[0-9][0-9][0-9][0-9]/*.csv"):
        m = datetime.strptime(p.stem, "%Y%m%d").date().replace(day=1)
        if m.strftime("%Y-%m") not in have:
            fetched_months.add(m)
    try:
        n = fetch_index(sorted(fetched_months))
        print(f"加權指數：{len(fetched_months)} 個月、{n} 筆")
    except Exception as e:  # noqa: BLE001
        print(f"加權指數失敗 {e!r}", file=sys.stderr)

    print(f"完成：新抓 {counts[FETCHED]} 天、跳過 {counts[SKIPPED]} 天、新發現非交易日 {counts[NO_DATA]} 天、失敗 {len(failed)} 天")
    if failed:
        print(f"失敗: {', '.join(map(str, failed))}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
