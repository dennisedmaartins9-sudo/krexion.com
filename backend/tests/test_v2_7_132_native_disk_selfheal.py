"""v2.7.132+ — Native Windows disk self-heal (superseded by v2.7.133 nuclear)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_132():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.132")


def test_windows_release_has_disk_selfheal():
    wf = (REPO / ".github/workflows/build-windows-release.yml").read_text(
        encoding="utf-8"
    )
    # v2.7.133 renamed/moved step ahead of checkout (nuclear wipe)
    assert "Windows disk self-heal (before checkout)" in wf or (
        "Windows disk self-heal (before embed build)" in wf
    )
    assert "krexion-ci-cache" in wf
    assert "_diag" in wf
    assert "5 GB" in wf or "5.0" in wf or "2 GB" in wf or "2.0" in wf
