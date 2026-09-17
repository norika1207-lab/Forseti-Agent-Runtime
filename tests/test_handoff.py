"""交接檔。C4：新 session 不貼任何東西就能接上。

2026-09-16 加這一組的理由：`handoff.py` 先前一條測試都沒有，
而它產出的 `.forseti/NEXT.md` 是**停機之後唯一有人看的東西**。
一個沒有測試的交接檔，在最需要它的那一刻才會發現它壞了。

守兩件：

一，**看不到不等於沒有。** 這份的「下一步」只長得出已經被拆成步驟的
    任務，所以它必須自己講清楚這件事，並指向 ROADMAP。
    不然接手的人會以為沒事做 —— 而那正是 09-16 早上發生的事。

二，**mtime 要保有意義。** 每兩秒被輪詢一次就重寫的檔案，
    「這份是什麼時候寫的」這個問題就沒有答案了。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import handoff as H  # noqa: E402


def test_沒有下一步的時候要講清楚不等於沒事做():
    t = H.render({"goal": "G", "n": 9})
    assert "這不等於沒事做" in t
    assert "ROADMAP.md" in t, "沒有下一步就更要指向排好的順序"
    assert "AUTO_CONTINUE_LOG.md" in t


def test_不塞對話全文():
    """§3.2 的非目標。全文在 jsonl 裡，這份給的是座標。"""
    t = H.render({"goal": "G", "n": 9})
    assert "不複製全文" in t
    assert len(t) < 8000, "交接檔變大就是有人開始往裡面倒全文"


def test_沒有標記就說沒有不拿最近的頂替():
    t = H.render({"goal": "G", "n": 9})
    assert "系統不自己挑" in t
    t2 = H.render({"goal": "G", "n": 9, "last_good": {"id": "cp-1", "n": 3}})
    assert "cp-1" in t2 and "第 3 輪" in t2


def _state(**over):
    """一份形狀完整的交接狀態。

    每個欄位都給空值不是省事 —— `write()` 守的是**鍵在不在**，
    不是值空不空，所以這份正好是「算過了，這一刻沒東西可講」的樣子。
    """
    s = {k: None for k in H.REQUIRED_KEYS}
    s.update({"at": 0, "goal": "G", "n": 1})
    s.update(over)
    return s


def test_寫入有最小間隔(tmp_path):
    p = tmp_path / "NEXT.md"
    assert H.should_write(p) is True, "檔案不存在一定要寫"
    H.write(_state(), path=p, force=True)
    assert H.should_write(p) is False, "剛寫完就再寫，mtime 會失去意義"
    assert H.should_write(p, now=p.stat().st_mtime + H.MIN_GAP_S + 1) is True


def test_force_可以蓋過間隔(tmp_path):
    p = tmp_path / "NEXT.md"
    H.write(_state(), path=p, force=True)
    r = H.write(_state(n=2), path=p, force=True)
    assert r["ok"] is True
    assert "第 2 輪" in p.read_text(encoding="utf-8")


def test_交接檔一定排在checkpoint算完之後():
    """2026-09-16 實際發生的 bug，這一條是它的回歸測試。

    `_write_handoff` 原本排在 advice 那一段，而那時候 snap 裡還沒有
    `checkpoints`，所以交接檔的「最後一個已知良好的點」永遠印「沒有」，
    即使真的有人標過。症狀是兩個來源說法不一致：畫面上的救援那格說
    「你自己標的第 206 輪」，交接檔說沒有。

    **這種 bug 不會報錯**，只會在停機之後讓接手的人以為無處可退 ——
    而那正是這份交接檔存在的理由。

    用原始碼位置檢查而不是跑一次 `strands()`，因為後者要吃真實
    transcript，在沒有那份資料的機器上這條會變成假綠燈。
    """
    src = (ROOT / "apps" / "forseti-cli" / "desktop_api.py").read_text(
        encoding="utf-8")
    cp = src.index('snap["checkpoints"] =')
    call = src.index("_write_handoff(snap)")
    assert call > cp, ("_write_handoff 排在 checkpoints 之前，"
                       "交接檔的 last_good 會永遠是空的")


# ---------------------------------------------------------------------------
# 這份交接自己夠不夠。v5.0 §39.1
# ---------------------------------------------------------------------------
#
# 上面每一節都可能同時是空的，而這份檔案看起來仍然很完整。
# 2026-09-16 被過期狀態檔咬到就是這個形狀：文件沒寫錯，
# 是沒有人在檢查它帶了什麼。

def test_有契約缺口就要印出來而且指得回規格():
    t = H.render({"goal": "G", "n": 9,
                  "contract_lines": ["照 §39.1，31 個欄位裡有 8 個",
                                     "- `stop_condition` 算得出來，沒帶"]})
    assert "這份交接照規格少了什麼" in t
    assert "stop_condition" in t
    assert "§39.1" in t
    assert "apps/forseti-cli/contract.py" in t, "要給得出自己查的方法"


def test_算不出契約的時候整節不出現():
    """算失敗就不寫那一節。

    一個算失敗的空殼看起來像「沒有缺口」，那比不寫更糟。
    """
    t = H.render({"goal": "G", "n": 9, "contract_lines": []})
    assert "這份交接照規格少了什麼" not in t
    t2 = H.render({"goal": "G", "n": 9})
    assert "這份交接照規格少了什麼" not in t2


def test_加了契約那節還是不准把交接撐大():
    """§3.2 的非目標。這一節是摘要，不是把整張表倒進來。"""
    t = H.render({"goal": "G", "n": 9,
                  "contract_lines": [f"- 第 {i} 行" for i in range(40)]})
    assert len(t) < 8000


# ── 2026-09-16 19:0x：做完等收尾，不准印在「卡在哪」底下 ──────
#
# 起因是這份檔案上一句假話：「T-7da5ef2183：7 個步驟都不在可動狀態」，
# 而那 7 個步驟全部是 VERIFIED_COMPLETE。兩種情況要人做的動作相反，
# 一個是去解依賴，一個是按收尾，所以分兩節不合成一節。

def test_等收尾自成一節不混進卡在哪():
    t = H.render({"goal": "G", "n": 1,
                  "awaiting_finish": ["T-1：2 個步驟全部驗證完成了"],
                  "stuck": []})
    assert "## 等你收尾" in t
    assert "## 卡在哪" not in t, "沒有卡住的時候不准出現那個標題"
    assert "不是卡住" in t


def test_等收尾的時候下一步那句不准說還沒拆成步驟():
    t = H.render({"goal": "G", "n": 1,
                  "awaiting_finish": ["T-1：全部驗證完成"]})
    # 猜錯方向的指示比沒有指示糟：會讓人去找一件不存在的事
    assert "還沒拆成步驟" not in t
    assert "該派的都派完了" in t


def test_兩節同時有的時候各自出現():
    t = H.render({"goal": "G", "n": 1,
                  "awaiting_finish": ["T-1：全部驗證完成"],
                  "stuck": ["T-2：依賴等不到"]})
    assert "## 等你收尾" in t and "## 卡在哪" in t
    assert t.index("## 等你收尾") < t.index("## 卡在哪")


def test_都沒有的時候兩節都不出現():
    t = H.render({"goal": "G", "n": 1})
    assert "## 等你收尾" not in t
    assert "## 卡在哪" not in t


# ── 2026-09-16 19:2x：已經被推翻的話要看得到，不只從缺口清單消失 ──
#
# 起因：§40 的 PollutionRegistry 接上之後，`invalidated_conclusions`
# 從 NO_SOURCE 變成有值，契約覆蓋率也跟著好看了。但缺口清單只印缺的，
# 所以接手的人在 NEXT.md 上看不到任何一句被推翻的話 ——
# 而那正是 §39.1 把這一欄放進 Limits 的理由。
#
# 一個覆蓋率變好、用途沒達成的欄位，是這個專案寫在 ROADMAP
# 「不做的事」第一條的那種白工。這一組釘住它不會退回去。

def test_被推翻的那節自成一節():
    t = H.render({"goal": "G", "n": 1,
                  "invalidated_lines": ["- 某句話 → 實際是別的"]})
    assert "## 已經被推翻的" in t
    assert "某句話" in t


def test_被推翻的跟還沒解決的不是同一節():
    """前者要把話收回來，後者要去找答案，兩件事。"""
    t = H.render({"goal": "G", "n": 1,
                  "unknowns": ["某個問題沒答案"],
                  "invalidated_lines": ["- 某句話 → 實際是別的"]})
    assert "## 還沒解決的" in t
    assert "## 已經被推翻的" in t
    assert t.index("## 還沒解決的") != t.index("## 已經被推翻的")


def test_沒有被推翻的就整節不出現():
    """不印「目前沒有被推翻的結論」。

    登記簿只收明確登錄的，空的不代表沒有污染，只代表沒人登錄。
    講出來等於給一個沒有根據的保證。
    """
    t = H.render({"goal": "G", "n": 1, "invalidated_lines": []})
    assert "已經被推翻的" not in t
    t2 = H.render({"goal": "G", "n": 1})
    assert "已經被推翻的" not in t2


# ── 2026-09-16 22:5x：理由過期那一節，三段接線各釘一條 ──
#
# 三段任何一段斷掉都不會報錯，只會少一節東西 —— 而少的那一節正好是
# 「這份交接裡有句話已經不成立了」。一個什麼都不做而且不報錯的接線，
# 是這個專案寫在 ROADMAP「不做的事」第一條的那種白工。

def test_理由過期那一節排得出來():
    import handoff as H
    out = H.render({"at": 0, "goal": "g", "n": 1,
                    "recheck_lines": ["頭一句", "", "- 某一條"]})
    assert "這份交接裡有理由過期了" in out
    assert "頭一句" in out and "- 某一條" in out
    assert "python3 apps/forseti-cli/contract.py" in out, "要給得出自己查的方法"


def test_沒有過期的時候整節不出現():
    """不印「0 條過期」。那種行讀起來像有人在守，而它只代表這一刻沒觸發。"""
    import handoff as H
    out = H.render({"at": 0, "goal": "g", "n": 1})
    assert "這份交接裡有理由過期了" not in out
    assert "理由過期" not in out


def test_desktop_api真的把那幾行傳過來():
    """釘住上游那一段。少了它，上面兩條照樣綠而畫面永遠是空的。"""
    from pathlib import Path
    import desktop_api as D
    src = Path(D.__file__).read_text(encoding="utf-8")
    assert "CT.recheck_lines(" in src, "算的那一行"
    assert '"recheck_lines": rck_lines' in src, "傳給 handoff 的那一行"


# ── `write()` 守自己的輸入 ──────────────────────────────────────────
#
# 2026-09-17 加。2026-09-16 那一輪踩到過：
#
#     handoff.write(desktop_api.strands(''), force=True)
#
# 寫出 1309 位元組的殘缺交接檔（正常九千上下），北極星變「還沒設」，
# blockers、污染登記簿、交接契約整段消失，**而且回 ok: True**。
# 當時是從位元組數用人眼看出來的。
#
# 這一組守的不是「那一行不准再打」，是**打了要有人擋**。
#
# 三條的分工要一起看，少一條就有一種死法沒有人守：
#   一，殘缺的形狀進不去（下面前四條）
#   二，正常那條路仍然寫得出完整的檔（`test_真正的那條路仍然寫得出完整的檔`）
#   三，必要欄位跟上游供應的欄位不准分家（`test_必要欄位每一個上游都真的有供`）
#
# 第二、三條是這一組的重點。只有第一條的話，這道守門的失敗方式會是
# **它把真正的交接也擋掉，然後安靜地什麼都不寫** ——
# 那正是這個模組檔頭寫的那 16 小時空白，換一個原因再發生一次。


def test_把strands的快照餵進來要擋掉(tmp_path):
    """事故那一行的回歸測試。兩種形狀的鍵一個都不重疊。"""
    import desktop_api as D
    p = tmp_path / "NEXT.md"
    r = H.write(D.strands(""), path=p, force=True)
    assert r["ok"] is False, "strands() 的快照不是交接狀態"
    assert p.exists() is False, "擋掉就不准留下任何檔案"
    assert len(r["missing"]) == len(H.REQUIRED_KEYS), \
        "兩種形狀的鍵不重疊，所以 15 個必要欄位應該一個都不在"


def test_擋掉的時候不准動原本那個檔(tmp_path):
    """一份舊的完整交接，比一份新的殘缺交接有用。

    舊的那份 mtime 自己會講「這是舊的」，殘缺那份看起來是最新狀態。
    """
    p = tmp_path / "NEXT.md"
    H.write(_state(goal="原本的北極星"), path=p, force=True)
    before = p.read_text(encoding="utf-8")
    r = H.write({"rows": [], "session": "x"}, path=p, force=True)
    assert r["ok"] is False
    assert p.read_text(encoding="utf-8") == before, "原本那份要一個字都沒變"


def test_force蓋不過形狀檢查(tmp_path):
    """事故那一行帶的正是 force=True。

    `force` 的意思是「蓋過時間間隔」，不是「我確定這是對的」。
    """
    p = tmp_path / "NEXT.md"
    assert H.write({"goal": "G", "n": 1}, path=p, force=True)["ok"] is False
    assert H.write({"goal": "G", "n": 1}, path=p, force=False)["ok"] is False


def test_擋掉的時候要講得出少了哪幾個(tmp_path):
    """只說「形狀不對」，下一個人還是得自己去翻原始碼。"""
    p = tmp_path / "NEXT.md"
    r = H.write(_state(), path=p, force=True)
    assert r["ok"] is True, "完整的要放行"

    s = _state()
    del s["blocker_lines"]
    del s["last_good"]
    r2 = H.write(s, path=p, force=True)
    assert r2["ok"] is False
    assert r2["missing"] == ["blocker_lines", "last_good"]
    assert "blocker_lines" in r2["why"] and "last_good" in r2["why"]
    assert "_write_handoff" in r2["why"], "要指得回唯一的產生者"


def test_值是空的不算缺(tmp_path):
    """**鍵在不在，跟值空不空，是兩件事。**

    `"blocker_lines": []` 是「算過了，這一刻沒有」，
    整個鍵不存在是「根本沒有人算」。守後者，不准守前者 ——
    守成前者的話，一個真的沒有阻塞的乾淨狀態會被擋下來。
    """
    p = tmp_path / "NEXT.md"
    s = {k: [] for k in H.REQUIRED_KEYS}
    s.update({"at": 0, "goal": "", "n": 0, "last_good": None})
    r = H.write(s, path=p, force=True)
    assert r["ok"] is True, "每一欄都空但每一欄都算過，那是合法狀態"


def test_不是dict也要擋掉(tmp_path):
    p = tmp_path / "NEXT.md"
    for bad in (None, [], "state", 7):
        r = H.write(bad, path=p, force=True)
        assert r["ok"] is False, f"{bad!r} 不是交接狀態"
    assert p.exists() is False


def test_必要欄位每一個上游都真的有供():
    """這道守門最危險的失敗方式，是它把真正的交接也擋掉。

    哪天有人往 `REQUIRED_KEYS` 加一欄而沒有往 `_write_handoff()` 加，
    畫面不會壞、測試不會紅，只有 `.forseti/NEXT.md` 從此停止更新 ——
    而那個檔停止更新這件事，要到下一次停機才有人發現。

    所以這一條拿真的那條路跑一次，比對兩邊的欄位。
    """
    import desktop_api as D
    seen = {}

    def _spy(state, **kw):
        seen.update({"keys": set(state.keys())})
        return {"ok": True, "spy": True}

    # `strands()` 自己就會呼叫 `_write_handoff`（`desktop_api.py:3418`），
    # 所以先算 snap 再單獨呼一次的話，第二次會被最小間隔擋掉回 None。
    # 這裡直接走那條真的路。
    orig_write, orig_should = H.write, H.should_write
    try:
        H.write, H.should_write = _spy, (lambda *a, **k: True)
        D.strands("")
    finally:
        H.write, H.should_write = orig_write, orig_should

    assert seen, "_write_handoff 沒有呼叫到 handoff.write"
    lack = sorted(H.REQUIRED_KEYS - seen["keys"])
    assert not lack, f"REQUIRED_KEYS 有 {lack} 上游沒供，真正的交接會被自己擋掉"


def test_真正的那條路仍然寫得出完整的檔(tmp_path, monkeypatch):
    """守門加上去之後，正常那條路不准有任何變化。

    這一條是加守門的前提條件：擋錯的東西之前，先釘住對的東西還過得去。
    """
    import desktop_api as D
    p = tmp_path / "NEXT.md"
    # `OUT` 改到暫存檔，所以跑測試不會去動真的那份交接檔。
    monkeypatch.setattr(H, "OUT", p)

    # 走的是 `strands()` 內部那一次呼叫（`desktop_api.py:3418`），
    # 也就是這個檔平常真的被寫出來的那條路，不是另外拼一條測試路徑。
    D.strands("")
    assert p.exists(), "正常那條路被擋掉了，一個字都沒寫出來"

    t = p.read_text(encoding="utf-8")
    assert "（北極星還沒設）" not in t, "殘缺那份的特徵"
    assert "第 ? 輪" not in t, "殘缺那份的特徵"
    assert "## 北極星" in t
    # 事故那份是 1309 位元組，正常的九千上下。3000 是分得開兩者的地板，
    # 不是對內容的斷言 —— 內容隨真實資料變，這個下界不變。
    n = len(t.encode("utf-8"))
    assert n > 3000, f"只有 {n} 位元組，接近殘缺那份"


def test_snapshot不寫交接檔寫的只有strands():
    """`snapshot()` 一個交接指令都不發，只有 `strands()` 發。

    **2026-09-17 06:5x 加這一條，是為了釘住一次錯掉的歸因。**
    前一輪實測到一個序列：`should_write()` 先問回 False、
    `snapshot()` 正常回傳、顯式呼叫 `_write_handoff()` 回 None，
    而 `.forseti/NEXT.md` 的 mtime 照樣往前動了。
    那一輪據此寫下「`snapshot()` 內部那一條路徑照樣寫成了」，
    並且自己標明沒有去讀程式碼、不當結論。

    **讀了之後那句話是錯的。** `snapshot()`（`desktop_api.py:442`）
    整支十三行，呼叫的是 `_blockers` / `_tasks` / `_continuity` /
    `_reading` / `_ledger_health` / `_gauges` / `_overall` / `_advice`，
    沒有一條路通到 `handoff`。真正的寫入點只有一個：
    `strands()` 尾段的 `_write_handoff(snap)`（`desktop_api.py:3418`）。
    mtime 會動是因為那一輪另外走過 `strands()`，不是因為 `snapshot()`。

    **機制：同一個時間窗裡兩件事都發生了，就把後發生的那件算在
    先呼叫的那一支頭上。** 兩者之間沒有任何證據連起來過 ——
    中間缺的那一步（去讀 `snapshot()` 到底呼叫了誰）跳過去了，
    而跳過去的理由是「它看起來像個會算很多東西的大函式」。

    這一條守的是歸因不是行為：哪天有人把 `_write_handoff` 搬進
    `snapshot()`，節流的語意會整個變（`snapshot()` 的呼叫頻率
    與呼叫脈絡跟 `strands()` 不同），而畫面不會壞、別條測試不會紅。
    """
    import desktop_api as D

    calls: list[tuple[str, object]] = []
    orig_write, orig_should = H.write, H.should_write

    def _spy_write(state, **kw):
        calls.append(("write", kw.get("force", False)))
        return {"ok": False, "why": "SPY 攔截，沒有真的寫", "path": "SPY"}

    def _spy_should(path=None, now=None):
        calls.append(("should_write", None))
        return True

    try:
        H.write, H.should_write = _spy_write, _spy_should
        D.snapshot()
        from_snapshot = list(calls)
        calls.clear()
        D.strands("")
        from_strands = list(calls)
    finally:
        H.write, H.should_write = orig_write, orig_should

    assert from_snapshot == [], (
        f"snapshot() 發了交接指令 {from_snapshot}。"
        "它先前不發，所以節流的語意是照 strands() 的呼叫頻率設計的。"
        "要搬過去得先重新決定 MIN_GAP_S，不是把這條測試調鬆")
    assert ("write", False) in from_strands, (
        f"strands() 沒有走到 handoff.write，攔到的是 {from_strands}。"
        "那表示唯一的寫入點斷了，`.forseti/NEXT.md` 會從此停止更新 ——"
        "而停止更新要到下一次停機才有人發現")
