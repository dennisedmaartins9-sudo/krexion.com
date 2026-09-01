"""
Krexion Desktop Dashboard — main entry point
==============================================
Launches as ``krexion-coreapp.exe -m desktop.krexion_dashboard``
(via krexion-tray.bat) on the customer's PC.

Behaviour:
  1. Sets up a file logger to ``{InstallDir}\\logs\\dashboard.log`` BEFORE
     any heavy imports so even a top-level ImportError leaves a paper
     trail (previous v1.0.4 used pythonw.exe which sends stderr to NUL).
  2. Starts a pystray icon in a background thread.
  3. Opens a PyWebView window pointing at the bundled
     ``static/index.html``. Closing the window's X minimises to tray
     (the dashboard never silently dies).
  4. If PyWebView / WebView2 fail to initialise (common on Win10 PCs
     without the WebView2 runtime installed), we fall back to a
     lightweight Tkinter window that at least surfaces the failure +
     a button to open krexion.com — so the customer ALWAYS sees a
     Krexion window after install, never a silent miss.

Cross-platform-friendly: the imports are wrapped so this file can be
linted on Linux build runners too (the Windows .exe build is the only
place it actually executes).
"""
from __future__ import annotations

# ── File logger setup FIRST — every other import below may raise ─────
import asyncio
import logging
import os
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
INDEX_FILE = STATIC_DIR / "index.html"

# Locate the install dir's logs/ folder. In the bundled layout the
# desktop package sits at {app}\bin\app\desktop\ so {app}\logs\ is three
# parents up. Fall back to the desktop folder itself if that doesn't
# exist (dev-mode run from repo).
_LOG_DIR_CANDIDATES = [
    Path(os.environ.get("KREXION_LOG_DIR", "")) if os.environ.get("KREXION_LOG_DIR") else None,
    HERE.parent.parent.parent / "logs",   # {app}\logs (native install)
    HERE.parent / "logs",                  # repo dev fallback
    Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Krexion" / "logs",
]
LOG_DIR = next((p for p in _LOG_DIR_CANDIDATES if p), Path.cwd() / "logs")
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:  # noqa: BLE001
    LOG_DIR = Path.cwd()

LOG_FILE = LOG_DIR / "dashboard.log"

# Configure logging immediately — file + (when console attached) stream
_handlers: list[logging.Handler] = []
try:
    _handlers.append(logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"))
except Exception:  # noqa: BLE001
    pass
# If launched from cmd.exe we still want visible output
try:
    if sys.stderr and sys.stderr.fileno() >= 0:
        _handlers.append(logging.StreamHandler(sys.stderr))
except Exception:  # noqa: BLE001
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_handlers,
    force=True,
)

logger = logging.getLogger("krexion.dashboard")
logger.info("=" * 60)
logger.info("Krexion Dashboard launching")
logger.info(f"  Python    : {sys.executable}")
logger.info(f"  Argv      : {sys.argv}")
logger.info(f"  CWD       : {os.getcwd()}")
logger.info(f"  HERE      : {HERE}")
logger.info(f"  INDEX     : {INDEX_FILE} (exists={INDEX_FILE.exists()})")
logger.info(f"  LOG_FILE  : {LOG_FILE}")


# Global, uncaught-exception hook — logs ANY crash anywhere in the app
def _excepthook(exc_type, exc_value, exc_tb):
    logger.error("UNCAUGHT EXCEPTION:\n" + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


sys.excepthook = _excepthook


# %PROGRAMDATA%\Krexion is where the installer drops license-key.txt +
# system-specs.json. Used by the tray menu's "Show Specs" item.
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Krexion"

KREXION_CLOUD = os.environ.get("KREXION_CLOUD_URL", "https://krexion.com").rstrip("/")

_window = None
_tray = None
_pending_update_version: str | None = None
_UPDATE_ICON_BASE = None  # PIL image cached
_UPDATE_ICON_BADGE = None
_COUNT_ICON_CACHE: dict[int, object] = {}
_LAST_TRAY_RUNNING = -1
_LAST_TRAY_TOTAL = -1
_UPDATE_LAST_TOAST_AT = 0.0
_UPDATE_TOAST_EVERY_S = 6 * 3600  # re-toast at most every 6h
_UPDATE_POLL_EVERY_S = 15 * 60  # background poll while tray is alive


def _open_in_explorer(path: Path) -> None:
    import subprocess
    try:
        if path.exists():
            subprocess.Popen(["explorer", str(path)])
        else:
            logger.warning(f"Cannot open (missing): {path}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"explorer launch failed: {exc}")


def _on_show_dashboard(_icon=None, _item=None) -> None:
    global _window
    if _window is not None:
        try:
            _window.show()
            _window.restore()
        except Exception:  # noqa: BLE001
            pass


def _on_hide_dashboard(_icon=None, _item=None) -> None:
    global _window
    if _window is not None:
        try:
            _window.hide()
        except Exception:  # noqa: BLE001
            pass


def _on_open_krexion(_icon=None, _item=None) -> None:
    webbrowser.open(f"{KREXION_CLOUD}/login")


def _on_open_logs(_icon=None, _item=None) -> None:
    _open_in_explorer(LOG_DIR)


def _on_open_specs(_icon=None, _item=None) -> None:
    _open_in_explorer(PROGRAM_DATA)


def _on_quit(icon, _item=None) -> None:
    global _window
    try:
        icon.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        if _window is not None:
            _window.destroy()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)  # pystray's run() blocks main thread; hard-exit guarantees release.


def _load_tray_icon():
    """Returns a PIL.Image suitable for pystray, falling back to a
    16x16 solid-colour square if the bundled icon is missing (so the
    tray icon still appears, even without the .ico file). Previously
    we returned a 1x1 fully-transparent pixel which Windows refused
    to render at all → tray icon invisible bug."""
    global _UPDATE_ICON_BASE
    from PIL import Image  # type: ignore
    candidates = [
        HERE / "icons" / "krexion.ico",
        HERE.parent / "krexion.ico",
        HERE.parent.parent / "installer" / "krexion.ico",
        # Native install layout: krexion.ico lives at {app}\krexion.ico
        HERE.parent.parent.parent.parent / "krexion.ico",
    ]
    for p in candidates:
        try:
            if p.exists():
                img = Image.open(str(p)).convert("RGBA")
                logger.info(f"Tray icon loaded from {p}")
                _UPDATE_ICON_BASE = img
                return img
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Tray icon at {p} failed to load: {exc}")
            continue
    # Visible fallback — solid teal square so the icon is at least clickable
    logger.warning("No .ico found, using solid-colour fallback (16x16 teal).")
    img = Image.new("RGBA", (16, 16), (45, 212, 191, 255))
    _UPDATE_ICON_BASE = img
    return img


def _tray_icon_with_update_badge():
    """Orange corner dot on tray icon so customer sees update without
    opening the dashboard window."""
    global _UPDATE_ICON_BADGE
    if _UPDATE_ICON_BADGE is not None:
        return _UPDATE_ICON_BADGE
    from PIL import Image, ImageDraw  # type: ignore
    base = _UPDATE_ICON_BASE or _load_tray_icon()
    try:
        img = base.copy().convert("RGBA")
        # Normalize to ~32px for badge placement
        if max(img.size) < 24:
            resample = getattr(getattr(Image, "Resampling", Image), "NEAREST", Image.NEAREST)
            img = img.resize((32, 32), resample)
        draw = ImageDraw.Draw(img)
        w, h = img.size
        r = max(4, w // 5)
        # Amber badge bottom-right
        draw.ellipse(
            (w - r - 1, h - r - 1, w - 1, h - 1),
            fill=(245, 158, 11, 255),
            outline=(26, 31, 46, 255),
        )
        _UPDATE_ICON_BADGE = img
        return img
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Update badge icon failed: {exc}")
        return base


def _tray_icon_with_count_badge(count: int):
    """Telegram/Cursor-style numeric badge on tray icon (running profiles)."""
    n = max(1, min(99, int(count or 0)))
    cached = _COUNT_ICON_CACHE.get(n)
    if cached is not None:
        return cached
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    base = _UPDATE_ICON_BASE or _load_tray_icon()
    try:
        img = base.copy().convert("RGBA")
        if max(img.size) < 24:
            resample = getattr(getattr(Image, "Resampling", Image), "NEAREST", Image.NEAREST)
            img = img.resize((32, 32), resample)
        draw = ImageDraw.Draw(img)
        w, h = img.size
        label = "99+" if int(count or 0) >= 99 else str(n)
        r = max(9, w // 3)
        x0, y0 = w - r - 1, h - r - 1
        x1, y1 = w - 1, h - 1
        draw.ellipse(
            (x0, y0, x1, y1),
            fill=(239, 68, 68, 255),
            outline=(26, 31, 46, 255),
            width=max(1, w // 32),
        )
        font_size = max(8, r // 2)
        font = None
        for name in ("segoeuib.ttf", "SegoeUI-Bold.ttf", "arialbd.ttf"):
            try:
                font = ImageFont.truetype(name, font_size)
                break
            except Exception:  # noqa: BLE001
                continue
        if font is None:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x0 + (r - tw) // 2 - bbox[0]
            ty = y0 + (r - th) // 2 - bbox[1]
        except Exception:  # noqa: BLE001
            tw, th = draw.textsize(label, font=font)
            tx = x0 + (r - tw) // 2
            ty = y0 + (r - th) // 2
        draw.text((tx, ty), label, fill=(255, 255, 255, 255), font=font)
        _COUNT_ICON_CACHE[n] = img
        return img
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Count badge icon failed: {exc}")
        return base


def _refresh_tray_for_profile_count(running: int, total: int) -> None:
    """Update tray icon tooltip + badge with active/total browser profiles."""
    global _LAST_TRAY_RUNNING, _LAST_TRAY_TOTAL
    if _tray is None:
        return
    running = max(0, int(running or 0))
    total = max(0, int(total or 0))
    if running == _LAST_TRAY_RUNNING and total == _LAST_TRAY_TOTAL:
        return
    _LAST_TRAY_RUNNING = running
    _LAST_TRAY_TOTAL = total
    try:
        if running > 0:
            _tray.icon = _tray_icon_with_count_badge(running)
            _tray.title = f"Krexion — {running} running · {total} profile(s)"
            return
        if _pending_update_version:
            _refresh_tray_for_update(_pending_update_version)
            return
        base = _UPDATE_ICON_BASE or _load_tray_icon()
        _tray.icon = base
        _tray.title = (
            f"Krexion — {total} profile(s)" if total else "Krexion — running"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"tray profile-count refresh failed: {exc}")


def _on_install_pending_update(icon=None, _item=None) -> None:
    """Tray menu: install the pending update silently (no website)."""
    ver = _pending_update_version
    threading.Thread(
        target=_run_silent_update,
        args=(ver,),
        daemon=True,
        name="krexion-tray-install-update",
    ).start()


def _refresh_tray_for_update(latest_norm: str | None) -> None:
    """Swap tray icon + tooltip when an update is (or isn't) available."""
    global _pending_update_version
    if _tray is None:
        return
    try:
        if latest_norm:
            _pending_update_version = latest_norm
            _tray.icon = _tray_icon_with_update_badge()
            _tray.title = f"Krexion — UPDATE v{latest_norm} available"
            # Rebuild menu so Install Update is visible at the top
            import pystray  # type: ignore
            _tray.menu = pystray.Menu(
                pystray.MenuItem(
                    f"⬆ Install Update v{latest_norm}",
                    _on_install_pending_update,
                    default=True,
                ),
                pystray.MenuItem("Show Dashboard", _on_show_dashboard),
                pystray.MenuItem("Hide Dashboard", _on_hide_dashboard),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Check for Updates…", _on_check_updates_now),
                pystray.MenuItem("Open krexion.com", _on_open_krexion),
                pystray.MenuItem("View Logs", _on_open_logs),
                pystray.MenuItem("View System Specs", _on_open_specs),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Krexion Dashboard", _on_quit),
            )
            try:
                _tray.update_menu()
            except Exception:  # noqa: BLE001
                pass
        else:
            _pending_update_version = None
            base = _UPDATE_ICON_BASE or _load_tray_icon()
            _tray.icon = base
            _tray.title = "Krexion — running"
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"tray update refresh failed: {exc}")


def _build_tray():
    import pystray  # type: ignore
    image = _load_tray_icon()
    menu = pystray.Menu(
        pystray.MenuItem("Show Dashboard", _on_show_dashboard, default=True),
        pystray.MenuItem("Hide Dashboard", _on_hide_dashboard),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Check for Updates…", _on_check_updates_now),
        pystray.MenuItem("Open krexion.com", _on_open_krexion),
        pystray.MenuItem("View Logs", _on_open_logs),
        pystray.MenuItem("View System Specs", _on_open_specs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Krexion Dashboard", _on_quit),
    )
    return pystray.Icon("Krexion", image, "Krexion — running", menu)


def _start_tray() -> None:
    global _tray
    try:
        logger.info("Tray thread: building icon...")
        _tray = _build_tray()
        logger.info("Tray thread: icon built — entering run() (blocking)")
        _tray.run()  # blocks the thread it's called from
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Tray icon failed: {exc}", exc_info=True)


def _on_window_closing():
    # Hide instead of close. PyWebView's `closing` event with a return
    # value of `False` cancels the close; we then show the tray icon's
    # "Show Dashboard" as the way back.
    _on_hide_dashboard()
    return False


# ── v2.1.81 — JS-to-Python bridge for auto-repair ─────────────────
# Exposed to dashboard.js via `window.pywebview.api.*`. Every method
# is wrapped so an internal failure NEVER crashes the webview — it
# just returns a structured `{ok: False, error: "..."}` payload that
# the JS can surface in the Diagnose panel. Keeps the customer in
# control while making the "Retry Now" button actually able to fix
# the underlying "KrexionBackend service is dead" problem instead of
# just re-polling a still-dead port for another 2 hours.
class DashboardApi:
    """Public surface exposed to the dashboard's JavaScript.

    All methods return JSON-serialisable dicts and NEVER raise. The
    dashboard is a customer-facing UI — a stray exception here would
    silently kill JS-to-Python calls for the rest of the session.
    """

    _SERVICE_BACKEND = "KrexionBackend"
    _SERVICE_DATABASE = "KrexionDatabase"

    def _run(self, args: list, timeout: int = 30) -> dict:
        """Run a subprocess quietly and return a structured result."""
        import subprocess
        try:
            # CREATE_NO_WINDOW keeps a black cmd flash from popping up
            # over the dashboard on every service call (Windows only).
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=creationflags,
            )
            return {
                "ok": proc.returncode == 0,
                "rc": proc.returncode,
                "stdout": (proc.stdout or "").strip()[:4000],
                "stderr": (proc.stderr or "").strip()[:4000],
            }
        except FileNotFoundError as exc:
            return {"ok": False, "rc": -1, "error": f"command not found: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "rc": -1, "error": str(exc)[:500]}

    def _query_service(self, name: str) -> dict:
        """Wraps `sc query <name>` — returns state ("RUNNING", "STOPPED",
        "PAUSED", "START_PENDING", "STOP_PENDING", "NOT_INSTALLED")."""
        if os.name != "nt":
            return {"ok": False, "state": "NOT_WINDOWS", "error": "sc query only works on Windows"}
        res = self._run(["sc", "query", name], timeout=8)
        out = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
        # `sc query` prints: STATE     : 4  RUNNING     etc.
        state = "UNKNOWN"
        for token in ("RUNNING", "STOPPED", "PAUSED", "START_PENDING", "STOP_PENDING"):
            if token in out:
                state = token
                break
        # Common "not installed" markers so the UI can suggest a repair-install.
        if "does not exist as an installed service" in out.lower() or res.get("rc") == 1060:
            state = "NOT_INSTALLED"
        return {"ok": True, "state": state, "raw": out[:800]}

    # ── Public JS-callable methods ──────────────────────────────────
    def check_services(self) -> dict:
        """Snapshot of both service states — called by dashboard.js
        when the Diagnose panel opens."""
        try:
            return {
                "ok": True,
                "backend": self._query_service(self._SERVICE_BACKEND),
                "database": self._query_service(self._SERVICE_DATABASE),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("check_services failed")
            return {"ok": False, "error": str(exc)[:500]}

    def restart_services(self) -> dict:
        """Try to start both KrexionDatabase and KrexionBackend. Order
        matters: MongoDB must be running before the backend can boot.
        Non-fatal — returns per-service result so the JS can decide
        what to say."""
        try:
            if os.name != "nt":
                return {"ok": False, "error": "restart_services only runs on Windows"}
            results = {}
            for svc in (self._SERVICE_DATABASE, self._SERVICE_BACKEND):
                current = self._query_service(svc)
                if current.get("state") == "RUNNING":
                    results[svc] = {"ok": True, "already_running": True, "state": "RUNNING"}
                    continue
                if current.get("state") == "NOT_INSTALLED":
                    results[svc] = {
                        "ok": False,
                        "not_installed": True,
                        "hint": f"{svc} service isn't installed — re-run the Krexion installer as Administrator.",
                    }
                    continue
                # Give a stuck service a moment to unwind before starting.
                if current.get("state") in ("STOP_PENDING", "START_PENDING"):
                    import time
                    time.sleep(2)
                res = self._run(["sc", "start", svc], timeout=20)
                # Recheck after start attempt.
                post = self._query_service(svc)
                results[svc] = {
                    "ok": res.get("ok") or post.get("state") == "RUNNING",
                    "rc": res.get("rc"),
                    "state_after": post.get("state"),
                    "stderr": res.get("stderr") or res.get("error") or "",
                }
                # Give MongoDB a moment to accept connections before we try
                # starting the backend that depends on it.
                if svc == self._SERVICE_DATABASE and results[svc]["ok"]:
                    import time
                    time.sleep(2)
            return {"ok": True, "services": results}
        except Exception as exc:  # noqa: BLE001
            logger.exception("restart_services failed")
            return {"ok": False, "error": str(exc)[:500]}

    def open_logs_folder(self) -> dict:
        """Opens Explorer at {app}\\logs (or the fallback log dir)."""
        try:
            target = LOG_DIR if LOG_DIR.exists() else HERE
            _open_in_explorer(target)
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("open_logs_folder failed")
            return {"ok": False, "error": str(exc)[:500]}

    def read_backend_log_tail(self, n: int = 30) -> dict:
        """Return the last N lines of backend.stderr.log so the customer
        (or support) can see WHY the service crashed on boot without
        leaving the dashboard."""
        try:
            n = max(1, min(int(n or 30), 500))
            # Search a few candidate locations — the install path can
            # differ between the NSSM native install ({app}\logs) and
            # dev-mode runs.
            candidates = [
                LOG_DIR / "backend.stderr.log",
                LOG_DIR / "backend.stdout.log",
                HERE.parent.parent.parent / "logs" / "backend.stderr.log",
                Path("C:/Program Files/Krexion/logs/backend.stderr.log"),
            ]
            for p in candidates:
                try:
                    if not p or not p.exists():
                        continue
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        lines = fh.readlines()
                    tail = "".join(lines[-n:])
                    return {
                        "ok": True,
                        "path": str(p),
                        "line_count": len(lines),
                        "tail": tail[-16000:],  # cap payload size
                    }
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"read_backend_log_tail: could not read {p}: {exc}")
                    continue
            return {"ok": False, "error": "backend.stderr.log not found in any expected location"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("read_backend_log_tail failed")
            return {"ok": False, "error": str(exc)[:500]}

    def open_krexion_com(self) -> dict:
        try:
            webbrowser.open("https://krexion.com/login")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}


_dashboard_api: "DashboardApi | None" = None


def _launch_pywebview_window() -> bool:
    """Try the normal PyWebView+WebView2 path. Returns True on success,
    False if any import / runtime error indicates the runtime is missing
    so the caller can fall back to Tkinter."""
    if not INDEX_FILE.exists():
        logger.error(f"Dashboard HTML missing at {INDEX_FILE} — cannot start PyWebView.")
        return False

    try:
        import webview  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.error(f"PyWebView import failed: {exc}", exc_info=True)
        return False

    global _window, _dashboard_api
    try:
        _dashboard_api = DashboardApi()
        _window = webview.create_window(
            title="Krexion — Local PC Dashboard",
            url=INDEX_FILE.as_uri(),
            width=1180,
            height=760,
            min_size=(960, 640),
            background_color="#0a0e1a",
            easy_drag=False,
            confirm_close=False,
            js_api=_dashboard_api,
        )
        try:
            _window.events.closing += _on_window_closing
        except Exception:  # noqa: BLE001
            # Older PyWebView versions: gracefully degrade. Window will just
            # close normally and tray will still be alive — customer can
            # reopen from tray.
            pass
        logger.info("PyWebView window created — entering webview.start() loop.")
        webview.start(debug=False)
        logger.info("webview.start() returned cleanly (window closed normally).")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"PyWebView runtime failure (likely WebView2 missing): {exc}", exc_info=True)
        return False


def _launch_native_messagebox_fallback() -> None:
    """Last-resort dialog so the customer is NEVER left wondering whether
    Krexion installed correctly. Uses Win32 ``user32!MessageBoxW`` via
    ``ctypes`` — works in EVERY Python interpreter on Windows including
    the embedded distribution we ship with the installer (which does
    NOT include tcl/tk, so Tkinter is unavailable; we previously tried
    Tkinter as fallback and it crashed too with "Can't find a usable
    init.tcl in the following directories...").

    Shows:
      * Krexion brand + version + reason for compatibility mode
      * Two buttons: "Open krexion.com" + "Open Logs Folder"
      * A close button (does NOT kill the tray icon)

    Falls back to opening krexion.com in the default browser if even
    ctypes is unavailable (which would only happen on a broken
    Python install).
    """
    try:
        import ctypes
        import ctypes.wintypes
    except Exception as exc:  # noqa: BLE001
        logger.error(f"ctypes unavailable, opening krexion.com in browser: {exc}", exc_info=True)
        webbrowser.open(f"{KREXION_CLOUD}/login")
        return

    # MB_OKCANCEL | MB_ICONWARNING | MB_TOPMOST = 0x00040031
    MB_FLAGS = 0x00000001 | 0x00000030 | 0x00040000
    title = "Krexion - Compatibility Mode"
    body = (
        "Krexion is installed and running in the background, but the\n"
        "full dashboard window could not start on this PC.\n\n"
        "Most likely cause: Microsoft Edge WebView2 Runtime is missing.\n"
        "Install it once from:\n"
        "https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n"
        "Backend services are running on 127.0.0.1:8001. The tray icon\n"
        "should still be visible in the notification area - right-click\n"
        "it for Show Dashboard / Open krexion.com / View Logs.\n\n"
        "Press OK to open krexion.com in your browser,\n"
        "or Cancel to open the logs folder for troubleshooting."
    )

    try:
        rv = ctypes.windll.user32.MessageBoxW(None, body, title, MB_FLAGS)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"MessageBoxW failed: {exc}", exc_info=True)
        webbrowser.open(f"{KREXION_CLOUD}/login")
        return

    # IDOK = 1, IDCANCEL = 2
    if rv == 1:
        webbrowser.open(f"{KREXION_CLOUD}/login")
    elif rv == 2:
        _open_in_explorer(LOG_DIR)
    logger.info(f"Compatibility MessageBox closed (button={rv}).")


def main() -> int:
    # Start tray in background thread BEFORE the GUI blocks the main thread.
    threading.Thread(target=_start_tray, daemon=True, name="krexion-tray").start()

    # v1.0.21: auto-update check (non-blocking daemon).
    threading.Thread(target=_check_for_updates, daemon=True, name="krexion-update-check").start()
    # Keep polling so customers who leave Krexion running for days still
    # get tray badge + notify when a new Setup ships.
    threading.Thread(target=_update_poll_loop, daemon=True, name="krexion-update-poll").start()

    # 2026-06-28 — user-session browser-profile launcher (Session-0 fix).
    # The NSSM-installed backend service runs in Session 0 and can't
    # display Chromium on the user's desktop, so it writes pending
    # launches into a local Mongo queue. THIS process (the tray app)
    # runs in the user's interactive session via the HKCU Run
    # autostart key, so it CAN display Chromium correctly — we run a
    # tiny polling loop in a daemon thread that drains the queue and
    # spawns the headed browser inline. See
    # `backend/browser_profile_launcher.py::process_pending_user_session_launches`.
    threading.Thread(
        target=_user_session_browser_launcher_loop,
        daemon=True,
        name="krexion-user-session-launcher",
    ).start()

    if _launch_pywebview_window():
        return 0
    # PyWebView failed - fallback so customer ALWAYS sees a window
    logger.warning("Falling back to native Win32 MessageBox compatibility dialog.")
    _launch_native_messagebox_fallback()
    return 0


def _user_session_browser_launcher_loop() -> None:
    """Daemon thread that drives the browser-profile-launch queue.

    Runs an asyncio event loop dedicated to this thread (NOT the
    pywebview main loop — pywebview can't tolerate having an async
    coroutine scheduled into its UI loop). Polls every 2 seconds.

    Cleanly exits if any of:
      * the backend module isn't importable (dev run, no embedded
        Python site-packages) → the queue is empty anyway so this is a
        no-op for those builds.
      * MongoDB isn't reachable on 127.0.0.1:27017 → retries every 10s
        in case the service starts later.
    """
    # Brief sleep so the rest of the dashboard finishes booting first
    import time as _t
    _t.sleep(4)
    logger.info("[user-session-launcher] thread starting")

    async def _loop() -> None:
        # Lazy import — these only need to work on the customer build
        # where the embedded Python ships with backend libs. On a dev
        # / non-installed run the imports may fail; we silently no-op.
        try:
            from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
            from browser_profile_launcher import (  # type: ignore
                process_pending_user_session_launches,
            )
        except Exception as imp_err:  # noqa: BLE001
            logger.info(
                f"[user-session-launcher] backend libs not available "
                f"({imp_err}); queue runner disabled (this is normal on "
                f"non-installed/dev runs)"
            )
            return

        mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
        db_name = os.environ.get("DB_NAME", "krexion")
        cloud_base = os.environ.get("KREXION_CLOUD_URL", "https://krexion.com").rstrip("/")
        cloud_session_update_url = (
            f"{cloud_base}/api/browser-profiles/_bridge/session-update"
        )

        # Read license key file once at startup; the cloud notify is
        # optional so a missing key just disables the cloud-push half.
        license_key = ""
        try:
            lk_path = os.environ.get(
                "LICENSE_KEY_FILE",
                "C:/ProgramData/Krexion/license-key.txt",
            )
            if os.path.exists(lk_path):
                with open(lk_path, "r", encoding="utf-8") as fh:
                    license_key = fh.read().strip()
        except Exception:  # noqa: BLE001
            pass

        client = None
        backoff = 10.0
        while True:
            if client is None:
                try:
                    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=3000)
                    # Trigger a ping so we surface auth/reachability errors here
                    await client.admin.command("ping")
                    logger.info(
                        f"[user-session-launcher] mongo connected: {mongo_url} / {db_name}"
                    )
                    backoff = 10.0
                except Exception as conn_err:  # noqa: BLE001
                    logger.warning(
                        f"[user-session-launcher] mongo not reachable "
                        f"({conn_err}); retrying in {backoff:.0f}s"
                    )
                    client = None
                    await asyncio.sleep(backoff)
                    backoff = min(60.0, backoff * 1.5)
                    continue

            try:
                processed = await process_pending_user_session_launches(
                    client[db_name],
                    cloud_session_update_url=cloud_session_update_url,
                    license_key=license_key,
                )
                if processed:
                    logger.info(
                        f"[user-session-launcher] dispatched {processed} "
                        f"browser-profile launch(es)"
                    )
                try:
                    coll = client[db_name].browser_profiles
                    not_deleted = {
                        "$or": [
                            {"deleted_at": {"$exists": False}},
                            {"deleted_at": None},
                            {"deleted_at": ""},
                        ]
                    }
                    running = await coll.count_documents(
                        {
                            **not_deleted,
                            "status": {"$in": ["running", "launching", "queued"]},
                        }
                    )
                    total = await coll.count_documents(not_deleted)
                    _refresh_tray_for_profile_count(running, total)
                except Exception as count_err:  # noqa: BLE001
                    logger.debug(
                        f"[user-session-launcher] tray profile count skipped: {count_err}"
                    )
            except Exception as work_err:  # noqa: BLE001
                logger.warning(f"[user-session-launcher] cycle error: {work_err}")
                # Force reconnect on next iteration in case the client died
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
                client = None

            await asyncio.sleep(2.0)

    # Run the asyncio loop inside THIS thread (asyncio.new_event_loop
    # is required because asyncio.run() can't share with another loop
    # running elsewhere in the process — pywebview owns its own).
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_loop())
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[user-session-launcher] thread crashed: {exc}", exc_info=True)


def _read_bundled_version() -> str | None:
    """Return installed VERSION (no leading v), or None."""
    version_paths = [
        HERE / "VERSION",
        HERE.parent / "VERSION",
        HERE.parent.parent / "backend" / "VERSION",
        HERE.parent.parent.parent / "backend" / "VERSION",
        HERE.parent.parent.parent.parent / "backend" / "VERSION",
    ]
    for p in version_paths:
        try:
            if p.exists():
                return p.read_text(encoding="utf-8").strip().lstrip("vV")
        except Exception:  # noqa: BLE001
            continue
    return None


def _parse_semver_tuple(v: str) -> tuple:
    parts = []
    for chunk in (v or "").split("."):
        num = ""
        for c in chunk:
            if c.isdigit():
                num += c
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _on_check_updates_now(icon=None, _item=None) -> None:
    """Tray menu: re-run update check immediately (non-blocking)."""
    threading.Thread(
        target=_check_for_updates,
        kwargs={"prompt_always": True, "delay_s": 0},
        daemon=True,
        name="krexion-update-check-now",
    ).start()


def _run_silent_update(target_version: str | None = None) -> None:
    """Download + silent-install latest Setup.exe (same path as dashboard)."""
    try:
        from desktop.updater import apply_update  # type: ignore
        result = apply_update(target_version)
        logger.info(f"[update] apply_update result: {result}")
        if not result.get("ok"):
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None,
                    f"Update failed:\n\n{result.get('message') or 'unknown error'}",
                    "Krexion Update",
                    0x00000010,  # MB_ICONERROR
                )
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[update] silent update failed: {exc}")


def _prompted_update_path(version: str) -> Path:
    return PROGRAM_DATA / f"update-prompted-{version}.flag"


def _already_prompted_version(version: str) -> bool:
    try:
        return _prompted_update_path(version).exists()
    except Exception:  # noqa: BLE001
        return False


def _mark_prompted_version(version: str) -> None:
    try:
        PROGRAM_DATA.mkdir(parents=True, exist_ok=True)
        _prompted_update_path(version).write_text("1", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _check_for_updates(prompt_always: bool = False, delay_s: float = 5.0) -> None:
    """Compare installed VERSION to krexion.com public-latest.

    Primary UX for customers who leave the dashboard closed:
      * Tray icon gets an amber badge + tooltip "UPDATE vX available"
      * Tray menu top item becomes "Install Update vX"
      * Windows tray balloon notify
      * MessageBox once per version (OK = silent install here)

    Dashboard blink "Update" pill is a second surface when the window
    is open. Failures are logged and ignored.
    """
    import time as _t
    global _UPDATE_LAST_TOAST_AT
    if delay_s:
        _t.sleep(delay_s)
    try:
        current_norm = _read_bundled_version()
        if not current_norm:
            logger.info("[update] no VERSION file found; skipping update check")
            return
        logger.info(f"[update] current version: {current_norm}")

        import urllib.request
        import json as _json
        url = f"{KREXION_CLOUD}/api/system/public-latest?current={current_norm}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"Krexion-Desktop/{current_norm}"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        latest = data.get("latest") or {}
        latest_norm = str(latest.get("version") or "").strip().lstrip("vV")
        if not latest_norm:
            logger.info("[update] no latest version from cloud; skipping")
            return
        logger.info(f"[update] latest cloud release: {latest_norm}")

        available = bool(data.get("update_available")) or (
            _parse_semver_tuple(latest_norm) > _parse_semver_tuple(current_norm)
        )
        if not available:
            logger.info("[update] already up to date")
            _refresh_tray_for_update(None)
            if prompt_always:
                try:
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(
                        None,
                        f"Krexion is up to date.\n\nYou have v{current_norm}.",
                        "Krexion Update",
                        0x00000040,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return

        logger.info(f"[update] NEW version available: {latest_norm} (currently {current_norm})")
        _refresh_tray_for_update(latest_norm)

        # Tray balloon — always useful; throttle repeats
        now = _t.time()
        should_toast = (now - _UPDATE_LAST_TOAST_AT) >= _UPDATE_TOAST_EVERY_S
        if should_toast and _tray is not None:
            try:
                _tray.notify(
                    f"Krexion {latest_norm} ready — click tray icon → Install Update "
                    f"(or open Local PC Dashboard blink Update).",
                    "Krexion Update Available",
                )
                _UPDATE_LAST_TOAST_AT = now
            except Exception:  # noqa: BLE001
                pass

        # MessageBox once per version (or always on manual Check)
        show_box = prompt_always or not _already_prompted_version(latest_norm)
        if not show_box:
            return
        try:
            import ctypes
            MB_FLAGS = 0x00000001 | 0x00000040  # OK|CANCEL | INFO
            title = "Krexion - Update Available"
            body = (
                f"A new version of Krexion is available!\n\n"
                f"  Current : v{current_norm}\n"
                f"  Latest  : v{latest_norm}\n\n"
                f"Press OK to download & install here automatically\n"
                f"(no website visit needed).\n\n"
                f"Cancel to skip — tray icon stays marked Update\n"
                f"and Local PC Dashboard shows a blinking Update button."
            )
            rv = ctypes.windll.user32.MessageBoxW(None, body, title, MB_FLAGS)
            _mark_prompted_version(latest_norm)
            if rv == 1:
                _run_silent_update(latest_norm)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[update] could not show MessageBox: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[update] check failed (will retry): {exc}")


def _update_poll_loop() -> None:
    """Keep checking while tray lives — customers leave Krexion running
    for days; a single launch-time check is not enough."""
    import time as _t
    # First check is started separately with a short delay; this loop
    # covers subsequent polls.
    _t.sleep(_UPDATE_POLL_EVERY_S)
    while True:
        try:
            _check_for_updates(prompt_always=False, delay_s=0)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[update] poll loop error: {exc}")
        _t.sleep(_UPDATE_POLL_EVERY_S)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Fatal error in main()")
        # Last-ditch: open krexion.com so user has SOMETHING to click
        try:
            webbrowser.open(f"{KREXION_CLOUD}/login")
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
