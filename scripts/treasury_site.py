"""data/treasury/*.csv → 網頁用 data/treasury.json（欄位名 + 列，減少檔案大小）。

  rows  每次買回計畫（fetch_treasury.py 的 programs.csv），決議日新到舊；
        執行中的計畫附上「買回達一定標準」申報加總（prog_*）當作進度
  brk   推定公司派分點（每個計畫）；co 每家公司比對到的分點（見 scripts/treasury_broker.py）
進度狀態（執行中／待公告／已完成）、現價與買回價格區間的位置由網頁依當天日期與最新股價計算。
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import treasury_broker

COLS = ["market", "code", "name", "board_date", "purpose", "cap_amount", "plan_shares", "price_lo", "price_hi",
        "start", "end", "done", "bought_shares", "exec_pct", "bought_amount", "avg_price", "issued_pct", "reason",
        "prog_shares", "prog_amount", "prog_date", "prog_held_pct"]
INTS = {"cap_amount", "plan_shares", "bought_shares", "bought_amount", "prog_shares", "prog_amount"}
NUMS = {"price_lo", "price_hi", "exec_pct", "avg_price", "issued_pct", "prog_held_pct"}


def _v(k, v):
    if v in (None, ""):
        return None
    if k in INTS:
        try:
            return int(float(v))
        except ValueError:
            return None
    if k in NUMS:
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except ValueError:
            return None
    return v


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def progress_by_program(progress):
    """同一計畫的達標申報加總：股數、金額、最後申報的買回日與累積持股比例。"""
    out = defaultdict(lambda: {"prog_shares": 0, "prog_amount": 0, "prog_date": "", "prog_held_pct": ""})
    for r in progress:
        k = (r["market"], r["code"], r["board_date"])
        o = out[k]
        o["prog_shares"] += int(float(r["shares"] or 0))
        o["prog_amount"] += int(float(r["amount"] or 0))
        d = r["buy_date"] or r["report_date"]
        if d >= o["prog_date"]:
            o["prog_date"], o["prog_held_pct"] = d, r["held_pct"]
    return out


def build(programs, progress, generated=None, brokers=None):
    prog = progress_by_program(progress)
    rows = []
    for p in programs:
        r = dict(p)
        if not p.get("bought_shares"):
            r.update(prog.get((p["market"], p["code"], p["board_date"]), {}))
        rows.append([_v(k, r.get(k)) for k in COLS])
    rows.sort(key=lambda x: (x[3] or "", x[1]), reverse=True)
    brk, co = treasury_broker.build(programs, brokers or [])
    return {"generated": generated, "cols": COLS, "rows": rows, "brk": brk, "co": co}


def write_treasury(data_dir, out_path):
    d = Path(data_dir) / "treasury"
    programs = _read(d / "programs.csv")
    if not programs:
        return None
    gen = None
    if (d / "sources.json").exists():
        gen = json.loads((d / "sources.json").read_text(encoding="utf-8")).get("generated")
    payload = build(programs, _read(d / "progress.csv"), gen, _read(d / "brokers.csv"))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
