# NORTH_STAR

最後更新 2026-09-08。內容取自 `soul.md` 第二節，那份只增不改。

---

## 北極星

> 讓 AI 的工作狀態變成可觀測、可驗證、可控制、可復原。
> 使用者不該變成 AI 的保姆、QA 部門、或手動復原機制。

出處：她的 ChatGPT 對話第六十節、AI-First 工程書 1.1 節。

**這不是北極星：** 「聚焦完成 Forseti」。那是 `goal.json` 裡的 scope 定義，
是手段。2026-09-08 我把它當成北極星，她問「你真的知道我的北極星？？」

---

## 三句不變量

> AI 可以死，但 Project State 不能死。
> AI 可以換，但 Reality 不能換。
> Session 可以 Fork，但 Goal、Decision、Evidence 與 Verified State 必須完整延續。

工程書的英文版：

> AI can be wrong, but a wrong claim must never silently become project truth.
> A session can die, but the project state, causal history, authority boundaries,
> and recoverable execution state must survive.

---

## 四個要守住的連續性

| 連續性 | 問題 | 失守的後果 |
|---|---|---|
| Truth | 環境裡實際是什麼 | 假完成、發明的檔案、過期假設變成事實 |
| Intent | 我們到底要做什麼、為什麼 | 接手的人做著另一個專案卻以為是同一個 |
| Authority | 誰有權把提案變成外部效果 | 未授權的部署、花錢、刪除、對外發訊 |
| State | 什麼必須在 session 死掉後還活著 | 工作進度丟失、無法接續、重複工作 |

---

## 成功條件

Engine 要能對每個事件回答十四個問題（ChatGPT 對話第六十一節）。
現況見 `PHASE_STATUS.md`。

**最終驗收：** 殺掉一個 session，後繼者能從 checkpoint 恢復，
正確回答目標、已接受的決策、未解決的未知、最後已知良好狀態。

---

## 非目標

- 不取代 Claude Code、Codex、OpenClaw、IDE、CI/CD、版本控制
- 不把 LLM 的信心當成真實
- 不要求每個動作都經人類批准
- 不把完整歷史對話倒進每個後繼 session
- 不把 Git 當成 runtime 真實的唯一來源
- 不是 MCP server、不是 Skill、不是純桌面應用、不是 LLM gateway

---

## 預設姿態

> OBSERVE 99%, INTERRUPT 1%. A noisy Forseti becomes another failure source.

2026-09-08 有過一次反例：一個只寫著單一專案路徑的 scope 對整台機器
每個目錄生效，擋掉她九小時的工作。所以任何會擋人的程式碼路徑，
上方十五行內必須看得到介入閘門的呼叫，已有測試守著。
