/* eslint-disable react-hooks/exhaustive-deps */
import { useState, useEffect, useMemo } from "react";
import ProxyProviderSelect from "../components/ProxyProviderSelect";
import ReferrerProProfilePanel, { DEFAULT_PROFILE_REFERRER } from "../components/ReferrerProProfilePanel";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { Textarea } from "../components/ui/textarea";
import { toast } from "sonner";
import {
  Plus,
  Trash2,
  Play,
  StopCircle,
  Copy,
  Download,
  Upload,
  Globe,
  Smartphone,
  Monitor,
  Shield,
  RefreshCw,
  Search,
  Folder,
  Link,
  Cookie,
  MoreVertical,
  LayoutGrid,
  Table2,
  Star,
  RotateCcw,
  ChevronDown,
  Pencil,
  Braces,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/browser-profiles`;
const UPLOADS_API = `${process.env.REACT_APP_BACKEND_URL}/api/uploads`;

const DEFAULT_LAUNCH_AUTO = {
  enabled: false,
  automation_upload_id: "",
  data_file_id: "",
  lead_row_index: 0,
  skip_missing_steps: true,
  self_heal: false,
  save_as_default: false,
  proxy_upload_id: "",
};
const PAGE_SIZE = 50;

const COUNTRY_OPTIONS = [
  "US","GB","CA","AU","DE","FR","ES","IT","NL","BR","MX","IN","PK","BD","ID","PH","JP","KR","TR","AE","SA","ZA","NG","KE","RU","UA","PL","PT","SE","NO","DK","FI",
];

// 2026-06 — Full list of US states/territories for the Proxy State
// dropdown. Customer ask: "proxy state select krne k liye drop down
// select krne ka option ho likhna na pare". Two-letter USPS codes
// (lowercase storage, uppercased on render) match what ProxyJet
// expects. Includes DC + PR + GU + VI so callers who use territories
// for geo-targeting can still pick them. "Any" (empty string) lets
// the proxy provider pick any state in the chosen country.
const US_STATE_OPTIONS = [
  { code: "", name: "Any state" },
  { code: "AL", name: "Alabama" },     { code: "AK", name: "Alaska" },
  { code: "AZ", name: "Arizona" },     { code: "AR", name: "Arkansas" },
  { code: "CA", name: "California" },  { code: "CO", name: "Colorado" },
  { code: "CT", name: "Connecticut" }, { code: "DE", name: "Delaware" },
  { code: "DC", name: "District of Columbia" },
  { code: "FL", name: "Florida" },     { code: "GA", name: "Georgia" },
  { code: "HI", name: "Hawaii" },      { code: "ID", name: "Idaho" },
  { code: "IL", name: "Illinois" },    { code: "IN", name: "Indiana" },
  { code: "IA", name: "Iowa" },        { code: "KS", name: "Kansas" },
  { code: "KY", name: "Kentucky" },    { code: "LA", name: "Louisiana" },
  { code: "ME", name: "Maine" },       { code: "MD", name: "Maryland" },
  { code: "MA", name: "Massachusetts" }, { code: "MI", name: "Michigan" },
  { code: "MN", name: "Minnesota" },   { code: "MS", name: "Mississippi" },
  { code: "MO", name: "Missouri" },    { code: "MT", name: "Montana" },
  { code: "NE", name: "Nebraska" },    { code: "NV", name: "Nevada" },
  { code: "NH", name: "New Hampshire" }, { code: "NJ", name: "New Jersey" },
  { code: "NM", name: "New Mexico" },  { code: "NY", name: "New York" },
  { code: "NC", name: "North Carolina" }, { code: "ND", name: "North Dakota" },
  { code: "OH", name: "Ohio" },        { code: "OK", name: "Oklahoma" },
  { code: "OR", name: "Oregon" },      { code: "PA", name: "Pennsylvania" },
  { code: "PR", name: "Puerto Rico" }, { code: "RI", name: "Rhode Island" },
  { code: "SC", name: "South Carolina" }, { code: "SD", name: "South Dakota" },
  { code: "TN", name: "Tennessee" },   { code: "TX", name: "Texas" },
  { code: "UT", name: "Utah" },        { code: "VT", name: "Vermont" },
  { code: "VA", name: "Virginia" },    { code: "WA", name: "Washington" },
  { code: "WV", name: "West Virginia" }, { code: "WI", name: "Wisconsin" },
  { code: "WY", name: "Wyoming" },
];

const DEFAULT_NEW = {
  name: "",
  notes: "",
  country: "us",
  language: "en-US",
  timezone: "America/New_York",
  device_type: "desktop",
  os: "windows",
  user_agent: "",
  viewport: { width: 1920, height: 1080 },
  is_mobile: false,
  has_touch: false,
  device_scale_factor: 1,
  locale: "en-US",
  accept_language: "en-US,en;q=0.9",
  start_url: "https://www.google.com/",
  tags: [],
  folder: "",
  geo_follow_proxy: true,
  quick_links: [],
  proxy: {
    enabled: false,
    server: "",
    username: "",
    password: "",
    use_proxyjet: false,
    proxyjet_country: "US",
    proxyjet_state: "",
    // v2.4.0 — Selected Proxy Provider (from Settings › Proxy Providers)
    provider_id: "",
  },
  anti_detect: {
    master: true,
    tls_prewarm: true,
    behavioral_bio: true,
    ip_warmup: false,
    browser_variant: "rotate",
    identity_persist: true,
    paranoia_mode: false,
    // v2.7.15 — WIN antidetect bundle (match backend AntiDetectConfig defaults)
    canvas_mode: "noise",
    webgl_mode: "noise",
    audio_mode: "noise",
    font_mode: "noise",
    webrtc_mode: "proxy",
    use_persistent_context: false,
    proxy_check_on_launch: true,
    proxy_check_block_on_fail: false,
    browser_kernel: "auto",
    fingerprint_win: true,
    fingerprint_win_prefer_real: true,
    allow_extensions: false,
    extensions_dir: "",
  },
  referrer: { ...DEFAULT_PROFILE_REFERRER },
};

const CREATE_DRAFT_KEY = "krexion_bp_create_draft_v1";

const ADV_CREATE_DEFAULTS = {
  advCount: 1,
  advNamePrefix: "",
  advUA: { app: "browser", platform: "any", brand: "", region: "US" },
  advProxy: {
    mode: "none",
    country: "US",
    state: "",
    sticky_minutes: 0,
    server: "",
    protocol: "http",
    host: "",
    port: "",
    username: "",
    password: "",
    paste_input: "",
    provider_id: "",
  },
  advAntiDetect: true,
  advMix: { ios: 0, android: 0, desktop: 100 },
  advDeviceMode: "random",
  advDeviceId: "",
  advResolutionMode: "match_device",
  advTags: "",
  advFolder: "",
  advTimezone: "",
  advLocale: "",
  advGeoFollow: true,
  advQuickLinks: "",
  advProxyLines: "",
  showFpAdvanced: false,
};

/** Relative or ISO timestamp for storage_state sync chip */
function formatSyncedAt(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19);
    const sec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (sec < 60) return "just now";
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 604800) return `${Math.floor(sec / 86400)}d ago`;
    return d.toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return String(iso).slice(0, 19);
  }
}

const FP_MODE_OPTIONS = [
  { value: "off", label: "off" },
  { value: "noise", label: "noise" },
  { value: "real", label: "real" },
];

const WEBRTC_MODE_OPTIONS = [
  { value: "disabled", label: "disabled" },
  { value: "proxy", label: "proxy" },
  { value: "real", label: "real" },
];

export default function BrowserProfilesPage() {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(DEFAULT_NEW);
  const [editingId, setEditingId] = useState(null);
  const [statusMap, setStatusMap] = useState({}); // id → status info

  // ── 2026-01 (advanced create) — UA + Proxy generator integration ──
  // Drives the new "New Browser Profile" modal. The form mirrors the
  // /ua-generator + /proxies pages so customers don't have to switch
  // tabs to build a powerful profile. Bulk count + auto-name make it
  // viable to spin up 50 unique profiles in one click.
  const [advCount, setAdvCount] = useState(1);
  const [advNamePrefix, setAdvNamePrefix] = useState("");
  const [advUA, setAdvUA] = useState({
    app: "browser",      // browser | instagram | facebook | tiktok | ...
    platform: "any",     // any | android | ios | desktop
    brand: "",           // optional
    region: "US",
  });
  const [advProxy, setAdvProxy] = useState({
    mode: "none",        // none | manual | proxyjet | provider
    country: "US",
    state: "",
    sticky_minutes: 0,   // 0 = rotating
    // Manual mode (any proxy provider):
    server: "",          // canonical URL: <protocol>://<host>:<port>
    protocol: "http",    // http | https | socks5 | socks5h | socks4
    host: "",
    port: "",
    username: "",
    password: "",
    paste_input: "",     // one-line paste-and-parse buffer
    // v2.4.0 — Selected Proxy Provider (from Settings › Proxy Providers)
    provider_id: "",
  });
  const [advAntiDetect, setAdvAntiDetect] = useState(true);
  const [advCreating, setAdvCreating] = useState(false);
  // v2.7.12 — Mix % + device/resolution + multi-select
  const [advMix, setAdvMix] = useState({ ios: 0, android: 0, desktop: 100 });
  const [advDeviceMode, setAdvDeviceMode] = useState("random"); // random | specific
  const [advDeviceId, setAdvDeviceId] = useState("");
  const [advResolutionMode, setAdvResolutionMode] = useState("match_device"); // match_device | random | exact
  const [deviceCatalog, setDeviceCatalog] = useState([]);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  // v2.7.13 — Agency UX: folders / tags / cookies / share / launch-URL
  const [filterQ, setFilterQ] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [filterFolder, setFilterFolder] = useState(""); // "" | "unsorted" | name
  const [folders, setFolders] = useState([]); // [{name,count}]
  const [foldersUnsorted, setFoldersUnsorted] = useState(0);
  const [proxyBusy, setProxyBusy] = useState(null); // profile id
  const [cookieDialog, setCookieDialog] = useState({ id: null, text: "", open: false });
  const [shareDialog, setShareDialog] = useState({
    id: null, email: "", includeCookies: false, mode: "acl", role: "editor",
  });
  const [syncBusy, setSyncBusy] = useState(false);
  const [activeSyncId, setActiveSyncId] = useState("");
  const [cloudPhoneDialog, setCloudPhoneDialog] = useState({
    id: null, provider: "cpi", partnerUrl: "", deviceId: "", label: "", devices: [], loadingDevices: false,
  });
  const [launchUrlPrompt, setLaunchUrlPrompt] = useState({ id: null, url: "" });
  const [advTags, setAdvTags] = useState("");
  const [advFolder, setAdvFolder] = useState("");
  const [advTimezone, setAdvTimezone] = useState("");
  const [advLocale, setAdvLocale] = useState("");
  const [advGeoFollow, setAdvGeoFollow] = useState(true);
  const [advQuickLinks, setAdvQuickLinks] = useState("");
  const [advProxyLines, setAdvProxyLines] = useState("");
  const [showFpAdvanced, setShowFpAdvanced] = useState(false);
  const [bulkMoveFolder, setBulkMoveFolder] = useState("");
  // v2.7.15 — fingerprint coherence panel + local API docs
  const [fpModal, setFpModal] = useState({ open: false, id: null, loading: false, data: null, error: null });
  const [docsModal, setDocsModal] = useState({ open: false, loading: false, data: null, error: null });
  const [cookieRobotBusy, setCookieRobotBusy] = useState(null);
  const [profileTemplates, setProfileTemplates] = useState([]);
  const [templateBusy, setTemplateBusy] = useState(false);
  // v2.7.76 — Agency UX: sort, view modes, trash, launch checklist, clone opts
  const [viewMode, setViewMode] = useState("cards");
  const [sortBy, setSortBy] = useState("updated_at");
  const [maxConcurrent, setMaxConcurrent] = useState(5);
  const [showTrash, setShowTrash] = useState(false);
  const [launchChecklist, setLaunchChecklist] = useState({ open: false, id: null, data: null, startUrl: undefined });
  const [launchAuto, setLaunchAuto] = useState({ ...DEFAULT_LAUNCH_AUTO });
  const [bulkLaunchAuto, setBulkLaunchAuto] = useState({ ...DEFAULT_LAUNCH_AUTO });
  const [automationUploads, setAutomationUploads] = useState([]);
  const [dataFileUploads, setDataFileUploads] = useState([]);
  const [proxyUploads, setProxyUploads] = useState([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);
  const [runAutoBusy, setRunAutoBusy] = useState(null);
  const [jsonMenuOpen, setJsonMenuOpen] = useState(false);
  const [jsonRunBusy, setJsonRunBusy] = useState(false);
  const [stopAutoBusy, setStopAutoBusy] = useState(null);
  const [cloneDialog, setCloneDialog] = useState({
    open: false, id: null, opts: { include_cookies: false, fresh_proxy: true, fresh_ua: false },
  });
  const [cardMenuId, setCardMenuId] = useState(null);
  // v2.7.77 — pagination, proxy retry
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [proxyRetryBusy, setProxyRetryBusy] = useState(null);

  const authHeaders = useMemo(() => {
    const t = localStorage.getItem("token");
    return { Authorization: `Bearer ${t}`, "Content-Type": "application/json" };
  }, []);

  const fetchFolders = async () => {
    try {
      const r = await fetch(`${API}/folders`, { headers: authHeaders });
      if (!r.ok) return;
      const d = await r.json();
      setFolders(d.folders || []);
      setFoldersUnsorted(d.unsorted || 0);
    } catch (_) { /* folders optional */ }
  };

  const fetchProfiles = async (opts = {}) => {
    const append = !!opts.append;
    const skip = append ? (opts.skip ?? 0) : 0;
    if (append) setLoadingMore(true);
    else setLoading(true);
    try {
      if (showTrash) {
        const r = await fetch(`${API}/trash`, { headers: authHeaders });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        setProfiles(d.profiles || []);
        setHasMore(false);
        return;
      }
      const params = new URLSearchParams();
      params.set("sort", sortBy);
      params.set("limit", String(PAGE_SIZE));
      params.set("skip", String(skip));
      if (filterQ.trim()) params.set("q", filterQ.trim());
      if (filterTag.trim()) params.set("tag", filterTag.trim());
      if (filterFolder) params.set("folder", filterFolder);
      const qs = params.toString();
      const r = await fetch(`${API}/?${qs}`, { headers: authHeaders });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const batch = d.profiles || [];
      setProfiles((prev) => (append ? [...prev, ...batch] : batch));
      setHasMore(!!d.has_more || batch.length >= PAGE_SIZE);
      fetchFolders();
    } catch (e) {
      toast.error(`Failed to load profiles: ${e.message}`);
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  };

  const loadMoreProfiles = () => {
    if (loadingMore || !hasMore || showTrash) return;
    fetchProfiles({ append: true, skip: profiles.length });
  };

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/device-catalog`, { headers: authHeaders });
        if (!r.ok) return;
        const d = await r.json();
        setDeviceCatalog(d.devices || []);
      } catch (_) { /* catalog optional */ }
    })();
  }, []);

  const fetchTemplates = async () => {
    try {
      const r = await fetch(`${API}/templates`, { headers: authHeaders });
      if (!r.ok) return;
      const d = await r.json();
      setProfileTemplates(d.templates || []);
    } catch (_) { /* templates optional */ }
  };

  useEffect(() => {
    fetchTemplates();
    fetchAutomationUploads();
  }, []);

  useEffect(() => {
    if (!jsonMenuOpen) return undefined;
    const close = () => setJsonMenuOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [jsonMenuOpen]);

  const serializeCreateState = () => ({
    form,
    advCount,
    advNamePrefix,
    advUA,
    advProxy,
    advAntiDetect,
    advMix,
    advDeviceMode,
    advDeviceId,
    advResolutionMode,
    advTags,
    advFolder,
    advTimezone,
    advLocale,
    advGeoFollow,
    advQuickLinks,
    advProxyLines,
    showFpAdvanced,
  });

  const applyCreateDraft = (draft) => {
    if (!draft || typeof draft !== "object") return;
    if (draft.form) {
      setForm({
        ...DEFAULT_NEW,
        ...draft.form,
        proxy: { ...DEFAULT_NEW.proxy, ...(draft.form.proxy || {}) },
        anti_detect: { ...DEFAULT_NEW.anti_detect, ...(draft.form.anti_detect || {}) },
        referrer: { ...DEFAULT_NEW.referrer, ...(draft.form.referrer || {}) },
        viewport: draft.form.viewport || DEFAULT_NEW.viewport,
      });
    }
    if (draft.advCount != null) setAdvCount(draft.advCount);
    if (draft.advNamePrefix != null) setAdvNamePrefix(draft.advNamePrefix);
    if (draft.advUA) setAdvUA({ ...ADV_CREATE_DEFAULTS.advUA, ...draft.advUA });
    if (draft.advProxy) setAdvProxy({ ...ADV_CREATE_DEFAULTS.advProxy, ...draft.advProxy });
    if (draft.advAntiDetect != null) setAdvAntiDetect(!!draft.advAntiDetect);
    if (draft.advMix) setAdvMix({ ...ADV_CREATE_DEFAULTS.advMix, ...draft.advMix });
    if (draft.advDeviceMode) setAdvDeviceMode(draft.advDeviceMode);
    if (draft.advDeviceId != null) setAdvDeviceId(draft.advDeviceId);
    if (draft.advResolutionMode) setAdvResolutionMode(draft.advResolutionMode);
    if (draft.advTags != null) setAdvTags(draft.advTags);
    if (draft.advFolder != null) setAdvFolder(draft.advFolder);
    if (draft.advTimezone != null) setAdvTimezone(draft.advTimezone);
    if (draft.advLocale != null) setAdvLocale(draft.advLocale);
    if (draft.advGeoFollow != null) setAdvGeoFollow(!!draft.advGeoFollow);
    if (draft.advQuickLinks != null) setAdvQuickLinks(draft.advQuickLinks);
    if (draft.advProxyLines != null) setAdvProxyLines(draft.advProxyLines);
    if (draft.showFpAdvanced != null) setShowFpAdvanced(!!draft.showFpAdvanced);
  };

  const resetAdvCreateForm = () => {
    setForm(DEFAULT_NEW);
    setAdvCount(ADV_CREATE_DEFAULTS.advCount);
    setAdvNamePrefix(ADV_CREATE_DEFAULTS.advNamePrefix);
    setAdvUA({ ...ADV_CREATE_DEFAULTS.advUA });
    setAdvProxy({ ...ADV_CREATE_DEFAULTS.advProxy });
    setAdvAntiDetect(ADV_CREATE_DEFAULTS.advAntiDetect);
    setAdvMix({ ...ADV_CREATE_DEFAULTS.advMix });
    setAdvDeviceMode(ADV_CREATE_DEFAULTS.advDeviceMode);
    setAdvDeviceId(ADV_CREATE_DEFAULTS.advDeviceId);
    setAdvResolutionMode(ADV_CREATE_DEFAULTS.advResolutionMode);
    setAdvTags(ADV_CREATE_DEFAULTS.advTags);
    setAdvFolder(ADV_CREATE_DEFAULTS.advFolder);
    setAdvTimezone(ADV_CREATE_DEFAULTS.advTimezone);
    setAdvLocale(ADV_CREATE_DEFAULTS.advLocale);
    setAdvGeoFollow(ADV_CREATE_DEFAULTS.advGeoFollow);
    setAdvQuickLinks(ADV_CREATE_DEFAULTS.advQuickLinks);
    setAdvProxyLines(ADV_CREATE_DEFAULTS.advProxyLines);
    setShowFpAdvanced(ADV_CREATE_DEFAULTS.showFpAdvanced);
  };

  const openCustomProfileModal = async () => {
    setEditingId(null);
    setShowFpAdvanced(false);
    try {
      const raw = sessionStorage.getItem(CREATE_DRAFT_KEY);
      if (raw) {
        applyCreateDraft(JSON.parse(raw));
      } else {
        try {
          const r = await fetch(`${API}/templates/default`, { headers: authHeaders });
          if (r.ok) {
            const d = await r.json();
            if (d.template?.settings) {
              applyCreateDraft(d.template.settings);
            } else {
              resetAdvCreateForm();
            }
          } else {
            resetAdvCreateForm();
          }
        } catch {
          resetAdvCreateForm();
        }
      }
    } catch {
      resetAdvCreateForm();
    }
    setShowCreate(true);
  };

  const closeCreateModal = (clearDraft = true) => {
    setShowCreate(false);
    setEditingId(null);
    if (clearDraft) {
      try { sessionStorage.removeItem(CREATE_DRAFT_KEY); } catch (_) { /* ignore */ }
    }
  };

  const applyProfileTemplate = (settings) => {
    applyCreateDraft(settings);
    toast.success("Template applied — adjust name/count then create");
  };

  const saveProfileTemplate = async () => {
    const name = window.prompt("Template name (save current settings):");
    if (!name || !name.trim()) return;
    setTemplateBusy(true);
    try {
      const r = await fetch(`${API}/templates`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ name: name.trim().slice(0, 80), settings: serializeCreateState() }),
      });
      if (!r.ok) {
        const t = await r.text();
        let msg = t;
        try { msg = JSON.parse(t).detail || t; } catch {}
        throw new Error(msg);
      }
      toast.success(`Template "${name.trim()}" saved`);
      fetchTemplates();
    } catch (e) {
      toast.error(`Save template failed: ${e.message}`);
    } finally {
      setTemplateBusy(false);
    }
  };

  const deleteProfileTemplate = async (templateId, templateName) => {
    if (!window.confirm(`Delete template "${templateName}"?`)) return;
    try {
      const r = await fetch(`${API}/templates/${templateId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Template deleted");
      fetchTemplates();
    } catch (e) {
      toast.error(`Delete failed: ${e.message}`);
    }
  };

  const updateProfileTemplate = async (templateId, templateName) => {
    const overwrite = window.confirm(
      `Overwrite template "${templateName}" with current form settings?`,
    );
    if (!overwrite) return;
    const rename = window.prompt("Template name (leave blank to keep current):", templateName);
    if (rename === null) return;
    setTemplateBusy(true);
    try {
      const body = { settings: serializeCreateState() };
      if (rename.trim()) body.name = rename.trim().slice(0, 80);
      const r = await fetch(`${API}/templates/${templateId}`, {
        method: "PUT",
        headers: authHeaders,
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        let msg = t;
        try { msg = JSON.parse(t).detail || t; } catch {}
        throw new Error(msg);
      }
      toast.success(`Template "${rename.trim() || templateName}" updated`);
      fetchTemplates();
    } catch (e) {
      toast.error(`Update template failed: ${e.message}`);
    } finally {
      setTemplateBusy(false);
    }
  };

  const setDefaultTemplate = async (templateId) => {
    try {
      const r = await fetch(`${API}/templates/${templateId}/default`, {
        method: "POST",
        headers: authHeaders,
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Default template set");
      fetchTemplates();
    } catch (e) {
      toast.error(`Set default failed: ${e.message}`);
    }
  };

  // Persist create-form draft so accidental refresh / mis-click does not lose settings.
  useEffect(() => {
    if (!showCreate || editingId) return undefined;
    const timer = setTimeout(() => {
      try {
        sessionStorage.setItem(CREATE_DRAFT_KEY, JSON.stringify(serializeCreateState()));
      } catch (_) { /* quota */ }
    }, 400);
    return () => clearTimeout(timer);
  }, [
    showCreate, editingId, form, advCount, advNamePrefix, advUA, advProxy, advAntiDetect,
    advMix, advDeviceMode, advDeviceId, advResolutionMode, advTags, advFolder, advTimezone,
    advLocale, advGeoFollow, advQuickLinks, advProxyLines, showFpAdvanced,
  ]);

  // Re-fetch when filters change (also runs on mount)
  useEffect(() => {
    fetchProfiles();
  }, [filterQ, filterTag, filterFolder, sortBy, showTrash]);

  useEffect(() => {
    if (!cardMenuId) return undefined;
    const close = () => setCardMenuId(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [cardMenuId]);

  const selectedCount = selectedIds.size;
  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const selectAllVisible = () => {
    setSelectedIds(new Set(profiles.map((p) => p.id)));
  };
  const clearSelection = () => setSelectedIds(new Set());

  const normalizeMix = (m) => {
    const ios = Math.max(0, Math.min(100, Number(m.ios) || 0));
    const android = Math.max(0, Math.min(100, Number(m.android) || 0));
    const desktop = Math.max(0, Math.min(100, Number(m.desktop) || 0));
    const sum = ios + android + desktop;
    return { ios, android, desktop, sum };
  };

  // v2.6.32 — Poll while any profile is mid-launch so cloud-bridged cards update.
  useEffect(() => {
    const active = profiles.some((p) =>
      ["launching", "running", "stopping", "queued"].includes(p.status)
    );
    if (!active) return undefined;
    const timer = setInterval(fetchProfiles, 3000);
    return () => clearInterval(timer);
  }, [profiles]);

  const statusBadgeClass = (status) => {
    const s = status || "idle";
    if (s === "running") return "bg-emerald-950/40 border-emerald-700 text-emerald-300";
    if (s === "launching" || s === "queued") return "bg-amber-950/40 border-amber-700 text-amber-300";
    if (s === "stopping") return "bg-orange-950/40 border-orange-700 text-orange-300";
    if (s === "error") return "bg-red-950/40 border-red-700 text-red-300";
    return "bg-zinc-900 border-zinc-700 text-zinc-400";
  };

  const healthBadgeClass = (level) => {
    const l = level || "unknown";
    if (l === "good") return "bg-emerald-950/40 border-emerald-700 text-emerald-300";
    if (l === "warn") return "bg-amber-950/40 border-amber-700 text-amber-300";
    if (l === "bad") return "bg-red-950/40 border-red-700 text-red-300";
    return "bg-zinc-900 border-zinc-700 text-zinc-400";
  };

  const truncateNotes = (notes, max = 80) => {
    if (!notes) return "";
    const s = String(notes).trim();
    return s.length > max ? `${s.slice(0, max)}…` : s;
  };

  const renderHealthBadge = (p) => {
    const h = p.health || {};
    const level = h.level || "unknown";
    const score = h.score != null ? h.score : "—";
    return (
      <Badge variant="outline" className={`text-[10px] ${healthBadgeClass(level)}`} title={(h.issues || []).join("; ")}>
        {level} · {score}
      </Badge>
    );
  };

  const handleQuickGenerate = async (deviceType = "desktop") => {
    try {
      const r = await fetch(`${API}/quick-generate`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ device_type: deviceType, country: form.country || "us" }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Profile "${d.profile.name}" created`);
      fetchProfiles();
    } catch (e) { toast.error(`Quick generate failed: ${e.message}`); }
  };

  const handleCreate = async () => {
    // 2026-01: When NOT editing an existing profile, route through the
    // new advanced-create endpoint so the form fully exploits the UA
    // generator + ProxyJet integration (no need for the customer to
    // pre-fill `user_agent` or proxy creds manually). The Edit flow
    // keeps using the old `/` PUT — that just replaces existing config
    // verbatim.
    if (!editingId) {
      return handleAdvancedCreate();
    }
    try {
      const payload = { ...form };
      if (payload.proxy?.provider_id) {
        payload.proxy = {
          ...payload.proxy,
          enabled: true,
          proxyjet_country: (
            payload.proxy.proxyjet_country
            || payload.country
            || "US"
          ).toUpperCase(),
        };
      } else if (payload.proxy?.use_proxyjet) {
        payload.proxy = { ...payload.proxy, enabled: true };
      }
      const r = await fetch(`${API}/${editingId}`, {
        method: "PUT", headers: authHeaders, body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Profile updated");
      closeCreateModal(true);
      fetchProfiles();
    } catch (e) { toast.error(`Save failed: ${e.message}`); }
  };

  const handleAdvancedCreate = async () => {
    if (advCreating) return;
    const count = Math.max(1, Math.min(parseInt(advCount) || 1, 200));
    const mix = normalizeMix(advMix);
    if (advDeviceMode !== "specific" && mix.sum <= 0) {
      toast.error("Set at least one mix % (iOS / Android / Desktop)");
      return;
    }
    if (advDeviceMode === "specific" && !advDeviceId) {
      toast.error("Pick a specific device, or switch Device mode to Random");
      return;
    }
    if (advResolutionMode === "exact" && (!(form.viewport?.width > 0) || !(form.viewport?.height > 0))) {
      toast.error("Exact resolution needs width and height");
      return;
    }
    setAdvCreating(true);
    try {
      const payload = {
        count,
        name_prefix: (advNamePrefix || "").trim(),
        country: (form.country || "us").toLowerCase(),
        device_type: mix.desktop >= mix.android && mix.desktop >= mix.ios ? "desktop" : "mobile",
        start_url: form.start_url || "https://www.google.com/",
        notes: form.notes || "",
        viewport_width: advResolutionMode === "exact" ? (form.viewport?.width || 0) : 0,
        viewport_height: advResolutionMode === "exact" ? (form.viewport?.height || 0) : 0,
        anti_detect_on: !!advAntiDetect,
        ...(advAntiDetect
          ? {
              anti_detect: {
                ...form.anti_detect,
                master: true,
                tls_prewarm: form.anti_detect?.tls_prewarm !== false,
              },
            }
          : {}),
        mix_ios_pct: mix.ios,
        mix_android_pct: mix.android,
        mix_desktop_pct: mix.desktop,
        device_mode: advDeviceMode,
        device_id: advDeviceId || "",
        resolution_mode: advResolutionMode,
        ua: {
          app: advUA.app || "browser",
          platform: advUA.platform || "any",
          brand: advUA.brand || null,
          region: advUA.region || (form.country || "US").toUpperCase(),
        },
        proxy: (() => {
          if (advProxy.provider_id) {
            return {
              mode: "provider",
              provider_id: advProxy.provider_id,
              country: (form.country || advProxy.country || "US").toUpperCase(),
              state: (advProxy.state || "").toUpperCase(),
            };
          }
          if (advProxy.mode === "provider" && advProxy.provider_id) {
            return {
              mode: "provider",
              provider_id: advProxy.provider_id,
              country: (form.country || "US").toUpperCase(),
              state: (advProxy.state || "").toUpperCase(),
            };
          }
          if (advProxy.mode === "proxyjet") {
            return {
              mode: "proxyjet",
              country: (advProxy.country || "US").toUpperCase(),
              state: (advProxy.state || "").toUpperCase(),
              sticky_minutes: Number(advProxy.sticky_minutes) || null,
            };
          }
          if (advProxy.mode === "manual") {
            const lines = (advProxyLines || "")
              .split(/\r?\n/)
              .map((l) => l.trim())
              .filter(Boolean);
            const base = {
              mode: "manual",
              server: advProxy.server || "",
              username: advProxy.username || "",
              password: advProxy.password || "",
            };
            if (lines.length) base.lines = lines;
            return base;
          }
          return { mode: "none" };
        })(),
        tags: (advTags || "").split(",").map((t) => t.trim()).filter(Boolean).slice(0, 20),
        folder: (advFolder || "").trim().slice(0, 80),
        timezone: (advTimezone || "").trim() || (form.timezone || ""),
        locale: (advLocale || "").trim() || (form.locale || ""),
        geo_follow_proxy: !!advGeoFollow,
        referrer: { ...DEFAULT_PROFILE_REFERRER, ...(form.referrer || {}) },
        quick_links: (advQuickLinks || "")
          .split(/\r?\n/)
          .map((u) => u.trim())
          .filter(Boolean)
          .slice(0, 12),
      };
      const r = await fetch(`${API}/advanced-create`, {
        method: "POST", headers: authHeaders, body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const t = await r.text();
        let msg = t;
        try { msg = JSON.parse(t).detail || t; } catch {}
        throw new Error(msg);
      }
      const d = await r.json();
      const n = d.created || 0;
      const mixLabel = d.mix
        ? ` (iOS ${d.mix.ios || 0} · Android ${d.mix.android || 0} · Desktop ${d.mix.desktop || 0})`
        : "";
      toast.success(
        n === 1
          ? `Profile "${d.profiles?.[0]?.name || ""}" created`
          : `${n} unique profiles created${mixLabel}`,
      );
      closeCreateModal(true);
      resetAdvCreateForm();
      fetchProfiles();
    } catch (e) {
      toast.error(`Create failed: ${e.message}`);
    } finally {
      setAdvCreating(false);
    }
  };

  const handleBulkLaunch = async () => {
    if (!selectedCount || bulkBusy) return;
    setBulkBusy(true);
    try {
      const payload = {
        profile_ids: [...selectedIds],
        max_concurrent: maxConcurrent,
      };
      if (bulkLaunchAuto.enabled && bulkLaunchAuto.automation_upload_id) {
        payload.automation = {
          enabled: true,
          automation_upload_id: bulkLaunchAuto.automation_upload_id,
          data_file_id: bulkLaunchAuto.data_file_id || "",
          lead_row_index: Number(bulkLaunchAuto.lead_row_index) || 0,
          skip_missing_steps: bulkLaunchAuto.skip_missing_steps !== false,
          self_heal: !!bulkLaunchAuto.self_heal,
          after_mode: "manual",
        };
      }
      const r = await fetch(`${API}/bulk-launch`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Launched ${d.launched_count || 0}` + (d.skipped?.length ? ` · skipped ${d.skipped.length}` : ""));
      clearSelection();
      fetchProfiles();
    } catch (e) {
      toast.error(`Bulk launch failed: ${e.message}`);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleBulkRunJson = async (uploadId) => {
    if (!selectedCount || jsonRunBusy || !uploadId) return;
    setJsonMenuOpen(false);
    setJsonRunBusy(true);
    try {
      const r = await fetch(`${API}/bulk-run-json`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({
          profile_ids: [...selectedIds],
          automation_upload_id: uploadId,
          data_file_id: bulkLaunchAuto.data_file_id || "",
          proxy_upload_id: bulkLaunchAuto.proxy_upload_id || "",
          max_concurrent: maxConcurrent,
          skip_missing_steps: bulkLaunchAuto.skip_missing_steps !== false,
          self_heal: !!bulkLaunchAuto.self_heal,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      const label = automationUploads.find((u) => u.id === uploadId);
      toast.success(
        `JSON started on ${d.started_count || 0} profile(s) — ${label?.name || label?.filename || "template"}`,
      );
      if (d.skipped?.length) {
        toast.info(`${d.skipped.length} skipped (busy or cap)`);
      }
      clearSelection();
      fetchProfiles();
    } catch (e) {
      toast.error(`JSON run failed: ${e.message}`);
    } finally {
      setJsonRunBusy(false);
    }
  };

  const handleStopAutomation = async (id) => {
    setStopAutoBusy(id);
    try {
      const r = await fetch(`${API}/${id}/stop-automation`, {
        method: "POST",
        headers: authHeaders,
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success("JSON automation stopped — profile still open for manual use");
      fetchProfiles();
    } catch (e) {
      toast.error(`Stop automation failed: ${e.message}`);
    } finally {
      setStopAutoBusy(null);
    }
  };

  const handleBulkStop = async () => {
    if (!selectedCount || bulkBusy) return;
    setBulkBusy(true);
    try {
      const r = await fetch(`${API}/bulk-stop`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ profile_ids: [...selectedIds] }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Stop sent to ${d.stopped || 0} profile(s)`);
      clearSelection();
      fetchProfiles();
    } catch (e) {
      toast.error(`Bulk stop failed: ${e.message}`);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleBulkDelete = async () => {
    if (!selectedCount || bulkBusy) return;
    if (!window.confirm(`Delete ${selectedCount} selected profile(s)? Storage state will be lost.`)) return;
    setBulkBusy(true);
    try {
      const r = await fetch(`${API}/bulk-delete`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ profile_ids: [...selectedIds] }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Deleted ${d.deleted_count || 0}` + (d.skipped?.length ? ` · skipped ${d.skipped.length} (busy)` : ""));
      clearSelection();
      fetchProfiles();
    } catch (e) {
      toast.error(`Bulk delete failed: ${e.message}`);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleCreateLegacy = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    try {
      const url = editingId ? `${API}/${editingId}` : `${API}/`;
      const method = editingId ? "PUT" : "POST";
      const r = await fetch(url, {
        method, headers: authHeaders, body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success(editingId ? "Profile updated" : "Profile created");
      setShowCreate(false); setEditingId(null); setForm(DEFAULT_NEW);
      fetchProfiles();
    } catch (e) { toast.error(`Save failed: ${e.message}`); }
  };

  const handleEdit = async (id) => {
    try {
      const r = await fetch(`${API}/${id}`, { headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      // Backend strips storage_state from response — that's fine for edit
      const p = d.profile || {};
      setForm({
        ...DEFAULT_NEW,
        ...p,
        folder: p.folder || "",
        geo_follow_proxy: p.geo_follow_proxy !== false,
        quick_links: Array.isArray(p.quick_links) ? p.quick_links : [],
        fingerprint_short: p.fingerprint_short || "",
        proxy: { ...DEFAULT_NEW.proxy, ...(p.proxy || {}) },
        anti_detect: { ...DEFAULT_NEW.anti_detect, ...(p.anti_detect || {}) },
        referrer: { ...DEFAULT_NEW.referrer, ...(p.referrer || {}) },
      });
      setEditingId(id); setShowCreate(true); setShowFpAdvanced(false);
    } catch (e) { toast.error(`Load profile failed: ${e.message}`); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Move this profile to recycle bin?")) return;
    try {
      const r = await fetch(`${API}/${id}`, { method: "DELETE", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Moved to recycle bin");
      fetchProfiles();
    } catch (e) { toast.error(`Delete failed: ${e.message}`); }
  };

  const handleRestore = async (id) => {
    try {
      const r = await fetch(`${API}/${id}/restore`, { method: "POST", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Profile restored");
      fetchProfiles();
    } catch (e) { toast.error(`Restore failed: ${e.message}`); }
  };

  const handlePermanentDelete = async (id, name) => {
    const label = name ? `"${name}"` : "this profile";
    if (!window.confirm(`Permanently delete ${label}? This cannot be undone.`)) return;
    try {
      const r = await fetch(`${API}/${id}?permanent=true`, { method: "DELETE", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Permanently deleted");
      fetchProfiles();
    } catch (e) { toast.error(`Permanent delete failed: ${e.message}`); }
  };

  const handleBulkPermanentDelete = async () => {
    if (!selectedCount || bulkBusy || !showTrash) return;
    if (!window.confirm(`Permanently delete ${selectedCount} profile(s)? This cannot be undone.`)) return;
    setBulkBusy(true);
    try {
      const r = await fetch(`${API}/bulk-delete`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ profile_ids: [...selectedIds], permanent: true }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Permanently deleted ${d.deleted_count || 0}` + (d.skipped?.length ? ` · skipped ${d.skipped.length}` : ""));
      clearSelection();
      fetchProfiles();
    } catch (e) {
      toast.error(`Bulk permanent delete failed: ${e.message}`);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleRetryWithNewProxy = async (id) => {
    if (proxyRetryBusy) return;
    setProxyRetryBusy(id);
    try {
      const r = await fetch(`${API}/${id}/refresh-proxy`, { method: "POST", headers: authHeaders });
      if (!r.ok) {
        const t = await r.text();
        let msg = t;
        try { msg = JSON.parse(t).detail || t; } catch {}
        throw new Error(msg);
      }
      const d = await r.json();
      toast.success(d.exit_ip ? `New proxy: ${d.exit_ip}` : "Proxy refreshed");
      fetchProfiles();
      requestLaunch(id);
    } catch (e) {
      toast.error(`Retry with new proxy failed: ${e.message}`);
    } finally {
      setProxyRetryBusy(null);
    }
  };

  const openCloneDialog = (id) => {
    setCloneDialog({
      open: true, id,
      opts: { include_cookies: false, fresh_proxy: true, fresh_ua: false },
    });
  };

  const confirmClone = async () => {
    const { id, opts } = cloneDialog;
    if (!id) return;
    try {
      const r = await fetch(`${API}/${id}/clone`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify(opts),
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success(opts.include_cookies ? "Profile cloned (with cookies)" : "Profile cloned");
      setCloneDialog({ open: false, id: null, opts: { include_cookies: false, fresh_proxy: true, fresh_ua: false } });
      fetchProfiles();
    } catch (e) { toast.error(`Clone failed: ${e.message}`); }
  };

  const handleBulkMove = async () => {
    if (!selectedCount || bulkBusy) return;
    const folder = (bulkMoveFolder || "").trim();
    setBulkBusy(true);
    try {
      const r = await fetch(`${API}/bulk-move`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ profile_ids: [...selectedIds], folder }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Moved ${d.moved || 0} to ${folder || "(unsorted)"}`);
      clearSelection();
      fetchProfiles();
    } catch (e) {
      toast.error(`Bulk move failed: ${e.message}`);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleImportFile = async (file) => {
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const list = Array.isArray(parsed)
        ? parsed
        : (Array.isArray(parsed?.profiles) ? parsed.profiles : null);
      if (!list || !list.length) {
        // Vendor exports may not be a flat list — still try vendor import with raw payload
        const includeCookies = window.confirm("Import cookies/storage_state when present?");
        let r = await fetch(`${API}/import-vendors`, {
          method: "POST", headers: authHeaders,
          body: JSON.stringify({ data: parsed, include_cookies: includeCookies }),
        });
        if (r.ok) {
          const d = await r.json();
          toast.success(`Imported ${d.created || 0} profile(s)`);
          fetchProfiles();
          return;
        }
        toast.error("JSON must be an array, { profiles: [...] }, or a vendor export");
        return;
      }
      const includeCookies = window.confirm("Import cookies/storage_state when present?");
      let r = await fetch(`${API}/import-vendors`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ data: parsed, include_cookies: includeCookies }),
      });
      if (r.ok) {
        const d = await r.json();
        toast.success(`Imported ${d.created || 0} profile(s)`);
        fetchProfiles();
        return;
      }
      r = await fetch(`${API}/import`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ profiles: list, include_cookies: includeCookies }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Imported ${d.created || 0} profile(s)`);
      fetchProfiles();
    } catch (e) {
      toast.error(`Import failed: ${e.message}`);
    }
  };

  const handleProxyCheck = async (id) => {
    if (proxyBusy) return;
    setProxyBusy(id);
    try {
      const r = await fetch(`${API}/${id}/check-proxy`, { method: "POST", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      const ip = d.ip || d.exit_ip || d.public_ip || "";
      const ok = d.ok !== false && !d.error;
      const fraudBit = d.fraud_score != null ? ` · fraud: ${d.fraud_score}` : "";
      toast[ok ? "success" : "error"](
        ok
          ? `Proxy OK${ip ? `: ${ip}` : ""}${d.country ? ` (${d.country})` : ""}${fraudBit}`
          : `Proxy check failed: ${d.error || d.message || "unknown"}`,
      );
      fetchProfiles();
    } catch (e) {
      toast.error(`Proxy check failed: ${e.message}`);
    } finally {
      setProxyBusy(null);
    }
  };

  const openFingerprintModal = async (id) => {
    setFpModal({ open: true, id, loading: true, data: null, error: null });
    try {
      const r = await fetch(`${API}/${id}/fingerprint`, { headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      setFpModal({ open: true, id, loading: false, data: d, error: null });
    } catch (e) {
      setFpModal({ open: true, id, loading: false, data: null, error: e.message || "Failed" });
    }
  };

  const handleFingerprintRefresh = async () => {
    const id = fpModal.id;
    if (!id) return;
    if (!window.confirm("Rotate fingerprint salt? Next launch gets a new CreepJS-class identity (cookies kept).")) return;
    try {
      const r = await fetch(`${API}/${id}/fingerprint/refresh`, {
        method: "POST", headers: authHeaders, body: "{}",
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(d.message || "Fingerprint rotated — relaunch to apply");
      await openFingerprintModal(id);
      fetchProfiles();
    } catch (e) {
      toast.error(`Fingerprint refresh failed: ${e.message}`);
    }
  };

  const handleCookieRobot = async (id) => {
    if (cookieRobotBusy) return;
    if (!window.confirm("Run Cookie Robot? Short stealth visits will warm cookies (desktop/native only).")) return;
    setCookieRobotBusy(id);
    try {
      const r = await fetch(`${API}/${id}/cookie-robot`, {
        method: "POST", headers: authHeaders, body: JSON.stringify({}),
      });
      if (!r.ok) {
        const t = await r.text();
        let msg = t;
        try { msg = JSON.parse(t).detail || t; } catch {}
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
      const d = await r.json();
      toast.success(
        d.ok !== false
          ? `Cookie robot done${d.cookie_count != null ? ` (${d.cookie_count} cookies)` : ""}`
          : `Cookie robot: ${d.error || "finished"}`,
      );
      fetchProfiles();
    } catch (e) {
      toast.error(`Cookie robot failed: ${e.message}`);
    } finally {
      setCookieRobotBusy(null);
    }
  };

  const openLocalApiDocs = async () => {
    setDocsModal({ open: true, loading: true, data: null, error: null });
    try {
      const r = await fetch(`${API}/local/docs`, { headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      setDocsModal({ open: true, loading: false, data: d, error: null });
    } catch (e) {
      setDocsModal({ open: true, loading: false, data: null, error: e.message || "Failed" });
    }
  };

  const openCookieDialog = async (id) => {
    try {
      const r = await fetch(`${API}/${id}/cookies`, { headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      setCookieDialog({
        id,
        text: JSON.stringify(d.storage_state || { cookies: [], origins: [] }, null, 2),
        open: true,
      });
    } catch (e) {
      toast.error(`Load cookies failed: ${e.message}`);
    }
  };

  const handleCookieSave = async () => {
    const { id, text } = cookieDialog;
    if (!id) return;
    try {
      let parsed;
      try { parsed = JSON.parse(text); } catch {
        toast.error("Cookies JSON invalid");
        return;
      }
      const body = Array.isArray(parsed)
        ? { cookies: parsed }
        : (parsed.cookies || parsed.origins
          ? { storage_state: parsed }
          : { storage_state: parsed });
      const r = await fetch(`${API}/${id}/cookies`, {
        method: "PUT", headers: authHeaders, body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(`Cookies saved (${d.cookie_count ?? "?"} cookies)`);
      setCookieDialog({ id: null, text: "", open: false });
      fetchProfiles();
    } catch (e) {
      toast.error(`Save cookies failed: ${e.message}`);
    }
  };

  const handleCookieClear = async () => {
    const { id } = cookieDialog;
    if (!id) return;
    if (!window.confirm("Clear all cookies for this profile?")) return;
    try {
      const r = await fetch(`${API}/${id}/cookies`, { method: "DELETE", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Cookies cleared");
      setCookieDialog({ id: null, text: "", open: false });
      fetchProfiles();
    } catch (e) {
      toast.error(`Clear cookies failed: ${e.message}`);
    }
  };

  const handleShare = async () => {
    const { id, email, includeCookies, mode, role } = shareDialog;
    if (!id || !(email || "").trim()) {
      toast.error("Target email required");
      return;
    }
    try {
      if (mode === "clone") {
        const r = await fetch(`${API}/${id}/share`, {
          method: "POST", headers: authHeaders,
          body: JSON.stringify({
            target_email: email.trim(),
            include_cookies: !!includeCookies,
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        toast.success(`Cloned profile to ${email.trim()}`);
      } else {
        const r = await fetch(`${API}/${id}/acl`, {
          method: "POST", headers: authHeaders,
          body: JSON.stringify({
            target_email: email.trim(),
            role: role || "editor",
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        toast.success(`ACL ${role || "editor"} granted to ${email.trim()}`);
        fetchProfiles();
      }
      setShareDialog({ id: null, email: "", includeCookies: false, mode: "acl", role: "editor" });
    } catch (e) {
      toast.error(`Share failed: ${e.message}`);
    }
  };

  const handleStartSync = async () => {
    const ids = [...selectedIds];
    if (ids.length < 2) {
      toast.error("Select 2+ running profiles (first = master)");
      return;
    }
    setSyncBusy(true);
    try {
      const r = await fetch(`${API}/sync/start`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({
          master_id: ids[0],
          slave_ids: ids.slice(1),
          modes: ["navigate", "click", "type", "scroll"],
          jitter: true,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      setActiveSyncId(d.sync_id || "");
      toast.success(`Synchronizer ON — master ${String(ids[0]).slice(0, 8)}…`);
    } catch (e) {
      toast.error(`Sync failed: ${e.message}`);
    } finally {
      setSyncBusy(false);
    }
  };

  const handleStopSync = async () => {
    if (!activeSyncId) return;
    setSyncBusy(true);
    try {
      const r = await fetch(`${API}/sync/${activeSyncId}/stop`, {
        method: "POST", headers: authHeaders,
      });
      if (!r.ok) throw new Error(await r.text());
      setActiveSyncId("");
      toast.success("Synchronizer stopped");
    } catch (e) {
      toast.error(`Stop sync failed: ${e.message}`);
    } finally {
      setSyncBusy(false);
    }
  };

  const openCloudPhoneDialog = async (profileId, existing) => {
    const cp = existing?.cloud_phone || {};
    setCloudPhoneDialog({
      id: profileId,
      provider: cp.provider || "cpi",
      partnerUrl: cp.partner_url || "",
      deviceId: cp.device_id || "",
      label: cp.label || "",
      devices: [],
      loadingDevices: true,
    });
    try {
      const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
      const r = await fetch(`${base}/api/cpi/devices`, { headers: authHeaders });
      if (r.ok) {
        const list = await r.json();
        const android = (Array.isArray(list) ? list : []).filter((d) =>
          String(d.device_type || "").startsWith("android_")
        );
        setCloudPhoneDialog((prev) => ({
          ...prev,
          devices: android,
          loadingDevices: false,
          deviceId: prev.deviceId || (android.find((d) => d.status === "online") || android[0] || {}).id || "",
        }));
      } else {
        setCloudPhoneDialog((prev) => ({ ...prev, loadingDevices: false }));
      }
    } catch {
      setCloudPhoneDialog((prev) => ({ ...prev, loadingDevices: false }));
    }
  };

  const handleCloudPhoneSave = async (mode = "bind") => {
    const { id, provider, partnerUrl, deviceId, label } = cloudPhoneDialog;
    if (!id) return;
    try {
      if (mode === "open" || (provider === "cpi" && mode === "open")) {
        const r = await fetch(`${API}/${id}/open-on-device`, {
          method: "POST", headers: authHeaders,
          body: JSON.stringify({ device_id: deviceId || "", auto_fallback: true }),
        });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        toast.success(
          d.auto_picked
            ? `Opened on ${d.device_label || "Krexion Android"} (auto)`
            : "Queued open URL on Krexion Android",
        );
      } else {
        const r = await fetch(`${API}/${id}/cloud-phone`, {
          method: "POST", headers: authHeaders,
          body: JSON.stringify({
            provider,
            partner_url: partnerUrl || "",
            device_id: deviceId || "",
            label: label || "",
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        toast.success(provider === "none" ? "Cloud phone cleared" : "Cloud phone bound");
      }
      setCloudPhoneDialog({
        id: null, provider: "cpi", partnerUrl: "", deviceId: "", label: "", devices: [], loadingDevices: false,
      });
      fetchProfiles();
    } catch (e) {
      toast.error(`Cloud phone failed: ${e.message}`);
    }
  };

  const handleLaunchUrlConfirm = () => {
    const { id, url } = launchUrlPrompt;
    if (!id) return;
    const u = (url || "").trim();
    setLaunchUrlPrompt({ id: null, url: "" });
    requestLaunch(id, u || undefined);
  };

  const executeLaunch = async (id, startUrl, automationOpts = null) => {
    try {
      const auto = automationOpts || { ...DEFAULT_LAUNCH_AUTO };
      const payload = { start_url: startUrl || undefined };
      if (auto.enabled && auto.automation_upload_id) {
        payload.automation = {
          enabled: true,
          automation_upload_id: auto.automation_upload_id,
          data_file_id: auto.data_file_id || "",
          lead_row_index: Number(auto.lead_row_index) || 0,
          skip_missing_steps: auto.skip_missing_steps !== false,
          self_heal: !!auto.self_heal,
          after_mode: "manual",
          save_as_default: !!auto.save_as_default,
        };
      }
      const r = await fetch(`${API}/${id}/launch`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const txt = await r.text();
        if (r.status === 409) throw new Error(txt || "Profile is already running — stop it first");
        throw new Error(txt);
      }
      const d = await r.json();
      setStatusMap((m) => ({ ...m, [id]: { ...d } }));
      if (d.desktop_available) {
        toast.success(
          d.automation_enabled
            ? "Launch + JSON automation queued on this PC"
            : "Launch queued — desktop app will open the browser",
        );
      } else {
        toast.warning("Profile saved — install the Krexion desktop app to launch", { duration: 6000 });
      }
      fetchProfiles();
    } catch (e) { toast.error(`Launch failed: ${e.message}`); }
  };

  const fetchAutomationUploads = async () => {
    setUploadsLoading(true);
    try {
      const [ajR, dfR, pxR] = await Promise.all([
        fetch(`${UPLOADS_API}?type=automation_json`, { headers: authHeaders }),
        fetch(`${UPLOADS_API}?type=data_file`, { headers: authHeaders }),
        fetch(`${UPLOADS_API}?type=proxies`, { headers: authHeaders }),
      ]);
      if (ajR.ok) {
        const aj = await ajR.json();
        setAutomationUploads(Array.isArray(aj) ? aj : []);
      }
      if (dfR.ok) {
        const df = await dfR.json();
        setDataFileUploads(Array.isArray(df) ? df : []);
      }
      if (pxR.ok) {
        const px = await pxR.json();
        setProxyUploads(Array.isArray(px) ? px : []);
      }
    } catch (_) { /* optional */ }
    finally { setUploadsLoading(false); }
  };

  const handleRunAutomationAgain = async (p) => {
    const uploadId = launchAuto.automation_upload_id
      || p.default_automation_upload_id
      || "";
    if (!uploadId) {
      toast.error("Select a JSON template in Launch preview first, or save a default.");
      return;
    }
    setRunAutoBusy(p.id);
    try {
      const r = await fetch(`${API}/${p.id}/run-automation`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({
          automation_upload_id: uploadId,
          data_file_id: launchAuto.data_file_id || p.default_data_file_id || "",
          lead_row_index: Number(launchAuto.lead_row_index) || 0,
          skip_missing_steps: launchAuto.skip_missing_steps !== false,
          self_heal: !!launchAuto.self_heal,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success("JSON automation queued on open profile");
      fetchProfiles();
    } catch (e) {
      toast.error(`Run automation failed: ${e.message}`);
    } finally {
      setRunAutoBusy(null);
    }
  };

  const requestLaunch = async (id, startUrl) => {
    try {
      const [prevR] = await Promise.all([
        fetch(`${API}/${id}/launch-preview`, { headers: authHeaders }),
        fetchAutomationUploads(),
      ]);
      if (!prevR.ok) throw new Error(await prevR.text());
      const data = await prevR.json();
      setLaunchAuto({
        ...DEFAULT_LAUNCH_AUTO,
        automation_upload_id: data.default_automation_upload_id || "",
        data_file_id: data.default_data_file_id || "",
      });
      setLaunchChecklist({ open: true, id, data, startUrl });
    } catch (e) {
      toast.error(`Launch preview failed: ${e.message}`);
    }
  };

  const confirmLaunchFromChecklist = () => {
    const { id, startUrl } = launchChecklist;
    const auto = { ...launchAuto };
    setLaunchChecklist({ open: false, id: null, data: null, startUrl: undefined });
    if (id) executeLaunch(id, startUrl, auto);
  };

  const handleLaunch = (id, startUrl) => requestLaunch(id, startUrl);

  const handleStop = async (id) => {
    try {
      const r = await fetch(`${API}/${id}/stop`, { method: "POST", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast.success(d.status === "stopping" ? "Stop signal sent — closing browser…" : "Profile stopped");
      fetchProfiles();
    } catch (e) { toast.error(`Stop failed: ${e.message}`); }
  };

  const handleExport = async () => {
    try {
      const r = await fetch(`${API}/export/all`, { headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `krexion-browser-profiles-${new Date().toISOString().slice(0,10)}.json`;
      link.click();
      toast.success(`Exported ${d.count} profiles`);
    } catch (e) { toast.error(`Export failed: ${e.message}`); }
  };

  const profileIsBusy = (p) => ["running", "launching", "stopping", "queued"].includes(p.status);
  const profileAutomationActive = (p) => ["queued", "running"].includes(String(p.automation_status || "").toLowerCase());

  const renderProfileRunningActions = (p) => (
    <>
      {profileAutomationActive(p) && (
        <Button
          size="sm"
          onClick={() => handleStopAutomation(p.id)}
          disabled={stopAutoBusy === p.id}
          className="bg-amber-600 hover:bg-amber-700 text-white h-7 text-xs"
          data-testid={`bp-stop-auto-${p.id}`}
        >
          <StopCircle className="w-3 h-3 mr-1" />
          {stopAutoBusy === p.id ? "Stopping…" : "Stop Auto"}
        </Button>
      )}
      <Button
        size="sm"
        onClick={() => handleStop(p.id)}
        className="bg-red-600 hover:bg-red-700 text-white h-7 text-xs"
        data-testid={`bp-stop-${p.id}`}
      >
        <StopCircle className="w-3 h-3 mr-1" /> Stop
      </Button>
    </>
  );

  const renderProfileMoreMenu = (p) => {
    const busy = profileIsBusy(p);
    const itemClass = "w-full text-left px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800 hover:text-fuchsia-200 disabled:opacity-40 disabled:pointer-events-none";
    return (
      <div
        className="absolute right-0 top-full mt-1 z-30 min-w-[10rem] rounded-md border border-zinc-700 bg-zinc-950 shadow-xl py-1"
        data-no-dbl-launch
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className={itemClass} disabled={busy || showTrash}
          data-testid={`bp-launch-url-${p.id}`}
          onClick={() => { setLaunchUrlPrompt({ id: p.id, url: p.start_url || "https://" }); setCardMenuId(null); }}>
          URL
        </button>
        {p.status === "running" && (
          <button type="button" className={itemClass} disabled={runAutoBusy === p.id}
            data-testid={`bp-run-automation-${p.id}`}
            onClick={() => { handleRunAutomationAgain(p); setCardMenuId(null); }}>
            Run JSON again
          </button>
        )}
        <button type="button" className={itemClass} disabled={showTrash}
          onClick={() => { openFingerprintModal(p.id); setCardMenuId(null); }}>
          Fingerprint
        </button>
        <button type="button" className={itemClass} disabled={busy || showTrash || cookieRobotBusy === p.id}
          onClick={() => { handleCookieRobot(p.id); setCardMenuId(null); }}>
          Cookie Robot
        </button>
        <button type="button" className={itemClass} disabled={showTrash}
          onClick={() => {
            window.location.href = `/rpa-studio?browser_profile_id=${encodeURIComponent(p.id)}&name=${encodeURIComponent(p.name || "")}`;
            setCardMenuId(null);
          }}>
          RPA
        </button>
        <button type="button" className={itemClass} disabled={showTrash || proxyBusy === p.id}
          data-testid={`bp-proxy-check-${p.id}`}
          onClick={() => { handleProxyCheck(p.id); setCardMenuId(null); }}>
          Proxy
        </button>
        <button type="button" className={itemClass} disabled={showTrash}
          data-testid={`bp-cookies-${p.id}`}
          onClick={() => { openCookieDialog(p.id); setCardMenuId(null); }}>
          Cookies
        </button>
        <button type="button" className={itemClass} disabled={showTrash}
          data-testid={`bp-share-${p.id}`}
          onClick={() => {
            setShareDialog({ id: p.id, email: "", includeCookies: false, mode: "acl", role: "editor" });
            setCardMenuId(null);
          }}>
          Share
        </button>
        <button type="button" className={itemClass} disabled={showTrash}
          onClick={() => { openCloudPhoneDialog(p.id, p); setCardMenuId(null); }}>
          Cloud Phone
        </button>
        <button type="button" className={itemClass} disabled={showTrash}
          onClick={() => { handleEdit(p.id); setCardMenuId(null); }}>
          Edit
        </button>
        <button type="button" className={itemClass} disabled={showTrash}
          onClick={() => { openCloneDialog(p.id); setCardMenuId(null); }}>
          Clone
        </button>
        <button type="button" className={`${itemClass} text-red-400 hover:text-red-300`} disabled={showTrash}
          onClick={() => { handleDelete(p.id); setCardMenuId(null); }}>
          Delete
        </button>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-fuchsia-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent">
              🌐 Browser Profiles
            </h1>
            <p className="text-zinc-400 text-sm mt-1">
              Krexion Browser Profiles — each profile uses the full Krexion anti-detect stack
              (same engine that powers Real User Traffic).
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              data-testid="bp-quick-desktop"
              onClick={() => handleQuickGenerate("desktop")}
              className="bg-fuchsia-600 hover:bg-fuchsia-700 text-white"
            >
              <Plus className="w-4 h-4 mr-1" /> Quick Desktop
            </Button>
            <Button
              data-testid="bp-quick-mobile"
              onClick={() => handleQuickGenerate("mobile")}
              className="bg-cyan-600 hover:bg-cyan-700 text-white"
            >
              <Smartphone className="w-4 h-4 mr-1" /> Quick Mobile
            </Button>
            <Button
              data-testid="bp-open-create"
              onClick={openCustomProfileModal}
              variant="outline" className="border-zinc-700 text-zinc-300"
            >
              <Plus className="w-4 h-4 mr-1" /> Custom Profile
            </Button>
            <label data-testid="bp-import" className="inline-flex items-center gap-1 px-3 py-2 rounded-md border border-zinc-700 text-zinc-300 text-sm cursor-pointer hover:bg-zinc-900">
              <Upload className="w-4 h-4" /> Import
              <input
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  handleImportFile(f);
                }}
              />
            </label>
            <Button data-testid="bp-export" onClick={handleExport} variant="outline" className="border-zinc-700 text-zinc-300">
              <Download className="w-4 h-4 mr-1" /> Export
            </Button>
            <Button data-testid="bp-local-api-docs" onClick={openLocalApiDocs} variant="outline" className="border-zinc-700 text-zinc-300">
              Local API docs
            </Button>
            <Button data-testid="bp-refresh" onClick={fetchProfiles} variant="outline" className="border-zinc-700 text-zinc-300">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        <div className="flex gap-4 items-start">
          {!showTrash && (
            <aside
              data-testid="bp-folder-sidebar"
              className="hidden lg:block w-44 flex-shrink-0 rounded-lg border border-zinc-800 bg-zinc-900/80 p-2 sticky top-4"
            >
              <p className="text-[10px] uppercase tracking-wide text-zinc-500 px-2 py-1 mb-1">Folders</p>
              <button
                type="button"
                data-testid="bp-folder-all"
                onClick={() => setFilterFolder("")}
                className={`w-full text-left px-2 py-1.5 rounded text-xs mb-0.5 ${
                  !filterFolder ? "bg-fuchsia-950/50 text-fuchsia-300" : "text-zinc-300 hover:bg-zinc-800"
                }`}
              >
                All profiles
              </button>
              <button
                type="button"
                data-testid="bp-folder-unsorted"
                onClick={() => setFilterFolder("unsorted")}
                className={`w-full text-left px-2 py-1.5 rounded text-xs mb-0.5 ${
                  filterFolder === "unsorted" ? "bg-fuchsia-950/50 text-fuchsia-300" : "text-zinc-300 hover:bg-zinc-800"
                }`}
              >
                <span className="inline-flex items-center gap-1">
                  <Folder className="w-3 h-3" /> Unsorted ({foldersUnsorted})
                </span>
              </button>
              {folders.map((f) => (
                <button
                  key={f.name}
                  type="button"
                  data-testid={`bp-folder-${f.name}`}
                  onClick={() => setFilterFolder(f.name)}
                  className={`w-full text-left px-2 py-1.5 rounded text-xs mb-0.5 truncate ${
                    filterFolder === f.name ? "bg-fuchsia-950/50 text-fuchsia-300" : "text-zinc-300 hover:bg-zinc-800"
                  }`}
                  title={f.name}
                >
                  <span className="inline-flex items-center gap-1 max-w-full">
                    <Folder className="w-3 h-3 flex-shrink-0" />
                    <span className="truncate">{f.name}</span>
                    <span className="text-zinc-500 flex-shrink-0">({f.count})</span>
                  </span>
                </button>
              ))}
            </aside>
          )}

          <div className="flex-1 min-w-0">

        {/* Info banner */}
        <div className="mb-6 p-3 rounded-lg bg-amber-950/20 border border-amber-700/40 text-xs text-amber-200 flex items-start gap-2">
          <Shield className="w-4 h-4 mt-0.5 text-amber-300" />
          <div>
            <span className="font-semibold">How it works:</span> Create a profile, then click{" "}
            <span className="text-amber-300">Launch</span>. On Local Engine / Native, Chromium opens on this PC
            (tray helper may open it if the backend runs as a Windows service). On cloud, your Krexion desktop
            app picks up the job. Anti-detect + cookies/localStorage from previous sessions apply automatically.
            Select multiple cards for bulk Launch / Stop / Delete.
          </div>
        </div>

        {/* Filters toolbar */}
        <div className="mb-3 flex flex-wrap items-center gap-2 p-2 rounded-lg bg-zinc-900/80 border border-zinc-800">
          <div className="relative flex-1 min-w-[160px] max-w-xs">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500" />
            <Input
              data-testid="bp-search"
              value={filterQ}
              onChange={(e) => setFilterQ(e.target.value)}
              placeholder="Search name, notes, tags…"
              className="bg-zinc-950 border-zinc-700 text-zinc-100 h-8 text-xs pl-8"
              disabled={showTrash}
            />
          </div>
          <div className="flex items-center gap-1.5 lg:hidden">
            <Folder className="w-3.5 h-3.5 text-zinc-500" />
            <select
              data-testid="bp-filter-folder-mobile"
              value={filterFolder}
              onChange={(e) => setFilterFolder(e.target.value)}
              disabled={showTrash}
              className="bg-zinc-950 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs h-8 flex-1 min-w-[120px]"
            >
              <option value="">All folders</option>
              <option value="unsorted">Unsorted ({foldersUnsorted})</option>
              {folders.map((f) => (
                <option key={f.name} value={f.name}>{f.name} ({f.count})</option>
              ))}
            </select>
          </div>
          <Input
            value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)}
            placeholder="Filter tag"
            className="bg-zinc-950 border-zinc-700 text-zinc-100 h-8 text-xs w-32"
            disabled={showTrash}
          />
          <select
            data-testid="bp-sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            disabled={showTrash}
            className="bg-zinc-950 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs h-8"
          >
            <option value="updated_at">Sort: Updated</option>
            <option value="last_launched_at">Sort: Last launched</option>
            <option value="name">Sort: Name</option>
            <option value="total_launches">Sort: Launches</option>
          </select>
          <div className="flex items-center rounded-md border border-zinc-700 overflow-hidden h-8">
            <button
              type="button"
              data-testid="bp-view-cards"
              onClick={() => setViewMode("cards")}
              className={`px-2 py-1 text-xs flex items-center gap-1 ${viewMode === "cards" ? "bg-fuchsia-950/50 text-fuchsia-300" : "text-zinc-400 hover:bg-zinc-900"}`}
            >
              <LayoutGrid className="w-3.5 h-3.5" /> Cards
            </button>
            <button
              type="button"
              data-testid="bp-view-table"
              onClick={() => setViewMode("table")}
              className={`px-2 py-1 text-xs flex items-center gap-1 border-l border-zinc-700 ${viewMode === "table" ? "bg-fuchsia-950/50 text-fuchsia-300" : "text-zinc-400 hover:bg-zinc-900"}`}
            >
              <Table2 className="w-3.5 h-3.5" /> Table
            </button>
          </div>
          <Button
            size="sm"
            variant="outline"
            data-testid="bp-trash-toggle"
            onClick={() => { setShowTrash((v) => !v); clearSelection(); }}
            className={`h-8 text-xs ${showTrash ? "border-fuchsia-600 text-fuchsia-300 bg-fuchsia-950/30" : "border-zinc-700 text-zinc-300"}`}
          >
            <Trash2 className="w-3.5 h-3.5 mr-1" />
            {showTrash ? "Back to profiles" : "Recycle bin"}
          </Button>
        </div>

        {profiles.length > 0 && showTrash && (
          <div className="mb-3 flex flex-wrap items-center gap-2 p-2 rounded-lg bg-zinc-900/80 border border-zinc-800">
            <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs" onClick={selectAllVisible} data-testid="bp-trash-select-all">
              Select all
            </Button>
            <Button size="sm" disabled={!selectedCount || bulkBusy} onClick={clearSelection} variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs">
              Clear ({selectedCount})
            </Button>
            <Button size="sm" disabled={!selectedCount || bulkBusy} onClick={handleBulkPermanentDelete}
              variant="outline" className="border-red-900/60 text-red-400 h-7 text-xs" data-testid="bp-bulk-permanent-delete">
              <Trash2 className="w-3 h-3 mr-1" /> Delete forever
            </Button>
          </div>
        )}

        {profiles.length > 0 && !showTrash && (
          <div className="mb-3 flex flex-wrap items-center gap-2 p-2 rounded-lg bg-zinc-900/80 border border-zinc-800">
            <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs" onClick={selectAllVisible} data-testid="bp-select-all">
              Select all
            </Button>
            <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs" onClick={clearSelection} data-testid="bp-clear-selection">
              Clear
            </Button>
            <span className="text-xs text-zinc-400">{selectedCount} selected</span>
            <div className="flex items-center gap-2 text-xs text-zinc-400">
              <span>Max concurrent</span>
              <input
                type="range"
                min={1}
                max={20}
                value={maxConcurrent}
                onChange={(e) => setMaxConcurrent(Number(e.target.value))}
                className="w-24 accent-fuchsia-500"
                data-testid="bp-max-concurrent"
              />
              <span className="text-fuchsia-300 w-4">{maxConcurrent}</span>
            </div>
            <div className="flex-1" />
            {selectedCount > 0 && (
              <div className="flex items-center gap-1.5">
                <Input
                  value={bulkMoveFolder}
                  onChange={(e) => setBulkMoveFolder(e.target.value)}
                  placeholder="Folder name"
                  list="bp-folder-suggestions"
                  className="bg-zinc-950 border-zinc-700 text-zinc-100 h-7 text-xs w-36"
                />
                <datalist id="bp-folder-suggestions">
                  {folders.map((f) => <option key={f.name} value={f.name} />)}
                </datalist>
                <Button size="sm" disabled={bulkBusy} onClick={handleBulkMove}
                  variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs" data-testid="bp-bulk-move">
                  <Folder className="w-3 h-3 mr-1" /> Move
                </Button>
              </div>
            )}
            <div className="flex items-center gap-2 text-xs text-zinc-400 flex-wrap">
              <select
                className="bg-zinc-950 border border-zinc-700 rounded px-1 py-0.5 text-zinc-200 max-w-[140px]"
                value={bulkLaunchAuto.data_file_id}
                onChange={(e) => setBulkLaunchAuto((s) => ({ ...s, data_file_id: e.target.value }))}
                data-testid="bp-bulk-auto-leads"
                title="Uploaded Things lead file — RUT jaisa, use hone par row remove"
              >
                <option value="">Lead file…</option>
                {dataFileUploads.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name || u.filename || u.id.slice(0, 8)} ({u.available_count ?? u.item_count ?? 0})
                  </option>
                ))}
              </select>
              <select
                className="bg-zinc-950 border border-zinc-700 rounded px-1 py-0.5 text-zinc-200 max-w-[140px]"
                value={bulkLaunchAuto.proxy_upload_id}
                onChange={(e) => setBulkLaunchAuto((s) => ({ ...s, proxy_upload_id: e.target.value }))}
                data-testid="bp-bulk-auto-proxy-upload"
                title="Proxy batch (Uploaded Things) ya khali = profile provider se fresh unique IP"
              >
                <option value="">Provider fresh IP</option>
                {proxyUploads.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name || u.id.slice(0, 8)} ({u.available_count ?? u.item_count ?? 0})
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-fuchsia-500"
                  checked={bulkLaunchAuto.enabled}
                  onChange={(e) => setBulkLaunchAuto((s) => ({ ...s, enabled: e.target.checked }))}
                  data-testid="bp-bulk-auto-enable"
                />
                JSON on Launch
              </label>
              {bulkLaunchAuto.enabled && (
                <>
                  <select
                    className="bg-zinc-950 border border-zinc-700 rounded px-1 py-0.5 text-zinc-200 max-w-[140px]"
                    value={bulkLaunchAuto.automation_upload_id}
                    onChange={(e) => setBulkLaunchAuto((s) => ({ ...s, automation_upload_id: e.target.value }))}
                    data-testid="bp-bulk-auto-json"
                  >
                    <option value="">JSON template…</option>
                    {automationUploads.map((u) => (
                      <option key={u.id} value={u.id}>{u.name || u.filename || u.id.slice(0, 8)}</option>
                    ))}
                  </select>
                </>
              )}
            </div>
            <Button size="sm" disabled={!selectedCount || bulkBusy} onClick={handleBulkLaunch}
              className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs" data-testid="bp-bulk-launch">
              <Play className="w-3 h-3 mr-1" /> Launch
            </Button>
            <div className="relative" data-testid="bp-bulk-json-wrap">
              <Button
                size="sm"
                disabled={!selectedCount || jsonRunBusy || uploadsLoading}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!automationUploads.length) {
                    fetchAutomationUploads();
                  }
                  setJsonMenuOpen((v) => !v);
                }}
                className="bg-violet-600 hover:bg-violet-700 text-white h-7 text-xs"
                data-testid="bp-bulk-json"
              >
                <Braces className="w-3 h-3 mr-1" />
                {jsonRunBusy ? "Starting…" : "JSON"}
                <ChevronDown className="w-3 h-3 ml-1" />
              </Button>
              {jsonMenuOpen && (
                <div
                  className="absolute left-0 top-full mt-1 z-40 min-w-[14rem] max-h-64 overflow-y-auto rounded-md border border-zinc-700 bg-zinc-950 shadow-xl py-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  {uploadsLoading ? (
                    <div className="px-3 py-2 text-xs text-zinc-500">Loading JSON templates…</div>
                  ) : automationUploads.length === 0 ? (
                    <div className="px-3 py-2 text-xs text-zinc-500">
                      No JSON templates — upload in RUT / Visual Recorder first.
                    </div>
                  ) : (
                    automationUploads.map((u) => (
                      <button
                        key={u.id}
                        type="button"
                        className="w-full text-left px-3 py-2 text-xs text-zinc-200 hover:bg-violet-950/50 hover:text-violet-200 truncate"
                        data-testid={`bp-json-pick-${u.id}`}
                        title={u.name || u.filename || u.id}
                        onClick={() => handleBulkRunJson(u.id)}
                      >
                        {u.name || u.filename || u.id.slice(0, 12)}
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
            <Button size="sm" disabled={selectedCount < 2 || syncBusy} onClick={handleStartSync}
              className="bg-sky-700 hover:bg-sky-800 text-white h-7 text-xs" data-testid="bp-sync-start"
              title="First selected = master; others = slaves (must be running with CDP)">
              Sync
            </Button>
            {activeSyncId ? (
              <Button size="sm" disabled={syncBusy} onClick={handleStopSync}
                variant="outline" className="border-sky-800 text-sky-300 h-7 text-xs" data-testid="bp-sync-stop">
                Stop Sync
              </Button>
            ) : null}
            <Button size="sm" disabled={!selectedCount || bulkBusy} onClick={handleBulkStop}
              className="bg-amber-700 hover:bg-amber-800 text-white h-7 text-xs" data-testid="bp-bulk-stop">
              <StopCircle className="w-3 h-3 mr-1" /> Stop
            </Button>
            <Button size="sm" disabled={!selectedCount || bulkBusy} onClick={handleBulkDelete}
              variant="outline" className="border-red-900/60 text-red-400 h-7 text-xs" data-testid="bp-bulk-delete">
              <Trash2 className="w-3 h-3 mr-1" /> Delete
            </Button>
          </div>
        )}

        {/* Profile list */}
        {profiles.length === 0 ? (
          <Card className="bg-zinc-900/50 border-zinc-800 mt-4">
            <CardContent className="py-12 text-center text-zinc-500">
              <Globe className="w-12 h-12 mx-auto mb-3 text-zinc-700" />
              {showTrash ? (
                <p>Recycle bin is empty.</p>
              ) : (
                <p>No profiles yet. Click <span className="text-fuchsia-400 font-semibold">Quick Desktop</span> or <span className="text-cyan-400 font-semibold">Quick Mobile</span> for a one-click profile.</p>
              )}
            </CardContent>
          </Card>
        ) : viewMode === "table" ? (
          <div className="rounded-lg border border-zinc-800 overflow-hidden">
            <table className="w-full text-xs text-zinc-300" data-testid="bp-table">
              <thead className="bg-zinc-900/80 text-zinc-500 uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left w-8" />
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Status</th>
                  <th className="px-3 py-2 text-left">Health</th>
                  <th className="px-3 py-2 text-left">Country</th>
                  <th className="px-3 py-2 text-left">Cookies</th>
                  <th className="px-3 py-2 text-left">Last used</th>
                  <th className="px-3 py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.id} className="border-t border-zinc-800 hover:bg-zinc-900/50" data-testid={`bp-row-${p.id}`}>
                    <td className="px-3 py-2">
                      <input type="checkbox" className="accent-fuchsia-500" checked={selectedIds.has(p.id)} onChange={() => toggleSelect(p.id)} />
                    </td>
                    <td className="px-3 py-2 font-medium text-zinc-100 truncate max-w-[12rem]">{p.name}</td>
                    <td className="px-3 py-2">
                      <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(p.status)}`}>{p.status || "idle"}</Badge>
                    </td>
                    <td className="px-3 py-2">{renderHealthBadge(p)}</td>
                    <td className="px-3 py-2">{(p.country || "?").toUpperCase()}</td>
                    <td className="px-3 py-2">{p.storage_state_stats?.cookie_count || 0}</td>
                    <td className="px-3 py-2 text-zinc-500">{p.last_used_label || "—"}</td>
                    <td className="px-3 py-2 text-right">
                      {showTrash ? (
                        <div className="flex flex-wrap gap-1 justify-end">
                          <Button size="sm" variant="outline" className="border-fuchsia-700 text-fuchsia-300 h-7 text-xs"
                            onClick={() => handleRestore(p.id)} data-testid={`bp-restore-${p.id}`}>
                            <RotateCcw className="w-3 h-3 mr-1" /> Restore
                          </Button>
                          <Button size="sm" variant="outline" className="border-red-900/60 text-red-400 h-7 text-xs"
                            onClick={() => handlePermanentDelete(p.id, p.name)} data-testid={`bp-permanent-delete-${p.id}`}>
                            <Trash2 className="w-3 h-3 mr-1" /> Delete forever
                          </Button>
                        </div>
                      ) : profileIsBusy(p) ? (
                        <div className="flex flex-wrap gap-1 justify-end">
                          {renderProfileRunningActions(p)}
                        </div>
                      ) : (
                        <Button size="sm" onClick={() => handleLaunch(p.id)} className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs" data-testid={`bp-launch-${p.id}`}>
                          <Play className="w-3 h-3 mr-1" /> Launch
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {profiles.map((p) => (
              <Card
                key={p.id}
                className={`bg-zinc-900/60 border-zinc-800 hover:border-fuchsia-700/40 transition cursor-default ${selectedIds.has(p.id) ? "ring-1 ring-fuchsia-500/50 border-fuchsia-700/50" : ""}`}
                data-testid={`bp-card-${p.id}`}
                onDoubleClick={(e) => {
                  if (e.target.closest("button, input, a, [data-no-dbl-launch]")) return;
                  if (!showTrash && !profileIsBusy(p)) handleLaunch(p.id);
                }}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <label className={`mt-1 flex-shrink-0 cursor-pointer`}>
                      <input
                        type="checkbox"
                        className="w-4 h-4 accent-fuchsia-500"
                        checked={selectedIds.has(p.id)}
                        onChange={() => toggleSelect(p.id)}
                        data-testid={`bp-select-${p.id}`}
                      />
                    </label>
                    <div className="flex-1 min-w-0">
                      <CardTitle className="text-base text-zinc-100 truncate">{p.name}</CardTitle>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-zinc-300">
                          {p.device_type === "mobile" ? <Smartphone className="w-3 h-3 mr-0.5" /> : <Monitor className="w-3 h-3 mr-0.5" />}
                          {p.os || p.device_type}
                        </Badge>
                        {p.device_model && (
                          <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-cyan-300">
                            {p.device_model}
                          </Badge>
                        )}
                        <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-zinc-300">{(p.country || "?").toUpperCase()}</Badge>
                        {p.anti_detect?.master && (
                          <Badge variant="outline" className="text-[10px] bg-fuchsia-950/40 border-fuchsia-700/60 text-fuchsia-300">
                            <Shield className="w-3 h-3 mr-0.5" /> AD
                          </Badge>
                        )}
                        <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(p.status)}`}>
                          {p.status || "idle"}
                        </Badge>
                        {renderHealthBadge(p)}
                      </div>
                      {p.last_used_label && (
                        <p className="text-[10px] text-zinc-500 mt-1">Last used: {p.last_used_label}</p>
                      )}
                      {p.notes && (
                        <p className="text-[10px] text-zinc-600 mt-0.5 truncate" title={p.notes}>{truncateNotes(p.notes)}</p>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-0 pb-3">
                  <div className="flex flex-wrap gap-1 mb-2">
                    {p.folder ? (
                      <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-violet-300">
                        <Folder className="w-3 h-3 mr-0.5" />{p.folder}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-zinc-500">unsorted</Badge>
                    )}
                    {(p.tags || []).map((t) => (
                      <Badge key={t} variant="outline" className="text-[10px] bg-fuchsia-950/30 border-fuchsia-800/50 text-fuchsia-300">{t}</Badge>
                    ))}
                  </div>
                  <div className="text-[11px] text-zinc-500 truncate mb-2" title={p.user_agent}>
                    {(p.user_agent || "").slice(0, 60)}…
                  </div>
                  <div className="text-[11px] text-zinc-500 mb-1">
                    {p.viewport?.width}×{p.viewport?.height} · {p.locale} · {p.total_launches || 0} launches
                    {(p.storage_state_stats?.cookie_count > 0 || p.storage_state_stats?.has_cookies) && (
                      <span className="text-emerald-400 ml-1">
                        · <Cookie className="w-3 h-3 inline" /> {p.storage_state_stats.cookie_count || 0} cookies
                      </span>
                    )}
                  </div>
                  {(p.fingerprint_short
                    || p.storage_state_stats?.synced_at
                    || p.last_tls_prewarm_ok != null
                    || (p.last_proxy_check && Object.keys(p.last_proxy_check).length > 0)) && (
                    <div className="text-[10px] text-zinc-500 mb-2 font-mono flex flex-wrap items-center gap-x-2 gap-y-1">
                      {p.fingerprint_short && <span>fp:{p.fingerprint_short}</span>}
                      {p.storage_state_stats?.synced_at && (
                        <span className="text-emerald-400/90" title={String(p.storage_state_stats.synced_at)}>
                          Synced: {formatSyncedAt(p.storage_state_stats.synced_at)}
                        </span>
                      )}
                      {p.last_tls_prewarm_ok != null && p.last_tls_prewarm_ok !== "" && (
                        <Badge
                          variant="outline"
                          className={`text-[9px] px-1 py-0 h-4 ${
                            p.last_tls_prewarm_ok === true || p.last_tls_prewarm_ok === "ok" || p.last_tls_prewarm_ok === 1
                              ? "border-emerald-700/60 text-emerald-300"
                              : "border-amber-700/60 text-amber-300"
                          }`}
                        >
                          tls:{String(p.last_tls_prewarm_ok === true ? "ok" : p.last_tls_prewarm_ok)}
                        </Badge>
                      )}
                      {p.exit_ip && (
                        <span className="text-cyan-300" title="Bound exit IP (team isolation)">
                          ip:{p.exit_ip}
                        </span>
                      )}
                      {p.last_proxy_check?.ip || p.last_proxy_check?.exit_ip ? (
                        <span className={p.last_proxy_check.ok === false ? "text-red-400" : "text-cyan-400"}>
                          proxy:{p.last_proxy_check.ip || p.last_proxy_check.exit_ip}
                          {p.last_proxy_check.country ? ` (${p.last_proxy_check.country})` : ""}
                        </span>
                      ) : p.last_proxy_check?.error ? (
                        <span className="text-red-400">proxy:fail</span>
                      ) : null}
                    </div>
                  )}
                  {Array.isArray(p.quick_links) && p.quick_links.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-2">
                      {p.quick_links.slice(0, 6).map((url) => (
                        <Button
                          key={url}
                          type="button"
                          size="sm"
                          variant="outline"
                          className="border-zinc-700 text-cyan-300 h-6 text-[10px] px-1.5"
                          onClick={() => handleLaunch(p.id, url)}
                          title={url}
                        >
                          <Link className="w-3 h-3 mr-0.5" />
                          {(() => { try { return new URL(url).hostname; } catch { return url.slice(0, 18); } })()}
                        </Button>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-1 items-center">
                    {showTrash ? (
                      <div className="flex flex-wrap gap-1">
                        <Button size="sm" variant="outline" className="border-fuchsia-700 text-fuchsia-300 h-7 text-xs"
                          onClick={() => handleRestore(p.id)} data-testid={`bp-restore-${p.id}`}>
                          <RotateCcw className="w-3 h-3 mr-1" /> Restore
                        </Button>
                        <Button size="sm" variant="outline" className="border-red-900/60 text-red-400 h-7 text-xs"
                          onClick={() => handlePermanentDelete(p.id, p.name)} data-testid={`bp-permanent-delete-${p.id}`}>
                          <Trash2 className="w-3 h-3 mr-1" /> Delete forever
                        </Button>
                      </div>
                    ) : profileIsBusy(p) ? (
                      <div className="flex flex-wrap gap-1">
                        {renderProfileRunningActions(p)}
                      </div>
                    ) : (
                      <Button data-testid={`bp-launch-${p.id}`} onClick={() => handleLaunch(p.id)} size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs">
                        <Play className="w-3 h-3 mr-1" /> Launch
                      </Button>
                    )}
                    {!showTrash && (
                      <div className="relative" data-no-dbl-launch>
                        <Button
                          data-testid={`bp-more-${p.id}`}
                          variant="outline"
                          size="sm"
                          className="border-zinc-700 text-zinc-300 h-7 text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            setCardMenuId(cardMenuId === p.id ? null : p.id);
                          }}
                        >
                          <MoreVertical className="w-3 h-3 mr-1" /> More <ChevronDown className="w-3 h-3" />
                        </Button>
                        {cardMenuId === p.id && renderProfileMoreMenu(p)}
                      </div>
                    )}
                  </div>
                  {statusMap[p.id]?.message && (
                    <div className="mt-2 text-[10px] text-amber-300/80 italic">{statusMap[p.id].message}</div>
                  )}
                  {p.automation_status && p.automation_status !== "idle" && (
                    <div className="mt-2 text-[10px] text-cyan-300/90" data-testid={`bp-auto-progress-${p.id}`}>
                      JSON: {p.automation_status}
                      {p.automation_total_steps > 0 && (
                        <span> · step {p.automation_step || 0}/{p.automation_total_steps}</span>
                      )}
                      {p.automation_error && (
                        <span className="block text-red-400/90 truncate" title={p.automation_error}>{p.automation_error}</span>
                      )}
                    </div>
                  )}
                  {(p.status === "error" || p.status === "queued" || p.status === "launching") && p.last_error && (
                    <div className="mt-2 space-y-1">
                      <div className="text-[10px] text-red-300/90 italic break-words" data-testid={`bp-last-error-${p.id}`}>
                        ⚠ {p.last_error}
                      </div>
                      {p.status === "error" && !showTrash && (p.proxy?.enabled || p.proxy?.provider_id || p.proxy?.server) && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={proxyRetryBusy === p.id}
                          className="h-6 text-[10px] border-amber-800/60 text-amber-300"
                          data-testid={`bp-retry-proxy-${p.id}`}
                          onClick={() => handleRetryWithNewProxy(p.id)}
                        >
                          <RefreshCw className={`w-3 h-3 mr-1 ${proxyRetryBusy === p.id ? "animate-spin" : ""}`} />
                          Retry with new proxy
                        </Button>
                      )}
                    </div>
                  )}
                  {p.status === "queued" && !p.last_error && (
                    <div className="mt-2 text-[10px] text-amber-300/80 italic">
                      Waiting for Krexion tray to open Chromium… Keep the tray app running.
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {!showTrash && hasMore && profiles.length > 0 && (
          <div className="mt-4 flex justify-center">
            <Button
              data-testid="bp-load-more"
              variant="outline"
              className="border-zinc-700 text-zinc-300"
              disabled={loadingMore}
              onClick={loadMoreProfiles}
            >
              <RefreshCw className={`w-4 h-4 mr-1 ${loadingMore ? "animate-spin" : ""}`} />
              {loadingMore ? "Loading…" : "Load more profiles"}
            </Button>
          </div>
        )}

          </div>
        </div>

        {/* Create / Edit dialog */}
        {showCreate && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
              <div className="p-5 border-b border-zinc-800 sticky top-0 bg-zinc-950 z-10">
                <h2 className="text-xl font-semibold text-zinc-100">{editingId ? "Edit Profile" : "New Browser Profile"}</h2>
                {!editingId && (
                  <p className="text-[11px] text-zinc-500 mt-1">
                    Each profile gets a UNIQUE user-agent (live generator) + UNIQUE proxy from your selected Proxy Provider — anti-detect ready. Leave name blank for auto-naming.
                  </p>
                )}
                {!editingId && (
                  <div className="mt-3 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] uppercase tracking-wide text-zinc-500">Templates</span>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={templateBusy}
                        className="h-7 text-[11px] border-fuchsia-700/50 text-fuchsia-300"
                        onClick={saveProfileTemplate}
                      >
                        {templateBusy ? "Saving…" : "Save current as template"}
                      </Button>
                    </div>
                    {profileTemplates.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {profileTemplates.map((t) => (
                          <div key={t.id} className="inline-flex items-center gap-1">
                            <button
                              type="button"
                              data-testid={`bp-template-${t.id}`}
                              className="px-2.5 py-1 rounded-md text-[11px] bg-zinc-900 border border-zinc-700 text-zinc-200 hover:border-fuchsia-600 hover:text-fuchsia-200"
                              onClick={() => applyProfileTemplate(t.settings)}
                            >
                              {t.name}
                              {t.is_default && (
                                <Badge variant="outline" className="ml-1 text-[9px] px-1 py-0 h-4 border-fuchsia-700 text-fuchsia-300">default</Badge>
                              )}
                            </button>
                            <button
                              type="button"
                              aria-label={`Edit template ${t.name}`}
                              className="text-zinc-600 hover:text-fuchsia-300 text-xs px-1"
                              onClick={() => updateProfileTemplate(t.id, t.name)}
                              data-testid={`bp-template-edit-${t.id}`}
                            >
                              <Pencil className="w-3 h-3" />
                            </button>
                            <button
                              type="button"
                              aria-label={`Set ${t.name} as default`}
                              className={`text-xs px-1 ${t.is_default ? "text-fuchsia-400" : "text-zinc-600 hover:text-fuchsia-300"}`}
                              onClick={() => setDefaultTemplate(t.id)}
                              data-testid={`bp-template-default-${t.id}`}
                            >
                              <Star className={`w-3 h-3 ${t.is_default ? "fill-fuchsia-400" : ""}`} />
                            </button>
                            <button
                              type="button"
                              aria-label={`Delete template ${t.name}`}
                              className="text-zinc-600 hover:text-red-400 text-xs px-1"
                              onClick={() => deleteProfileTemplate(t.id, t.name)}
                            >
                              ×
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[10px] text-zinc-600">No saved templates yet — configure settings once, then click Save.</p>
                    )}
                  </div>
                )}
              </div>
              <div className="p-5 space-y-4">
                {/* Basic */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2 grid grid-cols-3 gap-3">
                    <div className="col-span-2">
                      <Label className="text-zinc-300 text-xs">
                        {editingId ? "Name" : "Name Prefix"}{" "}
                        {!editingId && <span className="text-zinc-500">(blank = auto-unique name per profile)</span>}
                      </Label>
                      {editingId ? (
                        <Input data-testid="bp-form-name" value={form.name}
                          onChange={(e) => setForm({ ...form, name: e.target.value })}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100"
                          placeholder="Marketing Account US #1" />
                      ) : (
                        <Input data-testid="bp-form-name-prefix" value={advNamePrefix}
                          onChange={(e) => setAdvNamePrefix(e.target.value)}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100"
                          placeholder="Auto-generate (Krexion-Desktop-US-…)" />
                      )}
                    </div>
                    {!editingId && (
                      <div>
                        <Label className="text-zinc-300 text-xs">Count <span className="text-zinc-500">(1–200)</span></Label>
                        <Input data-testid="bp-form-count" type="number" min={1} max={200}
                          value={advCount}
                          onChange={(e) => setAdvCount(Math.max(1, Math.min(200, parseInt(e.target.value) || 1)))}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                      </div>
                    )}
                  </div>
                  <div>
                    <Label className="text-zinc-300 text-xs">Country</Label>
                    <select data-testid="bp-form-country" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value.toLowerCase() })}
                      className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                      {COUNTRY_OPTIONS.map((c) => <option key={c} value={c.toLowerCase()}>{c}</option>)}
                    </select>
                  </div>
                  {editingId ? (
                  <div>
                    <Label className="text-zinc-300 text-xs">Device Type</Label>
                    <select data-testid="bp-form-device" value={form.device_type}
                      onChange={(e) => {
                        const mob = e.target.value === "mobile";
                        const newViewport = mob
                          ? { width: 412, height: 914 }
                          : { width: 1920, height: 1080 };
                        setForm({
                          ...form,
                          device_type: e.target.value,
                          is_mobile: mob,
                          has_touch: mob,
                          device_scale_factor: mob ? 3 : 1,
                          os: mob ? "android" : "windows",
                          viewport: newViewport,
                        });
                      }}
                      className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                      <option value="desktop">Desktop</option>
                      <option value="mobile">Mobile</option>
                    </select>
                  </div>
                  ) : (
                  <div>
                    <Label className="text-zinc-300 text-xs">Start URL</Label>
                    <Input data-testid="bp-form-starturl-top" value={form.start_url} onChange={(e) => setForm({ ...form, start_url: e.target.value })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
                  )}
                  {editingId && (
                  <div className="col-span-2">
                    <Label className="text-zinc-300 text-xs">Start URL</Label>
                    <Input data-testid="bp-form-starturl" value={form.start_url} onChange={(e) => setForm({ ...form, start_url: e.target.value })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
                  )}
                  {!editingId && (
                    <div className="col-span-2 p-3 rounded-lg border border-emerald-500/30 bg-emerald-950/10 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-emerald-300 text-sm font-semibold">Platform mix %</span>
                        <span className="text-[10px] text-zinc-500">
                          Sum {normalizeMix(advMix).sum}% (auto-normalized) · names like Krexion-iPhone15-US-…
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          ["ios", "iOS"],
                          ["android", "Android"],
                          ["desktop", "Desktop"],
                        ].map(([key, label]) => (
                          <div key={key}>
                            <Label className="text-zinc-300 text-xs">{label}</Label>
                            <Input
                              data-testid={`bp-mix-${key}`}
                              type="number" min={0} max={100}
                              value={advMix[key]}
                              onChange={(e) => setAdvMix({ ...advMix, [key]: Math.max(0, Math.min(100, parseInt(e.target.value) || 0)) })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100"
                            />
                          </div>
                        ))}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" variant="outline" className="h-7 text-[10px] border-zinc-700"
                          onClick={() => setAdvMix({ ios: 40, android: 40, desktop: 20 })}>40/40/20</Button>
                        <Button type="button" size="sm" variant="outline" className="h-7 text-[10px] border-zinc-700"
                          onClick={() => setAdvMix({ ios: 50, android: 50, desktop: 0 })}>50/50 mobile</Button>
                        <Button type="button" size="sm" variant="outline" className="h-7 text-[10px] border-zinc-700"
                          onClick={() => setAdvMix({ ios: 0, android: 0, desktop: 100 })}>100% desktop</Button>
                        <Button type="button" size="sm" variant="outline" className="h-7 text-[10px] border-zinc-700"
                          onClick={() => setAdvMix({ ios: 0, android: 100, desktop: 0 })}>100% Android</Button>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <Label className="text-zinc-300 text-xs">Device</Label>
                          <select data-testid="bp-device-mode" value={advDeviceMode}
                            onChange={(e) => setAdvDeviceMode(e.target.value)}
                            className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                            <option value="random">Random unique models</option>
                            <option value="specific">Specific device</option>
                          </select>
                        </div>
                        <div>
                          <Label className="text-zinc-300 text-xs">Resolution</Label>
                          <select data-testid="bp-resolution-mode" value={advResolutionMode}
                            onChange={(e) => setAdvResolutionMode(e.target.value)}
                            className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                            <option value="match_device">Match device</option>
                            <option value="random">Random per profile</option>
                            <option value="exact">Exact W×H</option>
                          </select>
                        </div>
                      </div>
                      {advDeviceMode === "specific" && (
                        <div>
                          <Label className="text-zinc-300 text-xs">Specific device</Label>
                          <select data-testid="bp-device-id" value={advDeviceId}
                            onChange={(e) => setAdvDeviceId(e.target.value)}
                            className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                            <option value="">Pick a device…</option>
                            {deviceCatalog.map((d) => (
                              <option key={d.id} value={d.id}>{d.label} ({d.platform})</option>
                            ))}
                          </select>
                          <p className="text-[10px] text-zinc-500 mt-1">Specific device forces 100% that platform for the whole batch.</p>
                        </div>
                      )}
                      {advResolutionMode === "exact" && (
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <Label className="text-zinc-300 text-xs">Width</Label>
                            <Input type="number" value={form.viewport.width}
                              onChange={(e) => setForm({ ...form, viewport: { ...form.viewport, width: parseInt(e.target.value) || 0 } })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                          </div>
                          <div>
                            <Label className="text-zinc-300 text-xs">Height</Label>
                            <Input type="number" value={form.viewport.height}
                              onChange={(e) => setForm({ ...form, viewport: { ...form.viewport, height: parseInt(e.target.value) || 0 } })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                          </div>
                        </div>
                      )}
                      <p className="text-[11px] text-zinc-500">
                        iOS → Safari engine (real iPhone browsing). Android / Desktop → Chromium. Each profile gets a unique UA + device model.
                      </p>
                    </div>
                  )}
                  {editingId && (
                    <div className="col-span-2">
                      <Label className="text-zinc-300 text-xs">User Agent <span className="text-zinc-500">(leave blank = auto-generate)</span></Label>
                      <Input data-testid="bp-form-ua" value={form.user_agent} onChange={(e) => setForm({ ...form, user_agent: e.target.value })}
                        className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs" placeholder="Auto" />
                    </div>
                  )}
                  {editingId && (
                  <>
                  <div>
                    <Label className="text-zinc-300 text-xs">Viewport Width</Label>
                    <Input type="number" value={form.viewport.width}
                      onChange={(e) => setForm({ ...form, viewport: { ...form.viewport, width: parseInt(e.target.value) || 0 } })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
                  <div>
                    <Label className="text-zinc-300 text-xs">Viewport Height</Label>
                    <Input type="number" value={form.viewport.height}
                      onChange={(e) => setForm({ ...form, viewport: { ...form.viewport, height: parseInt(e.target.value) || 0 } })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
                  </>
                  )}
                  <div className="col-span-2">
                    <Label className="text-zinc-300 text-xs">Notes</Label>
                    <Textarea data-testid="bp-form-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
                      rows={2} className="bg-zinc-900 border-zinc-700 text-zinc-100" placeholder="Optional notes (e.g. 'Used for advertiser X login')" />
                  </div>
                </div>

                {/* ── 2026-01: UA Generator section (create mode only) ── */}
                {!editingId && (
                  <div className="p-3 rounded-lg border border-blue-500/30 bg-blue-950/10 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-blue-300 text-sm font-semibold">📱 User-Agent Generator</span>
                      <span className="text-[10px] text-zinc-500">Same engine as /ua-generator — one UA per profile, all unique</span>
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <Label className="text-zinc-300 text-xs">App</Label>
                        <select data-testid="bp-ua-app" value={advUA.app}
                          onChange={(e) => setAdvUA({ ...advUA, app: e.target.value })}
                          className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                          <option value="browser">Browser (Chrome/Safari)</option>
                          <option value="instagram">Instagram</option>
                          <option value="facebook">Facebook</option>
                          <option value="tiktok">TikTok</option>
                          <option value="youtube">YouTube</option>
                          <option value="whatsapp">WhatsApp</option>
                          <option value="gsearch">Google Search</option>
                          <option value="gchrome">Google Native (Chrome)</option>
                          <option value="pinterest">Pinterest</option>
                          <option value="snapchat">Snapchat</option>
                        </select>
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Operating System</Label>
                        <select data-testid="bp-ua-platform" value={advUA.platform}
                          onChange={(e) => setAdvUA({ ...advUA, platform: e.target.value })}
                          className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                          <option value="any">Any</option>
                          <option value="android">Android</option>
                          <option value="ios">iOS</option>
                          <option value="desktop">Desktop</option>
                        </select>
                        <p className="text-[10px] text-amber-400/90 mt-1">
                          Platform mix ON → OS auto (ignore Operating System)
                        </p>
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Region / Country</Label>
                        <select data-testid="bp-ua-region" value={advUA.region}
                          onChange={(e) => setAdvUA({ ...advUA, region: e.target.value })}
                          className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                          {COUNTRY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                    </div>
                    <div>
                      <Label className="text-zinc-300 text-xs">Brand <span className="text-zinc-500">(optional — leave blank for random)</span></Label>
                      <select data-testid="bp-ua-brand" value={advUA.brand || ""}
                        onChange={(e) => setAdvUA({ ...advUA, brand: e.target.value })}
                        className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                        <option value="">Random</option>
                        <option value="samsung">Samsung</option>
                        <option value="google">Google Pixel</option>
                        <option value="motorola">Motorola</option>
                        <option value="xiaomi">Xiaomi</option>
                        <option value="oneplus">OnePlus</option>
                        <option value="realme">Realme</option>
                        <option value="oppo">Oppo</option>
                        <option value="vivo">Vivo</option>
                        <option value="iphone">iPhone</option>
                        <option value="ipad">iPad</option>
                        <option value="windows">Windows</option>
                        <option value="mac">Mac</option>
                        <option value="linux">Linux</option>
                      </select>
                    </div>
                  </div>
                )}

                {/* Agency fields — create mode */}
                {!editingId && (
                  <div className="p-3 rounded-lg border border-violet-500/30 bg-violet-950/10 space-y-3">
                    <span className="text-violet-300 text-sm font-semibold">Folder · Tags · Geo · Links</span>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <Label className="text-zinc-300 text-xs">Folder</Label>
                        <Input value={advFolder} onChange={(e) => setAdvFolder(e.target.value)}
                          list="bp-folder-suggestions"
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" placeholder="e.g. Clients / US Ads" />
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Tags <span className="text-zinc-500">(csv)</span></Label>
                        <Input value={advTags} onChange={(e) => setAdvTags(e.target.value)}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" placeholder="warmup, client-a" />
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Timezone</Label>
                        <Input value={advTimezone} onChange={(e) => setAdvTimezone(e.target.value)}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" placeholder="America/New_York (blank = default)" />
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Locale</Label>
                        <Input value={advLocale} onChange={(e) => setAdvLocale(e.target.value)}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" placeholder="en-US (blank = default)" />
                      </div>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                      <input type="checkbox" checked={advGeoFollow}
                        onChange={(e) => setAdvGeoFollow(e.target.checked)}
                        className="w-4 h-4 rounded accent-fuchsia-500" />
                      geo_follow_proxy — timezone/locale follow proxy IP
                    </label>
                    <div>
                      <Label className="text-zinc-300 text-xs">Quick links <span className="text-zinc-500">(one URL per line)</span></Label>
                      <Textarea value={advQuickLinks} onChange={(e) => setAdvQuickLinks(e.target.value)}
                        rows={2} className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs"
                        placeholder={"https://mail.google.com\nhttps://facebook.com"} />
                    </div>
                  </div>
                )}

                <ReferrerProProfilePanel
                  referrer={form.referrer}
                  onChange={(referrer) => setForm({ ...form, referrer })}
                  profileCountry={form.country}
                  testIdPrefix="bp"
                />

                {/* Anti-Detect */}
                <div className="p-3 rounded-lg border border-fuchsia-500/30 bg-fuchsia-950/10">
                  <label className="flex items-center justify-between cursor-pointer">
                    <div>
                      <span className="text-fuchsia-300 text-sm font-semibold">🛡️ Anti-Detect</span>
                      <p className="text-[11px] text-zinc-400 mt-0.5">One toggle — auto-tunes all internal protection layers (TLS prewarm, behavioral bio, identity persist, browser rotation).</p>
                    </div>
                    {editingId ? (
                      <input data-testid="bp-form-antidetect"
                        type="checkbox"
                        checked={form.anti_detect.master}
                        onChange={(e) => setForm({ ...form, anti_detect: {
                          ...form.anti_detect, master: e.target.checked,
                          tls_prewarm: e.target.checked,
                          behavioral_bio: e.target.checked,
                          browser_variant: e.target.checked ? "rotate" : "auto",
                          identity_persist: e.target.checked,
                        }})}
                        className="w-5 h-5 rounded accent-fuchsia-500" />
                    ) : (
                      <input data-testid="bp-form-antidetect"
                        type="checkbox"
                        checked={advAntiDetect}
                        onChange={(e) => setAdvAntiDetect(e.target.checked)}
                        className="w-5 h-5 rounded accent-fuchsia-500" />
                    )}
                  </label>
                  {(editingId || advAntiDetect) && (
                    <div className="mt-3">
                      <button
                        type="button"
                        className="text-[11px] text-fuchsia-300/90 hover:text-fuchsia-200 underline"
                        onClick={() => setShowFpAdvanced((v) => !v)}
                      >
                        {showFpAdvanced ? "Hide" : "Show"} advanced anti-detect
                      </button>
                      {showFpAdvanced && (
                        <div className="mt-2 space-y-3 text-xs text-zinc-300 border-t border-fuchsia-500/20 pt-2">
                          {editingId && (
                            <>
                              <label className="flex items-center gap-2">
                                <input type="checkbox" className="accent-fuchsia-500" checked={!!form.anti_detect.master}
                                  onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, master: e.target.checked } })} />
                                master
                              </label>
                              <label className="flex items-center gap-2">
                                <input type="checkbox" className="accent-fuchsia-500" checked={!!form.anti_detect.behavioral_bio}
                                  onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, behavioral_bio: e.target.checked } })} />
                                behavioral_bio
                              </label>
                              <label className="flex items-center gap-2">
                                <input type="checkbox" className="accent-fuchsia-500" checked={!!form.anti_detect.paranoia_mode}
                                  onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, paranoia_mode: e.target.checked } })} />
                                paranoia_mode
                              </label>
                            </>
                          )}
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              ["canvas_mode", "Canvas", "noise = slight spoof; real = pass-through; off = no inject"],
                              ["webgl_mode", "WebGL", "Align GPU vendor/renderer noise with UA"],
                              ["audio_mode", "Audio", "AudioContext fingerprint noise"],
                              ["font_mode", "Fonts", "Font enumeration noise"],
                            ].map(([key, label, help]) => (
                              <div key={key}>
                                <Label className="text-zinc-400 text-[10px]">{label}</Label>
                                <select
                                  value={form.anti_detect?.[key] || "noise"}
                                  onChange={(e) => setForm({
                                    ...form,
                                    anti_detect: { ...form.anti_detect, [key]: e.target.value },
                                  })}
                                  className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs"
                                >
                                  {FP_MODE_OPTIONS.map((o) => (
                                    <option key={o.value} value={o.value}>{o.label}</option>
                                  ))}
                                </select>
                                <p className="text-[9px] text-zinc-500 mt-0.5">{help}</p>
                              </div>
                            ))}
                            <div className="col-span-2">
                              <Label className="text-zinc-400 text-[10px]">Browser kernel</Label>
                              <select
                                data-testid="bp-browser-kernel"
                                value={form.anti_detect?.browser_kernel || "auto"}
                                onChange={(e) => setForm({
                                  ...form,
                                  anti_detect: { ...form.anti_detect, browser_kernel: e.target.value },
                                })}
                                className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs"
                              >
                                <option value="auto">Krexion Stealth (auto)</option>
                                <option value="cloak">Krexion Stealth Chromium</option>
                                <option value="patchright">Krexion Hardened Chromium</option>
                                <option value="playwright">Krexion Standard Chromium</option>
                                <option value="firefox">Krexion Firefox</option>
                                <option value="chrome">System Chrome (not recommended)</option>
                              </select>
                              <p className="text-[9px] text-zinc-500 mt-0.5">
                                Auto selects the strongest Krexion stealth kernel available on this PC
                              </p>
                            </div>
                            <label className="col-span-2 flex items-start gap-2">
                              <input
                                type="checkbox"
                                className="accent-fuchsia-500 mt-0.5"
                                data-testid="bp-fingerprint-win"
                                checked={form.anti_detect?.fingerprint_win !== false}
                                onChange={(e) => setForm({
                                  ...form,
                                  anti_detect: { ...form.anti_detect, fingerprint_win: e.target.checked },
                                })}
                              />
                              <span>
                                Fingerprint WIN pack (CreepJS-class)
                                <span className="block text-[9px] text-zinc-500">
                                  iframe / Worker / OffscreenCanvas / chrome.runtime coherence — recommended ON
                                </span>
                              </span>
                            </label>
                            <label className="col-span-2 flex items-start gap-2">
                              <input
                                type="checkbox"
                                className="accent-fuchsia-500 mt-0.5"
                                checked={form.anti_detect?.fingerprint_win_prefer_real !== false}
                                onChange={(e) => setForm({
                                  ...form,
                                  anti_detect: {
                                    ...form.anti_detect,
                                    fingerprint_win_prefer_real: e.target.checked,
                                  },
                                })}
                              />
                              <span>
                                Prefer real canvas/WebGL under Stealth kernel
                                <span className="block text-[9px] text-zinc-500">
                                  Quiet path: C++ kernel owns FP, less JS noise (CreepJS safer)
                                </span>
                              </span>
                            </label>
                            <div className="col-span-2">
                              <Label className="text-zinc-400 text-[10px]">WebRTC</Label>
                              <select
                                value={form.anti_detect?.webrtc_mode || "proxy"}
                                onChange={(e) => setForm({
                                  ...form,
                                  anti_detect: { ...form.anti_detect, webrtc_mode: e.target.value },
                                })}
                                className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs"
                              >
                                {WEBRTC_MODE_OPTIONS.map((o) => (
                                  <option key={o.value} value={o.value}>{o.label}</option>
                                ))}
                              </select>
                              <p className="text-[9px] text-zinc-500 mt-0.5">
                                proxy = leak via proxy IP; disabled = block; real = system WebRTC
                              </p>
                            </div>
                          </div>
                          <label className="flex items-start gap-2">
                            <input type="checkbox" className="accent-fuchsia-500 mt-0.5" checked={!!form.anti_detect.tls_prewarm}
                              onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, tls_prewarm: e.target.checked } })} />
                            <span>
                              tls_prewarm
                              <span className="block text-[9px] text-zinc-500">Warm TLS session to start URL before browse</span>
                            </span>
                          </label>
                          <label className="flex items-start gap-2">
                            <input type="checkbox" className="accent-fuchsia-500 mt-0.5" checked={!!form.anti_detect.use_persistent_context}
                              onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, use_persistent_context: e.target.checked } })} />
                            <span>
                              use_persistent_context
                              <span className="block text-[9px] text-zinc-500">Disk profile dir instead of ephemeral + storage_state</span>
                            </span>
                          </label>
                          <label className="flex items-start gap-2">
                            <input type="checkbox" className="accent-fuchsia-500 mt-0.5" checked={!!form.anti_detect.proxy_check_on_launch}
                              onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, proxy_check_on_launch: e.target.checked } })} />
                            <span>
                              proxy_check_on_launch
                              <span className="block text-[9px] text-zinc-500">Verify exit IP when launching</span>
                            </span>
                          </label>
                          <label className="flex items-start gap-2">
                            <input type="checkbox" className="accent-fuchsia-500 mt-0.5" checked={!!form.anti_detect.proxy_check_block_on_fail}
                              onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, proxy_check_block_on_fail: e.target.checked } })} />
                            <span>
                              proxy_check_block_on_fail
                              <span className="block text-[9px] text-zinc-500">Abort launch if proxy check fails</span>
                            </span>
                          </label>
                          <label className="flex items-start gap-2">
                            <input type="checkbox" className="accent-fuchsia-500 mt-0.5" checked={!!form.anti_detect.allow_extensions}
                              onChange={(e) => setForm({ ...form, anti_detect: { ...form.anti_detect, allow_extensions: e.target.checked } })} />
                            <span>
                              allow_extensions
                              <span className="block text-[9px] text-zinc-500">Load unpacked Chromium extensions (requires extensions_dir or KREXION_PROFILE_EXTENSIONS env)</span>
                            </span>
                          </label>
                          {form.anti_detect.allow_extensions && (
                            <div>
                              <Label className="text-zinc-400 text-[10px]">extensions_dir (optional)</Label>
                              <Input
                                value={form.anti_detect.extensions_dir || ""}
                                onChange={(e) => setForm({
                                  ...form,
                                  anti_detect: { ...form.anti_detect, extensions_dir: e.target.value },
                                })}
                                placeholder="C:\\path\\to\\unpacked\\extension"
                                className="bg-zinc-900 border-zinc-700 text-zinc-100 h-8 text-xs mt-1"
                              />
                            </div>
                          )}
                          {editingId && (
                            <p className="text-[10px] text-zinc-500 font-mono">
                              fingerprint: {form.fingerprint_short || "(none yet — set after first launch)"}
                            </p>
                          )}
                          {!editingId && (
                            <p className="text-[10px] text-zinc-500">
                              Modes are sent with advanced-create (backend AntiDetectConfig). Defaults match WIN bundle.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Edit-mode agency fields */}
                {editingId && (
                  <div className="p-3 rounded-lg border border-violet-500/30 bg-violet-950/10 space-y-3">
                    <span className="text-violet-300 text-sm font-semibold">Folder · Tags · Geo · Referrer · Links</span>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <Label className="text-zinc-300 text-xs">Folder</Label>
                        <Input value={form.folder || ""}
                          onChange={(e) => setForm({ ...form, folder: e.target.value })}
                          list="bp-folder-suggestions"
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Tags <span className="text-zinc-500">(csv)</span></Label>
                        <Input
                          value={Array.isArray(form.tags) ? form.tags.join(", ") : (form.tags || "")}
                          onChange={(e) => setForm({
                            ...form,
                            tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                          })}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Timezone</Label>
                        <Input value={form.timezone || ""}
                          onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                      </div>
                      <div>
                        <Label className="text-zinc-300 text-xs">Locale</Label>
                        <Input value={form.locale || ""}
                          onChange={(e) => setForm({ ...form, locale: e.target.value })}
                          className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                      </div>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                      <input type="checkbox" checked={form.geo_follow_proxy !== false}
                        onChange={(e) => setForm({ ...form, geo_follow_proxy: e.target.checked })}
                        className="w-4 h-4 rounded accent-fuchsia-500" />
                      geo_follow_proxy
                    </label>
                    <div>
                      <Label className="text-zinc-300 text-xs">Quick links <span className="text-zinc-500">(one URL per line)</span></Label>
                      <Textarea
                        value={Array.isArray(form.quick_links) ? form.quick_links.join("\n") : ""}
                        onChange={(e) => setForm({
                          ...form,
                          quick_links: e.target.value.split(/\r?\n/).map((u) => u.trim()).filter(Boolean).slice(0, 12),
                        })}
                        rows={2}
                        className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs"
                      />
                    </div>
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button type="button" size="sm" variant="outline" className="h-7 text-xs border-zinc-700 text-zinc-300"
                        onClick={() => openCookieDialog(editingId)}>
                        <Cookie className="w-3 h-3 mr-1" /> Manage cookies
                      </Button>
                      <Button type="button" size="sm" variant="outline" className="h-7 text-xs border-zinc-700 text-zinc-300"
                        onClick={() => handleProxyCheck(editingId)} disabled={proxyBusy === editingId}>
                        Check proxy
                      </Button>
                    </div>
                  </div>
                )}

                {/* Proxy — create vs edit modes use different controls */}
                {!editingId ? (
                  <div className="p-3 rounded-lg border border-cyan-500/30 bg-cyan-950/10 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-cyan-300 text-sm font-semibold">🌍 Proxy</span>
                      <span className="text-[10px] text-zinc-500">Team-unique exit IP at create — IP isolation ledger (duplicate block)</span>
                    </div>
                    {/* v2.4.0 — Provider dropdown at the very top of Proxy section */}
                    <div className="pb-2 border-b border-cyan-500/20">
                      <ProxyProviderSelect
                        value={advProxy.provider_id}
                        onChange={(v) => setAdvProxy({ ...advProxy, provider_id: v, mode: v ? "provider" : "none" })}
                        label="Proxy provider (from Settings)"
                        labelDefault="(pick a mode below instead)"
                        testIdPrefix="bp-adv-proxy-provider"
                      />
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <label className={`cursor-pointer p-2 rounded border text-center text-xs ${advProxy.mode === "none" ? "border-cyan-400 bg-cyan-500/15 text-cyan-200" : "border-zinc-700 text-zinc-400 hover:bg-zinc-900"}`}>
                        <input type="radio" name="proxy_mode" value="none" className="sr-only"
                          checked={advProxy.mode === "none"}
                          onChange={() => setAdvProxy({ ...advProxy, mode: "none" })} />
                        <div className="font-semibold">No Proxy</div>
                        <div className="text-[10px] mt-0.5 opacity-70">Direct connection</div>
                      </label>
                      <label data-testid="bp-proxy-mode-proxyjet" className={`cursor-pointer p-2 rounded border text-center text-xs ${advProxy.mode === "proxyjet" ? "border-amber-400 bg-amber-500/15 text-amber-200" : "border-zinc-700 text-zinc-400 hover:bg-zinc-900"}`}>
                        <input type="radio" name="proxy_mode" value="proxyjet" className="sr-only"
                          checked={advProxy.mode === "proxyjet"}
                          onChange={() => setAdvProxy({ ...advProxy, mode: "proxyjet" })} />
                        <div className="font-semibold">⚡ Generate (Provider)</div>
                        <div className="text-[10px] mt-0.5 opacity-70">Unique IP per profile</div>
                      </label>
                      <label className={`cursor-pointer p-2 rounded border text-center text-xs ${advProxy.mode === "manual" ? "border-cyan-400 bg-cyan-500/15 text-cyan-200" : "border-zinc-700 text-zinc-400 hover:bg-zinc-900"}`}>
                        <input type="radio" name="proxy_mode" value="manual" className="sr-only"
                          checked={advProxy.mode === "manual"}
                          onChange={() => setAdvProxy({ ...advProxy, mode: "manual" })} />
                        <div className="font-semibold">Manual</div>
                        <div className="text-[10px] mt-0.5 opacity-70">Paste host/port</div>
                      </label>
                    </div>

                    {advProxy.mode === "proxyjet" && (
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <Label className="text-zinc-300 text-[11px]">Country</Label>
                          <select data-testid="bp-pj-country" value={advProxy.country}
                            onChange={(e) => setAdvProxy({ ...advProxy, country: e.target.value })}
                            className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                            {COUNTRY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        </div>
                        <div>
                          <Label className="text-zinc-300 text-[11px]">State <span className="text-zinc-500">(US only)</span></Label>
                          {/* 2026-06 — Customer ask: state should be a
                              dropdown, no typing. The dropdown is only
                              meaningful when country=US, but we keep
                              it visible (disabled+greyed) for non-US
                              picks so the form layout stays stable. */}
                          <select
                            value={advProxy.state || ""}
                            onChange={(e) => setAdvProxy({ ...advProxy, state: e.target.value })}
                            disabled={(advProxy.country || "US").toUpperCase() !== "US"}
                            data-testid="bp-pj-state"
                            className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            {US_STATE_OPTIONS.map((s) => (
                              <option key={s.code || "any"} value={s.code}>
                                {s.code ? `${s.code} — ${s.name}` : s.name}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <Label className="text-zinc-300 text-[11px]">Session</Label>
                          <select value={advProxy.sticky_minutes || 0}
                            onChange={(e) => setAdvProxy({ ...advProxy, sticky_minutes: parseInt(e.target.value) || 0 })}
                            className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                            <option value={0}>Rotating (fresh IP)</option>
                            <option value={5}>Sticky 5 min</option>
                            <option value={15}>Sticky 15 min</option>
                            <option value={30}>Sticky 30 min</option>
                            <option value={60}>Sticky 60 min</option>
                            <option value={120}>Sticky 120 min</option>
                          </select>
                        </div>
                      </div>
                    )}

                    {advProxy.mode === "manual" && (
                      <div className="space-y-3">
                        {/* Provider hint */}
                        <div className="p-2.5 rounded-md bg-zinc-900/60 border border-zinc-800 text-[11px] text-zinc-400">
                          <span className="text-zinc-200 font-semibold">💡 Works with any proxy provider</span> — BrightData, SmartProxy, Oxylabs, IPRoyal, Nimble, Rayobyte, GeoNode, BestGo, DataImpulse, etc.
                          Paste the proxy string OR fill the fields below.
                        </div>

                        <div>
                          <Label className="text-zinc-300 text-[11px] mb-1 block">
                            Unique proxies <span className="text-zinc-500">(one line per profile — preferred for bulk)</span>
                          </Label>
                          <Textarea
                            value={advProxyLines}
                            onChange={(e) => setAdvProxyLines(e.target.value)}
                            rows={4}
                            className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs"
                            placeholder={"http://user:pass@host:port\nhost:port:user:pass"}
                          />
                          <p className="text-[10px] text-zinc-500 mt-1">
                            When lines are set, each profile gets the next unique proxy. Single server below is still supported as fallback.
                          </p>
                        </div>

                        {/* Paste-and-parse — accepts all 5 common formats */}
                        <div>
                          <Label className="text-zinc-300 text-[11px] mb-1 block">
                            Paste proxy string <span className="text-zinc-500">(auto-detects format)</span>
                          </Label>
                          <div className="flex gap-2">
                            <Input
                              data-testid="bp-manual-proxy-paste"
                              placeholder="e.g. http://user:pass@host:port  OR  host:port:user:pass"
                              value={advProxy.paste_input || ""}
                              onChange={(e) => setAdvProxy({ ...advProxy, paste_input: e.target.value })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs flex-1"
                            />
                            <Button
                              type="button"
                              data-testid="bp-manual-proxy-parse-btn"
                              variant="secondary"
                              onClick={() => {
                                // Parse any of 5 proxy string formats and fill the
                                // split fields below. Mirrors the backend parser in
                                // /app/backend/browser_profile_module.py so what the
                                // customer sees here matches what the engine uses.
                                const raw = (advProxy.paste_input || "").trim();
                                if (!raw) return;
                                let protocol = "http";
                                let host = "";
                                let port = "";
                                let username = "";
                                let password = "";
                                try {
                                  let rest = raw;
                                  if (rest.includes("://")) {
                                    const parts = rest.split("://");
                                    protocol = (parts[0] || "http").toLowerCase();
                                    rest = parts.slice(1).join("://");
                                  }
                                  if (rest.includes("@")) {
                                    // user:pass@host:port
                                    const at = rest.lastIndexOf("@");
                                    const creds = rest.slice(0, at);
                                    const hp = rest.slice(at + 1);
                                    const c1 = creds.indexOf(":");
                                    username = c1 >= 0 ? creds.slice(0, c1) : creds;
                                    password = c1 >= 0 ? creds.slice(c1 + 1) : "";
                                    const hpParts = hp.split(":");
                                    host = hpParts[0] || "";
                                    port = hpParts[1] || "";
                                  } else {
                                    // host:port  OR  host:port:user:pass
                                    const parts = rest.split(":");
                                    host = parts[0] || "";
                                    port = parts[1] || "";
                                    if (parts.length >= 4) {
                                      username = parts[2] || "";
                                      password = parts.slice(3).join(":");
                                    }
                                  }
                                  if (!host || !port) {
                                    toast.error("Could not extract host or port from that string");
                                    return;
                                  }
                                  setAdvProxy({
                                    ...advProxy,
                                    protocol,
                                    host,
                                    port,
                                    username,
                                    password,
                                    server: `${protocol}://${host}:${port}`,
                                  });
                                  toast.success(`Parsed: ${protocol}://${host}:${port}${username ? " (with auth)" : ""}`);
                                } catch (e) {
                                  toast.error("Parse failed: " + (e.message || "unknown"));
                                }
                              }}
                              className="text-xs px-3"
                            >
                              Parse & fill
                            </Button>
                          </div>
                        </div>

                        {/* Divider */}
                        <div className="flex items-center gap-2 text-[10px] text-zinc-600 uppercase tracking-wider">
                          <div className="flex-1 h-px bg-zinc-800" />
                          <span>or fill manually</span>
                          <div className="flex-1 h-px bg-zinc-800" />
                        </div>

                        {/* Split fields */}
                        <div className="grid grid-cols-12 gap-2">
                          <div className="col-span-3">
                            <Label className="text-zinc-300 text-[11px] mb-1 block">Protocol</Label>
                            <select
                              data-testid="bp-manual-proxy-protocol"
                              value={advProxy.protocol || "http"}
                              onChange={(e) => {
                                const p = e.target.value;
                                const h = advProxy.host || "";
                                const po = advProxy.port || "";
                                setAdvProxy({
                                  ...advProxy,
                                  protocol: p,
                                  server: h && po ? `${p}://${h}:${po}` : advProxy.server,
                                });
                              }}
                              className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs"
                            >
                              <option value="http">HTTP</option>
                              <option value="https">HTTPS</option>
                              <option value="socks5">SOCKS5</option>
                              <option value="socks5h">SOCKS5H</option>
                              <option value="socks4">SOCKS4</option>
                            </select>
                          </div>
                          <div className="col-span-6">
                            <Label className="text-zinc-300 text-[11px] mb-1 block">Host</Label>
                            <Input
                              data-testid="bp-manual-proxy-host"
                              placeholder="e.g. gate.smartproxy.com"
                              value={advProxy.host || ""}
                              onChange={(e) => {
                                const h = e.target.value;
                                const p = advProxy.protocol || "http";
                                const po = advProxy.port || "";
                                setAdvProxy({
                                  ...advProxy,
                                  host: h,
                                  server: h && po ? `${p}://${h}:${po}` : "",
                                });
                              }}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                            />
                          </div>
                          <div className="col-span-3">
                            <Label className="text-zinc-300 text-[11px] mb-1 block">Port</Label>
                            <Input
                              data-testid="bp-manual-proxy-port"
                              placeholder="7000"
                              inputMode="numeric"
                              value={advProxy.port || ""}
                              onChange={(e) => {
                                const po = e.target.value.replace(/\D+/g, "");
                                const p = advProxy.protocol || "http";
                                const h = advProxy.host || "";
                                setAdvProxy({
                                  ...advProxy,
                                  port: po,
                                  server: h && po ? `${p}://${h}:${po}` : "",
                                });
                              }}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                            />
                          </div>
                          <div className="col-span-6">
                            <Label className="text-zinc-300 text-[11px] mb-1 block">Username <span className="text-zinc-500">(optional)</span></Label>
                            <Input
                              data-testid="bp-manual-proxy-user"
                              placeholder="proxy username"
                              value={advProxy.username || ""}
                              onChange={(e) => setAdvProxy({ ...advProxy, username: e.target.value })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                            />
                          </div>
                          <div className="col-span-6">
                            <Label className="text-zinc-300 text-[11px] mb-1 block">Password <span className="text-zinc-500">(optional)</span></Label>
                            <Input
                              data-testid="bp-manual-proxy-pass"
                              placeholder="proxy password"
                              type="password"
                              value={advProxy.password || ""}
                              onChange={(e) => setAdvProxy({ ...advProxy, password: e.target.value })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs"
                            />
                          </div>
                        </div>

                        {/* Resolved preview + apply-to-batch note */}
                        {advProxy.server && (
                          <div className="text-[11px] font-mono px-2.5 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-cyan-300 break-all">
                            ✓ {advProxy.server}{advProxy.username ? `  (auth: ${advProxy.username})` : ""}
                          </div>
                        )}
                        <p className="text-[10px] text-zinc-500">
                          {advProxyLines.trim()
                            ? "Unique proxy lines above take priority (one per profile)."
                            : "Same proxy applied to every profile in this batch (or paste unique lines above)."}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  /* Edit-mode keeps the legacy compact proxy section */
                  <div className="p-3 rounded-lg border border-cyan-500/30 bg-cyan-950/10">
                    <label className="flex items-center justify-between cursor-pointer mb-2">
                      <span className="text-cyan-300 text-sm font-semibold">🌍 Proxy</span>
                      <input data-testid="bp-form-proxy-enable"
                        type="checkbox"
                        checked={form.proxy.enabled}
                        onChange={(e) => setForm({ ...form, proxy: { ...form.proxy, enabled: e.target.checked } })}
                        className="w-4 h-4 rounded accent-cyan-500" />
                    </label>
                    {form.proxy.enabled && (
                      <div className="space-y-2">
                        {/* v2.4.0 — Multi-provider dropdown */}
                        <ProxyProviderSelect
                          value={form.proxy.provider_id}
                          onChange={(v) => setForm({ ...form, proxy: { ...form.proxy, provider_id: v } })}
                          label="Provider (optional)"
                          labelDefault="(use manual proxy fields below)"
                          testIdPrefix="bp-proxy-provider"
                        />
                        <label className="flex items-center gap-2 text-xs text-zinc-300">
                          <input type="checkbox" checked={form.proxy.use_proxyjet}
                            onChange={(e) => setForm({ ...form, proxy: { ...form.proxy, use_proxyjet: e.target.checked } })}
                            className="w-4 h-4 rounded accent-cyan-500" />
                          Auto-generate unique proxy via selected Provider (same as RUT)
                        </label>
                        {!form.proxy.use_proxyjet && (
                          <div className="grid grid-cols-2 gap-2">
                            <Input placeholder="http://host:port" value={form.proxy.server}
                              onChange={(e) => setForm({ ...form, proxy: { ...form.proxy, server: e.target.value } })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs" />
                            <div />
                            <Input placeholder="username" value={form.proxy.username}
                              onChange={(e) => setForm({ ...form, proxy: { ...form.proxy, username: e.target.value } })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs" />
                            <Input placeholder="password" type="password" value={form.proxy.password}
                              onChange={(e) => setForm({ ...form, proxy: { ...form.proxy, password: e.target.value } })}
                              className="bg-zinc-900 border-zinc-700 text-zinc-100 text-xs" />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div className="p-4 border-t border-zinc-800 flex justify-end gap-2 sticky bottom-0 bg-zinc-950">
                <Button onClick={() => closeCreateModal(true)} variant="outline" className="border-zinc-700 text-zinc-300">Cancel</Button>
                <Button data-testid="bp-form-save" onClick={handleCreate} disabled={advCreating}
                  className="bg-fuchsia-600 hover:bg-fuchsia-700 text-white disabled:opacity-60">
                  {editingId
                    ? "Save Changes"
                    : (advCreating
                        ? "Creating…"
                        : (advCount > 1 ? `Create ${advCount} Profiles` : "Create Profile"))}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Cookie dialog */}
        {cookieDialog.open && (
          <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setCookieDialog({ id: null, text: "", open: false })}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}>
              <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
                  <Cookie className="w-4 h-4 text-emerald-400" /> Cookies / storage_state
                </h3>
                <Button size="sm" variant="outline" className="h-7 text-xs border-zinc-700"
                  onClick={() => setCookieDialog({ id: null, text: "", open: false })}>Close</Button>
              </div>
              <div className="p-4 flex-1 overflow-y-auto">
                <Textarea
                  value={cookieDialog.text}
                  onChange={(e) => setCookieDialog({ ...cookieDialog, text: e.target.value })}
                  rows={16}
                  className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-[11px]"
                />
                <p className="text-[10px] text-zinc-500 mt-2">
                  Paste Playwright storage_state JSON, or a cookies array. Export is already loaded.
                </p>
              </div>
              <div className="p-3 border-t border-zinc-800 flex justify-end gap-2">
                <Button size="sm" variant="outline" className="border-red-900/60 text-red-400 h-7 text-xs"
                  onClick={handleCookieClear}>Clear</Button>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs"
                  onClick={handleCookieSave}>Import / Save</Button>
              </div>
            </div>
          </div>
        )}

        {/* Share / ACL dialog */}
        {shareDialog.id && (
          <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setShareDialog({ id: null, email: "", includeCookies: false, mode: "acl", role: "editor" })}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-md w-full p-5"
              onClick={(e) => e.stopPropagation()}>
              <h3 className="text-sm font-semibold text-zinc-100 mb-3">Team share</h3>
              <Label className="text-zinc-300 text-xs">Mode</Label>
              <select
                className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded-md h-9 text-xs mb-3 px-2"
                value={shareDialog.mode || "acl"}
                onChange={(e) => setShareDialog({ ...shareDialog, mode: e.target.value })}
                data-testid="bp-share-mode"
              >
                <option value="acl">Live ACL (same profile)</option>
                <option value="clone">Clone into their account</option>
              </select>
              <Label className="text-zinc-300 text-xs">Target email</Label>
              <Input
                value={shareDialog.email}
                onChange={(e) => setShareDialog({ ...shareDialog, email: e.target.value })}
                className="bg-zinc-900 border-zinc-700 text-zinc-100 mb-3"
                placeholder="teammate@company.com"
              />
              {shareDialog.mode !== "clone" ? (
                <>
                  <Label className="text-zinc-300 text-xs">Role</Label>
                  <select
                    className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded-md h-9 text-xs mb-4 px-2"
                    value={shareDialog.role || "editor"}
                    onChange={(e) => setShareDialog({ ...shareDialog, role: e.target.value })}
                    data-testid="bp-share-role"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                  </select>
                </>
              ) : (
                <label className="flex items-center gap-2 text-xs text-zinc-300 mb-4 cursor-pointer">
                  <input type="checkbox" className="accent-fuchsia-500"
                    checked={shareDialog.includeCookies}
                    onChange={(e) => setShareDialog({ ...shareDialog, includeCookies: e.target.checked })} />
                  Include cookies / storage state
                </label>
              )}
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs"
                  onClick={() => setShareDialog({ id: null, email: "", includeCookies: false, mode: "acl", role: "editor" })}>Cancel</Button>
                <Button size="sm" className="bg-fuchsia-600 hover:bg-fuchsia-700 text-white h-7 text-xs"
                  onClick={handleShare} data-testid="bp-share-confirm">Share</Button>
              </div>
            </div>
          </div>
        )}

        {/* Cloud phone / Krexion Android dialog */}
        {cloudPhoneDialog.id && (
          <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setCloudPhoneDialog({
              id: null, provider: "cpi", partnerUrl: "", deviceId: "", label: "", devices: [], loadingDevices: false,
            })}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-md w-full p-5"
              onClick={(e) => e.stopPropagation()}>
              <h3 className="text-sm font-semibold text-zinc-100 mb-3">Krexion Android / Cloud phone</h3>
              <Label className="text-zinc-300 text-xs">Provider</Label>
              <select
                className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded-md h-9 text-xs mb-3 px-2"
                value={cloudPhoneDialog.provider}
                onChange={(e) => setCloudPhoneDialog({ ...cloudPhoneDialog, provider: e.target.value })}
                data-testid="bp-cloud-phone-provider"
              >
                <option value="cpi">Krexion Android (this PC farm)</option>
                <option value="partner">Krexion Cloud Android (URL)</option>
                <option value="none">Clear</option>
              </select>
              {cloudPhoneDialog.provider === "partner" && (
                <>
                  <Label className="text-zinc-300 text-xs">Console URL</Label>
                  <Input
                    value={cloudPhoneDialog.partnerUrl}
                    onChange={(e) => setCloudPhoneDialog({ ...cloudPhoneDialog, partnerUrl: e.target.value })}
                    className="bg-zinc-900 border-zinc-700 text-zinc-100 mb-3"
                    placeholder="https://…"
                  />
                </>
              )}
              {cloudPhoneDialog.provider === "cpi" && (
                <>
                  <Label className="text-zinc-300 text-xs">Krexion Android device</Label>
                  {cloudPhoneDialog.loadingDevices ? (
                    <p className="text-[10px] text-zinc-500 mb-3">Loading devices…</p>
                  ) : (
                    <select
                      className="w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded-md h-9 text-xs mb-3 px-2"
                      value={cloudPhoneDialog.deviceId}
                      onChange={(e) => setCloudPhoneDialog({ ...cloudPhoneDialog, deviceId: e.target.value })}
                      data-testid="bp-cloud-phone-device"
                    >
                      <option value="">Auto (first online)</option>
                      {(cloudPhoneDialog.devices || []).map((d) => (
                        <option key={d.id} value={d.id}>
                          {(d.label || d.model || "Android")} · {d.status}
                          {d.device_type === "android_cloud" ? " · cloud" : ""}
                        </option>
                      ))}
                    </select>
                  )}
                  {(cloudPhoneDialog.devices || []).length === 0 && !cloudPhoneDialog.loadingDevices && (
                    <p className="text-[10px] text-amber-400 mb-3">
                      No devices yet — Enable Krexion Android on CPI → Devices first.
                    </p>
                  )}
                </>
              )}
              <div className="flex justify-end gap-2 flex-wrap">
                <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs"
                  onClick={() => setCloudPhoneDialog({
                    id: null, provider: "cpi", partnerUrl: "", deviceId: "", label: "", devices: [], loadingDevices: false,
                  })}>Cancel</Button>
                <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-200 h-7 text-xs"
                  onClick={() => handleCloudPhoneSave("bind")} data-testid="bp-cloud-phone-save">Bind</Button>
                {cloudPhoneDialog.provider === "cpi" && (
                  <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs"
                    onClick={() => handleCloudPhoneSave("open")} data-testid="bp-cloud-phone-open">
                    Open now
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Launch checklist modal (v2.7.76) */}
        {launchChecklist.open && launchChecklist.data && (
          <div className="fixed inset-0 z-[65] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setLaunchChecklist({ open: false, id: null, data: null, startUrl: undefined })}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-lg w-full p-5 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()} data-testid="bp-launch-checklist">
              <h3 className="text-sm font-semibold text-zinc-100 mb-1">Launch preview</h3>
              <p className="text-xs text-zinc-500 mb-4">{launchChecklist.data.name}</p>
              <ul className="space-y-2 text-xs text-zinc-300 mb-4">
                <li className="flex items-start gap-2">
                  <span className={launchChecklist.data.proxy_enabled ? "text-emerald-400" : "text-zinc-500"}>●</span>
                  <span>Proxy: {launchChecklist.data.proxy_enabled ? (launchChecklist.data.exit_ip || "configured") : "none"}</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className={launchChecklist.data.cookie_count > 0 ? "text-emerald-400" : "text-amber-400"}>●</span>
                  <span>Cookies: {launchChecklist.data.cookie_count || 0}</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className={healthBadgeClass(launchChecklist.data.health?.level).includes("emerald") ? "text-emerald-400" : launchChecklist.data.health?.level === "bad" ? "text-red-400" : "text-amber-400"}>●</span>
                  <span>
                    Health: {launchChecklist.data.health?.level || "unknown"} ({launchChecklist.data.health?.score ?? "—"})
                    {(launchChecklist.data.health?.issues || []).length > 0 && (
                      <span className="block text-zinc-500 mt-0.5">{(launchChecklist.data.health.issues || []).join(" · ")}</span>
                    )}
                  </span>
                </li>
              </ul>

              <div className="mb-4 p-3 rounded-lg border border-zinc-800 bg-zinc-900/50 space-y-2">
                <label className="flex items-center gap-2 text-xs text-zinc-200 cursor-pointer">
                  <input
                    type="checkbox"
                    className="accent-fuchsia-500"
                    checked={launchAuto.enabled}
                    onChange={(e) => setLaunchAuto((s) => ({ ...s, enabled: e.target.checked }))}
                    data-testid="bp-launch-auto-enable"
                  />
                  Run JSON automation after launch (RUT-style)
                </label>
                {launchAuto.enabled && (
                  <div className="space-y-2 pl-1">
                    <div>
                      <Label className="text-[10px] text-zinc-500">Automation JSON</Label>
                      <select
                        className="mt-1 w-full bg-zinc-950 border border-zinc-700 rounded-md px-2 py-1.5 text-xs text-zinc-100"
                        value={launchAuto.automation_upload_id}
                        onChange={(e) => setLaunchAuto((s) => ({ ...s, automation_upload_id: e.target.value }))}
                        data-testid="bp-launch-auto-json"
                      >
                        <option value="">{uploadsLoading ? "Loading…" : "Select template…"}</option>
                        {automationUploads.map((u) => (
                          <option key={u.id} value={u.id}>{u.name || u.filename || u.id.slice(0, 8)}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <Label className="text-[10px] text-zinc-500">Lead data file (optional — for {"{{email}}"} etc.)</Label>
                      <select
                        className="mt-1 w-full bg-zinc-950 border border-zinc-700 rounded-md px-2 py-1.5 text-xs text-zinc-100"
                        value={launchAuto.data_file_id}
                        onChange={(e) => setLaunchAuto((s) => ({ ...s, data_file_id: e.target.value }))}
                        data-testid="bp-launch-auto-leads"
                      >
                        <option value="">Static JSON only</option>
                        {dataFileUploads.map((u) => (
                          <option key={u.id} value={u.id}>{u.name || u.filename || u.id.slice(0, 8)}</option>
                        ))}
                      </select>
                    </div>
                    {launchAuto.data_file_id && (
                      <div>
                        <Label className="text-[10px] text-zinc-500">Lead row index</Label>
                        <Input
                          type="number"
                          min={0}
                          className="mt-1 h-7 text-xs bg-zinc-950 border-zinc-700"
                          value={launchAuto.lead_row_index}
                          onChange={(e) => setLaunchAuto((s) => ({ ...s, lead_row_index: Number(e.target.value) || 0 }))}
                        />
                      </div>
                    )}
                    <label className="flex items-center gap-2 text-[10px] text-zinc-400 cursor-pointer">
                      <input
                        type="checkbox"
                        className="accent-fuchsia-500"
                        checked={launchAuto.skip_missing_steps}
                        onChange={(e) => setLaunchAuto((s) => ({ ...s, skip_missing_steps: e.target.checked }))}
                      />
                      Skip missing steps
                    </label>
                    <label className="flex items-center gap-2 text-[10px] text-zinc-400 cursor-pointer">
                      <input
                        type="checkbox"
                        className="accent-fuchsia-500"
                        checked={launchAuto.save_as_default}
                        onChange={(e) => setLaunchAuto((s) => ({ ...s, save_as_default: e.target.checked }))}
                      />
                      Save as profile default (pre-select next time)
                    </label>
                  </div>
                )}
                {!launchAuto.enabled && (
                  <p className="text-[10px] text-zinc-500">Default: manual browse — same as before.</p>
                )}
              </div>

              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs"
                  onClick={() => setLaunchChecklist({ open: false, id: null, data: null, startUrl: undefined })}>
                  Cancel
                </Button>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs"
                  disabled={launchAuto.enabled && !launchAuto.automation_upload_id}
                  onClick={confirmLaunchFromChecklist} data-testid="bp-launch-anyway">
                  {launchAuto.enabled ? "Launch + run JSON" : "Launch (manual)"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Clone options modal (v2.7.76) */}
        {cloneDialog.open && (
          <div className="fixed inset-0 z-[65] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setCloneDialog({ open: false, id: null, opts: { include_cookies: false, fresh_proxy: true, fresh_ua: false } })}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-sm w-full p-5"
              onClick={(e) => e.stopPropagation()} data-testid="bp-clone-dialog">
              <h3 className="text-sm font-semibold text-zinc-100 mb-3 flex items-center gap-2">
                <Copy className="w-4 h-4 text-fuchsia-400" /> Clone profile
              </h3>
              <div className="space-y-2 mb-4 text-xs text-zinc-300">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" className="accent-fuchsia-500"
                    checked={cloneDialog.opts.include_cookies}
                    onChange={(e) => setCloneDialog((d) => ({ ...d, opts: { ...d.opts, include_cookies: e.target.checked } }))} />
                  Include cookies / storage state
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" className="accent-fuchsia-500"
                    checked={cloneDialog.opts.fresh_proxy}
                    onChange={(e) => setCloneDialog((d) => ({ ...d, opts: { ...d.opts, fresh_proxy: e.target.checked } }))} />
                  Fresh proxy allocation
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" className="accent-fuchsia-500"
                    checked={cloneDialog.opts.fresh_ua}
                    onChange={(e) => setCloneDialog((d) => ({ ...d, opts: { ...d.opts, fresh_ua: e.target.checked } }))} />
                  Fresh user-agent
                </label>
              </div>
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs"
                  onClick={() => setCloneDialog({ open: false, id: null, opts: { include_cookies: false, fresh_proxy: true, fresh_ua: false } })}>
                  Cancel
                </Button>
                <Button size="sm" className="bg-fuchsia-600 hover:bg-fuchsia-700 text-white h-7 text-xs"
                  onClick={confirmClone} data-testid="bp-clone-confirm">
                  Clone
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Launch URL prompt */}
        {launchUrlPrompt.id && (
          <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setLaunchUrlPrompt({ id: null, url: "" })}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-md w-full p-5"
              onClick={(e) => e.stopPropagation()}>
              <h3 className="text-sm font-semibold text-zinc-100 mb-3 flex items-center gap-2">
                <Link className="w-4 h-4 text-cyan-400" /> Launch with URL
              </h3>
              <Input
                value={launchUrlPrompt.url}
                onChange={(e) => setLaunchUrlPrompt({ ...launchUrlPrompt, url: e.target.value })}
                className="bg-zinc-900 border-zinc-700 text-zinc-100 mb-4"
                placeholder="https://…"
                autoFocus
                onKeyDown={(e) => { if (e.key === "Enter") handleLaunchUrlConfirm(); }}
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-xs"
                  onClick={() => setLaunchUrlPrompt({ id: null, url: "" })}>Cancel</Button>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs"
                  data-testid={`bp-launch-url-confirm-${launchUrlPrompt.id}`}
                  onClick={handleLaunchUrlConfirm}>Launch</Button>
              </div>
            </div>
          </div>
        )}

        {/* v2.7.15 — Fingerprint coherence panel */}
        {fpModal.open && (
          <div
            className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            data-testid="bp-fp-modal"
            onClick={() => setFpModal({ open: false, id: null, loading: false, data: null, error: null })}
          >
            <div
              className="bg-zinc-950 border border-fuchsia-800/40 rounded-xl max-w-lg w-full max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-zinc-800 flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-fuchsia-300 flex items-center gap-2">
                  <Shield className="w-4 h-4" /> Fingerprint / coherence
                </h3>
                <div className="flex gap-2">
                  {fpModal.id && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs border-fuchsia-800/60 text-fuchsia-200"
                      data-testid="bp-fp-refresh"
                      onClick={handleFingerprintRefresh}
                    >
                      Refresh FP
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs border-zinc-700"
                    onClick={() => setFpModal({ open: false, id: null, loading: false, data: null, error: null })}
                  >
                    Close
                  </Button>
                </div>
              </div>
              <div className="p-4 flex-1 overflow-y-auto text-xs">
                {fpModal.loading && <p className="text-zinc-400">Loading…</p>}
                {fpModal.error && <p className="text-red-400">{fpModal.error}</p>}
                {fpModal.data && (() => {
                  const d = fpModal.data;
                  const prev = d.preview || {};
                  const anti = d.anti_detect || {};
                  const lpc = d.last_proxy_check || {};
                  const card = profiles.find((x) => x.id === fpModal.id) || {};
                  const warnings = [];
                  const proxyCc = String(lpc.country || "").toLowerCase().slice(0, 2);
                  const profileCc = String(card.country || prev.country || "").toLowerCase().slice(0, 2);
                  if (proxyCc && profileCc && proxyCc !== profileCc) {
                    warnings.push(`Proxy exit country (${proxyCc}) ≠ profile country (${profileCc})`);
                  }
                  const rows = [
                    ["UA", (prev.user_agent || "").slice(0, 120)],
                    ["OS", prev.os || ""],
                    ["Timezone", prev.timezone || ""],
                    ["Locale", prev.locale || ""],
                    ["WebGL", [prev.webgl_vendor, prev.webgl_renderer].filter(Boolean).join(" / ") || "—"],
                    ["canvas_mode", anti.canvas_mode || ""],
                    ["webrtc_mode", anti.webrtc_mode || ""],
                    ["fp_win", anti.fingerprint_win == null ? "true" : String(anti.fingerprint_win)],
                    ["Proxy exit", lpc.ip || lpc.exit_ip || (lpc.error ? `fail: ${lpc.error}` : "—")],
                    ["geo_follow", String(prev.geo_follow_proxy ?? "")],
                    ["fp short", d.fingerprint_short || ""],
                    ["fp salt", prev.fingerprint_salt || "—"],
                    ["TLS prewarm", d.last_tls_prewarm_ok == null ? "—" : String(d.last_tls_prewarm_ok)],
                  ];
                  return (
                    <>
                      {warnings.length > 0 && (
                        <div className="mb-3 p-2 rounded border border-amber-700/50 bg-amber-950/30 text-amber-200 space-y-1">
                          {warnings.map((w) => (
                            <div key={w}>⚠ {w}</div>
                          ))}
                        </div>
                      )}
                      <table className="w-full text-left border-collapse">
                        <tbody>
                          {rows.map(([k, v]) => (
                            <tr key={k} className="border-b border-zinc-800/80">
                              <td className="py-1.5 pr-3 text-zinc-500 whitespace-nowrap align-top w-28">{k}</td>
                              <td className="py-1.5 text-zinc-200 font-mono break-all">{v || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  );
                })()}
              </div>
            </div>
          </div>
        )}

        {/* v2.7.15 — Local API docs (migration map) */}
        {docsModal.open && (
          <div
            className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setDocsModal({ open: false, loading: false, data: null, error: null })}
          >
            <div
              className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-zinc-100">Local API docs</h3>
                <div className="flex gap-2">
                  {docsModal.data && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs border-zinc-700"
                      onClick={() => {
                        const blob = new Blob([JSON.stringify(docsModal.data, null, 2)], { type: "application/json" });
                        const url = URL.createObjectURL(blob);
                        window.open(url, "_blank");
                        setTimeout(() => URL.revokeObjectURL(url), 30_000);
                      }}
                    >
                      Open blob
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs border-zinc-700"
                    onClick={() => setDocsModal({ open: false, loading: false, data: null, error: null })}
                  >
                    Close
                  </Button>
                </div>
              </div>
              <div className="p-4 flex-1 overflow-y-auto">
                {docsModal.loading && <p className="text-zinc-400 text-xs">Loading…</p>}
                {docsModal.error && <p className="text-red-400 text-xs">{docsModal.error}</p>}
                {docsModal.data && (
                  <pre className="text-[11px] text-zinc-300 font-mono whitespace-pre-wrap break-all">
                    {JSON.stringify(docsModal.data, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
