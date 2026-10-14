"""data/alert/*.csv → 網頁用 data/alert/alert.json（欄位名 + 列，減少檔案大小）。

  disp   處置（近 DISP_DAYS 天公布的），新到舊
  att    注意（近 ATT_DAYS 個交易日），新到舊
  days   交易日（有任何注意公告的日子，含權證），網頁算「近 10／30 日注意次數」用
  near   最新一天的注意累計次數異常（再一次就可能處置）
  cand   本站依處置規則推算：下一個交易日再被列注意就會處置的股票（見 candidates），附最近回測命中率
  names  代號 → 名稱
只列股票與 ETF（權證、可轉債等不列，見 is_stock）。
"""
import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

DISP = ["market", "ann_date", "code", "start", "end", "reason", "measure", "interval"]
ATT = ["market", "date", "code", "clauses", "close", "pe", "info"]
NEAR = ["market", "code", "situation"]
CAND = ["market", "code", "rules", "need", "s1", "s8", "n10", "n30"]
BACKTEST_DAYS = 120  # 名單命中率回測最近幾個交易日
DISP_DAYS = 400
ATT_DAYS = 60


def is_stock(code):
    """股票 4 碼（含 DR）、ETF 00 開頭 4–6 碼可帶英文字尾；權證 6 碼、可轉債 5 碼不算。"""
    return bool(re.fullmatch(r"\d{4}|00\d{2,4}[A-Z]?", code or ""))


R18 = {str(k) for k in range(1, 9)}
RULES = {"s1": "連續 3 日第一款", "s8": "連續 5 日", "n10": "10 日內 6 次", "n30": "30 日內 12 次"}


def _counts(hits, days, i, since, w10=10, w30=30):
    """第 i 個交易日（含）往回：連續第一款天數、連續第一至八款天數、近 w10／w30 日第一至八款次數。
    只算上次處置公布日（since）之後的注意。hits: 日期 → 款次集合。"""
    def c1(k):
        return k >= 0 and days[k] > since and "1" in hits.get(days[k], ())

    def c8(k):
        return k >= 0 and days[k] > since and bool(hits.get(days[k], set()) & R18)

    def streak(f):
        n, j = 0, i
        while f(j):
            n, j = n + 1, j - 1
        return n
    return (streak(c1), streak(c8), sum(c8(k) for k in range(i - w10 + 1, i + 1)),
            sum(c8(k) for k in range(i - w30 + 1, i + 1)))


def is_disposed(c):
    """證交所、櫃買處置標準（依注意公告款次）：連續 3 日第一款、連續 5 日第一至八款、
    10 日內 6 日、30 日內 12 日第一至八款。用 2025 年起的資料回測，與實際處置公告完全吻合。"""
    s1, s8, n10, n30 = c
    return s1 >= 3 or s8 >= 5 or n10 >= 6 or n30 >= 12


def _index(att, disp, d):
    hits, last = {}, {}
    for a in att:
        if a["date"] <= d:
            hits.setdefault((a["market"], a["code"]), {})[a["date"]] = set((a.get("clauses") or "").split(";"))
    for x in disp:
        k = (x["market"], x["code"])
        if x["ann_date"] <= d and x["ann_date"] > last.get(k, ""):
            last[k] = x["ann_date"]
    return hits, last


def candidates(att, disp, days, i=None):
    """第 i 個交易日收盤後：下一個交易日只要再被列注意（need：第一款 "1"，或第一至八款任一 "1-8"）就會處置的股票。
    回傳 [{market, code, rules, need, s1, s8, n10, n30}]，n10／n30 是到今天為止的次數。"""
    i = len(days) - 1 if i is None else i
    if i < 0:
        return []
    hits, last = _index(att, disp, days[i])
    out = []
    for (mk, code), h in hits.items():
        since = last.get((mk, code), "")
        s1, s8, n10, n30 = _counts(h, days, i, since)
        _, _, m9, m29 = _counts(h, days, i, since, 9, 29)  # 明天的 10／30 日窗口裡，今天以前的部分
        rules = [r for r, ok in (("s1", s1 == 2), ("s8", s8 == 4), ("n10", m9 >= 5), ("n30", m29 >= 11)) if ok]
        if rules and not is_disposed((s1, s8, n10, n30)):
            out.append({"market": mk, "code": code, "rules": rules, "need": "1" if rules == ["s1"] else "1-8",
                        "s1": s1, "s8": s8, "n10": n10, "n30": n30})
    return sorted(out, key=lambda r: (-len(r["rules"]), r["code"]))


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _v(k, v):
    if v in (None, ""):
        return None
    if k == "interval":
        return int(v)
    if k in ("close", "pe"):
        try:
            return float(v)
        except ValueError:
            return None
    return v


def backtest(att, disp, days, n=BACKTEST_DAYS):
    """最近 n 個交易日，名單上的股票隔一個交易日就被公布處置的比例：(命中, 名單總數)"""
    ann = {(d["ann_date"], d["market"], d["code"]) for d in disp}
    hit = tot = 0
    for i in range(max(30, len(days) - 1 - n), len(days) - 1):
        for c in candidates(att, disp, days, i):
            tot += 1
            hit += (days[i + 1], c["market"], c["code"]) in ann
    return hit, tot


def build(disp, att, near):
    days = sorted({a["date"] for a in att if a.get("date")})  # 含權證，才不會漏掉交易日
    generated = max([days[-1] if days else ""] + [d["ann_date"] for d in disp if d.get("ann_date")]) or None
    names = {}
    for r in disp + att + near:
        if is_stock(r.get("code")) and r.get("name"):
            names[r["code"]] = r["name"]
    s_att = [a for a in att if is_stock(a["code"]) and a.get("date")]
    s_disp = [d for d in disp if is_stock(d["code"]) and d.get("ann_date")]
    cand = candidates(s_att, s_disp, days)
    hit, tot = backtest(s_att, s_disp, days)
    cut = (date.fromisoformat(generated) - timedelta(days=DISP_DAYS)).isoformat() if generated else ""
    disp = sorted((d for d in disp if is_stock(d["code"]) and d["ann_date"] >= cut),
                  key=lambda d: (d["ann_date"], d["start"], d["code"]), reverse=True)
    keep = set(days[-ATT_DAYS:])
    att = sorted((a for a in att if is_stock(a["code"]) and a["date"] in keep),
                 key=lambda a: (a["date"], a["code"]), reverse=True)
    nd = max((n["date"] for n in near if n.get("date")), default=None)
    near = [n for n in near if n.get("date") == nd and is_stock(n["code"])]
    return {"generated": generated, "days": days[-ATT_DAYS:], "names": names,
            "disp": {"cols": DISP, "rows": [[_v(k, d.get(k)) for k in DISP] for d in disp]},
            "att": {"cols": ATT, "rows": [[_v(k, a.get(k)) for k in ATT] for a in att]},
            "near": {"date": nd, "cols": NEAR, "rows": [[n.get(k) for k in NEAR] for n in near]},
            "cand": {"date": days[-1] if days else None, "hit": hit, "total": tot, "cols": CAND,
                     "rows": [[";".join(c[k]) if k == "rules" else c[k] for k in CAND] for c in cand]}}


def write_alert(data_dir, out_path):
    d = Path(data_dir) / "alert"
    if not (d / "disposal.csv").exists() and not (d / "attention.csv").exists():
        return None
    payload = build(_read(d / "disposal.csv"), _read(d / "attention.csv"), _read(d / "near.csv"))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
