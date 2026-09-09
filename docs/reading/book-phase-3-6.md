# 讀書報告：AI-First 工程書 §12-15，Phase 3 到 Phase 6

寫於 2026-09-09。任務 T-7a5ae42356/s1。

源檔　`docs/sources/Forseti_AI_First_Development_Engineering_Book_v1.0_2026-09-07.md` 第 509 到 670 行。
本報告的行號全部指這個檔案。這一段我逐行讀完（Level 5）。

先講清楚範圍：全書 166,196 字，我這次只讀第 509 到 670 行。
`.forseti/REQUIRED_READING.md` 標整本書的讀取深度是 Level 3（約三成）。
所以「§12-15 跟書中其他章節有沒有互相引用或衝突」這件事，本報告答不了，沒讀就是沒讀。

對照現況的部分，列出的每個檔案我都親自開過（Read 或 sed 讀了關鍵段落，
grep 掃過全 repo 關鍵字），不是憑 PHASE_STATUS 的宣稱轉述。
但我沒有逐行讀完 40 個 JS 模組，讀的是每個相關模組的檔頭說明與關鍵函式，
所以「某功能不存在」的判定依據是全 repo grep 沒有命中加上相關模組讀過沒看到，
標「沒有」的地方如果之後被推翻，最可能的原因是功能藏在我沒逐行讀的模組深處。

---

## 一、這幾節規定了什麼

### §12　Phase 3：Suspicious Window Locator（行 509-538）

12.1 Phase Charter（行 511-520）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 515 | 找出值得語意檢視的小時間窗，不把整個 session 餵 LLM |
| In scope | 516 | 窗口評分、切段、事件指紋、錨點擴張、檢索 API |
| Out of scope | 517 | 不做全 session LLM 摘要，不做診斷 |
| Deliverables | 518 | SuspiciousWindow 實體、locator engine、CLI list/export、確定性排序測試 |
| Exit gate | 519 | 用歷史 fixture 驗：已知工具迴圈與糾正周圍的高訊號窗要進 top-k，語意 payload 只佔全文一小部分 |
| Stop 條款 | 520 | top-k 跟隨機沒差、locator 需要全文才能動、選出的窗設計上就漏掉因果前導，三者任一成立就停 |

12.2 窗口發現邏輯，六步（行 522-534）：

1. 依「事件數與時間」分割，不依 token 數（行 524）
2. 每窗算行為異常特徵（行 526）
3. 對 session 早期的健康基線找變點（行 528）
4. 加錨點：人為糾正、工具逾時、取消、重複錯誤、狀態跳變（行 530）
5. 選中的窗前後有界擴張脈絡（行 532）
6. 持久化 window ID 加精確 event refs，讓分析可重現（行 534）

12.3 取樣預算（行 536-538）：語意 payload 預算必須明講，例如 top 5 窗、
每窗不超過 N 個事件或設定的字元/token 數。超了就排得更嚴，絕不靜默吞整個 session。

### §13　Phase 4：Targeted Semantic Analysis 與協作健康（行 540-566）

13.1 Phase Charter（行 542-551）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 546 | 只用可疑窗與關鍵錨點，分類協作為何退化，特別是 human-as-QA 與被動重複行為 |
| In scope | 547 | 針對性文字分類、糾正抽取、主動性/協作特徵、信心與證據標籤 |
| Out of scope | 548 | 不自主封鎖，不做情緒診斷 |
| Deliverables | 549 | semantic analyzer 介面、協作樣本、糾正候選、帶證據連結的分類 |
| Exit gate | 550 | 歷史窗能分類出重複病徵且附證據 ref；不確定的窗保持 UNKNOWN；payload 守預算 |
| Stop 條款 | 551 | 模型解釋沒有 provenance 就存、把髒話當技術失敗的證據、需要全文，三者任一成立就停 |

13.2 六個協作病徵與其可觀察證據組合（行 553-562）：

| 病徵 | 行號 |
|---|---|
| Human-as-QA inversion（糾正密度高 + 重複的補漏指示 + AI 宣稱完成後被返工） | 557 |
| Agent passivity（使用者微指令變多 + 自主驗證變少 + 輸出變短變不完整） | 558 |
| Instruction repetition（同一個北極星/目標/糾正在窗內被重講多次） | 559 |
| Output starvation（有做事的事件證據 + 幾乎沒有可見回答） | 560 |
| Premature completion（宣稱完成 + 缺驗證契約或隨後被 owner 糾正） | 561 |
| Narrative preservation（糾正推翻了前提，後續計畫卻保留失效血統） | 562 |

13.3 協作健康不是情緒分析（行 564-566）：可以量 owner 介入負擔、糾正密度、
重複指示負擔、復原成本、角色反轉；不准把憤怒等同病態、不准推論私人心理狀態。

### §14　Phase 5：Reality、Verified Progress、資源燃燒防護（行 568-609）

14.1 Phase Charter（行 570-579）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 574 | 不把活動當進度，保護 token/時間/API 預算 |
| In scope | 575 | 檔案/程序/基本指令的宣稱-證據驗證、進度狀態機、資源成本帳、燃燒事件 |
| Out of scope | 576 | 不做企業級 policy engine |
| Deliverables | 577 | ProgressRecord、ResourceCostRecord、BurnIncident、verifier adapters、進度效率報告 |
| Exit gate | 578 | 歷史的無進度重試案例要在原本的極端成本點之前開出 burn incident；假進度宣稱被證據降級 |
| Stop 條款 | 579 | 用訊息量/工具次數推進度、verifier 分不出 WRITTEN 跟 VERIFIED、成本資料缺失被靜默忽略，三者任一成立就停 |

14.2 進度狀態機（行 581-587）：
PLANNED → QUEUED → RUNNING → COMPLETED → VERIFIED → RELEASABLE，
側枝 STALLED、FAILED、INVALIDATED / SUPERSEDED。

14.3 verified progress 的定義（行 589-591）：新的持久狀態才算，
過閘、已驗 artifact、解掉的 unknown、驗過的 blocker、被接受的決策、完成的復原。
工具呼叫、牆鐘時間、agent 數、訊息數是活動，不是進度。

14.4 資源燃燒模型（行 593-605）：
ResourceCost = token + 牆鐘時間 + API + 算力 + 人為中斷成本（行 595）。
ProgressEfficiency = verified_progress_units / ResourceCost（行 597）。
NO_PROGRESS_BURN 開立條件（行 599-605）：重試超出政策預算，且 verified progress
持平或倒退，且策略/假設沒換或已有反證，三者同時成立。

14.5 Observe 模式下的動作（行 607-609）：POC 階段 guard 先給復原建議不硬擋：
停掉昂貴重試、保全狀態、轉純對話或換策略、建 checkpoint、解釋原因。

### §15　Phase 6：Correction、Hypothesis、Plan Graph、權威撤銷（行 611-669）

15.1 Phase Charter（行 613-622）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 617 | 新資訊要能動手：事實/權限/假設/owner 糾正變了，過期的假設與計畫就失去權威 |
| In scope | 618 | 糾正正規化、假設租約、計畫前置條件、依賴傳播、行動前決策模擬 |
| Out of scope | 619 | 不做通用法務/授權判定；unknown 就維持 unknown |
| Deliverables | 620 | Correction/Hypothesis/Plan 模型、依賴圖、失效引擎、SHADOW 模式的 pre-action gate |
| Exit gate | 621 | fixture 要能演出：被駁倒的 DNS/伺服器假設不能再授權改伺服器；KOL 編輯權限 unknown/禁止時該計畫分支失效 |
| Stop 條款 | 622 | 允許模型繞過失效前提去推理、糾正只存成散文、unknown 權限被當成有權限，三者任一成立就停 |

15.2 Correction schema（行 624-638）：九類欄位，
correction_id / actor / source_event_id、refutes[]、constrains[]、supersedes[]、
adds_hard_constraints[]、removes_permissions[]、invalidates_assumptions[]、
invalidates_plan_nodes[]、requires_replan、evidence_refs[]。

15.3 Replan Boundary（行 640-649）：六種失效各對應一種回應，
小參數變動 PATCH、必要資產不可得 RESET 該分支、權限/授權 unknown 或被移除
CONDITIONAL/BLOCK 且行動前先驗、核心機制被證偽 RESET 依賴計畫、
北極星/商業目標變了就從新的正典目標開新計畫版本、目標環境實質改變就失效部署宣稱。

15.4 Pre-action epistemic gate，先跑 SHADOW（行 651-669）：八項檢查，
北極星、有效糾正、假設狀態與權威租約、計畫步驟前置條件、所需權威/權限/授權、
新反證、重試/燃燒預算、外部能力新鮮度；輸出六值之一
ALLOW | PREPARE | VERIFY | REPLAN | ASK | BLOCK（行 669）。

---

## 二、對照 repo 現況

### 先講一個蓋在所有比對上面的事實

`.forseti/PHASE_STATUS.md` 的「這個 repo 現在的東西是什麼性質」一節與
`.forseti/DECISION_LEDGER.md` ADR-001 都已明講：`src/` 底下 40 個 JS 模組是
「離線分析工具，不是 daemon」，事後拿 transcript 跑，不是對事件即時回答；
新 Engine 決定用 Python 重寫，JS 留作 hook 與判準參考。

工程書 §12-15 的 deliverables 全部假設有一個跑在事件流上的引擎。
所以下面標「已做（離線）」的意思是：判準邏輯存在且有測試，
但它不是書要的那個 locator engine / guard / gate 的運行形態。

### Phase 3（§12）對照

| 書的要求 | 行號 | 現況 | 依據 |
|---|---|---|---|
| 窗口評分、峰值、變點、母題、top-k 選取 | 515-518 | 已做（離線） | `src/windows.js`：bucketize / findPeaks / findChangePoints / findMotifs / selectWindows，測試 `test/windows.test.mjs` |
| 確定性排序測試 | 518 | 已做 | `test/windows.test.mjs` 存在；PHASE_STATUS 記 48 個套件全過。我沒有親自重跑這批 JS 測試，這一格是檔案存在加上 PHASE_STATUS 的宣稱 |
| 依事件數「與」時間分割 | 524 | 部分 | `src/windows.js` 只用固定時間桶（bucketMs），註解自己講了選時間不選事件數的理由：活動密度本身是訊號 |
| 對早期健康基線找變點 | 528 | 部分 | `src/windows.js` 的 findChangePoints 是相鄰桶落差；`src/baseline.js` 有「只用有已驗證產出的窗口當樣本」的自適應健康基線，但兩者沒有接在一起 |
| 錨點注入（糾正/逾時/取消/重複錯誤/狀態跳變） | 530 | 沒有 | windows.js 的候選來源只有峰值、變點、母題三種，grep 不到錨點類事件被當 anchor 餵入的程式碼 |
| 前後有界擴張 | 532 | 已做 | `src/windows.js` DEFAULT_CONFIG 的 contextBefore / contextAfter，selectWindows 有重疊合併 |
| 持久化 window ID + 精確 event refs | 534 | 沒有 | selectWindows 回傳的窗物件沒有 window_id，events 是整包內嵌不是 ref；沒有任何持久化 |
| CLI list/export | 518 | 沒有 | `apps/forseti-cli/forseti.py` 的子指令是 doctor/status/gate/context/index/recall/tasks/dispatch/auto/drain/event/verify/continuity/watch/handoff，沒有窗口相關指令 |
| 取樣預算明講、超了就排更嚴 | 536-538 | 部分 | topK=5 有；每窗事件數/字元上限沒有，「超預算就 rank harder」的邏輯沒有。倒是有 reduction 欄位回報收窄比例 |

windows.js 檔頭自己標了「以下全部沒有實測校準」，這跟書 519 的 exit gate
（要用歷史 fixture 驗 top-k 命中）是同一件事還沒做的兩種說法。

### Phase 4（§13）對照

| 書的要求 | 行號 | 現況 | 依據 |
|---|---|---|---|
| Human-as-QA inversion | 557 | 已做（離線） | `src/collaboration.js`：correctionBurden、HCD，四種 corrective labor 事件，測試 `test/collaboration.test.mjs` |
| Agent passivity | 558 | 沒有 | 沒有偵測「微指令變多 + 自主驗證變少」的模組。最接近的 `src/followthrough.js`（說了沒做）與 `src/yield.js`（過早交還發言權）量的是別的失效 |
| Instruction repetition | 559 | 沒有 | 沒有偵測器。`src/goalanchor.js` 的 REPEATED_OWNER_INSTRUCTION 是目標來源的信心權重，不是重複偵測；`apps/forseti-cli/recall.py` 的糾正候選是檢索標記 |
| Output starvation | 560 | 已做（離線） | `src/liveness.js`：OUTPUT_STARVATION 分類與 TOS 綜合分。注意 `apps/forseti-cli/starvation.py` 同名但是另一件事，見第三部分 |
| Premature completion | 561 | 已做（離線） | `src/primitives.js` prematureClosure（FP-16）、`src/claims.js` Post-Claim Integrity Gate、`src/yield.js` |
| Narrative preservation | 562 | 已做（離線） | `src/primitives.js` invalidatedNarrativePersistence（FP-22）、`src/recovery.js` 明令不得把失效敘事帶入 successor |
| semantic analyzer 介面 | 549 | 沒有 | `src/windows.js` 檔頭明說「這個模組不呼叫任何模型，送不送、送去哪、怎麼問是宿主的事」。介面本身沒有定義 |
| 信心/證據標籤 | 547 | 已做（離線） | windows.js 的 result_epistemic_ceiling: 'INFERRED'；`src/evidence.js` 的 DECLARED_CAUSAL_HYPOTHESIS 標籤 |
| 不確定保持 UNKNOWN | 550 | 已做（離線） | `src/baseline.js` 樣本不足回 null；`src/heartbeat.js` 拿不到驗證資料回 UNKNOWN；`src/verifier.js` 的 UNKNOWN_COVERAGE |
| 不做情緒診斷 | 548、564-566 | 已做且一致 | `src/collaboration.js` 檔頭：不接受任何情緒輸入，連參數都沒有；CT-027 專測「使用者在罵髒話而一切健康時 HCD 必須是零」 |

### Phase 5（§14）對照

| 書的要求 | 行號 | 現況 | 依據 |
|---|---|---|---|
| 進度狀態機 | 581-587 | 已做但形狀不同 | `apps/forseti-cli/ledger.py` 行 50-74：PROPOSED → ACCEPTED → RUNNING ↔ WAITING_DEPENDENCY ↔ BLOCKED ↔ NEEDS_HUMAN ↔ VERIFYING → VERIFIED_COMPLETE，終態另有 CANCELLED_BY_OWNER / FAILED_TERMINAL / SUPERSEDED。跟書的狀態集不同名不同形，見第三部分 |
| WRITTEN 與 VERIFIED 分開 | 579 | 已做 | ledger.py：verifier 沒過就轉回 RUNNING 並累加 retry_count（行 529-532 附近的註解與 CT-F02-01）；PHASE_STATUS 全篇執行這條 |
| 活動不是進度 | 574、589-591 | 已做（離線） | `src/progress.js`：三層 ACTIVITY/TASK/GOAL 永遠分開存，沒有 overall_progress 欄位；`src/heartbeat.js` v0.2 只認 verified_progress |
| ProgressRecord 實體 | 577 | 沒有 | 全 repo grep 無此名。ledger.py 的 step 狀態是最接近的東西，但不是書定義的那個 record |
| ResourceCostRecord、成本帳 | 577、595 | 沒有 | 全 repo grep 無 ResourceCost。`src/cost.js` 名字像但內容是變更影響的依賴圖代價（M4），不是 token/時間/API 燃燒帳 |
| BurnIncident、NO_PROGRESS_BURN | 577、599-605 | 沒有 | 全 repo grep 無 BurnIncident、無 NO_PROGRESS_BURN |
| ProgressEfficiency 公式與報告 | 597、577 | 沒有 | 無對應實作 |
| burn guard 建議式動作 | 607-609 | 部分 | `src/heartbeat.js`：連續空轉計數升級、「Continuing would burn budget to look busy」時建議停。方向一致，但沒有成本輸入，觸發條件是空轉次數不是書 599-605 的三條件 |
| verifier adapters | 577 | 已做（兩處） | `src/verifier.js`：registry、四種 outcome 含 UNKNOWN_COVERAGE；`apps/forseti-cli/ledger.py`：file:/cmd: verifier 收據（本任務的驗收就是走 file: 這條） |
| 成本資料缺失不准靜默忽略 | 579 | 無從評 | 成本帳整個沒做，這條既沒違反也沒滿足 |

### Phase 6（§15）對照

| 書的要求 | 行號 | 現況 | 依據 |
|---|---|---|---|
| Correction 結構化 schema（九類欄位） | 624-638 | 沒有 | 全 repo 沒有 refutes[]/constrains[]/supersedes[] 這種結構。`src/challenge.js` 只把 corrections 當輸入，查 agent 有沒有認列（unacknowledged_corrections） |
| Hypothesis 模型與權威租約 | 618、620 | 沒有 | `src/evidence.js` 只有 DECLARED_CAUSAL_HYPOTHESIS 這個證據標籤，沒有租約、沒有到期、沒有撤銷 |
| Plan 模型、依賴圖、傳播 | 618、620 | 沒有 | `src/cost.js` 的依賴圖是程式 import 圖，不是計畫節點圖 |
| 失效引擎 | 620 | 沒有 | 偵測面有 FP-22（事後抓「失效敘事還在」），但沒有主動把計畫分支標失效的引擎 |
| Replan Boundary 六種回應 | 640-649 | 沒有 | 無對應機制 |
| Pre-action gate 八檢查六輸出、SHADOW | 651-669 | 部分（一小塊） | `src/progress.js` preActionCommitmentGate 只做「有沒有已承諾任務正在餓死」這一項，輸出二值 PROCEED / REQUIRE_EXPLICIT_REPRIORITISATION，不是六值；`src/challenge.js` crossCheck 覆蓋「檢查有效糾正」的偵測面。八項裡的假設租約、權限、反證、燃燒預算、能力新鮮度都沒有 |
| unknown 權限不得當有權限 | 622 | 無從評 | 權限模型整個沒做。精神上一致的東西存在（verifier.js 的 UNKNOWN_COVERAGE 優先於錯誤的 pass/fail），但那是驗證方法的 coverage，不是權限 |

---

## 三、衝突與矛盾

先講結論：沒有找到「已實作的東西違反書的 MUST NOT」的正面衝突。
我逐條核對過四個 Phase Charter 的 stop 條款（行 520、551、579、622），
已實作的部分不是符合就是無從違反（因為對應機制根本沒做）。
其中三條甚至是現有程式碼刻意反向設計的：髒話不當失敗證據（collaboration.js）、
活動不當進度（progress.js、heartbeat.js）、WRITTEN 與 VERIFIED 分開（ledger.py）。

但有五個會咬人的分歧與混淆源：

一、運行形態衝突，已被承認但還沒解。書的 deliverables 是引擎與閘門
（locator engine、burn guard、pre-action gate），repo 現有的是離線純函數庫加執行側帳本。
ADR-001（`.forseti/DECISION_LEDGER.md`）已決策：Engine 用 Python 重寫，JS 當判準參考。
所以本報告裡每一格「已做（離線）」在書的驗收標準下都要再過一次 Python 重寫。
這不是新發現，是把既有決策對到 §12-15 的每一條上。

二、兩套狀態機，需要對映決策。ledger.py 的狀態機（PROPOSED/ACCEPTED/RUNNING/
WAITING_DEPENDENCY/BLOCKED/NEEDS_HUMAN/VERIFYING/VERIFIED_COMPLETE...）跟書 14.2
（PLANNED/QUEUED/RUNNING/COMPLETED/VERIFIED/RELEASABLE + STALLED/FAILED/INVALIDATED/
SUPERSEDED）名稱與形狀都不同。語意上有對得上的（VERIFYING→VERIFIED_COMPLETE 保住了
COMPLETED≠VERIFIED 的精神；SUPERSEDED 兩邊都有），但書有而 ledger 沒有的是：
RELEASABLE、INVALIDATED（這個跟 Phase 6 的失效引擎綁在一起）、STALLED 作為狀態
（ledger 把停滯當 watchdog 的 STALL_SUSPECT 事件，不是狀態）。ledger 有而書沒有的是
NEEDS_HUMAN、WAITING_DEPENDENCY、CANCELLED_BY_OWNER。照書實作 ProgressRecord 的那天，
要嘛對映要嘛併軌，不決定就會有兩套「進度」各說各話。

三、命名撞車之一：starvation。`apps/forseti-cli/starvation.py` 實作的是 F07 的
ResultReceipt 保全（回應吐白時工作成果不丟），書 13.2 行 560 的 Output starvation
是協作病徵（有做事但看不到回答），偵測它的是 `src/liveness.js`。同名不同物，
接手的人看到 starvation.py 很容易把行 560 勾成已做。

四、命名撞車之二：cost。`src/cost.js` 是變更影響的依賴圖代價（五機制 M4），
書 14.4 行 595 的 ResourceCost 是 token/時間/API/算力/人為中斷的燃燒帳。
將來實作 ResourceCostRecord 時不要往 cost.js 裡塞，那個模組檔頭明令禁止
把維度合成單一分數，跟燃燒帳的加總公式正好是相反的設計哲學。

五、階段編號是兩套平行系統。`.forseti/PHASE_STATUS.md` 的階段 0-5 出自
`docs/build-plan.md` 第五節（階段 3 = 人與 AI 雙向記錄），書的 Phase 3 = Suspicious
Window Locator，完全是兩回事。PHASE_STATUS 目前只有階段 0 是 VERIFIED，
書的 Phase 3-6 在 build-plan 的編號下大致散落在階段 2 到 4 之後。
任何寫「Phase 3」三個字的地方都必須講明是哪套編號，不然就是下一個混淆事故。

另有一條不算衝突但要記著：windows.js 用純時間桶而不是書 524 行的
「事件數與時間」雙軌分割，是有寫下理由的刻意選擇（活動密度本身是訊號，
用事件數切會把密集期壓縮掉）。Python 重寫時這條要當成一個待裁決的分歧
帶進去，不是照書無腦改掉，也不是照舊碼無腦保留。
