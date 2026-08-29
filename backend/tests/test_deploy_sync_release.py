"""Deploy-sync release row + installer-info reads backend/VERSION first."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from releases_module import (
    _github_native_download_url,
    current_version,
    sync_deployed_release_record,
)


def test_sync_deployed_release_record_upserts():
    db = MagicMock()
    db.app_releases.find_one = AsyncMock(return_value=None)
    db.app_releases.insert_one = AsyncMock()

    async def _run():
        with patch("releases_module._db", db), patch(
            "releases_module.current_version", return_value="2.7.37"
        ):
            return await sync_deployed_release_record()

    out = asyncio.run(_run())
    assert out["ok"] is True
    assert out["version"] == "2.7.37"
    assert "Krexion-Setup-v2.7.37.exe" in out["download_url"]
    db.app_releases.insert_one.assert_awaited_once()


def test_github_native_download_url():
    url = _github_native_download_url("2.7.36")
    assert url.endswith("Krexion-Setup-v2.7.36.exe")
    assert "/releases/download/v2.7.36/" in url


def test_current_version_reads_file():
    ver = current_version()
    assert ver.count(".") == 2
