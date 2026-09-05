"""v2.7.117 — AdsPower-style Proxies: skip_duplicates + probe-lines + UI tabs."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_117():
    from releases_module import _parse
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.117")


def test_normalize_proxy_identity_strips_remark_and_scheme():
    import re
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "def _normalize_proxy_identity(" in src
    # Execute helper in isolation (no motor import)
    start = src.index("def _normalize_proxy_identity(")
    end = src.index("\ndef ", start + 1)
    ns: dict = {"re": re}
    exec(src[start:end], ns)
    fn = ns["_normalize_proxy_identity"]
    a = fn("http://user:pass@1.2.3.4:8080{Remark}")
    b = fn("1.2.3.4:8080:user:pass")
    c = fn("socks5://user:x@1.2.3.4:8080[https://change.ip]")
    assert a == b == c
    assert a.startswith("1.2.3.4:8080|user")


def test_proxy_upload_model_has_skip_duplicates():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    block = src[src.index("class ProxyUpload"): src.index("class ProxyUpload") + 500]
    assert "skip_duplicates" in block
    assert "proxy_list" in block


def test_probe_lines_route_exists():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert '@api_router.post("/proxies/probe-lines")' in src
    assert "async def probe_proxy_lines" in src


def test_frontend_has_adspower_tabs_and_bulk_panel():
    page = (REPO / "frontend/src/pages/ProxiesPage.js").read_text(encoding="utf-8")
    assert 'data-testid="proxies-main-tabs"' in page
    assert 'data-testid="proxies-tab-list"' in page
    assert 'data-testid="proxies-tab-rotating"' in page
    assert 'data-testid="proxies-tab-providers"' in page
    assert 'data-testid="proxies-tab-resources"' in page
    assert "ProxyBulkAddPanel" in page
    panel = (REPO / "frontend/src/components/ProxyBulkAddPanel.js").read_text(encoding="utf-8")
    assert "Check duplicate" in panel
    assert "skip_duplicates" in panel
    assert "probe-lines" in panel
    assert "parseProxyLine" in panel


def test_parse_proxy_line_helpers_cover_adspower_formats():
    # Mirror FE parser rules in a tiny Python twin for regression.
    def parse(raw, default_type="http"):
        line = (raw or "").strip()
        if not line:
            return None
        remark = ""
        change = ""
        m = re.search(r"\{([^}]*)\}\s*$", line)
        if m:
            remark = m.group(1).strip()
            line = line[: m.start()].strip()
        m = re.search(r"\[([^\]]*)\]\s*$", line)
        if m:
            change = m.group(1).strip()
            line = line[: m.start()].strip()
        ptype = default_type
        sm = re.match(r"^(https?|socks5h?|socks4)://", line, re.I)
        if sm:
            ptype = sm.group(1).lower()
            line = line[sm.end() :]
        if "@" in line:
            auth, hp = line.rsplit("@", 1)
            user = auth.split(":", 1)[0]
            host, port = hp.split(":")[0], hp.split(":")[1]
        else:
            parts = line.split(":")
            host, port = parts[0], parts[1]
            user = parts[2] if len(parts) >= 4 else ""
        return {"ok": True, "host": host, "port": port, "user": user, "type": ptype, "remark": remark, "change": change}

    r = parse("socks5://user:pass@1.2.3.4:8000[http://x]{Hello}")
    assert r["host"] == "1.2.3.4" and r["port"] == "8000" and r["user"] == "user"
    assert r["remark"] == "Hello" and r["change"] == "http://x"
    r2 = parse("1.2.3.4:8000:user:pass{Remark}")
    assert r2["host"] == "1.2.3.4" and r2["user"] == "user"
