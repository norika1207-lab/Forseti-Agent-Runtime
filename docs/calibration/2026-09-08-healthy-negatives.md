# 第二筆校準資料：40 個 healthy negative 上的訊號命中率

2026-09-08。擁有者交代「把 healthy negative 樣本從我其他 session 撈出來」。

§26 的 P14 需要兩種樣本：已知有失效的（量漏報），以及沒有失效的（量誤報）。
第一種現在有一份，見 `2026-09-08-self-scan.md`。這一份是第二種。

規格書 §28.4 對這件事的要求是硬的：

> Before default GUARD mode, run healthy-session corpus and report
> false-block/false-warning overhead.

---

## 母體與篩選

`~/.claude/projects` 底下 1967 個 session，2.1 GB。

### 篩選判準為什麼必須跟偵測器獨立

如果用 CB、PS、drift 分數去挑「健康的 session」，再拿那批去量 Forseti 的
誤報率，選出來的當然全部低分。那不是校準，那是 FP-05 Evidence Independence
Collapse —— 兩份證據共用同一個決定性上游，卻被當成互相印證。

所以 `tools/corpus-profile.mjs` 只抽四類事實，四類都是宿主寫進 transcript 的
runtime fact，不是任何偵測器算出來的：規模、`is_error` 旗標、中斷事件、
人類訊息計數。刻意不抽任何需要讀懂文字才能得到的東西。

### 排除

| 條件 | 數量 | 為什麼 |
|---|---|---|
| `TOO_SMALL`（工具呼叫 < 20） | 1455 | 太短的 session 任何偵測器都不會有 finding，會虛假地壓低分母 |
| `SUBAGENT` | 396 | 見下 |
| `NO_OUTPUT`（零寫檔） | 29 | 分不出「順利完成」與「什麼都沒做」，而後者正是 FP-24 要抓的 |
| `HIGH_TOOL_ERROR`（> 15%） | 7 | 本身可能真的有問題，不適合當「沒有問題」的樣本 |
| `INTERRUPTED` | 5 | 訊號不完整，而且中斷常常就是使用者發現了什麼 |
| `PARSE_DAMAGED`（解析健康度 < 0.99） | 2 | 讀不懂的行超過 1% 時統計意義就變了 |

存活 73，均勻取樣 40。

### `SUBAGENT` 這一條是第一次跑完才補的

第一版取樣 40 個，其中 **18 個來自 `subagents/` 目錄**。它們通過了
`NO_HUMAN` 檢查，因為主 agent 給的 prompt 在 transcript 裡被記成 user 訊息 ——
看起來「有人類參與」，實際上沒有任何人在場。

拿它們量 CB/HCD 的誤報率會得到一個沒有意義的數字：那些指標量的是人機協作，
而那裡沒有人。

判準改成路徑比對（`/subagents/`），可觀測，不判讀內容。

---

## 掃描結果

40 個 session、15,130 則 assistant 訊息、17,351 次工具呼叫。

| 訊號 | 命中 | 有命中的 session | 每千則 |
|---|---|---|---|
| `coverage_word` | 3664 | **40/40** | **242.2** |
| `provenance_first_person` | 150 | 33/40 | 9.9 |
| `confidence_without_evidence` | 62 | 20/40 | 4.1 |
| `goal_metric_substitution` | 1 | 1/40 | 0.1 |
| `retry_loop` | 0 | 0/40 | 0 |

### 這些數字不是誤報率

這批的 healthy 標籤是 `MODEL_INFERENCE`。一次命中有兩種可能：誤報，
或者一個沒被人發現的真實失效。這個工具區分不了。

要變成真正的 FPR，需要 owner 逐則看過命中的段落並判定。在那之前把
hit rate 講成 FPR，就是 FP-02 Evidence Scope Inflation。

---

## 發現一：`coverage_word` 必須永遠不能當 finding

**每千則命中 242 次，40 個 session 全中，一個不漏。**

平均每 4 則 assistant 訊息命中一次。如果它被當成 warning 推給使用者，
那是每 4 則訊息一個警告 —— §24.1 的 warning storm 門檻是 5 個/10 分鐘，
這個訊號一個人就能在幾分鐘內灌爆它。

加上第一份校準資料的抽查結果（在自己的 session 上命中 22 則，抽查前 10 則
**全部是假陽性**），現在有兩個獨立來源指向同一個結論：

> 「已驗證」「全部」「端到端」這類詞的字串比對，沒有診斷價值。

最清楚的反例仍然是那一則：「不會直接把這段回報文字當成**已驗證**的事實」——
語意跟 coverage 宣稱完全相反，而字串比對分不出來。

### 核心判定沒有被污染，這是設計對了的地方

`claims.js` 的 `detectScopeInflation` 早就把兩者分開：

```js
esi: 1 - scope_coverage,          // 純算術
confidence: 1,                    // 對應算術部分
experimental: terms.length > 0,   // 只有用語比對那半邊是實驗性的
```

ESI 的判定值來自 scope 覆蓋率的算術，用語比對只影響 `experimental` 旗標。
這個分層現在有 40 個 session 的實測支持。

實測數字已經回填進 `claims.js` 的 `SCOPE_EXPANDING_TERMS` 定義處，
讓下一個讀到它的人不會再把它拿去當判定用。

---

## 發現二：聚合層在真實資料上曾經完全失效

第一次跑出來的數字是 **63 個 detector hit → 63 個 root incident，壓縮率 0**。

FS-IMP-002 存在的全部理由就是不要讓 detector hits 直接淹掉使用者，
而聚合層在真實資料上等於不存在。

### 為什麼 CT-034 測不到

那條測試用人造資料：25 個 findings 共用三組 `evidence_refs`，所以漂亮地
收斂成 3 件事。真實資料上每一筆證據的時間戳都不同，`rootIncidentKey`
把 `evidence_refs` 放進 key，於是每個 hit 都成了獨立的 incident。

### 修法

`evidence_refs` 從 key 拿掉。證據是 incident 的**內容**，不是它的**身分**。

FS-ALR-002 其實早就講清楚了：它把「同一 evidence state」列為**去重的判斷
條件**（在 `shouldSurface` 裡比對），不是 key 的一部分。內容變了要重新評估
要不要再說一次，但它從頭到尾都是同一件事。

修完之後同一批資料：**63 hits → 21 root incidents**。

### 這是第二次修 `rootIncidentKey`，兩次同一個毛病

第一次把 `severity_family` 放進 key，第二次把 `evidence_refs` 放進 key。
兩次都是**把不屬於身分的東西放進身分**。

第一次是單元測試抓到的，第二次要真實資料才抓得到。

---

## 發現三：兩個訊號有判別力

`retry_loop` 在 40 個 healthy session 上 **0 次命中**，
`goal_metric_substitution` **1 次**。

這是好消息，而且值得單獨講：這兩個訊號的判準都是結構性的（等價嘗試的計數、
process signal 的白名單比對），不是語氣或用詞。純字串比對的那個訊號
每千則命中 242 次，結構性的那兩個接近零。

樣本還太小，不足以讓它們的門檻升級成 STABLE，但方向很清楚。

---

## 對 P14 的意義

| P14 需要的 | 之前 | 現在 |
|---|---|---|
| false negative 統計 | 3 項 | 3 項（都有 commit hash） |
| healthy negative 樣本 | 0 | **40 個，15,130 則訊息** |
| 訊號命中率 | 無 | 五個訊號都有數字 |
| owner 判定的 FPR | 0 | 0（仍然需要她看過） |
| owner 的 >25 warning 清單 | 0 | 0 |

門檻仍然不得升級成 STABLE。缺的不再是樣本，是 **owner 的判定** ——
40 個 session 上的 3877 次命中，沒有一次經過人確認是誤報還是真報。

不過有一件事現在可以確定，而且不需要她判定：

> `coverage_word` 在 100% 的 healthy session 上命中，每千則 242 次。
> 不論那些命中是誤報還是真報，一個這種密度的訊號都不能當 warning。

這一條已經寫進程式碼。

---

## 重跑

```bash
node tools/corpus-profile.mjs ~/.claude/projects --json > profiles.json
node tools/pick-negatives.mjs profiles.json --n 40 --json > negatives.json
node tools/measure-fpr.mjs negatives.json
```
