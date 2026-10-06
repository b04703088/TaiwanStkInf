"""指數調整行事曆 → data/calendar.json（calendar.html 用）

把三種資料疊在同一張日曆上：
  1. 指數審核：臺灣指數公司日程表／定審結果、富時合編（臺灣50 等）、MSCI 臺灣指數（etf_site.build_tip）
  2. 預估審核：日程表還沒公布的，用去年同期（+52 週，同星期幾）推估，遇休市順延；標示 est
  3. ETF 換股期間：過去用實際偵測到的（fetch_etf_rebalance.py）；未來用該 ETF 通常的「相對生效日」期間推估

輸出：
  holidays {日期: 名稱}、hol_until（休市日已知到哪一年）、tdays（交易日序列，過去＝實際有行情的日子，未來＝平日扣休市）
  只放規模 MIN_AUM 億以上的 ETF（小型 ETF 換股對市場影響小）
  etfs {代號: [名稱, 規模(億), 通常開始差, 通常結束差, 定期調整次數]}
  reviews [[指數, 提供者, 公告日, 生效日, [ETF], est, 納入[[代號,名稱]], 刪除[[代號,名稱]],
            資料截止起, 資料截止迄, 截止規則說明, glob（全球指數：不管有沒有 ETF 都顯示）]]
  資料截止日規則見 scripts/index_rules.py；公告日不固定的（00891）公告日留空
  actual [[ETF, 開始, 結束, 生效日]]
"""
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import etf_site  # noqa: E402
import index_rules as IR  # noqa: E402
import rebalance_site  # noqa: E402

HORIZON = 200  # 往後推估幾天內的審核
MIN_AUM = 300  # 只放規模（億）達到這個門檻的 ETF；查不到規模的也不放


def _d(s):
    return date.fromisoformat(s)


def load_holidays(data_dir):
    p = Path(data_dir) / "calendar" / "holidays.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fp:
        return {r["date"]: r["name"] for r in csv.DictReader(fp)}


def trading_days(data_dir, holidays, today, ahead=HORIZON + 40):
    past = sorted(f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}" for f in Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")
                  if len(f.stem) == 8)
    out = [d for d in past if d <= today.isoformat()]
    d = _d(out[-1]) + timedelta(1) if out else today - timedelta(400)
    end = today + timedelta(ahead)
    while d <= end:
        if not is_holiday(d, holidays):
            out.append(d.isoformat())
        d += timedelta(1)
    return out


def is_holiday(d, holidays):
    """證交所還沒公布的年份，至少把元旦算進去"""
    return d.weekday() >= 5 or d.isoformat() in holidays or d.strftime("%m-%d") == "01-01"


def next_trading(d, holidays):
    while is_holiday(d, holidays):
        d += timedelta(1)
    return d


def project(reviews, holidays, today, horizon=HORIZON):
    """去年同期有審核、今年日程還沒出來的 → 推估（+364 天＝同一個星期幾）"""
    from fetch_tip_schedule import index_key
    by = {}
    for r in reviews:
        by.setdefault((r[1], index_key(r[0])), []).append(r)
    out = []
    for (prov, _), rs in by.items():
        anns = sorted(_d(r[2]) for r in rs if r[2])
        for r in rs:
            if not r[2] or not r[3]:
                continue
            a = _d(r[2]) + timedelta(364)
            if not (today < a <= today + timedelta(horizon)):
                continue
            if any(abs((x - a).days) <= 40 for x in anns):  # 已有正式日程
                continue
            a2 = next_trading(a, holidays)
            # 公告到生效隔幾個交易日，照去年
            gap, d = 0, _d(r[2])
            while d < _d(r[3]):
                d += timedelta(1)
                gap += not is_holiday(d, holidays)
            e2 = a2
            for _ in range(gap):
                e2 = next_trading(e2 + timedelta(1), holidays)
            out.append([r[0], prov, a2.isoformat(), e2.isoformat(), r[4], True, [], []] + r[8:9])
            anns.append(a2)
    return out


MSCI_TW = "MSCI 臺灣指數"
MSCI_CUSTOM = [("00878", "MSCI臺灣ESG永續高股息精選30指數"), ("00922", "MSCI台灣領袖50精選指數")]
ICE_NAME = "NYSE FactSet 臺灣ESG永續關鍵半導體指數"


def extra_reviews(reviews, cal, today):
    """臺灣指數公司日程表沒有的審核：MSCI 客製指數（跟 5/11 月半年度審核）、00891（ICE）、富時全球"""
    out = []
    for r in reviews:
        if r[1] == "MSCI" and r[0].startswith(MSCI_TW) and r[2] and int(r[2][5:7]) in (5, 11):
            for etf, name in MSCI_CUSTOM:
                out.append([name, "MSCI", r[2], r[3], [etf], r[5], [], []])
    for eff in IR.ice_reviews(cal, today - timedelta(400), today + timedelta(HORIZON)):
        out.append([ICE_NAME, "ICE", "", eff.isoformat(), ["00891"], eff > today, [], []])
    for rv, cut, ann, eff, est in IR.FTSE_GEIS:
        out.append([IR.GEIS_NAME, "FTSE", ann, eff, [], est, [], [], cut])
    return out


def add_cutoffs(reviews, cal):
    from fetch_tip_schedule import index_key
    ftse = {index_key(x) for x in IR.FTSE_TWSE_INDEXES}
    for r in reviews:
        fixed = r[8] if len(r) > 8 else None
        del r[8:]
        rule = next((IR.RULES[c] for c in r[4] if c in IR.RULES), None)
        if rule is None and r[1] == "FTSE" and index_key(r[0]) in ftse:
            rule = IR.FTSE_TWSE
        if rule is None and r[0].startswith(MSCI_TW):
            rule = IR.RULES["0057"]
        cut = None
        if fixed:
            cut, note = (fixed, fixed), IR.GEIS_NOTE
        elif rule:
            c = IR.cutoff(rule, r[2], r[3], cal)
            cut = (c[0].isoformat(), c[1].isoformat()) if c else None
            note = rule["note"]
        r += [cut[0], cut[1], note] if cut else ["", "", ""]
        r.append(r[0] == IR.GEIS_NAME or r[0].startswith(MSCI_TW))


def build(data_dir, root, today=None):
    data_dir, root = Path(data_dir), Path(root)
    today = today or date.today()
    tip = etf_site.build_tip(data_dir, root)
    if tip is None:
        return None
    holidays = load_holidays(data_dir)
    C = tip["cols"]
    reviews = []
    for x in tip["rows"]:
        r = dict(zip(C, x))
        if not r["ann"]:
            continue
        reviews.append([r["index"], r["prov"], r["ann"], r["eff"] or "", r["etfs"], False,
                        [a[:2] for a in (r["add"] or [])], [a[:2] for a in (r["del"] or [])]])
    past = [f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}" for f in data_dir.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")
            if len(f.stem) == 8]
    cal = IR.TradingCalendar(past, holidays)
    reviews += extra_reviews(reviews, cal, today)
    reviews += project(reviews, holidays, today)
    reviews.sort(key=lambda r: (r[2] or r[3], r[0]))
    add_cutoffs(reviews, cal)

    reb = rebalance_site.build(root) or {"etfs": []}
    aum = etf_site.build_aum(data_dir) if hasattr(etf_site, "build_aum") else None
    size = {}
    if aum:
        ac = aum["cols"]
        for x in aum["rows"]:
            r = dict(zip(ac, x))
            if r.get("aum"):
                size[r["etf"]] = round(r["aum"] / 1e8)
    typ = {x["etf"]: x for x in reb["etfs"]}
    for r in reviews:
        r[4] = [c for c in r[4] if (size.get(c) or 0) >= MIN_AUM]
    used = sorted({c for r in reviews for c in r[4]})
    etfs = {}
    for c in used:
        t = typ.get(c, {})
        etfs[c] = [tip["etfs"].get(c) or t.get("name", ""), size.get(c), t.get("start"), t.get("end"), t.get("n") or 0]
    actual = []
    for x in reb["etfs"]:
        for e in x["events"]:
            if e[8] == "regular":
                actual.append([x["etf"], e[0], e[1], e[3] or ""])
    hol_until = max((d[:4] for d in holidays), default="")
    keep = set(used)
    actual = [a for a in actual if a[0] in keep]
    return {"min_aum": MIN_AUM, "today": today.isoformat(), "updated": tip["updated"], "holidays": holidays, "hol_until": hol_until,
            "tdays": trading_days(data_dir, holidays, today), "etfs": etfs, "reviews": reviews, "actual": actual}


def write_calendar(data_dir, root, out_path):
    payload = build(data_dir, root)
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
