#!/bin/bash
# 部署桌面版。**不要用 rm -rf 再 cp。**
#
# 【2026-09-15 查了一整晚才找到】
# 先前的部署是 `rm -rf ~/Applications/Forseti.app && cp -R ...`。
# bundle 的識別碼沒變，但整份檔案被換掉，LaunchServices 的快取
# 還指著已經不存在的東西。結果 `open` 會啟動一個不建視窗的殼：
#
#   進程活著、Rust 日誌說 visible=true、系統回報 0 個視窗
#
# 而直接執行 bundle 裡的二進位就一切正常。那個差異讓人以為是
# 程式壞掉，於是往截圖、權限、沙盒、TCC、掛載命名空間查了一輪，
# 全部都在錯的層。**真正的原因是部署指令本身。**
#
# 【2026-09-15 第二個坑】SRC 原本寫死成
# `~/.forseti/build/forseti-desktop/debug/bundle/macos/Forseti.app`。
# 換一種 CARGO_TARGET_DIR 的設法，產物會落在
# `~/.forseti/build/debug/bundle/macos/Forseti.app`，少一層。
# 舊路徑仍然存在（裡面是舊產物），所以 `[ -d "$SRC" ]` 通過，
# 於是靜默部署了舊版，畫面上一個新東西都沒有而且不報錯。
#
# 這跟 WIDGET_SPEC §28.9 記的是同一個形狀:看起來有在檢查，
# 實際回的是舊答案。所以這裡改成兩件事都做:
#   一，不寫死路徑，挑最新的產物。
#   二，部署後比對二進位的時間戳，沒換成功就當失敗。
set -e
DST=~/Applications/Forseti.app
SRC=$(find ~/.forseti/build -maxdepth 6 -name "Forseti.app" -type d 2>/dev/null \
      | xargs -I{} stat -f "%m %N" {} 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-)

[ -n "$SRC" ] && [ -d "$SRC" ] || { echo "  沒有建置產物，先跑 npx tauri build --debug --bundles app"; exit 1; }

# 【2026-09-16 第三個坑】部署前先跑守門測試。
#
# 這支先前只驗「視窗數 > 0」。而 2026-09-15 到 09-16 之間有三次
# 畫面整頁變成一行 ReferenceError，視窗照樣開得出來，它照樣回報
# 「部署完成」。三次都是部署之後才發現，其中兩次是 owner 先看到的。
#
# `node --check` 抓不到這種錯（語法是合法的），所以防線放在測試:
# test_js_symbols 抓「呼叫了但沒定義」，test_ui_contract 抓 DOM 契約
# 與 CSS 變數。這兩組不過就不准部署。
REPO=$(cd "$(dirname "$0")/.." && pwd)
if ! python3 -m pytest "$REPO/tests/test_js_symbols.py" "$REPO/tests/test_ui_contract.py" -q >/tmp/forseti-deploy-gate.txt 2>&1; then
  echo "  守門測試沒過，不部署。畫面很可能整頁是錯誤訊息："
  tail -12 /tmp/forseti-deploy-gate.txt | sed 's/^/    /'
  exit 1
fi
echo "  守門測試通過"
echo "  來源 $SRC"
echo "  建於 $(stat -f '%Sm' -t '%m-%d %H:%M' "$SRC/Contents/MacOS/forseti-desktop")"
BEFORE=$(stat -f "%m" "$DST/Contents/MacOS/forseti-desktop" 2>/dev/null || echo 0)

pkill -9 -f "Forseti.app/Contents/MacOS" 2>/dev/null || true
sleep 2
mkdir -p ~/Applications
# rsync 保留 bundle 本身，只換裡面的檔案
rsync -a --delete "$SRC/" "$DST/"
touch "$DST"
# 重新註冊，讓 LaunchServices 的快取跟上
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DST" 2>/dev/null || true
sleep 1

# 【2026-09-16 owner 明令】部署不再自動開視窗。
#
#     你現在每幾分鐘殺掉又開啟又殺掉又開啟
#
# 這支先前每次部署都 pkill 再 open，而自動接續每 7 分鐘可能跑一次部署，
# 於是視窗在她眼前反覆消失又跳出來。**部署是把檔案換掉，不是把視窗打開。**
# 要開視窗自己加 FORSETI_OPEN=1，或者手動 open。
if [ "${FORSETI_OPEN:-0}" = "1" ]; then
  open "$DST"
else
  echo "  沒有開視窗（要開就 FORSETI_OPEN=1 再跑一次）"
  echo "  部署完成，二進位 $(stat -f '%Sm' -t '%m-%d %H:%M' "$DST/Contents/MacOS/forseti-desktop")"
  exit 0
fi
sleep 5
# 目標要跟來源一樣新。比「跟部署前不同」準確 ——
# 重複部署同一份的時候來源跟目標本來就一樣，那是正常不是失敗，
# 舊版的寫法會在這種情況誤報中止。
SRCM=$(stat -f "%m" "$SRC/Contents/MacOS/forseti-desktop" 2>/dev/null || echo 0)
AFTER=$(stat -f "%m" "$DST/Contents/MacOS/forseti-desktop" 2>/dev/null || echo 0)
[ "$AFTER" = "$SRCM" ] || { echo "  二進位跟來源對不上，部署的可能是舊的。中止"; exit 1; }
# 視窗要等一下才建得起來。查一次就下結論會誤報 0，
# 而誤報會讓人以為 app 壞掉，然後往權限、沙盒那些錯的層去查。
n=0
for _ in $(seq 1 14); do
  n=$(osascript -e 'tell application "System Events" to count windows of (first process whose bundle identifier is "com.norika.forseti")' 2>/dev/null || echo 0)
  [ "$n" -ge 1 ] && break
  sleep 2
done
echo "  部署完成，視窗數 $n，二進位 $(stat -f '%Sm' -t '%m-%d %H:%M' "$DST/Contents/MacOS/forseti-desktop")"
[ "$n" -ge 1 ] || { echo "  視窗沒出來 —— 看 Rust 日誌：直接跑 $DST/Contents/MacOS/forseti-desktop"; exit 1; }
