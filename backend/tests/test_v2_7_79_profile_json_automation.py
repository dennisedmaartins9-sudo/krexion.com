"""v2.7.79 — Profile JSON automation (RUT step engine on manual profiles)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_version_is_2_7_79():
    from releases_module import _parse as _semver_parse
    assert _semver_parse((ROOT / "VERSION").read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.79")


def test_parse_automation_steps_list():
    from browser_profile_automation import parse_automation_steps

    steps = parse_automation_steps([{"action": "wait", "ms": 100}])
    assert len(steps) == 1
    assert steps[0]["action"] == "wait"


def test_parse_automation_steps_json_string():
    from browser_profile_automation import parse_automation_steps

    steps = parse_automation_steps('[{"action":"goto","url":"https://example.com"}]')
    assert steps[0]["action"] == "goto"


def test_launch_body_models_exist():
    from browser_profile_module import BulkLaunchBody, LaunchBody, ProfileAutomationLaunch

    body = LaunchBody(
        automation=ProfileAutomationLaunch(enabled=True, automation_upload_id="aj1"),
    )
    assert body.automation.enabled is True


def test_request_run_automation_queues_spec():
    from browser_profile_launcher import _RUNNING_SESSIONS, request_run_automation

    sid = "sess_auto_q"
    _RUNNING_SESSIONS[sid] = {}
    ok = request_run_automation(sid, {"enabled": True, "steps": [{"action": "wait", "ms": 1}]})
    assert ok is True
    assert len(_RUNNING_SESSIONS[sid]["automation_queue"]) == 1
    _RUNNING_SESSIONS.pop(sid, None)


def test_launcher_wires_automation_hook():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_run_profile_automation_if_configured" in src
    assert "request_run_automation" in src
    assert "_launch_automation" in src


def test_frontend_launch_auto_ui():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "BrowserProfilesPage.js").resolve().read_text(encoding="utf-8")
    assert "bp-launch-auto-enable" in src
    assert "bp-bulk-auto-enable" in src
    assert "run-automation" in src


def test_sync_client_run_automation_route():
    src = (ROOT / "sync_client.py").read_text(encoding="utf-8")
    assert "browser-profile/run-automation" in src
    assert "__browser_profile_run_automation__" in src
