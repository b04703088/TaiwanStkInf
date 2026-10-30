"""原物料報價頁（commod.html）用的 JSON：能源、金屬、農產品、化工、航運運價、記憶體報價的走勢與對應台股族群。

  data/commod.json
    date_tw  最新台股交易日（YYYYMMDD）
    items    [{"k", "name", "cat", "unit", "src", "d": 最新報價日, "p": 收盤,
               "r": [1 日, 5 日, 20 日, 60 日, 1 年 漲跌%], "hi", "lo": 52 週高低, "pos": 52 週位置 0～100,
               "z": 今天漲跌是近 60 日日報酬標準差的幾倍, "streak": 連漲(+)／連跌(−)天數, "wk": 週資料}, ...]
               週資料（SCFI 等）的「1 日」是上一期、「5 日」是 4 期前、「20 日」是 13 期前，依 ROWS 換算
    series   {k: [[YYYY-MM-DD, 收盤], ...]}  近 SERIES_DAYS 天
    groups   [[品項, 族群, 受惠/成本, 說明, [代號...], 族群 5 日%, 族群 20 日%, 60 日相關, 品項漲時族群平均%, 樣本數], ...]
               族群＝等權平均（還原權息）；相關＝每個台股交易日對應「前一個台股交易日之後、這天之前」的報價累積漲跌，
               跟族群當天漲跌的相關（最近 WIN 天）。週資料不算相關。
    tw       {代號: [名稱, 收盤, 漲跌%, 5 日%, 20 日%]}

品項定義在 config/commod_items.csv，族群對應在 config/commod_map.csv（產業鏈／細分族群，不用官方產業分類）。
"""
import csv
import json
import math
import statistics
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import kline_site
import us_site

SERIES_DAYS = 800   # 圖表保留的日曆天數（約 2 年）
WIN = 120           # 相關係數用最近幾個台股交易日
MIN_POS = 10        # 資料少於幾筆不算 52 週位置（SCFI、記憶體是上線後才開始累積）
MIN_CORR = 60
CATS = ["能源", "金屬", "農產品", "化工", "航運", "科技"]


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)


def _pct(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def load(data_dir):
    """{key: ([YYYY-MM-DD...], [close...])}"""
    p = Path(data_dir) / "commod" / "daily.csv"
    out = {}
    for r in us_site.read_csv(p):
        try:
            v = float(r["close"])
        except (TypeError, ValueError):
            continue
        s = out.setdefault(r["key"], {})
        s[r["date"]] = v
    return {k: (sorted(v), [v[d] for d in sorted(v)]) for k, v in out.items()}


def weekly(dates):
    """平均間隔超過 4 天就當週資料。"""
    ds = dates[-6:]
    if len(ds) < 2:
        return False
    a, b = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    return (b - a).days / (len(ds) - 1) > 4


def stats(dates, closes):
    n = len(closes)
    wk = weekly(dates)
    steps = (1, 1, 4, 13, 52) if wk else (1, 5, 20, 60, 250)
    last = closes[-1]
    r = [_r(_pct(last, closes[-1 - s])) if n > s else None for s in steps[:4]]
    # 1 年用日曆天：一年前那天（或之前最近一筆）的收盤；資料起點晚於一年前 7 天以上就不算
    cut = (date.fromisoformat(dates[-1]) - timedelta(days=365)).isoformat()
    i = bisect_right(dates, cut) - 1
    if i < 0 and dates[0] <= (date.fromisoformat(cut) + timedelta(days=7)).isoformat():
        i = 0
    r.append(_r(_pct(last, closes[i])) if i >= 0 and n > 1 else None)
    yr = [c for d, c in zip(dates, closes) if d > cut]
    hi, lo = max(yr), min(yr)
    pos = _r((last - lo) / (hi - lo) * 100, 0) if hi > lo and len(yr) >= MIN_POS else None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, n - 61), n) if closes[i - 1]]
    z = None
    if not wk and len(rets) >= 30:
        sd = statistics.pstdev(rets[:-1])
        z = _r(rets[-1] / sd, 1) if sd else None
    streak = 0
    for i in range(n - 1, 0, -1):
        d = (closes[i] > closes[i - 1]) - (closes[i] < closes[i - 1])
        if d == 0 or (streak and (d > 0) != (streak > 0)):
            break
        streak += d
    return {"r": r, "hi": hi, "lo": lo, "pos": pos, "z": z, "streak": streak, "wk": wk}


def build(prices, days, events, series, items, mapping):
    if not series:
        return None
    out_items, out_series = [], {}
    for it in items:
        k = it["key"]
        if k not in series:
            continue
        d, c = series[k]
        s = stats(d, c)
        out_items.append({"k": k, "name": it["name"], "cat": it["cat"], "sub": it.get("sub", ""), "unit": it["unit"], "src": it.get("label", ""),
                          "d": d[-1], "p": c[-1], **s})
        cut = (date.fromisoformat(d[-1]) - timedelta(days=SERIES_DAYS)).isoformat()
        out_series[k] = [[x, y] for x, y in zip(d, c) if x > cut]

    have = {i["k"]: i for i in out_items}
    codes = {c for r in mapping for c in r["codes"].split()}
    ser = {c: us_site.tw_series(prices[c]["rows"], events.get(c)) for c in codes if c in prices}
    tw = {}
    for c, s in ser.items():
        rs = prices[c]["rows"]
        ds = [r[0] for r in rs]
        cl = lambda n: s[ds[-1 - n]][1] if len(ds) > n else None  # noqa: E731
        tw[c] = [prices[c]["name"], rs[-1][4], _r(_pct(s[ds[-1]][1], cl(1))), _r(_pct(s[ds[-1]][1], cl(5))),
                 _r(_pct(s[ds[-1]][1], cl(20)))]

    recent = days[-WIN - 1:]
    groups = []
    for m in mapping:
        k = m["item"]
        if k not in have:
            continue
        cs = [c for c in m["codes"].split() if c in ser]
        g5 = [tw[c][3] for c in cs if tw[c][3] is not None]
        g20 = [tw[c][4] for c in cs if tw[c][4] is not None]
        rho, up, n = None, None, 0
        if not have[k]["wk"] and cs and len(series[k][0]) >= MIN_CORR:
            cr = us_site.us_by_tw((series[k][0], None, series[k][1]), recent)
            xs, ys = [], []
            for i in range(1, len(recent)):
                td, pd = recent[i], recent[i - 1]
                if td not in cr:
                    continue
                rr = [_pct(ser[c][td][1], ser[c][pd][1]) for c in cs if td in ser[c] and pd in ser[c]]
                if rr:
                    xs.append(cr[td])
                    ys.append(sum(rr) / len(rr))
            rho, _ = us_site.corr(xs, ys)
            n = len(xs)
            ups = [y for x, y in zip(xs, ys) if x > 0]
            up = sum(ups) / len(ups) if ups else None
        groups.append([k, m["group"], m["effect"], m.get("note", ""), cs,
                       _r(sum(g5) / len(g5)) if g5 else None, _r(sum(g20) / len(g20)) if g20 else None,
                       _r(rho), _r(up), n])
    return {"date_tw": days[-1] if days else None, "cats": CATS, "items": out_items, "series": out_series,
            "groups": groups, "tw": tw}


def write_commod(data_dir, root, out_path, prices=None):
    data_dir = Path(data_dir)
    if prices is None:
        prices = kline_site.load_prices(data_dir)
    prices, days = prices
    payload = build(prices, days, kline_site.load_events(data_dir), load(data_dir),
                    us_site.read_csv(Path(root) / "config" / "commod_items.csv"),
                    us_site.read_csv(Path(root) / "config" / "commod_map.csv"))
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    p = write_commod(root / "data", root, sys.argv[1] if len(sys.argv) > 1 else root / "_site" / "data" / "commod.json")
    if p:
        print(p["date_tw"], "items", len(p["items"]), "groups", len(p["groups"]))
