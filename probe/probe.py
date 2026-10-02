import pathlib, re, urllib.request
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
log = []
for name, u in [("isin_e2.html", "https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2"),
                ("isin_e4.html", "https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4"),
                ("twse_en_list.html", "https://www.twse.com.tw/rwd/en/company/list?response=html"),
                ("mops_en.html", "https://mopsov.twse.com.tw/mops/web/ajax_t05st03?encodeURIComponent=1&step=1&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&co_id=1101")]:
    try:
        b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read()
        (OUT / name).write_bytes(b); log.append(f"{u} -> {len(b)}")
    except Exception as e:
        log.append(f"{u} -> ERR {e}")
(OUT / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
