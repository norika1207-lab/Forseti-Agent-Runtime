#!/usr/bin/env python3
"""指令名在三層之間對不對得上。

畫面按一下，經過的是三層：

    app.js  invoke("work")            ← 第一層，前端
      ↓
    main.rs #[tauri::command] fn work ← 第二層，Rust
            run_api(&["work"])
      ↓
    desktop_api.py  cmd == "work"     ← 第三層，Python

**三層各說各話不會有任何東西變紅。** 2026-09-18 實際發生過：
revert 之前 Rust 還註冊著 `machine` 等六支，而 Python 那邊已經砍掉，
前端也不叫 —— 三層互不知道，編譯過、測試綠、畫面上少一塊。
revert 之後三層又對上了，所以現在不痛，可是下一次砍後端仍然沒有人擋。
那一輪的紀錄在 `AUTO_CONTINUE_LOG.md`，「還缺什麼」第三條。

既有的 `tests/test_ui_contract.py::TauriWiring` 只守一個方向
（JS 呼叫的 ⊆ Rust 註冊的）。這一組守的是它沒守的另外兩段：
Rust 往 Python 那一段，以及 Rust 自己定義與註冊之間那一段。

## 為什麼解析寫成吃字串的純函式

自驗要能注入壞掉的來源，而正本不能改 —— 工作區可能有別條 session
在跑測試（2026-09-18 21:29 那一輪的注入法污染過別人的量測）。
所以每一支解析都吃字串不吃檔案，注入時餵合成來源，一個位元組都不碰正本。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RS_PATH = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"
JS_PATH = ROOT / "desktop" / "ui" / "app.js"
PY_PATH = ROOT / "apps" / "forseti-cli" / "desktop_api.py"


# ---------------------------------------------------------------- 解析

def rust_registered(src: str) -> set:
    """`generate_handler![...]` 裡登記的名字。"""
    m = re.search(r"generate_handler!\[([^\]]*)\]", src, re.S)
    if m is None:
        return set()
    return {x.strip() for x in m.group(1).split(",") if x.strip()}


def rust_command_defs(src: str) -> set:
    """掛了 `#[tauri::command]` 的函式名。"""
    return set(re.findall(
        r"#\[tauri::command\]\s*\n\s*(?:pub\s+)?(?:async\s+)?fn\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)", src))


def rust_subcommands(src: str) -> set:
    """`run_api(&["x", ...])` 送給 Python 的第一個字。

    只抓第一個字面字串 —— 後面那些是參數（session id、輪號），
    不是子指令名。
    """
    return set(re.findall(r'run_api\(&\[\s*"([A-Za-z_][A-Za-z0-9_]*)"', src))


def rust_async_commands(src: str) -> set:
    """掛了 `#[tauri::command]` 且不在 UI thread 執行的 async 函式名。"""
    return set(re.findall(
        r"#\[tauri::command\]\s*\n\s*(?:pub\s+)?async\s+fn\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)", src))


def python_dispatch(src: str) -> set:
    """`desktop_api.main()` 的分派表認得的名字。

    只看 `def main(` 到 `if __name__` 之間 —— 別處出現的
    `cmd == "..."` 不是這張分派表的一員。
    """
    m = re.search(r"\ndef main\(argv.*?\n(.*?)\nif __name__", src, re.S)
    if m is None:
        return set()
    return set(re.findall(r'cmd == "([A-Za-z_][A-Za-z0-9_]*)"', m.group(1)))


def js_invoked(src: str) -> set:
    """`invoke("x")` 字面呼叫的名字。"""
    return set(re.findall(r'invoke\(\s*"([A-Za-z_][A-Za-z0-9_]*)"', src))


# ------------------------------------------------------------ 比對規則

def rust_sends_what_python_cannot_take(rust_src: str, py_src: str) -> list:
    """Rust 送過去、Python 分派不認得的。

    後果是 `{"error": "不認得的指令：x"}` 加 exit 2，
    前端拿到一段錯誤字串，畫面上那一塊是空的。
    """
    return sorted(rust_subcommands(rust_src) - python_dispatch(py_src))


def rust_defined_but_not_registered(rust_src: str) -> list:
    """有 `#[tauri::command]` 卻沒進 `generate_handler!` 的。

    **這個不會編譯失敗**，只是前端永遠叫不到它。
    反向（註冊了沒定義）會編譯失敗，所以那一條在這裡只是順手驗。
    """
    return sorted(rust_command_defs(rust_src) - rust_registered(rust_src))


def rust_registered_but_undefined(rust_src: str) -> list:
    return sorted(rust_registered(rust_src) - rust_command_defs(rust_src))


def orphan_commands(rust_src: str, js_src: str) -> set:
    """Rust 註冊了，而畫面從來不叫的。"""
    return rust_registered(rust_src) - js_invoked(js_src)


# 2026-09-18 21:47 實測的孤兒，四支。
#
# **這張名單不是「這四支該砍」**，是「這四支現在沒人叫這件事是已知的」。
# 為什麼留著沒有查到，owner 未定 —— 所以這裡不替它們編理由，
# 只釘住數量：名單以外多一支就會紅。
#
# 三支（snapshot / timeline / selftest）Python 分派也認得，走 CLI 叫得到；
# repo_path 不走 run_api，它在 Rust 那邊自己算路徑。
KNOWN_ORPHANS = frozenset({"repo_path", "selftest", "snapshot", "timeline"})


class 正本現況(unittest.TestCase):

    RS = RS_PATH.read_text(encoding="utf-8")
    JS = JS_PATH.read_text(encoding="utf-8")
    PY = PY_PATH.read_text(encoding="utf-8")

    def test_三層的來源都讀得到而且不是空的(self):
        """解析回空集合跟「真的沒有」長得一樣，先把這條堵住。"""
        self.assertTrue(rust_registered(self.RS), "main.rs 找不到 generate_handler!")
        self.assertTrue(rust_subcommands(self.RS), "main.rs 找不到 run_api 呼叫")
        self.assertTrue(python_dispatch(self.PY), "desktop_api.py 找不到 main() 分派")
        self.assertTrue(js_invoked(self.JS), "app.js 找不到 invoke 呼叫")

    def test_Rust送出去的子指令Python都認得(self):
        bad = rust_sends_what_python_cannot_take(self.RS, self.PY)
        self.assertEqual(bad, [], f"Rust 送了 Python 分派不認得的指令：{bad}")

    def test_定義了的指令都有註冊(self):
        bad = rust_defined_but_not_registered(self.RS)
        self.assertEqual(bad, [], f"有 #[tauri::command] 卻沒註冊，前端叫不到：{bad}")

    def test_註冊了的指令都有定義(self):
        bad = rust_registered_but_undefined(self.RS)
        self.assertEqual(bad, [], f"generate_handler! 裡有沒定義的名字：{bad}")

    def test_沒人叫的指令就是名單上那幾支(self):
        """多一支沒人叫的會紅，少一支（有人接回去叫了）也會紅。

        後者一樣要紅 —— 名單過期跟名單漏一支是同一種爛掉的方式。
        """
        self.assertEqual(orphan_commands(self.RS, self.JS), set(KNOWN_ORPHANS))

    def test_Python橋接不得阻塞AppKit主執行緒(self):
        """同步等 Python 會讓視窗看似存活、實際完全不能拖動。"""
        python_bridge_commands = {
            "snapshot", "strands", "sessions", "timeline", "audit",
            "spec_reading", "block_reading", "sufficiency", "features",
            "selftest", "machine", "work", "fork", "note_add", "act",
            "north_star_change", "blast_detail",
        }
        self.assertIn(
            "spawn_blocking", self.RS,
            "Python 橋接缺少背景 worker，可能再次凍結原生視窗",
        )
        self.assertEqual(
            python_bridge_commands - rust_async_commands(self.RS),
            set(),
            "呼叫 Python 的 Tauri command 必須是 async",
        )
        for command in python_bridge_commands:
            match = re.search(
                rf"#\[tauri::command\]\s*\n\s*async\s+fn\s+{command}\b"
                rf"(?P<body>.*?)(?=\n#\[tauri::command\]|\nfn main\()",
                self.RS,
                re.S,
            )
            self.assertIsNotNone(match, f"找不到 async command: {command}")
            self.assertIn(
                "run_api_off_main", match.group("body"),
                f"{command} 仍可能在 AppKit 主執行緒等待 Python",
            )

    def test_Python子程序不得繼承GUI_bundle身份或寫外接碟pyc(self):
        bundled = ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
        self.assertIn(bundled, self.RS)
        self.assertLess(self.RS.index(bundled), self.RS.index('"/usr/bin/python3"'))
        self.assertIn('.env_remove("__CFBundleIdentifier")', self.RS)
        self.assertIn('.env("PYTHONDONTWRITEBYTECODE", "1")', self.RS)
        self.assertIsNotNone(re.search(
            r'Command::new\(&py\).*?\.arg\("-B"\)', self.RS, re.S))

    def test_Python程式模組先同步到本機runtime再執行(self):
        self.assertIn("prepare_python_runtime", self.RS)
        self.assertIn('forseti-repo-v2', self.RS)
        self.assertIn('std::fs::copy(&source', self.RS)
        self.assertNotIn('Command::new("/usr/bin/rsync")', self.RS)
        self.assertIn('RUNTIME_SCRIPT: OnceLock', self.RS)

    def test_Session首屏使用App內的本機runtime(self):
        self.assertIn("run_session_surface", self.RS)
        self.assertIn('Resources/forseti-cli/session_surface.py', self.RS)
        match = re.search(
            r'async\s+fn\s+strands\b(?P<body>.*?)(?=\n#\[tauri::command\])',
            self.RS, re.S)
        self.assertIsNotNone(match)
        self.assertIn("run_session_surface(session, tail)", match.group("body"))


# ------------------------------------------------------- 合成來源自驗
#
# 下面全部餵字串，不讀正本，也不改正本。

RS_OK = '''
#[tauri::command]
fn work() -> Result<String, String> {
    run_api(&["work"])
}

#[tauri::command]
fn timeline(session: String) -> Result<String, String> {
    // 第二格刻意放一個字面字串。抓「所有字串」跟抓「第一個」
    // 在只有變數參數的來源上分不出來，那樣自驗就沒有鑑別力。
    run_api(&["timeline", &session, "desc"])
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![work, timeline])
        .run(ctx)
}
'''

PY_OK = '''
def helper():
    # 這一句刻意長得跟分派表一模一樣，而且是合法識別字。
    # 用中文字串的話，regex 本來就抓不到，注入「不限定區間」會是綠的 ——
    # 2026-09-18 這個合成來源第一版就是那樣，注入照樣通過。
    cmd = "work"
    if cmd == "machine":
        pass

def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "snapshot"
    if cmd == "work":
        print(1)
    elif cmd == "timeline":
        print(2)
    else:
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''

JS_OK = 'await invoke("work"); await invoke( "timeline" );'


class 解析器自己對不對(unittest.TestCase):

    def test_抓得到註冊名單(self):
        self.assertEqual(rust_registered(RS_OK), {"work", "timeline"})

    def test_抓得到指令定義(self):
        self.assertEqual(rust_command_defs(RS_OK), {"work", "timeline"})

    def test_只抓run_api的第一個字不抓後面的參數(self):
        """`run_api(&["timeline", &session, "desc"])` 的子指令是 timeline。
        後面兩格是參數，`"desc"` 被抓進來的話，差集會多出一堆假的。"""
        self.assertEqual(rust_subcommands(RS_OK), {"work", "timeline"})
        self.assertNotIn("desc", rust_subcommands(RS_OK))

    def test_分派只看main裡面(self):
        """`helper()` 裡那句 `cmd == "machine"` 不准被算進分派表。

        算進去的後果是反向的：分派表看起來比實際大，
        Rust 送過去會被打回來的指令，這裡會顯示成對得上。
        """
        self.assertEqual(python_dispatch(PY_OK), {"work", "timeline"})
        self.assertNotIn("machine", python_dispatch(PY_OK))

    def test_invoke兩種空白寫法都抓得到(self):
        self.assertEqual(js_invoked(JS_OK), {"work", "timeline"})


class 注入壞掉的來源要紅(unittest.TestCase):
    """每一條先確認乾淨版是綠的，再確認壞掉版是紅的。

    只驗壞掉版會紅不夠 —— 一個永遠回傳「有問題」的檢查也會通過那一半。
    """

    def test_Python少一支要被抓到(self):
        self.assertEqual(rust_sends_what_python_cannot_take(RS_OK, PY_OK), [])
        壞掉 = PY_OK.replace('elif cmd == "timeline":\n        print(2)\n', "")
        self.assertEqual(
            rust_sends_what_python_cannot_take(RS_OK, 壞掉), ["timeline"])

    def test_定義了沒註冊要被抓到(self):
        self.assertEqual(rust_defined_but_not_registered(RS_OK), [])
        壞掉 = RS_OK.replace("generate_handler![work, timeline]",
                             "generate_handler![work]")
        self.assertEqual(rust_defined_but_not_registered(壞掉), ["timeline"])

    def test_註冊了沒定義要被抓到(self):
        self.assertEqual(rust_registered_but_undefined(RS_OK), [])
        壞掉 = RS_OK.replace("generate_handler![work, timeline]",
                             "generate_handler![work, timeline, machine]")
        self.assertEqual(rust_registered_but_undefined(壞掉), ["machine"])

    def test_多一支沒人叫的要被抓到(self):
        self.assertEqual(orphan_commands(RS_OK, JS_OK), set())
        壞掉 = RS_OK.replace("generate_handler![work, timeline]",
                             "generate_handler![work, timeline, machine]")
        self.assertEqual(orphan_commands(壞掉, JS_OK), {"machine"})

    def test_前端不叫了也要被抓到(self):
        """砍掉前端那一句，指令就變孤兒 —— 這是砍功能砍到一半的樣子。"""
        self.assertEqual(orphan_commands(RS_OK, JS_OK), set())
        self.assertEqual(
            orphan_commands(RS_OK, 'await invoke("work");'), {"timeline"})

    def test_來源整個讀不到的時候不准安靜地通過(self):
        """解析回空集合，差集也會是空的 —— 每一條檢查都會變成綠的。

        `正本現況.test_三層的來源都讀得到而且不是空的` 就是為了擋這個，
        這裡驗的是那個狀態真的存在，不是假想的。
        """
        self.assertEqual(rust_registered("完全不是 rust 的東西"), set())
        self.assertEqual(python_dispatch("完全不是那支檔案"), set())
        self.assertEqual(
            rust_sends_what_python_cannot_take("空的", "空的"), [],
            "兩邊都讀不到的時候差集是空的，所以空集合守門不能省")


if __name__ == "__main__":
    unittest.main()
