#!/usr/bin/env python3
"""內部人實際買賣期間的分點進出：用來推出內部人是透過哪個券商分點下單（內部人分點）。

做法（跟庫藏股公司派分點 fetch_treasury_broker.py 同一套）
  每月持股異動事後申報（data/insider/trades/）告訴我們某家公司的內部人上個月在集中市場實際買／賣了幾張；
  內部人下單一定經過某個分點，所以查這檔股票「那個月買超、賣超前 15 大分點」，再跟實際張數比對
  （比對在 scripts/insider_broker.py，網站建置時計算）。

  內部人要在市場賣股得先做事前申報（data/insider/transfer/），申報裡有轉讓期間；那個月有申報的話，
  查詢區間縮到申報期間跟該月重疊的部分，雜訊比較少。

每筆要查的區間（job）：
  m  月報：某家公司某月內部人集中市場淨買賣 ≥ MIN_LOTS 張、而且方向一面倒（淨額 ≥ 總買賣的 60%）
       in   該月（或申報期間重疊部分）
       pre  區間前 30 天，用來排除本來就常買賣這檔的分點；只查一次
  t  事前申報追蹤：一般交易／鉅額／盤後的申報（≥ MIN_LOTS 張），轉讓期間已開始、還沒結束超過 5 天的，
       in   最早的轉讓期間起日 ～ 最新交易日（每天重查），用來看已知內部人分點賣了多少
  接著對候選分點查「單一分點每日進出」（zco0），看是不是天天同方向（內部人分批出貨／進貨的樣子）。

資料來源：富邦證券網站「券商分點-進出明細」（MoneyDJ，公開頁面、免登入），單位：張
  https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a=<代號>&e=<起日>&f=<迄日>

輸出 data/insider/brokers.csv：
  kind(m|t), market, code, ref(月報 YYYY-MM；申報 期間起日), dir(B 買｜S 賣), lots(內部人淨張數，正數),
  win(in|pre), d1, d2, side(B 買超前15｜S 賣超前15), rank, bid, broker, buy, sell, net
  查過但沒資料時存一列 rank=0（避免重複查）。
data/insider/broker_days.csv：
  kind, code, ref, bid, d1, d2, days, buy_days, sell_days, buy_net, sell_net, buy, sell, net

用法：python fetch_insider_broker.py [--max-minutes 20] [--months 6]
"""
import argparse
import calendar
import csv
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C
import fetch_broker as FB
import fetch_broker_watch as FW
import fetch_treasury_broker as TB

ROOT = Path(__file__).resolve().parent
D = ROOT / "data" / "insider"
COLS = ["kind", "market", "code", "ref", "dir", "lots", "win", "d1", "d2", "side", "rank", "bid", "broker",
        "buy", "sell", "net"]
DAY_COLS = ["kind", "code", "ref", "bid", "d1", "d2", "days", "buy_days", "sell_days", "buy_net", "sell_net",
            "buy", "sell", "net"]
MIN_LOTS = 100      # 內部人淨買賣至少幾張才查
ONE_WAY = 0.6       # 淨額 ÷ 總買賣（買＋賣）下限
PRE_DAYS = 30
DAY_LO, DAY_HI = 0.3, 3.0   # 候選分點：同方向淨額在內部人張數的 0.3～3 倍
MAX_OPP = 0.35      # 而且反向張數 ≤ 同方向的 35%，才查每日
LIVE_TOP = 5        # 申報追蹤：同方向前幾名（外資券商除外）查每日
FOREIGN = ("美林", "摩根", "高盛", "花旗", "瑞銀", "麥格理", "法銀巴黎", "德意志", "野村", "大和", "瑞士信貸", "香港上海匯豐",
           "法國興業", "巴克萊", "星展", "新加坡商", "港商")
LIVE_TAIL = 5       # 轉讓期間結束後再追幾天（等最後幾天的分點資料）
MKT = ("一般交易", "鉅額", "盤後")
DELAY = 0.3


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(p, rows, cols):
    tmp = p.with_suffix(".tmp")
    key = (lambda r: (r["kind"], r["ref"], r["code"], r.get("win", ""), r.get("side", ""), int(r.get("rank") or 0),
                      r.get("bid", "")))
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=key))
    tmp.replace(p)


def _int(v):
    try:
        return int(float(v or 0))
    except ValueError:
        return 0


def roc(s):
    """1151015 → 2026-10-15"""
    s = (s or "").strip()
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:]}"
    return ""


def periods(transfer):
    """市場賣出的事前申報 → [{market, code, shares, d1, d2, date}]（d1、d2 = 轉讓期間）"""
    out = []
    for r in transfer:
        if not any(k in (r.get("method") or "") for k in MKT):
            continue
        a, _, b = (r.get("period") or "").partition("~")
        d1, d2 = roc(a), roc(b)
        if d1 and d2:
            out.append({"market": r["market"], "code": r["code"], "shares": _int(r["shares"]), "d1": d1, "d2": d2,
                        "date": r["date"]})
    return out


def month_jobs(trades, pers, last_day):
    """月報 → [job]；trades 是 data/insider/trades/*.csv 的列"""
    agg = {}
    for r in trades:
        if r.get("dup"):
            continue
        k = (r["month"], r["market"], r["code"])
        a = agg.setdefault(k, [0, 0])
        a[0] += _int(r["buy_mkt"])
        a[1] += _int(r["sell_mkt"])
    out = []
    for (m, mkt, code), (b, s) in agg.items():
        net = b - s
        if abs(net) < MIN_LOTS * 1000 or abs(net) < ONE_WAY * (b + s):
            continue
        y, mo = int(m[:4]), int(m[5:7])
        d1, d2 = f"{m}-01", f"{m}-{calendar.monthrange(y, mo)[1]:02d}"
        if net < 0:  # 賣：有市場賣出申報就縮到申報期間
            ps = [p for p in pers if p["code"] == code and p["d1"] <= d2 and p["d2"] >= d1]
            if ps:
                d1, d2 = max(d1, min(p["d1"] for p in ps)), min(d2, max(p["d2"] for p in ps))
        d2 = min(d2, last_day)
        if d1 > d2:
            continue
        out.append({"kind": "m", "market": mkt, "code": code, "ref": m, "dir": "B" if net > 0 else "S",
                    "lots": round(abs(net) / 1000), "d1": d1, "d2": d2})
    return out


def live_jobs(pers, last_day):
    """事前申報追蹤：轉讓期間已開始、結束不到 LIVE_TAIL 天 → 每家公司一個 job（期間取聯集）"""
    cut = (date.fromisoformat(last_day) - timedelta(days=LIVE_TAIL)).isoformat()
    by = {}
    for p in pers:
        if p["d1"] > last_day or p["d2"] < cut:
            continue
        by.setdefault((p["market"], p["code"]), []).append(p)
    out = []
    for (mkt, code), ps in by.items():
        sh = sum(p["shares"] for p in ps)
        if sh < MIN_LOTS * 1000:
            continue
        d1 = min(p["d1"] for p in ps)
        out.append({"kind": "t", "market": mkt, "code": code, "ref": d1, "dir": "S", "lots": round(sh / 1000),
                    "d1": d1, "d2": min(last_day, max(p["d2"] for p in ps))})
    return out


def jobs(mjobs, ljobs, have):
    """→ [(job, win, d1, d2)]；have = {(kind, code, ref, win): 已查的 d2}"""
    out = []
    for j in ljobs + sorted(mjobs, key=lambda j: j["ref"], reverse=True):
        k = (j["kind"], j["code"], j["ref"])
        if have.get(k + ("in",), "") < j["d2"]:
            out.append((j, "in", j["d1"], j["d2"]))
        if j["kind"] == "m" and (k + ("pre",)) not in have:
            s = date.fromisoformat(j["d1"])
            out.append((j, "pre", (s - timedelta(days=PRE_DAYS)).isoformat(), (s - timedelta(days=1)).isoformat()))
    return out


def fetch_range(code, d1, d2):
    ds = lambda d: f"{int(d[:4])}-{int(d[5:7])}-{int(d[8:10])}"  # noqa: E731
    raw = C.http(FB.BASE, {"a": code, "e": ds(d1), "f": ds(d2)}, raw=True, retries=3)
    rows, _ = FB.parse(raw.decode("cp950", errors="replace"), d1, code)
    return rows


def _opp_ok(r, sg):
    din, dout = (float(r["buy"]), float(r["sell"])) if sg > 0 else (float(r["sell"]), float(r["buy"]))
    return dout <= MAX_OPP * din


def is_foreign(name):
    return any(k in (name or "") for k in FOREIGN)


def day_jobs(jlist, rows, have):
    """要查每日進出的 (job, row)：淨額跟內部人張數同量級、買賣一面倒的分點；have = {(kind, code, ref, bid): 已查的 d2}"""
    by = {}
    for r in rows:
        if r["win"] == "in" and r["bid"]:
            by.setdefault((r["kind"], r["code"], r["ref"]), []).append(r)
    out = []
    for j in jlist:
        k = (j["kind"], j["code"], j["ref"])
        sg = 1 if j["dir"] == "B" else -1
        rs = [r for r in by.get(k, []) if sg * float(r["net"]) > 0]
        if j["kind"] == "m":
            cands = [r for r in rs if DAY_LO * j["lots"] <= sg * float(r["net"]) <= DAY_HI * j["lots"] and _opp_ok(r, sg)]
        else:
            cands = sorted((r for r in rs if not is_foreign(r["broker"])), key=lambda r: -sg * float(r["net"]))[:LIVE_TOP]
        out += [(j, r) for r in cands if have.get(k + (r["bid"],), "") < r["d2"]]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-minutes", type=float, default=20, help="最多跑幾分鐘，剩下的下次再查（預設 20）")
    ap.add_argument("--months", type=int, default=6, help="月報查最近幾個月（預設 6）")
    a = ap.parse_args(argv)
    last_day = FB.latest_trading_day()
    tfiles = sorted((D / "trades").glob("[0-9]" * 6 + ".csv"))[-a.months:]
    trades = [r for p in tfiles for r in _read(p)]
    pers = periods([r for p in sorted((D / "transfer").glob("*.csv")) for r in _read(p)])
    mj, lj = month_jobs(trades, pers, last_day), live_jobs(pers, last_day)

    path = D / "brokers.csv"
    rows = _read(path)
    have = {}
    for r in rows:
        k = (r["kind"], r["code"], r["ref"], r["win"])
        have[k] = max(have.get(k, ""), r["d2"])
    todo = jobs(mj, lj, have)
    print(f"月報 {len(mj)} 筆、申報追蹤 {len(lj)} 家，要查 {len(todo)} 段（最新交易日 {last_day}）")

    t0, n, failed = time.time(), 0, 0
    for j, win, d1, d2 in todo:
        if time.time() - t0 > a.max_minutes * 60:
            print(f"達到 {a.max_minutes} 分鐘上限，剩 {len(todo) - n - failed} 段下次再查")
            break
        try:
            got = fetch_range(j["code"], d1, d2)
        except C.AdapterError as e:
            failed += 1
            print(f"  {j['code']} {win} {d1}~{d2} 失敗：{e}", file=sys.stderr)
            continue
        k = (j["kind"], j["code"], j["ref"], win)
        rows = [r for r in rows if (r["kind"], r["code"], r["ref"], r["win"]) != k]
        base = {c: j[c] for c in ("kind", "market", "code", "ref", "dir", "lots")}
        base.update(win=win, d1=d1, d2=d2)
        if got:
            rows += [{**base, **{c: g[c] for c in ("side", "rank", "bid", "broker", "buy", "sell", "net")}} for g in got]
        else:
            rows.append({**base, "side": "", "rank": 0, "bid": "", "broker": "", "buy": "", "sell": "", "net": ""})
        n += 1
        if n % 100 == 0:
            _write(path, rows, COLS)
            print(f"  {n}/{len(todo)}（{time.time() - t0:.0f} 秒）", flush=True)
        time.sleep(DELAY)
    if n:
        _write(path, rows, COLS)
    print(f"本次查了 {n} 段，失敗 {failed} -> {path}（{datetime.now(C.TPE):%Y-%m-%d %H:%M}）")

    dpath = D / "broker_days.csv"
    days = _read(dpath)
    have_d = {(r["kind"], r["code"], r["ref"], r["bid"]): r["d2"] for r in days}
    bhid = {r["bid"]: r["broker_id"] for r in _read(ROOT / "data" / "broker" / "branches.csv")}
    dtodo = day_jobs(lj + mj, rows, have_d)
    print(f"候選分點每日進出：要查 {len(dtodo)} 個")
    m, dfail = 0, 0
    for j, r in dtodo:
        if time.time() - t0 > a.max_minutes * 60:
            print(f"達到 {a.max_minutes} 分鐘上限，剩 {len(dtodo) - m - dfail} 個下次再查")
            break
        try:
            got = TB.fetch_daily(j["code"], r["bid"], bhid.get(r["bid"], r["bid"]), r["d1"], r["d2"])
        except C.AdapterError as e:
            dfail += 1
            print(f"  {j['code']} {r['bid']} 每日進出失敗：{e}", file=sys.stderr)
            continue
        k = (j["kind"], j["code"], j["ref"], r["bid"])
        days = [x for x in days if (x["kind"], x["code"], x["ref"], x["bid"]) != k]
        days.append({"kind": j["kind"], "code": j["code"], "ref": j["ref"], "bid": r["bid"], "d1": r["d1"],
                     "d2": r["d2"], **TB.summarize(got)})
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
