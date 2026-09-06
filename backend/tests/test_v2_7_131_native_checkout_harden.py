"""v2.7.131 — Native Windows checkout retry harden."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_131():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.131")


def test_windows_release_checkout_retries():
    wf = (REPO / ".github/workflows/build-windows-release.yml").read_text(encoding="utf-8")
    assert "Checkout attempt" in wf
    assert "index.lock" in wf
    assert wf.count("Checkout attempt") >= 2
    assert "git rev-parse HEAD" in wf or 'git rev-parse HEAD' in wf
