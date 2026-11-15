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
        "nt_date", "bank_date", "price_src"]
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
        # 行庫公告多在詢圈／競拍前幾天，少數在開始後（世紀鋼九 開始後 5 天才公告）；
        # 舊案沒有掛牌日時，最晚只到開始後 20 天，不要吃到同一家下一次發行的公告
        end = c.get("list_date") or c.get("issue_date") or (_plus(c["bb_start"], 20) if c.get("bb_start") else "9999")
        hit = [x for x in banks.get(c["code"], []) if ref and ref <= x <= end]
        c["bank_date"] = max(hit) if hit else ""
    add_mops_price(cases, d)
    return cases


def add_mops_price(cases, d):
    """觀測站「完成訂價／轉換價格及溢價率」重訊 → 補還沒有承銷公告 PDF 的案子的訂價基準日、溢價率、轉換價。
    公會承銷公告 PDF 通常晚一兩天才上，這則重訊多在訂價當天發；兩邊都有時以承銷公告為準。"""
    det = {(r["code"], r["enter_date"], r["serial"]): r for r in _read(d / "mops_details.csv")}
    px = {}
    for e in _read(d / "mops_events.csv"):
        x = det.get((e["code"], e["enter_date"], e["serial"]))
        if e["kind"] in ("price", "bank") and x and x.get("conv_price"):
            px.setdefault(e["code"], []).append({**x, "date": e["date"]})
    for c in cases:
        if c.get("conv_price") or c["code"] not in px:
            continue
        lo = c.get("bb_start") or c.get("bank_date") or c.get("eff_date") or ""
        if not lo:
            continue
        hit = [x for x in px[c["code"]] if lo <= (x["price_base_date"] or x["date"]) <= _plus(lo, 30)]
        if not hit:
            continue
        x = max(hit, key=lambda x: x["date"])
        base = x["price_base_date"] or x["date"]
        c.update(conv_price=x["conv_price"], premium=c.get("premium") or x["premium"], price_src="mops")
        c["price_base_date"] = c.get("price_base_date") or base
        if c.get("method") == "競價拍賣":
            c["done_date"] = c.get("done_date") or base


def _plus(iso, n):
    from datetime import date, timedelta
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


BANK_COLS = ["date", "time", "code", "name", "subject", "collect", "escrow", "text", "cases"]


def bank_notices(cases, data_dir, days=120):
    """代收價款行庫重訊（觀測站）→ 網頁摘要用的列：公告時間、行庫、內容摘要，加上對到的案件 id（同檔可能一次詢圈＋競拍）。
    行庫名稱等內容由 fetch_cb_pre.py 讀重訊內容後寫進 data/cb/mops_details.csv。"""
    d = Path(data_dir) / "cb"
    det = {(r["code"], r["enter_date"], r["serial"]): r for r in _read(d / "mops_details.csv")}
    evs = [r for r in _read(d / "mops_events.csv") if r["kind"] == "bank" and r["date"]]
    if not evs:
        return []
    from datetime import date, timedelta
    since = (date.fromisoformat(max(e["date"] for e in evs)) - timedelta(days=days)).isoformat()
    out = []
    for e in evs:
        if e["date"] < since:
            continue
        x = det.get((e["code"], e["enter_date"], e["serial"]), {})
        ids = [c["id"] for c in cases if c["code"] == e["code"] and c.get("bank_date") == e["date"]]
        out.append({"date": e["date"], "time": e["time"], "code": e["code"], "name": e["name"], "subject": e["subject"],
                    "collect": x.get("collect", ""), "escrow": x.get("escrow", ""), "text": x.get("text", ""),
                    "cases": ids})
    out.sort(key=lambda r: (r["date"], r["time"]), reverse=True)
    return out


def build(cases, generated=None, banks=None):
    out = {"generated": generated, "cols": COLS, "rows": [[_v(k, c.get(k)) for k in COLS] for c in cases]}
    if banks is not None:
        out["banks"] = {"cols": BANK_COLS, "rows": [[b[k] for k in BANK_COLS] for b in banks]}
    return out


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
    cases = add_flow_dates(cases, data_dir)
    payload = build(cases, gen, bank_notices(cases, data_dir))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
