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

詳細差異請以 `git log` 與 `git diff upstream/main` 為準。
