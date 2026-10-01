import pathlib, urllib.request
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
B = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm"
for name, q in [("9801_B", "a=9800&b=9801&c=B&e=2026-9-30&f=2026-9-30"),
                ("9801_E", "a=9800&b=9801&c=E&e=2026-9-30&f=2026-9-30"),
                ("9A9g_B", "a=9A00&b=0039004100390067&c=B&e=2026-9-30&f=2026-9-30"),
                ("8450_B", "a=8450&b=8450&c=B&e=2026-9-30&f=2026-9-30"),
                ("9801_B_5d", "a=9800&b=9801&c=B&e=2026-9-24&f=2026-9-30"),
                ("9801_B_today", "a=9800&b=9801&c=B&e=2026-10-1&f=2026-10-1")]:
    try:
        (OUT / f"zgb_{name}.html").write_bytes(urllib.request.urlopen(urllib.request.Request(f"{B}?{q}", headers={"User-Agent": UA}), timeout=30).read())
    except Exception as e:
        (OUT / f"zgb_{name}.err").write_text(str(e))
