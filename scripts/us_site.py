"""美股連動頁（us.html）用的 JSON：美股大廠的台灣供應鏈、昨夜美股對今日台股、連動排名。

  data/us.json
    date_us / date_tw  最新美股、台股交易日（YYYY-MM-DD / YYYYMMDD）
    us       {代號: [名稱, 收盤, 漲跌%, 5 日%, 20 日%, 日期]}
    drivers  看板上的美股大廠（DRIVERS）
    tw       {代號: [名稱, 收盤, 漲跌%, 5 日%, 20 日%, 20 日均成交值（億）, 開盤跳空%]}  供應鏈與連動排名用到的台股
    supply   [[美股, 節點, 台股代號, 角色, 營收曝險, 備註], ...]  config/us_supply.csv
    react    {美股: {"thr": 門檻%, "up": 事件數, "dn": 事件數, "s": {台股: [up 跳空, up 當日, up 勝率, up 5 日, dn 跳空, dn 當日, dn 勝率, dn 5 日, up 超額, dn 超額]}}}
               美股單日漲跌超過門檻（max(3%, 1.5 倍標準差)）後，台股下一個交易日的開盤跳空、收盤漲跌、同向機率、含當天 5 日報酬（%）；
               超額＝當日漲跌減 0050。2022 年起（台股資料起點）。
    link     {美股: [[台股, 相關, beta, 超額相關, 美股漲時台股平均, 美股跌時台股平均, 隔兩日相關, 樣本數], ...]}
               最近 WIN 個台股交易日。每個台股交易日對應「前一個台股交易日之後、這天之前」的美股累積漲跌。
               超額相關＝偏相關：美股、台股報酬都先扣掉跟那斯達克 100（QQQ）一起動的部分再算相關；
               只列超額相關前 TOP 名加上供應鏈名單。

還原價用 screen_site.factors()（同 K 線頁）。
"""
import csv
import json
import math
import re
from bisect import bisect_left, bisect_right
from pathlib import Path

import kline_site
import screen_site

DRIVERS = ["NVDA", "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "AMD", "AVGO", "META"]
NAMES = {
    "NVDA": "輝達", "AAPL": "蘋果", "GOOGL": "Google", "MSFT": "微軟", "AMZN": "亞馬遜", "TSLA": "特斯拉",
    "AMD": "超微", "AVGO": "博通", "META": "Meta", "SPY": "S&P 500", "QQQ": "那斯達克 100", "^SOX": "費城半導體",
    "TSM": "台積電 ADR", "TWD=X": "美元兌台幣", "QCOM": "高通", "AMKR": "艾克爾", "GFS": "格芯", "MU": "美光",
    "WDC": "威騰", "DELL": "戴爾", "SMCI": "美超微", "JBL": "捷普", "VRT": "Vertiv", "ANET": "Arista",
    "COHR": "Coherent", "LITE": "Lumentum", "MRVL": "邁威爾", "HPQ": "惠普", "TER": "泰瑞達", "FORM": "FormFactor",
}
THR = 3.0          # 大漲大跌門檻下限（%）；實際用 max(THR, 1.5 倍日報酬標準差)，波動大的股票門檻較高
WIN = 250
TOP = 30
UNIVERSE = 400      # 連動排名掃描的台股：20 日均成交值前幾名（另外加供應鏈名單）
MARKET = "0050"
STOCK = re.compile(r"^[1-9]\d{3}$")


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)


def _pct(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def load_us(data_dir):
    """{symbol: ([YYYY-MM-DD...], [open...], [close...])}"""
    p = Path(data_dir) / "us" / "daily.csv"
    out = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            s = out.setdefault(r["symbol"], ([], [], []))
            s[0].append(r["date"])
            s[1].append(float(r["open"]))
            s[2].append(float(r["close"]))
    for k, (d, o, c) in out.items():
        z = sorted(zip(d, o, c))
        out[k] = ([x[0] for x in z], [x[1] for x in z], [x[2] for x in z])
    return out


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def tw_series(rows, events):
    """還原後 {YYYYMMDD: (開盤, 收盤)}。"""
    f = screen_site.factors(events, [r[0] for r in rows])
    return {r[0]: (r[1] * k, r[4] * k) for r, k in zip(rows, f)}


def iso(d):
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def us_by_tw(us, tw_days):
    """每個台股交易日對應的美股累積漲跌（%）：前一個台股交易日之前最後一個美股收盤 → 這天之前最後一個美股收盤。"""
    d, _, c = us
    out = {}
    prev = None
    for td in tw_days:
        i = bisect_left(d, iso(td)) - 1  # 日期嚴格小於台股日
        if i >= 0 and prev is not None and prev >= 0:
            out[td] = _pct(c[i], c[prev]) if i != prev else 0.0
        prev = i
    return out


def corr(xs, ys):
    n = len(xs)
    if n < 20:
        return None, None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None, None
    return sxy / math.sqrt(sxx * syy), sxy / sxx


def reactions(us, ser, tw_days, mkt):
    """美股大漲大跌後台股下一個交易日的反應。回傳 (up 事件數, dn 事件數, {code: [...]})。"""
    d, _, c = us
    thr = threshold(us, tw_days[0])
    events = []  # (台股日索引, 方向)
    for i in range(1, len(d)):
        ret = _pct(c[i], c[i - 1])
        if ret is None or abs(ret) < thr:
            continue
        j = bisect_right(tw_days, int(d[i].replace("-", "")))
        if j == 0 or j >= len(tw_days):
            continue
        # 中間還有別的美股交易日（台股連假）就不算，反應會混在一起
        if i + 1 < len(d) and int(d[i + 1].replace("-", "")) < tw_days[j]:
            continue
        events.append((j, 1 if ret > 0 else -1))
    n_up = sum(1 for e in events if e[1] > 0)
    out = {}
    for code, s in ser.items():
        acc = {1: [[], [], [], [], []], -1: [[], [], [], [], []]}
        for j, sg in events:
            t, p = tw_days[j], tw_days[j - 1]
            if t not in s or p not in s:
                continue
            gap, ret = _pct(s[t][0], s[p][1]), _pct(s[t][1], s[p][1])
            a = acc[sg]
            a[0].append(gap)
            a[1].append(ret)
            a[2].append(1 if ret * sg > 0 else 0)
            t5 = tw_days[min(j + 4, len(tw_days) - 1)]
            if j + 4 < len(tw_days) and t5 in s:
                a[3].append(_pct(s[t5][1], s[p][1]))
            if t in mkt and p in mkt:
                a[4].append(ret - _pct(mkt[t][1], mkt[p][1]))
        if not acc[1][1] and not acc[-1][1]:
            continue
        avg = lambda xs: _r(sum(xs) / len(xs)) if xs else None  # noqa: E731
        u, dn = acc[1], acc[-1]
        out[code] = [avg(u[0]), avg(u[1]), _r(avg(u[2]) * 100, 0) if u[2] else None, avg(u[3]),
                     avg(dn[0]), avg(dn[1]), _r(avg(dn[2]) * 100, 0) if dn[2] else None, avg(dn[3]),
                     avg(u[4]), avg(dn[4])]
    return thr, n_up, len(events) - n_up, out


def threshold(us, since):
    d, _, c = us
    s = iso(since)
    rs = [_pct(c[i], c[i - 1]) for i in range(1, len(d)) if d[i] >= s]
    if len(rs) < 20:
        return THR
    m = sum(rs) / len(rs)
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / len(rs))
    return max(THR, round(sd * 1.5 * 2) / 2)


def _resid(ys, xs):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    return [y - my - b * (x - mx) for x, y in zip(xs, ys)]


def linkage(usr, qqr, ser, tw_days, codes):
    days = tw_days[-WIN - 1:]
    rows = []
    for code in codes:
        s = ser.get(code)
        if not s:
            continue
        xs, ys, qs, lx, ly = [], [], [], [], []
        for k in range(1, len(days)):
            t, p = days[k], days[k - 1]
            if t not in s or p not in s or t not in usr or t not in qqr:
                continue
            tr = _pct(s[t][1], s[p][1])
            xs.append(usr[t])
            ys.append(tr)
            qs.append(qqr[t])
            if k + 1 < len(days) and days[k + 1] in s:
                lx.append(usr[t])
                ly.append(_pct(s[days[k + 1]][1], s[t][1]))
        c, b = corr(xs, ys)
        if c is None or len(xs) < WIN // 2:
            continue
        # 偏相關：美股、台股都先扣掉跟那斯達克 100 一起動的部分
        ce, _ = corr(_resid(xs, qs), _resid(ys, qs))
        cl, _ = corr(lx, ly)
        up = [y for x, y in zip(xs, ys) if x > 0]
        dn = [y for x, y in zip(xs, ys) if x < 0]
        rows.append([code, _r(c), _r(b), _r(ce), _r(sum(up) / len(up)) if up else None,
                     _r(sum(dn) / len(dn)) if dn else None, _r(cl), len(xs)])
    return rows


def build(prices, days, events, us, supply):
    if not days or not us:
        return None
    sup = [[r["us"], r["node"], r["code"], r["role"], r["exposure"], r.get("note", "")] for r in supply]
    sup_codes = {r[2] for r in sup}
    by_us = {}
    for r in sup:
        by_us.setdefault(r[0], set()).add(r[2])

    # 台股：20 日均成交值排名的普通股＋供應鏈＋0050
    recent = set(days[-5:])
    val = {}
    for code, s in prices.items():
        rs = s["rows"]
        if rs and rs[-1][0] in recent and len(rs) >= WIN and STOCK.match(code):
            val[code] = sum(r[4] * r[5] for r in rs[-20:]) / 20 * 1000
    universe = sorted(val, key=val.get, reverse=True)[:UNIVERSE]
    want = set(universe) | sup_codes | {MARKET}
    ser = {c: tw_series(prices[c]["rows"], events.get(c)) for c in want if c in prices}
    mkt = ser.get(MARKET, {})

    tw = {}
    for c in want:
        if c not in prices or c == MARKET:
            continue
        rs = prices[c]["rows"]
        s = ser[c]
        ds = [r[0] for r in rs]
        cl = lambda n: s[ds[-1 - n]][1] if len(ds) > n else None  # noqa: E731
        last = s[ds[-1]]
        tw[c] = [prices[c]["name"], rs[-1][4], _r(_pct(last[1], cl(1))), _r(_pct(last[1], cl(5))),
                 _r(_pct(last[1], cl(20))), _r(sum(r[4] * r[5] for r in rs[-20:]) / 20 * 1000 / 1e8),
                 _r(_pct(last[0], cl(1)))]

    usd = {}
    for k, (d, _, c) in us.items():
        n = len(c)
        usd[k] = [NAMES.get(k, k), _r(c[-1], 4 if k == "TWD=X" else 2), _r(_pct(c[-1], c[-2])) if n > 1 else None,
                  _r(_pct(c[-1], c[-6])) if n > 5 else None, _r(_pct(c[-1], c[-21])) if n > 20 else None, d[-1]]

    react, link = {}, {}
    qqr = us_by_tw(us["QQQ"], days) if "QQQ" in us else {}
    for sym in DRIVERS + ["^SOX"]:
        if sym not in us:
            continue
        codes = by_us.get(sym, sup_codes if sym == "^SOX" else set())
        thr, n_up, n_dn, st = reactions(us[sym], {c: ser[c] for c in codes if c in ser}, days, mkt)
        react[sym] = {"thr": thr, "up": n_up, "dn": n_dn, "s": st}
        rows = linkage(us_by_tw(us[sym], days), qqr, ser, days, [c for c in ser if c != MARKET])
        rows.sort(key=lambda r: -(r[3] if r[3] is not None else -9))
        keep = {r[0] for r in rows[:TOP]} | codes
        link[sym] = [r for r in rows if r[0] in keep]

    used = {r[0] for v in link.values() for r in v} | sup_codes
    return {"date_us": max(v[5] for k, v in usd.items() if k != "TWD=X"), "date_tw": days[-1], "us": usd, "drivers": DRIVERS,
            "tw": {c: v for c, v in tw.items() if c in used}, "supply": sup, "react": react, "link": link}


def write_us(data_dir, root, out_path, prices=None):
    data_dir = Path(data_dir)
    if prices is None:
        prices = kline_site.load_prices(data_dir)
    prices, days = prices
    payload = build(prices, days, kline_site.load_events(data_dir), load_us(data_dir),
                    read_csv(Path(root) / "config" / "us_supply.csv"))
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    p = write_us(root / "data", root, sys.argv[1] if len(sys.argv) > 1 else root / "_site" / "data" / "us.json")
    if p:
        print(p["date_us"], p["date_tw"], "tw", len(p["tw"]), "react", {k: (v["up"], v["dn"]) for k, v in p["react"].items()})
