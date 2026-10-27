import json, re, sys
sys.path.insert(0, ".")
import etf_common as C

def show(t, s): print(f"===== {t}\n{s}\n", flush=True)

for name, url in [("twse", "https://openapi.twse.com.tw/v1/swagger.json"),
                  ("tpex", "https://www.tpex.org.tw/openapi/swagger.json")]:
    try:
        d = C.http(url)
        for p, v in d.get("paths", {}).items():
            for m, op in v.items():
                s = op.get("summary", "") + op.get("description", "")
                if re.search("質|內部人|董監|董事|持股", s):
                    show(f"{name} {p}", s[:200])
    except Exception as e:
        show(name, e)

for code in ("2330", "1108", "2002"):
    try:
        r = C.http("https://mops.twse.com.tw/mops/api/query6_1", body={"companyId": code, "dataType": "2", "year": "115", "month": "09", "subsidiaryCompanyId": ""}, headers={"Referer": "https://mops.twse.com.tw/mops/"})
        res = r.get("result") or {}
        show(f"query6_1 {code} titles", json.dumps(res.get("titles"), ensure_ascii=False)[:3000])
        for row in (res.get("data") or [])[:6]:
            show("row", json.dumps(row, ensure_ascii=False))
    except Exception as e:
        show(f"query6_1 {code}", e)

# new MOPS bundles
try:
    page = C.http("https://mops.twse.com.tw/mops/", as_json=False)
    show("mops index", page[:1500])
    for js in set(re.findall(r'(?:src|href)="([^"]+\.js)"', page)):
        u = js if js.startswith("http") else "https://mops.twse.com.tw" + (js if js.startswith("/") else "/mops/" + js)
        t = C.http(u, as_json=False)
        show(f"js {u}", len(t))
        for m in re.finditer("設質|質權|解質", t):
            show("ctx", t[max(0, m.start()-300):m.end()+300])
        for m in set(re.findall(r'"(query6_\w+|t\d+s[bc]\d+\w*)"', t)):
            print("api", m)
        # chunk files
        for ch in set(re.findall(r'"(assets/[^"]+\.js)"', t))[:0]:
            pass
except Exception as e:
    show("mops new", e)

for path in ("https://mopsov.twse.com.tw/mops/web/index", "https://mopsov.twse.com.tw/mops/web/t56sb21_q1"):
    try:
        t = C.http(path, as_json=False)
        show(path, len(t))
        for m in re.finditer("設質|質權|解質", t):
            show("ctx", t[max(0, m.start()-300):m.end()+200])
    except Exception as e:
        show(path, e)
