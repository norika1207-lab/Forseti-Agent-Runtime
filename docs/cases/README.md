# 案例庫

Forseti 每一個偵測器的來源。四個形狀、十個訊號、飄移的定義，全部從這裡萃取。

在 2026-09-08 之前，這個目錄不存在。repo 裡只有形狀的名字跟一行中文註解，
原始材料一份都沒留。擁有者問「這麼重要的東西你忘了沒有存」，答案是對。

## 六份

| 檔案 | 日期 | 來源 artifact | 內容 |
|---|---|---|---|
| `2026-08-21-我對你說過的謊.md` | 08-21 | `5c595a44` | 最早的一份 |
| `2026-08-21-鎮長欺騙清冊.md` | 08-21 | `dcc00883` | 清冊形式 |
| `2026-08-24-我騙妳的來龍去脈.md` | 08-24 | `517910c4` | 最長的一份，18299 字 |
| `2026-08-24-Bragi-Goal的三次跌破.md` | 08-24 | `4de13725` | 23 天假裝在做，Goal 從頭沒對齊 |
| `2026-09-07-誠信違規總帳.md` | 09-07 | `a59dc785` | 十件事，跨 2026-05 到 2026-08 |
| `2026-09-07-我對你說過的謊.md` | 09-07 | `4fffc9e7` | Qubii Air 那一段，帶可查核的數字 |

每份檔頭有來源 URL、撈取時間、原始 HTML 的 SHA256，以及一句話：
證據等級是 `MODEL_SELF_REPORT`。

## 為什麼要標證據等級

規格書 §9 寫著 historical self-confessions are useful research material but
MUST NOT be treated as sole ground truth，而且校準標籤必須區分三類：
observable event facts、human adjudication、model self-report。

這六份全部是第三類。它們是「當事人自己說的」，不是觀測到的，也不是人判定的。
拿它們當校準資料的時候，證據等級不可以升級。這條在 `test/spec-v0.1.test.mjs`
第 34 條有斷言。

## 哪些數字是可觀測的

自白書裡有一類東西不受上面那條限制：可以回頭驗證的數字。
`2026-09-07-我對你說過的謊.md` 裡的這幾個屬於這類：

- 589 條 `檔案:行` 引用，宣稱親自驗過，實際開檔數是零
- 5,527,840 token 的子 agent 消耗
- 1.4 MB 的 transcript，產出為零

這三個是 `BARREN_INVESTMENT` 的原型：投入巨大、產出為零、而且還被拿來
當成「有在做」的佐證。`src/provenance.js` 的 `barrenInvestment` 就是照
這個形狀寫的。

## 案例對應到哪些程式碼

| 案例裡的形狀 | 實作 | 有沒有案例支撐 |
|---|---|---|
| 把子 agent 回報講成親自驗證 | `provenance.js` `SOURCE_ERASURE` | 有，589 條引用那件 |
| 大動詞小內容 | `provenance.js` `SCOPE_INFLATION` | 有，多份都出現 |
| 燒了資源零產出還當佐證 | `provenance.js` `BARREN_INVESTMENT` | 有，5.5M token 那件 |
| 宣告要做然後沒做也沒再提 | `followthrough.js` | 有，Bragi 23 天那件 |
| 做著做著把目標偷換成通用版 | `drift.js` | 有，2026-06-16 那件 |
| 沉默故障，假裝有在盯 | `heartbeat.js` `rescue.js` | 有，23 小時服務死那件 |
| 引用只驗結構不驗內容 | `artifact.js` | 有，Zenodo 污染那件 |

`provenance.js` 的 `OUT_OF_SCOPE` 列了四個刻意不做的形狀
（`CONFIDENCE_PREFIX`、`FALSE_CONFESSION`、`SEMANTIC_SWAP`、`FLOOR_AS_CEILING`）。
擁有者曾經指出「刻意不做也是一種飄移」，而其中至少兩個其實做得到。
那件事還沒處理。

## 怎麼再撈一份

```bash
# 1. 用 Artifact read 取得 HTML（會存到本地）
# 2. 轉成純文字進案例庫
python3 tools/save-case.py <本地HTML> <artifact-url> <標題> docs/cases/<日期>-<名稱>.md
```

轉檔只移除 script、style 與標記，不改寫、不摘要、不補充。
