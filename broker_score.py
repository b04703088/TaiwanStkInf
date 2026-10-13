#!/usr/bin/env python3
"""分點績效評分與分類：哪些分點買了之後股票會漲（波段高手）、哪些是隔日沖、哪些是反指標。

只讀已經抓好的資料，不連網：
  data/broker/<YYYY>/<YYYYMMDD>.csv          每檔股票前 15 大買超／賣超分點（fetch_broker.py）
  data/broker/<YYYY>/<YYYYMMDD>_total.csv    哪些股票當天有查到分點
  data/broker/watch/<YYYY>/<YYYYMMDD>.csv    重點分點每天買賣的股票（fetch_broker_watch.py，歷史較長）
  data/<YYYY>/<YYYYMMDD>.csv                 收盤行情

做法
  1. 事件：某分點某天對某檔股票的買超（或賣超）佔當天成交量 ≥ --min-pct（預設 1%）
     且金額 ≥ --min-amt（預設 500 萬元）。只看一般股票（4 位數代號），ETF、權證不算。
  2. 前瞻超額報酬：分點資料收盤後才公布，所以假設「隔天開盤買進」，持有到第 h 個交易日收盤，
     減去同期間全市場（成交金額 ≥ 3000 萬的股票）等權平均報酬。日報酬用交易所的漲跌價差，已含除權息。
     同一分點連續幾天買同一檔只算第一天（h 天內不重複計），避免同一段漲幅被算很多次。
  3. 分數 z：買超後的超額報酬 − 賣超後的超額報酬，除以全體事件的標準差 × √次數。
     |z| ≥ 2 大約是「不太像運氣」的程度；次數少的分點 z 會自然偏小，不會因為一兩次猜中就上榜。
  4. 隔日沖比例：買超隔天，同一分點把這檔賣掉了幾成（看得到隔天分點資料才算）。
  5. 分類（依序判斷）：
       隔日沖    隔日賣出比例 ≥ 50%，或 ≥ 35% 且買進當天平均漲 3% 以上（追強勢股、隔天倒貨），至少 5 次
       樣本不足  持有 --main 天的事件 < --min-n 次，或分布在 < --min-days 個不同交易日
                 （同一天的事件會一起受大盤、類股影響，天數太少時 z 會高估，所以另外要求天數）
       波段高手  z ≥ 2；反指標 z ≤ −2；其餘 一般
     注意：幾百個分點裡，純靠運氣也會有約 4.5% 的 |z| ≥ 2，執行時會印出「運氣預期數」對照。

輸出
  data/broker/score/branches.csv   每個分點的分數與分類
  data/broker/score/signals.csv    最新一天：高手／反指標／隔日沖各買了哪些股票

所有分數只用「到評分日為止已經實現」的報酬（--as-of 可指定評分日），不偷看未來。

用法：
  python broker_score.py                     用全部資料評分
  python broker_score.py --horizons 1 5 20 --main 5
  python broker_score.py --as-of 2026-10-08  假裝今天是 10/8（回測用）
"""
import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "broker" / "score"

STOCK = re.compile(r"[1-9]\d{3}")   # 一般股票；ETF（00 開頭）、權證、特別股不算
BENCH_MIN_VALUE = 30_000_000        # 大盤基準只用成交金額 ≥ 3000 萬的股票

CLASS_DT, CLASS_SMART, CLASS_CONTRA, CLASS_NORMAL, CLASS_FEW = "隔日沖", "波段高手", "反指標", "一般", "樣本不足"
CLASS_ORDER = [CLASS_SMART, CLASS_CONTRA, CLASS_DT, CLASS_NORMAL, CLASS_FEW]


def _f(s):
    try:
        return float(str(s).replace(",", "").replace("+", "")) if s not in (None, "") else None
    except ValueError:
        return None


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _date(stem):
    return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"


# ---------------- 行情 ----------------
def load_prices(data_dir, start=None, end=None):
    """回傳 (days, px, names)。px[code][date] = (open, close, ret, value, volume)；ret 是含除權息的日報酬。"""
    files = sorted((f for f in Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(f.stem) == 8),
                   key=lambda p: p.name)
    days, px, names = [], defaultdict(dict), {}
    for f in files:
        d = _date(f.stem)
        if (start and d < start) or (end and d > end):
            continue
        days.append(d)
        for r in _read(f):
            code = r["code"]
            if not STOCK.fullmatch(code):
                continue
            o, c, chg, vol = _f(r["open"]), _f(r["close"]), _f(r["change"]), _f(r["volume"])
            if not o or not c or not vol or chg is None:
                continue
            prev = c - chg
            px[code][d] = (o, c, chg / prev if prev > 0 else 0.0, _f(r["value"]) or 0.0, vol)
            names[code] = r["name"]
    return days, px, names


def bench(days, px, min_value=BENCH_MIN_VALUE):
    """每天全市場等權平均：(開盤→收盤報酬, 日報酬)。"""
    acc = {d: [0.0, 0.0, 0] for d in days}
    for series in px.values():
        for d, (o, c, ret, val, _) in series.items():
            if val >= min_value and d in acc:
                a = acc[d]
                a[0] += c / o - 1
                a[1] += ret
                a[2] += 1
    return {d: ((a[0] / a[2], a[1] / a[2]) if a[2] else (0.0, 0.0)) for d, a in acc.items()}


def forward_excess(days, px, bm, code, t, h):
    """t 收盤後得知訊號 → t+1 開盤買進 → t+h 收盤賣出，扣掉大盤。資料不夠（還沒到期、停牌）回傳 None。"""
    if t + h >= len(days):
        return None
    s = px.get(code, {})
    d1 = days[t + 1]
    if d1 not in s:
        return None
    o, c = s[d1][0], s[d1][1]
    r, b = c / o, 1 + bm[d1][0]
    for j in range(t + 2, t + h + 1):
        dj = days[j]
        if dj not in s:
            return None
        r *= 1 + s[dj][2]
        b *= 1 + bm[dj][1]
    return r - b


# ---------------- 分點 ----------------
def load_broker(data_dir, start=None, end=None):
    """回傳 (net, names, covered)。
    net[(date, bid, code)] = 買超張數（賣超為負）
    covered：看得到某分點在某天對某檔有沒有買賣的範圍，{("s", date, code)} 前 15 大有查到、{("w", date, bid)} 重點分點有抓到
    """
    root = Path(data_dir) / "broker"
    net, names, covered = {}, {}, set()

    def in_range(d):
        return not ((start and d < start) or (end and d > end))

    for f in sorted(root.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name):
        if len(f.stem) == 8 and in_range(_date(f.stem)):
            for r in _read(f):
                net[(r["date"], r["bid"], r["code"])] = int(_f(r["net"]))
                names[r["bid"]] = r["broker"]
        elif f.stem.endswith("_total") and in_range(_date(f.stem[:8])):
            for r in _read(f):
                if r.get("buy_total") not in (None, ""):
                    covered.add(("s", r["date"], r["code"]))
    for f in sorted((root / "watch").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name):
        if not in_range(_date(f.stem)):
            continue
        for r in _read(f):
            covered.add(("w", r["date"], r["bid"]))
            names.setdefault(r["bid"], r["branch"])
            n = _f(r.get("net_sh"))
            if n is not None:
                net.setdefault((r["date"], r["bid"], r["code"]), int(n))   # 前 15 大有的以前 15 大為準
    return net, names, covered


def make_events(net, days, px, min_pct=1.0, min_amt=5_000_000):
    """夠大的買超／賣超 → [(day_idx, bid, code, net, pct)]；pct = 佔當天成交量 %（賣超為負）。"""
    idx = {d: i for i, d in enumerate(days)}
    ev = []
    for (d, bid, code), n in net.items():
        if d not in idx or not STOCK.fullmatch(code) or n == 0:
            continue
        p = px.get(code, {}).get(d)
        if not p:
            continue
        pct = n * 1000 / p[4] * 100
        if abs(pct) >= min_pct and abs(n) * 1000 * p[1] >= min_amt:
            ev.append((idx[d], bid, code, n, pct))
    ev.sort()
    return ev


def flip_ratio(e, days, net, covered):
    """買超隔天被同一分點賣掉的比例（0–1）；看不到隔天資料回傳 None。"""
    t, bid, code, n, _ = e
    if n <= 0 or t + 1 >= len(days):
        return None
    d1 = days[t + 1]
    nxt = net.get((d1, bid, code))
    if nxt is None:
        if ("s", d1, code) in covered or ("w", d1, bid) in covered:
            nxt = 0   # 看得到隔天，只是沒進前 15 大 → 當作沒大量賣
        else:
            return None
    return min(max(-nxt / n, 0.0), 1.0)


def dedup(events, h):
    """同一分點、同一檔、同一方向，h 天內只留第一次。"""
    last, out = {}, []
    for e in events:
        k = (e[1], e[2], e[3] > 0)
        if k in last and e[0] < last[k] + h:
            continue
        last[k] = e[0]
        out.append(e)
    return out


# ---------------- 評分 ----------------
def score(data_dir=DATA, horizons=(1, 5, 20), main=5, as_of=None, min_pct=1.0, min_amt=5_000_000,
          min_n=10, min_days=10, z_cut=2.0, flip_cut=0.5, flip_soft=0.35, hot_day=0.03, flip_min_n=5,
          history_days=None):
    """回傳 dict：days, as_of, rows（每個分點一筆）, cls{bid: 分類}, events, px, names, net。"""
    net, names, covered = load_broker(data_dir, end=as_of)
    first_broker = min((k[0] for k in net), default=None)
    if not first_broker:
        return {"days": [], "rows": [], "cls": {}, "as_of": as_of}
    pstart = (date.fromisoformat(first_broker) - timedelta(days=14)).isoformat()
    days, px, stock_names = load_prices(data_dir, start=pstart, end=as_of)
    # 只保留分點資料開始前一點點的行情（算報酬用不到更早的）
    start_i = max(0, next((i for i, d in enumerate(days) if d >= first_broker), 0) - 1)
    if history_days:
        start_i = max(start_i, len(days) - history_days)
    days = days[start_i:]
    bm = bench(days, px)
    events = make_events(net, days, px, min_pct, min_amt)

    st = defaultdict(lambda: {"nb": 0, "ns": 0, "flip": [], "bday": [], "gap": [], "first": None, "last": None,
                              **{f"x{h}": [] for h in horizons}, **{f"d{h}": set() for h in horizons}})
    for e in events:
        t, bid, code, n, _ = e
        s = st[bid]
        s["nb" if n > 0 else "ns"] += 1
        d = days[t]
        s["first"] = min(s["first"] or d, d)
        s["last"] = max(s["last"] or d, d)
        if n > 0:
            p = px[code][d]
            s["bday"].append(p[2])
            fr = flip_ratio(e, days, net, covered)
            if fr is not None:
                s["flip"].append((fr, n))
            if t + 1 < len(days) and days[t + 1] in px[code]:
                s["gap"].append(px[code][days[t + 1]][0] / p[1] - 1)

    sigma = {}
    for h in horizons:
        pooled = []
        for e in dedup(events, h):
            x = forward_excess(days, px, bm, e[2], e[0], h)
            if x is None:
                continue
            signed = x if e[3] > 0 else -x      # 賣超後跌 = 判斷正確
            st[e[1]][f"x{h}"].append(signed)
            st[e[1]][f"d{h}"].add(e[0])
            pooled.append(signed)
        m = sum(pooled) / len(pooled) if pooled else 0.0
        sigma[h] = math.sqrt(sum((v - m) ** 2 for v in pooled) / (len(pooled) - 1)) if len(pooled) > 1 else None

    rows, cls = [], {}
    for bid, s in st.items():
        fw = sum(w for _, w in s["flip"])
        flip = sum(f * w for f, w in s["flip"]) / fw if fw else None
        r = {"bid": bid, "branch": names.get(bid, ""), "n_buy": s["nb"], "n_sell": s["ns"],
             "flip_n": len(s["flip"]), "flip_ratio": flip,
             "buy_day_ret": sum(s["bday"]) / len(s["bday"]) if s["bday"] else None,
             "next_gap": sum(s["gap"]) / len(s["gap"]) if s["gap"] else None,
             "first": s["first"], "last": s["last"]}
        for h in horizons:
            xs = s[f"x{h}"]
            r[f"n{h}"] = len(xs)
            r[f"ex{h}"] = sum(xs) / len(xs) if xs else None
            r[f"hit{h}"] = sum(1 for v in xs if v > 0) / len(xs) if xs else None
            r[f"z{h}"] = sum(xs) / (sigma[h] * math.sqrt(len(xs))) if xs and sigma[h] else None
            r[f"days{h}"] = len(s[f"d{h}"])
        z, n, nd = r.get(f"z{main}"), r.get(f"n{main}", 0), r.get(f"days{main}", 0)
        hot = r["buy_day_ret"] is not None and r["buy_day_ret"] >= hot_day
        if r["flip_n"] >= flip_min_n and flip is not None and (flip >= flip_cut or (flip >= flip_soft and hot)):
            c = CLASS_DT
        elif n < min_n or nd < min_days or z is None:
            c = CLASS_FEW
        elif z >= z_cut:
            c = CLASS_SMART
        elif z <= -z_cut:
            c = CLASS_CONTRA
        else:
            c = CLASS_NORMAL
        r["class"] = c
        cls[bid] = c
        rows.append(r)
    rows.sort(key=lambda r: (CLASS_ORDER.index(r["class"]), -(r.get(f"z{main}") or 0), -r["n_buy"]))
    return {"days": days, "as_of": days[-1] if days else as_of, "rows": rows, "cls": cls, "events": events,
            "px": px, "names": stock_names, "branch_names": names, "sigma": sigma, "horizons": list(horizons),
            "main": main}


def signals(res, day=None):
    """某天（預設最新）各類分點的動作，每檔一列。pct 為佔當天成交量 %，買超正、賣超負。"""
    days, cls = res["days"], res["cls"]
    if not days:
        return []
    day = day or days[-1]
    t = days.index(day)
    per = defaultdict(lambda: defaultdict(lambda: [0.0, []]))
    for e in res["events"]:
        if e[0] != t:
            continue
        c = cls.get(e[1])
        if c not in (CLASS_SMART, CLASS_CONTRA, CLASS_DT):
            continue
        if c == CLASS_DT and e[3] <= 0:
            continue
        a = per[e[2]][c]
        a[0] += e[4]
        a[1].append(f"{res['branch_names'].get(e[1], e[1])}{e[4]:+.1f}%")
    out = []
    for code, by in per.items():
        p = res["px"][code][day]
        out.append({"date": day, "code": code, "name": res["names"].get(code, ""), "close": p[1],
                    "chg_pct": p[2] * 100,
                    "smart_pct": by[CLASS_SMART][0], "smart_branches": " ".join(by[CLASS_SMART][1]),
                    "contra_pct": by[CLASS_CONTRA][0], "contra_branches": " ".join(by[CLASS_CONTRA][1]),
                    "daytrade_pct": by[CLASS_DT][0], "daytrade_branches": " ".join(by[CLASS_DT][1])})
    out.sort(key=lambda r: (-(r["smart_pct"] - r["contra_pct"]), r["code"]))
    return out


# ---------------- 輸出 ----------------
def _fmt(v, pct=False, nd=2):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v * 100:.{nd}f}" if pct else f"{v:.{nd}f}"
    return v


def write(res, out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hs = res["horizons"]
    cols = ["bid", "branch", "class", "n_buy", "n_sell", "flip_n", "flip_ratio", "buy_day_ret", "next_gap"]
    for h in hs:
        cols += [f"n{h}", f"days{h}", f"ex{h}", f"hit{h}", f"z{h}"]
    cols += ["first", "last"]
    pct_cols = {"flip_ratio", "buy_day_ret", "next_gap"} | {f"ex{h}" for h in hs} | {f"hit{h}" for h in hs}
    with (out_dir / "branches.csv").open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(cols)
        for r in res["rows"]:
            w.writerow([_fmt(r.get(c), c in pct_cols) for c in cols])
    sig = signals(res)
    scols = ["date", "code", "name", "close", "chg_pct", "smart_pct", "smart_branches",
             "contra_pct", "contra_branches", "daytrade_pct", "daytrade_branches"]
    with (out_dir / "signals.csv").open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(scols)
        for r in sig:
            w.writerow([_fmt(r[c]) if c != "close" else r[c] for c in scols])
    return out_dir / "branches.csv", out_dir / "signals.csv", sig


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horizons", nargs="+", type=int, default=[1, 5, 20], help="持有天數（預設 1 5 20）")
    ap.add_argument("--main", type=int, default=5, help="分類用哪個持有天數（預設 5）")
    ap.add_argument("--as-of", help="評分日 YYYY-MM-DD（預設：最新）；只用這天以前的資料")
    ap.add_argument("--min-pct", type=float, default=1.0, help="買賣超佔成交量 %% 門檻（預設 1）")
    ap.add_argument("--min-amt", type=float, default=5_000_000, help="買賣超金額門檻（元，預設 500 萬）")
    ap.add_argument("--min-n", type=int, default=10, help="分類需要的最少事件數（預設 10）")
    ap.add_argument("--min-days", type=int, default=10, help="事件至少分布在幾個不同交易日（預設 10）")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    if a.main not in a.horizons:
        a.horizons.append(a.main)
    res = score(DATA, sorted(set(a.horizons)), a.main, a.as_of, a.min_pct, a.min_amt, a.min_n, a.min_days)
    if not res["rows"]:
        print("沒有分點資料")
        return 0
    bp, sp, sig = write(res, a.out)
    counts = defaultdict(int)
    for r in res["rows"]:
        counts[r["class"]] += 1
    n_ev = len(res["events"])
    span = f"{res['days'][0]}～{res['as_of']}"
    print(f"評分到 {res['as_of']}（行情 {span}）：事件 {n_ev} 筆、分點 {len(res['rows'])} 個 → "
          + "、".join(f"{c} {counts[c]}" for c in CLASS_ORDER if counts[c]))
    rated = counts[CLASS_SMART] + counts[CLASS_CONTRA] + counts[CLASS_NORMAL]
    print(f"  可評分 {rated} 個，純靠運氣預期約 {rated * 0.0455:.1f} 個會 |z| ≥ 2"
          f"（實際 高手 {counts[CLASS_SMART]}、反指標 {counts[CLASS_CONTRA]}）")
    print(f"  {bp}\n  {sp}（{len(sig)} 檔）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
