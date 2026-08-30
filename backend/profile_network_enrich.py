"""CDP Fetch-layer URL param injection for browser profiles (Everflow-grade).

Playwright route.continue_(url=…) and synthetic 302 fulfills are not reliable
across all Chromium builds.  Chrome DevTools Fetch.requestPaused rewrites the
request URL at the network stack — the same layer RUT/server redirects use.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_STATIC_SUFFIXES = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".mp4", ".m3u8", ".json", ".map", ".xml",
)


def _is_static_asset_url(url: str) -> bool:
    try:
        base = (url or "").lower().split("?", 1)[0].split("#", 1)[0]
        return any(base.endswith(sfx) for sfx in _STATIC_SUFFIXES)
    except Exception:
        return False


def _headers_list_from_request(
    req_headers: Any,
    *,
    overrides: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """Build CDP Fetch.continueRequest header list (full replacement)."""
    raw: Dict[str, str] = {}
    if isinstance(req_headers, dict):
        for key, value in req_headers.items():
            if key and value is not None:
                raw[str(key)] = str(value)
    skip = {"user-agent", "referer", "accept-language"}
    out: List[Dict[str, str]] = []
    for key, value in raw.items():
        if key.lower().startswith("sec-ch-ua"):
            continue
        if key.lower() in skip:
            continue
        out.append({"name": key, "value": value})
    for key, value in (overrides or {}).items():
        if value:
            out.append({"name": key, "value": str(value)})
    return out


def _url_already_enriched(url: str) -> bool:
    low = (url or "").lower()
    return any(
        tok in low
        for tok in (
            "clickid=", "click_id=", "utm_source=", "utm_medium=",
            "fbclid=", "gclid=", "ttclid=", "sub1=", "aff_sub=",
        )
    )


async def install_profile_cdp_fetch_enricher(
    context: Any,
    state_supplier: Callable[[], Any],
    *,
    enrich_url_fn: Callable[[str, Any], str],
    should_enrich_fn: Callable[[str, bool], bool],
) -> None:
    """Attach Fetch.requestPaused to every tab — rewrite tracker URLs + headers."""
    _bound: Set[int] = set()

    async def _attach_page(page: Any) -> None:
        pg_id = id(page)
        if pg_id in _bound:
            return
        _bound.add(pg_id)
        try:
            session = await context.new_cdp_session(page)
            await session.send(
                "Fetch.enable",
                {"patterns": [{"urlPattern": "*"}], "handleAuthRequests": False},
            )

            async def _on_paused(params: Dict[str, Any]) -> None:
                request_id = params.get("requestId")
                if not request_id:
                    return
                try:
                    state = state_supplier()
                    request = params.get("request") or {}
                    url = str(request.get("url") or "")
                    method = str(request.get("method") or "GET").upper()

                    if (
                        not state
                        or not getattr(state, "enabled", False)
                        or method not in ("GET", "HEAD")
                        or not url.startswith(("http://", "https://"))
                        or _is_static_asset_url(url)
                    ):
                        await session.send(
                            "Fetch.continueRequest", {"requestId": request_id}
                        )
                        return

                    req_headers = request.get("headers") or {}
                    accept = ""
                    if isinstance(req_headers, dict):
                        accept = str(
                            req_headers.get("Accept")
                            or req_headers.get("accept")
                            or ""
                        ).lower()

                    is_document = (
                        "text/html" in accept
                        or should_enrich_fn(url, True)
                    )
                    if not is_document:
                        await session.send(
                            "Fetch.continueRequest", {"requestId": request_id}
                        )
                        return

                    nav_url = url
                    if not _url_already_enriched(url):
                        nav_url = enrich_url_fn(url, state)

                    ua = str(getattr(state, "user_agent", "") or "").strip()
                    if not ua and isinstance(req_headers, dict):
                        ua = str(
                            req_headers.get("User-Agent")
                            or req_headers.get("user-agent")
                            or ""
                        ).strip()

                    hdr_overrides: Dict[str, str] = {}
                    if ua:
                        hdr_overrides["User-Agent"] = ua
                    ref = str(getattr(state, "referer_url", "") or "").strip()
                    if ref:
                        hdr_overrides["Referer"] = ref
                    al = str(getattr(state, "accept_language", "") or "").strip()
                    if al:
                        hdr_overrides["Accept-Language"] = al
                    sf = getattr(state, "sec_fetch", None) or {}
                    if isinstance(sf, dict):
                        for k, v in sf.items():
                            if k and v:
                                hdr_overrides[str(k)] = str(v)

                    cont: Dict[str, Any] = {"requestId": request_id}
                    if nav_url != url:
                        cont["url"] = nav_url
                        logger.info(
                            "[profile-cdp] enriched %s -> %s",
                            url[:80],
                            nav_url[:140],
                        )
                    cdp_headers = _headers_list_from_request(
                        req_headers, overrides=hdr_overrides
                    )
                    if cdp_headers:
                        cont["headers"] = cdp_headers
                    await session.send("Fetch.continueRequest", cont)
                except Exception as exc:
                    logger.warning("[profile-cdp] continueRequest failed: %s", exc)
                    try:
                        await session.send(
                            "Fetch.continueRequest", {"requestId": request_id}
                        )
                    except Exception:
                        pass

            def _schedule(params: Dict[str, Any]) -> None:
                asyncio.create_task(_on_paused(params))

            session.on("Fetch.requestPaused", _schedule)
            logger.info("[profile-cdp] Fetch enricher attached page=%s", pg_id)
        except Exception as exc:
            logger.debug("[profile-cdp] attach skipped: %s", exc)
            _bound.discard(pg_id)

    def _on_new_page(page: Any) -> None:
        asyncio.create_task(_attach_page(page))

    context.on("page", _on_new_page)
    for _pg in list(getattr(context, "pages", []) or []):
        await _attach_page(_pg)
