import { useState, useEffect, useRef, useMemo } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { Textarea } from "../components/ui/textarea";
import { toast } from "sonner";
import ProxyProviderSelect from "../components/ProxyProviderSelect";
import {
  Fingerprint,
  Play,
  RefreshCw,
  Download,
  Trash2,
  StopCircle,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileSpreadsheet,
  Globe,
  Sheet as SheetIcon,
  ClipboardCheck,
  Radio,
  Apple,
  Monitor,
  Activity,
  X,
  Zap,
  Loader2,
  Pause,
  Play as PlayIcon,
  MousePointer,
  Hand,
  Keyboard,
  ArrowUpDown,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

const COUNTRY_CHIPS = [
  "Pakistan", "India", "United States", "United Kingdom", "Canada", "Australia",
  "Germany", "France", "Italy", "Spain", "Netherlands", "Brazil", "Mexico",
  "United Arab Emirates", "Saudi Arabia", "Turkey", "Indonesia", "Philippines",
  "Thailand", "Vietnam", "Japan", "South Korea", "Nigeria", "South Africa", "Egypt",
];

const OS_CHIPS = [
  { key: "android", label: "Android" },
  { key: "ios", label: "iOS" },
  { key: "windows", label: "Windows" },
  { key: "macos", label: "macOS" },
  { key: "linux", label: "Linux" },
];

const PACING_PRESETS = [
  { label: "1m", value: 1 },
  { label: "5m", value: 5 },
  { label: "10m", value: 10 },
  { label: "20m", value: 20 },
  { label: "30m", value: 30 },
  { label: "60m", value: 60 },
  { label: "Instant", value: 0 },
];

function StatusBadge({ status }) {
  const map = {
    completed: "bg-emerald-900/50 text-emerald-200 border-emerald-800",
    running: "bg-blue-900/50 text-blue-200 border-blue-800",
    queued: "bg-blue-900/50 text-blue-200 border-blue-800",
    preparing: "bg-cyan-900/50 text-cyan-200 border-cyan-800",
    failed: "bg-red-900/50 text-red-200 border-red-800",
    stopped: "bg-orange-900/50 text-orange-200 border-orange-800",
    ok: "bg-emerald-900/50 text-emerald-200 border-emerald-800",
    skipped_captcha: "bg-amber-900/50 text-amber-200 border-amber-800",
    skipped_country: "bg-amber-900/50 text-amber-200 border-amber-800",
    skipped_os: "bg-amber-900/50 text-amber-200 border-amber-800",
    skipped_duplicate_ip: "bg-amber-900/50 text-amber-200 border-amber-800",
    skipped_vpn: "bg-amber-900/50 text-amber-200 border-amber-800",
    no_fields_matched: "bg-zinc-800 text-zinc-300 border-zinc-700",
    submitted_but_no_redirect: "bg-indigo-900/50 text-indigo-200 border-indigo-800",
  };
  return (
    <Badge className={`border ${map[status] || "bg-zinc-800 text-zinc-300 border-zinc-700"}`}>
      {status}
    </Badge>
  );
}

function EngineStatusBadge({ status, onPrewarm, prewarming }) {
  // status = { status: "ready"|"installing"|"missing"|"error", message, expected_revision }
  const s = status?.status || "ready";
  const config = {
    ready: {
      dotClass: "bg-emerald-400 shadow-emerald-400/50",
      pulse: false,
      borderClass: "border-emerald-800/60 bg-emerald-950/30",
      textClass: "text-emerald-200",
      labelClass: "text-emerald-300",
      label: "Engine Ready",
    },
    installing: {
      dotClass: "bg-amber-400 shadow-amber-400/50",
      pulse: true,
      borderClass: "border-amber-800/60 bg-amber-950/30",
      textClass: "text-amber-200",
      labelClass: "text-amber-300",
      label: "Installing…",
    },
    missing: {
      dotClass: "bg-red-400 shadow-red-400/50",
      pulse: false,
      borderClass: "border-red-800/60 bg-red-950/30",
      textClass: "text-red-200",
      labelClass: "text-red-300",
      label: "Engine Missing",
    },
    error: {
      dotClass: "bg-red-400 shadow-red-400/50",
      pulse: false,
      borderClass: "border-red-800/60 bg-red-950/30",
      textClass: "text-red-200",
      labelClass: "text-red-300",
      label: "Engine Error",
    },
  }[s] || {
    dotClass: "bg-zinc-400",
    pulse: false,
    borderClass: "border-zinc-700 bg-zinc-900",
    textClass: "text-zinc-300",
    labelClass: "text-zinc-300",
    label: "Engine",
  };

  // Show prewarm button only when engine is NOT ready and NOT actively
  // installing (so users don't double-click while a download is in progress).
  const canPrewarm = s === "missing" || s === "error";

  return (
    <div
      data-testid="rut-engine-status-badge"
      data-engine-status={s}
      title={status?.message || config.label}
      className={`flex-shrink-0 flex items-center gap-3 px-3 py-2 rounded-lg border ${config.borderClass} text-xs`}
    >
      <span className="relative flex w-2.5 h-2.5">
        {config.pulse && (
          <span className={`absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping ${config.dotClass}`}></span>
        )}
        <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${config.dotClass} shadow`}></span>
      </span>
      <div className="flex flex-col leading-tight">
        <span className={`font-semibold ${config.labelClass}`}>{config.label}</span>
        <span className={`${config.textClass} text-[11px] opacity-80`}>
          {status?.expected_revision ? `Chromium rev ${status.expected_revision}` : (status?.message || "")}
        </span>
      </div>
      {canPrewarm && onPrewarm && (
        <button
          type="button"
          data-testid="rut-engine-prewarm-btn"
          onClick={onPrewarm}
          disabled={prewarming}
          className="ml-1 px-2.5 py-1.5 rounded-md text-[11px] font-semibold border border-amber-700/60 bg-amber-900/40 text-amber-100 hover:bg-amber-900/70 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
        >
          <Zap size={12} />
          {prewarming ? "Starting…" : "Pre-warm"}
        </button>
      )}
    </div>
  );
}

// Device-mix widget palette. Keys are `os_tag` values used by uploaded
// UA batches. Unknown keys fall through to `other`.
const DEVICE_MIX_COLORS = {
  android:  "rgb(110, 231, 183)",   // emerald-300
  ios:      "rgb(165, 180, 252)",   // indigo-300
  windows:  "rgb(251, 191, 36)",    // amber-400
  macos:    "rgb(203, 213, 225)",   // slate-300
  linux:    "rgb(252, 165, 165)",   // red-300
  other:    "rgb(148, 163, 184)",   // slate-400
};
const DEVICE_MIX_LABELS = {
  android:  "Android",
  ios:      "iOS (iPhone/iPad)",
  windows:  "Windows",
  macos:    "macOS",
  linux:    "Linux",
  other:    "Other",
};


// ──────────────────────────────────────────────────────────────────────
// 2026-06-11: Reusable multi-select with per-key % sliders.
// Used by Pro Mode for the platform-mix AND the email-source-mix.
// Customer ticks the keys they want, adjusts % via slider. Total auto-
// normalises (engine handles unequal sums fine — weights are relative).
// ──────────────────────────────────────────────────────────────────────
function ReferrerProMultiSelect({ title, description, keys, weights, onChange, accent = "fuchsia", testIdPrefix }) {
  // Total for the live indicator
  const total = Object.values(weights || {}).reduce((s, w) => s + (parseFloat(w) || 0), 0);
  const accentClasses = {
    fuchsia: { ring: "border-fuchsia-700/40", bg: "bg-fuchsia-950/20", text: "text-fuchsia-300", slider: "accent-fuchsia-500" },
    emerald: { ring: "border-emerald-700/40", bg: "bg-emerald-950/20", text: "text-emerald-300", slider: "accent-emerald-500" },
    cyan:    { ring: "border-cyan-700/40",    bg: "bg-cyan-950/20",    text: "text-cyan-300",    slider: "accent-cyan-500" },
  }[accent] || { ring: "border-fuchsia-700/40", bg: "bg-fuchsia-950/20", text: "text-fuchsia-300", slider: "accent-fuchsia-500" };

  const toggle = (k) => {
    const next = { ...(weights || {}) };
    if (next[k] === undefined) {
      // Default new entry to remaining-balance or 10
      const remaining = Math.max(0, 100 - total);
      next[k] = remaining > 0 ? Math.min(remaining, 20) : 10;
    } else {
      delete next[k];
    }
    onChange(next);
  };
  const setWeight = (k, w) => {
    const next = { ...(weights || {}) };
    next[k] = Math.max(0, Math.min(100, parseFloat(w) || 0));
    if (next[k] === 0) delete next[k];
    onChange(next);
  };
  const resetEqual = () => {
    const active = Object.keys(weights || {});
    if (active.length === 0) return;
    const each = Math.round(100 / active.length);
    const next = {};
    active.forEach((k, i) => {
      next[k] = i === active.length - 1 ? 100 - each * (active.length - 1) : each;
    });
    onChange(next);
  };
  const clearAll = () => onChange({});

  return (
    <div className={`p-3 rounded-md border ${accentClasses.ring} ${accentClasses.bg}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className={`text-sm font-semibold ${accentClasses.text}`}>{title}</div>
          {description && (
            <div className="text-[11px] text-zinc-400 mt-0.5">{description}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400">
            Total: <span className={total >= 90 && total <= 110 ? "text-emerald-300 font-semibold" : "text-amber-400"}>{total.toFixed(0)}%</span>
          </span>
          <button
            data-testid={`${testIdPrefix}-reset`}
            type="button"
            onClick={resetEqual}
            className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 hover:bg-zinc-700"
          >
            Equal
          </button>
          <button
            data-testid={`${testIdPrefix}-clear`}
            type="button"
            onClick={clearAll}
            className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 hover:bg-zinc-700"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Chip selector */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(keys || []).map((k) => {
          const active = weights && weights[k] !== undefined;
          return (
            <button
              key={k}
              data-testid={`${testIdPrefix}-chip-${k}`}
              type="button"
              onClick={() => toggle(k)}
              className={`text-[11px] px-2.5 py-1 rounded-full border transition ${
                active
                  ? `${accentClasses.text} border-current bg-zinc-900/80`
                  : "text-zinc-500 border-zinc-700 bg-zinc-900/40 hover:text-zinc-300"
              }`}
            >
              {k}{active ? ` (${(weights[k] || 0).toFixed(0)}%)` : ""}
            </button>
          );
        })}
      </div>

      {/* Sliders for active keys */}
      {Object.keys(weights || {}).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(weights).map(([k, w]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-24 text-xs text-zinc-300 truncate" title={k}>{k}</span>
              <input
                data-testid={`${testIdPrefix}-slider-${k}`}
                type="range"
                min={0}
                max={100}
                step={1}
                value={w}
                onChange={(e) => setWeight(k, e.target.value)}
                className={`flex-1 ${accentClasses.slider}`}
              />
              <input
                data-testid={`${testIdPrefix}-input-${k}`}
                type="number"
                min={0}
                max={100}
                value={w}
                onChange={(e) => setWeight(k, e.target.value)}
                className="w-14 bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-1 py-0.5 text-xs text-right"
              />
              <span className="text-xs text-zinc-500">%</span>
            </div>
          ))}
        </div>
      )}

      {Object.keys(weights || {}).length === 0 && (
        <div className="text-[11px] text-zinc-500 italic">No keys selected — click chips above to add. Engine will fall back to UA-derived behaviour for this visit.</div>
      )}
    </div>
  );
}


export default function RealUserTrafficPage() {
  // Target
  const [links, setLinks] = useState([]);
  const [linkId, setLinkId] = useState("");
  const [targetUrlOverride, setTargetUrlOverride] = useState("");
  // AI Learning panel state — historical answer→conversion stats per offer host
  const [aiLearning, setAiLearning] = useState(null);
  const [aiLearningLoading, setAiLearningLoading] = useState(false);

  // Target Screenshot Verification — user uploads a reference image of the
  // expected final/thank-you page so the bot can pHash-verify each visit
  // actually reached that destination (not just heuristic host-change).
  const [targetScreenshotFile, setTargetScreenshotFile] = useState(null);
  const [targetScreenshotPreview, setTargetScreenshotPreview] = useState("");
  const [targetScreenshotThreshold, setTargetScreenshotThreshold] = useState(12);

  // Compute the offer URL that AI Learning will key against (override > selected link)
  const effectiveOfferUrl = useMemo(() => {
    if (targetUrlOverride && targetUrlOverride.trim()) return targetUrlOverride.trim();
    const link = (links || []).find((l) => l.id === linkId);
    return link?.offer_url || "";
  }, [targetUrlOverride, linkId, links]);

  const fetchAiLearning = async () => {
    if (!effectiveOfferUrl) {
      setAiLearning(null);
      return;
    }
    setAiLearningLoading(true);
    try {
      const r = await fetch(
        `${API}/real-user-traffic/ai-learning?offer_url=${encodeURIComponent(effectiveOfferUrl)}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (r.ok) {
        const data = await r.json();
        setAiLearning(data);
      } else {
        setAiLearning(null);
      }
    } catch (e) {
      setAiLearning(null);
    } finally {
      setAiLearningLoading(false);
    }
  };

  // Auto-fetch when offer URL changes (debounced 500ms)
  useEffect(() => {
    if (!effectiveOfferUrl) {
      setAiLearning(null);
      return;
    }
    const t = setTimeout(() => fetchAiLearning(), 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveOfferUrl]);

  // Proxies & UAs
  const [proxies, setProxies] = useState("");
  const [userAgents, setUserAgents] = useState("");
  // v2.6.29 — accept UAs stashed from User Agent Generator page
  useEffect(() => {
    try {
      const stash = localStorage.getItem("ua_generator_payload");
      if (stash && stash.trim()) {
        setUserAgents(stash.trim());
        localStorage.removeItem("ua_generator_payload");
        toast.success("User agents loaded from UA Generator");
      }
      const vrStash = localStorage.getItem("vr_automation_handoff");
      if (vrStash && vrStash.trim()) {
        const parsed = JSON.parse(vrStash);
        localStorage.removeItem("vr_automation_handoff");
        const steps = parsed?.automation_json ?? parsed?.steps;
        if (steps) {
          setFormFillEnabled(true);
          setUseCustomJson(true);
          setAutomationJson(
            typeof steps === "string" ? steps : JSON.stringify(steps, null, 2)
          );
          if (parsed?.url) setTargetUrlOverride(parsed.url);
          toast.success("Automation JSON loaded from Visual Recorder");
        }
      }
    } catch { /* ignore */ }
  }, []);
  const [useStoredProxies, setUseStoredProxies] = useState(false);
  // ── Auto Mode (via Proxy Provider) ─────────────────────────────
  // When ON, the user does NOT have to paste / upload any proxies —
  // the backend auto-generates a fresh batch from whichever provider
  // was selected in the Proxy source dropdown above. (v2.6.2: any
  // provider works — the ProxyJet-specific fallback path has been
  // removed. A provider MUST be selected for Auto Mode to run.)
  const [useProxyJetAuto, setUseProxyJetAuto] = useState(false);  // 2026-01: per-job stuck-watchdog inactivity threshold (seconds).
  // Pages where the URL doesn't change for longer than this are
  // force-aborted. Default raised from old hardcoded 25 → 60 → 240
  // (2026-05) → 600 (2026-06-27, user request — survey-heavy multi-
  // deal offers like target 750 v10 need 10+ min on slow pages).
  // chrome-error:// fast-path still fires instantly for dead proxies
  // / DNS failures (handled in backend watchdog).
  const [stuckWatchdogSeconds, setStuckWatchdogSeconds] = useState(600);
  // Geo hints — sent to the backend as `proxyjet_country` /
  // `proxyjet_state` (wire-name preserved for backward compat) but
  // labelled generically in the UI. Non-native providers ignore
  // these server-side; native ProxyJet-style providers use them.
  const [proxyJetCountry, setProxyJetCountry] = useState("US");
  const [proxyJetState, setProxyJetState] = useState("");
  // v2.4.0 — Selected Proxy Provider (from Settings › Proxy Providers).
  const [proxyProviderId, setProxyProviderId] = useState("");
  // v2.5.0 — Kind of the currently-selected provider, fetched lazily
  // when proxyProviderId changes.
  const [proxyProviderKind, setProxyProviderKind] = useState("");
  // ── Multi-Geo MIX ──────────────────────────
  // When `pjGeoMode === "many"`, the engine picks a random
  // country/state per visit from these pools. Single mode preserves
  // the legacy geo hint behaviour exactly.
  const [pjGeoMode, setPjGeoMode] = useState("one");   // "one" | "many"
  const [pjCountriesPool, setPjCountriesPool] = useState([]);
  const [pjStatesPool, setPjStatesPool] = useState([]);
  // ── Inline UA Generator (so user doesn't have to leave RUT page) ──
  const [uaGenOpen, setUaGenOpen] = useState(false);
  const [uaGenApp, setUaGenApp] = useState("chrome");
  const [uaGenPlatform, setUaGenPlatform] = useState("android");
  const [uaGenCount, setUaGenCount] = useState(50);
  const [uaGenBusy, setUaGenBusy] = useState(false);

  // Uploaded Things — saved batch IDs (alternative to paste)
  const [uploadedLibrary, setUploadedLibrary] = useState([]);
  const [selectedUploadProxyId, setSelectedUploadProxyId] = useState("");
  // ── 2026-06-11: Multi-batch uploaded proxies ───────────────────
  // When 2+ batch IDs are selected, the backend merges + dedupes +
  // shuffles them so the run picks a random interleave across all
  // batches (e.g. US-CA + US-TX + DE-Berlin batches all blended).
  // Single batch falls back to the legacy `upload_proxy_id` flow.
  const [selectedUploadProxyIds, setSelectedUploadProxyIds] = useState([]);
  const [selectedUploadUaId, setSelectedUploadUaId] = useState("");         // legacy single-select (kept for backward compat)
  const [selectedUploadUaIds, setSelectedUploadUaIds] = useState([]);       // NEW: multi-select device UA batches
  const [selectedUploadDataId, setSelectedUploadDataId] = useState("");

  // Compute device-mix distribution from the selected UA batches. Runs
  // purely on the client so the user sees an *estimated* OS split the
  // moment they check/uncheck a batch — no backend call. Groups by the
  // batch's `os_tag` (user-provided label) and weights by `available_count`
  // (falls back to `item_count` for legacy docs). Skips depleted batches.
  const deviceMix = (() => {
    const totals = {};
    let grand = 0;
    uploadedLibrary.forEach((u) => {
      if (u.type !== "user_agents") return;
      if (!selectedUploadUaIds.includes(u.id)) return;
      const avail = Number(u.available_count ?? u.item_count ?? 0);
      if (avail <= 0) return;
      const key = ((u.os_tag || "other") + "").toLowerCase();
      totals[key] = (totals[key] || 0) + avail;
      grand += avail;
    });
    const entries = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    return { entries, grand };
  })();

  // Run settings
  const [totalClicks, setTotalClicks] = useState(10);
  const [concurrency, setConcurrency] = useState(15);
  const [durationMinutes, setDurationMinutes] = useState(0);
  // Target-mode: "clicks" = N fixed visits, "conversions" = keep trying
  // until X thank-you pages reached (capped by max_attempts for safety)
  const [targetMode, setTargetMode] = useState("clicks");
  const [targetConversions, setTargetConversions] = useState(10);
  const [maxAttempts, setMaxAttempts] = useState(100);

  // Filters
  const [allowedCountries, setAllowedCountries] = useState([]);
  const [allowedOs, setAllowedOs] = useState([]);
  const [skipDuplicateIp, setSkipDuplicateIp] = useState(true);
  const [skipVpn, setSkipVpn] = useState(true);
  const [followRedirect, setFollowRedirect] = useState(false);
  const [noRepeatedProxy, setNoRepeatedProxy] = useState(false);
  // When ON, every RUT visit is forced to route through the tracker URL
  // (/api/t/<short_code>) — server-side click counter, duplicate IP check
  // and link-stats all increment naturally. OFF (default) keeps the
  // preview-pod auto-bypass so residential proxies don't hit Cloudflare 403.
  const [forceTrackerUrl, setForceTrackerUrl] = useState(false);
  // 2026-07 v2.6.9 CUSTOMER-REQUEST — Tracker hard-block detection.
  // When ON: any visit that lands on a "Access Denied" / "Duplicate
  // Access" / "Close Manually" screen is instantly aborted so the IP
  // is burnt and the visit slot retries with a fresh proxy (saving
  // 10-30 s of wasted proxy time per blocked visit).
  const [abortOnTrackerBlock, setAbortOnTrackerBlock] = useState(true);
  const [trackerBlockExtraPatterns, setTrackerBlockExtraPatterns] = useState("");

  // Form-fill toggle
  const [formFillEnabled, setFormFillEnabled] = useState(false);
  const [dataSource, setDataSource] = useState("excel");
  const [file, setFile] = useState(null);
  const [gsheetUrl, setGsheetUrl] = useState("");
  const [pendingCandidates, setPendingCandidates] = useState([]);
  const [importPendingJobId, setImportPendingJobId] = useState("");
  const [stateMatchEnabled, setStateMatchEnabled] = useState(false);
  // ── Data-file preview / state-filter (auto-detected from uploaded data) ──
  // When the user picks a file (or selects an uploaded data batch) we call
  // /api/real-user-traffic/preview-data-file to get per-state row counts.
  // The user then ticks which states to run on; only those rows are used.
  const [dataPreview, setDataPreview] = useState(null);     // {total_rows, states:[{code,count}], quality, ...}
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedStates, setSelectedStates] = useState([]); // [] = no filter (use all)
  // ── 2026-06 — Email-domain filter (gmail / yahoo / hotmail …) ──
  // Mirrors `selectedStates`. Empty = no filter (use all rows whose
  // email is present). When a subset is ticked, only rows with those
  // domains pass through to the job.
  const [selectedEmailDomains, setSelectedEmailDomains] = useState([]);
  const [invalidDetectionEnabled, setInvalidDetectionEnabled] = useState(false);
  // 2026-06 — Max replacement leads per visit when invalid_detection_enabled
  // is ON. Was hard-coded to 3 inside the engine; now configurable so a
  // visit with dirty data can absorb up to 50 bad rows before giving up
  // (proxy/UA aren't wasted). Default 10.
  const [invalidDataRetryLimit, setInvalidDataRetryLimit] = useState(10);
  // 2026-06 — Step-wait multiplier. 1.0 = default per-step ceilings
  // (30-45s). Higher = wait longer per step before timeout (better
  // for slow offers / proxies). Range 0.5-5.0.
  const [stepTimeoutMultiplier, setStepTimeoutMultiplier] = useState(1);
  const [skipCaptcha, setSkipCaptcha] = useState(true);
  const [postSubmitWait, setPostSubmitWait] = useState(6);
  const [automationJson, setAutomationJson] = useState("");
  const [useCustomJson, setUseCustomJson] = useState(false);
  // ── 2026-07 — Native Smart Funnel (adaptive survey/form/deals) ──
  const [funnelMode, setFunnelMode] = useState("legacy"); // legacy | smart | custom
  const [smartFunnelPattern, setSmartFunnelPattern] = useState("auto");
  const [smartFunnelMinDeals, setSmartFunnelMinDeals] = useState(2);
  const [smartFunnelWaitUntilConversion, setSmartFunnelWaitUntilConversion] = useState(true);
  const [selectedUploadAjId, setSelectedUploadAjId] = useState("");
  const [selfHeal, setSelfHeal] = useState(true);
  // ── 2026-05: Pure JSON Mode ──
  // When ON, the runner strictly follows the recorded automation JSON
  // with NO AI involvement (self-heal forced off + AI answer-learning
  // bypassed). Default OFF — current behaviour unchanged.
  const [pureJsonMode, setPureJsonMode] = useState(false);
  // Default OFF — per user's explicit request: "job ek sequence mein
  // chale, resume na ho". When OFF, a backend restart marks the job
  // failed and the user clicks Retry manually. Predictable lifecycle.
  const [autoResumeEnabled, setAutoResumeEnabled] = useState(false);

  // ── 2026-02 v2.1.31 — Anti-Detect Phase 1 wiring ──
  // pacing_per_hour: 0 = legacy flat duration spacing.
  //                  >0 = log-normal jitter from PacingEngine.
  // identity_label: persistent cookies + fingerprint across runs.
  // tls_prewarm: real-Chrome JA3 curl_cffi handshake before goto.
  const [pacingPerHour, setPacingPerHour] = useState(0);
  const [identityLabel, setIdentityLabel] = useState("");
  const [tlsPrewarm, setTlsPrewarm] = useState(true);

  // ── 2026-02 v2.1.31 — Step 3: Multi-Hop Proxy Chain + Browser Variant ──
  const [proxyChainEnabled, setProxyChainEnabled] = useState(false);
  const [proxyChainUseTor, setProxyChainUseTor] = useState(true);
  const [proxyChainExtraHops, setProxyChainExtraHops] = useState("");
  const [browserVariant, setBrowserVariant] = useState("auto");
  const [adCapabilities, setAdCapabilities] = useState(null);

  // ── 2026-02 v2.1.31 — Step 4: Phase-4 Anti-Detect ──
  const [behavioralBioEnabled, setBehavioralBioEnabled] = useState(true);
  const [ipWarmupEnabled, setIpWarmupEnabled] = useState(true);

  // ── 2026-06-11: UNIFIED Anti-Detect master toggle ──
  // Single user-facing switch. When ON, all underlying flags above
  // are auto-set to production defaults. Customer never sees internals
  // (privacy by design — we don't tell end users what's running).
  const [antiDetectMaster, setAntiDetectMaster] = useState(false);

  // ── 2026-07 v2.2.1 — In-App Browser Preset (one-click "Traffic Source") ──
  // When set to a platform name (facebook / messenger / instagram / tiktok /
  // snapchat / linkedin / twitter), the backend engine automatically:
  //   • Forces Referer = https://www.<platform>.com/
  //   • Turns on UA→Referer coercion (adds FBAN/FBIOS, FB_IAB/FB4A,
  //     Instagram, musical_ly, Snapchat/, LinkedInApp, TwitterAndroid …)
  //   • Turns on pass-referer-to-offer (offer sees the platform Referer)
  //   • Replaces every desktop UA in the pool with a mobile UA
  // Result: every RUT visit is reported as "<Platform> In-App Browser"
  // on the advertiser dashboard — exactly like a real ad click.
  // Empty / "none" = advanced/custom (backward-compatible legacy path).
  const [inappBrowserPreset, setInappBrowserPreset] = useState("none");

  // ── 2026-06: Referrer Override (OFF by default — customer opt-in) ──
  // When OFF the engine uses the legacy UA-derived referer logic
  // (TikTok UA → tiktok.com, plain Chrome UA → no Referer).
  // When ON, the chosen mode below is applied per visit so the operator
  // can make traffic look like it originated from any platform.
  const [refererOverrideEnabled, setRefererOverrideEnabled] = useState(false);

  // ── 2026-07: Traffic Source Preset (SIMPLE MODE) ─────────────────────
  // Single-dropdown replacement for the 20+ granular toggles below so
  // non-technical customers can pick ONE meaningful business-mode and
  // let Krexion configure every downstream toggle consistently (no
  // conflicts possible). When set to "custom" the full advanced UI
  // appears exactly as before → power-users lose nothing.
  //
  // Default is "off" so existing customers see zero behaviour change
  // until they explicitly pick a preset. Picking any non-"off" preset
  // auto-enables refererOverrideEnabled and configures pool / realism
  // toggles below via the effect that follows.
  const [trafficSourcePreset, setTrafficSourcePreset] = useState("off");
  const [refererMode, setRefererMode] = useState("platform_pool");
  // ↑ Default mode is platform_pool (visually obvious "real social
  // traffic" look). The toggle is OFF by default so existing customer
  // jobs keep behaving exactly as before.
  const [refererValue, setRefererValue] = useState("");
  const [refererPlatformPool, setRefererPlatformPool] = useState(
    "facebook,tiktok,instagram,google"
  );
  // 2026-06: Optional brand identifier — when email is in the pool,
  // tracker tags visits with brand-aware UTMs (utm_source=<brand>_newsletter,
  // utm_campaign=<brand>_<base>). Helps customers claiming they market
  // for a specific brand produce consistent brand-labelled email signals.
  const [refererBrand, setRefererBrand] = useState("");

  // ── 2026-06-11: Referrer Pro-Mode (weighted multi-select pools) ──
  // Pro mode replaces the comma-list with a multi-select + per-platform
  // % slider UI. Customer fully controls traffic mix. Off by default →
  // backend uses legacy comma-list behaviour exactly as before.
  const [refererProMode, setRefererProMode] = useState(false);
  // Platform weights as an object: { facebook: 35, tiktok: 25, … }
  // Empty = no platform picked = legacy fallback.
  const [refererPlatformWeights, setRefererPlatformWeights] = useState({
    facebook: 35, tiktok: 25, instagram: 15, google: 15, email: 10,
  });
  // Email-bucket weights — empty / Gmail / Outlook / each ESP
  const [refererEmailWeights, setRefererEmailWeights] = useState({});
  // Realism toggles (default ON — modern bot-detection killer)
  const [refererSocialWrapper, setRefererSocialWrapper] = useState(true);
  const [refererInappDeep, setRefererInappDeep] = useState(true);
  const [refererStripSearchPath, setRefererStripSearchPath] = useState(true);
  const [refererNetworkClickChain, setRefererNetworkClickChain] = useState(false);
  // v2.6.25 — Paid vs Organic referer split (mirrors LinksPage dropdown).
  // "auto" preserves legacy behaviour so existing saved jobs keep working
  // identically. Operator can force paid / organic / mixed per job.
  const [refererTrafficType, setRefererTrafficType] = useState("auto");
  const [refererCampaignType, setRefererCampaignType] = useState("auto");
  // 2026-01 — Pass-Referer-To-Offer (direct offer navigation so the
  // offer sees the EXACT chosen Referer instead of Krexion origin).
  // Default OFF — preserves legacy behavior for existing users.
  const [refererPassToOffer, setRefererPassToOffer] = useState(false);
  // 2026-06-14 — UA ↔ Referer coercion (anti-fraud). When ON and the
  // resolved Referer is an in-app platform (FB/TikTok/IG/Snapchat/…)
  // the engine appends realistic in-app webview markers to the
  // per-visit mobile UA so Anura/IPQS/Forensiq/Singular/AppsFlyer
  // Protect360 don't flag the visit as bot due to a mismatched
  // Referer↔UA signature. Default ON — recommended for all paid-
  // social traffic.
  const [refererMatchUaToPlatform, setRefererMatchUaToPlatform] = useState(true);
  // Search-engine sub-options for the search-Referer rotation
  const [refererSearchEngine, setRefererSearchEngine] = useState("google");
  const [refererSearchKeywords, setRefererSearchKeywords] = useState("");
  // Defaults loaded from /api/referrer-pro/defaults (platforms list, ESP list, etc.)
  const [refererProDefaults, setRefererProDefaults] = useState({
    platforms: [], email_buckets: [], email_default_weights: {},
    search_engines: [], countries: [], intent_mixes: [],
  });
  // AI keyword generator state
  const [aiKwOffer, setAiKwOffer] = useState("");
  const [aiKwVertical, setAiKwVertical] = useState("");
  const [aiKwCountry, setAiKwCountry] = useState("us");
  const [aiKwIntent, setAiKwIntent] = useState("balanced");
  const [aiKwCount, setAiKwCount] = useState(15);
  const [aiKwLoading, setAiKwLoading] = useState(false);
  const [aiKwError, setAiKwError] = useState("");

  // ── 2026-07 v2.6.7: Saved-Traffic-Source-Presets (per-user) ─────────
  // Customer can customise the built-in Simple Mode preset (adjust
  // platform mix, set specific source URL, enable/disable realism
  // toggles) and save the whole config under a name. Next time they
  // open RUT they just pick their preset from the dropdown and every
  // toggle auto-fills — same UX as saved JSON automation profiles.
  const [myTrafficPresets, setMyTrafficPresets] = useState([]);
  const [selectedMyPresetId, setSelectedMyPresetId] = useState("");
  const [presetSaveOpen, setPresetSaveOpen] = useState(false);
  const [presetSaveName, setPresetSaveName] = useState("");
  const [presetSaving, setPresetSaving] = useState(false);
  const [presetSaveError, setPresetSaveError] = useState("");
  // Editable "source URL" — when set, becomes the exact Referer URL
  // (per-visit) even inside Simple-Mode presets. Empty = let the preset
  // pick a realistic source per platform.
  const [presetSourceUrl, setPresetSourceUrl] = useState("");
  // 2026-07 v2.6.7: fine-tune which of the preset's built-in platforms are
  // ACTIVE. `null` = use the preset's default. A Set of platform keys
  // = only those platforms contribute traffic. Empty Set means keep
  // preset defaults (safety fallback).
  const [presetPlatformFilter, setPresetPlatformFilter] = useState(null);
  // Advanced Options accordion inside Customize panel (v2.6.7)
  const [presetAdvancedOpen, setPresetAdvancedOpen] = useState(false);

  // Load saved traffic-source presets on mount
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/my-presets`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (Array.isArray(d)) setMyTrafficPresets(d);
      })
      .catch(() => {});
  }, []);

  // Keep the underlying refererValue in sync with the customer's
  // preset-level Source URL override. Behaviour (v2.6.7 upgrade):
  //   - empty         → preset picks its own realistic source per platform
  //   - 1 URL         → mode="custom" (that exact URL used for every visit)
  //   - multiple URLs → mode="random_list" (one URL picked at random per visit)
  useEffect(() => {
    const trimmed = (presetSourceUrl || "").trim();
    if (!trimmed) return;
    const lines = trimmed.split("\n").map((s) => s.trim()).filter(Boolean);
    setRefererValue(trimmed);
    if (lines.length > 1) {
      setRefererMode("random_list");
    } else {
      setRefererMode("custom");
    }
    setRefererProMode(false); // explicit URLs override pro-mode pools
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetSourceUrl]);

  // ── Apply a saved preset (from the "My Saved Presets" chip strip) ──
  const applyMyPreset = (mp) => {
    if (!mp || !mp.config) return;
    const cfg = mp.config || {};
    setSelectedMyPresetId(mp.id);
    // Set the base preset first so the "auto-configure" effect fires and
    // sets sensible defaults, THEN override each field with saved values.
    setTrafficSourcePreset(mp.base_preset || "custom");
    // Defer the overrides one tick so the base-preset effect runs first
    setTimeout(() => {
      setRefererOverrideEnabled(true);
      if (cfg.platform_weights && typeof cfg.platform_weights === "object") {
        setRefererPlatformWeights({ ...cfg.platform_weights });
      }
      if (cfg.email_weights && typeof cfg.email_weights === "object") {
        setRefererEmailWeights({ ...cfg.email_weights });
      }
      if (typeof cfg.referer_value === "string") {
        setRefererValue(cfg.referer_value);
        setPresetSourceUrl(cfg.referer_value);
      }
      if (typeof cfg.referer_brand === "string") setRefererBrand(cfg.referer_brand);
      if (typeof cfg.referer_mode === "string") setRefererMode(cfg.referer_mode);
      if (typeof cfg.social_wrapper === "boolean") setRefererSocialWrapper(cfg.social_wrapper);
      if (typeof cfg.inapp_deep === "boolean") setRefererInappDeep(cfg.inapp_deep);
      if (typeof cfg.strip_search_path === "boolean") setRefererStripSearchPath(cfg.strip_search_path);
      if (typeof cfg.network_click_chain === "boolean") setRefererNetworkClickChain(cfg.network_click_chain);
      // v2.6.25 — restore paid/organic split settings from saved config
      if (typeof cfg.traffic_type === "string") setRefererTrafficType(cfg.traffic_type);
      if (typeof cfg.campaign_type === "string") setRefererCampaignType(cfg.campaign_type);
      if (typeof cfg.pass_to_offer === "boolean") setRefererPassToOffer(cfg.pass_to_offer);
      if (typeof cfg.match_ua_to_platform === "boolean") setRefererMatchUaToPlatform(cfg.match_ua_to_platform);
      if (typeof cfg.search_engine === "string") setRefererSearchEngine(cfg.search_engine);
      if (typeof cfg.search_keywords === "string") setRefererSearchKeywords(cfg.search_keywords);
      if (typeof cfg.pro_mode === "boolean") setRefererProMode(cfg.pro_mode);
    }, 30);
  };

  // ── Save the current preset+customisations as a NAMED preset ──
  const saveMyPreset = async () => {
    const name = (presetSaveName || "").trim();
    if (!name) {
      setPresetSaveError("Preset name required");
      return;
    }
    setPresetSaving(true);
    setPresetSaveError("");
    // Snapshot every field the frontend controls so reloading later
    // brings the customer back to the EXACT same configuration.
    const cfg = {
      platform_weights: refererPlatformWeights,
      email_weights: refererEmailWeights,
      referer_value: presetSourceUrl || refererValue || "",
      referer_brand: refererBrand,
      referer_mode: refererMode,
      social_wrapper: refererSocialWrapper,
      inapp_deep: refererInappDeep,
      strip_search_path: refererStripSearchPath,
      // v2.6.25 — persist paid/organic split settings in saved config
      traffic_type: refererTrafficType,
      campaign_type: refererCampaignType,
      network_click_chain: refererNetworkClickChain,
      pass_to_offer: refererPassToOffer,
      match_ua_to_platform: refererMatchUaToPlatform,
      search_engine: refererSearchEngine,
      search_keywords: refererSearchKeywords,
      pro_mode: refererProMode,
    };
    try {
      const token = localStorage.getItem("token");
      const res = await fetch(
        `${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/my-presets`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            name,
            base_preset: trafficSourcePreset,
            config: cfg,
          }),
        }
      );
      const body = await res.json();
      if (!res.ok) {
        setPresetSaveError(body?.detail || "Save failed");
      } else {
        setMyTrafficPresets((prev) => [body, ...prev.filter((p) => p.id !== body.id)]);
        setSelectedMyPresetId(body.id);
        setPresetSaveOpen(false);
        setPresetSaveName("");
      }
    } catch (e) {
      setPresetSaveError(String(e?.message || e));
    } finally {
      setPresetSaving(false);
    }
  };

  // ── Delete a saved preset ──
  const deleteMyPreset = async (mp) => {
    if (!mp || !mp.id) return;
    if (!window.confirm(`Delete preset "${mp.name}"? This cannot be undone.`)) return;
    try {
      const token = localStorage.getItem("token");
      const res = await fetch(
        `${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/my-presets/${mp.id}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (res.ok) {
        setMyTrafficPresets((prev) => prev.filter((p) => p.id !== mp.id));
        if (selectedMyPresetId === mp.id) setSelectedMyPresetId("");
      }
    } catch {}
  };

  // Load referrer-pro defaults ONCE so the multi-select UI can render
  // the list of available platforms / ESPs / countries / search engines.
  useEffect(() => {
    const token = localStorage.getItem("token");
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/defaults`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((d) => {
        if (d && Array.isArray(d.platforms)) {
          setRefererProDefaults(d);
          // Seed email weights to backend defaults the first time
          if (Object.keys(refererEmailWeights).length === 0 && d.email_default_weights) {
            setRefererEmailWeights({ ...d.email_default_weights });
          }
        }
      })
      .catch(() => { /* silent — UI keeps its hard-coded fallback */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch host capabilities ONCE so we render only what works here
  useEffect(() => {
    const token = localStorage.getItem("token");
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/anti-detect/capabilities`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => setAdCapabilities(d))
      .catch(() => {});
  }, []);

  // ── 2026-07: Traffic Source Preset applier ─────────────────────────
  // When the operator picks a preset from the SIMPLE dropdown, this
  // effect deterministically wires up EVERY downstream toggle (pool
  // weights + realism layers + pass-to-offer + UA coercion) to a
  // tested, conflict-free combination. Each preset is a "recipe" of
  // all 20+ toggles so the customer cannot accidentally produce a
  // mismatched configuration (e.g. social wrappers off but in-app
  // preset on). Preset "custom" is the escape hatch that leaves
  // every toggle untouched → power-users see the full advanced UI.
  // Preset "off" restores the legacy UA-only behaviour.
  useEffect(() => {
    if (!trafficSourcePreset || trafficSourcePreset === "custom") {
      return;  // Custom / initial mount — do NOT overwrite manual picks
    }
    if (trafficSourcePreset === "off") {
      // Legacy path: just turn the master switch off and leave the
      // sub-toggles at whatever they already are so re-enabling
      // returns the customer to their previous config.
      setRefererOverrideEnabled(false);
      return;
    }
    // Every real preset REQUIRES the master switch on.
    setRefererOverrideEnabled(true);
    // Recommended universal defaults — every preset gets these unless
    // it overrides below. Pass-to-offer + UA↔platform coercion are
    // the anti-fraud fundamentals; they must be on for realistic ads.
    setRefererPassToOffer(true);
    setRefererMatchUaToPlatform(true);
    setRefererProMode(true);              // presets use weighted pools
    setRefererMode("platform_pool");      // pro-mode reads weights from here
    setRefererSocialWrapper(true);
    setRefererInappDeep(true);
    setRefererStripSearchPath(true);
    setInappBrowserPreset("none");        // let matchUaToPlatform rotate per visit
    setRefererValue("");                   // preset owns the source
    if (trafficSourcePreset === "mixed_realistic") {
      setRefererTrafficType("auto");
      // Balanced 4-way mix — best all-round default for most offers.
      setRefererPlatformWeights({
        facebook: 30, instagram: 15, tiktok: 20,
        google: 20, twitter: 5, email: 10,
      });
      setRefererNetworkClickChain(true);   // affiliate-chain look
      setRefererSearchEngine("google");
    } else if (trafficSourcePreset === "social_media_ads") {
      setRefererTrafficType("paid");
      // Paid-social heavy: FB / IG / TikTok / Twitter, no search
      setRefererPlatformWeights({
        facebook: 40, instagram: 30, tiktok: 25, twitter: 5,
      });
      setRefererNetworkClickChain(true);
      setRefererSearchEngine("google");
    } else if (trafficSourcePreset === "search_engine_ads") {
      setRefererTrafficType("paid");
      // Google / Bing SEM + a slice of privacy engines
      setRefererPlatformWeights({
        google: 65, bing: 25, duckduckgo: 5, yandex: 5,
      });
      setRefererNetworkClickChain(false);  // search doesn't use ad-network wrappers
      setRefererSearchEngine("google");
      setRefererInappDeep(false);           // search has no in-app deep paths
      setRefererSocialWrapper(false);
    } else if (trafficSourcePreset === "email_campaign") {
      setRefererTrafficType("organic");
      // Pure email — ESP weights drive per-visit ESP choice
      setRefererPlatformWeights({ email: 100 });
      setRefererEmailWeights({
        gmail: 40, outlook: 20, yahoo: 10,
        mailchimp: 15, klaviyo: 10, empty: 5,
      });
      setRefererNetworkClickChain(false);
      setRefererInappDeep(false);
      setRefererSocialWrapper(false);
    } else if (trafficSourcePreset === "direct_traffic") {
      setRefererTrafficType("auto");
      // Bookmark / direct-typed URL / native mail app — no Referer.
      // pass_to_offer STAYS ON: Bug #9 fix allows pass-to-offer with
      // blank Referer, so the browser navigates DIRECTLY to the offer
      // with an empty Referer header. Without this, the browser would
      // go tracker→302→offer and referrer-policy would leak
      // `krexion.com` as the origin — defeating the whole point of
      // "direct traffic".
      setRefererMode("direct");
      setRefererProMode(false);             // direct mode ignores pro pools
      setRefererNetworkClickChain(false);
      setRefererSocialWrapper(false);
      setRefererInappDeep(false);
      // setRefererPassToOffer(true) already set above → keep it.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trafficSourcePreset]);



  // ── 2026-06: Health Check / Preflight Trace ──
  // Lightweight dry-run that validates the recording + URL on ONE
  // browser BEFORE committing budget to a full RUT job. Surfaces a
  // per-step trace (ms timing, native-click frame match, error reason)
  // so the operator catches a broken recording upfront — saves the
  // proxies + leads that would have been wasted on hundreds of
  // silent-failure visits when the offer page structure changed.
  const [hcRunning, setHcRunning] = useState(false);
  const [hcResult, setHcResult] = useState(null); // { ok, status, error, duration_ms, step_results, ... }
  const [hcModalOpen, setHcModalOpen] = useState(false);


  // AI Automation Generator state
  const [aiGenOpen, setAiGenOpen] = useState(false);
  const [aiGenFiles, setAiGenFiles] = useState([]);
  const [aiGenTargetUrl, setAiGenTargetUrl] = useState("");
  const [aiGenDesc, setAiGenDesc] = useState("");
  const [aiGenCols, setAiGenCols] = useState("");
  const [aiGenLoading, setAiGenLoading] = useState(false);

  // Job state
  const [submitting, setSubmitting] = useState(false);
  const [jobs, setJobs] = useState([]);
  // v2.1.70 — true when the cloud's /jobs list call timed out waiting
  // for the desktop bridge (response: {queued:true, via:"bridge"}).
  // Frontend keeps polling and shows a friendly hint in Past Jobs.
  const [bridgePending, setBridgePending] = useState(false);
  const [activeJob, setActiveJob] = useState(null);
  const [selectedJobIds, setSelectedJobIds] = useState(new Set());
  const pollRef = useRef(null);

  // Live activity modal — default OFF so backend stays light
  const [liveModalOpen, setLiveModalOpen] = useState(false);
  const [liveSteps, setLiveSteps] = useState([]);
  const [previewShot, setPreviewShot] = useState(null);
  const liveCursorRef = useRef(0);
  const liveTimerRef = useRef(null);

  // 2026-01: Visual Live Grid — real-time per-visit browser frames for
  // concurrent RUT visits. Mirrors the Visual Recorder live test feed
  // but at job scale (20+ tiles when 20 concurrency).
  const [visualGridOpen, setVisualGridOpen] = useState(false);
  const [visualGridMinimized, setVisualGridMinimized] = useState(false);
  const [liveVisits, setLiveVisits] = useState({}); // { "1": {visit_idx, latest_frame_b64, latest_event, ...} }
  const [expandedVisit, setExpandedVisit] = useState(null); // tile id when expanded to fullscreen
  const visualGridTimerRef = useRef(null);
  // v2.6.1 — Customer ask (Task 5): keep failed / cancelled visits in
  // view (in red) so the operator can see WHAT went wrong instead of
  // the tile silently vanishing. Persisted so the choice survives
  // reloads.
  const [showFailedVisits, setShowFailedVisits] = useState(
    () => (typeof window !== "undefined" && localStorage.getItem("krexion_rut_show_failed") !== "0")
  );
  useEffect(() => {
    try { localStorage.setItem("krexion_rut_show_failed", showFailedVisits ? "1" : "0"); } catch (_) {}
  }, [showFailedVisits]);

  // 2026-06 — Customer ask (Roman Urdu): "Live visual grid mein siraf
  // wo screen show ho jo active chal rahi hai. Jo complete / cancelled
  // / failed ho gayi ho us ki tile turant khatam ho jaaye, taa ke pata
  // chalta rahe ke abhi kitne actually chal rahe hain. Agar 5 concurrent
  // chala rahe hain to ek waqt mein 5 tile he dikhein — jab ek complete /
  // cancel / fail ho jaaye, tab next visit ki tile uski jagah le."
  //
  // The backend keeps every visit (running, done, failed, cancelled) in
  // its `live_visits` dict so post-mortem inspection is possible. The
  // grid however should only render visits that are currently ACTIVE —
  // anything else is dead weight that confuses the operator's "kitne
  // actually chal rahe hain?" mental model. This helper is the single
  // source of truth; it's used by the grid renderer AND by the header
  // counter so the two never disagree.
  const isVisitActive = (v) => {
    if (!v) return false;
    const ev = v.latest_event || {};
    const vStatus = v.status;
    // Cancelled (manual kill OR job-level cancel) → tile must vanish
    if (vStatus === 'cancelled' || ev.stage === 'manual_cancel') return false;
    // 2026-06-27 BUGFIX — Use VISIT-level status only as source of truth
    // for "is visit done?". Previously we also checked
    // `ev.status === 'ok'`, but the automation engine emits
    // `{action: 'click', status: 'ok', idx: 38}` on EVERY successful
    // step. That made every mid-flow visit instantly disappear from the
    // grid and the user saw "Waiting for first visit to start…" even
    // though a visit was actively running through 118 steps. The
    // visit-level v.status is the only authoritative signal.
    if (vStatus === 'done' || vStatus === 'ok') return false;
    if (vStatus === 'failed') return false;
    if (vStatus === 'skipped') return false;
    // Catch the brief race where push_live_step has emitted the final
    // {stage:'done'} event but the dispatcher has not yet flipped
    // v.status. This is the ONLY safe per-step short-circuit because
    // `stage:"done"` is reserved for visit completion (push_live_step
    // calls — never the per-step automation callback which uses
    // `action`/`selector` and never sets `stage`).
    if (ev.stage === 'done') return false;
    return true;
  };

  // v2.6.1 — Task 5. Predicate that also keeps FAILED / CANCELLED
  // visits visible so the operator can see what went wrong. Successful
  // visits still vanish (nothing to inspect).
  const isVisitVisible = (v) => {
    if (!v) return false;
    if (isVisitActive(v)) return true;
    if (!showFailedVisits) return false;
    const vStatus = v.status;
    const ev = v.latest_event || {};
    if (vStatus === 'failed') return true;
    if (vStatus === 'cancelled' || ev.stage === 'manual_cancel') return true;
    if (vStatus === 'skipped') return true;
    return false;
  };

  // ─── 2026-06 — Manual Takeover + Hybrid Streaming state ──────────────
  // Customer ask (Roman Urdu): "live visual grid mein sab smoothly live
  // dikhe… or live visual grid mein manually kam krne ka b option ho jese
  // profile khol kr kam krte hien… agr stuck ho jay to manuualy wo kaam
  // kr liya jay".
  //
  // pausedVisits  — Set of visit_idx strings currently paused. UI flip
  //                 between "Pause" and "Resume" buttons; sending input
  //                 only enabled while paused.
  // controlVisit  — visit_idx ("1","2"…) currently in interactive control
  //                 mode (NULL = view-only). When non-null the live frame
  //                 in the expanded modal becomes click-able and the
  //                 keyboard listener routes key presses to /input/key.
  // controlText   — buffered text in the manual-type input box.
  const [pausedVisits, setPausedVisits] = useState({}); // {"1": true, ...}
  const [controlVisit, setControlVisit] = useState(null);
  const [controlText, setControlText] = useState("");
  const [inputInFlight, setInputInFlight] = useState(false);
  const frameImgRef = useRef(null);

  // Helper: PATCH-style call to one of the new manual-takeover endpoints.
  // Wraps fetch + error toast so callers stay tight. Always returns the
  // parsed JSON (or null on failure).
  const _rutCallVisit = async (jobId, visitIdx, path, body) => {
    try {
      const r = await fetch(
        `${API_URL}/api/real-user-traffic/jobs/${jobId}/visits/${visitIdx}/${path}`,
        {
          method: "POST",
          headers: { ...authH(), "Content-Type": "application/json" },
          body: body !== undefined ? JSON.stringify(body) : undefined,
        }
      );
      if (!r.ok) {
        // v2.1.70 — stream-mode + cancel are best-effort cleanup calls.
        // When a job finishes the backend purges it from in-memory
        // _RUT_JOBS so any in-flight POST gets a 404 — that's expected,
        // not an error to surface to the user. Toast only for genuine
        // failures (auth, server crash, etc.).
        if (r.status === 404 && (path === "stream" || path === "cancel")) {
          return null;
        }
        const t = await r.text();
        let msg = `${path} failed (${r.status})`;
        try { msg = JSON.parse(t).detail || msg; } catch (_) { /* ignore */ }
        toast.error(msg);
        return null;
      }
      return await r.json();
    } catch (e) {
      toast.error(`${path} failed: ${e.message || e}`);
      return null;
    }
  };

  // Stream-mode switcher. Called whenever the operator opens / closes
  // the grid, or expands / collapses a tile. The backend daemon adjusts
  // its screenshot cadence so we get smooth-ish updates without burning
  // CPU on visits the operator isn't watching.
  const setVisitStreamMode = async (visitIdx, mode) => {
    if (!activeJob?.job_id) return;
    await _rutCallVisit(activeJob.job_id, visitIdx, "stream", { mode });
  };

  // Pause / Resume the JSON automation for THIS visit.
  const pauseVisit = async (visitIdx) => {
    if (!activeJob?.job_id) return;
    const r = await _rutCallVisit(activeJob.job_id, visitIdx, "pause");
    if (r && r.ok) {
      setPausedVisits((p) => ({ ...p, [String(visitIdx)]: true }));
      toast.success(`Visit #${String(visitIdx).padStart(3, "0")} paused`);
    }
  };

  const resumeVisit = async (visitIdx) => {
    if (!activeJob?.job_id) return;
    const r = await _rutCallVisit(activeJob.job_id, visitIdx, "resume");
    if (r && r.ok) {
      setPausedVisits((p) => {
        const n = { ...p };
        delete n[String(visitIdx)];
        return n;
      });
      // Leaving manual-control mode when we resume
      if (controlVisit === String(visitIdx)) setControlVisit(null);
      toast.success(`Visit #${String(visitIdx).padStart(3, "0")} resumed`);
    }
  };

  // Forward an input action to the live page. `kind` ∈
  // {"click","type","key","scroll","nav","back"}. Backend rejects with
  // 409 if visit isn't paused — we surface that as a hint.
  const sendVisitInput = async (visitIdx, kind, payload) => {
    if (!activeJob?.job_id) return null;
    setInputInFlight(true);
    try {
      const r = await _rutCallVisit(activeJob.job_id, visitIdx, "input",
        { kind, payload });
      return r;
    } finally {
      setInputInFlight(false);
    }
  };

  // Coordinates from a click on the rendered <img> → frame coords for the
  // backend (which then scales to viewport). We pass the rendered img
  // dimensions as frame_w/frame_h so the backend can scale precisely.
  const handleFrameClick = async (e, visitIdx) => {
    if (controlVisit !== String(visitIdx)) return;
    if (!pausedVisits[String(visitIdx)]) {
      toast.warning("Pause the visit first to take manual control");
      return;
    }
    const img = e.currentTarget;
    if (!img || !img.getBoundingClientRect) return;
    const rect = img.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    await sendVisitInput(visitIdx, "click", {
      x, y,
      frame_w: rect.width,
      frame_h: rect.height,
      button: e.button === 2 ? "right" : "left",
    });
  };

  // Keyboard listener — only active while a visit is in control mode.
  useEffect(() => {
    if (!controlVisit) return undefined;
    const handler = async (e) => {
      // Ignore keystrokes that are typed into our own input fields
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || e.target?.isContentEditable) {
        return;
      }
      // Map browser key names to Playwright key names where they differ
      const k = e.key;
      // Allow Cmd/Ctrl+C/V/A/Z to behave locally — don't forward those
      if ((e.metaKey || e.ctrlKey) && k.length === 1) return;
      e.preventDefault();
      await sendVisitInput(controlVisit, "key", { key: k });
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controlVisit, pausedVisits]);

  // Diagnostics modal — shows macro-leak + stuck-visit events recorded
  // during the run. Powers the "Why didn't this offer convert?" workflow.
  const [diagModalOpen, setDiagModalOpen] = useState(false);
  const [diagData, setDiagData] = useState(null);
  const [diagLoading, setDiagLoading] = useState(false);

  const openDiagnostics = async () => {
    if (!activeJob?.job_id) return;
    setDiagModalOpen(true);
    setDiagLoading(true);
    setDiagData(null);
    try {
      const r = await fetch(
        `${API_URL}/api/real-user-traffic/jobs/${activeJob.job_id}/diagnostics`,
        { headers: authH() },
      );
      if (r.ok) {
        setDiagData(await r.json());
      }
    } catch (e) {
      // silent — UI shows "no data" state
    } finally {
      setDiagLoading(false);
    }
  };

  // Engine readiness — polled every 5s. Coloured badge at top of page.
  const [engineStatus, setEngineStatus] = useState({
    status: "ready",
    message: "Chromium ready",
    expected_revision: null,
  });
  const engineTimerRef = useRef(null);
  const [enginePrewarming, setEnginePrewarming] = useState(false);

  const token = () => localStorage.getItem("token");
  const authH = () => ({ Authorization: `Bearer ${token()}` });

  // ─── Data fetching ─────────────────────────────────────────────
  const fetchLinks = async () => {
    try {
      const r = await fetch(`${API_URL}/api/links`, { headers: authH() });
      if (r.ok) {
        const data = await r.json();
        setLinks(Array.isArray(data) ? data : (data.links || []));
      }
    } catch (e) { /* ignore */ }
  };

  const fetchJobs = async () => {
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs`, { headers: authH() });
      if (r.ok) {
        const data = await r.json();
        // v2.1.70 — when the cloud bridge times out waiting for the
        // desktop it returns {queued:true, via:"bridge", state, message}
        // with HTTP 202 (still "ok" for fetch). Don't blow away the
        // existing jobs list in that case — leave it so the user keeps
        // seeing the last good snapshot while we retry. We just flag
        // bridge-pending so the UI can show a friendly hint.
        if (data && data.queued && !Array.isArray(data.jobs)) {
          setBridgePending(true);
          return;
        }
        setBridgePending(false);
        setJobs(data.jobs || []);
      }
    } catch (e) { /* ignore */ }
  };

  const fetchPendingCandidates = async () => {
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/pending-candidates`, { headers: authH() });
      if (r.ok) {
        const data = await r.json();
        // v2.1.70 — same bridge-pending tolerance as fetchJobs above.
        if (data && data.queued && !Array.isArray(data.items)) {
          return;
        }
        setPendingCandidates(data.items || []);
      }
    } catch (e) { /* ignore */ }
  };

  // v2.6.2 — ProxyJet credential probe removed. Auto Mode is now
  // exclusively driven by a Proxy Provider selection from Settings.
  const fetchProxyJetStatus = async () => { /* removed — provider-only */ };

  // ── Inline UA Generator ────────────────────────────────────────────
  // Fetch UAs from /api/user-agents/generate and append into the UA
  // textarea — avoids leaving the page just to populate user agents.
  const generateUAsInline = async () => {
    const n = Math.max(1, Math.min(Number(uaGenCount) || 10, 5000));
    setUaGenBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/user-agents/generate`, {
        method: "POST",
        headers: { ...authH(), "Content-Type": "application/json" },
        body: JSON.stringify({
          app: uaGenApp,
          platform: uaGenPlatform,
          count: n,
          format: "json",
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const list = (d.user_agents || []).map((x) => x.user_agent).filter(Boolean);
      if (!list.length) {
        toast.error("Generator returned 0 UAs — try a different app/platform");
        return;
      }
      // Append to existing list (preserve what user already pasted)
      setUserAgents((prev) => {
        const sep = prev.trim() ? "\n" : "";
        return prev + sep + list.join("\n");
      });
      toast.success(`✓ Generated ${list.length} ${uaGenPlatform} ${uaGenApp} UAs`);
      setUaGenOpen(false);
    } catch (e) {
      toast.error(`UA generation failed: ${e.message || e}`);
    } finally {
      setUaGenBusy(false);
    }
  };

  // ── Preview uploaded data file: detect states + quality stats ─────
  // Called whenever the user changes file source so the State filter
  // panel can show "AL: 124, AK: 105" before they submit the job.
  const previewDataFile = async ({ fileObj, uploadDataFileId, gsheetUrl: gs }) => {
    setPreviewLoading(true);
    setDataPreview(null);
    setSelectedStates([]);
    setSelectedEmailDomains([]);
    try {
      const fd = new FormData();
      if (fileObj) fd.append("file", fileObj);
      if (uploadDataFileId) fd.append("upload_data_file_id", uploadDataFileId);
      if (gs) fd.append("gsheet_url", gs);
      const r = await fetch(`${API_URL}/api/real-user-traffic/preview-data-file`, {
        method: "POST",
        headers: authH(),
        body: fd,
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setDataPreview(d);
      // Default: pre-select all detected states so user can deselect
      const codes = (d.states || []).map((s) => s.code);
      setSelectedStates(codes);
      // 2026-06 — Default: pre-select all detected email domains so
      // current behaviour is unchanged (filter ON only when user
      // deselects some).
      const domains = (d.email_domains || []).map((e) => e.domain);
      setSelectedEmailDomains(domains);
    } catch (e) {
      toast.error(`Could not analyze data file: ${e.message || e}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const fetchJobDetail = async (jobId) => {
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/${jobId}`, { headers: authH() });
      if (r.ok) {
        const data = await r.json();
        setActiveJob(data);
        if (["completed", "failed", "stopped"].includes(data.status) && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          fetchJobs();
          fetchPendingCandidates();
        }
      }
    } catch (e) { /* ignore */ }
  };

  const startPolling = (jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    fetchJobDetail(jobId);
    pollRef.current = setInterval(() => fetchJobDetail(jobId), 2500);
  };

  // ─── Live activity log polling (only runs when modal is open) ──
  const fetchLiveSteps = async (jobId) => {
    try {
      const r = await fetch(
        `${API_URL}/api/real-user-traffic/jobs/${jobId}/live-log?since=${liveCursorRef.current}`,
        { headers: authH() }
      );
      if (!r.ok) return;
      const data = await r.json();
      if (data.steps && data.steps.length > 0) {
        liveCursorRef.current = data.cursor;
        setLiveSteps((prev) => {
          const next = [...prev, ...data.steps];
          return next.length > 400 ? next.slice(-400) : next;
        });
      }
      if (!data.running) {
        // job ended — stop auto-poll
        if (liveTimerRef.current) {
          clearInterval(liveTimerRef.current);
          liveTimerRef.current = null;
        }
      }
    } catch (_) { /* ignore */ }
  };

  const openLiveModal = () => {
    if (!activeJob?.job_id) return;
    setLiveSteps([]);
    liveCursorRef.current = 0;
    setLiveModalOpen(true);
    fetchLiveSteps(activeJob.job_id);
    liveTimerRef.current = setInterval(() => fetchLiveSteps(activeJob.job_id), 1500);
  };

  const closeLiveModal = () => {
    setLiveModalOpen(false);
    if (liveTimerRef.current) {
      clearInterval(liveTimerRef.current);
      liveTimerRef.current = null;
    }
  };

  // ─── 2026-01: Visual Live Grid polling (per-visit screenshots) ──
  const fetchLiveVisits = async (jobId) => {
    try {
      const r = await fetch(
        `${API_URL}/api/real-user-traffic/jobs/${jobId}/live-visits?include_frames=true`,
        { headers: authH() }
      );
      if (!r.ok) return;
      const data = await r.json();
      if (data && data.visits) setLiveVisits(data.visits);
      if (!data.job_running) {
        // Job ended — do one more poll then stop
        setTimeout(() => {
          if (visualGridTimerRef.current) {
            clearInterval(visualGridTimerRef.current);
            visualGridTimerRef.current = null;
          }
        }, 1500);
      }
    } catch (_) { /* ignore */ }
  };

  const openVisualGrid = () => {
    if (!activeJob?.job_id) return;
    setLiveVisits({});
    setVisualGridOpen(true);
    setVisualGridMinimized(false);
    fetchLiveVisits(activeJob.job_id);
    // 2026-06 — Hybrid streaming: faster poll (400 ms) when grid is open
    // so the backend daemon's ~700 ms grid-mode frames OR ~150 ms expanded
    // frames both feel fresh. Without this, frontend polling becomes the
    // bottleneck and the smooth backend updates are invisible.
    if (visualGridTimerRef.current) clearInterval(visualGridTimerRef.current);
    visualGridTimerRef.current = setInterval(
      () => fetchLiveVisits(activeJob.job_id), 400
    );
  };

  const closeVisualGrid = () => {
    // 2026-06 — Turn off ALL streaming daemons for this job before closing
    // so the backend stops snapping screenshots on visits the operator
    // can no longer see.
    if (activeJob?.job_id) {
      Object.keys(liveVisits).forEach((vid) => {
        // Fire-and-forget; do NOT await — closing the modal must feel instant
        _rutCallVisit(activeJob.job_id, vid, "stream", { mode: "off" });
      });
    }
    setVisualGridOpen(false);
    setExpandedVisit(null);
    setControlVisit(null);
    setPausedVisits({});
    if (visualGridTimerRef.current) {
      clearInterval(visualGridTimerRef.current);
      visualGridTimerRef.current = null;
    }
  };

  // 2026-06 — Hybrid stream-mode driver. Watches the grid + expansion
  // state and tells the backend to switch each visit between off / grid
  // (low fps, fills idle gaps) / expanded (high fps, single-tile focus).
  // Fire-and-forget — failures just leave the visit on its previous
  // cadence and the next render will re-sync.
  useEffect(() => {
    if (!activeJob?.job_id || !visualGridOpen) return;
    const visitIds = Object.keys(liveVisits);
    visitIds.forEach((vid) => {
      const v = liveVisits[vid];
      // 2026-06 — Don't keep streaming visits that have already
      // finished (ok / failed / cancelled / skipped). The tile is
      // hidden from the grid the moment isVisitActive() returns
      // false, so streaming bytes for it is pure waste of backend +
      // bandwidth. Forcing stream=off here also prevents the
      // backend's daemon from re-attaching to a finished page.
      if (!isVisitActive(v)) {
        if (v && v.frame_source !== "off") {
          setVisitStreamMode(vid, "off");
        }
        return;
      }
      const desired = (expandedVisit && String(expandedVisit) === String(vid))
        ? "expanded"
        : "grid";
      if (v && v.frame_source === desired) return;  // already at target cadence
      setVisitStreamMode(vid, desired);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visualGridOpen, expandedVisit, Object.keys(liveVisits).join(",")]);

  // 2026-06 — If the user expanded a tile that has since finished
  // (visit completed / failed / cancelled), auto-collapse so the user
  // is not stuck staring at a dead screenshot. The grid below will
  // also have hidden the tile, so without this auto-collapse the
  // expanded modal would point at a vanished tile id.
  useEffect(() => {
    if (!expandedVisit) return;
    const v = liveVisits[expandedVisit];
    if (v && !isVisitActive(v)) {
      setExpandedVisit(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveVisits, expandedVisit]);

  // ─── 2026-05: Manually kill ONE in-flight visit (per-tile button) ──
  // User ask (Roman Urdu): "agar kisi profile mein koi issue ai to os
  // ko manualy close krne ka option ho ta k mazeed os pr time waste na
  // ho or next profile pr kam ho sake".
  const [cancellingVisits, setCancellingVisits] = useState({});
  // 2026-05 — "Show Step Markers" toggle. When ON, an SVG overlay is
  // rendered on top of the full-page tile screenshot with one coloured
  // dot per recorded step at the resolved element's bounding box
  // (full-page coordinates from backend, scaled to the rendered <img>
  // dimensions). Hover shows "step #N (action) selector" tooltip. Lets
  // the operator instantly see WHERE every step landed on the page
  // without scrolling step-by-step through the JSON.
  const [showStepMarkers, setShowStepMarkers] = useState(true);
  const cancelOneVisit = async (vid) => {
    if (!activeJob?.job_id || !vid) return;
    if (cancellingVisits[vid]) return; // debounce double-clicks
    setCancellingVisits((p) => ({ ...p, [vid]: true }));
    try {
      const r = await fetch(
        `${API_URL}/api/real-user-traffic/jobs/${activeJob.job_id}/visits/${vid}/cancel`,
        { method: "POST", headers: authH() }
      );
      if (r.ok) {
        toast.success(`Visit #${String(vid).padStart(3, "0")} cancelled — next visit will spawn into this slot.`);
        // Optimistic UI flip — server will confirm on next 800 ms poll
        setLiveVisits((prev) => {
          const next = { ...prev };
          if (next[vid]) {
            next[vid] = {
              ...next[vid],
              status: "cancelled",
              latest_event: {
                ...(next[vid].latest_event || {}),
                status: "failed",
                stage: "manual_cancel",
                detail: "Cancelled by user",
              },
            };
          }
          return next;
        });
        if (expandedVisit === vid) setExpandedVisit(null);
      } else {
        const txt = await r.text().catch(() => "");
        toast.error(`Cancel failed: ${txt.slice(0, 120) || r.status}`);
      }
    } catch (e) {
      toast.error(`Cancel failed: ${e.message || e}`);
    } finally {
      // Clear the in-flight flag after a short delay so user can see
      // the spinner if backend takes >1 frame.
      setTimeout(() => {
        setCancellingVisits((p) => {
          const c = { ...p };
          delete c[vid];
          return c;
        });
      }, 800);
    }
  };

  useEffect(() => {
    fetchLinks();
    fetchJobs();
    fetchPendingCandidates();
    fetchUploadedLibrary();
    fetchEngineStatus();
    fetchProxyJetStatus();
    // Poll engine status every 5s — cheap (single fs check on the backend)
    // and gives the user immediate feedback when chromium finishes
    // installing on a fresh pod boot.
    engineTimerRef.current = setInterval(fetchEngineStatus, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (liveTimerRef.current) clearInterval(liveTimerRef.current);
      if (engineTimerRef.current) clearInterval(engineTimerRef.current);
    };
  }, []);

  // v2.5.0 — Whenever the customer changes their selected proxy
  // provider, fetch just the kind field so Auto Mode can decide
  // whether to route through the generic batch generator (any non-
  // ProxyJet kind) or through the legacy ProxyJet auto flow.
  useEffect(() => {
    if (!proxyProviderId) {
      setProxyProviderKind("");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_URL}/api/proxy-providers/${proxyProviderId}`, {
          headers: authH(),
        });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setProxyProviderKind(j?.kind || "");
      } catch {
        /* silent — Auto Mode will fall back to ProxyJet path */
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proxyProviderId]);

  const fetchEngineStatus = async () => {
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/engine-status`, {
        headers: authH(),
      });
      if (r.ok) {
        const data = await r.json();
        setEngineStatus({
          status: data.status || "ready",
          message: data.message || "",
          expected_revision: data.expected_revision || null,
        });
      }
    } catch (e) { /* ignore — keep last known status */ }
  };

  const handleEnginePrewarm = async () => {
    if (enginePrewarming) return;
    setEnginePrewarming(true);
    // Optimistic flip to "installing" so the badge gives instant feedback
    // even before the next poll cycle lands.
    setEngineStatus((prev) => ({
      ...prev,
      status: "installing",
      message: "Prewarm requested — downloading Chromium…",
    }));
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/engine-prewarm`, {
        method: "POST",
        headers: authH(),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        if (data.already_ready) {
          toast.success("Engine already ready");
        } else if (data.already_installing) {
          toast.info("Install already in progress");
        } else {
          toast.success("Pre-warm started — engine will be ready in ~60s");
        }
        // Force an immediate re-fetch so the badge picks up the real status
        fetchEngineStatus();
      } else {
        toast.error(data.detail || "Pre-warm failed");
      }
    } catch (e) {
      toast.error("Pre-warm error: " + (e.message || e));
    } finally {
      setEnginePrewarming(false);
    }
  };

  const fetchUploadedLibrary = async () => {
    try {
      const r = await fetch(`${API_URL}/api/uploads`, { headers: authH() });
      if (r.ok) {
        const data = await r.json();
        setUploadedLibrary(data || []);
      }
    } catch (e) {
      // silent — feature may not be enabled for this user
    }
  };

  // ─── Helpers ──────────────────────────────────────────────────
  const toggleCountry = (c) => {
    setAllowedCountries((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]
    );
  };
  const toggleOs = (k) => {
    setAllowedOs((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
  };

  const proxyCount = proxies.split("\n").filter((l) => l.trim()).length;
  const uaCount = userAgents.split("\n").filter((l) => l.trim()).length;

  // ─── AI Automation Generator ──────────────────────────────────
  const onAiGenerate = async () => {
    if (!aiGenFiles || aiGenFiles.length === 0) {
      return toast.error("Upload at least one screenshot or a short video");
    }
    const hasVideo = Array.from(aiGenFiles).some((f) => (f.type || "").startsWith("video/"));
    const imageCount = Array.from(aiGenFiles).filter((f) => (f.type || "").startsWith("image/")).length;
    if (imageCount > 15) {
      return toast.error("Maximum 15 screenshots per request");
    }
    if (Array.from(aiGenFiles).filter((f) => (f.type || "").startsWith("video/")).length > 1) {
      return toast.error("Only one video per request");
    }

    setAiGenLoading(true);
    try {
      const fd = new FormData();
      if (aiGenTargetUrl.trim()) fd.append("target_url", aiGenTargetUrl.trim());
      if (aiGenDesc.trim()) fd.append("description", aiGenDesc.trim());
      if (aiGenCols.trim()) fd.append("excel_columns", aiGenCols.trim());
      for (const f of aiGenFiles) fd.append("files", f);

      const r = await fetch(`${API_URL}/api/real-user-traffic/ai-generate-automation`, {
        method: "POST",
        headers: authH(),
        body: fd,
      });
      const data = await r.json();
      if (!r.ok || data.status === "failed") {
        return toast.error(data.error || data.detail || "AI generation failed");
      }
      if (!data.steps || data.steps.length === 0) {
        return toast.error("AI did not return any steps — try adding a description or clearer screenshots");
      }

      const pretty = JSON.stringify({ steps: data.steps }, null, 2);
      setAutomationJson(pretty);
      setUseCustomJson(true);
      toast.success(`Generated ${data.steps.length} automation steps — review & Start`);
      setAiGenOpen(false);
      if (hasVideo) setAiGenFiles([]);
    } catch (e) {
      toast.error("AI generation error: " + (e.message || e));
    } finally {
      setAiGenLoading(false);
    }
  };

  // ── 2026-06: Run Health Check ───────────────────────────────────
  // Lightweight preflight trace. Does NOT consume a job slot, does NOT
  // write to DB, does NOT rotate proxies. Just opens ONE browser, runs
  // the steps, returns per-step trace. Operator should run this BEFORE
  // spending real budget on 1000-visit jobs.
  const runHealthCheck = async () => {
    if (!linkId && !targetUrlOverride.trim()) {
      return toast.error("Select a tracker link OR enter a target URL override first");
    }
    // Build target URL the same way the live job does
    let target = targetUrlOverride.trim();
    if (!target) {
      const link = (links || []).find((l) => l.id === linkId);
      target = link?.offer_url || "";
    }
    if (!target.startsWith("http://") && !target.startsWith("https://")) {
      return toast.error("Target URL must start with http:// or https://");
    }
    // Build automation JSON payload: prefer raw text, else uploaded id
    const ajText = (automationJson || "").trim();
    const ajId = selectedUploadAjId || "";
    if (!ajText && !ajId) {
      return toast.error("Paste automation JSON or pick a saved template before running Health Check");
    }
    if (ajText) {
      try { JSON.parse(ajText); }
      catch (e) { return toast.error(`Invalid JSON: ${e.message}`); }
    }

    setHcRunning(true);
    setHcModalOpen(true);
    setHcResult(null);
    try {
      const body = {
        target_url: target,
        timeout_sec: 90,
      };
      if (ajId) body.upload_automation_json_id = ajId;
      else body.automation_json = ajText;

      const r = await fetch(`${API_URL}/api/real-user-traffic/health-check`, {
        method: "POST",
        headers: { ...authH(), "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      setHcResult(data);
      if (data.ok) {
        toast.success(`Health Check PASSED — all ${data.executed_steps} steps OK in ${(data.duration_ms / 1000).toFixed(1)}s`);
      } else {
        toast.error(`Health Check FAILED — step ${(data.failed_at_idx ?? -1) + 1}: ${(data.error || "").slice(0, 80)}`);
      }
    } catch (err) {
      setHcResult({
        ok: false, status: "failed",
        error: err.message || String(err),
        duration_ms: 0, step_results: [],
      });
      toast.error(`Health Check failed: ${err.message || err}`);
    } finally {
      setHcRunning(false);
    }
  };


  const onStart = async (opts = {}) => {
    // 2026-05 — Pre-flight smoke test mode. Same form, same backend, but
    // forces total=1/concurrency=1 and tags the job so the result panel
    // renders pass/fail per step instead of the normal report. User can
    // then click "Start Full Job" to launch the real run.
    const isSmokeTest = !!opts.smokeTest;
    if (!linkId) return toast.error("Select a tracker link");
    // v2.6.2 — Auto Mode is now provider-only. A selected Proxy
    // Provider (any kind) is required — the ProxyJet-specific
    // fallback path has been removed.
    const autoModeViaProvider = useProxyJetAuto && !!proxyProviderId;
    // Validation: either paste OR uploaded batch OR Auto Mode must be present
    if (!useProxyJetAuto && !useStoredProxies && !selectedUploadProxyId && selectedUploadProxyIds.length === 0 && !proxies.trim()) {
      return toast.error("Paste proxies, select an uploaded proxy batch, enable 'Use my stored proxies', or turn on Auto Mode");
    }
    if (useProxyJetAuto && !autoModeViaProvider) {
      return toast.error("Auto Mode needs a Proxy Provider selected above (Settings › Proxy Providers).");
    }
    if (!selectedUploadUaId && selectedUploadUaIds.length === 0 && !userAgents.trim()) {
      return toast.error("Paste at least one User Agent or select one-or-more uploaded UA batch(es)");
    }
    if (formFillEnabled) {
      if (dataSource === "excel" && !file && !selectedUploadDataId) {
        return toast.error("Upload the leads Excel/CSV file or select an uploaded data file");
      }
      if (dataSource === "gsheet" && !gsheetUrl.trim()) return toast.error("Paste the Google Sheet URL");
      if (dataSource === "pending_from_job" && !importPendingJobId) return toast.error("Select a previous job to import pending leads from");
      if (useCustomJson || funnelMode === "custom") {
        // Either a saved template is selected OR user pasted JSON
        if (!selectedUploadAjId && !automationJson.trim()) {
          return toast.error("Paste the custom automation JSON, pick a saved template, or disable the toggle");
        }
        if (!selectedUploadAjId) {
          try { JSON.parse(automationJson); }
          catch (e) { return toast.error("Automation JSON is not valid: " + e.message); }
        }
      }
      if (funnelMode === "smart" && !formFillEnabled) {
        return toast.error("Smart Funnel requires Form Fill with Excel/Sheet lead data");
      }
    }

    setSubmitting(true);
    // Declared outside try so catch can read it for network-abort recovery.
    let jobsBefore = null;
    try {
      // ─────── Pre-upload ALL big payloads via library endpoints to avoid
      // Cloudflare tunnel ~100s timeout + ingress body-size limits on the
      // main job-create POST. Even small pastes are pre-uploaded so the
      // final job-create request body stays < 10 KB (IDs + numbers only).
      // Any pre-upload failure is HARD-FAILED (no silent fallback to raw
      // payload) so the user sees a clear error instead of a mysterious
      // "Network request aborted" message 30-90s later. ────────────────

      const preUpload = async (label, url, builder) => {
        try {
          const fd = new FormData();
          builder(fd);
          const r = await fetch(url, {
            method: "POST", headers: authH(), body: fd,
          });
          if (!r.ok) {
            const txt = await r.text().catch(() => "");
            throw new Error(`${label} pre-upload failed (HTTP ${r.status}): ${txt.slice(0, 200)}`);
          }
          const j = await r.json();
          return j.id || "";
        } catch (e) {
          throw new Error(`${label} pre-upload failed: ${e.message || e}`);
        }
      };

      // Excel data-file (if user picked a fresh file, not from library)
      // ────────────────────────────────────────────────────────────────
      // PARALLEL PRE-UPLOADS — earlier these ran sequentially which made
      // a typical job take 3-7 s before the actual /jobs POST fired.
      // Now all independent uploads (Excel, proxies paste, UAs paste,
      // automation JSON, target screenshot) fire at once via Promise.all
      // so total wait collapses to max-of-N (~1-2 s on a typical link).
      // ────────────────────────────────────────────────────────────────
      const wantExcel = formFillEnabled && dataSource === "excel" && file && !selectedUploadDataId;
      // v2.5.0 — Auto Mode via a non-ProxyJet provider pre-generates
      // the proxy batch here (client-side) and injects it into the
      // regular paste flow. This means the backend receives a normal
      // proxies payload and NOT `use_proxyjet_auto=true`, so no
      // ProxyJet credentials are required. The ProxyJet path (empty
      // provider OR native_proxyjet kind) is completely untouched.
      let effectiveProxies = proxies;
      let effectiveUseProxyJetAuto = useProxyJetAuto;
      if (autoModeViaProvider) {
        const multiGeo = pjGeoMode === "many" && pjCountriesPool.length >= 2;
        if (multiGeo) {
          // Multi-geo mix needs backend on-demand ROW-FIRST — skip single-country pre-gen.
          effectiveUseProxyJetAuto = true;
          toast.info("Multi-geo Auto Mode: per-visit proxy mix handled by the engine (no pre-gen).");
        } else {
        try {
          const desired = Math.max(1, parseInt(totalClicks, 10) || 10);
          const genRes = await fetch(
            `${API_URL}/api/proxy-providers/${proxyProviderId}/generate-batch`,
            {
              method: "POST",
              headers: { ...authH(), "Content-Type": "application/json" },
              body: JSON.stringify({
                count: desired,
                // For non-ProxyJet providers geo hints are ignored server-side,
                // but sending them is harmless and lets rotating_gateway
                // providers that use `-country-{XX}` username templates
                // (future) pick them up.
                country: (proxyJetCountry || "").toUpperCase() || null,
                state: (proxyJetState || "").toUpperCase() || null,
                // proxy_type: keep the provider's saved default (backend picks it)
              }),
            }
          );
          if (!genRes.ok) {
            const t = await genRes.text().catch(() => "");
            throw new Error(`HTTP ${genRes.status}: ${t.slice(0, 180)}`);
          }
          const gj = await genRes.json();
          const list = gj?.proxies || [];
          if (!list.length) throw new Error("provider returned zero proxies");
          effectiveProxies = list.join("\n");
          effectiveUseProxyJetAuto = false;
          toast.success(`Auto Mode: fetched ${list.length} proxies from ${gj?.provider_name || "provider"}`);
        } catch (e) {
          setSubmitting(false);
          return toast.error(`Auto Mode failed: ${e.message || e}. Try disabling Auto Mode and pasting proxies manually.`);
        }
        }
      }
      const wantProxies = !effectiveUseProxyJetAuto && !useStoredProxies && !selectedUploadProxyId && selectedUploadProxyIds.length === 0 && effectiveProxies && effectiveProxies.trim();
      const wantUas = !selectedUploadUaId && selectedUploadUaIds.length === 0 && userAgents && userAgents.trim();
      const wantAj = formFillEnabled && (useCustomJson || funnelMode === "custom") && !selectedUploadAjId && automationJson.trim();
      const wantTarget = !!targetScreenshotFile;

      const [
        autoDataIdR, autoProxyIdR, autoUaIdR, autoAjIdR, autoTargetScreenshotIdR
      ] = await Promise.all([
        wantExcel ? preUpload("Excel data file",
          `${API_URL}/api/uploads/data-file`,
          (fd) => {
            fd.append("name", `auto-${Date.now()}-${file.name}`.slice(0, 80));
            fd.append("file", file);
          }) : Promise.resolve(""),
        wantProxies ? preUpload("Proxies",
          `${API_URL}/api/uploads/proxies`,
          (fd) => {
            fd.append("name", `auto-proxies-${Date.now()}`);
            fd.append("proxies", effectiveProxies);
          }) : Promise.resolve(""),
        wantUas ? preUpload("User-Agents",
          `${API_URL}/api/uploads/user-agents`,
          (fd) => {
            fd.append("name", `auto-uas-${Date.now()}`);
            fd.append("user_agents", userAgents);
          }) : Promise.resolve(""),
        wantAj ? preUpload("Automation JSON",
          `${API_URL}/api/uploads/automation-json`,
          (fd) => {
            fd.append("name", `auto-aj-${Date.now()}`);
            fd.append("automation_json", automationJson);
          }) : Promise.resolve(""),
        wantTarget ? preUpload("Target screenshot",
          `${API_URL}/api/uploads/target-screenshot`,
          (fd) => {
            fd.append("name", `auto-target-${Date.now()}`);
            fd.append("file", targetScreenshotFile);
          }) : Promise.resolve(""),
      ]);
      const autoDataId = autoDataIdR;
      const autoProxyId = autoProxyIdR;
      const autoUaId = autoUaIdR;
      const autoAjId = autoAjIdR;
      const autoTargetScreenshotId = autoTargetScreenshotIdR;

      const fd = new FormData();
      fd.append("link_id", linkId);
      if (targetUrlOverride.trim()) fd.append("target_url", targetUrlOverride.trim());

      // Target Screenshot Verification — prefer pre-uploaded ID (tiny payload).
      // Only fall back to inline multipart if pre-upload was somehow skipped
      // (shouldn't happen now that we always pre-upload above).
      if (autoTargetScreenshotId) {
        fd.append("target_screenshot_upload_id", autoTargetScreenshotId);
        fd.append(
          "target_screenshot_threshold",
          String(targetScreenshotThreshold)
        );
      } else if (targetScreenshotFile) {
        fd.append("target_screenshot", targetScreenshotFile);
        fd.append(
          "target_screenshot_threshold",
          String(targetScreenshotThreshold)
        );
      }

      // Use pre-uploaded IDs when available (smaller payload = no timeout)
      fd.append("proxies", autoProxyId ? "" : effectiveProxies);
      fd.append("user_agents", (autoUaId || selectedUploadUaIds.length > 0) ? "" : userAgents);
      fd.append("use_stored_proxies", String(useStoredProxies));
      // Uploaded batches — backend prefers these over pasted content
      // ── 2026-06-11: Proxy multi-batch — mirrors the UA multi-batch
      // pattern. When 2+ batches checked, send `upload_proxy_ids` (CSV)
      // and the backend merges + shuffles. Single batch falls back to
      // legacy `upload_proxy_id` for full backwards-compat (live-remove
      // + auto-delete after use both depend on the singular ID path).
      const finalDataId = selectedUploadDataId || autoDataId;
      if (selectedUploadProxyIds.length >= 2) {
        fd.append("upload_proxy_ids", selectedUploadProxyIds.join(","));
      } else {
        const finalProxyId =
          (selectedUploadProxyIds[0] || selectedUploadProxyId || autoProxyId);
        if (finalProxyId) fd.append("upload_proxy_id", finalProxyId);
      }
      // UA: multi-batch mode wins if the user checked any; otherwise
      // fall back to legacy single-batch (backward-compat with deep
      // links / stored drafts / auto-created batches).
      if (selectedUploadUaIds.length > 0) {
        fd.append("upload_ua_ids", selectedUploadUaIds.join(","));
      } else {
        const finalUaId = selectedUploadUaId || autoUaId;
        if (finalUaId) fd.append("upload_ua_id", finalUaId);
      }
      if (formFillEnabled && dataSource === "excel" && finalDataId) {
        fd.append("upload_data_file_id", finalDataId);
      }

      fd.append("total_clicks", String(totalClicks));
      fd.append("concurrency", String(concurrency));
      fd.append("duration_minutes", String(durationMinutes));
      fd.append("target_mode", targetMode);
      if (targetMode === "conversions") {
        fd.append("target_conversions", String(targetConversions));
        fd.append("max_attempts", String(maxAttempts));
      }

      fd.append("allowed_countries", allowedCountries.join(","));
      fd.append("allowed_os", allowedOs.join(","));
      fd.append("skip_duplicate_ip", String(skipDuplicateIp));
      fd.append("skip_vpn", String(skipVpn));
      fd.append("follow_redirect", String(followRedirect));
      fd.append("no_repeated_proxy", String(noRepeatedProxy));
      fd.append("force_tracker_url", String(forceTrackerUrl));
      // 2026-07 v2.6.9 CUSTOMER-REQUEST — tracker hard-block detection
      fd.append("abort_on_tracker_block", String(abortOnTrackerBlock));
      fd.append("tracker_block_extra_patterns", trackerBlockExtraPatterns || "");
      // ProxyJet Auto Mode — when ON the backend ignores proxies/use_stored_proxies/upload_proxy_id
      // and instead asks proxyjet_module to generate a fresh batch of
      // unique residential proxies (one-per-visit, no exit-IP ever reused).
      // v2.5.0 — When Auto Mode is routed through a non-ProxyJet provider
      // (effectiveUseProxyJetAuto=false above) we send `false` here so
      // the backend uses the pre-generated proxies list normally.
      fd.append("use_proxyjet_auto", String(effectiveUseProxyJetAuto));
      fd.append("proxyjet_country", (proxyJetCountry || "US").toUpperCase());
      fd.append("proxyjet_state", (proxyJetState || "").toUpperCase());
      // v2.4.0 — Multi-provider proxy dropdown. Empty ⇒ legacy behavior.
      fd.append("proxy_provider_id", proxyProviderId || "");
      // ── 2026-06-11: Multi-Geo MIX pools (CSV). Backend picks random
      // country/state per visit when 2+ entries. Single mode → empty
      // strings here → backend falls back to scalar fields above.
      if (pjGeoMode === "many" && pjCountriesPool.length >= 2) {
        fd.append("proxyjet_countries", pjCountriesPool.join(","));
      } else {
        fd.append("proxyjet_countries", "");
      }
      if (pjGeoMode === "many" && pjStatesPool.length >= 2) {
        fd.append("proxyjet_states", pjStatesPool.join(","));
      } else {
        fd.append("proxyjet_states", "");
      }
      // 2026-01: Per-job watchdog inactivity timeout. Pages stuck for
      // longer than this (URL not changing) are force-aborted. Default
      // 60 — raised from old hardcoded 25 to handle slow form-submit
      // sequences.
      fd.append("stuck_watchdog_seconds", String(stuckWatchdogSeconds || 600));
      // 2026-02 v2.1.31 — Anti-Detect Phase 1
      fd.append("pacing_per_hour", String(pacingPerHour || 0));
      fd.append("identity_label", identityLabel || "");
      fd.append("tls_prewarm", String(!!tlsPrewarm));
      // 2026-02 v2.1.31 — Step 3
      fd.append("proxy_chain_enabled", String(!!proxyChainEnabled));
      fd.append("proxy_chain_use_tor", String(!!proxyChainUseTor));
      fd.append("proxy_chain_extra_hops", proxyChainExtraHops || "");
      fd.append("browser_variant", browserVariant || "auto");
      // 2026-02 v2.1.31 — Step 4
      fd.append("behavioral_bio_enabled", String(!!behavioralBioEnabled));
      fd.append("ip_warmup_enabled", String(!!ipWarmupEnabled));
      fd.append("ad_chain_simulation_enabled", "true");
      fd.append("ip_quality_check_enabled", "true");

      // 2026-06 — Referrer Override (off-by-default, customer opt-in)
      fd.append("referer_override_enabled", String(!!refererOverrideEnabled));
      fd.append("referer_mode", refererMode || "auto");
      fd.append("referer_value", refererValue || "");
      fd.append("referer_platform_pool", refererPlatformPool || "");
      fd.append("referer_brand", refererBrand || "");

      // ── 2026-06-11: Referrer Pro-Mode (weighted, realism layers) ──
      fd.append("referer_pro_mode", String(!!refererProMode));
      // JSON-serialise weight dicts only when non-empty (saves bandwidth
      // + keeps backend in legacy mode when user never touched the UI).
      if (refererProMode && refererPlatformWeights && Object.keys(refererPlatformWeights).length > 0) {
        fd.append("referer_platform_weights", JSON.stringify(refererPlatformWeights));
      } else {
        fd.append("referer_platform_weights", "");
      }
      if (refererProMode && refererEmailWeights && Object.keys(refererEmailWeights).length > 0) {
        fd.append("referer_email_weights", JSON.stringify(refererEmailWeights));
      } else {
        fd.append("referer_email_weights", "");
      }
      fd.append("referer_social_wrapper", String(!!refererSocialWrapper));
      fd.append("referer_inapp_deep", String(!!refererInappDeep));
      // v2.6.25 — send paid/organic split to backend engine
      fd.append("referer_traffic_type", String(refererTrafficType || "auto"));
      fd.append("referer_campaign_type", String(refererCampaignType || "auto"));
      fd.append("referer_search_engine", refererSearchEngine || "google");
      fd.append("referer_search_keywords", refererSearchKeywords || "");
      fd.append("referer_strip_search_path", String(!!refererStripSearchPath));
      fd.append("referer_network_click_chain", String(!!refererNetworkClickChain));
      // 2026-01 — Pass-Referer-To-Offer (direct offer navigation).
      fd.append("referer_pass_to_offer", String(!!refererPassToOffer));
      // 2026-06-14 — UA ↔ Referer coercion (anti-fraud, default ON).
      fd.append("referer_match_ua_to_platform", String(!!refererMatchUaToPlatform));
      // 2026-07 v2.2.1 — In-App Browser Preset (one-click social)
      fd.append("inapp_browser_preset", (inappBrowserPreset && inappBrowserPreset !== "none") ? inappBrowserPreset : "");

      fd.append("form_fill_enabled", String(formFillEnabled));
      if (formFillEnabled) {
        fd.append("data_source", dataSource);
        // Skip raw file upload if we already pre-uploaded above (avoids
        // duplicate transfer + Cloudflare timeout).
        if (dataSource === "excel" && file && !autoDataId) fd.append("file", file);
        if (dataSource === "gsheet") fd.append("gsheet_url", gsheetUrl.trim());
        if (dataSource === "pending_from_job") {
          fd.append("import_pending_from_job_id", importPendingJobId);
        }
        fd.append("state_match_enabled", String(stateMatchEnabled));
        // Only send selected_states if user actually subset the file
        // (i.e. preview was loaded AND user deselected something).
        // Empty string = no filter (backend uses all rows).
        if (
          dataPreview &&
          dataPreview.states &&
          dataPreview.states.length > 0 &&
          selectedStates.length > 0 &&
          selectedStates.length < dataPreview.states.length
        ) {
          fd.append("selected_states", selectedStates.join(","));
        }
        // 2026-06 — Email-domain subset: same semantics as states.
        // Only send when user has narrowed to a subset of detected
        // domains; empty string = no filter (backend uses all rows).
        if (
          dataPreview &&
          dataPreview.email_domains &&
          dataPreview.email_domains.length > 0 &&
          selectedEmailDomains.length > 0 &&
          selectedEmailDomains.length < dataPreview.email_domains.length
        ) {
          fd.append("selected_email_domains", selectedEmailDomains.join(","));
        }
        fd.append("invalid_detection_enabled", String(invalidDetectionEnabled));
        fd.append("invalid_data_retry_limit", String(invalidDataRetryLimit));
        fd.append("step_timeout_multiplier", String(stepTimeoutMultiplier));
        fd.append("skip_captcha", String(skipCaptcha));
        fd.append("post_submit_wait", String(postSubmitWait));
        fd.append("smart_funnel_enabled", String(funnelMode === "smart"));
        if (funnelMode === "smart") {
          fd.append("smart_funnel_pattern", smartFunnelPattern || "auto");
          fd.append("smart_funnel_min_deals", String(smartFunnelMinDeals));
          fd.append("smart_funnel_wait_until_conversion", String(!!smartFunnelWaitUntilConversion));
        }
        if (useCustomJson || funnelMode === "custom") {
          const finalAjId = selectedUploadAjId || autoAjId;
          if (finalAjId) {
            fd.append("upload_automation_json_id", finalAjId);
          } else if (automationJson.trim()) {
            fd.append("automation_json", automationJson);
          }
        }
        fd.append("self_heal", String(selfHeal));
        fd.append("pure_json_mode", String(pureJsonMode));
        fd.append("auto_resume_enabled", String(autoResumeEnabled));
      }

      // 2026-05 — Smoke test override (forces total=1, concurrency=1 on
      // the backend so user can validate the recording before spending
      // budget on a 1000-visit run).
      if (isSmokeTest) {
        fd.append("smoke_test", "true");
      }

      // Snapshot of the latest job-id BEFORE posting, used by the
      // fallback-detection branch below to tell whether a fetch-abort
      // actually meant the job DID start on the backend.
      jobsBefore = new Set((await (async () => {
        try {
          const rr = await fetch(`${API_URL}/api/real-user-traffic/jobs`, { headers: authH() });
          if (!rr.ok) return [];
          const jj = await rr.json();
          return Array.isArray(jj) ? jj : (jj.jobs || []);
        } catch { return []; }
      })()).map((j) => j.job_id));

      // Resilient submit: very generous timeout + TWO silent retries on
      // transient network abort. Cloudflare-tunnel idle-timeouts are
      // usually ~100s, but the backend's job-create endpoint now returns
      // within ~100ms because all heavy prep (gsheet fetches, Excel
      // parse, dup-IP scan) is deferred to a background task. We use
      // a 600s ceiling so even on a heavily loaded box / many parallel
      // submissions / extra-slow tunnel the submit will NEVER time out
      // before the response arrives.
      const submitOnce = async () => {
        const ac = new AbortController();
        const timer = setTimeout(() => ac.abort(), 600_000);
        try {
          return await fetch(`${API_URL}/api/real-user-traffic/jobs`, {
            method: "POST",
            headers: authH(),
            body: fd,
            signal: ac.signal,
          });
        } finally {
          clearTimeout(timer);
        }
      };
      let r;
      try {
        r = await submitOnce();
      } catch (firstErr) {
        const fmsg = (firstErr && firstErr.message) ? firstErr.message : String(firstErr);
        const transient = /failed to fetch|networkerror|load failed|aborted|timeout/i.test(fmsg);
        if (!transient) throw firstErr;
        // First retry after 2s — backend has just finished any cold-
        // start gsheet fetches and cached `last_synced_at` so the
        // second call returns fast.
        await new Promise((res) => setTimeout(res, 2000));
        try {
          r = await submitOnce();
        } catch (secondErr) {
          const smsg = (secondErr && secondErr.message) ? secondErr.message : String(secondErr);
          const stillTransient = /failed to fetch|networkerror|load failed|aborted|timeout/i.test(smsg);
          if (!stillTransient) throw secondErr;
          // Final retry after 4s — if even this fails we fall through
          // to the recovery-poll branch below which will pick the job
          // up from the /jobs list (backend inserts the DB row before
          // any heavy work, so the job IS there).
          await new Promise((res) => setTimeout(res, 4000));
          r = await submitOnce();
        }
      }
      let data = null;
      try { data = await r.json(); } catch (_) { data = null; }
      if (!r.ok) {
        // FastAPI can return detail/error as string, object, or array of validation errors.
        // Normalise so toast never shows "[object Object]".
        const raw = data && (data.detail !== undefined ? data.detail : data.error);
        let msg = "";
        if (typeof raw === "string") {
          msg = raw;
        } else if (Array.isArray(raw)) {
          msg = raw
            .map((it) => (it && (it.msg || it.message)) ? `${it.msg || it.message}${it.loc ? ` (${it.loc.join('.')})` : ''}` : JSON.stringify(it))
            .join("; ");
        } else if (raw && typeof raw === "object") {
          msg = raw.msg || raw.message || JSON.stringify(raw);
        }
        throw new Error(msg || `HTTP ${r.status}`);
      }
      toast.success(`Job started: ${data.total} visit(s) queued`);
      // Clear selected uploaded batches — they'll be deleted server-side
      // when the job finishes. Also refresh the library so the UI reflects
      // what's still available for future campaigns.
      setSelectedUploadProxyId("");
      setSelectedUploadUaId("");
      setSelectedUploadUaIds([]);
      setSelectedUploadDataId("");
      await fetchJobs();
      fetchUploadedLibrary();
      startPolling(data.job_id);
    } catch (e) {
      // Better diagnostics: "Failed to fetch" is usually a network/ingress abort
      console.error("RUT job start failed:", e);
      const raw = (e && e.message) ? e.message : String(e);
      const isNetworkAbort = /failed to fetch|networkerror|load failed|aborted|timeout/i.test(raw);

      // If the main POST was aborted by the network (tunnel/ingress)
      // even after multiple silent retries, the backend may STILL have
      // already accepted the job (the tunnel can drop the response
      // while the server keeps processing). Poll the past-jobs list
      // for up to 600s (10 min) — backend inserts the DB row BEFORE
      // any heavy work so the job is guaranteed to be there.
      if (isNetworkAbort && jobsBefore) {
        const deadline = Date.now() + 600_000;
        let recovered = null;
        while (Date.now() < deadline) {
          await new Promise((res) => setTimeout(res, 2500));
          try {
            const rr = await fetch(`${API_URL}/api/real-user-traffic/jobs`, { headers: authH() });
            if (rr.ok) {
              const jj = await rr.json();
              const list = Array.isArray(jj) ? jj : (jj.jobs || []);
              const fresh = list.find((j) => !jobsBefore.has(j.job_id));
              if (fresh) { recovered = fresh; break; }
            }
          } catch { /* keep polling */ }
        }
        if (recovered) {
          toast.success("Job started (auto-recovered after network timeout)");
          setSelectedUploadProxyId("");
          setSelectedUploadUaId("");
          setSelectedUploadUaIds([]);
          setSelectedUploadDataId("");
          await fetchJobs();
          fetchUploadedLibrary();
          startPolling(recovered.job_id);
          return;
        }
      }

      let friendly = raw;
      if (isNetworkAbort) {
        friendly = "Network aborted 3x + 600s recovery poll failed — job DID NOT start. " +
                   "Most likely cause: Cloudflare tunnel down OR backend container restarting. " +
                   "Steps: (1) Check tunnel status (cloudflared logs / Cloudflare dashboard). " +
                   "(2) `docker compose ps` — is `krexion-backend` healthy? " +
                   "(3) Refresh Past Jobs list once more — the job may still appear there.";
      }
      toast.error(friendly);
    } finally {
      setSubmitting(false);
    }
  };

  const onDownload = async (jobId) => {
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/${jobId}/download`, { headers: authH() });
      if (!r.ok) return toast.error("Results not ready yet");
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `real-user-traffic-${jobId.slice(0, 8)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error("Download failed"); }
  };

  const onDownloadPendingLeads = async (jobId) => {
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/${jobId}/pending-leads`, { headers: authH() });
      if (!r.ok) {
        const txt = await r.text().catch(() => "");
        return toast.error(txt.includes("not found") ? "No pending leads file (this run had no data file)" : "Pending leads not ready");
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pending_leads_${jobId.slice(0, 8)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Pending leads downloaded — upload this as next run's data");
    } catch (e) { toast.error("Download failed"); }
  };

  const onDelete = async (jobId) => {
    if (!window.confirm("Delete this job and its results?")) return;
    try {
      await fetch(`${API_URL}/api/real-user-traffic/jobs/${jobId}`, {
        method: "DELETE",
        headers: authH(),
      });
      toast.success("Deleted");
      if (activeJob?.job_id === jobId) setActiveJob(null);
      setSelectedJobIds((prev) => {
        const n = new Set(prev); n.delete(jobId); return n;
      });
      fetchJobs();
    } catch (e) { /* ignore */ }
  };

  const onStop = async (jobId) => {
    if (!window.confirm("Stop this job now? Partial screenshots + Excel will be packaged for download.")) return;
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/${jobId}/stop`, {
        method: "POST",
        headers: authH(),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return toast.error(data.detail || "Stop failed");
      if (data.stopped) toast.success("Stop signal sent — finalising partial results…");
      else toast.info(data.message || "Job already finished");
      // Keep polling so UI flips to `stopped` + enables Download
      fetchJobs();
      if (activeJob?.job_id === jobId) startPolling(jobId);
    } catch (e) { toast.error("Stop request failed"); }
  };

  const onBulkDelete = async () => {
    const ids = Array.from(selectedJobIds);
    if (ids.length === 0) return;
    if (!window.confirm(`Delete ${ids.length} selected job(s)?`)) return;
    try {
      const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/bulk-delete`, {
        method: "POST",
        headers: { ...authH(), "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: ids }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed");
      toast.success(`Deleted ${d.deleted} job(s)`);
      if (activeJob && ids.includes(activeJob.job_id)) setActiveJob(null);
      setSelectedJobIds(new Set());
      fetchJobs();
    } catch (e) {
      toast.error(e.message || "Bulk delete failed");
    }
  };

  const toggleJobSelected = (jobId) => {
    setSelectedJobIds((prev) => {
      const n = new Set(prev);
      if (n.has(jobId)) n.delete(jobId); else n.add(jobId);
      return n;
    });
  };

  const toggleSelectAll = () => {
    if (selectedJobIds.size === jobs.length && jobs.length > 0) {
      setSelectedJobIds(new Set());
    } else {
      setSelectedJobIds(new Set(jobs.map((j) => j.job_id)));
    }
  };

  return (
    <div className="space-y-5" data-testid="real-user-traffic-page">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Fingerprint className="text-fuchsia-400" size={28} />
            Real User Traffic
          </h1>
          <p className="text-zinc-400 text-sm mt-1">
            Add clicks with custom IPs, user agents, countries & OS — optionally auto-fill the
            landing-page form with Excel/CSV or Google Sheet data.
          </p>
        </div>
        {/* Engine Status badge — auto-polled every 5s. Lets users know
            instantly whether the Chromium engine is ready, still
            installing on a fresh pod, missing, or errored. Pre-warm
            button appears when status is missing/error so users can
            kick off the install BEFORE running a campaign. */}
        <EngineStatusBadge
          status={engineStatus}
          onPrewarm={handleEnginePrewarm}
          prewarming={enginePrewarming}
        />
      </div>

      {/* ═══ Select Link ═══ */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader className="pb-3">
          <CardTitle className="text-white flex items-center gap-2 text-base">
            <Globe size={18} className="text-blue-400" /> Select Link
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <select
            data-testid="rut-link-select"
            value={linkId}
            onChange={(e) => setLinkId(e.target.value)}
            className="w-full h-11 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
          >
            <option value="">Select a link…</option>
            {links.map((l) => (
              <option key={l.id} value={l.id}>
                /{l.short_code} → {l.offer_url?.slice(0, 70)}
                {l.offer_url && l.offer_url.length > 70 ? "…" : ""}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>

      {/* ═══ Real Traffic Config ═══ */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2 text-base">
            <Radio size={18} className="text-red-400" /> Real Traffic via Residential Proxies
          </CardTitle>
          <CardDescription className="text-zinc-400 text-xs">
            Fires <strong>real</strong> browser sessions against your selected short link through each
            proxy you paste. Each exit IP is checked for duplicates · VPN · allowed country · allowed
            OS <strong>BEFORE</strong> the click is sent — so only clean traffic reaches your tracker.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* v2.4.0 — Multi-provider proxy dropdown */}
          <div className="rounded-md border border-blue-500/30 bg-blue-950/20 p-3" data-testid="rut-proxy-provider-block">
            <ProxyProviderSelect
              value={proxyProviderId}
              onChange={setProxyProviderId}
              label="Proxy source (pick from your Settings › Proxy Providers)"
              testIdPrefix="rut-proxy-provider"
            />
            {proxyProviderId && (
              <p className="text-[10px] text-blue-300 mt-1">
                ✓ Auto Mode below (when enabled) will pull proxies from this provider. Paste / upload
                fields are optional and only used if Auto Mode is OFF.
              </p>
            )}
          </div>

          {/* ── Auto Mode toggle (works with the selected Proxy Provider) ── */}
          <div
            className={`rounded-md border p-3 transition-colors ${
              useProxyJetAuto
                ? "bg-gradient-to-r from-indigo-950/40 via-indigo-950/20 to-transparent border-indigo-500/40"
                : "bg-zinc-900/40 border-zinc-700/60"
            }`}
            data-testid="rut-auto-mode-block"
          >
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={useProxyJetAuto}
                onChange={(e) => setUseProxyJetAuto(e.target.checked)}
                className="mt-1 w-4 h-4 accent-indigo-500"
                data-testid="rut-use-auto-mode"
              />
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-indigo-200 font-medium text-sm">
                    🚀 Auto Mode
                  </span>
                  {proxyProviderId ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                      ✓ using selected provider
                    </span>
                  ) : (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
                      pick a Proxy source above
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-zinc-400 mt-1 leading-snug">
                  Skip pasting proxies entirely. When ON, a fresh batch of proxies is auto-generated
                  from whichever <b className="text-indigo-300">Proxy source</b> you picked above
                  (any kind — rotating gateway, API endpoint, manual list, custom provider).
                  Add providers in <i>Settings › Proxy Providers</i> — they show up in the dropdown above.
                </p>
                {useProxyJetAuto && (
                  <div className="mt-3 space-y-2">
                    {/* ── Single / Multi toggle ──────────────────── */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <Label className="text-xs text-zinc-300">Geo:</Label>
                      <div
                        className="inline-flex rounded-md overflow-hidden border border-zinc-700 text-[10px]"
                        data-testid="rut-pj-geo-mode"
                      >
                        <button
                          type="button"
                          onClick={() => setPjGeoMode("one")}
                          className={`px-2 py-0.5 ${pjGeoMode === "one" ? "bg-blue-600 text-white" : "bg-zinc-900 text-zinc-400 hover:text-white"}`}
                        >
                          Single
                        </button>
                        <button
                          type="button"
                          onClick={() => setPjGeoMode("many")}
                          className={`px-2 py-0.5 border-l border-zinc-700 ${pjGeoMode === "many" ? "bg-blue-600 text-white" : "bg-zinc-900 text-zinc-400 hover:text-white"}`}
                        >
                          Multi (random mix)
                        </button>
                      </div>
                      {pjGeoMode === "many" && (
                        <span className="text-[10px] text-blue-300">
                          {pjCountriesPool.length >= 2
                            ? `${pjCountriesPool.length} countries selected`
                            : "Click 2+ countries below"}
                          {pjStatesPool.length >= 2 && ` · ${pjStatesPool.length} states`}
                        </span>
                      )}
                    </div>

                    {/* ── Single mode (legacy) ────────────────────── */}
                    {pjGeoMode === "one" && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Label className="text-xs text-zinc-300">Country:</Label>
                        <select
                          value={proxyJetCountry}
                          onChange={(e) => {
                            setProxyJetCountry(e.target.value);
                            if (e.target.value !== "US") setProxyJetState("");
                          }}
                          className="h-8 px-2 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                          data-testid="rut-proxyjet-country"
                        >
                          {["US","CA","GB","DE","FR","AU","BR","IN","JP","IT","ES","NL","MX"].map((c) => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                        </select>
                        {proxyJetCountry === "US" && (
                          <>
                            <Label className="text-xs text-zinc-300 ml-2">State:</Label>
                            <select
                              value={proxyJetState}
                              onChange={(e) => setProxyJetState(e.target.value)}
                              className="h-8 px-2 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                              data-testid="rut-proxyjet-state"
                            >
                              <option value="">Any</option>
                              {["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"].map((s) => (
                                <option key={s} value={s}>{s}</option>
                              ))}
                            </select>
                          </>
                        )}
                      </div>
                    )}

                    {/* ── Multi mode (random mix) ─────────────────── */}
                    {pjGeoMode === "many" && (
                      <div className="space-y-2 bg-zinc-950/50 border border-zinc-800 rounded p-2">
                        <div>
                          <Label className="text-[11px] text-zinc-300 block mb-1">
                            Countries — random pick per visit
                          </Label>
                          <div className="flex flex-wrap gap-1">
                            {["US","CA","GB","DE","FR","AU","BR","IN","JP","IT","ES","NL","MX"].map((c) => {
                              const active = pjCountriesPool.includes(c);
                              return (
                                <button
                                  key={c}
                                  type="button"
                                  onClick={() =>
                                    setPjCountriesPool((prev) =>
                                      prev.includes(c)
                                        ? prev.filter((k) => k !== c)
                                        : [...prev, c]
                                    )
                                  }
                                  className={`px-2 py-0.5 rounded text-[11px] border transition ${
                                    active
                                      ? "bg-blue-600 border-blue-500 text-white"
                                      : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"
                                  }`}
                                  data-testid={`rut-pj-country-${c}`}
                                >
                                  {c}
                                </button>
                              );
                            })}
                            <button
                              type="button"
                              onClick={() => setPjCountriesPool([])}
                              className="ml-1 px-2 py-0.5 rounded text-[10px] bg-zinc-900 border border-zinc-700 text-zinc-400 hover:text-white"
                              data-testid="rut-pj-countries-clear"
                            >
                              Clear
                            </button>
                          </div>
                        </div>

                        {(pjCountriesPool.includes("US") || pjCountriesPool.length === 0) && (
                          <div>
                            <Label className="text-[11px] text-zinc-300 block mb-1">
                              US States — random pick per visit{" "}
                              <span className="text-zinc-500">(optional — leave empty for any-state)</span>
                            </Label>
                            <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                              {["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"].map((s) => {
                                const active = pjStatesPool.includes(s);
                                return (
                                  <button
                                    key={s}
                                    type="button"
                                    onClick={() =>
                                      setPjStatesPool((prev) =>
                                        prev.includes(s)
                                          ? prev.filter((k) => k !== s)
                                          : [...prev, s]
                                      )
                                    }
                                    className={`px-1.5 py-0.5 rounded text-[10px] border transition ${
                                      active
                                        ? "bg-emerald-600 border-emerald-500 text-white"
                                        : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"
                                    }`}
                                    data-testid={`rut-pj-state-${s}`}
                                  >
                                    {s}
                                  </button>
                                );
                              })}
                              <button
                                type="button"
                                onClick={() => setPjStatesPool([])}
                                className="ml-1 px-2 py-0.5 rounded text-[10px] bg-zinc-900 border border-zinc-700 text-zinc-400 hover:text-white"
                                data-testid="rut-pj-states-clear"
                              >
                                Clear
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    <span className="block text-[10px] text-indigo-300">
                      Anti-detect safeties (no-repeated-proxy + skip-duplicate-IP) auto-enabled.
                    </span>
                  </div>
                )}
              </div>
            </label>
          </div>

          {/* Proxies + UAs side-by-side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className={useProxyJetAuto ? "opacity-50 pointer-events-none" : ""}>
              <div className="flex items-center justify-between mb-1">
                <Label className="text-zinc-300">
                  Proxies (one per line)
                  {useProxyJetAuto && <span className="ml-2 text-[10px] text-indigo-300">— disabled (Auto Mode ON)</span>}
                </Label>
                <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={useStoredProxies}
                    onChange={(e) => setUseStoredProxies(e.target.checked)}
                    className="w-3.5 h-3.5 accent-fuchsia-500"
                    data-testid="rut-use-stored-proxies"
                    disabled={useProxyJetAuto}
                  />
                  Use my stored proxies
                </label>
              </div>
              {/* Uploaded proxy batch picker (multi-select since 2026-06-11) */}
              {uploadedLibrary.filter(u => u.type === "proxies").length > 0 && (
                <div className="mb-2 p-2 bg-indigo-950/30 border border-indigo-900/50 rounded">
                  <div className="flex items-center justify-between mb-1">
                    <Label className="text-indigo-300 text-xs">
                      Or pick saved batch(es) from <span className="font-semibold">Uploaded Things</span>
                    </Label>
                    {selectedUploadProxyIds.length > 0 && (
                      <span className="text-[10px] text-blue-300">
                        {selectedUploadProxyIds.length} batch{selectedUploadProxyIds.length === 1 ? "" : "es"} selected
                        {selectedUploadProxyIds.length >= 2 && " · will be merged + shuffled"}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
                    {uploadedLibrary.filter(u => u.type === "proxies").map((u) => {
                      const active = selectedUploadProxyIds.includes(u.id);
                      return (
                        <button
                          key={u.id}
                          type="button"
                          onClick={() =>
                            setSelectedUploadProxyIds((prev) =>
                              prev.includes(u.id)
                                ? prev.filter((x) => x !== u.id)
                                : [...prev, u.id]
                            )
                          }
                          className={`px-2 py-1 rounded text-[11px] border transition text-left ${
                            active
                              ? "bg-indigo-600 border-indigo-500 text-white"
                              : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"
                          }`}
                          data-testid={`rut-upload-proxy-batch-${u.id}`}
                        >
                          {u.name} · {u.country_tag || "?"}{u.state_tag ? `/${u.state_tag}` : ""} · {u.item_count}
                        </button>
                      );
                    })}
                    {selectedUploadProxyIds.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setSelectedUploadProxyIds([])}
                        className="px-2 py-1 rounded text-[10px] bg-zinc-900 border border-zinc-700 text-zinc-400 hover:text-white"
                        data-testid="rut-upload-proxy-batches-clear"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="text-[10px] text-zinc-500 mt-1">
                    Multiple batches → merged + randomly interleaved per visit. Single batch → legacy behaviour (auto-delete after use).
                  </p>
                </div>
              )}
              <Textarea
                data-testid="rut-proxies"
                rows={(selectedUploadProxyId || selectedUploadProxyIds.length > 0) ? 5 : 9}
                placeholder={"user:pass@host:port\nuser:pass@host:port"}
                value={proxies}
                onChange={(e) => setProxies(e.target.value)}
                disabled={useStoredProxies || !!selectedUploadProxyId || selectedUploadProxyIds.length > 0}
                className="bg-zinc-800 border-zinc-700 text-zinc-100 font-mono text-xs disabled:opacity-50"
              />
              <p className="text-xs text-zinc-500 mt-1">
                {selectedUploadProxyIds.length >= 2
                  ? `Using ${selectedUploadProxyIds.length} uploaded batches (merged + shuffled, batches preserved for re-use)`
                  : (selectedUploadProxyId || selectedUploadProxyIds.length === 1)
                    ? "Using uploaded batch (will auto-delete after job)"
                    : useStoredProxies
                      ? "Using your saved proxies from the Proxies page."
                      : `${proxyCount} proxies`}
              </p>
            </div>
            <div>
              <Label className="text-zinc-300 mb-1 block">User Agents (one per line)</Label>
              {/* Uploaded UA batch picker — multi-select so a single job
                  can span iPhone + Android + iPad pools at once.
                  Engine round-robins across the merged pool and $pulls
                  each consumed UA from its ORIGINAL batch (via ua→batch
                  map on the server). */}
              {uploadedLibrary.filter(u => u.type === "user_agents").length > 0 && (
                <div className="mb-2 p-2 bg-indigo-950/30 border border-indigo-900/50 rounded">
                  <Label className="text-indigo-300 text-xs mb-1 block">
                    Or pick saved batches from <span className="font-semibold">Uploaded Things</span> —{" "}
                    <span className="text-amber-300/80">check multiple</span> to mix devices in one job (e.g., iPhone + Android)
                  </Label>
                  <div
                    className="max-h-36 overflow-y-auto bg-zinc-900/60 border border-zinc-700 rounded divide-y divide-zinc-800"
                    data-testid="rut-upload-ua-multiselect"
                  >
                    {uploadedLibrary.filter(u => u.type === "user_agents").map((u) => {
                      const checked = selectedUploadUaIds.includes(u.id);
                      const available = Number(u.available_count ?? u.item_count ?? 0);
                      const isDepleted = !!u.depleted || available === 0;
                      return (
                        <label
                          key={u.id}
                          className={`flex items-center gap-2 px-2 py-1.5 text-xs cursor-pointer hover:bg-indigo-950/40 ${isDepleted ? "opacity-50" : ""}`}
                          data-testid={`rut-ua-option-${u.id}`}
                        >
                          <input
                            type="checkbox"
                            className="accent-indigo-500"
                            checked={checked}
                            disabled={isDepleted}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedUploadUaIds([...selectedUploadUaIds, u.id]);
                              } else {
                                setSelectedUploadUaIds(selectedUploadUaIds.filter(x => x !== u.id));
                              }
                            }}
                          />
                          <span className="flex-1 text-zinc-100 truncate">
                            <span className="font-medium">{u.name}</span>
                            <span className="text-zinc-400"> · {u.os_tag || "?"}{u.network_tag ? `/${u.network_tag}` : ""} · </span>
                            <span className={available > 0 ? "text-emerald-300" : "text-red-400"}>
                              {available}
                            </span>
                            <span className="text-zinc-500"> UAs</span>
                            {isDepleted && <span className="ml-1 text-[10px] text-red-300 font-bold">● DEPLETED</span>}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                  {selectedUploadUaIds.length > 0 && (
                    <div className="flex items-center justify-between mt-1.5 text-[11px]">
                      <span className="text-emerald-300">
                        {selectedUploadUaIds.length} batch{selectedUploadUaIds.length !== 1 ? "es" : ""} selected · mixed-device mode ON
                      </span>
                      <button
                        type="button"
                        onClick={() => setSelectedUploadUaIds([])}
                        className="text-indigo-300 hover:text-indigo-200 underline-offset-2 hover:underline"
                        data-testid="rut-ua-clear-all"
                      >
                        clear all
                      </button>
                    </div>
                  )}
                  {selectedUploadUaIds.length >= 2 && deviceMix.grand > 0 && (
                    <div
                      className="mt-2 p-2 bg-zinc-900/40 border border-zinc-700 rounded"
                      data-testid="rut-device-mix"
                    >
                      <div className="text-[11px] text-zinc-400 mb-1.5 font-medium">
                        📊 Estimated device mix — based on merged pool of{" "}
                        <span className="text-zinc-200">{deviceMix.grand.toLocaleString()}</span> UAs
                      </div>
                      <div
                        className="flex h-3 rounded overflow-hidden bg-zinc-800"
                        role="img"
                        aria-label="Device mix bar"
                      >
                        {deviceMix.entries.map(([os, count]) => {
                          const pct = (count / deviceMix.grand) * 100;
                          const color = DEVICE_MIX_COLORS[os] || DEVICE_MIX_COLORS.other;
                          const label = DEVICE_MIX_LABELS[os] || os;
                          return (
                            <div
                              key={os}
                              style={{ width: `${pct}%`, backgroundColor: color }}
                              title={`${label}: ${count.toLocaleString()} UAs (${pct.toFixed(1)}%)`}
                              data-testid={`rut-device-mix-bar-${os}`}
                            />
                          );
                        })}
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-[10px]">
                        {deviceMix.entries.map(([os, count]) => {
                          const pct = (count / deviceMix.grand) * 100;
                          const color = DEVICE_MIX_COLORS[os] || DEVICE_MIX_COLORS.other;
                          const label = DEVICE_MIX_LABELS[os] || os;
                          return (
                            <span
                              key={os}
                              className="inline-flex items-center gap-1"
                              data-testid={`rut-device-mix-legend-${os}`}
                            >
                              <span
                                className="inline-block w-2 h-2 rounded-full"
                                style={{ backgroundColor: color }}
                              />
                              <span className="text-zinc-200">{label}</span>
                              <span className="text-zinc-500">
                                · {pct.toFixed(0)}% ({count.toLocaleString()})
                              </span>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
              <div className="flex items-center justify-between mb-1">
                <Label className="text-zinc-300 text-sm" htmlFor="rut-user-agents">User Agents (one per line)</Label>
                <button
                  type="button"
                  onClick={() => setUaGenOpen((v) => !v)}
                  disabled={selectedUploadUaIds.length > 0}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-500/40 text-emerald-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  data-testid="rut-ua-gen-toggle"
                  title="Generate realistic UAs inline — no need to visit UA Generator page"
                >
                  <span className="text-xs">✨</span> Generate UAs
                </button>
              </div>

              {/* Inline UA Generator panel (collapsed by default) */}
              {uaGenOpen && (
                <div
                  className="mb-2 p-3 rounded-md bg-emerald-950/30 border border-emerald-500/30 space-y-2"
                  data-testid="rut-ua-gen-panel"
                >
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    <div>
                      <Label className="text-[10px] text-zinc-400 uppercase tracking-wide">App</Label>
                      <select
                        value={uaGenApp}
                        onChange={(e) => setUaGenApp(e.target.value)}
                        className="w-full h-8 px-2 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                        data-testid="rut-ua-gen-app"
                      >
                        <option value="chrome">Chrome (web)</option>
                        <option value="instagram">Instagram</option>
                        <option value="facebook">Facebook</option>
                        <option value="tiktok">TikTok</option>
                        <option value="snapchat">Snapchat</option>
                        <option value="pinterest">Pinterest</option>
                      </select>
                    </div>
                    <div>
                      <Label className="text-[10px] text-zinc-400 uppercase tracking-wide">Platform</Label>
                      <select
                        value={uaGenPlatform}
                        onChange={(e) => setUaGenPlatform(e.target.value)}
                        className="w-full h-8 px-2 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                        data-testid="rut-ua-gen-platform"
                      >
                        <option value="any">Any (mix)</option>
                        <option value="android">Android</option>
                        <option value="ios">iOS</option>
                        <option value="desktop">Desktop</option>
                      </select>
                    </div>
                    <div>
                      <Label className="text-[10px] text-zinc-400 uppercase tracking-wide">Count</Label>
                      <Input
                        type="number"
                        min={1}
                        max={5000}
                        value={uaGenCount}
                        onChange={(e) => setUaGenCount(Number(e.target.value) || 50)}
                        className="h-8 bg-zinc-800 border-zinc-700 text-zinc-100 text-xs"
                        data-testid="rut-ua-gen-count"
                      />
                    </div>
                    <div className="flex items-end">
                      <Button
                        onClick={generateUAsInline}
                        disabled={uaGenBusy}
                        className="w-full h-8 bg-emerald-600 hover:bg-emerald-500 text-white text-xs"
                        data-testid="rut-ua-gen-run"
                      >
                        {uaGenBusy ? "Generating…" : "Generate & Append"}
                      </Button>
                    </div>
                  </div>
                  <p className="text-[10px] text-emerald-300/80">
                    Generated UAs are <b>appended</b> below — existing ones are preserved. Want full advanced
                    options (brand, regions, resolutions)? Open the <a href="/user-agent-generator" className="underline text-emerald-300">UA Generator page</a>.
                  </p>
                </div>
              )}

              <Textarea
                data-testid="rut-user-agents"
                rows={selectedUploadUaIds.length > 0 ? 5 : 9}
                placeholder={"Mozilla/5.0 (Linux; Android 15; SM-S928U) AppleWebKit/...\nMozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) ..."}
                value={userAgents}
                onChange={(e) => setUserAgents(e.target.value)}
                disabled={selectedUploadUaIds.length > 0}
                className="bg-zinc-800 border-zinc-700 text-zinc-100 font-mono text-xs disabled:opacity-50"
              />
              <p className="text-xs text-zinc-500 mt-1">
                {selectedUploadUaIds.length > 0
                  ? `Using ${selectedUploadUaIds.length} uploaded batch${selectedUploadUaIds.length !== 1 ? "es" : ""} — only used UAs will be removed per-row from each`
                  : `${uaCount} UAs · system auto-detects OS + device from each UA and matches viewport, platform, touch & canvas/WebGL spoof`}
              </p>
            </div>
          </div>

          {/* Target URL override */}
          <div>
            <Label className="text-zinc-300 text-sm">
              Target URL{" "}
              <span className="text-zinc-500 text-xs font-normal">
                (optional — paste your PUBLIC short-link URL if tracker isn't reachable from the
                internet, e.g. localhost / Docker / behind NAT)
              </span>
            </Label>
            <Input
              data-testid="rut-target-url"
              placeholder="https://yourdomain.com/t/insta  — leave empty to auto-detect"
              value={targetUrlOverride}
              onChange={(e) => setTargetUrlOverride(e.target.value)}
              className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100 text-sm font-mono"
            />
          </div>

          {/* AI Learning Panel — historical answer→conversion stats */}
          {effectiveOfferUrl && (
            <div className="p-4 bg-gradient-to-br from-purple-950/40 to-zinc-950/60 border border-purple-900/40 rounded-lg">
              <Label className="text-zinc-300 flex items-center gap-2 text-sm">
                <span className="inline-block w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
                AI Answer Learning
                <span className="text-xs text-zinc-500 font-normal">
                  — bot biases survey answers toward historically high-converting picks
                </span>
              </Label>
              {aiLearningLoading ? (
                <p className="text-xs text-zinc-500 mt-2" data-testid="ai-learning-loading">
                  Loading learning data…
                </p>
              ) : !aiLearning || aiLearning.questions_learned === 0 ? (
                <p className="text-xs text-zinc-500 mt-2" data-testid="ai-learning-empty">
                  No learning data yet for{" "}
                  <span className="font-mono text-purple-300">
                    {(() => {
                      try {
                        return new URL(effectiveOfferUrl).hostname;
                      } catch {
                        return effectiveOfferUrl.slice(0, 50);
                      }
                    })()}
                  </span>{" "}
                  — first run will be pure random. After ~10 conversions the bot will
                  auto-bias toward winning answers.
                </p>
              ) : (
                <div className="mt-3 space-y-3" data-testid="ai-learning-panel">
                  <div className="text-xs text-zinc-400">
                    <span className="text-purple-300 font-semibold">
                      {aiLearning.questions_learned}
                    </span>{" "}
                    questions learned ·{" "}
                    <span className="text-purple-300 font-semibold">
                      {aiLearning.total_clicks}
                    </span>{" "}
                    historical answer clicks recorded
                  </div>
                  {aiLearning.questions.map((q, i) => (
                    <div
                      key={i}
                      className="bg-zinc-950/60 border border-zinc-800 rounded p-3"
                      data-testid={`ai-learning-question-${i}`}
                    >
                      <div className="text-xs text-zinc-400 mb-2 truncate">
                        Q: {q.question || "(no signature)"}
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {(q.answers || []).slice(0, 6).map((a, j) => {
                          const isBest =
                            a.answer === q.best_answer && q.best_rate > 0;
                          return (
                            <div
                              key={j}
                              className={`flex items-center justify-between text-xs px-2 py-1 rounded ${
                                isBest
                                  ? "bg-purple-900/30 border border-purple-700/40"
                                  : "bg-zinc-900/40"
                              }`}
                            >
                              <span
                                className={
                                  isBest
                                    ? "text-purple-200 font-medium"
                                    : "text-zinc-400"
                                }
                              >
                                {isBest && "★ "}
                                {a.answer}
                              </span>
                              <span className="text-zinc-500 font-mono">
                                {a.conv}/{a.clicks} (
                                {Math.round((a.rate || 0) * 100)}%)
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Target Screenshot Verification — upload reference final page image */}
          <div className="p-4 bg-gradient-to-br from-emerald-950/40 to-zinc-950/60 border border-emerald-900/40 rounded-lg">
            <Label className="text-zinc-300 flex items-center gap-2 text-sm">
              <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
              Target Page Screenshot Verification{" "}
              <span className="text-xs text-zinc-500 font-normal">
                — upload a screenshot of the FINAL page each visit must reach;
                bot will pHash-compare and mark only matching visits as TRUE conversions
              </span>
            </Label>
            <div className="mt-3 flex flex-col md:flex-row gap-4">
              <div className="flex-1">
                <input
                  data-testid="rut-target-screenshot"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    setTargetScreenshotFile(f || null);
                    if (f) {
                      const url = URL.createObjectURL(f);
                      setTargetScreenshotPreview(url);
                    } else {
                      setTargetScreenshotPreview("");
                    }
                  }}
                  className="text-xs text-zinc-300 file:bg-emerald-700 file:hover:bg-emerald-600 file:text-white file:border-0 file:rounded file:px-3 file:py-1 file:mr-3 file:cursor-pointer"
                />
                <p className="text-xs text-zinc-500 mt-2">
                  Tip: open the offer in incognito with a US proxy, complete it
                  manually once, screenshot the final reward / "Congratulations"
                  / partner-deal page → upload here. Bot will count only visits
                  that visually match this page as conversions.
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <Label className="text-zinc-400 text-xs whitespace-nowrap">
                    Match strictness
                  </Label>
                  <Input
                    data-testid="rut-target-screenshot-threshold"
                    type="number"
                    min="0"
                    max="30"
                    value={targetScreenshotThreshold}
                    onChange={(e) =>
                      setTargetScreenshotThreshold(
                        Math.max(0, Math.min(30, Number(e.target.value || 12)))
                      )
                    }
                    className="w-20 bg-zinc-800 border-zinc-700 text-zinc-100 text-xs h-7"
                  />
                  <span className="text-xs text-zinc-500">
                    (lower = stricter · 12 default · 0 = pixel-perfect · 22 = same template)
                  </span>
                </div>
              </div>
              {targetScreenshotPreview && (
                <div
                  className="flex-shrink-0 relative"
                  data-testid="rut-target-screenshot-preview"
                >
                  <img
                    src={targetScreenshotPreview}
                    alt="target preview"
                    className="max-h-40 rounded border border-emerald-800/40 bg-zinc-950"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      setTargetScreenshotFile(null);
                      setTargetScreenshotPreview("");
                    }}
                    className="absolute -top-2 -right-2 bg-zinc-800 text-zinc-300 hover:text-white border border-zinc-700 rounded-full w-6 h-6 text-xs flex items-center justify-center"
                    data-testid="rut-target-screenshot-remove"
                  >
                    ×
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Pacing */}
          <div className="p-4 bg-zinc-950/60 border border-zinc-800 rounded-lg">
            <Label className="text-zinc-300 flex items-center gap-2 text-sm">
              <RefreshCw size={14} className="text-blue-400" /> Pacing — deliver clicks over time (optional)
            </Label>
            <p className="text-xs text-zinc-500 mt-1 mb-3">
              Set duration in minutes to spread the run. e.g. Target=1000 + Duration=20 → about one
              click every ~1.2s. Leave 0 to fire as fast as possible.
            </p>
            <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3">
              <div className="flex-1 md:max-w-xs">
                <Label className="text-zinc-400 text-xs">Duration (minutes)</Label>
                <Input
                  data-testid="rut-duration"
                  type="number"
                  min={0}
                  value={durationMinutes}
                  onChange={(e) => setDurationMinutes(Math.max(0, Number(e.target.value) || 0))}
                  className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {PACING_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    data-testid={`rut-pacing-${p.label}`}
                    onClick={() => setDurationMinutes(p.value)}
                    className={`px-3 py-1.5 rounded-md border text-xs font-medium transition ${
                      durationMinutes === p.value
                        ? p.label === "Instant"
                          ? "bg-red-600 border-red-500 text-white"
                          : "bg-fuchsia-600 border-fuchsia-500 text-white"
                        : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <span className="text-xs text-zinc-500 whitespace-nowrap ml-auto">
                {durationMinutes === 0 ? "As fast as proxies allow" : `~${(durationMinutes * 60 / Math.max(1, totalClicks)).toFixed(1)}s between clicks`}
              </span>
            </div>
          </div>

          {/* Total + Concurrency */}
          {/* Target-mode selector + conditional inputs */}
          <div>
            <Label className="text-zinc-300 text-sm mb-2 block">Run target</Label>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <button
                type="button"
                onClick={() => setTargetMode("clicks")}
                data-testid="rut-target-clicks-mode"
                className={`p-2.5 rounded-lg border text-sm font-medium transition flex items-center justify-center gap-2 ${
                  targetMode === "clicks"
                    ? "bg-cyan-600 border-cyan-500 text-white"
                    : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                }`}
              >
                📈 Total clicks (fixed count)
              </button>
              <button
                type="button"
                onClick={() => setTargetMode("conversions")}
                data-testid="rut-target-conversions-mode"
                className={`p-2.5 rounded-lg border text-sm font-medium transition flex items-center justify-center gap-2 ${
                  targetMode === "conversions"
                    ? "bg-emerald-600 border-emerald-500 text-white"
                    : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                }`}
              >
                🎯 Target conversions (keep trying)
              </button>
            </div>
            {targetMode === "conversions" && !formFillEnabled && (
              <p className="text-xs text-amber-400 bg-amber-950/30 border border-amber-900/50 rounded-md px-3 py-2 mb-3" data-testid="rut-conv-mode-warning">
                ⚠️ Conversions are only detected when Form Auto-Fill is ON (a conversion = thank-you page reached after submitting a lead). Enable <b>Form Auto-Fill</b> below or switch back to <b>Total clicks</b> mode.
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {targetMode === "clicks" ? (
              <div>
                <Label className="text-zinc-300 text-sm">Total Clicks Target</Label>
                <Input
                  data-testid="rut-total-clicks"
                  type="number"
                  min={1}
                  max={100000}
                  value={totalClicks}
                  onChange={(e) => setTotalClicks(Math.max(1, Math.min(100000, Number(e.target.value) || 1)))}
                  className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                />
                <p className="text-xs text-zinc-500 mt-1">Runs exactly this many visits.</p>
              </div>
            ) : (
              <>
                <div>
                  <Label className="text-zinc-300 text-sm">Target Conversions (thank-you pages)</Label>
                  <Input
                    data-testid="rut-target-conversions"
                    type="number"
                    min={1}
                    max={10000}
                    value={targetConversions}
                    onChange={(e) => setTargetConversions(Math.max(1, Math.min(10000, Number(e.target.value) || 1)))}
                    className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                  />
                  <p className="text-xs text-emerald-300 mt-1">Stops AS SOON AS this many conversions reach the thank-you page.</p>
                </div>
                <div>
                  <Label className="text-zinc-300 text-sm">Max Attempts (safety cap)</Label>
                  <Input
                    data-testid="rut-max-attempts"
                    type="number"
                    min={1}
                    max={100000}
                    value={maxAttempts}
                    onChange={(e) => setMaxAttempts(Math.max(1, Math.min(100000, Number(e.target.value) || 1)))}
                    className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                  />
                  <p className="text-xs text-zinc-500 mt-1">Hard cap — run stops when this many visits have been launched even if the target wasn't hit.</p>
                </div>
              </>
            )}
            <div>
              <Label className="text-zinc-300 text-sm">Concurrency (1–50) ⚡</Label>
              <Input
                data-testid="rut-concurrency"
                type="number"
                min={1}
                max={50}
                value={concurrency}
                onChange={(e) => setConcurrency(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
                className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
              />
              <p className="text-xs text-gray-500 mt-1">
                Recommended: 20-30 (safe) | 40-50 (ultra speed)
              </p>
            </div>
            <div>
              <Label className="text-zinc-300 text-sm">Stuck-Page Watchdog (sec) ⏱️</Label>
              <Input
                data-testid="rut-stuck-watchdog-seconds"
                type="number"
                min={30}
                max={1800}
                value={stuckWatchdogSeconds}
                onChange={(e) => setStuckWatchdogSeconds(Math.max(30, Math.min(1800, Number(e.target.value) || 600)))}
                className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
              />
              <p className="text-xs text-gray-500 mt-1">
                If page URL & DOM both stay frozen for this many seconds the visit is aborted. Default 600 (10 min) — survey-heavy / multi-deal offers need this much. Lower to 240 for fast fail-on-stuck. Range: 30-1800s. Dead proxies / chrome-errors are aborted instantly regardless.
              </p>
            </div>
          </div>

          {/* ── 2026-06-11: UNIFIED Anti-Detect (single toggle) ──
              Replaces former Anti-Detect (Phase 1/3/4) panels. When ON,
              ALL anti-detect features are auto-enabled with sensible
              production defaults — customer doesn't see internals. ── */}
          <div className="mt-6 p-4 rounded-lg border border-fuchsia-500/30 bg-gradient-to-r from-fuchsia-950/20 via-purple-950/10 to-zinc-950/10">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-fuchsia-300 text-base font-semibold">🛡️ Anti-Detect</span>
                <span className="text-[10px] text-zinc-500 px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-800">
                  One toggle · auto-tunes everything
                </span>
              </div>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  data-testid="rut-anti-detect-master"
                  type="checkbox"
                  checked={antiDetectMaster}
                  onChange={(e) => {
                    const on = e.target.checked;
                    setAntiDetectMaster(on);
                    if (on) {
                      // Auto-tune ALL underlying anti-detect features with
                      // production-grade defaults. Customer doesn't see
                      // what got enabled — privacy by design.
                      if (!pacingPerHour) setPacingPerHour(30);
                      setTlsPrewarm(true);
                      setBehavioralBioEnabled(true);
                      setIpWarmupEnabled(true);
                      setBrowserVariant("rotate");
                      // Multi-hop proxy chain stays opt-in (heavy resource
                      // — Tor adds ~3-5s per visit). Auto-enable only when
                      // proxies list exists and customer wants paranoia.
                    } else {
                      // Reset heavy opt-ins only — production anti-detect
                      // baselines (TLS prewarm, IP warm-up, behavioral bio)
                      // stay ON per v2.6.35 defaults.
                      setBrowserVariant("auto");
                      setProxyChainEnabled(false);
                    }
                  }}
                  className="w-5 h-5 rounded accent-fuchsia-500"
                />
                <span className={`text-sm font-semibold ${antiDetectMaster ? "text-fuchsia-300" : "text-zinc-500"}`}>
                  {antiDetectMaster ? "ON" : "OFF"}
                </span>
              </label>
            </div>
            <p className="text-xs text-zinc-400 mt-2">
              {antiDetectMaster
                ? "✓ Full anti-detect stack active — your traffic is configured with all professional-grade evasion layers."
                : "Turn ON for professional-grade traffic. Recommended for all paid campaigns and CPL / SOI offers."}
            </p>
          </div>

          {/* ── 2026-07 v2.2.1 — In-App Browser Preset (one-click "Traffic Source") ── */}
          <div className="mt-6 p-4 rounded-lg border border-cyan-500/40 bg-gradient-to-br from-cyan-950/20 to-blue-950/10">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-cyan-300 text-sm font-semibold">📱 In-App Browser Preset</span>
                <span className="text-[10px] text-zinc-500 px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-800">
                  One-click · Reports as "Facebook In-App Browser" etc.
                </span>
              </div>
              {inappBrowserPreset && inappBrowserPreset !== "none" && (
                <span className="text-xs text-cyan-300 font-medium px-2 py-0.5 rounded-full bg-cyan-900/40 border border-cyan-700/50">
                  ACTIVE
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-400 mb-3">
              Select a social platform to make every visit look exactly like a real user opening the link inside that app's <span className="text-cyan-300">in-app browser</span>. Advertiser dashboards will report the browser as (e.g.) <span className="text-cyan-300 font-mono">Facebook In-App Browser</span> — just like real ad-click traffic.
            </p>
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="flex-1">
                <Label className="text-zinc-300 text-xs mb-1 block">Traffic Source Preset</Label>
                <select
                  data-testid="rut-inapp-browser-preset"
                  value={inappBrowserPreset}
                  onChange={(e) => setInappBrowserPreset(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-zinc-900 border border-zinc-700 text-zinc-100 text-sm focus:outline-none focus:border-cyan-500"
                >
                  <option value="none">— None (Advanced / Custom below) —</option>
                  <optgroup label="Social">
                    <option value="facebook">Facebook In-App Browser (FB4A / FBIOS)</option>
                    <option value="messenger">Messenger In-App Browser</option>
                    <option value="instagram">Instagram In-App Browser</option>
                    <option value="tiktok">TikTok In-App Browser (musical_ly)</option>
                    <option value="snapchat">Snapchat In-App Browser</option>
                    <option value="linkedin">LinkedIn In-App Browser</option>
                    <option value="twitter">Twitter / X In-App Browser</option>
                  </optgroup>
                  <optgroup label="Search / Video / Discovery (new in v2.2.5)">
                    <option value="youtube">YouTube In-App Browser (com.google.…youtube)</option>
                    <option value="google">Google Search In-App Browser (GSA)</option>
                    <option value="reddit">Reddit In-App Browser</option>
                    <option value="pinterest">Pinterest In-App Browser</option>
                  </optgroup>
                </select>
              </div>
            </div>
            {inappBrowserPreset && inappBrowserPreset !== "none" && (
              <div className="mt-3 p-3 rounded-md bg-cyan-950/40 border border-cyan-700/40 text-xs text-cyan-100 space-y-1">
                <div className="flex items-start gap-2">
                  <span className="text-cyan-400 leading-none">✓</span>
                  <span>
                    <span className="font-semibold text-cyan-300">Preset active</span> — engine will auto-configure this job:
                  </span>
                </div>
                <ul className="ml-6 list-disc space-y-0.5 text-zinc-300">
                  <li>UA rotation → realistic mobile UAs (Android + iOS mix)</li>
                  <li>In-app markers appended per visit (e.g. <span className="font-mono text-cyan-300">{inappBrowserPreset === "facebook" ? "[FB_IAB/FB4A;FBAV/…]" : inappBrowserPreset === "instagram" ? "Instagram 354.0.0.45.81 …" : inappBrowserPreset === "tiktok" ? "musical_ly_… BytedanceWebview/…" : inappBrowserPreset === "messenger" ? "[FB_IAB/MESSENGER;FBAV/…]" : inappBrowserPreset === "snapchat" ? "Snapchat/…" : inappBrowserPreset === "linkedin" ? "LinkedInApp/…" : "TwitterAndroid/…"}</span>) — tracker will report <span className="text-cyan-300 font-medium">Browser: {inappBrowserPreset === "tiktok" ? "TikTok for iOS/Android" : inappBrowserPreset === "facebook" ? "Facebook In-App" : inappBrowserPreset === "instagram" ? "Instagram In-App" : inappBrowserPreset === "messenger" ? "Messenger In-App" : inappBrowserPreset === "snapchat" ? "Snapchat In-App" : inappBrowserPreset === "linkedin" ? "LinkedIn In-App" : "Twitter In-App"}</span></li>
                  <li>
                    <span className="font-semibold text-emerald-300">Referer:</span>{" "}
                    <span className="text-zinc-300">
                      If you type a URL in <span className="text-emerald-300">&ldquo;Custom Referrer URL&rdquo;</span> below (e.g. your landing page{" "}
                      <span className="font-mono text-cyan-300">https://your-landing.com/</span>), <span className="text-emerald-300 font-medium">that</span> becomes the referer sent to the tracker/offer &mdash; exactly like a real{" "}
                      <span className="capitalize">{inappBrowserPreset}</span> ad click that lands on the advertiser page.
                      Leave the Custom URL empty to fall back to{" "}
                      <span className="font-mono text-cyan-300">https://www.{inappBrowserPreset === "twitter" ? "twitter" : inappBrowserPreset}.com/</span>{" "}
                      as the referer.
                    </span>
                  </li>
                  <li>Referer passed directly to the offer (bypasses Krexion origin leak)</li>
                </ul>
                <div className="pt-1 text-[11px] text-zinc-400">
                  💡 The preset applies the in-app <span className="text-zinc-300">browser identity</span>. The <span className="text-zinc-300">&ldquo;Referrer Source&rdquo;</span> panel below still controls the <span className="text-zinc-300">exact Referer URL</span> — perfect for real-ad-flow simulation (in-app browser + advertiser landing-page referer).
                </div>
              </div>
            )}
          </div>

          {/* ── 2026-06: Referrer Source (off-by-default, customer opt-in) ── */}
          <div className="mt-6 p-4 rounded-lg border border-emerald-500/30 bg-emerald-950/10">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-emerald-300 text-sm font-semibold">🌍 Referrer Source</span>
                <span className="text-[10px] text-zinc-500 px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-800">
                  Per-visit Referer header · 100% organic look
                </span>
              </div>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  data-testid="rut-referer-override-enabled"
                  type="checkbox"
                  checked={refererOverrideEnabled}
                  onChange={(e) => {
                    setRefererOverrideEnabled(e.target.checked);
                    // Turning the master switch off also parks the
                    // preset dropdown at "off" so the two controls
                    // never disagree.
                    if (!e.target.checked) setTrafficSourcePreset("off");
                  }}
                  className="w-4 h-4 rounded accent-emerald-500"
                />
                <span className={`text-xs font-medium ${refererOverrideEnabled ? "text-emerald-300" : "text-zinc-500"}`}>
                  {refererOverrideEnabled ? "ON" : "OFF (legacy UA-only)"}
                </span>
              </label>
            </div>
            <p className="text-xs text-zinc-400 mb-3">
              When <span className="text-zinc-300">OFF</span> the engine sets Referer only for in-app browser UAs (TikTok / FB / IG / …) — plain Chrome / Safari UAs hit your tracker with <span className="text-zinc-300">no Referer</span>, which gets logged as <span className="text-amber-400">Direct / Other</span>. Turn this <span className="text-emerald-300">ON</span> to force every visit through a chosen organic source so analytics show the real platform.
            </p>

            {/* ── 2026-07: SIMPLE MODE — Traffic Source Preset dropdown ── */}
            {refererOverrideEnabled && (
              <div className="mb-4 p-4 rounded-lg border-2 border-emerald-500/50 bg-gradient-to-br from-emerald-950/40 to-teal-950/30">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-emerald-200 text-sm font-bold">
                    🎯 Traffic Source (Simple Mode)
                  </span>
                  <span className="text-[10px] text-emerald-400 px-2 py-0.5 rounded-full bg-emerald-900/60 border border-emerald-600/60 font-medium">
                    ONE-CLICK SETUP
                  </span>
                </div>
                <p className="text-[12px] text-zinc-300 mb-3 leading-relaxed">
                  Pick <span className="text-emerald-300 font-medium">one</span> traffic source and Krexion auto-configures every advanced setting for you (weighted platforms, in-app markers, UA matching, network chains, offer-referrer pass-through). No conflicts, no confusion — just pick and go.
                </p>

                {/* ── 2026-07 v2.6.7: My Saved Presets ── */}
                {myTrafficPresets.length > 0 && (
                  <div className="mb-4 p-3 rounded-md bg-indigo-950/40 border border-indigo-700/40" data-testid="rut-my-presets-panel">
                    <div className="flex items-center justify-between mb-2">
                      <Label className="text-indigo-200 text-xs font-semibold uppercase tracking-wide flex items-center gap-2">
                        ⭐ My Saved Presets
                        <span className="text-[10px] font-normal text-indigo-400 px-2 py-0.5 rounded-full bg-indigo-900/60 border border-indigo-600/60">
                          {myTrafficPresets.length}
                        </span>
                      </Label>
                      <button
                        type="button"
                        data-testid="rut-my-presets-clear"
                        className="text-[10px] text-zinc-400 hover:text-zinc-200 underline"
                        onClick={() => {
                          setSelectedMyPresetId("");
                          setPresetSourceUrl("");
                          setPresetPlatformFilter(null);
                        }}
                        title="Deselect the saved preset (built-in preset stays)"
                      >
                        clear selection
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {myTrafficPresets.map((mp) => {
                        const active = selectedMyPresetId === mp.id;
                        return (
                          <div key={mp.id} className="flex items-center gap-1">
                            <button
                              type="button"
                              data-testid={`rut-my-preset-chip-${mp.id}`}
                              onClick={() => applyMyPreset(mp)}
                              className={`text-xs px-3 py-1.5 rounded-full border transition font-medium ${
                                active
                                  ? "bg-indigo-500 border-indigo-300 text-white"
                                  : "bg-zinc-900 border-indigo-700/60 text-indigo-200 hover:bg-indigo-900/60"
                              }`}
                              title={`Load: ${mp.name} (base: ${mp.base_preset})`}
                            >
                              {mp.name}
                            </button>
                            <button
                              type="button"
                              data-testid={`rut-my-preset-delete-${mp.id}`}
                              onClick={() => deleteMyPreset(mp)}
                              className="text-xs text-red-400 hover:text-red-300 px-1 leading-none"
                              title={`Delete "${mp.name}"`}
                            >
                              ✕
                            </button>
                          </div>
                        );
                      })}
                    </div>
                    <p className="text-[10px] text-indigo-400/70 mt-2 italic">
                      Click a chip to load your saved configuration. All 20+ toggles auto-fill from that preset.
                    </p>
                  </div>
                )}

                <Label className="text-emerald-200 text-xs font-semibold uppercase tracking-wide">
                  Choose Your Traffic Source
                </Label>
                <select
                  data-testid="rut-traffic-source-preset"
                  value={trafficSourcePreset}
                  onChange={(e) => setTrafficSourcePreset(e.target.value)}
                  className="mt-1 w-full bg-zinc-900 border-2 border-emerald-600/60 text-emerald-100 rounded-lg px-4 py-3 text-sm font-medium focus:outline-none focus:border-emerald-400 hover:border-emerald-500 transition"
                >
                  <option value="off">🚫 Off — legacy UA-only (no Referer override)</option>
                  <option value="mixed_realistic">⭐ Mixed Realistic (Recommended) — best all-round</option>
                  <option value="social_media_ads">📱 Social Media Ads — Facebook / Instagram / TikTok / Twitter</option>
                  <option value="search_engine_ads">🔍 Search Engine Ads — Google / Bing / DuckDuckGo / Yandex</option>
                  <option value="email_campaign">📧 Email Campaign — Gmail / Outlook / Mailchimp / Klaviyo</option>
                  <option value="direct_traffic">🎯 Direct Traffic — no Referer (bookmark / typed URL / native mail)</option>
                  <option value="custom">⚙️ Custom (Advanced) — show every toggle</option>
                </select>

                {/* Live preview of what preset just configured */}
                {trafficSourcePreset !== "custom" && trafficSourcePreset !== "off" && (
                  <div className="mt-3 p-3 rounded-md bg-zinc-950/60 border border-emerald-800/40">
                    <div className="text-[11px] text-emerald-300 font-semibold mb-2 flex items-center gap-1">
                      ✓ Auto-configured settings for this preset:
                    </div>
                    <ul className="text-[11px] text-zinc-300 space-y-1 leading-relaxed" data-testid="rut-preset-summary">
                      {trafficSourcePreset === "mixed_realistic" && (
                        <>
                          <li>• <span className="text-emerald-300">Traffic mix:</span> 30% Facebook · 20% TikTok · 20% Google · 15% Instagram · 10% Email · 5% Twitter</li>
                          <li>• <span className="text-emerald-300">Realism:</span> In-app deep paths + Social link wrappers + Network click chain — all ON</li>
                          <li>• <span className="text-emerald-300">Anti-fraud:</span> UA↔Platform matching + Pass-to-Offer — all ON</li>
                        </>
                      )}
                      {trafficSourcePreset === "social_media_ads" && (
                        <>
                          <li>• <span className="text-emerald-300">Traffic mix:</span> 40% Facebook · 30% Instagram · 25% TikTok · 5% Twitter</li>
                          <li>• <span className="text-emerald-300">Realism:</span> Deep post/reel/video paths + <span className="font-mono text-zinc-200">l.facebook.com</span> / <span className="font-mono text-zinc-200">t.co</span> wrappers + Ad-network click chain</li>
                          <li>• <span className="text-emerald-300">Mobile in-app markers:</span> FBAN/FBIOS · musical_ly · Instagram — auto-appended to UA per visit</li>
                        </>
                      )}
                      {trafficSourcePreset === "search_engine_ads" && (
                        <>
                          <li>• <span className="text-emerald-300">Search mix:</span> 65% Google · 25% Bing · 5% DuckDuckGo · 5% Yandex</li>
                          <li>• <span className="text-emerald-300">Realism:</span> Geo-localized TLDs (google.de, google.co.uk, …) matching your proxy country</li>
                          <li>• <span className="text-emerald-300">Referrer-Policy strip:</span> Only origin (matches modern search-engine referrer behaviour)</li>
                        </>
                      )}
                      {trafficSourcePreset === "email_campaign" && (
                        <>
                          <li>• <span className="text-emerald-300">ESP mix:</span> 40% Gmail · 20% Outlook · 15% Mailchimp · 10% Klaviyo · 10% Yahoo · 5% Native</li>
                          <li>• <span className="text-emerald-300">Auto-tagging:</span> <span className="font-mono text-zinc-200">mc_cid</span> · <span className="font-mono text-zinc-200">_kx</span> · <span className="font-mono text-zinc-200">_hsenc</span> — matched to the picked ESP per visit</li>
                          <li>• <span className="text-emerald-300">UTMs:</span> <span className="font-mono text-zinc-200">utm_medium=email</span> auto-added</li>
                        </>
                      )}
                      {trafficSourcePreset === "direct_traffic" && (
                        <>
                          <li>• <span className="text-emerald-300">Referer:</span> None (offer sees blank Referer, tracker logs as <span className="text-zinc-400">Direct</span>)</li>
                          <li>• <span className="text-emerald-300">Use case:</span> Bookmark clicks / typed URLs / native iOS Mail links / SMS clicks</li>
                        </>
                      )}
                    </ul>
                    <p className="text-[10px] text-emerald-400/70 mt-2 italic">
                      Want to fine-tune anything? Pick <span className="font-semibold">Custom (Advanced)</span> to see all 20+ toggles — or use the <span className="font-semibold text-cyan-300">Customize</span> panel below to tweak this preset and save it as your own.
                    </p>
                  </div>
                )}

                {/* ── 2026-07 v2.6.7: Inline Customize + Save this preset ── */}
                {trafficSourcePreset !== "off" && trafficSourcePreset !== "custom" && (
                  <div className="mt-3 p-3 rounded-md bg-cyan-950/40 border border-cyan-700/50" data-testid="rut-preset-customize-panel">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <span className="text-cyan-200 text-xs font-bold uppercase tracking-wide">
                          🎛️ Customize This Preset
                        </span>
                        <span className="text-[10px] text-cyan-400/80">
                          Pick ANY platforms + source URL(s) — save the setup as your own preset for one-click reuse next time.
                        </span>
                      </div>
                    </div>

                    {/* Platform chips: ALL 18 platforms shown; toggling adds/removes from mix */}
                    {(() => {
                      const ALL_PLATFORMS = (refererProDefaults?.platforms && refererProDefaults.platforms.length > 0)
                        ? refererProDefaults.platforms
                        : [
                            "facebook", "instagram", "tiktok", "youtube", "twitter",
                            "snapchat", "pinterest", "reddit", "linkedin",
                            "google", "bing", "duckduckgo", "yahoo", "yandex",
                            "email", "whatsapp", "telegram", "discord",
                          ];
                      const LABELS = {
                        facebook: "Facebook", instagram: "Instagram", tiktok: "TikTok",
                        youtube: "YouTube", twitter: "Twitter/X", snapchat: "Snapchat",
                        pinterest: "Pinterest", reddit: "Reddit", linkedin: "LinkedIn",
                        google: "Google", bing: "Bing", duckduckgo: "DuckDuckGo",
                        yahoo: "Yahoo", yandex: "Yandex", email: "Email",
                        whatsapp: "WhatsApp", telegram: "Telegram", discord: "Discord",
                      };
                      const activePlats = ALL_PLATFORMS.filter(
                        (p) => (refererPlatformWeights[p] || 0) > 0
                      );
                      const inactivePlats = ALL_PLATFORMS.filter(
                        (p) => !((refererPlatformWeights[p] || 0) > 0)
                      );

                      const togglePlatform = (plat, on) => {
                        setRefererPlatformWeights((prev) => {
                          const next = { ...prev };
                          if (!on) {
                            delete next[plat];
                          } else {
                            next[plat] = 20;  // sensible default weight
                          }
                          return next;
                        });
                      };

                      return (
                        <>
                          <div className="mb-3">
                            <Label className="text-cyan-300 text-[11px] font-semibold uppercase tracking-wide mb-1 block">
                              Active Platforms &amp; Weights ({activePlats.length})
                            </Label>
                            {activePlats.length === 0 ? (
                              <p className="text-[11px] text-amber-300/80 italic">
                                No platforms selected — pick at least one from the "Add another platform" list below.
                              </p>
                            ) : (
                              <div className="flex flex-wrap gap-2">
                                {activePlats.map((plat) => {
                                  const weight = refererPlatformWeights[plat] || 0;
                                  return (
                                    <div
                                      key={plat}
                                      className="flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs bg-cyan-900/60 border-cyan-500/60 text-cyan-100"
                                      data-testid={`rut-preset-plat-chip-${plat}`}
                                    >
                                      <label className="flex items-center gap-2 cursor-pointer select-none">
                                        <input
                                          type="checkbox"
                                          checked
                                          data-testid={`rut-preset-plat-toggle-${plat}`}
                                          onChange={() => togglePlatform(plat, false)}
                                          className="w-3.5 h-3.5 rounded accent-cyan-400"
                                          title={`Remove ${LABELS[plat] || plat} from the mix`}
                                        />
                                        <span className="font-medium">{LABELS[plat] || plat}</span>
                                      </label>
                                      <input
                                        type="number"
                                        min={0}
                                        max={100}
                                        step={1}
                                        value={weight}
                                        data-testid={`rut-preset-plat-weight-${plat}`}
                                        onChange={(e) => {
                                          const v = Math.max(0, Math.min(100, parseInt(e.target.value || "0", 10) || 0));
                                          setRefererPlatformWeights((prev) => {
                                            const next = { ...prev };
                                            if (v <= 0) delete next[plat];
                                            else next[plat] = v;
                                            return next;
                                          });
                                        }}
                                        className="w-12 bg-zinc-950 border border-cyan-700/50 rounded px-1.5 py-0.5 text-[11px] text-cyan-100 text-center"
                                      />
                                      <span className="text-[10px] text-cyan-400/80">%</span>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                            <p className="text-[10px] text-cyan-400/60 mt-1.5">
                              Weights are relative — they don't have to sum to 100. Uncheck to remove.
                            </p>
                          </div>

                          {inactivePlats.length > 0 && (
                            <div className="mb-3">
                              <Label className="text-emerald-300 text-[11px] font-semibold uppercase tracking-wide mb-1 block">
                                ➕ Add Another Platform ({inactivePlats.length} available)
                              </Label>
                              <div className="flex flex-wrap gap-2" data-testid="rut-preset-add-platform-strip">
                                {inactivePlats.map((plat) => (
                                  <button
                                    key={plat}
                                    type="button"
                                    data-testid={`rut-preset-plat-add-${plat}`}
                                    onClick={() => togglePlatform(plat, true)}
                                    className="text-xs px-3 py-1.5 rounded-full border border-zinc-700 bg-zinc-900/60 text-zinc-400 hover:bg-emerald-900/40 hover:border-emerald-600/60 hover:text-emerald-200 transition"
                                    title={`Add ${LABELS[plat] || plat} to the mix (default weight 20%)`}
                                  >
                                    + {LABELS[plat] || plat}
                                  </button>
                                ))}
                              </div>
                              <p className="text-[10px] text-emerald-400/60 mt-1.5">
                                Click any platform to add it. New platform starts at 20% weight — adjust after.
                              </p>
                            </div>
                          )}
                        </>
                      );
                    })()}

                    {/* Source URL(s) — supports multi-line for random rotation */}
                    <div className="mb-3">
                      <Label htmlFor="rut-preset-source-url" className="text-cyan-300 text-[11px] font-semibold uppercase tracking-wide mb-1 block">
                        Source URL(s) — Optional
                      </Label>
                      <textarea
                        id="rut-preset-source-url"
                        data-testid="rut-preset-source-url"
                        placeholder={"https://mysite.com/promo\nhttps://tiktok.com/@me/video/12345   (one URL per line — one is picked at random per visit)"}
                        value={presetSourceUrl}
                        onChange={(e) => setPresetSourceUrl(e.target.value)}
                        rows={3}
                        className="w-full bg-zinc-950 border border-cyan-700/50 rounded px-3 py-2 text-xs text-cyan-100 placeholder-zinc-600 focus:outline-none focus:border-cyan-400 font-mono resize-y"
                      />
                      <p className="text-[10px] text-cyan-400/60 mt-1">
                        Leave blank → preset picks a realistic source per platform. Paste one or more URLs (one per line) → Krexion rotates them as the Referer.
                      </p>
                    </div>

                    {/* Advanced Options accordion */}
                    <div className="mb-3 border-t border-cyan-800/40 pt-3">
                      <button
                        type="button"
                        data-testid="rut-preset-advanced-toggle"
                        onClick={() => setPresetAdvancedOpen((v) => !v)}
                        className="text-xs text-cyan-300 hover:text-cyan-200 font-semibold flex items-center gap-2 mb-2"
                      >
                        <span>{presetAdvancedOpen ? "▼" : "▶"}</span>
                        ⚙️ Advanced Options
                        <span className="text-[10px] font-normal text-cyan-400/70">
                          (search keywords, brand tag, country, realism toggles)
                        </span>
                      </button>

                      {presetAdvancedOpen && (
                        <div className="pl-4 border-l-2 border-cyan-800/50 space-y-3">
                          {/* Search Engine + Keywords — only relevant when a search platform is in the mix */}
                          {(() => {
                            const searchPlatformsInMix = ["google", "bing", "yahoo", "duckduckgo", "yandex"]
                              .filter((p) => (refererPlatformWeights[p] || 0) > 0);
                            if (searchPlatformsInMix.length === 0) return null;
                            return (
                              <div>
                                <Label className="text-cyan-300 text-[11px] font-semibold uppercase tracking-wide mb-1 block">
                                  Search Engine &amp; Keywords
                                </Label>
                                <div className="grid md:grid-cols-2 gap-2">
                                  <select
                                    data-testid="rut-preset-search-engine"
                                    value={refererSearchEngine}
                                    onChange={(e) => setRefererSearchEngine(e.target.value)}
                                    className="bg-zinc-950 border border-cyan-700/50 rounded px-2 py-1.5 text-xs text-cyan-100"
                                  >
                                    <option value="google">Google</option>
                                    <option value="bing">Bing</option>
                                    <option value="yahoo">Yahoo</option>
                                    <option value="duckduckgo">DuckDuckGo</option>
                                    <option value="yandex">Yandex</option>
                                    <option value="youtube">YouTube Search</option>
                                    <option value="baidu">Baidu (China)</option>
                                    <option value="naver">Naver (Korea)</option>
                                  </select>
                                  <textarea
                                    data-testid="rut-preset-search-keywords"
                                    placeholder={"free trial\nbest running shoes\nhow to lose weight   (one keyword per line)"}
                                    value={refererSearchKeywords}
                                    onChange={(e) => setRefererSearchKeywords(e.target.value)}
                                    rows={2}
                                    className="bg-zinc-950 border border-cyan-700/50 rounded px-2 py-1.5 text-xs text-cyan-100 placeholder-zinc-600 font-mono resize-y"
                                  />
                                </div>
                                <p className="text-[10px] text-cyan-400/60 mt-1">
                                  Active search platforms in mix: {searchPlatformsInMix.join(", ")}. Empty keywords → origin-only URL (e.g. https://google.com/).
                                </p>
                              </div>
                            );
                          })()}

                          {/* Brand tag */}
                          <div>
                            <Label htmlFor="rut-preset-brand" className="text-cyan-300 text-[11px] font-semibold uppercase tracking-wide mb-1 block">
                              Brand Tag — Optional
                            </Label>
                            <input
                              id="rut-preset-brand"
                              data-testid="rut-preset-brand"
                              type="text"
                              maxLength={40}
                              placeholder="e.g. mybrand   (used in utm_source=mybrand_newsletter + utm_campaign=mybrand_...)"
                              value={refererBrand}
                              onChange={(e) => setRefererBrand(e.target.value)}
                              className="w-full bg-zinc-950 border border-cyan-700/50 rounded px-3 py-1.5 text-xs text-cyan-100 placeholder-zinc-600"
                            />
                          </div>

                          {/* Realism toggles */}
                          <div>
                            <Label className="text-cyan-300 text-[11px] font-semibold uppercase tracking-wide mb-1 block">
                              Realism Layers (advanced)
                            </Label>
                            <div className="grid md:grid-cols-2 gap-2">
                              {[
                                { key: "socialWrapper", state: refererSocialWrapper, set: setRefererSocialWrapper,
                                  label: "Social link wrappers", hint: "l.facebook.com, t.co, lnkd.in, out.reddit.com" },
                                { key: "inappDeep", state: refererInappDeep, set: setRefererInappDeep,
                                  label: "In-app deep paths", hint: "TikTok video URLs, IG /p/ post URLs, FB pfbid posts" },
                                { key: "networkClickChain", state: refererNetworkClickChain, set: setRefererNetworkClickChain,
                                  label: "Ad-network click chain", hint: "Referer becomes affiliate-network host (sig.click.com, trklink)" },
                                { key: "passToOffer", state: refererPassToOffer, set: setRefererPassToOffer,
                                  label: "Pass Referer to offer", hint: "Bypass Krexion origin leak — offer sees exact Referer" },
                                { key: "matchUaToPlatform", state: refererMatchUaToPlatform, set: setRefererMatchUaToPlatform,
                                  label: "Match UA to platform", hint: "Add FBAN/musical_ly/Instagram in-app markers to UA per visit" },
                                { key: "stripSearchPath", state: refererStripSearchPath, set: setRefererStripSearchPath,
                                  label: "Strip search /?q= path", hint: "Match modern strict-origin referrer-policy" },
                              ].map((t) => (
                                <label
                                  key={t.key}
                                  className="flex items-start gap-2 cursor-pointer text-[11px] text-zinc-200 hover:text-cyan-100"
                                >
                                  <input
                                    type="checkbox"
                                    data-testid={`rut-preset-realism-${t.key}`}
                                    checked={t.state}
                                    onChange={(e) => t.set(e.target.checked)}
                                    className="mt-0.5 w-3.5 h-3.5 rounded accent-cyan-400"
                                  />
                                  <span className="flex flex-col leading-tight">
                                    <span className="font-medium">{t.label}</span>
                                    <span className="text-[10px] text-cyan-400/60">{t.hint}</span>
                                  </span>
                                </label>
                              ))}
                            </div>
                          </div>

                          <p className="text-[10px] text-cyan-400/70 italic">
                            All these fields also travel with the preset — click Save below to persist your exact recipe.
                          </p>
                        </div>
                      )}
                    </div>

                    {/* Save-as-preset action */}
                    <div className="pt-2 border-t border-cyan-800/40">
                      {!presetSaveOpen ? (
                        <button
                          type="button"
                          data-testid="rut-preset-save-open"
                          onClick={() => {
                            setPresetSaveError("");
                            setPresetSaveName("");
                            setPresetSaveOpen(true);
                          }}
                          className="text-xs bg-cyan-500 hover:bg-cyan-400 text-white font-semibold px-4 py-2 rounded transition"
                        >
                          💾 Save this configuration as my preset
                        </button>
                      ) : (
                        <div className="flex flex-col gap-2" data-testid="rut-preset-save-dialog">
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              data-testid="rut-preset-save-name"
                              placeholder="Preset name (e.g. 'TikTok-only US promo')"
                              value={presetSaveName}
                              onChange={(e) => setPresetSaveName(e.target.value)}
                              maxLength={80}
                              className="flex-1 bg-zinc-950 border border-cyan-500 rounded px-3 py-2 text-xs text-cyan-100 placeholder-zinc-600 focus:outline-none focus:border-cyan-300"
                            />
                            <button
                              type="button"
                              data-testid="rut-preset-save-confirm"
                              disabled={presetSaving || !presetSaveName.trim()}
                              onClick={saveMyPreset}
                              className="text-xs bg-emerald-500 hover:bg-emerald-400 text-white font-semibold px-4 py-2 rounded transition disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {presetSaving ? "Saving…" : "Save"}
                            </button>
                            <button
                              type="button"
                              data-testid="rut-preset-save-cancel"
                              onClick={() => {
                                setPresetSaveOpen(false);
                                setPresetSaveError("");
                              }}
                              className="text-xs text-zinc-400 hover:text-zinc-200 px-2"
                            >
                              cancel
                            </button>
                          </div>
                          {presetSaveError && (
                            <p className="text-[11px] text-red-400" data-testid="rut-preset-save-error">
                              ⚠️ {presetSaveError}
                            </p>
                          )}
                          <p className="text-[10px] text-cyan-400/70">
                            Saves ALL current settings (base preset "{trafficSourcePreset}", every active platform + weight, source URLs, search keywords, brand, realism toggles). One-click reload next time.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {trafficSourcePreset === "custom" && (
                  <div className="mt-3 p-2 rounded-md bg-amber-950/40 border border-amber-700/40 text-[11px] text-amber-200">
                    ⚙️ <span className="font-semibold">Advanced mode active.</span> Every toggle below is under your control — Krexion will NOT auto-configure anything.
                  </div>
                )}
              </div>
            )}

            {refererOverrideEnabled && trafficSourcePreset === "custom" && (
              <div className="mb-3 p-3 rounded-md bg-emerald-950/30 border border-emerald-700/40">
                <div className="flex items-start gap-2 text-xs text-emerald-200">
                  <span className="text-emerald-400 text-base leading-none">⚡</span>
                  <span>
                    <span className="font-semibold text-emerald-300">Auto-sync URL params (signed handshake)</span> — when this is ON, every visit's Referer AND URL params come from the SAME platform automatically. A TikTok-Referer visit gets fresh <span className="font-mono text-emerald-200">ttclid</span>, a Facebook one gets <span className="font-mono text-emerald-200">fbclid + fbc</span>, a Google one gets <span className="font-mono text-emerald-200">gclid + gad_source</span>, Bing → <span className="font-mono text-emerald-200">msclkid</span>, Pinterest → <span className="font-mono text-emerald-200">epik</span>, <span className="font-mono text-emerald-200">email</span> → rotating ESP params (<span className="font-mono">mc_cid</span> / <span className="font-mono">_kx</span> / <span className="font-mono">_hsenc</span>) + <span className="font-mono">utm_medium=email</span>, etc. Modern 2026 ID formats. No link-level config needed. Eliminates the Referer ↔ URL-params mismatch tell that anti-fraud trackers (Voluum / RedTrack / Binom / AppsFlyer) flag.
                  </span>
                </div>
              </div>
            )}

            {/* 2026-01 — Pass-Referer-To-Offer (universal toggle, works in every referer mode) */}
            {refererOverrideEnabled && trafficSourcePreset === "custom" && (
              <label
                className="flex items-start gap-3 text-xs text-zinc-200 cursor-pointer p-3 mb-3 rounded-md border-2 border-emerald-500/60 bg-emerald-950/40 hover:bg-emerald-950/60 transition"
                data-testid="rut-pass-referer-to-offer-label"
              >
                <input
                  data-testid="rut-pass-referer-to-offer"
                  type="checkbox"
                  checked={refererPassToOffer}
                  onChange={(e) => setRefererPassToOffer(e.target.checked)}
                  className="w-5 h-5 rounded accent-emerald-500 mt-0.5"
                />
                <span className="flex flex-col gap-1 flex-1">
                  <span className="font-semibold text-emerald-300 text-sm flex items-center gap-2">
                    🎯 Pass Referer to Offer (direct offer navigation)
                    <span className="text-[10px] font-normal text-emerald-400 px-2 py-0.5 rounded bg-emerald-900/50 border border-emerald-600/50">
                      RECOMMENDED
                    </span>
                  </span>
                  <span className="text-zinc-300 text-[12px] leading-relaxed">
                    Without this, the bot navigates <span className="text-zinc-400">tracker → 302 → offer</span> and the browser's referrer policy STRIPS your chosen Referer down to the Krexion origin — so the offer sees <span className="text-amber-400">https://krexion.com</span> (or empty) instead of TikTok / your custom URL.
                  </span>
                  <span className="text-emerald-200 text-[12px] leading-relaxed">
                    Turn ON → Krexion resolves the tracker <span className="text-emerald-300">server-side</span> (click is still recorded with the proxy exit IP via <code className="text-emerald-200">X-Forwarded-For</code>) and Chromium navigates <span className="text-emerald-300">directly to the offer URL</span> with the EXACT Referer you picked (TikTok / custom URL / platform pool / Google search / Facebook wrapper / etc.).
                  </span>
                  <span className="text-zinc-400 text-[11px] leading-relaxed italic">
                    Safe fallback: if the server-side resolve fails for any reason, the visit silently falls back to the legacy tracker path so it still completes.
                  </span>
                </span>
              </label>
            )}

            {refererOverrideEnabled && trafficSourcePreset === "custom" && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <Label className="text-zinc-300 text-sm">Referrer Mode</Label>
                  <select
                    data-testid="rut-referer-mode"
                    value={refererMode}
                    onChange={(e) => setRefererMode(e.target.value)}
                    className="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-3 py-2 text-sm"
                  >
                    <option value="auto">Auto from UA (smart in-app detection)</option>
                    <option value="platform_pool">Random Platform Pool</option>
                    <option value="custom">Custom URL (same for every visit)</option>
                    <option value="random_list">Random from URL List</option>
                    <option value="google_search">Google Search (organic SEO look)</option>
                    <option value="direct">Direct / None (no Referer)</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    Mode controls how each visit's Referer header is picked.
                  </p>

                  {/* 2026-06-11: PRO-MODE master toggle */}
                  <div className="mt-4 p-3 rounded-md bg-gradient-to-r from-fuchsia-900/30 to-amber-900/20 border border-fuchsia-700/40">
                    <label className="flex items-center justify-between gap-2 cursor-pointer select-none">
                      <span className="flex items-center gap-2">
                        <span className="text-fuchsia-300 text-sm font-semibold">⚡ Pro Mode</span>
                        <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-700">
                          Weighted + 12 realism layers
                        </span>
                      </span>
                      <input
                        data-testid="rut-referer-pro-mode"
                        type="checkbox"
                        checked={refererProMode}
                        onChange={(e) => setRefererProMode(e.target.checked)}
                        className="w-4 h-4 rounded accent-fuchsia-500"
                      />
                    </label>
                    <p className="text-[11px] text-zinc-400 mt-1">
                      Multi-select platforms with <span className="text-fuchsia-300">% sliders</span>, weighted ESP/webmail mix, geo-localized Google/Bing/Yandex, social link wrappers (<span className="font-mono text-zinc-300">l.facebook.com</span>/<span className="font-mono text-zinc-300">t.co</span>/<span className="font-mono text-zinc-300">lnkd.in</span>), Sec-Fetch-* header sync, mobile in-app deep paths.
                    </p>
                  </div>
                </div>

                {refererMode === "platform_pool" && !refererProMode && (
                  <div className="md:col-span-2">
                    <Label className="text-zinc-300 text-sm">Platform Pool (comma-separated)</Label>
                    <Input
                      data-testid="rut-referer-platform-pool"
                      type="text"
                      value={refererPlatformPool}
                      onChange={(e) => setRefererPlatformPool(e.target.value.slice(0, 512))}
                      placeholder="facebook,tiktok,instagram,google,email,youtube,twitter,snapchat,pinterest,reddit,linkedin,bing"
                      className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      One platform is picked per visit at random. Available: facebook, messenger, instagram, tiktok, youtube, twitter, snapchat, pinterest, reddit, linkedin, whatsapp, telegram, discord, google, bing, duckduckgo, yahoo, yandex, baidu, naver, ecosia, brave, <span className="text-emerald-300 font-medium">email</span>.
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      Want full % control + ESP mix? Turn on <span className="text-fuchsia-300 font-medium">Pro Mode</span> for the multi-select UI.
                    </p>

                    {/* Brand identifier — shown only when email is in the pool */}
                    {refererPlatformPool.toLowerCase().includes("email") && (
                      <div className="mt-3 p-3 rounded-md bg-zinc-900/60 border border-zinc-700/60">
                        <Label className="text-zinc-300 text-sm flex items-center gap-2">
                          <span>Brand Identifier <span className="text-zinc-500 text-xs font-normal">(optional, email visits only)</span></span>
                        </Label>
                        <Input
                          data-testid="rut-referer-brand"
                          type="text"
                          value={refererBrand}
                          onChange={(e) => setRefererBrand(e.target.value.slice(0, 64))}
                          placeholder="acme   ·   brandname   ·   your-shop"
                          className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          When set, email visits get brand-tagged UTMs: <span className="font-mono text-emerald-300">utm_source=&lt;brand&gt;_newsletter</span>.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {/* 2026-06-11: PRO-MODE multi-select + sliders */}
                {refererProMode && (
                  <div className="md:col-span-2 space-y-4">
                    <ReferrerProMultiSelect
                      title="Platform Mix"
                      description="Tick platforms aap chahte ho, % slider se traffic share define karo. Total auto-normalize."
                      keys={(refererProDefaults.platforms && refererProDefaults.platforms.length > 0)
                        ? refererProDefaults.platforms
                        : ["facebook","instagram","tiktok","youtube","twitter","snapchat","pinterest","reddit","linkedin","google","bing","duckduckgo","yahoo","yandex","email","whatsapp","telegram","discord"]}
                      weights={refererPlatformWeights}
                      onChange={setRefererPlatformWeights}
                      accent="fuchsia"
                      testIdPrefix="rut-pro-platform"
                    />

                    {/* Email bucket weights — only when "email" is in the platform mix */}
                    {Object.keys(refererPlatformWeights).includes("email") && refererPlatformWeights.email > 0 && (
                      <ReferrerProMultiSelect
                        title="Email Source Mix (ESP + Webmail)"
                        description="Jab platform pool email pick kare, ye sub-mix decide karta hai Referer empty rahe / Gmail / Outlook / kaunsa ESP click-tracker."
                        keys={(refererProDefaults.email_buckets && refererProDefaults.email_buckets.length > 0)
                          ? refererProDefaults.email_buckets
                          : ["empty","gmail","outlook","yahoo","proton","mailchimp","klaviyo","sendgrid","hubspot","activecampaign","convertkit","constantcontact","mailerlite","brevo","aweber","drip","iterable","marketo","pardot"]}
                        weights={refererEmailWeights}
                        onChange={setRefererEmailWeights}
                        accent="emerald"
                        testIdPrefix="rut-pro-email"
                      />
                    )}

                    {/* Search-engine sub-options */}
                    {(Object.keys(refererPlatformWeights).some((k) =>
                      ["google", "bing", "yahoo", "duckduckgo", "yandex"].includes(k)
                    )) && (
                      <div className="p-3 rounded-md bg-cyan-950/20 border border-cyan-700/40">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-cyan-300 text-sm font-semibold">🔎 Search Engine Settings</span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div>
                            <Label className="text-zinc-300 text-xs">Strip URL path (Real Chrome Referrer-Policy)</Label>
                            <label className="flex items-center gap-2 mt-1 cursor-pointer">
                              <input
                                data-testid="rut-pro-strip-search-path"
                                type="checkbox"
                                checked={refererStripSearchPath}
                                onChange={(e) => setRefererStripSearchPath(e.target.checked)}
                                className="w-4 h-4 rounded accent-cyan-500"
                              />
                              <span className="text-xs text-zinc-400">Recommended ON — modern Chrome strips path on cross-site nav.</span>
                            </label>
                          </div>
                          <div>
                            <Label className="text-zinc-300 text-xs">Keyword Pool (per visit random)</Label>
                            <textarea
                              data-testid="rut-pro-search-keywords"
                              value={refererSearchKeywords}
                              onChange={(e) => setRefererSearchKeywords(e.target.value.slice(0, 8000))}
                              rows={3}
                              placeholder={"best dating app 2026\nflexfit review\nfree dating sites"}
                              className="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-3 py-2 text-xs font-mono"
                            />
                            <p className="text-[11px] text-gray-500 mt-1">
                              Per visit, the engine picks one keyword and builds the SERP URL (geo-localized to proxy country: <span className="font-mono">google.de</span>, <span className="font-mono">.fr</span>, <span className="font-mono">.co.uk</span>, etc.).
                            </p>
                          </div>
                        </div>

                        {/* AI keyword generator */}
                        <div className="mt-3 p-3 rounded-md bg-zinc-950/60 border border-zinc-800">
                          <div className="text-xs text-amber-300 font-semibold mb-2">✨ AI Keyword Generator (Claude Sonnet 4.6)</div>
                          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                            <input
                              data-testid="rut-pro-aikw-offer"
                              type="text"
                              value={aiKwOffer}
                              onChange={(e) => setAiKwOffer(e.target.value.slice(0, 200))}
                              placeholder="Offer name (e.g. FlexFit Dating)"
                              className="bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1 text-xs"
                            />
                            <input
                              data-testid="rut-pro-aikw-vertical"
                              type="text"
                              value={aiKwVertical}
                              onChange={(e) => setAiKwVertical(e.target.value.slice(0, 120))}
                              placeholder="Vertical (dating, finance, …)"
                              className="bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1 text-xs"
                            />
                            <select
                              data-testid="rut-pro-aikw-country"
                              value={aiKwCountry}
                              onChange={(e) => setAiKwCountry(e.target.value)}
                              className="bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1 text-xs"
                            >
                              {(refererProDefaults.countries || ["US"]).map((cc) => (
                                <option key={cc} value={cc.toLowerCase()}>{cc}</option>
                              ))}
                            </select>
                            <select
                              data-testid="rut-pro-aikw-intent"
                              value={aiKwIntent}
                              onChange={(e) => setAiKwIntent(e.target.value)}
                              className="bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1 text-xs"
                            >
                              {(refererProDefaults.intent_mixes || ["balanced", "informational", "commercial", "branded"]).map((m) => (
                                <option key={m} value={m}>{m}</option>
                              ))}
                            </select>
                          </div>
                          <div className="flex items-center gap-2 mt-2">
                            <label className="text-[11px] text-zinc-400">Count:</label>
                            <input
                              data-testid="rut-pro-aikw-count"
                              type="number"
                              min={5}
                              max={40}
                              value={aiKwCount}
                              onChange={(e) => setAiKwCount(Math.max(5, Math.min(40, parseInt(e.target.value) || 15)))}
                              className="w-16 bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1 text-xs"
                            />
                            <button
                              data-testid="rut-pro-aikw-generate"
                              type="button"
                              disabled={aiKwLoading || !aiKwOffer.trim()}
                              onClick={async () => {
                                setAiKwError("");
                                setAiKwLoading(true);
                                try {
                                  const token = localStorage.getItem("token");
                                  const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/generate-keywords`, {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                                    body: JSON.stringify({
                                      offer_name: aiKwOffer.trim(),
                                      vertical: aiKwVertical.trim(),
                                      country: aiKwCountry,
                                      language: "en",
                                      count: aiKwCount,
                                      intent_mix: aiKwIntent,
                                    }),
                                  });
                                  if (!r.ok) {
                                    const t = await r.text();
                                    throw new Error(t || `HTTP ${r.status}`);
                                  }
                                  const data = await r.json();
                                  const newKws = (data.keywords || []).join("\n");
                                  setRefererSearchKeywords((prev) => prev ? `${prev}\n${newKws}` : newKws);
                                } catch (err) {
                                  setAiKwError(String(err.message || err));
                                } finally {
                                  setAiKwLoading(false);
                                }
                              }}
                              className="px-3 py-1 rounded-md text-xs font-medium bg-amber-600/80 hover:bg-amber-600 disabled:bg-zinc-700 disabled:cursor-not-allowed text-white"
                            >
                              {aiKwLoading ? "Generating…" : "Generate"}
                            </button>
                            {aiKwError && (
                              <span className="text-xs text-red-400 truncate" title={aiKwError}>{aiKwError.slice(0, 80)}</span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Realism toggles */}
                    <div className="p-3 rounded-md bg-zinc-900/60 border border-zinc-700/60">
                      <div className="text-xs text-fuchsia-300 font-semibold mb-2">🎚️ Realism Layers</div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                          <input
                            data-testid="rut-pro-social-wrapper"
                            type="checkbox"
                            checked={refererSocialWrapper}
                            onChange={(e) => setRefererSocialWrapper(e.target.checked)}
                            className="w-4 h-4 rounded accent-fuchsia-500"
                          />
                          <span>Social link wrappers <span className="text-zinc-500">(l.facebook.com / t.co / lnkd.in)</span></span>
                        </label>
                        <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                          <input
                            data-testid="rut-pro-inapp-deep"
                            type="checkbox"
                            checked={refererInappDeep}
                            onChange={(e) => setRefererInappDeep(e.target.checked)}
                            className="w-4 h-4 rounded accent-fuchsia-500"
                          />
                          <span>Mobile in-app deep paths <span className="text-zinc-500">(tiktok video/post URLs)</span></span>
                        </label>
                        <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                          <input
                            data-testid="rut-pro-match-ua-platform"
                            type="checkbox"
                            checked={refererMatchUaToPlatform}
                            onChange={(e) => setRefererMatchUaToPlatform(e.target.checked)}
                            className="w-4 h-4 rounded accent-emerald-500"
                          />
                          <span className="text-emerald-200">
                            🛡️ Match UA to Referer
                            <span className="text-zinc-500"> (auto-append FB_IAB / BytedanceWebview / Instagram markers so mobile traffic matches real in-app clicks — kills the #1 fraud signal)</span>
                          </span>
                        </label>
                        <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                          <input
                            data-testid="rut-pro-network-chain"
                            type="checkbox"
                            checked={refererNetworkClickChain}
                            onChange={(e) => setRefererNetworkClickChain(e.target.checked)}
                            className="w-4 h-4 rounded accent-fuchsia-500"
                          />
                          <span>Network click-redirect chain <span className="text-zinc-500">(one extra 302 hop)</span></span>
                        </label>
                        <div className="text-xs text-zinc-400 leading-relaxed">
                          <span className="text-fuchsia-300">Sec-Fetch-*</span> headers + UTM source/medium variation are <span className="text-emerald-300">always ON</span> in Pro Mode (no off-switch needed — they're 100% safe additive signals).
                        </div>
                      </div>
                    </div>

                    {/* v2.6.25 — Paid vs Organic Traffic Type + Campaign Type
                        (mirrors LinksPage — RUT jobs can now force the same
                        paid/organic referer pool that Create-Link uses).
                        This is the SINGLE place where RUT-driven traffic
                        chooses its realism mode — the operator does NOT
                        need to also configure Pro-Referrer on the target
                        Link (RUT overrides link config).                     */}
                    <div className="p-3 rounded-md bg-gradient-to-br from-purple-950/40 to-fuchsia-950/40 border border-fuchsia-500/40">
                      <div className="text-xs text-fuchsia-300 font-semibold mb-2 flex items-center gap-2">
                        <span>🚦 Traffic Type</span>
                        <span className="text-[10px] text-fuchsia-500/70 font-normal">(v2.6.25 — Paid vs Organic split)</span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                          <Label className="text-xs text-zinc-400">Traffic Type</Label>
                          <select
                            data-testid="rut-pro-traffic-type"
                            value={refererTrafficType}
                            onChange={(e) => setRefererTrafficType(e.target.value)}
                            className="w-full mt-1 p-2 rounded-md bg-zinc-900 border border-zinc-700 text-zinc-100 text-sm"
                          >
                            <option value="auto">Auto — detect from Campaign Type + platform</option>
                            <option value="paid">Paid Ads — force paid-ad referer pool</option>
                            <option value="organic">Organic — force organic-click referer pool</option>
                            <option value="mixed">Mixed — 60% paid / 40% organic blend</option>
                          </select>
                        </div>
                        <div>
                          <Label className="text-xs text-zinc-400">Campaign Type</Label>
                          <select
                            data-testid="rut-pro-campaign-type"
                            value={refererCampaignType}
                            onChange={(e) => setRefererCampaignType(e.target.value)}
                            className="w-full mt-1 p-2 rounded-md bg-zinc-900 border border-zinc-700 text-zinc-100 text-sm"
                          >
                            <option value="auto">Auto — random rotation (legacy)</option>
                            <option value="static_image">Static Image Ad</option>
                            <option value="video_ad">Video Ad</option>
                            <option value="carousel_ad">Carousel Ad</option>
                            <option value="story_ad">Story Ad</option>
                            <option value="lookalike_prospect">Lookalike Prospecting</option>
                            <option value="retargeting_warm">Retargeting (Warm)</option>
                            <option value="retargeting_cold">Retargeting (Cold)</option>
                            <option value="cold_email">Cold Email</option>
                            <option value="search_cpc">Search / CPC (Google Ads)</option>
                          </select>
                        </div>
                      </div>
                      <p className="text-[10px] text-zinc-500 mt-2 leading-relaxed">
                        Applies platform-specific real-capture referer patterns for all 10 platforms (TikTok, FB, IG, X, YouTube, LinkedIn, Snap, Pinterest, Reddit, Google, Bing, Messenger).
                        &nbsp;<span className="text-fuchsia-400">Auto</span> preserves legacy — pick <span className="text-emerald-400">Paid / Organic / Mixed</span> to force a specific mode for this RUT job.
                      </p>
                    </div>

                    {/* Brand identifier */}
                    {Object.keys(refererPlatformWeights).includes("email") && refererPlatformWeights.email > 0 && (
                      <div className="p-3 rounded-md bg-zinc-900/60 border border-zinc-700/60">
                        <Label className="text-zinc-300 text-sm flex items-center gap-2">
                          <span>Brand Identifier <span className="text-zinc-500 text-xs font-normal">(optional, email visits only)</span></span>
                        </Label>
                        <Input
                          data-testid="rut-referer-brand"
                          type="text"
                          value={refererBrand}
                          onChange={(e) => setRefererBrand(e.target.value.slice(0, 64))}
                          placeholder="acme   ·   brandname   ·   your-shop"
                          className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Sets <span className="font-mono text-emerald-300">utm_source=&lt;brand&gt;_newsletter</span> on email visits. Real address never exposed.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {refererMode === "custom" && (
                  <div className="md:col-span-2">
                    <Label className="text-zinc-300 text-sm">Custom Referrer URL</Label>
                    <Input
                      data-testid="rut-referer-custom-value"
                      type="text"
                      value={refererValue}
                      onChange={(e) => setRefererValue(e.target.value.slice(0, 1024))}
                      placeholder="https://www.facebook.com/groups/your-group-id/"
                      className="mt-1 bg-zinc-800 border-zinc-700 text-zinc-100"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      Exact URL used as the Referer header for EVERY visit. Use the full URL of the FB post / IG bio link / blog page that "sent" the visitor.
                    </p>
                  </div>
                )}

                {refererMode === "random_list" && (
                  <div className="md:col-span-2">
                    <Label className="text-zinc-300 text-sm">Referrer URL Pool (one per line)</Label>
                    <textarea
                      data-testid="rut-referer-url-list"
                      value={refererValue}
                      onChange={(e) => setRefererValue(e.target.value.slice(0, 8000))}
                      rows={5}
                      placeholder={"https://www.facebook.com/groups/123/\nhttps://www.instagram.com/p/abc/\nhttps://www.tiktok.com/@user/video/9999\nhttps://twitter.com/user/status/1234"}
                      className="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-3 py-2 text-sm font-mono"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      One URL per line — engine picks a different one per visit at random. Best for campaigns with 5–50 different ad creatives / post URLs.
                    </p>
                  </div>
                )}

                {refererMode === "google_search" && (
                  <div className="md:col-span-2">
                    <Label className="text-zinc-300 text-sm">Search Keywords (one per line)</Label>
                    <textarea
                      data-testid="rut-referer-google-keywords"
                      value={refererValue}
                      onChange={(e) => setRefererValue(e.target.value.slice(0, 8000))}
                      rows={5}
                      placeholder={"best vpn 2026\nfree trial software\ncar insurance quotes\ncrypto trading signals"}
                      className="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-3 py-2 text-sm font-mono"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      Each visit gets a Referer like <span className="text-emerald-300">https://www.google.com/search?q=&lt;your-keyword&gt;</span> — looks like organic Google search traffic. Empty list = plain <span className="text-zinc-300">google.com</span>.
                    </p>
                  </div>
                )}

                {(refererMode === "auto" || refererMode === "direct") && (
                  <div className="md:col-span-2 flex items-start gap-2 text-xs text-zinc-400 mt-2">
                    <span className="text-emerald-300 text-base leading-none">ℹ</span>
                    <span>
                      {refererMode === "auto"
                        ? "Smart mode — Referer is auto-derived from each visit's User-Agent. TikTok/FB/IG in-app UAs get their platform URL, plain browsers get no Referer."
                        : "No Referer header will be sent on any visit. Useful when simulating bookmark / direct-typed-URL / email-link traffic."}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── 2026-02 v2.1.31 — Anti-Detect (Phase 3) ──
              2026-06-11: HIDDEN from UI — controlled by unified Anti-Detect
              toggle above. State retained so backend still receives values. */}
          <div className="hidden">
          <div className="mt-6 p-4 rounded-lg border border-sky-500/30 bg-sky-950/10">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-sky-300 text-sm font-semibold">🌐 Anti-Detect (Phase 3)</span>
              <span className="text-[10px] text-zinc-500 px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-800">Multi-Hop Proxy · Browser Rotation</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label className="text-zinc-300 text-sm">Multi-Hop Proxy Chain</Label>
                <div className="mt-2 flex items-center gap-2">
                  <input
                    data-testid="rut-proxy-chain-enabled"
                    type="checkbox"
                    checked={proxyChainEnabled}
                    onChange={(e) => setProxyChainEnabled(e.target.checked)}
                    className="w-4 h-4 rounded accent-sky-500"
                  />
                  <span className="text-sm text-zinc-300">Enable chain (Tor → exit proxy)</span>
                </div>
                {proxyChainEnabled && (
                  <div className="mt-2 ml-6 flex items-center gap-2">
                    <input
                      data-testid="rut-proxy-chain-use-tor"
                      type="checkbox"
                      checked={proxyChainUseTor}
                      onChange={(e) => setProxyChainUseTor(e.target.checked)}
                      className="w-3.5 h-3.5 rounded accent-sky-500"
                    />
                    <span className="text-xs text-zinc-400">First hop: local Tor SOCKS5 (127.0.0.1:9050)</span>
                    {adCapabilities && (
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                          adCapabilities.tor_available
                            ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                            : "bg-amber-500/15 text-amber-300 border-amber-500/30"
                        }`}
                        data-testid="rut-tor-status-badge"
                      >
                        {adCapabilities.tor_available ? "Tor LIVE" : "Tor down → single-hop"}
                      </span>
                    )}
                  </div>
                )}
                {proxyChainEnabled && (
                  <div className="mt-2 ml-6">
                    <Label className="text-zinc-400 text-xs">Extra Hops (one per line, optional)</Label>
                    <textarea
                      data-testid="rut-proxy-chain-extra-hops"
                      value={proxyChainExtraHops}
                      onChange={(e) => setProxyChainExtraHops(e.target.value.slice(0, 800))}
                      rows={3}
                      placeholder="socks5://hop1.example:1080&#10;http://user:pass@hop2.example:8080"
                      className="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1.5 text-xs font-mono"
                    />
                    <p className="text-[10px] text-zinc-500 mt-1">
                      Inserted BETWEEN Tor and exit proxy. Build 3+ hop chains. Max 6 hops.
                    </p>
                  </div>
                )}
                <p className="text-xs text-gray-500 mt-2">
                  Breaks single-IP correlation (IPQS / AppsFlyer / Anura cross-IP graph). Tor unreachable → graceful single-hop fallback. Off = legacy single-proxy.
                </p>
              </div>
              <div>
                <Label className="text-zinc-300 text-sm">Browser Binary</Label>
                <select
                  data-testid="rut-browser-variant"
                  value={browserVariant}
                  onChange={(e) => setBrowserVariant(e.target.value)}
                  className="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-2 py-1.5 text-sm"
                >
                  <option value="auto">Auto (default — full chromium when available)</option>
                  {adCapabilities?.browser_variants?.includes("chromium") && (
                    <option value="chromium">Full Chromium (--headless=new)</option>
                  )}
                  {adCapabilities?.browser_variants?.includes("brave") && (
                    <option value="brave">Brave Browser</option>
                  )}
                  {adCapabilities?.browser_variants?.includes("headless-shell") && (
                    <option value="headless-shell">Chromium Headless-Shell (lightweight)</option>
                  )}
                  <option value="rotate">Rotate (random per job from installed binaries)</option>
                </select>
                {adCapabilities && (
                  <div className="mt-1 text-[10px] text-zinc-500 font-mono flex flex-wrap gap-2" data-testid="rut-browser-variants-available">
                    {adCapabilities.chromium_path && <span className="text-emerald-300">✓ chromium</span>}
                    {adCapabilities.brave_path && <span className="text-emerald-300">✓ brave</span>}
                    {adCapabilities.headless_shell_path && <span className="text-emerald-300">✓ headless-shell</span>}
                    {!adCapabilities.chromium_path && <span>· chromium ✗</span>}
                    {!adCapabilities.brave_path && <span>· brave ✗</span>}
                    {!adCapabilities.headless_shell_path && <span>· headless-shell ✗</span>}
                  </div>
                )}
                <p className="text-xs text-gray-500 mt-1">
                  Defeats "100% Chromium" cohort tell. Brave path: set <code>KREXION_BRAVE_PATH</code> env or install at standard paths. Variants not present here will fall back to auto.
                </p>
              </div>
            </div>
          </div>

          {/* ── 2026-02 v2.1.31 — Anti-Detect (Phase 4) ── */}
          <div className="mt-6 p-4 rounded-lg border border-emerald-500/30 bg-emerald-950/10">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-emerald-300 text-sm font-semibold">🧬 Anti-Detect (Phase 4)</span>
              <span className="text-[10px] text-zinc-500 px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-800">WebAuthn · ClientRects · HTTP/3 · IPv6 · Behavioral · IP Warm-up · Identity Persistence</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Always-on patches summary */}
              <div className="p-3 rounded-md bg-emerald-950/20 border border-emerald-500/20">
                <div className="text-xs font-semibold text-emerald-200 mb-2">Always-On (injected automatically)</div>
                <ul className="text-[11px] text-zinc-400 space-y-0.5 font-mono">
                  <li><span className="text-emerald-400">✓</span> WebAuthn <code>isUserVerifyingPlatformAuthenticatorAvailable</code> → true</li>
                  <li><span className="text-emerald-400">✓</span> ClientRects / getBoundingClientRect sub-pixel noise</li>
                  <li><span className="text-emerald-400">✓</span> ScreenOrientation realism</li>
                  <li><span className="text-emerald-400">✓</span> HTTP/3 (QUIC h3) enabled at launch</li>
                  <li><span className="text-emerald-400">✓</span> IPv6 dual-stack enabled at launch</li>
                </ul>
              </div>

              {/* Opt-in toggles */}
              <div className="space-y-3">
                <div>
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      data-testid="rut-behavioral-bio-enabled"
                      type="checkbox"
                      checked={behavioralBioEnabled}
                      onChange={(e) => setBehavioralBioEnabled(e.target.checked)}
                      className="mt-0.5 w-4 h-4 rounded accent-emerald-500"
                    />
                    <div>
                      <div className="text-sm text-zinc-200">Behavioral Biometrics (paranoia mode)</div>
                      <p className="text-[11px] text-zinc-500">
                        Longer pre-click dwells, micro-movements, scroll-before-click. Defeats BioCatch / NuData / Forter on Tier-2 networks. +5–8% bypass; +2–4s/visit.
                      </p>
                    </div>
                  </label>
                </div>

                <div>
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      data-testid="rut-ip-warmup-enabled"
                      type="checkbox"
                      checked={ipWarmupEnabled}
                      onChange={(e) => setIpWarmupEnabled(e.target.checked)}
                      className="mt-0.5 w-4 h-4 rounded accent-emerald-500"
                    />
                    <div>
                      <div className="text-sm text-zinc-200">IP Warm-up (visit Google / Wikipedia first)</div>
                      <p className="text-[11px] text-zinc-500">
                        Visits 2 benign sites via the same proxy before target. Seeds CF / Akamai cookies, IP looks "active" not cold. +~10s/visit.
                      </p>
                    </div>
                  </label>
                </div>

                <div className="text-[11px] text-zinc-500 pl-6">
                  <span className="text-emerald-300">Identity Label set above</span> → cookies + localStorage + history persist across runs (browser profile aging).
                </div>
              </div>
            </div>
          </div>
          </div>{/* /hidden wrapper closing for Phase 3+4 (2026-06-11 unified UI) */}

          {/* Allowed OS */}
          <div>
            <Label className="text-zinc-300 mb-2 block text-sm">
              Allowed Operating Systems{" "}
              <span className="text-zinc-500 text-xs font-normal">
                (click to toggle — leave empty to allow ALL OS)
              </span>
            </Label>
            <div className="flex flex-wrap gap-2">
              {OS_CHIPS.map((os) => {
                const active = allowedOs.includes(os.key);
                const Icon =
                  os.key === "ios" || os.key === "macos" ? Apple :
                  os.key === "android" ? Radio :
                  Monitor;
                return (
                  <button
                    key={os.key}
                    type="button"
                    data-testid={`rut-os-${os.key}`}
                    onClick={() => toggleOs(os.key)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center gap-2 ${
                      active
                        ? "bg-fuchsia-600 border-fuchsia-500 text-white"
                        : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                    }`}
                  >
                    <Icon size={14} />
                    {os.label}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-zinc-500 mt-2">
              {allowedOs.length === 0
                ? "Any OS will be accepted"
                : `Only ${allowedOs.map(k => OS_CHIPS.find(o => o.key === k)?.label).join(" · ")} UAs will be used — all others skipped`}
            </p>
          </div>

          {/* Allowed Countries */}
          <div>
            <Label className="text-zinc-300 mb-2 block text-sm">
              Allowed Countries{" "}
              <span className="text-zinc-500 text-xs font-normal">
                (click to toggle — leave empty to allow ALL countries)
              </span>
            </Label>
            <div className="flex flex-wrap gap-1.5">
              {COUNTRY_CHIPS.map((c) => {
                const active = allowedCountries.includes(c);
                return (
                  <button
                    key={c}
                    type="button"
                    data-testid={`rut-country-${c.replace(/\s+/g, "-").toLowerCase()}`}
                    onClick={() => toggleCountry(c)}
                    className={`px-3 py-1 rounded-full text-xs font-medium border transition ${
                      active
                        ? "bg-fuchsia-600 border-fuchsia-500 text-white"
                        : "bg-zinc-900 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                    }`}
                  >
                    {c}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-zinc-500 mt-2">
              {allowedCountries.length === 0
                ? "Any country will be accepted"
                : `${allowedCountries.length} countries selected`}
            </p>
          </div>

          {/* Toggle filters - inline row */}
          <div className="flex flex-wrap gap-x-6 gap-y-3 pt-2 border-t border-zinc-800">
            <CheckRow testId="rut-skip-duplicate-ip" checked={skipDuplicateIp} onChange={setSkipDuplicateIp}>
              <span className="text-zinc-300">🚫 Skip duplicate exit IP</span>
            </CheckRow>
            {/* 2026-06-26 — quick action to wipe the per-user burnt-IP
                cache. After many test runs the persistent blocklist
                grows to 200+ entries which causes every new job to
                burn 2-10 attempts cycling stale IPs before finding a
                fresh one. Operator can hit this once to start fresh. */}
            <button
              type="button"
              data-testid="rut-clear-burnt-ips"
              onClick={async () => {
                if (!window.confirm("Aap ke account ki SAARI burnt-IP history clear ho jaye gi. Confirm?")) return;
                try {
                  const r = await fetch(`${API_URL}/api/real-user-traffic/burnt-ips`, {
                    method: "DELETE",
                    headers: { Authorization: `Bearer ${localStorage.getItem("token") || ""}` },
                  });
                  const data = await r.json().catch(() => ({}));
                  if (r.ok) {
                    toast.success(`✓ Cleared ${data?.deleted ?? 0} burnt-IP entries — next job starts fresh.`);
                  } else {
                    toast.error(`Clear failed: ${data?.detail || r.statusText}`);
                  }
                } catch (e) {
                  toast.error(`Clear failed: ${e.message}`);
                }
              }}
              className="text-xs text-zinc-400 hover:text-amber-300 underline-offset-2 hover:underline transition-colors"
              title="Wipe your burnt-IP blocklist so the next job doesn't waste retries on stale duplicate-IP burns"
            >
              🧹 Clear my burnt-IP cache
            </button>
            <CheckRow testId="rut-skip-vpn" checked={skipVpn} onChange={setSkipVpn}>
              <span className="text-zinc-300">🛡️ Skip VPN / datacenter</span>
            </CheckRow>
            <CheckRow testId="rut-follow-redirect" checked={followRedirect} onChange={setFollowRedirect}>
              <span className="text-zinc-300">🔄 Follow redirect to offer URL</span>
            </CheckRow>
            <CheckRow testId="rut-no-repeated-proxy" checked={noRepeatedProxy} onChange={setNoRepeatedProxy}>
              <span className="text-zinc-300">♻️ No repeated proxy (one use per line)</span>
            </CheckRow>
            <CheckRow testId="rut-force-tracker-url" checked={forceTrackerUrl} onChange={setForceTrackerUrl}>
              <span className="text-zinc-300">
                🎯 Strict tracker URL
                <span className="text-zinc-500 text-xs ml-2">
                  (force every visit through /api/t/&lt;short_code&gt; — best for strict duplicate-IP &amp; click counting; may 403 from some residential proxies on preview pods)
                </span>
              </span>
            </CheckRow>
            {/* 2026-07 v2.6.9 CUSTOMER-REQUEST — 3rd-party tracker hard-block detection */}
            <CheckRow testId="rut-abort-on-tracker-block" checked={abortOnTrackerBlock} onChange={setAbortOnTrackerBlock}>
              <span className="text-zinc-300">
                ⛔ Abort on tracker hard-block
                <span className="text-zinc-500 text-xs ml-2">
                  (Traxun / Voluum / RedTrack "Access Denied" · "Duplicate Access" · "Close Manually" screens → instant visit abort, save proxy budget)
                </span>
              </span>
            </CheckRow>
          </div>
          {/* Custom tracker-block patterns textarea (only visible when the toggle is ON) */}
          {abortOnTrackerBlock && (
            <div className="pt-4 border-t border-zinc-800 mt-3">
              <label className="text-xs text-zinc-400 flex items-center gap-2 mb-2">
                <span>🛡️ Custom tracker-block phrases</span>
                <span className="text-zinc-600">(one per line — case-insensitive substring match)</span>
              </label>
              <textarea
                data-testid="rut-tracker-block-patterns"
                value={trackerBlockExtraPatterns}
                onChange={(e) => setTrackerBlockExtraPatterns(e.target.value)}
                placeholder={"Access denied\nDuplicate access\nClose manually\nTraxun Security Shield\nYour tracker's custom block message here…"}
                className="w-full text-xs bg-zinc-950 border border-zinc-800 rounded p-2 text-zinc-200 font-mono min-h-[90px] resize-y focus:border-purple-700 outline-none"
                rows={4}
              />
              <p className="text-[11px] text-zinc-500 mt-1">
                ℹ️ Built-in phrases already include Traxun/Voluum/RedTrack/Binom common blocks. Add ONLY your tracker's extra phrases here.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ═══ Form Filler TOGGLE ═══ */}
      <Card className={`border transition ${
        formFillEnabled ? "bg-emerald-950/20 border-emerald-800" : "bg-zinc-900 border-zinc-800"
      }`}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <ClipboardCheck className={formFillEnabled ? "text-emerald-400" : "text-zinc-500"} size={22} />
              <div>
                <CardTitle className="text-white text-base flex items-center gap-2">
                  Form Filler / Survey Bot
                  {formFillEnabled && (
                    <Badge className="bg-emerald-900/50 text-emerald-200 border-emerald-800">ENABLED</Badge>
                  )}
                </CardTitle>
                <CardDescription className="text-zinc-400 text-xs mt-1">
                  Turn ON to auto-fill the landing-page form + survey with your leads data, using
                  the same proxies + UAs + OS filter from above.
                </CardDescription>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setFormFillEnabled(!formFillEnabled)}
              data-testid="rut-form-fill-toggle"
              role="switch"
              aria-checked={formFillEnabled}
              className={`relative inline-flex h-7 w-14 shrink-0 cursor-pointer items-center rounded-full border transition ${
                formFillEnabled ? "bg-emerald-600 border-emerald-500" : "bg-zinc-700 border-zinc-600"
              }`}
            >
              <span
                className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${
                  formFillEnabled ? "translate-x-8" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        </CardHeader>

        {formFillEnabled && (
          <CardContent className="space-y-4 border-t border-emerald-900/30 pt-4">
            {/* Data source toggle */}
            <div>
              <Label className="text-zinc-300 text-sm mb-2 block">Data source</Label>
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => setDataSource("excel")}
                  data-testid="rut-data-excel"
                  className={`p-3 rounded-lg border text-sm font-medium transition flex items-center justify-center gap-2 ${
                    dataSource === "excel"
                      ? "bg-emerald-600 border-emerald-500 text-white"
                      : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                  }`}
                >
                  <FileSpreadsheet size={16} /> Excel / CSV upload
                </button>
                <button
                  type="button"
                  onClick={() => setDataSource("gsheet")}
                  data-testid="rut-data-gsheet"
                  className={`p-3 rounded-lg border text-sm font-medium transition flex items-center justify-center gap-2 ${
                    dataSource === "gsheet"
                      ? "bg-emerald-600 border-emerald-500 text-white"
                      : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                  }`}
                >
                  <SheetIcon size={16} /> Google Sheet
                </button>
                <button
                  type="button"
                  onClick={() => { setDataSource("pending_from_job"); fetchPendingCandidates(); }}
                  data-testid="rut-data-pending"
                  disabled={pendingCandidates.length === 0}
                  title={pendingCandidates.length === 0 ? "No past runs with unused leads — finish a run first" : "Import the unused leads from a previous run"}
                  className={`p-3 rounded-lg border text-sm font-medium transition flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed ${
                    dataSource === "pending_from_job"
                      ? "bg-amber-600 border-amber-500 text-white"
                      : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:border-zinc-600"
                  }`}
                >
                  <Download size={16} /> Pending from previous run
                  {pendingCandidates.length > 0 && (
                    <span className="ml-1 text-[10px] bg-amber-900/60 px-1.5 py-0.5 rounded">{pendingCandidates.length}</span>
                  )}
                </button>
              </div>
              {dataSource === "excel" ? (
                <div className="mt-2 space-y-2">
                  {/* Uploaded data file picker */}
                  {uploadedLibrary.filter(u => u.type === "data_file").length > 0 && (
                    <div className="p-2 bg-indigo-950/30 border border-indigo-900/50 rounded">
                      <Label className="text-indigo-300 text-xs mb-1 block">
                        Or pick a saved file from <span className="font-semibold">Uploaded Things</span> (auto-deletes after use)
                      </Label>
                      <select
                        value={selectedUploadDataId}
                        onChange={(e) => {
                          const id = e.target.value;
                          setSelectedUploadDataId(id);
                          if (id) {
                            previewDataFile({ uploadDataFileId: id });
                          } else {
                            setDataPreview(null);
                            setSelectedStates([]);
                            setSelectedEmailDomains([]);
                          }
                        }}
                        className="w-full h-8 px-2 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                        data-testid="rut-upload-data-id"
                      >
                        <option value="">— upload manually below —</option>
                        {uploadedLibrary.filter(u => u.type === "data_file").map((u) => {
                          // 2026-06 — Show "1857 / 1920" when some rows
                          // have already been consumed, so the user
                          // knows the file auto-skips used leads.
                          const original = u.original_item_count || u.item_count || 0;
                          const available = u.available_count != null ? u.available_count : u.item_count;
                          const countLabel = (u.consumed_count > 0 && available !== original)
                            ? `${available} / ${original} rows`
                            : `${available} rows`;
                          return (
                            <option key={u.id} value={u.id}>
                              {u.name} · {countLabel} · {u.file_name}
                            </option>
                          );
                        })}
                      </select>
                    </div>
                  )}
                  <Input
                    data-testid="rut-file"
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    onChange={(e) => {
                      const f = e.target.files?.[0] || null;
                      setFile(f);
                      if (f) {
                        previewDataFile({ fileObj: f });
                      } else {
                        setDataPreview(null);
                        setSelectedStates([]);
                        setSelectedEmailDomains([]);
                      }
                    }}
                    disabled={!!selectedUploadDataId}
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 file:text-zinc-100 file:bg-zinc-700 file:border-0 file:rounded disabled:opacity-50"
                  />
                  {selectedUploadDataId && (
                    <p className="text-xs text-zinc-500">
                      Using saved batch · used rows are tracked automatically — original file stays intact, a separate "remaining" file is auto-maintained.
                    </p>
                  )}

                  {/* ── Data file analysis: detected states + filter ────────── */}
                  {previewLoading && (
                    <div className="mt-2 p-2 bg-zinc-900 border border-zinc-700 rounded text-xs text-zinc-400" data-testid="rut-data-preview-loading">
                      Analyzing file…
                    </div>
                  )}
                  {dataPreview && dataPreview.total_rows > 0 && (
                    <div
                      className="mt-2 p-3 bg-emerald-950/30 border border-emerald-900/60 rounded space-y-2"
                      data-testid="rut-data-preview-panel"
                    >
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <div className="text-sm text-emerald-300 font-semibold">
                          📊 File analysis: {dataPreview.total_rows} leads
                          {dataPreview.states.length > 0 && (
                            <span className="text-emerald-400/80 font-normal"> · {dataPreview.states.length} state{dataPreview.states.length !== 1 ? "s" : ""}</span>
                          )}
                        </div>
                        {dataPreview.states.length > 0 && (
                          <div className="flex gap-1 text-[11px]">
                            <button
                              type="button"
                              onClick={() => setSelectedStates(dataPreview.states.map((s) => s.code))}
                              className="px-2 py-0.5 bg-emerald-700/40 hover:bg-emerald-700/70 text-emerald-100 rounded"
                              data-testid="rut-state-select-all"
                            >
                              Select all
                            </button>
                            <button
                              type="button"
                              onClick={() => setSelectedStates([])}
                              className="px-2 py-0.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-100 rounded"
                              data-testid="rut-state-clear-all"
                            >
                              Clear all
                            </button>
                          </div>
                        )}
                      </div>

                      {dataPreview.states.length > 0 ? (
                        <div className="space-y-1.5">
                          <div className="text-[11px] text-emerald-200/70">
                            Tick which states this job should run on (only those rows are sent through traffic).
                            Use with <span className="font-semibold">Auto Mode</span> = "Any" + <span className="font-semibold">Match lead-state to proxy IP</span> for perfect geo-match.
                          </div>
                          <div className="flex flex-wrap gap-1.5" data-testid="rut-state-list">
                            {dataPreview.states.map((s) => {
                              const checked = selectedStates.includes(s.code);
                              return (
                                <label
                                  key={s.code}
                                  className={`px-2 py-1 rounded text-xs flex items-center gap-1.5 cursor-pointer border transition ${
                                    checked
                                      ? "bg-emerald-600/30 border-emerald-500 text-emerald-100"
                                      : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500"
                                  }`}
                                  data-testid={`rut-state-pill-${s.code}`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() =>
                                      setSelectedStates((prev) =>
                                        prev.includes(s.code)
                                          ? prev.filter((c) => c !== s.code)
                                          : [...prev, s.code]
                                      )
                                    }
                                    className="h-3 w-3 accent-emerald-500"
                                  />
                                  <span className="font-semibold">{s.code}</span>
                                  <span className="opacity-70">({s.count})</span>
                                </label>
                              );
                            })}
                          </div>
                          <div className="text-[11px] text-emerald-300">
                            Selected: <b>{selectedStates.length}</b> / {dataPreview.states.length} states ·{" "}
                            <b>
                              {dataPreview.states
                                .filter((s) => selectedStates.includes(s.code))
                                .reduce((sum, s) => sum + s.count, 0)}
                            </b>{" "}
                            rows will be used
                          </div>
                        </div>
                      ) : (
                        <div className="text-[11px] text-amber-300">
                          ⚠ No state column detected — state filter unavailable. Job will use all {dataPreview.total_rows} rows.
                        </div>
                      )}

                      {/* ── 2026-06 Email-domain filter (gmail / yahoo / hotmail …) ── */}
                      {dataPreview.email_domains && dataPreview.email_domains.length > 0 && (
                        <div className="space-y-1.5 border-t border-emerald-900/40 pt-2 mt-2" data-testid="rut-email-filter-block">
                          <div className="flex items-center justify-between">
                            <div className="text-[12px] font-semibold text-emerald-200">
                              📧 Email-domain filter
                              <span className="text-emerald-300/70 font-normal"> · {dataPreview.email_domains.length} domain{dataPreview.email_domains.length !== 1 ? "s" : ""} detected</span>
                            </div>
                            <div className="flex gap-1 text-[11px]">
                              <button
                                type="button"
                                onClick={() => setSelectedEmailDomains(dataPreview.email_domains.map((d) => d.domain))}
                                className="px-2 py-0.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-100 rounded"
                                data-testid="rut-email-select-all"
                              >
                                Select all
                              </button>
                              <button
                                type="button"
                                onClick={() => setSelectedEmailDomains([])}
                                className="px-2 py-0.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-100 rounded"
                                data-testid="rut-email-clear-all"
                              >
                                Clear all
                              </button>
                            </div>
                          </div>
                          <div className="text-[11px] text-emerald-200/70">
                            Tick which email providers this job should run on (only rows whose email is at those domains).
                          </div>
                          <div className="flex flex-wrap gap-1.5" data-testid="rut-email-list">
                            {dataPreview.email_domains.map((e) => {
                              const checked = selectedEmailDomains.includes(e.domain);
                              return (
                                <label
                                  key={e.domain}
                                  className={`px-2 py-1 rounded text-xs flex items-center gap-1.5 cursor-pointer border transition ${
                                    checked
                                      ? "bg-emerald-600/30 border-emerald-500 text-emerald-100"
                                      : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500"
                                  }`}
                                  data-testid={`rut-email-pill-${e.domain}`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() =>
                                      setSelectedEmailDomains((prev) =>
                                        prev.includes(e.domain)
                                          ? prev.filter((d) => d !== e.domain)
                                          : [...prev, e.domain]
                                      )
                                    }
                                    className="h-3 w-3 accent-emerald-500"
                                  />
                                  <span className="font-semibold">{e.domain}</span>
                                  <span className="opacity-70">({e.count})</span>
                                </label>
                              );
                            })}
                          </div>
                          <div className="text-[11px] text-emerald-300">
                            Selected: <b>{selectedEmailDomains.length}</b> / {dataPreview.email_domains.length} domains ·{" "}
                            <b>
                              {dataPreview.email_domains
                                .filter((e) => selectedEmailDomains.includes(e.domain))
                                .reduce((sum, e) => sum + e.count, 0)}
                            </b>{" "}
                            rows match
                          </div>
                        </div>
                      )}
                      {dataPreview.email_column && (!dataPreview.email_domains || dataPreview.email_domains.length === 0) && (
                        <div className="text-[11px] text-amber-300 border-t border-emerald-900/40 pt-2 mt-2">
                          ⚠ Email column detected but no valid email domains found.
                        </div>
                      )}

                      {/* Quality warnings — only show fields that have empties */}
                      {dataPreview.quality && Object.values(dataPreview.quality).some((v) => v > 0) && (
                        <div className="text-[11px] text-amber-300/90 border-t border-emerald-900/40 pt-1.5">
                          ⚠ <span className="font-semibold">Empty fields detected:</span>{" "}
                          {Object.entries(dataPreview.quality)
                            .filter(([, v]) => v > 0)
                            .map(([k, v]) => `${k.replace("empty_", "")}: ${v}`)
                            .join(" · ")}
                          <div className="text-amber-300/70 mt-0.5">
                            Empty values may cause form-fill failures for those rows.
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : dataSource === "gsheet" ? (
                <Input
                  data-testid="rut-gsheet-url"
                  placeholder="https://docs.google.com/spreadsheets/d/…/edit — must be published as CSV"
                  value={gsheetUrl}
                  onChange={(e) => {
                    setGsheetUrl(e.target.value);
                    setDataPreview(null);
                    setSelectedStates([]);
                    setSelectedEmailDomains([]);
                  }}
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v) previewDataFile({ gsheetUrl: v });
                  }}
                  className="mt-2 bg-zinc-800 border-zinc-700 text-zinc-100"
                />
              ) : (
                <div className="mt-2 space-y-1">
                  <select
                    data-testid="rut-pending-select"
                    value={importPendingJobId}
                    onChange={(e) => setImportPendingJobId(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-amber-500"
                  >
                    <option value="">— Select a previous run —</option>
                    {pendingCandidates.map((c) => (
                      <option key={c.job_id} value={c.job_id}>
                        {c.job_id.slice(0, 8)} · {c.pending_leads_count} leads left · {c.link_short_code || "—"} · {c.created_at ? new Date(c.created_at).toLocaleString() : ""}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-amber-300/80">
                    Imports the `pending_leads.xlsx` from the selected run automatically — no file upload needed.
                  </p>
                </div>
              )}
              <p className="text-xs text-zinc-500 mt-1">
                Columns auto-match to form fields by name / id / placeholder / aria-label — e.g.{" "}
                <code className="text-zinc-400">first_name, last_name, email, phone, address, zip, dob</code>
              </p>
            </div>

            {/* State-match toggle */}
            <div className="rounded-lg border border-amber-900/40 bg-amber-950/10 p-3">
              <CheckRow testId="rut-state-match" checked={stateMatchEnabled} onChange={setStateMatchEnabled}>
                <span className="text-amber-200 font-medium">🌎 Match lead state to proxy IP state</span>
              </CheckRow>
              <p className="text-xs text-zinc-400 mt-1 pl-7">
                When ON: a row is only submitted through a proxy whose exit-IP is in the SAME US state
                as the lead (e.g. California lead → California proxy). Needs a <code className="text-amber-300">state</code> column in your data
                (full name or 2-letter code). Visits with no matching lead are counted as <code className="text-amber-300">skipped_state_mismatch</code>.
              </p>
              {/* Smart proxy-gen hint — visible only when state-match is ON AND
                  Auto Mode is ON AND no specific state pinned.
                  This is the configuration that triggers the "generate
                  proxies in the same state distribution as your leads"
                  shortcut, eliminating state-mismatch waste. */}
              {stateMatchEnabled && useProxyJetAuto && !(proxyJetState || "").trim() && (
                <div
                  className="mt-2 ml-7 p-2 rounded border border-emerald-900/40 bg-emerald-950/20 text-[11px] text-emerald-200 leading-relaxed"
                  data-testid="rut-smart-gen-hint"
                >
                  <span className="font-semibold">⚡ Smart sequence active:</span> for this run the engine will
                  first read each lead's state and then ask your provider for a fresh unique IP
                  <em> from that same state</em>. Pre-loop state-mismatch skips become zero — every visit
                  reaches form-fill + automation.
                </div>
              )}
            </div>

            {/* Invalid-data detection toggle — DEFAULT OFF */}
            <div className="rounded-lg border border-red-900/40 bg-red-950/10 p-3">
              <CheckRow testId="rut-invalid-detect" checked={invalidDetectionEnabled} onChange={setInvalidDetectionEnabled}>
                <span className="text-red-200 font-medium">🔍 Detect &amp; remove invalid leads <span className="text-[10px] text-zinc-500 font-normal">(advanced — leave OFF if unsure)</span></span>
              </CheckRow>
              <p className="text-xs text-zinc-400 mt-1 pl-7">
                When ON: after every submit, the page is scanned for inline validation errors (Bootstrap <code className="text-red-300">.invalid-feedback</code>, Angular / MUI error messages, or body text like "invalid email / invalid zip / duplicate submission"). Matching rows are auto-removed from pending leads and the form retries with the next lead.
                <br />
                <span className="text-amber-300">
                  ⚠️ Keep OFF for offer pages that show consent / marketing banners — those can be misread as errors and cause every visit to loop-retry without any conversion.
                </span>
              </p>
              {invalidDetectionEnabled && (
                <div className="mt-3 pl-7 flex flex-wrap items-center gap-3">
                  <Label className="text-red-200 text-xs whitespace-nowrap" htmlFor="rut-invalid-retry">
                    Max replacement leads per visit:
                  </Label>
                  <Input
                    id="rut-invalid-retry"
                    type="number"
                    min={1}
                    max={50}
                    value={invalidDataRetryLimit}
                    onChange={(e) =>
                      setInvalidDataRetryLimit(
                        Math.max(1, Math.min(50, Number(e.target.value) || 10))
                      )
                    }
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 max-w-[80px] h-8 text-xs"
                    data-testid="rut-invalid-retry-limit"
                  />
                  <span className="text-[11px] text-zinc-400">
                    Higher = visit absorbs more dirty rows before giving up (proxy/UA not wasted). Default 10.
                  </span>
                </div>
              )}
            </div>

            <CheckRow testId="rut-skip-captcha" checked={skipCaptcha} onChange={setSkipCaptcha}>
              <span className="text-zinc-300">
                ⚠️ Skip if captcha detected{" "}
                <span className="text-zinc-500 text-xs">(reCAPTCHA · hCaptcha · Turnstile)</span>
              </span>
            </CheckRow>

            {/* Post-submit wait */}
            <div className="pt-3 border-t border-emerald-900/30">
              <Label className="text-zinc-300 text-sm">
                Post-submit wait (seconds) — how long to stay on the "thank-you" page before final screenshot
              </Label>
              <div className="flex items-center gap-3 mt-1">
                <Input
                  type="number"
                  min={3}
                  max={15}
                  value={postSubmitWait}
                  onChange={(e) => setPostSubmitWait(Math.max(3, Math.min(15, Number(e.target.value) || 6)))}
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 max-w-[120px]"
                  data-testid="rut-post-submit-wait"
                />
                <span className="text-xs text-zinc-500">Range: 3-15s. Default: 6s.</span>
              </div>
            </div>

            {/* 2026-06 — Slow-step wait multiplier */}
            <div className="pt-3 border-t border-emerald-900/30">
              <Label className="text-zinc-300 text-sm">
                Step-wait multiplier — stretch per-step timeouts when offer / proxy is slow
              </Label>
              <div className="flex items-center gap-3 mt-1 flex-wrap">
                <Input
                  type="number"
                  min={0.5}
                  max={5}
                  step={0.5}
                  value={stepTimeoutMultiplier}
                  onChange={(e) =>
                    setStepTimeoutMultiplier(
                      Math.max(0.5, Math.min(5, Number(e.target.value) || 1))
                    )
                  }
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 max-w-[120px]"
                  data-testid="rut-step-timeout-multiplier"
                />
                <span className="text-xs text-zinc-500">
                  Range: 0.5×–5×. Default: 1× (30-45s per step). E.g. 2× = wait 60-90s before moving on so a slow page can finish before the next step fires. Visit nahi waste hoti.
                </span>
              </div>
            </div>

            {/* AI Automation Generator */}
            <div className="pt-3 border-t border-emerald-900/30">
              <button
                type="button"
                onClick={() => setAiGenOpen((v) => !v)}
                className="w-full text-left flex items-center justify-between px-3 py-2 rounded-md bg-gradient-to-r from-fuchsia-900/40 to-indigo-900/40 border border-fuchsia-700/40 hover:from-fuchsia-900/60 hover:to-indigo-900/60 transition"
                data-testid="rut-ai-generator-toggle"
              >
                <span className="text-sm font-semibold text-fuchsia-200">
                  🎬 AI Automation Generator — screenshots/video se JSON banao
                </span>
                <span className="text-xs text-fuchsia-300">{aiGenOpen ? "▲ Hide" : "▼ Open"}</span>
              </button>

              {aiGenOpen && (
                <div className="mt-3 p-3 rounded-md border border-fuchsia-800/40 bg-zinc-950/60 space-y-3">
                  <p className="text-xs text-zinc-400">
                    Upload karo: <b>1-15 screenshots</b> (jpg/png/webp) <b>ya 1 short video</b> (mp4/mov/webm, max 40 MB)
                    jismein aap ka form-fill process dikh raha ho. Gemini 2.5 Pro dekh ke
                    automation JSON khud bana de ga.
                  </p>

                  <div className="grid md:grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-zinc-300 text-xs">Target URL (optional, best accuracy)</Label>
                      <Input
                        data-testid="rut-aigen-target-url"
                        value={aiGenTargetUrl}
                        onChange={(e) => setAiGenTargetUrl(e.target.value)}
                        placeholder="https://example-offer.com"
                        className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-zinc-300 text-xs">Excel columns (comma-separated)</Label>
                      <Input
                        data-testid="rut-aigen-cols"
                        value={aiGenCols}
                        onChange={(e) => setAiGenCols(e.target.value)}
                        placeholder="first, last, email, phone, zip, month, day, year"
                        className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <Label className="text-zinc-300 text-xs">Description (Roman Urdu/English OK)</Label>
                    <Textarea
                      data-testid="rut-aigen-desc"
                      rows={3}
                      value={aiGenDesc}
                      onChange={(e) => setAiGenDesc(e.target.value)}
                      placeholder="Pehle UNLOCK NOW par click karo, phir form fill karo (first, last, email, phone), TCPA checkbox tick karo, Submit par click karo, 6 second wait karo."
                      className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                    />
                  </div>

                  <div className="space-y-1">
                    <Label className="text-zinc-300 text-xs">Screenshots or Video</Label>
                    <input
                      type="file"
                      multiple
                      accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,video/mpeg"
                      onChange={(e) => setAiGenFiles(Array.from(e.target.files || []))}
                      data-testid="rut-aigen-files"
                      className="block w-full text-xs text-zinc-300 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:bg-fuchsia-700 file:text-white hover:file:bg-fuchsia-600"
                    />
                    {aiGenFiles.length > 0 && (
                      <p className="text-xs text-zinc-500">
                        Selected: {aiGenFiles.length} file(s) —{" "}
                        {Array.from(aiGenFiles).map((f) => f.name).join(", ").slice(0, 140)}
                      </p>
                    )}
                  </div>

                  <Button
                    type="button"
                    onClick={onAiGenerate}
                    disabled={aiGenLoading}
                    data-testid="rut-aigen-submit"
                    className="w-full bg-fuchsia-600 hover:bg-fuchsia-700 text-white"
                  >
                    {aiGenLoading ? (
                      <><RefreshCw className="animate-spin mr-2" size={16} /> Gemini 2.5 Pro analysing…</>
                    ) : (
                      <>✨ Generate Automation JSON</>
                    )}
                  </Button>

                  <p className="text-xs text-amber-300/70">
                    💡 Tip: Video mein aap screen record karein — landing page → UNLOCK click → form fill → submit tak.
                    Aur Excel columns ke naam upar likh dein taa ke placeholders match hon ({"{{first}}"}, {"{{email}}"} etc.).
                  </p>
                </div>
              )}
            </div>

            {/* ── 2026-07: Smart Funnel (native adaptive engine) ── */}
            <div className="pt-3 border-t border-emerald-900/30">
              <p className="text-zinc-200 text-sm font-medium mb-2">🧠 Funnel Mode</p>
              <div className="space-y-2 ml-1">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="funnelMode"
                    checked={funnelMode === "smart"}
                    onChange={() => { setFunnelMode("smart"); setUseCustomJson(false); }}
                    className="mt-1 accent-violet-500"
                    data-testid="rut-funnel-smart"
                  />
                  <span className="text-xs text-zinc-300">
                    <b className="text-violet-300">Smart Funnel</b> (Recommended) — surveys, forms, deals auto-detect.
                    Page-order resilient, no 400-step JSON. Excel placeholders auto-clean (zip, DOB, phone).
                  </span>
                </label>
                {funnelMode === "smart" && (
                  <div className="ml-6 p-3 bg-violet-950/20 border border-violet-900/40 rounded space-y-3">
                    <div>
                      <Label className="text-violet-300 text-xs">Pattern</Label>
                      <select
                        value={smartFunnelPattern}
                        onChange={(e) => setSmartFunnelPattern(e.target.value)}
                        className="w-full h-8 px-2 mt-1 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                        data-testid="rut-smart-funnel-pattern"
                      >
                        <option value="auto">Auto Detect</option>
                        <option value="reward_survey_funnel">Reward Survey Funnel</option>
                        <option value="survey_form_deals">Survey + Form + Deals</option>
                        <option value="form_deals">Form + Deals</option>
                      </select>
                    </div>
                    <div className="flex flex-wrap gap-4 items-center">
                      <div>
                        <Label className="text-violet-300 text-xs">Min deals</Label>
                        <input
                          type="number"
                          min={1}
                          max={5}
                          value={smartFunnelMinDeals}
                          onChange={(e) => setSmartFunnelMinDeals(Math.max(1, Math.min(5, parseInt(e.target.value, 10) || 2)))}
                          className="w-20 h-8 px-2 mt-1 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                          data-testid="rut-smart-funnel-min-deals"
                        />
                      </div>
                      <label className="flex items-center gap-2 cursor-pointer mt-4">
                        <input
                          type="checkbox"
                          checked={smartFunnelWaitUntilConversion}
                          onChange={(e) => setSmartFunnelWaitUntilConversion(e.target.checked)}
                          className="w-4 h-4 accent-violet-500"
                          data-testid="rut-smart-funnel-wait-conversion"
                        />
                        <span className="text-xs text-zinc-300">Wait until conversion (extended watchdog, no early exit)</span>
                      </label>
                    </div>
                    <p className="text-[11px] text-violet-300/70">
                      Tip: Amazon $750 deal wall (LEVEL 1 DEALS) needs Min deals = 3. Stuck Watchdog ≥ 1800s recommended for long survey offers when wait-until-conversion is ON.
                    </p>
                  </div>
                )}
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="funnelMode"
                    checked={funnelMode === "custom"}
                    onChange={() => { setFunnelMode("custom"); setUseCustomJson(true); }}
                    className="mt-1 accent-emerald-500"
                    data-testid="rut-funnel-custom"
                  />
                  <span className="text-xs text-zinc-300">
                    <b>Custom Automation JSON</b> — Visual Recorder step-by-step script (402-step flows, Pure JSON mode, etc.)
                  </span>
                </label>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="funnelMode"
                    checked={funnelMode === "legacy"}
                    onChange={() => { setFunnelMode("legacy"); setUseCustomJson(false); }}
                    className="mt-1 accent-zinc-500"
                    data-testid="rut-funnel-legacy"
                  />
                  <span className="text-xs text-zinc-300">
                    <b>Legacy auto-fill</b> — built-in heuristic form filler (older offers)
                  </span>
                </label>
              </div>
            </div>

            {/* Custom Automation JSON */}
            <div className="pt-3 border-t border-emerald-900/30">
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input
                  type="checkbox"
                  checked={useCustomJson || funnelMode === "custom"}
                  onChange={(e) => {
                    const on = e.target.checked;
                    setUseCustomJson(on);
                    setFunnelMode(on ? "custom" : (funnelMode === "custom" ? "legacy" : funnelMode));
                  }}
                  disabled={funnelMode === "smart"}
                  className="w-4 h-4 accent-emerald-500 disabled:opacity-40"
                  data-testid="rut-use-custom-json"
                />
                <span className="text-zinc-200 text-sm font-medium">
                  🧩 Use Custom Automation JSON (for specific offer sites)
                </span>
              </label>
              <p className="text-xs text-zinc-500 mb-2 ml-6">
                Bypass the auto form-filler and run your own step-by-step script.
                Supports: <code className="text-zinc-400">click · fill · type · select · check · press · wait · wait_for_selector · scroll · evaluate · screenshot</code>.
                Placeholders: <code className="text-zinc-400">{"{{first}} {{email}} {{phone}} {{random.10}}"}</code>.
              </p>
              { (useCustomJson || funnelMode === "custom") && (
                <>
                  {/* Saved automation-json templates (Uploaded Things + VR handoff) */}
                  <div className="mb-2 p-2 bg-emerald-950/30 border border-emerald-900/50 rounded">
                    <Label className="text-emerald-300 text-xs mb-1 block">
                      Pick a <span className="font-semibold">saved automation template</span> (Uploaded Things — reusable, never deleted)
                    </Label>
                    {uploadedLibrary.filter(u => u.type === "automation_json").length > 0 ? (
                      <select
                        value={selectedUploadAjId}
                        onChange={(e) => setSelectedUploadAjId(e.target.value)}
                        className="w-full h-8 px-2 rounded bg-zinc-800 border border-zinc-700 text-zinc-100 text-xs"
                        data-testid="rut-upload-aj-id"
                      >
                        <option value="">— paste manually below —</option>
                        {uploadedLibrary.filter(u => u.type === "automation_json").map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.name} · {u.item_count} steps
                          </option>
                        ))}
                      </select>
                    ) : (
                      <p className="text-[11px] text-zinc-500">
                        No saved templates yet — record in Visual Recorder and click
                        {" "}<b>Use in RUT</b>, or save one under Uploaded Things → Automation JSON.
                      </p>
                    )}
                  </div>
                  <Textarea
                    data-testid="rut-automation-json"
                    rows={10}
                    placeholder={`{
  "steps": [
    {"action": "click", "selector": "a:has-text('UNLOCK NOW')", "wait_nav": true, "optional": true},
    {"action": "fill",  "selector": "input[name='first']",   "value": "{{first}}"},
    {"action": "fill",  "selector": "input[name='last']",    "value": "{{last}}"},
    {"action": "fill",  "selector": "input[name='email']",   "value": "{{email}}"},
    {"action": "fill",  "selector": "input[name='phone']",   "value": "{{cellphone}}"},
    {"action": "fill",  "selector": "input[name='zip']",     "value": "{{zip}}"},
    {"action": "select","selector": "select[name='dobmonth']","value": "{{month}}"},
    {"action": "select","selector": "select[name='dobday']", "value": "{{day}}"},
    {"action": "select","selector": "select[name='dobyear']","value": "{{year}}"},
    {"action": "click", "selector": "#submit-btn", "wait_nav": true}
  ]
}`}
                    value={automationJson}
                    onChange={(e) => setAutomationJson(e.target.value)}
                    disabled={!!selectedUploadAjId}
                    className="bg-zinc-950 border-zinc-700 text-zinc-100 font-mono text-xs disabled:opacity-50"
                  />
                  {selectedUploadAjId && (
                    <p className="text-xs text-emerald-400/70 mt-1">
                      Using saved template (template is NOT consumed — you can reuse it for future campaigns)
                    </p>
                  )}
                </>
              )}
              <p className="text-xs text-amber-400/70 mt-2 ml-6">
                💡 Aap koi bhi naya offer site bhejen (URL + brief kya karna hai) — main aapke liye exact JSON bana dunga, bas yahan paste karen.
              </p>

              {/* ── 2026-05: Pure JSON Mode toggle ── */}
              <label className="flex items-start gap-2 cursor-pointer mt-3 ml-6">
                <input
                  type="checkbox"
                  checked={pureJsonMode}
                  onChange={(e) => setPureJsonMode(e.target.checked)}
                  className="w-4 h-4 accent-sky-500 mt-0.5"
                  data-testid="rut-pure-json-mode"
                />
                <span className="text-xs text-zinc-300">
                  🎯 <b>Pure JSON Mode</b> (default <span className="text-sky-400">OFF</span>) — ON karenge to job <b>sirf recorded JSON</b> follow karegi, <span className="text-rose-400">koi AI involvement nahi</span> (self-heal force OFF + AI answer-learning bypass — survey picks purely random, koi outcome record nahi hoga). OFF rakhain to by-default behaviour: self-heal aur answer-learning aapke toggles ke hisab se chalenge.
                </span>
              </label>

              {/* Self-heal toggle */}
              <label className={`flex items-start gap-2 mt-3 ml-6 ${pureJsonMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}>
                <input
                  type="checkbox"
                  checked={selfHeal && !pureJsonMode}
                  disabled={pureJsonMode}
                  onChange={(e) => setSelfHeal(e.target.checked)}
                  className="w-4 h-4 accent-emerald-500 mt-0.5"
                  data-testid="rut-self-heal"
                />
                <span className="text-xs text-zinc-300">
                  🤖 <b>Smart self-heal</b> — agar runtime par koi unexpected popup / modal / cookie banner aa jaye,
                  Gemini 2.5 Pro screenshot dekh ke khud close/skip kar dega aur automation continue karega (up to 3 recoveries per lead).
                  {pureJsonMode && <span className="block text-sky-400 mt-1">⛔ Pure JSON Mode ON hone ki vajah se disabled.</span>}
                </span>
              </label>

              {/* Auto-resume toggle (default OFF) — added 2026-01 per user request */}
              <label className="flex items-start gap-2 cursor-pointer mt-3 ml-6">
                <input
                  type="checkbox"
                  checked={autoResumeEnabled}
                  onChange={(e) => setAutoResumeEnabled(e.target.checked)}
                  className="w-4 h-4 accent-orange-500 mt-0.5"
                  data-testid="rut-auto-resume"
                />
                <span className="text-xs text-zinc-300">
                  ⟳ <b>Auto-resume on backend restart</b> (default <span className="text-orange-400">OFF</span>) — agar backend kabhi restart ho mid-job, ON honay par job apne aap continue hogi (visits + counters preserve). OFF rakhain to job <span className="text-rose-400">failed</span> mark hogi aur aap manually "Retry" karein — predictable lifecycle, no surprise resumes.
                </span>
              </label>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ═══ 2026-06: Health Check (Preflight Trace) button ═══ */}
      {/* User ask (Roman Urdu): RUT job se PEHLE pehli visit ke har
          step ka short live trace — which selector matched, kis frame
          mein, kitna time laga. So if page structure changed overnight
          the operator catches it BEFORE wasting 200+ proxies/leads.
          No DB write, no job slot used. */}
      <Button
        data-testid="rut-health-check-btn"
        onClick={runHealthCheck}
        disabled={hcRunning || submitting}
        title="Validate the recording + URL on ONE browser. Returns per-step trace (timing, frame match, failure reason). Zero budget cost."
        className="w-full h-11 mb-2 text-sm font-medium bg-cyan-800 hover:bg-cyan-700 text-white border border-cyan-700/70"
      >
        {hcRunning ? (
          <>
            <RefreshCw className="animate-spin mr-2" size={16} /> Running Health Check…
          </>
        ) : (
          <>
            <Activity className="mr-2" size={16} />
            🩺 Run Health Check (per-step trace, no budget cost)
          </>
        )}
      </Button>

      {/* ═══ 2026-05: Pre-flight Smoke Test button ═══ */}
      {/* User ask (Roman Urdu): "Jab user 'Start RUT Job' daba k 1000
          visits k liye paisa kharchne wala ho, system pehle 1 visit ka
          smoke test chala k bataye recording sahi hai ya nahi". This
          button reuses the SAME form/backend with smoke_test=true. */}
      <Button
        data-testid="rut-smoke-test-btn"
        onClick={() => onStart({ smokeTest: true })}
        disabled={submitting}
        title="Run ONE validation visit first to catch broken recordings before spending your full budget"
        className="w-full h-11 mb-2 text-sm font-medium bg-amber-700 hover:bg-amber-600 text-white border border-amber-600/70"
      >
        {submitting ? (
          <>
            <RefreshCw className="animate-spin mr-2" size={16} /> Starting smoke test…
          </>
        ) : (
          <>
            <ClipboardCheck className="mr-2" size={16} />
            Pre-flight Smoke Test (1 visit) — Recommended
          </>
        )}
      </Button>

      {/* ═══ Big red START button ═══ */}
      <Button
        data-testid="rut-start-btn"
        onClick={() => onStart()}
        disabled={submitting}
        className="w-full h-14 text-lg font-semibold bg-red-600 hover:bg-red-700 text-white border border-red-500"
      >
        {submitting ? (
          <>
            <RefreshCw className="animate-spin mr-2" size={20} /> Starting…
          </>
        ) : (
          <>
            <Play className="mr-2" size={20} />
            {targetMode === "conversions"
              ? `Run until ${targetConversions} Conversions (max ${maxAttempts} attempts)`
              : `Send ${totalClicks} Real ${formFillEnabled ? "Visits with Auto-Fill" : "Clicks"}`}
          </>
        )}
      </Button>

      {/* ═══ Live Run panel ═══ */}
      {activeJob && (
        <Card className="bg-zinc-900 border-fuchsia-900/50">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              Live Run <StatusBadge status={activeJob.status} />
            </CardTitle>
            <CardDescription className="text-zinc-400 font-mono text-xs break-all">
              target: {activeJob.target_url}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {/* 2026-05 — Smoke-test result banner. Renders when activeJob
                was started via the Pre-flight Smoke Test button. Three
                states: running (1 visit in progress), passed, failed.
                On pass, surfaces a "Start Full Job" button that calls
                onStart() again with the user's ORIGINAL totalClicks. */}
            {activeJob.smoke_test && (
              <div
                data-testid="rut-smoke-test-result"
                className={`mb-4 rounded-lg border px-4 py-3 ${
                  activeJob.status === "completed"
                    ? "border-emerald-900/60 bg-emerald-950/40"
                    : activeJob.status === "failed" || activeJob.status === "stopped"
                    ? "border-rose-900/60 bg-rose-950/40"
                    : "border-amber-900/60 bg-amber-950/30"
                }`}
              >
                <div className="flex items-start gap-3">
                  <ClipboardCheck className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                    activeJob.status === "completed" ? "text-emerald-300" :
                    activeJob.status === "failed" || activeJob.status === "stopped" ? "text-rose-300" :
                    "text-amber-300"
                  }`} />
                  <div className="flex-1 min-w-0">
                    <div className={`text-sm font-semibold ${
                      activeJob.status === "completed" ? "text-emerald-100" :
                      activeJob.status === "failed" || activeJob.status === "stopped" ? "text-rose-100" :
                      "text-amber-100"
                    }`}>
                      {activeJob.status === "completed"
                        ? "Smoke test PASSED — recording, proxies and form-fill all look good."
                        : activeJob.status === "failed" || activeJob.status === "stopped"
                        ? `Smoke test FAILED${activeJob.processed > 0 ? " — visit completed but didn't reach conversion page" : " — visit could not finish"}.`
                        : "Smoke test running — validating 1 visit before full job…"}
                    </div>
                    <div className="text-xs text-zinc-400 mt-1">
                      {activeJob.status === "completed"
                        ? `Click below to launch your full run with the original settings (${totalClicks} ${formFillEnabled ? "visits" : "clicks"}, concurrency ${concurrency}).`
                        : activeJob.status === "failed" || activeJob.status === "stopped"
                        ? "Fix the failing step (see Live Activity below) BEFORE running the full job — this saves the proxies + leads you would have wasted on 1000 broken visits."
                        : "This validation visit costs only 1 proxy + 1 lead. Full job spawns only on your confirmation."}
                    </div>
                    {(activeJob.status === "completed" || activeJob.status === "failed" || activeJob.status === "stopped") && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {activeJob.status === "completed" && (
                          <Button
                            data-testid="rut-smoke-test-start-full-btn"
                            size="sm"
                            onClick={() => onStart()}
                            disabled={submitting}
                            className="bg-emerald-700 hover:bg-emerald-600 text-white"
                          >
                            <Play className="mr-1.5" size={14} />
                            Start Full Job ({targetMode === "conversions" ? `${targetConversions} conv` : `${totalClicks} clicks`})
                          </Button>
                        )}
                        {(activeJob.status === "failed" || activeJob.status === "stopped") && (
                          <>
                            <Button
                              data-testid="rut-smoke-test-retry-btn"
                              size="sm"
                              onClick={() => onStart({ smokeTest: true })}
                              disabled={submitting}
                              className="bg-amber-700 hover:bg-amber-600 text-white"
                            >
                              <RefreshCw className="mr-1.5" size={14} />
                              Retry Smoke Test
                            </Button>
                            <Button
                              data-testid="rut-smoke-test-force-full-btn"
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                if (window.confirm(
                                  "Smoke test failed. Are you SURE you want to run the full job anyway? " +
                                  "Most of the visits will likely fail in the same way."
                                )) {
                                  onStart();
                                }
                              }}
                              disabled={submitting}
                              className="bg-transparent text-rose-200 border-rose-800/60 hover:bg-rose-900/30"
                            >
                              Force-start Full Job anyway
                            </Button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Prep-step indicator — shows what the BG task is currently
                doing while the job is in queued/preparing state. Without
                this, users stare at "queued" with zero feedback during
                the 5-30s prep phase. */}
            {(activeJob.status === "queued" || activeJob.status === "preparing") && activeJob.prep_step && (
              <div data-testid="rut-job-prep-step" className="mb-4 rounded-lg border border-blue-900/60 bg-blue-950/30 px-4 py-3 flex items-center gap-3">
                <RefreshCw className="w-4 h-4 text-blue-400 animate-spin flex-shrink-0" />
                <div className="text-sm text-blue-200">
                  <span className="font-semibold">Preparing:</span> {activeJob.prep_step}
                </div>
              </div>
            )}
            {/* Show error/diagnosis banner — covers BOTH "failed" jobs
                (with error_message) AND "stopped" jobs that produced
                zero visits (where the new engine self-diagnosis fills
                in `diagnosis` to explain WHY it ended early). Without
                this, users only see a "failed/stopped" badge with no
                detail. */}
            {(activeJob.status === "failed" || activeJob.status === "stopped" || activeJob.status === "running" || activeJob.status === "queued") && (activeJob.error || activeJob.error_message || activeJob.diagnosis || activeJob.stop_reason) && (
              <div
                data-testid="rut-job-error-banner"
                className={`mb-4 rounded-lg border px-4 py-3 flex items-start gap-3 ${
                  activeJob.status === "failed"
                    ? "border-red-900/60 bg-red-950/40"
                    : "border-amber-900/60 bg-amber-950/30"
                }`}
              >
                <AlertTriangle className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                  activeJob.status === "failed" ? "text-red-400" : "text-amber-400"
                }`} />
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-semibold mb-1 ${
                    activeJob.status === "failed" ? "text-red-300" : "text-amber-300"
                  }`}>
                    {activeJob.status === "failed"
                      ? "Job failed"
                      : activeJob.status === "stopped"
                      ? "Job stopped — diagnosis"
                      : "Job status note"}
                  </div>
                  <div className={`text-sm break-words whitespace-pre-wrap ${
                    activeJob.status === "failed" ? "text-red-200" : "text-amber-200"
                  }`}>
                    {activeJob.error || activeJob.error_message || activeJob.diagnosis || activeJob.stop_reason}
                  </div>
                  {activeJob.status === "stopped" && (activeJob.diagnosis || activeJob.stop_reason) && (
                    <div className="mt-2 text-xs text-amber-300/80">
                      Tip: hit <code className="bg-amber-900/40 px-1 rounded">/api/diagnostics/health</code> on your backend to see if Mongo, Playwright, GSheet SA and memory are all green.
                    </div>
                  )}
                  {/* Resume / Retry button — appears on failed/stopped jobs
                      that have persisted submit_params (the source of
                      truth for resumability), OR on queued/preparing
                      jobs that appear stuck (let the user force-resume
                      instead of waiting for the auto-resume to give up).
                      The endpoint preserves processed/succeeded/skipped
                      counters — engine continues from `prev_processed`. */}
                  {(activeJob.status === "failed" || activeJob.status === "stopped" || activeJob.status === "queued" || activeJob.status === "preparing") && activeJob.job_id && (
                    <button
                      data-testid="rut-job-retry-btn"
                      onClick={async () => {
                        try {
                          const r = await fetch(`${API_URL}/api/real-user-traffic/jobs/${activeJob.job_id}/retry`, {
                            method: "POST",
                            headers: authH(),
                          });
                          const d = await r.json();
                          if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
                          const _doneAlready = Number(activeJob.processed || 0);
                          toast.success(_doneAlready > 0
                            ? `Resuming from visit #${_doneAlready + 1} (${_doneAlready} already done)`
                            : "Job re-queued — preparing now");
                          await loadJobs();
                          setActiveJob(null);
                        } catch (e) {
                          toast.error(`Resume failed: ${e.message || e}`);
                        }
                      }}
                      className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-700/40 hover:bg-emerald-700/60 border border-emerald-500/40 text-emerald-200 text-sm font-medium transition-colors"
                    >
                      <RefreshCw className="w-4 h-4" />
                      {(activeJob.status === "queued" || activeJob.status === "preparing")
                        ? "Force restart job"
                        : (Number(activeJob.processed || 0) > 0
                            ? `▶ Resume from visit #${Number(activeJob.processed || 0) + 1}`
                            : "Retry this job")}
                    </button>
                  )}
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 md:grid-cols-8 gap-3 mb-4">
              <Stat label="Total" value={activeJob.total ?? 0} />
              <Stat label="Processed" value={activeJob.processed ?? 0} />
              <Stat label="Succeeded" value={activeJob.succeeded ?? 0} color="emerald" />
              <Stat
                label={activeJob.target_mode === "conversions" ? `Conversions (${activeJob.conversions ?? 0}/${activeJob.target_conversions ?? "?"})` : "Conversions"}
                value={activeJob.conversions ?? 0}
                color="fuchsia"
                data-testid="rut-conversions-stat"
              />
              <Stat
                label="Skipped"
                value={(activeJob.skipped_captcha ?? 0) + (activeJob.skipped_country ?? 0) + (activeJob.skipped_os ?? 0) + (activeJob.skipped_duplicate_ip ?? 0) + (activeJob.skipped_vpn ?? 0) + (activeJob.skipped_state_mismatch ?? 0)}
                color="amber"
                data-testid="rut-skipped-total"
              />
              <Stat label="Invalid Data" value={activeJob.invalid_data ?? 0} color="red" data-testid="rut-invalid-stat" />
              <Stat label="Failed" value={activeJob.failed ?? 0} color="red" />
              <Stat label="Leads Left" value={activeJob.leftover_leads_count ?? "—"} color="emerald" data-testid="rut-leads-left-stat" />
            </div>
            <div className="border border-zinc-800 rounded-lg overflow-hidden">
              <div className="bg-zinc-950 text-zinc-400 text-xs font-semibold px-3 py-2 uppercase tracking-wide">
                Recent Visits
              </div>
              <div className="max-h-80 overflow-y-auto divide-y divide-zinc-800">
                {(activeJob.events || []).slice().reverse().map((ev, i) => (
                  <div key={i} className="px-3 py-2 text-sm flex items-center gap-3">
                    <span className="text-zinc-500 w-10 text-right">#{ev.row}</span>
                    <StatusBadge status={ev.status} />
                    <span className="text-zinc-400 font-mono text-xs">{ev.exit_ip || "?"}</span>
                    <span className="text-zinc-500 text-xs">{ev.city}, {ev.country}</span>
                    <span className="text-zinc-300 text-xs hidden md:inline">{ev.device}</span>
                    {ev.error && <span className="text-red-400 text-xs truncate ml-auto">{ev.error}</span>}
                  </div>
                ))}
                {(!activeJob.events || activeJob.events.length === 0) && (
                  <div className="px-3 py-6 text-center text-zinc-500 text-sm">Waiting for first visit…</div>
                )}
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              {activeJob.is_draining && (
                <div
                  className="flex items-center gap-2 px-3 py-1.5 rounded border text-sm"
                  style={{
                    backgroundColor: "rgba(245, 158, 11, 0.10)",
                    borderColor: "rgba(245, 158, 11, 0.40)",
                    color: "rgb(252, 211, 77)",
                  }}
                  title="Target reached. The dispatcher has stopped spawning new visits. In-flight visits will run to completion so the proxies/UAs/leads they already picked up aren't wasted."
                  data-testid="rut-draining-badge"
                >
                  <span className="text-base leading-none">🎯</span>
                  <span className="font-medium">Target reached — draining in-flight visits…</span>
                </div>
              )}
              {(activeJob.status === "running" || activeJob.status === "queued" || activeJob.status === "preparing") && (
                <>
                  <Button
                    data-testid="rut-stop-active"
                    onClick={() => onStop(activeJob.job_id)}
                    className="bg-orange-600 hover:bg-orange-700 text-white"
                  >
                    <StopCircle size={16} className="mr-2" /> Stop Now & Package Partial Results
                  </Button>
                  <Button
                    data-testid="rut-live-activity-btn"
                    onClick={openLiveModal}
                    variant="outline"
                    className="bg-zinc-800 border-fuchsia-700 text-fuchsia-200 hover:bg-fuchsia-950"
                  >
                    <Activity size={16} className="mr-2" /> Show Live Activity
                  </Button>
                  <Button
                    data-testid="rut-visual-grid-btn"
                    onClick={openVisualGrid}
                    variant="outline"
                    className="bg-zinc-800 border-blue-700 text-blue-200 hover:bg-blue-950"
                    title="Real-time grid of all concurrent visits — see each browser session live"
                  >
                    <Activity size={16} className="mr-2" /> Live Visual Grid
                  </Button>
                  <Button
                    data-testid="rut-show-diagnostics-btn"
                    onClick={openDiagnostics}
                    variant="outline"
                    className="bg-zinc-800 border-amber-700 text-amber-200 hover:bg-amber-950"
                    title="Show macro-leak blocks + stuck-visit events for this job"
                  >
                    <AlertTriangle size={16} className="mr-2" /> Diagnostics
                  </Button>
                </>
              )}
              {(activeJob.status === "completed" || activeJob.status === "stopped") && (
                <>
                  <Button
                    data-testid="rut-download-active"
                    onClick={() => onDownload(activeJob.job_id)}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  >
                    <Download size={16} className="mr-2" /> Download Results ZIP
                    {activeJob.status === "stopped" ? " (Partial)" : ""}
                  </Button>
                  {activeJob.form_fill_enabled && (
                    <Button
                      data-testid="rut-download-pending-leads-active"
                      onClick={() => onDownloadPendingLeads(activeJob.job_id)}
                      className="bg-amber-600 hover:bg-amber-700 text-white"
                      title="Excel with only the leads that haven't been used yet (used + invalid removed). Re-upload as next run's data."
                    >
                      <Download size={16} className="mr-2" /> Pending Leads
                      {typeof activeJob.leftover_leads_count === "number" ? ` (${activeJob.leftover_leads_count})` : ""}
                    </Button>
                  )}
                  <Button
                    data-testid="rut-show-diagnostics-completed-btn"
                    onClick={openDiagnostics}
                    variant="outline"
                    className="bg-zinc-800 border-amber-700 text-amber-200 hover:bg-amber-950"
                    title="Show macro-leak blocks + stuck-visit events for this job"
                  >
                    <AlertTriangle size={16} className="mr-2" /> Diagnostics
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ═══ Past jobs ═══ */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-white">Past Jobs</CardTitle>
            <CardDescription className="text-zinc-400">
              Latest runs — auto-refreshes while running
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {selectedJobIds.size > 0 && (
              <Button
                size="sm"
                onClick={onBulkDelete}
                data-testid="rut-bulk-delete-btn"
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                <Trash2 size={14} className="mr-1" /> Delete Selected ({selectedJobIds.size})
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={fetchJobs} className="bg-zinc-800 border-zinc-700 text-zinc-200">
              <RefreshCw size={14} className="mr-1" /> Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            bridgePending ? (
              <p className="text-blue-300 text-sm text-center py-6" data-testid="rut-past-jobs-bridge-loading">
                <RefreshCw size={14} className="inline mr-2 animate-spin" />
                Loading jobs from your PC… <span className="text-zinc-500">(auto-refreshing — your desktop is responding)</span>
              </p>
            ) : (
              <p className="text-zinc-500 text-sm text-center py-6">
                No jobs yet — start one above 👆
              </p>
            )
          ) : (
            <div className="border border-zinc-800 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-zinc-950 text-zinc-400">
                  <tr>
                    <th className="px-3 py-2 text-left">
                      <input
                        type="checkbox"
                        checked={selectedJobIds.size === jobs.length && jobs.length > 0}
                        onChange={toggleSelectAll}
                        className="w-4 h-4 accent-fuchsia-500 cursor-pointer"
                        data-testid="rut-select-all"
                      />
                    </th>
                    <th className="px-3 py-2 text-left font-semibold">Job</th>
                    <th className="px-3 py-2 text-left font-semibold">Status</th>
                    <th className="px-3 py-2 text-left font-semibold">Progress</th>
                    <th className="px-3 py-2 text-left font-semibold">Created</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {jobs.map((j) => {
                    const checked = selectedJobIds.has(j.job_id);
                    return (
                    <tr key={j.job_id} className={`hover:bg-zinc-800/50 ${checked ? "bg-fuchsia-950/20" : ""}`}>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleJobSelected(j.job_id)}
                          className="w-4 h-4 accent-fuchsia-500 cursor-pointer"
                          data-testid={`rut-select-${j.job_id}`}
                        />
                      </td>
                      <td className="px-3 py-2 text-zinc-300 font-mono text-xs">{j.job_id.slice(0, 8)}</td>
                      <td className="px-3 py-2"><StatusBadge status={j.status} /></td>
                      <td className="px-3 py-2 text-zinc-400 text-xs">
                        {j.processed || 0} / {j.total || 0}
                        {j.succeeded ? <span className="text-emerald-400 ml-2"><CheckCircle2 size={12} className="inline" /> {j.succeeded}</span> : null}
                        {j.conversions ? <span className="text-fuchsia-400 ml-2">🎯 {j.conversions}</span> : null}
                        {j.failed ? <span className="text-red-400 ml-2"><XCircle size={12} className="inline" /> {j.failed}</span> : null}
                      </td>
                      <td className="px-3 py-2 text-zinc-500 text-xs">{j.created_at ? new Date(j.created_at).toLocaleString() : ""}</td>
                      <td className="px-3 py-2 text-right space-x-1 whitespace-nowrap">
                        <Button size="sm" variant="outline" onClick={() => startPolling(j.job_id)} className="bg-zinc-800 border-zinc-700 text-zinc-200">View</Button>
                        {(j.status === "running" || j.status === "queued" || j.status === "preparing") && (
                          <Button
                            size="sm"
                            onClick={() => onStop(j.job_id)}
                            title="Stop"
                            className="bg-orange-600 hover:bg-orange-700 text-white"
                            data-testid={`rut-stop-${j.job_id}`}
                          >
                            <StopCircle size={12} />
                          </Button>
                        )}
                        {(j.status === "completed" || j.status === "stopped") && (
                          <>
                            <Button size="sm" onClick={() => onDownload(j.job_id)} className="bg-emerald-600 hover:bg-emerald-700 text-white" title="Download full results ZIP"><Download size={12} /></Button>
                            {j.form_fill_enabled && (
                              <Button
                                size="sm"
                                onClick={() => onDownloadPendingLeads(j.job_id)}
                                className="bg-amber-600 hover:bg-amber-700 text-white"
                                title="Download pending leads (unused rows only, re-uploadable)"
                                data-testid={`rut-download-pending-${j.job_id}`}
                              >
                                <Download size={12} />
                                <span className="ml-1 text-[10px] font-bold">LEADS</span>
                              </Button>
                            )}
                          </>
                        )}
                        <Button size="sm" variant="outline" onClick={() => onDelete(j.job_id)} className="bg-red-900/40 border-red-800 text-red-200 hover:bg-red-900/60"><Trash2 size={12} /></Button>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ═══ 2026-06: Health Check Result Modal ═══ */}
      {hcModalOpen && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          data-testid="rut-hc-modal"
          onClick={(e) => { if (e.target === e.currentTarget && !hcRunning) setHcModalOpen(false); }}
        >
          <div className="bg-zinc-950 border border-cyan-900/60 rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Activity size={18} className={hcRunning ? "text-cyan-400 animate-pulse" : (hcResult?.ok ? "text-emerald-400" : "text-rose-400")} />
                <h3 className="text-white font-semibold">
                  🩺 Health Check {hcRunning ? "— running…" : (hcResult ? (hcResult.ok ? "— PASSED" : "— FAILED") : "")}
                </h3>
              </div>
              <button
                onClick={() => !hcRunning && setHcModalOpen(false)}
                disabled={hcRunning}
                className="text-zinc-400 hover:text-white p-1 rounded disabled:opacity-30"
                data-testid="rut-hc-modal-close"
                aria-label="Close health check"
              >
                <X size={20} />
              </button>
            </div>

            {/* Summary bar */}
            <div className={`px-5 py-3 border-b border-zinc-800 text-xs ${
              hcRunning ? "bg-cyan-950/30" :
              hcResult?.ok ? "bg-emerald-950/30" :
              hcResult ? "bg-rose-950/30" : ""
            }`}>
              {hcRunning ? (
                <div className="flex items-center gap-2 text-cyan-200">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Opening browser, running steps… (typically 10–60s).</span>
                </div>
              ) : hcResult ? (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span className={hcResult.ok ? "text-emerald-300 font-semibold" : "text-rose-300 font-semibold"}>
                    {hcResult.ok ? "✓ All steps OK" : `✗ Step ${(hcResult.failed_at_idx ?? -1) + 1} failed`}
                  </span>
                  <span className="text-zinc-400">
                    {hcResult.executed_steps}/{hcResult.total_steps} steps · {((hcResult.duration_ms || 0) / 1000).toFixed(1)}s
                  </span>
                  {hcResult.final_url && (
                    <span className="text-zinc-500 truncate" title={hcResult.final_url}>
                      final: <span className="font-mono text-zinc-300">{hcResult.final_url.slice(0, 60)}{hcResult.final_url.length > 60 ? "…" : ""}</span>
                    </span>
                  )}
                  {hcResult.proxy_used && <span className="text-amber-300">⚡ via proxy</span>}
                </div>
              ) : null}
              {hcResult?.error && (
                <div className="mt-2 text-rose-300 text-[11px] font-mono whitespace-pre-wrap break-words">
                  {hcResult.error.slice(0, 400)}
                </div>
              )}
            </div>

            {/* Step trace table */}
            <div className="flex-1 overflow-y-auto p-3 text-xs" data-testid="rut-hc-modal-body">
              {hcRunning && (!hcResult || !hcResult.step_results?.length) ? (
                <div className="text-center text-zinc-500 py-10">
                  Waiting for the first step result…
                </div>
              ) : !hcResult?.step_results?.length ? (
                <div className="text-center text-zinc-500 py-10">No step results.</div>
              ) : (
                <div className="space-y-1.5">
                  {hcResult.step_results.map((s, i) => {
                    const ok = s.ok !== false;
                    const isFail = s.ok === false;
                    return (
                      <div
                        key={i}
                        className={`rounded-md border px-3 py-2 ${
                          isFail
                            ? "border-rose-800/60 bg-rose-950/30"
                            : "border-zinc-800 bg-zinc-900/50"
                        }`}
                        data-testid={`rut-hc-step-${i}`}
                      >
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold ${
                            isFail ? "bg-rose-700 text-rose-50" : "bg-emerald-700 text-emerald-50"
                          }`}>
                            {ok && !isFail ? "✓" : "✗"}
                          </span>
                          <span className="text-zinc-200 font-mono font-medium">
                            #{(s.idx ?? i) + 1} {s.action}
                          </span>
                          {s.selector && (
                            <span className="text-zinc-500 font-mono text-[10px] truncate max-w-[300px]" title={s.selector}>
                              {s.selector}
                            </span>
                          )}
                          {s.optional && (
                            <span className="text-amber-300/80 text-[9px] uppercase tracking-wide">optional</span>
                          )}
                          <span className="ml-auto text-zinc-400 font-mono text-[10px]">
                            {s.ms != null ? `${s.ms} ms` : ""}
                          </span>
                        </div>
                        {s.note && (
                          <div className="mt-1 ml-7 text-cyan-300/90 text-[11px] break-words">
                            {s.note}
                          </div>
                        )}
                        {isFail && s.error && (
                          <div className="mt-1 ml-7 text-rose-300 text-[11px] font-mono whitespace-pre-wrap break-words">
                            {String(s.error).slice(0, 300)}
                          </div>
                        )}
                        {isFail && s.friendly_hint && (
                          <div className="mt-1 ml-7 text-amber-300 text-[11px]">
                            💡 {s.friendly_hint}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer actions */}
            <div className="px-5 py-3 border-t border-zinc-800 flex items-center justify-between gap-2 flex-wrap">
              <div className="text-[11px] text-zinc-500">
                Zero budget cost — no DB row, no proxy used (unless overridden), no leads consumed.
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={runHealthCheck}
                  disabled={hcRunning}
                  className="text-cyan-200 border-cyan-800/60 hover:bg-cyan-900/30"
                  data-testid="rut-hc-rerun-btn"
                >
                  <RefreshCw className={`mr-1.5 ${hcRunning ? "animate-spin" : ""}`} size={13} />
                  Re-run
                </Button>
                <Button
                  size="sm"
                  onClick={() => setHcModalOpen(false)}
                  disabled={hcRunning}
                  className="bg-zinc-800 hover:bg-zinc-700 text-white"
                  data-testid="rut-hc-close-btn"
                >
                  Close
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ═══ Live Activity Modal ═══ */}
      {liveModalOpen && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          data-testid="rut-live-modal"
        >
          <div className="bg-zinc-950 border border-fuchsia-900/50 rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Activity size={18} className="text-fuchsia-400 animate-pulse" />
                <h3 className="text-white font-semibold">Live Activity — what backend is doing right now</h3>
              </div>
              <button
                onClick={closeLiveModal}
                className="text-zinc-400 hover:text-white p-1 rounded"
                data-testid="rut-live-modal-close"
                aria-label="Close live activity"
              >
                <X size={20} />
              </button>
            </div>
            <div className="px-5 py-3 border-b border-zinc-800 text-xs text-zinc-400 flex items-center justify-between">
              <span>
                Polling every 1.5s · auto-stops when job finishes · steps: <span className="text-zinc-200 font-mono">{liveSteps.length}</span>
              </span>
              <span className="text-zinc-500">Thumbnails are real browser screenshots — click to enlarge.</span>
            </div>
            <div
              className="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-1"
              data-testid="rut-live-modal-body"
            >
              {liveSteps.length === 0 ? (
                <div className="text-center text-zinc-500 py-10">
                  Waiting for the next backend step…
                </div>
              ) : (
                liveSteps.map((s) => {
                  const colorMap = {
                    ok: "text-emerald-300",
                    info: "text-zinc-200",
                    skipped: "text-amber-300",
                    failed: "text-rose-300",
                  };
                  const stageTagColor = {
                    setup: "bg-zinc-800 text-zinc-200",
                    geo: "bg-blue-900/50 text-blue-200",
                    filter: "bg-amber-900/50 text-amber-200",
                    browser: "bg-indigo-900/50 text-indigo-200",
                    landing: "bg-cyan-900/50 text-cyan-200",
                    form: "bg-fuchsia-900/50 text-fuchsia-200",
                    form_filled: "bg-pink-900/50 text-pink-200",
                    submit: "bg-violet-900/50 text-violet-200",
                    post_submit: "bg-purple-900/50 text-purple-200",
                    final: "bg-emerald-900/50 text-emerald-200",
                    done: "bg-emerald-900/50 text-emerald-200",
                  };
                  // If this step has a screenshot, build a secured URL with the auth token.
                  const shotSrc = s.screenshot
                    ? `${API_URL}/api/real-user-traffic/jobs/${activeJob?.job_id}/screenshot/${encodeURIComponent(s.screenshot)}?t=${encodeURIComponent(token())}`
                    : null;
                  return (
                    <div key={s.idx} className="flex gap-2 items-start">
                      <span className="text-zinc-600 w-16 text-right shrink-0 pt-0.5">
                        #{String(s.visit).padStart(3, "0")}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold shrink-0 mt-0.5 ${stageTagColor[s.stage] || "bg-zinc-800 text-zinc-200"}`}>
                        {s.stage}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className={`${colorMap[s.status] || "text-zinc-200"} leading-snug break-words`}>
                          {s.detail}
                        </div>
                        {shotSrc && (
                          <button
                            type="button"
                            onClick={() => setPreviewShot(shotSrc)}
                            className="mt-1 block rounded-md overflow-hidden border border-zinc-800 hover:border-fuchsia-500 transition-colors"
                            data-testid={`rut-live-thumb-${s.idx}`}
                            title="Click to enlarge"
                          >
                            <img
                              src={shotSrc}
                              alt={`visit ${s.visit} ${s.stage}`}
                              loading="lazy"
                              className="max-h-28 w-auto block"
                            />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══ 2026-01: Visual Live Grid — per-visit browser tiles ═══ */}
      {visualGridOpen && (
        <div
          className={`fixed z-40 ${visualGridMinimized
            ? 'bottom-3 right-3 w-72 h-12'
            : 'inset-3 bg-black/85 backdrop-blur-sm flex flex-col'}`}
          data-testid="rut-visual-grid-modal"
        >
          {visualGridMinimized ? (
            <button
              onClick={() => setVisualGridMinimized(false)}
              className="w-full h-full flex items-center justify-between px-3 rounded-lg bg-blue-900 hover:bg-blue-800 border border-blue-500 text-white text-sm shadow-2xl"
              data-testid="rut-visual-grid-restore"
            >
              <span className="flex items-center gap-2">
                <Activity size={14} className="animate-pulse" />
                Live Grid ({Object.values(liveVisits).filter(isVisitActive).length} visits)
              </span>
              <span className="text-xs opacity-70">▴ click to expand</span>
            </button>
          ) : (
            <div className="flex-1 flex flex-col bg-zinc-950 border border-blue-900/50 rounded-xl overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-800 flex-shrink-0">
                <div className="flex items-center gap-2">
                  <Activity size={18} className="text-blue-400 animate-pulse" />
                  <h3 className="text-white font-semibold">
                    Live Visual Grid —
                    <span className="text-blue-300 ml-1">
                      {Object.values(liveVisits).filter(isVisitActive).length}
                    </span>
                    <span className="text-zinc-500 text-sm font-normal ml-1">
                      / {activeJob?.concurrency || activeJob?.total || '?'} concurrent visits
                    </span>
                    {showFailedVisits && Object.values(liveVisits).filter(v => v && (v.status === 'failed' || v.status === 'cancelled')).length > 0 && (
                      <span className="text-rose-400 text-sm font-normal ml-2">
                        + {Object.values(liveVisits).filter(v => v && (v.status === 'failed' || v.status === 'cancelled')).length} failed/cancelled
                      </span>
                    )}
                  </h3>
                </div>
                <div className="flex items-center gap-1">
                  {/* v2.6.1 — Show/Hide Failed Visits toggle (Task 5).
                      When ON, failed / cancelled visits stay pinned in
                      the grid (with red border + error tooltip) so the
                      operator can see WHAT went wrong. When OFF, tiles
                      vanish the moment they fail (original behaviour). */}
                  <button
                    onClick={() => setShowFailedVisits((v) => !v)}
                    className={`px-2 py-1 text-xs rounded transition-colors mr-1 ${
                      showFailedVisits
                        ? 'bg-rose-900/60 text-rose-200 hover:bg-rose-800/70'
                        : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
                    }`}
                    title={showFailedVisits
                      ? 'Failed/cancelled visits stay visible in red — click to hide them'
                      : 'Show failed/cancelled visits in red (so you can see the error)'}
                    data-testid="rut-visual-grid-toggle-failed"
                  >
                    {showFailedVisits ? '⚠ Failed ON' : '⚠ Failed'}
                  </button>
                  {/* 2026-05 — Show Step Markers toggle. When ON, the
                      tile renders coloured dots at each step's target
                      position on the full-page screenshot. */}
                  <button
                    onClick={() => setShowStepMarkers((v) => !v)}
                    className={`px-2 py-1 text-xs rounded transition-colors mr-1 ${
                      showStepMarkers
                        ? 'bg-emerald-900/60 text-emerald-200 hover:bg-emerald-800/70'
                        : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
                    }`}
                    title={showStepMarkers
                      ? 'Hide per-step marker dots overlaid on the page'
                      : 'Show per-step marker dots overlaid on the page (coloured by step status)'}
                    data-testid="rut-visual-grid-toggle-step-markers"
                  >
                    {showStepMarkers ? '⊙ Step Markers ON' : '⊙ Step Markers'}
                  </button>
                  <button
                    onClick={() => setVisualGridMinimized(true)}
                    className="px-2 py-1 text-zinc-400 hover:text-white text-xs rounded hover:bg-zinc-800"
                    title="Minimize (keeps polling)"
                    data-testid="rut-visual-grid-minimize"
                  >
                    ▾ Minimize
                  </button>
                  <button
                    onClick={closeVisualGrid}
                    className="text-zinc-400 hover:text-white p-1 rounded"
                    title="Close (stops polling)"
                    data-testid="rut-visual-grid-close"
                  >
                    <X size={20} />
                  </button>
                </div>
              </div>
              {/* Sub-header info */}
              <div className="px-4 py-2 border-b border-zinc-800 text-xs text-zinc-400 flex items-center gap-3 flex-shrink-0">
                <span>Polling every 800ms · live browser frames</span>
                <span className="text-zinc-600">·</span>
                <span>
                  {/* 2026-06-27 BUGFIX — Same root cause as isVisitActive:
                      `latest_event.status` is per-STEP, not per-visit. Use
                      v.status (visit-level) or stage==='done' for the ✓
                      counter, and v.status === 'failed' for the ✗ counter.
                      The ⏵ "in-flight" counter is just `isVisitActive`. */}
                  Tiles: <span className="text-emerald-300 font-mono">{Object.values(liveVisits).filter(v => v && (v.status === 'ok' || v.status === 'done' || (v.latest_event?.stage === 'done' && v.latest_event?.status === 'ok'))).length}✓</span>
                  {' '}
                  <span className="text-rose-300 font-mono">{Object.values(liveVisits).filter(v => v && v.status === 'failed').length}✗</span>
                  {' '}
                  <span className="text-blue-300 font-mono">{Object.values(liveVisits).filter(isVisitActive).length}⏵</span>
                </span>
                <span className="text-zinc-600">·</span>
                <span>Click any tile to expand</span>
              </div>
              {/* Grid body */}
              <div className="flex-1 overflow-y-auto p-3" data-testid="rut-visual-grid-body">
                {Object.values(liveVisits).filter(isVisitVisible).length === 0 ? (
                  <div className="text-center text-zinc-500 py-20">
                    <Loader2 className="w-8 h-8 animate-spin inline-block mb-2" />
                    <div>Waiting for first visit to start…</div>
                    <div className="text-xs text-zinc-600 mt-1">
                      Live frames begin streaming the moment a visit&apos;s browser opens.
                    </div>
                  </div>
                ) : (
                  <div className="grid gap-3" style={{
                    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                  }}>
                    {Object.entries(liveVisits)
                      .filter(([, v]) => isVisitVisible(v))
                      .sort(([a], [b]) => parseInt(a, 10) - parseInt(b, 10))
                      .map(([vid, v]) => {
                        const ev = v.latest_event || {};
                        const status = ev.status || v.status || 'running';
                        const isCancelled = v.status === 'cancelled' || ev.stage === 'manual_cancel';
                        const isExpanded = expandedVisit === vid;
                        const borderColor =
                          isCancelled ? 'border-zinc-600/60' :
                          status === 'ok' ? 'border-emerald-500/60' :
                          status === 'failed' ? 'border-rose-500/60' :
                          'border-blue-500/60';
                        const badgeColor =
                          isCancelled ? 'bg-zinc-800/90 text-zinc-300' :
                          status === 'ok' ? 'bg-emerald-900/90 text-emerald-200' :
                          status === 'failed' ? 'bg-rose-900/90 text-rose-200' :
                          'bg-blue-900/90 text-blue-200';
                        // 2026-01: support BOTH event shapes:
                        //  (a) automation_steps callback → action, selector, idx, ms
                        //  (b) push_live_step mirror     → stage, status, detail
                        // 2026-05 — append elapsed-s suffix from the
                        // heartbeat. Shows "step #13 · wait (18s)" so the
                        // operator can see live progress instead of a
                        // frozen-looking tile during slow steps.
                        const _elap = ev.elapsed_s;
                        const _elap_suffix = (typeof _elap === 'number' && _elap >= 6)
                          ? ` (${_elap}s)`
                          : '';
                        const descr = ev.action
                          ? `step #${(ev.idx ?? 0) + 1} · ${ev.action}${ev.selector ? ' ' + ev.selector.slice(0, 30) : ''}${_elap_suffix}`
                          : ev.stage
                          ? `${ev.stage} · ${(ev.detail || '').slice(0, 50)}`
                          : 'starting…';
                        const isRunningTile = !isCancelled && status === 'running';
                        const isCancelling = !!cancellingVisits[vid];
                        return (
                          <div
                            key={vid}
                            className={`relative rounded-lg border-2 ${borderColor} bg-zinc-950 overflow-hidden cursor-pointer hover:border-blue-400 transition-colors ${isExpanded ? 'fixed inset-4 z-50 cursor-default' : ''}`}
                            onClick={() => !isExpanded && setExpandedVisit(vid)}
                            data-testid={`rut-visual-tile-${vid}`}
                          >
                            {/* Visit badge top-left */}
                            <div className="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-900/90 text-white font-bold z-10">
                              #{String(vid).padStart(3, "0")}
                            </div>
                            {/* Status badge top-right */}
                            <div className={`absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded text-[10px] font-mono ${badgeColor} z-10`}>
                              {isCancelled ? '⊘ cancelled' : status === 'running' ? '⏵ running' : status === 'ok' ? '✓ ok' : '✗ failed'}
                            </div>
                            {/* v2.6.1 — Task 5: red error banner for FAILED / CANCELLED
                                visits. Sits at the bottom of the tile with the exact
                                error message + a small "Dismiss" button so the operator
                                can free the slot after reviewing the reason. */}
                            {(v.status === 'failed' || v.status === 'cancelled') && (v.error || v.latest_event?.detail || v.latest_event?.error) && (
                              <div
                                className={`absolute bottom-0 left-0 right-0 z-20 px-2 py-1.5 border-t text-[10px] leading-tight font-mono
                                  ${v.status === 'failed' 
                                    ? 'bg-rose-950/95 text-rose-100 border-rose-500/60'
                                    : 'bg-zinc-900/95 text-zinc-200 border-zinc-500/60'}`}
                                onClick={(e) => e.stopPropagation()}
                                data-testid={`rut-visual-tile-error-${vid}`}
                              >
                                <div className="flex items-start gap-1">
                                  <span className="shrink-0">{v.status === 'failed' ? '⚠' : '⊘'}</span>
                                  <span className="flex-1 break-words" title={v.error || v.latest_event?.detail || v.latest_event?.error}>
                                    {(v.error || v.latest_event?.detail || v.latest_event?.error || '').toString().slice(0, isExpanded ? 400 : 140)}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      // Dismiss = hide this tile client-side by
                                      // wiping its entry from state. Backend
                                      // still keeps it for post-mortem.
                                      setLiveVisits((prev) => {
                                        const nx = { ...prev };
                                        delete nx[vid];
                                        return nx;
                                      });
                                    }}
                                    className="shrink-0 px-1 py-0 rounded text-[9px] font-semibold bg-black/40 hover:bg-black/70 text-white"
                                    title="Dismiss this tile"
                                    data-testid={`rut-visual-tile-dismiss-${vid}`}
                                  >
                                    ✕
                                  </button>
                                </div>
                              </div>
                            )}
                            {/* 2026-05 — Per-visit manual kill button.
                                Shows only while the visit is still running
                                (so users can rescue a stuck tile without
                                stopping the whole job). Sits just below the
                                status badge so it never overlaps. */}
                            {isRunningTile && (
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); cancelOneVisit(vid); }}
                                disabled={isCancelling}
                                title="Cancel this visit only — next visit will take its slot"
                                aria-label={`Cancel visit #${String(vid).padStart(3, "0")}`}
                                data-testid={`rut-visual-tile-kill-${vid}`}
                                className={`absolute z-20 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold transition-colors
                                  ${isCancelling
                                    ? 'bg-zinc-700/90 text-zinc-300 cursor-wait'
                                    : 'bg-rose-900/90 text-rose-100 hover:bg-rose-700 hover:text-white cursor-pointer'
                                  } ${isExpanded ? 'top-2 right-24' : 'top-7 right-1.5'}`}
                              >
                                {isCancelling
                                  ? (<><Loader2 size={10} className="animate-spin" /> cancelling…</>)
                                  : (<><X size={10} /> kill</>)
                                }
                              </button>
                            )}
                            {/* 2026-06 — Live Visual Grid: Manual Takeover
                                controls toolbar. Only renders for the
                                EXPANDED tile so the regular grid stays
                                lightweight. Pause/Resume always available
                                on a running tile; Take Control + Type/Send
                                only unlock once paused (engine refuses
                                input on running visits — 409). */}
                            {isExpanded && isRunningTile && (
                              <div
                                className="absolute top-12 left-1/2 -translate-x-1/2 z-30 flex items-center gap-1.5 bg-zinc-900/95 backdrop-blur-md border border-zinc-700 rounded-lg px-2 py-1.5 shadow-lg"
                                onClick={(e) => e.stopPropagation()}
                                data-testid={`rut-visual-tile-controls-${vid}`}
                              >
                                {!pausedVisits[vid] ? (
                                  <button
                                    type="button"
                                    onClick={() => pauseVisit(vid)}
                                    className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-amber-900/80 text-amber-100 hover:bg-amber-700 hover:text-white cursor-pointer transition-colors"
                                    title="Pause this visit's JSON automation"
                                    data-testid={`rut-visual-tile-pause-${vid}`}
                                  >
                                    <Pause size={11} /> pause
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => resumeVisit(vid)}
                                    className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-emerald-900/80 text-emerald-100 hover:bg-emerald-700 hover:text-white cursor-pointer transition-colors"
                                    title="Resume the JSON automation"
                                    data-testid={`rut-visual-tile-resume-${vid}`}
                                  >
                                    <PlayIcon size={11} /> resume
                                  </button>
                                )}
                                {pausedVisits[vid] && (
                                  controlVisit === vid ? (
                                    <button
                                      type="button"
                                      onClick={() => setControlVisit(null)}
                                      className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-blue-700 text-white hover:bg-blue-600 cursor-pointer ring-1 ring-blue-300/40 transition-colors"
                                      title="Stop manual control (Pause stays on)"
                                      data-testid={`rut-visual-tile-stopcontrol-${vid}`}
                                    >
                                      <Hand size={11} /> manual ON
                                    </button>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => setControlVisit(vid)}
                                      className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-blue-900/80 text-blue-100 hover:bg-blue-700 hover:text-white cursor-pointer transition-colors"
                                      title="Take manual control — click on the frame to interact"
                                      data-testid={`rut-visual-tile-control-${vid}`}
                                    >
                                      <Hand size={11} /> take control
                                    </button>
                                  )
                                )}
                                {pausedVisits[vid] && (
                                  <>
                                    <button
                                      type="button"
                                      onClick={() => sendVisitInput(vid, "scroll", { dx: 0, dy: 400 })}
                                      disabled={inputInFlight}
                                      className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700 hover:text-white cursor-pointer disabled:opacity-50 transition-colors"
                                      title="Scroll down"
                                    >
                                      <ArrowUpDown size={11} /> ↓
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => sendVisitInput(vid, "scroll", { dx: 0, dy: -400 })}
                                      disabled={inputInFlight}
                                      className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700 hover:text-white cursor-pointer disabled:opacity-50 transition-colors"
                                      title="Scroll up"
                                    >
                                      <ArrowUpDown size={11} /> ↑
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => sendVisitInput(vid, "back", {})}
                                      disabled={inputInFlight}
                                      className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700 hover:text-white cursor-pointer disabled:opacity-50 transition-colors"
                                      title="Browser Back"
                                    >
                                      ← back
                                    </button>
                                  </>
                                )}
                              </div>
                            )}
                            {/* Live frame */}
                            {v.latest_frame_b64 ? (
                              <div
                                className="bg-black w-full overflow-y-auto overflow-x-hidden relative"
                                style={{
                                  height: isExpanded ? '88vh' : 220,
                                  scrollbarWidth: 'thin',
                                }}
                                onClick={(e) => isExpanded && e.stopPropagation()}
                                onWheel={(e) => isExpanded && e.stopPropagation()}
                                data-testid={`rut-visual-tile-frame-${vid}`}
                              >
                                {/* Image-and-overlay wrapper so SVG
                                    overlays in the SAME scrolling
                                    region (otherwise dots would stay
                                    fixed while the page scrolls). */}
                                <div className="relative w-full">
                                  <img
                                    ref={isExpanded && controlVisit === vid ? frameImgRef : undefined}
                                    src={v.latest_frame_b64}
                                    alt={`Visit ${vid}`}
                                    className={`w-full block ${isExpanded && controlVisit === vid ? 'cursor-crosshair ring-2 ring-blue-400 ring-inset' : ''}`}
                                    style={{ height: 'auto', display: 'block' }}
                                    onClick={(e) => {
                                      if (isExpanded && controlVisit === vid) {
                                        e.stopPropagation();
                                        handleFrameClick(e, vid);
                                      }
                                    }}
                                    onContextMenu={(e) => {
                                      if (isExpanded && controlVisit === vid) {
                                        e.preventDefault();
                                        handleFrameClick(e, vid);
                                      }
                                    }}
                                    draggable={false}
                                  />
                                  {/* Pause / Manual overlay banner */}
                                  {isExpanded && pausedVisits[vid] && (
                                    <div className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[11px] font-mono bg-amber-500/95 text-amber-950 font-bold shadow-lg flex items-center gap-1.5 pointer-events-none">
                                      <Pause size={11} />
                                      {controlVisit === vid
                                        ? 'PAUSED · MANUAL CONTROL ACTIVE — click on frame to interact'
                                        : 'PAUSED — click "take control" to interact manually'}
                                    </div>
                                  )}
                                  {/* ── 2026-05: Step Markers SVG ──
                                      One coloured dot per recorded step
                                      at the resolved element's full-page
                                      coords (scaled to rendered <img>
                                      width). Position uses % so it
                                      survives image rescale on window
                                      resize. */}
                                  {showStepMarkers && Array.isArray(v.step_markers)
                                    && v.step_markers.length > 0
                                    && v.doc_size && v.doc_size.w > 0 && v.doc_size.h > 0 && (
                                    <svg
                                      className="absolute inset-0 w-full h-full pointer-events-none"
                                      style={{ overflow: 'visible' }}
                                      viewBox={`0 0 ${v.doc_size.w} ${v.doc_size.h}`}
                                      preserveAspectRatio="none"
                                      data-testid={`rut-visual-tile-markers-${vid}`}
                                    >
                                      {v.step_markers.map((m, mi) => {
                                        const box = m.box || {};
                                        const cx = (box.x || 0) + (box.w || 0) / 2;
                                        const cy = (box.y || 0) + (box.h || 0) / 2;
                                        const isLatest = mi === v.step_markers.length - 1;
                                        // Colour by action type for at-a-glance
                                        // recognition: click=blue, fill=emerald,
                                        // select=violet, check=amber, others=zinc.
                                        const colourMap = {
                                          click: '#3b82f6',
                                          fill: '#10b981',
                                          type: '#10b981',
                                          select: '#a855f7',
                                          check: '#f59e0b',
                                          uncheck: '#f59e0b',
                                          hover: '#06b6d4',
                                          press: '#ec4899',
                                        };
                                        const fillC = colourMap[(m.action || '').toLowerCase()] || '#71717a';
                                        const stroke = isLatest ? '#ffffff' : 'rgba(0,0,0,0.6)';
                                        const r = isLatest ? 28 : 18;
                                        return (
                                          <g key={mi}>
                                            {/* Hit-box rectangle for context */}
                                            {(box.w > 0 && box.h > 0) && (
                                              <rect
                                                x={box.x} y={box.y}
                                                width={box.w} height={box.h}
                                                fill="none"
                                                stroke={fillC}
                                                strokeWidth={isLatest ? 4 : 2}
                                                strokeOpacity={isLatest ? 0.9 : 0.55}
                                                strokeDasharray={isLatest ? "0" : "8 4"}
                                              />
                                            )}
                                            {/* Numbered dot at element centre */}
                                            <circle
                                              cx={cx} cy={cy} r={r}
                                              fill={fillC}
                                              fillOpacity={isLatest ? 0.95 : 0.75}
                                              stroke={stroke}
                                              strokeWidth={isLatest ? 4 : 2}
                                            />
                                            <text
                                              x={cx} y={cy + r * 0.35}
                                              textAnchor="middle"
                                              fontSize={r * 1.0}
                                              fontFamily="ui-monospace, Menlo, monospace"
                                              fontWeight="700"
                                              fill="#ffffff"
                                            >
                                              {(m.idx ?? mi) + 1}
                                            </text>
                                          </g>
                                        );
                                      })}
                                    </svg>
                                  )}
                                </div>

                                {/* Step-markers legend, only when toggle is ON
                                    and there's something to mark. */}
                                {showStepMarkers && Array.isArray(v.step_markers) && v.step_markers.length > 0 && (
                                  <div className="sticky bottom-0 left-0 right-0 bg-zinc-950/85 backdrop-blur-sm border-t border-zinc-800 px-2 py-1 text-[10px] text-zinc-300 flex items-center gap-3 flex-wrap">
                                    <span className="text-zinc-500">Markers ({v.step_markers.length}):</span>
                                    <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block"/>click</span>
                                    <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"/>fill/type</span>
                                    <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-violet-500 inline-block"/>select</span>
                                    <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500 inline-block"/>check</span>
                                    <span className="text-zinc-500 ml-auto">Solid ring = current step</span>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div className="w-full h-40 flex items-center justify-center text-zinc-500 text-xs">
                                <Loader2 className="w-4 h-4 animate-spin mr-1" /> Waiting for first frame…
                              </div>
                            )}
                            {/* Current step info — bottom overlay */}
                            <div className="absolute bottom-0 left-0 right-0 bg-black/80 text-white px-2 py-1 text-[11px] font-mono">
                              <div className="flex items-center justify-between gap-2">
                                <span className="truncate">{descr}</span>
                                {typeof ev.ms === 'number' && (
                                  <span className="text-zinc-400 flex-shrink-0">{ev.ms}ms</span>
                                )}
                              </div>
                              {(status === 'failed' && (ev.error || ev.detail)) && (
                                <div className="text-rose-300 truncate text-[10px] mt-0.5" title={ev.error || ev.detail}>
                                  ⚠ {(ev.error || ev.detail).slice(0, 80)}
                                </div>
                              )}
                            </div>
                            {/* Expanded close button */}
                            {isExpanded && (
                              <button
                                onClick={(e) => { e.stopPropagation(); setExpandedVisit(null); setControlVisit(null); }}
                                className="absolute top-2 right-12 px-2 py-1 rounded bg-black/80 text-white text-xs hover:bg-zinc-800 z-20"
                                data-testid={`rut-visual-tile-collapse-${vid}`}
                              >
                                <X size={14} className="inline" /> Close
                              </button>
                            )}
                            {/* 2026-06 — Manual-type input row. Appears at
                                the bottom of the expanded tile while the
                                visit is paused. Lets the operator focus
                                a form field with a click then type a
                                value the recorded automation couldn't
                                figure out. Pressing Enter sends + clears. */}
                            {isExpanded && pausedVisits[vid] && (
                              <div
                                className="absolute bottom-0 left-0 right-0 z-30 flex items-center gap-2 bg-zinc-900/95 backdrop-blur-md border-t border-zinc-700 px-3 py-2"
                                onClick={(e) => e.stopPropagation()}
                                data-testid={`rut-visual-tile-type-row-${vid}`}
                              >
                                <Keyboard size={14} className="text-blue-400 shrink-0" />
                                <Input
                                  value={controlText}
                                  onChange={(e) => setControlText(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                      e.preventDefault();
                                      if (controlText) {
                                        sendVisitInput(vid, "type", { text: controlText });
                                        setControlText("");
                                      } else {
                                        sendVisitInput(vid, "key", { key: "Enter" });
                                      }
                                    }
                                  }}
                                  placeholder="Type text → Enter to send to the focused field (works after a click on the frame)"
                                  className="flex-1 h-8 bg-zinc-950 border-zinc-700 text-white text-xs"
                                  data-testid={`rut-visual-tile-type-input-${vid}`}
                                />
                                <Button
                                  size="sm"
                                  onClick={() => {
                                    if (controlText) {
                                      sendVisitInput(vid, "type", { text: controlText });
                                      setControlText("");
                                    }
                                  }}
                                  disabled={!controlText || inputInFlight}
                                  className="h-8 px-3 bg-blue-700 hover:bg-blue-600 text-white text-xs"
                                  data-testid={`rut-visual-tile-type-send-${vid}`}
                                >
                                  Send
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => sendVisitInput(vid, "key", { key: "Tab" })}
                                  disabled={inputInFlight}
                                  className="h-8 px-2 border-zinc-700 text-zinc-200 hover:bg-zinc-800 text-xs"
                                  title="Press Tab"
                                >
                                  Tab
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => sendVisitInput(vid, "key", { key: "Enter" })}
                                  disabled={inputInFlight}
                                  className="h-8 px-2 border-zinc-700 text-zinc-200 hover:bg-zinc-800 text-xs"
                                  title="Press Enter"
                                >
                                  Enter
                                </Button>
                              </div>
                            )}
                          </div>
                        );
                      })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ═══ Diagnostics Modal ═══ */}
      {diagModalOpen && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          data-testid="rut-diag-modal"
        >
          <div className="bg-zinc-950 border border-amber-900/50 rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <AlertTriangle size={18} className="text-amber-400" />
                <h3 className="text-white font-semibold">
                  Diagnostics — macro leaks & stuck visits
                </h3>
              </div>
              <button
                onClick={() => setDiagModalOpen(false)}
                className="text-zinc-400 hover:text-white p-1 rounded"
                data-testid="rut-diag-modal-close"
                aria-label="Close diagnostics"
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 text-xs space-y-4">
              {diagLoading && (
                <div className="text-center text-zinc-500 py-10">Loading diagnostics…</div>
              )}
              {!diagLoading && diagData && (
                <>
                  {/* ── 2026-05: Smart Replay Diagnostics (script static analysis) ── */}
                  {diagData.script_diagnostics && (diagData.script_step_count || 0) > 0 && (
                    <section data-testid="rut-script-diag-section" className="border border-blue-700/40 rounded-lg bg-blue-950/20 p-3">
                      <h4 className="text-blue-300 font-semibold mb-2 flex items-center gap-2">
                        <Activity size={14} /> Smart Replay Diagnostics
                        <span className="text-zinc-500 font-mono text-[11px]">
                          ({diagData.script_step_count} steps)
                        </span>
                      </h4>
                      <p className="text-zinc-500 mb-3">
                        Static analysis of your recorded automation. Spot brittle/slow steps before they cost you visits.
                      </p>

                      {/* Wrapper-kind summary */}
                      {diagData.script_diagnostics.wrapper_summary && Object.keys(diagData.script_diagnostics.wrapper_summary).length > 0 && (
                        <div className="mb-3">
                          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Dropdown stack</div>
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(diagData.script_diagnostics.wrapper_summary).map(([k, v]) => (
                              <span
                                key={k}
                                data-testid={`rut-diag-wrap-${k}`}
                                className={`text-[11px] px-2 py-0.5 rounded-full border ${k === "native" ? "bg-zinc-800 border-zinc-700 text-zinc-300" : "bg-blue-500/15 border-blue-500/40 text-blue-200"}`}
                              >
                                {k}: {v}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Anti-patterns */}
                      {Array.isArray(diagData.script_diagnostics.anti_patterns) && diagData.script_diagnostics.anti_patterns.length > 0 && (
                        <div className="mb-3">
                          <div className="text-[10px] uppercase tracking-wide text-amber-400 mb-1 flex items-center gap-1">
                            <AlertTriangle size={12} /> Anti-patterns ({diagData.script_diagnostics.anti_patterns.length})
                          </div>
                          <ul className="space-y-1.5 list-disc list-inside">
                            {diagData.script_diagnostics.anti_patterns.map((ap, i) => (
                              <li key={i} data-testid={`rut-diag-ap-${i}`} className="text-zinc-300 leading-snug">{ap}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Recommendations */}
                      {Array.isArray(diagData.script_diagnostics.recommendations) && diagData.script_diagnostics.recommendations.length > 0 && (
                        <div>
                          <div className="text-[10px] uppercase tracking-wide text-emerald-400 mb-1">Recommendations</div>
                          <ul className="space-y-1.5 list-disc list-inside">
                            {diagData.script_diagnostics.recommendations.map((rc, i) => (
                              <li key={i} data-testid={`rut-diag-rec-${i}`} className="text-emerald-100/90 leading-snug">{rc}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {(!diagData.script_diagnostics.anti_patterns || diagData.script_diagnostics.anti_patterns.length === 0) && (
                        <p className="text-emerald-300/80 italic mt-2" data-testid="rut-diag-no-issues">
                          ✓ No anti-patterns detected — your recording looks clean.
                        </p>
                      )}
                    </section>
                  )}

                  {/* ── Macro leaks ── */}
                  <section>
                    <h4 className="text-amber-300 font-semibold mb-2 flex items-center gap-2">
                      <AlertTriangle size={14} /> Macro-leak blocks
                      <span className="text-zinc-500 font-mono text-[11px]">
                        ({diagData.macro_leak_count || 0})
                      </span>
                    </h4>
                    <p className="text-zinc-500 mb-2">
                      Each row = a navigation that was blocked because the URL
                      still contained an unfilled tracker macro
                      (<code className="text-amber-300">{`{{ccpa}}`}</code>,
                      <code className="text-amber-300">{`{{sub}}`}</code>, etc.).
                      Frequent leaks on the same host mean that offer's tracker
                      URL is missing a required parameter — fix it on the
                      affiliate-network side.
                    </p>
                    {(diagData.top_macro_leak_hosts || []).length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {diagData.top_macro_leak_hosts.map((h, i) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded bg-amber-900/40 border border-amber-800 text-amber-200 font-mono"
                            data-testid={`rut-diag-top-host-${i}`}
                          >
                            {h.host} × {h.count}
                          </span>
                        ))}
                      </div>
                    )}
                    {(diagData.macro_leaks || []).length === 0 ? (
                      <p className="text-zinc-600 italic">No macro leaks recorded for this job.</p>
                    ) : (
                      <div className="max-h-48 overflow-y-auto border border-zinc-800 rounded">
                        <table className="w-full font-mono">
                          <thead className="bg-zinc-900 text-zinc-400 sticky top-0">
                            <tr>
                              <th className="text-left px-2 py-1">Visit</th>
                              <th className="text-left px-2 py-1">Type</th>
                              <th className="text-left px-2 py-1">Blocked URL</th>
                            </tr>
                          </thead>
                          <tbody>
                            {diagData.macro_leaks.map((ev, i) => (
                              <tr
                                key={i}
                                className="border-t border-zinc-900 text-zinc-300"
                                data-testid={`rut-diag-macro-row-${i}`}
                              >
                                <td className="px-2 py-1">#{ev.visit_index}</td>
                                <td className="px-2 py-1 text-zinc-500">{ev.resource_type || "?"}</td>
                                <td className="px-2 py-1 break-all">{ev.blocked_url}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>

                  {/* ── Stuck events ── */}
                  <section>
                    <h4 className="text-rose-300 font-semibold mb-2 flex items-center gap-2">
                      <AlertTriangle size={14} /> Stuck visits
                      <span className="text-zinc-500 font-mono text-[11px]">
                        ({diagData.stuck_event_count || 0})
                      </span>
                    </h4>
                    <p className="text-zinc-500 mb-2">
                      Each row = a visit whose page URL didn't change for
                      &gt;25 seconds while automation steps were running.
                      Clusters around the same URL mean the bot is dying on
                      that specific offer page — usually because the JSON
                      script's selectors don't match.
                    </p>
                    {(diagData.top_stuck_hosts || []).length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {diagData.top_stuck_hosts.map((h, i) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded bg-rose-900/40 border border-rose-800 text-rose-200 font-mono"
                            data-testid={`rut-diag-stuck-host-${i}`}
                          >
                            {h.host} × {h.count}
                          </span>
                        ))}
                      </div>
                    )}
                    {(diagData.stuck_events || []).length === 0 ? (
                      <p className="text-zinc-600 italic">No stuck visits recorded for this job.</p>
                    ) : (
                      <div className="max-h-96 overflow-y-auto border border-zinc-800 rounded">
                        <table className="w-full font-mono">
                          <thead className="bg-zinc-900 text-zinc-400 sticky top-0">
                            <tr>
                              <th className="text-left px-2 py-1">Visit</th>
                              <th className="text-left px-2 py-1">Stuck (s)</th>
                              <th className="text-left px-2 py-1">URL · what the page was showing</th>
                            </tr>
                          </thead>
                          <tbody>
                            {diagData.stuck_events.map((ev, i) => (
                              <tr
                                key={i}
                                className="border-t border-zinc-900 text-zinc-300 align-top"
                                data-testid={`rut-diag-stuck-row-${i}`}
                              >
                                <td className="px-2 py-1">#{ev.visit_index}</td>
                                <td className="px-2 py-1 text-rose-300">
                                  {ev.seconds_stuck}
                                </td>
                                <td className="px-2 py-1 space-y-1">
                                  <div className="break-all">{ev.stuck_url}</div>
                                  {ev.body_snippet && (
                                    <details className="text-[11px] text-zinc-400">
                                      <summary className="cursor-pointer hover:text-zinc-200">
                                        Show page text snippet
                                      </summary>
                                      <pre className="whitespace-pre-wrap mt-1 p-2 bg-zinc-900 border border-zinc-800 rounded text-zinc-300 max-h-32 overflow-y-auto">
                                        {ev.body_snippet}
                                      </pre>
                                    </details>
                                  )}
                                  {ev.snapshot_name && (
                                    <div className="text-[11px] text-zinc-500">
                                      📷 Screenshot in ZIP: <code className="text-zinc-300">{ev.snapshot_name}</code>
                                    </div>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                </>
              )}
              {!diagLoading && !diagData && (
                <div className="text-center text-zinc-500 py-10">
                  No diagnostics data available for this job.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══ Thumbnail lightbox ═══ */}
      {previewShot && (
        <div
          className="fixed inset-0 bg-black/85 backdrop-blur-md z-[60] flex items-center justify-center p-4"
          onClick={() => setPreviewShot(null)}
          data-testid="rut-live-lightbox"
        >
          <button
            type="button"
            onClick={() => setPreviewShot(null)}
            className="absolute top-4 right-4 text-zinc-300 hover:text-white p-2 rounded-full bg-zinc-900/70 border border-zinc-700"
            aria-label="Close preview"
            data-testid="rut-live-lightbox-close"
          >
            <X size={22} />
          </button>
          <img
            src={previewShot}
            alt="Visit screenshot full size"
            className="max-w-[95vw] max-h-[90vh] object-contain rounded-md shadow-2xl border border-zinc-800"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }) {
  const colorMap = { emerald: "text-emerald-300", amber: "text-amber-300", red: "text-red-300", fuchsia: "text-fuchsia-300" };
  return (
    <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${colorMap[color] || "text-zinc-100"}`}>{value}</div>
    </div>
  );
}

function CheckRow({ testId, checked, onChange, children }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 accent-fuchsia-500"
        data-testid={testId}
      />
      {children}
    </label>
  );
}
