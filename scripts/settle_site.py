"""結算日股期套利部位 → settle.html 用的 JSON。

想找的是：月結算日（每月第三個週三）股期套利的現貨部位要平掉，尾盤（股期結算價＝收盤前 60 分鐘均價）被賣壓或買盤影響的個股。

  空方（正價差套利：買現貨＋空期貨 → 結算日賣現貨）
    十大特法空單 ÷ 近 5 日成交量；扣掉多單的淨空 ÷ 近 5 日量；這個結算週期的空單增減
  多方（逆價差套利：借券／融券賣現貨＋買期貨 → 結算日買回現貨）
    十大特法多單 ÷ 近 5 日成交量；淨多 ÷ 近 5 日量；多單增減
  自營商（套利多半是自營商在做）
    從上次結算日隔天累積到今天的自營商（自行＋避險）買賣超 ÷ 近 5 日量

資料
  data/futures/stk/YYYY.csv   近月大額交易人（特定法人前十大多空口數、全市場未沖銷），見 fetch_futures.py
  data/futures/stk_list.csv   股期代號 → 證券代號、每口股數（一般 2,000、小型 100、ETF 依契約）
  data/YYYY/YYYYMMDD.csv      收盤、成交量
  data/chips/YYYY/*.csv       自營商買賣超 d_net、當沖量 dt_vol（近 5 日量扣當沖）

  data/futures/stk_px/YYYY.csv 股期近月收盤 → 價差%＝（期貨收盤 − 現貨收盤）÷ 現貨收盤；一般股期優先，沒有才用小型
    期貨收盤在 13:45、現貨 13:30，時間差 15 分鐘，盤後大漲大跌的日子價差會失真；除權息前的逆價差多半是股利，不一定是套利

  套利判定（這個結算週期內逐日看）
    空方：自營商買超的日子是不是正價差（買現貨＋空期貨才有利可圖）→ d_buy_pos ÷ d_buy；特法空單增加的日子是不是正價差 → s_add_pos ÷ s_add
    多方：自營商賣超的日子是不是逆價差 → d_sell_neg ÷ d_sell；特法多單增加的日子是不是逆價差 → l_add_neg ÷ l_add

  data/settle.json
    {date, month, next_settle:{date,tdays}, last_settle, cycle_start, cycle_days, v5_days, cols, rows, dcols, detail:{code:[[...]]}}
    同一檔股票的一般、小型股期合併，口數全部換算成張（1,000 股）。
    調整型契約（除權息後的 CD1 之類）期交所已併在根碼口數裡，但每口股數不同，這裡一律用標準股數換算，會有小誤差。
"""
import csv
import json
from pathlib import Path

import futures_site

COLS = ["code", "name", "market", "etf", "close", "chg", "v5", "oi",
        "s10", "l10", "s_r", "ns_r", "l_r", "nl_r", "s_d", "l_d", "d_cum", "d_r",
        "basis", "pos_days", "neg_days", "d_buy_pos", "d_buy", "d_sell_neg", "d_sell", "s_add_pos", "s_add", "l_add_neg", "l_add"]
# 每檔每天的明細（點列展開）：日期、價差%、自營商買賣超（張）、特法空單增減、特法多單增減
DCOLS = ["date", "basis", "d_net", "s_chg", "l_chg"]


def _read(p):
    if not Path(p).exists():
        return []
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _day_file(data_dir, d, sub=""):
    ymd = d.replace("-", "")
    return Path(data_dir) / sub / ymd[:4] / f"{ymd}.csv"


def build(data_dir, holidays=()):
    data_dir = Path(data_dir)
    fut = data_dir / "futures"
    stk = []
    for p in sorted((fut / "stk").glob("*.csv"))[-2:]:
        stk += _read(p)
    lst = {r["product"]: r for r in _read(fut / "stk_list.csv")}
    fpx = {}
    for p in sorted((fut / "stk_px").glob("*.csv"))[-2:]:
        for r in _read(p):
            m = lst.get(r["product"])
            c = _f(r["close"]) or _f(r["settle"])  # 當天沒成交就用結算價
            if not m or not c:
                continue
            k = (r["date"], m["code"])
            mini = (_f(m["size"]) or 2000) < 1000 or (m["code"].startswith("00") and (_f(m["size"]) or 0) < 10000)
            if k not in fpx or not mini:
                fpx[k] = c
    if not stk or not lst:
        return None
    by_date = {}
    for r in stk:
        by_date.setdefault(r["date"], []).append(r)
    asof = max(by_date)
    month = by_date[asof][0]["month"]

    price_days = sorted(p.stem for y in sorted(data_dir.glob("20[0-9][0-9]"))[-2:] for p in y.glob("*.csv"))
    price_days = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in price_days]
    days = [d for d in price_days if d <= asof]
    settles, nxt = futures_site.settle_dates(days[-80:], holidays)
    past = [s for s in settles if s < asof] if asof not in settles else [s for s in settles if s <= asof]
    last_settle = past[-1] if past else None
    cycle = [d for d in days if last_settle is None or d > last_settle]
    if asof == last_settle:  # 今天就是結算日：週期從今天算起
        cycle = [asof]
    v5_days = days[-5:]

    def agg(d):
        out = {}
        for r in by_date.get(d, []):
            if r["month"] != month or r["product"] not in lst:
                continue
            m = lst[r["product"]]
            size = _f(m["size"]) or 2000
            o = out.setdefault(m["code"], {"name": m["name"], "s": 0.0, "l": 0.0, "oi": 0.0})
            o["s"] += (_f(r["top10_short"]) or 0) * size
            o["l"] += (_f(r["top10_long"]) or 0) * size
            o["oi"] += (_f(r["oi"]) or 0) * size
        return out

    now = agg(asof)
    # 結算日當天的大額交易人報表已換成新近月 → 用它當週期起點；沒有才用週期第一天
    pre = agg(last_settle) if last_settle in by_date and last_settle not in cycle else {}
    base_day = last_settle if pre else next((d for d in cycle if d in by_date), None)
    base = pre or (agg(base_day) if base_day and base_day != asof else {})

    vol, dt, dnet, px = {}, {}, {}, {}
    for d in v5_days:
        for r in _read(_day_file(data_dir, d)):
            vol[r["code"]] = vol.get(r["code"], 0) + (_f(r["volume"]) or 0)
            px[r["code"]] = r
        for r in _read(_day_file(data_dir, d, "chips")):
            dt[r["code"]] = dt.get(r["code"], 0) + (_f(r["dt_vol"]) or 0)
    dday, spot = {}, {}
    for d in cycle:
        for r in _read(_day_file(data_dir, d, "chips")):
            v = _f(r["d_net"]) or 0
            dnet[r["code"]] = dnet.get(r["code"], 0) + v
            dday[(d, r["code"])] = v
        for r in _read(_day_file(data_dir, d)):
            spot[(d, r["code"])] = _f(r["close"])
    pos_by_day = {d: agg(d) for d in cycle if d in by_date}

    def basis(d, code):
        f, s_ = fpx.get((d, code)), spot.get((d, code))
        return round((f - s_) / s_ * 100, 2) if f and s_ else None

    rows, detail = [], {}
    for code, o in now.items():
        v5 = vol.get(code, 0) - dt.get(code, 0)
        if v5 <= 0 or not o["oi"]:
            continue
        p = px.get(code, {})
        close, chg = _f(p.get("close")), _f(p.get("change"))
        prev = close - chg if close is not None and chg is not None else None
        b = base.get(code)
        dc = dnet.get(code)
        r4 = lambda x: round(x, 3)  # noqa: E731
        det, prev_o = [], pre.get(code)
        st = dict(pos_days=0, neg_days=0, d_buy_pos=0.0, d_buy=0.0, d_sell_neg=0.0, d_sell=0.0,
                  s_add_pos=0.0, s_add=0.0, l_add_neg=0.0, l_add=0.0)
        for d in cycle:
            bz, dn = basis(d, code), dday.get((d, code))
            cur = pos_by_day.get(d, {}).get(code)
            sc = (cur["s"] - prev_o["s"]) if cur and prev_o else None
            lc = (cur["l"] - prev_o["l"]) if cur and prev_o else None
            prev_o = cur or prev_o
            det.append([d, bz, round(dn / 1000) if dn is not None else None,
                        round(sc / 1000) if sc is not None else None, round(lc / 1000) if lc is not None else None])
            if bz is None:
                continue
            st["pos_days"] += bz > 0
            st["neg_days"] += bz < 0
            if dn:
                if dn > 0:
                    st["d_buy"] += dn
                    st["d_buy_pos"] += dn if bz > 0 else 0
                else:
                    st["d_sell"] -= dn
                    st["d_sell_neg"] -= dn if bz < 0 else 0
            if sc and sc > 0:
                st["s_add"] += sc
                st["s_add_pos"] += sc if bz > 0 else 0
            if lc and lc > 0:
                st["l_add"] += lc
                st["l_add_neg"] += lc if bz < 0 else 0
        detail[code] = det
        rows.append([
            code, o["name"], p.get("market", ""), 1 if code.startswith("00") else 0,
            close, round(chg / prev * 100, 2) if prev else None,
            round(v5 / 1000), round(o["oi"] / 1000),
            round(o["s"] / 1000), round(o["l"] / 1000),
            r4(o["s"] / v5), r4((o["s"] - o["l"]) / v5), r4(o["l"] / v5), r4((o["l"] - o["s"]) / v5),
            round((o["s"] - b["s"]) / 1000) if b else None, round((o["l"] - b["l"]) / 1000) if b else None,
            round(dc / 1000) if dc is not None else None, r4(dc / v5) if dc is not None else None,
            basis(asof, code), st["pos_days"], st["neg_days"],
            *[round(st[k] / 1000) for k in ("d_buy_pos", "d_buy", "d_sell_neg", "d_sell", "s_add_pos", "s_add", "l_add_neg", "l_add")],
        ])
    rows.sort(key=lambda r: -r[10])
    return {"date": asof, "month": month, "next_settle": nxt, "last_settle": last_settle,
            "cycle_start": cycle[0] if cycle else None, "cycle_days": len(cycle), "base_day": base_day,
            "v5_days": v5_days, "cols": COLS, "rows": rows, "dcols": DCOLS, "detail": detail}


def write_settle(data_dir, out_path):
    payload = build(data_dir, holidays=futures_site.load_holidays(data_dir))
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    p = build(Path(__file__).resolve().parent.parent / "data")
    print({k: v for k, v in p.items() if k not in ("rows", "detail")}, len(p["rows"]))
    for r in p["rows"][:int(sys.argv[1]) if len(sys.argv) > 1 else 10]:
        print(r, p["detail"][r[0]])
