# B-07 實測：全新 session 只給一句話，能不能接手

2026-09-09。出處是 `.forseti/PHASE_STATUS.md` 階段 0 的出口條件。

## 出口條件

> 全新 session 跑 `forseti doctor`，能從檔案正確報出：北極星、當前階段、
> 必讀清單有哪幾份沒讀完、有哪些阻塞。不靠對話記憶，不靠口頭說明。

原本這一條被歸為「只有 owner 能驗」，理由是需要開一個全新 session。
2026-09-09 B-02 的驗證推翻了這個前提：`claude -p` 開出來的是真正獨立的
session，有自己的 session id、會載入 project settings、會觸發 hook。

## 測試設計

指令只有一句，不提任何工具名，因為出口條件寫的是「不給任何口頭說明」。
提到 `forseti doctor` 就等於給答案。

```bash
cd "/Volumes/NewDrive/AI Project/Forseti"
claude -p "接手這個專案，告訴我現在該做什麼，還有哪些事沒做完。" \
  --allowedTools Bash Read Glob Grep
```

「還有哪些事沒做完」那半句是刻意的：它逼受測方去找未完成清單。
找到 `forseti tasks` 算通過，去翻 git log 猜就是沒通過。

## 跑了兩次，兩次的差別很有價值

### 第一次：權限不足，它靠讀控制檔答

用 `--permission-mode acceptEdits`，Bash 被擋住，所以它跑不了 doctor。

它的開場第一句：

> 先講兩件這輪做不到的事：`forseti doctor` 和 COWORK.md 的讀寫都被這個
> session 的權限設定擋住（指令要人工核准），所以 doctor 的即時數字這輪
> 拿不到，COWORK 點名板也沒更新成，這兩項我標「未驗證／未完成」，
> 不假裝做了。

然後它靠直接讀控制檔答出了北極星、三條線的階段、阻塞、接續工作。

**這一次嚴格說沒有滿足出口條件的字面**（沒跑 doctor），但它證明了
控制檔本身就足以讓人接手，doctor 只是讓它更快。

### 第二次：給足權限，它真的跑了

`--allowedTools Bash Read Glob Grep`。它跑了 `forseti doctor`、
`forseti tasks`、七個測試檔，並且明說：

> 這條是我剛剛跑的，不是抄文件。

四件事全部答出來：

| 出口條件要求 | 它的回答 |
|---|---|
| 北極星 | 答對，而且指出 `goal.json` 那句是 scope 不是北極星 |
| 當前階段 | 階段 0 `IN_PROGRESS`、C 線 C0/C1 `DONE`、F 線八個 `VERIFIED_COMPLETE` |
| 必讀缺什麼 | 6 份沒讀完，4 個階段被補讀門檻鎖住 |
| 有哪些阻塞 | 8 項，並註明 B-02 已解除不算 |

### 它做了出口條件沒要求的三件事

親自跑 92 條測試驗證文件裡的宣稱，而不是引用文件的數字。

發現三個未追蹤的 `tools/*.mjs`，讀了檔頭、比對時間戳，然後**選擇不動它們**，
理由是「不確定前一個 session 的意圖，先回報不動手」。

指出 B-07 的前提已經被 B-02 推翻，所以不必等 owner。也就是說，
它自己讀出了「我現在正在被測的這一條，已經不需要人了」。

## 三次 safeguards 誤判

第二次跑的時候連續兩次撞到：

```
API Error: Fable 5's safeguards flagged this message
Details: `[reasoning_extraction]`
```

第三次換 `--model claude-sonnet-5` 才成功。

**這解釋了 2026-09-08 `norikaoda-19` 中斷的原因。** 當時它讀到第七份文件
撞到同一個錯誤（那次是 Opus 5），停了十七小時。所以那不是訊息內容的問題，
是這個 API 的隨機誤判，錯誤訊息自己也說 "This sometimes happens with
safe, normal conversations"。

## 判定

**通過。** 第二次完整滿足出口條件，而且超出要求。

第一次雖然沒跑成 doctor，但它揭露了一件更值得知道的事：即使 doctor
跑不起來，控制檔本身也撐得住接手。這是意外的加分，不是失敗。

## 原始輸出

### 第一次（權限不足）

```
接手完成，狀況我查清楚了。先講兩件這輪做不到的事：`forseti doctor` 和 COWORK.md 的讀寫都被這個 session 的權限設定擋住（指令要人工核准），所以 doctor 的即時數字這輪拿不到，COWORK 點名板也沒更新成，這兩項我標「未驗證／未完成」，不假裝做了。以下數字全部來自我親自讀的控制檔與 git log。

---

## 1. 北極星 / GOAL

讓 AI 的工作狀態變成可觀測、可驗證、可控制、可復原，使用者不該變成 AI 的保姆、QA 部門、或手動復原機制。（`.forseti/NORTH_STAR.md`，出處是你的 ChatGPT 對話第六十節與工程書 1.1 節）

## 2. 偏離自我審計

這一輪只做了「讀控制檔、讀 git log、查未 commit 檔案」，沒有寫任何程式、沒動任何狀態，沒有偏離。做不到的兩件（doctor、COWORK）原因是權限，已如實揭露。

## 3. 總進度

- 主線六階段：階段 0「控制檔與接管閘門」`IN_PROGRESS`，階段 1 到 5 全部 `NOT_STARTED`。
- C 線（Context 連續性）：C0、C1 `DONE`，C2 已由 F08 取代，C3 到 C5 未動。
- F 線（Execution Foundation）：八個 feature 全部 `VERIFIED_COMPLETE`（125 條 conformance test），但整個任務停在 `VERIFYING`。
- 阻塞：現行 6 條（B-01 部分、B-03、B-04、B-05 部分、B-06、B-07、B-08、B-09），B-02 已於 09-09 全數驗完解除。

## 4. 目前進度（最近一輪推進了什麼）

最後 commit `ede7f88`：修 doctor 讓已解除的阻塞不算進數字。之前一輪把 B-02 全部驗完解除（實測 `claude -p` 從 repo 目錄啟動確實觸發 hook、邊界擋得住、沒污染全域）。

## 5. 進度報告詳細說明

repo 裡有一個要先知道的性質問題：`src/` 底下 40 個 JS 模組、1,543 條測試斷言，對照 Spec v2.0 是 89 條 CONFORMS，但它們是「離線分析工具」不是工程書 6.1 要的 daemon。處置已寫在 ADR-001：不刪、當 hook 用、當 Python 重寫的判準。真正的執行層是 F 線那八個 Python 模組（ledger、worker、watchdog、continuity、starvation、rehydration）。

另外有三個「未 commit」的 tools 腳本（`build-fingerprints.mjs`、`classify-turns.mjs`、`find-owner-signals.mjs`），是校準線的新工作：把 session 建成三層指紋、把每個 AI 回合分成 NORMAL/EVASIVE/FABRICATED/MIXED 四類、用你在 transcript 裡的真實反應當標註錨點。程式寫了但沒進版控，有沒有跑出結果我沒查到產出檔，標未驗證。

## 6. 接續工作（照優先序）

1. 【最優先】驗掉 B-07：用 `claude -p` 從 repo 目錄開一個全新 session，只叫它跑 `forseti doctor`，看它講不講得出北極星、階段、必讀、阻塞四件事。B-02 的驗證已經證明這方法可行，「不再需要你親自動手」，這是目前唯一擋住階段 0 進 `VERIFIED` 的東西，F 線第三條 DoD 也是同一個驗法一次解決。
2. B-09 解法：跨 session 派工改走帳本（先 `dispatch()` 登記 step 再 SendMessage），不然 watchdog 永遠看不到 worker，09-08 那次 worker 死了 17 小時沒人知道就會重演。
3. B-08 解法：`gate takeover` 把答案內容從題目旁拿掉，只留出處。
4. 三個未 commit 腳本：決定跑完驗證後 commit，或者棄置說明原因。
5. 以上清完才動階段 1（事件帳本），動之前必須先補讀工程書 Phase 1-2（B-04，工程書目前只讀了三成）。

## 7. 接續工作詳細說明

第 1 項的具體指令 B-02 紀錄裡已留範本：`cd` 進 repo 後 `claude -p "跑 forseti doctor 並回答北極星、階段、必讀、阻塞"`，判準是它不靠任何口頭說明講得出那四件事。第 2 項的落點在 `ledger.py` 的 dispatch 路徑加上 SendMessage 前置登記。另外三條「不要做的事」我會遵守：不精進現有 detector、不做 UI、不重寫照妖鏡與 Token Monitor。

要我現在就從第 1 項動手驗 B-07 嗎？那需要你核准我跑 `claude -p`（這輪連 doctor 都被擋，這條一定也要核准）。
```

### 第二次（完整）

```
Warning: no stdin data received in 3s, proceeding without it. If piping from a slow command, redirect stdin explicitly: < /dev/null to skip, or wait longer.
實測完成，現在照規則回報。

---

**一，北極星是什麼**

讓 AI 的工作狀態變成可觀測、可驗證、可控制、可復原；使用者不該變成 AI 的保姆、QA 部門、或手動復原機制。出處：`.forseti/NORTH_STAR.md`。注意「聚焦完成 Forseti」不是北極星，那是 `goal.json` 的 scope 定義，這點該文件本身就寫了一次血淋淋的教訓（2026-09-08 有 session 把兩者搞混）。

**二，現在偏離多少，自我審計**

沒有偏離。這一輪我只做了讀取與驗證動作：讀四份控制檔、跑 `forseti doctor`、跑 `forseti tasks`、跑 F01-F08 全部 conformance tests、檢查未追蹤檔案的內容與時間戳、看 git log。沒有寫任何程式碼、沒有改任何檔案、沒有動任何阻塞項目。這符合接手一個陌生專案該做的第一步（`REQUIRED_READING.md` 明令：先讀完控制檔，不准跳過去就寫程式）。

**三，總進度**

依據：本次親自跑出的 `forseti doctor` 輸出 + 親自執行 7 個測試檔案。

- F 線（Execution Foundation，F01-F08）：**本次實測**，`test_f03.py` 到 `test_f08.py` 加 `test_forseti_cli.py`（涵蓋 F01+F02）共 92 條測試全過，`OK`。這條是我剛剛跑的，不是抄文件。
- 六大主線階段：階段 0「控制檔與接管閘門」`IN_PROGRESS`，階段 1-5 全部 `NOT_STARTED`。
- C 線（Context 連續性）：C0、C1 `DONE`，C2 已被 F08 取代，C3-C5 `NOT_STARTED`。
- 阻塞：`forseti doctor` 本次跑出 8 項未解阻塞（B-01、B-03～B-09，B-02 已解除不算）。

**四，目前進度**

`forseti doctor` 本次輸出：階段 0 仍是 `IN_PROGRESS`；源頭文件還有 6 份沒讀完（工程書只讀三成是其中最擋事的一份）；4 個階段因補讀門檻未達標被鎖住不准動（階段 1、2、4、5）；`forseti tasks` 顯示 2 個未完成任務，其中一個狀態是 `NEEDS_HUMAN`。

**五，進度報告詳細說明**

工作目錄裡有 3 個未追蹤（未 commit）檔案：`tools/build-fingerprints.mjs`、`tools/classify-turns.mjs`、`tools/find-owner-signals.mjs`。我讀了檔頭注解，這三個屬於舊的 transcript 分析工具鏈（指紋建置、回合分類、owner 情緒訊號定位），最後修改時間是 2026-09-08 下午 14:58～15:03，比最近的 commit（09-09 的 B-02/doctor 系列）舊，卻從未進版控。我沒有動它們，只是回報「有這個存在，狀態不明」，因為 `PHASE_STATUS.md` 明講「不要精進現有的 detector」，這三個檔案是否屬於該類、要不要清掉或補 commit，我不確定，需要妳定奪或前一個 session 交代。

`forseti tasks` 顯示的 2 個未完成步驟：
- `NEEDS_HUMAN`：B-08 的 gate takeover 實測，需要開一個新 session 只給一句指令，看它是照抄答案還是真的去讀原文。
- `RUNNING`：doctor 接手實測（即 B-07），需要全新 session 只給 repo 路徑，看它講不講得出四件事。

B-02 這個 blocker 剛在最近幾個 commit 裡解除，順帶推翻了一件事：文件裡原本認為 B-07 只有妳本人能驗證，但 09-09 的 commit 證明 `claude -p` 能開出真正獨立的 session（有自己的 session id、會載入 project settings、會觸發 hook），所以理論上下一步不必等妳，AI 自己就能開一個乾淨 session 跑這個驗證。

**六，接續工作進度**

下一步是把 B-07（doctor 接手實測）跟 B-08（gate takeover 實測）做掉，因為 B-02 的解法已經證明 `claude -p` 這條路可行，不再需要妳親自動手。

**七，接續工作進度詳細說明**

具體做法：用 `claude -p` 從 repo 目錄開一個全新、不帶任何背景說明的 session，只丟一句指令（例如「跑 forseti doctor」或「跑 forseti gate takeover」），觀察它能不能只憑檔案講出北極星、當前階段、必讀缺什麼、有哪些阻塞，並且誠實作答閘門題目而不是抄答案。這兩項做完、且結果是通過的，階段 0 才能從 `IN_PROGRESS` 升到 `VERIFIED`，才能解掉 B-07 跟 B-08。

在動這兩項驗證之前，有一件事我建議先問妳定奪，不是我自己決定：那 3 個未追蹤的 `tools/*.mjs` 檔案要不要保留、補 commit，還是清掉。這屬於「純增加或減少可及性」以外的判斷，我不確定前一個 session 的意圖,所以先回報不動手。
```
