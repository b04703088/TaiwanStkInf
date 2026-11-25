"""用 TXO 月選盤後結算價推算台指 VIX（CBOE 舊制，近月＋次近月內插 30 天）。

期交所只免費提供近 3 個月的官方 VIX，更早的用這支推算。
跟官方重疊期（2026-08～11，77 天）比：平均誤差 0.10 點（0.3%）。
用結算價比用收盤最佳買賣價中價準很多（中價誤差 3.5 點）。

fetch_market.py --only vixcalc 每天抓期交所選擇權日資料（optDataDown）算一次，寫 data/market/vix_calc.csv。
"""
import csv, gzip, math, sys
from collections import defaultdict
from datetime import date, datetime, timedelta

R = 0.015          # 無風險利率（影響極小）
MIN_YEAR = 525600


def third_wed(ym):
    y, m = int(ym[:4]), int(ym[4:])
    d = date(y, m, 1)
    d += timedelta(days=(2 - d.weekday()) % 7)
    return d + timedelta(days=14)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_taifex(text, data=None, last=None):
    """期交所 optDataDown 的 CSV（big5 解碼後）→ data, last。只留 TXO 月選一般盤。"""
    data = data if data is not None else defaultdict(lambda: defaultdict(dict))
    last = last if last is not None else {}
    for p in csv.reader(text.splitlines()[1:]):
        if len(p) < 18 or p[1].strip() != "TXO" or p[17].strip() != "一般":
            continue
        exp = p[2].strip()
        if not (len(exp) == 6 and exp.isdigit()):
            continue
        d = p[0].replace("/", "-")
        data[d][exp].setdefault(float(p[3]), {})["C" if p[4].strip() == "買權" else "P"] = (_num(p[12]), _num(p[13]), _num(p[10]))
        last[exp] = max(last.get(exp, ""), d)
    return data, last


def load(paths):
    """research/vix_chain.py 的精簡 csv.gz（回補時用）。"""
    data = defaultdict(lambda: defaultdict(dict))   # date -> exp -> strike -> {C:(bid,ask,settle), P:...}
    last = {}
    for p in paths:
        with gzip.open(p, "rt") as f:
            for r in csv.DictReader(f):
                data[r["date"]][r["exp"]].setdefault(float(r["strike"]), {})[r["cp"]] = (_num(r["bid"]), _num(r["ask"]), _num(r["settle"]))
                last[r["exp"]] = max(last.get(r["exp"], ""), r["date"])
    return data, last


def price(q, mode):
    if not q:
        return None, 0
    b, a, s = q
    if mode == "mid":
        if b and a and a >= b:
            return (a + b) / 2, b
        return None, b or 0
    return (s if s and s > 0 else None), (b or 0)


def sigma2(chain, T, mode):
    ks = sorted(chain)
    c = {k: price(chain[k].get("C"), mode) for k in ks}
    p = {k: price(chain[k].get("P"), mode) for k in ks}
    both = [k for k in ks if c[k][0] is not None and p[k][0] is not None]
    if not both:
        return None
    ks_ = min(both, key=lambda k: abs(c[k][0] - p[k][0]))
    er = math.exp(R * T)
    F = ks_ + er * (c[ks_][0] - p[ks_][0])
    below = [k for k in ks if k <= F]
    if not below:
        return None
    K0 = below[-1]
    sel = {}
    zero = 0
    for k in reversed([k for k in ks if k < K0]):
        v, b = p[k]
        if mode == "mid" and not b:
            zero += 1
            if zero >= 2: break
            continue
        zero = 0
        if v: sel[k] = v
    zero = 0
    for k in [k for k in ks if k > K0]:
        v, b = c[k]
        if mode == "mid" and not b:
            zero += 1
            if zero >= 2: break
            continue
        zero = 0
        if v: sel[k] = v
    vals = [x for x in (c[K0][0], p[K0][0]) if x is not None]
    if vals:
        sel[K0] = sum(vals) / len(vals)
    sk = sorted(sel)
    if len(sk) < 3:
        return None
    tot = 0
    for i, k in enumerate(sk):
        dk = (sk[min(i + 1, len(sk) - 1)] - sk[max(i - 1, 0)]) / (2 if 0 < i < len(sk) - 1 else 1)
        tot += dk / k / k * er * sel[k]
    return 2 / T * tot - 1 / T * (F / K0 - 1) ** 2


def compute(data, last, end_date, mode="settle", roll=0):
    out = {}
    for d in sorted(data):
        now = datetime.fromisoformat(d).replace(hour=13, minute=45)
        exps = []
        for e in sorted(data[d])[:3]:
            ed = date.fromisoformat(last[e]) if last[e] < end_date else third_wed(e)
            mins = (datetime.combine(ed, datetime.min.time()).replace(hour=13, minute=30) - now).total_seconds() / 60
            if mins > roll * 1440:
                exps.append((e, mins))
        if len(exps) < 2:
            continue
        (e1, m1), (e2, m2) = exps[:2]
        T1, T2 = m1 / MIN_YEAR, m2 / MIN_YEAR
        s1, s2 = sigma2(data[d][e1], T1, mode), sigma2(data[d][e2], T2, mode)
        if s1 is None or s2 is None:
            continue
        N30 = 30 * 1440
        v = (T1 * s1 * (m2 - N30) / (m2 - m1) + T2 * s2 * (N30 - m1) / (m2 - m1)) * MIN_YEAR / N30
        if v > 0:
            out[d] = round(100 * math.sqrt(v), 2)
    return out


if __name__ == "__main__":
    data, last = load(sys.argv[2:])
    res = compute(data, last, max(data))
    with open(sys.argv[1], "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "vix"])
        for d in sorted(res): w.writerow([d, res[d]])
    print(len(res), "days")
