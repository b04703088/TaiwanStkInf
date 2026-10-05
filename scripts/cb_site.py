"""data/cb/cases.csv → 網頁用 data/cb/cb.json（欄位名 + 列，減少檔案大小）。
進度（詢圈中／待訂價／待掛牌…）由網頁依當天日期計算。"""
import csv
import json
from pathlib import Path

COLS = ["id", "code", "company", "short", "series", "bond_code", "type", "method", "lead",
        "units", "bb_units", "bb_start", "bb_end", "premium_lo", "premium_hi", "min_price", "done_date",
        "price_base_date", "conv_price", "premium", "issue_pct", "pay_date", "list_expected",
        "issue_date", "list_date",
        "board_date", "board_amount", "board_method", "filed_date", "eff_date", "sfb_status", "stop_date", "wd_date", "sfb_amount"]
SUBPAGES = ["cb-pipeline.html", "cb-active.html", "cb-bb.html", "cb-auction.html", "cb-listed.html"]
NUMS = {"series", "units", "bb_units", "premium_lo", "premium_hi", "min_price", "conv_price", "premium", "issue_pct", "board_amount", "sfb_amount"}


def _v(k, v):
    if v in (None, ""):
        return None
    if k in NUMS:
        try:
            f = float(v)
            return int(f) if f.is_integer() and k in ("series", "units", "bb_units") else f
        except ValueError:
            return None
    if k == "company":
        return v.replace("股份有限公司", "")
    if k == "lead":
        return v.replace("股份有限公司", "").replace("綜合證券", "").replace("證券", "")
    return v


def build(cases, generated=None):
    return {"generated": generated, "cols": COLS, "rows": [[_v(k, c.get(k)) for k in COLS] for c in cases]}


def write_cb(data_dir, out_path):
    p = Path(data_dir) / "cb" / "cases.csv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as fp:
        cases = list(csv.DictReader(fp))
    gen = None
    src = Path(data_dir) / "cb" / "sources.json"
    if src.exists():
        gen = json.loads(src.read_text(encoding="utf-8")).get("generated")
    payload = build(cases, gen)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
