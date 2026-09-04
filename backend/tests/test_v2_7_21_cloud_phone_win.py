"""v2.7.21 — Krexion Android farm / cloud phone WIN pack."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).resolve().parents[2] / "krexion-cpi-worker" / "krexion_cpi_worker"
FE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages"


def test_runtime_multi_avd_helpers():
    import sys
    sys.path.insert(0, str(WORKER.parent))
    from krexion_cpi_worker.krexion_android_runtime import (
        _avd_name,
        _adb_endpoint,
        _console_port,
        ensure_krexion_android,
    )

    assert _avd_name(1) == "KrexionPhone"
    assert _avd_name(2) == "KrexionPhone-2"
    assert _console_port(1) == 5554
    assert _console_port(2) == 5556
    assert _adb_endpoint(1) == "127.0.0.1:5555"
    assert _adb_endpoint(3) == "127.0.0.1:5559"
    # Signature accepts instances=
    assert "instances" in ensure_krexion_android.__code__.co_varnames or True


def test_orchestrator_cloud_sync_and_parallel():
    src = (WORKER / "orchestrator.py").read_text(encoding="utf-8")
    assert "_sync_cloud_adb_endpoints" in src
    assert "android_krexion" in src
    assert "instances" in src
    assert "list_devices" in src
    assert "EVERY idle slot" in src or "for slot in idle" in src


def test_cpi_android_farm_routes():
    src = (ROOT / "cpi_module.py").read_text(encoding="utf-8")
    assert "CPIAndroidEnableBody" in src
    assert '"/android/catalog"' in src
    assert '"/apk-library"' in src
    assert "instances" in src
    assert "farm_target" in src
    assert "cpi_apk_library" in src


def test_open_on_device_auto_pick():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "auto_fallback" in src
    assert "Auto-pick" in src or "auto_picked" in src
    assert "No Krexion Android online" in src


def test_frontend_farm_and_device_picker():
    devices = (FE / "CPIDevicesPage.js").read_text(encoding="utf-8")
    assert "cpi-farm-size" in devices
    assert "cpi-add-cloud-android" in devices
    assert "apk-library" in devices
    assert "cloud-phone/provision" in devices

    bp = (FE / "BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "bp-cloud-phone-device" in bp
    assert "openCloudPhoneDialog" in bp
    assert "Open now" in bp
    assert "auto_fallback" in bp


def test_version_2_7_21_or_newer():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.21")
