"""
Shared JWT / HMAC secret resolution for cloud server + desktop RUT engine.

Both server.py (tracker verify) and real_user_traffic.py (RUT sign) MUST use
the same secret or `_kx_src` / `_kx_traffic_type` handshakes fail silently.
"""
from __future__ import annotations

import logging
import os
import secrets as _secrets_mod
from pathlib import Path
from typing import Optional

logger = logging.getLogger("krexion_auth_secret")

_INSECURE_DEFAULT_SECRETS = frozenset({
    "",
    "your-secret-key-change-in-production",
    "change-me",
    "changeme",
})

_SERVER_SECRET: Optional[str] = None


def _backend_root() -> Path:
    return Path(__file__).resolve().parent


def _secret_file_path() -> Path:
    custom = os.environ.get("KREXION_SECRET_DIR", "").strip()
    if custom:
        return Path(custom) / "jwt_secret"
    return _backend_root() / ".krexion" / "jwt_secret"


def _load_env_file_secret() -> str:
    """Read JWT_SECRET_KEY from backend/.env when not in os.environ."""
    try:
        from dotenv import dotenv_values
        env_path = _backend_root() / ".env"
        if env_path.is_file():
            vals = dotenv_values(env_path)
            sk = (vals.get("JWT_SECRET_KEY") or "").strip()
            if sk and sk.lower() not in _INSECURE_DEFAULT_SECRETS:
                return sk
    except Exception:
        pass
    return ""


def _read_persisted_secret() -> str:
    try:
        p = _secret_file_path()
        if p.is_file():
            sk = p.read_text(encoding="utf-8").strip()
            if sk and sk.lower() not in _INSECURE_DEFAULT_SECRETS:
                return sk
    except Exception:
        pass
    return ""


def _persist_secret(secret: str) -> None:
    try:
        p = _secret_file_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secret, encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
    except Exception as exc:
        logger.debug(f"Could not persist JWT secret: {exc}")


def _resolve_secret_chain() -> str:
    """Env → backend/.env → persisted file."""
    env = os.environ.get("JWT_SECRET_KEY", "").strip()
    if env and env.lower() not in _INSECURE_DEFAULT_SECRETS:
        return env
    file_env = _load_env_file_secret()
    if file_env:
        return file_env
    persisted = _read_persisted_secret()
    if persisted:
        return persisted
    return ""


def resolve_jwt_secret_for_server() -> str:
    """Called once at server.py import — mirrors prior SECRET_KEY logic."""
    global _SERVER_SECRET
    found = _resolve_secret_chain()
    if found:
        _SERVER_SECRET = found
        os.environ.setdefault("JWT_SECRET_KEY", found)
        return _SERVER_SECRET
    _SERVER_SECRET = _secrets_mod.token_urlsafe(48)
    _persist_secret(_SERVER_SECRET)
    os.environ.setdefault("JWT_SECRET_KEY", _SERVER_SECRET)
    logger.warning(
        "JWT_SECRET_KEY missing — generated and persisted to %s. "
        "Copy this secret to cloud production env so RUT handshakes match.",
        _secret_file_path(),
    )
    return _SERVER_SECRET


def get_hmac_secret() -> str:
    """Return the HMAC key RUT uses when signing `_kx_src` / `_kx_traffic_type`.

    Order:
      1. JWT_SECRET_KEY env (production path — cloud + desktop must share this)
      2. backend/.env JWT_SECRET_KEY
      3. Persisted ~/.krexion-style file under backend/.krexion/jwt_secret
      4. server.SECRET_KEY when running in-process with the local backend
      5. Cached server secret from resolve_jwt_secret_for_server()
      6. Legacy insecure default (dev only — both sides must use same default)
    """
    found = _resolve_secret_chain()
    if found:
        return found
    try:
        import server as _srv  # noqa: WPS433 — intentional late import
        sk = getattr(_srv, "SECRET_KEY", None)
        if sk and str(sk).strip():
            return str(sk)
    except Exception:
        pass
    if _SERVER_SECRET:
        return _SERVER_SECRET
    return "your-secret-key-change-in-production"


__all__ = ["get_hmac_secret", "resolve_jwt_secret_for_server"]
