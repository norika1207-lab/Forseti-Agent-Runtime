# tools/README.md 稽核：跟實際腳本有沒有脫節

日期　2026-09-09
方法　逐支打開 tools/ 底下全部 22 個檔案（21 支腳本加 dashboard.html），對照 README 裡寫的用法、參數預設值、exit code、行為宣稱，一條一條比。每一筆結論都附原始碼行號，可以回查。
稽核對象　tools/README.md（2026-09-09 23:10 的版本，13,450 bytes）

## 結論先講

README 沒有實質脫節。22 個檔案全部有條目，沒有幽靈條目（README 寫了但檔案不存在的），也沒有漏網腳本（檔案存在但 README 沒寫的）。逐支驗過的用法、預設值、exit code 全部與原始碼相符。

找到四筆小出入，嚴重度都低，其中一筆的脫節在腳本自己的註解而不在 README：

1. classify-turns.mjs 頭部註解還寫「分成四類」，實作與 README 都是六類。該修的是腳本註解。
2. goal.mjs 的 exit 1 條件，README 寫得比實際窄了一點（壞檔案也會回 1）。
3. install.mjs 的 exit 1 清單漏了一種拒絕情況（settings.json 壞掉）。
4. 「.gitignore 已擋」這句只對慣用輸出檔名成立，輸出檔名是使用者自己指定的那幾支，取了別的名字就不會被擋。

## 一、覆蓋率比對

tools/ 實際內容（`._` 開頭的 AppleDouble 附屬檔不算，README 第 11 行自己也講了）：

| 檔案 | README 有條目 |
|---|---|
| check-auto-continuity.py | 有 |
| check-orphan-workers.py | 有 |
| orphans.mjs | 有 |
| latency.mjs | 有 |
| self-audit.mjs | 有 |
| focus.mjs | 有 |
| goal.mjs | 有 |
| corpus-profile.mjs | 有 |
| pick-negatives.mjs | 有 |
| measure-fpr.mjs | 有 |
| sample-hits.mjs | 有 |
| build-fingerprints.mjs | 有 |
| classify-turns.mjs | 有 |
| find-owner-signals.mjs | 有 |
| calibrate.mjs | 有 |
| self-scan-v2.mjs | 有 |
| analyze-transcripts.mjs | 有 |
| dashboard.mjs | 有 |
| dashboard.html | 有（併在 dashboard.mjs 條目） |
| install.mjs | 有 |
| docx2md.py | 有 |
| save-case.py | 有 |

兩個方向都是零缺口。

## 二、逐支驗證結果（全部相符的部分）

每筆格式：README 的宣稱，然後是原始碼佐證。

check-auto-continuity.py
- exit 0/1/2 的三種意義：與 main() 相符（回 2 在第 31 行、回 1 在第 57 行、回 0 在第 62 行）。
- 「自己把 apps/forseti-cli 加進 sys.path」：第 22 行。

check-orphan-workers.py
- `--grace` 預設 900 秒：第 95-96 行。`--db`、`--json` 都在：第 97-99 行。
- 「已終止但沒回報過的那類不影響 exit code」：exit 只看 orphans（第 115、139 行），historical 只列出。
- exit 2 找不到帳本或空檔：第 103-105 行。

orphans.mjs
- 預設掃 repo 的 src/：第 25 行。exit 0/1：第 39、52 行。
- 「曾因沒濾掉 ._ 而兩次假警報，教訓已寫進腳本」：第 13-17 行註解與第 30 行 NOT_SOURCE 正則都在。

latency.mjs
- 預設每項 30 次：第 20 行。含 node 啟動、附空程序底線：第 30-33、67-73 行。沒有語意化 exit code：全檔無 process.exit。

self-audit.mjs
- 用法與 exit 1（沒給參數）：第 29-33 行。三類（未兌現、在等、驗不了）：第 18-24 行註解與第 103-105 行輸出。

focus.mjs
- 「exit code 一律 0，連 goal.json 不存在都只是印提示」：全檔沒有 process.exit 呼叫，goal 缺檔走第 37-43 行的提示分支。README 加註「node 執行錯誤才非零」也對，transcript 格式異常時可能丟例外。

goal.mjs
- exit 0 至少找到一份、exit 1 找不到：第 37-41 行。順序「先專案再家目錄」：第 20-23 行。

corpus-profile.mjs
- 用法 `<projects-dir> [--json] [--limit N]` 與 exit 1：第 34-42 行。
- 「只抽四類獨立事實」：第 66-134 行的 profile() 確實只數規模、is_error、中斷、人類訊息數，沒有讀語意的欄位。

pick-negatives.mjs
- `--n` 預設 30：第 37-38 行。標籤 PRESUMED_HEALTHY、證據等級 MODEL_INFERENCE：第 140-141 行。exit 1 沒給檔案：第 41-44 行。

measure-fpr.mjs
- 「算的是 hit rate 不是誤報率」：第 160-169 行的報告欄位 what_hit_rate_means、what_would_make_it_an_fpr 原文如此。exit 1：第 38-42 行。

sample-hits.mjs
- `--n` 預設 20：第 35-36 行。`--signal`、`--json` 都在：第 37-39 行。
- 「均勻抽樣避免全來自同一個 session」：第 116-122 行。「原文在前、模型判斷折在後、標 MODEL_ADJUDICATION」：第 159-169 行輸出結構。
- 附帶一提：腳本自己第 42 行的 usage 字串沒列 `--json`，README 反而列全了。要修的話修腳本的 usage 字串。

build-fingerprints.mjs
- 用法兩個位置參數、exit 1 參數不足：第 37-42 行。三層指紋（session、segment、turn）：第 149-185 行回傳結構。

classify-turns.mjs
- 六類 NORMAL / MIXED / UNSUPPORTED / EVASIVE / CHATTER / INTENT：第 227 行 CLASSES 常數逐字相同。README 說「事件流裡找不到的叫 UNSUPPORTED 不叫 FABRICATED」：第 174-180 行實作如此。`--limit`：第 47-48 行。

find-owner-signals.mjs
- `--context` 預設 3：第 46-47 行。exit 1 沒給目錄：第 49-52 行。
- 「已排除 subagent、Codex 歷史重播、skill 塞入文字」：第 76-101 行 NOT_OWNER 清單（Codex agent history 正則在第 82 行、skill 文字在第 96 行），subagent 目錄排除在第 138 行。

calibrate.mjs
- 「處理十項中推得出來的六項」：第 7-13 行註解與第 35-42 行的量測清單一致。exit 1 沒給目錄：第 22-25 行。

self-scan-v2.mjs
- 用法與 exit 1：第 48-53 行。「重建不出來的東西明列在結尾」：第 32-46 行註解說明 not_reconstructable 的設計。

analyze-transcripts.mjs
- exit 1 兩種情況（沒給目錄、目錄裡沒有 .jsonl）：第 25-35 行，兩種都在。

dashboard.mjs
- `--port` 預設 7777：第 36-37 行。只綁 127.0.0.1：第 76 行。「唯讀、不寫入、不送任何東西給被觀測 session」：readState() 只讀 state.json，全檔沒有任何寫入。

install.mjs
- exit 1 的四種情況（沒給參數、目標不存在、目標是家目錄、目標是本 repo）：第 30、33、44-52、53-59 行。
- 「裝完不會生效，要人手動改 cross_project_enabled」：第 110 行只會把缺的欄位補成 false，絕不寫 true。

docx2md.py
- 沒給參數回 2：第 131-133 行。目錄轉裡面所有 .docx：第 137 行。「少了 N 字只印在輸出、不影響 exit code」：第 148-151 行，main 永遠 return 0。

save-case.py
- 四個位置參數、沒有參數檢查、參數不足直接 traceback：第 18 行直接索引 sys.argv[1] 到 [4]，IndexError 未捕捉，確實如 README 所述。
- MODEL_SELF_REPORT 證據等級與檔頭聲明：第 37-45 行。

README 開頭的通則兩條也驗了：「參數不對印用法回 1、docx2md.py 回 2」與各腳本相符；「把 exit code 當答案的只有四支」的名單（兩支 Python 診斷、orphans、goal）成立。install.mjs 的 0/1 其實也有語意（裝好對拒絕），但它的非零全是前置條件不對，歸進「參數不對回 1」那類不算錯。

## 三、找到的出入

### 出入一（脫節在腳本，不在 README）：classify-turns.mjs 頭部註解過時

腳本第 2 行寫「把每一個 AI 回合分成四類」，第 17-24 行列 NORMAL / EVASIVE / FABRICATED / MIXED 四類。實作（第 166-183 行與第 227 行）是六類，還有 INTENT 與 CHATTER，而且 FABRICATED 在輸出裡叫 UNSUPPORTED（頭部註解第 36 行有補講這一點，但四類的說法沒改）。README 寫的六類才是對的。

建議：改腳本頭部註解，把四類那段更新成六類。README 不用動。

### 出入二：goal.mjs 的 exit 1 條件比 README 寫的寬

README 第 91 行寫「1 = 兩處都找不到」。實際上還有一種情況也回 1：檔案存在但 JSON 壞掉。壞檔不會進 found 清單（第 28-34 行，解析失敗只印「壞了」），兩處都壞或一壞一缺時 found 是空的，一樣走第 37-41 行回 1。對自動化接這支的人來說，exit 1 的意思是「沒有任何一份讀得動的北極星」，比「找不到」寬。

建議：README 那行改成「1 = 兩處都拿不到能用的北極星（缺檔或壞檔）」。

### 出入三：install.mjs 的 exit 1 清單少列一種

README 第 221-222 行列了四種回 1 的情況。原始碼第 69-71 行還有第五種：目標專案的 `.claude/settings.json` 存在但不是合法 JSON 時，拒絕覆寫並回 1。這個拒絕本身是好設計，README 漏列而已。

建議：README 補上這一種。

### 出入四：「.gitignore 已擋」只對慣用檔名成立

README 第 109 行說校準管線「產出的 JSON 都含對話內容，不進版控（.gitignore 已擋）」。.gitignore 擋的是固定模式：`*profiles.json`、`negatives.json`、`corpus-*.json`、`signals.json`、`reactive.json`、`turns*.json`、`fingerprints*.json`。

問題在 classify-turns.mjs 與 build-fingerprints.mjs 的輸出檔名是使用者自己給的位置參數，sample-hits.mjs 的 `--json` 輸出也是自己重導向。取名 turns-x.json、fingerprints-y.json 會被擋，取名 out.json 或 hits.json 就不會。README 這句話讀起來像「不管存成什麼都擋得住」，實際上擋的是命名慣例。

建議：README 那句補一句「前提是輸出檔名跟著 .gitignore 列的模式取」，或者在 .gitignore 對這幾支的輸出換更寬的擋法。二選一，屬 owner 的取捨。

## 四、這次稽核沒驗的東西

照不欺騙的紀律，講清楚邊界：

- 沒有實際執行任何一支腳本。驗的是「README 講的跟原始碼寫的一致」，不是「原始碼跑起來跟它寫的一致」。exit code 是讀 return 與 process.exit 語句得出，不是跑出來的。
- find-owner-signals.mjs、calibrate.mjs、self-scan-v2.mjs、classify-turns.mjs 四支只完整讀了與 README 宣稱相關的段落（用法、參數、exit、分類常數、排除規則），中段的統計邏輯沒有逐行讀。README 對那些中段沒有可查核的具體宣稱，所以不影響本次結論。
- README 裡引用的歷史事件（8 筆手動派工、17 小時、40 個 session 3877 次命中、每千則 242 次這類數字）是引用當時的量測，不是 README 對腳本行為的宣稱，本次不在稽核範圍。
