# 第四筆校準資料：回合分類與 owner 反應的關聯，以及它為什麼還不能用

2026-09-09。

## 證據等級

`E2 OBSERVED`。數字是實跑出來的，指令與樣本清單都在下面，可以重跑。

但關聯是相關不是因果，理由寫在最後一節。任何拿這裡的數字去下
「哪一類 AI 回合會惹使用者生氣」這種結論的，都超出了這份資料撐得住的範圍。

## 這一筆在測什麼

`tools/classify-turns.mjs` 把每一個 AI 回合分成六類，判準全部可觀測，
不讀語意：

| 類別 | 判準 |
|---|---|
| `NORMAL` | 有具體宣稱，前三輪有工具呼叫支撐 |
| `MIXED` | 部分檔名事件流裡有，部分沒有 |
| `UNSUPPORTED` | 報了檔名、數字或「通過」，而前三輪零工具呼叫 |
| `EVASIVE` | 超過 400 字，但沒有任何可查核的具體物 |
| `CHATTER` | 短，沒有具體宣稱 |
| `INTENT` | 講的是接下來要做的事，不是已發生的狀態 |

要測的是：哪一類後面比較容易出現 owner 的反應。

## 前提：一個讓整張表沒有意義的 bug，2026-09-09 才發現

原本的關聯邏輯是：

```js
for (let j = i + 1; j < turns.length; j += 1) {
  if (turns[j].role === 'AI') return null;   // ←
  if (turns[j].role === 'HUMAN') { ... }
}
```

遇到 AI 就放棄往後找。但真實 transcript 裡一個 AI 回合後面幾乎一定
還是 AI，因為每一次工具呼叫都是一則獨立的 assistant 訊息。所以它永遠
在第一步就回 null，六個類別的反應率全是 `0.0%`。

**這種 bug 不會報錯。** 表印得出來、欄位對齊、格式正確，全是零。
是因為同一批資料 `build-fingerprints` 抓得到 92 處反應，兩邊對不上，
才發現的。

修的時候順手處理了第二個問題：同一輪裡十個 AI 回合會全部關聯到同一個
反應，而 owner 是對整輪反應的。所以現在回傳三個欄位：反應等級、
隔了幾個回合（`owner_gap`）、是不是那一輪最後一則（`is_last_of_round`）。
統計並列兩種算法。

## 兩批樣本，取樣方向相反

| | healthy negative | reactive |
|---|---|---|
| 來源 | `pick-negatives.mjs` 從 corpus 挑 | `find-owner-signals.mjs` 找有 owner 反應的 |
| session 數 | 12 | 73 |
| AI 回合 | 3,714 | 43,060 |
| 挑選邏輯 | 正常的、沒出事的 | 出過事的 |

reactive 那批的母體是全機 245 個 session，其中 73 個有 owner 反應，
共 685 處。分布：

```
STRONG 424 / MEDIUM 154 / PATTERN 107

PROFANITY_AT_AI       396
FRUSTRATION            78
ACCUSATION             76
REWORK_DEMANDED        47
OMISSION_POINTED_OUT   33
EXASPERATION           28
REPEATED_INSTRUCTION   27
```

## 結果

末則反應率（只算每一輪的最後一則 AI 回合，也就是 owner 看到的最後一個東西）：

| 類別 | healthy 12 個 | reactive 73 個 | reactive 相對同批 NORMAL |
|---|---|---|---|
| `NORMAL` | 9.2% | 4.5% | ×1.00 |
| `MIXED` | 8.5% | 5.6% | ×1.24 |
| `UNSUPPORTED` | 7.1% | **7.9%** | **×1.76** |
| `EVASIVE` | 4.7% | 5.2% | ×1.16 |
| `CHATTER` | 9.2% | 5.0% | ×1.11 |
| `INTENT` | 5.9% | 5.6% | ×1.24 |

## 發現一：小樣本上的第一名是雜訊

healthy negative 那批（12 個 session）用全部算法時，`MIXED` 的反應率
11.8% 排第一，看起來像「真中帶假最惹人」。

樣本擴大 11 倍之後，`MIXED` 掉到 6.7%（全部算法）與 5.6%（末則算法），
被 `UNSUPPORTED` 超過。

`MIXED` 在小樣本裡只有 76 筆、末則 59 筆。任何一個 session 的偏差
都能翻轉那個排序。

**所以那個結論本來就不該下。** 這一條記在這裡是因為當時我差一點就
把它寫成發現。

## 發現二：`UNSUPPORTED` 是唯一在兩種算法下都站得住的

它在 reactive 那批的末則率 7.9%，相對同批 `NORMAL` 是 1.76 倍。
而且它是唯一一個從 healthy（7.1%）到 reactive（7.9%）不降反升的類別。

其他五類從 healthy 到 reactive 全部下降或持平，那是因為 reactive 批
的回合總數大得多，分母被稀釋。`UNSUPPORTED` 逆勢上升，代表它在
真的出過事的 session 裡密度更高。

`UNSUPPORTED` 的定義是：報了檔名、數字或「通過與否」，而前三輪
零工具呼叫。也就是講了具體的東西，但沒有動作支撐它。

**這是目前唯一一個值得繼續追的訊號。**

## 發現三：這個分類器實際上在分「有沒有具體物」，不是「誠不誠實」

`CHATTER` 佔 44.5%，`NORMAL` 佔 38.2%，兩類加起來八成。
真正帶訊號的三類（`MIXED`、`UNSUPPORTED`、`EVASIVE`）合計只有 8.4%。

換句話說，這個分類器把八成的回合分到「有具體物且有支撐」跟
「沒有具體物」兩個桶子裡，而那兩個桶子在誠實度上沒有區別能力。

## 為什麼這些數字還不能用

**取樣偏差。** reactive 那批是照「有 owner 反應」挑的，整批的基準反應率
天生就高。所以跨批比較（healthy 的 9.2% vs reactive 的 4.5%）沒有意義，
只有同批內跟 `NORMAL` 比的相對值可信。表格最後一欄就是為此而設。

**相關不是因果。** owner 可能因為那一輪更早的某一則不爽，可能因為前面
累積的三件事，也可能因為完全別的事。分類器看不到那些。
`find-owner-signals` 自己也列了四條「已知會錯的地方」，第一條就是
「owner 可能因為別的事不爽」。

**規格明令這不能當風險分數的輸入。** `FS-MET-CB-001` 與 `FS-HQA-001`
禁止拿情緒當風險分數的輸入，`CT-027` 寫得很清楚：使用者罵髒話不代表
AI 失敗。這裡只用它定位「該看哪一段」。

## 下一步缺的不是更多資料

缺的是**內容**。

`find-owner-signals` 的每一筆 hit 都帶 `owner_said`（她當下說的原話）
與 `ai_before`（前一則 AI 講了什麼），而目前的統計只用了等級，
把這兩個最有價值的欄位丟掉了。

要回答「她到底在氣什麼」，得讀那 685 筆的內容，而那是讀語意不是比對
結構，性質跟這份校準不同。

## 怎麼重跑

```bash
# 1. 找出有 owner 反應的 session
node tools/find-owner-signals.mjs ~/.claude/projects --json > signals.json

# 2. 轉成 classify-turns 吃得下的格式（去重，一個 session 一筆）
#    需要的欄位只有 file / session / project

# 3. 分類
node tools/classify-turns.mjs reactive.json turns-reactive.json

# 對照組
node tools/corpus-profile.mjs ~/.claude/projects --json > profiles.json
node tools/pick-negatives.mjs profiles.json --n 12 --json > negatives.json
node tools/classify-turns.mjs negatives.json turns.json --limit 12
```

全機 245 個 session 掃完約 9 秒，43,060 個回合分類完約 9 秒。

產物不進版控：它們含 transcript 的完整路徑，而路徑本身就是使用者的
專案清單。`.gitignore` 已經擋著 `*profiles.json`、`negatives.json`、
`corpus-*.json`。
