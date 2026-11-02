#!/usr/bin/env python3
"""把研究結果整理成網站用的靜態 JSON：research/data/cb_regulars.json

  regulars  config/cb_regulars.csv 每個分點：訂價前出現事件數、各階段進場次數、每件金額中位數、
            掛牌（基準日）後 20 日超額報酬、活躍期間、歷史案件清單
  只統計有詢圈的案件（同檔同時詢圈＋競拍算詢圈；純競拍不列入，Leo 2026-11-02）
  stages    詢圈各流程階段的累積超額報酬（等權市場指數，起點 = 董事會決議前 21 個交易日）
先跑 research/ew_index.py、research/cb_broker_analyze.py。
"""
import bisect
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "scripts"))
import cb_broker_analyze as A  # noqa: E402

STAGES = ["s0", "s1", "s2", "s3", "s4"]
STAGE_LAB = {"s0": "決議前20日", "s1": "決議→送件", "s2": "送件→生效", "s3": "生效→詢圈", "s4": "詢圈→訂價"}


def regulars_stats(rows, cases, px, close):
    by = defaultdict(lambda: defaultdict(dict))
    wd = defaultdict(dict)
    for r in rows:
        wd[r["id"]][r["win"]] = (r["d1"], r["d2"])
        if r["bid"]:
            by[r["id"]][r["win"]][(r["side"], r["broker"])] = int(r["net"])

    def avgp(code, d1, d2):
        v = [p for d, p in close.get(code, {}).items() if d1 <= d <= d2]
        return st.mean(v) if v else None

    # 有詢圈的事件（同檔同一次董事會決議只要有一件是詢圈就算）
    bbk = {(c["code"], c["board_date"] or c["bb_start"][:7]) for c in cases.values() if c["method"] == "詢價圈購"}
    out = []
    for g in A.rd(ROOT / "config" / "cb_regulars.csv"):
        name, side = g["broker"], g["side"]
        sign = 1 if side == "B" else -1
        seen, items = set(), []
        for i in sorted(wd, key=lambda i: cases[i]["bb_start"]):
            c = cases[i]
            nets = {s: by[i][s].get((side, name)) for s in STAGES if s in wd[i]}
            hit = [s for s in STAGES if nets.get(s) is not None and nets[s] * sign > 0]
            key = (c["code"], c["board_date"] or c["bb_start"][:7])
            if not hit or key in seen or key not in bbk:
                continue
            seen.add(key)
            lots = sum(nets[s] for s in hit)
            d1, d2 = wd[i][hit[0]][0], wd[i][hit[-1]][1]
            p = avgp(c["code"], d1, d2)
            x = px.get(i, {}).get("x_post20")
            items.append({"date": c["bb_start"], "code": c["code"], "name": c["short"] or c["company"][:4],
                          "entry": hit[0],
                          "lots": lots, "amt": round(abs(lots) * p / 100) / 10 if p else None,  # 百萬元
                          "post": round(float(x) * 1000) / 10 if x else None})
        posts = [it["post"] for it in items if it["post"] is not None]
        amts = [it["amt"] for it in items if it["amt"] is not None]
        out.append({"broker": name, "side": side, "tier": g["tier"], "note": g["note"], "n": len(items),
                    "entry": {s: sum(1 for it in items if it["entry"] == s) for s in STAGES},
                    "amt_med": round(st.median(amts), 1) if amts else None,
                    "amt_sum": round(sum(amts) / 100, 2) if amts else None,   # 億元
                    "post_med": round(st.median(posts), 1) if posts else None,
                    "post_win": sum(1 for x in posts if x > 0), "post_n": len(posts),
                    "first": items[0]["date"] if items else None, "last": items[-1]["date"] if items else None,
                    "cases": items[::-1]})
    return out


def stage_table(cases, td, close):
    marks = [("b20", "董事會決議前 20 日"), ("board_date", "董事會決議"), ("filed_date", "送件申報"),
             ("eff_date", "申報生效"), ("bb_start", "詢圈開始"), ("done_date", "訂價日"),
             ("price_base_date", "轉換價格基準日"), ("pay_date", "繳款截止"), ("list_date", "掛牌"),
             ("list20", "掛牌後 20 日"), ("list40", "掛牌後 40 日")]
    ew = close["EW"]
    res = {}
    for m in ("詢價圈購",):
        acc = {k: ([], []) for k, _ in marks}
        for c in cases:
            if c["method"] != m or not c["board_date"] or not c["bb_start"]:
                continue
            kb = bisect.bisect_left(td, c["board_date"])
            if kb < 21 or kb >= len(td):
                continue
            ref, cl = td[kb - 21], close.get(c["code"], {})
            if ref not in cl or ref not in ew:
                continue
            for k, _ in marks:
                if k == "b20":
                    j = kb - 20
                elif k in ("list20", "list40"):
                    if not c["list_date"]:
                        continue
                    j = bisect.bisect_left(td, c["list_date"]) + int(k[4:])
                elif c.get(k):
                    j = bisect.bisect_left(td, c[k])
                else:
                    continue
                if not 0 <= j < len(td):
                    continue
                d = td[j]
                if d in cl and d in ew:
                    acc[k][0].append(cl[d] / cl[ref] - ew[d] / ew[ref])
                    acc[k][1].append(j - kb)
        res[m] = acc
    out = []
    for k, lab in marks:
        row = {"stage": lab}
        for m, tag in (("詢價圈購", "bb"),):
            v, off = res[m][k]
            if len(v) >= 10:
                row[tag] = {"off": round(st.median(off)), "x": round(st.median(v) * 1000) / 10,
                            "up": round(sum(x > 0 for x in v) / len(v) * 100), "n": len(v)}
        out.append(row)
    return out


def main():
    rows = A.rd(ROOT / "research" / "data" / "cb_brokers.csv")
    cases = {c["id"]: c for c in A.rd(ROOT / "data" / "cb" / "cases.csv")}
    px = {r["id"]: r for r in A.rd(ROOT / "research" / "data" / "cb_cases_px.csv")}
    codes = {c["code"] for c in cases.values()}
    td, close, _ = A.load_px(codes)
    bb_ids = {i for i, c in cases.items() if (c["code"], c["board_date"] or c["bb_start"][:7]) in
              {(x["code"], x["board_date"] or x["bb_start"][:7]) for x in cases.values() if x["method"] == "詢價圈購"}}
    data = {"regulars": regulars_stats(rows, cases, px, close),
            "stages": stage_table([c for c in cases.values() if c["method"] == "詢價圈購"], td, close),
            "stage_labels": STAGE_LAB,
            "sample": {"from": min(c["bb_start"] for c in cases.values() if c["bb_start"]),
                       "to": max(r["d2"] for r in rows), "events": len({(cases[r["id"]]["code"], cases[r["id"]]["board_date"] or cases[r["id"]]["bb_start"][:7])
                                     for r in rows if r["id"] in bb_ids})}}
    p = ROOT / "research" / "data" / "cb_regulars.json"
    p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for g in data["regulars"]:
        print(g["broker"], g["side"], g["n"], g["entry"], g["amt_med"], g["post_med"], g["post_win"], g["post_n"])


if __name__ == "__main__":
    main()
