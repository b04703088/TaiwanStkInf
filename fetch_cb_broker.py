#!/usr/bin/env python3
"""進行中可轉債（CB）案件：標的現股在各流程階段的分點買超／賣超前 15 名。

用來看「CB 常客分點」（config/cb_regulars.csv，研究見 research/）有沒有在這次進場。

階段（依 data/cb/cases.csv 的實際日期，以交易日切）：
  s0  董事會決議前 20 個交易日
  s1  董事會決議 → 送件前一日
  s2  送件 → 生效前一日
  s3  生效 → 詢圈／競拍開始前一日
  s4  詢圈／競拍開始 → 訂價日
還沒走完的階段查到最新交易日，之後每天重查；走完的階段查過一次就不再查。

資料來源：富邦證券「券商分點-進出明細」區間查詢（MoneyDJ，公開頁面），單位：張。
輸出 data/cb/brokers.csv：id, code, win, d1, d2, side, rank, bid, broker, buy, sell, net
  查過但沒資料時存一列 rank=0。

用法：python fetch_cb_broker.py [--max-minutes 15]
"""
import argparse
import bisect
import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import etf_common as C
import fetch_broker as FB

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "cb" / "brokers.csv"
COLS = ["id", "code", "win", "d1", "d2", "side", "rank", "bid", "broker", "buy", "sell", "net"]
LOOKBACK_DAYS = 240     # 董事會決議在這麼多天內的案件才追
AFTER_PRICE_DAYS = 30   # 訂價後再保留幾天（網站顯示用；之後不再查）
DELAY = 0.3


def trading_days():
    ds = sorted(p.stem for p in (ROOT / "data").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8)
    return [f"{s[:4]}-{s[4:6]}-{s[6:]}" for s in ds]


def price_day(c):
    return c["done_date"] or c["bb_end"]


def active_cases(cases, last):
    """還沒撤回、近期決議、還沒訂價（或剛訂價）的案件"""
    lo = (date.fromisoformat(last) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    hi = (date.fromisoformat(last) - timedelta(days=AFTER_PRICE_DAYS)).isoformat()
    out = []
    for c in cases:
        if c["method"] not in ("詢價圈購", "競價拍賣", "") or not c["code"]:
            continue
        if c["wd_date"] or c["sfb_status"] in ("自行撤回", "廢止/撤銷", "退件"):
            continue
        start = c["board_date"] or c["filed_date"] or c["bb_start"]
        if not start or start < lo:
            continue
        pd = price_day(c)
        if pd and pd < hi:
            continue
        out.append(c)
    return out


def stages(c, td):
    """[(win, d1, d2, 已走完)]；d2 最多到最新交易日"""
    last = len(td) - 1

    def k(d):
        return bisect.bisect_left(td, d) if d else None

    kb, kf, ke, ks, kp = k(c["board_date"]), k(c["filed_date"]), k(c["eff_date"]), k(c["bb_start"]), k(price_day(c))
    out = []
    if kb is not None and 20 <= kb <= last + 1:
        out.append(("s0", kb - 20, kb - 1, True))
    for win, a, b in (("s1", kb, kf), ("s2", kf, ke), ("s3", ke, ks)):
        if a is None or a > last:
            continue
        if b is not None and b <= a:
            continue
        end = b - 1 if b is not None and b <= last + 1 else last
        out.append((win, a, min(end, last), b is not None and b <= last))
    if ks is not None and ks <= last:
        done = kp is not None and kp <= last
        out.append(("s4", ks, kp if done else last, done))
    return [(w, td[a], td[b], fin) for w, a, b, fin in out if a <= b]


def fetch(code, d1, d2):
    ds = lambda d: f"{int(d[:4])}-{int(d[5:7])}-{int(d[8:10])}"  # noqa: E731
    raw = C.http(FB.BASE, {"a": code, "e": ds(d1), "f": ds(d2)}, raw=True, retries=3)
    rows, _ = FB.parse(raw.decode("cp950", errors="replace"), d1, code)
    return rows


def read_rows():
    if not OUT.exists():
        return []
    with OUT.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def write_rows(rows):
    rows.sort(key=lambda r: (r["id"], r["win"], r["side"], int(r["rank"] or 0)))
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(OUT)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-minutes", type=float, default=15)
    a = ap.parse_args(argv)
    td = trading_days()
    with (ROOT / "data" / "cb" / "cases.csv").open(encoding="utf-8") as fp:
        cases = list(csv.DictReader(fp))
    act = active_cases(cases, td[-1])
    keep = {c["id"] for c in act}
    rows = [r for r in read_rows() if r["id"] in keep]   # 不再追的案件就丟掉
    have = {}
    for r in rows:
        have[(r["id"], r["win"])] = r["d2"]
    jobs = [(c, w, d1, d2) for c in act for w, d1, d2, _ in stages(c, td) if have.get((c["id"], w)) != d2]
    print(f"追蹤 {len(act)} 件 CB，要查 {len(jobs)} 段（最新交易日 {td[-1]}）")
    t0, n, failed = time.time(), 0, 0
    cache = {}   # 同一檔同時辦詢圈＋競拍時日期相同，只查一次
    for c, w, d1, d2 in jobs:
        if time.time() - t0 > a.max_minutes * 60:
            print("時間到，剩下的下次再查")
            break
        key = (c["code"], d1, d2)
        if key not in cache:
            try:
                cache[key] = fetch(c["code"], d1, d2)
            except C.AdapterError as e:
                failed += 1
                print(f"  {c['code']} {w} {d1}~{d2} 失敗：{e}", file=sys.stderr)
                continue
            time.sleep(DELAY)
        got = cache[key]
        rows = [r for r in rows if (r["id"], r["win"]) != (c["id"], w)]
        base = {"id": c["id"], "code": c["code"], "win": w, "d1": d1, "d2": d2}
        if got:
            rows += [{**base, **{k: g[k] for k in ("side", "rank", "bid", "broker", "buy", "sell", "net")}} for g in got]
        else:
            rows.append({**base, "side": "", "rank": 0})
        n += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_rows(rows)
    print(f"查了 {n} 段，失敗 {failed} → {OUT}")
    return 1 if failed and failed > max(3, n // 10) else 0


if __name__ == "__main__":
    sys.exit(main())
