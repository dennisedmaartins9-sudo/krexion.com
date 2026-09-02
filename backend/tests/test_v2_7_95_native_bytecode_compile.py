"""v2.7.95 — Native bytecode must compile with embedded Python 3.11."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compile_strip_uses_embedded_python_not_host_compileall():
    src = (ROOT.parent / "build" / "build-backend.py").read_text(encoding="utf-8")
    assert "compileall.compile_dir" not in src
    assert '"-m", "compileall"' in src
    assert "_python_exe()" in src
    assert "bad magic number" in src or "Bytecode magic mismatch" in src


def test_version_is_2_7_96():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.96"
