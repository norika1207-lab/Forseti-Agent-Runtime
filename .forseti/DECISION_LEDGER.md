# DECISION_LEDGER

已接受的決策、被否決的替代方案、理由、推翻條件。

規則：決策用增補的方式更新，不回頭改寫。要推翻就新增一條標明取代哪一條。
理由是 v5.0 §19.3：更正取代先前紀錄，而不是靜靜改寫歷史。

---

## ADR-001　主線用 Python，JS 保留為 hook 與參考實作

**日期** 2026-09-08　**狀態** 已接受

**決策：** 新的 Engine 用 Python 3.12。現有 40 個 JS 模組不刪不重寫，
繼續當 Claude Code 的 hook 用，同時作為 Python 實作的判準參考。

**理由：**
- AI-First 工程書 6.1 節明確指定 Python 3.12 + Pydantic v2 + SQLite WAL + Typer + pytest
- daemon 需要 watchdog / psutil 這類生態
- JS 那些模組的價值在判準邏輯不在語言，對照重寫比憑空重想安全

**否決的替代方案：** 整套用 JS 重做。否決理由是工程書已經定案，
而且 daemon 的生態在 Python 這邊成熟。

**代價：** 兩套程式碼並存。用「JS 只做採集、Python 做判斷」的分工避免重疊。

**推翻條件：** 她要求單一語言，或 Code Duo 那邊是 JS 而必須共用執行環境。

---

## ADR-002　照妖鏡與 Token Monitor 去接，不重寫

**日期** 2026-09-08　**狀態** 已接受

**決策：** 這兩個能力已經在 Code Duo 實作。Forseti 寫 adapter 去接。

**理由：** 她的原話「照妖鏡跟 Token Monitor 都在 Code Duo 那邊」。
工程書 Evidence Basis 列的十四個既有專案就是資產清單，
重寫等於 `bible.md` R-02 記的那個錯誤。

**代價：** 十四題的第 1 到 3 題（Context 有多少、多少有效、多少污染）
要等接口，在那之前答不了，不准自己造一個假的來填。

**推翻條件：** Code Duo 那邊的介面拿不到，或它的資料模型與這裡不相容。

---

## ADR-003　hook 只採集，daemon 才判斷

**日期** 2026-09-08　**狀態** 已接受

**決策：**

```
Claude Code ──> forseti hook (JS, 短命程序)
                  只做：timestamp / 計數 / append / 檔案 stat+hash
                  ↓ append-only
              .forseti/event_ledger.jsonl
                  ↓
              forsetid (Python daemon)
                  做：所有判斷、回答十四題
```

**理由：** hook 每次都是新 process，約 130ms 啟動成本，不能做重的事。
它唯一必須即時做的是 Evidence Receipt，因為檔案大小與內容指紋
事後就永遠拿不到了（Formal Spec FS-TMP-001）。

**熱路徑硬約束：** hook 內禁止跨程序呼叫、禁止任何模型呼叫。
p95 目標 < 50ms，量出來要寫進 `PHASE_STATUS.md`。

**推翻條件：** 實測發現 append 本身就超出預算，那要改成環形緩衝或共享記憶體。

---

## ADR-004　人與 AI 平等記錄

**日期** 2026-09-08　**狀態** 已接受

**決策：** 事件帳本裡人的訊息與 AI 的訊息是平等的一等公民，
各有分類欄位。人的訊息至少分出：新要求、澄清、改變主意、糾正、確認。

**理由：** 她的原話：「在評估 AI 是否飄移的時候，我們也要去紀錄跟分析
用戶是在什麼情況下用什麼樣的方式去回應，這樣才不會讓整件事情看起來
單方面都是 AI 產生飄移的問題，而人卻沒有。」

**關鍵區別：** 改變想法與糾正必須分開。前者是她的權利
（Formal Spec 的 `OWNER_GOAL_CHANGE`，明令不算 drift），後者才是 AI 的失誤。

**已知後果：** 2026-09-08 算出的「UNSUPPORTED 後面接強烈反應率是 NORMAL 的
3.8 倍」這個數字不能用，因為沒有做這個區分。要重做。

**推翻條件：** 無。這條是 Formal Spec FS-GOL-002 的直接要求。

---

## ADR-005　控制檔進版控

**日期** 2026-09-08　**狀態** 已接受

**決策：** `.forseti/` 底下的 NORTH_STAR、PHASE_STATUS、DECISION_LEDGER、
BLOCKERS、REQUIRED_READING 進版控。執行期狀態
（state.json / streak.json / declarations.json / event_ledger.jsonl）繼續忽略。

**理由：** 控制檔是給下一個 session 讀的，不在版控裡就等於不存在。
`.gitignore` 裡原本就記著一次同型事故：搬碟的時候整個 `.forseti/`
被忽略，`goal.json` 沒跟過來，離題偵測在新位置是關的，而且完全靜默。

**推翻條件：** 無。

---

## 被否決的做法（留著避免重議）

| 做法 | 否決理由 | 日期 |
|---|---|---|
| 先做時序視覺化 / X-Ray 畫面 | 工程書 Phase 0 明令不做 UI。沒有事件帳本之前畫什麼都是假的 | 2026-09-08 |
| 繼續精進現有 detector | 實測有系統性假陽性，且沒有正確輸入 | 2026-09-08 |
| 用 CB / PS / drift 分數去挑校準樣本 | 循環論證，是 Formal Spec 的 FP-05 Evidence Independence Collapse | 2026-09-08 |
| 用字串比對產生 finding | 40 個 healthy session 實測每千則命中 242 次，40/40 全中 | 2026-09-08 |
| 把「規格條款符合數」當完成度 | 那是過程指標。是 Formal Spec 的 FP-08 Goal Metric Substitution | 2026-09-08 |

---

## ADR-006　C 線與主線並行，不合併也不取代

2026-09-08。

### 決定

Context 連續性子系統（C0-C5）作為獨立的一條線，跟主線六階段並行推進。
兩條線共用 `.forseti/` 控制檔與 `forseti` 指令，但階段各自獨立。

### 為什麼不合併進主線

它們處理的是兩種不同的失效：

主線問「這個 AI 有沒有偏離目標、有沒有在唬爛」。它假設 AI 還記得目標。

C 線問「這個 AI 還記不記得目標」。壓縮之後它可能連目標是什麼都不知道了，
而它不會察覺，因為遺忘不會留下空格。

合併的話會出現一個荒謬：用一個已經忘記北極星的 AI，去偵測自己有沒有偏離北極星。

### 為什麼不取代主線

C 線解決的是「記得」，不解決「誠實」。一個記憶完整的 AI 照樣可以宣稱
它沒做過的事。照妖鏡那條路仍然要走。

### 依賴關係

C0 是獨立的，已完成。
C3 需要主線 ADR-002 的照妖鏡接入。
C5 的指紋切片需要主線階段 3 的人與 AI 雙向記錄。

所以兩條線在 C3 之後會交會，但在那之前互不阻塞。

### 被否決的替代方案

把 C 線做成主線的階段 6。否決理由是它會排在階段 5 之後，
而使用者現在就在受壓縮的苦，等不到那時候。

先做一個 handoff.md 產生器。否決理由是那還是塞，見設計文件不變量二。
這條路先前試過，撐不過六個 session。

### 推翻條件

如果 C1 的索引在真實使用中查不出東西，或者助理的回覆品質差到
不如直接讀原文，那整條線的前提就不成立，該停下來重新想。

---

## ADR-002 補充　「Code Duo」指的是哪一份檔案（2026-09-09）

**問題：** 有兩個目錄，而且不同。

```
~/Code-Duo/app.py              1642 行  2026-09-02  md5 11a9f4cf
~/code-matrix-rebuild/app.py   1746 行  2026-09-03  md5 ced1cfc5
```

**實際在跑的是 `~/code-matrix-rebuild/app.py`。**
`~/.claude/launch.json` 的 `code-duo` 設定指向它，port 8765。
`~/Code-Duo` 是 git repo，用來版控，不是每天在改的那份。

memory 的 `code_matrix_repo_split_trap` 早就記了這件事：
天天改的 `~/code-matrix-rebuild` 沒有 git，repo 在 `~/Code-Duo`。

**2026-09-09 我讀錯了那一份。** 讀的是 `~/Code-Duo/app.py`，
並且把行號寫進 `BLOCKERS.md` 與 `docs/context-continuity.md`。
兩份差 104 行，同名函式的行號差 61：

| 函式 | ~/Code-Duo | ~/code-matrix-rebuild |
|---|---|---|
| `token_stats` | 1154 | 1215 |
| `check_honesty` | 1268 | 1329 |
| bluff 判定 | 1307 | 1368 |
| `record_behavior` | 1321 | 1382 |

出處已更正。機制本身沒有讀錯，兩份的那幾個函式邏輯相同，
新版只多了 `_session_name` 與 `read_ssh_hosts`，跟照妖鏡無關。

**教訓：** 讀一個外部專案之前先確認哪一份是活的。
`launch.json` 或 `ps` 會告訴你，猜不會。
這次沒有造成錯誤結論，只是出處錯，但下一次可能不會這麼好運。

---

## 待裁決　工程書與現行實作的六條分歧（2026-09-09）

來源是六份讀後對照（`docs/reading/`），由六個 worker 分段讀 AI-First
工程書並逐條對照 repo，主 session 抽驗 19 條，全部屬實。

**這六條都是「接手的 session 不准自己決定」等級的。** 放在這裡不是
拖延，是因為每一條選哪邊都會影響後面很久，而且兩邊各自都有道理。
在有裁決之前，動到那一塊的人請先回來看這一節。

### 一　Phase 0 VERIFIED 同名不同義

`PHASE_STATUS.md:9` 的 VERIFIED 是照 `docs/build-plan.md` 第五節驗的，
2026-09-09 真的用新 session 驗過出口。書 401 行要求的 VERIFIED 是它
第 9.2 節那七條全數完成，而七條裡有四條半沒做（HANDOFF.md、
policies.yaml、Pydantic models、fixture manifest，加上不是 pytest）。

**風險：** 拿 A 定義的驗收去蓋 B 定義的章，然後據此動 Phase 1。

**兩條路：** 以書為準補齊缺項；或記一條 ADR 說明本專案的 Phase 0
定義取代書的定義。

### 二　「事件帳本」即將撞名

書 Phase 1 的 event ledger 是 provider 行為事件（445-450 行六類：
Dialogue / Tool / Runtime / Artifact / Usage / Governance）。
現有 `ledger.py` 的 events 表是派工協調事件（`WORKER_*` 八種）。
兩者都叫 ledger、都有 events 表、都在講事件。

**風險：** 做 Phase 1 時直接往 `ledger.py` 的表裡塞 provider 事件；
或接手的 session 以為 `ledger.py` 就是 Phase 1 的事件帳本而標記已做。

**2026-09-10 補充，v5.0 §6/§20 讀完之後，這條的選項本身變了。**

v5.0 §6 的 event ledger 跟工程書 Phase 1 的是同一種東西（provider 行為
事件），這點已經確認：175 行第一句就是「Every provider-native event is
stored twice」，`RawEvent` 的必要欄位是 `provider, provider_event_type`
（177-179 行），派工事件裝不進那個結構。所以撞名是真的。

**但 v5.0 自己的設計不是分庫，是「單一帳本容納兩類，用分類與分表區隔」。**
§6.2 的八大類裡有 Workflow 一類（194 行：`STEP_START`、`STEP_COMMIT`、
`STEP_ROLLBACK`、`APPROVAL_REQUESTED`），那正是派工協調那一族；
§20.2 又把 `workflows`、`workflow_steps` 與 `events`、`raw_events`
列在同一個資料庫（558-559 行）。照 v5.0 走，派工步驟事件會以 Workflow
分類進同一本 normalized 帳。

**所以要決定的是這兩條路：**

一，照 v5.0 合一。`ledger.py` 的 `tasks`/`steps` 大致對應 v5.0 的
`workflows`/`workflow_steps`，但它的 `events` 表要改造成 §6.1 的
NormalizedEvent 結構，現有欄位對不上，等於重寫加資料遷移。

二，分開。與 §20.2 的單庫清單字面不符，但保住已實測過的派工帳本。
而且實體上已經半分開了：派工帳本因 exFAT 限制在 `~/.forseti/ledgers/`，
行為事件帳本照 ADR-003 會是 `.forseti/event_ledger.jsonl`，本來就不同地方。

**不管選哪邊，「`events` 這個名字給誰」都要寫成 ADR**，沒有明文的話
上面那兩個風險會一直在。

### 三　Pydantic 對零依賴

書 389 行明定用 Pydantic domain models。現行 Python 模組的設計約束是
零依賴，寫在 `ledger.py:31` 與 `forseti.py` 檔頭。六條 ADR 沒有任何
一條裁過依賴政策（ADR-001 只裁了 Python 對 JS）。

**這是真的二選一：** 遵守書就要引入第三方依賴，遵守現行慣例就永遠
不會有 Pydantic。

### 四　NPG 公式對「拒絕相減」

書 919-932 行要求把效益與成本加減成一個淨值。
`test/overhead.test.mjs` 第 2 行逐字寫著：「負擔可以量，效益只能估，
而這個模組拒絕把兩者相減。」

**這不是漏做，是 repo 端刻意做了相反的決定。** 照書實作 NPG 就要
推翻那個立場；維持那個立場，書的 NPG 就得降級成概念框架而不是
要算出來的數字。

### 五　證據分級四套並存

| 出處 | 分級 |
|---|---|
| 工程書 344-352、889-897 | 五級，多一個 COUNTERFACTUAL |
| `src/evidence.js:36-39` | 四級，v2 規格書的 OBSERVED/DECLARED/INFERRED/MISSING |
| `src/conformance.js:32` | v1 的 EPISTEMIC 序列 |
| `tools/save-case.py` | 第四套，用 `MODEL_SELF_REPORT` |

四套的精神一致（低級不得冒充高級），但要照書實作 fixture 之前，
五級與現有分級的對映必須先決，否則同一份材料會有兩個等級標籤。

### 六　§27 的 HANDOFF 模板對「handoff 是文字就會失效」

書 §27 要求每個 session 產出一份文字交接模板。
`DECISION_LEDGER.md:162-163` 已經否決過 handoff.md 產生器，理由是
「那還是塞」「這條路先前試過，撐不過六個 session」。
`bible.md` H-01 記著她的原話：handoff 是文字就會失效，要是可驗證狀態。

**精神其實一致**（書 1003 行自己也說交接不是證據的替代品），
分歧在形式：書要一份模板檔，repo 選了控制檔集合加 doctor 加帳本。
缺的是一條 ADR 寫明「我們用什麼取代 §27 模板、模板裡哪幾欄因此沒人記」。

### 不必裁決但要知道的三件事

`src/rescue.js` 檔名撞書的 Phase 7，但它是 spec v0.1 §7 的中斷前快照；
書 Phase 7 的對應物在 `src/recovery.js`。用檔名對照書的人會對錯位。

`src/thermometer.js` 量的是「查過的對自己生出來的」比例，不是健康溫度。
接書 Phase 8 的 UI 時把它接到體溫那個位置，會把事實比例當健康度顯示。

書的章節號與 `docs/spec-v2.0.md` 是兩套系統（書 §16 Phase 7 ≈
spec-v2.0 §17）。repo 程式碼註解裡的 § 編號一律指 spec-v2.0。
