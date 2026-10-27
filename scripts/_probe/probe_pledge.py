import re, sys, html
sys.path.insert(0, ".")
import etf_common as C
def show(t, s): print(f"===== {t}\n{s}\n", flush=True)
for kind in ("IRB130", "IRB190", "IRB200", "IRB140", "IRB180"):
    for mkt in ("sii", "otc"):
        url = f"https://siis.twse.com.tw/publish/{mkt}/115{kind}_09.HTM"
        try:
            t = C.http(url, raw=True, retries=2).decode("cp950", errors="replace")
            rows = re.findall(r"<TR>(.*?)</TR>", t, re.S | re.I)
            show(f"{url} len={len(t)} rows={len(rows)}", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", t[:1500])))
            for r in rows[:12]:
                print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", r))[:400])
        except Exception as e:
            show(url, e)
