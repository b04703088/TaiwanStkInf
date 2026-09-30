# TaiwanStkInf

每日自動抓取台股收盤行情（上市 TWSE + 上櫃 TPEx）。

- `fetch_daily.py`：抓取腳本，只用 Python 標準函式庫
- `.github/workflows/daily.yml`：週一至週五台北時間 15:30 自動執行，結果 commit 到 `data/`
- 已抓過的日期、週末、已確認的非交易日（記在 `data/no_trading_days.txt`）會直接跳過不連線；`--force` 可強制重抓
- 輸出：`data/<YYYY>/<YYYYMMDD>.csv`，欄位 `date, market, code, name, open, high, low, close, change, volume, value, transactions`

## ETF 每日持股明細

每天抓各投信公告的 ETF 持股（成分股、總股數、權重），workflow `.github/workflows/etf.yml` 每個工作日跑三次並 commit。

- **追蹤 50 檔**（清單在 `fetch_etf.py` 的 `ETF_LIST`，也輸出成 `data/etf/etf_list.csv`）
  - 被動式 19 檔：0050、0056、00713、00850、00940、006208、00692、00892、00900、00878、00881、00919、00927、00946、00929、00891、00915、00935、00939
  - 主動式 31 檔：00400A–00411A、00980A–00999A（00996A 兆豐網站擋 GitHub 主機，暫不追蹤）
  - 15 家投信：元大、富邦、國泰、群益、復華、統一、中信、野村、安聯、凱基、台新、永豐、第一金、聯博、摩根
- 輸出：`data/etf/<ETF>/<YYYYMMDD>.csv`，欄位 `date, etf, code, name, shares, weight`
  - 檔名日期一律是**持股基準日**（投信的 PCF 公告日是隔一個交易日，已換算對齊）
  - 台股名稱統一用交易所簡稱；海外持股代號為 `NVDA US` 格式，跨 ETF 可直接比對
  - 股數一律用投信公布的實際持股，不做推算；國泰投信只公布持股權重，股數欄留空（變化只看新增／剔除）
- `data/etf/summary.csv`：每檔每日的基金規模、流通單位數、淨值、持股檔數（單位數變化 = 申購贖回）
- `data/etf/source_ids.json`：各投信內部基金代碼快取（投信清單端點失敗時備援）

程式結構：`etf_common.py`（HTTP、日期/代號解析）、`etf_adapters.py`（每家投信一個 adapter）、`fetch_etf.py`（清單、檢查、輸出）。
新增 ETF：同一家投信只要在 `ETF_LIST` 加一行；新投信要在 `etf_adapters.py` 多寫一個 adapter。

```bash
python fetch_etf.py                  # 全部
python fetch_etf.py 0050 00981A      # 指定
python fetch_etf.py --issuer ctbc    # 某家投信
```

### 全體 ETF 規模（AUM）

`fetch_etf_aum.py` 抓證交所 ETF 淨值揭露（`mis.twse.com.tw/stock/data/all_etf.txt`，全體上市櫃 ETF 約 350 檔），
算出規模 = 發行單位數 × 前一營業日淨值、資金流入 = 單位增減 × 淨值，存成 `data/etf/aum/<YYYYMMDD>.csv`；
類型（國內股票／主動式／國外股票／債券／槓桿反向／期貨商品）依證交所 ETF 基本資料。隨 `etf.yml` 每天執行。

## 網站（GitHub Pages）

網址：https://b04703088.github.io/TaiwanStkInf/ （成交排行：`ranking.html`）

- `site/`：網頁原始檔（首頁 `index.html`、成交金額排行 `ranking.html`、ETF持股 `etf.html`：個股持有查詢／每日持股變化／AUM 排行）
- `scripts/etf_site.py`：整理 ETF 最新持股與前一份的差異（扣除申購贖回造成的同比例增減）→ `data/etf/latest.json`
- `scripts/build_site.py`：把最近 120 個交易日的 CSV 轉成 `data/daily/<日期>.json` 給網頁讀
- `.github/workflows/pages.yml`：每日抓完股價或 ETF 持股、或改了 `site/` 後自動重建部署

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
