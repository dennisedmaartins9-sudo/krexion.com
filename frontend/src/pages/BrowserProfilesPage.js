/* eslint-disable react-hooks/exhaustive-deps */
import { useState, useEffect, useMemo } from "react";
import ProxyProviderSelect from "../components/ProxyProviderSelect";
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
  Globe,
  Smartphone,
  Monitor,
  Shield,
  RefreshCw,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/browser-profiles`;

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
  },
  referrer: {
    enabled: false,
    pro_mode: true,
    platform_weights: { google: 50, facebook: 25, tiktok: 25 },
    email_weights: {},
    social_wrapper: true,
    inapp_deep_path: true,
    strip_search_path: true,
    network_click_chain: false,
    search_engine: "google",
    search_keywords: "",
    brand: "",
  },
};

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
    platform: "desktop", // any | android | ios | desktop
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

  const authHeaders = useMemo(() => {
    const t = localStorage.getItem("token");
    return { Authorization: `Bearer ${t}`, "Content-Type": "application/json" };
  }, []);

  const fetchProfiles = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/`, { headers: authHeaders });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setProfiles(d.profiles || []);
    } catch (e) {
      toast.error(`Failed to load profiles: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfiles();
  }, []);

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
      const r = await fetch(`${API}/${editingId}`, {
        method: "PUT", headers: authHeaders, body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Profile updated");
      setShowCreate(false); setEditingId(null); setForm(DEFAULT_NEW);
      fetchProfiles();
    } catch (e) { toast.error(`Save failed: ${e.message}`); }
  };

  const handleAdvancedCreate = async () => {
    if (advCreating) return;
    const count = Math.max(1, Math.min(parseInt(advCount) || 1, 200));
    setAdvCreating(true);
    try {
      const payload = {
        count,
        name_prefix: (advNamePrefix || "").trim(),
        country: (form.country || "us").toLowerCase(),
        device_type: form.device_type || "desktop",
        start_url: form.start_url || "https://www.google.com/",
        notes: form.notes || "",
        viewport_width: form.viewport?.width || 0,
        viewport_height: form.viewport?.height || 0,
        anti_detect_on: !!advAntiDetect,
        ua: {
          app: advUA.app || "browser",
          platform: advUA.platform || "any",
          brand: advUA.brand || null,
          region: advUA.region || (form.country || "US").toUpperCase(),
        },
        proxy: (() => {
          if (advProxy.mode === "provider" && advProxy.provider_id) {
            return {
              mode: "provider",
              provider_id: advProxy.provider_id,
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
            return {
              mode: "manual",
              server: advProxy.server || "",
              username: advProxy.username || "",
              password: advProxy.password || "",
            };
          }
          return { mode: "none" };
        })(),
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
      toast.success(
        n === 1
          ? `Profile "${d.profiles?.[0]?.name || ""}" created`
          : `${n} unique profiles created (UA: ${d.ua_source}, proxies: ${d.proxies_allocated || 0})`,
      );
      setShowCreate(false); setEditingId(null); setForm(DEFAULT_NEW);
      // Reset advanced fields to defaults for next open
      setAdvCount(1); setAdvNamePrefix("");
      fetchProfiles();
    } catch (e) {
      toast.error(`Create failed: ${e.message}`);
    } finally {
      setAdvCreating(false);
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
        proxy: { ...DEFAULT_NEW.proxy, ...(p.proxy || {}) },
        anti_detect: { ...DEFAULT_NEW.anti_detect, ...(p.anti_detect || {}) },
        referrer: { ...DEFAULT_NEW.referrer, ...(p.referrer || {}) },
      });
      setEditingId(id); setShowCreate(true);
    } catch (e) { toast.error(`Load profile failed: ${e.message}`); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this profile? Storage state will be lost.")) return;
    try {
      const r = await fetch(`${API}/${id}`, { method: "DELETE", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Profile deleted"); fetchProfiles();
    } catch (e) { toast.error(`Delete failed: ${e.message}`); }
  };

  const handleClone = async (id) => {
    try {
      const r = await fetch(`${API}/${id}/clone`, { method: "POST", headers: authHeaders });
      if (!r.ok) throw new Error(await r.text());
      toast.success("Profile cloned"); fetchProfiles();
    } catch (e) { toast.error(`Clone failed: ${e.message}`); }
  };

  const handleLaunch = async (id, startUrl) => {
    try {
      const r = await fetch(`${API}/${id}/launch`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ start_url: startUrl || undefined }),
      });
      if (!r.ok) {
        const txt = await r.text();
        if (r.status === 409) throw new Error(txt || "Profile is already running — stop it first");
        throw new Error(txt);
      }
      const d = await r.json();
      setStatusMap((m) => ({ ...m, [id]: { ...d } }));
      if (d.desktop_available) {
        toast.success("Launch queued — desktop app will open the browser");
      } else {
        toast.warning("Profile saved — install the Krexion desktop app to launch", { duration: 6000 });
      }
      fetchProfiles();
    } catch (e) { toast.error(`Launch failed: ${e.message}`); }
  };

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

  return (
    <div className="min-h-screen bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-fuchsia-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent">
              🌐 Browser Profiles
            </h1>
            <p className="text-zinc-400 text-sm mt-1">
              AdsPower / GoLogin-style manual browsing profiles. Each profile uses the FULL Krexion anti-detect stack — same anti-detect engine that powers Real User Traffic.
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
              onClick={() => { setEditingId(null); setForm(DEFAULT_NEW); setShowCreate(true); }}
              variant="outline" className="border-zinc-700 text-zinc-300"
            >
              <Plus className="w-4 h-4 mr-1" /> Custom Profile
            </Button>
            <Button data-testid="bp-export" onClick={handleExport} variant="outline" className="border-zinc-700 text-zinc-300">
              <Download className="w-4 h-4 mr-1" /> Export
            </Button>
            <Button data-testid="bp-refresh" onClick={fetchProfiles} variant="outline" className="border-zinc-700 text-zinc-300">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {/* Info banner */}
        <div className="mb-6 p-3 rounded-lg bg-amber-950/20 border border-amber-700/40 text-xs text-amber-200 flex items-start gap-2">
          <Shield className="w-4 h-4 mt-0.5 text-amber-300" />
          <div>
            <span className="font-semibold">How it works:</span> Configure profile here in the cloud. Click <span className="text-amber-300">Launch</span> → your Krexion desktop app picks up the job → opens a HEADED Chromium with all anti-detect injected + cookies/localStorage seeded from previous sessions. Manual browsing fully anonymous, looks like a real user. Storage state syncs back here so you can resume across devices.
          </div>
        </div>

        {/* Profile list */}
        {profiles.length === 0 ? (
          <Card className="bg-zinc-900/50 border-zinc-800 mt-4">
            <CardContent className="py-12 text-center text-zinc-500">
              <Globe className="w-12 h-12 mx-auto mb-3 text-zinc-700" />
              <p>No profiles yet. Click <span className="text-fuchsia-400 font-semibold">Quick Desktop</span> or <span className="text-cyan-400 font-semibold">Quick Mobile</span> for a one-click profile.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {profiles.map((p) => (
              <Card key={p.id} className="bg-zinc-900/60 border-zinc-800 hover:border-fuchsia-700/40 transition" data-testid={`bp-card-${p.id}`}>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <CardTitle className="text-base text-zinc-100 truncate">{p.name}</CardTitle>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-zinc-300">
                          {p.device_type === "mobile" ? <Smartphone className="w-3 h-3 mr-0.5" /> : <Monitor className="w-3 h-3 mr-0.5" />}
                          {p.device_type}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] bg-zinc-900 border-zinc-700 text-zinc-300">{(p.country || "?").toUpperCase()}</Badge>
                        {p.anti_detect?.master && (
                          <Badge variant="outline" className="text-[10px] bg-fuchsia-950/40 border-fuchsia-700/60 text-fuchsia-300">
                            <Shield className="w-3 h-3 mr-0.5" /> AD
                          </Badge>
                        )}
                        <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(p.status)}`}>
                          {p.status || "idle"}
                        </Badge>
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-0 pb-3">
                  <div className="text-[11px] text-zinc-500 truncate mb-2" title={p.user_agent}>
                    {(p.user_agent || "").slice(0, 60)}…
                  </div>
                  <div className="text-[11px] text-zinc-500 mb-3">
                    {p.viewport?.width}×{p.viewport?.height} · {p.locale} · {p.total_launches || 0} launches
                    {p.storage_state_stats?.cookie_count > 0 && (
                      <span className="text-emerald-400 ml-1">· {p.storage_state_stats.cookie_count} cookies</span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {["running", "launching", "stopping", "queued"].includes(p.status) ? (
                      <Button data-testid={`bp-stop-${p.id}`} onClick={() => handleStop(p.id)} size="sm" className="bg-red-600 hover:bg-red-700 text-white h-7 text-xs">
                        <StopCircle className="w-3 h-3 mr-1" /> Stop
                      </Button>
                    ) : (
                      <Button data-testid={`bp-launch-${p.id}`} onClick={() => handleLaunch(p.id)} size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white h-7 text-xs">
                        <Play className="w-3 h-3 mr-1" /> Launch
                      </Button>
                    )}
                    <Button data-testid={`bp-edit-${p.id}`} onClick={() => handleEdit(p.id)} variant="outline" size="sm" className="border-zinc-700 text-zinc-300 h-7 text-xs">
                      Edit
                    </Button>
                    <Button data-testid={`bp-clone-${p.id}`} onClick={() => handleClone(p.id)} variant="outline" size="sm" className="border-zinc-700 text-zinc-300 h-7 text-xs">
                      <Copy className="w-3 h-3" />
                    </Button>
                    <Button data-testid={`bp-delete-${p.id}`} onClick={() => handleDelete(p.id)} variant="outline" size="sm" className="border-red-900/60 text-red-400 hover:bg-red-950/40 h-7 text-xs">
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                  {statusMap[p.id]?.message && (
                    <div className="mt-2 text-[10px] text-amber-300/80 italic">{statusMap[p.id].message}</div>
                  )}
                  {p.status === "error" && p.last_error && (
                    <div className="mt-2 text-[10px] text-red-300/90 italic break-words" data-testid={`bp-last-error-${p.id}`}>
                      ⚠ {p.last_error}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Create / Edit dialog */}
        {showCreate && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowCreate(false)}>
            <div className="bg-zinc-950 border border-zinc-800 rounded-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
              <div className="p-5 border-b border-zinc-800 sticky top-0 bg-zinc-950 z-10">
                <h2 className="text-xl font-semibold text-zinc-100">{editingId ? "Edit Profile" : "New Browser Profile"}</h2>
                {!editingId && (
                  <p className="text-[11px] text-zinc-500 mt-1">
                    Each profile gets a UNIQUE user-agent (live generator) + UNIQUE proxy from your selected Proxy Provider — anti-detect ready. Leave name blank for auto-naming.
                  </p>
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
                  <div>
                    <Label className="text-zinc-300 text-xs">Device Type</Label>
                    <select data-testid="bp-form-device" value={form.device_type}
                      onChange={(e) => {
                        const mob = e.target.value === "mobile";
                        // 2026-06 — Customer ask: viewport should
                        // AUTO-MATCH the device type. Previously
                        // switching to mobile left viewport at the
                        // desktop 1920×1080 default, which made the
                        // headed browser render mobile sites in
                        // desktop layout (broken anti-detect signal —
                        // a Samsung UA with a 1920px window is a dead
                        // giveaway to any fingerprint script). We now
                        // set sensible per-device defaults the user
                        // can still override below if they need
                        // something specific.
                        const newViewport = mob
                          ? { width: 412, height: 914 }   // Pixel 5 / iPhone 14 Pro Max bucket
                          : { width: 1920, height: 1080 }; // common desktop
                        setForm({
                          ...form,
                          device_type: e.target.value,
                          is_mobile: mob,
                          has_touch: mob,
                          device_scale_factor: mob ? 3 : 1,
                          os: mob ? "ios" : "windows",
                          viewport: newViewport,
                        });
                        // Sync UA platform to match device by default
                        if (!editingId) {
                          setAdvUA((u) => ({ ...u, platform: mob ? "android" : "desktop" }));
                        }
                      }}
                      className="w-full mt-1 bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-sm">
                      <option value="desktop">Desktop</option>
                      <option value="mobile">Mobile</option>
                    </select>
                  </div>
                  <div className="col-span-2">
                    <Label className="text-zinc-300 text-xs">Start URL</Label>
                    <Input data-testid="bp-form-starturl" value={form.start_url} onChange={(e) => setForm({ ...form, start_url: e.target.value })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
                  {editingId && (
                    <div className="col-span-2">
                      <Label className="text-zinc-300 text-xs">User Agent <span className="text-zinc-500">(leave blank = auto-generate)</span></Label>
                      <Input data-testid="bp-form-ua" value={form.user_agent} onChange={(e) => setForm({ ...form, user_agent: e.target.value })}
                        className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs" placeholder="Auto" />
                    </div>
                  )}
                  <div>
                    <Label className="text-zinc-300 text-xs">Viewport Width <span className="text-zinc-500">(0 = device default)</span></Label>
                    <Input type="number" value={form.viewport.width}
                      onChange={(e) => setForm({ ...form, viewport: { ...form.viewport, width: parseInt(e.target.value) || 0 } })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
                  <div>
                    <Label className="text-zinc-300 text-xs">Viewport Height <span className="text-zinc-500">(0 = device default)</span></Label>
                    <Input type="number" value={form.viewport.height}
                      onChange={(e) => setForm({ ...form, viewport: { ...form.viewport, height: parseInt(e.target.value) || 0 } })}
                      className="bg-zinc-900 border-zinc-700 text-zinc-100" />
                  </div>
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
                </div>

                {/* Proxy — create vs edit modes use different controls */}
                {!editingId ? (
                  <div className="p-3 rounded-lg border border-cyan-500/30 bg-cyan-950/10 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-cyan-300 text-sm font-semibold">🌍 Proxy</span>
                      <span className="text-[10px] text-zinc-500">Same engine as /proxies — every profile gets a unique exit-IP</span>
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
                        <p className="text-[10px] text-zinc-500">Same proxy applied to every profile in this batch.</p>
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
                          Auto-generate unique proxy per profile (uses selected Provider)
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
                <Button onClick={() => { setShowCreate(false); setEditingId(null); }} variant="outline" className="border-zinc-700 text-zinc-300">Cancel</Button>
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
      </div>
    </div>
  );
}
