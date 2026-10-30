"""data/futures/*.csv（fetch_futures.py）→ 期權籌碼頁（futures.html）用的 JSON。

  data/futures/futures.json
    {date, cols, rows}  每個交易日一列（由舊到新，最近 N 天），欄位見 COLS：
      tx, tx_chg            台指期近月收盤、漲跌
      f_oi, t_oi, d_oi      外資／投信／自營商 台指期未平倉淨口數（大台＋小台／4＋微台／20 折成大台口數）
      f_oi_d                外資未平倉淨口數比前一天增減
      f_net                 外資台指期當天多空淨口數（折大台）
      f_call, f_put         外資臺指選擇權未平倉淨金額（買權、賣權，千元 → 億元）
      pc_oi, pc_vol         Put/Call Ratio（未平倉、成交量，%）
      top10_net, top10i_net 前十大交易人（全部月份）多空淨部位；其中特定法人
      top5n_net             近月前五大多空淨部位
      oi_all                台指期全市場未平倉口數
    settle  台指期月結算日（每月第三個週三，遇休市順延到下一個交易日）：
            資料期間內以實際有行情的日子判斷順延（颱風假也算進去），之後的用 data/calendar/holidays.csv 推估
    next_settle  {date, tdays}  下一個結算日、距今還有幾個交易日（不含今天）
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

N = 250
SCALE = {"TX": 1, "MTX": 0.25, "TMF": 0.05}   # 小台 1/4 大台、微台 1/20 大台
COLS = ["date", "tx", "tx_chg", "f_oi", "t_oi", "d_oi", "f_oi_d", "f_net", "f_call", "f_put",
        "pc_oi", "pc_vol", "top10_net", "top10i_net", "top5n_net", "oi_all"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def third_wed(y, m):
    d = date(y, m, 1)
    return d + timedelta((2 - d.weekday()) % 7 + 14)


def _closed(d, holidays):
    return d.weekday() >= 5 or d.isoformat() in holidays or d.strftime("%m-%d") == "01-01"


def settle_dates(dates, holidays=(), ahead=2):
    """dates：有行情的交易日（由舊到新）。回傳涵蓋這段期間＋之後 ahead 個月的月結算日"""
    if not dates:
        return [], None
    first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    known = set(dates)
    out, nxt = [], None
    y, m = first.year, first.month
    while True:
        d = third_wed(y, m)
        if d < first:               # 資料起點之前的結算日不標
            pass
        elif d > last:
            while _closed(d, holidays):
                d += timedelta(1)
            if nxt is None:
                nxt = d
            elif (d.year - last.year) * 12 + d.month - last.month > ahead:
                break
        else:
            while d.isoformat() not in known and d <= last:
                d += timedelta(1)
            if d > last:            # 結算日落在最後一天之後（還沒抓到），當未來的處理
                while _closed(d, holidays):
                    d += timedelta(1)
                nxt = nxt or d
        if d >= first:
            out.append(d.isoformat())
        m += 1
        if m > 12:
            y, m = y + 1, 1
    tdays = 0
    d = last + timedelta(1)
    while d <= nxt:
        tdays += not _closed(d, holidays)
        d += timedelta(1)
    return out, {"date": nxt.isoformat(), "tdays": tdays}


def load_holidays(data_dir):
    p = Path(data_dir) / "calendar" / "holidays.csv"
    return {r["date"] for r in _read(p)}


def build(fut_dir, n=N, holidays=()):
    fut_dir = Path(fut_dir)
    inst, pcr, large, tx = (_read(fut_dir / f"{k}.csv") for k in ("inst", "pcr", "large", "tx"))
    if not inst:
        return None
    by = {}
    for r in inst:
        d = by.setdefault(r["date"], {})
        if r["product"] in SCALE:
            k = r["who"]
            d[f"{k}_oi"] = d.get(f"{k}_oi", 0) + (_f(r["oi_net"]) or 0) * SCALE[r["product"]]
            d[f"{k}_net"] = d.get(f"{k}_net", 0) + (_f(r["net_vol"]) or 0) * SCALE[r["product"]]
        elif r["who"] == "foreign" and r["product"] in ("TXO_C", "TXO_P"):
            v = _f(r["oi_net_val"])
            d["f_call" if r["product"] == "TXO_C" else "f_put"] = round(v / 1e5, 2) if v is not None else None
    for r in pcr:
        by.setdefault(r["date"], {}).update(pc_oi=_f(r["pc_oi"]), pc_vol=_f(r["pc_vol"]))
    for r in large:
        d = by.setdefault(r["date"], {})
        net5 = (_f(r["top5_long"]) or 0) - (_f(r["top5_short"]) or 0)
        net10 = (_f(r["top10_long"]) or 0) - (_f(r["top10_short"]) or 0)
        if r["month"] == "all":
            d["top10i_net" if r["kind"] == "inst" else "top10_net"] = net10
        elif r["kind"] == "all":
            d["top5n_net"] = net5
    for r in tx:
        by.setdefault(r["date"], {}).update(tx=_f(r["close"]), tx_chg=_f(r["change"]), oi_all=_f(r["oi_all"]))
    dates = sorted(d for d, x in by.items() if "foreign_oi" in x)[-n:]
    rows, prev = [], None
    for d in dates:
        x = by[d]
        f_oi = round(x.get("foreign_oi")) if x.get("foreign_oi") is not None else None
        rows.append([d, x.get("tx"), x.get("tx_chg"), f_oi,
                     round(x["trust_oi"]) if "trust_oi" in x else None, round(x["dealer_oi"]) if "dealer_oi" in x else None,
                     f_oi - prev if f_oi is not None and prev is not None else None,
                     round(x["foreign_net"]) if "foreign_net" in x else None,
                     x.get("f_call"), x.get("f_put"), x.get("pc_oi"), x.get("pc_vol"),
                     x.get("top10_net"), x.get("top10i_net"), x.get("top5n_net"), x.get("oi_all")])
        prev = f_oi
    settle, nxt = settle_dates(dates, holidays)
    return {"date": dates[-1] if dates else None, "cols": COLS, "rows": rows, "settle": settle, "next_settle": nxt}


def write_futures(data_dir, out_path):
    payload = build(Path(data_dir) / "futures", holidays=load_holidays(data_dir))
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
