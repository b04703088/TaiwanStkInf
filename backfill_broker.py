#!/usr/bin/env python3
"""回補過去的分點資料（前 15 大），給 broker_score.py 評分用。建議在自己電腦上跑，不佔 GitHub Actions 分鐘數。

一天約 900 檔、30 分鐘左右（成交金額 ≥ 3000 萬）；--min-value 1e8 只抓 1 億以上，約快一半。
從 --end 往回抓到 --start，已抓過的股票會略過，所以中斷後重跑會接著補。
富邦網站查不到資料（超過網站保留期間）連續 3 個交易日就停。

用法：
  python backfill_broker.py --start 2026-07-01
  python backfill_broker.py --start 2026-04-01 --end 2026-06-30 --min-value 1e8
抓完記得 commit：git add data/broker && git commit -m "data: backfill broker" && git push
"""
import argparse
import sys
from pathlib import Path

import fetch_broker as F

STOP_AFTER_EMPTY = 3


def trading_days(start, end):
    files = sorted(p for p in F.DATA.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8)
    days = [f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:8]}" for p in files]
    return [d for d in days if start <= d <= end]


def earliest_broker_day():
    files = sorted(p for p in (F.OUT).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8)
    s = files[0].stem if files else None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if s else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="最早要補到哪天 YYYY-MM-DD")
    ap.add_argument("--end", help="從哪天開始往回補（預設：現有分點資料最早一天的前一天）")
    ap.add_argument("--min-value", type=float, default=F.MIN_VALUE, help="成交金額門檻（元，預設 3000 萬）")
    a = ap.parse_args(argv)
    end = a.end
    if not end:
        first = earliest_broker_day()
        end = first if first else "9999-12-31"
    days = [d for d in trading_days(a.start, end) if not (a.end is None and d == end)]
    print(f"要補 {len(days)} 個交易日：{days[-1] if days else '-'} → {days[0] if days else '-'}")
    empty = 0
    for i, d in enumerate(reversed(days), 1):
        print(f"[{i}/{len(days)}] {d}")
        try:
            F.main(["--date", d, "--min-value", str(a.min_value), "--max-minutes", "600"])
        except KeyboardInterrupt:
            print("中斷；每 200 檔存一次檔，重跑會從上次存檔處接著補")
            return 1
        rp, _ = F.out_paths(d)
        if rp.exists() and len(rp.read_text(encoding="utf-8").splitlines()) > 1:
            empty = 0
        else:
            empty += 1
            if empty >= STOP_AFTER_EMPTY:
                print(f"連續 {empty} 天查不到分點資料，應該已超過網站保留期間，停止")
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
