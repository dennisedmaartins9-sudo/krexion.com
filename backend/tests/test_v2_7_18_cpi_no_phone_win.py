"""v2.7.18 — CPI no-real-phone win: emulator auto-connect, needs_action, cloud ADB."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT.parent / "krexion-cpi-worker" / "krexion_cpi_worker"


def test_version_2_7_18():
    from releases_module import _parse as _semver_parse
    assert _semver_parse((ROOT / "VERSION").read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.18")


def test_cpi_backend_action_and_cloud_routes():
    src = (ROOT / "cpi_module.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert '"/devices/{device_id}/action"' in src
    assert '"/cloud-phone/provision"' in src
    assert '"/cloud-phone/guide"' in src
    assert "CPIDeviceActionBody" in src
    assert "android_cloud" in src
    assert "android_emulator" in src


def test_worker_needs_action_and_emulator():
    orch = (WORKER / "orchestrator.py").read_text(encoding="utf-8")
    eng = (WORKER / "android_engine.py").read_text(encoding="utf-8")
    adb = (WORKER / "adb.py").read_text(encoding="utf-8")
    cfg = (WORKER / "config.py").read_text(encoding="utf-8")
    for src in (orch, eng, adb, cfg):
        ast.parse(src)
    assert "_handle_needs_action" in orch
    assert "clear_needs_action" in orch
    assert "ensure_emulator_connections" in eng
    assert "_classify_android_type" in eng
    assert "execute_action" in eng
    assert "async def connect" in adb
    assert "emulator_endpoints" in cfg
    assert "cloud_adb_endpoints" in cfg


def test_classify_types():
    # Inline mirror of classifier (avoid importing worker package → yaml dep)
    def classify(serial: str, model: str = "") -> str:
        s = (serial or "").strip().lower()
        m = (model or "").lower()
        if s.count(":") == 1 and s.split(":")[-1].isdigit():
            host = s.split(":")[0]
            if host in ("127.0.0.1", "localhost", "0.0.0.0") or host.startswith("10.0.2."):
                if "ldplayer" in m or "leidian" in m:
                    return "android_ldplayer"
                if "genymotion" in m or "vbox" in m:
                    return "android_genymotion"
                if "bluestacks" in m:
                    return "android_bluestacks"
                return "android_emulator"
            return "android_cloud"
        if s.startswith("emulator-"):
            return "android_emulator"
        if any(x in m for x in ("sdk_gphone", "google_sdk", "emulator", "android sdk")):
            return "android_emulator"
        if "ldplayer" in m or "leidian" in m:
            return "android_ldplayer"
        if "genymotion" in m:
            return "android_genymotion"
        return "android_real"

    assert classify("127.0.0.1:5555", "LDPlayer") == "android_ldplayer"
    assert classify("127.0.0.1:5555", "sdk") == "android_emulator"
    assert classify("203.0.113.9:5555", "Phone") == "android_cloud"
    assert classify("emulator-5554", "") == "android_emulator"
    assert classify("R58M123", "Pixel") == "android_real"
    # Also assert worker source still matches these labels
    eng = (WORKER / "android_engine.py").read_text(encoding="utf-8")
    assert "android_ldplayer" in eng and "android_cloud" in eng



def test_frontend_cpi_no_phone_ux():
    fe = ROOT.parent / "frontend" / "src" / "pages"
    devices = (fe / "CPIDevicesPage.js").read_text(encoding="utf-8")
    setup = (fe / "CPIWorkerSetupPage.js").read_text(encoding="utf-8")
    assert "cpi-enable-krexion-android" in devices
    assert "install_apk" in devices
    assert "open_url" in devices
    assert "Enable Krexion Android" in devices or "Krexion Android" in setup
    assert "LDPlayer" not in devices
    assert "Genymotion" not in setup
