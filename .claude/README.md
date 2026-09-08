# 為什麼 hook 設定放在這裡，不放在 `~/.claude/settings.json`

2026-09-08 01:02，這三個 hook 被寫進擁有者的 `~/.claude/settings.json`。
官方文件對那個位置的說明只有一行：`You, in every project on this machine`。

結果是她那一晚安排的工作被持續 deny，九個小時。她必須自己動手改
`~/.forseti/goal.json`，把不相干的路徑加進 scope，才能讓當時的 session
繼續工作。完整經過與根因在 `docs/工程規格書.md` §9.2。

三層設定的作用範圍：

| 層級 | 檔案 | 誰受影響 |
|---|---|---|
| User | `~/.claude/settings.json` | 這台機器上的每一個專案 |
| Shared project | `.claude/settings.json` | 只有含這個檔案的資料夾 |
| Project local | `.claude/settings.local.json` | 只有你，只有這個專案 |

hooks 屬於 Shared project 那一層，所以設定在這裡。

## 兩道保險，不是一道

設定檔的位置是第一道。第二道在程式碼裡：兩個 hook 都會從自己的檔案位置
算出所屬的 repo 根目錄，`cwd` 不在底下就立刻 `exit 0`，連狀態檔都不建。

第二道存在的理由是，第一道依賴我對設定作用範圍的理解，而上次出事正是
因為那個理解是錯的。程式碼層的邊界不看設定、不看環境變數、不可設定關閉。
`test/hooks.e2e.test.mjs` 的 AT-HOOK-B1 到 B4 守著它，B4 專門檢查有沒有
人偷偷加繞過開關。

## 這些 hook 現在會做什麼

只說話，不擋。每一個攔截點都要先問 `intervention.js` 的 `canIntervene`，
而它對這些情況只放行安靜標註。唯一剩下的 `exit(2)` 在撞車偵測裡，
前面有一次明確的閘門呼叫，而閘門會拒絕，因為可能覆蓋是機率，不是
它要求的硬前提未知。

## 沒有驗證過的部分

Claude Code 是否真的載入這個檔案並執行這些 hook，這裡沒有驗證過。
驗證需要在這個目錄底下開一個 session，而寫這段的 session 的工作目錄
不是這裡。已經驗證的是：JSON 合法、命令字串照抄可以執行、邊界在
repo 外確實不動作。
