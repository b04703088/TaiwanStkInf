"""data/analyst/*.csv → 網頁用 data/analyst/analyst.json（欄位名 + 列，減少檔案大小）。

  cons   FactSet 市場共識快訊（fetch_analyst.py 的 consensus_<年>.csv），新到舊
  reps   外資個股報告（reports_<年>.csv），新到舊
  names  代號 → 名稱
股價、潛在空間由網頁讀最新一天的 data/daily/<日期>.json 計算。
"""
import csv
import json
from pathlib import Path

CONS = ["date", "time", "news_id", "code", "kind", "year", "analysts", "prev", "value", "chg_pct",
        "high", "low", "target", "bull", "neutral", "bear"]
REPS = ["date", "time", "news_id", "broker", "code", "action", "rating", "target", "prev_target", "title"]
INTS = {"news_id", "analysts", "bull", "neutral", "bear"}
NUMS = {"prev", "value", "chg_pct", "high", "low", "target", "prev_target"}


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


def _rows(data_dir, prefix):
    out = []
    for f in sorted(Path(data_dir).glob(f"analyst/{prefix}_[0-9][0-9][0-9][0-9].csv")):
        with f.open(encoding="utf-8") as fp:
            out += list(csv.DictReader(fp))
    out.sort(key=lambda r: (r["date"], r["time"], r["news_id"]), reverse=True)
    return out


def build(cons, reps):
    names = {}
    for r in cons + reps:
        if r.get("code") and r.get("name"):
            names.setdefault(r["code"], r["name"])  # 新到舊排序，取最新的名稱
    dates = [r["date"] for r in cons + reps]
    return {
        "generated": max(dates) if dates else None,
        "cons": {"cols": CONS, "rows": [[_v(k, r.get(k)) for k in CONS] for r in cons]},
        "reps": {"cols": REPS, "rows": [[_v(k, r.get(k)) for k in REPS] for r in reps]},
        "names": names,
    }


def write_analyst(data_dir, out_path):
    cons, reps = _rows(data_dir, "consensus"), _rows(data_dir, "reports")
    if not cons and not reps:
        return None
    payload = build(cons, reps)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
