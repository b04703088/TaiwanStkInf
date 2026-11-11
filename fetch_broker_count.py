#!/usr/bin/env python3
"""每檔股票的分點買賣家數：掃全部約 900 個分點當天的買賣超股票，彙總成「每檔幾家買超、幾家賣超」。

資料來源：富邦證券網站「分點明細查詢」（MoneyDJ，公開頁面、免登入），張數版 c=E
  https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm?a=<券商>&b=<分點>&c=E&e=<日期>&f=<日期>

限制：每個分點每邊（買超／賣超）只列前 50 檔。交易很多檔的大分點（網路單、總公司）
在某檔只買賣一點點時不會出現，所以家數是「近似全分點」，會略少於證交所的真實家數。
每檔另外記 capped_b／capped_s：當天買超（賣超）表滿 50 檔的分點裡，有幾家列了這檔
（它們是「有列到的大分點」，沒列到的就是漏掉的部分）；全市場滿 50 檔的分點數寫在 _meta.csv。

輸出 data/broker/count/<YYYY>/<YYYYMMDD>.csv：
  date, code, buyers, sellers, diff(= buyers − sellers), buy_sh, sell_sh(張，買超／賣超分點的淨張數合計)
  data/broker/count/<YYYY>/<YYYYMMDD>_meta.csv：branches, done, failed, capped_b, capped_s

中途中斷時，已抓的分點存在 data/broker/count/<YYYY>/<YYYYMMDD>_raw.csv.gz 暫存（全部抓完就刪掉）。

用法：
  python fetch_broker_count.py                 最新一個有收盤行情的交易日
  python fetch_broker_count.py --date 2026-11-10
  python fetch_broker_count.py --days 20       最近 20 個交易日裡還沒抓完的都補
"""
import argparse
import csv
import gzip
import sys
import time
from pathlib import Path

import etf_common as C
from fetch_broker_watch import fetch, load_branches, trading_days

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "broker" / "count"
COLS = ["date", "code", "buyers", "sellers", "diff", "buy_sh", "sell_sh"]
META = ["date", "branches", "done", "failed", "capped_b", "capped_s"]
RAW = ["bid", "code", "net", "capped"]
DELAY = 0.15
CAP = 50
PROBE = ("9800", "9800")  # 元大總公司：判斷當天資料是否已經公布
KEEP_RAW = False


def paths(date):
    d = OUT / date[:4]
    s = date.replace("-", "")
    return d / f"{s}.csv", d / f"{s}_meta.csv", d / f"{s}_raw.csv.gz"


def read_raw(p):
    if not p.exists():
        return [], set()
    with gzip.open(p, "rt", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    return rows, {r["bid"] for r in rows}


def write_raw(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=RAW)
        w.writeheader()
        w.writerows(rows)


def branch_rows(bid, table):
    """table = {code: (name, buy, sell)}（買超、賣超兩張表合併）→ 原始列；capped 記哪一邊滿 50 檔。"""
    nb = sum(1 for _, b, s in table.values() if b > s)
    ns = sum(1 for _, b, s in table.values() if b < s)
    cap = ("B" if nb >= CAP else "") + ("S" if ns >= CAP else "")
    rows = [{"bid": bid, "code": code, "net": int(round(b - s)), "capped": cap}
            for code, (_, b, s) in table.items() if b != s]
    # 沒有任何買賣超的分點也記一列（code 空），代表「抓過了」
    return rows or [{"bid": bid, "code": "", "net": 0, "capped": ""}]


def aggregate(date, raw):
    agg = {}
    for r in raw:
        if not r["code"]:
            continue
        a = agg.setdefault(r["code"], {"date": date, "code": r["code"], "buyers": 0, "sellers": 0,
                                       "buy_sh": 0, "sell_sh": 0})
        n = int(r["net"])
        if n > 0:
            a["buyers"] += 1
            a["buy_sh"] += n
        elif n < 0:
            a["sellers"] += 1
            a["sell_sh"] += -n
    for a in agg.values():
        a["diff"] = a["buyers"] - a["sellers"]
    return sorted(agg.values(), key=lambda a: a["code"])


def run_day(date, branches, deadline):
    out, meta, rawp = paths(date)
    if out.exists():
        return "done", 0, 0
    raw, have = read_raw(rawp)
    if not have:  # 先用大分點確認當天資料已經公布
        try:
            d, _ = fetch(PROBE[0], PROBE[1], "E", date)
        except C.AdapterError:
            d = None
        if d != date:
            return "notyet", 0, 0
    todo = [b for b in branches if b[2] not in have]
    failed, n = [], 0
    for hq, _, bid, name in todo:
        if time.time() > deadline:
            break
        try:
            d, table = fetch(hq, bid, "E", date)
        except C.AdapterError as e:
            failed.append(bid)
            print(f"  {date} {name} 失敗：{e}", file=sys.stderr)
            continue
        finally:
            time.sleep(DELAY)
        if d != date:
            # 個別分點當天沒交易時頁面日期會是較早的日期：當成沒有買賣超
            table = {}
        raw += branch_rows(bid, table)
        have.add(bid)
        n += 1
        if n % 100 == 0:
            write_raw(rawp, raw)
            print(f"  {date}: {len(have)}/{len(branches)}", flush=True)
    write_raw(rawp, raw)
    if len(have) + len(failed) < len(branches) or len(failed) > len(branches) * 0.03:
        return "partial", n, len(failed)
    rows = aggregate(date, raw)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    caps = {}
    for r in raw:
        caps.setdefault(r["bid"], r["capped"])
    with meta.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=META)
        w.writeheader()
        w.writerow({"date": date, "branches": len(branches), "done": len(have), "failed": len(failed),
                    "capped_b": sum("B" in c for c in caps.values()),
                    "capped_s": sum("S" in c for c in caps.values())})
    if not KEEP_RAW:
        rawp.unlink()
    return "done", n, len(failed)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="交易日 YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=1, help="最近幾個交易日裡還沒抓完的都補（預設 1）")
    ap.add_argument("--max-minutes", type=float, default=60)
    ap.add_argument("--keep-raw", action="store_true", help="完成後保留分點原始檔（驗證用）")
    a = ap.parse_args(argv)
    global KEEP_RAW
    KEEP_RAW = a.keep_raw
    deadline = time.time() + a.max_minutes * 60
    branches = load_branches(refresh=True)
    dates = [a.date] if a.date else list(reversed(trading_days(a.days)))
    bad = 0
    for date in dates:
        if time.time() > deadline:
            print("時間到，下次再補")
            break
        st, n, f = run_day(date, branches, deadline)
        print(f"{date}: {st}（本次抓 {n} 個分點，失敗 {f}）", flush=True)
        bad += f
    return 1 if bad > len(branches) * 0.03 else 0


if __name__ == "__main__":
    sys.exit(main())
