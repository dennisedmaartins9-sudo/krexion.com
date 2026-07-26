import { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "./ui/card";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { toast } from "sonner";
import {
  Server, Zap, Copy, Settings2, ExternalLink, Loader2, Download,
  Globe2, MapPin, Building2, Hash, Radio, Timer, Sparkles, Info,
  ChevronDown, ChevronUp, Wand2,
} from "lucide-react";
import SearchableCombo from "./SearchableCombo";
import {
  COUNTRIES as REF_COUNTRIES,
  US_STATES as REF_US_STATES,
  CITIES_BY_COUNTRY,
  ISPS_BY_COUNTRY,
} from "../data/proxyTargetingRefData";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Build combobox options from the shared reference data. Values are
// normalised (lower/no-space) so they match the backend's DSL syntax
// for the detected provider — the customer never has to worry about
// which form the provider wants.
const COUNTRY_OPTIONS = REF_COUNTRIES.map((c) => ({
  value: c.code,
  label: `${c.flag}  ${c.code} — ${c.label}`,
  hint: c.code,
}));

const US_STATE_OPTIONS = REF_US_STATES.map((s) => ({
  value: s.code,
  label: `${s.code} — ${s.label}`,
  hint: s.code,
}));

const PROXY_TYPES = [
  { value: "http",     label: "HTTP" },
  { value: "https",    label: "HTTPS" },
  { value: "socks5",   label: "SOCKS5" },
  { value: "socks5h",  label: "SOCKS5H (remote DNS)" },
  { value: "socks4",   label: "SOCKS4" },
];

/** Every provider gets the full generator UI — backend applies what it can. */
const FULL_GENERATOR_SUPPORTS = {
  country: true,
  state: true,
  city: true,
  zip: true,
  asn: true,
  sticky_minutes: true,
  session_mode: true,
};

/**
 * "My Proxy Providers" — provider-agnostic on-demand proxy generator.
 *
 *   • Dropdown of every enabled provider the customer added under
 *     Settings › Proxy Providers.
 *   • Universal batch generator with Country / State / City / ZIP /
 *     ASN / Session mode / Sticky minutes — the backend detects the
 *     provider (DataImpulse, Bright Data, Oxylabs, IPRoyal, Smart-
 *     proxy, ProxyEmpire, Soax, PacketStream, or custom {placeholders})
 *     and applies each field using that provider's own DSL.
 *   • Output textarea with Copy / Download.
 */
export default function MyProxyProvidersCard() {
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState("");
  const [profile, setProfile] = useState(null);        // targeting-profile from backend
  const [profileLoading, setProfileLoading] = useState(false);

  // Batch generator state
  const [count, setCount] = useState(10);
  const [proxyType, setProxyType] = useState("http");
  const [country, setCountry] = useState("US");
  const [state, setState] = useState("");
  const [city, setCity] = useState("");
  const [zip, setZip] = useState("");
  const [asn, setAsn] = useState("");
  const [sessionMode, setSessionMode] = useState("sticky"); // rotating | sticky
  const [stickyMinutes, setStickyMinutes] = useState(60);
  const [showTargeting, setShowTargeting] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [output, setOutput] = useState("");

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem("token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/proxy-providers`, { headers: authHeaders() });
      const enabled = (r.data || []).filter((p) => p.enabled);
      setProviders(enabled);
      if (enabled.length > 0 && !selectedId) {
        setSelectedId(enabled[0].id);
        setProxyType(enabled[0].proxy_type || "http");
      }
    } catch (e) {
      // silent — user might not have providers yet
    } finally {
      setLoading(false);
    }
  }, [authHeaders, selectedId]);

  useEffect(() => { load(); }, [load]);

  const selected = providers.find((p) => p.id === selectedId);

  // Load per-provider targeting profile whenever selection changes.
  useEffect(() => {
    if (!selectedId) { setProfile(null); return; }
    setProfileLoading(true);
    axios.get(`${API}/proxy-providers/${selectedId}/targeting-profile`, { headers: authHeaders() })
      .then((r) => setProfile(r.data || null))
      .catch(() => setProfile(null))
      .finally(() => setProfileLoading(false));
    if (selected?.proxy_type) setProxyType(selected.proxy_type);
  }, [selectedId, authHeaders, selected?.proxy_type]);

  const supports = FULL_GENERATOR_SUPPORTS;
  const ttlCap = profile?.ttl_cap_min || 120;
  const kindHint = profile?.hint || "";

  // Reference options for the geo comboboxes — refresh whenever the
  // selected country changes so cities/ISPs update in sync.
  const cityOptions = useMemo(() => {
    const list = CITIES_BY_COUNTRY[country] || [];
    // If US and state chosen, prefer cities in that state at the top
    // but keep the rest available (customer may still want cross-state).
    if (country === "US" && state) {
      const inState = list.filter((c) => c.state === state);
      const rest = list.filter((c) => c.state !== state);
      return [...inState, ...rest];
    }
    return list;
  }, [country, state]);

  const ispOptions = useMemo(() => {
    const list = ISPS_BY_COUNTRY[country] || [];
    // Show ISP name + ASN so power users can pick a numeric ASN too.
    return list.map((i) => ({
      value: i.value,
      label: i.label,
      hint: i.asn ? `AS${i.asn}` : "",
    }));
  }, [country]);

  const stateOptions = useMemo(() => {
    // Only US has a curated state dropdown. Other countries → free-text
    // (customer can still type region names their provider accepts).
    return country === "US" ? US_STATE_OPTIONS : [];
  }, [country]);

  const kindLabel = (k) => (k || "").replace(/_/g, " ");

  // Preview of what backend will build for the FIRST generated line —
  // helps the user learn each provider's DSL by seeing exactly what
  // gets sent. Uses only client-side heuristics; backend is source of
  // truth. Only shown for rotating_gateway providers.
  const dslPreview = useMemo(() => {
    if (!selected) return "";
    if (selected.kind === "native_proxyjet") {
      const bits = [];
      if (country) bits.push(`country=${country}`);
      if (state) bits.push(`state=${state}`);
      if (sessionMode === "sticky" && stickyMinutes) bits.push(`sticky=${stickyMinutes}m`);
      return bits.length
        ? `ProxyJet session · ${bits.join(" · ")}`
        : "ProxyJet session · uses saved Auto Mode country/state";
    }
    if (selected.kind === "manual_list") {
      return "Manual list · returns saved lines (geo fields ignored)";
    }
    if (selected.kind === "api_endpoint") {
      return "API endpoint · fetches from configured API URL";
    }
    const host = selected?.config_summary?.gateway_host
      || selected?.gateway_host
      || (selected?.name || "").toLowerCase();
    const detect = profile?.detected_provider || selected?.name || "";
    let sep = "-", kv = "-", prefix = "-";
    let keys = { country: "country", state: "state", city: "city", zip: "zip", asn: "asn" };
    let sidKey = "session", ttlKey = null;
    if (/DataImpulse/i.test(detect)) {
      prefix = "__"; sep = ";"; kv = ".";
      keys = { country: "cr", state: "st", city: "city", zip: "zip", asn: "asn" };
      sidKey = "sessid"; ttlKey = "sessttl";
    } else if (/Oxylabs/i.test(detect)) {
      prefix = "-"; sep = "-"; kv = "-";
      keys = { country: "cc", state: "st", city: "city", zip: "zip", asn: "asn" };
      sidKey = "sessid"; ttlKey = "sesstime";
    } else if (/IPRoyal/i.test(detect)) {
      prefix = "_"; sep = "_"; kv = "-";
      sidKey = "session"; ttlKey = "lifetime";
    } else if (/ProxyEmpire/i.test(detect)) {
      keys.state = "region"; ttlKey = "lifetime";
    } else if (/Smartproxy|Decodo/i.test(detect)) {
      ttlKey = "sessionduration";
    } else if (/Soax/i.test(detect)) {
      prefix = ";"; sep = ";"; kv = "-";
      keys.state = "region"; keys.asn = "isp";
      sidKey = "sessionid"; ttlKey = "sessionlength";
    } else if (/PacketStream/i.test(detect)) {
      prefix = "_"; sep = "_";
    } else if (/Bright Data/i.test(detect)) {
      sidKey = "session";
    }
    const parts = [];
    if (country && keys.country) parts.push(`${keys.country}${kv}${country.toLowerCase()}`);
    if (state && keys.state) parts.push(`${keys.state}${kv}${state.toLowerCase()}`);
    if (city && keys.city) parts.push(`${keys.city}${kv}${city.toLowerCase().replace(/\s+/g, "")}`);
    if (zip && keys.zip) parts.push(`${keys.zip}${kv}${zip}`);
    if (asn && keys.asn) parts.push(`${keys.asn}${kv}${asn.toLowerCase()}`);
    if (sessionMode === "sticky" && stickyMinutes && ttlKey) parts.push(`${ttlKey}${kv}${stickyMinutes}`);
    if (sidKey) parts.push(`${sidKey}${kv}<random>`);
    if (!parts.length) return "";
    return `<login>${prefix}${parts.join(sep)}`;
  }, [selected, profile, country, state, city, zip, asn, sessionMode, stickyMinutes]);

  const generateBatch = async () => {
    if (!selectedId) {
      toast.error("Pick a provider first");
      return;
    }
    const n = Math.max(1, Math.min(parseInt(count, 10) || 10, 5000));
    setGenerating(true);
    setOutput("");
    try {
      const payload = {
        count: n,
        proxy_type: proxyType,
        session_mode: sessionMode,
      };
      if (country) payload.country = country.trim().toUpperCase();
      if (state) payload.state = state.trim().toUpperCase();
      if (city) payload.city = city.trim();
      if (zip) payload.zip = zip.trim();
      if (asn) payload.asn = asn.trim();
      if (sessionMode === "sticky" && stickyMinutes) {
        payload.sticky_minutes = Math.max(1, Math.min(parseInt(stickyMinutes, 10) || 10, ttlCap));
      }
      const r = await axios.post(
        `${API}/proxy-providers/${selectedId}/generate-batch`,
        payload,
        { headers: authHeaders() }
      );
      const lines = (r.data?.proxies || []).join("\n");
      setOutput(lines);
      toast.success(`Generated ${r.data?.count || 0} ${proxyType.toUpperCase()} proxies from ${selected?.name || "provider"}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const copyOutput = async () => {
    if (!output) return;
    try {
      await navigator.clipboard.writeText(output);
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Copy failed — select & copy manually");
    }
  };

  const downloadOutput = () => {
    if (!output) return;
    const blob = new Blob([output + "\n"], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const fname = `${(selected?.name || "provider").replace(/[^a-z0-9_-]/gi, "_")}-${proxyType}-${output.split("\n").length}.txt`;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <Card className="bg-gradient-to-br from-blue-950/30 to-indigo-950/30 border-blue-500/30" data-testid="my-proxy-providers-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-blue-200">
              <Server size={18} className="text-blue-400" /> My Proxy Providers
              {providers.length > 0 && (
                <Badge variant="secondary" className="bg-blue-500/20 text-blue-200 border-blue-500/30 ml-2">
                  {providers.length} active
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="mt-1 text-zinc-400">
              Pick any provider you added in Settings and pull proxies on-demand in whichever format
              you need (HTTP / SOCKS5 / etc). The same provider is used automatically by RUT,
              Browser Profiles, and CPI — no per-page setup required.
            </CardDescription>
          </div>
          <Link
            to="/settings"
            className="text-xs text-blue-300 hover:text-blue-200 flex items-center gap-1 shrink-0"
            data-testid="my-proxy-providers-manage-link"
          >
            <Settings2 size={14} /> Manage <ExternalLink size={12} />
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <div className="text-sm text-zinc-500 italic">Loading providers…</div>
        ) : providers.length === 0 ? (
          <div className="text-sm text-zinc-400 italic py-2">
            You haven&apos;t added any proxy providers yet.
            <Link to="/settings" className="text-blue-300 hover:underline ml-1">
              Add one in Settings › Proxy Providers
            </Link>
            &nbsp;— then generate proxies here or use the dropdown on RUT / Browser Profiles / CPI.
          </div>
        ) : (
          <>
            {/* Provider picker */}
            <div>
              <Label className="text-xs text-blue-200 uppercase tracking-wider mb-1 block">Provider</Label>
              <Select value={selectedId} onValueChange={setSelectedId}>
                <SelectTrigger data-testid="my-proxy-providers-select" className="bg-zinc-900/50">
                  <SelectValue placeholder="Pick a provider" />
                </SelectTrigger>
                <SelectContent>
                  {providers.map((p) => (
                    <SelectItem key={p.id} value={p.id} data-testid={`my-proxy-providers-option-${p.id}`}>
                      {p.name} · {kindLabel(p.kind)} · {(p.proxy_type || "").toUpperCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* Provider detection hint */}
              {selected && (
                <div className="mt-2 flex items-start gap-2 text-[11px]">
                  {profileLoading ? (
                    <span className="text-zinc-500 italic">Detecting provider capabilities…</span>
                  ) : profile ? (
                    <div className="flex-1 flex items-center gap-2 flex-wrap">
                      <Badge className="bg-emerald-500/15 text-emerald-300 border-emerald-500/40 font-medium">
                        <Sparkles size={11} className="mr-1" />
                        {profile.detected_provider || "Custom"}
                      </Badge>
                      <span className="text-zinc-400 text-[11px]">{profile.hint}</span>
                    </div>
                  ) : (
                    <span className="text-zinc-500 italic">
                      Selected: <span className="text-blue-300 font-medium">{selected.name}</span>{" · "}
                      <span className="text-zinc-400">{kindLabel(selected.kind)}</span>{" · "}
                      <span className="uppercase text-blue-300">{selected.proxy_type}</span>
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Batch generator */}
            <div className="pt-4 mt-2 border-t border-blue-500/20 space-y-4">
              <div className="flex items-center gap-2">
                <Zap size={14} className="text-amber-300" />
                <h4 className="text-sm font-semibold text-white">Generate proxies on-demand</h4>
              </div>

              {/* Basic controls: How many + Format */}
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                <div>
                  <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                    <Hash size={11} /> How many
                  </Label>
                  <Input
                    type="number"
                    min={1}
                    max={5000}
                    value={count}
                    onChange={(e) => setCount(e.target.value)}
                    className="bg-zinc-900/60 border-zinc-700 text-white"
                    data-testid="mpp-gen-count"
                  />
                </div>
                <div>
                  <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                    <Radio size={11} /> Output format
                  </Label>
                  <select
                    value={proxyType}
                    onChange={(e) => setProxyType(e.target.value)}
                    className="w-full h-10 px-2 rounded-md bg-zinc-900/60 border border-zinc-700 text-white text-sm"
                    data-testid="mpp-gen-format"
                  >
                    {PROXY_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                    <Timer size={11} /> Session type
                  </Label>
                  <select
                    value={sessionMode}
                    onChange={(e) => setSessionMode(e.target.value)}
                    className="w-full h-10 px-2 rounded-md bg-zinc-900/60 border border-zinc-700 text-white text-sm"
                    data-testid="mpp-gen-session-mode"
                  >
                    <option value="rotating">Rotating (fresh IP per connect)</option>
                    <option value="sticky">Sticky (hold IP for N min)</option>
                  </select>
                </div>
              </div>

              {/* Sticky duration slider */}
              {sessionMode === "sticky" && (
                <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-3">
                  <Label className="text-[11px] text-emerald-300 uppercase tracking-wider flex items-center gap-1 mb-2">
                    <Timer size={11} /> Sticky duration
                    <Badge variant="secondary" className="ml-auto bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px] font-normal">
                      max {ttlCap} min
                    </Badge>
                  </Label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={1}
                      max={ttlCap}
                      value={Math.min(stickyMinutes, ttlCap)}
                      onChange={(e) => setStickyMinutes(e.target.value)}
                      className="flex-1 accent-emerald-500"
                      data-testid="mpp-gen-sticky-slider"
                    />
                    <Input
                      type="number"
                      min={1}
                      max={ttlCap}
                      value={stickyMinutes}
                      onChange={(e) => setStickyMinutes(e.target.value)}
                      className="w-20 bg-zinc-900/70 border-emerald-500/30 text-emerald-100 text-center"
                      data-testid="mpp-gen-sticky-min"
                    />
                    <span className="text-emerald-300 text-sm font-medium">min</span>
                  </div>
                  <p className="text-[10px] text-emerald-200/70 mt-1.5">
                    Each proxy line holds the same IP for up to <b>{Math.min(stickyMinutes, ttlCap)} min</b> before rotating (subject to the upstream network availability).
                  </p>
                </div>
              )}

              {/* Advanced Targeting section — always visible for every provider */}
              <div className="rounded-lg border border-blue-500/25 bg-zinc-950/40">
                <button
                  type="button"
                  onClick={() => setShowTargeting((v) => !v)}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-blue-500/5 transition"
                  data-testid="mpp-targeting-toggle"
                >
                  <span className="flex items-center gap-2 text-sm">
                    <Globe2 size={14} className="text-blue-300" />
                    <span className="text-blue-100 font-medium">Geo targeting</span>
                    <span className="text-[10px] text-zinc-500 italic">— optional, uses provider&apos;s native DSL</span>
                  </span>
                  {showTargeting ? <ChevronUp size={14} className="text-zinc-400" /> : <ChevronDown size={14} className="text-zinc-400" />}
                </button>
                {showTargeting && (
                  <div className="px-3 pb-3 space-y-3">
                    {kindHint && (
                      <div className="rounded border border-zinc-700/60 bg-zinc-900/40 px-3 py-2 text-[11px] text-zinc-400 flex items-start gap-2">
                        <Info size={12} className="text-blue-400 mt-0.5 shrink-0" />
                        <span>{kindHint}</span>
                      </div>
                    )}
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                      <div>
                        <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                          <Globe2 size={11} /> Country
                        </Label>
                        <SearchableCombo
                          value={country}
                          onChange={(v) => {
                            setCountry(v);
                            if (v !== country) {
                              setState("");
                              setCity("");
                              setAsn("");
                            }
                          }}
                          options={COUNTRY_OPTIONS}
                          placeholder="Any country — search or type ISO"
                          testid="mpp-gen-country"
                        />
                      </div>
                      <div>
                        <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                          <MapPin size={11} /> State / Region
                          {country && country !== "US" && (
                            <span className="text-zinc-600 lowercase text-[10px]">(free text)</span>
                          )}
                        </Label>
                        <SearchableCombo
                          value={state}
                          onChange={setState}
                          options={stateOptions}
                          placeholder={country === "US" ? "Any state — search or type code" : "e.g. bavaria, ontario, ile-de-france"}
                          testid="mpp-gen-state"
                        />
                      </div>
                      <div>
                        <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                          <Building2 size={11} /> City
                          {cityOptions.length === 0 && (
                            <span className="text-zinc-600 lowercase text-[10px]">(free text)</span>
                          )}
                        </Label>
                        <SearchableCombo
                          value={city}
                          onChange={setCity}
                          options={cityOptions}
                          placeholder={cityOptions.length ? "Search cities or type your own" : "e.g. miami, london, tokyo"}
                          testid="mpp-gen-city"
                        />
                      </div>
                      <div>
                        <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                          <Hash size={11} /> ZIP / Postal
                        </Label>
                        <Input
                          value={zip}
                          onChange={(e) => setZip(e.target.value)}
                          placeholder="e.g. 33101, SW1A"
                          className="bg-zinc-900/60 border-zinc-700 text-white"
                          data-testid="mpp-gen-zip"
                        />
                      </div>
                      <div>
                        <Label className="text-[11px] text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                          <Server size={11} /> ISP / ASN
                          {ispOptions.length === 0 && (
                            <span className="text-zinc-600 lowercase text-[10px]">(free text)</span>
                          )}
                        </Label>
                        <SearchableCombo
                          value={asn}
                          onChange={setAsn}
                          options={ispOptions}
                          placeholder={ispOptions.length ? "Pick an ISP or type ASN like 7018" : "e.g. comcast, 7018"}
                          testid="mpp-gen-asn"
                        />
                      </div>
                    </div>

                    {dslPreview && (
                      <div className="rounded border border-zinc-700/60 bg-black/40 px-3 py-2 flex items-start gap-2">
                        <Wand2 size={12} className="text-amber-300 mt-0.5 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">
                            Provider will receive
                          </div>
                          <code className="text-[11px] text-amber-200/90 font-mono block break-all">
                            {dslPreview}
                          </code>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <Button
                onClick={generateBatch}
                disabled={generating || !selectedId}
                className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white shadow-lg shadow-blue-500/20 w-full sm:w-auto"
                data-testid="my-proxy-providers-generate-btn"
              >
                {generating
                  ? <><Loader2 className="animate-spin mr-2" size={14} />Generating…</>
                  : <><Zap size={14} className="mr-2" />Generate {count} {proxyType.toUpperCase()} {parseInt(count, 10) === 1 ? "proxy" : "proxies"}</>}
              </Button>

              {output && (
                <div className="space-y-2 pt-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs text-zinc-400">
                      <span className="text-emerald-300 font-semibold">{output.split("\n").length}</span> proxies ready
                    </Label>
                    <div className="flex gap-2">
                      <Button
                        onClick={copyOutput}
                        variant="outline"
                        size="sm"
                        className="h-7 px-2 text-blue-300 border-blue-500/40 hover:bg-blue-500/10"
                        data-testid="my-proxy-providers-copy-btn"
                      >
                        <Copy size={12} className="mr-1" /> Copy
                      </Button>
                      <Button
                        onClick={downloadOutput}
                        variant="outline"
                        size="sm"
                        className="h-7 px-2 text-emerald-300 border-emerald-500/40 hover:bg-emerald-500/10"
                        data-testid="my-proxy-providers-download-btn"
                      >
                        <Download size={12} className="mr-1" /> Download .txt
                      </Button>
                    </div>
                  </div>
                  <textarea
                    value={output}
                    readOnly
                    className="w-full h-40 px-2 py-1 rounded-md bg-zinc-950/70 border border-zinc-700 text-white font-mono text-xs"
                    data-testid="my-proxy-providers-output"
                  />
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
