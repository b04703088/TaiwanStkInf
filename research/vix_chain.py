"""暫時：抓 TXO 月選日資料（一般盤、前三個月份），存成精簡 csv.gz 供推算歷史 VIX。"""
import urllib.request, urllib.parse, gzip, csv, sys, time, calendar
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def num(x):
    try: return float(x)
    except: return None
y0, y1 = int(sys.argv[1]), int(sys.argv[2])
out = gzip.open(sys.argv[3], "wt", newline=""); w = csv.writer(out)
w.writerow(["date", "exp", "strike", "cp", "bid", "ask", "settle", "close"])
for y in range(y0, y1 + 1):
    for m in range(1, 13):
        if (y, m) > (2026, 11): break
        last = calendar.monthrange(y, m)[1]
        d = {"down_type": "1", "commodity_id": "TXO", "commodity_id2": "", "queryStartDate": f"{y}/{m:02d}/01", "queryEndDate": f"{y}/{m:02d}/{last}"}
        for k in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request("https://www.taifex.com.tw/cht/3/optDataDown", headers=UA, data=urllib.parse.urlencode(d).encode()), timeout=180) as r:
                    t = r.read().decode("big5", "replace"); break
            except Exception as e:
                print("retry", y, m, e); time.sleep(10); t = ""
        rows = {}
        for p in csv.reader(t.splitlines()[1:]):
            if len(p) < 18 or p[1] != "TXO" or p[17] != "一般": continue
            exp = p[2].strip()
            if not (len(exp) == 6 and exp.isdigit()): continue
            rows.setdefault(p[0], []).append((exp, p[3], "C" if p[4] == "買權" else "P", num(p[12]), num(p[13]), num(p[10]), num(p[8])))
        n = 0
        for dt, rs in sorted(rows.items()):
            keep = sorted({r[0] for r in rs})[:3]
            for r in rs:
                if r[0] in keep:
                    w.writerow([dt.replace("/", "-"), *r]); n += 1
        print(y, m, len(rows), "days", n, "rows", flush=True)
        time.sleep(2)
out.close()
