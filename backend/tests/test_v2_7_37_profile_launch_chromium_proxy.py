"""v2.7.37 — Headed profile launch Chromium path + launch-time unique proxy."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_normalize_playwright_browsers_path_absolute(tmp_path, monkeypatch):
    import importlib

    import real_user_traffic as rut

    fake_exe = tmp_path / "KrexionBackend.exe"
    fake_exe.write_text("", encoding="utf-8")
    bundle = tmp_path / "browser-engine" / "chromium-1234" / "chrome-win64"
    bundle.mkdir(parents=True)
    (bundle / "chrome.exe").write_text("", encoding="utf-8")

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", r"\pw-browsers")
    monkeypatch.setattr(rut.sys, "executable", str(fake_exe))
    importlib.reload(rut)

    got = rut.normalize_playwright_browsers_path()
    assert Path(got).is_absolute()
    assert "browser-engine" in got.replace("/", "\\")
    assert rut._full_chromium_binary_path() is not None


def test_full_chromium_finds_chrome_win64(tmp_path, monkeypatch):
    import importlib

    import real_user_traffic as rut

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    importlib.reload(rut)
    monkeypatch.setattr(rut, "_chromium_revision_from_playwright", lambda: "9999")
    monkeypatch.setattr(rut, "_browsers_search_roots", lambda: [tmp_path])

    d = tmp_path / "chromium-1208" / "chrome-win64"
    d.mkdir(parents=True)
    (d / "chrome.exe").write_text("", encoding="utf-8")

    got = rut._full_chromium_binary_path()
    assert got is not None
    assert "chrome-win64" in str(got).replace("/", "\\")


def test_launch_proxy_helpers_exist():
    from browser_profile_module import _ensure_profile_launch_proxy

    assert callable(_ensure_profile_launch_proxy)


def test_profile_launcher_headed_preflight():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "get_headed_engine_status" in src
    assert "_ensure_full_chromium_available" in src
    assert "normalize_playwright_browsers_path" in src


def test_launch_endpoint_uses_ensure_proxy():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "_ensure_profile_launch_proxy" in src
    assert "launch retry, no team dedupe" not in src
