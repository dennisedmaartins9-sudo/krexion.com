"""v2.7.14 — Browser Profiles agency features (cookies, folders, local API, etc.)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"


def test_module_has_agency_endpoints():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    for needle in (
        '"/folders"',
        '"/bulk-move"',
        '"/import"',
        '"/local/info"',
        '"/local/start"',
        '"/{profile_id}/cookies"',
        '"/{profile_id}/check-proxy"',
        '"/{profile_id}/share"',
        "geo_follow_proxy",
        "proxy.lines",
        "CookieImportBody",
        "ShareProfileBody",
        "storage_synced_at",
    ):
        assert needle in src, f"missing {needle}"


def test_profile_body_agency_fields():
    from browser_profile_module import ProfileBody, AdvancedCreateBody

    pb = ProfileBody(folder="ClientA", tags=["fb", "warm"], geo_follow_proxy=False)
    assert pb.folder == "ClientA"
    assert pb.geo_follow_proxy is False
    adv = AdvancedCreateBody(tags=["x"], folder="F1", timezone="Europe/London")
    assert adv.folder == "F1"
    assert adv.timezone == "Europe/London"


def test_netscape_cookie_parse():
    from browser_profile_module import _parse_netscape_cookies, _normalize_cookie_list

    text = (
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t1999999999\tsession\tabc123\n"
    )
    cookies = _normalize_cookie_list(_parse_netscape_cookies(text))
    assert len(cookies) == 1
    assert cookies[0]["name"] == "session"
    assert cookies[0]["value"] == "abc123"
    assert cookies[0]["domain"] == "example.com"


def test_launcher_cdp_and_geo_follow():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "remote-debugging-port" in src
    assert "geo_follow_proxy" in src
    assert "cdp_ws" in src


def test_frontend_agency_ux():
    fe = FE.read_text(encoding="utf-8")
    for needle in (
        'data-testid="bp-search"',
        'data-testid="bp-import"',
        "geo_follow_proxy",
        "advProxyLines",
        "Platform mix ON",
        "bp-proxy-check-",
        "bp-cookies-",
        "bp-share-",
        "bp-launch-url-",
        "bulk-move",
    ):
        assert needle in fe, f"frontend missing {needle}"
