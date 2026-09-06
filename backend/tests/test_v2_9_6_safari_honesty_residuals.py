"""v2.9.6 — Safari/iOS Open honesty + Electron WebKit + Sync engine infer."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_9_6():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.6")


def test_launcher_blocks_silent_ios_chromium_swap():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_safari_intent = bool(_webkit_profile)" in src
    assert "Open will NOT silently switch to Cloak Chromium." in src
    safari_block = src.split("_safari_intent = bool(_webkit_profile)")[1].split("else:")[0]
    assert "_normalize_mobile_ua_for_visit" not in safari_block
    assert '_profile_engine = "webkit"' in safari_block
    assert "_webkit_runtime_available" in safari_block


def test_create_persists_browser_engine_and_keeps_ios():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"browser_engine": _browser_engine' in src
    assert 'requested_os in ("ios", "iphone", "ipad")' in src
    assert 'os_val = "ios"' in src
    # Android UA + requested ios stays coherent (v2.7.8) — not blind force.
    assert "_ua_is_android" in src
    assert '_anti.setdefault("browser_engine", _browser_engine)' in src


def test_sync_infers_webkit_from_os_or_ua():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    fn = src.split("def _engine_of(doc: dict)")[1].split(
        "# v2.9.4 — WebKit / Krexion Safari"
    )[0]
    assert 'os") or "").lower() in ("ios"' in fn
    assert "_ua_prefers_webkit" in fn


def test_electron_installs_webkit():
    js = (REPO / "electron-desktop" / "scripts" / "prepare-resources.js").read_text(
        encoding="utf-8"
    )
    assert "need.push('webkit')" in js or 'need.push("webkit")' in js
    assert "required for Krexion Safari / iOS profiles" in js
