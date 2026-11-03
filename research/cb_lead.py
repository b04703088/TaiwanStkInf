#!/usr/bin/env python3
"""研究用：CB 詢圈案依主辦券商分組，各流程階段的現股超額報酬（等權市場指數）。
組間差異用置換檢定（該券商 vs 其他券商的中位數差），重抽 5000 次。"""
import bisect, csv, random, statistics as st, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))
import cb_broker_analyze as A  # noqa: E402
import cb_f10  # noqa: E402

ids = cb_f10.json_ids()
cases = [c for c in A.rd(ROOT / "data" / "cb" / "cases.csv") if c["id"] in ids]
td, close, _ = A.load_px({c["code"] for c in cases})
ew = close["EW"]


def k_of(d):
    return bisect.bisect_left(td, d) if d else None


def ret(code, a, b):
    if a is None or b is None or b <= a or b >= len(td) or a < 0:
        return None
    da, db = td[a], td[b]
    cl = close[code]
    if da in cl and db in cl and da in ew and db in ew:
        return (cl[db] / cl[da] - ew[db] / ew[da]) * 100
    return None


SEG = [("決議前20日→決議", lambda c, k: (k["b"] - 20 if k["b"] else None, k["b"])),
       ("決議→送件", lambda c, k: (k["b"], k["f"])),
       ("送件→生效", lambda c, k: (k["f"], k["e"])),
       ("生效→詢圈", lambda c, k: (k["e"], k["s"])),
       ("詢圈→訂價", lambda c, k: (k["s"], k["p"])),
       ("訂價→掛牌", lambda c, k: (k["p"], k["l"])),
       ("掛牌後20日", lambda c, k: (k["l"], k["l"] + 20 if k["l"] is not None else None)),
       ("決議→掛牌", lambda c, k: (k["b"], k["l"]))]

short = lambda s: s.replace("綜合證券股份有限公司", "").replace("證券股份有限公司", "").replace("金鼎", "")  # noqa: E731
data = {}
for c in cases:
    k = {"b": k_of(c["board_date"]), "f": k_of(c["filed_date"]), "e": k_of(c["eff_date"]), "s": k_of(c["bb_start"]),
         "p": k_of(c["done_date"] or c["bb_end"]), "l": k_of(c["list_date"])}
    data[c["id"]] = (short(c["lead"]), {n: ret(c["code"], *f(c, k)) for n, f in SEG})

random.seed(1)
leads = [l for l, n in __import__("collections").Counter(v[0] for v in data.values()).most_common() if n >= 8]
print(f"樣本 {len(data)} 件；券商 ≥8 件：{leads}")
for seg, _ in SEG:
    allv = [(v[0], v[1][seg]) for v in data.values() if v[1][seg] is not None]
    print(f"\n{seg}（全體 {len(allv)} 件，中位 {st.median(x for _, x in allv):+.1f}%）")
    for L in leads:
        a = [x for l, x in allv if l == L]
        b = [x for l, x in allv if l != L]
        if len(a) < 5:
            continue
        obs = st.median(a) - st.median(b)
        xs = [x for _, x in allv]
        cnt = 0
        for _ in range(5000):
            random.shuffle(xs)
            if abs(st.median(xs[:len(a)]) - st.median(xs[len(a):])) >= abs(obs):
                cnt += 1
        print(f"  {L}\t{len(a)}件\t中位 {st.median(a):+.1f}%\t上漲比 {sum(x>0 for x in a)/len(a)*100:.0f}%\t差 {obs:+.1f}\tp={cnt/5000:.3f}")
