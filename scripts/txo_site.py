"""data/futures/txo/YYYY/*.csv、inst.csv、pcr.csv、tx.csv（fetch_futures.py）→ 台指選擇權頁（txo.html）用的 JSON。

  data/txo.json
    date, tx, tx_chg       最新交易日、台指期近月收盤與漲跌（畫「現價」線用）
    pc_oi, pc_vol          期交所公布的全市場 P/C Ratio（未平倉、成交量，%）
    exps  最新一天還沒到期的每個契約（月選、週三週選 W、週五週選 F），依最後結算日排序，再加一個「全部合計」（exp="ALL"）：
      {exp, exp_date, kind（月／週三／週五／全部）, oi_c, oi_p, oi_c_d, oi_p_d, pc,
       top_c [[履約價, 口數]×3]（買權未平倉最大 → 壓力）, top_p（賣權 → 支撐）, pain（最大痛點）,
       cols, strikes [[履約價, 買權未平倉, 賣權未平倉, 買權增減, 賣權增減, 買權量, 賣權量, 買權收盤, 賣權收盤]…]}
      增減＝跟前一個交易日同一個序列比；前一天這個契約還沒掛牌就是 null
      最大痛點＝讓所有買方到期價值合計最小的結算價（只在有未平倉的履約價之間找）
    hist  {cols, rows}  每個交易日（最近 N 天）：台指期、當時最近月選的壓力／支撐／P/C／最大痛點、全部契約合計的壓力／支撐／P/C
    inst  {date, cols, rows}  三大法人臺指選擇權未平倉（口數）：
      who, cp, oi_long 買方, oi_short 賣方, oi_net 淨口數, d1 日增減, d5 5日增減, val 淨金額（億）, val_d1 金額日增減
"""
import csv
import json
from pathlib import Path

N = 120
KIND = {"W": "週三", "F": "週五"}
WHO = ["foreign", "trust", "dealer"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    x = _f(v)
    return int(x) if x is not None else 0


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def kind(exp):
    return "月" if exp.isdigit() else KIND.get(exp[6:7], "週")


def load_day(p):
    """→ {exp: {"exp_date", "s": {strike: [c_oi, p_oi, c_vol, p_vol, c_px, p_px]}}}"""
    out = {}
    for r in _read(p):
        e = out.setdefault(r["exp"], {"exp_date": r["exp_date"], "s": {}})
        k = _f(r["strike"])
        k = int(k) if k == int(k) else k
        v = e["s"].setdefault(k, [0, 0, 0, 0, None, None])
        j = 0 if r["cp"] == "C" else 1
        v[j] += _i(r["oi"])
        v[2 + j] += _i(r["volume"])
        v[4 + j] = _f(r["close"]) if _f(r["close"]) is not None else _f(r["settle"])
    return out


def merge_all(day):
    s = {}
    for e in day.values():
        for k, v in e["s"].items():
            t = s.setdefault(k, [0, 0, 0, 0, None, None])
            for j in range(4):
                t[j] += v[j]
    return {"exp_date": "", "s": s}


def top(s, j, n=3):
    xs = sorted(((v[j], k) for k, v in s.items() if v[j] > 0), key=lambda x: (-x[0], x[1]))[:n]
    return [[k, oi] for oi, k in xs]


def max_pain(s):
    ks = sorted(k for k, v in s.items() if v[0] or v[1])
    if not ks:
        return None
    best = None
    for x in ks:
        pain = sum(v[0] * max(0, x - k) + v[1] * max(0, k - x) for k, v in s.items())
        if best is None or pain < best[0]:
            best = (pain, x)
    return best[1]


def summary(e):
    s = e["s"]
    oc, op = sum(v[0] for v in s.values()), sum(v[1] for v in s.values())
    return {"oi_c": oc, "oi_p": op, "pc": round(op / oc * 100, 1) if oc else None,
            "top_c": top(s, 0), "top_p": top(s, 1), "pain": max_pain(s)}


def live(day, d):
    """今天（含）以前結算的契約拿掉"""
    return {x: e for x, e in day.items() if not e["exp_date"] or e["exp_date"] > d}


def near_month(day, d):
    ms = sorted((e["exp_date"], x) for x, e in day.items() if x.isdigit() and e["exp_date"] > d)
    return ms[0][1] if ms else None


def build(data_dir, n=N):
    fut = Path(data_dir) / "futures"
    files = sorted((fut / "txo").glob("*/*.csv"))[-n:]
    if not files:
        return None
    tx = {r["date"]: r for r in _read(fut / "tx.csv")}
    days = [(f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}", p) for p in files]

    hist, prev, cur = [], None, None
    for i, (d, p) in enumerate(days):
        day = live(load_day(p), d)
        m = near_month(day, d)
        ms = summary(day[m]) if m else {}
        al = summary(merge_all(day))
        hist.append([d, _f(tx.get(d, {}).get("close")), m,
                     ms.get("top_c", [[None]])[0][0] if ms.get("top_c") else None,
                     ms.get("top_p", [[None]])[0][0] if ms.get("top_p") else None,
                     ms.get("pc"), ms.get("pain"),
                     al["top_c"][0][0] if al["top_c"] else None, al["top_p"][0][0] if al["top_p"] else None, al["pc"]])
        if i == len(days) - 2:
            prev = load_day(p)
        cur = day
    d = days[-1][0]
    prev = prev or {}
    prev_all = merge_all(live(prev, d)) if prev else None

    exps = []
    order = sorted(cur, key=lambda x: (cur[x]["exp_date"], x))
    for x in order + ["ALL"]:
        e = merge_all(cur) if x == "ALL" else cur[x]
        pe = prev_all if x == "ALL" else prev.get(x)
        rows = []
        for k in sorted(e["s"]):
            v = e["s"][k]
            if not (v[0] or v[1] or v[2] or v[3]):
                continue
            pv = pe["s"].get(k, [0, 0]) if pe else None
            rows.append([k, v[0], v[1], v[0] - pv[0] if pv else None, v[1] - pv[1] if pv else None, v[2], v[3],
                         v[4] if x != "ALL" else None, v[5] if x != "ALL" else None])
        sm = summary(e)
        ps = summary(pe) if pe else None
        exps.append({"exp": x, "exp_date": e["exp_date"], "kind": "全部" if x == "ALL" else kind(x), **sm,
                     "oi_c_d": sm["oi_c"] - ps["oi_c"] if ps else None, "oi_p_d": sm["oi_p"] - ps["oi_p"] if ps else None,
                     "strikes": rows})

    # 三大法人
    inst = {}
    for r in _read(fut / "inst.csv"):
        if r["product"] in ("TXO_C", "TXO_P"):
            inst.setdefault(r["date"], {})[(r["who"], r["product"][-1])] = r
    idates = sorted(inst)
    irows = []
    if idates:
        ld = idates[-1]
        p1 = inst[idates[-2]] if len(idates) > 1 else {}
        p5 = inst[idates[-6]] if len(idates) > 5 else {}
        for w in WHO:
            for cp in ("C", "P"):
                r = inst[ld].get((w, cp))
                if not r:
                    continue
                net = _i(r["oi_net"])
                val = _f(r["oi_net_val"])
                a, b = p1.get((w, cp)), p5.get((w, cp))
                irows.append([w, cp, _i(r["oi_long"]), _i(r["oi_short"]), net,
                              net - _i(a["oi_net"]) if a else None, net - _i(b["oi_net"]) if b else None,
                              round(val / 1e5, 2) if val is not None else None,
                              round((val - _f(a["oi_net_val"])) / 1e5, 2) if a and val is not None and _f(a["oi_net_val"]) is not None else None])
    pcr = {r["date"]: r for r in _read(fut / "pcr.csv")}
    t = tx.get(d, {})
    return {
        "date": d, "tx": _f(t.get("close")), "tx_chg": _f(t.get("change")),
        "pc_oi": _f(pcr.get(d, {}).get("pc_oi")), "pc_vol": _f(pcr.get(d, {}).get("pc_vol")),
        "cols": ["k", "c_oi", "p_oi", "c_d", "p_d", "c_vol", "p_vol", "c_px", "p_px"],
        "exps": exps,
        "hist": {"cols": ["date", "tx", "m_exp", "m_c", "m_p", "m_pc", "m_pain", "a_c", "a_p", "a_pc"], "rows": hist},
        "inst": {"date": idates[-1] if idates else None,
                 "cols": ["who", "cp", "oi_long", "oi_short", "oi_net", "d1", "d5", "val", "val_d1"], "rows": irows},
    }


def write_txo(data_dir, out_path):
    payload = build(data_dir)
    if payload is None:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
