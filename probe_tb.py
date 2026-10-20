import re, sys
import etf_common as C
import fetch_broker as F
def get(url, params):
    raw = C.http(url, params, raw=True, retries=2)
    return raw.decode("cp950", errors="replace")
cases = [("2474","2026-8-10","2026-10-6",32145),("3008","2025-12-19","2026-2-11",2670),("2474","2024-12-21","2025-2-20",31219),
         ("6239","2026-8-10","2026-9-30",10000),("2324","2026-5-13","2026-7-10",100000),("2371","2025-1-8","2025-3-5",75500)]
first_bid=None
for code,s,e,sh in cases:
    try:
        p = get(F.BASE, {"a":code,"e":s,"f":e})
    except Exception as ex:
        print(code, s, e, "ERR", ex); continue
    rows,_ = F.parse(p, s, code)
    print(f"== {code} {s}~{e} bought {sh} 張; rows={len(rows)}", flush=True)
    m = re.search(r"資料日期[^<]*", p); print("  ", m.group(0) if m else "")
    for r in rows[:8]:
        if r["side"]=="B": print("   B", r["rank"], r["bid"], r["broker"], r["buy"], r["sell"], r["net"], r["pct"])
    if first_bid is None and rows: first_bid=(code, rows[0]["bid"], s, e)
# zco0 detail
code,bid,s,e = first_bid
for url in ["https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco0/zco0.djhtm"]:
    try:
        p = get(url, {"A":code,"BHID":bid[:4],"b":bid,"C":"1","D":s,"E":e,"ver":"V3"})
        print("zco0 len", len(p)); print(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",p))[:3000])
    except Exception as ex: print("zco0 ERR", ex)
# show link format in zco page
p = get(F.BASE, {"a":"2474","e":"2026-8-10","f":"2026-10-6"})
print(re.findall(r'href="[^"]*zco0[^"]*"', p)[:3])
