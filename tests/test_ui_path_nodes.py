#!/usr/bin/env python3
"""Point clicks must explain their own turn or event, not repeat line hover."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "ui-render-check.py"
spec = importlib.util.spec_from_file_location("forseti_ui_path_harness", HARNESS)
RC = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = RC
spec.loader.exec_module(RC)
BASE_HARNESS = RC._load_harness()


class IsolatedHarness:
    """Browser shell with synthetic data only; never calls desktop_api.strands."""

    def __init__(self, snap: dict, click_selector: str | None = None) -> None:
        self.snap = snap
        self.click_selector = click_selector

    def build(self, out: Path, fake: bool, session: str = "") -> None:
        ui = ROOT / "desktop" / "ui"
        for name in ("app.css", "app.js", "index.html"):
            shutil.copy2(ui / name, out / name)
        fixture = {"strands": self.snap,
                   "snapshot": {}, "sessions": [], "work": {}, "machine": {},
                   "features": {}, "selftest": {}, "audit": {}, "fork": {"error": "test"}}
        (out / "fixture.json").write_text(json.dumps(fixture, ensure_ascii=False),
                                          encoding="utf-8")
        html = (ui / "index.html").read_text(encoding="utf-8")
        stub = BASE_HARNESS.STUB.replace(
            '<script src="app.js"></script>',
            '<script>window.__TAURI__.event = {listen: async () => () => {}};</script>'
            '<script src="app.js"></script>')
        html = html.replace('<script src="app.js"></script>', stub)
        if self.click_selector:
            selector = json.dumps(self.click_selector)
            click_script = (
                '<script>const pointClick = new MutationObserver(() => {'
                f'const point = document.querySelector({selector});'
                'if (point) { pointClick.disconnect(); '
                'point.dispatchEvent(new MouseEvent("click", {bubbles:true})); }'
                '}); pointClick.observe(document, {childList:true, subtree:true});</script>')
            html = html.replace('</body>', click_script + '</body>')
        blob = json.dumps(fixture, ensure_ascii=False).replace("<", "\\u003c")
        html = html.replace("</head>",
                            '<script type="application/json" id="fx">' + blob + '</script>\n</head>')
        (out / "index.html").write_text(html, encoding="utf-8")


def marker(dom: str) -> str:
    matches = re.findall(r'<section\b[^>]*>.*?</section>', dom, re.S)
    match = next((item for item in matches if 'id="nodeMarker"' in item.split('>', 1)[0]), None)
    if not match:
        raise AssertionError("node marker panel was not rendered")
    return match


class PathPointClick(unittest.TestCase):
    def setUp(self):
        if not RC.find_chrome():
            self.skipTest("Chrome unavailable; browser click not verified")
        def row(n, label, why, evidence):
            return {"n": n, "started_at": n, "duration": 5,
                    "owner_text": f"Owner request {n}", "ai_text": f"AI answer {n}",
                    "dots": [], "gaps": [], "goal": {}, "notes": [],
                    "activity": [], "support": [], "betrayals": [], "claims": [],
                    "path_semantics": {"state": "suspected", "label": label,
                                       "actor": "AI", "epistemic": "INFERRED",
                                       "why": why, "evidence": evidence}}
        self.snap = {"rows": [row(1, "First state", "First reason", "First proof"),
                              row(2, "Second state", "Second reason", "Second proof")],
                     "cards": [], "session": "synthetic", "strands": 2, "shown": 2}
        self.snap["rows"][1]["decision_comparison"] = {
            "state": "POSSIBLE_DIFFERENCE", "epistemic": "INFERRED",
            "baseline_n": 1, "current_n": 2,
            "baseline_source_ref": "line:10", "evidence_source_ref": "line:20",
            "baseline": "Previous approach", "evidence": "New decision",
            "why": "Changed choice, not an AI drift verdict"}
        self.snap["rows"][1]["betrayals"] = [{
            "title": "AI claim needs review", "grade": "CANDIDATE",
            "why": "Claim lacks a tool record", "hit": "I wrote config.json",
            "target": "config.json", "fp": "FP-11", "advice": "Check the file"}]
        self.snap["rows"][1]["drift_alert"] = {
            "state": "SUSPECTED_DRIFT", "n": 2, "from_n": 1, "turns": 2,
            "from_distance": 0.2, "distance": 0.5, "confidence": 0.6,
            "goal_anchor_ref": "v1", "gac": 0.55,
            "excluded": ["owner change checked"], "prompt": "Review current goal"}
        self.snap["rows"][1]["notes"] = [{"text": "Owner note for this turn", "at": 2}]

    def shot(self, selector=None, snap=None):
        with tempfile.TemporaryDirectory(prefix="forseti-point-test-", dir=ROOT.parent) as tmp:
            with patch.object(RC, "_load_harness", return_value=IsolatedHarness(snap or self.snap, selector)):
                result = RC.render(fake=False, outdir=Path(tmp),
                                   budget_ms=7000)
            self.assertFalse(any("Uncaught" in line for line in result.console), result.console)
            return result.dom

    def test_large_path_point_has_turn_verdict_and_neighbor_context(self):
        point = marker(self.shot(".drift circle.node:last-of-type"))
        self.assertNotIn('hidden=""', point.split(">", 1)[0])
        self.assertIn("第 2 輪 · Second state", point)
        self.assertIn("判定責任：AI · 證據等級：INFERRED", point)
        self.assertIn("前一輪「First state」→ 本輪「Second state」", point)
        self.assertIn("本輪判定依據：Second proof", point)
        card = marker(self.shot('.st[data-n="2"] .body'))
        self.assertIn('hidden=""', card.split(">", 1)[0])

    def test_gold_event_point_has_comparison_not_path_verdict(self):
        point = marker(self.shot('.st[data-n="2"] .eventMark.gold'))
        self.assertIn("第 2 輪 · 決策模式提醒", point)
        self.assertIn("過去的做法：Previous approach", point)
        self.assertIn("本輪決策：New decision", point)
        self.assertIn("來源：line:10 → line:20", point)
        self.assertIn("推論級參考", point)
        self.assertNotIn("前一輪「First state」", point)

    def test_white_event_point_shows_its_own_claim_receipt(self):
        point = marker(self.shot('.st[data-n="2"] .eventMark.white'))
        self.assertIn("查證等級：CANDIDATE", point)
        self.assertIn("命中原文：I wrote config.json", point)
        self.assertIn("對應規則：FP-11", point)
        self.assertNotIn("Second proof", point)

    def test_purple_event_point_uses_alert_metrics_not_path_evidence(self):
        point = marker(self.shot('.st[data-n="2"] .eventMark.purple'))
        self.assertIn("目標距離 0.2 → 0.5", point)
        self.assertIn("目標錨點：v1 · GAC：0.55", point)
        self.assertIn("owner change checked", point)
        self.assertNotIn("Second proof", point)

    def test_pink_event_point_shows_only_the_selected_note(self):
        point = marker(self.shot('.st[data-n="2"] .eventMark.pink'))
        self.assertIn("Owner note for this turn", point)
        self.assertNotIn("Second proof", point)

    def test_no_gold_dot_without_producer_field(self):
        self.snap["rows"][1].pop("decision_comparison")
        dom = self.shot()
        self.assertNotIn('class="eventMark gold"', dom)

    def test_gold_dot_rejects_unclassified_comparison(self):
        self.snap["rows"][1]["decision_comparison"].pop("epistemic")
        self.assertNotIn('class="eventMark gold"', self.shot())

    def test_gold_dot_rejects_missing_source_refs(self):
        self.snap["rows"][1]["decision_comparison"].pop("baseline_source_ref")
        self.assertNotIn('class="eventMark gold"', self.shot())

    def test_old_goal_reference_only_after_confirmed_goal_version(self):
        for state in ("exploratory", "temporary"):
            with self.subTest(state=state):
                self.snap["rows"][1]["path_semantics"]["state"] = state
                self.assertNotIn('data-reference="north-star"', self.shot())
        self.snap["rows"][1]["path_semantics"]["state"] = "new_direction"
        self.assertIn('data-reference="north-star"', self.shot())

    def test_each_sideband_compaction_opens_its_own_receipt(self):
        self.snap["compaction_events"] = [
            {"ordinal": 1, "n": 2, "line": 101, "at": 1000,
             "label": "對話壓縮", "size": 6},
            {"ordinal": 2, "n": 2, "line": 205, "at": 2000,
             "label": "對話壓縮", "size": 6},
        ]
        self.assertEqual(len(self.snap["rows"]), 2)
        self.assertEqual(self.snap["rows"][1]["dots"], [])
        dom = self.shot()
        self.assertEqual(dom.count('class="eventMark compaction"'), 2)
        first = marker(self.shot('.st[data-n="2"] .eventMark.compaction'))
        second = marker(self.shot('.st[data-n="2"] .eventMark.compaction + .eventMark.compaction'))
        self.assertIn("第 1 次 · 對話壓縮", first)
        self.assertIn("原始紀錄第 101 行", first)
        self.assertNotIn("原始紀錄第 205 行", first)
        self.assertIn("第 2 次 · 對話壓縮", second)
        self.assertIn("原始紀錄第 205 行", second)
        self.assertNotIn("原始紀錄第 101 行", second)

    def test_compaction_marks_are_not_inferred_from_row_or_tool_dots(self):
        self.snap["rows"][1]["dots"] = [{"label": "對話壓縮", "count": 2}]
        self.snap["rows"][1]["compaction_meta"] = {"events": [
            {"ordinal": 1, "n": 2, "line": 101, "at": 1000, "size": 6}]}
        self.assertNotIn('class="eventMark compaction"', self.shot())

    def test_69_sideband_events_remain_separate_without_covering_next_turn(self):
        self.snap["compaction_events"] = [
            {"ordinal": i, "n": 2, "line": 100 + i, "at": 1000 + i,
             "label": "對話壓縮", "size": 6}
            for i in range(1, 70)]
        dom = self.shot()
        self.assertEqual(dom.count('class="eventMark compaction"'), 69)
        row = re.search(r'<div class="st[^>]*data-n="2".*?</div>\s*<button class="body"', dom, re.S)
        self.assertIsNotNone(row)
        self.assertIn('min-height: 1905px', row.group(0))


if __name__ == "__main__":
    unittest.main()
