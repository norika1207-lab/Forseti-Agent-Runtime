# Forseti UI 安全測試計畫

狀態：`PROPOSED_FOR_COMMANDER_VERIFICATION`

本文件不是執行許可。`ui_safety_lock` 仍為 `ACTIVE`；重新開機也不構成批准。
在 Commander 驗證本計畫、且 owner 緊接在測試前明確批准以前，不得啟動、部署、
驅動或測試 Forseti.app。

## 單一整合宣稱

只驗證以下一件事：

> 在指定 Git SHA、單一 Forseti.app process、沒有 Accessibility 或自動化輸入的
> 受控環境中，owner 手動啟動程式，待初始畫面穩定後只把實體滑鼠移入一個既有
> Source Tree dot 並停留十秒，不會造成重複 tooltip transition、重疊 refresh、
> Forseti process 進入不可中斷狀態，或 macOS 失去可操作性；程式之後能正常結束。

這不證明整個桌面程式安全，不涵蓋其他視圖、長時間執行、部署、復原成功率、
多 session、鍵盤操作或任何背景自動續作。

## 可支持宣稱的精確證據

必須同時取得以下證據，少一項即為 `INCONCLUSIVE`，不得標記通過：

1. 測試前記錄 Git SHA、macOS 版本、Forseti build identity、開始時間與唯一 PID。
2. 離線 focused suite 在相同 SHA 通過，且完整保留命令、exit code 與測試數量。
3. 初始畫面穩定後，由 owner 做一次實體滑鼠移入；不得由 AX、腳本或錄製重播產生。
4. 一份帶時間的人工觀察記錄：進入前、停留十秒後、離開後各記一次 tooltip 狀態。
5. 兩個離散 process snapshot：hover 前與停留十秒後各一次。不得用 timer 或 polling loop。
6. app log 或既有 telemetry 能區分該次測試，且沒有重疊 refresh 或相同 dot 的重複 transition。
7. 測試結束時只送一次正常 quit，記錄是否在五秒內離開；失敗時保存 PID/state/log。

畫面看起來正常、測試者口頭說沒事、process 曾經存在、單元測試全綠，任何一項單獨都
不能支持此整合宣稱。

## 離線 Preflight

以下項目全部完成後，Commander 才能向 owner 請求一次性批准：

1. 確認 Work Order、此計畫與待測 SHA 已固定，工作區位於 `/Volumes/NewDrive/AI Project/Forseti`。
2. 確認 `ui_safety_lock` 仍為 `ACTIVE`，且批准尚未被預先填入或沿用。
3. 確認 Forseti.app 未執行；不得為了檢查而啟動它。
4. 執行離線 focused suite：

   ```text
   python3 -m pytest -q tests/test_hover_event_guard.py tests/test_ui_contract.py tests/test_poll_overlap.py
   ```

5. 靜態確認 hover handler 對相同 dot 有去重，且 refresh 不由 hover 直接建立額外 loop。
6. 記錄目前已知未知：Rust 檔案事件未完整取代高成本 refresh 路徑；本測試只量單次受控 hover。
7. 預先開好非 UI 證據保存位置與恢復指令，但不得執行 launch、deploy、AX 或 UI 驅動。
8. Commander 核對所有 preflight evidence 後，向 owner 顯示本宣稱、風險、stop conditions 與
   recovery path，取得「針對此 SHA、此一次測試」的明確批准。沉默、舊批准與重新開機皆不算。

## 一次一操作邊界

批准後仍按以下 Gate 逐步執行。每一 Gate 只有在證據已寫下且 stop condition 未觸發時，
才可進下一 Gate：

1. `G1 Launch`：owner 手動啟動唯一 process；記錄 PID 後停止操作三十秒。
2. `G2 Baseline`：人工確認系統仍可操作，只取一次 process snapshot；不移動到 dot。
3. `G3 Hover`：owner 只把實體滑鼠移入一個既有 dot 一次，停留十秒，不點擊、不切頁。
4. `G4 Exit hover`：owner 把滑鼠移到空白區一次，記錄 tooltip 是否只關閉一次。
5. `G5 Quit`：只送一次正常 quit，等待最多五秒；保存結果後測試結束。

不得平行開第二個 app、第二個 session 或第二條監控 loop。任何 Gate 失敗後不得跳到下一 Gate，
也不得在同一次批准下重新測試。

## 立即停止條件

任一條成立就立刻停止 UI 操作並進入非 UI recovery：

- macOS 游標、鍵盤或視窗切換明顯失去回應，或 beachball 持續三秒。
- Forseti process 顯示 `U`／不可中斷等待狀態。
- 同一個 dot 出現第二次 tooltip transition，或看到重疊 refresh 的明確證據。
- app 產生第二個非預期 process、視窗或 session。
- 單次 process snapshot 顯示異常資源壓力，或第二次 snapshot 相較第一次記憶體增加超過 256 MiB。
- 正常 quit 五秒內沒有完成。
- 證據保存失敗、PID 不明、待測 SHA 不符，或任何人無法確認目前 Gate。

停止條件是 fail-closed。不得用「再等一下」、連續點擊、重複 quit 或重新啟動來判斷是否恢復。

## 非 UI Recovery

1. 停止所有滑鼠與鍵盤輸入，記錄觸發條件和時間。
2. 使用預先開好的 Terminal 或遠端 shell，只讀取一次 `ps` 狀態並保存 PID/state；不使用 AX 或前景視窗控制。
3. process 仍可中斷時，只送一次 `SIGTERM` 並等待五秒；仍存在才送一次 `SIGKILL`。
4. process 若為 `U` 狀態，不重複送 signal、不再啟動 app；保存 process snapshot 與既有 log。
5. 主機仍可操作時，先將 evidence 複製到外接硬碟工作區，再由 owner 決定是否重開機。
6. 主機不可操作時，依 owner 的既有主機復原方式處理。重開機只恢復主機，不代表測試通過、
   不解除安全鎖，也不授權重試。
7. 任何失敗都建立新的 incident/receipt；下一次測試需要新的 Commander 驗證與 owner 明確批准。

## 明確禁止

本計畫及未來受控測試均禁止：

- Accessibility／AX API、VoiceOver scripting 或任何輔助使用權限驅動。
- `osascript`、AppleScript、`cliclick`、UI recorder/replay 或 foreground-window automation。
- 自動滑鼠、鍵盤、hover、click、window focus 或 menu 操作。
- timer loop、polling loop、`setInterval` 或以 watchdog 心跳當正常測試引擎。
- deploy script、Tauri integration test、批次啟動、壓力測試、長時間 soak test。
- 在沒有 owner 即時批准時啟動 app，或把重新開機、文件完成、單元測試通過當成批准。

## 判定與後續

- `PASS`：所有必要證據齊全、沒有 stop condition、正常 quit 成功，且 Commander 獨立核對。
- `FAIL`：任一 stop condition 觸發或 recovery 被使用。
- `INCONCLUSIVE`：證據缺失、觀測邊界不清、SHA/PID 不確定或操作超出單一宣稱。

不論結果為何，`ui_safety_lock` 都不因本計畫或一次測試自動解除。解除或縮小安全鎖需要另外的
Commander 決策、可追溯證據與 owner 明確授權。
