"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = "http://localhost:8001";

interface Preset {
  id: number;
  name: string;
  description: string;
  is_default: boolean;
}

interface PresetSelectorProps {
  value: number | null;
  onChange: (id: number | null) => void;
  onManageClick?: () => void; // open preset manager
  compact?: boolean; // smaller variant for dialogs
}

export default function PresetSelector({ value, onChange, onManageClick, compact }: PresetSelectorProps) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPresets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/presets`);
      if (!res.ok) return;
      const data: Preset[] = await res.json();
      if (!Array.isArray(data)) return;
      setPresets(data);
      // Auto-select default if no value set
      if (value === null) {
        const def = data.find((p) => p.is_default);
        if (def) onChange(def.id);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []); // intentionally stable; value/onChange handled by caller

  useEffect(() => {
    fetchPresets();
  }, [fetchPresets]);

  // Expose refresh for parent
  const refresh = useCallback(() => fetchPresets(), [fetchPresets]);

  // Store refresh on a ref-like pattern via a global callback
  useEffect(() => {
    // Attach refresh to a custom event so parent can trigger it
    const handler = () => fetchPresets();
    window.addEventListener("presets-refresh", handler);
    return () => window.removeEventListener("presets-refresh", handler);
  }, [fetchPresets]);

  if (loading) {
    return <div className={compact ? "text-xs text-zinc-400" : "text-sm text-zinc-400"}>加载预设...</div>;
  }

  return (
    <div className="flex items-center gap-2">
      <select
        value={value ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v ? Number(v) : null);
        }}
        className={`border border-zinc-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-400 ${
          compact ? "px-2 py-1 text-xs" : "px-3 py-2 text-sm"
        }`}
      >
        {presets.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}{p.is_default ? " (默认)" : ""}
          </option>
        ))}
      </select>
      {onManageClick && (
        <button
          onClick={onManageClick}
          className={`text-zinc-500 hover:text-zinc-800 transition-colors ${compact ? "text-xs" : "text-sm"}`}
          title="管理预设"
        >
          <svg className={compact ? "w-4 h-4" : "w-5 h-5"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      )}
    </div>
  );
}
