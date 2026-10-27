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
"""
import csv
import json
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


def build(fut_dir, n=N):
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
    return {"date": dates[-1] if dates else None, "cols": COLS, "rows": rows}


def write_futures(data_dir, out_path):
    payload = build(Path(data_dir) / "futures")
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
