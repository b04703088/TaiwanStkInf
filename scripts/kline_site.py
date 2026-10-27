"""data/<YYYY>/*.csv ＋ data/adjust/events.csv → K 線頁（kline.html）用的 JSON。

  data/kline/index.json    {last, stocks: [[代號, 名稱, 市場], ...]}（最近 LIVE_DAYS 個交易日有成交的）
  data/kline/s/<代號>.json  {code, name, market, d, o, h, l, c, v, ev}
                           d   日期 YYYYMMDD（整數）；o/h/l/c 原始價；v 成交量（張）
                           ev  [[YYYYMMDD, factor, kind, note, cash], ...] 還原因子事件（見 fetch_adjust.py）
還原在網頁上算：日期 t 的價格 × 所有事件日 > t 的 factor 連乘（同 adjust.py）。
"""
import csv
import json
import shutil
from pathlib import Path

LIVE_DAYS = 20


def _n(v):
    """'2440.00' → 2440；'47.57' → 47.57；空白 → None。"""
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return int(x) if x == int(x) else round(x, 4)


def load_prices(data_dir):
    """{code: {"name", "market", "rows": [(YYYYMMDD, o, h, l, c, 張)]}}，依日期排序；沒成交的日子略過。"""
    out = {}
    files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    for p in files:
        d = int(p.stem)
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                c = _n(r["close"])
                if c is None:
                    continue
                code = r["code"].strip()
                s = out.setdefault(code, {"rows": []})
                s["name"], s["market"] = r["name"].strip(), r["market"]  # 用最新一天的名稱、市場（上櫃轉上市）
                o, h, lo = _n(r["open"]), _n(r["high"]), _n(r["low"])
                vol = _n(r["volume"]) or 0
                s["rows"].append((d, o if o is not None else c, h if h is not None else c,
                                  lo if lo is not None else c, c, round(vol / 1000)))
    return out, [int(p.stem) for p in files]


def load_events(data_dir):
    out = {}
    p = Path(data_dir) / "adjust" / "events.csv"
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            try:
                f = float(r["factor"])
            except ValueError:
                continue
            if f <= 0:
                continue
            out.setdefault(r["code"], []).append([int(r["date"].replace("-", "")), f, r["kind"], r["note"], _n(r["cash"])])
    for v in out.values():
        v.sort()
    return out


def build(prices, events, days):
    """回傳 (index, {code: payload})。只收最近 LIVE_DAYS 個交易日還有成交的（下市的不放）。"""
    recent = set(days[-LIVE_DAYS:])
    stocks, per = [], {}
    for code in sorted(prices):
        s = prices[code]
        rows = s["rows"]
        if not rows or rows[-1][0] not in recent:
            continue
        first = rows[0][0]
        ev = [e for e in events.get(code, []) if e[0] > first]  # 第一筆價格之前的事件不影響圖
        per[code] = {"code": code, "name": s["name"], "market": s["market"],
                     "d": [r[0] for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
                     "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows], "ev": ev}
        stocks.append([code, s["name"], s["market"]])
    return {"last": days[-1] if days else None, "stocks": stocks}, per


def write_kline(data_dir, out_dir, loaded=None):
    """loaded: 已經讀好的 load_prices(data_dir) 結果（選股頁共用，省一次讀檔）。"""
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "s").mkdir(parents=True)
    prices, days = loaded or load_prices(data_dir)
    index, per = build(prices, load_events(data_dir), days)
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    (out_dir / "index.json").write_text(dump(index), encoding="utf-8")
    for code, payload in per.items():
        (out_dir / "s" / f"{code}.json").write_text(dump(payload), encoding="utf-8")
    return len(per)
