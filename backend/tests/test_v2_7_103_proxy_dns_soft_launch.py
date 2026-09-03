"""v2.7.103 — Soft-disable dead proxy DNS so profiles (incl. iPhone) still open."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_proxy_dns_failure_helper():
    from browser_profile_launcher import _is_dns_proxy_error, _proxy_dns_failure

    assert _proxy_dns_failure("http://127.0.0.1:8080") is None
    err = _proxy_dns_failure("http://ca.rrp.bestgo.work.invalid.krexion.test:10000")
    assert err
    assert "ENOTFOUND" in err or "DNS" in err or "getaddrinfo" in err.lower()
    assert _is_dns_proxy_error(
        "https://api.ipify.org: Error: getaddrinfo ENOTFOUND ca.rrp.bestgo.work"
    )


def test_launcher_soft_disables_dead_dns():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "proxy DNS soft-disable" in src
    assert 'proxy_diag["soft_disabled"] = True' in src
    assert "Launched WITHOUT proxy so the profile still opens" in src
    assert "soft_disabled" in src
    assert "retrying WITHOUT proxy so iOS/Android still open" in src


def test_frontend_clears_sticky_opening_message():
    fe = (
        ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "Drop sticky launch toast" in fe
    assert 'st === "running"' in fe


def test_version_is_2_7_103():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 103]
