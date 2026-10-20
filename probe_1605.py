import re
import etf_common as C
import fetch_broker as FB
def get(url, params):
    return C.http(url, params, raw=True, retries=2).decode("cp950", errors="replace")
for s, e, sh in [("2020-8-5","2020-10-4",60000),("2020-4-13","2020-6-12",40000),("2016-7-30","2016-9-28",120000),("2014-3-6","2014-5-5",30000)]:
    try:
        p = get(FB.BASE, {"a":"1605","e":s,"f":e})
    except Exception as ex:
        print(s, "ERR", ex); continue
    rows, _ = FB.parse(p, s, "1605")
    print(f"== 1605 {s}~{e} bought {sh}; rows={len(rows)}", flush=True)
    for r in rows[:6]:
        if r["side"]=="B": print("  ", r["bid"], r["broker"], r["buy"], r["sell"], r["net"])
    links = re.findall(r'zco0\.djhtm\?a=1605&b=([0-9A-Za-z]+)&BHID=([0-9A-Za-z]+)', p)
    print("  links", links[:4])
    if rows and links:
        b, bh = links[0]
        d = get("https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco0/zco0.djhtm", {"A":"1605","BHID":bh,"b":b,"C":"1","D":s,"E":e,"ver":"V3"})
        t = re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",d))
        i = t.find("買賣超(張)"); print("  daily:", t[i:i+600])
