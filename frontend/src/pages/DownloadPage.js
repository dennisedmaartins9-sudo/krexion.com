import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import axios from "axios";
import {
  Sparkles, Download, Shield, Cpu, HardDrive, Wifi,
  Check, Copy, ArrowRight, Lock, KeyRound, AlertCircle, Loader2, Mail,
} from "lucide-react";
import { toast } from "sonner";
import WavyBackground from "../components/WavyBackground";
import PublicMobileMenu from "../components/PublicMobileMenu";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const INSTALLER_SHA256 = "b21b9f7d7803d3748dfa3e41d5d5a5eee4127b3b592bf2a56395275f6a1502bc";

export default function DownloadPage() {
  // ── Installer info (native-exe vs legacy-zip) ────────────────────
  // The download flow + UI copy differ between the new white-label
  // single-.exe install and the legacy Docker-based ZIP. We fetch
  // /api/system/installer-info once on mount to know which to show.
  const [installerInfo, setInstallerInfo] = useState({
    kind: "legacy-zip",
    version: "1.0.4",
    size_bytes: null,
  });

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/system/installer-info`).then((r) => {
      if (!cancelled && r.data) setInstallerInfo(r.data);
    }).catch(() => { /* ignore — UI just shows legacy defaults */ });
    return () => { cancelled = true; };
  }, []);

  const isNativeExe = installerInfo.kind === "native-exe";
  const installerVersion = installerInfo.version || "1.0.4";
  const installerSizeLabel = isNativeExe
    ? (installerInfo.size_bytes
        ? `~${Math.round(installerInfo.size_bytes / (1024 * 1024))} MB`
        : "~300 MB")
    : "~20 KB ZIP";
  // ── License-gated download state ───────────────────────────────
  // 2026-05: Customers must enter their KRX-XXXX-XXXX-XXXX-XXXX key
  // BEFORE the installer ZIP can be downloaded. The backend verifies
  // the key (not revoked / not expired) and streams a personalized
  // ZIP with the key auto-embedded in `license-key.txt`, which the
  // installer reads to pre-fill LICENSE_KEY= in the generated .env.
  const [licenseKey, setLicenseKey] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [verified, setVerified] = useState(null); // { license, max_pcs, machines_used, machines_remaining }

  const formatKey = (raw) => {
    // KRX-XXXX-XXXX-XXXX-XXXX — auto-format as user types/pastes.
    const stripped = (raw || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!stripped) return "";
    let core = stripped.startsWith("KRX") ? stripped.slice(3) : stripped;
    core = core.slice(0, 16);
    const parts = [];
    for (let i = 0; i < core.length; i += 4) parts.push(core.slice(i, i + 4));
    return "KRX-" + parts.join("-");
  };

  const handleKeyChange = (e) => {
    setLicenseKey(formatKey(e.target.value));
    if (verified) setVerified(null); // re-verification required after edit
  };

  const verifyKey = async () => {
    const key = (licenseKey || "").trim().toUpperCase();
    if (!/^KRX-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(key)) {
      toast.error("License key must look like KRX-XXXX-XXXX-XXXX-XXXX");
      return;
    }
    setVerifying(true);
    try {
      const r = await axios.post(`${API}/license/verify-for-download`, { license_key: key });
      if (r.data?.ok) {
        setVerified(r.data);
        toast.success("License verified! You can now download the installer.");
      } else {
        toast.error(r.data?.reason || "Could not verify license.");
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || "License verification failed.";
      toast.error(typeof detail === "string" ? detail : "License verification failed.");
      setVerified(null);
    } finally {
      setVerifying(false);
    }
  };

  const downloadInstaller = async () => {
    const key = (licenseKey || "").trim().toUpperCase();
    if (!verified) return;
    setDownloading(true);
    try {
      // ── Native-exe flow ───────────────────────────────────────────
      // Backend responds with a 302 redirect to the GitHub Release
      // .exe asset. We open it in a new tab so the browser handles the
      // download natively (no in-memory blob → no 300 MB memory spike,
      // no axios timeout).
      if (isNativeExe) {
        const url = `${API}/license/download-installer/${encodeURIComponent(key)}`;
        // Use a hidden anchor so the request is sent with credentials
        // (cookies) and the browser follows the 302 automatically.
        const a = document.createElement("a");
        a.href = url;
        a.target = "_self";
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        a.remove();
        toast.success("Krexion installer download started.");
        return;
      }

      // ── Legacy-zip flow (backwards compat) ───────────────────────
      const r = await axios.get(`${API}/license/download-installer/${encodeURIComponent(key)}`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/zip" }));
      const a = document.createElement("a");
      a.href = url;
      const tail = key.replace(/-/g, "").slice(-8);
      a.download = `Krexion-User-Package-${tail}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Installer downloaded with your license pre-embedded.");
    } catch (e) {
      const detail = e?.response?.data?.detail
        || (e?.response?.status === 410 ? "License is no longer valid." : "Download failed.");
      toast.error(typeof detail === "string" ? detail : "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  const copyHash = async () => {
    try {
      await navigator.clipboard.writeText(INSTALLER_SHA256);
      toast.success("SHA-256 hash copied!");
    } catch {
      toast.error("Could not copy");
    }
  };

  return (
    <div className="min-h-screen bg-black text-white relative" data-testid="download-page">
      <WavyBackground />

      {/* Ambient backdrop — blue glow */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-32 -left-32 w-[520px] h-[520px] rounded-full bg-blue-500/15 blur-[140px]" />
        <div className="absolute top-1/3 -right-40 w-[460px] h-[460px] rounded-full bg-cyan-500/10 blur-[140px]" />
      </div>

      {/* Nav */}
      <header className="border-b border-white/5 backdrop-blur-md sticky top-0 z-50 bg-black/70">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2" data-testid="download-logo">
            <Sparkles className="text-blue-400" size={22} />
            <span className="text-xl font-bold tracking-tight">KREXION</span>
          </Link>
          <nav className="hidden md:flex items-center gap-5 text-sm">
            <Link to="/pricing" className="text-zinc-400 hover:text-white">Pricing</Link>
            <Link to="/download" className="text-white">Download</Link>
            <Link to="/guide" className="text-zinc-400 hover:text-white">Guide</Link>
            <Link to="/login" className="text-zinc-400 hover:text-white">Login</Link>
          </nav>
          <PublicMobileMenu
            accent="blue"
            ctaTo="/pricing"
            ctaLabel="Get started"
            links={[
              { to: "/", label: "Home" },
              { to: "/pricing", label: "Pricing" },
              { to: "/download", label: "Download" },
              { to: "/guide", label: "Guide" },
              { to: "/login", label: "Login" },
            ]}
          />
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-6 pt-20 pb-10 text-center">
        <div className="inline-flex items-center gap-2 bg-white/5 border border-white/10 rounded-full px-4 py-1.5 mb-6 text-xs">
          <Download size={12} className="text-[#3B82F6]" />
          Optional desktop install • Version {installerVersion} • Windows 10/11 (64-bit)
        </div>
        <h1 className="text-5xl sm:text-6xl font-bold tracking-tight mb-5 leading-tight">
          Download <span className="text-[#3B82F6]">Krexion</span>
        </h1>
        <p className="text-lg text-[#A1A1AA] max-w-2xl mx-auto mb-3">
          The Krexion dashboard works fully online at <Link to="/login" className="text-white underline hover:text-[#3B82F6]">krexion.com/login</Link>.
        </p>
        <p className="text-sm text-[#71717A] max-w-xl mx-auto mb-9">
          This installer is only needed if you want to run heavy local features like Real User Traffic, Form Filler, or CPI Worker on your own PC.
        </p>

        {/* 2026-06 — Two-button download CTA (Windows Native vs Mac/Linux Electron).
            Customer-driven copy: heavy operators (RUT / Form Filler /
            150+ concurrent jobs) belong on the NATIVE installer because
            it leaves ~400 MB more RAM available for Playwright Chromium
            workers vs Electron (which spends that RAM on its own UI
            runtime). Electron is offered as the cross-platform path
            for Mac/Linux customers — it has built-in auto-update which
            the Native installer doesn't (Native needs a manual
            reinstall when a new version ships, but we mirror
            Krexion-Setup-latest.exe so the URL stays stable forever).
            Both installers fully embed mongo + backend + frontend; the
            only difference is the UI runtime.
            */}
        <div className="flex flex-col sm:flex-row items-stretch justify-center gap-4 mb-4">
          {/* WINDOWS — Native (recommended for heavy users) */}
          <a
            href="https://krexion.com/downloads/windows/Krexion-Setup-latest.exe"
            download
            data-testid="download-windows-native-btn"
            className="group flex-1 max-w-sm bg-[#3B82F6] hover:bg-[#60A5FA] text-black font-semibold px-6 py-4 rounded-xl transition shadow-xl shadow-[#3B82F6]/30 text-left"
          >
            <div className="flex items-center gap-3">
              {/* Windows logo (4-square tiles) */}
              <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                <path d="M3 5.5L10.5 4.5V11.5H3V5.5ZM3 12.5H10.5V19.5L3 18.5V12.5ZM11.5 4.4L21 3V11.5H11.5V4.4ZM11.5 12.5H21V21L11.5 19.6V12.5Z"/>
              </svg>
              <div className="flex-1">
                <div className="text-[10px] uppercase tracking-wider opacity-70 font-bold mb-0.5">Recommended for heavy jobs</div>
                <div className="text-base font-bold leading-tight">Download for Windows</div>
                <div className="text-[11px] opacity-80 mt-0.5 font-normal">Native installer · v{installerVersion} · ~571 MB · 64-bit</div>
              </div>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="group-hover:translate-y-0.5 transition-transform"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            </div>
          </a>

          {/* MAC / LINUX — Electron */}
          <a
            href="https://krexion.com/downloads/desktop/Krexion-Desktop-Setup-latest.exe"
            download
            data-testid="download-mac-linux-electron-btn"
            className="group flex-1 max-w-sm bg-white/[0.04] hover:bg-white/[0.08] border border-white/15 text-white font-semibold px-6 py-4 rounded-xl transition text-left"
          >
            <div className="flex items-center gap-3">
              {/* Apple + Linux Tux generic platform icon */}
              <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                <path d="M17.05 13.34c-.02-2.11 1.72-3.13 1.8-3.18-.98-1.44-2.51-1.64-3.06-1.66-1.3-.13-2.55.77-3.21.77-.66 0-1.69-.75-2.78-.73-1.43.02-2.75.83-3.49 2.11-1.49 2.58-.38 6.4 1.07 8.5.71 1.03 1.55 2.18 2.65 2.14 1.07-.04 1.47-.69 2.76-.69s1.65.69 2.78.67c1.15-.02 1.87-1.04 2.57-2.07.81-1.19 1.14-2.34 1.16-2.4-.03-.01-2.22-.85-2.25-3.36zM14.94 7.27c.58-.71 1-1.69.88-2.67-.85.04-1.89.57-2.49 1.27-.54.62-1.01 1.63-.88 2.59.95.07 1.91-.48 2.49-1.19z"/>
              </svg>
              <div className="flex-1">
                <div className="text-[10px] uppercase tracking-wider opacity-70 font-bold mb-0.5 text-[#A1A1AA]">Cross-platform · Auto-update</div>
                <div className="text-base font-bold leading-tight">Download for Mac / Linux</div>
                <div className="text-[11px] opacity-70 mt-0.5 font-normal">Electron build · v{installerVersion} · ~579 MB · auto-updates</div>
              </div>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="group-hover:translate-y-0.5 transition-transform"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            </div>
          </a>
        </div>
        <p className="text-xs text-[#71717A] max-w-2xl mx-auto mb-10">
          <strong className="text-[#A1A1AA]">Not sure which?</strong> If you're on Windows and plan to run heavy
          jobs (Real User Traffic, Form Filler, 50+ concurrent visits), pick the <span className="text-white">Native</span> installer
          on the left — it leaves more RAM free for the browser workers and stays stable under load.
          The <span className="text-white">Mac / Linux</span> build also runs on Windows if you prefer
          built-in auto-update over the small RAM premium.
        </p>

        {/* License-gated download card */}
        <div
          data-testid="license-gate-card"
          className="max-w-xl mx-auto bg-white/[0.03] border border-white/10 rounded-2xl p-6 sm:p-8 text-left backdrop-blur-sm"
        >
          <div className="flex items-center gap-2 mb-1">
            <KeyRound size={18} className="text-[#3B82F6]" />
            <h3 className="text-lg font-semibold text-white">
              {verified ? "License verified" : "Enter your license key"}
            </h3>
          </div>
          <p className="text-xs text-[#A1A1AA] mb-5">
            {verified
              ? "Your key will be auto-embedded inside the installer — no manual copy needed on your PC."
              : "Purchase a license first, then enter the KRX-XXXX-XXXX-XXXX-XXXX key we emailed you."}
          </p>

          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              data-testid="license-key-input"
              value={licenseKey}
              onChange={handleKeyChange}
              onKeyDown={(e) => { if (e.key === "Enter" && !verified) verifyKey(); }}
              placeholder="KRX-XXXX-XXXX-XXXX-XXXX"
              maxLength={23}
              spellCheck={false}
              autoCapitalize="characters"
              className="flex-1 bg-black/40 border border-white/10 rounded-lg px-4 py-3 font-mono tracking-wider text-white placeholder:text-[#52525B] focus:outline-none focus:border-[#3B82F6]"
            />
            {!verified ? (
              <button
                type="button"
                onClick={verifyKey}
                disabled={verifying || !licenseKey}
                data-testid="verify-license-button"
                className="inline-flex items-center justify-center gap-2 bg-[#3B82F6] hover:bg-[#60A5FA] disabled:opacity-50 disabled:cursor-not-allowed text-black font-semibold px-6 py-3 rounded-lg transition"
              >
                {verifying ? <Loader2 size={16} className="animate-spin" /> : <Shield size={16} />}
                {verifying ? "Verifying…" : "Verify Key"}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => { setVerified(null); }}
                data-testid="change-license-key-button"
                className="inline-flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 text-white px-4 py-3 rounded-lg transition border border-white/10 text-sm"
              >
                Change key
              </button>
            )}
          </div>

          {verified && (
            <div data-testid="license-info-block" className="mt-5 bg-[#10B981]/10 border border-[#10B981]/30 rounded-xl p-4 text-sm">
              <div className="flex items-center gap-2 text-[#34D399] font-semibold mb-2">
                <Check size={16} /> License OK — Status: {verified.license?.status || "active"}
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs text-[#A1A1AA]">
                {verified.license?.email && (
                  <div className="col-span-2 truncate">
                    <span className="text-[#71717A]">Issued to:</span>{" "}
                    <span className="text-white">{verified.license.email}</span>
                  </div>
                )}
                {typeof verified.max_pcs === "number" && (
                  <div>
                    <span className="text-[#71717A]">PCs allowed:</span>{" "}
                    <span className="text-white">{verified.max_pcs}</span>
                  </div>
                )}
                {typeof verified.machines_remaining === "number" && (
                  <div>
                    <span className="text-[#71717A]">Slots left:</span>{" "}
                    <span className="text-white">{verified.machines_remaining}</span>
                  </div>
                )}
                {verified.license?.subscription_ends_at && (
                  <div className="col-span-2">
                    <span className="text-[#71717A]">Renews:</span>{" "}
                    <span className="text-white">
                      {new Date(verified.license.subscription_ends_at).toLocaleDateString()}
                    </span>
                  </div>
                )}
                {verified.license?.trial_ends_at && verified.license?.status === "trial" && (
                  <div className="col-span-2">
                    <span className="text-[#71717A]">Trial ends:</span>{" "}
                    <span className="text-white">
                      {new Date(verified.license.trial_ends_at).toLocaleDateString()}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="mt-6 flex flex-col items-center">
            <button
              type="button"
              onClick={downloadInstaller}
              disabled={!verified || downloading}
              data-testid="download-installer-button"
              className={`inline-flex items-center gap-3 font-bold px-10 py-4 rounded-xl transition shadow-2xl w-full sm:w-auto justify-center
                ${verified
                  ? "bg-[#3B82F6] hover:bg-[#60A5FA] text-black shadow-[#2563EB]/30 cursor-pointer"
                  : "bg-white/5 text-[#52525B] cursor-not-allowed shadow-none border border-white/5"}`}
            >
              {downloading ? <Loader2 size={20} className="animate-spin" /> : verified ? <Download size={20} /> : <Lock size={20} />}
              {downloading
                ? "Preparing your installer…"
                : verified
                  ? (isNativeExe ? "Download Krexion for Windows" : "Download installer (.zip)")
                  : "Verify key to unlock download"}
              {verified && !downloading && <ArrowRight size={18} />}
            </button>
            <div className="mt-3 text-xs text-[#71717A] text-center">
              {isNativeExe
                ? `${installerSizeLabel} • Single .exe installer • License key entered during install`
                : `${installerSizeLabel} • License key auto-embedded • Auto-downloads Krexion runtime (~600 MB) during install`}
            </div>
          </div>

          {!verified && (
            <div data-testid="no-license-help" className="mt-6 pt-5 border-t border-white/5 flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-[#A1A1AA]">
                <AlertCircle size={14} className="text-[#F59E0B] shrink-0" />
                Don't have a license key yet?
              </div>
              <div className="flex items-center gap-2">
                <Link
                  to="/pricing"
                  data-testid="purchase-license-link"
                  className="inline-flex items-center gap-1.5 text-xs bg-[#3B82F6]/15 border border-[#3B82F6]/40 text-[#60A5FA] hover:bg-[#3B82F6]/25 px-3 py-1.5 rounded-md transition"
                >
                  See plans <ArrowRight size={12} />
                </Link>
                <a
                  href="mailto:admin@krexion.local?subject=License%20key%20request"
                  data-testid="contact-admin-link"
                  className="inline-flex items-center gap-1.5 text-xs bg-white/5 hover:bg-white/10 text-white px-3 py-1.5 rounded-md transition border border-white/10"
                >
                  <Mail size={12} /> Contact admin
                </a>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Pre-checks */}
      <section className="max-w-5xl mx-auto px-6 py-10">
        <h2 className="text-sm uppercase tracking-widest text-[#3B82F6] mb-4 text-center">System requirements</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { icon: HardDrive, t: "20 GB free disk", d: "SSD recommended" },
            { icon: Cpu, t: "8 GB RAM", d: "16 GB for Pro/Business" },
            { icon: Shield, t: "Windows 10/11 64-bit", d: "Admin rights needed" },
            { icon: Wifi, t: "Stable internet", d: "For first-time install" },
          ].map((s, i) => (
            <div key={i} className="bg-white/[0.03] border border-white/10 rounded-xl p-5 text-center">
              <s.icon size={20} className="text-[#3B82F6] mx-auto mb-2" />
              <div className="font-semibold text-sm mb-1">{s.t}</div>
              <div className="text-xs text-[#71717A]">{s.d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Install steps */}
      <section className="max-w-4xl mx-auto px-6 py-10">
        <div className="bg-white/[0.02] border border-white/10 rounded-2xl p-8">
          <h2 className="text-xl font-bold mb-6">Installation in {isNativeExe ? "3" : "4"} steps</h2>
          <ol className="space-y-5">
            {(isNativeExe
              ? [
                  {
                    t: "Run Krexion-Setup.exe",
                    d: "Double-click the downloaded file. Click \"Yes\" on the UAC prompt to give Krexion administrator access.",
                  },
                  {
                    t: "Enter your license key",
                    d: "The installer wizard will ask for your KRX-XXXX-XXXX-XXXX-XXXX key. Paste it and click Next.",
                  },
                  {
                    t: "Wait for install to finish",
                    d: "Krexion installs silently in ~60-90 seconds. Your dashboard opens automatically at http://127.0.0.1:3000 when done.",
                  },
                ]
              : [
                  {
                    t: "Download & extract",
                    d: "Right-click the ZIP → \"Extract All\". Keep all files together in one folder.",
                  },
                  {
                    t: "Run INSTALL.bat",
                    d: "Double-click INSTALL.bat. Click \"Yes\" on the UAC prompt. Wait 20–30 minutes (one-time setup).",
                  },
                  {
                    t: "Login or register",
                    d: "Browser opens automatically. Use the email + password from your Krexion welcome email, or register a new account.",
                  },
                  {
                    t: "Enter license key",
                    d: "In the Setup Wizard, paste the license key from your email. Krexion activates and you're ready.",
                  },
                ]
            ).map((step, i) => (
              <li key={i} className="flex gap-4">
                <div className="shrink-0 w-9 h-9 rounded-full bg-[#3B82F6] text-black font-bold flex items-center justify-center text-sm">
                  {i + 1}
                </div>
                <div className="flex-1 pt-1">
                  <div className="font-semibold mb-1">{step.t}</div>
                  <p className="text-sm text-[#A1A1AA] leading-relaxed">{step.d}</p>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-7 p-4 bg-[#F59E0B]/5 border border-[#F59E0B]/20 rounded-lg">
            <div className="flex gap-2 items-start text-sm">
              <Lock size={15} className="text-[#F59E0B] shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-[#F59E0B]">No license yet?</span>{" "}
                <span className="text-[#A1A1AA]">
                  Buy one at{" "}
                  <Link to="/pricing" className="text-[#3B82F6] hover:text-white underline">
                    krexion.com/pricing
                  </Link>{" "}
                  starting at 3 USDT for a 1-day trial.
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* File integrity */}
      {!isNativeExe && (
      <section className="max-w-4xl mx-auto px-6 py-10">
        <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-3">
            <Check size={16} className="text-[#22C55E]" />
            <span className="text-sm font-semibold">File integrity (SHA-256)</span>
          </div>
          <div className="flex items-center gap-2 bg-[#0a0a0f] border border-white/10 rounded-md p-3 font-mono text-[11px] sm:text-xs break-all">
            <span className="flex-1 text-[#3B82F6]">{INSTALLER_SHA256}</span>
            <button
              onClick={copyHash}
              className="text-[#71717A] hover:text-white shrink-0"
              data-testid="copy-sha-button"
              title="Copy hash"
            >
              <Copy size={13} />
            </button>
          </div>
          <p className="text-xs text-[#71717A] mt-3">
            Verify with PowerShell: <code className="bg-white/5 px-1.5 py-0.5 rounded text-[#3B82F6]">Get-FileHash -Algorithm SHA256 Krexion-User-Package.zip</code>
          </p>
        </div>
      </section>
      )}

      {/* FAQ */}
      <section className="max-w-4xl mx-auto px-6 pb-20">
        <h2 className="text-lg font-bold mb-4">Common questions</h2>
        <div className="space-y-3">
          {[
            {
              q: "Will any third-party tools pop up during install?",
              a: "No. The installer runs in the background and only shows Krexion-branded progress. Helper engines run silently — you'll never see them.",
            },
            {
              q: "Can I install on multiple PCs?",
              a: "Yes, up to your plan limit (Starter: 1, Pro: 3, Business: 10, Trial: 1). Each install is bound to a unique machine fingerprint.",
            },
            {
              q: "I lost my license email — what now?",
              a: <>Login at <Link to="/login" className="text-[#3B82F6]">krexion.com/login</Link> with the credentials we emailed; your license is shown there. Or email <a href="mailto:support@krexion.com" className="text-[#3B82F6]">support@krexion.com</a>.</>,
            },
            {
              q: "Does Krexion run after PC restart?",
              a: "Yes — Krexion auto-starts in the background. Open the desktop shortcut to access the dashboard.",
            },
          ].map((f, i) => (
            <details key={i} className="bg-white/[0.03] border border-white/10 rounded-xl group" data-testid={`download-faq-${i}`}>
              <summary className="px-5 py-4 cursor-pointer text-sm font-medium hover:bg-white/[0.02] list-none flex items-center justify-between">
                {f.q}
                <span className="text-[#A1A1AA] group-open:rotate-180 transition-transform">▾</span>
              </summary>
              <div className="px-5 pb-4 text-sm text-[#A1A1AA] leading-relaxed">{f.a}</div>
            </details>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[#71717A]">
          <div className="flex items-center gap-2">
            <Sparkles className="text-[#3B82F6]" size={14} />
            <span className="font-semibold text-white">KREXION</span>
            <span>© {new Date().getFullYear()}</span>
          </div>
          <div className="flex items-center gap-5">
            <Link to="/pricing" className="hover:text-white">Pricing</Link>
            <Link to="/guide" className="hover:text-white">Guide</Link>
            <Link to="/login" className="hover:text-white">Login</Link>
            <a href="mailto:support@krexion.com" className="hover:text-white">Support</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
