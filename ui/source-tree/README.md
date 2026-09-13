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

## 現在做不到的，寫清楚

**fork 只畫得出位置，按不下去。** `claude --resume <id>` 目前只能從
session 結尾接，從中間某一輪 resume 還沒有做出來。介面上那一段
明寫了這個限制，沒有畫一個按不下去的按鈕假裝可以。

`clean fork` 在三份規格都出現而實作完全沒有：
`F05-WDG-001` §5 recovery ladder、`F08-CTX-001` §4 rehydration 鏈、
`spec-v2.0` §17 Rescue 流程。

**這還不是桌面版。** `PRODUCT_DIRECTION.md` 第一件事是桌面 App，
這個是網頁。工程書 Phase 8 §17.1 的 in scope 寫的是 `CLI/Tauri UI`。

**判準還太粗。** 2026-09-11 實測 163 輪，`CORRECTED` 8 個裡有
誤判（長篇論述裡的否定詞），而當天最嚴重的兩次它一個都沒抓到。
`owner.py` 的模組註解記著三種已知誤判，沒有乾淨的結構解法。
