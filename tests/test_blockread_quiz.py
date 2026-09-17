"""出題器。接手閘門的題目從這裡來，所以這裡漏掉的等於閘門漏掉。

2026-09-16 踩到的事：`.forseti/NEXT.md` 多了一行摘要
「有值但不滿足規格要求：2」，`_RULEY` 命中「要求」、`_NUM` 抽到 `2`，
於是接手閘門出了一題**答案是「2」的填空**。

`grade()` 比的是「原文的 key 有沒有出現在答案裡」，所以一個只有一個
字元的 key 幾乎在任何一句話裡都找得到。那題答對答錯跟有沒有讀懂
那一行完全無關，而它照樣算進通過門檻。

**跟 owner 2026-09-14 當場考出來的那件事是同一種病**：原本禁令題的
key 抽的是「不准」兩個字，於是那題變成「你會不會把『不准』打出來」。
禁令那一支後來用 `len(tail) >= 4` 擋掉了，數字這一支沒有。

這一組把數字這一支也釘住。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import blockread as BR  # noqa: E402


def _quiz(tmp_path, body: str) -> list:
    p = tmp_path / "doc.md"
    p.write_text(body, encoding="utf-8")
    blk = BR.Block(index=0, title="t", level=1, lo=1,
                   hi=len(body.splitlines()))
    return BR.quiz(p, blk)


def test_單字元答案不出題(tmp_path):
    """答案只有一個字元的題目擋不住任何人，所以不准出。"""
    qs = _quiz(tmp_path, "# t\n- 有值但不滿足規格要求：2\n")
    assert [q for q in qs if q["kind"] == "數字" and len(q["key"]) < 2] == []


def test_兩位數以上的規定照樣出得了題(tmp_path):
    """擋掉退化情形不可以順手把正常的題目也擋掉。"""
    qs = _quiz(tmp_path, "# t\n這一項規定至少要 12 份文件才算數。\n")
    nums = [q for q in qs if q["kind"] == "數字"]
    assert nums, "正常的數字規定該出得了題"
    assert nums[0]["key"] == "12"


def test_出出來的題答案都夠長到能分辨(tmp_path):
    """對整支的守備：任何題型都不准回單字元答案。"""
    body = ("# t\n"
            "- 有值但不滿足規格要求：2\n"
            "這一條規定最多 3 次。\n"
            "這一條規定上限是 48 小時。\n")
    for q in _quiz(tmp_path, body):
        assert len(q["key"]) >= 2, (q["kind"], q["key"])


def test_單字元的key在grade裡幾乎一定會過():
    """把「為什麼不准出那種題」寫成可執行的證據。

    這一條不是在驗 `grade()` 壞掉 —— 它的比對方式本來就是包含。
    它證明的是：**只要題目出得出單字元的 key，閘門就形同虛設**，
    所以防線必須放在出題那一端。
    """
    q = {"key": "2", "line": 1, "kind": "數字"}
    for said in ("大概是講2那件事", "我不知道，可能是 2 吧", "隨便寫 12 個字"):
        assert BR.grade(q, said)["ok"] is True, said


def test_夠長的key擋得住亂answer():
    q = {"key": "grep 找答案", "line": 1, "kind": "禁令"}
    assert BR.grade(q, "大概是講gr那件事")["ok"] is False
    assert BR.grade(q, "不准 grep 找答案")["ok"] is True


def test_識別碼裡的數字不出題(tmp_path):
    """`B-08` 的 08 是這條阻塞的名字，不是它規定的值。

    2026-09-16 18:5x：`.forseti/NEXT.md` 新增阻塞那一節之後，
    「- B-08　擋住：階段 0 的其中一半」被出成一題答案是「08」的填空，
    而「大概是講08那件事」這種含糊回答照樣算對
    （`tests/test_gate.py::test_不做語意相似度` 當場變紅）。

    這是同一種病的第三個變體，前兩個是禁令詞與單字元數字。
    """
    qs = _quiz(tmp_path, "# t\n- B-08　擋住：階段 0 的其中一半，至少要 3 份。\n")
    assert [q for q in qs if q["key"] == "08"] == [], "編號不是規定值"


def test_排除識別碼不可以順手排掉同一行的真數字(tmp_path):
    """擋掉退化情形不准把旁邊正常的規定也擋掉。"""
    qs = _quiz(tmp_path, "# t\n- B-08 這一條規定至少要 24 份文件。\n")
    nums = [q for q in qs if q["kind"] == "數字"]
    assert nums and nums[0]["key"] == "24"


def test_F01這種沒有連字號的編號也算識別碼(tmp_path):
    qs = _quiz(tmp_path, "# t\n- F01 規定至少要有一份，不得省略。\n")
    assert [q for q in qs if q["key"] == "01"] == []
