# 工程書第 9-11 節（Phase 0 到 Phase 2）讀後對照

讀的檔案：`docs/sources/Forseti_AI_First_Development_Engineering_Book_v1.0_2026-09-07.md` 第 372 到 508 行。
逐行完整讀取，不是 grep 出來的。本文所有行號都指那份檔案。

這一段就是 `.forseti/REQUIRED_READING.md` 第 64 行標的「動階段 1 之前必須補 Phase 1-2」的缺口。
寫這份的日期：2026-09-09。對照的 repo 狀態以當天工作目錄為準。

對照時有查證過的檔案才寫路徑；沒查到的直接寫「沒有」；查了但不足以下定論的標「未驗證」。

---

## 一、這幾節規定了什麼（逐條附行號）

### 第 9 節　Phase 0：Bootstrap、Ground Truth、AI 執行契約（372-408）

9.1 Phase Charter（374-383）：

| 行號 | 規定 |
|---|---|
| 378 | 目標：做出一個 repo，任何接手的 AI 不靠對話記憶，就能從檔案認出當前 phase、真相、決策、阻塞、下一步 |
| 379 | 範圍內：repo 骨架、schemas、canonical docs、fixture 慣例、CI、versioning |
| 380 | 明確排除：不做 provider 整合、不做 health score、不做 UI |
| 381 | 交付物：repository、`.forseti` 控制檔、domain package 骨架、schema tests |
| 382 | 出口條件：全新 AI session 跑 `forseti doctor`（stub 可），能從檔案正確報出專案身分、當前 phase、version、缺哪些前置 |
| 383 | 停止條件：canonical docs 缺少或互相矛盾、repo 狀態無法驗證、phase 邊界模糊，就不准繼續 |

9.2 Exact tasks（385-393），七條：

| 行號 | 規定 |
|---|---|
| 387 | 依第 6 節建立 repo 結構（第 6 節在本次讀取範圍之外，見第二部分的說明） |
| 388 | 建立 NORTH_STAR.md、PHASE_STATUS.md、DECISION_LEDGER.md、BLOCKERS.md、HANDOFF.md、policies.yaml |
| 389 | 實作初始 Pydantic domain models，帶 schema_version |
| 390 | 建立 migration framework 與空的 SQLite 資料庫初始化器 |
| 391 | 建立 pytest smoke tests：schema 序列化、資料庫 reopen |
| 392 | 加 `forseti status` 與 `forseti doctor`，輸出必須是 deterministic |
| 393 | 建立 historical-incidents 的 fixture manifest 格式；此階段不解析 sessions 本身 |

9.3 Required evidence artifacts（395-401），五項：pytest 報告（397）、repo tree snapshot（398）、SQLite migration version（399）、canonical 控制檔的 hash（400）、PHASE_STATUS 顯示 Phase 0 VERIFIED 才准轉移（401）。

9.4 Prohibited behaviors（403-408），四條：不做 desktop UI（405）、不加 LLM 依賴（406）、不宣稱某個 detector 有效（407）、不准為了實作方便改寫北極星（408）。

### 第 10 節　Phase 1：Capture Plane 與可重放事件帳本（410-457）

10.1 Phase Charter（412-421）：

| 行號 | 規定 |
|---|---|
| 416 | 目標：把 provider 與 runtime 行為捕捉成持久的 raw 加 normalized 事件，讓 Forseti 從外部行為推理，不是從隱藏思考推理 |
| 417 | 範圍內：先做一個 provider adapter（選 local fixture 最豐富的）、通用 JSONL importer、檔案系統／process／基本 usage 事件 |
| 418 | 明確排除：不做健康診斷、不做語意分析、不做自動干預 |
| 419 | 交付物：RawEvent store、NormalizedEvent store、importer、adapter fixtures、replay 指令、EventGap 表示法 |
| 420 | 出口條件：一個被捕捉的 session 能 ingest、daemon 重啟後 replay，事件數量與順序 deterministic，raw 與 normalized 有連結 |
| 421 | 停止條件：provider schema 無法可重現地捕捉、normalization 毀掉 raw 證據、事件遺失是無聲的 |

10.2 Adapter 契約（423-439）：六個方法，`discover_sources()`（427）、`stream_raw_events()`（429）、`normalize(raw_event)`（431）、`identify_session()`（433）、`capabilities()`（435）、`checkpoint_cursor()`（437）。

10.3 Canonical 事件分類（441-450），六類：

| 行號 | 類別 | 例子 |
|---|---|---|
| 445 | Dialogue | USER_MESSAGE、ASSISTANT_MESSAGE、EMPTY_RESPONSE、RESPONSE_COMPLETE |
| 446 | Tool | TOOL_REQUEST、TOOL_START、TOOL_RESULT、TOOL_ERROR、TOOL_CANCEL、TOOL_TIMEOUT |
| 447 | Runtime | PROCESS_START、PROCESS_EXIT、HEARTBEAT、SESSION_START、SESSION_END |
| 448 | Artifact | FILE_READ、FILE_WRITE、FILE_DIFF、GIT_STATE |
| 449 | Usage | TOKEN_SAMPLE、COST_SAMPLE、CONTEXT_SAMPLE |
| 450 | Governance | CORRECTION、POLICY_DECISION、CHECKPOINT、INCIDENT |

10.4 Acceptance tests（452-457），四條：同一 fixture ingest 兩次不重複產生 canonical 事件（454）、importer 中途 crash 能從 cursor 續跑且不弄壞序列（455）、未知 provider 事件保留 raw payload 並 normalize 成 UNKNOWN_EVENT 而非丟棄（456）、刻意刪掉一段序列要產生 EventGap 且後續 causal completeness 要下降（457）。

### 第 11 節　Phase 2：Runtime Thermometer v0，只用事件（459-507）

11.1 Phase Charter（461-470）：

| 行號 | 規定 |
|---|---|
| 465 | 目標：只從事件行為產生被動的健康溫度，不讀 session 語意 |
| 466 | 範圍內：windowed metrics、baseline 校準、anomaly features、health samples、CLI 顯示 |
| 467 | 明確排除：不宣稱溫度能找出根因、不做人類情緒推斷 |
| 468 | 交付物：health engine、feature extractor、baseline store、temperature sample 流、replay 報告 |
| 469 | 出口條件：歷史上「明顯正常」與「明顯卡死」的 fixtures 要產生可分離的 feature 軌跡；報告要解釋哪些 feature 貢獻了分數，且不做語意宣稱 |
| 470 | 停止條件：分數被單一任意指標主宰、正常的工具密集工作持續被誤標、閾值無法 replay 與校準 |

11.2 Event-only features（472-485），十個：tool_call_rate（476）、tool_duration_p95 / max（477）、tool_to_visible_output_ratio（478）、blank_response_count / streak（479）、answer_length_delta（480，明寫是弱訊號）、retry_similarity（481）、artifact_change_rate（482）、time_since_last_verified_progress（483）、human_message_rate after agent actions（484，語意判讀延後）、cancel/ESC frequency（485）。

11.3 溫度模型（487-503）：

| 行號 | 規定 |
|---|---|
| 489 | 不准把醫學語意硬編進數字分數。內部算 0-100 的 anomaly/instability 分數，再映射成體溫給 UX。初始映射是校準假設，要版本化放在 policy 裡，不是科學事實 |
| 491 | `instability_score = weighted_normalized_features(features, baseline_profile)` |
| 493 | `temperature = 36.3 + 5.0 * sigmoid((instability_score - center) / scale)` |
| 495-501 | 36.x 正常、37.x 觀察、38.x 退化、39.x 以上強烈注意 |
| 503 | 絕不准只憑溫度推斷失敗原因 |

11.4 Productivity requirement（505-507）：這一階必須 benchmark Forseti 自身的 overhead。觀測層若明顯拖慢日常工作，不准前進到更聰明的分析，先修捕捉與彙整。

---

## 二、對照 repo 現況（重點段落，逐條驗過）

### Phase 0 的七條 exact tasks

1. 依第 6 節建 repo 結構（387）：無法逐條比對。第 6 節不在這次指定的讀取範圍（372-508）內，我沒有讀它，不猜。現有頂層結構是 `.forseti/`、`apps/forseti-cli/`、`src/`、`test/`、`tests/`、`tools/`、`adapters/`、`hooks/`、`docs/`、`example/`。是否符合第 6 節，要等補讀第 6 節後另行對照。

2. 六份控制檔（388）：四份有，兩份沒有。
   - 有：`.forseti/NORTH_STAR.md`、`.forseti/PHASE_STATUS.md`、`.forseti/DECISION_LEDGER.md`、`.forseti/BLOCKERS.md`
   - 沒有：HANDOFF.md。`ls .forseti/HANDOFF.md` 回 No such file。注意 `apps/forseti-cli/forseti.py:981` 有一個 `cmd_handoff`，那是跨 session 派工指令（B-09 的解法），跟書上說的交接文件是兩回事，名字撞了而已。
   - 沒有：policies.yaml。整個 repo `find` 不到這個檔名。
   - 另外 `.forseti/` 裡有書上沒列的檔：REQUIRED_READING.md、goal.json、state.json、streak.json、inbox/。多出來的不算違規，書上沒禁止。

3. Pydantic domain models 帶 schema_version（389）：沒有。`grep pydantic|BaseModel` 在 `apps/forseti-cli/` 與 `src/` 都是零命中。現行 Python 模組刻意零依賴（`apps/forseti-cli/ledger.py:31` 自己寫明「零依賴。sqlite3 是標準庫」）。有 schema 版本概念但在 SQLite 層：`ledger.py:173` 的 `SCHEMA_VERSION = 3` 與 `recall.py:267` 的 `SCHEMA_VERSION = 3`，用 `PRAGMA user_version` 存。這不是書上說的 domain model 的 schema_version 欄位。衝突細節見第三部分。

4. Migration framework 與 SQLite 初始化器（390）：部分有。`ledger.py:215-232` 讀 `PRAGMA user_version` 比對 `SCHEMA_VERSION`，`ledger.py:255-262` 的 `connect()` 會建表並寫版本；`recall.py:273-279` 版本不合會重建。這是「版本檢查加重建」，是不是書上要的 migration framework（逐版遷移）我沒有逐行驗它的升級路徑，標未驗證。另外資料庫不在 repo 裡，在 `~/.forseti/ledgers/`，原因是這個 repo 放在 exFAT 外接碟，exFAT 不支援 sqlite 需要的 POSIX advisory lock（`ledger.py:240-241` 記了實測失敗）。這一點對書的精神有張力，見第三部分。

5. pytest smoke tests：schema 序列化與 DB reopen（391）：測試有，但不是 pytest。`tests/` 有十一個 Python 測試檔（test_ledger.py、test_forseti_cli.py、test_context_meter.py、test_recall.py、test_f03 到 f08），`grep "import pytest"` 全部零命中，跑法是 `python3 tests/test_fXX.py`（PHASE_STATUS.md 記錄的驗收指令）。reopen 這個行為有測到：`tests/test_ledger.py:50` 定義 `reopen()`，第 108、208、215、226 行都用「全新 Ledger 物件等於全新 session」來驗。schema 序列化的專門測試我沒有找到對應檔案，不確定有沒有涵蓋，標未驗證。

6. `forseti status` 與 `forseti doctor`，deterministic 輸出（392）：兩個指令都有，`apps/forseti-cli/forseti.py:400`（status）與 `:311`（doctor）。出口條件（382）大部分驗過：PHASE_STATUS.md 第 47-58 行記錄 2026-09-09 用 `claude -p` 開全新 session 實測，doctor 報出北極星、當前階段、未讀清單、阻塞四件事，完整記錄在 `docs/cases/doctor-handover-2026-09-09.md`。兩個缺口：
   - 書上第 382 行要求報 version，doctor 沒有報任何專案 version（`grep version apps/forseti-cli/forseti.py` 零命中）。
   - deterministic 不完全成立：`cmd_doctor` 會讀帳本的 active steps 並印「幾分鐘沒動靜」（forseti.py:311 起那段），這是時間相依的輸出。從控制檔讀的部分是 deterministic 的，帳本那段不是。

7. historical-incidents fixture manifest 格式（393）：沒有。`find -iname "*fixture*"` 整個 repo 零命中。`docs/cases/` 底下有九份事故與判例文件（例如 `2026-09-07-誠信違規總帳.md`、`owner-adjudications.md`），是敘事文件，不是 manifest 格式；沒有任何機器可讀的 incidents 清單格式定義。

### Phase 0 的五項證據（9.3）

| 要求（行號） | 現況 |
|---|---|
| pytest 報告（397） | 沒有 pytest。有測試通過的記錄（PHASE_STATUS.md 的 F 線表格記各檔測試數與 exit 0），但沒有保存下來的測試報告產物 |
| repo tree snapshot（398） | 沒有找到。repo 裡沒有任何 tree snapshot 檔案 |
| SQLite migration version（399） | 有，`PRAGMA user_version = 3`（ledger.py:173、recall.py:267） |
| 控制檔 hash（400） | 沒有。REQUIRED_READING.md 第 73-75 行自己承認「沒有版本指紋，來源改了不會有人發現」，並指向 Vol2 第 10 節的 content-addressable evidence store，還沒做。已有的 hash 只有九份 Modular Spec 源文件的 sha256（REQUIRED_READING.md 第 159-169 行），不含 .forseti 控制檔 |
| PHASE_STATUS 顯示 Phase 0 VERIFIED（401） | 字面上有：PHASE_STATUS.md 第 9 行「階段 0：控制檔與接管閘門　狀態 VERIFIED」。但那個 VERIFIED 驗的是 build-plan 的階段 0 定義，不是書上 9.2 的七條，見第三部分第 1 條 |

### Phase 0 的四條禁令（9.4）

| 禁令（行號） | 現況 |
|---|---|
| 不做 desktop UI（405） | 沒做 desktop UI。`docs/design/thermostat.html` 是設計稿，`tools/dashboard.html` 加 `tools/dashboard.mjs` 是離線分析的視覺化頁面。後者算不算踩線見第三部分第 7 條 |
| 不加 LLM 依賴（406） | `apps/forseti-cli/` 零依賴，符合。`src/` 那四十個 JS 模組我沒有逐一查依賴，標未驗證 |
| 不宣稱 detector 有效（407） | 符合，而且反向記錄了：PHASE_STATUS.md 第 220-223 行明寫「不要精進現有的 detector，它們有實測的系統性假陽性」；`docs/calibration/` 有四份校準文件記錄假陽性實測 |
| 不為實作方便改北極星（408） | 符合。REQUIRED_READING.md 第 135-143 行記錄了 NORTH_STAR.md 單向與 Vol1 雙向的差異，並明令「要 owner 拍板，接手的 session 不准自己改」 |

### Phase 1 對照（第 10 節）

Phase 1 整體是 NOT_STARTED（PHASE_STATUS.md 第 68 行，階段 1 事件帳本），而且補讀門檻未達標（REQUIRED_READING.md 第 208 行），這份文件本身就是在補那個門檻的一部分（工程書 Phase 1 這節讀完了，v5.0 §6 與 §20 還沒補）。

書上交付物逐項對：

| 交付（419） | 現況 |
|---|---|
| RawEvent store | 沒有。沒有任何持久化的 raw 事件儲存 |
| NormalizedEvent store | 沒有 |
| 通用 JSONL importer | 沒有書上定義的那種（帶 cursor、可續跑、冪等）。相近但不是的東西有兩個：`apps/forseti-cli/context_meter.py` 會掃 session jsonl 讀 usage 欄位（一次性讀取，不落事件）；`apps/forseti-cli/recall.py` 把 jsonl 切段建 FTS5 索引（是搜尋索引，不是事件帳本） |
| adapter fixtures | 沒有。`find -iname "*fixture*"` 零命中 |
| replay 指令 | 沒有。`grep replay` 只命中 `adapters/claude-code.mjs` 的函式名以外零處，CLI 沒有 replay 子指令 |
| EventGap 表示法 | 沒有。`grep EventGap` 全 repo 零命中 |

10.2 的 adapter 契約：`adapters/claude-code.mjs` 是最接近的現有物，有 `lineToRawEvents()`（第 58 行）、`parseTranscripts()`（第 100 行）、`parseTranscript()`（第 192 行）。它是離線批次解析器，不是書上的 streaming adapter；六個契約方法裡 `discover_sources`、`stream_raw_events`、`identify_session`、`capabilities`、`checkpoint_cursor` 都沒有對應實作（grep 零命中），只有 normalize 的概念部分對應到 `lineToRawEvents`。

10.3 的六類事件：沒有實作這套分類。`ledger.py:163` 有一張 `events` 表，但存的是派工協調事件（`ledger.py:176-179` 的八種 WORKER_EVENTS：WORKER_ACCEPTED、WORKER_PROGRESS、WORKER_COMPLETION、WORKER_BLOCKED、WORKER_FAILED、WORKER_CANCELLED、EVIDENCE_AVAILABLE、ARTIFACT_CHANGED，加控制端的 TASK_STATE、DISPATCH、REASSIGN），跟書上第 445-450 行捕捉 provider 行為的六類是不同用途的東西。名字都叫 event ledger，見第三部分第 2 條。

10.4 的四條驗收測試：全部沒有，因為被測的東西本身還不存在。

### Phase 2 對照（第 11 節）

先講對映：書的 Phase 2 到 4 對應 repo 六階段裡的「階段 4 健康與退化」（REQUIRED_READING.md 第 211 行），PHASE_STATUS.md 第 71 行標 NOT_STARTED，補讀門檻同樣未達標。

書上交付物逐項對：

| 交付（468） | 現況 |
|---|---|
| health engine | 書上定義的那種（事件流上的 windowed metrics）沒有。`src/signals.js` 有一個 composite 溫度（0 到 1 加權平均加燈號封頂），但它屬於離線分析層，輸入是 transcript 事後解析，不是即時事件流 |
| feature extractor | 沒有書上這種。`src/` 有若干 detector 各自算特徵，未逐一比對十個 feature，標未驗證 |
| baseline store | 沒有驗證過的對應物。`src/baseline.js` 檔名吻合但我沒有讀它的內容，不確定是不是書上說的 baseline profile 儲存，標未驗證 |
| temperature sample 流 | 沒有 |
| replay 報告 | 沒有 |

11.3 的溫度公式：完全沒有實作。`grep "36\.3|sigmoid"` 在 src/、tools/、apps/、docs/design/ 全部零命中。`docs/design/thermostat.html` 是體溫計的介面設計稿，不含公式實作。`src/signals.js` 的 temperature 是 0 到 1 的加權平均，跟書上 0-100 instability 映射到 36.3 起跳的體溫是兩套不同設計，見第三部分第 5 條。

11.2 的十個特徵，現有的零散對應（都不是書上要的「事件流上的 windowed metric」形式）：
- blank_response_count（479）：`apps/forseti-cli/starvation.py` 實作的是 F07 的空輸出「結果保全」機制（ResultReceipt），是防治不是量測，方向相關但不是這個 feature。
- cancel/ESC frequency（485）：`src/signals.js` 的 S9 取消壓力訊號存在（signals.js 第 229 行附近的註解），屬離線層。
- 其餘八個：沒有找到對應實作。`docs/calibration/` 的四份文件（string-signals-verdict、healthy-negatives、turn-classification、cross-engine）是對舊 detector 的假陽性校準記錄，是給未來 feature 設計的地基，不是 feature 實作。

11.4 的 overhead benchmark：沒有針對「Forseti 觀測層拖慢日常工作多少」的 benchmark。相近的數字只有 C0 的一次實測（PHASE_STATUS.md 第 103-112 行：236 份 session 全掃 10.0 秒），那是索引可行性證明，不是持續性 overhead 量測。`src/overhead.js` 檔名吻合但內容未讀，標未驗證。

---

## 三、衝突與矛盾

1. 「Phase 0 VERIFIED」同名不同義，這是最重要的一條。PHASE_STATUS.md 第 9 行的 VERIFIED 是照 `docs/build-plan.md` 第五節的階段 0 定義驗的（控制檔加 doctor 加接管閘門，且 2026-09-09 真的用新 session 驗過出口）。但書上第 401 行要求的「PHASE_STATUS showing Phase 0 VERIFIED before transition」指的是第 9.2 節那七條全數完成後的 VERIFIED，而七條裡有四條半沒做（HANDOFF.md、policies.yaml、Pydantic models、fixture manifest，加上不是 pytest）。如果有人拿 PHASE_STATUS.md 的 VERIFIED 直接當成書上 Phase 0 的通行證去動 Phase 1，就是拿 A 定義的驗收去蓋 B 定義的章。兩邊都是誠實的，衝突在於同一個詞指兩套驗收標準，需要 owner 決定：以書為準補齊缺項，還是在 DECISION_LEDGER 記一條 ADR 說明本專案的 Phase 0 定義取代書的定義。

2. 「事件帳本」一詞已經被佔用。書 Phase 1 的 event ledger 是 provider 行為事件（第 445-450 行六類），現有 `ledger.py` 的 events 表是派工協調事件（WORKER_* 八種）。兩者都叫 ledger、都有 events 表、都在講事件。將來做 Phase 1 時如果直接往 `ledger.py` 的表裡塞 provider 事件，或者接手的 session 以為 ledger.py 就是 Phase 1 的事件帳本而標記「已做」,兩種都會出事。這不是既有實作的錯,是命名空間即將相撞,動 Phase 1 之前要先明確分開（不同資料庫、或至少不同表與不同文件名義）。

3. Pydantic（389）與零依賴慣例直接衝突。書明定用 Pydantic；現行 Python 模組的設計原則是零依賴，寫在 `ledger.py:31`，而 DECISION_LEDGER.md 的六條 ADR 裡沒有任何一條裁過這件事（ADR-001 只裁了 Python 對 JS，沒裁依賴政策）。遵守書就要引入第三方依賴，遵守現行慣例就永遠不會有 Pydantic。這要 owner 或一條新 ADR 拍板，接手的 session 不該自己選邊。

4. SQLite 位置與「真相在 repo」的精神有張力。書 Phase 0 的核心（378）是接手的人從 repo 檔案就能取得全部真相，但帳本實際放在 `~/.forseti/ledgers/`（home 目錄），因為 repo 所在的 exFAT 碟跑不了 sqlite 鎖（`ledger.py:240-241`，實測過的硬限制，不是偷懶）。後果：換一台機器、或 home 被清掉，repo 完好但任務狀態全沒了；doctor 報的「未完成義務」「有人正在做事」也是從 repo 外讀的。這是環境限制對書的原則的真實讓步，目前只記在 ledger.py 註解與 PHASE_STATUS.md 第 170 行，建議升格成一條 ADR 並想備援（例如定期把帳本快照回 repo）。

5. 兩套溫度並存。`src/signals.js` 已有一套 temperature（0 到 1 加權平均，燈號有 measured_weight 封頂機制），書 11.3 是另一套（0-100 instability 經 sigmoid 映射到 36.3 起跳的體溫）。兩套的輸入、量綱、映射都不同。ADR-001 已裁定 src/ 是離線參考實作不是主線，所以這不算活著的矛盾，但做 Phase 2 時要明確聲明舊 temperature 不是新 thermometer 的實作基礎，只有 signals.js 那些防呆教訓（沒量到的訊號不當 0、代表性不足要封頂、不准只憑使用者怒氣亮紅燈）值得搬過去，那些教訓跟書 470 行的停止條件「分數被單一任意指標主宰」是同一件事，方向一致。

6. doctor 少報 version（382）。書的出口條件要求報 project identity、active phase、version、缺的前置四樣，現行 doctor 報了三樣加上帳本狀態，唯獨沒有 version（repo 也沒有一個明確的專案版本號可報，package.json 是 hook 用的）。小缺口，但它屬於書的 exit gate 字面要求。

7. dashboard 與 UI 禁令的邊界。書 405 行禁的是 desktop UI，`tools/dashboard.html` 加 `dashboard.mjs` 是離線分析的網頁視覺化，`docs/design/thermostat.html` 是純設計稿。嚴格讀，兩者都不是 desktop UI，不違規；但 PHASE_STATUS.md 第 224 行自己的禁令寫的是「不要做任何 UI，工程書 Phase 0 明令禁止」，比書更嚴。現況是既成事實（dashboard 在 ADR-001 保留的 JS 離線層裡），兩條禁令的寬嚴不一致值得知道，接手的人別拿書的窄版去開新 UI 的門，repo 內部的禁令是寬版。

8. HANDOFF 一詞撞名。書 388 行的 HANDOFF.md 是控制檔（交接文件），`forseti handoff`（forseti.py:981）是跨 session 派工指令，`src/handoff.js` 又是離線層的另一個模組。三個 handoff 三種意思。補 HANDOFF.md 的時候要在檔內講清楚它跟指令的關係,不然下一個 session 會以為指令就是那份檔的實作。

---

## 給下一步的話

這份讀後對照補掉的是「工程書 Phase 0-2 沒讀」這個門檻的工程書部分。REQUIRED_READING.md 第 208 行的階段 1 門檻還有另一半：v5.0 架構規格的第 6 節與第 20 節（儲存架構），那份不讀完，階段 1 照樣不准動。

動 Phase 1 之前，第三部分的第 1、2、3 條至少要有裁決（Phase 0 定義誰說了算、事件帳本命名空間怎麼分、Pydantic 要不要），這三條都是「接手的 session 不准自己決定」等級的事。
