"""產生 GitHub Pages 網站：site/ 的頁面 + data/ 最近 N 個交易日轉成 JSON。

輸出 _site/：
  index.html, ranking.html ...        從 site/ 複製
  data/days.json                     可用日期（由舊到新）
  data/daily/YYYY-MM-DD.json         當日全市場 {date, columns, rows}
  data/etf/latest.json               各 ETF 最新持股與前一份的差異（見 scripts/etf_site.py）
  data/etf/aum.json                  全體 ETF 規模排行（fetch_etf_aum.py 的最新一天）
  data/etf/tip.json                  臺灣指數公司定期審核行事曆（見 fetch_tip_schedule.py）
  data/etf/active.json               主動式 ETF 每次持股變化（台股，含扣除申贖的增減）
  data/health.json                   資料健檢結果（見 scripts/health.py）
  data/broker/days.json, <日期>.json  券商分點前 15 大（見 scripts/broker_site.py）
  data/broker/watch.json             重點分點（config/broker_watch.csv）近 60 個交易日

用法：python scripts/build_site.py [--days 120] [--out _site]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from upload_firestore import SNAPSHOT_FIELDS, read_rows  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import etf_site  # noqa: E402
import health  # noqa: E402
import broker_site  # noqa: E402
import cb_site  # noqa: E402
import industry_site  # noqa: E402


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
    cb_site.write_cb(ROOT / "data", out / "data" / "cb" / "cb.json")
    industry_site.write_industry(ROOT / "data", out / "data" / "industry" / "industry.json")
    for page in cb_site.SUBPAGES:  # CB詢圈子頁共用同一個 HTML，由檔名決定顯示哪一頁
        shutil.copy(out / "cb.html", out / page)
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
