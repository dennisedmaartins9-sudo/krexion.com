"""v2.7.93 — Upload Thing available math + auto-batch list filter."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upload_doc_available_derived_from_original_minus_consumed():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "derived_available = max(0, original_item_count - consumed_count)" in src
    assert "_upload_is_user_visible" in src
    assert 'name.startswith("auto-")' in src


def test_rut_no_auto_proxy_ua_preupload():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "RealUserTrafficPage.js").resolve().read_text(encoding="utf-8")
    assert "const wantProxies = false;" in src
    assert "const wantUas = false;" in src


def test_license_mac_product_not_same_as_windows_electron():
    src = (ROOT / "license_module.py").read_text(encoding="utf-8")
    assert 'product_kind in ("mac", "darwin", "osx")' in src
    assert 'product_kind in ("electron", "desktop", "mac", "linux")' not in src


def test_uploaded_things_labeled_downloads():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "UploadedThingsPage.js").resolve().read_text(encoding="utf-8")
    assert "function uploadAvailableCount" in src
    assert "Original" in src and "Available" in src and "Used" in src
