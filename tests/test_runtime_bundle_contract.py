import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_desktop_bundle_contains_self_contained_python_runtime():
    config = json.loads(
        (ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    resources = config["bundle"]["resources"]

    assert resources["../../apps/forseti-cli"] == "runtime/apps/forseti-cli"
    for source in ("../../src", "../../tools", "../../docs", "../../.forseti"):
        assert source in resources


def test_installed_runtime_precedes_external_drive_fallback():
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text(encoding="utf-8")
    bundled = source.index('contents.join("Resources/runtime")')
    external = source.index('PathBuf::from("/Volumes/NewDrive/AI Project/Forseti")')

    assert bundled < external
    assert 'p.join("apps/forseti-cli").is_dir()' in source
    assert 'repo.join("apps/forseti-cli/desktop_api.py")' in source


def test_session_surface_uses_the_same_runtime_root_as_desktop_api():
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text(encoding="utf-8")
    start = source.index("fn run_session_surface")
    end = source.index("\n#[tauri::command]", start)
    body = source[start:end]

    assert "let repo = find_repo()" in body
    assert 'repo.join("apps/forseti-cli/session_surface.py")' in body
    assert 'Resources/forseti-cli/session_surface.py' not in body


def test_native_titlebar_drag_region_has_permission():
    config = json.loads(
        (ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    permissions = config["app"]["security"]["capabilities"][0]["permissions"]
    html = (ROOT / "desktop/ui/index.html").read_text(encoding="utf-8")

    assert "core:window:allow-start-dragging" in permissions
    assert 'class="top" data-tauri-drag-region' in html
