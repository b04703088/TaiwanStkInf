"""籌碼脆弱分數（fragility.html）：六項籌碼結構訊號，每項 0～2 分加總，並回測高分股之後的表現。

輸出 data/fragility.json：
  date      最新一天
  items     六項的名稱、說明、門檻
  cols      rows 的欄位
  rows      最新一天每檔的分數與各項數值（只列成交金額 ≥ MIN_VALUE 的普通股）
  bt        回測：依總分分組的之後 5／20 日超額報酬（對同日全體平均）與下跌比例
  bt_item   每一項各自 ≥1 分時的回測

六項（v1，門檻是初版，見 ITEMS）：
  1 大戶賣散戶接  近 5 日漲 ≥ 5% 而（前 15 大買超 − 前 15 大賣超）÷ 成交量 為負。真正的「買賣家數差」要全部分點，
                 免費來源只有前 15 大（證交所／櫃買全部分點有驗證碼），先用集中度近似。
  2 融資過熱      融資 5 日增幅、融資使用率（融資餘額 ÷ 融資限額，限額＝股數 25%）、估計維持率。
  3 當沖比重高    近 5 日當沖量 ÷ 成交量。
  4 短線分點買超  前 15 大買超分點裡的短線分點（站上分點評分的隔日沖，或翻手率 ≥ FLIP）近 3 日買超 ÷ 成交量。
  5 借券／券資比  借券賣出餘額 5 日增加 ÷ 股數，或券資比。
  6 投信成本很近  投信近 20 日買超 ÷ 股數，且收盤在投信近 20 日買進均價 ±BAND 內。

分點資料從 2026-09-30 開始，第 1、4 項在這之前沒有分數（回測分兩段看）。
"""
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

STOCK = re.compile(r"^[1-9]\d{3}$")
MIN_VALUE = 3e7          # 成交金額門檻（元），跟分點爬蟲一致
FLIP = 30.0              # 翻手率 ≥ 此值算短線分點
BAND = 0.05              # 投信成本 ±5%
FIN_RATIO = 0.6
START = "2025-10-01"     # 三大法人／借券／當沖資料起點

ITEMS = [
    {"key": "conc", "k": "大戶賣散戶接", "unit": "%",
     "d": "近 5 日漲幅 ≥ 5% 時，近 5 日（前 15 大買超 − 前 15 大賣超）÷ 成交量 ≤ −3%（≤ −10% 得 2 分）：股價在漲、大分點卻在賣，籌碼散到小分點。",
     "t1": -3, "t2": -10},
    {"key": "fin", "k": "融資過熱", "unit": "",
     "d": "融資 5 日增 ≥ 15%（30% 得 2 分）、融資使用率 ≥ 25%（35% 得 2 分）、估計維持率 ≤ 145%（135% 得 2 分），取最高。",
     "t1": None, "t2": None},
    {"key": "dt", "k": "當沖比重高", "unit": "%",
     "d": "近 5 日當沖量 ÷ 成交量 ≥ 45%（55% 得 2 分）。", "t1": 45, "t2": 55},
    {"key": "short", "k": "短線分點買超", "unit": "%",
     "d": "近 3 日前 15 大買超裡，隔日沖或翻手率 ≥ 30% 的分點合計買超 ÷ 成交量 ≥ 5%（10% 得 2 分）。", "t1": 5, "t2": 10},
    {"key": "sbl", "k": "借券／券資比", "unit": "",
     "d": "借券賣出餘額 5 日增加 ≥ 股數 0.5%（1% 得 2 分），或券資比 ≥ 15%（30% 得 2 分），取最高。",
     "t1": None, "t2": None},
    {"key": "trust", "k": "投信成本很近", "unit": "%",
     "d": "投信近 20 日買超 ≥ 股數 0.5%（1.5% 得 2 分），且收盤在投信近 20 日買進均價 ±5% 內。", "t1": 0.5, "t2": 1.5},
]


def _f(v):
    try:
        x = float(str(v).replace(",", ""))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _iso(name):
    s = name[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _files(data_dir, sub, pattern="[0-9]" * 8 + ".csv"):
    base = Path(data_dir) / sub if sub else Path(data_dir)
    return {_iso(f.name): f for f in base.glob("[0-9][0-9][0-9][0-9]/" + pattern)}


def _pts(v, t1, t2, low=False):
    if v is None:
        return 0
    if low:
        return 2 if v <= t2 else 1 if v <= t1 else 0
    return 2 if v >= t2 else 1 if v >= t1 else 0


def short_branches(data_dir):
    p = Path(data_dir) / "broker" / "score" / "branches.csv"
    out = set()
    if p.exists():
        for r in _read(p):
            fr = _f(r.get("flip_ratio"))
            if r.get("class") == "隔日沖" or (fr is not None and fr >= FLIP and (_f(r.get("n_buy")) or 0) >= 20):
                out.add(r["bid"])
    return out


class Win:
    """每檔股票一個固定長度的序列視窗。"""

    def __init__(self, n):
        self.n = n
        self.d = defaultdict(list)

    def push(self, code, v):
        a = self.d[code]
        a.append(v)
        if len(a) > self.n:
            del a[0]

    def get(self, code):
        return self.d.get(code, [])


def build(data_dir):
    data_dir = Path(data_dir)
    px_f = _files(data_dir, "")
    ch_f = _files(data_dir, "chips")
    mg_f = _files(data_dir, "margin")
    bk_f = {_iso(f.name): f for f in (data_dir / "broker").glob("[0-9][0-9][0-9][0-9]/" + "[0-9]" * 8 + ".csv")}
    shorts = short_branches(data_dir)
    days = sorted(d for d in px_f if d >= min(mg_f) if mg_f)

    vol5, conc5, dt5, short3 = Win(5), Win(5), Win(5), Win(3)
    fin6, sbl6, cl5 = Win(6), Win(6), Win(6)
    tr20 = Win(20)  # (t_net 股, vwap)
    fin_avg, fin_prev = {}, {}
    panel = {}  # date -> {code: (score, vals, pts)}
    closes = {}  # date -> {code: close}
    names, markets, values = {}, {}, {}

    for d in days:
        px = {}
        for r in _read(px_f[d]):
            c = r["code"].strip()
            if not STOCK.match(c):
                continue
            cl, vol, val = _f(r.get("close")), _f(r.get("volume")), _f(r.get("value"))
            if cl is None or not vol:
                continue
            px[c] = (cl, vol, val or 0)
            names[c] = r["name"].strip()
            markets[c] = "上市" if r["market"] == "TWSE" else "上櫃"
        closes[d] = {c: v[0] for c, v in px.items()}

        mg = {}
        if d in mg_f:
            for r in _read(mg_f[d]):
                c = r["code"].strip()
                if STOCK.match(c):
                    mg[c] = r
        # 融資平均成本（同 margin_site.CostTracker）
        for c, r in mg.items():
            if c not in px:
                continue
            p = px[c][1] and px[c][2] / px[c][1] or px[c][0]
            bal = _f(r.get("fin_bal")) or 0
            prev, avg = fin_prev.get(c), fin_avg.get(c)
            if prev is None or avg is None or prev <= 0:
                avg = p
            else:
                buy = _f(r.get("fin_buy")) or 0
                out = (_f(r.get("fin_sell")) or 0) + (_f(r.get("fin_cash")) or 0)
                kept = max(prev - out, 0)
                if kept + buy > 0:
                    avg = (kept * avg + buy * p) / (kept + buy)
            fin_avg[c], fin_prev[c] = avg, bal
            fin6.push(c, bal)
        if d < START:
            continue

        ch = {}
        if d in ch_f:
            for r in _read(ch_f[d]):
                c = r["code"].strip()
                if STOCK.match(c):
                    ch[c] = r
        have_bk = d in bk_f
        tot = {}
        sh = defaultdict(float)
        if have_bk:
            tf = bk_f[d].with_name(bk_f[d].stem + "_total.csv")
            if tf.exists():
                for r in _read(tf):
                    b, s = _f(r.get("buy_total")), _f(r.get("sell_total"))
                    if b is not None and s is not None:
                        tot[r["code"]] = b - s
            for r in _read(bk_f[d]):
                if r["side"] == "B" and r["bid"] in shorts:
                    sh[r["code"]] += max(_f(r.get("net")) or 0, 0)

        day = {}
        for c, (cl, vol, val) in px.items():
            lots = vol / 1000
            cl5.push(c, cl)
            vol5.push(c, lots)
            r = ch.get(c, {})
            dtv = _f(r.get("dt_vol"))
            dt5.push(c, None if dtv is None else dtv / 1000)
            sbl6.push(c, _f(r.get("sbl_bal")))
            tn = _f(r.get("t_net"))
            tr20.push(c, ((tn or 0), (val / vol) if vol else cl))
            if have_bk:
                conc5.push(c, tot.get(c))
                short3.push(c, sh.get(c, 0.0) if c in tot else None)
            if val < MIN_VALUE:
                continue
            m = mg.get(c, {})
            limit = _f(m.get("fin_limit"))
            shares = limit * 4 if limit else None  # 張
            v5 = sum(vol5.get(c))
            vals, pts = {}, {}
            c5 = cl5.get(c)
            chg5 = (cl / c5[0] - 1) * 100 if c5 and len(c5) == 6 and c5[0] else None
            vals["chg5"] = None if chg5 is None else round(chg5, 1)

            # 1 集中度
            cs = [x for x in conc5.get(c)[-5:] if x is not None] if have_bk else []
            if len(cs) >= 3:
                vv = sum(vol5.get(c)[-len(cs):])
                vals["conc"] = round(sum(cs) / vv * 100, 1) if vv else None
            pts["conc"] = _pts(vals.get("conc"), -3, -10, low=True) if (chg5 or 0) >= 5 else 0

            # 2 融資
            fb = fin6.get(c)
            p2 = 0
            if len(fb) == 6 and fb[0] and fb[0] >= 200:
                g = (fb[-1] / fb[0] - 1) * 100
                vals["fin5"] = round(g, 1)
                p2 = max(p2, _pts(g, 15, 30))
            if limit and fb:
                use = fb[-1] / limit * 100
                vals["finuse"] = round(use, 1)
                p2 = max(p2, _pts(use, 25, 35))
            if fb and fb[-1] >= 200 and fin_avg.get(c):
                mr = cl / (fin_avg[c] * FIN_RATIO) * 100
                vals["maint"] = round(mr)
                p2 = max(p2, _pts(mr, 145, 135, low=True))
            pts["fin"] = p2

            # 3 當沖
            dts = dt5.get(c)
            if dts and all(x is not None for x in dts) and v5:
                vals["dt"] = round(sum(dts) / v5 * 100, 1)
            pts["dt"] = _pts(vals.get("dt"), 45, 55)

            # 4 短線分點
            s3 = [x for x in short3.get(c) if x is not None] if have_bk else []
            if s3:
                vv = sum(vol5.get(c)[-len(s3):])
                vals["short"] = round(sum(s3) / vv * 100, 1) if vv else None
            pts["short"] = _pts(vals.get("short"), 5, 10)

            # 5 借券／券資比
            sb = sbl6.get(c)
            p5 = 0
            if shares and len(sb) == 6 and sb[0] is not None and sb[-1] is not None:
                inc = (sb[-1] - sb[0]) / 1000 / shares * 100
                vals["sbl"] = round(inc, 2)
                p5 = max(p5, _pts(inc, 0.5, 1.0))
            fbal, sbal = _f(m.get("fin_bal")), _f(m.get("sht_bal"))
            if fbal and fbal >= 500 and sbal is not None:
                sr = sbal / fbal * 100
                vals["ssr"] = round(sr, 1)
                p5 = max(p5, _pts(sr, 15, 30))
            pts["sbl"] = p5

            # 6 投信
            tw = tr20.get(c)
            p6 = 0
            if shares and len(tw) >= 10:
                net = sum(x[0] for x in tw) / 1000
                buys = [(x[0], x[1]) for x in tw if x[0] > 0]
                bq = sum(q for q, _ in buys)
                if net > 0 and bq:
                    cost = sum(q * p for q, p in buys) / bq
                    vals["trust"] = round(net / shares * 100, 2)
                    vals["tcost"] = round(cl / cost * 100 - 100, 1)
                    if abs(cl / cost - 1) <= BAND:
                        p6 = _pts(vals["trust"], 0.5, 1.5)
            pts["trust"] = p6

            score = sum(pts.values())
            day[c] = (score, vals, pts, have_bk)
        panel[d] = day
    return panel, closes, names, markets


def backtest(panel, closes, horizons=(1, 5, 20)):
    """之後 h 日報酬 − 同日全體（成交金額 ≥ MIN_VALUE 的普通股）中位數，單位 %。
    用中位數當基準：個股報酬右偏，用平均數當基準時大部分股票都「輸大盤」。"""
    dates = sorted(panel)
    all_days = sorted(closes)
    pos = {d: i for i, d in enumerate(all_days)}

    def fwd(d, h):
        i = pos[d]
        if i + h >= len(all_days):
            return None
        a, b = closes[d], closes[all_days[i + h]]
        r = {c: b[c] / a[c] - 1 for c in panel[d] if c in b and a.get(c)}
        if not r:
            return None
        xs = sorted(r.values())
        med = xs[len(xs) // 2]
        return {c: (v - med) * 100 for c, v in r.items()}

    keys = [it["key"] for it in ITEMS]
    buckets = defaultdict(lambda: defaultdict(list))
    items = defaultdict(lambda: defaultdict(list))
    for d in dates:
        f = {h: fwd(d, h) for h in horizons}
        for c, (score, vals, pts, bk) in panel[d].items():
            b = "0" if score == 0 else "1-2" if score <= 2 else "3-4" if score <= 4 else "5+"
            for h in horizons:
                if f[h] is None or c not in f[h]:
                    continue
                ex = f[h][c]
                buckets[("all", b)][h].append(ex)
                if bk:
                    buckets[("full", b)][h].append(ex)
                for k in keys:
                    if pts[k] >= 1:
                        items[k][h].append(ex)

    def stat(xs):
        if len(xs) < 20:
            return None
        n = len(xs)
        srt = sorted(xs)
        return {"n": n, "mean": round(sum(xs) / n, 2), "med": round(srt[n // 2], 2),
                "neg": round(sum(1 for x in xs if x < 0) / n * 100, 1)}

    bt = [dict(era=era, bucket=b, **{f"h{h}": stat(buckets[(era, b)][h]) for h in horizons})
          for era in ("all", "full") for b in ("0", "1-2", "3-4", "5+")]
    bt_item = [dict(key=k, **{f"h{h}": stat(items[k][h]) for h in horizons}) for k in keys]
    return bt, bt_item, ([dates[0], dates[-1]] if dates else [])


COLS = ["code", "name", "market", "score", "close", "chg5",
        "conc", "fin5", "finuse", "maint", "dt", "short", "sbl", "ssr", "trust", "tcost",
        "p_conc", "p_fin", "p_dt", "p_short", "p_sbl", "p_trust"]


def write_fragility(data_dir, out_path):
    panel, closes, names, markets = build(data_dir)
    if not panel:
        return None
    dates = sorted(panel)
    last = dates[-1]
    rows = []
    for c, (score, vals, pts, _) in sorted(panel[last].items(), key=lambda kv: (-kv[1][0], kv[0])):
        cl = closes[last][c]
        rows.append([c, names.get(c), markets.get(c), score, cl, vals.get("chg5")] +
                    [vals.get(k) for k in COLS[6:16]] + [pts[k] for k in ("conc", "fin", "dt", "short", "sbl", "trust")])
    bt, bt_item, span = backtest(panel, closes)
    out = {"date": last, "items": ITEMS, "cols": COLS, "rows": rows, "bt": bt, "bt_item": bt_item,
           "bt_span": span, "bk_start": next((d for d in dates if panel[d] and next(iter(panel[d].values()))[3]), None)}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[1]
    o = write_fragility(root / "data", Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fragility.json"))
    print(o["date"], len(o["rows"]), o["bk_start"], o["bt_span"])
    for r in o["bt"]:
        print(r["era"], r["bucket"], r["h1"], r["h5"], r["h20"])
    for r in o["bt_item"]:
        print(r["key"], r["h1"], r["h5"], r["h20"])
