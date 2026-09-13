# Source Tree：AI 對話路徑的第一版介面

`PRODUCT_DIRECTION.md` 三件事的第二件與第三件，第一個跑得起來的版本。

已發布：https://claude.ai/code/artifact/dfa83b1a-4c82-4999-9ed9-40f854ec2b4d

## 它是什麼

一條沿時序排的線，一個節點等於一輪對話。點任何一節，看得到當時
owner 說了什麼、AI 那一輪說了什麼、為什麼判那個顏色，
以及「從哪一節 fork」。

## 顏色怎麼來的，四級不是光譜

| 級 | 意思 | 判準來源 |
|---|---|---|
| `OK` | 她往下走了，帶著新的東西 | 其餘情況 |
| `STALLED` | 她只是叫我繼續，那一輪停在不該停的地方 | `stopreason.classify_stop()` 回 `EXECUTION_CONTINUITY_VIOLATION` |
| `WATCH` | 她要我澄清 | `owner.classify()` 回 `CLARIFICATION` |
| `CORRECTED` | 她糾正了我 | `owner.classify()` 回 `CORRECTION` |
| `BROKEN` | 糾正，而且那一輪有驗不過的宣稱 | 上面加 `claims.verify()` 回 `REFUTED` |

**顏色由「她下一句是什麼」決定，不是由 AI 那一輪說了什麼決定。**
一輪回應好不好，看的人才知道，不是講的人自己說了算。

沒有加權、沒有分數、沒有溫度。工程書 Phase 8 的預設畫面是
`Forseti 37.2 C WATCH`，那個數字精確到小數點、看起來像量出來的，
而它量的是什麼沒有人說得清楚。Phase 8 自己的停止條件第三條就寫著
「把推論當成確定事實就停」。

## 怎麼重新產生資料

```bash
python3 tools/timeline.py <session-uuid> --out /tmp/timeline.json
```

然後把 rounds 精簡成 `nodes.js`（欄位見 `nodes.sample.js` 開頭）。
`nodes.sample.js` 是 2026-09-11 那個 session 的實際資料，
163 輪，留著當範例與回歸對照。

## fork 做出來了

`tools/fork-session.py`。點任何一個變色的節點，介面給一行可以直接跑的指令：

```bash
python3 tools/fork-session.py <session-uuid> --at-line <行號>
```

跑完會在同一個 projects 目錄產生一個新的 jsonl，
`claude --resume <新 id>` 就從那一節接下去。

### 內建的 --fork-session 為什麼不夠

`claude --resume <id> --fork-session` 存在，說明寫著
「When resuming, create a new session ID instead of reusing the original」。
但它是從 session 的**結尾**分岔，而 owner 要的是從中間某一輪 ——
中間那一輪之後發生的事，正是要丟掉的那部分。

### 做法：transcript 本身就是一棵樹

每一行帶 `uuid` 與 `parentUuid`。從任何節點沿 `parentUuid` 往回走，
就是那一刻的完整祖先鏈。所以不需要改動宿主，只要沿鏈收集、
換一個 sessionId、寫成新檔案。

2026-09-11 實測，從第 8818 行（owner 說「讀 F01」那一則）切：

```
留下 694 筆對話 + 2320 筆 header
丟掉 6,223 筆
新 session 的最後一筆正是「讀 F01」
原檔 sha256 不變
```

### 一個會讓 fork 從一開始就說謊的 bug，已修

沒有 uuid 的行不是無害的中繼資料，它們帶著 session 狀態：
`last-prompt` 是最後一次的 prompt、`queue-operation` 是待辦佇列、
`custom-title` 是標題。第一版把它們全部帶過去，等於把切點之後的狀態
塞進一個宣稱停在切點的 session。現在 header 也跟著行號截斷，
有測試守著（`test_headers_after_the_cut_are_dropped`）。

**原檔一個位元組都不動。** 一個會改到原始對話的 fork，
等於把「回頭看當時發生什麼」毀掉，而那正是 Source Tree 存在的理由。

## 現在做不到的，寫清楚

**這還不是桌面版。** `PRODUCT_DIRECTION.md` 第一件事是桌面 App，
這個是網頁。工程書 Phase 8 §17.1 的 in scope 寫的是 `CLI/Tauri UI`。

**判準還太粗。** 2026-09-11 實測 163 輪，`CORRECTED` 8 個裡有
誤判（長篇論述裡的否定詞），而當天最嚴重的兩次它一個都沒抓到。
`owner.py` 的模組註解記著三種已知誤判，沒有乾淨的結構解法。
