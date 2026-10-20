"""庫藏股 × 分點：從買回期間的分點買超推定公司派（公司實際下單買回）的分點。

輸入
  programs   data/treasury/programs.csv（fetch_treasury.py）
  brokers    data/treasury/brokers.csv（fetch_treasury_broker.py）：每個計畫「買回期間」與「買回前 60 天」的買超前 15 名

已結束的計畫（有公告實際買回張數 B）
  1. 候選：買回期間買超 ≥ B 的 10%，而且幾乎只買不賣（賣出 ≤ 買進的 35%；公司買回只買不賣，
     但同一分點的其他客戶會有一些賣出）。
     買回前 60 天就已經買超達到期間買超一半以上的分點，是本來就常買這檔的人，排除；
     但買回前那段如果跟同一家公司的上一次買回期間重疊（連續買回），就不做這個排除。
  2. 從買超最多的候選開始，加總不超過 B 的 115% 的就納入，最多 3 個分點。
  3. 吻合度 = 納入分點買超合計 ÷ B。0.85～1.15 為「高」，0.6 以上為「中」，0.3 以上為「低」，其餘不列。

執行中的計畫（還沒有實際張數）
  列出這家公司過去比對到（高、中）的分點在本次期間的買超，另外列最多 2 個「只買不賣」的可疑分點。
"""
from collections import defaultdict

MIN_SHARE = 0.10      # 候選分點買超至少佔實際買回張數的比例
MAX_SELL = 0.35       # 賣出 ÷ 買進 上限
CAP = 1.15            # 納入分點買超合計上限（÷ 實際買回張數）
MAX_PICK = 3
SUSPECT_SELL = 0.2    # 執行中計畫的可疑分點：賣出 ÷ 買進 上限


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def conf_of(cov):
    if 0.85 <= cov <= CAP:
        return "高"
    if 0.6 <= cov <= CAP:
        return "中"
    if 0.3 <= cov <= CAP:
        return "低"
    return ""


def _windows(brokers):
    """{(market, code, board_date): {"in": {"d2":…, "rows":[…]}, "pre": {…}}}"""
    out = defaultdict(dict)
    for r in brokers:
        w = out[(r["market"], r["code"], r["board_date"])].setdefault(r["win"], {"d1": r["d1"], "d2": r["d2"], "rows": []})
        if r.get("bid"):
            w["rows"].append({"bid": r["bid"], "broker": r["broker"], "buy": _f(r["buy"]),
                              "sell": _f(r["sell"]), "net": _f(r["net"])})
    return out


def _overlaps_other(p, programs_by_code, d1, d2):
    """d1～d2 是否跟同一家公司另一次買回期間重疊"""
    for q in programs_by_code.get(p["code"], []):
        if q is p or not q["start"]:
            continue
        if q["start"] <= d2 and (q["end"] or "9") >= d1:
            return True
    return False


def match_program(p, win, programs_by_code):
    """已結束的計畫 → {"m": [[bid, broker, net, buy, sell]], "cov": 吻合度, "conf": 高/中/低} 或 None"""
    lots = _f(p.get("bought_shares")) / 1000
    w_in = win.get("in")
    if lots <= 0 or not w_in or not w_in["rows"]:
        return None
    pre = win.get("pre")
    pre_net = {}
    if pre and not _overlaps_other(p, programs_by_code, pre["d1"], pre["d2"]):
        pre_net = {r["bid"]: r["net"] for r in pre["rows"]}
    cands = [r for r in w_in["rows"]
             if r["net"] >= MIN_SHARE * lots and r["sell"] <= MAX_SELL * r["buy"]
             and pre_net.get(r["bid"], 0) < 0.5 * r["net"]]
    cands.sort(key=lambda r: -r["net"])
    picked, tot = [], 0.0
    for r in cands:
        if len(picked) >= MAX_PICK:
            break
        if tot + r["net"] <= CAP * lots:
            picked.append(r)
            tot += r["net"]
    cov = tot / lots
    conf = conf_of(cov) if picked else ""
    if not conf:
        return None
    return {"m": [[r["bid"], r["broker"], int(r["net"]), int(r["buy"]), int(r["sell"])] for r in picked],
            "cov": round(cov, 3), "conf": conf, "d2": w_in["d2"]}


def build(programs, brokers):
    """→ (brk, co)
    brk  {"代號|決議日": {...}}  已結束：match_program 的結果；執行中：{"live": [[bid, broker, net, buy, sell, 已知]], "d2"}
    co   {"代號": [[bid, broker, 比對到次數, 最近決議日, 合計買超張數]]}  依次數、張數排序
    """
    win = _windows(brokers)
    by_code = defaultdict(list)
    for p in programs:
        by_code[p["code"]].append(p)

    brk, agg = {}, defaultdict(dict)
    for p in programs:
        if not p.get("bought_shares"):
            continue
        m = match_program(p, win.get((p["market"], p["code"], p["board_date"]), {}), by_code)
        if not m:
            continue
        brk[f'{p["code"]}|{p["board_date"]}'] = m
        if m["conf"] in ("高", "中"):
            for bid, name, net, _, _ in m["m"]:
                a = agg[p["code"]].setdefault(bid, [bid, name, 0, "", 0])
                a[2] += 1
                a[3] = max(a[3], p["board_date"])
                a[4] += net
    co = {c: sorted(v.values(), key=lambda a: (-a[2], -a[4])) for c, v in agg.items()}

    for p in programs:
        if p.get("bought_shares"):
            continue
        w_in = win.get((p["market"], p["code"], p["board_date"]), {}).get("in")
        if not w_in:
            continue
        rows = {r["bid"]: r for r in w_in["rows"]}
        known = [a[0] for a in co.get(p["code"], [])]
        live = []
        for a in co.get(p["code"], []):
            r = rows.get(a[0])
            live.append([a[0], a[1], int(r["net"]) if r else None, int(r["buy"]) if r else None,
                         int(r["sell"]) if r else None, 1])
        sus = [r for r in w_in["rows"] if r["bid"] not in known and r["net"] > 0 and r["sell"] <= SUSPECT_SELL * r["buy"]]
        sus.sort(key=lambda r: -r["net"])
        live += [[r["bid"], r["broker"], int(r["net"]), int(r["buy"]), int(r["sell"]), 0] for r in sus[:2]]
        if live:
            brk[f'{p["code"]}|{p["board_date"]}'] = {"live": live, "d2": w_in["d2"]}
    return brk, co
