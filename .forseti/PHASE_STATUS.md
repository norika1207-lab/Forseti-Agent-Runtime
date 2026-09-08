# PHASE_STATUS

最後更新 2026-09-08。階段定義出自 `docs/build-plan.md` 第五節。

---

## 現在在哪一階

**階段 0：控制檔與接管閘門**　狀態 `IN_PROGRESS`

---

## 這一階的出口條件

全新 session 跑 `forseti doctor`，能從檔案正確報出：
北極星、當前階段、必讀清單有哪幾份沒讀完、有哪些阻塞。
不靠對話記憶，不靠口頭說明。

**驗收方式：** 開一個新 session，只給它 repo 路徑，不給任何說明。
它跑完 doctor 之後要講得出上面四件事。講不出來就是這一階沒做完。

---

## 已有的證據

| 交付 | 狀態 | 證據 |
|---|---|---|
| `soul.md` | 已完成 | commit `28463fe` |
| `bible.md` | 已完成 | commit `28463fe` |
| `docs/build-plan.md` | 已完成 | commit `83b75ff` |
| `.forseti/NORTH_STAR.md` | 已完成 | 本次 |
| `.forseti/PHASE_STATUS.md` | 已完成 | 本次（這份） |
| `.forseti/DECISION_LEDGER.md` | 已完成 | 本次 |
| `.forseti/BLOCKERS.md` | 已完成 | 本次 |
| `.forseti/REQUIRED_READING.md` | 已完成 | 本次 |
| `forseti doctor` | 已完成 | `apps/forseti-cli/forseti.py`，16 條測試通過 |
| `forseti gate takeover` | 部分完成 | 列題目與出處，尚不驗證答案 |

### `forseti gate takeover` 為什麼只算部分完成

現在它只列六個題目與答案在哪個檔案，不驗證你答得對不對。
要驗證得把答案存進帳本再比對，那是階段 1 之後的事。

在那之前，這個閘門靠讀的人自己誠實。這件事寫在指令的輸出裡，
不藏 —— 一個宣稱在把關而實際上沒有的閘門，比沒有閘門更危險。

### 出口條件還差什麼

出口條件是「開一個全新 session，只給 repo 路徑，不給任何說明，
它跑完 doctor 能講出北極星、當前階段、必讀缺什麼、有哪些阻塞」。

指令本身做完了，但**這一條還沒有被真的驗證過**，因為驗證需要開一個
全新的 session。跟 `BLOCKERS.md` 的 B-02 是同一類：只有她做得到。

所以這一階的狀態是 `IN_PROGRESS` 不是 `VERIFIED`。
工程書 AI-04：WRITTEN 跟 VERIFIED 是不同狀態，不准跳。

---

## 六個階段的總覽

| 階段 | 名稱 | 回答哪幾題 | 狀態 |
|---|---|---|---|
| 0 | 控制檔與接管閘門 | — | `IN_PROGRESS` |
| 1 | 事件帳本 | 地基 | `NOT_STARTED` |
| 2 | Claim 與 Reality | 6、7 | `NOT_STARTED` |
| 3 | 人與 AI 雙向記錄 | 4、5 | `NOT_STARTED` |
| 4 | 健康與退化 | 9、10 | `NOT_STARTED` |
| 5 | Checkpoint 與 Fork | 13、14 | `NOT_STARTED` |

第 1、2、3、8、11、12 題的現況見 `docs/build-plan.md` 第 1.3 節。
第 1-3 題要等接上 Code Duo 才做得了。

---

## 這個 repo 現在的東西是什麼性質

**重要，接手的人先看這條。**

`src/` 底下 40 個 JavaScript 模組、1,543 條測試斷言、48 個測試套件，
對照 Formal Spec v2.0 是 89 條 CONFORMS、0 違規、46 條 CT 全過。

**但它們是離線分析工具，不是 daemon。** 事後拿 transcript 來跑，
不是對每個事件即時回答。工程書 6.1 節要的是後者。
這是性質差異，不是完成度差異。

處置見 `DECISION_LEDGER.md` 的 ADR-001：不刪，繼續當 hook 用，
同時作為 Python 重寫時的判準參考。

---

## 不要做的事

完整清單在 `docs/build-plan.md` 第四節。這裡列最容易誤觸的三條：

1. **不要精進現有的 detector。** 它們有實測的系統性假陽性，
   而且沒有事件帳本就沒有正確的輸入。
2. **不要做任何 UI。** 工程書 Phase 0 明令禁止。
3. **不要重寫照妖鏡與 Token Monitor。** 它們在 Code Duo，要接不要重寫。
