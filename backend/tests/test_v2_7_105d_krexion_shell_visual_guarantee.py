"""v2.7.105d — Krexion phone chrome visual guarantee (embed + strict + early)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_shell_module_has_embed_apis():
    import krexion_mobile_browser_shell as shell

    assert hasattr(shell, "is_mobile_shell_embedded")
    assert hasattr(shell, "wait_for_mobile_shell_embedded")
    assert hasattr(shell, "mark_mobile_shell_embedded")
    assert hasattr(shell, "preflight_mobile_shell")
    assert hasattr(shell, "mobile_shell_status")
    pf = shell.preflight_mobile_shell()
    assert "ok" in pf and "windows" in pf
    # Non-Windows CI: preflight must fail closed with a clear reason
    if not shell._IS_WINDOWS:
        assert pf["ok"] is False
        assert "Windows" in (pf.get("error") or "")


def test_launcher_waits_for_embed_and_early_shell():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "wait_for_mobile_shell_embedded" in src
    assert "require_embed" in src
    assert "early Krexion phone chrome" in src.lower() or "Early Krexion phone chrome" in src
    assert "except RuntimeError" in src
    # Strict abort must not be swallowed by bare Exception
    assert "Strict mobile shell" in src
    assert "mobile_shell_embedded" in src
    assert "preflight_mobile_shell" in src


def test_strict_mobile_default_on_for_mobile_profiles():
    from browser_profile_module import AntiDetectConfig, _public_view

    assert AntiDetectConfig().strict_mobile_shell is True
    view = _public_view({
        "id": "p1",
        "user_id": "u",
        "name": "m",
        "is_mobile": True,
        "anti_detect": {},
        "proxy": {},
    })
    assert view.get("strict_mobile_shell") is True


def test_shell_apply_loop_marks_embedded():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "mark_mobile_shell_embedded" in src
    assert '"engine_embedded": False' in src or "'engine_embedded': False" in src


def test_frontend_strict_mobile_default_and_honesty():
    fe = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    )
    src = fe.read_text(encoding="utf-8")
    assert "strict_mobile_shell: true" in src
    assert "mobile_shell_embedded" in src
    assert "bp-mobile-honesty" in src
    assert "plain Chromium/WebKit" in src or "Chromium/WebKit" in src


def test_session_bridge_clears_embedded_flag():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "mobile_shell_embedded" in src
    assert 'prof_update["mobile_shell_embedded"] = False' in src
