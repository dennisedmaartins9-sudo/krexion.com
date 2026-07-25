"""
v2.6.28 — Popup Work backend tests.

Fixtures:
    /app/backend/tests/_popup_fixtures/{empty,hidden,visible,mixed}.html
    Served on http://localhost:8765 by a background threaded http.server
    started in the module fixture.

Covers:
    1. Visibility filter — hidden .modal templates must NOT be counted.
    2. element_kind classification (text_input / select / checkbox / button).
    3. Label extraction prefers placeholder / name over "Button #N".
    4. VERSION endpoint returns 2.6.28.
    5. Mixed page (visible dialog + hidden template) → popup_count == 1.
"""
import os
import time
import uuid
import threading
import http.server
import socketserver
from pathlib import Path

import pytest
import requests


def _read_base_url():
    p = "/app/frontend/.env"
    with open(p) as f:
        for ln in f:
            if ln.strip().startswith("REACT_APP_BACKEND_URL="):
                return ln.strip().split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE_URL = _read_base_url()
FIXTURE_DIR = Path(__file__).parent / "_popup_fixtures"
# find a free port at import time so parallel runs don't collide
def _pick_port():
    import socket
    s = socket.socket()
    s.bind(("0.0.0.0", 0))
    p = s.getsockname()[1]
    s.close()
    return p


FIXTURE_PORT = _pick_port()
FIXTURE_BASE = f"http://localhost:{FIXTURE_PORT}"


FIXTURES = {
    "empty.html": (
        "<!doctype html><html><head><title>empty</title></head>"
        "<body><h1>Empty page</h1><p>No popups here.</p></body></html>"
    ),
    "hidden.html": (
        "<!doctype html><html><head><title>hidden</title>"
        "<style>.modal{display:none;padding:40px;background:#fff;"
        "border:1px solid #ccc;}</style></head>"
        "<body><h1>Hidden template</h1>"
        "<div class=\"modal\"><button>Hidden Btn A</button>"
        "<button>Hidden Btn B</button></div></body></html>"
    ),
    "visible.html": (
        "<!doctype html><html><head><title>visible</title>"
        "<style>.backdrop{position:fixed;inset:0;background:rgba(0,0,0,.4);}"
        "#dlg{position:fixed;left:50%;top:50%;"
        "transform:translate(-50%,-50%);background:#fff;padding:30px;"
        "width:400px;border:1px solid #333;z-index:9999;} "
        "input,select,button{display:block;margin:8px 0;padding:6px;"
        "font-size:14px;}</style></head>"
        "<body><h1>Visible modal fixture</h1><div class=\"backdrop\"></div>"
        "<div id=\"dlg\" role=\"dialog\" aria-modal=\"true\" "
        "aria-label=\"Signup dialog\"><h2>Sign up</h2>"
        "<input type=\"text\" name=\"email\" placeholder=\"Email address\" />"
        "<select name=\"country\"><option>USA</option>"
        "<option>Canada</option></select>"
        "<label><input type=\"checkbox\" name=\"tos\" /> Accept terms</label>"
        "<button type=\"submit\" id=\"submitBtn\">Submit</button>"
        "<button type=\"button\" id=\"cancelBtn\">Cancel</button></div>"
        "</body></html>"
    ),
    "mixed.html": (
        "<!doctype html><html><head><title>mixed</title>"
        "<style>.popup{display:none;} "
        "#real{position:fixed;left:50%;top:50%;"
        "transform:translate(-50%,-50%);background:#fff;padding:30px;"
        "width:400px;border:1px solid #333;z-index:9999;} "
        "button,input{display:block;margin:8px 0;padding:6px;}</style></head>"
        "<body><h1>Mixed fixture</h1>"
        "<div class=\"popup\"><h3>Hidden template popup</h3>"
        "<button>Ghost 1</button><button>Ghost 2</button>"
        "<input type=\"text\" placeholder=\"ghost email\"/></div>"
        "<div id=\"real\" role=\"dialog\" aria-modal=\"true\">"
        "<h2>Real visible dialog</h2>"
        "<input type=\"email\" name=\"email\" placeholder=\"Enter email\"/>"
        "<button id=\"ok\">OK</button></div></body></html>"
    ),
}


# ── module-level fixture server ─────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def fixture_server():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in FIXTURES.items():
        (FIXTURE_DIR / name).write_text(content, encoding="utf-8")

    handler = _make_handler(str(FIXTURE_DIR))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("0.0.0.0", FIXTURE_PORT), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    # sanity — wait for socket
    for _ in range(20):
        try:
            r = requests.get(f"{FIXTURE_BASE}/empty.html", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    yield
    httpd.shutdown()


def _make_handler(directory):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, *a, **kw):
            pass
    return H


# ── auth: register a fresh user, admin-activate, return user token ─
@pytest.fixture(scope="module")
def user_token():
    email = f"TEST_vr_popup_{uuid.uuid4().hex[:8]}@demo.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "test1234", "name": "VR Popup"},
        timeout=20,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"register failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    tok = body.get("access_token")
    user_id = body.get("user", {}).get("id")
    assert tok and user_id

    # Admin-activate the user (preview admin creds from /app/memory/test_credentials.md)
    ar = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": "admin@krexion.local", "password": "admin123"},
        timeout=15,
    )
    if ar.status_code == 200:
        atok = ar.json().get("access_token")
        if atok:
            requests.put(
                f"{BASE_URL}/api/admin/users/{user_id}",
                json={"status": "active"},
                headers={"Authorization": f"Bearer {atok}",
                         "Content-Type": "application/json"},
                timeout=15,
            )
    return tok


@pytest.fixture(scope="module")
def auth_headers(user_token):
    return {"Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json"}


# ── helpers ─────────────────────────────────────────────────────────
def _start_session(auth_headers, url):
    r = requests.post(f"{BASE_URL}/api/visual-recorder/start",
                      json={"url": url}, headers=auth_headers, timeout=60)
    assert r.status_code == 200, f"vr start failed: {r.status_code} {r.text[:300]}"
    return r.json()["session_id"]


def _detect(auth_headers, sid):
    """Poll detect-popup-buttons until session ready, then return the result."""
    deadline = time.time() + 45
    last_err = None
    while time.time() < deadline:
        rr = requests.get(
            f"{BASE_URL}/api/visual-recorder/{sid}/detect-popup-buttons",
            headers=auth_headers, timeout=30,
        )
        if rr.status_code == 200:
            # once ready — give the page a beat to paint, then re-fetch
            time.sleep(1.5)
            rr2 = requests.get(
                f"{BASE_URL}/api/visual-recorder/{sid}/detect-popup-buttons",
                headers=auth_headers, timeout=30,
            )
            return rr2.json() if rr2.status_code == 200 else rr.json()
        last_err = (rr.status_code, rr.text[:200])
        if rr.status_code in (409,):
            time.sleep(1.0)
            continue
        pytest.fail(f"detect-popup-buttons failed: {rr.status_code} {rr.text[:300]}")
    pytest.fail(f"session never ready — last={last_err}")


def _cleanup(auth_headers, sid):
    try:
        requests.delete(f"{BASE_URL}/api/visual-recorder/{sid}",
                        headers=auth_headers, timeout=15)
    except Exception:
        pass


def _run(auth_headers, url):
    sid = _start_session(auth_headers, url)
    try:
        return _detect(auth_headers, sid)
    finally:
        _cleanup(auth_headers, sid)


# ── tests ────────────────────────────────────────────────────────────
class TestVersion:
    def test_version_is_2_6_28(self):
        r = requests.get(f"{BASE_URL}/api/public/status", timeout=15)
        assert r.status_code == 200
        assert r.json().get("version") == "2.6.28", r.json()


class TestPopupWork:
    def test_no_popup_on_empty_page(self, auth_headers):
        data = _run(auth_headers, f"{FIXTURE_BASE}/empty.html")
        assert data.get("popup_count") == 0, data
        assert data.get("items") == [], data

    def test_hidden_template_not_counted(self, auth_headers):
        data = _run(auth_headers, f"{FIXTURE_BASE}/hidden.html")
        assert data.get("popup_count") == 0, f"hidden .modal was over-counted: {data}"
        assert data.get("items") == []

    def test_visible_dialog_counted_once_with_kinds(self, auth_headers):
        data = _run(auth_headers, f"{FIXTURE_BASE}/visible.html")
        assert data.get("popup_count") == 1, data
        items = data.get("items") or []
        # >=4 rows: text input + select + checkbox + submit + cancel
        assert len(items) >= 4, f"expected >=4 items, got {len(items)}: {items}"
        kinds = [i.get("element_kind") for i in items]
        assert "text_input" in kinds, kinds
        assert "select" in kinds, kinds
        assert "checkbox" in kinds, kinds
        assert "button" in kinds, kinds

        text_items = [i for i in items if i.get("element_kind") == "text_input"]
        assert text_items, "no text_input row detected"
        for ti in text_items:
            lbl = (ti.get("text") or "")
            assert not lbl.startswith("Button #"), f"text_input still 'Button #N': {lbl}"
            assert lbl.strip(), "text_input label empty"
            assert ti.get("input_type") in (
                "text", "email", "search", "tel", "url",
                "password", "number", "date",
            ), ti

        btn_items = [i for i in items if i.get("element_kind") == "button"]
        assert btn_items, "no button rows"

    def test_mixed_visible_plus_hidden(self, auth_headers):
        data = _run(auth_headers, f"{FIXTURE_BASE}/mixed.html")
        assert data.get("popup_count") == 1, f"mixed page over-counted: {data}"
        items = data.get("items") or []
        assert all(i.get("popup_index") == 0 for i in items), items
        text_labels = [i.get("text") for i in items
                       if i.get("element_kind") == "text_input"]
        assert any("Enter email" in (t or "") for t in text_labels), text_labels
        assert not any("ghost" in (t or "").lower() for t in text_labels), text_labels
