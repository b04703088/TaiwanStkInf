import sys, pathlib, json, re, traceback, uuid
from datetime import date, timedelta
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root))
import etf_common as C, etf_adapters as A
OUT = root / "probe" / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
log = []
DATES = [date(2026, 6, 12), date(2025, 12, 12), date(2024, 12, 13)]
real_recent = C.recent_days
def run(issuer, code, fn):
    for d in DATES:
        try:
            got = fn(d)
            log.append(f"{issuer:9} {code:7} ask {d} -> {got}")
        except Exception as e:
            log.append(f"{issuer:9} {code:7} ask {d} -> ERR {str(e)[:160]}")
def via_recent(adapter, code):
    def fn(d):
        C.recent_days = lambda n, start=None: [d - timedelta(days=k) for k in range(n) if (d - timedelta(days=k)).weekday() < 5]
        try:
            dd, rows, _ = A.ADAPTERS[adapter](code) if hasattr(A, "ADAPTERS") else getattr(A, adapter)(code)
        finally:
            C.recent_days = real_recent
        return (dd, len(rows))
    return fn
for issuer, code in [("fuhhwa", "00929"), ("ctbc", "00934"), ("nomura", "00935"), ("uob", "00918"), ("allianz", "00984A")]:
    run(issuer, code, via_recent(issuer, code))
# 國泰
def cathay(d):
    fc = A._cathay_fund("00878")
    rows = A.cathay_holdings(fc, d.isoformat())
    return len(rows) if rows is not None else None
run("cathay", "00878", cathay)
# 統一 specificDate
def president(d):
    A.president("00939")  # 先建 map
    fc = A._ez_map.get("00939")
    out = []
    for spec in (True, False):
        r = C.http(A.EZ + "GetPCF", body={"fundCode": fc, "date": f"{d.year-1911}/{d.month:02d}/{d.day:02d}", "specificDate": spec},
                   headers={"Referer": A.EZ + "PCF", "X-Requested-With": "XMLHttpRequest"})
        pcf = C.find_key(r, "pcf"); pcf = pcf[0] if isinstance(pcf, list) and pcf else pcf
        out.append((spec, (pcf or {}).get("TranDate")))
    return out
run("president", "00939", president)
# 元大：試不同日期參數
def yuanta(d):
    res = []
    for k in ("date", "Date", "searchDate", "SearchDate", "trandate", "pcfDate"):
        p = {"APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS", "PageName": "/product/detail/0056/ratio", "DeviceId": str(uuid.uuid4()),
             "FuncId": "PCF/Daily", "AppName": "ETF", "Device": "3", "Platform": "ETF", "ticker": "0056", k: d.strftime("%Y/%m/%d")}
        r = C.http(A.YUANTA_BRIDGE, p, headers={"Referer": "https://www.yuantaetfs.com/product/detail/0056/ratio"})
        if isinstance(r, dict) and "Data" in r and "PCF" not in r: r = r["Data"]
        res.append((k, ((r or {}).get("PCF") or {}).get("trandate")))
    return res
run("yuanta", "0056", yuanta)
# 群益
def capital(d):
    A.capital("00919"); fid = A._capital_map.get("00919")
    res = []
    for k in ("date", "searchDate", "qDate", "Date", "pcfDate"):
        r = (C.http(A.CAPITAL + "buyback", body={"fundId": fid, k: d.strftime("%Y/%m/%d")}) or {}).get("data") or {}
        res.append((k, (r.get("pcf") or {}).get("date2"), len(r.get("stocks") or [])))
    return res
run("capital", "00919", capital)
# 富邦
def fubon(d):
    res = []
    for k in ("date", "sDate", "qDate", "dt"):
        page = C.http(A.FUBON_ASSETS, {"stkId": "006208", "lan": "TW", k: d.strftime("%Y/%m/%d")}, as_json=False)
        m = re.search(r"資料日期：\s*(\d{4}/\d{1,2}/\d{1,2})", page)
        res.append((k, m.group(1) if m else None))
    page = C.http(A.FUBON_ASSETS, {"stkId": "006208", "lan": "TW"}, as_json=False)
    (OUT / "fubon.html").write_text(page, encoding="utf-8")
    return res
run("fubon", "006208", fubon)
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
