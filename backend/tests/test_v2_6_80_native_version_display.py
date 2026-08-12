"""Native version badge must show installed engine, not cloud publish."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import releases_module as rel


def test_native_mode_shows_file_version_not_cloud_publish(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("2.6.74", encoding="utf-8")
    monkeypatch.setattr(rel, "VERSION_FILE", vf)
    monkeypatch.setenv("KREXION_MODE", "native")

    mock_db = MagicMock()
    mock_db.app_releases.find_one = AsyncMock(return_value={
        "version": "2.6.79",
        "download_url": "https://github.com/org/repo/releases/download/v2.6.79/Krexion-Setup-v2.6.79.exe",
    })
    monkeypatch.setattr(rel, "_db", mock_db)

    shown = asyncio.run(rel._displayed_current_version())
    assert shown == "2.6.74"
