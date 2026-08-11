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
    desktop_module._LAST_GOOD_CLOUD_LINK = None
    desktop_module._LAST_GOOD_CLOUD_TS = 0.0
    status = tmp_path / "Krexion" / "sync-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        json.dumps({"last_heartbeat_at": time.time(), "cloud_url": "https://krexion.com"}),
        encoding="utf-8",
    )
    result = asyncio.run(desktop_module._cloud_link_status())
    assert result["connected"] is True
    assert result["last_sync_age"] is not None
    assert result["last_sync_age"] < desktop_module.CLOUD_LINK_FRESH_SEC


def test_cloud_link_still_fresh_after_3_minutes(monkeypatch, tmp_path):
    monkeypatch.delenv("KREXION_SYNC_STATUS_FILE", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    desktop_module._LAST_GOOD_CLOUD_LINK = None
    desktop_module._LAST_GOOD_CLOUD_TS = 0.0
    status = tmp_path / "Krexion" / "sync-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        json.dumps({"last_heartbeat_at": time.time() - 180}),
        encoding="utf-8",
    )
    result = asyncio.run(desktop_module._cloud_link_status())
    assert result["connected"] is True


def test_cloud_link_stale_is_disconnected(monkeypatch, tmp_path):
    monkeypatch.delenv("KREXION_SYNC_STATUS_FILE", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    desktop_module._LAST_GOOD_CLOUD_LINK = None
    desktop_module._LAST_GOOD_CLOUD_TS = 0.0
    status = tmp_path / "Krexion" / "sync-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        json.dumps({"last_heartbeat_at": time.time() - 600}),
        encoding="utf-8",
    )
    result = asyncio.run(desktop_module._cloud_link_status())
    assert result["connected"] is False
    assert result["last_sync_age"] >= desktop_module.CLOUD_LINK_FRESH_SEC


def test_heartbeat_loop_is_independent_of_sync_loop():
    src = (BACKEND_DIR / "sync_client.py").read_text(encoding="utf-8")
    assert "def _heartbeat_thread_main(" in src
    assert "def _start_heartbeat_thread(" in src
    assert "_start_heartbeat_thread()" in src
    assert "name=\"krexion-cloud-heartbeat\"" in src or 'name="krexion-cloud-heartbeat"' in src
    # link-sync loop must not block keepalive
    sync_fn = src.split("async def _sync_loop", 1)[1].split("def start_if_local", 1)[0]
    assert "await _heartbeat()" not in sync_fn
    assert "asyncio.create_task(_heartbeat_loop())" not in src


def test_cloud_online_window_is_wide():
    import bridge_module
    assert bridge_module.ONLINE_WINDOW_SEC >= 240
