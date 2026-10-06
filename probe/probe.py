import sys, pathlib, json, re, uuid, html
from datetime import date
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root))
import etf_common as C, etf_adapters as A
OUT = root / "probe" / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
log = []
d = date(2026, 6, 12)
def yt(extra, func="PCF/Daily"):
    p = {"APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS", "PageName": "/product/detail/0056/ratio", "DeviceId": str(uuid.uuid4()),
         "FuncId": func, "AppName": "ETF", "Device": "3", "Platform": "ETF", "ticker": "0056", **extra}
    try:
        r = C.http(A.YUANTA_BRIDGE, p, headers={"Referer": "https://www.yuantaetfs.com/product/detail/0056/ratio"})
    except Exception as e:
        return f"ERR {e}"[:150]
    if isinstance(r, dict) and "Data" in r and "PCF" not in r: r = r["Data"]
    if isinstance(r, dict):
        return (((r.get("PCF") or {}).get("trandate")), len(((r.get("FundWeights") or {}).get("StockWeights")) or []), str(r)[:150] if not r.get("PCF") else "")
    return str(r)[:150]
for k in ("date", "Date", "pcfdate", "PCFDate", "SDate", "tradeDate", "day"):
    for f in ("20260612", "2026-06-12", "2026/06/12", "115/06/12"):
        log.append(f"yuanta {k}={f}: {yt({k: f})}")
for fn in ("PCF/History", "PCF/Daily/History", "PCF/HistoryDaily", "PCF/ByDate"):
    log.append(f"yuanta func {fn}: {yt({'date': '20260612'}, fn)}")
# 元大官網頁面：找 API 名稱
try:
    page = C.http("https://www.yuantaetfs.com/product/detail/0056/ratio", as_json=False)
    funcs = sorted(set(re.findall(r'"(PCF/[A-Za-z/]+)"', page)) | set(re.findall(r"FuncId[\"']?\s*[:=]\s*[\"']([^\"']+)", page)))
    log.append("yuanta page funcs: " + ", ".join(funcs)[:500])
    (OUT / "yuanta_ratio.html").write_text(page[:400000], encoding="utf-8")
except Exception as e:
    log.append(f"yuanta page ERR {e}")
# 第一金
try:
    fid = A.SOURCE_IDS.get("00728") or "D90"
    for ds in ("2026/06/12", "20260612", "2026-06-12"):
        r = C.http(A.FSITC + "WebAPI.aspx/Get_hd", body={"pStrFundID": fid, "pStrDate": ds})
        st = C.find_key(r, "d"); st = json.loads(st) if isinstance(st, str) else st
        log.append(f"firstsec {ds}: {str(st)[:200]}")
except Exception as e:
    log.append(f"firstsec ERR {e}")
# 富蘭克林
try:
    lst = C.http(A.FTFT + "etf")
    fid = next(str(x.get("FundID")) for x in lst if str(x.get("StockCode")).strip() == "00965" or True)
    for ds in ("2026-06-12", "2026/06/12"):
        r = C.http(A.FTFT + f"etf/shares/{fid}", {"date": ds})
        log.append(f"franklin {fid} {ds}: {r.get('AssetDate') if isinstance(r, dict) else str(r)[:100]}")
except Exception as e:
    log.append(f"franklin ERR {e}")
# 凱基：Detail 頁找日期參數
try:
    A.kgi("00915", "凱基優選高股息30")
    fid = A._match_name(A._kgi_map, "凱基優選高股息30", "00915")
    for k in ("date", "sDate", "qDate", "searchDate"):
        page = html.unescape(C.http(A.KGI + "Detail", {"fundID": fid, k: "2026/06/12"}, as_json=False))
        m = re.search(r"持股比重\s*(?:</div>\s*<p[^>]*>)?\s*[（(]\s*(\d{4}/\d{1,2}/\d{1,2})", page)
        log.append(f"kgi {k}: {m.group(1) if m else None}")
    (OUT / "kgi_detail.html").write_text(page, encoding="utf-8")
except Exception as e:
    log.append(f"kgi ERR {e}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
