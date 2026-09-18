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

---

## 這份日誌截斷了（2026-09-18）

原本 17,071 行，是自動接續每一輪的完整工作紀錄。

**截斷的理由跟 ROADMAP 那 40 節一樣:** 它記的絕大多數是
「補上一輪自己寫下的缺口」那一類，一輪一輪往上長，
而沒有人讀得完 17,071 行的日誌 —— 讀不完的紀錄跟沒有紀錄一樣。

完整內容在 git 歷史裡:`git log -p .forseti/AUTO_CONTINUE_LOG.md`。

**這份檔案之後只留最近十輪。** 要往前查就查 git。

---

## 2026-09-18 17:4x-17:5x　`handoff` 那兩個真旗標，量了也修了；同一輪撞到第二個 session

### 挑了什麼，為什麼

`還缺什麼` 裡連續三輪掛著「`handoff` 那兩個真旗標仍然沒量」。
P0 兩項都卡在 owner（`dry_run=False` 那一按、F04/F05 沒接上），
所以這一輪挑它。

### 它為什麼是前三種判準都管不到的那一支

`no_extra_args` 問「該不該有參數」、`operands` 問「位置與長相對不對」、
`membership` 問「這個值在不在名單裡」—— **三支都把以 `-` 開頭的 token
當成錯的。** `handoff` 的 `--shell` / `--no-shell` 是合法的，所以那三支
沒有一支管得到它。

它是唯一一支，這句話是 AST 數出來的不是讀出來的：掃所有 `cmd_*`
函式裡以 `-` 開頭的字串常數，只有 `cmd_handoff` 有東西。
（`claims` / `overclaim` 的 `--limit` 由 `transcript_limit(known=)` 自己守。）

### 量出來的後果分兩種，第二種比第一種重一級

攔 `accept` / `transition` / `dispatch` 三個寫入點，假帳本，沒碰正本。

| 寫法 | 改之前 exit | 走到寫入點 | 帳本收到什麼 |
|---|---|---|---|
| `handoff --bogus <真 task> s1 w` | 1 | 沒有 | ── |
| `handoff --shel <真 task> s1 w` | 1 | 沒有 | ── |
| `handoff --no-shell --shell <真 task> s1 w` | 1 | 沒有 | ── |
| `handoff --new --bogus w 目標` | ── | **三個都走到** | objective=`w`、worker=`--bogus` |
| `handoff --new --no-shell --shell w 目標` | ── | 同上 | objective=`w`、worker=`--shell`、can_report=`write_only` |

前三列是訊息指錯地方加 exit code 錯一級：畫面回「找不到任務：--bogus」，
那句話是真的，可是他錯的是旗標名，於是他會去查任務。

後兩列**整筆錯位寫進帳本**：認不得的旗標沒被拿掉，佔住 worker 那一格，
worker 的名字被擠去當目標，目標被擠去當驗證條件（實測
`definition_of_done=['目標']`）。帳本 append-only，收不回來。

最後一列還多一層：`--no-shell` 生效了而 `--shell` 同時變成 worker 的
名字 —— 一個旗標同時被當成旗標與位置參數，畫面從頭到尾沒提過。

### 第一版量測只攔第一個寫入點，看不到 worker 是誰

`accept` 一攔就 `SystemExit`，於是只看得到 objective=`w`，
而 worker 那一格才是這件事嚴重的地方。前兩個放行才走得到 `dispatch`。
**第一版的量測結果不完整，不是錯，是看不到最重要那一格。**

### 改了什麼

新增第四種判準 `flags()`，兩半：名字認不得、不准同時給。
**名字那一半接 `cliargs.unknown_flags`，沒有寫第二份**。
常數三個：`HANDOFF_NEW`、`HANDOFF_CAPABILITY`（旗標對 can_report）、
`COMMAND_FLAGS` 與 `EXCLUSIVE_FLAGS` 都從 `HANDOFF_CAPABILITY` 推。

`cmd_handoff` 改成從常數讀，一個字面量都不留，而且**拿掉的是全部不是
挑一個拿掉** —— 原本 if/elif 兩個都給的時候只拿掉 `--no-shell`。

排在 `operands` **前面**，因為那一支會把合法的旗標當成放錯位置。
`handoff` 今天不在 `OPERAND_SHAPES` 裡，所以兩支現在不會同時攔到同一個
呼叫；哪天要加進去，得先決定位置參數要不要先把認得的旗標剝掉，
**那是協定決定，這一輪沒有自己補**。

### 十道注入，九條測試每一條都有人紅

注入 2 唯一紅「互斥」、注入 4 唯一紅「順序」、注入 6 唯一紅「直接呼叫
也不留那條漏」、注入 8 唯一紅「沒有多擋」。注入 5（擋死整支）與注入 10
（名單少收一個合法旗標）是讓「乾淨呼叫五種」紅的那兩道 —— 沒有它們，
把整支擋死會全綠。

新增 `HandoffFlags` 9 條，單檔 159 → **168**。

### 同一輪撞到第二個 session，全套這一輪沒有跑

17:48:31 `tests/` 被動過，**10 個已追蹤的測試檔從工作區消失**，
`tests/conftest.py` 少掉 125 行（`_snapshot` / `_diff` / `append_record` /
`write_record` / `scan_errors` / `pytest_runtest_protocol` /
`pytest_sessionfinish` 整塊，語法完整、沒有殘留呼叫端 ——
**那是一致的移除，不是損壞**）。

消失的十個：`test_artifact_drift` / `test_cli_flag_dispatch` /
`test_declared_only` / `test_forseti_dir_writes` / `test_literal_restate` /
`test_module_write_targets` / `test_silent_oserror` /
`test_state_changing_writes` / `test_tempdir_cleanup` /
`test_zz_forseti_write_attribution`。

**是誰做的，答出來了：另一個 Claude Code session。** `ps` 追父程序鏈：
pid 3527 `python -m pytest tests/ -q --tb=line` 17:49:50 起跑 →
pid 3525 zsh（shell snapshot `...1789539271324-kepavc`，**不是我這一條的
`...1789724381881-bn4vqg`**）→ pid 40849 `claude.app`。
那一句指令我沒有下過，`--tb=line` 從頭到尾沒出現在我的任何一個呼叫裡。

**它為什麼刪那十個，我不知道，也沒有猜。** 那十個裡有九個是這個專案
自我稽核的測試。

我做的處置，只有一件：`git checkout -- tests/test_cli_flag_dispatch.py`。
還原前先驗過**它的 HEAD 版本與我動手前的備份逐位元相同**
（兩邊都是 `a10cef8b2578807b`），所以還原沒有覆蓋任何人的改動。
**另外九個檔與 `conftest.py` 一個字都沒碰** —— 那是 owner 的決定，
不是我的。內容都在 HEAD 裡，還原的指令是
`git checkout -- tests/<檔名>`。

**全套這一輪沒有跑，理由不是程式碼。** 對面那條 session 的全套
17:49:50 起跑，到我收工時還在跑。兩個全套同時跑，紅的歸屬會互相污染 ——
那正是這份紀錄前幾輪反覆付過代價的形狀。所以這一輪的驗證只到單檔
（168 綠）與十道注入為止，**沒有全套數字可以報**。

還有一件要講清楚：我 17:51 還原那個檔的時候，對面的全套已經在跑了。
**我改了它腳底下的樹**，這件事我沒辦法宣稱無害。

### 這一輪的量測自己壞過一次，而且是同一個機制的第四次

第一次跑注入，十道全部回「no tests ran in 0.00s、紅：[]、被紅過的
測試 0 條」。那個畫面讀起來像「我寫的九條測試一條都守不住東西」。

**真正的原因是測試檔在那個時候已經不存在了。** 拿一個壞掉的狀態
去量，量出來的東西不算數 —— 跟上一輪 `blast.SRC` 那次（`sed` 的 `\b`
在 BSD sed 不生效、檔案當時是 `NameError`）是同一個機制。

分辨的方法這一次也在畫面上：`0.00s` 跟 `no tests ran`。一個真的跑過
九條測試的 pytest 不會是 0.00 秒。**看到自己的東西全軍覆沒，
第一個動作該是問量測本身是不是壞了，不是接受那個結論。**

**沒有登進 §40。** 那句話沒有變成結論被帶下去 —— 從看到到推翻中間
沒有任何一步是基於它做的。登進去會稀釋登記簿（同 §40 那條政策）。
這是判斷，可以被推翻。

### 還缺什麼

- **全套沒跑**。對面那條 session 的全套跑完之後才有意義。
  基準：上一輪 2238 綠 1 紅，新增 9 條。**但那十個檔現在不在，
  收集到的數量會比 2239 少，直接比對數字會得到假的差值** ——
  比之前先確認那十個檔在不在
- **那十個檔與 `conftest.py` 要不要還原，等 owner。** 九個是自我稽核的
  測試，`conftest` 少掉的是「正本被碰到沒有」那整套機制。
  它們不在的時候，全套全綠的意思比平常小
- **`deploy.sh` 的守門沒有受影響**：它跑的是 `test_js_symbols.py` 與
  `test_ui_contract.py`，兩個都不在消失的名單裡（B-15 那條沒有變）
- **這一輪沒有量「`handoff` 的旗標放在中間位置」**：
  `handoff <真 task> --shell s1 w` 改前改後都走到寫入點。
  旗標從任何位置被拿掉是這一支原本的設計，改它會讓現在合法的寫法
  退回，**那是另一個決定，刻意沒做**
- **`antianchor` 與 `probe-model` 的子指令名單常數**（上一輪那條沒有變）
- **另外五支 helper 搬到 `cliargs.py`**（要先決定 `_arg` 回 None 還是
  default，上一輪那條沒有變）
- **`unfilled()` 只守 `register` 這一條路**（上一輪那條沒有變）
- **`context` / `index` / `recall` 轉發給別的模組，還是沒量**
- **exit code 的慣例仍然沒有寫下來**
- 等 owner 的那一串沒有變，另外多一條：**這個 repo 同時有兩條 session
  在動，排程的自動接續要不要加一道「有別人在跑就不動手」的閘**
- **沒有動畫面、沒有 build、沒有開關 App**，一次模型呼叫都沒有發生
