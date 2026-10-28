"""data/insider/ → 網頁用 data/insider/insider.json（insider.html 用）。

  trades    每月事後申報：每位內部人當月的集中市場買賣、其他原因增減、設質／解質（最近 MONTHS 個月）
  transfer  持股轉讓事前申報（最近 TRANSFER_DAYS 天）：預定在市場賣出、鉅額、洽特定人、贈與、信託…
  pledge    質權設定彙總表（每月每家公司）：董監當月設質／解質、累計設質比例，經理人＋大股東設質；
            只留當月有設質／解質、或設質比例 ≥ PLEDGE_PCT% 的公司（最近 MONTHS 個月）
欄位名 + 列（減少檔案大小）；公司層級的加總、估計金額（股數 × 最新收盤）由網頁計算。

另產生 data/insider/alerts.json（首頁「內部人新動作」用，見 build_alerts）。
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

MONTHS = 6
TRANSFER_DAYS = 180
PLEDGE_PCT = 20
TRADES = ["month", "market", "code", "company", "role", "name", "held_prev", "buy_mkt", "buy_other",
          "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add", "pledge_sub", "note", "dup"]
TRANSFER = ["date", "market", "code", "company", "role", "name", "method", "shares", "held", "after",
            "daily_max", "transferee", "period"]
PLEDGE = ["month", "market", "code", "company", "ds_held", "ds_padd", "ds_psub", "ds_pledged", "ds_ppct",
          "mgr_held", "major_held", "mm_pledged", "mm_ppct"]
INTS = {"held_prev", "buy_mkt", "buy_other", "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add",
        "pledge_sub", "shares", "held", "after", "daily_max", "ds_held", "ds_padd", "ds_psub", "ds_pledged",
        "mgr_held", "major_held", "mm_pledged"}
NUMS = {"ds_ppct", "mm_ppct"}


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
    return {"generated": generated, "months": [f"{m[:4]}-{m[4:]}" for m in reversed(months)],
            "pmonths": [f"{m[:4]}-{m[4:]}" for m in reversed(pmonths)],
            "trades": _table(TRADES, trades), "transfer": _table(TRANSFER, transfer),
            "pledge": _table(PLEDGE, pledge)}


ALERT_DAYS = 30
ALERT_MIN_AMT = 3_000_000   # 每月申報：異動股數合計 × 收盤 低於這個金額的公司不列（檔案太大）


def _closes(data_dir, files=10):
    """最近幾個交易日檔案裡每檔的最新收盤（停牌的用更早的價）。"""
    out = {}
    paths = sorted(Path(data_dir).glob("[0-9]" * 4 + "/[0-9]*.csv"), key=lambda p: p.name)[-files:]
    for p in paths:
        for r in _read(p):
            try:
                out[r["code"].strip()] = float(r["close"])
            except (TypeError, ValueError):
                pass
    return out


def _family(s):
    return "配偶" in (s or "") or "子女" in (s or "")


def build_alerts(data_dir, today=None, generated=None):
    """首頁提醒用的精簡清單；每筆有固定 key，網頁用 localStorage 記住哪些看過。

    transfer  近 ALERT_DAYS 天的事前申報轉讓，一筆一列
    monthly   最新一個月的事後申報（持股異動＋設質解質），一家公司一列，附變動最大的幾位內部人
    fam = 有配偶／未成年子女；amt = 股數 × 最新收盤（估計，元），mamt 只算集中市場買賣、pamt 只算設質解質，px = 用的收盤價。門檻篩選、自選優先在網頁做。
    """
    d = Path(data_dir) / "insider"
    today = today or date.today()
    px = _closes(data_dir)
    since = (today - timedelta(days=ALERT_DAYS)).isoformat()
    transfer = []
    for p in sorted((d / "transfer").glob("*.csv")):
        for r in _read(p):
            if r.get("date", "") < since:
                continue
            sh = _v("shares", r.get("shares"))
            transfer.append({"key": f"t:{r['date']}:{r['code']}:{r['name']}:{sh}", "date": r["date"],
                             "code": r["code"], "company": r.get("company", ""), "role": r.get("role", ""),
                             "name": r.get("name", ""), "method": r.get("method", ""), "shares": sh,
                             "transferee": r.get("transferee", ""), "period": roc_period(r.get("period")),
                             "fam": _family(r.get("role")), "amt": round(sh * px.get(r["code"], 0))})
    transfer.sort(key=lambda x: (x["date"], x["shares"]), reverse=True)

    months = sorted(p.stem for p in (d / "trades").glob("[0-9]" * 6 + ".csv"))
    monthly, month = [], None
    if months:
        m = months[-1]
        month = f"{m[:4]}-{m[4:]}"
        by = {}
        for r in _read(d / "trades" / f"{m}.csv"):
            if r.get("dup"):
                continue
            v = {k: _v(k, r.get(k)) for k in ("buy_mkt", "sell_mkt", "buy_other", "sell_other",
                                               "pledge_add", "pledge_sub")}
            if not any(v.values()):
                continue
            g = by.setdefault(r["code"], {"key": f"m:{month}:{r['code']}", "month": month, "code": r["code"],
                                          "company": r.get("company", ""), "buy": 0, "sell": 0, "oin": 0,
                                          "oout": 0, "padd": 0, "psub": 0, "fam": False, "who": []})
            for a, b in (("buy", "buy_mkt"), ("sell", "sell_mkt"), ("oin", "buy_other"), ("oout", "sell_other"),
                         ("padd", "pledge_add"), ("psub", "pledge_sub")):
                g[a] += v[b]
            fam = _family(r.get("name"))
            g["fam"] = g["fam"] or fam
            # [姓名, 職稱, 市場淨買, 其他淨增, 質押淨增, 是否配偶子女]
            g["who"].append([r["name"].split("(")[0], r.get("role", ""), v["buy_mkt"] - v["sell_mkt"],
                             v["buy_other"] - v["sell_other"], v["pledge_add"] - v["pledge_sub"], fam])
        for g in by.values():
            g["amt"] = round((g["buy"] + g["sell"] + g["oin"] + g["oout"] + g["padd"] + g["psub"])
                             * px.get(g["code"], 0))
            g["px"] = px.get(g["code"], 0)
            g["mamt"] = round((g["buy"] + g["sell"]) * px.get(g["code"], 0))   # 只算集中市場買賣
            g["pamt"] = round((g["padd"] + g["psub"]) * px.get(g["code"], 0))  # 設質＋解質
            if g["amt"] < ALERT_MIN_AMT:
                continue
            # 配偶子女那幾位一定留，其他按變動大小
            g["who"].sort(key=lambda w: (not w[5], -(abs(w[2]) + abs(w[3]) + abs(w[4]))))
            g["who"] = g["who"][:3]
            monthly.append(g)
        monthly.sort(key=lambda g: -g["amt"])
    return {"generated": generated, "since": since, "month": month, "transfer": transfer, "monthly": monthly}


def write_insider(data_dir, out_path, today=None):
    d = Path(data_dir) / "insider"
    if not d.exists():
        return None
    payload = build(data_dir, today)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    alerts = build_alerts(data_dir, today, payload.get("generated"))
    (out_path.parent / "alerts.json").write_text(json.dumps(alerts, ensure_ascii=False, separators=(",", ":")),
                                                 encoding="utf-8")
    return payload
