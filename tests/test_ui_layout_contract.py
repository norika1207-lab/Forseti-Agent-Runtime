#!/usr/bin/env python3
"""離線窄視窗幾何契約。

這組不啟動瀏覽器，也不把「DOM 裡有這個 class」當成排版驗證。
它從實際 app.css 讀出區域邊界，對 screenshot 對應的兩個 viewport
做可重現的 pixel arithmetic：header、scroll、footer 必須是連續的
grid 區域，最後一張卡必須留在 footer clearance 之上。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


CSS = (Path(__file__).resolve().parents[1] / "desktop" / "ui" / "app.css").read_text(
    encoding="utf-8"
)


def _root_value(name: str) -> int:
    root = re.search(r":root\{(.*?)\n\}", CSS, re.S)
    if not root:
        raise AssertionError("app.css 沒有可讀的 :root token")
    match = re.search(rf"{re.escape(name)}:(\d+)px", root.group(1))
    if not match:
        raise AssertionError(f"找不到 {name} 的 pixel token")
    return int(match.group(1))


class NarrowViewportGeometry(unittest.TestCase):
    """672x1380 與 390x844 都不可讓上層或 footer 蓋住主內容。"""

    VIEWPORTS = ((672, 1380), (390, 844))

    def test_grid_has_a_real_scroll_track_between_header_and_footer(self):
        self.assertIn(
            ".w{display:grid;grid-template-rows:auto minmax(0,1fr) auto;",
            CSS,
        )
        self.assertIn("min-height:100dvh;overflow:hidden", CSS)
        self.assertIn(".scroll{min-height:0;overflow-y:auto", CSS)
        self.assertIn(".bottom{display:flex", CSS)
        self.assertIn("position:relative;z-index:20", CSS)

        footer_min = _root_value("--layout-footer-min")
        clearance = _root_value("--layout-footer-clearance")
        self.assertGreaterEqual(clearance, footer_min + 16)

        for width, height in self.VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                header_cap = min(height * 0.52, 460)
                footer_top = height - footer_min
                scroll_height = footer_top - header_cap
                self.assertGreaterEqual(footer_top, header_cap)
                self.assertGreater(scroll_height, clearance)

    def test_open_analysis_panel_is_bounded_and_in_normal_flow(self):
        self.assertIn(
            ".top{max-height:min(52vh,460px)}", CSS
        )
        self.assertIn(
            ".panel:not([hidden]){max-height:calc(min(52vh,460px) - 64px);",
            CSS,
        )
        self.assertIn(
            "overflow-y:auto;overscroll-behavior:contain}",
            CSS,
        )
        media = CSS[CSS.index("@media (max-width:760px)") :]
        panel = media[media.index(".panel:not([hidden])") :]
        self.assertNotIn("position:fixed", panel.split("}", 1)[0])

    def test_lane_has_footer_clearance_and_cards_use_available_width(self):
        self.assertIn(
            ".lane{padding:18px 0 var(--layout-footer-clearance);position:relative}",
            CSS,
        )
        self.assertIn(".cards{padding-left:12px;padding-right:12px}", CSS)
        self.assertIn(
            ".card2{width:100%;min-width:0;overflow-wrap:anywhere}",
            CSS,
        )
        self.assertIn(".card2 .row{flex-wrap:wrap}", CSS)

    def test_each_viewport_has_non_overlapping_content_budget(self):
        """這是 geometry assertion，不只是字串 presence assertion。"""
        footer_min = _root_value("--layout-footer-min")
        clearance = _root_value("--layout-footer-clearance")
        for width, height in self.VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                header_bottom = min(height * 0.52, 460)
                footer_top = height - footer_min
                last_card_safe_bottom = footer_top - clearance
                self.assertGreater(last_card_safe_bottom, header_bottom)
                self.assertGreaterEqual(
                    footer_top - last_card_safe_bottom, footer_min + 16
                )


if __name__ == "__main__":
    unittest.main()
