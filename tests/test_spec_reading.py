"""必讀清單的判定。§40

這一支守的是 2026-09-15 撞到的一個真 bug：

`spec_reading()` 挑「最佳閱讀紀錄」時用嚴格大於比 `ratio`，
於是同樣是 1.0 的兩筆會留住舊的那筆。實際後果是
**「重新讀一次」永遠不算數** —— 檔案改過之後重讀並重新記錄，
狀態仍然停在「讀過但檔案已經變了」。

那一類 bug 跟這個專案在防的東西是同一類：看起來有在檢查，
實際上回的是舊答案。
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))


class BestRecordPicksTheLatest(unittest.TestCase):
    """同樣完整度的兩筆，要取時間較晚的那一筆。"""

    def _run(self, records, content="x\n"):
        """用一個臨時 repo 跑 spec_reading，回傳那份檔案的判定。"""
        import desktop_api as D
        import hashlib

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".forseti").mkdir()
            (repo / "docs").mkdir()
            target = repo / ".forseti" / "TARGET.md"
            target.write_text(content, encoding="utf-8")
            real = hashlib.sha256(target.read_bytes()).hexdigest()[:12]

            log = repo / ".forseti" / "reading_coverage.jsonl"
            with log.open("w", encoding="utf-8") as fh:
                for r in records:
                    r = dict(r)
                    r["path"] = str(target)
                    if r.pop("use_real_hash", False):
                        r["content_hash"] = real
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

            old_repo = D.REPO
            try:
                D.REPO = repo
                rows = D.spec_reading().get("rows") or []
            finally:
                D.REPO = old_repo
            return next((x for x in rows if x["name"] == "TARGET.md"), None)

    def test_a_later_record_with_the_same_ratio_wins(self):
        """舊的 hash 對不上，新的對得上。取新的，狀態要是「讀完」。"""
        row = self._run([
            {"at": 100.0, "ratio": 1.0, "level": "FULL_READ",
             "content_hash": "deadbeefdead"},
            {"at": 200.0, "ratio": 1.0, "level": "FULL_READ",
             "use_real_hash": True},
        ])
        self.assertIsNotNone(row, "必讀清單裡應該看得到這個檔案")
        self.assertEqual(row["state"], "讀完",
                         "重新讀過並記錄之後，狀態必須跟著更新")

    def test_a_higher_ratio_still_wins_over_a_later_one(self):
        """完整度仍然優先於時間。半讀的新紀錄不該蓋掉全讀的舊紀錄。"""
        row = self._run([
            {"at": 100.0, "ratio": 1.0, "level": "FULL_READ",
             "use_real_hash": True},
            {"at": 200.0, "ratio": 0.2, "level": "SAMPLED",
             "use_real_hash": True},
        ])
        self.assertEqual(row["state"], "讀完")

    def test_no_record_is_not_the_same_as_read(self):
        """沒有紀錄一律算沒讀。拿不出證據就不算讀過。"""
        row = self._run([])
        self.assertEqual(row["state"], "沒有閱讀紀錄")

    def test_a_changed_file_is_reported_not_silently_passed(self):
        """讀過但檔案變了要講出來，不能當成讀完。"""
        row = self._run([
            {"at": 100.0, "ratio": 1.0, "level": "FULL_READ",
             "content_hash": "0123456789ab"},
        ])
        self.assertEqual(row["state"], "讀過但檔案已經變了")


if __name__ == "__main__":
    unittest.main(verbosity=0)
