#!/usr/bin/env python3
"""隔夜美股數字：給 07:52 盤前更新直接讀，不用再靠網路搜尋找昨晚收盤。

讀  data/us/daily.csv（fetch_us.py）、data/macro/daily.csv（fetch_macro.py）、data/commod/daily.csv（fetch_commod.py）、
    config/us_supply.csv、最新的台股收盤 data/YYYY/YYYYMMDD.csv
寫  data/digest/overnight.md

由 .github/workflows/overnight.yml 在台北 05:15 後（美股收盤後）跑；08:30 早班 batch 之後也會再算一次。
美股交易日以 SPY 最新一天為準；某個數字的日期跟它不同（例如還沒更新）就標出日期。

用法：python scripts/overnight.py
"""
import csv
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from us_site import DRIVERS, NAMES, load_us  # noqa: E402

TPE = timezone(timedelta(hours=8))
OUT = ROOT / "data" / "digest" / "overnight.md"
INDEX = [("SPY", "S&P 500（SPY）"), ("QQQ", "那斯達克 100（QQQ）"), ("^SOX", "費城半導體"), ("TSM", "台積電 ADR")]
MOVERS = DRIVERS + ["QCOM", "MU", "MRVL", "DELL", "SMCI", "ANET", "VRT", "AMKR", "COHR", "LITE", "WDC", "TER"]
COMMOD = [("brent", "布蘭特原油"), ("wti", "西德州原油"), ("gold", "黃金"), ("copper", "銅")]
WEEK = "一二三四五六日"


def pct(a, b):
    return (a / b - 1) * 100 if a and b else None


def fmt(x, n=1, sign=True):
    if x is None:
        return "—"
    return f"{x:+,.{n}f}" if sign else f"{x:,.{n}f}"


def md(d):
    dt = datetime.fromisoformat(d)
    return f"{dt.month}/{dt.day}（{WEEK[dt.weekday()]}）"


def last_two(series, upto):
    """series: [(date, value)] 排序過；回傳 upto 當天（或之前最近一天）與前一天。"""
    xs = [x for x in series if x[0] <= upto]
    return (xs[-1], xs[-2]) if len(xs) >= 2 else (xs[-1] if xs else None, None)


def big_thr(c):
    """大漲大跌門檻：max(3%, 1.5 倍近 250 日日報酬標準差)，跟 us.html 一樣。"""
    rs = [pct(c[i], c[i - 1]) for i in range(max(1, len(c) - 250), len(c))]
    rs = [r for r in rs if r is not None]
    if len(rs) < 20:
        return 3.0
    m = sum(rs) / len(rs)
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / len(rs))
    return max(3.0, round(sd * 1.5 * 2) / 2)


def read_series(path, key_col, val_col):
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            try:
                out.setdefault(r[key_col], []).append((r["date"], float(r[val_col])))
            except (ValueError, TypeError):
                continue
    for v in out.values():
        v.sort()
    return out


def tw_close(upto):
    """upto 當天（或之前最近一天）的台股收盤：(YYYY-MM-DD, {代號: (名稱, 收盤)})。
    台股收盤在同一日曆日美股開盤前，所以 ADR 溢價用同一天比。"""
    key = upto.replace("-", "")
    files = sorted(p for p in (ROOT / "data").glob("20[0-9][0-9]/20*.csv") if p.stem <= key)
    if not files:
        return None, {}
    p = files[-1]
    out = {}
    with p.open(encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            try:
                out[r["code"]] = (r["name"], float(r["close"]))
            except (ValueError, TypeError):
                continue
    s = p.stem
    return f"{s[:4]}-{s[4:6]}-{s[6:]}", out


def suppliers():
    """{美股: [台股代號...]}，高曝險排前面。"""
    out = {}
    p = ROOT / "config" / "us_supply.csv"
    if not p.exists():
        return out
    rank = {"高": 0, "中": 1, "低": 2}
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    rows.sort(key=lambda r: rank.get(r["exposure"], 3))
    for r in rows:
        lst = out.setdefault(r["us"], [])
        if r["code"] not in lst:
            lst.append(r["code"])
    return out


def build():
    us = load_us(ROOT / "data")
    if "SPY" not in us:
        return None
    day = us["SPY"][0][-1]
    lines = [f"# 隔夜美股 {day}", "",
             f"美股交易日 {md(day)}（美東）・產生於台北 {datetime.now(TPE):%Y-%m-%d %H:%M}・"
             "資料：Yahoo Finance（data/us、data/macro）、原物料頁（data/commod）。", ""]

    def chg(sym):
        if sym not in us:
            return None, None, None
        d, _, c = us[sym]
        i = len(d) - 1
        while i > 0 and d[i] > day:
            i -= 1
        return d[i], c[i], pct(c[i], c[i - 1]) if i > 0 else None

    lines.append("## 指數與台積電 ADR")
    lines.append("")
    for sym, name in INDEX:
        d, c, p = chg(sym)
        if c is None:
            continue
        note = "" if d == day else f"（{md(d)}）"
        lines.append(f"- {name} {fmt(c, 2, False)}，{fmt(p, 2)}%{note}")
    # ADR 溢價：TSM ÷（2330 收盤 × 5 ÷ 匯率）− 1
    tw_d, tw = tw_close(day)
    macro = read_series(ROOT / "data" / "macro" / "daily.csv", "series", "value")
    _, tsm, _ = chg("TSM")
    fx = last_two(macro.get("usdtwd", []), day)[0]
    if tsm and fx and "2330" in tw:
        prem = pct(tsm, tw["2330"][1] * 5 / fx[1])
        lines.append(f"- 台積電 ADR 溢價 {fmt(prem, 1)}%（ADR {tsm:.2f} 美元 vs 台股 {md(tw_d)} 收 {tw['2330'][1]:,.0f} 元、匯率 {fx[1]:.3f}）")
    lines.append("")

    lines.append("## 利率、美元、波動")
    lines.append("")
    spec = [("us10y", "美 10 年債殖利率", "%", "bp", 3), ("dxy", "美元指數", "", "%", 2), ("vix", "VIX", "", "pt", 2),
            ("usdtwd", "美元兌台幣", "", "%", 3)]
    for key, name, unit, how, n in spec:
        cur, prev = last_two(macro.get(key, []), day)
        if not cur:
            continue
        note = "" if cur[0] == day else f"（{md(cur[0])}）"
        if prev is None:
            delta = ""
        elif how == "bp":
            delta = f"，{(cur[1] - prev[1]) * 100:+.0f} bp"
        elif how == "pt":
            delta = f"，{cur[1] - prev[1]:+.2f}"
        else:
            delta = f"，{fmt(pct(cur[1], prev[1]), 2)}%"
        lines.append(f"- {name} {cur[1]:,.{n}f}{unit}{delta}{note}")
    h, i_ = macro.get("hyg", []), macro.get("ief", [])
    if h and i_:
        ief = dict(i_)
        r = [(d, v / ief[d]) for d, v in h if d in ief and d <= day]
        if len(r) > 20:
            lines.append(f"- 信用利差代理 HYG÷IEF 日 {fmt(pct(r[-1][1], r[-2][1]), 2)}%、20 日 {fmt(pct(r[-1][1], r[-21][1]), 1)}%"
                         f"（跌＝利差擴大）" + ("" if r[-1][0] == day else f"（{md(r[-1][0])}）"))
    lines.append("")

    com = read_series(ROOT / "data" / "commod" / "daily.csv", "key", "close")
    rows = []
    for key, name in COMMOD:
        cur, prev = last_two(com.get(key, []), day)
        if cur and prev and cur[0] >= (datetime.fromisoformat(day) - timedelta(days=4)).date().isoformat():
            note = "" if cur[0] == day else f"（{md(cur[0])}）"
            rows.append(f"- {name} {cur[1]:,.2f}，{fmt(pct(cur[1], prev[1]), 2)}%{note}")
    if rows:
        lines += ["## 原物料", ""] + rows + [""]

    sup = suppliers()
    mv = []
    for sym in dict.fromkeys(MOVERS):
        if sym not in us:
            continue
        d, c, p = chg(sym)
        if p is None or d != day:
            continue
        thr = big_thr(us[sym][2][:us[sym][0].index(d) + 1])
        mv.append((sym, c, p, thr))
    mv.sort(key=lambda x: -abs(x[2]))
    lines.append("## 美股大廠（依漲跌幅絕對值）")
    lines.append("")
    lines.append("門檻＝max(3%, 1.5 倍日報酬標準差)，超過標「大漲／大跌」；後面是 config/us_supply.csv 的台股供應鏈（高曝險在前）。")
    lines.append("")
    for sym, c, p, thr in mv:
        tag = "，**大漲**" if p >= thr else "，**大跌**" if p <= -thr else ""
        tws = [f"{tw[k][0]} {k}" if k in tw else k for k in sup.get(sym, [])[:5]]
        tail = f"；台股：{'、'.join(tws)}" if tws else ""
        lines.append(f"- {NAMES.get(sym, sym)} {sym} {fmt(p, 1)}%（門檻 ±{thr:g}%{tag}）{tail}")
    lines.append("")
    lines.append("台指期夜盤、Fed 發言與新聞不在這份檔案裡，盤前更新另外搜尋。")
    return "\n".join(lines) + "\n"


def main():
    text = build()
    if not text:
        print("沒有 data/us/daily.csv 的 SPY，跳過")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
