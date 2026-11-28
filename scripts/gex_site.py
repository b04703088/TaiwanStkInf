"""data/futures/txo/YYYY/*.csv、inst.csv、tx.csv（fetch_futures.py）→ 選擇權 Gamma 頁（gex.html）用的 JSON。

做法（用三大法人資料推估「誰」持有 gamma）
  1. 每個還沒到期的序列：用買賣權平價（同履約價 C − P 最接近 0 的幾檔）推遠期價 F，
     以結算價用 Black-76（r＝0）反推隱含波動率；價外權利金 < 0.5 點反推不準的，用同到期日相鄰履約價內插。
     同一履約價買權、賣權共用一個波動率（取價外那一邊）。
  2. 三大法人「選擇權買賣權分計」只有商品合計：各身分 × 買權／賣權 × 買方／賣方的未平倉口數 N 與契約金額 V。
     平均權利金 A＝V×1000 ÷ (N×50) 點，透露部位偏價外（便宜）還是偏價平（貴）。
     把 N 分到各序列：權重 wᵢ ∝ OIᵢ × Pᵢ^θ（Pᵢ＝結算價），解 θ 讓 Σ wᵢPᵢ ＝ A（θ<0 偏便宜的價外／近到期序列）。
     沒有金額的日子 θ＝0（依未平倉比例分）。三個法人加總超過某序列未平倉時，超過的部分移到其他序列。
  3. 其他交易人（散戶、非三大法人）＝每個序列的未平倉減掉三大法人，所以四群加總的淨部位、淨 gamma 恆等於 0。
  4. gamma 單位：「指數漲 1% 時，這群人為了維持 delta 中性要賣出幾口大台」＝ Σ 淨口數 × Γ × 1%×F × 50 ÷ 200。
     正值＝long gamma（漲賣跌買、壓抑波動）；負值＝short gamma（追漲殺跌、放大波動）。
     delta 也換成大台口數（Σ 淨口數 × Δ × 50 ÷ 200）。
  5. 翻轉點：把所有遠期價一起移動 −8%～+8%（波動率、到期時間不變），找自營商淨 gamma 由正轉負的指數位置。

  data/gex.json
    date, tx, spot（最近到期契約的遠期價）, method（tilt＝依金額傾斜／equal＝依未平倉比例）
    groups  [{who, gamma, gamma_c, gamma_p, gamma_wk（7 天內到期）, delta, oi_long, oi_short}]  who: dealer／foreign／trust／other
    flip    {who: 指數點位或 null}；profile {cols, rows}  [移動%, 指數, 各身分 gamma]
    strikes {cols, rows}  現價 ±10% 各履約價（所有到期合計）各身分 gamma
    exps    [{exp, exp_date, kind, F, iv（價平）, dealer, foreign, trust, other}]
    alloc   {cols, rows}  [who, cp, side, 口數, 平均權利金, 依未平倉比例的平均權利金, θ]
    hist    {cols, rows}  每個交易日：台指期、各身分 gamma、自營商翻轉點、方法、隔日加權指數漲跌%
    check   隔日加權指數漲跌幅依自營商 gamma 分組：[{bucket, n, abs_ret, rng}]
"""
import csv
import json
import math
from datetime import date
from pathlib import Path

N_DAYS = 120
WHO = ["dealer", "foreign", "trust"]
GROUPS = WHO + ["other"]
KIND = {"W": "週三", "F": "週五"}
MULT, BIG = 50, 200
GRID = [x / 1000 for x in range(-80, 81, 5)]        # 最新一天：±8%，每 0.5%
GRID_H = [x / 1000 for x in range(-60, 61, 10)]     # 歷史翻轉點：±6%，每 1%
SQ2 = math.sqrt(2)
SQ2PI = math.sqrt(2 * math.pi)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def ncdf(x):
    return 0.5 * (1 + math.erf(x / SQ2))


def b76(F, K, T, s, cp):
    if s <= 0 or T <= 0:
        return max(0.0, F - K) if cp == "C" else max(0.0, K - F)
    v = s * math.sqrt(T)
    d1 = (math.log(F / K) + v * v / 2) / v
    d2 = d1 - v
    if cp == "C":
        return F * ncdf(d1) - K * ncdf(d2)
    return K * ncdf(-d2) - F * ncdf(-d1)


def greeks(F, K, T, s, cp):
    """→ (delta, gamma)，gamma 單位：每指數點的 delta 變化"""
    v = s * math.sqrt(T)
    d1 = (math.log(F / K) + v * v / 2) / v
    if abs(d1) > 9:
        return ((1.0 if d1 > 0 else 0.0) if cp == "C" else (-1.0 if d1 < 0 else 0.0)), 0.0
    g = math.exp(-d1 * d1 / 2) / SQ2PI / (F * v)
    dl = ncdf(d1)
    return (dl if cp == "C" else dl - 1), g


def implied(px, F, K, T, cp):
    intr = max(0.0, F - K) if cp == "C" else max(0.0, K - F)
    if px is None or px <= intr + 1e-9 or T <= 0:
        return None
    lo, hi = 0.005, 3.0
    if b76(F, K, T, hi, cp) < px:
        return None
    for _ in range(48):
        m = (lo + hi) / 2
        if b76(F, K, T, m, cp) < px:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def kind(exp):
    return "月" if exp.isdigit() else KIND.get(exp[6:7], "週")


def load_series(p, d):
    """→ {exp: {"exp_date", "T", "s": {K: {"C": (px, oi), "P": (px, oi)}}}}，只留還沒到期的"""
    out = {}
    d0 = date.fromisoformat(d)
    for r in _read(p):
        ed = r["exp_date"]
        if not ed or ed <= d:
            continue
        e = out.get(r["exp"])
        if e is None:
            days = (date.fromisoformat(ed) - d0).days
            e = out[r["exp"]] = {"exp_date": ed, "T": max(days - 0.01, 0.5) / 365, "s": {}}
        st, cl = _f(r["settle"]), _f(r["close"])
        px = st if st and st > 0 else (cl if cl and cl > 0 else None)
        oi = int(_f(r["oi"]) or 0)
        e["s"].setdefault(float(r["strike"]), {})[r["cp"]] = (px, oi)
    return out


def forward(e, fallback):
    """買賣權平價：C − P 絕對值最小的 3 檔的 K + C − P 取中位數"""
    xs = []
    for k, v in e["s"].items():
        c, p = v.get("C", (None, 0))[0], v.get("P", (None, 0))[0]
        if c and p:
            xs.append((abs(c - p), k + c - p))
    if not xs:
        return fallback
    xs.sort()
    top = sorted(x[1] for x in xs[:3])
    return top[len(top) // 2]


def smile(e, F):
    """每個履約價一個波動率：價外那一邊反推，權利金太小的用相鄰履約價線性內插、兩端平推"""
    ks = sorted(e["s"])
    got = {}
    for k in ks:
        cp = "C" if k >= F else "P"
        px = e["s"][k].get(cp, (None, 0))[0]
        if px is not None and px >= 0.5:
            iv = implied(px, F, k, e["T"], cp)
            if iv and 0.03 <= iv <= 2.0:
                got[k] = iv
    if not got:
        return {k: 0.2 for k in ks}, 0.2
    gk = sorted(got)
    out = {}
    j = 0
    for k in ks:
        if k in got:
            out[k] = got[k]
            continue
        while j + 1 < len(gk) and gk[j + 1] < k:
            j += 1
        if k <= gk[0]:
            out[k] = got[gk[0]]
        elif k >= gk[-1]:
            out[k] = got[gk[-1]]
        else:
            a, b = gk[j], gk[j + 1]
            out[k] = got[a] + (got[b] - got[a]) * (k - a) / (b - a)
    atm = min(gk, key=lambda k: abs(k - F))
    return out, got[atm]


def solve_theta(oi, px, target):
    """wᵢ ∝ oiᵢ × pxᵢ^θ，平均權利金 Σw·px／Σw ＝ target；單調遞增，二分法"""
    lp = [math.log(p) for p in px]

    def avg(t):
        m = max(math.log(o) + t * l for o, l in zip(oi, lp))
        ws = [math.exp(math.log(o) + t * l - m) for o, l in zip(oi, lp)]
        s = sum(ws)
        return sum(w * p for w, p in zip(ws, px)) / s, [w / s for w in ws]

    lo, hi = -4.0, 4.0
    a_lo, a_hi = avg(lo)[0], avg(hi)[0]
    if target <= a_lo:
        return lo, avg(lo)[1]
    if target >= a_hi:
        return hi, avg(hi)[1]
    for _ in range(50):
        m = (lo + hi) / 2
        if avg(m)[0] < target:
            lo = m
        else:
            hi = m
    t = (lo + hi) / 2
    return t, avg(t)[1]


def cap(alloc, oi, it=8):
    """三個法人在同一序列加總不能超過該序列未平倉：超過的按比例砍，砍掉的口數按原權重移到還有空間的序列"""
    n = len(oi)
    for _ in range(it):
        tot = [sum(a[i] for a in alloc.values()) for i in range(n)]
        over = [i for i in range(n) if tot[i] > oi[i] * 1.0000001]
        if not over:
            break
        for g, a in alloc.items():
            moved = 0.0
            for i in over:
                cut = a[i] * (1 - oi[i] / tot[i])
                a[i] -= cut
                moved += cut
            room = [i for i in range(n) if tot[i] < oi[i]]
            rs = sum(a[i] for i in room) or sum(oi[i] for i in room)
            if room and rs > 0:
                base = [a[i] for i in room] if sum(a[i] for i in room) > 0 else [oi[i] for i in room]
                for i, b in zip(room, base):
                    a[i] += moved * b / rs
    return alloc


def day_model(series, inst, tx):
    """→ (rows, meta)；rows：[(exp, K, cp, F, T, iv, {group: 淨口數})]"""
    fb = tx
    flat = []      # (exp, K, cp, px, oi, F, T, iv)
    exps = {}
    for x in sorted(series, key=lambda x: (series[x]["exp_date"], x)):
        e = series[x]
        F = forward(e, fb)
        if F is None:
            continue
        iv, atm = smile(e, F)
        exps[x] = {"exp": x, "exp_date": e["exp_date"], "kind": kind(x), "F": round(F, 1), "iv": round(atm * 100, 1), "T": e["T"]}
        for k, v in e["s"].items():
            for cp, (px, oi) in v.items():
                if oi > 0:
                    if px is None:
                        px = b76(F, k, e["T"], iv[k], cp)
                    flat.append((x, k, cp, max(px, 0.1), oi, F, e["T"], iv[k]))
    if not flat:
        return None
    method = "tilt"
    pos = {g: [0.0] * len(flat) for g in GROUPS}
    alloc_rows = []
    for cp in ("C", "P"):
        idx = [i for i, r in enumerate(flat) if r[2] == cp]
        oi = [flat[i][4] for i in idx]
        px = [flat[i][3] for i in idx]
        tot = sum(oi)
        eq = sum(o * p for o, p in zip(oi, px)) / tot
        for side, sgn in (("long", 1), ("short", -1)):
            al = {}
            for g in WHO:
                r = inst.get((g, cp))
                n = int(_f(r["oi_" + side]) or 0) if r else 0
                v = _f(r.get("oi_" + side + "_val")) if r else None
                if n <= 0:
                    al[g] = [0.0] * len(idx)
                    alloc_rows.append([g, cp, side, 0, None, round(eq, 1), None])
                    continue
                if v is None:
                    method = "equal"
                    th, w = 0.0, [o / tot for o in oi]
                    target = None
                else:
                    target = v * 1000 / (n * MULT)
                    th, w = solve_theta(oi, px, target)
                al[g] = [n * x for x in w]
                alloc_rows.append([g, cp, side, n, round(target, 1) if target is not None else None, round(eq, 1),
                                   round(th, 2) if target is not None else None])
            cap(al, oi)
            for j, i in enumerate(idx):
                s = 0.0
                for g in WHO:
                    pos[g][i] += sgn * al[g][j]
                    s += al[g][j]
                pos["other"][i] += sgn * max(0.0, oi[j] - s)
    rows = [(r[0], r[1], r[2], r[5], r[6], r[7], {g: pos[g][i] for g in GROUPS}) for i, r in enumerate(flat)]
    return rows, {"exps": exps, "alloc": alloc_rows, "method": method}


def gamma_at(rows, shift=0.0, filt=None):
    """所有遠期價一起乘 (1+shift)；→ {group: 大台口／1%}"""
    out = {g: 0.0 for g in GROUPS}
    for r in rows:
        if filt and not filt(r):
            continue
        F = r[3] * (1 + shift)
        _, g = greeks(F, r[1], r[4], r[5], r[2])
        if g == 0:
            continue
        u = g * 0.01 * F * MULT / BIG
        for k, n in r[6].items():
            out[k] += n * u
    return out


def delta_of(rows):
    out = {g: 0.0 for g in GROUPS}
    for r in rows:
        dl, _ = greeks(r[3], r[1], r[4], r[5], r[2])
        for k, n in r[6].items():
            out[k] += n * dl * MULT / BIG
    return out


def flip(profile, spot, who="dealer"):
    """gamma 由正轉負（往下跌的方向）最接近現價的交叉點"""
    best = None
    for (x0, g0), (x1, g1) in zip(profile, profile[1:]):
        a, b = g0[who], g1[who]
        if (a < 0 <= b) or (a >= 0 > b):
            x = x0 + (x1 - x0) * (0 - a) / (b - a) if b != a else x0
            if best is None or abs(x) < abs(best):
                best = x
    return round(spot * (1 + best)) if best is not None else None


def build(data_dir, n=N_DAYS):
    fut = Path(data_dir) / "futures"
    files = sorted((fut / "txo").glob("*/*.csv"))[-n:]
    if not files:
        return None
    tx = {r["date"]: r for r in _read(fut / "tx.csv")}
    inst = {}
    for r in _read(fut / "inst.csv"):
        if r["product"] in ("TXO_C", "TXO_P"):
            inst.setdefault(r["date"], {})[(r["who"], r["product"][-1])] = r
    hist = []
    last = None
    for p in files:
        d = f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}"
        if d not in inst:
            continue
        txc = _f(tx.get(d, {}).get("close"))
        m = day_model(load_series(p, d), inst[d], txc)
        if not m:
            continue
        rows, meta = m
        spot = next(iter(meta["exps"].values()))["F"]
        g0 = gamma_at(rows)
        prof = [(x, gamma_at(rows, x)) for x in GRID_H]
        hist.append([d, txc] + [round(g0[g]) for g in GROUPS] + [flip(prof, spot), meta["method"]])
        last = (d, rows, meta, spot, txc)
    if not last:
        return None
    # 隔日加權指數漲跌%（驗證用；不用台指期近月，結算日近月會是當天到期的合約）
    ix = {r["date"]: _f(r["close"]) for r in _read(Path(data_dir) / "market" / "taiex.csv")}
    for i, h in enumerate(hist):
        c0 = ix.get(h[0])
        c1 = ix.get(hist[i + 1][0]) if i + 1 < len(hist) else None
        h.append(round((c1 / c0 - 1) * 100, 2) if c0 and c1 else None)
    d, rows, meta, spot, txc = last
    d0 = date.fromisoformat(d)
    g0 = gamma_at(rows)
    gc = gamma_at(rows, filt=lambda r: r[2] == "C")
    gp = gamma_at(rows, filt=lambda r: r[2] == "P")
    wk = gamma_at(rows, filt=lambda r: r[4] * 365 <= 7)
    dl = delta_of(rows)
    groups = []
    for g in GROUPS:
        lo = sum(n for r in rows for k, n in r[6].items() if k == g and n > 0)
        sh = -sum(n for r in rows for k, n in r[6].items() if k == g and n < 0)
        groups.append({"who": g, "gamma": round(g0[g]), "gamma_c": round(gc[g]), "gamma_p": round(gp[g]),
                       "gamma_wk": round(wk[g]), "delta": round(dl[g]), "oi_long": round(lo), "oi_short": round(sh)})
    prof = [(x, gamma_at(rows, x)) for x in GRID]
    flips = {g: flip(prof, spot, g) for g in GROUPS}
    # 各履約價（所有到期合計）
    byk = {}
    for r in rows:
        if abs(r[1] / spot - 1) > 0.10:
            continue
        _, g = greeks(r[3], r[1], r[4], r[5], r[2])
        u = g * 0.01 * r[3] * MULT / BIG
        t = byk.setdefault(r[1], {x: 0.0 for x in GROUPS})
        for k, nn in r[6].items():
            t[k] += nn * u
    strikes = [[int(k) if k == int(k) else k] + [round(byk[k][g], 1) for g in GROUPS] for k in sorted(byk)]
    exps = []
    for x, e in meta["exps"].items():
        ge = gamma_at(rows, filt=lambda r, x=x: r[0] == x)
        exps.append({k: e[k] for k in ("exp", "exp_date", "kind", "F", "iv")} | {g: round(ge[g]) for g in GROUPS}
                    | {"days": (date.fromisoformat(e["exp_date"]) - d0).days})
    # 驗證：依自營商 gamma 分三組，看隔日台指期漲跌幅
    ok = [h for h in hist if h[-1] is not None]
    check = []
    if len(ok) >= 9:
        srt = sorted(ok, key=lambda h: h[2])
        k = len(srt) // 3
        for name, part in (("最負（short gamma）", srt[:k]), ("中間", srt[k:len(srt) - k]), ("最正（long gamma）", srt[len(srt) - k:])):
            check.append({"bucket": name, "n": len(part), "lo": part[0][2], "hi": part[-1][2],
                          "abs_ret": round(sum(abs(h[-1]) for h in part) / len(part), 2)})
        neg = [h for h in ok if h[2] < 0]
        pos = [h for h in ok if h[2] >= 0]
        for name, part in (("自營商 < 0", neg), ("自營商 ≥ 0", pos)):
            if part:
                check.append({"bucket": name, "n": len(part), "lo": None, "hi": None,
                              "abs_ret": round(sum(abs(h[-1]) for h in part) / len(part), 2)})
    return {
        "date": d, "tx": txc, "spot": spot, "method": meta["method"],
        "groups": groups, "flip": flips,
        "profile": {"cols": ["x", "lvl"] + GROUPS,
                    "rows": [[round(x * 100, 1), round(spot * (1 + x))] + [round(g[k]) for k in GROUPS] for x, g in prof]},
        "strikes": {"cols": ["k"] + GROUPS, "rows": strikes},
        "exps": exps,
        "alloc": {"cols": ["who", "cp", "side", "n", "avg", "eq", "theta"], "rows": meta["alloc"]},
        "hist": {"cols": ["date", "tx"] + GROUPS + ["flip", "method", "next_ret"], "rows": hist},
        "check": check,
    }


def write_gex(data_dir, out_path):
    payload = build(data_dir)
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    import time
    t = time.time()
    p = build(Path(__file__).resolve().parents[1] / "data")
    print(f"{time.time() - t:.1f}s")
    if p and "-v" in sys.argv:
        print(json.dumps({k: p[k] for k in ("date", "tx", "spot", "method", "groups", "flip", "check")}, ensure_ascii=False, indent=1))
        print(p["exps"][:4])
        print(p["alloc"])
        for r in p["hist"]["rows"][-8:]:
            print(r)
