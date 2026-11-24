import urllib.request, http.cookiejar, time
jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36","Accept":"application/json, text/plain, */*","Referer":"https://mis.twse.com.tw/stock/index.jsp"}
for u in ["https://mis.twse.com.tw/stock/index.jsp","https://mis.twse.com.tw/stock/index","https://mis.twse.com.tw/stock/fibest.jsp?lang=zh_tw",
          "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw&json=1&delay=0",
          "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|otc_6488.tw&json=1&delay=0&_=%d"%(time.time()*1000),
          "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw%7Cotc_6488.tw&json=1&delay=0",
          "https://mis.twse.com.tw/stock/data/all_etf.txt"]:
    try:
        r=op.open(urllib.request.Request(u,headers=H),timeout=15); b=r.read()
        print("OK",r.status,u,r.geturl(),b[:400])
    except Exception as e:
        print("ERR",u,e, getattr(e,'url',''))
    print([c.name for c in jar])
