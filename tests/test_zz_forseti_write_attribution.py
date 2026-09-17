"""跑測試的時候動到正本 `.forseti/` 的，只准是在冊的那幾條。

**2026-09-17 加這一組，補的是上一輪（5ai）自己寫下的那個缺口。**
上一輪量到 `.forseti/NEXT.md` 的 mtime 在只有 pytest 在跑的那段時間
從 09:33:20 跳到 09:49:50，但是**哪一條測試寫的沒有量**。
而「測試不碰正本」是 `tests/test_forseti_dir_writes.py` 與
`tests/test_module_write_targets.py` 兩組共同的前提 ——
前提沒人守跟沒有前提一樣。

量的機制在 `tests/conftest.py`，這一組只負責把量到的東西跟名單比。

## 量出來的結果，以及它在同一輪裡就被推翻了一次

第一次全套（1507 條）量到 28 條測試動到正本，5 個相異路徑，
於是寫下「`NEXT.md` 的寫入者是 `test_forseti_dir_writes.py` 那一條」。

**第二次全套（1515 條）推翻了它。** 同樣的程式碼、同樣的測試集，
答案換了人：寫 `NEXT.md` 的變成
`test_claims_wiring.py::TestRealSnapshot::test_no_duplicates_within_a_row`，
而且多出一個第一次沒有的 `test_blast.py`。

**錯的不是數字，是「一次觀測就寫成歸屬」這件事。**
兩條路徑各有各的漂移機制，都是讀原始碼確認的：

`NEXT.md` ── `handoff.should_write:78` 讀的是**正本檔自己的 mtime**，
`MIN_GAP_S = 240`。所以寫得成的是「那一輪裡第一個走到 `strands()`
而且剛好在窗外的那一條」。誰是第一個由執行順序決定，
而 `c` 開頭的 `test_claims_wiring` 排在 `f` 開頭的
`test_forseti_dir_writes` 前面（它在 `:117` 呼叫 `desktop_api.strands("")`）。
2026-09-17 10:0x 對照實測，同一條測試跑兩次：

    距上次寫 241.3 秒（窗外）  →  動到 NEXT.md
    距上次寫   9.1 秒（窗內）  →  沒動到 NEXT.md

第一次全套整場都在窗內（三分鐘前剛有人跑過），所以那一次誰都沒寫成。

`cache/blast.json` ── `blast._cache_get:388` 比對的指紋
（`_fingerprint:365`）涵蓋 `SCAN_DIRS = ("apps/forseti-cli", "tools", "tests")`
底下每個 .py 的 mtime 與大小。**`tests/` 在裡面**，所以改任何一個測試檔
都會讓快取失效，下一個算 blast 的測試就得重寫。
第二次全套是在反覆增刪測試檔之後跑的，第一次不是。
（第二次裡有三個不同的檔各寫過一次 blast.json，
**這三次的成因沒有量** —— 只知道失效條件是指紋變動。）

## 名單的來源本身有缺陷，2026-09-17 補上（掃原始碼那一半）

上面那張名單是**觀測**出來的：跑一輪，看誰動到正本。
而誰寫得成 `NEXT.md` 由節流窗加執行順序決定，所以觀測看得見的
永遠只是「那一輪碰巧贏了競速的那一條」——
**一個從頭到尾都碰得到正本、但還沒輪到它的檔，在觀測裡是隱形的。**

`tests/test_sot.py` 就是這樣藏著。它 `:357` 呼叫 `strands()`，
而 `strands()` 尾段無條件走 `_write_handoff`（`desktop_api.py:3418`），
目標是 `handoff.OUT` 也就是正本 `NEXT.md`。2026-09-17 攔截實測
（不真的寫，只量路徑）：`should_write` 1 次、`write` 1 次、
目標 `<default>` = `/…/Forseti/.forseti/NEXT.md`。
同一輪全套裡它一次動到、最後一次沒動到，所以上一輪**沒有登記** ——
理由寫的是「登記一個時有時無的寫入者等於把不確定寫成確定」。

那句話對的是身份層，錯的是它讓這個檔整個逃掉了。
分開來看就沒有矛盾：

    「它那一次寫了沒有」          時有時無，不該寫成確定
    「它碰不碰得到正本」          確定的，掃原始碼就看得到

所以這一輪加的是第二題的守門（`STRANDS_CALLERS` 與
`test_呼叫strands的檔掃得出來而且一個都不漏`），
登記的意思也跟著改成「這個檔碰得到正本」，不是「它寫過」。

## 所以名單守的是形狀不是身份

這一組**不斷言哪一條測試寫了什麼**。身份會漂，量兩次就看得到。
守得住的是三件會漂的東西底下不會漂的部分：路徑的範圍、
寫入者所在檔案的集合、以及 `NEXT.md` 一輪最多被寫一次。

被動到過的 5 個相異路徑（兩次聯集），全部在 `cache/` 底下加上 `NEXT.md`：

    cache/artifact_hashes.json   test_contract.py / test_handoff.py
    cache/identity.json          test_identity.py / test_claims_wiring.py
    cache/blast.json             test_ui_render.py / test_blast.py /
                                 test_forseti_dir_writes.py
    cache/._identity.json        跟著上面一起動的 AppleDouble 檔
    cache/._blast.json           （NewDrive 是 exFAT，macOS 在這種碟上
                                  另外存一份中繼資料，不是哪支程式寫的）

## 這個量法的代價，以及兩個前提

**代價：全套慢 31.9 秒（+17.2%）。** 2026-09-17 同一台機器實測，
搬走 `tests/conftest.py` 跑 1507 條是 185.56 秒，
放回去加上這八條是 1515 條 217.49 秒。來源是每條測試前後各掃一次
`.forseti/`（155 個檔），約 47 萬次 `stat`，平均每條多 21 毫秒。

掃一次就好（拿上一條的結果當下一條的起點）可以砍掉一半，
**沒有這樣做**：那樣兩條測試之間發生的寫入會被算到下一條頭上，
而現在那段時間的寫入是無主的。誤判歸屬比慢十五秒糟。
這個取捨的數字留在這裡，是為了讓下一個人推得翻。

**前提一：Forseti App 不在跑。** App 每兩秒輪詢一次，
那些寫入會被算到剛好在跑的那條測試頭上。這三次量測都是在
`pgrep -x Forseti` 沒有回應的情況下跑的。App 在跑的時候這一組
會冒出大量寫入者，那是假陽性，不是真的有人改了測試。

**前提二：一條測試裡面先建檔再刪掉，這一組看不到。**
量的是「這條結束之後跟開始前有沒有不同」，不是期間發生過幾次寫入。
要量後者得攔動作，那是 `test_forseti_dir_writes._WriteSpy` 的範圍。
兩個問的不是同一題，所以兩個都要留著。

## 守的是什麼

一，**路徑**：動到的東西只准落在 `NEXT.md` 或 `cache/` 底下。
    其餘那些（`BLOCKERS.md`、`ROADMAP.md`、`pollution.jsonl`、
    `identity.jsonl`、`DECISION_LEDGER.md` …）是**重建不回來的正本狀態**，
    測試碰到就是把觀測資料跟被觀測的系統混在一起。

二，**誰**：動到正本的測試，它所在的檔案要在冊。粒度取到檔不取到條，
    因為同一個檔裡多加一條測試不該紅，而**一個新的檔開始動正本該紅**
    —— 那代表有人又在別的地方建了一條通往正本的路。

二之二，**次數**：`NEXT.md` 被寫的次數不超過這一輪跨過的節流窗數
    （`floor(跑了幾秒 / MIN_GAP_S) + 1`）。這個上界 2026-09-17
    改過一次：原本寫死「一輪最多一次」，而那句話的前提是
    「一輪比 240 秒短」。全套從 217.49 秒漲到 301.60 秒之後，
    2 條寫入者是節流正常運作的結果，卻被判成失效。
    **上界現在拿量到的秒數算，不拿假設算。**

三，**網還活著**：`conftest` 的掛鉤要真的每一條都跑到。
    沒有這一條的話，掛鉤壞掉會表現成「零個寫入者」，
    而零看起來跟通過一模一樣（`test_module_write_targets.py`
    的 docstring 記過同一個形狀的假陰性）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))


@pytest.fixture
def rec(request):
    """拿 pytest 載入的那一份 `conftest`，不自己 import。

    自己 `import conftest` 在某些 import 模式下會拿到另一份新模組，
    那一份的 `_RECORD` 永遠是空的，而空的記錄表跟「沒有人動正本」
    長得一模一樣。所以走 `pytest_configure` 掛上來的那條路。
    """
    r = getattr(request.config, "_forseti_recorder", None)
    assert r is not None, "conftest 的記錄器沒掛到 config 上，量測整組是瞎的"
    assert r is sys.modules.get("conftest", r), "拿到的不是 pytest 載入的那一份"
    return r

#: 允許被動到的頂層檔。`NEXT.md` 是系統設計上就會被 `strands()` 覆寫的
#: 產出檔，內容每一輪都重算得回來。
ALLOWED_TOP_LEVEL = frozenset({"NEXT.md"})

#: 允許被動到的目錄前綴。`cache/` 顧名思義刪掉會自己長回來。
ALLOWED_PREFIXES = ("cache/",)

#: 動到正本的測試，准許出現的檔案。2026-09-17 全套實測出來的，
#: 不是預先設計的。新增一個要先講得出「這個檔為什麼需要碰正本」。
REGISTERED_WRITER_FILES = frozenset({
    "tests/test_contract.py",
    "tests/test_handoff.py",
    "tests/test_identity.py",
    "tests/test_claims_wiring.py",
    "tests/test_ui_render.py",
    "tests/test_forseti_dir_writes.py",
    "tests/test_blast.py",
    # 2026-09-17 加的。`test_sot.py:357` 呼叫 `strands()`，而
    # `strands()` 尾段無條件走 `_write_handoff`（`desktop_api.py:3418`），
    # 目標是 `handoff.OUT` 也就是正本 `NEXT.md`。實測攔截
    # `handoff.should_write` / `handoff.write` 各 1 次、目標 `<default>`。
    # **會不會真的寫由 240 秒節流窗與執行順序決定**，所以它在觀測裡
    # 時有時無 —— 登記的是「這個檔碰得到正本」，不是「它那一次寫了」。
    # 不改成不碰：那一條測的正是 `strands()` 有沒有把 sot 接進快照，
    # 換成 `sot_panel()` 就不是同一題了（`sot_panel` 另有測試在 :284）。
    "tests/test_sot.py",
})

#: 直接呼叫 `strands()` 的測試檔。**這一組是掃原始碼掃出來的，
#: 不是觀測出來的** —— 上面那張名單的來源是「跑一輪看誰動到正本」，
#: 而 `NEXT.md` 一輪最多被寫幾次由節流窗決定，所以觀測只看得見
#: 贏了競速的那一條。`test_sot.py` 就是這樣藏了一輪：它從來都碰得到
#: 正本，只是前幾輪沒輪到它。
#:
#: 一個「潛在寫入者」的定義在這裡是可判定的：原始碼裡有一個
#: `strands()` 呼叫點，而 `strands()` 尾段無條件呼叫 `_write_handoff`。
STRANDS_CALLERS = frozenset({
    "tests/test_claims_wiring.py",
    "tests/test_forseti_dir_writes.py",
    "tests/test_handoff.py",
    "tests/test_sot.py",
})


def _scan_strands_callers(root: Path = ROOT / "tests") -> set[str]:
    """掃 `tests/` 底下每個 `test_*.py`，找出真的呼叫 `strands()` 的檔。

    **用 AST 不用 grep。** grep 會把 docstring 裡討論 `strands()` 的那些
    算進來 —— `test_handoff.py` 與 `test_forseti_dir_writes.py` 的說明裡
    各提了十幾次，`test_betrayal.py` 裡的 `strands(self)` 則是一個同名的
    方法定義不是呼叫。這三種 grep 分不出來。

    這個掃法看不到什麼（是前提不是補充）：

      一，`getattr(D, "strands")()` 這種動態取名的呼叫。
      二，測試呼叫某個輔助函式、由那支去呼叫 `strands()`（間接一層以上）。
      三，比對只看名字，所以別處有個同名函式會被算進來 —— 那是**假陽性**，
          方向是安全的（多紅不會少紅）。

    前兩種是真的漏，所以這一支守的是「直接呼叫點」這個範圍，
    不是「所有通往正本的路」。後者要攔動作，那是 `_WriteSpy` 的範圍。
    """
    import ast

    out: set[str] = set()
    for p in sorted(root.glob("test_*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name == "strands":
                out.add(str(p.relative_to(ROOT)))
                break
    return out

#: 這幾個重建不回來。點名是為了讓紅的時候訊息指得出嚴重性，
#: 不是靠「不在白名單內」這種只說得出否定的講法。
IRREPLACEABLE = (
    "BLOCKERS.md", "ROADMAP.md", "AUTO_CONTINUE_LOG.md", "NORTH_STAR.md",
    "DECISION_LEDGER.md", "REQUIRED_READING.md", "PHASE_STATUS.md",
    "pollution.jsonl", "identity.jsonl",
)


#: Claude Code 的 hook 掛在哪三個事件上。來源不是猜的:
#: `.claude/settings.json` 寫著 `PreToolUse` / `PostToolUse` / `Stop`
#: 三個掛點，而 `hooks/forseti-stop-hook.mjs:112` 與
#: `hooks/forseti-hook.mjs:379` 各自呼叫 `event-ledger.mjs` 的
#: `appendEvent()`，把一筆 `provider: "claude-code"` 接在
#: `.forseti/event_ledger.jsonl` 檔尾。
HOOK_EVENT_TYPES = frozenset({"Stop", "PreToolUse", "PostToolUse"})


def _written_by_external_hook(blob: str) -> bool:
    """這一段接在檔尾的內容，是不是整段都由 Claude Code 的 hook 寫的。

    ## 為什麼需要這一支

    `conftest` 量的是「這條測試前後這個檔有沒有不同」。
    那個量法**分不出寫入者** —— 時間窗裡的每一次寫入都會被記在
    當時在跑的那一條頭上，不管寫的人是不是它。

    2026-09-17 實測抓到一個:
    `test_ui_render.py::TabsMatchData::test_切過去之後別頁不會同時亮著`
    被記成動了 `event_ledger.jsonl`（+669 位元組）。單獨重跑一次，
    一模一樣的 +669 再現。把那一段讀出來是一筆
    `{"provider":"claude-code","provider_event_type":"Stop", ...}`。
    那一條測試跑 71 秒，而 hook 由**別的 session 結束回合**觸發，
    跟 pytest 沒有關係。

    決定性的那一步是在 `.forseti/` 以外做的:把 `hooks/` 複製到一個
    空的假 repo，餵一筆 `{"hook_event_name":"Stop"}` 進 stdin，
    **零 pytest**，它就在那個假 repo 底下寫出了結構完全相同的一筆。
    底下 `test_hook單獨跑就會寫事件帳本` 把這一步釘成可重跑的。

    ## 判準與它的代價

    判準是內容自己帶的來源欄位，不是時間、不是檔名、不是次數。
    整段每一行都要是 hook 事件才算，有一行不是就整段不算 ——
    因為混著的那種情況，測試確實寫了東西。

    **解不出 JSON 一律回 False（= 不放行）。** 讀新增段的時候
    不驗前綴（理由在 `conftest._appended`），所以檔頭被改過會切在
    行中間。切壞了就不放行，方向是多紅不是少紅。

    **代價寫明:** 一條測試要是刻意 append 一筆
    `provider: "claude-code"` 的 hook 事件進正本，這裡會放它過。
    沒有辦法從內容分辨「hook 寫的」跟「測試造了一筆長得像 hook 的」，
    那要攔動作，不是看結果。願意付這個代價，是因為另一邊的代價
    是每一輪點名一條無辜的測試 —— 而被點名的檔只有兩條路:
    修一個沒壞的東西，或者在名單裡登記一個假理由。
    """
    lines = [ln for ln in blob.splitlines() if ln.strip()]
    if not lines:
        return False
    for ln in lines:
        try:
            obj = json.loads(ln)
        except (ValueError, TypeError):
            return False
        raw = obj.get("raw") if isinstance(obj, dict) else None
        if not isinstance(raw, dict):
            return False
        if raw.get("provider") != "claude-code":
            return False
        if raw.get("provider_event_type") not in HOOK_EVENT_TYPES:
            return False
    return True


def _allowed(rel: str) -> bool:
    if rel in ALLOWED_TOP_LEVEL:
        return True
    return any(rel.startswith(pre) for pre in ALLOWED_PREFIXES)


def _bad_paths(nodeid: str, paths, appended: dict | None) -> list[str]:
    """這一條測試動到的路徑裡，真的算在它頭上的那些。

    兩道篩:路徑不在允許範圍內，而且那一次變動不是外部 hook 寫的。
    第二道要有 `appended` 才生效 —— 沒帶的時候退回只篩路徑，
    也就是**修正前的行為**。退回的方向是嚴的不是鬆的:
    量不到內容就不放行。
    """
    caps = (appended or {}).get(nodeid) or {}
    out = []
    for rel in paths:
        if _allowed(rel):
            continue
        blob = caps.get(rel)
        if blob is not None and _written_by_external_hook(blob):
            continue
        out.append(rel)
    return out


#: 紅的訊息裡，每個檔的新增段最多帶這麼多字。
EVIDENCE_CHARS = 200


def _evidence(nodeid: str, rels, appended: dict | None) -> str:
    """把擷取到的新增段摘要成一行，附在紅的訊息後面。

    **這一支存在的理由是實測的代價。** 2026-09-17 同一輪裡，
    同一個機制（時間窗歸因）誤記了兩次:一次是 Stop hook，
    一次是有人在全套跑的期間手動登記一筆污染記錄。
    第一次花了三輪才查出寫入者，第二次當場就看得出來 ——
    差別只在於第二次有新增段可以讀。

    訊息裡帶出內容，是把那個差別交到下一個人手上。
    沒有擷取到就明說「沒有擷取到」，不留白 ——
    留白跟「擷取到而且是空的」在讀的人眼裡同形。
    """
    caps = (appended or {}).get(nodeid) or {}
    bits = []
    for rel in rels:
        blob = caps.get(rel)
        if blob is None:
            bits.append(f"{rel}: 沒有擷取到新增段（不是 append，或太大）")
            continue
        head = " ".join(blob.split())[:EVIDENCE_CHARS]
        bits.append(f"{rel} 接上去的是:{head}")
    return "　".join(bits)


def _offending_files(record: dict, appended: dict | None = None) -> set[str]:
    """動到「不被允許的路徑」的測試檔。

    **抽成函式是為了驗得到。** 底下那條吃的是這一輪的實際記錄，
    而記錄裡有什麼取決於誰先跑、快取過期了沒 —— 那是時序。
    2026-09-17 實測:同一組反向驗證連跑兩輪，
    退回修正前的版本兩次都沒紅，因為前幾輪已經把快取養新鮮了。
    **靠時序驗不了的判準，就不該靠時序驗。**

    `appended` 帶進來的時候多一道篩:那一次變動的內容整段都是
    外部 hook 寫的話，不算在這條測試頭上（`_written_by_external_hook`）。
    """
    return {
        nodeid.split("::", 1)[0]
        for nodeid, paths in record.items()
        if _bad_paths(nodeid, paths, appended)
    }


def test_只動快取不算動到正本(rec):
    """`cache/` 底下的東西不算，混著正本的算。

    這一條釘住的是兩條規則的一致性:`ALLOWED_PREFIXES` 明寫
    `cache/` 可以動，而「在冊」那條先前只看檔名不看路徑，
    於是同一件事兩條規則的態度相反。代價實測看得到:
    快取何時重寫取決於它過期了沒，所以每一輪被點名的檔都不一樣。
    """
    fake = {
        "tests/t_cache_only.py::x": ["cache/identity.json",
                                     "cache/blast.json"],
        "tests/t_next_only.py::y": ["NEXT.md"],
        "tests/t_real.py::z": ["event_ledger.jsonl"],
        "tests/t_mixed.py::w": ["cache/x.json", "checkpoints.jsonl"],
    }
    assert _offending_files(fake) == {"tests/t_real.py", "tests/t_mixed.py"}


def _hook_line(ev: str = "Stop", provider: str = "claude-code") -> str:
    """一筆長得跟 hook 真的寫出來那樣的事件。

    欄位形狀不是照著判準倒推的，是 2026-09-17 從假 repo 裡
    真的跑出來那一筆剪下來的（見 `test_hook單獨跑就會寫事件帳本`）。
    """
    return json.dumps({
        "norm": {"action": ev, "type": "MODEL_OUTPUT",
                 "session_id": "S", "provenance": "OBSERVED"},
        "raw": {"id": "1-a", "payload": {"hook_event_name": ev},
                "provider": provider, "provider_event_type": ev,
                "timestamp": 1.0},
    }, ensure_ascii=False)


def test_認得出外部hook寫的那一段(rec):
    """判準是內容自己帶的來源欄位，不是時間也不是檔名。"""
    assert _written_by_external_hook(_hook_line("Stop"))
    assert _written_by_external_hook(
        _hook_line("PreToolUse") + "\n" + _hook_line("PostToolUse") + "\n")


def test_這一支抓得到東西而不是永遠回True(rec):
    """一個永遠回 True 的實作會讓上面那條全綠，而守門整個失效。

    所以反例要一條一條列，每一條對應一種**真的會被放過去**的錯:
    少了 provider 的檢查、少了事件種類的檢查、少了「整段都要是」、
    少了「解不出來不放行」。
    """
    # 不是 hook 的 provider —— 測試自己 append 的事件長這樣
    assert not _written_by_external_hook(_hook_line(provider="forseti-test"))
    # provider 對，事件種類不是 hook 掛的那三個
    assert not _written_by_external_hook(_hook_line("RESCUE"))
    # 混著:一行是 hook，一行是別人寫的 —— 整段不算
    assert not _written_by_external_hook(
        _hook_line("Stop") + "\n" + _hook_line(provider="x"))
    # 解不出 JSON（讀新增段的時候切在行中間就長這樣）
    assert not _written_by_external_hook('r":"claude-code"}}\n')
    # 空的。量到了而且是空的，跟「沒量到」不同，這裡不放行
    assert not _written_by_external_hook("")
    assert not _written_by_external_hook("\n\n")
    # 是合法 JSON 但不是這個帳本的形狀
    assert not _written_by_external_hook('{"raw": "claude-code"}')
    assert not _written_by_external_hook('[1,2,3]')


def test_hook寫的不算在那條測試頭上_而別人寫的照算(rec):
    """這一條釘住的是 2026-09-17 那個假紅的修法。

    `test_ui_render.py` 那一條跑 71 秒，期間別的 session 結束了一次
    回合，Stop hook 往 `event_ledger.jsonl` 接了一筆。
    `conftest` 的量法分不出寫入者，於是那一筆被記在它頭上。
    """
    record = {
        "tests/t_ui.py::a": ["event_ledger.jsonl"],
        "tests/t_real.py::b": ["event_ledger.jsonl"],
        "tests/t_mixed.py::c": ["event_ledger.jsonl"],
    }
    appended = {
        "tests/t_ui.py::a": {"event_ledger.jsonl": _hook_line("Stop")},
        "tests/t_real.py::b": {
            "event_ledger.jsonl": _hook_line(provider="forseti-test")},
        # 這一條有 hook 那一筆，也有自己寫的那一筆
        "tests/t_mixed.py::c": {
            "event_ledger.jsonl":
                _hook_line("Stop") + "\n" + _hook_line(provider="x")},
    }
    assert _offending_files(record, appended) == {
        "tests/t_real.py", "tests/t_mixed.py"}


def test_紅的訊息帶得出寫進去的是什麼(rec):
    """訊息裡沒有內容的話，下一個人只能靠猜 —— 這一輪猜錯過兩次。

    三種情況各驗一次:擷取到了、沒擷取到、混著。
    「沒擷取到」要明說，不准留白。
    """
    ap = {"tests/t.py::x": {"pollution.jsonl": '{"id":"pol-x","a":1}'}}
    msg = _evidence("tests/t.py::x", ["pollution.jsonl"], ap)
    assert "pol-x" in msg, f"內容沒帶出來:{msg}"

    msg = _evidence("tests/t.py::x", ["checkpoints.jsonl"], ap)
    assert "沒有擷取到" in msg, f"擷取不到卻沒說:{msg}"

    msg = _evidence("tests/t.py::x", ["pollution.jsonl", "別的.jsonl"], ap)
    assert "pol-x" in msg and "沒有擷取到" in msg, msg

    # 沒帶 appended 的時候也要講得出話，不准炸
    assert "沒有擷取到" in _evidence("tests/t.py::x", ["a.jsonl"], None)

    # 超長的要截斷，不把整個檔倒進錯誤訊息
    long = {"tests/t.py::x": {"a.jsonl": "x" * 5000}}
    assert len(_evidence("tests/t.py::x", ["a.jsonl"], long)) < 400


def test_量不到內容的時候退回嚴的那一邊(rec):
    """沒帶 `appended`、或者這個檔沒被擷取到，一律照舊算成動到正本。

    **這一條守的是預設方向。** 放寬的判準要是在「量不到」的時候
    也生效，那它就不是判準，是一個看不見的白名單。
    """
    record = {"tests/t.py::x": ["event_ledger.jsonl"]}
    assert _offending_files(record) == {"tests/t.py"}
    assert _offending_files(record, {}) == {"tests/t.py"}
    assert _offending_files(record, {"tests/t.py::x": {}}) == {"tests/t.py"}
    # 別的檔擷取到了，這個檔沒有 —— 這個檔照樣算
    assert _offending_files(
        record, {"tests/t.py::x": {"別的檔.jsonl": _hook_line()}}
    ) == {"tests/t.py"}


def test_hook單獨跑就會寫事件帳本(rec, tmp_path):
    """**零 pytest 的對照組。** 在假 repo 裡跑一次 Stop hook。

    上面那幾條驗的是判準本身，而判準成不成立取決於一件事實:
    寫 `event_ledger.jsonl` 的真的是 hook，不是那條測試。
    那件事實在這裡驗，而且**不碰正本** —— `hooks/` 複製到 tmp，
    hook 自己的 `REPO_ROOT` 是從它所在位置算的
    （`forseti-stop-hook.mjs` 的 `resolvePath(HERE, '..')`），
    所以它會寫進 tmp 底下那個 `.forseti/`。

    沒有 node 就 `skip`，不當成通過。
    """
    if shutil.which("node") is None:
        pytest.skip("沒有 node，驗不了，不是通過")

    fake = tmp_path / "fakerepo"
    (fake / "hooks").mkdir(parents=True)
    for f in (ROOT / "hooks").glob("*.mjs"):
        shutil.copy2(f, fake / "hooks" / f.name)

    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(fake),
                          "session_id": "TEST-SESSION-0001",
                          "transcript_path": ""})
    r = subprocess.run(["node", str(fake / "hooks" / "forseti-stop-hook.mjs")],
                       input=payload, capture_output=True, text=True,
                       cwd=str(fake), timeout=60)
    assert r.returncode == 0, f"hook 自己壞了，驗不了:{r.stderr[:400]}"

    out = fake / ".forseti" / "event_ledger.jsonl"
    assert out.exists(), (
        "hook 跑完沒有寫出事件帳本 —— 那麼「寫入者是 hook」這個結論"
        f"就沒有根據了。stderr:{r.stderr[:400]}")
    blob = out.read_text(encoding="utf-8")
    assert _written_by_external_hook(blob), (
        "hook 真的寫出來的那一段，判準認不出來 —— "
        f"判準跟現實對不上了。內容:{blob[:400]}")

    # 正本一個位元組都不准動:這一條要能天天跑。
    assert out.resolve() != (ROOT / ".forseti" / "event_ledger.jsonl").resolve()
    assert fake.resolve() != ROOT.resolve(), "hook 的 REPO_ROOT 指回正本了"


def test_擷取新增段這支自己是對的(rec, tmp_path):
    """判斷層再準，擷取層讀錯東西的話整條鏈就是假的。

    這一條驗 `conftest._appended()` 本身:讀回來的要剛好是接上去
    那一段，而且**四種讀不到的情況要回 `None` 不回空字串** ——
    空字串在判斷層跟「量到了而且是空的」同形，
    而那兩件事的正確結果不一樣。
    """
    f = tmp_path / "x.jsonl"
    f.write_text("第一行\n", encoding="utf-8")
    before = f.stat().st_size
    with f.open("a", encoding="utf-8") as fh:
        fh.write("第二行\n第三行\n")
    after = f.stat().st_size

    assert rec._appended("x.jsonl", before, after, tmp_path) == "第二行\n第三行\n"
    # 沒變大 —— 沒有東西可以擷取
    assert rec._appended("x.jsonl", after, after, tmp_path) is None
    # 變小（被截斷或重寫）
    assert rec._appended("x.jsonl", after, before, tmp_path) is None
    # 超過上限就整段不留，不留一半
    assert rec._appended(
        "x.jsonl", 0, rec.APPEND_CAPTURE_LIMIT + 1, tmp_path) is None
    # 檔不在 —— 記進 scan_errors，不靜默吞掉。
    #
    # **驗完要把自己加的那一筆拿掉。** `_SCAN_ERRORS` 是整場共用的，
    # 而它的用途是讓人看見「掃描期間有東西讀不到」這種真問題。
    # 一條測試故意製造的失敗留在裡面，等於在那張清單上放一個
    # 永遠不會被修的東西 —— 而一張永遠有東西的清單，
    # 跟一張沒有人看的清單是同一張。
    n = len(rec.scan_errors())
    try:
        assert rec._appended("沒有這個檔.jsonl", 0, 10, tmp_path) is None
        assert len(rec.scan_errors()) == n + 1, "讀不到卻沒有留下記錄"
    finally:
        del rec._SCAN_ERRORS[n:]
    assert len(rec.scan_errors()) == n, "自己製造的那一筆沒有收乾淨"


def test_擷取到的東西送得進判斷層(rec, tmp_path):
    """兩層接得起來才算數:擷取層讀出來的原文，判斷層認得出來。

    分開驗會漏掉一種:兩邊各自對但格式對不上（例如一邊帶著
    行尾換行、另一邊假設沒有）。這一條把真的 hook 事件寫進檔尾，
    走一次擷取再走一次判斷。
    """
    f = tmp_path / "event_ledger.jsonl"
    f.write_text(_hook_line("Stop") + "\n", encoding="utf-8")
    before = f.stat().st_size
    with f.open("a", encoding="utf-8") as fh:
        fh.write(_hook_line("PreToolUse") + "\n")
    blob = rec._appended("event_ledger.jsonl", before, f.stat().st_size,
                         tmp_path)
    assert blob is not None, "擷取不到"
    assert _written_by_external_hook(blob), f"判斷層不認得:{blob[:200]}"
    assert _offending_files(
        {"tests/t.py::x": ["event_ledger.jsonl"]},
        {"tests/t.py::x": {"event_ledger.jsonl": blob}}) == set()


def test_sidecar不算寫入而快取照記(rec):
    """職責劃分:conftest 只擋檔案系統自己長的東西。

    `cache/` 要不要算成「動到正本」是判斷，判斷在 `_allowed()`。
    兩邊各寫一份會分歧，而分歧的那天沒有人會發現。
    """
    assert rec._skip("._NEXT.md"), "頂層 sidecar 沒被擋掉"
    assert rec._skip("cache/._identity.json"), "快取裡的 sidecar 沒被擋掉"
    assert not rec._skip("cache/identity.json"), (
        "快取被 conftest 擋掉了 —— 那是判斷，不該做在觀測層")
    assert not rec._skip("NEXT.md")
    assert not rec._skip("event_ledger.jsonl")


# ---------------------------------------------------------------- 網還活著

def test_掃描與比對這兩支自己是對的(rec, tmp_path):
    """不依賴 session，純函式層級確認 `_snapshot` 與 `_diff` 沒瞎掉。

    這一條是其餘幾條的前提：比對函式壞掉的話，
    「沒有人動正本」跟「量不到」會回傳一模一樣的東西。
    """
    (tmp_path / "a.txt").write_text("1")
    before = rec._snapshot(tmp_path)
    assert before, "掃得到檔案才算掃描器活著"

    (tmp_path / "a.txt").write_text("22")          # 改內容
    (tmp_path / "b.txt").write_text("new")         # 新增
    after = rec._snapshot(tmp_path)
    assert rec._diff(before, after) == ["a.txt", "b.txt"]

    (tmp_path / "a.txt").unlink()                  # 刪除也要看得到
    assert "a.txt" in rec._diff(after, rec._snapshot(tmp_path))


def test_沒有變動的時候比對回空的不是回全部(rec, tmp_path):
    """反方向：同一張表比自己要是空的。

    這一條在的理由是，如果 `_diff` 永遠回一堆東西，
    上面那條照樣會過，而白名單那幾條會變成永遠紅的噪音。
    """
    (tmp_path / "a.txt").write_text("1")
    snap = rec._snapshot(tmp_path)
    assert rec._diff(snap, snap) == []


def test_掃描不到的路徑不被靜默吞掉(rec):
    """`_snapshot` 遇到 stat 失敗要留下痕跡，不是當成沒有這個檔。

    §5ai 那一輪量過九個靜默 `except OSError`，這裡是同一個形狀的預防：
    掃不到跟不存在在比對表裡長得一樣，差別只在有沒有記下來。
    """
    src = Path(rec.__file__).read_text(encoding="utf-8")
    assert "_SCAN_ERRORS.append" in src, "掃描錯誤要被記下來"
    assert "scan_errors" in src, "而且要有人拿得到"


def test_節流拿的是正本檔自己的時間(tmp_path):
    """上面那個「條件性」的成因，用行為釘住不是用註解講。

    `should_write` 讀的是檔案 mtime，所以同一條測試跑兩次結果不同 ——
    這正是全套那一次看不到 `NEXT.md` 的原因。
    """
    import handoff  # noqa: E402

    p = tmp_path / "NEXT.md"
    assert handoff.should_write(p) is True, "檔不存在的時候該寫"

    p.write_text("x")
    assert handoff.should_write(p) is False, "剛寫過就在窗內"

    import os
    old = p.stat().st_mtime - handoff.MIN_GAP_S - 1
    os.utime(p, (old, old))
    assert handoff.should_write(p) is True, "超過 MIN_GAP_S 就在窗外"


# ---------------------------------------------------------------- 名單比對

def test_NEXT_md的寫入次數不超過節流窗開過的次數(rec):
    """寫 `NEXT.md` 的測試條數，不准超過這一輪跨過的節流窗數。

    **不釘是哪一條** —— 2026-09-17 兩次全套量到的是兩個不同的答案，
    見這個檔開頭的說明。守得住的是數量。

    **上界是算出來的，不是假設的。** 這一條原本寫死「一輪最多一次」，
    前提是「一輪三分多鐘」比 `MIN_GAP_S = 240` 短。
    2026-09-17 全套從 217.49 秒漲到 301.60 秒，跨過那條線，
    於是量到 2 條寫入者而這一條紅了 —— **那次紅是假陽性**：
    301 秒裡節流窗開得成兩次，兩次寫入正是節流在運作。

    真正的上界：一段長 T 的時間裡，最小間隔 G 的事件最多
    `floor(T / G) + 1` 次。一輪比 G 短的時候這個式子就是 1，
    跟原本那句話一致 —— 所以守的東西沒有被放寬，只是把
    「一輪一定比節流窗短」這個會過期的前提換成量到的秒數。
    """
    import handoff  # noqa: E402

    elapsed = rec.session_elapsed_s()
    assert elapsed > 0, (
        "拿不到這一輪跑了多久，上界算不出來。"
        "`conftest.pytest_configure` 沒跑到的話整組量測是瞎的"
    )
    allowed = int(elapsed // handoff.MIN_GAP_S) + 1
    writers = [
        nodeid for nodeid, paths in rec.write_record().items()
        if "NEXT.md" in paths
    ]
    assert len(writers) <= allowed, (
        f"這一輪有 {len(writers)} 條測試寫到 NEXT.md：{writers}　"
        f"這一輪跑了 {elapsed:.1f} 秒，節流是 {handoff.MIN_GAP_S} 秒，"
        f"所以最多寫得成 {allowed} 次，多出來的代表節流失效"
    )
    for nodeid in writers:
        assert nodeid.split("::", 1)[0] in REGISTERED_WRITER_FILES, (
            f"{nodeid} 寫了 NEXT.md 但不在冊"
        )


def test_掛鉤每一條測試都跑到了(rec, request):
    """已完成的測試條數，要跟記錄表的筆數對得起來。

    對不起來代表掛鉤漏掉了某些測試，而漏掉的那些正好是
    「沒有人動正本」這個結論裡看不見的部分。
    """
    items = request.session.items
    me = items.index(request.node)
    recorded = len(rec._RECORD)
    assert recorded == me, (
        f"這一條是第 {me} 條（0 起算），照理前面 {me} 條都該被記錄，"
        f"實際記錄表裡只有 {recorded} 筆 —— 掛鉤漏了 {me - recorded} 條"
    )


#: 迷你 session 裡那條測試的 nodeid。判斷層拿 `::` 前半當檔名，
#: 所以這一個字串同時是「哪一條測試」與「哪一個檔」的來源。
E2E_NODEID = "tests/test_e2e_inner.py::test_期間有外部程序往正本接一筆"

#: 迷你 session 最多跑這麼久。它只有一條測試加一次 node 呼叫，
#: 實測 0.13 秒；給到分鐘級是留給冷啟動與慢碟，不是留給它卡住。
E2E_TIMEOUT_S = 180

#: 迷你 session 裡那條測試的原始碼。
#:
#: **它自己一個位元組都不寫 `.forseti/`** —— 寫的是它起的那個 node
#: 子程序，而那正是真實場景的形狀：別的 session 結束一次回合，
#: Stop hook 在這條測試跑的期間往事件帳本檔尾接一筆。
#: 差別只有時機是確定的而不是碰運氣，而那是驗證要的方向。
E2E_INNER = '''import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_期間有外部程序往正本接一筆():
    """這一條自己不碰 `.forseti/`，碰的是它起的那個 node 子程序。"""
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(ROOT),
                          "session_id": "E2E-0001", "transcript_path": ""})
    r = subprocess.run(["node", str(ROOT / "hooks" / "forseti-stop-hook.mjs")],
                       input=payload, capture_output=True, text=True,
                       cwd=str(ROOT), timeout=60)
    assert r.returncode == 0, r.stderr[:400]
'''


def test_端到端_跑的期間hook接一筆_那條測試不被點名(rec, tmp_path):
    """**整條鏈走一次真的。** 上一輪（5ai 之後那一輪）自己寫下的缺口。

    原話在 `AUTO_CONTINUE_LOG.md`：

        端到端沒驗到。要驗得想一個不污染正本的辦法，
        例如讓 `conftest.FORSETI_DIR` 可以被指到別處，
        再起一個迷你 session。

    在那之前，這條鏈的三段各自驗過（擷取層的單元測試、判斷層的
    單元測試、假 repo 證明 hook 是寫入者），**接起來沒有走過一次**。
    分段驗過不等於接得起來 —— `test_擷取到的東西送得進判斷層` 就是
    為了同一個理由才存在的，那一條接的是兩層，這一條接的是四層：
    外部程序寫 → conftest 擷取 → 判斷層放行 → 名單不點名。

    ## 做法換過，理由要一起看

    上一輪設想的是「讓 `FORSETI_DIR` 可以被指到別處」，
    也就是往觀測層加一個開關。**這裡改成複製那一份 conftest。**
    `conftest.py` 的 `FORSETI_DIR` 是從它自己的位置算的
    （`ROOT = Path(__file__).resolve().parents[1]`），所以複製到假 repo
    底下，它算出來的就是假的那一個 —— 同一件事，不必加開關。

    差別在於：一個只有測試才走得到的環境變數分支，平常沒有人走，
    而沒有人走的路壞了不會有人知道。複製沒有這個問題，代價是
    **驗的是那一份原始碼的行為，不是 pytest 此刻載入的那個物件**，
    所以下面第一件事是逐位元組比對 sha256。不比對的話，哪天有人
    改了正本 conftest 而這一條照樣綠，那它守的就是一份舊程式碼。

    ## 為什麼要先寫一行進去（seed）

    `conftest.pytest_runtest_protocol` 只對「前後都在」的檔擷取新增段
    （`b is None or a is None: continue`），所以**新建的檔擷取不到內容**，
    判斷層會退回嚴的那一邊。真實場景裡 `event_ledger.jsonl` 一直都在，
    那一次是長大不是新建，所以這裡先放一行讓形狀對得上。

    新建那一種不是漏，是保守方向（多紅不少紅），
    但它跟這一條要驗的不是同一題，所以不混在一起。

    ## 最後那個對照組才是這一條的重點

    前三個斷言全綠，只證明「這一輪沒有被誤指控」。
    它們在放行邏輯整個被拔掉的時候**仍然可能全綠** —— 只要那一輪
    hook 沒寫。所以第四個斷言反過來問：把內容那一半拿掉，
    這條測試會不會被點名。答案要是「不會」，那就代表放行根本沒起作用，
    而前面三條綠得沒有意義。
    """
    if shutil.which("node") is None:
        pytest.skip("沒有 node，驗不了，不是通過")

    fake = tmp_path / "e2e"
    for sub in ("hooks", "tests", ".forseti"):
        (fake / sub).mkdir(parents=True)
    for f in (ROOT / "hooks").glob("*.mjs"):
        shutil.copy2(f, fake / "hooks" / f.name)

    src = Path(rec.__file__).resolve()
    dst = fake / "tests" / "conftest.py"
    shutil.copy2(src, dst)
    assert (hashlib.sha256(dst.read_bytes()).hexdigest()
            == hashlib.sha256(src.read_bytes()).hexdigest()), (
        "複製過去的 conftest 跟 pytest 此刻載入的那一份不一樣　"
        "—— 那麼下面驗到的就不是現在這份觀測層的行為")

    # 真實場景裡這個檔一直都在，所以那一次是長大不是新建。理由見 docstring。
    (fake / ".forseti" / "event_ledger.jsonl").write_text(
        _hook_line() + "\n", encoding="utf-8")
    (fake / "tests" / "test_e2e_inner.py").write_text(
        E2E_INNER, encoding="utf-8")

    out = fake / "attr.json"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
        cwd=str(fake), capture_output=True, text=True,
        env=dict(os.environ, FORSETI_WRITE_ATTRIBUTION_OUT=str(out)),
        timeout=E2E_TIMEOUT_S)
    assert r.returncode == 0, (
        "迷你 session 自己就紅了，那麼它量到的東西不能當根據　"
        f"stdout：{r.stdout[-800:]}　stderr：{r.stderr[-400:]}")
    assert out.exists(), "迷你 session 沒有把量到的東西倒出來"

    payload = json.loads(out.read_text(encoding="utf-8"))
    writers, appended = payload["writers"], payload["appended"]

    assert payload["scan_errors"] == [], (
        f"迷你 session 掃描期間有讀不到的路徑：{payload['scan_errors']}")

    hit = sorted(n for n, paths in writers.items()
                 if "event_ledger.jsonl" in paths)
    assert hit == [E2E_NODEID], (
        "hook 接上去那一筆沒有被記在那條慢測試頭上　"
        f"—— 實際記到的是 {hit}，整條鏈的第一段就沒接上　"
        f"（全部記錄：{writers}）")

    blob = (appended.get(E2E_NODEID) or {}).get("event_ledger.jsonl")
    assert blob is not None, (
        "擷取層沒有把接上去那一段讀回來　"
        f"—— 判斷層無從判起（擷取到的：{ {k: list(v) for k, v in appended.items()} }）")
    assert _written_by_external_hook(blob), (
        f"真的 hook 寫出來的那一段，判準認不出來：{blob[:300]}")

    assert _offending_files(writers, appended) == set(), (
        "整條鏈接起來之後仍然點名了　"
        f"—— {_offending_files(writers, appended)}")

    assert _offending_files(writers) == {E2E_NODEID.split("::", 1)[0]}, (
        "把內容那一半拿掉之後它**沒有**被點名　"
        "—— 那代表上面三條綠得跟放行邏輯無關，這一條驗的東西是假的")


def test_呼叫strands的檔掃得出來而且一個都不漏(rec):
    """潛在寫入者要從原始碼掃出來，不是等它在某一輪贏了競速才被看見。

    **這一條補的是上面那張名單的來源缺陷。** `REGISTERED_WRITER_FILES`
    是 2026-09-17 跑全套觀測出來的，而 `NEXT.md` 的寫入者由
    `handoff.should_write` 的 240 秒節流窗加上執行順序決定 ——
    所以觀測到的永遠只是「那一輪碰巧寫成的那一條」。
    `test_sot.py` 連續幾輪都在名單外，不是因為它不碰正本，
    是因為沒輪到它：同一輪裡它有一次動到、最後一次沒動到。

    **兩個斷言抓的不是同一件事**，所以兩個都要：

      掃出來的集合 == 寫下來的集合
          抓「有人在既有的在冊檔裡新加了一個 `strands()` 呼叫點」。
          這種情況下面那一條抓不到，因為那個檔本來就在冊。
      掃出來的集合 ⊆ 在冊的集合
          抓「有人開了一個新檔去呼叫 `strands()`」。

    掃不到什麼寫在 `_scan_strands_callers` 的 docstring 裡，
    那是這一條的前提不是補充。
    """
    found = _scan_strands_callers()

    assert found == STRANDS_CALLERS, (
        f"掃到的 `strands()` 呼叫檔跟寫下來的對不上。"
        f"　多出來的：{sorted(found - STRANDS_CALLERS)}"
        f"　少掉的：{sorted(STRANDS_CALLERS - found)}"
        "　新增一個呼叫點要先在 STRANDS_CALLERS 登記，"
        "因為它是一條新的通往正本 NEXT.md 的路"
    )

    unregistered = sorted(found - REGISTERED_WRITER_FILES)
    assert not unregistered, (
        f"這幾個檔呼叫 `strands()`，也就是碰得到正本 NEXT.md，"
        f"但不在 REGISTERED_WRITER_FILES：{unregistered}　"
        "要嘛讓它別走 `strands()`，要嘛登記並寫下理由。"
        "**不准等它某一輪真的寫成了才處理** —— 那是用競速結果當證據"
    )


def test_動到正本的測試全部在冊(rec):
    """**只算動到「不被允許的路徑」的。**

    2026-09-17 修正：這一條原本只看 `write_record()` 有沒有這個檔名，
    不看它動到的是什麼路徑，於是跟下一條（路徑白名單）對同一件事
    態度相反 —— `ALLOWED_PREFIXES` 明寫 `cache/` 可以動，
    這一條卻把動到 `cache/identity.json` 的檔也要求登記。

    代價是實測看得到的：快取何時重寫取決於它過期了沒，那是時序，
    所以每一輪被點名的檔都不一樣。兩輪分別點名 `test_blockers`、
    `test_claims`、`test_context_meter`，而那三個單獨跑一個都沒碰正本
    （`test_context_meter.py` 全檔連 `.forseti` 這個字都沒有）。

    被無辜點名的檔只有兩條路：修一個沒壞的東西，
    或者在名單裡登記一個假理由。後者更糟，因為它會留下來。
    """
    seen = _offending_files(rec.write_record(), rec.append_record())
    unregistered = sorted(seen - REGISTERED_WRITER_FILES)
    assert not unregistered, (
        f"這幾個檔開始動正本 `.forseti/` 了，但不在冊：{unregistered}　"
        "要嘛讓它別碰正本，要嘛在 REGISTERED_WRITER_FILES 裡登記並寫下理由"
    )


def test_動到的路徑全部在允許範圍內_而且這是最後一條(rec, request):
    """路徑比對，外加「這一條必須是整個 session 的最後一條」。

    兩件事寫在一起不是偷懶。位置斷言要是自己另外開一條，
    那一條後面永遠還有別的測試，於是它守的位置不是真的最後。
    檔名 `test_zz_` 加上這一條擺在檔尾，兩個合起來才成立；
    哪天有人裝了打亂順序的外掛，這裡會先紅，
    而不是讓白名單無聲地只檢查一半。
    """
    items = request.session.items
    assert items[-1] is request.node, (
        f"這一條排在第 {items.index(request.node)}，"
        f"後面還有 {len(items) - 1 - items.index(request.node)} 條不會被檢查"
    )

    appended = rec.append_record()
    offenders = {}
    for nodeid, paths in rec.write_record().items():
        bad = _bad_paths(nodeid, paths, appended)
        if bad:
            offenders[nodeid] = bad
    grave = sorted({
        p for bad in offenders.values() for p in bad
        if p in IRREPLACEABLE
    })
    ev = "　".join(_evidence(n, bad, appended) for n, bad in offenders.items())
    assert not offenders, (
        f"有測試動到不該動的正本：{offenders}"
        + (f"　其中這幾個重建不回來：{grave}" if grave else "")
        + (f"\n\n寫進去的是什麼（先看這個再判斷是不是這條測試寫的）：\n{ev}"
           if ev else "")
        + "\n\n提醒：這個量法分不出寫入者，"
          "全套跑的期間有人動正本的話會被記在當時在跑的那一條頭上。"
    )


