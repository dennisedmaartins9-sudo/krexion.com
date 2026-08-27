import { useEffect, useState } from "react";
import axios from "axios";
import { Trash2, Smartphone, Apple, AlertCircle, ExternalLink, Download, Zap, Cloud } from "lucide-react";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { toast } from "sonner";
import useVisibleInterval from "../hooks/useVisibleInterval";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const dot = (s) => ({
  online: "bg-green-500",
  busy: "bg-yellow-500",
  offline: "bg-gray-400",
  error: "bg-red-500",
  needs_attention: "bg-amber-500",
}[s] || "bg-gray-400");

export default function CPIDevicesPage() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState("");
  const [androidStatus, setAndroidStatus] = useState(null);
  const [enabling, setEnabling] = useState(false);
  const [farmSize, setFarmSize] = useState(1);
  const [apkLibrary, setApkLibrary] = useState([]);
  const [cloudForm, setCloudForm] = useState({ open: false, label: "Krexion Cloud Android", adb: "" });
  const [provisionBusy, setProvisionBusy] = useState(false);

  const token = localStorage.getItem("token");
  const auth = { headers: { Authorization: `Bearer ${token}` } };

  const load = async () => {
    try {
      const [r, s, lib] = await Promise.all([
        axios.get(`${API}/cpi/devices`, auth),
        axios.get(`${API}/cpi/android/status`, auth).catch(() => ({ data: null })),
        axios.get(`${API}/cpi/apk-library`, auth).catch(() => ({ data: { items: [] } })),
      ]);
      setDevices(r.data || []);
      setAndroidStatus(s.data || null);
      setApkLibrary(lib.data?.items || []);
      if (s.data?.farm_target) setFarmSize(Number(s.data.farm_target) || 1);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load devices");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);
  useVisibleInterval(load, 5000);

  const enableKrexionAndroid = async (n) => {
    const instances = Math.max(1, Math.min(8, Number(n || farmSize) || 1));
    setEnabling(true);
    try {
      const r = await axios.post(`${API}/cpi/android/enable`, { instances }, auth);
      toast.success(r.data?.message || "Krexion Android starting…");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not enable Krexion Android");
    } finally {
      setEnabling(false);
    }
  };

  const provisionCloud = async () => {
    const ep = (cloudForm.adb || "").trim();
    if (!ep || !ep.includes(":")) {
      toast.error("Enter host:port for Krexion Cloud Android");
      return;
    }
    setProvisionBusy(true);
    try {
      const r = await axios.post(
        `${API}/cpi/cloud-phone/provision`,
        { label: cloudForm.label || "Krexion Cloud Android", adb_endpoint: ep },
        auth,
      );
      toast.success(r.data?.message || "Cloud Android registered");
      setCloudForm({ open: false, label: "Krexion Cloud Android", adb: "" });
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Provision failed");
    } finally {
      setProvisionBusy(false);
    }
  };

  const onDelete = async (id) => {
    if (!window.confirm("Remove this Krexion device?")) return;
    try {
      await axios.delete(`${API}/cpi/devices/${id}`, auth);
      toast.success("Device removed");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  const queueAction = async (id, type, preset) => {
    let payload = { type };
    if (type === "open_url") {
      const url = window.prompt("URL to open in Krexion Android", "https://www.google.com/");
      if (!url) return;
      payload.url = url;
    } else {
      let apk = preset?.apk_url || "";
      if (!apk) {
        const recent = (apkLibrary[0] && apkLibrary[0].apk_url) || "https://";
        apk = window.prompt(
          apkLibrary.length
            ? `APK URL (recent: ${apkLibrary[0].label || recent})\nOr paste a new URL`
            : "APK URL to install on Krexion Android",
          recent,
        );
      }
      if (!apk || !apk.startsWith("http")) return;
      payload.apk_url = apk;
      const pkg = preset?.package_name
        || window.prompt("Package name (optional)", "")
        || "";
      if (pkg) payload.package_name = pkg;
    }
    setActionBusy(`${id}-${type}`);
    try {
      await axios.post(`${API}/cpi/devices/${id}/action`, payload, auth);
      toast.success("Queued on Krexion Android");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Action failed");
    } finally {
      setActionBusy("");
    }
  };

  const isIos = (t) => t === "ios_real";
  const friendlyType = (t) => {
    if (!t) return "Krexion";
    if (t === "android_krexion" || (t || "").includes("emulator") || (t || "").includes("ldplayer")
      || (t || "").includes("genymotion") || (t || "").includes("bluestacks")) {
      return "Krexion Android";
    }
    if (t === "android_cloud") return "Krexion Cloud Android";
    if (t === "android_real") return "Krexion Android (device)";
    if (t === "ios_real") return "Krexion iOS";
    return "Krexion Android";
  };
  const successRate = (d) => d.total_installs ? Math.round(((d.successful_installs || 0) / d.total_installs) * 100) : 0;
  const ready = !!(androidStatus && androidStatus.ready);

  return (
    <div className="space-y-6" data-testid="cpi-devices-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Krexion Android</h1>
          <p className="text-sm text-muted-foreground">
            Real Android apps on a silent phone farm — Enable, Browse, Install. No third-party emulators.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="h-8 text-xs border rounded px-2 bg-background"
            value={farmSize}
            onChange={(e) => setFarmSize(Number(e.target.value) || 1)}
            data-testid="cpi-farm-size"
            title="Farm size"
          >
            {[1, 2, 3, 4, 5, 6, 8].map((n) => (
              <option key={n} value={n}>{n} phone{n > 1 ? "s" : ""}</option>
            ))}
          </select>
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
            disabled={enabling}
            onClick={() => enableKrexionAndroid(farmSize)}
            data-testid="cpi-enable-krexion-android"
          >
            <Zap className="h-4 w-4 mr-1" />
            {enabling ? "Starting…" : ready ? "Restart farm" : "Enable Krexion Android"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setCloudForm({ ...cloudForm, open: true })}
            data-testid="cpi-add-cloud-android"
          >
            <Cloud className="h-4 w-4 mr-1" /> Add Cloud Android
          </Button>
        </div>
      </div>

      <div className="border rounded-lg p-4 bg-emerald-500/5 border-emerald-500/30 space-y-1" data-testid="cpi-android-status">
        <div className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
          {ready ? "Krexion Android farm ready" : "Krexion Android Engine"}
        </div>
        <div className="text-xs text-muted-foreground">
          {androidStatus?.message || "Click Enable — Krexion prepares Android automatically on your PC worker."}
          {androidStatus?.online_count != null ? ` · ${androidStatus.online_count} online` : ""}
          {androidStatus?.farm_target ? ` · target ${androidStatus.farm_target}` : ""}
        </div>
      </div>

      {apkLibrary.length > 0 && (
        <div className="border rounded-lg p-3 space-y-2" data-testid="cpi-apk-library">
          <div className="text-xs font-medium text-muted-foreground">Recent APKs</div>
          <div className="flex flex-wrap gap-2">
            {apkLibrary.slice(0, 8).map((item) => (
              <Badge
                key={item.id}
                variant="outline"
                className="cursor-pointer text-[10px] max-w-[220px] truncate"
                title={item.apk_url}
                onClick={() => {
                  const online = devices.find((d) => d.status === "online" || d.status === "busy");
                  if (!online) {
                    toast.error("No online Krexion Android — Enable farm first");
                    return;
                  }
                  queueAction(online.id, "install_apk", item);
                }}
              >
                {item.label || item.apk_url}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {cloudForm.open && (
        <div className="border rounded-lg p-4 space-y-3" data-testid="cpi-cloud-provision-form">
          <div className="text-sm font-medium">Add Krexion Cloud Android</div>
          <Input
            value={cloudForm.label}
            onChange={(e) => setCloudForm({ ...cloudForm, label: e.target.value })}
            placeholder="Label"
            className="h-8 text-xs"
          />
          <Input
            value={cloudForm.adb}
            onChange={(e) => setCloudForm({ ...cloudForm, adb: e.target.value })}
            placeholder="host:port (ADB tunnel)"
            className="h-8 text-xs"
            data-testid="cpi-cloud-adb-endpoint"
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={provisionBusy} onClick={provisionCloud} data-testid="cpi-cloud-provision-save">
              {provisionBusy ? "Saving…" : "Register"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCloudForm({ ...cloudForm, open: false })}>Cancel</Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : devices.length === 0 ? (
        <div className="border rounded-lg p-8 text-center space-y-3">
          <Smartphone className="h-10 w-10 mx-auto text-muted-foreground" />
          <div className="text-sm font-medium">No Krexion Android yet</div>
          <div className="text-xs text-muted-foreground max-w-md mx-auto">
            Keep Krexion CPI Worker running on your PC, pick farm size, then click <strong>Enable Krexion Android</strong>.
            Or add a Cloud Android ADB endpoint.
          </div>
          <Button size="sm" onClick={() => enableKrexionAndroid(farmSize)} disabled={enabling} data-testid="cpi-enable-krexion-android-empty">
            Enable Krexion Android
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((d) => (
            <div key={d.id} className="border rounded-lg p-4 space-y-3" data-testid={`cpi-device-card-${d.id}`}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  {isIos(d.device_type) ? <Apple className="h-5 w-5" /> : <Smartphone className="h-5 w-5" />}
                  <div>
                    <div className="font-medium">{d.label || friendlyType(d.device_type)}</div>
                    <div className="text-xs text-muted-foreground">{d.model || friendlyType(d.device_type)}</div>
                  </div>
                </div>
                <span className={`h-2 w-2 rounded-full ${dot(d.status)}`} title={d.status}></span>
              </div>
              <div className="flex flex-wrap gap-1.5 text-xs">
                <Badge variant="outline">{friendlyType(d.device_type)}</Badge>
                {d.os_version && <Badge variant="outline">{d.os_version}</Badge>}
                <Badge variant={d.status === "online" ? "default" : "secondary"}>{d.status}</Badge>
              </div>
              {d.needs_action && (
                <div className="text-xs text-amber-500 flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" />
                  {typeof d.needs_action === "object"
                    ? `${d.needs_action.type || "action"} queued`
                    : String(d.needs_action)}
                </div>
              )}
              <div className="grid grid-cols-3 gap-2 text-xs pt-2 border-t">
                <div>
                  <div className="text-muted-foreground">Installs</div>
                  <div className="font-medium">{d.total_installs || 0}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Success</div>
                  <div className="font-medium">{d.successful_installs || 0}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Rate</div>
                  <div className="font-medium">{successRate(d)}%</div>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 pt-1">
                <Button size="sm" variant="outline" className="h-7 text-xs"
                  disabled={!!actionBusy || d.status === "offline"}
                  onClick={() => queueAction(d.id, "open_url")}
                  data-testid={`cpi-device-open-${d.id}`}>
                  <ExternalLink className="h-3 w-3 mr-1" /> Browse
                </Button>
                <Button size="sm" variant="outline" className="h-7 text-xs"
                  disabled={!!actionBusy || d.status === "offline"}
                  onClick={() => queueAction(d.id, "install_apk")}
                  data-testid={`cpi-device-install-${d.id}`}>
                  <Download className="h-3 w-3 mr-1" /> Install APK
                </Button>
                <Button size="sm" variant="ghost" className="h-7 ml-auto"
                  onClick={() => onDelete(d.id)} data-testid={`cpi-device-delete-${d.id}`}>
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
