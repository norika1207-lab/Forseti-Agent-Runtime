# 產品方向：這三件做完，才算落地

> owner 2026-09-11 逐字：
>
> 「你只有一個絕對方向不能錯，這一定會做成桌面版，而且非常重視ＵＩ呈現的內容，
> 以及我絕對要有ＡＩ對話路徑的ＳＯＵＲＣＥ ＴＲＥＥ。等你都做完了，
> 這才是真正落入能夠應用的領域」

這一段不改寫、不摘要。下面是把它接到已經讀過的規格上，
以及現在離它多遠。

---

## 1. 三件事

**一，桌面版是終點。** 不是 CLI 加一個網頁儀表板，是桌面 App。
Skill 與 CLI 是必經之路，不是產品形態。

**二，UI 呈現的內容是重點，不是附屬。** 「非常重視」是 owner 的原話。
後端把資料算對了不等於做完，人看得懂、用得上才算。

**三，AI 對話路徑的 Source Tree 是必要，不是加分。**
一條沿時序排的線，節點是一輪對話，顏色從綠走到紅；
點開紅的那一節看得到當時的對話與結果；從紅色之前那一節 fork，
任務接著跑。owner 2026-09-11 補充過兩個定義：
一個節點等於一輪對話；fork 是從那個節點 resume。
一開始是一條有顏色的線，fork 之後才長出分支。

**四，三件都做完才算落地。** 原話是「等你都做完了，這才是真正落入
能夠應用的領域」。目前所有工作都在底層。

---

## 2. 規格依據，都是已經讀過的原文

這三件不是新需求，它們在三份規格裡都有對應，而且散在不同地方。

| 要的東西 | 規格出處 | 原文重點 |
|---|---|---|
| 桌面 UI | 工程書 Phase 8 §17.1 | in scope 寫著 `CLI/Tauri UI, timeline, temperature curve, suspicious windows` |
| UI 不能製造負擔 | 工程書 §17.3 | `A governance tool that continuously shouts is itself a productivity failure` |
| 路徑可視化 | spec-v2.0 §11 | Nexus-inspired X-Ray Topology。node types 含 Goal / Decision / Claim / Evidence Receipt / Correction |
| 顯示語意漂移而非只顯示成功 | spec-v2.0 FS-TOP-002 | 必須看得見「所有 artifact 都做了，但 action path 與 Goal 的交集逐步下降」 |
| fork | spec-v2.0 §17 | Rescue 流程倒數第三步 `CLEAN FORK / NEW SESSION / RESUME` |
| fork | F05-WDG-001 §5 | recovery ladder 倒數第二階 `clean fork` |
| fork | F08-CTX-001 §4 | rehydration 鏈的終點 `bounded RehydrationPacket` |

**`clean fork` 在三份規格裡都出現，而實作完全沒有。**
它不是新功能，是三份都要求而一份都沒做的那一塊。

---

## 3. 已經做到哪裡（2026-09-11）

做得出一條有顏色的線了，但那是工具不是產品：

`tools/timeline.py` 跑這個 session 的 transcript，131 輪，
OK 112 / WATCH 15 / CORRECTED 4。四個紅點裡，第 114 輪是真的
（owner 抓到取樣錯誤那一刻），另外兩個是誤判，而且今天最嚴重的
兩次它一個都沒抓到。

也就是說：線畫得出來，判準還太粗。

**缺的：** 桌面 App（零）、UI（零）、fork（零）、
節點點開看原文（有資料但沒有介面）。

---

## 4. 為什麼底層要先做，以及底層的邊界在哪

工程書 Phase 0 明令不做 UI，理由是「沒有事件帳本之前畫什麼都是假的」。
那條成立：一條顏色亂標的線，比沒有線更糟，因為它看起來像有根據。

但底層不是無止境的。可以開始做 UI 的判準，照工程書 Phase 8 的
exit gate 原文：

> A user can inspect a historical incident and identify normal period,
> degradation onset, candidate first divergence, cost/progress,
> correction, recovery and evidence confidence.

現在做得到的：normal period、degradation onset、correction。
現在做不到的：candidate first divergence（判準太粗）、
cost/progress（沒接）、recovery（fork 沒做）、evidence confidence（有但沒接到線上）。

---

## 5. 這份文件為什麼存在

owner 2026-09-11 講這三件事的時候，這個 session 已經被壓縮過一次，
而那次壓縮吃掉的正是「我該讀什麼」（見
`.forseti/HANDOVER_FAILURE_2026-09-11.md`）。

一個方向如果只存在於 context 裡，下一次壓縮就會消失。
所以它落在磁碟上，而且進版控。

**給下一個 session：** 這三件是驗收標準，不是待辦清單上的其中三項。
底層做得再乾淨，這三件沒做就還沒落地。
