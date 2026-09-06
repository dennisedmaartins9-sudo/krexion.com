"""v2.7.19 — Silent Krexion Android + white-label (no third-party customer names)."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT.parent / "krexion-cpi-worker" / "krexion_cpi_worker"
FE = ROOT.parent / "frontend" / "src" / "pages"


def test_version():
    from releases_module import _parse as _semver_parse
    assert _semver_parse((ROOT / "VERSION").read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.19")


def test_runtime_module():
    src = (WORKER / "krexion_android_runtime.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "ensure_krexion_android" in src
    assert "Krexion Android" in src
    assert "LDPlayer" not in src
    assert "Genymotion" not in src


def test_orchestrator_auto_runtime():
    src = (WORKER / "orchestrator.py").read_text(encoding="utf-8")
    assert "_ensure_krexion_android" in src
    assert "_commands_loop" in src
    assert "auto_runtime" in src


def test_backend_enable_routes():
    src = (ROOT / "cpi_module.py").read_text(encoding="utf-8")
    assert '"/android/enable"' in src
    assert '"/android/status"' in src
    assert '"/worker/commands"' in src


def test_customer_ui_white_label():
    devices = (FE / "CPIDevicesPage.js").read_text(encoding="utf-8")
    setup = (FE / "CPIWorkerSetupPage.js").read_text(encoding="utf-8")
    bp = (FE / "BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "Enable Krexion Android" in devices
    assert "cpi-enable-krexion-android" in devices
    assert "LDPlayer" not in devices
    assert "Genymotion" not in devices
    assert "GeeLark" not in devices.lower()
    assert "LDPlayer" not in setup
    assert "Genymotion" not in setup
    assert "CloakBrowser" not in bp
    assert "AdsPower" not in bp
    assert "Octo" not in bp
    assert "Krexion Browser Stealth" in bp or "Krexion Stealth" in bp
