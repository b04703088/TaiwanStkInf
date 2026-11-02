"""data/cb/cases.csv → 網頁用 data/cb/cb.json（欄位名 + 列，減少檔案大小）。
進度（詢圈中／待訂價／待掛牌…）由網頁依當天日期計算。"""
import csv
import json
from pathlib import Path

COLS = ["id", "code", "company", "short", "series", "bond_code", "type", "method", "lead",
        "units", "bb_units", "bb_start", "bb_end", "premium_lo", "premium_hi", "min_price", "done_date",
        "price_base_date", "conv_price", "premium", "issue_pct", "pay_date", "list_expected",
        "issue_date", "list_date",
        "board_date", "board_amount", "board_method", "filed_date", "eff_date", "sfb_status", "stop_date", "wd_date", "sfb_amount",
        "nt_date", "bank_date"]
SUBPAGES = ["cb-calendar.html", "cb-pipeline.html", "cb-active.html", "cb-bb.html", "cb-auction.html", "cb-listed.html"]
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


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def add_flow_dates(cases, data_dir):
    """補流程日期：nt_date＝承銷公告日（公會承銷公告的申報日）、
    bank_date＝代收價款行庫公告日（公開資訊觀測站，通常在詢圈／競拍前幾天，是快要開始承銷的訊號）"""
    d = Path(data_dir) / "cb"
    nt = {r["sn"]: r["filed"] for r in _read(d / "notices.csv")}
    banks = {}
    for r in _read(d / "mops_events.csv"):
        if r["kind"] == "bank" and r["date"]:
            banks.setdefault(r["code"], []).append(r["date"])
    for c in cases:
        c["nt_date"] = nt.get(c.get("nt_sn") or "", "")
        ref = c.get("board_date") or c.get("filed_date") or ""
        end = c.get("list_date") or c.get("issue_date") or "9999"
        hit = [x for x in banks.get(c["code"], []) if ref and ref <= x <= end]
        c["bank_date"] = max(hit) if hit else ""
    return cases


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
    payload = build(add_flow_dates(cases, data_dir), gen)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
