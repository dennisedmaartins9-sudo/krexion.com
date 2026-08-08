import { useState, useEffect } from "react";
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
import { toast } from "sonner";
import {
  Smartphone,
  Copy,
  RefreshCw,
  Download,
  Instagram,
  Facebook,
  Music2,
  Image as ImageIcon,
  Ghost,
  Chrome as ChromeIcon,
  CheckCheck,
  Monitor,
  FileSpreadsheet,
  Clock,
  Layers,
  Youtube,
  MessageCircle,
  Search,
  Globe,
} from "lucide-react";
import MultiSelectChips from "../components/MultiSelectChips";

// Small toggle pill for switching a picker between "one" / "many" modes.
function ModePill({ mode, onChange, disabled = false, testId }) {
  return (
    <div
      className={`inline-flex rounded-md overflow-hidden border border-zinc-700 text-[10px] ${
        disabled ? "opacity-40 pointer-events-none" : ""
      }`}
      data-testid={testId}
    >
      <button
        type="button"
        onClick={() => onChange("one")}
        className={`px-2 py-0.5 ${mode === "one" ? "bg-blue-600 text-white" : "bg-zinc-900 text-zinc-400 hover:text-white"}`}
      >
        Single
      </button>
      <button
        type="button"
        onClick={() => onChange("many")}
        className={`px-2 py-0.5 border-l border-zinc-700 ${mode === "many" ? "bg-blue-600 text-white" : "bg-zinc-900 text-zinc-400 hover:text-white"}`}
      >
        Multi
      </button>
    </div>
  );
}


const API_URL = process.env.REACT_APP_BACKEND_URL;

const APPS = [
  { key: "instagram", label: "Instagram",     icon: Instagram,     color: "bg-pink-600" },
  { key: "facebook",  label: "Facebook",      icon: Facebook,      color: "bg-blue-600" },
  { key: "tiktok",    label: "TikTok",        icon: Music2,        color: "bg-black border border-pink-500" },
  { key: "youtube",   label: "YouTube",       icon: Youtube,       color: "bg-red-600" },
  { key: "whatsapp",  label: "WhatsApp",      icon: MessageCircle, color: "bg-green-600" },
  { key: "linkedin",  label: "LinkedIn",      icon: Globe,         color: "bg-blue-700" },
  { key: "twitter",   label: "Twitter / X",   icon: Globe,         color: "bg-zinc-800" },
  { key: "reddit",    label: "Reddit",        icon: MessageCircle, color: "bg-orange-600" },
  { key: "telegram",  label: "Telegram",      icon: MessageCircle, color: "bg-sky-500" },
  { key: "gsearch",   label: "Google Search", icon: Search,        color: "bg-amber-500" },
  { key: "gchrome",   label: "Google Chrome", icon: ChromeIcon,    color: "bg-sky-600" },
  { key: "pinterest", label: "Pinterest",     icon: ImageIcon,     color: "bg-rose-600" },
  { key: "snapchat",  label: "Snapchat",      icon: Ghost,         color: "bg-yellow-500" },
  { key: "chrome",    label: "Browser",       icon: Globe,         color: "bg-zinc-600" },
];

const PLATFORMS = [
  { key: "any",     label: "Any", icon: null },
  { key: "android", label: "Android", icon: Smartphone },
  { key: "ios",     label: "iOS", icon: Smartphone },
  { key: "desktop", label: "Desktop", icon: Monitor },
];

export default function UserAgentGeneratorPage() {
  const [app, setApp] = useState("instagram");
  const [platform, setPlatform] = useState("android");

  // ── 2026-06-11: Multi-select pools for App and Platform pickers ──
  // When mode = "many" and pool has 2+ entries, the backend mixes them
  // randomly per-UA. When pool has <2 entries, falls back to scalar
  // app/platform exactly like before (zero behaviour change for users
  // who keep the default "Single" mode).
  const [appsPool, setAppsPool] = useState([]);
  const [platformsPool, setPlatformsPool] = useState([]);
  const [appMode, setAppMode] = useState("one");          // "one" | "many"
  const [platformMode, setPlatformMode] = useState("one"); // "one" | "many"

  // Single-select picks
  const [deviceId, setDeviceId] = useState("");
  const [appVersion, setAppVersion] = useState("");
  const [osVersion, setOsVersion] = useState("");
  const [region, setRegion] = useState("");
  const [resolution, setResolution] = useState("");

  // Multi-select pools (2–N values; when a pool has any values it overrides the single pick)
  const [deviceIdsPool, setDeviceIdsPool] = useState([]);
  const [appVersionsPool, setAppVersionsPool] = useState([]);
  const [osVersionsPool, setOsVersionsPool] = useState([]);
  const [regionsPool, setRegionsPool] = useState([]);
  const [resolutionsPool, setResolutionsPool] = useState([]);

  // Per-picker mode toggle ("one" = single dropdown, "many" = multi-select)
  const [deviceMode, setDeviceMode] = useState("one");
  const [appVersionMode, setAppVersionMode] = useState("one");
  const [osVersionMode, setOsVersionMode] = useState("one");
  const [regionMode, setRegionMode] = useState("one");
  const [resolutionMode, setResolutionMode] = useState("one");
  const [count, setCount] = useState(20);
  const [loading, setLoading] = useState(false);
  const [downloadingXlsx, setDownloadingXlsx] = useState(false);
  const [results, setResults] = useState([]);
  // ── 2026-06-11: Mix-mode metadata returned by backend ────────────
  const [mixMeta, setMixMeta] = useState(null); // {mix_mode, apps_pool, platforms_pool, breakdown}
  const [options, setOptions] = useState(null);
  const [refreshingVersions, setRefreshingVersions] = useState(false);

  const fetchOptions = async () => {
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`${API_URL}/api/user-agents/options`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) setOptions(await r.json());
    } catch (e) { /* ignore */ }
  };

  useEffect(() => {
    fetchOptions();
  }, []);

  const refreshVersionsFromStore = async () => {
    setRefreshingVersions(true);
    try {
      // Use the admin endpoint — requires admin token
      const adminToken = localStorage.getItem("adminToken");
      if (!adminToken) {
        toast.error("Admin login required to refresh versions. Go to /admin first.");
        return;
      }
      const r = await fetch(`${API_URL}/api/admin/ua-versions/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.error(d.detail || "Refresh failed");
        return;
      }
      const data = await r.json();
      const bumps = (data.updated || []).length;
      toast.success(bumps > 0
        ? `Refreshed — ${bumps} app(s) got a newer version`
        : "All apps already up-to-date"
      );
      await fetchOptions();
    } catch (e) {
      toast.error("Network error: " + e.message);
    } finally {
      setRefreshingVersions(false);
    }
  };

  // reset pinned device & version when platform or app changes
  useEffect(() => {
    setDeviceId("");
    setResolution("");
    setOsVersion("");
    setDeviceIdsPool([]);
    setResolutionsPool([]);
    setOsVersionsPool([]);
  }, [platform]);
  useEffect(() => {
    setAppVersion("");
    setAppVersionsPool([]);
  }, [app]);

  const devicesForPlatform = () => {
    if (!options) return [];
    if (platform === "android") return options.android_devices;
    if (platform === "ios") return options.ios_devices;
    if (platform === "desktop") return options.desktop_devices;
    // any -> show all
    return [
      ...options.android_devices,
      ...options.ios_devices,
      ...options.desktop_devices,
    ];
  };

  const versionsForApp = () => {
    if (!options) return [];
    return options.app_versions?.[app] || [];
  };

  const regionList = () => options?.regions || [];
  const resolutionList = () => options?.resolutions || [];
  const osVersionList = () => {
    if (!options) return [];
    if (platform === "ios") return options.ios_os_versions || [];
    if (platform === "android") return options.android_os_versions || [];
    return [];
  };

  // Resolution is only embedded in Instagram UAs; for others it's informational.
  const resolutionHelp =
    app === "instagram"
      ? "Used in Instagram UA string."
      : platform === "desktop"
      ? "Not used for desktop UAs."
      : `Not embedded in ${app} UA (stored only in metadata)`;

  const buildBody = () => ({
    app,
    platform,
    // ── 2026-06-11: Multi-app + Multi-platform mix pools ─────────
    // Only sent when "Multi" mode is ON and at least 2 selected.
    // Backend auto-degrades single-entry pools to scalar mode and
    // ignores empty pools, so legacy single-pick behaviour is
    // preserved exactly when these arrays are null.
    apps: appMode === "many" && appsPool.length >= 2 ? appsPool : null,
    platforms: platformMode === "many" && platformsPool.length >= 2 ? platformsPool : null,
    // Single picks (null if in multi mode or empty)
    device_id: deviceMode === "one" && deviceId ? deviceId : null,
    app_version: appVersionMode === "one" && appVersion ? appVersion : null,
    os_version: osVersionMode === "one" && osVersion ? osVersion : null,
    region: regionMode === "one" && region ? region : null,
    resolution: resolutionMode === "one" && resolution ? resolution : null,
    // Multi-select pools (ignored if empty)
    device_ids: deviceMode === "many" && deviceIdsPool.length > 0 ? deviceIdsPool : null,
    app_versions: appVersionMode === "many" && appVersionsPool.length > 0 ? appVersionsPool : null,
    os_versions: osVersionMode === "many" && osVersionsPool.length > 0 ? osVersionsPool : null,
    regions: regionMode === "many" && regionsPool.length > 0 ? regionsPool : null,
    resolutions: resolutionMode === "many" && resolutionsPool.length > 0 ? resolutionsPool : null,
    count,
  });

  const generate = async () => {
    if (count < 1 || count > 50000) {
      toast.error("Count must be 1 - 50,000");
      return;
    }
    setLoading(true);
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`${API_URL}/api/user-agents/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ ...buildBody(), format: "json" }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.error(d.detail || "Failed to generate");
        return;
      }
      const data = await r.json();
      setResults(
        data.profiles ||
          data.results ||
          (data.user_agents || []).map((user_agent) => ({ user_agent }))
      );
      setMixMeta({
        mix_mode: !!data.mix_mode,
        apps_pool: data.apps_pool || [],
        platforms_pool: data.platforms_pool || [],
        breakdown: data.breakdown || { by_app: {}, by_platform: {} },
      });
      const mixSuffix = data.mix_mode ? " (mix mode)" : "";
      toast.success(`Generated ${data.count} user agents${mixSuffix}`);
    } catch (e) {
      toast.error("Network error: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  const downloadExcel = async () => {
    if (count < 1 || count > 50000) {
      toast.error("Count must be 1 - 50,000");
      return;
    }
    setDownloadingXlsx(true);
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`${API_URL}/api/user-agents/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ ...buildBody(), format: "xlsx" }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.error(d.detail || "Failed to download");
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = r.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/i);
      a.download = m ? m[1] : `user_agents_${app}_${platform}_${count}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Downloaded ${count} UAs as Excel`);
    } catch (e) {
      toast.error("Network error: " + e.message);
    } finally {
      setDownloadingXlsx(false);
    }
  };

  const copyOne = (ua) => {
    navigator.clipboard.writeText(ua);
    toast.success("Copied");
  };
  const copyAll = () => {
    if (results.length === 0) return;
    const text = results.map((r) => r.user_agent).join("\n");
    navigator.clipboard.writeText(text);
    toast.success(`Copied ${results.length} user agents`);
  };
  const downloadTxt = () => {
    if (results.length === 0) return;
    const text = results.map((r) => r.user_agent).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `user_agents_${app}_${platform}_${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const useInRealTraffic = () => {
    if (results.length === 0) return;
    const text = results.map((r) => r.user_agent).join("\n");
    localStorage.setItem("ua_generator_payload", text);
    toast.success("User agents stashed — open Real User Traffic page to use them");
  };

  return (
    <div className="space-y-6" data-testid="ua-generator-page">
      <div>
        <h1 className="text-2xl font-bold text-white">User Agent Generator</h1>
        <p className="text-zinc-400">
          Generate realistic in-app UAs — Instagram, Facebook, TikTok, Pinterest,
          Snapchat, browsers, and desktop. Pick a specific device &amp; version,
          or randomise. Export to TXT or Excel.
        </p>
      </div>

      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Smartphone className="w-5 h-5 text-blue-500" />
            Choose app, device and version
          </CardTitle>
          <CardDescription>
            Each generated UA uses realistic device specs (screen size, DPI, SoC,
            build id). On desktop, regular Chrome/Firefox/Safari UAs are emitted.
          </CardDescription>
          {/* Auto-update status row */}
          {options?.versions_meta && (
            <div className="mt-2 pt-2 border-t border-zinc-800 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Clock className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-xs text-zinc-400">
                  Everything auto-refreshes every 24h from live sources ·
                </span>
                <span className="text-xs text-emerald-300" data-testid="versions-last-updated">
                  {options.versions_meta.last_refreshed_at
                    ? `Last refresh: ${new Date(options.versions_meta.last_refreshed_at).toLocaleString()}`
                    : "Awaiting first refresh"}
                </span>
                {options.versions_meta.last_refresh_note && (
                  <Badge className="bg-zinc-800 text-zinc-300 text-[10px]">
                    {options.versions_meta.last_refresh_note}
                  </Badge>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={refreshVersionsFromStore}
                  disabled={refreshingVersions}
                  className="border-emerald-700 text-emerald-300 hover:bg-emerald-900/30 h-7 text-xs ml-auto"
                  data-testid="refresh-versions-btn"
                  title="Refreshes iOS · Android · Chrome · Firefox · all 5 apps (admin login required)"
                >
                  {refreshingVersions ? (
                    <><RefreshCw className="w-3 h-3 mr-1 animate-spin" /> Refreshing all...</>
                  ) : (
                    <><RefreshCw className="w-3 h-3 mr-1" /> Refresh all versions</>
                  )}
                </Button>
              </div>
              {/* Live versions pills — show the heads of each list */}
              <div className="flex flex-wrap gap-1.5 text-[10px]">
                {options.ios_os_versions?.[0] && (
                  <Badge className="bg-blue-900/40 text-blue-200 border border-blue-800/50">
                    📱 iOS {options.ios_os_versions[0]}
                  </Badge>
                )}
                {options.android_os_versions?.[0] && (
                  <Badge className="bg-green-900/40 text-green-200 border border-green-800/50">
                    🤖 Android {options.android_os_versions[0]}
                  </Badge>
                )}
                {options.chrome_versions?.[0] && (
                  <Badge className="bg-yellow-900/40 text-yellow-200 border border-yellow-800/50">
                    Chrome {options.chrome_versions[0].split(".")[0]}
                  </Badge>
                )}
                {options.firefox_versions?.[0] && (
                  <Badge className="bg-orange-900/40 text-orange-200 border border-orange-800/50">
                    Firefox {options.firefox_versions[0]}
                  </Badge>
                )}
                {options.app_versions?.tiktok?.[0] && (
                  <Badge className="bg-pink-900/40 text-pink-200 border border-pink-800/50">
                    TikTok {options.app_versions.tiktok[0]}
                  </Badge>
                )}
                {options.app_versions?.instagram?.[0] && (
                  <Badge className="bg-fuchsia-900/40 text-fuchsia-200 border border-fuchsia-800/50">
                    Instagram {options.app_versions.instagram[0]}
                  </Badge>
                )}
                {options.app_versions?.facebook?.[0] && (
                  <Badge className="bg-sky-900/40 text-sky-200 border border-sky-800/50">
                    Facebook {options.app_versions.facebook[0]}
                  </Badge>
                )}
                {options.app_versions?.pinterest?.[0] && (
                  <Badge className="bg-red-900/40 text-red-200 border border-red-800/50">
                    Pinterest {options.app_versions.pinterest[0]}
                  </Badge>
                )}
                {options.app_versions?.snapchat?.[0] && (
                  <Badge className="bg-amber-900/40 text-amber-200 border border-amber-800/50">
                    Snapchat {options.app_versions.snapchat[0]}
                  </Badge>
                )}
              </div>
            </div>
          )}
        </CardHeader>

        <CardContent className="space-y-5">
          {/* App picker */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-zinc-300">App</Label>
              <ModePill
                mode={appMode}
                onChange={(m) => setAppMode(m)}
                testId="app-mode-toggle"
              />
            </div>
            {appMode === "many" && (
              <div className="mb-2 text-[11px] text-blue-300 bg-blue-950/40 border border-blue-900/60 rounded px-2 py-1.5">
                <span className="font-semibold">Mix mode:</span>{" "}
                Click 2+ apps below. Output will be randomly interleaved
                (e.g. FB, IG, TT, FB, YT — not grouped).
                {appsPool.length > 0 && (
                  <span className="ml-1 text-blue-200">
                    {" "}— {appsPool.length} selected
                    {appsPool.length === 1 ? " (need at least 2 for mix)" : ""}
                  </span>
                )}
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
              {APPS.map((a) => {
                const Icon = a.icon;
                const active = appMode === "many"
                  ? appsPool.includes(a.key)
                  : app === a.key;
                return (
                  <button
                    key={a.key}
                    onClick={() => {
                      if (appMode === "many") {
                        setAppsPool((prev) =>
                          prev.includes(a.key)
                            ? prev.filter((k) => k !== a.key)
                            : [...prev, a.key]
                        );
                      } else {
                        setApp(a.key);
                      }
                    }}
                    className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-sm transition ${
                      active
                        ? `${a.color} border-white/20 text-white`
                        : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"
                    }`}
                    data-testid={`app-${a.key}`}
                  >
                    <Icon className="w-4 h-4" />
                    {a.label}
                  </button>
                );
              })}
            </div>
            {appMode === "many" && (
              <div className="mt-2 flex items-center gap-2 text-[11px] text-zinc-400">
                <button
                  type="button"
                  onClick={() => setAppsPool(APPS.map((a) => a.key))}
                  className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 hover:bg-zinc-700"
                  data-testid="apps-select-all"
                >
                  Select all
                </button>
                <button
                  type="button"
                  onClick={() => setAppsPool([])}
                  className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 hover:bg-zinc-700"
                  data-testid="apps-clear"
                >
                  Clear
                </button>
              </div>
            )}
          </div>

          {/* OS picker */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-zinc-300">Operating System</Label>
              <ModePill
                mode={platformMode}
                onChange={(m) => setPlatformMode(m)}
                testId="platform-mode-toggle"
              />
            </div>
            {platformMode === "many" && (
              <div className="mb-2 text-[11px] text-blue-300 bg-blue-950/40 border border-blue-900/60 rounded px-2 py-1.5">
                <span className="font-semibold">Mix mode:</span>{" "}
                Click 2+ platforms. Output randomly mixes Android / iOS /
                Desktop UAs into one pool.
                {platformsPool.length > 0 && (
                  <span className="ml-1 text-blue-200">
                    {" "}— {platformsPool.length} selected
                    {platformsPool.length === 1 ? " (need at least 2 for mix)" : ""}
                  </span>
                )}
              </div>
            )}
            <div className="flex gap-2 flex-wrap">
              {PLATFORMS.filter((p) => platformMode === "one" || p.key !== "any").map((p) => {
                const Icon = p.icon;
                const active = platformMode === "many"
                  ? platformsPool.includes(p.key)
                  : platform === p.key;
                return (
                  <button
                    key={p.key}
                    onClick={() => {
                      if (platformMode === "many") {
                        setPlatformsPool((prev) =>
                          prev.includes(p.key)
                            ? prev.filter((k) => k !== p.key)
                            : [...prev, p.key]
                        );
                      } else {
                        setPlatform(p.key);
                      }
                    }}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm transition ${
                      active
                        ? "bg-blue-600 border-blue-500 text-white"
                        : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"
                    }`}
                    data-testid={`platform-${p.key}`}
                  >
                    {Icon ? <Icon className="w-4 h-4" /> : null}
                    {p.label}
                  </button>
                );
              })}
            </div>
            {platformMode === "many" && (
              <div className="mt-2 flex items-center gap-2 text-[11px] text-zinc-400">
                <button
                  type="button"
                  onClick={() => setPlatformsPool(["android", "ios", "desktop"])}
                  className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 hover:bg-zinc-700"
                  data-testid="platforms-select-all"
                >
                  Select all
                </button>
                <button
                  type="button"
                  onClick={() => setPlatformsPool([])}
                  className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 hover:bg-zinc-700"
                  data-testid="platforms-clear"
                >
                  Clear
                </button>
              </div>
            )}
          </div>

          {/* Device + version pickers */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-zinc-300">
                  Device <span className="text-zinc-500 text-xs">(leave on "Random")</span>
                </Label>
                <ModePill mode={deviceMode} onChange={setDeviceMode} testId="device-mode" />
              </div>
              {deviceMode === "one" ? (
                <select
                  value={deviceId}
                  onChange={(e) => setDeviceId(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2"
                  data-testid="device-select"
                >
                  <option value="">🎲 Random device from pool</option>
                  {devicesForPlatform().map((d) => (
                    <option key={d.id} value={d.id}>{d.label}</option>
                  ))}
                </select>
              ) : (
                <MultiSelectChips
                  options={devicesForPlatform().map((d) => ({ value: d.id, label: d.label }))}
                  values={deviceIdsPool}
                  onChange={setDeviceIdsPool}
                  placeholder="Pick 2–5 specific devices"
                  testId="device-multiselect"
                />
              )}
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-zinc-300">
                  App Version <span className="text-zinc-500 text-xs">(leave on "Random")</span>
                </Label>
                <ModePill mode={appVersionMode} onChange={setAppVersionMode} testId="appver-mode" />
              </div>
              {appVersionMode === "one" ? (
                <select
                  value={appVersion}
                  onChange={(e) => setAppVersion(e.target.value)}
                  disabled={versionsForApp().length === 0}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 disabled:opacity-50"
                  data-testid="version-select"
                >
                  <option value="">🎲 Random version</option>
                  {versionsForApp().map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              ) : (
                <MultiSelectChips
                  options={versionsForApp().map((v) => ({ value: v, label: v }))}
                  values={appVersionsPool}
                  onChange={setAppVersionsPool}
                  placeholder="Pick 2–5 specific versions"
                  disabled={versionsForApp().length === 0}
                  testId="version-multiselect"
                />
              )}
              {versionsForApp().length === 0 && (
                <p className="text-zinc-500 text-xs mt-1">
                  (Browser/desktop has no app version)
                </p>
              )}
            </div>
          </div>

          {/* Region + Resolution + OS Version pickers */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-zinc-300">
                  Region / Country <span className="text-zinc-500 text-xs">(leave on "Random")</span>
                </Label>
                <ModePill mode={regionMode} onChange={setRegionMode} testId="region-mode" />
              </div>
              {regionMode === "one" ? (
                <select
                  value={region}
                  onChange={(e) => setRegion(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2"
                  data-testid="region-select"
                >
                  <option value="">🌍 Random region (TikTok-weighted)</option>
                  {regionList().map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.country} ({r.code}) — {r.locale}
                    </option>
                  ))}
                </select>
              ) : (
                <MultiSelectChips
                  options={regionList().map((r) => ({
                    value: r.code,
                    label: `${r.country} (${r.code})`,
                    extra: r.locale,
                  }))}
                  values={regionsPool}
                  onChange={setRegionsPool}
                  placeholder="Pick 2–5 specific regions"
                  testId="region-multiselect"
                />
              )}
              <p className="text-zinc-500 text-xs mt-1">
                Drives TikTok <code className="text-zinc-400">ByteLocale/Region</code>, Instagram locale, Facebook <code className="text-zinc-400">FBLC</code>.
              </p>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-zinc-300">
                  OS Version <span className="text-zinc-500 text-xs">(leave on "Device default")</span>
                </Label>
                <ModePill
                  mode={osVersionMode}
                  onChange={setOsVersionMode}
                  disabled={platform === "desktop" || platform === "any"}
                  testId="osver-mode"
                />
              </div>
              {osVersionMode === "one" ? (
                <select
                  value={osVersion}
                  onChange={(e) => setOsVersion(e.target.value)}
                  disabled={platform === "desktop" || platform === "any"}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 disabled:opacity-50"
                  data-testid="os-version-select"
                >
                  <option value="">
                    {platform === "ios" ? "📱 Device default iOS" : platform === "android" ? "📱 Device default Android" : "N/A"}
                  </option>
                  {osVersionList().map((v) => (
                    <option key={v} value={v}>
                      {platform === "ios" ? `iOS ${v}` : `Android ${v}`}
                    </option>
                  ))}
                </select>
              ) : (
                <MultiSelectChips
                  options={osVersionList().map((v) => ({
                    value: v,
                    label: platform === "ios" ? `iOS ${v}` : `Android ${v}`,
                  }))}
                  values={osVersionsPool}
                  onChange={setOsVersionsPool}
                  placeholder="Pick 2–5 specific OS versions"
                  disabled={platform === "desktop" || platform === "any"}
                  testId="os-version-multiselect"
                />
              )}
              <p className="text-zinc-500 text-xs mt-1">
                {platform === "ios"
                  ? "Overrides iOS version in the UA string."
                  : platform === "android"
                  ? "Overrides Android version (SDK adjusted automatically)."
                  : "Pick Android or iOS first."}
              </p>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-zinc-300">
                  Screen Resolution <span className="text-zinc-500 text-xs">(leave blank for default)</span>
                </Label>
                <ModePill
                  mode={resolutionMode}
                  onChange={setResolutionMode}
                  disabled={platform === "desktop"}
                  testId="res-mode"
                />
              </div>
              {resolutionMode === "one" ? (
                <select
                  value={resolution}
                  onChange={(e) => setResolution(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 disabled:opacity-50"
                  data-testid="resolution-select"
                  disabled={platform === "desktop"}
                >
                  <option value="">📱 Device default resolution</option>
                  {resolutionList().map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              ) : (
                <MultiSelectChips
                  options={resolutionList().map((r) => ({ value: r, label: r }))}
                  values={resolutionsPool}
                  onChange={setResolutionsPool}
                  placeholder="Pick 2–5 specific resolutions"
                  disabled={platform === "desktop"}
                  testId="resolution-multiselect"
                />
              )}
              <p className="text-zinc-500 text-xs mt-1">{resolutionHelp}</p>
            </div>
          </div>

          {/* Count + actions */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <Label className="text-zinc-300 mb-2 block">
                Count <span className="text-zinc-500 text-xs">(1 - 50,000)</span>
              </Label>
              <Input
                type="number"
                min="1"
                max="50000"
                value={count}
                onChange={(e) => setCount(parseInt(e.target.value) || 10)}
                className="bg-zinc-800 border-zinc-700 text-white"
                data-testid="ua-count"
              />
              {/* Quick preset buttons */}
              <div className="flex gap-1 mt-2 flex-wrap">
                {[100, 500, 1000, 5000, 10000].map((n) => (
                  <button
                    key={n}
                    onClick={() => setCount(n)}
                    className="px-2 py-0.5 text-[11px] rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700"
                  >
                    {n.toLocaleString()}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-end">
              <Button
                onClick={generate}
                disabled={loading || downloadingXlsx}
                className="w-full bg-blue-600 hover:bg-blue-700"
                data-testid="ua-generate-btn"
              >
                {loading ? (
                  <><RefreshCw className="w-4 h-4 mr-2 animate-spin" /> Generating...</>
                ) : (
                  <><Smartphone className="w-4 h-4 mr-2" /> Generate {count.toLocaleString()}</>
                )}
              </Button>
            </div>
            <div className="flex items-end">
              <Button
                onClick={downloadExcel}
                disabled={loading || downloadingXlsx}
                className="w-full bg-green-600 hover:bg-green-700"
                data-testid="ua-download-xlsx"
              >
                {downloadingXlsx ? (
                  <><RefreshCw className="w-4 h-4 mr-2 animate-spin" /> Building xlsx...</>
                ) : (
                  <><FileSpreadsheet className="w-4 h-4 mr-2" /> Download .xlsx ({count.toLocaleString()})</>
                )}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {results.length > 0 && (
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="flex-row justify-between items-center space-y-0">
            <div>
              <CardTitle className="text-white text-base">
                Generated ({results.length.toLocaleString()})
                {mixMeta?.mix_mode && (
                  <Badge className="ml-2 bg-blue-900/60 text-blue-200 border border-blue-700/50 text-[10px]">
                    MIX MODE — randomly interleaved
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>
                {mixMeta?.mix_mode ? (
                  <span className="flex flex-wrap gap-1 mt-1" data-testid="ua-mix-breakdown">
                    {Object.entries(mixMeta.breakdown?.by_app || {}).map(([k, v]) => (
                      <span key={`app-${k}`} className="text-[11px] bg-zinc-800 border border-zinc-700 rounded px-2 py-0.5 text-zinc-300">
                        {k}: <span className="text-blue-300 font-semibold">{v}</span>
                      </span>
                    ))}
                    {Object.entries(mixMeta.breakdown?.by_platform || {}).map(([k, v]) => (
                      <span key={`plat-${k}`} className="text-[11px] bg-zinc-800 border border-zinc-700 rounded px-2 py-0.5 text-zinc-300">
                        {k}: <span className="text-emerald-300 font-semibold">{v}</span>
                      </span>
                    ))}
                  </span>
                ) : (
                  "Click any row to copy just that one"
                )}
              </CardDescription>
            </div>
            <div className="flex gap-2 flex-wrap">
              <Button
                variant="outline"
                onClick={copyAll}
                className="border-zinc-700 text-zinc-300"
                data-testid="ua-copy-all"
              >
                <CheckCheck className="w-4 h-4 mr-2" /> Copy all
              </Button>
              <Button
                variant="outline"
                onClick={downloadTxt}
                className="border-zinc-700 text-zinc-300"
                data-testid="ua-download-txt"
              >
                <Download className="w-4 h-4 mr-2" /> Download .txt
              </Button>
              <Button
                onClick={useInRealTraffic}
                className="bg-green-600 hover:bg-green-700"
                data-testid="ua-use-real"
              >
                Use in Real Traffic
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 max-h-[500px] overflow-auto">
              {results.slice(0, 1000).map((r, i) => (
                <div
                  key={i}
                  onClick={() => copyOne(r.user_agent)}
                  className="group flex items-start gap-3 p-2 rounded bg-zinc-950 hover:bg-zinc-800 cursor-pointer border border-zinc-800"
                  title="Click to copy"
                >
                  <Badge
                    className={`${
                      r.platform === "ios"
                        ? "bg-zinc-700 text-zinc-100"
                        : r.platform === "desktop"
                        ? "bg-indigo-700 text-white"
                        : "bg-green-700 text-green-100"
                    } text-[10px] shrink-0`}
                  >
                    {r.platform === "ios" ? "iOS" : r.platform === "desktop" ? "Desktop" : "Android"}
                  </Badge>
                  <Badge className="bg-zinc-700 text-zinc-200 text-[10px] shrink-0 truncate max-w-[180px]">
                    {r.device}
                  </Badge>
                  {r.os_version && (
                    <Badge className="bg-emerald-900/50 text-emerald-200 text-[10px] shrink-0 font-mono">
                      {r.platform === "ios" ? `iOS ${r.os_version}` : `A${r.os_version}`}
                    </Badge>
                  )}
                  {r.region && (
                    <Badge className="bg-blue-900/50 text-blue-200 text-[10px] shrink-0" title={r.country}>
                      {r.region}
                    </Badge>
                  )}
                  {r.resolution && (
                    <Badge className="bg-purple-900/50 text-purple-200 text-[10px] shrink-0 font-mono">
                      {r.resolution}
                    </Badge>
                  )}
                  <span className="text-zinc-300 text-xs font-mono truncate flex-1 group-hover:text-white">
                    {r.user_agent}
                  </span>
                  <Copy className="w-3.5 h-3.5 text-zinc-600 group-hover:text-white shrink-0 mt-0.5" />
                </div>
              ))}
              {results.length > 1000 && (
                <div className="text-center text-zinc-500 text-xs py-2">
                  Showing first 1,000 rows — use Copy all / Download to get all {results.length.toLocaleString()}.
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
