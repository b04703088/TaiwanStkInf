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
import re
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


# ---------------- 臺灣指數公司 定期審核行事曆 ----------------
def build_tip(data_dir, root):
    """data/etf/tip/schedule.csv + 追蹤 ETF 對應 → 網頁 JSON。
    ETF 對應：證交所上市 ETF 的標的指數名稱比對；config/tip_index_etf.csv（index,etf）可手動補。"""
    import sys
    sys.path.insert(0, str(Path(root)))
    from fetch_tip_schedule import match_etfs
    tip = Path(data_dir) / "etf" / "tip"
    if not (tip / "schedule.csv").exists():
        return None
    with (tip / "schedule.csv").open(encoding="utf-8") as fp:
        sched = list(csv.DictReader(fp))
    etf_rows = []
    if (tip / "etf_index.csv").exists():
        with (tip / "etf_index.csv").open(encoding="utf-8") as fp:
            etf_rows = list(csv.DictReader(fp))
    overrides = {}
    ov = Path(root) / "config" / "tip_index_etf.csv"
    if ov.exists():
        with ov.open(encoding="utf-8-sig") as fp:
            for r in csv.DictReader(fp):
                if (r.get("index") or "").strip() and (r.get("etf") or "").strip():
                    overrides.setdefault(r["index"].strip(), []).append(r["etf"].strip())
    # 名稱優先用每日行情檔的交易所簡稱（證交所 ETF 基本資料的名稱常帶「ETF基金」）
    names = {}
    pf = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    if pf:
        with pf[-1].open(encoding="utf-8") as fp:
            names = {r["code"]: r["name"] for r in csv.DictReader(fp)}
    for e in etf_rows:
        names.setdefault(e["etf"], e["name"])
    from fetch_tip_schedule import index_key
    # 定審結果：(指數, 生效日) → 納入／刪除
    results = {}
    if (tip / "results.csv").exists():
        with (tip / "results.csv").open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                g = results.setdefault((index_key(r["index"]), r["effective_date"]),
                                       {"index": r["index"], "ann": r["announce_date"], "eff": r["effective_date"],
                                        "src": r["source_id"], "add": [], "del": []})
                if r["action"] in ("add", "del"):
                    g[r["action"]].append([r["code"], names.get(r["code"]) or r["name"]])
    all_idx = sorted({r["index"] for r in sched} | {g["index"] for g in results.values()})
    mapping = match_etfs(all_idx, etf_rows, overrides)
    sources = {}
    if (tip / "sources.json").exists():
        sources = json.loads((tip / "sources.json").read_text(encoding="utf-8"))
    from datetime import date as _date
    by_idx = {}
    for k, g in results.items():
        by_idx.setdefault(k[0], []).append((k, g))

    def find_result(r):
        """同一指數、結果公告日最接近排程公告日的那一份（前 5 天～後 10 天內）。
        實際公告可能提前一兩天，或遇颱風等因素順延（日程表不另更新）。"""
        a0 = _date.fromisoformat(r["announce_date"])
        best = None
        for k, g in by_idx.get(index_key(r["index"]), []):
            if k in used_res or not g["ann"]:
                continue
            gap = (_date.fromisoformat(g["ann"]) - a0).days
            if -5 <= gap <= 10 and (best is None or abs(gap) < best[0]):
                best = (abs(gap), k, g)
        return best

    rows, used_res = [], set()
    for r in sched:
        hit = find_result(r)
        g = hit[2] if hit else None
        if hit:
            used_res.add(hit[1])
        moved = bool(g and (g["ann"] != r["announce_date"] or (g["eff"] and g["eff"] != r["effective_date"])))
        rows.append([r["index"], g["ann"] if moved else r["announce_date"], (g["eff"] or r["effective_date"]) if moved else r["effective_date"],
                     r["schedule"], r["source_id"], mapping.get(r["index"], []),
                     g["add"] if g else None, g["del"] if g else None, g["src"] if g else None,
                     [r["announce_date"], r["effective_date"]] if moved else None])
    for k, g in results.items():  # 不在日程表裡的（例如臺灣50 等合編指數）
        if k not in used_res:
            rows.append([g["index"], g["ann"], g["eff"], "", None, mapping.get(g["index"], []), g["add"], g["del"], g["src"], None])
    # 提供者：臺灣指數公司自編、富時合編（臺灣50 等，結果也由 TIP 轉公告）
    FTSE = ("臺灣50指數", "臺灣中型100指數", "臺灣資訊科技指數", "臺灣發達指數", "臺灣高股息指數", "臺灣永續指數",
            "臺灣就業99指數", "臺灣高薪100指數")
    for r in rows:
        r.append("FTSE" if any(index_key(r[0]) == index_key(f) for f in FTSE) or "富時" in r[0] else "TIP")
    rows += msci_rows(data_dir, names, etf_rows)
    used = sorted({c for r in rows for c in r[5]})
    updated = max((v.get("file_date", "") for v in sources.values()), default="")
    return {"updated": updated, "cols": ["index", "ann", "eff", "sched", "src", "etfs", "add", "del", "rsrc", "orig", "prov"], "rows": rows,
            "etfs": {c: names.get(c, "") for c in used},
            "pdf": "https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/{}/tw"}


def msci_rows(data_dir, names, etf_rows):
    """MSCI Taiwan Index 季度審核（fetch_msci.py）→ 與 TIP 行事曆相同格式的列。"""
    d = Path(data_dir) / "etf" / "msci"
    import html as _html
    etfs = sorted({e["etf"] for e in etf_rows
                   if re.sub(r"\s+", "", _html.unescape(e["index"])).replace("®", "").upper() in ("MSCI臺灣指數", "MSCI台灣指數")})
    label = "MSCI 臺灣指數（MSCI Taiwan Index）"
    pdf = "https://app2.msci.com/eqb/gimi/stdindex/MSCI_{}_STPublicList.pdf"
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    groups = {}
    if (d / "results.csv").exists():
        with (d / "results.csv").open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                g = groups.setdefault(r["review"], {"ann": r["announce_date"], "eff": r["effective_date"], "add": [], "del": []})
                if r["action"] in ("add", "del"):
                    g[r["action"]].append([r["code"], names.get(r["code"], "") or r["en_name"], r["en_name"]])
    out = []
    for review, g in sorted(groups.items()):
        y, m = review.split("-")
        out.append([label, g["ann"], g["eff"], "MSCI", None, etfs, g["add"], g["del"],
                    pdf.format(f"{mon[int(m) - 1]}{y[2:]}"), None, "MSCI"])
    if (d / "schedule.csv").exists():
        with (d / "schedule.csv").open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                if r["review"] not in groups:
                    out.append([label, r["announce_date"], r["effective_date"], "MSCI", None, etfs, None, None, None, None, "MSCI"])
    return out


def write_tip(data_dir, root, out_path):
    payload = build_tip(data_dir, root)
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
