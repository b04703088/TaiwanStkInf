"""產生 GitHub Pages 網站：site/ 的頁面 + data/ 最近 N 個交易日轉成 JSON。

輸出 _site/：
  index.html, ranking.html ...        從 site/ 複製
  data/days.json                     可用日期（由舊到新）
  data/daily/YYYY-MM-DD.json         當日全市場 {date, columns, rows}

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


def build(out: Path, days: int) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    (out / ".nojekyll").touch()

    files = sorted((ROOT / "data").glob("*/*.csv"), key=lambda p: p.name)[-days:]
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
    return dates


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="保留最近幾個交易日（預設 120）")
    ap.add_argument("--out", default="_site")
    a = ap.parse_args()
    ds = build(ROOT / a.out, a.days)
    print(f"built {len(ds)} days: {ds[0] if ds else '-'} ~ {ds[-1] if ds else '-'}")
