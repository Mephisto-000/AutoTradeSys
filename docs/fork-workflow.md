# Fork 維護流程（Fork Workflow）

> 本文件說明 `Mephisto-000/AutoTradeSys` 如何與上游 `Blave-TW/blave-agent` 保持同步、
> 處理版本衝突，以及如何把修改回饋給上游。
>
> - 建立日期：2026-10-25
> - Fork 起點（upstream commit）：`c355089a`

---

## 1. Remote 與 Branch 設計

| 名稱 | 指向 | 用途 |
|---|---|---|
| `origin` | `https://github.com/Mephisto-000/AutoTradeSys.git` | 自己的 fork，可 push |
| `upstream` | `https://github.com/Blave-TW/blave-agent.git` | 原作者 repo，只 fetch，不 push |

| Branch | 規則 |
|---|---|
| `main` | **只做 fast-forward 跟上游同步，永遠不直接修改。** 內容應與 `upstream/main` 完全相同。 |
| `custom` | 自己的修改都在這裡（README fork 說明、本文件、客製化程式）。日常工作 branch，建議設為 GitHub 預設 branch。 |
| `feat/<主題>` | 要回饋上游時，從 `upstream/main` 臨時開出；PR 合併後刪除。 |

```
upstream/main ──●──●──●──●──────●──●   （原作者）
                 \                \
main  ───────────●──●──●──●───────●──●   （只 fast-forward）
                       \            \
custom ─────────────────●──●──●──●──M──●   （M = merge main）
```

---

## 2. 一次性設定（新電腦或重新 clone 時）

```bash
git clone https://github.com/Mephisto-000/AutoTradeSys.git
cd AutoTradeSys
git remote add upstream https://github.com/Blave-TW/blave-agent.git
git config rerere.enabled true      # 記住解過的衝突，同樣的衝突下次自動套用
git switch custom                   # 切到日常工作 branch
```

### 秘密掃描（gitleaks 原生 hook）

上游 README 要求 `pre-commit install`，但上游的 gitleaks hook 要用 Go 從原始碼建置、
必須連 `proxy.golang.org`；本機的 HiNet DNS 會把 `golang.org` 導到過濾頁，建置失敗後
每次 commit 都會被擋。因此改用**原生 git hook 直接呼叫 Homebrew 預編譯的 gitleaks**，
掃描指令與上游 hook 相同（`gitleaks git --pre-commit --staged --redact --verbose`）。

`.git/hooks/` 不進版控，每次重新 clone 都要再裝一次：

```bash
brew install gitleaks
cat > .git/hooks/pre-commit <<'EOF'
#!/bin/sh
# commit 前用 gitleaks 掃 staged 內容（原生 hook，不經 pre-commit 框架、不需 Go）
# 安裝方式見 docs/fork-workflow.md §2；誤報處理見 §6 FAQ

case ",${SKIP:-}," in
  *,gitleaks,*) echo "gitleaks: 依 SKIP 設定跳過掃描" >&2; exit 0 ;;
esac

GITLEAKS=$(command -v gitleaks || true)
for p in /opt/homebrew/bin/gitleaks /usr/local/bin/gitleaks; do
  [ -z "$GITLEAKS" ] && [ -x "$p" ] && GITLEAKS=$p
done

if [ -z "$GITLEAKS" ]; then
  echo "gitleaks: 找不到執行檔，commit 已中止（請先 brew install gitleaks）" >&2
  exit 1
fi

exec "$GITLEAKS" git --pre-commit --staged --redact --verbose --no-banner
EOF
chmod +x .git/hooks/pre-commit
```

- **不要再執行 `pre-commit install`**：它會接管 `.git/hooks/pre-commit`，又回到建置失敗、commit 被擋的狀況。
- 上游 `.pre-commit-config.yaml` 釘選 gitleaks `v8.30.1`；Homebrew 會隨 `brew upgrade` 更新，偶爾用 `gitleaks version` 對照即可。
- hook 會自己找 `/opt/homebrew/bin` 與 `/usr/local/bin`，GUI git 工具（`PATH` 沒有 Homebrew）也能正常掃描。

確認：

```bash
git remote -v                       # 應看到 origin 與 upstream
git branch -vv                      # custom 應追蹤 origin/custom
git config --get rerere.enabled     # 應為 true
git hook run pre-commit             # 應顯示 no leaks found
```

GitHub 網頁設定（一次性）：

- Settings → General → Default branch：改成 `custom`
- About（齒輪）→ Website：清空上游的 `blave.org`，避免被誤認為官方 repo

---

## 3. 情境一：原作者有更新

建議**至少每週同步一次**，上游 commit 頻繁，累積越久衝突越難解。

```bash
# Step 1：更新 main（純跟上游）
git switch main
git fetch upstream
git merge --ff-only upstream/main   # 若失敗，代表 main 被誤改，見 §6 FAQ
git push origin main

# Step 2：把上游更新帶進 custom
git switch custom
git merge main                      # 有衝突 → 見 §4
# 跑相關測試（見 §5 測試）
git push origin custom
```

> **為什麼用 merge 不用 rebase？** `custom` 已經 push 到遠端，rebase 會改寫歷史並需要
> force push；merge 保留完整歷史，方便追蹤每次同步的時間點與衝突處理方式。

> **GitHub 網頁的「Sync fork」按鈕**只同步 `main`，且 `main` 沒有自己的 commit 時才安全。
> 若畫面出現 **「Discard N commits」**，**不要按**，那會刪掉你的 commit。

---

## 4. 情境二：上游更新與自己的修改衝突

```bash
git switch custom
git merge main                      # 出現 CONFLICT
git status                          # 找出 both modified 的檔案
```

衝突區塊格式：

```
<<<<<<< HEAD
自己（custom）的版本
=======
上游（main）的版本
>>>>>>> main
```

| 狀況 | 指令／做法 |
|---|---|
| 兩邊都要保留 | 手動合併內容，刪除 `<<<<<<<`、`=======`、`>>>>>>>` 標記 |
| 整個檔案採用上游版本 | `git checkout --theirs <file>` |
| 整個檔案採用自己的版本 | `git checkout --ours <file>` |
| 解到一半想放棄、回到 merge 前 | `git merge --abort` |

```bash
git add <解完的檔案>
# 跑相關測試，確認通過
git commit                          # 在訊息中補充：哪些檔案衝突、如何取捨
git push origin custom
```

### 降低衝突的原則

1. **策略與資金配置放在 `strategies/`、`allocators/`**：被 `.gitignore` 排除，上游不會動，也不會被 push 到 public repo。
2. **優先新增檔案，少改上游核心**（`lib/`、`runtime/`、`manager/`、`shell/`）。
3. 必須修改上游檔案時，一次只改一小塊，並在檔案開頭加修改註記（Apache-2.0 §4(b)）：

   ```python
   # Modified by Mephisto-000 on YYYY-MM-DD: <修改摘要>
   # Original work: Copyright 2025-2026 WuChi Technology Company Limited
   # Licensed under the Apache License, Version 2.0
   ```

4. `README.md` 已改寫為 fork 專用版本，上游內容只保留下列原文段落（其餘品牌與產品介紹已移除）：

   | 保留段落 | 原因 |
   |---|---|
   | `License`、`Code Signing Policy` | 授權、商標與開源政策 |
   | 語言切換列（`**English** \| [繁體中文](README.zh-TW.md) \| …`） | `tests/check_readme_translations.py` 硬性檢查 |
   | `### Updating an existing workspace` 整節 | `tests/check_cloud_handoff_reference.py` 讀這一節，缺少會 crash |

   上游只要改 README 幾乎都會衝突，處理方式固定：

   ```bash
   git checkout --ours README.md            # 保留 fork 版本
   git diff HEAD...MERGE_HEAD -- README.md  # 看上游這次改了 README 哪些地方
   ```

   上游若改到上表任一段落，把該段手動同步成新原文；其餘改動（產品介紹、下載連結等）一律不帶進來。
   同步完跑一次兩支測試確認通過：

   ```bash
   python3 tests/check_readme_translations.py
   python3 tests/check_cloud_handoff_reference.py
   ```

   `check_readme_translations.py` 會印出 intro、What You Get、Quick Start、Safety 的 drift 警告，
   這是刻意移除這些段落造成的，exit code 仍為 0，可以忽略；出現 `FAIL` 才需要處理。

---

## 5. 情境三：把修改回饋給原作者（Pull Request）

**一定要從 `upstream/main` 開 branch**，不可從 `custom` 開，否則私人修改會一起進 PR。

```bash
git fetch upstream
git switch -c feat/<主題> upstream/main

# 方式 A：在此 branch 重新實作
# 方式 B：從 custom 挑出特定 commit
git cherry-pick <commit-hash>

# 跑相關測試
git push -u origin feat/<主題>
```

到 GitHub 的 `AutoTradeSys` 頁面 → **Contribute → Open pull request**，
目標選 `Blave-TW/blave-agent:main`。

### PR 檢查清單

- [ ] 已讀上游 `AGENTS.md`、`examples/README.md`、`references/lib.md`（上游 README 要求）
- [ ] 已安裝 §2 的 gitleaks 原生 hook，commit 時有跑過（取代上游 README 的 `pre-commit install`，掃描指令相同）
- [ ] 跑過相關測試（`tests/` 一個契約一個檔）
- [ ] 一個 PR 只做一件事；說明修改原因、影響範圍、測試方式
- [ ] diff 中**沒有**策略、`.env`、`manager/*.json`、下單紀錄、API key
- [ ] 回饋上游的檔案**不加** fork 修改註記（`Modified by Mephisto-000`）
- [ ] 了解授權：依 Apache-2.0 §5，提交的 contribution 以 Apache-2.0 授權給上游

PR 合併後：

```bash
git branch -d feat/<主題>
git push origin --delete feat/<主題>
```

下次同步時，該修改會經由 `upstream/main` → `main` → `custom` 自然回來；
`custom` 上若有重複的同一段修改，可在 merge 時以上游版本為準。

---

## 6. FAQ

**Q：`git merge --ff-only upstream/main` 失敗？**
代表 `main` 上有自己的 commit。先把那些 commit 搬到 `custom`（`git switch custom && git cherry-pick <hash>`），
再確認無誤後由本人決定是否將 `main` 重設回 `upstream/main`（此動作會改寫 `main`，需 force push，請謹慎）。

**Q：Fork 是 public，策略會不會外洩？**
上游 `.gitignore` 已排除 `.env`、`strategies/*`（範本除外）、`allocators/*`、`manager/*.json` 等。
**不要用 `git add -f`** 強制加入這些檔案，也不要修改 `.gitignore` 的這些規則。

**Q：commit 被 gitleaks 擋下來？**
先看輸出的 `File`、`Line`、`RuleID` 判斷是不是真的 key（秘密值已遮蔽為 `REDACTED`）。

- 真的是 key：`git restore --staged <file>` 移出 staged，把 key 改放 `.env`。
  這把 key 若曾出現在任何已 push 的 commit（本 repo 是 public），立即到交易所／服務商撤銷並重新產生。
- 誤報：在該行加 `gitleaks:allow` 註解；不方便改該行時，把輸出中的 `Fingerprint` 加進 repo 根目錄的 `.gitleaksignore`。
- 確認是誤報但急著 commit：`SKIP=gitleaks git commit`（或 `git commit --no-verify`，會跳過所有 hook）。

**Q：出現 `.git/index.lock: File exists`？**
先確認沒有其他 git 程式在執行，再刪除殘留的 lock 檔：`rm .git/index.lock`。

**Q：授權與商標要注意什麼？**
保留 `LICENSE`、`NOTICE`；不使用「Blave」名稱或 logo 作為本專案品牌；可事實性寫「based on Blave Agent」。
