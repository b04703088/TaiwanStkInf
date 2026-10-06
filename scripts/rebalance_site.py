"""data/etf/rebalance/events.csv → 網頁用 data/etf/rebalance.json

  etfs: [{etf, name, issuer, index, hist(可回推歷史), n(定期調整次數), days/start/end(中位數),
          events: [[開始, 結束, 時長, 生效日, 開始差, 結束差, 新增數, 刪除數, 類型, 新增代號, 刪除代號], ...]}]
  names: {股票代號: 名稱}
  類型：regular＝定期調整（同時有新增與刪除，或異動 3 檔以上）；adhoc＝臨時（只刪或只加 1～2 檔，例如下市、合併）
"""
import csv
import json
import re
from pathlib import Path
from statistics import median_low as median

HIST_ISSUERS = {"yuanta", "cathay", "capital", "fuhhwa", "ctbc", "president", "nomura", "uob", "firstsec", "allianz", "esun"}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build(root):
    root = Path(root)
    p = root / "data" / "etf" / "rebalance" / "events.csv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as fp:
        evs = list(csv.DictReader(fp))
    src = (root / "fetch_etf.py").read_text(encoding="utf-8")
    reg = [m for m in re.findall(r'\("(\w+)",\s*"([^"]+)",\s*"(\w+)",\s*"(\w+)"\)', src) if m[3] == "passive"]
    idx = {}
    ip = root / "data" / "etf" / "tip" / "etf_index.csv"
    if ip.exists():
        with ip.open(encoding="utf-8") as fp:
            idx = {r["etf"]: r["index"] for r in csv.DictReader(fp)}
    # 股票名稱：從回推的持股與每日持股取
    names = {}
    for f in (root / "data" / "etf" / "rebalance" / "holdings").glob("*.csv"):
        with f.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                names.setdefault(r["code"], r["name"])
    codes = {m[0] for m in reg}
    for d in (root / "data" / "etf").glob("*/[0-9]*.csv"):
        if len(d.stem) != 8 or d.parent.name not in codes:
            continue
        with d.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                if r.get("code"):
                    names.setdefault(r["code"], r.get("name", ""))
    by = {}
    for e in evs:
        by.setdefault(e["etf"], []).append(e)
    out, used = [], set()
    for code, name, issuer, _ in reg:
        rows = []
        for e in sorted(by.get(code, []), key=lambda e: e["start"]):
            na, nd = _int(e["n_add"]) or 0, _int(e["n_del"]) or 0
            kind = "regular" if (na and nd) or na + nd >= 3 else "adhoc"
            adds, dels = e["adds"].split(), e["dels"].split()
            used.update(adds + dels)
            rows.append([e["start"], e["end"], _int(e["days"]), e["effective"] or None, _int(e["start_off"]),
                         _int(e["end_off"]), na, nd, kind, adds, dels])
        reg_ev = [r for r in rows if r[8] == "regular"]
        offs = [r for r in reg_ev if r[4] is not None]
        out.append({"etf": code, "name": name, "issuer": issuer, "index": idx.get(code, ""),
                    "hist": issuer in HIST_ISSUERS, "n": len(reg_ev),
                    "days": median([r[2] for r in reg_ev]) if reg_ev else None,
                    "start": median([r[4] for r in offs]) if offs else None,
                    "end": median([r[5] for r in offs]) if offs else None,
                    "events": rows})
    return {"etfs": out, "names": {c: names.get(c, "") for c in sorted(used)}}


def write_rebalance(root, out_path):
    payload = build(root)
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
