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

接著對買回期間的候選分點查「單一分點每日進出」（zco0.djhtm），統計區間內每天是淨買還是淨賣：
  公司買回幾乎每天都是淨買超，偶爾有其他客戶賣出；一般客戶則買賣日交錯。
  候選：已結束計畫中買超 ≥ 實際買回張數 10% 的分點；執行中計畫買超前 5 名。

輸出 data/treasury/brokers.csv：
  market, code, board_date, win(in|pre), d1, d2, rank, bid, broker, buy, sell, net
  只存買超前 15 名；查過但沒資料時存一列 rank=0（避免重複查）。
data/treasury/broker_days.csv：
  market, code, board_date, bid, d1, d2, days(有進出的天數), buy_days(淨買超天數), sell_days(淨賣超天數), buy, sell, net

用法：python fetch_treasury_broker.py [--max-minutes 20]
"""
import argparse
import csv
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C
import fetch_broker as FB
import fetch_broker_watch as FW

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "treasury"
COLS = ["market", "code", "board_date", "win", "d1", "d2", "rank", "bid", "broker", "buy", "sell", "net"]
DAY_COLS = ["market", "code", "board_date", "bid", "d1", "d2", "days", "buy_days", "sell_days", "buy", "sell", "net"]
DAILY = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco0/zco0.djhtm"
PRE_DAYS = 60
MIN_SHARE = 0.10   # 已結束計畫：買超至少佔實際買回張數的比例才查每日
LIVE_TOP = 5       # 執行中計畫：查買超前幾名
DELAY = 0.3


def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(path, rows, cols=COLS):
    tmp = path.with_suffix(".tmp")
    if cols is COLS:
        rows = sorted(rows, key=lambda r: (r["board_date"], r["code"], r["win"], int(r["rank"])))
    else:
        rows = sorted(rows, key=lambda r: (r["board_date"], r["code"], r["bid"]))
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def fetch_range(code, d1, d2):
    """區間買超前 15 名 → [row]（d1、d2 是 YYYY-MM-DD）"""
    ds = lambda d: f"{int(d[:4])}-{int(d[5:7])}-{int(d[8:10])}"  # noqa: E731
    raw = C.http(FB.BASE, {"a": code, "e": ds(d1), "f": ds(d2)}, raw=True, retries=3)
    rows, _ = FB.parse(raw.decode("cp950", errors="replace"), d1, code)
    return [r for r in rows if r["side"] == "B"]


_DAY_ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>\s*(\d{4}/\d{2}/\d{2})\s*</td>(.*?)</tr>", re.S | re.I)


def parse_daily(page):
    """單一分點每日進出 → [(日期, 買, 賣)]（張）"""
    out = []
    for d, rest in _DAY_ROW.findall(page):
        nums = [FB._num(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", rest, re.S | re.I)]
        if len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
            out.append((d.replace("/", "-"), int(nums[0]), int(nums[1])))
    return out


def summarize(daily):
    """每日 (日期, 買, 賣) → 有進出天數、淨買天數、淨賣天數、買、賣、淨"""
    act = [(b, s) for _, b, s in daily if b or s]
    return {"days": len(act), "buy_days": sum(1 for b, s in act if b > s), "sell_days": sum(1 for b, s in act if b < s),
            "buy": sum(b for b, _ in act), "sell": sum(s for _, s in act), "net": sum(b - s for b, s in act)}


def fetch_daily(code, bid, bhid, d1, d2):
    ds = lambda d: f"{int(d[:4])}-{int(d[5:7])}-{int(d[8:10])}"  # noqa: E731
    raw = C.http(DAILY, {"A": code, "BHID": bhid, "b": FW.enc(bid), "C": "1", "D": ds(d1), "E": ds(d2), "ver": "V3"},
                 raw=True, retries=3)
    return parse_daily(raw.decode("cp950", errors="replace"))


def day_jobs(programs, rows, have):
    """要查每日進出的 (program, row)；have = {(market, code, board_date, bid): 已查的 d2}"""
    pk = {(p["market"], p["code"], p["board_date"]): p for p in programs}
    by = {}
    for r in rows:
        if r["win"] == "in" and r["bid"]:
            by.setdefault((r["market"], r["code"], r["board_date"]), []).append(r)
    out = []
    for k, rs in by.items():
        p = pk.get(k)
        if not p:
            continue
        if p["bought_shares"]:
            lots = int(p["bought_shares"]) / 1000
            cands = [r for r in rs if float(r["net"]) > 0 and float(r["net"]) >= MIN_SHARE * lots]
        else:
            cands = sorted((r for r in rs if float(r["net"]) > 0), key=lambda r: int(r["rank"]))[:LIVE_TOP]
        out += [(p, r) for r in cands if have.get(k + (r["bid"],), "") < r["d2"]]
    out.sort(key=lambda j: j[0]["board_date"], reverse=True)
    out.sort(key=lambda j: bool(j[0]["bought_shares"]))
    return out


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

    # 候選分點的每日進出
    dpath = OUT / "broker_days.csv"
    days = _read(dpath)
    have_d = {(r["market"], r["code"], r["board_date"], r["bid"]): r["d2"] for r in days}
    bhid = {r["bid"]: r["broker_id"] for r in _read(ROOT / "data" / "broker" / "branches.csv")}
    dtodo = day_jobs(programs, rows, have_d)
    print(f"候選分點每日進出：要查 {len(dtodo)} 個")
    m, dfail = 0, 0
    for p, r in dtodo:
        if time.time() - t0 > a.max_minutes * 60:
            print(f"達到 {a.max_minutes} 分鐘上限，剩 {len(dtodo) - m - dfail} 個下次再查")
            break
        try:
            got = fetch_daily(p["code"], r["bid"], bhid.get(r["bid"], r["bid"]), r["d1"], r["d2"])
        except C.AdapterError as e:
            dfail += 1
            print(f"  {p['code']} {r['bid']} 每日進出失敗：{e}", file=sys.stderr)
            continue
        k = (p["market"], p["code"], p["board_date"], r["bid"])
        days = [x for x in days if (x["market"], x["code"], x["board_date"], x["bid"]) != k]
        days.append({"market": p["market"], "code": p["code"], "board_date": p["board_date"], "bid": r["bid"],
                     "d1": r["d1"], "d2": r["d2"], **summarize(got)})
        m += 1
        if m % 100 == 0:
            _write(dpath, days, DAY_COLS)
            print(f"  {m}/{len(dtodo)}（{time.time() - t0:.0f} 秒）", flush=True)
        time.sleep(DELAY)
    if m:
        _write(dpath, days, DAY_COLS)
    print(f"每日進出查了 {m} 個，失敗 {dfail} -> {dpath}")
    failed += dfail
    return 1 if failed > max(5, 0.1 * (n + m + failed)) else 0


if __name__ == "__main__":
    sys.exit(main())
