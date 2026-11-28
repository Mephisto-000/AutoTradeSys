# 修改聲明（Modifications）

> 本文件列出 `Mephisto-000/AutoTradeSys` 相對於上游 `Blave-TW/blave-agent` 的修改（Apache-2.0 §4(b)）。
>
> - 建立日期：2026-10-29（原本是 README 的「修改聲明」一節，移到這裡避免 README 過長）
> - Fork 維護流程：[`docs/fork-workflow.md`](fork-workflow.md)

---

本 fork 相對於上游有以下修改，所有修改過的檔案皆已在檔案開頭註明：

- 2026-10-25：從上游 `main` 建立 fork（upstream commit: `c355089a`）
- 2026-10-25：新增本 fork 說明區塊與 [`docs/fork-workflow.md`](fork-workflow.md)（fork 維護流程）
- 2026-10-25：移除上游 README 的 Blave 品牌與產品介紹（logo、下載連結、示範影片、功能介紹、雲端方案等）；
  保留授權與政策段落，以及上游測試依賴的語言切換列與「Updating an existing workspace」一節
- 2026-10-25：新增永豐金證券（Shioaji）台股回測與自動下單 — 使用說明見 [`docs/sinopac.md`](sinopac.md)
  - 新增：`lib/sinopac_session.py`、`lib/account_sinopac.py`、`lib/sinopac_data.py`、`manager/sinopac_setup.py`、
    `tools/sinopac_deploy.py`、`examples/tw_sinopac_ma/`、`docs/sinopac.md`、`tests/check_sinopac_*.py`、`tests/sinopac_fake.py`
  - 修改（檔頭已註明）：`lib/order_sinopac.py`、`lib/venue_traits.py`（與 `runtime/venue_traits.py` 相同）、`lib/portfolio.py`、
    `lib/execute.py`、`runtime/agent_turn.py`、`shell/renderer/trade.js`、`references/sinopac-broker.md`、`references/lib.md`、
    `examples/README.md`，以及配合的既有測試（`tests/check_venue_traits.py`、`check_restart_stop_order_gate.py`、
    `check_capital_flatten_identity.py`、`check_position_detail.py`、`check_state_read_retry.py`、`check_blave_data_need.py`）
- 2026-10-26：電腦版「選擇下單帳戶」框的「台股」群組新增永豐金證券（API Key + Secret Key，模擬模式；憑證與實盤仍走終端機工具）
  - 修改（檔頭已註明）：`shell/renderer/trade.js`、`shell/cloudcmd.js`、`shell/daemon.js`、`shell/main.js`、
    `shell/i18n/en.po`、`shell/i18n/zh.po`（產生 `shell/renderer/strings.js`）、`runtime/command_listener.py`、`runtime/local_daemon.py`，
    以及配合的既有測試（`tests/check_shell_connect_venues.js`、`check_shell_trade.js`、`check_shell_binance_link.js`、
    `check_local_real_key_gate.py`、`check_desktop_venue_env.py`）
- 2026-10-26：永豐金畫面修正與 shioaji 自動安裝 — 資產分頁價值改 TWD、「現股／交割戶」標籤；永豐模擬環境標「模擬」不標「真錢」
  （頂列寫「永豐金證券（模擬）」，判斷同下單程式的 `SINOPAC_LIVE`）；下單方式不列限價追價並加說明；選單列的永豐名稱；
  shioaji 加進引擎的選用套件組 `sinopac`
  - 新增：`tests/check_sinopac_shell.js`、`tests/check_sinopac_reporter.py`
  - 修改（檔頭已註明）：`shell/renderer/trade.js`、`shell/renderer/portfolio.js`、`shell/traytext.js`、`shell/main.js`、
    `shell/i18n/en.po`、`shell/i18n/zh.po`（產生 `shell/renderer/strings.js`）、`runtime/portfolio_reporter.py`，
    以及配合的既有測試（`tests/check_shell_engine_setup.js`、`check_usstock_daily.py`）
- 2026-10-27：同步上游 `main` 至 `4cc0ed75`（電腦版 0.1.33）。上游讓排程報告回合完全不能執行 shell，
  2026-10-25 在 `runtime/agent_turn.py` 加的 `sinopac_setup` 攔截已被涵蓋，該檔還原為上游版本（不再列為修改過的檔案）
  - 注意：此次同步暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 0.1.33（VERSION `2026-10-26-e`），
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-10-31：同步上游 `main` 至 `c255299f`（電腦版 0.1.36）
  - 修改（檔頭已註明）：`shell/main.js` 的 `tradePaperOnly`（上游新的更新確認框）把永豐模擬環境算成模擬，以及配合的 `tests/check_sinopac_shell.js`
  - 上游的 `lib/venue_wiring._placing` 也會停放永豐查不到結果的單（原本只 HALT），恢復下單後不再重送；程式不改，
    [`docs/sinopac.md`](sinopac.md) 與 `references/sinopac-broker.md` 補上解除方式
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-10-31-a`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-10-31：再次同步上游 `main` 至 `e9b23e96`（電腦版 0.1.38）
  - 修改（檔頭已註明）：`lib/order_sinopac.py` 的 `cancel_spot_order` 走下單閘門（上游新增回合級下單鎖：對話分頁同時下單時，
    撤單也要排隊），以及配合的 `tests/check_sinopac_spot_layer.py`
  - 上游把 certifi 改成直接釘版：`shell/main.js` 的 `WORKSPACE_DEPS` 兩邊都留，`WORKSPACE_LOCK_FOR` 改用「上游的鎖 + fork 的清單」重算，
    五個平台 pip dry-run 重驗解出同一組；`tests/check_usstock_daily.py` 的數量跟著改成 19 個
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-10-31-b`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-01：同步上游 `main` 至 `189fd758`（電腦版 0.1.40）
  - 修改（檔頭已註明）：`shell/redact.js` 的 `envSecretValues`（上游新增的手機對話上傳前遮蔽）多認 `sinopac_ca_passwd`、`sinopac_person_id`，
    以及配合的 `tests/check_sinopac_shell.js`
  - `shell/renderer/portfolio.js` 的 `#po-live` 記號改用上游的 `trCfPaperOnly()`（fork 先前已讓它把永豐模擬環境算成模擬），行為不變
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-11-01-b`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-03：同步上游 `main` 至 `424a352f`（電腦版 0.1.44）
  - `shell/renderer/trade.js`：上游把 `envMoney` 簡化成只認 Blave 模擬帳戶，保留 fork 版（永豐模擬環境也算模擬），上游新增的
    `envCloudGated`、`envInputGate` 照收
  - `README.md`：上游只改了 fork 已移除段落裡的下載連結，保留 fork 版
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-11-03-c`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-04：同步上游 `main` 至 `4bf109cb`（電腦版 0.1.44，runtime 1.1.155），沒有文字衝突
  - 修改（檔頭已註明）：`runtime/agent_turn.py` 的 `_VENUE_NAMES`（上游新增「回覆裡交易所寫名稱、不寫 id」）補上永豐金證券，
    以及配合的 `tests/check_sinopac_reporter.py`
  - 上游的啟動下單框把模擬與真錢的說明併成同一句，fork 的「永豐模擬環境標模擬」判斷不受影響
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-11-04-c`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-07：同步上游 `main` 至 `e36501eb`（電腦版 0.1.47，runtime 1.1.158）
  - `shell/main.js`、`shell/renderer/trade.js`、`shell/traytext.js`：上游新增的選單列狀態「登入停下」與 fork 的永豐名稱兩邊都留
  - 修改（檔頭已註明）：`shell/renderer/trade.js` 的 `trUbMark`（上游新增的「平倉後解除綁定」框）把永豐模擬環境標成模擬，
    以及配合的 `tests/check_sinopac_shell.js`
  - 上游的平倉後解除綁定對永豐實測可用：盤中只賣 Blave 的股數、重讀歸零才刪金鑰；休市時不賣、解除停住、金鑰保留，
    平倉延到開盤後第一輪（`tests/check_sinopac_wiring.py` 釘住）
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-11-06-b`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-10：同步上游 `main` 至 `f22c182e`（電腦版 0.1.51，runtime 1.1.161）
  - 上游開放群益本機（`CAPL_LOCAL_ON`）：`shell/renderer/trade.js` 連接框「台股」組依序列統一、群益、永豐金，
    `lib/portfolio.py` 檔頭與上游新增的 import 兩邊都留；配合的測試（`check_shell_connect_venues.js`、`check_shell_trade.js`、
    `check_venue_traits.py`）收上游的新字並保留永豐那一項
  - 上游新增「解除綁定就清這一家的帳本」：永豐一樣適用（只清 Blave 的帳本，不賣股票，留在帳戶裡的算用戶自己的），程式不改
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 VERSION `2026-11-09-c`，
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-12：同步上游 `main` 至 `10841b61`（電腦版 0.1.52），沒有文字衝突
  - 上游只改了策略庫的一鍵購買框（用 Blave 帳號付款，不碰交易所金鑰），永豐的功能不受影響，程式不改
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 0.1.52（VERSION `2026-11-09-c`），
    再執行 `tools/sinopac_deploy.py --apply`
- 2026-11-18：同步上游 `main` 至 `730e7653`（電腦版 0.1.56，runtime 1.1.165）
  - 上游 `c1db277b` 把 venue id `sinopac` 改做永豐**期貨**（開關關著、拿掉零股股票路徑），與本 fork 的永豐股票同名同檔；
    依使用者決定保留 fork 的股票版：`lib/order_sinopac.py`、`lib/venue_traits.py`（與 `runtime/venue_traits.py`）的永豐列
    （不帶上游的 `verified_modes`／`bound_marker`／`cred_env`，避免帳戶讀取與全部平倉跳過永豐股票）、`references/sinopac-broker.md`；
    上游的期貨程式（`lib/sinopac_worker.py`、`lib/sinopac_vault.py`、`lib/sinopac_futures_account.py`）照收但不會啟動
  - 修改（檔頭已註明）：`AGENTS.md` 的 Type B 規則保留「永豐股票 → `lib/order_sinopac.py`」（上游改成「Blave 不下台股單」），
    `tools/sinopac_deploy.py` 的部署清單多帶 `AGENTS.md`（電腦版會把它拷進 workspace）
  - `shell/renderer/trade.js`：上游把連接框改成磚，永豐金的磚接在「台股」組最後（Mac 也列）、步驟 1 權限句用永豐版、
    步驟 2 多一句先接模擬，Passphrase 欄位判斷補上永豐不在 `CX_VENUES` 的情況；`.po` 與 `strings.js` 收上游刪掉的兩個字串
  - 上游 0.1.55 起全部平倉在休市時不再延到開盤（回報「休市中沒有平倉」，開盤後要再按一次），永豐股票跟著上游；
    [`docs/sinopac.md`](sinopac.md)、`references/sinopac-broker.md`、`tests/check_sinopac_wiring.py` 已改成新行為
  - 配合的既有測試：上游只測永豐期貨的 `check_sinopac_futures.py`、`check_sinopac_futures_wiring.py` 在 fork 整支 SKIP；
    `check_venue_traits.py`、`check_capital_flatten_identity.py`、`check_restart_stop_order_gate.py`、`check_halt_freeze.py`、
    `check_state_read_retry.py`、`check_win_replace_retry.py`、`check_shell_connect_venues.js`、`check_shell_trade.js`、
    `check_shell_onboarding.js` 改成驗 fork 的股票版
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 0.1.56（VERSION `2026-11-17-b`），
    再執行 `tools/sinopac_deploy.py --apply`；App 要用本 fork build 的版本（官方 0.1.56 App 內的 `runtime/venue_traits.py`
    把永豐當成未驗證的期貨，帳戶讀取會跳過永豐股票）

- 2026-11-20：同步上游 `main` 至 `1ca4008f`（電腦版 0.1.57，runtime 1.1.166，VERSION `2026-11-19-c`）
  - 上游這版：對帳器卡住偵測（進度戳記 240 秒沒動就重啟，一小時第 3 次先暫停交易）、電腦睡醒後新開倉等策略重算、
    Telegram 改背景送、拿券商密碼的行程不再把 workspace 放在 sys.path（`lib/secret_imports.py`）並擴大 agent 不能改的凍結清單、
    期貨停放紀錄存不進時寫旁檔不重送、Python 小版本變了自動重建 venv、改價 v3 付款框、左下帳戶選單等
  - `lib/order_sinopac.py`：永豐股票單等成交的輪詢每次有回應就更新對帳器的進度戳記（只在對帳器自己的行程）——
    收盤集合競價（13:25 送、等 13:30 撮合再撤單）與 09:10 前的零股合理會等超過 240 秒，不改會被卡住偵測誤殺並暫停交易；
    新測試 `tests/check_sinopac_hang_progress.py`
  - `runtime/secret_code.py`：凍結清單補上 fork 的 `lib/account_sinopac.py`、`lib/sinopac_session.py`（永豐下單會載入、處理 CA 密碼）
  - `shell/requirements.txt`（上游新增的依賴鏡像）補 `shioaji==1.7.9`，與 `shell/main.js` 的清單一致；`shell/main.js` 衝突照上游新寫法、
    保留永豐 SDK 下載量；上游只測永豐期貨的 `tests/check_tw_park_save_refused.py` 永豐那輪在 fork SKIP
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 0.1.57
    （workspace VERSION `2026-11-19-c`），再執行 `tools/sinopac_deploy.py --apply`；App 要用本 fork build 的版本
    （`runtime/` 隨 App 出貨，凍結清單與永豐的交易所設定都在裡面）

- 2026-11-24：同步上游 `main` 至 `5b0a87db`（電腦版 0.1.58、0.1.59，runtime 1.1.169，VERSION `2026-11-22-b`）
  - 上游這版：永豐**期貨**本機／雲端開通流程（`shell/renderer/sinopac.js`、`shell/sinopac_local.js`、`runtime/sinopac_service.py` 等，
    外殼旗標 `SINOPAC_LOCAL_ON` 關著、runtime 另看 venue_traits 期貨閘門）、下單標的在交易所不存在時擋下（`symbol_unavailable`，
    只查六家加密貨幣，永豐不受影響）、部分減倉結果不明不重送、billing 改 Agent 方案、寬版版面與 README 標語等
  - `runtime/command_listener.py`：上游讓 credentials 裡任何 `sinopac_*` 行都過期貨的 `sinopac_service.bind_gate`，
    fork 的永豐股票（連接框送的 `SINOPAC_API_KEY` + `SINOPAC_SECRET_KEY` 一對）會被拒；新增 `_fork_sinopac_stock_bind`，
    只在這台電腦、剛好那一對、不是 `vault:` 哨兵也不是期貨流程暫存的寫入才跳過，照舊跑 `_local_real_key_gate`；
    新測試 `tests/check_sinopac_bind_gate.py`
  - `shell/renderer/trade.js`：上游期貨框有三處沒看旗標就攔下 `sinopac`（按「連接」直接 return、不檢查金鑰空白、
    解除框說會刪憑證檔），改成旗標開才走期貨；台股組的永豐金磚在上游旗標打開時不重複列
  - `shell/daemon.js`：`SINOPAC_ENV` 合成上游期貨五行加 fork 的 `SINOPAC_LIVE`、`SINOPAC_BOUND_TS` 共七行（解除綁定都拿得掉）；
    `runtime/local_daemon.py` 照舊永遠開 SINOPAC；`README.md`、`references/sinopac-broker.md` 保留 fork 的股票版
  - 測試：上游新測試 `tests/check_shell_sinopac_local.js` ⓪ ⑤ 配合 fork（現股的解除名單、幣別、顯示名不看旗標，`SINOPAC_ENV` 七行）；
    `tests/check_venue_traits.py` 的永豐自有檔加上游的期貨檔；`.gitleaksignore` 補上游 0.1.59 行號移動後的 i18n key 誤判
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 0.1.59
    （workspace VERSION `2026-11-22-b`），再執行 `tools/sinopac_deploy.py --apply`；App 要用本 fork build 的版本
    （上面 runtime 與外殼的修正都隨 App 出貨，官方 App 0.1.58 起綁不了永豐股票）

- 2026-11-28：同步上游 `main` 至 `8812ca21`（電腦版 0.1.60–0.1.64，runtime 1.1.176，VERSION `2026-11-28`）
  - 上游這版：**永豐期貨正式開放**（0.1.61：runtime／lib 期貨閘門打開、外殼旗標 `SINOPAC_LOCAL_ON` 打開、期貨帳戶讀取器改名
    `lib/account_sinopac.py`、標籤改「永豐期貨」、存檔時擋非台指期、換金鑰、斷線重登、更新後重啟 worker）；另有參數掃描高原
    延伸、樣本外驗證時間上限、Type C 報酬下限、台股全市場寬表 `fetch_twstock_wide`、台股日線 CDN 落後時向 Blave 補尾巴、
    策略版本導讀、寬螢幕版面、啟動下單框等永豐回報、策略庫上架以來、資料金鑰自動寫入、憑證檔 Bash 守門等
  - 與 fork 的永豐金**現股**撞名（同一個 `sinopac` id），照 2026-11-18 的決定保留股票版、上游期貨維持關閉：
    `lib/venue_traits.py`／`runtime/venue_traits.py` 保留現股那一列並寫 `_SINOPAC_MODES = ()`（上游 `sinopac_connect`
    以文字讀這行）；`lib/account_sinopac.py`、`lib/order_sinopac.py`、`README.md`、`references/sinopac-broker.md` 保留 fork 版；
    `AGENTS.md` 索引維持「SinoPac (永豐金)」；`shell/main.js`、`shell/renderer/trade.js` 的 `SINOPAC_LOCAL_ON` 維持 `false`
  - `shell/renderer/trade.js`：上游新的 `trTwFutVenue` 把 `sinopac` 一律當台指期券商，只跑永豐股票時「啟動下單」會被停用、
    帳戶區變口數區；改成旗標開才算永豐（`trCloseDeferred` 標題、帳戶讀取失敗那行同理）。Mac 的台股組改成永豐金磚在上、
    「台灣期貨要 Windows」那行（含上游新的〔改用雲端主機〕）接在磚下，熱區不蓋進磚
  - 字串：上游 0.1.60 把 `tr.acct.cash` 當一般錢包「現金」，與 fork 的「交割戶」撞 key；fork 的改用 `tr.acct.settle`，
    只在永豐金那幾列使用
  - `runtime/secret_code.py` 凍結清單合併（上游已列 `lib/account_sinopac.py`，fork 補 `lib/sinopac_session.py`）；
    `references/lib.md` 的 fork 段改寫上游期貨讀取器改名的說明
  - 測試：上游假設永豐期貨已開的測試配合 fork 調整（`check_shell_trade.js`、`check_shell_txf_close_or_fail.js`、
    `check_exec_global.py`、`check_venue_traits.py`、`check_shell_sinopac_view.js`、`check_shell_connect_venues.js`、
    `check_capital_flatten_identity.py`）；期貨 worker 的 `check_sinopac_local.py` 整支 SKIP；`check_sinopac_shell.js` 替身框補 `delCtx`
  - 注意：此次同步尚未 build 成 App，也暫不部署到電腦版（`~/Blave/workspace`）。之後要部署需先等 app 更新到 0.1.64
    （workspace VERSION `2026-11-28`），再執行 `tools/sinopac_deploy.py --apply`；App 要用本 fork build 的版本
    （官方 App 0.1.61 起把 `sinopac` 當永豐期貨，`lib/account_sinopac.py` 也會換成期貨讀取器）

詳細差異請以 `git log` 與 `git diff upstream/main` 為準。
