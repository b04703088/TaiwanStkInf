# TaiwanStkInf

每日自動抓取台股收盤行情（上市 TWSE + 上櫃 TPEx）。

- `fetch_daily.py`：抓取腳本，只用 Python 標準函式庫
- `.github/workflows/daily.yml`：週一至週五台北時間 15:30 自動執行，結果 commit 到 `data/`
- 已抓過的日期、週末、已確認的非交易日（記在 `data/no_trading_days.txt`）會直接跳過不連線；`--force` 可強制重抓
- 輸出：`data/<YYYY>/<YYYYMMDD>.csv`，欄位 `date, market, code, name, open, high, low, close, change, volume, value, transactions`

## ETF 每日持股明細

`fetch_etf.py` 每天抓各投信公告的 ETF 持股（成分股、總股數、權重），workflow `.github/workflows/etf.yml` 自動執行並 commit。

- 輸出：`data/etf/<ETF>/<YYYYMMDD>.csv`，欄位 `date, etf, code, name, shares, weight`
  - 檔名日期是投信公告的**持股基準日**；股票名稱統一用交易所簡稱，方便跨 ETF 比對
- `data/etf/summary.csv`：每檔每日的基金規模、流通單位數、淨值、持股檔數（單位數變化 = 申購贖回）
- 目前追蹤：0050、0056、00713、00940（元大）、006208（富邦）、00878（國泰）、00919（群益）、00929（復華）
- 新增 ETF：同一家投信只要在 `ETF_LIST` 加一行；新投信要多寫一個 adapter

```bash
python fetch_etf.py              # 全部
python fetch_etf.py 0050 00878   # 指定
```

## 網站（GitHub Pages）

網址：https://b04703088.github.io/TaiwanStkInf/ （成交排行：`ranking.html`）

- `site/`：網頁原始檔（首頁 `index.html`、成交金額排行 `ranking.html`）
- `scripts/build_site.py`：把最近 120 個交易日的 CSV 轉成 `data/daily/<日期>.json` 給網頁讀
- `.github/workflows/pages.yml`：每日抓完資料、或改了 `site/` 後自動重建部署

## 同步到 Firebase（Firestore）

每次抓到新資料後，workflow 會用 `upload_firestore.py` 把這次新增的 CSV 寫進 Firestore：

- `stock_prices/{code}/daily/{YYYY-MM-DD}`：每檔每日一筆
- `daily_snapshots/{YYYY-MM-DD}`：當日全市場一份，`data` 欄位是 JSON 字串（`{columns, rows}`），前端用 `JSON.parse` 讀
- `jobs/firestore_upload`：最後一次上傳狀態

啟用方式：Firebase Console → 專案設定 → 服務帳戶 → 產生私密金鑰，把整份 JSON 貼到 GitHub repo 的
Settings → Secrets and variables → Actions → `FIREBASE_SERVICE_ACCOUNT`。沒設定就自動略過。

一天約 2,000 次寫入，Firestore 免費額度每天 20,000 次，所以一次最多上傳最新 5 天（`--max-files`）。

## 本機執行

```bash
python fetch_daily.py                                   # 今天
python fetch_daily.py --date 2026-09-23                 # 指定日期
python fetch_daily.py --start 2026-09-01 --end 2026-09-23   # 回補
python upload_firestore.py --latest 5                   # 把最新 5 天寫進 Firestore（需憑證）
python -m unittest discover tests                       # 測試
```

也可在 GitHub → Actions → "Fetch daily stock prices" → Run workflow 手動觸發或回補。
