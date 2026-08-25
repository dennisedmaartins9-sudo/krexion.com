"""v2.7.11 — Krexion taskbar icon branding for headed Browser Profiles."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_icon_module_uses_appusermodel_relaunch():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "PKEY_AppUserModel_RelaunchIconResource" in src
    assert "PKEY_AppUserModel_ID" in src
    assert "SHGetPropertyStoreForWindow" in src
    assert "Krexion.BrowserProfile" in src
    assert r"C:\Program Files\Krexion\krexion.ico" in src


def test_launcher_rebrands_after_first_page():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_brand_krexion_taskbar" in src
    assert src.count("_brand_krexion_taskbar()") >= 2
