/**
 * Shared traffic-source presets — RUT jobs + Links use the same weights
 * and realism toggles so customers get one mental model everywhere.
 */

export const TRAFFIC_SOURCE_PRESET_OPTIONS = [
  { value: "mixed_realistic", label: "Mixed Realistic (Recommended)" },
  { value: "social_media_ads", label: "Social Media Ads" },
  { value: "search_engine_ads", label: "Search Engine Ads" },
  { value: "email_campaign", label: "Email Campaign" },
  { value: "direct_traffic", label: "Direct Traffic (no Referer)" },
  { value: "custom", label: "Custom (Advanced)" },
];

/** Human-readable summary bullets per preset (Links + RUT). */
export const TRAFFIC_SOURCE_PRESET_SUMMARY = {
  mixed_realistic: [
    "Traffic mix: 30% Facebook · 20% TikTok · 20% Google · 15% Instagram · 10% Email · 5% Twitter",
    "Realism: in-app deep paths + social link wrappers",
    "Compliance: country language match + device/platform alignment",
  ],
  social_media_ads: [
    "Traffic mix: 40% Facebook · 30% Instagram · 25% TikTok · 5% Twitter (paid social)",
    "Realism: deep post/reel paths + l.facebook.com / t.co wrappers",
    "Mobile in-app markers aligned per platform",
  ],
  search_engine_ads: [
    "Search mix: 65% Google · 25% Bing · 5% DuckDuckGo · 5% Yandex",
    "Geo-localized search TLDs when country is set",
    "Referrer-Policy strip: origin-only (modern Chrome behaviour)",
  ],
  email_campaign: [
    "ESP mix: Gmail · Outlook · Mailchimp · Klaviyo · Yahoo",
    "Auto ESP click IDs (mc_cid, _kx, _hsenc) per visit",
    "UTM medium=email applied automatically",
  ],
  direct_traffic: [
    "Referer: none — offer sees direct / bookmark traffic",
    "Use for SMS, native mail, typed URLs",
    "Classic no-referrer mode (Pro engine off)",
  ],
};

/** { facebook: 30, ... } → "facebook:30,instagram:15" */
export function weightsToPlatformPool(weights) {
  if (!weights || typeof weights !== "object") return "";
  return Object.entries(weights)
    .filter(([, w]) => w > 0)
    .map(([k, w]) => `${k}:${Math.round(Number(w) || 0)}`)
    .join(",");
}

/** { gmail: 40 } → '{"gmail":40}' */
export function weightsToEmailJson(weights) {
  if (!weights || !Object.keys(weights).length) return "";
  return JSON.stringify(weights);
}

/**
 * Map a built-in preset key → partial Links form patch (referrer_pro_* fields).
 * Mirrors RealUserTrafficPage trafficSourcePreset useEffect (RUT parity).
 */
export function buildLinkProPatchFromPreset(presetKey) {
  if (!presetKey || presetKey === "off") {
    return {
      referrer_pro_enabled: false,
    };
  }

  if (presetKey === "direct_traffic") {
    return {
      referrer_pro_enabled: false,
      referrer_mode: "no_referrer",
      forced_source: "",
      forced_source_name: "",
      simulate_platform: "",
    };
  }

  const base = {
    referrer_pro_enabled: true,
    referrer_mode: "normal",
    forced_source: "",
    forced_source_name: "",
    simulate_platform: "",
    referrer_pro_lang_match: true,
    referrer_pro_device_mode: "match_platform",
    referrer_pro_quality_tier: "standard",
    referrer_pro_social_wrapper: true,
    referrer_pro_inapp_deep_path: true,
    referrer_pro_strip_search_path: true,
    referrer_pro_wrapper_redirect: true,
    referrer_pro_tod_enabled: false,
    referrer_pro_campaign_type: "auto",
    referrer_pro_search_engine: "google",
    referrer_pro_email_weights: "",
  };

  if (presetKey === "custom") {
    return base;
  }

  if (presetKey === "mixed_realistic") {
    return {
      ...base,
      referrer_pro_traffic_type: "auto",
      referrer_pro_platform_pool: weightsToPlatformPool({
        facebook: 30,
        instagram: 15,
        tiktok: 20,
        google: 20,
        twitter: 5,
        email: 10,
      }),
    };
  }

  if (presetKey === "social_media_ads") {
    return {
      ...base,
      referrer_pro_traffic_type: "paid",
      referrer_pro_platform_pool: weightsToPlatformPool({
        facebook: 40,
        instagram: 30,
        tiktok: 25,
        twitter: 5,
      }),
    };
  }

  if (presetKey === "search_engine_ads") {
    return {
      ...base,
      referrer_pro_traffic_type: "paid",
      referrer_pro_social_wrapper: false,
      referrer_pro_inapp_deep_path: false,
      referrer_pro_wrapper_redirect: false,
      referrer_pro_platform_pool: weightsToPlatformPool({
        google: 65,
        bing: 25,
        duckduckgo: 5,
        yandex: 5,
      }),
    };
  }

  if (presetKey === "email_campaign") {
    return {
      ...base,
      referrer_pro_traffic_type: "organic",
      referrer_pro_social_wrapper: false,
      referrer_pro_inapp_deep_path: false,
      referrer_pro_wrapper_redirect: false,
      referrer_pro_platform_pool: weightsToPlatformPool({ email: 100 }),
      referrer_pro_email_weights: weightsToEmailJson({
        gmail: 40,
        outlook: 20,
        yahoo: 10,
        mailchimp: 15,
        klaviyo: 10,
        empty: 5,
      }),
    };
  }

  return base;
}

/** Apply a saved My Preset doc (from /api/referrer-pro/my-presets) to Links form. */
export function buildLinkPatchFromSavedPreset(mp) {
  if (!mp || !mp.config) {
    return buildLinkProPatchFromPreset(mp?.base_preset || "custom");
  }
  const cfg = mp.config || {};
  const patch = buildLinkProPatchFromPreset(mp.base_preset || "custom");

  if (cfg.platform_weights && typeof cfg.platform_weights === "object") {
    patch.referrer_pro_platform_pool = weightsToPlatformPool(cfg.platform_weights);
    patch.referrer_pro_enabled = mp.base_preset !== "direct_traffic" && mp.base_preset !== "off";
  }
  if (cfg.email_weights && typeof cfg.email_weights === "object") {
    patch.referrer_pro_email_weights = weightsToEmailJson(cfg.email_weights);
  }
  if (typeof cfg.referer_brand === "string") {
    patch.referrer_pro_brand = cfg.referer_brand;
  }
  if (typeof cfg.traffic_type === "string") {
    patch.referrer_pro_traffic_type = cfg.traffic_type;
  }
  if (typeof cfg.campaign_type === "string") {
    patch.referrer_pro_campaign_type = cfg.campaign_type;
  }
  if (typeof cfg.social_wrapper === "boolean") {
    patch.referrer_pro_social_wrapper = cfg.social_wrapper;
  }
  if (typeof cfg.inapp_deep === "boolean") {
    patch.referrer_pro_inapp_deep_path = cfg.inapp_deep;
  }
  if (typeof cfg.strip_search_path === "boolean") {
    patch.referrer_pro_strip_search_path = cfg.strip_search_path;
  }
  if (typeof cfg.search_engine === "string") {
    patch.referrer_pro_search_engine = cfg.search_engine;
  }
  if (typeof cfg.search_keywords === "string") {
    patch.referrer_pro_search_keywords = cfg.search_keywords;
  }
  return patch;
}
