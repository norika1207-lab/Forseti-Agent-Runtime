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

fn main() {
    tauri::Builder::default()
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
                        .build()
                    {
                        Ok(w) => {
                            let _ = w.show();
                            let _ = w.set_focus();
                            eprintln!("[forseti] 視窗建好了");
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
