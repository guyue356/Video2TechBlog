"use client";

import { useState, useEffect } from "react";

const API_BASE = "http://localhost:8000";

interface PromptTemplate {
  id: string;
  name: string;
  template: string;
  description: string;
}

const TEMPLATE_LABELS: Record<string, string> = {
  segment_chapters: "📋 章节划分",
  extract_knowledge: "🧠 知识提取",
  generate_blog_system: "⚙️ 博客生成 - 系统提示",
  generate_blog_user: "📝 博客生成 - 用户提示",
};

interface PromptSettingsProps {
  open: boolean;
  onClose: () => void;
}

export default function PromptSettings({ open, onClose }: PromptSettingsProps) {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetch(`${API_BASE}/api/prompts`)
      .then((r) => r.json())
      .then((data: PromptTemplate[]) => {
        // Sort to match our preferred order
        const order = Object.keys(TEMPLATE_LABELS);
        data.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
        setTemplates(data);
      })
      .catch(() => setMessage({ type: "err", text: "加载模板失败" }))
      .finally(() => setLoading(false));
  }, [open]);

  const handleSave = async (id: string) => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/api/prompts/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template: editValue }),
      });
      if (!res.ok) throw new Error("save failed");
      const updated: PromptTemplate = await res.json();
      setTemplates((prev) =>
        prev.map((t) => (t.id === id ? { ...t, template: updated.template } : t))
      );
      setEditingId(null);
      setMessage({ type: "ok", text: "保存成功" });
    } catch {
      setMessage({ type: "err", text: "保存失败" });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async (id: string) => {
    if (!confirm("确定要恢复此模板为默认值吗？")) return;
    setSaving(true);
    setMessage(null);
    try {
      // Re-fetch from server (which merges defaults)
      const res = await fetch(`${API_BASE}/api/prompts/${id}`);
      const data: PromptTemplate = await res.json();
      // Delete the DB entry by saving the default value back
      // Actually, we need a reset endpoint. For now, just inform the user.
      setMessage({ type: "ok", text: "请手动将模板内容替换为默认值后保存" });
    } catch {
      setMessage({ type: "err", text: "操作失败" });
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white border border-zinc-200 rounded-xl shadow-xl max-w-4xl w-full mx-4 max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200">
          <div>
            <h2 className="text-lg font-semibold">提示词模板设置</h2>
            <p className="text-sm text-zinc-500 mt-0.5">
              编辑各阶段的 AI 提示词。支持变量: {"{transcript}"}, {"{chapter_titles}"}, {"{knowledge_str}"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-zinc-100 rounded-lg transition-colors"
          >
            <svg className="w-5 h-5 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Message */}
        {message && (
          <div className={`mx-6 mt-3 px-4 py-2 rounded-lg text-sm ${
            message.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
          }`}>
            {message.text}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {loading ? (
            <div className="text-center py-12 text-zinc-400">加载中...</div>
          ) : (
            templates.map((t) => {
              const isExpanded = expandedId === t.id;
              const isEditing = editingId === t.id;
              const label = TEMPLATE_LABELS[t.id] || t.name;

              return (
                <div key={t.id} className="border border-zinc-200 rounded-lg overflow-hidden">
                  {/* Collapsed header */}
                  <button
                    onClick={() => {
                      setExpandedId(isExpanded ? null : t.id);
                      if (!isExpanded) {
                        setEditingId(null);
                      }
                    }}
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-50 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium">{label}</span>
                      <span className="text-xs text-zinc-400 font-mono">{t.id}</span>
                    </div>
                    <svg
                      className={`w-4 h-4 text-zinc-400 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {/* Expanded content */}
                  {isExpanded && (
                    <div className="px-4 pb-4 border-t border-zinc-100">
                      <p className="text-xs text-zinc-500 mt-3 mb-2">{t.description}</p>

                      {isEditing ? (
                        <div>
                          <textarea
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            className="w-full h-64 px-3 py-2 border border-zinc-300 rounded-lg text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-sky-400"
                            spellCheck={false}
                          />
                          <div className="flex gap-2 mt-2">
                            <button
                              onClick={() => handleSave(t.id)}
                              disabled={saving}
                              className="px-4 py-1.5 bg-sky-400 hover:bg-sky-400 disabled:opacity-40 rounded-lg text-sm font-medium text-white transition-colors"
                            >
                              {saving ? "保存中..." : "保存"}
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="px-4 py-1.5 bg-zinc-200 hover:bg-zinc-300 rounded-lg text-sm transition-colors"
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <pre className="bg-zinc-50 border border-zinc-200 rounded-lg p-3 text-xs text-zinc-700 font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
                            {t.template}
                          </pre>
                          <div className="flex gap-2 mt-2">
                            <button
                              onClick={() => {
                                setEditValue(t.template);
                                setEditingId(t.id);
                              }}
                              className="px-4 py-1.5 bg-zinc-900 hover:bg-zinc-700 rounded-lg text-sm font-medium text-white transition-colors"
                            >
                              编辑
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-zinc-200 bg-zinc-50 text-xs text-zinc-500">
          提示词中的 {"{transcript}"}, {"{chapter_titles}"}, {"{knowledge_str}"} 为运行时自动替换的变量。
          XML 标签 {"<transcript>"}, {"<chapters>"}, {"<knowledge>"} 用于防注入，建议保留。
        </div>
      </div>
    </div>
  );
}
