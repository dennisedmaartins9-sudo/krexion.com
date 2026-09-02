"""v2.7.94 — Browser profile audit gaps (source-string tests, no Mongo)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def test_launch_warnings_on_webkit_and_mobile_shell_fail():
    src = _read("browser_profile_launcher.py")
    assert "_launch_warnings" in src
    assert "launch_warnings" in src
    assert "not a real iOS Safari fingerprint" in src or "NOT a real iOS Safari" in src
    assert "not the branded iOS/Android shell" in src


def test_profile_audit_module_and_route():
    assert "log_profile_event" in _read("browser_profile_audit.py")
    mod = _read("browser_profile_module.py")
    assert "/audit" in mod or "profile_audit_log" in mod
    assert "session_start" in mod
    assert "lead_consumed" in _read("browser_profile_automation.py")


def test_smart_session_bulk_create_skips_pre_allocate():
    mod = _read("browser_profile_module.py")
    assert "smart_session" in mod
    assert "body.proxy.smart_session" in mod


def test_rut_live_remove_preserves_original_file_path():
    rut = _read("real_user_traffic.py")
    assert "remaining_file_path" in rut
    idx = rut.find("async def _live_remove_data_row")
    block = rut[idx : idx + 12000]
    assert "wb.save(fp_str)" in block or "remaining_file_path" in block
    assert "file_path': None" not in block or "remaining_file_path" in block


def test_export_cookies_owner_only():
    mod = _read("browser_profile_module.py")
    assert "Cookie export is owner-only" in mod


def test_public_view_launch_warnings():
    mod = _read("browser_profile_module.py")
    assert '"launch_warnings"' in mod or "'launch_warnings'" in mod


def test_version_is_2_7_95():
    assert (ROOT / "VERSION").read_text().strip() == "2.7.95"
