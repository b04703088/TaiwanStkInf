import json, re, sys
sys.path.insert(0, ".")
import etf_common as C
def show(t, s): print(f"===== {t}\n{s}\n", flush=True)
B = "https://mopsov.twse.com.tw/mops/web/"
for pg in ("STAMAK03_q1", "STAMAK03_q2", "STAMAK03_1"):
    try:
        t = C.http(B + pg, as_json=False)
        i = t.find("<form")
        show(pg, re.sub(r"\s+", " ", t[i:i+6000]))
        for m in re.finditer(r"ajax_[A-Za-z0-9_]+", t): print("ajax", m.group(0))
        for m in re.finditer(r"function (\w+)\(", t): print("fn", m.group(1))
    except Exception as e:
        show(pg, e)
# guesses
for pg, form in [
    ("ajax_STAMAK03_q1", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "10", "day": "20"}),
    ("ajax_STAMAK03_q1", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "10"}),
    ("ajax_STAMAK03_1", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "co_id": "2002", "year": "115", "month": "09"}),
]:
    try:
        t = C.http(B + pg, form=form, as_json=False)
        show(f"{pg} {form}", re.sub(r"\s+", " ", re.sub(r"<(script|style).*?</\1>", "", t, flags=re.S))[:5000])
    except Exception as e:
        show(pg, e)
for api in ("STAMAK03_q1", "STAMAK03_1", "stamak03_q1"):
    try:
        r = C.http("https://mops.twse.com.tw/mops/api/" + api, body={"marketKind": "sii", "year": "115", "month": "10", "day": "20", "companyId": "2002"}, headers={"Referer": "https://mops.twse.com.tw/mops/"})
        show("api " + api, json.dumps(r, ensure_ascii=False)[:3000])
    except Exception as e:
        show("api " + api, e)
