# Forseti 全文件重讀比對筆記

讀取日期 2026-09-15
讀取範圍 /Users/norikaoda/Library/CloudStorage/Dropbox/My project/Forseti Agent Runtime
讀取原則 依日期由舊到新逐份全文讀，最終判準以最新版本為準
撰寫原則 每份四欄：文件說什麼、我實際做了什麼、我做錯什麼、該調整什麼。沒親自讀到的不寫。

待讀清單共 23 份 .md
- [x] 0906 / AI_Runtime_Guardian_System_Architecture_Engineering_Spec_v2.0 (42.5KB, 817行)
- [ ] 0906 / Forseti_Agent_Runtime_System_Architecture_Engineering_Spec_v5.0 (112KB)
- [ ] 0906 / Guardian_Runtime_Intelligence_Product_Research_Strategy_Whitepaper_v1.0 (35KB)
- [ ] 0907 / Forseti_AI_First_Development_Engineering_Book_v1.0 (162.3KB)
- [ ] 0907 / Forseti_Five_Mechanisms_Handoff_v1.0 (49.6KB)
- [ ] 0907 / all.md (219KB)
- [ ] 0908 / Forseti_Formal_Specification_v2.0_Case_Calibrated (65.9KB)
- [ ] 0908 / Forseti_Formal_Specification_v2.0_Case_Calibrated_revA (76.8KB) 最終判準
- [x] 0909-1 / Vol1 Platform Constitution
- [x] 0909-1 / Vol2 Platform Architecture
- [x] 0909-1 / Vol3 Collaboration Protocol
- [x] 0909-1 / Vol4 Product Ecosystem Roadmap
- [x] 0909-1 / Design Evolution History
- [ ] 0909-2 / 00 Execution Foundation Architecture
- [ ] 0909-2 / F01 Persistent Execution Contract
- [ ] 0909-2 / F02 Task State Machine
- [ ] 0909-2 / F03 Main SubSession Context Isolation
- [ ] 0909-2 / F04 Event Driven Dispatch
- [ ] 0909-2 / F05 Watchdog Heartbeat Recovery
- [ ] 0909-2 / F06 Execution Continuity
- [ ] 0909-2 / F07 Output Starvation
- [ ] 0909-2 / F08 Context Isolation Rehydration
- [ ] _transfer_20260914 / 接手.md

---

## 01. Guardian 架構規格 v2.0（2026-09-04，最早的一份）

### 文件說什麼

名字還叫 AI Runtime Guardian，定位是「自主 AI 系統的可靠度控制平面」，明講不是 agent 框架、不是觀測 dashboard、不是記憶產品。

核心不變量一句話：AI 可以是錯的，但一個錯的宣稱絕不可以無聲地變成專案真相。

要守住四個連續性
- Truth 已驗證的執行現實與證據來源
- Intent 北極星、已接受的需求、被否決的選項、使用者的更正、範圍邊界
- Authority 誰有權把假設升格為事實、誰能批准不可逆動作、誰能改目標
- State 可持久的工作流、session、執行、checkpoint、runtime node 狀態

信任階層（第 3.3 節，由高到低）
擁有者的明確決定 > 決定性驗證器與已驗執行證據 > 正典專案狀態與決策帳本 > 帶來源的工具輸出 > 當前 agent 的推論 > 繼承來的交接摘要 > 過期記憶與快取 > 沒有支撐的假設

證據強度五級（第 7.2 節）
E0 模型自己說的，非權威
E1 工具輸出、未驗證路徑、快取狀態，弱
E2 新鮮的決定性檢查（stat/hash/git diff/API GET/process state），強
E3 多個決定性來源獨立佐證，很強
E4 擁有者確認、簽署政策、外部系統紀錄，正典候選

Claim 生命週期（第 7.1 節）
PROPOSED 到 EVIDENCE_REQUIRED 到 VERIFIED/REFUTED/UNKNOWN，只有權限才能升到 CANONICAL。
原文那句關鍵：一個宣稱不會因為多個 agent 重複它就變成正典，重複增加的是社會共識，不是證據強度。

填空衝動偵測器（第 8.3 節）
危險鏈是 UNKNOWN 到 貌似合理的推論 到 假定事實 到 沒有證據就動手。
正確鏈是 UNKNOWN 到 問/查/驗 到 假設 到 證據 到 決定。

認知分支五種型別（第 8.2 節）
MAINLINE 目前接受的目標與路徑
EXPERIMENTAL 刻意隔離的可能有用偏離
QUARANTINED 沒有支撐的假設或可疑漂移，只准讀跟驗
HARVESTED 從漂移裡萃取出的有用想法
CUT 已知有害的偏離，停止擴散並從最後健康節點復原

行為序列偵測（第 13 章，七種，全部是跨輪不是單點）
Thrashing、Busywork 零變更、Tool loop、Verification avoidance、Template degeneration、Goal erosion、Premature completion

最小介入治理（第 18 章）
八種結果 ALLOW / NORMALIZE / REPAIR / RETRY / QUARANTINE / ASK / BLOCK / ROLLBACK
原文的預設姿態：OBSERVE 99%, INTERRUPT 1%。噪音多的 Guardian 自己會變成另一個故障源。

十條不准倒退（第 26 章），其中直接打到我的三條
第 1 條 絕不把模型的自信當成權威或證據強度
第 7 條 絕不把每個爛答案都標成 context drift，route、cache、STT、fastpath、環境、authority 是不同的因果類別
第 8 條 絕不因為影響範圍大就介入，只有跨越政策紅線才准介入

最終判準（第 31 章）
在模型、session、程序、機器、agent 失敗之後，另一個行動者能不能復原同樣的已驗證現實、理解同樣的意圖、遵守同樣的權限邊界、從同樣的持久狀態繼續，而不用發明缺失的歷史。
是，就叫 Computational Continuity。如果答案取決於某個模型記得對話內容，就不是。

### 我實際做了什麼

對到這份的部分
- betrayal.py 對到 Claim/Evidence 的一小角，只做到「宣稱有沒有可查標的」
- starvation 對到第 13 章的 Busywork 零變更
- yieldcheck 對到第 13 章的 Premature completion
- intervene.py 對到第 18 章的八種結果，但我只做了六個動作而且沒有 NORMALIZE/REPAIR/ROLLBACK
- 桌面畫面對到第 16 章 X-Ray 的 Session Graph 一個視圖

完全沒做的部分
- Authority 整層，包含權限圖與衝突偵測
- State 整層，durable workflow 與 WorkflowStep
- Two-Phase Commit（DRAFT/PREPARING/PREPARED/AWAITING_APPROVAL/COMMITTED）
- RuntimeNode 與 runtime topology
- Source-of-truth registry（第 12.2 節那張表）
- Probe Packs（第 15 章）
- E0 到 E4 證據強度分級
- Claim 五狀態生命週期
- 填空衝動偵測器
- Context Sufficiency Gate（接手者先唯讀，通過理解測驗才准寫）
- 分支五型別
- 第 16.1 節八個視圖裡的七個（我只有 Session Graph）

### 我做錯什麼

第一，違反第 18 章的預設姿態。文件寫 OBSERVE 99% INTERRUPT 1%，我 2026-09-14 一整天在加 detector、加規則、加警告，方向與此相反。

第二，違反第 26 章第 7 條。betrayal 把不同因果類別的可疑現象往同一個判準塞，文件明講 route、cache、環境、authority 是分開的因果類別。

第三，第 24.2 節列的歷史回歸案例第 1 條，字面描述就是昨天發生在這個 session 的事：context 在交接前就塞滿，接手者只看到部分因果歷史，開始做錯的子問題。這份文件在 09-04 就把它列成必測案例，我在 09-14 親自重演了一次。

第四，第 31 章的最終判準我從沒拿來當驗收標準。我的驗收標準一直是「測試通過數」，那不是這份文件承認的判準。

### 該調整什麼

判準要換。不是「我接了幾個模組」，是第 31 章那個問題：現在如果這個 session 死掉，另一個 session 能不能不發明歷史就接著做。今天這一輪的起因正是這個判準失敗。

介入預算要有上限。第 18 章的 99/1 要變成程式裡真的存在的配額，不是寫在文件裡的態度。

證據強度要分級。現有的 CONFIRMED/CANDIDATE 兩級不足以表達 E0 到 E4，特別是分不出「工具輸出」跟「新鮮的決定性檢查」。
