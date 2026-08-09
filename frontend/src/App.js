import { useEffect, useState } from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { PageTransition } from "./components/PageTransitions";
import LoginPage from "./pages/LoginPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import CustomerLayout from "./components/CustomerLayout";
import Dashboard from "./pages/Dashboard";
import LinksPage from "./pages/LinksPage";
import ClicksPage from "./pages/ClicksPage";
import ConversionsPage from "./pages/ConversionsPage";
import ProxiesPage from "./pages/ProxiesPage";
import SettingsPage from "./pages/SettingsPage";
import ReferrerStatsPage from "./pages/ReferrerStatsPage";
// import ImportTrafficPage from "./pages/ImportTrafficPage";  // removed v2.6.1 — merged into RUT
import EmailCheckerPage from "./pages/EmailCheckerPage";
import PhoneCheckerPage from "./pages/PhoneCheckerPage";
import SeparateDataPage from "./pages/SeparateDataPage";
import UserAgentGeneratorPage from "./pages/UserAgentGeneratorPage";
import UserAgentCheckerPage from "./pages/UserAgentCheckerPage";
// import FormFillerPage from "./pages/FormFillerPage";  // removed v2.6.1 — merged into RUT
import RealUserTrafficPage from "./pages/RealUserTrafficPage";
import BrowserProfilesPage from "./pages/BrowserProfilesPage";
import VisualRecorderPage from "./pages/VisualRecorderPage";
import UploadedThingsPage from "./pages/UploadedThingsPage";
import AdsPowerPage from "./pages/AdsPowerPage";
import CPIOffersPage from "./pages/CPIOffersPage";
import CPIJobsPage from "./pages/CPIJobsPage";
import CPIJobDetailPage from "./pages/CPIJobDetailPage";
import CPIDevicesPage from "./pages/CPIDevicesPage";
import CPIDashboardPage from "./pages/CPIDashboardPage";
import CPISmartLinksPage from "./pages/CPISmartLinksPage";
import CPIWorkerSetupPage from "./pages/CPIWorkerSetupPage";
import SystemHealthPage from "./pages/SystemHealthPage";
import AdminLoginPage from "./pages/AdminLoginPage";
import AdminDashboard from "./pages/AdminDashboard";
import LicenseAdminPage from "./pages/LicenseAdminPage";
import AnimationDemoPage from "./pages/AnimationDemoPage";
import BackgroundPreviewPage from "./pages/BackgroundPreviewPage";
import PricingPage from "./pages/PricingPage";
import CheckoutPage from "./pages/CheckoutPage";
import OrderStatusPage from "./pages/OrderStatusPage";
import CryptoOrdersPage from "./pages/CryptoOrdersPage";
import HomePage from "./pages/HomePage";
import DownloadPage from "./pages/DownloadPage";
import StatusPage from "./pages/StatusPage";
import DebugConsole from "./components/DebugConsole";
import GuidePage from "./pages/GuidePage";
import SyncHeartbeatsPage from "./pages/SyncHeartbeatsPage";
import ReleasesAdminPage from "./pages/ReleasesAdminPage";
import PlansAdminPage from "./pages/PlansAdminPage";
import SystemMaintenancePage from "./pages/SystemMaintenancePage";
import SiteContentAdminPage from "./pages/SiteContentAdminPage";
import LicensePage from "./pages/LicensePage";
import RPAStudioPage from "./pages/RPAStudioPage";
import RPAWorkflowsPage from "./pages/RPAWorkflowsPage";
import RPARunsPage from "./pages/RPARunsPage";
import AdminBannersPage from "./pages/AdminBannersPage";
import { Toaster } from "./components/ui/sonner";
import { BrandingProvider } from "./context/BrandingContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ModeProvider } from "./context/ModeContext";
import LocalPCOfflineDialog from "./components/LocalPCOfflineDialog";
import "./utils/cloudGateInterceptor";

// Apply blue theme to body
if (typeof document !== 'undefined') {
  document.body.classList.add('blue-theme');
}

function PrivateRoute({ children }) {
  const token = localStorage.getItem("token");
  return token ? children : <Navigate to="/login" />;
}

function PublicHome() {
  const token = localStorage.getItem("token");
  // 2026-06 — Edit-mode escape hatch. When the admin clicks
  // "Edit Website" we open `/?edit=1` in a new tab. If that browser
  // happens to ALSO have a regular-user `token` in localStorage (very
  // common — most admins are also customers) the old code would
  // bounce them to /dashboard and they'd never see the live editor.
  // Allow the redirect to be skipped when ?edit=1 + adminToken are
  // present so the in-place editor on HomePage can mount.
  // Desktop (Electron) builds skip the marketing HomePage entirely: the
  // bundled app is installed locally, so a customer landing on "/" should
  // be taken straight to the login form, not to the public marketing site.
  // Cloud builds keep the original HomePage behavior.
  if (process.env.REACT_APP_DESKTOP_BUILD === '1') {
    return token ? <Navigate to="/dashboard" replace /> : <Navigate to="/login" replace />;
  }
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("edit") === "1" && localStorage.getItem("adminToken")) {
      return <HomePage />;
    }
  } catch { /* ignore */ }
  return token ? <Navigate to="/dashboard" replace /> : <HomePage />;
}

function AdminRoute({ children }) {
  const adminToken = localStorage.getItem("adminToken");
  return adminToken ? children : <Navigate to="/admin" />;
}

// Feature-protected route component
function FeatureRoute({ children, feature }) {
  const user = JSON.parse(localStorage.getItem("user") || "{}");
  const features = user.features || {};
  const isSubUser = user.is_sub_user === true;
  
  // Settings is ONLY for main users, and only if not explicitly disabled
  if (feature === "settings") {
    // Sub-users can NEVER access settings
    if (isSubUser) {
      return <Navigate to="/dashboard" replace />;
    }
    // Main users can access unless explicitly set to false
    if (features.settings === false) {
      return <Navigate to="/dashboard" replace />;
    }
    return children;
  }
  
  // Backward compat: new granular features fall back to "import_data" legacy flag
  const LEGACY_IMPORT_GROUP = new Set([
    "email_checker", "phone_checker", "separate_data", "import_traffic", "real_traffic", "ua_generator", "ua_checker"
  ]);

  // If feature is specified and not enabled, redirect to dashboard
  if (feature) {
    const explicit = features[feature];
    const hasAccess =
      explicit === true ||
      (explicit === undefined && LEGACY_IMPORT_GROUP.has(feature) && features.import_data === true);
    if (!hasAccess) {
      return <Navigate to="/dashboard" replace />;
    }
  }
  
  return children;
}

function App() {
  return (
    <BrandingProvider>
      <ThemeProvider>
        <ModeProvider>
        <div className="App">
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/admin" element={<AdminLoginPage />} />
            <Route path="/animation-demo" element={<AnimationDemoPage />} />
            <Route path="/bg-preview" element={<BackgroundPreviewPage />} />
            <Route path="/pricing" element={<PricingPage />} />
            <Route path="/download" element={<DownloadPage />} />
            <Route path="/status" element={<StatusPage />} />
            <Route path="/guide" element={<GuidePage />} />
            <Route path="/checkout/:planId" element={<CheckoutPage />} />
            <Route path="/order/:orderId" element={<OrderStatusPage />} />
            <Route path="/admin/crypto-orders" element={
              <AdminRoute>
                <CryptoOrdersPage />
              </AdminRoute>
            } />
            <Route path="/admin/sync-heartbeats" element={
              <AdminRoute>
                <SyncHeartbeatsPage />
              </AdminRoute>
            } />
            <Route path="/admin/releases" element={
              <AdminRoute>
                <ReleasesAdminPage />
              </AdminRoute>
            } />
            <Route path="/admin/plans" element={
              <AdminRoute>
                <PlansAdminPage />
              </AdminRoute>
            } />
            <Route path="/admin/system-maintenance" element={
              <AdminRoute>
                <SystemMaintenancePage />
              </AdminRoute>
            } />
            <Route path="/admin/website-content" element={
              <AdminRoute>
                <SiteContentAdminPage />
              </AdminRoute>
            } />
            <Route path="/admin/dashboard" element={
              <AdminRoute>
                <AdminDashboard />
              </AdminRoute>
            } />
            <Route path="/" element={<PublicHome />} />
            <Route path="/admin/licenses" element={
              <AdminRoute>
                <LicenseAdminPage />
              </AdminRoute>
            } />
            <Route path="/admin/banners" element={
              <AdminRoute>
                <AdminBannersPage />
              </AdminRoute>
            } />
            <Route
              path="/*"
              element={
                <PrivateRoute>
                  <CustomerLayout>
                    <Routes>
                      <Route path="/dashboard" element={<Dashboard />} />
                      <Route path="/links" element={
                        <FeatureRoute feature="links">
                          <LinksPage />
                        </FeatureRoute>
                      } />
                      <Route path="/clicks" element={
                        <FeatureRoute feature="clicks">
                          <ClicksPage />
                        </FeatureRoute>
                      } />
                      <Route path="/conversions" element={
                        <FeatureRoute feature="conversions">
                          <ConversionsPage />
                        </FeatureRoute>
                      } />
                      <Route path="/proxies" element={
                        <FeatureRoute feature="proxies">
                          <ProxiesPage />
                        </FeatureRoute>
                      } />
                      <Route path="/profile-builder" element={
                        <FeatureRoute feature="profile_builder">
                          <AdsPowerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/referrers" element={
                        <FeatureRoute feature="clicks">
                          <ReferrerStatsPage />
                        </FeatureRoute>
                      } />
                      {/* Import Traffic + Form Filler pages removed (v2.6.1)
                        — functionality already exists inside Real User Traffic.
                        Legacy URLs redirect to /real-user-traffic. */}
                      <Route path="/import-traffic" element={<Navigate to="/real-user-traffic" replace />} />
                      <Route path="/email-checker" element={
                        <FeatureRoute feature="email_checker">
                          <EmailCheckerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/phone-checker" element={
                        <FeatureRoute feature="phone_checker">
                          <PhoneCheckerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/separate-data" element={
                        <FeatureRoute feature="separate_data">
                          <SeparateDataPage />
                        </FeatureRoute>
                      } />
                      <Route path="/ua-generator" element={
                        <FeatureRoute feature="ua_generator">
                          <UserAgentGeneratorPage />
                        </FeatureRoute>
                      } />
                      <Route path="/ua-checker" element={
                        <FeatureRoute feature="ua_checker">
                          <UserAgentCheckerPage />
                        </FeatureRoute>
                      } />
                      <Route path="/form-filler" element={<Navigate to="/real-user-traffic" replace />} />
                      <Route path="/real-user-traffic" element={
                        <FeatureRoute feature="real_user_traffic">
                          <RealUserTrafficPage />
                        </FeatureRoute>
                      } />
                      <Route path="/browser-profiles" element={
                        <FeatureRoute feature="real_user_traffic">
                          <BrowserProfilesPage />
                        </FeatureRoute>
                      } />
                      <Route path="/visual-recorder" element={
                        <FeatureRoute feature="real_user_traffic">
                          <VisualRecorderPage />
                        </FeatureRoute>
                      } />
                      <Route path="/rpa-studio" element={
                        <RPAWorkflowsPage />
                      } />
                      <Route path="/rpa-studio/:id" element={
                        <RPAStudioPage />
                      } />
                      <Route path="/rpa-runs" element={
                        <RPARunsPage />
                      } />
                      <Route path="/uploaded-things" element={
                        <FeatureRoute feature="real_user_traffic">
                          <UploadedThingsPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi" element={
                        <FeatureRoute feature="cpi">
                          <CPIDashboardPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi/offers" element={
                        <FeatureRoute feature="cpi">
                          <CPIOffersPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi/jobs" element={
                        <FeatureRoute feature="cpi">
                          <CPIJobsPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi/jobs/:id" element={
                        <FeatureRoute feature="cpi">
                          <CPIJobDetailPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi/devices" element={
                        <FeatureRoute feature="cpi">
                          <CPIDevicesPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi/smartlinks" element={
                        <FeatureRoute feature="cpi">
                          <CPISmartLinksPage />
                        </FeatureRoute>
                      } />
                      <Route path="/cpi/setup" element={
                        <FeatureRoute feature="cpi">
                          <CPIWorkerSetupPage />
                        </FeatureRoute>
                      } />
                      <Route path="/settings" element={
                        <FeatureRoute feature="settings">
                          <SettingsPage />
                        </FeatureRoute>
                      } />
                      <Route path="/system-health" element={<SystemHealthPage />} />
                      {/* v2.1.14 — customer-facing license dashboard */}
                      <Route path="/license" element={<LicensePage />} />
                    </Routes>
                  </CustomerLayout>
                </PrivateRoute>
              }
            />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-center" richColors closeButton style={{zIndex:99999}} />
        <DebugConsole />
        {/* 2026-05: Global modal for "your PC is offline" — pops up
            whenever a heavy-feature request is gated. See
            components/LocalPCOfflineDialog.js + utils/cloudGateInterceptor.js. */}
        <LocalPCOfflineDialog />
      </div>
      </ModeProvider>
      </ThemeProvider>
    </BrandingProvider>
  );
}

export default App;
