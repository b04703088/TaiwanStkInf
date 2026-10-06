"""data/industry/ → 網頁用 data/industry/industry.json

  industries: 產業清單（櫃買平台上的順序）
  nodes:  [[產業, 上中下游, 類別, 細類, 類別全名], ...]   （細類空白＝類別本身沒有再細分）
  stocks: {代號: [名稱, 官方產業別, [nodes 索引...]]}
"""
import csv
import json
import re
from pathlib import Path


def short(name):
    """「無線通訊設備(如行動電話、衛星定位系統…)」→「無線通訊設備」"""
    s = re.sub(r"[(（](?:如|例如|含|包括)[^)）]*[)）]", "", name or "").strip()
    return s or (name or "")


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def build(data_dir):
    d = Path(data_dir) / "industry"
    chain, off = _read(d / "chain.csv"), _read(d / "official.csv")
    if not chain and not off:
        return None
    nodes, idx, stocks = [], {}, {}
    for r in off:
        stocks[r["code"]] = [r["name"], r["industry"], []]
    for r in chain:
        key = (r["industry"], r["stream"], short(r["node"]), short(r["sub"]))
        if key not in idx:
            idx[key] = len(nodes)
            nodes.append([*key, r["node"] if short(r["node"]) != r["node"] else ""])
        s = stocks.setdefault(r["code"], [r["name"], "", []])
        if not s[0]:
            s[0] = r["name"]
        if idx[key] not in s[2]:
            s[2].append(idx[key])
    gen, order = None, []
    if (d / "sources.json").exists():
        src = json.loads((d / "sources.json").read_text(encoding="utf-8"))
        gen, order = src.get("generated"), list(src.get("industries") or {})
    inds = [i for i in order if any(n[0] == i for n in nodes)]
    inds += sorted({n[0] for n in nodes} - set(inds))
    return {"generated": gen, "industries": inds, "nodes": nodes, "stocks": stocks}


def write_industry(data_dir, out_path):
    payload = build(data_dir)
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
