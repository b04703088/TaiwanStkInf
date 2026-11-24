# 潮汐盤中行情偵測（本機版）

在自己電腦上跑，用證交所 MIS 即時報價（上市＋上櫃），偵測：

| 類型 | 條件（預設，可在 config.json 改） |
|---|---|
| 急拉／急殺 | 5 分鐘內從低點漲（從高點跌）≥ 2.5% |
| 爆量 | 5 分鐘量 ≥ 平常同樣時間的 4 倍且 ≥ 300 張；或今日累積量剛超過近5日均量 1.5 倍 |
| 鎖漲停／漲停打開／再鎖回 | 附委買張數 |
| 跌停打開 | 附委賣價量 |
| 族群急拉／族群急殺 | 同一產業鏈族群 10 分鐘內 ≥ 3 檔急拉（急殺）；族群用潮汐的 AI 供應鏈族群＋產業價值鏈 |
| ETF溢價／ETF折價 | 盤中市價對預估淨值，新跨過 ±1%（只看近5日均成交值 ≥ 0.1 億的 ETF） |
| 自選股 | watchlist.txt 裡的股票不套成交值濾網，門檻打 6 折，標 ★ |

只掃近5日均成交值 ≥ 1 億的股票（約 500 檔），每輪約 15～50 秒（看 MIS 回應速度）。

程式剛開時已經鎖漲停、或 ETF 已經超過折溢價門檻的，不逐檔警示，只在畫面列一次摘要；之後新發生的才警示。

另外會產生 `logs\etf.html`：全部 ETF 的市價、預估淨值、折溢價，依 |折溢價| 排序，每 15 秒更新，可用近5日均成交值（不限／≥1億／≥5億／≥20億）篩選。ETF 跨過 ±1% 會警示（`etf_premium_pct` 可改）。

## 安裝（Windows，只要做一次）

1. 到 https://www.python.org/downloads/ 下載安裝 Python 3（安裝時勾 **Add python.exe to PATH**）。
2. 下載這個資料夾：https://github.com/b04703088/TaiwanStkInf/tree/main/local/intraday
   最簡單：GitHub 網頁按 Code → Download ZIP，解壓後把 `local/intraday` 資料夾放到桌面。
   不用 pip 安裝任何套件。

## 每天使用

- 雙擊 `start.bat`（或在資料夾裡開命令提示字元打 `python monitor.py`）。
  08:59 前開著會自動等開盤，13:35 自動結束。
- 用瀏覽器打開 `logs\alerts.html`，每 10 秒自動更新，最新警示在最上面。
- 每天的警示會存在 `logs\YYYYMMDD.csv`（可以拿來回測哪種警示後續有沒有賺）。
- 第一次開會產生 `config.json`（門檻）和 `watchlist.txt`（自選，一行一檔代號）。

## 手機推播（選用，Telegram）

1. Telegram 搜尋 **@BotFather** → 傳 `/newbot` → 照指示取名，會拿到一串 token。
2. 對你剛建的 bot 傳任一訊息，然後用瀏覽器開
   `https://api.telegram.org/bot<token>/getUpdates`，找 `"chat":{"id":` 後面的數字。
3. 把 token 和數字填進 `config.json` 的 `telegram_token`、`telegram_chat_id`，重開程式。
   哪些類型要推播在 `telegram_types` 設定；自選股的警示一律推播。

## 注意

- MIS 請求太頻繁會被暫時封鎖。程式預設每 2 秒一次；遇到失敗會自動等 1～5 分鐘再試。不要把 `request_gap_sec` 調太低。
- MIS 是快照（約 5 秒一次），不是逐筆，所以極短的瞬間拉抬可能看不到。
