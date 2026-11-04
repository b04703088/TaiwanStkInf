"""全站共用的成交值濾網資料 data/liq.json（site/nav.js 的 TideLiq 讀它）。

  {"date": 最新交易日, "n": 天數, "v": {代號: 近 n 個交易日平均成交金額（億）}}
沒成交的天以 0 計；一天都沒成交的代號不列（濾網會把它當成 0）。
2026-11-04 Leo：所有拿全市場或超過 200 檔個股來排名的表都要有這個濾網。
"""
import csv
import json
from pathlib import Path

N = 5


def build(price_files, n=N):
    files = [Path(f) for f in price_files][-n:]
    tot, days, last = {}, 0, None
    for f in files:
        with f.open(encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
        if not rows:
            continue
        days += 1
        last = rows[0]["date"]
        for r in rows:
            try:
                v = float(r.get("value") or 0)
            except ValueError:
                continue
            if v > 0:
                tot[r["code"]] = tot.get(r["code"], 0.0) + v
    return {"date": last, "n": days, "v": {c: round(v / days / 1e8, 3) for c, v in sorted(tot.items())} if days else {}}


def write(price_files, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(price_files), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
