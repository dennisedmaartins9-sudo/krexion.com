"""v2.7.81 — Bulk JSON button + stop-automation without closing browser."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_version_is_2_7_81():
    from releases_module import _parse as _semver_parse
    assert _semver_parse((ROOT / "VERSION").read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.81")


def test_bulk_run_json_endpoint_registered():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/bulk-run-json"' in src
    assert "BulkRunJsonBody" in src


def test_stop_automation_endpoint_registered():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/{profile_id}/stop-automation"' in src or "stop-automation" in src
    assert "request_stop_automation" in (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")


def test_execute_automation_steps_supports_cancel():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "should_cancel" in src
    assert '"cancelled"' in src


def test_frontend_bulk_json_button():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "BrowserProfilesPage.js").resolve().read_text(encoding="utf-8")
    assert "bp-bulk-json" in src
    assert "bulk-run-json" in src
    assert "Stop Auto" in src
    assert "stop-automation" in src


def test_consume_data_file_row_registered():
    src = (ROOT / "browser_profile_automation.py").read_text(encoding="utf-8")
    assert "consume_data_file_row" in src
    assert "on_lead_submitted" in src


def test_resolve_automation_uses_profile_default_data_file():
    src = (ROOT / "browser_profile_automation.py").read_text(encoding="utf-8")
    assert "default_data_file_id" in src
