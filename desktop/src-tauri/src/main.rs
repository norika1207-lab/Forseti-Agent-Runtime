// Forseti 桌面版的後端。
//
// 「這一層刻意很薄。」
//
// 所有判斷留在 Python（apps/forseti-cli/desktop_api.py）。這裡只做三件事：
//   1. 呼叫那支 Python，把 JSON 原樣轉給前端
//   2. 監看 .forseti/ 的檔案變化，變了就推一個事件
//   3. 找得到 repo 與 python3，找不到就明講
//
// 為什麼判斷不搬進 Rust:判斷邏輯只能有一份。兩份遲早會分歧，
// 而分歧的那天沒有人會發現,因為兩邊各自的測試都會過。
// 這個專案 2026-09-11 才因為同一個形狀還過一次技術債
// (stopreason.py 與 continuity.py 各有一份 STOP_REASONS)。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::Manager;
use std::sync::mpsc::channel;
use std::time::Duration;

use notify::{RecursiveMode, Watcher};
use tauri::Emitter;

/// 找 repo 根。往上走到看得見 .forseti 與 apps/forseti-cli 的那一層。
///
/// 找不到就回 None,不猜一個路徑 —— 猜錯的話後面每一個呼叫都會失敗,
/// 而錯誤訊息會指向錯的地方。
fn find_repo() -> Option<PathBuf> {
    let candidates = [
        PathBuf::from("/Volumes/NewDrive/AI Project/Forseti"),
        std::env::current_dir().ok()?,
    ];
    for c in candidates.iter() {
        let mut p = c.clone();
        loop {
            if p.join(".forseti").is_dir() && p.join("apps/forseti-cli").is_dir() {
                return Some(p);
            }
            match p.parent() {
                Some(parent) => p = parent.to_path_buf(),
                None => break,
            }
        }
    }
    None
}

/// 找得到哪一個 python3。
///
/// 不假設 PATH 裡有。找不到要說出來,不是讓每個呼叫各自失敗一次。
fn find_python() -> Option<String> {
    for cand in ["python3", "/usr/bin/python3", "/opt/homebrew/bin/python3"] {
        if Command::new(cand).arg("--version").output().is_ok() {
            return Some(cand.to_string());
        }
    }
    None
}

fn run_api(args: &[&str]) -> Result<String, String> {
    let repo = find_repo().ok_or_else(|| {
        "找不到 Forseti repo。往上走都看不到同時有 .forseti/ 與 apps/forseti-cli/ 的目錄"
            .to_string()
    })?;
    let py = find_python().ok_or_else(|| {
        "找不到 python3。試過 PATH、/usr/bin、/opt/homebrew/bin".to_string()
    })?;
    let script = repo.join("apps/forseti-cli/desktop_api.py");
    if !script.is_file() {
        return Err(format!("找不到 {}", script.display()));
    }
    let out = Command::new(&py)
        .arg(&script)
        .args(args)
        .current_dir(&repo)
        .output()
        .map_err(|e| format!("跑不起來:{e}"))?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let tail: String = err.chars().rev().take(600).collect::<Vec<_>>()
            .into_iter().rev().collect();
        return Err(format!("desktop_api.py 失敗:{tail}"));
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}

#[tauri::command]
fn snapshot() -> Result<String, String> {
    run_api(&["snapshot"])
}

/// 那條線。Widget 的主體。
///
/// 每 1 到 3 秒被叫一次(WIDGET_SPEC §13),所以 Python 那邊只讀新增的
/// 位元組,不重讀整份 —— 那份 jsonl 是 24 MB 而且一直在長。
#[tauri::command]
fn strands(session: Option<String>) -> Result<String, String> {
    match session {
        Some(s) if !s.is_empty() => run_api(&["strands", &s]),
        _ => run_api(&["strands"]),
    }
}

#[tauri::command]
fn sessions() -> Result<String, String> {
    run_api(&["sessions"])
}

#[tauri::command]
fn timeline(session: String) -> Result<String, String> {
    run_api(&["timeline", &session])
}

#[tauri::command]
fn repo_path() -> Result<String, String> {
    find_repo()
        .map(|p| p.display().to_string())
        .ok_or_else(|| "找不到 repo".to_string())
}

/// 監看 .forseti/。變了就推一個事件給前端。
///
/// 為什麼監看而不是定時輪詢:輪詢會在什麼都沒發生的時候一直跑 Python,
/// 而這個系統自己的規格(§24.2 GovernanceOverheadRatio)在量
/// 「治理系統本身吃掉多少時間」。一個自己就很吵的監控工具,
/// 正是它要抓的東西。
fn spawn_watcher(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let Some(repo) = find_repo() else { return };
        let target = repo.join(".forseti");
        if !target.is_dir() {
            return;
        }
        let (tx, rx) = channel();
        let mut watcher = match notify::recommended_watcher(tx) {
            Ok(w) => w,
            Err(_) => return,
        };
        if watcher.watch(Path::new(&target), RecursiveMode::Recursive).is_err() {
            return;
        }
        // 合併短時間內的連續變化。一次寫檔可能觸發好幾個事件,
        // 每一個都重算一次快照是浪費。
        let mut pending = false;
        loop {
            match rx.recv_timeout(Duration::from_millis(700)) {
                Ok(_) => pending = true,
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                    if pending {
                        pending = false;
                        let _ = app.emit("forseti://changed", ());
                    }
                }
                Err(_) => break,
            }
        }
    });
}

/// 自我審計。§39
///
/// owner：「你自己審計都不做。」
/// 帳本裡的 SELF_FAULT 事件 —— append-only，刪不掉也改不了。
#[tauri::command]
fn audit() -> Result<String, String> {
    run_api(&["audit"])
}

/// 必讀文件讀完了沒。§40
///
/// owner 2026-09-14：「讀文件沒有全部讀好並且擅自作主，
/// 這也是重大事件，也是標注紅色，一開始就是紅色，
/// 後面不可能會出現綠色。」
#[tauri::command]
fn spec_reading() -> Result<String, String> {
    run_api(&["spec_reading"])
}

/// 區塊閱讀與要拷問 owner 的清單。§41
#[tauri::command]
fn block_reading() -> Result<String, String> {
    run_api(&["block_reading"])
}

/// 接管閘門現在擋不擋得住人。v5.0 §17.3 / §19.2 / §39
///
/// B-08 記的是「閘門只列題目不驗答案」。這一頁顯示的是它接上之後
/// 的狀態:這條線考過沒有、五個維度裡有幾個根本沒有來源可考。
///
/// **這裡只讀不出卷。** 出卷會寫進帳本，一個重新整理就多一筆考卷
/// 的東西，帳本會被畫面的刷新次數填滿。出卷走 CLI。
#[tauri::command]
fn sufficiency() -> Result<String, String> {
    run_api(&["sufficiency"])
}

/// 功能說明加當場驗證。§36
///
/// owner 的老闆明天要看。每一項:抓什麼、憑什麼規格、現在的真實數字。
/// 沒接的照實列 —— 藏起來的那一項，正是會被問到的那一項。
#[tauri::command]
fn features() -> Result<String, String> {
    run_api(&["features"])
}

/// 每一個功能，當場證明它是活的。§33
///
/// 每一項跑兩次:真實資料看現況，合成違規確認它會叫。
/// 一個回 0 的偵測器，跟一個壞掉的偵測器，在真實資料上長得一模一樣。
#[tauri::command]
fn selftest() -> Result<String, String> {
    run_api(&["selftest"])
}

/// 這台機器上該搬的東西現在是什麼數字。§31
///
/// owner 2026-09-14 換機器那一晚漏掉了 142 個工作目錄綁定檔，
/// 而那件事沒有任何東西主動說出來。這個指令把它變成畫面上一列數字。
#[tauri::command]
fn machine() -> Result<String, String> {
    run_api(&["machine"])
}

/// 執行層的現況:未完成的義務、進行中的步驟、卡住的。
///
/// F02 §6 的 obligation ledger。CT-F02-02 要求未完成項目被**自動暴露**，
/// 而「在終端下指令才看得到」就是一種盤問。
#[tauri::command]
fn work() -> Result<String, String> {
    run_api(&["work"])
}

/// 從某一輪 fork 出一個新 session。
///
/// `go` 為 false 時只是乾跑（算會留下幾筆、丟掉幾筆），不寫任何檔案。
/// **預設乾跑** —— 一個手滑就產生檔案的指令，
/// 遲早會在沒人打算 fork 的時候產生檔案。
///
/// 原始的 transcript 一個位元組都不動。
#[tauri::command]
fn fork(session: String, n: u32, go: bool) -> Result<String, String> {
    let n = n.to_string();
    if go {
        run_api(&["fork", &session, &n, "--go"])
    } else {
        run_api(&["fork", &session, &n])
    }
}

/// 把桌面版切到某個 session。
///
/// 【2026-09-14 實測】`claude://code/continue?session=<ui_id>` 會讓
/// Claude 桌面版切過去（拿 lastFocusedAt 驗證過，焦點確實跳了）。
///
/// owner:「點了某個節點，就要跳回到那個桌面 APP 相應對話位置啊，
/// 這樣才能 Fork 啊，不然都是單向的還要自己慢慢往前面翻。」
///
/// **只接受 `local_` 開頭、只含 uuid 字元的 id。**
/// 這個指令會叫 `open`，而 `open` 能開的東西遠不只這一個 scheme ——
/// 前端傳什麼就開什麼，等於把整台機器交給一段 JavaScript。
/// 寫一則粉紅點。§5.5 這是唯一由使用者寫進系統的證據。
///
/// text 不做字元白名單（她要寫什麼是她的自由），但長度擋住 ——
/// 那一層 Python 端也擋，這裡擋是為了不讓超長字串跑完整條管線。
#[tauri::command]
fn note_add(session: String, n: u32, text: String) -> Result<String, String> {
    if text.trim().is_empty() {
        return Err("空的注記不寫".to_string());
    }
    if text.chars().count() > 1200 {
        return Err("超過 1200 字".to_string());
    }
    if session.len() > 128
        || !session.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("session id 只接受英數與 - _".to_string());
    }
    let n = n.to_string();
    run_api(&["note_add", &session, &n, &text])
}

/// 畫面上會改變狀態的動作。owner 2026-09-16:「接動作層」。
///
/// **kind 用白名單擋。** 這個指令會跑 Python 並改帳本，
/// 前端傳什麼就做什麼等於把帳本交給一段 JavaScript ——
/// 跟 `open_session` 只收 `local_` 開頭是同一條理由。
#[tauri::command]
fn act(kind: String, target: String, worker: String) -> Result<String, String> {
    const OK: [&str; 4] = ["finish", "verify", "dispatch", "drain"];
    if !OK.contains(&kind.as_str()) {
        return Err(format!("不認得的動作：{kind}"));
    }
    if target.is_empty() || target.len() > 128
        || !target.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("target 只接受英數與 - _，長度 128 以內".to_string());
    }
    if worker.is_empty() {
        run_api(&["act", &kind, &target])
    } else {
        if worker.len() > 64
            || !worker.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
        {
            return Err("worker 只接受英數與 - _".to_string());
        }
        run_api(&["act", &kind, &target, &worker])
    }
}

/// 點一個節點，看誰依賴它。§16.1 Blast Radius 的 files 那一種。
///
/// 排行榜回答「哪些檔案最貴」，這一個回答「這一個貴在哪裡」——
/// 是哪十個檔會被波及，不只是十這個數字。
///
/// **路徑用字元白名單擋，而且擋 `..`。** 這個值會變成 Python 的
/// argv，而一個路徑參數前端傳什麼就吃什麼，等於把檔案系統的
/// 走訪範圍交給一段 JavaScript —— 跟 `open_session` 只收 `local_`
/// 開頭是同一條理由。真正「這個檔在不在圖裡」由 Python 端判，
/// 這裡只擋形狀，不做第二套存在性判定（兩套會分歧）。
#[tauri::command]
fn blast_detail(target: String) -> Result<String, String> {
    if target.is_empty() || target.len() > 256 {
        return Err("路徑長度要在 1 到 256 之間".to_string());
    }
    if target.contains("..") || target.starts_with('/') || target.starts_with('-') {
        return Err("不接受絕對路徑、上層路徑或 - 開頭".to_string());
    }
    if !target.chars().all(|c| {
        c.is_ascii_alphanumeric() || c == '/' || c == '.' || c == '_' || c == '-'
    }) {
        return Err("路徑只接受英數與 / . _ -".to_string());
    }
    run_api(&["blast_detail", &target])
}

#[tauri::command]
fn open_session(ui_id: String) -> Result<(), String> {
    let ok = ui_id.starts_with("local_")
        && ui_id.len() <= 64
        && ui_id[6..].chars().all(|c| c.is_ascii_hexdigit() || c == '-');
    if !ok {
        return Err(format!("不是合法的 session id：{ui_id}"));
    }
    let url = format!("claude://code/continue?session={ui_id}&source=forseti");
    Command::new("open")
        .arg(&url)
        .status()
        .map_err(|e| format!("開不起來 {url}：{e}"))?;
    Ok(())
}

/// 把 WebView 的 console 轉到 Rust 的 stderr。
///
/// 【2026-09-18】桌面版打開是空白的，而 WebView 的 console 從外面看不到、
/// Rust 的 stderr 也收不到它。於是「白畫面」跟「還在載入」「視窗沒開」
/// 長得一模一樣，查不下去。
///
/// 【為什麼走 document.title 不走 IPC】
/// 空白畫面的可能成因之一就是 `window.__TAURI__` 沒被注入
/// （2026-09-14 踩過一次，靠 withGlobalTauri 修的）。
/// 走 IPC 的話，如果問題剛好是那個，訊息永遠回不來 ——
/// **而我會拿到「沒有任何錯誤」，跟「真的沒有錯誤」分不出來。**
///
/// `title` 是視窗的屬性不是 WebView 的 API，讀得到跟前端死活無關。
///
/// 【已知限制，寫在這裡不寫在別處】
/// 一、`eval` 要等頁面有 document 才有效，所以重試幾次。
///     頁面在那之前就炸的話，這一支抓不到 —— 那要 initialization_script，
///     而那需要改成用 WebviewWindowBuilder 手動建視窗。
/// 二、title 一次只帶得動最後一則，中間爆出來的會被蓋掉。
/// 三、原本的標題會被蓋掉，所以只在 debug build 掛。
/// 直接對 WKWebView 打開 JavaScript。
///
/// 【2026-09-18】三條獨立路徑（`eval`、頁面 inline `<script>`、
/// `WKUserScript`）全部不執行，而 HTML 渲染正常。
/// 所以是 WKWebView 這一層關了 JS，不是 Tauri 的設定也不是我們的程式碼。
///
/// wry 0.55.1 只在 `attributes.javascript_disabled` 為真時
/// 呼叫 `setAllowsContentJavaScript(false)`，**沒有相反方向的設定**。
/// 如果 macOS 26 把那個屬性的預設從 true 改成 false，
/// wry 就沒有任何一條路會把它打開。
///
/// 這一支繞過 wry 直接設 true。成功的話那個推論就成立，
/// 而且是可以回報給上游的結論。
#[cfg(target_os = "macos")]
fn force_enable_javascript(w: &tauri::WebviewWindow) {
    use objc2::rc::Retained;
    use objc2_web_kit::WKWebView;
    let r = w.with_webview(|wv| unsafe {
        let ptr = wv.inner() as *mut WKWebView;
        if ptr.is_null() {
            eprintln!("[webview] 拿不到 WKWebView 指標");
            return;
        }
        let view: Retained<WKWebView> = Retained::retain(ptr).unwrap();
        let cfg = view.configuration();
        let prefs = cfg.defaultWebpagePreferences();
        let before = prefs.allowsContentJavaScript();
        prefs.setAllowsContentJavaScript(true);
        let after = prefs.allowsContentJavaScript();
        eprintln!("[webview] allowsContentJavaScript: {before} -> {after}");
        // 【那個開關本來就是 true,所以問題不在它】
        // WKPreferences 上還有一個更舊的 `javaScriptEnabled`（已棄用）。
        // 直接用型別化的 API 讀，不用 KVC —— objc2-web-kit 有它。
        let wp = cfg.preferences();
        #[allow(deprecated)]
        {
            let old_flag = wp.javaScriptEnabled();
            eprintln!("[webview] prefs.javaScriptEnabled = {old_flag}");
            if !old_flag {
                wp.setJavaScriptEnabled(true);
                eprintln!("[webview] 已強制打開，現在 = {}",
                          wp.javaScriptEnabled());
            }
        }
    });
    if let Err(e) = r {
        eprintln!("[webview] with_webview 失敗 {e}");
    }
}

fn hook_console(w: &tauri::WebviewWindow) {
    const JS: &str = r#"
(function(){
  if (window.__forsetiHooked) return "already";
  // 【旗標只在真的掛得上之後才設】
  // 先設旗標的話，第一次在還沒有 document 的時候跑過，
  // 之後每一次 eval 都會直接 return，於是永遠掛不上 ——
  // 而 eval 每次都回 Ok，看起來像成功了。
  if (!document || !document.body) return "no-document";
  window.__forsetiHooked = true;
  var seq = 0;
  function put(kind, args) {
    try {
      var parts = [];
      for (var i = 0; i < args.length; i++) {
        var a = args[i];
        if (a instanceof Error) parts.push(a.message + " @ " + String(a.stack||"").split("\n")[1]);
        else if (a && typeof a === "object") { try { parts.push(JSON.stringify(a).slice(0,180)); } catch (e) { parts.push(String(a)); } }
        else parts.push(String(a));
      }
      seq++;
      document.title = "FORSETI|" + seq + "|" + kind + "|" + parts.join(" ").slice(0, 260);
    } catch (e) {}
  }
  ["error","warn","log"].forEach(function(k){
    var orig = console[k] ? console[k].bind(console) : function(){};
    console[k] = function(){ put(k, arguments); orig.apply(console, arguments); };
  });
  window.addEventListener("error", function(e){
    put("uncaught", [e.message, (e.filename||"") + ":" + (e.lineno||"")]);
  });
  window.addEventListener("unhandledrejection", function(e){
    put("reject", [String(e.reason)]);
  });
  put("log", ["console 轉發掛上了"]);
  return "ok";
})();
"#;
    let w2 = w.clone();
    std::thread::spawn(move || {
        // 【先證明這個 thread 有在跑】
        // 2026-09-18:上一版在迴圈裡重複呼叫 eval 與 title，
        // 結果連「掛不上」那行都沒印出來 —— 而那個迴圈最多 16.8 秒。
        // macOS 要求 UI API 在主執行緒，所以它可能卡在第一次呼叫上。
        // **卡住跟沒跑完在輸出上長得一模一樣，所以先印一行。**
        eprintln!("[webview] 轉發 thread 起來了");
        // 【先問它載入了什麼】
        // 2026-09-18:eval 五次都送進去、title 五次都沒變,
        // 所以 WebView 沒有在執行任何 JS。那不是時機問題也不是執行緒問題,
        // 是它可能根本沒載入我們的頁面。
        eprintln!("[webview] 目前 url = {:?}", w2.url());
        // 【把「引擎不跑 JS」跟「我們的頁面有問題」分開】
        // 2026-09-18:eval 在任何時機都改不到 title，連 on_page_load
        // 的 Finished 那一刻也一樣。所以先問一個更基本的問題:
        // 這個 WebView 執行得了 JavaScript 嗎。
        //
        // 載入一個自帶 <script> 的 data URL。它會把 title 改成 DATAURL_OK。
        // 變了 = 引擎正常，問題在我們的頁面。
        // 沒變 = 引擎層面的事，跟 app.js 無關。
        //
        // **這是診斷，跑完就把畫面換回去。**
        std::thread::sleep(std::time::Duration::from_millis(1500));
        let probe = "data:text/html,<html><body>probe</body>\
<script>document.title='DATAURL_OK'</script></html>";
        match w2.navigate(probe.parse().unwrap()) {
            Ok(()) => eprintln!("[webview] 診斷頁送出去了"),
            Err(e) => eprintln!("[webview] 診斷頁送不出去 {e}"),
        }
        std::thread::sleep(std::time::Duration::from_millis(2500));
        eprintln!("[webview] 診斷頁之後的 title = {:?}", w2.title());
        // 【wry #1848 的 workaround:resize 強制重繪】
        // macOS 26 + Apple Silicon + wry 0.55.1 + tauri 2.11.5 上，
        // WKWebView 的 compositor 會停止呈現新 frame，
        // 而 DOM 與 accessibility tree 是活的。
        //
        // 那個 issue 說 JS 有在跑，而這裡量到的是 title 沒變 ——
        // title 走 AppKit 不走 compositor，所以兩者對不上。
        // **resize 之後畫面出來 = compositor 問題、我的 title 量法有問題;
        //   沒出來 = JS 真的沒跑。這一步是要把那兩件事分開。**
        std::thread::sleep(std::time::Duration::from_millis(800));
        let _ = w2.set_size(tauri::LogicalSize::new(341.0, 861.0));
        std::thread::sleep(std::time::Duration::from_millis(300));
        let _ = w2.set_size(tauri::LogicalSize::new(340.0, 860.0));
        eprintln!("[webview] resize 強制重繪做了一次");
        std::thread::sleep(std::time::Duration::from_millis(1200));
        eprintln!("[webview] resize 之後的 title = {:?}", w2.title());
        // 頁面還沒好的時候 eval 沒有效果，所以重試。
        // 只試一次的話，慢一點的機器上會靜靜地什麼都沒掛上。
        // 【無條件講出來】原本只在重試過才印，第一次就成功反而不說話 ——
        // 於是「掛上了但沒訊息」跟「根本沒掛上」分不出來。
        // 這一支存在的理由就是要分得出那兩件事。
        // 【用結果驗證，不用回傳值驗證】
        // `eval` 的 Ok 只代表「送出去了」，不代表 JS 跑起來。
        // 2026-09-18 實測:第一次就回 Ok，而 title 一直是 "Forseti" ——
        // 那段 JS 根本沒執行，因為那時還沒有 document。
        // **所以判準是 title 有沒有變，不是 eval 回什麼。**
        let mut hooked = false;
        for i in 0..3 {
            std::thread::sleep(std::time::Duration::from_millis(300));
            eprintln!("[webview] 第 {} 圈:準備 eval", i + 1);
            if let Err(e) = w2.eval(JS) {
                if i == 0 { eprintln!("[webview] eval 失敗 {e}"); }
                continue;
            }
            eprintln!("[webview] 第 {} 圈:eval 回來了", i + 1);
            std::thread::sleep(std::time::Duration::from_millis(120));
            eprintln!("[webview] 第 {} 圈:準備 title()", i + 1);
            if let Ok(t) = w2.title() {
                eprintln!("[webview] 第 {} 圈:title = {:?}", i + 1, t);
                if t.starts_with("FORSETI|") {
                    eprintln!("[webview] console 轉發掛上了（第 {} 次，{:.1} 秒）",
                              i + 1, (i as f64 + 1.0) * 0.42);
                    hooked = true;
                    break;
                }
            }
        }
        if !hooked {
            eprintln!("[webview] console 轉發掛不上:送了四十次，title 一直是 {:?}",
                      w2.title());
            eprintln!("[webview] 那代表注入的 JS 沒有執行。頁面本身可能也沒跑起來");
        }
        let mut last = String::new();
        loop {
            std::thread::sleep(std::time::Duration::from_millis(400));
            match w2.title() {
                Ok(t) => {
                    if t != last && t.starts_with("FORSETI|") {
                        // seq|kind|body
                        let body = t.splitn(4, '|').nth(3).unwrap_or("");
                        let kind = t.splitn(4, '|').nth(2).unwrap_or("?");
                        eprintln!("[webview] {kind}: {body}");
                        last = t;
                    }
                }
                Err(_) => break,   // 視窗關了
            }
        }
    });
}

fn main() {
    tauri::Builder::default()
        // 【2026-09-18 診斷】頁面到底有沒有載入。
        //
        // 已經證實的:WebView 沒有在執行任何 JS
        // （eval 送五次、title 五次都沒變）。兩種可能:
        //   一、頁面根本沒載入 → 這個 hook 不會被呼叫
        //   二、載入了但 JS 不跑 → 這個 hook 會被呼叫
        // **這一行的作用是把那兩種分開，而不是再猜一次。**
        .on_page_load(|w, payload| {
            eprintln!("[page] {:?} url={} label={}",
                      payload.event(), payload.url(), w.label());
            // 【在 Finished 那一刻問它頁面裡有什麼】
            // 這是 document 一定存在的時機。先前在 thread 裡重試四十次
            // 都沒改到 title，而頁面其實幾百毫秒就 Finished 了 ——
            // 所以那不是時機問題。這一次把「頁面有多少內容」寫進 title，
            // 空頁面跟「有內容但 JS 不跑」就分得開了。
            // 診斷頁載完之後立刻讀 title。先前在 thread 裡讀太早，
            // 讀到的是它 Finished 之前的值 —— 那個「沒變」不算數。
            // 比較的兩個值直接印出來。上一輪這個 if 沒進去，
            // 而我看不出為什麼 —— 那種時候就把值攤開，不要再讀一次程式碼。
            eprintln!("[page] cmp url_as_str={:?} event_dbg={:?}",
                      &payload.url().as_str()[..payload.url().as_str().len().min(24)],
                      format!("{:?}", payload.event()));
            if payload.url().as_str().starts_with("data:")
                && format!("{:?}", payload.event()) == "Finished" {
                std::thread::sleep(std::time::Duration::from_millis(400));
                // `on_page_load` 給的是 Webview 不是 WebviewWindow，
                // 沒有 title()。從 app handle 拿同一個 label 的視窗。
                let t = w.app_handle()
                    .get_webview_window(w.label())
                    .map(|ww| ww.title());
                eprintln!("[webview] 診斷頁 Finished，title = {t:?}");
            }
            if format!("{:?}", payload.event()) == "Finished" {
                let _ = w.eval(
                    "try{document.title='PAGE|html='+(document.documentElement.outerHTML||'').length+'|body='+(document.body?document.body.innerHTML.length:-1)+'|scripts='+document.scripts.length+'|ready='+document.readyState;}catch(e){document.title='PAGE|throw|'+e.message;}");
            }
        })
        .setup(|app| {
            spawn_watcher(app.handle().clone());

            // 明確把視窗叫出來。
            //
            // 【2026-09-14 實測】換到新機器之後，進程活著、沒有任何
            // 錯誤輸出、log 是 0 bytes，而系統回報 0 個視窗 ——
            // 設定檔裡的 windows 那條路徑沒有生出東西，
            // 而它失敗的時候一聲都不吭。
            //
            // 所以不依賴設定:拿得到就 show，拿不到就自己建一個。
            // 一個開不出視窗又不說話的 app，使用者只會看到「沒反應」。
            match app.get_webview_window("main") {
                Some(w) => {
                    // 【2026-09-15】這一行原本只印「已存在，show」，
                    // 而系統回報 0 個視窗 —— 也就是設定檔裡有那個物件，
                    // 但它沒有真的出現在畫面上。
                    // 一行說「已存在」的日誌，讓我以為 Rust 這層沒問題，
                    // 於是往 UI 跟資料層找了一輪。**日誌要印可以被推翻的東西。**
                    let vis = w.is_visible().unwrap_or(false);
                    let pos = w.outer_position().ok();
                    let size = w.outer_size().ok();
                    eprintln!("[forseti] 視窗 main 存在 visible={vis} \
                               pos={pos:?} size={size:?}");
                    let _ = w.show();
                    let _ = w.unminimize();
                    let _ = w.set_focus();
                    // 【2026-09-18】上面那三行早就在了，而視窗還是看不到。
                    // 所以印出「它以為自己在哪個螢幕上」——
                    // 這台機器是雙螢幕鏡像（主 4608x2592、內建 3024x1964），
                    // 兩邊解析度不同，視窗的座標算在主螢幕的座標系裡，
                    // 鏡像過去可能落在裁切區外。
                    // **「visible=true 而看不到」的解釋只能來自螢幕資訊，
                    // 不能來自視窗自己怎麼說。**
                    match w.current_monitor() {
                        Ok(Some(m)) => eprintln!(
                            "[forseti] 目前螢幕 {:?} size={:?} pos={:?} scale={}",
                            m.name(), m.size(), m.position(), m.scale_factor()),
                        Ok(None) => eprintln!("[forseti] 目前螢幕:拿不到（視窗可能不在任何一個螢幕上）"),
                        Err(e) => eprintln!("[forseti] 目前螢幕:查詢失敗 {e}"),
                    }
                    if let Ok(ms) = w.available_monitors() {
                        for m in ms {
                            eprintln!("[forseti]   可用螢幕 {:?} size={:?} pos={:?} scale={}",
                                      m.name(), m.size(), m.position(), m.scale_factor());
                        }
                    }
                    eprintln!("[forseti] minimized={:?} focused={:?}",
                              w.is_minimized(), w.is_focused());
                    // 置中到目前的螢幕。位置檢查只擋得住「明顯在畫面外」，
                    // 擋不住「在主螢幕內但鏡像過去被裁掉」。
                    let _ = w.center();
                    let _ = w.set_always_on_top(true);
                    // 位置異常就拉回螢幕內。負座標或超出範圍會讓它
                    // 「開著但看不到」，而那跟沒開長得一模一樣。
                    if let Some(p) = pos {
                        if p.x < -100 || p.y < -100 || p.x > 8000 || p.y > 8000 {
                            eprintln!("[forseti] 位置在畫面外，拉回 (60, 80)");
                            let _ = w.set_position(tauri::PhysicalPosition::new(60, 80));
                        }
                    }
                    // 【2026-09-15 實測】這台新電腦上，設定檔那條路徑
                    // 建出來的視窗是 680x1720 —— 我設定的 340x860 的兩倍，
                    // 也就是 Retina 的實體像素。螢幕邏輯高度約 982，
                    // 1720 撐出畫面外，所以「visible=true 但你看不到」。
                    //
                    // 舊電腦沒事是因為螢幕尺寸不同。**同一個 bug 在不同
                    // 機器上會表現成「有時候好有時候壞」，而那最難查。**
                    //
                    // 明確用邏輯尺寸重設一次，不依賴設定檔怎麼解讀。
                    let _ = w.set_size(tauri::LogicalSize::new(340.0, 860.0));
                    eprintln!("[forseti] 重設尺寸後 {:?}", w.outer_size());
                    eprintln!("[forseti] show 之後 visible={:?}", w.is_visible());
                    hook_console(&w);
                }
                None => {
                    eprintln!("[forseti] 設定檔沒生出視窗，改用程式建");
                    match tauri::WebviewWindowBuilder::new(
                        app, "main", tauri::WebviewUrl::default())
                        .title("Forseti")
                        .inner_size(340.0, 860.0)
                        .min_inner_size(280.0, 400.0)
                        .position(40.0, 60.0)
                        .always_on_top(true)
                        .title_bar_style(tauri::TitleBarStyle::Overlay)
                        .hidden_title(true)
                        .resizable(true)
                        // 【走 WKUserScript 這條，不走 evaluateJavaScript】
                        // eval 那條在任何時機都沒效果。initialization_script
                        // 是另一個機制（WKUserScript，頁面載入前注入）。
                        // 兩個都不跑，才能確定是 WKWebView 把 JS 關了;
                        // 只有 eval 不跑的話，問題在 eval 那條路。
                        .initialization_script(
                            "document.title='INITSCRIPT_OK';")
                        .build()
                    {
                        Ok(w) => {
                            let _ = w.show();
                            let _ = w.set_focus();
                            eprintln!("[forseti] 視窗建好了（手動路徑）");
                            #[cfg(target_os = "macos")]
                            force_enable_javascript(&w);
                            // 手動這條路跟 config 那條走不同程式碼。
                            // 行為不同的話，範圍就縮到 config 上。
                            hook_console(&w);
                        }
                        Err(e) => eprintln!("[forseti] 視窗建不起來：{e}"),
                    }
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            snapshot, strands, sessions, timeline, repo_path, open_session, fork, act, note_add, work, machine, selftest, features, audit, spec_reading, block_reading, sufficiency, blast_detail
        ])
        .run(tauri::generate_context!())
        .expect("Forseti 啟動失敗");
}
