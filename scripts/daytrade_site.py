"""當沖與隔日沖頁（site/daytrade.html）→ data/daytrade.json

當沖（data/chips 的 dt_vol／dt_buy／dt_sell，證交所 TWTB4U、櫃買中心當沖統計）
  只算上市櫃普通股（代號 1～9 開頭 4 碼），ETF、特別股不算。
  當沖客損益 ＝ 當沖賣出金額 − 當沖買進金額 − 證交稅（賣出 0.15%）− 手續費（0.1425% 三折，買賣兩邊）
  交易所資料不分先買後賣、先賣後買；也不含留倉。數字 T+2 才定案，最近兩天可能小幅修正。
  當沖率 ＝ 當沖股數 ÷ 當日成交股數；當沖占成交金額 ＝ 當沖買進金額 ÷ 普通股成交金額。
  買在全天位置 ＝ (當沖買均 − 最低) ÷ (最高 − 最低)，0％＝買在最低、100％＝買在最高。

隔日沖（data/broker，富邦分點前 15 大買賣超；分點分類來自 broker_score.py 的 data/broker/score/branches.csv）
  今天買：分類為「隔日沖」的分點今天買超哪些股票（明天開盤可能倒貨）。
  昨天買→今天賣：昨天買超的股票今天賣掉幾成、以兩天均價（成交金額 ÷ 成交股數）估算的扣稅損益。
  分點資料只有每檔前 15 大、成交金額 ≥ 3000 萬的股票；今天沒進前 15 大的分點看不到，標「未上榜」。
"""
import csv
import json
import re
from pathlib import Path

STOCK = re.compile(r"^[1-9]\d{3}$")
TAX, FEE = 0.0015, 0.001425 * 0.3
MIN_AMT = 1e7          # 個股表：當沖買進金額 ≥ 1000 萬
HIST = 250             # 大盤走勢天數


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read(p):
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _files(d, pat):
    return sorted(Path(d).glob(pat), key=lambda p: p.name)


def _prices(data_dir, ymd):
    p = Path(data_dir) / ymd[:4] / f"{ymd}.csv"
    return {r["code"]: r for r in _read(p)} if p.exists() else {}


def _pnl(buy, sell):
    return sell - buy - sell * TAX - (buy + sell) * FEE


def market(data_dir):
    rows = []
    files = [f for f in _files(Path(data_dir) / "chips", "[0-9]*/[0-9]*.csv") if len(f.stem) == 8][-(HIST + 20):]
    for f in files:
        px = _prices(data_dir, f.stem)
        if not px:
            continue
        val = sum(_f(r["value"]) or 0 for c, r in px.items() if STOCK.match(c))
        b = s = 0.0
        for r in _read(f):
            if not STOCK.match(r["code"]):
                continue
            bb, ss = _f(r["dt_buy"]), _f(r["dt_sell"])
            if bb and ss:
                b += bb
                s += ss
        if not b or not val:
            continue
        rows.append([f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}", round(b / val * 100, 2), round(_pnl(b, s) / 1e8, 2),
                     round((s - b) / 1e8, 2), round(b / 1e8, 1)])
    return rows[-HIST:]


def stocks(data_dir, chips_file, hist_files):
    ymd = chips_file.stem
    px = _prices(data_dir, ymd)
    # 近 20 日平均當沖率
    avg = {}
    for f in hist_files:
        p2 = _prices(data_dir, f.stem)
        for r in _read(f):
            v, vol = _f(r["dt_vol"]), _f((p2.get(r["code"]) or {}).get("volume"))
            if v and vol:
                avg.setdefault(r["code"], []).append(v / vol * 100)
    out = []
    for r in _read(chips_file):
        c = r["code"]
        if not STOCK.match(c) or c not in px:
            continue
        p = px[c]
        vol, b, s, b_amt, s_amt = _f(p["volume"]), _f(r["dt_vol"]), _f(r["dt_vol"]), _f(r["dt_buy"]), _f(r["dt_sell"])
        if not (vol and b and b_amt and s_amt) or b_amt < MIN_AMT:
            continue
        hi, lo, cl, ch = _f(p["high"]), _f(p["low"]), _f(p["close"]), _f(p["change"])
        bavg, savg = b_amt / b, s_amt / s
        rate = b / vol * 100
        a20 = avg.get(c, [])
        a20 = sum(a20) / len(a20) if a20 else None
        pnl = _pnl(b_amt, s_amt)
        out.append([c, p["name"], p["market"], cl, round(ch / (cl - ch) * 100, 2) if cl and ch is not None and cl - ch else None,
                    round(b_amt / 1e8, 2), round(rate, 1), round(rate / a20, 2) if a20 else None,
                    round(bavg, 2), round(savg, 2),
                    round((bavg - lo) / (hi - lo) * 100) if hi and lo and hi > lo else None,
                    round((cl / bavg - 1) * 100, 2), round(pnl / 1e4), round(pnl / b_amt * 100, 2),
                    round((hi / lo - 1) * 100, 1) if hi and lo else None])
    out.sort(key=lambda x: -x[5])
    return out


def _flip_branches(data_dir):
    p = Path(data_dir) / "broker" / "score" / "branches.csv"
    if not p.exists():
        return {}
    return {r["bid"]: r for r in _read(p) if r["class"] == "隔日沖"}


def flip(data_dir):
    fb = _flip_branches(data_dir)
    files = [f for f in _files(Path(data_dir) / "broker", "[0-9]*/[0-9]*.csv") if len(f.stem) == 8]
    if not fb or len(files) < 2:
        return None
    d1, d0 = files[-1], files[-2]
    px1, px0 = _prices(data_dir, d1.stem), _prices(data_dir, d0.stem)
    vw = lambda px, c: (_f(px[c]["value"]) / _f(px[c]["volume"])) if c in px and _f(px[c]["volume"]) else None  # noqa: E731
    cov1 = {r["code"] for r in _read(d1.with_name(d1.stem + "_total.csv"))} if d1.with_name(d1.stem + "_total.csv").exists() else None
    r1, r0 = _read(d1), _read(d0)
    net1 = {}
    for r in r1:
        net1[(r["bid"], r["code"])] = _f(r["net"]) or 0
    # 今天買
    today = {}
    for r in r1:
        if r["bid"] in fb and STOCK.match(r["code"]) and (_f(r["net"]) or 0) > 0:
            today.setdefault(r["code"], []).append((r["broker"], _f(r["net"])))
    tb = []
    for c, lst in today.items():
        lots = sum(x for _, x in lst)
        p = px1.get(c, {})
        v = vw(px1, c)
        vol = _f(p.get("volume"))
        cl, ch = _f(p.get("close")), _f(p.get("change"))
        tb.append([c, p.get("name", ""), cl, round(ch / (cl - ch) * 100, 2) if cl and ch is not None and cl - ch else None,
                   int(lots), round(lots * 1000 * v / 1e8, 2) if v else None, round(lots * 1000 / vol * 100, 1) if vol else None,
                   [[n, int(x)] for n, x in sorted(lst, key=lambda t: -t[1])]])
    tb.sort(key=lambda x: -(x[5] or 0))
    # 昨天買 → 今天
    yb = []
    for r in r0:
        if r["bid"] not in fb or not STOCK.match(r["code"]):
            continue
        bl = _f(r["net"]) or 0
        if bl <= 0:
            continue
        c = r["code"]
        k = (r["bid"], c)
        v0, v1 = vw(px0, c), vw(px1, c)
        p1 = px1.get(c, {})
        cl, ch = _f(p1.get("close")), _f(p1.get("change"))
        if k in net1:
            n1 = net1[k]
            sold = max(0.0, -n1)
            ratio = round(sold / bl * 100)
            pnl = round(_pnl(sold * 1000 * v0, sold * 1000 * v1) / 1e4) if v0 and v1 and sold else 0
            st = "ok"
        else:
            n1, ratio, pnl, st = None, None, None, ("na" if cov1 is not None and c not in cov1 else "out")
        yb.append([c, p1.get("name") or r.get("code"), r["broker"], int(bl), round(bl * 1000 * v0 / 1e8, 2) if v0 else None,
                   None if n1 is None else int(n1), ratio, pnl, round(ch / (cl - ch) * 100, 2) if cl and ch is not None and cl - ch else None, st])
    yb.sort(key=lambda x: -(x[4] or 0))
    br = sorted(([b["branch"], int(_f(b["flip_n"]) or 0), _f(b["flip_ratio"]), _f(b["buy_day_ret"])] for b in fb.values()), key=lambda x: -x[1])
    return {"d1": f"{d1.stem[:4]}-{d1.stem[4:6]}-{d1.stem[6:]}", "d0": f"{d0.stem[:4]}-{d0.stem[4:6]}-{d0.stem[6:]}",
            "today_cols": ["code", "name", "close", "ret", "lots", "amt", "pct", "brokers"], "today": tb,
            "yest_cols": ["code", "name", "broker", "buy", "amt", "net1", "ratio", "pnl", "ret", "st"], "yest": yb,
            "branches": br}


def build(data_dir):
    data_dir = Path(data_dir)
    files = [f for f in _files(data_dir / "chips", "[0-9]*/[0-9]*.csv") if len(f.stem) == 8]
    files = [f for f in files if any(_f(r["dt_buy"]) for r in _read(f)[:300])]
    if not files:
        return None
    m = market(data_dir)
    last = files[-1]
    st = stocks(data_dir, last, files[-21:-1])
    tot = sum(x[12] for x in st) if st else 0
    w = [r[1] for r in m]
    pr = round(sum(1 for x in w if x <= m[-1][1]) / len(w) * 100) if m else None
    return {"date": f"{last.stem[:4]}-{last.stem[4:6]}-{last.stem[6:]}", "p_ratio": pr,
            "m_cols": ["date", "ratio", "pnl", "gross", "amt"], "market": m,
            "s_cols": ["code", "name", "market", "close", "ret", "amt", "rate", "x20", "bavg", "savg", "pos", "cvb", "pnl", "pnlr", "amp"],
            "stocks": st, "stocks_pnl": tot, "flip": flip(data_dir)}


def write(data_dir, out_path):
    j = build(data_dir)
    if j is None:
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    j = build(Path(__file__).resolve().parent.parent / "data")
    print(j["date"], j["p_ratio"], j["market"][-3:], len(j["stocks"]), j["stocks"][:3])
    f = j["flip"]
    print(f["d0"], f["d1"], len(f["today"]), f["today"][:3])
    print(f["yest"][:5])
