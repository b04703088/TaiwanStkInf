"""各頁「資料日期」：每份資料最新是哪一天，寫成 data/asof.json，由 nav.js 顯示在每頁標題下面。

來源還沒公布（或還沒抓到）時，頁面上的數字其實是前一天的；這裡把每份資料的日期跟
最新收盤行情的交易日（基準日）比，每天都該有的資料落後基準日就標成「未更新」。

asof.json
  ref       基準日（最新收盤行情日期 YYYY-MM-DD）
  datasets  {key: {label, date, kind, note, daily}}
            kind = day（日期）／month（YYYY-MM）／quarter（YYYYQn）／time（YYYY-MM-DD HH:MM 抓取時間）
            daily = true 表示每個交易日都該更新，落後 ref 就標未更新
  pages     {頁名: [key, ...]}（頁名 = 檔名去掉 .html）
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

_DAY = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:-am)?\.(?:csv|md)$")


def _iso(name):
    m = _DAY.match(name)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def latest_file_date(*globs):
    """data 底下符合 glob 的檔名（YYYYMMDD.csv／.md）裡最新的日期。"""
    best = None
    for g in globs:
        for p in DATA.glob(g):
            d = _iso(p.name)
            if d and (best is None or d > best):
                best = d
    return best


def max_col(path, col="date"):
    """CSV 某一欄（日期）的最大值；檔案不存在回 None。"""
    p = DATA / path
    if not p.exists():
        return None
    best = None
    with p.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            v = (r.get(col) or "").strip()[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", v) and (best is None or v > best):
                best = v
    return best


def last_line(path):
    p = DATA / path
    if not p.exists():
        return None
    lines = [x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    v = max(lines) if lines else None
    if v and re.match(r"^\d{8}$", v):
        v = f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return v[:10] if v else None


def generated(path):
    p = DATA / path
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("generated")
    except (OSError, ValueError):
        return None


def sbl_date():
    """借券／當沖：最新一個借券欄有填的法人檔（證交所約 21:00 才公布，傍晚那次先留空）。"""
    files = sorted(DATA.glob("chips/[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name, reverse=True)
    for p in files[:5]:
        with p.open(encoding="utf-8", newline="") as f:
            if any((r.get("sbl_sell") or "").strip() for r in csv.DictReader(f)):
                return _iso(p.name)
    return None


def etf_date():
    """ETF 持股：所有 ETF 最新持股日的最大值，加上「幾檔已到這天」。"""
    latest = {}
    for d in DATA.glob("etf/*/"):
        days = [x for x in (_iso(p.name) for p in d.glob("[0-9]*.csv")) if x]
        if days:
            latest[d.name] = max(days)
    if not latest:
        return None, ""
    top = max(latest.values())
    n = sum(1 for v in latest.values() if v == top)
    note = f"{n}/{len(latest)} 檔" if n < len(latest) else ""
    return top, note


def latest_period(glob, pat):
    best = None
    for p in DATA.glob(glob):
        m = re.match(pat, p.name)
        if m and (best is None or m[1] > best):
            best = m[1]
    return best


def datasets():
    out = {}

    def add(key, label, date, kind="day", daily=False, note=""):
        if date:
            out[key] = {"label": label, "date": date, "kind": kind, "daily": daily, "note": note}

    add("price", "股價", latest_file_date("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), daily=True)
    add("broker", "分點", latest_file_date("broker/[0-9][0-9][0-9][0-9]/[0-9]*[0-9].csv"), daily=True)
    add("watch", "重點分點", latest_file_date("broker/watch/*/[0-9]*.csv"), daily=True)
    add("chips", "法人", latest_file_date("chips/*/[0-9]*.csv"), daily=True)
    add("sbl", "借券／當沖", sbl_date(), daily=True)
    add("margin", "融資券", latest_file_date("margin/[0-9][0-9][0-9][0-9]/[0-9]*.csv"), daily=True)
    add("pledge", "擔保品", latest_file_date("pledge/*/[0-9]*.csv"), daily=True)
    add("futures", "期交所", max_col("futures/tx.csv"), daily=True)
    add("alert", "處置／注意", max(filter(None, [max_col("alert/attention.csv"),
                                               max_col("alert/disposal.csv", "ann_date")]), default=None), daily=True)
    d, note = etf_date()
    add("etf", "ETF 持股", d, note=note)  # 各投信公布時間不同，部分隔天早上才有，不標未更新
    add("mops", "重訊", last_line("mops/days.txt"))
    add("cb", "可轉債公告", last_line("cb/mops_days.txt"))
    add("analyst", "法人報告", last_line("analyst/days.txt"))
    add("treasury", "庫藏股", generated("treasury/sources.json"), kind="time")
    add("insider_m", "內部人月申報", latest_period("insider/trades/*.csv", r"^(\d{6})\.csv$"), kind="month")
    add("insider_t", "轉讓申報", max_col("insider/transfer/%s.csv" % (latest_period("insider/transfer/*.csv", r"^(\d{4})\.csv$") or "x")))
    add("revenue", "月營收", latest_period("financials/revenue/*.csv", r"^(\d{6})"), kind="month")
    add("quarterly", "季報", latest_period("financials/quarterly/*.csv", r"^(\d{4}Q\d)"), kind="quarter")
    add("tdcc", "集保", latest_file_date("tdcc/[0-9]*.csv"))
    add("commod", "原物料", max_col("commod/daily.csv"))
    add("macro", "匯率／美債", max_col("macro/daily.csv"))
    add("us", "美股", max_col("us/daily.csv"))
    add("digest", "盤後摘要", latest_file_date("digest/[0-9]*.md"), daily=True)
    add("note", "判讀", latest_file_date("digest/notes/[0-9]*.md"))
    add("industry", "產業分類", generated("industry/sources.json"), kind="time")
    return out


PAGES = {
    "index": ["price", "broker", "chips", "etf", "alert", "insider_t"],
    "market": ["price", "margin", "futures"], "daytrade": ["chips", "broker"], "etfcrowd": ["etf", "price"], "ranking": ["price"], "flow": ["price"], "rotation": ["price"], "newhigh": ["price"], "limitup": ["price"],
    "industry": ["price", "industry"], "kline": ["price", "chips", "broker"],
    "screen": ["price", "chips", "revenue", "quarterly"],
    "chips": ["chips", "sbl", "tdcc"], "trust": ["chips", "price"], "futures": ["futures"], "settle": ["futures", "price"],
    "broker": ["broker"], "local": ["broker"], "watch": ["watch"],
    "margin": ["margin", "pledge"], "cost": ["etf", "margin", "pledge", "price"], "heavy": ["etf", "margin", "pledge", "price"],
    "insider": ["insider_m", "insider_t"], "news": ["mops"], "alert": ["alert"],
    "treasury": ["treasury", "broker"], "cb": ["cb", "price"], "cb-broker": ["cb", "broker"],
    "digest": ["digest", "note", "chips", "margin"], "stock": ["price", "chips", "broker", "mops"],
    "fin": ["revenue", "quarterly"], "analyst": ["analyst"],
    "etf": ["etf"], "calendar": ["etf"], "events": ["us", "mops", "alert"], "commod": ["commod"], "us": ["us", "price"],
}


def build():
    ds = datasets()
    ref = ds.get("price", {}).get("date")
    pages = {p: [k for k in keys if k in ds] for p, keys in PAGES.items()}
    return {"ref": ref, "datasets": ds, "pages": pages}


def write(out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=1))
