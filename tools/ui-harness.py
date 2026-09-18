#!/usr/bin/env python3
"""在瀏覽器裡看 Widget，不用編譯。

改 UI 的時候，`npx tauri build` 要三到八分鐘，而改的往往只是
一行 CSS。這支把 `desktop/ui/` 那三個檔案複製到暫存目錄，
用真實 transcript 產生 fixture，起一個本機 http server。

畫面跟 `.app` 裡一模一樣 —— 同一份 CSS 與 JS。

## 已知盲點，寫在最前面因為它咬過一次

這支會 stub 掉 `window.__TAURI__`，不然 `app.js` 在瀏覽器裡跑不起來。

**所以它永遠測不出「前端連不連得上後端」。**

2026-09-14 就是這樣騙到自己的：UI 每個細節都在這裡驗過，
`.app` 打開卻是空的，因為 Tauri 2 預設不注入那個全域物件。
補那一層的是 `tests/test_ui_contract.py` 的 `TauriWiring`。

用法：

    python3 tools/ui-harness.py            # 起在 8791
    python3 tools/ui-harness.py --port 9000
    python3 tools/ui-harness.py --fake     # 塞一筆合成的白點進去看提示卡
"""

from __future__ import annotations

import http.server
import json
import shutil
import socketserver
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI = REPO / "desktop" / "ui"
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

STUB = '''<script>
// 假的 Tauri。**這正是這支工具的盲點所在** ——
// 它讓 app.js 跑得起來，也讓「連不連得上後端」永遠測不到。
const FIX = JSON.parse(document.getElementById("fx").textContent);
window.__TAURI__ = { core: { invoke: async (cmd, args) => {
  const v = FIX[cmd];
  // 帶參數的指令(blast_detail)。fixture 存的是「參數值 → 回傳」的表,
  // 因為同一個 cmd 對不同參數要回不同東西。
  // **查不到不回空物件** —— 空的明細在畫面上讀起來像「沒有人依賴它」,
  // 而真相是 harness 沒有預先算那一個。
  if (v && v.__by_arg) {
    const key = args ? args[v.__by_arg] : undefined;
    const hit = v.rows ? v.rows[key] : undefined;
    return JSON.stringify(hit ?? { has: false, target: key ?? "",
      why: "harness fixture 沒有預先算這一個(只算了排行榜上那幾個)" });
  }
  return JSON.stringify(v ?? {});
} } };
</script>
<script src="app.js"></script>'''


def build(out: Path, fake: bool, session: str = "") -> None:
    import desktop_api as D

    for name in ("app.css", "app.js", "index.html"):
        shutil.copy2(UI / name, out / name)

    data = D.strands(session)
    if fake:
        row = _fake_betrayal()
        rows = data.get("rows") or []
        if rows:
            rows[max(0, len(rows) - 6)]["betrayals"] = row
            data["betrayal_total"] = len(row)

    # 每一個前端會 invoke 的指令都要在 fixture 裡，
    # 不然那個功能在 harness 裡是死的，而死的跟壞的長得一樣。
    #
    # 【2026-09-14 實測驗證過這句話】加了 spec_reading 跟 block_reading
    # 之後忘了補這裡，瀏覽器版點「讀文件」什麼都沒有 ——
    # 症狀跟 renderSpec 寫壞完全一樣，查了才發現是 fixture 少了兩把鑰匙。
    # blast_detail 帶參數，所以存的是「參數 → 回傳」的表，不是單一結果。
    # 只算排行榜上那幾個:每一個都要跑一次 node，全部 104 個檔會讓
    # harness 起不來。查不到的那些由 stub 回「沒有預先算」，不回空的。
    blast_rows = {"__by_arg": "target", "rows": {}}
    try:
        import blast as BL
        want = [t.get("target") for t in
                ((data.get("blast") or {}).get("top") or []) if t.get("target")]
        # 排行榜以外再預算兩個，因為搜尋框的出口條件正是「排行榜上沒有
        # 的檔也點得開」。只算排行榜的話，harness 上驗不到那件事。
        for extra in ((data.get("blast") or {}).get("all_files") or []):
            if len(want) >= len(
                    ((data.get("blast") or {}).get("top") or [])) + 2:
                break
            if extra not in want:
                want.append(extra)
        for tgt in want:
            blast_rows["rows"][tgt] = BL.detail(tgt)
    except Exception as e:  # harness 是開發工具，算不出來不該擋住整個畫面
        blast_rows["rows"] = {}
        print(f"  blast_detail 算不出來：{e}", file=sys.stderr)

    fixture = {"strands": data, "snapshot": D.snapshot(),
               "blast_detail": blast_rows,
               "sessions": D.sessions(), "work": D.work(),
               "machine": D.machine(), "features": D.features(),
               "selftest": D.selftest(), "audit": D.audit(),
               "spec_reading": D.spec_reading(),
               "block_reading": D.block_reading(),
               "sufficiency": D.sufficiency_state()}
    (out / "fixture.json").write_text(
        json.dumps(fixture, ensure_ascii=False), encoding="utf-8")

    html = (UI / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="app.js"></script>', STUB)
    # `</` 一定要跳脫。
    #
    # 【2026-09-14 實測】transcript 裡本來就會出現 `</script>` 這種字串
    # （這個 session 自己就在討論 HTML）。不跳脫的話標籤提前關閉，
    # 後面整份 app.js 被當成文字印在畫面上，
    # 而錯誤訊息是「invoke is not a function」—— 完全看不出真正原因。
    blob = (out / "fixture.json").read_text(encoding="utf-8").replace("</", "<\\/")
    html = html.replace(
        "</head>",
        '<script type="application/json" id="fx">' + blob + "</script>\n</head>")
    (out / "index.html").write_text(html, encoding="utf-8")


def _fake_betrayal() -> list[dict]:
    """一筆合成的白點，用來看提示卡長什麼樣。

    標成合成的，因為真實資料上白點很少出現 ——
    而一個從沒亮過的提示，跟一個壞掉的提示長得一樣。
    """
    import betrayal as B
    f = B.inspect("我把 `apps/forseti-cli/betrayal.py` 寫好了。", [])
    return [x.to_dict() | {"n": 0} for x in f]


def main(argv: list[str]) -> int:
    port = 8791
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    fake = "--fake" in argv
    # 預設那條線常常只有幾輪，而幾輪的線什麼都看不出來。
    # 要看曲線這種跟歷史長度有關的東西，必須指得到一條真的長線。
    session = ""
    if "--session" in argv:
        session = argv[argv.index("--session") + 1]

    # 這一支借了目錄從來不還。整個檔案以前一個 `rmtree` 都沒有，
    # 所以每跑一次留一個：2026-09-18 實測暫存區 44 個
    # `forseti-ui-*`，42MB，最早的是 09-14。
    #
    # `--keep` 沿用 `ui-render-check.py` 已經在用的那個旗標名，
    # 給的是同一件事：留著讓人進去看。不給就收掉。
    keep = "--keep" in argv

    out = Path(tempfile.mkdtemp(prefix="forseti-ui-"))
    try:
        build(out, fake, session)

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(out), **kw)

            def log_message(self, *a):
                pass

            def end_headers(self):
                # 不准快取。
                #
                # 【2026-09-14 實測】改了 app.js 重啟 harness，index.html 是新的
                # （fixture 內嵌在裡面）但 app.js 被瀏覽器快取成舊版。
                # 新 HTML 有新分頁按鈕，舊 JS 沒有對應的分支，於是點下去
                # 落到 else 分支畫成別的畫面 —— 看起來像新功能寫壞了，
                # 實際上新功能根本沒被載進來。這種假症狀最貴。
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                super().end_headers()

        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", port), H) as srv:
            print()
            print(f"  http://127.0.0.1:{port}/index.html")
            print(f"  檔案在 {out}")
            print("  改了 desktop/ui/ 之後要重跑這支，它是複製不是連結")
            print()
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                print("\n  停了")
    finally:
        if keep:
            print(f"  暫存目錄留著：{out}")
        else:
            shutil.rmtree(out, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
