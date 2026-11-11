"""分點集中度（與買賣家數）→ 網頁 JSON data/broker/conc.json（conc.html 排名表、stock.html 個股卡片共用）。

  date, days(最近幾個交易日，舊→新), win([1, 5, 20] 實際可用天數), has_count(有沒有全分點家數),
  cols / rows：每檔一列
    code, name, market, close, chg(當日漲跌%),
    每個區間 k ∈ 1/5/20：c{k} 集中度%, t{k} 前15大買超−賣超(張), r{k} 區間漲跌%,
                         b{k} 買超家數, s{k} 賣超家數, d{k} 家數差（沒有全分點資料時為 null）
  hist: {代號: [[每日集中度%...], [每日家數差...]]}（對應 days，沒資料 null）

定義（Leo 2026-11-11）：
  - 集中度 = （區間淨買超前 15 名分點合計 − 淨賣超前 15 名合計）÷ 區間成交張數 × 100%。
    分點資料（富邦 zco）每天只有前 15 大買超、前 15 大賣超；5／20 日是把每個分點每天上榜的淨張數加總後重新排前 15 名，
    某天沒上榜的那天當 0 → 區間值是近似（大分點連續買賣幾乎每天都在榜上，誤差小）。
  - 家數差 = 買超家數 − 賣超家數，需要全部分點的資料（data/broker/count/<YYYY>/<YYYYMMDD>.csv：code, buyers, sellers；
    有 <YYYYMMDD>_branch.csv.gz（bid, code, net）時 5／20 日用分點加總算）。免費來源拿不到，目前沒有。
"""
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

WINS = (1, 5, 20)
TOP = 15


def _num(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def top15_days(data_dir):
    files = sorted((f for f in (Path(data_dir) / "broker").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")
                    if len(f.stem) == 8), key=lambda p: p.name)
    return [(f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}", f) for f in files]


def read_top15(path):
    """{代號: {分點: 淨張數}}（前 15 大買超＋前 15 大賣超）"""
    out = defaultdict(dict)
    for r in _read(path):
        out[r["code"]][r["bid"]] = out[r["code"]].get(r["bid"], 0) + int(r["net"])
    return out


def read_count(data_dir, date):
    """全分點家數：({代號: (買超家數, 賣超家數)}, {代號: {分點: 淨張數}} 或 None)；沒有資料回 (None, None)。"""
    d = Path(data_dir) / "broker" / "count" / date[:4]
    s = date.replace("-", "")
    if not (d / f"{s}.csv").exists():
        return None, None
    cnt = {r["code"]: (int(r["buyers"]), int(r["sellers"])) for r in _read(d / f"{s}.csv")}
    br = None
    if (d / f"{s}_branch.csv.gz").exists():
        br = defaultdict(dict)
        with gzip.open(d / f"{s}_branch.csv.gz", "rt", encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                if r["code"]:
                    br[r["code"]][r["bid"]] = int(r["net"])
    return cnt, br


def read_prices(data_dir, date):
    p = Path(data_dir) / date[:4] / f"{date.replace('-', '')}.csv"
    return {r["code"]: r for r in _read(p)} if p.exists() else {}


def prev_trading_day(data_dir, date):
    s = date.replace("-", "")
    before = sorted(f.stem for f in Path(data_dir).glob(f"{date[:4]}/[0-9]*.csv") if len(f.stem) == 8 and f.stem < s)
    if not before:
        before = sorted(f.stem for f in Path(data_dir).glob(f"{int(date[:4]) - 1}/[0-9]*.csv") if len(f.stem) == 8)
    return f"{before[-1][:4]}-{before[-1][4:6]}-{before[-1][6:]}" if before else None


def conc(nets, vol):
    """nets = {分點: 淨張數} → (集中度%, 前15大買超−賣超 張)"""
    pos = sorted((v for v in nets.values() if v > 0), reverse=True)[:TOP]
    neg = sorted((-v for v in nets.values() if v < 0), reverse=True)[:TOP]
    t = sum(pos) - sum(neg)
    return (round(t / vol * 100, 2) if vol else None), t


def counts(nets):
    b = sum(1 for v in nets.values() if v > 0)
    s = sum(1 for v in nets.values() if v < 0)
    return b, s, b - s


def build(data_dir):
    data_dir = Path(data_dir)
    days = top15_days(data_dir)[-max(WINS):]
    if not days:
        return None
    dates = [d for d, _ in days]
    daily = [read_top15(p) for _, p in days]
    cnts = [read_count(data_dir, d) for d in dates]
    prices = [read_prices(data_dir, d) for d in dates]
    vol = [{c: (_num(r.get("volume")) or 0) / 1000 for c, r in p.items()} for p in prices]
    last = prices[-1]
    win = [min(k, len(dates)) for k in WINS]
    base = {}
    for k in win:
        pd = prev_trading_day(data_dir, dates[-k])
        base[k] = read_prices(data_dir, pd) if pd else {}
    has_count = cnts[-1][0] is not None

    cols = ["code", "name", "market", "close", "chg"]
    for k in WINS:
        cols += [f"c{k}", f"t{k}", f"r{k}", f"b{k}", f"s{k}", f"d{k}"]
    rows, hist = [], {}
    for code in sorted(daily[-1]):
        p = last.get(code)
        if not p or not (_num(p.get("volume")) or 0):
            continue
        close, chg = _num(p.get("close")), _num(p.get("change"))
        prev = close - chg if close is not None and chg is not None else None
        row = [code, p.get("name", ""), "上市" if p.get("market") == "TWSE" else "上櫃", close,
               round(chg / prev * 100, 2) if prev else None]
        for k in win:
            nets = defaultdict(int)
            for d in daily[-k:]:
                for bid, n in d.get(code, {}).items():
                    nets[bid] += n
            c, t = conc(nets, sum(v.get(code, 0) for v in vol[-k:]))
            bc = _num(base[k].get(code, {}).get("close"))
            row += [c, t, round((close / bc - 1) * 100, 2) if close and bc else None]
            # 家數：區間每天都有全分點資料才算
            cw = cnts[-k:]
            if all(x[0] is not None for x in cw) and k == 1:
                b, s_ = cw[-1][0].get(code, (0, 0))
                row += [b, s_, b - s_]
            elif all(x[0] is not None and x[1] is not None for x in cw):
                agg = defaultdict(int)
                for x in cw:
                    for bid, n in x[1].get(code, {}).items():
                        agg[bid] += n
                row += list(counts(agg))
            else:
                row += [None] * 3
        rows.append(row)
        hc = [conc(d[code], v.get(code, 0))[0] if code in d else None for d, v in zip(daily, vol)]
        hd = [(x[0][code][0] - x[0][code][1]) if x[0] is not None and code in x[0] else None for x in cnts]
        hist[code] = [hc, hd]
    return {"date": dates[-1], "days": dates, "win": win, "has_count": has_count,
            "cols": cols, "rows": rows, "hist": hist}


def write(data_dir, out):
    payload = build(data_dir)
    if not payload:
        return None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload["date"]
