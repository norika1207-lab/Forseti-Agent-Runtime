# REQUIRED_READING

最後更新 2026-09-08。

這份存在的理由：2026-09-08 那個 session 拿到九份文件只讀了一份就開始寫程式，
走偏兩小時。她的原話是「你跟所有 AI 都犯一樣的錯，就是只挑標題重點看，
掃描前幾排字後面就略過」。

所以「還沒讀完」這件事要是檔案裡的狀態，不是靠誰記得。

**規則：** 不准 grep 找答案再說讀過了。搜尋只會找到符合你預期的段落，
而你預期什麼取決於你已經決定要做什麼，於是文件變成確認計畫，不是改變計畫。

---

## 進 repo 之後，寫任何程式碼之前

這三份是入口，全部讀完，順序不能換。

| 檔案 | 是什麼 |
|---|---|
| `soul.md` | 我是誰、北極星、她糾正過的七個時刻（原話）、怎麼發現自己忘了 |
| `bible.md` | 怎麼做事，七類二十一條，每條附誕生的事故 |
| `docs/build-plan.md` | 現在做什麼、不做什麼、為什麼 |

然後讀 `.forseti/` 的四份控制檔。

---

## 讀取深度怎麼記

出自 Vol2 第 4 節 Context Understanding Coverage。用這個量表取代
「約三成」那種模糊描述，因為模糊描述沒辦法檢查。

| Level | 意思 |
|---|---|
| 0 NONE | 完全未讀 |
| 1 TITLE_ONLY | 只見檔名或標題 |
| 2 HEADER_SCAN | 讀檔頭或摘要 |
| 3 SAMPLED | 取樣讀了部分段落 |
| 4 STRUCTURAL | 讀完整結構與關鍵段落 |
| 5 FULL_READ | 逐段完整讀取 |
| 6 VERIFIED_UNDERSTANDING | 完整讀取後能正確引用、重建、通過 challenge |

**level 5 跟 6 的差別是這份文件裡最重要的一條。** 5 是我說我讀完了，
6 是有人考過我。`forseti gate takeover` 現在只列題目不驗答案
（見 `BLOCKERS.md` 的 B-08），所以任何文件現在最高只能到 5。

完整的 schema 還有 `read_ranges[]`，記錄實際讀了哪些範圍。
現在沒有實作，所以下面的 level 是我自己標的，屬於宣稱不是事實。
這件事要標明，不然這張表會變成另一個「我以為我讀完了」。

---

## 源頭文件

放在 `~/Dropbox/My project/Forseti Agent Runtime/`。九份。

| 文件 | 字數 | Level | 讀取狀態 | 什麼時候必須補完 |
|---|---|---|---|---|
| Formal Specification v2.0（revA） | 78,650 | 5 | 逐段完整 | — |
| ChatGPT 對話（產品願景）※ | 21,587 | 5 | 逐段完整 | — |
| v5.0 架構規格 | 108,401 | 4 | 約八成，第 1-24 節 | 動階段 1 之前補第 20 節儲存架構 |
| AI-First 工程書 | 157,680 | 3 | **約三成，Phase 1-12 未讀** | **動階段 1 之前必須補 Phase 1-2** |
| 產品策略白皮書 | 34,157 | 3 | 約五成，第 1-7 節 | 談商業化或研究語料之前 |
| Mercury `all.md` | 224,213 | 2 | 導覽總結完整，其餘未讀 | 需要 ISEEU/Bragi 細節時 |
| Five Mechanisms Handoff | 50,838 | 2 | **約兩成** | 動 M3-M5 之前 |
| Guardian v2.0 架構規格 | 39,873 | 1 | 開頭，與 v5.0 高度重疊 | 低優先，內容重複 |
| 龍蝦 memory 四份 | — | 5 | 逐段完整 | — |

Formal Spec 那份在目錄裡有四個變體（docx/md × 有無 revA）。讀的是
`_revA_2026-09-08.md`，78,650 bytes。repo 裡的 `docs/spec-v2.0.md` 是它的副本
加了一段來源說明，所以雜湊對不上，只能靠檔案大小推。**沒有版本指紋，
來源改了不會有人發現。** Vol2 第 10 節的 content-addressable evidence store
就是在解這件事，還沒做。

※ ChatGPT 對話不在資料夾裡，連結由她提供。分享頁只有五則訊息，
最後一則 21,587 字是主體。要看的是第 1 到 61 節全部，不是跳到第 60 節。

**docx 轉 markdown**：用 `tools/docx2md.py`，給目錄就整批轉。

```bash
python3 tools/docx2md.py ~/Dropbox/My\ project/Forseti\ Agent\ Runtime/platform/
```

不要用「剝掉所有標籤」那種一行指令。它不會漏字，但會把標題、清單、
表格壓成沒有層級的平行文字行。Vol1 的三層產品定位是一張表，剝完之後
變成十二行散落的字，讀的人要自己猜回它是表格。結構本身就是資訊。

也不要用正則抓 `<w:t>`。它在自閉合標籤上會跨越邊界，把 XML 標籤吃進
文字裡。2026-09-09 我用它量 Vol1 得到 16,859 字，以為原轉法漏了 83%，
差點據此重查所有讀過的文件。真實是 2,876。

---

## 平台願景文件（vNext）

放在 `~/Dropbox/My project/Forseti Agent Runtime/platform/`。五份，2026-09-08。
2026-09-09 已用 `tools/docx2md.py` 轉成 md，與 docx 並排。

**這五份跟上面那九份不是同一層。** 上面九份是現在這條線的規格，
這五份是平台願景，範圍比現在做的大很多。Vol4 第 12 節自己寫了
Kill Criteria，第 14 節寫「任何 Stage 都必須能獨立證明價值，
不可以用終極願景掩蓋目前產品不好用」。**讀它們是為了知道方向，
不是為了現在就做。**

| 文件 | 字數 | Level | 這份在講什麼 |
|---|---|---|---|
| Design Evolution History | 2,385 | 5 | 推導過程，不是結論。為什麼從溫度計變成協作平台 |
| Vol1 Platform Constitution | 2,599 | 5 | 三層產品定位、平台北極星、不可違反的十條憲法 |
| Vol2 Platform Architecture | 4,200 | 5 | 物件模型、Raw Ledger、Context Coverage 量表、X-Ray Graph |
| Vol3 Collaboration Protocol | 3,595 | 5 | Rehydration、雙 Session、Goal 演化、Fork、Replay |
| Vol4 Product Ecosystem Roadmap | 2,727 | 4 | Stage 0-8 路線與 Kill Criteria。第 11 節商業層次只到 level 4 |

### 這五份裡現在就用得到的四處

| 出處 | 內容 | 對應到現在的什麼 |
|---|---|---|
| Vol2 §4 | Context Understanding Coverage 七級量表 | 就是本檔上面那張表 |
| Vol2 §3.2 | CompressionEpoch schema | `context_meter.py` 已抓到大部分欄位，缺 `lost_context_refs[]` |
| Vol2 §10 | content-addressable evidence store | 版本指紋，現在完全沒有 |
| Vol3 §4.1 | RehydrationPacket schema | **C2 的正確規格**，取代原本自己拍的「context 增加小於 500 token」 |
| Vol3 §5 | Dual-Session Protocol | Assistant Session 回報要附 Evidence + Result + **Unknowns** |
| Vol3 §6 | Goal Evolution Protocol | `NORTH_STAR.md` 缺的版本機制 |

### 一件待決的事，不要自己決定

Vol1 第 2 節的平台北極星是**雙向**的（Human-AI Collaboration Unit，
第四條憲法明說不是單向檢討 AI）。`.forseti/NORTH_STAR.md` 現在寫的是
**單向**的（AI 的狀態可觀測，使用者是被服務方）。

這是擴大不是措辭差異。但 Vol3 第 6 節規定 Goal 演化要走 proposal →
owner confirm → dependency analysis 的流程。**所以這件事要 owner 拍板，
接手的 session 不准自己改 `NORTH_STAR.md`。**

---

## 模組化執行規格（Modular Spec，2026-09-09）

放在 `~/Dropbox/My project/forseti_20260909-2_Modular_Spec/`。九份，全部是 md。
`spec_manifest.json` 是機器可讀的清單。

**這一組是「怎麼做」，platform 五份是「做什麼」。** 而且這一組現在就做得到。

它的 `reading_policy` 寫著 full-file required，sampled 或 title-only 的閱讀
直接判為 non-conformant。ARCH-EXEC-001 第 5 節有 AI Reading Contract 六條，
其中一條要求回報 `READ_COVERAGE=FULL` 加檔案 hash，另一條要求明確列出
沒看懂的段落。下表的 hash 就是照那條記的。

| ID | 檔案 | Level | sha256(前12) | 主題 |
|---|---|---|---|---|
| ARCH-EXEC-001 | `00_Forseti_Execution_Foundation_Architecture.md` | 5 | `4ca6689973e5` | 五層架構、核心不變量、Reading Contract |
| F01-PEC-001 | `F01_Persistent_Execution_Contract.md` | 5 | `fe86cb2a1ab7` | 持久執行契約，TURN_END ≠ TASK_END |
| F02-TSM-001 | `F02_Task_State_Machine.md` | 5 | `99ec01294dde` | 狀態機與外部任務真相 |
| F03-CSI-001 | `F03_Main_SubSession_Context_Isolation.md` | 5 | `792cd95009f0` | Main/Worker 隔離、Worker Result Packet |
| F04-EVT-001 | `F04_Event_Driven_Dispatch.md` | 5 | `91dfb59b5dfa` | 事件驅動派工，心跳不是轉換機制 |
| F05-WDG-001 | `F05_Watchdog_Heartbeat_Recovery.md` | 5 | `17ca3a6ee9c4` | 停滯偵測與復原階梯 |
| F06-EXC-001 | `F06_Execution_Continuity.md` | 5 | `e2c0dfb0f965` | 解釋完就停、報告完就停 |
| F07-OUT-001 | `F07_Output_Starvation.md` | 5 | `c721da66a062` | 空輸出與結果保全 |
| F08-CTX-001 | `F08_Context_Isolation_Rehydration.md` | 5 | `b80b985fdfc0` | Context Coverage、壓縮邊界、Rehydration |

### 讀完當下的自我審計

F06 第 5 節定義 `HumanContinueBurden` = 每個任務裡人類必須說「繼續」的次數，
應趨近於零。

**2026-09-09 這一場實測 8 次。** 時間點：06:32、06:56、10:18、10:28、10:52、
13:48、02:09、03:50（UTC）。F01 第 2 節那段 problem statement 是逐字劇本，
定性是「This converts the human into an artificial heartbeat and supervisor」。

這個數字是這一組規格要解決的問題本身，也是 F01/F02 要先做的理由：
義務只存在於模型記憶裡，回合結束它就消失。

### 兩處沒看懂，照 Reading Contract 列出

`F05 §3` 的 `STALL_RISK` 是四個因子相乘，但沒有定義各因子的值域與量法。
概念懂（不能只看時間長），不知道怎麼實作成一個數字。

`F07 §2` 的 `STALE_WATCHER`。從 CT-F07-04「ESC reveals completion」推測是
「工作已完成但介面沒更新」，這是推測不是理解。

### 一處規格之間不一致，不要自己補

`F01 §3` 說非終止狀態包含 `REPORTING`、`NEEDS_REVIEW`、`NO_OUTPUT`，
但 `F02 §2` 的 canonical states 沒有這三個。

實作以 F02 的狀態機為準（那是狀態機的規格），F01 那三個先記為待澄清。
**不要自己決定要不要加進狀態機。**

---

## 各階段動工前的補讀門檻

這張表是給 `forseti doctor` 檢查用的。

| 要動哪一階 | 必須先讀完 | 現況 |
|---|---|---|
| 階段 0 | 三份入口 + 四份控制檔 | 可以動 |
| 階段 1 事件帳本 | 工程書 Phase 1、v5.0 §6 與 §20 | **未達標** |
| 階段 2 Claim/Reality | 工程書 Phase 5、v5.0 §7 | v5.0 §7 已讀，工程書未讀 |
| 階段 3 人與 AI 雙向 | v5.0 §8、Formal Spec §5-6 | 已達標 |
| 階段 4 健康與退化 | 工程書 Phase 2-4、v5.0 §13-14 | **未達標** |
| 階段 5 Checkpoint/Fork | 工程書 Phase 7、v5.0 §17 | v5.0 §17 已讀，工程書未讀 |

---

## 她講過但沒寫進文件的事

這些只存在對話裡，2026-09-08 那一輪。原話記在 `soul.md` 第三節。

- 照妖鏡與 Context Token Monitor 都在 Code Duo，要接不要重寫
- 她的判定早就寫在一千多個 session 裡，就在她罵人的地方
- 摘要要用外部學問的維度做（心理學、行為學、語言學、MBTI），才能比對
- 要記錄「沒說的」，她問問題的位置本身就是資訊
- 指紋不一致要先分辨三種原因：換人、模型錯、人真的改變想法
- 人改變想法時拿舊北極星去警告他，那個北極星就變成強噪音
- 累積互動之後要能反過來給三張卡片讓她選，選完直接變 prompt
