"""
Subprocess host — one Krexion mobile chrome pair (top + bottom) per profile.
Isolated pywebview.start() so multiple profiles can run chrome bars in parallel.
v2.7.76 — interactive mode wires chrome buttons to Playwright via file IPC.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    cfg_path = sys.argv[1]
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    # v2.7.127 — AdsPower-style: own AppUserModelID + title before any HWND
    # so taskbar shows Krexion, not EdgeWebView / python.
    slot = int(cfg.get("slot") or 1)
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"Krexion.PhoneChrome.{slot}"
        )
    except Exception:
        pass

    import webview  # type: ignore

    handles: dict = {"top": 0, "bottom": 0, "content": 0}
    bezel = int(cfg.get("bezel") or 0)
    outer_w = int(cfg.get("outer_w") or 400)
    top_h = int(cfg.get("top_h") or 56)
    bottom_h = int(cfg.get("bottom_h") or 72)
    vx = int(cfg.get("x") or 100)
    vy = int(cfg.get("y") or 80)
    vh = int(cfg.get("viewport_h") or 844)
    interactive = bool(cfg.get("interactive"))
    home_url = str(cfg.get("home_url") or "https://www.google.com/")
    profile_label = str(cfg.get("profile_label") or "Profile")
    session_key = str(cfg.get("session_key") or "")

    bottom_y = vy + top_h + bezel + vh + bezel
    show_bottom = bool(cfg.get("show_bottom")) and bottom_h > 0

    api = None
    if interactive:
        try:
            from krexion_mobile_shell_interactive import MobileShellHostApi

            api = MobileShellHostApi(cfg_path, home_url, profile_label)
        except Exception:
            api = None
            interactive = False

    def _save_handles():
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                base = json.load(fh)
            base["handles"] = handles
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(base, fh)
        except Exception:
            pass

    def _on_top_loaded():
        try:
            handles["top"] = int(top.native.Handle.ToInt32())  # type: ignore[attr-defined]
        except Exception:
            try:
                handles["top"] = int(top.native.handle)  # type: ignore[attr-defined]
            except Exception:
                pass
        _save_handles()
        if api is not None:
            api.bind_windows(top, bottom if show_bottom else None, session_key=session_key)

    def _on_bottom_loaded():
        try:
            handles["bottom"] = int(bottom.native.Handle.ToInt32())  # type: ignore[attr-defined]
        except Exception:
            try:
                handles["bottom"] = int(bottom.native.handle)  # type: ignore[attr-defined]
            except Exception:
                pass
        _save_handles()
        if api is not None:
            api.bind_windows(top, bottom, session_key=session_key)

    top = webview.create_window(
        title=f"Krexion — Profile {slot}",
        html=str(cfg.get("top_html") or ""),
        width=outer_w,
        height=top_h,
        x=vx,
        y=vy,
        frameless=True,
        on_top=True,
        easy_drag=False,
        resizable=False,
        background_color="#0b0b12",
        js_api=api,
    )
    top.events.loaded += _on_top_loaded

    # v2.7.128 — Invisible content host between chrome bars so the engine can
    # be SetParent'd into a Krexion-owned HWND (AdsPower-style single window).
    content = None
    content_y = vy + top_h + bezel
    try:
        content = webview.create_window(
            title=f"KrexionContent-{slot}",
            html=(
                "<!doctype html><html><body style='margin:0;background:#000;"
                "overflow:hidden'></body></html>"
            ),
            width=outer_w,
            height=max(200, int(vh)),
            x=vx,
            y=content_y,
            frameless=True,
            on_top=False,
            easy_drag=False,
            resizable=False,
            background_color="#000000",
        )

        def _on_content_loaded():
            try:
                handles["content"] = int(content.native.Handle.ToInt32())  # type: ignore[attr-defined]
            except Exception:
                try:
                    handles["content"] = int(content.native.handle)  # type: ignore[attr-defined]
                except Exception:
                    pass
            _save_handles()

        content.events.loaded += _on_content_loaded
    except Exception:
        content = None

    bottom = None
    if show_bottom:
        bottom = webview.create_window(
            title=f"KrexionShell-{slot}-bottom",
            html=str(cfg.get("bottom_html") or ""),
            width=outer_w,
            height=bottom_h,
            x=vx,
            y=bottom_y,
            frameless=True,
            on_top=True,
            easy_drag=False,
            resizable=False,
            background_color="#0b0b12",
            js_api=api,
        )
        bottom.events.loaded += _on_bottom_loaded
    try:
        webview.start(gui="edgechromium")
    except Exception:
        webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
