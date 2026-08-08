import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import { Plus, Copy, Pencil, Trash2, TrendingUp, Globe, Shield, Monitor, Smartphone, ExternalLink, Sparkles, Eye, ChevronDown, ChevronUp, X, Search } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// ══════════════════════════════════════════════════════════════════════
// v2.1.83 — Zero-typing helper constants for visual selectors.
// Customers now pick from dropdowns / sliders / row-builders instead of
// hand-crafting weighted strings + JSON. Every visual selector still
// serialises back to the SAME wire format the backend already accepts,
// so no server-side schema change is needed.
// ══════════════════════════════════════════════════════════════════════

// Supported platforms for the visual "Platform Pool" builder. Order = UI
// order (most-used first). `mobile` field feeds the sanity chip that
// tells the customer "TikTok is mobile-first, LinkedIn is desktop-first".
const PLATFORM_OPTIONS = [
  { key: "facebook",   label: "Facebook",     emoji: "📘", mobile: "any" },
  { key: "instagram",  label: "Instagram",    emoji: "📷", mobile: "mobile" },
  { key: "tiktok",     label: "TikTok",       emoji: "🎵", mobile: "mobile" },
  { key: "twitter",    label: "X / Twitter",  emoji: "𝕏",  mobile: "any" },
  { key: "snapchat",   label: "Snapchat",     emoji: "👻", mobile: "mobile" },
  { key: "pinterest",  label: "Pinterest",    emoji: "📌", mobile: "any" },
  { key: "reddit",     label: "Reddit",       emoji: "🤖", mobile: "any" },
  { key: "linkedin",   label: "LinkedIn",     emoji: "💼", mobile: "desktop" },
  { key: "youtube",    label: "YouTube",      emoji: "▶️", mobile: "any" },
  { key: "whatsapp",   label: "WhatsApp",     emoji: "💬", mobile: "mobile" },
  { key: "telegram",   label: "Telegram",     emoji: "✈️", mobile: "any" },
  { key: "google",     label: "Google Search",emoji: "🔍", mobile: "any" },
  { key: "bing",       label: "Bing",         emoji: "🅱️", mobile: "desktop" },
  { key: "duckduckgo", label: "DuckDuckGo",   emoji: "🦆", mobile: "any" },
  { key: "yahoo",      label: "Yahoo",        emoji: "🅨",  mobile: "any" },
  { key: "yandex",     label: "Yandex",       emoji: "🅨",  mobile: "any" },
  { key: "email",      label: "Email (ESP)",  emoji: "📧", mobile: "any" },
];

// 68 countries — matches _COUNTRY_LANG_MAP in referrer_pro.py so
// Accept-Language auto-match works for every option.
const PRO_COUNTRY_OPTIONS = [
  { code: "us", name: "United States", flag: "🇺🇸" },
  { code: "gb", name: "United Kingdom", flag: "🇬🇧" },
  { code: "ca", name: "Canada", flag: "🇨🇦" },
  { code: "au", name: "Australia", flag: "🇦🇺" },
  { code: "nz", name: "New Zealand", flag: "🇳🇿" },
  { code: "ie", name: "Ireland", flag: "🇮🇪" },
  { code: "de", name: "Germany", flag: "🇩🇪" },
  { code: "fr", name: "France", flag: "🇫🇷" },
  { code: "es", name: "Spain", flag: "🇪🇸" },
  { code: "it", name: "Italy", flag: "🇮🇹" },
  { code: "nl", name: "Netherlands", flag: "🇳🇱" },
  { code: "be", name: "Belgium", flag: "🇧🇪" },
  { code: "at", name: "Austria", flag: "🇦🇹" },
  { code: "ch", name: "Switzerland", flag: "🇨🇭" },
  { code: "pt", name: "Portugal", flag: "🇵🇹" },
  { code: "gr", name: "Greece", flag: "🇬🇷" },
  { code: "pl", name: "Poland", flag: "🇵🇱" },
  { code: "cz", name: "Czech Republic", flag: "🇨🇿" },
  { code: "sk", name: "Slovakia", flag: "🇸🇰" },
  { code: "hu", name: "Hungary", flag: "🇭🇺" },
  { code: "ro", name: "Romania", flag: "🇷🇴" },
  { code: "bg", name: "Bulgaria", flag: "🇧🇬" },
  { code: "hr", name: "Croatia", flag: "🇭🇷" },
  { code: "rs", name: "Serbia", flag: "🇷🇸" },
  { code: "si", name: "Slovenia", flag: "🇸🇮" },
  { code: "no", name: "Norway", flag: "🇳🇴" },
  { code: "se", name: "Sweden", flag: "🇸🇪" },
  { code: "fi", name: "Finland", flag: "🇫🇮" },
  { code: "dk", name: "Denmark", flag: "🇩🇰" },
  { code: "is", name: "Iceland", flag: "🇮🇸" },
  { code: "ru", name: "Russia", flag: "🇷🇺" },
  { code: "ua", name: "Ukraine", flag: "🇺🇦" },
  { code: "by", name: "Belarus", flag: "🇧🇾" },
  { code: "kz", name: "Kazakhstan", flag: "🇰🇿" },
  { code: "tr", name: "Turkey", flag: "🇹🇷" },
  { code: "sa", name: "Saudi Arabia", flag: "🇸🇦" },
  { code: "ae", name: "UAE", flag: "🇦🇪" },
  { code: "eg", name: "Egypt", flag: "🇪🇬" },
  { code: "il", name: "Israel", flag: "🇮🇱" },
  { code: "ir", name: "Iran", flag: "🇮🇷" },
  { code: "in", name: "India", flag: "🇮🇳" },
  { code: "pk", name: "Pakistan", flag: "🇵🇰" },
  { code: "bd", name: "Bangladesh", flag: "🇧🇩" },
  { code: "lk", name: "Sri Lanka", flag: "🇱🇰" },
  { code: "np", name: "Nepal", flag: "🇳🇵" },
  { code: "cn", name: "China", flag: "🇨🇳" },
  { code: "hk", name: "Hong Kong", flag: "🇭🇰" },
  { code: "tw", name: "Taiwan", flag: "🇹🇼" },
  { code: "jp", name: "Japan", flag: "🇯🇵" },
  { code: "kr", name: "South Korea", flag: "🇰🇷" },
  { code: "sg", name: "Singapore", flag: "🇸🇬" },
  { code: "my", name: "Malaysia", flag: "🇲🇾" },
  { code: "th", name: "Thailand", flag: "🇹🇭" },
  { code: "id", name: "Indonesia", flag: "🇮🇩" },
  { code: "ph", name: "Philippines", flag: "🇵🇭" },
  { code: "vn", name: "Vietnam", flag: "🇻🇳" },
  { code: "br", name: "Brazil", flag: "🇧🇷" },
  { code: "mx", name: "Mexico", flag: "🇲🇽" },
  { code: "ar", name: "Argentina", flag: "🇦🇷" },
  { code: "cl", name: "Chile", flag: "🇨🇱" },
  { code: "co", name: "Colombia", flag: "🇨🇴" },
  { code: "pe", name: "Peru", flag: "🇵🇪" },
  { code: "za", name: "South Africa", flag: "🇿🇦" },
  { code: "ng", name: "Nigeria", flag: "🇳🇬" },
  { code: "ke", name: "Kenya", flag: "🇰🇪" },
  { code: "gh", name: "Ghana", flag: "🇬🇭" },
];

// Email service providers for the visual ESP-weight builder.
const ESP_OPTIONS = [
  { key: "gmail",      label: "Gmail",       emoji: "📮" },
  { key: "yahoo",      label: "Yahoo Mail",  emoji: "💜" },
  { key: "outlook",    label: "Outlook",     emoji: "📧" },
  { key: "hotmail",    label: "Hotmail",     emoji: "🔥" },
  { key: "protonmail", label: "ProtonMail",  emoji: "🔒" },
  { key: "icloud",     label: "iCloud Mail", emoji: "☁️" },
  { key: "yandex",     label: "Yandex Mail", emoji: "🅨" },
  { key: "empty",      label: "No referer (direct)", emoji: "◯" },
];

// Postback URL templates for major affiliate/tracker platforms.
// Placeholders are Krexion macros — customer just replaces the tracker
// host part.
const POSTBACK_TEMPLATES = [
  {
    key: "custom",
    label: "— Custom (I'll paste my own URL) —",
    url: "",
    hint: "",
  },
  {
    key: "voluum",
    label: "Voluum",
    url: "https://YOUR-DOMAIN.voluumtrk.com/postback?cid={click_id}&payout={payout}",
    hint: "Replace YOUR-DOMAIN with your Voluum tracker subdomain.",
  },
  {
    key: "everflow",
    label: "Everflow",
    url: "https://YOUR-NETWORK.evyy.net/postback/?transaction_id={click_id}&adv1={payout}",
    hint: "Replace YOUR-NETWORK with your Everflow network slug.",
  },
  {
    key: "hasoffers",
    label: "HasOffers / Tune",
    url: "https://YOUR-NETWORK.go2cloud.org/aff_lsr?transaction_id={click_id}&amount={payout}",
    hint: "Replace YOUR-NETWORK with your HasOffers subdomain.",
  },
  {
    key: "cake",
    label: "Cake",
    url: "https://YOUR-NETWORK.cakelog.com/track_conversion.php?requestid={click_id}&price={payout}",
    hint: "Replace YOUR-NETWORK with your Cake subdomain.",
  },
  {
    key: "adsterra",
    label: "Adsterra",
    url: "https://api.adsterra.com/postback?cnv_id={click_id}&sum={payout}",
    hint: "Add your API key parameter to the end (&api_key=…).",
  },
  {
    key: "mostplay",
    label: "Mostplay / iGaming",
    url: "https://YOUR-TRACKER.com/pb?click_id={click_id}&payout={payout}&status={status}",
    hint: "Replace YOUR-TRACKER with your gambling network's tracker host.",
  },
  {
    key: "maxbounty",
    label: "MaxBounty",
    url: "https://www.maxbounty.com/postback.asp?adv=YOUR_ADV_ID&cd={click_id}&sale={payout}",
    hint: "Replace YOUR_ADV_ID with your MaxBounty advertiser ID.",
  },
];

// ─────────────────────────────────────────────────────────────
// Serialiser helpers — convert visual UI state ↔ wire-format
// strings the backend already understands. Callers keep passing
// the same string fields to the API; the UI just becomes visual.
// ─────────────────────────────────────────────────────────────

// "facebook:50,instagram:30" → [{key:"facebook",weight:50}, ...]
const parsePlatformPool = (str) => {
  if (!str) return [];
  return str.split(",").map(s => s.trim()).filter(Boolean).map(chunk => {
    const [k, w] = chunk.split(":");
    return { key: (k || "").trim().toLowerCase(), weight: parseInt(w) || 1 };
  }).filter(x => x.key);
};

// [{key,weight}] → "facebook:50,instagram:30"
const stringifyPlatformPool = (arr) => {
  if (!Array.isArray(arr)) return "";
  return arr.filter(x => x.key && x.weight > 0)
    .map(x => `${x.key}:${x.weight}`).join(",");
};

// '{"gmail":40,"yahoo":25}' → {gmail:40, yahoo:25}
const parseEmailWeights = (str) => {
  if (!str) return {};
  try { return JSON.parse(str) || {}; } catch { return {}; }
};

// {gmail:40} → '{"gmail":40}'
const stringifyEmailWeights = (obj) => {
  if (!obj || !Object.keys(obj).length) return "";
  return JSON.stringify(obj);
};

// "url:60,url:40" or JSON → [{url,weight}]
const parseOfferUrls = (str) => {
  if (!str) return [];
  const raw = str.trim();
  if (raw.startsWith("[")) {
    try {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) {
        return arr.filter(x => x && x.url).map(x => ({ url: x.url, weight: parseInt(x.weight) || 1 }));
      }
    } catch { /* fall through to compact */ }
  }
  // Compact "url:weight,url:weight" — split each on LAST ":<n>" to preserve https:// colons.
  return raw.split(",").map(s => s.trim()).filter(Boolean).map(chunk => {
    const m = chunk.match(/:(\d+(?:\.\d+)?)\s*$/);
    if (m) {
      return { url: chunk.slice(0, m.index).trim(), weight: parseInt(m[1]) || 1 };
    }
    return { url: chunk, weight: 1 };
  }).filter(x => x.url);
};

// [{url,weight}] → "url:60,url:40"
const stringifyOfferUrls = (arr) => {
  if (!Array.isArray(arr)) return "";
  return arr.filter(x => x.url && x.weight > 0)
    .map(x => `${x.url}:${x.weight}`).join(",");
};

// Host for user-facing tracking links. If REACT_APP_BACKEND_URL is empty
// (nginx-same-origin deployments like local Docker), fall back to the
// current window origin so copied links include the full URL.
// 2026-02 v2.1.17 — Tracking links are PROFESSIONAL and must live on
// the cloud (krexion.com), NOT on the customer's local PC. Reasons:
//   1. A shared link must keep working even when the customer's PC is
//      off — the redirect endpoint lives on cloud Mongo.
//   2. "http://127.0.0.1:8088/api/t/abcd" looks unprofessional when
//      pasted into a campaign / shared with a partner.
//   3. The /api/links/* allowlist forwards CRUD to cloud already, so
//      every short_code in the dashboard is guaranteed to exist on
//      krexion.com — the redirect host and the data host match.
// Override via REACT_APP_KREXION_PUBLIC_HOST if a customer self-hosts.
const PUBLIC_HOST =
  process.env.REACT_APP_KREXION_PUBLIC_HOST || "https://krexion.com";

// Fallback copy function that works over HTTP (not just HTTPS)
const copyToClipboard = async (text) => {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.log("Clipboard API failed, trying fallback");
    }
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.left = "-999999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    document.execCommand('copy');
    textArea.remove();
    return true;
  } catch (err) {
    textArea.remove();
    return false;
  }
};

// Available OS options
const OS_OPTIONS = [
  { value: "iOS", label: "iOS", icon: "📱" },
  { value: "Android", label: "Android", icon: "🤖" },
  { value: "Windows", label: "Windows", icon: "🪟" },
  { value: "macOS", label: "macOS", icon: "🍎" },
  { value: "Linux", label: "Linux", icon: "🐧" },
  { value: "ChromeOS", label: "ChromeOS", icon: "💻" },
];

// Traffic source options
const TRAFFIC_SOURCE_OPTIONS = [
  { value: "", label: "Auto Detect (from referrer)", icon: "🔄" },
  { value: "facebook", label: "Facebook", icon: "📘" },
  { value: "instagram", label: "Instagram", icon: "📷" },
  { value: "twitter", label: "Twitter/X", icon: "🐦" },
  { value: "pinterest", label: "Pinterest", icon: "📌" },
  { value: "linkedin", label: "LinkedIn", icon: "💼" },
  { value: "youtube", label: "YouTube", icon: "🎬" },
  { value: "tiktok", label: "TikTok", icon: "🎵" },
  { value: "whatsapp", label: "WhatsApp", icon: "💬" },
  { value: "telegram", label: "Telegram", icon: "✈️" },
  { value: "discord", label: "Discord", icon: "🎮" },
  { value: "google", label: "Google Search", icon: "🔍" },
  { value: "bing", label: "Bing Search", icon: "🔎" },
  { value: "gmail", label: "Gmail", icon: "📧" },
  { value: "outlook", label: "Outlook/Hotmail", icon: "📨" },
  { value: "reddit", label: "Reddit", icon: "🔴" },
  { value: "direct", label: "Direct (QR Code/Offline)", icon: "🔗" },
  { value: "sms", label: "SMS", icon: "📱" },
  { value: "email", label: "Email Campaign", icon: "📬" },
  { value: "ads", label: "Paid Ads", icon: "💰" },
  { value: "other", label: "Other", icon: "🌐" },
];

// Referrer mode options
const REFERRER_MODE_OPTIONS = [
  { value: "normal", label: "Normal (Krexion as referrer)", description: "Destination sees your tracking domain" },
  { value: "no_referrer", label: "No Referrer (Blank/Direct)", description: "Destination sees direct traffic" },
  { value: "with_params", label: "Add Source Parameters", description: "Add utm_source, fbclid, etc. to URL" },
];

// Platform simulation options (adds realistic click IDs)
const PLATFORM_SIMULATION_OPTIONS = [
  { value: "", label: "None - Don't simulate", description: "No fake click IDs added" },
  { value: "facebook", label: "Facebook (fbclid)", description: "Adds fbclid=IwAR... parameter" },
  { value: "instagram", label: "Instagram (igshid)", description: "Adds igshid parameter" },
  { value: "tiktok", label: "TikTok (ttclid)", description: "Adds ttclid parameter" },
  { value: "twitter", label: "Twitter/X (twclid)", description: "Adds twclid parameter" },
  { value: "google", label: "Google Ads (gclid)", description: "Adds gclid parameter" },
  { value: "pinterest", label: "Pinterest (epik)", description: "Adds epik parameter" },
  { value: "linkedin", label: "LinkedIn (li_fat_id)", description: "Adds li_fat_id parameter" },
  { value: "snapchat", label: "Snapchat (sccid)", description: "Adds sccid parameter" },
  { value: "whatsapp", label: "WhatsApp", description: "Adds utm_source=whatsapp" },
  { value: "telegram", label: "Telegram", description: "Adds utm_source=telegram" },
  { value: "youtube", label: "YouTube", description: "Adds utm_source=youtube" },
  { value: "email", label: "Email Campaign", description: "Adds utm_source=email" },
  { value: "sms", label: "SMS", description: "Adds utm_source=sms" },
];

// Popular countries list
const COUNTRY_OPTIONS = [
  "United States", "United Kingdom", "Canada", "Australia", "Germany", 
  "France", "Italy", "Spain", "Netherlands", "Belgium", "Switzerland",
  "India", "Pakistan", "Bangladesh", "Brazil", "Mexico", "Argentina",
  "Japan", "China", "South Korea", "Thailand", "Vietnam", "Philippines",
  "Indonesia", "Malaysia", "Singapore", "United Arab Emirates", "Saudi Arabia",
  "South Africa", "Nigeria", "Egypt", "Turkey", "Russia", "Poland"
];

export default function LinksPage() {
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingLink, setEditingLink] = useState(null);
  // v2.1.80 — Pro-Referrer collapsible section state
  const [proReferrerOpen, setProReferrerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  // v2.1.83 — QA-check modal state + auto-pause telemetry from GET /links
  const [qaOpen, setQaOpen] = useState(false);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaData, setQaData] = useState(null);
  // v2.2.0 (Tier 4) — Traffic Believability Score per link
  const [believability, setBelievability] = useState({}); // { link_id: {score, grade, color, fixes} }
  const [believabilityLoading, setBelievabilityLoading] = useState({});
  // v2.2.0 (Tier 7) — Perfect Config preset picker per link
  const [presetPickerFor, setPresetPickerFor] = useState(null);
  // v2.1.83 — Beginner guide toggle (defaults to OPEN so first-time
  // users see the step-by-step walkthrough right when they enable
  // Referrer Mode; they can collapse it once they know the flow).
  const [guideOpen, setGuideOpen] = useState(true);
  const [formData, setFormData] = useState({ 
    offer_url: "", 
    status: "active",
    name: "",
    custom_short_code: "",
    allowed_countries: [],
    allowed_os: [],
    block_vpn: false,
    all_countries: true,
    all_os: true,
    duplicate_timer_enabled: false,
    duplicate_timer_seconds: 5,
    strict_duplicate_check: true,
    forced_source: "",
    forced_source_name: "",
    referrer_mode: "normal",
    simulate_platform: "",
    url_params: {},
    // v2.1.80 — Pro-Referrer defaults (all match backend defaults so
    // creating a link with the section untouched behaves identically
    // to before this feature landed).
    referrer_pro_enabled: false,
    referrer_pro_platform_pool: "",
    referrer_pro_email_weights: "",
    referrer_pro_brand: "",
    referrer_pro_country: "",
    referrer_pro_search_engine: "google",
    referrer_pro_search_keywords: "",
    referrer_pro_social_wrapper: true,
    referrer_pro_inapp_deep_path: true,
    referrer_pro_strip_search_path: true,
    referrer_pro_network_click_chain: false,
    referrer_pro_network_click_host: "",
    referrer_pro_wrapper_redirect: false,
    // v2.1.83 — International guardrails (10-feature pack). Defaults
    // match the server-side defaults so pre-existing links keep
    // behaving IDENTICALLY when the customer opens them for edit.
    referrer_pro_lang_match: true,
    referrer_pro_device_mode: "auto",
    referrer_pro_tod_enabled: false,
    referrer_pro_campaign_type: "auto",
    referrer_pro_quality_tier: "standard",
    referrer_pro_traffic_type: "auto",
    traffic_type_param: "",
    referrer_pro_offer_urls: "",
    postback_url: "",
    referrer_pro_auto_pause_enabled: false,
    referrer_pro_auto_pause_threshold: 10
  });

  useEffect(() => {
    fetchLinks();
  }, []);

  const fetchLinks = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get(`${API}/links`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setLinks(response.data);
      // v2.2.0 — auto-fetch believability score for each link (async, non-blocking)
      (response.data || []).forEach((lnk) => {
        fetchBelievability(lnk.id).catch(() => {});
      });
    } catch (error) {
      toast.error("Failed to fetch links");
    } finally {
      setLoading(false);
    }
  };

  // v2.2.0 (Tier 4) — Believability Score per link
  const fetchBelievability = async (linkId) => {
    setBelievabilityLoading((s) => ({ ...s, [linkId]: true }));
    try {
      const token = localStorage.getItem("token");
      const r = await axios.get(`${API}/links/${linkId}/believability`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setBelievability((s) => ({ ...s, [linkId]: r.data }));
    } catch (e) {
      // Silent — believability is a UX enhancement, not critical
    } finally {
      setBelievabilityLoading((s) => ({ ...s, [linkId]: false }));
    }
  };

  const applyBelievabilityFix = async (linkId, fix) => {
    try {
      const token = localStorage.getItem("token");
      await axios.post(`${API}/links/${linkId}/apply-fix`, fix.payload, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success(`Applied: ${fix.label}`);
      fetchLinks();
    } catch (e) {
      toast.error("Failed to apply fix");
    }
  };

  // v2.2.0 (Tier 7) — Apply Perfect Config preset
  const applyPreset = async (linkId, presetKey) => {
    try {
      const token = localStorage.getItem("token");
      await axios.post(`${API}/links/${linkId}/apply-preset`, { key: presetKey }, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success(`Applied "${presetKey.replace(/_/g, ' ')}" preset ✨`);
      setPresetPickerFor(null);
      fetchLinks();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to apply preset");
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const token = localStorage.getItem("token");
      const submitData = {
        ...formData,
        allowed_countries: formData.all_countries ? [] : formData.allowed_countries,
        allowed_os: formData.all_os ? [] : formData.allowed_os,
      };
      // Remove UI-only fields
      delete submitData.all_countries;
      delete submitData.all_os;

      if (editingLink) {
        await axios.put(`${API}/links/${editingLink.id}`, submitData, {
          headers: { Authorization: `Bearer ${token}` },
        });
        toast.success("Link updated successfully");
      } else {
        await axios.post(`${API}/links`, submitData, {
          headers: { Authorization: `Bearer ${token}` },
        });
        toast.success("Link created successfully");
      }
      setDialogOpen(false);
      setEditingLink(null);
      resetForm();
      fetchLinks();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Operation failed");
    }
  };

  const resetForm = () => {
    setFormData({ 
      offer_url: "", 
      status: "active",
      name: "",
      custom_short_code: "",
      allowed_countries: [],
      allowed_os: [],
      block_vpn: false,
      all_countries: true,
      all_os: true,
      duplicate_timer_enabled: false,
      duplicate_timer_seconds: 5,
      strict_duplicate_check: true,
      forced_source: "",
      forced_source_name: "",
      referrer_mode: "normal",
      simulate_platform: "",
      url_params: {},
      referrer_pro_enabled: false,
      referrer_pro_platform_pool: "",
      referrer_pro_email_weights: "",
      referrer_pro_brand: "",
      referrer_pro_country: "",
      referrer_pro_search_engine: "google",
      referrer_pro_search_keywords: "",
      referrer_pro_social_wrapper: true,
      referrer_pro_inapp_deep_path: true,
      referrer_pro_strip_search_path: true,
      referrer_pro_network_click_chain: false,
      referrer_pro_network_click_host: "",
      referrer_pro_wrapper_redirect: false,
      referrer_pro_lang_match: true,
      referrer_pro_device_mode: "auto",
      referrer_pro_tod_enabled: false,
      referrer_pro_campaign_type: "auto",
      referrer_pro_quality_tier: "standard",
      referrer_pro_traffic_type: "auto",
      traffic_type_param: "",
      referrer_pro_offer_urls: "",
      postback_url: "",
      referrer_pro_auto_pause_enabled: false,
      referrer_pro_auto_pause_threshold: 10
    });
    setProReferrerOpen(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this link?")) return;
    
    try {
      const token = localStorage.getItem("token");
      await axios.delete(`${API}/links/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Link deleted successfully");
      fetchLinks();
    } catch (error) {
      toast.error("Failed to delete link");
    }
  };

  const copyTrackingLink = (shortCode) => {
    const trackingLink = `${PUBLIC_HOST}/api/t/${shortCode}`;
    copyToClipboard(trackingLink);
    toast.success("Tracking link copied to clipboard");
  };

  // v2.1.80 — Pro-Referrer preview. Calls the backend to generate N
  // sample visits using the CURRENT form settings (without saving the
  // link) so the customer can eyeball the mix before they publish.
  const runReferrerPreview = async () => {
    if (!formData.referrer_pro_platform_pool && !formData.referrer_pro_email_weights) {
      toast.error("Add a platform pool (e.g. facebook:50,instagram:30,google:20) before previewing.");
      return;
    }
    setPreviewLoading(true);
    setPreviewOpen(true);
    setPreviewData(null);
    try {
      const token = localStorage.getItem("token");
      const res = await axios.post(`${API}/links/preview-referrer`, {
        offer_url: formData.offer_url || "https://example.com/offer",
        referrer_pro_platform_pool: formData.referrer_pro_platform_pool,
        referrer_pro_email_weights: formData.referrer_pro_email_weights,
        referrer_pro_brand: formData.referrer_pro_brand,
        referrer_pro_country: formData.referrer_pro_country,
        referrer_pro_search_engine: formData.referrer_pro_search_engine,
        referrer_pro_search_keywords: formData.referrer_pro_search_keywords,
        referrer_pro_social_wrapper: formData.referrer_pro_social_wrapper,
        referrer_pro_inapp_deep_path: formData.referrer_pro_inapp_deep_path,
        referrer_pro_strip_search_path: formData.referrer_pro_strip_search_path,
        referrer_pro_network_click_chain: false,
        referrer_pro_network_click_host: "",
        referrer_pro_wrapper_redirect: formData.referrer_pro_wrapper_redirect,
        referrer_pro_traffic_type: formData.referrer_pro_traffic_type || "auto",
        referrer_pro_lang_match: formData.referrer_pro_lang_match,
        referrer_pro_device_mode: formData.referrer_pro_device_mode || "auto",
        referrer_pro_tod_enabled: formData.referrer_pro_tod_enabled,
        referrer_pro_campaign_type: formData.referrer_pro_campaign_type || "auto",
        sample_count: 20
      }, { headers: { Authorization: `Bearer ${token}` } });
      setPreviewData(res.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Preview failed");
      setPreviewOpen(false);
    } finally {
      setPreviewLoading(false);
    }
  };

  // v2.1.83 Feature 9 — Run the QA-check report against an existing link.
  // Grades all 10 international fraud-detector guardrails and shows a
  // report card. Only available for saved links (needs a link_id).
  const runQaCheck = async (linkId) => {
    setQaOpen(true);
    setQaLoading(true);
    setQaData(null);
    try {
      const token = localStorage.getItem("token");
      const res = await axios.post(`${API}/links/${linkId}/qa-check`, {}, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setQaData(res.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "QA check failed");
      setQaOpen(false);
    } finally {
      setQaLoading(false);
    }
  };

  // v2.1.83 Feature 6 — Apply Quality Tier preset locally. When the user
  // picks a tier, we flip the downstream toggles to the recommended
  // combo so they don't have to tune 8 knobs by hand.
  const applyQualityTier = (tier) => {
    const presets = {
      premium: {
        referrer_pro_lang_match: true,
        referrer_pro_social_wrapper: true,
        referrer_pro_inapp_deep_path: true,
        referrer_pro_strip_search_path: true,
        referrer_pro_wrapper_redirect: true,
        referrer_pro_tod_enabled: true,
        referrer_pro_device_mode: "match_platform",
      },
      standard: {
        referrer_pro_lang_match: true,
        referrer_pro_social_wrapper: true,
        referrer_pro_inapp_deep_path: true,
        referrer_pro_strip_search_path: true,
        referrer_pro_wrapper_redirect: false,
        referrer_pro_tod_enabled: false,
        referrer_pro_device_mode: "auto",
      },
      aggressive: {
        referrer_pro_lang_match: false,
        referrer_pro_social_wrapper: false,
        referrer_pro_inapp_deep_path: false,
        referrer_pro_strip_search_path: true,
        referrer_pro_wrapper_redirect: false,
        referrer_pro_tod_enabled: false,
        referrer_pro_device_mode: "auto",
      },
    };
    const p = presets[tier] || presets.standard;
    setFormData((prev) => ({ ...prev, referrer_pro_quality_tier: tier, ...p }));
    toast.success(`Quality tier: ${tier}`);
  };

  // v2.1.83 Feature 10 — Resume an auto-paused link.
  const resumeLink = async (linkId) => {
    try {
      const token = localStorage.getItem("token");
      await axios.post(`${API}/links/${linkId}/resume`, {}, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Link resumed");
      fetchLinks();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Resume failed");
    }
  };

  const openEditDialog = (link) => {
    setEditingLink(link);
    const hasCountryRestriction = link.allowed_countries && link.allowed_countries.length > 0;
    const hasOsRestriction = link.allowed_os && link.allowed_os.length > 0;
    
    setFormData({ 
      offer_url: link.offer_url, 
      status: link.status,
      name: link.name || "",
      custom_short_code: "", // Leave empty to keep existing, or enter new code
      allowed_countries: link.allowed_countries || [],
      allowed_os: link.allowed_os || [],
      block_vpn: link.block_vpn || false,
      all_countries: !hasCountryRestriction,
      all_os: !hasOsRestriction,
      duplicate_timer_enabled: link.duplicate_timer_enabled || false,
      duplicate_timer_seconds: link.duplicate_timer_seconds || 5,
      strict_duplicate_check: link.strict_duplicate_check !== undefined ? link.strict_duplicate_check : true,
      forced_source: link.forced_source || "",
      forced_source_name: link.forced_source_name || "",
      referrer_mode: link.referrer_mode || "normal",
      simulate_platform: link.simulate_platform || "",
      url_params: link.url_params || {},
      // v2.1.80 — Pro-Referrer fields (safe defaults for OLD docs that
      // don't have these keys — LinkResponse fills defaults server-side
      // but we defensively fall back here too).
      referrer_pro_enabled: link.referrer_pro_enabled || false,
      referrer_pro_platform_pool: link.referrer_pro_platform_pool || "",
      referrer_pro_email_weights: link.referrer_pro_email_weights || "",
      referrer_pro_brand: link.referrer_pro_brand || "",
      referrer_pro_country: link.referrer_pro_country || "",
      referrer_pro_search_engine: link.referrer_pro_search_engine || "google",
      referrer_pro_search_keywords: link.referrer_pro_search_keywords || "",
      referrer_pro_social_wrapper: link.referrer_pro_social_wrapper !== undefined ? link.referrer_pro_social_wrapper : true,
      referrer_pro_inapp_deep_path: link.referrer_pro_inapp_deep_path !== undefined ? link.referrer_pro_inapp_deep_path : true,
      referrer_pro_strip_search_path: link.referrer_pro_strip_search_path !== undefined ? link.referrer_pro_strip_search_path : true,
      referrer_pro_network_click_chain: false,
      referrer_pro_network_click_host: "",
      referrer_pro_wrapper_redirect: link.referrer_pro_wrapper_redirect || false,
      // v2.1.83 fields
      referrer_pro_lang_match: link.referrer_pro_lang_match !== undefined ? link.referrer_pro_lang_match : true,
      referrer_pro_device_mode: link.referrer_pro_device_mode || "auto",
      referrer_pro_tod_enabled: link.referrer_pro_tod_enabled || false,
      referrer_pro_campaign_type: link.referrer_pro_campaign_type || "auto",
      referrer_pro_quality_tier: link.referrer_pro_quality_tier || "standard",
      referrer_pro_traffic_type: link.referrer_pro_traffic_type || "auto",
      traffic_type_param: link.traffic_type_param || "",
      referrer_pro_offer_urls: link.referrer_pro_offer_urls || "",
      postback_url: link.postback_url || "",
      referrer_pro_auto_pause_enabled: link.referrer_pro_auto_pause_enabled || false,
      referrer_pro_auto_pause_threshold: link.referrer_pro_auto_pause_threshold || 10
    });
    // Auto-expand the Pro-Referrer section when editing a link that
    // already has it enabled — customer immediately sees their settings.
    setProReferrerOpen(!!link.referrer_pro_enabled);
    setDialogOpen(true);
  };

  const openCreateDialog = () => {
    setEditingLink(null);
    resetForm();
    setDialogOpen(true);
  };

  const toggleCountry = (country) => {
    setFormData(prev => ({
      ...prev,
      allowed_countries: prev.allowed_countries.includes(country)
        ? prev.allowed_countries.filter(c => c !== country)
        : [...prev.allowed_countries, country]
    }));
  };

  const toggleOS = (os) => {
    setFormData(prev => ({
      ...prev,
      allowed_os: prev.allowed_os.includes(os)
        ? prev.allowed_os.filter(o => o !== os)
        : [...prev.allowed_os, os]
    }));
  };

  if (loading) {
    return <div className="text-muted-foreground">Loading links...</div>;
  }

  return (
    <div className="space-y-6" data-testid="links-page">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Links Management</h2>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={openCreateDialog} data-testid="create-link-button">
              <Plus size={16} className="mr-2" />
              Create Link
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{editingLink ? "Edit Link" : "Create New Link"}</DialogTitle>
              <DialogDescription>
                {editingLink ? "Update your tracking link settings" : "Configure your new tracking link"}
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Offer Name */}
              <div className="space-y-2">
                <Label htmlFor="name">Offer Name</Label>
                <Input
                  id="name"
                  data-testid="link-name-input"
                  type="text"
                  placeholder="e.g., Christmas Sale Campaign"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                />
              </div>

              {/* Custom Tracking Code */}
              <div className="space-y-2">
                <Label htmlFor="custom_short_code">Custom Tracking Code</Label>
                <Input
                  id="custom_short_code"
                  data-testid="custom-short-code-input"
                  type="text"
                  placeholder="e.g., summer-sale or black-friday-2024"
                  value={formData.custom_short_code}
                  onChange={(e) => setFormData({ ...formData, custom_short_code: e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, '') })}
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                />
                <p className="text-xs text-muted-foreground">
                  {editingLink 
                    ? `Current: ${editingLink.short_code} • Change to use a new code (3-50 chars)`
                    : "Leave empty for auto-generated code. Use letters, numbers, hyphens, underscores (3-50 chars)"
                  }
                </p>
              </div>

              {/* Offer URL */}
              <div className="space-y-2">
                <Label htmlFor="offer_url">Offer URL *</Label>
                <Input
                  id="offer_url"
                  data-testid="offer-url-input"
                  type="url"
                  placeholder="https://example.com/offer"
                  value={formData.offer_url}
                  onChange={(e) => setFormData({ ...formData, offer_url: e.target.value })}
                  required
                  className="bg-[var(--brand-card)] border-[var(--brand-border)]"
                />
              </div>

              {/* Status */}
              <div className="space-y-2">
                <Label htmlFor="status">Status</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant={formData.status === "active" ? "default" : "outline"}
                    className={formData.status === "active" ? "bg-[#22C55E] hover:bg-[#16A34A]" : "border-[var(--brand-border)]"}
                    onClick={() => setFormData({ ...formData, status: "active" })}
                  >
                    Active
                  </Button>
                  <Button
                    type="button"
                    variant={formData.status === "paused" ? "default" : "outline"}
                    className={formData.status === "paused" ? "bg-[#F59E0B] hover:bg-[#D97706]" : "border-[var(--brand-border)]"}
                    onClick={() => setFormData({ ...formData, status: "paused" })}
                  >
                    Paused
                  </Button>
                </div>
              </div>

              {/* Country Restriction */}
              <div className="space-y-3 p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Globe size={18} className="text-[#3B82F6]" />
                    <Label className="text-base font-medium">Country Restriction</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">All Countries</span>
                    <button
                      type="button"
                      onClick={() => setFormData({ ...formData, all_countries: !formData.all_countries, allowed_countries: [] })}
                      className={`relative w-11 h-6 rounded-full transition-colors ${formData.all_countries ? 'bg-[#22C55E]' : 'bg-[#27272A]'}`}
                    >
                      <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.all_countries ? 'left-6' : 'left-1'}`} />
                    </button>
                  </div>
                </div>
                
                {!formData.all_countries && (
                  <div className="space-y-2 mt-3">
                    <p className="text-xs text-muted-foreground">Select allowed countries:</p>
                    <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto p-2 bg-[var(--brand-card)] rounded">
                      {COUNTRY_OPTIONS.map((country) => (
                        <button
                          key={country}
                          type="button"
                          onClick={() => toggleCountry(country)}
                          className={`px-2 py-1 text-xs rounded transition-colors ${
                            formData.allowed_countries.includes(country)
                              ? 'bg-[#3B82F6] text-white'
                              : 'bg-[#27272A] text-[#A1A1AA] hover:bg-[#3F3F46]'
                          }`}
                        >
                          {country}
                        </button>
                      ))}
                    </div>
                    {formData.allowed_countries.length > 0 && (
                      <p className="text-xs text-[#3B82F6]">
                        Selected: {formData.allowed_countries.join(", ")}
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* OS Restriction */}
              <div className="space-y-3 p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Monitor size={18} className="text-[#8B5CF6]" />
                    <Label className="text-base font-medium">Device/OS Restriction</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">All Devices</span>
                    <button
                      type="button"
                      onClick={() => setFormData({ ...formData, all_os: !formData.all_os, allowed_os: [] })}
                      className={`relative w-11 h-6 rounded-full transition-colors ${formData.all_os ? 'bg-[#22C55E]' : 'bg-[#27272A]'}`}
                    >
                      <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.all_os ? 'left-6' : 'left-1'}`} />
                    </button>
                  </div>
                </div>
                
                {!formData.all_os && (
                  <div className="space-y-2 mt-3">
                    <p className="text-xs text-muted-foreground">Select allowed operating systems:</p>
                    <div className="grid grid-cols-3 gap-2">
                      {OS_OPTIONS.map((os) => (
                        <button
                          key={os.value}
                          type="button"
                          onClick={() => toggleOS(os.value)}
                          className={`flex items-center gap-2 px-3 py-2 rounded transition-colors ${
                            formData.allowed_os.includes(os.value)
                              ? 'bg-[#8B5CF6] text-white'
                              : 'bg-[#27272A] text-[#A1A1AA] hover:bg-[#3F3F46]'
                          }`}
                        >
                          <span>{os.icon}</span>
                          <span className="text-sm">{os.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* VPN/Proxy Block */}
              <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Shield size={18} className="text-[#EF4444]" />
                    <div>
                      <Label className="text-base font-medium">Block VPN/Proxy</Label>
                      <p className="text-xs text-muted-foreground mt-1">Prevent access from VPN and proxy connections</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, block_vpn: !formData.block_vpn })}
                    className={`relative w-11 h-6 rounded-full transition-colors ${formData.block_vpn ? 'bg-[#EF4444]' : 'bg-[#27272A]'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.block_vpn ? 'left-6' : 'left-1'}`} />
                  </button>
                </div>
              </div>

              {/* Strict Duplicate Check — NEW (2026-01) */}
              {/* When ON: every duplicate IP across ALL links/users rejected (current default behavior preserved). */}
              {/* When OFF: duplicate-IP check fully bypassed — every click passes regardless of history. */}
              <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#22C55E]"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                    <div>
                      <Label className="text-base font-medium">Strict Duplicate Check</Label>
                      <p className="text-xs text-muted-foreground mt-1">
                        ON: same IP cannot click again (anywhere, any time) ·
                        OFF: allow every click — no duplicate filtering
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    data-testid="strict-duplicate-check-toggle"
                    onClick={() => setFormData({ ...formData, strict_duplicate_check: !formData.strict_duplicate_check })}
                    className={`relative w-11 h-6 rounded-full transition-colors ${formData.strict_duplicate_check ? 'bg-[#22C55E]' : 'bg-[#27272A]'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.strict_duplicate_check ? 'left-6' : 'left-1'}`} />
                  </button>
                </div>
              </div>

              {/* Duplicate Timer */}
              <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#F59E0B]"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    <div>
                      <Label className="text-base font-medium">Duplicate IP Block Page Timer</Label>
                      <p className="text-xs text-muted-foreground mt-1">Auto-close the duplicate-IP block screen after N seconds (does not re-allow the IP)</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, duplicate_timer_enabled: !formData.duplicate_timer_enabled })}
                    className={`relative w-11 h-6 rounded-full transition-colors ${formData.duplicate_timer_enabled ? 'bg-[#F59E0B]' : 'bg-[#27272A]'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${formData.duplicate_timer_enabled ? 'left-6' : 'left-1'}`} />
                  </button>
                </div>
                {formData.duplicate_timer_enabled && (
                  <div className="flex items-center gap-3 mt-3 pl-7">
                    <Label className="text-sm text-muted-foreground">Wait time:</Label>
                    <Input
                      type="number"
                      min="1"
                      max="3600"
                      value={formData.duplicate_timer_seconds}
                      onChange={(e) => setFormData({ ...formData, duplicate_timer_seconds: parseInt(e.target.value) || 5 })}
                      className="w-24 bg-[var(--brand-card)] border-[var(--brand-border)]"
                    />
                    <span className="text-sm text-muted-foreground">seconds</span>
                  </div>
                )}
              </div>

              {/* Traffic Source */}
              <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center gap-2 mb-3">
                  <TrendingUp size={18} className="text-[#3B82F6]" />
                  <div>
                    <Label className="text-base font-medium">Traffic Source</Label>
                    <p className="text-xs text-muted-foreground mt-1">Force all clicks from this link to show as specific source</p>
                  </div>
                </div>
                <select
                  value={formData.forced_source}
                  onChange={(e) => {
                    const selectedOption = TRAFFIC_SOURCE_OPTIONS.find(opt => opt.value === e.target.value);
                    setFormData({ 
                      ...formData, 
                      forced_source: e.target.value,
                      forced_source_name: selectedOption?.label || ""
                    });
                  }}
                  className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white"
                >
                  {TRAFFIC_SOURCE_OPTIONS.map(source => (
                    <option key={source.value} value={source.value}>
                      {source.icon} {source.label}
                    </option>
                  ))}
                </select>
                {formData.forced_source && (
                  <p className="text-xs text-[#22C55E] mt-2">
                    All clicks will be recorded as "{TRAFFIC_SOURCE_OPTIONS.find(s => s.value === formData.forced_source)?.label}"
                  </p>
                )}
              </div>

              {/* Referrer Simulation - Make destination see specific referrer */}
              <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex items-center gap-2 mb-3">
                  <ExternalLink size={18} className="text-[#8B5CF6]" />
                  <div>
                    <Label className="text-base font-medium">Referrer Simulation</Label>
                    <p className="text-xs text-muted-foreground mt-1">Make destination website see traffic as from specific platform</p>
                  </div>
                </div>
                
                {/* Referrer Mode */}
                <div className="space-y-3">
                  <div>
                    <Label className="text-xs text-[#A1A1AA]">Referrer Mode</Label>
                    <select
                      value={formData.referrer_mode}
                      onChange={(e) => setFormData({ ...formData, referrer_mode: e.target.value })}
                      className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1"
                    >
                      {REFERRER_MODE_OPTIONS.map(mode => (
                        <option key={mode.value} value={mode.value}>
                          {mode.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-[#52525B] mt-1">
                      {REFERRER_MODE_OPTIONS.find(m => m.value === formData.referrer_mode)?.description}
                    </p>
                  </div>
                  
                  {/* Platform Simulation */}
                  <div>
                    <Label className="text-xs text-[#A1A1AA]">Simulate Platform (Add Click IDs to URL)</Label>
                    <select
                      value={formData.simulate_platform}
                      onChange={(e) => setFormData({ ...formData, simulate_platform: e.target.value })}
                      className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1"
                    >
                      {PLATFORM_SIMULATION_OPTIONS.map(platform => (
                        <option key={platform.value} value={platform.value}>
                          {platform.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-[#52525B] mt-1">
                      {PLATFORM_SIMULATION_OPTIONS.find(p => p.value === formData.simulate_platform)?.description}
                    </p>
                  </div>
                  
                  {formData.simulate_platform && (
                    <div className="p-3 bg-[var(--brand-card)] rounded border border-[var(--brand-border)]">
                      <p className="text-xs text-[#22C55E]">
                        <strong>Example URL:</strong><br/>
                        {formData.simulate_platform === "facebook" && "offer.com?fbclid=IwAR3xyz...&utm_source=facebook"}
                        {formData.simulate_platform === "tiktok" && "offer.com?ttclid=abc123...&utm_source=tiktok"}
                        {formData.simulate_platform === "instagram" && "offer.com?igshid=xyz...&utm_source=instagram"}
                        {formData.simulate_platform === "google" && "offer.com?gclid=Cj0KC...&utm_source=google"}
                        {formData.simulate_platform === "twitter" && "offer.com?twclid=abc...&utm_source=twitter"}
                        {formData.simulate_platform === "whatsapp" && "offer.com?utm_source=whatsapp&utm_medium=social"}
                        {formData.simulate_platform === "youtube" && "offer.com?utm_source=youtube&utm_medium=video"}
                        {!["facebook", "tiktok", "instagram", "google", "twitter", "whatsapp", "youtube"].includes(formData.simulate_platform) && 
                          `offer.com?utm_source=${formData.simulate_platform}`}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {/* v2.1.80 — Advanced Referrer System (RUT-style, applied per-click) */}
              <div className="p-4 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <button
                  type="button"
                  onClick={() => setProReferrerOpen(!proReferrerOpen)}
                  className="w-full flex items-center justify-between gap-2 text-left"
                  data-testid="pro-referrer-toggle"
                >
                  <div className="flex items-center gap-2">
                    <Sparkles size={18} className="text-[#F59E0B]" />
                    <div>
                      <Label className="text-base font-medium cursor-pointer">
                        Advanced Referrer System (RUT-style)
                      </Label>
                      <p className="text-xs text-muted-foreground mt-1">
                        Per-click platform rotation, real referer wrappers, brand-tagged UTMs — same engine as RUT jobs, applied automatically when anyone clicks this link
                      </p>
                    </div>
                  </div>
                  {proReferrerOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </button>

                {proReferrerOpen && (
                  <div className="mt-4 space-y-4 pt-4 border-t border-[var(--brand-border)]">
                    {/* Master toggle */}
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formData.referrer_pro_enabled}
                        onChange={(e) => setFormData({ ...formData, referrer_pro_enabled: e.target.checked })}
                        className="w-4 h-4"
                        data-testid="pro-referrer-enabled"
                      />
                      <span className="text-sm font-medium">
                        Enable Pro-Referrer for this link
                      </span>
                    </label>
                    <p className="text-xs text-[#F59E0B] -mt-2">
                      When OFF, this link uses the classic Traffic Source + Referrer Mode fields above (safe / unchanged behavior). When ON, every click resolves fresh from the pool below.
                    </p>

                    {formData.referrer_pro_enabled && (
                      <>
                        {/* ═════════════════════════════════════════════════
                            v2.1.83 — Beginner Step-by-Step Guide.
                            Shown right after the customer flips the master
                            switch — walks through what Krexion will do on
                            every click, WHY each guardrail exists, and the
                            business benefit of turning each one on. Simple
                            Roman-Urdu/English mix. Collapsible.
                           ═════════════════════════════════════════════════ */}
                        <div className="rounded-lg border-2 border-[#F59E0B60] bg-gradient-to-br from-[#F59E0B10] to-[#3B82F608]">
                          <button
                            type="button"
                            onClick={() => setGuideOpen(!guideOpen)}
                            className="w-full flex items-center justify-between p-3 hover:bg-[#F59E0B08] transition-colors"
                            data-testid="referrer-guide-toggle"
                          >
                            <div className="flex items-center gap-2">
                              <span className="text-lg">📖</span>
                              <span className="text-sm font-semibold text-[#F59E0B]">
                                Referrer Mode kaise kaam karta hai? — Step-by-Step Guide
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] text-[#A1A1AA]">
                                {guideOpen ? "Chhupayen" : "Dekhen"}
                              </span>
                              {guideOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                            </div>
                          </button>

                          {guideOpen && (
                            <div className="p-3 border-t border-[#F59E0B30] space-y-2">
                              {/* Intro */}
                              <p className="text-xs text-[#A1A1AA] leading-relaxed">
                                Jab bhi koi customer aap ki Krexion link click karega,
                                Krexion background mein <strong className="text-white">10 checks</strong> chalata
                                hai taake wo click ek <em className="text-[#F59E0B]">real user ki jaisi</em> lage.
                                Neeche har step visually samjhayi gayi hai — kya hota hai, kyu zaruri hai, aur faida kya milta hai.
                              </p>

                              {/* Flow diagram */}
                              <div className="my-3 p-2 rounded-lg bg-[var(--brand-bg)] border border-[var(--brand-border)]">
                                <div className="flex items-center justify-between text-[10px] flex-wrap gap-1">
                                  <span className="px-2 py-1 rounded bg-[#3B82F620] text-[#3B82F6]">👆 Click</span>
                                  <span className="text-[#52525B]">→</span>
                                  <span className="px-2 py-1 rounded bg-[#8B5CF620] text-[#8B5CF6]">🎯 Krexion</span>
                                  <span className="text-[#52525B]">→</span>
                                  <span className="px-2 py-1 rounded bg-[#F59E0B20] text-[#F59E0B]">🎭 Fake real click</span>
                                  <span className="text-[#52525B]">→</span>
                                  <span className="px-2 py-1 rounded bg-[#22C55E20] text-[#22C55E]">✅ Offer accepts</span>
                                  <span className="text-[#52525B]">→</span>
                                  <span className="px-2 py-1 rounded bg-[#EC489920] text-[#EC4899]">💰 Conversion + Postback</span>
                                </div>
                              </div>

                              {/* Steps */}
                              {[
                                {
                                  n: 1,
                                  icon: "🎯",
                                  color: "#8B5CF6",
                                  title: "Platform Pool se ek platform pick karo",
                                  what: "Krexion aap ki set ki hui weights ke hisab se ek platform choose karta hai — Facebook, TikTok, Google search, Email etc.",
                                  why: "Har click ek alag platform se aata hua dikhta hai — network sochti hai aap ki traffic diverse hai (jaise real ads).",
                                  benefit: "Networks ko lagta hai aap 5-10 alag channels chala rahe hain. Diversity = trust = higher payouts.",
                                  setting: "Platform Pool section — ticks + sliders",
                                },
                                {
                                  n: 2,
                                  icon: "🔗",
                                  color: "#3B82F6",
                                  title: "Realistic Referer URL banao",
                                  what: "Agar Facebook pick hua to Referer URL banti hai jaise 'facebook.com/permalink...', agar Google search hua to 'google.com/search?q=...'. Aap ki brand name automatic add hoti hai.",
                                  why: "Har network Referer header check karti hai. Empty ya fake Referer = instant reject.",
                                  benefit: "Offer ke server ko lagta hai click asli Facebook ad ya Google search se aaya. 100% acceptance.",
                                  setting: "Automatic — aap ka Brand Tag field use hota hai",
                                },
                                {
                                  n: 3,
                                  icon: "🌍",
                                  color: "#22C55E",
                                  title: "Accept-Language country se match karo",
                                  what: "Aap ne Germany choose ki? Krexion header bhejta hai 'de-DE,de;q=0.9' — na ke 'en-US'. Har country ka apna language format.",
                                  why: "Fraud detectors ka #1 check yeh hai. German proxy + English language = red flag = instant reject.",
                                  benefit: "European aur Asian offers ka acceptance rate 20-40% increase. Bina is ke MaxBounty/Cake reject karti hain.",
                                  setting: "Country dropdown + 'Match Accept-Language' toggle",
                                },
                                {
                                  n: 4,
                                  icon: "📱",
                                  color: "#EC4899",
                                  title: "Device type match karo",
                                  what: "TikTok / Instagram / WhatsApp = sirf mobile. LinkedIn = mostly desktop. Krexion visitor ka UA dekhta hai aur platform pool filter karta hai.",
                                  why: "TikTok click from Windows desktop = kabhi nahi hota real world mein. Networks yeh instantly flag karti hain.",
                                  benefit: "Traffic distribution real-world jaisi. Offer analytics dashboard 'suspicious device combo' warnings nahi deta.",
                                  setting: "Device Distribution dropdown → 'match_platform'",
                                },
                                {
                                  n: 5,
                                  icon: "🕒",
                                  color: "#F59E0B",
                                  title: "Time-of-day realistic distribution",
                                  what: "TikTok peaks 6-11 PM, LinkedIn business hours only, Facebook 7-9 AM + 12-1 PM + 7-10 PM. Krexion current time dekh kar platform weights adjust karta hai.",
                                  why: "Agar aap ke sab clicks 3 AM aa rahe hain to network ko instantly pata chal jayega yeh bot traffic hai.",
                                  benefit: "Clicks natural pattern follow karte hain. 'Suspicious 3am spike' fraud flag avoid hoti hai.",
                                  setting: "'Time-of-day realism weighting' checkbox",
                                },
                                {
                                  n: 6,
                                  icon: "🎨",
                                  color: "#06B6D4",
                                  title: "UTM parameters banao (real campaign jaisa)",
                                  what: "utm_source=facebook, utm_medium=paid_social, utm_content=video_a, utm_campaign=irestore_lookalike_m35 — sab dynamic. Aap Campaign Type dropdown se choose kar sakte hain.",
                                  why: "Voluum, Everflow, HasOffers dashboards yeh dikhate hain. Bina proper UTMs ke conversions attribute nahi hoti.",
                                  benefit: "Aap ka tracker (Voluum) proper campaign source dikhata hai. Analytics saaf. A/B testing ke liye ready.",
                                  setting: "Campaign Type dropdown (10 presets)",
                                },
                                {
                                  n: 7,
                                  icon: "🔄",
                                  color: "#EAB308",
                                  title: "Wrapper redirect chain (Premium tier only)",
                                  what: "Click actually goes through 'lm.facebook.com/l.php?u=...' ya 'google.com/url?q=...' — asli Facebook wrapper. Offer ko Referer header mein real facebook.com domain milta hai.",
                                  why: "MaxBounty aur Cake ki top-tier offers Referer header ko strictly check karti hain. Sirf yeh check pass karta hai to top payouts milte hain.",
                                  benefit: "Premium networks accept karte hain. 2-3x higher EPC on top-tier offers. Adds ~50ms per click.",
                                  setting: "Quality Tier: Premium (turns this ON automatically)",
                                },
                                {
                                  n: 8,
                                  icon: "🧩",
                                  color: "#A855F7",
                                  title: "Sub-ID / ClickID macros expand karo",
                                  what: "Aap ki offer URL mein {click_id}, {source}, {campaign}, {country}, {utm_medium} etc. macros write karen — Krexion har click pe replace karta hai unique values se.",
                                  why: "Networks ki apni tracking hoti hai (MaxBounty=s1, ClickDealer=aff_sub, Everflow=sub1-5). Bina passthrough ke conversion attribute nahi hoti.",
                                  benefit: "Har conversion aap ki proper campaign pe attribute hoti hai. Commission lost nahi hoti. Multi-network setups possible.",
                                  setting: "Offer URL field mein macros likhen — Feature 2 info card",
                                },
                                {
                                  n: 9,
                                  icon: "🔀",
                                  color: "#14B8A6",
                                  title: "Multi-URL A/B rotation (agar set kya)",
                                  what: "Aap 2-3 landing pages weights ke sath set kar sakte hain (LP-A: 60%, LP-B: 30%, LP-C: 10%). Krexion har click pe weighted-random pick karta hai.",
                                  why: "Same offer ke different landing pages test karne se aap best-performing find kar sakte hain.",
                                  benefit: "Continuous A/B testing without extra tools. 20-50% conversion rate improvement over time.",
                                  setting: "Multi-URL A/B Rotation section — Add landing page",
                                },
                                {
                                  n: 10,
                                  icon: "💰",
                                  color: "#EC4899",
                                  title: "Conversion → Postback forward → Auto-pause guard",
                                  what: "Jab offer ki taraf se conversion aati hai to Krexion aap ke Voluum/Everflow tracker ko S2S postback bhej deti hai. Agar 10 back-to-back clicks convert na hon to link auto-pause ho jati hai.",
                                  why: "Voluum/Everflow ke bina auto postback, aap ke dashboard mein conversions dikhayi nahi deti. Auto-pause proxy quota bachati hai jab offer dead ho jaye.",
                                  benefit: "Zero manual work. Dead offers khud rukh jaate hain. Aap ka analytics tool aur Krexion sync rehte hain.",
                                  setting: "Postback template picker + Auto-Pause threshold",
                                },
                              ].map((s) => (
                                <div
                                  key={s.n}
                                  className="p-2 rounded border border-[var(--brand-border)] bg-[var(--brand-bg)]"
                                  data-testid={`guide-step-${s.n}`}
                                >
                                  <div className="flex items-start gap-2">
                                    <div
                                      className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                                      style={{ background: s.color + "20", color: s.color }}
                                    >
                                      {s.n}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-1.5 mb-1">
                                        <span className="text-base">{s.icon}</span>
                                        <span className="text-xs font-semibold text-white">{s.title}</span>
                                      </div>
                                      <div className="space-y-1">
                                        <div className="text-[11px] text-[#D4D4D8]">
                                          <span className="text-[#A1A1AA] font-medium">Kya hota hai: </span>
                                          {s.what}
                                        </div>
                                        <div className="text-[11px] text-[#D4D4D8]">
                                          <span className="text-[#EF4444] font-medium">Kyu zaruri hai: </span>
                                          {s.why}
                                        </div>
                                        <div className="text-[11px] text-[#D4D4D8]">
                                          <span className="text-[#22C55E] font-medium">Faida kya: </span>
                                          {s.benefit}
                                        </div>
                                        <div className="text-[10px] text-[#F59E0B] font-mono pt-0.5">
                                          ⚙ Setting: {s.setting}
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              ))}

                              {/* Bottom TL;DR */}
                              <div className="mt-3 p-2 rounded-lg bg-gradient-to-r from-[#22C55E20] to-[#3B82F620] border border-[#22C55E60]">
                                <p className="text-[11px] text-[#D4D4D8] leading-relaxed">
                                  <span className="text-[#22C55E] font-bold">💡 TL;DR — </span>
                                  Sab 10 features ON hon (Quality Tier = Premium) to aap ka har click bilkul <strong className="text-white">real user ki tarah</strong> lagega.
                                  MaxBounty, ClickDealer, Everflow, Cake, Voluum — koi network reject nahi karegi. Fraud score 0/100.
                                  Har conversion attribute hogi, aap ka tracker sync rahega, dead offers auto-pause hongi.
                                  <br />
                                  <span className="text-[#F59E0B] mt-1 block">
                                    Beginner setup: sirf <strong>Quality Tier → Premium</strong> click karen, phir Platform Pool aur Country choose karen. Baaki settings automatic set ho jayen gi. Ho gaya!
                                  </span>
                                </p>
                              </div>

                              {/* Beginner quick-start CTA */}
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => {
                                    applyQualityTier("premium");
                                    // Pre-select a sensible default pool if empty
                                    if (!formData.referrer_pro_platform_pool) {
                                      setFormData((prev) => ({
                                        ...prev,
                                        referrer_pro_platform_pool: "facebook:40,tiktok:20,google:20,email:10,instagram:10",
                                        referrer_pro_quality_tier: "premium",
                                        referrer_pro_lang_match: true,
                                        referrer_pro_social_wrapper: true,
                                        referrer_pro_inapp_deep_path: true,
                                        referrer_pro_strip_search_path: true,
                                        referrer_pro_wrapper_redirect: true,
                                        referrer_pro_tod_enabled: true,
                                        referrer_pro_device_mode: "match_platform",
                                      }));
                                    }
                                    toast.success("Premium setup applied — bas Offer URL aur Country choose kar ke Save karo!");
                                  }}
                                  className="px-3 py-1.5 text-xs font-semibold rounded bg-[#F59E0B] hover:bg-[#D97706] text-black flex items-center gap-1.5"
                                  data-testid="beginner-quickstart"
                                >
                                  <Sparkles size={12} /> Beginner Quick-Start (Premium setup)
                                </button>
                                <span className="text-[10px] text-[#52525B]">
                                  Automatically applies best settings for MaxBounty/Cake/Everflow acceptance.
                                </span>
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Platform Pool (weighted) — v2.1.83: visual builder replaces the raw text field */}
                        <div>
                          <Label className="text-xs text-[#A1A1AA]">Platform Pool (weighted)</Label>
                          <div className="mt-1 p-2 rounded border border-[var(--brand-border)] bg-[var(--brand-bg)]">
                            {(() => {
                              const pool = parsePlatformPool(formData.referrer_pro_platform_pool || "");
                              const poolMap = Object.fromEntries(pool.map(p => [p.key, p.weight]));
                              const totalWeight = pool.reduce((s, p) => s + (p.weight || 0), 0) || 0;
                              const togglePlatform = (key) => {
                                const next = { ...poolMap };
                                if (next[key] !== undefined) delete next[key];
                                else next[key] = 20;
                                setFormData({
                                  ...formData,
                                  referrer_pro_platform_pool: stringifyPlatformPool(
                                    Object.entries(next).map(([k, w]) => ({ key: k, weight: w }))
                                  )
                                });
                              };
                              const setWeight = (key, w) => {
                                const next = { ...poolMap, [key]: Math.max(1, parseInt(w) || 1) };
                                setFormData({
                                  ...formData,
                                  referrer_pro_platform_pool: stringifyPlatformPool(
                                    Object.entries(next).map(([k, w2]) => ({ key: k, weight: w2 }))
                                  )
                                });
                              };
                              return (
                                <>
                                  <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5">
                                    {PLATFORM_OPTIONS.map((p) => {
                                      const selected = poolMap[p.key] !== undefined;
                                      const w = poolMap[p.key] || 0;
                                      const pct = totalWeight > 0 && selected ? Math.round((w / totalWeight) * 100) : 0;
                                      return (
                                        <div
                                          key={p.key}
                                          className={`p-1.5 rounded border text-xs transition-all ${
                                            selected
                                              ? "border-[#F59E0B] bg-[#F59E0B10]"
                                              : "border-[var(--brand-border)] hover:border-[#F59E0B60] opacity-70"
                                          }`}
                                        >
                                          <label className="flex items-center gap-1.5 cursor-pointer">
                                            <input
                                              type="checkbox"
                                              checked={selected}
                                              onChange={() => togglePlatform(p.key)}
                                              className="w-3.5 h-3.5"
                                              data-testid={`platform-toggle-${p.key}`}
                                            />
                                            <span className="text-sm">{p.emoji}</span>
                                            <span className="flex-1 truncate font-medium">{p.label}</span>
                                            {selected && (
                                              <span className="text-[10px] text-[#F59E0B] font-mono">
                                                {pct}%
                                              </span>
                                            )}
                                          </label>
                                          {selected && (
                                            <div className="mt-1 flex items-center gap-1.5">
                                              <input
                                                type="range"
                                                min={1}
                                                max={100}
                                                value={w}
                                                onChange={(e) => setWeight(p.key, e.target.value)}
                                                className="flex-1 h-1.5"
                                                data-testid={`platform-weight-${p.key}`}
                                              />
                                              <input
                                                type="number"
                                                min={1}
                                                max={100}
                                                value={w}
                                                onChange={(e) => setWeight(p.key, e.target.value)}
                                                className="w-12 px-1 py-0 text-[10px] rounded bg-[var(--brand-card)] border border-[var(--brand-border)] text-white"
                                              />
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                  <div className="mt-2 flex items-center justify-between text-[10px] text-[#52525B]">
                                    <span>
                                      {pool.length === 0
                                        ? "Tick platforms above — set weight for each"
                                        : `${pool.length} platform(s) selected · Total weight: ${totalWeight}`}
                                    </span>
                                    {pool.length > 0 && (
                                      <button
                                        type="button"
                                        onClick={() => setFormData({ ...formData, referrer_pro_platform_pool: "" })}
                                        className="text-[#EF4444] hover:underline"
                                      >
                                        Clear all
                                      </button>
                                    )}
                                  </div>
                                </>
                              );
                            })()}
                          </div>
                        </div>

                        {/* Brand */}
                        <div>
                          <Label className="text-xs text-[#A1A1AA]">Brand Tag (for UTM campaigns)</Label>
                          <Input
                            value={formData.referrer_pro_brand}
                            onChange={(e) => setFormData({ ...formData, referrer_pro_brand: e.target.value })}
                            placeholder="acme, mybrand, offer42..."
                            className="mt-1"
                          />
                          <p className="text-xs text-[#52525B] mt-1">Feeds into utm_campaign naming (e.g. <code>acme_lookalike_m35_video_a</code>)</p>
                        </div>

                        {/* Search Engine + Keywords */}
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <Label className="text-xs text-[#A1A1AA]">Search Engine</Label>
                            <select
                              value={formData.referrer_pro_search_engine}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_search_engine: e.target.value })}
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1"
                            >
                              <option value="google">Google</option>
                              <option value="bing">Bing</option>
                              <option value="duckduckgo">DuckDuckGo</option>
                              <option value="yahoo">Yahoo</option>
                              <option value="yandex">Yandex</option>
                            </select>
                          </div>
                          <div>
                            <Label className="text-xs text-[#A1A1AA]">Country (auto-matches language)</Label>
                            <select
                              value={formData.referrer_pro_country || ""}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_country: e.target.value })}
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-sm"
                              data-testid="pro-country"
                            >
                              <option value="">— Any country (no geo-lock) —</option>
                              {PRO_COUNTRY_OPTIONS.map((c) => (
                                <option key={c.code} value={c.code}>
                                  {c.flag} {c.name} ({c.code.toUpperCase()})
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>

                        <div>
                          <Label className="text-xs text-[#A1A1AA]">Search Keywords (one per line)</Label>
                          <textarea
                            value={formData.referrer_pro_search_keywords}
                            onChange={(e) => setFormData({ ...formData, referrer_pro_search_keywords: e.target.value })}
                            rows={3}
                            placeholder={"best diet plan 2026\nketo meals for beginners\ngluten free recipes"}
                            className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-sm"
                          />
                          <p className="text-xs text-[#52525B] mt-1">Used when the pool picks a search engine (google, bing, etc.)</p>
                        </div>

                        {/* Email Weights (visual sliders replace raw JSON) */}
                        <div>
                          <Label className="text-xs text-[#A1A1AA]">Email ESP Mix (used when pool picks &quot;email&quot;)</Label>
                          <div className="mt-1 p-2 rounded border border-[var(--brand-border)] bg-[var(--brand-bg)]">
                            {(() => {
                              const espMap = parseEmailWeights(formData.referrer_pro_email_weights || "");
                              const totalW = Object.values(espMap).reduce((s, v) => s + (parseFloat(v) || 0), 0) || 0;
                              const toggleEsp = (key) => {
                                const next = { ...espMap };
                                if (next[key] !== undefined) delete next[key];
                                else next[key] = 20;
                                setFormData({ ...formData, referrer_pro_email_weights: stringifyEmailWeights(next) });
                              };
                              const setEspW = (key, w) => {
                                const next = { ...espMap, [key]: Math.max(1, parseInt(w) || 1) };
                                setFormData({ ...formData, referrer_pro_email_weights: stringifyEmailWeights(next) });
                              };
                              return (
                                <>
                                  <div className="grid grid-cols-2 gap-1.5">
                                    {ESP_OPTIONS.map((e) => {
                                      const selected = espMap[e.key] !== undefined;
                                      const w = espMap[e.key] || 0;
                                      const pct = totalW > 0 && selected ? Math.round((w / totalW) * 100) : 0;
                                      return (
                                        <div
                                          key={e.key}
                                          className={`p-1.5 rounded border text-xs transition-all ${
                                            selected
                                              ? "border-[#F59E0B] bg-[#F59E0B10]"
                                              : "border-[var(--brand-border)] hover:border-[#F59E0B60] opacity-70"
                                          }`}
                                        >
                                          <label className="flex items-center gap-1.5 cursor-pointer">
                                            <input
                                              type="checkbox"
                                              checked={selected}
                                              onChange={() => toggleEsp(e.key)}
                                              className="w-3.5 h-3.5"
                                              data-testid={`esp-toggle-${e.key}`}
                                            />
                                            <span className="text-sm">{e.emoji}</span>
                                            <span className="flex-1 truncate font-medium">{e.label}</span>
                                            {selected && (
                                              <span className="text-[10px] text-[#F59E0B] font-mono">{pct}%</span>
                                            )}
                                          </label>
                                          {selected && (
                                            <div className="mt-1 flex items-center gap-1.5">
                                              <input
                                                type="range"
                                                min={1}
                                                max={100}
                                                value={w}
                                                onChange={(ev) => setEspW(e.key, ev.target.value)}
                                                className="flex-1 h-1.5"
                                              />
                                              <input
                                                type="number"
                                                min={1}
                                                max={100}
                                                value={w}
                                                onChange={(ev) => setEspW(e.key, ev.target.value)}
                                                className="w-12 px-1 py-0 text-[10px] rounded bg-[var(--brand-card)] border border-[var(--brand-border)] text-white"
                                              />
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                  <p className="text-[10px] text-[#52525B] mt-2">Tick ESPs above · rotates them on email visits with these weights</p>
                                </>
                              );
                            })()}
                          </div>
                        </div>

                        {/* Toggles */}
                        <div className="grid grid-cols-2 gap-2">
                          <label className="flex items-center gap-2 cursor-pointer p-2 rounded border border-[var(--brand-border)]">
                            <input
                              type="checkbox"
                              checked={formData.referrer_pro_social_wrapper}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_social_wrapper: e.target.checked })}
                              className="w-4 h-4"
                            />
                            <span className="text-xs">Social wrappers (l.fb.com, etc.)</span>
                          </label>
                          <label className="flex items-center gap-2 cursor-pointer p-2 rounded border border-[var(--brand-border)]">
                            <input
                              type="checkbox"
                              checked={formData.referrer_pro_inapp_deep_path}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_inapp_deep_path: e.target.checked })}
                              className="w-4 h-4"
                            />
                            <span className="text-xs">In-app deep paths (FB/IG webview)</span>
                          </label>
                          <label className="flex items-center gap-2 cursor-pointer p-2 rounded border border-[var(--brand-border)]">
                            <input
                              type="checkbox"
                              checked={formData.referrer_pro_strip_search_path}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_strip_search_path: e.target.checked })}
                              className="w-4 h-4"
                            />
                            <span className="text-xs">Strip search-engine paths</span>
                          </label>
                        </div>

                        {/* Wrapper redirect — the powerful one */}
                        <label className="flex items-start gap-2 cursor-pointer p-3 rounded border-2 border-[#F59E0B] bg-[#F59E0B08]">
                          <input
                            type="checkbox"
                            checked={formData.referrer_pro_wrapper_redirect}
                            onChange={(e) => setFormData({ ...formData, referrer_pro_wrapper_redirect: e.target.checked })}
                            className="w-4 h-4 mt-0.5"
                            data-testid="pro-wrapper-redirect"
                          />
                          <div>
                            <span className="text-sm font-medium">Wrapper redirect chain (recommended)</span>
                            <p className="text-xs text-[#A1A1AA] mt-1">
                              Bounces every click through the real platform wrapper (<code>l.facebook.com/l.php?u=...</code>, <code>google.com/url?q=...</code>, <code>t.co/...</code> etc.). The offer sees a REAL platform domain as Referer — most powerful anti-detect. Adds ~50ms per click.
                            </p>
                            <p className="text-[10px] text-[#22C55E] mt-1.5 font-medium">
                              ✨ v2.2.0 Smart Wrapper — Cold external clicks (WhatsApp share, direct paste) automatically SKIP warning-trigger wrappers. In-app FB/IG/TT clicks still use the wrapper (silently bypassed). No more &quot;Leaving Facebook&quot; warnings for end users.
                            </p>
                          </div>
                        </label>

                        {/* ─────────────────────────────────────────────────
                            v2.1.83 — International Fraud-Detector Guardrails
                            (10-feature pack, network-agnostic MaxBounty /
                             ClickDealer / Everflow / Cake / Voluum ready)
                           ───────────────────────────────────────────────── */}
                        <div className="pt-2 mt-2 border-t border-[var(--brand-border)]">
                          <p className="text-xs font-medium text-[#F59E0B] mb-3 flex items-center gap-1.5">
                            <Sparkles size={12} /> International Guardrails
                          </p>

                          {/* Feature 6 — Quality Tier one-click preset */}
                          <div className="mb-4">
                            <Label className="text-xs text-[#A1A1AA]">Quality Tier (Feature 6 — one-click preset)</Label>
                            <div className="grid grid-cols-3 gap-2 mt-1">
                              {[
                                { v: "premium",    l: "🟢 Premium",    d: "MaxBounty / Cake top tier" },
                                { v: "standard",   l: "🟡 Standard",   d: "Balanced (default)" },
                                { v: "aggressive", l: "🔴 Aggressive", d: "Gambling / adult / crypto" },
                              ].map((t) => (
                                <button
                                  key={t.v}
                                  type="button"
                                  onClick={() => applyQualityTier(t.v)}
                                  className={`p-2 rounded border text-left text-xs transition-all ${
                                    formData.referrer_pro_quality_tier === t.v
                                      ? "border-[#F59E0B] bg-[#F59E0B15] text-[#F59E0B]"
                                      : "border-[var(--brand-border)] hover:border-[#F59E0B60]"
                                  }`}
                                  data-testid={`quality-tier-${t.v}`}
                                >
                                  <div className="font-medium">{t.l}</div>
                                  <div className="text-[10px] text-[#A1A1AA] mt-0.5">{t.d}</div>
                                </button>
                              ))}
                            </div>
                            <p className="text-[10px] text-[#52525B] mt-1">
                              One-click preset for the 8 realism toggles below. Overrides current values.
                            </p>
                          </div>

                          <div className="grid grid-cols-2 gap-3">
                            {/* Feature 1 — Accept-Language country match */}
                            <label className="flex items-start gap-2 cursor-pointer p-2 rounded border border-[var(--brand-border)]">
                              <input
                                type="checkbox"
                                checked={formData.referrer_pro_lang_match}
                                onChange={(e) => setFormData({ ...formData, referrer_pro_lang_match: e.target.checked })}
                                className="w-4 h-4 mt-0.5"
                                data-testid="pro-lang-match"
                              />
                              <div>
                                <div className="text-xs font-medium">🌍 Match Accept-Language to country</div>
                                <p className="text-[10px] text-[#52525B] mt-0.5">
                                  Feature 1 — Germany proxy sends <code>de-DE,de;q=0.9</code> not <code>en-US</code>. Boosts EU/Asia offer accept rate 20-40%.
                                </p>
                              </div>
                            </label>

                            {/* Feature 4 — Time-of-day realism */}
                            <label className="flex items-start gap-2 cursor-pointer p-2 rounded border border-[var(--brand-border)]">
                              <input
                                type="checkbox"
                                checked={formData.referrer_pro_tod_enabled}
                                onChange={(e) => setFormData({ ...formData, referrer_pro_tod_enabled: e.target.checked })}
                                className="w-4 h-4 mt-0.5"
                                data-testid="pro-tod-enabled"
                              />
                              <div>
                                <div className="text-xs font-medium">🕒 Time-of-day realism weighting</div>
                                <p className="text-[10px] text-[#52525B] mt-0.5">
                                  Feature 4 — FB peaks 7-9am / 7-10pm, TikTok 6-11pm, LinkedIn business hours. Avoids &quot;suspicious 3am spike&quot; flags.
                                </p>
                              </div>
                            </label>
                          </div>

                          {/* Feature 3 — Device Type per Platform */}
                          <div className="mt-3">
                            <Label className="text-xs text-[#A1A1AA]">📱 Device Distribution (Feature 3)</Label>
                            <select
                              value={formData.referrer_pro_device_mode}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_device_mode: e.target.value })}
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-sm"
                              data-testid="pro-device-mode"
                            >
                              <option value="auto">Auto — any device fits any platform (legacy)</option>
                              <option value="match_platform">Strict — TikTok/IG only on mobile UA, LinkedIn on desktop UA</option>
                              <option value="mobile_only">Mobile-only pool (drop desktop-leaning platforms)</option>
                              <option value="desktop_only">Desktop-only pool (drop mobile-only platforms)</option>
                            </select>
                            <p className="text-[10px] text-[#52525B] mt-1">
                              Prevents red-flag combinations like &quot;TikTok click from Windows desktop&quot; that fraud detectors instantly reject.
                            </p>
                          </div>

                          {/* Feature 5 — Campaign Type Preset */}
                          <div className="mt-3">
                            <Label className="text-xs text-[#A1A1AA]">🎯 Campaign Type / UTM Preset (Feature 5)</Label>
                            <select
                              value={formData.referrer_pro_campaign_type}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_campaign_type: e.target.value })}
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-sm"
                              data-testid="pro-campaign-type"
                            >
                              <option value="auto">Auto — random per-visit rotation (legacy)</option>
                              <option value="static_image">Static Image Ad — utm_content=static_image</option>
                              <option value="video_ad">Video Ad — utm_content=video_a</option>
                              <option value="carousel_ad">Carousel Ad — utm_content=carousel_v2</option>
                              <option value="story_ad">Story Ad — utm_content=story_9x16</option>
                              <option value="lookalike_prospect">Lookalike Prospecting — utm_term=lookalike_m35</option>
                              <option value="retargeting_warm">Retargeting (Warm Audience)</option>
                              <option value="retargeting_cold">Retargeting (Cold Audience)</option>
                              <option value="cold_email">Cold Email Outreach</option>
                              <option value="search_cpc">Search / CPC (Google Ads)</option>
                            </select>
                            <p className="text-[10px] text-[#52525B] mt-1">
                              Sets utm_medium / utm_content / utm_term to a realistic campaign combo — Meta / Google / Voluum dashboards render properly.
                            </p>
                          </div>

                          {/* v2.6.24 — Traffic Type: Paid vs Organic Referer Split */}
                          <div className="mt-3">
                            <Label className="text-xs text-[#A1A1AA]">🚦 Traffic Type (v2.6.24 — Paid vs Organic split)</Label>
                            <select
                              value={formData.referrer_pro_traffic_type || 'auto'}
                              onChange={(e) => setFormData({ ...formData, referrer_pro_traffic_type: e.target.value })}
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-sm"
                              data-testid="pro-traffic-type"
                            >
                              <option value="auto">Auto — detect from Campaign Type + platform (safest default)</option>
                              <option value="paid">Paid Ads — use paid-ad referer pool (l.facebook.com w/ __cft__, googleads.g.doubleclick.net, t.co, empty for TikTok, etc.)</option>
                              <option value="organic">Organic — use organic-click referer pool (google.tld origin only, pfbid post URLs, no ad tracking params)</option>
                              <option value="mixed">Mixed — 60% paid / 40% organic (realistic real-world blend)</option>
                            </select>
                            <p className="text-[10px] text-[#52525B] mt-1">
                              Applies platform-specific real-capture referer patterns for all 10 supported platforms. &quot;Auto&quot; preserves legacy behaviour for existing links — pick Paid / Organic / Mixed to force a specific mode.
                            </p>
                          </div>

                          {/* v2.6.29 — Custom tracker param key for paid/organic inject */}
                          <div className="mt-3">
                            <Label className="text-xs text-[#A1A1AA]">📊 Traffic Type Param Key</Label>
                            <input
                              type="text"
                              value={formData.traffic_type_param || ""}
                              onChange={(e) => setFormData({ ...formData, traffic_type_param: e.target.value })}
                              placeholder="sub2 (default) — or aff_sub2, s2, p2 …"
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-sm font-mono"
                              data-testid="traffic-type-param"
                            />
                            <p className="text-[10px] text-[#52525B] mt-1">
                              Query param injected on redirect when Traffic Type resolves to paid/organic. Leave blank for default <span className="font-mono">sub2</span>.
                            </p>
                          </div>

                          {/* Feature 7 — Multi-URL A/B Rotation (visual row-builder) */}
                          <div className="mt-3">
                            <Label className="text-xs text-[#A1A1AA]">🔀 Multi-URL A/B Rotation (Feature 7)</Label>
                            <div className="mt-1 p-2 rounded border border-[var(--brand-border)] bg-[var(--brand-bg)]">
                              {(() => {
                                const rows = parseOfferUrls(formData.referrer_pro_offer_urls || "");
                                const totalW = rows.reduce((s, r) => s + (r.weight || 0), 0) || 0;
                                const setRows = (next) => {
                                  setFormData({ ...formData, referrer_pro_offer_urls: stringifyOfferUrls(next) });
                                };
                                const addRow = () => setRows([...rows, { url: "", weight: 20 }]);
                                const updateRow = (i, patch) => {
                                  const next = rows.slice();
                                  next[i] = { ...next[i], ...patch };
                                  setRows(next);
                                };
                                const removeRow = (i) => setRows(rows.filter((_, idx) => idx !== i));
                                return (
                                  <>
                                    {rows.length === 0 && (
                                      <p className="text-[11px] text-[#52525B] py-1">
                                        Leave empty to use the single &quot;Offer URL&quot; above.
                                      </p>
                                    )}
                                    {rows.map((r, i) => {
                                      const pct = totalW > 0 ? Math.round((r.weight / totalW) * 100) : 0;
                                      return (
                                        <div key={i} className="flex items-center gap-1.5 mb-1.5" data-testid={`offer-row-${i}`}>
                                          <span className="text-[10px] text-[#52525B] w-4 text-right">{i + 1}.</span>
                                          <Input
                                            value={r.url}
                                            onChange={(e) => updateRow(i, { url: e.target.value })}
                                            placeholder="https://offer.com/landing-a"
                                            className="flex-1 font-mono text-[11px] h-8"
                                            data-testid={`offer-url-${i}`}
                                          />
                                          <input
                                            type="number"
                                            min={1}
                                            max={100}
                                            value={r.weight}
                                            onChange={(e) => updateRow(i, { weight: parseInt(e.target.value) || 1 })}
                                            className="w-14 h-8 px-2 text-xs rounded bg-[var(--brand-card)] border border-[var(--brand-border)] text-white"
                                            data-testid={`offer-weight-${i}`}
                                          />
                                          <span className="w-10 text-[10px] text-[#F59E0B] font-mono text-right">{pct}%</span>
                                          <button
                                            type="button"
                                            onClick={() => removeRow(i)}
                                            className="p-1 text-[#EF4444] hover:bg-[#EF444415] rounded"
                                            title="Remove URL"
                                            data-testid={`offer-remove-${i}`}
                                          >
                                            <X size={14} />
                                          </button>
                                        </div>
                                      );
                                    })}
                                    <button
                                      type="button"
                                      onClick={addRow}
                                      className="mt-1 w-full py-1.5 text-[11px] text-[#F59E0B] border border-dashed border-[#F59E0B60] rounded hover:bg-[#F59E0B08] flex items-center justify-center gap-1"
                                      data-testid="offer-add-row"
                                    >
                                      <Plus size={12} /> Add landing page
                                    </button>
                                  </>
                                );
                              })()}
                            </div>
                            <p className="text-[10px] text-[#52525B] mt-1">
                              Weighted A/B/C landing page test. Higher weight = more traffic. Krexion auto-rotates on each click.
                            </p>
                          </div>

                          {/* Feature 2 — Sub-ID / ClickID passthrough via url_params (macro info card) */}
                          <div className="mt-3 p-3 rounded border border-[#3B82F6] bg-[#3B82F615]">
                            <div className="text-xs font-medium text-[#3B82F6] mb-1">
                              💡 Feature 2 — Custom URL Params with Macros
                            </div>
                            <p className="text-[11px] text-[#A1A1AA] mb-2">
                              Add these directly to your <strong>Offer URL</strong> above, OR to the URL Params field.
                              Each per-click value is auto-substituted:
                            </p>
                            <div className="grid grid-cols-2 gap-1 text-[10px] font-mono text-[#A1A1AA]">
                              <div><code className="text-[#3B82F6]">{"{click_id}"}</code> — unique per click</div>
                              <div><code className="text-[#3B82F6]">{"{source}"}</code> — picked platform</div>
                              <div><code className="text-[#3B82F6]">{"{campaign}"}</code> — utm_campaign</div>
                              <div><code className="text-[#3B82F6]">{"{country}"}</code> — geo</div>
                              <div><code className="text-[#3B82F6]">{"{utm_source}"}</code></div>
                              <div><code className="text-[#3B82F6]">{"{utm_medium}"}</code></div>
                              <div><code className="text-[#3B82F6]">{"{ip}"}</code>, <code className="text-[#3B82F6]">{"{ua}"}</code></div>
                              <div><code className="text-[#3B82F6]">{"{timestamp}"}</code>, <code className="text-[#3B82F6]">{"{random16}"}</code></div>
                            </div>
                            <p className="text-[10px] text-[#52525B] mt-2">
                              Example: <code className="text-[#A1A1AA]">https://offer.com/click?sub1={"{click_id}"}&s1={"{source}"}&aff_sub={"{campaign}"}</code>
                            </p>
                          </div>

                          {/* Feature 8 — Postback / S2S URL with template picker */}
                          <div className="mt-3">
                            <Label className="text-xs text-[#A1A1AA]">📤 Outbound S2S Postback URL (Feature 8)</Label>
                            <select
                              onChange={(e) => {
                                const tpl = POSTBACK_TEMPLATES.find(t => t.key === e.target.value);
                                if (tpl && tpl.url) {
                                  setFormData({ ...formData, postback_url: tpl.url });
                                  toast.success(`${tpl.label} template loaded — edit the tracker host + save`);
                                } else if (tpl && tpl.key === "custom") {
                                  setFormData({ ...formData, postback_url: "" });
                                }
                              }}
                              value="custom"
                              className="w-full p-2 rounded-md bg-[var(--brand-card)] border border-[var(--brand-border)] text-white mt-1 text-xs"
                              data-testid="pro-postback-template"
                            >
                              <option value="custom">— Pick a tracker template… —</option>
                              {POSTBACK_TEMPLATES.filter(t => t.key !== "custom").map(t => (
                                <option key={t.key} value={t.key}>{t.label}</option>
                              ))}
                            </select>
                            <Input
                              value={formData.postback_url}
                              onChange={(e) => setFormData({ ...formData, postback_url: e.target.value })}
                              placeholder={"https://YOUR-TRACKER.com/pb?cid={click_id}&payout={payout}"}
                              className="mt-1 font-mono text-xs"
                              data-testid="pro-postback-url"
                            />
                            <p className="text-[10px] text-[#52525B] mt-1">
                              When a conversion hits Krexion&apos;s /postback endpoint, we forward it to this URL (Voluum / Everflow / HasOffers / Cake). Macros: <code>{"{click_id}"}, {"{payout}"}, {"{status}"}, {"{source}"}</code>.
                            </p>
                          </div>

                          {/* Feature 10 — Auto-Pause on Rejection Spike */}
                          <div className="mt-3 grid grid-cols-3 gap-2 items-start">
                            <label className="col-span-2 flex items-start gap-2 cursor-pointer p-2 rounded border border-[var(--brand-border)]">
                              <input
                                type="checkbox"
                                checked={formData.referrer_pro_auto_pause_enabled}
                                onChange={(e) => setFormData({ ...formData, referrer_pro_auto_pause_enabled: e.target.checked })}
                                className="w-4 h-4 mt-0.5"
                                data-testid="pro-auto-pause"
                              />
                              <div>
                                <div className="text-xs font-medium">🛑 Auto-Pause on Rejection Spike (Feature 10)</div>
                                <p className="text-[10px] text-[#52525B] mt-0.5">
                                  Pauses this link automatically after N consecutive non-converting clicks. Saves proxy quota when an offer gets IP-banned / budget-capped. Resets on any conversion.
                                </p>
                              </div>
                            </label>
                            <div>
                              <Label className="text-[10px] text-[#A1A1AA]">Threshold</Label>
                              <Input
                                type="number"
                                min={1}
                                max={10000}
                                value={formData.referrer_pro_auto_pause_threshold}
                                onChange={(e) => setFormData({ ...formData, referrer_pro_auto_pause_threshold: parseInt(e.target.value) || 10 })}
                                className="mt-1 text-sm"
                                disabled={!formData.referrer_pro_auto_pause_enabled}
                                data-testid="pro-auto-pause-threshold"
                              />
                            </div>
                          </div>
                        </div>

                        {/* Preview button */}
                        <div className="flex flex-wrap items-center gap-2 pt-2">
                          <Button
                            type="button"
                            variant="outline"
                            onClick={runReferrerPreview}
                            disabled={previewLoading}
                            className="gap-2"
                            data-testid="preview-referrer-btn"
                          >
                            <Eye size={16} />
                            {previewLoading ? "Generating…" : "Preview 20 Sample Clicks"}
                          </Button>
                          {editingLink && (
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => runQaCheck(editingLink.id)}
                              disabled={qaLoading}
                              className="gap-2 border-[#22C55E] text-[#22C55E] hover:bg-[#22C55E15]"
                              data-testid="qa-check-btn"
                            >
                              <Shield size={16} />
                              {qaLoading ? "Checking…" : "QA Report Card"}
                            </Button>
                          )}
                          <span className="text-xs text-[#52525B]">See exactly what traffic mix your link will produce</span>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>


              <Button type="submit" data-testid="submit-link-button" className="w-full">
                {editingLink ? "Update Link" : "Create Link"}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardHeader>
          <CardTitle>All Links</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                  <TableHead>Name / Short Code</TableHead>
                  <TableHead>Offer URL</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Restrictions</TableHead>
                  <TableHead className="text-right">Clicks</TableHead>
                  <TableHead className="text-right">Conversions</TableHead>
                  <TableHead className="text-right">Revenue</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {links.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                      No links created yet. Click "Create Link" to get started.
                    </TableCell>
                  </TableRow>
                ) : (
                  links.map((link) => (
                    <TableRow key={link.id} className="border-[var(--brand-border)]" data-testid={`link-row-${link.id}`}>
                      <TableCell className="font-mono">
                        <div>
                          {link.name && <div className="font-semibold text-white mb-1">{link.name}</div>}
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span>{link.short_code}</span>
                            <button
                              onClick={() => copyTrackingLink(link.short_code)}
                              className="text-muted-foreground hover:text-white"
                              data-testid={`copy-link-${link.id}`}
                            >
                              <Copy size={14} />
                            </button>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-xs truncate" title={link.offer_url}>
                        {link.offer_url}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={link.status === "active" ? "default" : "secondary"}
                          className={
                            link.status === "active"
                              ? "bg-[#22C55E]"
                              : link.status === "paused"
                              ? "bg-[#EF4444]"
                              : "bg-[#F59E0B]"
                          }
                        >
                          {link.status === "paused" && link.auto_paused_at ? "auto-paused" : link.status}
                        </Badge>
                        {/* v2.1.83 — auto-pause telemetry chip */}
                        {link.referrer_pro_auto_pause_enabled && link.status === "active" && (link.consecutive_no_conversions || 0) > 0 && (
                          <div className="mt-1 text-[10px] text-[#F59E0B]" title={`${link.consecutive_no_conversions} clicks since last conversion (pause at ${link.referrer_pro_auto_pause_threshold || 10})`}>
                            streak {link.consecutive_no_conversions}/{link.referrer_pro_auto_pause_threshold || 10}
                          </div>
                        )}
                        {/* v2.2.0 (Tier 4) — Believability Score badge */}
                        {believability[link.id] && link.status === "active" && (
                          <div
                            className="mt-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold cursor-help"
                            style={{
                              backgroundColor: believability[link.id].color === "green" ? "rgba(34,197,94,0.15)"
                                : believability[link.id].color === "lime" ? "rgba(132,204,22,0.15)"
                                : believability[link.id].color === "yellow" ? "rgba(234,179,8,0.15)"
                                : believability[link.id].color === "orange" ? "rgba(249,115,22,0.15)"
                                : "rgba(239,68,68,0.15)",
                              color: believability[link.id].color === "green" ? "#22C55E"
                                : believability[link.id].color === "lime" ? "#84CC16"
                                : believability[link.id].color === "yellow" ? "#EAB308"
                                : believability[link.id].color === "orange" ? "#F97316"
                                : "#EF4444",
                            }}
                            title={`Believability ${believability[link.id].score}% (Grade ${believability[link.id].grade}). ${(believability[link.id].fixes || []).length} suggestion(s) available.`}
                            data-testid={`believability-badge-${link.id}`}
                          >
                            <Sparkles size={10} />
                            {believability[link.id].score}% {believability[link.id].grade}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          {link.forced_source && (
                            <Badge variant="outline" className="text-xs border-[#22C55E] text-[#22C55E]">
                              <TrendingUp size={10} className="mr-1" /> {link.forced_source_name || link.forced_source}
                            </Badge>
                          )}
                          {link.simulate_platform && (
                            <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">
                              <ExternalLink size={10} className="mr-1" /> Simulates {link.simulate_platform}
                            </Badge>
                          )}
                          {link.referrer_mode === "no_referrer" && (
                            <Badge variant="outline" className="text-xs border-[#F59E0B] text-[#F59E0B]">
                              No Referrer
                            </Badge>
                          )}
                          {link.block_vpn && (
                            <Badge variant="outline" className="text-xs border-[#EF4444] text-[#EF4444]">
                              <Shield size={10} className="mr-1" /> No VPN
                            </Badge>
                          )}
                          {link.allowed_countries && link.allowed_countries.length > 0 && (
                            <Badge variant="outline" className="text-xs border-[#3B82F6] text-[#3B82F6]">
                              <Globe size={10} className="mr-1" /> {link.allowed_countries.length} countries
                            </Badge>
                          )}
                          {link.allowed_os && link.allowed_os.length > 0 && (
                            <Badge variant="outline" className="text-xs border-[#8B5CF6] text-[#8B5CF6]">
                              <Smartphone size={10} className="mr-1" /> {link.allowed_os.join(", ")}
                            </Badge>
                          )}
                          {!link.block_vpn && !link.forced_source && !link.simulate_platform && link.referrer_mode !== "no_referrer" && (!link.allowed_countries || link.allowed_countries.length === 0) && (!link.allowed_os || link.allowed_os.length === 0) && (
                            <span className="text-xs text-muted-foreground">No restrictions</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono">{link.clicks}</TableCell>
                      <TableCell className="text-right font-mono">{link.conversions}</TableCell>
                      <TableCell className="text-right font-mono">${link.revenue.toFixed(2)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => openEditDialog(link)}
                            data-testid={`edit-link-${link.id}`}
                          >
                            <Pencil size={16} />
                          </Button>
                          {/* v2.1.83 Feature 9 — QA report card shortcut */}
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => runQaCheck(link.id)}
                            title="Run Pro-Referrer QA report card"
                            data-testid={`qa-link-${link.id}`}
                            className="text-[#22C55E] hover:text-[#16A34A]"
                          >
                            <Shield size={16} />
                          </Button>
                          {/* v2.2.0 (Tier 7) — Apply Perfect Config preset */}
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setPresetPickerFor(link.id)}
                            title="Apply Perfect Config preset (Facebook / TikTok / Google / LinkedIn / MaxBounty)"
                            data-testid={`preset-link-${link.id}`}
                            className="text-[#8B5CF6] hover:text-[#7C3AED]"
                          >
                            <Sparkles size={16} />
                          </Button>
                          {/* v2.1.83 Feature 10 — Resume auto-paused link */}
                          {link.status === "paused" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => resumeLink(link.id)}
                              title="Resume auto-paused link"
                              data-testid={`resume-link-${link.id}`}
                              className="text-[#F59E0B] hover:text-[#D97706]"
                            >
                              <TrendingUp size={16} />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(link.id)}
                            data-testid={`delete-link-${link.id}`}
                            className="text-red-400 hover:text-red-300"
                          >
                            <Trash2 size={16} />
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

      {links.length > 0 && (
        <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp size={20} />
              Tracking URL Format
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-sm text-muted-foreground mb-2">Basic tracking link:</p>
              <code className="block bg-[var(--brand-card)] p-3 rounded-md text-sm font-mono">
                {PUBLIC_HOST}/api/t/&#123;shortcode&#125;
              </code>
            </div>
            <div>
              <p className="text-sm text-muted-foreground mb-2">With tracking parameters:</p>
              <code className="block bg-[var(--brand-card)] p-3 rounded-md text-sm font-mono">
                {PUBLIC_HOST}/api/t/&#123;shortcode&#125;?sub1=&#123;clickid&#125;&amp;sub2=&#123;source&#125;&amp;sub3=&#123;campaign&#125;
              </code>
            </div>
            <div>
              <p className="text-sm text-muted-foreground mb-2">Postback URL (for conversions):</p>
              <code className="block bg-[var(--brand-card)] p-3 rounded-md text-sm font-mono">
                {PUBLIC_HOST}/api/postback?clickid=&#123;clickid&#125;&amp;payout=&#123;amount&#125;&amp;status=approved&amp;token=YOUR_TOKEN
              </code>
            </div>
          </CardContent>
        </Card>
      )}

      {/* v2.1.80 — Pro-Referrer Preview Modal (20 sample clicks) */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto bg-[var(--brand-bg)] border-[var(--brand-border)]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Eye size={18} className="text-[#F59E0B]" />
              Pro-Referrer Preview — {previewData?.sample_count || 0} sample clicks
            </DialogTitle>
            <DialogDescription>
              What each click on this link will look like to the offer network, based on your current settings.
            </DialogDescription>
          </DialogHeader>

          {previewLoading && (
            <div className="py-8 text-center text-muted-foreground text-sm">Generating samples…</div>
          )}

          {previewData && !previewLoading && (
            <div className="space-y-4">
              {/* Distribution bar */}
              <div className="p-3 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <p className="text-xs font-medium text-[#A1A1AA] mb-2">Platform distribution</p>
                <div className="space-y-1">
                  {(previewData.distribution || []).map((d) => (
                    <div key={d.platform} className="flex items-center gap-2 text-xs">
                      <span className="w-24 truncate font-medium">{d.platform}</span>
                      <div className="flex-1 h-4 bg-[var(--brand-bg)] rounded overflow-hidden relative">
                        <div
                          className="h-full bg-[#F59E0B] transition-all"
                          style={{ width: `${d.pct}%` }}
                        />
                      </div>
                      <span className="w-16 text-right text-[#A1A1AA]">{d.count} ({d.pct}%)</span>
                    </div>
                  ))}
                </div>
              </div>

              {previewData.wrapper_redirect && (
                <div className="p-2 bg-[#F59E0B15] border border-[#F59E0B] rounded text-xs text-[#F59E0B]">
                  Wrapper redirect is ON — every click will bounce through the referer URL below so the offer sees a real platform domain.
                </div>
              )}

              {/* Sample list */}
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                      <TableHead className="w-8">#</TableHead>
                      <TableHead>UA</TableHead>
                      <TableHead>Platform</TableHead>
                      <TableHead>Referer</TableHead>
                      <TableHead>UTM Source</TableHead>
                      <TableHead>UTM Medium</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(previewData.samples || []).map((s) => (
                      <TableRow key={s.index} className="border-[var(--brand-border)] text-xs">
                        <TableCell className="font-mono text-[#52525B]">{s.index}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-[10px]">
                            {s.ua_type === "mobile" ? <Smartphone size={10} className="inline mr-1" /> : <Monitor size={10} className="inline mr-1" />}
                            {s.ua_type}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium">{s.platform || <span className="text-[#52525B]">—</span>}</TableCell>
                        <TableCell className="font-mono text-[10px] max-w-[280px] truncate" title={s.referer}>
                          {s.referer || <span className="text-[#52525B]">(direct)</span>}
                        </TableCell>
                        <TableCell className="text-[10px]">{s.utm_source || "—"}</TableCell>
                        <TableCell className="text-[10px]">{s.utm_medium || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* v2.1.83 — QA Report Card modal (Feature 9) */}
      <Dialog open={qaOpen} onOpenChange={setQaOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto bg-[var(--brand-bg)] border-[var(--brand-border)]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Shield size={18} className="text-[#22C55E]" />
              QA Report Card — 10-check international fraud-detector audit
            </DialogTitle>
            <DialogDescription>
              Grades your link against MaxBounty / ClickDealer / Everflow / Cake / Voluum acceptance criteria.
            </DialogDescription>
          </DialogHeader>

          {qaLoading && (
            <div className="py-8 text-center text-muted-foreground text-sm">Running 10 checks + 5 sample visits…</div>
          )}

          {qaData && !qaLoading && (
            <div className="space-y-4">
              {/* Score summary */}
              <div className="flex items-center gap-4 p-3 bg-[var(--brand-card)] rounded-lg border border-[var(--brand-border)]">
                <div className="flex-1">
                  <p className="text-xs text-[#A1A1AA]">Overall Score</p>
                  <p className={`text-3xl font-bold ${qaData.score >= 80 ? "text-[#22C55E]" : qaData.score >= 50 ? "text-[#F59E0B]" : "text-[#EF4444]"}`}>
                    {qaData.score}%
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-[#A1A1AA]">Passes / Warnings</p>
                  <p className="text-sm">
                    <span className="text-[#22C55E] font-bold">{qaData.passes}</span>
                    {" / "}
                    <span className="text-[#F59E0B] font-bold">{qaData.warnings}</span>
                    {" out of "}
                    <span className="font-bold">{qaData.total_checks}</span>
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-[#A1A1AA]">No-conv streak</p>
                  <p className="text-sm font-bold">{qaData.consecutive_no_conversions}</p>
                  {qaData.auto_paused_at && (
                    <p className="text-[10px] text-[#EF4444]">⏸ auto-paused</p>
                  )}
                </div>
              </div>

              {/* Checks list */}
              <div className="space-y-1.5">
                {qaData.checks.map((c) => (
                  <div
                    key={c.id}
                    className={`flex items-start gap-2 p-2 rounded border ${
                      c.status === "pass"
                        ? "border-[#22C55E30] bg-[#22C55E08]"
                        : c.status === "warn"
                        ? "border-[#F59E0B30] bg-[#F59E0B08]"
                        : "border-[var(--brand-border)] bg-[var(--brand-card)]"
                    }`}
                  >
                    <div className="text-lg leading-none mt-0.5">
                      {c.status === "pass" ? "✅" : c.status === "warn" ? "⚠️" : "ℹ️"}
                    </div>
                    <div className="flex-1">
                      <div className="text-xs font-medium">{c.label}</div>
                      <div className="text-[11px] text-[#A1A1AA] mt-0.5 font-mono">{c.detail}</div>
                    </div>
                  </div>
                ))}
              </div>

              {qaData.samples?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-[#A1A1AA] mb-2">5 sample visits</p>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                          <TableHead className="text-[10px]">UA</TableHead>
                          <TableHead className="text-[10px]">Platform</TableHead>
                          <TableHead className="text-[10px]">Accept-Lang</TableHead>
                          <TableHead className="text-[10px]">utm_medium</TableHead>
                          <TableHead className="text-[10px]">utm_content</TableHead>
                          <TableHead className="text-[10px]">Device fit</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {qaData.samples.map((s) => (
                          <TableRow key={s.index} className="border-[var(--brand-border)] text-[11px]">
                            <TableCell>{s.ua_type === "mobile" ? <Smartphone size={12} className="inline" /> : <Monitor size={12} className="inline" />}</TableCell>
                            <TableCell className="font-medium">{s.platform || "—"}</TableCell>
                            <TableCell className="font-mono text-[10px]">{s.accept_language || "—"}</TableCell>
                            <TableCell>{s.utm_medium || "—"}</TableCell>
                            <TableCell>{s.utm_content || "—"}</TableCell>
                            <TableCell className="text-[10px]">{s.device_expected || "any"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}

              {qaData.last_postback_fired_at && (
                <div className="p-2 bg-[var(--brand-card)] rounded border border-[var(--brand-border)] text-[11px]">
                  <p className="text-[#A1A1AA]">
                    Last outbound postback: <span className="font-mono">{qaData.last_postback_fired_at}</span>
                    {" · status "}
                    <span className={qaData.last_postback_status_code >= 200 && qaData.last_postback_status_code < 300 ? "text-[#22C55E]" : "text-[#EF4444]"}>
                      {qaData.last_postback_status_code}
                    </span>
                  </p>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* v2.2.0 (Tier 7) — Perfect Config Preset Picker Dialog */}
      <Dialog open={!!presetPickerFor} onOpenChange={(open) => !open && setPresetPickerFor(null)}>
        <DialogContent className="max-w-2xl bg-[var(--brand-bg)] border-[var(--brand-border)]" data-testid="preset-picker-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles size={18} className="text-[#8B5CF6]" />
              Apply Perfect Config Preset
            </DialogTitle>
            <DialogDescription>
              One-click best-practice configuration. Overwrites Pro-Referrer settings on this link only.
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
            {[
              { key: "facebook_ads",      label: "Facebook Ads",       emoji: "📘", tint: "border-[#1877F2] hover:bg-[#1877F2]/10", desc: "Mobile-first, in-app deep paths, video ad UTMs" },
              { key: "tiktok_ads",        label: "TikTok Ads",         emoji: "🎵", tint: "border-[#FE2C55] hover:bg-[#FE2C55]/10", desc: "Mobile-only, silent redirect (bypass warnings)" },
              { key: "google_ads",        label: "Google Ads",         emoji: "🔍", tint: "border-[#34A853] hover:bg-[#34A853]/10", desc: "Search + YouTube split, google.com/url wrapper" },
              { key: "linkedin_ads",      label: "LinkedIn Ads",       emoji: "💼", tint: "border-[#0A66C2] hover:bg-[#0A66C2]/10", desc: "Desktop-first, business hours, sponsored UTMs" },
              { key: "maxbounty_premium", label: "MaxBounty Premium",  emoji: "⭐", tint: "border-[#FFD700] hover:bg-[#FFD700]/10", desc: "Multi-platform mix, wrapper ON, auto-pause 15" },
              { key: "gambling_aggressive", label: "Gambling / Adult / Crypto", emoji: "🎰", tint: "border-[#EF4444] hover:bg-[#EF4444]/10", desc: "Aggressive rotation, wrapper OFF, auto-pause 8" },
            ].map((p) => (
              <button
                key={p.key}
                onClick={() => applyPreset(presetPickerFor, p.key)}
                className={`text-left p-3 rounded-lg border ${p.tint} bg-[var(--brand-card)] transition-colors`}
                data-testid={`preset-${p.key}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{p.emoji}</span>
                  <span className="font-semibold text-sm text-white">{p.label}</span>
                </div>
                <p className="text-xs text-[#A1A1AA]">{p.desc}</p>
              </button>
            ))}
          </div>
          <p className="text-[10px] text-[#71717A] pt-2">
            💡 Presets are curated for v2.2.0 cold-click safety. All warning-trigger wrappers auto-bypass on external clicks.
          </p>
        </DialogContent>
      </Dialog>

    </div>
  );
}
