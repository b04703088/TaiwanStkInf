"""庫藏股 × 分點：從買回期間的分點買超推定公司派（公司實際下單買回）的分點。

輸入
  programs   data/treasury/programs.csv（fetch_treasury.py）
  brokers    data/treasury/brokers.csv（fetch_treasury_broker.py）：每個計畫「買回期間」與「買回前 60 天」的買超前 15 名
  days       data/treasury/broker_days.csv（同上）：候選分點在買回期間每天淨買／淨賣的天數

公司買回的特徵：整段期間幾乎每天都是淨買超，偶爾同分點其他客戶賣出，但賣超的天數和張數都少。

已結束的計畫（有公告實際買回張數 B）
  1. 候選：買回期間買超 ≥ B 的 10%，而且買進賣出很一面倒：
       有每日資料時：淨買超天數 ≥ 有進出天數的 60%、淨賣超那幾天的賣超合計 ≤ 淨買超那幾天買超合計的 15%、
                     賣出張數 ≤ 買進的 35%
       （公司沒下單的日子，同分點其他客戶零星賣幾張也會算一天淨賣超，所以賣超看張數不看天數）
       還沒有每日資料時：只看賣出張數 ≤ 買進的 35%
     買回前 60 天就已經買超達到期間買超一半以上的分點，是本來就常買這檔的人，排除；
     但買回前那段如果跟同一家公司的上一次買回期間重疊（連續買回），就不做這個排除。
  2. 從買超最多的候選開始納入，合計達到 B 的 85% 就停，最多 3 個分點。買超超過 B 也算（同分點還有別的買盤）。
  3. 吻合度 = 納入分點買超合計 ÷ B。
       高：吻合度 0.85～2，而且納入的分點都有每日資料、天天在買
       中：吻合度 ≥ 0.6（含超過 2 倍、或還沒有每日資料）
       低：吻合度 ≥ 0.3；其餘不列

執行中的計畫（還沒有實際張數）
  列出這家公司過去比對到（高、中）的分點在本次期間的買超，另外列最多 2 個符合上面「一面倒」條件的可疑分點。
"""
from collections import defaultdict

MIN_SHARE = 0.10      # 候選分點買超至少佔實際買回張數的比例
MAX_SELL = 0.35       # 賣出 ÷ 買進 上限
BUY_DAYS = 0.60       # 淨買超天數 ÷ 有進出天數 下限
SELL_NET = 0.15       # 淨賣超日賣超合計 ÷ 淨買超日買超合計 上限
ENOUGH = 0.85         # 合計達到實際張數的這個比例就停
HIGH_MAX = 2.0        # 吻合度超過這個倍數降為「中」
MAX_PICK = 3


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _windows(brokers):
    """{(market, code, board_date): {"in": {"d1", "d2", "rows":[…]}, "pre": {…}}}"""
    out = defaultdict(dict)
    for r in brokers:
        w = out[(r["market"], r["code"], r["board_date"])].setdefault(r["win"], {"d1": r["d1"], "d2": r["d2"], "rows": []})
        if r.get("bid"):
            w["rows"].append({"bid": r["bid"], "broker": r["broker"], "buy": _f(r["buy"]),
                              "sell": _f(r["sell"]), "net": _f(r["net"])})
    return out


def _days(days):
    """{(market, code, board_date, bid): (有進出天數, 淨買天數, 淨賣天數, 淨買日買超, 淨賣日賣超)}"""
    return {(r["market"], r["code"], r["board_date"], r["bid"]):
            tuple(int(_f(r[k])) for k in ("days", "buy_days", "sell_days", "buy_net", "sell_net")) for r in days}


def one_sided(r, d):
    """買超是否一面倒（公司買回的樣子）。d = _days 的值或 None"""
    if r["net"] <= 0 or r["sell"] > MAX_SELL * r["buy"]:
        return False
    if d is None:
        return True
    n, b, _, bn, sn = d
    return n > 0 and b >= BUY_DAYS * n and sn <= SELL_NET * bn


def _overlaps_other(p, programs_by_code, d1, d2):
    """d1～d2 是否跟同一家公司另一次買回期間重疊"""
    for q in programs_by_code.get(p["code"], []):
        if q is p or not q["start"]:
            continue
        if q["start"] <= d2 and (q["end"] or "9") >= d1:
            return True
    return False


def _entry(r, d):
    """[bid, broker, net, buy, sell, 天數, 淨買天數, 淨賣天數]（沒有每日資料時後三欄 None）"""
    return [r["bid"], r["broker"], int(r["net"]), int(r["buy"]), int(r["sell"])] + (list(d[:3]) if d else [None] * 3)


def match_program(p, win, days, programs_by_code):
    """已結束的計畫 → {"m": [entry…], "cov": 吻合度, "conf": 高/中/低, "d2"} 或 None"""
    lots = _f(p.get("bought_shares")) / 1000
    w_in = win.get("in")
    if lots <= 0 or not w_in or not w_in["rows"]:
        return None
    pre = win.get("pre")
    pre_net = {}
    if pre and not _overlaps_other(p, programs_by_code, pre["d1"], pre["d2"]):
        pre_net = {r["bid"]: r["net"] for r in pre["rows"]}
    key = (p["market"], p["code"], p["board_date"])
    cands = [r for r in w_in["rows"]
             if r["net"] >= MIN_SHARE * lots and one_sided(r, days.get(key + (r["bid"],)))
             and pre_net.get(r["bid"], 0) < 0.5 * r["net"]]
    cands.sort(key=lambda r: -r["net"])
    picked, tot = [], 0.0
    for r in cands[:MAX_PICK]:
        picked.append(r)
        tot += r["net"]
        if tot >= ENOUGH * lots:
            break
    if not picked:
        return None
    cov = tot / lots
    all_daily = all(key + (r["bid"],) in days for r in picked)
    conf = ("高" if ENOUGH <= cov <= HIGH_MAX and all_daily else
            "中" if cov >= 0.6 else "低" if cov >= 0.3 else "")
    if not conf:
        return None
    return {"m": [_entry(r, days.get(key + (r["bid"],))) for r in picked],
            "cov": round(cov, 3), "conf": conf, "d2": w_in["d2"]}


def build(programs, brokers, days=()):
    """→ (brk, co)
    brk  {"代號|決議日": {...}}  已結束：match_program 的結果；執行中：{"live": [entry + [已知]], "d2"}
    co   {"代號": [[bid, broker, 比對到次數, 最近決議日, 合計買超張數]]}  依次數、張數排序
    """
    win = _windows(brokers)
    dd = _days(days)
    by_code = defaultdict(list)
    for p in programs:
        by_code[p["code"]].append(p)

    brk, agg = {}, defaultdict(dict)
    for p in programs:
        if not p.get("bought_shares"):
            continue
        m = match_program(p, win.get((p["market"], p["code"], p["board_date"]), {}), dd, by_code)
        if not m:
            continue
        brk[f'{p["code"]}|{p["board_date"]}'] = m
        if m["conf"] in ("高", "中"):
            for e in m["m"]:
                a = agg[p["code"]].setdefault(e[0], [e[0], e[1], 0, "", 0])
                a[2] += 1
                a[3] = max(a[3], p["board_date"])
                a[4] += e[2]
    co = {c: sorted(v.values(), key=lambda a: (-a[2], -a[4])) for c, v in agg.items()}

    for p in programs:
        if p.get("bought_shares"):
            continue
        key = (p["market"], p["code"], p["board_date"])
        w_in = win.get(key, {}).get("in")
        if not w_in:
            continue
        rows = {r["bid"]: r for r in w_in["rows"]}
        known = [a[0] for a in co.get(p["code"], [])]
        live = []
        for a in co.get(p["code"], []):
            r = rows.get(a[0])
            live.append((_entry(r, dd.get(key + (r["bid"],))) if r else [a[0], a[1]] + [None] * 6) + [1])
        sus = [r for r in w_in["rows"] if r["bid"] not in known and one_sided(r, dd.get(key + (r["bid"],)))
               and (key + (r["bid"],)) in dd]
        sus.sort(key=lambda r: -r["net"])
        live += [_entry(r, dd.get(key + (r["bid"],))) + [0] for r in sus[:2]]
        if live:
            brk[f'{p["code"]}|{p["board_date"]}'] = {"live": live, "d2": w_in["d2"]}
    return brk, co
