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

**第三條 2026-09-10 深夜更正：不是「部分通過」，是 0% 驗證。**

先前寫的是「23 筆 PostToolUse 是真實 hook 寫的」。那句話誤導，
現在查清楚了：**正本 36 筆裡沒有一筆來自真實工作。**

| 來源 | 筆數 |
|---|---|
| `test/hooks.e2e.test.mjs` 與效能測試直接呼叫 hook | 23 |
| 我在這個 session 手寫進去的 | 13 |
| **真實工作觸發 hook 產生的** | **0** |

驗法很直接：我今天用 Write 建了 `tools/check-page-readable.py`、
`test/event-ledger.test.mjs`、`docs/glossary.md`、`docs/reading/v5-13-14.md`，
每一個在正本裡都是 0 筆。

**原因是 hook 對這個 session 根本不生效。** hook 註冊在 repo 的
`.claude/settings.json`，而這個 session 的 project 是 `/Users/norikaoda`，
不會載入那份設定。Bash 工具裡 `cd` 進 repo 不改變這件事。

**這繼承了 B-02 已經記過的事實**（那條已解除，但它記的現象還在）：
掃全機 jsonl 找 cwd 在 repo 底下的 session，結果是零個。
hook 註冊在那裡，一次都沒有機會跑。我把 Event Ledger 接上去，
等於接在一個從來不會被觸發的地方。

**所以「三種事件都進得來」目前是用手寫樣本驗的。**
`test_the_three_kinds_of_claude_code_events_fit` 證明的是資料結構
容得下，不是它們真的流進來了。這個區別是階段 1 現在最大的缺口。

**驗它的唯一方法是從 repo 目錄開一個真的 session 工作。**

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

### 第三條出口條件：從 0% 到 3/3（2026-09-10 深夜）

更正上面那段之後，實際去驗了。方法是從 repo 目錄開一個真的 session
工作（`claude -p`），因為 hook 只在那種 session 底下才會被載入。

**派工前正本 36 筆，派工後 42 筆。多的 6 筆全部有真實 session id**
（`021e0e9c-5e21-4b79-b42e-a5a55f881e37`，uuid 不是測試假名）：

```
PreToolUse   TOOL_CALL    .forseti/inbox/.../accepted.txt
PostToolUse  FILE_WRITE   .forseti/inbox/.../accepted.txt
PreToolUse   TOOL_CALL    hooks/README.md
PostToolUse  FILE_WRITE   hooks/README.md
PreToolUse   TOOL_CALL    .forseti/inbox/.../done.txt
PostToolUse  FILE_WRITE   .forseti/inbox/.../done.txt
```

**更正一個我先前的判斷：** 我以為 `PreToolUse` 不會進來，
理由是那條路徑拿不到 `file_path` 會提早 `OK()` 離開。
實測進來了 3 筆 —— 因為 append 的位置在那個判斷之前。猜錯了。

程序事件補上了：`forseti-stop-hook.mjs` 也接了，
`Stop` → `MODEL_OUTPUT`，實測 42 → 43 筆。

接的位置刻意在 `if (!open.length) OK()` **之前**。那一行很關鍵，
大多數的 Stop 都沒有未完成宣告會從那裡直接離開；記在它後面的話，
只有「被擋下來的那一輪」會留下紀錄，正常收尾的每一輪都會消失。
**那樣的帳本只看得到異常看不到基準，而異常沒有基準就失去比較的對象。**

| 出口條件 | 狀態 |
|---|---|
| 殺掉程序再開，事件不掉 | 通過（真的 SIGKILL） |
| 重播兩次逐位元組相同 | 通過（62,342 bytes，跨行程也相同） |
| tool / 檔案 / 程序事件都進得來 | **通過**（TOOL_CALL、FILE_WRITE 來自真實工作；MODEL_OUTPUT 實測） |

### Evidence Receipt 搬進帳本（2026-09-11）

`docs/build-plan.md:323` 的最後一項交付。**做法不是新增一種事件，
是讓事件帶著自己的證據。**

理由：evidence 不是一件「發生的事」，是某件事在那一刻的證據。
拆成兩筆的話，它們之間的關聯要靠時間或 id 去拼，而拼接會錯，
尤其在併發寫入的時候。v5.0 §6.1 的 NormalizedEvent 本來就有
`result` 與 `metadata`，證據放那裡是它們的用途。

量測的位置也動了：從原本的 PostToolUse 分支提前到 append 之前，
兩邊共用同一次量測。**同一輪對同一個檔案量兩次的話，兩次之間檔案
可能已經變了，而那會產生兩個都是真的、但互相矛盾的證據。**

實測（`FORSETI_EVENT_LEDGER_DIR` 導向沙箱）：

```
type      FILE_WRITE
result    13 bytes
evidence  byteSize 13, contentHash a1c372016c6ccf88, existence true
磁碟實際  13 bytes, a1c372016c6ccf88
```

**舊的 `state.json` 那份沒有拿掉。** 那不是重複而是兩個讀者：
`src/runtime.js` 的分析層讀 `state.json`，Event Ledger 是給重播與
跨 session 追溯用的。要拿掉舊的得先把 runtime.js 那一整層改成從帳本讀，
那是另一件事。兩份內容保證一致，因為用的是同一次量測。

`existence` 的三態在兩邊都有測試守著：量得到是 `true`/`false`，
量不到是 `'unknown'` 不是 `false`。**量不到跟不存在是兩件事** ——
混在一起的話，一個因為權限讀不到的檔案會被當成「AI 說做了但沒做」，
而那是冤枉它。

**階段 1 的五項交付到此全部完成。**

### 階段 2 完成，以及它第一次跑出來的那個答案（2026-09-11）

五項交付全做完，最後一項是從 `src/claims.js` 移植三個 primitive
（`apps/forseti-cli/overclaim.py`）。

**第一次拿真實 transcript 跑 FP-03，結果值得留下來：**

```
FP-02   POSITIVE 0   NEGATIVE 0     INDETERMINATE 300
FP-03   POSITIVE 0   NEGATIVE 295   INDETERMINATE 5
FP-07   POSITIVE 0   NEGATIVE 0     INDETERMINATE 300
```

那 5 個 INDETERMINATE 全部是同一句話：**「我親自」**。
全部是主 session 自己說的，而判準的理由是「查不到這個 session 的 receipt」。

**查不到的原因是 hook 對主 session 不生效**（它的 project 是
`/Users/norikaoda`，載不到 repo 的 settings）。

所以這個結果同時是三件事：

一，判準做對了。它沒有冤枉（那幾次是真的親自讀的），也沒有背書
（它確實沒有證據）。**如果判準預設「說親自驗但沒證據等於誇大」，
主 session 剛剛會被冤枉六次。** bible Q-07 那條原則在這裡直接兌現。

二，它指出一個真實的缺口：主 session 的活動沒有被採集，
所以關於主 session 的任何宣稱，這套系統目前都只能答「我不知道」。

三，FP-02 與 FP-07 全部 INDETERMINATE 是預期的 ——
它們要結構化的 scope 與宣稱／驗證計數，transcript 裡都沒有。

### 抽取器校準：冤枉率 30.8% 降到 1.9%（2026-09-11）

階段 3 的風險清單吃 `claims.py` 的輸出，上游有誤判下游的警告就是噪音。
所以在往下走之前，先拿真實語料把上游量一次。

工具是 `tools/claims-audit.py`，它做的事只有一件：拿真的講過的話進去，
把每一類判定的原句攤開給人看。**它不判斷對錯，它沒有那個能力** ——
判斷一個宣稱是不是真的需要當時的上下文，而那只有人有。

六個真 session、4,747 段文字：

```
              校準前              校準後
REFUTED       541　30.8%          34　 1.9%
VERIFIED      187　10.7%         205　11.6%
UNKNOWN       951　54.2%       1,454　82.2%
```

**降的不是偵測力，是冤枉率。** 被擋下來的全部變成 UNKNOWN，
沒有一個變成 VERIFIED；VERIFIED 反而多了 18 個（絕對路徑那個 bug 修好之後）。

逐條看原句發現的東西，按價值排序：

**一，驗證器自己會爆炸。** 第一次跑的第一秒就撞到
`RuntimeError: Could not determine home directory` —— `~someone/x`
展不開時 `expanduser()` 會丟例外，而 `verify()` 沒接。
批次跑的時候它會讓後面所有宣稱都沒被驗到，**而且沒有人會知道**。
那比判錯嚴重。

**二，少吃一個字元就冤枉一個真目錄。** 路徑正則不吃開頭的 `/`，
`/Users/norikaoda` 被抽成 `Users/norikaoda`，相對於 repo 當然找不到。

**三，定罪的門檻本來就定錯了。** 這是最大的一塊。
`Goal/Task`、`yes/no`、`github.com/...`、`9/8`、`$HOME/llama.cpp`
全部被判成「你講了假話」。門檻改成一句：**只有在驗證器真的有能力驗、
而且真的驗了、答案是否定的時候才給 REFUTED，其餘一律 UNKNOWN。**
四條結構規則（佔位符／沒有副檔名／repo 外／數字不算副檔名），
每一條都附當時抓到的實際字串當出處。

**四，技術上正確的定罪也可能是冤枉。** 原句講
`~/Library/Application Support/Claude/...`，含空格被切成
`~/Library/Application`，而那裡剛好真的有一個 0 bytes 的檔案。
CT-001 判得沒錯，**但它驗的不是那句話在講的東西**。
所以 CT-001 那條定罪路徑也要先問有沒有資格。

### 剩下的 34 筆，誠實講是什麼

沒有再加規則去擋。再擋下去就會變成「把判準放寬到什麼都過」，
而那是修誤判最容易犯的錯。四種形狀，結構上跟真的不存在無法區分：

- 別的專案的相對路徑（`logs/train_run3.log`、`data/city.json`）
- 有副檔名的斜線列舉（`coord_send/read.py` 其實是兩個檔案的簡寫）
- 說明文字裡的舉例（`src/工具/foo.ts`）
- 疑問句被當成宣稱（「看 `.forseti/state.json` 有沒有出現」）

最後一種是抽取層的問題不是驗證層的：`PAST_TENSE` 在句子別處命中，
把一個問句抽成了宣稱。要修它得能分辨句子的語氣，而那是語意判斷，
`docs/build-plan.md:350` 明文禁止。

**這四種留著。** 1.9% 的冤枉率，34 筆少到可以人工全部看過，
而 `tools/claims-audit.py` 讓下一個人隨時可以重跑一次。
**那不是判準失效，是它們的前提還沒備齊。** 記在這裡是為了讓下一個人
不要看到一整欄 INDETERMINATE 就以為模組壞了。
