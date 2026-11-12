import re, requests, json
H={"User-Agent":"Mozilla/5.0"}
urls=[
 "https://www.tpex.org.tw/data/menu/zh-tw/menu.json",
 "https://wwwov.tpex.org.tw/web/stock/most_active/active_BROKER_vol/rt_brk.php?l=zh-tw",
 "https://info.tpex.org.tw/IIH/zh/ranking1.html",
 "https://mis.tpex.org.tw/ib140srt2.aspx",
 "https://mis.tpex.org.tw/",
 "https://www.tpex.org.tw/web/service/info_service/real_time_info.php?l=zh-tw",
]
for u in urls:
    print("=====",u,flush=True)
    try:
        r=requests.get(u,headers=H,timeout=30)
        t=r.content.decode(r.apparent_encoding or "utf-8","replace")
        print(r.status_code,len(t))
        if "menu.json" in u:
            for m in re.findall(r'"([^"]*?(?:盤中|即時|買超|法人|券商|分點)[^"]*?)"',t): print("  M",m)
            for m in re.findall(r'"(/[^"]*?(?:most_active|active|rt_|intraday|realtime)[^"]*?)"',t): print("  U",m)
            continue
        for m in set(re.findall(r'''(?:src|href|url|action)\s*[:=]\s*["']([^"']+)["']''',t)): print("  L",m)
        for m in set(re.findall(r'''["']([^"'\s]*(?:\.php|\.json|\.aspx|/api/|bulletin/)[^"'\s]*)["']''',t)): print("  E",m)
        print(re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',t))[:3000])
    except Exception as e: print("ERR",e)
