import React from "react";

/**
 * Weighted multi-select — shared by RUT jobs, manual Links, and Browser Profiles.
 */
export default function ReferrerProMultiSelect({
  title,
  description,
  keys,
  weights,
  onChange,
  accent = "fuchsia",
  testIdPrefix = "referrer-pro",
}) {
  const total = Object.values(weights || {}).reduce((s, w) => s + (parseFloat(w) || 0), 0);
  const accentClasses = {
    fuchsia: { ring: "border-fuchsia-700/40", bg: "bg-fuchsia-950/20", text: "text-fuchsia-300", slider: "accent-fuchsia-500" },
    emerald: { ring: "border-emerald-700/40", bg: "bg-emerald-950/20", text: "text-emerald-300", slider: "accent-emerald-500" },
    cyan: { ring: "border-cyan-700/40", bg: "bg-cyan-950/20", text: "text-cyan-300", slider: "accent-cyan-500" },
    amber: { ring: "border-[#F59E0B60]", bg: "bg-[#F59E0B10]", text: "text-[#F59E0B]", slider: "accent-[#F59E0B]" },
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
            Total:{" "}
            <span className={total >= 90 && total <= 110 ? "text-emerald-300 font-semibold" : "text-amber-400"}>
              {total.toFixed(0)}%
            </span>
          </span>
          <button
            type="button"
            data-testid={`${testIdPrefix}-reset`}
            onClick={resetEqual}
            className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 hover:bg-zinc-700"
          >
            Equal
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(keys || []).map((k) => {
          const active = weights && weights[k] !== undefined;
          return (
            <button
              key={k}
              type="button"
              data-testid={`${testIdPrefix}-chip-${k}`}
              onClick={() => toggle(k)}
              className={`text-[11px] px-2.5 py-1 rounded-full border transition ${
                active ? `${accentClasses.text} border-current bg-zinc-900/80` : "text-zinc-500 border-zinc-700 bg-zinc-900/40 hover:text-zinc-300"
              }`}
            >
              {k}
              {active ? ` (${(weights[k] || 0).toFixed(0)}%)` : ""}
            </button>
          );
        })}
      </div>
      {Object.keys(weights || {}).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(weights).map(([k, w]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-24 text-xs text-zinc-300 truncate">{k}</span>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={w}
                data-testid={`${testIdPrefix}-slider-${k}`}
                onChange={(e) => setWeight(k, e.target.value)}
                className={`flex-1 ${accentClasses.slider}`}
              />
              <span className="w-8 text-xs text-zinc-400 text-right">{Number(w).toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
