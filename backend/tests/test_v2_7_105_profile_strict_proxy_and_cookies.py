"""v2.7.105 — Strict proxy, cookie SameSite, ACL import, new anti-detect defaults."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_strict_proxy_helper():
    from browser_profile_module import _strict_proxy_mode

    assert _strict_proxy_mode({"anti_detect": {"proxy_check_block_on_fail": True}}) is True
    assert _strict_proxy_mode({"anti_detect": {"strict_proxy": True}}) is True
    assert _strict_proxy_mode({"anti_detect": {"proxy_check_block_on_fail": False}}) is False
    assert _strict_proxy_mode({"proxy_check_block_on_fail": True}) is True
    assert _strict_proxy_mode({}) is False
    assert _strict_proxy_mode(None) is False


def test_netscape_cookies_do_not_force_lax():
    from browser_profile_module import _normalize_cookie_list, _parse_netscape_cookies

    raw = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t1893456000\tsid\tabc123\n"
        ".example.com\tTRUE\t/\tFALSE\t1893456000\tpref\t1\n"
    )
    parsed = _parse_netscape_cookies(raw)
    assert len(parsed) == 2
    assert parsed[0]["httpOnly"] is True
    assert "sameSite" not in parsed[0]
    assert "sameSite" not in parsed[1]

    normalized = _normalize_cookie_list(
        [
            {"name": "a", "value": "1", "domain": "x.com", "sameSite": "Strict"},
            {"name": "b", "value": "2", "domain": "x.com", "same_site": "none"},
            {"name": "c", "value": "3", "domain": "x.com"},
        ]
    )
    by_name = {c["name"]: c for c in normalized}
    assert by_name["a"]["sameSite"] == "Strict"
    assert by_name["b"]["sameSite"] == "None"
    assert "sameSite" not in by_name["c"]


def test_antidetect_defaults_strict_and_persistent():
    from browser_profile_module import AntiDetectConfig

    cfg = AntiDetectConfig()
    assert cfg.proxy_check_block_on_fail is True
    assert cfg.use_persistent_context is True


def test_launcher_strict_blocks_dns_soft_disable():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "Strict proxy: proxy host could not be resolved" in src
    assert "Browser was NOT opened on your real IP" in src
    assert "proxy_diag.get(\"soft_disabled\")" in src
    assert "not a real iPhone/Android device" in src or "NOT a real iPhone" in src


def test_frontend_defaults_and_honesty():
    fe = (
        ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "proxy_check_block_on_fail: true" in fe
    assert "use_persistent_context: true" in fe
    assert "Strict proxy (never open without working proxy)" in fe
    assert "not a real iPhone" in fe
    assert "bp-strict-proxy" in fe
    assert "bp-ios-honesty" in fe


def test_cookie_import_acl_owner_only_message():
    mod = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "Cookie import is owner-only for shared profiles" in mod
    # import uses ACL helper (not raw owner-only find that 404s shared users)
    idx = mod.find("async def import_cookies")
    block = mod[idx : idx + 800]
    assert "_get_profile_for_user" in block
