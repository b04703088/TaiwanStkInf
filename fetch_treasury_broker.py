#!/usr/bin/env python3
"""庫藏股買回期間的分點買超：用來比對公司實際是透過哪個券商分點買回（公司派分點）。

做法
  公司買回自家股份一定要透過某個券商分點下單，而且只買不賣。所以把整段買回期間當成一個區間，
  查這檔股票「區間內買超前 15 大分點」，再跟公司公告的實際買回張數比對（比對在
  scripts/treasury_broker.py，網站建置時計算），幾乎都能找到一兩個分點，買超張數加起來
  跟實際買回張數只差幾 %。

資料來源：富邦證券網站「券商分點-進出明細」（MoneyDJ，公開頁面、免登入），可以查任意日期區間
  https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a=<代號>&e=<起日>&f=<迄日>   單位：張

每個買回計畫查兩段：
  in   買回期間（期間起 ～ 期間迄；還在期間內的查到最新交易日，每天重查）
  pre  買回前 60 天（期間起前 60 天 ～ 前一天），用來排除本來就常買這檔的分點；只查一次
已結束而且實際買回 0 股的計畫不查。

輸出 data/treasury/brokers.csv：
  market, code, board_date, win(in|pre), d1, d2, rank, bid, broker, buy, sell, net
  只存買超前 15 名；查過但沒資料時存一列 rank=0（避免重複查）。

用法：python fetch_treasury_broker.py [--max-minutes 20]
"""
import argparse
import csv
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C
import fetch_broker as FB

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "treasury"
COLS = ["market", "code", "board_date", "win", "d1", "d2", "rank", "bid", "broker", "buy", "sell", "net"]
PRE_DAYS = 60
DELAY = 0.3


def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(path, rows):
    tmp = path.with_suffix(".tmp")
    rows = sorted(rows, key=lambda r: (r["board_date"], r["code"], r["win"], int(r["rank"])))
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def fetch_range(code, d1, d2):
    """區間買超前 15 名 → [row]（d1、d2 是 YYYY-MM-DD）"""
    ds = lambda d: f"{int(d[:4])}-{int(d[5:7])}-{int(d[8:10])}"  # noqa: E731
    raw = C.http(FB.BASE, {"a": code, "e": ds(d1), "f": ds(d2)}, raw=True, retries=3)
    rows, _ = FB.parse(raw.decode("cp950", errors="replace"), d1, code)
    return [r for r in rows if r["side"] == "B"]


def jobs(programs, have, last_day):
    """要查的 (program, win, d1, d2)；have = {(market, code, board_date, win): 已查的 d2}"""
    out = []
    for p in programs:
        if not p["start"] or p["start"] > last_day:
            continue
        done = bool(p["bought_shares"])
        if done and int(p["bought_shares"]) == 0:
            continue
        k = (p["market"], p["code"], p["board_date"])
        d2 = min(p["end"] or last_day, last_day)
        if have.get(k + ("in",), "") < d2:
            out.append((p, "in", p["start"], d2))
        if (k + ("pre",)) not in have:
            s = date.fromisoformat(p["start"])
            out.append((p, "pre", (s - timedelta(days=PRE_DAYS)).isoformat(), (s - timedelta(days=1)).isoformat()))
    # 執行中的先查（每天要更新），其餘依決議日新到舊
    out.sort(key=lambda j: j[0]["board_date"], reverse=True)
    out.sort(key=lambda j: bool(j[0]["bought_shares"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-minutes", type=float, default=20, help="最多跑幾分鐘，剩下的下次再查（預設 20）")
    a = ap.parse_args(argv)
    programs = _read(OUT / "programs.csv")
    path = OUT / "brokers.csv"
    rows = _read(path)
    have = {}
    for r in rows:
        k = (r["market"], r["code"], r["board_date"], r["win"])
        have[k] = max(have.get(k, ""), r["d2"])
    last_day = FB.latest_trading_day()
    todo = jobs(programs, have, last_day)
    print(f"買回計畫 {len(programs)} 筆，要查 {len(todo)} 段（最新交易日 {last_day}）")

    t0, n, failed = time.time(), 0, 0
    for p, win, d1, d2 in todo:
        if time.time() - t0 > a.max_minutes * 60:
            print(f"達到 {a.max_minutes} 分鐘上限，剩 {len(todo) - n - failed} 段下次再查")
            break
        try:
            got = fetch_range(p["code"], d1, d2)
        except C.AdapterError as e:
            failed += 1
            print(f"  {p['code']} {win} {d1}~{d2} 失敗：{e}", file=sys.stderr)
            continue
        k = (p["market"], p["code"], p["board_date"], win)
        rows = [r for r in rows if (r["market"], r["code"], r["board_date"], r["win"]) != k]
        base = {"market": p["market"], "code": p["code"], "board_date": p["board_date"], "win": win, "d1": d1, "d2": d2}
        if got:
            rows += [{**base, **{c: g[c] for c in ("rank", "bid", "broker", "buy", "sell", "net")}} for g in got]
        else:
            rows.append({**base, "rank": 0, "bid": "", "broker": "", "buy": "", "sell": "", "net": ""})
        n += 1
        if n % 100 == 0:
            _write(path, rows)
            print(f"  {n}/{len(todo)}（{time.time() - t0:.0f} 秒）", flush=True)
        time.sleep(DELAY)
    if n:
        _write(path, rows)
    print(f"本次查了 {n} 段，失敗 {failed} -> {path}（{datetime.now(C.TPE):%Y-%m-%d %H:%M}）")
    return 1 if failed > max(5, 0.1 * (n + failed)) else 0


if __name__ == "__main__":
    sys.exit(main())
