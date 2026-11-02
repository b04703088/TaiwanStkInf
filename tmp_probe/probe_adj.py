import sys, csv, urllib.parse, urllib.request
sys.path.insert(0, ".")
from pathlib import Path
import fetch_futures as ff
out = Path("tmp_probe/out2"); out.mkdir(parents=True, exist_ok=True)
def raw(path, form):
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(ff.BASE + path, data=body, headers={"User-Agent": ff.UA})
    try:
        return urllib.request.urlopen(req, timeout=120).read().decode("cp950", "replace")
    except Exception as e:
        return f"ERR {e}"
D = "2026/10/30"
tries = [
 ("futDataDown", {"down_type": "1", "commodity_id": "all", "queryStartDate": D, "queryEndDate": D}),
 ("futDataDown", {"down_type": "1", "commodity_id": "STF", "queryStartDate": D, "queryEndDate": D}),
 ("futDataDown", {"down_type": "1", "commodity_id": "STO", "commodity_id2": "", "queryStartDate": D, "queryEndDate": D}),
 ("futDataDown", {"down_type": "1", "commodity_id": "CDF", "queryStartDate": D, "queryEndDate": D}),
 ("futDataDown", {"down_type": "1", "commodity_id": "STF", "commodity_id2": "CDF", "queryStartDate": D, "queryEndDate": D}),
]
for i, (p, f) in enumerate(tries):
    t = raw(p, f)
    (out / f"try{i}.csv").write_text(t, encoding="utf-8")
    lines = t.splitlines()
    print(i, f, len(lines), lines[:3], flush=True)
for url, fn in [("https://www.taifex.com.tw/cht/2/stockLists", "x"), ]:
    pass
