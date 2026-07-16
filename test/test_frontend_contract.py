"""成员 D 前端公共契约的静态回归检查。"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def test_base_template_loads_contract_modules_in_dependency_order():
    template = (BASE_DIR / "app/templates/base.html").read_text(encoding="utf-8")
    names = ["app-core.js", "sse-client.js", "card-renderer.js", "base.js"]
    positions = [template.index(name) for name in names]
    assert positions == sorted(positions)


def test_only_request_module_calls_fetch_directly():
    scripts = BASE_DIR / "app/static/js"
    direct_fetch_files = {
        path.name
        for path in scripts.glob("*.js")
        if "fetch(" in path.read_text(encoding="utf-8")
    }
    assert direct_fetch_files == {"app-core.js"}


def test_sse_event_names_match_frozen_contract():
    source = (BASE_DIR / "app/static/js/sse-client.js").read_text(encoding="utf-8")
    for event in ("meta", "delta", "card", "audio", "error", "done"):
        assert f'"{event}"' in source
    for legacy_event in ("status", "message", "usage", "conversation"):
        assert f'"{legacy_event}"' not in source


def test_user_and_model_pages_share_sse_client():
    user_script = (BASE_DIR / "app/static/js/user-workspace.js").read_text(encoding="utf-8")
    model_script = (BASE_DIR / "app/static/js/models.js").read_text(encoding="utf-8")
    assert "DataFinderSSE" in user_script
    assert "DataFinderSSE" in model_script
    assert "TextDecoder" not in user_script
    assert "TextDecoder" not in model_script
