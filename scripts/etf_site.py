"""把 data/etf/ 的每日持股整理成網頁用的 JSON：最新一份持股 + 與該 ETF 前一份持股的股數差異。

每檔 ETF 各自與「自己的前一份」持股比較（各投信公告進度不同，同一天不一定都有資料）。
差異是原始股數增減（含申購贖回造成的同比例增減），不做任何過濾。
只公布權重、不公布股數的投信（國泰），股數為 null，只判斷新增／剔除；
權重變動可能只是股價漲跌，不當成買賣。

輸出 data/etf/latest.json：
  etfs: [{code, name, issuer, kind, date, prev, aum, units, prev_units}]
  cols: ["e", "code", "name", "sh", "w", "psh", "pw", "px", "cls", "d"]
  rows: 每列一檔（ETF × 成分股），e 是 etfs 的索引；
        sh / w:   最新股數、權重（剔除者為 0；投信未公布股數為 null）
        psh / pw: 前一份股數、權重（新增者為 0；沒有前一份為 null）
        cls: new 新增 / removed 剔除 / add 增加 / cut 減少 / same 不變 /
             nw 續抱但未公布股數（無法判斷增減）/ null 沒有前一份可比
        d:   股數增減 = sh − psh
        px:  該 ETF 資料日的收盤價（剔除者用前一份資料日；海外股、查無價格為 null）
"""
import csv
import json
from pathlib import Path

COLS = ["e", "code", "name", "sh", "w", "psh", "pw", "px", "cls", "d"]


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


def classify(prev, cur):
    """prev / cur：該成分股在前一份 / 最新持股中的資料（dict），不在持股中為 None。
    回傳 (類別, 股數增減)；股數未公布時增減為 None。"""
    if prev is None:
        return "new", cur["sh"]
    if cur is None:
        return "removed", (-prev["sh"] if prev["sh"] is not None else None)
    if prev["sh"] is None or cur["sh"] is None:
        return "nw", None
    d = cur["sh"] - prev["sh"]
    if d == 0:
        return "same", 0
    return ("add" if d > 0 else "cut"), d


class PriceBook:
    """收盤價查詢：{日期: {代號: 收盤價}}，該日沒有行情檔就用之前最近一天。"""

    def __init__(self, data_dir):
        self.files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
        self.cache = {}

    def get(self, d):
        if not d:
            return {}
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
        s1, s0 = summary.get((d1, code), {}), (summary.get((d0, code), {}) if d0 else {})
        e = len(etfs)
        etfs.append({"code": code, "name": info["name"], "issuer": info["issuer_name"], "kind": info["kind"],
                     "date": d1, "prev": d0, "aum": _num(s1.get("aum")),
                     "units": _num(s1.get("units")), "prev_units": _num(s0.get("units"))})
        px1, px0 = prices.get(d1), prices.get(d0)
        for c in sorted(set(cur) | set(prev or {}), key=lambda c: -((cur.get(c) or {}).get("w") or 0)):
            a, b = (prev or {}).get(c), cur.get(c)
            if prev is None:
                cls, d = None, None
            else:
                cls, d = classify(a, b)
            ref = b or a
            rows.append([e, c, ref["name"],
                         b["sh"] if b else 0, b["w"] if b else 0,
                         (a["sh"] if a else 0) if prev is not None else None,
                         (a["w"] if a else 0) if prev is not None else None,
                         px1.get(c) if b else px0.get(c), cls, d])
    return {"etfs": etfs, "cols": COLS, "rows": rows}


def write_latest(data_dir, out_path):
    payload = build_latest(data_dir)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


# ---------------- AUM 排行 ----------------
AUM_COLS = ["etf", "name", "cat", "aum", "nav", "units", "du", "flow", "flow5", "daum", "prem", "tracked"]


def build_aum(data_dir, flow_days=5):
    """data/etf/aum/ 最新一天 → 排行資料；另算較前一份的規模變化、近 N 份的資金流入合計。

    flow5 只加總「實際有的」日檔（最多 flow_days 份），n_flow 告訴前端是幾天。
    """
    data_dir = Path(data_dir)
    files = sorted((data_dir / "etf" / "aum").glob("[0-9]*.csv"))
    if not files:
        return None

    def read(f):
        with f.open(encoding="utf-8") as fp:
            return {r["etf"]: r for r in csv.DictReader(fp)}

    latest, prev = read(files[-1]), (read(files[-2]) if len(files) > 1 else {})
    recent = [read(f) for f in files[-flow_days:]]
    tracked = set()
    lst = data_dir / "etf" / "etf_list.csv"
    if lst.exists():
        with lst.open(encoding="utf-8") as fp:
            tracked = {r["etf"] for r in csv.DictReader(fp)}
    rows = []
    for code, r in latest.items():
        aum = _num(r["aum"])
        p = prev.get(code)
        flow5 = sum(_num(day[code]["flow"]) or 0 for day in recent if code in day)
        rows.append([code, r["name"], r["category"], aum, _num(r["nav"]), _num(r["units"]),
                     _num(r["units_change"]), _num(r["flow"]), flow5,
                     (aum - _num(p["aum"])) if p else None, _num(r["premium"]), code in tracked])
    rows.sort(key=lambda x: -(x[3] or 0))
    return {"date": date_of(files[-1]), "prev": date_of(files[-2]) if len(files) > 1 else None,
            "n_flow": len(recent), "cols": AUM_COLS, "rows": rows}


def write_aum(data_dir, out_path):
    payload = build_aum(data_dir)
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
