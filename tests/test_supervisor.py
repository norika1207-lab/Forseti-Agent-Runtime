"""開發監督的停滯判斷。

**這組測試是為了一個實際發生過的失效寫的。**

2026-09-16：supervisor 原本用「~/.claude/projects 底下最新的 transcript
有多久沒動」判停滯。兩個問題同時存在：

一，owner 同時開十幾個 session。實測五個 session 全部在 0.4 分鐘內有活動，
    所以那個指標在她身上永遠是 0，永遠判不出停滯。

二，**排程任務自己也是一個 session。** 它一跑起來，自己的 transcript
    就成了最新的，於是它看到 idle=0，判定沒停，然後結束什麼都不做。
    它在偵測自己。實測跑了三次，每次活 20 到 45 秒就退出。

結果是：一支寫來「不讓 owner 當工人」的腳本，跑了三次，一次都沒接手，
而她又等了 13 分鐘然後自己開口。

指標改成「Forseti 的程式碼有多久沒被改」。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import supervisor as S  # noqa: E402


def test_看的是程式碼不是對話紀錄():
    """這條紅了就代表有人把指標改回 transcript。"""
    fs = S.watched()
    assert fs, "應該看得到原始碼"
    assert all(f.suffix in S.WATCH_EXT for f in fs)
    assert not any(".jsonl" in f.name for f in fs)
    assert not any("/.claude/projects/" in str(f) for f in fs)


def test_forseti目錄要被排除():
    """`.forseti/` 裡的帳本會自動更新，包括這支自己寫的 log。

    把它算進去就是第二次自我否定：跑一次寫一次 log，
    寫完 idle 歸零，於是永遠判不出停滯。
    """
    assert ".forseti" not in S.WATCH_DIRS
    assert not any("/.forseti/" in str(f) for f in S.watched())


def test_看的目錄涵蓋實際會動的地方():
    for d in ("apps", "tests", "tools", "desktop/ui"):
        assert d in S.WATCH_DIRS, f"{d} 沒被監看，改那裡的東西不算在做事"


def test_四道閘每一道都說得出是哪一道():
    d = S.decide()
    assert "wake" in d and "why" in d
    if not d["wake"]:
        assert d["gate"], "被擋住一定要說出是哪一道閘"


def test_停止開關存在就完全不跑(tmp_path, monkeypatch):
    off = tmp_path / "SUPERVISOR_OFF"
    off.write_text("stop", encoding="utf-8")
    monkeypatch.setattr(S, "OFF", off)
    d = S.decide()
    assert d["wake"] is False
    assert d["gate"] == "OFF"


def test_冷卻要比門檻長():
    """冷卻比門檻短的話，上一次被喚醒的還在跑就會被再叫一次。"""
    assert S.COOLDOWN_MIN > S.IDLE_MIN


def test_喚醒不帶resume():
    """接續「最新的 transcript」會接到別條線。接錯線比開新線更糟。"""
    cmd = S.wake(dry=True)["cmd"]
    assert "--resume" not in cmd


def test_喚醒有輪數上限():
    """沒有上限的話一次喚醒可能跑很久。"""
    cmd = S.wake(dry=True)["cmd"]
    assert "--max-turns" in cmd


def test_沒事做就不喚醒(tmp_path, monkeypatch):
    """沒事還把人叫起來就是製造噪音，而 v5.0 §18：
    噪音多的守護者自己會變成另一個故障源。"""
    empty = tmp_path / "NEXT.md"
    empty.write_text("# 接下來要做什麼\n\n沒有算得出來的下一步。\n", encoding="utf-8")
    monkeypatch.setattr(S, "NEXT", empty)
    ok, why = S.has_work()
    assert ok is False


def test_有卡住的就算有事做(tmp_path, monkeypatch):
    f = tmp_path / "NEXT.md"
    f.write_text("# 接下來\n\n## 卡在哪\n\n- T-123 卡住了\n", encoding="utf-8")
    monkeypatch.setattr(S, "NEXT", f)
    ok, _ = S.has_work()
    assert ok is True


# ---------------------------------------------------------------------------
# 起得來不等於做得了事。2026-09-17 加的。
#
# 事故:`claude` CLI 的 OAuth 過期，`claude -p` 起得來但 2.7 秒後
# 以 rc=1 退出。`wake()` 先前只檢查 `Popen` 有沒有丟 `OSError`，
# 而 `OSError` 只在「執行檔不存在、權限不足」這類情況出現。
# 於是每一次認證失敗都被記成「自動喚醒」成功，帳本上看起來正常。
# stdout 跟 stderr 又都丟 `DEVNULL`，所以錯誤訊息一個字都留不下來。
#
# owner 要的是「停著就有人接手」。一個回報成功而什麼都沒做的喚醒，
# 比沒有喚醒更糟 —— 沒有喚醒至少看得出來沒人接。
# ---------------------------------------------------------------------------

class _FakeProc:
    """假的子行程。`code` 是 None 代表還在跑。"""

    def __init__(self, code):
        self.pid = 4242
        self._code = code

    def poll(self):
        return self._code


def _patch_wake(monkeypatch, S, code, tmp_path):
    """把 Popen、sleep、帳本都換掉，不真的叫 claude 也不寫正本。"""
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        seen["stderr"] = kw.get("stderr")
        seen["stdout"] = kw.get("stdout")
        return _FakeProc(code)

    monkeypatch.setattr(S.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(S.time, "sleep", lambda *_: None)
    monkeypatch.setattr(S, "WAKE_LOG", tmp_path / "wake.log")
    rows = []
    monkeypatch.setattr(S, "record",
                        lambda did, why, extra=None: rows.append(
                            (did, why, extra or {})))
    return seen, rows


def test_起來就以非零退出要當成失敗(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup_fail", ROOT / "tools" / "supervisor.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    seen, rows = _patch_wake(monkeypatch, S, code=1, tmp_path=tmp_path)

    out = S.wake()
    assert out["ok"] is False, "起來就死了卻回報成功"
    assert out.get("rc") == 1
    assert any(did == "error" for did, _, _ in rows), \
        "失敗沒有進帳本，那就沒有人查得到它失敗過"
    assert not any(did == "wake" for did, _, _ in rows), \
        "失敗的那一次被記成喚醒成功"


def test_還在跑的就算成功(tmp_path, monkeypatch):
    """`poll()` 回 None 代表還活著，那是正常的喚醒。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup_ok", ROOT / "tools" / "supervisor.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    seen, rows = _patch_wake(monkeypatch, S, code=None, tmp_path=tmp_path)

    out = S.wake()
    assert out["ok"] is True
    assert any(did == "wake" for did, _, _ in rows)


def test_stderr不准丟進devnull(tmp_path, monkeypatch):
    """錯誤訊息被丟掉的話，失敗查不出原因。

    這一條釘的是「留得下證據」，不是「有沒有失敗」。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup_err", ROOT / "tools" / "supervisor.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    seen, _ = _patch_wake(monkeypatch, S, code=None, tmp_path=tmp_path)

    S.wake()
    import subprocess as sp
    assert seen["stderr"] is not sp.DEVNULL, \
        "stderr 又被丟回 DEVNULL 了"
    assert hasattr(seen["stderr"], "write"), "stderr 不是一個寫得進去的東西"


def test_讀不到log要說讀不到而不是回空字串(tmp_path, monkeypatch):
    """「沒有錯誤」跟「讀不到錯誤」在紀錄裡不能長一樣。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup_tail", ROOT / "tools" / "supervisor.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    monkeypatch.setattr(S, "WAKE_LOG", tmp_path / "不存在的目錄" / "x.log")
    out = S.wake_log_tail()
    assert out and "讀不到" in out, f"讀不到卻回了 {out!r}"
