import pathlib, re, urllib.request, urllib.parse
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
for p in OUT.iterdir(): p.unlink()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
get = lambda url: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90).read()
s = get("https://www.sfb.gov.tw/ch/home.jsp?id=1016&parentpath=0,6,52").decode("utf-8", "ignore")
for u in re.findall(r'href="(https://www\.fsc\.gov\.tw/userfiles/file/[^"]*%E7%94%B3%E5%A0%B1%E6%A1%88%E4%BB%B6%E5%BD%99%E7%B8%BD%E8%A1%A8\.(?:xlsx|ods))"', s):
    n = urllib.parse.unquote(u.split("/")[-1])
    if n.startswith("115"):
        (OUT / ("sfb115." + n.rsplit(".", 1)[1])).write_bytes(get(u))
