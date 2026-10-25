# 永豐金證券（Shioaji）回測與自動下單 — AutoTradeSys fork 使用說明

> 本功能是本 fork 新增的客製化（2026-10-25），不屬於上游 Blave Agent。
> 技術細節（給電腦版內建 agent 讀）：[`references/sinopac-broker.md`](../references/sinopac-broker.md)

## 能做什麼

| 功能 | 說明 |
|---|---|
| 回測資料 | 用永豐的 1 分 K（2020-03-02 起）做台股／ETF 回測：1m、5m、15m、30m、60m、日 K，可還原除權息 |
| 自動下單 | 「自動下單」頁的策略可以路由到永豐，對帳器自動用整股＋盤中零股下單 |
| 帳戶頁 | 權益（TWD）、持股、交割戶餘額會顯示在電腦版 |
| 安全機制 | 只賣機器人自己買的股數（不動你原本的持股）、買單前檢查交割款、價格保護、休市不送單、HALT 緊急停止 |

**不支援：** 期貨／選擇權（台指期請用群益或統一）、融資融券、放空。

## 架構（一張圖看懂）

```
策略（strategies/<name>/strategy.py）
  ├─ 回測：lib/runner.py ← fetch_data() ← lib/sinopac_data.fetch_sinopac_kbars（永豐 1 分 K → 快取 → 重組 K 棒）
  └─ 實盤 tick：寫 state.json（部位訊號）
            ↓
電腦版對帳器 manager/reconciler.py → lib/portfolio.reconcile（金額 → 目標部位，self_ledger 帳本）
            ↓（venue 自動接線 lib/venue_wiring 的「現貨」路徑）
lib/order_sinopac.py 現貨層：整股 IOC 限價 ＋ 盤中零股 ROD 限價 → 永豐 Shioaji
lib/account_sinopac.py：帳戶快照（權益、持股）→ 電腦版自動下單頁
lib/sinopac_session.py：每個程序只登入一次（永豐每日登入上限 1,000 次）
```

## 一次性設定

### 1. 申請金鑰與憑證

1. 到永豐 [API 管理頁](https://www.sinotrade.com.tw/newweb/PythonAPIKey/) 新增 API Key：勾選「行情/資料」「帳務」「交易」「正式環境」，建議設定 IP 限制。Secret Key 只會顯示一次。
2. 同一頁「下載憑證」取得 `Sinopac.pfx`（實盤才需要；密碼預設是身分證字號）。
3. 到永豐「簽署中心」簽署 API 相關條款。

### 2. 把本 fork 的檔案部署到電腦版 workspace

電腦版的 workspace 在 `~/Blave/workspace`。在本 repo（`custom` branch）執行：

```bash
python3 tools/sinopac_deploy.py
```

先看預覽（會新增／取代哪些檔），確認後：

```bash
python3 tools/sinopac_deploy.py --apply
```

- 被取代的檔案會先備份到 `~/Blave/workspace/.official-backup/sinopac-deploy-<時間>/`。
- 版本（VERSION）不一致、或對帳正在進行中時會拒絕。
- 部署後請**結束並重新開啟 Blave 電腦版**，讓對帳程式載入新程式碼。

### 3. shioaji（永豐的 Python SDK）

**本 fork 的電腦版會自動安裝**：shioaji 是引擎的選用套件組 `sinopac`（`shell/main.js` 的 `OPTIONAL_DEPS`），
從本 repo 執行（`cd shell && npm start`）或用本 repo build 的 app 一開啟，就會在背景裝進 `~/Blave/venv`（約 35 MB）。
裝不起來不會擋住聊天，下次開 app 會再試。

只有在用**官方原版** app（沒有這一組）時才需要手動安裝：

```bash
~/Blave/venv/bin/python -m pip install shioaji==1.7.9
```

### 4. 綁定金鑰

**方式 A：在電腦版的「選擇下單帳戶」框綁（2026-10-26 起）**

自動下單頁 → 連接交易所 → 真實帳戶 → 「台股」群組選 **永豐金證券** → 填 API Key、Secret Key → 連接交易所。

- 送出前，電腦版會用 `lib/account_sinopac.py` 登入永豐**模擬環境**讀一次帳戶，讀得到才寫進 `.env`；
  所以第 2、3 步（部署、安裝 shioaji）要先做完，否則會看到「這一版還不能在這台電腦檢查永豐金證券的金鑰」或登入失敗的原因。
- 這個框只收 API Key 與 Secret Key，寫入後是**模擬模式**；憑證與實盤開關仍由下面的終端機工具處理（方式 B 的 `live on`）。
- 解除綁定在自動下單頁操作，連終端機工具寫過的憑證、實盤開關一起移除。

**方式 B：在終端機親自執行（要連憑證一起設定時）**

```bash
cd ~/Blave/workspace
~/Blave/venv/bin/python manager/sinopac_setup.py bind
```

- 依提示輸入 API Key、Secret Key（不會顯示在畫面上）、憑證路徑與密碼（只做模擬可略過）。
- 寫入 `.env`（權限 600），預設為**模擬模式**（`SINOPAC_LIVE=false`）。
- 這台電腦若已綁定其他交易所，會拒絕綁定：一台電腦只交易一個帳戶，請先在自動下單頁解除綁定。
- 兩種方式可以混用：用框綁了金鑰之後，再跑一次 `bind` 補憑證即可（同名設定會被取代，不會留兩份）。
- 請不要把金鑰貼到聊天視窗；若不小心貼了，請到永豐 API 管理頁重新產生一組。

### 5. 檢查連線與通過永豐 API 測試

```bash
~/Blave/venv/bin/python manager/sinopac_setup.py check      # 登入、帳戶、流量、憑證（實盤）
~/Blave/venv/bin/python manager/sinopac_setup.py api-test   # 永豐規定的模擬環境測試單
```

`api-test` 只在週一至週五 08:00–20:00 可做（18:00 後限台灣 IP），在**模擬環境**送一筆 2890 整股、跌停價（不會成交）的限價買單，確認後撤單。約 5 分鐘後再跑一次 `check`，看到「已簽署 API 條款: True」即可。

## 回測：用永豐分 K

在策略檔頂部 import（**一定要放最上面**，回測引擎的「偷看未來」檢查才會涵蓋 `fetch_data`）：

```python
from lib.sinopac_data import fetch_sinopac_kbars

SYMBOL   = "0050"
MARKET   = "spot"      # 台股現股：只做多
INTERVAL = "60m"
START    = "2021-01-01"
END      = None
FEE      = 0.003       # 單邊(per side)，ETF 0.3%；個股預設 0.5%

def fetch_data(hdrs):
    df = fetch_sinopac_kbars(SYMBOL, INTERVAL, START, END, adjust=True)   # adjust=True：還原除權息
    return _add_indicators(df)
```

完整範例：[`examples/tw_sinopac_ma/strategy.py`](../examples/tw_sinopac_ma/strategy.py)（0050 60 分 K 均線交叉）。複製到 `strategies/<名稱>/strategy.py` 後執行：

```bash
cd ~/Blave/workspace
BLAVE_MODE=backtest ~/Blave/venv/bin/python strategies/<名稱>/strategy.py
```

或直接請電腦版的 agent 幫你回測。

**資料說明：**

- K 棒時間為「開始時間」標記（永豐原始是結束時間：09:01 = 09:00–09:01，已轉換）；分 K 索引是 UTC，日 K 是台北時間午夜；成交量單位是「張」，另附 `Amount`（成交金額 TWD）。
- 只回傳已收完的 K 棒；13:30 收盤集合競價的那根在 13:31 後才算完成。
- 只含整股成交（零股不在永豐 kbars 裡）。
- 本機快取在 `cache/sinopac_kbars/<代號>/<年-月>.parquet`，重跑回測不再抓。預先下載：`python3 -m lib.sinopac_data 0050 5m 2021-01-01`。
- **流量限制**：沒有交易量的帳戶每天行情流量 500 MB、盤中 kbars 最多 270 次查詢；第一次抓長歷史請在收盤後。
- 日 K 策略也可以繼續用 `fetch_twstock_price_adj`（免費、2010 起），永豐資料的優勢是分 K。

## 自動下單

### 策略條件

- 標的是台股上市／上櫃股票或 ETF 代號（`"0050"`、`"2330"`、`"00679B"`）。
- `MARKET = "spot"`（現股）。放空訊號會被當成「空手」。
- Type A（單一標的）與 Type C（多標的權重，例如 0050／00679B 80/20）都支援。
- 金額單位是新台幣（自動下單頁填的金額）。

### 上線步驟

1. 先回測，看清楚跟「單純持有」的比較結果。
2. 在模擬模式下跑一陣子（模擬只會下**整張**：永豐模擬環境不支援零股，金額至少要買得起一張）。
3. 確認沒問題，**你親自**開啟實盤：

   ```bash
   ~/Blave/venv/bin/python manager/sinopac_setup.py live on     # 需要輸入 LIVE 確認
   ```

   切換會**先暫停自動下單**；模擬與實盤是兩本帳，機器人在永豐的帳本會重新開始（模擬期間的部位不會被拿去賣你的真實持股）。

4. 在自動下單頁確認策略金額、按「啟動下單」。
5. 第一筆成交後，到永豐 App 核對「委託／成交」與自動下單頁的交易紀錄。

### 下單規則

| 項目 | 規則 |
|---|---|
| 交易時段 | 09:00–13:30（交易日）。盤後訊號（日 K 策略）會在隔天開盤後的第一輪送出；休市時不送單也不報錯 |
| 整股 | 每 1,000 股一張：限價 IOC；13:25–13:30 改 ROD 參加收盤集合競價 |
| 零股 | 剩下不足 1,000 股：盤中零股限價 ROD（集合競價每 5 秒撮合，09:10 起），約 45 秒未成交即撤單 |
| 價格保護 | 買一／賣一 ±1%（`.env` 的 `SINOPAC_MAX_SLIPPAGE` 可調，例如 `0.005`），依升降單位取價，不超過漲跌停 |
| 現金檢查 | 實盤買單上限 = 交割戶餘額 − 所有未交割款（不分正負都當應付）− 機器人今天已買的金額 − 手續費 − 0.5% 緩衝；不夠買一股就不下單並通知 |
| 你的持股 | `self_ledger`（預設開啟）只賣機器人自己買的股數。Type A 策略第一次啟動時，若帳上已有同一檔，最多「目標金額」的部分會被認為是機器人的 |
| 結果 | 只回報交易所確認的成交；完全沒成交會在下一輪重試；看不到結果的委託（下單回覆遺失且查無此單、盤中撤單沒確認）會自動 **HALT**，請到永豐 App 核對後再按「啟動下單」；收盤（13:32）後撤不掉的剩餘數量視為已到期，不會 HALT |
| 全部平倉 | 只賣機器人自己的部位；休市時會排到開盤後第一輪 |
| 下單方式 | 市價與 TWAP 可用；「限價追價」會自動改用市價 |

### 帳戶頁

- 權益 = 交割戶餘額 ＋ 明天以後到期的交割款 ＋ 持股市值（TWD）。永豐文件沒定義交割款正負號，這裡採券商慣例（負數＝應付），只影響顯示。
- 持股清單包含你自己的持股（只顯示，不會被交易）。
- 帳戶資料每 5 分鐘（盤中）／30 分鐘（盤後）更新一次快照，避免超過永豐每日登入上限；對帳器運作時每輪都會順便更新。

## 日常維運

| 情境 | 做法 |
|---|---|
| Blave 電腦版更新後 | app 會把官方檔換回原版（你的修改備份到 `.official-backup/`）。先把上游新版合併進 `custom`（[docs/fork-workflow.md](fork-workflow.md) §3），再執行 `python3 tools/sinopac_deploy.py --apply`，重開 app |
| 想暫停 | 自動下單頁按「暫停」，或請 agent 執行 HALT |
| 切回模擬 | `manager/sinopac_setup.py live off`（會先暫停；機器人若還有實盤部位會先警告——切回後機器人不再管理那些股票，請先平倉或自行處理） |
| 解除綁定 | `manager/sinopac_setup.py unbind`（帳上持股不受影響） |
| 查價格保護會掛多少 | `manager/sinopac_setup.py quote 0050` |
| 查發生了什麼 | `state/audit.jsonl`（每筆委託嘗試與結果）、`manager/orders.jsonl`（成交紀錄） |

## 已知限制

- 電腦版的綁定框只收 API Key 與 Secret Key（模擬模式）；憑證與實盤開關要用終端機工具。雲端主機不支援永豐（框裡的雲端視角不會列出它）。
- 永豐金的選項、綁定路徑、shioaji 自動安裝、模擬／真錢記號都在 app 本體（`shell/`、`runtime/`）裡，`tools/sinopac_deploy.py` 裝不到：要在電腦版看到它們，必須從本 repo 執行 app（`cd shell && npm start`）或自行 build。
- 畫面上的模擬／真錢照 `.env` 的 `SINOPAC_LIVE` 判斷（只有 `true` 是真錢），與下單程式同一條規則；永豐模擬環境在頂列寫「永豐金證券（模擬）」。
- 「限價追價」對永豐不適用（沒有追價用的限價單介面，會改以市價送出），設定分頁的下單方式不列這一項。
- 實盤的 K 棒排程器（`manager/wait_for_bar.py`）只對 `fetch_twstock_price*` 日 K 認得台股行事曆：用永豐分 K（或日 K）的策略實盤時，收盤後、週末、假日可能收到「K 棒沒到位」通知（上游對台股分 K 的既有限制）。日 K 策略建議訊號照用 `fetch_twstock_price_adj`，下單一樣走永豐。
- 憑證、密碼、金鑰只存在本機 `.env`；工具不會顯示，也不會寫進任何紀錄。
- 永豐模擬環境不支援零股；模擬成交方式由永豐決定，不代表實盤成交價。
- 本 fork 的修改沒有經過上游 Blave 的實盤驗證，請先用小金額試行。

## 測試

本功能的離線測試（假的 shioaji，不連網）：

```bash
.venv/bin/python tests/check_sinopac_spot_layer.py   # 下單層
.venv/bin/python tests/check_sinopac_account.py      # 帳戶快照與登入
.venv/bin/python tests/check_sinopac_data.py         # 歷史 K 棒
.venv/bin/python tests/check_sinopac_wiring.py       # 對帳 → 下單 → 全部平倉 端到端
```
