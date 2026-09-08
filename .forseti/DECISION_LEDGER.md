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
