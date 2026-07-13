"use client";

import dynamic from "next/dynamic";
import { type TabKey, TAB_LABELS, TAB_ICONS } from "./useStageData";

const MarkdownRenderer = dynamic(() => import("./MarkdownRenderer"), {
  loading: () => <div className="animate-pulse h-64 bg-zinc-100 rounded-lg" />,
});

const API_BASE = "http://localhost:8000";

const KNOWLEDGE_CATEGORIES = [
  "concepts",
  "frameworks",
  "methods",
  "tools",
  "papers",
  "code_examples",
  "insights",
] as const;

const KNOWLEDGE_LABELS: Record<string, string> = {
  concepts: "概念",
  frameworks: "框架",
  methods: "方法",
  tools: "工具",
  papers: "论文",
  code_examples: "代码示例",
  insights: "洞察",
};

function formatDuration(sec: number): string {
  if (!sec) return "--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface ExportHandlers {
  onExportMd?: () => void;
  onExportTxt?: () => void;
  onExportSrt?: () => void;
  onExportJson?: (stage: string) => void;
  onDownloadAudio?: () => void;
}

interface StageViewerProps {
  videoId: string;
  filename?: string;
  duration?: number;
  stageData: Record<string, Record<string, unknown>>;
  audioUrl: string | null;
  activeTab: TabKey;
  onTabChange: (tab: TabKey) => void;
  /** Whether to show export/download buttons. Default: false */
  showExport?: boolean;
  /** Blog content. Falls back to stageData.blog if not provided */
  blogMarkdown?: string;
  blogId?: number | null;
  exportHandlers?: ExportHandlers;
  /** Callback to regenerate blog only (skip transcript/chapters/knowledge) */
  onRegenerate?: () => void;
  /** Whether blog regeneration is in progress */
  regenerating?: boolean;
}

export default function StageViewer({
  videoId,
  filename,
  duration,
  stageData,
  audioUrl,
  activeTab,
  onTabChange,
  showExport = false,
  blogMarkdown,
  blogId,
  exportHandlers,
  onRegenerate,
  regenerating = false,
}: StageViewerProps) {
  const sd = stageData;

  // Resolve blog content from props or stageData
  const resolvedBlogMd = blogMarkdown ?? (sd.blog?.markdown as string) ?? "";

  return (
    <div>
      {/* Tab bar */}
      <div className="flex gap-1 mb-4 border-b border-zinc-200">
        {(Object.keys(TAB_LABELS) as TabKey[]).map((key) => (
          <button
            key={key}
            onClick={() => onTabChange(key)}
            className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${
              activeTab === key
                ? "bg-white text-zinc-900 border-b-2 border-sky-400 shadow-sm"
                : "text-zinc-500 hover:text-zinc-700 hover:bg-zinc-200/50"
            }`}
          >
            <span className="mr-1.5">{TAB_ICONS[key]}</span>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-6 min-h-[400px]">
        {/* Video */}
        {activeTab === "video" && (
          <div>
            <h3 className="text-lg font-semibold mb-4">原始视频</h3>
            <div className="bg-zinc-100 rounded-lg p-4">
              <video
                controls
                className="w-full max-h-[60vh] rounded"
                src={`${API_BASE}/api/video/${videoId}`}
              >
                您的浏览器不支持视频播放
              </video>
              <div className="flex items-center gap-4 mt-3 text-xs text-zinc-500">
                {filename && <span>文件: {filename}</span>}
                {duration != null && <span>时长: {formatDuration(duration)}</span>}
                {!filename && <span>视频 ID: {videoId}</span>}
              </div>
            </div>
          </div>
        )}

        {/* Audio */}
        {activeTab === "audio" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">音频</h3>
              {showExport && exportHandlers?.onDownloadAudio && (
                <button
                  onClick={exportHandlers.onDownloadAudio}
                  disabled={!audioUrl}
                  className="px-3 py-1.5 bg-sky-400 hover:bg-sky-400 disabled:opacity-40 rounded-lg text-sm font-medium transition-colors"
                >
                  下载 .wav
                </button>
              )}
            </div>
            {audioUrl ? (
              <div className="bg-zinc-100 rounded-lg p-4">
                <audio controls src={audioUrl} className="w-full" />
                <p className="text-xs text-zinc-500 mt-2">
                  时长:{" "}
                  {sd.audio?.duration
                    ? `${Number(sd.audio.duration).toFixed(1)}秒`
                    : "无"}
                </p>
              </div>
            ) : (
              <p className="text-zinc-500">暂无音频</p>
            )}
          </div>
        )}

        {/* Transcript */}
        {activeTab === "transcript" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">转录文本</h3>
              {showExport && (
                <div className="flex gap-2">
                  {exportHandlers?.onExportTxt && (
                    <button
                      onClick={exportHandlers.onExportTxt}
                      className="px-3 py-1.5 bg-sky-400 hover:bg-sky-400 rounded-lg text-sm font-medium transition-colors"
                    >
                      导出 .txt
                    </button>
                  )}
                  {exportHandlers?.onExportSrt && (
                    <button
                      onClick={exportHandlers.onExportSrt}
                      className="px-3 py-1.5 bg-green-600 hover:bg-green-500 rounded-lg text-sm font-medium transition-colors"
                    >
                      导出 .srt
                    </button>
                  )}
                </div>
              )}
            </div>
            {sd.transcript?.segments ? (
              <div className="bg-zinc-100 rounded-lg p-4 max-h-[60vh] overflow-y-auto">
                <pre className="text-sm text-zinc-700 whitespace-pre-wrap font-mono leading-relaxed">
                  {(
                    sd.transcript.segments as Array<{
                      start: number;
                      end: number;
                      text: string;
                    }>
                  )
                    .map(
                      (s) =>
                        `[${s.start.toFixed(1)}秒-${s.end.toFixed(1)}秒] ${s.text}`
                    )
                    .join("\n")}
                </pre>
              </div>
            ) : sd.transcript?.transcript ? (
              <div className="bg-zinc-100 rounded-lg p-4 max-h-[60vh] overflow-y-auto">
                <pre className="text-sm text-zinc-700 whitespace-pre-wrap font-mono leading-relaxed">
                  {String(sd.transcript.transcript)}
                </pre>
              </div>
            ) : (
              <p className="text-zinc-500">暂无转录文本</p>
            )}
          </div>
        )}

        {/* Chapters */}
        {activeTab === "chapters" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">章节结构</h3>
              {showExport && exportHandlers?.onExportJson && (
                <button
                  onClick={() => exportHandlers.onExportJson!("chapters")}
                  className="px-3 py-1.5 bg-sky-400 hover:bg-sky-400 rounded-lg text-sm font-medium transition-colors"
                >
                  导出 .json
                </button>
              )}
            </div>
            {sd.chapters?.chapters ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-300">
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">#</th>
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">标题</th>
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">时间范围</th>
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">重要度</th>
                      <th className="text-left py-2 px-3 text-zinc-400 font-medium">摘要</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      sd.chapters.chapters as Array<{
                        title: string;
                        start_time: number;
                        end_time: number;
                        importance_score: number;
                        summary: string;
                      }>
                    ).map((ch, i) => (
                      <tr
                        key={i}
                        className="border-b border-zinc-200 hover:bg-zinc-200/50"
                      >
                        <td className="py-2 px-3 text-zinc-500">{i + 1}</td>
                        <td className="py-2 px-3 text-zinc-800 font-medium">
                          {ch.title}
                        </td>
                        <td className="py-2 px-3 text-zinc-400 font-mono text-xs">
                          {ch.start_time}秒 — {ch.end_time}秒
                        </td>
                        <td className="py-2 px-3">
                          <span
                            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                              ch.importance_score >= 8
                                ? "bg-red-100 text-red-700"
                                : ch.importance_score >= 5
                                  ? "bg-yellow-100 text-yellow-700"
                                  : "bg-zinc-300 text-zinc-400"
                            }`}
                          >
                            {ch.importance_score}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-zinc-400 text-xs max-w-xs truncate">
                          {ch.summary}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-zinc-500">暂无章节</p>
            )}
          </div>
        )}

        {/* Knowledge */}
        {activeTab === "knowledge" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">知识提取</h3>
              {showExport && exportHandlers?.onExportJson && (
                <button
                  onClick={() => exportHandlers.onExportJson!("knowledge")}
                  className="px-3 py-1.5 bg-sky-400 hover:bg-sky-400 rounded-lg text-sm font-medium transition-colors"
                >
                  导出 .json
                </button>
              )}
            </div>
            {sd.knowledge && Object.keys(sd.knowledge).length > 0 ? (
              <div className="grid grid-cols-2 gap-4">
                {KNOWLEDGE_CATEGORIES.map((cat) => {
                  const items = sd.knowledge[cat] as string[] | undefined;
                  if (!items || items.length === 0) return null;
                  return (
                    <div
                      key={cat}
                      className="bg-zinc-100 border border-zinc-200 rounded-lg p-4"
                    >
                      <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                        {KNOWLEDGE_LABELS[cat]}
                      </h4>
                      <ul className="space-y-1">
                        {items.map((item, i) => (
                          <li
                            key={i}
                            className="text-sm text-zinc-700 flex items-start gap-2"
                          >
                            <span className="text-zinc-400 mt-0.5">*</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-zinc-500">暂无知识数据</p>
            )}
          </div>
        )}

        {/* Blog */}
        {activeTab === "blog" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">博客</h3>
              <div className="flex gap-2">
                {onRegenerate && (
                  <button
                    onClick={onRegenerate}
                    disabled={regenerating}
                    className="px-3 py-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-40 rounded-lg text-sm font-medium transition-colors"
                  >
                    {regenerating ? "生成中..." : "重新生成"}
                  </button>
                )}
                {showExport && exportHandlers?.onExportMd && (
                  <button
                    onClick={exportHandlers.onExportMd}
                    disabled={!blogId}
                    className="px-3 py-1.5 bg-sky-400 hover:bg-sky-400 disabled:opacity-40 rounded-lg text-sm font-medium transition-colors"
                  >
                    导出 .md
                  </button>
                )}
              </div>
            </div>
            {resolvedBlogMd ? (
              <div className="bg-zinc-100 rounded-lg p-6">
                <MarkdownRenderer content={resolvedBlogMd} />
              </div>
            ) : (
              <p className="text-zinc-500">暂无博客</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
