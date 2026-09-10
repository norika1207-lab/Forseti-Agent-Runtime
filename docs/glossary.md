# 名詞對照表

2026-09-10。解 B-11。

**這份文件的用途不是統一命名，是讓對照查得到。**

改名會斷測試與工具，而問題本來就不是名字錯 —— 是這個專案有四份規範來源
（AI-First 工程書、v5.0 架構規格、Formal Spec v2.0、spec v0.1）加上一套
自己長出來的實作，而沒有任何地方記錄「這個詞在哪一份文件裡是什麼意思」。

同一個詞在不同來源指不同東西，接錯之後**不會報錯**，只會安靜地顯示錯的東西。
那正是這份表要防的。

---

## 一　`events`

已由 ADR-008 定案。

| 出處 | 是什麼 |
|---|---|
| v5.0 §6、工程書 Phase 1 | provider 行為事件。`RawEvent` 必須有 `provider, provider_event_type`（v5.0 177-179 行） |
| `apps/forseti-cli/ledger.py` 的 `events` 表 | 派工協調事件，`WORKER_*` 八種加控制端事件 |

**本專案怎麼用：** 兩本帳本分開，各自的庫裡都可以叫 `events`。
**文件與口語一律用完整限定名** —— 講「Task Ledger 的 events」或
「Event Ledger 的 events」，不准只講「events 表」。

兩本帳本本身的名字沒有撞：`ledger.py` 檔頭第一行是「Task Ledger：
外部任務真相」，v5.0 §6 標題是「Event Ledger and Lineage Ledger」。

**接錯的後果：** 做階段 1 時往 Task Ledger 塞 provider 事件，
或接手的人以為 `ledger.py` 就是 Event Ledger 而標記已做。

---

## 二　`temperature`（溫度）

| 出處 | 量的是什麼 |
|---|---|
| `src/signals.js` | session 的健康溫度，0 到 1 加權平均，燈號有 `measured_weight` 封頂 |
| `src/thermometer.js` | context 裡「查過的」對「自己生出來的」比例 |
| 工程書 11.3 | 0-100 instability 經 sigmoid 映射到 36.3 起跳的體溫 |

**三套的輸入、量綱、映射全都不同。**

**本專案怎麼用：** ADR-001 已裁定 `src/` 是離線參考實作不是主線，
所以現在沒有活著的衝突。做工程書 Phase 8 的溫度 UI 時要重新實作，
不要把現有任何一個接上去。

**接錯的後果：** 把 `thermometer.js` 的數字接到「37.2 °C」那個位置，
會把事實比例當健康度顯示，語意完全是錯的。

---

## 三　`rescue`

| 出處 | 是什麼 |
|---|---|
| `src/rescue.js` | spec v0.1 §7 的中斷前快照（檔頭寫「可見存活與安全中斷」） |
| 工程書 Phase 7 Rescue Mode | 恢復人的主導權。**對應物其實是 `src/recovery.js`**（檔頭寫「§17 Rescue」） |

**本專案怎麼用：** 用檔名對照工程書會對錯位。要找 Phase 7 的東西看
`recovery.js`，不是 `rescue.js`。

---

## 四　lineage 邊型

| 出處 | 有幾種 |
|---|---|
| v5.0 §6.3（199-210 行） | 十種：`DERIVED_FROM`、`TRIGGERED_BY`、`VERIFIES`、`REFUTES`、`SUPERSEDES`、`CONSUMES`、`PRODUCES`、`PROMOTES`、`PROPAGATES_TO`、`RECONSTRUCTED_FROM` |
| `src/topology.js:40-41` | 九種：`DEPENDS_ON`、`SUPPORTS`、`REFUTES`、`SUPERSEDES`、`CLAIMS`、`VERIFIES`、`SPAWNS`、`DELEGATES_TO`、`IMPLEMENTS`、`UNKNOWN_EDGE` |

**只有三個名字重疊**（`VERIFIES`、`REFUTES`、`SUPERSEDES`），而且沒有
驗證過重疊的那三個語意是否相同。

**接錯的後果：** 混用會產生對不上的圖。做階段 1 的 `lineage_edges`
表時要照 v5.0 §6.3，`topology.js` 那組是離線層自己的。

---

## 五　`heartbeat`（心跳）

| 出處 | 是什麼 |
|---|---|
| `src/heartbeat.js` | **主動報告**機制。檔頭：「前面所有機制都要有人來叫才會講話，那等於把最後一道防線押在使用者記得問上面」 |
| v5.0 §14 `runtime_node_heartbeat` | **節點存活**訊號，判斷一個 runtime node 還在不在 |

一個是「我主動說話」，一個是「我還活著」。

**接錯的後果：** 把「有沒有主動報告」當成「節點活著沒」。
一個不報告但活著的節點會被判死，一個死掉但最後一則報告還在的會被判活。

---

## 六　`handoff`（交接）

**三個意思，這是撞得最厲害的一個。**

| 出處 | 是什麼 |
|---|---|
| 工程書 §27（27 行、287 行） | `HANDOFF.md`，每個 session 產出的文字交接模板 |
| `apps/forseti-cli/forseti.py:981` `cmd_handoff` | `forseti handoff` 指令，跨 session 派工（登記帳本 + 產出要送的訊息） |
| `src/handoff.js` | Moirai M2 的交接規則，視窗之間的工作移交 |

**本專案怎麼用：** `HANDOFF.md` 目前不存在，而且 `DECISION_LEDGER.md:162-163`
已經否決過 handoff.md 產生器（理由：「那還是塞」「撐不過六個 session」）。
這一條是待裁決第六條，還沒定案。

**接錯的後果：** 補 `HANDOFF.md` 的人會以為 `forseti handoff` 指令就是
那份檔的實作。它們完全無關。

---

## 七　「階段」對 `Phase`

| 出處 | 幾個 |
|---|---|
| `docs/build-plan.md:271-276` | 本專案六階：階段 0 控制檔、1 事件帳本、2 Claim 與 Reality、3 人與 AI 雙向、4 健康與退化、5 Checkpoint 與 Fork |
| 工程書 §8-21 | 十三個 Phase：Phase 0 到 Phase 12 |

**不是一對一對應。** 例如工程書的 Phase 1（Capture Plane）與本專案的
階段 1（事件帳本）主題接近，但工程書的 Phase 2 是 Runtime Thermometer，
而本專案的階段 2 是 Claim 與 Reality。

**Phase 0 特別要小心**，它連驗收標準都是兩套 —— 見 ADR-007。

**本專案怎麼用：** 講「階段 N」指本專案的，講「Phase N」指工程書的。
`REQUIRED_READING.md` 的補讀門檻表用的是本專案的階段編號，
它要求的文件則用工程書的 Phase 編號，那張表兩種都出現。

---

## 八　章節號 `§N`

**同一個 §17 在三份文件裡是三件事。**

| 出處 | §17 是 |
|---|---|
| `docs/spec-v2.0.md` | repo 程式碼註解裡的 § 一律指這一份 |
| v5.0 架構規格 | §17 Reconstruction and Clean Fork |
| 工程書 | §17 是 Phase 8 X-Ray v1 |

**本專案怎麼用：** 程式碼註解裡的 `§N` 一律指 `docs/spec-v2.0.md`
（該檔 12-13 行有明文，連 FS-、FP-、CT- 編號一起）。引用其他兩份時要寫全名，
例如「v5.0 §6」或「工程書 §9.2」。

---

## 這份表一定不完整

上面八條**全部是撞到才發現的**，
不是系統性掃出來的。掃了模組名與規格術語的交集，但「兩邊都常出現」
不等於「意思不同」，逐個查證的成本太高，所以沒有為了湊完整而填。

**怎麼發現新的：**

一，讀規格時看到一個 repo 裡也有的詞，先問「這兩個是同一個東西嗎」，
不要預設是。

二，準備把 A 接到 B 的位置之前，各自開檔讀檔頭。這個專案的模組檔頭
幾乎都寫了自己是什麼，`src/heartbeat.js` 那個撞名就是這樣發現的。

三，發現新的就加進這份表，附出處行號。**沒有出處的不要加** ——
一份有猜測的名詞表比沒有更危險，因為它看起來權威。

---

## 為什麼不是統一命名

`src/topology.js` 那組邊型有測試、`heartbeat.js` 有測試。改名等於改一批
公開介面，而且改完之後舊文件與舊 commit 訊息裡的名字全部對不上。

問題本來就不是名字錯，是沒有地方說明它們各自指什麼。
