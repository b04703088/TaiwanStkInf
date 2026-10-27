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


# ---------------- 內資分點（排除外資、凱基-台北、總公司） ----------------
# 外資券商（以 branches.csv 的券商名稱判斷）；含外商銀行的證券部門
FOREIGN = {"美林", "摩根大通", "台灣摩根士丹利", "美商高盛", "花旗環球", "花旗", "新加坡商瑞銀", "港商麥格理",
           "港商野村", "大和國泰", "法銀巴黎", "台灣巴克萊", "港商蘇皇", "港商聯昌", "港商德意志(停)",
           "港商法國興業(停)", "瑞士信貸(停)", "香港上海匯豐", "渣打商銀"}
EXCLUDE_BRANCHES = {"凱基-台北"}
def _branch_kinds(data_dir):
    """bid → (券商代號, 券商名稱)。"""
    p = Path(data_dir) / "broker" / "branches.csv"
    return {r["bid"]: (r["broker_id"], r["broker"]) for r in _read(p)} if p.exists() else {}


def is_local_branch(bid, name, kinds):
    """不是外資、不是凱基-台北、不是券商總公司的分點。"""
    if name in EXCLUDE_BRANCHES:
        return False
    k = kinds.get(bid)
    if k:
        return k[1] not in FOREIGN and k[0] != bid
    return "-" in name  # 不在清單裡：總公司名稱不含「-」


PERIODS = (1, 5, 10, 20)
LBCOLS = ["bid", "name", "buy", "sell", "net", "nb", "ns", "bdays", "top", "pnl"]


def _scores(data_dir):
    p = Path(data_dir) / "broker" / "score" / "branches.csv"
    return {r["bid"]: r for r in _read(p)} if p.exists() else {}


def build_local(data_dir, days=20, top=5):
    """全市場前 15 大分點中的地方分點（非外資、非凱基-台北、非總公司），最新一天往回各期間的買賣超金額排行。

    金額（仟元）≈ 淨張數 × 當日收盤價。每個分點：買超金額、賣超金額、淨額、買超／賣超檔數、
    有淨買超的天數、買超最多的幾檔股票 [代號, 金額]。另附 broker_score 的分類。
    """
    data_dir = Path(data_dir)
    items = broker_days(data_dir)[-days:]
    if not items:
        return None
    kinds = _branch_kinds(data_dir)
    names, bnames, daily = {}, {}, []  # daily[i] = {bid: {code: (金額, 淨張數)}}
    last_close = {}
    for date, path in items:
        pf = data_dir / date[:4] / f"{date.replace('-', '')}.csv"
        prices = {r["code"]: r for r in _read(pf)} if pf.exists() else {}
        per, seen = {}, set()
        for r in _read(path):
            key = (r["code"], r["bid"])
            if key in seen or r["code"].startswith("00") or not is_local_branch(r["bid"], r["broker"], kinds):
                continue
            seen.add(key)
            close, net = _num(prices.get(r["code"], {}).get("close")), _int(r["net"])
            if close is None or not net:
                continue
            per.setdefault(r["bid"], {})[r["code"]] = (net * close, net)
            names[r["code"]] = prices[r["code"]].get("name", "")
            bnames[r["bid"]] = r["broker"]
        daily.append(per)
        for c, p in prices.items():
            v = _num(p.get("close"))
            if v is not None:
                last_close[c] = v
    scores = _scores(data_dir)
    periods = {}
    for n in PERIODS:
        agg, shares, bdays = {}, {}, {}
        for per in daily[-n:]:
            for bid, m in per.items():
                a, sh = agg.setdefault(bid, {}), shares.setdefault(bid, {})
                for c, (v, k) in m.items():
                    a[c] = a.get(c, 0) + v
                    sh[c] = sh.get(c, 0) + k
                if sum(v for v, _ in m.values()) > 0:
                    bdays[bid] = bdays.get(bid, 0) + 1
        rows = []
        for bid, a in agg.items():
            buy = sum(v for v in a.values() if v > 0)
            sell = -sum(v for v in a.values() if v < 0)
            tops = sorted(((c, v) for c, v in a.items() if v > 0), key=lambda x: -x[1])[:top]
            # 估計損益：期間內買賣（以當日收盤價成交）到最新收盤價的市值變化
            pnl = sum(k * last_close[c] for c, k in shares[bid].items() if c in last_close) - sum(a.values())
            rows.append([bid, bnames[bid], int(round(buy)), int(round(sell)), int(round(buy - sell)),
                         sum(v > 0 for v in a.values()), sum(v < 0 for v in a.values()), bdays.get(bid, 0),
                         [[c, int(round(v))] for c, v in tops], int(round(pnl))])
        rows.sort(key=lambda r: -r[4])
        periods[str(n)] = {"from": items[max(0, len(items) - n)][0], "days": min(n, len(items)), "rows": rows}
    # 分點評分：[分類, 隔日賣出比例%, z5, 買超後 5 日平均超額報酬%, 5 日勝率%, 5 日事件數]
    cls = {bid: [r["class"], _num(r.get("flip_ratio")), _num(r.get("z5")), _num(r.get("ex5")),
                 _num(r.get("hit5")), _int(r.get("n5"))]
           for bid, r in scores.items() if bid in bnames}
    return {"date": items[-1][0], "cols": LBCOLS, "periods": periods, "names": names, "score": cls,
            "foreign": sorted(FOREIGN), "excluded": sorted(EXCLUDE_BRANCHES)}
def write_local(data_dir, out_dir, days=20):
    payload = build_local(data_dir, days)
    if payload is None:
        return None
    out = Path(out_dir) / "data" / "broker" / "local.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
