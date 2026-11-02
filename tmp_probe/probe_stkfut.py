import sys, time, urllib.request
sys.path.insert(0, ".")
from datetime import date
from pathlib import Path
import fetch_futures as ff
out = Path("tmp_probe/out"); out.mkdir(parents=True, exist_ok=True)
rows = ff._get("largeTraderFutDown", {}, date(2026, 9, 1), date(2026, 11, 2))
print("large rows", len(rows), flush=True)
import csv
with open(out / "large_all.csv", "w", newline="", encoding="utf-8") as fp:
    w = csv.writer(fp); w.writerows(r for r in rows if r[1] not in ("TX", "MTX", "TE", "TF"))
prods = sorted({(r[1], r[2]) for r in rows})
print(prods[:40], len(prods), flush=True)
for url, fn in [("https://www.taifex.com.tw/cht/2/stockLists", "stocklists.html")]:
    req = urllib.request.Request(url, headers={"User-Agent": ff.UA})
    try:
        b = urllib.request.urlopen(req, timeout=60).read()
        (out / fn).write_bytes(b); print(fn, len(b), flush=True)
    except Exception as e:
        print("ERR", url, e, flush=True)
