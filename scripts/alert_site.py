"""data/alert/*.csv → 網頁用 data/alert/alert.json（欄位名 + 列，減少檔案大小）。

  disp   處置（近 DISP_DAYS 天公布的），新到舊
  att    注意（近 ATT_DAYS 個交易日），新到舊
  days   交易日（有任何注意公告的日子，含權證），網頁算「近 10／30 日注意次數」用
  near   最新一天的注意累計次數異常（再一次就可能處置）
  names  代號 → 名稱
只列股票與 ETF（權證、可轉債等不列，見 is_stock）。
"""
import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

DISP = ["market", "ann_date", "code", "start", "end", "reason", "measure", "interval"]
ATT = ["market", "date", "code", "clauses", "close", "pe", "info"]
NEAR = ["market", "code", "situation"]
DISP_DAYS = 400
ATT_DAYS = 60


def is_stock(code):
    """股票 4 碼（含 DR）、ETF 00 開頭 4–6 碼可帶英文字尾；權證 6 碼、可轉債 5 碼不算。"""
    return bool(re.fullmatch(r"\d{4}|00\d{2,4}[A-Z]?", code or ""))


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _v(k, v):
    if v in (None, ""):
        return None
    if k == "interval":
        return int(v)
    if k in ("close", "pe"):
        try:
            return float(v)
        except ValueError:
            return None
    return v


def build(disp, att, near):
    days = sorted({a["date"] for a in att if a.get("date")})
    generated = max([days[-1] if days else ""] + [d["ann_date"] for d in disp if d.get("ann_date")]) or None
    names = {}
    for r in disp + att + near:
        if is_stock(r.get("code")) and r.get("name"):
            names[r["code"]] = r["name"]
    cut = (date.fromisoformat(generated) - timedelta(days=DISP_DAYS)).isoformat() if generated else ""
    disp = sorted((d for d in disp if is_stock(d["code"]) and d["ann_date"] >= cut),
                  key=lambda d: (d["ann_date"], d["start"], d["code"]), reverse=True)
    keep = set(days[-ATT_DAYS:])
    att = sorted((a for a in att if is_stock(a["code"]) and a["date"] in keep),
                 key=lambda a: (a["date"], a["code"]), reverse=True)
    nd = max((n["date"] for n in near if n.get("date")), default=None)
    near = [n for n in near if n.get("date") == nd and is_stock(n["code"])]
    return {"generated": generated, "days": days[-ATT_DAYS:], "names": names,
            "disp": {"cols": DISP, "rows": [[_v(k, d.get(k)) for k in DISP] for d in disp]},
            "att": {"cols": ATT, "rows": [[_v(k, a.get(k)) for k in ATT] for a in att]},
            "near": {"date": nd, "cols": NEAR, "rows": [[n.get(k) for k in NEAR] for n in near]}}


def write_alert(data_dir, out_path):
    d = Path(data_dir) / "alert"
    if not (d / "disposal.csv").exists() and not (d / "attention.csv").exists():
        return None
    payload = build(_read(d / "disposal.csv"), _read(d / "attention.csv"), _read(d / "near.csv"))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
