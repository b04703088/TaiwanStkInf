"""把 data/etf/ 的每日持股整理成網頁用的 JSON：最新一份持股 + 與該 ETF 前一份持股的差異。

每檔 ETF 各自與「自己的前一份」持股比較（各投信公告進度不同，同一天不一定都有資料）。

被動式 ETF 每天都有申購贖回，所有成分股股數會同比例增減；這不是經理人換股。
因此先算出「申購贖回倍率」k：
  - 有流通單位數 → k = 今日單位數 / 前一份單位數
  - 沒有 → 取所有續抱成分股「今日股數 / 前一份股數」的中位數（大多數成分股只隨申購贖回變動）
每檔成分股的「主動調整股數」= 今日股數 − 前一份股數 × k。
調整幅度小於前一份股數的 FLOW_TOLERANCE（0.2%，或不到 1 張）視為申購贖回連動。

輸出 data/etf/latest.json：
  etfs: [{code, name, issuer, kind, date, prev, aum, units, prev_units, k, k_source}]
  cols: ["e", "code", "name", "sh", "w", "psh", "pw", "px", "cls", "adj"]
  rows: 每列一檔（ETF × 成分股），e 是 etfs 的索引；
        cls: new 新增 / removed 剔除 / add 加碼 / cut 減碼 / flow 申購贖回連動 / same 不變 / null 無前一份
        adj: 主動調整股數（新增 = 今日股數，剔除 = −前一份股數）
        px:  該 ETF 資料日的收盤價（海外股、查無價格為 null）
"""
import csv
import json
import statistics
from pathlib import Path

FLOW_TOLERANCE = 0.002   # 0.2%：實測被動式 ETF 的申購贖回誤差在 0.1% 以內
MIN_LOT = 1000           # 1 張

COLS = ["e", "code", "name", "sh", "w", "psh", "pw", "px", "cls", "adj"]


def _num(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def read_holdings(path):
    with open(path, encoding="utf-8") as fp:
        return {r["code"]: {"name": r["name"], "sh": _num(r["shares"]), "w": _num(r["weight"])}
                for r in csv.DictReader(fp)}


def date_of(path):
    s = Path(path).stem
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def flow_ratio(prev, cur, units_prev, units_cur):
    """回傳 (k, 來源)。"""
    if units_prev and units_cur:
        return units_cur / units_prev, "units"
    ratios = [cur[c]["sh"] / prev[c]["sh"] for c in cur
              if c in prev and cur[c]["sh"] and prev[c]["sh"]]
    if len(ratios) >= 5:
        return statistics.median(ratios), "median"
    return 1.0, None


def classify(prev_sh, cur_sh, k):
    """回傳 (類別, 主動調整股數)。prev_sh / cur_sh 為 None 表示不在該份持股中。"""
    if prev_sh is None:
        return "new", cur_sh or 0
    if cur_sh is None:
        return "removed", -(prev_sh or 0)
    if cur_sh == prev_sh:
        return "same", 0
    adj = cur_sh - prev_sh * k
    if abs(adj) < max(prev_sh * FLOW_TOLERANCE, MIN_LOT):
        return "flow", 0
    return ("add" if adj > 0 else "cut"), round(adj)


class PriceBook:
    """收盤價查詢：{日期: {代號: 收盤價}}，該日沒有行情檔就用之前最近一天。"""

    def __init__(self, data_dir):
        self.files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
        self.cache = {}

    def get(self, d):
        if d not in self.cache:
            target = d.replace("-", "") + ".csv"
            f = next((f for f in reversed(self.files) if f.name <= target), None)
            prices = {}
            if f:
                with f.open(encoding="utf-8") as fp:
                    prices = {r["code"]: float(r["close"]) for r in csv.DictReader(fp) if r.get("close")}
            self.cache[d] = prices
        return self.cache[d]


def build_latest(data_dir):
    data_dir = Path(data_dir)
    etf_dir = data_dir / "etf"
    summary = {}
    if (etf_dir / "summary.csv").exists():
        with (etf_dir / "summary.csv").open(encoding="utf-8") as fp:
            summary = {(r["date"], r["etf"]): r for r in csv.DictReader(fp)}
    with (etf_dir / "etf_list.csv").open(encoding="utf-8") as fp:
        etf_list = list(csv.DictReader(fp))

    prices = PriceBook(data_dir)
    etfs, rows = [], []
    for info in etf_list:
        code = info["etf"]
        files = sorted((etf_dir / code).glob("[0-9]*.csv"))
        if not files:
            continue
        d1 = date_of(files[-1])
        cur = read_holdings(files[-1])
        d0 = date_of(files[-2]) if len(files) > 1 else None
        prev = read_holdings(files[-2]) if d0 else None
        s1, s0 = summary.get((d1, code), {}), summary.get((d0, code), {}) if d0 else {}
        u1, u0 = _num(s1.get("units")), _num(s0.get("units"))
        k, k_src = flow_ratio(prev, cur, u0, u1) if prev else (None, None)
        e = len(etfs)
        etfs.append({"code": code, "name": info["name"], "issuer": info["issuer_name"], "kind": info["kind"],
                     "date": d1, "prev": d0, "aum": _num(s1.get("aum")), "units": u1, "prev_units": u0,
                     "k": round(k, 6) if k else None, "k_source": k_src})
        px1 = prices.get(d1)
        px0 = prices.get(d0) if d0 else {}
        for c in sorted(set(cur) | set(prev or {}), key=lambda c: -((cur.get(c) or {}).get("w") or 0)):
            a, b = (prev or {}).get(c), cur.get(c)
            if prev is None:
                cls, adj = None, None
            else:
                cls, adj = classify(a["sh"] if a else None, b["sh"] if b else None, k)
            ref = b or a
            rows.append([e, c, ref["name"],
                         b["sh"] if b else 0, b["w"] if b else 0,
                         a["sh"] if a else (None if prev is None else 0), a["w"] if a else (None if prev is None else 0),
                         px1.get(c) if b else px0.get(c), cls, adj])
    return {"etfs": etfs, "cols": COLS, "rows": rows}


def write_latest(data_dir, out_path):
    payload = build_latest(data_dir)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
