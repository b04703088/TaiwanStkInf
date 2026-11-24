import urllib.request, json, re, sys
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u, n=900):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            b = r.read()
        print("==", u, r.status, len(b)); t = b.decode("utf-8", "replace"); print(t[:n]); return t
    except Exception as e:
        print("==", u, "ERR", repr(e)); return ""
get("https://www.twse.com.tw/rwd/zh/indicesReport/MI_5MINS_HIST?date=20261101&response=json")
get("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20261120&selectType=ALL&response=json", 1500)
get("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20160108&selectType=ALL&response=json", 800)
get("https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=20261120&response=json", 1500)
get("https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&date=2026/11/20&response=json", 1500)
get("https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date=2026/11/01&response=json", 1500)
get("https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?type=Monthly&date=2026/11/01&response=json", 1500)
m = get("https://www.tpex.org.tw/www/zh-tw/menu.json", 0)
for x in sorted(set(re.findall(r'"(/www/zh-tw/[^"]*(?:ind|inx|Ind|insti)[^"]*)"', m)))[:80]: print("menu", x)
for x in sorted(set(re.findall(r'[^"]{0,40}指數[^"]{0,40}', m)))[:60]: print("menuz", x)
get("https://www.taifex.com.tw/cht/7/vixMinNew", 3000)
get("https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/20261120new.txt", 600)
get("https://www.taifex.com.tw/cht/7/vixDaily", 1500)
