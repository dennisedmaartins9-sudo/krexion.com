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
    # Early + post-nav branding (kwargs may span lines)
    assert "mobile_shell=True" in src
    assert "_brand_krexion_taskbar(mobile_shell=False)" not in src
    assert "Early Krexion phone chrome" in src or "post-nav" in src.lower()
