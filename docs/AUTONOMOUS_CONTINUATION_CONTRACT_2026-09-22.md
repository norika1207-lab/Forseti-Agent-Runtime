# Forseti 自動續作執行契約

日期：2026-09-22

## 目的

把「繼續做」改成可驗證的執行規則，不以自然語言宣稱代替工具結果。

## Commander audit 規則

1. 讀取 Task Ledger、durable worker events、ResultReceipt、測試程序與工作樹變更。
2. 只有下列項目算 progress signal：新檔案／新 diff、新工具結果、新測試結果、新 receipt、verified completion event、dependency resolution。
3. active/running、空白回合、單純報告、自然語言「正在做」都不算 progress。
4. task 未完成且一個 audit 週期沒有 progress signal 時，必須在同一輪採取一個具體動作：編輯、測試、建置、checkpoint、或轉做下一個未完成缺口。UI safety lock 啟用時不得以 UI 驗收作為動作。
5. 外部阻塞只能阻塞該缺口；必須轉做下一個不依賴它的缺口，不得只解釋阻塞。
6. 每次回報前必須先留下 evidence ref；沒有 evidence 不得宣稱完成。

## 完成定義

- 程式修復：有實際 diff + 對應回歸測試結果。
- 原生 E2E：AX/UI 實際狀態或 screenshot + 可重現操作步驟。
- 完整回歸：完整命令結束碼與總數；局部測試不得冒充完整回歸。
- 阻塞：記錄精確錯誤、已嘗試的替代路徑、下一個可做缺口。

## 失約判定

下列任一情況即標記 `CONTRACT_BREACH`，不得以「已繼續」收尾：

- watchdog 週期內沒有 progress signal，也沒有具體 recovery action。
- 把局部測試、編譯或自然語言宣稱寫成完整產品完成。
- 未留下 evidence ref 就宣稱修復或 E2E 通過。
- 明知有未完成缺口卻用「完成」或「全部通過」描述。

## 權限邊界

本契約可以約束本 repo 的工作流程與報告格式；Codex 沒有 Token 發放、扣款或賠償權限，因此不能承諾 Token 賠償。若發生 `CONTRACT_BREACH`，唯一可自動執行的補救是：留下 breach event、保存已有證據、停止誤報，並在下一週期重啟具體工作。

## 目前狀態

- watchdog：ACTIVE，每 2 分鐘。
- 已核驗：完整 pytest `2789 passed, 9 skipped`；UI contract `88 passed`；隔離原生 AX/UI smoke 通過。
- 未完成：正式 bundle stale process 清理、完整 owner action/reload 流程、其餘 R04/R05/R06/R09/R10/R11/R12 產品級閉環。

## Desktop controller

`tools/codex-desktop-controller.sh` 是離線、event-driven 的 host adapter 入口，不是 heartbeat，也不是 macOS Accessibility controller：

```sh
tools/codex-desktop-controller.sh \
  --db /path/to/ledger.db \
  --cwd /path/to/workspace \
  --step task:step \
  --target exact-thread-id
```

它從 stdin 接收 JSONL observation，僅在同一精確 target 已持久記錄 `ACTIVE` 後收到 `IDLE` 時，讀取 ledger 保存的原始 `next_action` 並輸出 idempotent packet。缺少 Accessibility permission、目標不相符、state 不明、observation id 缺失、沒有前一筆 ACTIVE、或 ledger 沒有已授權原始動作時，一律 `FAIL_CLOSED`。

它不輪詢、不尋找前景視窗、不點擊、不輸入自然語言，也不直接對桌面 App 發送任何內容。`--interval`、`--idle`、`--once` 與 `--dry-run` 是已拒絕的舊 polling 參數。真正的 host transport 仍是未驗證範圍；在 UI safety lock 明確解除前，任何實機 AX/UI/部署測試都禁止執行。

本文件不宣稱已啟動常駐 controller，也不宣稱任何實機 AX/UI delivery 已通過；離線 adapter 測試只能支持 fail-closed 邏輯。
