# 讀書報告：AI-First 工程書 §16-21，Phase 7 到 Phase 12

寫於 2026-09-09。任務 T-04102433fb/s1。

源檔　`docs/sources/Forseti_AI_First_Development_Engineering_Book_v1.0_2026-09-07.md` 第 671 到 840 行。
本報告的行號全部指這個檔案。這一段我逐行讀完。

先講清楚範圍：全書 166,196 字，我這次只讀第 671 到 840 行。
`.forseti/REQUIRED_READING.md` 第 64 行標整本書讀取深度 Level 3（約三成、Phase 1-12 未讀）。
所以「§16-21 跟書中其他章節有沒有互相引用或衝突」這件事，本報告答不了，沒讀就是沒讀。
但 REQUIRED_READING 第 212 行寫「階段 5 Checkpoint/Fork 需要工程書 Phase 7，未讀」，
本報告讀完之後那一列的 Phase 7 部分有依據可以更新了（更新 RR 不在本步驟交付範圍，只提示）。

對照現況的部分，列出的每個檔案我都親自開過（Read 或 sed 讀了檔頭與關鍵段落，
grep 掃過全 repo 關鍵字）。但我沒有逐行讀完 40 個 JS 模組與整份 forseti.py，
所以「某功能不存在」的判定依據是全 repo grep 沒命中加上相關模組讀過沒看到。
標「沒有」的地方若之後被推翻，最可能的原因是功能藏在我沒逐行讀的深處。

---

## 一、這幾節規定了什麼

### §16　Phase 7：Rescue Mode，把人帶出火場（行 671-706）

16.1 Phase Charter（行 673-682）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 677 | session 明顯退化時，給使用者一條離開火場的路，不是更多警鈴 |
| In scope | 678 | 復原建議、緊急對話模式、供應商允許時的 freeze/pause hook、搶救 checkpoint、clean fork packet |
| Out of scope | 679 | 不准嘗試實際上不存在的供應商控制；adapter 不能中斷時不准承諾自動救援 |
| Deliverables | 680 | RecoveryPlan、EmergencyConversationMode、checkpoint、clean-fork context、依供應商能力調整的動作 |
| Exit gate | 681 | 用歷史空白/工具迴圈 fixture 驗：能產出精簡救援方案，並保留足夠狀態讓後繼者不重複失敗策略 |
| Stop 條款 | 682 | 救援毀掉有用 artifact、供應商控制不了但 UI 假裝控制了、復原需要讀完整段污染結尾，任一成立就停 |

16.2 緊急對話模式的流程（行 686-698），七步：
偵測嚴重退化（686）-> 能力與政策允許時凍結新的高風險寫入與工具（688）-> 保持人類對話可用（690）
-> 抓取當前狀態與證據（692）-> 只摘要「已驗證」的目標、決策、結果、未知（694）
-> 標出已污染/失效的分支並排除（696）-> 給選項：繼續、clean fork、人接管、鑑識模式（698）。

16.3 救援輸出必須可行動（行 700-706）：三組對照，
不准說「AI 好像不健康」，要說「工具活動持續 14 分鐘無可見輸出、artifact 無變化，停掉這個策略、保存狀態、切對話模式、從 checkpoint X 重建」（704）；
不准說「context 可能污染了」，要說「最後三次糾正使 plan 節點 P12-P18 失效，不得注入後繼者」（705）；
不准說「試試重啟」，要說「重啟安全因為 W7 與 A9 是持久的，外部效果 E2 已提交不得重放」（706）。

### §17　Phase 8：X-Ray v1 與溫度 UI（行 708-737）

17.1 Phase Charter（行 710-719）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 714 | 用最不吵的形式暴露系統：一個健康溫度、一句原因、一個下一步，加可下鑽的 X-Ray |
| In scope | 715 | CLI/Tauri UI、時間軸、溫度曲線、可疑窗、糾正與計畫失效、燒錢、復原 |
| Out of scope | 716 | 不做企業儀表板；不做沒有證據語意的裝飾圖 |
| Deliverables | 717 | X-Ray API、桌面/CLI 視圖、事故匯出（incident export） |
| Exit gate | 718 | 使用者能檢視一個歷史事故並辨認：正常期、退化起點、候選首次偏離、成本/進度、糾正、復原、證據信心 |
| Stop 條款 | 719 | UI 比原始 log 更耗認知、警報沒有排序、推論出來的邊被畫成確定事實，任一成立就停 |

17.2 預設畫面（行 721-733）：一屏只有溫度與狀態（如 37.2 C WATCH，723）、session 名（725）、
主要變化一句話（727）、已驗證進度停滯多久（729）、動作建議（731）、三個入口 Why / X-Ray / Checkpoint（733）。

17.3 下鑽規則（行 735-737）：預設只顯示單一最高槓桿事實；原始節點、幾十筆債、
每個指標只在下鑽時出現。一個持續大叫的治理工具本身就是生產力失敗（737）。

### §18　Phase 9：連續性記憶，保存有生產力的協作者而不只是摘要（行 739-766）

18.1 Phase Charter（行 741-750）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 745 | 讓替補 session 不只拿回任務狀態，還拿回讓先前協作有效的互動脈絡 |
| In scope | 746 | 互動側寫、協作偏好、決策理由、健康窗錨點、交接安全的 context builder |
| Out of scope | 747 | 不宣稱保存靈魂/人格；不在使用者無法控制下儲存私人特質；不注入整份 transcript |
| Deliverables | 748 | InteractionProfile、健康協作指紋、context builder、接管測試 |
| Exit gate | 749 | 後繼者在有界 context 下重現工作風格、決策約束與專案理解，且不復活已失效分支 |
| Stop 條款 | 750 | profile 只是散文摘要、profile 從單一壞掉區間推出來、使用者不能檢視編輯，任一成立就停 |

18.2 連續性記憶存什麼（行 752-762），七類：決策理由（756）、互動偏好（757）、
主動權邊界（758）、證據標準（759）、健康協作錨點（760）、糾正教訓（761）、
語言溝通側寫且使用者可編輯（762）。

18.3 健康 context 挑選（行 764-766）：不准主要從 session 結尾建連續性，
因為結尾常被工具迴圈、怒氣、糾正風暴與失敗復原污染。
按「已驗證進度高、矛盾與糾正負荷低、目標穩定、結果成功」排序選窗（766）。

### §19　Phase 10：Code Duo 整合（行 768-787）

19.1 Phase Charter（行 770-779）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 774 | 把持久邏輯 agent 綁到可替換的 session 上，協作在供應商/session 死亡後仍存活，分工不失去共同意圖 |
| In scope | 775 | 持久 Agent 身份、session mesh、共享結果 context、角色能力側寫、接管 |
| Out of scope | 776 | 不在 agent 之間交叉注入全部原始對話 |
| Deliverables | 777 | Agent/Session 分離、只共享結果的 context、後繼者指派、生命週期狀態、Code Duo adapter |
| Exit gate | 778 | 兩個邏輯 agent 平行工作，一個 session 死掉，後繼者收到有界已驗證 context 且不混淆身份角色 |
| Stop 條款 | 779 | Agent 身份綁死供應商 session ID、共享 context 變成 transcript 洪水、後繼者繞過充分性閘門，任一成立就停 |

19.2 身份定律（行 781-783）：持久 Agent 身份 ≠ 供應商 Session ≠ 模型 ≠ 程序 ≠ 執行槽 ≠ 角色。

19.3 共享 context 規則（行 785-787）：共享已驗證產出、已接受決策、需求、checkpoint 與明確協作請求；
不自動共享對方不需要的原始私有上游對話。

### §20　Phase 11：Code Tree 整合（行 789-814）

20.1 Phase Charter（行 791-800）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 795 | 把專案變成持久的追溯/因果樹：AI 能懂 artifact 為何存在、依賴什麼、什麼證明它 |
| In scope | 796 | 需求-決策-程式-測試-證據圖、變更帳、語意 blast radius、專案拓撲 |
| Out of scope | 797 | 第一次整合不求完美解析每種語言 |
| Deliverables | 798 | Code Tree 圖 adapter、追溯邊、artifact 與需求連結、X-Ray 交叉導覽 |
| Exit gate | 799 | 從任何重要 artifact 能往上走「為何存在」、往下走「什麼證明它」，且帶證據 |
| Stop 條款 | 800 | 圖是裝飾、沒綁 runtime 事件與驗證；糾正之後過時的 code 節點仍是 canonical，任一成立就停 |

20.2 三系統閉環（行 802-814）：Code Tree 管專案知道什麼與為何、Code Duo 管誰在協作與
持久邏輯 agent 擁有什麼、Forseti 管協作與 runtime 健不健康真不真實可不可復原還有沒有授權，
循環是 observe -> work -> verify -> update graph -> preserve continuity -> next session（814）。

### §21　Phase 12：預測性 X-Ray、研究語料與企業治理（行 816-839）

21.1 Phase Charter（行 818-827）：

| 條 | 行號 | 內容 |
|---|---|---|
| Goal | 822 | runtime 原語都能動之後，才學習重複失效拓撲、預測 motif、有生產力的異常、更高風險的政策執法 |
| In scope | 823 | 拓撲指紋、研究匯出、holdout、shadow 轉 enforced 政策、團隊企業 |
| Out of scope | 824 | 不准用「發明每個偵測器所用的同批歷史事故」訓練然後稱之為泛化 |
| Deliverables | 825 | 研究 schema、benchmark 切分、motif 搜尋、政策校準、企業路線圖 |
| Exit gate | 826 | 專案層與時間層 blind set 展示可量測泛化；介入負擔低於被阻止的失效成本 |
| Stop 條款 | 827 | 只有 regression fixture 通過、隱私要求集中化原始專有資料、假陽性與打斷率摧毀生產力，任一成立就停 |

21.2 語料切分（行 829-835），五種：session 層切分、專案層 holdout、時間 holdout、
失效家族 blind set、未來外部使用者 opt-in 集。

21.3 研究面（行 837-839）：原始 prompt 與程式碼預設留本機；只在明確 opt-in
加預覽與遮蔽之下，匯出結構化遙測、拓撲、狀態轉移、時序、失效標籤與介入結果。

---

## 二、對照 repo 現況

先講一個貫穿全部六個 Phase 的事實：repo 現有程式碼的規格來源是
`docs/spec-v2.0.md`、`docs/spec-v0.1.md`、F 線規格與 Five Mechanisms handoff，
不是這本工程書。所以下面的「已做」全部是「內容重疊、方向相同」，
不是「照著書的 Phase 7-12 做的」。書的 Phase 編號在 repo 程式碼註解裡一個都沒出現過（grep 驗過）。

### Phase 7　Rescue Mode

已做的部分：

- `src/recovery.js`（302 行，有 `test/recovery.test.mjs`）。RESCUE_SEQUENCE 八步
  （DETECT -> PRESERVE -> QUIET_MODE -> … -> CLEAN_FORK -> VERIFY_FIRST_RESUMED_ACTION，檔內 121-130 行），
  對應書 686-698 行的緊急流程。`buildRecoveryCapsule`（139 行起）帶走已驗證工作、artifact、
  goal、糾正、未知、exact_next_step，並明列「刻意不帶走的」失效敘事與禁止重試清單，
  對應書 694-696 行「只摘要已驗證的、排除污染分支」。`rescueCard`（178 行起）輸出單一
  建議動作、刻意沒有 warnings 陣列，對應書 700-706 行「輸出是方案不是告警」。
  `verifyFirstResumedAction`（279 行起）對應「後繼者第一步先驗證」。
- `src/rescue.js`（181 行，有 `test/rescue.test.mjs`）。注意：這個檔名撞書的 Phase 7，
  但內容是 spec v0.1 §7 的「可見存活與安全中斷」，做中斷前快照（必含 exact_next_step）。
  是相鄰能力，不是書 Phase 7 的 Rescue Mode 本體。
- `apps/forseti-cli/watchdog.py`（F05）。復原階梯 SUSPECT -> soft ping -> inspect state
  -> structured status -> checkpoint -> restart/reassign -> clean fork -> human（檔內 184-215 行一帶），
  人排最後。含 B-10 的 write_only worker 跳過問話三階。這是 clean fork 概念目前唯一
  接到真實 runtime（帳本派工）的地方。

沒做的部分：

- EmergencyConversationMode 這個實體：全 repo grep「emergency」零命中。沒有。
- freeze/pause hook（書 678、688 行，偵測到退化就凍結高風險寫入與工具）：沒有。
  `hooks/` 目錄存在且 dashboard 依賴 hook 寫出的 state 檔，但我沒看到任何凍結或攔截寫入的 hook。
- 書 681 行的 exit gate（歷史空白/工具迴圈 fixture 走完整條救援產出）：`test/recovery.test.mjs`
  存在但我沒逐行讀它驗什麼，這一項標未驗證。

### Phase 8　X-Ray v1 與溫度 UI

已做的部分：

- 健康溫度：`src/signals.js` 算 temperature（已測訊號加權平均，含單一訊號拉滿即 CRITICAL
  的封頂規則，檔內 229-282 行一帶）。
- UI：`tools/dashboard.mjs`（80 行）+ `tools/dashboard.html`（180 行）。本地唯讀 web 儀表板，
  讀 hook 寫出的 state 檔，顯示狀態點、溫度、原因一行、可展開的診斷卡與救援卡
  （html 66-80 行的 dot/temp/cause/diag/rescue 元素）。分級安靜規則寫死在檔頭註解
  （HEALTHY 只有小指示器、CRITICAL 才出救援卡），與書 735-737 行的下鑽規則同方向。
- 拓撲：`src/topology.js`（203 行，有測試）。Goal/Decision/Claim/Evidence/Correction/Unknown
  節點圖，FS-TOP-001 規定看不到 sub-agent prompt 時標 UNKNOWN_EDGE、禁止補圖，
  正是書 719 行「推論的邊不得畫成確定事實」。
- CLI：`apps/forseti-cli/forseti.py` `cmd_status`（400 行起）一屏四個數字，另有 --json 輸出。
- 可疑窗：`src/windows.js`（Phase 3 的東西，但它是書 715 行 in scope 清單裡「suspicious windows」的對應物）。

沒做的部分：

- 時間軸與溫度曲線（書 715 行）：dashboard 兩個檔 grep「timeline/curve/history」零命中，
  只顯示當下狀態。沒有。
- 事故匯出 incident export（書 717 行）：`src/incident.js` 是 warning storm 聚合器、
  `tools/save-case.py` 是存自白書案例，都不是「把一段歷史事故打包成可檢視匯出」。我沒找到，標沒有。
- Tauri 或桌面 UI：沒有，現有的是 CLI 與 local web。
- 書 718 行的 exit gate（歷史事故上辨認正常期/退化起點/首次偏離）：沒有工具支援這整條走查。

### Phase 9　連續性記憶

已做的部分：

- 健康窗挑選：`src/recovery.js` 的 `CONTEXT_KINDS` 三分法（208 行起，CHAT_HISTORY /
  CANONICAL_PROJECT_STATE / HEALTHY_COLLABORATION_CONTEXT）與 `selectHealthyContext`
  （224 行起，判準是 verified progress 高、correction burden 低、goal 穩定，
  明文禁止「選最新的」，失敗段標 forensic only 不得當模板）。
  這幾乎逐條對應書 764-766 行的 §18.3。
- 有界 rehydration：`apps/forseti-cli/rehydration.py`（F08），摘要會丟「為什麼」所以回原文取段、
  且有界不倒整份 transcript，對應書 747 行「不注入整份 transcript」。
- 糾正分界：`apps/forseti-cli/recall.py`（C1 索引層），使用者糾正位置當分界線、
  線之前的講法標可疑，對應書 761 行的糾正教訓方向。
- 接管測試：`apps/forseti-cli/forseti.py` TAKEOVER_QUESTIONS 六題 + `cmd_gate_takeover`
  （416 行起），題目全部來自她實際糾正過的地方。對應書 748 行 deliverables 裡的 takeover test，
  但它驗的是「接手的 AI 讀懂了沒」，不是驗 InteractionProfile 的重現度。
- 文件層承載：`soul.md`、`bible.md`、`.forseti/DECISION_LEDGER.md` 以人可讀可編輯的文件
  承載糾正教訓與決策理由，內容上覆蓋書 756、761 行那兩類。

沒做的部分：

- InteractionProfile 結構化實體（書 748 行）：全 repo grep 只命中書本身。沒有。
  現況正好落在書 750 行 stop 條款警告的形態（「profile 只是散文摘要」），
  soul.md 是散文，不是可檢視可編輯的結構化側寫。
- 健康協作指紋作為可餵給後繼者的資料物（書 748 行）：`selectHealthyContext` 是純函數，
  沒有任何東西在真實 session 上算 fragment 分數再餵給下一個 session。沒有接上。
- 書 757-759、762 行那四類（互動偏好、主動權邊界、證據標準、語言側寫）的結構化儲存:沒有。

### Phase 10　Code Duo 整合

已做的部分（方向相同、來源是 F 線規格）：

- 連續性外部化：`apps/forseti-cli/ledger.py` + `worker.py`。worker.py 檔頭引 F03 §5
  「不是消滅 worker，是消滅 worker 必須擁有連續性」，worker 可死可換可忘，
  連續性在帳本。這正是書 774 行「collaboration survives session death」的機制基礎。
  跨 session 派工實測解除過（commit 84248ad、5c5fa2a、4cf7709，B-09/B-10）。
- 只共享結果：worker.py 的 Worker Result Packet，summary 有字元上限超過拒收、
  raw log 落檔 packet 只帶路徑，對應書 776、787 行「不交叉注入原始對話、共享產出不共享洪水」。
- 接不重寫的決策已立案：`.forseti/DECISION_LEDGER.md` ADR-002（31 行起）
  「照妖鏡與 Token Monitor 在 Code Duo，Forseti 寫 adapter 去接」，
  另有 172 行起的補充釐清「Code Duo 指哪份檔案」。

沒做的部分：

- Code Duo adapter 本體（書 777 行）：`adapters/` 只有 `claude-code.mjs`。沒有。
  DECISION_LEDGER 152 行寫「C3 需要 ADR-002 的照妖鏡接入」，還沒發生。
- 持久 Agent 身份（書 775、781-783 行）：ledger 的 steps 表只有 `assigned_worker TEXT`
  一個欄位（ledger.py 157 行），存的是當次 worker 名（如註解 194 行的 claude-p-worker-3）。
  沒有獨立於 session 的 agent 身份註冊、沒有角色能力側寫、沒有 agent 生命週期狀態。
- session mesh、兩邏輯 agent 平行工作的 exit gate 場景（書 778 行）：沒有。

### Phase 11　Code Tree 整合

已做的部分（只有零件，不是 Code Tree）：

- `src/topology.js`：有 Goal/Decision/Claim/Evidence 圖，但那是「一個 session 的執行過程」的圖，
  不是「整個專案」的需求-決策-程式-測試-證據樹（書 796 行）。
- `src/cost.js`：由 import 紀錄建依賴圖、算 blast set（檔內 112 行一帶）。
  這是檔案層級的 blast radius，不是書 796 行的語意 blast radius。
- `.forseti/DECISION_LEDGER.md`：人工維護的決策帳，是變更帳（change ledger）的雛型內容，
  但它是 markdown，不綁 runtime 事件，不可程式化追溯。

沒做的部分：

- Code Tree graph adapter、需求與 artifact 的連結、「為何存在/什麼證明它」的雙向追溯查詢、
  X-Ray 交叉導覽（書 798-799 行）：全 repo grep「Code Tree」在程式碼裡零命中。沒有。

### Phase 12　預測性 X-Ray 與研究語料

已做的部分（前置紀律，不是 Phase 12 本體）：

- 校準工具鏈：`tools/calibrate.mjs`（十項常數裡能從事件流推的六項，報分佈不報單值，
  碰不到的四項明講不碰）、`tools/pick-negatives.mjs` + `tools/measure-fpr.mjs`
  （healthy corpus 假陽性測量，明知 PRESUMED_HEALTHY 標籤是 MODEL_INFERENCE 所以
  不敢自稱誤報率）、`tools/build-fingerprints.mjs` + `tools/corpus-profile.mjs`
  （可回查的三層 session 指紋，不是只剩彙總數字）。
- 校準結果落檔：`docs/calibration/` 五份（2026-09-08 到 09-09）。
- shadow 先於 enforced 的政策紀律：`src/recovery.js` 的 FS-INT-003，
  未經 healthy corpus 校準前 hard blocking 不得成為預設。與書 823 行
  「shadow-to-enforced policy」同方向。
- 資料留本機：calibrate.mjs 檔頭明文「資料全部留在本機」，與書 837-839 行研究面的
  預設一致（但只做到「不匯出」，沒做到「可 opt-in 匯出」）。

沒做的部分：

- 語料切分（書 829-835 行五種 holdout/blind set）：grep「holdout」只命中書本身。沒有。
  現有校準全部是同一批 transcript，正是書 824 行 out of scope 警告的那種資料狀態。
- 拓撲指紋學習、motif 搜尋、預測性偵測（書 822、825 行）：沒有。
- opt-in 結構化遙測匯出管道與遮蔽預覽（書 839 行）：沒有。
- 企業/團隊治理（書 823 行）：沒有。

---

## 三、衝突或矛盾

1. 「temperature」一詞在 repo 裡有兩個不同的東西，跟書撞名。
   書 714、723 行的 temperature 是 session 健康溫度；repo 裡對應它的是 `src/signals.js`
   的 temperature。但 `src/thermometer.js` 也叫溫度計，量的是另一件事：
   context 裡「查過的」對「自己生出來的」比例。兩個都有測試、都會繼續存在。
   這是命名衝突不是邏輯衝突，但接書的 Phase 8 UI 時如果把 thermometer.js 的數字
   接到「37.2 C」那個位置，就會把事實比例當健康度顯示，語意是錯的。

2. `src/rescue.js` 檔名撞書的 Phase 7 但內容不是它。
   rescue.js 是 spec v0.1 §7 的中斷前快照；書 Phase 7 的 Rescue Mode 對應物其實在
   `src/recovery.js`。用檔名對照書的人會對錯位。同理，repo 程式碼註解裡的 § 編號
   全部指 `docs/spec-v2.0.md`（該檔開頭 12-14 行明文），跟書的章節號是兩套系統：
   書 §16 Phase 7 ≈ spec-v2.0 §17，書 §18 Phase 9 ≈ spec-v2.0 §18。
   目前沒有任何一份對照表把書的 Phase 編號映射到 spec-v2.0 的 § 編號。這不是程式錯，
   是之後照書驗收時保證會發生的混亂來源。

3. 書 783 行的身份定律（Agent 身份不得等於 session ID）與 ledger 現況有潛在踩線。
   `assigned_worker` 存的就是當次 session 的 worker 名。現況不算違反，因為 repo
   沒有宣稱做了 Phase 10；但若之後直接把 assigned_worker 當持久 agent 身份用，
   就直接踩中書 779 行 stop 條款第一項。做 Phase 10 時這個欄位要嘛升級要嘛加一層。

4. 書 824 行明令不准「用發明偵測器的同批事故訓練再稱泛化」。
   repo 現有全部偵測器與校準數字都出自同一批 transcript 與自白書案例
   （save-case.py 檔頭自己講：四個形狀、十個訊號全部從這些文件萃取）。
   工具自己標得很誠實（measure-fpr.mjs 明講它算的不是誤報率），所以現況不構成違規，
   但這代表：現有任何校準數字都不能拿去填書 826 行的 exit gate，一個都不行。

5. 性質差距：書 Phase 7/8 預設是 runtime 介入與即時 UI，repo 的 src/ 模組是
   離線分析純函數（forseti.py 接管測試第三題的標準答案自己講：離線分析工具，
   事後拿 transcript 跑，不是 daemon）。dashboard 透過 hook 讀 state 算半即時，
   但凍結、介入、救援流程沒有一條接到活的 session。拿現有模組宣稱書的
   Phase 7/8 exit gate 已過，會同時踩書 679 行（不准承諾做不到的自動救援）
   與 682 行（UI 假裝控制了供應商）。這不是現在的錯，是之後最容易犯的宣稱錯誤。

6. 沒有發現「已實作的東西跟書的規定反著做」的直接矛盾。
   六個 Phase 裡 repo 已有的零件（recovery capsule、selectHealthyContext、
   worker packet 上限、FS-INT-003、UNKNOWN_EDGE）跟書的對應條文方向全部一致。
   衝突集中在命名、編號映射、以及「零件存在但沒接成書要求的系統」這三類。
