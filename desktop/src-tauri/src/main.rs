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

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            spawn_watcher(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            snapshot, sessions, timeline, repo_path
        ])
        .run(tauri::generate_context!())
        .expect("Forseti 啟動失敗");
}
