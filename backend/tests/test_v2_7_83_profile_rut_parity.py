"""v2.7.83 — Profile JSON RUT parity: proxy upload consume + used data sheet."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_version_is_2_7_83():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() >= "2.7.83"


def test_proxy_upload_pick_consume_registered():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "_pick_proxy_line_from_upload" in src
    assert "_consume_proxy_line_from_upload" in src
    assert "_apply_json_run_proxy_from_upload" in src


def test_used_data_sheet_and_download():
    auto = (ROOT / "browser_profile_automation.py").read_text(encoding="utf-8")
    srv = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "used_file_path" in auto
    assert '"used data"' in auto
    assert 'which == "used"' in srv
    assert "has_used_file" in srv


def test_frontend_proxy_upload_picker():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "BrowserProfilesPage.js").resolve().read_text(encoding="utf-8")
    assert "bp-bulk-auto-proxy-upload" in src
    assert "proxy_upload_id" in src


def test_uploaded_things_used_download():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "UploadedThingsPage.js").resolve().read_text(encoding="utf-8")
    assert "ut-dl-used-" in src
