"""選股頁（screen.html）用的 JSON：每檔一列，把技術面、營收、財報、股利與籌碼放在一起，網頁上用條件篩。

  data/screen/screen.json  {date, cols, rows, ind}
      rows 每檔一列，欄位見 COLS；沒有的資料是 null。ind 是產業名稱表（rows 存索引）。
  data/screen/div.json     除權息與填息（見 dividends()）

技術面用還原價（data/adjust/events.csv，同 adjust.py）：最新一天不變，之前的價格乘之後事件的因子連乘，
報酬率、均線、52 週高點才不會被除權息切斷。成交金額用原始收盤 × 張數估。
營收、財報來自 data/financials/（同 fin_site.py）；股利殖利率＝近 365 天除息現金合計 ÷ 收盤。
籌碼欄位（三大法人、借券、當沖、集保大戶）由各自的模組算好傳進來（extra），沒有就留空。
"""
import csv
import json
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import fin_site
import kline_site

TECH = ["close", "chg", "r5", "r20", "r60", "r250", "ma20", "ma60", "ma120", "bull", "hi250", "new_hi",
        "vr", "value", "sq", "bo"]
FUND = ["rev_ym", "rev_yoy", "rev_n", "rev_hi", "cum_yoy", "rev_acc",
        "yq", "gm", "gm_d", "om", "om_d", "eps_q", "eps_ttm", "eps_yoy", "roe", "pe", "pb", "dy"]
BASE = ["code", "name", "market", "ind"]
MIN_DAYS = 20          # 上市不到 20 個交易日的不算技術面
DIV_KINDS = {"除息", "除權", "除權息"}
FILL_MAX = 250         # 填息最多追幾個交易日


def _r(x, n=2):
    return None if x is None else round(x, n)


def _pct(a, b):
    if a is None or not b:
        return None
    return round((a / b - 1) * 100, 2)


def factors(events, dates):
    """每個價格日的還原倍數 list（同 adjust.py：日期 t 乘所有事件日 > t 的 factor）。events: [[YYYYMMDD, f, ...]]"""
    if not events:
        return [1.0] * len(dates)
    ev_d = [e[0] for e in events]
    cum, c = [], 1.0
    for e in reversed(events):
        c *= e[1]
        cum.append(c)
    cum.reverse()
    out = []
    for d in dates:
        i = bisect_right(ev_d, d)
        out.append(cum[i] if i < len(cum) else 1.0)
    return out


def _ma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def tech(rows, events):
    """rows: [(YYYYMMDD, o, h, l, c, 張)]。回傳 TECH 欄位 dict。"""
    if len(rows) < MIN_DAYS:
        return None
    f = factors(events, [r[0] for r in rows])
    c = [r[4] * k for r, k in zip(rows, f)]
    h = [r[2] * k for r, k in zip(rows, f)]
    v = [r[5] / k for r, k in zip(rows, f)]
    last = c[-1]
    ma = {n: _ma(c, n) for n in (5, 20, 60, 120)}
    ret = {n: _pct(last, c[-1 - n]) if len(c) > n else None for n in (1, 5, 20, 60, 250)}
    win = c[-250:]
    hi = max(win)
    prev_hi = max(c[-250:-1]) if len(c) > 1 else None
    v20 = sum(v[-21:-1]) / 20 if len(v) > 20 else None
    vr = round(v[-1] / v20, 2) if v20 else None
    ms = [ma[5], ma[20], ma[60]]
    sq = _r((max(ms) - min(ms)) / last * 100) if all(ms) else None
    bull = int(bool(ma[120]) and last > ma[20] > ma[60] > ma[120])
    hi20 = max(h[-21:-1]) if len(h) > 20 else None
    bo = int(bool(hi20) and last > hi20 and (vr or 0) >= 2 and (ret[1] or 0) > 0)
    return {"close": rows[-1][4], "chg": ret[1], "r5": ret[5], "r20": ret[20], "r60": ret[60], "r250": ret[250],
            "ma20": _pct(last, ma[20]), "ma60": _pct(last, ma[60]), "ma120": _pct(last, ma[120]), "bull": bull,
            "hi250": _pct(last, hi), "new_hi": int(len(c) >= 120 and prev_hi is not None and last > prev_hi),
            "vr": vr, "value": _r(rows[-1][4] * rows[-1][5] * 1000 / 1e8), "sq": sq, "bo": bo}


def fundamentals(index, stocks, close, cash_365):
    """fin_site.build() 的結果 → {code: FUND 欄位}。"""
    out = {}
    rev_ym = index["rev"]["ym"]
    yq = index["q"]["yq"]
    for c, s in stocks.items():
        d = {}
        rev = s["rev"]["rows"]  # [ym, revenue, yoy, cum, cum_yoy]
        if rev and rev[-1][0] == rev_ym:
            yoys = [x[2] for x in rev]
            n = 0
            for y in reversed(yoys):
                if y is None or y <= 0:
                    break
                n += 1
            a3 = [y for y in yoys[-3:] if y is not None]
            b3 = [y for y in yoys[-6:-3] if y is not None]
            d.update(rev_ym=rev_ym, rev_yoy=yoys[-1], rev_n=n, rev_hi=fin_site.high_n([[x[0], x[1]] for x in rev], len(rev) - 1),
                     cum_yoy=rev[-1][4],
                     rev_acc=_r(sum(a3) / 3 - sum(b3) / 3) if len(a3) == 3 and len(b3) == 3 else None)
        q = {x[0]: x for x in s["q"]["rows"]}  # [yq, revenue, gp, oi, ni, eps, ta, tl, eq, bvps]
        cur = q.get(yq)
        if cur and cur[1]:
            y, sn = int(yq[:4]), int(yq[-1])
            ly = q.get(f"{y - 1}Q{sn}")
            last4 = [q.get(k) for k in fin_site._last4(y, sn)]
            ttm = round(sum(x[5] for x in last4), 2) if all(x and x[5] is not None for x in last4) else None
            ni4 = sum(x[4] for x in last4) if all(x and x[4] is not None for x in last4) else None

            def margin(x, i):
                return round(x[i] / x[1] * 100, 2) if x and x[1] and x[i] is not None else None
            gm, om = margin(cur, 2), margin(cur, 3)
            lgm, lom = margin(ly, 2), margin(ly, 3)
            px = close.get(c)
            d.update(yq=yq, gm=gm, gm_d=_r(gm - lgm) if gm is not None and lgm is not None else None,
                     om=om, om_d=_r(om - lom) if om is not None and lom is not None else None,
                     eps_q=cur[5], eps_ttm=ttm,
                     eps_yoy=fin_site._pct(cur[5], ly and ly[5]),
                     roe=_r(ni4 / cur[8] * 100) if ni4 is not None and cur[8] and cur[8] > 0 else None,
                     pe=_r(px / ttm, 1) if px and ttm and ttm > 0 else None,
                     pb=_r(px / cur[9]) if px and cur[9] and cur[9] > 0 else None)
        px = close.get(c)
        if px and cash_365.get(c):
            d["dy"] = _r(cash_365[c] / px * 100)
        if d:
            out[c] = d
    return out


def cash_last_year(events, today):
    """近 365 天（含今天以前）除息現金合計 {code: 元}。"""
    since = int((today - timedelta(days=365)).strftime("%Y%m%d"))
    t = int(today.strftime("%Y%m%d"))
    out = {}
    for code, evs in events.items():
        s = sum(e[4] for e in evs if since < e[0] <= t and e[2] in DIV_KINDS and e[4])
        if s:
            out[code] = round(s, 4)
    return out


def dividends(prices, events_csv, today, days_back=730):
    """除權息事件 + 填息天數。

    填息：除權息日（含）之後第一個收盤 ≥ 除權息前收盤的交易日；天數＝從除權息日起算第幾個交易日（當天就填＝1）。
    回傳 {date, cols, rows, stats_cols, stats}
      rows   每個事件 [date, code, name, kind, prev_close, ref_price, cash, yield, fill_days, fill_date, days_since]
             未來（還沒到除權息日）的 fill_days 等都是 null；還沒填息的 fill_days null、days_since＝已經過幾個交易日
      stats  每檔 [code, n, n_filled, median_fill_days, avg_yield]（近 days_back 天、已過除權息日的事件）
    """
    t = int(today.strftime("%Y%m%d"))
    since = (today - timedelta(days=days_back)).isoformat()
    rows = []
    with Path(events_csv).open(encoding="utf-8") as fp:
        evs = [r for r in csv.DictReader(fp) if r["kind"] in DIV_KINDS and r["date"] >= since]
    for e in evs:
        d = int(e["date"].replace("-", ""))
        prev = kline_site._n(e["prev_close"])
        cash = kline_site._n(e["cash"])
        yld = _r(cash / prev * 100) if cash and prev else None
        fill = fdate = since_n = None
        p = prices.get(e["code"])
        if d <= t and p and prev:
            ds = [r[0] for r in p["rows"]]
            i = bisect_right(ds, d - 1)
            after = p["rows"][i:i + FILL_MAX]
            for k, r in enumerate(after, 1):
                if r[4] >= prev:
                    fill, fdate = k, r[0]
                    break
            if fill is None:
                since_n = len(after)
        rows.append([d, e["code"], p["name"] if p else e["name"], e["kind"], prev, kline_site._n(e["ref_price"]), cash, yld, fill, fdate, since_n])
    rows.sort(key=lambda r: (-r[0], r[1]))
    stats = {}
    for r in rows:
        if r[0] > t or (r[8] is None and r[10] is None):
            continue
        s = stats.setdefault(r[1], {"n": 0, "f": [], "y": []})
        s["n"] += 1
        if r[8] is not None:
            s["f"].append(r[8])
        if r[7] is not None:
            s["y"].append(r[7])
    st = []
    for c, s in sorted(stats.items()):
        f = sorted(s["f"])
        med = f[len(f) // 2] if len(f) % 2 else (f[len(f) // 2 - 1] + f[len(f) // 2]) / 2 if f else None
        st.append([c, s["n"], len(f), med, _r(sum(s["y"]) / len(s["y"])) if s["y"] else None])
    return {"date": t, "cols": ["date", "code", "name", "kind", "prev_close", "ref_price", "cash", "yield", "fill_days",
                                "fill_date", "days_since"],
            "rows": rows, "stats_cols": ["code", "n", "n_filled", "median_fill", "avg_yield"], "stats": st}


def industries(data_dir):
    """{code: 產業}：官方產業別。"""
    p = Path(data_dir) / "industry" / "official.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fp:
        return {r["code"]: r["industry"] for r in csv.DictReader(fp)}


def build(prices, days, events, fin, ind, today, extra=None):
    """prices/days: kline_site.load_prices()；events: kline_site.load_events()；fin: fin_site.build() 或 None。
    extra: {欄位群名稱: (cols, {code: {col: v}})} 籌碼等其他來源。"""
    extra = extra or {}
    recent = set(days[-5:])
    techs, close = {}, {}
    for code, s in prices.items():
        rows = s["rows"]
        if not rows or rows[-1][0] not in recent:
            continue
        t = tech(rows, events.get(code))
        if t:
            techs[code] = t
            close[code] = rows[-1][4]
    funds = fundamentals(fin[0], fin[1], close, cash_last_year(events, today)) if fin else {}
    xcols = [c for cols, _ in extra.values() for c in cols]
    cols = BASE + TECH + FUND + xcols
    ind_names = sorted({v for v in ind.values() if v})
    ind_ix = {v: i for i, v in enumerate(ind_names)}
    rows = []
    for code in sorted(techs):
        s = prices[code]
        base = [code, s["name"], "上市" if s["market"] == "TWSE" else "上櫃", ind_ix.get(ind.get(code))]
        t, fd = techs[code], funds.get(code, {})
        x = [m.get(code, {}).get(c) for cols_, m in extra.values() for c in cols_]
        rows.append(base + [t[c] for c in TECH] + [fd.get(c) for c in FUND] + x)
    return {"date": days[-1] if days else None, "cols": cols, "ind": ind_names, "rows": rows}


def write_screen(data_dir, out_dir, today=None, extra=None, prices=None):
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    today = today or date.today()
    if prices is None:
        prices, days = kline_site.load_prices(data_dir)
    else:
        prices, days = prices
    if not days:
        return None
    events = kline_site.load_events(data_dir)
    rev, qs = fin_site.load(data_dir)
    fin = fin_site.build(rev, qs) if rev or qs else None
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    sc = build(prices, days, events, fin, industries(data_dir), today, extra)
    (out_dir / "screen.json").write_text(dump(sc), encoding="utf-8")
    ev = data_dir / "adjust" / "events.csv"
    if ev.exists():
        (out_dir / "div.json").write_text(dump(dividends(prices, ev, today)), encoding="utf-8")
    return sc
