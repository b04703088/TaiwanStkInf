"""產生 GitHub Pages 網站：site/ 的頁面 + data/ 最近 N 個交易日轉成 JSON。

輸出 _site/：
  index.html, ranking.html ...        從 site/ 複製
  data/days.json                     可用日期（由舊到新）
  data/daily/YYYY-MM-DD.json         當日全市場 {date, columns, rows}
  data/etf/latest.json               各 ETF 最新持股與前一份的差異（見 scripts/etf_site.py）
  data/etf/aum.json                  全體 ETF 規模排行（fetch_etf_aum.py 的最新一天）
  data/etf/tip.json                  臺灣指數公司定期審核行事曆（見 fetch_tip_schedule.py）
  data/etf/active.json               主動式 ETF 每次持股變化（台股，含扣除申贖的增減）
  data/calendar.json                 指數調整行事曆：審核日、預估審核、ETF 換股期間（見 scripts/calendar_site.py）
  data/health.json                   資料健檢結果（見 scripts/health.py）
  data/broker/days.json, <日期>.json  券商分點前 15 大（見 scripts/broker_site.py）
  data/broker/watch.json             重點分點（config/broker_watch.csv）近 60 個交易日
  data/broker/local.json             地方分點（排除外資、凱基-台北、總公司）買賣超金額排行，近 1／5／10／20 日
  data/analyst/analyst.json          FactSet 共識與外資報告（見 scripts/analyst_site.py）
  data/alert/alert.json              處置股、注意股（見 scripts/alert_site.py）
  data/treasury.json                 庫藏股買回計畫與進度（見 scripts/treasury_site.py）
  data/insider/insider.json          內部人事前申報、每月持股異動與設質解質（見 scripts/insider_site.py）
  data/mops/mops.json                重大訊息、股東會／法說會行事曆（見 scripts/mops_site.py）
  data/fin/index.json, s/<代號>.json  財報：月營收與季報（見 scripts/fin_site.py）
  data/margin/market.json, stocks.json, s/<代號>.json  融資融券、估計維持率（見 scripts/margin_site.py）
  data/kline/index.json, s/<代號>.json  K 線：2022 年起每日價量＋還原因子事件（見 scripts/kline_site.py）
  data/chips/chips.json, s/<代號>.json 三大法人、借券賣出、當沖、集保大戶（見 scripts/chips_site.py）
  data/futures.json                  期貨選擇權籌碼：法人未平倉、P/C ratio、大額交易人（見 scripts/futures_site.py）
  data/digest/index.json, <日期>.md  盤後摘要：數字摘要與每晚判讀（見 scripts/digest_site.py）
  data/newhigh.json                  創新高：近 60 日創 52 週／2022 年以來新高的個股與族群（見 scripts/newhigh_site.py）
  data/limitup.json                  漲停：近 20 日每天收漲停、觸及漲停的個股，連板與隔日表現（見 scripts/limitup_site.py）
  data/screen/screen.json, div.json   選股：技術面、營收財報、籌碼條件；除權息與填息（見 scripts/screen_site.py）
  data/stock/s/<代號>.json           個股綜合查詢：各頁資料裡跟這檔有關的動作（見 scripts/stock_site.py，要最後跑）
  每頁標題旁標示建置時間（＝網站上次更新時間，台北時間），見 stamp_built()

用法：python scripts/build_site.py [--days 120] [--out _site]
"""
import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
NUM_FIELDS = ("open", "high", "low", "close", "change", "volume", "value", "transactions")
SNAPSHOT_FIELDS = ("code", "name", "market", "open", "high", "low", "close", "change", "volume", "value")


def _num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_rows(path):
    """讀一天的 CSV；沒有收盤價（當日無成交）的列略過。"""
    rows = []
    with open(path, newline="", encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            row = {"date": r["date"], "market": r["market"],
                   "code": r["code"].strip(), "name": r["name"].strip()}
            for k in NUM_FIELDS:
                row[k] = _num(r.get(k))
            if row["close"] is not None:
                rows.append(row)
    return rows


sys.path.insert(0, str(ROOT / "scripts"))
import etf_site  # noqa: E402
import health  # noqa: E402
import broker_site  # noqa: E402
import cb_site  # noqa: E402
import industry_site  # noqa: E402
import flow_site  # noqa: E402
import rebalance_site  # noqa: E402
import calendar_site  # noqa: E402
import analyst_site  # noqa: E402
import alert_site  # noqa: E402
import treasury_site  # noqa: E402
import insider_site  # noqa: E402
import mops_site  # noqa: E402
import fin_site  # noqa: E402
import margin_site  # noqa: E402
import kline_site  # noqa: E402
import screen_site  # noqa: E402
import chips_site  # noqa: E402
import futures_site  # noqa: E402
import stock_site  # noqa: E402
import digest_site  # noqa: E402
import newhigh_site  # noqa: E402
import limitup_site  # noqa: E402

TPE = timezone(timedelta(hours=8))
BRAND_SUB = '<span class="brand-sub">籌碼觀測站</span>'


def stamp_built(out: Path, now: datetime) -> int:
    """在每頁「籌碼觀測站」下面加一行上次更新時間，回傳改了幾頁。"""
    t = now.astimezone(TPE)
    # 絕對定位掛在「籌碼觀測站」正下方，不佔寬度（導覽列在 1280px 已經很擠）
    tag = (f'<span class="brand-sub" style="position:relative">籌碼觀測站<span class="built-at"'
           f' title="網站上次更新 {t:%Y-%m-%d %H:%M}（台北）"'
           f' style="position:absolute;left:0;top:100%;font-size:11px;line-height:1.4;white-space:nowrap">'
           f'更新 {t.month}/{t.day} {t:%H:%M}</span></span>')
    n = 0
    for f in out.glob("*.html"):
        s = f.read_text(encoding="utf-8")
        if BRAND_SUB in s:
            f.write_text(s.replace(BRAND_SUB, tag, 1), encoding="utf-8")
            n += 1
    return n


def build(out: Path, days: int) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    (out / ".nojekyll").touch()

    files = sorted((ROOT / "data").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)[-days:]  # 只取年份資料夾（排除 data/etf）
    daily = out / "data" / "daily"
    daily.mkdir(parents=True)
    dates = []
    for f in files:
        rows = read_rows(f)
        if not rows:
            continue
        d = rows[0]["date"]
        payload = {"date": d, "columns": list(SNAPSHOT_FIELDS),
                   "rows": [[r[k] for k in SNAPSHOT_FIELDS] for r in rows]}
        (daily / f"{d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        dates.append(d)
    (out / "data" / "days.json").write_text(json.dumps(dates), encoding="utf-8")
    if (ROOT / "data" / "etf" / "etf_list.csv").exists():
        etf_site.write_latest(ROOT / "data", out / "data" / "etf" / "latest.json")
    etf_site.write_aum(ROOT / "data", out / "data" / "etf" / "aum.json")
    etf_site.write_tip(ROOT / "data", ROOT, out / "data" / "etf" / "tip.json")
    etf_site.write_active(ROOT / "data", out / "data" / "etf" / "active.json")
    broker_site.write_site(ROOT / "data", out, days=20)
    broker_site.write_watch(ROOT / "data", ROOT, out, days=60)
    broker_site.write_local(ROOT / "data", out, days=20)
    cb_site.write_cb(ROOT / "data", out / "data" / "cb" / "cb.json")
    industry_site.write_industry(ROOT / "data", out / "data" / "industry" / "industry.json")
    flow_site.write_flow(ROOT / "data", out / "data" / "flow.json")
    rebalance_site.write_rebalance(ROOT, out / "data" / "etf" / "rebalance.json")
    calendar_site.write_calendar(ROOT / "data", ROOT, out / "data" / "calendar.json")
    analyst_site.write_analyst(ROOT / "data", out / "data" / "analyst" / "analyst.json")
    alert_site.write_alert(ROOT / "data", out / "data" / "alert" / "alert.json")
    treasury_site.write_treasury(ROOT / "data", out / "data" / "treasury.json")
    insider_site.write_insider(ROOT / "data", out / "data" / "insider" / "insider.json")
    mops_site.write_mops(ROOT / "data", out / "data" / "mops" / "mops.json")
    fin_site.write_fin(ROOT / "data", out / "data" / "fin")
    margin_site.write_margin(ROOT / "data", out / "data" / "margin")
    prices = kline_site.load_prices(ROOT / "data")
    kline_site.write_kline(ROOT / "data", out / "data" / "kline", prices)
    futures_site.write_futures(ROOT / "data", out / "data" / "futures.json")
    digest_site.write_digest(ROOT / "data", out / "data" / "digest")
    newhigh_site.write_newhigh(ROOT / "data", out / "data" / "newhigh.json", prices=prices)
    limitup_site.write_limitup(ROOT / "data", out / "data" / "limitup.json")
    chips = chips_site.write_chips(ROOT / "data", out / "data" / "chips")
    screen_site.write_screen(ROOT / "data", out / "data" / "screen", today=datetime.now(TPE).date(), prices=prices,
                             extra={"chips": chips} if chips else None)
    stock_site.write_stock(out, datetime.now(TPE).date())  # 讀上面各頁剛寫好的 JSON，要放最後
    for page in cb_site.SUBPAGES:  # CB詢圈子頁共用同一個 HTML，由檔名決定顯示哪一頁
        shutil.copy(out / "cb.html", out / page)
    stamp_built(out, datetime.now(timezone.utc))
    (out / "data" / "health.json").write_text(
        json.dumps(health.check(ROOT / "data"), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return dates


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="保留最近幾個交易日（預設 120）")
    ap.add_argument("--out", default="_site")
    a = ap.parse_args()
    ds = build(ROOT / a.out, a.days)
    print(f"built {len(ds)} days: {ds[0] if ds else '-'} ~ {ds[-1] if ds else '-'}")
