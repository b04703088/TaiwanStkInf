# TaiwanStkInf

每日自動抓取台股收盤行情（上市 TWSE + 上櫃 TPEx）。

- `fetch_daily.py`：抓取腳本，只用 Python 標準函式庫
- `.github/workflows/daily.yml`：週一至週五台北時間 15:30 自動執行，結果 commit 到 `data/`
- 已抓過的日期、週末、已確認的非交易日（記在 `data/no_trading_days.txt`）會直接跳過不連線；`--force` 可強制重抓
- 輸出：`data/<YYYY>/<YYYYMMDD>.csv`，欄位 `date, market, code, name, open, high, low, close, change, volume, value, transactions`

## 還原股價（除權息、減資、面額變更、ETF 分割）

`fetch_adjust.py` 抓證交所／櫃買中心公布的「基準價變動」事件，每個事件都有事件前收盤價與事件後參考價，
相除就是還原因子 `factor = ref_price / prev_close`。workflow `.github/workflows/adjust.yml` 週一至週五台北 18:53 跑（抓近 60 天到未來 14 天），已回補 2022 年起。

- 來源：上市 TWT49U（除權除息計算結果）、TWTAUU（減資）、TWTB8U（變更面額）、TWTCAU（ETF 分割／反分割）；
  上櫃 exDailyQ（除權除息）、revivt（減資）、pvChgRslt（變更面額）、etfSplitRslt／etfRvsRslt（ETF 分割／反分割）
- 輸出 `data/adjust/events.csv`，欄位 `date, market, code, name, kind, prev_close, ref_price, factor, cash, note, source`
  - `date`：除權息日／恢復買賣日，這天起是新基準；這天之前的價格要乘 `factor`
  - `kind`：除息、除權、除權息、減資、面額變更、分割、反分割；`cash`：每股現金股利或減資退還股款（查得到才填）
- 換算：還原價(t) = 原始價(t) × 所有「事件日 > t」的 factor 連乘（向後還原，最新價格不變）；成交量反向除以同一個倍數

```bash
python adjust.py 2330                                  # 2330 每天的原始價＋還原價（CSV）
python adjust.py 0050 --start 2025-01-01 --events      # 只列事件與累積因子
python fetch_adjust.py --since 2022-01-01              # 手動回補
```

網站「K線」頁（`site/kline.html`，資料由 `scripts/kline_site.py` 產生 `data/kline/s/<代號>.json`）畫日／週／月 K、均線 5/20/60，可切換還原價與原始價，事件日在圖下方標「息、權、減、面、分」。網址可帶 `#s=2330` 直接開某一檔。

## ETF 每日持股明細

每天抓各投信公告的 ETF 持股（成分股、總股數、權重），workflow `.github/workflows/etf.yml` 每個工作日跑三次並 commit。

- **追蹤 90 檔**：國內股票型 ETF（主動式＋被動式）全數納入，另含幾檔主動式海外股票 ETF（清單在 `fetch_etf.py` 的 `ETF_LIST`，也輸出成 `data/etf/etf_list.csv`）
  - 被動式 19 檔：0050、0056、00713、00850、00940、006208、00692、00892、00900、00878、00881、00919、00927、00946、00929、00891、00915、00935、00939
  - 主動式 31 檔：00400A–00411A、00980A–00999A（00996A 兆豐網站擋 GitHub 主機，暫不追蹤）
  - 20 家投信：元大、富邦、國泰、群益、復華、統一、中信、野村、安聯、凱基、台新、永豐、第一金、聯博、摩根、富蘭克林華美、大華銀、玉山、聯邦、華南永昌
  - 兆豐投信（00690、00913、00932、00921、00943、00996A）官網擋 GitHub 主機（403），暫無法追蹤
  - 大華銀官網憑證鏈不完整，只對該網域略過憑證驗證（僅讀取公開持股資料）
- 輸出：`data/etf/<ETF>/<YYYYMMDD>.csv`，欄位 `date, etf, code, name, shares, weight`
  - 檔名日期一律是**持股基準日**（投信的 PCF 公告日是隔一個交易日，已換算對齊）
  - 台股名稱統一用交易所簡稱；海外持股代號為 `NVDA US` 格式，跨 ETF 可直接比對
  - 股數一律用投信公布的實際持股，不做推算（國泰用官網「持股權重」分頁的 API，含實際持有股數）
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

### 指數調整行事曆（臺灣指數公司）

`fetch_tip_schedule.py` 讀臺灣指數公司每月的「指數定期審核日程表」PDF（公開下載），整理各指數的公告日（收盤後）與生效日，
並用證交所 ETF 基本資料的「標的指數」比對追蹤的 ETF。隨 `etf.yml` 每天執行（TIP 會原檔更新，最新 3 份每次重抓）。

- 輸出 `data/etf/tip/schedule.csv`（index, announce_date, effective_date, schedule, source_id, file_date）、`etf_index.csv`、`sources.json`
- 同時抓「定審結果」公告（2024/09 起約 300 份），輸出 `data/etf/tip/results.csv`（index, announce_date, effective_date, action add/del/none, code, name, source_id），
  含富時合編的臺灣50、中型100、高股息等指數；網頁在每個指數下列出納入／刪除名單
- 網站 ETF持股 →「指數調整行事曆」：即將公告／已公告、只看有 ETF 追蹤的指數、30 天內審核，可用個股代號或名稱搜尋
- 比對不到的（多半是上櫃 ETF）可在 `config/tip_index_etf.csv` 手動補一行 `指數名稱,ETF代號`

### 指數調整（換股）時長

`fetch_etf_rebalance.py`（`.github/workflows/rebalance.yml` 每週六補查；`etf.yml` 每天只做偵測）用歷史持股算出被動式 ETF 每次換股從開始到完成花了幾個交易日，網頁在 ETF持股 →「調整時長」（`etf.html#rebal`）。

- 可回推歷史持股：元大、國泰、群益、復華、中信、統一、野村、大華、第一金、安聯、玉山（投信網站可帶日期查）；富邦、凱基等只有最新持股，從每日排程累積
- 做法：每 5 個工作天粗掃 → 成分股有變的區間逐日補齊 → 用股數（除以延續成分股股數變化的中位數，扣掉申購贖回）算進度：
  刪除股減少 5% 以上或新增股出現＝開始；每檔完成 85% 以上且平均 97% 以上＝完成。個股短暫漏列（30 天內以相近股數再出現）會補回
- 有指數生效日（臺灣指數公司、MSCI）時，另算開始／結束相對生效日差幾個交易日
- 輸出 `data/etf/rebalance/events.csv`（每次換股）、`holdings/<ETF>.csv`（回推的歷史持股）、`asked.json`（查過的日期）

### 指數行事曆（月曆）

ETF持股的子頁「指數行事曆」`calendar.html`（`scripts/calendar_site.py` → `data/calendar.json`）把指數審核與 ETF 換股放在同一張月曆，只放規模 300 億以上的 ETF（`MIN_AUM`）：

- 公告日／生效日：臺灣指數公司日程表與定審結果、富時合編指數、MSCI 臺灣指數（同 ETF持股 → 指數調整行事曆）
- 預估審核：日程表還沒公布的，用去年同期 +52 週（同星期幾）推估，公告到生效隔幾個交易日照去年；正式日程出來就取代
- ETF 換股期間：已發生的用「調整時長」實際偵測；未來的用該 ETF 通常的相對生效日期間推估（不早於公告隔天）
- 資料截止日：各指數規則在 `scripts/index_rules.py`（臺灣指數公司編製規則、富時臺灣指數系列規則＝生效日前四週星期一、MSCI＝公告前一個月最後 10 個營業日之一、
  00891＝審核月第三個星期五前 3 個營業日…），並附出處
- 另外加入：MSCI 客製指數（00878、00922，跟 MSCI 5/11 月半年度審核）、00891（ICE，1/4/7/10 月）、富時全球（FTSE GEIS）季度審核；
  MSCI 臺灣指數與富時全球不限 ETF 規模一律顯示
- 交易日：證交所休市日 `fetch_holidays.py` → `data/calendar/holidays.csv`（`etf.yml` 每天更新；隔年日程證交所約 12 月公布）

### MSCI 臺灣指數季度審核

`fetch_msci.py` 讀 MSCI 官網公開的「Global Standard Indexes List of Additions/Deletions」PDF，取 MSCI TAIWAN INDEX 段（2023 年起），
以及 MSCI 公布的未來八次審核日期（ir_dates.csv）。追蹤 ETF：0057、006203。

- 名單只有英文名，用證交所／櫃買中心公司資料（英文簡稱、網址、e-mail 網域）自動對應代號；不夠確定時留空，
  手動對照寫在 `config/msci_names.csv`（en_name,code），資料健檢會列出對不到的名稱
- 輸出 `data/etf/msci/results.csv`、`schedule.csv`；生效日 = MSCI「as of the close of」的下一個交易日
- 富時合編指數（臺灣50、中型100、高股息等）的審核結果由臺灣指數公司轉公告，已含在 TIP 定審結果中

## 網站（Cloudflare Pages）

網址：https://tide-stk-infs.pages.dev/ （成交排行：`ranking.html`）

- `site/`：網頁原始檔（首頁 `index.html`、成交金額排行 `ranking.html`、ETF持股 `etf.html`：個股持有查詢／每日持股變化／AUM 排行）
- `scripts/etf_site.py`：整理 ETF 最新持股與前一份的原始股數差異（含申購贖回）→ `data/etf/latest.json`
- `scripts/build_site.py`：把最近 120 個交易日的 CSV 轉成 `data/daily/<日期>.json` 給網頁讀
- `.github/workflows/pages.yml`：固定時段統一重建部署（台北 平日 08:53、14:03、20:03、23:03，週六 12:03），抓資料的 workflow 只 commit 不觸發部署；改了 `site/` 或網頁程式 push 到 main 時也會立即重建
  - repo variable `DEPLOY_TARGET=cloudflare` 時部署到 Cloudflare Pages（需要 secrets `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`；專案名稱預設 `tide-stk-infs`，可用 variable `CF_PAGES_PROJECT` 改）；沒設時部署到 GitHub Pages

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


## 券商分點（前 15 大）

`fetch_broker.py` 每天抓全部有成交的上市櫃股票（約 2,400 檔）的前 15 大買超、前 15 大賣超分點，
來源是富邦證券網站的公開頁面（MoneyDJ 券商分點進出明細，免登入），單位：張。

- 輸出 `data/broker/<YYYY>/<YYYYMMDD>.csv`：`date, code, side(B/S), rank, bid, broker, buy, sell, net, pct`
- 輸出 `data/broker/<YYYY>/<YYYYMMDD>_total.csv`：前 15 大合計買超／賣超張數、平均買超／賣超成本
- `.github/workflows/broker.yml`：股價 workflow 完成後接著跑，另有台北 18:33、22:03 備援；資料尚未公布時直接結束
- 一次一條連線、每頁間隔 0.15 秒，全部約 30～40 分鐘；中斷後重跑只補沒抓到的股票
- 只公布前 15 大，不是全部分點；分點頁只看得到該分點擠進某檔股票前 15 大的部分
- 網站「分點籌碼」頁（`broker.html`）：主力買賣超排行（集中度 = 主力買賣超 ÷ 成交量）、個股分點明細、單一分點的上榜個股

### 重點分點追蹤

`config/broker_watch.csv` 列出要追蹤的分點（`label` 網頁顯示名稱、`branch` 富邦網站上的分點名稱；總公司就寫券商名稱，例如「康和」）。
分點名稱可查 `data/broker/branches.csv`（約 900 個分點）。**增刪分點只要編輯這個檔案**，存檔後 `broker.yml` 會自動回補近 20 個交易日、網站也會跟著更新。

- `fetch_broker_watch.py`：富邦「分點明細查詢」，每個分點每天買超、賣超各前 50 檔，金額（仟元）與張數
- 輸出 `data/broker/watch/<YYYY>/<YYYYMMDD>.csv`：`date, bid, branch, code, name, buy_amt, sell_amt, net_amt, buy_sh, sell_sh, net_sh`
- 網站 `watch.html`（分點籌碼 → 重點分點）：選取分點的買賣超金額加總排行，可選當日／近 5、10、20 日，可只看部分分點；另有「大額買賣超清單」：當日 >5,000 萬、近 5 日 >1 億、近 20 日 >3 億的買超／賣超股票

### 分點評分與分類（波段高手／隔日沖／反指標）

`broker_score.py`（不連網，`broker.yml` 抓完分點後接著跑，約 5 秒）用前 15 大分點＋重點分點資料，替每個分點打分數：

- 事件：買超或賣超 ≥ 當天成交量 1% 且 ≥ 500 萬元（只算 4 位數代號的一般股票）
- 報酬：隔天開盤買進、持有 1／5／20 個交易日，扣掉全市場等權平均；同一分點同一檔 h 天內只算第一次
- 分數 z：買超後的超額報酬與賣超後的負超額報酬合計 ÷（全體標準差 × √次數）
- 分類：隔日沖（買超隔天賣掉 ≥ 50%，或 ≥ 35% 且買在當天大漲 3% 以上）→ 樣本不足（5 日事件 < 10 次或 < 10 個交易日）→ 波段高手 z ≥ 2 → 反指標 z ≤ −2 → 一般
- 只用評分日以前已實現的報酬；`--as-of YYYY-MM-DD` 可模擬過去某天的評分（回測用）
- 輸出 `data/broker/score/branches.csv`（每個分點的分數）、`signals.csv`（最新一天高手／反指標／隔日沖各買賣了哪些股票，pct 為佔成交量 %）
- 前 15 大資料從 2026-09-30 才開始，要累積 2～3 個月分數才有意義；可用 `backfill_broker.py --start 2026-07-01` 在自己電腦回補（一天約 30 分鐘，不佔 Actions 分鐘數）

## 內部人持股異動

`fetch_insider.py`：董監事、經理人、10% 大股東的買賣。

- **月報（事後申報）**：每月 15 日前申報上個月，證交所約 22 日公布全市場「股權異動彙總表」（IRB110）。
  先用彙總表篩出內部人持股有增加的公司（約 350 家），再逐家查觀測站「內部人持股異動事後申報表」（query6_1，一家約 4 秒，約 25 分鐘），
  分出 **集中市場買進／賣出**（`buy_mkt`、`sell_mkt`）與 其他原因（贈與、信託、繼承、員工認股…）
  - `.github/workflows/insider.yml`：每月 18～28 日台北 19:07 檢查；已抓過幾秒就結束；超過 35 分鐘會存進度，隔天接著查
  - 輸出 `data/insider/trades/<YYYYMM>.csv`：`month, market, code, company, role, name, held_prev, buy_mkt, buy_other, sell_mkt, sell_other, held_now, pledged, note, dup`
    （同一人兼多個身分只列一次；夫妻都是內部人時「甲的配偶」那列＝乙本人，`dup` 填乙，加總要略過）
  - `data/insider/irb110/<YYYYMM>_<sii|otc>.csv`：每家公司董監增減、董監／經理人／大股東持股合計
  - 只賣不買的公司不查（賣出看下面的事前申報）
- **事前申報（每天）**：內部人要在市場上賣、贈與、信託前要先申報，OpenAPI 只給最新一天，跟著 `broker.yml` 每天抓、累積到 `data/insider/transfer/<YYYY>.csv`
  （`date, market, code, company, role, name, method, shares, held, after, daily_max, transferee, period`）

## 可轉債詢圈（CB）

`fetch_cb.py`（`.github/workflows/cb.yml`，平日台北 08:13、18:13）把每檔 CB 從圈購到掛牌的時間點整理成 `data/cb/cases.csv`，網頁在 `cb.html`。

| 來源 | 拿到什麼 |
|---|---|
| 證券商業同業公會承銷公告 — 詢圈公告 | 圈購期間、溢價率區間、承銷／圈購張數（還沒訂價的案子只有這裡有） |
| 同上 — 競拍公告 | 投標期間、競拍張數 |
| 同上 — 承銷公告 PDF（銷售辦法公告） | 第幾次、訂價基準日、轉換價、溢價率、發行價、繳款日、預定上櫃日 |
| 櫃買中心 OpenAPI `bond_ISSBD5_data` | 債券代號、實際發行／上櫃日、發行時轉換價（只含流通中的債券） |

- 已解析過的 PDF 記在 `data/cb/notices.csv`，不會重抓；剛申報（30 天內）而 PDF 還沒有訂價結果的會每次重試。
- 公司全名對不到代號時，網頁的資料健檢會列出來；在 `config/cb_names.csv` 加一行 `name,code` 即可。
- 手動回補：Actions → Fetch CB bookbuilding → Run workflow，`years` 填 `2024 2025`。

### 詢圈之前：董事會決議 → 送件 → 申報生效

`fetch_cb_pre.py`（同一個 workflow，在 `fetch_cb.py` 之前跑）補上承銷之前的三個時間點，網頁在「籌備中」子頁（`cb-pipeline.html`）。

| 來源 | 拿到什麼 |
|---|---|
| 金管會證期局「受理申報(請)案件情形」→ 申報案件彙總表（今年＋去年，ODS） | 送件（收文）日、生效日（審查中的是預計生效日）、停止生效／撤回／退件 |
| 公開資訊觀測站重大訊息（新版 API，依日期） | 董事會決議日、第幾次、有無擔保、發行總額、詢圈或競拍、主辦承銷商；撤回公告 |

- 結果在 `data/cb/sfb.csv`、`data/cb/mops_events.csv`，`fetch_cb.py` 會把它們接到同一檔 CB（同代號、日期與金額最接近者）。
- 重訊第一次會從 2025-01-01 逐日回補，每次最多 20 分鐘，進度記在 `data/cb/mops_days.txt`；之後每次只重抓最近 7 天。
- 董事會通過超過一年仍未送件的不列入。

## 產業分類

`fetch_industry.py`（`.github/workflows/industry.yml`，每週六台北 09:13）整理每檔股票的產業細分類，網頁在 `industry.html`。

| 來源 | 拿到什麼 |
|---|---|
| 櫃買中心「產業價值鏈資訊平台」（ic.tpex.org.tw，47 個產業） | 產業 › 上中下游 › 類別 › 細類，各類別的上市／上櫃／興櫃公司；一檔股票可屬於多個細類 |
| 證交所／櫃買 OpenAPI 公司基本資料 | 官方「產業別」代碼（平台沒收錄的股票用這個） |

- 輸出 `data/industry/chain.csv`（`code, name, industry_id, industry, stream, node_id, node, sub_id, sub`）、`data/industry/official.csv`。
- 網頁：查個股所屬細類、今日細產業強弱排行（等權平均漲跌，3 檔以上）、依產業瀏覽各細類成分股與漲跌。

### 族群資金流向

`scripts/flow_site.py` 在建網站時把最近 60 個交易日的個股成交金額（只含上市櫃普通股）和族群名單寫成 `data/flow.json`，網頁 `flow.html`（成交排行 → 族群資金流向）計算：

- 成交佔比＝族群成交金額 ÷ 全部個股成交金額；佔比變化＝今日 − 近 5／20 日平均（百分點）
- 增減金額＝今日成交金額 − 近 5／20 日平均成交金額；熱度＝今日佔比 ÷ 近 N 日平均佔比
- 趨勢＝近 5 日平均佔比 − 近 20 日平均佔比（百分點），看資金是不是連續幾天往同一族群集中；連續＝佔比連續幾天高於（或低於）前 20 日平均；點族群可看佔比走勢圖（每日、5 日、20 日均線）
- 族群走勢比較：表格上方的重疊圖，預設畫表格前 4 名的佔比走勢，點表格左邊圓點可自選（最多 8 個）；可切 20／40／60 日、每日／5 日均、成交佔比／相對平均（÷ 期間平均 × 100）
- 族群：產業價值鏈細類、產業、官方產業別三種層級；近 N 日平均成交不到 2 億的族群不列入

## 外資報告與市場共識

`fetch_analyst.py`（`.github/workflows/analyst.yml`，每天台北 08:23、13:53、21:23）從鉅亨網新聞整理外資對台股的評等、目標價，以及 FactSet 市場共識。

| 來源 | 拿到什麼 |
|---|---|
| 鉅亨網新聞 API（`api.cnyes.com/media/api/v1/newslist/category/tw_stock`、`tw_quo`，公開免登入） | 台股新聞全文，一天約 100～300 則 |

- **外資個股報告** `data/analyst/reports_<YYYY>.csv`：`date, time, news_id, broker, code, name, action(up/down/maintain/initiate), rating, target, prev_target, title, url`
  - 同一句提到券商（高盛、大摩、小摩、美銀、花旗、瑞銀、野村、麥格理…，或「美系外資」等）又有**新台幣**目標價或投資評等才收；不具名的「外資」一定要有目標價
  - 評等統一成 買進／加碼／中立／減碼／賣出（優於大盤、增持、Overweight → 加碼）；外資買賣超（加碼 N 張）不會被當成評等
  - 鉅亨網對外資個股報告的報導不算多（大型權值股為主），只是新聞轉述，不是報告原文
- **FactSet 市場共識** `data/analyst/consensus_<YYYY>.csv`：鉅亨網「Factset 最新調查」自動快訊，一天約 5～10 則
  - `kind=eps`：分析師人數、預估年度、EPS 中位數前值→新值、最高／最低、共識目標價
  - `kind=tp`：目標價中位數前值→新值、調整幅度、最高／最低、看多／中立／看空家數、當日收盤
- 只存標題、連結與數字，不存新聞內文
- API 一次查詢最多翻約 1,000 則，所以按「一天」查；可回查好幾年。今天、昨天每次重抓，更早的抓完記在 `data/analyst/days.txt` 不再重抓
- 回補：Actions → Fetch analyst reports → Run workflow，填起訖日；一年約 1 小時，超過 `max_minutes` 會停，再按一次會接著抓

網頁 `analyst.html`（導覽列「外資報告」，`scripts/analyst_site.py` → `data/analyst/analyst.json`）：
查個股（共識目標價、潛在空間、看多／中立／看空、EPS 預估與歷次紀錄）、共識目標價 vs 現價排行、最新動態（可篩外資報告／共識目標價／共識 EPS、上修／下修、期間）。

```bash
python fetch_analyst.py                                   # 最近 3 天
python fetch_analyst.py --start 2025-10-01 --end 2026-09-30 --max-minutes 50
```

## 處置股、注意股

`fetch_alert.py`（`.github/workflows/alert.yml`，平日台北 18:47、隔天 07:47 補抓）抓證交所與櫃買中心的每日公告，存在 `data/alert/`：

- **處置** `disposal.csv`：`market(上市/上櫃), ann_date, code, name, start, end, reason, measure(第一次／第二次／再次處置), interval(撮合間隔分鐘), detail`
- **注意** `attention.csv`：`market, date, code, name, info, clauses(第幾款，; 分隔), close, pe`
- **注意累計次數異常**（瀕臨處置）`near.csv`：`date, market, code, name, situation`；官方只提供當天名單，每天抓一次累積
- 每次抓最近 10 天，與舊資料合併；含權證、可轉債，網頁才濾成股票與 ETF。回補：Actions → Fetch disposal & attention stocks → Run workflow 填起日（已回補到 2025-01-01）

網頁 `alert.html`（導覽列「處置注意」，`scripts/alert_site.py` → `data/alert/alert.json`）：即將出關（出關日、還剩幾天、處置期間漲跌）、處置中與即將處置（剩幾天、撮合間隔）、明天可能處置（依處置標準由注意紀錄推算，2025 年起回測與實際公告完全吻合，附名單命中率）、注意股（可選日期，含連續天數與近 10／30 日次數）、查個股、處置紀錄。

```bash
python fetch_alert.py                      # 最近 10 天
python fetch_alert.py --start 2025-01-01   # 回補
## 重大訊息（董事會、股東會、法說會、除權息）

`fetch_mops_news.py`（`.github/workflows/mops.yml`，週一至週五台北 08:37、17:37、22:37，週六 09:37）從公開資訊觀測站抓上市、上櫃每天所有重大訊息（不含興櫃）。

- 資料來源：觀測站新版 API `t05st02`（某天所有重訊主旨）、`t05st02_detail`（單則內容），跟 `fetch_cb_pre.py` 同一組
- `data/mops/news/<YYYY-MM>.csv`：`date, time, code, name, market, cat, sub, subject, enter_date, serial, ev_kind, ev_date, ev_note, summary`
  - `cat` 依主旨關鍵字分類：股東會、法說會、董事會決議、股利、財報營收、注意處置、訴訟調查、人事異動、庫藏股、增減資籌資、取得處分併購、澄清報導、其他；`sub=1` 是代子公司公告
  - 「董事會決議召開股東會」與法說會公告會再讀內容，`ev_date` 是開會日期（`ev_kind`＝常會／臨時會／法說會）
  - 董事會決議、股利、股東會決議、庫藏股、增減資、併購、人事異動也會讀內容，`summary` 是一行重點；除權息公告另填 `ev_kind`＝除權／除息／除權息、`ev_date`＝除權息交易日
- `data/mops/exright.csv`：證交所 `TWT48U_ALL`、櫃買 `tpex_exright_prepost` 除權除息預告表（`stock` 是每股配股換算成元，配股率 × 10）
- `data/mops/calls.csv`：觀測站法說會一覽表（`mopsov.twse.com.tw/mops/web/ajax_t100sb02_1`，本月＋下月），`file` 是中文簡報檔名（`https://mopsov.twse.com.tw/nas/STR/<file>`），`video` 是影音連結
- 今天、昨天每次重抓；更早的抓完記在 `data/mops/days.txt`。預設回補 60 天，要更早：Actions → Fetch MOPS news → Run workflow 填 `since`（股東會旺季一天要讀上百則內容，約 3～4 分鐘）
- 董事會開會日期多半不會事先發重訊，所以只看得到董事會「決議」

網頁 `news.html`（導覽列「重大訊息」，`scripts/mops_site.py` → `data/mops/mops.json`）：
- 查個股：輸入代號看完整時間軸（重訊、股東會、法說會、除權息，加上外資報告、CB、處置注意頁的資料），網址 `news.html#s=2330` 可直接分享
- 關注清單：個股旁的 ☆ 加入，存在這台瀏覽器（localStorage `tide.watch`）；行事曆與重訊都可以「只看關注」
- 股東會・法說會・除權息行事曆：依日期分組，可篩種類、即將舉行／近 30 天；法說會有簡報連結
- 最近 30 天重訊列表：分類、關鍵字、是否含代子公司公告、內容摘要

```bash
python fetch_mops_news.py                                  # 今天、昨天＋回補 60 天內還沒抓過的
python fetch_mops_news.py --since 2026-01-01 --max-minutes 50
```

## 庫藏股

`fetch_treasury.py`（`.github/workflows/treasury.yml`，週一至週五台北 08:37、19:37）整理上市櫃公司買回自家股份的計畫與結果。

| 來源 | 拿到什麼 |
|---|---|
| 公開資訊觀測站「庫藏股統計彙總表」（`mopsov.twse.com.tw/mops/web/ajax_t35sc09`，上市、上櫃各查一次，依董事會決議日） | 決議日、目的、預定股數、價格區間、預定期間；結束後的實際股數、金額、均價、佔股本 |
| 觀測站「買回達一定標準」（`ajax_t35sb01`，只查執行中的計畫） | 每買回達已發行股數 2% 或 3 億元的申報，當作執行中進度 |
| 富邦證券網站（MoneyDJ）券商分點進出明細，查整段日期區間（`fetch_treasury_broker.py`，同一個 workflow） | 每次買回期間、買回前 60 天的分點買超前 15 名，用來比對公司派分點 |

- `data/treasury/programs.csv`：每次買回計畫一列，每次重抓前年 1 月 1 日起的計畫，更早的保留不動
- `data/treasury/progress.csv`：執行中計畫的達標申報
- `data/treasury/brokers.csv`：買回期間（`win=in`）與買回前 60 天（`win=pre`）的分點買超前 15 名；已結束的只查一次，執行中的每次更新
- 回補：Actions → Fetch treasury stock → Run workflow，填 `since`

網頁 `treasury.html`（導覽列「庫藏股」，`scripts/treasury_site.py` → `data/treasury.json`）：
執行中（價格區間、收盤是否在區間內、預定金額、期間剩幾天、已申報進度、公司派分點本期買超）、公司派分點（每家公司比對到的分點與次數）與已結束（執行率、平均買價、收盤 vs 均價、佔股本、推定買回分點）。

公司派分點比對（`scripts/treasury_broker.py`）：公司買回只買不賣，所以在買回期間挑「幾乎只買不賣、買超至少佔實際買回 10%」的分點，從大到小加總到不超過實際買回張數 115%（最多 3 個），
合計 ÷ 實際張數 85～115% 標「高」。2024 年起 535 次有買到股票的買回裡，456 次吻合度「高」。

## 財報資料（月營收、季報）

`fetch_financials.py`（`.github/workflows/financials.yml`，每天台北 18:40）從公開資訊觀測站抓上市＋上櫃公司的月營收與每季財報重點項目，存成 CSV。金額單位一律**新台幣千元**（EPS、每股淨值是元）。

| 來源（公開免登入，觀測站舊版 `mopsov.twse.com.tw`） | 拿到什麼 |
|---|---|
| `nas/t21/<sii\|otc>/t21sc03_<民國年>_<月>_<0\|1>.html` | 月營收彙總表（國內／外國公司），102 年起 |
| `mops/web/ajax_t163sb04`、`ajax_t163sb05` | 綜合損益表、資產負債表彙總（全市場一次回來，一次要 1～2 分鐘） |

- **月營收** `data/financials/revenue/<YYYYMM>.csv`：`ym, market, code, name, industry, revenue, prev_month, last_year, mom_pct, yoy_pct, cum, cum_last_year, cum_yoy_pct, note`
  - 每月 10 日前公布、之後可能更正，所以最近 2 個月每次重抓；`note` 是公司對營收大幅增減的說明
- **季報** `data/financials/quarterly/<YYYY>Q<n>.csv`：`year, season, market, code, name, type` ＋
  - 損益（**當年累計**）：`revenue, gross_profit, operating_income, pretax_income, net_income, net_income_parent, eps`
  - 單季（本季累計減前一季累計）：同上欄位加 `q_` 前綴；前一季沒資料就空白
  - 資產負債（季底）：`current_assets, total_assets, current_liabilities, total_liabilities, capital, retained_earnings, equity_parent, equity, bvps`
  - `type`：一般／銀行／金控／證券／保險／其他。觀測站對不同行業用不同格式，這裡統一欄位；銀行沒有「營業收入」，`revenue` 用淨收益（利息淨收益＋利息以外淨損益）；保險業 2026 年起適用 IFRS 17、沒有營業收入，`revenue` 空白；金融業沒有毛利、流動資產等欄位就空白
  - 沒有子公司的公司（個體報表）不分歸屬，`net_income_parent`、`equity_parent` 等於全部
  - 申報期間（Q1 4/1～6/15、Q2 7/1～9/15、Q3 10/1～12/15、Q4 隔年 1/1～4/15）每天重抓，期間過了就不再抓
- 回補：例行執行也會在 40 分鐘內往回補 2019-01 之後還沒有的月份／季別（一季約 4～5 分鐘），幾天內補完；
  要補更早的：Actions → Fetch financials → Run workflow，`since` 填 `2013-01`。只重抓某月／某季填 `only`（`2026-09` 或 `2026Q2`）
- `data/financials/sources.json`：最近一次執行抓了哪些月份／季別、錯誤訊息

網頁 `fin.html`（導覽列「財報」，`scripts/fin_site.py` → `data/fin/index.json` 與每檔 `data/fin/s/<代號>.json`）：
查個股（近三年月營收與年增率、單季 EPS 與營益率圖，季報與月營收明細）、月營收排行（年增、創 N 個月新高、累計年增、月增，可篩上市／上櫃與營收規模）、季報排行（單季 EPS、EPS 年增、營收年增、毛利率、近四季 EPS、ROE）。

```bash
python fetch_financials.py                        # 例行
python fetch_financials.py --revenue 2026-09      # 某月營收
python fetch_financials.py --quarter 2026Q2       # 某季財報
python fetch_financials.py --since 2013-01 --max-minutes 50
```

## 資料健檢

`scripts/health.py` 檢查資料有沒有漏抓或抓錯，結果在網站的 `health.html`（ETF持股、成交排行頁尾有連結）。

- 股價：最近一個應開盤日（平日、不在 `data/no_trading_days.txt`）是否有收盤檔、檔數是否正常
- ETF 持股：每檔落後幾個交易日（≥ 2 為異常；T+1 公告的投信早上落後 1 天屬正常）、成分股數、權重加總（< 70% 或 > 105% 異常，< 80% 留意）、檔數與前一份相差 > 25%、股數缺漏
- 券商分點：最新一天是否落後、檔數是否齊全
- 重點分點：最新一天是否落後、設定的分點是否都有資料
- ETF 規模：最新一天是否落後
- `.github/workflows/health.yml` 每週二至週六台北 09:07 自動執行；有異常時該次執行失敗，GitHub 會寄 Actions 失敗通知信
- 另外 `etf.yml` 只要有任何一檔 ETF 抓取失敗，整次執行就會標示失敗（已抓到的仍會存檔），同樣會寄通知信

