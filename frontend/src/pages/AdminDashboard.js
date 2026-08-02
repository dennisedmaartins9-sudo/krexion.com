import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import SystemCheckPanel from "../components/SystemCheckPanel";
import CrossUserIpIsolationPanel from "../components/CrossUserIpIsolationPanel";
import { toast } from "sonner";
import { format } from "date-fns";
import { 
  Shield, Users, Link2, MousePointer, DollarSign, 
  LogOut, Settings, Trash2, CheckCircle, XCircle, 
  Clock, Search, RefreshCw, Eye, EyeOff, UserPlus,
  Palette, Image, Type, RotateCcw, Save, Server, Key, Plus, TestTube, Globe,
  Activity, Mail, Send, ExternalLink, AlertCircle, Menu, Cpu, ShieldCheck, Cloud, Lock
} from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator } from "../components/ui/dropdown-menu";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedUser, setSelectedUser] = useState(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [userFeatures, setUserFeatures] = useState({
    links: false,
    clicks: false,
    conversions: false,
    proxies: false,
    import_data: false,
    max_links: 10,
    max_clicks: 10000
  });
  const [userStatus, setUserStatus] = useState("pending");
  const [subscriptionNote, setSubscriptionNote] = useState("");
  const [subscriptionType, setSubscriptionType] = useState("free");
  const [subscriptionExpires, setSubscriptionExpires] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [activeTab, setActiveTab] = useState("users");
  // Heavy-features VPS protection badge (cloud+strict block status)
  const [heavyStatus, setHeavyStatus] = useState(null);
  const [togglingStrict, setTogglingStrict] = useState(false);
  const [adminAccount, setAdminAccount] = useState(null);
  const [adminCurrentPassword, setAdminCurrentPassword] = useState("");
  const [adminNewPassword, setAdminNewPassword] = useState("");
  const [adminConfirmPassword, setAdminConfirmPassword] = useState("");
  const [adminPasswordSaving, setAdminPasswordSaving] = useState(false);
  const [showAdminCurrentPassword, setShowAdminCurrentPassword] = useState(false);
  const [showAdminNewPassword, setShowAdminNewPassword] = useState(false);

  // ── Email settings (admin-managed SMTP / Resend) ──
  const [emailCfg, setEmailCfg] = useState({
    provider: "disabled",
    smtp_host: "",
    smtp_port: 587,
    smtp_user: "",
    smtp_password: "",        // local-only — only sent on save when typed
    smtp_password_set: false, // server tells us if a value already exists
    smtp_password_preview: "",
    resend_api_key: "",       // local-only
    resend_api_key_set: false,
    resend_api_key_preview: "",
    resend_from: "",
    sender_name: "Krexion",
    sender_email: "",
    updated_at: "",
  });
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailTesting, setEmailTesting] = useState(false);
  const [emailTestTo, setEmailTestTo] = useState("");
  const [emailHelpOpen, setEmailHelpOpen] = useState(false);
  const [branding, setBranding] = useState({
    app_name: "Krexion",
    tagline: "Real Users. Real Results.",
    logo_url: "",
    favicon_url: "",
    primary_color: "#3B82F6",
    secondary_color: "#22C55E",
    accent_color: "#8B5CF6",
    danger_color: "#EF4444",
    warning_color: "#F59E0B",
    success_color: "#22C55E",
    background_color: "#09090B",
    card_color: "#18181B",
    border_color: "#27272A",
    text_color: "#FAFAFA",
    muted_color: "#A1A1AA",
    login_bg_url: "",
    admin_email: "",
    footer_text: "",
    sidebar_style: "dark",
    button_style: "rounded",
    font_family: "Inter"
  });
  const [brandingSaving, setBrandingSaving] = useState(false);
  // Sub-users state
  const [subUsers, setSubUsers] = useState([]);
  const [subUserSearchTerm, setSubUserSearchTerm] = useState("");
  const [selectedSubUser, setSelectedSubUser] = useState(null);
  const [editSubUserDialogOpen, setEditSubUserDialogOpen] = useState(false);
  const [subUserName, setSubUserName] = useState("");
  const [subUserPassword, setSubUserPassword] = useState("");
  const [subUserPermissions, setSubUserPermissions] = useState({});
  const [subUserIsActive, setSubUserIsActive] = useState(true);
  // API Settings state
  const [apiSettings, setApiSettings] = useState({});
  const [apiSettingsLoading, setApiSettingsLoading] = useState(false);
  const [showApiKey, setShowApiKey] = useState({});
  const [testingApi, setTestingApi] = useState(null);
  const [addApiDialogOpen, setAddApiDialogOpen] = useState(false);
  const [apiStatus, setApiStatus] = useState(null);
  const [newApiData, setNewApiData] = useState({
    key: "",
    name: "",
    enabled: true,
    api_key: "",
    endpoint: "",
    priority: 10,
    description: ""
  });
  const navigate = useNavigate();

  useEffect(() => {
    const adminToken = localStorage.getItem("adminToken");
    if (!adminToken) {
      navigate("/admin");
      return;
    }
    fetchData();
    fetchEmailSettings();
  }, [navigate]);

  const getAdminToken = () => localStorage.getItem("adminToken");

  const fetchEmailSettings = async () => {
    try {
      const r = await axios.get(`${API}/admin/email-settings`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` },
      });
      setEmailCfg((prev) => ({
        ...prev,
        ...r.data,
        // Don't overwrite typed-but-not-saved fields with empty server response
        smtp_password: "",
        resend_api_key: "",
      }));
    } catch (e) {
      // ignore on first load
    }
  };

  const handleSaveEmailSettings = async () => {
    setEmailSaving(true);
    try {
      // Build payload — only send password fields when admin typed something
      // new. Otherwise the server keeps the previously-saved value.
      const payload = {
        provider: emailCfg.provider,
        smtp_host: emailCfg.smtp_host,
        smtp_port: Number(emailCfg.smtp_port) || 587,
        smtp_user: emailCfg.smtp_user,
        resend_from: emailCfg.resend_from,
        sender_name: emailCfg.sender_name,
        sender_email: emailCfg.sender_email,
      };
      if (emailCfg.smtp_password) payload.smtp_password = emailCfg.smtp_password;
      if (emailCfg.resend_api_key) payload.resend_api_key = emailCfg.resend_api_key;
      await axios.put(`${API}/admin/email-settings`, payload, {
        headers: { Authorization: `Bearer ${getAdminToken()}` },
      });
      toast.success("Email settings saved");
      await fetchEmailSettings();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to save email settings");
    } finally {
      setEmailSaving(false);
    }
  };

  const handleTestEmail = async () => {
    setEmailTesting(true);
    try {
      const target = emailTestTo.trim();
      const r = await axios.post(
        `${API}/admin/email-settings/test`,
        target ? { to: target } : {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      const status = r.data?.status;
      if (status === "sent") {
        toast.success(`Test email sent via ${r.data?.provider} to ${r.data?.to}`);
      } else if (status === "logged") {
        toast.warning(`No provider configured — email was only logged. Save creds first.`);
      } else {
        toast.warning(`Unexpected status: ${status}`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Test failed");
    } finally {
      setEmailTesting(false);
    }
  };

  const fetchData = async () => {
    try {
      const headers = { Authorization: `Bearer ${getAdminToken()}` };
      
      // Fetch each endpoint separately with error handling
      const fetchWithFallback = async (url, fallback) => {
        try {
          const res = await axios.get(url, { headers });
          return res.data;
        } catch (err) {
          console.error(`Failed to fetch ${url}:`, err);
          return fallback;
        }
      };
      
      // Fetch all data with individual error handling
      const [statsData, usersData, brandingData, subUsersData, userStatsData, apiSettingsData, apiStatusData, heavyData, accountData] = await Promise.all([
        fetchWithFallback(`${API}/admin/stats`, { total_users: 0, active_users: 0, pending_users: 0, blocked_users: 0, total_links: 0, total_clicks: 0, total_conversions: 0, total_sub_users: 0, users_with_sub_users: 0 }),
        fetchWithFallback(`${API}/admin/users`, []),
        fetchWithFallback(`${API}/admin/branding`, {}),
        fetchWithFallback(`${API}/admin/sub-users`, []),
        fetchWithFallback(`${API}/admin/users/stats/all`, []),
        fetchWithFallback(`${API}/admin/api-settings`, {}),
        fetchWithFallback(`${API}/admin/api-settings/status`, { apis: [], total_enabled: 0, total_rate_limited: 0 }),
        fetchWithFallback(`${API}/admin/heavy-features-status`, null),
        fetchWithFallback(`${API}/admin/account`, null),
      ]);
      
      setStats(statsData);
      setHeavyStatus(heavyData);
      setAdminAccount(accountData && accountData.email ? accountData : null);
      
      // Merge user stats with user data
      const usersWithStats = usersData.map(user => {
        const userStats = userStatsData.find(s => s.id === user.id) || {};
        return {
          ...user,
          link_count: userStats.link_count || 0,
          click_count: userStats.click_count || 0,
          proxy_count: userStats.proxy_count || 0
        };
      });
      setUsers(usersWithStats);
      
      setBranding(brandingData);
      setSubUsers(subUsersData);
      setApiSettings(apiSettingsData);
      setApiStatus(apiStatusData);
    } catch (error) {
      if (error.response?.status === 401 || error.response?.status === 403) {
        localStorage.removeItem("adminToken");
        navigate("/admin");
      }
      toast.error("Failed to fetch data");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("adminToken");
    localStorage.removeItem("isAdmin");
    navigate("/admin");
  };

  const openEditDialog = (user) => {
    setSelectedUser(user);
    setUserFeatures(user.features || {
      links: false,
      clicks: false,
      conversions: false,
      proxies: false,
      import_data: false,
      max_links: 10,
      max_clicks: 10000
    });
    setUserStatus(user.status || "pending");
    setSubscriptionNote(user.subscription_note || "");
    setSubscriptionType(user.subscription_type || "free");
    setSubscriptionExpires(user.subscription_expires ? user.subscription_expires.split("T")[0] : "");
    setUserEmail(user.email);
    setUserPassword("");
    setEditDialogOpen(true);
  };

  const handleUpdateUser = async () => {
    if (!selectedUser) return;

    try {
      const updateData = {
        status: userStatus,
        features: userFeatures,
        subscription_note: subscriptionNote,
        subscription_type: subscriptionType
      };
      
      if (subscriptionExpires) {
        updateData.subscription_expires = subscriptionExpires + "T00:00:00Z";
      }
      
      if (userEmail !== selectedUser.email) {
        updateData.email = userEmail;
      }
      
      if (userPassword) {
        updateData.password = userPassword;
      }
      
      await axios.put(
        `${API}/admin/users/${selectedUser.id}`,
        updateData,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("User updated successfully");
      setEditDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update user");
    }
  };

  const handleDeleteUser = async (userId, userName) => {
    if (!window.confirm(`Are you sure you want to delete user "${userName}"? This will delete ALL their data including links, clicks, and conversions.`)) {
      return;
    }

    try {
      await axios.delete(`${API}/admin/users/${userId}`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` }
      });
      toast.success("User deleted successfully");
      fetchData();
    } catch (error) {
      toast.error("Failed to delete user");
    }
  };

  const quickActivate = async (userId) => {
    try {
      await axios.put(
        `${API}/admin/users/${userId}`,
        {
          status: "active",
          features: {
            links: true,
            clicks: true,
            conversions: true,
            proxies: true,
            import_data: true,
            max_links: 100,
            max_clicks: 100000
          }
        },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("User activated with full access");
      fetchData();
    } catch (error) {
      toast.error("Failed to activate user");
    }
  };

  const quickBlock = async (userId) => {
    try {
      await axios.put(
        `${API}/admin/users/${userId}`,
        { status: "blocked" },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("User blocked");
      fetchData();
    } catch (error) {
      toast.error("Failed to block user");
    }
  };

  // v2.6.1 — Toggle per-user override that lets a specific customer
  // run heavy features (RUT, Form Filler, Visual Recorder) on the VPS
  // even while global strict_heavy_block stays ON for everyone else.
  const toggleCloudHeavy = async (user) => {
    const nextValue = !user.allow_cloud_heavy;
    setUsers((prev) =>
      prev.map((u) => (u.id === user.id ? { ...u, allow_cloud_heavy: nextValue } : u))
    );
    try {
      await axios.put(
        `${API}/admin/users/${user.id}`,
        { allow_cloud_heavy: nextValue },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success(
        nextValue
          ? `${user.email} — VPS Heavy ON (can run RUT/VR on VPS)`
          : `${user.email} — VPS Heavy OFF (desktop-only when strict is on)`
      );
      fetchData();
    } catch (error) {
      setUsers((prev) =>
        prev.map((u) => (u.id === user.id ? { ...u, allow_cloud_heavy: !nextValue } : u))
      );
      toast.error("Failed to update VPS heavy override");
    }
  };

  const toggleStrictMode = async () => {
    const dep = heavyStatus?.deployment;
    if (!dep?.is_cloud) return;
    const next = !dep.strict_heavy_block;
    const confirmMsg = next
      ? "Enable Strict Mode? Heavy features (RUT, Form Filler, Visual Recorder, bulk proxy tests) will REFUSE to run on this VPS unless the user has VPS Heavy enabled."
      : "Disable Strict Mode? Heavy features may run on this VPS when customer PCs are offline — VPS load may spike.";
    if (!window.confirm(confirmMsg)) return;
    setTogglingStrict(true);
    try {
      const r = await axios.post(
        `${API}/admin/system/strict-mode`,
        { enabled: next },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success(r.data?.message || `Strict mode ${next ? "ON" : "OFF"}`);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to toggle strict mode");
    } finally {
      setTogglingStrict(false);
    }
  };

  const changeAdminPassword = async () => {
    if (!adminCurrentPassword || !adminNewPassword) {
      toast.error("Current and new password are required");
      return;
    }
    if (adminNewPassword.length < 8) {
      toast.error("New password must be at least 8 characters");
      return;
    }
    if (adminNewPassword !== adminConfirmPassword) {
      toast.error("New passwords do not match");
      return;
    }
    setAdminPasswordSaving(true);
    try {
      const r = await axios.post(
        `${API}/admin/account/change-password`,
        {
          current_password: adminCurrentPassword,
          new_password: adminNewPassword,
        },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success(r.data?.message || "Admin password updated");
      setAdminCurrentPassword("");
      setAdminNewPassword("");
      setAdminConfirmPassword("");
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to change admin password");
    } finally {
      setAdminPasswordSaving(false);
    }
  };

  const toggleSelectUser = (userId) => {
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const toggleSelectAll = () => {
    if (selectedUsers.length === filteredUsers.length) {
      setSelectedUsers([]);
    } else {
      setSelectedUsers(filteredUsers.map((u) => u.id));
    }
  };

  const handleBulkDeleteUsers = async () => {
    if (selectedUsers.length === 0) {
      toast.error("No users selected");
      return;
    }

    if (!window.confirm(`Are you sure you want to delete ${selectedUsers.length} users? This will delete ALL their data including links, clicks, and conversions. This action cannot be undone.`)) {
      return;
    }

    try {
      // Delete users one by one
      let deleted = 0;
      for (const userId of selectedUsers) {
        await axios.delete(`${API}/admin/users/${userId}`, {
          headers: { Authorization: `Bearer ${getAdminToken()}` }
        });
        deleted++;
      }
      toast.success(`${deleted} users deleted successfully`);
      setSelectedUsers([]);
      fetchData();
    } catch (error) {
      toast.error("Failed to delete some users");
      fetchData();
    }
  };

  const filteredUsers = users.filter(user => 
    user.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    user.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Sub-user functions
  const filteredSubUsers = subUsers.filter(subUser => 
    subUser.email.toLowerCase().includes(subUserSearchTerm.toLowerCase()) ||
    subUser.name.toLowerCase().includes(subUserSearchTerm.toLowerCase()) ||
    (subUser.parent_email && subUser.parent_email.toLowerCase().includes(subUserSearchTerm.toLowerCase()))
  );

  const openEditSubUserDialog = (subUser) => {
    setSelectedSubUser(subUser);
    setSubUserName(subUser.name);
    setSubUserPassword("");
    setSubUserPermissions(subUser.permissions || {});
    setSubUserIsActive(subUser.is_active !== false);
    setEditSubUserDialogOpen(true);
  };

  const handleUpdateSubUser = async () => {
    if (!selectedSubUser) return;

    try {
      const updateData = {
        name: subUserName,
        permissions: subUserPermissions,
        is_active: subUserIsActive
      };
      
      if (subUserPassword) {
        updateData.password = subUserPassword;
      }
      
      await axios.put(
        `${API}/admin/sub-users/${selectedSubUser.id}`,
        updateData,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("Sub-user updated successfully");
      setEditSubUserDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update sub-user");
    }
  };

  const handleDeleteSubUser = async (subUserId, subUserName) => {
    if (!window.confirm(`Are you sure you want to delete sub-user "${subUserName}"?`)) {
      return;
    }

    try {
      await axios.delete(`${API}/admin/sub-users/${subUserId}`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` }
      });
      toast.success("Sub-user deleted successfully");
      fetchData();
    } catch (error) {
      toast.error("Failed to delete sub-user");
    }
  };

  const handleBrandingChange = (field, value) => {
    setBranding(prev => ({ ...prev, [field]: value }));
  };

  const handleSaveBranding = async () => {
    setBrandingSaving(true);
    try {
      await axios.put(
        `${API}/admin/branding`,
        branding,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      toast.success("Branding saved successfully! Refresh the page to see changes.");
    } catch (error) {
      toast.error("Failed to save branding");
    } finally {
      setBrandingSaving(false);
    }
  };

  const handleResetBranding = async () => {
    if (!window.confirm("Are you sure you want to reset branding to default settings?")) return;
    
    try {
      const response = await axios.post(
        `${API}/admin/branding/reset`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setBranding(response.data.branding);
      toast.success("Branding reset to default");
    } catch (error) {
      toast.error("Failed to reset branding");
    }
  };

  // API Settings Functions
  const handleApiSettingChange = async (apiKey, field, value) => {
    try {
      const response = await axios.put(
        `${API}/admin/api-settings/${apiKey}`,
        { [field]: value },
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      // Backend returns full settings (with possible auto-disable cascade)
      if (response.data?.all_settings) {
        setApiSettings(response.data.all_settings);
      } else {
        setApiSettings(prev => ({
          ...prev,
          [apiKey]: { ...prev[apiKey], [field]: value }
        }));
      }
      const autoDisabled = response.data?.auto_disabled || [];
      if (autoDisabled.length > 0) {
        toast.success(
          `${apiSettings[apiKey]?.name || apiKey} enabled. Free APIs auto-disabled: ${autoDisabled.join(", ")}`,
          { duration: 5000 }
        );
      } else {
        toast.success(`${apiSettings[apiKey]?.name || apiKey} updated`);
      }
      // Refresh status to reflect any cascaded changes
      refreshApiStatus();
    } catch (error) {
      toast.error("Failed to update API setting");
    }
  };

  const handleTestApi = async (apiKey) => {
    setTestingApi(apiKey);
    try {
      const response = await axios.post(
        `${API}/admin/api-settings/test/${apiKey}`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      if (response.data.success) {
        toast.success(`${apiSettings[apiKey]?.name || apiKey}: API is working!`);
      } else {
        toast.error(`${apiSettings[apiKey]?.name || apiKey}: ${response.data.message}`);
      }
    } catch (error) {
      toast.error(`Failed to test API: ${error.response?.data?.detail || error.message}`);
    } finally {
      setTestingApi(null);
    }
  };

  const handleAddCustomApi = async () => {
    if (!newApiData.key || !newApiData.name || !newApiData.endpoint) {
      toast.error("Please fill in key, name, and endpoint");
      return;
    }
    
    try {
      const response = await axios.post(
        `${API}/admin/api-settings`,
        newApiData,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(prev => ({
        ...prev,
        [newApiData.key]: response.data.setting
      }));
      setAddApiDialogOpen(false);
      setNewApiData({
        key: "",
        name: "",
        enabled: true,
        api_key: "",
        endpoint: "",
        priority: 10,
        description: ""
      });
      toast.success("Custom API added successfully");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to add custom API");
    }
  };

  const handleDeleteCustomApi = async (apiKey) => {
    if (!window.confirm(`Are you sure you want to delete ${apiSettings[apiKey]?.name || apiKey}?`)) return;
    
    try {
      await axios.delete(
        `${API}/admin/api-settings/${apiKey}`,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(prev => {
        const newSettings = { ...prev };
        delete newSettings[apiKey];
        return newSettings;
      });
      toast.success("Custom API deleted");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to delete API");
    }
  };

  const handleResetApiSettings = async () => {
    if (!window.confirm("Are you sure you want to reset API settings to default?")) return;
    
    try {
      const response = await axios.post(
        `${API}/admin/api-settings/reset`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiSettings(response.data.settings);
      toast.success("API settings reset to default");
    } catch (error) {
      toast.error("Failed to reset API settings");
    }
  };

  const handleClearRateLimits = async () => {
    try {
      const response = await axios.post(
        `${API}/admin/api-settings/clear-rate-limits`,
        {},
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      // Refresh API status
      const statusResponse = await axios.get(
        `${API}/admin/api-settings/status`,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiStatus(statusResponse.data);
      toast.success(response.data.message);
    } catch (error) {
      toast.error("Failed to clear rate limits");
    }
  };

  const refreshApiStatus = async () => {
    try {
      const response = await axios.get(
        `${API}/admin/api-settings/status`,
        { headers: { Authorization: `Bearer ${getAdminToken()}` } }
      );
      setApiStatus(response.data);
    } catch (error) {
      console.error("Failed to refresh API status");
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case "active":
        return <Badge className="bg-[#22C55E]">Active</Badge>;
      case "blocked":
        return <Badge className="bg-[#EF4444]">Blocked</Badge>;
      default:
        return <Badge className="bg-[#F59E0B]">Pending</Badge>;
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--brand-card)] flex items-center justify-center">
        <div className="text-white">Loading admin panel...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--brand-card)]" data-testid="admin-dashboard">
      {/* Header */}
      <header className="border-b border-[var(--brand-border)] bg-[var(--brand-card)]/95 backdrop-blur sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Shield className="w-8 h-8 text-[#EF4444] shrink-0" />
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-white truncate">Krexion Admin</h1>
              <p className="text-xs text-[#A1A1AA] hidden sm:block">System Administration</p>
            </div>
          </div>

          {/* Desktop action buttons */}
          <div className="hidden lg:flex items-center gap-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/crypto-orders"}
              data-testid="goto-crypto-orders-btn"
              className="border-[#A78BFA]/40 text-[#A78BFA] hover:bg-[#A78BFA]/10"
            >
              <DollarSign size={16} className="mr-2" />
              Crypto Orders
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/releases"}
              data-testid="goto-releases-btn"
              className="border-[#A78BFA]/40 text-[#A78BFA] hover:bg-[#A78BFA]/10"
            >
              <Settings size={16} className="mr-2" />
              Releases
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/plans"}
              data-testid="goto-plans-btn"
              className="border-pink-500/40 text-pink-400 hover:bg-pink-500/10"
            >
              <DollarSign size={16} className="mr-2" />
              Pricing &amp; Discounts
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/sync-heartbeats"}
              data-testid="goto-sync-heartbeats-btn"
              className="border-[var(--brand-border)]"
            >
              <RefreshCw size={16} className="mr-2" />
              Customer Installs
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/system-maintenance"}
              data-testid="goto-system-maintenance-btn"
              className="border-yellow-500/40 text-yellow-400 hover:bg-yellow-500/10"
            >
              <Trash2 size={16} className="mr-2" />
              VPS Cleanup
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open("/?edit=1", "_blank")}
              data-testid="goto-website-content-btn"
              className="border-blue-500/40 text-blue-400 hover:bg-blue-500/10"
            >
              <Palette size={16} className="mr-2" />
              Edit Website
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/banners"}
              data-testid="goto-banners-btn"
              className="border-fuchsia-500/40 text-fuchsia-400 hover:bg-fuchsia-500/10"
            >
              <Palette size={16} className="mr-2" />
              Banners
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = "/admin/licenses"}
              data-testid="goto-licenses-btn"
              className="border-[var(--brand-border)]"
            >
              <Settings size={16} className="mr-2" />
              Licenses &amp; Pricing
            </Button>
            <Button variant="outline" size="sm" onClick={fetchData} className="border-[var(--brand-border)]">
              <RefreshCw size={16} className="mr-2" />
              Refresh
            </Button>
            <Button variant="destructive" size="sm" onClick={handleLogout}>
              <LogOut size={16} className="mr-2" />
              Logout
            </Button>
          </div>

          {/* Mobile/tablet: collapsed dropdown menu */}
          <div className="lg:hidden flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={fetchData} className="border-[var(--brand-border)] px-2" data-testid="admin-refresh-mobile">
              <RefreshCw size={16} />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="border-[var(--brand-border)] px-2" data-testid="admin-menu-mobile">
                  <Menu size={18} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem onClick={() => window.location.href = "/admin/crypto-orders"} data-testid="mobile-goto-crypto-orders">
                  <DollarSign size={16} className="mr-2 text-[#A78BFA]" />
                  Crypto Orders
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => window.location.href = "/admin/releases"} data-testid="mobile-goto-releases">
                  <Settings size={16} className="mr-2 text-[#A78BFA]" />
                  Releases
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => window.location.href = "/admin/plans"} data-testid="mobile-goto-plans">
                  <DollarSign size={16} className="mr-2 text-pink-400" />
                  Pricing &amp; Discounts
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => window.location.href = "/admin/sync-heartbeats"} data-testid="mobile-goto-sync-heartbeats">
                  <RefreshCw size={16} className="mr-2" />
                  Customer Installs
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => window.location.href = "/admin/system-maintenance"} data-testid="mobile-goto-system-maintenance">
                  <Trash2 size={16} className="mr-2 text-yellow-400" />
                  VPS Cleanup
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => window.open("/?edit=1", "_blank")} data-testid="mobile-goto-website-content">
                  <Palette size={16} className="mr-2 text-blue-400" />
                  Edit Website
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => window.location.href = "/admin/licenses"} data-testid="mobile-goto-licenses">
                  <Settings size={16} className="mr-2" />
                  Licenses & Pricing
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleLogout} className="text-[#EF4444] focus:text-[#EF4444]" data-testid="mobile-admin-logout">
                  <LogOut size={16} className="mr-2" />
                  Logout
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8 space-y-8">
        {/* Heavy-Features Protection Badge — shows VPS load-protection status */}
        {heavyStatus && (
          (() => {
            const dep = heavyStatus.deployment || {};
            const b = heavyStatus.bridge_24h || {};
            const pcs = heavyStatus.customer_pcs || {};
            const protectedMode = dep.protected;
            const localInstall = !dep.is_cloud;
            const accent = protectedMode
              ? { bg: "from-[#022c22] to-[#064e3b]", border: "border-[#10B981]/40", iconBg: "bg-[#10B981]/15", iconColor: "text-[#34D399]", chipBg: "bg-[#10B981]/15 text-[#34D399] border-[#10B981]/30" }
              : localInstall
              ? { bg: "from-[#0c1326] to-[#11203f]", border: "border-[#3B82F6]/40", iconBg: "bg-[#3B82F6]/15", iconColor: "text-[#60A5FA]", chipBg: "bg-[#3B82F6]/15 text-[#60A5FA] border-[#3B82F6]/30" }
              : { bg: "from-[#2a1a05] to-[#3d2607]", border: "border-[#F59E0B]/40", iconBg: "bg-[#F59E0B]/15", iconColor: "text-[#FBBF24]", chipBg: "bg-[#F59E0B]/15 text-[#FBBF24] border-[#F59E0B]/30" };
            const topFeatures = Object.entries(b.by_feature || {}).slice(0, 3);
            return (
              <Card
                data-testid="heavy-features-status-banner"
                className={`bg-gradient-to-br ${accent.bg} ${accent.border} border-2`}
              >
                <CardContent className="p-5 md:p-6">
                  <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
                    {/* Left: status label */}
                    <div className="flex items-start gap-4">
                      <div className={`w-12 h-12 rounded-xl ${accent.iconBg} flex items-center justify-center shrink-0`}>
                        <ShieldCheck className={`w-6 h-6 ${accent.iconColor}`} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="text-lg font-semibold text-white" data-testid="heavy-status-title">
                            {protectedMode
                              ? "VPS Protected"
                              : localInstall
                              ? "Local Install"
                              : "Cloud Edge — Strict Block Disabled"}
                          </h3>
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${accent.chipBg}`}>
                            {dep.mode ? dep.mode.toUpperCase() : "—"}
                          </span>
                          {dep.is_cloud && (
                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${accent.chipBg}`}>
                              STRICT {dep.strict_heavy_block ? "ON" : "OFF"}
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-[#A1A1AA] mt-1 max-w-2xl" data-testid="heavy-status-note">
                          {dep.note || ""}
                        </p>
                        {dep.is_cloud && (
                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={toggleStrictMode}
                              disabled={togglingStrict}
                              className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
                                dep.strict_heavy_block
                                  ? "bg-yellow-600 hover:bg-yellow-500 text-black"
                                  : "bg-emerald-600 hover:bg-emerald-500 text-white"
                              } ${togglingStrict ? "opacity-50 cursor-not-allowed" : ""}`}
                              data-testid="admin-strict-mode-toggle"
                            >
                              {togglingStrict
                                ? "Updating…"
                                : dep.strict_heavy_block
                                ? "Strict ON — click to turn OFF"
                                : "Strict OFF — click to turn ON"}
                            </button>
                            <span className="text-[11px] text-[#71717A]">
                              Instant — no VPS restart needed
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Right: live counters */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 lg:gap-4 shrink-0">
                      <div className="text-center px-3 py-2 rounded-lg bg-black/30 border border-white/5">
                        <p className="text-2xl font-bold text-white leading-tight" data-testid="heavy-routed-24h">
                          {b.done || 0}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-[#A1A1AA] mt-1">
                          Routed to PCs<br/>(24h)
                        </p>
                      </div>
                      <div className="text-center px-3 py-2 rounded-lg bg-black/30 border border-white/5">
                        <p className="text-2xl font-bold text-white leading-tight" data-testid="heavy-total-24h">
                          {b.total || 0}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-[#A1A1AA] mt-1">
                          Total Bridge<br/>Jobs (24h)
                        </p>
                      </div>
                      <div className="text-center px-3 py-2 rounded-lg bg-black/30 border border-white/5">
                        <p className="text-2xl font-bold text-white leading-tight" data-testid="heavy-pcs-online">
                          {pcs.online_now || 0}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-[#A1A1AA] mt-1 flex items-center justify-center gap-1">
                          <Cpu className="w-3 h-3" /> PCs Online<br/>Now
                        </p>
                      </div>
                      <div className="text-center px-3 py-2 rounded-lg bg-black/30 border border-white/5">
                        <p className="text-2xl font-bold text-white leading-tight" data-testid="heavy-pcs-active-24h">
                          {pcs.active_24h || 0}
                        </p>
                        <p className="text-[10px] uppercase tracking-wide text-[#A1A1AA] mt-1">
                          PCs Active<br/>(24h)
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Per-feature breakdown (top 3) */}
                  {topFeatures.length > 0 && (
                    <div className="mt-4 pt-4 border-t border-white/5 flex flex-wrap items-center gap-2">
                      <span className="text-xs text-[#A1A1AA] mr-1">Top features routed:</span>
                      {topFeatures.map(([feat, n]) => (
                        <span
                          key={feat}
                          className="px-2.5 py-1 rounded-md bg-black/30 border border-white/10 text-xs text-white font-mono"
                          data-testid={`heavy-feature-${feat.replace(/\//g, "-")}`}
                        >
                          {feat} <span className="text-[#34D399] font-bold">×{n}</span>
                        </span>
                      ))}
                      {b.pending > 0 && (
                        <span className="px-2.5 py-1 rounded-md bg-[#F59E0B]/15 border border-[#F59E0B]/30 text-xs text-[#FBBF24]" data-testid="heavy-pending-count">
                          {b.pending} pending
                        </span>
                      )}
                      {b.failed > 0 && (
                        <span className="px-2.5 py-1 rounded-md bg-[#EF4444]/15 border border-[#EF4444]/30 text-xs text-[#F87171]" data-testid="heavy-failed-count">
                          {b.failed} failed
                        </span>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })()
        )}

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Total Users</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_users || 0}</p>
                </div>
                <Users className="w-10 h-10 text-[#3B82F6]" />
              </div>
              <div className="mt-2 flex gap-2 text-xs">
                <span className="text-[#22C55E]">{stats?.active_users || 0} active</span>
                <span className="text-[#F59E0B]">{stats?.pending_users || 0} pending</span>
                <span className="text-[#EF4444]">{stats?.blocked_users || 0} blocked</span>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Sub-Users</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_sub_users || 0}</p>
                </div>
                <UserPlus className="w-10 h-10 text-[#8B5CF6]" />
              </div>
              <div className="mt-2 text-xs text-[#A1A1AA]">
                {stats?.users_with_sub_users || 0} users with sub-accounts
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Total Links</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_links || 0}</p>
                </div>
                <Link2 className="w-10 h-10 text-[#8B5CF6]" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Total Clicks</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_clicks?.toLocaleString() || 0}</p>
                </div>
                <MousePointer className="w-10 h-10 text-[#22C55E]" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-[#A1A1AA]">Conversions</p>
                  <p className="text-3xl font-bold text-white">{stats?.total_conversions || 0}</p>
                </div>
                <DollarSign className="w-10 h-10 text-[#F59E0B]" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Tabs for Users, Sub-Users, Branding and API Settings */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="bg-[var(--brand-card)] border border-[var(--brand-border)] p-1 w-full overflow-x-auto flex justify-start no-scrollbar">
            <TabsTrigger 
              value="users" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="users-tab"
            >
              <Users size={16} className="mr-2" />
              User Management
            </TabsTrigger>
            <TabsTrigger 
              value="subusers" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="subusers-tab"
            >
              <UserPlus size={16} className="mr-2" />
              Sub-Users ({stats?.total_sub_users || 0})
            </TabsTrigger>
            <TabsTrigger 
              value="branding" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="branding-tab"
            >
              <Palette size={16} className="mr-2" />
              Branding
            </TabsTrigger>
            <TabsTrigger 
              value="api-settings" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="api-settings-tab"
            >
              <Key size={16} className="mr-2" />
              API Settings
            </TabsTrigger>
            <TabsTrigger 
              value="email-settings" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="email-settings-tab"
            >
              <Mail size={16} className="mr-2" />
              Email
            </TabsTrigger>
            <TabsTrigger 
              value="ip-isolation" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="ip-isolation-tab"
            >
              <ShieldCheck size={16} className="mr-2" />
              IP Isolation
            </TabsTrigger>
            <TabsTrigger 
              value="admin-settings" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="admin-settings-tab"
            >
              <Lock size={16} className="mr-2" />
              Admin Settings
            </TabsTrigger>
            <TabsTrigger 
              value="system" 
              className="data-[state=active]:bg-[#27272A] data-[state=active]:text-white"
              data-testid="system-tab"
            >
              <Activity size={16} className="mr-2" />
              System Check
            </TabsTrigger>
          </TabsList>

          <TabsContent value="users" className="mt-6">
        {/* User Management */}
        <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
          <CardHeader>
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <CardTitle className="text-white">User Management</CardTitle>
                <CardDescription>Manage all registered users, their access and subscriptions</CardDescription>
              </div>
              <div className="flex items-center gap-4">
                {selectedUsers.length > 0 && (
                  <Button 
                    variant="destructive" 
                    size="sm" 
                    onClick={handleBulkDeleteUsers}
                    data-testid="bulk-delete-users-button"
                  >
                    <Trash2 size={16} className="mr-2" />
                    Delete Selected ({selectedUsers.length})
                  </Button>
                )}
                <div className="relative w-64">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A1A1AA]" />
                  <Input
                    placeholder="Search users..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="pl-10 bg-[var(--brand-card)] border-[var(--brand-border)]"
                    data-testid="search-users-input"
                  />
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                    <TableHead className="w-12">
                      <input
                        type="checkbox"
                        checked={filteredUsers.length > 0 && selectedUsers.length === filteredUsers.length}
                        onChange={toggleSelectAll}
                        className="w-4 h-4 cursor-pointer"
                        data-testid="select-all-users"
                      />
                    </TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Stats</TableHead>
                    <TableHead>Features</TableHead>
                    <TableHead>Sub-Users</TableHead>
                    <TableHead>Registered</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredUsers.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center text-[#A1A1AA] py-8">
                        No users found
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredUsers.map((user) => (
                      <TableRow key={user.id} className="border-[var(--brand-border)]" data-testid={`user-row-${user.id}`}>
                        <TableCell>
                          <input
                            type="checkbox"
                            checked={selectedUsers.includes(user.id)}
                            onChange={() => toggleSelectUser(user.id)}
                            className="w-4 h-4 cursor-pointer"
                            data-testid={`select-user-${user.id}`}
                          />
                        </TableCell>
                        <TableCell>
                          <div>
                            <p className="font-medium text-white">{user.name}</p>
                            <p className="text-sm text-[#A1A1AA]">{user.email}</p>
                          </div>
                        </TableCell>
                        <TableCell>{getStatusBadge(user.status)}</TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1 text-xs">
                            <div className="flex items-center gap-1">
                              <Link2 size={12} className="text-[#3B82F6]" />
                              <span className="text-[#A1A1AA]">{user.link_count || 0} links</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <MousePointer size={12} className="text-[#22C55E]" />
                              <span className="text-[#A1A1AA]">{(user.click_count || 0).toLocaleString()} clicks</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Server size={12} className="text-[#8B5CF6]" />
                              <span className="text-[#A1A1AA]">{user.proxy_count || 0} proxies</span>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 flex-wrap">
                            {user.features?.links && <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">Links</Badge>}
                            {user.features?.clicks && <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">Clicks</Badge>}
                            {user.features?.proxies && <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">Proxies</Badge>}
                            {user.features?.import_data && <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">Import</Badge>}
                            {user.features?.settings !== false && <Badge variant="outline" className="text-xs border-[#EC4899] text-[#EC4899]">Settings</Badge>}
                            {!user.features?.links && !user.features?.clicks && !user.features?.proxies && user.features?.settings === false && (
                              <span className="text-xs text-[#71717A]">No access</span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {user.sub_user_count > 0 ? (
                            <Badge className="bg-[#8B5CF6]">
                              <UserPlus size={12} className="mr-1" />
                              {user.sub_user_count}
                            </Badge>
                          ) : (
                            <span className="text-xs text-[#71717A]">None</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-[#A1A1AA]">
                          {format(new Date(user.created_at), "MMM dd, yyyy")}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            {user.status !== "active" && (
                              <Button 
                                size="sm" 
                                variant="outline"
                                className="border-[#22C55E] text-[#22C55E] hover:bg-[#22C55E]/10"
                                onClick={() => quickActivate(user.id)}
                                data-testid={`activate-user-${user.id}`}
                              >
                                <CheckCircle size={14} className="mr-1" />
                                Activate
                              </Button>
                            )}
                            {user.status !== "blocked" && (
                              <Button 
                                size="sm" 
                                variant="outline"
                                className="border-[#EF4444] text-[#EF4444] hover:bg-[#EF4444]/10"
                                onClick={() => quickBlock(user.id)}
                                data-testid={`block-user-${user.id}`}
                              >
                                <XCircle size={14} className="mr-1" />
                                Block
                              </Button>
                            )}
                            <Button 
                              size="sm" 
                              variant={user.allow_cloud_heavy ? "default" : "outline"}
                              className={user.allow_cloud_heavy 
                                ? "bg-[#F59E0B] hover:bg-[#D97706] text-black border-[#F59E0B] font-semibold" 
                                : "border-[var(--brand-border)] text-[#94A3B8] hover:bg-white/5"}
                              onClick={() => toggleCloudHeavy(user)}
                              data-testid={`cloud-heavy-user-${user.id}`}
                              title={user.allow_cloud_heavy 
                                ? "VPS Heavy ON — click to turn OFF" 
                                : "VPS Heavy OFF — click to allow heavy features on VPS"}
                            >
                              {user.allow_cloud_heavy ? (
                                <CheckCircle size={14} className="mr-1" />
                              ) : (
                                <Cloud size={14} className="mr-1" />
                              )}
                              {user.allow_cloud_heavy ? "VPS Heavy ON" : "VPS Heavy OFF"}
                            </Button>
                            <Button 
                              size="sm" 
                              variant="outline"
                              className="border-[var(--brand-border)]"
                              onClick={() => openEditDialog(user)}
                              data-testid={`edit-user-${user.id}`}
                            >
                              <Settings size={14} className="mr-1" />
                              Edit
                            </Button>
                            <Button 
                              size="sm" 
                              variant="destructive"
                              onClick={() => handleDeleteUser(user.id, user.name)}
                              data-testid={`delete-user-${user.id}`}
                            >
                              <Trash2 size={14} />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
          </TabsContent>

          {/* Sub-Users Tab */}
          <TabsContent value="subusers" className="mt-6">
            <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <CardHeader>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <UserPlus className="w-5 h-5 text-[#8B5CF6]" />
                      Sub-User Management
                    </CardTitle>
                    <CardDescription>View and manage all sub-users across all main users</CardDescription>
                  </div>
                  <div className="relative w-64">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A1A1AA]" />
                    <Input
                      placeholder="Search sub-users..."
                      value={subUserSearchTerm}
                      onChange={(e) => setSubUserSearchTerm(e.target.value)}
                      className="pl-10 bg-[var(--brand-card)] border-[var(--brand-border)]"
                      data-testid="search-subusers-input"
                    />
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                        <TableHead>Sub-User</TableHead>
                        <TableHead>Parent User</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Permissions</TableHead>
                        <TableHead>Last Active</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead>Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredSubUsers.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={7} className="text-center text-[#A1A1AA] py-8">
                            No sub-users found
                          </TableCell>
                        </TableRow>
                      ) : (
                        filteredSubUsers.map((subUser) => (
                          <TableRow key={subUser.id} className="border-[var(--brand-border)]" data-testid={`subuser-row-${subUser.id}`}>
                            <TableCell>
                              <div>
                                <p className="font-medium text-white">{subUser.name}</p>
                                <p className="text-sm text-[#A1A1AA]">{subUser.email}</p>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div>
                                <p className="font-medium text-white">{subUser.parent_name}</p>
                                <p className="text-sm text-[#A1A1AA]">{subUser.parent_email}</p>
                              </div>
                            </TableCell>
                            <TableCell>
                              {subUser.is_active !== false ? (
                                <Badge className="bg-[#22C55E]">Active</Badge>
                              ) : (
                                <Badge className="bg-[#EF4444]">Inactive</Badge>
                              )}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-1 flex-wrap">
                                {subUser.permissions?.view_links && <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">Links</Badge>}
                                {subUser.permissions?.view_clicks && <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">Clicks</Badge>}
                                {subUser.permissions?.view_proxies && <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">Proxies</Badge>}
                                {subUser.permissions?.edit && <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">Edit</Badge>}
                              </div>
                            </TableCell>
                            <TableCell className="text-sm text-[#A1A1AA]">
                              {subUser.last_active ? format(new Date(subUser.last_active), "MMM dd, HH:mm") : "Never"}
                            </TableCell>
                            <TableCell className="text-sm text-[#A1A1AA]">
                              {format(new Date(subUser.created_at), "MMM dd, yyyy")}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-2">
                                <Button 
                                  size="sm" 
                                  variant="outline"
                                  className="border-[var(--brand-border)]"
                                  onClick={() => openEditSubUserDialog(subUser)}
                                  data-testid={`edit-subuser-${subUser.id}`}
                                >
                                  <Settings size={14} className="mr-1" />
                                  Edit
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
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Branding Tab */}
          <TabsContent value="branding" className="mt-6">
            <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <Palette className="w-5 h-5 text-[#3B82F6]" />
                      Branding Settings
                    </CardTitle>
                    <CardDescription>Customize your application's appearance and branding</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      onClick={handleResetBranding}
                      className="border-[var(--brand-border)]"
                      data-testid="reset-branding-btn"
                    >
                      <RotateCcw size={16} className="mr-2" />
                      Reset to Default
                    </Button>
                    <Button 
                      onClick={handleSaveBranding}
                      disabled={brandingSaving}
                      className="bg-[#3B82F6]"
                      data-testid="save-branding-btn"
                    >
                      <Save size={16} className="mr-2" />
                      {brandingSaving ? "Saving..." : "Save Changes"}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-8">
                {/* Basic Info */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Type size={18} />
                    Basic Information
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="app_name">App Name</Label>
                      <Input
                        id="app_name"
                        value={branding.app_name}
                        onChange={(e) => handleBrandingChange("app_name", e.target.value)}
                        placeholder="Krexion"
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-app-name"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="tagline">Tagline</Label>
                      <Input
                        id="tagline"
                        value={branding.tagline}
                        onChange={(e) => handleBrandingChange("tagline", e.target.value)}
                        placeholder="Traffic Tracking & Link Management"
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-tagline"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="admin_email">Admin Contact Email</Label>
                      <Input
                        id="admin_email"
                        type="email"
                        value={branding.admin_email}
                        onChange={(e) => handleBrandingChange("admin_email", e.target.value)}
                        placeholder="admin@example.com"
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-admin-email"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="footer_text">Footer Text</Label>
                      <Input
                        id="footer_text"
                        value={branding.footer_text}
                        onChange={(e) => handleBrandingChange("footer_text", e.target.value)}
                        placeholder="© 2026 Krexion. All rights reserved."
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-footer-text"
                      />
                    </div>
                  </div>
                </div>

                {/* Images */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Image size={18} />
                    Images & Media
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="logo_url">Logo URL</Label>
                      <Input
                        id="logo_url"
                        value={branding.logo_url}
                        onChange={(e) => handleBrandingChange("logo_url", e.target.value)}
                        placeholder="https://example.com/logo.png"
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-logo-url"
                      />
                      {branding.logo_url && (
                        <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)] mt-2">
                          <img 
                            src={branding.logo_url} 
                            alt="Logo Preview" 
                            className="max-h-16 object-contain"
                            onError={(e) => e.target.style.display = 'none'}
                          />
                        </div>
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="favicon_url">Favicon URL</Label>
                      <Input
                        id="favicon_url"
                        value={branding.favicon_url}
                        onChange={(e) => handleBrandingChange("favicon_url", e.target.value)}
                        placeholder="https://example.com/favicon.ico"
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-favicon-url"
                      />
                      {branding.favicon_url && (
                        <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)] mt-2 flex items-center gap-2">
                          <img 
                            src={branding.favicon_url} 
                            alt="Favicon Preview" 
                            className="w-8 h-8 object-contain"
                            onError={(e) => e.target.style.display = 'none'}
                          />
                          <span className="text-xs text-[#A1A1AA]">32x32 recommended</span>
                        </div>
                      )}
                    </div>
                    <div className="space-y-2 md:col-span-2">
                      <Label htmlFor="login_bg_url">Login Background Image URL</Label>
                      <Input
                        id="login_bg_url"
                        value={branding.login_bg_url}
                        onChange={(e) => handleBrandingChange("login_bg_url", e.target.value)}
                        placeholder="https://example.com/background.jpg"
                        className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                        data-testid="branding-login-bg"
                      />
                      {branding.login_bg_url && (
                        <div className="mt-2 rounded-lg overflow-hidden border border-[var(--brand-border)]">
                          <img 
                            src={branding.login_bg_url} 
                            alt="Background Preview" 
                            className="w-full h-32 object-cover"
                            onError={(e) => e.target.style.display = 'none'}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Colors */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Palette size={18} />
                    Color Scheme
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="primary_color">Primary</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="primary_color"
                          value={branding.primary_color}
                          onChange={(e) => handleBrandingChange("primary_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                          data-testid="branding-primary-color"
                        />
                        <Input
                          value={branding.primary_color}
                          onChange={(e) => handleBrandingChange("primary_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="secondary_color">Secondary</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="secondary_color"
                          value={branding.secondary_color}
                          onChange={(e) => handleBrandingChange("secondary_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                          data-testid="branding-secondary-color"
                        />
                        <Input
                          value={branding.secondary_color}
                          onChange={(e) => handleBrandingChange("secondary_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="accent_color">Accent</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="accent_color"
                          value={branding.accent_color || "#8B5CF6"}
                          onChange={(e) => handleBrandingChange("accent_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                        />
                        <Input
                          value={branding.accent_color || "#8B5CF6"}
                          onChange={(e) => handleBrandingChange("accent_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="danger_color">Danger</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="danger_color"
                          value={branding.danger_color || "#EF4444"}
                          onChange={(e) => handleBrandingChange("danger_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                        />
                        <Input
                          value={branding.danger_color || "#EF4444"}
                          onChange={(e) => handleBrandingChange("danger_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="warning_color">Warning</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="warning_color"
                          value={branding.warning_color || "#F59E0B"}
                          onChange={(e) => handleBrandingChange("warning_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                        />
                        <Input
                          value={branding.warning_color || "#F59E0B"}
                          onChange={(e) => handleBrandingChange("warning_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="success_color">Success</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="success_color"
                          value={branding.success_color || "#22C55E"}
                          onChange={(e) => handleBrandingChange("success_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                        />
                        <Input
                          value={branding.success_color || "#22C55E"}
                          onChange={(e) => handleBrandingChange("success_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="background_color">Background</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="background_color"
                          value={branding.background_color || "#09090B"}
                          onChange={(e) => handleBrandingChange("background_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                        />
                        <Input
                          value={branding.background_color || "#09090B"}
                          onChange={(e) => handleBrandingChange("background_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="card_color">Card</Label>
                      <div className="flex gap-2">
                        <input
                          type="color"
                          id="card_color"
                          value={branding.card_color || "#18181B"}
                          onChange={(e) => handleBrandingChange("card_color", e.target.value)}
                          className="w-10 h-10 rounded cursor-pointer border border-[var(--brand-border)] bg-transparent"
                        />
                        <Input
                          value={branding.card_color || "#18181B"}
                          onChange={(e) => handleBrandingChange("card_color", e.target.value)}
                          className="bg-[var(--brand-card)] border-[var(--brand-border)] flex-1 text-xs"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Interface Settings */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white flex items-center gap-2">
                    <Settings size={18} />
                    Interface Settings
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="sidebar_style">Sidebar Style</Label>
                      <Select
                        value={branding.sidebar_style || "dark"}
                        onValueChange={(value) => handleBrandingChange("sidebar_style", value)}
                      >
                        <SelectTrigger className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                          <SelectValue placeholder="Select style" />
                        </SelectTrigger>
                        <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                          <SelectItem value="dark">Dark</SelectItem>
                          <SelectItem value="light">Light</SelectItem>
                          <SelectItem value="gradient">Gradient</SelectItem>
                          <SelectItem value="transparent">Transparent</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="button_style">Button Style</Label>
                      <Select
                        value={branding.button_style || "rounded"}
                        onValueChange={(value) => handleBrandingChange("button_style", value)}
                      >
                        <SelectTrigger className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                          <SelectValue placeholder="Select style" />
                        </SelectTrigger>
                        <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                          <SelectItem value="rounded">Rounded</SelectItem>
                          <SelectItem value="square">Square</SelectItem>
                          <SelectItem value="pill">Pill</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="font_family">Font Family</Label>
                      <Select
                        value={branding.font_family || "Inter"}
                        onValueChange={(value) => handleBrandingChange("font_family", value)}
                      >
                        <SelectTrigger className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                          <SelectValue placeholder="Select font" />
                        </SelectTrigger>
                        <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                          <SelectItem value="Inter">Inter</SelectItem>
                          <SelectItem value="Roboto">Roboto</SelectItem>
                          <SelectItem value="Poppins">Poppins</SelectItem>
                          <SelectItem value="Open Sans">Open Sans</SelectItem>
                          <SelectItem value="Montserrat">Montserrat</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>

                {/* Preview */}
                <div className="space-y-4">
                  <h3 className="text-lg font-medium text-white">Preview</h3>
                  <div className="p-6 rounded-lg border border-[var(--brand-border)] bg-[var(--brand-card)]">
                    <div className="flex items-center gap-3 mb-4">
                      {branding.logo_url ? (
                        <img src={branding.logo_url} alt="Logo" className="h-10 object-contain" />
                      ) : (
                        <div 
                          className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold"
                          style={{ backgroundColor: branding.primary_color }}
                        >
                          {branding.app_name?.charAt(0) || "T"}
                        </div>
                      )}
                      <div>
                        <h4 className="font-bold text-white">{branding.app_name || "Krexion"}</h4>
                        <p className="text-xs text-[#A1A1AA]">{branding.tagline || "Traffic Tracking"}</p>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button 
                        size="sm" 
                        style={{ backgroundColor: branding.primary_color }}
                        className="text-white"
                      >
                        Primary Button
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline"
                        style={{ borderColor: branding.secondary_color, color: branding.secondary_color }}
                      >
                        Secondary Button
                      </Button>
                    </div>
                    <p className="text-xs text-[#52525B] mt-4">{branding.footer_text || "© 2026 Krexion. All rights reserved."}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* API Settings Tab */}
          <TabsContent value="api-settings" className="mt-6">
            <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <CardHeader>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <Key className="w-5 h-5" />
                      API Settings
                    </CardTitle>
                    <CardDescription>Manage VPN detection and geolocation API services</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      onClick={refreshApiStatus}
                      className="border-[var(--brand-border)]"
                    >
                      <RefreshCw size={16} className="mr-2" />
                      Refresh Status
                    </Button>
                    <Button 
                      variant="outline" 
                      onClick={handleResetApiSettings}
                      className="border-[var(--brand-border)]"
                    >
                      <RotateCcw size={16} className="mr-2" />
                      Reset to Default
                    </Button>
                    <Button 
                      onClick={() => setAddApiDialogOpen(true)}
                      className="bg-[#3B82F6] hover:bg-[#2563EB]"
                    >
                      <Plus size={16} className="mr-2" />
                      Add Custom API
                    </Button>
                  </div>
                </div>
                
                {/* API Status Summary */}
                {apiStatus && (
                  <div className="mt-4 p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                    <div className="flex items-center justify-between flex-wrap gap-4">
                      <div className="flex items-center gap-6 flex-wrap">
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">Enabled: </span>
                          <span className="text-[#22C55E] font-semibold">{apiStatus.total_enabled}</span>
                        </div>
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">Rate Limited: </span>
                          <span className={`font-semibold ${apiStatus.total_rate_limited > 0 ? 'text-[#F59E0B]' : 'text-[#22C55E]'}`}>
                            {apiStatus.total_rate_limited}
                          </span>
                        </div>
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">At Limit: </span>
                          <span className={`font-semibold ${apiStatus.total_limit_reached > 0 ? 'text-[#EF4444]' : 'text-[#22C55E]'}`}>
                            {apiStatus.total_limit_reached || 0}
                          </span>
                        </div>
                        <div className="text-sm">
                          <span className="text-[#A1A1AA]">Today's Usage: </span>
                          <span className="text-white font-semibold">
                            {apiStatus.total_used_today?.toLocaleString() || 0} / {apiStatus.total_limit_today?.toLocaleString() || 0}
                          </span>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        {apiStatus.total_rate_limited > 0 && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleClearRateLimits}
                            className="border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B] hover:text-black"
                          >
                            Clear Rate Limits
                          </Button>
                        )}
                      </div>
                    </div>
                    {/* Total usage progress bar */}
                    {apiStatus.total_limit_today > 0 && (
                      <div className="mt-3">
                        <div className="h-2 bg-[#27272A] rounded-full overflow-hidden">
                          <div 
                            className={`h-full transition-all ${
                              (apiStatus.total_used_today / apiStatus.total_limit_today) > 0.9 ? 'bg-[#EF4444]' :
                              (apiStatus.total_used_today / apiStatus.total_limit_today) > 0.7 ? 'bg-[#F59E0B]' : 'bg-[#22C55E]'
                            }`}
                            style={{ width: `${Math.min(100, (apiStatus.total_used_today / apiStatus.total_limit_today) * 100)}%` }}
                          />
                        </div>
                        <p className="text-xs text-[#52525B] mt-1">
                          {apiStatus.date} • Auto-resets at midnight UTC
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {Object.entries(apiSettings).sort((a, b) => (a[1].priority || 99) - (b[1].priority || 99)).map(([apiKey, config]) => {
                    const statusInfo = apiStatus?.apis?.find(a => a.key === apiKey);
                    const isRateLimited = statusInfo?.rate_limited || false;
                    const isLimitReached = statusInfo?.limit_reached || false;
                    const usagePercent = statusInfo?.usage_percent || 0;
                    const tier = config.tier || (config.is_custom ? "custom" : "free");
                    const isPaidTier = tier === "paid";
                    const hasApiKey = !!(config.api_key && String(config.api_key).trim());
                    const isAutoDisabled = !!config.auto_disabled_by;
                    
                    return (
                    <div 
                      key={apiKey} 
                      data-testid={`api-card-${apiKey}`}
                      className={`p-4 rounded-lg border ${
                        isLimitReached ? 'bg-[#1a0808] border-[#EF4444]/30' :
                        isRateLimited ? 'bg-[#1a1408] border-[#F59E0B]/30' : 
                        config.enabled ? 'bg-[var(--brand-card)] border-[var(--brand-border)]' : 'bg-[#0a0a0a] border-[#1a1a1a]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1">
                          <div className="flex items-center gap-3 mb-2 flex-wrap">
                            <Globe className={`w-5 h-5 ${
                              isLimitReached ? 'text-[#EF4444]' :
                              isRateLimited ? 'text-[#F59E0B]' : 
                              config.enabled ? 'text-[#22C55E]' : 'text-[#52525B]'
                            }`} />
                            <h3 className="font-semibold text-white">{config.name}</h3>
                            {config.is_custom ? (
                              <Badge className="bg-[#8B5CF6] text-xs">Custom</Badge>
                            ) : isPaidTier ? (
                              <Badge className="bg-[#F59E0B] text-black text-xs font-semibold">PAID</Badge>
                            ) : (
                              <Badge className="bg-[#3B82F6] text-xs font-semibold">FREE</Badge>
                            )}
                            {isLimitReached ? (
                              <Badge className="bg-[#EF4444] text-xs">
                                Limit Reached
                              </Badge>
                            ) : isRateLimited ? (
                              <Badge className="bg-[#F59E0B] text-xs">
                                Rate Limited ({Math.ceil(statusInfo.rate_limit_resets_in / 60)}m)
                              </Badge>
                            ) : (
                              <Badge className={config.enabled ? 'bg-[#22C55E]' : 'bg-[#52525B]'}>
                                {config.enabled ? 'Enabled' : 'Disabled'}
                              </Badge>
                            )}
                            <span className="text-xs text-[#52525B]">Priority: {config.priority}</span>
                            {config.signup_url && (
                              <a
                                href={config.signup_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-[#3B82F6] hover:text-[#60A5FA] inline-flex items-center gap-1"
                                data-testid={`api-signup-${apiKey}`}
                              >
                                Get API key <ExternalLink size={11} />
                              </a>
                            )}
                          </div>

                          {isAutoDisabled && (
                            <div className="mb-3 p-2 rounded-md bg-[#1a1408] border border-[#F59E0B]/30 text-xs text-[#F59E0B]">
                              ⚠ Auto-disabled because <strong>{apiSettings[config.auto_disabled_by]?.name || config.auto_disabled_by}</strong> (paid) is active. Toggle this back on to re-enable.
                            </div>
                          )}
                          
                          {/* Usage Progress Bar */}
                          {config.enabled && statusInfo && (
                            <div className="mb-3">
                              <div className="flex justify-between text-xs mb-1">
                                <span className="text-[#A1A1AA]">
                                  Used: {statusInfo.used_today?.toLocaleString() || 0} / {statusInfo.daily_limit?.toLocaleString() || 0}
                                </span>
                                <span className={`font-medium ${
                                  usagePercent >= 100 ? 'text-[#EF4444]' :
                                  usagePercent >= 80 ? 'text-[#F59E0B]' : 'text-[#22C55E]'
                                }`}>
                                  {usagePercent}%
                                </span>
                              </div>
                              <div className="h-2 bg-[#27272A] rounded-full overflow-hidden">
                                <div 
                                  className={`h-full transition-all ${
                                    usagePercent >= 100 ? 'bg-[#EF4444]' :
                                    usagePercent >= 80 ? 'bg-[#F59E0B]' : 'bg-[#22C55E]'
                                  }`}
                                  style={{ width: `${Math.min(100, usagePercent)}%` }}
                                />
                              </div>
                              <p className="text-xs text-[#52525B] mt-1">
                                Remaining: {statusInfo.remaining?.toLocaleString() || 0} requests today
                              </p>
                            </div>
                          )}
                          
                          <p className="text-sm text-[#A1A1AA] mb-3 leading-relaxed">{config.description}</p>
                          {isPaidTier && !hasApiKey && (
                            <p className="text-xs text-[#F59E0B] mb-3">
                              ℹ This API requires an API key. Enter your key below to enable it (free APIs will auto-disable when enabled).
                            </p>
                          )}
                          {isPaidTier && hasApiKey && config.enabled && (
                            <p className="text-xs text-[#22C55E] mb-3">
                              ✓ Paid API active. Free-tier APIs have been auto-disabled to use your higher quota.
                            </p>
                          )}
                          {isLimitReached && (
                            <p className="text-xs text-[#EF4444] mb-3">
                              🚫 Daily limit reached! System will automatically use the next available API.
                            </p>
                          )}
                          {isRateLimited && !isLimitReached && (
                            <p className="text-xs text-[#F59E0B] mb-3">
                              ⚠️ API returned rate limit error. Will retry in {Math.ceil(statusInfo.rate_limit_resets_in / 60)} minutes.
                            </p>
                          )}
                          
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <Label className="text-xs text-[#71717A]">API Endpoint</Label>
                              <Input
                                value={config.endpoint || ""}
                                onChange={(e) => handleApiSettingChange(apiKey, "endpoint", e.target.value)}
                                className="bg-[var(--brand-card)] border-[var(--brand-border)] text-sm"
                                placeholder="API endpoint URL"
                                data-testid={`api-endpoint-${apiKey}`}
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-xs text-[#71717A]">
                                API Key {isPaidTier ? <span className="text-[#F59E0B]">(required)</span> : <span className="text-[#71717A]">(optional)</span>}
                              </Label>
                              <div className="relative">
                                <Input
                                  type={showApiKey[apiKey] ? "text" : "password"}
                                  value={config.api_key || ""}
                                  onChange={(e) => handleApiSettingChange(apiKey, "api_key", e.target.value)}
                                  className="bg-[var(--brand-card)] border-[var(--brand-border)] text-sm pr-10"
                                  placeholder={isPaidTier ? "Paste your API key here" : "Enter API key (optional)"}
                                  data-testid={`api-key-input-${apiKey}`}
                                />
                                <button
                                  type="button"
                                  onClick={() => setShowApiKey(prev => ({ ...prev, [apiKey]: !prev[apiKey] }))}
                                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                                >
                                  {showApiKey[apiKey] ? <EyeOff size={14} /> : <Eye size={14} />}
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                        
                        <div className="flex flex-col gap-2">
                          <Switch
                            checked={config.enabled}
                            onCheckedChange={(checked) => handleApiSettingChange(apiKey, "enabled", checked)}
                            data-testid={`api-toggle-${apiKey}`}
                          />
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleTestApi(apiKey)}
                            disabled={testingApi === apiKey}
                            className="border-[var(--brand-border)]"
                            data-testid={`api-test-${apiKey}`}
                          >
                            {testingApi === apiKey ? (
                              <RefreshCw size={14} className="animate-spin" />
                            ) : (
                              <TestTube size={14} />
                            )}
                          </Button>
                          {config.is_custom && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleDeleteCustomApi(apiKey)}
                              className="border-[#EF4444] text-[#EF4444] hover:bg-[#EF4444] hover:text-white"
                            >
                              <Trash2 size={14} />
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                  })}
                  
                  {Object.keys(apiSettings).length === 0 && (
                    <div className="text-center py-8 text-[#A1A1AA]">
                      No API settings configured. Click "Add Custom API" to add one.
                    </div>
                  )}
                </div>
                
                {/* Info Box: How priority + auto-fallback works */}
                <div className="mt-6 p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                  <h4 className="font-medium text-white mb-2 flex items-center gap-2">
                    <Activity size={16} className="text-[#3B82F6]" />
                    How VPN Detection Works (Auto-Fallback)
                  </h4>
                  <ol className="text-sm text-[#A1A1AA] list-decimal list-inside space-y-1">
                    <li>APIs are tried in <strong className="text-white">priority order</strong> (lowest number first).</li>
                    <li>If an API hits its <strong className="text-white">daily limit</strong>, it is skipped automatically — the next enabled API takes over so checking <em>never stops</em>.</li>
                    <li>If an API returns a <strong className="text-white">rate-limit error</strong>, it is paused for 1 hour then retried.</li>
                    <li>When you add a <strong className="text-[#F59E0B]">PAID</strong> API key and enable it, all <strong className="text-[#3B82F6]">FREE</strong> APIs are <em>auto-disabled</em> so your paid quota is used. Toggle them back on any time.</li>
                    <li>Disabled APIs are <strong className="text-white">never called</strong> — toggle is the master switch.</li>
                  </ol>
                </div>

                {/* Info Box: Step-by-step paid API setup */}
                <div className="mt-4 p-4 bg-[var(--brand-card)] rounded-lg border border-[#F59E0B]/30">
                  <h4 className="font-medium text-white mb-3 flex items-center gap-2">
                    <Key size={16} className="text-[#F59E0B]" />
                    How to add a Paid API (Step by Step)
                  </h4>
                  <ol className="text-sm text-[#A1A1AA] list-decimal list-inside space-y-2">
                    <li>Pick a provider above (ProxyCheck.io, IPQualityScore, Scamalytics, IPHub) and click its <strong className="text-[#3B82F6]">"Get API key"</strong> link to sign up on their website.</li>
                    <li>After signing up, copy your <strong className="text-white">API key</strong> from the provider's dashboard.</li>
                    <li>Paste the key into the <strong className="text-white">"API Key"</strong> input on the matching card above.</li>
                    <li>Flip the <strong className="text-white">toggle ON</strong> for that API. Free APIs will automatically be disabled and your paid quota will take over.</li>
                    <li>Click the <strong className="text-white">test button</strong> (🧪 icon) next to the toggle to confirm the key works.</li>
                    <li>Done — proxy checks will now use your paid API. If your paid quota ever runs out, re-enable any free API to use as a backup.</li>
                  </ol>
                  <div className="mt-3 pt-3 border-t border-[var(--brand-border)] text-xs text-[#71717A]">
                    💡 Tip: You can keep multiple paid APIs enabled at once — they will be tried in priority order so you get automatic fallback between paid services too.
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Email Settings tab ───────────────────────── */}
          <TabsContent value="email-settings" className="mt-6 space-y-6">
            <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <CardHeader>
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <div>
                    <CardTitle className="text-white flex items-center gap-2">
                      <Mail size={20} /> Email Settings
                    </CardTitle>
                    <CardDescription>
                      One-time setup. These credentials send notification emails (low-stock
                      alerts, password resets, etc.) for ALL users on this app — they do not
                      see or configure anything themselves.
                    </CardDescription>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setEmailHelpOpen((v) => !v)}
                    className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                    data-testid="email-help-toggle"
                  >
                    <AlertCircle size={16} className="mr-2" />
                    {emailHelpOpen ? "Hide setup guide" : "How to get keys"}
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Setup walkthrough — collapsed by default */}
                {emailHelpOpen && (
                  <div className="rounded-lg border border-blue-700/40 bg-blue-900/10 p-4 space-y-4 text-sm text-zinc-300">
                    <div>
                      <div className="text-blue-300 font-semibold mb-1">
                        Option 1 — Gmail (free, 5 min setup, recommended for &lt; 500 emails/day)
                      </div>
                      <ol className="list-decimal pl-5 space-y-1 text-zinc-400 text-[13px]">
                        <li>
                          Apni Gmail account mein <span className="text-zinc-200">2-Step Verification</span> on karen:{" "}
                          <a href="https://myaccount.google.com/security" target="_blank" rel="noopener noreferrer"
                             className="text-blue-300 hover:underline inline-flex items-center gap-1">
                            myaccount.google.com/security <ExternalLink size={11} />
                          </a>
                        </li>
                        <li>
                          Phir App Password generate karen:{" "}
                          <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer"
                             className="text-blue-300 hover:underline inline-flex items-center gap-1">
                            myaccount.google.com/apppasswords <ExternalLink size={11} />
                          </a>{" "}
                          → "App: Mail" → "Device: Other" → naam: "Krexion"
                        </li>
                        <li>16-character password copy karen (jaise <span className="font-mono text-zinc-200">abcd efgh ijkl mnop</span>)</li>
                        <li>Yahan provider <span className="text-zinc-200">Gmail</span> select karen, email + 16-char password paste karen, Save click karen</li>
                        <li>"Send test email" button se verify karen</li>
                      </ol>
                    </div>
                    <div className="border-t border-zinc-800 pt-3">
                      <div className="text-blue-300 font-semibold mb-1">
                        Option 2 — Resend (free 3,000 emails/month, custom domain support)
                      </div>
                      <ol className="list-decimal pl-5 space-y-1 text-zinc-400 text-[13px]">
                        <li>
                          Sign up:{" "}
                          <a href="https://resend.com/signup" target="_blank" rel="noopener noreferrer"
                             className="text-blue-300 hover:underline inline-flex items-center gap-1">
                            resend.com/signup <ExternalLink size={11} />
                          </a>
                        </li>
                        <li>
                          API key banayen:{" "}
                          <a href="https://resend.com/api-keys" target="_blank" rel="noopener noreferrer"
                             className="text-blue-300 hover:underline inline-flex items-center gap-1">
                            resend.com/api-keys <ExternalLink size={11} />
                          </a>{" "}
                          → "Create API Key" → naam: "Krexion", Permission: "Sending access"
                        </li>
                        <li>Apna domain verify karen ya default <span className="font-mono text-zinc-200">onboarding@resend.dev</span> use karen (testing ke liye)</li>
                        <li>Yahan provider <span className="text-zinc-200">Resend</span> select karen, API key + From-email paste karen, Save</li>
                        <li>"Send test email" se verify karen</li>
                      </ol>
                    </div>
                  </div>
                )}

                {/* Provider selector */}
                <div className="space-y-2">
                  <Label className="text-zinc-300">Email Provider</Label>
                  <Select
                    value={emailCfg.provider}
                    onValueChange={(v) => setEmailCfg({ ...emailCfg, provider: v })}
                  >
                    <SelectTrigger className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]" data-testid="email-provider-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                      <SelectItem value="disabled">Disabled (no emails sent)</SelectItem>
                      <SelectItem value="gmail">Gmail SMTP (recommended)</SelectItem>
                      <SelectItem value="resend">Resend API</SelectItem>
                      <SelectItem value="smtp">Custom SMTP server</SelectItem>
                    </SelectContent>
                  </Select>
                  <div className="text-xs text-zinc-500">
                    {emailCfg.provider === "disabled" && "Emails will only be logged. Switch to Gmail or Resend to actually send."}
                    {emailCfg.provider === "gmail" && "smtp.gmail.com:587 will be set automatically. Use a Gmail App Password (not your regular password)."}
                    {emailCfg.provider === "resend" && "Best for high-volume sending and custom domains."}
                    {emailCfg.provider === "smtp" && "Configure any SMTP server (SendGrid, Mailgun, AWS SES, etc.)."}
                  </div>
                </div>

                {/* Gmail / SMTP fields */}
                {(emailCfg.provider === "gmail" || emailCfg.provider === "smtp") && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {emailCfg.provider === "smtp" && (
                      <>
                        <div className="space-y-2">
                          <Label className="text-zinc-300">SMTP Host</Label>
                          <Input
                            value={emailCfg.smtp_host}
                            onChange={(e) => setEmailCfg({ ...emailCfg, smtp_host: e.target.value })}
                            placeholder="smtp.example.com"
                            className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]"
                            data-testid="email-smtp-host"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-zinc-300">SMTP Port</Label>
                          <Input
                            type="number"
                            value={emailCfg.smtp_port}
                            onChange={(e) => setEmailCfg({ ...emailCfg, smtp_port: e.target.value })}
                            placeholder="587"
                            className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]"
                            data-testid="email-smtp-port"
                          />
                        </div>
                      </>
                    )}
                    <div className="space-y-2 md:col-span-2">
                      <Label className="text-zinc-300">
                        {emailCfg.provider === "gmail" ? "Gmail address" : "SMTP user"}
                      </Label>
                      <Input
                        type="email"
                        value={emailCfg.smtp_user}
                        onChange={(e) => setEmailCfg({ ...emailCfg, smtp_user: e.target.value })}
                        placeholder={emailCfg.provider === "gmail" ? "alerts@gmail.com" : "user@example.com"}
                        className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]"
                        data-testid="email-smtp-user"
                      />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                      <Label className="text-zinc-300">
                        {emailCfg.provider === "gmail" ? "Gmail App Password (16 chars)" : "SMTP password"}
                        {emailCfg.smtp_password_set && (
                          <span className="ml-2 text-[10px] text-emerald-400">
                            ● already set: {emailCfg.smtp_password_preview}
                          </span>
                        )}
                      </Label>
                      <Input
                        type="password"
                        value={emailCfg.smtp_password}
                        onChange={(e) => setEmailCfg({ ...emailCfg, smtp_password: e.target.value })}
                        placeholder={emailCfg.smtp_password_set ? "Leave blank to keep saved value" : "abcd efgh ijkl mnop"}
                        className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)] font-mono"
                        data-testid="email-smtp-password"
                      />
                    </div>
                  </div>
                )}

                {/* Resend fields */}
                {emailCfg.provider === "resend" && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2 md:col-span-2">
                      <Label className="text-zinc-300">
                        Resend API Key
                        {emailCfg.resend_api_key_set && (
                          <span className="ml-2 text-[10px] text-emerald-400">
                            ● already set: {emailCfg.resend_api_key_preview}
                          </span>
                        )}
                      </Label>
                      <Input
                        type="password"
                        value={emailCfg.resend_api_key}
                        onChange={(e) => setEmailCfg({ ...emailCfg, resend_api_key: e.target.value })}
                        placeholder={emailCfg.resend_api_key_set ? "Leave blank to keep saved value" : "re_xxxxxxxxxxxxxxxxxxxxxxxx"}
                        className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)] font-mono"
                        data-testid="email-resend-key"
                      />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                      <Label className="text-zinc-300">From email address</Label>
                      <Input
                        type="email"
                        value={emailCfg.resend_from}
                        onChange={(e) => setEmailCfg({ ...emailCfg, resend_from: e.target.value })}
                        placeholder="alerts@yourdomain.com or onboarding@resend.dev"
                        className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]"
                        data-testid="email-resend-from"
                      />
                      <div className="text-xs text-zinc-500">
                        Use <span className="font-mono text-zinc-300">onboarding@resend.dev</span> for testing.
                        Verify your own domain at{" "}
                        <a href="https://resend.com/domains" target="_blank" rel="noopener noreferrer"
                           className="text-blue-300 hover:underline">resend.com/domains</a>{" "}
                        for production use.
                      </div>
                    </div>
                  </div>
                )}

                {/* Common — sender display name */}
                {emailCfg.provider !== "disabled" && (
                  <div className="space-y-2">
                    <Label className="text-zinc-300">Sender name (shown in inbox &quot;From&quot; field)</Label>
                    <Input
                      value={emailCfg.sender_name}
                      onChange={(e) => setEmailCfg({ ...emailCfg, sender_name: e.target.value })}
                      placeholder="Krexion Alerts"
                      className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)]"
                      data-testid="email-sender-name"
                    />
                  </div>
                )}

                {/* Save + Test row */}
                <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-zinc-800">
                  <Button
                    onClick={handleSaveEmailSettings}
                    disabled={emailSaving}
                    className="bg-[#3B82F6] hover:bg-[#2563EB]"
                    data-testid="email-save-btn"
                  >
                    <Save size={16} className="mr-2" />
                    {emailSaving ? "Saving..." : "Save email settings"}
                  </Button>

                  <div className="flex items-center gap-2">
                    <Input
                      type="email"
                      value={emailTestTo}
                      onChange={(e) => setEmailTestTo(e.target.value)}
                      placeholder="test@youremail.com (blank = your admin email)"
                      className="bg-[var(--brand-card-elevated)] border-[var(--brand-border)] w-[300px]"
                      data-testid="email-test-to"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleTestEmail}
                      disabled={emailTesting || emailCfg.provider === "disabled"}
                      className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                      data-testid="email-test-btn"
                    >
                      <Send size={16} className="mr-2" />
                      {emailTesting ? "Sending..." : "Send test email"}
                    </Button>
                  </div>
                </div>

                {emailCfg.updated_at && (
                  <div className="text-xs text-zinc-500">
                    Last updated: {new Date(emailCfg.updated_at).toLocaleString()}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Cross-user IP isolation ──────────────────── */}
          <TabsContent value="ip-isolation" className="mt-6">
            <CrossUserIpIsolationPanel users={users} getAdminToken={getAdminToken} />
          </TabsContent>

          {/* ── System Check tab ─────────────────────────── */}
          <TabsContent value="system" className="mt-6">
            <SystemCheckPanel api={API} />
          </TabsContent>

          <TabsContent value="admin-settings" className="mt-6 space-y-6">
            <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <CardHeader>
                <CardTitle className="text-white flex items-center gap-2">
                  <Lock size={20} className="text-[#F59E0B]" />
                  Admin Account
                </CardTitle>
                <CardDescription>
                  Change your admin login password. Email is configured on the VPS (.env ADMIN_EMAIL).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-lg bg-black/30 border border-[var(--brand-border)]">
                    <p className="text-xs uppercase tracking-wide text-[#71717A] mb-1">Login email</p>
                    <p className="text-white font-mono text-sm" data-testid="admin-account-email">
                      {adminAccount?.email || "—"}
                    </p>
                  </div>
                  <div className="p-4 rounded-lg bg-black/30 border border-[var(--brand-border)]">
                    <p className="text-xs uppercase tracking-wide text-[#71717A] mb-1">Password status</p>
                    <p className={`text-sm font-medium ${adminAccount?.password_customized ? "text-[#34D399]" : "text-[#FBBF24]"}`}>
                      {adminAccount?.password_customized ? "Custom password set" : "Using default / .env password"}
                    </p>
                    {adminAccount?.password_updated_at && (
                      <p className="text-xs text-[#71717A] mt-1">
                        Last changed: {format(new Date(adminAccount.password_updated_at), "PPp")}
                      </p>
                    )}
                  </div>
                </div>

                <div className="space-y-4 max-w-xl">
                  <div className="space-y-2">
                    <Label htmlFor="admin-current-password">Current password</Label>
                    <div className="relative">
                      <Input
                        id="admin-current-password"
                        type={showAdminCurrentPassword ? "text" : "password"}
                        value={adminCurrentPassword}
                        onChange={(e) => setAdminCurrentPassword(e.target.value)}
                        className="bg-[var(--brand-card)] border-[var(--brand-border)] pr-10"
                        data-testid="admin-current-password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowAdminCurrentPassword((v) => !v)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                      >
                        {showAdminCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="admin-new-password">New password</Label>
                    <div className="relative">
                      <Input
                        id="admin-new-password"
                        type={showAdminNewPassword ? "text" : "password"}
                        value={adminNewPassword}
                        onChange={(e) => setAdminNewPassword(e.target.value)}
                        className="bg-[var(--brand-card)] border-[var(--brand-border)] pr-10"
                        data-testid="admin-new-password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowAdminNewPassword((v) => !v)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                      >
                        {showAdminNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                    <p className="text-xs text-[#71717A]">Minimum 8 characters</p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="admin-confirm-password">Confirm new password</Label>
                    <Input
                      id="admin-confirm-password"
                      type="password"
                      value={adminConfirmPassword}
                      onChange={(e) => setAdminConfirmPassword(e.target.value)}
                      className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                      data-testid="admin-confirm-password"
                    />
                  </div>
                  <Button
                    onClick={changeAdminPassword}
                    disabled={adminPasswordSaving}
                    className="bg-[#F59E0B] hover:bg-[#D97706] text-black font-semibold"
                    data-testid="admin-change-password-btn"
                  >
                    {adminPasswordSaving ? "Saving…" : "Change Admin Password"}
                  </Button>
                </div>

                <div className="p-4 rounded-lg border border-[var(--brand-border)] bg-black/20 text-sm text-[#A1A1AA]">
                  <p className="text-white font-medium mb-2">Forgot your password?</p>
                  <p className="mb-3">
                    Use the password reset page with your admin email. Email must be configured under the Email Settings tab first.
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="border-[var(--brand-border)]"
                    onClick={() => window.open("/forgot-password", "_blank")}
                    data-testid="admin-forgot-password-link"
                  >
                    Open Forgot Password Page
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>

      {/* Edit User Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit User: {selectedUser?.name}</DialogTitle>
            <DialogDescription>{selectedUser?.email}</DialogDescription>
          </DialogHeader>
          
          <div className="space-y-6 py-4">
            {/* Credentials */}
            <div className="space-y-4">
              <Label className="text-base font-medium">Account Credentials</Label>
              <div className="grid grid-cols-2 gap-4 bg-[var(--brand-card)] p-4 rounded-lg">
                <div className="space-y-2">
                  <Label htmlFor="user-email">Email</Label>
                  <Input
                    id="user-email"
                    type="email"
                    value={userEmail}
                    onChange={(e) => setUserEmail(e.target.value)}
                    className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                    data-testid="edit-user-email"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="user-password">New Password (leave empty to keep)</Label>
                  <div className="relative">
                    <Input
                      id="user-password"
                      type={showPassword ? "text" : "password"}
                      value={userPassword}
                      onChange={(e) => setUserPassword(e.target.value)}
                      placeholder="Enter new password"
                      className="bg-[var(--brand-card)] border-[var(--brand-border)] pr-10"
                      data-testid="edit-user-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Status */}
            <div className="space-y-2">
              <Label>Account Status</Label>
              <div className="flex gap-2">
                {["pending", "active", "blocked"].map((status) => (
                  <Button
                    key={status}
                    variant={userStatus === status ? "default" : "outline"}
                    size="sm"
                    onClick={() => setUserStatus(status)}
                    className={userStatus === status ? 
                      status === "active" ? "bg-[#22C55E]" : 
                      status === "blocked" ? "bg-[#EF4444]" : "bg-[#F59E0B]"
                      : "border-[var(--brand-border)]"
                    }
                  >
                    {status.charAt(0).toUpperCase() + status.slice(1)}
                  </Button>
                ))}
              </div>
            </div>

            {/* Subscription */}
            <div className="space-y-4">
              <Label className="text-base font-medium">Subscription Management</Label>
              <div className="grid grid-cols-2 gap-4 bg-[var(--brand-card)] p-4 rounded-lg">
                <div className="space-y-2">
                  <Label>Subscription Type</Label>
                  <Select value={subscriptionType} onValueChange={setSubscriptionType}>
                    <SelectTrigger className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                      <SelectItem value="free">Free</SelectItem>
                      <SelectItem value="monthly">Monthly</SelectItem>
                      <SelectItem value="yearly">Yearly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Expiration Date</Label>
                  <Input
                    type="date"
                    value={subscriptionExpires}
                    onChange={(e) => setSubscriptionExpires(e.target.value)}
                    className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                  />
                </div>
              </div>
            </div>

            {/* Features */}
            <div className="space-y-4">
              <Label>Feature Access</Label>
              <div className="space-y-3 bg-[var(--brand-card)] p-4 rounded-lg">
                {[
                  { key: "links", label: "Links Management" },
                  { key: "clicks", label: "Click Tracking" },
                  { key: "conversions", label: "Conversion Tracking" },
                  { key: "proxies", label: "Proxy Management" },
                  { key: "import_traffic", label: "Import Traffic (Quick / Manual / Bulk)" },
                  { key: "real_traffic", label: "Real Traffic (residential proxies)" },
                  { key: "ua_generator", label: "User Agent Generator" },
                  { key: "email_checker", label: "Email Profile Checker" },
                  { key: "phone_checker", label: "Phone Checker (free libphonenumber)" },
                  { key: "separate_data", label: "Separate Data (row filter)" },
                  { key: "form_filler", label: "Form Filler / Survey Bot" },
                  { key: "real_user_traffic", label: "Real User Traffic (anti-detect)" },
                  { key: "profile_builder", label: "Profile Builder (AdsPower bulk profiles + Proxy Provider)" },
                  { key: "cpi", label: "CPI Installs (Cost-Per-Install module)" },
                  { key: "import_data", label: "Data Import (legacy master toggle)" },
                  { key: "settings", label: "Settings Access" }
                ].map(({ key, label }) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm text-[#FAFAFA]">{label}</span>
                    <Switch
                      checked={userFeatures[key] || false}
                      onCheckedChange={(checked) => setUserFeatures(prev => ({ ...prev, [key]: checked }))}
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Limits */}
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Max Links</Label>
                <Input
                  type="number"
                  value={userFeatures.max_links || 0}
                  onChange={(e) => setUserFeatures(prev => ({ ...prev, max_links: parseInt(e.target.value) || 0 }))}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                />
              </div>
              <div className="space-y-2">
                <Label>Max Clicks</Label>
                <Input
                  type="number"
                  value={userFeatures.max_clicks || 0}
                  onChange={(e) => setUserFeatures(prev => ({ ...prev, max_clicks: parseInt(e.target.value) || 0 }))}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                />
              </div>
              <div className="space-y-2">
                <Label>Max Sub-Users</Label>
                <Input
                  type="number"
                  value={userFeatures.max_sub_users || 0}
                  onChange={(e) => setUserFeatures(prev => ({ ...prev, max_sub_users: parseInt(e.target.value) || 0 }))}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                  data-testid="max-sub-users-input"
                />
                <p className="text-xs text-[#A1A1AA]">0 = unlimited</p>
              </div>
            </div>

            {/* Subscription Note */}
            <div className="space-y-2">
              <Label>Subscription Note (Internal)</Label>
              <Textarea
                value={subscriptionNote}
                onChange={(e) => setSubscriptionNote(e.target.value)}
                placeholder="Add notes about payment, subscription tier, etc."
                className="bg-[var(--brand-card)] border-[var(--brand-border)]"
              />
            </div>

            <Button onClick={handleUpdateUser} className="w-full">
              Save Changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Edit Sub-User Dialog */}
      <Dialog open={editSubUserDialogOpen} onOpenChange={setEditSubUserDialogOpen}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Sub-User: {selectedSubUser?.name}</DialogTitle>
            <DialogDescription>
              {selectedSubUser?.email} (Parent: {selectedSubUser?.parent_email})
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-6 py-4">
            {/* Name */}
            <div className="space-y-2">
              <Label htmlFor="subuser-name">Name</Label>
              <Input
                id="subuser-name"
                value={subUserName}
                onChange={(e) => setSubUserName(e.target.value)}
                className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                data-testid="edit-subuser-name"
              />
            </div>

            {/* Password */}
            <div className="space-y-2">
              <Label htmlFor="subuser-password">New Password (leave empty to keep)</Label>
              <div className="relative">
                <Input
                  id="subuser-password"
                  type={showPassword ? "text" : "password"}
                  value={subUserPassword}
                  onChange={(e) => setSubUserPassword(e.target.value)}
                  placeholder="Enter new password"
                  className="bg-[var(--brand-card)] border-[var(--brand-border)] pr-10"
                  data-testid="edit-subuser-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-white"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Status */}
            <div className="flex items-center justify-between bg-[var(--brand-card)] p-4 rounded-lg">
              <div>
                <Label>Account Status</Label>
                <p className="text-sm text-[#A1A1AA]">Enable or disable this sub-user account</p>
              </div>
              <Switch
                checked={subUserIsActive}
                onCheckedChange={setSubUserIsActive}
                data-testid="subuser-active-switch"
              />
            </div>

            {/* Permissions */}
            <div className="space-y-4">
              <Label>Permissions</Label>
              <div className="space-y-3 bg-[var(--brand-card)] p-4 rounded-lg">
                {[
                  { key: "view_links", label: "View Links" },
                  { key: "view_clicks", label: "View Clicks" },
                  { key: "view_proxies", label: "View Proxies" },
                  { key: "edit", label: "Edit Capabilities" }
                ].map(({ key, label }) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm text-[#FAFAFA]">{label}</span>
                    <Switch
                      checked={subUserPermissions[key] || false}
                      onCheckedChange={(checked) => setSubUserPermissions(prev => ({ ...prev, [key]: checked }))}
                      data-testid={`subuser-perm-${key}`}
                    />
                  </div>
                ))}
              </div>
            </div>

            <Button onClick={handleUpdateSubUser} className="w-full">
              Save Changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Custom API Dialog */}
      <Dialog open={addApiDialogOpen} onOpenChange={setAddApiDialogOpen}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Custom API</DialogTitle>
            <DialogDescription>Add a new VPN detection or geolocation API service</DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="api-key-id">API Key ID *</Label>
                <Input
                  id="api-key-id"
                  value={newApiData.key}
                  onChange={(e) => setNewApiData(prev => ({ ...prev, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') }))}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                  placeholder="e.g., my_vpn_api"
                />
                <p className="text-xs text-[#52525B]">Unique identifier (lowercase, no spaces)</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="api-name">Display Name *</Label>
                <Input
                  id="api-name"
                  value={newApiData.name}
                  onChange={(e) => setNewApiData(prev => ({ ...prev, name: e.target.value }))}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                  placeholder="e.g., My VPN API"
                />
              </div>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="api-endpoint">API Endpoint *</Label>
              <Input
                id="api-endpoint"
                value={newApiData.endpoint}
                onChange={(e) => setNewApiData(prev => ({ ...prev, endpoint: e.target.value }))}
                className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                placeholder="https://api.example.com/check/"
              />
              <p className="text-xs text-[#52525B]">Use {"{ip}"} as placeholder for IP address</p>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="api-key-value">API Key (if required)</Label>
              <Input
                id="api-key-value"
                type="password"
                value={newApiData.api_key}
                onChange={(e) => setNewApiData(prev => ({ ...prev, api_key: e.target.value }))}
                className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                placeholder="Your API key"
              />
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="api-priority">Priority</Label>
                <Input
                  id="api-priority"
                  type="number"
                  min="1"
                  max="99"
                  value={newApiData.priority}
                  onChange={(e) => setNewApiData(prev => ({ ...prev, priority: parseInt(e.target.value) || 10 }))}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                />
                <p className="text-xs text-[#52525B]">Lower = checked first</p>
              </div>
              <div className="space-y-2 flex items-end">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={newApiData.enabled}
                    onCheckedChange={(checked) => setNewApiData(prev => ({ ...prev, enabled: checked }))}
                  />
                  <Label>Enabled</Label>
                </div>
              </div>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="api-description">Description</Label>
              <Textarea
                id="api-description"
                value={newApiData.description}
                onChange={(e) => setNewApiData(prev => ({ ...prev, description: e.target.value }))}
                className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                placeholder="What does this API do?"
                rows={2}
              />
            </div>
            
            <div className="flex gap-2 pt-4">
              <Button 
                variant="outline" 
                onClick={() => setAddApiDialogOpen(false)}
                className="flex-1 border-[var(--brand-border)]"
              >
                Cancel
              </Button>
              <Button 
                onClick={handleAddCustomApi}
                className="flex-1 bg-[#3B82F6] hover:bg-[#2563EB]"
              >
                Add API
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
