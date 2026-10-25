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

# 上游要求的 gitleaks 秘密掃描 hook（需在本機實際執行）
uv tool install pre-commit          # 或 pipx install pre-commit
pre-commit install
```

確認：

```bash
git remote -v                       # 應看到 origin 與 upstream
git branch -vv                      # custom 應追蹤 origin/custom
git config --get rerere.enabled     # 應為 true
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

4. `README.md` 開頭的 fork 說明區塊是唯一刻意修改的上游檔案；若上游改動 README 開頭而衝突，保留 fork 說明區塊，其餘採用上游版本。

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
- [ ] 已執行 `pre-commit install`，commit 時 gitleaks 有跑過
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

**Q：出現 `.git/index.lock: File exists`？**
先確認沒有其他 git 程式在執行，再刪除殘留的 lock 檔：`rm .git/index.lock`。

**Q：授權與商標要注意什麼？**
保留 `LICENSE`、`NOTICE`；不使用「Blave」名稱或 logo 作為本專案品牌；可事實性寫「based on Blave Agent」。
