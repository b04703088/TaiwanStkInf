"""data/margin/ + 每日收盤 → 網頁用 JSON（融資融券頁 margin.html）。

  data/margin/market.json   大盤：每日上市／上櫃融資餘額（金額、張數）、融券張數、估計融資維持率、
                            融資增／減家數、加權指數（fetch_margin.py 的 summary.csv + index.csv）
  data/margin/stocks.json   最新一天全部個股：融資餘額與 1／5／20 日增減、股價漲跌、
                            融資市值、估計融資成本與維持率、融券餘額、券資比、融資使用率
  data/margin/s/<代號>.json 個股近 SERIES_N 個交易日：收盤、融資餘額、融券餘額、估計維持率、不限用途借貸擔保張數
  data/margin/delev.json    去槓桿進度（殺乾淨了沒）：大盤融資張數離高點、連續大減、維持率、
                            台股正 2／反 1 ETF 的融資與受益單位、主動式 ETF 融資合計（見 deleverage()）
  data/margin/level.json    融資水位（融資金額 ÷ 市值）近幾年走勢、分位、平均 ±σ、歷次過熱後指數回檔；
                            融資使用率、券資比的歷史分位（歷史來自 data/margin/level.csv，見 backfill_margin_level.py）
不限用途款項借貸（data/pledge/，證交所借貸款項擔保品餘額表）：個股被拿去質押借錢的張數與限額；
  大盤加總擔保市值＝Σ(擔保張數 × 1000 × 收盤)。

估計方式（官方只公布大盤融資金額，個股沒有）：
  大盤維持率 ＝ Σ(個股融資餘額張數 × 1000 × 收盤) ÷ 官方融資金額
  個股融資成本：從資料第一天起，假設既有餘額成本＝當天收盤，之後每天
    融資買進以當天收盤計入成本、償還（賣出＋現金償還）以平均成本扣除；
  個股維持率 ＝ 收盤 ÷ (平均成本 × 融資成數 0.6)。除權息、減資會讓估計失真，僅供參考。
"""
import csv
import json
import re
from pathlib import Path

FIN_RATIO = 0.6       # 融資成數
SERIES_N = 250        # 個股走勢保留天數（K 線頁副圖也用，約一年）
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


def pledge_for(data_dir, d):
    """當日借貸款項擔保品 {(market, code): row}，沒有資料回傳空 dict。"""
    p = Path(data_dir) / "pledge" / d[:4] / (d.replace("-", "") + ".csv")
    return {(r["market"], r["code"]): r for r in _read(p)} if p.exists() else {}


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


# ───────────── 融資水位（占市值）每日彙總 ─────────────
# 市值：融資限額＝上市（櫃）股份 25%，所以 股數 ≈ 限額 × 4，市值 ≈ Σ 限額 × 4 × 1000 × 收盤（只算一般股，不含 ETF）。
# 只涵蓋可融資的股票（全額交割、停止信用交易的不在名單內），是近似值；看的是自己跟自己比的相對位置。
LEVEL_COLS = ["date", "market", "fin_lots", "fin_amount", "sht_lots", "use_bal", "use_lim", "mcap", "x_amt", "x_mcap"]
STOCK_RE = re.compile(r"^[1-9]\d{3}$")
EXCL = "2330"   # 台積電：市值占上市四成、融資極少，算「不含台積電」的水位


def level_rows(d, rows, closes, summary):
    """單日彙總 → [每市場一列 dict]。rows：{(market, code): row}；summary：{market: summary row}。"""
    out = []
    for m in ("TWSE", "TPEx"):
        s = summary.get(m)
        if not s:
            continue
        use_bal = use_lim = mcap = x_amt = x_mcap = 0.0
        for (mk, code), r in rows.items():
            if mk != m:
                continue
            bal, lim = _f(r.get("fin_bal")) or 0, _f(r.get("fin_limit")) or 0
            if lim > 0:
                use_bal += bal
                use_lim += lim
            c = closes.get((mk, code))
            if c and lim > 0 and STOCK_RE.match(code):
                cap = lim * 4 * 1000 * c
                mcap += cap
                if code == EXCL:
                    x_mcap, x_amt = cap, bal * 1000 * c * FIN_RATIO
        if not mcap:
            continue
        out.append({"date": d, "market": m, "fin_lots": s.get("fin_lots", ""), "fin_amount": s.get("fin_amount", ""),
                    "sht_lots": s.get("sht_lots", ""), "use_bal": int(use_bal), "use_lim": int(use_lim),
                    "mcap": int(mcap), "x_amt": int(x_amt), "x_mcap": int(x_mcap)})
    return out


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
        pl = pledge_for(data_dir, d)
        ul_lots = sum(_f(r.get("ul_bal")) or 0 for r in pl.values()) if pl else None
        ul_val = sum((_f(r.get("ul_bal")) or 0) * 1000 * closes[k] for k, r in pl.items() if closes.get(k)) if pl and closes else None
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
                    ratio["TWSE"], ratio["TPEx"], all_ratio, n_up, n_down, idx.get(d),
                    None if ul_lots is None else int(ul_lots), yi(ul_val)])
    return out


MARKET_COLS = ["date", "twse_amt", "tpex_amt", "twse_lots", "tpex_lots", "twse_sht", "tpex_sht",
               "twse_ratio", "tpex_ratio", "all_ratio", "n_up", "n_down", "taiex", "ul_lots", "ul_amt"]
STOCK_COLS = ["market", "code", "name", "close", "r1", "r5", "r20", "fin", "f1", "f5", "f5p", "f20", "f20p",
              "fin_val", "cost", "ratio", "sht", "s5", "ss_ratio", "use",
              "ul", "ul1", "ul5", "ul5p", "ul20p", "ul_val", "ul_use", "sf", "val5", "sp", "s1", "s20"]


def avg_value(data_dir, dates):
    """近幾個交易日的平均成交值（元）{(market, code): 均值}，沒成交的天以 0 計。"""
    tot = {}
    n = 0
    for d in dates:
        p = Path(data_dir) / d[:4] / (d.replace("-", "") + ".csv")
        if not p.exists():
            continue
        n += 1
        for r in _read(p):
            v = _f(r.get("value"))
            if v:
                k = (r["market"], r["code"])
                tot[k] = tot.get(k, 0.0) + v
    return {k: v / n for k, v in tot.items()} if n else {}


def build(data_dir):
    data_dir = Path(data_dir)
    mdir = data_dir / "margin"
    days = load_days(data_dir, max(COST_WARMUP, MARKET_N, SERIES_N))
    if not days:
        return None
    tracker = CostTracker()
    last_close = {}
    series = {}       # key -> list of [date, close, fin, sht, ratio, ul, ul_lim]（ul 不限用途擔保張數、ul_lim 限額張數）
    pledge = {}       # date -> 不限用途借貸擔保品
    for i, (d, rows, closes) in enumerate(days):
        tracker.step(rows, closes, last_close)
        last_close.update(closes)
        if i >= len(days) - SERIES_N:
            pledge[d] = pl = pledge_for(data_dir, d)
            for k, r in rows.items():
                c = closes.get(k)
                a = tracker.avg.get(k)
                ratio = round(c / (a * FIN_RATIO) * 100) if c and a and (_f(r.get("fin_bal")) or 0) > 0 else None
                series.setdefault(k, []).append([d, c, _f(r.get("fin_bal")), _f(r.get("sht_bal")), ratio,
                                                 _f(pl.get(k, {}).get("ul_bal")), _f(pl.get(k, {}).get("ul_limit"))])

    def at(n):
        return days[-1 - n] if len(days) > n else None

    d0, rows0, closes0 = days[-1]
    ref = {n: at(n) for n in (1, 5, 20)}
    val5 = avg_value(data_dir, [x[0] for x in days[-5:]])
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
        sht_at = lambda n: _f(ref[n][1][k].get("sht_bal")) if ref[n] and k in ref[n][1] else None  # noqa: E731
        sht1, sht5, sht20 = sht_at(1), sht_at(5), sht_at(20)
        def ul_at(n):
            x = days[-1 - n] if len(days) > n else None
            return _f(pledge.get(x[0], {}).get(k, {}).get("ul_bal")) if x else None

        p0 = pledge.get(d0, {}).get(k, {})
        u0, u1, u5, u20 = ul_at(0), ul_at(1), ul_at(5), ul_at(20)
        ulim = _f(p0.get("ul_limit"))
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
            u0,
            None if u0 is None or u1 is None else int(u0 - u1),
            None if u0 is None or u5 is None else int(u0 - u5), pct(u0, u5), pct(u0, u20),
            round(u0 * 1000 * c) if u0 and c else None,
            # 次一營業日限額（約股本 1 成）：不限用途擔保張數 ÷ 限額
            round(u0 / ulim * 100, 2) if u0 is not None and ulim else None,
            _f(p0.get("sf_bal")),
            round(val5[k]) if val5.get(k) else None,
            # 近 20 日融資餘額（迷你走勢圖）
            [None if x[2] is None else int(x[2]) for x in series.get(k, [])[-20:]] if fin else None,
            None if sht is None or sht1 is None else int(sht - sht1),
            None if sht is None or sht20 is None else int(sht - sht20),
        ])
    stocks.sort(key=lambda x: -(x[13] or 0))

    summary = _read(mdir / "summary.csv") if (mdir / "summary.csv").exists() else []
    index = _read(mdir / "index.csv") if (mdir / "index.csv").exists() else []
    market = market_series(data_dir, days[-MARKET_N:], summary, index)
    return {
        "delev": deleverage(data_dir, days[-MARKET_N:], market),
        "level": level_series(data_dir, days),
        "market": {"date": d0, "cols": MARKET_COLS, "rows": market},
        "stocks": {"date": d0, "cols": STOCK_COLS, "rows": stocks},
        "series": {f"{k[1]}": v for k, v in series.items()},
    }


# ───────────── 融資水位歷史（level.json） ─────────────
LEVEL_YEARS = 5          # 分位、平均 ±σ 用最近幾年
HEAT_SIGMA = 1.0         # 水位 > 平均 + 1σ 算過熱
HEAT_GAP = 20            # 兩段過熱相隔不到 20 個交易日視為同一段
HEAT_MIN = 3            # 過熱至少連續幾個交易日才算一段（排除單日雜訊）
FWD_N = 60               # 過熱後看幾個交易日的指數最大回檔
DD_BIG = -10.0           # 「大回檔」門檻（%）


def _stat(vals):
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return None
    mean = sum(v) / len(v)
    sd = (sum((x - mean) ** 2 for x in v) / (len(v) - 1)) ** 0.5
    now = vals[-1]
    return {"now": now, "mean": round(mean, 4), "sd": round(sd, 4), "min": min(v), "max": max(v),
            "pct": None if now is None else round(sum(1 for x in v if x <= now) / len(v) * 100)}


def _fwd_dd(tx, i, n=FWD_N):
    """第 i 天起 n 個交易日內，指數從區間內高點到之後低點的最大跌幅（%）；資料不足回傳 None。"""
    if i + n >= len(tx) or tx[i] is None:
        return None
    pk, dd = tx[i], 0.0
    for v in tx[i:i + n + 1]:
        if v is None:
            continue
        pk = max(pk, v)
        dd = min(dd, (v / pk - 1) * 100)
    return round(dd, 1)


def level_series(data_dir, days):
    data_dir = Path(data_dir)
    mdir = data_dir / "margin"
    hist = {}
    if (mdir / "level.csv").exists():
        for r in _read(mdir / "level.csv"):
            hist[(r["date"], r["market"])] = r
    summ = {}
    if (mdir / "summary.csv").exists():
        for r in _read(mdir / "summary.csv"):
            summ.setdefault(r["date"], {})[r["market"]] = r
    for d, rows, closes in days:
        if (d, "TWSE") in hist and (d, "TPEx") in hist:
            continue
        for r in level_rows(d, rows, closes, summ.get(d, {})):
            hist[(d, r["market"])] = {k: str(v) for k, v in r.items()}
    idx = {}
    if (mdir / "index.csv").exists():
        idx = {r["date"]: _f(r["taiex"]) for r in _read(mdir / "index.csv")}
    dates = sorted({d for d, m in hist if (d, "TWSE") in hist and (d, "TPEx") in hist})
    if not dates:
        return None
    cut = f"{int(dates[-1][:4]) - LEVEL_YEARS}{dates[-1][4:]}"
    dates = [d for d in dates if d > cut]
    rows = []
    for d in dates:
        a, b = hist[(d, "TWSE")], hist[(d, "TPEx")]
        g = lambda r, k: _f(r.get(k)) or 0  # noqa: E731
        lv = lambda amt, cap: round(amt / cap * 100, 4) if cap else None  # noqa: E731
        fin = g(a, "fin_lots") + g(b, "fin_lots")
        lim = g(a, "use_lim") + g(b, "use_lim")
        rows.append([d,
                     lv(g(a, "fin_amount") - g(a, "x_amt"), g(a, "mcap") - g(a, "x_mcap")),
                     lv(g(b, "fin_amount"), g(b, "mcap")),
                     lv(g(a, "fin_amount"), g(a, "mcap")),
                     round((g(a, "use_bal") + g(b, "use_bal")) / lim * 100, 3) if lim else None,
                     round((g(a, "sht_lots") + g(b, "sht_lots")) / fin * 100, 3) if fin else None,
                     int(g(a, "fin_lots")), int(g(b, "fin_lots")),
                     round((g(a, "fin_amount") + g(b, "fin_amount")) / 1e8, 1),
                     idx.get(d)])
    cols = ["date", "twse_x", "tpex", "twse", "use", "ss", "twse_lots", "tpex_lots", "amt", "taiex"]
    col = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
    col["lots"] = [x + y for x, y in zip(col["twse_lots"], col["tpex_lots"])]
    tx = col["taiex"]
    fwd = [_fwd_dd(tx, i) for i in range(len(rows))]
    stats, heat = {}, {}
    for k in ("twse_x", "tpex", "twse", "use", "ss", "lots", "amt"):
        stats[k] = _stat(col[k])
    for k in ("twse_x", "tpex"):
        st = stats[k]
        if not st:
            continue
        th = st["mean"] + HEAT_SIGMA * st["sd"]
        on = [i for i, v in enumerate(col[k]) if v is not None and v > th]
        eps = []
        for i in on:
            if eps and i - eps[-1][1] <= HEAT_GAP:
                eps[-1][1] = i
            else:
                eps.append([i, i])
        eps = [e for e in eps if e[1] - e[0] + 1 >= HEAT_MIN]
        out = []
        for s0, e0 in eps:
            pk = max(range(s0, e0 + 1), key=lambda j: col[k][j] or 0)
            out.append({"start": dates[s0], "end": dates[e0], "peak_date": dates[pk], "peak": col[k][pk],
                        "taiex": tx[s0], "dd": fwd[s0], "days": e0 - s0 + 1})
        hot = [fwd[i] for i in on if fwd[i] is not None]
        base = [x for x in fwd if x is not None]
        share = lambda v: round(sum(1 for x in v if x <= DD_BIG) / len(v) * 100) if v else None  # noqa: E731
        heat[k] = {"th": round(th, 4), "episodes": out, "hot_big": share(hot), "base_big": share(base),
                   "hot_n": len(hot), "base_n": len(base)}
    return {"date": dates[-1], "first": dates[0], "cols": cols, "rows": rows, "stats": stats, "heat": heat,
            "rules": {"years": LEVEL_YEARS, "sigma": HEAT_SIGMA, "gap": HEAT_GAP, "min": HEAT_MIN, "fwd": FWD_N, "dd_big": DD_BIG}}


# ───────────── 去槓桿進度（殺乾淨了沒） ─────────────
# 2026-11-04 Leo：看槓桿有沒有殺乾淨。樣板是 2026/7 的洗盤：融資張數 7/3→7/30 減 10.3%、
# 7/28–29 連兩天單日減 2%～3.7%、估計維持率低點 154%，隔天指數 +8%。00631L 融資在下跌中增加、反彈後才降。
LEV_ETFS = [("00631L", "lev"), ("00675L", "lev"), ("00685L", "lev"), ("00663L", "lev"), ("00632R", "inv")]
DELEV = {
    "peak_n": 60,        # 張數高點：近 60 個交易日
    "dd": -8.0,          # 張數離高點 ≤ -8%
    "drop2": -2.0,       # 單日張數減 ≥ 2%，近 5 日內連 2 天
    "ratio": 150.0,      # 大盤估計維持率 ≤ 150%
}
DELEV_N = 120            # 走勢保留天數


def _is_active(code):
    return code.startswith("00") and code.endswith("A") and code[2:-1].isdigit()


def etf_units(data_dir, codes):
    """data/etf/aum：{code: {date: (units, flow)}}，同一資料日以較晚的檔案為準。
    單位數是該交易日盤前揭露的已發行單位數（反映前一交易日的申購贖回）。"""
    out = {c: {} for c in codes}
    for f in sorted(Path(data_dir).glob("etf/aum/[0-9]*.csv")):
        for r in _read(f):
            c = r.get("etf")
            if c in out and _f(r.get("units")) is not None:
                out[c][r["date"]] = (_f(r["units"]), _f(r.get("flow")) or 0.0)
    return out


def _chg_n(vals, n):
    """vals 最後一筆對 n 筆前的 %（缺值往前找最近一筆有值的）"""
    v = [x for x in vals if x is not None]
    return pct(v[-1], v[-1 - n]) if len(v) > n else None


def deleverage(data_dir, days, market):
    """days：load_days 的結果；market：market_series 的列（MARKET_COLS）。"""
    if not days or not market:
        return None
    C = {c: i for i, c in enumerate(MARKET_COLS)}
    mk = [r for r in market if r[C["twse_lots"]] is not None]
    if not mk:
        return None
    lots = [r[C["twse_lots"]] + (r[C["tpex_lots"]] or 0) for r in mk]
    ratio = [r[C["all_ratio"]] for r in mk]
    dates = [r[0] for r in mk]
    taiex = [r[C["taiex"]] for r in mk]
    d1 = [None] + [pct(b, a) for a, b in zip(lots, lots[1:])]

    def dd_at(i):
        lo = max(0, i - DELEV["peak_n"] + 1)
        pk = max(range(lo, i + 1), key=lambda j: lots[j])
        return pk, pct(lots[i], lots[pk])

    i = len(lots) - 1
    pk, dd = dd_at(i)
    ix_pk = max(range(max(0, i - DELEV["peak_n"] + 1), i + 1), key=lambda j: taiex[j] or 0)
    last5 = d1[-5:]
    two = any(a is not None and b is not None and a <= DELEV["drop2"] and b <= DELEV["drop2"] for a, b in zip(last5, last5[1:]))

    # 上一次洗盤：20 個交易日以前維持率最低的一天
    ref = None
    old = [j for j in range(len(ratio) - 20) if ratio[j] is not None]
    if old:
        j = min(old, key=lambda j: ratio[j])
        pj, ddj = dd_at(j)
        ref = {"date": dates[j], "ratio": ratio[j], "dd": ddj, "peak_date": dates[pj],
               "max_drop": min((x for x in d1[pj + 1:j + 1] if x is not None), default=None),
               "next5": pct(taiex[min(j + 5, i)], taiex[j]) if taiex[j] else None}

    # ETF：融資張數（含收盤）＋受益單位
    want = [c for c, _ in LEV_ETFS]
    units = etf_units(data_dir, want)
    tail = days[-DELEV_N:]
    etfs = []
    for code, grp in LEV_ETFS:
        rows, name = [], ""
        for d, rs, closes in tail:
            r = next((x for k, x in rs.items() if k[1] == code), None)
            if r:
                name = name or r.get("name", "")
            u = units[code].get(d)
            rows.append([d, _f(r.get("fin_bal")) if r else None, closes.get(("TWSE", code)),
                         u[0] if u else None, round(u[1] / 1e8, 2) if u else None])
        if not any(x[1] for x in rows):
            continue
        fin = [x[1] for x in rows]
        un = [x[3] for x in rows]
        flow5 = [x[4] for x in rows[-5:] if x[4] is not None]
        flow20 = [x[4] for x in rows[-20:] if x[4] is not None]
        etfs.append({"code": code, "name": name, "group": grp, "fin": fin[-1], "f1": _chg_n(fin, 1),
                     "f5": _chg_n(fin, 5), "f20": _chg_n(fin, 20),
                     "fin_peak": max(x for x in fin if x is not None),
                     "units": next((x for x in reversed(un) if x is not None), None),
                     "u5": _chg_n(un, 5), "u20": _chg_n(un, 20),
                     "flow5": round(sum(flow5), 1) if flow5 else None, "flow20": round(sum(flow20), 1) if flow20 else None,
                     "close": rows[-1][2], "r5": _chg_n([x[2] for x in rows], 5),
                     "rows": rows})
    act = []
    for d, rs, closes in tail:
        n = v = 0.0
        for k, r in rs.items():
            if _is_active(k[1]):
                b = _f(r.get("fin_bal")) or 0
                n += b
                v += b * 1000 * (closes.get(k) or 0)
        act.append([d, int(n), round(v / 1e8, 1)])
    an = [x[1] for x in act]
    active = {"fin": an[-1], "val": act[-1][2], "f1": _chg_n(an, 1), "f5": _chg_n(an, 5), "f20": _chg_n(an, 20),
              "peak": max(an), "rows": act}

    e631 = next((e for e in etfs if e["code"] == "00631L"), None)
    checks = [
        {"key": "dd", "k": "張數離高點 ≤ -8%", "hit": dd is not None and dd <= DELEV["dd"],
         "t": f"融資張數離近 {DELEV['peak_n']} 日高點 {dd:+.1f}%" if dd is not None else "融資張數離高點 –",
         "d": f"高點 {dates[pk]}；{DELEV['dd']:.0f}% 以下才算真的減肥（7 月洗盤減了 10%）"},
        {"key": "drop2", "k": "連 2 天單日減 ≥ 2%", "hit": two,
         "t": "近 5 日單日張數：" + "、".join("–" if x is None else f"{x:+.1f}%" for x in last5[-3:]),
         "d": f"連 2 天單日減 {-DELEV['drop2']:.0f}% 以上＝斷頭潮（7 月是 -2.0%、-3.7%）"},
        {"key": "ratio", "k": "大盤維持率 ≤ 150%", "hit": ratio[-1] is not None and ratio[-1] <= DELEV["ratio"],
         "t": f"大盤估計維持率 {ratio[-1]:.1f}%" if ratio[-1] is not None else "大盤估計維持率 –",
         "d": f"{DELEV['ratio']:.0f}% 附近開始大量追繳（7 月低點 154%）"},
        {"key": "lev", "k": "00631L 融資＋單位同減", "hit": bool(e631 and (e631["f5"] or 0) < 0 and (e631["u5"] or 0) < 0),
         "t": (f"00631L 融資 5 日 {e631['f5']:+.1f}%、單位數 5 日 {e631['u5']:+.1f}%" if e631 and e631["f5"] is not None and e631["u5"] is not None else "00631L –"),
         "d": "融資和受益單位同時下降＝槓桿 ETF 散戶退場"},
        {"key": "active", "k": "主動式 ETF 融資轉減", "hit": active["f5"] is not None and active["f5"] < 0,
         "t": f"主動式 ETF 融資 5 日 {active['f5']:+.1f}%" if active["f5"] is not None else "主動式 ETF 融資 –",
         "d": "主動式 ETF 的融資開始減少"},
    ]
    hits = sum(c["hit"] for c in checks)
    level, label = (3, "接近殺乾淨") if hits >= 4 else (2, "去槓桿進行中") if hits >= 2 else (1, "還沒殺乾淨")
    return {"date": dates[-1], "level": level, "label": label, "hits": hits, "checks": checks, "rules": DELEV,
            "market": {"lots": lots[-1], "peak": lots[pk], "peak_date": dates[pk], "dd": dd, "d1": d1[-1],
                       "ratio": ratio[-1], "taiex_dd": pct(taiex[-1], taiex[ix_pk]), "taiex_peak_date": dates[ix_pk],
                       "rows": [[dates[k], lots[k], ratio[k], taiex[k]] for k in range(max(0, i - DELEV_N + 1), i + 1)]},
            "ref": ref, "etfs": etfs, "active": active}


def deleverage_from_disk(data_dir):
    """給盤後摘要用：自己讀資料算一次。"""
    data_dir = Path(data_dir)
    days = load_days(data_dir, MARKET_N)
    mdir = data_dir / "margin"
    summary = _read(mdir / "summary.csv") if (mdir / "summary.csv").exists() else []
    index = _read(mdir / "index.csv") if (mdir / "index.csv").exists() else []
    return deleverage(data_dir, days, market_series(data_dir, days, summary, index))


def write_margin(data_dir, out_dir):
    payload = build(data_dir)
    if payload is None:
        return None
    out_dir = Path(out_dir)
    (out_dir / "s").mkdir(parents=True, exist_ok=True)
    dump = lambda p, o: p.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")  # noqa: E731
    dump(out_dir / "market.json", payload["market"])
    dump(out_dir / "stocks.json", payload["stocks"])
    if payload.get("delev"):
        dump(out_dir / "delev.json", payload["delev"])
    if payload.get("level"):
        dump(out_dir / "level.json", payload["level"])
    for code, rows in payload["series"].items():
        dump(out_dir / "s" / f"{code}.json", {"cols": ["date", "close", "fin", "sht", "ratio", "ul", "ul_lim"], "rows": rows})
    return payload
