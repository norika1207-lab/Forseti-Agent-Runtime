# Forseti 即時施工狀態

最後依證據更新：2026-09-22 13:57 Asia/Taipei

這一頁是 Commander 的 Git 可追蹤狀態，不是 Worker 自述。每次狀態變更都必須能對應到 Git diff、測試輸出、Delivery Receipt 或明確的阻塞證據。

## 安全鎖

**啟用中：禁止啟動、部署、驅動或 Accessibility 測試 Forseti.app。**

原因：使用者回報滑鼠移到桌面程式即造成整台 Mac 長時間轉圈。已觀測到 `forseti-desktop` PID 38762 進入 macOS `U`（不可中斷等待）狀態；`SIGTERM` 與 `SIGKILL` 當時均未能立即回收。這不是完成條件，也不是已定位的根因。

## DAG

| 工作項 | 狀態 | 可做範圍 | 目前證據／阻塞 |
| --- | --- | --- | --- |
| `FOR-P0-001` 桌面卡死隔離與定位 | `VERIFIED_COMPLETE`（限縮範圍） | 僅靜態診斷與離線測試；禁止 UI 操作 | tooltip hover 的事件放大已改用 pointer event 並對相同 dot 去重。獨立離線驗證 `95 passed`，commit `5e78264`。此 Gate 只驗證該 hover 修補；未進行真實桌面驗收，安全鎖仍維持。前端未接 Rust `.forseti` 檔案事件卻每 2 秒呼叫 Python `strands` 的高成本刷新路徑，仍是下一個待隔離項目。 |
| `FOR-P1-001` 持久續作契約 | `VERIFIED_COMPLETE`（限縮範圍） | Ledger / recovery contract / focused tests | Commander 獨立重跑 F05/F07/continuation/recovery suite，結果 `55 passed`；scoped diff check 與 Python compile 也通過。R2 收據逐檔如實標示 Git 狀態，作者 provenance 保留 `UNKNOWN`，不以猜測取代證據。此 Gate 只驗證持久續作政策，未驗證 host transport、桌面或部署。 |
| `FOR-P1-002` Host delivery adapter | `VERIFIED_COMPLETE`（限縮範圍） | 精確目標、原始指令封包、fail-closed | Commander 獨立重跑 controller/adapter 離線 suite，結果 `10 passed`。controller 拒絕舊 polling 參數，且無前景視窗、AppleScript、點擊或 timer loop。這只驗證 packet production，不驗證任何實機 host transport 或桌面 delivery；UI safety lock 仍有效。 |
| `FOR-P2-001` 整合驗收 | `BLOCKED_UI_SAFETY_PLAN_REQUIRED` | 一條完整恢復回路 | 規格要求「刻意批准的 UI safety test plan」才可 VERIFIED_COMPLETE。使用者曾遭遇嚴重 macOS 卡死，安全鎖仍啟用；不得啟動、部署、AX 或整合 UI 測試。 |

完整機器可讀 DAG：`.forseti/commander-state.json`。

## 已驗證的小型修補

`tests/test_f07.py` 新增案例：worker 仍執行時，即使已有舊 ResultReceipt，也必須回 `HOLD_RUNNING`，不得改走 synthesis 或 redispatch。針對 F05/F07/continuation 的 focused suite 已通過 `20 passed`；這只證明該案例，不代表桌面、adapter 或整個 Forseti 完成。

`FOR-P0-001` 的 hover event guard 已由 Commander 獨立重跑：`python3 -m pytest -q tests/test_hover_event_guard.py tests/test_ui_contract.py tests/test_poll_overlap.py`，結果 `95 passed`。它只支持「同一 dot 不再造成 hover 重建風暴」；不支持「桌面 app 已完全安全」的結論。

`FOR-P1-001` 的 Worker receipt 宣稱修改 `ledger.py`、`test_f07.py`、`test_task_continue.py`。Commander 獨立重跑 `python3 -m pytest -q tests/test_f05.py tests/test_f07.py tests/test_task_continue.py tests/test_recovery_contract.py`，結果 `55 passed`，且 scoped `git diff --check` 通過；但實際 allowed-scope 工作樹還可見 `recovery_contract.py`、`test_recovery_contract.py` 與 `test_f05.py`。這些檔案可能是本次工作或既有 dirty change，沒有 provenance 就不能猜。因此先要求 Worker 補正或明確排除，驗證 gate 保持關閉。

R1 收據修正後仍不可採信：其文字稱 `recovery_contract.py`「未觀測為 dirty」，但 Commander 的獨立 `git status --short` 顯示它是 untracked；同一收據還把 `test_task_continue.py` 列為 P1 變更，卻未在 reconciliation 的 observed list 中一致處理。這是 receipt contract drift，不是程式測試失敗。Commander 已重派相同且唯一路徑限制為 receipt 的 R1，要求以完整、互不矛盾的路徑清單修正；沒有修正前不會進入 P1 verifier。

重派的 R1 task 回合後來結束，沒有更新 receipt、沒有可觀測 Git artifact，先前執行中的完整 `pytest` process 也已離開而未留下可驗證的最終輸出。此處不把「session 曾 active」或「process 曾存在」當成功證據。Commander 依停滯規則建立 `FOR-P1-001-R2`：只允許把目前 receipt 改成能逐一路徑對應 `git status` 的可稽核版本；這是最後一次 receipt-only recovery，仍不允許任何產品程式、UI 或部署修改。

R2 已完成。Commander 獨立重跑 `python3 -m pytest -q tests/test_f05.py tests/test_f07.py tests/test_task_continue.py tests/test_recovery_contract.py`，結果 `55 passed`；並以 scoped `git diff --check` 與 `py_compile` 檢查交付檔案。收據的 provenance 無法從 Git 工作樹推得，已明確維持 `UNKNOWN`，而非虛構作者。P1 的驗證範圍只涵蓋持久 decision/ledger 行為，下一張 `FOR-P1-002` 只能開發 fail-closed host adapter 的離線邏輯，絕不解除 UI safety lock。

`FOR-P1-002` 已由 Commander 獨立重跑 `python3 -m pytest -q tests/test_controller_contract.py tests/test_desktop_adapter.py`，結果 `10 passed`。靜態掃描未發現 `frontmost`、`osascript`、`cliclick`、`setInterval` 或 `sleep 10`；controller 也會在執行 adapter 前拒絕 `--interval`、`--idle`、`--once`、`--dry-run`。這是離線 fail-closed 驗證，不是對任一桌面程式注入指令的成功聲明。

## 更新規則

1. Worker 只能提交 `SUBMITTED` 與 Delivery Receipt。
2. Verifier 以獨立測試、diff 與驗收條件決定是否 `VERIFIED_COMPLETE`。
3. 沒有 evidence 的進度一律保持 `STALLED`、`BLOCKED` 或 `UNKNOWN`。
4. 這份頁面與 Work Order 會和 Git commit 一起更新；GitHub 顯示的最後 commit 即是可追溯的最新版本。
