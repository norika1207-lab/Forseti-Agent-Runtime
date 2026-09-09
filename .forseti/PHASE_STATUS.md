# PHASE_STATUS

最後更新 2026-09-08。階段定義出自 `docs/build-plan.md` 第五節。

---

## 現在在哪一階

**階段 0：控制檔與接管閘門**　狀態 `IN_PROGRESS`

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

### 出口條件還差什麼

出口條件是「開一個全新 session，只給 repo 路徑，不給任何說明，
它跑完 doctor 能講出北極星、當前階段、必讀缺什麼、有哪些阻塞」。

指令本身做完了，但**這一條還沒有被真的驗證過**，因為驗證需要開一個
全新的 session。跟 `BLOCKERS.md` 的 B-02 是同一類：只有她做得到。

所以這一階的狀態是 `IN_PROGRESS` 不是 `VERIFIED`。
工程書 AI-04：WRITTEN 跟 VERIFIED 是不同狀態，不准跳。

---

## 六個階段的總覽

| 階段 | 名稱 | 回答哪幾題 | 狀態 |
|---|---|---|---|
| 0 | 控制檔與接管閘門 | — | `IN_PROGRESS` |
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
