"""市場大事行事曆 → data/events.json（events.html、盤後摘要「未來一週重要事件」用）

把站上各處的「未來會發生的事」跟美台總經數據疊在同一條時間軸：
  macro   美國／台灣經濟數據（config/macro_events.csv，官方年度發布時間表手動維護；est=1 是依往例推估）
  cb      央行：FOMC、台灣央行理監事會（同上 csv）
  rev     上市櫃月營收公布截止（每月 10 日，遇休市順延）
  earn    美股大廠財報（data/us/earnings.csv，Nasdaq 行事曆）、台股法說會（data/mops/calls.csv，只列大型股）
  settle  台指期月結算（每月第三個週三，遇休市順延；3/6/9/12 月是季結算）
  index   指數審核公告與生效（scripts/calendar_site.py，只列有 300 億以上 ETF 追蹤的、或 MSCI／富時全球指數）
  disp    處置股出關（data/alert/disposal.csv，同一天合併成一列）
  div     除權息（data/mops/exright.csv，只列大型股與大型 ETF）
  hol     台股／美股休市、選舉

時間一律換成台灣時間（美東 08:30 數據＝台灣 21:30 或 20:30，盤後 amc 財報＝台灣隔天清晨），
所以 date 是「台灣日曆上的那一天」。
輸出 {today, cats, events: [[date, time, cat, region, title, detail, imp(1–3), est, code]]}
  imp 3＝會動到大盤的（CPI、非農、FOMC、PCE、台灣央行、NVDA 財報、MSCI 審核、季結算），盤後摘要只撈 ≥2
"""
import csv
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

ET, TW = ZoneInfo("America/New_York"), ZoneInfo("Asia/Taipei")
BACK, AHEAD = 7, 120          # 往前留幾天、往後放幾天
BIG_LIQ = 30                  # 法說會／除權息只列近 5 日均成交值 ≥ 這個（億）的股票
CATS = {"macro": "經濟數據", "cb": "央行", "rev": "月營收", "earn": "財報法說", "settle": "期貨結算",
        "index": "指數調整", "disp": "處置出關", "div": "除權息", "hol": "休市選舉"}
WD = "一二三四五六日"
US_BIG = {"NVDA": 3, "AAPL": 2, "MSFT": 2, "GOOGL": 2, "AMZN": 2, "META": 2, "AVGO": 2, "AMD": 2, "TSLA": 2}
US_NAME = {"NVDA": "輝達", "AAPL": "蘋果", "MSFT": "微軟", "GOOGL": "Google", "AMZN": "亞馬遜", "META": "Meta",
           "AVGO": "博通", "AMD": "超微", "TSLA": "特斯拉", "QCOM": "高通", "MU": "美光", "INTC": "英特爾",
           "TSM": "台積電 ADR", "ARM": "Arm", "SMCI": "美超微", "DELL": "戴爾", "MRVL": "邁威爾", "ORCL": "甲骨文"}


def _read(p):
    p = Path(p)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _md(s):
    return f"{int(s[5:7])}/{int(s[8:10])}"


def to_tw(d, t, tz):
    """(日期, 'HH:MM', 'ET'|'TW') → (台灣日期, 台灣時間 'HH:MM' 或 '')"""
    if not t:
        return d, ""
    src = ET if tz == "ET" else TW
    x = datetime.combine(date.fromisoformat(d), time.fromisoformat(t), src).astimezone(TW)
    return x.date().isoformat(), x.strftime("%H:%M")


def macro_events(root):
    out = []
    for r in _read(Path(root) / "config" / "macro_events.csv"):
        d, t = to_tw(r["date"], r["time"], r["tz"])
        cat = {"data": "macro", "cb": "cb", "hol": "hol", "pol": "hol"}.get(r["kind"], "macro")
        det = []
        if r["period"]:
            det.append(r["period"] if not r["period"][:4].isdigit() else
                       (f"{r['period'][:4]} 年 Q{r['period'][5:]}" if "Q" in r["period"] else f"{int(r['period'][5:7])} 月份"))
        if r["tz"] == "ET" and r["time"]:
            det.append(f"美東 {_md(r['date'])} {r['time']}")
        if r["src"]:
            det.append(r["src"])
        out.append([d, t, cat, r["region"], r["title"], "・".join(det), int(r["imp"] or 1), bool(r["est"]), ""])
    return out


def revenue_deadlines(holidays, start, end):
    import calendar_site as CS
    out, y, m = [], start.year, start.month
    while True:
        d = CS.next_trading(date(y, m, 10), holidays)
        if d > end:
            break
        if d >= start:
            pm = 12 if m == 1 else m - 1
            out.append([d.isoformat(), "", "rev", "TW", f"上市櫃 {pm} 月營收公布截止", "多數公司在 1–10 日間陸續公布", 2, False, ""])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def settle_events(holidays, start, end):
    import calendar_site as CS
    from futures_site import third_wed
    out, y, m = [], start.year, start.month
    while True:
        d = CS.next_trading(third_wed(y, m), holidays)
        if d > end:
            break
        if d >= start:
            q = m in (3, 6, 9, 12)
            out.append([d.isoformat(), "13:30", "settle", "TW", ("台指期季結算" if q else "台指期月結算") + f"（{m} 月）",
                        "台指期、台指選、股票期貨同日結算；結算價取 13:00–13:30 現股成交量加權平均", 3 if q else 2, False, ""])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def us_earnings(data_dir, root, start, end):
    watch = {r["us"] for r in _read(Path(root) / "config" / "us_supply.csv")}
    out = []
    for r in _read(Path(data_dir) / "us" / "earnings.csv"):
        if r["symbol"] not in watch and r["symbol"] not in US_NAME:
            continue
        t = r.get("time") or ""
        # amc（盤後）＝台灣隔天清晨；bmo（盤前）＝台灣當天晚上
        d, hhmm = to_tw(r["date"], {"amc": "16:05", "bmo": "07:30"}.get(t, ""), "ET")
        if not (start.isoformat() <= d <= end.isoformat()):
            continue
        nm = US_NAME.get(r["symbol"], r["symbol"])
        when = {"amc": "美股盤後", "bmo": "美股盤前"}.get(t, "時間未定")
        out.append([d, hhmm, "earn", "US", f"{nm}（{r['symbol']}）財報", f"美東 {_md(r['date'])} {when}・Nasdaq 行事曆",
                    US_BIG.get(r["symbol"], 1), False, ""])
    return out


def _liq(data_dir):
    import liq_site
    files = sorted(f for f in Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(f.stem) == 8)
    return liq_site.build(files)["v"] if files else {}


def tw_calls(data_dir, liq, start, end):
    out, seen = [], set()
    for r in _read(Path(data_dir) / "mops" / "calls.csv"):
        d, c = r["date"], r["code"]
        if not (start.isoformat() <= d <= end.isoformat()) or (d, c) in seen:
            continue
        v = liq.get(c, 0)
        if v < BIG_LIQ and c != "2330":
            continue
        seen.add((d, c))
        imp = 3 if c == "2330" else 2 if v >= 100 else 1
        place = (r.get("place") or "").strip()
        out.append([d, (r.get("time") or "")[:5], "earn", "TW", f"{c} {r['name']} 法說會", place, imp, False, c])
    return out


def exrights(data_dir, liq, big_etfs, start, end):
    out = []
    for r in _read(Path(data_dir) / "mops" / "exright.csv"):
        d, c = r["ex_date"], r["code"]
        if not (start.isoformat() <= d <= end.isoformat()):
            continue
        if liq.get(c, 0) < BIG_LIQ and c not in big_etfs:
            continue
        amt = []
        if r.get("cash"):
            amt.append(f"現金 {float(r['cash']):g} 元")
        if r.get("stock"):
            amt.append(f"股票 {float(r['stock']):g} 元")
        out.append([d, "", "div", "TW", f"{c} {r['name']} {r['kind']}", "・".join(amt), 1, False, c])
    return out


def disposal_exits(data_dir, start, end):
    import alert_site
    hp = Path(data_dir) / "no_trading_days.txt"
    hol = set(hp.read_text(encoding="utf-8").split()) if hp.exists() else set()
    disp = [x for x in _read(Path(data_dir) / "alert" / "disposal.csv") if alert_site.is_stock(x["code"]) and x.get("end")]
    for x in disp:
        x["exit"] = alert_site.next_open(x["end"], hol)
    by = {}
    for c in alert_site.upcoming_exits(disp, (start - timedelta(1)).isoformat(), end.isoformat()):
        by.setdefault(c["exit"], []).append(c)
    out = []
    for d, cs in sorted(by.items()):
        names = "、".join(f"{c['code']} {c['name']}" for c in cs[:12]) + ("…" if len(cs) > 12 else "")
        out.append([d, "", "disp", "TW", f"處置股出關 {len(cs)} 檔", names, 1, False, ",".join(c["code"] for c in cs)])
    return out


def index_events(data_dir, root, start, end):
    import calendar_site as CS
    cal = CS.build(data_dir, root, today=date.today())
    if not cal:
        return [], {}, set()
    etfs = cal["etfs"]
    out = []
    for r in cal["reviews"]:
        name, prov, ann, eff, codes, est = r[0], r[1], r[2], r[3], r[4], r[5]
        glob = r[-1]
        if not codes and not glob:
            continue
        msci = name.startswith(CS.MSCI_TW)
        imp = 3 if msci else 2 if (glob or any((etfs.get(c, [None, 0])[1] or 0) >= 1000 for c in codes)) else 1
        who = "、".join(f"{c} {etfs[c][0]}" for c in codes[:3] if c in etfs)
        short = name.replace("臺灣指數公司", "").replace("（MSCI Taiwan Index）", "")
        if ann and start.isoformat() <= ann <= end.isoformat():
            det = "追蹤 ETF：" + who if who else ""
            if r[6] or r[7]:
                det = f"已公告：納入 {len(r[6])}、刪除 {len(r[7])}" + ("・" + det if det else "")
            out.append([ann, "", "index", "TW", f"{short} 審核公告", det, imp, bool(est), ",".join(codes)])
        if eff and start.isoformat() <= eff <= end.isoformat() and eff != ann:
            out.append([eff, "", "index", "TW", f"{short} 生效", ("追蹤 ETF：" + who) if who else "", max(1, imp - 1), bool(est),
                        ",".join(codes)])
    return out, cal["holidays"], {c for c, v in etfs.items() if (v[1] or 0) >= 1000}


def build(data_dir, root, today=None):
    import calendar_site as CS
    data_dir, root = Path(data_dir), Path(root)
    today = today or date.today()
    start, end = today - timedelta(BACK), today + timedelta(AHEAD)
    try:
        idx, holidays, big_etfs = index_events(data_dir, root, start, end)
    except Exception as e:  # 指數資料壞掉不要拖垮整頁
        print("events index:", e)
        idx, holidays, big_etfs = [], CS.load_holidays(data_dir), set()
    liq = _liq(data_dir)
    ev = macro_events(root) + revenue_deadlines(holidays, start, end) + settle_events(holidays, start, end)
    ev += us_earnings(data_dir, root, start, end) + tw_calls(data_dir, liq, start, end)
    ev += exrights(data_dir, liq, big_etfs, start, end) + disposal_exits(data_dir, start, end) + idx
    for d, nm in holidays.items():
        dd = date.fromisoformat(d)
        if start <= dd <= end and dd.weekday() < 5:
            ev.append([d, "", "hol", "TW", f"台股休市（{nm}）", "", 2, False, ""])
    ev = [e for e in ev if start.isoformat() <= e[0] <= end.isoformat()]
    ev.sort(key=lambda e: (e[0], e[1] or "99", -e[6], e[4]))
    return {"today": today.isoformat(), "cats": CATS, "events": ev}


def upcoming(payload, days=7, min_imp=2):
    """盤後摘要用：今天之後 days 天內（日曆天）重要度 ≥ min_imp 的事件"""
    t = date.fromisoformat(payload["today"])
    hi = (t + timedelta(days)).isoformat()
    return [e for e in payload["events"] if t.isoformat() < e[0] <= hi and e[6] >= min_imp and e[2] not in ("index", "disp")]


def weekday(d):
    return WD[date.fromisoformat(d).weekday()]


def write_events(data_dir, root, out_path):
    payload = build(data_dir, root)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
