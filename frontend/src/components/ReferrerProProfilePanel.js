import React, { useEffect, useState } from "react";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";

export const DEFAULT_PROFILE_REFERRER = {
  enabled: false,
  pro_mode: true,
  mode: "auto",
  value: "",
  preset_platform: "",
  platform_weights: { google: 40, facebook: 30, tiktok: 30 },
  email_weights: {},
  social_wrapper: true,
  inapp_deep_path: true,
  strip_search_path: true,
  network_click_chain: false,
  search_engine: "google",
  search_keywords: "",
  brand: "",
  country: "",
  wrapper_redirect: false,
  lang_match: true,
  device_mode: "auto",
  tod_enabled: false,
  campaign_type: "auto",
  quality_tier: "standard",
  traffic_type: "auto",
  match_ua_to_platform: true,
  sticky_session: true,
};

function ReferrerProMultiSelect({ title, description, keys, weights, onChange, accent = "fuchsia", testIdPrefix }) {
  const total = Object.values(weights || {}).reduce((s, w) => s + (parseFloat(w) || 0), 0);
  const accentClasses = {
    fuchsia: { ring: "border-fuchsia-700/40", bg: "bg-fuchsia-950/20", text: "text-fuchsia-300", slider: "accent-fuchsia-500" },
    emerald: { ring: "border-emerald-700/40", bg: "bg-emerald-950/20", text: "text-emerald-300", slider: "accent-emerald-500" },
    cyan: { ring: "border-cyan-700/40", bg: "bg-cyan-950/20", text: "text-cyan-300", slider: "accent-cyan-500" },
  }[accent] || { ring: "border-fuchsia-700/40", bg: "bg-fuchsia-950/20", text: "text-fuchsia-300", slider: "accent-fuchsia-500" };

  const toggle = (k) => {
    const next = { ...(weights || {}) };
    if (next[k] === undefined) {
      const remaining = Math.max(0, 100 - total);
      next[k] = remaining > 0 ? Math.min(remaining, 20) : 10;
    } else {
      delete next[k];
    }
    onChange(next);
  };
  const setWeight = (k, w) => {
    const next = { ...(weights || {}) };
    next[k] = Math.max(0, Math.min(100, parseFloat(w) || 0));
    if (next[k] === 0) delete next[k];
    onChange(next);
  };
  const resetEqual = () => {
    const active = Object.keys(weights || {});
    if (!active.length) return;
    const each = Math.round(100 / active.length);
    const next = {};
    active.forEach((k, i) => {
      next[k] = i === active.length - 1 ? 100 - each * (active.length - 1) : each;
    });
    onChange(next);
  };

  return (
    <div className={`p-3 rounded-md border ${accentClasses.ring} ${accentClasses.bg}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className={`text-sm font-semibold ${accentClasses.text}`}>{title}</div>
          {description && <div className="text-[11px] text-zinc-400 mt-0.5">{description}</div>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400">
            Total: <span className={total >= 90 && total <= 110 ? "text-emerald-300 font-semibold" : "text-amber-400"}>{total.toFixed(0)}%</span>
          </span>
          <button type="button" data-testid={`${testIdPrefix}-reset`} onClick={resetEqual}
            className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 hover:bg-zinc-700">
            Equal
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(keys || []).map((k) => {
          const active = weights && weights[k] !== undefined;
          return (
            <button key={k} type="button" data-testid={`${testIdPrefix}-chip-${k}`} onClick={() => toggle(k)}
              className={`text-[11px] px-2.5 py-1 rounded-full border transition ${
                active ? `${accentClasses.text} border-current bg-zinc-900/80` : "text-zinc-500 border-zinc-700 bg-zinc-900/40 hover:text-zinc-300"
              }`}>
              {k}{active ? ` (${(weights[k] || 0).toFixed(0)}%)` : ""}
            </button>
          );
        })}
      </div>
      {Object.keys(weights || {}).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(weights).map(([k, w]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-24 text-xs text-zinc-300 truncate">{k}</span>
              <input type="range" min={0} max={100} step={1} value={w}
                data-testid={`${testIdPrefix}-slider-${k}`}
                onChange={(e) => setWeight(k, e.target.value)}
                className={`flex-1 ${accentClasses.slider}`} />
              <span className="w-8 text-xs text-zinc-400 text-right">{Number(w).toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Full RUT-grade Referrer Pro panel for Browser Profiles.
 * Binds to profile.referrer object (ReferrerProConfig on backend).
 */
export default function ReferrerProProfilePanel({
  referrer,
  onChange,
  profileCountry = "us",
  testIdPrefix = "bp-referrer",
}) {
  const ref = { ...DEFAULT_PROFILE_REFERRER, ...(referrer || {}) };
  const patch = (updates) => onChange({ ...ref, ...updates });

  const [defaults, setDefaults] = useState({
    platforms: [],
    email_buckets: [],
    countries: ["US"],
    intent_mixes: ["balanced", "informational", "commercial", "branded"],
  });
  const [aiKwOffer, setAiKwOffer] = useState("");
  const [aiKwVertical, setAiKwVertical] = useState("");
  const [aiKwCountry, setAiKwCountry] = useState((profileCountry || "us").toLowerCase());
  const [aiKwIntent, setAiKwIntent] = useState("balanced");
  const [aiKwCount, setAiKwCount] = useState(15);
  const [aiKwLoading, setAiKwLoading] = useState(false);
  const [aiKwError, setAiKwError] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("token");
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/defaults`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setDefaults((prev) => ({ ...prev, ...d })); })
      .catch(() => {});
  }, []);

  const applyQualityTier = (tier) => {
    const updates = { quality_tier: tier };
    if (tier === "premium") {
      updates.wrapper_redirect = true;
      updates.tod_enabled = true;
      if ((ref.device_mode || "auto") === "auto") updates.device_mode = "match_platform";
    } else if (tier === "aggressive") {
      updates.wrapper_redirect = false;
      updates.lang_match = false;
      updates.social_wrapper = false;
      updates.inapp_deep_path = false;
      updates.tod_enabled = false;
      updates.device_mode = "auto";
    } else {
      updates.wrapper_redirect = false;
      updates.lang_match = true;
      updates.social_wrapper = true;
      updates.inapp_deep_path = true;
      updates.tod_enabled = false;
      updates.device_mode = "auto";
    }
    patch(updates);
  };

  const platformKeys = defaults.platforms?.length
    ? defaults.platforms
    : ["facebook", "instagram", "tiktok", "youtube", "twitter", "snapchat", "pinterest", "reddit", "linkedin", "google", "bing", "duckduckgo", "yahoo", "yandex", "email", "whatsapp", "telegram", "discord"];
  const emailKeys = defaults.email_buckets?.length
    ? defaults.email_buckets
    : ["empty", "gmail", "outlook", "yahoo", "proton", "mailchimp", "klaviyo", "sendgrid", "hubspot", "activecampaign", "convertkit", "constantcontact", "mailerlite", "brevo", "aweber", "drip", "iterable", "marketo", "pardot"];

  const hasSearchPlatform = Object.keys(ref.platform_weights || {}).some((k) =>
    ["google", "bing", "yahoo", "duckduckgo", "yandex"].includes(k));

  return (
    <div className="p-3 rounded-lg border border-fuchsia-500/30 bg-fuchsia-950/10 space-y-3" data-testid={`${testIdPrefix}-panel`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="text-fuchsia-300 text-sm font-semibold">🔗 Referrer Pro (RUT-grade)</span>
          <p className="text-[11px] text-zinc-400 mt-0.5">
            Profile launch ke baad har tab / har offer URL par yahi referer jayega — platform mix, wrappers, Sec-Fetch sync.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer shrink-0">
          <input type="checkbox" data-testid={`${testIdPrefix}-enabled`} checked={!!ref.enabled}
            onChange={(e) => patch({ enabled: e.target.checked })}
            className="w-4 h-4 rounded accent-fuchsia-500" />
          Enabled
        </label>
      </div>

      {ref.enabled && (
        <div className="space-y-4 border-t border-fuchsia-500/20 pt-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <Label className="text-zinc-300 text-xs">Referrer Mode</Label>
              <select data-testid={`${testIdPrefix}-mode`} value={ref.mode || "auto"}
                onChange={(e) => patch({ mode: e.target.value })}
                className="mt-1 w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                <option value="auto">Auto from UA</option>
                <option value="platform_pool">Platform pool (legacy)</option>
                <option value="custom">Custom URL (fixed)</option>
                <option value="random_list">Random URL list</option>
                <option value="google_search">Google Search keywords</option>
                <option value="direct">Direct / no referer</option>
              </select>
            </div>
            <div>
              <Label className="text-zinc-300 text-xs">Quality Tier</Label>
              <select data-testid={`${testIdPrefix}-quality-tier`} value={ref.quality_tier || "standard"}
                onChange={(e) => applyQualityTier(e.target.value)}
                className="mt-1 w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                <option value="standard">Standard</option>
                <option value="premium">Premium (wrapper + TOD + device match)</option>
                <option value="aggressive">Aggressive (fast, lenient networks)</option>
              </select>
            </div>
            <div>
              <Label className="text-zinc-300 text-xs">Referrer country override</Label>
              <Input data-testid={`${testIdPrefix}-country`} value={ref.country || ""}
                onChange={(e) => patch({ country: e.target.value.slice(0, 8).toLowerCase() })}
                placeholder={profileCountry || "us"}
                className="mt-1 bg-zinc-900 border-zinc-700 text-zinc-100 text-xs" />
            </div>
          </div>

          <label className="flex items-center justify-between gap-2 p-2 rounded border border-fuchsia-700/40 bg-fuchsia-950/20 cursor-pointer">
            <span className="text-fuchsia-300 text-xs font-semibold">⚡ Pro Mode — weighted platform + ESP mix</span>
            <input type="checkbox" data-testid={`${testIdPrefix}-pro-mode`} checked={ref.pro_mode !== false}
              onChange={(e) => patch({ pro_mode: e.target.checked })}
              className="w-4 h-4 rounded accent-fuchsia-500" />
          </label>

          {ref.pro_mode !== false && (
            <div className="space-y-3">
              <ReferrerProMultiSelect
                title="Platform Mix"
                description="Session start par ek platform pick hota hai — poore launch mein wahi referer har tab par."
                keys={platformKeys}
                weights={ref.platform_weights || {}}
                onChange={(w) => patch({ platform_weights: w })}
                accent="fuchsia"
                testIdPrefix={`${testIdPrefix}-platform`}
              />
              {Object.keys(ref.platform_weights || {}).includes("email") && (ref.platform_weights?.email || 0) > 0 && (
                <ReferrerProMultiSelect
                  title="Email Source Mix"
                  description="ESP / webmail sub-mix jab platform email ho."
                  keys={emailKeys}
                  weights={ref.email_weights || {}}
                  onChange={(w) => patch({ email_weights: w })}
                  accent="emerald"
                  testIdPrefix={`${testIdPrefix}-email`}
                />
              )}
            </div>
          )}

          {ref.mode === "custom" && (
            <div>
              <Label className="text-zinc-300 text-xs">Custom Referrer URL</Label>
              <Input data-testid={`${testIdPrefix}-custom-url`} value={ref.value || ""}
                onChange={(e) => patch({ value: e.target.value.slice(0, 1024) })}
                placeholder="https://www.facebook.com/groups/..."
                className="mt-1 bg-zinc-900 border-zinc-700 text-zinc-100 text-xs" />
            </div>
          )}

          {ref.mode === "random_list" && (
            <div>
              <Label className="text-zinc-300 text-xs">Referrer URL pool (one per line)</Label>
              <Textarea data-testid={`${testIdPrefix}-url-list`} value={ref.value || ""} rows={4}
                onChange={(e) => patch({ value: e.target.value.slice(0, 8000) })}
                className="mt-1 bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs" />
            </div>
          )}

          {ref.mode === "google_search" && (
            <div>
              <Label className="text-zinc-300 text-xs">Search keywords (one per line)</Label>
              <Textarea data-testid={`${testIdPrefix}-google-kw`} value={ref.value || ref.search_keywords || ""} rows={3}
                onChange={(e) => patch({ value: e.target.value.slice(0, 8000), search_keywords: e.target.value.slice(0, 8000) })}
                className="mt-1 bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs" />
            </div>
          )}

          {(hasSearchPlatform || ref.mode === "google_search") && (
            <div className="p-3 rounded-md bg-cyan-950/20 border border-cyan-700/40 space-y-2">
              <Label className="text-cyan-300 text-xs font-semibold">🔎 Search engine settings</Label>
              <div className="grid grid-cols-2 gap-2">
                <select value={ref.search_engine || "google"}
                  onChange={(e) => patch({ search_engine: e.target.value })}
                  className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                  <option value="google">Google</option>
                  <option value="bing">Bing</option>
                  <option value="yahoo">Yahoo</option>
                  <option value="duckduckgo">DuckDuckGo</option>
                  <option value="yandex">Yandex</option>
                </select>
                <label className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                  <input type="checkbox" checked={ref.strip_search_path !== false}
                    onChange={(e) => patch({ strip_search_path: e.target.checked })}
                    className="w-4 h-4 rounded accent-cyan-500" />
                  Strip SERP path
                </label>
              </div>
              <Textarea data-testid={`${testIdPrefix}-search-keywords`} value={ref.search_keywords || ""} rows={3}
                onChange={(e) => patch({ search_keywords: e.target.value.slice(0, 8000) })}
                placeholder={"best vpn 2026\nfree trial software"}
                className="bg-zinc-900 border-zinc-700 text-zinc-100 font-mono text-xs" />
              <div className="p-2 rounded bg-zinc-950/60 border border-zinc-800 space-y-2">
                <div className="text-[10px] text-amber-300 font-semibold">✨ AI Keyword Generator</div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <Input value={aiKwOffer} onChange={(e) => setAiKwOffer(e.target.value.slice(0, 200))}
                    placeholder="Offer name" className="bg-zinc-800 border-zinc-700 text-zinc-100 text-xs h-8" />
                  <Input value={aiKwVertical} onChange={(e) => setAiKwVertical(e.target.value.slice(0, 120))}
                    placeholder="Vertical" className="bg-zinc-800 border-zinc-700 text-zinc-100 text-xs h-8" />
                  <select value={aiKwCountry} onChange={(e) => setAiKwCountry(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-2 text-xs h-8">
                    {(defaults.countries || ["US"]).map((cc) => (
                      <option key={cc} value={cc.toLowerCase()}>{cc}</option>
                    ))}
                  </select>
                  <select value={aiKwIntent} onChange={(e) => setAiKwIntent(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-2 text-xs h-8">
                    {(defaults.intent_mixes || []).map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <button type="button" disabled={aiKwLoading || !aiKwOffer.trim()}
                  onClick={async () => {
                    setAiKwError("");
                    setAiKwLoading(true);
                    try {
                      const token = localStorage.getItem("token");
                      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/referrer-pro/generate-keywords`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                        body: JSON.stringify({
                          offer_name: aiKwOffer.trim(),
                          vertical: aiKwVertical.trim(),
                          country: aiKwCountry,
                          language: "en",
                          count: aiKwCount,
                          intent_mix: aiKwIntent,
                        }),
                      });
                      if (!r.ok) throw new Error(await r.text());
                      const data = await r.json();
                      const newKws = (data.keywords || []).join("\n");
                      patch({ search_keywords: ref.search_keywords ? `${ref.search_keywords}\n${newKws}` : newKws });
                    } catch (err) {
                      setAiKwError(String(err.message || err));
                    } finally {
                      setAiKwLoading(false);
                    }
                  }}
                  className="px-3 py-1 rounded text-xs bg-amber-600/80 hover:bg-amber-600 disabled:opacity-50 text-white">
                  {aiKwLoading ? "Generating…" : "Generate keywords"}
                </button>
                {aiKwError && <span className="text-xs text-red-400">{aiKwError.slice(0, 120)}</span>}
              </div>
            </div>
          )}

          <div className="p-3 rounded-md bg-zinc-900/60 border border-zinc-700/60 space-y-2">
            <div className="text-xs text-fuchsia-300 font-semibold">🎚️ Realism layers</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-zinc-300">
              {[
                ["social_wrapper", "Social link wrappers (l.facebook.com / t.co)"],
                ["inapp_deep_path", "Mobile in-app deep paths"],
                ["wrapper_redirect", "Wrapper redirect hop (Premium networks)"],
                ["lang_match", "Accept-Language ↔ country match"],
                ["tod_enabled", "Time-of-day realism weighting"],
                ["match_ua_to_platform", "Match UA to referer platform"],
                ["sticky_session", "Same referer for whole session (recommended)"],
              ].map(([key, label]) => (
                <label key={key} className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" checked={ref[key] !== false}
                    onChange={(e) => patch({ [key]: e.target.checked })}
                    className="w-4 h-4 rounded accent-fuchsia-500 mt-0.5" />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <Label className="text-zinc-300 text-xs">Traffic type</Label>
              <select value={ref.traffic_type || "auto"}
                onChange={(e) => patch({ traffic_type: e.target.value })}
                className="mt-1 w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                <option value="auto">Auto</option>
                <option value="paid">Paid ads</option>
                <option value="organic">Organic</option>
                <option value="mixed">Mixed 60/40</option>
              </select>
            </div>
            <div>
              <Label className="text-zinc-300 text-xs">Campaign type</Label>
              <select value={ref.campaign_type || "auto"}
                onChange={(e) => patch({ campaign_type: e.target.value })}
                className="mt-1 w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                <option value="auto">Auto rotation</option>
                <option value="static_image">Static image ad</option>
                <option value="video_ad">Video ad</option>
                <option value="carousel_ad">Carousel ad</option>
                <option value="story_ad">Story ad</option>
                <option value="lookalike_prospect">Lookalike prospecting</option>
                <option value="retargeting_warm">Retargeting warm</option>
                <option value="retargeting_cold">Retargeting cold</option>
                <option value="cold_email">Cold email</option>
                <option value="search_cpc">Search / CPC</option>
              </select>
            </div>
            <div>
              <Label className="text-zinc-300 text-xs">Device distribution</Label>
              <select value={ref.device_mode || "auto"}
                onChange={(e) => patch({ device_mode: e.target.value })}
                className="mt-1 w-full bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1.5 text-xs">
                <option value="auto">Auto</option>
                <option value="match_platform">Match platform</option>
                <option value="mobile_only">Mobile only</option>
                <option value="desktop_only">Desktop only</option>
              </select>
            </div>
            <div>
              <Label className="text-zinc-300 text-xs">Brand (email UTMs)</Label>
              <Input data-testid={`${testIdPrefix}-brand`} value={ref.brand || ""}
                onChange={(e) => patch({ brand: e.target.value.slice(0, 64) })}
                placeholder="your-brand"
                className="mt-1 bg-zinc-900 border-zinc-700 text-zinc-100 text-xs" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
