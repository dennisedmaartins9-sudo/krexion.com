import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, Link2, MousePointerClick, DollarSign, Server, Menu, LogOut, User, Settings, TrendingUp, Upload, Mail, Phone, Filter, Smartphone, Search, ClipboardCheck, Fingerprint, Package, Apple, Cpu, Briefcase, ChevronDown, ChevronRight, ChevronLeft, PanelLeftClose, PanelLeftOpen, Link as LinkIcon, Activity, Camera, UserPlus, KeyRound, Zap, Globe } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "./ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu";
import { useBranding } from "../context/BrandingContext";
import ThemeToggle from "./ThemeToggle";
import WavyBackground from "./WavyBackground";
import CloudModeBanner from "./CloudModeBanner";
import LocalPCStatusBadge from "./LocalPCStatusBadge";
import UpdateBanner from "./UpdateBanner";
import InstalledVersionBadge from "./InstalledVersionBadge";
import BannerBar from "./BannerBar";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function DashboardLayout({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { branding } = useBranding();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // Mobile drawer state (separate from desktop collapse) — closed by default on mobile
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  // Close mobile drawer whenever route changes
  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [location.pathname]);
  // CPI group expanded by default if user is currently on a CPI page
  const initialCpiOpen = (() => {
    try { return location.pathname.startsWith("/cpi"); } catch { return false; }
  })();
  const [cpiGroupOpen, setCpiGroupOpen] = useState(initialCpiOpen);
  const [user, setUser] = useState(JSON.parse(localStorage.getItem("user") || "{}"));
  const [loading, setLoading] = useState(true);

  // Fetch fresh user data on mount to get updated features
  useEffect(() => {
    const fetchUserData = async () => {
      const token = localStorage.getItem("token");
      if (!token) {
        navigate("/login");
        return;
      }

      try {
        const response = await axios.get(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const freshUserData = response.data;
        
        // Update localStorage with fresh data
        const currentUser = JSON.parse(localStorage.getItem("user") || "{}");
        const updatedUser = { ...currentUser, ...freshUserData };
        localStorage.setItem("user", JSON.stringify(updatedUser));
        setUser(updatedUser);
      } catch (error) {
        console.error("Failed to fetch user data:", error);
        // If token is invalid, redirect to login
        if (error.response?.status === 401 || error.response?.status === 403) {
          localStorage.removeItem("token");
          localStorage.removeItem("user");
          navigate("/login");
        }
      } finally {
        setLoading(false);
      }
    };

    fetchUserData();
  }, [navigate]);

  const isSubUser = user.is_sub_user === true;
  const features = user.features || {};

  // Build navigation based on user's enabled features
  const allNavItems = [
    { name: "Dashboard", path: "/dashboard", icon: LayoutDashboard, feature: null }, // Always show dashboard
    { name: "Links", path: "/links", icon: Link2, feature: "links" },
    { name: "Clicks", path: "/clicks", icon: MousePointerClick, feature: "clicks" },
    { name: "Traffic Sources", path: "/referrers", icon: TrendingUp, feature: "clicks" },
    // v2.6.1 — Import Traffic + Form Filler removed (already inside Real User Traffic)
    { name: "Email Checker", path: "/email-checker", icon: Mail, feature: "email_checker" },
    { name: "Phone Checker", path: "/phone-checker", icon: Phone, feature: "phone_checker" },
    { name: "Separate Data", path: "/separate-data", icon: Filter, feature: "separate_data" },
    { name: "UA Generator", path: "/ua-generator", icon: Smartphone, feature: "ua_generator" },
    { name: "UA Checker", path: "/ua-checker", icon: Search, feature: "ua_checker" },
    { name: "Real User Traffic", path: "/real-user-traffic", icon: Fingerprint, feature: "real_user_traffic" },
    { name: "Browser Profiles", path: "/browser-profiles", icon: Globe, feature: "real_user_traffic" },
    { name: "Visual Recorder", path: "/visual-recorder", icon: Camera, feature: "real_user_traffic" },
    { name: "RPA Studio", path: "/rpa-studio", icon: Zap, feature: null },
    { name: "Uploaded Things", path: "/uploaded-things", icon: Package, feature: "real_user_traffic" },
    { name: "Proxies", path: "/proxies", icon: Server, feature: "proxies" },
    { name: "Profile Builder", path: "/profile-builder", icon: UserPlus, feature: "profile_builder" },
  ];

  // Backward compat: new granular features fall back to "import_data" legacy flag
  const LEGACY_IMPORT_GROUP = new Set([
    "email_checker", "phone_checker", "separate_data", "import_traffic", "real_traffic", "ua_generator", "ua_checker"
  ]);

  // Filter navigation: show only enabled features (groups + flat items)
  const navigation = allNavItems.filter(item => {
    if (item.feature === null || item.feature === undefined) return true; // Always show
    if (features[item.feature] === true) return true;
    // Legacy fallback
    if (
      features[item.feature] === undefined &&
      LEGACY_IMPORT_GROUP.has(item.feature) &&
      features.import_data === true
    ) {
      return true;
    }
    return false;
  });

  // Add Settings - ONLY for main users, and only if settings feature is not explicitly false
  // Sub-users NEVER see Settings
  if (!isSubUser && features.settings !== false) {
    navigation.push({ name: "Settings", path: "/settings", icon: Settings, feature: "settings" });
  }

  // System Health is ALWAYS visible to every logged-in user (main + sub).
  // No feature flag — every owner should be able to check the stack
  // before launching a job, and one-click auto-repair if needed.
  navigation.push({ name: "System Health", path: "/system-health", icon: Activity, feature: null });

  // v2.1.14 — License dashboard: always visible to every logged-in user
  // so they can see remaining days, copy their key, and release their
  // current PC without contacting support.
  navigation.push({ name: "License", path: "/license", icon: KeyRound, feature: null });

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    navigate("/login");
  };

  return (
    <div className="flex h-screen relative overflow-hidden" style={{ backgroundColor: '#000000' }}>
      {/* Cursor-following wavy lines background — sits behind everything */}
      <WavyBackground intensity={0.6} lineCount={50} zIndex={0} />

      <aside
        className={`${
          sidebarOpen ? "w-64" : "w-20"
        } sidebar-themed transition-all duration-300 flex-col z-40 fixed inset-y-0 left-0 transform ${
          mobileSidebarOpen ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0 md:relative md:flex md:z-10 flex`}
        style={{
          background: 'linear-gradient(180deg, rgba(0,0,0,0.85) 0%, rgba(10,10,20,0.85) 100%)',
          backdropFilter: 'blur(16px)',
          borderRight: '1px solid rgba(79, 127, 255, 0.2)',
        }}
        data-testid="sidebar"
      >
        <div className="p-6 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(79, 127, 255, 0.2)' }}>
          {sidebarOpen && (
            <div className="flex items-center gap-2 min-w-0 flex-1">
              {branding.logo_url ? (
                <img src={branding.logo_url} alt={branding.app_name} className="h-8 object-contain" data-testid="app-logo" />
              ) : (
                <h1 className="text-xl font-bold bg-gradient-to-r from-white to-[#4F7FFF] bg-clip-text text-transparent truncate" data-testid="app-logo">{branding.app_name || "Krexion"}</h1>
              )}
              <InstalledVersionBadge />
            </div>
          )}
          {/* 2026-06 — Sidebar hide/show button right next to Krexion logo.
              Customer ask (Roman Urdu): "side bar hide krne k liye krexion
              logo k sath he hide k button ho ta k hide or show side bar se
              he kr liya jay". Uses chevron icons + tooltip so the action is
              obvious. */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="hover:bg-[#4F7FFF]/15 text-[#4F7FFF] hover:text-white transition-colors shrink-0 ring-1 ring-[#4F7FFF]/25 hover:ring-[#4F7FFF]/60"
            style={{ backgroundColor: 'transparent' }}
            data-testid="sidebar-toggle"
            title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
          >
            {sidebarOpen ? <PanelLeftClose size={20} /> : <PanelLeftOpen size={20} />}
          </Button>
        </div>

        <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
          {navigation.map((item) => {
            const Icon = item.icon;
            // Group with collapsible children (e.g., CPI Module)
            if (item.group) {
              const anyChildActive = item.children.some(c => location.pathname === c.path);
              const expanded = cpiGroupOpen || anyChildActive;
              return (
                <div key={item.name}>
                  <button
                    type="button"
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-300"
                    style={{
                      background: anyChildActive
                        ? 'linear-gradient(90deg, rgba(79,127,255,0.25) 0%, transparent 100%)'
                        : 'transparent',
                      color: anyChildActive ? '#FFFFFF' : '#A0A0A0',
                      borderLeft: anyChildActive ? '3px solid #4F7FFF' : '3px solid transparent',
                    }}
                    onClick={() => setCpiGroupOpen(!cpiGroupOpen)}
                    onMouseEnter={(e) => {
                      if (!anyChildActive) {
                        e.currentTarget.style.background = 'linear-gradient(90deg, rgba(79,127,255,0.15) 0%, transparent 100%)';
                        e.currentTarget.style.color = '#FFFFFF';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!anyChildActive) {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.color = '#A0A0A0';
                      }
                    }}
                    data-testid={`nav-group-${item.name.toLowerCase().replace(/\s+/g, '-')}`}
                  >
                    <Icon size={20} />
                    {sidebarOpen && (
                      <>
                        <span className="text-sm font-medium flex-1 text-left">{item.name}</span>
                        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </>
                    )}
                  </button>
                  {sidebarOpen && expanded && (
                    <div className="ml-3 mt-1 space-y-1 border-l pl-3" style={{ borderColor: 'rgba(79, 127, 255, 0.25)' }}>
                      {item.children.map((c) => {
                        const isActive = location.pathname === c.path;
                        const CIcon = c.icon;
                        return (
                          <Link key={c.path} to={c.path}>
                            <div
                              className="flex items-center gap-2 px-2 py-1.5 rounded-md transition-all duration-300 text-xs"
                              style={{
                                background: isActive
                                  ? 'linear-gradient(90deg, #4F7FFF 0%, #3D66D9 100%)'
                                  : 'transparent',
                                color: isActive ? '#FFFFFF' : '#A0A0A0',
                                boxShadow: isActive ? '0 4px 14px rgba(79,127,255,0.4)' : 'none',
                              }}
                              onMouseEnter={(e) => {
                                if (!isActive) {
                                  e.currentTarget.style.background = 'rgba(79,127,255,0.1)';
                                  e.currentTarget.style.color = '#FFFFFF';
                                }
                              }}
                              onMouseLeave={(e) => {
                                if (!isActive) {
                                  e.currentTarget.style.background = 'transparent';
                                  e.currentTarget.style.color = '#A0A0A0';
                                }
                              }}
                              data-testid={`nav-${c.name.toLowerCase().replace(/\s+/g, '-')}`}
                            >
                              <CIcon size={14} />
                              <span className="font-medium">{c.name}</span>
                            </div>
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            }
            // Regular flat item
            const isActive = location.pathname === item.path;
            return (
              <Link key={item.path} to={item.path}>
                <motion.div
                  whileHover={{ x: 4 }}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-300`}
                  style={{
                    background: isActive
                      ? 'linear-gradient(90deg, #4F7FFF 0%, #3D66D9 100%)'
                      : 'transparent',
                    color: isActive ? '#FFFFFF' : '#A0A0A0',
                    boxShadow: isActive ? '0 4px 14px rgba(79,127,255,0.4)' : 'none',
                    borderLeft: isActive ? '3px solid #6B95FF' : '3px solid transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = 'linear-gradient(90deg, rgba(79,127,255,0.15) 0%, transparent 100%)';
                      e.currentTarget.style.color = '#FFFFFF';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = 'transparent';
                      e.currentTarget.style.color = '#A0A0A0';
                    }
                  }}
                  data-testid={`nav-${item.name.toLowerCase().replace(/\s+/g, '-')}`}
                >
                  <Icon size={20} />
                  {sidebarOpen && <span className="text-sm font-medium">{item.name}</span>}
                </motion.div>
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Mobile backdrop — only visible when drawer is open on mobile */}
      {mobileSidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/60 backdrop-blur-sm z-30"
          onClick={() => setMobileSidebarOpen(false)}
          data-testid="sidebar-mobile-backdrop"
        />
      )}

      <div className="flex-1 flex flex-col overflow-hidden relative z-10">
        <header
          className="h-16 flex items-center justify-between px-4 md:px-6 gap-2"
          style={{
            background: 'rgba(0, 0, 0, 0.55)',
            backdropFilter: 'blur(16px)',
            borderBottom: '1px solid rgba(79, 127, 255, 0.2)',
          }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setMobileSidebarOpen(true)}
              className="md:hidden text-white hover:bg-[#4F7FFF]/10 shrink-0"
              data-testid="mobile-sidebar-toggle"
              aria-label="Open menu"
            >
              <Menu size={22} />
            </Button>
            <h2 className="text-base md:text-lg font-semibold text-white truncate" data-testid="page-title">
              {(() => {
                for (const it of navigation) {
                  if (it.path === location.pathname) return it.name;
                  if (it.group && it.children) {
                    const c = it.children.find(c => c.path === location.pathname);
                    if (c) return `${it.name} → ${c.name}`;
                  }
                }
                return "Dashboard";
              })()}
            </h2>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <div className="hidden sm:block">
              <LocalPCStatusBadge />
            </div>
            <ThemeToggle />
            <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="flex items-center gap-2 text-white hover:bg-[#4F7FFF]/10 px-2" data-testid="user-menu">
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center transition-all duration-300 hover:scale-110 shrink-0"
                  style={{ background: 'linear-gradient(135deg, #4F7FFF 0%, #3D66D9 100%)', boxShadow: '0 4px 14px rgba(79,127,255,0.4)' }}
                >
                  <User size={18} />
                </div>
                <span className="text-sm hidden sm:inline">{user.name || "User"}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48 bg-black/95 border-[#4F7FFF]/30 text-white backdrop-blur-xl">
              {!isSubUser && (
                <DropdownMenuItem onClick={() => navigate("/settings")} data-testid="settings-button" className="hover:bg-[#4F7FFF]/20 focus:bg-[#4F7FFF]/20">
                  <Settings size={16} className="mr-2" />
                  Settings
                </DropdownMenuItem>
              )}
              {!isSubUser && <DropdownMenuSeparator className="bg-[#4F7FFF]/20" />}
              <DropdownMenuItem onClick={handleLogout} data-testid="logout-button" className="hover:bg-[#4F7FFF]/20 focus:bg-[#4F7FFF]/20">
                <LogOut size={16} className="mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          </div>
        </header>

        <main className="flex-1 overflow-auto data-testid-main" data-testid="main-content" style={{ backgroundColor: 'transparent' }}>
          <CloudModeBanner />
          <UpdateBanner />
          <BannerBar />
          <div className="p-4 md:p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 1.02 }}
              transition={{ duration: 0.35, ease: [0.43, 0.13, 0.23, 0.96] }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
          </div>
        </main>
      </div>
    </div>
  );
}
