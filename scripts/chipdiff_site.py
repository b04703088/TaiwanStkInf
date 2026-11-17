"""籌碼差頁（chipdiff.html）：把 Leo 的「籌碼差」筆記（notes/籌碼差.md）裡的觀察項目畫成走勢、排成表。

輸出 data/chipdiff.json：
  date      最新交易日
  market    大盤每日（2023-01 起）cols：
              date, taiex 加權指數, value 成交值（億）, f 外資買賣超（億）, t 投信買賣超（億）,
              fin 融資餘額（億，官方金額）, ul 不限用途借貸擔保市值（億，2025-07 起）, sbl 借券賣出餘額市值（億）
  cols/rows 最新一天每檔一列（只收近一年至少 60 天有收盤的股票）：
              code name market close r20(近 20 日漲跌%)
              fin fin20 fin_p   融資餘額（張）、20 日增減%、在自己近一年的百分位（0＝一年最低、100＝一年最高）
              ul  ul20  ul_p    不限用途借貸擔保（張），同上
              sbl sbl20 sbl_p   借券賣出餘額（張），同上
              f20 f20r f20_p    外資近 20 日買賣超（張）、佔 20 日成交量%、20 日累計在自己近一年的百分位
              p1000 big_d hold_d wk   千張大戶持股%、與 wk 週前相比（百分點）、集保人數增減%、比較的週數
              c5                近 5 日前 15 大分點集中度%（conc.json）
              sc               籌碼分數：下列每項「籌碼變集中」+1、「變分散」−1 加總
                                融資 20 日減／增、不限用途減／增、借券減／增、外資 20 日買／賣、大戶比例升／降、
                                集保人數減／增、分點集中度正／負
  tdcc      {first, last, n}：集保資料有幾週

歷史長度：融資、不限用途個股資料 2025-07 起；法人、借券 2023-01 起；集保每週累積（2026-10 起）；
分點 2026-09-30 起。百分位只用近 HIST 個交易日，至少 MIN_N 天才算。
買賣家數（全部分點）免費來源拿不到（見 conc_site.py），先用前 15 大分點集中度代替。
"""
import csv
import json
from pathlib import Path

HIST = 250      # 百分位用近一年
MIN_N = 60
START = 20230101


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _files(d, sub):
    return {int(p.stem): p for p in Path(d).glob(f"{sub}/[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8}


def _iso(n):
    s = str(n)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _pct(hist, v):
    xs = [x for x in hist if x is not None]
    if v is None or len(xs) < MIN_N:
        return None
    return round(sum(1 for x in xs if x <= v) / len(xs) * 100)


def _chg(a, b):
    return None if a is None or b is None or not b else round((a - b) / b * 100, 1)


def build(data_dir, prices, conc=None):
    d = Path(data_dir)
    px, days = prices
    days = [x for x in days if x >= START]
    if not days:
        return None
    close = {}
    vol = {}
    for code, s in px.items():
        close[code] = {r[0]: r[4] for r in s["rows"] if r[0] >= START}
        vol[code] = {r[0]: r[5] for r in s["rows"] if r[0] >= START}

    chips = _files(d, "chips")
    margin = _files(d, "margin")
    pledge = _files(d, "pledge")

    # ---- 大盤 ----
    idx = {}
    p = d / "margin" / "index.csv"
    if p.exists():
        for r in _read(p):
            idx[int(r["date"].replace("-", ""))] = (_f(r["taiex"]), _f(r["value"]))
    fin_amt = {}
    p = d / "margin" / "level.csv"
    if p.exists():
        for r in _read(p):
            k = int(r["date"].replace("-", ""))
            fin_amt[k] = fin_amt.get(k, 0) + (_f(r["fin_amount"]) or 0)
    p = d / "margin" / "summary.csv"  # level.csv 由建站時補，最新幾天以 summary.csv 為準
    if p.exists():
        sm = {}
        for r in _read(p):
            k = int(r["date"].replace("-", ""))
            sm[k] = sm.get(k, 0) + (_f(r["fin_amount"]) or 0)
        fin_amt.update(sm)

    recent = set(days[-HIST - 25:])
    st_sbl, st_f, st_fin, st_ul = {}, {}, {}, {}  # 近一年個股序列 {code: {day: v}}
    market = []
    for day in days:
        cl = {c: v.get(day) for c, v in close.items()}
        f = t = sbl = None
        if day in chips:
            f = t = sbl = 0.0
            for r in _read(chips[day]):
                c = cl.get(r["code"])
                fn, tn, sb = _f(r["f_net"]), _f(r["t_net"]), _f(r["sbl_bal"])
                if day in recent:
                    st_sbl.setdefault(r["code"], {})[day] = None if sb is None else sb / 1000
                    st_f.setdefault(r["code"], {})[day] = None if fn is None else fn / 1000
                if not c:
                    continue
                f += (fn or 0) * c
                t += (tn or 0) * c
                sbl += (sb or 0) * c
        ul = None
        if day in pledge:
            ul = 0.0
            for r in _read(pledge[day]):
                b = _f(r["ul_bal"])
                if day in recent:
                    st_ul.setdefault(r["code"], {})[day] = b
                c = cl.get(r["code"])
                if c and b:
                    ul += b * 1000 * c
        if day in margin and day in recent:
            for r in _read(margin[day]):
                st_fin.setdefault(r["code"], {})[day] = _f(r["fin_bal"])
        tx, val = idx.get(day, (None, None))
        y = lambda v: None if v is None else round(v / 1e8, 1)  # noqa: E731
        market.append([_iso(day), tx, y(val), y(f), y(t), y(fin_amt.get(day)), y(ul) if ul else None, y(sbl)])

    # ---- 集保 ----
    tdcc_files = sorted((d / "tdcc").glob("[0-9]*.csv"))
    tdcc = [{r["code"]: r for r in _read(p)} for p in tdcc_files]

    # ---- 個股 ----
    D = days[-1]
    hist_days = days[-HIST:]
    conc5 = {}
    if conc:
        i5 = conc["cols"].index("c5") if "c5" in conc["cols"] else None
        if i5 is not None:
            conc5 = {r[0]: r[i5] for r in conc["rows"]}

    def series(st, code):
        m = st.get(code, {})
        return [m.get(x) for x in hist_days]

    def trio(st, code):
        s = series(st, code)
        now = s[-1]
        ago = s[-21] if len(s) > 20 else None
        return now, _chg(now, ago), _pct(s, now)

    rows = []
    for code, s in px.items():
        c = close[code].get(D)
        if c is None or sum(1 for x in hist_days if x in close[code]) < MIN_N:
            continue
        c20 = close[code].get(days[-21]) if len(days) > 20 else None
        fin, fin20, fin_p = trio(st_fin, code)
        ul, ul20, ul_p = trio(st_ul, code)
        sbl, sbl20, sbl_p = trio(st_sbl, code)
        fs = series(st_f, code)
        roll = [None if any(x is None for x in fs[i - 19:i + 1]) else sum(fs[i - 19:i + 1]) for i in range(19, len(fs))]
        f20 = roll[-1] if roll else None
        v20 = sum(vol[code].get(x, 0) or 0 for x in days[-20:])
        f20r = round(f20 / v20 * 100, 1) if f20 is not None and v20 else None
        p1000 = big_d = hold_d = None
        wk = 0
        if tdcc and code in tdcc[-1]:
            a = tdcc[-1][code]
            p1000 = _f(a["p1000"])
            base = next(((i, w[code]) for i, w in enumerate(tdcc[:-1]) if code in w), None)
            if base:
                wk = len(tdcc) - 1 - base[0]
                b = base[1]
                big_d = None if p1000 is None or _f(b["p1000"]) is None else round(p1000 - _f(b["p1000"]), 2)
                hold_d = _chg(_f(a["holders"]), _f(b["holders"]))
        c5 = conc5.get(code)
        sig = [(-fin20 if fin20 is not None else None), (-ul20 if ul20 is not None else None),
               (-sbl20 if sbl20 is not None else None), f20, big_d, (-hold_d if hold_d is not None else None), c5]
        sc = sum((1 if x > 0 else -1 if x < 0 else 0) for x in sig if x is not None)
        r = lambda v: None if v is None else round(v)  # noqa: E731
        rows.append([code, s["name"], "上市" if s["market"] == "TWSE" else "上櫃", c, _chg(c, c20),
                     r(fin), fin20, fin_p, r(ul), ul20, ul_p, r(sbl), sbl20, sbl_p,
                     r(f20), f20r, _pct(roll, f20),
                     p1000, big_d, hold_d, wk, c5, sc])
    rows.sort(key=lambda x: x[0])
    cols = ["code", "name", "market", "close", "r20", "fin", "fin20", "fin_p", "ul", "ul20", "ul_p",
            "sbl", "sbl20", "sbl_p", "f20", "f20r", "f20_p", "p1000", "big_d", "hold_d", "wk", "c5", "sc"]
    return {
        "date": _iso(D),
        "market": {"cols": ["date", "taiex", "value", "f", "t", "fin", "ul", "sbl"], "rows": market},
        "cols": cols, "rows": rows,
        "tdcc": {"first": tdcc_files[0].stem if tdcc_files else None,
                 "last": tdcc_files[-1].stem if tdcc_files else None, "n": len(tdcc_files)},
    }


def write(data_dir, out, prices, conc_path=None):
    conc = None
    if conc_path and Path(conc_path).exists():
        conc = json.loads(Path(conc_path).read_text(encoding="utf-8"))
    obj = build(data_dir, prices, conc)
    if obj is None:
        return
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
