import React, { useEffect, useRef, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Camera,
  Play,
  Square,
  Trash2,
  Download,
  Copy,
  Hand,
  Type,
  Shuffle,
  MousePointerClick,
  Flag,
  Clock,
  ScrollText,
  ArrowLeft,
  ArrowRight,
  Loader2,
  CheckCircle2,
  Sparkles,
  Globe,
  ListPlus,
  RefreshCw,
  Image as ImageIcon,
  ChevronDown,
  CheckSquare,
  Undo2,
  Keyboard,
  History,
  Smartphone,
  Tablet,
  Monitor,
  Save,
  Zap,
  AlertCircle,
  Activity,
  CheckCheck,
  XCircle,
  Lightbulb,
  Timer,
  Pencil,
  Brain,
  Trash,
  FastForward,
  GitBranch,
  X,
  ArrowLeftRight,
  MessageSquareWarning,
  ScanSearch,
  Columns,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import * as XLSX from "xlsx";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_URL = `${BACKEND_URL}`;

const authH = () => ({
  Authorization: `Bearer ${localStorage.getItem("token")}`,
  "Content-Type": "application/json",
});

// 2026-06 — Friendly auto-label for a recorded step. The step list
// previously fell back to `s.action` which made 8 consecutive clicks
// all read "click" / "click" / "click". This helper turns each step
// into a descriptive 1-line label like "Click: Next button" or
// "Dropdown → {{state}}" so the recording is glanceable at a scroll.
// User can still rename manually via inline-edit; this is just the
// auto-default when `s.name` is empty.
function getStepDisplayName(s) {
  if (s?.name) return s.name;
  const a = (s?.action || "").toLowerCase();
  if (s?.source === "auto_wait") {
    if (a === "wait") return `Auto wait ${s.ms || 0}ms`;
    if (a === "wait_for_load") return "Auto wait for load";
  }
  // Short, value-aware preview helpers
  const _val = (v, n = 24) => {
    const x = (v == null ? "" : String(v)).trim();
    if (!x) return "";
    return x.length > n ? x.slice(0, n - 1) + "…" : x;
  };
  const _sel = (v, n = 24) => _val(v, n);
  switch (a) {
    case "click": {
      // Recorder stamps `text` on click steps when the element had visible text
      const t = _val(s.text, 26);
      if (t) return `Click: ${t}`;
      const sel = _sel(s.selector, 30);
      return sel ? `Click ${sel}` : "Click";
    }
    case "fill":
    case "type": {
      const v = _val(s.value, 22);
      const sel = _sel(s.selector, 20);
      if (v) return `Type → ${v}${sel ? "  (" + sel + ")" : ""}`;
      return sel ? `Type ${sel}` : "Type";
    }
    case "select": {
      const v = _val(s.value, 22);
      const sel = _sel(s.selector, 20);
      if (v) return `Dropdown → ${v}${sel ? "  (" + sel + ")" : ""}`;
      return sel ? `Dropdown ${sel}` : "Dropdown";
    }
    case "check":
      return s.selector ? `Check ${_sel(s.selector, 30)}` : "Check Box";
    case "uncheck":
      return s.selector ? `Uncheck ${_sel(s.selector, 30)}` : "Uncheck";
    case "wait":
      return `Wait ${s.ms || 0}ms`;
    case "wait_for_selector":
      return `Wait for selector ${_sel(s.selector, 26)}`;
    case "wait_for_text":
      return `Wait for text "${_val(s.text, 24)}"`;
    case "wait_for_url":
      return `Wait for URL ${_val(s.url || s.value, 28)}`;
    case "wait_for_load":
      return "Wait for page load";
    case "navigate":
    case "goto": {
      const u = _val(s.url || s.value, 36);
      return u ? `Go to ${u}` : "Navigate";
    }
    case "screenshot":
      return s.name || "📷 Screenshot";
    case "press":
      return `Press ${s.key || ""}`.trim();
    case "scroll":
      return s.dir === "up" ? "Scroll ↑" : "Scroll ↓";
    case "hover":
      return s.selector ? `Hover ${_sel(s.selector, 28)}` : "Hover";
    case "evaluate":
      if (s.origin === "gender_pick" && s.header_name) {
        const ml = s.gender_labels?.male?.join("/") || "Male";
        const fl = s.gender_labels?.female?.join("/") || "Female";
        return `Gender → {{${s.header_name}}} (${ml} | ${fl})`;
      }
      if ((s.origin === "option_pick" || s.origin === "sheet_pick") && s.header_name) {
        const opts = s.option_labels?.join(" · ") || s.gender_labels?.male?.join("/") || "";
        return opts
          ? `Option Pick → {{${s.header_name}}} (${opts})`
          : `Option Pick → {{${s.header_name}}}`;
      }
      return s.script ? `Run JS: ${_val(s.script, 30)}` : "Run JS";
    case "dismiss_popups":
      return "Dismiss popups";
    case "extract":
      return `Extract → ${_val(s.var_name || s.var || "var", 18)}`;
    case "random_pick":
      return "🎲 Random Pick";
    case "random_click":
      return "🎯 Random Click";
    case "auto_continue":
    case "auto_continue_survey":
      return "🔄 Auto-Continue";
    case "branch": {
      const n = Array.isArray(s.branches) ? s.branches.length : 0;
      return `🔀 If / Else (${n} branch${n === 1 ? "" : "es"})`;
    }
    case "close":
    case "close_browser":
      return "✖ Close Browser";
    case "switch_tab": {
      const i = typeof s.index === "number" ? s.index : "?";
      const u = _val(s.url, 22);
      return u ? `↔ Switch to tab #${i} (${u})` : `↔ Switch to tab #${i}`;
    }
    case "close_tab": {
      const i = typeof s.index === "number" ? `#${s.index}` : "(current)";
      return `✕ Close tab ${i}`;
    }
    case "stage": {
      const nm = _val(s.name || s.stage, 28) || "Stage";
      const ow = s.open_when;
      const hasDetect = ow && (ow.selector || ow.text || ow.value || ow.type);
      return hasDetect ? `📦 Stage: ${nm} (detect)` : `📦 Stage: ${nm}`;
    }
    case "stage_markers":
      return s.enabled === false ? "Stage markers OFF" : "Stage markers ON";
    case "accept_dialog": {
      // v2.1.74 — JS dialog accept (alert/confirm/prompt)
      const t = s.dialog_type || "dialog";
      const m = s.message_contains ? ` · "${_val(s.message_contains, 24)}"` : "";
      const pt = s.prompt_text ? ` → ${_val(s.prompt_text, 18)}` : "";
      return `✓ Accept ${t}()${m}${pt}`;
    }
    case "dismiss_dialog": {
      const t = s.dialog_type || "dialog";
      const m = s.message_contains ? ` · "${_val(s.message_contains, 24)}"` : "";
      return `✕ Dismiss ${t}()${m}`;
    }
    default:
      return s.action || "step";
  }
}


const TOOLS = [
  { id: "default",   icon: Hand,        label: "Click",       key: "1", help: "Normal click — captures button/link text" },
  { id: "form_fill", icon: Type,        label: "Form Fill",   key: "2", help: "Click an input, then bind to Excel column" },
  { id: "option_pick", icon: Columns,   label: "Option Pick", key: "c", help: "Click 2+ buttons (Male/Female, Yes/No), bind Excel column — replays per-row value" },
  { id: "gender_pick", icon: Users,    label: "Gender",      key: "g", help: "Shortcut for Option Pick — Male + Female pool, bind {{gender}} column (M/F auto)" },
  { id: "dropdown",  icon: ChevronDown, label: "Dropdown",    key: "3", help: "Click a <select> dropdown to bind option / Excel column" },
  { id: "check",     icon: CheckSquare, label: "Check Box",   key: "4", help: "Click a checkbox (consent / agree / opt-in) — works on hidden CSS-styled boxes too" },
  { id: "random",    icon: Shuffle,     label: "Random Pick", key: "5", help: "Auto-detect form-selection buttons (Yes/No/radio/checkbox groups) on page → tick the ones to randomise each run" },
  { id: "random_click", icon: MousePointerClick, label: "Random Click", key: "0", help: "Auto-detect ALL clickable CTAs (buttons/links/ads) on the page → tick the ones to randomly click ONE per visit (for offer-flow A/B variants)" },
  // 2026-01 v2.4.2 — Popup Work: like Random Click but SCOPED to any
  // currently-visible popup/modal/dialog on the page. Detects the
  // close (✕) / OK / Cancel / custom buttons INSIDE the popup and
  // lets the customer tick which ones to add as click steps.
  { id: "popup_work", icon: MessageSquareWarning, label: "Popup Work", key: "p", help: "Detect ALL buttons inside any visible popup / modal / dialog (close-X, OK, Cancel, custom close-buttons) → tick which ones to add as steps. Perfect for surveys / form pages that throw mid-flow popups." },
  // 2026-01 v2.4.2 — Scan: click any element to reveal its text,
  // CSS selector, xpath (stable + absolute) without recording a
  // step or clicking. Copy-paste locators anywhere.
  { id: "scan",      icon: ScanSearch,  label: "Scan",        key: "s", help: "Click any element on the page → get its text, CSS selector, xpath (stable + absolute). NO click is performed. Copy the locators for use in RPA Studio / manual steps / wait_for_selector / wait_for_xpath." },
  // 2026-07 v2.5.4 — Wait for Button: point-and-click sibling of the
  // typed "Wait for selector" / "Wait for xpath" buttons. When active,
  // clicking any button/link on the live preview inserts a
  // wait_for_selector step targeting that button (no click fires).
  // Perfect for lazy-loading offer pages: pick the CTA that eventually
  // appears, replay pauses until it materialises.
  { id: "wait_for_button", icon: Clock, label: "Wait for Button", key: "w", help: "Click any button/link on the live page → recorder saves a WAIT-UNTIL-VISIBLE step for that exact button (NO click). Use when the offer page loads the button lazily and RUT needs to pause until it appears." },
  { id: "capture",   icon: ImageIcon,   label: "Capture",     key: "6", help: "Insert a screenshot marker — shown in Live Activity" },
  { id: "final",     icon: Flag,        label: "Mark Final",  key: "7", help: "Capture this page as conversion target" },
  { id: "nav_only",  icon: ArrowRight,  label: "Move",        key: "8", help: "Click without recording — use to navigate past a Random Pick step" },
  { id: "manual_type", icon: Pencil,    label: "Fix Type",    key: "t", help: "Click an input and type a correction — live page updates but NO step is added to the JSON (use when Form Fill typed wrong during recording)" },
  // 2026-05: explicit "close browser" step. Inserts {"action":"close"}
  // at current position so the RUT runner frees the browser as soon
  // as it reaches this step (recommended right after the conversion-
  // confirmation Capture so post-submit pixel chains don't keep the
  // tile alive on slower VPSes).
  { id: "close_browser", icon: XCircle, label: "Close Browser", key: "9", help: "Insert a close-browser step — RUT runner will end this visit's browser immediately when reached (frees RAM for next worker)" },
  // 2026-06: "If / Else" — conditional branch. Opens a modal where the
  // user defines 2 (or more) branches, each with a condition (URL
  // contains / selector visible / text visible) and the steps to run
  // when that branch wins. Backed by the existing {"action":"branch"}
  // engine which RACES all branch conditions in parallel and runs
  // whichever resolves first.
  { id: "branch", icon: GitBranch, label: "If / Else", key: "i", help: "Conditional step — different sub-steps run depending on URL / visible element / text. Use when an offer page randomly shows phone OR email OR survey." },
];

// Device-viewport presets — applied at session start so the recording
// resembles the target audience's typical screen. The actual viewport
// is set server-side via the proxy/UA combo; this is a hint for the UI
// scaling + UA defaults.
const DEVICE_PRESETS = [
  { id: "mobile",  label: "Mobile",  icon: Smartphone, width: 412, height: 914,  hint: "Pixel-8 / iPhone-14 size" },
  { id: "tablet",  label: "Tablet",  icon: Tablet,     width: 820, height: 1180, hint: "iPad / Galaxy Tab"        },
  { id: "desktop", label: "Desktop", icon: Monitor,    width: 1280, height: 800, hint: "1280×800 laptop"          },
];

// localStorage keys for recent recordings + draft state
const LS_RECENT_KEY = "vr_recent_v1";
const LS_DRAFT_KEY = "vr_draft_v1";
const LS_VR_RUT_HANDOFF = "vr_automation_handoff";
const LS_VR_AUTO_WAITS = "vr_auto_insert_waits";
const LS_VR_PROXY_PROVIDER = "vr_proxy_provider_id";
const LS_VR_WAIT_AUTO_DETECT = "vr_wait_auto_detect";
const LS_RUT_SELF_HEAL = "rut_self_heal";
const LS_RUT_SKIP_CAPTCHA = "rut_skip_captcha";

function stashVrAutomationForRut(bundle) {
  if (!bundle) return;
  try {
    localStorage.setItem(
      LS_VR_RUT_HANDOFF,
      JSON.stringify({
        automation_json: bundle.automation_json || bundle.steps || [],
        url: bundle.url || "",
        headers: bundle.headers || [],
        proxy: bundle.proxy || "",
        proxy_provider_id: bundle.proxy_provider_id || "",
        country: bundle.country || "",
        device_preset: bundle.device_preset || "",
        user_agent: bundle.user_agent || "",
        auto_insert_waits: !!bundle.auto_insert_waits,
        target_screenshot_path: bundle.target_screenshot_path || "",
        session_id: bundle.session_id || "",
      }),
    );
    localStorage.setItem(LS_RUT_SELF_HEAL, "1");
    localStorage.setItem(LS_RUT_SKIP_CAPTCHA, "0");
    if (bundle.proxy_provider_id) {
      localStorage.setItem(LS_VR_PROXY_PROVIDER, bundle.proxy_provider_id);
    }
  } catch { /* quota / private mode */ }
}

// Tiny JSON colorizer — safe (escapes HTML, only adds <span class>)
function colorizeJson(obj) {
  const json = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  // Escape HTML
  const esc = json.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = "text-amber-300"; // numbers
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? "text-sky-300" : "text-emerald-300";
      } else if (/true|false/.test(match)) {
        cls = "text-fuchsia-300";
      } else if (/null/.test(match)) {
        cls = "text-zinc-500";
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

export default function VisualRecorderPage() {
  const [setupStage, setSetupStage] = useState("setup"); // setup | recording | done
  const [url, setUrl] = useState("");
  const [proxy, setProxy] = useState("");
  const [ua, setUa] = useState("");
  const [headers, setHeaders] = useState([]);
  const [headersInput, setHeadersInput] = useState("");
  const [excelFile, setExcelFile] = useState(null);
  // 2026-05: first data row → auto-fill form inputs during recording
  // so the user can submit forms and continue recording on the
  // post-submit page. Empty {} means no sample data yet.
  const [sampleRow, setSampleRow] = useState({});

  const [sessionId, setSessionId] = useState(null);
  const [sessionState, setSessionState] = useState("starting"); // starting | ready | error | stopped
  const [sessionError, setSessionError] = useState("");
  const [connectElapsed, setConnectElapsed] = useState(0);
  const [shotTick, setShotTick] = useState(0);   // bumps every poll → forces <img> reload via ?ts=
  const [shotErrorCount, setShotErrorCount] = useState(0);
  const [viewport, setViewport] = useState({ width: 412, height: 914 });
  const [steps, setSteps] = useState([]);

  // ─── 2026-06: AI Refine state (post-generation step editing) ───
  // User ask (Roman Urdu): "agar koi changes karni ho to AI ko hi bol
  // kar changes kara le jaye — k 'ye issue hai, isko solve kar do'".
  // Opens a small inline panel when there are existing steps in the
  // draft. User types an instruction, we POST to /ai-refine-steps,
  // backend's `refine_automation_for_user` returns updated steps, we
  // swap them in. The "Undo" button keeps the previous version one
  // click away so the user can roll back a bad AI edit.
  const [aiRefineOpen, setAiRefineOpen] = useState(false);
  const [aiRefineInstruction, setAiRefineInstruction] = useState("");
  const [aiRefineBusy, setAiRefineBusy] = useState(false);
  const [aiRefineError, setAiRefineError] = useState("");
  const [aiRefinePrevSteps, setAiRefinePrevSteps] = useState(null);

  // ─── 2026-06: AI Step Generator (Visual Recorder) ─────────────────
  // User ask (Roman Urdu): "Visual recorder mein AI integration ka option
  // ho ta k AI k zarye JSON banana aur b asan ho jaaye." Open the dialog,
  // upload screenshots/video + description, and the user's chosen AI
  // provider (gemini / openai / claude / emergent — configured in
  // Settings → AI Integrations) generates a starter step-list. The
  // generated steps replace the current draft so the user can refine,
  // re-record specific selectors, or Start Recording on top of them.
  //
  // 2026-06 update: proxy selector field added because "kuch offers
  // sirf USA ya specific country mein khulti hain — to AI dialog se
  // hi proxy choose kar paayen taa ke generation ke baad Start
  // Recording wahi proxy use kare."
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiFiles, setAiFiles] = useState([]);              // File[] from <input>
  const [aiDescription, setAiDescription] = useState("");
  const [aiTargetUrl, setAiTargetUrl] = useState("");
  const [aiExcelCols, setAiExcelCols] = useState("");      // optional CSV header list
  const [aiProxy, setAiProxy] = useState("");              // proxy string for the eventual recording
  const [aiProxyJetBusy, setAiProxyJetBusy] = useState(false);
  const [aiProviderUsed, setAiProviderUsed] = useState(""); // returned by backend
  const [aiError, setAiError] = useState("");
  // 2026-06 — Electron-safe prompt/confirm replacement.
  // Electron Renderer removed `await vrPrompt()` / `window.confirm()` —
  // any code path that hit them threw "prompt() is and will not be
  // supported." silently breaking 20+ recorder toolbar actions (Wait
  // for selector / text / URL, Extract var, Captcha pause, File upload,
  // OTP wait, Pause for human, Right-click, Set clipboard, Branch
  // condition, Iframe selector, Zoom, Capture screenshot name, etc.).
  // We replace the native dialogs with a tiny in-app modal driven by
  // this state + a resolver-based async helper.
  //   { kind: "prompt" | "confirm", message, defaultValue,
  //     resolve: (value: string|null|boolean) => void }
  const [promptModal, setPromptModal] = useState(null);
  // Edit-step modal state (2026-01) — null when closed; otherwise
  // {index, draft} where `draft` is a mutable copy of the step the
  // user is editing. See `openEditStep` / `saveEditStep` below.
  const [editingStep, setEditingStep] = useState(null);
  // Smart Selector Suggester state (2026-01) — { loading, items[], failedSelector }
  const [selectorSuggest, setSelectorSuggest] = useState({ loading: false, items: null, error: "" });
  // Hover-preview state (2026-01) — bbox of the suggestion currently
  // being hovered, drawn as a blue pulse outline overlay on the
  // live screenshot. null = no preview.
  const [hoverPreview, setHoverPreview] = useState(null);   // { x, y, width, height, viewport }
  // Manual "Add Step" modal — null when closed; otherwise a draft step
  const [manualStepDraft, setManualStepDraft] = useState(null);
  // Selector Aliases panel (2026-01, self-healing memory) — null = closed
  const [aliasesPanel, setAliasesPanel] = useState(null);   // { loading, items, error }
  const [pageMeta, setPageMeta] = useState({ url: "", title: "" });
  const [tool, setTool] = useState("default");
  const [pendingFormFill, setPendingFormFill] = useState(null); // {selector, header_name?}
  const [pendingOptionButtons, setPendingOptionButtons] = useState([]); // Option Pick pool
  const [pendingDropdownQueue, setPendingDropdownQueue] = useState([]); // queued dropdown binds
  const pendingDropdown = pendingDropdownQueue[0] || null;
  // 2026-06: If / Else branch editor modal. When non-null an overlay
  // dialog appears letting the user define 2+ branches with conditions
  // (URL contains / selector visible / text visible) and the inline
  // steps to run when each branch wins.
  //   { mode: "create" | "edit", insertIndex: number|null,
  //     editStepIndex: number|null, draft: <branch step JSON> }
  const [branchEditor, setBranchEditor] = useState(null);
  const [pendingRandom, setPendingRandom] = useState([]); // texts collected so far (legacy click-to-pool flow)
  // 2026-01: NEW Random Pick checklist flow
  //   detectedClickables: full list returned by /detect-clickables (one per page)
  //   selectedRandomKeys: Set of indices the user has ticked from that list
  //   detectingClickables: spinner flag while the call is in flight
  const [detectedClickables, setDetectedClickables] = useState([]);
  const [selectedRandomKeys, setSelectedRandomKeys] = useState(() => new Set());
  const [detectingClickables, setDetectingClickables] = useState(false);
  // ── 2026-01 v2.4.2 — Popup Work state (parallel to detectedClickables
  //                     but scoped to elements INSIDE popups/modals) ──
  // v2.6.28 — Added `popupItemActions` map so each detected popup item
  //           can be given its own action mode (click / form_fill /
  //           dropdown / check). Defaults are inferred from
  //           `element_kind` returned by the backend: text_input →
  //           form_fill, select → dropdown, checkbox/radio → check,
  //           everything else → click.  Customer ask: "click form fill
  //           wale button b use krein to wo b sab es pr use hun".
  const [detectedPopupItems, setDetectedPopupItems] = useState([]);
  const [selectedPopupKeys, setSelectedPopupKeys] = useState(() => new Set());
  const [popupItemActions, setPopupItemActions] = useState(() => new Map()); // idx -> "click"|"form_fill"|"dropdown"|"check"
  const [popupContainerCount, setPopupContainerCount] = useState(0);
  const [detectingPopups, setDetectingPopups] = useState(false);
  // ── 2026-01 v2.4.2 — Scan tool result modal ──
  const [scanResult, setScanResult] = useState(null); // {text, selector, xpath, xpath_stable, xpath_abs, tag, attrs, bbox}
  const [navUrl, setNavUrl] = useState("");
  const [waitMs, setWaitMs] = useState(2000);
  const [autoInsertWaits, setAutoInsertWaits] = useState(() => {
    try {
      return localStorage.getItem(LS_VR_AUTO_WAITS) === "1";
    } catch {
      return false;
    }
  });
  const [stageMarkersOn, setStageMarkersOn] = useState(false);
  const [currentStageName, setCurrentStageName] = useState("");
  const [waitAutoDetect, setWaitAutoDetect] = useState(() => {
    try {
      const v = localStorage.getItem(LS_VR_WAIT_AUTO_DETECT);
      return v === null ? true : v === "1";
    } catch {
      return true;
    }
  });
  const [waitPickTimeoutMs, setWaitPickTimeoutMs] = useState(15000);
  const [busy, setBusy] = useState(false);
  const [finalBundle, setFinalBundle] = useState(null);
  const [finalizeChecklistOpen, setFinalizeChecklistOpen] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [recentRecordings, setRecentRecordings] = useState([]);
  // ── 2026-01 (new) — Active sessions panel ─────────────────────────
  // Shows every recorder currently running under this user's account
  // so they can SEE the 5/5 cap, switch between sessions, or stop the
  // ones they don't need. Polled every 3s while on the setup screen.
  const [activeSessions, setActiveSessions] = useState([]);
  const [activeSessionStats, setActiveSessionStats] = useState({ user_session_count: 0, total_running: 0, max_concurrent: 5 });
  const [devicePreset, setDevicePreset] = useState("mobile");
  // ── 2026-01 (mobile fingerprint coherence) ──
  // Country drives locale, timezone, accept-language and geolocation
  // of the recorder browser context. Passed to /start so the recorder
  // presents the SAME fingerprint as the eventual RUT job.
  // Defaults to US — user picks via the country dropdown in setup.
  const [country, setCountry] = useState("US");
  const [pjAvailable, setPjAvailable] = useState(false);
  const [proxyProviders, setProxyProviders] = useState([]);
  const [proxyProviderId, setProxyProviderId] = useState(() => {
    try {
      return localStorage.getItem(LS_VR_PROXY_PROVIDER) || "";
    } catch {
      return "";
    }
  });
  const [saving, setSaving] = useState(false);
  const [savedToLibraryId, setSavedToLibraryId] = useState(null);

  // ── 2026-05: Edit-an-existing-template mode ─────────────────────
  // When the user clicks the "Open in Visual Recorder" (camera) icon
  // on the Uploaded Things → Automation JSON tab, the page is loaded
  // with `?edit_upload_id=X` in the URL. We then:
  //   1. Fetch that upload via /api/uploads, extract the saved
  //      automation_json + name + description + first goto.url.
  //   2. Pre-fill the Offer URL field so the user just clicks Start.
  //   3. After the recording session is ready, POST the saved steps
  //      to /visual-recorder/{sid}/import-steps — so the recorder
  //      session is seeded with the existing recording.
  //   4. When the user clicks Save-to-Library, we PATCH the original
  //      upload_id instead of POSTing a new one (preserves every
  //      RUT campaign preset that already references this template).
  // editTemplate holds the loaded upload object once /uploads returns;
  // editUploadId is the live URL-param (truthy = edit mode is active).
  const [editUploadId, setEditUploadId] = useState(null);
  const [editTemplate, setEditTemplate] = useState(null);   // {id, name, description, automation_json}
  // JSON editor state (2026-01) — when truthy, the Preview JSON block
  // turns into an editable textarea on the Recording Complete screen.
  const [editingJson, setEditingJson] = useState(false);
  const [editingJsonText, setEditingJsonText] = useState("");
  const [editingJsonError, setEditingJsonError] = useState("");
  // Live Visual Test state — when running, the finalized page shows a
  // progress overlay and re-opens the recorder so the user can watch
  // the full automation step-by-step.
  const [replayLaunching, setReplayLaunching] = useState(false);
  // ── 2026-05: Live Test + Smart Diagnostics ──
  const [liveTestResult, setLiveTestResult] = useState(null); // {ok, total_ms, step_results, diagnostics, ...}
  const [liveTesting, setLiveTesting] = useState(false);
  const [liveTestRutParity, setLiveTestRutParity] = useState(false);
  // 2026-01: Real-time step-by-step progress feed during live test.
  // Populated by polling /live-progress endpoint every ~400ms while
  // a test is running. Cleared at the start of each run.
  const [liveProgress, setLiveProgress] = useState([]);
  // 2026-01: Latest live browser screenshot (data:image/jpeg;base64,...)
  // from the most recent step event. Updated as steps execute.
  const [liveFrame, setLiveFrame] = useState(null);
  const [liveFrameMeta, setLiveFrameMeta] = useState(null);
  const [showDiagnostics, setShowDiagnostics] = useState(true);
  // ── 2026-05: Auto-fix history + auto-retest toggle ──
  // Persisted across the session so the user can: 1) Auto-fix all,
  // 2) automatically re-run Live Test, 3) Finalize — in 3 clicks
  // total. Undo button reverts the most recent fix if it broke
  // something specific to the user's page.
  const [fixHistoryCount, setFixHistoryCount] = useState(0);
  const [lastUndoneFix, setLastUndoneFix] = useState(null);
  const [autoRetestEnabled, setAutoRetestEnabled] = useState(true);
  const imgRef = useRef(null);
  const sessionStartedAt = useRef(null);
  const [recordingElapsed, setRecordingElapsed] = useState(0);
  // ── 2026-01 (multi-tab support) ─────────────────────────────────
  // Live list of all open Chromium tabs in this recorder session and
  // which one is currently active. Polled every 1.5s while
  // sessionState === "ready". When the offer page opens a new tab
  // (target="_blank" / window.open) the backend auto-promotes it,
  // so the user instantly sees the new page AND the tabs bar
  // updates to show the previous one is still available.
  const [tabs, setTabs] = useState([]);
  const [activeTabIndex, setActiveTabIndex] = useState(0);
  // 2026-06 — "Switch to Tab" picker modal. Open via the dedicated
  // button above the live preview (always visible, even when there's
  // only 1 tab) so the operator can confidently switch tabs without
  // confusion. Lists every open tab with title + URL.
  const [showTabPicker, setShowTabPicker] = useState(false);

  // ── Recent recordings (localStorage) ───────────────────────────────
  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_RECENT_KEY);
      if (raw) setRecentRecordings(JSON.parse(raw));
    } catch {}
  }, []);

  // ── 2026-05: Edit-existing-template mode bootstrap ─────────────
  // When the user lands on /visual-recorder?edit_upload_id=X (from
  // Uploaded Things → Edit-in-Recorder camera icon), fetch the saved
  // template so we can:
  //   • pre-fill the Offer URL field (extracted from the first goto
  //     step) so the user doesn't have to retype it,
  //   • show an "Editing template …" banner above the Start button,
  //   • remember the upload_id so Save-to-Library PATCHes the same
  //     row instead of creating a new one.
  // Listening on `window.location.search` (no react-router-dom dep
  // change) keeps this drop-in.
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const id = sp.get("edit_upload_id");
    if (!id) return;
    setEditUploadId(id);
    (async () => {
      try {
        const r = await fetch(`${API_URL}/api/uploads?type=automation_json`, {
          headers: authH(),
        });
        const list = await r.json();
        if (!r.ok) throw new Error(list?.detail || `HTTP ${r.status}`);
        const found = Array.isArray(list)
          ? list.find((u) => u.id === id)
          : null;
        if (!found) {
          toast.error("Template not found — it may have been deleted.");
          return;
        }
        setEditTemplate(found);
        // Pre-fill the Offer URL from the first step that mentions a
        // URL. Recorder JSONs USUALLY start with `goto`, but a lot of
        // older / hand-crafted templates start with `wait_for_load` and
        // rely on the RUT job to inject the URL at run-time. We search
        // multiple step shapes so we catch as many as possible:
        //   • {action:"goto", url:"…"}
        //   • {action:"navigate", url:"…"}        (alias used by some recorders)
        //   • {action:"wait_for_url", url:"…"}    (sometimes a substring)
        // If none match, we LEAVE the field blank — the user can
        // either type one in OR just click Start Editing (we now
        // accept blank URL in edit-mode and the recorder opens
        // about:blank so the step-list UI is still fully usable).
        try {
          const parsedSteps = JSON.parse(found.automation_json || "[]");
          if (Array.isArray(parsedSteps)) {
            const urlStep = parsedSteps.find((s) => {
              if (!s || typeof s !== "object") return false;
              if (typeof s.url !== "string") return false;
              return ["goto", "navigate", "wait_for_url"].includes(s.action);
            });
            if (urlStep && urlStep.url) {
              setUrl(urlStep.url);
            }
          }
        } catch (_pe) {
          // bad JSON — user will see error if they try to import. Don't
          // surface here to avoid spurious toasts on page load.
        }
        toast.info(
          `🔧 Editing template: ${found.name} — start recording to load existing steps`,
          { duration: 6000 },
        );
      } catch (e) {
        toast.error(`Could not load template: ${e.message || e}`);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 2026-01 (new) — Active sessions list (poll while on setup) ────
  const refreshActiveSessions = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/sessions`, {
        headers: authH(),
      });
      if (!r.ok) return;
      const d = await r.json();
      setActiveSessions(Array.isArray(d.sessions) ? d.sessions : []);
      setActiveSessionStats({
        user_session_count: d.user_session_count || 0,
        total_running: d.total_running || 0,
        max_concurrent: d.max_concurrent || 5,
      });
    } catch {}
  }, []);

  useEffect(() => {
    if (setupStage !== "setup") return;
    refreshActiveSessions();
    const t = setInterval(refreshActiveSessions, 3000);
    return () => clearInterval(t);
  }, [setupStage, refreshActiveSessions]);

  // Switch to an existing session (minimize/restore flow). Does NOT
  // stop the current session — just hops the UI over to render the
  // other one. The original session continues running in the
  // background; the user can come back any time via the same panel.
  const switchToSession = useCallback((sess) => {
    if (!sess || !sess.session_id) return;
    setSessionId(sess.session_id);
    setViewport(sess.viewport || { width: 412, height: 914 });
    setSessionState(sess.state || "starting");
    setSessionError(sess.error_message || "");
    setShotTick(0);
    setShotErrorCount(0);
    setSteps([]);  // refreshState will repopulate
    setSetupStage("recording");
    toast.success(`Switched to recorder · ${(() => { try { return new URL(sess.current_url || sess.url).hostname; } catch { return (sess.url || "").slice(0, 30); } })()}`);
  }, []);

  // Stop a specific session from the list (without leaving setup stage).
  const stopSessionById = useCallback(async (sid, hostnameLabel) => {
    if (!sid) return;
    if (!await vrConfirm(`Stop this recorder session?${hostnameLabel ? `\n\n${hostnameLabel}` : ""}\n\nAny unsaved steps in this session will be lost.`)) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sid}`, {
        method: "DELETE",
        headers: authH(),
      });
      toast.success("Session stopped");
      refreshActiveSessions();
    } catch (e) {
      toast.error(`Failed to stop: ${e?.message || e}`);
    }
  }, [refreshActiveSessions]);

  const pushRecent = (item) => {
    try {
      const next = [item, ...recentRecordings.filter((r) => r.url !== item.url)].slice(0, 5);
      setRecentRecordings(next);
      localStorage.setItem(LS_RECENT_KEY, JSON.stringify(next));
    } catch {}
  };

  // v2.6.2 — Load enabled Proxy Providers (Settings › Proxy Providers)
  // for the provider dropdown + one-click "From Provider" fetch.
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_URL}/api/proxy-providers`, { headers: authH() });
        if (r.ok) {
          const list = await r.json();
          const enabled = Array.isArray(list) ? list.filter(p => p.enabled !== false) : [];
          setProxyProviders(enabled);
          setPjAvailable(enabled.length > 0);
        }
      } catch {}
    })();
  }, []);

  const onProxyProviderChange = (id) => {
    setProxyProviderId(id);
    try {
      if (id) localStorage.setItem(LS_VR_PROXY_PROVIDER, id);
      else localStorage.removeItem(LS_VR_PROXY_PROVIDER);
    } catch {}
  };

  // ── Live recording-elapsed counter ─────────────────────────────────
  useEffect(() => {
    if (setupStage !== "recording" || sessionState !== "ready") {
      sessionStartedAt.current = null;
      setRecordingElapsed(0);
      return;
    }
    if (!sessionStartedAt.current) sessionStartedAt.current = Date.now();
    const t = setInterval(() => {
      if (sessionStartedAt.current) {
        setRecordingElapsed(Math.floor((Date.now() - sessionStartedAt.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(t);
  }, [setupStage, sessionState]);

  // v2.6.2 — Fetch ONE fresh proxy from the selected provider
  // (generic — works for any provider kind).
  const useProxyJetProxy = async () => {
    if (!proxyProviderId) {
      toast.error("Select a Proxy Provider above, or add one in Settings › Proxy Providers");
      return;
    }
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/proxy-providers/${proxyProviderId}/generate-batch`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ count: 1, country }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const line = d.proxies?.[0] || d.lines?.[0];
      if (line) {
        setProxy(line);
        toast.success(`Fresh proxy loaded from provider`);
      } else {
        toast.error("No proxy returned by provider");
      }
    } catch (e) {
      toast.error(e.message || "Provider fetch failed");
    } finally {
      setBusy(false);
    }
  };

  // ── Excel header parsing ──────────────────────────────────────────
  const coerceExcelCell = (header, v) => {
    const h = String(header || "").toLowerCase();
    if (/zip|postal|postcode/.test(h)) {
      if (typeof v === "number" && Number.isFinite(v)) {
        return String(Math.round(v)).padStart(5, "0");
      }
      const digits = String(v).replace(/\D/g, "");
      if (digits.length >= 5) return digits.slice(0, 5);
      if (digits.length > 0) return digits.padStart(5, "0");
    }
    if (typeof v === "number" && Number.isFinite(v) && /year|day|month|dob/.test(h)) {
      return String(Math.round(v));
    }
    return v;
  };

  const onExcelUpload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setExcelFile(f);
    try {
      const buf = await f.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array" });
      const ws = wb.Sheets[wb.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
      const rawHdrRow = rows[0] || [];
      const hdr = rawHdrRow
        .map((h) => String(h ?? "").trim())
        .filter(Boolean);
      setHeaders(hdr);
      setHeadersInput(hdr.join(", "));
      // Build sample_row using ORIGINAL column indices so empty header
      // columns in row 1 do not shift zip_code → wrong cell values.
      const first = rows[1] || [];
      const sample = {};
      rawHdrRow.forEach((h, colIdx) => {
        const name = String(h ?? "").trim();
        if (!name) return;
        const v = first[colIdx];
        if (v !== undefined && v !== null && String(v).trim() !== "") {
          sample[name] = coerceExcelCell(name, v);
        }
      });
      setSampleRow(sample);
      const sampleCount = Object.keys(sample).length;
      toast.success(
        `Detected ${hdr.length} columns: ${hdr.slice(0, 5).join(", ")}${hdr.length > 5 ? "…" : ""}` +
        (sampleCount > 0 ? ` · using ${sampleCount} sample values for live form-fill` : "")
      );
    } catch (err) {
      toast.error(`Excel parse failed: ${err.message}`);
    }
  };

  const applyManualHeaders = () => {
    const arr = headersInput
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setHeaders(arr);
    if (arr.length) toast.success(`${arr.length} headers ready`);
  };

  // ── 2026-06 — Client-side image compression for the AI dialog. ────
  // Why: the Kubernetes ingress in front of preview / cloud backends
  // enforces a 1 MiB request-body limit. A single high-DPI page
  // screenshot is typically 2-5 MiB, so the request gets rejected at
  // the EDGE (returns HTTP 502 before FastAPI even sees it). Shrinking
  // each image to max 1600px and JPEG q=0.82 reliably brings the total
  // payload below the limit while keeping the page readable enough
  // for the multimodal LLM to extract form fields / buttons.
  const compressImageFile = (file, { maxDim = 1600, quality = 0.82 } = {}) => new Promise((resolve, reject) => {
    if (!file.type.startsWith("image/")) { resolve(file); return; }
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const ratio = Math.min(1, maxDim / Math.max(img.width, img.height));
      const w = Math.round(img.width * ratio);
      const h = Math.round(img.height * ratio);
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(img, 0, 0, w, h);
      canvas.toBlob((blob) => {
        if (!blob) { resolve(file); return; }
        // Only swap if compressed is actually smaller
        if (blob.size >= file.size) { resolve(file); return; }
        const newName = (file.name || "image").replace(/\.(png|webp|heic|heif|jpeg|jpg)$/i, "") + ".jpg";
        resolve(new File([blob], newName, { type: "image/jpeg", lastModified: Date.now() }));
      }, "image/jpeg", quality);
    };
    img.onerror = (e) => {
      URL.revokeObjectURL(url);
      reject(e);
    };
    img.src = url;
  });

  // ── 2026-06 — AI Step Generator handler ──────────────────────────
  // v2.6.2 — Fetch a fresh proxy from the user's default Proxy
  // Provider directly into the AI dialog's local proxy field.
  const aiUseProxyJet = async () => {
    if (!proxyProviderId) {
      toast.error("Select a Proxy Provider above, or add one in Settings › Proxy Providers");
      return;
    }
    setAiProxyJetBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/proxy-providers/${proxyProviderId}/generate-batch`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ count: 1, country }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const line = d.proxies?.[0] || d.lines?.[0];
      if (line) {
        setAiProxy(line);
        toast.success(`Fresh proxy loaded from provider into AI dialog`);
      } else {
        toast.error("No proxy returned by provider");
      }
    } catch (e) {
      toast.error(e.message || "Provider fetch failed");
    } finally {
      setAiProxyJetBusy(false);
    }
  };

  // ── 2026-06 — AI Refine handler ──────────────────────────────────
  // Send the current step-list + a natural-language instruction to the
  // backend's refine endpoint. Swap returned steps in. Keep the
  // previous step-list in `aiRefinePrevSteps` so the user can Undo.
  const handleAiRefine = async () => {
    if (!aiRefineInstruction.trim()) {
      setAiRefineError("Please describe what to change (e.g. 'survey ke jawab har visit pe random karen').");
      return;
    }
    if (!steps || steps.length === 0) {
      setAiRefineError("Pehle koi steps generate ya record karen, phir refine kar sakte hain.");
      return;
    }
    setAiRefineBusy(true);
    setAiRefineError("");
    try {
      const payload = {
        steps,
        instruction: aiRefineInstruction.trim(),
        target_url: url || undefined,
        excel_columns: (headers && headers.length) ? headers : undefined,
      };
      const r = await fetch(`${API_URL}/api/visual-recorder/ai-refine-steps`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("token")}`,
        },
        body: JSON.stringify(payload),
      });
      if (r.status === 502 || r.status === 504) {
        setAiRefineError(`Backend gateway error (HTTP ${r.status}). 30 second wait karke dobara try karen.`);
        return;
      }
      const data = await r.json().catch(() => ({}));
      if (!r.ok || data.status !== "ok") {
        const err = data?.detail || data?.error || `HTTP ${r.status}`;
        setAiRefineError(typeof err === "string" ? err : JSON.stringify(err));
        return;
      }
      const refined = Array.isArray(data.steps) ? data.steps : [];
      if (!refined.length) {
        setAiRefineError("AI ne empty step-list return ki. Try a more specific instruction.");
        return;
      }
      setAiRefinePrevSteps(steps);  // remember for undo
      setSteps(refined);
      toast.success(
        `${data.provider_display || "AI"} updated ${refined.length} steps — review the diff above. "Undo" se previous version par jayen.`
      );
      setAiRefineInstruction("");
      // Keep panel open so user can chain instructions or undo
    } catch (e) {
      setAiRefineError(e.message || String(e));
    } finally {
      setAiRefineBusy(false);
    }
  };

  const handleAiRefineUndo = () => {
    if (!aiRefinePrevSteps) return;
    setSteps(aiRefinePrevSteps);
    setAiRefinePrevSteps(null);
    toast.success("Refine undone — pichli steps wapas restore ho gayin");
  };

  const handleAiGenerate = async () => {
    if (!aiFiles.length) {
      setAiError("Please attach at least one screenshot (or a short demo video).");
      return;
    }
    setAiBusy(true);
    setAiError("");
    setAiProviderUsed("");
    try {
      // 2026-06 — Compress images BEFORE upload so we never trip the
      // 1 MiB ingress body limit (which would return 502 before
      // FastAPI even sees the request, giving the user a useless
      // generic error). Videos are passed through untouched.
      const compressed = [];
      let totalBytes = 0;
      for (const f of aiFiles) {
        let out = f;
        if (f.type.startsWith("image/")) {
          try { out = await compressImageFile(f); } catch { out = f; }
        }
        compressed.push(out);
        totalBytes += out.size;
      }
      // Hard cap: if total payload >7 MiB we shrink images more
      // aggressively (cap at ~900 KiB each before any further trim).
      const MAX_TOTAL = 7 * 1024 * 1024;
      if (totalBytes > MAX_TOTAL) {
        const re = [];
        for (const f of compressed) {
          if (f.type.startsWith("image/") && f.size > 900 * 1024) {
            try {
              const tiny = await compressImageFile(f, { maxDim: 1100, quality: 0.7 });
              re.push(tiny);
            } catch {
              re.push(f);
            }
          } else {
            re.push(f);
          }
        }
        compressed.splice(0, compressed.length, ...re);
        totalBytes = compressed.reduce((a, x) => a + x.size, 0);
      }
      if (totalBytes > 15 * 1024 * 1024) {
        setAiError(`Total upload size is ${(totalBytes/1024/1024).toFixed(1)} MiB — please remove the video or use fewer screenshots (max ~15 MiB).`);
        return;
      }

      const fd = new FormData();
      for (const f of compressed) fd.append("files", f);
      if (aiTargetUrl.trim()) fd.append("target_url", aiTargetUrl.trim());
      if (aiDescription.trim()) fd.append("description", aiDescription.trim());
      if (aiExcelCols.trim()) fd.append("excel_columns", aiExcelCols.trim());
      else if (headers && headers.length) fd.append("excel_columns", headers.join(","));
      const r = await fetch(`${API_URL}/api/visual-recorder/ai-generate-steps`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
        body: fd,
      });
      // 2026-06 — Graceful handling for edge-level failures.
      // 502/504 happen at the Kubernetes ingress when (a) backend is
      // restarting, (b) request body exceeds ingress client_max_body
      // limit (rare after our client-side compression above), or (c)
      // the upstream LLM provider call exceeds the ingress timeout.
      // 413 = Payload Too Large (ingress) — we surface it explicitly
      // so the user knows to reduce screenshot count / video size.
      if (r.status === 502 || r.status === 504) {
        setAiError(
          `Backend gateway error (HTTP ${r.status}). Yeh aksar tab hota hai jab AI call bohat lambi ho jaaye ya server abhi restart par ho. 30 second wait karke dobara try karein, ya doosra provider (Gemini / OpenAI / Claude) select karen jiska key chhota response deta hai.`
        );
        toast.error(`Gateway error HTTP ${r.status} — retry in 30s`);
        return;
      }
      if (r.status === 413) {
        setAiError("Upload size too large for the server. Please use fewer / smaller screenshots, or upload only one short MP4 video.");
        toast.error("Upload too large — reduce screenshot count");
        return;
      }
      const data = await r.json().catch(() => ({}));
      if (!r.ok || data.status !== "ok") {
        const err = data?.detail || data?.error || `HTTP ${r.status}`;
        setAiError(typeof err === "string" ? err : JSON.stringify(err));
        toast.error(`AI generation failed — ${err}`);
        setAiProviderUsed(data?.provider_display || data?.provider || "");
        return;
      }
      const generated = Array.isArray(data.steps) ? data.steps : [];
      if (!generated.length) {
        setAiError("AI returned an empty step list. Try a more detailed description or clearer screenshots.");
        return;
      }
      if (data.lint_ok === false && data.lint_error_summary) {
        setAiError(`AI steps generated but lint found issues: ${data.lint_error_summary}`);
        toast.warning("Generated steps have lint errors — review before recording.");
      }
      setAiProviderUsed(data.provider_display || data.provider || "");
      // Replace the current draft with the AI-generated steps. The
      // user can still Start Recording on top and edit each step.
      setSteps(generated);

      // 2026-06 — Propagate AI dialog's selections to the main setup
      // screen so "Start Recording" (and the eventual recording) uses
      // them automatically. Target URL is copied only if the main
      // `url` field is empty (don't trample manual input).
      if (aiProxy.trim()) {
        setProxy(aiProxy.trim());
      }
      if (aiTargetUrl.trim() && !url.trim()) {
        setUrl(aiTargetUrl.trim());
      }

      const proxyNote = aiProxy.trim() ? " · Proxy applied to setup" : "";
      const providerLabel = data.provider_display || data.provider || "AI";
      toast.success(
        `${providerLabel} generated ${generated.length} steps${proxyNote} — review & Start Recording to refine.`
      );
      setAiDialogOpen(false);
      // Reset form so next open starts clean
      setAiFiles([]);
      setAiDescription("");
      setAiTargetUrl("");
      setAiExcelCols("");
      setAiProxy("");
    } catch (e) {
      setAiError(e.message || String(e));
      toast.error(`AI generation error: ${e.message || e}`);
    } finally {
      setAiBusy(false);
    }
  };

  // ── Recording session ─────────────────────────────────────────────
  const startRecording = async () => {
    // ── 2026-05: In edit-mode the URL field is OPTIONAL ──
    // The user is editing an existing step list. They can fully use
    // the step-management UI (reorder / delete / rename / edit-step
    // modal / append manual-step / save) without ever needing a live
    // browser page. If they DO want to add new recorded clicks, they
    // can navigate the recorder browser to any URL via the existing
    // Navigate textbox after the session is ready. We default to
    // about:blank so the recorder still has a target — Chromium opens
    // a blank tab instantly, no proxy slowdown.
    const effectiveUrl = url.trim() || (editUploadId ? "about:blank" : "");
    if (!effectiveUrl) {
      toast.error("URL required");
      return;
    }
    setBusy(true);
    setSessionError("");
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/start`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          url: effectiveUrl,
          proxy: proxy.trim() || null,
          proxy_provider_id: proxyProviderId || null,
          user_agent: ua.trim() || null,
          headers: headers,
          // 2026-05: pass first data row so form inputs auto-fill
          // during recording (lets the user submit forms and continue
          // recording on the post-submit page)
          sample_row: Object.keys(sampleRow || {}).length ? sampleRow : null,
          // ── 2026-01 (mobile fingerprint coherence) ──
          // Pass the device + country choices so the recorder browser
          // presents the SAME fingerprint that the eventual RUT job
          // will use. Without these the recorder hardcoded
          // mobile+en-US+NY → advertiser detected mismatch with the UA.
          device_type: (devicePreset === "mobile" || devicePreset === "tablet")
            ? devicePreset
            : (devicePreset === "desktop" ? "desktop" : "auto"),
          country: (country || "").toLowerCase(),
          auto_insert_waits: !!autoInsertWaits,
        }),
      });
      const d = await r.json();
      if (!r.ok) {
        // FastAPI can return detail as string, object, or array of validation errors.
        // Normalise so the toast never shows "[object Object]".
        let detailMsg = "";
        if (typeof d.detail === "string") {
          detailMsg = d.detail;
        } else if (Array.isArray(d.detail)) {
          detailMsg = d.detail
            .map((it) => (it && (it.msg || it.message)) ? `${it.msg || it.message}${it.loc ? ` (${it.loc.join('.')})` : ''}` : JSON.stringify(it))
            .join("; ");
        } else if (d.detail && typeof d.detail === "object") {
          detailMsg = d.detail.msg || d.detail.message || JSON.stringify(d.detail);
        }
        throw new Error(detailMsg || `HTTP ${r.status}`);
      }
      setSessionId(d.session_id);
      setViewport(d.viewport);
      setSessionState(d.state || "starting");
      setConnectElapsed(0);
      setSetupStage("recording");
      toast.success("Recording session created — connecting…");
      // ── 2026-05: Edit-mode — auto-import the saved steps so the user
      // can continue from where the original recording left off. The
      // session is "starting" at this point; the import-steps endpoint
      // does NOT need a ready page (it just appends to sess.steps).
      // After session reaches "ready" the user can immediately reorder,
      // re-record over, delete, or append new steps.
      if (editUploadId && editTemplate?.automation_json) {
        try {
          let parsedSteps = JSON.parse(editTemplate.automation_json);
          if (!Array.isArray(parsedSteps)) parsedSteps = [];
          const importRes = await fetch(
            `${API_URL}/api/visual-recorder/${d.session_id}/import-steps`,
            {
              method: "POST",
              headers: authH(),
              body: JSON.stringify({ steps: parsedSteps }),
            },
          );
          if (!importRes.ok) {
            const ie = await importRes.json().catch(() => ({}));
            throw new Error(ie.detail || `HTTP ${importRes.status}`);
          }
          toast.success(
            `✓ Loaded ${parsedSteps.length} step${parsedSteps.length === 1 ? "" : "s"} from "${editTemplate.name}" — edit freely, Save to update`,
            { duration: 6000 },
          );
        } catch (impErr) {
          toast.error(`Could not load existing steps: ${impErr.message || impErr}`);
        }
      }
      // Save to recent recordings (localStorage) for one-click re-use
      pushRecent({
        url: url.trim(),
        proxy: proxy.trim() || null,
        ua: ua.trim() || null,
        headers,
        device: devicePreset,
        ts: Date.now(),
      });
    } catch (e) {
      let msg = e && e.message ? e.message : "";
      if (!msg || msg === "[object Object]") {
        try { msg = typeof e === "string" ? e : JSON.stringify(e); } catch { msg = String(e); }
      }
      toast.error(`Start failed: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const refreshState = useCallback(async () => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/state`, {
        headers: authH(),
      });
      if (!r.ok) return;
      const d = await r.json();
      setSteps(d.steps || []);
      setPageMeta(d.page || { url: "", title: "" });
      if (d.state) setSessionState(d.state);
      if (d.state === "error") setSessionError(d.error_message || "Unknown error");
      if (typeof d.elapsed_seconds === "number") setConnectElapsed(d.elapsed_seconds);
      if (typeof d.auto_insert_waits === "boolean") {
        setAutoInsertWaits(d.auto_insert_waits);
        try {
          localStorage.setItem(LS_VR_AUTO_WAITS, d.auto_insert_waits ? "1" : "0");
        } catch { /* quota / private mode */ }
      }
      if (typeof d.stage_markers_enabled === "boolean") {
        setStageMarkersOn(d.stage_markers_enabled);
      }
      if (typeof d.current_stage === "string") {
        setCurrentStageName(d.current_stage || "");
      }
    } catch {}
  }, [sessionId]);

  const setAutoInsertWaitsPref = async (enabled) => {
    setAutoInsertWaits(enabled);
    try {
      localStorage.setItem(LS_VR_AUTO_WAITS, enabled ? "1" : "0");
    } catch { /* quota / private mode */ }
    if (!sessionId) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/settings`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ auto_insert_waits: !!enabled }),
      });
    } catch { /* best effort */ }
  };

  const setStageMarkersPref = async (enabled) => {
    setStageMarkersOn(enabled);
    if (!enabled) setCurrentStageName("");
    if (!sessionId) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/settings`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ stage_markers_enabled: !!enabled }),
      });
    } catch { /* best effort */ }
  };

  const addNewStageMarker = async () => {
    if (!sessionId) {
      toast.error("Start a recording session first");
      return;
    }
    if (!stageMarkersOn) {
      await setStageMarkersPref(true);
    }
    const name = (await vrPrompt(
      "Stage name (e.g. Questions, Email, Form fill, Survey, Deals):",
      currentStageName || "Form fill"
    ) || "").trim();
    if (!name) return;
    const detectKind = (await vrPrompt(
      "Open-when detect? none / selector / text / url\n(none = always run this stage; selector/text/url = skip whole stage if not found)",
      name.toLowerCase().includes("form") ? "selector" : "none"
    ) || "none").trim().toLowerCase();
    let open_when = null;
    if (detectKind === "selector" || detectKind === "css") {
      const sel = (await vrPrompt(
        "CSS/XPath that ONLY appears when this stage is open (e.g. input[name=first_name]):",
        "input[name=first_name]"
      ) || "").trim();
      const tmo = Math.max(1000, Number(await vrPrompt("Detect timeout ms:", "5000")) || 5000);
      if (sel) open_when = { type: "selector_visible", selector: sel, timeout_ms: tmo };
    } else if (detectKind === "text") {
      const txt = (await vrPrompt("Text that ONLY appears when this stage is open:", "First Name") || "").trim();
      const tmo = Math.max(1000, Number(await vrPrompt("Detect timeout ms:", "5000")) || 5000);
      if (txt) open_when = { type: "text_visible", text: txt, timeout_ms: tmo };
    } else if (detectKind === "url") {
      const part = (await vrPrompt("URL must contain:", "/form") || "").trim();
      const tmo = Math.max(1000, Number(await vrPrompt("Detect timeout ms:", "5000")) || 5000);
      if (part) open_when = { type: "url_contains", value: part, timeout_ms: tmo };
    }
    const step = {
      action: "stage",
      name,
      stage: name,
      skip_if_not_open: true,
      source: "manual",
    };
    if (open_when) step.open_when = open_when;
    setBusy(true);
    try {
      await setStageMarkersPref(true);
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/manual-step`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ step }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.added === false) {
        toast.error(d.detail || d.reason || "Could not add stage");
        return;
      }
      setCurrentStageName(name);
      await refreshState();
      toast.success(
        open_when
          ? `Stage "${name}" added — will SKIP whole block if detect fails`
          : `Stage "${name}" added — always runs (no detect)`
      );
    } catch (e) {
      toast.error(e.message || "Add stage failed");
    } finally {
      setBusy(false);
    }
  };

  const setWaitAutoDetectPref = (enabled) => {
    setWaitAutoDetect(enabled);
    try {
      localStorage.setItem(LS_VR_WAIT_AUTO_DETECT, enabled ? "1" : "0");
    } catch { /* quota / private mode */ }
    if (!enabled && ["wait_for_text_pick", "wait_for_selector_pick", "wait_for_xpath_pick", "extract_pick"].includes(tool)) {
      setTool("default");
    }
  };

  const startWaitPick = (pickTool, label) => {
    if (!sessionId || sessionState !== "ready") {
      toast.error("Start a recording session first");
      return;
    }
    setTool(pickTool);
    toast.info(`${label} — page par element/text par click karein (Esc cancel)`);
  };

  const postWaitPickAt = async (endpoint, x, y, successLabel) => {
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/${endpoint}`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          x: Math.round(x),
          y: Math.round(y),
          timeout_ms: Math.max(500, Number(waitPickTimeoutMs) || 15000),
        }),
      });
      const d = await r.json();
      if (!r.ok || d.recorded === false) {
        toast.error(d.error || d.detail || "Could not add wait step");
        return false;
      }
      const hint = d.step?.text || d.step?.hint_text || d.step?.selector || "";
      toast.success(`${successLabel}${hint ? ` — "${String(hint).slice(0, 40)}"` : ""}`);
      refreshState();
      return true;
    } catch (err) {
      toast.error(err.message || "Wait pick failed");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const refreshScreenshot = useCallback(() => {
    if (!sessionId) return;
    // Just bump the tick → <img> re-fetches via cache-busting URL.
    setShotTick((t) => t + 1);
  }, [sessionId]);

  // Poll state always (covers connecting + recording).
  useEffect(() => {
    if (setupStage !== "recording" || !sessionId) return;
    refreshState();
    const t1 = setInterval(refreshState, 1000);
    return () => clearInterval(t1);
  }, [setupStage, sessionId, refreshState]);

  // Tick screenshot URL once per second when ready
  useEffect(() => {
    if (setupStage !== "recording" || !sessionId || sessionState !== "ready") return;
    setShotTick((x) => x + 1);
    const t = setInterval(() => setShotTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [setupStage, sessionId, sessionState]);

  // ── 2026-01 (multi-tab) — Poll the tabs list every 1.5s ─────────
  // Picks up newly opened popups / target="_blank" tabs the offer
  // page spawns. The user sees the tabs strip update + the live
  // preview auto-switches to the new tab (backend promotes it).
  useEffect(() => {
    if (setupStage !== "recording" || !sessionId || sessionState !== "ready") return;
    let cancelled = false;
    const pollTabs = async () => {
      try {
        const r = await fetch(
          `${API_URL}/api/visual-recorder/${sessionId}/tabs`,
          { headers: authH() },
        );
        if (!r.ok) return;
        const d = await r.json();
        if (cancelled) return;
        if (Array.isArray(d.tabs)) setTabs(d.tabs);
        if (typeof d.active_index === "number") setActiveTabIndex(d.active_index);
      } catch {}
    };
    pollTabs();
    const t = setInterval(pollTabs, 1500);
    return () => { cancelled = true; clearInterval(t); };
  }, [setupStage, sessionId, sessionState]);

  // ── v2.1.74 — JS dialog (alert/confirm/prompt) capture banner ─────
  // While recording, if the offer page fires alert() / confirm() /
  // prompt() the backend parks it. We poll for it and pop a banner
  // with Accept / Dismiss buttons + a text input for prompt(). When
  // the user picks, we POST /dialog/answer which both resolves the
  // Playwright dialog AND appends an accept_dialog / dismiss_dialog
  // step so RUT replay reproduces the same choice.
  const [pendingDialog, setPendingDialog] = useState(null);
  const [dialogPromptText, setDialogPromptText] = useState("");
  useEffect(() => {
    if (setupStage !== "recording" || !sessionId || sessionState !== "ready") return;
    let cancelled = false;
    const pollDialog = async () => {
      try {
        const r = await fetch(
          `${API_URL}/api/visual-recorder/${sessionId}/dialog`,
          { headers: authH() },
        );
        if (!r.ok) return;
        const d = await r.json();
        if (cancelled) return;
        if (d && d.pending) {
          setPendingDialog((prev) => prev || d);
          if (d.type === "prompt") setDialogPromptText((cur) => cur || d.default_value || "");
        } else {
          setPendingDialog(null);
          setDialogPromptText("");
        }
      } catch {}
    };
    pollDialog();
    const t = setInterval(pollDialog, 700);
    return () => { cancelled = true; clearInterval(t); };
  }, [setupStage, sessionId, sessionState]);

  const answerDialog = useCallback(async (decision) => {
    if (!sessionId || !pendingDialog) return;
    try {
      const body = { decision };
      if (pendingDialog.type === "prompt" && decision === "accept") {
        body.prompt_text = dialogPromptText;
      }
      const r = await fetch(
        `${API_URL}/api/visual-recorder/${sessionId}/dialog/answer`,
        {
          method: "POST",
          headers: { ...authH(), "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      const d = await r.json();
      if (!r.ok || !d.ok) {
        toast.error(`Dialog answer failed: ${d.error || d.detail || "unknown"}`);
        return;
      }
      setPendingDialog(null);
      setDialogPromptText("");
      toast.success(`Dialog ${decision === "accept" ? "accepted" : "dismissed"} — step recorded`);
      // Force step list refresh
      setShotTick((x) => x + 1);
    } catch (err) {
      toast.error(`Dialog answer failed: ${err.message || err}`);
    }
  }, [sessionId, pendingDialog, dialogPromptText]);

  // ── 2026-01 (multi-tab) — switch / close tab actions ────────────
  const switchTab = useCallback(async (index) => {
    if (!sessionId || index === activeTabIndex) return;
    try {
      const r = await fetch(
        `${API_URL}/api/visual-recorder/${sessionId}/tabs/${index}/activate`,
        { method: "POST", headers: authH() },
      );
      const d = await r.json();
      if (!r.ok || !d.ok) {
        toast.error(`Switch tab failed: ${d.error || d.detail || "unknown"}`);
        return;
      }
      setActiveTabIndex(index);
      // Force screenshot refresh on next tick
      setShotTick((x) => x + 1);
    } catch (err) {
      toast.error(`Switch tab failed: ${err.message || err}`);
    }
  }, [sessionId, activeTabIndex]);

  const closeTab = useCallback(async (index, e) => {
    if (e) { e.stopPropagation(); e.preventDefault(); }
    if (!sessionId) return;
    if (tabs.length <= 1) {
      toast.error("Cannot close the last tab");
      return;
    }
    try {
      const r = await fetch(
        `${API_URL}/api/visual-recorder/${sessionId}/tabs/${index}/close`,
        { method: "POST", headers: authH() },
      );
      const d = await r.json();
      if (!r.ok || !d.ok) {
        toast.error(`Close tab failed: ${d.error || d.detail || "unknown"}`);
        return;
      }
      setShotTick((x) => x + 1);
    } catch (err) {
      toast.error(`Close tab failed: ${err.message || err}`);
    }
  }, [sessionId, tabs.length]);

  // ── Keyboard shortcuts ─────────────────────────────────────────────
  // 1-8  → switch tool
  // Esc  → cancel any pending binding (form-fill / dropdown / random)
  // Ctrl/Cmd+Z → undo last step
  // Ctrl/Cmd+Enter → finalize (if ≥ 2 steps)
  // Ignored when focus is in an <input>/<textarea>/contenteditable so
  // typing inside the URL / Excel / wait-ms fields is never hijacked.
  useEffect(() => {
    if (setupStage !== "recording") return;
    const onKey = (e) => {
      const target = e.target;
      const tag = (target?.tagName || "").toUpperCase();
      const editable =
        tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable;
      const ctrl = e.ctrlKey || e.metaKey;

      // Ctrl+Z anywhere (except editable fields) — undo last step
      if (!editable && ctrl && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undoLastStep();
        return;
      }
      // Ctrl+Enter — finalize
      if (!editable && ctrl && e.key === "Enter") {
        e.preventDefault();
        if (steps.length >= 2 && !busy) requestFinalize();
        return;
      }
      // Esc — cancel pending bindings
      if (e.key === "Escape") {
        if (pendingFormFill) { setPendingFormFill(null); e.preventDefault(); return; }
        if (pendingOptionButtons.length) { setPendingOptionButtons([]); e.preventDefault(); return; }
        if (pendingDropdown) { setPendingDropdownQueue([]); e.preventDefault(); return; }
        if (pendingRandom.length) { setPendingRandom([]); e.preventDefault(); return; }
        if (["wait_for_text_pick", "wait_for_selector_pick", "wait_for_xpath_pick", "extract_pick"].includes(tool)) {
          setTool("default");
          toast.info("Auto-detect wait cancelled");
          e.preventDefault();
          return;
        }
        if (detectedClickables.length || selectedRandomKeys.size) {
          setDetectedClickables([]);
          setSelectedRandomKeys(new Set());
          e.preventDefault();
          return;
        }
      }
      // 1-9 — switch tool (only when nothing has focus)
      if (!editable && !ctrl && /^[1-9]$/.test(e.key)) {
        const t = TOOLS[Number(e.key) - 1];
        if (t) {
          setTool(t.id);
          if (t.id !== "random" && t.id !== "random_click") {
            setPendingRandom([]);
            setDetectedClickables([]);
            setSelectedRandomKeys(new Set());
          } else {
            // Re-trigger auto-detect when switching via keyboard
            detectClickables();
          }
          if (t.id === "popup_work") {
            detectPopupButtons();
          } else {
            setDetectedPopupItems([]);
            setSelectedPopupKeys(new Set());
            setPopupItemActions(new Map());
            setPopupContainerCount(0);
          }
          e.preventDefault();
        }
      }
      // 2026-01 v2.4.2 — "p" → Popup Work, "s" → Scan (keys chosen so
      // they don't collide with the numeric 1-9 shortcuts).
      if (!editable && !ctrl && (e.key === "p" || e.key === "P")) {
        setTool("popup_work");
        setPendingRandom([]);
        setDetectedClickables([]);
        setSelectedRandomKeys(new Set());
        detectPopupButtons();
        e.preventDefault();
      } else if (!editable && !ctrl && (e.key === "s" || e.key === "S")) {
        setTool("scan");
        setPendingRandom([]);
        setDetectedClickables([]);
        setSelectedRandomKeys(new Set());
        setDetectedPopupItems([]);
        setSelectedPopupKeys(new Set());
        setPopupItemActions(new Map());
        e.preventDefault();
      } else if (!editable && !ctrl && (e.key === "c" || e.key === "C")) {
        setTool("option_pick");
        setPendingRandom([]);
        setDetectedClickables([]);
        setSelectedRandomKeys(new Set());
        setDetectedPopupItems([]);
        setSelectedPopupKeys(new Set());
        setPopupItemActions(new Map());
        setPendingOptionButtons([]);
        e.preventDefault();
      } else if (!editable && !ctrl && (e.key === "g" || e.key === "G")) {
        setTool("option_pick");
        setPendingRandom([]);
        setDetectedClickables([]);
        setSelectedRandomKeys(new Set());
        setDetectedPopupItems([]);
        setSelectedPopupKeys(new Set());
        setPopupItemActions(new Map());
        setPendingOptionButtons([]);
        e.preventDefault();
      } else if (!editable && !ctrl && (e.key === "w" || e.key === "W")) {
        // 2026-07 v2.5.4 — "w" → Wait for Button tool
        setTool("wait_for_button");
        setPendingRandom([]);
        setDetectedClickables([]);
        setSelectedRandomKeys(new Set());
        setDetectedPopupItems([]);
        setSelectedPopupKeys(new Set());
        setPopupItemActions(new Map());
        e.preventDefault();
      } else if (!editable && !ctrl && (e.key === "t" || e.key === "T")) {
        setTool("manual_type");
        setPendingRandom([]);
        setDetectedClickables([]);
        setSelectedRandomKeys(new Set());
        setDetectedPopupItems([]);
        setSelectedPopupKeys(new Set());
        setPopupItemActions(new Map());
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setupStage, steps.length, busy, pendingFormFill, pendingOptionButtons, pendingDropdown, pendingRandom]);

  // Format the live recording timer as mm:ss
  const fmtTimer = (sec) => {
    const m = Math.floor(sec / 60).toString().padStart(2, "0");
    const s = (sec % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  // ── 2026-06 — Electron-safe vrPrompt / vrConfirm helpers ─────────
  // Drop-in async replacements for window.prompt / window.confirm.
  // Electron Renderer no longer ships prompt(), so calls would throw
  // "prompt() is and will not be supported." and silently break the
  // toolbar buttons that depended on them (capture name, wait-for-
  // selector text, extract var, captcha pause reason, file upload
  // paths, OTP digits, branch conditions, iframe selector, zoom level,
  // clipboard text, right-click coords, etc.).
  //
  // vrPrompt(message, defaultValue) returns Promise<string|null> —
  //   null when the user cancels (mirrors native prompt() behaviour).
  // vrConfirm(message)              returns Promise<boolean>.
  // Both also work in the regular browser, so the same code path
  // serves both cloud and Electron deployments without branching.
  const vrPrompt = (message, defaultValue = "") =>
    new Promise((resolve) => {
      setPromptModal({
        kind: "prompt",
        message: String(message || ""),
        defaultValue: defaultValue == null ? "" : String(defaultValue),
        resolve,
      });
    });
  const vrConfirm = (message) =>
    new Promise((resolve) => {
      setPromptModal({
        kind: "confirm",
        message: String(message || ""),
        defaultValue: "",
        resolve,
      });
    });

  // Build the direct img src with ?t=<token>&ts=<tick> so the browser handles
  // load + retries natively (no blob URL plumbing — removes a class of races).
  const screenshotSrc = (sessionId && sessionState === "ready")
    ? `${API_URL}/api/visual-recorder/${sessionId}/screenshot?t=${encodeURIComponent(localStorage.getItem("token") || "")}&ts=${shotTick}`
    : "";

  // ── Click forwarding ──────────────────────────────────────────────
  const handleImgClick = async (e) => {
    if (busy || !imgRef.current || !sessionId) return;
    if (sessionState !== "ready") {
      toast.error("Session is still connecting");
      return;
    }

    const rect = imgRef.current.getBoundingClientRect();
    const scaleX = viewport.width / rect.width;
    const scaleY = viewport.height / rect.height;
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);

    if (tool === "final") {
      setBusy(true);
      try {
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/mark-final`, {
          method: "POST",
          headers: authH(),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        toast.success("Final page captured! Conversion target set.");
        setTool("default");
      } catch (err) {
        toast.error(`Mark final failed: ${err.message || err}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    // 2026-01 v2.4.2 "scan" tool — inspect an element WITHOUT clicking
    // it and WITHOUT recording a step. Returns text/selector/xpath so
    // the customer can paste them into RPA Studio, manual steps or
    // waits.  Tool stays on "scan" so the user can inspect multiple
    // elements back-to-back — press Esc / 1 / any other key to leave.
    if (tool === "scan") {
      await scanElementAt(x, y);
      return;
    }

    // 2026-07 v2.5.4 "wait_for_button" tool — pick a button on the live
    // page and record a wait-until-visible step for it. NO click is
    // fired. Perfect for lazy-loading offer pages: recorder captures
    // the best selector for the button; at replay RUT pauses until
    // that button becomes visible before continuing.
    if (tool === "wait_for_button") {
      setBusy(true);
      try {
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/wait-for-button`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({ x: Math.round(x), y: Math.round(y), timeout_ms: Math.max(500, Number(waitPickTimeoutMs) || 30000) }),
        });
        const d = await r.json();
        if (!r.ok || d.recorded === false) {
          toast.error(d.error || d.detail || "Could not add wait-for-button step");
        } else {
          const hint = d.step?.hint_text ? ` — "${d.step.hint_text}"` : "";
          toast.success(`⏱️ Wait-for-button step added${hint}`);
          refreshState();
        }
      } catch (err) {
        toast.error(`Wait-for-button failed: ${err.message || err}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    if (tool === "wait_for_text_pick") {
      const ok = await postWaitPickAt("wait-for-text-at", x, y, "Wait for text added");
      if (ok) setTool("default");
      return;
    }

    if (tool === "wait_for_selector_pick") {
      const ok = await postWaitPickAt("wait-for-selector-at", x, y, "Wait for selector added");
      if (ok) setTool("default");
      return;
    }

    if (tool === "wait_for_xpath_pick") {
      const ok = await postWaitPickAt("wait-for-xpath-at", x, y, "Wait for xpath added");
      if (ok) setTool("default");
      return;
    }

    if (tool === "extract_pick") {
      setBusy(true);
      try {
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/scan`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({ x: Math.round(x), y: Math.round(y) }),
        });
        const d = await r.json();
        if (!r.ok || !d.ok) {
          toast.error(d.error || d.detail || "Scan failed");
          return;
        }
        const sel = (d.selector || "").trim();
        if (!sel) {
          toast.error("Could not detect selector — turn off auto-detect and type manually");
          return;
        }
        const key = await vrPrompt(
          `Selector detected: ${sel.slice(0, 60)}\nVariable name (e.g. order_id) — use later as {{order_id}}:`,
          "",
        );
        if (!key || !key.trim()) return;
        const er = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-extract`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({
            selector: sel,
            store_key: key.trim(),
            attribute: null,
            timeout: 10000,
            optional: false,
          }),
        });
        const ed = await er.json();
        if (!er.ok || !ed.recorded) {
          toast.error(ed.error || ed.detail || "Extract failed");
          return;
        }
        toast.success(`Extract → {{${key.trim()}}} added`);
        refreshState();
        setTool("default");
      } catch (err) {
        toast.error(err.message || "Extract pick failed");
      } finally {
        setBusy(false);
      }
      return;
    }

    // 2026-01: "nav_only" tool — click happens on the live page but
    // NO step is recorded. Used to advance the browser past a Random
    // Pick step (the random step already contains its own click JS;
    // we just need the live preview to move to the next page so the
    // user can record subsequent steps).
    if (tool === "nav_only") {
      setBusy(true);
      try {
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/nav-click`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({ x, y }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        toast.success("Navigated — no step recorded ✓");
        refreshScreenshot();
      } catch (err) {
        toast.error(`Nav click failed: ${err.message || err}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    // 2026-07: "manual_type" (Fix Type) — type into an input without
    // recording a step. Same idea as Move: correct a wrong auto-fill
    // during recording without polluting the automation JSON.
    if (tool === "manual_type") {
      setBusy(true);
      try {
        const text = await vrPrompt(
          "Sahi value likhein (JSON mein step add nahi hoga):",
          "",
        );
        if (text === null) {
          setBusy(false);
          return;
        }
        if (!String(text).trim()) {
          toast.error("Value khali hai");
          setBusy(false);
          return;
        }
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/manual-type`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({ x, y, value: String(text) }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || d.error || `HTTP ${r.status}`);
        if (!d.typed) {
          toast.error(d.error || d.fill_warning || "Fix Type failed");
        } else {
          toast.success(
            `Typed "${(d.filled_sample || String(text)).slice(0, 30)}" — no step recorded ✓`,
          );
          refreshScreenshot();
        }
      } catch (err) {
        toast.error(`Fix Type failed: ${err.message || err}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    // "capture" tool: insert a screenshot marker — no need to click
    // anywhere on the page, but if the user does, we still treat it
    // as a request to insert at current position.
    if (tool === "capture") {
      setBusy(true);
      try {
        const name = await vrPrompt(
          "Name this capture (shown in Live Activity):",
          `Step ${steps.length + 1}`,
        );
        if (name === null) { setBusy(false); return; }   // user cancelled
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/screenshot-marker`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({ name: name || `Step ${steps.length + 1}` }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        toast.success(`📷 Capture point inserted: "${d.step?.name || "Step"}"`);
        refreshState();
      } catch (err) {
        toast.error(`Insert capture failed: ${err.message || err}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    // 2026-05: "close_browser" tool — no click needed, just append a
    // {"action":"close"} step at the current position. Same pattern as
    // the capture tool above. We auto-flip back to "default" so the
    // operator can keep recording (or save/test) without manually
    // changing the tool.
    if (tool === "close_browser") {
      setBusy(true);
      try {
        const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/close-browser-step`, {
          method: "POST",
          headers: authH(),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        toast.success("🔌 Close-browser step inserted — RUT will end the visit's browser here");
        setTool("default");
        refreshState();
      } catch (err) {
        toast.error(`Insert close failed: ${err.message || err}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    setBusy(true);
    try {
      const body = { x, y, mode: tool };
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/click`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);

      if (tool === "form_fill" && d.element) {
        setPendingFormFill({ selector: d.selector || "input", element: d.element });
      } else if ((tool === "option_pick" || tool === "sheet_pick" || tool === "gender_pick") && d.element) {
        if (d.warning) toast.warning(d.warning, { duration: 5000 });
        const txt = (d.option_pick_text || d.gender_pick_text || d.element?.text || "").trim();
        if (!txt) {
          toast.error("No button text — click Male, Female, ya koi option label");
        } else {
          setPendingOptionButtons((prev) => {
            if (prev.some((b) => b.toLowerCase() === txt.toLowerCase())) {
              toast.info(`"${txt}" pehle se pool mein hai`);
              return prev;
            }
            const next = [...prev, txt];
            toast.success(
              `Option pool (${next.length}): ${next.join(" · ")} — 2+ add karein phir column bind`,
            );
            return next;
          });
        }
      } else if (tool === "dropdown") {
        // The backend returned the <select> element's options. Open
        // the binding panel so the user picks one option literal OR
        // an Excel column to substitute at run-time.
        if (d.warning) {
          toast.error(d.warning);
        } else if (!Array.isArray(d.options) || d.options.length === 0) {
          toast.error("No <select> options found at that point — click the dropdown control itself.");
        } else {
          setPendingDropdownQueue([{
            selector: d.selector || "select",
            options: d.options,
            element: d.element,
            wrapper_kind: d.wrapper_kind || "",
            is_hidden_select: !!d.is_hidden_select,
          }]);
          if (d.wrapper_kind) {
            toast.success(
              d.is_hidden_select
                ? `Hidden <select> behind ${d.wrapper_kind} detected — replay will be faster.`
                : `Custom dropdown UI detected: ${d.wrapper_kind}`
            );
          }
        }
      } else if ((tool === "random" || tool === "random_click") && d.element) {
        const txt = (d.element.text || "").trim();
        if (txt) {
          setPendingRandom((prev) => [...prev, txt]);
          toast.success(`Random pool: ${pendingRandom.length + 1} items — click "Build Random Step" when ready`);
        }
      } else if (tool === "check" && d.element) {
        // 2026-05: dedicated checkbox tool. Backend records a
        // {"action":"check"} step that the RUT engine routes through
        // _smart_check_with_fallback (handles CSS-styled hidden boxes).
        const tag = (d.element.tag || "").toLowerCase();
        const txt = (d.element.text || "").slice(0, 40);
        if (d.warning) {
          toast.error(d.warning);
        } else if (tag !== "input" || (d.element.type || "").toLowerCase() !== "checkbox") {
          toast.error("That isn't a checkbox — click directly on the box (or its label/border).");
        } else {
          toast.success(txt ? `☑ Checkbox recorded: "${txt}"` : "☑ Checkbox step recorded");
        }
      } else if (tool === "default") {
        const txt = (d.element?.text || "").slice(0, 30);
        if (d.live_click_warning) {
          toast.warning(d.live_click_warning, { duration: 7000 });
        }
        if (d.cross_origin_iframe || d.warning) {
          toast.warning(d.warning || "Cross-origin iframe — use ⋯ More → iframe click for reliable RUT replay.", { duration: 6000 });
        }
        toast.success(txt ? `Click recorded: "${txt}"` : "Click recorded");
      }
      refreshState();
      refreshScreenshot();
    } catch (err) {
      toast.error(`Click failed: ${err.message || err}`);
    } finally {
      setBusy(false);
    }
  };

  // ── 2026-06: If / Else branch — submit the assembled draft ────────
  // Inserts the branch step at `branchEditor.insertIndex` (or appends
  // at the end if null). After insert the user can use the existing
  // "Edit Raw JSON" on the step to fine-tune nested steps, OR drag
  // existing recorded steps INTO branches via the Branch Editor UI's
  // "Move into branch" affordance (covered in a follow-up iteration).
  const submitBranch = async () => {
    if (!branchEditor || !sessionId) return;
    const draft = branchEditor.draft || {};
    // ── Validate ──
    if (!Array.isArray(draft.branches) || draft.branches.length < 1) {
      toast.error("Add at least one branch");
      return;
    }
    for (let i = 0; i < draft.branches.length; i++) {
      const b = draft.branches[i];
      const c = b?.condition || {};
      const ct = (c.type || "").trim();
      if (!ct) { toast.error(`Branch #${i + 1}: pick a condition type`); return; }
      if (ct === "selector_visible" || ct === "selector_attached") {
        if (!(c.selector || "").trim()) { toast.error(`Branch #${i + 1}: selector is required`); return; }
      } else if (ct === "text_visible") {
        if (!(c.text || "").trim()) { toast.error(`Branch #${i + 1}: text is required`); return; }
      } else if (ct === "url_contains" || ct === "url_matches") {
        if (!(c.value || "").trim()) { toast.error(`Branch #${i + 1}: URL fragment / pattern is required`); return; }
      }
    }
    // Normalise the step shape the backend expects
    const cleanBranches = draft.branches.map((b) => ({
      name: (b.name || "").trim() || "Path",
      condition: { ...b.condition, timeout_ms: Number(b.condition.timeout_ms) || Number(draft.timeout_ms) || 12000 },
      steps: Array.isArray(b.steps) ? b.steps : [],
    }));
    const step = {
      action: "branch",
      name: (draft.name || "If / Else").trim(),
      timeout_ms: Number(draft.timeout_ms) || 12000,
      branches: cleanBranches,
      default_steps: Array.isArray(draft.default_steps) ? draft.default_steps : [],
    };
    setBusy(true);
    try {
      // Append at end when insertIndex is null
      const position = (branchEditor.insertIndex == null) ? (steps.length || 0) : branchEditor.insertIndex;
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/manual-step`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ step, position }),
      });
      const d = await r.json();
      if (!r.ok || !d.added) throw new Error(d.reason || d.detail || `HTTP ${r.status}`);
      toast.success(`🔀 If/Else inserted (${cleanBranches.length} branches)`);
      setBranchEditor(null);
      refreshState();
    } catch (err) {
      toast.error(`Insert branch failed: ${err.message || err}`);
    } finally {
      setBusy(false);
    }
  };

  // ── Dropdown bind: complete the select after picking the dropdown ─
  const submitDropdownBind = async (opts) => {
    // opts: { value?: string, header_name?: string, match_by?: 'label'|'value' }
    if (!pendingDropdown || !sessionId) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/dropdown-bind`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          selector: pendingDropdown.selector,
          value: opts.value || null,
          header_name: opts.header_name || null,
          match_by: opts.match_by || "label",
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success(
        opts.header_name
          ? `Dropdown bound to {{${opts.header_name}}}`
          : `Dropdown will select "${opts.value}"`,
      );
      setPendingDropdownQueue((prev) => prev.slice(1));
      refreshState();
    } catch (err) {
      toast.error(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  // ── Option Pick: bind 2+ buttons to Excel column ─────────────────
  const submitOptionPick = async (headerName) => {
    if (!sessionId || !headerName || pendingOptionButtons.length < 2) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/sheet-pick-bind`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          header_name: headerName,
          button_labels: pendingOptionButtons,
        }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) throw new Error(d.error || d.detail || `HTTP ${r.status}`);
      const sample = d.clicked_sample;
      toast.success(
        `Option Pick bound to {{${headerName}}}${sample ? ` · live click "${sample}"` : ""}`,
      );
      if (d.sample_hint) toast(d.sample_hint, { icon: "ℹ️" });
      if (d.click_warning) toast.warning(d.click_warning);
      setPendingOptionButtons([]);
      setTool("default");
      refreshState();
      refreshScreenshot();
    } catch (err) {
      toast.error(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  // ── Form fill: complete the type after clicking an input ─────────
  const submitFormFill = async (headerName, plainValue) => {
    if (!pendingFormFill || !sessionId) return;
    setBusy(true);
    try {
      // ── 2026-05 fix ──
      // When binding to a header (no plain value), send `value=""` and
      // let the backend resolve the sample value via `sample_row[header]`.
      // Previously we sent `{{first}}` literally which got typed into the
      // live form input (visible as `{{first}}` text in the field) — the
      // form then failed validation and the user couldn't proceed.
      const sendValue = plainValue || "";
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/type`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          selector: pendingFormFill.selector,
          value: sendValue,
          header_name: headerName || null,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const filled = d.filled_sample;
      toast.success(
        headerName
          ? `Bound to {{${headerName}}}${filled ? ` · live page filled with "${filled}"` : ""}`
          : "Plain value set"
      );
      if (d.sample_hint) toast(d.sample_hint, { icon: "ℹ️" });
      setPendingFormFill(null);
      refreshState();
      refreshScreenshot();
    } catch (err) {
      toast.error(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  // ── 2026-01 NEW: Detect all clickable elements on the current page ─
  // Called automatically when user selects the "Random Pick" tool.
  // The user then ticks which ones go in the random pool (no need to
  // click each one on the live page → no premature navigation).
  const detectClickables = async () => {
    if (!sessionId) return;
    setDetectingClickables(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/detect-clickables`, {
        method: "GET",
        headers: authH(),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const items = Array.isArray(d.items) ? d.items : [];
      setDetectedClickables(items);
      setSelectedRandomKeys(new Set());
      if (items.length === 0) {
        toast.error("No clickable elements detected on this page.");
      } else {
        toast.success(`Detected ${items.length} clickable element${items.length === 1 ? "" : "s"} — tick the ones for the random pool.`);
      }
    } catch (err) {
      toast.error(`Detect failed: ${err.message || err}`);
    } finally {
      setDetectingClickables(false);
    }
  };

  // ── 2026-01 v2.4.2 — Popup Work: detect buttons INSIDE popups ─────
  //  v2.6.28 — Also seeds `popupItemActions` from each item's
  //  `element_kind` so form fields default to Form Fill, selects to
  //  Dropdown, checkboxes/radios to Check Box, everything else to
  //  Click.
  const defaultActionFor = (item) => {
    const k = (item && item.element_kind) || '';
    if (k === 'text_input' || k === 'textarea') return 'form_fill';
    if (k === 'select') return 'dropdown';
    if (k === 'checkbox' || k === 'radio') return 'check';
    return 'click';
  };

  const detectPopupButtons = async () => {
    if (!sessionId) return;
    setDetectingPopups(true);
    setDetectedPopupItems([]);
    setSelectedPopupKeys(new Set());
    setPopupItemActions(new Map());
    setPopupContainerCount(0);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/detect-popup-buttons`, {
        method: "GET",
        headers: authH(),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const items = Array.isArray(d.items) ? d.items : [];
      setDetectedPopupItems(items);
      // v2.6.28 — Seed default actions per element_kind
      const seedActions = new Map();
      items.forEach((it, idx) => { seedActions.set(idx, defaultActionFor(it)); });
      setPopupItemActions(seedActions);
      setPopupContainerCount(Number(d.popup_count) || 0);
      if (!items.length) {
        toast.error(d.popup_count > 0
          ? `Found ${d.popup_count} popup(s) but no clickable buttons inside.`
          : "No popup/modal/dialog is currently visible on the page.");
      } else {
        toast.success(`Detected ${items.length} item(s) in top popup (screen center)${d.total_popups_found > 1 ? ` — ${d.total_popups_found} popups on page, showing topmost only` : ''} — pick action per item then Add as steps.`);
      }
    } catch (err) {
      toast.error(`Popup scan failed: ${err.message || err}`);
    } finally {
      setDetectingPopups(false);
    }
  };

  // Add each ticked popup item as a step using its selected action mode.
  // v2.6.28 — Each item's `popupItemActions[idx]` (click | form_fill |
  //           dropdown | check) drives the mode passed to `/click`.
  //           - click / check → step recorded atomically
  //           - form_fill (no header yet) → backend records
  //             `wait_for_selector`; user can bind a header later via
  //             /type or via the last-item follow-up picker below.
  //           - dropdown → backend returns options; queue ALL dropdown
  //             picks so the user can bind each one in sequence.
  const addSelectedPopupClicks = async () => {
    if (!sessionId) return;
    const picks = Array.from(selectedPopupKeys)
      .map((idx) => ({ item: detectedPopupItems[idx], mode: popupItemActions.get(idx) || 'click' }))
      .filter((p) => !!p.item);
    if (!picks.length) {
      toast.error("Tick at least one popup item first");
      return;
    }
    setBusy(true);
    let added = 0;
    let lastFormFillPending = null;   // {selector, element}
    const dropdownQueue = [];         // all dropdown binds to queue
    try {
      for (const { item, mode } of picks) {
        const cx = Math.round(item.x);
        const cy = Math.round(item.y);
        try {
          const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/click`, {
            method: "POST",
            headers: authH(),
            body: JSON.stringify({ x: cx, y: cy, mode }),
          });
          const d = await r.json();
          if (!r.ok) continue;
          if (mode === 'form_fill') {
            added += 1;
            if (d.element) lastFormFillPending = { selector: d.selector || 'input', element: d.element };
          } else if (mode === 'dropdown') {
            if (Array.isArray(d.options) && d.options.length > 0) {
              dropdownQueue.push({
                selector: d.selector || 'select',
                options: d.options,
                element: d.element,
                wrapper_kind: d.wrapper_kind || '',
                is_hidden_select: !!d.is_hidden_select,
              });
            }
          } else if (mode === 'check') {
            if (d.recorded !== false) added += 1;
          } else {
            if (d.recorded !== false) added += 1;
          }
        } catch {
          /* keep going — best effort across the batch */
        }
      }
      if (lastFormFillPending) setPendingFormFill(lastFormFillPending);
      if (dropdownQueue.length) setPendingDropdownQueue(dropdownQueue);

      toast.success(
        `Added ${added}/${picks.length} popup step(s)` +
        (dropdownQueue.length
          ? ` — bind ${dropdownQueue.length} dropdown${dropdownQueue.length === 1 ? "" : "s"} (first shown)`
          : "") +
        (lastFormFillPending ? " — bind an Excel column for the form field" : "")
      );
      setSelectedPopupKeys(new Set());
      setDetectedPopupItems([]);
      setPopupItemActions(new Map());
      setPopupContainerCount(0);
      refreshState();
    } catch (err) {
      toast.error(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  // ── 2026-01 v2.4.2 — Scan: click any element and see its locators ──
  //                     No step is recorded and no click is fired on
  //                     the live page. Just inspection + copy-paste.
  const scanElementAt = async (x, y) => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/scan`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ x: Math.round(x), y: Math.round(y) }),
      });
      const d = await r.json();
      if (!r.ok || !d.ok) {
        toast.error(d.error || d.detail || "Scan failed");
        return;
      }
      setScanResult(d);
      toast.success("Element scanned — locators shown");
    } catch (err) {
      toast.error(`Scan failed: ${err.message || err}`);
    }
  };

  const copyScanValue = async (value, label) => {
    if (!value) {
      toast.error("nothing to copy");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label} copied`);
    } catch {
      toast.error("Copy failed — select the value manually");
    }
  };

  // ── 2026-01 v2.4.2 — Wait for XPath (sibling of Wait for selector) ─
  const waitForXpathAction = async () => {
    if (!sessionId) return;
    if (waitAutoDetect) {
      startWaitPick("wait_for_xpath_pick", "Wait for xpath (auto-detect)");
      return;
    }
    const xp = await vrPrompt(
      "XPath expression to wait for (e.g. //button[contains(text(),'Continue')] or //div[@id='thank-you']):",
      ""
    );
    if (!xp || !xp.trim()) return;
    const t = await vrPrompt("Max wait time in ms (default 15000):", "15000");
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/wait-for-xpath`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          xpath: xp.trim(),
          timeout_ms: Math.max(500, Number(t) || 15000),
        }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) {
        toast.error(d.error || d.detail || "XPath wait failed");
        return;
      }
      toast.success("XPath appeared — recorded");
      refreshState();
    } catch (e) {
      toast.error(e.message || "XPath wait failed");
    }
  };

  const buildRandomStep = async () => {
    // Two paths: NEW checklist flow (selectedRandomKeys) or legacy
    // click-to-pool flow (pendingRandom). Prefer checklist if any
    // boxes are ticked.
    const checklistTexts = Array.from(selectedRandomKeys)
      .map((idx) => detectedClickables[idx])
      .filter(Boolean)
      .map((el) => (el.text || "").trim())
      .filter(Boolean);

    const useChecklist = checklistTexts.length >= 2;
    const useLegacy = !useChecklist && pendingRandom.length >= 2;

    if (!useChecklist && !useLegacy) {
      toast.error("Need at least 2 items in the random pool");
      return;
    }
    if (!sessionId) return;
    setBusy(true);
    try {
      const body = useChecklist
        ? { count: checklistTexts.length, texts: checklistTexts }
        : { count: pendingRandom.length };
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/group-random`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success(`Random step built: pick from ${d.items?.length || 0}`);
      setPendingRandom([]);
      setSelectedRandomKeys(new Set());
      setDetectedClickables([]);
      refreshState();
    } catch (err) {
      toast.error(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  // ── Manual step shortcuts ─────────────────────────────────────────
  const addWait = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/wait`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ ms: Number(waitMs) || 2000 }),
      });
      toast.success(`Wait ${waitMs}ms added`);
      refreshState();
    } finally {
      setBusy(false);
    }
  };

  const addWaitLoad = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/wait-load`, {
        method: "POST",
        headers: authH(),
      });
      toast.success("Wait-for-load added");
      refreshState();
    } finally {
      setBusy(false);
    }
  };

  const addAutoContinueSurvey = async () => {
    if (!sessionId) return;
    const newStep = {
      action: "auto_continue_survey",
      max_iterations: 15,
      iteration_wait_ms: 1500,
      optional: false,
      name: "Auto-continue survey / deal wall (same as RUT Smart Funnel tail)",
    };
    const merged = [...(steps || []), newStep];
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/import-steps`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ steps: merged }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setSteps(merged);
      toast.success("auto_continue_survey step added — RUT will drive Yes/No + deal cards after your form steps");
    } catch (e) {
      toast.error(e.message || "Failed to add step");
    } finally {
      setBusy(false);
    }
  };

  const addScroll = async (direction) => {
    if (!sessionId) return;
    setBusy(true);
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/scroll`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ y: direction === "down" ? 600 : -600 }),
      });
      toast.success(`Scrolled ${direction}`);
      refreshState();
      refreshScreenshot();
    } finally {
      setBusy(false);
    }
  };

  const navigateTo = async () => {
    if (!sessionId || !navUrl.trim()) return;
    setBusy(true);
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/navigate`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ url: navUrl.trim() }),
      });
      toast.success("Navigated");
      setNavUrl("");
      refreshState();
      refreshScreenshot();
    } finally {
      setBusy(false);
    }
  };

  // Send keyboard key to live session + auto-record as a step
  const pressKey = async (key) => {
    if (!sessionId || sessionState !== "ready") return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/press-key`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ key }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) {
        toast.error(d.error || d.detail || "Press key failed");
        return;
      }
      toast.success(`Pressed ${key}`);
      refreshState();
    } catch (e) {
      toast.error(e.message || "Press key failed");
    }
  };

  // Wait for a CSS selector (recorded as step too)
  const waitForSelectorAction = async () => {
    if (waitAutoDetect) {
      startWaitPick("wait_for_selector_pick", "Wait for selector (auto-detect)");
      return;
    }
    const sel = await vrPrompt("CSS selector to wait for (e.g. 'button.cta' or '#thank-you-msg'):", "");
    if (!sel) return;
    const t = await vrPrompt("Max wait time in ms (default 15000):", "15000");
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/wait-for-selector`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ selector: sel.trim(), timeout_ms: Math.max(500, Number(t) || 15000) }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) {
        toast.error(d.error || d.detail || "Wait failed");
        return;
      }
      toast.success("Selector appeared — recorded");
      refreshState();
    } catch (e) {
      toast.error(e.message || "Wait failed");
    }
  };

  // 2026-01: New step types — Wait for Text / Wait for URL / Extract / Dismiss Popups
  const addWaitForText = async () => {
    if (!sessionId) return;
    if (waitAutoDetect) {
      startWaitPick("wait_for_text_pick", "Wait for text (auto-detect)");
      return;
    }
    const text = await vrPrompt("Wait until this text appears on the page (e.g. 'Thank you', 'Order confirmed'):", "");
    if (!text || !text.trim()) return;
    const tout = await vrPrompt("Max wait time in ms (default 15000):", "15000");
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-wait-text`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({
          text: text.trim(),
          timeout: Math.max(1000, Number(tout) || 15000),
          case_insensitive: true,
          optional: false,
        }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success(`Wait for text "${text.slice(0, 30)}" added`);
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addWaitForUrl = async () => {
    if (!sessionId) return;
    const contains = await vrPrompt("Wait until URL contains (e.g. '/thank-you', '/success'):", "");
    if (!contains || !contains.trim()) return;
    const tout = await vrPrompt("Max wait time in ms (default 15000):", "15000");
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-wait-url`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({
          contains: contains.trim(),
          timeout: Math.max(1000, Number(tout) || 15000),
          optional: false,
        }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success(`Wait for URL ~ "${contains}" added`);
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addExtract = async () => {
    if (!sessionId) return;
    if (waitAutoDetect) {
      startWaitPick("extract_pick", "Extract var (auto-detect selector)");
      return;
    }
    const sel = await vrPrompt("CSS selector to extract text from (e.g. '#order-id', '.confirmation .code'):", "");
    if (!sel || !sel.trim()) return;
    const key = await vrPrompt("Variable name to store the value (e.g. 'order_id'). Use later as {{order_id}}:", "");
    if (!key || !key.trim()) return;
    const attr = await vrPrompt("(Optional) attribute name to read instead of text (e.g. 'href', 'data-id'). Leave blank for text:", "");
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-extract`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({
          selector: sel.trim(),
          store_key: key.trim(),
          attribute: (attr || "").trim() || null,
          timeout: 10000,
          optional: false,
        }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success(`Extract → {{${key}}} added`);
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addDismissPopups = async () => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-dismiss-popups`, {
        method: "POST", headers: authH(),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success("Dismiss popups step added");
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  // ── 2026-01 Phase 1: "any-offer" step helpers ───────────────────
  // Each fires the corresponding /api/visual-recorder/:id/add-*
  // endpoint and refreshes state so the new step appears in the
  // Recorded Steps panel.

  const addWaitNetworkIdle = async () => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-wait-network-idle`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ timeout_ms: 30000 }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success("Wait for network idle added — good for SPAs (React/Vue/Next offers)");
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addCaptchaPause = async () => {
    if (!sessionId) return;
    try {
      // Probe first so the user knows whether a captcha was actually detected
      const probe = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/detect-captcha`, { headers: authH() });
      const pd = await probe.json().catch(() => ({}));
      if (pd.detected) {
        const types = (pd.providers || []).map(p => p.type).join(", ");
        toast.info(`CAPTCHA detected: ${types} — adding pause-for-human step`);
      }
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-captcha-pause`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ label: "" }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success("Captcha pause added — during job replay your Electron app will pop up for manual solve");
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addFileUpload = async () => {
    if (!sessionId) return;
    const selector = await vrPrompt(
      "CSS selector of the file input element\n(e.g. input[name=id_doc] or #upload-photo)",
      "input[type=file]",
    );
    if (!selector) return;
    const filePath = await vrPrompt(
      "File path OR {{column_name}} template\n• Local: ~/Pictures/id.jpg\n• Per-row: {{id_photo_path}}",
      "{{file_path}}",
    );
    if (!filePath) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-file-upload`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ selector, file_path: filePath }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success("File upload step added");
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addOtpWait = async () => {
    if (!sessionId) return;
    const targetSelector = await vrPrompt(
      "CSS selector of the OTP input where the code will be filled\n(e.g. input[name=otp] or #verification-code)",
      "input[name=otp]",
    );
    if (!targetSelector) return;
    const sourceRaw = await vrPrompt(
      "Where does the code arrive? (url / page_text / clipboard / selector)",
      "page_text",
    );
    const source = (sourceRaw || "page_text").trim().toLowerCase();
    const digitsRaw = await vrPrompt("How many digits? (default 6)", "6");
    const digits = parseInt(digitsRaw, 10) || 6;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-otp-wait`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({
          source,
          target_selector: targetSelector,
          digits,
          timeout_ms: 120000,
        }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success(`OTP wait step added (${digits} digits from ${source})`);
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addHumanPause = async () => {
    if (!sessionId) return;
    const reason = await vrPrompt(
      "Why pause? (label shown in Electron app popup during job replay)",
      "wallet_connect",
    );
    if (!reason) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/add-human-pause`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ reason, timeout_ms: 300000 }),
      });
      const d = await r.json();
      if (!r.ok || !d.recorded) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success("Human pause added — replay will halt for manual action");
      refreshState();
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  // ── 2026-01 Phase 2: full any-offer coverage handlers ────────────
  // Drop these into the "More" dropdown to keep the toolbar uncluttered

  const callVRPost = async (path, body, successMsg) => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/${path}`, {
        method: "POST", headers: authH(),
        body: body ? JSON.stringify(body) : undefined,
      });
      const d = await r.json();
      if (!r.ok || (d.recorded === false)) { toast.error(d.error || d.detail || "Failed"); return; }
      toast.success(successMsg || "Step added");
      refreshState();
      return d;
    } catch (e) { toast.error(e.message || "Failed"); }
  };

  const addBrowserBack = () => callVRPost("browser-back", null, "← Back step added");
  const addBrowserForward = () => callVRPost("browser-forward", null, "→ Forward step added");

  const addRightClick = async () => {
    const sel = await vrPrompt("CSS selector of element to right-click (blank = use coords)", "");
    let x = 0, y = 0;
    if (!sel) {
      x = parseInt(await vrPrompt("X coordinate", "100"), 10) || 0;
      y = parseInt(await vrPrompt("Y coordinate", "100"), 10) || 0;
    }
    return callVRPost("right-click", { selector: sel, x, y }, "Right-click step added");
  };

  const addClipboardWrite = async () => {
    const text = await vrPrompt("Text to write to clipboard (supports {{templates}})", "{{counter}}");
    if (text === null) return;
    return callVRPost("clipboard-write", { text }, "Clipboard write step added");
  };

  const addClipboardRead = async () => {
    const v = await vrPrompt("Variable name to store clipboard contents", "clipboard_value");
    if (!v) return;
    return callVRPost("clipboard-read", { var_name: v }, `Clipboard read → {{${v}}}`);
  };

  const addCondSkip = async () => {
    const typeRaw = await vrPrompt("Condition type: visible / not_visible / text", "visible");
    const if_type = (typeRaw || "visible").toLowerCase().trim();
    let selector = "", text = "";
    if (if_type === "text") {
      text = await vrPrompt("Text to check on page", "");
      if (!text) return;
    } else {
      selector = await vrPrompt("CSS selector to check", ".captcha-frame");
      if (!selector) return;
    }
    const skipRaw = await vrPrompt("How many subsequent steps to skip?", "1");
    const skip_count = parseInt(skipRaw, 10) || 1;
    return callVRPost("conditional-skip", { if_type, selector, text, skip_count },
      `If ${if_type} → skip ${skip_count} steps`);
  };

  const addSaveStorage = async () => {
    const v = await vrPrompt("Variable name for cookies+localStorage snapshot", "session_state");
    if (!v) return;
    return callVRPost("add-save-storage", { var_name: v }, "Save storage step added");
  };

  const addRestoreStorage = async () => {
    const v = await vrPrompt("Variable name to restore cookies+localStorage from", "session_state");
    if (!v) return;
    return callVRPost("add-restore-storage", { var_name: v }, "Restore storage step added");
  };

  const setBrowserZoom = async () => {
    const raw = await vrPrompt("Zoom level (1.0 = 100%, 1.25 = 125%, 1.5 = 150%)", "1.0");
    const level = parseFloat(raw) || 1.0;
    return callVRPost("set-zoom", { level }, `Zoom = ${Math.round(level * 100)}%`);
  };

  const addIframeClick = async () => {
    const fs = await vrPrompt("CSS selector of the iframe element", "iframe");
    if (!fs) return;
    const inner = await vrPrompt("Inner selector OR inner text\n(prefix with text: for text match)", "button.submit");
    if (!inner) return;
    let inner_selector = inner, inner_text = "";
    if (inner.startsWith("text:")) {
      inner_text = inner.slice(5).trim();
      inner_selector = "";
    }
    return callVRPost("iframe-click", {
      frame_selector: fs, inner_selector, inner_text, timeout_ms: 10000,
    }, "iframe click added");
  };

  const addShadowClick = async () => {
    const raw = await vrPrompt(
      "Shadow DOM selector chain — comma-separated\n" +
      "Each step is a selector; we pierce shadowRoot at each level.\n" +
      "Example: my-card, checkout-btn, button.primary",
      "host-element, button",
    );
    if (!raw) return;
    const chain = raw.split(",").map(s => s.trim()).filter(Boolean);
    if (chain.length < 2) {
      toast.error("Need at least 2 selectors (host + final target)");
      return;
    }
    return callVRPost("shadow-click", { chain }, `Shadow DOM click → ${chain[chain.length - 1]}`);
  };

  const addDragDrop = async () => {
    const src = await vrPrompt("Source CSS selector (e.g. .slider-handle) — blank for coords", "");
    if (src === null) return;
    let body = { steps: 25 };
    if (src) {
      body.source_selector = src;
      const tgt = await vrPrompt("Target selector (blank → use delta)", "");
      if (tgt) {
        body.target_selector = tgt;
      } else {
        body.delta_x = parseInt(await vrPrompt("Drag delta X (pixels right)", "200"), 10) || 0;
        body.delta_y = parseInt(await vrPrompt("Drag delta Y (pixels down)", "0"), 10) || 0;
      }
    } else {
      body.source_x = parseInt(await vrPrompt("Source X", "100"), 10) || 0;
      body.source_y = parseInt(await vrPrompt("Source Y", "200"), 10) || 0;
      body.target_x = parseInt(await vrPrompt("Target X", "300"), 10) || 0;
      body.target_y = parseInt(await vrPrompt("Target Y", "200"), 10) || 0;
    }
    return callVRPost("drag-drop", body, "Drag-and-drop step added");
  };

  const runHeadlessProbe = async () => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/headless-probe`, { headers: authH() });
      const d = await r.json();
      if (!r.ok) { toast.error(d.detail || "Probe failed"); return; }
      const score = d.score || 0;
      const verdict = d.verdict || "";
      const fails = (d.fails || []).join("\n• ");
      const msg = `Anti-bot score: ${score}/100\n${verdict}` + (fails ? `\n\nLeaks:\n• ${fails}` : "");
      const toastFn = score >= 85 ? toast.success : score >= 70 ? toast.info : toast.error;
      toastFn(msg, { duration: 12000 });
    } catch (e) { toast.error(e.message || "Probe failed"); }
  };

  const [showMoreMenu, setShowMoreMenu] = useState(false);

  // Pre-flight lint
  const [lintResult, setLintResult] = useState(null);
  const [showLintPanel, setShowLintPanel] = useState(false);
  const runLint = async () => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/lint`, { headers: authH() });
      const d = await r.json();
      setLintResult(d);
      setShowLintPanel(true);
      const summary = d.summary || {};
      if (d.ok) toast.success(`Lint passed (${summary.warnings || 0} warnings, ${summary.infos || 0} info)`);
      else toast.error(`Lint found ${summary.errors || 0} error(s)`);
    } catch (e) { toast.error(e.message || "Lint failed"); }
  };

  // Move step up or down
  const moveStep = async (idx, direction) => {
    if (!sessionId) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/step/${idx}/move`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ direction }),
      });
      refreshState();
    } catch {}
  };

  // 2026-01: Drag-and-drop reorder — move any step to any index
  const moveStepTo = async (fromIndex, toIndex) => {
    if (!sessionId) return;
    if (fromIndex === toIndex) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/step/move-to`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ from_index: fromIndex, to_index: toIndex }),
      });
      refreshState();
    } catch (e) {
      toast.error(e.message || "Move failed");
    }
  };

  // 2026-01: Drag-and-drop state — `dragSrc` is the index currently being dragged
  const [dragSrc, setDragSrc] = useState(null);
  const [dragOver, setDragOver] = useState(null);

  // 2026-01: Insert a new step at a SPECIFIC index (between two existing steps).
  // Prompts the user to pick action type, then opens the existing modal.
  const insertStepAt = async (position) => {
    if (!sessionId) return;
    const action = await vrPrompt(
      "Step action to insert? Options: click, fill, type, select, check, uncheck, wait, wait_for_selector, wait_for_text, wait_for_url, press, scroll, screenshot, hover, dismiss_popups, extract, branch, stage",
      "wait"
    );
    if (!action || !action.trim()) return;
    const cleanAction = action.trim().toLowerCase();
    let stepDraft = { action: cleanAction };
    // Action-specific prompts
    if (cleanAction === "branch") {
      // ── Conditional branch scaffold (2026-02) ───────────────────
      // We scaffold a template with TWO empty branches + an empty
      // default. User then opens "Edit Raw JSON" on the new step to
      // wire up real selectors / nested steps. This keeps the prompt
      // flow short (5 window.prompts is already a lot) while still
      // giving a working template.
      const label = (await vrPrompt(
        "Branch step name (e.g. 'After email submit page picker'):",
        "Page picker"
      ) || "Page picker").trim();
      const tmoMs = Math.max(
        1000,
        Number(await vrPrompt("Overall race timeout in milliseconds (how long to wait for ANY branch's page to appear):", "12000")) || 12000
      );
      const condA = (await vrPrompt(
        "BRANCH A — CSS selector that ONLY appears when path A loads (e.g. 'input[name=phone]'):",
        "input[name=phone]"
      ) || "").trim();
      const condB = (await vrPrompt(
        "BRANCH B — CSS selector that ONLY appears when path B loads (e.g. 'input[name=birthday]'):",
        "input[name=birthday]"
      ) || "").trim();
      stepDraft = {
        action: "branch",
        name: label,
        timeout_ms: tmoMs,
        branches: [
          {
            name: "Path A",
            condition: condA
              ? { type: "selector_visible", selector: condA, timeout_ms: tmoMs }
              : { type: "selector_visible", selector: "", timeout_ms: tmoMs },
            steps: [
              {
                action: "wait",
                ms: 500,
                source: "manual",
              },
            ],
          },
          {
            name: "Path B",
            condition: condB
              ? { type: "selector_visible", selector: condB, timeout_ms: tmoMs }
              : { type: "selector_visible", selector: "", timeout_ms: tmoMs },
            steps: [
              {
                action: "wait",
                ms: 500,
                source: "manual",
              },
            ],
          },
        ],
        default_steps: [],
      };
    } else if (cleanAction === "stage") {
      const label = (await vrPrompt("Stage name:", "Form fill") || "Form fill").trim();
      const detectKind = (await vrPrompt("Detect: none / selector / text / url", "selector") || "none").trim().toLowerCase();
      stepDraft = {
        action: "stage",
        name: label,
        stage: label,
        skip_if_not_open: true,
      };
      if (detectKind === "selector" || detectKind === "css") {
        const sel = (await vrPrompt("Selector when stage is open:", "") || "").trim();
        const tmo = Math.max(1000, Number(await vrPrompt("Timeout ms:", "5000")) || 5000);
        if (sel) stepDraft.open_when = { type: "selector_visible", selector: sel, timeout_ms: tmo };
      } else if (detectKind === "text") {
        const txt = (await vrPrompt("Text when stage is open:", "") || "").trim();
        const tmo = Math.max(1000, Number(await vrPrompt("Timeout ms:", "5000")) || 5000);
        if (txt) stepDraft.open_when = { type: "text_visible", text: txt, timeout_ms: tmo };
      } else if (detectKind === "url") {
        const part = (await vrPrompt("URL contains:", "") || "").trim();
        const tmo = Math.max(1000, Number(await vrPrompt("Timeout ms:", "5000")) || 5000);
        if (part) stepDraft.open_when = { type: "url_contains", value: part, timeout_ms: tmo };
      }
    } else if (["click", "fill", "type", "select", "check", "uncheck", "hover", "wait_for_selector"].includes(cleanAction)) {
      const sel = await vrPrompt("CSS selector (or XPath e.g. //input[@name='x']):", "");
      if (!sel || !sel.trim()) return;
      stepDraft.selector = sel.trim();
      if (["fill", "type", "select"].includes(cleanAction)) {
        const val = await vrPrompt("Value to fill/type/select (use {{var}} for row data):", "");
        if (val !== null) stepDraft.value = val;
      }
    } else if (cleanAction === "wait") {
      const ms = await vrPrompt("Wait time in milliseconds:", "1000");
      stepDraft.ms = Math.max(0, Number(ms) || 1000);
    } else if (cleanAction === "wait_for_text") {
      const text = await vrPrompt("Text to wait for (e.g. 'Thank you'):", "");
      if (!text || !text.trim()) return;
      stepDraft.text = text.trim();
      stepDraft.timeout = 15000;
    } else if (cleanAction === "wait_for_url") {
      const contains = await vrPrompt("URL must contain:", "");
      if (!contains || !contains.trim()) return;
      stepDraft.contains = contains.trim();
      stepDraft.timeout = 15000;
    } else if (cleanAction === "press") {
      const key = await vrPrompt("Key to press (e.g. Enter, Tab, Escape):", "Enter");
      stepDraft.key = key || "Enter";
    } else if (cleanAction === "scroll") {
      stepDraft.value = await vrPrompt("Scroll amount (px, e.g. 500 or 'bottom'):", "500") || "500";
    } else if (cleanAction === "screenshot") {
      stepDraft.name = await vrPrompt("Screenshot label (e.g. 'After Submit'):", "Capture") || "Capture";
    } else if (cleanAction === "extract") {
      const sel = await vrPrompt("CSS selector to extract from:", "");
      if (!sel) return;
      stepDraft.selector = sel.trim();
      const key = await vrPrompt("Variable name to store value as (use later via {{var}}):", "");
      if (!key) return;
      stepDraft.store_key = key.trim();
    }
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/manual-step`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ step: stepDraft, position }),
      });
      const d = await r.json();
      if (!r.ok || !d.added) {
        toast.error(d.reason || d.detail || "Insert failed");
        return;
      }
      toast.success(`Step inserted at position #${(d.index ?? position) + 1}`);
      refreshState();
    } catch (e) {
      toast.error(e.message || "Insert failed");
    }
  };

  // Duplicate step
  const duplicateStep = async (idx) => {
    if (!sessionId) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/step/${idx}/duplicate`, {
        method: "POST",
        headers: authH(),
      });
      refreshState();
      toast.success("Step duplicated");
    } catch {}
  };

  // Rename step (inline edit)
  const renameStep = async (idx, name) => {
    if (!sessionId) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/step/${idx}/rename`, {
        method: "PATCH",
        headers: authH(),
        body: JSON.stringify({ name }),
      });
      refreshState();
    } catch {}
  };

  // ── Edit step (2026-01) ──────────────────────────────────────────
  // Opens the Edit modal pre-filled with the current step's editable
  // fields (selector / value / timeout / etc.). Lets the user fix a
  // wrong selector or bump a timeout after a Live Test failure
  // (e.g. the #birth_month case from the screenshots), then PATCHes
  // the change to the backend and refreshes the recorded-steps list.
  const openEditStep = (idx) => {
    if (idx < 0 || idx >= steps.length) return;
    const s = steps[idx] || {};
    setSelectorSuggest({ loading: false, items: null, error: "" });
    // 2026-05 — Pre-populate fallback editor fields from the existing
    // `fallbacks` dict (if any). Serialize `attrs` to a "key: value"
    // per-line textarea format that's friendlier to manual editing
    // than raw JSON.
    const fb = (s.fallbacks && typeof s.fallbacks === "object") ? s.fallbacks : {};
    const fbAttrsText = (fb.attrs && typeof fb.attrs === "object")
      ? Object.entries(fb.attrs).map(([k, v]) => `${k}: ${v}`).join("\n")
      : "";
    setEditingStep({
      index: idx,
      draft: {
        action: s.action || "",       // read-only display
        selector: s.selector || "",
        xpath: s.xpath || fb.xpath || "",
        xpath_abs: s.xpath_abs || fb.xpath_abs || "",
        value: s.value != null ? String(s.value) : "",
        timeout: s.timeout != null ? String(s.timeout) : "",
        key: s.key || "",
        ms: s.ms != null ? String(s.ms) : "",
        state: s.state || "",
        delay: s.delay != null ? String(s.delay) : "",
        match_by: s.match_by || "",
        humanize: s.humanize !== false,   // default true (existing behaviour)
        name: s.name || "",
        // Manual fallback editor fields (mirror of step.fallbacks)
        fb_xpath: fb.xpath || "",
        fb_text: fb.text || "",
        fb_tag: fb.tag || "",
        fb_attrs_text: fbAttrsText,
        fallbacksEdited: false,  // flipped to true the moment user touches any fb_* field
        // ── 2026-05: Random-pick advanced editor state ──
        // Pre-populate from step.pick_options if present (new format),
        // otherwise parse legacy `var labels=['x','y','z']` from script.
        pickOptions: (() => {
          if (Array.isArray(s.pick_options) && s.pick_options.length > 0) {
            return s.pick_options.map(o => ({
              text: o.text || "",
              selector: o.selector || "",
              xpath: o.xpath || "",
            }));
          }
          // Legacy parsing — extract labels=['…','…',…] from JS
          if ((s.action || "").toLowerCase() === "evaluate" && typeof s.script === "string") {
            const m = s.script.match(/var\s+labels\s*=\s*\[([^\]]*)\]/);
            if (m) {
              const items = [...m[1].matchAll(/'((?:[^'\\]|\\.)*)'/g)].map(x =>
                x[1].replace(/\\'/g, "'").replace(/\\\\/g, "\\")
              );
              return items.map(t => ({ text: t.trim(), selector: "", xpath: "" }));
            }
          }
          return [];
        })(),
        pickOptionsEdited: false,
        optional: !!s.optional,
        never_strict: !!s.never_strict,
      },
    });
  };

  const cancelEditStep = () => {
    setEditingStep(null);
    setSelectorSuggest({ loading: false, items: null, error: "" });
    setHoverPreview(null);
  };

  // Fetch live-page DOM candidates for a given (failed) selector and
  // surface them in the Edit modal as one-click suggestions.
  const fetchSelectorSuggestions = async () => {
    if (!editingStep || !sessionId) return;
    const failed = (editingStep.draft.selector || "").trim();
    if (!failed) {
      toast.error("Enter a selector first (or paste the failed one) before suggesting alternatives.");
      return;
    }
    setSelectorSuggest({ loading: true, items: null, error: "" });
    try {
      const r = await fetch(
        `${API_URL}/api/visual-recorder/${sessionId}/suggest-selectors?failed=${encodeURIComponent(failed)}&limit=10`,
        { headers: authH() },
      );
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setSelectorSuggest({ loading: false, items: [], error: d.detail || "Suggest failed" });
        return;
      }
      const items = d.suggestions || [];
      setSelectorSuggest({ loading: false, items, error: items.length === 0 ? "No similar elements found on the live page." : "" });
    } catch (e) {
      setSelectorSuggest({ loading: false, items: [], error: e.message || "Suggest failed" });
    }
  };

  // Apply a clicked suggestion → write into the Edit-modal selector field.
  const applySuggestion = (sel) => {
    if (!editingStep) return;
    setEditingStep({
      ...editingStep,
      draft: { ...editingStep.draft, selector: sel },
    });
    toast.success("Selector updated — review and Save");
  };

  // Hover-preview: fetch the bounding box of `selector` from the live
  // page and stash it so the screenshot overlay renders a blue pulse.
  // Debounced via a tiny ref so quick hovers across the list don't
  // hammer the backend.
  const previewFetchRef = useRef(0);
  const showSelectorPreview = async (selector) => {
    if (!sessionId || !selector) return;
    const myReq = ++previewFetchRef.current;
    try {
      const r = await fetch(
        `${API_URL}/api/visual-recorder/${sessionId}/selector-bbox?selector=${encodeURIComponent(selector)}`,
        { headers: authH() },
      );
      const d = await r.json().catch(() => ({}));
      // Discard if another hover already fired after this one
      if (myReq !== previewFetchRef.current) return;
      if (r.ok && d.found) {
        setHoverPreview({
          x: d.x, y: d.y, width: d.width, height: d.height,
          viewport: d.viewport || { width: viewport.width, height: viewport.height },
          selector,
        });
      } else {
        setHoverPreview(null);
      }
    } catch {
      setHoverPreview(null);
    }
  };

  const clearSelectorPreview = () => {
    previewFetchRef.current++;   // invalidate any in-flight request
    setHoverPreview(null);
  };

  // ── Smart Error → Fix Suggester (2026-01) ────────────────────────
  // Parses common Playwright / replay errors and returns a friendly
  // explanation + a recommended next action the user can take from the
  // Live Test results panel. Returns null when no rule matches (raw
  // error is then shown verbatim).
  const getSuggestedFix = (errorMsg, action, failedIdx) => {
    if (!errorMsg) return null;
    const e = String(errorMsg).toLowerCase();

    // 1. Execution context destroyed (navigation during evaluate / click)
    if (e.includes("execution context") || e.includes("context was destroyed")) {
      return {
        cause: "JavaScript ran a click that navigated the page mid-evaluate. The replay engine has been updated to swallow this safely — most likely just needs a re-run.",
        fix: "Click Re-run Live Test. If it persists, the JS may be navigating before doing all its work — split into two steps (one to click, one to wait_for_navigation).",
        action: "rerun",
      };
    }

    // 2. Selector exhausted (smart_wait gave up)
    if (e.includes("exhausted") && e.includes("selector variants")) {
      return {
        cause: "The recorded selector — and all auto-derived fallbacks — no longer match anything on the page. The site likely renamed this form field.",
        fix: typeof failedIdx === "number"
          ? `Open the Edit modal (✏️) on step #${failedIdx + 1}, click "Find similar" — Krexion will scan the live page and suggest the new selector. Saved as a permanent alias for future runs.`
          : "Edit the failing step and use Find similar to pick the correct selector. Save = permanent alias.",
        action: "edit",
        edit_idx: failedIdx,
      };
    }

    // 3. Generic timeout on wait_for_selector
    if (e.includes("timeout") && (e.includes("wait_for_selector") || e.includes("waiting for"))) {
      return {
        cause: "Element didn't appear within the step's timeout — page may be slow, or the selector is wrong, or the element is hidden behind a custom UI.",
        fix: "Edit the step: (a) increase timeout (e.g., 8000 → 20000), (b) change State to 'attached' if the element is hidden, OR (c) Find similar if the selector is stale.",
        action: "edit",
        edit_idx: failedIdx,
      };
    }

    // 4. Element not visible / not stable
    if (e.includes("not visible") || e.includes("element is not stable") || e.includes("element is outside of the viewport")) {
      return {
        cause: "Element exists in the DOM but is hidden (display:none) or being animated/transformed when we tried to act on it.",
        fix: "In Edit modal, change State to 'attached' (DOM-only). For check/select on hidden inputs, this usually fixes it instantly.",
        action: "edit",
        edit_idx: failedIdx,
      };
    }

    // 5. Net errors / navigation timeout
    if (e.includes("net::") || e.includes("err_") || e.includes("navigation timeout") || e.includes("page.goto")) {
      return {
        cause: "Page failed to load — proxy issue, DNS failure, target site down, or strict CAPTCHA before content.",
        fix: "Verify the URL works in a normal browser. If using a proxy, try without it first. Try a different proxy region. Increase the goto timeout if the page is just slow.",
        action: "rerun",
      };
    }

    // 6. Captcha
    if (e.includes("captcha")) {
      return {
        cause: "The page is showing a CAPTCHA challenge before our automation could proceed.",
        fix: "Some offers show CAPTCHA only on specific proxies/UAs. Switch proxy region or User-Agent. Add a 'wait' step to give the page time to settle. Consider AdsPower profiles for fingerprint-resistant runs.",
        action: "rerun",
      };
    }

    // 7. Target / browser closed
    if (e.includes("target closed") || e.includes("browser has been closed") || e.includes("connection closed")) {
      return {
        cause: "Browser session ended unexpectedly — usually a memory pressure event or the recorder session expired.",
        fix: "Discard this session and start a fresh recording. Steps already saved are NOT lost — they remain in your sample data.",
        action: "restart",
      };
    }

    // 8. Frame detached
    if (e.includes("frame was detached") || e.includes("frame got detached")) {
      return {
        cause: "An iframe holding the element was removed mid-action. Common on SPA-style pages that swap content.",
        fix: "Add a small 'wait' (1000ms) step BEFORE the failing step so the frame has time to mount stably.",
        action: "manual_add",
      };
    }

    // 9. Generic fill / type fail
    if (action === "fill" || action === "type") {
      return {
        cause: "Could not type into the input. Either the selector is wrong, the field is read-only/disabled, or a different element is intercepting focus.",
        fix: "Edit step → Find similar (may have renamed) OR try uncheck 'Human-like typing' (some pages reject character-by-character input).",
        action: "edit",
        edit_idx: failedIdx,
      };
    }

    return null;
  };

  // ── Manual Add Step (2026-01) ────────────────────────────────────
  // Opens a creation modal so the user can author a step by hand
  // (action + selector + value + timeout). Accepts both CSS and XPath.
  const openManualAddStep = () => {
    setManualStepDraft({
      action: "wait_for_selector",
      selector: "",
      value: "",
      timeout: "8000",
      key: "",
      ms: "1000",
      state: "visible",
      match_by: "label",
      humanize: true,
      name: "",
      position: "",   // empty = append to end
    });
  };

  const cancelManualAddStep = () => setManualStepDraft(null);

  // ── Selector Aliases panel (2026-01) ─────────────────────────────
  // Opens a read-only list of every selector rename the user has
  // accumulated across all their recordings. Each entry is one-click
  // deletable in case the user wants to revoke a past self-heal rule.
  const openAliasesPanel = async () => {
    setAliasesPanel({ loading: true, items: [], error: "" });
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/aliases`, {
        headers: authH(),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAliasesPanel({ loading: false, items: [], error: d.detail || "Failed to load aliases" });
        return;
      }
      setAliasesPanel({ loading: false, items: d.aliases || [], error: "" });
    } catch (e) {
      setAliasesPanel({ loading: false, items: [], error: e.message || "Failed to load" });
    }
  };

  const closeAliasesPanel = () => setAliasesPanel(null);

  const deleteAlias = async (domain, original) => {
    try {
      const r = await fetch(
        `${API_URL}/api/visual-recorder/aliases?domain=${encodeURIComponent(domain)}&original=${encodeURIComponent(original)}`,
        { method: "DELETE", headers: authH() },
      );
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.deleted) {
        toast.error(d.detail || "Delete failed");
        return;
      }
      toast.success("Alias removed");
      // Refresh the panel
      openAliasesPanel();
    } catch (e) {
      toast.error(e.message || "Delete failed");
    }
  };

  const saveManualAddStep = async () => {
    if (!manualStepDraft || !sessionId) return;
    const d = manualStepDraft;
    const action = (d.action || "").toLowerCase();
    // Build clean step payload based on action
    const step = { action };
    if (d.name && d.name.trim()) step.name = d.name.trim();
    if (["wait_for_selector", "click", "fill", "type", "select", "hover", "check", "uncheck", "press"].includes(action)) {
      if (!d.selector || !d.selector.trim()) {
        toast.error("Selector is required for this action");
        return;
      }
      step.selector = d.selector.trim();
    }
    if (["fill", "type", "select"].includes(action)) {
      step.value = d.value || "";
      step.timeout = d.timeout === "" ? 8000 : Number(d.timeout);
      if (action !== "select") step.humanize = !!d.humanize;
      if (action === "select" && d.match_by) step.match_by = d.match_by;
    } else if (action === "wait_for_selector") {
      step.timeout = d.timeout === "" ? 8000 : Number(d.timeout);
      if (d.state) step.state = d.state;
    } else if (action === "wait") {
      step.ms = d.ms === "" ? 1000 : Number(d.ms);
    } else if (action === "press") {
      if (!d.key || !d.key.trim()) {
        toast.error("Key is required (e.g., Enter, Tab, Escape)");
        return;
      }
      step.key = d.key.trim();
      if (d.selector) step.selector = d.selector.trim();
    } else if (["click", "hover", "check", "uncheck"].includes(action)) {
      step.timeout = d.timeout === "" ? 8000 : Number(d.timeout);
    } else if (["switch_tab", "close_tab"].includes(action)) {
      // 2026-06 — Multi-tab control. switch_tab REQUIRES an index;
      // close_tab accepts a blank index (means "close current tab").
      if (action === "switch_tab" && (d.index === "" || d.index == null || isNaN(Number(d.index)))) {
        toast.error("Tab index is required for switch_tab (0 = first tab)");
        return;
      }
      if (d.index !== "" && d.index != null && !isNaN(Number(d.index))) {
        step.index = Math.max(0, Number(d.index));
      }
    }

    const body = { step };
    if (d.position !== "" && d.position != null && !isNaN(Number(d.position))) {
      body.position = Math.max(0, Number(d.position) - 1); // user enters 1-based
    }

    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/manual-step`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify(body),
      });
      const dr = await r.json().catch(() => ({}));
      if (!r.ok || dr.added === false) {
        toast.error(dr.detail || dr.reason || "Add step failed");
        return;
      }
      toast.success(`Manual step added at #${(dr.index ?? 0) + 1}`);
      setManualStepDraft(null);
      refreshState();
    } catch (e) {
      toast.error(e.message || "Add step failed");
    }
  };

  const saveEditStep = async () => {
    if (!editingStep || !sessionId) return;
    const { index, draft } = editingStep;
    // Build patch payload — only include fields relevant to this action
    // so we don't write empty strings into steps that never had them.
    const patch = {};
    const action = (draft.action || "").toLowerCase();
    if (draft.selector !== undefined) patch.selector = draft.selector;
    if (draft.xpath !== undefined) patch.xpath = draft.xpath;
    if (draft.xpath_abs !== undefined) patch.xpath_abs = draft.xpath_abs;
    if (draft.name !== undefined) patch.name = draft.name;
    if (action === "fill" || action === "type" || action === "select") {
      patch.value = draft.value;
      patch.timeout = draft.timeout === "" ? 0 : Number(draft.timeout);
      if (action !== "select") patch.humanize = !!draft.humanize;
      if (action === "type" && draft.delay !== "") patch.delay = Number(draft.delay);
      if (action === "select" && draft.match_by) patch.match_by = draft.match_by;
    } else if (action === "wait_for_selector") {
      patch.timeout = draft.timeout === "" ? 0 : Number(draft.timeout);
      if (draft.state) patch.state = draft.state;
    } else if (action === "wait") {
      if (draft.ms !== "") patch.ms = Number(draft.ms);
    } else if (action === "press") {
      patch.key = draft.key;
      if (draft.selector) patch.selector = draft.selector;
    } else if (action === "click" || action === "hover" || action === "check" || action === "uncheck") {
      patch.timeout = draft.timeout === "" ? 0 : Number(draft.timeout);
    } else {
      // Fallback — pass through whatever non-empty fields the user touched.
      if (draft.value) patch.value = draft.value;
      if (draft.timeout !== "") patch.timeout = Number(draft.timeout);
    }

    // 2026-05 — Manual fallback editor.
    // If the user touched the fallback fields, build a clean dict and
    // send it. Empty dict / no fields touched → SEND null to clear
    // (so user can deliberately remove a bad fallbacks block).
    if (draft.fallbacksEdited === true) {
      const fb = {};
      const xp = (draft.fb_xpath || "").trim();
      const txt = (draft.fb_text || "").trim();
      const tg = (draft.fb_tag || "").trim().toLowerCase();
      if (xp) fb.xpath = xp;
      if (txt) fb.text = txt;
      if (tg) fb.tag = tg;
      // Parse attrs textarea (key: value per line)
      const attrsRaw = (draft.fb_attrs_text || "").trim();
      if (attrsRaw) {
        const attrs = {};
        attrsRaw.split("\n").forEach((line) => {
          const eq = line.indexOf(":");
          if (eq > 0) {
            const k = line.slice(0, eq).trim();
            const v = line.slice(eq + 1).trim();
            if (k && v) attrs[k] = v;
          }
        });
        if (Object.keys(attrs).length > 0) fb.attrs = attrs;
      }
      patch.fallbacks = Object.keys(fb).length > 0 ? fb : null;
    }

    // 2026-05 — Random-pick advanced editor.
    // When user edited the per-option list, send pick_options patch.
    // Backend rebuilds the evaluate script with CSS → xpath → text
    // fallback per option.
    if (draft.pickOptionsEdited === true) {
      const cleaned = (draft.pickOptions || [])
        .map(o => ({
          text: (o.text || "").trim(),
          selector: (o.selector || "").trim(),
          xpath: (o.xpath || "").trim(),
        }))
        .filter(o => o.text || o.selector || o.xpath);
      patch.pick_options = cleaned;
    }
    patch.optional = !!draft.optional;
    patch.never_strict = !!draft.never_strict;

    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/step/${index}`, {
        method: "PATCH",
        headers: authH(),
        body: JSON.stringify(patch),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.updated === false) {
        toast.error(d.detail || d.reason || "Edit failed");
        return;
      }
      toast.success(`Step #${index + 1} updated`);
      if (d.alias_saved) {
        // Self-healing memory — let the user know their fix is now
        // permanent for this domain (future replays will auto-recover).
        toast.success("🧠 Selector alias saved — future runs will auto-heal", {
          duration: 5000,
          description: `Krexion will remember this rename for future recordings on this site.`,
        });
      }
      setEditingStep(null);
      refreshState();
    } catch (e) {
      toast.error(e.message || "Edit failed");
    }
  };

  const deleteStep = async (idx) => {
    if (!sessionId) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}/step/${idx}`, {
        method: "DELETE",
        headers: authH(),
      });
      refreshState();
    } catch {}
  };

  // Undo = delete the most recently added step. Visible only when there
  // is at least one step. Maps to Ctrl/Cmd+Z keyboard shortcut.
  const undoLastStep = async () => {
    if (!sessionId || steps.length === 0) return;
    await deleteStep(steps.length - 1);
    toast.success("Undid last step");
  };

  // Load a recent recording from localStorage into the setup form.
  const loadRecent = (r) => {
    setUrl(r.url || "");
    setProxy(r.proxy || "");
    setUa(r.ua || "");
    setHeaders(r.headers || []);
    setHeadersInput((r.headers || []).join(", "));
    if (r.device) setDevicePreset(r.device);
    toast.success("Recent recording loaded — review and Start");
  };

  const clearRecent = async () => {
    if (!await vrConfirm("Clear all recent recordings?")) return;
    setRecentRecordings([]);
    try { localStorage.removeItem(LS_RECENT_KEY); } catch {}
  };

  // Save the finalized automation JSON into the user's Uploaded Things
  // library so they can pick it from a dropdown in the RUT page on every
  // future job without copy-pasting.
  // ── 2026-05: Live Test + Diagnostics ─────────────────────────────
  // Runs the current recorded steps end-to-end (fresh page in same
  // browser context) and shows per-step timing + pass/fail + a Smart
  // Replay Diagnostics summary. User can iterate the recording until
  // every step passes before finalising the JSON.
  const runLiveTest = async (opts = {}) => {
    if (!sessionId) return;
    if (!steps || steps.length === 0) {
      toast.error("Record at least one step first.");
      return;
    }
    // 2026-01: "Replay from here" — `opts.startIndex` skips the first
    // N steps and forces fresh_page=false so the browser stays on its
    // current state (post-previous-failure page).
    const startIndex = Math.max(0, Number(opts.startIndex || 0));
    const freshPage = startIndex > 0 ? false : true;
    const rutParity = opts.rutParity != null ? !!opts.rutParity : !!liveTestRutParity;
    // 2026-06 — Make "Run Live Test from Start" visibly behave like a
    // brand-new RUT job: clear ALL prior live-frame / progress state,
    // show a clear "starting fresh from step 1" toast so the operator
    // knows the test is identical to what an actual job visit will do
    // (fresh page, no leftover cookies, full step list from index 0).
    // This addresses the customer ask "jab live run test krte hein to
    // start se show ho jese aik new job chalate hein".
    if (startIndex === 0) {
      toast(
        rutParity
          ? `▶ RUT parity test — self-heal ON, captcha NOT skipped, strict steps (${steps.length} total)`
          : `▶ Live Test (lenient) — ${steps.length} step${steps.length === 1 ? "" : "s"} from #1`,
        { icon: rutParity ? "🎯" : "🚀", duration: 3500 },
      );
    }
    setLiveTesting(true);
    setLiveTestResult(null);
    // 2026-01: real-time progress feed — clear & start polling
    setLiveProgress([]);
    setLiveFrame(null);
    setLiveFrameMeta(null);
    let sinceIdx = 0;
    const pollProgress = async () => {
      try {
        const r = await fetch(
          `${API_URL}/api/visual-recorder/${sessionId}/live-progress?since=${sinceIdx}`,
          { headers: authH() }
        );
        if (!r.ok) return;
        const d = await r.json();
        if (Array.isArray(d.events) && d.events.length > 0) {
          sinceIdx = d.total_events;
          // 2026-01: pick most recent event that has a screenshot
          // (most actions emit one; some lightweight events skip it)
          for (let i = d.events.length - 1; i >= 0; i--) {
            const e = d.events[i];
            if (e && e.screenshot_b64) {
              setLiveFrame(e.screenshot_b64);
              setLiveFrameMeta({
                idx: e.idx,
                action: e.action,
                selector: e.selector,
                status: e.status,
                page_url: e.page_url,
                ms: e.ms,
              });
              break;
            }
          }
          // Strip screenshot_b64 from the array before keeping in
          // memory to avoid bloating React state.
          const lite = d.events.map((e) => {
            if (!e || !e.screenshot_b64) return e;
            // eslint-disable-next-line no-unused-vars
            const { screenshot_b64, ...rest } = e;
            return rest;
          });
          setLiveProgress((prev) => [...prev, ...lite].slice(-200));
        }
        return d.running;
      } catch {
        return null;
      }
    };
    // Start polling every 400ms
    const pollTimer = setInterval(async () => {
      const stillRunning = await pollProgress();
      // Auto-stop polling if backend says it's finished (but keep one
      // last poll to drain final events)
      if (stillRunning === false) {
        await pollProgress();
        clearInterval(pollTimer);
      }
    }, 400);

    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/live-test`, {
        method: "POST",
        headers: { ...authH(), "Content-Type": "application/json" },
        body: JSON.stringify({
          fresh_page: freshPage,
          start_index: startIndex,
          rut_parity: rutParity,
          sample_row: Object.keys(sampleRow || {}).length ? sampleRow : null,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setLiveTestResult(d);
      if (d.ok) {
        const range = startIndex > 0
          ? ` (resumed from step #${startIndex + 1})`
          : "";
        toast.success(`Live test PASSED — ${d.executed_steps}/${d.total_steps} steps in ${(d.total_ms / 1000).toFixed(1)}s${range}`);
      } else {
        toast.error(
          d.error
            ? `Live test FAILED at step #${(d.failed_at_idx ?? 0) + 1}: ${d.error.slice(0, 120)}`
            : "Live test failed."
        );
      }
    } catch (e) {
      toast.error(`Live test crashed: ${e.message || e}`);
    } finally {
      // Drain final progress events, then stop polling
      try { await pollProgress(); } catch {}
      clearInterval(pollTimer);
      setLiveTesting(false);
    }
  };

  // ── 2026-05: Auto-fix one or all anti-pattern findings ───────────
  // Applies a structured fix (or all auto-fixable fixes in one shot)
  // to the recorder session. Re-fetches steps + diagnostics on
  // success so the UI re-renders with the post-fix state.
  //
  // 2026-05 update: also tracks `fix_history_count` from the response
  // (powers the Undo button) and, when `autoRetestEnabled` is on,
  // automatically triggers Run Live Test after the fix succeeds — so
  // the full loop becomes: Live Test → Auto-fix all → (auto Live Test) →
  // Finalize. Three clicks total.
  const applyAutoFix = async ({ kind, at_step, extra } = {}, applyAll = false) => {
    if (!sessionId) return;
    setLiveTesting(true);
    try {
      const body = applyAll ? { apply_all: true } : { kind, at_step, extra };
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/auto-fix`, {
        method: "POST",
        headers: { ...authH(), "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);

      if (Array.isArray(d.steps)) setSteps(d.steps);
      if (typeof d.fix_history_count === "number") setFixHistoryCount(d.fix_history_count);
      setLastUndoneFix(null); // any new fix invalidates the "last undone" hint

      if (liveTestResult) {
        setLiveTestResult({
          ...liveTestResult,
          diagnostics: d.diagnostics || liveTestResult.diagnostics,
        });
      }

      const nApplied = (d.applied || []).length;
      const nSkipped = (d.skipped || []).length;
      if (applyAll) {
        toast.success(
          nApplied > 0
            ? `Auto-fix applied ${nApplied} fix${nApplied === 1 ? "" : "es"}${nSkipped ? ` · ${nSkipped} skipped` : ""}.`
            : "Nothing to fix — all anti-patterns are non-auto-fixable.",
        );
      } else {
        toast.success(d.applied?.[0]?.summary || "Auto-fix applied.");
      }

      // Auto-retest: if enabled and we actually applied at least one
      // fix, immediately re-run Live Test so the user sees the result
      // of the fix without another click.
      if (autoRetestEnabled && nApplied > 0) {
        // Brief pause so the toast registers + steps state propagates
        // through React before the next fetch fires.
        setTimeout(() => { runLiveTest(); }, 400);
      }
    } catch (e) {
      toast.error(`Auto-fix failed: ${e.message || e}`);
    } finally {
      setLiveTesting(false);
    }
  };

  // ── 2026-05: Undo last auto-fix ──────────────────────────────────
  // Pops the most-recent fix from history and restores the pre-fix
  // snapshot of the steps array. Used when an auto-fix turned out to
  // break something specific to the user's page that the static
  // analyser couldn't predict.
  const undoLastAutoFix = async () => {
    if (!sessionId || fixHistoryCount === 0) return;
    setLiveTesting(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/auto-fix/undo`, {
        method: "POST",
        headers: authH(),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);

      if (Array.isArray(d.steps)) setSteps(d.steps);
      if (typeof d.fix_history_count === "number") setFixHistoryCount(d.fix_history_count);
      setLastUndoneFix(d.undone || null);
      if (liveTestResult) {
        setLiveTestResult({
          ...liveTestResult,
          diagnostics: d.diagnostics || liveTestResult.diagnostics,
        });
      }
      const k = d.undone?.kind || "last fix";
      toast.success(`Undone: ${k}. Run Live Test to re-verify.`);
    } catch (e) {
      toast.error(`Undo failed: ${e.message || e}`);
    } finally {
      setLiveTesting(false);
    }
  };

  const saveToLibrary = async () => {
    if (!finalBundle) return;
    // ── 2026-05: Edit-mode → PATCH the original upload instead of
    // POSTing a new one. Preserves upload_id (every RUT campaign that
    // already references this template keeps working) and updates the
    // step_count badge automatically.
    if (editUploadId && editTemplate) {
      if (!await vrConfirm(
        `Update existing template "${editTemplate.name}" with the edited recording?\n\n` +
        `Step count will go from ${editTemplate.item_count || 0} → ${finalBundle.step_count}. ` +
        `Every saved RUT campaign that references this template will use the new version on its next run.`,
      )) return;
      setSaving(true);
      try {
        const fd = new FormData();
        fd.append("name", editTemplate.name);
        fd.append("automation_json", JSON.stringify(finalBundle.automation_json));
        if (editTemplate.description) {
          fd.append("description", editTemplate.description);
        }
        const r = await fetch(
          `${API_URL}/api/uploads/automation-json/${editUploadId}`,
          {
            method: "PATCH",
            headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
            body: fd,
          },
        );
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        setSavedToLibraryId(d.id || editUploadId);
        toast.success(`Updated "${editTemplate.name}" — every campaign using this template will pick up the new version automatically.`);
      } catch (e) {
        toast.error(`Update failed: ${e.message || e}`);
      } finally {
        setSaving(false);
      }
      return;
    }
    const defaultName = `Recording-${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
    const name = await vrPrompt("Save as template — name?", defaultName);
    if (!name) return;
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("automation_json", JSON.stringify(finalBundle.automation_json));
      fd.append("description", `Recorded on ${new Date().toLocaleString()} · ${finalBundle.step_count} steps · VR session ${finalBundle.session_id?.slice(0, 8) || ""}${finalBundle.target_screenshot_path ? " · target screenshot ✓" : ""}${finalBundle.proxy_provider_id ? ` · provider ${finalBundle.proxy_provider_id}` : ""}`);
      const r = await fetch(`${API_URL}/api/uploads/automation-json`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
        body: fd,
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setSavedToLibraryId(d.id);
      toast.success(`Saved to library as "${name}"`);
    } catch (e) {
      toast.error(`Save failed: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  // ── JSON inline edit (2026-01) ──────────────────────────────────
  // On the Recording Complete page, lets the user toggle the JSON
  // preview into an editable textarea, fix anything by hand
  // (selectors, timeouts, add/remove steps), then save back into the
  // `finalBundle` so the Copy/Download/Save-to-Library + Live Visual
  // Test buttons all use the edited version. Validates the JSON is a
  // non-empty array of step objects.
  const openJsonEditor = () => {
    if (!finalBundle) return;
    setEditingJsonText(JSON.stringify(finalBundle.automation_json, null, 2));
    setEditingJsonError("");
    setEditingJson(true);
  };

  const cancelJsonEditor = () => {
    setEditingJson(false);
    setEditingJsonError("");
  };

  const saveJsonEditor = () => {
    let parsed;
    try {
      parsed = JSON.parse(editingJsonText);
    } catch (e) {
      setEditingJsonError(`Invalid JSON: ${e.message}`);
      return;
    }
    if (!Array.isArray(parsed)) {
      setEditingJsonError("JSON must be an array of step objects (e.g., [{...}, {...}])");
      return;
    }
    if (parsed.length === 0) {
      setEditingJsonError("Steps array cannot be empty");
      return;
    }
    // Per-step lightweight validation
    for (let i = 0; i < parsed.length; i++) {
      const s = parsed[i];
      if (!s || typeof s !== "object") {
        setEditingJsonError(`Step ${i + 1} is not an object`);
        return;
      }
      if (!s.action || typeof s.action !== "string") {
        setEditingJsonError(`Step ${i + 1} is missing 'action' (string)`);
        return;
      }
    }
    setFinalBundle({
      ...finalBundle,
      automation_json: parsed,
      step_count: parsed.length,
    });
    setEditingJson(false);
    setEditingJsonError("");
    toast.success(`JSON updated — ${parsed.length} steps`);
    if (savedToLibraryId) {
      toast.info("Tip: Re-click 'Save to Library' to update the saved template with these edits.", { duration: 6000 });
    }
  };

  // ── Live Visual Test on finalized bundle (2026-01) ───────────────
  // Re-opens a fresh recorder session with the saved URL / proxy / UA,
  // imports the finalized JSON, then drops the UI back into recording
  // mode so the existing "Run Live Test from Start" button + live
  // screenshot polling shows the full automation step-by-step. Any
  // failure surfaces the Smart Fix suggester so the user can edit
  // problematic steps and re-test — and on Finalize again, the
  // updated steps are exported.
  const launchVisualReplay = async () => {
    if (!finalBundle) return;
    if (!finalBundle.url) {
      toast.error("Cannot replay — original URL is missing from the bundle");
      return;
    }
    setReplayLaunching(true);
    try {
      // 1. Start a fresh recorder session with the same params
      const startRes = await fetch(`${API_URL}/api/visual-recorder/start`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          url: finalBundle.url,
          proxy: finalBundle.proxy || null,
          proxy_provider_id: proxyProviderId || null,
          user_agent: finalBundle.user_agent || null,
          headers: finalBundle.headers || [],
          sample_row: Object.keys(sampleRow || {}).length ? sampleRow : null,
        }),
      });
      const startData = await startRes.json();
      if (!startRes.ok) {
        throw new Error(startData.detail || `Failed to start replay session: HTTP ${startRes.status}`);
      }
      const newSid = startData.session_id;

      // 2. Poll until ready (max ~30s)
      let ready = false;
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 500));
        const sr = await fetch(`${API_URL}/api/visual-recorder/${newSid}/state`, { headers: authH() });
        const sd = await sr.json().catch(() => ({}));
        if (sd.state === "ready") { ready = true; break; }
        if (sd.state === "error") {
          throw new Error(sd.error_msg || "Replay session failed to start");
        }
      }
      if (!ready) {
        throw new Error("Replay session timed out while loading the page");
      }

      // 3. Import the saved steps into the new session
      const impRes = await fetch(`${API_URL}/api/visual-recorder/${newSid}/import-steps`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          steps: finalBundle.automation_json,
          sample_row: Object.keys(sampleRow || {}).length ? sampleRow : null,
          headers: finalBundle.headers || [],
        }),
      });
      const impData = await impRes.json();
      if (!impRes.ok || impData.imported === false) {
        throw new Error(impData.detail || impData.reason || "Failed to import steps");
      }

      // 4. Transition UI back into recording mode with the imported state
      setSessionId(newSid);
      setSessionState("ready");
      setSteps(finalBundle.automation_json);
      setUrl(finalBundle.url);
      setProxy(finalBundle.proxy || "");
      setUa(finalBundle.user_agent || "");
      setHeaders(finalBundle.headers || []);
      setFinalBundle(null);
      setEditingJson(false);
      setSetupStage("recording");
      toast.success(`Replay session ready — ${impData.total} steps loaded. Click "Run Live Test from Start" to watch the full flow.`, { duration: 6000 });
    } catch (e) {
      toast.error(`Visual replay failed: ${e.message || e}`);
    } finally {
      setReplayLaunching(false);
    }
  };

  // ── Finalize ──────────────────────────────────────────────────────
  const finalize = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/finalize`, {
        method: "POST",
        headers: authH(),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setFinalBundle(d);
      setSetupStage("done");
      setFinalizeChecklistOpen(false);
      toast.success(`Recording complete — ${d.step_count} steps`);
    } catch (err) {
      toast.error(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const requestFinalize = () => {
    if (steps.length < 2) return;
    setFinalizeChecklistOpen(true);
  };

  const stopAndDiscard = async () => {
    if (!sessionId) return;
    if (!await vrConfirm("Discard recording and stop session?")) return;
    try {
      await fetch(`${API_URL}/api/visual-recorder/${sessionId}`, {
        method: "DELETE",
        headers: authH(),
      });
    } catch {}
    setSessionId(null);
    setSteps([]);
    setSetupStage("setup");
    setSessionState("starting");
    setSessionError("");
    setShotTick(0);
    toast.success("Session stopped");
  };

  const copyJson = () => {
    if (!finalBundle) return;
    const txt = JSON.stringify(finalBundle.automation_json, null, 2);
    navigator.clipboard.writeText(txt).then(() => toast.success("JSON copied to clipboard"));
  };

  const downloadJson = () => {
    if (!finalBundle) return;
    const txt = JSON.stringify(finalBundle.automation_json, null, 2);
    const blob = new Blob([txt], { type: "application/json" });
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u;
    a.download = `automation_${finalBundle.session_id?.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(u);
  };

  const downloadTargetScreenshot = () => {
    if (!finalBundle?.target_screenshot_path) {
      toast.error("No final page was marked");
      return;
    }
    const a = document.createElement("a");
    a.href = `${API_URL}/api/visual-recorder/${finalBundle.session_id}/target-screenshot`;
    a.download = `target_${finalBundle.session_id?.slice(0, 8)}.png`;
    // Need auth for the GET — open with token via fetch+blob instead
    fetch(a.href, { headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } })
      .then((r) => r.blob())
      .then((b) => {
        const u = URL.createObjectURL(b);
        a.href = u;
        a.click();
        URL.revokeObjectURL(u);
      });
  };

  // ── UI ────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-b from-zinc-950 via-zinc-950 to-black text-zinc-100" data-testid="visual-recorder-page">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        <div className="mb-4 p-3 rounded-lg bg-amber-950/30 border border-amber-700/40 text-sm text-amber-100" data-testid="vr-desktop-banner">
          Visual Recorder live browser recording requires <strong>Krexion Desktop</strong> (local mode).
          Cloud par aap JSON edit / Live Test kar sakte hain; recording ke liye desktop app kholein.
        </div>
        {/* ─── Header (pro-grade, with live session badge) ─── */}
        <div className="flex flex-wrap items-center justify-between mb-5 gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              to="/real-user-traffic"
              className="p-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
              data-testid="vr-back-btn"
              title="Back to Real-User-Traffic"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold flex items-center gap-2">
                <span className="relative inline-flex">
                  <Camera className="w-6 h-6 text-emerald-400" />
                  {setupStage === "recording" && sessionState === "ready" && (
                    <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                  )}
                </span>
                Visual Recorder
                <span className="text-[10px] font-normal text-zinc-500 ml-1 hidden sm:inline">PRO</span>
              </h1>
              <p className="text-sm text-zinc-400 truncate">
                Click your way through any offer page → automatic JSON for RUT
              </p>
            </div>
          </div>

          {/* Right-side cluster — live stats during recording */}
          <div className="flex items-center gap-2 flex-wrap">
            {setupStage === "recording" && (
              <>
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border ${
                    sessionState === "ready"
                      ? "bg-emerald-950/50 border-emerald-700/40 text-emerald-300"
                      : sessionState === "error"
                      ? "bg-rose-950/50 border-rose-700/40 text-rose-300"
                      : "bg-amber-950/50 border-amber-700/40 text-amber-300"
                  }`}
                  data-testid="vr-session-badge"
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      sessionState === "ready"
                        ? "bg-emerald-400 animate-pulse"
                        : sessionState === "error"
                        ? "bg-rose-400"
                        : "bg-amber-400 animate-pulse"
                    }`}
                  />
                  {sessionState === "ready" ? "REC" : sessionState === "error" ? "ERROR" : "CONNECTING"}
                </div>
                {sessionState === "ready" && (
                  <div
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono bg-zinc-900 border border-zinc-800 text-zinc-300"
                    data-testid="vr-elapsed-timer"
                    title="Recording elapsed time"
                  >
                    <Clock className="w-3 h-3 text-emerald-400" />
                    {fmtTimer(recordingElapsed)}
                  </div>
                )}
                <div
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-indigo-950/40 border border-indigo-700/40 text-indigo-300"
                  data-testid="vr-step-counter"
                  title="Steps recorded so far"
                >
                  <Activity className="w-3 h-3" />
                  {steps.length} step{steps.length === 1 ? "" : "s"}
                </div>
                {/* ── 2026-01: Minimize button ──────────────────────
                    Keeps the recorder ALIVE in the background and
                    returns the user to the setup screen, where they
                    can start a 2nd / 3rd recorder OR switch to any
                    other running session via the Active Sessions
                    panel. Standard "minimize to background" flow. */}
                {sessionId && (
                  <button
                    onClick={() => {
                      setSetupStage("setup");
                      toast.success("Recorder minimized — still running in background. Reopen from \"Active recorder sessions\" panel.", { duration: 4500 });
                    }}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 hover:text-emerald-300 transition-colors"
                    data-testid="vr-minimize-btn"
                    title="Minimize (keeps session alive in background, lets you start another)"
                  >
                    <ArrowLeft className="w-3 h-3" />
                    Minimize
                  </button>
                )}
              </>
            )}
            <button
              onClick={() => setShowShortcuts((v) => !v)}
              className="p-1.5 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-400 hover:text-emerald-400"
              data-testid="vr-shortcuts-toggle"
              title="Keyboard shortcuts"
            >
              <Keyboard className="w-4 h-4" />
            </button>
            <button
              onClick={() => setShowHelp(!showHelp)}
              className="text-xs px-2 py-1 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-400 hover:text-emerald-400"
              data-testid="vr-help-toggle"
            >
              {showHelp ? "Hide help" : "Help"}
            </button>
          </div>
        </div>

        {/* Keyboard-shortcut cheat sheet (toggle) */}
        {showShortcuts && (
          <div
            className="mb-5 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 text-sm"
            data-testid="vr-shortcuts-panel"
          >
            <div className="flex items-center gap-2 font-medium text-emerald-400 mb-3">
              <Keyboard className="w-4 h-4" /> Keyboard Shortcuts
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-zinc-300">
              {TOOLS.map((t) => (
                <div key={t.id} className="flex items-center gap-2">
                  <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-200 font-mono">{t.key}</kbd>
                  <span className="text-zinc-400">→ {t.label}</span>
                </div>
              ))}
              <div className="flex items-center gap-2">
                <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-200 font-mono">Esc</kbd>
                <span className="text-zinc-400">→ Cancel pending</span>
              </div>
              <div className="flex items-center gap-2">
                <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-200 font-mono">Ctrl+Z</kbd>
                <span className="text-zinc-400">→ Undo last step</span>
              </div>
              <div className="flex items-center gap-2">
                <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-200 font-mono">Ctrl+Enter</kbd>
                <span className="text-zinc-400">→ Finalize</span>
              </div>
            </div>
          </div>
        )}

        {showHelp && (
          <div className="mb-5 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 text-sm text-zinc-300 space-y-2">
            <div className="flex items-center gap-2 font-medium text-emerald-400"><Sparkles className="w-4 h-4" /> Quick guide</div>
            <ol className="list-decimal list-inside space-y-1 text-zinc-400">
              <li>Enter the offer URL (and optionally proxy + UA + Excel headers)</li>
              <li>Click <b>Start Recording</b> — a real Chromium opens server-side and shows you live</li>
              <li>Use the toolbar: <b>Click</b> for buttons, <b>Form Fill</b> for inputs, <b>Dropdown</b> for &lt;select&gt;, <b>Check Box</b> for consent/agree, <b>Random Pick</b> for surveys</li>
              <li>Need to scroll? Use scroll buttons. Need to wait? Use Wait shortcut.</li>
              <li>When you reach the conversion page, switch to <b>Mark Final</b> tool and click anywhere</li>
              <li>Hit <b>Finalize & Generate</b> — copy/download the JSON</li>
            </ol>
          </div>
        )}

        {/* SETUP stage */}
        {setupStage === "setup" && (
          <div className="space-y-5">
            {/* ── 2026-01: Active Sessions panel ────────────────────
                Shows every recorder this user has running right now
                so the 5-concurrent cap is never a mystery. Each row
                lets the user OPEN (switch to / minimize current) or
                STOP a session. */}
            {activeSessions.length > 0 && (
              <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-700/30" data-testid="vr-active-sessions-panel">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-emerald-200">
                    <Activity className="w-4 h-4 text-emerald-400 animate-pulse" />
                    Active recorder sessions
                    <span
                      className={`ml-1 text-[11px] px-1.5 py-0.5 rounded ${
                        activeSessionStats.user_session_count >= activeSessionStats.max_concurrent
                          ? "bg-rose-700/40 border border-rose-500/40 text-rose-200"
                          : "bg-emerald-700/40 border border-emerald-500/40 text-emerald-200"
                      }`}
                      data-testid="vr-active-count"
                    >
                      {activeSessionStats.user_session_count}/{activeSessionStats.max_concurrent} in use
                    </span>
                  </div>
                  <button
                    onClick={refreshActiveSessions}
                    className="text-[11px] text-zinc-500 hover:text-emerald-300 inline-flex items-center gap-1"
                    data-testid="vr-active-refresh"
                    title="Refresh list"
                  >
                    <RefreshCw className="w-3 h-3" /> refresh
                  </button>
                </div>
                <div className="space-y-2">
                  {activeSessions.map((s) => {
                    const hostname = (() => {
                      try { return new URL(s.current_url || s.url).hostname; } catch { return (s.url || "").slice(0, 40); }
                    })();
                    const stateColor =
                      s.state === "ready"
                        ? "bg-emerald-700/40 border-emerald-500/40 text-emerald-200"
                        : s.state === "error"
                        ? "bg-rose-700/40 border-rose-500/40 text-rose-200"
                        : "bg-amber-700/40 border-amber-500/40 text-amber-200";
                    const stateLabel =
                      s.state === "ready" ? "REC" :
                      s.state === "error" ? "ERROR" :
                      s.state === "starting" ? "CONNECTING" :
                      String(s.state || "").toUpperCase();
                    const mins = Math.floor((s.elapsed_seconds || 0) / 60);
                    const secs = (s.elapsed_seconds || 0) % 60;
                    const elapsedStr = `${String(mins).padStart(2,"0")}:${String(secs).padStart(2,"0")}`;
                    return (
                      <div
                        key={s.session_id}
                        className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-zinc-900/70 border border-zinc-800 hover:border-emerald-600/40 transition-colors"
                        data-testid={`vr-active-session-${s.session_id}`}
                      >
                        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold border ${stateColor} shrink-0`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${s.state === "ready" ? "bg-emerald-400 animate-pulse" : s.state === "error" ? "bg-rose-400" : "bg-amber-400 animate-pulse"}`} />
                          {stateLabel}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-zinc-200 truncate font-medium" title={s.current_url || s.url}>
                            <Globe className="w-3 h-3 inline mr-1 text-emerald-400" />
                            {hostname}
                          </div>
                          <div className="text-[10px] text-zinc-500 flex items-center gap-2 mt-0.5">
                            <span title="Recording elapsed time"><Clock className="w-2.5 h-2.5 inline mr-0.5" />{elapsedStr}</span>
                            <span>·</span>
                            <span>{s.step_count} step{s.step_count === 1 ? "" : "s"}</span>
                            <span>·</span>
                            <span className="font-mono text-[9px] text-zinc-600" title="Session ID">{(s.session_id || "").slice(0, 8)}</span>
                          </div>
                          {s.state === "error" && s.error_message && (
                            <div className="text-[10px] text-rose-400/80 mt-0.5 truncate" title={s.error_message}>
                              {s.error_message.split("\n")[0].slice(0, 90)}
                            </div>
                          )}
                        </div>
                        <button
                          onClick={() => switchToSession(s)}
                          className="px-2.5 py-1 rounded-md bg-emerald-700/40 hover:bg-emerald-600/60 border border-emerald-500/40 text-emerald-200 text-xs font-medium inline-flex items-center gap-1 transition-colors shrink-0"
                          data-testid={`vr-active-open-${s.session_id}`}
                          title="Switch to this session"
                        >
                          <Play className="w-3 h-3" /> Open
                        </button>
                        <button
                          onClick={() => stopSessionById(s.session_id, hostname)}
                          className="px-2.5 py-1 rounded-md bg-rose-700/40 hover:bg-rose-600/60 border border-rose-500/40 text-rose-200 text-xs font-medium inline-flex items-center gap-1 transition-colors shrink-0"
                          data-testid={`vr-active-stop-${s.session_id}`}
                          title="Stop this session (frees a slot)"
                        >
                          <Square className="w-3 h-3" /> Stop
                        </button>
                      </div>
                    );
                  })}
                </div>
                {activeSessionStats.user_session_count >= activeSessionStats.max_concurrent && (
                  <div className="mt-3 text-[11px] text-amber-300 bg-amber-950/30 border border-amber-700/40 rounded-md px-3 py-2">
                    ⚠️ You've hit the max ({activeSessionStats.max_concurrent}) concurrent recorders. Stop one above to start a new recording, or click <b>Open</b> to continue an existing one.
                  </div>
                )}
              </div>
            )}

            {/* Recent recordings — quick re-use (last 5) */}
            {recentRecordings.length > 0 && (
              <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800" data-testid="vr-recent-panel">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 text-sm font-medium text-zinc-300">
                    <History className="w-4 h-4 text-emerald-400" /> Recent recordings
                  </div>
                  <button
                    onClick={clearRecent}
                    className="text-[11px] text-zinc-500 hover:text-rose-400"
                    data-testid="vr-clear-recent"
                  >
                    clear
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {recentRecordings.map((r, i) => (
                    <button
                      key={i}
                      onClick={() => loadRecent(r)}
                      className="text-xs px-2.5 py-1 rounded-md bg-zinc-800/80 hover:bg-emerald-700/40 border border-zinc-700 hover:border-emerald-500/40 text-zinc-300 hover:text-emerald-200 max-w-[280px] truncate transition-colors"
                      title={r.url}
                      data-testid={`vr-recent-${i}`}
                    >
                      <Globe className="w-3 h-3 inline mr-1" />
                      {(() => {
                        try { return new URL(r.url).hostname; } catch { return r.url.slice(0, 40); }
                      })()}
                      <span className="text-[10px] text-zinc-500 ml-1">· {r.device || "mobile"}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="grid md:grid-cols-2 gap-5">
              <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
                <h2 className="text-lg font-medium mb-3 flex items-center gap-2"><Globe className="w-5 h-5 text-emerald-400" />Target</h2>
                <label className="block text-sm font-medium text-zinc-300 mb-1">Offer URL <span className="text-rose-400">*</span></label>
                <input
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://your-offer.com/landing"
                  className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-100 placeholder-zinc-600 focus:border-emerald-500 focus:outline-none transition-colors"
                  data-testid="vr-url-input"
                />

                {/* Device preset selector */}
                <label className="block text-sm font-medium text-zinc-300 mb-1 mt-3">Device preset</label>
                <div className="grid grid-cols-3 gap-2" data-testid="vr-device-presets">
                  {DEVICE_PRESETS.map((d) => {
                    const Ic = d.icon;
                    const active = devicePreset === d.id;
                    return (
                      <button
                        key={d.id}
                        onClick={() => setDevicePreset(d.id)}
                        className={`flex flex-col items-center justify-center gap-1 py-2.5 rounded-lg border text-xs font-medium transition-colors ${
                          active
                            ? "bg-emerald-600 text-white border-emerald-500"
                            : "bg-zinc-950 hover:bg-zinc-800 border-zinc-800 text-zinc-300"
                        }`}
                        title={d.hint}
                        data-testid={`vr-device-${d.id}`}
                      >
                        <Ic className="w-4 h-4" />
                        {d.label}
                        <span className="text-[9px] opacity-70">{d.width}×{d.height}</span>
                      </button>
                    );
                  })}
                </div>

                {/* ── 2026-01 (mobile fingerprint coherence) ──
                    Country picks locale + timezone + geolocation for the
                    recorder browser. Critical for offers that geo-fence
                    via JS clock / Intl API (e.g. PK offer in NY timezone
                    is an instant tell). */}
                <label className="block text-sm font-medium text-zinc-300 mb-1 mt-3" data-testid="vr-country-label">
                  Country <span className="text-zinc-500 font-normal text-xs">(locale + timezone + geo)</span>
                </label>
                <select
                  value={country}
                  onChange={(e) => setCountry(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-100 focus:border-emerald-500 focus:outline-none transition-colors"
                  data-testid="vr-country-select"
                >
                  <option value="US">United States (en-US, America/New_York)</option>
                  <option value="GB">United Kingdom (en-GB, Europe/London)</option>
                  <option value="CA">Canada (en-CA, America/Toronto)</option>
                  <option value="AU">Australia (en-AU, Australia/Sydney)</option>
                  <option value="DE">Germany (de-DE, Europe/Berlin)</option>
                  <option value="FR">France (fr-FR, Europe/Paris)</option>
                  <option value="ES">Spain (es-ES, Europe/Madrid)</option>
                  <option value="IT">Italy (it-IT, Europe/Rome)</option>
                  <option value="NL">Netherlands (nl-NL, Europe/Amsterdam)</option>
                  <option value="BR">Brazil (pt-BR, America/Sao_Paulo)</option>
                  <option value="MX">Mexico (es-MX, America/Mexico_City)</option>
                  <option value="IN">India (en-IN, Asia/Kolkata)</option>
                  <option value="PK">Pakistan (en-PK, Asia/Karachi)</option>
                  <option value="BD">Bangladesh (bn-BD, Asia/Dhaka)</option>
                  <option value="ID">Indonesia (id-ID, Asia/Jakarta)</option>
                  <option value="PH">Philippines (en-PH, Asia/Manila)</option>
                  <option value="TH">Thailand (th-TH, Asia/Bangkok)</option>
                  <option value="MY">Malaysia (en-MY, Asia/Kuala_Lumpur)</option>
                  <option value="SG">Singapore (en-SG, Asia/Singapore)</option>
                  <option value="JP">Japan (ja-JP, Asia/Tokyo)</option>
                  <option value="KR">South Korea (ko-KR, Asia/Seoul)</option>
                  <option value="AE">UAE (en-AE, Asia/Dubai)</option>
                  <option value="SA">Saudi Arabia (ar-SA, Asia/Riyadh)</option>
                  <option value="TR">Turkey (tr-TR, Europe/Istanbul)</option>
                  <option value="IL">Israel (he-IL, Asia/Jerusalem)</option>
                  <option value="EG">Egypt (ar-EG, Africa/Cairo)</option>
                  <option value="ZA">South Africa (en-ZA, Africa/Johannesburg)</option>
                  <option value="NG">Nigeria (en-NG, Africa/Lagos)</option>
                  <option value="RU">Russia (ru-RU, Europe/Moscow)</option>
                  <option value="PL">Poland (pl-PL, Europe/Warsaw)</option>
                  <option value="SE">Sweden (sv-SE, Europe/Stockholm)</option>
                  <option value="NZ">New Zealand (en-NZ, Pacific/Auckland)</option>
                </select>

                <label className="block text-sm font-medium text-zinc-300 mb-1 mt-3">
                  Proxy Provider <span className="text-zinc-500 font-normal text-xs">(optional — from Settings › Proxy Providers)</span>
                </label>
                <select
                  value={proxyProviderId}
                  onChange={(e) => onProxyProviderChange(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-100 focus:border-emerald-500 focus:outline-none transition-colors"
                  data-testid="vr-proxy-provider"
                >
                  <option value="">(none — paste proxy manually)</option>
                  {proxyProviders.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {(p.kind || "").replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
                {!pjAvailable && (
                  <p className="text-[10px] text-zinc-500 mt-1">
                    Tip: add a Proxy Provider in Settings › Proxy Providers to fetch fresh proxies here.
                  </p>
                )}

                <div className="mt-3 flex items-center justify-between">
                  <label className="block text-sm font-medium text-zinc-300 mb-1">
                    Proxy <span className="text-zinc-500 font-normal">(optional)</span>
                  </label>
                  {pjAvailable && (
                    <button
                      onClick={useProxyJetProxy}
                      disabled={busy || !proxyProviderId}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-indigo-600/30 hover:bg-indigo-600/60 border border-indigo-500/40 text-indigo-200 disabled:opacity-50"
                      data-testid="vr-use-provider-proxy"
                      title="Fetch a fresh proxy from the selected Proxy Provider"
                    >
                      <Zap className="w-3 h-3" /> From Provider
                    </button>
                  )}
                </div>
                <input
                  type="text"
                  value={proxy}
                  onChange={(e) => setProxy(e.target.value)}
                  placeholder="http://user:pass@host:port  or  host:port"
                  className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-100 placeholder-zinc-600 focus:border-emerald-500 focus:outline-none font-mono text-xs transition-colors"
                  data-testid="vr-proxy-input"
                />
                <label className="block text-sm font-medium text-zinc-300 mb-1 mt-3">User Agent <span className="text-zinc-500 font-normal">(optional)</span></label>
                <input
                  type="text"
                  value={ua}
                  onChange={(e) => setUa(e.target.value)}
                  placeholder={devicePreset === "desktop" ? "Defaults to Chrome desktop UA" : devicePreset === "tablet" ? "Defaults to iPad UA" : "Defaults to Pixel 7 mobile UA"}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-100 placeholder-zinc-600 focus:border-emerald-500 focus:outline-none text-xs transition-colors"
                  data-testid="vr-ua-input"
                />
              </div>

            <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
              <h2 className="text-lg font-medium mb-3 flex items-center gap-2"><ListPlus className="w-5 h-5 text-emerald-400" />Excel Headers <span className="text-xs text-zinc-500 font-normal">(for form fill)</span></h2>

              <p className="text-xs text-zinc-400 mb-3">Upload the same Excel you'll use in RUT — we'll detect column names so you can bind form inputs. <b>Or</b> type them manually below.</p>

              <label className="block text-sm font-medium text-zinc-300 mb-1">Upload Excel</label>
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={onExcelUpload}
                className="w-full text-sm text-zinc-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:bg-emerald-700/40 file:text-emerald-200 hover:file:bg-emerald-700/60"
                data-testid="vr-excel-input"
              />
              {excelFile && (
                <div className="mt-1 text-xs text-zinc-500">📄 {excelFile.name}</div>
              )}

              <label className="block text-sm font-medium text-zinc-300 mb-1 mt-3">Or type headers (comma-separated)</label>
              <input
                type="text"
                value={headersInput}
                onChange={(e) => setHeadersInput(e.target.value)}
                onBlur={applyManualHeaders}
                placeholder="first, last, email, phone, day, month, year"
                className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-100 placeholder-zinc-600 focus:border-emerald-500 focus:outline-none text-sm"
                data-testid="vr-headers-input"
              />
              {headers.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {headers.map((h) => (
                    <span key={h} className="px-2 py-0.5 rounded bg-emerald-700/30 border border-emerald-500/30 text-emerald-200 text-xs">
                      {h}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="md:col-span-2 flex flex-col items-center gap-3">
              {/* 2026-05: Edit-mode banner — visible whenever the page
                  was opened via `?edit_upload_id=X`. Tells the user
                  EXACTLY what will happen when they click Start. */}
              {editUploadId && (
                <div
                  className="w-full max-w-2xl rounded-xl border border-indigo-500/40 bg-indigo-500/10 px-4 py-3 text-sm text-indigo-200 flex items-start gap-3"
                  data-testid="vr-edit-mode-banner"
                >
                  <Pencil className="w-5 h-5 shrink-0 mt-0.5 text-indigo-300" />
                  <div className="flex-1">
                    <div className="font-semibold mb-0.5 text-indigo-100">
                      Editing template: {editTemplate?.name || "(loading…)"}
                    </div>
                    <div className="text-xs text-indigo-200/80 leading-relaxed">
                      Click <b>Start Recording</b> below — your existing{" "}
                      <b>{editTemplate?.item_count ?? "…"} steps</b> will load
                      automatically. You can re-record over them, reorder, fix
                      selectors live, delete, or append new steps. Saving will
                      update this SAME template (upload ID preserved → every
                      RUT campaign using it keeps working).
                    </div>
                  </div>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3 justify-center">
                <button
                  onClick={startRecording}
                  disabled={busy || (editUploadId ? !editTemplate : !url.trim())}
                  className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-medium text-base transition-colors shadow-lg shadow-emerald-900/30"
                  data-testid="vr-start-btn"
                >
                  {busy ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
                  {editUploadId ? "Start Editing (loads existing steps)" : "Start Recording"}
                </button>
                {/* 2026-06 — AI step generator (per-user provider config in Settings → AI Integrations) */}
                <button
                  type="button"
                  onClick={() => { setAiDialogOpen(true); setAiError(""); }}
                  disabled={busy}
                  className="inline-flex items-center gap-2 px-5 py-3 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white font-medium text-base transition-colors shadow-lg shadow-purple-900/30"
                  data-testid="vr-ai-generate-btn"
                  title="Auto-generate Visual Recorder steps from screenshots/video using your configured AI provider (Settings → AI Integrations)"
                >
                  <Sparkles className="w-5 h-5" />
                  Generate with AI
                </button>
              </div>
              {editUploadId && !url.trim() && (
                <p className="text-[11px] text-zinc-500 max-w-md text-center mt-1">
                  No URL — recorder will open <code className="text-zinc-400">about:blank</code>.
                  You can still reorder / edit / delete / append steps. To add
                  new <em>recorded clicks</em>, type the offer URL above or
                  use the Navigate box after the session starts.
                </p>
              )}
            </div>
          </div>
          </div>
        )}

        {/* RECORDING stage */}
        {setupStage === "recording" && (
          <div className="grid lg:grid-cols-3 gap-4">
            {/* Live preview */}
            <div className="lg:col-span-2 p-3 rounded-xl bg-zinc-900/60 border border-zinc-800">
              <div className="flex items-center justify-between mb-2 px-1">
                <div className="flex items-center gap-2 text-xs text-zinc-400 truncate">
                  <Globe className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="truncate" title={pageMeta.url}>{pageMeta.url || "loading…"}</span>
                </div>
                <button onClick={refreshScreenshot} title="Refresh" className="p-1 text-zinc-400 hover:text-emerald-400">
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* ── 2026-01 (multi-tab) — Browser-style tabs strip ──
                  Renders one chip per open Chromium tab in the recorder
                  session. The active tab is highlighted; clicking any
                  other tab switches the live preview to it (subsequent
                  /click / /type act on that tab). When the offer page
                  opens a new tab (target="_blank", window.open) it
                  appears here automatically AND is auto-promoted to
                  active so the user instantly sees the destination
                  page.
                  
                  2026-06 — A dedicated "Switch to Tab" button is now
                  ALWAYS visible (even when there's only 1 tab) so the
                  operator can confidently switch tabs without searching
                  the UI. Clicking it opens a modal listing every open
                  tab with title + URL. */}
              {sessionState === "ready" && (
                <div
                  className="flex items-center gap-1 mb-2 px-1 overflow-x-auto pb-1"
                  data-testid="vr-tabs-strip"
                >
                  {/* Always-visible "Switch to Tab" button — opens the
                      tab-picker modal with the full list of open tabs
                      so the operator can pick one without confusion. */}
                  <button
                    type="button"
                    onClick={() => setShowTabPicker(true)}
                    title={`Switch to tab… (${tabs.length} open)`}
                    data-testid="vr-switch-tab-btn"
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold whitespace-nowrap bg-blue-600/20 hover:bg-blue-600/40 text-blue-200 border border-blue-500/40 hover:border-blue-400 transition-colors"
                  >
                    <ArrowLeftRight className="w-3.5 h-3.5" />
                    <span>Switch to Tab</span>
                    <span className="ml-0.5 px-1.5 py-0 rounded-full bg-blue-500/30 text-blue-100 text-[10px]">
                      {tabs.length}
                    </span>
                  </button>

                  {/* v2.1.74 — JS dialog (alert/confirm/prompt) banner */}
                  {pendingDialog && (
                    <div
                      data-testid="vr-dialog-banner"
                      className="ml-2 flex items-center gap-2 px-3 py-1.5 rounded-md bg-amber-500/20 border border-amber-400/60 shadow-[0_0_0_1px_rgba(251,191,36,0.4)] animate-pulse"
                    >
                      <span className="text-amber-200 text-[11px] font-bold uppercase tracking-wide">
                        {pendingDialog.type}()
                      </span>
                      <span className="text-amber-100 text-[12px] max-w-[280px] truncate" title={pendingDialog.message}>
                        {pendingDialog.message || "(no message)"}
                      </span>
                      {pendingDialog.type === "prompt" && (
                        <input
                          type="text"
                          data-testid="vr-dialog-prompt-input"
                          value={dialogPromptText}
                          onChange={(e) => setDialogPromptText(e.target.value)}
                          placeholder={pendingDialog.default_value || "type response…"}
                          className="px-2 py-0.5 rounded bg-zinc-900 border border-amber-500/50 text-amber-100 text-[11px] w-32"
                        />
                      )}
                      <button
                        type="button"
                        data-testid="vr-dialog-accept-btn"
                        onClick={() => answerDialog("accept")}
                        className="px-2 py-0.5 rounded bg-emerald-500/30 hover:bg-emerald-500/50 text-emerald-100 text-[11px] font-semibold border border-emerald-400/60"
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        data-testid="vr-dialog-dismiss-btn"
                        onClick={() => answerDialog("dismiss")}
                        className="px-2 py-0.5 rounded bg-rose-500/30 hover:bg-rose-500/50 text-rose-100 text-[11px] font-semibold border border-rose-400/60"
                      >
                        Dismiss
                      </button>
                    </div>
                  )}

                  {/* Existing inline tab strip (kept for quick clicks). */}
                  {tabs.length > 1 && (
                    <p className="w-full text-[10px] text-zinc-500 px-1 mb-0.5">
                      💡 Naya tab khule to yahan click karein — <code className="text-zinc-400">switch_tab</code> step auto record hota hai.
                    </p>
                  )}
                  {tabs.length > 1 && tabs.map((t) => {
                    const isActive = t.is_active || t.index === activeTabIndex;
                    let domain = "";
                    try { domain = t.url ? new URL(t.url).hostname.replace(/^www\./, "") : ""; } catch {}
                    const label = (t.title && t.title !== t.url ? t.title : domain) || `Tab ${t.index + 1}`;
                    return (
                      <button
                        key={t.index}
                        onClick={() => switchTab(t.index)}
                        title={t.url || label}
                        data-testid={`vr-tab-${t.index}`}
                        className={`group flex items-center gap-1.5 px-2.5 py-1 rounded-t-md text-[11px] font-medium whitespace-nowrap border-b-2 transition-colors ${
                          isActive
                            ? "bg-zinc-800 text-emerald-300 border-emerald-400"
                            : "bg-zinc-900/70 text-zinc-400 border-transparent hover:text-zinc-200 hover:bg-zinc-800/70"
                        }`}
                      >
                        <Globe className="w-3 h-3 shrink-0 opacity-70" />
                        <span className="max-w-[140px] truncate">{label}</span>
                        {tabs.length > 1 && (
                          <span
                            onClick={(e) => closeTab(t.index, e)}
                            data-testid={`vr-tab-close-${t.index}`}
                            className="ml-0.5 w-3.5 h-3.5 inline-flex items-center justify-center rounded-sm opacity-0 group-hover:opacity-100 hover:bg-rose-500/40 hover:text-rose-200 text-zinc-500 transition-all cursor-pointer"
                            title="Close tab"
                          >
                            <X className="w-2.5 h-2.5" />
                          </span>
                        )}
                      </button>
                    );
                  })}
                  {tabs.length > 1 && (
                    <div className="ml-1 text-[10px] text-zinc-500 self-center px-1">
                      {tabs.length} tabs
                    </div>
                  )}
                </div>
              )}

              {/* Live image */}
              <div className="relative bg-zinc-950 rounded-lg overflow-hidden flex justify-center">
                {sessionState === "error" ? (
                  <div className="aspect-[412/914] w-full flex flex-col items-center justify-center text-rose-300 text-sm gap-3 px-6 text-center" data-testid="vr-error-state">
                    <AlertCircle className="w-12 h-12 text-rose-400" />
                    <div className="font-medium text-rose-200">Connection failed</div>
                    <div className="text-xs text-zinc-400 max-w-xs leading-relaxed">{sessionError}</div>
                    <div className="text-[11px] text-zinc-500 max-w-xs leading-relaxed bg-zinc-900/60 rounded-md p-2 border border-zinc-800">
                      <span className="text-amber-300 font-medium">Common fixes:</span>{" "}
                      {sessionError.toLowerCase().includes("proxy") || sessionError.toLowerCase().includes("auth")
                        ? "Verify proxy credentials, ensure your IP is whitelisted at the proxy provider, or try a different gateway."
                        : sessionError.toLowerCase().includes("timeout") || sessionError.toLowerCase().includes("nav")
                        ? "Page may be slow — try without proxy first, or pick a closer proxy region."
                        : "Check the URL is correct & publicly reachable; confirm proxy is alive."}
                    </div>
                    <button
                      onClick={async () => {
                        try { await fetch(`${API_URL}/api/visual-recorder/${sessionId}`, { method: "DELETE", headers: authH() }); } catch {}
                        setSessionId(null);
                        setSessionState("starting");
                        setSessionError("");
                        setSetupStage("setup");
                      }}
                      className="mt-1 px-4 py-2 rounded-lg bg-rose-700 hover:bg-rose-600 text-white text-xs font-medium transition-colors"
                      data-testid="vr-retry-btn"
                    >
                      <ArrowLeft className="w-3 h-3 inline mr-1" /> Back to Setup
                    </button>
                  </div>
                ) : sessionState !== "ready" ? (
                  <div className="aspect-[412/914] w-full flex flex-col items-center justify-center text-zinc-400 text-sm gap-3 px-6" data-testid="vr-connecting-state">
                    <div className="relative">
                      <Loader2 className="w-10 h-10 animate-spin text-emerald-400" />
                      <div className="absolute inset-0 flex items-center justify-center text-[10px] text-emerald-300 font-mono">
                        {connectElapsed}s
                      </div>
                    </div>
                    <div className="font-medium text-zinc-200">
                      Spinning up Chromium {proxy ? "via proxy" : "directly"}…
                    </div>
                    <div className="text-[11px] text-zinc-500 text-center max-w-xs leading-relaxed">
                      Launching anti-detect browser → resolving DNS → opening page.<br />
                      <span className="text-amber-300">Slow proxies can take up to 45 seconds.</span>
                    </div>
                    {/* Progress shimmer */}
                    <div className="w-32 h-1 rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        className="h-full bg-emerald-500 transition-all"
                        style={{ width: `${Math.min(100, (connectElapsed / 45) * 100)}%` }}
                      />
                    </div>
                  </div>
                ) : screenshotSrc ? (
                  <>
                    <img
                      ref={imgRef}
                      src={screenshotSrc}
                      alt="Live preview"
                      onClick={handleImgClick}
                      onLoad={() => setShotErrorCount(0)}
                      onError={() => setShotErrorCount((c) => c + 1)}
                      className={`max-w-full h-auto cursor-${tool === "form_fill" ? "text" : tool === "manual_type" ? "text" : tool === "final" ? "crosshair" : tool === "nav_only" ? "grab" : "pointer"} select-none`}
                      style={{ aspectRatio: `${viewport.width}/${viewport.height}` }}
                      data-testid="vr-preview-img"
                    />
                    {/* ── 2026-05: chrome-error / page-load failure overlay ──
                        User report: "Visual Recorder mein chrome-error://
                        chromewebdata/ dikh raha hai blank white page —
                        solve kar do". When backend reports `page_status
                        !== "ok"`, overlay a clear message + Reload button
                        instead of letting the operator stare at the blank
                        Chromium error placeholder. */}
                    {pageMeta.page_status && pageMeta.page_status !== "ok" && pageMeta.page_status !== "blank" && (
                      <div
                        className="absolute inset-0 bg-zinc-950/92 backdrop-blur-sm flex flex-col items-center justify-center text-center px-6 gap-3"
                        data-testid="vr-page-load-error"
                      >
                        <AlertCircle className="w-12 h-12 text-amber-400" />
                        <div className="text-amber-100 font-semibold">
                          Page failed to load
                        </div>
                        <div className="text-xs text-zinc-300 max-w-sm leading-relaxed">
                          {pageMeta.page_status_reason === "proxy_error" && "Chromium couldn't reach the page through the proxy — the gateway may be dead or your IP isn't whitelisted."}
                          {pageMeta.page_status_reason === "dns_failure" && "The URL's DNS could not be resolved — check spelling or try a different DNS gateway."}
                          {pageMeta.page_status_reason === "ssl_error" && "SSL/TLS handshake failed — the certificate may be invalid or the proxy is intercepting HTTPS."}
                          {pageMeta.page_status_reason === "connection_refused" && "The server refused the connection — it may be down or blocking your proxy IP."}
                          {pageMeta.page_status_reason === "timeout" && "Page took too long to respond — usually a slow / overloaded proxy."}
                          {pageMeta.page_status_reason === "no_internet" && "Chromium reports no internet — the proxy may be offline."}
                          {(!pageMeta.page_status_reason || pageMeta.page_status_reason === "unknown_load_error") && "Chromium landed on its error page (chrome-error://chromewebdata/). The target URL is unreachable through the current network/proxy."}
                        </div>
                        <div className="text-[11px] text-zinc-500 max-w-sm">
                          Common fixes: swap to a fresh proxy, check the offer URL opens in your normal browser, or click Reload to retry.
                        </div>
                        <div className="flex gap-2 mt-2">
                          <button
                            onClick={async () => {
                              try {
                                setShotErrorCount(0);
                                const r = await fetch(
                                  `${API_URL}/api/visual-recorder/${sessionId}/reload`,
                                  { method: "POST", headers: authH() }
                                );
                                const d = await r.json();
                                if (d.ok) {
                                  toast.success("Page reloaded successfully");
                                } else {
                                  toast.error(
                                    d.error || `Reload failed (${d.page_status_reason || "unknown"})`
                                  );
                                }
                                // Force a fresh state poll
                                if (typeof refreshState === "function") refreshState();
                                if (typeof refreshScreenshot === "function") refreshScreenshot();
                              } catch (e) {
                                toast.error(`Reload failed: ${e.message || e}`);
                              }
                            }}
                            className="px-4 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-medium transition-colors flex items-center gap-1.5"
                            data-testid="vr-reload-page-btn"
                          >
                            <RefreshCw className="w-3.5 h-3.5" />
                            Reload Page
                          </button>
                          <button
                            onClick={async () => {
                              try { await fetch(`${API_URL}/api/visual-recorder/${sessionId}`, { method: "DELETE", headers: authH() }); } catch {}
                              setSessionId(null);
                              setSessionState("starting");
                              setSessionError("");
                              setSetupStage("setup");
                            }}
                            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition-colors flex items-center gap-1.5"
                            data-testid="vr-back-to-setup-btn"
                          >
                            <ArrowLeft className="w-3.5 h-3.5" />
                            Change URL / Proxy
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="aspect-[412/914] w-full flex items-center justify-center text-zinc-500 text-sm">
                    <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading first frame…
                  </div>
                )}

                {/* ── Selector hover-preview overlay (2026-01) ────────
                    Drawn when the user hovers a suggestion in the
                    Edit-modal's "Find similar" panel. Position is
                    percent-based on viewport so it stays aligned even
                    if the screenshot is responsively scaled. */}
                {hoverPreview && hoverPreview.viewport?.width > 0 && (
                  <>
                    {/* Outer pulse ring */}
                    <div
                      className="absolute pointer-events-none animate-ping rounded-sm"
                      style={{
                        left: `${(hoverPreview.x / hoverPreview.viewport.width) * 100}%`,
                        top: `${(hoverPreview.y / hoverPreview.viewport.height) * 100}%`,
                        width: `${(hoverPreview.width / hoverPreview.viewport.width) * 100}%`,
                        height: `${(hoverPreview.height / hoverPreview.viewport.height) * 100}%`,
                        boxShadow: "0 0 0 3px rgba(59, 130, 246, 0.5)",
                        backgroundColor: "rgba(59, 130, 246, 0.10)",
                      }}
                    />
                    {/* Solid outline + label badge */}
                    <div
                      className="absolute pointer-events-none rounded-sm transition-all duration-150"
                      style={{
                        left: `${(hoverPreview.x / hoverPreview.viewport.width) * 100}%`,
                        top: `${(hoverPreview.y / hoverPreview.viewport.height) * 100}%`,
                        width: `${(hoverPreview.width / hoverPreview.viewport.width) * 100}%`,
                        height: `${(hoverPreview.height / hoverPreview.viewport.height) * 100}%`,
                        outline: "2px solid rgb(59, 130, 246)",
                        outlineOffset: "0px",
                        backgroundColor: "rgba(59, 130, 246, 0.12)",
                        boxShadow: "0 0 12px 2px rgba(59, 130, 246, 0.6)",
                      }}
                    >
                      <div
                        className="absolute -top-5 left-0 px-1.5 py-0.5 rounded-sm bg-blue-600 text-white text-[10px] font-mono whitespace-nowrap shadow-lg"
                        data-testid="vr-hover-preview-label"
                      >
                        {hoverPreview.selector}
                      </div>
                    </div>
                  </>
                )}

                {busy && (
                  <div className="absolute inset-0 bg-black/30 flex items-center justify-center">
                    <Loader2 className="w-8 h-8 animate-spin text-emerald-400" />
                  </div>
                )}
              </div>

              {/* Toolbar — 7-col grid with kbd hints */}
              <div className="mt-3 grid grid-cols-4 sm:grid-cols-7 gap-2">
                {TOOLS.map((t) => {
                  const Ic = t.icon;
                  const active = tool === t.id;
                  return (
                    <button
                      key={t.id}
                      onClick={() => {
                        // 2026-05: `close_browser` is an instant-action
                        // tool — there's nothing to "click on the page"
                        // for it. Fire the insert immediately and snap
                        // back to the default tool so the operator can
                        // keep recording without an extra step.
                        if (t.id === "close_browser") {
                          (async () => {
                            setBusy(true);
                            try {
                              const r = await fetch(`${API_URL}/api/visual-recorder/${sessionId}/close-browser-step`, {
                                method: "POST",
                                headers: authH(),
                              });
                              const d = await r.json();
                              if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
                              toast.success("🔌 Close-browser step inserted");
                              refreshState();
                            } catch (err) {
                              toast.error(`Insert close failed: ${err.message || err}`);
                            } finally {
                              setBusy(false);
                            }
                          })();
                          return;
                        }
                        // 2026-06: `branch` (If/Else) is also an instant-
                        // dialog tool — opens the branch builder modal
                        // instead of waiting for a screen click.
                        if (t.id === "branch") {
                          setBranchEditor({
                            mode: "create",
                            insertIndex: null,  // append at end
                            draft: {
                              name: "If / Else",
                              timeout_ms: 12000,
                              branches: [
                                { name: "Path A", condition: { type: "selector_visible", selector: "" }, steps: [] },
                                { name: "Path B", condition: { type: "selector_visible", selector: "" }, steps: [] },
                              ],
                              default_steps: [],
                            },
                          });
                          return;
                        }
                        setTool(t.id);
                        if (t.id !== "random" && t.id !== "random_click") {
                          setPendingRandom([]);
                          setDetectedClickables([]);
                          setSelectedRandomKeys(new Set());
                        } else {
                          // 2026-01: auto-detect all clickables on the
                          // current page the moment the user picks
                          // the Random Pick / Random Click tool. No need
                          // to click each button manually anymore.
                          detectClickables();
                        }
                        // 2026-01 v2.4.2 — auto-scan popups when Popup
                        // Work tool is selected, and clear popup state
                        // when switching to any OTHER tool.
                        if (t.id === "popup_work") {
                          detectPopupButtons();
                        } else {
                          setDetectedPopupItems([]);
                          setSelectedPopupKeys(new Set());
                          setPopupItemActions(new Map());
                          setPopupContainerCount(0);
                        }
                      }}
                      title={`${t.help} (key: ${t.key})`}
                      className={`relative flex flex-col items-center justify-center gap-1 py-2 px-1.5 rounded-lg text-xs font-medium transition-all ${
                        active
                          ? "bg-emerald-600 text-white shadow-md shadow-emerald-900/30"
                          : "bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
                      }`}
                      data-testid={`vr-tool-${t.id}`}
                    >
                      <Ic className="w-4 h-4" />
                      <span className="truncate w-full text-center">{t.label}</span>
                      <kbd
                        className={`absolute top-0.5 right-1 text-[9px] px-1 rounded font-mono ${
                          active ? "bg-emerald-800 text-emerald-200" : "bg-zinc-900 text-zinc-500"
                        }`}
                      >
                        {t.key}
                      </kbd>
                    </button>
                  );
                })}
              </div>

              {/* Sub-controls per mode */}
              {/* 2026-01 NEW: Random Pick checklist panel — auto-populated
                  by /detect-clickables when the user selects the "Random
                  Pick" tool. User ticks the candidates they want in the
                  random pool, then clicks "Build Random Step". */}
              {(tool === "random" || tool === "random_click") && (detectingClickables || detectedClickables.length > 0) && (
                <div
                  className="mt-3 p-3 rounded-lg bg-amber-950/40 border border-amber-700/40"
                  data-testid="vr-random-checklist-panel"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs text-amber-300 font-medium">
                      {detectingClickables ? (
                        <span className="flex items-center gap-1.5">
                          <Loader2 className="w-3 h-3 animate-spin" /> Detecting clickable elements on the page…
                        </span>
                      ) : (
                        <>{tool === "random_click" ? "Random Click" : "Random Pick"} — tick the buttons for the random pool ({selectedRandomKeys.size}/{detectedClickables.length} selected)</>
                      )}
                    </div>
                    <button
                      onClick={detectClickables}
                      disabled={detectingClickables}
                      title="Re-scan the current page"
                      className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-amber-200 border border-amber-800/40"
                      data-testid="vr-rescan-clickables-btn"
                    >
                      <RefreshCw className="w-3 h-3 inline-block mr-1" />
                      Re-scan
                    </button>
                  </div>
                  {!detectingClickables && detectedClickables.length > 0 && (
                    <>
                      <div className="max-h-56 overflow-y-auto pr-1 mb-2 space-y-1 rounded border border-amber-900/40 bg-zinc-950/40 p-1.5">
                        {detectedClickables.map((el, i) => {
                          const checked = selectedRandomKeys.has(i);
                          return (
                            <label
                              key={i}
                              className={`flex items-start gap-2 px-2 py-1 rounded cursor-pointer text-xs transition-colors ${
                                checked
                                  ? "bg-amber-900/40 text-amber-100"
                                  : "hover:bg-zinc-900 text-zinc-300"
                              }`}
                              data-testid={`vr-clickable-row-${i}`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => {
                                  setSelectedRandomKeys((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(i)) next.delete(i);
                                    else next.add(i);
                                    return next;
                                  });
                                }}
                                className="mt-0.5 accent-amber-500"
                                data-testid={`vr-clickable-check-${i}`}
                              />
                              <span className="flex-1 leading-snug">
                                <span className="font-medium">{el.text}</span>
                                <span className="ml-1.5 text-[9px] uppercase tracking-wide text-zinc-500">
                                  {el.tag}{el.role ? ` · role=${el.role}` : ""}
                                </span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          onClick={() => {
                            // Toggle all
                            if (selectedRandomKeys.size === detectedClickables.length) {
                              setSelectedRandomKeys(new Set());
                            } else {
                              setSelectedRandomKeys(new Set(detectedClickables.map((_, i) => i)));
                            }
                          }}
                          className="text-[10px] px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
                          data-testid="vr-toggle-all-btn"
                        >
                          {selectedRandomKeys.size === detectedClickables.length ? "Clear all" : "Select all"}
                        </button>
                        <button
                          onClick={buildRandomStep}
                          disabled={selectedRandomKeys.size < 2 || busy}
                          className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-xs font-medium"
                          data-testid="vr-build-random-checklist-btn"
                        >
                          Build Random Step ({selectedRandomKeys.size})
                        </button>
                        <span className="text-[10px] text-amber-200/70">
                          Tip: After building, switch to <b>Click</b> and pick any answer to move to the next page.
                        </span>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Legacy click-to-pool flow — still works for users who
                  prefer clicking each candidate on the live page. Only
                  shown when the new checklist isn't being used. */}
              {(tool === "random" || tool === "random_click") && detectedClickables.length === 0 && !detectingClickables && pendingRandom.length > 0 && (
                <div className="mt-3 p-3 rounded-lg bg-amber-950/40 border border-amber-700/40">
                  <div className="text-xs text-amber-300 mb-2 font-medium">
                    {tool === "random_click" ? "Random Click" : "Random Pick"} pool ({pendingRandom.length}): click more to add, then "Build Random Step"
                  </div>
                  <div className="flex flex-wrap gap-1 mb-2">
                    {pendingRandom.map((t, i) => (
                      <span key={i} className="px-2 py-0.5 rounded bg-zinc-900 text-amber-200 text-xs">{t.slice(0, 30)}</span>
                    ))}
                  </div>
                  <button
                    onClick={buildRandomStep}
                    disabled={pendingRandom.length < 2}
                    className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-xs font-medium"
                    data-testid="vr-build-random-btn"
                  >
                    Build Random Step ({pendingRandom.length})
                  </button>
                </div>
              )}

              {/* ── 2026-01 v2.4.2 — Popup Work checklist panel ──────
                   Auto-populated by /detect-popup-buttons the moment
                   the "Popup Work" tool is selected. Same pattern as
                   the Random checklist above.  Buttons are grouped by
                   popup_index so the customer can see WHICH popup each
                   candidate belongs to (useful when 2+ overlapping
                   modals are open). */}
              {tool === "popup_work" && (detectingPopups || detectedPopupItems.length > 0 || popupContainerCount > 0) && (
                <div
                  className="mt-3 p-3 rounded-lg bg-rose-950/40 border border-rose-700/40"
                  data-testid="vr-popup-checklist-panel"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs text-rose-300 font-medium">
                      {detectingPopups ? (
                        <span className="flex items-center gap-1.5">
                          <Loader2 className="w-3 h-3 animate-spin" /> Scanning page for popups…
                        </span>
                      ) : (
                        <>
                          🪟 Popup Work — top popup · {detectedPopupItems.length} item{detectedPopupItems.length === 1 ? "" : "s"} · tick items & pick action per item ({selectedPopupKeys.size}/{detectedPopupItems.length})
                        </>
                      )}
                    </div>
                    <button
                      onClick={detectPopupButtons}
                      disabled={detectingPopups}
                      title="Re-scan the page for popups now"
                      className="text-[10px] px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 disabled:opacity-40"
                      data-testid="vr-popup-rescan-btn"
                    >
                      <RefreshCw className={`w-3 h-3 inline mr-1 ${detectingPopups ? "animate-spin" : ""}`} />
                      Re-scan
                    </button>
                  </div>
                  {!detectingPopups && detectedPopupItems.length > 0 && (
                    <>
                      <div className="max-h-56 overflow-y-auto mb-2 flex flex-col gap-1">
                        {detectedPopupItems.map((el, i) => {
                          const checked = selectedPopupKeys.has(i);
                          const currentAction = popupItemActions.get(i) || defaultActionFor(el);
                          const kind = el.element_kind || 'generic';
                          return (
                            <label
                              key={i}
                              className={`flex items-center gap-2 px-2 py-1 rounded cursor-pointer text-xs ${
                                checked
                                  ? "bg-rose-800/50 text-rose-100 border border-rose-500/40"
                                  : "bg-zinc-900/60 text-zinc-300 hover:bg-zinc-800/60 border border-transparent"
                              }`}
                              data-testid={`vr-popup-item-${i}`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(e) => {
                                  const next = new Set(selectedPopupKeys);
                                  if (e.target.checked) next.add(i); else next.delete(i);
                                  setSelectedPopupKeys(next);
                                }}
                                className="accent-rose-500 shrink-0"
                                data-testid={`vr-popup-item-checkbox-${i}`}
                              />
                              <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-rose-900/50 text-rose-200 shrink-0">
                                #{(el.popup_index ?? 0) + 1}
                              </span>
                              <span className="flex-1 leading-snug min-w-0">
                                <span className="font-medium truncate block">{el.text}</span>
                                <span className="mt-0.5 text-[9px] uppercase tracking-wide text-zinc-500">
                                  {el.tag}
                                  {kind && kind !== 'generic' && kind !== 'button' && kind !== 'link' ? ` · ${kind}` : ''}
                                </span>
                              </span>
                              {/* v2.6.28 — per-item action selector so Form Fill /
                                  Dropdown / Check Box can be used INSIDE popups too. */}
                              <select
                                value={currentAction}
                                onClick={(ev) => ev.stopPropagation()}
                                onChange={(ev) => {
                                  ev.stopPropagation();
                                  const next = new Map(popupItemActions);
                                  next.set(i, ev.target.value);
                                  setPopupItemActions(next);
                                }}
                                className="text-[10px] px-1 py-0.5 rounded bg-zinc-800 text-rose-100 border border-rose-500/30 shrink-0"
                                data-testid={`vr-popup-item-action-${i}`}
                                title="Choose how this popup item should be recorded"
                              >
                                <option value="click">Click</option>
                                <option value="form_fill">Form Fill</option>
                                <option value="dropdown">Dropdown</option>
                                <option value="check">Check Box</option>
                              </select>
                            </label>
                          );
                        })}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          onClick={() => {
                            if (selectedPopupKeys.size === detectedPopupItems.length) {
                              setSelectedPopupKeys(new Set());
                            } else {
                              setSelectedPopupKeys(new Set(detectedPopupItems.map((_, i) => i)));
                            }
                          }}
                          className="text-[10px] px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
                          data-testid="vr-popup-toggle-all-btn"
                        >
                          {selectedPopupKeys.size === detectedPopupItems.length ? "Clear all" : "Select all"}
                        </button>
                        <button
                          onClick={addSelectedPopupClicks}
                          disabled={selectedPopupKeys.size < 1 || busy}
                          className="px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-xs font-medium"
                          data-testid="vr-popup-add-clicks-btn"
                        >
                          Add {selectedPopupKeys.size} popup item{selectedPopupKeys.size === 1 ? "" : "s"} as step{selectedPopupKeys.size === 1 ? "" : "s"}
                        </button>
                        <span className="text-[10px] text-rose-200/70">
                          Tip: Pick per-item action — Click / Form Fill / Dropdown / Check Box. Form-Fill items become <code>wait_for_selector</code> until you bind an Excel column. Dropdown picker opens for the last selected select.
                        </span>
                      </div>
                    </>
                  )}
                  {!detectingPopups && detectedPopupItems.length === 0 && popupContainerCount === 0 && (
                    <div className="text-[11px] text-rose-200/70">
                      No popup / modal / dialog is currently visible on the page. Trigger the popup on the live preview (e.g. click something that opens it) then hit <b>Re-scan</b>.
                    </div>
                  )}
                </div>
              )}

              {/* ── 2026-01 v2.4.2 — Scan tool active hint ─────────── */}
              {tool === "scan" && (
                <div
                  className="mt-3 p-3 rounded-lg bg-cyan-950/40 border border-cyan-700/40"
                  data-testid="vr-scan-hint-panel"
                >
                  <div className="text-xs text-cyan-200 leading-snug">
                    <b>🔎 Scan mode active.</b> Click any element on the live preview to reveal its
                    text, CSS selector and XPath. Nothing will be clicked or recorded — just
                    inspection. Copy the locators for use in RPA Studio, manual click steps or
                    Wait for selector / xpath.
                  </div>
                </div>
              )}

              {["wait_for_text_pick", "wait_for_selector_pick", "wait_for_xpath_pick", "extract_pick"].includes(tool) && (
                <div
                  className="mt-3 p-3 rounded-lg bg-emerald-950/40 border border-emerald-700/40"
                  data-testid="vr-wait-pick-hint-panel"
                >
                  <div className="text-xs text-emerald-200 leading-snug">
                    <b>🎯 Auto-detect wait mode.</b>{" "}
                    {tool === "wait_for_text_pick" && "Page par jis text ka wait chahiye us par click karein — text khud detect ho jayega."}
                    {tool === "wait_for_selector_pick" && "Element par click karein — CSS selector auto detect ho jayega."}
                    {tool === "wait_for_xpath_pick" && "Element par click karein — XPath auto detect ho jayega."}
                    {tool === "extract_pick" && "Element par click karein — selector detect hoga, phir variable name poochega."}
                    {" "}Esc se cancel.
                  </div>
                </div>
              )}


              {(tool === "option_pick" || tool === "sheet_pick" || tool === "gender_pick") && (
                <div
                  className="mt-3 p-3 rounded-lg bg-violet-950/40 border border-violet-700/40"
                  data-testid="vr-option-pick-hint-panel"
                >
                  <div className="text-xs text-violet-200 leading-snug">
                    <b>Option Pick active.</b> Pehle <b>Male</b> par click karein, phir <b>Female</b> —
                    ya koi bhi 2+ buttons pool mein add karein. Phir neeche Excel column bind karein
                    (e.g. <code className="text-zinc-300">{`{{gender}}`}</code>).
                    Sheet mein <b>M / F / male / female</b> sab auto-detect hoga.
                  </div>
                </div>
              )}

              {pendingOptionButtons.length > 0 && (
                <div
                  className="mt-3 p-3 rounded-lg bg-violet-950/50 border border-violet-600/40"
                  data-testid="vr-option-pick-bind-panel"
                >
                  <div className="text-xs text-violet-200 mb-2 font-medium">
                    Option pool ({pendingOptionButtons.length}/2+):
                    {" "}
                    {pendingOptionButtons.map((t) => (
                      <code key={t} className="text-zinc-200 mx-0.5">{t}</code>
                    ))}
                  </div>
                  {pendingOptionButtons.length < 2 ? (
                    <div className="text-[11px] text-violet-200/80 mb-2">
                      Abhi {2 - pendingOptionButtons.length} aur button add karein.
                    </div>
                  ) : (
                    <>
                      <div className="text-[11px] text-zinc-400 mb-2">
                        Excel column bind karein — replay har row ki value se sahi button click karega:
                      </div>
                      <div className="flex flex-wrap gap-1.5 mb-2">
                        {headers.length === 0 && (
                          <span className="text-xs text-zinc-500">Pehle Excel upload karein</span>
                        )}
                        {headers
                          .filter((h) => /gender|sex/i.test(h))
                          .concat(headers.filter((h) => !/gender|sex/i.test(h)))
                          .filter((h, i, arr) => arr.indexOf(h) === i)
                          .map((h) => (
                            <button
                              key={`op-${h}`}
                              onClick={() => submitOptionPick(h)}
                              disabled={pendingOptionButtons.length < 2 || busy}
                              className={`px-2 py-1 rounded text-xs border ${
                                /gender|sex/i.test(h)
                                  ? "bg-violet-600/50 hover:bg-violet-600 border-violet-400/50 text-violet-50"
                                  : "bg-violet-900/30 hover:bg-violet-800/50 border-violet-700/40 text-violet-100"
                              }`}
                              data-testid={`vr-option-pick-bind-${h}`}
                            >
                              {`{{${h}}}`}
                            </button>
                          ))}
                      </div>
                    </>
                  )}
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => setPendingOptionButtons([])}
                      className="px-2 py-1 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs"
                    >
                      Clear pool
                    </button>
                  </div>
                </div>
              )}

              {tool === "manual_type" && (
                <div
                  className="mt-3 p-3 rounded-lg bg-sky-950/40 border border-sky-700/40"
                  data-testid="vr-fix-type-hint-panel"
                >
                  <div className="text-xs text-sky-200 leading-snug">
                    <b>Fix Type active.</b> Galat value wale input par click karein —
                    sahi text likhein. Live page update hogi, JSON mein <b>koi step add nahi</b> hoga
                    (Move button jaisa).
                  </div>
                </div>
              )}
              {pendingFormFill && (
                <div className="mt-3 p-3 rounded-lg bg-blue-950/40 border border-blue-700/40">
                  <div className="text-xs text-blue-300 mb-2 font-medium">
                    Bind input <code className="text-zinc-300">{pendingFormFill.selector}</code> to:
                  </div>
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {headers.length === 0 && <span className="text-xs text-zinc-500">No Excel headers — use Plain value below</span>}
                    {headers.map((h) => (
                      <button
                        key={h}
                        onClick={() => submitFormFill(h, null)}
                        className="px-2 py-1 rounded bg-blue-600/40 hover:bg-blue-600 border border-blue-500/40 text-blue-100 text-xs"
                        data-testid={`vr-bind-${h}`}
                      >
                        {`{{${h}}}`}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2 mt-2">
                    <input
                      type="text"
                      placeholder="Or plain value"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") submitFormFill(null, e.target.value);
                      }}
                      className="flex-1 px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-zinc-100 placeholder-zinc-600 text-xs"
                      data-testid="vr-plain-value-input"
                    />
                    <button
                      onClick={() => setPendingFormFill(null)}
                      className="px-2 py-1 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {pendingDropdown && (
                <div
                  className="mt-3 p-3 rounded-lg bg-amber-950/30 border border-amber-700/40"
                  data-testid="vr-dropdown-bind-panel"
                >
                  <div className="text-xs text-amber-200 mb-1 font-medium flex items-center gap-1 flex-wrap">
                    <ChevronDown className="w-3.5 h-3.5" />
                    Bind dropdown <code className="text-zinc-300">{pendingDropdown.selector}</code>
                    {pendingDropdown.wrapper_kind && (
                      <span
                        data-testid="vr-dd-wrapper-badge"
                        className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/20 border border-blue-400/40 text-blue-200"
                        title={
                          pendingDropdown.is_hidden_select
                            ? "Native <select> is CSS-hidden behind this custom UI. Recorder will mark this step state=\"attached\" + prefer JS-set at replay so the visit doesn't 25s-timeout on visibility."
                            : "Custom dropdown UI detected — replay will use JS-first select."
                        }
                      >
                        {pendingDropdown.wrapper_kind === "generic-custom"
                          ? "Custom UI"
                          : pendingDropdown.wrapper_kind}
                        {pendingDropdown.is_hidden_select ? " · hidden <select>" : ""}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-zinc-400 mb-2">
                    {pendingDropdown.options.length} option{pendingDropdown.options.length === 1 ? "" : "s"} found —
                    pick a fixed one OR bind to an Excel column.
                    {pendingDropdownQueue.length > 1 && (
                      <span className="ml-1 text-amber-300">
                        ({pendingDropdownQueue.length - 1} more queued)
                      </span>
                    )}
                  </div>

                  {/* Excel column bindings (preferred for per-row values) */}
                  {headers.length > 0 && (
                    <>
                      <div className="text-[11px] text-zinc-500 mb-1 uppercase tracking-wide">
                        Bind to Excel column (match by visible label)
                      </div>
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {headers.map((h) => (
                          <button
                            key={`dd-h-${h}`}
                            onClick={() => submitDropdownBind({ header_name: h, match_by: "label" })}
                            className="px-2 py-1 rounded bg-amber-600/30 hover:bg-amber-600/60 border border-amber-500/40 text-amber-50 text-xs"
                            data-testid={`vr-dd-bind-${h}`}
                          >
                            {`{{${h}}}`}
                          </button>
                        ))}
                      </div>
                    </>
                  )}

                  <div className="text-[11px] text-zinc-500 mb-1 uppercase tracking-wide">
                    Or pick a fixed option (always selected)
                  </div>
                  <div className="max-h-44 overflow-y-auto rounded border border-zinc-800 bg-zinc-950/50 divide-y divide-zinc-800/60">
                    {pendingDropdown.options.map((o, idx) => {
                      const lbl = (o.label || o.value || "").trim() || `(option #${idx + 1})`;
                      const sub = o.value && o.value !== lbl ? ` · value="${o.value}"` : "";
                      return (
                        <button
                          key={`dd-opt-${idx}`}
                          onClick={() => submitDropdownBind({ value: o.label || o.value || "", match_by: "label" })}
                          className="w-full text-left px-2 py-1.5 text-xs text-zinc-200 hover:bg-amber-600/20 hover:text-amber-100 transition flex items-center justify-between"
                          data-testid={`vr-dd-opt-${idx}`}
                        >
                          <span className="truncate">{lbl}</span>
                          <span className="text-[10px] text-zinc-500 ml-2 truncate">{sub}</span>
                        </button>
                      );
                    })}
                  </div>

                  <div className="flex justify-end mt-2">
                    <button
                      onClick={() => setPendingDropdownQueue([])}
                      className="px-2 py-1 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs"
                      data-testid="vr-dd-cancel"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Auxiliary controls */}
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={() => addScroll("down")} title="Scroll down" className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs">
                  <ScrollText className="w-3.5 h-3.5" /> Scroll ↓
                </button>
                <button onClick={() => addScroll("up")} title="Scroll up" className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs">
                  <ScrollText className="w-3.5 h-3.5 rotate-180" /> Scroll ↑
                </button>
                <button onClick={addWaitLoad} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs">
                  <Clock className="w-3.5 h-3.5" /> Wait for Load
                </button>
                <label
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-zinc-300 text-xs cursor-pointer select-none"
                  title="When ON, each recorded click/fill/type automatically adds wait steps after it. When OFF, add waits manually."
                  data-testid="vr-auto-wait-toggle-label"
                >
                  <input
                    type="checkbox"
                    checked={autoInsertWaits}
                    onChange={(e) => setAutoInsertWaitsPref(e.target.checked)}
                    data-testid="vr-auto-wait-toggle"
                  />
                  Auto waits after steps
                </label>
                <label
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded border text-xs cursor-pointer select-none ${
                    stageMarkersOn
                      ? "bg-sky-950/40 border-sky-500/40 text-sky-200"
                      : "bg-zinc-900 border-zinc-800 text-zinc-300"
                  }`}
                  title="ON = stage groups with open-when detect (skip whole Form fill block if form never opens). OFF = classic linear steps."
                  data-testid="vr-stage-markers-toggle-label"
                >
                  <input
                    type="checkbox"
                    checked={stageMarkersOn}
                    onChange={(e) => setStageMarkersPref(e.target.checked)}
                    data-testid="vr-stage-markers-toggle"
                  />
                  Stage markers
                </label>
                {stageMarkersOn && (
                  <>
                    <button
                      type="button"
                      onClick={addNewStageMarker}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-sky-700/80 hover:bg-sky-600 text-white text-xs font-medium"
                      data-testid="vr-new-stage-btn"
                      title="Start a named stage group (Questions / Email / Form fill / Survey / Deals)"
                    >
                      + New Stage
                    </button>
                    {currentStageName ? (
                      <span className="text-[10px] text-sky-300/90 px-2 py-1 rounded bg-sky-950/30 border border-sky-800/40" data-testid="vr-current-stage">
                        Current: {currentStageName}
                      </span>
                    ) : (
                      <span className="text-[10px] text-zinc-500">Add a stage, then record steps inside it</span>
                    )}
                  </>
                )}
                <p className="w-full text-[10px] text-amber-600/90 -mt-1">
                  Optional auto-waits can mask missing selectors — prefer explicit wait_for_selector when debugging failures.
                </p>
                {stageMarkersOn && (
                  <p className="w-full text-[10px] text-sky-500/90 -mt-1">
                    Stage markers: Form fill pe open-when set karo — form na khule to poori stage ek shot mein skip (har step timeout nahi).
                  </p>
                )}
                <label
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-zinc-300 text-xs cursor-pointer select-none"
                  title="When ON, Wait for text/selector/xpath buttons let you click the page to auto-fill — no manual scan/copy."
                  data-testid="vr-wait-auto-detect-toggle-label"
                >
                  <input
                    type="checkbox"
                    checked={waitAutoDetect}
                    onChange={(e) => setWaitAutoDetectPref(e.target.checked)}
                    data-testid="vr-wait-auto-detect-toggle"
                  />
                  Auto-detect waits (click page)
                </label>
                <div className="inline-flex items-center gap-1">
                  <span className="text-[10px] text-zinc-500">Pick timeout</span>
                  <input
                    type="number"
                    value={waitPickTimeoutMs}
                    onChange={(e) => setWaitPickTimeoutMs(e.target.value)}
                    className="w-16 px-1.5 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-100 text-xs"
                    data-testid="vr-wait-pick-timeout"
                  />
                  <span className="text-[10px] text-zinc-500">ms</span>
                </div>
                <button
                  onClick={addAutoContinueSurvey}
                  disabled={sessionState !== "ready" || busy}
                  title="Append RUT auto_continue_survey — drives Yes/No survey + deal cards after your form (deal-wall offers)"
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-violet-900/40 hover:bg-violet-800/50 border border-violet-600/40 text-violet-200 text-xs disabled:opacity-40"
                  data-testid="vr-auto-continue-survey-btn"
                >
                  🔄 Auto-continue survey
                </button>
                <div className="inline-flex items-center gap-1">
                  <input
                    type="number"
                    value={waitMs}
                    onChange={(e) => setWaitMs(e.target.value)}
                    className="w-16 px-1.5 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-100 text-xs"
                    data-testid="vr-wait-ms"
                  />
                  <button onClick={addWait} className="inline-flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs" data-testid="vr-add-wait">
                    + Wait ms
                  </button>
                </div>
                <div className="inline-flex items-center gap-1 flex-1 min-w-[200px]">
                  <input
                    type="text"
                    value={navUrl}
                    onChange={(e) => setNavUrl(e.target.value)}
                    placeholder="Navigate to URL"
                    className="flex-1 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-100 placeholder-zinc-600 text-xs"
                    data-testid="vr-nav-input"
                  />
                  <button onClick={navigateTo} className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs" data-testid="vr-nav-go">
                    Go
                  </button>
                </div>

                {/* Keyboard quick-keys + wait-for-selector — power-user actions */}
                <div className="inline-flex items-center gap-1 ml-auto" data-testid="vr-key-row">
                  <span className="text-[10px] text-zinc-500 mr-1">Press:</span>
                  {["Enter","Tab","Escape","Backspace","ArrowDown"].map((k) => (
                    <button
                      key={k}
                      onClick={() => pressKey(k)}
                      disabled={sessionState !== "ready"}
                      title={`Press ${k} key`}
                      className="px-2 py-1 rounded bg-zinc-800 hover:bg-emerald-700/40 border border-zinc-700 hover:border-emerald-500/40 text-zinc-300 text-[10px] font-mono disabled:opacity-40"
                      data-testid={`vr-press-${k}`}
                    >
                      {k === "Backspace" ? "⌫" : k === "ArrowDown" ? "↓" : k}
                    </button>
                  ))}
                  <button
                    onClick={waitForSelectorAction}
                    disabled={sessionState !== "ready"}
                    title="Wait until a CSS selector becomes visible"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-sky-700/40 border border-zinc-700 hover:border-sky-500/40 text-zinc-300 text-[10px] disabled:opacity-40 ml-1"
                    data-testid="vr-wait-selector-btn"
                  >
                    ⏳ Wait for selector
                  </button>
                  {/* 2026-01 v2.4.2 — sibling of Wait for selector.
                       Uses Playwright's `xpath=` prefix so RUT replay
                       hits the same wait_for_selector engine — no
                       runtime branching, full backward compat. */}
                  <button
                    onClick={waitForXpathAction}
                    disabled={sessionState !== "ready"}
                    title="Wait until an XPath expression matches a visible element (fallback / alternative when a CSS selector isn't stable)"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-indigo-700/40 border border-zinc-700 hover:border-indigo-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-wait-xpath-btn"
                  >
                    🎯 Wait for xpath
                  </button>
                  <button
                    onClick={addWaitForText}
                    disabled={sessionState !== "ready"}
                    title="Wait until specific text appears on the page (e.g. 'Thank you')"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-emerald-700/40 border border-zinc-700 hover:border-emerald-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-wait-text-btn"
                  >
                    💬 Wait for text
                  </button>
                  <button
                    onClick={addWaitForUrl}
                    disabled={sessionState !== "ready"}
                    title="Wait until URL contains a pattern (e.g. '/thank-you')"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-cyan-700/40 border border-zinc-700 hover:border-cyan-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-wait-url-btn"
                  >
                    🔗 Wait for URL
                  </button>
                  <button
                    onClick={addExtract}
                    disabled={sessionState !== "ready"}
                    title="Extract text/attribute into a variable usable later with {{var_name}}"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-purple-700/40 border border-zinc-700 hover:border-purple-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-extract-btn"
                  >
                    📋 Extract var
                  </button>
                  <button
                    onClick={addDismissPopups}
                    disabled={sessionState !== "ready"}
                    title="Auto-dismiss cookie/GDPR banners and popups"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-amber-700/40 border border-zinc-700 hover:border-amber-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-dismiss-popups-btn"
                  >
                    🍪 Dismiss popups
                  </button>
                  {/* ── 2026-01 Phase 1: any-offer coverage buttons ── */}
                  <button
                    onClick={addWaitNetworkIdle}
                    disabled={sessionState !== "ready"}
                    title="Wait until all XHRs/fetches finish — essential for React/Vue/Next offer pages"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-sky-700/40 border border-zinc-700 hover:border-sky-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-wait-netidle-btn"
                  >
                    🌐 Wait net-idle
                  </button>
                  <button
                    onClick={addCaptchaPause}
                    disabled
                    title="Coming soon — use RUT Skip Captcha for headless runs. CAPTCHA needs manual solve in desktop app."
                    className="px-2 py-1 rounded bg-zinc-800/50 border border-zinc-700 text-zinc-500 text-[10px] cursor-not-allowed opacity-60"
                    data-testid="vr-captcha-pause-btn"
                  >
                    🛡️ Captcha pause (soon)
                  </button>
                  <button
                    onClick={addFileUpload}
                    disabled={sessionState !== "ready"}
                    title="Upload a file at job run time (KYC docs, profile pic, crypto exchange ID)"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-indigo-700/40 border border-zinc-700 hover:border-indigo-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-file-upload-btn"
                  >
                    📎 File upload
                  </button>
                  <button
                    onClick={addOtpWait}
                    disabled={sessionState !== "ready"}
                    title="Wait for OTP / verification code (URL or page text), then auto-fill"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-fuchsia-700/40 border border-zinc-700 hover:border-fuchsia-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-otp-wait-btn"
                  >
                    🔢 OTP wait
                  </button>
                  <button
                    onClick={addHumanPause}
                    disabled={sessionState !== "ready"}
                    title="Pause for human action (wallet connect, push-2FA, video watch checkpoint)"
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-orange-700/40 border border-zinc-700 hover:border-orange-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                    data-testid="vr-human-pause-btn"
                  >
                    ⏸ Pause human
                  </button>
                  {/* ── 2026-01 Phase 2: "More" dropdown for advanced step types ── */}
                  <div className="relative inline-block">
                    <button
                      onClick={() => setShowMoreMenu((v) => !v)}
                      disabled={sessionState !== "ready"}
                      title="Advanced step types: iframe, shadow DOM, drag-drop, conditional skip, cookies/storage, zoom, browser back/forward, right-click, clipboard, headless probe"
                      className="px-2 py-1 rounded bg-zinc-800 hover:bg-teal-700/40 border border-zinc-700 hover:border-teal-500/40 text-zinc-300 text-[10px] disabled:opacity-40"
                      data-testid="vr-more-steps-btn"
                    >
                      ⋯ More ▾
                    </button>
                    {showMoreMenu && (
                      <div
                        className="absolute right-0 mt-1 z-50 w-64 max-h-[420px] overflow-y-auto bg-zinc-950 border border-zinc-700 rounded-lg shadow-2xl p-1.5 text-[11px]"
                        onMouseLeave={() => setShowMoreMenu(false)}
                        data-testid="vr-more-menu"
                      >
                        <div className="px-2 py-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Embedded Content</div>
                        <button onClick={() => { setShowMoreMenu(false); addIframeClick(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          🖼️ iframe click
                        </button>
                        <button onClick={() => { setShowMoreMenu(false); addShadowClick(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          🌐 Shadow DOM click
                        </button>

                        <div className="px-2 py-1 mt-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Interactions</div>
                        <button onClick={() => { setShowMoreMenu(false); addDragDrop(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          🎚️ Drag-and-drop (slider CAPTCHA)
                        </button>
                        <button onClick={() => { setShowMoreMenu(false); addRightClick(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          🖱️ Right-click
                        </button>
                        <button onClick={() => { setShowMoreMenu(false); setBrowserZoom(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          🔍 Browser zoom
                        </button>

                        <div className="px-2 py-1 mt-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Navigation</div>
                        <button onClick={() => { setShowMoreMenu(false); addBrowserBack(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          ← Browser back
                        </button>
                        <button onClick={() => { setShowMoreMenu(false); addBrowserForward(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          → Browser forward
                        </button>

                        <div className="px-2 py-1 mt-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Clipboard</div>
                        <button onClick={() => { setShowMoreMenu(false); addClipboardWrite(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          📋 Write to clipboard
                        </button>
                        <button onClick={() => { setShowMoreMenu(false); addClipboardRead(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          📋 Read clipboard → variable
                        </button>

                        <div className="px-2 py-1 mt-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Flow Control</div>
                        <button onClick={() => { setShowMoreMenu(false); addCondSkip(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          ⏭ Conditional skip
                        </button>

                        <div className="px-2 py-1 mt-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Session</div>
                        <button onClick={() => { setShowMoreMenu(false); addSaveStorage(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          💾 Save cookies + storage
                        </button>
                        <button onClick={() => { setShowMoreMenu(false); addRestoreStorage(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-teal-700/30 text-zinc-200">
                          📂 Restore cookies + storage
                        </button>

                        <div className="px-2 py-1 mt-1 text-[9px] uppercase tracking-wider text-zinc-500 font-semibold">Diagnostics</div>
                        <button onClick={() => { setShowMoreMenu(false); runHeadlessProbe(); }}
                          className="w-full text-left px-2 py-1.5 rounded hover:bg-emerald-700/40 text-emerald-200 font-medium"
                          data-testid="vr-headless-probe-btn">
                          🛡️ Anti-bot probe (0-100 score)
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Steps panel */}
            <div className="lg:col-span-1 p-3 rounded-xl bg-zinc-900/60 border border-zinc-800 flex flex-col" style={{ maxHeight: "85vh" }}>
              <div className="flex items-center justify-between mb-2 px-1">
                <h3 className="text-sm font-medium flex items-center gap-1.5">
                  <ScrollText className="w-4 h-4 text-emerald-400" />
                  Recorded Steps
                  <span className="px-1.5 py-0.5 rounded bg-emerald-700/30 border border-emerald-500/30 text-emerald-200 text-[10px] font-mono">
                    {steps.length}
                  </span>
                </h3>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => { setAiRefineOpen(o => !o); setAiRefineError(""); }}
                    title="AI ko bol kar steps mein changes karwayen — surveys randomize, fix selectors, remove unnecessary steps, etc."
                    disabled={steps.length === 0}
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-purple-800/40 hover:bg-purple-600/60 border border-purple-500/30 hover:border-purple-400/60 text-purple-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    data-testid="vr-ai-refine-btn"
                  >
                    <Sparkles className="w-3 h-3" /> Refine with AI
                  </button>
                  <button
                    onClick={runLint}
                    title="Pre-flight lint — checks for missing selectors, invalid actions, hard-waits >30s, etc."
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-zinc-800 hover:bg-emerald-700/40 border border-zinc-700 hover:border-emerald-500/40 text-zinc-300 hover:text-emerald-200 transition-colors"
                    data-testid="vr-lint-btn"
                  >
                    ✓ Lint
                  </button>
                  <button
                    onClick={openAliasesPanel}
                    title="View self-healing selector aliases (saved automatically when you fix wrong selectors)"
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-zinc-800 hover:bg-fuchsia-700/40 border border-zinc-700 hover:border-fuchsia-500/40 text-zinc-300 hover:text-fuchsia-200 transition-colors"
                    data-testid="vr-aliases-btn"
                  >
                    <Brain className="w-3 h-3" /> Aliases
                  </button>
                  <button
                    onClick={openManualAddStep}
                    title="Add a step manually (CSS / XPath selector + action)"
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-zinc-800 hover:bg-sky-700/40 border border-zinc-700 hover:border-sky-500/40 text-zinc-300 hover:text-sky-200 transition-colors"
                    data-testid="vr-add-manual-step-btn"
                  >
                    <ListPlus className="w-3 h-3" /> Add Step
                  </button>
                  {steps.length > 0 && (
                    <button
                      onClick={undoLastStep}
                      title="Undo last step (Ctrl+Z)"
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-zinc-800 hover:bg-amber-700/40 border border-zinc-700 hover:border-amber-500/40 text-zinc-300 hover:text-amber-200 transition-colors"
                      data-testid="vr-undo-btn"
                    >
                      <Undo2 className="w-3 h-3" /> Undo
                    </button>
                  )}
                </div>
              </div>

              {/* 2026-01: Lint Result Panel */}
              {showLintPanel && lintResult && (
                <div
                  className={`mb-2 p-2 rounded border text-[11px] ${
                    lintResult.ok
                      ? 'bg-emerald-950/30 border-emerald-500/30'
                      : 'bg-rose-950/30 border-rose-500/30'
                  }`}
                  data-testid="vr-lint-panel"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className={`font-medium ${lintResult.ok ? 'text-emerald-300' : 'text-rose-300'}`}>
                      {lintResult.ok ? '✓ Lint passed' : '⚠ Lint found issues'}
                      <span className="text-zinc-500 ml-2">
                        ({lintResult.summary?.errors || 0} errors,
                        {' '}{lintResult.summary?.warnings || 0} warnings,
                        {' '}{lintResult.summary?.infos || 0} info)
                      </span>
                    </span>
                    <button
                      onClick={() => setShowLintPanel(false)}
                      className="text-zinc-500 hover:text-zinc-300 px-1"
                      data-testid="vr-lint-close"
                    >×</button>
                  </div>
                  {(lintResult.issues || []).length > 0 && (
                    <ul className="space-y-0.5 max-h-32 overflow-y-auto">
                      {lintResult.issues.map((issue, idx) => (
                        <li
                          key={idx}
                          className={`flex items-start gap-1 ${
                            issue.level === 'error'
                              ? 'text-rose-300'
                              : issue.level === 'warn'
                              ? 'text-amber-300'
                              : 'text-zinc-400'
                          }`}
                          data-testid={`vr-lint-issue-${idx}`}
                        >
                          <span className="flex-shrink-0 font-mono">
                            {issue.level === 'error' ? '✗' : issue.level === 'warn' ? '⚠' : 'ℹ'}
                          </span>
                          <span>{issue.message}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {/* 2026-06 — AI Refine panel: opens when user clicks the
                  "Refine with AI" button in the header. Lets them give
                  the AI a natural-language change request. */}
              {aiRefineOpen && (
                <div className="mb-2 p-2.5 rounded-lg bg-purple-950/30 border border-purple-700/40" data-testid="vr-ai-refine-panel">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-semibold text-purple-200 flex items-center gap-1">
                      <Sparkles className="w-3 h-3" /> Refine with AI
                    </span>
                    <div className="flex items-center gap-1">
                      {aiRefinePrevSteps && (
                        <button
                          onClick={handleAiRefineUndo}
                          disabled={aiRefineBusy}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-200 border border-zinc-600"
                          data-testid="vr-ai-refine-undo"
                          title="Undo the last AI refine and restore the previous step-list"
                        >
                          ⤺ Undo
                        </button>
                      )}
                      <button
                        onClick={() => setAiRefineOpen(false)}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300"
                        data-testid="vr-ai-refine-close"
                      >✕</button>
                    </div>
                  </div>
                  <textarea
                    value={aiRefineInstruction}
                    onChange={(e) => setAiRefineInstruction(e.target.value)}
                    rows={3}
                    disabled={aiRefineBusy}
                    placeholder="Example: 'Survey k jawab har visit pe random karen', 'First name selector galat hai, input[id=fname] use karen', 'Step 5 par 5 second wait add karen', 'Final 3 deal clicks ke beech 4 second ka pause dalein'..."
                    className="w-full text-xs rounded-md border border-purple-800/40 bg-zinc-950 px-2.5 py-1.5 text-zinc-100 placeholder:text-zinc-500 focus:border-purple-500 focus:outline-none resize-none"
                    data-testid="vr-ai-refine-input"
                  />
                  {aiRefineError && (
                    <div className="mt-1.5 text-[11px] text-rose-300 bg-rose-950/40 rounded px-2 py-1 border border-rose-700/40">
                      {aiRefineError}
                    </div>
                  )}
                  <div className="mt-1.5 flex items-center justify-between">
                    <span className="text-[10px] text-zinc-500">
                      Current steps: {steps.length}{aiRefinePrevSteps ? ` (was ${aiRefinePrevSteps.length})` : ""}
                    </span>
                    <button
                      onClick={handleAiRefine}
                      disabled={aiRefineBusy || !aiRefineInstruction.trim()}
                      className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-purple-600 hover:bg-purple-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white"
                      data-testid="vr-ai-refine-submit"
                    >
                      {aiRefineBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                      {aiRefineBusy ? "Refining…" : "Apply"}
                    </button>
                  </div>
                </div>
              )}

              <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
                {steps.length === 0 && (
                  <div className="text-zinc-600 text-xs text-center py-4">No steps yet — click on the preview to record</div>
                )}
                {steps.map((s, i) => {
                  // 2026-01: Step icon + color coding for quick visual scan
                  const stepIconMap = {
                    click: { icon: "👆", color: "text-emerald-400", bg: "bg-emerald-700/30 border-emerald-500/30" },
                    fill: { icon: "✏️", color: "text-sky-400", bg: "bg-sky-700/30 border-sky-500/30" },
                    type: { icon: "⌨️", color: "text-sky-400", bg: "bg-sky-700/30 border-sky-500/30" },
                    select: { icon: "▾", color: "text-purple-400", bg: "bg-purple-700/30 border-purple-500/30" },
                    check: { icon: "☑", color: "text-emerald-400", bg: "bg-emerald-700/30 border-emerald-500/30" },
                    uncheck: { icon: "☐", color: "text-zinc-400", bg: "bg-zinc-700/30 border-zinc-500/30" },
                    wait: { icon: "⏱", color: "text-zinc-400", bg: "bg-zinc-700/30 border-zinc-500/30" },
                    wait_for_selector: { icon: "⏳", color: "text-sky-400", bg: "bg-sky-700/30 border-sky-500/30" },
                    wait_for_load: { icon: "⏳", color: "text-sky-400", bg: "bg-sky-700/30 border-sky-500/30" },
                    wait_for_navigation: { icon: "⏳", color: "text-sky-400", bg: "bg-sky-700/30 border-sky-500/30" },
                    wait_for_networkidle: { icon: "⏳", color: "text-sky-400", bg: "bg-sky-700/30 border-sky-500/30" },
                    wait_for_text: { icon: "💬", color: "text-emerald-400", bg: "bg-emerald-700/30 border-emerald-500/30" },
                    wait_for_url: { icon: "🔗", color: "text-cyan-400", bg: "bg-cyan-700/30 border-cyan-500/30" },
                    extract: { icon: "📋", color: "text-purple-400", bg: "bg-purple-700/30 border-purple-500/30" },
                    dismiss_popups: { icon: "🍪", color: "text-amber-400", bg: "bg-amber-700/30 border-amber-500/30" },
                    screenshot: { icon: "📷", color: "text-amber-400", bg: "bg-amber-700/30 border-amber-500/30" },
                    scroll: { icon: "⇅", color: "text-zinc-400", bg: "bg-zinc-700/30 border-zinc-500/30" },
                    navigate: { icon: "🌐", color: "text-cyan-400", bg: "bg-cyan-700/30 border-cyan-500/30" },
                    goto: { icon: "🌐", color: "text-cyan-400", bg: "bg-cyan-700/30 border-cyan-500/30" },
                    press: { icon: "🔘", color: "text-zinc-400", bg: "bg-zinc-700/30 border-zinc-500/30" },
                    hover: { icon: "🖱", color: "text-zinc-400", bg: "bg-zinc-700/30 border-zinc-500/30" },
                    evaluate: { icon: "⚡", color: "text-yellow-400", bg: "bg-yellow-700/30 border-yellow-500/30" },
                    auto_continue: { icon: "🔄", color: "text-violet-400", bg: "bg-violet-700/30 border-violet-500/30" },
                    auto_continue_survey: { icon: "🔄", color: "text-violet-400", bg: "bg-violet-700/30 border-violet-500/30" },
                    branch: { icon: "🔀", color: "text-fuchsia-400", bg: "bg-fuchsia-700/30 border-fuchsia-500/30" },
                    stage: { icon: "📦", color: "text-sky-300", bg: "bg-sky-800/40 border-sky-500/40" },
                    stage_markers: { icon: "🏷", color: "text-sky-400", bg: "bg-sky-900/40 border-sky-600/30" },
                    switch_tab: { icon: "↔", color: "text-blue-400", bg: "bg-blue-700/30 border-blue-500/30" },
                    close_tab: { icon: "✕", color: "text-rose-400", bg: "bg-rose-700/30 border-rose-500/30" },
                  };
                  const sm = stepIconMap[s.action] || { icon: "•", color: "text-zinc-400", bg: "bg-zinc-700/30 border-zinc-500/30" };
                  const isDragSrc = dragSrc === i;
                  const isDragOver = dragOver === i;
                  const isStageHeader = (s.action || "").toLowerCase() === "stage";
                  return (
                  <React.Fragment key={i}>
                    {isStageHeader && (
                      <div
                        className="mt-2 mb-0.5 px-2 py-1 rounded-md bg-sky-950/50 border border-sky-600/40 text-[11px] text-sky-200 font-semibold tracking-wide"
                        data-testid={`vr-stage-header-${i}`}
                      >
                        ── {s.name || s.stage || "Stage"} ──
                        {s.open_when?.selector || s.open_when?.text || s.open_when?.value ? (
                          <span className="ml-2 font-normal text-sky-400/80 text-[10px]">
                            open when: {s.open_when.selector || s.open_when.text || s.open_when.value}
                          </span>
                        ) : (
                          <span className="ml-2 font-normal text-zinc-500 text-[10px]">always run</span>
                        )}
                      </div>
                    )}
                    {/* 2026-06 — Insert-between-steps button now
                        ALWAYS visible (was opacity-0 until hover, so
                        most operators never discovered it). Customer
                        ask: "kis b step k bad wo step add krne ki
                        option ho". Visible as a thin separator with a
                        centered + icon — solid colour on hover. */}
                    <div
                      className="relative h-3 group/insert"
                      data-testid={`vr-step-insert-zone-${i}`}
                    >
                      <button
                        onClick={() => insertStepAt(i)}
                        title={`Insert a new step BEFORE step #${i + 1}`}
                        className="absolute left-1/2 -translate-x-1/2 top-0 px-2 py-0.5 rounded-full bg-zinc-800 border border-emerald-700/50 hover:bg-emerald-600 hover:border-emerald-400 text-emerald-400 hover:text-white text-[9px] font-bold transition-colors z-10 leading-none shadow"
                        data-testid={`vr-step-insert-before-${i}`}
                      >
                        + insert step here
                      </button>
                    </div>
                  <div
                    className={`flex items-start gap-1 p-2 rounded bg-zinc-950 border text-xs hover:border-zinc-700 transition-all group ${
                      isDragSrc ? 'opacity-40 border-emerald-500' :
                      isDragOver ? 'border-emerald-500 bg-emerald-950/30' :
                      'border-zinc-800'
                    }`}
                    draggable
                    onDragStart={(e) => {
                      setDragSrc(i);
                      try { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); } catch {}
                    }}
                    onDragEnd={() => { setDragSrc(null); setDragOver(null); }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      try { e.dataTransfer.dropEffect = "move"; } catch {}
                      if (dragOver !== i) setDragOver(i);
                    }}
                    onDragLeave={(e) => {
                      // Only clear if leaving the entire element (not entering a child)
                      if (e.currentTarget.contains(e.relatedTarget)) return;
                      if (dragOver === i) setDragOver(null);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      let src = dragSrc;
                      try {
                        const dt = parseInt(e.dataTransfer.getData("text/plain"), 10);
                        if (!Number.isNaN(dt)) src = dt;
                      } catch {}
                      setDragOver(null);
                      setDragSrc(null);
                      if (src !== null && src !== i) {
                        moveStepTo(src, i);
                      }
                    }}
                    data-testid={`vr-step-${i}`}
                  >
                    <span
                      className="text-zinc-600 hover:text-zinc-300 cursor-grab active:cursor-grabbing select-none pt-0.5 text-[10px]"
                      title="Drag to reorder"
                      data-testid={`vr-step-drag-${i}`}
                    >⋮⋮</span>
                    <span className="text-emerald-400 font-mono pt-0.5 text-[10px]">#{i + 1}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded border ${sm.bg} ${sm.color} text-[10px] font-medium flex-shrink-0`}
                      title={s.action}
                    >
                      {sm.icon}
                    </span>
                    <div className="flex-1 min-w-0">
                      {/* Inline-editable name (click to edit). Default is
                          the friendly auto-label from getStepDisplayName
                          (e.g. "Click: Next button" / "Dropdown → {{state}}")
                          instead of the bare action verb. */}
                      <input
                        type="text"
                        defaultValue={s.name || getStepDisplayName(s)}
                        onBlur={(e) => {
                          const newName = (e.target.value || "").trim();
                          const autoName = getStepDisplayName(s);
                          // Only persist if user actually changed it AWAY
                          // from both the existing name and the auto-label.
                          if (newName && newName !== (s.name || autoName)) renameStep(i, newName);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") e.target.blur();
                          if (e.key === "Escape") { e.target.value = s.name || getStepDisplayName(s); e.target.blur(); }
                        }}
                        className="w-full bg-transparent border-0 border-b border-transparent hover:border-zinc-700 focus:border-emerald-500 focus:outline-none text-zinc-300 font-medium px-0 py-0 text-xs"
                        title={`Rename step (action: ${s.action})`}
                        data-testid={`vr-step-name-${i}`}
                      />
                      <div className="text-zinc-500 truncate">
                        {s.selector && <span>sel: <code className="text-zinc-400">{s.selector.slice(0, 28)}</code></span>}
                        {s.xpath && <span className="ml-1">xp: <code className="text-sky-400/80">{s.xpath.slice(0, 24)}</code></span>}
                        {s.value && <span> → {String(s.value).slice(0, 30)}</span>}
                        {s.ms && <span>{s.ms}ms</span>}
                        {s.timeout && !s.ms && <span>tout: {s.timeout}</span>}
                        {s.key && <span>key: <code className="text-zinc-400">{s.key}</code></span>}
                        {s.script && !s.name && <span title={s.script}>{s.script.slice(0, 50)}…</span>}
                        {s.action === "branch" && Array.isArray(s.branches) && (
                          <span className="text-fuchsia-300">
                            {s.branches.length} branch{s.branches.length === 1 ? "" : "es"}
                            {Array.isArray(s.default_steps) && s.default_steps.length > 0 ? " + default" : ""}
                            {" — "}
                            {s.branches
                              .map((b, _i) =>
                                (b?.name || `branch[${_i}]`) +
                                (Array.isArray(b?.steps) ? ` (${b.steps.length})` : "")
                              )
                              .join(" | ")
                              .slice(0, 80)}
                          </span>
                        )}
                      </div>
                    </div>
                    {/* Step actions — visible on hover */}
                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => moveStep(i, "up")}
                        disabled={i === 0}
                        title="Move up"
                        className="p-0.5 text-zinc-600 hover:text-emerald-400 disabled:opacity-30 disabled:cursor-not-allowed"
                        data-testid={`vr-step-up-${i}`}
                      >▲</button>
                      <button
                        onClick={() => moveStep(i, "down")}
                        disabled={i === steps.length - 1}
                        title="Move down"
                        className="p-0.5 text-zinc-600 hover:text-emerald-400 disabled:opacity-30 disabled:cursor-not-allowed"
                        data-testid={`vr-step-down-${i}`}
                      >▼</button>
                      <button
                        onClick={() => runLiveTest({ startIndex: i })}
                        title={`Test from this step onwards (skips previous ${i} steps, uses current page state)`}
                        disabled={i === 0 || liveTesting || busy}
                        className="p-0.5 text-zinc-600 hover:text-fuchsia-400 disabled:opacity-30 disabled:cursor-not-allowed text-[10px]"
                        data-testid={`vr-step-test-from-${i}`}
                      >⏵</button>
                      <button
                        onClick={() => duplicateStep(i)}
                        title="Duplicate"
                        className="p-0.5 text-zinc-600 hover:text-sky-400 text-[10px]"
                        data-testid={`vr-step-dup-${i}`}
                      >⎘</button>
                      <button
                        onClick={() => openEditStep(i)}
                        title="Edit step (selector, value, timeout, etc.)"
                        className="p-0.5 text-zinc-600 hover:text-amber-400"
                        data-testid={`vr-step-edit-${i}`}
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => deleteStep(i)}
                        title="Delete"
                        className="p-0.5 text-zinc-600 hover:text-rose-400"
                        data-testid={`vr-step-del-${i}`}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                  </React.Fragment>
                  );
                })}
                {/* 2026-06 — Final "insert at end" button (ALWAYS visible — same UX as in-between insert) */}
                {steps.length > 0 && (
                  <div className="relative h-4 mt-1 group/insert" data-testid="vr-step-insert-zone-end">
                    <button
                      onClick={() => insertStepAt(steps.length)}
                      title="Insert a new step at the END"
                      className="absolute left-1/2 -translate-x-1/2 top-0 px-2.5 py-1 rounded-full bg-zinc-800 border border-emerald-700/50 hover:bg-emerald-600 hover:border-emerald-400 text-emerald-400 hover:text-white text-[10px] font-bold transition-colors z-10 leading-none shadow"
                      data-testid="vr-step-insert-end"
                    >
                      + insert step at end
                    </button>
                  </div>
                )}
              </div>

              {/* Action buttons */}
              <div className="mt-3 pt-3 border-t border-zinc-800 space-y-2">
                <div className="flex items-center gap-2 text-[10px] text-zinc-500">
                  <label className="inline-flex items-center gap-1 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={liveTestRutParity}
                      onChange={(e) => setLiveTestRutParity(e.target.checked)}
                      data-testid="vr-live-test-rut-parity"
                    />
                    Test like RUT (self-heal ON, captcha NOT skipped, strict steps)
                  </label>
                </div>
                {!liveTestRutParity && (
                  <p className="text-[10px] text-amber-600/90" data-testid="vr-live-test-lenient-warn">
                    Live Test uses lenient defaults (skip missing steps, skip captcha) — enable “Test like RUT” before Finalize.
                  </p>
                )}
                <button
                  onClick={() => runLiveTest({ rutParity: liveTestRutParity })}
                  disabled={steps.length === 0 || liveTesting || busy}
                  data-testid="vr-live-test-btn"
                  className="w-full inline-flex items-center justify-center gap-1.5 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white text-sm font-medium transition-colors"
                  title={liveTestRutParity
                    ? "RUT parity — matches production job settings"
                    : "Lenient Live Test — may pass steps that fail in RUT"}
                >
                  {liveTesting ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Running…</>
                  ) : liveTestRutParity ? (
                    <><Zap className="w-4 h-4" /> Test like RUT ({steps.length} steps)</>
                  ) : (
                    <><Zap className="w-4 h-4" /> Run Live Test ({steps.length} step{steps.length === 1 ? "" : "s"})</>
                  )}
                </button>
                <div className="text-[10px] text-zinc-500 text-center -mt-1">
                  {liveTestRutParity ? "Stricter replay — closer to real RUT visits" : "Opens a fresh browser tab from step 0"}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={stopAndDiscard}
                    className="inline-flex items-center justify-center gap-1.5 py-2 rounded bg-zinc-800 hover:bg-rose-700 text-zinc-300 hover:text-white text-sm transition-colors"
                    data-testid="vr-discard-btn"
                  >
                    <Square className="w-4 h-4" /> Discard
                  </button>
                  <button
                    onClick={requestFinalize}
                    disabled={steps.length < 2 || busy}
                    className="inline-flex items-center justify-center gap-1.5 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white text-sm font-medium transition-colors"
                    data-testid="vr-finalize-btn"
                  >
                    <CheckCircle2 className="w-4 h-4" /> Finalize
                  </button>
                </div>
              </div>

              {/* 2026-01: Live Activity Panel — real-time step feed during live test */}
              {(liveTesting || (liveProgress && liveProgress.length > 0 && !liveTestResult)) && (
                <div
                  className="mb-2 p-2 rounded border bg-zinc-950/80 border-blue-500/30"
                  data-testid="vr-live-activity-panel"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-blue-300 flex items-center gap-1">
                      {liveTesting ? (
                        <><Loader2 className="w-3 h-3 animate-spin" /> Live Activity — backend pe kya chal raha hai</>
                      ) : (
                        <>📋 Live Activity (last run)</>
                      )}
                    </span>
                    {liveProgress.length > 0 && (() => {
                      const okCount = liveProgress.filter(e => e.status === "ok").length;
                      const failedCount = liveProgress.filter(e => e.status === "failed").length;
                      const runningCount = liveProgress.filter(e => e.status === "running").length;
                      const totalSteps = liveProgress[0]?.total_steps || steps.length;
                      return (
                        <span className="text-[10px] text-zinc-400 font-mono">
                          {okCount}✓ / {failedCount}✗ / {Math.max(0, runningCount - okCount - failedCount)}⏵ / {totalSteps}
                        </span>
                      );
                    })()}
                  </div>
                  {/* Progress bar */}
                  {liveProgress.length > 0 && (() => {
                    const okCount = liveProgress.filter(e => e.status === "ok").length;
                    const failedCount = liveProgress.filter(e => e.status === "failed").length;
                    const totalSteps = liveProgress[0]?.total_steps || steps.length || 1;
                    const pct = Math.min(100, ((okCount + failedCount) / totalSteps) * 100);
                    return (
                      <div className="mb-1.5 h-1 bg-zinc-800 rounded overflow-hidden">
                        <div
                          className={`h-full transition-all ${failedCount > 0 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    );
                  })()}

                  {/* 2026-01: LIVE BROWSER SCREENSHOT — see the page state at the latest completed step */}
                  {/* 2026-06 — scrollable container so tall full-page
                      captures stay at NATURAL size (operator scrolls
                      inside the panel to inspect any part). Earlier
                      version used `objectFit: contain` with a 320px
                      max-height which squeezed multi-screen offer
                      pages into an unreadable thin strip. The new
                      layout keeps the image at full intrinsic width
                      and lets the wrapper scroll vertically. */}
                  {liveFrame && (
                    <div className="mb-1.5 relative rounded overflow-hidden border border-zinc-800" data-testid="vr-live-frame">
                      <div
                        className="overflow-y-auto bg-black"
                        style={{ maxHeight: 360 }}
                        data-testid="vr-live-frame-scroll"
                      >
                        <img
                          src={liveFrame}
                          alt="Live browser view"
                          className="w-full block"
                          style={{ height: "auto", display: "block" }}
                        />
                      </div>
                      {liveFrameMeta && (
                        <div className="absolute top-1 left-1 right-1 flex items-center justify-between gap-1 pointer-events-none">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                            liveFrameMeta.status === 'ok' ? 'bg-emerald-900/90 text-emerald-200' :
                            liveFrameMeta.status === 'failed' ? 'bg-rose-900/90 text-rose-200' :
                            'bg-blue-900/90 text-blue-200'
                          }`}>
                            #{(liveFrameMeta.idx ?? 0) + 1} {liveFrameMeta.action}
                            {liveFrameMeta.selector ? ` ${liveFrameMeta.selector.slice(0, 30)}` : ''}
                          </span>
                          {typeof liveFrameMeta.ms === 'number' && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-900/90 text-zinc-200">
                              {liveFrameMeta.ms}ms
                            </span>
                          )}
                        </div>
                      )}
                      {liveTesting && (
                        <div className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-rose-700/90 text-[10px] text-white font-medium animate-pulse pointer-events-none">
                          ● LIVE
                        </div>
                      )}
                      {/* Scroll hint pill — fades out after operator's
                          first scroll inside the panel. Pure CSS hover
                          so it doesn't cost a re-render per frame. */}
                      <div className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded bg-zinc-900/80 text-[9px] text-zinc-300 font-mono pointer-events-none border border-zinc-700/60">
                        ↕ scroll inside to see full page
                      </div>
                    </div>
                  )}
                  {!liveFrame && liveTesting && (
                    <div className="mb-1.5 p-3 rounded border border-zinc-800 bg-zinc-900/50 text-center text-[10px] text-zinc-500" data-testid="vr-live-frame-empty">
                      <Loader2 className="w-4 h-4 animate-spin inline-block mr-1" /> Waiting for first browser frame…
                    </div>
                  )}

                  {/* Event log — most recent first, max 12 visible */}
                  <div
                    className="max-h-48 overflow-y-auto space-y-0.5 text-[10px] font-mono"
                    data-testid="vr-live-activity-log"
                  >
                    {liveProgress.length === 0 ? (
                      <div className="text-zinc-500 italic">Waiting for first step…</div>
                    ) : (
                      [...liveProgress].reverse().slice(0, 30).map((ev, k) => {
                        const stepNum = (ev.idx ?? 0) + 1;
                        const icon =
                          ev.status === "ok" ? "✓" :
                          ev.status === "failed" ? "✗" :
                          "⏵";
                        const color =
                          ev.status === "ok" ? "text-emerald-400" :
                          ev.status === "failed" ? "text-rose-400" :
                          "text-blue-400 animate-pulse";
                        const time = ev.timestamp_ms ?
                          new Date(ev.timestamp_ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) :
                          "";
                        return (
                          <div
                            key={`${ev.timestamp_ms}-${ev.idx}-${ev.status}-${k}`}
                            className={`flex items-start gap-1.5 ${color}`}
                            data-testid={`vr-live-event-${k}`}
                          >
                            <span className="flex-shrink-0 w-3">{icon}</span>
                            <span className="flex-shrink-0 text-zinc-500">[{time}]</span>
                            <span className="flex-shrink-0">#{stepNum}</span>
                            <span className="flex-shrink-0 text-zinc-200 font-medium truncate max-w-[220px]" title={ev.name || ev.label || ev.detail || ev.action}>
                              {ev.name || ev.label || ev.detail || ev.action}
                            </span>
                            {!(ev.name || ev.label) && ev.selector && (
                              <span className="flex-shrink-0 text-zinc-500 truncate max-w-[140px]" title={ev.selector}>
                                {ev.selector.slice(0, 24)}{ev.selector.length > 24 ? '…' : ''}
                              </span>
                            )}
                            {ev.status === "ok" && typeof ev.ms === "number" && (
                              <span className="flex-shrink-0 text-zinc-500">{ev.ms}ms</span>
                            )}
                            {ev.status === "failed" && ev.error && (
                              <span className="text-rose-300 truncate" title={ev.error}>{ev.error.slice(0, 80)}</span>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              )}

              {/* Live Test Results Panel */}
              {liveTestResult && (
                <div
                  data-testid="vr-live-test-results"
                  className={`mt-3 rounded-lg border ${
                    liveTestResult.ok
                      ? "bg-emerald-950/30 border-emerald-700/40"
                      : "bg-rose-950/30 border-rose-700/40"
                  }`}
                >
                  <div className="p-3 flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                      {liveTestResult.ok ? (
                        <CheckCheck className="w-4 h-4 text-emerald-400" />
                      ) : (
                        <XCircle className="w-4 h-4 text-rose-400" />
                      )}
                      <span className={`text-sm font-medium ${liveTestResult.ok ? "text-emerald-200" : "text-rose-200"}`}>
                        Live test {liveTestResult.ok ? "passed" : "FAILED"}
                      </span>
                      <span className="text-xs text-zinc-400" data-testid="vr-live-test-summary">
                        {liveTestResult.executed_steps}/{liveTestResult.total_steps} steps
                        {typeof liveTestResult.total_ms === "number" && (
                          <> · {(liveTestResult.total_ms / 1000).toFixed(2)}s total</>
                        )}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Auto-retest toggle */}
                      <label
                        className="inline-flex items-center gap-1 text-[10px] text-zinc-400 cursor-pointer select-none"
                        title="When ON, Live Test is automatically re-run after every Auto-fix so you can see the result without an extra click. Off if you want manual control."
                        data-testid="vr-autoretest-toggle-label"
                      >
                        <input
                          type="checkbox"
                          checked={autoRetestEnabled}
                          onChange={(e) => setAutoRetestEnabled(e.target.checked)}
                          data-testid="vr-autoretest-toggle"
                          className="accent-blue-500 cursor-pointer"
                        />
                        Auto-retest after fix
                      </label>
                      {/* Undo button (only when there's fix history) */}
                      {fixHistoryCount > 0 && (
                        <button
                          onClick={undoLastAutoFix}
                          disabled={liveTesting}
                          data-testid="vr-undo-fix-btn"
                          className="inline-flex items-center gap-1 px-2 py-1 rounded bg-amber-600/20 hover:bg-amber-600/40 border border-amber-500/40 text-amber-200 text-[10px] font-medium transition-colors disabled:opacity-40"
                          title="Revert the most recent Auto-fix. Use this if the fix turned out to break something specific to your page."
                        >
                          <Undo2 className="w-3 h-3" />
                          Undo ({fixHistoryCount})
                        </button>
                      )}
                      <button
                        onClick={() => setLiveTestResult(null)}
                        className="text-xs text-zinc-500 hover:text-zinc-200"
                        data-testid="vr-live-test-close"
                      >
                        Close ✕
                      </button>
                    </div>
                  </div>

                  {/* Optional "last undone" hint */}
                  {lastUndoneFix && (
                    <div
                      className="mx-3 mb-2 p-2 rounded bg-amber-950/40 border border-amber-700/40 text-[11px] text-amber-100 flex items-start gap-1.5"
                      data-testid="vr-last-undone-hint"
                    >
                      <Undo2 className="w-3 h-3 mt-0.5 shrink-0" />
                      <span>
                        Reverted: <code className="text-amber-300">{lastUndoneFix.kind}</code> @ step #{(lastUndoneFix.at_step ?? 0) + 1}.
                        Re-run Live Test to confirm the previous state still works.
                      </span>
                    </div>
                  )}

                  {liveTestResult.error && (() => {
                    // 2026-01: Smart fix suggester — parses the error
                    // and surfaces a one-liner cause + recommended
                    // action with quick-jump buttons.
                    const failedIdx = liveTestResult.failed_at_idx;
                    const failedStep = (typeof failedIdx === "number" && steps[failedIdx]) || null;
                    const failedAction = failedStep?.action || null;
                    const fix = getSuggestedFix(liveTestResult.error, failedAction, failedIdx);
                    return (
                      <div className="mx-3 mb-2 space-y-1.5" data-testid="vr-live-test-error">
                        {/* Raw error */}
                        <div className="p-2 rounded bg-rose-900/40 border border-rose-700/40 text-xs text-rose-100">
                          <AlertCircle className="inline w-3.5 h-3.5 mr-1" />
                          {liveTestResult.error}
                        </div>
                        {/* 2026-01: Friendly hint (Roman-Urdu/English plain-language explanation) */}
                        {liveTestResult.friendly_hint && (
                          <div
                            className="p-2 rounded bg-amber-950/30 border border-amber-700/30 text-xs text-amber-100"
                            data-testid="vr-friendly-hint"
                          >
                            💡 <span className="font-medium">Hint:</span> {liveTestResult.friendly_hint}
                          </div>
                        )}
                        {/* Smart suggestion */}
                        {fix && (
                          <div
                            className="p-2.5 rounded bg-sky-950/30 border border-sky-700/30"
                            data-testid="vr-fix-suggestion"
                          >
                            <div className="flex items-start gap-2 mb-1.5">
                              <Lightbulb className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                              <div className="flex-1">
                                <div className="text-[11px] font-semibold text-amber-200 mb-0.5">
                                  WHY THIS HAPPENED
                                </div>
                                <div className="text-xs text-zinc-200 leading-relaxed">
                                  {fix.cause}
                                </div>
                              </div>
                            </div>
                            <div className="flex items-start gap-2 mb-2">
                              <Sparkles className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                              <div className="flex-1">
                                <div className="text-[11px] font-semibold text-emerald-300 mb-0.5">
                                  SUGGESTED FIX
                                </div>
                                <div className="text-xs text-zinc-200 leading-relaxed">
                                  {fix.fix}
                                </div>
                              </div>
                            </div>
                            {/* Quick-jump action buttons */}
                            <div className="flex items-center gap-1.5 flex-wrap mt-2">
                              {fix.action === "edit" && typeof fix.edit_idx === "number" && (
                                <button
                                  onClick={() => openEditStep(fix.edit_idx)}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-amber-700 hover:bg-amber-600 text-white text-[11px] font-medium"
                                  data-testid="vr-fix-edit-btn"
                                >
                                  <Pencil className="w-3 h-3" /> Edit step #{fix.edit_idx + 1}
                                </button>
                              )}
                              {/* "Replay from here" — picks up replay
                                  on the CURRENT page state (no fresh
                                  page) starting at the failed step.
                                  Saves the user from re-running 1-2
                                  min of preceding steps. Available
                                  whenever a specific step index
                                  failed. */}
                              {typeof failedIdx === "number" && failedIdx > 0 && (
                                <button
                                  onClick={() => runLiveTest({ startIndex: failedIdx })}
                                  disabled={liveTesting}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-fuchsia-700 hover:bg-fuchsia-600 text-white text-[11px] font-medium disabled:opacity-40"
                                  data-testid="vr-fix-resume-btn"
                                  title={`Re-run from step #${failedIdx + 1} only — keeps the browser on its current state. ~5-10× faster than a full re-run.`}
                                >
                                  <FastForward className="w-3 h-3" /> Replay from step #{failedIdx + 1}
                                </button>
                              )}
                              {fix.action === "rerun" && (
                                <button
                                  onClick={() => runLiveTest()}
                                  disabled={liveTesting}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-blue-700 hover:bg-blue-600 text-white text-[11px] font-medium disabled:opacity-40"
                                  data-testid="vr-fix-rerun-btn"
                                >
                                  <Zap className="w-3 h-3" /> Re-run Live Test
                                </button>
                              )}
                              {fix.action === "manual_add" && (
                                <button
                                  onClick={openManualAddStep}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-sky-700 hover:bg-sky-600 text-white text-[11px] font-medium"
                                  data-testid="vr-fix-add-btn"
                                >
                                  <ListPlus className="w-3 h-3" /> Add a wait step
                                </button>
                              )}
                              {fix.action === "restart" && (
                                <button
                                  onClick={stopAndDiscard}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-rose-700 hover:bg-rose-600 text-white text-[11px] font-medium"
                                  data-testid="vr-fix-restart-btn"
                                >
                                  <RefreshCw className="w-3 h-3" /> Discard & restart
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Per-step timing list */}
                  {Array.isArray(liveTestResult.step_results) && liveTestResult.step_results.length > 0 && (
                    <div className="mx-3 mb-2 max-h-56 overflow-y-auto rounded border border-zinc-800 bg-zinc-950/60 divide-y divide-zinc-800/60">
                      {liveTestResult.step_results.map((r) => (
                        <div
                          key={`vrst-${r.idx}`}
                          data-testid={`vr-live-step-${r.idx}`}
                          className={`px-2 py-1.5 text-xs flex items-center justify-between gap-2 ${
                            r.ok
                              ? "text-zinc-200"
                              : "text-rose-200 bg-rose-950/40"
                          }`}
                          title={r.error || ""}
                        >
                          <div className="flex items-center gap-1.5 min-w-0 flex-1">
                            {r.ok ? (
                              <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                            ) : (
                              <XCircle className="w-3 h-3 text-rose-400 shrink-0" />
                            )}
                            <span className="text-zinc-500 w-7 shrink-0">#{(r.idx ?? 0) + 1}</span>
                            <span className="font-mono text-[11px] uppercase shrink-0 text-zinc-400">{r.action}</span>
                            <span className="truncate text-zinc-500">{r.selector}</span>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {r.self_healed && (
                              <span className="text-[10px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">healed</span>
                            )}
                            {r.optional && !r.ok && (
                              <span className="text-[10px] px-1 py-0.5 rounded bg-zinc-700/40 text-zinc-400">skipped</span>
                            )}
                            <span className={`font-mono text-[11px] ${(r.ms || 0) > 5000 ? "text-amber-300" : "text-zinc-400"}`}>
                              <Timer className="inline w-3 h-3 mr-0.5" />{r.ms ?? 0}ms
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Smart Diagnostics */}
                  {liveTestResult.diagnostics && showDiagnostics && (
                    <div className="mx-3 mb-3 rounded border border-zinc-800 bg-zinc-950/60 p-2" data-testid="vr-diagnostics-panel">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-1 text-xs font-medium text-blue-300">
                          <Lightbulb className="w-3.5 h-3.5" /> Smart Replay Diagnostics
                        </div>
                        <button
                          onClick={() => setShowDiagnostics(false)}
                          className="text-[10px] text-zinc-500 hover:text-zinc-200"
                        >
                          Hide
                        </button>
                      </div>

                      {/* Top-3 slowest */}
                      {Array.isArray(liveTestResult.diagnostics.slowest) && liveTestResult.diagnostics.slowest.length > 0 && (
                        <div className="mb-2">
                          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Top slowest steps</div>
                          <div className="flex flex-wrap gap-1.5">
                            {liveTestResult.diagnostics.slowest.map((s) => (
                              <span
                                key={`slow-${s.idx}`}
                                data-testid={`vr-diag-slow-${s.idx}`}
                                className={`text-[10px] px-2 py-0.5 rounded-full border ${(s.ms || 0) > 5000 ? "bg-amber-500/15 border-amber-500/40 text-amber-200" : "bg-zinc-800 border-zinc-700 text-zinc-300"}`}
                              >
                                #{(s.idx ?? 0) + 1} {s.action} · {s.ms}ms
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Wrapper summary */}
                      {liveTestResult.diagnostics.wrapper_summary && Object.keys(liveTestResult.diagnostics.wrapper_summary).length > 0 && (
                        <div className="mb-2">
                          <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Dropdown wrappers</div>
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(liveTestResult.diagnostics.wrapper_summary).map(([k, v]) => (
                              <span
                                key={`wk-${k}`}
                                data-testid={`vr-diag-wrap-${k}`}
                                className={`text-[10px] px-2 py-0.5 rounded-full border ${k === "native" ? "bg-zinc-800 border-zinc-700 text-zinc-300" : "bg-blue-500/15 border-blue-500/40 text-blue-200"}`}
                              >
                                {k}: {v}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Anti-patterns / Findings — with Auto-fix buttons */}
                      {(Array.isArray(liveTestResult.diagnostics.findings) && liveTestResult.diagnostics.findings.length > 0) ? (
                        <div className="mb-2" data-testid="vr-diag-findings-section">
                          <div className="flex items-center justify-between mb-1.5 flex-wrap gap-1">
                            <div className="text-[10px] uppercase tracking-wide text-amber-400 flex items-center gap-1">
                              <AlertCircle className="w-3 h-3" /> Anti-patterns ({liveTestResult.diagnostics.findings.length})
                            </div>
                            {(liveTestResult.diagnostics.auto_fixable_count || 0) > 0 && (
                              <button
                                onClick={() => applyAutoFix({}, true)}
                                disabled={liveTesting}
                                data-testid="vr-autofix-all-btn"
                                className="inline-flex items-center gap-1 px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white text-[10px] font-medium transition-colors"
                                title="Apply every auto-fixable finding in one shot. Re-run Live Test after to confirm."
                              >
                                <Sparkles className="w-3 h-3" />
                                Auto-fix all ({liveTestResult.diagnostics.auto_fixable_count})
                              </button>
                            )}
                          </div>
                          <ul className="space-y-1.5 text-[11px]">
                            {liveTestResult.diagnostics.findings.map((f, i) => (
                              <li
                                key={`f-${i}-${f.kind}-${f.at_step}`}
                                data-testid={`vr-diag-finding-${i}`}
                                className="rounded border border-zinc-800 bg-zinc-950/40 p-1.5 flex items-start gap-2"
                              >
                                <div className="flex-1 min-w-0">
                                  <div className="text-zinc-200 leading-snug">{f.message}</div>
                                  {f.fix_summary && (
                                    <div className="text-emerald-300/80 mt-0.5 text-[10px] flex items-start gap-1">
                                      <Lightbulb className="w-2.5 h-2.5 mt-0.5 shrink-0" />
                                      <span>{f.fix_summary}</span>
                                    </div>
                                  )}
                                </div>
                                {f.auto_fixable ? (
                                  <button
                                    onClick={() => applyAutoFix({ kind: f.kind, at_step: f.at_step, extra: f.extra })}
                                    disabled={liveTesting}
                                    data-testid={`vr-autofix-btn-${i}`}
                                    className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded bg-emerald-600/30 hover:bg-emerald-600/60 border border-emerald-500/40 text-emerald-100 text-[10px] font-medium transition-colors disabled:opacity-40"
                                    title={f.fix_summary || "Apply this fix"}
                                  >
                                    <Sparkles className="w-2.5 h-2.5" /> Auto-fix
                                  </button>
                                ) : (
                                  <span className="shrink-0 text-[10px] text-zinc-500 px-1 py-0.5">manual</span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : (
                        // Fallback to legacy string-only render for builds without findings field
                        Array.isArray(liveTestResult.diagnostics.anti_patterns) && liveTestResult.diagnostics.anti_patterns.length > 0 && (
                          <div className="mb-2">
                            <div className="text-[10px] uppercase tracking-wide text-amber-400 mb-1 flex items-center gap-1">
                              <AlertCircle className="w-3 h-3" /> Anti-patterns ({liveTestResult.diagnostics.anti_patterns.length})
                            </div>
                            <ul className="space-y-1 text-[11px] text-zinc-300 list-disc list-inside">
                              {liveTestResult.diagnostics.anti_patterns.map((ap, i) => (
                                <li key={`ap-${i}`} data-testid={`vr-diag-ap-${i}`} className="leading-snug">{ap}</li>
                              ))}
                            </ul>
                          </div>
                        )
                      )}

                      {/* Recommendations — only show if NO structured findings
                          (otherwise the fix_summary inside each finding is
                          already showing the actionable advice) */}
                      {(!Array.isArray(liveTestResult.diagnostics.findings) || liveTestResult.diagnostics.findings.length === 0) && Array.isArray(liveTestResult.diagnostics.recommendations) && liveTestResult.diagnostics.recommendations.length > 0 && (
                        <div>
                          <div className="text-[10px] uppercase tracking-wide text-emerald-400 mb-1 flex items-center gap-1">
                            <Lightbulb className="w-3 h-3" /> Recommendations
                          </div>
                          <ul className="space-y-1 text-[11px] text-emerald-100/90 list-disc list-inside">
                            {liveTestResult.diagnostics.recommendations.map((rc, i) => (
                              <li key={`rc-${i}`} data-testid={`vr-diag-rec-${i}`} className="leading-snug">{rc}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* DONE stage */}
        {setupStage === "done" && finalBundle && (
          <div className="max-w-3xl mx-auto p-6 rounded-xl bg-zinc-900/60 border border-emerald-700/40">
            <div className="flex items-center gap-2 mb-4">
              <CheckCircle2 className="w-7 h-7 text-emerald-400" />
              <h2 className="text-xl font-semibold">Recording Complete!</h2>
            </div>
            <div className="grid sm:grid-cols-3 gap-3 mb-5">
              <div className="p-3 rounded bg-zinc-950 border border-zinc-800">
                <div className="text-xs text-zinc-500">Steps</div>
                <div className="text-2xl font-semibold text-emerald-400">{finalBundle.step_count}</div>
              </div>
              <div className="p-3 rounded bg-zinc-950 border border-zinc-800">
                <div className="text-xs text-zinc-500">Headers</div>
                <div className="text-2xl font-semibold text-emerald-400">{finalBundle.headers?.length || 0}</div>
              </div>
              <div className="p-3 rounded bg-zinc-950 border border-zinc-800">
                <div className="text-xs text-zinc-500">Final Page</div>
                <div className="text-2xl font-semibold text-emerald-400">{finalBundle.target_screenshot_path ? "✓" : "—"}</div>
              </div>
            </div>

            <div className="mb-4 p-3 rounded-lg bg-indigo-950/40 border border-indigo-600/30 text-sm text-indigo-100">
              <strong className="text-indigo-200">Deal-wall / reward offers?</strong>{" "}
              Har deal click record karne ki bajaye RUT{" "}
              <Link to="/real-user-traffic" className="underline text-indigo-300 hover:text-indigo-100">
                Smart Funnel
              </Link>{" "}
              use karein — retail → survey → form → deals automatically handle hota hai.
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
              <button
                onClick={launchVisualReplay}
                disabled={replayLaunching || !finalBundle.url}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white text-sm font-medium transition-colors"
                data-testid="vr-visual-replay-btn"
                title="Re-opens a fresh browser session and replays the full saved JSON step-by-step with live visual — perfect for verifying everything works end-to-end before deploying."
              >
                {replayLaunching ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Launching replay…</>
                ) : (
                  <><Zap className="w-4 h-4" /> Live Visual Test (Step-by-Step)</>
                )}
              </button>
              <button
                onClick={copyJson}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-700/40 hover:bg-emerald-700/60 border border-emerald-500/40 text-emerald-100 text-sm font-medium transition-colors"
                data-testid="vr-copy-json-btn"
              >
                <Copy className="w-4 h-4" /> Copy JSON
              </button>
              <button
                onClick={downloadJson}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-700/40 hover:bg-emerald-700/60 border border-emerald-500/40 text-emerald-100 text-sm font-medium transition-colors"
                data-testid="vr-download-json-btn"
              >
                <Download className="w-4 h-4" /> Download JSON
              </button>
              <button
                onClick={saveToLibrary}
                disabled={saving}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-700/40 hover:bg-indigo-700/60 border border-indigo-500/40 text-indigo-100 text-sm font-medium disabled:opacity-60 transition-colors"
                data-testid="vr-save-library-btn"
                title={editUploadId
                  ? `Update existing template "${editTemplate?.name || ''}" (upload ID preserved)`
                  : "Save as reusable template in Uploaded Things library"}
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : savedToLibraryId ? <CheckCircle2 className="w-4 h-4" /> : <Save className="w-4 h-4" />}
                {savedToLibraryId
                  ? (editUploadId ? "Updated ✓ (re-save to push more edits)" : "Saved (re-save to update)")
                  : (editUploadId
                      ? `Update "${editTemplate?.name || 'template'}"`
                      : "Save to Library")}
              </button>
              {finalBundle.target_screenshot_path && (
                <button
                  onClick={downloadTargetScreenshot}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-700/40 hover:bg-blue-700/60 border border-blue-500/40 text-blue-100 text-sm font-medium transition-colors"
                  data-testid="vr-download-target-btn"
                >
                  <Download className="w-4 h-4" /> Download Final Screenshot
                </button>
              )}
            </div>

            <details className="mt-4" open>
              <summary className="cursor-pointer text-sm text-zinc-400 hover:text-zinc-200 select-none flex items-center gap-1">
                <ChevronDown className="w-4 h-4" /> {editingJson ? "Edit JSON" : "Preview JSON"}
                {!editingJson && (
                  <button
                    type="button"
                    onClick={(e) => { e.preventDefault(); openJsonEditor(); }}
                    className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-700/40 hover:bg-amber-700/60 border border-amber-500/40 text-amber-200 text-[10px] font-medium"
                    data-testid="vr-edit-json-btn"
                    title="Edit the finalized JSON directly — fix selectors, tweak timeouts, add/remove steps"
                  >
                    <Pencil className="w-3 h-3" /> Edit JSON
                  </button>
                )}
                {editingJson && <span className="text-[10px] text-amber-400 ml-auto">unsaved changes</span>}
              </summary>
              {editingJson ? (
                <div className="mt-2 space-y-2">
                  <textarea
                    value={editingJsonText}
                    onChange={(e) => { setEditingJsonText(e.target.value); setEditingJsonError(""); }}
                    spellCheck={false}
                    className="w-full p-3 rounded bg-zinc-950 border border-amber-700/40 focus:border-amber-500 text-emerald-300 text-xs font-mono leading-relaxed outline-none resize-y"
                    style={{ minHeight: "24rem", maxHeight: "60vh" }}
                    data-testid="vr-edit-json-textarea"
                  />
                  {editingJsonError && (
                    <div className="p-2 rounded bg-rose-900/40 border border-rose-700/40 text-xs text-rose-200" data-testid="vr-edit-json-error">
                      <AlertCircle className="inline w-3.5 h-3.5 mr-1" />
                      {editingJsonError}
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={saveJsonEditor}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium"
                      data-testid="vr-save-json-btn"
                    >
                      <Save className="w-3.5 h-3.5" /> Save JSON Changes
                    </button>
                    <button
                      onClick={cancelJsonEditor}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
                      data-testid="vr-cancel-json-btn"
                    >
                      Cancel
                    </button>
                    <div className="text-[10px] text-zinc-500 ml-2">
                      Must be a JSON array of step objects with <code className="text-zinc-300">"action"</code>.
                    </div>
                  </div>
                </div>
              ) : (
                <pre
                  className="mt-2 p-3 rounded bg-zinc-950 border border-zinc-800 text-xs overflow-x-auto max-h-96 font-mono leading-relaxed"
                  dangerouslySetInnerHTML={{
                    __html: colorizeJson(finalBundle.automation_json),
                  }}
                />
              )}
            </details>

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                onClick={() => {
                  stashVrAutomationForRut(finalBundle);
                  window.location.href = "/real-user-traffic";
                }}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
                data-testid="vr-use-in-rut-btn"
              >
                <ArrowLeft className="w-4 h-4" /> Use in RUT
              </button>
              <button
                onClick={() => {
                  setFinalBundle(null);
                  setSessionId(null);
                  setSteps([]);
                  setSetupStage("setup");
                  setUrl("");
                  setProxy("");
                  setUa("");
                }}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm"
                data-testid="vr-new-recording-btn"
              >
                <Play className="w-4 h-4" /> New Recording
              </button>
              <Link
                to="/real-user-traffic"
                onClick={() => stashVrAutomationForRut(finalBundle)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm"
              >
                <ArrowLeft className="w-4 h-4" /> Back to RUT
              </Link>
            </div>
          </div>
        )}
      </div>

      {/* ── Edit Step Modal (2026-01) ─────────────────────────────────
          Opened by the per-step pencil button. Lets the user fix a
          wrong selector / bump a timeout / change a value or key after
          a Live Test failure, without deleting + re-recording.
          `action` is shown read-only — changing it would break replay
          semantics (delete + re-record instead). ────────────────── */}
      {/* ── 2026-06: If / Else Branch Editor modal ───────────────────
          Lets the user define a conditional branch step without having
          to edit raw JSON. Each branch has a condition (URL contains /
          selector visible / text visible / etc.) and a list of nested
          steps that run when that branch wins. Branches race in
          parallel — first matching condition wins; falls back to
          `default_steps` if none match within `timeout_ms`.

          Initial nested steps default to a simple [wait 500ms]; the user
          can refine via the existing "Edit Raw JSON" affordance on the
          parent branch step after insert. ─────────────────────────── */}
      {branchEditor && (
        <div
          className="fixed inset-0 z-50 flex items-stretch justify-end pointer-events-none"
          data-testid="vr-branch-modal-backdrop"
        >
          <div
            className="absolute inset-0 pointer-events-auto bg-black/30"
            onClick={() => setBranchEditor(null)}
          />
          <div
            className="relative w-full max-w-xl bg-zinc-950/95 border-l border-zinc-800 shadow-2xl backdrop-blur-md pointer-events-auto flex flex-col"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-branch-modal"
          >
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-fuchsia-400" />
                <h3 className="text-sm font-semibold text-zinc-100">
                  If / Else Branch
                </h3>
                <span className="px-1.5 py-0.5 rounded bg-fuchsia-900/40 border border-fuchsia-700/50 text-fuchsia-200 text-[10px] font-mono uppercase">
                  conditional
                </span>
              </div>
              <button
                onClick={() => setBranchEditor(null)}
                className="text-zinc-500 hover:text-zinc-200"
                data-testid="vr-branch-modal-close"
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
              <div className="text-zinc-400 leading-relaxed">
                Use this when a page can show <b>different forms randomly</b>
                {" "}— e.g. sometimes <i>phone</i>, sometimes <i>email</i>,
                sometimes a survey. The first branch whose condition becomes
                true within the timeout will run. If <b>none</b> match, the
                Default Steps run.
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] uppercase text-zinc-500 mb-1">
                    Step name
                  </label>
                  <input
                    type="text"
                    value={branchEditor.draft.name || ""}
                    onChange={(e) => setBranchEditor((bx) => ({
                      ...bx, draft: { ...bx.draft, name: e.target.value }
                    }))}
                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-zinc-200"
                    placeholder="e.g. Page picker"
                    data-testid="vr-branch-name"
                  />
                </div>
                <div>
                  <label className="block text-[10px] uppercase text-zinc-500 mb-1">
                    Race timeout (ms)
                  </label>
                  <input
                    type="number"
                    min={1000}
                    step={500}
                    value={branchEditor.draft.timeout_ms || 12000}
                    onChange={(e) => setBranchEditor((bx) => ({
                      ...bx, draft: { ...bx.draft, timeout_ms: Math.max(1000, Number(e.target.value) || 12000) }
                    }))}
                    className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-zinc-200 font-mono"
                    data-testid="vr-branch-timeout"
                  />
                </div>
              </div>

              {/* Branches list */}
              <div className="space-y-3">
                {(branchEditor.draft.branches || []).map((b, bi) => (
                  <div
                    key={bi}
                    className="rounded-lg border border-fuchsia-900/40 bg-fuchsia-950/10 p-3 space-y-2"
                    data-testid={`vr-branch-row-${bi}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 flex-1">
                        <span className="text-fuchsia-300 font-mono text-[10px]">#{bi + 1}</span>
                        <input
                          type="text"
                          value={b.name || ""}
                          onChange={(e) => setBranchEditor((bx) => {
                            const arr = [...(bx.draft.branches || [])];
                            arr[bi] = { ...arr[bi], name: e.target.value };
                            return { ...bx, draft: { ...bx.draft, branches: arr } };
                          })}
                          placeholder={`Path ${String.fromCharCode(65 + bi)}`}
                          className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-zinc-200"
                          data-testid={`vr-branch-name-${bi}`}
                        />
                      </div>
                      {(branchEditor.draft.branches || []).length > 1 && (
                        <button
                          onClick={() => setBranchEditor((bx) => {
                            const arr = (bx.draft.branches || []).filter((_, i) => i !== bi);
                            return { ...bx, draft: { ...bx.draft, branches: arr } };
                          })}
                          className="text-rose-400 hover:text-rose-300 p-1"
                          title="Remove this branch"
                          data-testid={`vr-branch-remove-${bi}`}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                      <div className="col-span-1">
                        <label className="block text-[10px] uppercase text-zinc-500 mb-1">
                          When
                        </label>
                        <select
                          value={b.condition?.type || "selector_visible"}
                          onChange={(e) => setBranchEditor((bx) => {
                            const arr = [...(bx.draft.branches || [])];
                            arr[bi] = {
                              ...arr[bi],
                              condition: { ...(arr[bi].condition || {}), type: e.target.value }
                            };
                            return { ...bx, draft: { ...bx.draft, branches: arr } };
                          })}
                          className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-zinc-200"
                          data-testid={`vr-branch-cond-type-${bi}`}
                        >
                          <option value="selector_visible">Element visible</option>
                          <option value="selector_attached">Element exists (hidden ok)</option>
                          <option value="text_visible">Text appears</option>
                          <option value="url_contains">URL contains</option>
                          <option value="url_matches">URL matches regex</option>
                        </select>
                      </div>
                      <div className="col-span-2">
                        <label className="block text-[10px] uppercase text-zinc-500 mb-1">
                          {(() => {
                            const t = b.condition?.type || "selector_visible";
                            if (t === "text_visible") return "Text to wait for";
                            if (t === "url_contains") return "URL fragment (e.g. /phone)";
                            if (t === "url_matches") return "URL regex (e.g. thank-?you)";
                            return "CSS selector (e.g. input[name=phone])";
                          })()}
                        </label>
                        <input
                          type="text"
                          value={(() => {
                            const c = b.condition || {};
                            const t = c.type || "selector_visible";
                            if (t === "text_visible") return c.text || "";
                            if (t === "url_contains" || t === "url_matches") return c.value || "";
                            return c.selector || "";
                          })()}
                          onChange={(e) => setBranchEditor((bx) => {
                            const arr = [...(bx.draft.branches || [])];
                            const c = { ...(arr[bi].condition || {}) };
                            const t = c.type || "selector_visible";
                            if (t === "text_visible") c.text = e.target.value;
                            else if (t === "url_contains" || t === "url_matches") c.value = e.target.value;
                            else c.selector = e.target.value;
                            arr[bi] = { ...arr[bi], condition: c };
                            return { ...bx, draft: { ...bx.draft, branches: arr } };
                          })}
                          placeholder={(() => {
                            const t = b.condition?.type || "selector_visible";
                            if (t === "text_visible") return "Birthday";
                            if (t === "url_contains") return "/phone-question";
                            if (t === "url_matches") return "thank.?you|congrats";
                            return "input[name=phone]";
                          })()}
                          className="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-zinc-200 font-mono"
                          data-testid={`vr-branch-cond-value-${bi}`}
                        />
                      </div>
                    </div>

                    <div className="text-[10px] text-zinc-500">
                      Steps to run when this branch wins: <span className="text-fuchsia-300 font-mono">
                        {(b.steps || []).length}
                      </span>
                      {(b.steps || []).length === 0 && (
                        <span> — use <b>Edit Raw JSON</b> on this branch step after insert to add nested actions, or insert a quick wait below.</span>
                      )}
                      <button
                        onClick={() => setBranchEditor((bx) => {
                          const arr = [...(bx.draft.branches || [])];
                          const cur = Array.isArray(arr[bi].steps) ? arr[bi].steps : [];
                          arr[bi] = { ...arr[bi], steps: [...cur, { action: "wait", ms: 500, source: "manual" }] };
                          return { ...bx, draft: { ...bx.draft, branches: arr } };
                        })}
                        className="ml-2 px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10px]"
                        data-testid={`vr-branch-add-wait-${bi}`}
                      >
                        + wait 500ms
                      </button>
                    </div>
                  </div>
                ))}

                <button
                  onClick={() => setBranchEditor((bx) => {
                    const arr = bx.draft.branches || [];
                    const newBranch = {
                      name: `Path ${String.fromCharCode(65 + arr.length)}`,
                      condition: { type: "selector_visible", selector: "" },
                      steps: [],
                    };
                    return { ...bx, draft: { ...bx.draft, branches: [...arr, newBranch] } };
                  })}
                  className="w-full px-3 py-2 rounded-lg border border-dashed border-fuchsia-700/40 hover:border-fuchsia-500 hover:bg-fuchsia-900/10 text-fuchsia-300 text-xs font-medium transition-colors"
                  data-testid="vr-branch-add"
                >
                  + Add another branch
                </button>
              </div>

              {/* Default steps fall-back hint */}
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                <div className="text-[10px] uppercase text-zinc-500 mb-1">
                  Default steps
                </div>
                <div className="text-zinc-400 text-[11px]">
                  If <b>no branch</b> matches within {(branchEditor.draft.timeout_ms || 12000)}ms,
                  these run instead.{" "}
                  <span className="text-zinc-500">
                    Currently <span className="text-fuchsia-300 font-mono">{(branchEditor.draft.default_steps || []).length}</span> step{(branchEditor.draft.default_steps || []).length === 1 ? "" : "s"}.
                    Add a quick wait below, or refine via &quot;Edit Raw JSON&quot; on the parent step after insert.
                  </span>
                </div>
                <button
                  onClick={() => setBranchEditor((bx) => {
                    const cur = Array.isArray(bx.draft.default_steps) ? bx.draft.default_steps : [];
                    return { ...bx, draft: { ...bx.draft, default_steps: [...cur, { action: "wait", ms: 500, source: "manual" }] } };
                  })}
                  className="mt-2 px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10px]"
                  data-testid="vr-branch-add-default-wait"
                >
                  + wait 500ms (default)
                </button>
              </div>
            </div>

            <div className="border-t border-zinc-800 p-3 flex items-center justify-between gap-2">
              <button
                onClick={() => setBranchEditor(null)}
                className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
                data-testid="vr-branch-cancel"
              >
                Cancel
              </button>
              <button
                onClick={submitBranch}
                disabled={busy}
                className="px-4 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-500 disabled:opacity-50 text-white text-xs font-semibold"
                data-testid="vr-branch-save"
              >
                {busy ? "Inserting…" : "Insert branch step"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 2026-06 — AI Step Generator dialog (Visual Recorder).
          Provider + key come from user's Settings → AI Integrations.
          Output replaces the current `steps` array. Z-index 70 above
          prompt modal so a self-heal prompt mid-AI-call doesn't hide
          this dialog. */}
      {/* 2026-01 v2.4.2 — Scan Result modal.  Shows the text / CSS
          selector / xpath (stable + absolute) / attrs of whatever
          element the customer clicked in Scan mode, each with a Copy
          button. No step is recorded and no click was fired on the
          live page. */}
      {scanResult && (
        <div
          className="fixed inset-0 z-[65] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          data-testid="vr-scan-result-backdrop"
          onClick={() => setScanResult(null)}
        >
          <div
            className="w-[min(680px,94vw)] max-h-[90vh] overflow-y-auto rounded-2xl border border-cyan-500/40 bg-zinc-950 p-6 shadow-2xl shadow-cyan-900/40"
            data-testid="vr-scan-result-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-cyan-600/20 border border-cyan-500/40 flex items-center justify-center">
                  <ScanSearch className="w-5 h-5 text-cyan-300" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Scanned element</h3>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    Copy the locators to use anywhere — RPA Studio, manual click steps,
                    Wait for selector / xpath, custom automation JSON.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setScanResult(null)}
                className="p-1 text-zinc-500 hover:text-white rounded"
                data-testid="vr-scan-result-close-btn"
                aria-label="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              {/* Tag + text summary */}
              <div className="flex items-center gap-2 text-xs text-zinc-400">
                <span className="px-2 py-0.5 rounded bg-cyan-900/40 text-cyan-200 font-mono uppercase">
                  {scanResult.tag || "?"}
                </span>
                {scanResult.bbox && (
                  <span className="text-[10px] text-zinc-500 font-mono">
                    {scanResult.bbox.w}×{scanResult.bbox.h} @ ({scanResult.bbox.x},{scanResult.bbox.y})
                  </span>
                )}
              </div>

              {/* Text */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] uppercase tracking-wider text-cyan-300 font-semibold">Text</label>
                  <button
                    onClick={() => copyScanValue(scanResult.text, "Text")}
                    className="text-[10px] px-2 py-0.5 rounded bg-cyan-800/40 hover:bg-cyan-700/50 text-cyan-200 flex items-center gap-1"
                    data-testid="vr-scan-copy-text-btn"
                  >
                    <Copy className="w-3 h-3" /> Copy
                  </button>
                </div>
                <div className="p-2 rounded bg-zinc-900 border border-zinc-800 text-sm text-zinc-100 break-words">
                  {scanResult.text || <span className="text-zinc-500 italic">(no text)</span>}
                </div>
              </div>

              {/* Selector (CSS) */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] uppercase tracking-wider text-cyan-300 font-semibold">CSS Selector</label>
                  <button
                    onClick={() => copyScanValue(scanResult.selector, "Selector")}
                    className="text-[10px] px-2 py-0.5 rounded bg-cyan-800/40 hover:bg-cyan-700/50 text-cyan-200 flex items-center gap-1"
                    data-testid="vr-scan-copy-selector-btn"
                  >
                    <Copy className="w-3 h-3" /> Copy
                  </button>
                </div>
                <div className="p-2 rounded bg-zinc-900 border border-zinc-800 text-xs text-emerald-200 font-mono break-all">
                  {scanResult.selector || <span className="text-zinc-500 italic">(none)</span>}
                </div>
              </div>

              {/* Xpath (stable, preferred) */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] uppercase tracking-wider text-cyan-300 font-semibold">XPath (stable)</label>
                  <button
                    onClick={() => copyScanValue(scanResult.xpath_stable || scanResult.xpath, "XPath")}
                    className="text-[10px] px-2 py-0.5 rounded bg-cyan-800/40 hover:bg-cyan-700/50 text-cyan-200 flex items-center gap-1"
                    data-testid="vr-scan-copy-xpath-btn"
                  >
                    <Copy className="w-3 h-3" /> Copy
                  </button>
                </div>
                <div className="p-2 rounded bg-zinc-900 border border-zinc-800 text-xs text-indigo-200 font-mono break-all">
                  {scanResult.xpath_stable || scanResult.xpath || <span className="text-zinc-500 italic">(none)</span>}
                </div>
              </div>

              {/* Xpath absolute (fallback) */}
              {scanResult.xpath_abs && scanResult.xpath_abs !== (scanResult.xpath_stable || "") && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[11px] uppercase tracking-wider text-cyan-300 font-semibold">XPath (absolute)</label>
                    <button
                      onClick={() => copyScanValue(scanResult.xpath_abs, "Absolute XPath")}
                      className="text-[10px] px-2 py-0.5 rounded bg-cyan-800/40 hover:bg-cyan-700/50 text-cyan-200 flex items-center gap-1"
                      data-testid="vr-scan-copy-xpath-abs-btn"
                    >
                      <Copy className="w-3 h-3" /> Copy
                    </button>
                  </div>
                  <div className="p-2 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-400 font-mono break-all">
                    {scanResult.xpath_abs}
                  </div>
                </div>
              )}

              {/* Attributes */}
              {scanResult.attrs && Object.keys(scanResult.attrs).length > 0 && (
                <div>
                  <label className="text-[11px] uppercase tracking-wider text-cyan-300 font-semibold block mb-1">Attributes</label>
                  <div className="p-2 rounded bg-zinc-900 border border-zinc-800 text-[11px] text-zinc-300 font-mono max-h-32 overflow-y-auto">
                    {Object.entries(scanResult.attrs).slice(0, 20).map(([k, v]) => (
                      <div key={k} className="truncate">
                        <span className="text-amber-300">{k}</span>=<span className="text-emerald-200">&quot;{String(v).slice(0, 120)}&quot;</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setScanResult(null)}
                className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
                data-testid="vr-scan-close-btn"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {aiDialogOpen && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 backdrop-blur-sm"
          data-testid="vr-ai-dialog-backdrop"
          onClick={() => { if (!aiBusy) setAiDialogOpen(false); }}
        >
          <div
            className="w-[min(640px,92vw)] max-h-[88vh] overflow-y-auto rounded-2xl border border-purple-500/30 bg-zinc-950 p-6 shadow-2xl shadow-purple-900/40"
            data-testid="vr-ai-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-purple-600/20 border border-purple-500/40 flex items-center justify-center">
                  <Sparkles className="w-5 h-5 text-purple-300" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Generate steps with AI</h3>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    Upload 1-15 screenshots (or one short MP4 walkthrough) and let AI
                    generate the Visual Recorder steps. Refine selectors live after.
                  </p>
                </div>
              </div>
              <button
                onClick={() => { if (!aiBusy) setAiDialogOpen(false); }}
                className="text-zinc-500 hover:text-white p-1"
                data-testid="vr-ai-dialog-close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Screenshots / video <span className="text-zinc-500">(png, jpg, webp, mp4, mov, webm — up to 15 images or 1 video)</span>
                </label>
                <input
                  type="file"
                  multiple
                  accept="image/png,image/jpeg,image/jpg,image/webp,video/mp4,video/quicktime,video/webm,video/mpeg,video/x-msvideo"
                  onChange={(e) => setAiFiles(Array.from(e.target.files || []))}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 file:mr-3 file:rounded file:border-0 file:bg-purple-600 file:px-3 file:py-1 file:text-white hover:file:bg-purple-500"
                  data-testid="vr-ai-files-input"
                />
                {aiFiles.length > 0 && (
                  <div className="text-xs text-zinc-500 mt-1">
                    {aiFiles.length} file{aiFiles.length === 1 ? "" : "s"} selected ({(aiFiles.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MiB) — auto-compressed before upload to bypass ingress limit.
                  </div>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Target URL <span className="text-zinc-500">(optional — helps AI orient)</span>
                </label>
                <input
                  type="text"
                  value={aiTargetUrl}
                  onChange={(e) => setAiTargetUrl(e.target.value)}
                  placeholder={url || "https://example.com/offer"}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-purple-500 focus:outline-none"
                  data-testid="vr-ai-target-url"
                />
              </div>

              {/* 2026-06 — Proxy selector (US-only offers etc.). Once
                  AI generates steps, this proxy is auto-copied into the
                  main setup screen so Start Recording uses it. */}
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Proxy Provider <span className="text-zinc-500 font-normal">(optional)</span>
                </label>
                <select
                  value={proxyProviderId}
                  onChange={(e) => onProxyProviderChange(e.target.value)}
                  className="w-full px-3 py-2 rounded-md border border-zinc-700 bg-zinc-900 text-zinc-100 focus:border-purple-500 focus:outline-none transition-colors text-sm mb-2"
                  data-testid="vr-ai-proxy-provider"
                >
                  <option value="">(none — paste proxy manually)</option>
                  {proxyProviders.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {(p.kind || "").replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-xs font-medium text-zinc-300">
                    Proxy <span className="text-zinc-500 font-normal">(optional — for geo-restricted offers like US-only)</span>
                  </label>
                  {pjAvailable && (
                    <button
                      type="button"
                      onClick={aiUseProxyJet}
                      disabled={aiProxyJetBusy || aiBusy || !proxyProviderId}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-indigo-600/30 hover:bg-indigo-600/60 border border-indigo-500/40 text-indigo-200 disabled:opacity-50"
                      data-testid="vr-ai-use-provider-proxy"
                      title="Fetch a fresh proxy from the selected Proxy Provider"
                    >
                      {aiProxyJetBusy
                        ? <Loader2 className="w-3 h-3 animate-spin" />
                        : <Zap className="w-3 h-3" />}
                      From Provider
                    </button>
                  )}
                </div>
                <input
                  type="text"
                  value={aiProxy}
                  onChange={(e) => setAiProxy(e.target.value)}
                  placeholder={proxy ? `Currently using: ${proxy.slice(0, 60)}${proxy.length > 60 ? "…" : ""} (clear to override)` : "http://user:pass@host:port  or  host:port"}
                  className="w-full px-3 py-2 rounded-md border border-zinc-700 bg-zinc-900 text-zinc-100 placeholder:text-zinc-600 focus:border-purple-500 focus:outline-none font-mono text-xs"
                  data-testid="vr-ai-proxy-input"
                />
                <p className="text-[10px] text-zinc-500 mt-1">
                  {pjAvailable
                    ? "Click From Provider for a one-click fresh proxy, OR paste your own. Used during Start Recording / Live Test."
                    : "Tip: add a Proxy Provider in Settings › Proxy Providers for one-click fresh proxies. Or paste your own proxy URL."}
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Describe the flow <span className="text-zinc-500">(English / Urdu / mixed — be specific about consent boxes, popups, submit button text)</span>
                </label>
                <textarea
                  value={aiDescription}
                  onChange={(e) => setAiDescription(e.target.value)}
                  rows={4}
                  placeholder="Example: Click 'Get Started' → fill First Name, Last Name, Email, Zip → check Terms checkbox → click Submit → wait for thank-you page."
                  className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-purple-500 focus:outline-none resize-none"
                  data-testid="vr-ai-description"
                />
              </div>

              {headers && headers.length > 0 && (
                <div className="text-xs text-emerald-300 bg-emerald-950/30 border border-emerald-900/40 rounded px-3 py-2">
                  ✓ Using Excel headers from your upload as placeholders: <code className="text-emerald-200">{headers.slice(0, 8).join(", ")}{headers.length > 8 ? "…" : ""}</code>
                </div>
              )}
              {(!headers || !headers.length) && (
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                    Excel/CSV columns <span className="text-zinc-500">(optional, comma-separated — used as placeholders)</span>
                  </label>
                  <input
                    type="text"
                    value={aiExcelCols}
                    onChange={(e) => setAiExcelCols(e.target.value)}
                    placeholder="first, last, email, zip, phone"
                    className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-purple-500 focus:outline-none"
                    data-testid="vr-ai-excel-cols"
                  />
                </div>
              )}

              {aiError && (
                <div className="rounded-md border border-rose-700/50 bg-rose-950/40 px-3 py-2 text-xs text-rose-200" data-testid="vr-ai-error">
                  <div className="font-semibold mb-0.5">AI generation failed</div>
                  <div className="opacity-90">{aiError}</div>
                  <div className="mt-1.5 text-rose-300/80">
                    Tip: open <Link to="/settings" className="underline">Settings → AI Integrations</Link> and verify your provider + API key.
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between pt-2 border-t border-zinc-800">
                <div className="text-[11px] text-zinc-500">
                  Provider is picked from your Settings → AI Integrations. {aiProviderUsed && <>Last used: <span className="text-zinc-300">{aiProviderUsed}</span></>}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => { if (!aiBusy) setAiDialogOpen(false); }}
                    disabled={aiBusy}
                    className="px-3 py-1.5 text-sm text-zinc-400 hover:text-white rounded-md hover:bg-zinc-800"
                    data-testid="vr-ai-cancel-btn"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleAiGenerate}
                    disabled={aiBusy || !aiFiles.length}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-purple-600 hover:bg-purple-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-white text-sm font-medium"
                    data-testid="vr-ai-submit-btn"
                  >
                    {aiBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                    {aiBusy ? "Generating…" : "Generate steps"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}


      {/* 2026-06 — Electron-safe prompt/confirm modal.
          Drives `vrPrompt()` / `vrConfirm()`. See state definition for
          context. Z-index 60 sits above the edit-step drawer (z-50)
          so a prompt opened FROM the edit drawer (e.g. "Find similar"
          fallback path) still shows on top. */}
      {promptModal && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          data-testid="vr-prompt-modal-backdrop"
        >
          <div
            className="bg-zinc-950 border border-zinc-700 rounded-lg shadow-2xl w-full max-w-md mx-4 p-5"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-prompt-modal"
          >
            <div className="text-sm text-zinc-100 whitespace-pre-wrap mb-4 leading-relaxed">
              {promptModal.message}
            </div>
            {promptModal.kind === "prompt" && (
              <input
                type="text"
                autoFocus
                defaultValue={promptModal.defaultValue}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const v = e.currentTarget.value;
                    const r = promptModal.resolve;
                    setPromptModal(null);
                    r(v);
                  } else if (e.key === "Escape") {
                    const r = promptModal.resolve;
                    setPromptModal(null);
                    r(null);
                  }
                }}
                className="w-full px-3 py-2 mb-4 rounded bg-zinc-900 border border-zinc-700 focus:border-emerald-500 text-zinc-100 text-sm outline-none font-mono"
                data-testid="vr-prompt-input"
                id="vr-prompt-input-field"
              />
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  const r = promptModal.resolve;
                  setPromptModal(null);
                  r(promptModal.kind === "confirm" ? false : null);
                }}
                className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs border border-zinc-700"
                data-testid="vr-prompt-cancel"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (promptModal.kind === "confirm") {
                    const r = promptModal.resolve;
                    setPromptModal(null);
                    r(true);
                  } else {
                    const input = document.getElementById("vr-prompt-input-field");
                    const v = input ? input.value : promptModal.defaultValue;
                    const r = promptModal.resolve;
                    setPromptModal(null);
                    r(v);
                  }
                }}
                className="px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 text-white text-xs border border-emerald-500/40"
                data-testid="vr-prompt-ok"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}

      {editingStep && (
        <div
          className="fixed inset-0 z-50 flex items-stretch justify-end pointer-events-none"
          data-testid="vr-edit-modal-backdrop"
        >
          {/* Transparent click-catcher (close on outside click) — does NOT
              blur the page so the live screenshot stays visible for
              hover-preview. */}
          <div
            className="absolute inset-0 pointer-events-auto bg-black/10"
            onClick={cancelEditStep}
          />
          <div
            className="relative w-full max-w-md bg-zinc-950/95 border-l border-zinc-800 shadow-2xl backdrop-blur-md pointer-events-auto flex flex-col"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-edit-modal"
          >
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Pencil className="w-4 h-4 text-amber-400" />
                <h3 className="text-sm font-semibold text-zinc-100">
                  Edit Step #{editingStep.index + 1}
                </h3>
                <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 text-[10px] font-mono uppercase">
                  {editingStep.draft.action || "step"}
                </span>
              </div>
              <button
                onClick={cancelEditStep}
                className="p-1 text-zinc-500 hover:text-zinc-200"
                data-testid="vr-edit-modal-close"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 space-y-3 flex-1 overflow-y-auto">
              {/* Name (label) */}
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">
                  Step name (label only)
                </label>
                <input
                  type="text"
                  value={editingStep.draft.name}
                  onChange={(e) =>
                    setEditingStep({
                      ...editingStep,
                      draft: { ...editingStep.draft, name: e.target.value },
                    })
                  }
                  placeholder={editingStep.draft.action}
                  className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs outline-none"
                  data-testid="vr-edit-name"
                />
              </div>

              {/* Selector — shown for all element-targeted actions */}
              {!["wait", "goto"].includes(
                (editingStep.draft.action || "").toLowerCase()
              ) && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-[11px] text-zinc-400">
                      Selector{" "}
                      <span className="text-zinc-600">
                        (CSS or XPath — e.g. <code>#birth_month</code>,{" "}
                        <code>{`//input[@name="month"]`}</code>)
                      </span>
                    </label>
                    <button
                      type="button"
                      onClick={fetchSelectorSuggestions}
                      disabled={selectorSuggest.loading}
                      className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-emerald-700/30 hover:bg-emerald-700/50 border border-emerald-600/40 text-emerald-200 disabled:opacity-50"
                      title="Scan the live page for elements that look like what you meant"
                      data-testid="vr-edit-suggest-btn"
                    >
                      {selectorSuggest.loading ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Sparkles className="w-3 h-3" />
                      )}
                      Find similar
                    </button>
                  </div>
                  <input
                    type="text"
                    value={editingStep.draft.selector}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, selector: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs font-mono outline-none"
                    data-testid="vr-edit-selector"
                  />
                  {/* XPath — dedicated field (CSS selector ke neeche) */}
                  <div className="mt-2">
                    <label className="block text-[11px] text-zinc-400 mb-1">
                      XPath{" "}
                      <span className="text-zinc-600">
                        (stable path — e.g. <code>{`//button[@id="cpa_linkout_btn"]`}</code>)
                      </span>
                    </label>
                    <input
                      type="text"
                      value={editingStep.draft.xpath || ""}
                      onChange={(e) =>
                        setEditingStep({
                          ...editingStep,
                          draft: { ...editingStep.draft, xpath: e.target.value },
                        })
                      }
                      placeholder='//button[@id="cpa_linkout_btn"]'
                      className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none"
                      data-testid="vr-edit-xpath"
                    />
                  </div>
                  {/* Suggestions panel */}
                  {selectorSuggest.items !== null && (
                    <div className="mt-2 rounded border border-emerald-700/30 bg-emerald-950/20 p-2">
                      <div className="text-[10px] text-emerald-300/80 font-medium mb-1.5 flex items-center gap-1">
                        <Sparkles className="w-3 h-3" />
                        Smart Selector Suggestions
                        {selectorSuggest.items.length > 0 && (
                          <span className="text-zinc-500">({selectorSuggest.items.length} matches)</span>
                        )}
                      </div>
                      {selectorSuggest.error && (
                        <div className="text-[11px] text-amber-400 mb-1">{selectorSuggest.error}</div>
                      )}
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {selectorSuggest.items.map((s, k) => (
                          <button
                            type="button"
                            key={k}
                            onClick={() => applySuggestion(s.selector)}
                            onMouseEnter={() => showSelectorPreview(s.selector)}
                            onMouseLeave={clearSelectorPreview}
                            onFocus={() => showSelectorPreview(s.selector)}
                            onBlur={clearSelectorPreview}
                            className="w-full text-left p-1.5 rounded bg-zinc-900/80 hover:bg-emerald-900/40 border border-zinc-800 hover:border-emerald-600/40 transition-colors group"
                            data-testid={`vr-edit-suggest-item-${k}`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <code className="text-[11px] text-emerald-300 font-mono truncate">
                                {s.selector}
                              </code>
                              <span className="text-[9px] px-1 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 uppercase font-mono shrink-0">
                                {s.tag}
                                {s.input_type ? `[${s.input_type}]` : ""}
                              </span>
                            </div>
                            <div className="text-[10px] text-zinc-500 mt-0.5 truncate">
                              {s.label && <span className="text-zinc-300">{s.label}</span>}
                              {s.placeholder && !s.label && (
                                <span>placeholder: {s.placeholder}</span>
                              )}
                              {(s.matched_tokens || []).length > 0 && (
                                <span className="ml-2 text-emerald-400/70">
                                  ✓ {(s.matched_tokens || []).join(", ")}
                                </span>
                              )}
                              {!s.visible && (
                                <span className="ml-2 text-amber-500/70">hidden</span>
                              )}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Value — for fill / type / select / goto */}
              {["fill", "type", "select", "goto"].includes(
                (editingStep.draft.action || "").toLowerCase()
              ) && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Value{" "}
                    <span className="text-zinc-600">
                      (supports <code>{"{{header}}"}</code> placeholders)
                    </span>
                  </label>
                  <input
                    type="text"
                    value={editingStep.draft.value}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, value: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs font-mono outline-none"
                    data-testid="vr-edit-value"
                  />
                </div>
              )}

              {/* Key — for press action */}
              {(editingStep.draft.action || "").toLowerCase() === "press" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Key{" "}
                    <span className="text-zinc-600">
                      (Enter, Tab, Escape, ArrowDown, etc.)
                    </span>
                  </label>
                  <input
                    type="text"
                    value={editingStep.draft.key}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, key: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs font-mono outline-none"
                    data-testid="vr-edit-key"
                  />
                </div>
              )}

              {/* Timeout — shown for everything except plain "wait" */}
              {(editingStep.draft.action || "").toLowerCase() !== "wait" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Timeout{" "}
                    <span className="text-zinc-600">
                      (ms — e.g. 8000. Bump this if the element appears slowly.)
                    </span>
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="500"
                    value={editingStep.draft.timeout}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, timeout: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-edit-timeout"
                  />
                </div>
              )}

              {/* ms — for "wait" action */}
              {(editingStep.draft.action || "").toLowerCase() === "wait" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Wait duration (ms)
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="100"
                    value={editingStep.draft.ms}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, ms: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-edit-ms"
                  />
                </div>
              )}

              {/* State — for wait_for_selector */}
              {(editingStep.draft.action || "").toLowerCase() ===
                "wait_for_selector" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    State
                  </label>
                  <select
                    value={editingStep.draft.state || "visible"}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, state: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-edit-state"
                  >
                    <option value="visible">visible (default)</option>
                    <option value="attached">attached (DOM only, may be hidden)</option>
                    <option value="hidden">hidden</option>
                    <option value="detached">detached</option>
                  </select>
                </div>
              )}

              {/* match_by — for select action */}
              {(editingStep.draft.action || "").toLowerCase() === "select" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Match by
                  </label>
                  <select
                    value={editingStep.draft.match_by || "label"}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, match_by: e.target.value },
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-amber-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-edit-match-by"
                  >
                    <option value="label">label (visible text)</option>
                    <option value="value">value (HTML value attr)</option>
                    <option value="index">index (0-based)</option>
                  </select>
                </div>
              )}

              {/* Humanize toggle — for fill / type only */}
              {["fill", "type"].includes(
                (editingStep.draft.action || "").toLowerCase()
              ) && (
                <div className="p-2.5 rounded bg-zinc-900/60 border border-zinc-800">
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={editingStep.draft.humanize}
                      onChange={(e) =>
                        setEditingStep({
                          ...editingStep,
                          draft: {
                            ...editingStep.draft,
                            humanize: e.target.checked,
                          },
                        })
                      }
                      className="mt-0.5 w-3.5 h-3.5 accent-emerald-500"
                      data-testid="vr-edit-humanize"
                    />
                    <div className="flex-1">
                      <div className="text-xs text-zinc-200 font-medium">
                        Human-like typing
                        <span className="ml-1 text-emerald-400 text-[10px]">
                          (anti-detect — default)
                        </span>
                      </div>
                      <div className="text-[11px] text-zinc-500 mt-0.5">
                        Types character-by-character with realistic
                        delays (~50-180ms each + thinking pauses).
                        Uncheck for fast <code>page.fill()</code> — useful
                        for debugging or internal forms where speed
                        matters more than stealth.
                      </div>
                    </div>
                  </label>
                </div>
              )}

              {/* ── 2026-05: Random-pick advanced editor ─────────────
                  Shows ONLY for `evaluate` steps that have parseable
                  random-pick options (either step.pick_options or
                  legacy `var labels=[...]` in script). Lets the operator
                  add a CSS selector + XPath alongside each option's
                  visible text — RUT replay tries them in order so
                  random picks survive selector renames or text edits. */}
              {(editingStep.draft.action || "").toLowerCase() === "evaluate"
                && Array.isArray(editingStep.draft.pickOptions)
                && editingStep.draft.pickOptions.length > 0 && (
                <details
                  className="rounded border border-violet-900/60 bg-violet-950/20"
                  open={true}
                  data-testid="vr-edit-pick-options-details"
                >
                  <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-violet-200 hover:bg-violet-900/30 transition-colors">
                    <span className="inline-flex items-center gap-1.5">
                      <Shuffle className="w-3.5 h-3.5" />
                      Random-pick options ({editingStep.draft.pickOptions.length})
                      <span className="text-[10px] text-violet-400/70 font-normal">
                        — each option can have selector + xpath fallback
                      </span>
                    </span>
                  </summary>
                  <div className="px-3 pb-3 pt-1 space-y-2.5">
                    <div className="text-[11px] text-zinc-400 leading-relaxed">
                      Pick one at random per visit. For each option you can add a CSS selector + XPath — RUT tries selector → xpath → text-contains in order.
                    </div>
                    {editingStep.draft.pickOptions.map((opt, oi) => (
                      <div key={oi} className="rounded border border-violet-900/40 bg-zinc-900/60 p-2 space-y-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-violet-300/70 font-mono">#{oi + 1}</span>
                          <input
                            type="text"
                            value={opt.text}
                            onChange={(e) => {
                              const arr = [...editingStep.draft.pickOptions];
                              arr[oi] = { ...arr[oi], text: e.target.value };
                              setEditingStep({ ...editingStep, draft: { ...editingStep.draft, pickOptions: arr, pickOptionsEdited: true } });
                            }}
                            placeholder="Visible text (e.g. Yes / Continue / California)"
                            className="flex-1 px-2 py-1 rounded bg-zinc-900 border border-zinc-700 focus:border-violet-500 text-zinc-200 text-xs outline-none"
                            data-testid={`vr-edit-pickopt-text-${oi}`}
                          />
                          <button
                            onClick={() => {
                              const arr = editingStep.draft.pickOptions.filter((_, i) => i !== oi);
                              setEditingStep({ ...editingStep, draft: { ...editingStep.draft, pickOptions: arr, pickOptionsEdited: true } });
                            }}
                            className="text-rose-400 hover:text-rose-200 text-xs px-1.5 py-0.5 rounded hover:bg-rose-900/30"
                            title="Remove this option"
                            data-testid={`vr-edit-pickopt-remove-${oi}`}
                          >
                            ×
                          </button>
                        </div>
                        <input
                          type="text"
                          value={opt.selector}
                          onChange={(e) => {
                            const arr = [...editingStep.draft.pickOptions];
                            arr[oi] = { ...arr[oi], selector: e.target.value };
                            setEditingStep({ ...editingStep, draft: { ...editingStep.draft, pickOptions: arr, pickOptionsEdited: true } });
                          }}
                          placeholder="CSS selector (optional, e.g. #yes-btn or button.cta)"
                          className="w-full px-2 py-1 rounded bg-zinc-900 border border-zinc-700 focus:border-violet-500 text-zinc-200 text-xs font-mono outline-none"
                          data-testid={`vr-edit-pickopt-selector-${oi}`}
                        />
                        <input
                          type="text"
                          value={opt.xpath}
                          onChange={(e) => {
                            const arr = [...editingStep.draft.pickOptions];
                            arr[oi] = { ...arr[oi], xpath: e.target.value };
                            setEditingStep({ ...editingStep, draft: { ...editingStep.draft, pickOptions: arr, pickOptionsEdited: true } });
                          }}
                          placeholder="XPath (optional, e.g. //button[@data-value='yes'])"
                          className="w-full px-2 py-1 rounded bg-zinc-900 border border-zinc-700 focus:border-violet-500 text-zinc-200 text-xs font-mono outline-none"
                          data-testid={`vr-edit-pickopt-xpath-${oi}`}
                        />
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => {
                        const arr = [...editingStep.draft.pickOptions, { text: "", selector: "", xpath: "" }];
                        setEditingStep({ ...editingStep, draft: { ...editingStep.draft, pickOptions: arr, pickOptionsEdited: true } });
                      }}
                      className="w-full py-1.5 rounded border border-dashed border-violet-700/50 text-violet-300 text-xs hover:bg-violet-900/30 hover:border-violet-500 transition-colors"
                      data-testid="vr-edit-pickopt-add"
                    >
                      + Add option
                    </button>
                    {editingStep.draft.pickOptionsEdited && (
                      <div className="text-[10px] text-violet-300/80">
                        ✓ Options will be saved when you click "Save" — script will be rebuilt with new fallback chain.
                      </div>
                    )}
                  </div>
                </details>
              )}

              {/* ── 2026-05: Manual Fallback Strategies editor ─────────
                  When the recording captured only a brittle CSS selector
                  (or no fallbacks at all), user can paste xpath / text /
                  attrs here. RUT replay will then try ALL of these in
                  order if the primary selector misses — same rescue
                  pipeline the auto-capture path uses. Surfaces ONLY
                  for element-targeted actions; hidden on action types
                  that have no selector (wait/goto/scroll) or that use
                  pure JavaScript matching (evaluate/random-pick). */}
              {!["wait", "goto", "wait_for_load", "scroll", "evaluate", "screenshot", "close", "dismiss_popups"].includes(
                (editingStep.draft.action || "").toLowerCase()
              ) && (
                <details
                  className="rounded border border-sky-900/60 bg-sky-950/20 group"
                  open={!!(editingStep.draft.fb_xpath || editingStep.draft.fb_text || editingStep.draft.fb_tag || editingStep.draft.fb_attrs_text)}
                  data-testid="vr-edit-fallbacks-details"
                >
                  <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-sky-200 hover:bg-sky-900/30 transition-colors">
                    <span className="inline-flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5" />
                      Fallback Strategies
                      <span className="text-[10px] text-sky-400/70 font-normal">
                        (xpath · text · attrs — RUT tries these when selector misses)
                      </span>
                    </span>
                  </summary>
                  <div className="px-3 pb-3 pt-1 space-y-2.5">
                    <div className="text-[11px] text-zinc-400 leading-relaxed">
                      Agar selector kabhi miss ho jaye ya page id/name change kar de, RUT in fallbacks ko try karega: xpath → attrs → text. Sab optional hain — jo bharo wahi use hoga.
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-400 mb-1">
                        XPath{" "}
                        <span className="text-zinc-600">(e.g. <code>{`//button[@id='submit']`}</code>)</span>
                      </label>
                      <input
                        type="text"
                        value={editingStep.draft.fb_xpath}
                        onChange={(e) =>
                          setEditingStep({
                            ...editingStep,
                            draft: { ...editingStep.draft, fb_xpath: e.target.value, fallbacksEdited: true },
                          })
                        }
                        placeholder="//button[@id='submit']  OR  //*[@data-testid='cta']"
                        className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none"
                        data-testid="vr-edit-fb-xpath"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-400 mb-1">
                        Visible Text{" "}
                        <span className="text-zinc-600">(button label / link text)</span>
                      </label>
                      <input
                        type="text"
                        value={editingStep.draft.fb_text}
                        onChange={(e) =>
                          setEditingStep({
                            ...editingStep,
                            draft: { ...editingStep.draft, fb_text: e.target.value, fallbacksEdited: true },
                          })
                        }
                        placeholder="Continue  /  Submit  /  Next →"
                        className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                        data-testid="vr-edit-fb-text"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[11px] text-zinc-400 mb-1">
                          Tag <span className="text-zinc-600">(scopes text match)</span>
                        </label>
                        <input
                          type="text"
                          value={editingStep.draft.fb_tag}
                          onChange={(e) =>
                            setEditingStep({
                              ...editingStep,
                              draft: { ...editingStep.draft, fb_tag: e.target.value, fallbacksEdited: true },
                            })
                          }
                          placeholder="button / input / a / select"
                          className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none lowercase"
                          data-testid="vr-edit-fb-tag"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-400 mb-1">
                        Attributes{" "}
                        <span className="text-zinc-600">(one per line, <code>key: value</code>)</span>
                      </label>
                      <textarea
                        value={editingStep.draft.fb_attrs_text}
                        onChange={(e) =>
                          setEditingStep({
                            ...editingStep,
                            draft: { ...editingStep.draft, fb_attrs_text: e.target.value, fallbacksEdited: true },
                          })
                        }
                        placeholder={`id: submit-btn\nname: submit\ndata-testid: cta\naria-label: Continue to next step`}
                        rows={4}
                        className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none resize-y"
                        data-testid="vr-edit-fb-attrs"
                      />
                      <div className="text-[10px] text-zinc-500 mt-1">
                        Useful keys: <code>id</code>, <code>name</code>, <code>data-testid</code>, <code>aria-label</code>, <code>placeholder</code>, <code>role</code>, <code>type</code>, <code>autocomplete</code>, <code>title</code>
                      </div>
                    </div>
                    {editingStep.draft.fallbacksEdited && (
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-sky-300/80">
                          ✓ Fallbacks will be saved when you click "Save"
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setEditingStep({
                              ...editingStep,
                              draft: {
                                ...editingStep.draft,
                                fb_xpath: "",
                                fb_text: "",
                                fb_tag: "",
                                fb_attrs_text: "",
                                fallbacksEdited: true,
                              },
                            })
                          }
                          className="text-[10px] text-rose-300 hover:text-rose-200 hover:underline"
                          data-testid="vr-edit-fb-clear"
                        >
                          Clear all fallbacks
                        </button>
                      </div>
                    )}
                  </div>
                </details>
              )}

              <div className="flex flex-wrap gap-4 pt-3 mt-2 border-t border-zinc-800/80">
                <label className="inline-flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!editingStep.draft.optional}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, optional: e.target.checked },
                      })
                    }
                    data-testid="vr-edit-optional"
                  />
                  optional (RUT skip on failure)
                </label>
                <label className="inline-flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!editingStep.draft.never_strict}
                    onChange={(e) =>
                      setEditingStep({
                        ...editingStep,
                        draft: { ...editingStep.draft, never_strict: e.target.checked },
                      })
                    }
                    data-testid="vr-edit-never-strict"
                  />
                  never_strict (keep optional in strict mode)
                </label>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 p-4 border-t border-zinc-800">
              <button
                onClick={cancelEditStep}
                className="px-4 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
                data-testid="vr-edit-cancel"
              >
                Cancel
              </button>
              <button
                onClick={saveEditStep}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium"
                data-testid="vr-edit-save"
              >
                <Save className="w-3.5 h-3.5" /> Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {finalizeChecklistOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onClick={() => setFinalizeChecklistOpen(false)}
          data-testid="vr-finalize-checklist-backdrop"
        >
          <div
            className="w-full max-w-md bg-zinc-950 border border-zinc-700 rounded-xl shadow-2xl p-5"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-finalize-checklist"
          >
            <h3 className="text-lg font-semibold text-zinc-100 mb-3">Finalize checklist</h3>
            <ul className="text-sm text-zinc-300 space-y-2 mb-4 list-disc list-inside">
              <li>{steps.length} steps recorded</li>
              <li>Live Test (RUT parity) run kiya? {liveTestResult?.ok && liveTestResult?.rut_parity ? "✓" : "—"}</li>
              <li>
                Unsupported steps:{" "}
                {steps.filter((s) =>
                  ["pause_for_human", "otp_wait", "wait_for_otp", "captcha_pause"].includes(
                    (s?.action || "").toLowerCase(),
                  ),
                ).length || "none"}
              </li>
            </ul>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setFinalizeChecklistOpen(false)}
                className="px-3 py-1.5 rounded bg-zinc-800 text-zinc-300 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => runLiveTest({ rutParity: true })}
                className="px-3 py-1.5 rounded bg-blue-700 text-white text-sm"
              >
                Run RUT test first
              </button>
              <button
                type="button"
                onClick={finalize}
                className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm font-medium"
                data-testid="vr-finalize-confirm"
              >
                Mark Final
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 2026-06 — Switch-to-Tab Picker Modal ───────────────────────
          Opened by the "Switch to Tab" button above the live preview.
          Shows EVERY open Chromium tab with title + URL so the operator
          can confidently pick one without confusion. Clicking a row
          calls switchTab(index) which also RECORDS the switch_tab step
          server-side (visual_recorder.switch_tab does the bookkeeping)
          so RUT replay can faithfully reproduce the manual navigation.
          ─────────────────────────────────────────────────────────── */}
      {showTabPicker && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onClick={() => setShowTabPicker(false)}
          data-testid="vr-tab-picker-backdrop"
        >
          <div
            className="w-full max-w-xl bg-zinc-950 border border-zinc-800 rounded-xl shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-tab-picker-modal"
          >
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <ArrowLeftRight className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-semibold text-zinc-100">
                  Switch to Tab
                </h3>
                <span className="text-[11px] text-zinc-500">
                  ({tabs.length} open)
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowTabPicker(false)}
                className="p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
                data-testid="vr-tab-picker-close"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>

            <div className="p-3 max-h-[60vh] overflow-y-auto space-y-1.5">
              {tabs.length === 0 ? (
                <div className="text-center text-zinc-500 text-xs py-8">
                  No tabs open yet. Start a recording to see the live tab list here.
                </div>
              ) : (
                tabs.map((t) => {
                  const isActive = t.is_active || t.index === activeTabIndex;
                  let domain = "";
                  try {
                    domain = t.url ? new URL(t.url).hostname.replace(/^www\./, "") : "";
                  } catch {
                    /* ignore */
                  }
                  const label = (t.title && t.title !== t.url ? t.title : domain) || `Tab ${t.index + 1}`;
                  return (
                    <button
                      key={t.index}
                      type="button"
                      onClick={() => {
                        switchTab(t.index);
                        setShowTabPicker(false);
                      }}
                      data-testid={`vr-tab-picker-item-${t.index}`}
                      className={`w-full text-left p-2.5 rounded-lg border transition-colors flex items-start gap-2.5 ${
                        isActive
                          ? "bg-emerald-600/15 border-emerald-500/50 hover:bg-emerald-600/25"
                          : "bg-zinc-900 border-zinc-800 hover:bg-zinc-800 hover:border-zinc-700"
                      }`}
                    >
                      <div
                        className={`mt-0.5 w-6 h-6 rounded-md flex items-center justify-center text-[11px] font-bold shrink-0 ${
                          isActive ? "bg-emerald-500 text-zinc-950" : "bg-zinc-700 text-zinc-300"
                        }`}
                      >
                        {t.index}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <Globe className="w-3 h-3 shrink-0 opacity-60 text-zinc-400" />
                          <span
                            className={`text-xs font-medium truncate ${
                              isActive ? "text-emerald-200" : "text-zinc-200"
                            }`}
                          >
                            {label}
                          </span>
                          {isActive && (
                            <span className="ml-1 px-1.5 py-0 rounded-full bg-emerald-500/30 text-emerald-100 text-[9px] uppercase tracking-wide font-semibold">
                              Active
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-zinc-500 mt-0.5 truncate">
                          {t.url || "(no url)"}
                        </div>
                      </div>
                      {!isActive && (
                        <span className="self-center text-[10px] text-blue-400 shrink-0">
                          Switch →
                        </span>
                      )}
                    </button>
                  );
                })
              )}
            </div>

            <div className="px-4 py-3 border-t border-zinc-800 text-[11px] text-zinc-500 leading-relaxed">
              💡 Picking a tab records a <code className="text-blue-300">switch_tab</code> step in the recipe —
              RUT will switch back to the same tab during replay, so multi-deal workflows
              (complete a deal on a popup, return to the listing tab, start the next deal)
              run end-to-end without manual intervention.
            </div>
          </div>
        </div>
      )}


      {/* ── Manual Add Step Modal (2026-01) ───────────────────────────
          Opened by the "+ Add Step" button. Lets the user inject a
          step the auto-recorder didn't capture — supports BOTH CSS
          and XPath selectors. ───────────────────────────────────── */}
      {manualStepDraft && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onClick={cancelManualAddStep}
          data-testid="vr-manual-modal-backdrop"
        >
          <div
            className="w-full max-w-lg bg-zinc-950 border border-zinc-800 rounded-xl shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-manual-modal"
          >
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <ListPlus className="w-4 h-4 text-sky-400" />
                <h3 className="text-sm font-semibold text-zinc-100">
                  Add Manual Step
                </h3>
                <span className="px-1.5 py-0.5 rounded bg-sky-900/40 border border-sky-700/40 text-sky-300 text-[10px] font-mono uppercase">
                  CSS or XPath
                </span>
              </div>
              <button
                onClick={cancelManualAddStep}
                className="p-1 text-zinc-500 hover:text-zinc-200"
                data-testid="vr-manual-close"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
              {/* Action type */}
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">
                  Action type
                </label>
                <select
                  value={manualStepDraft.action}
                  onChange={(e) =>
                    setManualStepDraft({
                      ...manualStepDraft,
                      action: e.target.value,
                    })
                  }
                  className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                  data-testid="vr-manual-action"
                >
                  <option value="wait_for_selector">wait_for_selector — wait until element appears</option>
                  <option value="click">click — click an element</option>
                  <option value="fill">fill — type into input</option>
                  <option value="type">type — slow per-char typing</option>
                  <option value="select">select — choose a &lt;select&gt; option</option>
                  <option value="press">press — keyboard key (Enter / Tab / etc.)</option>
                  <option value="wait">wait — pause for N ms</option>
                  <option value="hover">hover — mouse over element</option>
                  <option value="check">check — tick a checkbox/radio</option>
                  <option value="uncheck">uncheck — untick a checkbox</option>
                  <option value="screenshot">screenshot — capture page state</option>
                  <option value="switch_tab">switch_tab — go back to a prior tab (e.g. start next deal on listing tab)</option>
                  <option value="close_tab">close_tab — close the current tab and fall back to the previous one</option>
                </select>
              </div>

              {/* 2026-06 — Tab-index input (switch_tab / close_tab) */}
              {["switch_tab", "close_tab"].includes(manualStepDraft.action) && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Tab index{" "}
                    <span className="text-zinc-600">
                      (0 = first tab, 1 = second, etc.{" "}
                      {manualStepDraft.action === "close_tab" && "leave blank to close current tab"})
                    </span>
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={manualStepDraft.index ?? ""}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        index: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                    placeholder={manualStepDraft.action === "switch_tab" ? "0" : "(current)"}
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-manual-tab-index"
                  />
                  <div className="text-[10px] text-zinc-500 mt-1">
                    💡 The tab strip above the live preview shows current tabs and their order.
                    Click a tab to record a switch_tab step automatically.
                  </div>
                </div>
              )}

              {/* Step name (optional label) */}
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">
                  Step name <span className="text-zinc-600">(optional label)</span>
                </label>
                <input
                  type="text"
                  value={manualStepDraft.name}
                  onChange={(e) =>
                    setManualStepDraft({ ...manualStepDraft, name: e.target.value })
                  }
                  placeholder={manualStepDraft.action}
                  className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                  data-testid="vr-manual-name"
                />
              </div>

              {/* Selector — for most actions */}
              {!["wait", "switch_tab", "close_tab"].includes(manualStepDraft.action) && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Selector{" "}
                    <span className="text-zinc-600">
                      (CSS like <code>#email</code>, OR XPath like{" "}
                      <code>{`//input[@name="email"]`}</code>)
                    </span>
                  </label>
                  <input
                    type="text"
                    value={manualStepDraft.selector}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        selector: e.target.value,
                      })
                    }
                    placeholder="#email  OR  //input[@name='email']"
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none"
                    data-testid="vr-manual-selector"
                  />
                  <div className="text-[10px] text-zinc-500 mt-1">
                    Playwright auto-detects XPath (starts with <code>//</code> or <code>(</code>).
                    For complex cases, prefix with <code>xpath=</code>.
                  </div>
                </div>
              )}

              {/* Value — for fill / type / select */}
              {["fill", "type", "select"].includes(manualStepDraft.action) && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Value{" "}
                    <span className="text-zinc-600">
                      (supports <code>{"{{header}}"}</code> placeholders)
                    </span>
                  </label>
                  <input
                    type="text"
                    value={manualStepDraft.value}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        value: e.target.value,
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none"
                    data-testid="vr-manual-value"
                  />
                </div>
              )}

              {/* Key — for press */}
              {manualStepDraft.action === "press" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Key
                  </label>
                  <input
                    type="text"
                    value={manualStepDraft.key}
                    onChange={(e) =>
                      setManualStepDraft({ ...manualStepDraft, key: e.target.value })
                    }
                    placeholder="Enter / Tab / Escape / ArrowDown"
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs font-mono outline-none"
                    data-testid="vr-manual-key"
                  />
                </div>
              )}

              {/* Timeout (most actions) */}
              {!["wait", "press"].includes(manualStepDraft.action) && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Timeout (ms)
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="500"
                    value={manualStepDraft.timeout}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        timeout: e.target.value,
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-manual-timeout"
                  />
                </div>
              )}

              {/* ms — for wait */}
              {manualStepDraft.action === "wait" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Wait duration (ms)
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="100"
                    value={manualStepDraft.ms}
                    onChange={(e) =>
                      setManualStepDraft({ ...manualStepDraft, ms: e.target.value })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-manual-ms"
                  />
                </div>
              )}

              {/* State — for wait_for_selector */}
              {manualStepDraft.action === "wait_for_selector" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    State
                  </label>
                  <select
                    value={manualStepDraft.state}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        state: e.target.value,
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-manual-state"
                  >
                    <option value="visible">visible (default)</option>
                    <option value="attached">attached (DOM only)</option>
                    <option value="hidden">hidden</option>
                    <option value="detached">detached</option>
                  </select>
                </div>
              )}

              {/* match_by — for select */}
              {manualStepDraft.action === "select" && (
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">
                    Match by
                  </label>
                  <select
                    value={manualStepDraft.match_by}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        match_by: e.target.value,
                      })
                    }
                    className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                    data-testid="vr-manual-match-by"
                  >
                    <option value="label">label (visible text)</option>
                    <option value="value">value</option>
                    <option value="index">index (0-based)</option>
                  </select>
                </div>
              )}

              {/* humanize for fill / type */}
              {["fill", "type"].includes(manualStepDraft.action) && (
                <label className="flex items-start gap-2 cursor-pointer p-2.5 rounded bg-zinc-900/60 border border-zinc-800">
                  <input
                    type="checkbox"
                    checked={manualStepDraft.humanize}
                    onChange={(e) =>
                      setManualStepDraft({
                        ...manualStepDraft,
                        humanize: e.target.checked,
                      })
                    }
                    className="mt-0.5 w-3.5 h-3.5 accent-emerald-500"
                    data-testid="vr-manual-humanize"
                  />
                  <div className="flex-1">
                    <div className="text-xs text-zinc-200 font-medium">
                      Human-like typing
                      <span className="ml-1 text-emerald-400 text-[10px]">
                        (anti-detect — default)
                      </span>
                    </div>
                    <div className="text-[11px] text-zinc-500 mt-0.5">
                      Uncheck for fast <code>page.fill()</code>.
                    </div>
                  </div>
                </label>
              )}

              {/* Position — where in the steps list to insert */}
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">
                  Insert at position{" "}
                  <span className="text-zinc-600">
                    (leave empty = append to end; 1-based)
                  </span>
                </label>
                <input
                  type="number"
                  min="1"
                  max={steps.length + 1}
                  value={manualStepDraft.position}
                  onChange={(e) =>
                    setManualStepDraft({
                      ...manualStepDraft,
                      position: e.target.value,
                    })
                  }
                  placeholder={`${steps.length + 1} (end)`}
                  className="w-full px-2.5 py-1.5 rounded bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-xs outline-none"
                  data-testid="vr-manual-position"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 p-4 border-t border-zinc-800">
              <button
                onClick={cancelManualAddStep}
                className="px-4 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
                data-testid="vr-manual-cancel"
              >
                Cancel
              </button>
              <button
                onClick={saveManualAddStep}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium"
                data-testid="vr-manual-save"
              >
                <ListPlus className="w-3.5 h-3.5" /> Add Step
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Selector Aliases Panel (2026-01) ──────────────────────────
          Read-only listing of all self-healing rules the user has
          accumulated. Each row shows the original selector + the alias
          chain + per-row hit count + delete button. ─────────────── */}
      {aliasesPanel && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onClick={closeAliasesPanel}
          data-testid="vr-aliases-modal-backdrop"
        >
          <div
            className="w-full max-w-2xl max-h-[80vh] bg-zinc-950 border border-zinc-800 rounded-xl shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
            data-testid="vr-aliases-modal"
          >
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Brain className="w-4 h-4 text-fuchsia-400" />
                <h3 className="text-sm font-semibold text-zinc-100">
                  Self-Healing Selector Aliases
                </h3>
                {aliasesPanel.items && (
                  <span className="px-1.5 py-0.5 rounded bg-fuchsia-900/40 border border-fuchsia-700/40 text-fuchsia-200 text-[10px] font-mono">
                    {aliasesPanel.items.length} rule{aliasesPanel.items.length === 1 ? "" : "s"}
                  </span>
                )}
              </div>
              <button
                onClick={closeAliasesPanel}
                className="p-1 text-zinc-500 hover:text-zinc-200"
                data-testid="vr-aliases-close"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto">
              <div className="text-[11px] text-zinc-500 mb-3 leading-relaxed">
                Every time you fix a wrong selector via the Edit modal,
                Krexion saves the mapping below. Future Live Tests and
                RUT jobs on the same website silently try these aliases
                when the original selector fails — so your recordings
                keep working even after the site renames its form fields.
              </div>
              {aliasesPanel.loading && (
                <div className="flex items-center justify-center py-6 text-zinc-500 text-xs gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" /> Loading aliases…
                </div>
              )}
              {!aliasesPanel.loading && aliasesPanel.error && (
                <div className="p-3 rounded border border-rose-700/40 bg-rose-950/30 text-rose-300 text-xs">
                  {aliasesPanel.error}
                </div>
              )}
              {!aliasesPanel.loading &&
                !aliasesPanel.error &&
                aliasesPanel.items.length === 0 && (
                  <div className="text-center py-8 text-zinc-500 text-xs">
                    <Brain className="w-10 h-10 mx-auto mb-2 text-zinc-700" />
                    No aliases yet. They are saved automatically when you
                    edit a step's selector via the pencil icon.
                  </div>
                )}
              {!aliasesPanel.loading && aliasesPanel.items.length > 0 && (
                <div className="space-y-2">
                  {aliasesPanel.items.map((a) => (
                    <div
                      key={a._id}
                      className="p-2.5 rounded border border-zinc-800 bg-zinc-900/60 hover:border-fuchsia-700/30 transition-colors"
                      data-testid={`vr-alias-row-${a._id}`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <div className="flex items-center gap-2 min-w-0">
                          <Globe className="w-3 h-3 text-emerald-400 shrink-0" />
                          <span className="text-[11px] text-zinc-300 font-mono truncate">
                            {a.domain}
                          </span>
                          {(a.hit_count || 0) > 0 && (
                            <span className="px-1.5 py-0.5 rounded bg-emerald-900/40 border border-emerald-700/40 text-emerald-300 text-[9px] font-mono shrink-0">
                              ✓ {a.hit_count} rescue{a.hit_count === 1 ? "" : "s"}
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => deleteAlias(a.domain, a.original)}
                          title="Delete this alias"
                          className="p-1 text-zinc-500 hover:text-rose-400 shrink-0"
                          data-testid={`vr-alias-delete-${a._id}`}
                        >
                          <Trash className="w-3 h-3" />
                        </button>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap text-[11px] font-mono">
                        <code className="px-1.5 py-0.5 rounded bg-rose-950/50 border border-rose-800/40 text-rose-200">
                          {a.original}
                        </code>
                        <ArrowRight className="w-3 h-3 text-zinc-600" />
                        <div className="flex items-center gap-1 flex-wrap">
                          {(a.aliases || []).map((alt, k) => (
                            <code
                              key={k}
                              className={`px-1.5 py-0.5 rounded ${
                                k === 0
                                  ? "bg-emerald-950/50 border border-emerald-700/40 text-emerald-200"
                                  : "bg-zinc-800/60 border border-zinc-700/40 text-zinc-400"
                              }`}
                              title={k === 0 ? "Most recent — tried first" : `Older alias (#${k + 1})`}
                            >
                              {alt}
                            </code>
                          ))}
                        </div>
                      </div>
                      {a.last_used_at && (
                        <div className="text-[10px] text-zinc-600 mt-1">
                          Last used: {new Date(a.last_used_at).toLocaleString()}
                          {a.last_alias_used && <span className="ml-1 font-mono">via {a.last_alias_used}</span>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 p-4 border-t border-zinc-800">
              <button
                onClick={closeAliasesPanel}
                className="px-4 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs"
                data-testid="vr-aliases-cancel"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
