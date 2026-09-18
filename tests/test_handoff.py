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


# ---------------------------------------------------------------------------
# 「這一份是在哪裡寫的」那一節。v5.0 §39.1 Identity + Reality
# ---------------------------------------------------------------------------
#
# 2026-09-17 21:xx 加。在這之前這份檔案只印缺口 ——
# **填得出來的欄位一個字都不印**。所以同一天稍早把 `runtime_node`
# 從「沒有資料來源」接成有值之後，這份交接照樣答不出
# 「現在是在哪台機器上寫的」，而它自己的「已經發生過的決定」
# 第一條就是「換機器」。

def test_座標那節印得出來():
    t = H.render({"goal": "G", "n": 9,
                  "coordinate_lines": ["- 現在跑在哪台機器（`runtime_node`）：node-abc"]})
    assert "這一份是在哪裡寫的" in t
    assert "node-abc" in t


def test_算不出座標的時候整節不出現():
    """跟契約那一節同一條理由：空殼看起來像「已經答出來了」。"""
    assert "這一份是在哪裡寫的" not in H.render(
        {"goal": "G", "n": 9, "coordinate_lines": []})
    assert "這一份是在哪裡寫的" not in H.render({"goal": "G", "n": 9})


def test_座標排在其他每一節之前():
    """座標決定底下每一條路徑該不該被相信，所以不能排在後面。

    讀的人先看到一串路徑、最後才知道那是另一台機器上的路徑，
    跟先知道機器再看路徑，是兩種不一樣的閱讀。
    """
    t = H.render({"goal": "G", "n": 9,
                  "coordinate_lines": ["- 在這裡"],
                  "artifact_lines": ["產出那一節"],
                  "contract_lines": ["缺口那一節"]})
    assert t.index("## 北極星") < t.index("## 這一份是在哪裡寫的")
    assert t.index("## 這一份是在哪裡寫的") < t.index("## 下一步")
    # 下面這個 "## 產出在哪裡" **故意是硬寫的,不准改成 contract.ARTIFACT_HEADING**。
    #
    # 2026-09-18 起排版側改用那份常數,於是 `test_artifact_drift.py` 整組
    # 都從同一個值推出來 —— 一旦這裡也收進去,改那個常數對整套測試就完全
    # 隱形了。實測過:只改 contract 那一份常數,全樹只有這一行會紅。
    # 這一行是唯一的獨立對照組,收掉它就沒有人看得見改名。
    assert t.index("## 這一份是在哪裡寫的") < t.index("## 產出在哪裡")


def test_加了座標那節還是不准把交接撐大():
    """§3.2 的非目標。這一節是座標，不是把整張表倒進來。"""
    t = H.render({"goal": "G", "n": 9,
                  "coordinate_lines": [f"- 第 {i} 行" for i in range(40)]})
    assert len(t) < 8000


def test_desktop_api真的把座標那幾行傳過來():
    """釘住上游那一段。少了它，上面幾條照樣綠而正文永遠是空的。"""
    from pathlib import Path
    import desktop_api as D
    src = Path(D.__file__).read_text(encoding="utf-8")
    assert "CT.coordinate_lines(" in src, "算的那一行"
    assert '"coordinate_lines": crd_lines' in src, "傳給 handoff 的那一行"


def test_座標傳的是整份report不是ctx():
    """傳 ctx 的話這一節會什麼都印不出來，而且不會報錯。

    它要的是每一欄的狀態（只印 PRESENT），狀態在 `check()` 那一半算，
    ctx 裡沒有。一個什麼都不做又不報錯的接線，是這個專案
    寫在 ROADMAP「不做的事」第一條的那種白工。
    """
    from pathlib import Path
    import desktop_api as D
    src = Path(D.__file__).read_text(encoding="utf-8")
    assert "CT.coordinate_lines(_rep)" in src, "傳的必須是整份 report"
    import contract as CT
    assert CT.coordinate_lines(CT.report({}, None).get("ctx")) == [], \
        "傳 ctx 的話回空清單 —— 這正是那條接線壞掉時的樣子"


def test_座標是必要欄位不是可有可無():
    """從 `REQUIRED_KEYS` 拿掉的話，這一節會安靜地消失。

    `write()` 守的是鍵在不在。這個鍵不在必要清單裡的時候，
    上游哪天不再供它，`NEXT.md` 照樣寫得出來、照樣沒有人會紅 ——
    只是從此答不出它是在哪台機器上寫的，跟 2026-09-17 之前一樣。
    """
    assert "coordinate_lines" in H.REQUIRED_KEYS


# ---- 2026-09-18 05:2x：那一種殘缺，既有的守備認不出來 ----

def _殘缺state():
    """重現 2026-09-18 05:2x 那一份。

    那一次拿 `desktop_api.snapshot()` 的回傳餵 `_write_handoff()`,
    而那一支要的四個 snap 鍵只有 `blockers` 在。後果是
    `unknowns` / `verified` / `last_good` 全部落到空值,
    而 `goal` 與 `n` 照樣有值（它們的上游是 `north_star()` 與
    `work()`,不是 snap）。

    **這個組合才是重點**:有北極星、有輪號,所以它讀起來是正常的。
    """
    return {"goal": "讓 AI 的工作狀態變成可觀測、可驗證、可控制、可復原。",
            "n": 14, "unknowns": [], "verified": [], "last_good": None,
            "next_actions": [], "awaiting_finish": ["T-x：等收尾"], "stuck": [],
            "decisions": [], "blocker_lines": [], "invalidated_lines": [],
            "artifact_lines": [], "contract_lines": [], "recheck_lines": [],
            "coordinate_lines": [], "at": 0}


def test_那兩個殘缺特徵認不出2026_09_18那一種():
    """`test_真正的那條路仍然寫得出完整的檔` 拿兩個字串當殘缺的特徵:
    `（北極星還沒設）` 與 `第 ? 輪`。**這一條釘住那個判準的盲區。**

    2026-09-18 05:2x 那一份殘缺版,兩個特徵**一個都沒有** ——
    北極星在、輪號是 14。所以那一條測試會全綠地放它過去,
    而它實際掉了「還沒解決的」（`scope_match` 那個未解）與
    「已驗證的狀態」（必讀 20/30）兩整節。

    真實數字:殘缺版 13345 bytes,正確的那一份 15039。
    **沒有任何一個字是錯的**,所以讀的人分不出來 ——
    它只是少講了幾件事。

    這一條不是要去改那一條測試的判準（那要決定「哪幾節缺了算殘缺」,
    而那個清單一寫下來就會跟著 `render()` 腐爛）。它要守的是
    **別再有人以為那兩個特徵蓋得住所有殘缺**。
    """
    t = H.render(_殘缺state())
    assert "（北極星還沒設）" not in t, "這一種殘缺的北極星是在的,不然重現得不對"
    assert "第 ? 輪" not in t, "這一種殘缺的輪號是在的,不然重現得不對"


def test_上游缺的時候那兩節整個不見而不是講缺什麼():
    """殘缺版的形狀,量出來釘住。

    `render()` 對空的 `unknowns` / `verified` 是**整節不印**,
    不是印一句「這一節的上游沒供」。兩者的差別是接手的人
    看不看得出少了東西 —— 而這一支的 docstring 自己寫著
    「不自己判斷任何事」,所以「缺了要講」這件事不該在它裡面加。

    哪天有人讓它改成講缺什麼（那是好事），這一條會先紅，
    提醒回頭看上面那一條的事故敘述還對不對。
    """
    完整 = dict(_殘缺state(),
                unknowns=["GAC 算不出來，缺 scope_match：規格沒有定義"],
                verified=["必讀文件 20/30 讀完"])
    缺 = H.render(_殘缺state())
    有 = H.render(完整)

    assert "scope_match" in 有 and "必讀文件" in 有, "重現得不對,完整那份就該有這兩句"
    assert "scope_match" not in 缺 and "必讀文件" not in 缺
    # 整節不見,不是留一句說明。
    assert "還沒解決的" not in 缺, (
        "那一節的標題還在 —— 那就不是「整節不見」,上面那條敘述要改")
    assert "已驗證的狀態" not in 缺
    assert len(缺) < len(有), "缺的那一份沒有變短,重現得不對"


# ── 「那一支從 snap 取哪些鍵」這個問題，答案只有一份（2026-09-18）──
#
# 2026-09-18 之前這個掃描是正則吃原始碼字串，而那種吃法**連註解都算**。
# `desktop_api.py:1924` 那一行註解寫的是：
#
#     # **自己叫 `_blockers()`，不從 snap 拿。** `snap["blockers"]` 只存在於
#     # `snapshot()`，而這一支收到的是 `strands()` 的 snap，那裡面沒有這個 key。
#
# 一句話的內容是「這個鍵不從 snap 來」，被掃成「這個鍵從 snap 來」。
#
# 那個誤判有後果，不是潔癖。上一輪拿這個掃法得到的四個鍵去當
# `_write_handoff()` 的入口守門，於是**正常那條路被自己的門擋掉**
# （`strands()` 的 snap 從來就沒有 `blockers`），三條既有測試變紅，
# 而當時把紅的原因記成「測試環境下的 snap 跟真實環境不一樣」。
# 那句話這一輪量了，是錯的（見最後一條測試）。


def _snap_keys_in(src: str, func: str) -> set[str]:
    """一段原始碼裡，`func` 那一支**真的從 snap 取了哪些鍵**。

    走 AST 不走正則：註解與字串裡長得像 `snap["x"]` 的東西不算。
    吃字串不吃檔案路徑，所以合成的原始碼餵得進來 ——
    「註解不算」這件事要驗得到，就不能只有真檔一個入口。
    """
    import ast

    i = src.index(f"def {func}")
    j = src.index("\ndef ", i + 1)
    tree = ast.parse(src[i:j])
    out: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "snap"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            out.add(node.slice.value)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "snap"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            out.add(node.args[0].value)
    return out


def _calls_in(src: str, func: str) -> set[str]:
    """一段原始碼裡，`func` 那一支**真的呼叫了哪些名字**。

    走 AST 不走子字串，理由跟 `_snap_keys_in()` 完全一樣，
    而且是同一行註解害的：`desktop_api.py:1924` 那句「自己叫
    `_blockers()`，不從 snap 拿」裡面有 `_blockers()` 這七個字，
    所以 `"_blockers()" in src[i:j]` 在真正的呼叫被拿掉之後**照樣是 True**。
    2026-09-18 實測過：把那一行的呼叫改名，那條測試仍然 1 passed。

    取 `ast.Name` 也取 `ast.Attribute`（`X.y()` 收 `y`），
    因為呼叫端寫成 `mod.f()` 的時候問的仍然是「有沒有呼叫 f」。
    """
    import ast

    i = src.index(f"def {func}")
    j = src.index("\ndef ", i + 1)
    out: set[str] = set()
    for node in ast.walk(ast.parse(src[i:j])):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name):
            out.add(f.id)
        elif isinstance(f, ast.Attribute):
            out.add(f.attr)
    return out


def _desktop_api_src() -> str:
    return (ROOT / "apps" / "forseti-cli" / "desktop_api.py").read_text(
        encoding="utf-8")


def test_註解裡長得像取鍵的東西不算取鍵():
    """掃描器本身的偵測器。**餵合成原始碼，不依賴真檔此刻的註解長相。**

    真檔那一行註解哪天被改寫，這一條不該跟著紅 ——
    它守的是掃描器的判準，不是某一行註解還在不在。
    """
    fake = (
        'def _f(snap):\n'
        '    # 自己叫 _blockers()，不從 snap 拿。snap["blockers"] 只在別處\n'
        '    """snap.get("docstring_only") 也不算。"""\n'
        '    note = \'snap["string_only"]\'\n'
        '    return snap["real"], snap.get("also_real"), note\n'
        '\ndef _g():\n    pass\n'
    )
    got = _snap_keys_in(fake, "_f")
    assert got == {"real", "also_real"}, (
        f"掃出來的是 {sorted(got)}。註解、docstring、字串字面值裡的"
        "`snap[...]` 都不是取鍵 —— 正則吃得下它們，這也正是"
        "2026-09-18 那道守門把正常那條路擋掉的原因")


def test_註解裡長得像呼叫的東西不算呼叫():
    """`_calls_in()` 自己的偵測器。**餵合成原始碼，不依賴真檔的註解長相。**

    跟上面那條是同一個形狀的第二種：上面守「取鍵」，這條守「有沒有呼叫」。
    兩條分開是因為 2026-09-18 修掉取鍵那一半之後，**同一輪寫下的
    另一半仍然是子字串比對**，被同一行註解騙到。
    一個機制修一半，剩下那一半不會自己好。
    """
    fake = (
        'def _f(snap):\n'
        '    # 自己叫 _blockers()，不從 snap 拿。\n'
        '    """docstring 裡的 _docstring_only() 也不算。"""\n'
        '    note = "_string_only()"\n'
        '    return _real(), mod._also_real(), note\n'
        '\ndef _g():\n    pass\n'
    )
    got = _calls_in(fake, "_f")
    assert "_blockers" not in got, (
        f"掃出來的是 {sorted(got)}。註解裡的 `_blockers()` 被算成呼叫了 —— "
        "那正是子字串比對犯的錯")
    assert "_docstring_only" not in got and "_string_only" not in got
    assert {"_real", "_also_real"} <= got, (
        f"真正的呼叫沒掃到：{sorted(got)}")


def test_那一支不從snap拿blockers而是自己算():
    """真檔這一側的語義斷言，跟上面那條合成的分工。

    這一條不看註解寫什麼，看的是兩件事同時成立：
    `_write_handoff()` 沒有從 snap 取 `blockers`，而它自己呼叫了
    `_blockers()`。哪天有人改成從 snap 拿，這一條先紅 ——
    而那個改動會讓 `.forseti/BLOCKERS.md` 那一節從此永遠是空的，
    **不會報錯**（`strands()` 的 snap 沒有這個 key）。

    2026-09-18：第二個斷言原本寫成 `"_blockers()" in src[i:j]`，
    而 `desktop_api.py:1924` 那一行註解裡就有這七個字。實測把真正的
    呼叫改名，這一條照樣 1 passed —— 它守的東西整個是空的。
    改成 `_calls_in()` 走 AST。
    """
    src = _desktop_api_src()
    要的 = _snap_keys_in(src, "_write_handoff")
    assert "blockers" not in 要的, (
        "`_write_handoff()` 開始從 snap 取 blockers 了。"
        "`strands()` 的 snap 沒有這個 key，所以那一節會永遠是空的而且不報錯")
    呼叫的 = _calls_in(src, "_write_handoff")
    assert "_blockers" in 呼叫的, (
        "那一支不再自己呼叫 `_blockers()` 了。"
        "上面那個斷言於是失去意義 —— 兩邊都沒有的話，那一節是空的")


def test_snapshot給不齊那一支要的snap鍵():
    """上面兩條的前提:**為什麼會餵錯**。

    `_write_handoff()` 從 snap 取的鍵,`snapshot()` 給不齊 ——
    所以「拿 `snapshot()` 餵它」這條路一定產出殘缺版。
    正確的來源是 `strands()` 的 snap。

    哪天 `snapshot()` 補齊了（那是好事），這一條會先紅，
    提醒回頭看上面兩條的事故敘述還成不成立。

    抓法:`_write_handoff()` 的 AST 掃 `snap[...]` 與 `snap.get(...)`,
    對 `snapshot()` 實際回傳的鍵。讀回傳不讀原始碼,
    因為那些鍵是 `_safe()` 包著動態塞進去的。

    **2026-09-18 從正則改成 AST。** 正則版掃出來多一個 `blockers`,
    那個字來自一行寫著「不從 snap 拿」的註解。這一條當時照樣綠 ——
    因為 `snapshot()` 剛好有 `blockers`,多出來的那個被減掉了。
    綠的測試蓋著一個錯的中間值,而拿那個中間值去做別的事的人
    （上一輪）就被咬了。
    """
    import desktop_api as D

    要的 = _snap_keys_in(_desktop_api_src(), "_write_handoff")
    assert 要的, "掃不到那一支從 snap 取哪些鍵,掃描器過期了"

    給的 = set(D.snapshot().keys())
    缺 = sorted(要的 - 給的)
    assert 缺, (
        f"`snapshot()` 現在給得齊 {sorted(要的)} 了 —— 那是好事,"
        "可是上面兩條測試的事故敘述要回頭改:"
        "「拿 snapshot() 餵會寫出殘缺版」不再成立")
    assert "rows" in 缺, f"缺的那幾個換人了,回頭看事故敘述:{缺!r}"


def test_測試環境下那三個鍵跟真實環境一樣齊(tmp_path, monkeypatch):
    """**推翻上一輪寫下的那句話。** §40 那一筆的回歸偵測器。

    上一輪的紀錄寫著：「三條既有測試走 `D.strands("")`，而那條路徑產的
    snap 給不齊 `rows` / `goal_gate` / `checkpoints`，真實環境下三個都齊
    （14 / 11 / 6）」。2026-09-18 在真的 pytest 底下攔 `_write_handoff()`
    量過，三個都在，數量跟真實環境一樣。

    真正沒有的是 `blockers`，而那一個本來就不從 snap 來（上面那條）。

    這一條釘住的是**「測試環境的 snap 形狀有缺」這個說法不准再被寫下來**。
    數量會隨真實資料變，所以只斷言鍵在不在、以及是不是非空，不斷言數字。
    """
    import desktop_api as D

    monkeypatch.setattr(H, "OUT", tmp_path / "NEXT.md")
    snap = D.strands("")
    assert not snap.get("error"), f"這一輪連 transcript 都沒挑到：{snap!r}"

    for k in ("rows", "goal_gate", "checkpoints"):
        assert k in snap, (
            f"`strands(\"\")` 的 snap 少了 {k}。"
            "上一輪那句「測試環境下給不齊」這一次成立了 —— "
            "回頭看 §40 的登記，那一筆要從 RESOLVED 退回去")
        assert snap[k], f"{k} 在，可是是空的。上面那句話要改成「在但空的」"
    assert "blockers" not in snap, (
        "`strands()` 開始供 blockers 了。那是好事，"
        "可是 `_write_handoff()` 自己算那一份的理由要回頭看")
