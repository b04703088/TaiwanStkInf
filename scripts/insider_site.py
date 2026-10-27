"""data/insider/ → 網頁用 data/insider/insider.json（insider.html 用）。

  trades    每月事後申報：每位內部人當月的集中市場買賣、其他原因增減、設質／解質（最近 MONTHS 個月）
  transfer  持股轉讓事前申報（最近 TRANSFER_DAYS 天）：預定在市場賣出、鉅額、洽特定人、贈與、信託…
  pledge    內部人設質／解質公告（每天，最近 PLEDGE_DAYS 天；fetch_insider.py 有抓才有）
欄位名 + 列（減少檔案大小）；公司層級的加總、估計金額（股數 × 最新收盤）由網頁計算。
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

MONTHS = 6
TRANSFER_DAYS = 180
PLEDGE_DAYS = 180
TRADES = ["month", "market", "code", "company", "role", "name", "held_prev", "buy_mkt", "buy_other",
          "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add", "pledge_sub", "note", "dup"]
TRANSFER = ["date", "market", "code", "company", "role", "name", "method", "shares", "held", "after",
            "daily_max", "transferee", "period"]
PLEDGE = ["date", "market", "code", "company", "role", "name", "kind", "shares", "held", "pledged",
          "pledged_pct", "pledgee", "deal_date"]
INTS = {"held_prev", "buy_mkt", "buy_other", "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add",
        "pledge_sub", "shares", "held", "after", "daily_max"}
NUMS = {"pledged_pct"}


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _v(k, v):
    if v in (None, ""):
        return 0 if k in INTS else None
    if k in INTS:
        try:
            return int(float(v))
        except ValueError:
            return 0
    if k in NUMS:
        try:
            return float(v)
        except ValueError:
            return None
    return v


def _table(cols, rows):
    return {"cols": cols, "rows": [[_v(k, r.get(k)) for k in cols] for r in rows]}


def roc_period(s):
    """事前申報的有效轉讓期間「1151015~1151114」→ 「2026-10-15~2026-11-14」；看不懂就原樣。"""
    def one(x):
        x = x.strip()
        if len(x) == 7 and x.isdigit():
            return f"{int(x[:3]) + 1911}-{x[3:5]}-{x[5:]}"
        return x
    return "~".join(one(x) for x in (s or "").split("~")) if s else s


def build(data_dir, today=None, generated=None):
    d = Path(data_dir) / "insider"
    today = today or date.today()
    months = sorted(p.stem for p in (d / "trades").glob("[0-9]" * 6 + ".csv"))[-MONTHS:]
    trades = []
    for m in reversed(months):
        trades += _read(d / "trades" / f"{m}.csv")
    since = (today - timedelta(days=TRANSFER_DAYS)).isoformat()
    transfer = []
    for p in sorted((d / "transfer").glob("*.csv")):
        transfer += [dict(r, period=roc_period(r.get("period"))) for r in _read(p) if r.get("date", "") >= since]
    transfer.sort(key=lambda r: (r["date"], r["code"]), reverse=True)
    since = (today - timedelta(days=PLEDGE_DAYS)).isoformat()
    pledge = []
    for p in sorted((d / "pledge").glob("*.csv")):
        pledge += [r for r in _read(p) if r.get("date", "") >= since]
    pledge.sort(key=lambda r: (r["date"], r["code"]), reverse=True)
    return {"generated": generated, "months": [f"{m[:4]}-{m[4:]}" for m in reversed(months)],
            "trades": _table(TRADES, trades), "transfer": _table(TRANSFER, transfer),
            "pledge": _table(PLEDGE, pledge)}


def write_insider(data_dir, out_path, today=None):
    d = Path(data_dir) / "insider"
    if not d.exists():
        return None
    payload = build(data_dir, today)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
