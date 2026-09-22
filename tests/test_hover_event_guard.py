from pathlib import Path


JS = (Path(__file__).parents[1] / "desktop" / "ui" / "app.js").read_text(
    encoding="utf-8"
)


def test_tooltip_uses_pointer_events_not_mouseover_storm():
    assert 'document.addEventListener("pointerover"' in JS
    assert 'document.addEventListener("mouseover"' not in JS
    assert 'document.addEventListener("pointerout"' in JS


def test_tooltip_skips_rebuilding_for_same_dot_target():
    assert "let tipDot = null;" in JS
    assert "if (d === tipDot) return;" in JS
    assert "tipDot = d;" in JS
