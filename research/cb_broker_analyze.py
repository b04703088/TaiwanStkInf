#!/usr/bin/env python3
"""研究用：分析 research/data/cb_brokers.csv → 詢圈前常客分點、壓價／布局行為、事後報酬。
輸出 research/data/cb_branch_stats.csv、cb_cases_px.csv，並印出摘要。"""
import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from broker_site import FOREIGN  # noqa: E402

D = ROOT / "research" / "data"
import os
BENCH = os.environ.get("BENCH", "EW")   # EW = 等權市場指數（research/ew_index.py）；0050 會被台積電行情扭曲


def rd(p):
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def load_px(codes):
    files = sorted(p for p in (ROOT / "data").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8)
    td, close, vol = [], defaultdict(dict), defaultdict(dict)
    for p in files:
        d = f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}"
        td.append(d)
        for r in rd(p):
            if r["code"] in codes:
                try:
                    close[r["code"]][d] = float(r["close"])
                    vol[r["code"]][d] = float(r["volume"] or 0) / 1000
                except ValueError:
                    pass
    for d in list(close["0050"]):
        if d < "2025-06-18":   # 0050 2025-06 一拆四
            close["0050"][d] /= 4
    ew = ROOT / "research" / "data" / "ew_index.csv"
    if ew.exists():
        close["EW"] = {r["date"]: float(r["close"]) for r in rd(ew)}
    return td, close, vol


def binom_sf(k, n, p):
    """P(X >= k), X ~ Binomial(n, p)"""
    from math import comb
    return float(f"{sum(comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1)):.2g}")


def main():
    rows = rd(D / "cb_brokers.csv")
    cases = {c["id"]: c for c in rd(ROOT / "data" / "cb" / "cases.csv")}
    kinds = {r["bid"]: (r["broker_id"], r["broker"]) for r in rd(ROOT / "data" / "broker" / "branches.csv")}

    def kind(bid, name):
        k = kinds.get(bid)
        if k and k[1] in FOREIGN:
            return "外資"
        if k and k[0] == bid:
            return "總公司"
        if "網路" in name or "敦南" in name:
            return "網路/大型"
        return "分點"

    by = defaultdict(lambda: defaultdict(dict))   # id → win → {(side,bid): row}
    win_dates = defaultdict(dict)
    names = {}
    for r in rows:
        win_dates[r["id"]][r["win"]] = (r["d1"], r["d2"])
        if r["bid"]:
            by[r["id"]][r["win"]][(r["side"], r["bid"])] = r
            names[r["bid"]] = r["broker"]
    ids = [i for i in win_dates if "pre20" in win_dates[i] and i in cases]
    codes = {cases[i]["code"] for i in ids} | {"0050"}
    td, close, vol = load_px(codes)
    pos = {d: k for k, d in enumerate(td)}

    def px(code, d, off=0):
        k = pos.get(d)
        if k is None or not 0 <= k + off < len(td):
            return None
        return close[code].get(td[k + off])

    def ret(code, d1, d2):
        a, b = close[code].get(d1), close[code].get(d2)
        x, y = close[BENCH].get(d1), close[BENCH].get(d2)
        if not (a and b and x and y):
            return None, None
        return b / a - 1, (b / a) - (y / x)

    # ---- 個案價格 ----
    cpx = []
    for i in ids:
        c, w = cases[i], win_dates[i]
        code = c["code"]
        p1, p2 = w["pre20"]
        k1 = pos[p1]
        d_pre_start = td[k1 - 1] if k1 else p1
        rec = {"id": i, "code": code, "company": c["company"][:6], "method": c["method"], "bb_start": c["bb_start"],
               "base": c["price_base_date"], "premium": c["premium"], "prem_lo": c["premium_lo"], "issue_pct": c["issue_pct"]}
        rec["r_pre20"], rec["x_pre20"] = ret(code, d_pre_start, p2)
        if "in" in w:
            rec["r_in"], rec["x_in"] = ret(code, p2, w["in"][1])
        if "post" in w:
            rec["r_post20"], rec["x_post20"] = ret(code, w["in"][1], w["post"][1])
        v = vol[code]
        rec["vol_pre20"] = sum(v.get(td[k], 0) for k in range(pos[p1], pos[p2] + 1))
        cpx.append(rec)
    cmap = {r["id"]: r for r in cpx}

    # ---- 分點統計 ----
    N = {"詢價圈購": 0, "競價拍賣": 0}
    for i in ids:
        N[cases[i]["method"]] += 1
    # 同一檔常常同時辦詢圈＋競拍（拆兩部分），開始日相差 30 天內視為同一個事件
    ev, last = {}, {}
    for i in sorted(ids, key=lambda i: cases[i]["bb_start"]):
        code = cases[i]["code"]
        k = last.get(code)
        if k and (pos.get(win_dates[i]["pre20"][1], 0) - pos.get(k[1], 0)) <= 22:
            ev[i] = k
        else:
            ev[i] = last[code] = (code, win_dates[i]["pre20"][1])
    NE = len(set(ev.values()))
    print("事件數", NE)
    NP = len({(ev[i], pw) for i in ids for pw in ("plc1", "plc2") if pw in win_dates[i]})
    st_ = defaultdict(lambda: defaultdict(list))
    for i in ids:
        m = cases[i]["method"]
        wins = by[i]
        base_bids = {b for (_, b) in wins.get("base", {})}
        for (side, bid), r in wins.get("pre20", {}).items():
            net = float(r["net"])
            if (side == "B" and net <= 0) or (side == "S" and net >= 0):
                continue
            key = (bid, side)
            st_[key][m + "_pre"].append(i)
            if m == "詢價圈購":
                st_[key]["share"].append(abs(net) / max(cmap[i]["vol_pre20"], 1))
                st_[key]["lots"].append(abs(net))
                if bid not in base_bids:
                    st_[key]["new"].append(i)
                opp = "S" if side == "B" else "B"
                later = [wins.get(x, {}).get((opp, bid)) for x in ("in", "post")]
                if any(r2 and (float(r2["net"]) < 0 if side == "B" else float(r2["net"]) > 0) for r2 in later):
                    st_[key]["flip"].append(i)
        for (side, bid), r in wins.get("base", {}).items():
            st_[(bid, side)][m + "_base"].append(i)
        for pw in ("plc1", "plc2"):
            for (side, bid), r in wins.get(pw, {}).items():
                net = float(r["net"])
                if (side == "B" and net > 0) or (side == "S" and net < 0):
                    st_[(bid, side)][m + "_plc"].append((i, pw))

    out = []
    for (bid, side), s in st_.items():
        n_bb = len(set(s["詢價圈購_pre"]))
        if len(set(s["詢價圈購_pre"]) | set(s["競價拍賣_pre"])) < 4 or not s["share"]:
            continue
        rate_bb = n_bb / N["詢價圈購"]
        rate_au = len(set(s["競價拍賣_pre"])) / max(N["競價拍賣"], 1)
        rate_base = len(set(s["詢價圈購_base"])) / N["詢價圈購"]
        xs = [cmap[i].get("x_post20") for i in set(s["詢價圈購_pre"])]
        xs = [x for x in xs if x is not None]
        xp = [cmap[i].get("x_pre20") for i in set(s["詢價圈購_pre"])]
        xp = [x for x in xp if x is not None]
        n_all = len({ev[i] for i in set(s["詢價圈購_pre"]) | set(s["競價拍賣_pre"])})
        n_plc = len({(ev[i], w) for i, w in set(s["詢價圈購_plc"]) | set(s["競價拍賣_plc"])})
        p0 = max(n_plc / NP, 0.5 / NP)
        out.append({"bid": bid, "branch": names[bid], "kind": kind(bid, names[bid]), "side": side,
                    "n_bb": n_bb, "rate_bb": round(rate_bb, 3), "rate_au": round(rate_au, 3),
                    "rate_base_bb": round(rate_base, 3),
                    "n_all": n_all, "rate_plc": round(n_plc / NP, 3),
                    "lift_vs_plc": round(n_all / NE / p0, 2), "p_plc": binom_sf(n_all, NE, p0),
                    "p_bb_plc": binom_sf(n_bb, N["詢價圈購"], p0),
                    "lift_vs_au": round(rate_bb / rate_au, 2) if rate_au else "",
                    "n_new": len(set(s["new"])), "n_flip": len(set(s["flip"])),
                    "med_share": round(st.median(s["share"]) * 100, 2),
                    "med_lots": round(st.median(s["lots"])),
                    "x_pre20": round(st.mean(xp) * 100, 1) if xp else "",
                    "x_post20": round(st.mean(xs) * 100, 1) if xs else "",
                    "win_post20": round(sum(x > 0 for x in xs) / len(xs) * 100) if xs else "",
                    "n_post": len(xs), "codes": " ".join(sorted({cases[i]["code"] for i in s["詢價圈購_pre"]}))})
    out.sort(key=lambda r: (r["side"], -r["n_bb"]))
    cols = list(out[0].keys())
    with open(D / "cb_branch_stats.csv", "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    cc = sorted({k for r in cpx for k in r})
    with open(D / "cb_cases_px.csv", "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cc)
        w.writeheader()
        w.writerows(cpx)
    print("N", N)


if __name__ == "__main__":
    main()
