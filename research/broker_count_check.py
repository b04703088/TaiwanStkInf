"""驗證 fetch_broker_count.py 的近似家數：跟前 15 大（fetch_broker.py）比對涵蓋率。
用法：python research/broker_count_check.py 2026-11-10"""
import csv, gzip, sys, statistics as st
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
date = sys.argv[1]; s = date.replace("-", "")
raw = list(csv.DictReader(gzip.open(ROOT / f"data/broker/count/{date[:4]}/{s}_raw.csv.gz", "rt", encoding="utf-8")))
net = {(r["bid"], r["code"]): int(r["net"]) for r in raw if r["code"]}
caps = {}
nrows = defaultdict(int)
for r in raw:
    caps[r["bid"]] = r["capped"]; nrows[r["bid"]] += 1
print("分點數", len(caps), "滿50(買)", sum("B" in c for c in caps.values()), "滿50(賣)", sum("S" in c for c in caps.values()))
top = list(csv.DictReader(open(ROOT / f"data/broker/{date[:4]}/{s}.csv", encoding="utf-8")))
hit = tot = 0; whit = wtot = 0; miss = defaultdict(int)
for r in top:
    k = (r["bid"], r["code"]); n = int(r["net"])
    ok = k in net and (net[k] > 0) == (n > 0)
    tot += 1; hit += ok; wtot += abs(n); whit += abs(n) * ok
    if not ok: miss[r["broker"]] += 1
print(f"前15大分點出現在全分點掃描：{hit}/{tot} = {hit/tot:.1%}；以張數加權 {whit/wtot:.1%}")
print("漏掉最多的分點：", sorted(miss.items(), key=lambda x: -x[1])[:15])
cnt = {r["code"]: r for r in csv.DictReader(open(ROOT / f"data/broker/count/{date[:4]}/{s}.csv", encoding="utf-8"))}
tot15 = {r["code"]: r for r in csv.DictReader(open(ROOT / f"data/broker/{date[:4]}/{s}_total.csv", encoding="utf-8"))}
px = {r["code"]: r for r in csv.DictReader(open(ROOT / f"data/{date[:4]}/{s}.csv", encoding="utf-8"))}
bal = []
for c, r in cnt.items():
    b, se = int(r["buy_sh"]), int(r["sell_sh"])
    if b + se > 200: bal.append(min(b, se) / max(b, se))
print(f"買賣淨張數平衡（全分點應 =1）中位數 {st.median(bal):.2f}，P10 {sorted(bal)[len(bal)//10]:.2f}，n={len(bal)}")
# 前15大合計 vs 掃到的合計
cov = []
for c, t in tot15.items():
    if c in cnt and t["buy_total"]:
        bt = float(t["buy_total"]); 
        if bt > 0: cov.append(int(cnt[c]["buy_sh"]) / bt)
print(f"掃到的買超淨張數 ÷ 前15大買超合計 中位數 {st.median(cov):.2f}（應 ≥1）")
for c in ["2330", "2317", "2454", "3231", "2603", "6669", "8046", "3017", "2383", "1513"]:
    if c in cnt:
        r = cnt[c]; print(c, px.get(c, {}).get("name", ""), "買", r["buyers"], "賣", r["sellers"], "差", r["diff"], "買張", r["buy_sh"], "賣張", r["sell_sh"])
