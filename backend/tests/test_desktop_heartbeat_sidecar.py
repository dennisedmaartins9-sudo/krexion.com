"""v2.6.64 — desktop heartbeat sidecar + heavy-job busy markers."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["KREXION_MODE"] = "local"

import desktop_module as dm  # noqa: E402


def test_heavy_job_busy_counter():
    # Reset
    with dm._HEAVY_BUSY_LOCK:
        dm._HEAVY_BUSY = 0
        dm._HEAVY_LABEL = ""
    dm.mark_heavy_job_busy("RUT abc")
    st = dm.heavy_job_status()
    assert st["busy"] is True
    assert st["active_count"] == 1
    assert "RUT" in st["label"]
    dm.mark_heavy_job_idle()
    st2 = dm.heavy_job_status()
    assert st2["busy"] is False
    assert st2["active_count"] == 0


def test_stats_cache_roundtrip():
    payload = {"ok": True, "backend_version": "2.6.64", "system": {"ram_gb": 8}}
    dm._cache_stats_payload(payload)
    cached = dm._cached_stats_payload(max_age_s=5.0)
    assert cached is not None
    assert cached["backend_version"] == "2.6.64"
    assert cached["_from_cache"] is True


def test_heartbeat_snapshot_shape():
    snap = dm._heartbeat_snapshot()
    assert snap["ok"] is True
    assert snap["alive"] is True
    assert "heavy" in snap
    assert "backend_version" in snap


def test_sidecar_responds_on_ping():
    # Use a high ephemeral port to avoid colliding with a live install.
    port = 18082
    with patch.object(dm, "_SIDECAR_SERVER", None), patch.object(dm, "_SIDECAR_THREAD", None):
        # Force fresh start
        dm._SIDECAR_SERVER = None
        dm._SIDECAR_THREAD = None
        result = dm.start_desktop_heartbeat_sidecar(port=port)
        assert result.get("started") is True
        # Give the thread a moment to bind
        deadline = time.time() + 3
        last_err = None
        body = None
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.1)
        assert body is not None, f"sidecar did not answer: {last_err}"
        assert body.get("alive") is True
        assert body.get("sidecar") is True
        # Stop server if started
        if dm._SIDECAR_SERVER is not None:
            try:
                dm._SIDECAR_SERVER.shutdown()
            except Exception:
                pass
