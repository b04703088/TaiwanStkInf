"""創新高頁（newhigh.html）用的 JSON：近 60 個交易日哪些股票、哪些族群在創新高。

  data/newhigh.json
    days     最近 DAYS 個交易日 [YYYYMMDD...]
    breadth  {"hi": [每天創 52 週新高家數], "lo": [創 52 週新低家數], "ath": [創 2022 年以來新高家數]}
    cols     rows 的欄位
    rows     每檔一列（上市櫃普通股、最近 5 天有成交、至少有 250 天資料）；value＝近 20 日平均成交金額（億），vol＝最新一天成交張數
               hi / ath 是 days 的索引：那天收盤創 52 週新高／2022 年以來新高
    groups   {"off": 官方產業別, "ind": 產業價值鏈產業, "sub": 產業價值鏈細類}，每個 [名稱, 路徑, [rows 索引...]]

用還原收盤價（同 screen_site.tech()）：「創 52 週新高」＝收盤是含當天在內最近 250 個交易日的最高，
不會被除權息切斷。股價資料從 2022 年開始，所以「歷史新高」只能算 2022 年以來。
"""
import json
import re
from pathlib import Path

import industry_site
import kline_site
import screen_site

DAYS = 60
WIN = 250
STOCK = re.compile(r"^[1-9]\d{3}$")
COLS = ["code", "name", "market", "close", "chg", "r5", "r20", "r60", "dist", "value", "vol", "hi", "ath"]


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if b else None


def scan(rows, events, days):
    """rows: [(YYYYMMDD, o, h, l, c, 張)]。回傳 (hi_days, lo_days, ath_days, 欄位 dict)，days 以外的日子不算。"""
    f = screen_site.factors(events, [r[0] for r in rows])
    c = [r[4] * k for r, k in zip(rows, f)]
    pos = {d: i for i, d in enumerate(days)}
    hi, lo, ath = [], [], []
    start = max(WIN - 1, next((i for i, r in enumerate(rows) if r[0] >= days[0]), len(rows)))
    run = max(c[:start]) if start else 0  # 2022 年以來到前一天的最高
    for i in range(start, len(c)):
        j = pos.get(rows[i][0])
        if j is not None:
            win = c[i - WIN + 1:i]
            if c[i] > max(win):
                hi.append(j)
            if c[i] < min(win):
                lo.append(j)
            if c[i] > run:
                ath.append(j)
        run = max(run, c[i])
    last = c[-1]
    ret = {n: _pct(last, c[-1 - n]) if len(c) > n else None for n in (1, 5, 20, 60)}
    val = [r[4] * r[5] * 1000 for r in rows[-20:]]
    info = {"close": rows[-1][4], "chg": ret[1], "r5": ret[5], "r20": ret[20], "r60": ret[60],
            "dist": _pct(last, max(c[-WIN:])), "value": round(sum(val) / len(val) / 1e8, 2), "vol": rows[-1][5]}
    return hi, lo, ath, info


def build(prices, days_all, events, ind):
    days = days_all[-DAYS:]
    recent = set(days_all[-5:])
    n = len(days)
    b_hi, b_lo, b_ath = [0] * n, [0] * n, [0] * n
    rows, ix = [], {}
    for code in sorted(prices):
        s = prices[code]
        r = s["rows"]
        if not STOCK.match(code) or len(r) < WIN or r[-1][0] not in recent:
            continue
        hi, lo, ath, info = scan(r, events.get(code), days)
        for arr, hits in ((b_hi, hi), (b_lo, lo), (b_ath, ath)):
            for j in hits:
                arr[j] += 1
        ix[code] = len(rows)
        rows.append([code, s["name"], "上市" if s["market"] == "TWSE" else "上櫃"]
                    + [info[k] for k in COLS[3:11]] + [hi, ath])

    groups = {"off": [], "ind": [], "sub": []}
    if ind:
        members, by_ind, by_off = {}, {}, {}
        for code, s in ind["stocks"].items():
            if code not in ix:
                continue
            for i in s[2]:
                members.setdefault(i, set()).add(ix[code])
                by_ind.setdefault(ind["nodes"][i][0], set()).add(ix[code])
            if s[1] and s[1] not in ("存託憑證", "管理股票"):
                by_off.setdefault(s[1], set()).add(ix[code])
        for i, node in enumerate(ind["nodes"]):
            if members.get(i):
                label = node[3] or node[2]
                path = " › ".join(x for x in (node[0], node[1], node[2] if node[3] else "") if x)
                groups["sub"].append([label, path, sorted(members[i])])
        groups["ind"] = [[k, "產業價值鏈", sorted(v)] for k, v in by_ind.items()]
        groups["off"] = [[k, "官方產業別", sorted(v)] for k, v in by_off.items()]
    return {"date": days[-1] if days else None, "days": days,
            "breadth": {"hi": b_hi, "lo": b_lo, "ath": b_ath}, "cols": COLS, "rows": rows, "groups": groups}


def write_newhigh(data_dir, out_path, prices=None):
    data_dir = Path(data_dir)
    if prices is None:
        prices = kline_site.load_prices(data_dir)
    prices, days = prices
    if not days:
        return None
    payload = build(prices, days, kline_site.load_events(data_dir), industry_site.build(data_dir))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    p = write_newhigh(root / "data", sys.argv[1] if len(sys.argv) > 1 else root / "_site" / "data" / "newhigh.json")
    print(p["date"], "rows", len(p["rows"]), "hi today", p["breadth"]["hi"][-1], "lo today", p["breadth"]["lo"][-1])
