#!/bin/bash
# 雙擊就開。繞過 Tauri 的 WebView bug（macOS 26 上它不執行 JavaScript）。
# 畫面跟桌面版一模一樣:同一份 app.js 與 app.css。
cd "$(dirname "$0")"
pkill -f "ui-harness.py" 2>/dev/null
sleep 1
nohup python3 tools/ui-harness.py --port 8791 > /tmp/forseti-ui.log 2>&1 &
until curl -s -o /dev/null http://127.0.0.1:8791/ 2>/dev/null; do sleep 1; done
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --app=http://127.0.0.1:8791/ \
  --window-size=360,900 \
  --window-position=40,60 \
  --user-data-dir="$HOME/.forseti/chrome-profile" \
  --no-first-run --no-default-browser-check >/dev/null 2>&1 &
