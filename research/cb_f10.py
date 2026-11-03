#!/usr/bin/env python3
"""研究用：送件前 10 個交易日，常出現在前 15 大買超的分點。
對照：同檔送件前 50～41、90～81 個交易日（同長度 10 日）。二項檢定＋Bonferroni。
只看有詢圈的案件（同 cb_site_static 的樣本），重新詢圈（retry_of）不重複算。
用法：python research/cb_f10.py [B|S]
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))
from cb_broker_analyze import binom_sf, rd  # noqa: E402

SIDE = sys.argv[1] if len(sys.argv) > 1 else "B"


def main():
    regs = json_ids()
    rows = [r for r in rd(ROOT / "research" / "data" / "cb_brokers.csv")
            if r["win"] in ("f10", "f10c1", "f10c2") and r["id"] in regs]
    have = defaultdict(set)          # win → ids 有查
    hit = defaultdict(lambda: defaultdict(set))   # bid → win → ids
    amt = defaultdict(list)
    names = {}
    for r in rows:
        have[r["win"]].add(r["id"])
        if r["side"] != SIDE or not r["bid"]:
            continue
        hit[r["bid"]][r["win"]].add(r["id"])
        names[r["bid"]] = r["broker"]
        if r["win"] == "f10":
            amt[r["bid"]].append(abs(int(float(r["net"] or 0))))
    ids = have["f10"] & have["f10c1"] & have["f10c2"]
    n = len(ids)
    print(f"樣本 {n} 件（送件前 10 日＋兩段對照都有）")
    out = []
    for bid, w in hit.items():
        k = len(w["f10"] & ids)
        c = (len(w["f10c1"] & ids) + len(w["f10c2"] & ids)) / 2
        if k < 4:
            continue
        p0 = max(c, 0.5) / n
        pv = binom_sf(k, n, p0)
        amt_sorted = sorted(amt[bid])
        out.append((pv, names[bid], k, c, amt_sorted[len(amt_sorted) // 2]))
    m = len(hit)
    out.sort()
    print(f"分點 {m} 個；Bonferroni 門檻 p < {0.05 / m:.1e}")
    for pv, nm, k, c, med in out[:25]:
        flag = "★" if pv < 0.05 / m else ""
        print(f"{nm}\t送件前10日 {k} 件\t對照 {c:.1f} 件\t中位張數 {med}\tp={pv:.1e} {flag}")


def json_ids():
    """2025 年起有詢圈、非重新詢圈的案件；同檔同一送件日只算一件"""
    seen, ids = set(), set()
    for c in rd(ROOT / "data" / "cb" / "cases.csv"):
        if c["method"] != "詢價圈購" or c.get("retry_of") or (c["bb_start"] or "") < "2025-01-01" or not c["filed_date"]:
            continue
        key = (c["code"], c["filed_date"])
        if key not in seen:
            seen.add(key)
            ids.add(c["id"])
    return ids


if __name__ == "__main__":
    main()
