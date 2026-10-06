"""族群資金流向（成交熱度）→ 網頁用 data/flow.json

只放「原料」，佔比、熱度、增減金額由網頁依選的日期與比較基準計算：
  days:   最近 DAYS 個交易日
  names:  {代號: 名稱}
  vals:   {代號: [每日成交金額（百萬元，整數）...]}   只含上市櫃普通股（不含 ETF、權證）
  groups: {"sub": [[名稱, 路徑, [代號...]], ...],    產業價值鏈細類
           "ind": [...],                            產業價值鏈產業（47 個）
           "off": [...]}                            證交所／櫃買官方產業別
"""
import csv
import json
import re
from pathlib import Path

import industry_site

DAYS = 45
STOCK = re.compile(r"^[1-9]\d{3}$")


def _price_files(data_dir, n):
    files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    return [f for f in files if len(f.stem) == 8][-n:]


def build(data_dir, days=DAYS):
    ind = industry_site.build(data_dir)
    files = _price_files(data_dir, days)
    if not ind or not files:
        return None
    dates, vals, names = [], {}, {}
    for k, f in enumerate(files):
        with f.open(encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
        if not rows:
            continue
        dates.append(rows[0]["date"])
        for r in rows:
            c = r["code"]
            if not STOCK.match(c):
                continue
            try:
                v = float(r["value"] or 0)
            except ValueError:
                v = 0.0
            names[c] = r["name"]
            vals.setdefault(c, [0] * len(files))[k] = int(round(v / 1e6))
    n = len(dates)
    vals = {c: v[:n] for c, v in vals.items() if any(v[:n])}

    def keep(codes):
        return sorted({c for c in codes if c in vals})

    sub = []
    members = {}
    for code, s in ind["stocks"].items():
        for i in s[2]:
            members.setdefault(i, []).append(code)
    for i, node in enumerate(ind["nodes"]):
        codes = keep(members.get(i, []))
        if codes:
            label = node[3] or node[2]
            path = " › ".join(x for x in (node[0], node[1], node[2] if node[3] else "") if x)
            sub.append([label, path, codes])
    by_ind, by_off = {}, {}
    for i, node in enumerate(ind["nodes"]):
        by_ind.setdefault(node[0], set()).update(members.get(i, []))
    for code, s in ind["stocks"].items():
        if s[1]:
            by_off.setdefault(s[1], set()).add(code)
    groups = {
        "sub": sub,
        "ind": [[k, "產業價值鏈", keep(v)] for k, v in by_ind.items() if keep(v)],
        "off": [[k, "官方產業別", keep(v)] for k, v in by_off.items() if keep(v) and k not in ("存託憑證", "管理股票")],
    }
    return {"days": dates, "names": {c: names[c] for c in vals}, "vals": vals, "groups": groups}


def write_flow(data_dir, out_path, days=DAYS):
    payload = build(data_dir, days)
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
