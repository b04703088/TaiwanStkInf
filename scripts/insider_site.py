"""data/insider/ → 網頁用 data/insider/insider.json（insider.html 用）。

  trades    每月事後申報：每位內部人當月的集中市場買賣、其他原因增減、設質／解質（最近 MONTHS 個月）
  transfer  持股轉讓事前申報（最近 TRANSFER_DAYS 天）：預定在市場賣出、鉅額、洽特定人、贈與、信託…
  pledge    質權設定彙總表（每月每家公司）：董監當月設質／解質、累計設質比例，經理人＋大股東設質；
            只留當月有設質／解質、或設質比例 ≥ PLEDGE_PCT% 的公司（最近 MONTHS 個月）
欄位名 + 列（減少檔案大小）；公司層級的加總、換算市值（股數 × 價格）由網頁計算。
換算市值用的價格（px 欄，收盤價，元）：
  transfer  申報日收盤（申報日不是交易日就用前一個交易日）
  trades    當月平均收盤（月報只有張數沒有成交價，用月均價估實際買賣金額）
  pledge    當月最後一個交易日收盤
設質累計、持股等「現在值多少」的數字，網頁用最新收盤。
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

MONTHS = 6
TRANSFER_DAYS = 180
PLEDGE_PCT = 20
TRADES = ["month", "market", "code", "company", "role", "name", "held_prev", "buy_mkt", "buy_other",
          "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add", "pledge_sub", "note", "dup", "px"]
TRANSFER = ["date", "market", "code", "company", "role", "name", "method", "shares", "held", "after",
            "daily_max", "transferee", "period", "px"]
PLEDGE = ["month", "market", "code", "company", "ds_held", "ds_padd", "ds_psub", "ds_pledged", "ds_ppct",
          "mgr_held", "major_held", "mm_pledged", "mm_ppct", "px"]
INTS = {"held_prev", "buy_mkt", "buy_other", "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add",
        "pledge_sub", "shares", "held", "after", "daily_max", "ds_held", "ds_padd", "ds_psub", "ds_pledged",
        "mgr_held", "major_held", "mm_pledged"}
NUMS = {"ds_ppct", "mm_ppct", "px"}


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


def _keep_pledge(r):
    v = {k: _v(k, r.get(k)) for k in ("ds_padd", "ds_psub", "ds_ppct", "mm_ppct")}
    return v["ds_padd"] or v["ds_psub"] or (v["ds_ppct"] or 0) >= PLEDGE_PCT or (v["mm_ppct"] or 0) >= PLEDGE_PCT


class Closes:
    """data/YYYY/YYYYMMDD.csv 每日收盤 → 查某檔某天（或之前最近交易日）收盤、某月平均收盤、月底收盤。"""

    def __init__(self, data_dir, since):
        self.days = []                      # 由舊到新的交易日
        self.px = {}                        # 日期 → {代號: 收盤}
        root = Path(data_dir)
        y0 = int(since[:4])
        for p in sorted(root.glob("[0-9]" * 4 + "/" + "[0-9]" * 8 + ".csv")):
            if int(p.parent.name) < y0:
                continue
            d = f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}"
            if d < since:
                continue
            day = {}
            for r in _read(p):
                try:
                    c = float(r.get("close") or 0)
                except ValueError:
                    continue
                if c > 0:
                    day[r["code"]] = c
            if day:
                self.days.append(d)
                self.px[d] = day

    def on(self, code, d):
        """d 當天（不是交易日就往前找，最多 10 個交易日）的收盤"""
        import bisect
        i = bisect.bisect_right(self.days, d) - 1
        for j in range(i, max(-1, i - 10), -1):
            c = self.px[self.days[j]].get(code)
            if c:
                return c
        return None

    def month_avg(self, code, ym):
        cs = [self.px[d][code] for d in self.days if d[:7] == ym and code in self.px[d]]
        return round(sum(cs) / len(cs), 2) if cs else None

    def month_end(self, code, ym):
        ds = [d for d in self.days if d[:7] == ym]
        return self.on(code, ds[-1]) if ds else None


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
    pledge = []
    pmonths = sorted({p.stem[:6] for p in (d / "irb130").glob("[0-9]" * 6 + "_*.csv")})[-MONTHS:]
    for m in reversed(pmonths):
        for mkt in ("sii", "otc"):
            pledge += [dict(r, month=f"{m[:4]}-{m[4:]}", market=mkt) for r in _read(d / "irb130" / f"{m}_{mkt}.csv")
                       if _keep_pledge(r)]
    if trades or transfer or pledge:
        first = min([r["date"] for r in transfer] + [f"{m[:4]}-{m[4:]}-01" for m in months + pmonths] or [today.isoformat()])
        cl = Closes(data_dir, (date.fromisoformat(first) - timedelta(days=20)).isoformat())
        avg = {}
        for r in transfer:
            r["px"] = cl.on(r["code"], r["date"])
        for r in trades:
            k = (r["code"], r["month"])
            if k not in avg:
                avg[k] = cl.month_avg(*k)
            r["px"] = avg[k]
        for r in pledge:
            r["px"] = cl.month_end(r["code"], r["month"])
    return {"generated": generated, "months": [f"{m[:4]}-{m[4:]}" for m in reversed(months)],
            "pmonths": [f"{m[:4]}-{m[4:]}" for m in reversed(pmonths)],
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


RECENT_DAYS = 5


def write_brokers(data_dir, out_path):
    """內部人分點比對 → data/insider/brokers.json（insider.html「分點答案」「申報追蹤」用）"""
    import insider_broker as IB
    d = Path(data_dir) / "insider"
    rows = _read(d / "brokers.csv")
    if not rows:
        return None
    res = IB.build(rows, _read(d / "broker_days.csv"))
    files = sorted(p for p in (Path(data_dir) / "broker").glob("[0-9]" * 4 + "/" + "[0-9]" * 8 + ".csv"))
    files = files[-RECENT_DAYS:]
    daily = [r for p in files for r in _read(p)]
    res["recent"] = IB.recent(res["known"], daily)
    res["recent_days"] = [f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}" for p in files]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return res
