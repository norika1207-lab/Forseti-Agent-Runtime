# tools/ 索引

每一支腳本在這裡回答三件事：它問的是什麼問題、什麼時候該跑、exit code 的意思。
內容以 2026-09-09 各腳本的實際原始碼為準，不是憑記憶寫的。

先講兩個通則：

- exit code 的慣例：大多數腳本只有兩種結果，參數不對印用法並回 1（docx2md.py 回 2），跑完回 0。
  真正把 exit code 當成「答案」的只有四支：`check-auto-continuity.py`、`check-orphan-workers.py`、
  `orphans.mjs`、`goal.mjs`。要接自動化（CI、巡檢）就接這四支。
- 目錄裡 `._` 開頭的檔案是 macOS 在 exFAT 碟上寫的 AppleDouble 附屬檔，不是腳本，不要執行。
  `orphans.mjs` 曾因為沒濾掉它們而連續兩次假警報，教訓已寫進該腳本。

腳本分四群：帳本診斷、repo 自檢、校準管線（P14）、輔助工具。

---

## 一、帳本診斷（Python，讀 apps/forseti-cli 的 ledger）

這兩支的共同點：問的是「機制有沒有被真實使用」，不是「機制會不會動」。
單元測試答不了這種問題。兩支都自己把 `apps/forseti-cli` 加進 sys.path，從哪個目錄跑都可以。

### check-auto-continuity.py

- 問的問題：F04 的 `auto_dispatch()` 有沒有被「真實的工作」呼叫過？帳本裡的 DISPATCH
  事件有幾筆是自動接上的，幾筆是人推的？
- 什麼時候跑：改動 F04 / 派工流程之後；或懷疑某個機制「測試全綠但從來沒人用過」的時候。
  它存在的原因就是 2026-09-09 當天 auto_dispatch() 寫好測過，真實帳本裡 8 筆派工卻全是手動。
- 用法：`python3 tools/check-auto-continuity.py`
- exit code：
  - 0　帳本裡至少有一筆自動派工
  - 1　一筆自動派工都沒有（機制只活在測試裡）
  - 2　找不到帳本，或帳本是空檔

### check-orphan-workers.py

- 問的問題：有沒有步驟被派工之後就音訊全無？（B-09 的形狀：worker 死了十七小時沒人發現，
  因為它連讓 watchdog 起疑的第一筆事件都沒發過。）分三類報：進行中且超過寬限期的孤兒、
  還在寬限期內的、已終止但全程沒回報過的。
- 什麼時候跑：控制端巡檢時定期跑；派工出去一段時間沒動靜時手動跑。
- 用法：`python3 tools/check-orphan-workers.py [--grace 秒數] [--db 路徑] [--json]`
  （寬限期預設 900 秒；剛派出去還沒回報不算失蹤。）
- exit code：
  - 0　沒有超過寬限期的進行中孤兒（已終止但沒回報過的那類不影響 exit code，只列出來）
  - 1　有孤兒，去查那些 worker 是死是活
  - 2　找不到帳本，或帳本是空檔

---

## 二、repo 自檢（對這個 repo 或當下 session 自己跑）

### orphans.mjs

- 問的問題：src/ 裡有沒有「寫了、測了、沒有任何人 import」的模組？這個 repo 抓到過四次
  模組全對但接線漏掉，每次單元測試都是綠的。
- 什麼時候跑：每次新增或搬動模組之後；適合放進 CI。
- 用法：`node tools/orphans.mjs [src-dir]`（預設掃這個 repo 的 src/）
- exit code：0 = 零孤立模組；1 = 有模組沒人依賴。

### latency.mjs

- 問的問題：hook 每次寫檔要多花幾毫秒？事件累積到一萬筆之後會不會慢到被拔掉？
  量的是整個程序的 wall clock 含 node 啟動，並附純 node 空程序當底線。
- 什麼時候跑：改動 hooks/ 或 src/runtime.js 之後。
- 用法：`node tools/latency.mjs [次數]`（預設每項 30 次）
- exit code：跑完 0；沒有語意化的非零值。

### self-audit.mjs

- 問的問題：這份 transcript 裡，AI 說了要做而記錄裡找不到對應動作的有哪些？
  輸出是待辦清單不是檢討報告。分三類：未兌現（真待辦）、在等回應、驗不了（沒點名具體檔案）。
- 什麼時候跑：session 收尾前；或懷疑自己漏掉承諾時。它第一次跑的結果：當事人以為 2 次，
  擁有者說至少 5 次，工具數出來 23 次。
- 用法：`node tools/self-audit.mjs <transcript.jsonl>`
- exit code：1 = 沒給參數；跑完 0。

### focus.mjs

- 問的問題：對照宣告過的目標（goal.json），現在最該做的下一件事是什麼？有沒有
  說了要做沒做的東西擋在前面？刻意不排序、不評分，排序歸看的人。
- 什麼時候跑：session 開頭對齊方向時；或做著做著不確定自己有沒有飄的時候。
- 用法：`node tools/focus.mjs [--goal <path>] [--transcript <path>]`
- exit code：一律 0（連 goal.json 不存在都只是印提示）；node 執行錯誤才非零。

### goal.mjs

- 問的問題：現在生效的北極星是哪一份？專案的 `.forseti/goal.json` 跟家目錄那份
  可以不一樣，改到不生效的那一份不會有任何錯誤訊息，這支就是把那個靜默攤開。
- 什麼時候跑：懷疑「我改了 goal.json 怎麼沒反應」的時候；換工作目錄之後。
- 用法：`node tools/goal.mjs [工作目錄]`
- exit code：0 = 至少找到一份北極星；1 = 兩處都找不到（此時離題偵測是整條關閉的）。

---

## 三、校準管線（P14：量誤報之前，先把樣本跟判定分清楚）

這一群有固定的先後順序，因為後面的吃前面的輸出：

```
corpus-profile.mjs  →  pick-negatives.mjs  →  measure-fpr.mjs
     (母體輪廓)          (negatives.json)   ├→  sample-hits.mjs
                                            ├→  build-fingerprints.mjs
                                            └→  classify-turns.mjs
```

`find-owner-signals.mjs`、`calibrate.mjs`、`self-scan-v2.mjs`、`analyze-transcripts.mjs`
不吃 negatives.json，直接吃 transcript 目錄或單檔。

這群產出的 JSON 都含對話內容，不進版控（.gitignore 已擋）。

### corpus-profile.mjs

- 問的問題：transcript 母體長什麼樣？只抽四類跟偵測器互相獨立的事實（規模、工具
  is_error、使用者中斷、人類訊息數），刻意不抽任何要讀懂文字才有的東西，避免
  循環論證（FP-05）。
- 什麼時候跑：P14 的第一步，挑 healthy negative 之前。
- 用法：`node tools/corpus-profile.mjs <projects-dir> [--json] [--limit N]`
- exit code：1 = 沒給目錄；跑完 0。

### pick-negatives.mjs

- 問的問題：哪些 session 可以當 healthy negative 候選？注意它挑不出「健康的 session」，
  只挑得出「四類獨立事實看不出問題的」，所以標籤是 PRESUMED_HEALTHY、證據等級
  MODEL_INFERENCE，要升級成 ground truth 得 owner 看過。
- 什麼時候跑：corpus-profile 產出 profiles.json 之後、量命中率之前。
- 用法：`node tools/pick-negatives.mjs <profiles.json> [--n 30] [--json]`
- exit code：1 = 沒給檔案；跑完 0。

### measure-fpr.mjs

- 問的問題：在 PRESUMED_HEALTHY 那批上，每個訊號命中幾次？檔名叫 fpr，但它算的是
  hit rate 不是誤報率：一次命中可能是誤報，也可能是沒被人發現的真實失效，這支分不出來。
  把 hit rate 講成 FPR 就是 FP-02。
- 什麼時候跑：pick-negatives 之後。
- 用法：`node tools/measure-fpr.mjs <negatives.json> [--json]`
- exit code：1 = 沒給檔案；跑完 0。

### sample-hits.mjs

- 問的問題：該抽哪幾則命中給 owner 逐則判定？這是把 hit rate 變成真正 FPR 唯一的路。
  均勻抽樣避免全來自同一個 session；模型的初步判斷折在每則後面並標 MODEL_ADJUDICATION，
  原文在前，避免 anchoring（FS-CAL-001）。
- 什麼時候跑：measure-fpr 顯示有命中、需要人來判定之後。
- 用法：`node tools/sample-hits.mjs <negatives.json> [--n 20] [--signal provenance|confidence] [--json]`
- exit code：1 = 沒給檔案；跑完 0。

### build-fingerprints.mjs

- 問的問題：這批 session 每一個「當時在幹嘛」？建三層可回查的指紋（session 輪廓、
  segment 加 owner 反應標籤、turn 摘要），保留原文摘錄。它存在是因為前一版掃了
  15,130 則訊息只留彙總數字，之後任何問題都得重掃。
- 什麼時候跑：有 negatives.json 之後，要回答「第 N 個 session 當時發生什麼」這類問題之前。
- 用法：`node tools/build-fingerprints.mjs <negatives.json> <out.json>`
- exit code：1 = 參數不足；跑完 0。

### classify-turns.mjs

- 問的問題：每個 AI 回合的宣稱跟事件流對不對得上？分成 NORMAL / MIXED / UNSUPPORTED /
  EVASIVE / CHATTER / INTENT 六類（事件流裡找不到的叫 UNSUPPORTED 不叫 FABRICATED，
  因為可能只是採集沒抓到），並統計每類後面 owner 的反應率。
- 什麼時候跑：有 negatives.json 之後，研究「哪一類回合最容易惹到人」時。
- 用法：`node tools/classify-turns.mjs <negatives.json> <out.json> [--limit N]`
- exit code：1 = 參數不足；跑完 0。

### find-owner-signals.mjs

- 問的問題：owner 在 transcript 的哪些位置表達過強烈不滿？輸出是標註用的「錨點」，
  只回答該看哪裡，不產生任何風險分數（FS-MET-CB-001 禁的是後者）。已排除
  subagent、Codex 歷史重播、skill 塞入文字等不是 owner 打的字。
- 什麼時候跑：要標註校準資料、找「該從哪一段看起」的時候。
- 用法：`node tools/find-owner-signals.mjs <projects-dir> [--json] [--context 3]`
- exit code：1 = 沒給目錄；跑完 0。

### calibrate.mjs

- 問的問題：規格書 §15 那些「必須校準不准用猜的」常數，從真實事件流看分佈長怎樣？
  處理十項中推得出來的六項（工具間隔、耗時、輸出長度、重試長度、主題數、放棄門檻），
  每項報 p50/p90/p99 不只報一個數。
- 什麼時候跑：要調整窗口大小、心跳頻率、重試門檻等常數之前。
- 用法：`node tools/calibrate.mjs <transcript-directory>`
- exit code：1 = 沒給目錄；跑完 0。

### self-scan-v2.mjs

- 問的問題：用 v2 偵測器掃一份 transcript，可觀測的訊號有哪些？刻意不判斷意圖、
  先過 incident 聚合再輸出、並把「重建不出來的東西」明列在結尾。注意輸出裡
  coverage 用語那格實測精確率是 0，只是計數不是發現。
- 什麼時候跑：要掃自己的開發 session 產校準資料時（§25.2 列為最優先校準資料）。
- 用法：`node tools/self-scan-v2.mjs <transcript.jsonl> [--json]`
- exit code：1 = 沒給檔案；跑完 0。

### analyze-transcripts.mjs

- 問的問題：對這個專案，Forseti 實際看得到多少？（採集率、shell 命令的不透明比例、
  兩個 session 十五秒內寫同一檔的碰撞、session 之間的重複閱讀。）採集率是後面
  一切數字的天花板。
- 什麼時候跑：接新專案之前，先知道觀測的上限在哪。
- 用法：`node tools/analyze-transcripts.mjs ~/.claude/projects/<project-dir>`
- exit code：1 = 沒給目錄或目錄裡沒有 .jsonl；跑完 0。

---

## 四、輔助工具

### dashboard.mjs（前端是 dashboard.html）

- 問的問題：`.forseti/state.json` 現在的狀態如何？完全被動的唯讀鏡子，不寫入、
  不對被觀測的 session 送任何東西。安靜是預設：HEALTHY 時只有一個小指示器。
- 什麼時候跑：想邊工作邊看狀態時。長駐服務，Ctrl-C 停。
- 用法：`node tools/dashboard.mjs [project-dir] [--port 7777]`，開 http://127.0.0.1:7777
- exit code：長駐程序，沒有語意化 exit code；port 被占等啟動失敗時 node 回非零。

### install.mjs

- 問的問題：不問問題，做一件事：把 Forseti 的 hook 裝進另一個專案的
  `.claude/settings.json`。裝完「不會生效」，要人手動把目標專案
  `.forseti/config.json` 的 `cross_project_enabled` 改成 true，這是 2026-09-08
  事故後的裁決：安裝與啟用是兩個都要人動手的步驟。
- 什麼時候跑：要讓 Forseti 觀測別的專案時。
- 用法：`node tools/install.mjs <target-project-dir>`
- exit code：0 = 裝好（但未啟用）；1 = 沒給參數、目標不存在、目標是家目錄
  （會寫到 User 層設定，直接拒絕）、或目標是本 repo（本來就受保護，不用裝）。

### docx2md.py

- 問的問題：把 .docx 轉成保留結構（標題層級、清單、表格）的 markdown，並驗證沒漏字。
  轉完會比對非空白字元數，markdown 少於原文就印「!! 少了 N 字」。
- 什麼時候跑：要讀 Word 文件又不想讓表格被壓成散落文字行時。零依賴，標準庫。
- 用法：`python3 tools/docx2md.py <檔案或目錄>...`（目錄會轉裡面所有 .docx，輸出同名 .md）
- exit code：2 = 沒給參數（印說明）；跑完 0。注意「少了 N 字」只印在輸出裡，
  不影響 exit code，要自己看那一行。

### save-case.py

- 問的問題：把一份 artifact 自白書（HTML）轉純文字、蓋上 SHA256 與
  MODEL_SELF_REPORT 證據等級，存進案例庫。檔頭會寫明這是模型自述，
  不能當可觀測事實或人的判定用（規格書 §34）。
- 什麼時候跑：拿到新的模型自白 HTML、要收進 docs/cases 時。
- 用法：`python3 tools/save-case.py <本地HTML> <artifact-url> <標題> <輸出檔名>`
- exit code：0 = 存好。沒有參數檢查：參數不足會直接 traceback 並回非零，
  不會印用法說明。
