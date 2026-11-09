"""族群輪動頁（site/rotation.html）→ data/rotation.json

兩組族群：
  theme  依主要產品整理的 AI 供應鏈細分族群（config/rotation_groups.csv，上游→下游）
  chain  櫃買中心產業價值鏈的產業（不含「其他」）

族群指數＝等權：每天取成分股漲跌幅（有成交的才算）的平均，連乘成指數（起點 100）。
用每日「漲跌 ÷ 前一日參考價」連乘，除權息不會被當成下跌。

輸出：
  date, days[DAYS], taiex[DAYS]                    加權指數（data/margin/index.csv，缺值沿用前一天）
  sets: {theme|chain: [{n 名稱, st 上中下游, note, codes, idx[DAYS], sh[SH] 成交值佔比%, up, dn, nh 創一年新高檔數}]}
  stocks: {代號: [名稱, 今日漲跌bp, 昨日漲跌bp, 今日成交（百萬）, 近 5 日漲跌bp]}
"""
import csv
import json
import re
from pathlib import Path

DAYS = 330          # 一年輪動圖（52 週 + 50 日均 + 10 日動能）＋今年以來
SH = 20             # 成交值佔比保留最近幾天
HIGH_N = 250        # 一年新高：收盤（還原）≥ 前 250 個交易日最高
STOCK = re.compile(r"^[1-9]\d{3}$")
ROOT = Path(__file__).resolve().parent.parent


def _price_files(data_dir, n):
    files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    return [f for f in files if len(f.stem) == 8][-n:]


def theme_groups(path=ROOT / "config" / "rotation_groups.csv"):
    out = []
    if not Path(path).exists():
        return out
    with open(path, encoding="utf-8") as fp:
        lines = [x for x in fp if x.strip() and not x.startswith("#")]
    for r in csv.DictReader(lines):
        codes = (r.get("codes") or "").split()
        if r.get("group") and codes:
            out.append({"n": r["group"].strip(), "st": (r.get("stage") or "").strip(), "note": (r.get("note") or "").strip(), "codes": codes})
    return out


def chain_groups(data_dir):
    p = Path(data_dir) / "industry" / "chain.csv"
    if not p.exists():
        return []
    by = {}
    with p.open(encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            if r["industry"] and r["industry"] != "其他":
                by.setdefault(r["industry"], set()).add(r["code"])
    order = []
    src = Path(data_dir) / "industry" / "sources.json"
    if src.exists():
        order = list((json.loads(src.read_text(encoding="utf-8")).get("industries") or {}))
    names = [i for i in order if i in by] + sorted(set(by) - set(order))
    return [{"n": k, "st": "", "note": "", "codes": sorted(by[k])} for k in names]


def _taiex(data_dir, dates):
    p = Path(data_dir) / "margin" / "index.csv"
    m = {}
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                try:
                    m[r["date"]] = float(r["taiex"])
                except (TypeError, ValueError):
                    pass
    out, last = [], None
    for d in dates:
        last = m.get(d, last)
        out.append(last)
    first = next((x for x in out if x is not None), None)
    return [x if x is not None else first for x in out]


def build(data_dir, days=DAYS):
    files = _price_files(data_dir, days)
    if not files:
        return None
    n = len(files)
    dates, pct, val, names = [], {}, {}, {}
    for k, f in enumerate(files):
        with f.open(encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
        if not rows:
            continue
        dates.append(rows[0]["date"])
        k = len(dates) - 1
        for r in rows:
            c = r["code"]
            if not STOCK.match(c):
                continue
            try:
                v = float(r["value"] or 0)
            except ValueError:
                v = 0.0
            if v <= 0:
                continue
            names[c] = r["name"]
            val.setdefault(c, [0.0] * n)[k] = v
            try:
                close, ch = float(r["close"]), float(r["change"])
                prev = close - ch
                if close > 0 and prev > 0:
                    p = ch / prev
                    if abs(p) <= 0.6:  # 擋掉新上市首日、減資等異常
                        pct.setdefault(c, [None] * n)[k] = p
            except (KeyError, TypeError, ValueError):
                pass
    n = len(dates)
    if n < 2:
        return None
    val = {c: v[:n] for c, v in val.items()}
    pct = {c: v[:n] for c, v in pct.items()}
    mkt = [sum(v[k] for v in val.values()) for k in range(n)]
    t = n - 1

    # 個股還原收盤（連乘漲跌）→ 一年新高
    def new_high(c):
        s = pct.get(c)
        if not s or s[t] is None:
            return False
        have = sum(1 for x in s if x is not None)
        if have < min(HIGH_N, n - 1) * 0.8:
            return False
        lvl, path = 1.0, []
        for x in s:
            lvl *= 1 + (x or 0)
            path.append(lvl)
        prior = path[max(0, t - HIGH_N):t]
        return bool(prior) and path[t] >= max(prior)

    nh_cache = {}

    def group(g):
        codes = [c for c in g["codes"] if c in val or c in pct]
        if not codes:
            return None
        idx, lvl = [], 100.0
        for k in range(n):
            xs = [pct[c][k] for c in codes if c in pct and pct[c][k] is not None]
            if k and xs:
                lvl *= 1 + sum(xs) / len(xs)
            idx.append(round(lvl, 3))
        sh = [round(sum(val[c][k] for c in codes if c in val) / mkt[k] * 100, 4) if mkt[k] else 0 for k in range(max(0, n - SH), n)]
        today = [pct[c][t] for c in codes if c in pct and pct[c][t] is not None]
        for c in codes:
            if c not in nh_cache:
                nh_cache[c] = new_high(c)
        return {**g, "codes": codes, "idx": idx, "sh": sh,
                "up": sum(1 for x in today if x > 0), "dn": sum(1 for x in today if x < 0),
                "nh": sum(1 for c in codes if nh_cache[c])}

    sets = {}
    for key, gs in (("theme", theme_groups()), ("chain", chain_groups(data_dir))):
        sets[key] = [x for x in (group(g) for g in gs) if x]

    def bp(x):
        return None if x is None else int(round(x * 1e4))

    stocks = {}
    for c, v in val.items():
        if not v[t]:
            continue
        s = pct.get(c, [None] * n)
        r5 = 1.0
        for k in range(max(1, n - 5), n):
            r5 *= 1 + (s[k] or 0)
        stocks[c] = [names.get(c, c), bp(s[t]), bp(s[t - 1]), int(round(v[t] / 1e6)), bp(r5 - 1)]
    return {"date": dates[-1], "days": dates, "taiex": _taiex(data_dir, dates), "sets": sets, "stocks": stocks}


def write(data_dir, out_path, days=DAYS):
    payload = build(data_dir, days)
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    p = write(ROOT / "data", sys.argv[1] if len(sys.argv) > 1 else "_site/data/rotation.json")
    print(p and {k: len(v) for k, v in p["sets"].items()}, p and p["date"])
