"""v2.7.111 — Suite green hygiene after 2.7.109/110."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_2_7_111():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.111")


def test_no_string_version_compare_traps():
    """Catch bare string VERSION compares that break at 2.7.100+."""
    needle = 'assert ver >= "2.'
    bad = []
    for path in (ROOT / "tests").glob("test_v2_7_*.py"):
        if path.name == "test_v2_7_111_suite_green.py":
            continue
        src = path.read_text(encoding="utf-8")
        if needle in src or "assert ver >= '2." in src:
            bad.append(path.name)
    assert bad == [], f"string VERSION compares: {bad}"
