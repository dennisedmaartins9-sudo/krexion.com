import React, { useEffect, useRef, useState } from "react";
import axios from "axios";
import { Loader2, RefreshCw } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Native-only banner that auto-heals stale bundled UI after upgrades.
 * Backend compares backend/VERSION vs frontend/build-version.json and
 * downloads the matching zip from krexion.com when needed.
 */
export default function FrontendSyncBanner() {
  const [visible, setVisible] = useState(false);
  const [statusText, setStatusText] = useState("Checking UI bundle…");
  const syncingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      try {
        const versionRes = await axios.get(`${API}/system/version`, { timeout: 8000 });
        if (cancelled) return;
        if (!versionRes.data?.frontend_sync_needed) {
          setVisible(false);
          return;
        }

        setVisible(true);
        if (syncingRef.current) return;
        syncingRef.current = true;
        setStatusText("Updating Krexion UI from cloud…");

        await axios.post(`${API}/system/sync-frontend`, {}, { timeout: 300000 });
        if (cancelled) return;

        setStatusText("UI updated — reloading…");
        window.setTimeout(() => {
          window.location.reload();
        }, 1200);
      } catch (_err) {
        if (!cancelled) {
          setVisible(true);
          setStatusText("UI update pending — restarting Krexion usually fixes this.");
          syncingRef.current = false;
        }
      }
    };

    run();
    const timer = window.setInterval(run, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!visible) return null;

  return (
    <div
      data-testid="frontend-sync-banner"
      className="bg-gradient-to-r from-[#3b0a0a] to-[#1f0a0a] border-b border-red-500/40 text-white"
    >
      <div className="max-w-7xl mx-auto px-4 py-2.5 flex items-center gap-3 text-sm">
        <div className="shrink-0 w-7 h-7 rounded-md flex items-center justify-center border border-red-500/40 bg-red-500/20">
          <RefreshCw size={14} className="text-red-300" />
        </div>
        <div className="flex-1 min-w-0 font-medium">{statusText}</div>
        <Loader2 size={16} className="animate-spin text-red-300 shrink-0" />
      </div>
    </div>
  );
}
