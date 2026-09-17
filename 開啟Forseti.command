#!/bin/bash
# 雙擊這個檔案就會開啟 Forseti。
#
# 2026-09-14 做的。owner 明天要 demo，而在這之前唯一的啟動方式
# 是在終端下指令 —— 那正是她從頭到尾沒有要過的東西。

cd "$(dirname "$0")" || exit 1

PORT=8830
while lsof -i :$PORT >/dev/null 2>&1; do PORT=$((PORT+1)); done

echo ""
echo "  Forseti 啟動中，第一次要等十幾秒"
echo ""

python3 tools/ui-harness.py --port $PORT > /tmp/forseti-ui.log 2>&1 &
PID=$!

for i in $(seq 1 40); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/index.html" 2>/dev/null; then
    open "http://127.0.0.1:$PORT/index.html"
    echo "  開好了　http://127.0.0.1:$PORT/index.html"
    echo ""
    echo "  這個視窗關掉，Forseti 就會停。"
    echo "  要停止請按 Control + C"
    echo ""
    wait $PID
    exit 0
  fi
  sleep 1
done

echo "  起不來。錯誤在 /tmp/forseti-ui.log"
tail -20 /tmp/forseti-ui.log
kill $PID 2>/dev/null
read -r -p "  按 Enter 關閉"
