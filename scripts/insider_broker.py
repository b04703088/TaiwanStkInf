"""內部人 × 分點：拿每月持股異動（實際集中市場買賣張數）去比對當期分點進出，推出內部人用哪些分點下單。

輸入（fetch_insider_broker.py）
  brokers  data/insider/brokers.csv：每個「月報」區間與前 30 天、每個「申報追蹤」區間的買超／賣超前 15 名
  days     data/insider/broker_days.csv：候選分點在區間內每天淨買／淨賣的天數

內部人分批出貨（或進貨）的特徵跟公司買回庫藏股一樣：整段期間幾乎天天同方向，偶爾同分點其他客戶反向。

月報（已知內部人淨買賣 L 張，方向 B／S）
  1. 候選：同方向淨額 ≥ L 的 10%，而且一面倒：
       反向張數 ≤ 同方向的 35%；有每日資料時再要求：同方向天數 ≥ 有進出天數的一半、
       反向那幾天的淨額合計 ≤ 同方向那幾天合計的 15%
     前 30 天就已經同方向做了期間淨額一半以上的分點（本來就常買賣這檔的）排除；
     但如果前一個月這家公司內部人也同方向在買賣（連續出貨），不做這個排除。
  2. 淨額不超過 L 兩倍的候選，從大到小納入，合計達 L 的 85% 就停，最多 3 個；
     都超過兩倍時只取最接近 L 的一個（大分點，混了很多別人的單）。
  3. 吻合度 = 納入分點淨額合計 ÷ L
       高：0.85～2，而且納入的分點都有每日資料（逐日一面倒）
       中：0.6～3，而且都有每日資料
       低：0.3～6 但沒有每日資料（還沒查或不在候選範圍），或 0.3～0.6、3～6；其餘不列
     月報的分點前 15 名裡，隨便一個分點剛好落在 0.6～3 倍的機率不低，所以「中」以上一定要逐日也一面倒。
  公司層級：同一分點「高」一次或「中」兩次以上 → 已知內部人分點。

申報追蹤（事前申報的轉讓期間內，還沒有月報）
  列出這家公司已知內部人分點在期間內的賣超（進度 = 賣超合計 ÷ 申報張數），另列最多 2 個一面倒的可疑分點。
"""
from collections import defaultdict

MIN_SHARE = 0.10
MAX_OPP = 0.35
DIR_DAYS = 0.50
OPP_NET = 0.15
ENOUGH = 0.85
HIGH_MAX = 2.0
MID_MAX = 3.0
LOW_MAX = 6.0
MAX_PICK = 3


FOREIGN = ("美林", "摩根", "高盛", "花旗", "瑞銀", "麥格理", "法銀巴黎", "德意志", "野村", "大和", "瑞士信貸", "香港上海匯豐",
           "法國興業", "巴克萊", "星展", "新加坡商", "港商")


def _foreign(name):
    return any(k in (name or "") for k in FOREIGN)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sg(d):
    return 1 if d == "B" else -1


def _windows(brokers):
    """{(kind, code, ref): {"dir", "lots", "market", "in": {d1, d2, rows}, "pre": {…}}}"""
    out = {}
    for r in brokers:
        k = (r["kind"], r["code"], r["ref"])
        j = out.setdefault(k, {"dir": r["dir"], "lots": _f(r["lots"]), "market": r["market"]})
        w = j.setdefault(r["win"], {"d1": r["d1"], "d2": r["d2"], "rows": {}})
        if r.get("bid") and r["bid"] not in w["rows"]:  # 同一分點可能同時在買超、賣超榜（不會），保險起見只取一次
            w["rows"][r["bid"]] = {"bid": r["bid"], "broker": r["broker"], "buy": _f(r["buy"]), "sell": _f(r["sell"]),
                                   "net": _f(r["net"])}
    for j in out.values():
        for w in ("in", "pre"):
            if w in j:
                j[w]["rows"] = list(j[w]["rows"].values())
    return out


def _days(days):
    return {(r["kind"], r["code"], r["ref"], r["bid"]):
            tuple(int(_f(r[k])) for k in ("days", "buy_days", "sell_days", "buy_net", "sell_net")) for r in days}


def _dir(r, d, sg):
    """→ (同方向淨額, 同方向張數, 反向張數, 同方向天數, 反向天數)，d 是每日統計或 None"""
    dn = sg * r["net"]
    din, dout = (r["buy"], r["sell"]) if sg > 0 else (r["sell"], r["buy"])
    if d is None:
        return dn, din, dout, None, None
    return dn, din, dout, (d[1] if sg > 0 else d[2]), (d[2] if sg > 0 else d[1])


def one_sided(r, d, sg):
    dn, din, dout, _, _ = _dir(r, d, sg)
    if dn <= 0 or dout > MAX_OPP * din:
        return False
    if d is None:
        return True
    n, bd, sd, bn, sn = d
    dd, dnet, onet = (bd, bn, sn) if sg > 0 else (sd, sn, bn)
    return n > 0 and dd >= DIR_DAYS * n and onet <= OPP_NET * dnet


def _entry(r, d, sg):
    """[bid, broker, 同方向淨額, 同方向張數, 反向張數, 有進出天數, 同方向天數, 反向天數]"""
    dn, din, dout, dd, od = _dir(r, d, sg)
    return [r["bid"], r["broker"], int(dn), int(din), int(dout), d[0] if d else None, dd, od]


def _conf(cov, all_daily):
    if ENOUGH <= cov <= HIGH_MAX and all_daily:
        return "高"
    if 0.6 <= cov <= MID_MAX and all_daily:
        return "中"
    if 0.3 <= cov <= LOW_MAX:
        return "低"
    return ""


def _prev_month(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


def match_month(key, j, days, win_all):
    """月報一筆 → {"dir", "lots", "d1", "d2", "m": [entry…], "cov", "conf"} 或 None"""
    kind, code, ref = key
    lots, sg = j["lots"], _sg(j["dir"])
    w_in = j.get("in")
    if lots <= 0 or not w_in or not w_in["rows"]:
        return None
    prev = win_all.get(("m", code, _prev_month(ref)))
    pre_net = {}
    if j.get("pre") and not (prev and prev["dir"] == j["dir"]):
        pre_net = {r["bid"]: sg * r["net"] for r in j["pre"]["rows"]}
    dk = lambda r: days.get(key + (r["bid"],))  # noqa: E731
    cands = [r for r in w_in["rows"]
             if sg * r["net"] >= MIN_SHARE * lots and one_sided(r, dk(r), sg)
             and pre_net.get(r["bid"], 0) < 0.5 * sg * r["net"]]
    small = sorted((r for r in cands if sg * r["net"] <= HIGH_MAX * lots), key=lambda r: -sg * r["net"])
    picked, tot = [], 0.0
    for r in small[:MAX_PICK]:
        picked.append(r)
        tot += sg * r["net"]
        if tot >= ENOUGH * lots:
            break
    if not picked or tot < 0.6 * lots:
        big = sorted((r for r in cands if sg * r["net"] > HIGH_MAX * lots), key=lambda r: sg * r["net"])
        if big and (not picked or abs(sg * big[0]["net"] / lots - 1) < abs(tot / lots - 1)):
            picked, tot = [big[0]], sg * big[0]["net"]
    if not picked:
        return None
    cov = tot / lots
    conf = _conf(cov, all(dk(r) is not None for r in picked))
    if not conf:
        return None
    return {"dir": j["dir"], "lots": int(lots), "d1": w_in["d1"], "d2": w_in["d2"],
            "m": [_entry(r, dk(r), sg) for r in picked], "cov": round(cov, 3), "conf": conf}


def build(brokers, days=()):
    """→ {"match": {"代號|月份": …}, "known": {"代號": [[bid, broker, 高次數, 中次數, 最近月份, 合計張數, 方向]]},
          "live": [{code, market, ref, d1, d2, lots, known: [[bid, broker, 賣超 或 None]], sus: [entry…], prog}]}"""
    win = _windows(brokers)
    dd = _days(days)
    match, agg = {}, defaultdict(dict)
    for key, j in win.items():
        if key[0] != "m":
            continue
        m = match_month(key, j, dd, win)
        if not m:
            continue
        match[f"{key[1]}|{key[2]}"] = m
        if m["conf"] in ("高", "中"):
            for e in m["m"]:
                a = agg[key[1]].setdefault(e[0], [e[0], e[1], 0, 0, "", 0, ""])
                a[2 if m["conf"] == "高" else 3] += 1
                a[4] = max(a[4], key[2])
                a[5] += e[2]
                if m["dir"] not in a[6]:
                    a[6] = "".join(sorted(a[6] + m["dir"]))
    known = {c: sorted((a for a in v.values() if a[2] or a[3] >= 2), key=lambda a: (-a[2], -a[3], -a[5]))
             for c, v in agg.items()}
    known = {c: v for c, v in known.items() if v}
    # 只出現一次「中」的分點也留著當參考（標成 cand）
    cand = {c: [a for a in v.values() if not a[2] and a[3] < 2] for c, v in agg.items()}

    live = []
    for key, j in win.items():
        if key[0] != "t" or not j.get("in"):
            continue
        code, sg = key[1], _sg(j["dir"])
        rows = {r["bid"]: r for r in j["in"]["rows"]}
        ks = known.get(code, []) + cand.get(code, [])
        kn = []
        for a in ks:
            r = rows.get(a[0])
            kn.append([a[0], a[1], int(sg * r["net"]) if r else None, 1 if a in known.get(code, []) else 0])
        kb = {a[0] for a in ks}
        sus = [r for r in j["in"]["rows"] if r["bid"] not in kb and (key + (r["bid"],)) in dd and not _foreign(r["broker"])
               and one_sided(r, dd[key + (r["bid"],)], sg)]
        sus.sort(key=lambda r: -sg * r["net"])
        done = sum(x[2] or 0 for x in kn if x[3] and (x[2] or 0) > 0)
        live.append({"code": code, "market": j["market"], "ref": key[2], "d1": j["in"]["d1"], "d2": j["in"]["d2"],
                     "lots": int(j["lots"]), "known": kn,
                     "sus": [_entry(r, dd[key + (r["bid"],)], sg) for r in sus[:2]],
                     "prog": round(done / j["lots"], 3) if j["lots"] and done else None})
    live.sort(key=lambda x: (x["d1"], x["code"]), reverse=True)
    return {"match": match, "known": known, "live": live}


def recent(known, daily_rows):
    """已知內部人分點最近幾天在自家股票的進出（分點每日前 15 名資料，data/broker/YYYY/YYYYMMDD.csv）
    → {"代號": [[bid, broker, 淨張數合計, 出現天數, 最近日期]]}"""
    want = {(c, a[0]) for c, v in known.items() for a in v}
    out = defaultdict(dict)
    for r in daily_rows:
        k = (r["code"], r["bid"])
        if k not in want:
            continue
        a = out[r["code"]].setdefault(r["bid"], [r["bid"], r["broker"], 0, 0, ""])
        a[2] += int(_f(r["net"]))
        a[3] += 1
        a[4] = max(a[4], r["date"])
    return {c: sorted(v.values(), key=lambda a: -abs(a[2])) for c, v in out.items()}
