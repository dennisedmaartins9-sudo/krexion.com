"""v2.7.6 — Anti-detect hardening checks (RUT + Browser Profiles)."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock

# real_user_traffic imports playwright at module load — stub for unit tests.
sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault(
    "playwright.async_api",
    MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    ),
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_version_is_2_7_6_or_newer():
    # Superseded by v2.7.7; keep hardening assertions, allow VERSION bump.
    ver = _read("VERSION").strip()
    assert ver in ("2.7.6", "2.7.7") or ver.startswith("2.7.")


def test_identity_store_has_pin_ua():
    from advanced_anti_detect import IdentityStore

    assert hasattr(IdentityStore, "pin_ua")
    src = inspect.getsource(IdentityStore.pin_ua)
    assert "anti_detect_identities.update_one" in src
    assert '"ua"' in src or "'ua'" in src


def test_stealth_script_webdriver_undefined_and_connection_type():
    import real_user_traffic as rut

    fp = rut._fingerprint_from_ua(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    )
    geo = {
        "timezone": "America/New_York",
        "accept_language": "en-US,en;q=0.9",
        "lat": 40.7,
        "lon": -74.0,
    }
    js = rut._build_stealth_script(fp, geo, skip_canvas_noise=True)
    assert "() => undefined" in js or "()=>undefined" in js.replace(" ", "")
    assert "__KX.connectionType" in js
    assert "Chrome PDF Viewer" in js
    assert "Microsoft Edge PDF Viewer" not in js
    assert "WebKit built-in PDF" not in js
    assert "__KX.skipCanvasNoise" in js or "skipCanvasNoise" in js
    assert "__KX.historyLength" in js
    assert "isChromiumUa" in js


def test_fingerprint_sets_chromium_and_history():
    import real_user_traffic as rut

    fp = rut._fingerprint_from_ua(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    )
    assert fp.get("is_chromium_ua") is True
    assert 2 <= int(fp.get("history_length") or 0) <= 5
    assert fp.get("connection_type") in ("wifi", "cellular")


def test_tls_targets_include_136():
    from tls_anti_detect import _CHROME_TARGETS, _pick_chrome_target, impersonate_for_ua

    assert 136 in _CHROME_TARGETS
    assert 133 in _CHROME_TARGETS
    assert _pick_chrome_target(136) == "chrome136"
    assert _pick_chrome_target(133) == "chrome133a"
    assert impersonate_for_ua("") == "chrome136"
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    )
    assert impersonate_for_ua(ua) == "chrome136"


def test_profile_tls_prewarm_default_false_in_source():
    src = _read("browser_profile_launcher.py")
    assert 'anti.get("tls_prewarm", False)' in src


def test_rut_apply_context_stealth_skips_canvas_noise():
    src = _read("real_user_traffic.py")
    # Path that injects stealth with skip_canvas_noise=True
    assert "skip_canvas_noise=True" in src
    assert "skip_canvas_noise: bool = False" in src


def test_pin_ua_and_headless_shell_gate_in_source():
    aad = _read("advanced_anti_detect.py")
    assert "async def pin_ua" in aad
    rut = _read("real_user_traffic.py")
    assert "KREXION_ALLOW_HEADLESS_SHELL" in rut
    assert "_pinned_ua" in rut


def test_build_stealth_script_parses():
    """Ensure the module still parses after large JS edits."""
    ast.parse(_read("real_user_traffic.py"))
    ast.parse(_read("anti_detect_v230.py"))
    ast.parse(_read("tls_anti_detect.py"))
