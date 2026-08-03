#!/usr/bin/env python3
"""Show Smartproxy Smart Region usernames Krexion builds per state (verify before push)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _detect_profile,
    _gateway_base_username,
    _rotate_session_in_username,
    _state_slug,
)

CA_PANEL_USER = (
    "smart-u0h51gc8hmdw_area-US_state-california_life-120_session-vMPdPfj97"
)
HOST = "proxy.smartproxy.net"
PASS = "bsNDKlwpUV4DpIDP"
PORT = "3120"


def build_for_state(state_code: str, source_user: str = CA_PANEL_USER) -> str:
    clean = _gateway_base_username(source_user, HOST)
    return _rotate_session_in_username(
        _apply_targeting_to_username(
            clean,
            HOST,
            {"country": "US", "state": state_code, "_want_sid": True, "force_replace": True},
        )
    )


def main() -> None:
    prof = _detect_profile(HOST, "", CA_PANEL_USER)
    print(f"Detected profile: {prof.get('name')} ({prof.get('dsl')})")
    print()
    print("Aapka CA panel string:")
    print(CA_PANEL_USER)
    print()
    print("=" * 72)

    for st in ("CA", "FL", "TX", "NY", "NE"):
        built = build_for_state(st)
        slug = _state_slug(st)
        pat = re.compile(
            rf"^smart-u0h51gc8hmdw_area-US_state-{re.escape(slug)}_life-120_session-[A-Za-z0-9]{{9}}$",
            re.I,
        )
        ok = bool(pat.match(built))
        hpl = f"{HOST}:{PORT}:{built}:{PASS}"
        print(f"\nSTATE {st} (slug={slug})")
        print(f"  Built:    {built}")
        print(f"  Expected: smart-u0h51gc8hmdw_area-US_state-{slug}_life-120_session-<9chars>")
        print(f"  Match:    {'YES' if ok else 'NO'}")
        print(f"  Full line (host:port:user:pass):")
        print(f"    {hpl}")

    print("\n" + "=" * 72)
    fl = build_for_state("FL")
    print("\n*** FL verify (aap panel se compare karein) ***")
    print(fl)
    print(f"\n{HOST}:{PORT}:{fl}:{PASS}")


if __name__ == "__main__":
    main()
