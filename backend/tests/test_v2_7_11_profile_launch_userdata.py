"""v2.7.11 — Browser Profile launch must not pass illegal --user-data-dir."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_no_user_data_dir_cli_append():
    src = _read("browser_profile_launcher.py")
    assert 'f"--user-data-dir={_kx_user_data_dir}"' not in src
    assert "Do NOT pass `--user-data-dir=`" in src


def test_tray_mirror_persists_last_error():
    src = _read("browser_profile_launcher.py")
    assert '_prof_set["last_error"]' in src
    assert 'status == "error" and body.get("error_message")' in src
