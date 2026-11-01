#!/usr/bin/env python3
"""研究用：CB 詢圈／競拍前後，各券商分點在標的現股的區間買賣超（前 15 大買超＋前 15 大賣超）。

每個案件（data/cb/cases.csv，詢價圈購＋競價拍賣當對照組）以 T0 = 詢圈／競拍開始日 為準，查：
  base  T0 前 80～21 個交易日（平常有沒有在進出這檔）
  pre20 T0 前 20～1 個交易日（詢圈前布局）
  pre5  T0 前 5～1 個交易日
  in    T0 ～ 轉換價格基準日（沒有就用訂價日／詢圈結束日）
  post  基準日次一交易日起 20 個交易日（掛牌後有沒有出場）
  plc1/plc2  T0 前 60～41、100～81 個交易日（同長度 20 日的對照期間）
輸出 research/data/cb_brokers.csv：id, code, method, win, d1, d2, side, rank, bid, broker, buy, sell, net
用法：python research/cb_broker_fetch.py [--max-minutes 60]
"""
import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import etf_common as C  # noqa: E402
import fetch_broker as FB  # noqa: E402

OUT = ROOT / "research" / "data" / "cb_brokers.csv"
COLS = ["id", "code", "method", "win", "d1", "d2", "side", "rank", "bid", "broker", "buy", "sell", "net"]


def trading_days():
    ds = sorted(p.stem for p in (ROOT / "data").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8)
    return [f"{s[:4]}-{s[4:6]}-{s[6:]}" for s in ds]


def windows(c, td):
    t0 = c["bb_start"]
    if not t0:
        return []
    i = next((k for k, d in enumerate(td) if d >= t0), None)
    if i is None or i < 100:
        return []
    end = c["price_base_date"] or c["done_date"] or c["bb_end"]
    if not end or end < t0:
        end = c["done_date"] or c["bb_end"]
    j = next((k for k, d in enumerate(td) if d >= end), None)
    out = [("base", td[i - 80], td[i - 21]), ("pre20", td[i - 20], td[i - 1]), ("pre5", td[i - 5], td[i - 1]),
           ("plc1", td[i - 60], td[i - 41]), ("plc2", td[i - 100], td[i - 81])]
    if j is not None:
        out.append(("in", td[i], td[j]))
        if j + 20 < len(td):
            out.append(("post", td[j + 1], td[j + 20]))
    return out


def fetch(code, d1, d2):
    ds = lambda d: f"{int(d[:4])}-{int(d[5:7])}-{int(d[8:10])}"  # noqa: E731
    raw = C.http(FB.BASE, {"a": code, "e": ds(d1), "f": ds(d2)}, raw=True, retries=3)
    rows, _ = FB.parse(raw.decode("cp950", errors="replace"), d1, code)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=60)
    a = ap.parse_args()
    with (ROOT / "data" / "cb" / "cases.csv").open(encoding="utf-8") as fp:
        cases = [c for c in csv.DictReader(fp) if c["method"] in ("詢價圈購", "競價拍賣") and c["code"]]
    td = trading_days()
    rows = []
    have = set()
    if OUT.exists():
        with OUT.open(encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
        have = {(r["id"], r["win"]) for r in rows}
    jobs = [(c, w, d1, d2) for c in cases for w, d1, d2 in windows(c, td) if (c["id"], w) not in have]
    print(f"案件 {len(cases)}，要查 {len(jobs)} 段")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t0, n = time.time(), 0
    for c, w, d1, d2 in jobs:
        if time.time() - t0 > a.max_minutes * 60:
            print("時間到，下次接著查")
            break
        try:
            got = fetch(c["code"], d1, d2)
        except C.AdapterError as e:
            print(f"  {c['code']} {w} 失敗 {e}", file=sys.stderr)
            continue
        base = {"id": c["id"], "code": c["code"], "method": c["method"], "win": w, "d1": d1, "d2": d2}
        if got:
            rows += [{**base, **{k: g[k] for k in ("side", "rank", "bid", "broker", "buy", "sell", "net")}} for g in got]
        else:
            rows.append({**base, "side": "", "rank": 0})
        n += 1
        if n % 100 == 0:
            print(f"  {n}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
        time.sleep(0.2)
    with OUT.open("w", encoding="utf-8", newline="") as fp:
        wr = csv.DictWriter(fp, fieldnames=COLS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    print(f"查了 {n} 段 → {OUT}")


if __name__ == "__main__":
    main()
