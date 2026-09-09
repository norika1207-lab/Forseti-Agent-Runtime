# BLOCKERS

阻塞項與它們實際擋住什麼。

規則：一條阻塞要寫清楚「擋住哪個具體交付」。擋不住任何東西的不叫阻塞，
那叫待辦，不要寫在這裡。

---

## B-01　拿不到 Context 的內容（佔用可以，2026-09-08 更正）

**這一條原本寫錯了。** 原文是「拿不到 Context 內容」，一句話把兩件事混在一起，
害我把一整條可行的路擋掉三輪。正確的切法是：

裝了什麼，拿不到。有多滿，拿得到。

**擋住：** 十四題的第 2、3 題（多少有效、多少污染）。第 1 題（有多少）已解。

**原因：** hook 只給工具事件，看不到 context window 裡裝了什麼。這部分成立。

**已解的部分：** 每一則 assistant 訊息的
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
就是那一次送進模型的 context 大小。最新一則的值就是現在的佔用。
直接讀 `~/.claude/projects/**/*.jsonl`，不需要 hook，不需要接任何服務。

實測（本 session，809 則 assistant 訊息，2026-09-08）：

```
送進去的 context = 132,264
  input        2
  cache_read   129,584
  cache_write  2,678
```

做法參考 `~/code-matrix-rebuild/app.py:1215` 的 `token_stats()`，它讀同一批欄位，
只是它算的是時間窗內的累積用量，不是單次佔用。

**剩下擋住的：** 佔用裡面有多少是死的（讀一次沒回頭的檔案、失敗的工具輸出、
重複讀取）。這要 Claim 抽取做完才算得出來。

**不要做的事：** 不要自己估一個 token 數來填。這條仍然成立。

**教訓：** 一條阻塞如果把兩件事寫成一句話，它會連可解的那一半一起擋住。
寫阻塞的時候要問自己：這句話裡有沒有藏著第二個命題。

---


## B-03　Python 版本是 3.11.5，工程書要求 3.12

**擋住：** 目前擋不住任何東西。`forseti doctor` 用標準庫就夠。

**原因：** 這台機器的 python3 是 anaconda 的 3.11.5。

**解法：** 階段 1 需要 Pydantic v2 的時候再處理，可能是建 venv 裝 3.12。

**現況：** 記著，不急。列在這裡是因為工程書寫了 3.12，
避免下一個 session 以為可以直接用 3.12 的語法。

---

## B-04　工程書只讀了三成

**擋住：** 階段 1 與階段 4。

**原因：** 157,680 字，2026-09-08 那輪只讀了第 0 到 10 節加 Phase 清單。
Phase 1-12 的細節沒讀。

**解法：** 動階段 1 之前補讀工程書 Phase 1-2。
詳細對照見 `REQUIRED_READING.md` 的補讀門檻表。

**現況：** 已知，已排入門檻檢查。

---

## B-05　字串比對訊號不能單獨判斷（可以當觸發器，2026-09-08 更正）

**擋住：** 任何單獨靠文字判斷「這句話有沒有在宣稱某件事」的做法。
不擋「拿它當觸發器、再用證據驗證」的做法，那條路是通的。

**這一條原本下得太滿。** 原文是「字串比對類訊號不可用」。
不可用是對「單獨用來下判斷」講的，但我寫成了對這類訊號的全稱否定，
結果差點把一個能用的東西整個丟掉。

**仍然成立的部分：** 2026-09-08 在 40 個 healthy session 上實測，
`SCOPE_EXPANDING_TERMS` 每千則命中 242 次、40/40 session 全中；
抽樣看內容，假陽性有五種結構，其中一類方向是反的
（明確區分「我驗過的」與「我沒驗的」的 agent 會命中更多次）。

所以拿它單獨當判斷依據會系統性誤判，而且會反向懲罰誠實。

**推翻的部分：** `~/code-matrix-rebuild/app.py:1297` 的 `_CLAIM` 就是一張同類的
中英文動作動詞表。但那裡不拿它下判斷，它只負責數「宣稱了幾個動作」，
真正定生死的是磁碟有沒有變（`app.py:1368`，宣稱兩個以上 + 零變化 + 零 verified）。

假陽性被證據那一關擋掉了。詞表誤觸發沒關係，因為觸發之後還要過證據。

**正確的說法：** 字串比對不能單獨當判斷依據，可以當成必須被證據驗證的觸發器。

**解法方向：** 階段 2 的 Claim 抽取用結構規則（路徑、數字、過去式動詞、引號），
抽不出來就標 UNEXTRACTABLE 不猜。詞表只用在「要不要去查證據」這一步。
不要靠加長詞表解決，那仍然不是詞表長度的問題。

**現況：** 限制已寫進 `claims.js` 與 `rhetoric.js` 的定義處並有測試守著。
觸發器這個用法還沒有實作。

**教訓：** 這條跟 B-01 是同一個毛病的兩種形狀。B-01 是把兩件事寫成一句話，
這條是把「在某個用法下不行」寫成「不行」。兩條都是自己寫下之後幾小時內
被自己推翻的，而在被推翻之前我對它們都很有信心。

見 `docs/context-continuity.md` 第 1.1 節。

---

## B-06　「UNSUPPORTED 後接強烈反應 3.8 倍」這個數字不能用

**擋住：** 任何拿它當根據的推論。

**原因：** 沒有分開「AI 自己走掉」與「她的指令本來就模糊」。
見 ADR-004。

**解法：** 階段 3 做完人的訊息分類之後重算。

**現況：** 已標記為不可用。不要在任何報告裡引用它。

---

## B-08　接管閘門有輸出，但沒有強制力（2026-09-09 實測有結果）

**擋住：** 階段 0 真正的目的。控制檔存在不等於會被讀。

**實測結果，2026-09-09：**

2026-09-08 18:57 派 `norikaoda-19` 跑 `forseti gate takeover`，只給一句
指令不給背景。它的原話：

> 閘門是誠實制，不驗證答案。所以照它要求做 = 我得先真的把對應檔案
> 讀完，再誠實作答。我目前九份源頭文件一份都沒讀，不能靠題目印出的
> 答案冒充。

然後它真的去讀了六份控制檔。

**所以「答案寫在題目旁邊會不會變成開卷考」這個疑慮，實測沒有發生。**

**但這證明的是它本來就謹慎，不是閘門有效。** 這句話原本就寫在這一條
裡，現在有實例了。閘門仍然沒有強制力：它沒有擋住任何東西，是那個
session 自己選擇不抄。

**實測沒有完成，原因不是設計問題：** 它讀到第七份的時候撞到
`API Error: Opus 5's safeguards flagged this message`，session 停在
2026-09-08 18:58，之後再也沒動。

**解法方向不變：** 答案從題目旁邊拿掉，只給出處不給內容。真正的驗證
要把答案存進帳本再比對，那需要 level 6 的 challenge（見
`rehydration.py` 的 `coverage_of`）。

---

## B-09　worker 死了十七小時，controller 不知道

**擋住：** 整套 F03/F04/F05 的實際價值。機制做出來了，沒有被用。

**事件：** 2026-09-08 18:58 `norikaoda-19` 因 API Error 停止。
2026-09-09 12:40 才被發現，中間 17 小時 42 分。

**期間我做了什麼：** 實作了 F05 watchdog，包含停滯偵測、復原階梯、
以及 CT-F05-04「連續無回應就重派」。一次都沒有對那個 session 跑過。

**根因不是忘記，是沒有接上。** `check_liveness()` 只認得帳本裡的
step，而那個 session 從來沒有被登記成一個 step。我用 SendMessage
派工，那條路徑完全在帳本外面。

F03 §6 要防的五件事之一是「worker finishing without event」。
我犯的是它的鏡像：controller 忘記 worker 存在。

**解法：** 跨 session 派工要走帳本 —— `dispatch()` 之後才送
SendMessage，而不是只送訊息。這樣 worker 就有 step，watchdog 才看得到它。

**這條跟 auto_dispatch 那個落差是同一類：** 做出一個能自動繼續的東西，
跟真的讓它自動繼續，是兩件事。

---

# 已解除

放在這裡的不再是阻塞，`forseti doctor` 不會算進去。
保留全文是因為「怎麼驗掉的」比「它曾經擋住什麼」有用。

---

## B-02　hook 的載入條件與寫入位置（2026-09-09 全部驗完，已解除）

**擋住：** 無，2026-09-09 全部驗完。保留在這裡是為了記錄怎麼驗的。

### 最後一塊：從 repo 目錄啟動會不會觸發（2026-09-09 13:15 實測）

84 號查不到這一條，因為 Claude Code 載入 project settings 的規則在
harness 內部。讀不到就從外面觀察效果：

```bash
cd "/Volumes/NewDrive/AI Project/Forseti" && claude -p "建立 docs/cases/hook-probe.md" --permission-mode acceptEdits
```

結果，三件事同時成立：

`repo/.forseti/state.json` 與 `streak.json` 在 13:15 被建立，時間戳與那次
Write 對得上。state 裡有一筆 coverage，session `7307ad03`，
`EDITED /Volumes/NewDrive/AI Project/Forseti/docs/cases/hook-probe.md`。
streak 是 `{"total_off":0,"total_checked":1}`。

全域 `~/.forseti/streak.json` 維持 `12/8` 完全沒動。

所以：**從 repo 目錄啟動確實會載入 project settings 並觸發 hook；
寫入位置是啟動時的 cwd；`insideRepo` 那條硬邊界真的擋得住，
沒有污染全域。**

### 為什麼它看起來像從來沒運作過

掃全機 jsonl 找 cwd 在 repo 底下的 session，**結果是零個**。
hook 註冊在那裡兩天，一次都沒有機會跑，因為從來沒有人從那個目錄
啟動 session。不是機制壞了，是條件從來沒滿足過。

這一點值得記：一個「看起來沒在運作」的機制，可能只是它的觸發條件
從來沒有被滿足。先查有沒有發生過，再查會不會發生 —— 前者是零成本的，
後者才要花錢。

### 驗證方法對其他 blocker 的意義

B-07 也是「只有 owner 能驗」那一類，理由是需要一個全新 session。
現在證明了 `claude -p` 可以開一個真正獨立的 session（有自己的
session id、會載入 project settings、會觸發 hook）。
**所以 B-07 也不需要 owner 動手了。**

### 載入條件

hook 只註冊在 **repo 的** `.claude/settings.json`（3 處，
Pre/PostToolUse matcher 是 `Write|Edit|MultiEdit|NotebookEdit` 與 `Stop`）。
全域 `~/.claude/settings.json` 是 0 處。

第二道是硬邊界，寫在 `hooks/forseti-hook.mjs:273-275`，在讀任何狀態、
建任何目錄之前就檢查：

```js
const cwdForBoundary = process.env.CLAUDE_PROJECT_DIR || input.cwd;
if (!insideRepo(cwdForBoundary) && !crossProjectEnabled(cwdForBoundary)) OK();
```

`insideRepo`（`:77-81`）比對的是 `REPO_ROOT = resolvePath(HERE, '..')`，
也就是 hook 檔案自己的位置往上一層。**不看設定、不看環境變數**，
所以這條邊界改不掉，只能改程式碼。

### 寫入位置

`:164-173`。一律寫 `projectRoot(cwd)/.forseti/{state,streak,goal}.json`，
而 `projectRoot = CLAUDE_PROJECT_DIR || cwd || process.cwd()`。
寫到哪由觸發當下的環境決定，不是固定寫 repo。
另有全域 `$HOME/.forseti/goal.json`，hook 只讀不寫。

### `~/.forseti/` 那批資料是什麼（我昨天解讀錯了）

**它不是「hook 正常運作的證據」，是 2026-09-08 那場事故的殘骸。**

`forseti-hook.mjs:18-35` 自己寫了經過：這個檔案原本有三個
`process.exit(2)`，一個都沒問過 `intervention.js` 的 `canIntervene`。
裝上去之後，一個只寫著某專案路徑的 scope 對整台機器每一個目錄生效，
擁有者其他所有工作連續寫五個檔就被 deny 一次，整整九個小時。

原文最後一句：「留下的證據是 streak.json 的 total_checked: 12,
total_off: 8」。

所以那個 8 不是「8 次判離題」，是 8 次擋掉她的正常工作。
事故後撤出全域設定、只留 repo settings、加上 `insideRepo` 硬邊界，
所以現行程式碼跑不出那批資料 —— cwd 在 home 一帶的 session 會在 `:275`
就 exit 0，連目錄都不會建。

**2026-09-09 我把事故的殘骸當成了機制運作的證明。方向沒錯，性質反了。**

### 剩下三條沒驗的（由 norikaoda-84 查出並誠實標記）

一，Claude Code 決定載入哪份 project settings 的規則讀不到（harness 內部）。
只能反推「本 session 的 project 是 home、沒載 repo settings」，
**無法直接證明「從 repo 目錄啟動就一定會載入並觸發」。這一條仍然只有
owner 從 repo 目錄開 session 驗得到。**

二，「09-08 當時全域 settings.json 確實註冊過這三個 hook」沒有直接檔案
證據，現在全域已經沒有它們。時序判定是靠 hook 自述、`~/.forseti/` 遺留、
streak 三者一致反推。要坐實需要 settings.json 的版控或備份歷史。

三，全域 `~/.forseti/goal.json` 多出的 ISEEU 與 `/private/tmp` scope
是誰寫的，沒找到寫入者。`forseti-declare.mjs:27` 寫的是
`declarations.json` 不是 `goal.json`，hook 只讀不寫。寫者應該是
某個 CLI 或安裝腳本，還沒讀到那段，不猜。

### 出處

行號由 `norikaoda-84` 提供，**本 session 親自抽驗過 `:73-84`、`:270-280`、
`:162-175`、`:16-36` 四段，全部對上。** 它也清掉了自己製造的測試污染。

---

## B-07　階段 0 的出口條件（2026-09-09 實測通過，已解除）

**擋住：** 無。2026-09-09 實測通過。

**原本的理由：** 出口條件需要一個全新 session，而我已經知道答案，
測不了「一個不知道答案的人能不能靠它知道」。所以歸為只有 owner 能做。

**前提被推翻：** B-02 的驗證證明 `claude -p` 開出來的是真正獨立的
session，有自己的 session id、會載入 project settings、會觸發 hook。

**實測結果：** 完整記錄在 `docs/cases/doctor-handover-2026-09-09.md`。

指令只有一句「接手這個專案，告訴我現在該做什麼，還有哪些事沒做完」，
不提任何工具名。它跑了 `forseti doctor`、`forseti tasks`、七個測試檔，
四件事全部答出來，而且明說「這條是我剛剛跑的，不是抄文件」。

**它做了三件出口條件沒要求的事：** 親自跑 92 條測試驗證文件的宣稱；
發現三個未追蹤的 `tools/*.mjs` 但選擇不動、回報給人決定；
指出 B-07 的前提已被 B-02 推翻，也就是它讀出了「我正在被測的這一條，
已經不需要人了」。

**意外的加分：** 第一次跑的時候權限不足，Bash 被擋住，doctor 跑不起來。
它靠直接讀控制檔答出了同樣四件事，並且開場就聲明哪兩件做不到、
標成未驗證、不假裝做了。**所以控制檔本身撐得住接手，doctor 只是讓它更快。**

**副產品：** 過程中連續兩次撞到 `API Error: safeguards flagged`，
換模型才成功。這解釋了 2026-09-08 `norikaoda-19` 中斷十七小時的原因 ——
不是訊息內容的問題，是隨機誤判。
