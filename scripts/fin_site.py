"""data/financials/*.csv → 網頁用 JSON（財報查詢頁 fin.html）。

  data/fin/index.json   排行用：最新一個月全部公司的月營收、最近一季（申報家數夠多的那季）的單季重點
                        {generated, names, rev: {ym, cols, rows}, q: {yq, cols, rows}}
  data/fin/s/<代號>.json 個股：近 Rev_N 個月營收、近 Q_N 季財報
                        {code, name, market, industry, type, rev: {cols, rows}, q: {cols, rows}}

金額單位：千元（與 CSV 相同）；比率是百分比。
"""
import csv
import json
import re
import shutil
from pathlib import Path

REV_N = 60
Q_N = 20
REV_COLS = ["code", "market", "industry", "revenue", "mom", "yoy", "cum_yoy", "high_n", "note"]
Q_RANK_COLS = ["code", "market", "q_revenue", "rev_yoy", "gm", "om", "q_ni", "ni_yoy", "q_eps", "eps_yoy", "ttm_eps", "bvps", "roe"]
S_REV_COLS = ["ym", "revenue", "yoy", "cum", "cum_yoy"]
S_Q_COLS = ["yq", "revenue", "gross_profit", "operating_income", "net_income_parent", "eps",
            "total_assets", "total_liabilities", "equity_parent", "bvps"]


def _read(p):
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _f(v):
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return int(x) if x == int(x) and abs(x) >= 1 else x


def _pct(a, b):
    """a 相對 b 的增減 %（b 是 0 或負數時不算：虧損的 YoY 沒意義）。"""
    if a is None or b is None or b <= 0:
        return None
    return round((a - b) / b * 100, 2)


def _ratio(a, b):
    if a is None or not b:
        return None
    return round(a / b * 100, 2)


def load(data_dir):
    d = Path(data_dir) / "financials"
    rev = {}
    for p in sorted((d / "revenue").glob("[0-9]" * 6 + ".csv")):
        rev[p.stem] = _read(p)
    qs = {}
    for p in sorted((d / "quarterly").glob("*Q[1-4].csv")):
        qs[p.stem] = _read(p)
    return rev, qs


def high_n(series, i):
    """第 i 個月營收比之前連續幾個月都高（往回數到第一個 >= 它的月份為止）。"""
    v = series[i][1]
    if v is None:
        return None
    n = 0
    for j in range(i - 1, -1, -1):
        pv = series[j][1]
        if pv is not None and pv >= v:
            break
        n += 1
    return n


def build(rev, qs):
    months = sorted(rev)
    quarters = sorted(qs, key=lambda k: (int(k[:4]), int(k[-1])))
    names, info, rev_s, q_s = {}, {}, {}, {}
    for ym in months:
        for r in rev[ym]:
            c = r["code"]
            names[c] = r["name"]
            info.setdefault(c, {}).update(market=r["market"], industry=r["industry"])
            rev_s.setdefault(c, []).append([ym, _f(r["revenue"]), _f(r["yoy_pct"]), _f(r["cum"]), _f(r["cum_yoy_pct"])])
    for yq in quarters:
        for r in qs[yq]:
            c = r["code"]
            names.setdefault(c, r["name"])
            i = info.setdefault(c, {})
            i.setdefault("market", r["market"])
            i["type"] = r["type"]
            q_s.setdefault(c, []).append([yq, _f(r["q_revenue"]), _f(r["q_gross_profit"]), _f(r["q_operating_income"]),
                                          _f(r["q_net_income_parent"]), _f(r["q_eps"]), _f(r["total_assets"]),
                                          _f(r["total_liabilities"]), _f(r["equity_parent"]), _f(r["bvps"])])

    # 月營收排行：最新月份
    rev_rank, last_ym = [], months[-1] if months else None
    if last_ym:
        notes = {r["code"]: r["note"] for r in rev[last_ym]}
        for r in rev[last_ym]:
            c, s = r["code"], rev_s[r["code"]]
            rev_rank.append([c, r["market"], r["industry"], _f(r["revenue"]), _f(r["mom_pct"]), _f(r["yoy_pct"]),
                             _f(r["cum_yoy_pct"]), high_n(s, len(s) - 1), notes.get(c) or None])

    # 季報排行：申報家數夠多的最近一季（申報期間剛開始只有少數公司）
    q_rank, rank_yq = [], None
    if quarters:
        most = max(len(qs[k]) for k in quarters)
        rank_yq = next(k for k in reversed(quarters) if len(qs[k]) >= most * 0.6)
        y, s = int(rank_yq[:4]), int(rank_yq[-1])
        ly = f"{y - 1}Q{s}"
        for r in qs[rank_yq]:
            c = r["code"]
            hist = {x[0]: x for x in q_s[c]}
            cur, prev = hist[rank_yq], hist.get(ly)
            last4 = [hist.get(k) for k in _last4(y, s)]
            ttm = round(sum(x[5] for x in last4), 2) if all(x and x[5] is not None for x in last4) else None
            ni4 = sum(x[4] for x in last4) if all(x and x[4] is not None for x in last4) else None
            q_rank.append([c, r["market"], cur[1], _pct(cur[1], prev and prev[1]), _ratio(cur[2], cur[1]), _ratio(cur[3], cur[1]),
                           cur[4], _pct(cur[4], prev and prev[4]), cur[5], _pct(cur[5], prev and prev[5]), ttm, cur[9],
                           _ratio(ni4, cur[8]) if cur[8] and cur[8] > 0 else None])

    index = {"generated": last_ym, "names": names,
             "rev": {"ym": last_ym, "cols": REV_COLS, "rows": rev_rank},
             "q": {"yq": rank_yq, "latest": quarters[-1] if quarters else None, "cols": Q_RANK_COLS, "rows": q_rank}}
    stocks = {}
    for c in names:
        i = info.get(c, {})
        stocks[c] = {"code": c, "name": names[c], "market": i.get("market"), "industry": i.get("industry"),
                     "type": i.get("type"),
                     "rev": {"cols": S_REV_COLS, "rows": rev_s.get(c, [])[-REV_N:]},
                     "q": {"cols": S_Q_COLS, "rows": q_s.get(c, [])[-Q_N:]}}
    return index, stocks


def _last4(y, s):
    out = []
    for _ in range(4):
        out.append(f"{y}Q{s}")
        y, s = (y, s - 1) if s > 1 else (y - 1, 4)
    return out


def write_fin(data_dir, out_dir):
    rev, qs = load(data_dir)
    if not rev and not qs:
        return None
    index, stocks = build(rev, qs)
    out = Path(out_dir)
    if (out / "s").exists():
        shutil.rmtree(out / "s")
    (out / "s").mkdir(parents=True, exist_ok=True)
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    (out / "index.json").write_text(dump(index), encoding="utf-8")
    for c, s in stocks.items():
        if re.fullmatch(r"[0-9A-Z]{4,6}", c):
            (out / "s" / f"{c}.json").write_text(dump(s), encoding="utf-8")
    return index
