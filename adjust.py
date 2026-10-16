#!/usr/bin/env python3
"""還原股價：用 data/adjust/events.csv 的還原因子，把 data/<YYYY>/*.csv 的原始價格換算成還原價。

做法（向後還原，最新一天的價格不變，越早的價格依之後發生的事件往下／往上調）
  還原價(t) = 原始價(t) × Π factor（所有事件日 > t 的事件）
  factor = 事件後參考價 / 事件前收盤價（除權息、減資、面額變更、ETF 分割都一樣算法）
  成交量要反向調整：還原量(t) = 原始量(t) ÷ 同一個連乘（分割 1 拆 4，以前的 1 張等於現在 4 張）

用法
  python adjust.py 2330                          # 印出 2330 全部日期的原始價與還原價（CSV）
  python adjust.py 0050 --start 2025-01-01 --end 2025-12-31
  python adjust.py 2330 --events                 # 只列 2330 的事件與因子

程式裡用：
  import adjust
  ev = adjust.load_events()
  f = adjust.factor_after(ev, "0050", "2025-06-17")   # 2025-06-17 的價格要乘的倍數
  rows = adjust.adjust_rows(ev, rows)                  # rows: [{date, code, open, high, low, close, volume, ...}]
"""
import argparse
import csv
import glob
import sys
from bisect import bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVENTS = ROOT / "data" / "adjust" / "events.csv"
PRICE_COLS = ("open", "high", "low", "close", "change")


def load_events(path=EVENTS):
    """{code: [(date, factor, row), ...]}，依日期排序。同一檔同一天有多筆（例如減資＋除權）就相乘。"""
    out = {}
    with open(path, encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            try:
                f = float(r["factor"])
            except (TypeError, ValueError):
                continue
            if f > 0:
                out.setdefault(r["code"], []).append((r["date"], f, r))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def cumulative(events_for_code):
    """[(date, cum)]：cum = 這個事件（含）之後所有因子的連乘；價格日 t 用第一個 date > t 的 cum。"""
    cum, out = 1.0, []
    for d, f, _ in reversed(events_for_code):
        cum *= f
        out.append((d, cum))
    out.reverse()
    return out


def factor_after(events, code, d):
    """日期 d（YYYY-MM-DD）的原始價格要乘的還原倍數。"""
    cum = cumulative(events.get(code, []))
    i = bisect_right([x[0] for x in cum], d)
    return cum[i][1] if i < len(cum) else 1.0


def adjust_rows(events, rows):
    """在每列加 adj_open/adj_high/adj_low/adj_close/adj_change/adj_volume/adj_factor（不改原本欄位）。"""
    cache = {}
    out = []
    for r in rows:
        code = r["code"]
        if code not in cache:
            cum = cumulative(events.get(code, []))
            cache[code] = ([x[0] for x in cum], [x[1] for x in cum])
        dates, cums = cache[code]
        i = bisect_right(dates, r["date"])
        f = cums[i] if i < len(cums) else 1.0
        a = dict(r, adj_factor=f"{f:.8f}".rstrip("0").rstrip("."))
        for k in PRICE_COLS:
            v = r.get(k)
            a["adj_" + k] = f"{float(v) * f:.4f}" if v not in (None, "") else ""
        v = r.get("volume")
        a["adj_volume"] = f"{float(v) / f:.0f}" if v not in (None, "") else ""
        out.append(a)
    return out


def read_prices(code, start=None, end=None, data_dir=ROOT / "data"):
    rows = []
    for path in sorted(glob.glob(str(data_dir / "[0-9]" * 4 / "*.csv"))):
        stem = Path(path).stem
        d = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        if (start and d < start) or (end and d > end):
            continue
        with open(path, encoding="utf-8") as fp:
            rows += [r for r in csv.DictReader(fp) if r["code"] == code]
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--events", action="store_true", help="只列事件")
    args = ap.parse_args()
    ev = load_events()
    w = csv.writer(sys.stdout)
    if args.events:
        cum = dict(cumulative(ev.get(args.code, [])))
        w.writerow(["date", "kind", "prev_close", "ref_price", "factor", "cum_factor", "cash", "note"])
        for d, _, r in ev.get(args.code, []):
            w.writerow([d, r["kind"], r["prev_close"], r["ref_price"], r["factor"], f"{cum[d]:.6f}", r["cash"], r["note"]])
        return
    rows = adjust_rows(ev, read_prices(args.code, args.start, args.end))
    cols = ["date", "market", "code", "name", "open", "high", "low", "close", "volume",
            "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume", "adj_factor"]
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])


if __name__ == "__main__":
    main()
