"""data/chips/（三大法人、借券賣出、當沖）＋ data/tdcc/（集保大戶）→ 法人籌碼頁（chips.html）與選股頁的籌碼欄位。

  data/chips/chips.json   {date, days, market, cols, rows, tdcc}
      days    最近 MARKET_N 個交易日
      market  每天 [date, 外資, 投信, 自營商, 三大法人（億元，張數 × 收盤估算）, 借券賣出餘額（億元）, 當沖占成交量 %]
      rows    最新一天每檔一列（欄位見 ROW_COLS；張數單位：張）
      tdcc    {date, prev}：最新一週與前一週的集保資料日期
  data/chips/s/<代號>.json 個股近 SERIES_N 個交易日 {d, c, f, t, dl, sbl, dt}＋集保週資料 {w, p1000, holders}

金額是張數 × 當天收盤估算（交易所只公布股數）。連買／連賣天數：從最新一天往回數，同方向（> 0 或 < 0）連續幾天。
"""
import csv
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

MARKET_N = 120
SERIES_N = 250          # 個股走勢保留天數（K 線頁副圖也用，約一年）
LOOK = 60           # 算排行、連買要讀幾天
ROW_COLS = ["code", "name", "market", "close", "value",
            "f1", "f5", "f20", "fs", "t1", "t5", "t20", "ts", "d1", "d5", "d20", "ds", "i1", "i5", "i20", "is",
            "fv5", "tv5", "dv5", "iv5",
            "sbl", "sbl1", "sbl5", "sbl_days", "dt", "dt5",
            "p1000", "big_d", "holders", "hold_d", "p400"]
SCREEN_COLS = ["f5", "fs", "t5", "ts", "i5", "sbl", "sbl5", "dt", "big", "big_d", "hold_d"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _lots(v):
    return None if v is None else round(v / 1000)


def _add(a, b):
    return None if a is None and b is None else round((a or 0) + (b or 0), 2)


def chip_files(data_dir):
    return sorted(Path(data_dir).glob("chips/[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)


def prices_for(data_dir, d):
    """{code: (close, volume 股)}。"""
    p = Path(data_dir) / d[:4] / (d.replace("-", "") + ".csv")
    if not p.exists():
        return {}
    out = {}
    for r in _read(p):
        c, v = _f(r.get("close")), _f(r.get("volume"))
        if c:
            out[r["code"]] = (c, v or 0)
    return out


def streak(xs):
    """xs 由舊到新；回傳最新一天往回同方向連續天數（買為正、賣為負，0 或沒資料就停）。"""
    n, sign = 0, 0
    for x in reversed(xs):
        if x is None or x == 0:
            break
        s = 1 if x > 0 else -1
        if sign and s != sign:
            break
        sign, n = s, n + 1
    return n * sign


def load(data_dir, n):
    days = []
    for f in chip_files(data_dir)[-n:]:
        rows = _read(f)
        if rows:
            d = rows[0]["date"]
            days.append((d, {r["code"]: r for r in rows}, prices_for(data_dir, d)))
    return days


def tdcc_weeks(data_dir, n=26):
    files = sorted((Path(data_dir) / "tdcc").glob("[0-9]*.csv"))[-n:]
    return [(f.stem, {r["code"]: r for r in _read(f)}) for f in files]


def build(days, weeks):
    """回傳 (chips.json payload, {code: 個股 payload}, {code: 選股欄位})。"""
    if not days:
        return None, {}, {}
    look = days[-LOOK:]
    last_d, last, last_px = look[-1]
    series = lambda code, k: [_f(dd.get(code, {}).get(k)) for _, dd, _ in look]  # noqa: E731

    def sum_n(xs, n):
        v = [x for x in xs[-n:] if x is not None]
        return sum(v) if v else None

    def val(code, k, n):
        """近 n 天買賣超金額（億元）：每天張數 × 當天收盤。"""
        tot, has = 0.0, False
        for _, dd, px in look[-n:]:
            x = _f(dd.get(code, {}).get(k))
            c = px.get(code, (None,))[0]
            if x is not None and c:
                tot += x * c
                has = True
        return round(tot / 1e8, 2) if has else None

    wk = weeks[-1][1] if weeks else {}
    pw = weeks[-2][1] if len(weeks) > 1 else {}
    rows, screen = [], {}
    for code, r in sorted(last.items()):
        c, vol = last_px.get(code, (None, None))
        f, t, dl, i = (series(code, k) for k in ("f_net", "t_net", "d_net", "inst_net"))
        fd = series(code, "fd_net")
        f = [a + (b or 0) if a is not None else None for a, b in zip(f, fd)]  # 外資含外資自營商
        sb = series(code, "sbl_bal")
        sbl, sbl1 = _f(r.get("sbl_bal")), None
        if len(sb) > 1 and sb[-1] is not None and sb[-2] is not None:
            sbl1 = sb[-1] - sb[-2]
        sbl5 = sb[-1] - sb[-6] if len(sb) > 5 and sb[-1] is not None and sb[-6] is not None else None
        vols = [px.get(code, (None, None))[1] for _, _, px in look[-20:]]
        vols = [v for v in vols if v]
        avg_vol = sum(vols) / len(vols) if vols else None
        dts = []
        for _, dd, px in look[-5:]:
            dv, v = _f(dd.get(code, {}).get("dt_vol")), px.get(code, (None, None))[1]
            dts.append(dv / v * 100 if dv is not None and v else None)
        dt = round(dts[-1], 1) if dts and dts[-1] is not None else None
        dt5 = [x for x in dts if x is not None]
        w, pv = wk.get(code), pw.get(code)
        p1000 = _f(w["p1000"]) if w else None
        big_d = round(p1000 - _f(pv["p1000"]), 2) if w and pv and _f(pv["p1000"]) is not None else None
        holders = int(w["holders"]) if w else None
        hold_d = round((holders / int(pv["holders"]) - 1) * 100, 2) if w and pv and int(pv["holders"] or 0) else None
        row = {"code": code, "name": r["name"], "market": "上市" if r["market"] == "TWSE" else "上櫃",
               "close": c, "value": round(c * vol / 1e8, 2) if c and vol else None,
               "f1": _lots(f[-1]), "f5": _lots(sum_n(f, 5)), "f20": _lots(sum_n(f, 20)), "fs": streak(f),
               "t1": _lots(t[-1]), "t5": _lots(sum_n(t, 5)), "t20": _lots(sum_n(t, 20)), "ts": streak(t),
               "d1": _lots(dl[-1]), "d5": _lots(sum_n(dl, 5)), "d20": _lots(sum_n(dl, 20)), "ds": streak(dl),
               "i1": _lots(i[-1]), "i5": _lots(sum_n(i, 5)), "i20": _lots(sum_n(i, 20)), "is": streak(i),
               "fv5": _add(val(code, "f_net", 5), val(code, "fd_net", 5)), "tv5": val(code, "t_net", 5),
               "dv5": val(code, "d_net", 5), "iv5": val(code, "inst_net", 5),
               "sbl": _lots(sbl), "sbl1": _lots(sbl1), "sbl5": _lots(sbl5),
               "sbl_days": round(sbl / avg_vol, 1) if sbl and avg_vol else None,
               "dt": dt, "dt5": round(sum(dt5) / len(dt5), 1) if dt5 else None,
               "p1000": p1000, "big_d": big_d, "holders": holders, "hold_d": hold_d,
               "p400": _f(w["p400"]) if w else None}
        if all(row[k] is None for k in ("f1", "t1", "i1", "sbl", "dt")):
            continue
        rows.append([row[k] for k in ROW_COLS])
        screen[code] = {"f5": row["f5"], "fs": row["fs"], "t5": row["t5"], "ts": row["ts"], "i5": row["i5"],
                        "sbl": row["sbl"], "sbl5": row["sbl5"], "dt": row["dt"],
                        "big": p1000, "big_d": big_d, "hold_d": hold_d}
    market = []
    for d, dd, px in days[-MARKET_N:]:
        tot = {"f": 0.0, "t": 0.0, "d": 0.0, "i": 0.0, "sbl": 0.0}
        dtv = vol = 0.0
        for code, r in dd.items():
            c, v = px.get(code, (None, None))
            if not c:
                continue
            for k, col in (("f", "f_net"), ("t", "t_net"), ("d", "d_net"), ("i", "inst_net"), ("sbl", "sbl_bal")):
                x = _f(r.get(col))
                if x is not None:
                    tot[k] += x * c
            x = _f(r.get("fd_net"))
            if x is not None:
                tot["f"] += x * c
            dv = _f(r.get("dt_vol"))
            if dv is not None and v:
                dtv += dv
                vol += v
        market.append([d] + [round(tot[k] / 1e8, 1) for k in ("f", "t", "d", "i", "sbl")] +
                      [round(dtv / vol * 100, 2) if vol else None])
    per = {}
    for code in last:
        sd = days[-SERIES_N:]
        px = [p.get(code, (None, None))[0] for _, _, p in sd]
        get = lambda k: [_lots(_f(dd.get(code, {}).get(k))) for _, dd, _ in sd]  # noqa: E731
        fd = get("fd_net")
        f = [a + (b or 0) if a is not None else None for a, b in zip(get("f_net"), fd)]
        dt = []
        for _, dd, p in sd:
            dv, v = _f(dd.get(code, {}).get("dt_vol")), p.get(code, (None, None))[1]
            dt.append(round(dv / v * 100, 1) if dv is not None and v else None)
        per[code] = {"code": code, "name": last[code]["name"], "d": [x[0] for x in sd], "c": px,
                     "f": f, "t": get("t_net"), "dl": get("d_net"), "sbl": get("sbl_bal"), "dt": dt,
                     "w": [w[0] for w in weeks],
                     "p1000": [_f(w[1][code]["p1000"]) if code in w[1] else None for w in weeks],
                     "holders": [int(w[1][code]["holders"]) if code in w[1] else None for w in weeks]}
    payload = {"date": last_d, "days": [d for d, _, _ in days[-MARKET_N:]],
               "market_cols": ["date", "foreign", "trust", "dealer", "inst", "sbl", "dt"], "market": market,
               "cols": ROW_COLS, "rows": rows,
               "tdcc": {"date": weeks[-1][0] if weeks else None, "prev": weeks[-2][0] if len(weeks) > 1 else None}}
    return payload, per, screen


def write_chips(data_dir, out_dir):
    """回傳選股頁用的 (欄位, {code: {欄位: 值}})；沒有資料回傳 None。"""
    days = load(data_dir, max(MARKET_N, SERIES_N, LOOK))
    payload, per, screen = build(days, tdcc_weeks(data_dir))
    if payload is None:
        return None
    out = Path(out_dir)
    if (out / "s").exists():
        shutil.rmtree(out / "s")
    (out / "s").mkdir(parents=True, exist_ok=True)
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    (out / "chips.json").write_text(dump(payload), encoding="utf-8")
    for code, s in per.items():
        (out / "s" / f"{code}.json").write_text(dump(s), encoding="utf-8")
    prices = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    if prices and payload["date"].replace("-", "") < (date.fromisoformat(_iso(prices[-1].stem)) - timedelta(days=7)).strftime("%Y%m%d"):
        return None  # 籌碼資料落後股價一週以上：不放進選股頁，免得用舊籌碼配新股價
    return SCREEN_COLS, screen


def _iso(stem):
    return f"{stem[:4]}-{stem[4:6]}-{stem[6:]}"
