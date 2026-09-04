"""Installer Smart App Control / prereqs path tests."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISS = ROOT / "installer" / "krexion-setup.iss"
VERSION = ROOT / "backend" / "VERSION"


def test_version():
    from releases_module import _parse as _semver_parse
    assert _semver_parse(VERSION.read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.66")


def test_prereqs_not_tmp():
    text = ISS.read_text(encoding="utf-8")
    assert r"{app}\prereqs" in text.replace("{app}\\prereqs", r"{app}\prereqs")
    assert "vc_redist.x64.exe" in text
    assert r'{tmp}\vc_redist' not in text
    assert r'{tmp}\MicrosoftEdgeWebview2Setup' not in text


def test_sign_script_exists():
    p = ROOT / "scripts" / "sign-krexion-release.ps1"
    assert p.is_file()
    body = p.read_text(encoding="utf-8")
    assert "Get-AuthenticodeSignature" in body
    assert "KREXION_CODESIGN_PFX_PATH" in body
