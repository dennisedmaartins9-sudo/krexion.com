"""v2.7.130 — AdsPower-parity Krexion profile list design."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_130():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.130")


def test_backend_exposes_profile_no_fields():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "serial_number" in src
    assert "custom_no" in src
    assert "profile_no" in src
    assert "_ensure_profile_serial" in src


def test_fe_default_table_and_adspower_columns():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert 'return "table"' in fe or 'krexion_bp_view' in fe
    assert "bp-dense-table-wrap" in fe or "bp-dense-layout" in fe
    assert ">No.<" in fe or ">No.</" in fe
    assert ">Proxy<" in fe
    assert ">Last open<" in fe or "Last open" in fe
    assert "formatProxyCompact" in fe
    assert "profileNoLabel" in fe
    assert "New Profile" in fe
    # Open/Close AdsPower verbs in primary actions
    assert "/> Open" in fe or "> Open<" in fe or "/> Open\n" in fe or "> Open" in fe
    assert "> Close" in fe or "/> Close" in fe
    # No AdsPower vendor string in customer UI
    assert "AdsPower" not in fe
    # Branding stays Krexion
    assert "Krexion Browser Profiles" in fe


def test_hero_not_marketing_gradient_title():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "🌐 Browser Profiles" not in fe
    assert "from-fuchsia-400 via-purple-400 to-cyan-400" not in fe or "Krexion Browser Profiles" in fe
