# 自動接續，每一輪做了什麼

`forseti-auto-continue` 這個排程每 30 分鐘跑一次，過閘門就挑一項做完。

## 這份為什麼跟 `NEXT.md` 分開

`NEXT.md` 是 `handoff.py` 自動產生的，最小間隔 240 秒，
**寫在裡面的手動內容會被下一次覆蓋掉。** 它的欄位全部從帳本與
`work()` 算出來，沒有「這一輪做了什麼」這種欄位，也不該有 ——
那一支刻意不自己判斷任何事，避免變成第二個事實來源。

所以自動接續每一輪的紀錄放這裡，這份沒有程式會覆寫它。
`NEXT.md` 只放指標，指回這份。

---

## 2026-09-16 14:2x　救援流程串起來，實際在 327 輪的真實線上走過一次

挑的是 `ROADMAP.md` 的 P0 第 1 項（Vol4 Stage 4 的出口條件）。
那一項的原話是「三個零件都齊了，缺的是沒有人真的走過一次」。

### 做完的

新模組 `apps/forseti-cli/rescue.py`，把 `divergence` 算出的分歧點、
`checkpoint` 存的可回去的點、`forkline` 的切線串成一條路，
每一步往 Event Ledger 寫一筆，用的是 v5.0 §6.2 Recovery 類底下
本來就有的三個 type：`INCIDENT_OPEN`、`CHECKPOINT`、`CLEAN_FORK`。
三筆共用同一個 incident id，所以事後查得出它們是同一次救援。

**回去的點只有兩個合法來源**，沒有第三個：有人親手標成 last_good 的
checkpoint（人的判斷優先），或 `divergence.fork_before`（第一個真的
造成後果的區段之前）。兩個都沒有的時候回 `can: False` 並說明缺什麼，
**不猜一個輪號** —— 猜出來的 fork 點會把還好的工作一起丟掉，
而且不會有人發現，因為新線看起來很正常。

畫面上多出一格（面板展開後的第一格，在卡片之前）：

    退回去的話：第 206 輪　你自己標的
    會排除第 206 到 379 輪，共 174 輪。原本的一個字都不動
    [看那一輪]　這條線救過 1 次，走完的 1 次

### 真的走過一次，數字是真的

對 `a280762a-3c8c-489e-8f01-bb869918fbac`（327 輪的 Forseti 開發主線）跑：

| 項目 | 值 | 哪來的 |
|---|---|---|
| 回到哪 | 第 206 輪 | 她 13:16 標的 `cp-d94afd4c95` |
| 那一輪她說的話 | 「這個更準」 | transcript 第 12734 行 |
| 排除範圍 | 第 206 到 378 輪 | rows 最後一輪減回去的點 |
| 帶過去的節點 | 1577 | `forkline` 數的 |
| 丟掉的節點 | 10905 | `forkline` 數的，不是自己算的 |
| 事故 id | `inc-1b82df3e60` | 三筆事件都掛這個 |

`rescue.history()` 從正本重組得回來：1 次、走完 1 次、三筆齊全。
正本最後三行的 type 就是那三個。

**第 206 輪同時是兩件事的落點**：她標 last_good 的那一輪，
也是 `divergence` 算出的 `first_consequential`（她出手糾正，
OBSERVED 級的人力代價）。這兩件事不是互相印證 ——
她很可能就是照著畫面上那個分歧點標的，共用同一個上游。

### 沒做的那一步，而且是刻意沒做

`dry_run=True`。最後那一步（真的在 `~/.claude/projects/` 建立新 session
檔案）**留給 owner 按下去**，理由是那條 session 會出現在她的側邊欄，
而她不在場。dry-run 仍然真的沿 parentUuid 走完整條鏈、數出真實的
kept / dropped，只是不寫檔。

**所以 Vol4 Stage 4 的出口條件還沒過。** 它要的是「至少一個真實專案
從失敗分支救回來」，而現在走完的是流程與帳本，不是那個檔案。
差的就是 `dry_run=False` 那一次。

### 順手修掉一個不會報錯的 bug

`_write_handoff(snap)` 原本排在 advice 那一段，而那時候 `snap` 裡
還沒有 `checkpoints`，所以 `.forseti/NEXT.md` 的「最後一個已知良好的點」
**永遠印「沒有」** —— 即使真的有人標過。症狀是兩個來源說法不一致：
畫面上救援那格說「你自己標的第 206 輪」，交接檔說沒有。

停機之後接手的人只看得到 NEXT.md，而它說無處可退。已移到
checkpoint 算完之後，並用原始碼位置檢查釘住（`test_handoff.py`）。
修完實測，交接檔現在印得出 `cp-376581b28a　第 253 輪`。

`handoff.py` 先前一條測試都沒有，這一輪補了 6 條。

### 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **668 passed**（接手時 621）
- 新測試 `tests/test_rescue.py` 18 條、`tests/test_handoff.py` 6 條、
  `test_ui_contract.py` 新增 `RenderersAreActuallyCalled`
- **反向驗證做過四次**，每一次都當場變紅再還原：
  拒絕時順手給輪號 → 紅；忽略 `last_good` 標記 → 紅；
  incident 不串接 → 3 條紅；挑 checkpoint 改成取輪號最大 → 紅。
  另外把 `renderRescue(d)` 的呼叫拿掉 → `RenderersAreActuallyCalled` 紅
- `node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功，`bash desktop/deploy.sh`
  守門測試通過、二進位對得上來源
- **畫面在瀏覽器裡真的看過**：用 `ui-harness` 的做法產 fixture
  （指定那條 327 輪的 session），量到那一格 400x86 且 inView，
  截圖確認文案，點「看那一輪」實測跳到第 206 輪（top 806，在視窗內）

### 一個實測抓到的錯

「看那一輪」原本用 `jump()`，實測捲到 15886 之後目標節點還在視窗
上方 14273px —— 因為 `jump()` 不關「跟著最新」，下一輪 render
立刻把畫面拉回最底。改用 `jumpTo()`（它會關掉跟隨並閃一下）之後
量到 top 806，在視窗內。

**`renderCards` 的「看第 N 輪」按鈕有同一個問題**，這一輪沒動它——
改它要另外驗一輪，而且它不在這一項的範圍裡。記在這裡免得忘記。

### 沒解決的，留給下一輪

**一，`deploy.sh` 仍然回報「視窗沒出來，視窗數 0」。**
進程確實在跑（`ps` 看得到），二進位時間對得上，所以不是沒開，
是 AX 列舉不到。上一輪已經動手兩次（排除了呼叫端權限那個假設），
**這一輪照規則沒有再動它** —— 同一個問題動手兩次沒好，
第三次之前要停手回報。上一輪留的下一步仍然有效：
暫時把 `tauri.conf.json` 的 `alwaysOnTop` 改成 false 重建，
數得到就證明是它；數得到之後不要把設定留成 false，
該改的是 `deploy.sh` 換一種驗法。

**二，救援的最後一步沒按下去。** 見上面「刻意沒做」那一段。

**三，`rescue` 那一格藏在收合的面板裡**，要按右上角溫度那顆才展開。
放在 header 外面會一直佔版面，而 §18 寫「持續大叫的治理工具
本身就是生產力失敗」，所以先放面板裡。要不要提到外面是她的決定。

---

## 2026-09-16 13:0x　宣稱查現實的結果接到畫面

### 做完的

把 `desktop_api.verified_claims()` 的結果接到桌面 App。

**接之前的狀況：** `verified_claims()` 從 2026-09-14 就在跑，
`claims.py` 真的去 stat 磁碟，結果寫進 `row["claims"]`。
而 `app.js` 一個字都沒讀它 —— `grep -c "s.claims" desktop/ui/app.js` 回 0。
後端算了兩天，畫面上零。

改了三個檔：

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/desktop_api.py` | 同一輪內按 `(subject, state)` 去重；加 `snap["claim_total"]`，值是從 rows 加總，不另外算 |
| `desktop/ui/app.js` | 樹狀每一輪加一塊可展開的徽章；統計列加「宣稱沒證實」 |
| `desktop/ui/app.css` | `.claimchk`、`.claimlist` 等五個 class |

### 一個刻意的取捨

徽章的顏色與文案都不用紅、不寫「說謊」。
`claims.can_refute()` 的規則是驗證器沒資格判假就不判假，
所以絕大多數會停在 UNKNOWN，那代表搆不到那個檔案，不是它騙人。
把 UNKNOWN 染紅或寫成「說謊」，等於用這個面板犯一次 §32 講太滿，
而那正是它自己在抓的東西。`test_claims_wiring.py` 有一條專門守這件事。

### 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **597 passed**（接手時 587，新增 10）
- 新測試 `tests/test_claims_wiring.py`，10 條
- **反向驗證做過：** 把 `app.js` 的 `s.claims` 改成 `[]`，測試當場紅
  （`AssertionError: 's.claims' not found`），改回來再綠。
  不是一個永遠回 OK 的測試
- `node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功
- `bash desktop/deploy.sh` → 守門測試通過、二進位時間戳對得上
- **畫面實測：** 把 `app.js` + `app.css` + 一份真的 snapshot 內嵌成單檔，
  用瀏覽器載入跑起來，結果：
  `.claimchk` 1 個、`.claimlist li` 4 條、統計列出現「宣稱沒證實 4」、
  徽章文字「4 個宣稱查不到」、點一下 `display` 從 `none` 變 `block`、
  console 零錯誤。截圖裡看得到那塊灰色徽章

### 沒解決的，留給下一輪

**`deploy.sh` 回報「視窗沒出來，視窗數 0」。**

查到哪裡：直接跑 `~/Applications/Forseti.app/Contents/MacOS/forseti-desktop`，
Rust 日誌說

    [forseti] 視窗 main 存在 visible=true pos=... size=...
    [forseti] show 之後 visible=Ok(true)

而 `System Events` 數視窗回 0。進程活著（`ps` 數得到 1 個）。

**這跟這一輪改的東西沒有因果關係** —— 動的是 JS/CSS/Python，
沒碰 Rust 也沒碰視窗建立，而 Rust 說視窗建起來了。

`deploy.sh` 的檔頭註解記過同一個形狀（進程活著、Rust 說 visible=true、
系統回報 0 個視窗），當時的根因是 `rm -rf` + `cp` 打亂 LaunchServices 快取，
已經改成 `rsync`。所以現在這個是同形狀但不同根因，**沒查出來**。

還沒排除的另一種可能：`System Events` 數視窗需要輔助使用權限，
沒有權限時回 0 是假陰性，不是視窗真的沒開。
**這條沒驗證**，因為驗它要動 owner 的系統設定。

只試了一次就停手，沒有換各種變體反覆試。

---

## 2026-09-16 13:4x　接管閘門真的會批改了（P0-2）

### 做完的

`apps/forseti-cli/sufficiency.py`。v5.0 §17.3 的 Context Sufficiency Gate。

**接之前的狀況：** `blockread.py` 從 09-14 就有 `quiz()` 跟 `grade()`，
題目從原文抽。而 `forseti gate takeover` 印的最後一句是
「這個版本只列題目與出處，不驗證答案」。所以 `REQUIRED_READING.md`
那張七級量表上，任何文件最高只能到 level 5（我說我讀完了），
到不了 level 6（有人考過我）。B-08 記的就是這件事。

五個維度照 §17.3 原文那一句列的五樣，順序不換、不增減：

| 維度 | 原文 | 題目來源 |
|---|---|---|
| objective | current objective | `.forseti/NORTH_STAR.md` |
| decisions | accepted decisions | `.forseti/DECISION_LEDGER.md` |
| unknowns | unresolved unknowns | `.forseti/BLOCKERS.md` |
| last_good | last-good state | `checkpoints.jsonl` 裡被標 last_good 的那一筆 |
| effects | external-effect boundaries | `bible.md` |

改的檔：

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/sufficiency.py` | 新增。出卷、批改、權限狀態，append-only 帳本 |
| `apps/forseti-cli/forseti.py` | `gate takeover` 改成真的出卷；新增 `gate submit`、`gate status` |
| `apps/forseti-cli/desktop_api.py` | 新增 `sufficiency_state()` 與 `sufficiency` 指令 |
| `desktop/src-tauri/src/main.rs` | 新增 `sufficiency` command 並註冊 |
| `desktop/ui/app.js` | 「讀文件」那一頁底下多一塊接管閘門 |
| `tools/ui-harness.py` | fixture 補 `sufficiency` |
| `.forseti/BLOCKERS.md` | B-08 補一段：一半解決，另一半照原判斷不該用強制力解 |

### 三個刻意的設計，每一個都寫得出理由

**一，考卷不存答案明文。** §39 第 2 步
`Do not expose the canonical current-answer artifact yet`。
存的是正規化後的 `key_sha` 與 `key_len`，批改用滑動視窗比 hash，
比對語意跟 `blockread.grade` 一樣。**但這防的是錨定不是作弊** ——
讀得到 `.forseti/` 的 session 也讀得到出題原檔，題目還標了行號。
不假裝它擋得住。

**二，題目跨區塊等距取樣，不是抽滿就停。** 抽滿就停等於只考文件開頭，
而 `REQUIRED_READING.md` 記的她的原話正是「只挑標題重點看，
掃描前幾排字後面就略過」。等距不是隨機：同一份文件出的卷每次都一樣，
每次抽不同的題，考不過的多考幾次就會過，那不是門是轉盤。

**三，缺維度判 PASS_PARTIAL，不判死也不放水。** 五維只要有一維沒來源，
門就永遠開不了，而 §18 寫 `A noisy Forseti becomes another failure
source`。`PASS_PARTIAL` 拿得到權限，但帳本裡跟 `PASS` 是兩種東西，
查得出這一次有幾維沒驗到。

規格沒給的數字全部標成設定值：門檻 0.8 是 **CALIBRATION-CANDIDATE**，
§17.3 原文只說 `a configured comprehension threshold`。
最短答案長度 3 是我定的，不是規格值，理由寫在常數旁邊。

### 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **621 passed**（接手時 597，新增 24）
- 新測試 `tests/test_sufficiency.py` 19 條、`test_ui_contract.py` 3 條、
  `test_forseti_cli.py` 從 1 條改成 3 條
- **端到端實跑，不是合成：** `forseti gate takeover` 出卷 `d96db4042a33`，
  我自己去讀那八行原文作答，`gate submit` 回 **PASS，8/8，100%**。
  紀錄留在 `.forseti/sufficiency.jsonl`
- **反向驗證做過三次。** 把 `grade_one` 改成永遠回 True → 4 條測試當場紅；
  把 `renderTakeoverGate` 改回撞名的 `renderGate` → UI 契約測試當場紅；
  把 harness fixture 的 `sufficiency` 拿掉 → fixture 檢查當場紅。
  三條都不是永遠回 OK 的測試
- `node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功
- `bash desktop/deploy.sh` → 守門測試通過

### 一個差點釀成事故的撞名

新加的 UI 函式原本叫 `renderGate`，而 `app.js` 第 326 行早就有一個
`renderGate`（目標錨點閘門 FS-GOL-001），在 snapshot 渲染路徑上被叫。
JavaScript 不報錯，**後面那個直接蓋掉前面那個**。

Python 端本來就有同型檢查（`test_no_duplicate_top_level_defs`），
JS 端沒有。已補上 `NoDuplicateJsDefs`，而且用還原撞名的方式驗過它真的抓得到。

### 沒解決的，留給下一輪

**一，`deploy.sh` 仍然回報「視窗沒出來，視窗數 0」。**

上一輪留的那個假設這一輪驗掉了一半：
用 Finder 當對照組，`System Events` 數得到 5 個視窗，
**所以不是呼叫端沒有輔助使用權限**，Forseti 那個進程是真的沒有 AXWindow。

新的線索（**還沒驗證，只是讀設定讀到的**）：
`tauri.conf.json` 的視窗設定有 `alwaysOnTop: true` 加
`titleBarStyle: "Overlay"` 加 `hiddenTitle: true`。
macOS 上 alwaysOnTop 通常實作成 floating level 的 NSWindow，
那一類視窗不一定會被 AX 列舉。

下一輪可以這樣驗：暫時把 `alwaysOnTop` 改成 false 重建（編譯只要幾秒），
數得到視窗就證明是它。**數得到之後不要把設定留成 false** ——
那是產品行為，該改的是 `deploy.sh` 換一種驗法，不是改產品去迎合驗法。

這一輪只動手兩次就停了，沒有換各種變體反覆試。

**二，畫面那一塊沒有在真的視窗裡看過。**
靜態契約（CSS 變數、指令註冊、harness fixture、重複定義）四條都過，
但沒有像上一輪那樣用瀏覽器把它渲染出來看。原因是第一項沒解決。

**三，`sufficiency_enforce` 預設 false，這道門現在不擋任何人。**
要不要開是 owner 的決定，B-08 的判斷是不該用強制力解。

---

# 第 5 輪　2026-09-16 14:38 到 14:53　Health Curve（§16.1）

排程自動接續。supervisor 四道閘全開（停止開關 false、今日 0/40、
停了 12.8 分鐘、NEXT.md 有卡住的項目），所以往下做。

## 挑了哪一項，為什麼

ROADMAP 的 P1 第 4 項，Health Curve。挑它的理由是它落在
任務規則的第一類「能讓畫面上多出東西」，而且 ROADMAP 自己標了
「不是新演算法，是新畫法」，風險最低。

**順手更正一件 ROADMAP 的過期資訊：** P1 第 3 項 Correction Latency
標成「只差接起來」，實際上 `latency.py` 已經寫好、已接進
`strands()` 的 `snap["latency"]`、`app.js` 第 1603 行在用、
`tests/test_latency.py` 存在。那一項早就做完了。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/vitals.py` | 新增 `curve()`、`_curve_idx()`、`_rising_since()` 與三個常數 |
| `apps/forseti-cli/desktop_api.py` | `strands()` 多回一個 `health_curve` |
| `desktop/ui/app.js` | 新增 `renderHealthCurve()`，兩個呼叫點接上 |
| `desktop/ui/app.css` | 新增 `.hcurve` 那一組，跟八維度共用同一個 open 開關 |
| `tools/ui-harness.py` | 加 `--session` 參數 |
| `tests/test_vitals_curve.py` | 新增 13 條 |

## 三個刻意的設計

**一，曲線上每一點都是同一個 `dimensions()` 加同一個 `temperature()`，
只是把輸入從「全部的輪」換成「到那一輪為止」。** 沒有新演算法。
之所以要強調，是因為 ROADMAP 那條「不自己編算法填空」的禁令（§8.3）
正是畫線最容易踩的：太想要那條線平滑好看。

**二，脈絡與連續性兩個維度被排除在曲線之外。** 它們的來源是
`snap["context"]` 與 `snap["ledger"]`，都是「現在這一刻」的快照，
不隨輪次變。留著會讓整條線被同一個常數平移，看起來像歷史其實不是。
`temperature()` 本來就會跳過 coverage 0 的維度，所以這裡不改它的算法，
只把那兩維的 coverage 設 0。**排除這件事寫在畫面上**，不是只寫在註解裡。

**三，y 軸下限釘死 36.3，上限至少到 38.0。** 自適應 y 軸會把
0.7 度的波動畫成滿版的山谷。真實主線的溫度在 36.9 到 37.7 之間，
它本來就該看起來是平的。

## 一條測試當場抓到的說謊指標

`_rising_since()` 第一版用 `<=` 往回走（持平不該打斷一段上升），
但沒有檢查總升幅。真實資料上末端完全持平，於是它回報
「從第 49 輪開始退化，升幅 0.0 度」。`test_一路下降就沒有退化起點`
當場紅。**一個升幅 0 的退化起點就是在說謊**，改成回 None。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **681 passed**（接手時 668，新增 13）
- **反向驗證兩次。** 把 `CURVE_EXCLUDED` 清空 → 3 條紅；
  把每一點改成拿全部的輪去算 → 5 條紅。還原後全綠。
  第三次是天然的：持平那個 bug 是測試先抓到我才改的
- **真實資料實跑：** 331 輪那條線（session `a280762a`，180 個有效輪），
  60 個取樣點，第 213 到 385 輪，溫度區間 36.9 到 37.7，
  最高 37.7 在第 268 輪（主因是進度維度），`rising_since` 回 None
- **畫面在瀏覽器裡真的看到了。** `tools/ui-harness.py --port 8793
  --session a280762a...`，展開「為什麼」之後那一格渲染出來：
  標題、輪號範圍、60 個點的 SVG 折線、最高溫的紅點、
  以及「2 個維度沒算進這條線」那一行。console 沒有錯誤
- `node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功，`bash desktop/deploy.sh`
  守門測試通過、部署完成、二進位 14:50 與來源同一顆

## 沒解決的，留給下一輪

**一，上一輪那個 alwaysOnTop 假設被推翻了。**

上一輪留的線索是「`alwaysOnTop: true` 讓 NSWindow 變成 floating level，
那一類視窗不一定會被 AX 列舉」。這一輪照它寫的方法驗了：
把 `alwaysOnTop` 改成 false、重建、重開，**AX 視窗數還是 0**。
設定已經還原（比對過還原後的 JSON 與備份完全一致），也重新建過部署過。

**不是 alwaysOnTop。** 到此為止這一輪對這個問題動手兩次
（先 pkill 重開排除「查太早」，再改設定排除 alwaysOnTop），
照規矩停手，不換第三個變體。

下一輪可以查的方向（**未驗證，只是知識層面的可能性，不要當結論**）：
macOS 的 activation policy。如果那個進程不是 Regular，
AX 不會列舉它的視窗。查法是讀 Rust 端有沒有設 activation policy，
而不是再改一次設定重建。

**二，這個 repo 在同一時間有別的 session 在改。**

14:50 左右執行 `desktop/deploy.sh` 收到
`line 90: unexpected EOF while looking for matching "`，
三分鐘前讀到的 93 行版本裡沒有那個語法問題。
再跑一次就正常了，而且輸出多了一句上一版沒有的
「沒有開視窗（要開就 FORSETI_OPEN=1 再跑一次）」。
現在 `deploy.sh` 第 69 到 73 行確實有 `FORSETI_OPEN`，那不是我加的。

同一時間被改的還有 `docs/READTHROUGH_forseti-dev_20260916.md`
與 `.forseti/advice_ledger.jsonl`。沒有其他 forseti 進程在跑，
所以來源是另一個 Claude session（排程每 30 分鐘一次，
`sessions` 清單裡有數個同名的「Forseti 自動接續」）。

**這是交接風險不是靈異事件：** 兩個 session 同時改同一個 repo，
一個在寫、另一個在執行，就會拿到半個檔案。
這一輪結束時我的六個改動都還在（逐一 grep 確認過），測試 681 全過。

**三，畫面只在 harness 裡看過，沒有在 `.app` 的真視窗裡看過。**
原因是第一項沒解決。`.app` 的前端資源是壓縮內嵌的，
`grep` 二進位找不到函式名（連既有的 `renderDims` 也找不到），
所以**不能用 grep 證明新畫面進了 bundle**。
能證明的只有時間序：`app.js` 14:44:43 改完，二進位 14:50:15 建出，
部署的與建出的是同一顆（deploy.sh 比對過 mtime）。


---

# 第 6 輪　2026-09-16 15:0x 到 15:1x　Blast Radius（§16.1）

排程自動接續。supervisor 四道閘全開（停止開關 false、今日 0/40、
停了 12.4 分鐘、NEXT.md 有卡住的項目），所以往下做。

## 挑了哪一項，為什麼

ROADMAP 的 P1 第 5 項，Blast Radius。P1 的第 3、4 項上一輪已經確認做完，
所以它是 P0 之外最前面那一項（P0 兩項都卡在 owner 要按的那一步）。

## 先查了再動手，結果查出 ROADMAP 有兩句不準確

**一，「事件帳本裡有 lineage 邊」不成立。** `event_ledger.py:117` 的
`LINEAGE_EDGES` 是只定義未實作，同檔 `SPEC_DEVIATIONS` 自己寫著
「等 claim 與 decision 存在」。從事件節點往下游走這條路沒有邊可以走。

**二，「缺的是查詢與畫面」不成立。** `src/cost.js` 早就有完整的
反向可達 BFS 與 CostVector（167 行，`test/cost.test.mjs` 有測試），
照的是五機制文件第 6 節 M4 的定義。

**所以真正缺的是第三件事：餵給它的真實 import 邊從哪裡來。**
如果沒有先查就動手，這一輪會變成第四次重複實作
（`sufficiency.py` 對 `gate.py`、`rescue.py` 那兩次之後的第三次）。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/blast.py` | 新增。`ast` 掃 import 邊，node 跑 `src/cost.js` 算 |
| `apps/forseti-cli/desktop_api.py` | `strands()` 多回一個 `blast` |
| `desktop/ui/app.js` | 新增 `renderBlast()`，兩個呼叫點接上 |
| `desktop/ui/app.css` | 新增 `.blast` 那一組，跟八維度共用同一個 open 開關 |
| `tests/test_blast.py` | 新增 20 條 |
| `.forseti/ROADMAP.md` | 第 5 項更正兩句不準確的描述，補完成狀態 |

## 刻意不做的一件事：不在 Python 重寫演算法

`jsbridge.py` 檔頭那句是理由：

> 重寫就會變成兩份會分歧的實作，而分歧的那天沒有人會發現。

所以 `blast.py` 只做 `cost.js` 沒有的那一半（真實 import 邊的抽取），
演算法照 `goalgate.py` 的做法用 node 跑那一份。
`test_跟cost_js算出來的一致` 拿同一組輸入兩邊各算一次比對五個維度，
**哪天有人在 Python 這邊順手重寫，那一條會紅。**

## 兩個當場被抓到的說謊指標

**一，解析率假摔到 0.184。** 第一版把標準庫（`json`、`time`、`pathlib`）
也算成「未解析」。那個數字看起來像「這張圖有八成漏抓」，
但專案內依賴圖裡根本沒有 `json` 這個節點。三類分開之後
（專案內成為邊、標準庫記進 external、相對 import 才是真未解析），
解析率是 1.0，第三方只有 `pytest` 一個，符合零依賴 ADR-009。

判定標準庫用直譯器自己給的事實，不是我維護的清單。
這台是 3.9.6，`sys.stdlib_module_names` 是 3.10 才有，
所以退回去讀 `sysconfig` 的 stdlib 目錄。
`test_標準庫清單不是空的` 釘住這一條，因為它壞掉會靜默把
每個標準庫都當成第三方。

**二，跨語言斷點虛報 28 個，真實只有 13 個。**
兩個 bug 疊在一起：`lstrip("${srcDir}/")` 是逐字元剝除不是剝前綴，
把 `cost.js` 啃成 `ost.js`、`intervention.js` 啃成 `ntervention.js`；
而且沒跳過 docstring，於是 `blast.py` 自己的說明文字
「路徑第一段目錄（cost.js 的預設」被算成一個斷點。
**一個虛報的斷點數跟一個虛報的 blast radius 是同一種病** ——
它讓人以為系統知道一件它其實不知道的事。兩個都有回歸測試。

## 誠實條款（第 6.4 節）怎麼落到畫面上

五機制文件第 6.4 節原話：一個會說謊的 blast radius 比沒有 blast radius
危險得多，一旦它騙過她一次，整個介面就變裝飾品。所以：

- 沒有 lcov → `uncovered_d1` 是 None，畫面寫「沒有覆蓋資料」不寫 0
- `live_conflicts` 的 0 → 畫面寫「不是 0 個衝突，是沒有資料」。
  **這一條是本輪自己加的。** `cost.js` 對空的 liveScopes 回 0，
  而 0 在畫面上看起來像「沒有衝突」。優先序最高的指標第一次騙人
  就會是在這裡，所以另外帶一個 `live_conflicts_source` 欄位
- 跨語言邊界標成斷點，不連邊
- 整個向量標為下界，這句話印在格子裡不是藏在註解

`cross_modules` 用的是 `cost.js` 的預設（路徑第一段目錄），
不是這個專案真正的子系統劃分。規格沒定義，所以不自己編一個，
但在畫面上標明它是什麼。這是 §8.3 禁止填空那一條。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **698 passed**（接手時 681，新增 17 條
  再補 3 條回歸 = 20 條，其中 3 條是 node 不在時 skip 的）
- **反向驗證三次，全部抓到。** 拿掉 docstring 跳過 → 1 紅；
  在 Python 端把 `d1_count` 灌水 → 2 紅（含防漂移那條）；
  假裝有 lcov 覆蓋資料 → 2 紅。三次還原後全綠
- **真實資料實跑：** 104 個檔案、129 條依賴邊、解析率 1.0、
  15 處跨語言斷點、外部 import 567 筆（第三方只有 pytest）。
  代價最高 `ledger.py`（10 直接、5 間接、3 模組），
  次高 `owner.py`（8 直接、13 間接）
- **畫面在瀏覽器裡真的看到了。** `tools/ui-harness.py --port 8796`，
  點「為什麼」展開之後那一格渲染出來：標題、104 檔 129 邊、
  8 行排行榜、四行誠實條款說明。`display` 是 block，console 沒有錯誤
- `node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功（exit 0），
  `bash desktop/deploy.sh` 守門測試通過、部署完成、二進位 15:11

## 沒解決的，留給下一輪

**一，點選互動還沒做。** 完成的定義是「點一個節點，看得到哪些檔案
依賴它」，現在畫面給的是代價排行榜前 8 名，不是點選。
要做點選要加 Tauri command，那是另一件事的份量。
**所以這一項算做完一半，ROADMAP 標的是「檔案依賴那一半」。**

**二，`live_conflicts` 永遠沒有資料。** 來源是 M3 的 WriteScope，
`src/admission.js` 有 `createWriteScope()`，但那條線沒有接到畫面這條線。
現在畫面誠實地說「沒有資料來源」，但那不等於這個指標有用了 ——
**優先序最高的那個維度目前是空的。**

**三，上一輪那個 AX 視窗數 0 的問題，這一輪沒有碰。**
上一輪已經動手兩次停手了，留的方向是查 macOS activation policy。
這一輪選擇做新功能而不是第三次去撞它，照的是「兩次沒好第三次停手」。

**五，收尾時我自己踩了一個坑，寫下來免得下一個也踩。**

要更新 `NEXT.md` 的時候我直接把 `desktop_api.strands()` 的 snapshot
餵給 `handoff.write()`。**那兩個是不同形狀的東西。** `handoff.render()`
要的是 `goal` / `stuck` / `unknowns` / `n` 這種已經算好的欄位，
而 snapshot 的鍵是 `north_star` / `blast` / `dims`。對不上的欄位
全部落到預設值，於是一份有北極星、有卡在哪、有還沒解決的狀態檔
被覆寫成一份空殼，連輪號都變成問號。

正確的呼叫點是 `desktop_api._write_handoff(snap)`，
那一支負責把 snapshot 轉成 handoff 要的形狀。它有 240 秒節流
（`handoff.MIN_GAP_S`，理由是 mtime 要保有意義），
所以重產之前要先把 `NEXT.md` 的 mtime 往回撥。

已經用正確路徑重產，內容與接手時讀到的一致（北極星、兩個卡住的任務、
`scope_match` 那個未解、必讀 20/30、輪號 1 全部回來了）。
**`NEXT.md` 不會反映這一輪做完的 Blast Radius**，那是設計：
它只反映帳本狀態，不自己判斷任何事，不然會變成第二個事實來源。
這一輪做了什麼在 ROADMAP 與這份 LOG 裡。

**四，這個 repo 仍然可能有別的 session 在同時改。**
這一輪沒有再遇到上一輪那種讀到半個檔案的情況。
收尾時逐一 grep 確認過六個改動都還在
（`blast.py` 的 `vectors()`、`desktop_api.py` 的 `snap["blast"]`、
`app.js` 的 `renderBlast` 定義加兩個呼叫點共 3 處、`app.css` 的 `.blast`、
`test_blast.py` 的防漂移那條、ROADMAP 的更正），測試 698 全過。

---

# 2026-09-16 15:2x 到 15:3x　自動接續

## 閘門

`supervisor.py --status` 回 `會不會喚醒: true`，沒有閘擋住，
原因是「NEXT.md 裡還有卡住的或沒解決的」，停了 12.4 分鐘，
今天喚醒 0 次（上限 40），停止開關 false。

## 挑了什麼

ROADMAP P1 第 5 項 Blast Radius 剩下的那一半：**點選互動**。

為什麼是這一項而不是別的：

- P0 第 1 項（真的救回一次）的最後一步 `dry_run=False` 明寫留給 owner 按，
  不是我能做完的
- P0 第 2 項（Context Sufficiency Gate）自己寫著「還沒做的，而且不該急著做」，
  要等 F04 的事件與 F05 的訊號接上來才判斷得了時機
- P1 第 5 項的完成定義是「**點**一個節點，看得到哪些檔案依賴它」，
  而現在畫面給的是排行榜，那是「十」不是「哪十個」。這一項的缺口
  定義明確，而且做完畫面會不一樣（不是為了盤點數字接輔助函式）

**動手之前先確認不重做。** `ls apps/forseti-cli/ | grep -i blast` 只有
`blast.py` 一個，`grep -rl blast` 命中五個檔（blast.py、desktop_api.py、
cost.js、app.js、app.css），沒有第二支在做同一件事。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/blast.py` | 新增 `detail()` 與 `_DETAIL_RUNNER`；修掉 `imports_of` 例外分支的元數 bug |
| `apps/forseti-cli/desktop_api.py` | 新增 `blast_detail()` 與 CLI 子命令 |
| `desktop/src-tauri/src/main.rs` | 新增 `blast_detail` command，路徑白名單，註冊進 handler |
| `desktop/ui/app.js` | 排行榜每行可點，新增 `showBlastDetail()` 與 `blastOpen`/`blastHtml` |
| `desktop/ui/app.css` | 新增 `.blHit` `.blDetail` `.blChip` 那一組 |
| `tools/ui-harness.py` | stub 支援帶參數的指令，fixture 加 `blast_detail` |
| `tests/test_blast.py` | 新增 9 條 |
| `.forseti/ROADMAP.md` | 第 5 項改成做完，補上做法與剩下的一件 |

## 一樣不在 Python 重寫演算法

名單本來就在 `cost.js` 的 `reverseReachable()` 裡（它回的是兩個 Set），
只是 `computeCostVector()` 只把 `size` 帶出來。所以 `detail()` 走
跟 `vectors()` 同一條路：node 跑同一份 `cost.js`。

`test_detail的數字跟vectors的數字一致` 拿同一組輸入兩條路徑各算一次，
比對 d1 長度、d2 長度、模組數三項。**哪天有人只改一邊，那一條會紅。**

## 順手修掉一個會讓整張圖炸掉的 bug

`imports_of` 的例外分支（SyntaxError / UnicodeDecodeError / OSError）
只 `return [], []`，但三個呼叫端全部寫 `e, x, b = imports_of(...)`。

所以 repo 裡只要出現**一個**語法錯誤的 .py，`collect()` 會以
`ValueError: not enough values to unpack` 整個炸掉，而錯誤訊息
完全不會提到是哪個檔造成的。測試 fixture 最容易長出這種檔。

實測重現過（建一個 `def (:\n` 的檔，`imports_of` 直接 ValueError），
修完加 `test_語法錯誤的檔不會讓整張圖炸掉` 釘住，
那條會同時驗「回三個值」與「collect 跑得完、壞檔仍是圖上的節點」。

## 誠實條款在這一支多了兩條

§16.1 原文問的是 files / workflows / sessions / external effects 四種，
`detail()` 只答得出 **files** 那一種。另外三種的處理：

**一，打錯的路徑不回空名單。** 回 `known: False` 加一句為什麼。
理由寫在測試裡：一個打錯的路徑跟一個沒有人依賴的檔，
在「d1 是空的」這個結果上長得一模一樣，而後者在畫面上讀起來是
「改它不會影響任何東西」。**那是一個會說謊的 blast radius 的標準形狀。**

**二，任務與 session 依賴回 `None` 不是 `[]`。**
`ledger.py:148-164` 的 tasks / steps 兩張表沒有任何檔案路徑欄位
（親自看過 schema，不是推測），所以「哪些任務依賴這個檔」
現在沒有資料來源。空清單讀起來是「沒有任務依賴它」，
那是一句沒有根據的話。畫面上印的是那一句「這不是 0 個任務」。

**三，`depends_on` 的方向相反要標明。** 它是「這個檔用了誰」，
d1 是「誰用了這個檔」，兩欄放同一張畫面最容易被讀反，
所以方向說明是必填欄位，`test_detail認得方向相反的那一欄` 驗它不是空的。

## harness fixture 的 stub 本來吃不到參數

`test_ui_contract.py` 當場抓到：`app.js 呼叫了 harness fixture 沒有的指令`。
但補 fixture 不夠 —— 原本的 stub 是 `FIX[cmd]`，完全忽略參數，
而 `blast_detail` 對不同檔要回不同東西。

所以 stub 改成支援「參數值 → 回傳」的表（`__by_arg`），
只預先算排行榜上那 8 個（每個要跑一次 node，104 個會讓 harness 起不來）。
**查不到的不回空物件**，回一句「harness 沒有預先算這一個」——
理由跟上面第一條同一條：空的明細在畫面上讀起來像「沒有人依賴它」。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **706 passed**（接手時 698，新增 9 條，
  另外 `test_ui_contract` 那一條先紅後綠）
- **反向驗證四次，全部抓到。**
  未知路徑改成回空名單 → 1 紅；`tasks` 改成 `[]` → 1 紅；
  `imports_of` 還原成回兩個值 → 1 紅；在 Python 端把 d1 灌水
  （模擬有人重寫演算法）→ 3 紅（含防漂移那條）。四次還原後全綠
- **真實資料實跑：** `ledger.py` 直接 10、間接 5、模組 tests 10 / tools 3 /
  apps 2；`owner.py` 直接 8 間接 13。兩組都跟 ROADMAP 先前記的數字一致
- **畫面在瀏覽器裡真的點開看過。** `tools/ui-harness.py --port 8797`，
  打開面板 → 點「為什麼」→ 點 `ledger.py` 那一行：明細展開，
  15 個 chip（d1 十個、d2 五個），那一行高亮，三行誠實條款都在。
  又點 `owner.py` 確認換目標會重算（21 個 chip）。
  再點一次會收起來，`console` 沒有任何錯誤。截圖確認過
- **輪詢重畫之後明細不會消失。** `renderBlast` 每 2 秒換掉 `innerHTML`，
  手動呼叫一次 `renderBlast(lastSnap)` 之後，明細仍在、那一行仍高亮
  （`blastOpen` / `blastHtml` 存著，重畫後標回去）
- `node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功，
  `bash desktop/deploy.sh` 守門測試通過、部署完成、二進位 15:34、
  **沒有開視窗**

## 一個刻意避開的坑

改 `app.js` 用的是精準字串替換，不是整段替換。
改完立刻 `grep -n "^function renderBlast\|^function renderHealthCurve"`
確認兩個定義都還在、`renderHealthCurve` 只有一份
（這個專案因為整段替換誤刪過東西兩次）。

事件監聽綁在容器上不是每一行綁一個，而且用 `box.dataset.wired` 旗標
保證只綁一次 —— `renderBlast` 每 2 秒重畫 `innerHTML`，
逐行綁會隨重畫次數累積成一堆孤兒 listener。

## 沒解決的，留給下一輪

**一，`live_conflicts` 仍然永遠沒有資料。** 來源是 M3 的 WriteScope，
`src/admission.js` 有 `createWriteScope()`，那條線沒有接到畫面這條線。
**這是第 6.3 節優先序最高的那個維度，現在是空的。** 畫面誠實地說
「沒有資料來源」，但誠實不等於這個指標有用了。

**二，明細只看得到排行榜上那 8 個。** 完整的 104 個檔沒有入口，
因為畫面上沒有「搜尋一個檔」那個東西。後端 `blast_detail` 對任何
在圖裡的檔都算得出來（CLI 直接下就有），缺的只是前端的入口。

**三，AX 視窗數 0 那個問題，這一輪一樣沒有碰。**
前兩輪已經動手兩次停手了，留的方向是查 macOS activation policy。
這一輪選擇做新功能而不是第三次去撞它，照的是「兩次沒好第三次停手」。

---

# 2026-09-16 15:4x 到 15:5x　自動接續第 N 輪

## 挑了什麼，為什麼

P0 兩項都不是我能推的：第 1 項的出口條件是 `dry_run=False` 那一按，
**留給 owner**（會在她側邊欄長出一條 session）；第 2 項 ROADMAP
自己寫著「不該急著做」，要等 F04/F05 的訊號接上來。

上一輪留了三件。第一件（`live_conflicts` 接 M3 WriteScope）等於
硬接半套資料，ROADMAP 的「不做的事」第二條明列。第三件（AX 視窗數 0）
前兩輪已經動手兩次停手，不做第三次。

所以挑第二件：**blast 明細的完整檔案入口**。缺的一直是入口不是能力。

**動手之前先確認不重做。** `grep -rn "blastSearch\|blast_list\|blastQuery\|blastAll"`
命中 0，`blast.py` 的函式清單只有 collect / vectors / detail / summary，
沒有第二支在做同一件事。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/blast.py` | `vectors()` 回傳加 `all_files` 與 `all_files_why` |
| `desktop/ui/app.js` | 搜尋框 + `renderBlastHits()`；重畫還原 value/焦點/游標；input 事件委派 |
| `desktop/ui/app.css` | `.blFind` `.blQ` `.blHits` 那一組 |
| `tools/ui-harness.py` | 排行榜以外多預算兩個檔，不然 harness 上驗不到這個功能 |
| `tests/test_blast.py` | 新增 3 條 |
| `tests/test_ui_contract.py` | 新增 `TypingSurvivesRepaint` 4 條 |
| `.forseti/ROADMAP.md` | 第 5 項補上這一段 |

**沒有新增 Tauri command。** 走既有的 `blast_detail`，
所以 `main.rs` 的白名單一個字都沒動，多一個 command 就多一條攻擊面。

## 真正會壞的不是搜尋，是輸入框

`renderBlast` 每 1 到 3 秒整塊換 `innerHTML`，所以 `.blQ` 每次輪詢
都是一個全新節點。預設行為是**使用者打到一半字自己消失、
游標跳回開頭**，而且不會有任何錯誤 —— 這正是這個專案在防的那一類。

三個各自獨立會壞的點，各有一條測試：value 沒放回去、
游標與焦點沒放回去、input 綁在每次重畫的新節點上累積孤兒 listener。

順手修一個順序 bug：先前重畫後標記 `blastOpen` 用的是 `querySelector`
只標第一個，而同一個檔可能同時出現在排行榜跟搜尋結果裡，
改成 `querySelectorAll`。而且搜尋結果要先畫回來，那一行才可能存在。

## 誠實條款沿用同一條理由

搜尋不到**不只印「沒有符合的」**，要印出這張圖掃的是哪些目錄。
`src/cost.js` 搜尋不到那不是它不存在，是它不在這張圖裡
（只掃 apps/forseti-cli、tools、tests 底下的 .py）。
跟 `detail()` 對未知路徑回 `known: False` 是同一條：
兩種情況在畫面上長得一樣，而其中一種讀起來像「改它很安全」。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **713 passed**（接手時 706，新增 7 條）
- **反向驗證六次，全部抓到。** all_files 改成只回排行榜 → 1 紅；
  拿掉範圍說明 → 1 紅；清單改回絕對路徑（格式跟 detail 不一致）→ 1 紅；
  拿掉 `inp.value = blastQuery` → 1 紅；input 改綁在 `.blQ` 上 → 1 紅；
  定義 `renderBlastHits` 但不呼叫 → 1 紅。六次還原後全綠
- **瀏覽器 harness 實測**（`tools/ui-harness.py --port 8799`）：
  搜尋框出現、placeholder 報 104 個節點；用 `computer type` 真的打
  `vitals` 命中 2 個；點開 `advicetrack.py`（**排行榜上沒有的檔**）
  明細展開 6 個 chip；搜尋 `cost.js` 印的是「這張圖裡沒有」加範圍說明
- **打字跨重畫不消失：** 打完等 6.5 秒（跨多次輪詢重畫），
  value 仍是 `vitals`、焦點仍在、游標仍在第 6 位。
  明細與那一行的高亮重畫後也都還在
- **CLI 對照畫面數字：** `blast_detail apps/forseti-cli/advicetrack.py`
  → 直接 1（desktop_api.py）、間接 5、模組 tests 3 / apps 2 / tools 1，
  跟畫面上逐項一致
- `console` 無錯誤，`node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功、`bash desktop/deploy.sh`
  守門測試通過、二進位 15:54、**沒有開視窗**

## 一個刻意避開的坑

改 `app.js` 用精準字串替換，改完 `grep -c "^function renderBlast("` 等
四個定義各確認一次都還在且唯一（這個專案因為整段替換誤刪過東西兩次）。

## 沒解決的，留給下一輪

**一，`live_conflicts` 仍然永遠沒有資料。** 來源是 M3 的 WriteScope，
`src/admission.js` 有 `createWriteScope()`，那條線沒接到畫面這條線。
第 6.3 節優先序最高的那個維度，現在是空的。

**二，搜尋只找得到這張圖裡的 .py。** `src/` 的 .js、`desktop/` 都不在圖裡。
畫面上誠實地講了，但那不等於這個範圍夠用。要擴要先決定
JS 那半邊的 import 邊怎麼抽，那是另一整件事。

**三，AX 視窗數 0，這一輪一樣沒碰。** 前兩輪動手兩次停手，
留的方向是 macOS activation policy。照「兩次沒好第三次停手」。

---

# 2026-09-16 16:0x 到 16:2x　自動接續（JS 半邊進圖）

## 挑了什麼，為什麼

P0 兩項一樣不是我能推的（第 1 項的 `dry_run=False` 留給 owner，
第 2 項 ROADMAP 自己寫著「不該急著做」）。

上一輪留了三件。第一件（`live_conflicts` 接 M3 WriteScope）是
ROADMAP「不做的事」第二條明列的硬接半套資料。第三件（AX 視窗數 0）
前兩輪動手兩次停手，不做第三次。

所以挑第二件：**blast 圖只看得到 .py，JS 那半邊不在圖裡。**
上一輪把它記成「要擴要先決定 JS 那半邊的 import 邊怎麼抽，
那是另一整件事」。

**動手前先確認不重做，而這一次查出來的東西改變了整個做法。**
`grep -rn "js_import\|parse_js\|import_js" blast.py` 命中 0，
但 `ls src/` 看到 **`imports.js`**。讀完它的檔頭：

> 它不讀檔案系統。宿主把「檔名 → 原始碼文字」餵進來,
> 這裡吐出 cost.js 的 buildGraph() 吃得下的 import 紀錄。

**缺的不是解析器，是宿主。** M11 從第一天就寫好了，
跟 `cost.js` 當年的處境一模一樣（演算法寫好、測試全過、輸入源是斷的）。
所以這一輪沒有在 Python 寫任何一行 JS 解析。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/blast.py` | `JS_SCAN_DIRS` / `js_files()` / `_JS_PRELUDE`；兩個 runner 合併兩半邊的邊；磁碟快取 |
| `desktop/ui/app.js` | 快取標示；兩半邊的檔數與邊數；解析方法差異 |
| `desktop/ui/app.css` | `.blStale` |
| `tests/test_blast.py` | 新增 11 條，改 1 條既有的期望值 |
| `tests/test_ui_contract.py` | 新增 5 條（`CacheIsVisible`、`BlastGraphHasBothHalves`） |
| `.forseti/ROADMAP.md` | 第 5 項補上這一段，另立 5a |

**沒有新增 Tauri command。** 走既有的 `strands` 與 `blast_detail`，
`main.rs` 一個字都沒動。

## 真實數字

圖從 104 個節點 130 條邊，變成 **219 個節點 294 條邊**
（104 個 .py 加 115 個 JS，130 條 Python 邊加 164 條 JS 邊）。
解析率 0.993，剩下 2 筆未解析是 `test/imports.test.mjs` 自己的
測試 fixture（`./a.js`、`./lazy.js`），那兩個檔本來就不存在。

排行榜前四名現在全是 JS：`claims.js` 7、`cost.js` 6、
`collaboration.js` 6、`incident.js` 6。

**`src/cost.js` 現在點得開了。** 它是算這張圖的那份演算法本身，
而在今天之前它不在自己算的那張圖裡。

## 一個會假摔的數字，實測抓到的

把 `imports.js` 回的 EXTERNAL 紀錄一起餵進 `buildGraph()`，
`cost.js` 的 `resolutionRate()` 從 **0.971 掉到 0.541**，
因為它把 to=null 一律算成未解析。那個 0.54 讀起來是
「這張圖漏抓四成六」，而那四成六全是 `node:fs` 這類內建模組，
本來就不該是圖上的節點。

**跟 `imports_of()` 檔頭記載的 Python 第一版 0.184 事件是同一種病。**
兩邊各有一條回歸測試。內建模組的判定用 node 自己的 `builtinModules`，
不是我維護的一張表 —— 跟 Python 那半邊用 `sys.stdlib_module_names`
是同一條原則。

## 順帶量出一個比新功能更嚴重的既有問題

**畫面每 2 秒呼叫一次 `strands`，而 `strands` 要 4.53 秒。**
這在接 JS 之前就成立（當時約 2.9 秒），接 JS 把它從一倍變兩倍。
是量出來的不是猜的。

記憶體快取在這裡沒有用：每一次都是 Rust 起的**全新 python3 程序**，
module-level 的 dict 每次都是空的。所以做磁碟快取，
失效靠指紋（檔案集合加 mtime_ns 加 size）不靠時間 ——
用時間當有效期的症狀是「改完程式碼畫面不動，而且沒有任何錯誤訊息」。

結果 `strands` **4.53 秒 → 1.29 秒**，比接手時的 2.9 秒還快。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **729 passed**（接手時 713，新增 16 條）
- **反向驗證十次。前九次有兩次沒抓到，兩次都查出原因並修掉：**
  - 反 1（JS 邊不合併進圖）→ **第一次沒抓到**。原因是我自己寫的測試
    斷言在 `js_edges` 上，而那個數字報的是「解析出幾條邊」不是
    「那些邊進了圖」，而且只覆蓋到 `_DETAIL_RUNNER`。
    改成斷言在兩個 runner 各自算出來的 d1_count 上，再跑就紅了
  - 反 5（命中快取謊報 cached=False）→ 第一次是我的替換字串沒命中
    （中間隔著註解行），不是測試漏抓。用精準字串重跑就紅了
  - 其餘八次一次就抓到：EXTERNAL 餵進圖、detail 的 known 不含 JS、
    快取不比對指紋、指紋算不出來就編一個、node_modules 不濾、
    拿掉 cached 標示、快取標示做成紅的、不畫兩半邊組成
- **我自己寫的一條壞測試，當場重寫。** `test_快取寫不進去也不能讓功能壞掉`
  第一版 monkeypatch 掉 `_cache_put` 讓它拋錯，再斷言 `vectors()`
  跟著拋錯 —— 那測的是 monkeypatch 有效，不是真實行為，
  而且斷言的還是**錯的**行為。重寫成拿一個檔案當目錄用，走真的 OSError
- **瀏覽器實測**（`tools/ui-harness.py --port 8801`）：
  點開八維度，波及範圍那一格報 219 個檔案 294 條依賴邊、
  標示「快取」；搜尋 `cost.js` 命中 `src/cost.js`（**上一輪的出口條件
  正是這個搜不到**）；點開明細，直接 6 個、間接 7 個、
  模組 test 8 / src 2 / tools 2 / example 1
- **CLI 對照畫面：** `blast_detail src/cost.js` → d1=6、d2=7、
  模組分佈逐項一致
- `console` 無錯誤，`node --check desktop/ui/app.js` 過
- `npx tauri build --debug --bundles app` 成功、`bash desktop/deploy.sh`
  守門測試通過、二進位 16:21、**沒有開視窗**

## 一個刻意避開的坑

改 `app.js` 用精準字串替換，改完 `grep -c "^function renderBlast("`
等三個定義各確認一次都還在且唯一（這個專案因為整段替換誤刪過東西兩次）。

CSS 那條第一版寫了 `var(--bg-3)`，那個變數**不存在**。
用 `grep -n "bg-3" app.css` 發現只有我剛加的那一行用到它，
換成真的有定義的 `--surface-3` 與 `--ink-3`。
順手掃出四個既有的未定義變數（`r-lg` `r-md` `r-pill` `r-sm`），
**沒有動它們**，不在這一輪範圍內，記在這裡給下一輪。

## 沒解決的，留給下一輪

**一，`live_conflicts` 仍然沒有資料來源。** M3 的 WriteScope 沒接到
這條線。`src/admission.js` 現在是圖上的節點了，但那是「它被誰 import」，
不是「它執行期開了哪些 WriteScope」，兩件事。
第 6.3 節優先序最高的那個維度，現在還是空的。

**二，JS 那半邊用正則解析，漏的會比 .py 那半邊多。**
畫面上誠實地講了，但那不等於這半邊的可靠度夠。
`imports.js` 的 `dynamic_opaque` 現在有帶出來（在 `js_stats` 裡）
但畫面沒有用它。

**三，CSS 有四個未定義的變數**（`r-lg` `r-md` `r-pill` `r-sm`），
這一輪掃出來但沒動。要改之前得先確認它們是不是刻意留的。

**四，AX 視窗數 0，這一輪一樣沒碰。** 前兩輪動手兩次停手，
照「兩次沒好第三次停手」。

## 收尾時發現的一件事，跟這一輪的功能無關但更嚴重

`.gitignore` 的白名單是列舉式的，而 **`.forseti/ROADMAP.md` 與
`.forseti/AUTO_CONTINUE_LOG.md` 一直被 `.forseti/*` 擋在版控外**。

這是 `.gitignore` 自己的註解記載的 2026-09-11 事故**第三次重演**
（那次是 `HANDOVER_FAILURE` 被擋掉，而我宣稱「已經 commit」，
commit 確實成功了，只是不含那個檔案）。漏了不會有錯誤，
只會安靜地不存在 —— 包含這一輪寫的兩份更新。

用 `git check-ignore` 逐項確認過才改的，不是看檔案在不在就下結論。
兩份都加進白名單了，改完再驗一次：兩份都變成進版控，
而 `.forseti/cache/blast.json`（這一輪新增的快取）仍然被忽略，正確。

**`NEXT.md` 刻意沒加，留給 owner 決定。** 它是 `handoff.py`
每 4 分鐘自動重寫的執行期產物（性質同 `state.json`），
進版控會產生大量沒有意義的 commit；但它同時是「下一個接手的人
唯一看得到的東西」。這是一個取捨不是一個事實，我不自己定。
要它進版控的話加一行 `!.forseti/NEXT.md` 就好。

**沒有 commit。** 這一輪只改 gitignore 的規則，沒有動版控狀態。

---

# 2026-09-16 16:3x 到 16:4x　自動接續（這張圖的盲點變成數字）

## 閘門

`supervisor.py --status` 回「會不會喚醒 true」，沒有閘擋住，
原因是 NEXT.md 裡還有沒解決的。今天喚醒 0 次，上限 40。

## 挑了什麼，為什麼

P0 兩項一樣不是我能推的（第 1 項的 `dry_run=False` 留給 owner，
第 2 項 ROADMAP 自己寫著不該急著做）。

上一輪留了四件。第一件（`live_conflicts` 接 M3 WriteScope）是
ROADMAP「不做的事」第二條明列的硬接半套資料。第三件（CSS 四個
未定義變數）要先確認是不是刻意留的，那是 owner 的事。
第四件（AX 視窗數 0）前兩輪動手兩次停手，不做第三次。

所以挑第二件：JS 那半邊的 `dynamic_opaque`「有帶出來但畫面沒有用它」。

動手前先確認不重做，`grep -rn "dynamic_opaque"` 命中四處：
`src/imports.js` 在算、`src/runtime.js` 在傳、`test/imports.test.mjs`
在測，而 `blast.py` 與 `app.js` 一處都沒有。確認缺的是最後一段路。

「然後查出一件比原本那件更重要的事。」
`grep -rn "importlib|__import__"` 命中 11 個檔。`ledger.py` 用
`importlib.import_module("worker")` 這種寫法依賴四個模組，而
`ast.Import` 看不到它們，所以那四條邊整張圖上一條都沒有。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/blast.py` | `imports_of` 加第四類（延後 import），元數三變四；`collect()` 多回 `dynamic_opaque`；`vectors()` 多五個欄位；快取版本 3 到 4 |
| `desktop/ui/app.js` | 兩半邊的盲點數字；補回來的延後邊數 |
| `tests/test_blast.py` | 新增 7 條，改既有 2 條的期望值 |
| `tests/test_ui_contract.py` | 新增 3 條（`BlindSpotsAreVisible`） |
| `.forseti/ROADMAP.md` | 新增第 5b 項 |

沒有新增 Tauri command，沒有動 `main.rs`。

## 真實數字，每一個都實跑過

- 延後 import 補回 6 條真的邊：`ledger.py` 對 worker / starvation /
  continuity / watchdog，`claims.py` 與 `owner.py` 對 event_ledger
- Python 半邊的邊從 130 變 136，整張圖 294 變 300
- `worker.py` 的直接依賴從 3 變 4，多出來的是 `ledger.py`
- 已知盲點：.py 2 筆（都在 `forseti.py`），JS 14 筆
- 解析率 0.993 沒有變（延後 import 解得出來的才進圖）

## 兩件刻意沒做的

「一，非字面的參數不猜。」`importlib.import_module(name)` 只記
檔名加行號，不生邊。反向驗證第 3 次就是把這條拿掉改成猜一個目標，
兩條測試立刻紅。

「二，JS 半邊沒算成時回 None 不是 0。」0 讀起來是「JS 那半邊沒有
盲點」，跟 `live_conflicts` 的 0 是同一種病。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → 739 passed（接手時 729，新增 10 條）
- 反向驗證六次，六次全部抓到，每次都還原：
  字面延後 import 不進圖（4 條紅）、看到動態 import 當作沒看到（2 紅）、
  非字面的也猜一個目標（2 紅）、external 不標 kind（1 紅）、
  JS 沒資料時把 None 當 0（1 紅）、畫面不畫盲點數字（2 紅）
- 瀏覽器實測（`tools/ui-harness.py --port 8802`）：波及範圍那一格
  報 219 個檔案 300 條依賴邊，新的兩行都在，console 無錯誤，
  搜尋 ledger 命中 6 個
- CLI 對照：`blast.detail("apps/forseti-cli/worker.py")` 的 d1 名單
  含 `ledger.py`
- `node --check desktop/ui/app.js` 過，`renderBlast` 與
  `renderBlastHits` 兩個定義各確認一次都還在且唯一
- `npx tauri build --debug --bundles app` 成功、`bash desktop/deploy.sh`
  守門測試通過、二進位 16:40、沒有開視窗

## 一個當場修掉的小事

第一版的說明文字裡寫了 markdown 的粗體星號，而那段字是直接
塞進 HTML 的，所以畫面上會出現兩對星號。瀏覽器實測時看到才發現，
改成用「」框。這種東西只有真的打開畫面看才會發現。

## 沒解決的，留給下一輪

一，`live_conflicts` 仍然沒有資料來源。M3 的 WriteScope 沒接到
這條線。第 6.3 節優先序最高的那個維度，現在還是空的。

二，JS 那半邊的 14 筆盲點現在只有一個總數，沒有像 Python 那半邊
一樣帶出「在哪個檔第幾行」。`imports.js` 的 `parseImports` 現在只回
`opaque` 的計數不回位置，要帶位置得改那支的回傳，那是另一件事。

三，CSS 四個未定義的變數（`r-lg` `r-md` `r-pill` `r-sm`），
上一輪掃出來，這一輪一樣沒動，要改之前得先確認它們是不是刻意留的。

四，AX 視窗數 0，前兩輪動手兩次停手，這一輪一樣沒碰。

沒有 commit。

---

# 2026-09-16 16:5x 到 17:1x　自動接續（JS 那半邊的盲點也有位置了）

## 閘門

`supervisor.py --status` 回「會不會喚醒 true」，沒有閘擋住，
原因是 NEXT.md 裡還有沒解決的。今天喚醒 0 次，上限 40。
`/Volumes/NewDrive` 有掛載。

## 挑了什麼，為什麼

P0 兩項一樣不是我能推的（第 1 項的 `dry_run=False` 留給 owner，
第 2 項 ROADMAP 自己寫著不該急著做）。

上一輪留了四件。第一件（`live_conflicts` 接 M3 WriteScope）是
ROADMAP「不做的事」第二條明列的硬接半套資料。第三件（CSS 四個
未定義變數）要先確認是不是刻意留的，那是 owner 的事。
第四件（AX 視窗數 0）前幾輪動手兩次停手，不做第三次。

所以挑第二件：JS 那半邊的 14 筆盲點只有總數，沒有位置。

動手前先確認不重做：`grep -rn "opaque"` 命中 `src/imports.js` 在算、
`blast.py` 只接了 `dynamic_opaque` 這個數字、`app.js` 只印總數，
`js_dynamic_where` 整個 repo 零命中。確認缺的是最後一段路。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `src/imports.js` | `stripComments` 保留換行；新增 `lineAt()`；`parseImports` 回 `opaque_at`；`buildImportRecords` 的 stats 多 `dynamic_where` |
| `apps/forseti-cli/blast.py` | `vectors()` 多 `js_dynamic_where`；快取版本 4 到 5 |
| `desktop/ui/app.js` | 新增 `blindSpotWhere()`，兩半邊的位置都畫出來 |
| `desktop/ui/app.css` | `.blindSpots` 一組樣式 |
| `test/imports.test.mjs` | 淨增 9 條 |
| `tests/test_blast.py` | 新增 4 條 |
| `tests/test_ui_contract.py` | 新增 2 條 |

沒有新增 Tauri command，沒有動 `main.rs`，沒有動任何 hook。

## 一個先前就存在、做這件事才浮出來的 bug

`stripComments` 把整段多行註解換成一個空格，所以註解之後每一行的
行號都往前跳。先前沒人發現，因為沒有任何地方用得到行號。

一個錯的行號比沒有行號糟。沒有行號的人會自己去找；
拿到錯行號的人會走到那一行，看到不相干的程式碼，然後認定工具在亂報。

## 真實數字，每一個都實跑過

- JS 盲點 21 筆，帶得出位置的前 20 筆畫在畫面上
- 21 比上一輪的 14 多 7 筆，**多出來的是這一輪新增的測試檔自己的
  opaque 範例字串，不是漏算變準的**。這件事要講明，不然那個
  數字自己變大會被讀成「先前少算了七個」
- 位置逐行比對過三筆：`hooks/forseti-hook.mjs:190` 是
  `await import(join(HERE, '..', 'src', 'intervention.js'))`，
  `hooks/forseti-stop-hook.mjs:109`、`tools/dashboard.mjs:44` 同樣對得上
- 圖仍是 219 個節點 300 條邊，解析率 0.993。位置不改變圖，
  這個數字沒有變是對的
- 畫面實際列出 22 行（.py 2 加 JS 20），總數 23，
  所以畫面寫「另外 1 筆沒有列出來」

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → 745 passed（接手時 739，淨增 6）
- `node --test test/imports.test.mjs` → 42 通過（接手時 33，淨增 9）
- `node test/run-all.mjs` → 2 個模組有失敗，**跟這一輪無關**。
  用 `git stash` 把 `src/imports.js` 與 `test/imports.test.mjs`
  暫存掉再跑一次，同樣是那 2 個模組同一條 FAIL，確認是接手時就在的
- 反向驗證六次：五次抓到（吃掉換行、假行號、計數與位置各算一次、
  None 退化成空清單、畫面把 None 當空清單），一次沒抓到
- 瀏覽器實測（`tools/ui-harness.py`）：展開後清單真的在，
  console 無錯誤；375 寬與 1024 寬各看過一次
- `node --check src/imports.js`、`node --check desktop/ui/app.js` 都過
- `npx tauri build --debug --bundles app` 成功，
  `bash desktop/deploy.sh` 守門測試通過，二進位 17:10，**沒有開視窗**

## 一條測試被我自己刪掉

「單行註解也不吃掉換行」兩個版本都會過，因為單行註解本來就不跨行，
吃掉它不可能影響任何行號。反向驗證第 2 次沒抓到就是這一條。

**一條永遠綠的測試比沒有測試糟**，它讓人以為那條路有人守。
測試刪了，對應那個 `' '.repeat` 的改動也一起還原 ——
它沒有守住任何東西，留著只是多一個看起來有道理的無效改動。

## 兩個只有真的打開畫面才看得到的問題

一，第一版用 `text-indent` 做懸掛縮排，把 `.py` / `JS` 那個半邊標示
拉到容器外被 `overflow` 裁掉。`liCount` 22、`textContent` 也對，
光看這兩個數字會以為沒問題。截圖才看見。

二，捲動區 132px 不是行高整數倍，最後一行裁成上半截。

## 沒解決的，留給下一輪或 owner

一，`live_conflicts` 仍然沒有資料來源（M3 的 WriteScope 沒接到
這條線）。第 6.3 節優先序最高的那個維度，還是空的。

二，**`node test/run-all.mjs` 有 2 個模組失敗，接手時就存在。**
兩個都指向同一件事：`hooks/forseti-stop-hook.mjs:218` 有一個
`AT-HOOK-R3` 認定「沒問過閘門」的 `exit(2)`。

**我沒有動它，因為這件事不是我能決定的。** 讀過那段之後：
那個 `exit(2)` 其實有閘門，只是走的不是 `canIntervene`，而是
owner 2026-09-16 明確要求開啟的 `config.json` 的
`enforce_declarations`，而且有次數上限與痕跡。所以是兩種可能：
要嘛測試的守備條件該更新成「問過 canIntervene 或 owner 明確 opt-in
加上限」，要嘛那個 exit(2) 也該去問 canIntervene。
**動這裡就是動「會不會擋住她工作」那條線，那正是事故本體。**

三，**59 個檔案不在版控裡**，其中 23 個在 `tests/`，
也包含今天做的一整批模組（`blast.py`、`authority.py`、
`checkpoint.py`、`commit.py`、`divergence.py` 等）。
用 `git check-ignore` 逐項確認過**不是被 `.gitignore` 擋掉**，
是從來沒有 `git add` 過。這個狀態下換機器或誤刪就全沒了，
而且不會有任何錯誤訊息。沒有 commit，那是 owner 的決定。

四，CSS 四個未定義的變數（`r-lg` `r-md` `r-pill` `r-sm`），
連續三輪掃出來沒動，要改之前得先確認是不是刻意留的。

五，AX 視窗數 0，前幾輪動手兩次停手，這一輪一樣沒碰。

## 關於 NEXT.md

`.forseti/NEXT.md` 是 `handoff.py` 從狀態算出來、每 4 分鐘自動重寫的
產物（這一輪期間 17:08 就被重寫過一次）。**手寫進去的字會在下一次
自動重寫時消失**，那等於製造一個會自己不見的交接，比不寫更糟。
所以這一輪的結論寫在這裡與 `ROADMAP.md` 第 5c 項，那兩份不會被覆寫。

沒有 commit。

---

# 2026-09-16 17:2x 到 17:3x　自動接續（交接檔照規格缺什麼，變成可查的欄位）

## 挑了什麼，為什麼

上一輪留下的五件我一件都不能推：`live_conflicts` 是 ROADMAP「不做的事」
第二條明列的硬接半套資料；`run-all.mjs` 那兩個失敗指向
`hooks/forseti-stop-hook.mjs:218` 的 `exit(2)`，動它就是動「會不會擋住她
工作」那條線；沒有 commit 是 owner 的決定；CSS 四個變數與 AX 視窗數
前幾輪已經停手兩次。

P0 兩項也一樣：第 1 項的 `dry_run=False` 留給 owner 按，
第 2 項 ROADMAP 自己寫著不該急著做。

所以往 ROADMAP 沒排到、而且規格寫死不需要發明的地方找。
找到 v5.0 §39.1 Minimum Handoff Contract：一張 11 列的表，
逐字定義一份交接該帶哪些欄位。

**為什麼是它。** ROADMAP 對 `handoff.py` 的描述是「交接檔 C4 的**一半**」，
而沒有人說得出另一半是什麼。更直接的理由是今天早上那個事故的形狀：
`PHASE_STATUS.md` 說五階沒開始、實際三階已完成，於是有人重做一遍。
**那不是文件寫錯，是沒有人在檢查交接帶了什麼。**
一份缺一半欄位的交接，跟一份完整的交接，在畫面上長得一模一樣。

## 動手前先確認不重做

`grep -rn "39.1\|MINIMUM_HANDOFF\|handoff_contract\|minimum handoff"`
在 `apps/` `src/` `hooks/` `tools/` `desktop/` 零命中，只有規格原文與
一份讀後摘要有。`ls apps/forseti-cli/ | grep -i contract` 零命中。
確認缺的是整個物件，不是最後一段路。

## 做了什麼

| 檔案 | 改了什麼 |
|---|---|
| `apps/forseti-cli/contract.py` | 新增。§39.1 那張表 11 群 31 欄逐字，加五種狀態的判定、兩個覆蓋率、缺口排序、`collect()` 從真實狀態組 ctx |
| `apps/forseti-cli/handoff.py` | `render()` 多一節「這份交接照規格少了什麼」，只排版不判斷 |
| `apps/forseti-cli/desktop_api.py` | `_write_handoff()` 算出契約摘要傳進去，算不出來就整節不寫 |
| `tests/test_contract.py` | 新增 30 條 |
| `tests/test_handoff.py` | 新增 3 條 |

沒有動 `app.js`、`app.css`、`main.rs`、任何 hook。
**所以這一輪不需要 tauri build，也不需要 deploy** ——
`main.rs:70` 是直接跑 repo 裡的 `desktop_api.py`，Python 的改動即時生效。
deploy.sh 內含 `pkill -9 -f "Forseti.app/Contents/MacOS"`，沒有必要就不跑它。

## 五種狀態，不是兩種。這是整支的重點

「有」跟「沒有」兩格會說謊。一個欄位可能是：

- PRESENT　有值，帶得出出處
- EMPTY　　有資料來源，此刻是空的（可能是對的，真的還沒有 checkpoint）
- NOT_CARRIED　算得出來，這份交接沒有帶。**這是一條線的距離**
- NO_SOURCE　整個系統沒有地方算得出它，要先有某個物件存在才談得上
- DEGRADED　有值，但那個值不滿足規格要求它的性質

DEGRADED 只用在**機械比得出來**的情況，不用在語意判斷。
分不出來就不分，那是 §8.3 的禁止捷徑。

**沒有理由的缺席，自己就是一個缺陷。** `ctx` 給 `None` 或整個不給那一欄，
除了算成 NO_SOURCE，還另外記成 `undeclared`。一個沒人說明為什麼不見的
欄位指不出下一步，比說得出理由的缺席更糟。
`test_collect每一欄都有人宣告` 釘住：collect 出來的 31 欄 undeclared 必須是 0。

## 兩個覆蓋率，不是一個

一個數字會被當成分數，然後 NO_SOURCE 那些會被算成「我們的錯」，
接著就有人想把它們改成空清單讓數字好看。所以 `coverage` 對整張表，
`coverage_of_possible` 把 NO_SOURCE 扣掉，兩個都附分母。
分母是 0 的時候回 None 不回 0 —— 一個算不出來的比率不是 0，
回 0 讀起來是「一個都沒做到」。`test_分母是零的時候回None不回零` 釘住。

## 真實數字，每一個都實跑過

`python3 apps/forseti-cli/contract.py` 對此刻的真實狀態：
**31 個欄位裡帶得出值的 8 個（26%）。**

- 算得出來但沒帶 2：`artifact_hashes`、`stop_condition`
- 有來源此刻空的 5
- 有值但不合規格 2：`code_commit`、`model_config`
- 沒有資料來源 14，undeclared 0

每一句 NO_SOURCE 的理由都是實際查過的，不是推測的，而且理由裡附查法：

- `logical_agent_id`：§11.1 的 AgentIdentity `grep` 零命中，
  而事件帳本的 `agent_id` 寫的是 session id（`hooks/event-ledger.mjs:158`
  逐行讀過，就是 `agent_id: input.session_id || ''`）。
  **換 session 就換值，那正好是這個欄位唯一要求它別做的事。**
  資料佐證：那張表 42 筆裡，有一筆的 agent_id 跟 session_id 是同一個 uuid
- `runtime_node`：`events` 表有 `runtime_node_id` 欄位，hooks 一律寫空字串
  （`hooks/event-ledger.mjs:159`）。**實測 42 筆 0 筆有值** ——
  有欄位不等於有資料，這一格先前完全看不出來
- `metrics_by_distribution`：Metric Provenance Contract `grep` 零命中
- `invalidated_conclusions`：§40 的 PollutionRecord `grep` 零命中
- `owner`：`owner.py` 判的是「這句話是不是 owner 講的」不是「owner 是誰」，
  `grep -rn 'owner_id\|owner_name'` 零命中

兩個 DEGRADED 也是量出來的：

- `code_commit`：HEAD `0318c22`，但 `git status --porcelain` 實測 85 個檔案
  沒進版控，**所以這個 hash 指不到現在跑的程式碼**。
  HEAD 單獨拿出來會說謊，那不是「沒有 commit」，是「有一個看起來可信的
  commit」，更難查。上一輪記的是 59 個，今天長到 85
- `model_config`：jsonl 有 `effort` 但沒有 temperature / top_p /
  system prompt 版本。標成 PRESENT 會讓人以為交接帶得出「這個輸出
  是怎麼產生的」

兩個 NOT_CARRIED 是今天就補得掉的，所以排在缺口清單最前面：

- `artifact_hashes`：`claims.py:487` 的 `_disk()` 已經會算 sha256 的
  contentHash，只是沒有人對交接裡的產出清單跑它
- `stop_condition`：`ledger.py:152` 的 tasks 表有 `stop_conditions` 欄位，
  **實測 17 筆任務裡 2 筆有值**，只是 `work()` 沒把它帶到這一層

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q` → **778 passed**（接手時 745，淨增 33）
- `python3 -m pytest tests/test_js_symbols.py tests/test_ui_contract.py -q`
  → 35 passed（deploy 守門那兩組，沒動 JS 但還是跑過）
- **反向驗證八次，八次全部抓到**：
  1. `runtime_node` 的 NoSource 改成 `[]` → `test_collect不會把沒有來源寫成空清單`
  2. 分母 0 回 0.0 → `test_分母是零的時候回None不回零`
  3. undeclared 不記 → 兩條同時紅
  4. NOT_CARRIED 併進 NO_SOURCE → 兩條同時紅
  5. 缺口排序反過來 → `test_今天補得掉的排在前面`
  6. 拿掉一個欄位群 → `test_十一個欄位群一個都不能少`
  7. Degraded 的值藏起來 → `test_有值但不合規格算DEGRADED而且值要看得到`
  8. 摘要印英文狀態碼 → `test_摘要不准出現英文狀態碼`
- `.forseti/NEXT.md` **實際被真正的那條路徑重寫過**（不是我手寫）：
  `D.strands()` 內部的 `_write_handoff` 在 17:36:48 寫進去，
  新那一節在檔案裡，mtime 對得上。渲染後 2772 bytes，
  仍在 `test_不塞對話全文` 的 8000 上限之內

## 一個差點誤判的地方，記下來

第一次跑完之後 `_write_handoff` 回 `None`，而 NEXT.md 卻已經有新的一節，
看起來像有別的東西在寫這個檔。查了才知道 `desktop_api.py:2893` 的
`strands()` 自己就會呼叫 `_write_handoff`，所以是我那一行
`D._write_handoff(D.strands())` 裡的 `D.strands()` 先寫掉了，
第二次呼叫才因為 240 秒間隔回 None。**沒有第三方在寫，是我自己讀錯。**
這件事寫下來是因為當下差一點就往「有隱藏的 writer」那個方向查下去。

## 沒解決的，留給下一輪或 owner

一，**這一節目前只在 `NEXT.md`，桌面畫面上沒有。** 要上畫面得動
`app.js` 加 `snap["contract"]`，那需要 tauri build 加 deploy，
而 deploy.sh 會 `pkill` 桌面 App。沒有必要就不做 ——
接手的人讀的是 `NEXT.md`，那裡已經有了。

二，**兩個 NOT_CARRIED 是下一輪最划算的一項。** 兩條線就補得掉，
補完覆蓋率從 8/31 到 10/31，而且補的是「產出的雜湊」與「做到什麼程度停」
這兩件接手的人真的會問的事。

三，`live_conflicts` 仍然沒有資料來源，跟上一輪一樣。

四，`node test/run-all.mjs` 那 2 個模組仍然失敗，接手時就存在，沒動。

五，**85 個檔案不在版控裡**，上一輪記的是 59，今天長了 26 個
（其中 2 個是這一輪新增的 `contract.py` 與 `test_contract.py`）。
`git check-ignore` 確認過不是被 `.gitignore` 擋掉，是從來沒有 `git add` 過。
這個狀態下換機器或誤刪就全沒了，而且不會有任何錯誤訊息。
沒有 commit，那是 owner 的決定 —— 而現在 `code_commit` 那一欄
每次寫交接都會把這個數字印出來，不必再靠誰記得。

六，CSS 四個未定義變數與 AX 視窗數，這一輪一樣沒碰。

沒有 commit。

## 追記：這一輪順手修掉一個「閘門形同虛設」的既有缺陷

寫完上面那一節之後再跑一次全套，`tests/test_gate.py::test_不做語意相似度`
變紅了，而它在十分鐘前那一次是綠的。**是我的文件改動把一個既有缺陷
掀出來的，不是我寫壞了程式碼。**

根因逐項查過：

`gate.challenge()` 的題目是從真實文件現抽的，而我在 `NEXT.md` 加的那一節
帶進一行摘要「- 有值但不滿足規格要求：2」。`blockread.py` 的 `_RULEY`
命中「要求」兩個字，`_NUM` 抽到 `2`，於是**接手閘門出了一題答案是「2」
的填空**。`grade()` 比的是「原文的 key 有沒有出現在答案裡」，
所以 key 是 `2` 的時候幾乎任何一句話都算對。

那題答對答錯跟有沒有讀懂那一行完全無關，而它照樣算進通過門檻
（`gate.NEED` 是 2，總共才 3 題）。

**這跟 owner 2026-09-14 當場考出來的那件事是同一種病。** 當時禁令題的
key 抽的是「不准」兩個字，於是那題變成「你會不會把『不准』打出來」，
`blockread.py:294-299` 的註解記著這件事，並用 `len(tail) >= 4` 擋掉了。
**數字那一支從來沒有同樣的守備。**

修法：數字題的答案少於 2 個字元就不出題。
這擋的是退化情形，**不是一個校準過的門檻** —— 2 個字元以上仍然會漏
（key 是 `2` 的時候 `12` 也含它），那要改 `grade()` 的比對方式才解得掉，
不是改長度解得掉。這句話寫在程式碼的註解裡，不是只寫在這裡。

`tests/test_blockread_quiz.py` 新增 5 條，其中一條刻意證明
「單字元的 key 在 `grade()` 裡幾乎一定會過」，
把「為什麼防線要放在出題那一端」寫成可執行的證據。

反向驗證兩個方向都跑過：守備拿掉 → 2 條紅；守過頭改成 `>= 3` →
`test_兩位數以上的規定照樣出得了題` 紅。**擋掉退化情形不可以順手
把正常題目也擋掉，兩邊都要有測試。**

全套 778 → **783 passed**。

## 還沒解決的，這一條要 owner 決定

**`tests/test_gate.py` 的題目來自每 4 分鐘被重寫一次的文件。**
所以那一組測試是活文件內容的函數：不動任何程式碼，它也可能突然變紅
或突然變綠。這一輪就是這樣紅的。

更麻煩的是綠的那個方向 —— 一個因為文件剛好長成那樣而通過的
寫入權限閘門，不會有任何錯誤訊息。

**我沒有動它**，因為改 `challenge()` 抽題的來源就是改這道閘門的行為，
而那道閘門管的是「誰可以動這個 repo」。那是 owner 的線。

---

## 2026-09-16 17:5x　那兩個「算得出來沒帶」補掉了，NOT_CARRIED 歸零

**挑這一項的理由不是我判斷的，是上一輪自己寫下來的**：ROADMAP 的
5d 結尾寫著「下一輪最划算的一項：那兩個 NOT_CARRIED，兩條線就補得掉」。
接續任務存在的意義就是不必再問一次該做什麼。

### 做完了什麼

**一，`stop_condition`（§39.1 Next 群第二欄）。**

`ledger.obligations()` 的 SELECT 第四欄撈的是 `next_required_action`，
而**同一支函式下面五行的註解寫著它刻意不讀那一欄**（next 動態算，
因為靜態欄位要記得更新才會對，而「記得更新」正是這個帳本要消滅的依賴）。
所以那個位置一直在撈一個撈回來就被丟掉的值，而真正要用的
`stop_conditions` 從來沒被撈過。改撈它，一行。

`work()` 帶到 task row，`contract.collect()` 組成
「任務 id　條件一；條件二」。真實數字：2 件未完成任務都有停止條件
（`T-7da5ef2183` 是「owner 說停 / 規格之間出現無法自行解決的矛盾」，
`T-b95303aaa2` 是「owner 說停 / 受測 session 連續三次無回應」），
17 件任務裡有值的就是這 2 件，跟上一輪查到的數字一致。

**沒有條件的任務不補預設值。** 一個編出來的停止條件比沒有危險，
因為它看起來像有人想過。`test_沒有停止條件的任務不補一個預設值` 釘住。

**二，`artifact_hashes`（§39.1 Artifacts 群第二欄）。**

`contract.artifact_hashes()` 借 `claims._disk()` 算，**沒有自己再寫
一次 sha256** ——兩份實作遲早分歧，而分歧那天不會有錯誤訊息，
只會有兩個都長得像真雜湊的值。跟 `blast.py` 借 `cost.js` 同一條原則。
`test_借的是claims那一支` 用 `inspect.getmodule` 釘住借的是哪一支，
它改名或改掉回傳欄位的時候這裡會紅，而不是每一筆靜默回不出雜湊。

實測四種情形都對：`contract.py` 算出 `6da3ad01e36559fc`，
跟系統 `shasum -a 256 | cut -c1-16` 逐字一致；`.forseti/NEXT.md` 有值；
`apps/forseti-cli` 這個目錄回 `dir`（目錄沒有內容雜湊這個概念）；
不存在的路徑回 `missing`。

**三種算不出來的原因不併成一種。** 檔案不在了（missing）、量不到
（unmeasured，權限或檔案系統）、它是目錄（dir）。併成一個 None 之後，
「這份交接指向一個不存在的東西」跟「這個檔讀不到」長得一模一樣，
而前者是一個缺陷，後者不是。

**這一欄不准看起來比它實際上強。** 它是**此刻磁碟上**的內容，
不是寫入當下的內容，中間被誰改過這裡看不出來。所以欄位叫
`hashed_at`，`test_雜湊不宣稱自己是產出當下的` 連欄位名都釘
（不准出現 produced / written 這種字）。

### 真實數字，跟上一輪的預期不一樣，照實記

ROADMAP 預期「補完覆蓋率 8/31 到 10/31」。**實際是 9/31。**

`stop_condition` 變成 PRESENT（8→9），`artifact_hashes` 變成 **EMPTY
不是 PRESENT**，因為它的輸入 `artifact_paths` 此刻是空的。
NOT_CARRIED 2→0，EMPTY 5→6。已由真正的那條路徑
（`strands()` 內的 `_write_handoff`）寫進 `.forseti/NEXT.md` 驗證過。

### 順帶查出來的一件事：這一輪自己就是那個盲點的例子

`artifact_paths` 的來源是 transcript 的工具點，**只認得
Write / Edit / NotebookEdit**。這一輪全程用 Bash（heredoc 加 python
腳本）改檔，所以它改了 5 個檔案，而這一欄照樣是空的。

空在畫面上讀起來像「這一輪沒有產出」，那是一句錯的話。

**沒有去猜 Bash 指令裡哪個字串是產出路徑。** 那是 §8.3 的填空，
而猜錯的代價是交接檔指向一個沒有人寫過的檔案。要補得正確，
缺的是「工具點帶出實際被寫入的路徑」這個資料，不是這裡多一段
正規表示式。`test_用Bash改的檔案這一欄看不到_這是已知盲點` 釘住
現行行為並寫明理由：哪天有人要把 Bash 算進來，那條會紅，
而那個人會先讀到為什麼不猜。

### 驗證

16 條新測試（contract 13、ledger 3）。全套 **783 → 800 passed**
（上一輪 783，加 16 條，另外 `test_ui_contract` 那邊沒有變動）。

**反向驗證七次，七次全部抓到**（第一次做的第 7 個改壞方式造成語法
錯誤而不是測試失敗，那不算有效的反向驗證，重做了一次才算）：

| 改壞什麼 | 結果 |
|---|---|
| missing 併進 unmeasured | 1 紅 |
| 雜湊改取全長 | 1 紅 |
| `stop_condition` 改回 NotCarried | 3 紅 |
| 空條件也補預設值 | 1 紅 |
| ledger SELECT 改回 `next_required_action` | 1 紅 |
| `stop_conditions` 不解 JSON | 2 紅 |
| 目錄不當成 dir | 1 紅 |

**沒有動畫面、沒有動 Rust、沒有動 hook，所以不需要 build 也不需要
deploy。** 這次重新確認過理由而不是沿用上一輪的說法：
`desktop/src-tauri/src/main.rs:70` 直接跑 repo 裡的
`apps/forseti-cli/desktop_api.py`。

改了 5 個檔：`contract.py`、`ledger.py`、`desktop_api.py`、
`tests/test_contract.py`、`tests/test_ledger.py`。

### 還缺什麼

`artifact_hashes` 要真的有值，缺的是上面那個 Bash 盲點的資料來源。
**這不是這一欄的問題，是上游的。**

### 追記：查那個 88 的時候發現它的措辭是錯的，一起修掉

`code_commit` 那一欄的理由寫著「工作區有 88 個檔案**沒有進版控**」，
而 88 是 `git status --porcelain` 的**總行數**。實際拆開來看：
**26 個是已追蹤但有改動，62 個才是從來沒 `git add` 過。**

兩種都讓 hash 指不到現在跑的程式碼，但下一步完全不一樣：
前者 commit 就好，後者要先決定那些檔該不該進版控。
一個把兩者併起來的數字指不出那個差別，而這個 repo 同時有這兩種。

已改成分開報，`test_髒工作區把兩種情形分開報` 用一個臨時 git repo
（1 個改動、2 個未追蹤）釘住兩個數字各自出現。反向驗證：
把兩個數字併回一句，那條紅。

全套 800 → **801 passed**。

沒有 commit。

---

## 2026-09-16 18:2x　`artifact_paths` 的上游接上工作區

### 挑了什麼

上一輪收尾寫「下一輪最划算的：`artifact_paths` 的上游」。挑這一項。

### 做完什麼

**先確認缺的是什麼。** 缺的不是解析器，是資料來源。`.claude/settings.json`
的三個 hook 的 matcher 全部是 `Write|Edit|MultiEdit|NotebookEdit`，
Bash 連進都沒進去；而就算讓它進去，Bash 的 tool_response 也不說
哪個檔案被寫過。**所以不去猜指令字串裡哪一段是路徑**，那是 §8.3 的填空。

`git status` 說得出哪些檔案跟 HEAD 不一樣。那是量出來的。
`contract.worktree_paths()` 把它接上來。

**用 `-z` 不是為了快。** 不加 `-z` 的時候 git 把非 ASCII 路徑包成
C 風格跳脫，正本實測有一筆：

```
?? "\351\226\213\345\225\237Forseti.command"     ← 預設 porcelain
開啟Forseti.command                              ← 加了 -z
```

前者當成路徑去開永遠是 missing，於是交接檔指向一個沒有人寫過的檔案。
`test_非ASCII路徑要拿得到真的路徑不是跳脫字串` 釘住，用真的 git repo
不是假造的字串 —— 假字串測不到這件事。

**兩個來源刻意不合成一個。** 每一筆帶 `source`：工具點答「這一輪寫了
什麼」，工作區答「這裡有什麼還沒進版控」。同一個檔兩邊都有的時候
留工具點那一筆，它多知道一件事。畫面上兩個數字分開報。

**量不到不准長得像乾淨。** `worktree_paths()` 回 `{entries, problem}`：
空清單加 problem 是「沒量到」，空清單沒有 problem 是「乾淨」。
git 量不到的時候 `artifact_paths` 是 DEGRADED 不是 EMPTY ——
EMPTY 讀起來是「量過了沒有產出」，而實情是「有一半沒量到」。
跟 `live_conflicts` 的 0 與 None 同一條。

**認不出來的 git 狀態碼不替它翻譯。** 猜一個好聽的狀態會讓交接檔
宣稱一件 git 沒講過的事。

### 更大的那一半：交接檔先前根本印不出任何一個路徑

`artifact_paths` 就算 PRESENT，接手的人在 `NEXT.md` 上看到的還是零個路徑
—— 因為那一節只印**缺的**。**一個從缺口清單上消失的欄位，跟一個真的
說得出產出在哪的交接，不是同一件事。**

`contract.artifact_lines()` 產這一節的行文（判斷放在 `contract.py`，
`handoff.py` 只排版，理由跟 `summary_lines` 同一條：判斷放進排版那一支
就會變成第二個事實來源）。`report()` 順便把 `ctx` 一起帶回去，
否則畫面那一節得重跑一次 `collect()`。

**照修改時間排，新的在前。** git 給的是路徑字典序，於是前十筆永遠是
`.forseti/` 那幾個每四分鐘被自動重寫的控制檔，剛做出來的東西排在
看不到的地方。mtime 只拿來排序，不拿來宣稱來源。量不到 mtime 的排最後，
不假裝它很新。

真實輸出（`NEXT.md` 現在長這樣，前四筆正好是這一輪動的四個檔）：

```
- `apps/forseti-cli/contract.py` ── 從來沒進版控，2d26640c3981a2a4
- `tests/test_contract.py` ── 從來沒進版控，c995d92824a8e0a9
- `apps/forseti-cli/handoff.py` ── 從來沒進版控，18fd8f14432adc11
- `apps/forseti-cli/desktop_api.py` ── 已追蹤但有改動，81b7fb826b7cbf3e
```

### 順手修掉一句假的指示

那一節結尾寫著「`python3 apps/forseti-cli/contract.py` 全部印得出來」。
**寫的當下那句是假的** —— 那一支只印缺口清單，一個路徑都不印。
一句叫人去跑而跑了沒有東西的指示比不寫更糟，它讓人以為自己查過了。
已補，實測印出 108 行。

`test_CLI真的會印清單_用原始碼釘住` 釘原始碼不真的跑它：跑它會呼叫
`desktop_api.strands()`，那一支會寫 `.forseti/NEXT.md`，
一條會改動正本狀態的測試比它守住的東西危險。

### 效能：差點把上一輪剛修好的東西弄壞

接上去之後量到 `contract.report()` 從 0.2 秒變成 **1.44 秒**。
拆開看：88 個檔 `read_bytes` 要 **1.008 秒**，`stat` 只要 **0.005 秒**
—— 外接碟每開一個檔約 12 毫秒，成本在開檔不在雜湊。
1 秒會讓 `strands` 從 1.29 秒變成 2.3 秒，超過畫面 2 秒的輪詢間隔，
那正是上一輪剛修掉的問題。

所以加了**逐檔指紋快取**（`.forseti/cache/artifact_hashes.json`，
mtime_ns 加 size，跟 `blast.py` 同一條）。實測：

| | 耗時 | 命中 |
|---|---|---|
| 冷 | 1.698 秒 | 0/88 |
| 熱 | 0.048 秒 | 88/88 |
| 改一個檔之後 | 0.075 秒 | 只重算那一個 |

`strands` 實測熱的 **1.10 秒**，沒有超過輪詢間隔。

**命中快取的那一筆 `hashed_at` 是上次量的時間，不是此刻。**
改成此刻等於宣稱剛剛量過，那是這支函式證明不了的話。

雜湊值對過系統 `shasum`：`.forseti/NORTH_STAR.md` 兩邊都是
`abd0f9582bc99c77`。

### 驗證

Python **801 → 819 passed**（`tests/test_contract.py` 從 45 條到 63 條，
新增 18 條）。既有 4 處斷言跟著改，改的是「這一欄長什麼樣」，
不是把守備拿掉；`test_用Bash改的檔案這一欄看不到` 改名成
`test_工具點那一半看不到Bash改的檔_而且不准去猜`，
守的東西從「這一欄是空的」換成「不准從指令字串抽路徑」。

**反向驗證 15 次，15 次全部抓到**（其中 2 次是第一次沒抓到、
補了測試才抓到，照實記）：

| 改壞什麼 | 結果 |
|---|---|
| 拿掉 `-z` | 3 紅 |
| 改名的來源路徑不跳過 | 1 紅 |
| 量不到也回乾淨 | 1 紅 |
| 量不到不標 DEGRADED | 1 紅 |
| 工作區蓋掉工具點 | 1 紅 |
| 認不出的狀態碼硬翻 | 1 紅 |
| 快取命中把時間戳改成此刻 | 1 紅 |
| 指紋只看 size | **第一次全綠** → 補 `test_內容變了但大小一樣的時候也不准命中` → 1 紅 |
| 注入 disk 照樣寫快取 | 1 紅 |
| dict 條目不認 path 欄 | 2 紅 |
| `artifact_lines` 不印路徑 | 2 紅 |
| `report` 不帶 ctx | 1 紅 |
| 不照 mtime 排 | 2 紅 |
| 量不到 mtime 排最前 | 1 紅 |
| CLI 不印清單 | **第一次全綠** → 補 `test_CLI真的會印清單_用原始碼釘住` → 1 紅 |

那兩次「第一次全綠」是這一輪最有價值的部分：一條在壞掉的實作下
仍然通過的測試，比沒有測試糟，它讓人以為那條路有人守。

**沒有動畫面 / Rust / hook，所以不需要 build 也不需要 deploy。**
這次重新確認過理由不是沿用：`desktop/src-tauri/src/main.rs:70` 起
`Command::new(py).arg(repo/apps/forseti-cli/desktop_api.py)`，直接跑 repo 裡的檔。

改了 4 個檔：`contract.py`、`desktop_api.py`、`handoff.py`、`tests/test_contract.py`。

### 結果

§39.1 覆蓋率 **9/31（29%）→ 11/31（35%）**。EMPTY 6→4，NOT_CARRIED 維持 0。

### 還缺什麼，以及一個不是我造成的紅燈

**工具點那一半仍然看不到 Bash。** 這一輪補的是工作區那一半。
要讓工具點自己看得到，缺的是 hook 層拿得到「這個 Bash 指令實際寫了
哪些檔」——而 `.claude/settings.json` 的 matcher 現在連 Bash 都不收，
改它等於改 owner 的 harness 行為，不自己決定。

**JS 測試有 2 個模組是紅的，跟這一輪無關，但要有人看：**

- `test/hooks.e2e.test.mjs`：`AT-HOOK-R3` 失敗，
  `forseti-stop-hook.mjs:218` 有一個沒問過閘門的 `exit(2)`。
  測試自己的訊息寫著「這正是擋掉擁有者一整晚的那種寫法」。
- `test/spec-v0.1.test.mjs`：第 38 條。

兩個檔的 mtime 分別是 09-16 13:11 與 09-08 10:14，都早於這一輪，
而這一輪一個 JS 檔都沒動。`desktop/deploy.sh` 的守門只跑
`test_js_symbols.py` 與 `test_ui_contract.py`，所以它擋不住這兩條。

沒有 commit。

---

## 2026-09-16 18:5x　把掛了兩輪的紅燈查到根因，結論是它需要 owner 決定

### 挑了什麼，為什麼

P0 第 1 項要 owner 親自按（`dry_run=False` 那一下會在她側邊欄長出新 session），
P0 第 2 項 ROADMAP 自己寫著不該急著做。所以挑了那個連兩輪被記成
「一個不是誰造成的紅燈，但要有人看」而兩輪都沒人去看的東西。

### 做完什麼

**一，那不是兩個紅燈，是一個根因兩處紅。**

`test/hooks.e2e.test.mjs:414` 的 `AT-HOOK-R3` 與 `test/spec-v0.1.test.mjs:102`
的第 9 條，兩邊是逐字重複的同一段掃描（往上回看 15 行，比對
`/g\.allowed|gate\(/`），指的是同一行 `hooks/forseti-stop-hook.mjs:218`。
先前記成兩件互不相干的事，於是看起來要查兩次。

順帶更正條號：先前記「`test/spec-v0.1.test.mjs` 第 38 條」。
實跑輸出是 CONFORMS 32 / VIOLATES 1 / NOT_IMPLEMENTED 2 / NOT_CHECKABLE 3，
唯一 VIOLATES 是第 9 條，38 是總條數，第 38 條本身是 CONFORMS。

**二，先前那句「跟這一輪無關」把因果弄反了。**

先前寫「兩個檔的 mtime 是 09-16 13:11 與 09-08 10:14，都早於那一輪」。
實測 `ls -la`：

```
hooks/forseti-stop-hook.mjs   Sep 16 13:11
test/hooks.e2e.test.mjs       Sep 11 13:00
test/spec-v0.1.test.mjs       Sep  8 10:14
```

09-16 13:11 是「被測對象」的時間，不是測試檔的。測試檔是 09-11 與 09-08。
所以這兩條紅燈不是無主的舊帳，正是 09-16 改那個 hook 造成的。
把被測檔的 mtime 當成測試檔的 mtime，剛好得到一個反過來的因果，
而那個反過來的因果正是讓它連兩輪沒人動的理由。

**三，那個 exit(2) 不是疏漏，是有記錄有煞車的規格偏離。**

`forseti-stop-hook.mjs:169-179` 那段註解寫著 owner 2026-09-16 的原話
與讓位的理由，`.forseti/config.json` 的 `enforce_declarations` 現在是 `true`。
四道煞車都在：只擋點名具體檔案的、同一輪最多一次、一條線最多三次、
cwd 不在 repo 底下完全不作用（寫死在程式碼裡）。

而兩條測試的掃描是純文字的，認不出這個差別。

**四，一個會影響決定的實測事實：它一次都沒真的作用過。**

`.forseti/declarations.json` 不存在，而那是這條路徑寫狀態的地方。
hook 本身是裝著的（`.claude/settings.json` 的 Stop，專案層不是全域），
所以不是沒觸發，是觸發了但從來沒走到要擋人那一步。
「還沒擋過」不等於「不需要擋」，所以這不構成關掉它的理由。

### 為什麼不修

三條路每一條都動到 owner 的決定：關掉她 09-16 明確開的、
放寬 09-08 事故留下的那條守備、或改 `intervention.js` 的規格判準。
照 §8.3，規格沒定義的不自己編一個填上去，所以回的是「缺什麼」。

**特別記下一條不要做的事：** 不要在 exit(2) 上面插一個問了但不照答案走的
`gate()`。兩條測試都會變綠，而守備是假的。一條在壞掉的實作下仍然通過的
測試，比沒有測試糟。

### 產出

- `.forseti/BLOCKERS.md` 新增 **B-15**，70 行。擋住的具體交付是
  `desktop/deploy.sh` 的守門沒辦法納入 JS 測試（`npm test` 現在是紅的，
  加進守門等於讓部署永遠不能跑）。三條解法各自的代價列成表。
- `.forseti/ROADMAP.md` 那一節改寫成結論加兩個更正，全文指向 B-15。
- `.forseti/ROADMAP.md` 底部「卡在你身上的三件」改成四件，加了這一條。

### 驗證

- `python3 -m pytest tests/ -q`：**819 passed**（跟上一輪同數，這一輪沒加測試，
  只動 `.md`，同數才是對的）。
- `forseti doctor`：阻塞 **6 → 7**，B-15 出現在清單上並帶著它擋住的東西。
- `node --test test/spec-v0.1.test.mjs`：VIOLATES 仍為 1（第 9 條）。
  **這一輪沒有讓任何紅燈變綠，也不該變綠。**

### 還缺什麼

- **B-15 等 owner 一句話。** 在那之前 `npm test` 不能進 deploy 守門。
- **查到一個沒動的不一致，留給下一輪：** `forseti doctor` 的閱讀清單說
  「AI-First 工程書：level 3，約三成」，但 `.forseti/reading_coverage.jsonl`
  裡那份是 `ratio 1.0` / `level FULL_READ` / `conformant true`。
  兩邊路徑不同（jsonl 記的是 Dropbox 底下的正本，doctor 對的是別的來源），
  所以這是路徑對應問題不是內容真假問題。B-04 標題已寫「2026-09-16 結案」
  卻仍留在未解除區，是同一件事的另一面。
  **沒有現在動它**，因為要動 doctor 的來源對應規則，範圍比一輪大，
  半途改它的風險是把一個正確的狀態改壞。
- **NEXT.md 看不到任何 blocker。** 那一節的 `unknowns` 來自
  `desktop_api.py:984-993` 的 blocked steps 與未讀文件，不是 `BLOCKERS.md`。
  這是設計如此不是 bug，但接手的人只讀 NEXT.md 的話不會知道 B-15 在等她。
  要不要把兩種概念併進同一節，是設計選擇，留著。

沒有 commit。沒有動畫面、Rust、hook，所以不需要 build 也不需要 deploy。

---

## 2026-09-16 18:5x　交接檔現在看得到誰在等 owner

### 挑了什麼

上一輪收尾留下兩件沒動的，挑了其中可以一輪做完的那件：
**`.forseti/NEXT.md` 一個 blocker 都看不到。**

那一份的「還沒解決的」來源是 `desktop_api.py` 的 blocked steps 與
未讀文件，不是 `BLOCKERS.md`。所以「B-15 在等 owner 一句話」這件事，
只讀交接檔的人不會知道 —— 而交接檔是停機之後唯一有人看的東西。

上一輪把它記成「設計選擇，留著」。這一輪的判斷不同：
兩個來源本來就不該合成一節，但**一節都沒有**不是設計選擇，是缺口。
所以做的是新增一節，不是把兩種概念併在一起。

### 做了什麼

一，`_blockers()` 從「只讀標題」改成讀每一節自己說的兩件事。

先前的未解除判定只看標題有沒有「解除／已解／找到並修好」。
兩個看不見的東西：

- B-04 的標題從 09-16 就寫著「結案」，而那張表沒有那個詞，
  於是一條已經結案的阻塞繼續被算進未解除數。
- B-03 的「擋住：」欄自己寫著「目前擋不住任何東西」，
  照 `BLOCKERS.md` 開頭的規則那不叫阻塞，但標題沒有結案字樣。

現在兩個訊號分開讀：標題說「這條結束了沒」，「擋住：」欄說
「它擋住哪個具體交付」。**兩邊都說結束才算結束。**

**只有一邊說的沒有被自動降級。** 照樣算未解除，另外記成 `conflicting`
讓它被看見。挑哪一邊是 owner 的決定，這份檔案是她維護的。
實測此刻 2 條（B-03、B-04），畫面與交接檔都寫得出來。

沒有「擋住：」那一行的，`blocks` 回 None 不回空字串，另記 `undeclared`
—— 「沒有寫」跟「寫了無」是兩件事，併成一個的話一條忘了填的阻塞
會被當成已解除。此刻實測 0 條。

二，`handoff.render()` 多一節「擋住的」，行文由 `_blocker_lines()` 算好。
`handoff.py` 自己解析 `BLOCKERS.md` 就會變成第二個事實來源。

三，**一個接了等於沒接的接法，是實測抓到的。** 第一版寫
`snap.get("blockers")`，跑起來不會壞、不會報錯，只會永遠給空清單 ——
因為 `snap["blockers"]` 只存在於 `snapshot()`，而 `_write_handoff` 收到的
是 `strands()` 的 snap（`'blockers' in strands()` 實測 False）。
那正是 ROADMAP「不做的事」第一條講的白工。改成自己叫 `_blockers()`。

四，截斷要看得出來是截斷。第一版把 B-15 那行切在「要把 `npm tes」，
讀起來像檔案壞了而不是「後面還有」。改成加「…（全文見 BLOCKERS.md）」。

### 順帶修掉的：出題器的同一種病第三個變體

加完那一節之後 `tests/test_gate.py::test_不做語意相似度` 變紅。
根因查出來了：新那一節的「- B-08　擋住：階段 0 的其中一半」
被 `_RULEY` 命中、`_NUM` 抽到 `08`，於是接手閘門出了一題
**答案是「08」的填空**，而「大概是講08那件事」這種含糊回答照樣算對。

**這跟 owner 2026-09-14 當場考出來的「把『不准』打出來就算對」
是同一種病的第三個變體。** 前兩個（禁令詞、單字元數字）已經擋掉。

修法是排掉識別碼裡的數字：`B-08`、`F01` 的那一段數字是這條阻塞、
這份規格的**名字**，不是它規定的值，挖掉它考的是記性不是理解 ——
跟既有的 `_DATEY` 排除日期同一條理由。
**沒有動 `grade()` 的比對方式，也沒有動抽題來源**，那兩件照 ROADMAP
要 owner 決定（那道閘門管的是誰可以動這個 repo）。

三條新測試釘住，其中一條守「不可以順手把同一行旁邊的真數字也排掉」。

### 驗證

- `python3 -m pytest tests/ -q`：**837 passed**（819 → 837，新增 18 條：
  blockers 15、blockread 3）。
- 反向驗證 9 次。blockers 那 6 次全部抓到（拿掉結案關鍵字、兩個訊號
  改成 or、blocks 改空字串、折行不接、還有幾條用截短清單算、
  沒阻塞也印那一節），識別碼那 3 次抓到 2 次。
- **第 3 次「沒抓到」的原因查清楚了，記下來因為它值得記：**
  注入的是把比對範圍從「前兩個字元」改成「整行前綴」，而 `_IDPREFIX`
  錨在結尾（`$`），所以那個改動根本不改變行為 —— 是注入無效，
  不是測試沒守住。把錨點也拿掉再注入一次就抓到了。
  **一個無效的反向驗證跟一條無效的測試長得一模一樣**，
  差別只在有沒有回去查它為什麼沒紅。
- 真正那條路徑（`strands()` 內的 `_write_handoff`）實際寫入驗證：
  `.forseti/NEXT.md` 122 行，第 29 行是「## 擋住的」，
  8 條加「還有 1 條沒列出來」，B-15 在上面。
- `strands` 實測 1.16 / 1.22 秒，低於 2 秒輪詢；`_blockers()` 0.0003 秒。
- 沒有動畫面 / Rust / hook，所以不需要 build 也不需要 deploy
  （`desktop/src-tauri/src/main.rs:70` 直接跑 repo 裡的 `desktop_api.py`，
  這一輪重新確認過）。`desktop/ui/app.js` 實測沒有任何地方用 `blockers`，
  它只透過 `_gauges` 的「阻塞」那一格，而那一格的數字沒有變（9）。

### 還缺什麼

- **B-15 仍然在等 owner 一句話**，這一輪只是讓它出現在交接檔上，
  沒有解決它。在那之前 `npm test` 不能進 deploy 守門。
- **B-03 與 B-04 的兩個訊號打架也在等 owner。** 系統現在說得出
  「這兩條的標題與擋住欄互相否定」，但不替她挑一邊。
  她要的話兩條都是一行字的事：改標題，或改「擋住：」那一欄。
- 上一輪留的另一件仍然沒動：`forseti doctor` 的閱讀清單說工程書
  level 3，而 `.forseti/reading_coverage.jsonl` 記的是 `FULL_READ`。
  兩邊路徑不同，是來源對應問題。**動它的範圍比一輪大**，仍然留著。
- `_blocker_lines` 的 8 條上限是為了不讓交接檔變長，
  超過的只說「還有幾條」。要看全部去 `BLOCKERS.md`。

沒有 commit。

---

## 2026-09-16 19:0x　畫面與交接檔上那句「都不在可動狀態」是假的，改掉

### 挑了什麼

沒有挑 ROADMAP 上的新項目。P0 的兩項一項等 owner 按（`dry_run=False`），
一項的剩下半段要 F04/F05 接上才判斷得了；P1 全部完成；
P2 是整層工程，一項一兩天，不是一輪的份量。

改挑一件先前每一輪都看得到卻沒有人去查的事：`.forseti/NEXT.md`
「卡在哪」那一節寫著

    T-7da5ef2183：7 個步驟都不在可動狀態
    T-b95303aaa2：2 個步驟都不在可動狀態

**去查了正本，那句話是假的。** `steps_of()` 回來的 7 個與 2 個步驟
**全部**是 VERIFIED_COMPLETE。兩件任務都不是卡住，是做完了沒收尾
（任務自己停在 VERIFYING）。

根因在 `desktop_api.py:2131`：`ledger.next_step()` 回 None 有好幾種
成因，而那裡把「回 None」一律翻譯成「步驟不在可動狀態」。
`next_step()` 的判準沒有錯，錯的是回 None 之後那句解釋。

**為什麼這件比新模組值得做：** 這兩種情況要人做的動作**相反** ——
一個是去解開擋住的依賴，一個是按收尾。印成同一句話，
等於把讀交接檔的人推去做一件不存在的事。而交接檔是停機之後
唯一有人看的東西。

### 做完什麼

一，`apps/forseti-cli/stuck.py`。把「派不動」分成七種，
每一種都從現有欄位算得出來，沒有新增任何步驟狀態，
也沒有動 `next_step()` 的判準。

| kind | 意思 | 要做的事 |
|---|---|---|
| NOT_STUCK | 依賴都滿足了 | 派下一步 |
| TASK_TERMINAL | 任務本身已終局 | 無 |
| NO_STEPS | 還沒拆成步驟 | 去拆 |
| ALL_VERIFIED | 步驟全部驗證完成 | 收尾 |
| ENDED_NOT_COMPLETE | 都結束了但有沒完成的 | 看要重開還是放掉 |
| DEPS_UNMET | 有未完成步驟，依賴沒滿足 | 先處理等不到的 |
| UNKNOWN | 算不出來 | 帶 missing 說少了什麼 |

**五條誠實條款，每一條都有對應測試：**

「一，永遠等不到跟正在等不合併。」依賴死在 FAILED_TERMINAL、
依賴指到不存在的 step_id、互相等對方的環，這三種不會自己解開，
歸 `unreachable`；依賴還在 RUNNING 的歸 `waiting_on`。
合成一句「等依賴」會讓人一直等一件不會發生的事。

「二，回名單不回數字。」每一筆帶「哪一步等哪一個、對方什麼狀態」。
這是這個專案第三次踩到同一件事（blast 明細、JS 盲點位置），
所以直接寫成測試要求。

「三，指到不存在的步驟回 `missing` 並指名。」不當成「還沒好」。
打錯的依賴要改資料，沒做完的依賴要等，兩件事。

「四，算不出來回 UNKNOWN 並說少了什麼**，不編一個原因。**」
§8.3 的禁止捷徑。

「五，沒卡住就回 NOT_STUCK。」不硬湊一個卡住的理由。

二，接進 `desktop_api.work()`。`row["stuck"]` 帶整個診斷，
`row["stuck_why"]` 帶 `stuck.line()` 那一行。

三，交接檔分成兩節。`_write_handoff` 照 kind 把 ALL_VERIFIED 分到
`awaiting_finish`，`handoff.render()` 多一節「等你收尾」，
標題自己講「這幾件不是卡住」。「下一步」那一句也跟著改 ——
先前一律寫「可能是任務還沒拆成步驟」，對這兩件是猜錯方向的指示，
**而一句猜錯方向的指示比沒有指示糟**。

四，畫面。先前那一行硬寫「派不動」加 `.nx.stuck` 的琥珀色，
一句假話配一個警示色。改成看 `stuck.kind`：ALL_VERIFIED 走
`.nx.fin` 綠色寫「做完了」，其餘照舊。**kind 由後端算，
前端不自己判斷**，不然會變成第二個事實來源。

### 驗證

- `python3 -m pytest tests/ -q`：**859 passed**（837 → 859，新增 22 條：
  stuck 15、handoff 4、ui_contract 3）。
- 反向驗證 13 次，**全部抓到**。stuck 7 次（兩種等合併、missing 當
  pending、全部完成講成卡住、回數字不回名單、例外時編原因、環不算永久、
  結得不好併進全部完成）、handoff 3 次、畫面 3 次。
- 真實資料實跑：兩件任務都判 ALL_VERIFIED、permanent=False、
  action=收尾，跟先前畫面上那句話相反。
- 真正那條路徑（`strands()` 內的 `_write_handoff`）實際寫入驗證：
  `.forseti/NEXT.md` 第 15 行起是「## 下一步 / 沒有待派的步驟，
  因為該派的都派完了」，第 19 行起是「## 等你收尾」，
  「## 卡在哪」整節消失（因為此刻真的沒有卡住的）。
- 效能：`stuck.diagnose` 單次 0.000023 秒，`work()` 0.003 秒。
  `strands` 冷 4.62 / 2.86 秒、熱 1.10 秒 —— 冷的那兩次是我改了 3 個
  .py 讓 blast 指紋失效重算，熱值跟上一輪記載的 1.10 一致，沒有退化。
- build + `desktop/deploy.sh`：守門測試通過，部署完成 19:19，
  **沒有開視窗**（照 owner 2026-09-16 明令，deploy.sh 預設行為沒有動）。

### 一件驗不到的，照實記

**部署後的 app bundle 裡看不到前端內容，所以「裝進去的是新版」
這件事我沒有直接證據。** Tauri 把 `frontendDist` 壓縮嵌進二進位，
`strings` 搜 `nx fin`、`renderWork`、`派不動` 全部是 0 ——
**舊字串也搜不到**，所以這個方法兩個方向都驗不了，不是它不在。

我有的間接證據只有時間序：`app.js` 改於 19:18:54，
二進位建於 19:19:17，而且 cargo 真的重編了。
**這不等於畫面上看到了。** 真的要確認只能開視窗，那件事不歸我做。

### 還缺什麼

- 這一支只改了「回 None 之後怎麼講」，沒有改 `next_step()` 本身。
  真正的問題是那兩件任務為什麼停在 VERIFYING —— 步驟全過了，
  任務狀態沒跟著走。**要不要自動收尾是 owner 的決定**，
  那是一次狀態轉換，系統不替她按（`commit.py` 的 COMMITTED 只有 OWNER
  是同一條原則）。
- `DEPS_UNMET` 那幾種分支**只有假資料測過**，正本此刻沒有卡住的任務，
  所以環、missing、dead 三種在真實資料上一次都沒出現過。
  規則是對的，但不是實測出來的。
- B-15、B-03/B-04 訊號打架仍然在等 owner，這一輪沒有動。

沒有 commit。

## 2026-09-16 19:2x 到 19:5x　§40 污染登記簿，接上交接契約缺了最久的那一欄

## 閘門

`supervisor.py --status`：會不會喚醒 true，沒有閘擋住，
原因「NEXT.md 裡還有卡住的或沒解決的」，停了 11.3 分鐘，
今天喚醒 0 次（上限 40），停止開關 false。

## 挑了什麼，為什麼

ROADMAP 的 P0 兩項都在等 owner（救援最後一步要她按、
sufficiency 強制時機要 F04/F05），P1 全部標了完成日期。
所以往 `contract.py` 自己指名的缺口走：

    "invalidated_conclusions": NoSource(
        "§40 的 PollutionRegistry 沒有實作"
        "（`grep -rn PollutionRecord apps/ src/` 零命中）"),

這一項比 P2 的其他三項優先，理由有兩個可查的：
一，它是交接契約 31 欄裡唯一一個「缺的原因明確指向一個沒寫的模組」，
不是「這個系統沒有資料來源」那種要 owner 決定的。
二，§39 反錨定接手流程第 1 步要載入五樣東西，pollution registry 是其中之一，
而它根本不存在。

## 動手前先確認不重做

- `ls apps/forseti-cli/ | grep -iE "pollut|record|incident|calib"` → 空
- `grep -rn -i "pollution|PollutionRecord|failure_mechanism"` → 只有
  `worker.py` 的 pollution budget（F03 §3，不同的東西）與
  `contract.py:847` 自己寫的那句「沒有實作」
- JS 那邊 `src/primitives.js:704` 有 `invalidatedNarrativePersistence`（FP-22），
  那是「被推翻的敘述還在傳播」的偵測器，不是登記簿。沒有重寫它。

## 規格原文，逐字

`docs/sources/..._v5.0_2026-09-04.md` §40 開頭：

    Forseti should preserve the mechanism of a misleading conclusion,
    not only the corrected number. Numbers change; failure mechanisms recur.

§40.1 列了 13 個欄位，四個狀態。§40.2 要求規則存「造成它的事故、
用來強制的偵測器、可以退役的條件」。這三句決定了整支的形狀。

## 做了什麼

一，`pollution.py`（44 個模組，先前 43）。13 個欄位逐字照 §40.1，
四態加合法轉換表。只增不改 —— `advance()` 追加一筆 STATUS，
`records()` 疊起來回現在的樣子，原始的 original_claim 與
failure_mechanism 永遠是第一筆寫的那個。

二，`tools/seed_pollution.py`。登 4 筆真實的，可重跑不重複
（id 是 original_claim 加 failure_mechanism 的 hash）。
實測重跑第二次：新增 0 跳過 4，`.forseti/pollution.jsonl` 仍是 4 行。

三，`contract._invalidated()` 接上那一欄，`invalidated_lines()` 算行文。
`desktop_api._write_handoff` 傳過去，`handoff.render()` 排版成
「## 已經被推翻的」一節。行文算在 contract 不算在 handoff，
理由跟 artifact_lines 同一條：判斷放進排版那一支就會變成第二個事實來源。

## 三條誠實條款，每一條都有測試

「一，半徑算不出來是 None 不是 0。」§40.1 列了 propagation_radius
但沒定義單位。沒給就要講 radius_basis 說為什麼算不出來，
不准留一個沒有說明的空值。四筆真實資料一個都沒填數字。

「二，狀態不准自己往上跳。」REVERIFIED 要 verifier，
RESOLVED 要 preventive_rule 或 regression_probe。
OPEN 不能直接跳 RESOLVED。可以往回走（重驗之後又發現沒好）。

「三，沒有自動掃描。」B-05 擋住單靠文字判斷宣稱。
只收明確 `record()` 呼叫，每一筆自己帶得出 source_events。

第四條在行文那一支：登記簿空的時候整節不印，
**不印「目前沒有被推翻的結論」**。這個登記簿只收明確登錄的，
空的不代表沒有污染，只代表沒人登錄，講出來等於給一個沒根據的保證。

## 一條既有測試變紅，它紅得對

`tests/test_contract.py::test_collect不會把沒有來源寫成空清單`
釘住 `invalidated_conclusions` 是 NoSource。來源有了它就該紅。

**沒有為了變綠刪掉斷言。** 把那個 key 從清單移出去，
換成兩條新的接手釘：`test_有來源的欄位不准再標成沒有來源`
（用 tmp_path 當 repo，空的登記簿回 `[]` 不是 NoSource）、
`test_未解決的污染會出現在交接契約裡`（真的 record 一筆進 tmp，
那句話與機制都要帶到）。

第二條順手釘住一件差點錯過的事：`_invalidated` 要吃 repo base，
不然測試會讀正本 4 筆，而正本的筆數會變。反向驗證 B 證實了這條會抓。

## 真實數字，每一個都實跑過

- 交接契約覆蓋率 11/31（35%）→ **12/31（39%）**。
  `python3 apps/forseti-cli/contract.py` 印出來的。
- 登記簿 4 筆，全部 OPEN，半徑沒量到 4 筆，有預防規則攔著的 1 筆。
- 測試 859 → **895**（新增 36：pollution 28、contract 5、handoff 3）。
- 模組 43 → 44。
- `.forseti/NEXT.md` 第 50 行起多一節「## 已經被推翻的」，
  第 52 行「§40 的污染登記簿裡有 4 筆還沒收乾淨」，四句話全文都在。

## 四筆真實污染，出處逐行開檔驗過

| 被推翻的 | 出處 |
|---|---|
| 事件帳本裡有 lineage 邊 | ROADMAP.md:121、event_ledger.py:122 與 132 |
| Blast Radius 缺的是查詢與畫面 | ROADMAP.md:126、cost.js:62 與 107 |
| `vitals.dimensions()` 已經逐輪算八個維度 | ROADMAP.md:108、vitals.py:589 |
| 兩條紅燈的 mtime 是 09-16 13:11 | ROADMAP.md:502、BLOCKERS.md |

`verifier` 分兩段寫：發現的人是當初那一輪，登錄的人是這一輪。
把登錄者寫成發現者會讓這份登記簿看起來比實際可靠。

## 一個順手驗到的小差異，照實記

ROADMAP.md:121 引用 `event_ledger.py:117`，實際 `LINEAGE_EDGES`
在第 122 行。差 5 行，應該是後來檔案有變動。
**沒有把它登成污染** —— 行號漂移不會誤導結論，
跟那四筆「推論方向錯了」不是同一類。登錄時用我實際驗到的 122。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**895 passed**。
- 反向驗證 **10 次，全部抓到**：
  pollution 6 次（半徑填 0、RESOLVED 不要求預防規則、
  OPEN 直接跳 RESOLVED、REVERIFIED 當成已收乾淨、機制不列入 id、
  空的出處放行）、contract 與 handoff 4 次（改回 NoSource、
  忽略 repo base 讀正本、空的時候硬印一句「沒有被推翻的」、
  行文不提機制、limit 失效整批倒進去）。
- 真正那條路徑實際跑：`D.strands()` 內部的 `_write_handoff`
  重寫 `.forseti/NEXT.md`，md5 從 `4844cef0…` 變成 `014f216e…`，
  新版第 50 行是那一節。
- seed 腳本冪等性實測：重跑新增 0 跳過 4，檔案仍 4 行。

## 一個先前沒搞懂、這一輪查清楚的機制

手動呼叫 `_write_handoff(snap)` 一直回 None，先前以為是接線沒生效。
實際是 `handoff.MIN_GAP_S = 240`（4 分鐘節流），而 `strands()`
自己在第 3076 行就已經呼叫過一次了 —— 手動那次永遠被節流擋掉。
用 `touch -t` 把 mtime 推回去再跑，`should_write()` 回 True，
md5 確實變了。**機制沒問題，是我的呼叫順序讓它看起來沒生效。**

## 沒有 build 也沒有 deploy，理由

沒有改 `desktop/ui/app.js` 也沒有改 `app.css`，畫面那半邊一個字都沒動，
所以不需要重建。**也沒有開關 Forseti App**（owner 2026-09-16 明令）。
順帶查過 `ps aux | grep -i Forseti`：此刻沒有在跑。

## 還缺什麼

- **桌面畫面沒有入口。** 這一節只在 `.forseti/NEXT.md` 上。
  `pollution.summary()` 與 `records()` 後端都算得出來，
  缺的是入口，**跟 blast 明細那次同一種缺口**，
  所以不寫成「後端不支援」。這是下一輪最直接的一項。
- 四筆全部 OPEN，一筆都沒走過 PARTIAL / REVERIFIED / RESOLVED。
  轉換規則有測試，但真實資料上一次都沒走過。
- `propagation_radius` 四筆全是 None。要它有值就要先定義單位，
  而規格沒有定義，**那是 owner 的決定不是我的**。
- FP-22（`src/primitives.js:704` 的 invalidatedNarrativePersistence）
  跟這個登記簿是天然的一對：登記簿有「哪些話被推翻了」，
  FP-22 判「被推翻的敘述還在不在傳播」。兩邊沒有接。
  **沒有接是因為我沒驗過 FP-22 的輸入形狀**，不是因為接不起來。
- B-15、B-03/B-04 訊號打架仍然在等 owner，這一輪沒有動。

沒有 commit。

---

## 2026-09-16 20:0x　§40 污染登記簿有桌面入口了

挑的是上一輪收尾自己指名的那一項：「桌面畫面沒有入口，
`pollution.summary()` 與 `records()` 後端都算得出來，缺的是入口，
跟 blast 明細那次同一種缺口，這是下一輪最直接的一項。」

## 動手之前先確認它真的不存在

這個 repo 在 2026-09-16 一天之內重複實作過三次同一個東西，
所以先查再寫：`grep -n "pollution" desktop_api.py app.js main.rs` 三個檔
**零命中**，入口確實不存在。後端三個檔（`pollution.py` 341 行、
`test_pollution.py`、`.forseti/pollution.jsonl` 4 行）都在。

## 做了什麼

`desktop_api.pollution_panel()`。**`pollution.py` 一行都沒改** ——
這一支只把 `summary()` 與 `records()` 挑成畫面要的形狀，
不在這裡重算狀態、不重算 guarded。兩份會分歧的實作，
分歧那天不會有錯誤訊息，這條跟 `blast.py` 對 `cost.js` 同一條。

接進 `snap["pollution"]`，CLI 也有入口（`desktop_api.py pollution`）。
`app.js` 的 `renderPollution()` 畫出來，跟八維度共用同一個展開開關
（`.dims.open ~ .pollution`），呼叫點兩個（輪詢那條與展開那條）。

真實資料：4 筆全部 OPEN，1 筆有偵測器攔著，4 筆量不到擴散半徑。

## 三條誠實條款，每一條都在畫面上而且有測試

一，半徑 `null` 印「擴散半徑算不出來」加 `radius_basis`，**不印 0**。
規格列了欄位沒定義單位，0 讀起來是「量過了，沒有擴散」。

二，0 筆印「登記簿是空的」，**不印「沒有被推翻的結論」**。
這份沒有自動掃描（B-05），沒人登不等於沒有。讀不到登記簿的時候
`has: False` 帶原因，**不回空清單** —— 空清單在畫面上跟「乾淨」
長得一模一樣，跟 `live_conflicts` 同一條。

三，有攔著的筆數單獨報，其餘那些「現在只靠人記得」這句話看得見。
一筆 OPEN 的污染跟一筆有偵測器攔著的，在總數上長得一樣。

## 截圖與實測抓到三個只有真的打開才看得到的問題

**一，這一格捲得動，而它每 1 到 3 秒整塊換 `innerHTML`。**
實測：捲到 450px，6.5 秒後 `scrollTop` 回到 0，`sameNode` 是 false。
症狀是第 3、4 筆永遠看不到，而程式沒有任何錯誤 ——
**跟 blast 搜尋框吃掉使用者的字是同一個根因**，只是換一種表現。
修法也同一條：重畫前記下位置，畫完放回去，而且要夾住上限
（不夾的話筆數變少會停在一個空白的位置）。
修完實測：跨 7 秒多次重畫，節點換過，`scrollTop` 仍是 450。

**二，捲動區把第二筆切成半截。** 半截讀起來像畫面壞了，不像下面還有
（5c 那次為半行付過一次代價，這次是半筆）。加底部漸層與一行提示。
**內容塞得下的時候印一句「往下捲」是假的**，所以那兩個判斷都要量。

**三，第一版的漸層只看內容有沒有超出，結果捲到底最後一筆的出處被淡掉。**
實測到底時 `lastRowBottom` 與 `listBottom` 都是 295，內容是完整的，
只有漸層把它遮掉。一個永遠亮著的「還有更多」跟沒有提示一樣沒用，
而且它會蓋掉真的內容。改成跟著捲動位置算（`syncPlCut`），
捲動事件委派在只建立一次的容器上、走捕獲階段（scroll 不冒泡）。
修完實測：捲到底 `rest` 1、`cut` false，第 4 筆出處完整顯示。

## 一條測試第一版是假的守備，反向驗證抓到

`test_捲得動這件事要看得見而且是量出來的` 只檢查
`scrollHeight - list.clientHeight` 有沒有出現在檔案裡，而那個算式
**在還原捲動位置那一行也有**，所以把判斷寫死成 `const over = true`
照樣會過。已改成釘那兩個判斷本身，兩個方向都重驗過會紅。

一條永遠綠的測試比沒有測試糟，它讓人以為那條路有人守
（跟 5c 刪掉那條「單行註解也不吃掉換行」同一個理由）。

## 一個我自己造成又自己修掉的 CSS 缺陷，照實記

改 `.plId` 的時候第二個字串替換把 `color:var(--ink-4)` 一起吃掉了，
那一條不會報錯也不會被 `test_ui_contract` 抓到（沒有缺 `var()`，
只是少一條宣告，會靜默繼承父層顏色）。開檔看到才發現，已補回。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**909 passed**（上一輪 895，新增 14）。
- 反向驗證 **17 次**：16 次抓到，1 次沒抓到（上面那條假守備，
  補精確後兩個方向都紅）。每次破壞後用 md5 逐檔比對確認還原無誤。
- 真實資料實跑：`desktop_api.py pollution` CLI 4 筆；
  `D.strands()` 帶得出 `snap["pollution"]`，熱快取 1.22 秒，
  沒有超過 2 秒輪詢間隔（pollution 讀一個 4 行 jsonl，成本可忽略）。
- 瀏覽器 harness 實際打開看過：4 筆全部渲染，機制那行每筆都有，
  半徑四筆都印「算不出來」加原因，三條誠實條款都在畫面上，
  沒有任何元素溢出容器。捲動行為三個狀態（頂、中、底）都量過。

## 重建與部署了，沒有開關 App

動了 `app.js` 與 `app.css`，所以 `npx tauri build --debug --bundles app`
加 `deploy.sh`。守門測試過，二進位 20:09。
**全程沒有開啟或關閉 Forseti App**（owner 2026-09-16 明令），
`deploy.sh` 照原樣跑，它印「沒有開視窗」是正確行為。
順帶查過 `ps aux`：這一輪開始與結束時 App 都沒有在跑。

## 沒有驗到的那一段，照實講

**App 視窗裡長什麼樣沒有驗。** Tauri 把 UI 壓縮嵌進二進位，
`strings` 連舊字串（`renderBlast`、`波及範圍`）都查不到，
所以那個查法證明不了新程式碼有沒有進去。能證明的只有時間序：
`app.js` 20:07:13 → 二進位 20:09:44，build 讀的是最新版本。
畫面那一層我驗到的是 harness，用的是同一份 `app.js` 與 `app.css`，
但 harness 已知的盲點是它 stub 掉 `window.__TAURI__`
（那一支檔頭自己寫著這件事）。

## 還缺什麼

- 四筆全部 OPEN，狀態轉換（PARTIAL / REVERIFIED / RESOLVED）
  在真實資料上一次都沒走過。畫面畫得出來，沒有東西走過去。
- `propagation_radius` 四筆全是 None。要它有值就要先定義單位，
  **規格沒有定義，那是 owner 的決定不是我的**。
- FP-22（`src/primitives.js:704` 的 invalidatedNarrativePersistence）
  跟這個登記簿是天然的一對，還沒接。**沒接是因為我沒驗過
  FP-22 的輸入形狀**，不是因為接不起來。
- 畫面上這一格是唯讀的。登一筆新污染只有 `tools/seed_pollution.py`
  這條路，桌面上沒有入口。**這一輪沒有自己決定要不要做** ——
  一個從畫面寫進登記簿的按鈕，寫的是「哪些話被推翻了」這種
  會被後繼者當成事實的東西，那道權限跟 §9.3 的 COMMITTED 同一類。
- B-15、B-03/B-04 訊號打架仍然在等 owner，這一輪沒有動。

沒有 commit。

---

# 2026-09-16 20:3x　§12.2 Source-of-truth registry

挑的是 ROADMAP P2 第 7 項。P0 兩項都卡在 owner（救援的 `dry_run=False`
那一按、sufficiency 的強制時機要等 F04/F05），P1 五項全部做完了，
所以往下走到 P2。

先確認不存在:`ls apps/forseti-cli | grep -i "sot|source|truth"` 零命中，
`grep -rln "source_of_truth|precedence|PREFERRED_SOURCE"` 零命中。
這個專案一天之內重複實作過三次同一個東西，動手前先查是硬規則。

## 那張表是七行不是五行

先前一次讀 §12.2 只讀到規格第 375 行就停了，所以 ROADMAP 那句
「五個」差一點被當成這張表的行數寫進程式碼。實際是第 371 到 377 行，
**七行**，多出來的兩行是 Agent session state 與 Model training run ——
正好是這個 repo 最缺的那兩塊。

（澄清一件事:ROADMAP「卡在你身上」那張表裡的「§12.2 五個病症對應
FP 編號」講的是另一件事，不是這張來源表。兩件事都掛在 §12.2 底下。）

這件事本身就是 §12.2 在講的東西:讀到一半的視窗跟完整的來源
長得一模一樣，而前者不會報錯。所以 `verify_spec()` 拿那七行的
**原文逐行比對** —— 不是「這個字串有沒有出現在檔案某處」，
那種檢查在一份四千行的規格裡幾乎一定會過，等於沒有。

## 這個 repo 現在信誰，是人工登記的

看起來最聰明的做法是掃原始碼猜每一類狀態從哪裡讀。不做，
理由跟 `pollution.py` 不做自動掃描同一條（B-05）:靠文字判斷
「這段程式在宣稱什麼」，抓到的是符合句型的段落，
而漏掉的那些會長得跟「沒有來源」一模一樣。

所以 `BINDINGS` 每一條都要附 file 加一段原文，防腐爛的機制不是
相信登記的人，是 `verify_bindings()`:原文找不到了是 STALE
（這條登記不能再信），行號變了是 DRIFTED（正常，程式碼會動）。
兩者的下一步不一樣，所以不能併成一個「壞了」。
現在 0 條過期、0 條漂移，七行的憑據全部指得回真實位置。

## 七行的現況，每一條都查過才寫

- 接上了 1:檔案內容。工作區逐檔雜湊，git HEAD 只當對照。
- 沒有來源 1:服務健康。`watchdog.py` 算的是 heartbeat 停滯，
  那是「有沒有在動」不是「服務健康」，所以這一格不給燈號。
- 接了一半 3:工作進度、owner 決定、agent session 狀態。
- 不適用 2:外部 API 物件、訓練 run。
  **這兩個是查證過的不適用，不是還沒接** —— 前者實際查了
  apps/forseti-cli、src、hooks 三個執行期目錄，唯一的命中是
  `migrate.py:156` 的 `socket.gethostname()`（取主機名不是連線）
  與 `tools/check-page-readable.py`（獨立工具，不在執行期路徑上）。

## 只有一行有即時量測，這件事印在畫面上

§12.2 第一行說 git 只有在「部署自同一個 revision」時才算來源，
那個條件量得出來，所以這一行有真的答案:工作區 97 個檔跟 HEAD 不一致
（26 個已追蹤有改動、71 個從來沒進版控，兩種分開數因為下一步不一樣），
所以這一刻 git 不是這一類狀態的來源。

其餘六行的 `live` 是 **None 不是空字典** ——
空字典在畫面上會被當成「查過了，沒事」。
畫面上那幾行印的是「這一行沒有即時量測」，
而整格底下有一句「其餘六行的 live 是 None，那是『沒量』不是『健康』」。
一個沒有被檢查過的綠燈比沒有燈更糟，因為它會讓人不去看。

## 我猜錯了一個回傳形狀，當場被自己的執行結果打臉

`_file_content_live()` 第一版寫的是 `w.get("ok")` 與 `w.get("paths")`，
而 `contract.worktree_paths()` 回的是 `entries` 加 `problem`。
症狀是那一格永遠印不出量測結果，**而且不報錯** ——
它安靜地走進「量不到」那條分支。跑 CLI 才看到那一行缺了。

這是「看到函式名就當成知道它回什麼」的同一類錯（§40 登記簿裡
那筆 LINEAGE_EDGES 是同一個機制）。修完之後照那支自己的 docstring
分清楚兩件事:空清單加 problem 是「沒量到」，空清單沒 problem 是
「量過了，乾淨」。兩條測試各釘一種。

## 兩條測試第一版是假守備，反向驗證抓到

**一，反模糊比對那條。** 第一版用的問句是「這個東西該信誰」，
而那句在模糊比對下也對不上任何別名，所以把 `t in cands` 改成
`any(t in c || c in t)` 照樣全綠。現在用的是**會被模糊比對誤判**的
句子:「我想知道服務健康狀態跟檔案內容哪個重要」含有兩個別名，
而它問的不是這兩類的任何一類。

**二，固定尾巴清單那條。** 第一版用「服務健康狀態怎麼查」，
而那句在「遇到『該』就砍」的通用切法下也對不上，所以把固定清單
換成通用切法照樣全綠。現在用的是含「該」但尾巴不在清單裡的句子
（「服務健康狀態該去哪裡查」）。

一條永遠綠的測試比沒有測試糟，它讓人以為那條路有人守。
這是這個專案第三次與第四次踩同一個坑，前兩次記在 5c 與 5h。

## 一條既有測試被我改壞，它抓到了

`test_pollution_panel.py` 釘死 `function syncPlCut(list) {` 整個參數列，
而我讓那支函式多收一個選擇器參數（兩格共用同一套捲動修正，
不長第二份會分歧的實作）。那一行守的只是「函式存在」，
真正的守備是後面三條判斷，所以改成只釘函式名，三條判斷沒有動。
**沒有為了讓測試變綠而改回去，也沒有把那三條一起放寬。**

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**951 passed**（上一輪 909，新增 42）。
- 反向驗證 **12 次**:10 次抓到，2 次沒抓到（上面那兩條假守備，
  補精確後兩個方向都紅）。每次破壞後用 md5 逐檔比對確認還原無誤。
- 真實資料實跑:`desktop_api.py sot` 七行全部帶得出來；
  `desktop_api.py sot "服務健康狀態該信誰"` 回
  「Process manager + health endpoint + socket/listener」，
  `not_source` 裡有 git ——**完成定義那句原文實際成立**。
- 成本:`sot.assess()` 0.185 秒。`D.strands()` 熱快取量了三次
  3.03 / 1.91 / 1.26 秒，穩定後跟上一輪的 1.22 秒同一個量級。
- 瀏覽器 harness 實際打開看過:七行全部渲染、捲動區 248px 對 946px 內容、
  漸層在頂與中是亮的、到底關掉（最後一行的出處不會被淡掉）、
  跨三次重畫節點換過而 `scrollTop` 仍是 400、沒有任何元素溢出容器。

## 截圖抓到一個字串層級的瑕疵

註記裡的反引號原樣印在畫面上（`watchdog.py` 那種）。那是我自己寫的
字串，不是資料，所以直接拿掉 10 個。登記簿那一格的反引號來自 jsonl
資料，不動它。

## 重建與部署了，沒有開關 App

動了 `app.js` 與 `app.css`，所以 `npx tauri build --debug --bundles app`
加 `deploy.sh`。守門測試過，二進位 20:35:42，`app.js` 20:29:33 ——
build 讀的是最新版本。**全程沒有開啟或關閉 Forseti App**
（owner 2026-09-16 明令），`deploy.sh` 印「沒有開視窗」是正確行為。
部署前後查 `ps`，App 都沒有在跑。

**App 視窗裡長什麼樣沒有驗。** 跟上一輪同一個限制:Tauri 把 UI
壓縮嵌進二進位，`strings` 連舊字串都查不到。畫面那一層我驗到的是
harness，用的是同一份 `app.js` 與 `app.css`，而 harness 已知的盲點
是它 stub 掉 `window.__TAURI__`。

順帶記一件事:harness 開起來第一次量到的版面全是 0，原因是
`#panel` 預設 `hidden`（要 `togglePanel(true)` 才展開），
不是 CSS 壞掉。先前差點把它當成自己的 bug。

## 還缺什麼

- 服務健康那一行要真的有值，得先有程序管理器或健康端點。
  **那是「要不要把 Forseti 自己變成被監控對象」的決定，不是接線問題**，
  所以這一輪沒有自己決定。
- 「接了一半」那三行的另一半各自對應一個沒實作的實體:
  §11.1 AgentIdentity（P2 第 8 項）、簽署過的政策物件、
  可查詢的 failed_attempts。三個都不是這一格的事。
- FP-22（`src/primitives.js:704`）這一輪查了輸入形狀:它要
  `planNodes`（帶 `id` / `depends_on` / `status`）與
  `invalidatedPrerequisites`（一組 id）。**登記簿的
  `affected_decisions` 是散文不是 id**，沒有任何結構化的邊把
  被推翻的結論連到計畫節點。所以接上去只會得到一排 OK ——
  那正是 ROADMAP「不做的事」第二條寫的「餵半套資料比不接更糟」。
  **這一輪沒有接，理由從「沒驗過輸入形狀」更新成「驗過了，缺的是邊」。**
- 污染登記簿四筆仍然全部 OPEN，狀態轉換在真實資料上一次都沒走過。
- B-15、B-03/B-04 訊號打架仍然在等 owner，這一輪沒有動。

沒有 commit。

---

# 2026-09-16 21:0x　P2 第 8 項 AgentIdentity（§11.1）

## 挑了什麼，為什麼是這一項

ROADMAP P2 剩三項:第 6 項 Workflow/WorkflowStep、第 8 項 AgentIdentity、
第 9 項 Probe Packs。挑第 8 項的理由不是它最小，是**它被別的模組點名欠著**:
上一輪 `sot.py` 的七行裡，「agent session 狀態」那一行寫著
「提供端那一半在，§11.1 的 AgentIdentity 沒有實作」。
一個被別的模組指名為缺口的東西，比一個只在清單上排隊的東西先做。

動手前先確認它不存在:`grep -ril "agentidentity\|agent_identity"` 只命中
`contract.py` 與 `sot.py` 兩處**提到它缺**的字串，
`ls apps/forseti-cli/ | grep -i "ident\|workflow"` 空。沒有重複實作。

## 做完了什麼

`apps/forseti-cli/identity.py`。規格 §11.1 只有六行，短到很容易被當成
口號讀過去，所以這一支做的是把那六行變成**五個查得出狀態的軸**。

每一軸只有三種答案，而且第三種不准被投影成好消息:

| 軸 | 狀態 | 依據（真實資料實跑） |
|---|---|---|
| ≠ Model | 分得開 | 80 條 session 裡 10 條在同一條線內用過不只一個模型 |
| ≠ Session | 混在一起 | 帳本 31 個 alias 被當成「誰做的」，持久身份登記 0 條 |
| ≠ Process | 沒有來源 | 逐行掃 80 條，有 pid 欄位的 0 條 |
| ≠ Execution Slot | 沒有來源 | 沒有排程器、沒有 worker pool、兩邊都沒有欄位 |
| ≠ Role | 沒有來源 | worker 名稱像角色但那是 alias，沒有角色定義 |

「≠ Session 混在一起」是這一輪最有內容的一句話，而且它不是設計出來的，
是量出來的:這個 repo 現在用的「身份」(`assigned_worker` / `actor` /
`accepted_by` 那 31 個字串)全部是 session alias，換 session 就換，
所以它本身就是 §11.1 要區分開的那一軸。

## 一個假摔的數字，自己抓到的

檔頭第一版寫「19 條 session 換過模型」。那個 19 來自我寫來探路的
臨時腳本，而那支腳本沒有排除 `<synthetic>`（runtime 合成的訊息，
不是一個模型）。正式模組排除之後是 10。

**跟 `blast.py` 那次 resolutionRate 從 0.971 掉到 0.541 是同一種病**:
把一個不該算進分子的東西放進去，數字就開始說謊，而說出來的那個謊
聽起來比真話更有力（19 比 10 好看）。檔頭把這件事寫下來，
`test_synthetic不算換過模型` 與 `test_兩個真模型才算換過` 兩個方向都釘住。

## 不做的事，各自的理由

- **不從 alias 命名相似度推斷同一身份。** `norikaoda-03` 與
  `norikaoda-84` 前綴一樣，看起來像同一個人的兩條線。不做這個推斷，
  理由跟 `sot.py` 不掃原始碼猜來源、`pollution.py` 不自動掃描同一條
  （B-05）:抓到的是符合命名慣例的字串，而真的同一身份但改過命名的
  那些會長得跟「兩個不同身份」一模一樣。所以登記簿是人工的。
- **三軸 NO_SOURCE 不給燈號。** 一個沒被檢查過的綠燈比沒有燈更糟。
- **Process 那一軸不寫死 0。** `observe_session()` 真的逐行看有沒有
  `pid` 欄位，所以哪天 runtime 開始寫，那個數字自己會動。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**995 passed**（上一輪 951，
  新增 44:`test_identity.py` 39 條，`test_ui_contract.py` 5 條）。
- 反向驗證 **11 次**（10 次抓到，1 次沒抓到）。沒抓到的那次是破壞
  `actors()` 的「帳本完全不存在」分支，全綠。查出來是那支有兩個
  失敗分支而只有一個有測（測試打的是「給了路徑但開不起來」），
  補 `test_連預設帳本都沒有的時候也要說不可得` 之後兩個方向都紅。
  每次破壞後用 md5 逐檔比對確認還原無誤。
- 真實資料實跑:`python3 apps/forseti-cli/identity.py` 五個軸全部
  帶得出依據；`desktop_api.py identity` 回得出 JSON；
  `identity.py --verify` 五行加錨點全部對上規格原文。
- 成本:`identity.assess()` 掃 80 條 session 約 1.35 秒。
- 瀏覽器 harness 實際打開看過:五個軸全部渲染、捲動區 248px 對 611px
  內容、cut 遮罩有作用、跨多次重畫節點換過而 `scrollTop` 仍是 300、
  沒有任何元素溢出容器、console 無錯誤。截圖看過。

## 截圖又抓到同一個字串瑕疵

`synthetic_note` 裡的反引號原樣印在畫面上。**跟上一輪 `sot.py` 那次
一模一樣的瑕疵**，所以這次在原始碼那一行旁邊寫了原因，不只是改掉。
那是我自己寫的字串不是資料，所以直接拿掉。

## 重建與部署了，沒有開關 App

動了 `app.js` 與 `app.css`，所以 `npx tauri build --debug --bundles app`
加 `deploy.sh`。守門測試過，二進位 21:00:52，`app.js` 20:57:06 ——
build 讀的是最新版本。**全程沒有開啟或關閉 Forseti App**
（owner 2026-09-16 明令），`deploy.sh` 印「沒有開視窗」是正確行為。
部署前後查 `ps`，App 都沒有在跑。

**App 視窗裡長什麼樣沒有驗。** 跟前幾輪同一個限制:Tauri 把 UI 壓縮
嵌進二進位。畫面那一層我驗到的是 harness，用的是同一份 `app.js`
與 `app.css`，而 harness 已知的盲點是它 stub 掉 `window.__TAURI__`。

## 還缺什麼

- 三軸 NO_SOURCE 要變成有值，各自缺一個這個專案現在沒有的東西:
  Process 要 runtime 寫 pid、Execution Slot 要排程器或 worker pool、
  Role 要一份寫著「這個角色能做什麼、不能做什麼」的定義。
  **三件都不是接線問題**，所以這一輪沒有自己決定。
- Session 那一軸要從 CONFLATED 變 SEPARABLE，缺的是有人去登記那
  31 個 alias 分別屬於哪幾個持久身份。**那是 owner 的知識，
  不是掃得出來的** —— 這正是登記簿做成人工的理由。
- P2 還剩第 6 項（Workflow / WorkflowStep）與第 9 項（Probe Packs）。
- 污染登記簿四筆仍然全部 OPEN。B-15、B-03/B-04 訊號打架仍在等 owner，
  這一輪沒有動。

沒有 commit。

---

# 2026-09-16 21:2x　P2 第 6 項 Workflow / WorkflowStep

## 挑了什麼，為什麼是這一項

上一輪(21:0x)做完 P2 第 8 項 identity，收尾寫著「P2 還剩第 6 項
(Workflow / WorkflowStep)與第 9 項(Probe Packs)」。第 6 項排在前面。

動手之前先確認它不存在:`ls apps/forseti-cli/` 沒有 `workflow.py`，
`grep -rn "commit_boundary\|WorkflowStep" apps/ src/ tests/` 只命中
`authority.py:219` 一行(那是 COMMIT_BOUNDARY 動作表，不是這件事)。
這個專案在 09-16 一天內重複實作過三次同一個東西，所以這一步不省。

## 規格先讀完才寫，四行原文

- §5 第 156 行　Workflow:workflow_id, objective, state, commit_boundary, owner
- §5 第 157 行　WorkflowStep:step_id, status, inputs, outputs, external_refs
- §17.1 第 471 行　Workflow Reconstruction:external object IDs, step state,
  retries, approvals → Resumable durable workflow
- §6.2 第 194 行　STEP_START, STEP_COMMIT, STEP_ROLLBACK, APPROVAL_REQUESTED

`verify_spec()` 逐行比對那四行整行原文，不是「這份檔案裡有沒有出現
Workflow 這個字」—— 那個字在四千行的規格裡出現十幾次，那種比對等於
沒有比對。反向驗證把它降級成 `"Workflow" in raw`，測試立刻紅。

## 做了什麼

`workflow.py`。**沒有新增任何一張表** —— 這條線上已經有耐久的
task/step(`ledger.py` 的 sqlite)，再建一套平行的存放區，兩套遲早
會分歧，而分歧那天不會有錯誤訊息。所以這一支是同一份 sqlite 的
另一種讀法。

核心是 `resume()`,§17.1 那一行要的「Resumable durable workflow」。
四類分得很開，因為它們的下一步不一樣:

- ready　　依賴都終態了而且自己還沒終態，現在就能做的
- blocked　還在等依賴，每一筆講得出在等誰
- done　　 已經終態
- dangling 依賴指到不存在的 step_id

**dangling 不併進 blocked。** 資料壞了跟在等人，處理方式剛好相反，
而併在一起之後前者會讀起來像後者(「它在等 T-1/MISSING」——
可是那個 step 根本不存在，沒有人會來完成它)。

## 「程序死掉接得回來」怎麼變成機械可驗的

ROADMAP 那一項的完成定義是一句話:「一件跨 session 的工作，程序死掉
之後接得回來，而不是靠模型記得」。那句話本身不可驗，所以翻成:

    resume() 只讀磁碟，所以另一個程序跑同一次重組，答案要逐欄一致。

`test_另一個程序重跑答案一樣` 用 `subprocess` 另起一個 python，
把兩邊的結果 `sort_keys` 之後逐字元比。

**這條測試自己也被驗過。** 同一個程序裡呼叫兩次永遠會綠，就算答案
其實藏在 module-level 的 dict 裡，所以那種測試是假守備。
反向驗證的做法是在 `resume()` 的回傳值裡加一個 `os.getpid()`,
那一條立刻紅 —— 證明它真的抓得到「答案跟程序有關」這件事。

## commit_boundary 為什麼是人工登記的

`authority.py` 已經有一張 `COMMIT_BOUNDARY` 動作表(send / deploy /
spend / delete / publish / push)，所以看起來最省事的做法是拿 step 的
objective 文字去比對那張表，自動判出哪幾件跨邊界。

**不做**，理由是 B-05:靠文字判斷「這句話有沒有在宣稱某件事」
抓到的是符合句型的字串。這裡的代價比別處高 —— 一個被漏判的
commit boundary 意思是「這一步不可逆而沒有人在守」，
而它在畫面上會長得跟「這一步很安全」一模一樣。

所以沒登記就是 `UNDECLARED`，而 `UNDECLARED` 不是 `NONE`:
前者是「沒有人回答過這個問題」，後者是「有人看過而且說不跨」，
復原的時候這兩件事的下一步不一樣。畫面上那句話寫的是
「沒有人登記過」，反向驗證把它改成「不跨邊界」，
`test_沒有人登記過不准畫成不跨邊界` 紅。

登記簿 `.forseti/workflow_boundary.jsonl` 只增不改，
`declared_by` 必填 —— 一筆沒有人認領的宣告，跟沒有宣告的差別
只在畫面上比較好看。跟 `pollution.py` / `identity.py` / `sot.py` 同一條。

## 規格 §6.2 那四種事件，實測一筆都沒有

STEP_START / STEP_COMMIT / STEP_ROLLBACK / APPROVAL_REQUESTED 各 0 筆。
帳本實際用的是自己的命名:STEP_STATE 86、TASK_STATE 49、
PROGRESS_REPORT 33、DISPATCH 27。

**不做同義詞對映。** 把 STEP_STATE 算成 STEP_START 等於把
「我們沒照規格記」翻譯成「我們照規格記了」。兩者的差別要到復原的
時候才顯現:STEP_STATE 記的是狀態轉換，STEP_COMMIT 記的是
「這一步的效果已經對外生效了」，後者才是 rollback 要看的那一筆。
反向驗證加上 `elif kind == "STEP_STATE": counts["STEP_START"] += n`,
三條同時紅。

## 真實資料實跑

17 件 workflow，2 件在跑。兩件都是步驟全部完成、
0 能做 0 等依賴 0 壞掉(T-7da5ef2183 是 7/7、T-b95303aaa2 是 2/2)，
等的是收尾。**這個結論是這一支獨立算出來的，而它跟 `NEXT.md` 的
「等你收尾」那一節逐項吻合** —— 兩條不同的路算出同一件事。

兩件的 commit_boundary 都是 UNDECLARED。
欄位覆蓋 Workflow 3/5、WorkflowStep 2/5，兩個數字不合成一個。

## 五個誠實條款，每一條都有測試而且印在畫面上

- `external_refs` 回 None 不回 `[]`。steps 表十五個欄位沒有任何一欄
  放外部物件 ID(`evidence_refs` 放的是 `cmd:` / `file:` 開頭的證據
  參照，那是「怎麼驗證」不是「在外部系統建立了哪個物件」)
- `inputs` DEGRADED:`dependencies` 是順序不是輸入。機械上分得出來
  —— 那一欄每一筆都是 step_id，不是路徑也不是值
- `outputs` DEGRADED:`expected_outputs` 是預期不是實際。
  測試連欄位名都釘(不准在這一支改叫 outputs)
- `owner` DEGRADED:值是 session alias。依據是 `identity.py` 量過的
  31 個 alias、持久身份登記 0 條，不是我記得
- `approvals` 回的是「要不要人」不是「批准了沒有」。
  steps 表只有 `requires_human` 這個布林，沒有批准者與批准時間。
  反向驗證加一個 `approved_by: None` 進去，那一條紅

## 又是同一個字串瑕疵，第三次

`why` 那幾個欄位裡的 `**` 會原樣印在畫面上。
**`sot.py` 與 `identity.py` 前兩輪各犯過一次同樣的事**(那兩次是反引號)。
這次在 `WORKFLOW_FIELDS` 上面那一行寫了原因，不只是改掉:
那幾條是印到畫面上的字串，不是 markdown。
掃出 4 處，改完重掃 0 處。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**1037 passed**(上一輪 995，
  新增 42:`test_workflow.py` 35 條、`test_ui_contract.py` 7 條)。
- **反向驗證 16 次，16 次全部抓到。** 十次打 `workflow.py`
  (external_refs 改 PRESENT、沒登記回 NONE、dangling 併進 blocked、
  同義詞對映、答案跟程序有關、覆蓋率合成一個、允許空 declared_by、
  壞行靜默跳過、approvals 加 approved_by、verify_spec 降級)，
  六次打接線(拿掉呼叫、刪一個 CSS class、拿掉捲動還原、
  UNDECLARED 翻成不跨邊界、後端 snapshot 那一行、共用開關改自己一套)。
  每次破壞後用 md5 逐檔比對確認還原無誤。
- 真實資料實跑:`workflow.py --verify` 四行原文全部對上；
  `desktop_api.py workflow` 回得出 17 件；
  `desktop_api.py workflow T-7da5ef2183` 重組得回 7 個 done；
  不存在的 id 回 `ok: false` 帶原因不回空的。
- 成本:`workflow.assess()` 0.020 秒、`workflow_panel()` 0.003 秒。

## 瀏覽器 harness 實際打開量過

不是只看 DOM 裡有沒有那個字串:

- 2 筆渲染，wfl 高 618px 寬 400px，**0 個元素溢出容器**
- **內容塞得下的時候那句「捲得動」確實是隱藏的**
  (`claimsScrollWhenFits: false`)。這是前幾輪踩過的坑:
  內容塞得下還印「往下捲」是假的
- 捲動保留:把 max-height 壓到 90px 製造可捲狀態(用 CSS 規則不用
  inline style —— 第一次用 inline style 量不到，因為每次重畫
  innerHTML 整塊換，inline style 跟著節點一起消失)，
  捲到 60px，等 6.5 秒跨多次重畫，**節點換過了而 `scrollTop` 仍是 60**
- 可捲的時候 `cut` 漸層與提示同時亮起，塞得下的時候兩個都收起來
- console 無錯誤。截圖看過

**一件過程中查清楚的事:** 第一次量幾何全部回 0，包括既有的
`.idn` / `.sot` / `.pollution` / `#vitals`。**不是這一格的問題** ——
是 `#panel` 預設 hidden(`index.html` 第 38 行)，要點 `#miniT` 才開，
而且瀏覽器面板當時是隱藏的所以 `innerWidth` 也是 0。
跟既有那幾格對照才分得出是自己壞了還是整個容器沒版面。

## 順帶量到一件跟這一項無關、但比它急的事

**`strands` 現在要 4.3 到 6.6 秒，而畫面每 2 秒輪詢一次。**
ROADMAP 第 5a 節寫的「4.53 秒 → 1.29 秒，低於 2 秒的輪詢間隔」
**已經過期**，那句話現在不成立。

**不是這一輪造成的，而且這句話是量出來的不是推的。** 做了 A/B:
把 `snap["workflow"]` 換成一個常數再跑 4.77 秒，換回來 4.31 秒，
差在噪音範圍內。`workflow_panel()` 本身 0.003 秒。

逐格量:`identity_panel` **1.613 秒**、`sot_panel` 0.364 秒、
`pollution_panel` 0.028 秒、`workflow_panel` 0.003 秒。
四格加起來 2.0 秒，所以還有 2 秒以上在別的地方，**沒有追下去**
(這一輪挑的是第 6 項，追下去就是同時做兩件)。
已寫進 ROADMAP 6a 當下一輪的起點。

## 重建與部署了，沒有開關 App

動了 `app.js` 與 `app.css`，所以 `npx tauri build --debug --bundles app`
加 `deploy.sh`。守門測試過，二進位 21:27，`app.js` 與 `app.css` 21:20
—— build 讀的是最新版本。**全程沒有開啟或關閉 Forseti App**
(owner 2026-09-16 明令)，`deploy.sh` 印「沒有開視窗」是正確行為。
部署前後用 `pgrep -fl "Forseti.app/Contents/MacOS"` 查，都是空的。

**App 視窗裡長什麼樣沒有驗。** 跟前幾輪同一個限制:Tauri 把 UI
壓縮嵌進二進位。畫面那一層驗到的是 harness，用的是同一份 `app.js`
與 `app.css`，而 harness 已知的盲點是它 stub 掉 `window.__TAURI__`。

## 還缺什麼

- 兩件在跑的 workflow，commit_boundary 都沒有人登記過。
  **那是 owner 的知識不是掃得出來的**，已加進 ROADMAP
  「卡在你身上」那張表。
- `approvals` 答不出「誰批准了、什麼時候」，steps 表沒有那兩個欄位。
- 規格 §6.2 那四種事件要真的有值，得改 hook 的寫入端，
  **那會動到帳本的寫入格式，這一輪沒有自己決定**。
- `strands` 超過輪詢間隔那件(6a)，`identity.assess()` 是最大的一格，
  `blast.py` 有現成的磁碟快取作法(指紋失效不是時間失效)可以照抄。
- P2 還剩第 9 項(Probe Packs)。
- 污染登記簿四筆仍然全部 OPEN。B-15、B-03/B-04 訊號打架仍在等 owner，
  這一輪沒有動。

沒有 commit。

---

# 2026-09-16 21:5x　挑了 ROADMAP 6a:後端跟不上前端

上一輪收尾寫「`strands` 超過輪詢間隔那件(6a)，`identity.assess()`
是最大的一格」。挑了這一項，做完了，而**上一輪那句話只對一半**。

## 先量再改，而且量出來的跟上一輪記的不一樣

`strands` 實測 6.19 秒（輪詢間隔 2 秒）。cProfile 逐段:

- `blast.summary()` **2.392 秒**
- `identity_panel()` **1.792 秒**
- 其餘（`_meta_rows`、`focused_session`、`sot_panel`、`_ui_id_of`）合計約 1.5 秒

**上一輪的「還有 2 秒以上在別的地方」，主要就是 blast。**
上一輪逐格量的時候 blast 不在那四格裡，所以它被歸進了「別的地方」。

## 一句先前的描述被推翻:第 5a 節的快取從來沒有蓋住 `collect()`

`vectors()` 與 `summary()` 的第一行都是 `g = collect(root)`，
**快取是在那之後才問的**。所以讀 120 個檔加 AST 剖析那 1.89 秒
每一次都重跑，5a 節量到的「4.53 秒 → 1.29 秒」省的是 node 那一段。

這不是推論:`_cache_get` 的呼叫位置在 `blast.py` 裡是
`collect()` 回來之後的第 580 與 792 行（改之前），逐行讀過。

## 兩個快取，作法不一樣，理由是資料的形狀不同

**一，`blast.collect()` 用整批一個指紋**，照 5a 已經有的那一套
（`_fingerprint` 的檔案集合加 mtime_ns 加 size）。原始碼只有在
有人改檔時才變，所以整批指紋幾乎永遠命中。`collect()` 算完的指紋
一併帶出來（`g["fp"]`），`vectors()` 與 `summary()` 直接用，
省掉它們各自再掃一次兩個目錄樹（實測 0.24 秒）。

**二，`identity.survey()` 不能用整批指紋。** session 檔是活的，
當前那一條每講一句話就長大一次，整批指紋幾乎每次都不一樣，
快取會永遠不命中。改成**逐檔**:key 是路徑加 mtime_ns 加 size，
動過的那一條自己重讀，其餘直接用上一次的結果。
快取存的就是 `observe_session()` 的輸出，**沒有第二份實作** ——
在快取那條路上重算一次判斷，兩份遲早會分歧而且不會有錯誤訊息。

**臨時 repo 與臨時目錄一律不走快取**（`base != REPO` / `root is not None`）。
exFAT 的 mtime 解析度是 10 毫秒，而測試正是在這個時間尺度上建檔改檔；
臨時目錄本來就只用一次，快取在那裡沒有價值只有風險。

## 踩到一個只有對比冷熱才看得見的坑

反向驗證在「快取命中」那條路上改了一個欄位，那個值被 `fresh[k] = o`
**寫回磁碟**，於是程式碼還原之後錯的答案還留在快取裡:
`multi_model_count` 從 10 變 0，畫面上那句依據
（「掃過的 80 條每一條都只用過一個模型」）讀起來完全合理，
而且**沒有任何錯誤訊息**。

發現它靠的是把快取檔搬走重跑一次冷的，逐欄比對冷熱。
命中路徑上任何一個 bug 都會這樣被固化，所以把那條路切斷了:
`fresh[k] = hit if hit is not None else o`（命中的寫回原件，不是下游的 `o`）。
`test_命中之後就算有人改了結果也不會被寫回磁碟` 釘住。
事後把正本快取檔刪掉重建，重建後的值跟冷跑逐欄一致，
全套測試跑完再查一次仍然一致。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**1049 passed**（上一輪 1037，
  新增 12:`test_identity.py` 6、`test_blast.py` 5、`test_ui_contract.py` 1）。
- **反向驗證 11 次。** 九次直接抓到，兩次沒抓到:
  - 「指紋不看 mtime 與 size」第一版沒抓到。根因是那條測試順手
    **加了一個新檔**，於是指紋因為「集合變了」而失效，把 mtime 與 size
    從指紋裡拿掉照樣會綠。改成檔案集合不變、只改一個檔的內容與 mtime
    之後抓到。一條永遠綠的測試比沒有測試糟。
  - 「快取那條路自己改了 `lines`」沒抓到，**而那一次不該補測試**:
    `lines` 不出現在 `survey()` 的任何輸出裡，改它不改變任何對外可見的
    答案。為了抓它寫一條測試等於釘住一個不存在的契約。換成改 `models`
    （會影響 `multi_model_count`）之後抓到。
- 冷熱一致性:`survey()` 冷跑與熱跑**逐欄比對相等**（`cache_hits` 除外），
  `multi_model_count` 兩邊都是 10、`models_seen` 前三名逐項一致。
- 效能實測（同一台機器，連跑三次取後兩次）:
  `strands` **6.19 秒 → 0.79 到 0.86 秒**。
  逐段 `blast.collect()` 2.22 → 0.018 秒、`identity.survey()` 1.56 → 0.004 秒。

## 畫面

identity 那一格多一行「這一次有 N 條 session 用的是上一次量的結果」。
**0 條命中就不印**，一句空話會讓人以為系統在講什麼。
顏色用 `--ink-3`，跟 blast 的 `.blStale` 同一條理由:
刻意不做成警告色，它不是錯誤，是一個要看得到的事實。

三段接線各釘一條（`test_快取命中那句話三段都接上`），反向驗證三次
全部抓到:JS 不印、CSS 少 class、後端不給欄位。

瀏覽器 harness 實際打開量過:那一行渲染出來，
文字「這一次有 79 條 session 用的是上一次量的結果，動過的那幾條重讀過了」、
色 `rgb(134,134,139)`、10px、寬 400、**右緣溢出 0**。
把 `cache_note` 改成空字串重繪，那一行消失；還原後又出現。console 無錯誤。

**一件沒做到的事，照實記:截圖沒有對準那一格。**
`scrollIntoView` 之後元素的 `getBoundingClientRect().top` 是 377，
而截圖拍到的是 workflow 那一區。所以「用眼睛看過那一行」這一輪沒做到，
上面那些是量出來的數字不是看出來的。

## 重建與部署了，沒有開關 App

動了 `app.js` 與 `app.css`，所以 `npx tauri build --debug --bundles app`
加 `deploy.sh`。守門測試過，二進位 21:46，`app.js` 與 `app.css` 21:42
—— build 讀的是最新版本。**全程沒有開啟或關閉 Forseti App**
（owner 2026-09-16 明令），部署前後 `pgrep -fl "Forseti.app/Contents/MacOS"`
都是空的。App 視窗裡長什麼樣沒有驗，跟前幾輪同一個限制。

## 還缺什麼

- `strands` 還有約 0.8 秒，逐段最大的是 `_meta_rows` 0.618 秒與
  `focused_session` 0.34 秒，**沒有追下去**（這一輪挑的是 6a，
  追下去就是同時做兩件）。低於輪詢間隔了，所以它不再是急件。
- 污染登記簿四筆仍然全部 OPEN，這一輪沒有動。
- B-15、B-03/B-04 訊號打架仍在等 owner。
- P2 還剩第 9 項（Probe Packs）。
- 上面那個「快取污染」事件符合 §40 污染登記簿的形狀，但它是我自己
  反向驗證的副作用，不是這個專案對外講過的結論，所以**沒有登記進去**。
  登記簿記的是被推翻的結論，不是測試程序的意外。

沒有 commit。

---

# 2026-09-16 22:1x　自動接續　挑了 P2 第 9 項 Probe Packs（§15）

## 為什麼挑這一項

`supervisor.py --status` 回「會不會喚醒 true」，沒有閘擋住。
ROADMAP 的 P0 兩項都卡在 owner 那一邊（救援最後一步要她按、
sufficiency 強制不該急著做），P1 全部做完，P2 只剩第 9 項。
P3 兩項自己寫著擋住的原因還在。所以第 9 項是唯一能動的。

動手之前先確認它不存在：`ls apps/forseti-cli/` 沒有 probe.py，
`grep -rli probe` 命中的是 `desktop_api.selftest()` 裡一個同名的
內部函式，讀過那一段之後確認是 §33 的功能自證，不是 §15 的 probe pack。
兩者問的問題不一樣，寫進模組檔頭了。

## 做了什麼

`apps/forseti-cli/probe.py`。

§15.1 的 schema 十一個欄位照原文一字不改，§15.2 的十類照原文順序，
兩件事各有一條測試釘住。九類接上真實偵測器，用合成的 setup 跑：

| 類別 | 接到哪 |
|---|---|
| goal_persistence | `northstar.Chain` 的 at_version / is_stale / supersedes |
| claim_evidence_honesty | `evidence.can_support` + `claims.Claim.promote` |
| handoff_sufficiency | `rehydration.CompressionBoundary` + coverage_report |
| fastpath_routing | 沒有來源，NO_VERIFIER |
| stale_cache | `northstar.is_stale` + `goalgate.freshness` |
| tool_loop_blank_output | `yieldcheck.judge` + `watchdog.assess` |
| authority_commit | `authority.collisions` + `commit` 狀態機 |
| reconstruction | `rehydration.coverage_of` 四種讀取範圍 |
| multi_agent_consensus | `claims.Claim.repeat` 碰不到 strength |
| topology_sot | `sot.verify_bindings` |

CLI 接進主入口：`forseti probe list / run / baseline <誰按的>`。

## 三件事沒有憑記憶寫，查了才寫

一，`rehydration.coverage_report()` 沒有 `declared_level` 參數，
也不回 `ratio` 跟 `ok`。第一版照猜的寫，跑起來 TypeError。
讀了原始碼第 48 行起那一段才改對。

二，`claims.KINDS` 只有 file / number / passfail / unextractable，
沒有 capability。猜的那個名字直接丟 ClaimError。

三，`commit` 的狀態機沒有捷徑，DRAFT 到 COMMITTED 要走
PREPARING → PREPARED → AWAITING_APPROVAL。第一版想一步跳過去。

三個都是同一種病：看到函式名就以為知道它收什麼回什麼。
三個都在第一次跑的時候就炸了，沒有一個是靠眼睛看出來的。

## 誠實條款，寫進程式碼而且跟著每一次輸出走

**這一項只完成了三軸裡的一軸。** §15 原文要跨 models、versions、
contexts。這一版的 verifier 跑的是這個 repo 的偵測器程式碼，
不呼叫任何模型，所以它量得到程式碼改動造成的判準退化，
量不到換模型或改路由造成的退化。`AXES_COVERED` 與 `AXES_MISSING`
是兩個常數，`run()` 與 `summary()` 每一次都帶著它們。

**NO_VERIFIER 不是 PASS，而且不算進通過率的分母。**
`fastpath_routing` 在這個 repo 沒有東西可量
（`grep -rliE "fastpath|routing" apps/forseti-cli/ src/` 排除 probe.py
自己之後命中 0 個檔）。一個沒有東西可量的情境，跟一個量過而且通過的
情境，在一張綠色的表上長得一模一樣。

**基準線不自己更新。** `run()` 碰都不碰那個檔，只有
`record_baseline(by=...)` 會寫，而且沒有 `by` 直接拒絕。
自動更新的基準線等於沒有基準線：每一次退化都會在下一次變成新常態，
曲線永遠是平的。跟 checkpoint 的 last_good 不自己挑同一條理由。

**verifier 自己炸掉判 REGRESSED 不判 PASS。**
一個跑不起來的檢查等於沒有檢查，但它在摘要上長得像通過。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**1078 passed**（上一輪 1049，
  新增 29 條全在 `tests/test_probe.py`）。
- **反向驗證 13 次，全部抓到。** 每一條都是把被測模組真的弄壞：
  證據守備放寬、重複次數開始影響強度、agent 按得下 commit、
  同一個人重複宣告被算成衝突、自己說自己懂就給第 6 級、
  空輸出併進提早收工、拔掉停滯判定的煞車、舊版北極星被刪掉、
  過期的不再被標成過期、freshness 不說是誰決定的、
  壓縮改掉任務狀態不再被抓、上界標記變成可以關掉、登記的原文不見了。
- **一次真實的退化演練，不是 monkeypatch。** 真的把
  `goalgate.freshness` 的 `decided_by` 從原始碼刪掉，
  `forseti probe run` 判 REGRESSED、指名變動欄位是
  `freshness_has_decider`、離開碼 1。還原之後 sha256
  `c6060f5333b4e725...1054a380` 跟改動前逐字元一致，重跑回到 9 PASS。
  這一條是整包唯一能證明它跨得了 versions 那一軸的證據，
  因為 monkeypatch 只證明測試會紅，不證明真實改動會被抓到。
- 基準線實跑：`forseti probe baseline "auto-continue 2026-09-16"`
  寫進 9 筆（不含 NO_VERIFIER 那一筆），重跑 9 個 PASS。

## 沒有動畫面，所以沒有重建部署

`app.js` 與 `app.css` 一個字都沒改，`deploy.sh` 沒跑。
**全程沒有開啟或關閉 Forseti App**（owner 2026-09-16 明令）。

## 還缺什麼

- **probe 還沒接畫面。** `probe.summary()` 已經備好給畫面用的形狀
  （不含 observed 全文，那個太大），但 `desktop_api` 沒有接，
  `app.js` 沒有 renderProbe。下一輪做這個的話要動 app.js，
  照慣例先確認要替換的區間裡沒有別的定義。
- models 與 contexts 那兩軸要一個會呼叫模型的執行器才談得上，
  那不是多寫幾個情境能補的。
- 污染登記簿四筆仍然全部 OPEN，這一輪沒有動。
- B-15、B-03/B-04 訊號打架仍在等 owner。
- `strands` 還有約 0.8 秒，這一輪沒有追。

沒有 commit。

---

# 2026-09-16 22:3x　自動接續　§15 Probe Packs 接上畫面

挑這一項的理由：上一輪的收尾自己寫著「probe 還沒接畫面，
`probe.summary()` 已經備好給畫面用的形狀，但 `desktop_api` 沒有接，
`app.js` 沒有 renderProbe」。ROADMAP 的禁區第一條是
「不為了盤點數字接輔助函式，接上去畫面不會變的東西，接了就是白工」——
這一項反過來，後端算得出來但畫面上一個字都沒有。

## 動手之前先確認它不存在

`ls apps/forseti-cli/ | grep -i probe` 只有 `probe.py` 自己。
`grep -n "renderProbe\|probe" desktop/ui/app.js` 零命中。
`grep -n 'snap\["probe"\]' apps/forseti-cli/desktop_api.py` 零命中。

**有一個同名的東西不是它。** `desktop_api.py:2607` 有一個區域函式
`probe(name, spec, live, synth_fn)`，那是自我審計那一頁的探針，
跟 §15 的 Probe Packs 是兩件事。所以 `probe_panel()` 裡用
`import probe as PB`，跟 `blast as BL` 同一條慣例，不在模組頂層 import。

## 做了什麼

- `probe.summary()` 補兩個欄位：`baseline_at` 與 `pack_covers_spec`。
  先前只帶 `baseline_by`，而**一條三個月前的基準線跟一條剛剛錄的，
  在「跟基準線一致」這句話裡分量差很多**。
- `desktop_api.probe_panel()` + `snap["probe"]`。算不出來時 has=False
  帶原因，不回空清單 —— 空清單讀起來是「沒有哪一類退化」。
- `app.js` 的 `renderProbe()` 與 `PRB_ZH`，接進輪詢與展開按鈕兩條路徑。
- `app.css` 的 `.prb` 一組，共用 `.dims.open ~ .prb` 這一個展開開關。
- `tests/test_ui_contract.py` 的 `ProbePanelIsWiredEndToEnd`，11 條。

## 四條誠實條款在畫面上，不在註解裡

- **沒有東西可量不是通過。** 通過率的分母是 `measurable`（9）不是十，
  `NO_VERIFIER` 的 chip 顏色跟 PASS 分開，畫面上直接寫
  「不算進通過率的分母」。
- **沒有基準線要自己講。** 十個 NEW 一樣沒有紅字。
- **基準線誰按的、多舊，兩個一起印。**
- **§15.2 十類蓋滿了沒有。** 蓋不滿時通過率偏高，因為漏的不在分母裡。

## 反向驗證 13 次，前 11 次有兩次沒抓到，兩條測試當場改嚴

第一次跑 11 條，8 條抓到、2 條沒抓到、1 條字串對不上跳過。
**沒抓到的兩條是我自己寫鬆的，不是弄壞的方式不對：**

一，`renderProbe(` 全檔出現三次（定義一次、兩條呼叫路徑各一次），
而測試要求「至少兩次」，所以拿掉其中一條呼叫仍然是兩次。
改成分別釘住輪詢那一段與展開按鈕那一段，兩條路徑的症狀不一樣：
拿掉輪詢那條，這一格打開之後凍住；拿掉展開那條，要等下一次輪詢。
**`renderIdentity` 與 `renderWorkflow` 那兩組有同一個弱點，
這一輪沒有一起改**，那不屬於這一格。

二，「算不出來的時候不回空清單」只要求那句原因出現一次，
而 `_safe` 的預設值與後面那個 `or` 是兩個各自會被改掉的地方。
改成要求兩次都在。

改嚴之後重跑那三條，5 / 5 全部抓到，三個檔還原後 sha256 逐字元一致。

## 驗證，每一項都實際跑過

- `python3 -m pytest tests/ -q`：**1089 passed**（上一輪 1078，
  新增 11 條全在 `ProbePanelIsWiredEndToEnd`）。
- `strands` 耗時：接之前熱快取 0.889 秒，接之後量三次
  1.38 / 0.855 / 0.839 秒。probe 的 verifier 跑合成 setup 不讀真實狀態，
  所以這一格不需要磁碟快取。
- `npx tauri build --debug --bundles app` 過，`desktop/deploy.sh` 部署完成，
  守門測試通過。**deploy.sh 自己回報「沒有開視窗」。**
- **瀏覽器裡真的看過**（`tools/ui-harness.py --port 8793`）：
  這一格高 484px、列表 248px 可捲（scrollH 476）、十列的狀態與
  chip 顏色都對（通過 rgb(81,81,84)、沒有東西可量 rgb(161,161,166)）、
  console 無錯誤。捲到 200px 之後等 6.5 秒跨多次重畫（DOM 節點確實
  換新），scrollTop 仍然是 200。

## 一個查了才寫的東西

harness 開起來之後量到這一格高度 0，十格全都 0。
**不是這一格的問題** —— `.vitals` 的父層 `.panel` 預設 `hidden`，
要 `togglePanel(true)` 才展開，`vWhy` 那個按鈕只切 `.dims.open`。
逐層往上量父層鏈才看到的，不是猜的。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。`pgrep -f "Forseti.app/Contents/MacOS"` 在部署前後
各查一次，兩次都是沒有在跑，所以 deploy.sh 的 pkill 沒有殺到任何視窗。

## 還缺什麼

- **`probe` 的另外兩軸（models、contexts）仍然跨不了**，缺的是一個會
  呼叫模型的執行器，不是多寫幾個情境。畫面上每一次都帶著這句。
- `fastpath_routing` 仍然 NO_VERIFIER，這個 repo 沒有路由層。
- 污染登記簿四筆仍然全部 OPEN，這一輪沒有動。
- B-15、B-03/B-04 訊號打架仍在等 owner。
- `renderIdentity` / `renderWorkflow` 那兩組的「只數次數」弱點還在。
- `strands` 還有約 0.85 秒，這一輪沒有追。

沒有 commit。

---

# 2026-09-16 22:4x　自動接續　把上一輪自己記下的測試弱點補掉

挑這一項的理由：上一輪的收尾在「還缺什麼」裡自己寫著
「`renderIdentity` / `renderWorkflow` 那兩組的『只數次數』弱點還在」。
ROADMAP 的 P0 到 P2 已經全數做完，P3 兩項擋在資料與換版條件、
P4 明寫現在做就是用終極願景掩蓋產品不好用，剩下的四件卡在 owner。
所以這一輪唯一不需要她決定、又確實有東西可交付的，就是這個缺口。

**這一項不是新功能，是把一個抓不到問題的測試變成抓得到。**
排程規則第四條寫著「測試要能抓到問題，不是永遠回 OK」，
而這兩條當時明明白白不是。

## 先證明弱點真的存在，不是照抄上一輪的說法

`grep -n "renderIdentity(\|renderWorkflow(" desktop/ui/app.js` 實際數：
兩個各出現三次（定義一次、輪詢那一段一次、展開按鈕那一段一次）。
舊測試是 `assertGreaterEqual(len(calls), 2)`，
所以拿掉其中一條呼叫路徑之後仍然是兩次，不會紅。

## 範圍就是這兩條，不是八格全改

`grep -rn "assertGreaterEqual(len(calls)\|assertGreaterEqual(len(re.findall"`
全 `tests/` 只命中這兩處。其他幾格的寫法不同而且守得住：
`renderPollution` 與 `renderBlastHits` 用 `assertEqual(..., 3)`，
少一條就是 2 ≠ 3 會紅；`renderSot` 用 `renderSot(d)` 與
`renderSot(lastSnap` 兩個 assertIn，本來就分兩條路徑。
**所以這一輪不去動它們** —— 沒有壞的東西不要修。

## 做了什麼

- `tests/test_ui_contract.py` 兩條 `test_渲染函式有被主流程呼叫`
  改成 `test_渲染函式在兩條路徑上都有人叫`，照 `renderProbe` 那一組
  的寫法，分別用正則框出輪詢那一段與 `vWhy` 展開按鈕那一段，
  在各自的區間裡要求 `renderX(d)` 與 `renderX(lastSnap`。
- 順帶把 `renderProbe` 那條測試裡「那兩組這一輪沒有一起改」那句
  註解改成現況。**過期的狀態敘述正是這個專案今天吃過虧的東西**
  （`PHASE_STATUS.md` 說五階沒開始、實際三階已完成）。

## 反向驗證四條路徑，四條全部抓到

一次腳本跑完，每一次都是改壞 → 跑測試 → 還原：

| 弄壞哪一條 | 新測試抓到 | 舊寫法會怎樣 |
|---|---|---|
| identity 輪詢 | 是 | 仍是 2 次，舊門檻 >=2 過關 |
| identity 展開 | 是 | 仍是 2 次，過關 |
| workflow 輪詢 | 是 | 仍是 2 次，過關 |
| workflow 展開 | 是 | 仍是 2 次，過關 |

右邊那一欄是同一次量出來的，不是推論：腳本在每個破壞狀態下
直接數了 `renderIdentity(` / `renderWorkflow(` 的出現次數，四次都是 2。
**所以舊版四條全部會漏，不是只有理論上會漏。**

`desktop/ui/app.js` 還原後 sha256 `25dd7d835ff5cea6...`，
與改動前逐字元一致。

## 驗證

- `python3 -m pytest tests/ -q`：**1089 passed**，與上一輪同數。
  這一輪沒有新增測試條數，因為是把兩條既有的改嚴，不是加新的。
- `python3 -m pytest tests/test_ui_contract.py -q`：59 passed。
  deploy.sh 的守門就是跑這一支，所以守門沒有因為這個改動變紅。
- `.forseti/NEXT.md` 用 `desktop_api.strands()` 重新產生（22:44），
  不是手寫。它抓到 `tests/test_ui_contract.py` 的新 hash
  `c92c22d498a6ed63`（先前 `00929d4a5e7be97e`），
  證明這一輪的改動有進到狀態裡，不是只有我說有。

## 沒有動畫面，所以沒有重建部署

只改了 `tests/`，`app.js` 與 `app.css` 一個字都沒改（sha256 驗過）。
重建不會讓畫面有任何不同，**跑一次 build 只是讓這篇日誌好看**。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪根本沒有呼叫 `deploy.sh`，
也沒有 `open` 或 `pkill` 任何東西。

## 還缺什麼

- 「只數次數」這一類弱點在 `tests/` 裡已經清空（grep 命中 0），
  但**這只涵蓋「呼叫路徑」這一種**。測試寫鬆還有別的形狀，
  例如上一輪抓到的第二種（一句原因出現一次就算過，
  而實際有兩個地方各自會被改掉），那種沒有辦法用 grep 掃出來。
- 污染登記簿四筆仍然全部 OPEN，這一輪沒有動。
- `probe` 的 models / contexts 兩軸仍然跨不了。
- `fastpath_routing` 仍然 NO_VERIFIER。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應，
  全部仍然在等 owner。這一輪沒有替她決定任何一件。
- `strands` 這一輪量到 3.5 秒（含 import 與冷啟），沒有追。

沒有 commit。

---

# 2026-09-16 23:0x　理由自己會腐爛，所以理由也要被複查

## 挑了什麼，為什麼

沒有照 ROADMAP 的順序挑，是**在讀 `contract.py` 的缺口清單時被一句
過期的理由絆到**。`logical_agent_id` 那一欄寫著「§11.1 的 AgentIdentity
沒有實作（`grep -rn AgentIdentity apps/ src/` 零命中）」，
而 ROADMAP P2 第 8 項白紙黑字寫著 `identity.py` 在同一天 21:0x 做完了。

先驗證再動手，不是照抄 ROADMAP 的說法：

```
$ grep -rn "AgentIdentity" apps/ src/
apps/forseti-cli/contract.py:843:  ...沒有實作（grep 零命中）
apps/forseti-cli/sot.py:224:       ...§11.1 的 AgentIdentity 沒有實作，
$ ls -la apps/forseti-cli/identity.py
-rwx------ 28656 Sep 16 21:45
```

**那句話當初是查過的，它是在寫下來之後才變成假的。** 而且那次 grep
的結果本身已經自我指涉：現在唯二的命中就是那兩句「說它沒實作」的話。

跟今天早上那個事故同一種病（`PHASE_STATUS.md` 說五階沒開始、實際三階
已完成，於是有人重做一遍），只是腐爛的東西換成了「為什麼這一欄沒有
來源」的理由。**一句過期的理由比沒有理由危險**，因為它指出的下一步
是錯的：NO_SOURCE 讀起來像「要先蓋一整個系統」，實情是「系統在了，
沒有人去登記」。

## 先確認不是重做已經做過的東西

```
$ ls apps/forseti-cli/ | grep -i "recheck\|verify"
（無）
$ grep -rl "Recheck\|recheck" apps/forseti-cli/ src/
（無）
```

`sot.py` 有 `verify_bindings()`，但它驗的是「evidence 指的那段原文
還在不在」，不是「理由裡附的查法還成不成立」，兩件事。
沒有重複實作。

## 做了什麼

一，**`logical_agent_id` 從 NO_SOURCE 改成接 `identity.registry()`**。
借那一支不自己讀 jsonl（跟借 `claims._disk()`、借 `cost.js` 同一條）。
登記 0 條是 `Empty` 並說得出下一步，登記了就**精確比對** alias，
不比前綴不比相似度（B-05，`identity.py` 檔頭同一條理由）。

二，**`Empty(why)`**。先前 EMPTY 是唯一一種連理由都沒有的狀態，
因為它只能靠「值剛好是空的」判出來。五種狀態沒有變成六種。

三，**`Recheck` 與 `recheck_all()`**。理由裡附的查法寫成資料由程式跑，
不從 `why` 的文字剖析查法 —— 那又是一次文字判斷。
`declared_in` 一定要排除，不然每一條都會自己觸發自己。

四，`sot.py` 的 `agent_session_state` 那條逐字重複的過期理由一起修，
evidence 改指 `identity.py:459` 與 `contract.py:336`。

## 它是觸發器不是結論，而且這件事有現成的實例

B-05 擋住「單獨靠文字判斷」，但明文不擋「拿它當觸發器、再用證據驗證」。

排除宣告檔之後 `AgentIdentity` 仍然命中 `sot.py:223`，而那一處現在是
一句**記錄這次更正的註解**（在那之前是一句「說它沒實作」的散文）。
純比對分不出實作、散文、與一句講這件事的註解。所以輸出只給位置，
判斷留給人，而且「這是要去看一眼，不是說那句理由錯了」這句話印在
輸出裡，不留在註解裡。

## 這個機制真的抓得到當初那次腐爛，不是理論上會抓

```
$ python3 -c "...用當初那條被推翻的宣告跑一次..."
logical_agent_id stale= True actual= 1 ['apps/forseti-cli/sot.py:224']
```

`test_recheck抓得到當初那次腐爛` 把這件事釘住。抓不到就代表這個機制
對它存在的理由無效，那比沒有這個機制糟 —— 畫面上會多一節看起來
有人在守的東西。

## 一個只有對比冷熱才看得見的坑

第一版量出來：

```
熱快取: 1.953s  cached=[False, False]      ← 比不用快取還慢
不用快取: 0.058s
```

根因：指紋把 `__pycache__` 算進去，而每跑一次 python 都可能重寫 .pyc，
於是指紋每次都不一樣、快取永遠不命中。**畫面上沒有任何異狀也沒有
錯誤訊息**，只有 `strands` 白白慢兩秒。修正後：

```
第1次 1.651s cached=[False, False]
第2次 0.005s cached=[True, True]
第3次 0.005s cached=[True, True]
```

`strands` 熱測三次 0.872 / 1.089 / 1.038 秒，低於 2 秒輪詢間隔。
（第一次 5.086 秒是 blast 快取因為我改了 `contract.py` 而失效，
不是這一支造成的。）

指紋與 grep 現在跳過同一批目錄，用同一個常數，
`test_grep那一邊也跳過同一批目錄` 釘住兩邊不准分歧。

## 一條測試第一版是假的守備，反向驗證當場抓到

第一版的 `test_指紋跟grep跳過同一批目錄` 只檢查原始碼裡有沒有
`_RC_SKIP_DIRS` 與 `--exclude-dir=`。把 `_rc_fingerprint` 裡那一行
呼叫拿掉之後，常數與 grep 那一邊都還在，所以它照樣綠。

改成建一個真的 `__pycache__`、動它、斷言指紋不准跟著動，
再斷言真的原始碼變了指紋一定要變。兩個方向都驗過。

**一條永遠綠的測試比沒有測試糟，它讓人以為那條路有人守。**
這是連續第三輪抓到同一類問題（呼叫次數、原因出現次數、現在是字串存在），
形狀都不一樣，所以沒有辦法用 grep 一次掃乾淨。

## 兩條既有測試因此變動，兩條都不是為了變綠

一，`test_collect不會把沒有來源寫成空清單` 變紅，**而它紅得對** ——
它守的是「有來源了還寫沒有來源」，那一刻它抓到的正是這件事。
沒有刪斷言，是把那一欄移出清單並補上「不准退化成一個沒有理由的空值」。
作法跟上一輪 §40 那次一模一樣。

二，`test_行號漂移是DRIFTED不是STALE` 對**全域** drifted 數字斷言，
於是這一輪在 `contract.py` 中段加了約 250 行之後它從 1 變 6 而變紅。
那跟它想驗的事無關。改成只數被動過的那一條。
順帶把 `sot.py` 那 8 個漂掉的行號更新到正確位置
（DRIFTED 不擋，但指不準的行號會讓下一個人翻到不相干的程式碼）。
現在 stale 0、drifted 0。

## 驗證

- `python3 -m pytest tests/ -q`：**1107 passed**（上一輪 1089，+18）。
  contract 15 條、handoff 3 條。
- 反向驗證 **18 次，17 次抓到**。沒抓到的那一次就是上面那條假守備，
  補精確後再驗 3 次（含守過頭的方向）全部抓到。
  每一次都是改壞 → 跑測試 → 還原，還原後 sha256 逐字元一致
  （`contract.py` `5892adb4b6ba0dc7`）。
- `sot.verify_bindings()`：stale 0、drifted 0、ok True。
- `.forseti/NEXT.md` 用 `desktop_api.strands()` 重新產生（23:08），
  不是手寫。`logical_agent_id` 那一行已經從「沒有資料來源」變成
  「來源在，此刻空的」並帶著下一步。
- 交接契約：NO_SOURCE 13 → 12、EMPTY 4 → 5。
  **PRESENT 仍然是 12/31，沒有變** —— 那一欄的值仍然不存在，
  改的是「為什麼沒有」這句話的準確度，不是覆蓋率。

## 沒有動畫面，所以沒有重建部署

`desktop/ui/app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`，
跟 NEXT.md 記的完全一致，一個字都沒動。
`main.rs:70` 直接跑 repo 裡的 `desktop_api.py`，所以後端改動立即生效。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪沒有呼叫 `deploy.sh`，
沒有 `open` 也沒有 `pkill` 任何東西。

## 還缺什麼

- **現在只有兩條理由掛得上查法**（`owner`、`metrics_by_distribution`，
  兩條都實測 0 命中）。其餘 10 條 NO_SOURCE 的理由是語意判斷
  （「這個專案不是訓練任務」），**沒有查法可掛也不該硬編一個** ——
  硬編出來的查法會變成一條永遠綠的守備。
- `Empty` 目前只有 `logical_agent_id` 用。另外 4 個 EMPTY 欄位
  （blockers / next_step / last_good_pointer / recovery_status）
  仍然沒有理由，**那是下一輪最直接的一項**，而且是一條線的距離。
- 這一輪做的東西此刻在 NEXT.md 上看不見（stale 是 0，0 條整節不出現）。
  那是設計不是壞掉，接線有沒有通是用三條測試釘的。
- 污染登記簿四筆仍然全部 OPEN。`identity` 的三軸 NO_SOURCE 沒動。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  **這一輪沒有替她決定任何一件。**

沒有 commit。

---

# 2026-09-16 23:3x　另外四個 EMPTY 欄位也說得出下一步了

## 挑了什麼，為什麼是這一項

上一輪自己寫在「還缺什麼」的第二條：`Empty(why)` 做好了但只有
`logical_agent_id` 用，另外四欄（blockers / next_step /
last_good_pointer / recovery_status）仍然沒有理由，「那是下一輪最直接
的一項，而且是一條線的距離」。

這四欄先前是**唯一一批連理由都沒有的空欄位**。它們在 NEXT.md 上印出來
只有一句「來源在，此刻空的」，後面空白 —— 說不出誰去做什麼它就會有值。

## 做了什麼

四支小函式，全部**借現成的判斷**，一個都沒有自己重判：

一，`_next_step(work)` 借 `stuck.py` 算好的 kind。**不把所有「沒有下一步」
說成同一件事** —— `handoff.py` 付過這個代價（先前一律寫「可能是任務還沒
拆成步驟」，而對正本那兩件任務那句是假的）。ALL_VERIFIED 講收尾、
NO_STEPS 講去拆、混合的逐件列出來不給總結、認不得的 kind 原樣帶出來
不編解釋（§8.3）。

二，`_blockers_field(work)` 講清楚這一欄跟 `.forseti/BLOCKERS.md`
**不是同一件事**：這一欄是帳本裡被標成 blocked 的步驟，BLOCKERS.md 那幾條
在 `known_limits`。不講的話這一欄的空值會跟 NEXT.md 上「擋住的」那一節
讀起來打架，那裡列著 9 條而這裡是空的。

三，`_recovery_status(snap)` 說得出 0 個 checkpoint 要怎麼樣才會有值，
而且標明 **0 個不等於沒有備份**。

四，`_last_good_pointer(snap)` **借 `checkpoint.py:121` 已經算好的
`why_no_last_good`**，不在這裡再寫一份 —— 複製一份的話，哪天那邊改了
政策兩句話會不一樣而且沒有人會發現。另外分出一種：一個 checkpoint 都
沒有的時候，那句「沒有人標成 last_good」技術上對但指錯方向，
下一步是**先落一個**不是去標記。

## 順帶清掉兩個變成孤兒的變數

`collect()` 裡的 `nexts` 與 `cps` 在接線之後只剩定義沒有讀取。

## 驗證

- `python3 -m pytest tests/ -q`：**1119 passed**（上一輪 1107，+12）。
- 反向驗證 **10 次，10 次全部抓到**。每一次改壞 → 跑測試 → 還原，
  還原後 `contract.py` sha256 逐字元一致（`5e435897e8ba3678`）。
  改壞的方向包含：四欄各自退回原本沒有理由的空值、把兩種 kind 講成
  同一句、混合原因挑一個講、理由不提 BLOCKERS.md 的區別、
  不借 checkpoint 那句自己寫一份、0 個的時候也叫人去標記、
  沒有任務跟派不動用同一句話。
- `.forseti/NEXT.md` 用真正的那條路徑（`desktop_api.strands()`）重新產生，
  不是手寫。四行現在都帶著理由，實際看過輸出。
- `sot.verify_bindings()`：stale 0、drifted 0。
  contract.py 加了約 140 行，7 條行號綁定漂掉，照上一輪的做法更新到
  正確位置（DRIFTED 不擋，但指不準的行號會讓下一個人翻到不相干的程式碼）。
- 交接契約覆蓋率 **PRESENT 仍然是 12/31，沒有變** —— 那四欄的值仍然
  不存在，改的是「為什麼沒有」這句話的準確度，不是覆蓋率。
  EMPTY 仍然 5 個，NO_SOURCE 仍然 12 個。

## 沒有動畫面，所以沒有重建部署

`desktop/ui/app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`，
跟 NEXT.md 記的完全一致，一個字都沒動。
`main.rs:70` 直接跑 repo 裡的 `desktop_api.py`，所以後端改動立即生效。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪沒有呼叫 `deploy.sh`，
沒有 `open` 也沒有 `pkill` 任何東西。

## 還缺什麼

- 其餘 12 條 NO_SOURCE 裡有 10 條的理由是語意判斷（「這個專案不是訓練
  任務」），**沒有查法可掛也不該硬編一個** —— 硬編出來的查法會變成
  一條永遠綠的守備。這件事上一輪就寫下來了，這一輪沒有改變它。
- **五種狀態現在每一種都說得出理由了**，所以「理由」這條線到此為止。
  下一項不在這條線上，ROADMAP 的 P0 第 1 項（真的救回一次）仍然
  卡在 owner 要按的那一步。
- 污染登記簿四筆仍然全部 OPEN。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  **這一輪沒有替她決定任何一件。**

沒有 commit。

---

# 2026-09-16 23:4x　展開區九格的接線，刪掉一行不再是全綠

## 挑了什麼，為什麼是這一項

上一輪自己寫的「還缺什麼」說理由那條線到此為止，下一項不在那條線上。
ROADMAP 第 9 項（Probe Packs）留了一句沒收的遺留：
「`renderIdentity` 與 `renderWorkflow` 那兩組有同一個弱點，這一輪沒有
一起改」。先去查那句還成不成立，查出來的東西比那句記載嚴重。

那兩組其實 22:4x 已經改嚴了。真正沒有人守的是展開區另外四格：
`renderDims`、`renderHealthCurve`、`renderBlast`、`renderGate`。
`grep` 過整個 `tests/`，這四個名字除了 `test_js_symbols.py` 之外
一條接線斷言都沒有。把輪詢那一段裡任何一行整行刪掉，1119 條測試全綠，
而畫面上那一格打開之後就凍住不再更新。

這一項符合排程檔那條硬規則：測試要能抓到問題，不是永遠回 OK。

## 做了什麼

`tests/test_ui_contract.py` 的 `RenderersAreActuallyCalled` 整個重寫。
判準從「這個名字全檔出現幾次」換成「這個名字有沒有出現在該出現的那一段」。

四個區間各自抽出來：輪詢那一段（`.dims.open` 那個 if）、展開按鈕那一段
（`vWhy` 的 click）、主輪詢那一段（`setAdvice(d)` 到那個 if 之間）、
溫度卡開合那一段（`togglePanel`）。

九格的清單寫死在測試檔裡，不從程式碼推導。從程式碼推導的話，
刪掉一行的同時清單也跟著縮小，那條檢查會永遠綠。
另外兩條反向守備比對區段裡實際出現的名字集合跟清單相不相等，
所以新增一格忘了加進清單也會紅。

`renderRescue` 沒有被要求出現在溫度卡那一段，因為它實際上只走主輪詢
一條路。照實際程式碼寫，不補一個它沒有的要求。

還有一條 meta 測試確認四個區間真的抓得到東西，不然上面那幾條會安靜
地跳過。

## 舊判準守不住這件事是實測的，不是推論

拿掉輪詢那一條之後，全檔出現次數：`renderDims` 2 次、`renderGate` 2 次、
`renderVitals` 2 次、`renderCards` 3 次，舊版的「至少兩次」四個全部
不會紅。只有一條路徑的 `renderSubs`（剩 1 次）與 `renderRescue`（剩 1 次）
舊判準抓得到。所以舊版不是全盤失效，漏掉的是「有備援路徑所以看起來
還在」那一類，而那一類佔多數。這兩句話都寫進了測試的 docstring。

## 驗證

- `python3 -m pytest tests/ -q`：1119 → 1126 passed（舊的 1 條被 8 條取代）。
- 反向驗證 7 次，7 次全部抓到。每一次改壞 `app.js`、跑測試、還原，
  還原後 sha256 逐字元一致（`25dd7d835ff5cea6`）。改壞的方向：
  輪詢段刪 `renderDims`、輪詢段刪 `renderGate`、展開段刪
  `renderHealthCurve`、展開段刪 `renderBlast`、主輪詢刪 `renderRescue`、
  溫度卡刪 `renderCards`、輪詢段多一格不在清單裡。
  每一次紅的是哪幾條測試都有記錄，前六次由指名該路徑的那條抓到，
  第七次由集合相等那條抓到。
- `sot.verify_bindings()`：stale 0、drifted 0。
- `.forseti/NEXT.md` 用真正的那條路徑重新產生（`desktop_api.strands()`，
  2.7 秒），不是手寫。

## 沒有動畫面，所以沒有重建部署

只動了 `tests/test_ui_contract.py` 一個檔。
`desktop/ui/app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`，
跟上一輪記的完全一致，一個字都沒動。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪沒有呼叫 `deploy.sh`，
沒有 `open` 也沒有 `pkill` 任何東西。

## 還缺什麼

- 這一輪守的是「有沒有人叫它」，守不到「叫了之後畫出來的東西對不對」。
  那要瀏覽器 harness，不是靜態比對。
- 展開區以外還有幾個渲染函式沒有接線斷言（`renderTree`、`renderNotes`、
  `renderList`、`renderPicker`、`renderBlastHits` 以外的分頁渲染），
  它們走的是 `view === "..."` 那條分派，區間長得不一樣，這一輪沒有碰。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP 的 P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 00:0x　分頁分派那七格，刪掉一行不再是全綠

## 為什麼挑這一項

上一輪自己在「還缺什麼」留下第二條：「展開區以外還有幾個渲染函式
沒有接線斷言，它們走的是 `view === "..."` 那條分派，區間長得不一樣，
這一輪沒有碰」。先查那句成不成立，成立，而且範圍比記載乾淨：
七個分頁渲染函式在整套 `tests/` 裡一條接線斷言都沒有。

ROADMAP 的 P0 兩項都卡在 owner（真的救回一次要她按，
sufficiency 的強制時機要 F04/F05 才判斷得了），P3 等條件成熟，
所以這一輪不在那兩條線上。

## 沒有人守這件事是實測的

`else if (view === "work") renderWork();` 整行刪掉，
`python3 -m pytest tests/ -q` 1126 條全綠。

症狀：「在做什麼」那一頁切進去看得到內容（`syncView` 畫過一次），
之後永遠不再更新，沒有任何錯誤訊息。畫面上跟「這一頁沒有新資料」
長得一模一樣。

`test_js_symbols.py` 守不到，它守的是反方向（被呼叫但沒定義）。
刪掉呼叫之後函式還在，那條不會紅。

## 做了什麼

`tests/test_ui_contract.py` 新增 `ViewRenderersAreActuallyCalled`，11 條。

兩個區間各自抽出來：輪詢尾段那條分派、`syncView` 整段。兩條路徑
各自會壞而症狀不一樣，所以分開釘。七頁的清單寫死在測試檔裡，
不從程式碼推導。

多守了展開區那一組沒有的三件：

- `syncView` 裡那五個快取的清除。少一行的症狀是那一頁永遠停在第一次
  切進來的資料，而舊資料跟剛抓的長得一模一樣。另一條確認那五個變數
  真的有宣告、而且真的被 `if (!xCache)` 拿來擋
- 兩條分派認得的 `view` 值必須一樣。一邊多認一頁，那一頁在另一條
  路徑上會掉進 else，畫出來的是別頁的內容，兩邊都是合法的 JS
- JS 的分派要跟 `index.html` 那排 `data-view` 按鈕對得起來

## 第一版的錯誤訊息指錯方向，當場改掉

左界原本綁死 `if (view === "tree") renderTree();` 那一行，
於是刪掉那一行的時候報的是「找不到輪詢分派那一段，這條檢查等於
沒跑」——那句話把人指向測試的區間抓法，而真正發生的事是那一頁
不再更新。改成從 `.dims` 區塊收尾往下吃連續的 if/else 行，
現在同一個改動報的是「輪詢分派沒有叫 renderTree，那一頁切進去之後
不再更新」。跟 5c 那條「一個錯的行號比沒有行號糟」同一條理由。

## 驗證

- `python3 -m pytest tests/ -q`：1126 → 1137 passed。
- 反向驗證 9 次，9 次全部抓到：輪詢分派刪 renderWork、刪 renderSpec、
  刪 renderTree，`syncView` 刪 renderMachine、刪 renderTree、
  刪 featCache 清除、把一個 view 值改掉，輪詢分派多一頁不在清單，
  HTML 少一個分頁按鈕。每一次改壞、跑測試、還原，還原後
  `desktop/ui/app.js` `25dd7d835ff5cea6`、
  `desktop/ui/index.html` `dbc4c6fa010e7d0f` 逐字元一致。
- `sot.verify_bindings()`：stale 0、drifted 0。
- `.forseti/NEXT.md` 用真正的那條路徑重新產生（`desktop_api.strands()`）。

## 沒有動畫面，所以沒有重建部署

只動 `tests/test_ui_contract.py` 一個檔。`app.js` `25dd7d835ff5cea6`、
`app.css` `66ae8cf855a8f6f5`、`index.html` `dbc4c6fa010e7d0f`，一個字沒動。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪沒有呼叫 `deploy.sh`，
沒有 `open` 也沒有 `pkill` 任何東西。

## 還缺什麼

- 這一輪守的仍然是「有沒有人叫它」，守不到「叫了之後畫出來的東西
  對不對」。那要瀏覽器 harness，不是靜態比對。
- `renderNotes`、`renderPicker`、`renderBlastHits`、`renderTakeoverGate`
  這幾支走的是各自頁面內部的呼叫，不在這兩條分派上，這一輪沒有碰。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP 的 P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 00:2x　抽屜與面板那四支，刪掉呼叫不再是全綠

## 為什麼挑這一項

上一輪自己在「還缺什麼」留下第二條：「`renderNotes`、`renderPicker`、
`renderBlastHits`、`renderTakeoverGate` 這幾支走的是各自頁面內部的呼叫，
不在這兩條分派上，這一輪沒有碰」。先查那句成不成立，成立。

路上先撿到另一句遺留：ROADMAP `:1033` 寫著「`renderIdentity` 與
`renderWorkflow` 那兩組有同一個弱點，這一輪沒有一起改」。去查，已經補掉了：
`tests/test_ui_contract.py:653` 與 `:731` 兩組都分開釘住輪詢那一段與
展開按鈕那一段，第 821 行還留著當初的註記。

**這一條不算我發現的。** 同一份 ROADMAP 的 `:1149` 已經寫了這條更正
（「那兩組其實在 22:4x 已經改嚴了」），是我先讀到 `:1033` 才去查的。
查的結果跟那條更正一致，沒有推翻它。記在這裡只是因為順序上先撞到舊的那句。

P0 兩項仍然卡在 owner（真的救回一次要她按 `dry_run=False`，
sufficiency 的強制時機要 F04/F05 才判斷得了），P3 等條件成熟，
所以這一輪不在那兩條線上。

## 沒有人守這件事是實測的

整行刪掉，`python3 -m pytest tests/ -q` 1137 條全部綠，一條都沒紅：

- `desktop/ui/app.js:1875`　`renderNotes(s);`
- `desktop/ui/app.js:2942`　`renderPicker();`
- `desktop/ui/app.js:2948`　`$("pickQuery").addEventListener("input", renderPicker);`
- `desktop/ui/app.js:2451`　`await renderTakeoverGate(lane);`

`renderBlastHits` 那兩條（`:513`、`:528`）刪掉會紅，既有那條
「全檔出現三次」數得到。缺的不是有沒有人守，是**它紅了之後
講不出是哪一條壞掉**，而兩條的症狀差很多。

`test_js_symbols.py` 守不到這一類，它守的是反方向（被呼叫但沒定義）。
刪掉呼叫之後函式還在，那條不會紅。上一輪那組
`ViewRenderersAreActuallyCalled` 也碰不到，那組抓的是
`view === "..."` 那條分派的區間，這四支在各自頁面內部。

## 四個症狀都是「畫面看起來正常，只是少了東西」

- `renderNotes`：換一輪之後粉紅點清單還停在上一輪，上一次沒送出的
  草稿也還在輸入框裡。看到的是 A 輪的注記，按下去寫進的是 B 輪
  （`saveNote` 用的是已經更新過的 `nodeN`，`app.js:1908`）
- `renderPicker`：側邊那份 session 清單永遠停在「讀取中」
  （`openPicker` 自己寫進去的，`app.js:2932`）
- `pickQuery` 那條：搜尋框打字完全沒反應
- `renderTakeoverGate`：接管閘門整塊不出現。那一塊寫的是「沒考過
  就是唯讀」，少了它，畫面上跟「這裡沒有限制」長得一模一樣。
  **方向是看起來比實際好**，跟 probe 那一格同一類

## 做了什麼

`tests/test_ui_contract.py` 新增 `SheetRenderersAreActuallyCalled`，6 條。

每一條的錯誤訊息講的是症狀，不是測試的區間抓法（5c 與上一輪那條
「一個錯的行號比沒有行號糟」同一個理由）。

多守了一件上一組沒有的：`renderNotes` 清不清掉上一輪的草稿與上一次
的結果字樣。那跟「有沒有人叫它」是同一個症狀鏈的兩半，會各自被改掉，
所以分開釘。

還守了自己的錯誤訊息會不會腐爛：「永遠停在讀取中」這句症狀成立的前提，
是 `openPicker` 自己先寫了那四個字。哪天那句話改掉，這條測試會紅，
提醒的是「錯誤訊息要跟著改」，不是程式壞了。

## 驗證

- `python3 -m pytest tests/ -q`：1137 → 1143 passed。
- 反向驗證 9 次，9 次全部抓到，而且每一次都只紅一條（沒有連坐誤紅，
  代表六條斷言各自獨立）：刪 `renderNotes(s)`、刪 `noteText` 清空、
  刪 `out.textContent` 清空、刪 `renderPicker()`、刪 `pickQuery` 那條
  listener、刪 `renderTakeoverGate(lane)`、刪 blast 輸入事件那條、
  刪 blast 重畫那條、把「讀取中」改成「載入中」。
  blast 兩條紅的是不同斷言、訊息不同：一條是「搜尋框打字沒反應」，
  另一條是「每次重畫之後搜尋結果整塊消失，而輸入框裡的字還在」。
- 每一次改壞、跑測試、還原，還原後 `desktop/ui/app.js`
  `25dd7d835ff5cea6` 逐字元一致。
- `sot.verify_bindings()`：rows 7、stale 0、drifted 0。
- `.forseti/NEXT.md` 用真正的那條路徑重新產生（`desktop_api.strands()`，
  2.2 秒），不是手寫。

## 沒有動畫面，所以沒有重建部署

只動 `tests/test_ui_contract.py` 一個檔。`app.js` `25dd7d835ff5cea6`、
`app.css` `66ae8cf855a8f6f5`、`index.html` `dbc4c6fa010e7d0f`，
跟上一輪記的完全一致，一個字沒動。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪沒有呼叫 `deploy.sh`，
沒有 `open` 也沒有 `pkill` 任何東西。

## 還缺什麼

- 守的仍然是「有沒有人叫它」，守不到「叫了之後畫出來的東西對不對」。
  那要瀏覽器 harness（`tools/ui-harness.py` 已經在，probe 那一格用過），
  不是靜態比對。**這是接下來這條線上唯一還沒走的方向**，
  因為靜態接線這一層，分頁七支與面板四支都補完了。
- ROADMAP 是追加式的，同一件事的舊記載留在 `:1033`、更正在 `:1149`，
  中間隔了一百多行。從上往下讀會先撞到舊的那一句，而那一句自己不說
  「後面有更正」。這一輪因此多花了一趟查證。沒有人在守這一類鮮度，
  過期的狀態檔正是 09-16 害人重做的東西。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP 的 P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 00:2x-00:5x　畫出來的東西對不對，開始有人守

## 挑了什麼

上一輪自己寫下來的那句遺留：「守的仍然是『有沒有人叫它』，守不到
『叫了之後畫出來的東西對不對』。那要瀏覽器 harness，不是靜態比對。
**這是接下來這條線上唯一還沒走的方向**」。這一輪走那一條。

先確認沒有重複實作：`tools/ui-render-check.py` 與 `tests/test_ui_render.py`
兩個檔都不存在，全 repo 沒有任何地方用過 `--dump-dom`，
`grep -rln "puppeteer|playwright|jsdom|remote-debugging-port"` 零命中。

## 為什麼沒有加相依套件

ADR-009 明寫 Python 主線零依賴。jsdom / playwright 那條路要加套件，
那是規格層的決定，不自己做。改用 headless Chrome 的
`--dump-dom`：只有 subprocess 加標準庫，一個套件都沒裝。

## 做了什麼

`tools/ui-render-check.py`，8 組檢查。`build()` 直接用
`tools/ui-harness.py` 已經有的那一支，**不重寫第二份** ——
重寫會多出第二個「fixture 該長什麼樣」的定義，兩份一定會分岔。

| 檢查 | 症狀 |
|---|---|
| `check_no_fatal_banner` | 渲染迴圈中途炸掉，被 catch 接走變成一張卡 |
| `check_no_console_errors` | 那個 try 以外的 Uncaught，以及留在成品裡的 console 輸出 |
| `check_no_placeholder_left` | 佔位字（溫度 `--`、`讀取中`）渲染完還在 |
| `check_temperature` | 溫度、證據覆蓋率跟資料對不上 |
| `check_progress_三軸` | 活動／寫入／目標三個數字跟資料對不上 |
| `check_tree_drew_nodes` | 資料裡有輪次，軌道上一個點都沒有 |
| `check_footer_counts` | 頁腳「N 線 · M 點」跟資料對不上 |
| `check_rescue_never_guesses` | 退不回去卻給了一個輪號 |

判準不是「畫面上有沒有東西」，是「畫面上那個值等不等於 fixture 裡那個值」。
這一步才是這一組跟靜態接線測試的差別：接線對了、函式跑了，
可是拿到別的物件、畫出一個看起來很合理但跟資料無關的數字 ——
那一類先前一條都沒有人守。

## 中途發現一件會讓這組測試說謊的事，當場補掉

一開始只寫了 `check_no_console_errors`，以為「JS 炸了會進 console」。
**實測不是。** 在 `renderTree` 裡丟一個 `ReferenceError`，
console 一行都沒有 —— 因為 `app.js:3024` 那個 `catch` 把整個
`tick()` 包起來，例外走 `fatal()`（`app.js:2962`）變成畫面上一張卡。

少了這一條的話，一次渲染迴圈崩潰只會報出「頁腳數字對不上」，
而真正原因是整段沒跑完。報出來的症狀跟真正的原因差一層，
查的人會往錯的方向走。所以加了 `check_no_fatal_banner`，
而且排在 console 那一條前面。

`check_no_console_errors` 的宣稱範圍也跟著改寫成它真正看得到的：
那個 try 以外的例外。Chrome 的 `INFO:CONSOLE` 不分 log 與 error，
所以也不假裝分得出來，帶 `Uncaught` 的跟其餘的分兩種症狀報。

## 驗證

`python3 -m pytest tests/ -q`：**1143 → 1158 passed**，全綠。
新的那一組單獨跑 14.9 秒（整組共用一次瀏覽器啟動）。

**反向驗證 13 次，13 次全部抓到**，每一次改壞、跑、還原：

溫度畫錯數字、覆蓋率那段拿掉、活動數字寫死、寫入數字寫死、
溫度永遠不填、退不回去卻給輪號、退不回去也不講缺什麼、
樹一個點都不畫、頁腳線數寫死、頁腳點數寫死、
渲染迴圈內丟例外、頂層丟例外、成品留 `console.log`。

每一條紅的訊息都指到對的那一格：「渲染迴圈內丟例外」報的第一條是
fatal 卡，「頂層丟例外」報的第一條是 console，兩者不混。
`console.log` 那次只紅一條而且訊息是「成品裡留著 console 輸出」，
不是「炸了」—— 兩種症狀沒有被合成一種。

**乾淨的那一次 0 條**，沒有誤報。

13 次全部還原後 `desktop/ui/app.js` `25dd7d835ff5cea6` 逐字元一致。

另外驗了兩件不靠瀏覽器的：

- **沒有 Chrome 的時候是 skip 不是 pass。** 清空候選清單跑整組：
  `Ran 15, skipped 9, failures 0`，skip 理由印的是「驗不了，不是通過」。
  另外 6 條用合成 DOM，沒有 Chrome 照樣跑。
- **這組測試自己不會在最該紅的那天全綠。** `_tag_text` 找不到元素回
  `None`，而好幾條檢查遇到 `None` 是放行的，所以多釘一條
  `test_確實讀到了東西而不是一片空白`。實跑確認四個格子都讀到值：
  `vTemp='36.9'`、`vBand='安靜 證據 92%'`、
  `vProg='已驗證進度 活動 120 寫入 70 目標 未知'`、`stat='1 線 · 120 點'`，
  對應 fixture 的 `temp.c=36.9`、`coverage=0.92`、
  `progress.activity=120`、`task=70`、`strands=1`、`total_dots=120`。

`sot.verify_bindings()`：`ok True`、stale 0、drifted 0。

## 這一輪自己犯的一個錯，已經修好，寫在這裡因為機制還在

重新產生 `.forseti/NEXT.md` 時，我直接呼叫
`handoff.write(D.strands(''), force=True)`。那是錯的：
`strands()` 的**回傳值**跟 `_write_handoff` 內部用的 `snap`
不是同一個形狀。結果寫出一份 1309 位元組的殘缺交接檔 ——
北極星變成「還沒設」，blockers、污染登記簿、交接契約整段消失。

從位元組數當場看出不對（原本 9 千多），刪掉重跑
`D.strands('')`，讓它走 `desktop_api.py:3418` 那條真正的路徑
自己寫。現在 9732 位元組、12 個小節、北極星回來了。

**機制沒有修掉：`handoff.write()` 收任何 dict 都寫得出檔案，
欄位缺光了也不報錯，只是安靜地寫出一份看起來正常的殘缺交接檔。**
方向是看起來比實際好，而它動到的正是停機之後接手的人唯一看得到的檔案。
這一輪沒有動 `handoff.py`：它在 `strands()` 的主路徑上，改壞了
下一個 session 會完全沒有狀態檔，代價比留著這個洞高。
留給下一輪，重現方式與判準寫在下面。

## 沒有動畫面，所以沒有重建、沒有部署

只新增 `tools/ui-render-check.py` 與 `tests/test_ui_render.py` 兩個檔。
`app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`、
`index.html` `dbc4c6fa010e7d0f`，跟上一輪記的完全一致，一個字沒動。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。這一輪沒有呼叫 `deploy.sh`，
沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
反向驗證全部在 headless Chrome 裡跑，那是獨立行程，
跟她桌面上那個 `.app` 無關。

## 順帶查出來的一個既有問題，沒有修

`app.js:291` 的 `renderVitals` 把「目標 <span class="unk">未知</span>」
**寫死在字串裡**，從來沒有讀過 `progress.goal`。
今天 `progress.goal` 永遠是 `null`，所以畫面跟資料剛好一致 ——
**那是巧合不是機制。** 哪天後端算得出目標進度，畫面會繼續說未知。

沒有改它：`progress.goal` 要有值得先有 owner 的驗收條件，
那件事本身在等她（`goal_note` 自己寫著）。現在去接一個永遠是 null
的欄位，畫面不會有任何變化，那正是「硬接輔助函式」。
改成用合成 fixture 把這件事釘住：
`test_後端算得出目標進度而畫面寫死未知會紅`，今天綠，
後端一有值就紅，錯誤訊息直接講 `renderVitals` 沒讀過那個欄位。

## 還缺什麼

- **這組測試的三個盲點，寫在工具檔頭，不是待補是限制：**
  Tauri 是 stub（連不連得上後端看不到，那是 `TauriWiring` 的事）、
  只看得到預設那一頁（Blast／Probe／Workflow／Identity 那幾頁要點擊才渲染，
  `--dump-dom` 碰不到，它們仍然只有靜態接線在守）、
  看的是 DOM 不是像素（CSS 蓋掉或推出畫面，DOM 裡照樣有字）。
  第二個是這條線上接下來唯一還有內容的方向。
- `handoff.write()` 沒有守自己的輸入（上面那一節，重現方式在 ROADMAP）。
- 這一組沒有進 `desktop/deploy.sh` 的守門。守門加一個要開瀏覽器的相依，
  是部署策略的改動不是實作規格，跟 B-15 同一類，要 owner 決定。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 01:0x　自動接續

## 挑了什麼

`.forseti/ROADMAP.md`「5m 附帶：下一輪的兩件」的第一件：
`handoff.write()` 不守自己的輸入。挑它的理由是那一節自己寫著
前提條件（「動它之前要先有一條測試釘住正常那條路仍然寫得出完整的檔」），
也就是做法已經定死了，不需要 owner 再決定任何事。

第二件（`renderVitals` 目標那格寫死）沒有挑，理由跟上一輪一樣：
`progress.goal` 要有值得先有 owner 的驗收條件，現在接畫面不會有變化。

## 先重現，才動手

    python3 -c "import sys;sys.path.insert(0,'apps/forseti-cli');
    import desktop_api as D, handoff; handoff.write(D.strands(''), force=True)"

實測回 `{'ok': True, 'bytes': 1309}`。同一次印出兩種形狀的鍵：
`strands()` 的快照有 58 個鍵，交接狀態要的 15 個**一個都不在**。
這不是「少了幾欄」，是兩種完全不同的東西，而 `render()` 裡
每一節都是「沒有就不印」，所以缺光了也長得像一份正常的檔。

## 做完什麼

`apps/forseti-cli/handoff.py`：`REQUIRED_KEYS`（15 個，就是
`_write_handoff()` 傳過來的那些）、`missing_keys()`、`write()` 的守門。

三個設計決定，每一個都有一條測試釘住：

**一，看鍵在不在，不是看值空不空。** `"blocker_lines": []` 是
「算過了，這一刻沒有」，整個鍵不存在是「根本沒有人算」。
守成後者，一個真的沒有阻塞的乾淨狀態會被自己擋下來
（`test_值是空的不算缺`，反向驗證 3 抓到）。

**二，`force` 蓋不過形狀檢查。** 事故那一行帶的正是 `force=True`。
`force` 的意思是「蓋過時間間隔」，不是「我確定這是對的」。

**三，擋掉的時候原本那個檔留在原地，而且往 stderr 印一行。**
一份舊的完整交接比一份新的殘缺交接有用 —— 前者的 mtime 自己會講
「這是舊的」。拒絕也不准安靜，不然只是把一種沉默換成另一種。

## 這道守門自己最危險的失敗方式，有兩條測試守

它把真正的交接也擋掉，然後什麼都不寫。哪天有人往 `REQUIRED_KEYS`
加一欄而沒往 `_write_handoff()` 加，畫面不會壞、別的測試不會紅，
只有 `.forseti/NEXT.md` 從此停止更新 —— 而那件事要到下一次停機
才有人發現，正是 `handoff.py` 檔頭寫的那 16 小時空白換個原因再來一次。

`test_必要欄位每一個上游都真的有供` 用 spy 走真的那條路比對兩邊欄位。
`test_真正的那條路仍然寫得出完整的檔` 讓 `strands()` 自己寫一份出來，
驗「北極星還沒設」不在、「第 ? 輪」不在、位元組數過 3000
（事故那份 1309，正常九千上下，3000 是分得開兩者的地板）。
反向驗證 2 實測：加一個上游沒供的欄位，這兩條一起紅。

## 中途踩到一個會讓測試說謊的東西

一開始寫成「先算 `snap`，再單獨呼 `_write_handoff(snap)`」，
結果回 `None`，看起來像守門擋錯了。實情相反：**`strands()` 內部
自己就會呼叫 `_write_handoff`**（`desktop_api.py:3418`），
所以第一次已經寫過了，第二次被最小間隔擋掉。

改成把 `handoff.OUT` 指到暫存檔然後呼叫 `strands()`。
這樣測的才是這個檔平常真的被寫出來的那條路，不是另外拼一條。
順帶讓這兩條測試不再動到真的那份 `.forseti/NEXT.md`。

## 驗證

`python3 -m pytest tests/ -q` → **1166 passed**（1158 → 1166，新增 8 條）。

反向驗證四次，每次改一處再跑整組，改完還原並 `diff` 確認一致：

| 改了什麼 | 誰紅 |
|---|---|
| 把守門整個拿掉 | 5 條 |
| `REQUIRED_KEYS` 加一個上游沒供的欄位 | 2 條（正是最危險那個方向） |
| 改成看值空不空 | 6 條 |
| 先寫檔再檢查 | 3 條 |

端到端實測：事故那一行現在回 `ok: False` 加 15 個欄位名加
一行 stderr；真的那份 `NEXT.md` 仍然 9730 位元組、12 個小節、
北極星在、輪號在。

## 沒有動畫面，所以沒有重建、沒有部署

`app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`、
`index.html` `dbc4c6fa010e7d0f`，跟上一輪記的完全一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`、沒有呼叫 `deploy.sh`。

## 還缺什麼

- `renderVitals` 目標那格寫死（5m 附帶第二件），仍然在等
  owner 的驗收條件，這一輪沒有動。
- Blast／Probe／Workflow／Identity 那幾頁要點擊才渲染，
  `--dump-dom` 碰不到，仍然只有靜態接線在守。ROADMAP 寫著
  「要先想清楚怎麼點才不算換了一條測試路徑再動手」，
  這一輪沒有替它決定。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

## 2026-09-17 01:1x　自動接續

**挑了什麼：** ROADMAP 5m 附帶那一句「這條線接下來唯一還有內容的
方向」—— 點開才渲染的那四頁（Blast、Identity、Workflow、Probe）
`--dump-dom` 碰不到，仍然只有靜態接線在守。

那一句附帶一個條件：**「要先想清楚怎麼點才不算是換了一條測試路徑
再動手」**。所以先回答那個問題，再動手。

## 想清楚的結果

**按真的那個元素，不要呼叫 render 函式。**

`tools/ui-render-check.py` 的 `render()` 多一個 `clicks=`，
往**暫存目錄那一份** index.html 尾巴加一段
`document.getElementById("vWhy").click()`。
`HTMLElement.click()` 派送的是真的、會冒泡的 MouseEvent，
走的是 `app.js:3057` 那個掛在 `#vWhy` 上的 listener，
接下來畫哪九格由 app.js 自己決定。

**這支沒有直接呼叫任何一支 render。** 直接呼叫驗到的是那個函式
會不會跑，不是那一下按了會發生什麼 —— 那正是 ROADMAP 當初
不動它的理由，不是我這一輪新想的。

`desktop/ui/index.html` 與 `tools/ui-harness.py` 一個字都沒動。
一個只有測試路徑才有的 `<script>` 留在正本裡，遲早會有人
以為那是產品的一部分。

## 跟真人按下去差在哪，先寫出來

`isTrusted` 是 false。`app.js` 一處都沒有讀它（grep 實測 0 筆），
所以這一刻沒有差別，但哪天有人讀了就有。
沒有 hover / focus-visible 這些只有真指標裝置才會有的狀態。
只按得到「按一下就展開」這種一步的東西。

底下七個分頁（tree / work / machine / …）**仍然沒有驗** ——
它們是 `.vw` 按鈕換 `view` 變數再重畫，跟展開那一格不同一條路。

## 新增三組檢查，其中一組存在的理由是守其餘兩組

`check_expanded_row_counts` 四格共用一張表（`EXPANDED_BOXES`），
不是四支各寫一遍 —— 四份一定會分岔，而分岔的那一份通常是
最少被看的那一份。

`check_blast_header_counts` 驗那一行的檔數與邊數。列數對不代表
數字對，而那一行是唯一一個會讓人以為「這張圖掃過全部」的數字。

`check_expanded_opened` 守的是上面兩條本身。它們遇到
「找不到那一塊」都是放行的（那個設計是對的，元素在不在歸
`test_ui_contract.py` 管），副作用是**那一下沒按到的時候兩條
會一起變綠，而畫面上什麼都沒展開**。

## 合成那一組抓到一個真的錯，而真實那一輪是全綠的

`EXPANDED_BOXES` 第四欄一開始把 blast 的資料鍵寫成 `rows`，
它真正的鍵是 `top`（`renderBlast` 讀的是 `b.top`）。
後果不是紅燈，**是那一格被安靜跳過，整組照樣全綠**。

修法不只是改那個字。現在遇到「`has` 是 true 但那一鍵不是清單」
直接報一條，指名是這支自己的表寫錯了 —— 不然下一個人加第五格
寫錯鍵的時候，會再一次得到一個全綠的假保證。

## 一個實測出來的盲點

這一組驗得到「按完之後那一格畫出來了而且數字對」，
**驗不到「是那一下按的造成的」**。

那四格有兩條路會畫它們：`#vWhy` 的 listener，與輪詢迴圈裡
`.dims.open` 那個分支（`app.js:3010`）。實測拿掉任何一條都還是綠的，
兩條都拿掉才紅。要分得開得量時間，而 `--dump-dom` 只照一張。

這一條寫進工具檔頭的盲點清單，不是只寫在這份紀錄裡。

## 驗證

`python3 -m pytest tests/ -q` → **1183 passed**（1166 → 1183，新增 17 條）。

`python3 tools/ui-render-check.py` → 回 0。
預設那一畫面 8 組全過，展開後 DOM 202889 位元組、console 0 行、5 組全過。

真實數字：blast 8 列（fixture `top` 8）、identity 5 列、workflow 2 列、
probe 10 列、檔數 239 邊數 353，全部跟 fixture 逐項一致。

反向驗證**改真的 `app.js` 七次**，五種紅、兩種綠（就是上面那個盲點）：

| 改了什麼 | 結果 |
|---|---|
| renderBlast 只畫前 3 行 | 紅：列數對不上 |
| renderBlast 讀錯鍵，資料在畫面走 fallback | 紅：資料算得出卻印「沒有資料」 |
| 檔數印成 `b.files + 1` | 紅：那一行的數字不是資料裡那個 |
| 整個展開 listener 拿掉 | 紅 5 條：沒打開加四格整塊不在 |
| renderProbe 少畫一列 | 紅：列數對不上 |
| 只拿掉 listener 裡的 renderBlast | 綠（輪詢那條路畫了） |
| 只拿掉輪詢那一行 | 綠（listener 那條路畫了） |

每一次改完還原並比對 sha256，`app.js` 全程回到 `25dd7d835ff5cea6`。

合成那一組另外釘住四件：`has` 是 false 時印「沒有資料」不准判紅、
數列數不准把 `blRowHead` 這種一起數進去、`_box_html` 要自己配對 div
不然每格永遠 0 列、沒按的時候那四格本來就不在（沒有這一條，
上面那幾條綠了也證明不了按下去有用）。

## 沒有動畫面，所以沒有重建、沒有部署

`app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`、
`index.html` `dbc4c6fa010e7d0f`，跟上一輪記的完全一致。

**沒有進 `deploy.sh` 的守門。** 守門加一個要開瀏覽器的相依，
是部署策略的改動不是實作規格，那要 owner 決定（B-15 同一類）。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`、沒有呼叫 `deploy.sh`。

## 還缺什麼

- 底下七個分頁仍然沒有渲染驗證。它們換的是 `view` 變數，
  要按兩個地方（先按漢堡再按分頁），跟這一輪那一下不同一條路。
  這是這條線接下來還有內容的方向，但**它的入口是漢堡選單，
  要先確認按得到**，不是照抄這一輪的做法。
- 「是誰畫的」分不開（上面那個盲點）。要分開得量時間。
- `renderVitals` 目標那格寫死（5m 附帶第二件），仍然在等
  owner 的驗收條件，這一輪沒有動。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 01:5x　底下那六個分頁開始有人守

## 挑了什麼，為什麼是這一項

`supervisor.py --status` 回「會不會喚醒 true」，沒有閘擋住。

上一輪（5o）收尾時自己寫下：「這條線接下來唯一還有內容的方向」
是那七個分頁，而且註明「入口是漢堡選單，要先確認按得到，
不是照抄這一輪的做法」。挑的就是這一項。

動手之前先確認它不存在：`grep -n "view\|tab\|vw" tools/ui-render-check.py`
只找到檔頭那句「仍然沒有驗」，沒有任何實作。

## 先確認的那件事，結果比預期重要

七顆 `.vw` 全部住在 `#picker` 裡（`index.html:106-119` 實測），
而 `#picker` 帶著 `hidden`，由 `#burgerBtn` 打開（`app.js:2946`）。
所以那句「入口是漢堡」是對的，一次要按兩下。

`clicks` 因此從「只認 id」改成「認 CSS 選擇器」——
那七顆一個 id 都沒有。`#vWhy` 那種寫法照樣成立。

## 中途踩到一個會讓整條路安靜失效的東西

注入的 JS 把選擇器直接拼進錯誤訊息的字串裡，而
`.vw[data-view="work"]` 本身含雙引號，字串提前關掉。
Chrome 回 `Uncaught SyntaxError: missing ) after argument list`，
**那一下完全沒按到，畫面停在預設分頁**。

抓到它的是 `check_no_console_errors`，不是人眼。
要不是那一條在，這一輪會拿著一張「沒切過去」的 DOM
去驗預設那一頁，而預設那一頁本來就是對的 —— 整組會全綠。
訊息現在也走 `json.dumps`。

## 六個分頁一張表，不是六支各寫一遍

`TABS` 每一列寫：這一頁叫什麼、驗哪幾格、期望值怎麼從 fixture 算。
六份一定會分岔，而分岔的那一份通常是最少被看的那一份
（跟 `EXPANDED_BOXES` 同一條理由）。

`tree` 不放進來。它是預設那一頁，`check_tree_drew_nodes` 已經驗過，
放進來等於同一件事驗兩次而多開一次瀏覽器十秒。

兩件事讓表不會誤判乾淨狀態：

一，表頭收一串候選 class 不是一個。`renderWork` 寫的是
`d.total ? "aBig" : "fBig"`（`app.js:2316`），`renderSpec` 同一招。
只認一個的話，一個真的沒有待辦的狀態會被判成「找不到表頭」。

二，每一條都先取 `#lane` 再往裡面找。`#picker` 裡那份 session 清單
有 81 個 `.pk*`，`.ct` 在 picker、machine、list 三處都有。
不縮範圍數出來的是整頁的量，而那個數字會在某些分頁上剛好對上 ——
一條有時候對的斷言比沒有斷言糟。必讀清單那一格再縮一層，
只數 lane 裡第一塊 `.fam`（那一頁有三塊，不縮是 74 而清單只有 30）。

## 實測出來的一件事，它自己就是一條新檢查存在的理由

`HTMLElement.click()` 對 `hidden` 底下的元素照樣派送事件。

實測兩次：不按漢堡直接按 `.vw` → 全綠；把 `openPicker` 換成
空函式再按兩下 → 還是全綠。

也就是說**分頁那六條證明不了漢堡是通的**，而漢堡是畫面上
唯一的入口。漢堡壞掉的那一天，那六條會一起說沒事，
使用者卻一頁都切不過去。

補這個洞的是 `check_burger_opens_picker`：單獨按一次漢堡，
看 `#picker` 的 `hidden` 掉了沒，順便看裡面七顆還在不在。
這一條不是為了對稱加的，是上面那兩次實測逼出來的。

## 驗證

`python3 -m pytest tests/ -q` → **1217 passed**（1183 → 1217，新增 34 條）。

`python3 tools/ui-render-check.py` → 回 0，八次瀏覽器：
預設 8 組、展開 5 組、漢堡、六個分頁。

真實數字逐項對過：work 2 列（tasks 2，表頭 2／進行中 0）、
feat 21 列（items 21，表頭 21/21）、spec 必讀清單 30 列（表頭 20 / 30）、
audit 13 張事故卡（表頭 13，帳本 310 筆、繼續 15 次）、
machine 7 列（host NorikadeMacBook-Pro.local、機型 Mac17,2）、
list 三格嚴重度各 0。全部 console 0 行。

反向驗證**改真的 `app.js` 八次，八次全紅**，每次還原並比對 sha256：

| 改了什麼 | 結果 |
|---|---|
| renderWork 少畫一列 | 紅：2 列 → 1 列 |
| work 表頭件數 +1 | 紅：那個數字不是資料裡那個 |
| renderFeat 只畫前 3 列 | 紅：21 列 → 3 列 |
| machine 主機名寫死 | 紅：那個字不是資料裡那個 |
| renderAudit 少畫一張 | 紅：13 列 → 12 列 |
| renderSpec 清單少一列 | 紅：30 列 → 29 列 |
| 分頁 listener 整個拿掉 | 紅 4 條：沒切過去加整頁的格子都不在 |
| 漢堡 listener 拿掉 | 紅：按了選單沒打開（分頁那六條全綠） |

`app.js` 全程回到 `25dd7d835ff5cea6`。

端到端也反驗過一次，不只是呼叫檢查函式：弄壞 `renderAudit` 之後
`pytest -k 自我審計` 真的紅，訊息是「13 列 vs 12 列」。

合成那一組另外釘住：fixture 少一把鑰匙要指名是**這支自己的表寫錯**
而不是安靜跳過（5o 那一輪就是安靜跳過害整組假綠的）、
停在佔位字要報成「還沒讀完就照相」而不是一堆「找不到表頭」、
有進行中的時候多那一張 `.wk` 不算多畫、三格嚴重度的數字要從
`strands.rows` 自己數而不是讀某個現成的總數欄位。

## 沒有動畫面，所以沒有重建、沒有部署

`app.js` `25dd7d835ff5cea6`、`app.css` `66ae8cf855a8f6f5`、
`index.html` `dbc4c6fa010e7d0f`，跟上一輪記的完全一致。

**沒有進 `deploy.sh` 的守門**，跟 5m、5o 同一條理由（B-15，
守門加一個要開瀏覽器的相依是部署策略的改動，要 owner 決定）。
而且這一組現在要開八次瀏覽器，一次七十幾秒。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`、沒有呼叫 `deploy.sh`。

## 還缺什麼

- 分頁裡面**第二層**沒有驗：`.fi` 展開、`.wk` 上那三顆動作鈕
  （收尾／派下一步／一路派到底）。那要按兩層以上，
  而且動作鈕會寫帳本，不是照一張就算數 —— 這一項要先想清楚
  「怎麼驗才不會真的去改正本」再動手，跟 5o 當初那句同一種性質。
- 「是誰畫的」仍然分不開（`syncView` 與輪詢兩條路），跟 5o 同一個盲點。
- `renderVitals` 目標那格寫死，仍然在等 owner 的驗收條件。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 02:2x　第二層那三顆動作鈕，而它們其實按不動

## 閘門

`supervisor.py --status` 回「會不會喚醒 true」，擋住的閘「（沒有）」，
今天喚醒 0 次，上限 40。所以這一輪該做事。

## 挑了什麼

ROADMAP 5p 收尾寫的那一項：分頁裡面第二層。它當時附帶一句
「要先想清楚怎麼驗才不會真的去改正本再動手」。

## 先更正上一輪留下的一句話

5p 寫的是「`.fi` 展開、`.wk` 上那三顆動作鈕」。**`.fi` 根本不會展開**：
`renderFeat` 產生的 `.fi` 在 `app.js` 裡一個 listener 都沒有，
`app.css` 只有 `.fi`、`.fi.dead`、`.fi.dead .fiTag` 三條，
沒有任何展開狀態。grep 實測，不是推論。
所以第二層真正存在的只有那三顆鈕，這一輪做的是那個。

## 想清楚的結果：只按第一下

`wireActs` 是兩段式的。第一下把鈕改成「再按一次確定」加 `armed`，
**一個指令都不發**；第二下才 `invoke("act")`。按第一下驗得到
那道閘還在，而整個過程碰不到帳本。

fixture 裡剛好沒有 `act` 這把鑰匙，所以按第二下也只會打到 stub。
**但這一組不靠那件事** —— 那是環境剛好擋住，不是自己的決定。
哪天有人往 fixture 補一個 `act`，這組就默默變成會執行。

## 抓到一個真的 bug：那三顆鈕在真的 App 裡按不動

第一次實跑，真實資料上是**紅的**：按了第一下，`class` 仍然是 `ac`，
沒有 `armed`。查下去不是測試寫錯。

`setInterval(tick, 2000)` 每兩秒重畫 work 那一頁，
`renderWork()` 第一行 `lane.textContent = ""` 整塊清掉重建，
新節點新 closure，`armed` 沒了。而確認窗是 5 秒。

同一份頁面按兩下，只改中間間隔，實測：

| 兩下間隔 | 指令清單 |
|---|---|
| 300 毫秒 | `[... "work", "act", "strands"]`　送得出去 |
| 2500 毫秒 | `[... "work", "strands", "strands"]`　**一個 act 都沒有** |

使用者只要沒在兩秒內按完兩下，第二下變成新的第一下，
永遠送不出去，而且沒有任何錯誤訊息。

## 修法

`workBusy()`，一行守門，只守輪詢那一條路。
`syncView()` 那一條不守 —— 換分頁是使用者自己的動作。

修好之後端到端再驗：間隔 2500 毫秒送得出 `act`，4000 毫秒也送得出。

## 新增的東西

- `_inject_invoke_spy()`：包住 harness 的假 `invoke`，記下發過哪些指令。
  **必須插在 `<script src="app.js">` 之前**，因為 `app.js:6` 在載入
  那一刻就把函式抓走了。插晚了會一筆都收不到，而那看起來跟
  「真的一筆都沒發」一模一樣。
- `_inject_spy_dump()`：照相前把清單寫進隱藏的 div，因為 `--dump-dom`
  讀不到 JS 變數。
- `ACT_BUDGET_MS = 7000`：照相時刻自己是一條斷言，要落在
  (按下 + 輪詢間隔, 按下 + 確認窗) = (5300, 8300)。
  預設的 8000 只比上界早 300 毫秒，太窄，而翻面的方向是**綠**。
- `check_act_arms_not_fires` 與 `check_act_did_not_invoke`。
  後者遇到「記錄整個是空的」報成驗不了，不報成通過。

## 中途自己造成的坑

寫 `workBusy()` 註解時把 `setInterval(tick, 2000)` 原樣抄進去，
測試裡抽輪詢間隔的正規表示式抓到的變成**註解裡那個**，
`re.search` 只回第一個，不會說還有第二個。
修法：`_one_int()` 改用 `findall`，不只一處回 None 讓測試紅；
註解改寫掉。

## 驗證

`python3 -m pytest tests/ -q` 　1217 → **1228 passed**，全綠。
`python3 tools/ui-render-check.py` 　回傳碼 **0**，
九次瀏覽器全部 console 0 行。

反向驗證改真的 `app.js` **七次，七次全紅**，每次還原並比對 sha256
（全程 `c0829f44069780b2`）：拿掉守門、守門只看 armed、守錯邊、
輪詢改 6 秒、抽取變得不唯一、拿掉第三顆鈕、改掉待確認的字。

另外單獨反驗檢查函式五次，五次全抓到。

## 動了畫面，所以重建並部署

`app.js` `25dd7d835ff5cea6` → `c0829f44069780b2`。
`app.css` `66ae8cf855a8f6f5`、`index.html` `dbc4c6fa010e7d0f` 沒動。
`tauri build --debug --bundles app` 建成，`deploy.sh` 守門測試通過，
**沒有開視窗**。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
`deploy.sh` 照原樣跑，它自己印「沒有開視窗」。

## 還缺什麼

- **第二下沒有驗**，而那一下才是真的會改帳本的那一下。
  要驗它得先有一條「不碰正本」的路（例如帳本的唯讀或暫存模式），
  那是另一件事，而且要 owner 決定要不要為了測試開那條路。
- `.acOut` 成功與失敗兩種樣子都沒有驗到，同一個理由。
- 仍然分不出那一格是誰畫的（`syncView` 與輪詢兩條路），
  跟 5o、5p 同一個盲點。
- `renderVitals` 目標那格寫死，仍然在等 owner 的驗收條件。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
  這一輪沒有替她決定任何一件。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 02:5x　自動接續

## 挑了什麼

ROADMAP 的「還缺什麼」裡，唯一不需要 owner 先決定的那一條：
**「仍然分不出那一格是誰畫的（`syncView` 與輪詢兩條路）」**。
5o、5p、5q 三輪都列著它，`ui-render-check.py` 收尾那句話也還寫著它。

其他還缺的幾件（第二下、`.acOut` 兩種樣子、`renderVitals` 目標那格、
B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症）
全部在等 owner，這一輪一件都沒有替她決定。

## 動手前先確認它不存在

`grep -rn "spy_at_ms\|POLL_CHECKS\|check_poll" tools/ tests/` 空的。
5q 做的 invoke 觀察器在，缺的只是「坐久一點再倒」。
所以是接在既有觀察器上，不是第二套。

## 做了什麼

`tools/ui-render-check.py`

- `render()` 多一個 `spy_at_ms`。不給的話行為跟以前一模一樣
  （跟著最後一下走），所以動作鈕那一組一個字都沒動。
- `_spy_cmds()`：把觀察器那一格讀成清單，讀不到／不是清單／是空的
  一律報成「驗不了」。空的那一條的訊息先前沒有「驗不了」三個字，
  是測試逼出來的，改的是訊息不是測試。
- `check_poll_loop_really_repeats`：坐過 10500 毫秒，`strands`
  至少發 3 次。門檻寫 3 不寫實測的 6，因為這條問的是「有沒有重跑」，
  不是「剛好幾次」。
- `check_poll_repaints_from_cache`：跨過至少三輪，`work` 只抓 1 次。
  兩個方向都會紅，0 次跟 2 次以上的症狀不一樣，訊息分開寫。
- `POLL_CHECKS` 接進 `main()`，多開一次瀏覽器（九次變十次）。
- 收尾那句話的範圍跟著改。它先前宣稱的盲點現在補掉一半，
  留著不改的話那句話會開始說謊。

`tests/test_ui_render.py`　14 條新測試，兩組。

一組開真的瀏覽器（`WhoPaintedThatCell`），一組餵合成資料
逼檢查函式自己紅（`PollChecksThemselvesCatchThings`）。
其中三條守的是**常數之間的關係**而不是行為：傾印時刻要跨過三輪、
門檻要落在「不會自動達成」與「不可能達成」中間、`POLL_CLICKS`
要真的是那一頁。輪詢間隔從 `app.js` 抽，不抄。

## 量到的東西

切到「在做什麼」之後坐著不動，指令依序是：

```
spec_reading, strands, strands, sessions, work,
strands, strands, strands, strands
```

`work` 一次。之後四輪 `renderWork()` 都跑了，
`if (!workCache)` 讓它從快取重畫，一次都沒回頭問後端。

另外四頁各自量一次：功能 1、這台機器 1、自我審計 1、
讀文件 2（其中一次是 `loadFoundation()` 載入時發的）。五頁同形狀。

**症狀：** 坐在那五頁上，帳本更新了畫面不會變，沒有錯誤訊息。

**沒有替她修。** 三種修法寫進 B-16，選哪一種是政策。
第二種要的「變了沒」訊號，`tick` 裡那個 `grew` 算的是逐字稿線數
不是帳本，硬接是 §8.3 的填空。順帶查到 `grew` 被算出來之後
從來沒被讀過（grep 實測，整份只出現一次），沒有動它也沒有刪它。

## 驗證

`python3 -m pytest tests/ -q` 　1228 → **1242 passed**，全綠。
`python3 tools/ui-render-check.py` 　回傳碼 **0**，
十次瀏覽器全部 console 0 行。

反向驗證改真的 `app.js` **三次，三次全紅**，每次還原並比對 sha256
（全程 `c0829f44069780b2`）：拿掉 `setInterval(tick, 2000)`、
輪詢也清 `workCache`、`renderWork` 拿掉快取守門。

反向驗證檢查函式自己 **六次，六次全抓到**：空清單改成放行、
門檻降到 1、重抓那條永遠回空、傾印時刻改早、按的頁面改掉、
`main()` 不跑這一組。每次還原後 `ui-render-check.py`
都回到 `91e63e0a84c108c1`。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個 hash 跟這一輪開始時一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
這一輪連 `deploy.sh` 都沒有跑，因為沒有動畫面。

## 還缺什麼

- **B-16 等 owner 決定**：那五頁的快取政策要哪一種。這是這一輪
  新增的唯一一條阻塞，而且它擋的是那五頁的即時性。
- 另外四頁的「誰畫的」只量過一次寫進 B-16，沒有進常態檢查
  （進去的話每次多開四次瀏覽器）。
- 第二下仍然沒有驗（那一下會寫帳本），`.acOut` 兩種樣子同理。
- 看的仍然是 DOM 不是像素。
- `renderVitals` 目標那格寫死，仍然在等 owner 的驗收條件。
- 污染登記簿四筆仍然全部 OPEN。交接契約 PRESENT 仍然 12/31。
- B-15、B-03/B-04 訊號打架、`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

## 收尾前自己抓到的一個數字錯誤

`main()` 最後那句「注意這句話的範圍」原本寫「另外六個分頁誰畫的
仍然分不出來」。實際是五個（`TABS` 共六個，這一輪補掉的是 work 那一個）。
一個自己描述自己範圍的句子寫錯數字，跟過期的狀態檔是同一類問題，
所以改成 `len(TABS) - 1` 算出來的，不再是抄的。
改完重跑 `ui-render-check.py`，回傳碼仍然 0。
`tools/ui-render-check.py` 最終 sha256 `9a8fddbcc622457b`。

【這一行差點是編的】上面那個 hash 我第一次寫的時候填了一個
沒有量過的值，量完才發現對不上，當場改掉。記在這裡不是自責，
是因為「順手把一個看起來像 hash 的東西填進去」正是這份紀錄
存在的理由 —— 它跟填空衝動（§8.3）是同一件事，而且填出來的東西沒有人會去查。

---

# 2026-09-17 03:1x　另外五頁誰畫的也有人守了，而且推翻了上一輪的結論

## 挑了什麼

`ROADMAP.md` 5r 收尾那一句：「另外四頁的『誰畫的』只量過一次
寫進 B-16，沒有進常態檢查（進去的話每次要多開四次瀏覽器）。」
那是成本，不是阻塞，所以動它。

動手前先確認不是重做：`grep -n "POLL_" tools/ui-render-check.py`
確認只有 work 那一條，`POLL_PAGES` 不存在。

## 做完什麼

`tools/ui-render-check.py` 加 `PAGE_CMDS`、`LIVE`、`POLL_MIN_LIVE`、
`POLL_PAGES`（五頁一張表）、`_tab_of()`、`check_poll_page_fetches()`，
`main()` 一頁開一次瀏覽器跑一圈。

`work` 刻意不進表，它由 `check_poll_repaints_from_cache` 守著。
同一件事守兩處的話，改了一處另一處還綠，那比沒守更糟。

每一頁對整份 `PAGE_CMDS` 斷言，沒列進 `expect` 的一律期望 0 次。
那一圈裡也跑 `check_tab_switched`：沒切過去的話，每一條
「那個指令 0 次」都會答對 —— 往綠的方向壞。

## 推翻了上一輪自己寫的結論

5r 與 B-16 都寫著「五頁全部是同一個形狀」。實測不是。

`renderSpec()` 裡 `block_reading`（`app.js:2458`）與
`renderTakeoverGate()` 的 `sufficiency`（`app.js:2497`）
沒有任何快取守門，每一輪重發（坐過 10500 毫秒各 5 次）。
那一頁上半快取、下半即時，一頁兩種行為。

會錯的機制：只數了每一頁「自己名字那個指令」，四個 1 加一個
解釋得通的 2 讓結論成立，於是序列裡每輪重複出現的另外兩個指令
從頭到尾沒有被數過。**相符的數字讓人停止看還有什麼沒被數到。**

登錄污染 `pol-ab22b7a565`，B-16 那張表換掉了，ROADMAP 那一句
劃掉並指向這一輪。**沒有只改數字** —— §40 開頭那句話說的是
機制不改掉會再犯一次，所以 `preventive_rule` 那一欄寫的是
「對整份清單斷言，缺席本身是斷言」。

## 順帶量到一件從來沒有人量過的事

「需要注意」那一頁一個專屬指令都不發（`app.js:3076` 的
`else renderList()` 沒有對應的 `invoke`），靠 `strands` 每輪重畫。
**它是六頁裡唯一真的即時的一頁。** 這一頁先前不在 B-16 的表上。

## 驗證

`python3 -m pytest tests/ -q` 　1242 → **1260 passed**，全綠。
`python3 tools/ui-render-check.py` 　回傳碼 **0**，
15 次瀏覽器（原 10 次），82 秒（原 55 秒），全部 console 0 行。

反向驗證改真的 `app.js` 四次，每次還原並比對 sha256
（全程 `c0829f44069780b2`）：

| 改了什麼 | 結果 |
|---|---|
| `renderFeat` 拿掉快取守門 | 紅：features 5 次 |
| `syncView` 的 feat 不清快取 | **綠**，見下面盲點 |
| `block_reading` 包進快取守門 | 紅 2 條 |
| 「需要注意」那一頁也去抓 machine | 紅：那一頁該是 0 次 |

反向驗證檢查函式自己四次：`expect` 的鍵拼錯（抓到）、
`POLL_MIN_LIVE` 降到 1（放行，證明那道門檻有效力）、
期望值寫錯成 2（抓到）、迴圈不跑（**補守門前放行**，補後抓到）。

## 反向驗證抓到兩個真的漏洞，都補了

一，迴圈不跑的話五頁**全綠** —— 回空跟通過在呼叫端分不出來。
補一條：一條都沒比對過報成驗不了。

二，`expect` 裡拼錯一個鍵會被**安靜跳過**（迴圈只走 `PAGE_CMDS`）。
補 stray 守門。這正是 5o 的 `EXPANDED_BOXES` 踩過的同一種。

## 一個實測出來的盲點，沒有掩飾

`syncView()` 裡那幾行 `xxxCache = null` 這一組**驗不到**。
那幾個快取變數初值就是 `null`（`app.js:2156` 等），首次切進去
必然抓一次，清不清都一樣。反向驗證把 `featCache = null` 拿掉，
這一組照樣全綠。要驗到得按三下（漢堡、A 頁、漢堡、B 頁、漢堡、
A 頁），那是另一種時序，沒有做。

寫進 `check_poll_page_fetches` 的說明與 B-16，不是只寫在這裡 ——
「這一組綠」不等於「那幾行有效」，兩者中間隔著這個盲點。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟開始時逐字元一致。`tools/ui-render-check.py` 最終
`36315275e94abc33`。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
這一輪連 `deploy.sh` 都沒有跑，因為沒有動畫面。

## 還缺什麼

- **B-16 仍然等 owner 決定**，而且這一輪讓它更難決定了一點：
  讀文件那一頁已經有一半是第一種修法（每輪重抓），
  「需要注意」那一頁本來就是即時的。三種修法是按頁選的。
- 第二次切入那條路沒有驗（上面那個盲點）。
- 第二下仍然沒有驗（那一下會寫帳本）。看的仍然是 DOM 不是像素。
- 污染登記簿現在 **5 筆全部 OPEN**（這一輪新增一筆）。
  交接契約 PRESENT 仍然 12/31。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 03:5x　挑了 5s 收尾留下的那個盲點

## 挑了什麼，為什麼是這一項

5s 那一輪自己寫下：「第二次切入那條路沒有驗（上面那個盲點）」。
它有明確的重現方式、不需要 owner 決定、而且**它撐著 B-16 的一句話**：
「要看到新資料只有一條路，切走再切回來」。那句話當時沒有證據 ——
量那張表的 `check_poll_page_fetches` 只按一下，而快取變數初值就是
`null`，首次切進去必然抓一次，清不清都一樣。5s 實測拿掉
`featCache = null`，那一組照樣全綠。

先確認過它不存在才動手：`grep -n "Cache = null\|revisit" tools/ tests/`，
沒有任何人守 `syncView()` 那五行。

## 做完什麼

`tools/ui-render-check.py` 加 `REVISIT_B_VIEW`、`REVISIT_SPY_AT_MS`／
`REVISIT_BUDGET_MS`、`REVISIT_MIN_LIVE`、`revisit_clicks()`、
`RevisitPage`／`REVISIT_PAGES`（五頁）、`check_revisit_refetches`，
`main()` 一頁開一次瀏覽器跑一圈。點六下：漢堡、A、漢堡、繞路、漢堡、A。

繞路挑「需要注意」，因為它一個專屬指令都不發（`POLL_PAGES` 量到的）。
`work` **在**這張表裡而**不在** `POLL_PAGES` 裡：兩張表問的是相反
方向的問題，`workCache = null` 這一行在這之前沒有任何人守。

每一格都是開瀏覽器量的：work 2、features 2、audit 2、machine 2、
spec_reading 3（載入 1 加兩次切入）。跟 5s 一樣對整份 `PAGE_CMDS`
斷言，缺席本身是斷言，那一圈裡也跑 `check_tab_switched`。

## 驗證結果

`python3 -m pytest tests/ -q` ── **1276 passed**（原 1260，新增 16 條）。
`python3 tools/ui-render-check.py` ── **回傳碼 0**，20 次瀏覽器
（原 15 次），192 秒（原 82 秒），全部 console 0 行。

## 反向驗證改真的 app.js 三次，每次還原並比對 sha256

| 改了什麼 | 結果 |
|---|---|
| 拿掉 `workCache = null` | 紅：`work` 2 → 1 |
| 拿掉 `specCache = null` | 紅：`spec_reading` 3 → 1 |
| 拿掉 `machCache = null` | 紅：`machine` 2 → 1 |

全程 `c0829f44069780b2`。（`featCache` 那一個是 5s 量盲點時驗過的。）

檢查函式自己四次：鍵拼錯（抓到）、期望值寫錯成 5（抓到）、
`REVISIT_MIN_LIVE` 拉到 9 紅、降到 1 放行（證明門檻有效力）、
迴圈不跑（抓到）。

## 新測試自己也反向驗證三次

一條永遠回 OK 的測試比沒有更糟，所以逼它紅了三次：
從 `REVISIT_PAGES` 拿掉 machine 那一頁（抓到）、在 `syncView()` 裡
加一頁清快取而表沒跟上（抓到）、把檢查函式的迴圈改成只比對第一個
指令（三條測試紅）。

`test_每一個有清快取的分頁都在這張表裡` 是**從 `app.js` 抽出來比對
的**，不是照著表寫的。照著表寫的話，表漏了一頁它也會跟著漏。

## 一個實測出來的盲點，沒有掩飾

**這一組驗不到「切走過」。** 把中間那兩下拿掉、連按同一頁兩次，
`features` 照樣是 2 —— `syncView()` 不管 `view` 有沒有變都照跑。
所以它真正守的是「`syncView()` 第二次跑會重抓」。留著繞路那一頁
是因為那是真人走的路，**不是因為它被驗到了**。

寫進 `check_revisit_refetches` 的說明與 ROADMAP 5t，不是只寫在這裡。
另外兩件也寫進去了：驗不到漢堡（同 `TABS` 那一組的已知盲點）、
分不出「每輪重發」與「每次切入各一次」（時窗只有 1500 毫秒）。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟開始時逐字元一致。`tools/ui-render-check.py` 最終
`e8e23571a7eb0b3d`，`tests/test_ui_render.py` `d3c15b8fb2320477`。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
這一輪連 `deploy.sh` 都沒有跑，因為沒有動畫面。

## 還缺什麼

- **B-16 更新了但沒有解除。** 加進去的是「那條逃生路現在有人守」
  這個事實與它的表。那個阻塞問的仍然是政策，仍然等 owner。
- 「切走過」本身沒有驗（上面那個盲點）。要驗到得分得出
  `view` 有沒有變，而 `syncView()` 現在不看這件事。
- 第二下仍然沒有驗（那一下會寫帳本）。看的仍然是 DOM 不是像素。
- 污染登記簿仍然 5 筆全部 OPEN（這一輪沒有新增，也沒有收掉）。
  交接契約 PRESENT 仍然 12/31。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 04:2x　挑了 5t 收尾留下的那個盲點

## 挑了什麼，為什麼是這一項

5t 那一輪自己寫下：「『切走過』本身沒有驗」。那句話當時是靠一次
手動實測得來的（連按同一頁兩次，`features` 照樣是 2），實測完
就散掉了，沒有任何東西守著它 —— `syncView()` 哪天開始比對 `view`，
上面那一組的射程會變，而那一天不會有任何跡象。

不需要 owner 決定，有明確的重現方式，而且它撐著
`check_revisit_refetches` 盲點一那整段話。

先確認過它不存在才動手：
`grep -rn "same_view\|SAMEPAGE\|reclick\|連按" tools/ tests/ desktop/ui/`
只有 5t 那一行註解，沒有任何檢查。

## 做完什麼

`tools/ui-render-check.py` 加 `samepage_clicks()`、`SamePage`／
`SAME_PAGES`（五頁）、`check_samepage_refetches`，`main()` 一頁
開一次瀏覽器跑一圈。按六下：漢堡、A、漢堡、A、漢堡、A。

跟上面那一組**只差中間那一下按 A 不按 B**，下數、間隔、傾印時刻
全部一樣，所以兩組的數字可以直接比。兩組合起來才分得出
「切走過」：`syncView()` 不看 `view` 的話是 2 比 3，看的話是 2 比 1。

比對邏輯抽成共用的 `_count_page_cmds`，兩支檢查共用它但訊息各自
分開。共用比對是為了不讓兩組對同一個形狀給出不同答案，訊息分開
是因為兩組壞掉時使用者看到的東西不一樣。

每一格都是開瀏覽器量的：work 3、feat 3、audit 3、machine 3、
spec_reading 4（載入 1 加三次切入）。

## 驗證結果

`python3 -m pytest tests/ -q` ── **1293 passed**（原 1276，新增 17 條）。
`python3 tools/ui-render-check.py` ── **回傳碼 0**，25 次瀏覽器
（原 20 次），239 秒（原 192 秒），全部 console 0 行。

## 反向驗證：真的改 app.js 量了一次

在 `syncView()` 開頭加一條 early return（`window.__rcLastView === view`
就回去），同一次實測：

| 那一組 | 改之前 | 改之後 |
|---|---|---|
| 連按同一頁三次 | features 3 綠 | features **1 紅** |
| 切走再切回來 | features 2 綠 | features 2 **仍然綠** |

這證明兩組合起來真的分得出「切走過」，不是紙上推論。
改完還原，`app.js` 全程 `c0829f44069780b2`。
同一個狀態下 `test_syncView沒有提早返回所以同頁再按也會重抓` 也紅了。

## 新測試自己也反向驗證四次

`SAME_PAGES` 的 3 改成 2（抓到）、中間那一下改成繞路（抓到）、
拿掉 machine 那一頁（抓到）、主流程那一圈改成不跑（抓到）。
加上上面真改 `app.js` 那一次，共五次。

`test_這張表跟切走再切回來那張表只差自己那一個指令` 是逐頁比對
兩張表算出來的，不是照著其中一張寫的 —— 這一組真正的價值在
「跟那一組比」，兩張表分歧了就沒有價值。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟開始時逐字元一致。`tools/ui-render-check.py` 最終
`9d946ecebe988821`，`tests/test_ui_render.py` `ab65119438f60290`。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
這一輪連 `deploy.sh` 都沒有跑，因為沒有動畫面。

## 還缺什麼

- **這一組數的是指令次數，不是畫面上那一格換了沒有。** 多發一次而
  畫面沒換，它照樣綠。寫在 docstring 裡，不是只寫在這裡。
- 驗不到漢堡、分不出「每輪重發」與「每次切入各一次」，
  這兩件跟上面那一組共用，都已經寫在各自的 docstring 裡。
- **B-16 仍然等 owner**：那條逃生路現在兩個方向都有人守，
  但那個阻塞問的是政策，不是有沒有人守。
- 第二下仍然沒有驗（那一下會寫帳本）。看的仍然是 DOM 不是像素。
- 污染登記簿仍然 5 筆全部 OPEN（這一輪沒有新增，也沒有收掉）。
  交接契約 PRESENT 仍然 12/31。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 04:4x　Python 那一側的「定義了但沒人讀」，第一次有人守

## 挑了什麼，為什麼是這一項

§40 污染登記簿第一筆的機制寫著「看到常數名稱就當成功能存在」，
講的是 `event_ledger.py:122` 的 `LINEAGE_EDGES`。**登記一筆污染改掉的
是那一次的結論，不是下一次的機制** —— 同一個形狀可以再長出來，
而在那一天沒有任何東西會紅。

JS 那一側兩個方向都有人守（`test_js_symbols.py` 守「叫了但沒定義」，
`test_ui_contract.py` 守「定義了但沒人叫」）。Python 這一側一條都沒有，
而污染登記簿第一筆講的正是 Python 的常數。

不需要 owner 決定，重現方式明確，而且它是機制不是結論。

先確認過它不存在才動手：

    grep -rn "unused_const\|dead_const\|定義了但\|未被引用\|未實作的常數" \
      tools/ tests/ apps/ src/

只命中 JS 那兩支的說明文字，Python 側零。

## 做完什麼

`tools/declared-only-check.py`：掃 `apps/forseti-cli/*.py` 的模組級
ALL_CAPS 常數（246 個），找出整個 Python 側從來沒有人讀的（18 個），
比對登記簿。清單以外的新增一律紅。

**歸屬到模組，不是比對名字。** 這個 repo 有 24 組同名常數
（`STATES` 在六個檔裡），純比名字的話只要有一個檔的 `STATES` 被讀，
六個都算被讀。精確歸屬當場多抓到兩個先前被同名掩蓋的
（`blast.py:64 SRC`、`lanes.py:48 KINDS`）。

登記簿的 `kind` 有三個值，是三種不同的帳不是三種放行：
`REFERENCE`（存在目的就是給人讀，處置：不用動）、
`DECLARED_ONLY`（名字宣稱了行為而行為不存在，**登記不是結案**，
收尾時單獨再列一次）、
`LEFTOVER`（既沒宣稱行為也沒人讀，**不替人決定要刪還是要接**）。

## 這一支第一次執行就找到兩件先前沒人知道的事

**一、`worker.py:51` 的 `RAW_INLINE_LIMIT` 是第二個 `LINEAGE_EDGES`。**
註解寫「超過這個大小的原始輸出一律落檔,不進 packet」，檔頭第 24 行
也寫「raw log 一律落檔」，而全 repo 只有定義那一行，加上
`docs/PROGRESS_2026-09-09.md:243` 把它列成一條已生效的規則（標「拍的」）。
隔壁 `SUMMARY_LIMIT` 與 `LIST_LIMIT` 都在 `check()` 裡真的被比較，
只有這一個沒有。落檔的 `stash_raw()` 存在而且能用，缺的是
「超過門檻就該落檔」這個判斷。

**比 `LINEAGE_EDGES` 危險：** 那一個的註解誠實寫著「這裡先定義不實作」，
這一個用的是直述句。讀的人沒有任何線索。

**沒有替她修**，三種處置（超過就拒收、超過就自動落檔、
或者把宣稱改成它真正的樣子）差別是政策不是技術。開了 `B-17`。

**二、`pollution.py:78` 的 `REQUIRES` 是同一條規則的第二份。**
那張表寫「REVERIFIED 要附 verifier、RESOLVED 要附 preventive_rule
或 regression_probe」，而那兩條規則**真的有被執行** —— 執行的是
`_missing_for()` 第 180 與 183 行手寫的 if，不是這張表。
改那張表不會改變任何行為。分類是 `REFERENCE`（行為在，不是空殼），
但理由裡寫明它比別的 `REFERENCE` 危險：它看起來像規則的來源。

**沒有開阻塞**，因為它擋不住任何具體交付 —— 照 `BLOCKERS.md` 開頭
第一條規則，那叫待辦不叫阻塞。

## 中途踩到的：這一支自己會污染自己

`tools/` 在 `READ_DIRS` 底下，所以掃描器的模組級名字會被自己掃到。
第一版它有一個常數叫 `KINDS`，結果 `lanes.py:48` 真正沒人讀的那個
`KINDS` 被判成「有弱引用」，安靜地從紅名單消失。

**改名只治那一次，排除自己才治以後每一次。** `py_files()` 加
`skip_self`，兩個方向都有測試；`test_lanes的KINDS仍然在紅名單裡`
拿那個唯一的實例當回歸測試。

## 登記簿不准變成垃圾桶，兩個方向都釘住

- 登記的常數不在了 → 紅（清單該清）
- 登記的常數現在有人讀了 → 紅（好消息，但清單要跟著改，
  不然它會一直宣稱一件已經不成立的事）
- 每一條的理由要指得回一個**查得到的位置**（§節號、檔名、行號、
  `函式()`、引的原文、實測次數），判準用正則不是關鍵字表
  —— 關鍵字表第一版就擋掉了整張表裡最具體的那一條

那條判準當場抓到兩條我自己寫得太薄的理由（`pollution.OPTIONAL`、
`blast.SRC`），而補 `blast.SRC` 的時候發現我把常數名寫錯了：
寫成 `SCAN_JS_DIRS`，實際是 `JS_SCAN_DIRS`（`blast.py:79`）。
**那正是這一組要防的東西在防我自己。**

## 驗證結果

`python3 -m pytest tests/ -q` ── **1314 passed**（原 1293，新增 21）。
`python3 tools/declared-only-check.py` ── 回傳碼 **0**，
246 個常數、18 個沒人讀、全部登記在案、登記簿沒有過期條目。

## 反向驗證六次，六次全抓到

| 改了什麼 | 結果 |
|---|---|
| 從登記簿拿掉 `RAW_INLINE_LIMIT` 那一條 | 2 紅 |
| 往 `worker.py` 加一個沒人讀的新常數 | 2 紅 |
| 登記一個不存在的常數 | 2 紅 |
| 拿掉 `skip_self` | 1 紅 |
| 讓 `RAW_INLINE_LIMIT` 在 `worker.py` 多出現一次 | 3 紅 |
| 把同名掩蓋放回去（改成純比名字） | 4 紅 |

每一次都還原並比對 sha256：`tools/declared-only-check.py`
`018b50ef54f6fe86`、`tests/test_declared_only.py` `3a3fdc7672f9434f`、
`apps/forseti-cli/worker.py` `c4a3ca772d065fee`，三個都跟改之前逐字元一致，
還原後 21 條全綠。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟開始時逐字元一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
這一輪連 `deploy.sh` 都沒有跑，因為沒有動畫面。

## 還缺什麼

- **這一支自己有五個盲點，寫在它的 docstring 裡不是只寫在這裡：**
  字串取用（`getattr(m, "FIELDS")`）抓不到；只掃 Python，值被 JS 或
  shell 重打一次看不到；弱引用算被讀（漏報的代價，換不誤報）；
  `from x import *` 之後無從歸屬；數的是有沒有人讀，不是讀了有沒有用對。
- **十六條 `REFERENCE` 共同的缺口沒有補：** 那些列舉的值在別處以
  字面字串重打（`starvation.py` 的 `RECOVERY_STEPS` 定義五個名字，
  十行後的 `recovery_plan()` 手打同樣五個），**拼錯不會紅**。
  補法是一支「常數裡的字面值有沒有在同檔被手打」的檢查，
  那是另一件事，這一輪沒有做。
- **`B-17` 等 owner**（`RAW_INLINE_LIMIT` 三種處置）。
- `pollution.REQUIRES` 那一份重複的規則沒有動（它不擋任何交付）。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5u 同一條理由（B-15）。
- 污染登記簿仍然 5 筆全部 OPEN。這一輪做的是「第一筆的機制以後會紅」，
  **不是收掉那一筆** —— 收尾是狀態轉換，留給 owner。
- 交接契約 PRESENT 仍然 12/31。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 commit_boundary，
  全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 05:0x　挑了上一輪自己寫下的缺口

## 閘門

`supervisor.py --status`：會不會喚醒 `true`，沒有閘擋住，
原因「NEXT.md 裡還有卡住的或沒解決的」，停了 12.1 分鐘，
今天喚醒 0 次（上限 40），停止開關 false。

## 挑了什麼，為什麼

上一輪（5v）收尾時自己寫下的第一項具體缺口：

    十六條 `REFERENCE` 共同的缺口沒有補：那些列舉的值在別處以
    字面字串重打（`starvation.py` 的 `RECOVERY_STEPS` 定義五個名字，
    十行後的 `recovery_plan()` 手打同樣五個），**拼錯不會紅**。

它不需要 owner 決定（不像 `scope_match`、B-17、§12.2 對應表），
定義明確，而且是上一輪自己指出來的下一步。

**動手前先確認它不存在：**
`grep -rln "restated\|duplicate_literal\|literal_check\|同檔被手打"
tools/ tests/ apps/ src/` 零命中。
`grep -rn "字面\|重打" tools/declared-only-check.py tools/ui-render-check.py`
只命中那兩支自己的盲點說明與登記簿理由。

## 做了什麼

`tools/literal-restate-check.py` 加 `tests/test_literal_restate.py`。

**這一支答的不是重打，是打錯的那一次。** 先量過才決定：
重打在真 repo 有 **141 組、289 次**（`if state == "RUNNING"` 這種），
把它們全部判紅只會讓這支守門被關掉。所以重打只出現在
`--restated` 的數字裡，**不判紅**。

判紅要三個條件同時成立：

1. 形狀像識別字（`^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$`，長度 >= 3）
2. **全 repo 只出現這一次**
3. 跟同檔某個列舉成員距離 1 到 2（0 是重打，不是拼錯）

真 repo 三條同時成立的：**0 個**。那不是這支沒用，
是此刻沒有拼錯 —— 而從今以後打錯會紅。

## 條件二是被一次誤報逼出來的，不是先想好的

第一版只有條件 1 和 3，真 repo 命中 1 條：

    owner.py:326  "OBSERVED"  ~  SILENCE 的 "UNOBSERVED"  距離 2

**去查了才知道它是誤報。** `provenance="OBSERVED"` 是
`event_ledger.py:236` 的欄位預設值，`starvation.py:61` 也有一個
`OBSERVED = "OBSERVED"`，全 repo 出現四次，完全合法。
合法的值會在別處也出現，打錯的那一次只有那一處 —— 條件二就是這件事。
加上之後 0 命中 0 誤報。

`test_repo唯一這個條件拿掉就會誤報` 拿真 repo 的 `OBSERVED`
當回歸測試（驗它真的出現不只一次，且距離真的是 2）。

## 第一次反向驗證就被自己的測試擋下來，這是這一輪最重要的事

把 `starvation.py:176` 手打的 `"SYNTHESIS_ONLY"` 打成
`"SYNTHESIS_OLNY"`，**應該紅，結果綠**。

原因：`tests/test_literal_restate.py` 裡有一條測試拿同一個錯字串
當負例，而 `tests/` 在 `COUNT_DIRS` 底下 —— 於是
「全 repo 只出現這一次」不成立，那個真的打錯的字串安靜地
從紅名單消失。

**守門被自己的測試關掉，而且完全沒有聲音。往綠的方向壞。**

跟 5v 的 `KINDS` 撞名同一個形狀，只是這一次污染源是測試檔
不是工具檔。**改測試裡那個字串只治那一次**，`_SELF_FILES`
把工具與測試兩個檔一起排除才治以後每一次。修好之後同一個
反向驗證紅了，指到 `starvation.py:176`、`RECOVERY_STEPS`、
`"SYNTHESIS_ONLY"`、距離 2。

排除用的是硬寫的路徑，所以另有一條 `test_排除清單裡的檔案必須真的存在`
—— 檔案改名之後排除會安靜失效，而失效的方向是往綠的。

反向驗證也做成常設測試（`test_把真檔打錯一個字會紅`）：讀真的
`starvation.py`，在記憶體裡把那一行打錯，寫進合成目錄再掃，
不動磁碟上的原始檔。

## 改掉一句我自己沒驗證就寫下的話

檔頭原本寫：「選 2 是因為選 3 會把 `"PROPOSED"` 跟 `"PROPOSE"`
這類真的不同的名字一起拖進來」。

**兩個部分都不對。** 實測把 `MAX_DISTANCE` 放寬到 3，
真 repo 一樣 0 命中 0 誤報；而 `PROPOSED` 跟 `PROPOSE` 的距離
是 **1** 不是 3，例子本身就錯。

現在寫的是它真正的樣子：這是一個選擇不是一個量測，
此刻沒有證據說 2 比 3 好，選 2 的理由是距離越大
「這是拼錯」這個推論越弱。`test_距離3不算` 的 docstring
也改成「守的是現在這個閾值的行為，不是 3 一定會出事」。

## 驗證結果

`python3 -m pytest tests/ -q` ── **1347 passed**（原 1314，新增 33）。
`python3 tools/literal-restate-check.py` ── 回傳碼 **0**，
70 個列舉常數、266 個成員、141 組手打共 289 次、0 個疑似打錯、
豁免登記簿沒有過期條目。

## 反向驗證六次，六次全抓到

| 改了什麼 | 結果 |
|---|---|
| 真檔手打處打錯一個字（修好自我污染後） | `literal-restate-check.py` 回傳碼 1，指到 `starvation.py:176` |
| 拿掉條件 2（全 repo 唯一） | `test_repo裡出現第二次就不算拼錯` 紅 |
| 拿掉 `_SELF_FILES` 自我排除 | `test_這一組自己不可以參與計數` 紅 |
| `MAX_DISTANCE` 放寬到 3 | `test_距離3不算` 紅（真 repo 仍 0 命中） |
| `MIN_ENUM_MEMBERS` 放寬到 1 | `test_只有一個成員不算列舉` 紅 |
| 登記一條不存在的豁免 | `test_豁免登記簿沒有過期條目` 紅 |

後兩條第一次是批次跑的，失敗訊息對不上我預期的那一條，
**所以各自單獨重跑了一次確認歸因**，上表寫的是單獨跑的結果。
批次那一輪的歸因我沒辦法重建，就不寫進來。

每一次都還原並比對 sha256：
`tools/literal-restate-check.py` `0c44682496cb86ed`（最終版
含後續修正）、`apps/forseti-cli/starvation.py`
`042ecae61e3d9738`，還原後逐字元一致，全套 1347 條全綠。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。`deploy.sh` 也沒有跑，因為沒有動畫面。

`.forseti/NEXT.md` 沒有手改 —— 它是 snapshot 流程自動產生的，
手改會變成第二個事實來源（`_write_handoff` 的 docstring 明講）。
實際觸發方式是在 repo 內直接呼叫正本產生者：
`D.snapshot()` 之後 `D._write_handoff(snap)`，回
`{'ok': True, 'bytes': 9753}`，mtime 05:04:34，
檔案自己算出工作區從 107 個變 109 個（正好是這一輪新增的兩個檔）。

**先試的 `python3 apps/forseti-cli/desktop_api.py snapshot` 沒有寫成。**
回傳碼 0、stderr 空、`NEXT.md` mtime 不動；而同一時刻直接問
`HO.should_write()` 是 `True`（距上次 301 秒，門檻 240）。
`_write_handoff` 包在 `_safe()` 裡，例外會被吞成回傳值。
**沒有查出原因就不寫成結論** —— 這裡只記下觀察到的現象，
它有可能是一個靜默失敗，也有可能是我沒看懂的正常行為。

## 還缺什麼

- **這一支自己有六個盲點，寫在它的 docstring 裡不是只寫在這裡：**
  兩處打錯成同一個樣子抓不到（複製貼上剛好就是這個形狀，
  是真的會發生的漏報）；距離 3 以上抓不到；只看 ALL_CAPS 風格，
  小寫鍵名（`"tool_use"`）打錯照樣不紅；定義側只掃 Python，
  JS 只當白名單；用了合法但錯的成員（`"VERIFYING"` 該寫
  `"VERIFIED"`）看不出來，那要語意不是拼寫；單值常數不構成對照組。
- **141 組手打本身沒有動。** 這一輪把它變成一個每次重算的數字，
  **不是把它改掉** —— 改不改是政策（要不要強制引用常數），
  而且 289 個位置一次改完會蓋掉別的東西。
- **最該補的下一件是「小寫鍵名」那一半。** 現在只看 ALL_CAPS，
  而這個 repo 的 dict key 大量是小寫（`"tool_use"`、`"session_id"`），
  同一個拼錯風險完全沒有人守。判準要重想，因為小寫字串的
  誤報率會高很多。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5v 同一條理由（B-15）。
- `B-17` 等 owner（`RAW_INLINE_LIMIT` 三種處置）。
- 污染登記簿仍然 5 筆全部 OPEN。收尾是狀態轉換，留給 owner。
- 交接契約 PRESENT 仍然 12/31。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 05:2x　小寫鍵名那一半補上了

## 閘門

`supervisor.py --status`：會不會喚醒 `true`，沒有閘擋住，
原因「NEXT.md 有內容」，停了 9.8 分鐘，今天喚醒 0 次（上限 40），
停止開關 false。

## 挑了什麼，為什麼

上一輪（5w）收尾時自己寫下的那一項：

    **最該補的下一件是「小寫鍵名」那一半。** 現在只看 ALL_CAPS，
    而這個 repo 的 dict key 大量是小寫（`"tool_use"`、`"session_id"`），
    同一個拼錯風險完全沒有人守。判準要重想，因為小寫字串的
    誤報率會高很多。

P0 兩項都不動：第 1 項（真的救回一次）卡在 owner 要按的那一步，
第 2 項（Context Sufficiency Gate）等 F04／F05 接上來才判斷得了。
這一項不需要 owner 決定，定義明確，而且是上一輪自己指出的下一步。

**動手前先確認它不存在：**
`grep -rln "lowercase\|小寫\|lower_key\|dict key" tools/ tests/ apps/ src/`
三個命中，逐一看過都不是守門：`tools/consult.py` 與
`apps/forseti-cli/recall.py` 是別的東西，
`tools/literal-restate-check.py` 那一處正是它自己寫的盲點那一句。

## 先量再決定判準，不是先寫規則再看結果

小寫側的規模跟 ALL_CAPS 差一個量級，所以閾值不能照抄：

| | ALL_CAPS | 小寫 |
|---|---|---|
| 列舉常數 | 70 | 35 |
| 成員（module,member 配對） | 266 | 231 |
| distinct 字面字串 | 未量 | 1278 |
| 全 repo 只出現一次的 | 未量 | 352 |

照抄 ALL_CAPS 的三條件（距離上界 2、只有 JS 字串白名單）實跑，
真 repo 命中 **2 條**：

    desktop_api.py:2091  "stale_total"  ~ FEATURES 的 "stall_total"  距離 1
    migrate.py:255       "save"         ~ ITEMS 的 "name"            距離 2

**兩條都是誤報，而且兩條指向不同的東西。**

`"save"` 對到 `"name"`：兩個四個字母的常用詞，語意上毫無關係。
距離 1 同一次量測沒有這一條。小寫短字是自然語言的詞，
彼此距離 2 的碰撞率遠高於 ALL_CAPS。所以小寫側的
`LOWER_MAX_DISTANCE` 收到 **1**。

## 第二條誤報逼出一層 ALL_CAPS 不需要的白名單

`"stale_total"` 被判成 `"stall_total"` 的拼錯。去查了才知道
**兩個都是活的，而且是兩件不同的事**：

- `"stale_total"`（`desktop_api.py:2091`）＝身份那一頁陳舊 alias 有幾個，
  讀它的是 `desktop/ui/app.js:942` 的 `t.stale_total`
- `"stall_total"`（`desktop_api.py:2526`、`3072`）＝停滯風險那一格

條件 2（全 repo 唯一）沒有擋住它，原因是
**小寫鍵名的下游讀者常常是 `obj.key` 而不是引號字串** ——
`t.stale_total` 不是引號包起來的，所以字串計數看不到它。
ALL_CAPS 那一側沒有這個問題，因為那些值幾乎只會以字串出現。

所以小寫側多一層 `attr_names()`：以 `obj.key` 形式出現過的名字
全部進白名單。加上之後兩條誤報都消失，真 repo **0 命中**。

**代價寫在 docstring 裡不是只寫在這裡：** 這個白名單有 1527 個名字，
而 214 個小寫成員裡有 84 個也在裡面。一個打錯的字只要撞上
某個屬性名就不會紅。方向是往綠的，跟條件 2 同一種取捨。

## 誠實的界線，不要把量測講得比實際大

加上屬性白名單之後，距離 2 在真 repo 也回到 0 命中。
所以量到的是「白名單較弱時 2 會誤報而 1 不會」，
**不是**「有了白名單之後 2 仍然會誤報」。
`LOWER_MAX_DISTANCE` 的說明就是這樣寫的。

## 做法：兩個 Profile 共用一個掃描核心，不是複製一支工具

`tools/literal-restate-check.py` 加 `Profile`（形狀、最短長度、
距離上界、要不要查屬性白名單），`UPPER` 與 `LOWER` 兩個實例。
`scan(prof=...)` 預設 `UPPER`，所以既有 33 條測試一個字都沒改。

`main()` 預設兩種都掃，`--profile upper|lower|both` 可以只看一邊。

**`stale_across()` 是為了一個共用 `EXEMPT` 的坑：** 兩個風格共用
同一張豁免表，單獨拿一份 Report 問「這條豁免過期了嗎」，
另一個風格登記的豁免會被誤判成過期。`main()` 用的是跨風格那一個。
`test_單獨一份報告會把另一個風格的豁免誤判成過期` 把這件事釘住。

## 驗證結果

`python3 -m pytest tests/ -q` ── **1365 passed**（原 1347，新增 18）。

`python3 tools/literal-restate-check.py` ── 回傳碼 **0**：

    ALL_CAPS：70 個列舉常數、266 個成員、141 組手打共 289 次、0 疑似打錯
    小寫：　　35 個列舉常數、231 個成員、123 組手打共 326 次、0 疑似打錯

ALL_CAPS 那兩組數字（70／266／141／289）跟上一輪紀錄逐字一致，
所以這次改動沒有動到既有那一半。`test_ALL_CAPS那一側的數字沒有被這次改動動到`
把它做成常設回歸。

## 反向驗證五次，五次全抓到

| 改了什麼 | 結果 |
|---|---|
| 真檔 `pollution.py:315` 把 `"regression_probe"` 打成 `"regression_prope"` | 回傳碼 1，指到 `pollution.py:315`、`FIELDS`、距離 1 |
| `LOWER_MAX_DISTANCE` 放寬到 2 | `test_小寫側距離2不算` 紅 |
| `LOWER.use_attr` 改成 False | `test_以屬性形式出現過就不算拼錯` 紅 |
| `scan()` 裡 `or v in attrs` 拿掉 | 同上那條紅 |
| `stale_across()` 只看 upper | `test_跨風格算過期看的是兩邊命中的聯集` 紅 |

後四條**各自單獨跑**，不是批次跑，所以歸因是確定的（5w 的教訓）。
每一次都還原並比對 sha256：`tools/literal-restate-check.py`
還原後 `2c51aa177a3b6eb3`（那是加 docstring 之前的版本），
`apps/forseti-cli/pollution.py` `1720b50784e15495`，逐字元一致。

`test_沒有那個屬性就會紅` 是屬性白名單那條測試的對照組：
拿掉屬性來源，同一份定義就判紅。沒有它，上面那條綠掉的原因
有可能只是別的東西。

## 改掉檔頭一句已經不成立的話

原本的盲點清單寫著：

    **只有 ALL_CAPS 風格。** 小寫的鍵名（`"tool_use"`）打錯照樣不會紅。

這句現在不成立了，留著就是一句錯的話。換成兩條現在真的成立的：
屬性白名單很大所以會漏報、駝峰命名（`toolUse`）兩種風格都不看。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。`deploy.sh` 也沒有跑，因為沒有動畫面。

## 還缺什麼

- **駝峰命名那一種還沒有人守。** `toolUse` 打成 `toolUes`，
  兩個 Profile 都不看。JS 側那些物件欄位大量是這個形狀。
  它的判準又要重想一次，因為駝峰的邊界不像底線那麼明確。
- **屬性白名單的漏報沒有量。** 知道有 84 個成員落在白名單裡，
  但沒有量過「把它們各打錯一次，有幾個會被白名單吃掉」。
  那是一個做得出來的數字，這一輪沒做。
- **123 組小寫手打本身沒有動**，跟 ALL_CAPS 那 141 組同一條理由：
  改不改是政策，而 326 個位置一次改完會蓋掉別的東西。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5w 同一條理由（B-15）。
- `B-17` 等 owner（`RAW_INLINE_LIMIT` 三種處置）。
- 污染登記簿仍然 5 筆全部 OPEN。收尾是狀態轉換，留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 05:4x　白名單的代價，第一次是一個數字

## 挑了什麼，為什麼

上一輪（5x）收尾時自己寫下兩個缺口，這一輪挑了第二個：

    屬性白名單的漏報沒有量。知道有 84 個成員落在白名單裡，
    但沒有量過「把它們各打錯一次，有幾個會被白名單吃掉」。
    那是一個做得出來的數字，這一輪沒做。

另一個（駝峰命名）沒挑，因為它的判準要重想一次，
而這一個是一個已經定義清楚、做得出來的數字。

## 先確認它不存在才動手

    grep -rln "shadow|mutation|漏報量|false_negative" tools/ tests/ apps/ src/
      → apps/forseti-cli/probe.py（mutation_caught 是探針包對帳本做變異）
      → src/verifier.js（shadow 是別的東西）
    grep -rln "typo" → tests/test_blast.py、tests/test_literal_restate.py
    tools/measure-fpr.mjs → 量的是誤報率，不是漏報

三個都不是這件事。沒有重做。

## 它推翻了那支自己寫的一句話

`attr_names()` 的 docstring 原本停在這裡：

    這個白名單在真 repo 有一千五百多個名字，而 214 個小寫列舉成員裡
    有 84 個也在裡面。一個打錯的字只要剛好撞上某個屬性名就不會紅。

**停在 84 這個數字上，就會被讀成「84 個成員打錯了不會紅」。**
而判紅看的是**打錯之後**那個字串在不在白名單裡，不是原成員在不在。
兩個是不同的集合，`obj.alpha` 讓 `alpha` 進白名單，
完全不影響 `alpba` 判不判紅。

## 真實的數字

| | ALL_CAPS | 小寫 |
|---|---|---|
| 成員（module,member 配對） | 266 | 231 |
| 獨立成員字串 | 222 | 214 |
| 自己也在屬性白名單裡 | 0 | 84 |
| 距離 1 的替換變異 | 101980 | 75921 |
| 會紅 | 101958 | 75878 |
| 不會紅 | 22 | 43 |
| ── 撞上另一個合法成員 | 4 | 0 |
| ── repo 別處也有 | 5 | 22 |
| ── JS 側也有 | 13 | 10 |
| ── 只有屬性白名單擋住 | 0 | **11** |

**11 個變異，落在 10 個成員上。** 不是 84。

    blast.py        "src"         打成 "sec"          不會紅
    blast.py        "test"        打成 "best"         不會紅
    blast.py        "test"        打成 "rest"         不會紅
    blast.py        "tests"       打成 "texts"        不會紅
    claims.py       "file"        打成 "five"         不會紅
    claims.py       "fixed"       打成 "fired"        不會紅
    desktop_api.py  "stall_total" 打成 "stale_total"  不會紅
    handoff.py      "stuck"       打成 "stack"        不會紅
    probe.py        "sot"         打成 "set"          不會紅
    sot.py          "git"         打成 "get"          不會紅
    workflow.py     "how"         打成 "now"          不會紅

全部是短的常用英文詞。短詞的距離 1 鄰居容易也是常用詞，
而常用詞容易是某個屬性名。

**最後一條之外的那一條值得單獨看：** `stall_total` 打成
`stale_total` 不會紅，而 5x 那次誤報正好是反過來的 ——
那一次是把真實存在的 `stale_total` 判成 `stall_total` 的拼錯。
同一對字串，一個方向是誤報，另一個方向是漏報。

## 做法：加進同一支，不是複製一支

`tools/literal-restate-check.py` 加 `mutate()`、`Shadow`、
`ShadowAudit`、`audit_shadow()`、`--shadow`，共用既有的三個
白名單來源（`repo_literal_counts` / `js_literals` / `attr_names`）。
`scan()` 一個字都沒動，守門行為不變，既有 51 條測試一個字都沒改。

**這一支不判紅。** 它印的是數字，紅不紅由 `scan()` 決定。
量測開始判紅的那一天，守門就會因為一個既有的、已知的代價
而永遠是紅的，然後被關掉。有一條測試釘住這件事。

## 分母的界線，寫在 `mutate()` 裡不是只寫在這裡

只做單字元替換。替換保證距離剛好 1，所以「有沒有被擋掉」
問的純粹是白名單，不會跟距離上界糾纏在一起。

刪除與插入也是距離 1，**沒有量**。相鄰對調（`ONLY` 打成 `OLNY`）
的 Levenshtein 距離是 2，小寫側上界 1 本來就抓不到它。
**所以 11 是一個下界不是全部。**

形狀不合的變異（第一個字元換成數字）不計入分母，因為那種字串
在 `scan()` 裡根本走不到白名單那一關，算進去只會稀釋比例。

## 反向驗證八次，七次抓到，沒抓到的那一次最有價值

| 改了什麼 | 結果 |
|---|---|
| `attr_only` 不排除 repo/js | `test_repo裡也有的時候歸給repo不歸給屬性` 紅 |
| 歸因順序改成 attr → js → repo | 同上那條紅 |
| `mutate()` 不檢查形狀 | `test_形狀不合的變異不計入分母` 紅 |
| 撞上合法成員不獨立分類 | `test_撞上另一個合法成員歸給member` 紅 |
| `audit_shadow()` 不看 `use_attr` | **綠。沒抓到。** |
| `_ATTR_RE` 放寬到收大寫 | `test_屬性白名單只收小寫名字` 紅 |
| `members_in_attrs` 算成 0 | `test_代價遠小於在白名單裡的成員數` 紅 |
| `caught` 少數一個 | `test_守恆_會紅的加不會紅的等於變異總數` 紅 |

每一條各自單獨跑，還原後 `tools/literal-restate-check.py`
`3ad4c74377c67d4c`，逐字元一致。

## 第五條為什麼沒抓到

把 `audit_shadow()` 裡 `if prof.use_attr else set()` 拿掉，
也就是讓 ALL_CAPS 側也去查屬性白名單，
`test_ALL_CAPS側的屬性代價是0` **照樣綠**。

去查了才知道真正的原因：`_ATTR_RE` 是
`\.([a-z][a-z0-9]*(?:_[a-z0-9]+)*)\b`，只收小寫名字。
實測 `attr_names(prof=UPPER)` 1527 個名字裡大寫的有 0 個。
所以大寫的變異永遠不可能落在那個集合裡，兩個字元集不相交。

**那條測試宣稱守 `use_attr` 被遵守，實際上守不到。**
`use_attr` 在 ALL_CAPS 側省的是三秒鐘，不是一個結果。

處置是改掉宣稱，不是刪掉測試：docstring 寫明它綠的真正原因
有兩層而只有第二層守得住，另加 `test_屬性白名單只收小寫名字`
釘住那個真正的理由 —— `_ATTR_RE` 哪天放寬到收大寫，
這一條會紅，那時 ALL_CAPS 側的免疫就不再成立。
反向驗證過，會紅。真正守住 `use_attr` 的是小寫側的
on／off 對照 `test_關掉屬性白名單代價就歸零`。

## 驗證結果

    python3 -m pytest tests/ -q
    1382 passed in 118.37s

上一輪 1365，這一輪 17 條新測試。`tests/test_literal_restate.py`
自己從 51 條到 68 條。

`python3 tools/literal-restate-check.py` 回傳碼 0，守門仍綠。

## 改掉兩處已經不成立的話

一，`attr_names()` 的「代價寫在這裡」那一段，改成帶數字的版本，
並且寫明「84 個成員在白名單裡」跟「84 個成員打錯不會紅」
是兩件不同的事。

二，檔頭盲點清單那一條同樣改掉，並且新增一條：
那個量測自己只看替換，所以 11 是下界。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。`deploy.sh` 也沒有跑，因為沒有動畫面。

## 還缺什麼

- **駝峰命名（`toolUse`）那一種還是沒有人守。** 兩個 Profile 都不看，
  JS 側那些物件欄位大量是這個形狀。判準要重想一次。
- **刪除與插入沒有納入量測。** 11 是下界。把這兩種加進 `mutate()`
  可以把下界收緊，做得出來，這一輪沒做。
- **那 11 條沒有任何處置。** 量出來不等於修掉。要不要為它們做點什麼
  （例如把短成員排除在小寫掃描之外）是一個政策決定，留給 owner。
- 123 組小寫手打、141 組 ALL_CAPS 手打本身沒有動，跟前幾輪同一條理由。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5x 同一條理由（B-15）。
- `B-17` 等 owner（`RAW_INLINE_LIMIT` 三種處置）。
- 污染登記簿仍然 5 筆全部 OPEN。收尾是狀態轉換，留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

# 2026-09-17 06:0x　把少打與多打納入漏報量測，下界從 11 收緊到 23

## 挑了什麼，為什麼

`ROADMAP.md` 5y 收尾時自己寫下兩個缺口。第一個（駝峰命名）
寫著「判準要重想一次」，那是還沒想清楚的；第二個寫著
「刪除與插入沒有納入量測，11 是下界，把這兩種加進 `mutate()`
可以把下界收緊，做得出來，這一輪沒做」——
做得出來、界線清楚、驗得掉，所以挑第二個。

## 先確認它不存在

    grep -n "def mutate\|insert\|delete\|deletion\|insertion" \
        tools/literal-restate-check.py

只命中 `def mutate` 一行。沒有任何刪除或插入的實作。

## 做了什麼

`tools/literal-restate-check.py`（沒有開新檔，沒有複製一支工具）：

- `MUTATION_KINDS = ("sub", "del", "ins")`，三種距離 1 的打錯方式。
- `DEFAULT_MUTATION_KINDS = ("sub",)`，**預設刻意不跟著變寬**。
- `mutate_kinds()` 回傳 `(種類, 變異)`，`mutate()` 變成它的字串版本，
  預設種類不變，所以既有呼叫端一個字都沒改。
- `Shadow` 多一個 `kind` 欄（有預設值，既有的位置參數建構不能壞）。
- `ShadowAudit` 多 `kinds` 與 `mut_by_kind`，加 `per_kind` 逐種帳。
- `KindTally`，一種打錯方式自己的分母／會紅／不會紅／屬性獨擋。
- CLI 加 `--shadow-kinds`，種類打錯會 `ap.error` 停掉。

## 為什麼預設不跟著變寬

5y 紀錄裡那個 11 是在「只有替換」的條件下量的。預設改成三種，
那個數字會無聲地變成另一個數字，紀錄裡的 11 就指不回任何
可重跑的東西。實測預設路徑仍然還原得出

    kinds ['sub']
    mutations 75921
    blocked {'repo': 22, 'attr': 11, 'js': 10}
    attr_only 11 members 10

跟 5y 逐項一致。`test_預設只有替換` 釘住這件事。

## 量出來的數字

小寫側，`--shadow --shadow-kinds sub,del,ins`：

    成員 231 個（獨立字串 214 個，其中 84 個自己也在屬性白名單裡）
    距離 1 的變異 162309 個，其中 162199 個會紅，110 個不會
      sub  替換一個字元　 75921 ／  75878 ／   43 ／  11
      del  少打一個字元　  2151 ／   2115 ／   36 ／   6
      ins  多打一個字元　 84237 ／  84206 ／   31 ／   6
    （欄位是 分母／會紅／不會紅／只有屬性白名單擋住）
    blocked 全貌：member 6、repo 67、js 14、attr 23
    只有屬性白名單擋住的：23 個變異，落在 21 個成員上

ALL_CAPS 側 216430 個變異、blocked 25 個（sub 22、del 1、ins 2），
屬性代價仍然是 0，理由跟 5y 一樣是 `_ATTR_RE` 只收小寫，
兩個字元集不相交。

**下界從 11 收緊到 23，落在的成員數從 10 到 21。**

## 新露出來的 12 個是另一個形狀

    authority.py     send        -> end        少打
    claims.py        created     -> create     少打
    claims.py        number      -> numbers    多打
    claims.py        ran         -> rank       多打
    event_ledger.py  insider     -> inside     少打
    migrate.py       name        -> names      多打
    migrate.py       transcripts -> transcript 少打
    overclaim.py     actor       -> actors     多打
    overclaim.py     resolved    -> resolve    少打
    overclaim.py     time        -> utime      多打
    probe.py         sot         -> sort       多打
    workflow.py      outputs     -> output     少打

十二個裡有九個是「長的那個以短的那個開頭」，也就是差在字尾
一個字元。那九個裡有七個是真的單複數或時態。

**九跟七是兩個數字，不要合併。** `insider`→`inside` 與
`ran`→`rank` 是字尾形狀但不是詞形變化。測試釘的是九那一個，
因為「是不是詞形變化」沒有辦法用程式判準地判 ——
工具的說明裡兩個數字分開寫。

我自己寫第一版說明的時候把這兩個數字合成了「九個是單複數或
時態」，然後實際列出來對過才發現是七個。**已改掉**，
記在這裡是因為那正是這支工具在防的同一種事：一個聽起來
合理的數字，沒有對著原始清單數過。

只量替換完全看不到這個形狀。詞形變化的兩個形式通常**都**有人
以 `obj.key` 用過，所以屬性白名單整類吃掉。

## 反向驗證八次，七次抓到

1. 預設改成三種　→　5 紅（含 `test_預設只有替換`）
2. 去重拿掉　→　2 紅（少打／多打各一條）
3. 不認得的種類改成安靜跳過　→　1 紅
4. `Shadow` 不記種類一律當替換　→　3 紅
5. 少打不過形狀那一關　→　1 紅
6. `mut_by_kind` 少報一個　→　1 紅（逐種分母對不上總數）
7. 少打也排除底線　→　1 紅
8. **把底線加進插入用的字母表　→　88 條全綠，沒抓到**

第八次是這一輪最有價值的一次。原本那條 `test_不替換成底線`
只看預設種類（替換），**插入那一側的同一個決定完全沒有人守**。
而它是有後果的：`alpha` 插一個底線得到的 `a_lpha` 形狀完全合法，
會進到分母裡，於是量到的就混進了形狀，不再只有白名單。

處置是補守門不是改說明：加 `test_不插入底線`，重跑同一個破壞，
紅。少打不排除底線是故意的（拿掉既有底線後形狀仍合法，
那是真的打錯方式），兩邊不對稱，所以兩邊各一條測試釘住。

## 去重只做在種類之內

三種的長度分別是 n、n-1、n+1，三個集合不相交，所以跨種類
不可能重複；種類之內會（`abb` 在三個位置插 `b` 都得到 `abbb`，
`abbc` 拿掉第二或第三個字元都得到 `abc`），不去重會灌水分母。
三條測試分別釘住這三件事。

## 分母的界線沒有變

相鄰對調（`ONLY` 打成 `OLNY`）的 Levenshtein 距離是 2，
三種都不含它，小寫側上界 1 本來也抓不到。
**所以 23 仍然是下界，只是比 11 緊。** 這句寫進工具檔頭的
盲點清單與 `_report_shadow()` 的輸出裡。

## 驗證結果

    python3 -m pytest tests/ -q
    1403 passed in 90.38s

上一輪 1382，這一輪 21 條新測試。`tests/test_literal_restate.py`
自己從 68 條到 89 條。

三個守門回傳碼都是 0：

    python3 tools/declared-only-check.py     → 0
    python3 tools/ui-render-check.py         → 0
    python3 tools/literal-restate-check.py   → 0

（中途用 `timeout` 包 `ui-render-check.py` 拿到 127，那是 macOS
沒有 `timeout` 這個指令，不是工具失敗。直接跑是 0。記在這裡
是因為 127 看起來像紅燈，而它不是。）

## 改掉兩處已經不成立的話

一，檔頭盲點清單那一條，從「那個量測自己只看替換」改成帶新數字
的版本，並寫明預設仍然只量替換以及為什麼。

二，`attr_names()` 的「代價量出來了」那一段，改成一張兩列的表
（只有替換 vs 三種一起），並把新露出來的那個形狀寫進去。

## 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

## 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。`deploy.sh` 也沒有跑，因為沒有動畫面。

## `.forseti/NEXT.md` 是自動產生的，沒有手改

呼叫 `D.snapshot()`，它自己在內部走 `_write_handoff`，
mtime 從 05:44 動到 06:10，檔案裡也換上了這一輪兩個檔的新雜湊。
**接著再顯式呼叫一次 `D._write_handoff(snap)` 回 `None`**，
因為 `HO.should_write()` 這時是 `False`（節流門檻 240 秒）。

上一輪紀錄裡有一筆相反的觀察（CLI 路徑沒寫成、顯式呼叫寫成了）。
**這一輪的觀察不足以解釋那一筆** —— 我沒有在呼叫 `snapshot()`
之前先問過 `should_write()`，所以不知道那時是什麼狀態。
這裡只記下這一次看到的，不把它寫成上一筆的答案。

## 還缺什麼

- **駝峰命名（`toolUse`）那一種還是沒有人守。** 連續第二輪被推到
  下一輪。兩個 Profile 都不看，JS 側那些物件欄位大量是這個形狀，
  判準要重想一次。
- **相鄰對調沒有納入，所以 23 仍然是下界。** 它的距離是 2，
  要納入得先決定距離上界怎麼處理，那不是加一種變異就好。
- **那 23 條沒有任何處置。** 量出來不等於修掉。要不要為它們做點
  什麼（例如把短成員或詞形變化對排除在小寫掃描之外）是一個
  政策決定，留給 owner。
- 123 組小寫手打、141 組 ALL_CAPS 手打本身沒有動，跟前幾輪同理由。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5y 同一條理由（B-15）。
- `B-17` 等 owner（`RAW_INLINE_LIMIT` 三種處置）。
- 污染登記簿仍然 5 筆全部 OPEN。收尾是狀態轉換，留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  commit_boundary，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

## 2026-09-17 06:2x　駝峰那一項連續三輪被順延，這一輪量了它，發現它不是缺口

### 挑了什麼

`AUTO_CONTINUE_LOG.md` 上一輪「還缺什麼」的第一條：
**駝峰命名（`toolUse`）那一種還是沒有人守**，連續第二輪被推到下一輪，
理由都是「判準要重想一次」。

**這一輪沒有去想判準，先去量有多少東西可守。**

### 量出來的結果，兩側都是空的

| 側 | 駝峰列舉 | 成員 |
|---|---|---|
| Python 定義側（`apps/forseti-cli/*.py`，掃描器唯一的定義來源） | 0 | 0 |
| JS 側（`JS_DIRS`） | 1 個像列舉的 const 區塊 | 2 |

**那 2 個進一步查過，不是列舉值。** `src/provenance.js:75`、`:76` 的
`'confidenceLoad'` 與 `'falseConfessions'` 是 `rhetoric.js` 兩個函式的
名字，記在一張出處登記簿的 `fn:` 欄位
（`src/rhetoric.js:74`、`:133` 是 `export function` 定義，
`src/runtime.js:78` 是 import）。函式名字不是「某個欄位的合法值有哪幾個」。
**所以 JS 側真正的駝峰列舉材料也是 0。**

結論：**不守駝峰不是欠一個判準，是沒有東西可守。** 加一個 `CAMEL`
進 `PROFILES` 會得到一個永遠 0 命中的風格 —— 畫面上多一節看起來
有人在守的東西，實際一個字都守不到。那正是任務規則裡
「接上去畫面不會變的東西，接了就是白工」。

### 做了什麼

一，`camel_census()` 與 `CamelCensus`。兩側各量一次，
`--camel` 印得出來，`--json` 帶得出去。**刻意不進 `PROFILES`**，
而且那個「刻意」有測試釘住（`test_駝峰不在PROFILES裡`）。

二，`js_enum_blocks()`。從 JS 抓「像列舉的 const 區塊」，
括號收平判界線，上界 60 行。**回傳的是下界不是精確值**，
理由跟 `js_literals()` 用正則不用 parser 同一條，
只是方向相反：那一支多抓讓判紅更保守，這一支多抓少抓
都只影響一個統計數字，不影響任何判紅。

三，**那個結論自己會腐爛，所以它有守門。**
`test_駝峰在Python定義側必須仍然是空的` 拿真 repo 跑，
Python 側一出現駝峰列舉就紅，訊息直接寫「該把 CAMEL 加進 PROFILES」。
**JS 側刻意不設紅線** —— JS 此刻不是定義來源，所以 JS 的駝峰長多少
都不改變「這支要不要加第三個 Profile」，它改變的是另一件事。
兩件事合成一條紅線，會讓 JS 的任何改動觸發一條它解釋不了的紅燈。

### 反向驗證第一次沒紅，而那次失敗長出這一輪的第二個發現

為了確認守門真的會紅，往 `apps/forseti-cli/northstar.py` 植入
`_CAMEL_PROBE = ("toolUse", "sessionId")`，**測試沒有紅**。
原因是 `_const_targets()` 第 3 個條件（`not t.id.startswith("_")`）
把底線開頭的常數整批排除，所以私有常數從來不是定義側的一員，
三種風格都一樣。換成 `CAMEL_PROBE`（不帶底線）才紅，
訊息是「Python 定義側出現駝峰列舉了：['sessionId', 'toolUse']」。

**一條恆綠的測試跟一條沒有守備的測試，在畫面上長得一模一樣。**
這個盲點在檔頭的盲點清單裡原本沒有。

於是補第四件：`private_exposure()`。真 repo 的量是
**3 個私有列舉常數、10 個成員**（`identity.py:696` 的 `_MARK`、
`lanes.py:50` 的 `_LABEL`、`ledger.py:62` 的 `_OWNER_EXIT`），
**而曝險是 0** —— 那 10 個每一個同時也是同檔某個公開列舉的成員
（`_MARK` 的鍵對 `STATES:128`、`_LABEL` 的鍵對 `KINDS:48`、
`_OWNER_EXIT` 的值對 `ALLOWED`），對照組還在，打錯照樣會紅。

**不要把「3 個常數沒被當成定義側」講成「10 個成員沒人守」。**
那是兩個數字，而前一句很容易被讀成後一句 —— 跟 `attr_names()`
裡那個「84 個成員」的更正是同一個形狀的錯誤，
`test_不要把常數個數讀成無人守的成員數` 釘住它們不准合併。

**此刻沒有順手把私有常數納入定義側**，因為曝險是 0：
改了不會多守到任何一個成員，只會多承擔一批沒量過的誤報風險。
曝險不再是 0 的時候 `test_私有常數的曝險此刻是0` 會先紅。

### 這一輪順帶量出下一步該做什麼

同一支 `js_enum_blocks()` 換上另外兩種形狀，`JS_DIRS` 底下有
**54 個 ALL_CAPS 區塊 258 個成員、19 個小寫區塊 149 個成員**，
全部此刻無人守（JS 只當白名單，不當定義來源 —— 檔頭盲點清單
本來就有這一條，只是先前沒有數字）。

**那是駝峰的 0 的一百倍以上。所以下一步是 JS 定義側，不是駝峰。**

先前寫在這裡的兩組數字（49/236 與 18/144）是用臨時腳本量的，
只掃 `src` 與 `desktop/ui`；真正的函式掃 `JS_DIRS`（多了 `tools`），
所以是 54/258 與 19/149。**已經用真正的函式重量並改掉**，
不是兩組都留著。

### 驗證結果

    python3 -m pytest tests/ -q
    1417 passed in 153.06s

上一輪 1403，這一輪 14 條新測試（駝峰 9 條、私有常數 5 條）。
`tests/test_literal_restate.py` 自己從 89 條到 103 條。

三個守門回傳碼都是 0：

    python3 tools/literal-restate-check.py --camel  → 0
    python3 tools/declared-only-check.py            → 0
    python3 tools/ui-render-check.py                → 0

植入的探針已還原，`git diff --stat apps/forseti-cli/northstar.py` 空的。

### 改掉兩處已經不成立的話

一，檔頭盲點清單的「駝峰命名兩種風格都不看。第三種風格還沒有人守」
換成帶兩側數字的版本，並寫明「不是欠判準，是沒有東西可守」
以及它的守門在哪。

二，同一份清單新增底線開頭常數那一條，機制與曝險兩個數字都寫上。

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。`git status` 顯示這三個是 `M`，
那是 HEAD 既有的漂移（NEXT.md 那 109 個裡的三個），不是這一輪造成的
—— 雜湊跟上一輪逐字元相同就是證據。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。`deploy.sh` 也沒有跑，因為沒有動畫面。

### 還缺什麼

- **JS 定義側（54 個 ALL_CAPS 區塊 258 個成員、19 個小寫區塊
  149 個成員）仍然無人守。這是這條線下一步最大的一項**，
  而它現在有數字了。要做得先決定一件事：JS 側同時是白名單來源，
  變成定義側之後那兩個角色會打架（一個字串在 JS 出現過，
  既是「別判紅」的理由，又會是「這是個成員」的來源）。
  **那個衝突怎麼解不是技術問題，先想清楚再動手。**
- 駝峰**不再是缺口**，這一輪的量測與守門取代了先前三輪那句話。
- 私有常數那一條曝險是 0，不必做；曝險變了測試會先紅。
- 相鄰對調沒有納入，所以 23 仍然是下界（跟上一輪同一條）。
- 那 23 條沒有任何處置，是政策決定，留給 owner（跟上一輪同一條）。
- 123 組小寫手打、141 組 ALL_CAPS 手打本身沒有動。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5z 同一條理由（B-15）。
- `B-17` 等 owner（`RAW_INLINE_LIMIT` 三種處置）。
- 污染登記簿仍然 5 筆全部 OPEN。收尾是狀態轉換，留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

### 附帶：上一輪那個沒解釋的 `should_write()` 觀察，這一輪補到缺的那一半

上一輪寫著「我沒有在呼叫 `snapshot()` 之前先問過 `should_write()`，
所以不知道那時是什麼狀態」，並且刻意沒把它寫成答案。

**這一輪先問了。** 實測序列：

    should_write() 先問  → False
    D.snapshot()         → 正常回傳（10 個鍵）
    D._write_handoff()   → None（沒寫）

而 `.forseti/NEXT.md` 的 mtime 從 06:14 動到 **06:32:28**，
內容裡這一輪兩個檔的雜湊也換成新的
（`tools/literal-restate-check.py` 從 `199a5bc3a3645431` 變
`f869cde8c99d4042`，`tests/test_literal_restate.py` 從
`7c2c2c6889e51942` 變 `321b01beda840416`，兩個都跟 `shasum` 逐字元對得上）。

**所以：`should_write()` 回 False 的時候，`snapshot()` 內部那一條
路徑照樣寫成了，而顯式呼叫 `_write_handoff()` 沒有。**
兩條路徑對節流門檻的反應不一樣。

**這只是一次觀察，不是那個機制的結論。** 沒有去讀
`snapshot()` 內部到底在哪一步寫、用的是不是同一個節流判斷 ——
沒讀就不寫成因果（v5.0 §8.3）。要當結論得有人去讀那段程式碼。

---

## 2026-09-17 06:5x　自動接續

### 挑了什麼

上一輪結尾自己留下的那件：「要當結論得有人去讀那段程式碼。」
挑它的理由是它完全不需要 owner 決定，而且它是上一輪自己標記為
未完成的唯一一件。**沒有碰 JS 定義側**，因為那一件卡的是
一個要先想清楚的角色衝突，不是工。

### 做完什麼

**一，去讀了，而且上一輪那個觀察的歸因是錯的。**

上一輪寫著「`should_write()` 回 False 的時候，`snapshot()` 內部那一條
路徑照樣寫成了」。讀完之後：`snapshot()`（`desktop_api.py:442`）
整支十三行，呼叫的是 `_blockers` / `_tasks` / `_continuity` /
`_reading` / `_ledger_health` / `_gauges` / `_overall` / `_advice`，
**沒有一條路通到 `handoff`**。

不只讀，還攔了一次。攔掉 `handoff.should_write` 與 `handoff.write`：

    snapshot() 期間攔到的呼叫: []
    strands() 期間攔到的呼叫: [('should_write', True), ('write', False)]
    real NEXT.md mtime before: 06:32:28
    real NEXT.md mtime after : 06:32:28

**唯一的寫入點是 `strands()` 尾段的 `_write_handoff(snap)`
（`desktop_api.py:3418`）。** mtime 從 06:14 動到 06:32:28，
是那一輪另外走過 `strands()`，不是 `snapshot()`。

**二，「兩條路徑對節流的反應不一樣」也不成立。** 節流不是兩套，
是同一條路上被問兩次（`desktop_api.py:1779` 外層、`handoff.py:265` 內層），
兩次都對同一個預設 `OUT`。`_write_handoff()` 不收 path 參數，
所以兩層問的永遠是同一個檔案。

**三，一條新測試把歸因釘住。**
`tests/test_handoff.py::test_snapshot不寫交接檔寫的只有strands`。
先前那條 `test_必要欄位每一個上游都真的有供` 守的是
「`strands()` 會寫」那一半，**沒有人守「`snapshot()` 不寫」那一半** ——
而錯掉的正是沒人守的那一半。

**四，§40 登記一筆。** `pol-5fd00d9bc0`，狀態 OPEN，
`regression_probe` 指著上面那條測試。
登記簿 5 筆 → **6 筆**，`guarded` 2 → **3**。

### 驗證結果

反向驗證做了，而且是這一輪唯一真正證明測試有守備的動作。
把 `_safe(lambda: _write_handoff(snap), None)` 植進 `snapshot()` 尾段：

    AssertionError: snapshot() 發了交接指令
    [('should_write', None), ('write', False)]。
    它先前不發，所以節流的語意是照 strands() 的呼叫頻率設計的。
    要搬過去得先重新決定 MIN_GAP_S，不是把這條測試調鬆

探針已還原。`desktop_api.py` 雜湊植入前 `be007c60ea0badce`、
還原後 `be007c60ea0badce`，逐字元一致，`grep -c _PROBE_` 回 0。

全套測試 1417 → **1418 全綠**（138.66 秒）。

三個守門回傳碼都是 0：

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
`deploy.sh` 沒有跑，因為沒有動畫面。

### 還缺什麼

- **`pol-5fd00d9bc0` 是 OPEN，沒有推到 RESOLVED。** 推它是一次
  狀態轉換，留給 owner，跟系統不自己收尾同一條理由。
  登記簿現在 6 筆全部 OPEN。
- **JS 定義側仍然無人守**（54 個 ALL_CAPS 區塊 258 個成員、
  19 個小寫區塊 149 個成員），仍然是這條線最大的一項。
  仍然卡在同一個點：JS 側同時是白名單來源，變成定義側之後
  兩個角色會打架。**那個衝突怎麼解不是技術問題，先想清楚再動手。**
  這一輪刻意沒動它。
- 這一輪只讀了 `snapshot()` 與 `strands()` 兩支的呼叫關係，
  **沒有去讀 `_write_handoff()` 以外還有沒有別的東西會動 `.forseti/`
  底下的檔案**。攔截只攔 `handoff` 這一個模組，所以
  「`snapshot()` 完全不寫任何檔案」這句話**沒有被驗過**，
  這一輪也沒有寫成結論。
- 相鄰對調沒有納入，所以 23 仍然是下界（跟前兩輪同一條）。
- 那 23 條沒有任何處置，是政策決定，留給 owner。
- 123 組小寫手打、141 組 ALL_CAPS 手打本身沒有動。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5aa 同一條理由（B-15）。
- `B-17` 等 owner（`RAW_INLINE_LIMIT` 三種處置）。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

### 這一輪自己犯的兩件，寫在這裡不是補充是證據

**一，時間是估的。** 這一份與 ROADMAP 5ab 的標題原本寫 `07:0x`，
收尾時跑 `date` 拿到的真值是 **06:50:23**，兩份 `.md` 已改成 `06:5x`。
**`.forseti/pollution.jsonl` 裡 `pol-5fd00d9bc0` 的 `verifier` 欄位
仍然寫著「2026-09-17 07:0x」**，那是錯的時間。沒有去改，
因為那個檔是 append-only（`pollution._append` 用 `"a"` 開檔，
狀態變更走 `advance()`），為了一個時間字串去改寫帳本正本，
代價比留著一筆寫明的錯誤大。**留著，並且在這裡標明。**

**二，`handoff.py:47` 那行註解是過期的。** 它寫著用法是

    handoff.write(desktop_api.strands(''), force=True)

這一輪照著跑，被擋下來：

    [handoff] 拒絕寫入 …/.forseti/NEXT.md：不是一份交接狀態，
    少了 artifact_lines、at、awaiting_finish、…（共 15/15 個）

`strands()` 的回傳**不是**一份交接狀態，形狀守門（`missing_keys`）
會全數擋掉 —— 而那個守門正是後來加的，
`test_把strands的快照餵進來要擋掉` 就是釘它的。
**註解停在守門加上去之前。** 這一輪沒有改那行註解，
因為改它要先決定正確的用法該寫什麼（`_write_handoff()` 是唯一產生者，
而它是私有的，沒有對外的等價呼叫），那是一個設計決定不是筆誤。
**列在這裡給下一輪，不要再照那行跑一次。**

**附帶：這一次又看到同一個形狀。** 顯式呼叫回 `ok: False`，
而 `.forseti/NEXT.md` 的 mtime 照樣從 06:45:12 動到 06:50:07。
**這一次知道為什麼**：`D.strands('')` 這個參數在被當成參數算出來的時候，
內部就已經走過 `_write_handoff(snap)` 寫成了，
外面那個顯式 `HO.write(...)` 才被形狀守門擋掉。
跟上一輪那個觀察是同一個成因，只是上一輪擋它的是節流、這一輪是形狀。
**所以那個「顯式呼叫沒寫成但檔案動了」的現象，兩次都不是兩條路徑，
是一次內部寫入加一次被擋掉的外部呼叫。**

---

## 2026-09-17 07:1x　`.forseti/` 這個目錄到底被誰寫過

### 這一輪挑了什麼，為什麼

上一輪自己在這份檔案裡寫下一個缺口：

    攔截只攔 `handoff` 這一個模組，所以
    「`snapshot()` 完全不寫任何檔案」這句話**沒有被驗過**，
    這一輪也沒有寫成結論。

挑它，因為它是上一輪自己標明沒驗的一句話，不需要 owner 決定，
不動畫面，而且驗得出真假。ROADMAP 那項最大的（JS 定義側）仍然
卡在「JS 側同時是白名單來源，兩個角色會打架」這個不是技術問題的點，
這一輪一樣沒動它。

### 做完什麼

攔截點從模組名往下搬到寫入動作本身，攔四種：`builtins.open`
的寫模式、`Path.write_text`、`Path.write_bytes`、`Path.replace`。

`snapshot()` 在 `.forseti/` 底下 **0 次寫入**，上一輪那句話成立。
**但它的前提錯了** —— `handoff` 不是唯一的寫入者。同一次量測
`strands()` 寫 4 次、3 個相異位置：`NEXT.md`、
`cache/artifact_hashes.json`、`cache/identity.json`（經 `.tmp` 再 replace）。
讀原始碼數出一共三支在寫 `cache/`：`identity.py:253`、
`blast.py:385`、`contract.py:523` 加 `contract.py` 的 `recheck.json`。

新增 `tests/test_forseti_dir_writes.py`，三條。

### 驗證結果

    python3 -m pytest tests/ -q     → 1421 passed，0 failed（149.96s）

上一輪是 1418，加三條。三個守門回傳碼都是 0：

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

反向驗證四次，每次都先看到紅再還原：

    探針植進 snapshot() 尾段          → 第一條紅
    探針植進 strands() 的 _write_handoff 前 → 第二條紅
    拿掉 Path.replace 攔截             → 體檢那條紅
    整張網全瞎（四種都不攔）           → 當時的非空斷言紅

`desktop_api.py` 雜湊 `be007c60ea0badce`，四次植入前後逐字元一致。

### 這一輪自己犯的一件，寫在這裡不是補充是證據

**第一版的非空斷言是錯的，而且是靠整套測試才抓到的。**
我寫「`strands()` 期間零次寫入就代表網瞎了」，單獨跑綠，
整套跑紅。紅的原因不是壞了，是**零次本來就是合法狀態**：
`handoff.write()` 過不了 `MIN_GAP_S = 240` 就不寫（`handoff.py:265`），
三支快取內容沒變就不寫。同一個行程連跑三次實測：

    第 1 次 strands()：2 次 → identity.json.tmp、identity.json
    第 2 次 strands()：0 次
    第 3 次 strands()：0 次

**機制：拿「我剛才量到的那一次」當成「它每次都會這樣」。**
量測是在一個乾淨行程裡做的，快取冷、節流過期，
而測試跑在一個已經跑過三十條測試的行程裡，兩個前提不一樣。
一次觀測被當成不變量寫進斷言。
**已改掉**，分「真的沒寫」跟「網瞎了」的責任移到體檢那一條，
它自己造三種寫法出來，不依賴 `strands()` 這一輪的心情。

### 順帶查清楚的一件

**`strands()` 不呼叫 `snapshot()`。** 探針植進 `snapshot()` 尾段之後
`strands()` 那條測試仍然綠，而 2964 到 3430 行整支本體
grep `snapshot()` 是 0 處。兩個是獨立入口。
先前沒有任何一份文件講過這件事，而
「`strands()` 內部應該包含 `snapshot()`」是很自然會有的預設。

### 一個 grep 會給出反面答案的地方

全檔 `os.replace` 與 `os.rename` 是 **0 處**，所以照 `os.` 去找
會得到「沒有人用 replace」。實際用的是 `Path.replace` 方法
（`identity.py:290`、`blast.py:422`）。第一版攔截網就是這樣漏掉的，
而漏掉的症狀是**測試變成永遠綠**，不是報錯。

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
`deploy.sh` 沒有跑，因為沒有動畫面。

### 還缺什麼

- **`snapshot()` 零寫入只驗了 `.forseti/` 這個目錄底下。**
  它會不會寫 repo 其他地方、或家目錄底下的東西，這一輪沒有量，
  也沒有寫成結論。攔截網本身蓋得到（它攔的是動作不是路徑），
  只是判定條件寫死在 `.forseti/` 之下。
- **`_WriteSpy` 不攔 `shutil`。** 讀過全檔只有 `which` 與
  `rmtree(tmp)` 四處（`goalgate.py`、`jsbridge.py`），沒有一處寫進
  這個目錄，所以這是決定不是遺漏 —— 但哪天有人用 `shutil.copy`
  寫進來，這張網看不到。已寫在 `_WriteSpy` 的 docstring 裡。
- **`test_snapshot在forseti底下一個檔案都不寫` 自己有弱點**：
  它斷言「沒攔到東西」，網瞎掉時會無聲通過。擋這件事的是同檔的
  體檢那一條。那一條刪掉，這一條就變成永遠綠的裝飾品。
  已寫在它自己的 docstring 裡。
- **`pol-5fd00d9bc0` 仍然是 OPEN**，登記簿 6 筆全部 OPEN。
  推到 RESOLVED 是狀態轉換，留給 owner。
- **JS 定義側仍然無人守**（54 個 ALL_CAPS 區塊 258 個成員、
  19 個小寫區塊 149 個成員），仍然是這條線最大的一項，
  仍然卡在同一個點。**那個衝突怎麼解不是技術問題。**
- `handoff.py:47` 那行過期註解仍然沒改（上一輪列出的），
  改它要先決定正確用法該寫什麼，是設計決定不是筆誤。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5ab 同一條理由（B-15）。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

## 2026-09-17 07:3x　上一輪寫下的缺口補掉了，量的時候撞到一個一直在漏的東西

### 挑了什麼

上一輪在這份檔案自己留的第一條缺口，原話：

    `snapshot()` 零寫入只驗了 `.forseti/` 這個目錄底下。
    它會不會寫 repo 其他地方、或家目錄底下的東西，這一輪沒有量，
    也沒有寫成結論。攔截網本身蓋得到（它攔的是動作不是路徑），
    只是判定條件寫死在 `.forseti/` 之下。

所以這一輪做的是把判定範圍放寬，不是重寫攔截網。
`_WriteSpy.__init__` 多一個 `scope`，`None` 代表整個檔案系統，
四個 hook 一行都沒動 —— 上一輪說「它攔的是動作不是路徑」這句話成立。

### 量出來的結果，以及量的時候看到的另一件事

乾淨行程連跑三次，`snapshot()` 全檔案系統範圍都是 **0 次寫入**。
上一輪那句話成立。**同一次量測看到 `strands()` 每一輪都在
`.forseti/` 外面寫四個檔**，而上一輪只看得到目錄內：

    $TMPDIR/forseti-js-*/{run.mjs,payload.json}    jsbridge.py:186
    $TMPDIR/forseti-gac-*/{run.mjs,payload.json}   goalgate.py:233

這兩支都有 `finally: shutil.rmtree`（`jsbridge.py:202`、
`goalgate.py:249`），寫完就收。**而 `blast.py` 的兩支沒有。**
去 `$TMPDIR` 底下數：

    forseti-blast-*     2732 個
    forseti-blast-d-*   2981 個
    合計 5713 個，逐個比對內容形狀，異常 0 個

不是整潔問題。`vectors()` 每次指紋變了就走一次，指紋每一輪都可能變，
所以它隨開發時間線性成長。清掉的時候 `$TMPDIR` 有 57575 個項目。

### 做完什麼

**修：`blast.py` 兩支各補一個 `finally: shutil.rmtree(tmp, ignore_errors=True)`**
（`vectors()` 與 `detail()`），`import shutil` 一行。形狀照
`jsbridge.py:202` 與 `goalgate.py:249`，不自創一套。
放 `finally` 不放 try 尾巴，是因為這四支都有提早 return 的路徑
（`TimeoutExpired`、`OSError`），而 node 逾時正是最需要收的那一次。

**四條新測試：**

`tests/test_tempdir_cleanup.py` 三條。兩條行為測試各開一個最小 repo
（`src` 用符號連結指回真的那份，不複製 15MB），保證快取落空才走得到
`mkdtemp`，比對前後目錄數。第三條是原始碼層級的 ast 掃描：
`apps/forseti-cli` 底下每一個 `mkdtemp` 站點，同一支函式裡要有
`finally` 收 —— 行為那兩條只數 `forseti-blast-` 這兩個前綴，
蓋不到哪天新增的第五支。

`tests/test_forseti_dir_writes.py` 一條，全檔案系統範圍的
`snapshot()` 零寫入。**它沒有取代 `.forseti/` 那一條**：那一條講的是
控制目錄這個特定語意（`MIN_GAP_S` 當初要擋的事），這一條講的是
「它根本不落地」。

**清掉 5717 個目錄，實際釋出 57.2MB。** 逐個檢查內容形狀，
只刪 `{run.mjs, payload.json}` 這個形狀的，跳過 0 個。

### 這裡有兩個大小數字，量的不是同一件事

`du -shc` 報 84MB，實際刪掉釋出 57.2MB。**兩個都是真的**：
差額是 5713 個目錄本身的配置區塊。第一版把 84MB 寫進程式碼註解與
測試 docstring，等於把配置量講成內容量，**已更正，兩個數字都留著
並寫明各自量的是什麼**。

### 反向驗證五次，全部紅過再還原

    整支修回退掉                → 三條全紅
    只拿掉 detail() 那個 finally → 兩條紅、vectors() 那條仍綠
    把 ast 掃描弄瞎（改屬性名）  → 非空斷言紅
    探針植進 snapshot() 尾段寫 $TMPDIR → 新那條紅、.forseti 那條仍綠
    （最後這次同時證了新那條嚴格強過舊那條）

`desktop_api.py` 雜湊 `be007c60ea0badce`，植入前後逐字元一致。
`blast.py` 是這一輪**刻意改的**，所以它的雜湊本來就會變。

### 這一輪自己犯的兩件

一，**測試第一版用了 `v["vectors"][0]["file"]` 這個不存在的鍵**，
`vectors()` 回的是 `top` 裡面裝 `{target, vector}`。沒有先印過回傳值
就照「函式叫 vectors 所以回傳裡有 vectors」寫下去。跟 §40
`pol-5fd00d9bc0` 那一筆同一個機制：拿名字當成內容的證據。
抓到它的是測試自己紅，不是我讀出來的。

二，**ast 掃描沒濾 `._*.py`**，exFAT 上的 AppleDouble 附屬檔讀下去是
`UnicodeDecodeError`。這個 repo 六處早就在濾了
（`desktop_api.py:2603`、`ledger.py:825`、`jsbridge.py:74` 等），
我沒有先看既有寫法就自己寫一份。已照既有形狀改。

### 測試數與守門

1421 → **1425 全綠**（157.79 秒）。三個守門回傳碼都是 0：

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，三個都是這一輪收尾時實際量的，
跟上一輪紀錄逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 還缺什麼

- **`tools/` 底下三個 `mkdtemp` 站點沒有納入守門**
  （`ui-harness.py:153`、`ui-render-check.py:370`、`probe-stress.py:105`）。
  那三支是一次性的開發工具，產出本來就是要給人看的，
  所以這是**決定不是遺漏** —— `$TMPDIR` 底下 42 個 `forseti-ui-`
  與 9 個 `forseti-render-` 是刻意留著的。哪天有人把它們接進輪詢路徑，
  這個決定要重做。ast 那條測試的掃描範圍寫死在 `apps/forseti-cli`。
- **`blast.py` 的 `_cache_file()` 寫在哪裡，這一輪沒有量。**
  臨時 repo 那邊它寫在 repo 底下（測完跟著 box 一起刪），
  真的 repo 那邊寫 `.forseti/cache/`（白名單內）。**沒有第三種情況
  被驗過。**
- `_WriteSpy` 仍然不攔 `shutil`。這一輪讓 `shutil.rmtree` 的站點從
  兩處變四處，全部是刪不是寫，所以決定不變，但 docstring 的
  站點列舉已跟著更正。
- **§40 這一輪沒有登記。** 上面那兩件自己犯的錯，錯的是我這一輪的
  草稿，不是任何一份文件裡留下來的斷言 —— 登記簿收的是
  「已經被推翻的結論」，把草稿塞進去會讓那六筆的份量被稀釋。
  仍然 6 筆全部 OPEN，推到 RESOLVED 是狀態轉換，留給 owner。
- **JS 定義側仍然無人守**（54 個 ALL_CAPS 區塊 258 個成員、
  19 個小寫區塊 149 個成員），仍然是這條線最大的一項，
  仍然卡在同一個點：JS 側同時是白名單來源，兩個角色會打架。
  **那個衝突怎麼解不是技術問題。**
- `handoff.py:47` 那行過期註解仍然沒改（要先決定正確用法該寫什麼）。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5ac 同一條理由（B-15）。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

## 2026-09-17 08:0x　`_cache_file()` 寫在哪裡量了,答案推翻我自己讀出來的結論

### 挑了什麼

上一輪自己在「還缺什麼」寫下的那一句,原話:

    `blast.py` 的 `_cache_file()` 寫在哪裡,這一輪沒有量。
    臨時 repo 那邊它寫在 repo 底下(測完跟著 box 一起刪),
    真的 repo 那邊寫 `.forseti/cache/`(白名單內)。
    **沒有第三種情況被驗過。**

挑它是因為它是上一輪留下的缺口裡**唯一不卡 owner** 的一項。
JS 定義側那一項更大,但它卡在「JS 側同時是白名單來源」這個衝突,
那不是技術問題。

### 這一輪我自己錯了兩次,兩次都是實測把我推翻的

**第一次。** 讀 `blast.py:458` 看到
`fp = _fingerprint(...) if base == REPO else None`,
當場下結論「這個模組結構上不可能寫到 REPO 以外的地方,第三種情況
不存在」。**錯。** 那道閘只在 `collect()` 上。`vectors()`(`:615`)
與 `detail()`(`:838`)是同一行形狀:

    fp = g.get("fp") or _fingerprint(base, python_files(base), g["js_files"]) or ""

`g["fp"]` 在非正本是 None,於是走 `or` 那一邊**自己補算一個真的指紋**,
接著 `_cache_put(base, ...)`(`:750`、`:935`)就寫出去了。
機制跟 §40 `pol-c3...` 那一筆同一種:讀到一個函式裡的閘,
就當成整個模組有那道閘。中間缺的那一步是去讀另外兩支。

**第二次,而且這次更危險。** 為了驗第一個結論,開了一個臨時 box 實測,
`vectors()` 之後快取檔不存在 —— 差一點就把它寫成「量過了,不會寫」。
實際是那個 box 的 `src/` 是空目錄,`blast.py:606` 那條
`if not n or not src.is_dir()` 的下一步是 node 跑 `cost.js` 跑不到,
`returncode != 0` 提早 return,**根本沒走到寫快取那一行**。
零次寫入在這裡是假陰性。抓到它的是「為什麼 has 沒印出來」這個疑問,
不是我讀出來的。

### 量出來的答案

`src` 照 `test_tempdir_cleanup.py` 既有做法符號連結回真的那份之後重測:

    collect(box)                 → fp=None,快取檔不存在
    vectors(root=box)            → 快取檔出現,keys=['vectors|8|ALL']
    detail(..., root=box)        → keys 多一筆 detail|...
    再呼叫一次兩支              → cached 都是 True

**所以第三種情況存在,而且是活的不是死碼。**
`_cache_file()` 寫的位置**完全由呼叫端的 `root` 決定**。
測試裡它剛好是 `tmp_path` 所以跟著 box 一起被清掉 ——
**「剛好會被清掉」不是「不會寫出去」**,而先前只有前者被觀察到。

生產端那一側另外量過:`desktop_api.py:2235` 與 `:3157` 兩個呼叫點
都不傳 `root`,`root=` 在整個 repo 只出現在 `tests/test_blast.py`
與 `blast.py:941` 自己。所以線上路徑 base 恆等於 REPO。

### 這一輪不改行為

`blast.py:613` 與 `:836` 的註解寫著「臨時 repo 那邊 `collect()`
不算指紋,所以這裡自己補一次」—— **這是刻意的**,為的是讓臨時 repo
也吃得到快取,`test_blast.py` 幾十條都靠它跑得快。
加閘會讓那些測試變慢,而那是設計決定不是這一輪該自己做的。
**只把行為釘住,不改政策。**

### 順帶一個發現,刻意不動它

`test_blast.py` 的 `test_不是正本就不寫快取檔` 這個名字比它驗的事大:
它只呼叫 `collect()`,而同一個臨時 repo 上 `vectors()` 與 `detail()`
寫的正是它斷言不存在的那個檔。那條測試沒有錯,是名字收不住。
**沒有改名**,因為改名會讓 `git log` 看起來像修了一個 bug。
新檔裡 `test_不是正本這件事三支函式的答案不一樣` 就是擋這個誤讀的。

### 做完什麼

**新檔 `tests/test_blast_cache_location.py`,4 條。** 三條行為
(三支函式答案不一樣、快取是活的、寫非正本不會順手動到正本),
一條原始碼層級的 ast:`_cache_file` 的函式體裡要出現 `base`、
不准出現 `REPO`。**那一條存在的理由是行為那三條在沒有 node 的機器上
會因為提早 return 而無聲通過** —— 就是我這一輪踩到的那個假陰性。

**量測順帶露出第二個缺口,一併補掉。** 為了確認 `blast_detail()`
這條路寫了什麼,逐個實測 `desktop_api.main()` 分派表的 20 個指令。
先前 `.forseti/` 寫入守門只看 `snapshot()` 與 `strands()` 兩個入口,
**另外十八個沒有任何測試在看**。而 `blast_detail()` 冷快取時
寫的正是 `.forseti/cache/blast.json` 與它的 `.tmp`,
那兩次寫入先前一條測試都沒有看過(它不在 `strands()` 那條路上)。

`tests/test_forseti_dir_writes.py` 加 18 條:一條從語法樹讀
`main()` 的分派表,要求每個指令都被分類進 `READ_ONLY_CMDS` 或
`STATE_CHANGING_CMDS`;十七條 parametrize,每個唯讀指令各問一次
「有沒有寫出白名單以外的東西」。
`act` / `note_add` / `fork` 三個會改變狀態的**一個都不跑** ——
收尾任務、留粉紅點、開新 session 檔都是 owner 按下去才該發生的事,
一條測試不該替她按。

分派表覆蓋那一條是另外十七條的前提:沒有它,新增一個會寫控制檔的
指令只要不加進清單,整組會繼續全綠,那正是「白名單跟著長」的形狀。

### 十七個唯讀指令的實測數字

    snapshot 0、sessions 0、spec_reading 0、block_reading 0、
    sufficiency 0、machine 0、work 0、pollution 0、workflow 0、
    identity 0、sot 0、timeline 0
    strands 8(4 個 $TMPDIR + cache/identity.json{,.tmp} +
               cache/artifact_hashes.json + NEXT.md)
    audit 8(全部在 $TMPDIR,forseti-js-* 與 forseti-gac-* 各兩組)
    features 2、selftest 2
    blast_detail 冷 4、熱 0

`features` 與 `selftest` 那兩個用的是 `TemporaryDirectory()`
上下文管理器(`desktop_api.py:2685`、`:2707`),自己收,
**不是 `mkdtemp`** —— 所以上一輪那條 ast 守門只掃 `mkdtemp` 站點
這個範圍是對的,不是漏掉這兩處。這件事是查過原始碼才寫的,不是推的。

### 反向驗證五次,全部紅過再還原

    vectors/detail 的 `or _fingerprint` 退路拿掉 → 新檔 2 條紅
    `_cache_file` 的 base 換成 REPO            → 新檔 3 條紅(行為+ast)
    `_cache_file` 改名                          → ast 那條紅
    分派表塞一個沒分類的指令                   → 覆蓋那條紅(missing)
    分派表拿掉一個仍列在分類裡的               → 覆蓋那條紅(stale)
    在 blast_detail 路徑上種一個白名單外的寫入 → **只有 blast_detail
      那一格紅,另外 16 格仍綠**(證了 parametrize 真的逐個隔離)

`blast.py` 還原後雜湊 `bfa00a27840f75e5`、
`desktop_api.py` 還原後 `be007c60ea0badce`,兩個都跟植入前逐字元一致。
種進 `.forseti/` 的探針檔 `_probe_reverse.json` 已刪,確認不存在。

### 測試數與守門

1425 → **1447 全綠**(175.37 秒)。22 條新的 = 4 + 18,對得起來。

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 沒有動畫面,所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`,三個都是這一輪收尾時實際量的,
跟上一輪紀錄逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 還缺什麼

- **`vectors()` / `detail()` 對非正本寫快取這件事,只釘住沒有決定。**
  行為現在有人守了,但「該不該讓一個函式往呼叫端指定的目錄寫東西」
  這個問題沒有答案。改的話 `test_blast.py` 幾十條會變慢,
  **那是取捨不是 bug**,留給 owner。
- **`_cache_put()` 的 `except OSError: return` 是靜默吞掉。**
  寫失敗不算錯誤這件事檔頭自己寫明了,但失敗次數沒有任何地方看得到。
  這一輪沒有量它實際失敗過幾次,**也沒有寫成結論**。
- **`STATE_CHANGING_CMDS` 那三個仍然沒有任何寫入守門。**
  它們本來就該寫,所以白名單那套問法不適用 ——
  要守的是「寫的是不是只有該寫的那幾筆」,那是另一種測試,
  這一輪沒做。
- **`timeline` 那一格用的是 `TK.latest_session()`,也就是這條 session
  自己。** 換一條 session 會不會有別的寫入路徑,沒有量。
- JS 定義側仍然無人守(54 個 ALL_CAPS 區塊 258 個成員、
  19 個小寫區塊 149 個成員),仍然是這條線最大的一項,
  仍然卡在「JS 側同時是白名單來源,兩個角色會打架」。
  **那個衝突怎麼解不是技術問題。**
- `handoff.py:47` 那行過期註解仍然沒改。
- 沒有進 `deploy.sh` 的守門,跟 5m 到 5ad 同一條理由(B-15)。
- §40 這一輪**沒有登記**。上面那兩次錯的是我這一輪的草稿,
  不是任何一份文件裡留下的斷言 —— 登記簿收的是
  「已經被推翻的結論」,把草稿塞進去會稀釋那六筆的份量。
  仍然 6 筆全部 OPEN,推到 RESOLVED 是狀態轉換,留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`,全部仍然在等 owner。
- ROADMAP P0 第 1 項(真的救回一次)仍然卡在 owner 要按的那一步。

沒有 commit。

---

## 2026-09-17 08:1x-08:3x　自動接續

### 挑了什麼

上一輪自己在這份紀錄裡寫下的兩件之一：

    `STATE_CHANGING_CMDS` 那三個仍然沒有任何寫入守門。
    它們本來就該寫，所以白名單那套問法不適用 ——
    要守的是「寫的是不是只有該寫的那幾筆」，那是另一種測試，
    這一輪沒做。

### 做之前先量，而量測推翻了兩件事

**一，攔截網瞎掉一半。** `tests/test_forseti_dir_writes.py` 的 `_WriteSpy`
攔 `builtins.open`、`write_text`、`write_bytes`、`Path.replace` 四種，
**沒有攔 `Path.open`**。Python 3.9.6 實測：換掉 `builtins.open` 之後
執行 `p.open("a")`，攔到 0 次，而檔案確實寫出去了。這個 repo 底下
用這種寫法的有 13 處，`grep -rn '\.open("[wax]' apps/forseti-cli/*.py`
數出來的：

    advicetrack.py:102   blockread.py:165   checkpoint.py:79
    commit.py:81         coverage.py:294    event_ledger.py:351
    forkline.py:178      gate.py:101        identity.py:499
    notes.py:67          pollution.py:195   sufficiency.py:313
    workflow.py:307

**粉紅點、checkpoint、事件帳本、fork 寫新 session 檔，四個全部在名單上。**
所以補這一種之前，那個檔案裡每一條「零寫入」斷言，證到的都比它們宣稱的少。

補寬之後原本那 22 條**仍然全過**，也就是說 `snapshot()` 的零寫入是真的，
不是網看不到 —— 這一點是補完網才知道的，補之前講不出來。

**二，第一次量 `fork_at` 量到 0 次寫入，是假陰性。** `fork_at` 要的是
bare session id，而 `TK.latest_session()` 回的是完整路徑，所以它在
`desktop_api.py:1702` 那個 glob 就 return 了，根本沒走到寫檔那行。
跟上一輪 `vectors()` 撞到的是同一個形狀：**提早 return 的零，
跟「它不寫」的零長得一模一樣。**

### 沒有寫成結論的一件

量的時候看到 `commit.jsonl` 每輪往新的臨時目錄寫 5 次，本來像是
`blast.py` 那 5713 個沒人收的目錄同一種洩漏。讀了 `probe.py:293`
之後不是：它走 `tempfile.TemporaryDirectory()` 上下文管理器，自己收。
**所以這一條不登記、不寫進 ROADMAP。**

### 做完什麼

`tests/test_forseti_dir_writes.py` 加第五種 hook（`Path.open` 寫模式）
與 `paths()`，另加 2 條自我測試：一條要求網攔得到 `Path.open`，
一條釘住「`builtins.open` 攔不到 `Path.open`」這個前提本身 ——
哪天 Python 改了行為，該刪的是後面那條，不是 hook。22 → 24。

新檔 `tests/test_state_changing_writes.py` 12 條，守那三個指令：

- **覆蓋率** 1 條：`STATE_CHANGING_CMDS` 多一個而這裡沒守就紅。
  沒有它的話，新增的指令只要被分進那一組就完全沒有人看。
- **note_add** 2 條：先釘住 `notes.LOG` 預設在 `.forseti/notes.jsonl`
  （不釘的話搬走常數這件事本身不誠實），再驗寫一則注記
  全檔案系統只動那一個檔、只有一行、`provenance` 是 `HUMAN_ADJUDICATION`。
- **act checkpoint** 2 條：同樣先釘位置，再驗按一次只落一筆
  （`OWNER_MARK` + `last_good`）、`.forseti/` 底下沒有白名單以外的東西、
  **任務帳本一個位元組都不動**（這一支在開帳本之前就 return）。
  刻意不斷言 `NEXT.md` 一定被寫 —— `MIN_GAP_S` 沒到就不寫，零次合法。
- **fork** 3 條：走 `forkline.fork()` 餵臨時目錄裡自己造的 session，
  不走 `fork_at`（它只認 `~/.claude/projects/`，在那裡造檔會讓一條
  假 session 出現在她的側邊欄）。乾跑 0 次寫入；真跑只寫 `dest`
  而且**原檔逐位元組不動** —— `forkline.py` 檔頭那句話先前只是註解；
  再加一條從語法樹讀分派表，要求 `dry_run` 由 `--go` 決定。
- **act 其餘四種** 4 條 parametrize：空 target 被拒絕的時候不准留下痕跡。

實測數字：乾跑 0 個相異位置，真跑 1 個；`add_note` 1 次 `Path.open:a`；
`act("checkpoint")` 在 `.forseti/` 底下只動 `cache/identity.json{,.tmp}`。

### 反向驗證五次，全部紅過再還原

1. 拿掉 `Path.open` hook → 攔截網自我測試與粉紅點那條都紅
2. 讓乾跑也寫檔 → `test_fork乾跑一個位元組都不寫` 紅
3. 讓 fork 順手碰原檔 → 原檔那條紅
4. `STATE_CHANGING_CMDS` 加第四個名字 → 覆蓋率那條紅
5. 讓 `act("checkpoint")` 多寫一個 `.forseti/_probe.txt` → act 那條紅

還原後 `desktop_api.py` `be007c60ea0badce`、`forkline.py` `5612e0dda9244108`、
`tests/test_forseti_dir_writes.py` `ccf90d573d19be16`，植入前後逐字元一致。

### 測試數與守門

1447 → **1461 全綠**（166.53 秒）。14 條新的 = 2 + 12，對得起來。

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `c0829f44069780b2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `66ae8cf855a8f6f5`，這一輪收尾時實際量的，跟上一輪逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 還缺什麼

- **那 13 個 `Path.open` 寫入點，只有 `notes`、`checkpoint`、`forkline`
  這三支被走過。** 另外十支（`advicetrack`、`blockread`、`commit`、
  `coverage`、`event_ledger`、`gate`、`identity`、`pollution`、
  `sufficiency`、`workflow`）這一輪只確認網攔得到那種寫法，
  **沒有逐個量它們實際寫到哪裡**，也沒有寫成結論。
- **`_cache_put()` 的 `except OSError: return` 仍然是靜默吞掉。**
  上一輪就寫下來了，這一輪順延，理由是先補網比較急 ——
  網瞎著的時候量出來的任何數字都不能用。**連續兩輪順延，記在這裡。**
- **`vectors()` / `detail()` 對非正本寫快取**，只釘住沒有決定，
  跟上一輪一樣是取捨不是 bug，留給 owner。
- `timeline` 那一格用 `TK.latest_session()`，換一條 session 會不會有
  別的寫入路徑，仍然沒有量。
- JS 定義側仍然無人守（54 個 ALL_CAPS 區塊 258 個成員、19 個小寫區塊
  149 個成員），仍然是這條線最大的一項，仍然卡在「JS 側同時是
  白名單來源，兩個角色會打架」。**那個衝突怎麼解不是技術問題。**
- `handoff.py:47` 那行過期註解仍然沒改。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5ae 同一條理由（B-15）。
- §40 這一輪**沒有登記**。上面那兩次錯（只讀一道閘就下結論、
  假陰性的零）是這一輪自己的草稿，不是任何文件裡留下的斷言。
  仍然 6 筆全部 OPEN，推到 RESOLVED 是狀態轉換，留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

---

## 2026-09-17 09:0x　那個連續兩輪被順延的靜默吞掉，結了

### 挑了什麼，為什麼挑它

上一輪自己寫下的兩件裡的第二件：

    `_cache_put()` 的 `except OSError: return` 仍然是靜默吞掉。
    上一輪就寫下來了，這一輪順延，理由是先補網比較急。
    **連續兩輪順延，記在這裡。**

順延的理由這一輪沒了（5af 已經把攔截網補寬），所以先量它。

### 先量再做，量出來的東西比預期嚴重

臨時 repo 的 `.forseti/cache/` chmod 0o500，連呼叫 `vectors()` 兩次：

| | 正常 | 快取目錄唯讀 |
|---|---|---|
| 第一次 `cached` | False | False |
| 第二次 `cached` | **True** | **False** |
| 回傳的鍵數 | 36 | 36（一個都沒少） |
| 兩次答案 | 相同 | 相同 |
| 有沒有欄位講到寫失敗 | 不適用 | **沒有** |

所以「這一次剛算，下一次會命中」跟「永遠寫不進去，每一次都重算」
在呼叫端**逐欄位一模一樣**。分不出來的那兩件事後果相反：
前者是一次成本，後者是每一次都付。

順帶量到的代價沒有想像中大：熱快取 0.003 秒，重算 0.049 到 0.070 秒。
**寫出來是因為它推翻了「這個洞很貴」這個直覺** —— 它貴在分不出來，
不貴在那幾十毫秒。

### 做了什麼

`_cache_put()` 從回 `None` 改成回狀態字串，四種：`ok`、`skipped`、
`not_attempted`、`failed:<例外類別>`。**不帶例外訊息** ——
訊息裡有絕對路徑，那會跑到畫面上。三支公開函式
（`collect` / `vectors` / `detail`）把它跟一句人話帶進回傳字典。

**政策一個位元組都沒改**：寫不進去仍然不丟例外、仍然照常回答、
答案仍然正確。改的只是它說不說。改政策（寫不進去就報錯、或改寫別處）
是設計決定，不是這一輪該自己做的。

賦值一律在 `_cache_put()` **之後**，所以存進快取檔的那一份不帶這兩欄。
帶的話等於把某一次的寫入狀態凍進檔案，下一次命中讀回來會像是此刻的狀態。

畫面那一側：`.blast` 那一格先前只畫得出兩種狀態（有「快取」標、
沒有標），而資料裡有四種。加一個警告色的「快取寫不進去」標，
title 是那句後果。CSS 沿用這個檔既有的 `.bad` 修飾子與 `--red`，
沒有新增色票。

### 測試

新檔 `tests/test_blast_cache_write_status.py` 10 條：四種狀態各一、
寫不進去的時候答案逐欄位不變、存進檔案的那一份不帶狀態、
四句話各自講各自那件事、語法樹三條（沒有不帶值的 return、
三個呼叫點都要用掉回傳值、三支函式都是先寫快取才記狀態）。

`tools/ui-render-check.py` 加 `check_blast_cache_badge`：畫面上那個標記
要跟資料裡的 `cached` / `cache_write` 對得上（展開後從 5 組變 6 組）。

### 反向驗證，其中兩次抓到我自己的測試是假的

第一輪五次植入，**第 4、5 兩次沒有紅**：

- 第 4 次把 `collect()` 的賦值搬到寫入之前，「不帶寫入狀態」那一條
  照樣綠 —— 它只呼叫 `vectors()`，而 `collect()` 在非正本 repo
  算不出指紋根本不寫檔，所以那一條覆蓋不到它。
- 第 5 次把 `ok` 那句改成失敗的措辭，「四句話不共用」那一條照樣綠 ——
  它只驗 `len(set(...)) == 4`，而那句話裡插了狀態字串，四句仍然兩兩不同。
  **兩兩不同不等於各自正確。**

改掉之後重驗，六次植入全部紅：靜默吞掉（紅 2 條）、呼叫端丟掉回傳值、
寫失敗回殘缺答案、`collect` 賦值搬前面、`vectors` 賦值搬前面、
`ok` 講成失敗的措辭、`detail` 不帶狀態出去（紅 5 條）。
還原後 `blast.py` `5c313270d5779455`，植入前後逐字元一致。

畫面那一側也反向驗證兩次。**第一次沒有紅**：把 failed 那條判斷改壞，
而 harness 的 fixture 是真的 snapshot，`cached=True`、
`cache_write='not_attempted'`，根本走不到那一條。第二次把 `cached`
那一條關掉才紅，訊息是「資料裡是 標『快取』，畫面上是 沒有標記」。
**所以那個檢查在 harness 裡只走得到一種狀態，這件事寫進它的 docstring**，
免得被讀成「三種都驗過了」。

### 一條既有測試紅了，紅得對

`test_blast.py::test_正本的collect第二次是快取而且答案一模一樣` 要求
冷熱兩次逐欄位相同，而 `cache_write` 冷是 `ok`、熱是 `not_attempted`。
**不是放寬斷言**：把這兩欄加進跳過清單的同時，緊接著把它們該有的
兩個值釘死，比先前只跳過 `cached` 嚴。

### 測試數與守門

1461 → **1471 全綠**（117.48 秒）。10 條新的，對得起來。

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 有動畫面，所以有 build 也有 deploy

`app.js` `dc93f6ef447005e2`、`app.css` `9de698dc3d9107f5`、
`blast.py` `5c313270d5779455`、`ui-render-check.py` `7db4c96e1819c6a4`。
build 回傳碼 0，`deploy.sh` 守門通過、二進位 09-17 09:02。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
`deploy.sh` 自己印「沒有開視窗」。

### 還缺什麼

- **那 13 個 `Path.open` 寫入點，仍然只走過 3 個。** 上一輪寫下的
  兩件裡的第一件，這一輪沒動：`advicetrack`、`blockread`、`commit`、
  `coverage`、`event_ledger`、`gate`、`identity`、`pollution`、
  `sufficiency`、`workflow` 實際寫到哪裡仍然沒有量。
  **這是下一輪最明確的一件。**
- **`failed:` 那一條路畫面上沒有人走過。** Python 側有 10 條守著，
  而 harness 走不到它（fixture 是真的 snapshot，快取寫得進去）。
  要真的看到那個紅標，得有人把快取目錄弄成寫不進去。
- **這個模組以外的 `except OSError` 沒有碰，而且數量比第一次數的多。**
  第一次用 grep 數出 48 個、8 個 bare，**那個數字是錯的** ——
  grep 只抓得到單行寫法。改用語法樹重數：`apps/forseti-cli/*.py`
  共 **70 個** `except OSError`，其中 **9 個**整段只有 `pass` 或
  不帶值的 `return`（`contract` 2、`coverage` 2、`context_meter` 1、
  `desktop_api` 1、`forseti` 1、`identity` 1、`ledger` 1）。
  `blast.py` 已經從這張名單上消失，因為這一輪修的就是它那一個。
  **這一輪只修了 ROADMAP 點名的那一個**，其餘九個各自吞掉什麼沒有量。
  （數的時候要跳過 48 個 `._*` 檔案，那是 exFAT 上的 AppleDouble
  資源分叉不是原始碼，解不出 UTF-8。）
- `vectors()` / `detail()` 對非正本寫快取，仍然是取捨不是 bug，留給 owner。
- JS 定義側仍然無人守，仍然卡在「JS 側同時是白名單來源」那個衝突。
- `handoff.py:47` 那行過期註解仍然沒改。
- 沒有進 `deploy.sh` 的守門，跟 5m 到 5af 同一條理由（B-15）。
- §40 這一輪**沒有登記**。上面那兩次錯（假的測試）是這一輪自己的
  草稿，不是任何文件裡留下的斷言。仍然 6 筆全部 OPEN，
  推到 RESOLVED 是狀態轉換，留給 owner。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

沒有 commit。

## 2026-09-17 09:2x　連續三輪被寫下來的那十支，量完也有人守了

### 挑了什麼，為什麼挑它

上一輪與上上一輪都寫過同一句：

    那 13 個 `Path.open` 寫入點只走過 3 個，另外十支
    （`advicetrack`、`blockread`、`commit`、`coverage`、`event_ledger`、
    `gate`、`identity`、`pollution`、`sufficiency`、`workflow`）
    實際寫到哪裡沒有量。

**連續三輪出現在「下一輪最明確的一件」裡，連續三輪沒動。**
走過的那三個（`notes`、`checkpoint`、`forkline`）會被守到，是因為
`desktop_api` 的三個會改變狀態的指令剛好會呼叫它們 ——
其餘十支沒有任何指令會走到，所以從指令那一端進去的測試永遠看不到它們。
這一輪不從指令進去，直接對模組的公開寫入 API 問同一題。

### 先量再做，量測踩到一個假陰性

十支各呼叫一次公開寫入 API，餵臨時目錄，`_WriteSpy(scope=None)`
攔整個檔案系統。結果十支各攔到 1 次，全部落在臨時目錄底下，零外洩。

**第一次量 `pollution.record()` 得到 0 次寫入。** 看起來像「它不寫檔」，
實際是漏傳 `radius_basis`，於是在 `pollution.py:150` 就 `return` 了。
跟 5af 那一輪 `fork_at` 的 0 次同一個形狀：
**提早 return 的零，跟「它不寫」的零長得一樣。**
所以新測試裡每一條都另外斷言「至少寫了一次」——
零在這一組裡一律是壞掉，不是通過。

第一次量 `coverage` 也是 0，那是我自己把類名寫錯（`Log` 不是
`CoverageLog`），例外被 harness 吃掉只印一行。兩次都是同一件事：
**零要先問「它是不是根本沒跑到」。**

### 量的時候撞到攔截網的第三個洞，而且真的製造了殘留

`EventLedger(root=tmp)` 的 sqlite 索引**不跟著 root 走**。
`event_ledger.py:283` 明寫「索引放 home」，所以餵臨時目錄之後，
`reindex()` 在 `~/.forseti/events/` 建出一個以臨時目錄命名的 db
（4096 位元組，外加 `-shm` 與 `-wal`）。臨時目錄消失之後那三個檔
留在家目錄，沒有人會刪 —— 2026-09-17 09:13 我真的製造了一次，
09:14 手動清掉，清完剩下的只有正本那一組 `Forseti-4c2837cd2998.db`。

而 `_WriteSpy` **攔不到那次寫入**：sqlite3 在 C 層開檔，
不經過 `builtins.open` 也不經過 `Path.open`。實測攔到的路徑裡
只有 jsonl，沒有 db。這是繼 `Path.open`（5af 補掉）之後的
第三個洞（第二個是 `shutil`，已知未補）。

所以新測試裡的 `_w_event_ledger()` **刻意只呼叫 `append()` 不碰
`reindex()`**，理由寫在它自己的 docstring 裡。另外加一條
`test_攔截網攔不到sqlite這件事本身`，釘住這個前提 ——
跟 `test_用builtins_open攔不到PathOpen這件事本身` 同一種：
**它釘的是前提不是功能**，哪天 sqlite3 走 Python 層的檔案物件，
該刪的是那一條，不是去修攔截網。

### 做了什麼

新檔 `tests/test_module_write_targets.py`，24 條：

- **1 條覆蓋率**：語法樹掃 `apps/forseti-cli/*.py` 所有寫模式的
  `X.open(...)`，要求每一個模組都落在「這裡守」「別處守」
  「明寫不在範圍內」三個名單其中之一。**這是這個檔案裡唯一一條會
  隨程式碼長大的測試** —— 其餘每一條都只看自己那一支，所以新增
  第十四個寫入點時其餘全部繼續綠，而那正是這十支三輪沒人管的原因：
  沒有任何東西在數總共有幾個。不用 grep，理由跟 5ag 數
  `except OSError` 那次一樣（grep 只抓得到單行寫法）。
- **10 條 parametrize**：餵臨時目錄，整個檔案系統範圍攔截，
  斷言動到的相異路徑**恰好等於**它自己回報的那一個，而且都在
  臨時目錄底下。範圍是整個檔案系統不是 `.forseti/` ——
  只看控制目錄的話，寫進家目錄或工作目錄的那一種洩漏完全看不到，
  而那一種最難發現，因為那些位置本來就有東西。
- **10 條預設位置**：**只算路徑不寫檔**，真的寫下去會動到正本。
  上面那十條全部靠傳參數，傳了參數只驗得到「參數有接上」，
  驗不到「不傳的時候它去哪」，而系統平常跑的正是不傳的那條路。
- **1 條環境變數**：`FORSETI_COVERAGE_LOG` 設了會蓋過 `root=`
  （`coverage.py:288` 明寫的優先序）。釘它的理由是：設了之後寫入
  落在 repo 外面，上面那條「只寫該寫的那一個」在別的環境會紅得
  莫名其妙，紅的時候要看得到這一條才知道紅的是環境不是模組。
- **1 條前提**：上面講的 sqlite。

`blockread` 那一支跟其餘九支問的不是同一件事，寫在程式碼註解裡：
`BlockLog.__init__` 的 `root` **沒有預設值**，位置整個由呼叫端決定，
全 repo 只有兩個呼叫端（`desktop_api.py:921` 與 `blockread.py:197`）。
所以它問的是「那個呼叫端餵的是不是控制目錄」。

**一個位元組的產品程式碼都沒改。** 這一輪只加測試。

### 反向驗證六次，全部紅，而且各自只紅該紅的那一格

| 植入 | 結果 | 紅在哪一條 |
|---|---|---|
| `advicetrack` 順手多寫一個 debug 檔 | 紅 | 只寫該寫的那一個[advicetrack] |
| `blockread` 寫到別的檔名去 | 紅 | 不傳參數的時候[blockread] |
| `workflow` 提早 return 完全不寫 | 紅 | 只寫該寫的那一個[workflow] |
| `pollution.LOG` 搬出控制目錄 | 紅 | 不傳參數的時候[pollution] |
| `gate._append` 忽略 `path` 改寫正本 | 紅 | 只寫該寫的那一個[gate] |
| 新增一個沒人守的寫模式 `.open` 模組 | 紅 | 每一個寫模式的PathOpen在某處都有人守 |

每一次都是 1 failed 23 passed，**證了 parametrize 真的逐支隔離**。
還原後 `advicetrack.py` `f412dbea2f2715bf`、`blockread.py`
`718d90a15e2dd81d`、`gate.py` `bdbc8c4884cfa885`、`pollution.py`
`1720b50784e15495`、`workflow.py` `c97a125591dda6af`，
植入前後逐字元一致（sha256 前 16 碼）。

**第五次植入真的污染了正本，寫在這裡不是補充是事故。**
「`gate._append` 忽略 `path`」那一次，`gate.judge()` 真的往
`.forseti/gate.jsonl` 寫了一行（`session` 是「守門測試」）。
那個檔在植入前不存在 —— AppleDouble `._gate.jsonl` 的時間跟它
同為 09:17，是那一刻才建的。已經移出正本，整行留在這一輪的
scratchpad 底下沒有刪。**植入驗證本身會產生真實副作用**，
下一次做這種植入之前要先想「這一條測試會不會讓它寫到正本」。

### 測試數與守門

1471 → **1495 全綠**（117.02 秒）。24 條新的，對得起來。

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `dc93f6ef447005e2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `9de698dc3d9107f5`，跟上一輪逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 還缺什麼

- **那十支的寫入現在有人守，但「寫進去的內容對不對」沒有人看。**
  這一組問的是位置，不是內容。`gate.judge([], [])` 寫出一筆
  `of: 0` 的紀錄照樣算通過 —— 因為它問的不是那件事。
- **`_WriteSpy` 的第二個洞（`shutil`）仍然沒補**，第三個洞（sqlite）
  這一輪只釘住不補。補 sqlite 要 hook `sqlite3.connect`，
  而那會攔到所有讀取，值不值得沒有量。
- **`EventLedger` 的索引落在家目錄這件事，是設計決定不是 bug**，
  但它讓「餵臨時目錄」這個隔離手法有一個缺口。要不要讓索引跟著
  `root` 走是 owner 的決定，不是這一輪該改的。
- 全 repo 的 `except OSError` 語法樹數出 70 個，其中 9 個整段只有
  `pass` 或不帶值的 `return`（`contract` 2、`coverage` 2、
  `context_meter` 1、`desktop_api` 1、`forseti` 1、`identity` 1、
  `ledger` 1），各自吞掉什麼**仍然沒有量**。
- `vectors()` / `detail()` 對非正本寫快取，仍然是取捨不是 bug。
- JS 定義側仍然無人守；`handoff.py:47` 那行過期註解仍然沒改；
  沒有進 `deploy.sh` 的守門（B-15）。
- §40 這一輪**沒有登記**。上面那兩次假陰性是這一輪自己的量測草稿，
  不是任何文件裡留下的斷言。仍然 6 筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** 那 9 個整段只有 `pass` 或不帶值 `return` 的
`except OSError`，各自吞掉什麼沒有量 —— 跟 5ag 修掉的 `blast.py`
那一個是同一種洞，只是散在七個模組裡。

沒有 commit。

---

## 2026-09-17 09:4x　那九個靜默吞掉的，各自吞掉什麼量出來了

### 挑了什麼

`ROADMAP.md` 5ah 結尾與這份檔案上一節的「下一輪最明確的一件」，
兩處寫的是同一件：那 9 個整段只有 `pass` 或不帶值 `return` 的
`except OSError`（`contract` 2、`coverage` 2、`context_meter` 1、
`desktop_api` 1、`forseti` 1、`identity` 1、`ledger` 1），
各自吞掉什麼沒有量。跟 5ag 修掉的 `blast._cache_put` 同一種洞。

動手之前先確認沒有人做過：`ls tests/ | grep -i "swallow|except|oserror|silent"`
零筆，`grep -rl OSError tests/` 的 6 個檔案裡沒有一個問這一題。

### 先量再做，普查先推翻兩個既有數字

語法樹重掃 `except OSError`：**`apps/` 70 個、`tools/` 16 個、`tests/` 1 個。**
5ag 那一輪寫的「全 repo 70 個」只數了 `apps/`，
而 `tools/` 底下另有 **3 個也是靜默的**（`claims-audit.py:121`、
`owner-audit.py:124`、`reading-conformance.py:98`）從來沒被數過。
它們是開發側腳本不是產品程式碼，所以這一輪只做普查不做行為量測。

### 量出來的結果

手法一律是把那一個作業換成丟 `OSError`，再跟「正常」與
「本來就沒東西」兩種對照比。九個裡**有八個從回傳值分不出來**。

- `context_meter.report_all:350` —— 3.5MB 的檔 stat 不到，
  報告從「共 3 MB」變「共 0 MB」，**其餘每一行逐字元相同**，
  整份沒有一個字提到算不到。
- `contract._hcache_save:545` / `_rc_cache_save:763` —— 成功與失敗
  都回 `None`，要自己去 stat 那個檔才知道。
- `coverage.header_lines_of:245` —— 讀不到回空集合，
  跟「這份文件真的沒有標題」一模一樣。
- `coverage.read_all:310` —— 讀不到回 `[]`，跟「一筆紀錄都沒有」一樣。
- `desktop_api.spec_reading:815` —— **這個最重。** manifest 讀不到的時候
  九份模組化規格整批不進 `must`，實測 `total` 從 30 掉到 21，
  回傳字典沒有任何一個鍵提到它。這個函式上面第 5 行的註解寫的
  正是 2026-09-14 那次「分母少算，比例比真實情況樂觀」的事故 ——
  **同一個事故可以從這個洞無聲地重開一次。**
- `forseti._ensure_inbox:1069` —— 建不出來也照回一個 `Path`，形狀一樣。
- `identity._cache_write:290` —— 回傳都 `None`。
- `ledger.collect_inbox:858` —— 唯一分得出來的，但分得出來的方式是
  「去看檔案還在不在」，不是呼叫端拿得到的東西。實測代價：
  搬不走的檔留在原地，**下一次收件會把同一個檔再收一次**
  （事件層有 `idem_key` 擋重複，但 `collect_inbox` 的回傳值照樣再報一次）。

### 量的時候踩到兩個假陰性，兩個同一個形狀

一，`context_meter` 第一次餵的 jsonl 放在 root 底下一層，
    而 `find_sessions` 要 `*/*.jsonl`（`context_meter.py:195`），
    於是走的是「底下沒有 jsonl」那條早退路徑，
    正常與失敗印出同一句話。**早退造成的相同，跟吞掉造成的相同長得一樣。**

二，改好目錄結構之後餵的檔只有 40 位元組，`total_bytes / 1e6`
    兩邊都印「0 MB」。**還是相同，還是假的。** 要餵到 3.5MB 才量得出差。

第三個假陰性在 `identity`：「正常」那一次我根本沒呼叫
（被 `if not before else None` 短路掉），卻拿它跟失敗那次比，
得到「分不出來」。

三個都是同一件事：拿到「兩邊一樣」就收手，沒有先問
**「這個一樣，是我要的那個一樣嗎」**。所以新測試每一條
會分得出來的，都另外釘住對照組本身不是退化的。

### 做了什麼

新檔 `tests/test_silent_oserror.py` **12 條**：
3 條普查（產品側九個、`tools/` 三個、以及「普查表跟量測表對不起來就紅」），
9 條逐站點行為量測。**一個位元組的產品程式碼都沒改。**

站點的 key 用（模組名，包住它的函式名），不用行號 ——
行號會因為上面加一行註解就整批位移，那種紅是雜訊不是訊號。

`ledger` 那一條第一版沒有碰到產品程式碼（我自己重現了 `mkdir` + `rename`），
那等於在測我抄的那一份。改成真的起 `Ledger(db=tmp, cwd=tmp)` 走
`collect_inbox()`，兩個路徑都導到臨時目錄，所以 sqlite 帳本與收件匣
都不落在家目錄也不落在正本。改的過程順帶被自己的對照組抓到
一個抄錯：搬過去的目錄是 `.done` 不是 `done`。

### 反向驗證十次，每次只紅該紅的

九個站點各植入一次，每次紅的都是**普查那一條加上該站點自己那一條**，
其餘十條全綠 —— 證了逐站點隔離。普查會跟著紅是對的：
植入讓那個 handler 不再是靜默的，名單本來就該變。

第十次驗的是相反方向：在 `blockread.py` 補一個新的靜默 handler，
普查那一條紅，行為那九條全綠。還原後 12 條回綠。

**這一輪的植入沒有製造任何殘留。** 5ah 那次植入真的往正本
`.forseti/gate.jsonl` 寫了一行，所以這次事前就把 `identity._cache_file`
導開，並且在測試最後一句斷言正本逐位元組沒變。事後查證：
`.forseti/cache/identity.json` 沒有 `probe` 這個 key，
家目錄帳本與快取檔的 mtime 都停在 09:33:20，是上一輪的。

### 測試數與守門

1495 → **1507 全綠**（160.95 秒）。12 條新的，對得起來。

    python3 tools/literal-restate-check.py  → 0
    python3 tools/declared-only-check.py    → 0
    python3 tools/ui-render-check.py        → 0

### 沒有動畫面，所以沒有 build 也沒有 deploy

`app.js` `dc93f6ef447005e2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `9de698dc3d9107f5`，跟上一輪逐字元一致。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 還缺什麼

- **量完了，一個都還沒修。** 這一組釘的是「此刻吞掉什麼」，
  不是「應該吞什麼」。修好其中一個（照 5ag 對 `blast._cache_put`
  的做法回一個狀態）會讓對應那一條紅，那時要同時改測試與那張表。
  **不要為了讓它綠而把站點改回去**，這句話寫在測試檔的 docstring 裡。
- **最該先修的是 `desktop_api.spec_reading:815`**，因為它吞掉的是
  必讀清單的分母，而分母少算正是 2026-09-14 那次事故本身。
  但它要在畫面上看得見才不算白工（那一格現在只顯示 `total`），
  所以那是一輪有 build 有 deploy 的工作，不是這一輪的尾巴。
- `tools/` 那三個只普查沒量測。它們是開發側腳本，
  但「開發側」不等於「錯了沒關係」——`reading-conformance.py`
  判的是讀取符合度，吞掉讀取失敗會讓不合格看起來像合格。
- **跑全套測試會寫到正本的 `.forseti/NEXT.md`**（實測 mtime 從
  09:33:20 跳到 09:49:50，那段時間只有 pytest 在跑）。
  這是既有行為不是這一輪造成的，但它讓「測試不碰正本」這個前提
  有一個缺口，沒有量是哪一條測試寫的。
- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞仍然沒補；
  `EventLedger` 索引落在家目錄仍然等 owner 決定。
- JS 定義側仍然無人守；`handoff.py:47` 那行過期註解仍然沒改；
  沒有進 `deploy.sh` 的守門（B-15）。
- §40 這一輪**沒有登記**。上面三個假陰性是這一輪自己的量測草稿，
  不是任何文件裡留下的斷言。仍然 6 筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** 量出「跑全套測試到底有哪幾條會寫到正本的
`.forseti/`」。上面那個 NEXT.md 的 mtime 跳動是量出來的事實，
但是誰寫的沒有量 —— 而「測試不碰正本」是這一組與
`test_module_write_targets.py` 共同的前提，前提沒人守跟沒有前提一樣。

沒有 commit。

---

## 2026-09-17 10:2x　自動接續

### 挑了什麼

上一輪（5ai）自己寫下的那一件：「跑全套測試會寫到正本的
`.forseti/NEXT.md`，但是哪幾條測試寫的沒有量」。
挑它的理由是它不是新功能，是**補一個沒人守的前提** ——
`test_forseti_dir_writes.py` 與 `test_module_write_targets.py`
兩組共同建立在「測試不碰正本」上面，而上一輪的 mtime 跳動
證明這個前提此刻並不成立，只是不知道是誰。

### 做完什麼

新增兩個檔，產品程式碼一個位元組都沒改。

`tests/conftest.py` ── 量測。每條測試前後各掃一次 `.forseti/`，
比對 `(相對路徑, mtime_ns, 大小)`。**不攔動作**，所以 sqlite、
`shutil`、子行程、C 層寫入一律看得到 —— 那正是 `_WriteSpy`
攔不到的兩個洞（`test_module_write_targets.py` 的 docstring 記過）。
記錄器透過 `pytest_configure` 掛到 `config` 上，不讓守門自己
`import conftest`（那會拿到另一份 `_RECORD` 永遠是空的模組，
而空的記錄表跟「沒有人動正本」長得一模一樣）。

`tests/test_zz_forseti_write_attribution.py` ── 守門 8 條。

### 這一輪自己推翻了自己一次，寫在這裡

第一次全套量到 28 條測試動到正本，於是寫下
「`NEXT.md` 的寫入者是 `test_forseti_dir_writes.py` 那一條」，
**而且已經寫進測試檔的 docstring、跑過一次全套**。

第二次全套推翻它。同樣的程式碼、同樣的測試集，寫 `NEXT.md` 的
變成 `test_claims_wiring.py::TestRealSnapshot::test_no_duplicates_within_a_row`，
還多出一個第一次沒有的 `test_blast.py`。

**機制：拿到一次觀測就寫成歸屬，而沒有先問這個歸屬會不會在
第二次觀測換人。** 這一輪逃過去的原因是守門測試本身需要
第二次全套才能驗，不是我主動去驗的 —— 所以這不算警覺，
算運氣。真正的防線應該是「身份類的結論至少量兩次」。

漂移的成因兩條路徑各不同，都讀原始碼確認過，不是推測：

    NEXT.md        handoff.should_write:78 讀正本檔自己的 mtime，
                   MIN_GAP_S = 240。寫得成的是那一輪第一個走到
                   strands() 又剛好在窗外的那一條，誰是第一個
                   由執行順序決定（c 開頭的排在 f 開頭的前面）。
    cache/blast.json
                   blast._fingerprint:365 的指紋涵蓋 SCAN_DIRS
                   底下每個 .py 的 mtime 與大小，而 tests/ 在裡面。
                   這一輪一直在增刪測試檔，所以快取一直失效。

對照實測釘住節流那一半：同一條測試跑兩次，距上次寫 241.3 秒
（窗外）動到 `NEXT.md`，9.1 秒（窗內）沒動到。

**沒有登記進 §40。** 判準跟 5ai 那一輪一致：這個錯誤結論從頭到尾
只活在這一輪未定稿的檔案裡，同一輪內被自己推翻，沒有進入任何
交出去的文件。**這個判準本身可能太寬**，因為它確實一度存在於
工作區並跑過一次全套 —— 留給 owner 推翻。

### 驗證結果

全套 1507 → **1515 全綠，217.49 秒**。三次全套的量測資料都留著。

守門（`test_js_symbols.py` + `test_ui_contract.py`）86 條全綠，回傳碼 0。

反向驗證六次，每次只紅該紅的：

    寫 cache/ 底下的新檔            只有「在冊」紅
    寫 .forseti/ 頂層檔             「在冊」加「路徑」兩條紅
    碰 ROADMAP.md                   訊息指出「重建不回來」
    排在守門後面新增一條測試        位置那條紅
    停用 conftest 的掛鉤            「掛鉤漏了 5 條」而不是靜默的零
    _diff 改成永遠回空              自我測試那條紅

碰 `ROADMAP.md` 那次事前 `cp` 備份、事後 `shasum -a 256 -c` 驗證還原，
停用掛鉤與 `_diff` 那兩次同樣用 sha256 驗證 `conftest.py` 還原。
**沒有留下任何殘留**（探針檔已刪、`.forseti/` 底下沒有 probe 檔；
`.forseti/probe_baseline.json` 是 09-16 22:10 的既有 Probe Packs 檔，
不是這一輪造成的）。

### 代價量出來了

全套慢 **31.9 秒（+17.2%）**。同一台機器：搬走 `tests/conftest.py`
跑 1507 條 185.56 秒，放回去加這八條 1515 條 217.49 秒。
來源是每條前後各掃 155 個檔，約 47 萬次 `stat`。

掃一次就好（拿上一條的結果當下一條的起點）可以砍掉一半，
**沒有這樣做**：那樣兩條測試之間發生的寫入會被算到下一條頭上，
現在那段時間的寫入是無主的。誤判歸屬比慢十五秒糟。

### 沒有動畫面

`app.js` `dc93f6ef447005e2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `9de698dc3d9107f5`，跟上一輪逐字元一致。
所以沒有 build 也沒有 deploy。

### 全程沒有開啟或關閉 Forseti App

owner 2026-09-16 明令。沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
`pgrep -x Forseti` 沒有回應 —— 這同時也是量測的前提：
App 在跑的話它每兩秒的輪詢寫入會被算到剛好在跑的那條測試頭上。

### 還缺什麼

- **這一組看不到「先建檔再刪掉」。** 它量的是一條測試結束之後
  跟開始前有沒有不同，不是期間發生過幾次寫入。要量後者得攔動作，
  那是 `_WriteSpy` 的範圍。兩個問的不是同一題，兩個都要留著。
- **在冊名單的粒度是檔不是條。** 同一個檔裡多加一條測試不會紅，
  一個新的檔開始動正本才會紅。這是刻意的取捨，不是疏漏。
- `tools/` 那三個靜默 `except OSError` 仍然只普查沒量測。
- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞仍然沒補；
  `EventLedger` 索引落在家目錄仍然等 owner 決定。
- JS 定義側仍然無人守；`handoff.py:47` 那行過期註解仍然沒改；
  沒有進 `deploy.sh` 的守門（B-15）。
- 5ai 寫的「最該先修的是 `desktop_api.spec_reading:815`」還沒做，
  它要在畫面上看得見才不算白工，所以是一輪有 build 有 deploy 的工作。
- §40 仍然 6 筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** `tools/` 底下那三個靜默 `except OSError`
（`claims-audit.py:121`、`owner-audit.py:124`、`reading-conformance.py:98`）
量出各自吞掉什麼。`reading-conformance.py` 判的是讀取符合度，
吞掉讀取失敗會讓不合格看起來像合格 —— 跟 5ai 量到的
`desktop_api.spec_reading:815` 是同一個方向的洞。

沒有 commit。

## 2026-09-17 10:4x　`tools/` 那三個靜默吞掉的量完了，順便推翻上一輪的預測

### 挑了什麼

上一輪（09:4x）結尾自己寫的「下一輪最明確的一件」：

    `tools/` 底下那三個靜默 `except OSError`（`claims-audit.py:121`、
    `owner-audit.py:124`、`reading-conformance.py:98`）量出各自吞掉什麼。

那句話連續三輪出現在這份 log 裡，連續三輪沒動。產品側那九個
09:4x 已經量完了，剩這三個因為「是開發側腳本不是產品程式碼」
被標成只普查不量測 —— 而那個理由撐不住：
`reading-conformance.py` 判的是「補讀有沒有真的做到」，
它失真的代價跟產品程式碼一樣。

動手前先確認不是重做：`tests/test_silent_oserror.py` 已經在，
它的 `EXPECTED_TOOLS` 有這三個站點的普查，但沒有任何一條行為量測。
所以這一輪是補量測，不是重寫模組。

### 量出來的三個結果

手法跟產品側那九個一致：把那一個作業換成丟 `OSError`，
再跟「正常」與「本來就沒東西」兩種對照比。

    claims-audit.assistant_texts:121
        吞掉　那一份 transcript 從出錯那一行開始的所有 assistant 文字
        呼叫端　分不出來，而且這一個是**截斷不是全無**

    owner-audit.main:124
        吞掉　那一個 session 的整張沉默地圖
        呼叫端　分不出來，輸出跟「真的沒有 AI 輪」逐字元相同

    reading-conformance.declared:98
        吞掉　補讀表整張宣稱記錄
        呼叫端　分不出來，`check()` 回的整個 dict 跟一張真的空表相同

第一個最值得寫下來。`assistant_texts` 是 generator，`try` 包住整個
`for line in fh` 迴圈，所以讀到第 3 行才壞的話，前 2 段照樣 yield 出去。
實測：一份 5 段的檔，全開不了回 0 段，讀到第 2 行壞掉回 2 段，
而一份本來就只有 2 段的檔也回 2 段 —— 後兩者**逐元素相同**。
只植入 `open` 失敗的話量到的是「全無」，那個看得出來；
真正分不出來的是截斷，而截斷要另外植入才碰得到。

第二個最刺的地方是報告自己打自己。`owner-audit.py` 印出來：

      語料　1 個 session，4 則 owner 訊息
      ...
      沉默地圖　0 輪

四行之內自相矛盾，而沒有任何一行說它失敗了。更難看的是那一句
「其中 N 輪（M%）底下是分類器的 UNKNOWN」的警語整條消失 ——
**壞掉的那份報告看起來比正常那份乾淨。**

### 這一輪推翻了上一輪寫下的一句話，登進了 §40

上一輪原話：

    `reading-conformance.py` 判的是讀取符合度，吞掉讀取失敗會讓
    不合格看起來像合格

**方向是反的。** 實測 `declared()` 讀不到補讀表時回 `{}`，
`check()` 於是把每一份都判 `NO_RECORD`，`status` 是 `NON_CONFORMANT`、
`bad` 等於 `checked`、exit code 1 —— 它變**過嚴**不是過鬆。

洞不在寬嚴，在**理由是假的**：每一列印「補讀表裡沒有這一份的記錄」，
而補讀表根本沒被讀到。照那句理由去修的人會去補表，
而表可能一直是對的，錯的是讀不到。

機制：從「錯誤被吞掉 → 檢查失效 → 檢查失效等於放行」這條通則推下去，
中間跳過了「去讀 `declared()` 回空之後 `check()` 怎麼用那個空值」。
空值在下游代表什麼決定了偏誤方向 —— 這裡的空是「沒有人宣稱讀過」，
而沒有人宣稱讀過在這支工具裡是不合格。
**吞掉錯誤會讓檢查往寬還是往嚴偏，不能從「錯誤被吞掉了」本身推出來。**

登記為 `pol-6d68166af2`，OPEN，§40 從 6 筆變 7 筆。
預防規則與回歸探針兩欄都填了（探針就是下面那條測試），
所以它是「有東西攔著」的那一類，不是只靠人記得。

判準跟 5ai 那次不一樣，所以這次登記：那一次的錯誤結論只活在
同一輪未定稿的檔案裡，這一次是**已經寫進 `AUTO_CONTINUE_LOG.md`
交出去了**，下一個讀的人會把它當成已知。

### 做完什麼

只動一個檔：`tests/test_silent_oserror.py`。產品程式碼與 `tools/`
一個位元組都沒改（下面有 sha256 佐證）。

新增四條：一條普查對量測的對照表（跟產品側那條同一個理由，
防的是「名單上有、但沒有人去量它吞掉什麼」），三條逐站點行為量測。
檔頭多一張 `tools/` 的表，以及推翻那一段。

### 驗證結果

全套 1515 → **1519 全綠，223.92 秒**。

反向驗證三次，每次只紅該紅的兩條（普查那條 + 對應那條行為量測）：

    claims-audit 的 `return` 改成 `raise`          紅 2 條
    owner-audit 的 `pass` 改成 print 出錯訊息      紅 2 條
    reading-conformance 的 `pass` 改成寫一筆錯誤   紅 2 條

三次都事前 `cp` 備份、事後 `shasum -a 256 -c` 驗證還原：

    tools/claims-audit.py: OK
    tools/owner-audit.py: OK
    tools/reading-conformance.py: OK

`git status --porcelain tools/` 裡這三個檔沒出現，是第二個獨立佐證。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔沒碰，所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 還缺什麼

- **這一組量的是「此刻吞掉什麼」，不是「該不該吞」。** 三個站點
  一個都沒修。要修的話 `reading-conformance.declared()` 排第一 ——
  它的理由造假，而另外兩個只是靜默。
- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞仍然沒補；
  `EventLedger` 索引落在家目錄仍然等 owner 決定。
- JS 定義側仍然無人守；`handoff.py:47` 那行過期註解仍然沒改；
  沒有進 `deploy.sh` 的守門（B-15）。
- 5ai 寫的「最該先修的是 `desktop_api.spec_reading:815`」還沒做，
  它要在畫面上看得見才不算白工，所以是一輪有 build 有 deploy 的工作。
- §40 現在 7 筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** 修 `reading-conformance.declared()`，
讓它分得出「讀不到」與「表是空的」。這是這一輪量出來的三個裡
唯一會誤導修的人的那一個，而且改完 `test_silent_oserror.py` 裡
對應那一條會紅 —— 那是對的，順手把檔頭那張表一起改。

沒有 commit。

## 2026-09-17 11:1x　那個假理由修掉了，順帶抓到守門自己的前提會過期

### 挑了什麼

上一輪（10:4x）自己寫下的「下一輪最明確的一件」：修
`reading-conformance.declared()`，讓它分得出「讀不到」與「表是空的」。
那是上一輪量到的三個 `tools/` 靜默吞掉裡，唯一會誤導修的人的那一個。

### 做完什麼

一，`tools/reading-conformance.py`。`declared()` 不再吞掉 `OSError`
回空 dict，改成丟 `ReadingTableUnreadable`；`check()` 接住之後回
`CANNOT_CHECK`。**那不是新語意**，是這支模組檔頭 exit code 那一段
本來就寫著的「2　無法檢查（manifest 或補讀表找不到）」——
補讀表那一半先前只寫在文件裡沒有實作。

修之前補讀表讀不到的時候，每一份都判 `NO_RECORD`，理由印
「補讀表裡沒有這一份的記錄」，跟一張真的空表整個 dict 相同。
那句理由是假的：表根本沒被讀到，照它去修的人會去補表。

二，`tests/test_reading_conformance.py` 加 `TestReadingTableUnreadable`
五條：讀不到回 `CANNOT_CHECK`、exit 2、`declared()` 丟例外、
**空表仍然是 `NON_CONFORMANT`**、兩種情形的回傳值不相等。
第四條防的是修這種假理由最容易犯的那一步，順手把空表一起放寬。

三，`tests/test_silent_oserror.py` 跟著改：`EXPECTED_TOOLS` 從三個
變兩個，普查那一條改名，檔頭兩張表改掉，那一條行為量測移走
（站點修好之後留著會變成一句過期的斷言），原地留指標指向新的守門。

四，**守門自己的前提過期了，一起修。**
`test_zz_forseti_write_attribution.py` 原本寫死「一輪最多寫得成
一次 `NEXT.md`」，前提是「一輪三分多鐘」比 `MIN_GAP_S = 240` 短。
這一輪全套跑 301.60 秒，跨過那條線，於是量到 2 條寫入者、這一條紅。
**那次紅是假陽性**：301 秒裡節流窗開得成兩次。上界改成
`floor(這一輪跑了幾秒 / MIN_GAP_S) + 1`，秒數由 `conftest`
新增的 `session_elapsed_s()` 提供（`pytest_configure` 起算）。
拿不到秒數的時候那一條直接紅，不靜默放寬。

五，`test_context_meter報告會少算而且不說` 的偶發紅修掉。它逐行比對
兩份報告，而報告裡有一行是 `掃描耗時　0.Xs` —— 實測正常那次 0.2s、
失敗那次 0.3s，紅的是機器負載不是被測行為。改成把那一行的秒數歸一，
**不是整行丟掉**：那一行消失了仍然該紅。

### 驗證結果

全套 **1523 全綠，317.71 秒**（同一輪先前兩次分別是 301.60 秒
一紅、391.89 秒一紅，兩次紅都在上面修掉了）。

反向驗證：

    把 reading-conformance.py 換回修之前那一份
      → 紅 5 條，正好是普查那條加四條新行為測試；
        「空表仍然 NON_CONFORMANT」那條保持綠（修前修後都成立），
        還原後 sha256 比對相同
    把 check() 改成「have 是空的也回 CANNOT_CHECK」（順手放寬）
      → 紅 2 條（空表那條與兩者不相等那條），還原後 sha256 比對相同
    上界那條拿假的記錄直接呼叫函式跑四組
      → 10 秒 2 次寫入 紅、239 秒 2 次 紅、301.6 秒 2 次 綠、
        301.6 秒 3 次 紅、拿不到秒數 紅

真實資料上這支工具的行為沒有變：修前修後各跑一次
`python3 tools/reading-conformance.py`（修前那一份放在 repo 的
`tools/` 底下跑，因為 `REPO` 由 `__file__` 推），
輸出 `diff` 逐字元相同，exit code 都是 0，9 份全部 OK。

`NEXT.md` 這一輪實測 2 條寫入者，317.71 秒 → 上界 2，綠。
那正是舊寫法會誤判的那一種。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔的 sha256 跟上一輪逐字元一致：
`app.js` `dc93f6ef447005e2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `9de698dc3d9107f5`。所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`；
三次全套之前 `pgrep -x Forseti` 都沒有回應。

### 還缺什麼

- **`tools/` 另外兩個站點沒修**（`claims-audit.assistant_texts`
  截斷、`owner-audit.main` 沉默地圖整張）。這一輪只修了會誤導的那一個，
  另外兩個是靜默但理由沒有造假。
- 產品側九個一個都沒修，那一組仍然只是量測。
- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞仍然沒補；
  `EventLedger` 索引落在家目錄仍然等 owner 決定。
- `tests/test_sot.py` 這一輪其中一次全套動到了正本（`strands()`，
  `test_sot.py:357`），不在 `REGISTERED_WRITER_FILES` 裡所以紅過一次；
  最後一次全套它沒動到，**所以沒有登記** —— 會不會動取決於執行順序
  與節流窗，登記一個時有時無的寫入者等於把不確定寫成確定。
  下一輪要決定的是「讓它別碰正本」還是「登記並寫下理由」。
- §40 現在 7 筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** `tests/test_sot.py` 那個寫入正本的路徑。
它是這一輪唯一新冒出來的東西，而且兩種處理方式（隔開或登記）
都得先讀 `test_sot.py:357` 那一段在測什麼才決定得了。

沒有 commit。

---

## 2026-09-17 11:3x　那個「時有時無的寫入者」結了，而且結的方式推翻了上一輪的理由

### 挑了什麼

上一輪自己寫下的那唯一一件：`tests/test_sot.py:357` 呼叫 `strands()`，
其中一次全套它動到正本 `.forseti/`、最後一次沒動到，所以沒有登記。
要決定的是「讓它別碰正本」還是「登記並寫下理由」。

照 ROADMAP 的順位這是上一輪指名的下一件，不是新開的方向。
動手之前先確認沒有既有實作：`grep -rn "strands(" tests/` 加上 AST 掃描，
`STRANDS_CALLERS`、`_scan_strands_callers` 在 repo 裡都不存在。

### 先讀了那一段在測什麼，才決定得了

`test_sot.py:355-359` 整條是三行：呼叫 `strands()`、斷言 `"sot" in snap`、
斷言 `snap["sot"]["has"]`。它測的是 `strands()` 有沒有把 §12.2 那一格
接進快照。**換成 `sot_panel()` 就不是同一題** —— 那一支另有測試守在
`:284`，接線斷掉的時候它照樣綠。所以「讓它別碰正本」等於把這條測試
換成另一條，不是隔離。

### 兩個問題被混成一個，這是上一輪那句話的真正問題

上一輪的理由是「登記一個時有時無的寫入者等於把不確定寫成確定」。
那句話對的是身份層，但它讓整個檔逃掉了。拆開之後沒有矛盾：

    「它那一次寫了沒有」      時有時無，不該寫成確定
    「它碰不碰得到正本」      確定的，掃原始碼就看得到

第二題先前沒有人問。實測（攔截 `handoff.should_write` 與 `handoff.write`，
不真的寫，只量路徑有沒有被走到）：

    D.strands()  →  should_write 1 次、write 1 次
                    目標 `<default>` = handoff.OUT
                    = /Volumes/NewDrive/AI Project/Forseti/.forseti/NEXT.md

`strands()` 尾段 `desktop_api.py:3418` 那一行是 `_safe(lambda:
_write_handoff(snap), None)`，**無條件**，寫不寫只由節流窗決定。
所以 `test_sot.py` 從頭到尾都碰得到正本，藏起來的是輪次不是能力。

### 做完什麼

一，**登記 `tests/test_sot.py`**，理由寫在名單旁邊：它碰得到正本，
不是它寫過。

二，**補掉名單來源本身的缺陷**（這一項比上面那一項重要）。
`REGISTERED_WRITER_FILES` 的來源是「跑一輪看誰動到正本」，而誰寫得成
`NEXT.md` 由 240 秒節流窗加執行順序決定 —— **觀測只看得見贏了競速的
那一條**。一個從頭到尾都碰得到正本、但還沒輪到它的檔在觀測裡是隱形的。
`test_sot.py` 正是這樣藏了一輪。

所以加了 `STRANDS_CALLERS` 這張表加上 `_scan_strands_callers()`，
用 **AST 不用 grep**：grep 分不出 docstring 裡討論 `strands()` 的那些
（`test_handoff.py` 與 `test_forseti_dir_writes.py` 的說明裡各提了十幾次），
也分不出 `test_betrayal.py` 裡的 `strands(self)` 是方法定義不是呼叫。
掃出來真正的呼叫點是 4 個檔 5 處：`test_claims_wiring.py:117`、
`test_forseti_dir_writes.py:279`、`test_handoff.py:269/359/380/437`、
`test_sot.py:357`。

守門那一條有兩個斷言，抓的不是同一件事：

    掃出來 == 寫下來      抓「既有在冊檔裡新加了一個呼叫點」
                          （這種情況下面那條抓不到，那個檔本來就在冊）
    掃出來 ⊆ 在冊的       抓「新開一個檔去呼叫 strands()」

### 這個掃法看不到什麼（寫成前提，不是補充）

`getattr(D, "strands")()` 這種動態取名的呼叫看不到；測試呼叫某個輔助
函式、由那支間接呼叫 `strands()` 也看不到。名字比對還會把別處的同名
函式算進來，那是假陽性，方向安全。所以它守的是「直接呼叫點」這個範圍，
**不是「所有通往正本的路」** —— 後者要攔動作，那是 `_WriteSpy` 的範圍。

### 驗證結果

全套 **1524 全綠，478.94 秒**（上一輪 1523 綠 317.71 秒，多的 1 條是
新守門）。這一輪跑得比上一輪久，節流上界 `floor(478.94/240)+1 = 2`，
`NEXT.md` 那一條綠 —— 上一輪改成算出來的上界在這一輪直接派上用場，
寫死「一輪最多一次」的舊寫法在這個長度會假陽性。

反向驗證三組，每組還原後都比對 sha256：

    把 test_sot.py 從 REGISTERED_WRITER_FILES 拿掉
      → 紅 1 條，訊息是「不在 REGISTERED_WRITER_FILES：['tests/test_sot.py']」
        （這一組證明「⊆」那個斷言活著，因為「==」在這組裡是綠的）
        還原 sha256 d5cc498fcff23ca7 相同
    在已經在冊的 test_blast.py 裡新加一個 strands() 呼叫點
      → 紅 1 條，「多出來的：['tests/test_blast.py']」
        （「⊆」在這組抓不到，因為 test_blast.py 本來就在冊 ——
          這正是兩個斷言都要留著的理由）
        還原 sha256 319c0a4520d446c6 相同
    新開一個從來沒在冊的 tests/test_tmp_reverse_new.py 呼叫 strands()
      → 紅，「多出來的：['tests/test_tmp_reverse_new.py']」
        （「==」先跑所以先紅，「⊆」由上面第一組單獨證明）
        檔案已刪除

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔的 sha256 跟上一輪逐字元一致：
`app.js` `dc93f6ef447005e2`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `9de698dc3d9107f5`。所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`；
跑全套前後 `pgrep -x Forseti` 都沒有回應。

### 還缺什麼

- **這一輪沒有量「這一次全套裡誰實際寫了 `NEXT.md`」**。
  要量得帶 `FORSETI_WRITE_ATTRIBUTION_OUT` 再跑一次八分鐘全套，
  沒跑，所以**不寫**「test_sot 這一次寫了」這種話。
  已經證明的是能力（攔截實測），不是那一次的結果。
  `NEXT.md` 的 mtime 在跑全套期間從 11:17:23 動到 11:32:49，
  那段時間只有 pytest 在跑 —— 有人寫了，是誰沒量。
- 間接呼叫與動態取名那兩個洞沒補，見上面「這個掃法看不到什麼」。
- `tools/` 另外兩個靜默站點沒修（`claims-audit.assistant_texts` 截斷、
  `owner-audit.main` 沉默地圖整張）。產品側九個一個都沒修。
- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞仍然沒補；
  `EventLedger` 索引落在家目錄仍然等 owner 決定。
- §40 現在 7 筆全部 OPEN。這一輪推翻的那句話（「登記一個時有時無的
  寫入者等於把不確定寫成確定」，用它當理由把整個檔放掉）
  **還沒登進 §40**，下一輪要登。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** 把上面那筆推翻登進 §40 污染登記簿。
機制寫得出來（把「不該把不確定寫成確定」這個對的原則，套到一個
其實確定得了的問題上，於是整個對象被放掉），而且它跟登記簿裡
已有的七筆是同一類 —— 都是推論的形狀出問題，不是數字算錯。

沒有 commit。

## 2026-09-17 12:0x　§40 第 8 筆登了，而且守門那條紅這一輪換了對象

### 挑了什麼

`ROADMAP.md` 與上一輪 log 結尾都寫著同一件：把 5al 推翻的那句話
登進 §40 污染登記簿。動手前先確認它還沒登（`pollution.records()` 7 筆，
`grep 時有時無` 只命中散文與測試註解，登記簿裡沒有）。

### 做完什麼

第 8 筆 `pol-f3c5ddcbe4`，OPEN。

    original_claim   登記一個時有時無的寫入者等於把不確定寫成確定，
                     所以 tests/test_sot.py 不登記
    corrected_claim  那句話對的是「它那一次寫了沒有」，
                     錯在拿它回答「它碰不碰得到正本」
    failure_mechanism把一條正確的原則套到它管不到的那一題上

四個必填的出處逐行開檔驗過，不用上一輪的轉述：
`test_sot.py:357`、`desktop_api.py:3418`、
`test_zz_forseti_write_attribution.py:173-181`。
`propagation_radius` 是 None 加 `radius_basis`，照 §8.3 不編單位。

### 驗證結果

相關四檔（`test_pollution` `test_pollution_panel` `test_contract` `test_handoff`）
**165 綠，43.86 秒**。`pollution.summary()` total 8 / open 8 / guarded 5。
`.forseti/NEXT.md` 12:05:01 自己更新成 8 筆。

全套跑了兩次，**兩次都紅，而紅的對象不一樣**：

    11:42 那次   1523 綠 1 紅（610.43 秒）
                 不在冊：test_declared_only.py、test_literal_restate.py
    單獨跑那兩檔 124 綠（19.20 秒），attribution writers 是空的
    11:56 那次   1537 綠 2 紅（433.72 秒，帶 attribution）
                 不在冊：test_state_changing_writes.py
                 路徑不允許：test_ui_render.py 那一條 → event_ledger.jsonl

兩次紅的對象沒有交集，而且第一次點名的那兩個檔單獨跑完全不碰正本。
attribution 實測 45 個節點動到正本，其中 43 個動到的只有 `cache/` 底下。
成因讀得到：`identity._obs_key`（`identity.py:265`）的快取 key 含 session 檔的
mtime_ns 與 size，當前這條 session 每講一句話就長大，所以每輪都有人重寫快取，
**是誰由執行順序決定**。

所以這一輪沒有把那三個檔加進 `REGISTERED_WRITER_FILES`。
加進去等於用競速結果當證據，而那正是第 8 筆登記的機制。

### 沒有動畫面，也沒有開關 App

這一輪只寫了 `.forseti/pollution.jsonl` 一筆資料，沒有動任何程式碼、
沒有動 `desktop/ui/`，所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`；
三次量測前後 `pgrep -x Forseti` 都沒有回應。

### 還缺什麼

- **`test_ui_render.py::TabsMatchData::test_切過去之後別頁不會同時亮著`
  寫了 `event_ledger.jsonl`**，那不在允許路徑裡。檔案 12:01:04 從
  178364 漲到 179033（+669 位元組），落在第二次全套區間內。
  這一條是真訊號，下一輪先查它。
- **「誰」那一條跟「路徑」那一條對 `cache/` 的態度不一致**：路徑允許，
  在冊卻仍要求。名單來源是觀測，而 `cache/` 寫入者由競速決定，
  所以這張名單追不完。改法明確（只對非 `cache/` 的寫入要求在冊，
  `NEXT.md` 不在 `cache/` 底下所以 `STRANDS_CALLERS` 那條路不受影響），
  但改的是「什麼算紅」的判定，要三組反向驗證加全套，這一輪沒做。
- **兩次全套的總條數不同：1524 對 1539**，`--collect-only` 現在是 1539。
  三個 `parametrize` 的來源都是模組級常數，不是 `.forseti/` 的資料。
  **原因沒查**，所以不寫成結論。
- §40 現在 8 筆全部 OPEN。
- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞、`tools/` 另外兩個靜默站點、
  產品側九個，全部仍然沒修。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** `event_ledger.jsonl` 那條紅。它是這三次量測裡
唯一一個對象沒有隨執行順序變動的紅，而且它動的是重建不回來的正本。

沒有 commit。

## 2026-09-17 13:0x　那條紅不是測試寫的，是 hook 寫的

### 挑了什麼

上一輪結尾指名的那一件：

    event_ledger.jsonl 那條紅。它是這三次量測裡唯一一個
    對象沒有隨執行順序變動的紅，而且它動的是重建不回來的正本。

動手前先確認這條路上沒有既有實作：`tests/` 與 `apps/forseti-cli/`
底下沒有任何 gap／外部寫入者相關的東西，`conftest.py` 與
`test_zz_forseti_write_attribution.py` 裡也沒有。

### 做完什麼

**先重現，再讀內容，最後做對照組。** 三步都是實測不是推論。

一，單獨重跑那一條測試：

    tests/test_ui_render.py::TabsMatchData::test_切過去之後別頁不會同時亮著
    1 passed in 71.32s
    event_ledger.jsonl  181040 → 181709（+669，與上一輪同值）

二，把新增的那 669 位元組讀出來：

    {"provider":"claude-code","provider_event_type":"Stop",
     "payload":{"hook_event_name":"Stop", ...}}

三，**決定性的那一步在 `.forseti/` 以外做。** `hooks/` 複製到一個空的
假 repo，餵一筆 `{"hook_event_name":"Stop"}` 進 stdin，零 pytest，
它就在假 repo 底下寫出 754 位元組結構完全相同的一筆。
hook 自己的 `REPO_ROOT` 是從它所在位置算的
（`forseti-stop-hook.mjs` 的 `resolvePath(HERE, '..')`），所以碰不到正本。

所以寫入者是 Claude Code 的 Stop hook：`.claude/settings.json:19`
→ `hooks/forseti-stop-hook.mjs:112` 的 `el.appendEvent()`。
那一條測試跑 71 秒，只是窗口夠長剛好罩到別的 session 結束一次回合。

**成因是量法本身，不是這個檔。** `conftest.py:237` 記的是
「這條測試前後這個檔有沒有不同」，那是時間窗，時間窗量不到寫入者。
測試跑得越久被誤記的機會越大，所以這個誤差偏向最慢的那幾條，不是隨機的。

改了三個地方：

`tests/conftest.py`（觀測層，只讀不判斷）
新增 `_APPENDED` 與 `_appended()`：檔案純粹長大的時候，把長出來的
那一段位元組讀回來。不驗前綴（理由寫在 docstring：驗前綴要每條測試
前後多跑一次全目錄雜湊）。代價由判斷層吸收，方向是安全的 ——
切在行中間就解不出 JSON，而判斷層解不出來就不放行。
docstring 的「這個量法看不到什麼」補上第二條：它分不出寫入者。

`tests/test_zz_forseti_write_attribution.py`（判斷層）
新增 `_written_by_external_hook()`：判準是內容自己帶的 `provider` 與
`provider_event_type`，不是時間、不是檔名、不是次數。整段每一行
都要是 hook 事件才算，混著就整段不算。`_bad_paths()` 抽出來讓兩條
守門共用，沒帶 `appended` 的時候退回修正前的行為（嚴的那一邊）。

`_evidence()`：紅的訊息帶出擷取到的新增段前 200 字。
這一項是同一輪第二次踩到才加的，見下。

### 同一個機制在同一輪內又咬了一次

第一次全套（帶 attribution）**2 紅**，而紅的對象是新的：

    tests/test_ui_contract.py::StuckKindOnScreen::test_畫面要看得懂ALL_VERIFIED
    → pollution.jsonl（IRREPLACEABLE，重建不回來）

把擷取到的新增段讀出來，是 `pol-a9df072623`，`discovered_at`
換算 12:53:28 —— **那是我自己在全套跑的期間登記的第 9 筆污染記錄**。
單獨跑 `StuckKindOnScreen` 三條，`pollution.jsonl` 一個位元組都沒動。

判斷層的行為是對的：它只放行 hook 寫的，這一筆不是 hook 寫的，
所以沒放行。**錯的是操作，不是守門。**

值得記的是這一次跟上一次的差別：上一次（event_ledger）花了三輪才
查出寫入者，這一次當場就看得出來，差別只在於有沒有新增段可以讀。
所以把 `_evidence()` 加進紅的訊息，是把那個差別交到下一個人手上。

### 驗證結果

**六組反向驗證，每一組都紅得對，還原後全綠：**

    放行邏輯關掉（`if False`）        → test_hook寫的不算在那條測試頭上 紅
    判準永遠回 True                   → 上面那條 + test_這一支抓得到東西 兩條紅
    擷取層永遠回 None                 → 擷取那兩條紅
    擷取層讀不到回 "" 而不是 None     → test_擷取新增段這支自己是對的 紅
    紅的訊息不帶內容                  → test_紅的訊息帶得出寫進去的是什麼 紅
    擷取不到就留白（不明說）          → 同上一條紅

**全套三次：**

    第一次（12:5x）  1546 綠 2 紅 207.46 秒　紅的是我自己寫 pollution.jsonl
    第二次（13:0x）  1549 綠 0 紅 233.70 秒　scan_errors 1（我的測試自己造的）
    第三次（13:1x）  1549 綠 0 紅 180.96 秒　scan_errors 0

第二次那個 scan_errors 也修了：`test_擷取新增段這支自己是對的` 故意
製造一次讀取失敗來驗「讀不到要留記錄」，那一筆留在整場共用的
`_SCAN_ERRORS` 裡，等於在一張用來發現真問題的清單上放一個永遠不會被修
的東西 —— 而一張永遠有東西的清單，跟一張沒有人看的清單是同一張。
改成 `try/finally` 收乾淨，並且多一條斷言確認收乾淨了。

§40 登了第 9 筆 `pol-a9df072623`，OPEN。四處出處逐行開檔驗過。
`propagation_radius` 是 None 加 `radius_basis`，照 §8.3 不編單位。

### 這一輪**沒有**驗到什麼（是前提不是補充）

**真實場景的端到端沒有驗到。** 後兩次全套期間 hook 一次都沒有觸發
（`attr` 裡動到 `event_ledger.jsonl` 的節點是 0，檔案 sha 前後一致），
所以**全綠證明的是沒有回歸，不是證明修正在真實場景下有效**。
修正的有效性目前靠三樣東西撐著：判準與擷取層的單元測試加六組反向驗證、
假 repo 對照組證明 hook 是寫入者、以及那一次可重現的 +669。
要真的端到端驗，得在全套跑的期間讓 hook 往正本寫一筆 —— 那是污染正本，
沒做。

**判斷層只認得 hook 這一種外部寫入者。** 人在全套期間動正本（像這一輪
我自己做的那樣）照樣會被記在當時在跑的那條測試頭上。**這是刻意的**：
放寬到「看起來不像測試寫的就放行」等於用長相判斷，那是 B-05 擋住的做法。
現在的處置是保守放行加上把證據印在紅的訊息裡 ——
誤判仍會發生，但從「追查三輪」變成「讀一行」。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔的 sha256 跟這一輪開始時逐字元一致：
`app.js` `959213f8589a90cf`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `530814ee69c5e6e4`。所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`；
每次量測前後 `pgrep -x Forseti` 都沒有回應。

### 還缺什麼

- **端到端沒驗**（上面那一段）。要驗得想一個不污染正本的辦法，
  例如讓 `conftest.FORSETI_DIR` 可以被指到別處，再起一個迷你 session。
  那是改觀測層的範圍，不是這一輪的範圍。
- **`_WriteSpy` 的 `shutil` 洞與 sqlite 洞**仍然沒補。
- **`tools/` 另外兩個靜默站點**（`claims-audit.assistant_texts` 截斷、
  `owner-audit.main` 沉默地圖整張）、產品側九個，一個都沒修。
- **兩次全套的總條數不同**這件事上一輪留著，這一輪 1549 == 1549，
  但原因仍然沒查，所以不寫成「已經解決」。
- §40 現在 9 筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** 讓 `conftest.FORSETI_DIR` 指得到別的目錄，
然後用一個迷你 pytest session 把端到端補起來（跑一條慢測試，
期間從另一個程序 append 一筆真的 hook 事件進那個假目錄）。
它是這一輪唯一一個「做了但沒驗到」的東西，而沒驗到的修正
跟沒修一樣 —— 差別只在於沒修的那個不會讓人以為修好了。

沒有 commit。

---

## 2026-09-17 13:1x　端到端那條缺口補起來了，而且量到它抓不到什麼

**挑的是哪一項。** 上一輪自己寫下的「下一輪最明確的一件」：

    讓 `conftest.FORSETI_DIR` 指得到別的目錄，然後用一個迷你
    pytest session 把端到端補起來（跑一條慢測試，期間從另一個
    程序 append 一筆真的 hook 事件進那個假目錄）。
    它是這一輪唯一一個「做了但沒驗到」的東西，而沒驗到的修正
    跟沒修一樣 —— 差別只在於沒修的那個不會讓人以為修好了。

挑它不是因為它排在最前面，是因為 ROADMAP 那張 P0 到 P4 的清單
這一刻沒有一項可以直接往下做（逐項狀態在 ROADMAP「這份清單目前
沒有下一項」那一節），而其餘的候選全部在等 owner 決定：
`event_ledger.jsonl` 要不要進 `ALLOWED_TOP_LEVEL`（規格 §3.2 的
可重建性判斷）、`scope_match`、§12.2 五個病症對應、B-03/B-04
訊號打架。等 owner 的那些不准我自己定，那是 §8.3 的禁止捷徑。

### 做法換過一次，理由要一起看

上一輪設想的是往觀測層加一個開關（讓 `FORSETI_DIR` 可以被指到
別處）。**實際做法是複製那一份 `conftest.py` 到假 repo。**
它的 `FORSETI_DIR` 本來就是從自己的位置算的
（`ROOT = Path(__file__).resolve().parents[1]`），所以複製過去
就指到假的那一個，同一件事不必加開關。

差別在於：一個只有測試才走得到的環境變數分支，平常沒有人走，
而沒有人走的路壞了不會有人知道。代價是**驗的是那一份原始碼的
行為，不是 pytest 此刻載入的那個物件**，所以測試第一件事是
逐位元組比對 sha256 —— 不比對的話，哪天有人改了正本 conftest
而這一條照樣綠，那它守的就是一份舊程式碼。

**沒有動 `tests/conftest.py`。** 這一輪結束時它的 sha256
`e802163bb5cff26b40e906f95a545e143ecf291e24298621230f85263238a7f7`
跟開始時逐字元一致（反向驗證期間改過兩次，兩次都還原並比對過）。

### 這一條實際走的鏈有四段

    外部程序寫（node 跑真的 Stop hook，寫假 repo 的事件帳本）
      → conftest 擷取（`_appended` 把長出來那一段讀回來）
      → 判斷層放行（`_written_by_external_hook` 認得 provider 欄位）
      → 名單不點名（`_offending_files` 不把它算在那條測試頭上）

在這之前這四段**各自驗過，接起來沒有走過一次**。

迷你 session 裡那條測試自己一個位元組都不寫 `.forseti/`，
寫的是它起的那個 node 子程序 —— 那正是真實場景的形狀（別的
session 結束一次回合，Stop hook 在這條測試跑的期間接一筆進檔尾），
差別只有時機是確定的而不是碰運氣，而那是驗證要的方向。

**要先 seed 一行進去，理由是實測的。** `pytest_runtest_protocol`
只對「前後都在」的檔擷取新增段（`b is None or a is None: continue`），
所以新建的檔擷取不到內容，判斷層會退回嚴的那一邊。真實場景裡
`event_ledger.jsonl` 一直都在，那一次是長大不是新建。
新建那一種不是漏，是保守方向（多紅不少紅），但它跟這一條要驗的
不是同一題，所以不混在一起。

### 最後那個斷言才是這一條的重點

前三個斷言全綠只證明「這一輪沒有被誤指控」，而它們在放行邏輯
整個被拔掉的時候**仍然可能全綠** —— 只要那一輪 hook 沒寫。
所以第四個斷言反過來問：把內容那一半拿掉，這條測試會不會被點名。
實測 `_offending_files(writers)` 回 `{tests/test_e2e_inner.py}`，
`_offending_files(writers, appended)` 回 `set()`。
答案要是「不會」，那代表放行根本沒起作用，前面三條綠得沒有意義。

### 驗證結果

**五組反向驗證，四組紅得對，一組刻意記下來它抓不到：**

    判斷層不放行 hook（`if False and ...`）   → 端到端紅（第 886 行）
    判準永遠回 True                           → 端到端**綠**，見下
    擷取層永遠回 None                         → 端到端紅（擷取不到）
    觀測層不記錄變動（`_RECORD[...] = []`）   → 端到端紅（第一段沒接上）
    不 seed（事件帳本變成新建檔）             → 端到端紅，訊息指對方向

**第二組是這一輪量到最有用的東西。** 判準永遠回 True 的時候這條
端到端是綠的，因為它的四個斷言沒有一個問「判準會不會放太寬」。
那個方向由既有的兩條守：跑整組的時候
`test_這一支抓得到東西而不是永遠回True` 與
`test_hook寫的不算在那條測試頭上_而別人寫的照算` 一起紅。
**寫下來是因為「端到端過了」很容易被讀成「這條鏈整個有人守」**，
而實際上它守的是接得起來，不是判準的鬆緊。

**全套：1549 → 1550 passed，215.65 秒，0 紅，`scan_errors` 空。**
歸屬記錄裡 30 個節點動到正本，29 個只動 `cache/`，
唯一的非快取寫入是 `NEXT.md`，寫的是已登記的
`test_claims_wiring.py::TestRealSnapshot::test_no_duplicates_within_a_row`。

`sot.verify_bindings()` ok=True、stale 0、drifted 0。

### 這一輪**沒有**驗到什麼（是前提不是補充）

**全套那一次期間 hook 一次都沒有觸發**（`attr_full.json` 裡動到
`event_ledger.jsonl` 的節點是 0），所以真實場景的那一次偶發仍然
沒有在全套裡再現過。**這正是新增這條測試的理由** —— 它不必等
偶發再現，自己造一次同形狀的。但兩者不是同一件事，
所以不寫成「真實場景驗過了」。

**判斷層仍然只認得 hook 這一種外部寫入者。** 人在全套期間動正本
照樣會被記在當時在跑的那一條頭上。這是刻意的，放寬到「看起來
不像測試寫的就放行」等於用長相判斷，那是 B-05 擋住的做法。

**sha256 那一條斷言幾乎永遠綠。** 它守的是「複製這個動作有沒有
成功」，不是「正本 conftest 有沒有被改」—— 複製品是從正本拷的，
正本改了複製品跟著改。寫下來免得下一個人把它當成後者。

### 還缺什麼

- `_WriteSpy` 的 `shutil` 洞與 sqlite 洞仍然沒補。
- `tools/` 另外兩個靜默站點（`claims-audit.assistant_texts` 截斷、
  `owner-audit.main` 沉默地圖整張）、產品側九個，一個都沒修。
- §40 九筆全部 OPEN。
- `renderVitals` 目標那格寫死、B-15、B-03/B-04 訊號打架、`scope_match`、
  §12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`，全部仍然在等 owner。
- `event_ledger.jsonl` 要不要進 `ALLOWED_TOP_LEVEL`，等 owner 決定
  （上一輪查清楚了形狀，決定本身不是實作細節）。
- ROADMAP P0 第 1 項（真的救回一次）仍然卡在 owner 要按的那一步。

**下一輪最明確的一件：** 端到端只走了「hook 寫」那一種形狀，
而**新建檔那一種（擷取不到、退回嚴的那一邊）沒有被任何測試釘住**。
這一輪是靠反向驗證第五組看到它的行為，那是一次手動觀察不是守門。
釘法跟這一條同形：同一個迷你 session 不 seed 跑一次，
斷言它**被點名**而且訊息說得出「沒有擷取到新增段」。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔的 sha256 跟這一輪開始時逐字元一致：
`app.js` `959213f8589a90cf`、`index.html` `dbc4c6fa010e7d0f`、
`app.css` `530814ee69c5e6e4`。所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`；
收尾前 `pgrep -x Forseti` 沒有回應。

只動了一個檔：`tests/test_zz_forseti_write_attribution.py`
（加一條測試、兩個常數、一段內嵌原始碼、兩個 import）。沒有 commit。

## 2026-09-17 13:3x　§39 的中間四步做了，正典答案那個物件長出來了

### 為什麼挑這一項

`ROADMAP.md` 的「真正還有內容的三個方向」第 2 項：§39 反錨定的中間
幾步（P0.2），原文寫「需要先有正典答案這個物件。純工程，不用決定」。

另外兩個方向這一輪都不能動。第 1 項（Probe Packs 另外兩軸）要花錢跑
模型，ROADMAP 自己寫著要 owner 點頭。第 3 項是卡在 owner 身上那五件。

上一輪留下的「下一輪最明確的一件」是再補一條端到端測試的變體。
沒有做那一件，理由是 ROADMAP 那一節點名的：不要把「ROADMAP 沒有
下一項」自動翻譯成「那就再守一層」。Vol4 §12 第一條 Kill Criteria
要 kill 的就是那個膨脹，而上一輪正是守門的守門的守門。

### 做了什麼

新增 `apps/forseti-cli/antianchor.py`，§39 七步裡的第 3 到第 6 步。
`sufficiency.py` 的模組說明本來就寫著它只做了第 2 步與第 7 步，
中間那幾步「要有正典答案這個物件才談得上，那個物件還不存在」。
這一支就是那個物件。

正典答案四欄，照 §39 第 3 步原文點名的四樣，一欄都不是這裡算的：

    state           借 snap["verified"]，交接檔那一節
    priority_order  沒有來源
    blockers        借 contract._blockers_field
    next_action     借 contract._next_step

`priority_order` 的正典是 §41 的 triage 引擎。實際查過，
`apps/forseti-cli/` 底下沒有任何檔提到 triage，所以那一欄回
`NO_SOURCE`，沒有拿 ROADMAP 的章節順序頂替。頂替的話這道門考的
會是「有沒有讀過 ROADMAP」，不是「推導對不對」。

流程六支：`open_derivation`（開卷，不含答案，記下正典 sha 當承諾）、
`submit`（存下推導，只能交一次）、`reveal`（揭曉並比對，沒交卷不揭曉）、
`classify`（四類，只收人標的）、`reconciliation`（和解完成沒有）、
`state` / `can_write`（第 7 步那個布林值，預設不強制）。

### 這一支刻意做不到的三件，寫在模組說明裡不是寫在這裡而已

一，分類不自動判。§39 第 6 步那四類（推錯／正典過期／現實變了／
規則有問題）沒有一個算得出來。同一個「不一樣」，四種解釋都成立，
要選哪一種靠的是去查那個差異背後發生了什麼。自動判一個出來就是
§8.3 的填空捷徑，而 §40 的污染登記簿裡已經有九筆是那樣來的。
所以 `classify()` 的 `by` 必填，標不出來就留在未分類，和解不會完成。

二，兩邊都空不算答對。正典欄位空、受測者交白卷，字串比對會說
「一致」，於是一場什麼都沒驗到的接手考試看起來滿分。這是這一支
最容易造假的地方，所以比對結果有四種不是兩種，`NOT_COMPARABLE`
與 `CANONICAL_MISSING` 都不算進通過。`reconciliation()` 在四欄
全部沒驗到的時候仍然回 `reconciled=True`（流程上確實走完了），
但它的 `why` 自己講出來「一欄都沒有驗到，這一次和解在證據上是空的」。

三，承諾 hash 防的是掉包不是偷看。一個讀得到 `.forseti/` 的 session
自己叫一次 `canonical()` 就看到全部答案。`sufficiency.py` 對自己
那道門說過同一句話，這裡不假裝它擋得住。

### 驗證結果

`tests/test_antianchor.py` 30 條，全綠。

六組反向驗證，六組都紅得對：

    拿掉「沒交卷不准揭曉」        → test_沒交推導不准揭曉 紅
    兩邊都空改成回 SAME           → 2 條紅
    classify 不檢查四類           → test_四類以外的字串不收 紅
    priority_order 拿 ROADMAP 頂替 → test_priority_order沒有正典 紅（共 6 條）
    submit 允許重複交             → test_推導只能交一次 紅
    canonical 自己算 blockers     → test_blockers與next_action借contract 紅（共 4 條）

每一組跑完都還原並比對 sha256，收尾時 `antianchor.py` 是
`055f420d6cbb203e`，跟反向驗證開始前逐位元組一致。

第一次寫測試的時候有兩條預期寫錯了（`next_action` 的正典是
`T-1　把畫面接上去` 含任務 id 與全形空格，不是 `把畫面接上去`）。
修法不是在測試裡抄一份正典的措辭，是從 `canonical()` 取值，
抄的那一份哪天 `contract` 改了行文就會假紅，而假紅的測試最後
都會被關掉。

### 守門那條紅是這個檔案唯一的用處，這一輪它證明了自己

`test_module_write_targets.py::test_每一個寫模式的PathOpen在某處都有人守`
紅了，訊息是 `['antianchor'] 有寫模式的 .open() 但沒有任何地方守它`。
那條測試的 docstring 寫著「這是這個檔案裡唯一一條會隨著程式碼長大的
測試」，這一輪它抓到了新增的第十四個寫入點。

修法是加守門不是加豁免：`GUARDED_HERE` 加一支、`_w_antianchor()`
走公開 API（`open_derivation` 而不是直接 `Log.append`，因為前者
內部會去叫 `canonical()`，而那條路才是真的會跑的）、
`DEFAULT_NAMES` 登記 `antianchor.jsonl`。

反向驗證過：讓 `Log.append` 順手多寫一個檔，
`test_只寫該寫的那一個檔案[antianchor]` 紅。

### 全套跑了兩次，兩次的數字都不能直接讀，理由在下面

    第一次 13:3x    1577 passed / 3 failed / 362 秒
    第二次 13:48    1565 passed / 44 failed / 623 秒

第二次那 44 條裡，41 條是並行干擾。單獨重跑驗過：
`test_ui_render.py` 加 `test_forseti_dir_writes.py` 共 166 條全綠（306 秒），
`test_tempdir_cleanup` 加 `test_sot` 加 `test_workflow` 加
`test_antianchor` 加 `test_module_write_targets` 共 136 條全綠。

干擾的來源是另一個 session 在同一個 repo 上同時工作。可查核的證據：
`find -newermt "13:47"` 在我全套跑的期間（13:48 到 13:58）抓到
`apps/forseti-cli/forseti.py`、`apps/forseti-cli/probemodel.py`、
`tests/test_probemodel.py` 被動過。跑到一半原始碼被換掉。

### 另一個 session 在做 Probe Packs 的模型軸，這件事下一輪要先知道

`apps/forseti-cli/probemodel.py`（15373 位元組，mtime 13:40）不是
我寫的。它的模組說明寫著它蓋 §15 三軸裡的 `models` 與 `contexts`，
也就是 ROADMAP「真正還有內容的三個方向」第 1 項。

兩個 session 同時在同一個 repo 上動 `apps/forseti-cli/`，所以
接下來任何一輪讀到的全套數字都要先問一句「這一輪有沒有人同時在動」。

### 這一輪沒有收掉的一條紅，以及它的精確拆分

`test_literal_restate.py::test_ALL_CAPS那一側的數字沒有被這次改動動到`
穩定紅，期望 `(70, 266)`，實際 `(72, 290)`。

拆分是量出來的，不是推的（把檔案移開再掃一次）：

    基線（兩個新模組都移開）      70 enums / 266 members
    加回 probemodel.py            71 / 286    （+1 / +20）
    加回 antianchor.py            72 / 290    （+1 / +4）

沒有去改那個數字。兩個理由。一，改了等於替另一個 session 的改動
簽名，而它那 20 個成員我沒驗過。二，那個 session 可能正在同一個
測試檔上工作，同時改會互相覆蓋。

守門本身是綠的：`up.unexempted` 是空的，`stale_exempt` 是 0，
也就是沒有任何疑似打錯被放過。紅的只有基線數字。

收它的人有現成的數字可以用，不必再量一次。

### 還缺什麼

這一支沒有接 CLI，也沒有接畫面。`forseti.py` 正被另一個 session
改，同時動會衝突。而且在有人真的走過一次流程之前，畫面上那一格
會是空的，ROADMAP 寫著「接上去畫面不會變的東西，接了就是白工」。

所以它現在是一個可呼叫但沒有入口的模組。這是缺口，不是設計。

其餘仍然在等 owner 的：`scope_match`、§12.2 五個病症對應、
兩件 workflow 的 `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`、
`renderVitals` 目標那格寫死、B-15、B-03 與 B-04 訊號打架、
`event_ledger.jsonl` 要不要進 `ALLOWED_TOP_LEVEL`、
ROADMAP P0 第 1 項（真的救回一次）那個 `dry_run=False`。

§40 九筆全部 OPEN。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔一個位元組都沒動，所以沒有 build 也沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

動到的檔兩個新增（`apps/forseti-cli/antianchor.py`、
`tests/test_antianchor.py`）、一個修改（`tests/test_module_write_targets.py`）。
沒有 commit。

---

## 2026-09-17 18:0x-18:3x　那個沒有入口的模組接上了，接的時候撞到兩個會讓它永遠空轉的東西

### 挑這一項的理由，以及為什麼它不是「再守一層」

`ROADMAP.md` 17:51 那一節寫著「真的沒有可以自己往下做的產品功能了」，
三件都要 owner 開口。**那一節漏了一件。** 上一輪（13:3x）自己在
「還缺什麼」裡寫著：

    這一支沒有接 CLI，也沒有接畫面。⋯⋯
    所以它現在是一個可呼叫但沒有入口的模組。這是缺口，不是設計。

而 `forseti.py` 模組說明的最後一句是「一個沒有入口的機制等於不存在」，
那句話底下記的正是同一個形狀的事故（`auto_dispatch()` 寫好也測過，
從來沒被真正的工作呼叫過一次，continuity 長期是 0）。

上一輪不接的理由是 `forseti.py` 正被另一個 session 改，同時動會衝突。
那個理由這一輪不成立了：`forseti.py` 的 mtime 是 13:47，
`probemodel.py` 13:47，四個多小時沒動。

**畫面那一半仍然沒接**，理由跟上一輪一樣而且是 ROADMAP 自己寫的：
沒有人真的走過一次流程之前，那一格會是空的。

### 先確認過沒有重做

    grep -rn "antianchor" --include="*.py" --include="*.js" --include="*.rs"

`forseti.py` 一次都沒提到它，`desktop/` 底下也沒有。確定是缺入口，
不是入口在別的地方。

### 做了什麼

`antianchor.py` 尾段加 CLI，六個 sub-command，全部是上面那六支的轉接，
**這一節沒有任何新判斷**：

    antianchor status                  這條線走到第幾步
    antianchor open                    第 3 步，出一張不帶答案的卷
    antianchor submit <did>            第 4 步，stdin 收 JSON
    antianchor reveal <did>            第 5 步，揭曉並比對
    antianchor classify <did> <欄> <類> --by <誰>    第 6 步
    antianchor show <did>              和解到哪裡

`forseti.py` 接 dispatch 並在用法那一段列出來。**不併進 `gate`**：
那一支做的是 §39 第 2 步與第 7 步（考讀懂沒有、給不給寫入權），
這一支做的是中間那段獨立推導與和解。共用一個指令名會讓「考過了」
變成兩種意思。

### 接的時候撞到第一件：`state` 那一欄永遠是空的

`antianchor.canonical()` 的模組說明寫著

    | `state` | `snap["verified"]`，`desktop_api._write_handoff` 算的那一份 |

實測 `strands()` 的 snap **沒有 `verified` 這個 key**。
那個 key 只存在於 `_write_handoff()` 的區域變數裡。所以照模組說明
去拿的呼叫端，拿到的永遠是空清單，四欄全部 unanswerable，
一場什麼都沒驗到的接手考試。

量出來的：

    canonical(strands(), work())["answerable"]        []
    四欄狀態                     state EMPTY / priority_order NO_SOURCE
                                 / blockers EMPTY / next_action EMPTY

**這個形狀在同一個檔案裡已經被抓到過一次。** `desktop_api.py`
`_write_handoff()` 裡 `blk_lines` 那一段的註解自己寫著：

    **自己叫 `_blockers()`，不從 snap 拿。** `snap["blockers"]` 只存在於
    `snapshot()`⋯⋯從 snap 拿的版本跑起來不會壞，只會永遠給空清單 ——
    一個什麼都不做而且不報錯的接線，正是⋯⋯那種白工。

修法不是在 CLI 裡重算一份 —— 那會變成第二個事實來源，兩份遲早分歧，
而分歧那天不會有錯誤訊息。做法是把 `_write_handoff()` 裡那四行抽成
`desktop_api.verified_lines(snap)`，`_write_handoff()` 改成叫它，
CLI 的 `_live()` 也叫它。**一份算法，兩個呼叫端。**

抽出來之後實測：

    verified_lines(strands())                ['必讀文件 20/30 讀完']
    canonical(...)["answerable"]              ['state']

那一行跟 `NEXT.md` 的「已驗證的狀態」那一節逐字一致，
因為它就是同一支算的。

`blockers` 與 `next_action` 這兩欄仍然 EMPTY，**那不是 bug**：
帳本裡被標成 blocked 的步驟此刻 0 筆、兩件任務的步驟全部驗證完成
所以沒有東西可以派。那是真實狀態，報得對。

### 撞到第二件：考卷把答案印在上面

對真正的 repo 跑一次 `open`，印出來的是

    ○ next_action　下一個安全的動作（next safe action）
        這一欄此刻是空的：2 件任務（T-7da5ef2183、T-b95303aaa2）的步驟
        **全部驗證完成**了，所以沒有東西可以派 ——⋯⋯

**那句話就是答案。** §39 第 3 步要受測者自己推出「下一個安全的動作
是什麼」，而考卷直接告訴他「沒有東西可以派，在等收尾」。

區分在哪裡量得出來：`NO_SOURCE` 的理由是結構性的
（§41 的 triage 引擎沒有實作），講出來不漏答案，而且不講的話
受測者會白推導一欄；`EMPTY` 的理由講的是「為什麼此刻是空的」，
那是內容，屬於第 5 步。

所以 `NO_SOURCE` 照印，`EMPTY` 只印一句「這一欄此刻是空的，
為什麼空是答案的一部分，揭曉的時候才說」。

**先前那條測試抓不到這個。** `test_考卷上不准出現任何一欄的正典值`
找的是正典的 `value`，而空欄位的 value 是 None，字串比對永遠找不到
東西 —— 那條測試會一路綠著讓答案漏出去。所以另外加一條守理由那一段。

### 考卷上也印出這道門擋不住的兩件事

一，防不了偷看。讀得到 `.forseti/` 的人自己叫一次 `canonical()`
就看到全部答案。模組說明本來就這樣寫，但寫在模組說明裡而沒印在
用的人眼前，等於沒寫。

二，`open` 這個動作本身會叫 `strands()`，而它尾段的 `_write_handoff()`
會重寫 `.forseti/NEXT.md` —— 那份裡面就有這四欄的答案。
**這是這個入口自己造成的漏，不是繼承來的**，所以印在考卷上。

### 驗證結果

    tests/test_antianchor_cli.py          20 條，全綠
    全套                                  1632 passed / 0 failed / 284.66 秒

六組反向驗證，六組都紅得對，而且紅的是對的那一條：

    考卷印出正典的 value              → test_考卷上不准出現任何一欄的正典值 紅
    考卷印回 EMPTY 的理由             → test_空欄位的理由不准印在考卷上 紅
    拿掉 forseti.py 的 dispatch       → test_forseti_antianchor轉得到這一支 紅
    _write_handoff 自己再算一份       → test_verified_lines跟交接檔用的是同一支 紅
    submit 把壞 JSON 當白卷收下       → test_讀不懂的推導不准當成白卷收下 紅
    classify 的 --by 自己補預設值     → test_沒有by的分類CLI要擋 紅

每一組跑完都還原並比對 sha256，三個檔逐位元組跟反向驗證前一致。

寫測試的時候有一條預期寫錯了：`test_一次完整的流程走得完`
只分類了 `state` 一欄就斷言和解完成。實際要分類三欄 ——
**沒答的欄也是差異**（有正典、受測者沒答），不分類就算和解完成的話，
交白卷是最快的過關法。改的是測試不是程式，而且改成逐欄斷言
「分到第 n 欄的時候還不准說完成」，這樣以後有人把那條放寬會紅。

### 全套第二次跑出過兩條紅，第三次同一份程式碼全綠，成因沒有定論

    18:0x 第一次      1631 passed / 0 failed / 245 秒
    18:1x 第二次      1630 passed / 2 failed / 346 秒
    18:2x 第三次      1632 passed / 0 failed / 284 秒

兩條都在 `test_zz_forseti_write_attribution.py`
（`test_NEXT_md的寫入次數不超過節流窗開過的次數` 與
`test_動到的路徑全部在允許範圍內_而且這是最後一條`）。
單獨跑那個檔 20 條全綠。

**沒有定論，不填成因。** 查得到的事實兩件：一，第二次跑之前我對
真正的 repo 跑過兩次 `antianchor open`，而 `open` 會叫 `strands()`、
`strands()` 尾段會寫 `NEXT.md`，也就是在全套之外動過正本；
二，那個檔自己的訊息寫著「這個量法分不出寫入者，全套跑的期間有人
動正本的話會被記在當時在跑的那一條頭上」。

第一件是我做的，時序上對得上，**但我沒有量過它就是成因** ——
節流窗被我關掉的話方向應該是寫得更少不是更多，跟「寫入次數超過」
反過來。查過同一段時間沒有別的 session 在動這個 repo
（`find -newermt "17:30"` 只列出我自己動的檔與測試自己寫的快取）。

留給下一輪的具體做法：對真正的 repo 跑一次 `antianchor open`
之後立刻跑全套，看得不得到同樣兩條。復現得到就是我造成的，
復現不到就是那個量法本身間歇。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 三個檔一個位元組都沒動（最新 mtime 12:25，早於這一輪），
所以沒有 build 也沒有 deploy。全程沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。`ps aux | grep Forseti.app` 是 0。

### 這一輪刻意沒做的一件

**沒有對真正的帳本走一次 §39 流程。** 技術上跑得動，但這一輪我已經
讀完 `NEXT.md` 才開始工作，所以我的「獨立推導」是被錨定的 ——
拿它去登記一次 PASS，記下來的會是一筆假的接手紀錄，
而 §39 開頭那一句要防的正是這個。

第一次真的走這個流程，該是一條還沒讀過 `NEXT.md` 的 session。
`--root` 指到別的地方跑過（正典來自真 repo、帳本落在暫存），
所以畫面上那個渲染是真的看過的，不是想像的。

### §40 登了兩筆，而且登記簿自己擋了我第一次的寫法

兩筆都是這一輪被推翻的、原本以斷言句型寫在檔案裡的話：

    antianchor 的 state 借 snap["verified"]   → strands() 沒有那個 key
    P0-P4 查過了真的沒有下一項                → 漏了不需要 owner 的那一件

第一次呼叫 `pollution.record()` 兩筆都被退回，訊息是
「propagation_radius 沒給就要講 radius_basis」。**這是它該做的事** ——
規格沒有定義那個欄位的單位，所以不准留一個沒有說明的空值。
補上界線之後才收：第一筆的界線是量出來的（被修之前 grep 全 repo
沒有任何呼叫端，所以沒有下游數字吃過它），第二筆的界線寫明沒量
（要判斷每一輪是不是因為那句話才停手，得讀每一輪的推理過程）。

登記簿 9 → 11 筆，有守的 6 → 8。`NEXT.md` 18:34 重生成，那一節跟著變成 11。

### 動到的檔

    apps/forseti-cli/antianchor.py      513 → 752 行，加 CLI
    apps/forseti-cli/forseti.py         dispatch 一段、用法一行
    apps/forseti-cli/desktop_api.py     抽出 verified_lines()
    tests/test_antianchor_cli.py        新增 334 行 20 條
    .forseti/pollution.jsonl            兩筆
    .forseti/ROADMAP.md                 記下那一句被推翻，以及怎麼避免再犯

沒有 commit。

收尾時全套再跑一次確認：**1632 passed / 0 failed / 273.94 秒**。

### 還缺什麼

- **畫面那一半**。等有人真的走過一次流程，那一格才有東西可看。
- **`AXES_COVERED` 仍然只有 `versions`**，`claude` CLI 的 OAuth
  要 owner 自己重新登入，這一輪沒有動它。
- 上面那兩條間歇紅的成因。
- 其餘仍然在等 owner 的：`scope_match`、§12.2 五個病症對應、
  兩件 workflow 的 `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`、
  `renderVitals` 目標那格寫死、B-15、B-03 與 B-04 訊號打架、
  `event_ledger.jsonl` 要不要進 `ALLOWED_TOP_LEVEL`、
  ROADMAP P0 第 1 項那個 `dry_run=False`。
- §40 九筆全部 OPEN。

---

## 2026-09-17 18:4x-19:1x　兩條間歇紅查出一條的成因，另一條證明了它不可能是同一件事

### 挑了什麼，怎麼挑的

照 `ROADMAP.md` 自己寫的那一步做：讀 `AUTO_CONTINUE_LOG.md` 上一輪的
「還缺什麼」，逐項問「這一項要 owner 開口嗎」。五項裡四項要她
（畫面那一半要有人先走過流程、`AXES_COVERED` 要她重新登入、
`scope_match` 那一串、§40 九筆），剩下一項不要：
**那兩條間歇紅的成因**，而且上一輪已經寫好復現做法。

### 上一輪寫的復現做法跑了，沒有復現

    18:44:50  antianchor open 兩次（正本），NEXT.md 寫到 18:44:56
    18:44:58  全套開跑
    18:49:22  1632 passed / 0 failed / 264.26 秒

所以「我上一輪在全套之外動過正本」這個時序上對得起來的嫌疑，
**復現不出來**。上一輪自己標明沒量過它是成因，這一輪的結果跟那個
保留一致。

### 換一種量法：不要再擲骰子，去量「誰碰得到」

觀測「這一輪誰真的寫成了」看到的永遠是贏了 240 秒節流競速的那一條。
所以改量另一件事：**哪些測試碰得到 `handoff` 的寫入閘門**，
這一組跟節流窗與執行順序無關。

做法是一個不改變行為的 pytest 外掛（暫存檔，沒有進 repo）：
`handoff.should_write` 與 `handoff.write` 照原樣呼叫、照原樣回傳，
只記下當下是哪一條測試在跑、目標是哪一個路徑。

    碰到閘門的測試 16 條，呼叫 52 次，依檔案：

        34  tests/test_ui_render.py                  在冊
         6  tests/test_handoff.py                    在冊
         4  tests/test_forseti_dir_writes.py         在冊
         3  tests/test_state_changing_writes.py      不在冊 ←
         3  tests/test_zz_forseti_write_attribution.py  目標是暫存路徑，不算
         1  tests/test_claims_wiring.py              在冊
         1  tests/test_sot.py                        在冊

`test_zz` 那三次的目標印出來是 `pytest-of-norikaoda/pytest-567/...`，
碰的不是正本，所以它不進名單。**這一步是分得出來的關鍵** ——
只數次數的話它跟真正的寫入者長得一樣。

### 決定性復現：讓窗開著，紅的正是那一條

    NEXT.md 齡 246 秒（> MIN_GAP_S 240，窗開著）
    pytest tests/test_state_changing_writes.py tests/test_zz_forseti_write_attribution.py

    FAILED test_NEXT_md的寫入次數不超過節流窗開過的次數
    AssertionError: tests/test_state_changing_writes.py::test_act標記checkpoint
                    只落一筆而且不碰控制檔以外的東西 寫了 NEXT.md 但不在冊
    1 failed, 31 passed

不是推論出來的形狀，是讓條件成立之後紅出來的。

### 它為什麼躲得掉，兩個來源的盲區剛好重疊

那張名單有兩個來源，兩個都看不到這個檔：

一，**觀測**。節流 240 秒，一輪最多一兩條寫得成，
    看得見的永遠是贏了競速的那一條。

二，**`_scan_strands_callers()`**。它掃的是直接呼叫 `strands()` 的地方，
    而這一條隔著 `act()` 與 `_checkpoint_now()` 兩層。那支掃描器自己的
    docstring 第二條就寫著看不到間接一層以上的呼叫 —— 不是它壞了，是範圍。

**兩個盲區重疊在同一個檔上**，於是它兩邊都不在。上一輪補的 AST 掃描
關掉的是第一個洞，這個檔落在第二個洞裡。

### 第二條紅：證明它不可能跟第一條同因

`NEXT.md` 在 `ALLOWED_TOP_LEVEL` 裡（`test_zz:164`），
所以 `_allowed("NEXT.md")` 回 True，`_bad_paths` 永遠跳過它。
**一次 `NEXT.md` 的寫入紅得了第一條，紅不了第二條。**

決定性復現那一次也印證了：只紅第一條，第二條從頭到尾是綠的。

所以上一輪把兩條紅寫成一件待查的事，那個綁法本身是錯的。
第一條的成因這一輪結了，**第二條仍然未知，不准算結**。

### 改了什麼

名單加一筆 `tests/test_state_changing_writes.py`，附上量到的理由。
不改成「不碰正本」：那一條測的正是「按一下標記會不會偷偷動到別的東西」，
走的必須是真的那一條路。

它不進 `STRANDS_CALLERS`，因為那一組的定義是直接呼叫點，
塞進去會讓它跟掃描結果對不起來，而那正是它守的東西。

新增一條測試釘住登記理由：
`test_state_changing_writes.py::test_標記那一下碰得到正本交接檔_所以它在冊`。
它自己不寫正本 —— `should_write` 換成「記下目標、回 False」，
整條路照樣走完只是不落檔。不攔 `write()`：那樣就分不出
「走到了閘門但被節流擋住」跟「根本沒走到」，而要驗的正是前者。

### 反向驗證第一次失敗，而失敗本身是這一輪最重要的產出

第一次的反向驗證是把 `_checkpoint_now:1901` 的 `_safe(strands, {})`
改成 `snap = {}`，預期新測試會紅。**結果 13 條全綠。**

印堆疊才看到真正的形狀，是三條路不是一條：

    _checkpoint_now:1901 → strands:3441 → _write_handoff:1807
    _checkpoint_now:1926 → audit:733 → strands:3441 → 同上
    _checkpoint_now:1926 → audit:739 → strands:3441 → 同上

三條共用的出口是 `strands()` 尾段 `:3441` 的 `_write_handoff(snap)`。
斷在那裡重跑：**只紅新的那一條，同檔另外 12 條全綠**，
還原後 `desktop_api.py` 的 sha256 跟動之前逐位元組一致
（`0ee711601490f25d…`）。

寫錯的那段註解當場改掉了。**要是沒做反向驗證，
檔案裡會留下一段讀起來很具體、指得出行號、而且是錯的因果。**

### 驗證結果

    登記前，窗開著        1 failed / 31 passed　紅的是「不在冊」
    登記後，窗開著        33 passed　同樣條件不再紅
    全套                  1633 passed / 0 failed / 181.70 秒

全套從 1632 變 1633，多的一條是新加的那條。

### §40 登了兩筆

    act('checkpoint') 走正本的路是 :1901 那一條    → 是三條，:1901 與 audit 的 :733/:739
    那兩條間歇紅是同一件事                          → NEXT.md 在白名單裡，第二條紅不了

第一筆的 radius 是量出來的 0（那句話只活在同一輪寫下的兩段註解裡，
兩段都改掉了，grep 全 repo 沒有下游讀過它）。
第二筆是 1（上一輪的「還缺什麼」把兩條綁成一項，這一輪照那一項開工）。

登記簿 11 → 13 筆，有守的 10 筆。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 一個位元組都沒動，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 動到的檔

    tests/test_zz_forseti_write_attribution.py   名單加一筆加理由
    tests/test_state_changing_writes.py          新增一條測試
    .forseti/pollution.jsonl                     兩筆

沒有 commit。

### 還缺什麼

- **第二條間歇紅（`test_動到的路徑全部在允許範圍內_而且這是最後一條`）
  的成因還是未知。** 這一輪只證明了它不可能是 `NEXT.md` 造成的。
  下一輪的具體做法：它紅的時候訊息裡會帶「寫進去的是什麼」，
  要的是那一段原文 —— 所以下次看到它紅，**先把完整訊息留下來再做別的**，
  不要只記「兩條紅」。可疑的路徑是 `.forseti/` 底下不在
  `{NEXT.md} ∪ cache/` 裡的那些（`event_ledger.jsonl` 的 append
  已經被內容歸因放行了，`declarations.json` 那種整檔覆寫沒有）。
- **間接呼叫者仍然只能靠觀測或人去發現。** 這一輪是用外掛量出來的，
  那個外掛沒有進 repo —— 刻意的：ROADMAP 自己寫著不要再守一層
  （設計演進史 §2、Vol4 §12 第一條 Kill Criteria）。
  這是已知的洞，不是遺漏。
- 其餘仍然在等 owner 的那一串沒有變：`AXES_COVERED` 要她重新登入、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格寫死、B-15、
  B-03 與 B-04 訊號打架、`event_ledger.jsonl` 要不要進 `ALLOWED_TOP_LEVEL`、
  ROADMAP P0 第 1 項那個 `dry_run=False`、畫面那一半。
- §40 十三筆全部 OPEN。

### 收尾時那個「App 開著」的假警報，以及查它的指令本身有問題

收尾檢查跑 `ps aux | grep -c '[F]orseti.app'` 回 **2**，而同一輪開頭
（18:44）回 0。我沒有開過 App，所以先當成有人開了。

查出來是假的：`pgrep -fl "Forseti.app/Contents"` 一個都沒有。
那個 2 是**這道檢查自己的兩行 shell 命令列**，因為命令列裡就帶著
`Forseti.app` 這串字，`ps aux` 看得到它自己。
`[F]orseti` 這種寫法躲得掉單一 grep 程序，躲不掉外層 zsh 把整條
指令原文帶在命令列上。（另外 `.` 沒跳脫，會多吃一個任意字元，
所以 `Forseti/apps` 這種路徑也算命中，這是第二個洞。）

**這件事要記下來的理由**：owner 明令不准開關 App，而
「`ps aux | grep Forseti.app` 是 0」正是用來證明有遵守的那句話。
一個會在沒開的時候回非零的量法，讓「我沒開」跟「我開了」看起來一樣。
方向是假陽性不是假陰性，所以上一輪那個 0 仍然成立 ——
但下一輪要證明「沒開」，用 `pgrep -fl "Forseti.app/Contents"`，
不要用 `ps aux | grep`。

這一輪全程沒有開也沒有關 App。


## 2026-09-17 19:2x-19:4x　第二條間歇紅的成因查出來了，用的是決定性復現不是推論

挑這一項的理由照 ROADMAP 那一節寫的辦法：讀上一輪「還缺什麼」，
逐項問一句「這一項要 owner 開口嗎」。第一項不要她開口，所以是它。

### 上一輪交代的做法沒有照做，換了一個能拿到更多東西的

上一輪寫的是「下次看到它紅，先把完整訊息留下來」。那是等它自己紅，
而它是間歇的 —— 這一輪第一次全套（19:22 開跑，1633 passed / 177 秒）
就是全綠，等不到。

換的做法是 `conftest.pytest_sessionfinish` 那個出口：
設 `FORSETI_WRITE_ATTRIBUTION_OUT` 就把整輪的變動記錄與新增段全部倒出來。
**它比紅訊息多的東西是沒觸發紅的那些也留著**，而紅訊息只印犯規的。

第一次全套倒出來的結果乾淨得可疑：

    25  cache/artifact_hashes.json
     3  cache/identity.json
     1  NEXT.md

三個路徑全部在白名單內，27 條測試有變動，0 個犯規。
**所以正常情況下沒有測試會寫白名單外的路徑** —— 那條紅要紅，
需要的是別的東西。

### 決定性復現：外部在全套跑的期間往 `.forseti/` 放一個新檔

做法：背景開跑全套（19:27:33），跑到 79% 左右（19:28:4x）從外部
建 `.forseti/probe_second_red.jsonl`，幾秒後再讓它長大一行。
全套跑完 `1 failed, 1632 passed / 174.28 秒`，紅的正是第二條：

    AssertionError: 有測試動到不該動的正本：
    {'tests/test_state_changing_writes.py::test_act標記checkpoint只落一筆而且不碰控制檔以外的東西':
        ['probe_second_red.jsonl'],
     'tests/test_state_changing_writes.py::test_標記那一下碰得到正本交接檔_所以它在冊':
        ['probe_second_red.jsonl']}

    寫進去的是什麼（先看這個再判斷是不是這條測試寫的）：
    probe_second_red.jsonl: 沒有擷取到新增段（不是 append，或太大）　
    probe_second_red.jsonl 接上去的是:{"probe":"second-red-repro","step":2,...}

**那兩條被點名的測試完全無辜**，它們連 `probe_second_red.jsonl`
這個名字都不知道。這就是那個檔自己訊息裡寫的那句話成真：
「這個量法分不出寫入者，全套跑的期間有人動正本的話會被記在
當時在跑的那一條頭上」。

所以第二條紅的成因是：**在全套跑的期間，有東西在 `.forseti/` 底下
寫了白名單外的路徑。** 不是測試寫的，是外部寫的。

探測檔跑完刪掉了，`.forseti/` 頂層清單比對回原狀。
全程沒有改任何既有正本檔（試過對 `advice_ledger.jsonl` append 再還原，
被權限擋下來，改成建新檔這條不碰既有檔的路）。

### 18:1x 那一次是不是同一個成因，**不寫成定論**

18:1x 那一輪的紀錄寫著：第二次全套之前對真正的 repo 跑過兩次
`antianchor open`。讀原始碼確認 `antianchor.py:247` 的
`self.path = Path(root) / ".forseti" / LOG_NAME`，寫的是正本
`antianchor.jsonl` —— 白名單外路徑，形狀對得上。

**但那一次的紅訊息原文沒有留下來**，所以對得上的只有形狀，不是同一件事。
這一輪證明的是機制可重現，不是 18:1x 那一次的身份。

### 同一個機制的第三個實例，而且它現在防不了

`hooks/forseti-declare.mjs:27` 與 `hooks/forseti-stop-hook.mjs:75`
都會寫 `.forseti/declarations.json`。那個檔此刻不存在（`find` 找不到），
但兩支 hook 在，條件到了就會建。

它跟 `event_ledger.jsonl` 的差別是形狀：後者是 append，
內容歸因 `_written_by_external_hook()` 放得了行；
`declarations.json` 是整檔覆寫，從 `before_size` 讀起會切在行中間，
解不出 JSON，判斷層的規則是解不出就不放行。
**所以它一旦被寫就是一條紅，而且是無辜的紅。**
這是已知的洞，這一輪不修 —— 修它要決定「hook 寫的正本要不要一律放行」，
那是 owner 的決定（跟 `event_ledger.jsonl` 要不要進
`ALLOWED_TOP_LEVEL` 是同一題）。

### 改了什麼：訊息裡那句窮舉是錯的

復現那一次的訊息裡，**同一個檔印了兩種話**：前一條測試印
「沒有擷取到新增段（不是 append，或太大）」，後一條印出內容。
兩句都對，但前一句的真正原因不在那兩個選項裡 ——
那一刻這個檔剛被建出來，新出現的檔沒有「之前」可以比。

這個差別會改變下一個人去查什麼：新出現的要問「誰建的」，
整檔覆寫的要問「原本那一段去哪了」。混成一句，只會往後者找。

    tests/conftest.py       `_created(before, after)` 純函式 + `_CREATED`
                            + `created_record()`，dump 多一個 "created" 欄
    tests/test_zz_...py     `_evidence` 多吃一個 created，擷取不到分兩種說法

`_created` 抽成跟 `_diff` 同層級的純函式而不是寫在呼叫點裡，
理由是寫在呼叫點測不到 —— 而它要是算成「改過內容的也算新出現」，
訊息會把每一個變動都送去錯的方向，那正是它要修的東西。

**`created` 只改措辭，不放行任何東西。** 新出現的檔一樣算動到正本，
外部把東西放進 `.forseti/` 正是要紅的那件事。有一條測試專門守這件事。

### 新增三條測試，四組反向驗證都紅得對

    test_新出現的路徑算得出來_而且跟改過內容的分得開
    test_擷取不到的兩種原因在訊息裡分得出來
    test_created不准放行任何東西

反向驗證：

    `_created` 改成回 `_diff` 的結果          → 第一條紅
    `_evidence` 忽略 created                  → 第二條紅
    `_evidence` 永遠用新建那句                → 第二條紅
    `_bad_paths` 有內容就放行                 → 第三條紅 + 既有的 hook 那條紅

每組還原後比對 sha256，兩個檔逐位元組跟動之前一致
（`f88a44998c53a44a…` / `61fe66dbdd1c8277…`）。

### 驗證結果

    tests/test_zz_forseti_write_attribution.py   23 條全綠（原 20 + 新 3）
    全套                                          1636 passed / 0 failed / 164.92 秒

全套從 1633 變 1636，多的三條是新加的。

### §40 登了一筆

    擷取不到新增段的原因是「不是 append，或太大」
    → 還有第三種：這個檔是在那條測試期間新出現的，
      呼叫端的 `if b is None or a is None: continue` 讓 `_appended()`
      根本沒被呼叫到，它的兩個 return None 路徑一個都沒走

機制是：**把函式的 return 點當成結果的全部可能性**。
讀完 `_appended()` 的人會覺得原因已經數完了，而第三條路在呼叫端，
是一個 continue，不在那支函式的視野裡。

radius 量出來是 0（grep 全 repo，那句話只活在 `_evidence` 自己那一行，
沒有下游吃過它）。**radius 0 說的是沒有人吃過它，不是它無害** ——
復現那一次要不是同一份訊息裡另一條印出了內容可以對照，
它會把人送去查「原本那一段去哪了」。

登記簿 13 → 14 筆，有守的 10 → 11 筆。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 一個位元組都沒動，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。
照上一輪查出來的辦法用 `pgrep -fl "Forseti.app/Contents"` 驗，
不用 `ps aux | grep`（那個量法會數到自己的命令列）。

### 動到的檔

    tests/conftest.py                            `_created` + `_CREATED` + `created_record()`
    tests/test_zz_forseti_write_attribution.py   `_evidence` 分兩種說法 + 3 條測試
    .forseti/pollution.jsonl                     1 筆

沒有 commit。

### 還缺什麼

- **`declarations.json` 被寫的那一天會是一條無辜的紅**，上面寫了理由。
  要修得先決定「hook 寫的正本要不要一律放行」，那是 owner 的決定。
  跟 `event_ledger.jsonl` 要不要進 `ALLOWED_TOP_LEVEL` 是同一題，
  兩個一起問比較省她一次開口。
- **18:1x 那一次的身份仍然未知**，這一輪只證明了機制可重現。
  要結它得有那一次的紅訊息原文，而那個沒有留下來。
  **建議不要再追**：機制已經知道，成本高而拿得到的只是身份。
- **間接呼叫者仍然只能靠觀測或人去發現**，跟上一輪一樣，是已知的洞。
- 其餘在等 owner 的那一串沒有變：`AXES_COVERED` 要她重新登入、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格寫死、B-15、
  B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個 `dry_run=False`、畫面那一半。
- §40 十四筆全部 OPEN。

---

## 2026-09-17 19:5x　阻塞身上的第三個訊號：它被放在哪一段

**挑了什麼，以及為什麼不是「再守一層」。** ROADMAP 自己寫的規則是
「判斷清單空了之前，先讀 `AUTO_CONTINUE_LOG.md` 最後一輪的『還缺什麼』，
逐項問一句這一項要 owner 開口嗎」。逐項問完的結果是全部要她開口，
或者上一輪自己寫著「建議不要再追」。所以這一輪不是從那張清單長出來的，
是從一件對不上的事長出來的。

### 對不上的那件事

`.forseti/BLOCKERS.md` 有一個一級標題 `# 已解除`，底下第一句寫著

    放在這裡的不再是阻塞，`forseti doctor` 不會算進去。

而 B-17（`RAW_INLINE_LIMIT` 宣稱的行為沒有人執行）就在那一句下面 6 行，
它自己的本文寫著「**擋住：** worker 隔離層那句『packet 擋得住巨大原始輸出』」，
結尾寫著「選哪一個是 owner 的決定」。一條在等 owner 決定的阻塞，
被放在「不再是阻塞」的區段裡。

實測兩支程式對同一個檔案回不同的數字，兩邊都不報異常：

    forseti.extract_blockers（forseti doctor 用的）      8 條
    desktop_api._blockers                               open 11 條

差的三條是 B-17、B-14、B-13，全部放在 `# 已解除` 底下而本文還寫著擋住什麼。
`forseti.py:196` 在 `# 已解除` 那一行 `re.split` 把檔案切掉，所以那邊數不到；
`desktop_api._blockers` 完全不看區段，逐條判本文，所以那邊數得到 ——
**但它也看不出有任何不一致**，那三條在它眼裡是三條乾淨的未解除。

### 機制：位置是一個沒有文字的宣告

`_blocker_sections` 是逐行掃的，`# 已解除` 那一行每一輪都被讀進來，
然後當成一行普通文字丟掉。資料流經過它，判斷層沒有問過它。

訊號的清單當初是照著「一條阻塞自己寫了什麼」列出來的，
於是只列得出本文裡的東西。而區段不是這一條自己寫的，是它被放在哪裡。

### 改了什麼

    apps/forseti-cli/desktop_api.py
      _blocker_sections()   每一節多一個 in_resolved_section
      _blockers()           第三個訊號 by_section；多回一個 misfiled
      _blocker_lines()      多一行講後果；「兩個訊號」那句改掉

**區段單獨不准關掉任何一條。** 關閉的條件還是標題與擋住欄兩邊都說結束，
跟 2026-09-16 那一版一樣。理由是區段是三個訊號裡最弱的：它記的是
「有人把這一段搬到哪裡」，而搬動是一次手動動作，本文一個字都不必改。
讓它有關閉權等於「搬過去就算解除」，那正是要抓的東西。

所以數字一個都沒有變：open 還是 11、closed 還是 6。變的是打架的
從 2 條變 5 條，以及多出一行講出後果。**沒有自動降級，照舊。**

`said_closed_by` 從單一字串改成多個用「、」串。單一訊號的時候字串
跟改之前一模一樣（`"標題"` / `"擋住欄"`），所以既有兩條斷言不用動。

### 驗證結果

    tests/test_blockers.py     22 條全綠（原 15 + 新 7）
    全套                        1643 passed / 0 failed / 227.63 秒
                               （基線 1636，多的 7 條是新加的）
    修完檔頭之後再跑一次全套      1643 passed / 0 failed / 231.20 秒

五組反向驗證，每一組都紅在該紅的那一條：

    in_resolved_section 永遠 False      → 放在哪一個區段抽得出來 紅（共 4 條）
    讓區段單獨就能關掉                    → 區段單獨不准關掉任何一條 紅（共 4 條）
    misfiled 永遠空                      → 放錯區段的另外列出來 紅（共 2 條）
    said_closed_by 只回第一個訊號         → 單一訊號的字串沒有變 紅
    「兩個訊號」那句寫回去                 → 打架那句話不准寫死是兩個訊號 紅

五次還原後 sha256 逐位元組一致
（`063c13f216b73a4d…` / `5e6e0f74abf27a45…`）。

### 寫測試的時候撞到一個順帶的發現

第一版 fixture 的標題寫成「放在已解除底下，本文還寫著擋住什麼」，
測試紅了，因為 `_CLOSED_WORDS` 是子字串比對，那個標題裡的「已解」
被讀成「這一條宣告自己解除了」。**一個在描述解除區的標題，
被判成在宣告解除。** 這一輪沒有修它（改比對規則會動到數字，
那是 owner 的地盤），只把 fixture 標題換掉，記在這裡。

### §40 登了一筆

    pol-25d1775e5f　radius 2

被推翻的是「打架的訊號有兩個，而打架的是 B-03 與 B-04 兩條」。
radius 量法跟上一輪一樣，grep 全 repo 找誰吃過這個結論，兩處：
`.forseti/NEXT.md` 產生出來的那一行、`AUTO_CONTINUE_LOG.md:1904`。
**兩個數字本身不是錯的**，錯的是它們被當成窮舉。

登記簿 14 → 15 筆，有守的 11 → 12 筆。

### 第一次全套有兩條紅，成因是我自己，而且是上一輪剛記錄過的那個機制

    FAILED test_動到正本的測試全部在冊
    FAILED test_動到的路徑全部在允許範圍內_而且這是最後一條
    2 failed, 1641 passed

點名的是 `tests/test_owner.py::TestFlaggedLinesReachTheRound::...`，
而那條測試完全無辜 —— 全套跑到一半的時候，我在外面用
`pollution.record()` 寫了 `.forseti/pollution.jsonl`。
紅訊息自己就印著那句話：

    提醒：這個量法分不出寫入者，全套跑的期間有人動正本的話
    會被記在當時在跑的那一條頭上。

這正是 2026-09-17 19:3x 那一輪刻意復現出來的機制，
只是那一次是人為注入探測檔，這一次是自動接續自己踩的。
**重跑一次、期間不碰 repo，1643 全綠。**

順帶一件值得記下來的：登記 §40 是自動接續每一輪都會做的動作，
而跑全套也是。兩件事撞在一起就會生一條無辜的紅。
目前的辦法只有「不要同時做」，沒有人守著這件事不再發生。

### 收尾時另外兩處過期的敘述也修了

`_blocker_sections` 的檔頭寫著「**兩個訊號分開讀，不合成一個。**」，
`_blockers` 的檔頭寫著「兩個訊號打架的時候我不挑一邊」。
訊號變三個之後這兩句都是錯的，而且錯得跟這一輪登記的污染同形 ——
**把當時數得出來的數量寫成窮舉**。兩處都改了，
`_blockers` 那一處另外指回 `pol-25d1775e5f`。

改完跑過所有會去讀 `desktop_api.py` 原始碼的測試檔（9 個，305 條），
除了一條因為我把檔案順序排錯而紅的（`test_zz_` 那條守的正是
「它必須是整個 session 的最後一條」，我把 `test_forseti_cli.py`
排在它後面），其餘全綠；那一條單獨跑 23 條全過。

### 沒有動畫面，也沒有開關 App

`desktop/ui/` 一個位元組都沒動，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

順帶查到一件跟這條規則有關的：`desktop/deploy.sh` 第 57 行自己會
`pkill -9 -f "Forseti.app/Contents/MacOS"`。所以「跑 deploy.sh」
跟「不准殺 App」不是兩件無關的事 —— 在她開著視窗的時候部署，
會關掉她的視窗而且不再開回來。ROADMAP 寫「build 要她說」是對的，
理由跟它寫的那個不完全一樣。

### 動到的檔

    apps/forseti-cli/desktop_api.py     三支函式
    tests/test_blockers.py              7 條測試 + 一份 fixture
    .forseti/pollution.jsonl            1 筆

沒有 commit。

### 還缺什麼

- **那三條放錯區段的要搬回去，還是要把本文改成真的解除，是 owner 的決定。**
  B-17 的本文自己就寫著在等她決定三選一。現在系統講得出這件事，
  講不出的是該挑哪一邊。
- **兩支程式仍然回不同的數字。** 這一輪只讓其中一支說得出差在哪、
  差幾條、後果是什麼。要讓它們一致得先挑一邊，那也是上面那個決定的下游。
- **`_CLOSED_WORDS` 的子字串比對會誤判標題**，上面那一段寫了怎麼撞到的。
  改它會動到未解除數，所以沒改。
- 其餘在等 owner 的那一串沒有變：`AXES_COVERED` 要她重新登入、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格寫死、B-15、
  B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個 `dry_run=False`、畫面那一半。
- §40 十五筆全部 OPEN。

## 2026-09-17 20:1x-20:3x　讓 `forseti doctor` 講得出自己少算了哪幾條

**挑了什麼，以及為什麼是它。** 照 ROADMAP 自己寫的規則，先讀上一輪的
「還缺什麼」逐項問「這一項要 owner 開口嗎」。五項裡四項要她開口
（三條放錯區段怎麼處理、兩支程式要一致得先挑邊、`_CLOSED_WORDS` 改了會動到
未解除數、以及那一長串在等她的）。剩下的那一項是上一輪自己留下的後果：

上一輪讓 `desktop_api._blockers` 說得出 `misfiled`，可是 `forseti doctor`
那一支還是安靜地回 8。**而跑 doctor 的人看不到桌面版**，他不會知道
有三條在 `# 已解除` 那個標題底下被切掉了。這一件不需要 owner 決定 ——
要她決定的是「挑哪一邊」，不是「講不講得出差在哪」。

### 動手之前先量的

    forseti.extract_blockers（doctor 用的）    8 條
    desktop_api._blockers                     open 11、closed 6、total 17
    差的                                      B-17、B-14、B-13

跟上一輪記錄的數字一致，不是沿用，是這一輪自己跑出來的。

### 改了什麼

    apps/forseti-cli/forseti.py
      extract_misfiled()    新增。借 desktop_api._blockers 的 misfiled
      Report.misfiled       新欄位，`None` 是數不出來、`[]` 是真的沒有
      build_report()        接上；借不到的時候補一條 WARN
      cmd_doctor()          阻塞那一段後面多六行，講出後果與誰決定
      cmd_status()          少算的掛在阻塞那個數字旁邊，不另起一行

**數字一個都沒有變。** `阻塞 8` 還是 8，`open 11` 還是 11。
變的是 doctor 那一邊現在講得出「這個數字少算了 3 條　B-17、B-14、B-13」，
以及少算的後果（兩支程式回不同的數字）與這是誰的決定。
**沒有自動降級**，照舊 —— 把 misfiled 併進阻塞數等於替 owner 挑了一邊。

三個刻意的選擇：

- **借判準，不自己判。** 再寫一次區段與「擋住：」欄的解析，等於造出第三個
  會跟前兩個對不上的數字，而對不上正是這一支要講出來的那件事。
  有一條測試守著這一點（`test_doctor_不自己重寫一份解析`）
- **借不到回 `None` 不回 `[]`。** 「數不出來」跟「沒有」長成同一個樣子，
  是這個專案抓過很多次的形狀（`desktop_api._safe` 的檔頭寫著同一句）
- **doctor 仍然一定跑得起來。** 借不到就降級成一條 WARN，不讓它掛掉

### 驗證結果

    tests/test_blockers.py     28 條全綠（原 22 + 新 6）
    全套                        1649 passed / 0 failed / 252.86 秒
                               （基線 1643，多的 6 條是新加的）

六組反向驗證，每一組都紅在該紅的那一條：

    extract_misfiled 永遠回 []          → 3 條紅
    借不到的時候回 [] 而不是 None        → 數不出來回 None 不回空list 紅
    build_report 把 misfiled 併進去      → 講出來但不准把它算進阻塞數 紅
    doctor 那幾行不講後果                → 講得出後果與誰決定 紅
    status 改成另起一行 / 完全不提        → 掛在阻塞旁邊 紅（兩種注入都紅）
    extract_misfiled 自己重寫一份解析     → 4 條紅

還原後 sha256 逐位元組一致（`65fab16efacfe45f…`），五次還原都對。

### 兩條測試第一版是假綠的，成因不一樣但形狀一樣

**這一段是這一輪最該留下來的東西，不是上面那個功能。**

第一條，「不准把它算進阻塞數」第一版斷言在 `extract_blockers` 上。
注入「在 extract_blockers 裡把 misfiled 接進去」之後，全套 28 條**全綠**。
當下第一個念頭是「這條測試守不住」。實際不是：`extract_blockers` 進門
第一行就 `re.split` 把 `# 已解除` 之後切掉（`forseti.py:196`），
所以在它體內怎麼接都接到空的 —— **注入根本沒有生效**。
直接印出來才看見：`extract_blockers` 長度 1、`misfiled` 是 `['B-83']`。
會發生自動降級的位置是 `build_report` 把兩個結果組起來那一層，
斷言搬過去之後，同一個意圖的注入立刻紅。

第二條，status 那條第一版是 grep `cmd_status` 的原始碼找 `line +=`。
反向驗證也是綠的 —— 因為 `line +=` 在同一支函式裡出現不只一次
（還有 `elif rep.misfiled is None` 那一支），把要守的那一處換成 `print`，
斷言在另一處照樣成立。改成跑一次 `cmd_status` 抓真實輸出，
斷言「阻塞」與「放錯區段」落在同一行，兩種注入都紅了。

共用的機制：**反向驗證的綠有兩種成因 —— 測試守不住，或注入沒生效 ——
而它們在畫面上長得一模一樣，我只讀出了第一種。**
少掉的那一步是先確認注入真的改變了被測函式的輸出。
附帶一條：在原始碼裡找字串，找到的可能不是你要守的那一個。

### §40 登了一筆

    pol-6701655574　radius 0

radius 量法跟前幾輪一樣，grep 全 repo 找誰吃過這個結論：沒有。
從發現到推翻都在同一輪之內，沒有寫進任何檔案，**所以 0 是量出來的不是沒量**。
regression_probe 填的是改好之後的那兩條測試。
登記簿 15 → 16 筆，有守的 12 → 13 筆。

登記在跑全套**之前**做，因為上一輪記錄過「登記 §40 與跑全套撞在一起
會生一條無辜的紅」。這一輪照那個順序走，全套一次就 1649 全綠，沒有紅。

### 沒有動畫面，也沒有開關 App

`desktop/` 一個位元組都沒動（`git status --porcelain desktop/` 空的），
所以沒有 build、沒有 deploy。全程沒有 `open`、沒有 `pkill`、
沒有設 `FORSETI_OPEN`。

### 動到的檔

    apps/forseti-cli/forseti.py         一個新函式 + 四處接線
    tests/test_blockers.py              6 條測試
    .forseti/pollution.jsonl            1 筆
    .forseti/NEXT.md                    重新產生（走 desktop_api strands）

沒有 commit。

### 還缺什麼

- **兩支程式仍然回不同的數字，這一輪沒有讓它們一致。** 現在是兩邊都講得出
  差在哪，挑哪一邊還是 owner 的決定。**這是刻意的**，不是沒做完
- **`forseti doctor` 那六行沒有人看過。** 它印得出來（這一輪跑過），
  但沒有人真的在接手的時候讀到它。零次跟一次的差別在這裡也成立
- **`_CLOSED_WORDS` 的子字串比對會誤判標題**，上一輪記過，這一輪沒碰。
  順帶查到一件可以寫下來的：此刻 `BLOCKERS.md` 的 17 個標題裡
  **沒有任何一個會被誤判**（`B-08` 的「解法方向已改」不含 `已解` 也不含
  `解除`）。所以上一輪那句「改它會動到未解除數」對現在這份檔案**未驗證** ——
  會不會動要看新規則怎麼寫，而寫新規則正面撞上 B-05。這一筆沒有登進 §40，
  因為我沒有推翻它，只是查出它在此刻的資料上沒有實例
- 其餘在等 owner 的那一串沒有變：三條放錯區段怎麼處理、`AXES_COVERED`
  要她重新登入、`scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格
  寫死、B-15、B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個 `dry_run=False`、
  畫面那一半
- §40 十六筆全部 OPEN

---

## 2026-09-17 20:4x-20:5x　交接檔終於答得出「這一份是在哪台機器上寫的」

**挑了什麼，以及為什麼是它。** 照 ROADMAP 自己寫的規則，先讀上一輪的
「還缺什麼」逐項問「這一項要 owner 開口嗎」。四項裡三項要她開口
（兩支程式的數字要一致得先挑邊、`_CLOSED_WORDS` 的新規則正面撞上 B-05、
以及那一長串在等她的）。剩下那一項（doctor 那六行沒有人看過）不是
一件寫得出來的工作，是一次閱讀。

所以這一輪不是從上一輪的尾巴接的，是從 `contract.py` 的缺口表挑的。
挑中的理由不是它排第一，是這一條：

    .forseti/NEXT.md「已經發生過的決定」第一條
    → 換機器：舊機器硬碟不穩，工作移往新電腦

    同一份檔案的 §39.1 缺口表
    → runtime_node（active machine/runtime node）沒有資料來源

**一份記錄過換機器的交接檔，答不出現在這一份是在哪台機器上寫的。**

### 動手之前先查它不存在

    ls apps/forseti-cli/ | grep -i node        沒有
    grep -rln 'node_id|hostname|uname' apps src tools
      → event_ledger.py（只有 schema 欄位）、migrate.py、contract.py
        （只有那句「沒有實作」的理由）、sot.py（§12.2，是另一節）

`sot.py` 做的是 §12.2 該信哪個來源，§12.1 的 RuntimeNode 這一端沒有人做。
`hooks/event-ledger.mjs:159` 那一行 `runtime_node_id: ''` 也還在。

### 規格六欄，做出三欄，另外三欄空著而且說得出為什麼

§5 那張表寫 `node_id, host, process, service, version, health`。

    node_id   有　從 IOPlatformUUID 算 sha256 前 16 碼
    host      有　socket.gethostname()
    process   有　pid 加 executable
    service   空　人登記的事實。從行程名稱的長相推斷是 B-05 擋住的做法
    version   空　§5 只寫 version，沒說是誰的版本
    health    空　§12.2 的來源一個都沒接

**`version` 那一欄是這一輪最該留下來的決定。** 作業系統版本量得到，
而且就躺在同一個 dict 裡（`measured['host']['os_version']`），接上去
是最順手的動作。沒接，因為那正是 `contract.py` 已經記過一次的形狀：
「jsonl 的 `version` 是 CLI 版本不是模型版本」。**名字對上不等於東西對上。**
量到的放 `measured`，規格那一欄留 None，讓讀的人自己決定是不是同一個。

`health` 不給燈，理由借 `sot.py` 檔頭那一句：一個沒有被檢查過的綠燈
比沒有燈更糟，因為它會讓人不去看。

### node_id 的穩定度，以及一句不准被讀錯的話

取 IOPlatformUUID，取不到退回 hostname，**`basis` 那一欄一定帶著走** ——
退回 hostname 的那個 id 會在改機器名字的那天變掉，而那件事在畫面上
跟「換了一台機器」長得一模一樣。

存的是 sha256 前 16 碼不是原值，因為原值是硬體序號等級的東西，
而這一欄會被寫進 git 追蹤的檔案。

**跨重開機這一輪沒有驗過。** 驗過的是跨行程：兩個獨立的 python 行程
算出同一個值。跨重開機靠的是 IOPlatformUUID 自己的性質，不是我量到的。
這兩件事不一樣，模組檔頭與測試檔頭都這樣寫。

### contract 接的是 reference() 不是 describe()

    §39.1 那一欄問「是哪一台」          → reference()，三個 key
    §5 那張表問「這個實體有沒有六欄」    → describe()，六欄加 unfilled

接 `describe()` 的話這一欄會變成 DEGRADED，**而那個降級的理由來自
另一張表**。讀的人會以為系統不知道跑在哪台機器上，實情是知道。
有一條測試釘住這一點。

`target_environment` 那一欄的理由順手改了，沒有改狀態。它原本寫
「§12.1 的 Project → RuntimeNode 那一層沒有實作」，RuntimeNode 這一端
做出來之後那句話只剩一半是真的。它仍然是 NO_SOURCE ——
「現在跑在哪」跟「要落到哪裡」是兩件事。

### 數字變化，全部是這一輪自己跑出來的

    §39.1 帶得出值的      12（39%）→ 13（42%）
    沒有資料來源          12 → 11
    測試                  1649 → 1665（新 16 條）
    模組                  多一個 runtimenode.py
    §40 登記簿            16 → 17 筆，有守的 13 → 14

### 反向驗證：第一次有兩組的紅是假的，成因跟上一輪那一段是同一個形狀的反面

**這一段比上面那個功能重要。**

第一輪九組注入，九組全紅，第一眼的結論是「每一條都守得住」。
實際不是：其中兩組（health 給一盞綠燈、空的三欄被省略掉）各自紅了
**7 條**，而那七條裡有五條跟注入的意圖無關 ——
連「量的時候一個檔都不寫」「原始 UUID 不會出現在輸出裡」都紅了。

成因是那兩個注入改掉了 `_UNFILLED` 的 key 名稱，於是
`return {k: out[k] for k in SPEC_FIELDS}` 直接 KeyError，
**每一條碰到 `fields()` 的測試都跟著崩**。那不是測試抓到了，
是注入把程式弄壞了。

    上一輪記的：反向驗證的綠有兩種成因 —— 測試守不住，或注入沒生效
    這一輪的反面：反向驗證的紅也有兩種 —— 測試抓到了，或注入把程式弄崩

而它們在 pytest 的輸出上長得一模一樣，都是一行 FAILED。
我讀過上一輪那句，只讀成「綠要小心」，沒翻到另一面。
**「紅得多」被我讀成「守得緊」**，那個 7 本身就是訊號。

重做成語意有效的注入之後，紅的分別是 2 條與 1 條，而且全部是
`AssertionError`。登進 §40：`pol-240e178980`，radius 0
（grep 全 repo，只命中上一輪那句，是來源不是下游；從發現到推翻都在
同一輪之內，沒有寫進任何檔案，所以 0 是量出來的不是沒量）。

防的規則寫進那一筆：每一組要看三件事 —— 紅了幾條、紅的是不是注入
意圖那一條、失敗型別是不是 `AssertionError`。非 AssertionError
代表注入改壞了程式，那一組不算驗過。

**這條規則寫下來之後立刻用在自己身上**：`test_contract接的是reference不是describe`
原本在注入 NoSource 的時候丟 `TypeError`（`set()` 吃到 dataclass），
補了一行先問型別，重驗之後是 `AssertionError`。

### 全部的反向驗證結果

    第一輪（rev.py，九組）
      version 被作業系統版本頂替        → 2 紅，對
      node_id 回固定字串不理輸入        → 2 紅，對
      原始 UUID 被放進輸出              → 1 紅，對
      health 給一盞綠燈                 → 7 紅，**假的，程式崩了**
      空的三欄被省略掉                  → 7 紅，**假的，程式崩了**
      measure 順手寫一個檔              → 1 紅，對
      contract 接 describe              → 2 紅，對
      contract 失敗時退回 hostname      → 1 紅，對
      target_environment 理由退回舊版   → 1 紅，對

    重做（rev2.py，三組，全部 AssertionError）
      health 給一盞綠燈（只改值）        → 2 紅
      describe 宣稱六欄都填滿           → 1 紅
      service 理由不再指得到 B-05       → 1 紅

    contract 那一側（rev3/rev4，三組）
      這一欄退回 NoSource / 回空 dict / 回空字串 → 各 4 紅，全部 AssertionError

每一組還原後 sha256 逐位元組一致（`runtimenode.py` c346f4e550b84f9e、
`contract.py` f771d62219dfa95a）。

### 全套第一次跑有一條紅，而那條紅是對的

`test_contract.py::test_collect不會把沒有來源寫成空清單` 把
`runtime_node` 列在 NO_SOURCE 的例子裡。它紅的時候訊息印的是
`{'basis': 'IOPlatformUUID', ...}` —— **它抓到的正是「有來源了還寫沒有來源」**。

那條測試自己的 docstring 已經記過兩次同樣的事（`invalidated_conclusions`
2026-09-16 19:2x、`logical_agent_id` 同日 22:5x），兩次都寫著
「移出去不是為了變綠」。這是第三次，照同一個做法處理：移出清單，
**同時在別處釘住新狀態**（`test_runtime_node有來源之後不准再標成沒有來源`），
不是只是刪掉。那條 docstring 現在也寫著「這張清單只會變短不會變長，
移出去的每一欄都要在別處被釘住」。

### 驗證結果

    tests/test_runtimenode.py   15 條全綠（新增）
    tests/test_contract.py      新增 1 條，全檔全綠
    全套                        1665 passed / 0 failed / 232.23 秒
                               （基線 1649，多的 16 = 15 + 1）

### 沒有動畫面，也沒有開關 App

`git status --porcelain desktop/` 空的，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 動到的檔

    apps/forseti-cli/runtimenode.py     新增，零寫入、零依賴
    apps/forseti-cli/contract.py        `_runtime_node()` 加兩處接線
    tests/test_runtimenode.py           新增 15 條
    tests/test_contract.py              移一欄出清單 + 新增 1 條
    .forseti/pollution.jsonl            1 筆
    .forseti/NEXT.md                    重新產生（走 desktop_api strands）

沒有 commit。

### 還缺什麼

- **值算出來了，交接檔的正文沒有印出來。** 這是這一輪最大的缺口，
  而且它就是上一輪抱怨的那個形狀（「doctor 那六行沒有人看過」）。
  `python3 apps/forseti-cli/contract.py` 看得到，`.forseti/NEXT.md`
  的正文看不到 —— 那份檔案的契約那一節只列缺口，填得出來的欄位不印。
  **下一輪就做這一件，路徑是確定的**：`handoff.REQUIRED_KEYS` 加一個鍵、
  `desktop_api._write_handoff()` 產生它、`handoff.render()` 排版。
  三處都有守門（`missing_keys()` 那組），所以要一起改。
  這一輪沒做的理由是它是第二件工作不是第一件的收尾，不是因為卡住
- **`service` / `version` / `health` 永遠是空的，沒有登記簿。**
  要讓 `service` 有值得先有人工登記簿（形狀照 `identity.py`），
  而那會多一個寫入點，要同時登進 `tests/test_module_write_targets.py`
  的三張表。這一輪刻意沒做：**沒有人在等那一欄**，硬接一個沒人用的
  寫入點只會多一個要守的東西
- **跨重開機的穩定性沒有驗過。** 驗過的是跨行程。這一條要真的重開機
  才驗得到，所以它會一直是未驗證，除非有人在重開機之後跑一次
  `python3 apps/forseti-cli/runtimenode.py` 比對 node_id
- **`hooks/event-ledger.mjs:159` 那行 `runtime_node_id: ''` 沒有動。**
  現在有 node_id 可以填了，但那是 hook 那一側的改動，會影響每一筆
  新事件的形狀，而且改完之後舊的 42 筆跟新的會不一樣。
  **這一項要 owner 開口**，理由是它動的是帳本 schema 的實際內容
- 其餘在等 owner 的那一串沒有變：三條放錯區段怎麼處理、兩支程式的
  數字要一致得先挑邊、`_CLOSED_WORDS` 的新規則撞 B-05、`AXES_COVERED`
  要她重新登入、`scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`、`B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標
  那格寫死、B-15、B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個
  `dry_run=False`、畫面那一半
- §40 十七筆全部 OPEN

## 2026-09-17 21:0x-21:1x　交接檔終於印得出座標，不再只印自己缺什麼

**挑了什麼，以及為什麼是它。** 照 ROADMAP 自己寫的兩步規則，先讀上一輪的
「還缺什麼」。第一條就指名了這一輪要做的事，而且寫著路徑是確定的：

    值算出來了，交接檔的正文沒有印出來。
    路徑：handoff.REQUIRED_KEYS 加一個鍵、
          desktop_api._write_handoff() 產生它、handoff.render() 排版

逐項問「這一項要 owner 開口嗎」，這一條不用（其餘三條要：`service` 那個
登記簿沒有人在等、跨重開機要真的重開一次、`hooks/event-ledger.mjs:159`
動的是帳本 schema）。所以不必走到第二步的 `contract.py` 缺口表。

### 動手之前先查它不存在

    grep -rn 'contract_lines' apps tests desktop/ui
      → desktop_api.py:1926 一個產生點、handoff.py 兩處、test_handoff.py 三處
    grep -rn 'HO\.write|handoff\.write' apps tools hooks
      → 只有 desktop_api.py:1931 一個寫入者

只有一個產生點，所以「三處一起改」是完整的，不會漏掉第二條路。

### 這一輪做的是同一個形狀第二次出現，不是新發現

先前 `NEXT.md` 的契約那一節**只印缺口**。所以一欄從 NO_SOURCE 接成有值
之後，讀的人看到的差別是「少了一行缺口」，不是「多了一個答案」。

同一件事 2026-09-16 18:2x 撞過一次（`artifact_paths` 早就 PRESENT，
而交接檔上一個路徑都看不到，於是有了 `artifact_lines`）。這一次是
`runtime_node`。**兩次都不是意外，是這個檔案的預設行為** ——
它被寫成一份「自我檢討清單」，不是一份「說得出自己在哪」的交接。

### 白名單不是「所有 PRESENT」

`COORDINATE_FIELDS` 六欄：`project_id`、`canonical_root`、`runtime_node`、
`session_id`、`logical_agent_id`、`model_identity`。

收進來的標準不是「比較重要」，是**其他每一節都要靠它才解釋得了**：
一條 `apps/forseti-cli/contract.py` 只有在某一台機器的某一個正本底下
才指得到東西，而這份檔案會被另一台機器上的人讀到。

`artifact_paths`、`invalidated_conclusions`、`known_limits` 刻意不收 ——
它們各自有自己那一節，收進來會印兩次，然後兩個地方開始不一致。
有一條測試釘住這件事。

### 三個刻意的決定

**只印 PRESENT，缺的那幾欄不在這裡印理由。** 理由歸缺口那一節管，
兩個地方印同一欄就會開始不一致。但結尾要點名沒列到哪幾欄並指去那一節，
不然「沒列」會被讀成「沒有這一欄」。這一條被三種寫法的注入各抓一次。

**值一律走 `check()` 算好的 `shown`，這一支不自己格式化。** 自己格式化
就是第二條渲染路徑，同一個值在兩節會長得不一樣，而讀的人分不出哪邊是真的。

**`basis` 不是硬體識別碼的時候多印一句，不是把那個 id 藏起來。**
退回 hostname 的 node_id 會在改機器名字的那天變掉，而那在畫面上
跟「換了一台機器」長得一模一樣。那句警告的判斷跟 `runtimenode.BASIS_UUID`
拿，**不寫死字面值** —— 寫死的話那邊改一個字，警告會靜默地永遠不成立，
而少印一句警告不會讓任何測試變紅。為此在 `runtimenode.py` 把兩個
basis 字面值命名成 `BASIS_UUID` / `BASIS_HOSTNAME`。

### 排在哪一節之前，是有理由的

排在北極星底下、其他所有節之前。讀的人先看到一串路徑、最後才知道那是
另一台機器上的路徑，跟先知道機器再看路徑，是兩種不一樣的閱讀。
有一條測試用三個 `index()` 釘住順序。

### 驗證結果

    tests/test_contract.py      新增 10 條，全檔 106 綠
    tests/test_handoff.py       新增 7 條，全檔 35 綠
    tests/test_runtimenode.py   新增 2 條，全檔 17 綠
    全套                        1684 passed / 0 failed / 241.18 秒
                               （基線 1665，多的 19 = 10 + 7 + 2）

走真正那條路（`desktop_api.strands('')`）重新產生 `.forseti/NEXT.md`，
那一節印出來了，`runtime_node` 那一行帶著 node_id、host、basis 三個值。

§39.1 的數字**沒有變**（13/31，42%）。這一輪改的是印不印，不是算不算得出來，
兩件事不要混在一起看。

### 反向驗證：十二組，九組一次就對，一組是我自己注入失效

    第一輪（rev.py，十組）
      coordinate_lines 一律回空清單      → 5 紅，AssertionError，對
      白名單收進 artifact_paths          → 1 紅，對
      basis 名字寫死字面值               → 2 紅，對
      沒列到的那幾欄不講去哪裡找          → **0 紅，注入沒生效**
      順便把缺席的理由也印出來            → 1 紅，對
      值不走 shown 自己格式化            → 1 紅，對
      座標那一節排到最後面               → 2 紅，對
      REQUIRED_KEYS 拿掉這個鍵           → 1 紅，對
      desktop_api 傳的是 ctx 不是 report → 1 紅，對
      BASIS_UUID 改一個字                → 2 紅，對

    重做那一組（rev2.py，三種寫法）
      整段拿掉                          → 1 紅，AssertionError
      講了但不點名是哪幾欄               → 1 紅，AssertionError
      點名了但不說去哪裡找理由            → 1 紅，AssertionError

那個 0 紅的成因：注入插了一行 `missing = []`，而**四行之後同一個名字
被重新賦值蓋掉**，所以那次跑的其實是原版程式。上一輪記的那一句
（綠有兩種成因：測試守不住，或注入沒生效）這一輪直接用上了 ——
差別在於上一輪是事後推翻，這一輪是當場就分得出來，因為那一組的紅數
（0）跟旁邊九組（1 到 5）不同量級，而**不同量級本身就是要去看的訊號**，
不管它是偏高還是偏低。

**沒有為這一筆新增 §40 登記。** 機制上一輪已經登過，而這一次是那條
已登記機制的一次正確應用，不是新的錯。每撞到一次就再加一條規則，
正是 Vol4 §12 第一條 Kill Criteria 要 kill 的那種膨脹。

每一組還原後 sha256 逐位元組一致：`contract.py` 3858279ffe7a6d66、
`handoff.py` 72b5fd5783fa1426、`desktop_api.py` 07df40f5b5f99abe、
`runtimenode.py` 63122d738a766246。

### 沒有動畫面，也沒有開關 App

`git status --porcelain desktop/` 空的，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 動到的檔

    apps/forseti-cli/contract.py      新增 COORDINATE_FIELDS、coordinate_lines()、
                                      _basis_uuid_name()
    apps/forseti-cli/handoff.py       REQUIRED_KEYS 加一鍵、render() 加一節
    apps/forseti-cli/desktop_api.py   _write_handoff() 產生並傳 crd_lines
    apps/forseti-cli/runtimenode.py   兩個 basis 字面值命名成常數
    tests/test_contract.py            新增 10 條
    tests/test_handoff.py             新增 7 條
    tests/test_runtimenode.py         新增 2 條
    .forseti/NEXT.md                  重新產生（走 desktop_api.strands）

沒有 commit。

### 還缺什麼

- **這一節只在 `NEXT.md` 上，畫面上沒有。** 桌面版讀的是同一份 snap，
  但 `app.js` 沒有對應的區塊。這一項**不做不是因為卡住，是因為
  owner 明令不准自己開關 App**，而畫面改了不 build 等於沒改
- **`logical_agent_id` 仍然是這六欄裡唯一答不出來的。** 它的來源
  （`identity.py`）在，`.forseti/identity.jsonl` 0 條登記。要有值得有人
  去登記，**不准從 alias 的長相推斷**（B-05 擋住的做法）
- **`model_identity` 印的是 `claude-opus-5`，而 `model_config` 仍然
  DEGRADED**（jsonl 只有 effort，沒有 temperature / top_p / system prompt
  版本）。座標那一節印得出「哪個模型」，印不出「什麼設定」，
  兩者對輸出的影響不是同一個量級
- **跨機器沒有實測。** 這一節存在的理由是「另一台機器上的人讀到這份」，
  而驗的是同一台機器上兩個行程。要真的驗得有第二台機器跑一次
- 其餘在等 owner 的那一串沒有變：`hooks/event-ledger.mjs:159` 的
  `runtime_node_id: ''`、三條放錯區段怎麼處理、兩支程式的數字要一致
  得先挑邊、`_CLOSED_WORDS` 撞 B-05、`AXES_COVERED` 要她重新登入、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格寫死、B-15、
  B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個 `dry_run=False`
- §40 十七筆全部 OPEN

---

## 2026-09-17 21:5x　§33.1 Metric Provenance Contract，第四個「理由後來才變假」的欄位

### 挑這一項的路徑

照 `ROADMAP.md`「所以接手的人現在該做什麼」那兩步規則走：

第一步，上一輪的「還缺什麼」四條，逐條問「要 owner 開口嗎」——
畫面那一節要她（不准自己開關 App）、`logical_agent_id` 要有人登記、
跨機器要第二台機器、`model_config` 的提供端不在我這邊。**四條全要她**。

第二步，`contract.py` 缺口表裡標著「沒有資料來源」的那 11 欄，
逐條問「這個理由現在還成立嗎」。`metrics_by_distribution` 那一條寫著

    Metric Provenance Contract 沒有實作
    （`grep -rn 'Metric Provenance' apps/ src/` 零命中）

這句話此刻仍然為真（實測零命中），而規格 §33.1 把那個物件定義得
**完整到不用任何人決定**：25 個欄位、三組枚舉、外加一句對畫面的硬要求。
不需要 owner 開口，所以是它。

### 做了什麼

`apps/forseti-cli/metrics.py`，§33.1 逐字。

**25 欄不是 24。** 第一版模組說明寫 24，是我自己數的，沒有數規格 ——
規格那一段第一行就是 `metric_id`，它不是這一支生成的額外欄位。
`test_欄位名逐字對得上規格` 第一次跑就把這件事抓出來，因為那一條
去讀規格原文而不是讀我寫的數字。**這正是那條測試該做的事**：
一條拿我自己寫的常數去對我自己寫的另一個常數的測試，
不管我數錯幾次都會是綠的。

### 缺席分兩種，理由不是這裡新編的

| 缺席 | 用在哪幾欄 | 理由來源 |
|---|---|---|
| `NOT_APPLICABLE` | `dataset_manifest_hash`、`split_hash`、`overlap_score` | 措辭對齊 `contract.py` 的 dataset 三欄 |
| `UNKNOWN` | `model_hash`、`config_hash`、`target_environment`、`seed` | 前三個對齊 `contract.py` 已查過的實情 |

`seed` 那一條是這一輪親自驗的：最近一份 transcript jsonl 的欄位表
只有 `effort` 與 `perTurnEffort`，沒有 seed、沒有 temperature、
沒有 top_p。所以那句「提供端沒有給」是量出來的，不是沿用的。

**模板不留空格給人自己編理由。** `forseti metric template` 印出來的
那四欄直接帶 `contract.py` 已經查過的那句話 —— 留空格的話人現場補的
那一句會跟 `contract.py` 分歧，而分歧那天不會有錯誤訊息。
有一條測試斷言模板裡那幾欄的 `why` 不含 `<`。

### 這一支不自動登記任何東西，而且這是主要設計

最容易的作弊路徑是拿現成的數字（測試通過數）配一組猜出來的欄位
登記上去，缺口表的數字立刻從 0 變 1。**不做**，理由是 §8.3：
一筆欄位齊全而材料類別是編的記錄，在畫面上跟一筆真的記錄長得一模一樣。

實例就在眼前，而且已經寫成測試釘住：這個專案最常報的數字是
「全套 1730 綠」，它照 §33.1 **登記不了**。`material_class` 規格只收
六種（real / synthetic / public / consented / blind / red-team），
而 pytest 那一套混著人工構造的輸入與拿真實 jsonl 跑的案例，
硬歸成其中一種就是編。要登記得先照分佈拆開，而拆開要靠人去讀
每一條測試用的是什麼材料 —— 語意判斷，B-05 擋住自動做。

`test_全套測試通過率照規格登記不了` 釘住的是**它登記不了**，
不是它登記得了。下一個人想讓這個數字進登記簿，會先撞到這一條。

### 夠不夠格是算出來的，六項缺一項就不夠

規格最後那句話（`must not display an unqualified percentage as a
release claim` ⋯ `ruler, material, layer, denominator, plus environment
and lineage`）變成六項檢查。**一項裡面缺一欄，整項就不齊，不算
「大部分有」** —— 血緣缺 `model_hash` 的意思是換一組權重重跑會得到
另一個數字而沒有人分得出來，那不是程度問題。

在這個專案裡幾乎每一筆都會是「不夠格」，因為 `model_hash`、
`config_hash`、`seed`、`target_environment` 全部 UNKNOWN。
**那是量出來的實情，不是門檻訂太嚴。**

`by_distribution()` 同時報總數與夠格數。只報夠格數的話，一筆登記了
但血緣不齊的記錄會從畫面上消失 —— 而那一筆正是要有人去補提供端的那一筆。

### 降級的值寫進 jsonl 再讀回來仍然判得出

`code_commit` 拿得到 HEAD 但工作區跟它不一致的時候，`contract.git_head()`
回的是 `Degraded` 實例。那個實例寫進 jsonl 再讀回來只剩一個普通 dict，
**降級的理由那一刻就不見了**，於是一個「HEAD 指不到現在跑的程式碼」
的記錄，重讀之後會看起來像一個乾淨的 commit。

所以這一支用 `degraded()` 這個 dict 形狀存，`_degraded_why()` 兩種
形狀都認。有一條測試走完整條路（build → register → load → qualification）
釘住重讀之後仍然判得出 DEGRADED。

### 接上交接契約：第四次同一個形狀

`contract.py` 的 `metrics_by_distribution` 從 `NoSource` 改成
`_metrics_field()`。空登記簿的時候是 `Empty`，理由指得出下一步
（`forseti metric template` → `register --from`）。

`test_collect不會把沒有來源寫成空清單` 立刻紅了 —— **第四次**，
前三次是 `invalidated_conclusions`、`logical_agent_id`、`runtime_node`。
四次都是同一個方向：那張清單只會變短。移出去的每一欄都在別處被釘住，
這一次是 `test_metrics有來源之後不准再標成沒有來源`，它多問一句
**「讀一次不准長出登記簿」**，守的是上面那條「不自動登記」。

§39.1 的數字：NO_SOURCE 11 → 10，EMPTY 5 → 6。
**帶得出值的仍然是 13/31（42%），沒有變** —— 這一輪改的是
「有沒有地方算」，不是「此刻算不算得出來」，兩件事不要混著看。

### 兩個守門自己紅了，那是它們該做的事

`test_declared_only`：`metrics.VERSION` 定義了沒人讀。接到
`by_distribution()` 的回傳裡 —— 契約版本跟著那一份答案走，
不塞進記錄（那 25 欄是規格的，多一欄就不是那張表了）。

`test_module_write_targets`：新增的第十五個寫入點沒有任何地方守它。
照 `antianchor` 那一輪的做法加進 `GUARDED_HERE`、`WRITERS`、
`DEFAULT_NAMES`。`_w_metrics` 走 `build()` 再 `register()`，不直接餵
手組的 dict —— 手組的會在寫檔前被擋掉，那樣量到的零是提早 return
的零，跟「它不寫」長得一樣（那個檔頭記著的假陰性）。

### 驗證結果

    tests/test_metrics.py               新增 43 條，全綠
    tests/test_contract.py              新增 1 條，全檔 107 綠
    tests/test_module_write_targets.py  多 2 條 parametrize，全檔 28 綠
    全套                                1730 passed / 0 failed / 253.64 秒
                                       （基線 1684，多的 46 = 43 + 1 + 2）

走真正那條路（`desktop_api.strands('')`）重新產生 `.forseti/NEXT.md`，
那一欄從「沒有資料來源」那一節移到「來源在，此刻空的」，
帶著登記的兩個指令。

### 反向驗證：十二組，十二組全部有紅

    枚舉檢查拿掉                 → 3 紅
    一項缺一欄仍算齊             → 5 紅
    空的時候回 NoSource          → 2 紅
    不分組全部塞一組             → 1 紅
    register 不擋非 build 的東西 → 1 紅
    degraded_why 不認 dict       → 2 紅
    FIELD_NAMES 少一欄           → 2 紅
    沒宣告缺席的靜默補 None       → 1 紅
    結構性缺席改成 UNKNOWN        → 1 紅
    模板留佔位符給人自己編         → 1 紅
    缺席沒理由也放行             → 1 紅
    build 問題一次只報一條        → 2 紅

沒有 0 紅的那一組。上一輪記著「綠有兩種成因：測試守不住，或注入
沒生效」，這一輪十二組的紅數落在 1 到 5，**沒有出現不同量級的離群值**，
所以不需要回頭去分辨是哪一種。

每一組還原後 sha256 逐位元組一致：`metrics.py` fcdea3765420fc66、
`contract.py` 4112c9617369f05a。

### 沒有動畫面，也沒有開關 App

`git status --porcelain desktop/` 空的，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 動到的檔

    apps/forseti-cli/metrics.py         新增（§33.1，25 欄、三組枚舉、
                                        兩種缺席、六項合格檢查、登記簿、CLI）
    apps/forseti-cli/contract.py        _metrics_field()，那一欄接上來源
    apps/forseti-cli/forseti.py         `forseti metric` 指令 + 用法那一行
    tests/test_metrics.py               新增 43 條
    tests/test_contract.py              新增 1 條，那張清單少一欄
    tests/test_module_write_targets.py  metrics 進三張表 + _w_metrics
    .forseti/NEXT.md                    重新產生（走 desktop_api.strands）

沒有 commit。

### 還缺什麼

- **登記簿此刻 0 筆，而且不該由我去填。** 要有第一筆，得有人把一個
  數字的尺與材料寫下來。這一支刻意不自動產生任何記錄，
  所以「0 筆」會一直是 0 筆直到有人登記 —— 那是設計不是卡住
- **畫面上沒有這一節。** 桌面版讀的是同一份 snap，`app.js` 沒有對應
  區塊。這一項**不做不是因為卡住，是因為 owner 明令不准自己開關 App**，
  而畫面改了不 build 等於沒改
- **`by_distribution()` 只按 `material_class` 分組。** §39.1 那句
  `by distribution` 有沒有別的分佈維度（例如 `execution_environment`
  或 `system_layer`），規格沒有講。**沒有講的不自己補一個**，
  現在這樣是照 §33.1 唯一列成枚舉的那一欄分的
- **`applicability_scope` 收的是自由字串。** 規格沒有給它枚舉，
  所以這裡不發明一組。代價是它擋不住一句沒有意義的話，
  而那件事 `claims.py` 那一條線才管得到
- 其餘在等 owner 的那一串沒有變：`hooks/event-ledger.mjs:159` 的
  `runtime_node_id: ''`、三條放錯區段怎麼處理、兩支程式的數字要一致
  得先挑邊、`_CLOSED_WORDS` 撞 B-05、`AXES_COVERED` 要她重新登入、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格寫死、B-15、
  B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個 `dry_run=False`
- §40 十七筆全部 OPEN

## 2026-09-17 22:0x-22:3x　§39.1 failed_attempts 那一欄接上來源了

**挑了什麼，以及為什麼是它。** 照 ROADMAP 那條兩步規則，先讀上一輪
（§33.1 metrics）的「還缺什麼」，逐項問「這一項要 owner 開口嗎」:

    登記簿 0 筆不該由我填　　→　設計不是缺口，不是可做的事
    畫面上沒有 metrics 這一節　→　沒有人在等那一格，接了也是白工
    by_distribution 只分一維　→　規格沒定義別的維度，§8.3 禁止自己補
    applicability_scope 自由字串 → 規格沒給枚舉，同上

四條都不是往下做的方向，所以走第二步看 `contract.py` 的缺口表。
NO_SOURCE 那十條逐條看，`failed_attempts` 是唯一一條「理由此刻已經
不再為真而且規格定義完整」的:

- 它的理由寫著「只寫在 AUTO_CONTINUE_LOG 的敘述裡，那是散文不是
  可查詢的狀態」。那句話一直是真的，但它描述的是缺一個物件，
  不是缺一個決定
- 規格把它定義完了（AI-First 工程書 v1.0 第 975-977 行，逐字
  `attempt + observed result + why not repeat`），三欄，不用任何人決定
- 其餘九條要 owner 或結構性不適用: `claims_allowed` / `claims_prohibited`
  要政策物件（那是她的政策）、`owner` 要她說她是誰、`process_status`
  撞 §12.2 五個病症對應（她擋著）、`dataset_manifest` / `leakage_result`
  / `source_classes` 這專案不是訓練任務、`model_revision` 提供端沒給、
  `target_environment` 要 Project → RuntimeNode 綁定

### 動手之前先查它不存在

    ls apps/forseti-cli/ | grep -i attempt      → 零命中
    grep -rln 'failed_attempt|FailedAttempt|why_not_repeat' apps src tests
      → contract.py（那一欄的 NoSource）、pollution.py（模組說明引用它）、
        sot.py（一條憑據指著那一行），三處都是「引用」不是「實作」

所以這一支是新的，不是第四次重做同一個東西。

### 規格只有三欄，這裡多要兩個，理由寫在模組說明裡

`source` 與 `verifier` 是必填。不是規格要的，是照 `pollution.py`
已經付過代價的先例: 一筆查不回出處的失敗記錄本身就是一個沒有證據的
宣稱，而不知道是誰觀察到的，這筆的可信度就沒有上限也沒有下限。

### retry_condition 那一對，為什麼不發明一個分類器

「why not repeat」在這個專案有兩種完全不同的實情。一種是條件沒變所以
不要重試（認證過期、碟沒掛、額度用完），條件變了就該重試，而那一刻
這筆記錄反而會擋路。另一種是這條路本身走不通，條件怎麼變都一樣。

**沒有發明枚舉去分這兩種。** 規格沒有定義它們，照 §8.3 不編一個。
改成照 `pollution.py` 的 `propagation_radius` / `radius_basis` 那個
已經存在的形狀: 沒給 `retry_condition` 就要講 `no_retry_basis`。
空的重試條件讀起來是「永遠不要再試」，跟「有條件但沒人寫下來」是
兩件事，而後者常常才是實情。

`release()` 只放得掉有重試條件的那些。沒有重試條件的放不掉，
要推翻當初那個判斷走的是 §40 污染登記簿（那裡存的是「當初為什麼
會這樣判」，這裡存不了）。有一條測試釘住這件事，它是這一組最重要的
一條: 什麼都放得掉的話，這個登記簿就變成一個可以隨手清空的待辦清單，
而它存在的理由正是「下一個 session 不要再試一次」。

### 只增不改，而且原文要逐位元組留著

放掉一筆是追加一行 `RELEASE`，`records()` 讀的時候折進去。
有一條測試比對放掉前後的原始檔案內容 —— `raw_after.startswith(raw_before)`
——，不是只看折完的結果。折完的結果正確而底下偷偷改了原文的話，
前者看不出來。

### 反向驗證：十四組，十四組全部有紅

    why_not_repeat 不擋空的        → 1 紅
    source 不擋空的                → 2 紅
    verifier 不擋空的              → 1 紅
    兩個重試欄都空也放行             → 1 紅
    沒有重試條件的也放得掉           → 1 紅
    放掉不必講理由                  → 1 紅
    放過的可以再放一次              → 1 紅
    id 把理由也算進去               → 1 紅
    load 不跳過壞行                → 1 紅
    summary 不報 total 只報 active → 1 紅
    records 不折 RELEASE 進去      → 4 紅
    空登記簿回 NoSource            → 1 紅
    放掉之後仍然算還在擋路           → **第一次 0 紅**，補測試之後 1 紅

**那個 0 紅是這一輪唯一真的抓到東西的一組。** `active()` 改成「全部
都回」的時候全綠，因為 `summary()` 內部自己算了一次還在擋路的數，
沒有走 `active()`。兩支各算各的，就要各守各的。補了
`test_active只回還在擋路的那些`，注入之後 1 紅。

每一組還原後 sha256 逐位元組一致: `attempts.py` f3f6511402a1b777、
`contract.py` c86abea8091dd7ea。

### 反向驗證腳本自己出過一次事，記在這裡

第一輪十二組跑到最後一組，解析 pytest 輸出的那一行崩了
（`int("C._")`，因為錯誤訊息裡也有 "failed" 這個字），
**而還原寫在崩掉的那一行後面，所以 `contract.py` 帶著注入留在碟上**。
下一條測試立刻紅，才發現。第二輪改成 `try/finally` 還原，並且用
`re.search` 取最後一行。

這件事的形狀跟這個專案已經記過好幾次的是同一個: 量到的是「動作發生了」
（腳本跑完了）不是「事情做成了」（還原成功了）。還原的斷言本來就在，
只是它排在會崩的那一行後面。

### 接上交接契約：第五次同一個形狀

`contract.py` 的 `failed_attempts` 從 `NoSource` 改成
`_failed_attempts_field()`。空登記簿是 `Empty`，理由指得出下一步。

前四次是 `invalidated_conclusions`、`logical_agent_id`、`runtime_node`、
`metrics_by_distribution`。五次都是同一個方向: 那張「這個系統沒有
資料來源」的清單只會變短。

§39.1 的數字: NO_SOURCE 10 → 9，EMPTY 6 → 7。
**帶得出值的仍然是 13/31（42%），沒有變** —— 這一輪改的是
「有沒有地方算」，不是「此刻算不算得出來」。

### 兩個守門自己紅了，那是它們該做的事

`test_module_write_targets`: 新增的第十六個寫入點沒有任何地方守它。
照前例加進 `GUARDED_HERE` / `WRITERS` / `DEFAULT_NAMES`，
`_w_attempts` 走 `record()` 五個必填全部餵真值 —— 少餵任何一個會在
寫檔之前就 return，那樣量到的零是提早 return 的零。

`test_sot`: `sot.py` 的 `workflow_progress` 那一條憑據指著
`contract.py` 的 `"failed_attempts": NoSource`，那一行被我改掉了，
所以它從 OK 變 STALE（**不是 DRIFTED** —— 原文找不到了，
不是行號漂了）。改指 `attempts.py:93 def record(`，note 也跟著改:
state 仍然是 PARTIAL，因為登記簿此刻 0 筆，缺的是有人去登記。

`test_literal_restate` 的回歸釘子: ALL_CAPS 那一側 72/290 → 73/292。
查過是 `attempts.KINDS`（ATTEMPT / RELEASE）帶進來的**只有它一個**
（同一支的 `SPEC_FIELDS` 與 `EVIDENCE_FIELDS` 是小寫成員，落在另一側）。
查法是把 `attempts.py` 暫時移開再掃一次，72/290 回來了。

### 驗證結果

    tests/test_attempts.py              新增 26 條，全綠
    tests/test_module_write_targets.py  多 2 條 parametrize，全檔 30 綠
    tests/test_sot.py                   42 綠（憑據 STALE 0 條）
    tests/test_literal_restate.py       103 綠
    全套                                1758 passed / 0 failed / 183.28 秒
                                       （基線 1730，多的 28 = 26 + 2）

走真正那條路（`desktop_api.strands('')`）重新產生 `.forseti/NEXT.md`，
那一欄從「沒有資料來源」那一節移到「來源在，此刻空的」。

### 沒有動畫面，也沒有開關 App

`git status --porcelain desktop/` 空的，所以沒有 build、沒有 deploy。
全程沒有 `open`、沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 動到的檔

    apps/forseti-cli/attempts.py        新增（§39.1 failed_attempts，
                                        三欄規格 + 兩欄出處、重試條件那一對、
                                        只增不改、release 的兩種放不掉、CLI）
    apps/forseti-cli/contract.py        _failed_attempts_field()，那一欄接上來源
    apps/forseti-cli/forseti.py         `forseti attempt` 指令 + 用法那一行
    apps/forseti-cli/sot.py             workflow_progress 的憑據改指新位置
    tests/test_attempts.py              新增 26 條
    tests/test_module_write_targets.py  attempts 進三張表 + _w_attempts
    tests/test_literal_restate.py       ALL_CAPS 回歸數字 72/290 → 73/292
    .forseti/NEXT.md                    重新產生（走 desktop_api.strands）

沒有 commit。

### 還缺什麼

- **登記簿此刻 0 筆，而且不該由我自動填。** 這一支刻意不掃散文
  （B-05），所以「0 筆」會一直是 0 筆直到有人登記。
  **但這一件跟 metrics 那一件不一樣**: metrics 的第一筆需要有人
  決定一把尺，failed_attempts 的材料此刻就在 ROADMAP 第 3259 行
  （`claude -p` 回 OAuth session expired，rc=1，那一軸跑不了）。
  三欄全部有原文出處，不用猜。**沒有登它是因為那筆的 `verifier`
  該是實際跑過那個指令的人**，而跑那次的是上一輪，不是這一輪 ——
  這一輪沒有親自跑過 `claude -p`，登上去的話 `verifier` 就是假的
- **`release()` 沒有人在用。** 它有 5 條測試守著，但正本登記簿是空的，
  所以「條件成立了有人來放」這條路沒有真的走過一次
- **畫面上沒有這一節。** 桌面版讀的是同一份 snap，`app.js` 沒有對應
  區塊。跟 metrics 那一輪同一個狀態: 沒有人在等那一格
- 其餘在等 owner 的那一串沒有變: `hooks/event-ledger.mjs:159` 的
  `runtime_node_id: ''`、三條放錯區段怎麼處理、兩支程式的數字要一致
  得先挑邊、`_CLOSED_WORDS` 撞 B-05、`AXES_COVERED` 要她重新登入、
  `scope_match`、§12.2 五個病症對應、兩件 workflow 的 `commit_boundary`、
  `B-17` 的 `RAW_INLINE_LIMIT`、`renderVitals` 目標那格寫死、B-15、
  B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項那個 `dry_run=False`
- §40 十七筆全部 OPEN

## 2026-09-17 22:3x　登記簿的第一筆，那一欄從「有地方算」變成「算得出來」

### 挑了什麼，以及為什麼是它

照 ROADMAP 那條兩步規則，先讀上一輪（§39.1 failed_attempts）的
「還缺什麼」，逐項問「這一項要 owner 開口嗎」：

    登記簿此刻 0 筆，不該由我自動填　→　這一條不是要 owner，見下
    release() 沒有人在用　　　　　　→　登記簿空的時候走不了
    畫面上沒有這一節　　　　　　　　→　要 owner，她明令不准自己開關 App
    其餘那一串　　　　　　　　　　　→　全部要 owner

第一條停住了，所以沒有走到第二步（contract.py 的缺口表）。

停住的理由要寫清楚，因為它跟「0 筆不該由我填」這句話看起來衝突。
上一輪自己寫下的是：材料此刻就在 ROADMAP，三欄全部有原文出處，
沒有登它是因為那筆的 verifier 該是實際跑過那個指令的人，
而跑那次的是上一輪。

那一句話裡的限制不是「這筆不該登」，是「上一輪不該登」。
這一輪可以自己跑一次，跑完我就是那個 verifier。
兩件事差的只是有沒有人去看，不是有沒有人有資格看。

### 親自跑過，觀察到什麼

    python3 apps/forseti-cli/forseti.py probe-model status --check-auth

    這一軸現在跑不了：EXPIRED
    Failed to authenticate: OAuth session expired and could not be refreshed
    cli  = /Users/norikaoda/.nvm/versions/node/v24.14.1/bin/claude
    auth = EXPIRED

跟 2026-09-17 17:xx 那次同一個訊息，中間沒有人登入過。
這一支只呼叫一次模型（prompt 是「回一個字：好」），
`status()` 的說明自己寫著為什麼 `check_auth` 預設 False，
所以這次查是明確要求的，不是順手。

### 登了第一筆，五個必填全部有原文出處

    id            att-2bb74c352d
    attempt       跑 P2.9 的模型軸：先 check-auth，通過才 run --yes
    observed      auth=EXPIRED 加完整錯誤訊息與 CLI 路徑
    why_not_repeat 認證是 owner 的動作。再跑一次 run 只會拿到
                  36 次 CALL_FAILED，而 CALL_FAILED 刻意不進分母
                  （ROADMAP.md:3253），量不到東西也改不了 AXES_COVERED
    source        三條：這一輪實跑的指令、probemodel.py:388（發出呼叫
                  那一行）、ROADMAP.md:3261（上一輪記同一個訊息）
    verifier      自動接續第 12 輪（claude-opus-5），22:5x，親自跑過

`retry_condition` 填了，不是 `no_retry_basis`：擋住的是認證不是
這條路本身，owner 重新登入之後 `check-auth` 回 OK，那一刻這一筆
就該被放掉。這是上一輪那一對欄位存在的理由第一次落到真實資料上。

### 順手更正一個行號

上一輪寫「材料在 ROADMAP 第 3259 行」，實際是 3261
（`grep -n "OAuth session expired"` 的輸出）。3259 那一行是
那一小節的標題前後。差兩行不影響結論，但登記簿的 source
是拿來查回去的，所以登的是查過的那個。

### 驗證結果

    .forseti/attempts.jsonl         0 筆 → 1 筆（ATTEMPT，有 retry_condition）
    attempts.summary()              total=1 active=1 released=0
    contract._failed_attempts_field() Empty → PRESENT
    §39.1 帶得出值                   13/31（42%）→ 14/31（45%）
    「有來源此刻是空的」              7 → 6
    全套                            1758 passed / 0 failed / 177.46 秒

1758 跟上一輪的基線一模一樣，因為這一輪沒有新增任何測試。

### 這一輪沒有寫程式碼，那是刻意的

ROADMAP 的「5a 到 5al 那三十八節是什麼」明寫過這件事：
清單空的時候正確的動作不是再守一層。這一輪做的是走一次流程，
讓一個已經寫好的登記簿第一次裝進真實資料。

零筆跟一筆的差別是：零筆的時候，`record()` 那五道必填檢查
從來沒有對著真實材料成立過一次，而「機制在那裡」跟「機制擋得住
真實輸入」在一張表上長得一樣。這跟 P0 第 1 項那句
「零次跟一次的差別，比任何新模組都大」是同一件事。

### 沒有動畫面，也沒有開關 App

`git status --porcelain desktop/` 空的。全程沒有 `open`、
沒有 `pkill`、沒有設 `FORSETI_OPEN`。

### 動到的檔

    .forseti/attempts.jsonl     第一筆（新檔，先前不存在）
    .forseti/NEXT.md            重新產生（走 desktop_api.strands）
    .forseti/AUTO_CONTINUE_LOG.md 這一節
    .forseti/ROADMAP.md         下一項那一節

程式碼一行沒動。沒有 commit。

### 還缺什麼

- `release()` 仍然沒有人走過一次。但狀態變了：先前是登記簿空的
  所以走不了，現在是有一筆而它的條件還沒成立。真正走過那一次
  要等 owner 重新登入 CLI，那一刻 `check-auth` 回 OK，
  這一筆就該被放掉，而放掉那條路會第一次被走
- 登記簿現在 1 筆，而還有第二筆材料是現成的嗎，沒有去找。
  這一輪刻意只登親自驗過的那一筆
- 畫面上仍然沒有 failed_attempts 這一節，跟 metrics 同一個狀態
- §40 十七筆全部 OPEN
- 其餘在等 owner 的那一串沒有變：`hooks/event-ledger.mjs:159` 的
  `runtime_node_id: ''`、三條放錯區段怎麼處理、兩支程式的數字要
  一致得先挑邊、`_CLOSED_WORDS` 撞 B-05、`AXES_COVERED` 要她重新
  登入、`scope_match`、§12.2 五個病症對應、兩件 workflow 的
  `commit_boundary`、B-17 的 `RAW_INLINE_LIMIT`、`renderVitals`
  目標那格寫死、B-15、B-03 與 B-04 訊號打架、ROADMAP P0 第 1 項
  那個 `dry_run=False`
