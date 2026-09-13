# Forseti 桌面版

`.forseti/PRODUCT_DIRECTION.md` 三件事的第一件。
Tauri 2，工程書 Phase 8 §17.1 的 in scope 寫的就是 `CLI/Tauri UI`。

## 跑起來

```bash
cd desktop
npm install
npx tauri dev          # 開發
npx tauri build --bundles app   # 建 .app
open ~/Applications/Forseti.app
```

實測 2026-09-13：release build 5 分 46 秒，`Forseti.app` 5.0 MB。

## 架構：這一層刻意很薄

```
前端 ui/          呈現。不算任何東西
  ↕ invoke
Rust src-tauri/   轉發 + 檔案監看。不算任何東西
  ↕ subprocess
Python desktop_api.py   所有判斷在這裡
  ↕ import
apps/forseti-cli/*.py   既有模組，一個字都沒重寫
```

**為什麼判斷不搬進 Rust 或 JS：** 判斷邏輯只能有一份。
兩份遲早會分歧，而分歧的那天沒有人會發現，因為兩邊各自的測試都會過。
這個 repo 2026-09-11 才因為同一個形狀還過一次技術債
（`stopreason.py` 與 `continuity.py` 各有一份 `STOP_REASONS`）。

## 溫度計為什麼不是一個數字

工程書 Phase 8 的預設畫面是 `Forseti 37.2 C WATCH`。
而這個專案的設計規則 §3.2 明令不合成單一風險分數：

> 把五個可行動的維度壓成一個數字，會毀掉唯一讓它們可行動的東西。

`FS-RSK-001` 也要求 Composite R MUST 同時顯示 EvidenceCoverage，
低 coverage 的高分不能裝作確定。

所以畫面給的是：

| 東西 | 內容 |
|---|---|
| 狀態燈 | OK / WATCH / ATTENTION，由分項裡最嚴重的那一個決定 |
| 一句話 | 燈憑什麼是那個顏色，指名是哪一項造成的 |
| 分項 | 現值、門檻、為什麼、以及它從哪個檔案來 |
| 提醒 | 最多三條，每一條帶一個可以直接跑的指令 |

**狀態燈可以用一句話講完它憑什麼是那個顏色。講不出來就不該有燈。**

提醒最多三條的理由是 `FS-RCV-002`：rescue 的 user-facing output
SHOULD 是單一可行動方案，而不是十幾個告警。

## 即時是怎麼即時的

Rust 那層用 `notify` 監看 `.forseti/`，變動就推 `forseti://changed`，
前端收到就重量。**不是定時輪詢。**

理由是這個系統自己的規格 §24.2 在量 `GovernanceOverheadRatio`
（治理系統本身吃掉多少時間）。一個什麼都沒發生也一直跑 Python 的
監控工具，正是它要抓的東西。

連續變化會合併：一次寫檔可能觸發好幾個事件，
每一個都重算一次快照是浪費，所以有 700ms 的合併窗口。

## 兩個分頁

**狀態**：燈、分項、提醒。啟動預設在這裡。

**路徑**：Source Tree。選一個 session 按載入，
它會跑 `tools/timeline.py`，節點依她的反應上色，
點任何一個變色節點給一行可直接執行的 fork 指令。

## 已知限制，寫清楚不蓋過去

**一，載入路徑很慢。** `timeline.py` 每一輪都跑 `claims.verify()`，
163 輪要數分鐘。大的 session 更久。還沒做快取。

**二，判準太粗。** 2026-09-11 實測 163 輪，`CORRECTED` 8 個裡有誤判
（長篇論述裡的否定詞），而當天最嚴重的兩次它一個都沒抓到。

**三，fork 只給指令不代跑。** 按鈕給的是可複製的指令，
不是按下去就執行。那是刻意的：fork 會產生一個新的 session 檔案，
那件事該由人明確發動。

**四，沒有簽章。** 第一次開會被 macOS 擋，要在系統設定裡放行。

**五，icon 是程式產生的。** 512x512 RGBA，一條主幹加分岔點。
需要的話換掉 `src-tauri/icons/icon.png`。

## exFAT 的坑，這次實際咬到

build 產物不能放在 NewDrive 上。

macOS 會為每個帶 extended attribute 的檔案寫一個 `._` sidecar，
而 Tauri 的 build script 會掃 permissions 目錄下的每個 `.toml`，
把 `._default.toml` 當成真的權限檔去讀，然後炸在
`stream did not contain valid UTF-8`。

刪掉不夠，那些 sidecar 在下一次寫檔時又會長回來。

處理：`desktop/.cargo/config.toml` 把 `target-dir` 指到本機 APFS。
原始碼仍然在外接碟上，只有暫存產物搬走。

另外 icon 必須是 RGBA（四通道），RGB 會讓 `generate_context!` panic，
訊息是 `icon ... is not RGBA`。
