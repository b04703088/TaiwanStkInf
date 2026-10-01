"""把 data/broker/ 的每日分點（前 15 大）整理成網頁用的 JSON。

輸出：
  data/broker/days.json            可用日期（由舊到新）
  data/broker/<YYYY-MM-DD>.json    當日資料（以索引壓縮）
    brokers: [[分點代號, 分點名稱], ...]
    scols / stocks: 每檔一列 [代號, 名稱, 市場, 收盤, 漲跌, 成交張數, 前15合計買超, 前15合計賣超, 平均買超成本, 平均賣超成本]
    rcols / rows:   每個分點一列 [股票索引, 邊(0 買超 / 1 賣超), 名次, 分點索引, 買進張數, 賣出張數, 佔成交比重%]
"""
import csv
import json
from pathlib import Path

SCOLS = ["code", "name", "market", "close", "change", "vol", "bt", "st", "bc", "sc"]
RCOLS = ["s", "side", "rank", "b", "buy", "sell", "pct"]


def _num(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _int(s):
    v = _num(s)
    return None if v is None else int(round(v))


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def broker_days(data_dir):
    files = sorted((f for f in (Path(data_dir) / "broker").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")
                    if len(f.stem) == 8), key=lambda p: p.name)
    return [(f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:8]}", f) for f in files]


def build_day(data_dir, date, path):
    data_dir = Path(data_dir)
    pf = data_dir / date[:4] / f"{date.replace('-', '')}.csv"
    prices = {r["code"]: r for r in _read(pf)} if pf.exists() else {}
    tp = path.with_name(path.stem + "_total.csv")
    totals = {r["code"]: r for r in _read(tp)} if tp.exists() else {}
    rows = _read(path)

    s_idx, stocks = {}, []
    b_idx, brokers = {}, []
    out = []
    for r in rows:
        c = r["code"]
        if c not in s_idx:
            p, t = prices.get(c, {}), totals.get(c, {})
            vol = _num(p.get("volume"))
            s_idx[c] = len(stocks)
            stocks.append([c, p.get("name", ""), p.get("market", ""), _num(p.get("close")), _num(p.get("change")),
                           None if vol is None else int(round(vol / 1000)),
                           _int(t.get("buy_total")), _int(t.get("sell_total")),
                           _num(t.get("buy_cost")), _num(t.get("sell_cost"))])
        if r["bid"] not in b_idx:
            b_idx[r["bid"]] = len(brokers)
            brokers.append([r["bid"], r["broker"]])
        out.append([s_idx[c], 0 if r["side"] == "B" else 1, int(r["rank"]), b_idx[r["bid"]],
                    int(r["buy"]), int(r["sell"]), _num(r["pct"])])
    return {"date": date, "brokers": brokers, "scols": SCOLS, "stocks": stocks, "rcols": RCOLS, "rows": out}


def write_site(data_dir, out_dir, days=20):
    """最近 days 天 → out_dir/data/broker/；回傳寫出的日期。"""
    out = Path(out_dir) / "data" / "broker"
    items = broker_days(data_dir)[-days:]
    if not items:
        return []
    out.mkdir(parents=True, exist_ok=True)
    dates = []
    for date, path in items:
        payload = build_day(data_dir, date, path)
        if not payload["rows"]:
            continue
        (out / f"{date}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        dates.append(date)
    (out / "days.json").write_text(json.dumps(dates), encoding="utf-8")
    return dates


# ---------------- 重點分點 ----------------
WCOLS = ["d", "b", "code", "ba", "sa", "bs", "ss"]


def _watch_config(root):
    p = Path(root) / "config" / "broker_watch.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig") as fp:
        return [{"label": (r.get("label") or "").strip() or r["branch"].strip(), "branch": r["branch"].strip()}
                for r in csv.DictReader(fp) if (r.get("branch") or "").strip()]


def build_watch(data_dir, root, days=60):
    """config 裡的分點、最近 days 個交易日 → 網頁用 JSON（金額：仟元；張數：張）。"""
    files = sorted((Path(data_dir) / "broker" / "watch").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"),
                   key=lambda p: p.name)[-days:]
    config = _watch_config(root)
    if not files or not config:
        return None
    rows_all = [r for f in files for r in _read(f)]
    name_to_bid = {}
    for r in rows_all:
        name_to_bid.setdefault(r["branch"], r["bid"])
    branches = []
    for c in config:
        bid = name_to_bid.get(c["branch"]) or name_to_bid.get(c["branch"].replace("總公司", ""))
        if bid and bid not in [b["bid"] for b in branches]:
            branches.append({"bid": bid, "label": c["label"], "branch": c["branch"]})
    b_idx = {b["bid"]: i for i, b in enumerate(branches)}
    day_list = [f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:8]}" for f in files]
    d_idx = {d: i for i, d in enumerate(day_list)}
    names, rows = {}, []
    for r in rows_all:
        if r["bid"] not in b_idx:
            continue
        names[r["code"]] = r["name"]
        rows.append([d_idx[r["date"]], b_idx[r["bid"]], r["code"],
                     _int(r["buy_amt"]), _int(r["sell_amt"]), _int(r["buy_sh"]), _int(r["sell_sh"])])
    return {"days": day_list, "branches": branches, "names": names, "cols": WCOLS, "rows": rows}


def write_watch(data_dir, root, out_dir, days=60):
    payload = build_watch(data_dir, root, days)
    if payload is None:
        return None
    out = Path(out_dir) / "data" / "broker" / "watch.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
