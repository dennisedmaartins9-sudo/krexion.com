import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Package, Smartphone, Server, FileSpreadsheet, Trash2, Plus, RefreshCw, FileCode, ExternalLink, Pencil, Camera, Download, CheckSquare, Square } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import GSheetTabPicker from "../components/GSheetTabPicker";
import useVisibleInterval from "../hooks/useVisibleInterval";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const OS_OPTIONS = [
  { value: "android", label: "Android" },
  { value: "ios", label: "iOS" },
  { value: "windows", label: "Windows" },
  { value: "macos", label: "macOS" },
  { value: "linux", label: "Linux" },
];

const NETWORK_OPTIONS = [
  { value: "tiktok", label: "TikTok" },
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "snapchat", label: "Snapchat" },
  { value: "twitter", label: "Twitter / X" },
  { value: "youtube", label: "YouTube" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "telegram", label: "Telegram" },
  { value: "chrome", label: "Chrome Browser" },
  { value: "safari", label: "Safari Browser" },
  { value: "firefox", label: "Firefox" },
];

const COUNTRY_OPTIONS = [
  { value: "US", label: "United States" },
  { value: "GB", label: "United Kingdom" },
  { value: "CA", label: "Canada" },
  { value: "AU", label: "Australia" },
  { value: "DE", label: "Germany" },
  { value: "FR", label: "France" },
  { value: "IN", label: "India" },
  { value: "PK", label: "Pakistan" },
  { value: "BR", label: "Brazil" },
  { value: "MX", label: "Mexico" },
];

const TABS = [
  { key: "user_agents", label: "User Agents / Networks", icon: Smartphone },
  { key: "proxies", label: "Proxies", icon: Server },
  { key: "data_file", label: "Data Files", icon: FileSpreadsheet },
  { key: "automation_json", label: "Automation JSON", icon: FileCode },
];

function TagBadge({ children, color = "indigo" }) {
  // 2026-06 — added `yellow` + `blue` palette for the "used" + "original"
  // count badges on the Data-Files tab (and any future tabs that need
  // additional accent colours). The `indigo` + `emerald` defaults are
  // unchanged so existing call-sites render identically.
  const palette = {
    indigo:  { bg: "rgba(99, 102, 241, 0.15)",  fg: "rgb(165, 180, 252)" },
    emerald: { bg: "rgba(16, 185, 129, 0.15)",  fg: "rgb(110, 231, 183)" },
    yellow:  { bg: "rgba(234, 179,   8, 0.15)", fg: "rgb(253, 224,  71)" },
    blue:    { bg: "rgba( 59, 130, 246, 0.15)", fg: "rgb(147, 197, 253)" },
  };
  const c = palette[color] || palette.indigo;
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: c.bg, color: c.fg }}
    >
      {children}
    </span>
  );
}

// 2026-06 — Bulk action toolbar shown above every list of uploaded
// resources. Renders a "select-all / N selected / delete / download"
// row. `showDownload` is opt-in (only Data-Files tab has files behind
// rows; UA / Proxy / Automation-JSON tabs store inline strings/JSON
// so there's nothing to "download as file" — only the per-row
// existing copy-buttons make sense there).
function BulkActionBar({
  selectedCount, totalCount, allChecked,
  onToggleAll, onBulkDelete, onBulkDownload,
  showDownload = false,
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        type="button"
        onClick={onToggleAll}
        className="flex items-center gap-1.5 text-xs text-zinc-300 hover:text-indigo-300 px-2 py-1 rounded border border-zinc-700 bg-zinc-900/40"
        data-testid="ut-bulk-toggle-all"
      >
        {allChecked
          ? <CheckSquare size={14} className="text-indigo-400" />
          : <Square size={14} />}
        {allChecked ? "Unselect all" : `Select all (${totalCount})`}
      </button>
      {selectedCount > 0 && (
        <>
          <span className="text-xs text-zinc-400">{selectedCount} selected</span>
          {showDownload && (
            <Button
              size="sm"
              variant="outline"
              onClick={onBulkDownload}
              className="h-7 px-2 text-emerald-300 border-emerald-700/40 hover:bg-emerald-900/20 hover:text-emerald-200"
              data-testid="ut-bulk-download"
            >
              <Download size={13} className="mr-1" />
              Download
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={onBulkDelete}
            className="h-7 px-2 text-red-300 border-red-700/40 hover:bg-red-900/20 hover:text-red-200"
            data-testid="ut-bulk-delete"
          >
            <Trash2 size={13} className="mr-1" />
            Delete
          </Button>
        </>
      )}
    </div>
  );
}

function GSheetLinkBlock({ u, onSynced }) {
  const [syncing, setSyncing] = useState(false);
  if (!u?.gsheet_url) return null;

  // Last-sync friendly text
  const last = u?.last_synced_at;
  let agoText = "never synced";
  if (last) {
    const diff = Math.max(0, Date.now() - new Date(last).getTime());
    if (diff < 5_000) agoText = "just now";
    else if (diff < 60_000) agoText = `${Math.round(diff / 1000)}s ago`;
    else if (diff < 3_600_000) agoText = `${Math.round(diff / 60_000)}m ago`;
    else agoText = `${Math.round(diff / 3_600_000)}h ago`;
  }

  // Pull the gid out of the URL so we can label the tab
  const gidMatch = (u.gsheet_url || "").match(/[?&#]gid=(\d+)/);
  const tabLabel = gidMatch ? `tab gid=${gidMatch[1]}` : "first tab";

  // Live row counts from the upload doc — these come back fresh on every
  // /api/uploads list call (server re-syncs gsheet metadata on demand).
  const remaining = Number(u?.available_count ?? u?.item_count ?? 0);
  const consumed = Number(u?.consumed_count ?? 0);
  const total = Number(u?.original_item_count ?? remaining + consumed);

  const onSyncNow = async () => {
    setSyncing(true);
    try {
      const tok = localStorage.getItem("token");
      await axios.post(
        `${API}/uploads/${u.id}/sync-gsheet`,
        {},
        { headers: { Authorization: `Bearer ${tok}` } }
      );
      toast.success("Sheet synced");
      if (onSynced) await onSynced();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div
      className="mt-2 rounded-md border border-emerald-700/30 bg-emerald-900/10 px-2.5 py-2 space-y-1.5"
      data-testid={`ut-gsheet-block-${u.id}`}
    >
      {/* Top row: pretty link + tab label */}
      <div className="flex items-center gap-2 flex-wrap">
        <a
          href={u.gsheet_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-300 hover:text-emerald-200 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/20 transition"
          title={u.gsheet_url}
          data-testid={`ut-gsheet-open-${u.id}`}
        >
          <ExternalLink className="w-3 h-3" />
          Open sheet
        </a>
        <span
          className="text-[10px] text-emerald-400/70 font-mono"
          title="Worksheet tab this upload is attached to"
        >
          {tabLabel}
        </span>
      </div>

      {/* Stats row: live count + sync status + sync-now button */}
      <div className="flex items-center justify-between gap-2 flex-wrap text-[10px]">
        <div className="flex items-center gap-2">
          <span
            className="text-emerald-200 font-semibold"
            data-testid={`ut-gsheet-count-${u.id}`}
          >
            {remaining.toLocaleString()} rows left
          </span>
          {consumed > 0 && (
            <span
              className="text-zinc-500"
              title={`${consumed.toLocaleString()} consumed of ${total.toLocaleString()} total`}
            >
              · {consumed.toLocaleString()} used
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="text-emerald-400/60"
            title="Live Google-Sheet uploads auto-sync every 30s. Edit your sheet — new rows show up here automatically."
            data-testid={`ut-synced-${u.id}`}
          >
            ↻ synced {agoText}
          </span>
          <button
            type="button"
            onClick={onSyncNow}
            disabled={syncing}
            className="px-1.5 py-0.5 rounded border border-emerald-700/40 text-emerald-300/80 hover:bg-emerald-800/20 disabled:opacity-50"
            title="Force-refresh this sheet right now (skips the cache)"
            data-testid={`ut-sync-now-${u.id}`}
          >
            {syncing ? "syncing…" : "sync now"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Renders a "X / Y used" amber pill (and a separate red "DEPLETED" pill
 * when the upload has been fully consumed). Works for both static
 * uploads (proxies/UAs/data-files) and live Google-Sheet uploads.
 */
function ConsumptionPill({ u, unit = "items" }) {
  const original = Number(u?.original_item_count || 0);
  const consumed = Number(u?.consumed_count || 0);
  const available = Number(u?.available_count || u?.item_count || 0);
  const isDepleted = !!u?.depleted || (original > 0 && available === 0 && consumed > 0);
  if (!isDepleted && consumed === 0) return null;
  return (
    <>
      {consumed > 0 && (
        <span
          className="inline-block px-2 py-0.5 rounded text-xs font-medium"
          style={{ backgroundColor: "rgba(245, 158, 11, 0.15)", color: "rgb(252, 211, 77)" }}
          title={`${consumed} consumed / ${available} available (of ${original || consumed + available} original)`}
          data-testid={`ut-consumed-${u.id}`}
        >
          {available} available · {consumed} used
        </span>
      )}
      {isDepleted && (
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold"
          style={{ backgroundColor: "rgba(248, 113, 113, 0.15)", color: "rgb(252, 165, 165)" }}
          title={`All ${unit} consumed${u?.depleted_at ? " on " + new Date(u.depleted_at).toLocaleString() : ""}. Entry kept for record; on-disk file removed.`}
          data-testid={`ut-depleted-${u.id}`}
        >
          ● DEPLETED
        </span>
      )}
    </>
  );
}

export default function UploadedThingsPage() {
  const token = localStorage.getItem("token");
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("user_agents");
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(false);

  // UA form
  const [uaName, setUaName] = useState("");
  const [uaOs, setUaOs] = useState("android");
  const [uaNetwork, setUaNetwork] = useState("tiktok");
  const [uaText, setUaText] = useState("");
  const [uaSaving, setUaSaving] = useState(false);
  // Google-Sheet variant of UA batch
  const [uaMode, setUaMode] = useState("text");        // "text" | "gsheet"
  const [uaGSheetUrl, setUaGSheetUrl] = useState("");

  // Proxy form
  const [pxName, setPxName] = useState("");
  const [pxCountry, setPxCountry] = useState("US");
  const [pxState, setPxState] = useState("");
  const [pxText, setPxText] = useState("");
  const [pxSaving, setPxSaving] = useState(false);
  // Google-Sheet variant of proxy batch
  const [pxMode, setPxMode] = useState("text");        // "text" | "gsheet"
  const [pxGSheetUrl, setPxGSheetUrl] = useState("");

  // Data file form
  const [dfName, setDfName] = useState("");
  const [dfFile, setDfFile] = useState(null);
  const [dfSaving, setDfSaving] = useState(false);
  // Google-Sheet variant of "data file" — paste a public sheet URL
  // once, every future job auto-fetches the latest rows live.
  const [dfMode, setDfMode] = useState("file");   // "file" | "gsheet"
  const [dfGSheetUrl, setDfGSheetUrl] = useState("");

  // Automation JSON form
  const [ajName, setAjName] = useState("");
  const [ajDesc, setAjDesc] = useState("");
  const [ajJson, setAjJson] = useState("");
  const [ajSaving, setAjSaving] = useState(false);

  // ── Edit modal for saved Automation-JSON templates ─────────────
  // Lets the user fix typos / add+remove steps / update selectors
  // WITHOUT deleting the upload — so every RUT job that already
  // references this template keeps working after the edit.
  const [editAJ, setEditAJ] = useState(null);   // {id, name, description, automation_json} | null
  const [editAJSaving, setEditAJSaving] = useState(false);

  const openEditAJ = (u) => {
    setEditAJ({
      id: u.id,
      name: u.name || "",
      description: u.description || "",
      automation_json: u.automation_json || "",
    });
  };

  const saveEditAJ = async () => {
    if (!editAJ) return;
    if (!editAJ.name.trim()) return toast.error("Template name cannot be empty");
    if (!editAJ.automation_json.trim()) return toast.error("Automation JSON cannot be empty");
    try { JSON.parse(editAJ.automation_json); }
    catch (e) { return toast.error("Invalid JSON: " + e.message); }
    setEditAJSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", editAJ.name);
      fd.append("description", editAJ.description || "");
      fd.append("automation_json", editAJ.automation_json);
      await axios.patch(`${API}/uploads/automation-json/${editAJ.id}`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Template updated");
      setEditAJ(null);
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Update failed");
    } finally {
      setEditAJSaving(false);
    }
  };

  const fetchUploads = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const r = await axios.get(`${API}/uploads`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setUploads(r.data || []);
    } catch (e) {
      if (!silent) toast.error(e?.response?.data?.detail || "Failed to load uploads");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchUploads();
  }, [fetchUploads]);

  // Auto-refresh every 30s — keeps live Google-Sheet uploads in sync
  // when the page is open (sheet edits show up automatically, depleted
  // batches auto-undeplete the moment the user pastes new rows).
  // Pauses automatically while the tab is in the background — saves
  // bandwidth + cuts gsheet API hits when the user has many tabs open.
  useVisibleInterval(() => fetchUploads({ silent: true }), 30_000);

  const createUA = async () => {
    if (!uaName.trim()) return toast.error("Give this batch a name");
    if (uaMode === "text" && !uaText.trim()) return toast.error("Paste at least one user-agent");
    if (uaMode === "gsheet" && !uaGSheetUrl.trim()) return toast.error("Paste a Google Sheet URL");
    setUaSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", uaName);
      fd.append("os_tag", uaOs);
      fd.append("network_tag", uaNetwork);
      let endpoint;
      if (uaMode === "gsheet") {
        endpoint = `${API}/uploads/user-agents-gsheet`;
        fd.append("gsheet_url", uaGSheetUrl.trim());
      } else {
        endpoint = `${API}/uploads/user-agents`;
        fd.append("user_agents", uaText);
      }
      await axios.post(endpoint, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success(uaMode === "gsheet"
        ? "Google Sheet linked — UAs will auto-refresh + auto-skip after-use"
        : "User-agent batch saved");
      setUaName(""); setUaText(""); setUaGSheetUrl("");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setUaSaving(false);
    }
  };

  const createProxy = async () => {
    if (!pxName.trim()) return toast.error("Give this batch a name");
    if (pxMode === "text" && !pxText.trim()) return toast.error("Paste at least one proxy line");
    if (pxMode === "gsheet" && !pxGSheetUrl.trim()) return toast.error("Paste a Google Sheet URL");
    setPxSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", pxName);
      fd.append("country_tag", pxCountry);
      if (pxState.trim()) fd.append("state_tag", pxState.trim());
      let endpoint;
      if (pxMode === "gsheet") {
        endpoint = `${API}/uploads/proxies-gsheet`;
        fd.append("gsheet_url", pxGSheetUrl.trim());
      } else {
        endpoint = `${API}/uploads/proxies`;
        fd.append("proxies", pxText);
      }
      await axios.post(endpoint, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success(pxMode === "gsheet"
        ? "Google Sheet linked — proxies will auto-refresh + auto-skip after-use"
        : "Proxy batch saved");
      setPxName(""); setPxText(""); setPxState(""); setPxGSheetUrl("");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setPxSaving(false);
    }
  };

  const createDF = async () => {
    if (!dfName.trim()) return toast.error("Give this file a name");
    if (dfMode === "file" && !dfFile) return toast.error("Choose an Excel/CSV file");
    if (dfMode === "gsheet" && !dfGSheetUrl.trim()) return toast.error("Paste a Google Sheet URL");
    setDfSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", dfName);
      let endpoint;
      if (dfMode === "gsheet") {
        endpoint = `${API}/uploads/data-file-gsheet`;
        fd.append("gsheet_url", dfGSheetUrl.trim());
      } else {
        endpoint = `${API}/uploads/data-file`;
        fd.append("file", dfFile);
      }
      await axios.post(endpoint, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success(dfMode === "gsheet" ? "Google Sheet linked — rows will auto-refresh on every job" : "Data file saved");
      setDfName(""); setDfFile(null); setDfGSheetUrl("");
      const inp = document.getElementById("df-file-input");
      if (inp) inp.value = "";
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setDfSaving(false);
    }
  };

  const createAJ = async () => {
    if (!ajName.trim()) return toast.error("Give this template a name");
    if (!ajJson.trim()) return toast.error("Paste the automation JSON");
    try { JSON.parse(ajJson); }
    catch (e) { return toast.error("Invalid JSON: " + e.message); }
    setAjSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", ajName);
      if (ajDesc.trim()) fd.append("description", ajDesc);
      fd.append("automation_json", ajJson);
      await axios.post(`${API}/uploads/automation-json`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Automation template saved");
      setAjName(""); setAjDesc(""); setAjJson("");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setAjSaving(false);
    }
  };

  const deleteUpload = async (id, name) => {
    if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API}/uploads/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Deleted");
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  // ── 2026-06 — Bulk selection & bulk delete (all 4 tabs) ──────────
  // Per-tab Set<id> of currently-checked rows. Bulk delete posts to
  // /api/uploads/bulk-delete in ONE request (server scopes by user_id
  // so cross-tenant deletion is structurally impossible).
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  // Helper used by every tab-switch button: changes tab AND clears
  // selection in one render, so a row checked on tab A can never be
  // accidentally bulk-deleted from tab B. Returned in place of the
  // raw setActiveTab so callers keep their existing call signature.
  const switchTab = useCallback((key) => {
    setActiveTab(key);
    setSelectedIds(new Set());
  }, []);

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = (rows) => {
    setSelectedIds((prev) => {
      const allOnPage = rows.map((r) => r.id);
      const everyOneChecked = allOnPage.length > 0 && allOnPage.every((id) => prev.has(id));
      if (everyOneChecked) return new Set();
      return new Set(allOnPage);
    });
  };

  const bulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!window.confirm(
      `Delete ${ids.length} selected item${ids.length === 1 ? "" : "s"}? This cannot be undone.`
    )) return;
    try {
      const r = await axios.post(
        `${API}/uploads/bulk-delete`,
        { upload_ids: ids },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      toast.success(`Deleted ${r.data?.deleted_count ?? ids.length} item(s)`);
      setSelectedIds(new Set());
      await fetchUploads();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Bulk delete failed");
    }
  };

  // Download original Excel/CSV behind the saved upload (data_file
  // type only). Uses fetch+blob so we can pass the Authorization
  // header (a plain <a href=...> can't carry headers). Falls back to
  // the upload's display name if the original filename is gone.
  // 2026-06 — `which` ("original" | "remaining") lets the user grab
  // the auto-maintained pending-leads file (1857 of 1920 etc.) without
  // having to re-upload anything.
  const downloadOne = async (u, which = "original") => {
    try {
      const r = await axios.get(`${API}/uploads/${u.id}/download`, {
        params: { which },
        headers: { Authorization: `Bearer ${token}` },
        responseType: "blob",
      });
      const blob = new Blob([r.data]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const baseName = u.file_name || `${u.name || "data_file"}.xlsx`;
      a.download = which === "remaining"
        ? baseName.replace(/(\.[a-zA-Z0-9]+)?$/, "_remaining$1")
        : which === "used"
          ? baseName.replace(/(\.[a-zA-Z0-9]+)?$/, "_used$1")
          : baseName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      const detail =
        e?.response?.data?.detail ||
        (e?.response?.status === 410
          ? "No remaining-leads file yet — run a job first."
          : null) ||
        "Download failed";
      toast.error(detail);
    }
  };

  const bulkDownload = async (rows) => {
    const ids = rows.filter((r) => selectedIds.has(r.id) && r.type === "data_file" && !r.gsheet_url);
    if (ids.length === 0) {
      toast.info("Select data files (not live-sheet rows) to download");
      return;
    }
    for (const u of ids) {
      await downloadOne(u);
    }
  };

  const filtered = uploads.filter((u) => u.type === activeTab);

  const inputClass = "bg-zinc-800 border-zinc-700 text-zinc-100";

  return (
    <div className="space-y-6" data-testid="uploaded-things-page">
      <div className="flex items-center gap-3">
        <Package size={28} style={{ color: "var(--brand-primary)" }} />
        <div>
          <h2 className="text-2xl font-bold" style={{ color: "var(--brand-text)" }}>
            Uploaded Things
          </h2>
          <p className="text-sm text-zinc-400 mt-1">
            Save reusable batches of user-agents, proxies, and data files — then pick them in any Real User Traffic
            campaign with one click. Used <strong>rows</strong> auto-remove per-job (not the whole batch) so the same
            leads / proxies never get reused. Batches stay visible even when fully consumed (marked
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-1 rounded text-[10px] font-bold align-middle"
              style={{ backgroundColor: "rgba(248, 113, 113, 0.15)", color: "rgb(252, 165, 165)" }}>
              ● DEPLETED
            </span>
            ). Automation-JSON templates are never auto-deleted.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-zinc-800 pb-2">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = activeTab === t.key;
          const count = uploads.filter((u) => u.type === t.key).length;
          return (
            <button
              key={t.key}
              onClick={() => switchTab(t.key)}
              className="px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors"
              style={{
                backgroundColor: active ? "var(--brand-primary)" : "transparent",
                color: active ? "white" : "var(--brand-muted)",
                border: `1px solid ${active ? "var(--brand-primary)" : "var(--brand-border)"}`,
              }}
              data-testid={`ut-tab-${t.key}`}
            >
              <Icon size={16} />
              {t.label}
              <span className="ml-1 text-xs opacity-80">({count})</span>
            </button>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          <span
            className="hidden md:inline text-[11px] text-zinc-500"
            title="Live Google Sheet uploads auto-sync every 30 seconds. Edit your sheet and changes will show up here without re-upload."
            data-testid="ut-autosync-hint"
          >
            ● auto-sync 30s
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchUploads()}
            disabled={loading}
            data-testid="ut-refresh"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            <span className="ml-2">Refresh</span>
          </Button>
        </div>
      </div>

      {/* UA tab */}
      {activeTab === "user_agents" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Add user-agent batch
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">Batch name</Label>
                <Input
                  value={uaName}
                  onChange={(e) => setUaName(e.target.value)}
                  placeholder={uaMode === "gsheet" ? "e.g. Master UA Sheet (Live)" : "e.g. TikTok Android Pixel UAs"}
                  className={inputClass}
                  data-testid="ut-ua-name"
                />
              </div>

              {/* Mode toggle: paste lines vs Google Sheet URL */}
              <div className="flex gap-2 p-1 bg-zinc-950/60 border border-zinc-800 rounded">
                <button
                  type="button"
                  onClick={() => setUaMode("text")}
                  className={`flex-1 text-xs font-medium px-3 py-1.5 rounded transition-colors ${
                    uaMode === "text"
                      ? "bg-indigo-500/30 text-indigo-200"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                  data-testid="ut-ua-mode-text"
                >
                  Paste lines
                </button>
                <button
                  type="button"
                  onClick={() => setUaMode("gsheet")}
                  className={`flex-1 text-xs font-medium px-3 py-1.5 rounded transition-colors ${
                    uaMode === "gsheet"
                      ? "bg-emerald-500/30 text-emerald-200"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                  data-testid="ut-ua-mode-gsheet"
                >
                  Google Sheet URL (live)
                </button>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-zinc-300">OS</Label>
                  <select
                    value={uaOs}
                    onChange={(e) => setUaOs(e.target.value)}
                    className="w-full h-10 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
                    data-testid="ut-ua-os"
                  >
                    {OS_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-zinc-300">Network / App</Label>
                  <select
                    value={uaNetwork}
                    onChange={(e) => setUaNetwork(e.target.value)}
                    className="w-full h-10 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
                    data-testid="ut-ua-network"
                  >
                    {NETWORK_OPTIONS.map((n) => (
                      <option key={n.value} value={n.value}>{n.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              {uaMode === "text" ? (
                <div>
                  <Label className="text-zinc-300">User-agents (one per line)</Label>
                  <Textarea
                    value={uaText}
                    onChange={(e) => setUaText(e.target.value)}
                    placeholder={"Mozilla/5.0 (Linux; Android 12; Pixel 8 Pro) ...\nMozilla/5.0 (Linux; Android 14; Pixel 8) ..."}
                    className={`${inputClass} font-mono text-xs min-h-[180px]`}
                    data-testid="ut-ua-text"
                  />
                </div>
              ) : (
                <div>
                  <GSheetTabPicker
                    token={token}
                    value={uaGSheetUrl}
                    onChange={setUaGSheetUrl}
                    testIdPrefix="ut-ua"
                    inputClass={inputClass}
                  />
                  <div className="mt-2 text-xs text-zinc-400 space-y-1 leading-relaxed">
                    <div>
                      <span className="text-emerald-300 font-semibold">LIVE + auto-skip-after-use:</span>{" "}
                      every job re-fetches the sheet AND auto-filters out
                      UAs that have already been picked, so the same UA
                      never gets used twice across jobs.
                    </div>
                    <div>
                      One UA per row in the FIRST column. Row 1 is treated
                      as a header (e.g., <span className="font-mono text-zinc-200">user_agent</span>).
                      Sheet must be public (Anyone with the link → Viewer)
                      or Published as CSV.
                    </div>
                  </div>
                </div>
              )}
              <Button
                onClick={createUA}
                disabled={uaSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-ua-save"
              >
                {uaSaving
                  ? "Saving..."
                  : uaMode === "gsheet"
                  ? "Link Google Sheet"
                  : "Save batch"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
                Your saved UA batches ({filtered.length})
              </h3>
              {filtered.length > 0 && (
                <BulkActionBar
                  selectedCount={selectedIds.size}
                  totalCount={filtered.length}
                  allChecked={filtered.length > 0 && filtered.every((r) => selectedIds.has(r.id))}
                  onToggleAll={() => toggleSelectAll(filtered)}
                  onBulkDelete={bulkDelete}
                />
              )}
            </div>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No user-agent batches yet. Add your first one on the left.
              </div>
            )}
            {filtered.map((u) => {
              const checked = selectedIds.has(u.id);
              return (
              <Card key={u.id} className={`bg-zinc-900/40 border-zinc-800 ${checked ? "ring-1 ring-indigo-500/60" : ""}`} data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => toggleSelect(u.id)}
                    className="mt-1 text-zinc-400 hover:text-indigo-300 transition"
                    aria-label={checked ? "Unselect row" : "Select row"}
                    data-testid={`ut-check-${u.id}`}
                  >
                    {checked ? <CheckSquare size={18} className="text-indigo-400" /> : <Square size={18} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate flex items-center gap-2">
                      {u.name}
                      {u.gsheet_url && (
                        <span
                          className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: "rgba(16,185,129,0.18)", color: "rgb(110, 231, 183)" }}
                          title="Live Google Sheet — refetched on every job, used items auto-skipped"
                        >
                          ● LIVE
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {u.os_tag && <TagBadge>OS · {u.os_tag}</TagBadge>}
                      {u.network_tag && <TagBadge color="emerald">App · {u.network_tag}</TagBadge>}
                      <TagBadge>
                        {(u.available_count || u.item_count || 0).toLocaleString()} available
                      </TagBadge>
                      {u.consumed_count > 0 && (
                        <TagBadge color="yellow">
                          {u.consumed_count.toLocaleString()} used
                        </TagBadge>
                      )}
                    </div>
                    <GSheetLinkBlock u={u} onSynced={() => fetchUploads({ silent: true })} />
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                    data-testid={`ut-del-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </Button>
                </CardContent>
              </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* Proxy tab */}
      {activeTab === "proxies" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Add proxy batch
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">Batch name</Label>
                <Input
                  value={pxName}
                  onChange={(e) => setPxName(e.target.value)}
                  placeholder="e.g. US Residential Pool 1"
                  className={inputClass}
                  data-testid="ut-px-name"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-zinc-300">Country</Label>
                  <select
                    value={pxCountry}
                    onChange={(e) => setPxCountry(e.target.value)}
                    className="w-full h-10 px-3 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 text-sm"
                    data-testid="ut-px-country"
                  >
                    {COUNTRY_OPTIONS.map((c) => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-zinc-300">State (optional)</Label>
                  <Input
                    value={pxState}
                    onChange={(e) => setPxState(e.target.value.toUpperCase())}
                    placeholder="e.g. CA, NY, TX"
                    maxLength={3}
                    className={inputClass}
                    data-testid="ut-px-state"
                  />
                </div>
              </div>
              {/* Mode toggle: paste lines vs Google Sheet URL */}
              <div className="flex gap-2 p-1 bg-zinc-950/60 border border-zinc-800 rounded">
                <button
                  type="button"
                  onClick={() => setPxMode("text")}
                  className={`flex-1 text-xs font-medium px-3 py-1.5 rounded transition-colors ${
                    pxMode === "text"
                      ? "bg-indigo-500/30 text-indigo-200"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                  data-testid="ut-px-mode-text"
                >
                  Paste lines
                </button>
                <button
                  type="button"
                  onClick={() => setPxMode("gsheet")}
                  className={`flex-1 text-xs font-medium px-3 py-1.5 rounded transition-colors ${
                    pxMode === "gsheet"
                      ? "bg-emerald-500/30 text-emerald-200"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                  data-testid="ut-px-mode-gsheet"
                >
                  Google Sheet URL (live)
                </button>
              </div>
              {pxMode === "text" ? (
                <div>
                  <Label className="text-zinc-300">Proxies (one per line, user:pass@host:port)</Label>
                  <Textarea
                    value={pxText}
                    onChange={(e) => setPxText(e.target.value)}
                    placeholder={"user1:pass1@proxy.example.com:1010\nuser2:pass2@proxy.example.com:1010"}
                    className={`${inputClass} font-mono text-xs min-h-[180px]`}
                    data-testid="ut-px-text"
                  />
                </div>
              ) : (
                <div>
                  <GSheetTabPicker
                    token={token}
                    value={pxGSheetUrl}
                    onChange={setPxGSheetUrl}
                    testIdPrefix="ut-px"
                    inputClass={inputClass}
                  />
                  <div className="mt-2 text-xs text-zinc-400 space-y-1 leading-relaxed">
                    <div>
                      <span className="text-emerald-300 font-semibold">LIVE + auto-skip-after-use:</span>{" "}
                      every job re-fetches the sheet AND auto-filters out
                      proxies that have already been picked, so the same
                      IP never gets used twice.
                    </div>
                    <div>
                      One proxy per row in the FIRST column. Format:{" "}
                      <span className="font-mono text-zinc-200">user:pass@host:port</span>.
                      Sheet must be public (Anyone with the link → Viewer)
                      or Published as CSV.
                    </div>
                  </div>
                </div>
              )}
              <Button
                onClick={createProxy}
                disabled={pxSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-px-save"
              >
                {pxSaving
                  ? "Saving..."
                  : pxMode === "gsheet"
                  ? "Link Google Sheet"
                  : "Save batch"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
                Your saved proxy batches ({filtered.length})
              </h3>
              {filtered.length > 0 && (
                <BulkActionBar
                  selectedCount={selectedIds.size}
                  totalCount={filtered.length}
                  allChecked={filtered.length > 0 && filtered.every((r) => selectedIds.has(r.id))}
                  onToggleAll={() => toggleSelectAll(filtered)}
                  onBulkDelete={bulkDelete}
                />
              )}
            </div>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No proxy batches yet.
              </div>
            )}
            {filtered.map((u) => {
              const checked = selectedIds.has(u.id);
              return (
              <Card key={u.id} className={`bg-zinc-900/40 border-zinc-800 ${checked ? "ring-1 ring-indigo-500/60" : ""}`} data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => toggleSelect(u.id)}
                    className="mt-1 text-zinc-400 hover:text-indigo-300 transition"
                    aria-label={checked ? "Unselect row" : "Select row"}
                    data-testid={`ut-check-${u.id}`}
                  >
                    {checked ? <CheckSquare size={18} className="text-indigo-400" /> : <Square size={18} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate flex items-center gap-2">
                      {u.name}
                      {u.gsheet_url && (
                        <span
                          className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: "rgba(16,185,129,0.18)", color: "rgb(110, 231, 183)" }}
                          title="Live Google Sheet — refetched on every job, used items auto-skipped"
                        >
                          ● LIVE
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {u.country_tag && <TagBadge>{u.country_tag}</TagBadge>}
                      {u.state_tag && <TagBadge color="emerald">State · {u.state_tag}</TagBadge>}
                      <TagBadge>
                        {(u.available_count || u.item_count || 0).toLocaleString()} available
                      </TagBadge>
                      {u.consumed_count > 0 && (
                        <TagBadge color="yellow">
                          {u.consumed_count.toLocaleString()} used
                        </TagBadge>
                      )}
                    </div>
                    <GSheetLinkBlock u={u} onSynced={() => fetchUploads({ silent: true })} />
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                    data-testid={`ut-del-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </Button>
                </CardContent>
              </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* Data file tab */}
      {activeTab === "data_file" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Add data file
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Mode toggle: static file vs live Google Sheet */}
              <div className="flex gap-2 p-1 bg-zinc-950/60 border border-zinc-800 rounded">
                <button
                  type="button"
                  onClick={() => setDfMode("file")}
                  className={`flex-1 text-xs font-medium px-3 py-1.5 rounded transition-colors ${
                    dfMode === "file"
                      ? "bg-indigo-500/30 text-indigo-200"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                  data-testid="ut-df-mode-file"
                >
                  Excel / CSV file
                </button>
                <button
                  type="button"
                  onClick={() => setDfMode("gsheet")}
                  className={`flex-1 text-xs font-medium px-3 py-1.5 rounded transition-colors ${
                    dfMode === "gsheet"
                      ? "bg-emerald-500/30 text-emerald-200"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                  data-testid="ut-df-mode-gsheet"
                >
                  Google Sheet URL (live)
                </button>
              </div>

              <div>
                <Label className="text-zinc-300">File name / label</Label>
                <Input
                  value={dfName}
                  onChange={(e) => setDfName(e.target.value)}
                  placeholder={
                    dfMode === "gsheet"
                      ? "e.g. Master Leads Sheet (Live)"
                      : "e.g. 504 Mixed Leads – Jan"
                  }
                  className={inputClass}
                  data-testid="ut-df-name"
                />
              </div>
              {dfMode === "file" ? (
                <div>
                  <Label className="text-zinc-300">Excel / CSV file</Label>
                  <input
                    id="df-file-input"
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    onChange={(e) => setDfFile(e.target.files?.[0] || null)}
                    className="block w-full text-sm text-zinc-300 mt-2 file:mr-3 file:py-2 file:px-3 file:rounded file:border-0 file:bg-zinc-700 file:text-zinc-100 hover:file:bg-zinc-600"
                    data-testid="ut-df-file"
                  />
                  {dfFile && (
                    <div className="text-xs text-zinc-400 mt-1.5">
                      Selected: <span className="text-zinc-100">{dfFile.name}</span> ({(dfFile.size / 1024).toFixed(1)} KB)
                    </div>
                  )}
                </div>
              ) : (
                <div>
                  <GSheetTabPicker
                    token={token}
                    value={dfGSheetUrl}
                    onChange={setDfGSheetUrl}
                    testIdPrefix="ut-df"
                    inputClass={inputClass}
                  />
                  <div className="mt-2 text-xs text-zinc-400 space-y-1 leading-relaxed">
                    <div>
                      <span className="text-emerald-300 font-semibold">LIVE mode:</span>{" "}
                      every job auto-fetches the latest rows — edit the sheet
                      anytime, no re-upload ever needed. Used rows are
                      automatically deleted from the sheet after each
                      successful submission.
                    </div>
                    <div>
                      First-row headers must include columns like{" "}
                      <span className="text-zinc-200 font-mono">first</span>,{" "}
                      <span className="text-zinc-200 font-mono">last</span>,{" "}
                      <span className="text-zinc-200 font-mono">email</span>,{" "}
                      <span className="text-zinc-200 font-mono">state</span>,{" "}
                      <span className="text-zinc-200 font-mono">zip</span>, etc.
                    </div>
                  </div>
                </div>
              )}
              <Button
                onClick={createDF}
                disabled={dfSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-df-save"
              >
                {dfSaving
                  ? "Saving..."
                  : dfMode === "gsheet"
                  ? "Link Google Sheet"
                  : "Save file"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
                Your saved data files ({filtered.length})
              </h3>
              {filtered.length > 0 && (
                <BulkActionBar
                  selectedCount={selectedIds.size}
                  totalCount={filtered.length}
                  allChecked={filtered.length > 0 && filtered.every((r) => selectedIds.has(r.id))}
                  onToggleAll={() => toggleSelectAll(filtered)}
                  onBulkDelete={bulkDelete}
                  onBulkDownload={() => bulkDownload(filtered)}
                  showDownload
                />
              )}
            </div>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No data files yet.
              </div>
            )}
            {filtered.map((u) => {
              const checked = selectedIds.has(u.id);
              const original = Number(u?.original_item_count ?? ((u?.available_count ?? u?.item_count ?? 0) + (u?.consumed_count ?? 0)));
              const canDownload = u.type === "data_file" && !u.gsheet_url;
              return (
              <Card key={u.id} className={`bg-zinc-900/40 border-zinc-800 ${checked ? "ring-1 ring-indigo-500/60" : ""}`} data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => toggleSelect(u.id)}
                    className="mt-1 text-zinc-400 hover:text-indigo-300 transition"
                    aria-label={checked ? "Unselect row" : "Select row"}
                    data-testid={`ut-check-${u.id}`}
                  >
                    {checked ? <CheckSquare size={18} className="text-indigo-400" /> : <Square size={18} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate flex items-center gap-2">
                      {u.name}
                      {u.gsheet_url && (
                        <span
                          className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: "rgba(16,185,129,0.18)", color: "rgb(110, 231, 183)" }}
                          data-testid={`ut-item-${u.id}-live-badge`}
                          title="Live Google Sheet — refetched on every job"
                        >
                          ● LIVE
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {u.file_name && <TagBadge>{u.file_name}</TagBadge>}
                      {original > 0 && (
                        <TagBadge color="blue">
                          {original.toLocaleString()} original
                        </TagBadge>
                      )}
                      <TagBadge color="emerald">
                        {(u.available_count || u.item_count || 0).toLocaleString()} available
                      </TagBadge>
                      {u.consumed_count > 0 && (
                        <TagBadge color="yellow">
                          {u.consumed_count.toLocaleString()} used
                        </TagBadge>
                      )}
                    </div>
                    <GSheetLinkBlock u={u} onSynced={() => fetchUploads({ silent: true })} />
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    {canDownload && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => downloadOne(u)}
                        className="text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/20"
                        data-testid={`ut-dl-${u.id}`}
                        title="Download ORIGINAL master file (all rows, untouched)"
                      >
                        <Download size={16} />
                      </Button>
                    )}
                    {canDownload && u.has_remaining_file && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => downloadOne(u, "remaining")}
                        className="text-amber-400 hover:text-amber-300 hover:bg-amber-900/20"
                        data-testid={`ut-dl-remaining-${u.id}`}
                        title={`Download REMAINING leads (${u.available_count} of ${u.original_item_count} unused)`}
                      >
                        <Download size={16} />
                      </Button>
                    )}
                    {canDownload && u.has_used_file && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => downloadOne(u, "used")}
                        className="text-violet-400 hover:text-violet-300 hover:bg-violet-900/20"
                        data-testid={`ut-dl-used-${u.id}`}
                        title={`Download USED leads sheet (${u.consumed_count || 0} consumed rows)`}
                      >
                        <Download size={16} />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => deleteUpload(u.id, u.name)}
                      className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                      data-testid={`ut-del-${u.id}`}
                    >
                      <Trash2 size={16} />
                    </Button>
                  </div>
                </CardContent>
              </Card>
              );
            })}
          </div>
        </div>
      )}
      {/* Automation JSON tab */}
      {activeTab === "automation_json" && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-zinc-900/40 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2 text-zinc-100">
                <Plus size={16} /> Save an automation template
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="text-zinc-300">Template name</Label>
                <Input
                  value={ajName}
                  onChange={(e) => setAjName(e.target.value)}
                  placeholder="e.g. Stimulus $750 Form Template"
                  className={inputClass}
                  data-testid="ut-aj-name"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Description (optional)</Label>
                <Input
                  value={ajDesc}
                  onChange={(e) => setAjDesc(e.target.value)}
                  placeholder="e.g. apptrk.addtitans.in → stimulusassistforall → thnkspg"
                  className={inputClass}
                  data-testid="ut-aj-desc"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Automation JSON (step-list array)</Label>
                <Textarea
                  value={ajJson}
                  onChange={(e) => setAjJson(e.target.value)}
                  placeholder={`[\n  { "action": "wait_for_load", "timeout": 30000 },\n  { "action": "fill", "selector": "input[name='first']", "value": "{{first}}" },\n  ...\n]`}
                  className={`${inputClass} font-mono text-xs min-h-[260px]`}
                  data-testid="ut-aj-json"
                />
              </div>
              <div className="p-2 rounded bg-emerald-950/30 border border-emerald-900/50 text-xs text-emerald-300">
                <strong>Reusable</strong> — unlike data/proxy/UA batches, automation templates are <em>not</em>
                auto-deleted after use. Save once, pick from the RUT page every time.
              </div>
              <Button
                onClick={createAJ}
                disabled={ajSaving}
                className="w-full"
                style={{ backgroundColor: "var(--brand-primary)" }}
                data-testid="ut-aj-save"
              >
                {ajSaving ? "Saving..." : "Save template"}
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide">
                Your saved automation templates ({filtered.length})
              </h3>
              {filtered.length > 0 && (
                <BulkActionBar
                  selectedCount={selectedIds.size}
                  totalCount={filtered.length}
                  allChecked={filtered.length > 0 && filtered.every((r) => selectedIds.has(r.id))}
                  onToggleAll={() => toggleSelectAll(filtered)}
                  onBulkDelete={bulkDelete}
                />
              )}
            </div>
            {filtered.length === 0 && (
              <div className="text-sm text-zinc-500 p-8 text-center border border-dashed border-zinc-800 rounded-lg">
                No automation templates yet. Save your first one on the left.
              </div>
            )}
            {filtered.map((u) => {
              const checked = selectedIds.has(u.id);
              return (
              <Card key={u.id} className={`bg-zinc-900/40 border-zinc-800 ${checked ? "ring-1 ring-indigo-500/60" : ""}`} data-testid={`ut-item-${u.id}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => toggleSelect(u.id)}
                    className="mt-1 text-zinc-400 hover:text-indigo-300 transition"
                    aria-label={checked ? "Unselect row" : "Select row"}
                    data-testid={`ut-check-${u.id}`}
                  >
                    {checked ? <CheckSquare size={18} className="text-indigo-400" /> : <Square size={18} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-zinc-100 truncate">{u.name}</div>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      <TagBadge color="emerald">{u.item_count} steps</TagBadge>
                      <TagBadge>Reusable</TagBadge>
                    </div>
                    {u.automation_json && (
                      <details className="mt-2">
                        <summary className="text-xs text-indigo-400 cursor-pointer">Preview JSON</summary>
                        <pre className="text-xs text-zinc-400 bg-zinc-950/70 p-2 rounded mt-1 overflow-x-auto max-h-48">
                          {u.automation_json.slice(0, 600)}{u.automation_json.length > 600 ? "…" : ""}
                        </pre>
                      </details>
                    )}
                    <div className="text-xs text-zinc-500 mt-1">
                      {new Date(u.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => navigate(`/visual-recorder?edit_upload_id=${u.id}`)}
                      className="text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/20"
                      title="Open in Visual Recorder — edit with full features (re-record, reorder, fix selectors live)"
                      data-testid={`ut-recorder-edit-${u.id}`}
                    >
                      <Camera size={16} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => openEditAJ(u)}
                      className="text-indigo-400 hover:text-indigo-300 hover:bg-indigo-900/20"
                      title="Quick edit raw JSON (name / description / step text)"
                      data-testid={`ut-edit-${u.id}`}
                    >
                      <Pencil size={16} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => deleteUpload(u.id, u.name)}
                      className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                      title="Delete this template"
                      data-testid={`ut-del-${u.id}`}
                    >
                      <Trash2 size={16} />
                    </Button>
                  </div>
                </CardContent>
              </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* ─── Edit Automation-JSON Template modal ───────────────────────
           Opens when user clicks the pencil icon on a saved automation
           template. Lets them rename / re-describe / edit the full step
           list in-place. The upload_id is preserved so any RUT campaign
           preset that already references this template keeps working. */}
      <Dialog open={!!editAJ} onOpenChange={(open) => { if (!open) setEditAJ(null); }}>
        <DialogContent
          className="max-w-3xl w-full bg-zinc-900 border-zinc-800 max-h-[90vh] overflow-y-auto"
          data-testid="ut-aj-edit-dialog"
        >
          <DialogHeader>
            <DialogTitle className="text-zinc-100 flex items-center gap-2">
              <Pencil size={16} className="text-indigo-400" /> Edit automation template
            </DialogTitle>
            <DialogDescription className="text-zinc-400 text-xs">
              Add / remove / fix steps without losing the upload ID — every campaign that already
              references this template will keep working after you save.
            </DialogDescription>
          </DialogHeader>
          {editAJ && (
            <div className="space-y-3 mt-2">
              <div>
                <Label className="text-zinc-300">Template name</Label>
                <Input
                  value={editAJ.name}
                  onChange={(e) => setEditAJ({ ...editAJ, name: e.target.value })}
                  className={inputClass}
                  data-testid="ut-aj-edit-name"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Description (optional)</Label>
                <Input
                  value={editAJ.description}
                  onChange={(e) => setEditAJ({ ...editAJ, description: e.target.value })}
                  className={inputClass}
                  data-testid="ut-aj-edit-desc"
                />
              </div>
              <div>
                <Label className="text-zinc-300">Automation JSON (step-list array)</Label>
                <Textarea
                  value={editAJ.automation_json}
                  onChange={(e) => setEditAJ({ ...editAJ, automation_json: e.target.value })}
                  className={`${inputClass} font-mono text-xs min-h-[360px]`}
                  data-testid="ut-aj-edit-json"
                />
                <div className="text-xs text-zinc-500 mt-1">
                  Valid JSON only. Step count is recomputed on save.
                </div>
              </div>
            </div>
          )}
          <DialogFooter className="gap-2 mt-3">
            <Button
              variant="outline"
              onClick={() => setEditAJ(null)}
              disabled={editAJSaving}
              data-testid="ut-aj-edit-cancel"
            >
              Cancel
            </Button>
            <Button
              onClick={saveEditAJ}
              disabled={editAJSaving}
              style={{ backgroundColor: "var(--brand-primary)" }}
              data-testid="ut-aj-edit-save"
            >
              {editAJSaving ? "Saving..." : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
