<!-- ===== AutoTradeSys fork 說明（上游 README 只保留授權政策與測試依賴的段落，見文末）===== -->

# AutoTradeSys

個人量化交易工作區，基於 [Blave Agent](https://github.com/Blave-TW/blave-agent) 修改而成。

> **說明（Attribution）**
> 本專案 fork 自 [Blave-TW/blave-agent](https://github.com/Blave-TW/blave-agent)，
> 原始著作權屬於吾集科技股份有限公司（WuChi Technology Company Limited），
> 依 [Apache License 2.0](./LICENSE) 授權。原始的 [LICENSE](./LICENSE) 與 [NOTICE](./NOTICE) 均保留於本 repo。
>
> 本專案**並非** Blave 官方版本，也未獲得 Blave 或吾集科技的背書或支援。
> 「Blave」名稱與 logo 為 Blave 的商標，本專案僅以「based on Blave Agent」的方式事實性引用。

## 修改聲明（Modifications）

本 fork 相對於上游有以下修改，所有修改過的檔案皆已在檔案開頭註明：

- 2026-10-25：從上游 `main` 建立 fork（upstream commit: `c355089a`）
- 2026-10-25：新增本 fork 說明區塊與 [`docs/fork-workflow.md`](docs/fork-workflow.md)（fork 維護流程）
- 2026-10-25：移除上游 README 的 Blave 品牌與產品介紹（logo、下載連結、示範影片、功能介紹、雲端方案等）；
  保留授權與政策段落，以及上游測試依賴的語言切換列與「Updating an existing workspace」一節
- 2026-10-25：新增永豐金證券（Shioaji）台股回測與自動下單 — 使用說明見 [`docs/sinopac.md`](docs/sinopac.md)
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

詳細差異請以 `git log` 與 `git diff upstream/main` 為準。

## 免責聲明（Disclaimer）

本專案依「現狀（AS IS）」提供，不附帶任何明示或默示的保證。
量化交易有虧損風險，任何策略、回測結果或程式輸出都不構成投資建議，使用者需自行承擔交易結果。

---

<!-- ===== 以下為上游 Blave Agent README 的原文段落（授權政策與測試依賴，依原文保留）===== -->

以下為上游 Blave Agent README 的原文段落，依原文保留：

- `License`、`Code Signing Policy`：授權、商標與開源政策。Code Signing Policy 描述的是上游官方版本的簽章流程，不適用於本 fork。
- 語言切換列、`Updating an existing workspace`：上游測試（`tests/check_readme_translations.py`、`tests/check_cloud_handoff_reference.py`）會檢查這兩處。

**English** | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md) | [Português](README.pt.md) | [Tiếng Việt](README.vi.md)

## License

Apache-2.0. The strategies you write are yours. "Blave" is a trademark: rename your fork.

Claude Code and Codex are products of their respective owners. Blave Agent is not affiliated with or endorsed by them.

## Code Signing Policy

The Windows build is not code-signed yet: we have applied to the [SignPath Foundation](https://signpath.org) open-source program, and until it is approved the Windows installer is unsigned. Once approved: free code signing on Windows provided by [SignPath.io](https://signpath.io), certificate by SignPath Foundation. Releases are built by the public GitHub Actions workflow in this repository from a tagged commit; each signing request is approved by the repository owner. Roles: Authors and Reviewers — the maintainers with write access; Approver — the repository owner. This program will not transfer any information to third parties except as described in the [privacy policy](https://blave.org/disclaimer/en/privacy_policy). The macOS build is signed and notarized with Blave's own Apple identity.

---

## For maintainers and existing machines

### Updating an existing workspace

<details>
<summary>Update steps for an existing workspace</summary>

This section is an operating contract: `references/updating.md` sends agents here, and the desktop app copies the same file list. Keep the heading and the list intact.

Tell your agent:

> Clone https://github.com/Blave-TW/blave-agent to /tmp/oc-config and use it as **reference** to update this machine's live workspace — `$BLAVE_AGENT_HOME/workspace`, i.e. the workspace you are running in (`/root/.openclaw/workspace` on old BlaveClaw machines, `/opt/blave-agent/workspace` on Blave Agent machines; resolution per `references/deployment.md`). For each file below, compare the repo version with the local version. Nothing is merged: an official file (its exact path is in the clone) that differs is replaced wholesale by the clone's version, after a backup of the local copy into `.official-backup/<old VERSION>-<UTC time>/` (relative path kept; older backups never overwritten). If the local copy matches no past official version of that file (`git hash-object` vs `git log --raw` on a `--filter=blob:none` clone), it was changed on this machine: ask the user before replacing it; if they keep it, leave it and do not copy `VERSION`. Replace atomically (`cp` to a temp name, then `mv`). A file whose path is not in the clone is never touched.
>
> - `AGENTS.md`, `CLAUDE.md` — replace wholesale (these are config, not user-edited)
> - `references/` — replace each differing file wholesale (with the `.official-backup/` copy); copy in any that are missing
> - `strategies/TEMPLATE_A.py`, `strategies/TEMPLATE_C.py` — replace wholesale
> - `lib/` — add any canonical files that are missing locally (`venue_errors.py` always); every canonical file that differs — the backtest-chain files (`runner.py`, `param_scan.py`, `walk_forward.py`, `validation.py`, `analysis.py`), `data.py`, the official broker libs and the rest — is replaced wholesale (with the `.official-backup/` copy), never merged. For `lib/order_*.py` / `lib/account_*.py`, the name alone doesn't tell you if it's user-created: if that exact filename exists in the reference clone (e.g. `order_bingx.py`, `order_sinopac.py`, `account_bingx.py`, `account_TEMPLATE.py`), it is official and replaced like the rest; **never touch** one that does not exist in the reference clone — that's the user's own exchange integration
> - `manager/` — replace wholesale (user edits live in `portfolio_config.json`, not in the scripts)
> - `examples/` — replace wholesale
> - `allocators/` — replace wholesale (only files that exist in the clone; the user's own allocators are never touched)
> - `VERSION` — copy verbatim, always last and only if every step above succeeded (it declares the workspace up to date; drives the web "update available" indicator)
>
> When done, remove /tmp/oc-config.

</details>
