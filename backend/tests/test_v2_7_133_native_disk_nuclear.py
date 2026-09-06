"""v2.7.133 — Native Windows nuclear disk self-heal before checkout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_133():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.133")


def test_selfheal_before_checkout():
    wf = (REPO / ".github/workflows/build-windows-release.yml").read_text(
        encoding="utf-8"
    )
    assert "Windows disk self-heal (before checkout)" in wf
    assert wf.index("Windows disk self-heal (before checkout)") < wf.index(
        "Checkout code via git"
    )
    assert "Wiped C:\\krexion-ci-cache" in wf or "krexion-ci-cache" in wf
    assert "5 GB" in wf or "5.0" in wf


def test_emergency_clean_workflow_exists():
    wf = (
        REPO / ".github/workflows/windows-disk-emergency-clean.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch" in wf
    assert "Nuclear disk clean" in wf
    assert "krexion-windows" in wf
