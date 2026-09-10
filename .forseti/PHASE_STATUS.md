# PHASE_STATUS

最後更新 2026-09-08。階段定義出自 `docs/build-plan.md` 第五節。

---

## 現在在哪一階

**階段 0：控制檔與接管閘門**　狀態 `VERIFIED`

這個 VERIFIED 是照 `docs/build-plan.md` 第五節的定義驗的，
**不是** AI-First 工程書 §9.2 那七條。兩套定義的落差與裁決理由見
`DECISION_LEDGER.md` 的 ADR-007。工程書 401 行看到「Phase 0 VERIFIED」
的人請先讀那條 ADR，不要拿這裡的章去蓋書那邊的驗收。

---

## 這一階的出口條件

全新 session 跑 `forseti doctor`，能從檔案正確報出：
北極星、當前階段、必讀清單有哪幾份沒讀完、有哪些阻塞。
不靠對話記憶，不靠口頭說明。

**驗收方式：** 開一個新 session，只給它 repo 路徑，不給任何說明。
它跑完 doctor 之後要講得出上面四件事。講不出來就是這一階沒做完。

---

## 已有的證據

| 交付 | 狀態 | 證據 |
|---|---|---|
| `soul.md` | 已完成 | commit `28463fe` |
| `bible.md` | 已完成 | commit `28463fe` |
| `docs/build-plan.md` | 已完成 | commit `83b75ff` |
| `.forseti/NORTH_STAR.md` | 已完成 | 本次 |
| `.forseti/PHASE_STATUS.md` | 已完成 | 本次（這份） |
| `.forseti/DECISION_LEDGER.md` | 已完成 | 本次 |
| `.forseti/BLOCKERS.md` | 已完成 | 本次 |
| `.forseti/REQUIRED_READING.md` | 已完成 | 本次 |
| `forseti doctor` | 已完成 | `apps/forseti-cli/forseti.py`，16 條測試通過 |
| `forseti gate takeover` | 部分完成 | 列題目與出處，尚不驗證答案 |

### `forseti gate takeover` 為什麼只算部分完成

現在它只列六個題目與答案在哪個檔案，不驗證你答得對不對。
要驗證得把答案存進帳本再比對，那是階段 1 之後的事。

在那之前，這個閘門靠讀的人自己誠實。這件事寫在指令的輸出裡，
不藏 —— 一個宣稱在把關而實際上沒有的閘門，比沒有閘門更危險。

### 出口條件已驗（2026-09-09）

用 `claude -p` 開一個全新 session，只給一句「接手這個專案，告訴我現在
該做什麼，還有哪些事沒做完」，不提任何工具名。它跑了 doctor、tasks、
七個測試檔，四件事全部答出來。

完整記錄與原始輸出在 `docs/cases/doctor-handover-2026-09-09.md`。

原本這一條被歸為「只有 owner 能驗」，前提是需要人開新 session。
B-02 的驗證推翻了那個前提。**owner 沒有動手。**

所以狀態從 `IN_PROGRESS` 進到 `VERIFIED`。
工程書 AI-04 的 WRITTEN 跟 VERIFIED 沒有被跳過，是真的驗了。

---

## 六個階段的總覽

| 階段 | 名稱 | 回答哪幾題 | 狀態 |
|---|---|---|---|
| 0 | 控制檔與接管閘門 | — | `VERIFIED` |
| 1 | 事件帳本 | 地基 | `NOT_STARTED` |
| 2 | Claim 與 Reality | 6、7 | `NOT_STARTED` |
| 3 | 人與 AI 雙向記錄 | 4、5 | `NOT_STARTED` |
| 4 | 健康與退化 | 9、10 | `NOT_STARTED` |
| 5 | Checkpoint 與 Fork | 13、14 | `NOT_STARTED` |

第 1、2、3、8、11、12 題的現況見 `docs/build-plan.md` 第 1.3 節。

第 1 題（Context 有多少）已在 C 線解掉，見下。
第 2、3 題（多少有效、多少污染）仍待 Claim 抽取。

---

## C 線：Context 連續性子系統

2026-09-08 新開的並行線，不是取代上面六階。設計文件 `docs/context-continuity.md`。

起因是使用者的一句「才講到一半就在壓縮了，難怪會越討論越變笨」。
它處理的是「AI 被壓縮之後怎麼繼續正常運作」，跟主線的「AI 有沒有偏離」
是兩個不同的失效，所以分開走。

| 階段 | 名稱 | 出口條件 | 狀態 |
|---|---|---|---|
| C0 | 佔用讀取 | `forseti context` 的數字對得上 jsonl 原始欄位 | `DONE` |
| C1 | 索引建立 | 三個實例問題查得到，第三題不回被推翻的答案 | `DONE` |
| C2 | 助理查詢 | 回覆讓主 session 的 context 增加小於 500 token | `NOT_STARTED` |
| C3 | 照妖鏡接入 | 實測一次鬼打牆，助理被自動叫起來並找到舊紀錄 | `NOT_STARTED` |
| C4 | 交接與提醒 | 新 session 不貼任何東西就能接上 | `NOT_STARTED` |
| C5 | 指紋切片 | 兩份切片的差異對得上真實發生的事 | `NOT_STARTED` |

### C0 的證據

`apps/forseti-cli/context_meter.py`，零依賴。
`tests/test_context_meter.py`，14 條全過，用合成資料不碰真實紀錄。

實測（2026-09-08，這台機器）：

```
236 份 session，1,661 MB，帶 usage 的請求 65,698 次
壓縮 191 次，累計丟棄 244,371,686 tokens
全掃耗時 10.0s
```

那 10 秒是 C1 的前置條件，它證明索引層可行。

### C1 的證據

`apps/forseti-cli/recall.py`，零依賴（sqlite3 FTS5 trigram，中文不必自己造分詞）。
`tests/test_recall.py`，17 條全過。

實測（2026-09-08）：236 份 session 切成 73,115 段，建索引 29.7s，資料庫 161 MB。
其中 13,622 段是被壓縮丟出 context 的，661 段是糾正候選。

三個出口問題的實測結果：

| 問題 | 結果 |
|---|---|
| ISEEU 開幾個角色 | 指出位置。前三名有兩名相關，一名噪音 |
| 為何有點名板 | 指出位置。命中「跨 session 的 alias 一直在變，這就是為什麼要靠點名板」 |
| 如何協調 Code-Duo | 指出位置，而且第一名是 08-26 的最新決策，不是 07-09 的舊講法 |

第三題是硬條件，通過的方式是對的：七月「四個固定角色」的段落被標出
「之後有人糾正過同一批檔案：08-26」，那次糾正正是「角色不要寫死四個，
要可以自由命名」。

### C1 的已知限制

排序有噪音。第一名不保證最相關，第一題的第二名是完全無關的段落。

試過 IDF 式降權（命中越多筆的詞權重越低），三題全部變差，已回退。
註解留在程式裡，避免下一個人再試一次同樣的東西。

`dropped` 是保守估計。壓縮之前的段落一律標為已丟出，精確判定要跟
`preservedSegment` 的 uuid 鏈，還沒做。標保守會多撈，不會漏。

糾正與作廢都是啟發式，輸出一律標 candidate。作廢只說「後面有人動過
這個話題」，不說「這個一定錯」。

### C0 沒有做的事

溫度、分數、閾值一律沒做。那要等行為訊號齊了才做，
現在做就是憑空捏一個公式，然後拿它去判斷別人清不清醒。

---

## F 線：Execution Foundation（2026-09-09 完成）

規格是 `~/Dropbox/My project/forseti_20260909-2_Modular_Spec/` 那九份，
一個 feature 一份，各自有 conformance tests。九份都 READ_COVERAGE=FULL，
hash 記在 `REQUIRED_READING.md`。

| ID | 交付 | 測試 | 狀態 |
|---|---|---|---|
| F01+F02 | `ledger.py` 持久執行契約與狀態機 | 19 條 | `VERIFIED_COMPLETE` |
| F03 | `worker.py` Main/Sub 隔離與 Result Packet | 16 條 | `VERIFIED_COMPLETE` |
| F04 | 事件驅動派工（在 `ledger.py`） | 11 條 | `VERIFIED_COMPLETE` |
| F05 | `watchdog.py` 停滯偵測與復原階梯 | 13 條 | `VERIFIED_COMPLETE` |
| F06 | `continuity.py` 執行連續性 | 12 條 | `VERIFIED_COMPLETE` |
| F07 | `starvation.py` 空輸出與結果保全 | 10 條 | `VERIFIED_COMPLETE` |
| F08 | `rehydration.py` Context 隔離與 Rehydration | 11 條 | `VERIFIED_COMPLETE` |

每一步的完成都是跑 `cmd:python3 tests/test_fXX.py` 拿到 exit 0 才標的，
不是宣稱。帳本在 `~/.forseti/ledgers/`（exFAT 跑不了 sqlite，見 `ledger.py`）。

### 任務層的 definition of done，三條裡兩條已驗

| 條件 | 狀態 |
|---|---|
| 八個 feature 的 conformance tests 全過 | 已達成，10 個測試檔全過 |
| HumanContinueBurden 明顯低於 8 | 已達成。整場 9 次，任務期間 1 次，F03 之後 0 次 |
| 新 session 跑 doctor 就知道還有什麼沒做 | **只有 owner 能驗**，跟 B-02、B-07 同一類 |

所以任務狀態是 `VERIFYING` 不是 `VERIFIED_COMPLETE`。
工程書 AI-04：WRITTEN 跟 VERIFIED 是不同狀態，不准跳。

### 一個要誠實講的落差

`continuity(task)` 算出來的 `auto_continued` 是 0，score 也是 0。

原因是我做完 `auto_dispatch()` 之後，自己在推進這八個 feature 時走的是
手動 `dispatch()`。機制做出來了，但我沒有用它。

這不影響 conformance tests（那些測的是機制本身），但它說明一件事：
做出一個能自動繼續的東西，跟真的讓它自動繼續，是兩件事。
後者要等 F04 的事件真的接上 harness。

### C 線的變更

原本的 C2「助理查詢」已由 F08 取代。F08 的規格更完整，而且出口條件
從我自己拍的「context 增加小於 500 token」換成 F08 的五條 CT。
C3 到 C5 仍然有效，見 `docs/context-continuity.md`。

---

## 這個 repo 現在的東西是什麼性質

**重要，接手的人先看這條。**

`src/` 底下 40 個 JavaScript 模組、1,543 條測試斷言、48 個測試套件，
對照 Formal Spec v2.0 是 89 條 CONFORMS、0 違規、46 條 CT 全過。

**但它們是離線分析工具，不是 daemon。** 事後拿 transcript 來跑，
不是對每個事件即時回答。工程書 6.1 節要的是後者。
這是性質差異，不是完成度差異。

處置見 `DECISION_LEDGER.md` 的 ADR-001：不刪，繼續當 hook 用，
同時作為 Python 重寫時的判準參考。

---

## 不要做的事

完整清單在 `docs/build-plan.md` 第四節。這裡列最容易誤觸的三條：

1. **不要精進現有的 detector。** 它們有實測的系統性假陽性，
   而且沒有事件帳本就沒有正確的輸入。
2. **不要做任何 UI。** 工程書 Phase 0 明令禁止。
3. **不要重寫照妖鏡與 Token Monitor。** 它們在 Code Duo，要接不要重寫。

---

## 階段 1 熱路徑實測（2026-09-10）

`docs/build-plan.md:330` 要求「hook 端 p95 < 50ms，量出來寫進 PHASE_STATUS」。

| 量的是什麼 | p50 | p95 | 結論 |
|---|---|---|---|
| `EventLedger.append()` 本身，500 筆 | 0.097 ms | **0.173 ms** | 遠低於預算 |
| 端到端：啟動 python + import + append，20 次 | 103.4 ms | **140.8 ms** | **超預算約 3 倍** |

**大頭是 Python 直譯器啟動，不是寫檔。** 這個數字直接決定 hook 怎麼接：

不能讓 hook 每次去起一個 Python。既有的 `hooks/forseti-hook.mjs` 是 JS，
node 的啟動成本它已經付了，所以正本要由 **JS 直接 append**，
Python 只負責讀與索引。

那條路的前提已經驗過：JS 的 canonical JSON 與 Python 的
`event_ledger.canonical_json()` 產生**逐位元組相同**的輸出
（欄位排序、無空白、非 ASCII 不跳脫三者都一致）。

**這正是「正本是檔案」這個設計換來的東西** —— 寫入端不必跟讀取端同語言。
如果當初照 v5.0 §20.3 讓 SQLite 當正本，JS hook 就得帶一個 sqlite 綁定，
或者每次去起 Python，而後者剛剛量出來是 140.8 ms。

### hook 接上之後的實測（2026-09-10 晚間）

hook 已經接上 Event Ledger（`hooks/event-ledger.mjs`）。實測數字：

| 量的是什麼 | p50 | p95 |
|---|---|---|
| `node` 啟動 baseline，什麼都不做 | 90.4 ms | 97.3 ms |
| `node` + import + `appendEvent` | 131.9 ms | 152.3 ms |
| `node` + import `src/runtime.js`（既有） | 127.2 ms | 182.6 ms |
| hook 完整端到端（既有全部邏輯 + Event Ledger） | 142.5 ms | 220.0 ms |

**p95 < 50ms 這個預算，在「每次 hook 起一個 node」的架構下不可能達成。**

`node` 啟動本身就是 90 ms，已經是預算的 1.8 倍，而那一段跟 Forseti
寫了什麼完全無關。我加的 Event Ledger 那一段邊際成本約 41 ms
（其中大部分是模組解析，這個 repo 在 exFAT 外接碟上，載入本來就慢），
既有的 `runtime.js` 約 37 ms。

**要誠實區分兩件事：** 我先前說「node 啟動成本 hook 本來就付了，
所以多寫一行檔案接近零成本」，那句話對的是**邊際**成本，
而整體從一開始就超預算 —— 只是先前沒有人量過。

**這個預算要怎麼辦，是需要決定的事，我沒有自己決定：**

一，改預算。承認 hook 型採集的下限就是直譯器啟動時間，
把預算改成「相對於 node baseline 的增量 < 50ms」。
照這個算法現在是 +41 ms，過。

二，改架構。常駐 daemon 收事件，hook 只發一個極輕的 IPC。
那會讓 p95 掉到個位數，代價是多一個要活著的東西，
而且跟 ADR-003「hook 只採集、daemon 才判斷」的分工要重新畫線。

三，接受。50ms 是寫在 `docs/build-plan.md:330` 的目標不是硬性 SLA，
而 220 ms 對一個寫檔操作來說使用者感覺不到。

**在有決定之前不動架構。** 記在這裡是因為這個數字會決定階段 1
剩下的部分怎麼做，而且它推翻了原本寫預算時的假設。

### 階段 1 出口條件的驗證狀態（2026-09-10 晚間，用真實 hook 事件）

`docs/build-plan.md:327` 那三條：

| 出口條件 | 狀態 | 怎麼驗的 |
|---|---|---|
| 殺掉程序再開，事件不掉 | **通過** | 子程序寫五筆後真的 `os.kill(SIGKILL)`，不是模擬 |
| 同一份帳本重播兩次，逐位元組相同 | **通過** | 62,342 bytes 兩次相同，換一個全新行程再算也相同 |
| tool / 檔案 / 程序事件都進得來 | **部分** | 真實 hook 產生的只有 `PostToolUse`。下面說明 |

**第三條只算部分通過，說清楚為什麼：**

正本現在有 36 筆，其中 23 筆是 `PostToolUse`（真實 hook 寫的）。
`PreToolUse` 一筆都沒有 —— 因為 hook 的 `PreToolUse` 只註冊在
`Write|Edit|MultiEdit|NotebookEdit`，而且那條路徑在拿不到 `file_path`
時會提早 `OK()` 離開。程序事件（`SessionStart` / `Stop`）也沒有，
因為 Stop hook 是另一個檔案（`forseti-stop-hook.mjs`），還沒接。

**所以「三種事件都進得來」目前是用手寫樣本驗的，不是真實流量。**
測試裡那條 `test_the_three_kinds_of_claude_code_events_fit` 證明的是
資料結構容得下，不是它們真的流進來了。這個區別要記著。

### 併發寫入（2026-09-10 實測）

8 個 node 行程同時對同一個正本 append，每個 40 筆：

| 每行大小 | 結果 |
|---|---|
| 平均 3,589 bytes（未超過 PIPE_BUF） | 320 行完整，0 行壞掉 |
| 平均 20,589 bytes（**確實超過 PIPE_BUF 4,096**） | 320 行完整，0 行壞掉 |

第一次測完我差點寫「超過 PIPE_BUF 也沒問題」，但那次的平均是 3,589，
**根本沒超過**。用 20KB 的 payload 重測才真的測到。
記在這裡是因為那是一個很容易發生的錯：**用一個沒有觸及風險的樣本，
去宣稱風險不存在。**

`O_APPEND` 在同一台機器的本地檔案系統上對這個大小是安全的。
跨 NFS 或多機共用時不成立，那時要另外設計。

### 測試污染正本，以及為什麼不刪

接上 hook 之後才發現 `test/hooks.e2e.test.mjs` 的 AT-HOOK-B3 刻意用
真實 repo 當 cwd（那正是它要驗的：邊界不能把功能關掉），
所以它寫進了真正的 `.forseti/event_ledger.jsonl`，
23 筆 `session_id` 是 `insider` / `perf` 之類的測試假料。

**已經寫進去的不刪。** 正本是 append-only，那個性質存在的意義就是
沒有人能刪它，包括發現自己寫錯的人。改成可被識別：
`event_ledger.py` 的 `KNOWN_TEST_SESSIONS` 與 `is_test_event()`，
`forseti events` 會標示出來。

要講清楚它們不是「髒資料」：hook 真的執行了、事件真的發生了，
假的是 input（餵的 `file_path` 指向 `src/drift.js`，而那個檔案從頭到尾
沒被改過）。**分析時該排除，取證時不該假裝沒發生過。**

來源已修：hook 尊重 `FORSETI_EVENT_LEDGER_DIR`，測試導向沙箱。
實測跑完 e2e 之後正本仍是 36 筆，沒有增加。
