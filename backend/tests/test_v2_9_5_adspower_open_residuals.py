"""v2.9.5 — AdsPower Open residuals: parallel tray + honesty + Sync CDP."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_9_5():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.5")


def test_tray_drains_parallel_slots():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "KREXION_TRAY_MAX_PARALLEL" in src
    assert "Claim up to N queued launches" in src


def test_tray_mirrors_cdp_to_mongo_for_sync():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    tray = src.split("async def process_pending_user_session_launches")[1].split(
        "async def warm_profile_cookies"
    )[0]
    assert 'if body.get("cdp_ws")' in tray
    assert '["cdp_ws"]' in tray or '["cdp_ws"] =' in tray
    assert "debugger_address" in tray
    assert "launch_warnings" in tray


def test_webkit_open_aborts_without_chromium_lie():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "no Chromium lie" in src
    wk = src.split("browser = await p.webkit.launch")[1].split(
        'elif _profile_engine == "firefox"'
    )[0]
    assert "raise RuntimeError" in wk
    assert '_profile_engine = "chromium"' not in wk


def test_firefox_open_aborts_without_chromium_lie():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    ff = src.split('elif _profile_engine == "firefox":')[1].split("else:")[0]
    assert "raise RuntimeError" in ff
    assert "Chromium fallback" not in ff
    assert '_profile_engine = "chromium"' not in ff


def test_cdp_does_not_invent_http_websocket():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "do NOT invent http://" in src
    assert '_cdp_ws = f"http://{_debugger_addr}"' not in src


def test_resolve_cdp_probes_before_http_invent():
    src = (ROOT / "browser_profile_sync.py").read_text(encoding="utf-8")
    assert "_http_cdp_if_live" in src
    assert "/json/version" in src
    # Stale invent without probe removed
    fn = src.split("def resolve_cdp_for_profile")[1].split("\nasync def ")[0]
    assert 'return f"http://{addr}"' not in fn or "_http_cdp_if_live" in fn


def test_ios_ua_note_no_chromium_fallback_promise():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "launch picks WebKit or Chromium fallback" not in src
    assert "aborts if Safari engine missing" in src


def test_local_api_docs_say_poll_for_cdp():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "poll" in src.lower()
    assert "Start queues Open" in src


def test_inno_requires_krexion_kernel():
    iss = (ROOT.parent / "installer" / "krexion-setup.iss").read_text(encoding="utf-8")
    line = [ln for ln in iss.splitlines() if "krexion-kernel" in ln and "Source:" in ln][0]
    assert "skipifsourcedoesntexist" not in line


def test_fe_polls_sync_slave_errors():
    fe = (
        ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "slave_error_count" in fe
    assert "/sync/${activeSyncId}" in fe or "/sync/${activeSyncId}" in fe
    assert "Poll Sync status" in fe or "mid-session slave" in fe
    # White-label: no competitor name in FE profiles page
    assert "AdsPower" not in fe
