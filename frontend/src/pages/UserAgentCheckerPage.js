import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import {
  Search,
  Smartphone,
  Monitor,
  Globe,
  CheckCircle2,
  AlertTriangle,
  Copy,
  RefreshCw,
  Cpu,
  MapPin,
  Wifi,
  Tag,
  FileText,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

const SAMPLE_UAS = [
  {
    label: "TikTok Android",
    ua: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/149.0.7827.114 Mobile Safari/537.36 TikTok/45.8.2 musical_ly_2024508020 JsSdk/1.0 NetType/WIFI Channel/googleplay AppName/musical_ly app_version/45.8.2 ByteLocale/en-GB ByteFullLocale/en-GB Region/GB com.zhiliaoapp.musically/2024508020",
  },
  {
    label: "Instagram Android",
    ua: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/149.0.7827.114 Mobile Safari/537.36 Instagram 437.0.0.33.78 Android (34/14; 420dpi; 1080x2400; google; Pixel 8; husky; tensor; en_US; 1011909233; IABMV/1)",
  },
  {
    label: "Facebook Android",
    ua: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/149.0.7827.114 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/556.0.0.59.68;IABMV/1;FBBV/681204512;]",
  },
  {
    label: "Chrome Desktop",
    ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.114 Safari/537.36",
  },
];

function Row({ icon: Icon, label, value, mono = false, testId }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-start gap-3 py-2 border-b border-zinc-800 last:border-0" data-testid={testId}>
      <div className="w-7 h-7 rounded bg-zinc-800 flex items-center justify-center shrink-0 mt-0.5">
        <Icon className="w-3.5 h-3.5 text-zinc-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
        <div className={`text-sm text-white ${mono ? "font-mono" : ""} break-words`}>
          {String(value)}
        </div>
      </div>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, accent }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <Icon className={`w-4 h-4 ${accent || "text-zinc-400"}`} />
      <h3 className="text-sm font-semibold text-zinc-200 uppercase tracking-wider">
        {title}
      </h3>
    </div>
  );
}

export default function UserAgentCheckerPage() {
  const [ua, setUa] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const analyze = async () => {
    const trimmed = ua.trim();
    if (!trimmed) {
      toast.error("Paste a user agent first");
      return;
    }
    setLoading(true);
    try {
      const token = localStorage.getItem("token");
      const r = await fetch(`${API_URL}/api/user-agents/check`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ user_agent: trimmed }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        toast.error(d.detail || "Failed to analyze");
        return;
      }
      setResult(await r.json());
    } catch (e) {
      toast.error("Network error: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    setUa("");
    setResult(null);
  };

  const copyRawJson = () => {
    if (!result) return;
    navigator.clipboard.writeText(JSON.stringify(result, null, 2));
    toast.success("Full JSON copied");
  };

  const loadSample = (sample) => {
    setUa(sample.ua);
    setResult(null);
  };

  // Decide summary icon / color based on platform
  const PlatformIcon =
    result?.platform === "iOS" || result?.platform === "Android"
      ? Smartphone
      : result?.platform === "Windows" || result?.platform === "macOS" || result?.platform === "Linux"
      ? Monitor
      : Globe;

  return (
    <div className="space-y-6" data-testid="ua-checker-page">
      <div>
        <h1 className="text-2xl font-bold text-white">User Agent Checker</h1>
        <p className="text-zinc-400">
          Paste any user agent and get a full breakdown — browser, OS, device,
          in-app detection, TikTok metadata (locale / region / net type),
          engine/runtime compatibility, support state, identities and contract warnings.
          Results check coherence against verified samples; they do not guarantee authenticity.
        </p>
      </div>

      {/* Input card */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-white flex items-center gap-2">
            <Search className="w-5 h-5 text-blue-500" />
            Paste a user agent
          </CardTitle>
          <CardDescription>
            Works for in-app UAs (TikTok, Instagram, Facebook, Pinterest, Snapchat) and regular browsers.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            value={ua}
            onChange={(e) => setUa(e.target.value)}
            placeholder="Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 ..."
            rows={4}
            className="w-full bg-zinc-950 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 font-mono resize-y focus:outline-none focus:border-blue-500"
            data-testid="ua-checker-input"
          />

          {/* Sample UAs */}
          <div className="flex flex-wrap gap-2">
            <span className="text-xs text-zinc-500 self-center">Try a sample:</span>
            {SAMPLE_UAS.map((s) => (
              <button
                key={s.label}
                onClick={() => loadSample(s)}
                className="text-xs px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 transition"
                data-testid={`ua-sample-${s.label.toLowerCase().replace(/\s+/g, "-")}`}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap gap-3">
            <Button
              onClick={analyze}
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-700"
              data-testid="ua-checker-analyze-btn"
            >
              {loading ? (
                <><RefreshCw className="w-4 h-4 mr-2 animate-spin" /> Analyzing...</>
              ) : (
                <><Search className="w-4 h-4 mr-2" /> Analyze</>
              )}
            </Button>
            <Button
              variant="outline"
              onClick={clearAll}
              className="border-zinc-700 text-zinc-300"
              data-testid="ua-checker-clear-btn"
            >
              Clear
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Result */}
      {result && (
        <>
          {/* Summary bar */}
          <Card className="bg-zinc-900 border-zinc-800" data-testid="ua-checker-result">
            <CardContent className="py-4">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center">
                    <PlatformIcon className="w-5 h-5 text-blue-400" />
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-zinc-500">Summary</div>
                    <div className="text-white text-base font-medium" data-testid="ua-summary">
                      {result.summary}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {result.valid ? (
                    <Badge className="bg-green-900/40 text-green-300 border border-green-800" data-testid="ua-verdict">
                      <CheckCircle2 className="w-3 h-3 mr-1" /> Contract coherent
                    </Badge>
                  ) : (
                    <Badge className="bg-amber-900/40 text-amber-300 border border-amber-800" data-testid="ua-verdict">
                      <AlertTriangle className="w-3 h-3 mr-1" /> {result.verdict?.issues?.length || 0} issue(s)
                    </Badge>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={copyRawJson}
                    className="border-zinc-700 text-zinc-300 focus-visible:ring-2 focus-visible:ring-blue-400"
                    data-testid="ua-copy-json-btn"
                    aria-label="Copy full user agent analysis as JSON"
                    title="Copy full user agent analysis as JSON"
                  >
                    <Copy className="w-3.5 h-3.5 mr-1" /> JSON
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Detail grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Browser / App */}
            <Card className="bg-zinc-900 border-zinc-800">
              <CardContent className="py-4">
                <SectionHeader icon={Tag} title={result.app?.is_inapp ? "In-App Browser" : "Browser"} accent="text-pink-400" />
                <Row icon={Tag} label="App / Browser" value={result.app?.app_name || result.browser?.family} testId="ua-row-app" />
                <Row icon={Tag} label="App version" value={result.app?.app_version} mono testId="ua-row-appver" />
                <Row icon={Cpu} label="Engine" value={result.engine} testId="ua-row-engine" />
                <Row icon={Tag} label="Browser version" value={result.browser?.version} mono testId="ua-row-browserver" />
                <Row icon={Tag} label="Profile type" value={result.profile_type} testId="ua-row-profile-type" />
                <Row icon={Tag} label="Runtime" value={result.runtime} testId="ua-row-runtime" />
                <Row icon={Tag} label="Runtime compatible" value={typeof result.runtime_compatible === "boolean" ? (result.runtime_compatible ? "Yes" : "No") : null} testId="ua-row-runtime-compatible" />
                <Row icon={Tag} label="Support state" value={result.profile?.support_state} testId="ua-row-support-state" />
                <Row icon={Tag} label="Identities" value={(result.app?.identities || result.profile?.identities || []).join(", ")} testId="ua-row-identities" />
                <Row icon={Tag} label="Is in-app webview" value={result.app?.is_inapp ? "Yes" : "No"} testId="ua-row-inapp" />
                <Row icon={Tag} label="Traffic source guess" value={result.traffic_source_guess} testId="ua-row-source" />
              </CardContent>
            </Card>

            {/* OS / Platform */}
            <Card className="bg-zinc-900 border-zinc-800">
              <CardContent className="py-4">
                <SectionHeader icon={Cpu} title="Operating System" accent="text-indigo-400" />
                <Row icon={Cpu} label="Platform" value={result.platform} testId="ua-row-platform" />
                <Row icon={Cpu} label="OS family" value={result.os?.family} testId="ua-row-osfam" />
                <Row icon={Cpu} label="OS version" value={result.os?.version} mono testId="ua-row-osver" />
              </CardContent>
            </Card>

            {/* Device */}
            <Card className="bg-zinc-900 border-zinc-800">
              <CardContent className="py-4">
                <SectionHeader icon={Smartphone} title="Device" accent="text-emerald-400" />
                <Row icon={Smartphone} label="Family" value={result.device?.family} testId="ua-row-devfam" />
                <Row icon={Smartphone} label="Brand" value={result.device?.brand} testId="ua-row-devbrand" />
                <Row icon={Smartphone} label="Model" value={result.device?.model} testId="ua-row-devmodel" />
                <Row icon={Smartphone} label="Is mobile" value={result.flags?.is_mobile ? "Yes" : "No"} testId="ua-row-ismobile" />
                <Row icon={Smartphone} label="Is tablet" value={result.flags?.is_tablet ? "Yes" : "No"} testId="ua-row-istablet" />
                <Row icon={Monitor} label="Is desktop / PC" value={result.flags?.is_pc ? "Yes" : "No"} testId="ua-row-ispc" />
                <Row icon={Smartphone} label="Touch capable" value={result.flags?.is_touch_capable ? "Yes" : "No"} testId="ua-row-touch" />
                <Row icon={AlertTriangle} label="Is bot" value={result.flags?.is_bot ? "Yes" : "No"} testId="ua-row-isbot" />
              </CardContent>
            </Card>

            {/* TikTok metadata (only shown for TikTok UAs) */}
            {result.tiktok_metadata && (
              <Card className="bg-zinc-900 border-zinc-800">
                <CardContent className="py-4">
                  <SectionHeader icon={MapPin} title="TikTok Metadata" accent="text-pink-400" />
                  <Row icon={Wifi} label="Network type" value={result.tiktok_metadata.net_type} testId="ua-row-nettype" />
                  <Row icon={Tag} label="Channel" value={result.tiktok_metadata.channel} testId="ua-row-channel" />
                  <Row icon={Globe} label="Locale" value={result.tiktok_metadata.locale} testId="ua-row-locale" />
                  <Row icon={MapPin} label="Region" value={result.tiktok_metadata.region} testId="ua-row-region" />
                  <Row icon={Tag} label="JsSdk" value={result.tiktok_metadata.jssdk} mono testId="ua-row-jssdk" />
                </CardContent>
              </Card>
            )}

            {/* Issues — always visible when present */}
            {(result.verdict?.issues || []).length > 0 && (
              <Card className="bg-amber-950/30 border-amber-900 lg:col-span-2">
                <CardContent className="py-4">
                  <SectionHeader icon={AlertTriangle} title="Issues detected" accent="text-amber-400" />
                  <ul className="space-y-1.5 text-sm text-amber-200">
                    {result.verdict.issues.map((issue, i) => (
                      <li key={i} className="flex gap-2">
                        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                        <span>{issue}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}

            {(result.verdict?.warnings || []).length > 0 && (
              <Card className="bg-blue-950/30 border-blue-900 lg:col-span-2">
                <CardContent className="py-4">
                  <SectionHeader icon={AlertTriangle} title="Warnings" accent="text-blue-400" />
                  <ul className="space-y-1.5 text-sm text-blue-200">
                    {result.verdict.warnings.map((warning, i) => (
                      <li key={i} className="flex gap-2">
                        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                        <span>{warning}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}

            {/* Raw UA */}
            <Card className="bg-zinc-900 border-zinc-800 lg:col-span-2">
              <CardContent className="py-4">
                <SectionHeader icon={FileText} title="Raw user agent" accent="text-zinc-400" />
                <div className="text-xs text-zinc-400 mb-1">
                  Length: <span className="text-zinc-200">{result.length} chars</span>
                </div>
                <code className="block text-xs text-zinc-200 font-mono bg-zinc-950 p-3 rounded border border-zinc-800 break-all">
                  {result.user_agent}
                </code>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
