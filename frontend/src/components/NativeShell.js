/* ════════════════════════════════════════════════════════════════════════
   NativeShell.js — Krexion native-install desktop window UI
   ════════════════════════════════════════════════════════════════════════

   ❗ SAFETY NOTE
   This component is a STRICT ADDITIVE wrapper around the existing
   customer-facing pages. It NEVER replaces business logic.

   • Activated ONLY when `KREXION_MODE === "native"` (set on the
     customer's PC by Inno Setup via NSSM AppEnvironmentExtra).
   • For the cloud preview (KREXION_MODE=cloud) and the dev preview
     (KREXION_MODE=local) the existing `DashboardLayout` continues to
     be used — this file is a NO-OP for those environments unless the
     `?ui=native` query param OR `localStorage.krexion_force_native_ui`
     is explicitly set (testing/preview only).
   • Admin routes (`/admin/*`) NEVER pass through this shell — they
     stay rendered exactly as today via the existing AdminRoute block
     in App.js.
   • Backend / API / data-model are 100% UNTOUCHED. We only swap the
     visual chrome around `{children}`.

   ════════════════════════════════════════════════════════════════════════ */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Link2, MousePointerClick, DollarSign, Server, LogOut,
  User, Settings, TrendingUp, Upload, Mail, Phone, Filter, Smartphone, Search,
  Fingerprint, Package, Camera, UserPlus, Activity, ChevronDown, Bell,
  CloudUpload, HelpCircle, Plus, Crown, Minus, Square, X as XIcon,
  ListChecks, Tag, Layers, FileText, Wrench, KeyRound, PanelLeftClose,
  PanelLeftOpen, RefreshCw, Zap, Globe
} from "lucide-react";
import axios from "axios";
import { useBranding } from "../context/BrandingContext";
import BannerBar from "./BannerBar";
import UpdateBanner from "./UpdateBanner";
import "./NativeShell.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

/* ── Feature → access-flag helpers (same rules as DashboardLayout) ──── */
const LEGACY_IMPORT_GROUP = new Set([
  "email_checker", "phone_checker", "separate_data", "import_traffic", "real_traffic", "ua_generator", "ua_checker",
]);

function hasFeature(features, key) {
  if (key === null || key === undefined) return true;
  if (features[key] === true) return true;
  if (
    features[key] === undefined &&
    LEGACY_IMPORT_GROUP.has(key) &&
    features.import_data === true
  ) return true;
  return false;
}

/* ── Sidebar navigation map (AdsPower-style grouped) ─────────────────
   Order, names and routes match the existing DashboardLayout 1:1 — we
   ONLY add visual grouping headers. No new routes, no removed routes. */
const NAV_GROUPS = [
  {
    id: "main",
    label: "Main",
    items: [
      { name: "Dashboard",       path: "/dashboard",         icon: LayoutDashboard, feature: null },
      { name: "Links",           path: "/links",             icon: Link2,           feature: "links" },
      { name: "Clicks",          path: "/clicks",            icon: MousePointerClick, feature: "clicks" },
      { name: "Conversions",     path: "/conversions",       icon: DollarSign,      feature: "conversions" },
      { name: "Traffic Sources", path: "/referrers",         icon: TrendingUp,      feature: "clicks" },
      { name: "Proxies",         path: "/proxies",           icon: Server,          feature: "proxies" },
      { name: "Profile Builder", path: "/profile-builder",   icon: UserPlus,        feature: "profile_builder" },
    ],
  },
  {
    id: "engine",
    label: "Traffic Engine",
    items: [
      { name: "Real-User Traffic", path: "/real-user-traffic", icon: Fingerprint, feature: "real_user_traffic" },
      { name: "Browser Profiles",  path: "/browser-profiles",  icon: Globe,       feature: "real_user_traffic" },
      { name: "Visual Recorder",   path: "/visual-recorder",   icon: Camera,      feature: "real_user_traffic" },
      { name: "RPA Studio",        path: "/rpa-studio",        icon: Zap,         feature: null },
      // v2.6.1 — Form Filler removed (already inside Real-User Traffic)
      { name: "Uploaded Items",    path: "/uploaded-things",   icon: Package,     feature: "real_user_traffic" },
    ],
  },
  {
    id: "tools",
    label: "Tools",
    items: [
      { name: "Email Checker",  path: "/email-checker",  icon: Mail,     feature: "email_checker" },
      { name: "Phone Checker",  path: "/phone-checker",  icon: Phone,    feature: "phone_checker" },
      { name: "Separate Data",  path: "/separate-data",  icon: Filter,   feature: "separate_data" },
      // v2.6.1 — Import Traffic removed (already inside Real-User Traffic)
      { name: "UA Generator",   path: "/ua-generator",   icon: Smartphone, feature: "ua_generator" },
      { name: "UA Checker",     path: "/ua-checker",     icon: Search,   feature: "ua_checker" },
    ],
  },
  {
    id: "cpi",
    label: "CPI",
    items: [
      { name: "CPI Dashboard", path: "/cpi",            icon: LayoutDashboard, feature: "cpi" },
      { name: "Offers",        path: "/cpi/offers",     icon: Tag,             feature: "cpi" },
      { name: "Jobs",          path: "/cpi/jobs",       icon: ListChecks,      feature: "cpi" },
      { name: "Devices",       path: "/cpi/devices",    icon: Smartphone,      feature: "cpi" },
      { name: "Smart Links",   path: "/cpi/smartlinks", icon: Layers,          feature: "cpi" },
      { name: "Worker Setup",  path: "/cpi/setup",      icon: Wrench,          feature: "cpi" },
    ],
  },
  {
    id: "system",
    label: "System",
    items: [
      { name: "License",       path: "/license",       icon: KeyRound, feature: null },
      { name: "System Health", path: "/system-health", icon: Activity, feature: null },
      { name: "Settings",      path: "/settings",      icon: Settings, feature: "settings" }, // hidden for sub-users below
    ],
  },
];

/* ── Title-bar action handlers (PyWebView API if available) ──────────
   These are wired so the title-bar buttons work both inside PyWebView
   (the production native shell) and inside a normal browser (preview
   testing). In a browser they simply do nothing or open a confirm. */
function titleBarAction(kind) {
  try {
    // PyWebView 5.x exposes window.pywebview.api when JS API is registered.
    // We fall back to window.close() which works in PyWebView frameless
    // mode too.
    if (typeof window !== "undefined" && window.pywebview && window.pywebview.api) {
      if (kind === "minimize" && window.pywebview.api.minimize)  return window.pywebview.api.minimize();
      if (kind === "maximize" && window.pywebview.api.toggle_fullscreen)
        return window.pywebview.api.toggle_fullscreen();
      if (kind === "close" && window.pywebview.api.hide_window)  return window.pywebview.api.hide_window();
    }
    if (kind === "close" && typeof window !== "undefined") window.close();
  } catch (e) { /* swallow — title bar is decorative in preview */ }
}

export default function NativeShell({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { branding } = useBranding();

  const [user, setUser] = useState(JSON.parse(localStorage.getItem("user") || "{}"));
  const [version, setVersion] = useState("");
  const [engineStatus, setEngineStatus] = useState("running"); // running | offline
  const [collapsed, setCollapsed] = useState({});  // section -> bool
  // v2.1.22 — Sidebar hide toggle for fullscreen RUT view. Persisted to
  // localStorage so the choice survives reloads.
  // v2.6.1 — Added an icons-only "collapsed" mode. Toggle cycles
  //   full ↔ icons-only. A separate long-press / secondary control can
  //   still fully hide the sidebar via `sidebarHidden`.
  const [sidebarHidden, setSidebarHidden] = useState(
    () => (typeof window !== "undefined" && localStorage.getItem("krexion_sidebar_hidden") === "1")
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => (typeof window !== "undefined" && localStorage.getItem("krexion_sidebar_collapsed") === "1")
  );
  useEffect(() => {
    try { localStorage.setItem("krexion_sidebar_hidden", sidebarHidden ? "1" : "0"); } catch (_) { /* localStorage unavailable */ }
  }, [sidebarHidden]);
  useEffect(() => {
    try { localStorage.setItem("krexion_sidebar_collapsed", sidebarCollapsed ? "1" : "0"); } catch (_) { /* ignore */ }
  }, [sidebarCollapsed]);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);

  /* Pull live user data so feature flags + name are always fresh */
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { navigate("/login"); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        const cur = JSON.parse(localStorage.getItem("user") || "{}");
        const merged = { ...cur, ...r.data };
        localStorage.setItem("user", JSON.stringify(merged));
        setUser(merged);
      })
      .catch((err) => {
        if (err?.response?.status === 401 || err?.response?.status === 403) {
          localStorage.removeItem("token");
          localStorage.removeItem("user");
          navigate("/login");
        }
      });
  }, [navigate]);

  /* Fetch app version + engine liveness (best-effort, no UI break on fail).
     `/api/system/version` is the lightest no-auth endpoint that exists in
     all modes (cloud + native), so we use ONE call to derive both. */
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      axios.get(`${API}/system/version`, { timeout: 5000 })
        .then((r) => {
          if (cancelled) return;
          setVersion(r.data?.version || "");
          setEngineStatus("running");
        })
        .catch(() => { if (!cancelled) setEngineStatus("offline"); });
    };
    tick();
    const t = setInterval(tick, 20000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  /* Click-outside to close user menu */
  useEffect(() => {
    function onDown(e) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false);
    }
    if (userMenuOpen) document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [userMenuOpen]);

  const isSubUser = user?.is_sub_user === true;
  const features = user?.features || {};

  /* Filter sidebar groups by feature flags (preserve DashboardLayout rules) */
  const visibleGroups = useMemo(() => {
    return NAV_GROUPS
      .map((g) => {
        const items = g.items.filter((it) => {
          if (it.path === "/settings") {
            if (isSubUser) return false;
            if (features.settings === false) return false;
            return true;
          }
          return hasFeature(features, it.feature);
        });
        return { ...g, items };
      })
      .filter((g) => g.items.length > 0);
  }, [features, isSubUser]);

  const currentPage = useMemo(() => {
    for (const g of visibleGroups) {
      for (const it of g.items) {
        if (it.path === location.pathname) return it;
        if (location.pathname.startsWith(it.path + "/")) return it;
      }
    }
    return { name: "Dashboard", icon: LayoutDashboard };
  }, [visibleGroups, location.pathname]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    navigate("/login");
  };

  /* Quick-action ("+ New RUT Job") jumps to the RUT page if visible,
     else dashboard. Same target the FAB on RealUserTrafficPage uses. */
  const quickAction = () => {
    const rut = visibleGroups.flatMap((g) => g.items).find((it) => it.path === "/real-user-traffic");
    navigate(rut ? rut.path : "/dashboard");
  };

  const userInitial = (user.name || user.email || "U").charAt(0).toUpperCase();
  const accountSubtitle = (() => {
    if (isSubUser) return "Team Member";
    const exp = user?.license_expiry_days;
    if (typeof exp === "number") return `Pro · ${exp} days left`;
    return user?.plan_name || "Local install";
  })();

  return (
    <div className="knative-root" data-testid="native-shell-root">
      {/* ── Title bar (decorative + drag region for future frameless) ── */}
      <div className="knative-titlebar" data-testid="native-titlebar">
        <div className="knative-titlebar-title">
          <span className="brand-mark">{branding?.app_name || "Krexion"}</span>
          <span className="ver">
            {version ? `v${version}` : ""} {version ? "|" : ""} local engine
          </span>
        </div>
        <div className="knative-titlebar-controls">
          <button title="Minimize" onClick={() => titleBarAction("minimize")} data-testid="native-titlebar-min"><Minus size={12} /></button>
          <button title="Maximize" onClick={() => titleBarAction("maximize")} data-testid="native-titlebar-max"><Square size={11} /></button>
          <button className="close" title="Close" onClick={() => titleBarAction("close")} data-testid="native-titlebar-close"><XIcon size={13} /></button>
        </div>
      </div>

      {/* ── Menubar (cosmetic) ─────────────────────────────────────── */}
      <div className="knative-menubar" data-testid="native-menubar">
        <button>File</button>
        <button>Edit</button>
        <button>View</button>
        <button>Window</button>
        <button onClick={() => window.open("https://krexion.com/guide", "_blank", "noopener")}>Help</button>
      </div>

      {/* ── Sidebar + content ──────────────────────────────────────── */}
      <div className={`knative-app ${sidebarHidden ? "knative-app-no-sidebar" : ""} ${!sidebarHidden && sidebarCollapsed ? "knative-app-collapsed" : ""}`}>
        {!sidebarHidden && (
        <aside className="knative-sidebar" data-testid="native-sidebar">
          <div className="knative-brand">
            <div className="knative-brand-logo">
              {branding?.logo_url ? <img src={branding.logo_url} alt={branding?.app_name || "Krexion"} /> : "K"}
            </div>
            {!sidebarCollapsed && (
              <div className="knative-brand-name">{branding?.app_name || "Krexion"}</div>
            )}
            {/* v2.6.1 — Sidebar collapse toggle right next to the Krexion logo.
                Visible in both full + collapsed states so user can always
                switch. Fully-hidden state is toggled from the top-bar icon. */}
            <button
              className="knative-brand-toggle"
              onClick={() => setSidebarCollapsed((v) => !v)}
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse to icons only"}
              data-testid="native-sidebar-collapse-toggle"
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
            </button>
          </div>

          <button className="knative-cta" onClick={quickAction} data-testid="native-quick-new-job">
            <Plus size={14} />
            <span>New RUT Job</span>
          </button>

          {visibleGroups.map((g) => {
            const isCollapsed = !!collapsed[g.id];
            return (
              <div key={g.id}>
                <div
                  className={`knative-nav-section${isCollapsed ? " collapsed" : ""}`}
                  onClick={() => setCollapsed((c) => ({ ...c, [g.id]: !c[g.id] }))}
                  data-testid={`native-nav-section-${g.id}`}
                >
                  <span>{g.label}</span>
                  <ChevronDown className="chev" size={9} />
                </div>
                {!isCollapsed && g.items.map((it) => {
                  const Icon = it.icon;
                  const active =
                    location.pathname === it.path ||
                    (it.path !== "/dashboard" && location.pathname.startsWith(it.path + "/"));
                  return (
                    <Link
                      key={it.path}
                      to={it.path}
                      className={`knative-nav-item${active ? " active" : ""}`}
                      data-testid={`native-nav-${it.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
                    >
                      <Icon size={16} />
                      <span className="label">{it.name}</span>
                    </Link>
                  );
                })}
              </div>
            );
          })}

          <div className="knative-account" onClick={() => navigate("/settings")} data-testid="native-account-card">
            <div className="knative-account-avatar">{userInitial}</div>
            <div className="knative-account-info">
              <div className="knative-account-name">{user.email || user.name || "User"}</div>
              <div className="knative-account-plan">
                <Crown size={9} /> {accountSubtitle}
              </div>
            </div>
          </div>
        </aside>
        )}

        <div className="knative-content">
          <div className="knative-topbar" data-testid="native-topbar">
            <div className="knative-page-title">
              <span>{currentPage.name}</span>
            </div>

            {/* Engine status pill intentionally hidden from customer-facing UI.
                The status is still tracked in `engineStatus` for internal
                diagnostics (System Health page) but never rendered here. */}

            {/* v2.1.22 — Sidebar hide toggle (fullscreen RUT view) + Refresh */}
            <button
              className="knative-topicon"
              title={sidebarHidden ? "Show sidebar" : "Hide sidebar (fullscreen)"}
              onClick={() => setSidebarHidden((v) => !v)}
              data-testid="native-icon-sidebar-toggle"
            >
              {sidebarHidden ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
            <button
              className="knative-topicon"
              title="Refresh current page"
              onClick={() => window.location.reload()}
              data-testid="native-icon-refresh"
            >
              <RefreshCw size={16} />
            </button>

            <button className="knative-topicon" title="Sync to cloud" data-testid="native-icon-cloud">
              <CloudUpload size={16} />
            </button>
            <button className="knative-topicon" title="Notifications" data-testid="native-icon-bell">
              <Bell size={16} />
            </button>
            <button className="knative-topicon" title="Help" onClick={() => window.open("https://krexion.com/guide", "_blank", "noopener")} data-testid="native-icon-help">
              <HelpCircle size={16} />
            </button>
            <button className="knative-topicon" title="User menu" onClick={() => setUserMenuOpen((v) => !v)} data-testid="native-icon-user">
              <User size={16} />
            </button>

            {userMenuOpen && (
              <div className="knative-usermenu" ref={userMenuRef} data-testid="native-usermenu">
                {!isSubUser && (
                  <button onClick={() => { setUserMenuOpen(false); navigate("/settings"); }} data-testid="native-usermenu-settings">
                    <Settings size={14} /> Settings
                  </button>
                )}
                <button onClick={() => { setUserMenuOpen(false); navigate("/system-health"); }} data-testid="native-usermenu-health">
                  <Activity size={14} /> System Health
                </button>
                <div className="sep" />
                <button onClick={handleLogout} data-testid="native-usermenu-logout">
                  <LogOut size={14} /> Logout
                </button>
              </div>
            )}
          </div>

          <div className="knative-body" data-testid="native-body">
            <UpdateBanner />
            <BannerBar />
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
