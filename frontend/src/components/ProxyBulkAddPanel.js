import { useMemo, useState } from "react";
import axios from "axios";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Label } from "./ui/label";
import { Input } from "./ui/input";
import { Checkbox } from "./ui/checkbox";
import { Badge } from "./ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "./ui/table";
import { toast } from "sonner";
import { Search, Plus, Loader2, Info } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const FORMAT_EXAMPLES = [
  "192.168.0.1:8000{Remark}",
  "192.168.0.1:8000:username:password{Remark}",
  "socks5://192.168.0.1:8000[Change IP URL]{Remark}",
  "http://[2001:db8:2de::e13]:8000[Change IP URL]{Remark}",
  "socks5://username:password@192.168.0.1:8000[Change IP URL]{Remark}",
  "http://user:pass@gate.example.com:10000",
  "http://host:port:user:pass",
];

/** Parse one AdsPower / Krexion proxy line for preview. */
export function parseProxyLine(raw, defaultType = "http") {
  let line = String(raw || "").trim();
  if (!line || line.startsWith("#")) return null;

  let remark = "";
  let changeIpUrl = "";
  const remarkMatch = line.match(/\{([^}]*)\}\s*$/);
  if (remarkMatch) {
    remark = remarkMatch[1].trim();
    line = line.slice(0, remarkMatch.index).trim();
  }
  const changeMatch = line.match(/\[([^\]]*)\]\s*$/);
  if (changeMatch) {
    changeIpUrl = changeMatch[1].trim();
    line = line.slice(0, changeMatch.index).trim();
  }

  let proxyType = defaultType;
  let username = "";
  let password = "";
  let host = "";
  let port = "";

  const schemeMatch = line.match(/^(https?|socks5h?|socks4|ssh):\/\//i);
  if (schemeMatch) {
    proxyType = schemeMatch[1].toLowerCase();
    line = line.slice(schemeMatch[0].length);
  }

  try {
    if (line.includes("@")) {
      const at = line.lastIndexOf("@");
      const auth = line.slice(0, at);
      const hostPart = line.slice(at + 1);
      const colon = auth.indexOf(":");
      username = colon >= 0 ? auth.slice(0, colon) : auth;
      password = colon >= 0 ? auth.slice(colon + 1) : "";
      if (hostPart.startsWith("[")) {
        const m = hostPart.match(/^\[([^\]]+)\]:(\d+)$/);
        if (!m) throw new Error("bad ipv6");
        host = m[1];
        port = m[2];
      } else {
        const hp = hostPart.split(":");
        host = hp[0];
        port = hp[1] || "";
      }
    } else if (line.startsWith("[")) {
      const m = line.match(/^\[([^\]]+)\]:(\d+)(?::([^:]*))?(?::(.*))?$/);
      if (!m) throw new Error("bad ipv6 line");
      host = m[1];
      port = m[2];
      username = m[3] || "";
      password = m[4] || "";
    } else {
      const parts = line.split(":");
      if (parts.length === 2) {
        host = parts[0];
        port = parts[1];
      } else if (parts.length >= 4) {
        host = parts[0];
        port = parts[1];
        username = parts[2];
        password = parts.slice(3).join(":");
      } else {
        throw new Error("need host:port");
      }
    }
  } catch (err) {
    return {
      raw,
      ok: false,
      error: err.message || "invalid",
      proxyType,
      host: "",
      port: "",
      username: "",
      password: "",
      remark,
      changeIpUrl,
      exitIp: "",
      isDuplicate: false,
      duplicateReason: "",
    };
  }

  if (!host || !port || !/^\d+$/.test(String(port))) {
    return {
      raw,
      ok: false,
      error: "host/port required",
      proxyType,
      host,
      port,
      username,
      password,
      remark,
      changeIpUrl,
      exitIp: "",
      isDuplicate: false,
      duplicateReason: "",
    };
  }

  return {
    raw,
    ok: true,
    error: "",
    proxyType,
    host,
    port: String(port),
    username,
    password,
    remark,
    changeIpUrl,
    exitIp: "",
    isDuplicate: false,
    duplicateReason: "",
  };
}

function identityKey(row) {
  if (!row?.ok) return "";
  return `${String(row.host).toLowerCase()}:${row.port}|${String(row.username || "").toLowerCase()}`;
}

/**
 * AdsPower-style bulk add: notes + formats | type/checker/tags + textarea,
 * Check proxy + Check duplicate, live preview table, then save.
 */
export default function ProxyBulkAddPanel({ existingProxies = [], onAdded }) {
  const [proxyType, setProxyType] = useState("http");
  const [ipChecker, setIpChecker] = useState("ipify");
  const [tags, setTags] = useState("");
  const [text, setText] = useState("");
  const [checkDuplicate, setCheckDuplicate] = useState(true);
  const [preview, setPreview] = useState([]);
  const [probing, setProbing] = useState(false);
  const [saving, setSaving] = useState(false);

  const existingKeys = useMemo(() => {
    const keys = new Set();
    for (const p of existingProxies || []) {
      const parsed = parseProxyLine(
        p.proxy_string || p.raw_line || "",
        p.proxy_type || "http"
      );
      if (parsed?.ok) keys.add(identityKey(parsed));
      if (p.proxy_string) keys.add(String(p.proxy_string).trim().toLowerCase());
    }
    return keys;
  }, [existingProxies]);

  const rebuildPreview = (rawText = text, type = proxyType) => {
    const lines = String(rawText || "")
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .slice(0, 500);
    const seen = new Set();
    const rows = [];
    for (const line of lines) {
      const row = parseProxyLine(line, type);
      if (!row) continue;
      if (row.ok) {
        const key = identityKey(row);
        const dupInBatch = key && seen.has(key);
        const dupInList =
          (key && existingKeys.has(key)) ||
          existingKeys.has(String(line).trim().toLowerCase());
        if (key) seen.add(key);
        row.isDuplicate = Boolean(dupInBatch || dupInList);
        row.duplicateReason = dupInList
          ? "already in Proxy list"
          : dupInBatch
            ? "duplicate in paste"
            : "";
      }
      rows.push(row);
    }
    setPreview(rows);
    return rows;
  };

  const handleTextChange = (value) => {
    setText(value);
    rebuildPreview(value, proxyType);
  };

  const handleCheckProxy = async () => {
    const rows = rebuildPreview();
    const valid = rows.filter((r) => r.ok && !(checkDuplicate && r.isDuplicate));
    if (valid.length === 0) {
      toast.error("No valid proxies to check — fix format or duplicates first");
      return;
    }
    setProbing(true);
    try {
      const token = localStorage.getItem("token");
      const res = await axios.post(
        `${API}/proxies/probe-lines`,
        {
          proxy_list: valid.map((r) => r.raw),
          proxy_type: proxyType,
          live: true,
          checker: ipChecker,
        },
        { headers: { Authorization: `Bearer ${token}` }, timeout: 180000 }
      );
      const byRaw = new Map((res.data?.results || []).map((r) => [r.raw, r]));
      setPreview((prev) =>
        prev.map((row) => {
          const hit = byRaw.get(row.raw);
          if (!hit) return row;
          return {
            ...row,
            exitIp: hit.exit_ip || "",
            ok: row.ok && hit.ok !== false,
            error: hit.error || row.error,
          };
        })
      );
      toast.success(
        `Checked ${res.data?.total || 0} — ${res.data?.ok || 0} ok, ${res.data?.failed || 0} failed`
      );
    } catch (err) {
      toast.error(err.response?.data?.detail || "Check proxy failed");
    } finally {
      setProbing(false);
    }
  };

  const handleAdd = async () => {
    const rows = rebuildPreview();
    let toAdd = rows.filter((r) => r.ok);
    if (checkDuplicate) toAdd = toAdd.filter((r) => !r.isDuplicate);
    if (toAdd.length === 0) {
      toast.error(
        checkDuplicate
          ? "Nothing to add — all lines invalid or duplicates (Check duplicate is ON)"
          : "Nothing to add — fix invalid lines"
      );
      return;
    }
    setSaving(true);
    try {
      const token = localStorage.getItem("token");
      const res = await axios.post(
        `${API}/proxies/upload`,
        {
          proxy_list: toAdd.map((r) => r.raw),
          proxy_type: proxyType,
          skip_duplicates: checkDuplicate,
          tags: tags.trim() || undefined,
        },
        { headers: { Authorization: `Bearer ${token}` }, timeout: 120000 }
      );
      const added = Array.isArray(res.data) ? res.data.length : 0;
      const skippedDupes = rows.filter((r) => r.ok && r.isDuplicate).length;
      const skippedInvalid = rows.filter((r) => !r.ok).length;
      let msg = `Added ${added} prox${added === 1 ? "y" : "ies"}`;
      if (checkDuplicate && skippedDupes) msg += ` · skipped ${skippedDupes} duplicate`;
      if (skippedInvalid) msg += ` · ${skippedInvalid} invalid`;
      toast.success(msg);
      setText("");
      setPreview([]);
      if (typeof onAdded === "function") onAdded(res.data || []);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to add proxies");
    } finally {
      setSaving(false);
    }
  };

  const validCount = preview.filter(
    (r) => r.ok && !(checkDuplicate && r.isDuplicate)
  ).length;
  const dupCount = preview.filter((r) => r.ok && r.isDuplicate).length;
  const badCount = preview.filter((r) => !r.ok).length;

  return (
    <div
      className="rounded-xl border border-[var(--brand-border)] bg-[var(--brand-card)] overflow-hidden"
      data-testid="proxy-bulk-add-panel"
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 divide-y lg:divide-y-0 lg:divide-x divide-[var(--brand-border)]">
        <div className="p-5 space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Info size={14} className="text-cyan-400" />
              Note
            </h3>
            <ol className="mt-2 text-xs text-zinc-400 space-y-1.5 list-decimal list-inside leading-relaxed">
              <li>If a line has no protocol, the Proxy type dropdown is used.</li>
              <li>Supported: HTTP, HTTPS, SOCKS5, SOCKS4.</li>
              <li>
                One proxy per line — up to <span className="text-zinc-200">500</span> at a time.
              </li>
              <li>
                IPv4 + IPv6 (wrap IPv6 host in <code className="text-cyan-300">[]</code>).
              </li>
              <li>
                <span className="text-emerald-400">Check duplicate ON</span> = identical
                host:port:user already in your list will not be added again.
              </li>
            </ol>
          </div>
          <div>
            <p className="text-xs font-medium text-zinc-300 mb-2">Filling formats</p>
            <div className="space-y-1 font-mono text-[11px]">
              {FORMAT_EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  className="block w-full text-left text-cyan-400/90 hover:text-cyan-300 truncate"
                  title="Click to append example"
                  onClick={() => handleTextChange(text ? `${text.trimEnd()}\n${ex}` : ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="p-5 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs text-zinc-400">Proxy type</Label>
              <select
                data-testid="bulk-proxy-type"
                value={proxyType}
                onChange={(e) => {
                  setProxyType(e.target.value);
                  rebuildPreview(text, e.target.value);
                }}
                className="flex h-9 w-full rounded-md border border-[var(--brand-border)] bg-zinc-950 px-3 text-sm text-white"
              >
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="socks5">SOCKS5</option>
                <option value="socks5h">SOCKS5H</option>
                <option value="socks4">SOCKS4</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-zinc-400">IP checker</Label>
              <select
                data-testid="bulk-ip-checker"
                value={ipChecker}
                onChange={(e) => setIpChecker(e.target.value)}
                className="flex h-9 w-full rounded-md border border-[var(--brand-border)] bg-zinc-950 px-3 text-sm text-white"
              >
                <option value="ipify">ipify</option>
                <option value="ip2location">IP2Location (via exit IP)</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-zinc-400">Tags</Label>
              <Input
                data-testid="bulk-proxy-tags"
                placeholder="Find / create a tag"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                className="h-9 bg-zinc-950 border-[var(--brand-border)]"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs text-zinc-400">Proxy information</Label>
            <Textarea
              data-testid="bulk-proxy-textarea"
              placeholder="Paste proxy lines here — auto-parsed into the table below."
              value={text}
              onChange={(e) => handleTextChange(e.target.value)}
              className="min-h-[180px] font-mono text-xs bg-zinc-950 border-[var(--brand-border)]"
            />
          </div>

          <div className="flex flex-wrap items-center gap-4 pt-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="bulk-check-proxy"
              onClick={handleCheckProxy}
              disabled={probing || !text.trim()}
              className="border-cyan-700 text-cyan-300"
            >
              {probing ? (
                <Loader2 size={14} className="mr-2 animate-spin" />
              ) : (
                <Search size={14} className="mr-2" />
              )}
              Check proxy
            </Button>
            <label
              className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer select-none"
              title="If you're adding a proxy identical to one already in the Proxy list, it won't be added again."
            >
              <Checkbox
                data-testid="bulk-check-duplicate"
                checked={checkDuplicate}
                onCheckedChange={(v) => setCheckDuplicate(Boolean(v))}
              />
              Check duplicate
            </label>
            <span
              className="text-xs text-zinc-500 ml-auto"
              data-testid="bulk-proxy-added-count"
            >
              Ready to add:{" "}
              <span className="text-white font-mono">{validCount}</span>
              {dupCount > 0 && (
                <span className="text-amber-400"> · {dupCount} dup</span>
              )}
              {badCount > 0 && (
                <span className="text-red-400"> · {badCount} invalid</span>
              )}
            </span>
            <Button
              type="button"
              size="sm"
              data-testid="bulk-add-proxies"
              onClick={handleAdd}
              disabled={saving || validCount === 0}
            >
              {saving ? (
                <Loader2 size={14} className="mr-2 animate-spin" />
              ) : (
                <Plus size={14} className="mr-2" />
              )}
              Add to list
            </Button>
          </div>
        </div>
      </div>

      {preview.length > 0 && (
        <div className="border-t border-[var(--brand-border)] overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-[11px]">Type</TableHead>
                <TableHead className="text-[11px]">Host</TableHead>
                <TableHead className="text-[11px]">Port</TableHead>
                <TableHead className="text-[11px]">Username</TableHead>
                <TableHead className="text-[11px]">Password</TableHead>
                <TableHead className="text-[11px]">Change IP URL</TableHead>
                <TableHead className="text-[11px]">Remark</TableHead>
                <TableHead className="text-[11px]">Outbound IP</TableHead>
                <TableHead className="text-[11px]">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.map((row, idx) => (
                <TableRow
                  key={`${idx}-${row.raw}`}
                  className={!row.ok || row.isDuplicate ? "opacity-70" : ""}
                >
                  <TableCell className="text-xs uppercase">{row.proxyType}</TableCell>
                  <TableCell className="font-mono text-xs">{row.host || "—"}</TableCell>
                  <TableCell className="font-mono text-xs">{row.port || "—"}</TableCell>
                  <TableCell className="font-mono text-xs max-w-[120px] truncate">
                    {row.username || "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs max-w-[100px] truncate">
                    {row.password ? "••••••" : "—"}
                  </TableCell>
                  <TableCell className="text-[10px] text-zinc-500 max-w-[140px] truncate">
                    {row.changeIpUrl || "—"}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {row.remark || "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-emerald-400">
                    {row.exitIp || "—"}
                  </TableCell>
                  <TableCell>
                    {!row.ok ? (
                      <Badge className="bg-red-500/20 text-red-300 text-[10px]">
                        {row.error || "invalid"}
                      </Badge>
                    ) : row.isDuplicate ? (
                      <Badge className="bg-amber-500/20 text-amber-300 text-[10px]">
                        duplicate
                        {row.duplicateReason ? `: ${row.duplicateReason}` : ""}
                      </Badge>
                    ) : row.exitIp ? (
                      <Badge className="bg-emerald-500/20 text-emerald-300 text-[10px]">
                        ok
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-[10px]">
                        ready
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
