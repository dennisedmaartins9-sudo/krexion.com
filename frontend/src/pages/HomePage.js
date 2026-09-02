import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { motion } from "framer-motion";
import {
  Globe, Activity, Layers, Cpu, Shield, MailCheck,
  ArrowRight, Check, ChevronDown, Zap, Lock, Sparkles, Download,
} from "lucide-react";
import WavyBackground from "../components/WavyBackground";
import PublicMobileMenu from "../components/PublicMobileMenu";
import { EditModeProvider, useEditMode } from "../components/EditModeProvider";
import EditableText from "../components/EditableText";
import EditModeToolbar from "../components/EditModeToolbar";

// 2026-06 — Hero bottom-line: in normal view it shows a gradient
// (`bg-clip-text text-transparent` motion.span). In edit mode the
// gradient is dropped because EditableText's `inline-block` wrapper
// breaks bg-clip-text inheritance and makes the line invisible. Plain
// white still looks fine while editing — the gradient comes back the
// moment the admin exits edit mode.
function HeroBottomLine({ value }) {
  const { editMode } = useEditMode();
  if (editMode) {
    return (
      <span className="block text-white">
        <EditableText section="hero" field="h1_bottom" value={value} as="span" />
      </span>
    );
  }
  return (
    <motion.span
      initial={{ opacity: 0, y: 30, filter: "blur(8px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{ delay: 0.35, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      className="block bg-clip-text text-transparent"
      style={{
        backgroundImage: "linear-gradient(90deg, #60A5FA 0%, #3B82F6 25%, #93C5FD 50%, #3B82F6 75%, #60A5FA 100%)",
        backgroundSize: "200% 100%",
        animation: "krx-gradient 5s ease-in-out infinite",
      }}
    >
      {value}
    </motion.span>
  );
}

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Brand blue (matches dashboard / login page)
const BLUE = "#3B82F6";

// 2026-06 — Icon lookup so admin can pick a lucide-react icon by name
// in the Site Content CMS (`features[].icon`). Anything outside this
// map falls back to Sparkles so we never crash on a typo.
const ICONS = {
  Globe, Activity, Layers, Cpu, Shield, MailCheck,
  Zap, Lock, Sparkles, Check, ArrowRight, ChevronDown, MailCheck,
};
const getIcon = (name) => ICONS[name] || Sparkles;

// Built-in fallback content — used until the /api/site-content fetch
// completes (so the first paint isn't blank) AND when the API call
// fails entirely. Mirrors DEFAULT_SITE_CONTENT in
// backend/site_content_module.py.
const DEFAULT_CONTENT = {
  hero: {
    badge: "Cloud + Self-host • Pay with USDT • Links live 24/7",
    h1_top: "Real traffic.",
    h1_bottom: "Real conversions.",
    subtitle: "Manage your tracking, links and campaigns from anywhere in the world. Your krexion.com links stay live 24/7 — even when your PC is off.",
    cta_label: "See plans",
    cta_secondary_label: "How it works",
  },
  stats: [
    { value: "10M+", label: "Clicks delivered" },
    { value: "120+", label: "Countries supported" },
    { value: "99.9%", label: "Uptime" },
    { value: "<30 min", label: "License delivery" },
  ],
  features_intro: {
    eyebrow: "Built for scale",
    title: "Everything you need to run traffic at scale",
    subtitle: "From single landing-page tests to multi-thousand-PC campaigns — one platform, fully self-hosted under your license.",
  },
  features: [
    { icon: "Globe", title: "Cloud Dashboard — Login Anywhere", desc: "Manage links, clicks and campaigns from any browser, any device. Your dashboard lives at krexion.com, not stuck on one PC." },
    { icon: "Activity", title: "Always-On Tracking Links", desc: "Every link you generate runs at krexion.com/r/xxx — clicks keep flowing even when your computer is off, sleeping, or unplugged." },
    { icon: "Layers", title: "Massive Proxy Pool", desc: "Plug in residential, ISP or mobile proxies. Built-in checker validates them at scale across parallel batches." },
    { icon: "Cpu", title: "CPI Job Orchestrator", desc: "Run Cost-Per-Install campaigns across distributed worker devices with smart routing and per-device fingerprinting." },
    { icon: "Shield", title: "Form Filler + Real User Traffic", desc: "Auto-fill landing pages and emulate genuine human patterns through real Chrome — not headless bots." },
    { icon: "MailCheck", title: "Email Validation Suite", desc: "Verify deliverability, separate cleaned lists, and feed only valid leads into your campaigns." },
  ],
  pricing_intro: {
    eyebrow: "Pricing",
    title: "Simple plans, USDT only",
    subtitle: "One-time payments. Pay per month — no auto-renewal, no surprises.",
  },
  faq_intro: {
    eyebrow: "FAQ",
    title: "Questions, answered",
    subtitle: "",
  },
  faqs: [
    { q: "Do I need to install anything?", a: "No — Krexion runs fully online at krexion.com. Login, generate links, view clicks, manage campaigns from any browser. The optional desktop installer is only for heavy features like Real User Traffic and Form Filler." },
    { q: "Will my links die if I turn off my computer?", a: "Never. All your links live on the krexion.com cloud — they keep tracking clicks 24/7 regardless of whether your PC is on, off, sleeping, or in a different country." },
    { q: "How does payment work?", a: "We accept USDT (TRC-20) only. Pick a plan, send USDT to the wallet shown at checkout, paste your TxID, and your license + login credentials are delivered to your email within 30 minutes." },
    { q: "Do I need a credit card or bank?", a: "No. Everything runs on crypto — no subscriptions, no recurring charges, no bank required. Pay only for the months you use." },
    { q: "How many PCs can I activate?", a: "Cloud dashboard works on unlimited devices. For the optional desktop install: Starter 1 PC, Pro 3 PCs, Business 10 PCs, Trial 1 PC." },
    { q: "Can I get a refund?", a: "Yes — if your license is not delivered within 24 hours of TxID submission and on-chain confirmation, we refund in full. Otherwise sales are final." },
  ],
  footer: {
    tagline: "Real traffic. Real conversions. Self-hosted under your license.",
    copyright: "© 2026 Krexion. All rights reserved.",
  },
  nav: {
    features_label: "Features",
    pricing_label: "Pricing",
    download_label: "Download",
    guide_label: "Guide",
    faq_label: "FAQ",
    login_label: "Login",
    cta_label: "Get started",
  },
};

// Word-by-word reveal animation for the hero headline
const WORD_VARIANTS = {
  hidden: { opacity: 0, y: 40, filter: "blur(8px)" },
  show: (i) => ({
    opacity: 1, y: 0, filter: "blur(0px)",
    transition: { delay: i * 0.08, duration: 0.6, ease: [0.22, 1, 0.36, 1] },
  }),
};

function AnimatedWords({ text, className = "", accent = false }) {
  return (
    <span className={className}>
      {text.split(" ").map((word, i) => (
        <motion.span
          key={`${word}-${i}`}
          custom={i}
          initial="hidden"
          animate="show"
          variants={WORD_VARIANTS}
          className={`inline-block mr-3 ${accent ? "" : ""}`}
        >
          {word}
        </motion.span>
      ))}
    </span>
  );
}

export default function HomePage() {
  const [plans, setPlans] = useState([]);
  const [openFaq, setOpenFaq] = useState(0);
  // 2026-06 — site content fetched from CMS so admin can edit hero,
  // stats, features, FAQ and footer copy live without a redeploy.
  const [content, setContent] = useState(DEFAULT_CONTENT);

  // 2026-06 — live-edit helper. Replaces a whole list section
  // (`stats`, `features`, `faqs`) in one PUT call. The backend wholesale-
  // replaces list sections (see `_merge` in site_content_module.py) so
  // sending the full new list is the right contract.
  const saveContentList = async (listKey, list) => {
    try {
      const token = localStorage.getItem("adminToken") || localStorage.getItem("token");
      const r = await axios.put(`${API}/admin/site-content`, { [listKey]: list }, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setContent(r.data);
      // Lazy-load `sonner` toast through window so we don't add an
      // extra import for a single call site. (sonner is already
      // mounted globally via App.js.)
      try {
        const { toast } = await import("sonner");
        toast.success("Saved");
      } catch { /* toast optional */ }
      return true;
    } catch (e) {
      try {
        const { toast } = await import("sonner");
        toast.error(e?.response?.data?.detail || "Save failed");
      } catch { /* toast optional */ }
      return false;
    }
  };

  useEffect(() => {
    axios.get(`${API}/crypto/plans`)
      .then(r => setPlans(r.data.plans || []))
      .catch(() => setPlans([]));
    // Site content (CMS) — fall back to DEFAULT_CONTENT on any failure
    // so the public site is ALWAYS renderable even if Mongo is down.
    axios.get(`${API}/site-content`)
      .then(r => {
        if (r?.data && typeof r.data === "object") {
          // Shallow merge with defaults so partially-saved docs still
          // render every section.
          setContent({ ...DEFAULT_CONTENT, ...r.data,
            hero: { ...DEFAULT_CONTENT.hero, ...(r.data.hero || {}) },
            features_intro: { ...DEFAULT_CONTENT.features_intro, ...(r.data.features_intro || {}) },
            pricing_intro: { ...DEFAULT_CONTENT.pricing_intro, ...(r.data.pricing_intro || {}) },
            faq_intro: { ...DEFAULT_CONTENT.faq_intro, ...(r.data.faq_intro || {}) },
            footer: { ...DEFAULT_CONTENT.footer, ...(r.data.footer || {}) },
            nav: { ...DEFAULT_CONTENT.nav, ...(r.data.nav || {}) },
          });
        }
      })
      .catch(() => { /* defaults are fine */ });
  }, []);

  return (
    <EditModeProvider content={content} setContent={setContent}>
    <div className="min-h-screen bg-black text-white overflow-x-hidden relative" data-testid="home-page">
      <EditModeToolbar />
      <WavyBackground />

      {/* Soft blue ambient glows */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-32 -left-32 w-[520px] h-[520px] rounded-full bg-blue-500/15 blur-[140px]" />
        <div className="absolute top-1/3 -right-40 w-[460px] h-[460px] rounded-full bg-blue-600/15 blur-[140px]" />
        <div className="absolute bottom-0 left-1/3 w-[380px] h-[380px] rounded-full bg-cyan-500/10 blur-[120px]" />
      </div>

      {/* Nav */}
      <header className="border-b border-white/5 backdrop-blur-md sticky top-0 z-50 bg-black/70">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2" data-testid="home-logo">
            <Sparkles className="text-blue-400" size={22} />
            <span className="text-xl font-bold tracking-tight">KREXION</span>
          </Link>
          <nav className="hidden md:flex items-center gap-7 text-sm">
            <a href="#features" className="text-zinc-400 hover:text-white transition">{content.nav.features_label}</a>
            <a href="#pricing" className="text-zinc-400 hover:text-white transition">{content.nav.pricing_label}</a>
            <Link to="/download" className="text-zinc-400 hover:text-white transition" data-testid="nav-download">{content.nav.download_label}</Link>
            <Link to="/guide" className="text-zinc-400 hover:text-white transition" data-testid="nav-guide">{content.nav.guide_label}</Link>
            <a href="#faq" className="text-zinc-400 hover:text-white transition">{content.nav.faq_label}</a>
            <Link to="/login" className="text-zinc-400 hover:text-white transition" data-testid="nav-login">{content.nav.login_label}</Link>
            <Link
              to="/pricing"
              className="bg-blue-500 text-white px-4 py-1.5 rounded-md font-medium hover:bg-blue-400 transition shadow-lg shadow-blue-500/30"
              data-testid="nav-get-started"
            >
              {content.nav.cta_label}
            </Link>
          </nav>
          <PublicMobileMenu
            accent="blue"
            ctaTo="/pricing"
            ctaLabel={content.nav.cta_label}
            links={[
              { to: "#features", label: content.nav.features_label },
              { to: "#pricing", label: content.nav.pricing_label },
              { to: "/download", label: content.nav.download_label },
              { to: "/guide", label: content.nav.guide_label },
              { to: "#faq", label: content.nav.faq_label },
              { to: "/login", label: content.nav.login_label },
            ]}
          />
        </div>
      </header>

      {/* Hero */}
      <section className="relative max-w-7xl mx-auto px-6 pt-24 pb-24 text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.6 }}
          className="inline-flex items-center gap-2 bg-blue-500/10 border border-blue-500/30 rounded-full px-4 py-1.5 mb-7 text-xs backdrop-blur-sm"
        >
          <Zap size={12} className="text-blue-400" />
          <EditableText section="hero" field="badge" value={content.hero.badge}
            className="text-blue-100" />
        </motion.div>

        {/* Animated heading */}
        <h1 className="text-5xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight leading-[1.05] mb-6">
          <EditableText section="hero" field="h1_top" value={content.hero.h1_top}
            as="span" className="block">
            <AnimatedWords text={content.hero.h1_top} className="block" />
          </EditableText>
          {/* 2026-06 — the bottom line normally has a `bg-clip-text
              text-transparent` gradient. EditableText wraps its target in
              `display: inline-block`, which breaks bg-clip-text
              inheritance and made the gradient line render INVISIBLE in
              edit mode. Workaround: render plain (no gradient) when the
              admin is editing — the gradient comes back the moment they
              exit edit mode. */}
          <HeroBottomLine value={content.hero.h1_bottom} />
        </h1>

        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6, duration: 0.6 }}
          className="text-lg text-zinc-400 max-w-2xl mx-auto mb-9 leading-relaxed"
        >
          <EditableText section="hero" field="subtitle" value={content.hero.subtitle}
            as="span" multiline />
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8, duration: 0.6 }}
          className="flex flex-col sm:flex-row items-center justify-center gap-3"
        >
          <Link
            to="/pricing"
            className="group bg-blue-500 text-white font-semibold px-7 py-3.5 rounded-lg hover:bg-blue-400 transition inline-flex items-center gap-2 shadow-xl shadow-blue-500/30"
            data-testid="hero-cta-pricing"
          >
            <EditableText section="hero" field="cta_label" value={content.hero.cta_label} as="span" />
            <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
          </Link>
          {/* 2026-06 — Two-platform direct-download CTA pointing to the
              stable VPS CDN URLs. Windows users get the NATIVE
              installer (recommended for heavy jobs — leaves ~400 MB
              more RAM free for Playwright Chromium vs Electron's
              embedded UI runtime). Mac/Linux users get the ELECTRON
              build because it's the only cross-platform option AND
              has built-in auto-update via electron-updater. Both URLs
              are stable forever — every release overwrites
              "*-latest.exe" on the VPS mirror. */}
          <Link
            to="/download"
            className="group bg-white/95 text-zinc-900 font-semibold px-7 py-3.5 rounded-lg hover:bg-white transition inline-flex items-center gap-2 shadow-xl"
            data-testid="hero-cta-download-windows"
          >
            <Download size={16} />
            Download for Windows
          </Link>
          <Link
            to="/download"
            className="group border border-white/20 bg-white/5 text-white font-medium px-6 py-3.5 rounded-lg hover:bg-white/10 transition inline-flex items-center gap-2 text-sm"
            data-testid="hero-cta-download-mac-linux"
            title="Cross-platform Electron build · auto-update built in"
          >
            <Download size={14} />
            For Mac / Linux
          </Link>
          <a
            href="#features"
            className="border border-white/15 px-7 py-3.5 rounded-lg hover:bg-white/5 transition text-sm backdrop-blur-sm"
          >
            <EditableText section="hero" field="cta_secondary_label" value={content.hero.cta_secondary_label} as="span" />
          </a>
        </motion.div>

        {/* Stat strip */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.0, duration: 0.7 }}
          className="mt-14 grid grid-cols-2 md:grid-cols-4 gap-6 max-w-3xl mx-auto text-center"
        >
          {(content.stats || []).map((s, idx) => (
            <motion.div
              key={s.label || idx}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 1.0 + idx * 0.08, duration: 0.5 }}
            >
              <div className="text-2xl font-bold bg-clip-text text-transparent" style={{ backgroundImage: "linear-gradient(90deg, #93C5FD, #3B82F6)" }}>
                <EditableText
                  section="stats" field={`stats.${idx}.value`}
                  value={s.value}
                  onSave={async (newVal) => {
                    const next = [...(content.stats || [])];
                    next[idx] = { ...next[idx], value: newVal };
                    return await saveContentList("stats", next);
                  }}
                />
              </div>
              <div className="text-xs text-zinc-500 mt-1">
                <EditableText
                  section="stats" field={`stats.${idx}.label`}
                  value={s.label}
                  onSave={async (newVal) => {
                    const next = [...(content.stats || [])];
                    next[idx] = { ...next[idx], label: newVal };
                    return await saveContentList("stats", next);
                  }}
                />
              </div>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* Features */}
      <section id="features" className="max-w-7xl mx-auto px-6 py-20 scroll-mt-20 relative">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-14"
        >
          <div className="text-xs uppercase tracking-widest text-blue-400 mb-3">
            <EditableText section="features_intro" field="eyebrow" value={content.features_intro.eyebrow} />
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold mb-3">
            <EditableText section="features_intro" field="title" value={content.features_intro.title} />
          </h2>
          <p className="text-zinc-400 max-w-2xl mx-auto text-sm">
            <EditableText section="features_intro" field="subtitle" value={content.features_intro.subtitle} multiline />
          </p>
        </motion.div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {(content.features || []).map((f, idx) => {
            const Icon = getIcon(f.icon);
            return (
            <motion.div
              key={f.title || idx}
              initial={{ opacity: 0, y: 22 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: idx * 0.06 }}
              data-testid={`feature-card-${(f.title || '').toLowerCase().replace(/\s+/g, '-')}`}
              className="group relative bg-white/[0.025] border border-white/10 rounded-xl p-6 hover:border-blue-500/40 hover:bg-blue-500/5 transition-all duration-300 overflow-hidden"
            >
              <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
                   style={{ background: "radial-gradient(circle at top left, rgba(59,130,246,0.12), transparent 60%)" }} />
              <div className="relative">
                <div className="w-10 h-10 rounded-lg bg-blue-500/15 border border-blue-500/30 flex items-center justify-center mb-4 group-hover:bg-blue-500/25 group-hover:scale-110 transition">
                  <Icon className="text-blue-400" size={18} />
                </div>
                <h3 className="font-semibold mb-1.5">
                  <EditableText
                    section="features" field={`features.${idx}.title`}
                    value={f.title}
                    onSave={async (newVal) => {
                      const next = [...(content.features || [])];
                      next[idx] = { ...next[idx], title: newVal };
                      return await saveContentList("features", next);
                    }}
                  />
                </h3>
                <p className="text-sm text-zinc-400 leading-relaxed">
                  <EditableText
                    section="features" field={`features.${idx}.desc`}
                    value={f.desc} multiline
                    onSave={async (newVal) => {
                      const next = [...(content.features || [])];
                      next[idx] = { ...next[idx], desc: newVal };
                      return await saveContentList("features", next);
                    }}
                  />
                </p>
              </div>
            </motion.div>
            );
          })}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="max-w-7xl mx-auto px-6 py-20 scroll-mt-20 relative">
        <motion.div
          initial={{ opacity: 0, y: 26 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-12"
        >
          <div className="text-xs uppercase tracking-widest text-blue-400 mb-3">
            <EditableText section="pricing_intro" field="eyebrow" value={content.pricing_intro.eyebrow} />
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold mb-3">
            <EditableText section="pricing_intro" field="title" value={content.pricing_intro.title} />
          </h2>
          <p className="text-zinc-400 text-sm max-w-xl mx-auto">
            <EditableText section="pricing_intro" field="subtitle" value={content.pricing_intro.subtitle} multiline />
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {plans.length === 0 ? (
            <div className="col-span-full text-center text-zinc-500 py-10 text-sm">Loading plans…</div>
          ) : plans.map((plan, idx) => (
            <motion.div
              key={plan.id}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-50px" }}
              transition={{ duration: 0.5, delay: idx * 0.08 }}
              data-testid={`home-plan-${plan.id}`}
              className={`rounded-2xl p-6 flex flex-col relative transition-all duration-300 hover:-translate-y-1 ${
                plan.is_popular
                  ? "bg-gradient-to-b from-blue-500/10 to-black border-2 border-blue-500 shadow-2xl shadow-blue-500/20"
                  : "bg-white/[0.03] border border-white/10 hover:border-blue-500/40"
              }`}
            >
              {plan.is_popular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-500 text-white text-[10px] font-bold px-3 py-1 rounded-full shadow-lg shadow-blue-500/50">
                  MOST POPULAR
                </div>
              )}
              <h3 className="font-bold text-lg mb-1">{plan.name}</h3>
              <p className="text-xs text-zinc-500 min-h-[28px] mb-3">{plan.description}</p>
              <div className="flex items-baseline gap-1 mb-4">
                <span className="text-3xl font-bold">{plan.price_usdt}</span>
                <span className="text-xs text-zinc-400">USDT</span>
                <span className="text-xs text-zinc-500 ml-1">
                  / {plan.duration_days === 1 ? "1 day" : `${plan.duration_days} days`}
                </span>
              </div>
              <ul className="space-y-1.5 mb-5 flex-1">
                {(plan.features || []).slice(0, 4).map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    <Check size={12} className="text-blue-400 shrink-0 mt-0.5" />
                    <span className="text-zinc-300">{f}</span>
                  </li>
                ))}
              </ul>
              <Link
                to={`/checkout/${plan.id}`}
                data-testid={`home-pick-${plan.id}`}
                className={`w-full text-center py-2 rounded-lg text-sm font-medium transition ${
                  plan.is_popular
                    ? "bg-blue-500 text-white hover:bg-blue-400 shadow-lg shadow-blue-500/30"
                    : "bg-white/5 border border-white/10 hover:bg-white/10 hover:border-blue-500/40"
                }`}
              >
                Pick {plan.name}
              </Link>
            </motion.div>
          ))}
        </div>
        <div className="text-center mt-8">
          <Link to="/pricing" className="text-sm text-blue-400 hover:text-white inline-flex items-center gap-1 transition" data-testid="see-all-plans">
            Compare full plans <ArrowRight size={13} />
          </Link>
        </div>
      </section>

      {/* How payment works */}
      <section className="max-w-5xl mx-auto px-6 py-16 relative">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="bg-white/[0.02] border border-white/10 rounded-2xl p-8 md:p-10 backdrop-blur-sm"
        >
          <div className="text-center mb-8">
            <div className="text-xs uppercase tracking-widest text-blue-400 mb-2">Crypto checkout in 3 steps</div>
            <h2 className="text-2xl font-bold">From payment to license in under 30 minutes</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {[
              { n: "1", t: "Pick your plan", d: "Choose Starter, Pro, or Business based on your scale." },
              { n: "2", t: "Send USDT-TRC20", d: "Pay from any wallet (Binance, Trust, OKX). We give you the address + QR." },
              { n: "3", t: "Submit your TxID", d: "Paste your transaction ID — we verify on-chain and email your license." },
            ].map((s, idx) => (
              <motion.div
                key={s.n}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: idx * 0.1 }}
                className="bg-black/40 border border-white/10 rounded-xl p-5 hover:border-blue-500/40 transition"
              >
                <div className="w-9 h-9 rounded-full bg-blue-500 text-white font-bold flex items-center justify-center mb-3 shadow-lg shadow-blue-500/40">
                  {s.n}
                </div>
                <h4 className="font-semibold mb-1">{s.t}</h4>
                <p className="text-xs text-zinc-400 leading-relaxed">{s.d}</p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </section>

      {/* FAQ */}
      <section id="faq" className="max-w-3xl mx-auto px-6 py-20 scroll-mt-20 relative">
        <motion.div
          initial={{ opacity: 0, y: 22 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-10"
        >
          <div className="text-xs uppercase tracking-widest text-blue-400 mb-3">
            <EditableText section="faq_intro" field="eyebrow" value={content.faq_intro.eyebrow} />
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold">
            <EditableText section="faq_intro" field="title" value={content.faq_intro.title} />
          </h2>
          {content.faq_intro.subtitle ? (
            <p className="text-zinc-400 text-sm max-w-xl mx-auto mt-3">
              <EditableText section="faq_intro" field="subtitle" value={content.faq_intro.subtitle} multiline />
            </p>
          ) : null}
        </motion.div>
        <div className="space-y-3">
          {(content.faqs || []).map((item, idx) => {
            const open = openFaq === idx;
            return (
              <div
                key={idx}
                data-testid={`faq-item-${idx}`}
                className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden hover:border-blue-500/30 transition-colors"
              >
                <button
                  onClick={() => setOpenFaq(open ? -1 : idx)}
                  className="w-full flex items-center justify-between text-left px-5 py-4 hover:bg-white/[0.02] transition"
                  data-testid={`faq-toggle-${idx}`}
                >
                  <span className="font-medium text-sm">
                    <EditableText
                      section="faqs" field={`faqs.${idx}.q`}
                      value={item.q}
                      onSave={async (newVal) => {
                        const next = [...(content.faqs || [])];
                        next[idx] = { ...next[idx], q: newVal };
                        return await saveContentList("faqs", next);
                      }}
                    />
                  </span>
                  <ChevronDown size={16} className={`text-zinc-400 transition-transform ${open ? "rotate-180 text-blue-400" : ""}`} />
                </button>
                {open && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="px-5 pb-4 text-sm text-zinc-400 leading-relaxed border-t border-white/5"
                  >
                    <div className="pt-3">
                      <EditableText
                        section="faqs" field={`faqs.${idx}.a`}
                        value={item.a} multiline
                        onSave={async (newVal) => {
                          const next = [...(content.faqs || [])];
                          next[idx] = { ...next[idx], a: newVal };
                          return await saveContentList("faqs", next);
                        }}
                      />
                    </div>
                  </motion.div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* CTA strip */}
      <section className="max-w-5xl mx-auto px-6 pb-20 relative">
        <motion.div
          initial={{ opacity: 0, y: 26 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="relative overflow-hidden bg-gradient-to-br from-blue-600/20 via-blue-500/10 to-black border border-blue-500/30 rounded-2xl p-10 text-center"
        >
          {/* decorative shimmer */}
          <div className="absolute inset-0 opacity-30 pointer-events-none"
               style={{ background: "radial-gradient(circle at 80% 20%, rgba(59,130,246,0.4), transparent 60%)" }} />
          <div className="relative">
            <Lock className="mx-auto mb-4 text-blue-400" size={28} />
            <h2 className="text-2xl sm:text-3xl font-bold mb-3">Start in under 5 minutes</h2>
            <p className="text-zinc-400 text-sm mb-6 max-w-lg mx-auto">
              Try Krexion for 1 day at just 3 USDT. Pay → check email → login at{" "}
              <span className="text-white font-semibold">krexion.com/login</span>. That's it.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link
                to="/pricing"
                className="bg-blue-500 text-white font-semibold px-8 py-3 rounded-lg hover:bg-blue-400 transition inline-flex items-center justify-center gap-2 shadow-xl shadow-blue-500/40"
                data-testid="footer-cta-pricing"
              >
                Start your trial <ArrowRight size={16} />
              </Link>
              <Link
                to="/login"
                className="border border-white/15 px-8 py-3 rounded-lg hover:bg-white/5 transition inline-flex items-center justify-center gap-2 text-sm"
              >
                I already have a license
              </Link>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 mt-10 relative">
        <div className="max-w-7xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-zinc-500">
          <div className="flex items-center gap-2">
            <Sparkles className="text-blue-400" size={14} />
            <span className="font-semibold text-white">KREXION</span>
            <EditableText section="footer" field="copyright" value={content.footer.copyright} />
          </div>
          <div className="flex items-center gap-5">
            <Link to="/pricing" className="hover:text-white transition">{content.nav.pricing_label}</Link>
            <Link to="/download" className="hover:text-white transition">{content.nav.download_label}</Link>
            <Link to="/guide" className="hover:text-white transition">{content.nav.guide_label}</Link>
            <Link to="/login" className="hover:text-white transition">{content.nav.login_label}</Link>
            <a href="mailto:support@krexion.com" className="hover:text-white transition">Support</a>
          </div>
        </div>
      </footer>

      {/* Inline keyframes for the gradient sweep on the headline */}
      <style>{`
        @keyframes krx-gradient {
          0%, 100% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
        }
        /* Edit-mode hover affordance for editable text */
        .krx-editable:hover {
          background-color: rgba(59,130,246,0.08);
          outline-color: rgba(59,130,246,0.9) !important;
        }
      `}</style>
    </div>
    </EditModeProvider>
  );
}
