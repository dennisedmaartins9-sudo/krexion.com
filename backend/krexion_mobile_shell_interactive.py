"""Interactive mobile shell HTML + file-based IPC (v2.7.76 production)."""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List

from krexion_mobile_browser_shell import (
    _esc,
    _krexion_mark_html,
    _shell_css_android,
    _shell_css_ios,
)

_SHELL_JS = """
function callApi(name) {
  if (window.pywebview && pywebview.api && pywebview.api[name]) {
    pywebview.api[name]();
  }
}
function renderTabList(tabs, active) {
  var sheet = document.getElementById('tab-sheet');
  var list = document.getElementById('tab-list');
  if (!sheet || !list) return;
  list.innerHTML = '';
  (tabs || []).forEach(function(t, i) {
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'tab-row' + (i === active ? ' on' : '');
    row.textContent = (i + 1) + '. ' + (t.title || t.url || 'Tab');
    row.onclick = function() { pywebview.api.switch_tab(i); };
    list.appendChild(row);
  });
  sheet.classList.add('open');
}
function closeTabSheet() {
  var sheet = document.getElementById('tab-sheet');
  if (sheet) sheet.classList.remove('open');
}
function setUrlText(text) {
  var el = document.getElementById('url-text');
  if (el) el.textContent = text || '';
  var topUrl = document.getElementById('top-url-text');
  if (topUrl) topUrl.textContent = text || '';
}
function setTabCount(n) {
  document.querySelectorAll('[data-tab-count]').forEach(function(el) {
    el.textContent = String(n);
  });
}
"""

_SHELL_CSS = """
.tab-sheet {
  display: none; position: fixed; inset: 0; background: rgba(0,0,0,.72);
  z-index: 99; flex-direction: column; justify-content: flex-end; padding: 10px;
}
.tab-sheet.open { display: flex; }
.tab-panel {
  background: #18181b; border: 1px solid rgba(34,211,238,.35);
  border-radius: 14px 14px 0 0; padding: 12px; max-height: 70%;
  overflow: auto;
}
.tab-panel h3 { font-size: 12px; color: #22d3ee; margin-bottom: 10px; letter-spacing: .08em; }
.tab-row {
  width: 100%; text-align: left; padding: 10px 12px; margin-bottom: 6px;
  border-radius: 8px; border: 1px solid #3f3f46; background: #0b0b12;
  color: #e4e4e7; font-size: 12px; cursor: pointer;
}
.tab-row.on { border-color: #eed322; color: #22d3ee; }
.tab-actions { display: flex; gap: 8px; margin-top: 8px; }
.tab-actions button {
  flex: 1; padding: 8px; border-radius: 8px; border: 1px solid #3f3f46;
  background: #27272a; color: #e4e4e7; font-size: 12px; cursor: pointer;
}
.tool, .nav-btn { cursor: pointer; }
.tool:active, .nav-btn:active { opacity: .65; }
"""


def shell_ipc_paths(cfg_path: str) -> Dict[str, str]:
    base = str(cfg_path or "")
    return {"cmd": base + ".cmd", "state": base + ".state"}


def enqueue_shell_command(cfg_path: str, cmd: str, **kwargs: Any) -> None:
    paths = shell_ipc_paths(cfg_path)
    line = json.dumps({"cmd": cmd, **kwargs}, ensure_ascii=False) + "\n"
    with open(paths["cmd"], "a", encoding="utf-8") as fh:
        fh.write(line)


def drain_shell_commands(cfg_path: str) -> List[Dict[str, Any]]:
    paths = shell_ipc_paths(cfg_path)
    cmd_path = paths["cmd"]
    if not cmd_path or not os.path.isfile(cmd_path):
        return []
    try:
        with open(cmd_path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh.readlines() if ln.strip()]
        os.remove(cmd_path)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def write_shell_state(cfg_path: str, state: Dict[str, Any]) -> None:
    paths = shell_ipc_paths(cfg_path)
    try:
        with open(paths["state"], "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
    except Exception:
        pass


def read_shell_state(cfg_path: str) -> Dict[str, Any]:
    paths = shell_ipc_paths(cfg_path)
    if not os.path.isfile(paths["state"]):
        return {}
    try:
        with open(paths["state"], encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def interactive_top_html(profile_label: str, slot: int, platform: str) -> str:
    plat = (platform or "").strip().lower()
    if plat in ("ios", "ipados"):
        tag = _esc(profile_label[:32]) if profile_label else f"#{slot}"
        return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_ios()}{_SHELL_CSS}</style></head>
<body><div class="ios-top">Krexion · {tag}</div>
<script>{_SHELL_JS}</script></body></html>"""
    safe = _esc(profile_label[:48])
    mark = _krexion_mark_html(platform, size=20)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_android()}{_SHELL_CSS}</style></head>
<body><div class="chrome-top"><div class="omnibox" onclick="callApi('open_tabs')">
  {mark}
  <span class="url" id="top-url-text">{safe}</span>
  <span class="tab-badge" data-tab-count onclick="event.stopPropagation();callApi('open_tabs')">{slot}</span>
  <span class="menu-dot" onclick="event.stopPropagation();callApi('open_menu')">⋮</span>
</div></div>
<script>{_SHELL_JS}
setInterval(function(){{ if(window.pywebview&&pywebview.api&&pywebview.api.poll_state) pywebview.api.poll_state(); }}, 800);
</script></body></html>"""


def interactive_bottom_html(platform: str, profile_label: str, slot: int) -> str:
    plat = (platform or "").strip().lower()
    poll = """
setInterval(function(){ if(window.pywebview&&pywebview.api&&pywebview.api.poll_state) pywebview.api.poll_state(); }, 800);
"""
    if plat in ("ios", "ipados"):
        safe = _esc(profile_label[:40])
        mark = _krexion_mark_html(platform, size=18)
        return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_ios()}{_SHELL_CSS}</style></head>
<body><div class="safari-bottom">
  <div class="url-pill">{mark}<span id="url-text">⟡ {safe}</span></div>
  <div class="tool-row">
    <button class="tool" type="button" onclick="callApi('go_back')">‹</button>
    <button class="tool" type="button" onclick="callApi('go_forward')">›</button>
    <button class="tool" type="button" onclick="callApi('reload_page')">↻</button>
    <button class="tool" type="button" onclick="callApi('go_home')">⌂</button>
    <button class="tool tabs" type="button" onclick="callApi('open_tabs')">▢<em data-tab-count>{slot}</em></button>
  </div>
  <div id="tab-sheet" class="tab-sheet" onclick="if(event.target===this)closeTabSheet()">
    <div class="tab-panel" onclick="event.stopPropagation()">
      <h3>KREXION TABS</h3>
      <div id="tab-list"></div>
      <div class="tab-actions">
        <button type="button" onclick="callApi('new_tab')">+ New tab</button>
        <button type="button" onclick="closeTabSheet()">Close</button>
      </div>
    </div>
  </div>
</div>
<script>{_SHELL_JS}{poll}</script></body></html>"""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_android()}{_SHELL_CSS}</style></head>
<body><div class="chrome-bottom">
  <div class="nav-btn" onclick="callApi('go_home')">⌂</div>
  <div class="nav-btn" onclick="callApi('go_back')">‹</div>
  <div class="nav-btn" onclick="callApi('go_forward')">›</div>
  <div class="nav-btn" onclick="callApi('reload_page')">↻</div>
  <div class="nav-btn" onclick="callApi('open_tabs')">▢</div>
</div>
<div id="tab-sheet" class="tab-sheet" onclick="if(event.target===this)closeTabSheet()">
  <div class="tab-panel" onclick="event.stopPropagation()">
    <h3>KREXION TABS</h3>
    <div id="tab-list"></div>
    <div class="tab-actions">
      <button type="button" onclick="callApi('new_tab')">+ New tab</button>
      <button type="button" onclick="closeTabSheet()">Close</button>
    </div>
  </div>
</div>
<script>{_SHELL_JS}{poll}</script></body></html>"""


class MobileShellHostApi:
    """pywebview js_api — forwards chrome clicks to Playwright via cmd file."""

    def __init__(self, cfg_path: str, home_url: str, profile_label: str) -> None:
        self.cfg_path = cfg_path
        self.home_url = home_url
        self.profile_label = profile_label
        self._top: Any = None
        self._bottom: Any = None

    def bind_windows(self, top: Any, bottom: Any) -> None:
        self._top = top
        self._bottom = bottom

    def _push(self, cmd: str, **kwargs: Any) -> None:
        enqueue_shell_command(self.cfg_path, cmd, **kwargs)

    def poll_state(self) -> None:
        st = read_shell_state(self.cfg_path)
        if not st:
            return
        win = self._bottom or self._top
        if not win:
            return
        try:
            url = str(st.get("url") or "")[:56]
            if url:
                payload = json.dumps(url)
                win.evaluate_js(f"setUrlText({payload})")
            tabs = st.get("tabs")
            if isinstance(tabs, list) and tabs:
                active = int(st.get("active_tab") or 0)
                data = json.dumps(tabs)
                win.evaluate_js(f"renderTabList({data}, {active})")
            tc = st.get("tab_count")
            if tc is not None:
                win.evaluate_js(f"setTabCount({int(tc)})")
        except Exception:
            pass

    def go_back(self) -> None:
        self._push("go_back")

    def go_forward(self) -> None:
        self._push("go_forward")

    def reload_page(self) -> None:
        self._push("reload")

    def go_home(self) -> None:
        self._push("go_home", url=self.home_url)

    def new_tab(self) -> None:
        self._push("new_tab", url=self.home_url)

    def switch_tab(self, index: int) -> None:
        self._push("switch_tab", index=int(index))

    def open_tabs(self) -> None:
        self.poll_state()

    def open_menu(self) -> None:
        self.open_tabs()
