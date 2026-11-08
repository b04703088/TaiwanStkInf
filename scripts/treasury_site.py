"""data/treasury/*.csv → 網頁用 data/treasury.json（欄位名 + 列，減少檔案大小）。

  rows  每次買回計畫（fetch_treasury.py 的 programs.csv），決議日新到舊；
        執行中的計畫附上「買回達一定標準」申報加總（prog_*）當作進度；
        ann_date/ann_time 是董事會決議買回的重訊公告日期、時間（announce.csv，盤前／盤中／盤後由網頁判斷）
  brk   推定公司派分點（每個計畫）；co 每家公司比對到的分點（見 scripts/treasury_broker.py）
進度狀態（執行中／待公告／已完成）、現價與買回價格區間的位置由網頁依當天日期與最新股價計算。
"""
import csv
import json
from datetime import date
from collections import defaultdict
from pathlib import Path

import treasury_broker

COLS = ["market", "code", "name", "board_date", "purpose", "cap_amount", "plan_shares", "price_lo", "price_hi",
        "start", "end", "done", "bought_shares", "exec_pct", "bought_amount", "avg_price", "issued_pct", "reason",
        "prog_shares", "prog_amount", "prog_date", "prog_held_pct", "ann_date", "ann_time", "ann_sess"]
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


def trading_days(data_dir):
    """data/YYYY/YYYYMMDD.csv（每日股價）→ 交易日集合"""
    return {f.stem[:4] + "-" + f.stem[4:6] + "-" + f.stem[6:] for f in Path(data_dir).glob("[12][0-9][0-9][0-9]/[0-9]*.csv")
            if len(f.stem) == 8}


def session(d, t, tdays=None):
    """公告日期＋時間 → 盤前（09:00 前）／盤中（09:00～13:30）／盤後／休市。
    tdays：交易日集合；最後一個交易日之後的平日當作交易日（當天股價檔可能還沒抓）。"""
    if not d or not t:
        return None
    if tdays:
        if d not in tdays and (d <= max(tdays) or date.fromisoformat(d).weekday() >= 5):
            return "休市"
    elif date.fromisoformat(d).weekday() >= 5:
        return "休市"
    return "盤前" if t < "09:00" else "盤中" if t <= "13:30" else "盤後"


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


def build(programs, progress, generated=None, brokers=None, days=None, announce=None, tdays=None):
    prog = progress_by_program(progress)
    ann = {(a["market"], a["code"], a["board_date"]): a for a in announce or [] if a.get("ann_date")}
    rows = []
    for p in programs:
        r = dict(p)
        a = ann.get((p["market"], p["code"], p["board_date"]))
        if a:
            r.update(ann_date=a["ann_date"], ann_time=a["ann_time"], ann_sess=session(a["ann_date"], a["ann_time"], tdays))
        if not p.get("bought_shares"):
            r.update(prog.get((p["market"], p["code"], p["board_date"]), {}))
        rows.append([_v(k, r.get(k)) for k in COLS])
    rows.sort(key=lambda x: (x[3] or "", x[1]), reverse=True)
    brk, co = treasury_broker.build(programs, brokers or [], days or [])
    return {"generated": generated, "cols": COLS, "rows": rows, "brk": brk, "co": co}


def write_treasury(data_dir, out_path):
    d = Path(data_dir) / "treasury"
    programs = _read(d / "programs.csv")
    if not programs:
        return None
    gen = None
    if (d / "sources.json").exists():
        gen = json.loads((d / "sources.json").read_text(encoding="utf-8")).get("generated")
    payload = build(programs, _read(d / "progress.csv"), gen, _read(d / "brokers.csv"), _read(d / "broker_days.csv"),
                    _read(d / "announce.csv"), trading_days(data_dir))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
