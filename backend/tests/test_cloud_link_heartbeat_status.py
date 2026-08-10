"""Regression: Local PC Dashboard 'krexion.com link' pill.

sync_client writes ProgramData/Krexion/sync-status.json by default.
desktop_module used to read only /tmp/... → always yellow
'no recent heartbeat' on Windows native.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("KREXION_MODE", "local")

import desktop_module
import sync_client


def test_default_sync_status_path_is_programdata(monkeypatch, tmp_path):
    monkeypatch.delenv("KREXION_SYNC_STATUS_FILE", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    p = sync_client.default_sync_status_path()
    assert p == tmp_path / "Krexion" / "sync-status.json"


def test_cloud_link_reads_programdata_status(monkeypatch, tmp_path):
    monkeypatch.delenv("KREXION_SYNC_STATUS_FILE", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    status = tmp_path / "Krexion" / "sync-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        json.dumps({"last_heartbeat_at": time.time(), "cloud_url": "https://krexion.com"}),
        encoding="utf-8",
    )
    result = asyncio.run(desktop_module._cloud_link_status())
    assert result["connected"] is True
    assert result["last_sync_age"] is not None
    assert result["last_sync_age"] < 120


def test_cloud_link_stale_is_disconnected(monkeypatch, tmp_path):
    monkeypatch.delenv("KREXION_SYNC_STATUS_FILE", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    status = tmp_path / "Krexion" / "sync-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        json.dumps({"last_heartbeat_at": time.time() - 600}),
        encoding="utf-8",
    )
    result = asyncio.run(desktop_module._cloud_link_status())
    assert result["connected"] is False
    assert result["last_sync_age"] >= 120
