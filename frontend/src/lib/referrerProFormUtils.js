/** Shared helpers — Links form ↔ RUT-style referrer config object. */

export const REFERRER_MODE_OPTIONS = [
  { value: "platform_pool", label: "Random Platform Pool (Pro Mode)" },
  { value: "auto", label: "Auto from UA (smart in-app detection)" },
  { value: "custom", label: "Custom URL (same for every click)" },
  { value: "random_list", label: "Random from URL List" },
  { value: "google_search", label: "Google Search (organic SEO look)" },
  { value: "direct", label: "Direct / None (no Referer)" },
];

export const parsePlatformPool = (str) => {
  if (!str || typeof str !== "string") return [];
  return str.split(",").map((part) => {
    const [key, weight] = part.trim().split(":");
    if (!key) return null;
    return { key: key.trim(), weight: parseFloat(weight) || 10 };
  }).filter(Boolean);
};

export const stringifyPlatformPool = (arr) => {
  if (!Array.isArray(arr)) return "";
  return arr.filter((x) => x.key && x.weight > 0).map((x) => `${x.key}:${x.weight}`).join(",");
};

export const parseEmailWeights = (str) => {
  if (!str) return {};
  try {
    const parsed = JSON.parse(str);
    if (parsed && typeof parsed === "object") return parsed;
  } catch (_) { /* legacy */ }
  return {};
};

export const stringifyEmailWeights = (obj) => {
  if (!obj || typeof obj !== "object") return "";
  return JSON.stringify(obj);
};

export const LANDING_HOP_MACRO = "{offer_url}";

/** Default operator landing — offer URL injected by Krexion at click time. */
export const LANDING_HOP_TEMPLATE = "https://www.yoursite.com/go?next={offer_url}";

export const CUSTOM_UTM_FIELDS = [
  { key: "custom_utm_source", label: "utm_source", placeholder: "facebook, google, mybrand_newsletter" },
  { key: "custom_utm_medium", label: "utm_medium", placeholder: "paid_social, cpc, email" },
  { key: "custom_utm_campaign", label: "utm_campaign", placeholder: "spring_sale_2026 or {campaign}" },
  { key: "custom_utm_content", label: "utm_content", placeholder: "video_a, carousel_v2" },
  { key: "custom_utm_term", label: "utm_term", placeholder: "keyword or audience tag" },
];

export function hasLandingHopMacro(url) {
  return String(url || "").includes(LANDING_HOP_MACRO);
}

export function applyLandingHopFromCustomUrl(value, prev = {}) {
  const v = String(value || "").trim();
  if (!hasLandingHopMacro(v)) return {};
  return {
    mode: "custom",
    value: v,
    pass_to_offer: true,
  };
}

export function inferRefererModeFromLink(form) {
  const explicit = (form?.referrer_pro_referer_mode || "").trim();
  if (explicit) return explicit;
  const custom = (form?.referrer_pro_custom_referer || "").trim();
  if (hasLandingHopMacro(custom)) return "custom";
  if (!custom) return "platform_pool";
  const lines = custom.split("\n").map((s) => s.trim()).filter(Boolean);
  if (lines.length > 1) return "random_list";
  if (lines.length === 1 && lines[0].startsWith("http")) return "custom";
  if (lines.length === 1) return "google_search";
  return "platform_pool";
}

export function linkToReferrerConfig(form) {
  const pool = parsePlatformPool(form.referrer_pro_platform_pool || "");
  const platform_weights = Object.fromEntries(pool.map((p) => [p.key, p.weight]));
  const mode = inferRefererModeFromLink(form);
  let value = form.referrer_pro_custom_referer || "";
  if (mode === "google_search" && !value.trim()) {
    value = form.referrer_pro_search_keywords || "";
  }
  return {
    mode,
    pro_mode: form.referrer_pro_pro_mode !== false,
    value,
    preset_platform: form.referrer_pro_inapp_preset || "",
    platform_weights,
    email_weights: parseEmailWeights(form.referrer_pro_email_weights || ""),
    brand: form.referrer_pro_brand || "",
    country: form.referrer_pro_country || "",
    search_engine: form.referrer_pro_search_engine || "google",
    search_keywords: form.referrer_pro_search_keywords || "",
    social_wrapper: form.referrer_pro_social_wrapper !== false,
    inapp_deep_path: form.referrer_pro_inapp_deep_path !== false,
    strip_search_path: form.referrer_pro_strip_search_path !== false,
    wrapper_redirect: !!form.referrer_pro_wrapper_redirect,
    lang_match: form.referrer_pro_lang_match !== false,
    device_mode: form.referrer_pro_device_mode || "auto",
    tod_enabled: !!form.referrer_pro_tod_enabled,
    campaign_type: form.referrer_pro_campaign_type || "auto",
    traffic_type: form.referrer_pro_traffic_type || "auto",
    pass_to_offer: !!form.referrer_pro_pass_to_offer,
    allow_risky_wrapper: !!form.referrer_pro_allow_risky_wrapper,
    match_ua_to_platform: form.referrer_pro_match_ua_to_platform !== false,
    cold_referer_fallback: form.referrer_pro_cold_referer_fallback !== false,
    html_hop: form.referrer_pro_html_hop !== false,
    custom_utm_enabled: !!form.referrer_pro_custom_utm_enabled,
    custom_utm_source: form.referrer_pro_custom_utm_source || "",
    custom_utm_medium: form.referrer_pro_custom_utm_medium || "",
    custom_utm_campaign: form.referrer_pro_custom_utm_campaign || "",
    custom_utm_content: form.referrer_pro_custom_utm_content || "",
    custom_utm_term: form.referrer_pro_custom_utm_term || "",
  };
}

export function patchLinkFromReferrerConfig(cfg) {
  const mode = cfg.mode || "platform_pool";
  let customReferer = cfg.value || "";
  let searchKeywords = cfg.search_keywords || "";
  if (mode === "google_search") {
    searchKeywords = customReferer;
  }
  const landingHop = hasLandingHopMacro(customReferer);
  return {
    referrer_pro_referer_mode: landingHop ? "custom" : mode,
    referrer_pro_pro_mode: cfg.pro_mode !== false,
    referrer_pro_custom_referer: customReferer,
    referrer_pro_inapp_preset: cfg.preset_platform || "",
    referrer_pro_platform_pool: stringifyPlatformPool(
      Object.entries(cfg.platform_weights || {}).map(([key, weight]) => ({ key, weight }))
    ),
    referrer_pro_email_weights: stringifyEmailWeights(cfg.email_weights || {}),
    referrer_pro_brand: cfg.brand || "",
    referrer_pro_country: cfg.country || "",
    referrer_pro_search_engine: cfg.search_engine || "google",
    referrer_pro_search_keywords: searchKeywords,
    referrer_pro_social_wrapper: cfg.social_wrapper !== false,
    referrer_pro_inapp_deep_path: cfg.inapp_deep_path !== false,
    referrer_pro_strip_search_path: cfg.strip_search_path !== false,
    referrer_pro_wrapper_redirect: !!cfg.wrapper_redirect,
    referrer_pro_lang_match: cfg.lang_match !== false,
    referrer_pro_device_mode: cfg.device_mode || "auto",
    referrer_pro_tod_enabled: !!cfg.tod_enabled,
    referrer_pro_campaign_type: cfg.campaign_type || "auto",
    referrer_pro_traffic_type: cfg.traffic_type || "auto",
    referrer_pro_pass_to_offer: landingHop || !!cfg.pass_to_offer,
    referrer_pro_allow_risky_wrapper: !!cfg.allow_risky_wrapper,
    referrer_pro_match_ua_to_platform: cfg.match_ua_to_platform !== false,
    referrer_pro_cold_referer_fallback: cfg.cold_referer_fallback !== false,
    referrer_pro_html_hop: cfg.html_hop !== false,
    referrer_pro_custom_utm_enabled: !!cfg.custom_utm_enabled,
    referrer_pro_custom_utm_source: cfg.custom_utm_source || "",
    referrer_pro_custom_utm_medium: cfg.custom_utm_medium || "",
    referrer_pro_custom_utm_campaign: cfg.custom_utm_campaign || "",
    referrer_pro_custom_utm_content: cfg.custom_utm_content || "",
    referrer_pro_custom_utm_term: cfg.custom_utm_term || "",
  };
}
