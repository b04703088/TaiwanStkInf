"""data/margin/ + 每日收盤 → 網頁用 JSON（融資融券頁 margin.html）。

  data/margin/market.json   大盤：每日上市／上櫃融資餘額（金額、張數）、融券張數、估計融資維持率、
                            融資增／減家數、加權指數（fetch_margin.py 的 summary.csv + index.csv）
  data/margin/stocks.json   最新一天全部個股：融資餘額與 1／5／20 日增減、股價漲跌、
                            融資市值、估計融資成本與維持率、融券餘額、券資比、融資使用率
  data/margin/s/<代號>.json 個股近 SERIES_N 個交易日：收盤、融資餘額、融券餘額、估計維持率

估計方式（官方只公布大盤融資金額，個股沒有）：
  大盤維持率 ＝ Σ(個股融資餘額張數 × 1000 × 收盤) ÷ 官方融資金額
  個股融資成本：從資料第一天起，假設既有餘額成本＝當天收盤，之後每天
    融資買進以當天收盤計入成本、償還（賣出＋現金償還）以平均成本扣除；
  個股維持率 ＝ 收盤 ÷ (平均成本 × 融資成數 0.6)。除權息、減資會讓估計失真，僅供參考。
"""
import csv
import json
from pathlib import Path

FIN_RATIO = 0.6       # 融資成數
SERIES_N = 120        # 個股走勢保留天數
MARKET_N = 250        # 大盤走勢保留天數
COST_WARMUP = 250     # 估計成本最多往回看幾天


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def margin_files(data_dir):
    return sorted(Path(data_dir).glob("margin/[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)


def closes_for(data_dir, d):
    """當日收盤 {(market, code): close}，沒有該日行情回傳空 dict。"""
    p = Path(data_dir) / d[:4] / (d.replace("-", "") + ".csv")
    if not p.exists():
        return {}
    out = {}
    for r in _read(p):
        c = _f(r.get("close"))
        if c:
            out[(r["market"], r["code"])] = c
    return out


def load_days(data_dir, limit):
    """最近 limit 個有融資資料的交易日：[(date, {(market, code): row}, closes)]，由舊到新。"""
    days = []
    for f in margin_files(data_dir)[-limit:]:
        rows = _read(f)
        if not rows:
            continue
        d = rows[0]["date"]
        days.append((d, {(r["market"], r["code"]): r for r in rows}, closes_for(data_dir, d)))
    return days


class CostTracker:
    """逐日追蹤個股融資平均成本（元／股）。"""

    def __init__(self):
        self.avg = {}   # key -> 平均成本
        self.bal = {}   # key -> 前一天餘額（張）

    def step(self, rows, closes, last_close):
        for k, r in rows.items():
            bal = _f(r.get("fin_bal")) or 0
            px = closes.get(k) or last_close.get(k)
            if px is None:
                continue
            prev_bal = self.bal.get(k)
            avg = self.avg.get(k)
            if prev_bal is None or avg is None or prev_bal <= 0:
                avg = px  # 第一天或之前沒有餘額：成本當作今天收盤
            else:
                buy = _f(r.get("fin_buy")) or 0
                out = (_f(r.get("fin_sell")) or 0) + (_f(r.get("fin_cash")) or 0)
                kept = max(prev_bal - out, 0)
                if kept + buy > 0:
                    avg = (kept * avg + buy * px) / (kept + buy)
            self.avg[k] = avg
            self.bal[k] = bal


def pct(a, b):
    if a is None or b is None or not b:
        return None
    return round((a / b - 1) * 100, 2)


def market_series(data_dir, days, summary, index):
    """大盤每日：[date, twse_amt, tpex_amt, twse_lots, tpex_lots, twse_sht, tpex_sht,
    twse_ratio, tpex_ratio, all_ratio, n_up, n_down, taiex]（金額單位：億元）。"""
    by_date = {}
    for r in summary:
        by_date.setdefault(r["date"], {})[r["market"]] = r
    idx = {r["date"]: _f(r["taiex"]) for r in index}
    out = []
    prev_rows = None
    for d, rows, closes in days:
        s = by_date.get(d, {})
        mv = {"TWSE": 0.0, "TPEx": 0.0}
        for k, r in rows.items():
            c = closes.get(k)
            b = _f(r.get("fin_bal"))
            if c and b:
                mv[k[0]] = mv.get(k[0], 0.0) + b * 1000 * c
        amt = {m: (_f(s[m]["fin_amount"]) if m in s else None) for m in ("TWSE", "TPEx")}
        ratio = {m: round(mv[m] / amt[m] * 100, 1) if amt[m] and mv[m] else None for m in amt}
        tot_amt = sum(v for v in amt.values() if v)
        all_ratio = round(sum(mv.values()) / tot_amt * 100, 1) if tot_amt and all(amt.values()) else None
        n_up = n_down = None
        if prev_rows is not None:
            n_up = n_down = 0
            for k, r in rows.items():
                b, pb = _f(r.get("fin_bal")), _f(prev_rows.get(k, {}).get("fin_bal"))
                if b is None or pb is None:
                    continue
                n_up += b > pb
                n_down += b < pb
        prev_rows = rows
        if not closes:  # 沒有當日行情：維持率算不出來
            ratio = {"TWSE": None, "TPEx": None}
            all_ratio = None
        yi = lambda v: round(v / 1e8, 2) if v else None  # noqa: E731
        lots = lambda m, f: int(_f(s[m][f])) if m in s and _f(s[m].get(f)) is not None else None  # noqa: E731
        out.append([d, yi(amt["TWSE"]), yi(amt["TPEx"]), lots("TWSE", "fin_lots"), lots("TPEx", "fin_lots"),
                    lots("TWSE", "sht_lots"), lots("TPEx", "sht_lots"),
                    ratio["TWSE"], ratio["TPEx"], all_ratio, n_up, n_down, idx.get(d)])
    return out


MARKET_COLS = ["date", "twse_amt", "tpex_amt", "twse_lots", "tpex_lots", "twse_sht", "tpex_sht",
               "twse_ratio", "tpex_ratio", "all_ratio", "n_up", "n_down", "taiex"]
STOCK_COLS = ["market", "code", "name", "close", "r1", "r5", "r20", "fin", "f1", "f5", "f5p", "f20", "f20p",
              "fin_val", "cost", "ratio", "sht", "s5", "ss_ratio", "use"]


def build(data_dir):
    data_dir = Path(data_dir)
    mdir = data_dir / "margin"
    days = load_days(data_dir, max(COST_WARMUP, MARKET_N, SERIES_N))
    if not days:
        return None
    tracker = CostTracker()
    last_close = {}
    series = {}       # key -> list of [date, close, fin, sht, ratio]
    for i, (d, rows, closes) in enumerate(days):
        tracker.step(rows, closes, last_close)
        last_close.update(closes)
        if i >= len(days) - SERIES_N:
            for k, r in rows.items():
                c = closes.get(k)
                a = tracker.avg.get(k)
                ratio = round(c / (a * FIN_RATIO) * 100) if c and a and (_f(r.get("fin_bal")) or 0) > 0 else None
                series.setdefault(k, []).append([d, c, _f(r.get("fin_bal")), _f(r.get("sht_bal")), ratio])

    def at(n):
        return days[-1 - n] if len(days) > n else None

    d0, rows0, closes0 = days[-1]
    ref = {n: at(n) for n in (1, 5, 20)}
    stocks = []
    for k, r in rows0.items():
        fin = _f(r.get("fin_bal"))
        sht = _f(r.get("sht_bal"))
        c = closes0.get(k)

        def fin_at(n):
            x = ref[n]
            return _f(x[1][k].get("fin_bal")) if x and k in x[1] else None

        def close_at(n):
            x = ref[n]
            return x[2].get(k) if x else None

        f1, f5, f20 = fin_at(1), fin_at(5), fin_at(20)
        sht5 = _f(ref[5][1][k].get("sht_bal")) if ref[5] and k in ref[5][1] else None
        cost = tracker.avg.get(k)
        limit = _f(r.get("fin_limit"))
        stocks.append([
            k[0], k[1], r.get("name", ""), c,
            pct(c, close_at(1)), pct(c, close_at(5)), pct(c, close_at(20)),
            fin,
            None if fin is None or f1 is None else int(fin - f1),
            None if fin is None or f5 is None else int(fin - f5), pct(fin, f5),
            None if fin is None or f20 is None else int(fin - f20), pct(fin, f20),
            round(fin * 1000 * c) if fin and c else None,
            round(cost, 2) if cost and fin else None,
            round(c / (cost * FIN_RATIO) * 100) if c and cost and fin else None,
            sht,
            None if sht is None or sht5 is None else int(sht - sht5),
            round(sht / fin * 100, 1) if fin and sht is not None else None,
            # 限額＝上市（櫃）股份 25%，融資使用率＝餘額 ÷ 限額
            round(fin / limit * 100, 2) if fin is not None and limit else None,
        ])
    stocks.sort(key=lambda x: -(x[13] or 0))

    summary = _read(mdir / "summary.csv") if (mdir / "summary.csv").exists() else []
    index = _read(mdir / "index.csv") if (mdir / "index.csv").exists() else []
    market = market_series(data_dir, days[-MARKET_N:], summary, index)
    return {
        "market": {"date": d0, "cols": MARKET_COLS, "rows": market},
        "stocks": {"date": d0, "cols": STOCK_COLS, "rows": stocks},
        "series": {f"{k[1]}": v for k, v in series.items()},
    }


def write_margin(data_dir, out_dir):
    payload = build(data_dir)
    if payload is None:
        return None
    out_dir = Path(out_dir)
    (out_dir / "s").mkdir(parents=True, exist_ok=True)
    dump = lambda p, o: p.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")  # noqa: E731
    dump(out_dir / "market.json", payload["market"])
    dump(out_dir / "stocks.json", payload["stocks"])
    for code, rows in payload["series"].items():
        dump(out_dir / "s" / f"{code}.json", {"cols": ["date", "close", "fin", "sht", "ratio"], "rows": rows})
    return payload
