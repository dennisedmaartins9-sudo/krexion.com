/* Krexion Desktop Dashboard — front-end logic
 * ────────────────────────────────────────────
 * Lightweight, dependency-free JS. Polls two backends:
 *   * Local backend (http://127.0.0.1:8001) every 2s for live stats
 *   * Cloud (https://krexion.com) every 15 min for auto-update banner
 *
 * If the local backend is unreachable, the UI shows a soft "starting up"
 * state instead of erroring — services may still be booting on first
 * install (NSSM gives them ~10s).
 */

const LOCAL = "http://127.0.0.1:8001";
const LOCAL_HEARTBEAT = "http://127.0.0.1:8002";
const CLOUD = "https://krexion.com";

const POLL_LOCAL_MS = 2000;
// Check cloud for new Setup.exe more often so customers see the blink
// soon after a release (was 15 min — easy to miss all day).
const POLL_CLOUD_MS = 5 * 60 * 1000;

// v2.1.79 — Diagnostic thresholds when the local backend never
// answers. Prevents the dashboard from silently sitting on
// "checking…" forever (customer report: "2 hours ho gy ye checking
// pr he hai kuch b chal ni raha"). After the escalation thresholds
// below we surface actionable info + a Diagnose panel with retry +
// logs-folder hints.
const BACKEND_WARN_MS = 8000;     // 8 s → "not responding yet"
const BACKEND_ESCALATE_MS = 20000; // 20 s → open Diagnose panel
const BACKEND_FATAL_MS = 60000;   // 60 s → red status + urgent copy
// v2.1.81 — When the Diagnose panel first opens (t≥20 s of downtime)
// silently fire one restart-services attempt through the JS bridge.
// Most customer PCs recover from this alone: the KrexionBackend NSSM
// service just needed a manual `sc start` because MongoDB wasn't up
// yet when it first tried to boot at Windows login. Zero clicks for
// the customer if we succeed; if we fail the panel still shows the
// manual "Retry Now" + Services.msc guidance.
const AUTO_REPAIR_ONCE_MS = 20000;

const $ = (id) => document.getElementById(id);

// Track how long the backend has been unreachable + last error so
// we can surface it in the Diagnose panel.
const _diag = {
  firstFailAt: 0,          // unix ms of first consecutive failure
  lastFailAt: 0,           // unix ms of most recent failure
  consecutiveFailures: 0,  // # of polls in a row that failed
  lastError: "",           // one-line error summary
  everSucceeded: false,    // has ANY poll ever succeeded this run?
  lastSuccessAt: 0,        // unix ms of most recent success (for uptime label)
  autoRepairAttempted: false,  // v2.1.81 — one silent restart per session
  autoRepairResult: null,      // last restart_services() payload
};

// Local installed version (from /api/desktop/stats) — used so update
// checks compare against THIS PC, not the cloud VERSION file.
let _localVersion = "";
const _updateUi = {
  available: false,
  latestVersion: "",
  title: "",
  notes: "",
};

// v2.1.81 — Access the PyWebView JS bridge safely. Returns null when
// the dashboard is opened as a plain file:// page (dev / repair mode)
// so every caller can gracefully degrade to the manual instructions.
function _pyapi() {
  try {
    return (typeof window !== "undefined"
            && window.pywebview
            && window.pywebview.api) ? window.pywebview.api : null;
  } catch (_) { return null; }
}

function fmtBytes(gb) {
  if (gb >= 100) return Math.round(gb) + " GB";
  if (gb >= 10) return gb.toFixed(0) + " GB";
  return gb.toFixed(1) + " GB";
}
function setText(id, value) { const e = $(id); if (e) e.textContent = value; }
function setBar(id, pct) {
  const e = $(id); if (!e) return;
  e.style.width = Math.max(0, Math.min(100, pct)).toFixed(1) + "%";
}
function setDot(id, state) {
  const e = $(id); if (!e) return;
  e.className = "dot dot-" + state;
}
function setPill(id, label, variant) {
  const e = $(id); if (!e) return;
  e.textContent = label;
  e.className = "pill" + (variant ? " pill-" + variant : "");
}

/* ── Poll local backend ─────────────────────────────────────────── */
async function fetchWithTimeout(url, ms) {
  const ac = new AbortController();
  const to = setTimeout(() => ac.abort(), ms);
  try {
    return await fetch(url, { cache: "no-store", signal: ac.signal });
  } finally {
    clearTimeout(to);
  }
}

async function pollLocal() {
  try {
    // Explicit 4 s per-poll timeout using AbortController so we can
    // distinguish "connection refused" (backend service dead) from
    // "backend hung on this request" — both show up in _diag.lastError
    // instead of the browser's opaque generic TypeError.
    //
    // v2.6.64 — During RUT the main :8001 loop can be busy. Fall back
    // to the threaded heartbeat sidecar on :8002 so we never false-
    // alarm "Backend offline" while visits are still running.
    let r;
    let fromSidecar = false;
    try {
      r = await fetchWithTimeout(`${LOCAL}/api/desktop/stats`, 4000);
      if (!r.ok) throw new Error("HTTP " + r.status);
    } catch (mainErr) {
      try {
        r = await fetchWithTimeout(`${LOCAL_HEARTBEAT}/stats`, 2000);
        if (!r.ok) {
          r = await fetchWithTimeout(`${LOCAL_HEARTBEAT}/ping`, 1500);
        }
        if (!r.ok) throw mainErr;
        fromSidecar = true;
      } catch (_) {
        throw mainErr;
      }
    }
    const d = await r.json();

    // Sidecar-only ping (no full stats) — backend is ALIVE / BUSY, not crashed.
    if (fromSidecar && (d.sidecar || d.alive) && !d.system) {
      _diag.everSucceeded = true;
      _diag.lastSuccessAt = Date.now();
      _diag.consecutiveFailures = 0;
      _diag.firstFailAt = 0;
      hideDiagnosePanel();
      const busy = !!(d.heavy && d.heavy.busy);
      setPill("connection-pill", busy ? "Backend busy (RUT)" : "Backend alive", busy ? "warn" : "");
      setDot("backend-dot", busy ? "warn" : "ok");
      setText("backend-detail",
        busy
          ? `heavy job running${d.heavy && d.heavy.label ? " · " + d.heavy.label : ""} — visits continue normally`
          : "main API briefly busy — heartbeat OK");
      setDot("cloud-dot", d.cloud?.connected ? "ok" : "warn");
      setText("cloud-detail", d.cloud?.connected
        ? `linked · ${d.cloud.last_sync_age || 0}s ago`
        : "no recent heartbeat");
      setText("version-pill", "v" + (d.backend_version || "—"));
      if (d.backend_version) {
        _localVersion = String(d.backend_version).replace(/^v/i, "");
      }
      return;
    }

    // v2.1.79 — reset diagnostic state on ANY success; dismiss panel.
    _diag.firstFailAt = 0;
    _diag.lastFailAt = 0;
    _diag.consecutiveFailures = 0;
    _diag.lastError = "";
    _diag.everSucceeded = true;
    _diag.lastSuccessAt = Date.now();
    _diag.autoRepairAttempted = false;
    _diag.autoRepairResult = null;
    hideDiagnosePanel();

    const heavyBusy = !!(d.heavy && d.heavy.busy);
    setPill("connection-pill",
      heavyBusy ? "Backend busy (job running)" : "Backend Online",
      heavyBusy ? "warn" : "ok");

    // ── Services ─────────────────────────
    setDot("backend-dot", heavyBusy ? "warn" : "ok");
    setText("backend-detail",
      heavyBusy
        ? `job running${d.heavy.label ? " · " + d.heavy.label : ""} · v${d.backend_version || "—"}`
        : (d.backend_version ? `running · ${d.backend_version}` : "running"));
    setDot("db-dot", d.database?.connected ? "ok" : "danger");
    setText("db-detail", d.database?.connected
      ? `connected · ${d.database.collections || 0} collections`
      : "not reachable");
    setDot("cloud-dot", d.cloud?.connected ? "ok" : "warn");
    setText("cloud-detail", d.cloud?.connected
      ? `linked · ${d.cloud.last_sync_age || 0}s ago`
      : "no recent heartbeat");
    setText("services-last-checked", "updated " + new Date().toLocaleTimeString());

    // ── License ─────────────────────────
    const lic = d.license || {};
    setText("license-status", lic.active ? "Active ✓" : "Inactive");
    setText("license-email", lic.email || "—");
    $("license-status").style.color = lic.active ? "var(--ok)" : "var(--warn)";

    // ── CPU/RAM ─────────────────────────
    const s = d.system || {};
    setText("cpu-cores", `${s.cpu_cores || "—"} cores`);
    setBar("cpu-bar", s.cpu_pct || 0);
    setText("cpu-pct", (s.cpu_pct || 0).toFixed(0) + "%");

    setText("ram-total", `${fmtBytes(s.ram_gb || 0)} total`);
    setBar("ram-bar", s.ram_used_pct || 0);
    setText("ram-used", fmtBytes(s.ram_used_gb || 0));
    setText("ram-pct", (s.ram_used_pct || 0).toFixed(0) + "%");

    setText("capacity-tier", (s.tier || "—").toUpperCase());
    setText("capacity-max", s.max_concurrent_heavy_jobs || "—");
    setText("tier-detector", `Detected by ${s.detected_by || "live"} · ${s.cpu_cores || "—"}c / ${fmtBytes(s.ram_gb || 0)}`);

    // ── Active jobs ─────────────────────
    renderJobs($("jobs-list"), d.jobs?.active || [], "No active jobs. Submit one from krexion.com — it will run here.");
    const t = d.jobs?.throughput || {};
    setText("jobs-throughput",
      `${t.jobs_per_hour || 0} jobs/hour · ${(t.success_rate_pct || 0).toFixed(0)}% success`);

    // ── Recent ──────────────────────────
    renderJobs($("recent-list"), d.jobs?.recent || [], "No recent activity yet.");

    // ── Dependencies (v2.1.59) ──────────
    renderDeps(d.dependencies || {});

    setText("version-pill", "v" + (d.backend_version || "—"));
    if (d.backend_version) {
      _localVersion = String(d.backend_version).replace(/^v/i, "");
    }
  } catch (e) {
    // v2.1.79 — Track failure duration + surface diagnostic UI.
    const now = Date.now();
    if (_diag.firstFailAt === 0) _diag.firstFailAt = now;
    _diag.lastFailAt = now;
    _diag.consecutiveFailures += 1;
    _diag.lastError = summariseError(e);
    const downMs = now - _diag.firstFailAt;

    // Progressive status copy so the customer sees the app IS aware
    // of the problem instead of a mysterious perpetual "checking…".
    if (downMs >= BACKEND_FATAL_MS) {
      setPill("connection-pill", "Backend offline", "danger");
      setDot("backend-dot", "danger");
      setText("backend-detail",
        `not responding for ${humanElapsed(downMs)} — service may have crashed`);
    } else if (downMs >= BACKEND_WARN_MS) {
      setPill("connection-pill", "Backend not responding", "warn");
      setDot("backend-dot", "warn");
      setText("backend-detail",
        `no reply for ${humanElapsed(downMs)} · ${_diag.lastError}`);
    } else {
      setPill("connection-pill", "Backend starting…", "warn");
      setDot("backend-dot", "warn");
      setText("backend-detail", "service is starting up (~10s on first boot)");
    }

    // Downstream cards can't be fresh either — mark them unknown so
    // the UI stops lying with a stale "checking…" for hours.
    setDot("db-dot", "unknown");
    setText("db-detail", _diag.everSucceeded ? "last check failed" : "waiting for backend");
    setDot("cloud-dot", "unknown");
    setText("cloud-detail", _diag.everSucceeded ? "last check failed" : "waiting for backend");

    // Escalate to Diagnose panel once we're clearly past normal boot.
    if (downMs >= BACKEND_ESCALATE_MS) {
      showDiagnosePanel(downMs);
    }
  }
}

function renderJobs(container, jobs, emptyMsg) {
  if (!container) return;
  if (!jobs || jobs.length === 0) {
    container.innerHTML = `<div class="jobs-empty">${emptyMsg}</div>`;
    return;
  }
  container.innerHTML = jobs.map((j) => `
    <div class="job-item">
      <div>
        <div>${escapeHtml(j.kind || "job")} · <span class="job-status-${escapeHtml(j.status || "running")}">${escapeHtml(j.status || "running")}</span></div>
        <div class="job-item-meta">${escapeHtml(j.detail || "")}</div>
      </div>
      <div class="job-item-meta">${escapeHtml(j.started_ago || "")}</div>
    </div>
  `).join("");
}

/* ── Dependencies grid (v2.1.59) ──────────────────────────────────
 * Surfaces the install state of every external binary a Krexion
 * feature needs (Playwright Chromium for RUT/VR/Browser-Profiles,
 * adb for CPI, the Playwright package itself, …) so the customer
 * sees at a glance which features are usable RIGHT NOW vs still
 * installing. Previously this only got surfaced once they CLICKED
 * Launch and the launch failed, leading to "kuch kaam ni krta" reports.
 */
const DEP_LABELS = {
  playwright: "Playwright (engine)",
  chromium:   "Chromium browser",
  adb:        "ADB (Android CPI)",
};
function renderDeps(deps) {
  const container = document.getElementById("deps-list");
  const summary = document.getElementById("deps-summary");
  if (!container) return;
  const keys = Object.keys(deps || {});
  if (keys.length === 0) {
    container.innerHTML = `<div class="jobs-empty">No dependency info available.</div>`;
    if (summary) summary.textContent = "—";
    return;
  }
  // Summary count
  let okCount = 0;
  let warnCount = 0;
  let failCount = 0;
  keys.forEach((k) => {
    const s = (deps[k]?.status || "error").toLowerCase();
    if (s === "ok") okCount++;
    else if (s === "installing") warnCount++;
    else failCount++;
  });
  if (summary) {
    summary.textContent = `${okCount}/${keys.length} ready` +
      (warnCount ? ` · ${warnCount} installing` : "") +
      (failCount ? ` · ${failCount} missing` : "");
  }
  container.innerHTML = keys.map((k) => {
    const d = deps[k] || {};
    const s = (d.status || "error").toLowerCase();
    const label = DEP_LABELS[k] || k;
    const dotClass = (s === "ok") ? "dot-ok"
                   : (s === "installing") ? "dot-warn"
                   : (s === "missing") ? "dot-danger"
                   : "dot-unknown";
    const stateText = (s === "ok") ? "ready"
                    : (s === "installing") ? "installing…"
                    : (s === "missing") ? "missing"
                    : "error";
    const msg = escapeHtml(d.message || "");
    return `
      <div class="dep-item">
        <span class="dot ${dotClass}"></span>
        <div class="dep-body">
          <div class="dep-label">${escapeHtml(label)} · <span class="job-status-${(s === 'ok') ? 'completed' : (s === 'missing' || s === 'error') ? 'failed' : 'running'}">${stateText}</span></div>
          ${msg ? `<div class="job-item-meta">${msg}</div>` : ""}
        </div>
      </div>
    `;
  }).join("");
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ── Diagnose panel (v2.1.79) ────────────────────────────────────
 * Surfaces WHY the local backend isn't responding once we've been
 * failing for >20 s. Prevents the "2 hours stuck on checking…"
 * silent-failure mode. Shows retry count, downtime, last error,
 * and actionable steps (open logs folder path, restart guidance).
 */
function summariseError(e) {
  if (!e) return "unknown error";
  const name = e.name || "";
  const msg = e.message || String(e);
  if (name === "AbortError") return "request timed out (>4s)";
  if (/Failed to fetch|NetworkError|network/i.test(msg)) return "cannot reach 127.0.0.1:8001 (service not running?)";
  if (/^HTTP 5\d\d/.test(msg)) return "backend returned " + msg + " (internal error)";
  if (/^HTTP 4\d\d/.test(msg)) return "backend returned " + msg;
  return msg.length > 80 ? msg.slice(0, 80) + "…" : msg;
}

function humanElapsed(ms) {
  if (ms < 1000) return "<1s";
  const s = Math.floor(ms / 1000);
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  const remS = s % 60;
  if (m < 60) return `${m}m ${remS}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${remM}m`;
}

function showDiagnosePanel(downMs) {
  const panel = $("diagnose-panel");
  if (!panel) return;
  panel.classList.remove("hidden");
  // Severity-based header colour: warn under 60s, danger past that.
  panel.classList.toggle("diagnose-danger", downMs >= BACKEND_FATAL_MS);
  setText("diag-downtime", humanElapsed(downMs));
  setText("diag-retries", String(_diag.consecutiveFailures));
  setText("diag-error", _diag.lastError || "—");
  // Show a friendly line about whether backend ever answered this session.
  setText("diag-history",
    _diag.everSucceeded
      ? "Backend was responding earlier and then stopped — the KrexionBackend Windows service may have crashed."
      : "Backend has never responded since Krexion started — the KrexionBackend Windows service may not have started at all."
  );

  // v2.1.81 — Fire ONE silent auto-repair per outage on first panel
  // open. Most customer PCs recover here: the service just needs a
  // `sc start` because MongoDB wasn't up when it first tried to boot.
  // Zero click for the customer if it works; UI still shows manual
  // options if it fails.
  if (!_diag.autoRepairAttempted && downMs >= AUTO_REPAIR_ONCE_MS) {
    _diag.autoRepairAttempted = true;
    tryAutoRepair();
  }
  // Refresh the service-state badges so the customer sees what's
  // actually going on with the NSSM services on their PC.
  refreshServiceState();
}
function hideDiagnosePanel() {
  const panel = $("diagnose-panel");
  if (!panel) return;
  panel.classList.add("hidden");
  panel.classList.remove("diagnose-danger");
}

/* Kick the poll loop immediately when the customer clicks Retry —
 * don't make them wait up to POLL_LOCAL_MS for the next scheduled
 * cycle. Also flashes the button so they see something happened
 * even when the poll fails again. */
async function diagnoseRetryNow() {
  const btn = $("diag-retry-btn");
  if (btn) {
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Repairing…";
    try {
      // v2.1.81 — Manual Retry ALWAYS tries a fresh restart-services
      // attempt first (unlike the auto-repair which only fires once
      // per outage). If the JS bridge isn't available we just fall
      // through to the poll, matching v2.1.79 behaviour.
      await tryAutoRepair(true);
      // Give NSSM ~2 s for the service to reach LISTEN state before
      // we retry the HTTP fetch; otherwise "Retry Now" always shows
      // one more failure even when the repair actually worked.
      await new Promise((r) => setTimeout(r, 2000));
      await pollLocal();
    } catch (_) {}
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = original;
    }, 800);
  } else {
    await pollLocal();
  }
}

/* v2.1.81 — Silent (or explicit) auto-repair through the pywebview
 * bridge. Runs `sc start KrexionDatabase` then `sc start KrexionBackend`
 * on the customer's PC. Gracefully no-ops when opened outside PyWebView
 * (dev / repair mode via file://). */
async function tryAutoRepair(explicit) {
  const api = _pyapi();
  if (!api || !api.restart_services) {
    if (explicit) {
      // Only surface the "no bridge" message on manual clicks so the
      // customer knows why the button appears to do nothing when the
      // dashboard is opened via file:// instead of the tray launcher.
      const el = $("diag-repair-result");
      if (el) {
        el.textContent = "Auto-repair unavailable in this window mode. Use the manual steps below.";
        el.classList.remove("hidden");
      }
    }
    return { ok: false, error: "no bridge" };
  }
  try {
    const res = await api.restart_services();
    _diag.autoRepairResult = res || {};
    const el = $("diag-repair-result");
    if (el) {
      el.classList.remove("hidden");
      const svcs = (res && res.services) || {};
      const parts = [];
      for (const name of ["KrexionDatabase", "KrexionBackend"]) {
        const s = svcs[name] || {};
        if (s.already_running) {
          parts.push(`${name}: already running`);
        } else if (s.not_installed) {
          parts.push(`${name}: NOT INSTALLED (reinstall required)`);
        } else if (s.ok) {
          parts.push(`${name}: started ✓`);
        } else {
          parts.push(`${name}: start failed (${s.state_after || "?"})`);
        }
      }
      el.textContent = parts.join("  ·  ");
    }
    return res;
  } catch (err) {
    _diag.autoRepairResult = { ok: false, error: String(err) };
    return _diag.autoRepairResult;
  }
}

/* Populate the service-state pills so the customer sees whether
 * KrexionBackend / KrexionDatabase are RUNNING / STOPPED / NOT_INSTALLED
 * without leaving the dashboard. Called when the Diagnose panel opens. */
async function refreshServiceState() {
  const api = _pyapi();
  const bBadge = $("diag-svc-backend");
  const dBadge = $("diag-svc-database");
  if (!api || !api.check_services) {
    if (bBadge) bBadge.textContent = "(open dashboard via tray icon to enable auto-diagnose)";
    if (dBadge) dBadge.textContent = "";
    return;
  }
  try {
    const res = await api.check_services();
    if (bBadge) {
      const st = (res.backend && res.backend.state) || "UNKNOWN";
      bBadge.textContent = `KrexionBackend: ${st}`;
      bBadge.className = "diag-svc-badge " + _svcClass(st);
    }
    if (dBadge) {
      const st = (res.database && res.database.state) || "UNKNOWN";
      dBadge.textContent = `KrexionDatabase: ${st}`;
      dBadge.className = "diag-svc-badge " + _svcClass(st);
    }
  } catch (err) {
    if (bBadge) bBadge.textContent = "service state check failed";
  }
}
function _svcClass(state) {
  if (state === "RUNNING") return "diag-svc-ok";
  if (state === "STOPPED" || state === "NOT_INSTALLED") return "diag-svc-danger";
  return "diag-svc-warn";
}

/* Toggle the "Show Backend Log" panel — reads the last 30 lines of
 * backend.stderr.log through the JS bridge. Lets the customer (or
 * support) see WHY the service crashed on boot without leaving the
 * app. Falls back to just showing the log file path if the bridge
 * isn't available. */
async function showBackendLogTail() {
  const wrap = $("diag-log-tail-wrap");
  const pre = $("diag-log-tail");
  if (!wrap || !pre) return;
  wrap.classList.remove("hidden");
  pre.textContent = "Loading last 30 lines…";
  const api = _pyapi();
  if (!api || !api.read_backend_log_tail) {
    pre.textContent = "Log preview needs the tray-launched dashboard. Open the log file at the path above instead.";
    return;
  }
  try {
    const res = await api.read_backend_log_tail(30);
    if (res && res.ok && res.tail) {
      pre.textContent = res.tail;
    } else {
      pre.textContent = (res && res.error) || "Could not read backend.stderr.log — check the path shown above.";
    }
  } catch (err) {
    pre.textContent = String(err);
  }
}

/* Open the logs folder in Explorer via the JS bridge (falls back
 * to a message if opened outside PyWebView). */
async function openLogsFolder() {
  const api = _pyapi();
  if (!api || !api.open_logs_folder) return;
  try { await api.open_logs_folder(); } catch (_) {}
}

/* ── Auto-update banner + blink notify icon ─────────────────────── */
function _parseSemver(v) {
  const m = String(v || "").trim().replace(/^v/i, "").match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!m) return [0, 0, 0];
  return [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)];
}
function _isNewer(remote, local) {
  const a = _parseSemver(remote);
  const b = _parseSemver(local);
  for (let i = 0; i < 3; i++) {
    if (a[i] > b[i]) return true;
    if (a[i] < b[i]) return false;
  }
  return false;
}

function _showUpdateBanner() {
  const banner = $("update-banner");
  if (!banner || !_updateUi.available) return;
  banner.classList.remove("hidden");
  const v = _updateUi.latestVersion || "newer";
  const you = _localVersion || "—";
  setText("update-version", `Krexion ${v} is available  (you have ${you})`);
  setText(
    "update-notes",
    _updateUi.title
      || "Click Update Now — downloads & installs here. No website visit needed. Krexion restarts automatically."
  );
  banner.dataset.targetVersion = v;
}

function _renderUpdateNotify() {
  const btn = $("update-notify-btn");
  if (!btn) return;
  if (_updateUi.available) {
    btn.classList.remove("hidden");
    btn.title = `Krexion ${_updateUi.latestVersion} available — click to update`;
    const dismissed = sessionStorage.getItem("krexion_update_dismissed_" + _updateUi.latestVersion) === "1";
    if (!dismissed) _showUpdateBanner();
    else $("update-banner")?.classList.add("hidden");
  } else {
    btn.classList.add("hidden");
    $("update-banner")?.classList.add("hidden");
  }
}

async function pollUpdate() {
  try {
    // Wait until we know our installed version so cloud can compare correctly.
    const current = (_localVersion || "").replace(/^v/i, "");
    const qs = current ? `?current=${encodeURIComponent(current)}` : "";
    const r = await fetch(`${CLOUD}/api/system/public-latest${qs}`, { cache: "no-store" });
    if (!r.ok) return;
    const d = await r.json();
    const latestVer = (d.latest && d.latest.version) ? String(d.latest.version).replace(/^v/i, "") : "";
    // Prefer server flag when we sent current=; also compare client-side
    // so older cloud builds (without the ?current= fix) still work.
    let available = !!(d.update_available && latestVer);
    if (latestVer && current && _isNewer(latestVer, current)) {
      available = true;
    }
    if (available && latestVer) {
      _updateUi.available = true;
      _updateUi.latestVersion = latestVer;
      _updateUi.title = (d.latest && d.latest.title) || "";
      _updateUi.notes = (d.latest && d.latest.notes) || "";
    } else {
      _updateUi.available = false;
      _updateUi.latestVersion = "";
    }
    _renderUpdateNotify();
  } catch (e) {
    // silent — notify stays hidden if cloud is unreachable
  }
}

async function applyUpdate() {
  const btn = $("update-now-btn");
  const banner = $("update-banner");
  const target = banner?.dataset?.targetVersion || _updateUi.latestVersion || "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Downloading…";
  }
  try {
    const r = await fetch(`${LOCAL}/api/desktop/run-update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_version: target }),
    });
    const d = await r.json();
    if (d.ok) {
      if (btn) btn.textContent = "Installing — Krexion will restart…";
      const notify = $("update-notify-btn");
      if (notify) {
        notify.classList.remove("hidden");
        const label = notify.querySelector(".update-notify-label");
        if (label) label.textContent = "Installing…";
      }
    } else {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Update Now";
      }
      alert("Update failed: " + (d.message || "unknown error"));
    }
  } catch (e) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Update Now";
    }
    alert("Could not reach the local Krexion service. Make sure Backend Online is green, then try again.");
  }
}

/* ── Wire it up ─────────────────────────────────────────────────── */
function init() {
  $("open-cloud-btn").addEventListener("click", () => {
    // v1.0.14: always open krexion.com (per product design - the cloud
    // UI is authoritative for ALL feature submissions; heavy jobs are
    // automatically routed to this PC via the bridge worker so they
    // execute locally without the user ever leaving krexion.com).
    try { window.open(CLOUD + "/login", "_blank"); }
    catch (e) { window.location.href = CLOUD + "/login"; }
  });
  $("update-now-btn").addEventListener("click", applyUpdate);
  $("update-dismiss-btn").addEventListener("click", () => {
    const v = $("update-banner")?.dataset?.targetVersion || _updateUi.latestVersion;
    if (v) sessionStorage.setItem("krexion_update_dismissed_" + v, "1");
    $("update-banner").classList.add("hidden");
    // Keep the blinking Update pill so they can still open it later.
  });
  const notifyBtn = $("update-notify-btn");
  if (notifyBtn) {
    notifyBtn.addEventListener("click", () => {
      const v = _updateUi.latestVersion;
      if (v) sessionStorage.removeItem("krexion_update_dismissed_" + v);
      _showUpdateBanner();
    });
  }

  // v2.1.79 — Diagnose panel wiring (retry + copy-logs-path helpers).
  const retryBtn = $("diag-retry-btn");
  if (retryBtn) retryBtn.addEventListener("click", diagnoseRetryNow);
  const copyBtn = $("diag-copy-path-btn");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const path = "C:\\Program Files\\Krexion\\logs\\backend.stderr.log";
      try {
        await navigator.clipboard.writeText(path);
        copyBtn.textContent = "Copied ✓";
        setTimeout(() => { copyBtn.textContent = "Copy Logs Path"; }, 1500);
      } catch {
        copyBtn.textContent = "Copy failed";
        setTimeout(() => { copyBtn.textContent = "Copy Logs Path"; }, 1500);
      }
    });
  }
  // v2.1.81 — Open logs folder (Explorer) + Show last 30 lines of backend.stderr.log.
  const openLogsBtn = $("diag-open-logs-btn");
  if (openLogsBtn) openLogsBtn.addEventListener("click", openLogsFolder);
  const showLogBtn = $("diag-show-log-btn");
  if (showLogBtn) showLogBtn.addEventListener("click", showBackendLogTail);

  pollLocal();
  // First update check after local version is known (~2s), again at 15s
  // (VERSION may arrive slightly later), then every 5 min.
  setTimeout(pollUpdate, 2000);
  setTimeout(pollUpdate, 15000);
  setInterval(pollUpdate, POLL_CLOUD_MS);
  setInterval(pollLocal, POLL_LOCAL_MS);
}

document.addEventListener("DOMContentLoaded", init);
