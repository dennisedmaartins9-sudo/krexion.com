import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { toast } from "sonner";
import { format } from "date-fns";
import { 
  User, Lock, Users, Plus, Trash2, Edit2, 
  Eye, EyeOff, Shield, CheckCircle, XCircle,
  Clock, Save, BarChart3, Link2, MousePointerClick, Server, Bell
} from "lucide-react";
import FraudDetectionTab from "./FraudDetectionTab";
import ProxyProvidersTab from "./ProxyProvidersTab";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// ── 2026-01: Full sub-user permission catalogue ─────────────────────
// Mirrors backend's `SUB_USER_PERMISSION_MAP` so the main user can
// grant a sub-user the SAME breadth of access an admin can grant a
// main user. `parentFeatKey` is the feature key on the PARENT user
// that must be ON for the permission to take effect — backend caps
// the effective feature to (granted AND parent_has), and the UI
// disables toggles for capabilities the parent doesn't own so the
// main user gets immediate visual feedback.
const ALL_SUB_USER_PERMISSIONS = [
  { key: "view_links",        label: "View Links",         parentFeatKey: "links" },
  { key: "view_clicks",       label: "View Clicks",        parentFeatKey: "clicks" },
  { key: "view_conversions",  label: "View Conversions",   parentFeatKey: "conversions" },
  { key: "view_proxies",      label: "View Proxies",       parentFeatKey: "proxies" },
  { key: "import_data",       label: "Import Data",        parentFeatKey: "import_data" },
  { key: "import_traffic",    label: "Import Traffic",     parentFeatKey: "import_traffic" },
  { key: "real_traffic",      label: "Real Traffic",       parentFeatKey: "real_traffic" },
  { key: "ua_generator",      label: "UA Generator",       parentFeatKey: "ua_generator" },
  { key: "ua_checker",        label: "UA Checker",         parentFeatKey: "ua_checker" },
  { key: "email_checker",     label: "Email Checker",      parentFeatKey: "email_checker" },
  { key: "separate_data",     label: "Separate Data",      parentFeatKey: "separate_data" },
  { key: "form_filler",       label: "Form Filler",        parentFeatKey: "form_filler" },
  { key: "real_user_traffic", label: "Real User Traffic",  parentFeatKey: "real_user_traffic" },
  { key: "profile_builder",   label: "Profile Builder",    parentFeatKey: "profile_builder" },
  { key: "settings",          label: "Settings Access",    parentFeatKey: "settings" },
];

export default function SettingsPage() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [subUsers, setSubUsers] = useState([]);
  const [subUserStats, setSubUserStats] = useState([]);
  
  // Profile form
  const [name, setName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  
  // Sub-user form
  const [subUserDialogOpen, setSubUserDialogOpen] = useState(false);
  const [editingSubUser, setEditingSubUser] = useState(null);
  const [subUserForm, setSubUserForm] = useState({
    email: "",
    name: "",
    password: "",
    permissions: {
      view_clicks: true,
      view_links: true,
      view_proxies: false,
      edit: false
    }
  });

  // ── AI Vision settings (Gemini / OpenAI / Claude / Emergent — 2026-06) ──
  const [aiProvider, setAiProvider] = useState("gemini"); // 'gemini' | 'openai' | 'claude' | 'emergent'
  const [aiKey, setAiKey] = useState("");
  const [aiGemini, setAiGemini] = useState({ has_key: false, key_preview: "" });
  const [aiOpenai, setAiOpenai] = useState({ has_key: false, key_preview: "" });
  const [aiClaude, setAiClaude] = useState({ has_key: false, key_preview: "" });
  const [aiEmergent, setAiEmergent] = useState({ has_key: false, key_preview: "", available: false, platform_fallback: false });
  const [aiSaving, setAiSaving] = useState(false);

  // ── Notification settings (low-stock email alerts) ──
  const [notifEmail, setNotifEmail] = useState("");
  const [notifPrimaryEmail, setNotifPrimaryEmail] = useState("");
  const [notifAlertsEnabled, setNotifAlertsEnabled] = useState(true);
  const [notifThreshold, setNotifThreshold] = useState(10);
  const [notifSaving, setNotifSaving] = useState(false);

  useEffect(() => {
    fetchUserData();
    fetchSubUsers();
    fetchSubUserStats();
    fetchAiSettings();
    fetchNotifSettings();
  }, []);

  const getToken = () => localStorage.getItem("token");

  const fetchUserData = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setUser(response.data);
      setName(response.data.name);
    } catch (error) {
      toast.error("Failed to fetch user data");
    } finally {
      setLoading(false);
    }
  };

  const fetchSubUsers = async () => {
    try {
      const response = await axios.get(`${API}/sub-users`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setSubUsers(response.data);
    } catch (error) {
      // Sub-users feature might not be available
      console.error("Failed to fetch sub-users");
    }
  };

  const fetchSubUserStats = async () => {
    try {
      const response = await axios.get(`${API}/sub-users/stats`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setSubUserStats(response.data.sub_users || []);
    } catch (error) {
      // Sub-user stats might not be available
      console.error("Failed to fetch sub-user stats");
    }
  };

  const fetchAiSettings = async () => {
    try {
      const r = await axios.get(`${API}/ai-settings`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      setAiProvider(r.data?.provider || "gemini");
      setAiGemini(r.data?.gemini || { has_key: false, key_preview: "" });
      setAiOpenai(r.data?.openai || { has_key: false, key_preview: "" });
      setAiClaude(r.data?.claude || { has_key: false, key_preview: "" });
      setAiEmergent(r.data?.emergent || { has_key: false, key_preview: "", available: false, platform_fallback: false });
    } catch (e) {
      // ignore
    }
  };

  const fetchNotifSettings = async () => {
    try {
      const r = await axios.get(`${API}/user/notification-settings`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      setNotifPrimaryEmail(r.data?.primary_email || "");
      setNotifEmail(r.data?.notification_email || "");
      setNotifAlertsEnabled(!!r.data?.low_stock_alerts_enabled);
      setNotifThreshold(Number(r.data?.threshold_percent || 10));
    } catch (e) {
      // ignore
    }
  };

  const handleSaveNotifSettings = async () => {
    setNotifSaving(true);
    try {
      await axios.put(
        `${API}/user/notification-settings`,
        {
          notification_email: notifEmail.trim(),
          low_stock_alerts_enabled: notifAlertsEnabled,
        },
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      toast.success("Notification settings saved");
      await fetchNotifSettings();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to save");
    } finally {
      setNotifSaving(false);
    }
  };

  const handleSaveAiKey = async () => {
    setAiSaving(true);
    try {
      const payload = { ai_provider: aiProvider };
      if (aiProvider === "gemini") payload.gemini_api_key = aiKey;
      else if (aiProvider === "openai") payload.openai_api_key = aiKey;
      else if (aiProvider === "claude") payload.anthropic_api_key = aiKey;
      else if (aiProvider === "emergent") payload.emergent_api_key = aiKey;
      await axios.put(`${API}/ai-settings`, payload, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      toast.success("AI settings saved");
      setAiKey("");
      await fetchAiSettings();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to save AI key");
    } finally {
      setAiSaving(false);
    }
  };

  const handleClearAiKey = async (which) => {
    try {
      let payload = {};
      if (which === "gemini") payload = { gemini_api_key: "" };
      else if (which === "openai") payload = { openai_api_key: "" };
      else if (which === "claude") payload = { anthropic_api_key: "" };
      else if (which === "emergent") payload = { emergent_api_key: "" };
      await axios.put(`${API}/ai-settings`, payload, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      const labels = { gemini: "Gemini", openai: "OpenAI", claude: "Claude", emergent: "Krexion Universal" };
      toast.success(`${labels[which] || which} key cleared`);
      await fetchAiSettings();
    } catch (e) {
      toast.error("Failed to clear key");
    }
  };

  const handleProviderChange = async (newProvider) => {
    setAiProvider(newProvider);
    try {
      await axios.put(
        `${API}/ai-settings`,
        { ai_provider: newProvider },
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
    } catch (e) {
      // silent
    }
  };

  const handleUpdateProfile = async (e) => {
    e.preventDefault();
    
    if (newPassword && newPassword !== confirmPassword) {
      toast.error("New passwords do not match");
      return;
    }
    
    if (newPassword && newPassword.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }
    
    setSaving(true);
    try {
      const updateData = { name };
      if (newPassword) {
        updateData.current_password = currentPassword;
        updateData.new_password = newPassword;
      }
      
      await axios.put(`${API}/auth/profile`, updateData, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      
      toast.success("Profile updated successfully");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      fetchUserData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update profile");
    } finally {
      setSaving(false);
    }
  };

  const handleCreateSubUser = async (e) => {
    e.preventDefault();
    
    if (!subUserForm.email || !subUserForm.name) {
      toast.error("Email and name are required");
      return;
    }
    
    if (!editingSubUser && !subUserForm.password) {
      toast.error("Password is required for new sub-user");
      return;
    }
    
    try {
      if (editingSubUser) {
        const updateData = {
          name: subUserForm.name,
          permissions: subUserForm.permissions
        };
        if (subUserForm.password) {
          updateData.password = subUserForm.password;
        }
        
        await axios.put(`${API}/sub-users/${editingSubUser.id}`, updateData, {
          headers: { Authorization: `Bearer ${getToken()}` }
        });
        toast.success("Sub-user updated");
      } else {
        await axios.post(`${API}/sub-users`, subUserForm, {
          headers: { Authorization: `Bearer ${getToken()}` }
        });
        toast.success("Sub-user created");
      }
      
      setSubUserDialogOpen(false);
      setEditingSubUser(null);
      setSubUserForm({
        email: "",
        name: "",
        password: "",
        permissions: { view_clicks: true, view_links: true, view_proxies: false, edit: false }
      });
      fetchSubUsers();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Operation failed");
    }
  };

  const handleDeleteSubUser = async (id, name) => {
    if (!window.confirm(`Delete sub-user "${name}"? This cannot be undone.`)) return;
    
    try {
      await axios.delete(`${API}/sub-users/${id}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      toast.success("Sub-user deleted");
      fetchSubUsers();
    } catch (error) {
      toast.error("Failed to delete sub-user");
    }
  };

  const handleToggleSubUserActive = async (subUser) => {
    try {
      await axios.put(`${API}/sub-users/${subUser.id}`, {
        is_active: !subUser.is_active
      }, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      toast.success(`Sub-user ${subUser.is_active ? 'deactivated' : 'activated'}`);
      fetchSubUsers();
    } catch (error) {
      toast.error("Failed to update sub-user");
    }
  };

  const openEditSubUser = (subUser) => {
    setEditingSubUser(subUser);
    setSubUserForm({
      email: subUser.email,
      name: subUser.name,
      password: "",
      permissions: subUser.permissions || { view_clicks: true, view_links: true, view_proxies: false, edit: false }
    });
    setSubUserDialogOpen(true);
  };

  const openCreateSubUser = () => {
    setEditingSubUser(null);
    setSubUserForm({
      email: "",
      name: "",
      password: "",
      permissions: { view_clicks: true, view_links: true, view_proxies: false, edit: false }
    });
    setSubUserDialogOpen(true);
  };

  if (loading) {
    return <div className="text-muted-foreground">Loading settings...</div>;
  }

  return (
    <div className="space-y-6" data-testid="settings-page">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Settings</h2>
      </div>

      <Tabs defaultValue="profile" className="space-y-6">
        <TabsList className="bg-[var(--brand-card)] border border-[var(--brand-border)]">
          <TabsTrigger value="profile" className="data-[state=active]:bg-[#27272A]" data-testid="tab-profile">
            <User size={16} className="mr-2" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="subusers" className="data-[state=active]:bg-[#27272A]" data-testid="tab-subusers">
            <Users size={16} className="mr-2" />
            Sub-Users
            {subUsers.length > 0 && (
              <Badge className="ml-2 bg-[#3B82F6]">{subUsers.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="subscription" className="data-[state=active]:bg-[#27272A]" data-testid="tab-subscription">
            <Shield size={16} className="mr-2" />
            Subscription
          </TabsTrigger>
          <TabsTrigger value="notifications" className="data-[state=active]:bg-[#27272A]" data-testid="tab-notifications">
            <Bell size={16} className="mr-2" />
            Notifications
          </TabsTrigger>
          <TabsTrigger value="fraud" className="data-[state=active]:bg-[#27272A]" data-testid="tab-fraud">
            <Shield size={16} className="mr-2" />
            Fraud Detection
          </TabsTrigger>
          <TabsTrigger value="proxy-providers" className="data-[state=active]:bg-[#27272A]" data-testid="tab-proxy-providers">
            <Server size={16} className="mr-2" />
            Proxy Providers
          </TabsTrigger>
        </TabsList>

        {/* Profile Tab */}
        <TabsContent value="profile" className="space-y-6">
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User size={20} />
                Profile Information
              </CardTitle>
              <CardDescription>Update your profile details and password</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleUpdateProfile} className="space-y-6">
                {/* Account Info */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Email</Label>
                    <Input
                      value={user?.email || ""}
                      disabled
                      className="bg-[var(--brand-card)] border-[var(--brand-border)] opacity-60"
                    />
                    <p className="text-xs text-muted-foreground">Contact admin to change email</p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="name">Display Name</Label>
                    <Input
                      id="name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                      data-testid="profile-name-input"
                    />
                  </div>
                </div>

                {/* Password Change */}
                <div className="border-t border-[var(--brand-border)] pt-6">
                  <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <Lock size={18} />
                    Change Password
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="current-password">Current Password</Label>
                      <div className="relative">
                        <Input
                          id="current-password"
                          type={showCurrentPassword ? "text" : "password"}
                          value={currentPassword}
                          onChange={(e) => setCurrentPassword(e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] pr-10"
                          data-testid="current-password-input"
                        />
                        <button
                          type="button"
                          onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                        >
                          {showCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="new-password">New Password</Label>
                      <div className="relative">
                        <Input
                          id="new-password"
                          type={showNewPassword ? "text" : "password"}
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] pr-10"
                          data-testid="new-password-input"
                        />
                        <button
                          type="button"
                          onClick={() => setShowNewPassword(!showNewPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                        >
                          {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="confirm-password">Confirm Password</Label>
                      <Input
                        id="confirm-password"
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="confirm-password-input"
                      />
                    </div>
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button type="submit" disabled={saving} data-testid="save-profile-button">
                    <Save size={16} className="mr-2" />
                    {saving ? "Saving..." : "Save Changes"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          {/* ────── AI Vision (Gemini / OpenAI / Claude / Emergent) ────── */}
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]" data-testid="ai-settings-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <span className="text-purple-400">⚡</span> AI Integrations
                {(aiGemini.has_key || aiOpenai.has_key || aiClaude.has_key || aiEmergent.has_key || (aiProvider === "emergent" && aiEmergent.platform_fallback)) && (
                  <span className="ml-2 rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs text-emerald-300">
                    Active ({aiProvider === "emergent" ? "krexion" : aiProvider})
                  </span>
                )}
              </CardTitle>
              <CardDescription className="space-y-1">
                <div>
                  Apna AI provider chunein. Yeh AI Visual Recorder mein JSON
                  steps auto-generate karne, Form Filler / RUT mein stuck pages se
                  recover karne, aur AI Vision fallback ke liye use hoti hai.
                  Aap apna khud ka API key save karenge — Krexion par koi extra
                  charge nahi padega.
                </div>
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">

              {/* Provider selector — 4 options */}
              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-zinc-300">Active provider:</label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <button
                    type="button"
                    onClick={() => handleProviderChange("gemini")}
                    data-testid="ai-provider-gemini"
                    className={`rounded-md px-3 py-2 text-sm transition text-left ${
                      aiProvider === "gemini"
                        ? "bg-purple-600 text-white border border-purple-500"
                        : "bg-zinc-900 text-zinc-300 border border-zinc-700 hover:border-zinc-500"
                    }`}
                  >
                    <div className="font-semibold">Google Gemini</div>
                    <div className="text-xs opacity-70 mt-0.5">
                      Free 1500/day {aiGemini.has_key && "✓"}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleProviderChange("openai")}
                    data-testid="ai-provider-openai"
                    className={`rounded-md px-3 py-2 text-sm transition text-left ${
                      aiProvider === "openai"
                        ? "bg-emerald-600 text-white border border-emerald-500"
                        : "bg-zinc-900 text-zinc-300 border border-zinc-700 hover:border-zinc-500"
                    }`}
                  >
                    <div className="font-semibold">OpenAI ChatGPT</div>
                    <div className="text-xs opacity-70 mt-0.5">
                      $5 trial credit {aiOpenai.has_key && "✓"}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleProviderChange("claude")}
                    data-testid="ai-provider-claude"
                    className={`rounded-md px-3 py-2 text-sm transition text-left ${
                      aiProvider === "claude"
                        ? "bg-orange-600 text-white border border-orange-500"
                        : "bg-zinc-900 text-zinc-300 border border-zinc-700 hover:border-zinc-500"
                    }`}
                  >
                    <div className="font-semibold">Anthropic Claude</div>
                    <div className="text-xs opacity-70 mt-0.5">
                      Best JSON quality {aiClaude.has_key && "✓"}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleProviderChange("emergent")}
                    data-testid="ai-provider-emergent"
                    className={`rounded-md px-3 py-2 text-sm transition text-left ${
                      aiProvider === "emergent"
                        ? "bg-blue-600 text-white border border-blue-500"
                        : "bg-zinc-900 text-zinc-300 border border-zinc-700 hover:border-zinc-500"
                    }`}
                    title="Use your own Krexion universal AI key, OR the built-in fallback if no key saved"
                  >
                    <div className="font-semibold">Krexion Universal</div>
                    <div className="text-xs opacity-70 mt-0.5">
                      {aiEmergent.has_key ? "Your key ✓" : (aiEmergent.platform_fallback ? "Built-in fallback" : "Not configured")}
                    </div>
                  </button>
                </div>
              </div>

              {/* Provider-specific step-by-step setup guide */}
              {aiProvider === "gemini" && (
                <div className="rounded-md border border-purple-900/40 bg-purple-950/20 p-3 text-xs text-purple-200/90 space-y-1.5">
                  <div className="font-semibold text-purple-300 text-sm">Google Gemini 2.5 Pro — Setup steps</div>
                  <ol className="list-decimal list-inside space-y-1">
                    <li>Open <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" className="text-purple-300 underline">aistudio.google.com/apikey</a> (sign-in with Google).</li>
                    <li>Click "Create API key" → choose / create a project.</li>
                    <li>Copy the key (starts with <code className="bg-zinc-900 px-1 rounded">AIza…</code>).</li>
                    <li>Paste below and click Save.</li>
                  </ol>
                  <div className="text-purple-300/60 pt-1">Free tier: 1500 requests/day. Best for JSON generation + screenshot vision.</div>
                </div>
              )}
              {aiProvider === "openai" && (
                <div className="rounded-md border border-emerald-900/40 bg-emerald-950/20 p-3 text-xs text-emerald-200/90 space-y-1.5">
                  <div className="font-semibold text-emerald-300 text-sm">OpenAI GPT-4o — Setup steps</div>
                  <ol className="list-decimal list-inside space-y-1">
                    <li>Open <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" className="text-emerald-300 underline">platform.openai.com/api-keys</a> and sign in.</li>
                    <li>Click "Create new secret key" → name it "Krexion".</li>
                    <li>Copy the key (starts with <code className="bg-zinc-900 px-1 rounded">sk-…</code>) — shown only once.</li>
                    <li>Settings → Billing → confirm trial credit OR add payment method.</li>
                    <li>Paste key below and click Save.</li>
                  </ol>
                  <div className="text-emerald-300/60 pt-1">$5 trial credit on new accounts (~50k vision calls). After that pay-as-you-go.</div>
                </div>
              )}
              {aiProvider === "claude" && (
                <div className="rounded-md border border-orange-900/40 bg-orange-950/20 p-3 text-xs text-orange-200/90 space-y-1.5">
                  <div className="font-semibold text-orange-300 text-sm">Anthropic Claude Sonnet 4.5 — Setup steps</div>
                  <ol className="list-decimal list-inside space-y-1">
                    <li>Open <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className="text-orange-300 underline">console.anthropic.com/settings/keys</a> and sign in.</li>
                    <li>Console → Billing → add at least $5 credit (Claude has no free tier).</li>
                    <li>Settings → API Keys → "Create Key" → name it "Krexion".</li>
                    <li>Copy the key (starts with <code className="bg-zinc-900 px-1 rounded">sk-ant-…</code>) — shown only once.</li>
                    <li>Paste below and click Save.</li>
                  </ol>
                  <div className="text-orange-300/60 pt-1">Highest JSON output quality. ~$3 per 1M input tokens + $15 per 1M output.</div>
                </div>
              )}
              {aiProvider === "emergent" && (
                <div className="rounded-md border border-blue-900/40 bg-blue-950/20 p-3 text-xs text-blue-200/90 space-y-1.5">
                  <div className="font-semibold text-blue-300 text-sm">Krexion Universal Key — Setup steps</div>
                  <ol className="list-decimal list-inside space-y-1">
                    <li>
                      <span className="font-semibold">Option A — Use your own Krexion universal AI key (recommended):</span><br/>
                      Krexion ka universal AI key copy karen aur neeche paste karen (key <code className="bg-zinc-900 px-1 rounded">sk-…</code> se shuru hoti hai).<br/>
                      Yeh ek hi key Gemini, OpenAI aur Claude — sab models par chalti hai. Aap apni AI subscription quota use karenge — Krexion par koi extra charge nahi padega.
                    </li>
                    <li>
                      <span className="font-semibold">Option B — Built-in fallback:</span><br/>
                      Koi key na save karein → Krexion ki platform-managed universal AI key automatically use hogi (fair-use limit).
                    </li>
                  </ol>
                  <div className={`pt-1 ${aiEmergent.available ? "text-blue-300/70" : "text-rose-300/80"}`}>
                    Status: {aiEmergent.has_key
                      ? "Using your own Krexion universal key ✓"
                      : (aiEmergent.platform_fallback
                          ? "No personal key saved — Krexion platform key will be used as fallback"
                          : "No personal key AND no platform fallback configured — please save your own key OR pick a different provider.")}
                  </div>
                </div>
              )}

              {/* Saved key status */}
              {aiProvider === "gemini" && aiGemini.has_key && aiGemini.key_preview && (
                <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
                  <span><span className="text-zinc-500">Saved Gemini key: </span><code className="text-zinc-300">{aiGemini.key_preview}</code></span>
                  <Button
                    variant="outline" size="sm"
                    onClick={() => handleClearAiKey("gemini")}
                    data-testid="clear-gemini-key"
                    className="border-red-700 text-red-300 hover:bg-red-950"
                  >Clear</Button>
                </div>
              )}
              {aiProvider === "openai" && aiOpenai.has_key && aiOpenai.key_preview && (
                <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
                  <span><span className="text-zinc-500">Saved OpenAI key: </span><code className="text-zinc-300">{aiOpenai.key_preview}</code></span>
                  <Button
                    variant="outline" size="sm"
                    onClick={() => handleClearAiKey("openai")}
                    data-testid="clear-openai-key"
                    className="border-red-700 text-red-300 hover:bg-red-950"
                  >Clear</Button>
                </div>
              )}
              {aiProvider === "claude" && aiClaude.has_key && (
                <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
                  <span>
                    <span className="text-zinc-500">Saved Claude key: </span>
                    <code className="text-zinc-300">{aiClaude.key_preview || "sk-ant-…"}</code>
                  </span>
                  <Button
                    variant="outline" size="sm"
                    onClick={() => handleClearAiKey("claude")}
                    data-testid="clear-claude-key"
                    className="border-red-700 text-red-300 hover:bg-red-950"
                  >Clear</Button>
                </div>
              )}
              {aiProvider === "emergent" && aiEmergent.has_key && (
                <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
                  <span>
                    <span className="text-zinc-500">Saved Krexion key: </span>
                    <code className="text-zinc-300">{aiEmergent.key_preview || "sk-…"}</code>
                  </span>
                  <Button
                    variant="outline" size="sm"
                    onClick={() => handleClearAiKey("emergent")}
                    data-testid="clear-emergent-key"
                    className="border-red-700 text-red-300 hover:bg-red-950"
                  >Clear</Button>
                </div>
              )}

              {/* Key input — always available (Emergent allows optional personal key) */}
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  type="password"
                  placeholder={
                    aiProvider === "gemini"
                      ? (aiGemini.has_key ? "Paste new key to replace…" : "AIzaSy...")
                      : aiProvider === "openai"
                        ? (aiOpenai.has_key ? "Paste new key to replace…" : "sk-...")
                        : aiProvider === "claude"
                          ? (aiClaude.has_key ? "Paste new key to replace…" : "sk-ant-...")
                          : (aiEmergent.has_key ? "Paste new key to replace…" : "sk-... (Krexion universal AI key — optional, blank uses platform fallback)")
                  }
                  value={aiKey}
                  onChange={(e) => setAiKey(e.target.value)}
                  className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-purple-500 focus:outline-none"
                  data-testid="ai-key-input"
                />
                <Button
                  onClick={handleSaveAiKey}
                  disabled={aiSaving || !aiKey}
                  data-testid="save-ai-key-button"
                  className={
                    aiProvider === "openai"
                      ? "bg-emerald-600 hover:bg-emerald-700"
                      : aiProvider === "claude"
                        ? "bg-orange-600 hover:bg-orange-700"
                        : aiProvider === "emergent"
                          ? "bg-blue-600 hover:bg-blue-700"
                          : "bg-purple-600 hover:bg-purple-700"
                  }
                >
                  {aiSaving ? "Saving..." : "Save Key"}
                </Button>
              </div>
              <div className="text-xs text-zinc-500">
                Tip: AI features (Visual Recorder "Generate with AI", Form-filler
                self-heal, RUT recovery) sirf tab call hoti hain jab rule-based
                logic stuck ho ya aap explicitly Generate-with-AI button daboye —
                taa ke API quota bachay.
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Sub-Users Tab */}
        <TabsContent value="subusers" className="space-y-6">
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Users size={20} />
                    Sub-User Management
                    {user?.max_sub_users > 0 && (
                      <Badge variant="outline" className="ml-2 text-xs">
                        {subUsers.length}/{user.max_sub_users} used
                      </Badge>
                    )}
                  </CardTitle>
                  <CardDescription>
                    Create sub-accounts with limited access for team members
                    {user?.max_sub_users > 0 && (
                      <span className="text-[#F59E0B]"> (Limit: {user.max_sub_users})</span>
                    )}
                  </CardDescription>
                </div>
                <Dialog open={subUserDialogOpen} onOpenChange={setSubUserDialogOpen}>
                  <DialogTrigger asChild>
                    <Button 
                      onClick={openCreateSubUser} 
                      data-testid="create-subuser-button"
                      disabled={user?.max_sub_users > 0 && subUsers.length >= user.max_sub_users}
                    >
                      <Plus size={16} className="mr-2" />
                      Add Sub-User
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                    <DialogHeader>
                      <DialogTitle>{editingSubUser ? "Edit Sub-User" : "Create Sub-User"}</DialogTitle>
                      <DialogDescription>
                        {editingSubUser ? "Update sub-user details and permissions" : "Create a new sub-user with specific permissions"}
                      </DialogDescription>
                    </DialogHeader>
                    <form onSubmit={handleCreateSubUser} className="space-y-4">
                      <div className="space-y-2">
                        <Label htmlFor="sub-email">Email</Label>
                        <Input
                          id="sub-email"
                          type="email"
                          value={subUserForm.email}
                          onChange={(e) => setSubUserForm({ ...subUserForm, email: e.target.value })}
                          disabled={!!editingSubUser}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                          required
                          data-testid="subuser-email-input"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="sub-name">Name</Label>
                        <Input
                          id="sub-name"
                          type="text"
                          value={subUserForm.name}
                          onChange={(e) => setSubUserForm({ ...subUserForm, name: e.target.value })}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                          required
                          data-testid="subuser-name-input"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="sub-password">
                          {editingSubUser ? "New Password (leave empty to keep current)" : "Password"}
                        </Label>
                        <Input
                          id="sub-password"
                          type="password"
                          value={subUserForm.password}
                          onChange={(e) => setSubUserForm({ ...subUserForm, password: e.target.value })}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                          required={!editingSubUser}
                          data-testid="subuser-password-input"
                        />
                      </div>
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <Label>Permissions</Label>
                          {/* 2026-01: Quick "All Features" toggle — mirrors the
                              admin "give user all features" workflow so the main
                              user can delegate the same breadth of access to a
                              sub-user with one click. Only enables the features
                              the parent ACTUALLY owns (backend caps it anyway). */}
                          <div className="flex gap-1.5">
                            <button
                              type="button"
                              onClick={() => {
                                const all = {};
                                ALL_SUB_USER_PERMISSIONS.forEach(({ key }) => { all[key] = true; });
                                setSubUserForm({ ...subUserForm, permissions: all });
                              }}
                              className="text-[11px] px-2 py-1 rounded bg-emerald-700/40 hover:bg-emerald-600/60 border border-emerald-500/40 text-emerald-200 font-medium"
                              data-testid="subuser-grant-all-btn"
                              title="Grant every permission the parent account has"
                            >
                              Grant all
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                const none = {};
                                ALL_SUB_USER_PERMISSIONS.forEach(({ key }) => { none[key] = false; });
                                setSubUserForm({ ...subUserForm, permissions: none });
                              }}
                              className="text-[11px] px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 font-medium"
                              data-testid="subuser-revoke-all-btn"
                              title="Revoke every permission"
                            >
                              Revoke all
                            </button>
                          </div>
                        </div>
                        <div className="bg-[var(--brand-card)] p-4 rounded-lg space-y-3 max-h-[320px] overflow-y-auto">
                          {ALL_SUB_USER_PERMISSIONS.map(({ key, label, parentFeatKey }) => {
                            // Disable toggle if parent doesn't own this feature
                            // (backend caps it anyway but the UI hint is useful).
                            const parentHas = parentFeatKey
                              ? (user?.features?.[parentFeatKey] !== false)
                              : true;
                            return (
                              <div key={key} className={`flex items-center justify-between ${parentHas ? "" : "opacity-50"}`} title={parentHas ? "" : "Parent account doesn't own this feature"}>
                                <span className="text-sm">
                                  {label}
                                  {!parentHas && <span className="ml-1 text-[10px] text-amber-400">(not owned by parent)</span>}
                                </span>
                                <Switch
                                  checked={subUserForm.permissions[key] || false}
                                  disabled={!parentHas}
                                  onCheckedChange={(checked) => setSubUserForm({
                                    ...subUserForm,
                                    permissions: { ...subUserForm.permissions, [key]: checked }
                                  })}
                                  data-testid={`permission-${key}`}
                                />
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      <Button type="submit" className="w-full" data-testid="submit-subuser-button">
                        {editingSubUser ? "Update Sub-User" : "Create Sub-User"}
                      </Button>
                    </form>
                  </DialogContent>
                </Dialog>
              </div>
            </CardHeader>
            <CardContent>
              {user?.status !== "active" ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Shield size={48} className="mx-auto mb-4 opacity-50" />
                  <p>Sub-user management is only available for active accounts.</p>
                  <p className="text-sm mt-2">Contact admin to activate your account.</p>
                </div>
              ) : subUsers.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Users size={48} className="mx-auto mb-4 opacity-50" />
                  <p>No sub-users created yet.</p>
                  <p className="text-sm mt-2">Click &quot;Add Sub-User&quot; to create team accounts with limited access.</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                      <TableHead>User</TableHead>
                      <TableHead>Permissions</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Active</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {subUsers.map((subUser) => (
                      <TableRow key={subUser.id} className="border-[var(--brand-border)]" data-testid={`subuser-row-${subUser.id}`}>
                        <TableCell>
                          <div>
                            <p className="font-medium text-white">{subUser.name}</p>
                            <p className="text-sm text-muted-foreground">{subUser.email}</p>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 flex-wrap max-w-[280px]">
                            {(() => {
                              // 2026-01: Show a compact badge for every
                              // permission granted (previously hard-coded
                              // to only 4). If user has 4+ grants we just
                              // show a "+N more" tally so the row height
                              // stays compact.
                              const granted = ALL_SUB_USER_PERMISSIONS.filter(
                                ({ key }) => subUser.permissions?.[key]
                              );
                              if (!granted.length) {
                                return <span className="text-xs text-muted-foreground">No permissions</span>;
                              }
                              const visible = granted.slice(0, 4);
                              const overflow = granted.length - visible.length;
                              return (
                                <>
                                  {visible.map(({ key, label }) => (
                                    <Badge
                                      key={key}
                                      variant="outline"
                                      className="text-xs border-[#22C55E] text-[#22C55E]"
                                    >
                                      {label.replace(/^View /, "")}
                                    </Badge>
                                  ))}
                                  {overflow > 0 && (
                                    <Badge variant="outline" className="text-xs border-zinc-600 text-zinc-400" title={granted.slice(4).map((g) => g.label).join(", ")}>
                                      +{overflow} more
                                    </Badge>
                                  )}
                                </>
                              );
                            })()}
                          </div>
                        </TableCell>
                        <TableCell>
                          {subUser.is_active ? (
                            <Badge className="bg-[#22C55E]">Active</Badge>
                          ) : (
                            <Badge className="bg-[#EF4444]">Inactive</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {subUser.last_active ? (
                            <div className="flex items-center gap-1">
                              <Clock size={14} />
                              {format(new Date(subUser.last_active), "MMM dd, HH:mm")}
                            </div>
                          ) : (
                            "Never"
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleToggleSubUserActive(subUser)}
                              className={subUser.is_active ? "border-[#EF4444] text-[#EF4444]" : "border-[#22C55E] text-[#22C55E]"}
                              data-testid={`toggle-subuser-${subUser.id}`}
                            >
                              {subUser.is_active ? <XCircle size={14} /> : <CheckCircle size={14} />}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => openEditSubUser(subUser)}
                              className="border-[var(--brand-border)]"
                              data-testid={`edit-subuser-${subUser.id}`}
                            >
                              <Edit2 size={14} />
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleDeleteSubUser(subUser.id, subUser.name)}
                              data-testid={`delete-subuser-${subUser.id}`}
                            >
                              <Trash2 size={14} />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Sub-User Statistics Card */}
          {subUserStats.length > 0 && (
            <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 size={20} className="text-[#8B5CF6]" />
                  Sub-User Statistics
                </CardTitle>
                <CardDescription>
                  Track usage and activity of your sub-users
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                      <TableHead>Sub-User</TableHead>
                      <TableHead>Links</TableHead>
                      <TableHead>Clicks</TableHead>
                      <TableHead>Proxies</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Active</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {subUserStats.map((stat) => (
                      <TableRow key={stat.id} className="border-[var(--brand-border)]" data-testid={`stat-row-${stat.id}`}>
                        <TableCell>
                          <div>
                            <p className="font-medium text-white">{stat.name}</p>
                            <p className="text-sm text-muted-foreground">{stat.email}</p>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Link2 size={14} className="text-[#3B82F6]" />
                            <span className="font-medium">{stat.link_count}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <MousePointerClick size={14} className="text-[#22C55E]" />
                            <span className="font-medium">{stat.click_count}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Server size={14} className="text-[#8B5CF6]" />
                            <span className="font-medium">{stat.proxy_count}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {stat.is_active ? (
                            <Badge className="bg-[#22C55E]">Active</Badge>
                          ) : (
                            <Badge className="bg-[#EF4444]">Inactive</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {stat.last_active ? format(new Date(stat.last_active), "MMM dd, HH:mm") : "Never"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Subscription Tab */}
        <TabsContent value="subscription" className="space-y-6">
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield size={20} />
                Subscription Status
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-[var(--brand-card)] p-6 rounded-lg border border-[var(--brand-border)]">
                  <h4 className="text-sm text-muted-foreground mb-2">Account Status</h4>
                  <div className="flex items-center gap-2">
                    {user?.status === "active" ? (
                      <>
                        <CheckCircle className="text-[#22C55E]" size={24} />
                        <span className="text-xl font-bold text-[#22C55E]">Active</span>
                      </>
                    ) : user?.status === "blocked" ? (
                      <>
                        <XCircle className="text-[#EF4444]" size={24} />
                        <span className="text-xl font-bold text-[#EF4444]">Blocked</span>
                      </>
                    ) : (
                      <>
                        <Clock className="text-[#F59E0B]" size={24} />
                        <span className="text-xl font-bold text-[#F59E0B]">Pending</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="bg-[var(--brand-card)] p-6 rounded-lg border border-[var(--brand-border)]">
                  <h4 className="text-sm text-muted-foreground mb-2">Subscription Type</h4>
                  <p className="text-xl font-bold capitalize">{user?.subscription_type || "Free"}</p>
                  {user?.subscription_expires && (
                    <p className="text-sm text-muted-foreground mt-1">
                      Expires: {format(new Date(user.subscription_expires), "MMM dd, yyyy")}
                    </p>
                  )}
                </div>
              </div>

              <div className="border-t border-[var(--brand-border)] pt-6">
                <h4 className="text-lg font-medium mb-4">Active Features</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { key: "links", label: "Links Management", icon: "🔗" },
                    { key: "clicks", label: "Click Tracking", icon: "📊" },
                    { key: "conversions", label: "Conversions", icon: "💰" },
                    { key: "proxies", label: "Proxy Management", icon: "🌐" },
                    { key: "import_data", label: "Data Import", icon: "📥" }
                  ].map(({ key, label, icon }) => (
                    <div
                      key={key}
                      className={`p-4 rounded-lg border ${
                        user?.features?.[key]
                          ? "bg-[#22C55E]/10 border-[#22C55E]/30"
                          : "bg-[#27272A]/30 border-[var(--brand-border)]"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span>{icon}</span>
                        {user?.features?.[key] ? (
                          <CheckCircle size={14} className="text-[#22C55E]" />
                        ) : (
                          <XCircle size={14} className="text-[#71717A]" />
                        )}
                      </div>
                      <p className={`text-sm ${user?.features?.[key] ? "text-white" : "text-muted-foreground"}`}>
                        {label}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-[var(--brand-card)] p-4 rounded-lg border border-[var(--brand-border)]">
                <p className="text-sm text-muted-foreground">
                  To upgrade your subscription or request additional features, please contact admin at{" "}
                  <a href={`mailto:${user?.admin_contact}`} className="text-[#3B82F6] hover:underline">
                    {user?.admin_contact}
                  </a>
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ─────── Notifications Tab ─────── */}
        <TabsContent value="notifications" className="space-y-6">
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]" data-testid="notif-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell size={20} />
                Low-Stock Email Alerts
              </CardTitle>
              <CardDescription>
                Get an email the moment a live Google Sheet upload runs low
                — refill your sheet before the bot stalls.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="rounded-md border border-[var(--brand-border)] bg-[var(--brand-card-elevated)] p-4 space-y-1">
                <div className="text-xs text-zinc-500 uppercase tracking-wider">
                  Trigger threshold
                </div>
                <div className="text-zinc-100 font-medium">
                  ≤ <span className="text-amber-400">{notifThreshold}%</span> rows remaining
                </div>
                <div className="text-xs text-zinc-500 leading-relaxed">
                  Example: a sheet that started with 1,000 rows triggers when
                  fewer than {Math.round(1000 * notifThreshold / 100)} rows are
                  left. The alert fires once per depletion — refilling the
                  sheet automatically re-arms it.
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-zinc-300">Notification email</Label>
                <Input
                  type="email"
                  value={notifEmail}
                  onChange={(e) => setNotifEmail(e.target.value)}
                  placeholder={notifPrimaryEmail || "alerts@yourdomain.com"}
                  className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]"
                  data-testid="notif-email-input"
                />
                <div className="text-xs text-zinc-500 leading-relaxed">
                  Leave blank to use your login email
                  {notifPrimaryEmail && (
                    <>
                      {" "}(<span className="font-mono text-zinc-400">{notifPrimaryEmail}</span>)
                    </>
                  )}
                  . Use a different address if you want alerts to go to ops /
                  team / different inbox than your main login.
                </div>
              </div>

              <div className="flex items-center justify-between rounded-md border border-[var(--brand-border)] bg-[var(--brand-card-elevated)] px-4 py-3">
                <div>
                  <div className="text-zinc-100 font-medium text-sm">
                    Enable low-stock alerts
                  </div>
                  <div className="text-xs text-zinc-500">
                    Toggle off to silence all gsheet depletion emails for this account.
                  </div>
                </div>
                <Switch
                  checked={notifAlertsEnabled}
                  onCheckedChange={setNotifAlertsEnabled}
                  data-testid="notif-alerts-toggle"
                />
              </div>

              <Button
                onClick={handleSaveNotifSettings}
                disabled={notifSaving}
                className="bg-[#3B82F6] hover:bg-[#2563EB]"
                data-testid="notif-save-btn"
              >
                <Save size={16} className="mr-2" />
                {notifSaving ? "Saving..." : "Save notification settings"}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Fraud Detection Tab */}
        <TabsContent value="fraud" className="space-y-6">
          <FraudDetectionTab />
        </TabsContent>

        {/* Proxy Providers Tab */}
        <TabsContent value="proxy-providers" className="space-y-6">
          <ProxyProvidersTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
