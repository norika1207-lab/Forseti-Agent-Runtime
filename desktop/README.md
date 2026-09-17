# Forseti 桌面版

Tauri 2。Rust 那層只轉發，所有判斷在 `apps/forseti-cli/` 的 Python。

## 改 UI 不要 build

```bash
npx tauri dev
```

前端改完存檔就反映，Rust 不重編。

`npx tauri build` 是 release 編譯，要三到八分鐘。
**只有要產出 `.app` 的時候才用它。**

2026-09-14 的教訓：那天為了調配色跟排版，前後 build 了六次，
其中五次只改了 CSS 跟 JS。那五次全部可以用 dev 模式省掉。

## 什麼情況會全量重編

改 `src-tauri/tauri.conf.json` 的 `app.security` 區塊。
build script 會重新產生 ACL schema，整個 tauri crate 的依賴樹跟著重編。
那一次比平常慢一倍以上。

改 `src/main.rs` 只會重編自己這個 crate，快很多。

## 只在 UI 改動時，更快的驗證法

`tools/ui-harness.py` 把 `ui/` 三個檔案複製到暫存目錄，
用真實 transcript 產生 fixture，起一個本機 http server。
瀏覽器看到的畫面跟 `.app` 裡一模一樣（同一份 CSS 與 JS）。

**但它有一個已知盲點**，2026-09-14 付過代價：
harness 自己 stub 掉 `window.__TAURI__`，
所以它永遠測不出「前端連不連得上後端」。
`tests/test_ui_contract.py` 的 `TauriWiring` 補的就是那一層。

## 兩個 exFAT 的坑

專案在 NewDrive（exFAT），macOS 會為帶 xattr 的檔案寫 `._` sidecar，
而 Tauri 的 build script 會把那些 sidecar 當成真的設定檔去讀，
炸在「stream did not contain valid UTF-8」。

| 咬到哪 | 解法 |
|---|---|
| `permissions/._default.toml` | `.cargo/config.toml` 把 target-dir 指到本機 APFS |
| `capabilities/._default.json` | capability 內嵌進 `tauri.conf.json`，不要那個目錄 |

icon 必須是 RGBA，否則 `generate_context!` panic。

## 部署

```bash
npx tauri build --bundles app && rm -rf ~/Applications/Forseti.app && cp -R ~/.forseti/build/forseti-desktop/release/bundle/macos/Forseti.app ~/Applications/
```
