# Forseti 即時施工狀態

最後依證據更新：2026-09-22 13:20 Asia/Taipei

這一頁是 Commander 的 Git 可追蹤狀態，不是 Worker 自述。每次狀態變更都必須能對應到 Git diff、測試輸出、Delivery Receipt 或明確的阻塞證據。

## 安全鎖

**啟用中：禁止啟動、部署、驅動或 Accessibility 測試 Forseti.app。**

原因：使用者回報滑鼠移到桌面程式即造成整台 Mac 長時間轉圈。已觀測到 `forseti-desktop` PID 38762 進入 macOS `U`（不可中斷等待）狀態；`SIGTERM` 與 `SIGKILL` 當時均未能立即回收。這不是完成條件，也不是已定位的根因。

## DAG

| 工作項 | 狀態 | 可做範圍 | 目前證據／阻塞 |
| --- | --- | --- | --- |
| `FOR-P0-001` 桌面卡死隔離與定位 | `VERIFIED_COMPLETE`（限縮範圍） | 僅靜態診斷與離線測試；禁止 UI 操作 | tooltip hover 的事件放大已改用 pointer event 並對相同 dot 去重。獨立離線驗證 `95 passed`，commit `5e78264`。此 Gate 只驗證該 hover 修補；未進行真實桌面驗收，安全鎖仍維持。前端未接 Rust `.forseti` 檔案事件卻每 2 秒呼叫 Python `strands` 的高成本刷新路徑，仍是下一個待隔離項目。 |
| `FOR-P1-001` 持久續作契約 | `RECEIPT_CORRECTION_REQUIRED` | Ledger / recovery contract / focused tests | Worker 已提交 receipt；獨立重跑 focused suite 為 `55 passed`，但 receipt 的 `changed_files` 漏列目前可觀測的 allowed-scope 檔案，無法確認 provenance。已發出單一 receipt 修正工作單；在修正前不得升為 verified。 |
| `FOR-P1-002` Host delivery adapter | `BLOCKED` | 精確目標、原始指令封包、fail-closed | 依賴 P0 和 P1。禁止前景視窗 fallback 與 timer 作為正常續作引擎。 |
| `FOR-P2-001` 整合驗收 | `BLOCKED` | 一條完整恢復回路 | 必須由獨立 verifier 驗證；UI 沒有證據即維持未驗證。 |

完整機器可讀 DAG：`.forseti/commander-state.json`。

## 已驗證的小型修補

`tests/test_f07.py` 新增案例：worker 仍執行時，即使已有舊 ResultReceipt，也必須回 `HOLD_RUNNING`，不得改走 synthesis 或 redispatch。針對 F05/F07/continuation 的 focused suite 已通過 `20 passed`；這只證明該案例，不代表桌面、adapter 或整個 Forseti 完成。

`FOR-P0-001` 的 hover event guard 已由 Commander 獨立重跑：`python3 -m pytest -q tests/test_hover_event_guard.py tests/test_ui_contract.py tests/test_poll_overlap.py`，結果 `95 passed`。它只支持「同一 dot 不再造成 hover 重建風暴」；不支持「桌面 app 已完全安全」的結論。

`FOR-P1-001` 的 Worker receipt 宣稱修改 `ledger.py`、`test_f07.py`、`test_task_continue.py`。Commander 獨立重跑 `python3 -m pytest -q tests/test_f05.py tests/test_f07.py tests/test_task_continue.py tests/test_recovery_contract.py`，結果 `55 passed`，且 scoped `git diff --check` 通過；但實際 allowed-scope 工作樹還可見 `recovery_contract.py`、`test_recovery_contract.py` 與 `test_f05.py`。這些檔案可能是本次工作或既有 dirty change，沒有 provenance 就不能猜。因此先要求 Worker 補正或明確排除，驗證 gate 保持關閉。

## 更新規則

1. Worker 只能提交 `SUBMITTED` 與 Delivery Receipt。
2. Verifier 以獨立測試、diff 與驗收條件決定是否 `VERIFIED_COMPLETE`。
3. 沒有 evidence 的進度一律保持 `STALLED`、`BLOCKED` 或 `UNKNOWN`。
4. 這份頁面與 Work Order 會和 Git commit 一起更新；GitHub 顯示的最後 commit 即是可追溯的最新版本。
