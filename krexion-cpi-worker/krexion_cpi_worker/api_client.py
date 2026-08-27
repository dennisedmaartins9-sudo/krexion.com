"""HTTP client for Krexion CPI backend."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("cpi.api")


class APIClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def close(self):
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _req(self, method: str, path: str, **kw) -> httpx.Response:
        r = await self._client.request(method, path, **kw)
        r.raise_for_status()
        return r

    # ── Devices ─────────────────────────────────────────────
    async def register_device(self, device_id: str, device_type: str,
                              label: Optional[str] = None,
                              model: Optional[str] = None,
                              os_version: Optional[str] = None) -> Dict[str, Any]:
        r = await self._req("POST", "/api/cpi/devices/register", json={
            "device_id": device_id,
            "device_type": device_type,
            "label": label,
            "model": model,
            "os_version": os_version,
        })
        return r.json()

    async def heartbeat(self, device_id: str, status: str = "online",
                         needs_action: Optional[Any] = None,
                         clear_needs_action: bool = False) -> Dict[str, Any]:
        try:
            body: Dict[str, Any] = {"status": status}
            if clear_needs_action:
                body["clear_needs_action"] = True
                body["ack_action"] = True
            elif needs_action is not None:
                body["needs_action"] = needs_action
            r = await self._req("POST", f"/api/cpi/devices/{device_id}/heartbeat", json=body)
            return r.json() if r.content else {"ok": True}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"heartbeat failed for {device_id}: {e}")
            return {"ok": False, "error": str(e)[:160]}

    async def list_devices(self) -> List[Dict[str, Any]]:
        r = await self._req("GET", "/api/cpi/devices")
        return r.json()

    # ── Worker poll/result ──────────────────────────────────
    async def poll(self, device_types: List[str], device_id: Optional[str] = None
                   ) -> Dict[str, Any]:
        r = await self._req("POST", "/api/cpi/worker/poll", json={
            "device_types": device_types,
            "device_id": device_id,
        })
        return r.json()

    async def report_result(self, attempt_id: str, success: bool,
                            failure_reason: Optional[str] = None,
                            duration_seconds: Optional[float] = None,
                            steps: Optional[list] = None,
                            click_id: Optional[str] = None,
                            device_id: Optional[str] = None,
                            device_label: Optional[str] = None) -> Dict[str, Any]:
        r = await self._req("POST", "/api/cpi/worker/result", json={
            "attempt_id": attempt_id,
            "success": success,
            "failure_reason": failure_reason,
            "duration_seconds": duration_seconds,
            "steps": steps or [],
            "click_id": click_id,
            "device_id": device_id,
            "device_label": device_label,
        })
        return r.json()

    # ── Health ──────────────────────────────────────────────
    async def auth_check(self) -> Dict[str, Any]:
        r = await self._req("GET", "/api/auth/me")
        return r.json()

    async def worker_commands(self) -> Dict[str, Any]:
        try:
            r = await self._req("GET", "/api/cpi/worker/commands")
            return r.json()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"worker_commands: {e}")
            return {"commands": []}

    async def ack_worker_command(self, command_id: str, ok: bool = True,
                                  result: Optional[Dict[str, Any]] = None) -> None:
        try:
            await self._req("POST", f"/api/cpi/worker/commands/{command_id}/ack", json={
                "ok": ok,
                "result": result or {},
            })
        except Exception as e:  # noqa: BLE001
            logger.debug(f"ack_worker_command: {e}")
