#!/usr/bin/env python3
"""外資研究報告（評等、目標價）與 FactSet 市場共識，從鉅亨網新聞整理。

資料來源（公開、免登入）
  鉅亨網新聞 API  https://api.cnyes.com/media/api/v1/newslist/category/<分類>
    分類：tw_stock（台股新聞，一天約 100～300 則）、tw_quo（台股盤勢）
    以「一天」為查詢區間逐頁抓（API 每頁最多 30 則、最多翻約 32 頁，所以不能一次查一個月）；
    可回查好幾年。新聞內文直接在列表裡，不必另外抓單篇。

整理出兩種資料
  1. 外資個股報告：內文同一句提到外資券商（高盛、大摩、小摩、美銀、花旗、瑞銀…或「外資」「美系外資」），
     又有台股目標價（新台幣）或投資評等 → 一檔股票一家券商一列。
     只收新聞看得到的部分：目標價、前次目標價、評等、調升／調降／維持。
  2. FactSet 市場共識：鉅亨網「Factset 最新調查」自動快訊（台股），格式固定：
     - EPS 預估：分析師人數、預估年度、中位數前值→新值、最高／最低、共識目標價
     - 目標價估值：中位數前值→新值、調整幅度、最高／最低、看多／中立／看空家數、當日收盤價

輸出 data/analyst/
  reports_<YYYY>.csv    date, time, news_id, broker, code, name, action, rating, target, prev_target, title, url
  consensus_<YYYY>.csv  date, time, news_id, code, name, kind(eps/tp), year, analysts, prev, value, chg_pct,
                        high, low, target, bull, neutral, bear, close, url
  days.txt              已抓完的日期（今天、昨天每次都重抓；之前的日期抓過就跳過）

只存標題、連結與數字，不存新聞內文。

用法
  python fetch_analyst.py                        # 最近 3 天
  python fetch_analyst.py --days 30              # 最近 30 天
  python fetch_analyst.py --start 2025-10-01 --end 2026-09-30 --max-minutes 50   # 回補（可分次跑，會接續）
"""
import argparse
import csv
import html
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "analyst"
API = "https://api.cnyes.com/media/api/v1/newslist/category/{cat}"
CATEGORIES = ("tw_stock", "tw_quo")
NEWS_URL = "https://news.cnyes.com/news/id/{id}"
DELAY = 0.4

REPORT_COLS = ["date", "time", "news_id", "broker", "code", "name", "action", "rating",
               "target", "prev_target", "title", "url"]
CONS_COLS = ["date", "time", "news_id", "code", "name", "kind", "year", "analysts", "prev", "value",
             "chg_pct", "high", "low", "target", "bull", "neutral", "bear", "close", "url"]

# 券商：(標準名稱, 新聞裡的寫法)。順序有意義：長的寫法先比對。
BROKERS = [
    ("摩根士丹利", ["摩根士丹利", "大摩", "Morgan Stanley"]),
    ("摩根大通", ["摩根大通", "小摩", "JPMorgan", "J.P. Morgan", "摩根證券"]),
    ("高盛", ["高盛", "Goldman Sachs", "Goldman"]),
    ("美銀", ["美銀美林", "美國銀行", "美銀證券", "美銀", "美林", "BofA"]),
    ("花旗", ["花旗環球", "花旗", "Citi"]),
    ("瑞銀", ["瑞銀", "UBS"]),
    ("野村", ["野村證券", "野村"]),
    ("麥格理", ["麥格理", "Macquarie"]),
    ("匯豐", ["匯豐", "HSBC"]),
    ("里昂", ["里昂", "CLSA"]),
    ("德意志", ["德意志", "德銀", "Deutsche"]),
    ("巴克萊", ["巴克萊", "Barclays"]),
    ("伯恩斯坦", ["伯恩斯坦", "Bernstein"]),
    ("傑富瑞", ["傑富瑞", "杰富瑞", "Jefferies"]),
    ("瑞穗", ["瑞穗", "Mizuho"]),
    ("大和", ["大和資本", "大和總研", "Daiwa"]),
    ("日興", ["SMBC日興", "日興證券", "日興"]),
    ("三菱日聯", ["三菱日聯", "MUFG"]),
    ("富國", ["富國銀行", "富國證券", "Wells Fargo"]),
    ("美系外資", ["美系外資", "美系券商", "美系投行"]),
    ("日系外資", ["日系外資", "日系券商"]),
    ("港系外資", ["港系外資", "港系券商"]),
    ("歐系外資", ["歐系外資", "歐系券商"]),
    ("外資", ["外資"]),  # 不具名；只在同一句有新台幣目標價時才收
]
GENERIC = {"外資"}
REGIONAL = {"美系外資", "日系外資", "港系外資", "歐系外資"}  # 同句有具名券商時只是形容詞，不另記
# 同名但不是券商研究部門的寫法，比對前先拿掉
NOT_BROKER = re.compile(r"(?:野村|摩根|富蘭克林|貝萊德|瑞銀|匯豐|日興)(?:投信|資產管理|資產|基金|ETF)|"
                        r"外資(?:買超|賣超|加碼|減碼|持股|連\d|今|昨|轉|大|狂|也|則|期|空單|多單|淨|進出|動向|圈|法人|銀行)|"
                        r"三大法人")

RATINGS = [
    ("買進", ["買進", "買入", "Buy", "強力買進", "Strong Buy"]),
    ("加碼", ["加碼", "增持", "優於大盤", "跑贏大盤", "Overweight", "Outperform"]),
    ("中立", ["中立", "持有", "Neutral", "Hold", "Equal-weight", "Market Perform", "與大盤同步"]),
    ("減碼", ["減碼", "減持", "劣於大盤", "落後大盤", "Underweight", "Underperform"]),
    ("賣出", ["賣出", "Sell"]),
]
_RATING_ALT = "|".join(re.escape(w) for _, ws in RATINGS for w in sorted(ws, key=len, reverse=True))
# 評等一定要跟「評等／評級」連在一起（避免「外資加碼 1 萬張」這種買賣超被當成評等）
RATING_RE = re.compile(
    rf"[「『“\"]\s*({_RATING_ALT})\s*[」』”\"]\s*(?:投資)?(?:評等|評級|建議)"
    rf"|(?:評等|評級|建議)\s*(?:為|至|調升至|調降至|上調至|下調至|升至|降至|維持)?\s*[「『“\"]?\s*({_RATING_ALT})"
    rf"|({_RATING_ALT})\s*(?:投資)?(?:評等|評級)", re.I)

UP = re.compile(r"調升|上調|調高|上修|提高|拉高|升至|喊高|大升")
DOWN = re.compile(r"調降|下調|調低|下修|降低|砍|降至")
KEEP = re.compile(r"維持|重申|不變")
INIT = re.compile(r"首次|首評|初次|首度給予|新納入")

NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"


# ---------- 共用 ----------

def text_of(item):
    """新聞內文：HTML 是兩層 escape（&lt;p&gt;），解開後去標籤。"""
    s = item.get("content") or ""
    for _ in range(2):
        s = html.unescape(s)
    s = re.sub(r"<(?:br|/p|/tr|/td|/li)[^>]*>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[ \t\r\n　\xa0]+", " ", s).strip()


def num(s):
    return C.num(s)


def when(item):
    dt = datetime.fromtimestamp(int(item["publishAt"]), C.TPE)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[。！？；])|\n", text) if s.strip()]


def load_names():
    """{名稱: 代號}，取最新一天的收盤檔（上市櫃全部）。"""
    files = sorted((ROOT / "data").glob("20[0-9][0-9]/*.csv"))
    names = {}
    for f in files[-1:]:
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                code, name = r["code"].strip(), r["name"].strip().replace("*", "")
                if re.fullmatch(r"\d{4}", code) and len(name) >= 2:  # 只要普通股
                    names.setdefault(name, code)
    return names


# ---------- FactSet 市場共識 ----------

FS_EPS = re.compile(
    r"共(\d+)位分析師，對(.+?)\((\d{4,6}[A-Z]?)-TW\)做出(\d{4})年EPS預估：中位數由" + r"(-?[\d.,]+)元(上修|下修)至(-?[\d.,]+)元"
    r"，其中最高估值(-?[\d.,]+)元，最低估值(-?[\d.,]+)元(?:，預估目標價為([\d.,]+)元)?")
FS_TP = re.compile(
    r"共(\d+)位分析師，對(.+?)\((\d{4,6}[A-Z]?)-TW\)提出目標價估值：中位數由([\d.,]+)元(上修|下修)至([\d.,]+)元"
    r"(?:，(?:調升|調降)幅度(-?[\d.]+)%)?[。，]其中最高估值([\d.,]+)元，最低估值([\d.,]+)元")
FS_VIEW = re.compile(r"積極樂觀(\d+)位、保持中立(\d+)位、保守悲觀(\d+)位")
FS_CLOSE = re.compile(r"-TW\)今\(\d+日?\)收盤價為([\d.,]+)元")


def is_factset(item):
    return bool(re.search(r"factset", item.get("title", ""), re.I)) and "-TW)" in item.get("title", "")


def parse_factset(item):
    t = text_of(item)
    d, hm = when(item)
    base = {"date": d, "time": hm, "news_id": item["newsId"], "url": NEWS_URL.format(id=item["newsId"])}
    m = FS_EPS.search(t)
    if m:
        n, name, code, yr, prev, _, val, hi, lo, tp = m.groups()
        return {**base, "code": code, "name": name, "kind": "eps", "year": yr, "analysts": n,
                "prev": num(prev), "value": num(val),
                "chg_pct": _pct(num(prev), num(val)), "high": num(hi), "low": num(lo), "target": num(tp)}
    m = FS_TP.search(t)
    if m:
        n, name, code, prev, way, val, pct, hi, lo = m.groups()
        row = {**base, "code": code, "name": name, "kind": "tp", "year": "", "analysts": n,
               "prev": num(prev), "value": num(val),
               "chg_pct": num(pct) if pct else _pct(num(prev), num(val)),
               "high": num(hi), "low": num(lo), "target": num(val)}
        if row["chg_pct"] is not None and way == "下修" and row["chg_pct"] > 0:
            row["chg_pct"] = -row["chg_pct"]
        v = FS_VIEW.search(t)
        if v:
            row.update(bull=v.group(1), neutral=v.group(2), bear=v.group(3))
        c = FS_CLOSE.search(t)
        if c:
            row["close"] = num(c.group(1))
        return row
    return None


def _pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return round((b - a) / abs(a) * 100, 2)


# ---------- 外資個股報告 ----------

def find_brokers(s):
    """句子裡的券商（標準名稱，依出現位置排序）。"""
    s = NOT_BROKER.sub(lambda m: "□" * len(m.group(0)), s)
    hits = []
    for std, words in BROKERS:
        for w in sorted(words, key=len, reverse=True):
            pat = re.escape(w) if not re.match(r"[A-Za-z]", w) else r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])"
            for m in re.finditer(pat, s):
                if any(a <= m.start() < b for a, b, _ in hits):
                    continue
                hits.append((m.start(), m.end(), std))
    named = {h[2] for h in hits if h[2] not in GENERIC | REGIONAL}
    # 「美系外資高盛」這種同句有具名券商時，不另外記「外資」「美系外資」
    out = []
    for a, b, std in sorted(hits):
        if (std in GENERIC and (named or any(h[2] in REGIONAL for h in hits))) or (std in REGIONAL and named):
            continue
        if std not in out:
            out.append(std)
    return out


def find_rating(s):
    m = RATING_RE.search(s)
    if not m:
        return ""
    word = next(g for g in m.groups() if g)
    for std, ws in RATINGS:
        if any(word.lower() == w.lower() for w in ws):
            return std
    return ""


def find_targets(s):
    """句子裡「目標價」之後的新台幣價格 → (前次, [新值…])。美元、港幣等跳過。"""
    i = s.find("目標價")
    if i < 0:
        return None, []
    tail = s[i:]
    tail = re.split(r"(?:EPS|每股盈餘|營收|毛利率)", tail)[0]
    vals = []
    for m in re.finditer(NUM + r"\s*(?:元|塊)", tail):
        before = tail[max(0, m.start() - 4):m.start()]
        after = tail[m.end():m.end() + 1]
        if re.search(r"美|港|日|人民幣|歐", tail[max(0, m.start() - 6):m.start()]) or after in ("美",):
            continue
        if "美元" in tail[m.start():m.end() + 2]:
            continue
        v = num(m.group(1))
        if v and v > 0:
            vals.append((m.start(), v, before))
    if not vals:
        return None, []
    prev = None
    m = re.search(r"(?:由|從)\s*(?:新台幣)?\s*" + NUM + r"\s*元?\s*(?:新台幣)?\s*(?:\S{0,6}?)(?:至|到|→|->)", tail)
    if m and len(vals) >= 2:
        prev = num(m.group(1))
        vals = [v for v in vals if not (v[1] == prev and v is vals[0])]
    return prev, [v[1] for v in vals]


def find_stocks(s, item_codes, names):
    """句子裡的台股 → [(位置, code, name)]。
    (2330-TW) 一定算；名稱比對：3 字以上直接比，2 字的名稱要是這篇新聞有標記的股票才算（避免「南亞」對到「東南亞」）。"""
    out = {}
    for m in re.finditer(r"(\S{1,8}?)\s*[\(（]\s*(\d{4,6}[A-Z]?)\s*-\s*TW\s*[\)）]", s):
        code = m.group(2)
        nm = next((n for n, c in names.items() if c == code), None) or re.sub(r"^.*[，、與和及跟對將]", "", m.group(1))
        out.setdefault(code, (m.start(), code, nm))
    for name, code in names.items():
        if code in out or len(name) < 2:
            continue
        for m in re.finditer(re.escape(name), s):
            j = m.start()
            if len(name) == 2 and code not in item_codes:
                # 2 字的名稱要前後都是斷詞處（「台光電與台燿「買進」」可以，「東南亞」裡的「南亞」不行）
                pre, post = s[j - 1:j], s[j + 2:j + 3]
                if (pre and _cjk(pre) and pre not in _EDGE) or (post and _cjk(post) and post not in _EDGE):
                    continue
            out[code] = (j, code, name)
            break
    # 長名稱包含短名稱時只留長的（例：「台積電」與「台積」）
    res = sorted(out.values())
    keep = []
    for a in res:
        if any(b is not a and a[2] in b[2] and len(b[2]) > len(a[2]) and b[0] <= a[0] < b[0] + len(b[2]) for b in res):
            continue
        keep.append(a)
    return keep


_EDGE = set("、與和及跟對將把給予持升降並也為是的「」『』（）()，,。目評股今在近仍")


def _cjk(ch):
    return "\u4e00" <= ch <= "\u9fff"


def item_codes(item, text):
    codes = {m.get("code") for m in (item.get("market") or []) if str(m.get("symbol", "")).startswith("TWS:")}
    codes |= set(re.findall(r"\((\d{4,6}[A-Z]?)-TW\)", text))
    for c in item.get("stock") or []:
        if re.fullmatch(r"\d{4,6}[A-Z]?", str(c)):
            codes.add(str(c))
    return {c for c in codes if c}


def parse_reports(item, names):
    """一篇新聞 → 外資報告列（同篇同股同券商只留一列，資訊合併）。"""
    if is_factset(item):
        return []
    title = re.sub(r"<[^>]+>", "", item.get("title", ""))
    text = text_of(item)
    if not re.search(r"目標價|評等|評級", title + text):
        return []
    codes = item_codes(item, text)
    d, hm = when(item)
    rows = {}
    for s in [title] + sentences(text):
        brokers = find_brokers(s)
        if not brokers:
            continue
        prev, tps = find_targets(s)
        rating = find_rating(s)
        if not tps and not rating:
            continue
        if all(b in GENERIC for b in brokers) and not tps:
            continue
        stocks = find_stocks(s, codes, names)
        if not stocks:
            # 句子沒寫股名：整篇只講一檔台股時歸給它
            if len(codes) == 1:
                c = next(iter(codes))
                nm = next((n for n, cc in names.items() if cc == c), "")
                stocks = [(0, c, nm)]
            else:
                continue
        stocks = [x for x in stocks if re.fullmatch(r"\d{4}", x[1])]  # 只要個股，不要 ETF
        if not stocks:
            continue
        # 目標價對應：幾檔股票就幾個價格時依序配對；只有一檔時取最後一個價格
        if len(stocks) > 1 and len(tps) == len(stocks):
            pairs = list(zip(stocks, tps))
        elif len(stocks) == 1:
            # 「由 3100 元調升至 3300 元」取後者；沒有前值時取第一個（後面的價格多半是別檔或情境價）
            pairs = [(stocks[0], (tps[-1] if prev else tps[0]) if tps else None)]
        else:
            pairs = [(st, None) for st in stocks] if rating and not tps else []
        action = ("initiate" if INIT.search(s) else "up" if UP.search(s) and tps else
                  "down" if DOWN.search(s) and tps else "maintain" if KEEP.search(s) else "")
        if prev and tps and not action:
            action = "up" if tps[-1] > prev else "down" if tps[-1] < prev else "maintain"
        if action in ("up", "down") and prev and tps and len(pairs) == 1:
            action = "up" if pairs[0][1] > prev else "down" if pairs[0][1] < prev else "maintain"
        for b in brokers:
            for (_, code, name), tp in pairs:
                key = (code, b)
                r = rows.setdefault(key, {
                    "date": d, "time": hm, "news_id": item["newsId"], "broker": b, "code": code, "name": name,
                    "action": "", "rating": "", "target": None, "prev_target": None,
                    "title": title, "url": NEWS_URL.format(id=item["newsId"])})
                r["target"] = r["target"] or tp
                r["prev_target"] = r["prev_target"] or (prev if len(pairs) == 1 else None)
                r["rating"] = r["rating"] or rating
                r["action"] = r["action"] or action
    out = [r for r in rows.values() if r["target"] or r["rating"]]
    # 同篇同股：有具名券商的話，不具名「外資」那列拿掉
    named = {r["code"] for r in out if r["broker"] not in GENERIC}
    return [r for r in out if not (r["broker"] in GENERIC and r["code"] in named)]


# ---------- 抓取 ----------

def fetch_day(day, cat):
    start = datetime(day.year, day.month, day.day, tzinfo=C.TPE)
    s, e = int(start.timestamp()), int((start + timedelta(days=1)).timestamp()) - 1
    items, page = [], 1
    while True:
        d = C.http(API.format(cat=cat), {"startAt": s, "endAt": e, "limit": 30, "page": page})
        it = d.get("items") or {}
        items += it.get("data") or []
        last = int(it.get("last_page") or 1)
        if page >= last:
            break
        page += 1
        time.sleep(DELAY)
    return items


def load_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["date"], r["time"], str(r["news_id"]), r.get("code", ""), r.get("broker", "")),
                  reverse=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) for k in cols})


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}" if abs(v) < 1e15 else f"{v:.0f}"
    return v


def merge(kind, cols, new_rows, keyf):
    by_year = {}
    for r in new_rows:
        by_year.setdefault(r["date"][:4], []).append(r)
    added = 0
    for yr, rows in by_year.items():
        path = OUT / f"{kind}_{yr}.csv"
        old = load_csv(path)
        days = {r["date"] for r in rows}
        ids = {str(r["news_id"]) for r in rows}
        # 重抓的日期：以新結果為準（新聞被刪或解析規則改了都會反映）
        keep = [r for r in old if r["date"] not in days and str(r["news_id"]) not in ids]
        before = {keyf(r) for r in old}
        added += sum(1 for r in rows if keyf(r) not in before)
        seen, merged = set(), []
        for r in rows + keep:
            k = keyf(r)
            if k not in seen:
                seen.add(k)
                merged.append(r)
        save_csv(path, cols, merged)
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=3, help="最近幾天（含今天）")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--max-minutes", type=float, default=0, help="回補時最多跑幾分鐘（0 = 不限）")
    ap.add_argument("--force", action="store_true", help="已抓過的日期也重抓")
    a = ap.parse_args()

    today = datetime.now(C.TPE).date()
    if a.start:
        d0 = date.fromisoformat(a.start)
        d1 = date.fromisoformat(a.end) if a.end else today
    else:
        d1, d0 = today, today - timedelta(days=a.days - 1)
    days_file = OUT / "days.txt"
    done = set(days_file.read_text().split()) if days_file.exists() else set()
    todo = []
    d = d1
    while d >= d0:
        # 今天、昨天的新聞可能還會增加，每次都重抓
        if a.force or d >= today - timedelta(days=1) or d.isoformat() not in done:
            todo.append(d)
        d -= timedelta(days=1)
    print(f"抓 {len(todo)} 天（{d0} ~ {d1}，略過已完成 {sum(1 for x in done if d0.isoformat() <= x <= d1.isoformat())} 天）")

    names = load_names()
    t0 = time.time()
    reports, cons, errors, finished = [], [], [], []
    for day in todo:
        if a.max_minutes and time.time() - t0 > a.max_minutes * 60:
            print(f"已達 {a.max_minutes} 分鐘上限，剩下的下次再抓")
            break
        try:
            items, seen = [], set()
            for cat in CATEGORIES:
                for it in fetch_day(day, cat):
                    if it["newsId"] not in seen:
                        seen.add(it["newsId"])
                        items.append(it)
                time.sleep(DELAY)
        except C.AdapterError as e:
            errors.append(f"{day}: {e}")
            print(f"  {day} 失敗：{e}", file=sys.stderr)
            continue
        nr = nc = 0
        for it in items:
            if is_factset(it):
                r = parse_factset(it)
                if r:
                    cons.append(r)
                    nc += 1
            else:
                rs = parse_reports(it, names)
                reports += rs
                nr += len(rs)
        finished.append(day.isoformat())
        print(f"  {day}：新聞 {len(items)} 則，外資報告 {nr} 列，FactSet {nc} 則")

    ra = merge("reports", REPORT_COLS, reports, lambda r: (str(r["news_id"]), r["code"], r["broker"]))
    ca = merge("consensus", CONS_COLS, cons, lambda r: (str(r["news_id"]),))
    done |= {x for x in finished if x < (today - timedelta(days=1)).isoformat()}
    OUT.mkdir(parents=True, exist_ok=True)
    days_file.write_text("\n".join(sorted(done)) + "\n")
    print(f"完成：外資報告 {len(reports)} 列（新增 {ra}），FactSet {len(cons)} 則（新增 {ca}），失敗 {len(errors)} 天")
    if errors and not finished:
        sys.exit(1)


if __name__ == "__main__":
    main()
