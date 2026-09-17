"""§12.1 RuntimeNode：這一份工作現在跑在哪台機器。

2026-09-17 加。在這之前 `contract.py` 的 `runtime_node` 那一欄是
`NO_SOURCE`，而 `.forseti/NEXT.md` 的「已經發生過的決定」第一條
就是「換機器：舊機器硬碟不穩，工作移往新電腦」——
**一份記錄過換機器的交接檔，答不出現在這一份是在哪台機器上寫的。**

這一組守的是三件事，順序是重要性排的：

一，**空的那三欄要一直是空的。** `service` / `version` / `health`
    沒有來源，而「填一個看起來合理的值進去」在這個 repo 是慣犯
    （`contract.py` 已經記過「jsonl 的 version 是 CLI 版本不是模型版本」）。
    所以下面有三條專門守「它們沒有被頂替」，不是守「它們現在是空的」。

二，**node_id 要跟著它宣稱的輸入走。** 一個不理會輸入、永遠回同一個
    字串的實作，在「跨行程一致」那條測試底下是全綠的。
    所以一致性與敏感性兩邊都要問，只問一邊會綠得沒有意義。

三，**原始硬體識別碼不能流出去。** 它會被寫進 git 追蹤的檔案。

## 這一組看不到什麼（是前提不是補充）

`_WriteSpy` 攔不到子行程。這一支會叫 `ioreg`，所以「一個檔都不寫」
那條證到的是「這個 python 行程沒寫」，不是「`ioreg` 沒寫」。
`ioreg` 是唯讀查詢工具，這一句是讀過它的用途之後的判斷，不是量到的。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import contract as C          # noqa: E402
import runtimenode as R       # noqa: E402

from test_forseti_dir_writes import _WriteSpy   # noqa: E402

#: 注入用的假硬體 UUID。真的那個不寫進測試檔。
FAKE_A = "AAAAAAAA-1111-2222-3333-444444444444"
FAKE_B = "BBBBBBBB-1111-2222-3333-444444444444"


# --------------------------------------------------------------- node_id

def test_同一台機器跨行程算出同一個node_id():
    """兩個獨立的 python 行程，同一個值。

    **這條證的是跨行程，不是跨重開機。** 跨重開機靠的是
    IOPlatformUUID 自己的性質，這一組沒有量過它，
    模組檔頭也是這樣寫的。
    """
    code = ("import sys;sys.path.insert(0, %r);"
            "import runtimenode;print(runtimenode.node_id())"
            % str(ROOT / "apps" / "forseti-cli"))
    got = []
    for _ in range(2):
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        got.append(r.stdout.strip())
    assert got[0] == got[1], got
    assert got[0].startswith("node-"), got[0]


def test_node_id跟著硬體UUID變():
    """換一個 UUID 就換一個 id。

    沒有這一條的話，一個永遠回固定字串的實作會通過上面那條一致性測試。
    """
    assert R.node_id(uuid=FAKE_A) != R.node_id(uuid=FAKE_B)
    assert R.node_id(uuid=FAKE_A) == R.node_id(uuid=FAKE_A)


def test_取不到硬體UUID就退回hostname而且basis說得出來():
    m = R.measure(uuid=None, host="某台機器")
    assert m["basis"] == "hostname"
    assert R.measure(uuid=FAKE_A, host="某台機器")["basis"] == "IOPlatformUUID"


def test_退回hostname的那一種會在改機器名字的時候換id():
    """basis 那一欄不是裝飾品，它標示的是兩種不同的穩定度。"""
    a = R.node_id(uuid=None, host="機器甲")
    b = R.node_id(uuid=None, host="機器乙")
    assert a != b
    # 有 UUID 的時候換機器名字不影響 id —— 這才是它比較穩的原因。
    assert (R.node_id(uuid=FAKE_A, host="機器甲")
            == R.node_id(uuid=FAKE_A, host="機器乙"))


def test_硬體UUID原值不會出現在輸出裡():
    """存的是雜湊。原值是硬體序號等級的東西，而輸出會進 git 追蹤的檔案。"""
    blob = json.dumps(R.describe(uuid=FAKE_A), ensure_ascii=False)
    assert FAKE_A not in blob
    assert FAKE_A.lower() not in blob.lower()


# --------------------------------------------------------- 空的那三欄

def test_六欄一欄都不少而且順序照規格():
    """省略掉的欄位跟從來沒有這個欄位長得一模一樣。"""
    assert tuple(R.fields(uuid=FAKE_A)) == R.SPEC_FIELDS
    assert R.SPEC_FIELDS == ("node_id", "host", "process",
                             "service", "version", "health")


def test_health永遠是空的而且說得出為什麼():
    """沒探測就不給燈。一個沒有被檢查過的綠燈比沒有燈更糟。"""
    h = R.fields(uuid=FAKE_A)["health"]
    assert h["value"] is None
    assert h["origin"] == R.ORIGIN_NONE
    assert "健康端點" in h["why"]


def test_service是空的而且理由指得到B_05():
    s = R.fields(uuid=FAKE_A)["service"]
    assert s["value"] is None
    assert "B-05" in s["why"]


def test_version沒有被作業系統版本頂替():
    """**這一條守的是這個 repo 的慣犯**：名字對上不等於東西對上。

    作業系統版本量得到，而且就在同一個 dict 裡。把它接到 `version`
    那一欄是最順手的動作，也正是 `contract.py` 已經記過一次的那個形狀
    （「jsonl 的 version 是 CLI 版本不是模型版本」）。
    """
    d = R.describe(uuid=FAKE_A)
    osv = d["measured"]["host"]["os_version"]
    assert osv, "作業系統版本這一次沒量到，那這條測試證不到任何東西"
    assert d["fields"]["version"]["value"] is None
    assert d["fields"]["version"]["value"] != osv


def test_describe講得出哪幾欄是空的():
    d = R.describe(uuid=FAKE_A)
    assert set(d["unfilled"]) == {"service", "version", "health"}
    assert set(d["filled"]) == {"node_id", "host", "process"}
    assert set(d["filled"]) | set(d["unfilled"]) == set(R.SPEC_FIELDS)


# --------------------------------------------------------------- 不寫檔

def test_量的時候一個檔都不寫():
    """範圍是整個檔案系統，不只 `.forseti/`。

    攔不到子行程，見檔頭最後一段。
    """
    with _WriteSpy(scope=None) as spy:
        R.describe()
        R.reference()
    assert spy.paths() == set(), sorted(spy.paths())


# ------------------------------------------------------------- contract

def test_contract那一欄不再是沒有來源():
    v = C.check(C.collect({}))["groups"]
    fields = {f["key"]: f for g in v for f in g["fields"]}
    rn = fields["runtime_node"]
    assert rn["status"] == C.STATUS_PRESENT, rn
    assert "node-" in rn["shown"], rn["shown"]


def test_contract接的是reference不是describe():
    """接 `describe()` 會把 §5 的實體完整度混進 §39.1 的這一欄。

    兩張表問的不是同一件事：§39.1 問「是哪一台」，§5 問「這個實體
    有沒有六欄」。混在一起的話，讀的人會以為系統不知道跑在哪台機器上，
    而實情是知道。
    """
    v = C._runtime_node()
    # 先問型別再問內容。不先問的話，回一個非 dict 的東西會讓這一條
    # 丟 TypeError 而不是斷言失敗 —— 而那兩種紅在輸出上長得一樣
    # （§40 pol-240e178980 就是這一輪登的這件事）。
    assert isinstance(v, dict), f"要的是 dict，拿到 {type(v).__name__}：{v!r}"
    assert set(v) == {"node_id", "host", "basis"}, v
    assert "fields" not in v and "unfilled" not in v


def test_runtimenode跑失敗的時候回沒有來源不回假值(monkeypatch):
    """這一支自己壞掉，跟這台機器沒有識別碼，是兩件事。"""
    monkeypatch.setattr(R, "reference",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("壞了")))
    v = C._runtime_node()
    assert isinstance(v, C.NoSource)
    assert "壞了" in v.why


def test_target_environment那句理由沒有繼續說RuntimeNode沒有實作():
    """理由腐爛是這個 repo 付過代價的病，見 `contract.Recheck` 的檔頭。

    那一欄先前的理由寫著「§12.1 的 Project → RuntimeNode 那一層
    沒有實作」。RuntimeNode 那一端做出來之後，那句話只剩一半是真的。
    """
    ctx = C.collect({})
    te = ctx["target_environment"]
    assert isinstance(te, C.NoSource)
    assert "那一層沒有實作" not in te.why
    assert "runtimenode" in te.why


# ── basis 的兩個值有名字。2026-09-17 21:xx ────────────────────────
#
# 取名字不是整理，是因為外面有人要問「這個 id 穩不穩」
# （`contract.coordinate_lines()` 靠它決定印不印那句警告）。
# 比對字面字串的那一種寫法，在這裡改一個字就會靜默失效，
# 而症狀是畫面上少一句警告 —— 少一句不會紅，所以沒有人會發現。

def test_兩個basis常數真的被measure用到():
    assert R.measure(uuid="U-1")["basis"] == R.BASIS_UUID
    assert R.measure(uuid=None, host="h1")["basis"] == R.BASIS_HOSTNAME


def test_basis只有這兩種():
    """第三種值出現的時候這條要紅。

    多一種而外面不知道的話，那句警告的條件（不是 UUID 就警告）
    會把新的那種也當成不穩，或反過來漏掉。
    """
    assert {R.measure(uuid="U-1")["basis"],
            R.measure(uuid=None, host="h")["basis"]} == {
        R.BASIS_UUID, R.BASIS_HOSTNAME}
