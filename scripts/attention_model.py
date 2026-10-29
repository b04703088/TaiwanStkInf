"""注意股第一～四款規則模型：由日成交資料推算每檔每天會不會被列注意、明天／後天會不會處置、觸發價，並和實際公告對帳。

規則依證交所、櫃買中心「公布或通知注意交易資訊暨處置作業要點第四條異常標準之詳細數據及除外情形」（115.08.03 版），
數字見 RULES。重點：
  6 日累積漲跌幅  最近 6 個營業日（含當日）每日漲跌幅相加（不是首尾收盤比）
  起迄漲幅、價差  起日收盤以除權息還原（data/adjust/events.csv 的 factor）
  偏離            要同時比全體平均、同類股平均多出門檻；同類股不到 5 檔或本益比為負、≥ 上限時只比全體；
                  上櫃實收資本未滿 8 千萬免比
  無漲跌幅的日子  （新股上市前 5 日、恢復交易）當日漲跌幅超過 10.5% 視為無漲跌幅，不計入累積
第五～八款（券商集中度、本益比淨值比、券資比、DR 溢價）資料不足，未建模。

輸出 data/alert/model.json（見 write_model）：
  next   明天再被列注意就處置的股票＋第一款觸發價、歷史命中率
  next2  再被列兩次就處置的股票＋兩天合計還要漲多少
  track  最近 TRACK_DAYS 個交易日，每天規則推算 vs 實際公告（第一～四款），誤判、漏抓逐筆列出
  disp   最近 TRACK_DAYS 個交易日，「明天可能處置」名單 vs 隔天實際處置公告
"""
import bisect
import csv
import glob
import json
import math
import re
from pathlib import Path

import alert_site

STOCK = re.compile(r"^[1-9]\d{3}$")
LOAD_DAYS = 230      # 讀幾個交易日的成交資料（90 日漲幅＋對帳期間）
TRACK_DAYS = 20      # 對帳列最近幾個交易日
STATS_DAYS = 60      # 精確率、涵蓋率統計最近幾個交易日
HIT_DAYS = 120       # 名單分級命中率回測最近幾個交易日
NO_LIMIT = 10.5      # 單日漲跌幅超過這個 %＝無漲跌幅限制的日子

RULES = {
    "TWSE": {"k1": 32, "k1_lo": 25, "k1_gap": 50, "dev": 20, "k34": 25, "pe_cap": 60,
             "k2": ((30, 100, 85), (60, 130, 110), (90, 160, 135)), "k2_low": None, "k2_ex": 25, "k2_ex_dev": 20,
             "vol_x": 5, "vol_dx": 4, "vol_turn": 0.1, "vol_min": 500_000,
             "turn": 10, "turn_dx": 5, "turn_strict": False, "small_cap": None},
    "TPEx": {"k1": 30, "k1_lo": 23, "k1_gap": 40, "dev": 20, "k34": 27, "pe_cap": 65,
             "k2": ((30, 100, 80), (60, 140, 80), (90, 160, 80)), "k2_low": (120, 180, 240), "k2_ex": 27, "k2_ex_dev": 15,
             "vol_x": 5, "vol_dx": 4, "vol_turn": 1, "vol_min": 300_000,
             "turn": 5, "turn_dx": 3, "turn_strict": True, "small_cap": 8_000_000},  # 股數（8 千萬元／面額 10 元）
}
MK = {"TWSE": "上市", "TPEx": "上櫃"}
MK_R = {v: k for k, v in MK.items()}


def _f(s):
    try:
        v = float(str(s).replace(",", ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ---------------- 讀資料 ----------------
def load_prices(data_dir, n=LOAD_DAYS):
    """→ (days, {(market, code): {"name", "rows": [(day_idx, close, pct, volume)]}})"""
    files = sorted(glob.glob(str(Path(data_dir) / "[0-9][0-9][0-9][0-9]" / "[0-9]*.csv")), key=lambda p: Path(p).name)[-n:]
    days, ser = [], {}
    for f in files:
        with open(f, encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
        if not rows:
            continue
        i = len(days)
        days.append(rows[0]["date"])
        for r in rows:
            code = (r.get("code") or "").strip()
            if not STOCK.match(code) or r.get("market") not in MK:
                continue
            close, chg, vol = _f(r.get("close")), _f(r.get("change")), _f(r.get("volume"))
            if not close or vol is None:
                continue
            ref = close - chg if chg is not None else None
            pct = chg / ref * 100 if ref and ref > 0 else None  # None：沒有漲跌，用前一天收盤推
            s = ser.setdefault((r["market"], code), {"name": r.get("name", "").strip(), "rows": []})
            s["rows"].append((i, close, pct, vol))
    return days, ser


def load_factors(data_dir):
    """{code: [(date, factor)]}：除權息、減資等的還原因子"""
    out = {}
    p = Path(data_dir) / "adjust" / "events.csv"
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                f = _f(r.get("factor"))
                if f and f > 0 and r.get("date"):
                    out.setdefault(r["code"].strip(), []).append((r["date"], f))
    return out


def load_industry(data_dir):
    p = Path(data_dir) / "industry" / "official.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fp:
        return {r["code"].strip(): r.get("ind_code") or r.get("industry") or "" for r in csv.DictReader(fp)}


_AVAIL = {1: (5, 15), 2: (8, 14), 3: (11, 14), 4: (3, 31)}  # 季報最晚公布日（第 4 季是隔年）


def load_fundamentals(data_dir):
    """{code: [(可用日, 近四季 EPS 或 None, 股數)]}，依可用日排序；股數＝股本（千元）×100"""
    files = sorted(glob.glob(str(Path(data_dir) / "financials" / "quarterly" / "*.csv")))[-12:]
    per = {}
    for f in files:
        with open(f, encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                y, s = int(r["year"]), int(r["season"])
                per.setdefault(r["code"].strip(), []).append((y, s, _f(r.get("q_eps")), _f(r.get("capital"))))
    out = {}
    for code, qs in per.items():
        qs.sort()
        lst = []
        for k, (y, s, _, cap) in enumerate(qs):
            last4 = qs[max(0, k - 3):k + 1]
            eps = sum(q[2] for q in last4) if len(last4) == 4 and all(q[2] is not None for q in last4) else None
            m, d = _AVAIL[s]
            lst.append((f"{y + (s == 4)}-{m:02d}-{d:02d}", eps, cap * 100 if cap else None))
        out[code] = sorted(lst)
    return out


def _asof(lst, day):
    best = None
    for item in lst or ():
        if item[0] <= day:
            best = item
        else:
            break
    return best


# ---------------- 指標 ----------------
def features(days, ser, factors, industry, fund):
    """→ {day_idx: {(market, code): feat}}，feat 含 s6 s5 s4 gap6 r30 r60 r90 vx turn pe shares close pct ind"""
    out = {}
    for (mk, code), s in ser.items():
        fac = sorted(factors.get(code, []))
        # 補成連續的交易日：沒成交的日子收盤沿用前一天、漲跌 0、量 0（交易所以營業日計算）
        rows, cum, acc, fi = [], [], 0.0, 0
        traded = {r[0]: r for r in s["rows"]}
        first, lastd = s["rows"][0][0], s["rows"][-1][0]
        prev = None
        for i in range(first, lastd + 1):
            step = 0.0
            while fi < len(fac) and fac[fi][0] <= days[i]:
                step += math.log(fac[fi][1])
                fi += 1
            acc += step
            r = traded.get(i)
            if r:
                _, close, pct, vol = r
                if pct is None:
                    pct = (close / prev - 1) * 100 if prev else 0.0  # 對照公告數字：以前一天收盤算，不用除權參考價
                if abs(pct) > NO_LIMIT:
                    pct = 0.0  # 無漲跌幅限制的日子不計
                rows.append((i, close, pct, vol, True))
            else:
                rows.append((i, prev, 0.0, 0.0, False))
            prev = rows[-1][1]
            cum.append(acc)
        fl = fund.get(code)
        for j, (i, close, pct, vol, ok) in enumerate(rows):
            if not ok:
                continue

            def base(back):
                if j - back < 0:
                    return None
                return rows[j - back][1] * math.exp(cum[j] - cum[j - back])
            f = {"close": close, "pct": pct, "vol": vol, "ind": industry.get(code, "")}
            if j >= 5:
                f["s6"] = sum(r[2] for r in rows[j - 5:j + 1])
                f["gap6"] = close - base(5)
            if j >= 4:
                f["s5"] = sum(r[2] for r in rows[j - 4:j + 1])
                f["b5"] = base(4)  # 明天的 6 日起點（已還原到今天）
            if j >= 3:
                f["s4"] = sum(r[2] for r in rows[j - 3:j + 1])
            for n in (30, 60, 90):
                b = base(n - 1)
                if b:
                    f[f"r{n}"] = (close / b - 1) * 100
            vs = [r[3] for r in rows[max(0, j - 59):j + 1]]
            if len(vs) >= 20 and sum(vs) > 0:
                f["vx"] = vol / (sum(vs) / len(vs))
            fa = _asof(fl, days[i])
            if fa:
                eps, sh = fa[1], fa[2]
                f["pe"] = (close / eps if eps and eps > 0 else -1.0) if eps is not None else None
                if sh:
                    f["shares"] = sh
                    f["turn"] = vol / sh * 100
            out.setdefault(i, {})[(mk, code)] = f
    # 全體、同類股平均
    for i, day in out.items():
        groups = {}
        for (mk, code), f in day.items():
            for key in ((mk, None), (mk, f["ind"])):
                g = groups.setdefault(key, {})
                for k in ("s6", "r30", "r60", "r90", "vx", "turn"):
                    if k in f:
                        g.setdefault(k, []).append(f[k])
        avg = {key: {k: (sum(v) / len(v), len(v)) for k, v in g.items()} for key, g in groups.items()}
        for (mk, code), f in day.items():
            f["m"] = {k: v[0] for k, v in avg[(mk, None)].items()}
            f["i"] = {k: v for k, v in avg.get((mk, f["ind"]), {}).items()} if f["ind"] else {}
    return out


def _dev(f, key, th, sign, R):
    """偏離條件：比全體平均、同類股平均都多 th（方向 sign）"""
    if R["small_cap"] and f.get("shares") and f["shares"] < R["small_cap"]:
        return True
    v = f.get(key)
    if v is None or (v - f["m"].get(key, 0)) * sign < th:
        return False
    pe = f.get("pe")
    ia = f["i"].get(key)
    if ia is None or ia[1] < 5 or (pe is not None and (pe < 0 or pe >= R["pe_cap"])):
        return True
    return (v - ia[0]) * sign >= th


def judge(mk, f, k1_recent):
    """規則推算的款次集合 {"1","2","3","4"}；k1_recent：最近 30 個營業日（不含今天）曾列第一款"""
    R = RULES[mk]
    out = set()
    s6 = f.get("s6")
    a = abs(s6) if s6 is not None else 0
    sg = 1 if (s6 or 0) >= 0 else -1
    d20 = s6 is not None and _dev(f, "s6", R["dev"], sg, R)
    if s6 is not None and f["close"] >= 5 and d20 and (
            a > R["k1"] or (a >= R["k1_lo"] and f.get("gap6") is not None and abs(f["gap6"]) >= R["k1_gap"])):
        out.add("1")
    for idx, (n, th, dv) in enumerate(R["k2"]):
        r = f.get(f"r{n}")
        if r is None:
            continue
        lim = R["k2_low"][idx] if R["k2_low"] and f["close"] < 5 else th
        sign = 1 if r > 0 else -1
        if abs(r) > lim and f["pct"] * sign > 0 and _dev(f, f"r{n}", dv, sign, R):
            exempt = k1_recent and not (a > R["k2_ex"] and s6 is not None and _dev(f, "s6", R["k2_ex_dev"], sg, R))
            if not exempt:
                out.add("2")
            break
    if s6 is not None and a > R["k34"] and d20:
        small = R["small_cap"] and f.get("shares") and f["shares"] < R["small_cap"]
        vx, turn = f.get("vx"), f.get("turn")
        if vx is not None and vx >= R["vol_x"] and (small or (
                vx - f["m"].get("vx", 0) >= R["vol_dx"] and (turn or 0) >= R["vol_turn"] and f["vol"] >= R["vol_min"])):
            out.add("3")
        if turn is not None and (turn > R["turn"] if R["turn_strict"] else turn >= R["turn"]) and (
                small or turn - f["m"].get("turn", 0) >= R["turn_dx"]):
            out.add("4")
    return out


# ---------------- 實際公告 ----------------
def actual_attention(att):
    """{(date, 上市/上櫃, code): set(款次)}"""
    out = {}
    for a in att:
        if STOCK.match(a.get("code", "")) and a.get("date"):
            out.setdefault((a["date"], a["market"], a["code"]), set()).update((a.get("clauses") or "").split(";"))
    return out


def k1_recent(act, days, i, mk, code):
    return any("1" in act.get((days[k], MK[mk], code), ()) for k in range(max(0, i - 29), i))


# ---------------- 觸發價 ----------------
def triggers(mk, f):
    """明天收盤要漲（跌）多少 % 會達第一款（偏離條件假設成立）。回傳 (up_pct, dn_pct, k34_pct)；None＝算不出"""
    R = RULES[mk]
    s5, close, b5 = f.get("s5"), f["close"], f.get("b5")
    if s5 is None:
        return None, None, None
    up = R["k1"] - s5
    dn = -R["k1"] - s5
    if b5:
        up = min(up, max(R["k1_lo"] - s5, (R["k1_gap"] + b5) / close * 100 - 100))
        dn = max(dn, min(-R["k1_lo"] - s5, (b5 - R["k1_gap"]) / close * 100 - 100))
    return up, dn, R["k34"] - s5


def bucket(dist):
    """dist：還要往同方向走多少 %"""
    if dist is None:
        return "na"
    if dist <= -10:
        return "lock"
    if dist <= 0:
        return "flat"
    if dist <= 3:
        return "3"
    if dist <= 6:
        return "6"
    if dist <= 10:
        return "10"
    return "far"


def bucket2(dist):
    if dist is None:
        return "na"
    for lim, k in ((0, "0"), (5, "5"), (10, "10"), (15, "15")):
        if dist <= lim:
            return k
    return "far"


def _dir_dist(mk, f):
    up, dn, _ = triggers(mk, f)
    if up is None:
        return None, None
    return (up, "up") if (f.get("s5") or 0) >= 0 else (-dn, "dn")


def two_away(att, disp, days, i):
    """第 i 日收盤後，再被列兩次（第一款連續或第一～八款）才處置的股票：[(market, code, need)]"""
    hits, last = alert_site._index(att, disp, days[i])
    window = days[max(0, i - 29):i + 1]
    out = []
    for (mk, code), h in hits.items():
        if not any(h.get(x, set()) & alert_site.R18 for x in window):
            continue  # 近 30 日沒有第一～八款，兩次不可能處置
        since = last.get((mk, code), "")
        if alert_site.is_disposed(alert_site._counts(h, days, i, since)):
            continue
        res = {}
        for need, cl in (("1", {"1"}), ("1-8", {"2"})):
            hh, dd = dict(h), days[:i + 1] + ["9999-F1", "9999-F2"]
            hh[dd[i + 1]] = cl
            one = alert_site.is_disposed(alert_site._counts(hh, dd, i + 1, since))
            hh[dd[i + 2]] = cl
            two = alert_site.is_disposed(alert_site._counts(hh, dd, i + 2, since))
            res[need] = (one, two)
        if res["1-8"][0] or res["1"][0]:
            continue  # 一次就夠，屬於 next
        if res["1-8"][1]:
            out.append((mk, code, "1-8"))
        elif res["1"][1]:
            out.append((mk, code, "1"))
    return out


# ---------------- 組合 ----------------
def build(data_dir):
    data_dir = Path(data_dir)
    d = data_dir / "alert"
    att_all = alert_site._read(d / "attention.csv")
    disp_all = alert_site._read(d / "disposal.csv")
    att = [a for a in att_all if alert_site.is_stock(a["code"]) and a.get("date")]
    disp = [x for x in disp_all if alert_site.is_stock(x["code"]) and x.get("ann_date")]
    adays = sorted({a["date"] for a in att_all if a.get("date")})
    days, ser = load_prices(data_dir)
    if not days:
        return None
    feats = features(days, ser, load_factors(data_dir), load_industry(data_dir), load_fundamentals(data_dir))
    names = {code: s["name"] for (_, code), s in ser.items()}
    act = actual_attention(att)
    pidx = {x: k for k, x in enumerate(days)}
    ann = {(x["ann_date"], x["market"], x["code"]) for x in disp}

    # --- 每天規則推算 vs 實際 ---
    track_days = [x for x in days[-STATS_DAYS:] if x in set(adays)]
    stats = {m: {k: [0, 0, 0] for k in "1234"} for m in MK.values()}
    daily = []
    for day in track_days:
        i = pidx[day]
        cases, tp = [], 0
        for (mk, code), f in feats.get(i, {}).items():
            pred = judge(mk, f, k1_recent(act, days, i, mk, code))
            real = act.get((day, MK[mk], code), set()) & set("1234")
            for k in "1234":
                p, r = k in pred, k in real
                st = stats[MK[mk]][k]
                st[0] += p and r
                st[1] += p and not r
                st[2] += r and not p
            if pred or real:
                tp += bool(pred & real)
                if pred != real:
                    cases.append(_case(day, mk, code, f, pred, real))
        if day in track_days[-TRACK_DAYS:]:
            cases.sort(key=lambda c: (c[0], c[1], c[2]))
            daily.append({"date": day, "cases": cases})

    # --- 名單分級命中率（過去 HIT_DAYS 天） ---
    rate1, rate2 = {}, {}
    disp_track = []
    lo = max(30, len(adays) - 1 - HIT_DAYS)
    att_by = sorted(att, key=lambda a: a["date"])
    adates = [a["date"] for a in att_by]

    def recent(k):
        """處置判斷只看最近 30 個交易日，先切掉更早的注意紀錄（只為了快）"""
        return att_by[bisect.bisect_left(adates, adays[max(0, k - 35)]):bisect.bisect_right(adates, adays[k])]
    for k in range(lo, len(adays) - 1):
        day, nxt = adays[k], adays[k + 1]
        i = pidx.get(day)
        att_k = recent(k)
        cands = alert_site.candidates(att_k, disp, adays, k)
        row = {"date": day, "next": nxt, "hit": [], "miss": [], "surprise": []}
        listed = set()
        for c in cands:
            f = feats.get(i, {}).get((MK_R[c["market"]], c["code"])) if i is not None else None
            b = bucket(_dir_dist(MK_R[c["market"]], f)[0]) if f else "na"
            h = (nxt, c["market"], c["code"]) in ann
            rate1.setdefault(b, [0, 0])
            rate1[b][0] += h
            rate1[b][1] += 1
            listed.add((c["market"], c["code"]))
            (row["hit"] if h else row["miss"]).append(c["code"])
        row["surprise"] = sorted(c for (a_, m, c) in ann if a_ == nxt and (m, c) not in listed)
        if k + 2 < len(adays):
            nxt2 = adays[k + 2]
            for mk, code, need in two_away(att_k, disp, adays, k):
                f = feats.get(i, {}).get((MK_R[mk], code)) if i is not None else None
                dist = RULES[MK_R[mk]]["k1"] - f["s4"] if f and f.get("s4") is not None else None
                b = bucket2(dist)
                h = (nxt2, mk, code) in ann
                rate2.setdefault(b, [0, 0])
                rate2[b][0] += h
                rate2[b][1] += 1
        if k >= len(adays) - 1 - TRACK_DAYS:
            disp_track.append(row)

    # --- 最新一天的名單 ---
    last = adays[-1] if adays else None
    i = pidx.get(last)
    nxt_rows, nxt2_rows = [], []
    if i is not None:
        for c in alert_site.candidates(att, disp, adays):
            mk = MK_R[c["market"]]
            f = feats[i].get((mk, c["code"]))
            if not f:
                continue
            up, dn, k34 = triggers(mk, f)
            dist, direction = _dir_dist(mk, f)
            nxt_rows.append([c["market"], c["code"], ";".join(c["rules"]), c["need"], f["close"], _r(f.get("s6")),
                             _r(up), _px(f["close"], up), _r(dn), _px(f["close"], dn), _r(k34), _r(f.get("turn")),
                             bucket(dist), direction])
        for mk_, code, need in two_away(att, disp, adays, len(adays) - 1):
            mk = MK_R[mk_]
            f = feats[i].get((mk, code))
            if not f or f.get("s4") is None:
                continue
            dist = RULES[mk]["k1"] - f["s4"]
            nxt2_rows.append([mk_, code, need, f["close"], _r(f.get("s6")), _r(dist), bucket2(dist)])
        nxt2_rows.sort(key=lambda r: r[5])
    return {
        "date": last, "price_date": days[-1],
        "names": {r[1]: names.get(r[1], "") for r in nxt_rows + nxt2_rows} | {
            c[3]: names.get(c[3], "") for dd in daily for c in dd["cases"]} | {
            c: names.get(c, "") for row in disp_track for k in ("hit", "miss", "surprise") for c in row[k]},
        "next": {"cols": ["market", "code", "rules", "need", "close", "s6", "up", "up_px", "dn", "dn_px", "k34", "turn",
                          "bucket", "dir"], "rows": nxt_rows, "rate": rate1, "days": HIT_DAYS},
        "next2": {"cols": ["market", "code", "need", "close", "s6", "two", "bucket"], "rows": nxt2_rows,
                  "rate": rate2, "days": HIT_DAYS},
        "stats": {"days": len(track_days), "from": track_days[0] if track_days else None, "by": stats},
        "track": {"cols": CASE_COLS, "days": daily},
        "disp": disp_track,
        "rules": {MK[k]: {kk: vv for kk, vv in v.items()} for k, v in RULES.items()},
    }


CASE_COLS = ["date", "market", "kind", "code", "clause", "close", "pct", "s6", "gap6", "dm6", "di6",
             "r30", "r60", "r90", "vx", "turn", "pe"]


def _r(v, n=2):
    return None if v is None else round(v, n)


def _px(close, pct):
    return None if pct is None or pct <= -10 or pct >= 10 else round(close * (1 + pct / 100), 2)


def _case(day, mk, code, f, pred, real):
    """一筆不一致：kind "fp"＝推算會中但沒公告，"fn"＝有公告但沒推算到；clause 為有差異的款次"""
    fp = "".join(sorted(pred - real))
    fn = "".join(sorted(real - pred))
    m, ia = f["m"], f["i"].get("s6")
    return [day, MK[mk], "fp" if fp and not fn else "fn" if fn and not fp else "mix", code, fp + ("/" + fn if fp and fn else fn),
            f["close"], _r(f["pct"]), _r(f.get("s6")), _r(f.get("gap6")),
            _r(f["s6"] - m["s6"]) if f.get("s6") is not None and "s6" in m else None,
            _r(f["s6"] - ia[0]) if f.get("s6") is not None and ia else None,
            _r(f.get("r30"), 1), _r(f.get("r60"), 1), _r(f.get("r90"), 1), _r(f.get("vx")), _r(f.get("turn")),
            _r(f.get("pe"), 1)]


def write_model(data_dir, out_path):
    payload = build(data_dir)
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[1]
    p = write_model(root / "data", Path(sys.argv[1]) if len(sys.argv) > 1 else root / "_model.json")
    for mkt, ks in p["stats"]["by"].items():
        print(mkt, {k: f"精確 {v[0] / max(1, v[0] + v[1]):.0%} 涵蓋 {v[0] / max(1, v[0] + v[2]):.0%}" for k, v in ks.items()})
    print("next", p["next"]["rate"], len(p["next"]["rows"]))
    print("next2", p["next2"]["rate"], len(p["next2"]["rows"]))
