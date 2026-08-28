import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Switch } from "../components/ui/switch";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { toast } from "sonner";
import { Plus, Trash2, Play, Edit2, Server, Wand2, Loader2, ShieldCheck, ExternalLink } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function authHeaders() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function ProxyProvidersTab() {
  const [providers, setProviders] = useState([]);
  const [kinds, setKinds] = useState([]);
  const [proxyTypes, setProxyTypes] = useState(["http", "https", "socks5", "socks5h", "socks4"]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({});
  // Smart-Paste state — customer can dump 1-N raw proxy strings of any
  // format (Task 1) and the tool auto-detects everything.
  const [smartPasteOpen, setSmartPasteOpen] = useState(false);
  const [smartInput, setSmartInput] = useState("");
  const [smartDefaultType, setSmartDefaultType] = useState("http");
  const [smartLoading, setSmartLoading] = useState(false);
  const [smartResult, setSmartResult] = useState(null);
  // v2.6.10 CUSTOMER-REQUEST — IP Quality Check dialog state
  const [qualityOpen, setQualityOpen] = useState(false);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityResult, setQualityResult] = useState(null);
  const [qualityProviderName, setQualityProviderName] = useState("");
  const [catalog, setCatalog] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const [p, m, cat] = await Promise.all([
        axios.get(`${API}/proxy-providers`, { headers: authHeaders() }),
        axios.get(`${API}/proxy-providers/_meta/kinds`, { headers: authHeaders() }),
        axios.get(`${API}/proxy-providers/_meta/catalog`, { headers: authHeaders() }).catch(() => ({ data: { providers: [] } })),
      ]);
      setProviders(p.data || []);
      setKinds(m.data.kinds || []);
      setProxyTypes(m.data.proxy_types || proxyTypes);
      setCatalog(cat.data?.providers || []);
    } catch (e) {
      toast.error("Failed to load proxy providers");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openNew = () => {
    setEditing({ isNew: true });
    setForm({
      name: "",
      kind: "rotating_gateway",
      proxy_type: "http",
      enabled: true,
      config: {
        strict_unique_ip: true,
        skip_datacenter_ip: true,
      },
    });
    setDialogOpen(true);
  };

  const openCatalogProvider = (item) => {
    if (!item) return;
    const isApi = item.kind === "api_endpoint";
    setEditing({ isNew: true, catalogId: item.id });
    setForm({
      name: item.name,
      kind: isApi ? "api_endpoint" : "rotating_gateway",
      proxy_type: item.proxy_type || "http",
      enabled: true,
      config: isApi
        ? {
            api_url: item.api_url || "",
            method: item.method || "GET",
            headers: item.headers || "",
            body: item.body || "",
            response_path: item.response_path || "",
            strict_unique_ip: true,
            skip_datacenter_ip: true,
          }
        : {
            gateway_host: item.gateway_host || "",
            gateway_port: String(item.gateway_port || ""),
            username: "",
            password: "",
            strict_unique_ip: true,
            skip_datacenter_ip: true,
          },
    });
    setDialogOpen(true);
    toast.info(`Enter your ${item.name} dashboard username + password — gateway is pre-filled.`);
  };

  const openEdit = (p) => {
    setEditing({ isNew: false, ...p });
    setForm({ ...p });
    setDialogOpen(true);
  };

  const save = async () => {
    if (!form.name || !form.kind) {
      toast.error("Name and Kind are required");
      return;
    }
    try {
      if (editing.isNew) {
        await axios.post(`${API}/proxy-providers`, form, { headers: authHeaders() });
        toast.success("Provider added");
      } else {
        const patch = {
          name: form.name,
          kind: form.kind,
          proxy_type: form.proxy_type,
          enabled: form.enabled,
          config: form.config || {},
        };
        await axios.put(`${API}/proxy-providers/${editing.id}`, patch, { headers: authHeaders() });
        toast.success("Provider updated");
      }
      setDialogOpen(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this provider?")) return;
    try {
      await axios.delete(`${API}/proxy-providers/${id}`, { headers: authHeaders() });
      toast.success("Deleted");
      load();
    } catch { toast.error("Delete failed"); }
  };

  const test = async (p) => {
    try {
      const res = await axios.post(`${API}/proxy-providers/${p.id}/test`, {}, { headers: authHeaders() });
      if (res.data.ok) {
        const s = res.data.sample || {};
        toast.success(`Test OK — ${s.use_proxyjet ? "provider " + (s.country || "") : (s.proxy ? s.proxy.slice(0, 40) + "…" : "resolved")}`);
      } else {
        toast.error(`Test failed: ${res.data.error || "unknown"}`);
      }
    } catch { toast.error("Test failed"); }
  };

  const toggleEnabled = async (p) => {
    try {
      await axios.put(`${API}/proxy-providers/${p.id}`, { enabled: !p.enabled }, { headers: authHeaders() });
      load();
    } catch { toast.error("Failed"); }
  };

  // v2.6.10 CUSTOMER-REQUEST — IP Quality Check
  // Fetches 5 sample proxies, probes each through-line against ip-api.com
  // to detect exit IP + datacenter/VPN flags. Shows verdict before the
  // customer burns a real click job's quota on a bad provider.
  const runQualityCheck = async (p) => {
    setQualityProviderName(p.name);
    setQualityResult(null);
    setQualityOpen(true);
    setQualityLoading(true);
    try {
      const res = await axios.post(
        `${API}/proxy-providers/${p.id}/ip-quality-check`,
        { count: 5 },
        { headers: authHeaders(), timeout: 90000 }
      );
      setQualityResult(res.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Quality check failed");
      setQualityResult({ ok: false, verdict: "failed", report: [] });
    } finally {
      setQualityLoading(false);
    }
  };

  const currentKind = kinds.find((k) => k.key === (form.kind || "rotating_gateway")) || kinds[0];
  const kindLabel = (k) => kinds.find((x) => x.key === k)?.label || k;

  // ── Smart Paste — auto-parse pasted proxy strings ───────────────
  const runSmartParse = async () => {
    if (!smartInput.trim()) {
      toast.error("Paste some proxy strings first");
      return;
    }
    setSmartLoading(true);
    setSmartResult(null);
    try {
      const r = await axios.post(
        `${API}/proxy-providers/_smart-parse`,
        { strings: [smartInput], default_type: smartDefaultType },
        { headers: authHeaders() }
      );
      setSmartResult(r.data);
      if ((r.data.ok_count || 0) === 0) {
        toast.error("Could not parse any strings — please check the format.");
      } else {
        toast.success(`Parsed ${r.data.ok_count} of ${(r.data.ok_count || 0) + (r.data.fail_count || 0)} strings`);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Parse failed");
    } finally {
      setSmartLoading(false);
    }
  };

  const useSmartParseAsNew = async () => {
    // Auto-create a provider from the parsed result.
    if (!smartResult || smartResult.ok_count === 0) {
      toast.error("Nothing to add");
      return;
    }
    const suggested = smartResult.suggested_kind || "manual_list";
    const config = smartResult.suggested_config || {};
    const proxy_type = smartResult.suggested_proxy_type || smartDefaultType;
    const defaultName = suggested === "rotating_gateway"
      ? `Gateway ${config.gateway_host || ""}`.trim()
      : `Paste ${smartResult.ok_count} proxies`;
    try {
      await axios.post(
        `${API}/proxy-providers`,
        {
          name: defaultName,
          kind: suggested,
          proxy_type,
          enabled: true,
          config,
        },
        { headers: authHeaders() }
      );
      toast.success("Provider added from Smart Paste");
      setSmartPasteOpen(false);
      setSmartInput("");
      setSmartResult(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to add provider");
    }
  };

  const applySmartToForm = () => {
    // Fill the classic form (already-open Add dialog) with the parsed result.
    if (!smartResult || smartResult.ok_count === 0) {
      toast.error("Parse a string first");
      return;
    }
    const suggested = smartResult.suggested_kind || "manual_list";
    const config = smartResult.suggested_config || {};
    setForm((f) => ({
      ...f,
      kind: suggested,
      proxy_type: smartResult.suggested_proxy_type || f.proxy_type,
      config,
      name: f.name || (suggested === "rotating_gateway"
        ? `Gateway ${config.gateway_host || ""}`.trim()
        : `Paste ${smartResult.ok_count} proxies`),
    }));
    setSmartPasteOpen(false);
    toast.success("Form filled from Smart Paste — review then click Add Provider");
  };


  const summarizeConfig = (p) => {
    const c = p.config || {};
    switch (p.kind) {
      case "rotating_gateway":
        return `${c.gateway_host || "?"}:${c.gateway_port || "?"}`;
      case "api_endpoint":
        return c.api_url ? c.api_url.slice(0, 40) + (c.api_url.length > 40 ? "…" : "") : "no url";
      case "manual_list": {
        const lines = (c.lines || "").toString().split(/\r?\n/).filter(Boolean);
        return `${lines.length} lines`;
      }
      case "native_proxyjet":
        return `country: ${c.country || "US"}${c.state ? ", state: " + c.state : ""}`;
      default:
        return "";
    }
  };

  return (
    <div className="space-y-6" data-testid="proxy-providers-tab">
      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Server size={20} /> Proxy Providers
              </CardTitle>
              <CardDescription className="mt-1">
                Add ANY proxy source &mdash; rotating gateways (Bright Data / Oxylabs / Soax / IPRoyal Gateway),
                REST-API endpoints (SmartProxy / Webshare / custom), manual lists, or Krexion&apos;s built-in
                ProxyJet with your country + state overrides. Any page that uses proxies (RUT, Browser
                Profiles, CPI, Proxy Test) will show a dropdown to pick which provider to use.
                When you have none, existing default flow runs unchanged.
              </CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => window.open(`${API}/docs/proxy-provider-template/view`, "_blank")} data-testid="proxy-provider-docs-btn" className="mr-2" title="Open provider template reference (all 8 supported providers with copy-paste examples)">
              <ExternalLink size={14} className="mr-1" /> Templates
            </Button>
            <Button size="sm" variant="outline" onClick={() => { setSmartInput(""); setSmartResult(null); setSmartPasteOpen(true); }} data-testid="proxy-provider-smart-paste-btn" className="mr-2">
              <Wand2 size={14} className="mr-1" /> Smart Paste
            </Button>
            <Button size="sm" onClick={openNew} data-testid="proxy-provider-add-btn">
              <Plus size={14} className="mr-1" /> Add Provider
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {catalog.length > 0 && (
            <div data-testid="proxy-provider-catalog">
              <p className="text-sm font-medium text-white mb-2">Popular providers — one-click setup</p>
              <p className="text-xs text-[var(--brand-muted)] mb-3">
                Pick your brand, paste dashboard username + password. Host, port, and geo/session DSL auto-configure for RUT, Browser Profiles, and CPI.
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                {catalog.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => openCatalogProvider(item)}
                    className="text-left rounded-lg border border-[var(--brand-border)] bg-[#0f1419] hover:border-[#3B82F6]/50 hover:bg-[#1a2332] px-3 py-2 transition-colors"
                    data-testid={`proxy-catalog-${item.id}`}
                  >
                    <div className="font-medium text-sm text-white truncate">{item.name}</div>
                    <div className="text-[10px] text-[var(--brand-muted)] mt-0.5 line-clamp-2">{item.tagline}</div>
                    {!item.kind && item.gateway_host && (
                      <div className="text-[10px] font-mono text-cyan-400/80 mt-1 truncate">
                        {item.gateway_host}:{item.gateway_port}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
          {providers.length === 0 && (
            <div className="text-sm text-[var(--brand-muted)] italic py-4">
              No providers yet &mdash; click &quot;Add Provider&quot; to add your first one, or continue using Krexion&apos;s default proxy flow.
            </div>
          )}
          {providers.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                  <TableHead>Name</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Proxy Type</TableHead>
                  <TableHead>Config</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead>Used</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {providers.map((p) => (
                  <TableRow key={p.id} className="border-[var(--brand-border)]" data-testid={`proxy-provider-row-${p.id}`}>
                    <TableCell className="font-medium">{p.name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="bg-[#1E293B]">{kindLabel(p.kind)}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs uppercase">{p.proxy_type}</TableCell>
                    <TableCell className="text-xs text-[var(--brand-muted)]">{summarizeConfig(p)}</TableCell>
                    <TableCell>
                      <Switch checked={!!p.enabled} onCheckedChange={() => toggleEnabled(p)} data-testid={`proxy-provider-toggle-${p.id}`} />
                    </TableCell>
                    <TableCell className="text-xs">{p.use_count || 0}</TableCell>
                    <TableCell className="text-right space-x-1">
                      <Button size="sm" variant="ghost" onClick={() => test(p)} title="Test connection" data-testid={`proxy-provider-test-${p.id}`}>
                        <Play size={14} />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => runQualityCheck(p)} title="IP Quality Check — sample 5 proxies & report unique-IP / non-VPN health" data-testid={`proxy-provider-quality-${p.id}`}>
                        <ShieldCheck size={14} className="text-cyan-300" />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => openEdit(p)} title="Edit" data-testid={`proxy-provider-edit-${p.id}`}>
                        <Edit2 size={14} />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => remove(p.id)} title="Delete" data-testid={`proxy-provider-delete-${p.id}`}>
                        <Trash2 size={14} className="text-red-400" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Add / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl" data-testid="proxy-provider-dialog">
          <DialogHeader>
            <DialogTitle>{editing?.isNew ? "Add Proxy Provider" : "Update Provider"}</DialogTitle>
            <DialogDescription>
              Configure any proxy source Krexion should choose from. Options here appear as a dropdown
              on pages that use proxies (RUT, Browser Profiles, CPI, Proxy Test).
            </DialogDescription>
          </DialogHeader>
          {editing?.catalogId && (() => {
            const cat = catalog.find((c) => c.id === editing.catalogId);
            if (!cat) return null;
            return (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-100">
                <strong>{cat.name}</strong> preset — {cat.username_hint}
                {cat.docs_url && (
                  <a href={cat.docs_url} target="_blank" rel="noreferrer" className="ml-2 underline text-emerald-300">
                    Open docs
                  </a>
                )}
              </div>
            );
          })()}
          {editing?.isNew && !editing?.catalogId && (
            <div className="rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-2 flex items-center justify-between text-xs">
              <span className="text-blue-200">
                Don&apos;t know host/port? Paste any raw proxy strings and let Krexion auto-detect
                the type (HTTP/SOCKS5/etc) &amp; fill everything for you.
              </span>
              <Button size="sm" variant="outline" onClick={() => { setSmartInput(""); setSmartResult(null); setSmartPasteOpen(true); }} data-testid="proxy-form-smart-paste-btn" className="ml-3 shrink-0">
                <Wand2 size={12} className="mr-1" /> Smart Paste
              </Button>
            </div>
          )}
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Name</Label>
                <Input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })}
                       placeholder="My New API Provider" data-testid="proxy-form-name" />
              </div>
              <div>
                <Label>Kind</Label>
                <Select value={form.kind || "rotating_gateway"}
                        onValueChange={(v) => setForm({ ...form, kind: v, config: {} })}>
                  <SelectTrigger data-testid="proxy-form-kind">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {kinds.map((k) => (
                      <SelectItem key={k.key} value={k.key}>{k.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Proxy Type</Label>
                <Select value={form.proxy_type || "http"}
                        onValueChange={(v) => setForm({ ...form, proxy_type: v })}>
                  <SelectTrigger data-testid="proxy-form-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {proxyTypes.map((t) => (
                      <SelectItem key={t} value={t}>{t.toUpperCase()}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end justify-between">
                <div>
                  <Label>Enabled</Label>
                  <div className="pt-2">
                    <Switch checked={!!form.enabled}
                            onCheckedChange={(v) => setForm({ ...form, enabled: v })}
                            data-testid="proxy-form-enabled" />
                  </div>
                </div>
              </div>
            </div>

            {currentKind && (
              <div className="text-xs text-[var(--brand-muted)] italic">
                {currentKind.description}
              </div>
            )}

            {currentKind && currentKind.fields.map((f) => {
              const val = (form.config && form.config[f.key]) || "";
              const set = (v) => setForm({ ...form, config: { ...(form.config || {}), [f.key]: v } });
              return (
                <div key={f.key}>
                  <Label>{f.label}</Label>
                  {f.type === "textarea" ? (
                    <Textarea rows={f.key === "lines" ? 6 : 3} value={val} onChange={(e) => set(e.target.value)}
                              placeholder={f.placeholder} data-testid={`proxy-form-cfg-${f.key}`} />
                  ) : f.type === "password" ? (
                    <Input type="password" value={val} onChange={(e) => set(e.target.value)}
                           placeholder={f.placeholder} data-testid={`proxy-form-cfg-${f.key}`} />
                  ) : (
                    <Input value={val} onChange={(e) => set(e.target.value)}
                           placeholder={f.placeholder} data-testid={`proxy-form-cfg-${f.key}`} />
                  )}
                </div>
              );
            })}

            {/* v2.6.10 CUSTOMER-REQUEST — Unique-IP + Non-VPN guarantee toggles.
                Applied before each proxy line leaves this provider, so RUT
                jobs see only unique, residential/mobile IPs. Default ON. */}
            <div className="mt-2 pt-3 border-t border-[var(--brand-border)] space-y-3">
              <div className="text-xs font-medium text-cyan-300 flex items-center gap-1">
                <ShieldCheck size={13}/> IP Quality Guarantee
              </div>
              <div className="flex items-start justify-between gap-4">
                <div className="text-xs">
                  <div className="font-medium text-[var(--brand-text)]">Strict unique IP</div>
                  <div className="text-[var(--brand-muted)] mt-0.5">
                    Probe every fetched proxy through-line; retry the session (up to 5×) if the exit IP
                    was already used in this batch. Guarantees no duplicate IPs on the tracker.
                  </div>
                </div>
                <Switch
                  checked={form.config?.strict_unique_ip !== false}
                  onCheckedChange={(v) => setForm({ ...form, config: { ...(form.config || {}), strict_unique_ip: v } })}
                  data-testid="proxy-form-strict-unique-ip"
                />
              </div>
              <div className="flex items-start justify-between gap-4">
                <div className="text-xs">
                  <div className="font-medium text-[var(--brand-text)]">Skip datacenter / VPN IPs</div>
                  <div className="text-[var(--brand-muted)] mt-0.5">
                    Reject proxies whose exit IP is flagged as hosting / datacenter / VPN by ip-api
                    (offer trackers block these — root cause of &quot;Traffic from proxies is blocked&quot;).
                  </div>
                </div>
                <Switch
                  checked={form.config?.skip_datacenter_ip !== false}
                  onCheckedChange={(v) => setForm({ ...form, config: { ...(form.config || {}), skip_datacenter_ip: v } })}
                  data-testid="proxy-form-skip-datacenter"
                />
              </div>
              <div className="text-[11px] text-[var(--brand-muted)] italic">
                Both toggles add ~1-3 s per proxy on first probe. Results cache for 7 days per IP
                (Mongo), so repeat runs are near-instant. Disable only if you need max throughput
                and trust your provider fully.
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} data-testid="proxy-form-save">
              {editing?.isNew ? "Add Provider" : "Update Provider"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Smart Paste dialog — auto-detects any proxy string format */}
      <Dialog open={smartPasteOpen} onOpenChange={setSmartPasteOpen}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl" data-testid="proxy-smart-paste-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wand2 size={18} className="text-amber-300" /> Smart Paste — Any Proxy Format
            </DialogTitle>
            <DialogDescription>
              Paste 1–500 proxy strings in <b>ANY</b> format. Krexion auto-detects the type
              (<code>http</code>, <code>https</code>, <code>socks5</code>, <code>socks5h</code>, <code>socks4</code>)
              and parses host, port, username, password. Then click <i>Parse</i> to preview, and
              <i> Add Provider</i> to save.
              <br />
              <span className="text-xs text-[var(--brand-muted)] mt-1 block">
                Supported: <code>socks5://user:pass@host:port</code> · <code>http://host:port</code> ·
                <code> user:pass@host:port</code> · <code>host:port</code> · <code>host:port:user:pass</code> ·
                <code> host,port,user,pass</code>
              </span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Label>Paste proxy strings (one per line)</Label>
                <Textarea
                  rows={7}
                  value={smartInput}
                  onChange={(e) => setSmartInput(e.target.value)}
                  placeholder={"socks5://joe:pw@1.2.3.4:1080\nhttp://5.6.7.8:8080\nhost.example.com:3128:user:pass"}
                  data-testid="proxy-smart-paste-input"
                  className="font-mono text-xs"
                />
              </div>
              <div>
                <Label>Default type (if scheme missing)</Label>
                <Select value={smartDefaultType} onValueChange={setSmartDefaultType}>
                  <SelectTrigger data-testid="proxy-smart-paste-default-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {proxyTypes.map((t) => (
                      <SelectItem key={t} value={t}>{t.toUpperCase()}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-[var(--brand-muted)] mt-2 leading-tight">
                  Lines that don&apos;t have <code>socks5://</code> or <code>http://</code> etc.
                  will use this scheme. Lines that DO include a scheme keep their own.
                </p>
              </div>
            </div>
            <Button onClick={runSmartParse} disabled={smartLoading} data-testid="proxy-smart-paste-parse-btn" className="bg-amber-500 hover:bg-amber-600 text-black">
              {smartLoading ? <><Loader2 size={14} className="mr-1 animate-spin" /> Parsing…</> : <><Wand2 size={14} className="mr-1" /> Parse</>}
            </Button>

            {smartResult && (
              <div className="rounded-md border border-[var(--brand-border)] p-3 space-y-2 max-h-64 overflow-auto" data-testid="proxy-smart-paste-preview">
                <div className="text-xs flex items-center gap-3">
                  <span className="text-emerald-400">OK: <b>{smartResult.ok_count}</b></span>
                  <span className="text-red-400">Failed: <b>{smartResult.fail_count}</b></span>
                  <span className="text-blue-300">Suggested kind: <b>{smartResult.suggested_kind}</b></span>
                  <span className="text-blue-300">Dominant type: <b>{(smartResult.suggested_proxy_type || "").toUpperCase()}</b></span>
                </div>
                <div className="space-y-1">
                  {(smartResult.parsed || []).map((p, i) => (
                    <div key={i} className={"text-[11px] font-mono flex items-start gap-2 " + (p.ok ? "text-emerald-300" : "text-red-300")}>
                      <span className="shrink-0 w-6">{p.ok ? "✓" : "✗"}</span>
                      <span className="truncate flex-1">
                        {p.ok ? p.normalized : `${p.raw} — ${p.error}`}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSmartPasteOpen(false)}>Cancel</Button>
            {smartResult && smartResult.ok_count > 0 && (
              <>
                {dialogOpen && (
                  <Button variant="outline" onClick={applySmartToForm} data-testid="proxy-smart-paste-apply-btn">
                    Fill Form
                  </Button>
                )}
                <Button onClick={useSmartParseAsNew} data-testid="proxy-smart-paste-add-btn">
                  Add Provider Now
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* v2.6.10 CUSTOMER-REQUEST — IP Quality Check result dialog */}
      <Dialog open={qualityOpen} onOpenChange={setQualityOpen}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl" data-testid="proxy-quality-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck size={18} className="text-cyan-300" /> IP Quality Check — {qualityProviderName}
            </DialogTitle>
            <DialogDescription>
              Krexion fetches 5 sample proxies from this provider and probes each one through-line
              against ip-api.com. Verdict shows whether this provider will produce clean unique
              residential IPs — the ones offer trackers accept.
            </DialogDescription>
          </DialogHeader>
          {qualityLoading && (
            <div className="flex items-center justify-center py-8 text-sm text-[var(--brand-muted)]">
              <Loader2 size={20} className="animate-spin mr-2" /> Probing 5 proxies… (up to ~15 s)
            </div>
          )}
          {!qualityLoading && qualityResult && (
            <div className="space-y-3">
              <div className="grid grid-cols-4 gap-3 text-center">
                <div className="rounded-md bg-[var(--brand-bg)] border border-[var(--brand-border)] p-3">
                  <div className="text-2xl font-bold text-[var(--brand-text)]">{qualityResult.returned || 0}</div>
                  <div className="text-[11px] text-[var(--brand-muted)] uppercase tracking-wide">Fetched</div>
                </div>
                <div className="rounded-md bg-[var(--brand-bg)] border border-[var(--brand-border)] p-3">
                  <div className="text-2xl font-bold text-cyan-300">{qualityResult.unique_ips || 0}</div>
                  <div className="text-[11px] text-[var(--brand-muted)] uppercase tracking-wide">Unique IPs</div>
                </div>
                <div className="rounded-md bg-[var(--brand-bg)] border border-[var(--brand-border)] p-3">
                  <div className="text-2xl font-bold text-emerald-400">{qualityResult.residential || 0}</div>
                  <div className="text-[11px] text-[var(--brand-muted)] uppercase tracking-wide">Residential</div>
                </div>
                <div className="rounded-md bg-[var(--brand-bg)] border border-[var(--brand-border)] p-3">
                  <div className="text-2xl font-bold text-amber-400">{qualityResult.datacenter_or_vpn || 0}</div>
                  <div className="text-[11px] text-[var(--brand-muted)] uppercase tracking-wide">DC / VPN</div>
                </div>
              </div>
              <div className={
                "rounded-md p-3 text-sm font-medium " +
                (qualityResult.verdict === "excellent" ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/40" :
                 qualityResult.verdict === "good"      ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/40" :
                 qualityResult.verdict === "poor"      ? "bg-amber-500/15 text-amber-300 border border-amber-500/40" :
                                                         "bg-red-500/15 text-red-300 border border-red-500/40")
              } data-testid="proxy-quality-verdict">
                Verdict: <b className="uppercase">{qualityResult.verdict || "unknown"}</b>
                {qualityResult.verdict === "excellent" && " — all IPs unique, all residential. Perfect for click jobs."}
                {qualityResult.verdict === "good"      && " — mostly unique + residential. Safe for click jobs."}
                {qualityResult.verdict === "poor"      && " — provider returned duplicate or datacenter IPs. Offer trackers will block these."}
                {qualityResult.verdict === "failed"    && " — could not probe any proxy. Check credentials & connection."}
              </div>
              <div className="rounded-md border border-[var(--brand-border)] max-h-72 overflow-auto">
                <table className="w-full text-xs">
                  <thead className="bg-[var(--brand-bg)] sticky top-0">
                    <tr className="border-b border-[var(--brand-border)]">
                      <th className="text-left px-3 py-2 font-medium text-[var(--brand-muted)]">Exit IP</th>
                      <th className="text-left px-3 py-2 font-medium text-[var(--brand-muted)]">Country</th>
                      <th className="text-left px-3 py-2 font-medium text-[var(--brand-muted)]">ISP</th>
                      <th className="text-center px-3 py-2 font-medium text-[var(--brand-muted)]">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(qualityResult.report || []).map((r, i) => (
                      <tr key={i} className="border-b border-[var(--brand-border)] last:border-b-0">
                        <td className="px-3 py-2 font-mono text-[11px]">{r.ip || "—"}</td>
                        <td className="px-3 py-2">{r.country || "—"} {r.city && <span className="text-[var(--brand-muted)]">/ {r.city}</span>}</td>
                        <td className="px-3 py-2 text-[var(--brand-muted)] truncate max-w-[220px]" title={r.isp}>{r.isp || "—"}</td>
                        <td className="px-3 py-2 text-center">
                          {r.probe_ok ? (
                            r.is_hosting || r.is_proxy ? <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/40">DC / VPN</Badge>
                            : r.is_mobile               ? <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/40">Mobile</Badge>
                            :                             <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/40">Residential</Badge>
                          ) : (
                            <Badge className="bg-red-500/20 text-red-300 border-red-500/40">Probe fail</Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setQualityOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
