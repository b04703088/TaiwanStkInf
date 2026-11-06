#!/usr/bin/env python3
"""回補融資水位歷史（大盤彙總，不存個股檔）→ data/margin/level.csv。

融資融券頁的「融資水位（融資金額 ÷ 市值）」要跟近幾年比，但個股融資檔只從 2025-07 開始，
整批回補個股檔會讓 repo 多幾百 MB。這支只抓證交所 MI_MARGN、櫃買 margin/balance，
當場算出每市場一列彙總（融資張數、金額、融券、使用率分子分母、市值近似）就丟掉個股明細。

  · 本機已有個股融資檔的日子直接用本機檔算，不連網。
  · 只跑有每日行情檔（data/YYYY/YYYYMMDD.csv）的日子：市值要用收盤價，也順便跳過假日。
  · 已在 level.csv 的日期跳過，可重跑續補；每 20 天存一次。
  · 加權指數（index.csv）缺的月份一起補。

用法:
    python backfill_margin_level.py --start 2022-01-01            # 預設補到今天
    python backfill_margin_level.py --start 2022-01-01 --max-minutes 250
"""
import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from fetch_daily import DATA_DIR, REQUEST_INTERVAL, TPE, http_get_json, parse_date
from fetch_margin import (MARGIN_DIR, TPEX_URL, TWSE_URL, _read_csv, fetch_index,
                          output_path, parse_tpex, parse_twse, upsert)

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from margin_site import LEVEL_COLS, closes_for, level_rows  # noqa: E402

LEVEL = MARGIN_DIR / "level.csv"


def local_day(d, summary):
    rows = _read_csv(output_path(d))
    if not rows:
        return None
    return {(r["market"], r["code"]): r for r in rows}, summary.get(d.isoformat(), {})


def remote_day(d):
    twse, s1 = parse_twse(http_get_json(TWSE_URL.format(d=d)), d)
    time.sleep(REQUEST_INTERVAL)
    tpex, s2 = parse_tpex(http_get_json(TPEX_URL.format(d=d)), d)
    if not twse and not tpex:
        return None
    return ({(r["market"], r["code"]): r for r in twse + tpex},
            {s["market"]: s for s in (s1, s2) if s})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=parse_date, required=True)
    ap.add_argument("--end", type=parse_date)
    ap.add_argument("--max-minutes", type=float, default=0)
    args = ap.parse_args()

    end = args.end or datetime.now(TPE).date()
    have = {(r["date"], r["market"]) for r in _read_csv(LEVEL)}
    summary = {}
    for r in _read_csv(MARGIN_DIR / "summary.csv"):
        summary.setdefault(r["date"], {})[r["market"]] = r
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    buf, n_local, n_remote, failed = [], 0, 0, []

    def flush():
        if buf:
            upsert(LEVEL, LEVEL_COLS, buf, lambda r: (r["date"], r["market"]))
            buf.clear()

    d = args.start
    while d <= end:
        cur, d = d, d + timedelta(days=1)
        ds = cur.isoformat()
        if (ds, "TWSE") in have and (ds, "TPEx") in have:
            continue
        closes = closes_for(DATA_DIR, ds)
        if not closes:
            continue
        if deadline and time.monotonic() > deadline:
            print(f"已達 {args.max_minutes:g} 分鐘上限，停在 {ds}；重跑會接著補")
            break
        got = local_day(cur, summary)
        if got:
            n_local += 1
        else:
            try:
                got = remote_day(cur)
            except Exception as e:  # noqa: BLE001  單日失敗不中斷
                print(f"{ds}: 失敗 {e!r}", file=sys.stderr)
                failed.append(ds)
                time.sleep(REQUEST_INTERVAL)
                continue
            time.sleep(REQUEST_INTERVAL)
            if not got:
                print(f"{ds}: 無融資資料")
                continue
            n_remote += 1
        rows = level_rows(ds, got[0], closes, got[1])
        buf.extend(rows)
        print(f"{ds}: {' '.join(r['market'] + ' ' + str(round(int(r['fin_amount'] or 0) / 1e8)) + '億' for r in rows)}")
        if len(buf) >= 40:
            flush()
    flush()

    # 加權指數：level.csv 有但 index.csv 沒有的月份
    have_ix = {r["date"][:7] for r in _read_csv(MARGIN_DIR / "index.csv")}
    months = sorted({r["date"][:7] for r in _read_csv(LEVEL)} - have_ix)
    if months:
        n = fetch_index([datetime.strptime(m + "-01", "%Y-%m-%d").date() for m in months])
        print(f"加權指數補 {len(months)} 個月、{n} 筆")
    print(f"完成：本機 {n_local} 天、連網 {n_remote} 天、失敗 {len(failed)} 天")
    if failed:
        print("失敗: " + ", ".join(failed), file=sys.stderr)


if __name__ == "__main__":
    main()
