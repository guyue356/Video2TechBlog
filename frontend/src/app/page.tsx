"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { useStageData, type TabKey } from "./useStageData";
import StageViewer from "./StageViewer";
import PromptSettings from "./PromptSettings";
import PresetSelector from "./PresetSelector";
import PresetManager from "./PresetManager";

const MarkdownRenderer = dynamic(() => import("./MarkdownRenderer"), {
  loading: () => <div className="animate-pulse h-64 bg-zinc-100 rounded-lg" />,
});

const API_BASE = "http://localhost:8001";

const STEPS = [
  "extract_audio",
  "transcribe",
  "segment_chapters",
  "extract_knowledge",
  "generate_blog",
];

const STEP_LABELS: Record<string, string> = {
  extract_audio: "音频提取",
  transcribe: "语音转录",
  segment_chapters: "章节划分",
  extract_knowledge: "知识提取",
  generate_blog: "博客生成",
};

interface StepState {
  status: "pending" | "active" | "completed" | "error";
  progressPct: number;
  detail: string;
  message: string;
  result: unknown;
}

interface VideoItem {
  task_id: string;
  title: string;
  filename: string;
  status: string;
  duration: number;
  processing_duration: number | null;
  has_blog: boolean;
  source_type: string;
  source_url: string;
  created_at: string | null;
}

interface VideoDetail {
  task_id: string;
  title: string;
  filename: string;
  status: string;
  duration: number;
  processing_duration: number | null;
  source_type: string;
  source_url: string;
  created_at: string | null;
  blog: { id: number; title: string; markdown: string } | null;
  transcript_segments: number;
  chapters_count: number;
  concepts_count: number;
}

const SOURCE_LABELS: Record<string, string> = {
  video: "视频",
  audio: "音频",
  url: "链接",
};

const SOURCE_COLORS: Record<string, string> = {
  video: "bg-sky-100 text-sky-600",
  audio: "bg-teal-100 text-teal-700",
  url: "bg-purple-100 text-purple-700",
};

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  failed: "失败",
  cancelled: "已终止",
  pending: "等待中",
  extracting_audio: "提取音频",
  transcribing: "转录中",
  segmenting: "分段中",
  extracting_knowledge: "提取知识",
  generating_blog: "生成博客",
};

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-zinc-200 text-zinc-600",
  pending: "bg-yellow-100 text-yellow-700",
  extracting_audio: "bg-sky-100 text-sky-600",
  transcribing: "bg-sky-100 text-sky-600",
  segmenting: "bg-sky-100 text-sky-600",
  extracting_knowledge: "bg-sky-100 text-sky-600",
  generating_blog: "bg-sky-100 text-sky-600",
};

function formatDuration(sec: number): string {
  if (!sec) return "--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatDate(d: string | null): string {
  if (!d) return "--";
  return new Date(d).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Home() {
  // Top-level view
  const [view, setView] = useState<"upload" | "assets">("upload");

  // Upload/processing state
  const [taskId, setTaskId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadMode, setUploadMode] = useState<"file" | "url">("file");
  const [urlInput, setUrlInput] = useState("");
  const [urlSubmitting, setUrlSubmitting] = useState(false);
  const [steps, setSteps] = useState<Record<string, StepState>>({});
  const [transcript, setTranscript] = useState("");
  const [chapters, setChapters] = useState<Array<Record<string, unknown>>>([]);
  const [knowledge, setKnowledge] = useState<Record<string, unknown>>({});
  const [blogMd, setBlogMd] = useState("");
  const [blogId, setBlogId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState<"upload" | "processing" | "done">("upload");
  const [activeTab, setActiveTab] = useState<TabKey>("video");
  const [elapsed, setElapsed] = useState(0);
  const elapsedRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const readerRef = useRef<EventSource | null>(null);
  const doneStageRef = useRef<ReturnType<typeof useStageData> | null>(null);

  // Shared stage data hooks (one for "done" phase, one for asset detail)
  const doneStage = useStageData();
  const detailStage = useStageData();

  // Keep ref in sync with latest doneStage (avoids stale closure in SSE useEffect)
  doneStageRef.current = doneStage;

  // Asset management state
  const [videoList, setVideoList] = useState<VideoItem[]>([]);
  const [assetSearch, setAssetSearch] = useState("");
  const [assetStatusFilter, setAssetStatusFilter] = useState("");
  const [selectedVideo, setSelectedVideo] = useState<VideoDetail | null>(null);
  const [assetDetailTab, setAssetDetailTab] = useState<TabKey>("video");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [showPromptSettings, setShowPromptSettings] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [presetId, setPresetId] = useState<number | null>(null);
  const [showPresetManager, setShowPresetManager] = useState(false);
  const [regenerateDialogVideoId, setRegenerateDialogVideoId] = useState<string | null>(null);
  const [regeneratePresetId, setRegeneratePresetId] = useState<number | null>(null);

  const initSteps = useCallback(() => {
    const s: Record<string, StepState> = {};
    STEPS.forEach((k) => {
      s[k] = { status: "pending", progressPct: 0, detail: "", message: "", result: null };
    });
    setSteps(s);
  }, []);

  // Fetch video list
  const fetchVideoList = useCallback(async () => {
    setLoadingAssets(true);
    try {
      const params = new URLSearchParams();
      if (assetSearch) params.set("search", assetSearch);
      if (assetStatusFilter) params.set("status", assetStatusFilter);
      const res = await fetch(`${API_BASE}/api/videos?${params}`);
      if (res.ok) {
        setVideoList(await res.json());
      }
    } catch { /* ignore */ }
    setLoadingAssets(false);
  }, [assetSearch, assetStatusFilter]);

  useEffect(() => {
    if (view === "assets" && !selectedVideo) {
      fetchVideoList();
    }
  }, [view, selectedVideo, fetchVideoList]);

  // Fetch detail for a selected video
  const fetchVideoDetail = useCallback(async (videoId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/videos/${videoId}`);
      if (res.ok) {
        const detail: VideoDetail = await res.json();
        setSelectedVideo(detail);
        setAssetDetailTab("blog");
        detailStage.reset();
        if (detail.status === "completed") {
          detailStage.fetchStageData(videoId);
        }
      }
    } catch { /* ignore */ }
  }, [detailStage]);

  // Delete a video
  const handleDelete = useCallback(async (videoId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/videos/${videoId}`, { method: "DELETE" });
      if (res.ok) {
        setDeleteConfirm(null);
        if (selectedVideo?.task_id === videoId) {
          setSelectedVideo(null);
          detailStage.reset();
        }
        fetchVideoList();
      }
    } catch { /* ignore */ }
  }, [selectedVideo, fetchVideoList, detailStage]);

  // Reprocess a video
  const handleReprocess = useCallback(async (videoId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/videos/${videoId}/reprocess`, { method: "POST" });
      if (res.ok) {
        setView("upload");
        setPhase("processing");
        setTaskId(videoId);
        setSelectedVideo(null);
        detailStage.reset();
        initSteps();
        setTranscript("");
        setChapters([]);
        setKnowledge({});
        setBlogMd("");
        setBlogId(null);
        setActiveTab("blog");
        doneStage.reset();
      }
    } catch { /* ignore */ }
  }, [initSteps, doneStage, detailStage]);

  // Regenerate blog only (keeps transcript/chapters/knowledge)
  const handleRegenerate = useCallback(async (videoId: string, regPresetId?: number | null) => {
    setRegenerating(true);
    setRegenerateDialogVideoId(null);
    try {
      const body: Record<string, unknown> = {};
      if (regPresetId) body.preset_id = regPresetId;
      const res = await fetch(`${API_BASE}/api/videos/${videoId}/regenerate-blog`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setRegenerating(false);
        return;
      }

      // Monitor SSE for completion
      const es = new EventSource(`${API_BASE}/api/task/${videoId}/stream`);
      es.addEventListener("step_progress", (e) => {
        // Blog generation progress updates
      });
      es.addEventListener("step_result", (e) => {
        const data = JSON.parse(e.data);
        if (data.step === "generate_blog") {
          // Refresh stage data
          detailStage.fetchStageData(videoId);
        }
      });
      es.addEventListener("complete", () => {
        es.close();
        setRegenerating(false);
        // Refresh video list and detail
        fetchVideoList();
        if (selectedVideo?.task_id === videoId) {
          fetch(`${API_BASE}/api/videos/${videoId}`)
            .then((r) => r.json())
            .then((d: VideoDetail) => setSelectedVideo(d));
        }
      });
      es.addEventListener("step_error", () => {
        es.close();
        setRegenerating(false);
      });
      es.onerror = () => {
        es.close();
        setRegenerating(false);
      };
    } catch {
      setRegenerating(false);
    }
  }, [detailStage.fetchStageData, fetchVideoList, selectedVideo]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    setError("");
    setElapsed(0);
    elapsedRef.current = 0;
    initSteps();
    setTranscript("");
    setChapters([]);
    setKnowledge({});
    setBlogMd("");
    setBlogId(null);
    setPhase("processing");
    setActiveTab("blog");
    doneStage.reset();

    const formData = new FormData();
    formData.append("file", file);
    if (presetId !== null) formData.append("preset_id", String(presetId));

    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        setUploadProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        setTaskId(data.task_id);
        setUploading(false);
      } else {
        setError("上传失败");
        setPhase("upload");
        setUploading(false);
      }
    });

    xhr.addEventListener("error", () => {
      setError("上传失败");
      setPhase("upload");
      setUploading(false);
    });

    // Unified /api/upload handles both video and audio — the backend
    // auto-detects the source type from the content type / extension.
    xhr.open("POST", `${API_BASE}/api/upload`);
    xhr.send(formData);
  };

  const handleUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const url = urlInput.trim();
    if (!url) return;

    // Basic URL validation
    try {
      new URL(url);
    } catch {
      setError("请输入有效的链接");
      return;
    }

    setUrlSubmitting(true);
    setError("");
    setElapsed(0);
    elapsedRef.current = 0;
    initSteps();
    setTranscript("");
    setChapters([]);
    setKnowledge({});
    setBlogMd("");
    setBlogId(null);
    setPhase("processing");
    setActiveTab("blog");
    doneStage.reset();

    try {
      const res = await fetch(`${API_BASE}/api/upload/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, audio_only: true, preset_id: presetId }),
      });
      if (res.ok) {
        const data = await res.json();
        setTaskId(data.task_id);
      } else {
        setError("链接提交失败");
        setPhase("upload");
      }
    } catch {
      setError("网络错误，请重试");
      setPhase("upload");
    } finally {
      setUrlSubmitting(false);
    }
  };

  // Timer for elapsed time during processing
  useEffect(() => {
    if (phase === "processing") {
      elapsedRef.current = 0;
      setElapsed(0);
      timerRef.current = setInterval(() => {
        elapsedRef.current += 1;
        setElapsed(elapsedRef.current);
      }, 1000);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [phase]);

  // Connect to SSE when taskId changes
  useEffect(() => {
    if (!taskId || phase !== "processing") return;

    const es = new EventSource(`${API_BASE}/api/task/${taskId}/stream`);
    readerRef.current = es;

    const setStepStatus = (stepKey: string, status: StepState["status"]) => {
      setSteps((prev) => ({
        ...prev,
        [stepKey]: { ...prev[stepKey], status },
      }));
    };

    es.addEventListener("step_start", (e) => {
      const d = JSON.parse(e.data);
      if (STEPS.includes(d.step)) {
        const idx = STEPS.indexOf(d.step);
        setSteps((prev) => {
          const next = { ...prev };
          // 新步骤已经开始，说明它前面的步骤必然已完成；
          // 如果之前因网络/事件丢失没改成 completed，这里兜底修正
          for (let i = 0; i < idx; i++) {
            const key = STEPS[i];
            if (next[key]?.status === "active") {
              next[key] = { ...next[key], status: "completed", progressPct: 100 };
            }
          }
          next[d.step] = { ...next[d.step], status: "active", message: d.message || "" };
          return next;
        });
      }
    });

    es.addEventListener("step_progress", (e) => {
      const d = JSON.parse(e.data);
      if (STEPS.includes(d.step)) {
        setSteps((prev) => ({
          ...prev,
          [d.step]: {
            ...prev[d.step],
            progressPct: d.progress_pct ?? prev[d.step].progressPct,
            detail: d.detail ?? "",
          },
        }));
        if (d.step === "generate_blog" && d.detail) {
          setBlogMd((prev) => prev + d.detail);
        }
      }
    });

    es.addEventListener("step_result", (e) => {
      const d = JSON.parse(e.data);
      if (STEPS.includes(d.step)) {
        setSteps((prev) => ({
          ...prev,
          [d.step]: {
            ...prev[d.step],
            status: "completed",
            result: d,
            progressPct: 100,
            detail: d.detail ?? prev[d.step].detail ?? "",
          },
        }));
        if (d.step === "transcribe" && d.transcript) {
          setTranscript(d.transcript);
        }
        if (d.step === "segment_chapters" && d.chapters) {
          setChapters(d.chapters);
        }
        if (d.step === "extract_knowledge" && d.knowledge) {
          setKnowledge(d.knowledge);
        }
      }
    });

    es.addEventListener("step_error", (e) => {
      const d = JSON.parse(e.data);
      setError(d.message || "处理出错");
      if (STEPS.includes(d.step)) {
        setStepStatus(d.step, "error");
      }
      setPhase("upload");
    });

    es.addEventListener("cancelled", () => {
      es.close();
    });

    es.addEventListener("complete", (e) => {
      const d = JSON.parse(e.data);
      setBlogId(d.blog_id || null);
      // 处理完成兜底：把所有仍活跃的步骤统一标记为完成
      setSteps((prev) => {
        const next = { ...prev };
        STEPS.forEach((key) => {
          if (next[key]?.status === "active") {
            next[key] = { ...next[key], status: "completed", progressPct: 100 };
          }
        });
        return next;
      });
      setPhase("done");
      // Fetch stage data using the ref (avoids re-running this effect on every render)
      doneStageRef.current?.fetchStageData(taskId!);
      es.close();
    });

    es.addEventListener("error", () => {});

    return () => {
      es.close();
    };
  }, [taskId, phase]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      // Accept both video and audio files
      if (file && (file.type.startsWith("video/") || file.type.startsWith("audio/"))) {
        handleUpload(file);
      }
    },
    [handleUpload]
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
  };

  const handleExportMd = async () => {
    if (!taskId || !blogId) return;
    const res = await fetch(`${API_BASE}/api/export/md`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: taskId }),
    });
    if (res.ok) {
      const data = await res.json();
      const blob = new Blob([data.content], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename || "blog.md";
      a.click();
    }
  };

  const handleExportSrt = async () => {
    if (!taskId) return;
    const res = await fetch(`${API_BASE}/api/export/srt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: taskId }),
    });
    if (res.ok) {
      const data = await res.json();
      const blob = new Blob([data.content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename || "transcript.srt";
      a.click();
    }
  };

  const handleExportTxt = async () => {
    if (!taskId) return;
    const res = await fetch(`${API_BASE}/api/export/txt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: taskId }),
    });
    if (res.ok) {
      const data = await res.json();
      const blob = new Blob([data.content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename || "transcript.txt";
      a.click();
    }
  };

  const handleExportJson = async (stage: string) => {
    if (!taskId) return;
    const res = await fetch(`${API_BASE}/api/export/json`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: taskId, stage }),
    });
    if (res.ok) {
      const data = await res.json();
      const blob = new Blob([data.content], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename || `${stage}.json`;
      a.click();
    }
  };

  const handleDownloadAudio = () => {
    if (!doneStage.audioUrl) return;
    const a = document.createElement("a");
    a.href = doneStage.audioUrl;
    a.download = "audio.wav";
    a.click();
  };

  const handleCancel = async () => {
    if (!taskId) return;
    try {
      await fetch(`${API_BASE}/api/task/${taskId}/cancel`, { method: "POST" });
    } catch { /* ignore */ }
    if (readerRef.current) {
      readerRef.current.close();
      readerRef.current = null;
    }
    setPhase("upload");
    setTaskId(null);
  };

  const activeStep = STEPS.find((k) => steps[k]?.status === "active");
  const currentStepLabel = activeStep ? STEP_LABELS[activeStep] : "";

  const completedSteps = STEPS.filter((k) => steps[k]?.status === "completed").length;
  const overallPct = Math.round(
    (completedSteps * 100 + (activeStep ? (steps[activeStep]?.progressPct || 0) : 0)) / STEPS.length
  );

  const formatElapsed = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  // ===== ASSET LIST VIEW =====
  const renderAssetList = () => (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold">资产管理</h2>
          <p className="text-sm text-zinc-500">
            浏览、查看和管理所有已处理的内容（视频/音频/链接）
          </p>
        </div>
        <button
          onClick={() => { setView("upload"); setPhase("upload"); }}
          className="px-4 py-2 bg-sky-400 hover:bg-sky-400 rounded-lg text-sm font-medium transition-colors"
        >
          + 新建任务
        </button>
      </div>

      {/* Search & Filter */}
      <div className="flex gap-3 mb-4">
        <input
          type="text"
          placeholder="按标题或文件名搜索..."
          value={assetSearch}
          onChange={(e) => setAssetSearch(e.target.value)}
          className="flex-1 bg-zinc-50 border border-zinc-300 rounded-lg px-4 py-2 text-sm text-zinc-800 placeholder-zinc-500 focus:outline-none focus:border-sky-400"
        />
        <select
          value={assetStatusFilter}
          onChange={(e) => setAssetStatusFilter(e.target.value)}
          className="bg-zinc-50 border border-zinc-300 rounded-lg px-4 py-2 text-sm text-zinc-800 focus:outline-none focus:border-sky-400"
        >
          <option value="">全部状态</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
          <option value="cancelled">已终止</option>
          <option value="pending">等待中</option>
        </select>
        <button
          onClick={fetchVideoList}
          className="px-4 py-2 bg-zinc-200 hover:bg-zinc-300 rounded-lg text-sm transition-colors"
        >
          刷新
        </button>
      </div>

      {/* Video List */}
      {loadingAssets ? (
        <div className="text-center py-20 text-zinc-500">加载中...</div>
      ) : videoList.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-4xl mb-3 text-zinc-400">[ ]</div>
          <p className="text-zinc-500">暂无内容</p>
          <p className="text-xs text-zinc-400 mt-1">上传视频、音频或链接即可开始</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {videoList.map((v) => (
            <div
              key={v.task_id}
              className="bg-zinc-50 border border-zinc-200 rounded-lg p-4 hover:border-zinc-600 transition-colors"
            >
              <div className="flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-semibold text-zinc-800 truncate">
                      {v.title || v.filename}
                    </h3>
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[v.status] || "bg-zinc-300 text-zinc-400"}`}>
                      {STATUS_LABELS[v.status] || v.status}
                    </span>
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${SOURCE_COLORS[v.source_type] || "bg-zinc-100 text-zinc-500"}`}>
                      {SOURCE_LABELS[v.source_type] || v.source_type}
                    </span>
                    {v.has_blog && (
                      <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                        已生成博客
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-xs text-zinc-500">
                    <span>{v.filename}</span>
                    <span>时长 {formatDuration(v.duration)}</span>
                    {v.processing_duration != null && (
                      <span>处理耗时 {formatDuration(v.processing_duration)}</span>
                    )}
                    <span>{formatDate(v.created_at)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => fetchVideoDetail(v.task_id)}
                    className="px-3 py-1.5 bg-sky-400 hover:bg-sky-400 rounded-lg text-xs font-medium transition-colors"
                  >
                    详情
                  </button>
                  {v.status === "completed" || v.status === "failed" || v.status === "cancelled" ? (
                    <button
                      onClick={() => handleReprocess(v.task_id)}
                      className="px-3 py-1.5 bg-yellow-50 hover:bg-yellow-100 text-yellow-600 rounded-lg text-xs font-medium transition-colors"
                    >
                      重新处理
                    </button>
                  ) : null}
                  <button
                    onClick={() => setDeleteConfirm(v.task_id)}
                    className="px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-xs font-medium transition-colors"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ===== ASSET DETAIL VIEW =====
  const renderAssetDetail = () => {
    if (!selectedVideo) return null;
    const v = selectedVideo;

    // Export handlers for detail view (use video task_id as id)
    const detailExportHandlers = v.status === "completed" ? {
      onExportMd: async () => {
        const res = await fetch(`${API_BASE}/api/export/md`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_id: v.task_id }),
        });
        if (res.ok) {
          const data = await res.json();
          const blob = new Blob([data.content], { type: "text/markdown" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = data.filename || "blog.md";
          a.click();
        }
      },
      onExportTxt: async () => {
        const res = await fetch(`${API_BASE}/api/export/txt`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_id: v.task_id }),
        });
        if (res.ok) {
          const data = await res.json();
          const blob = new Blob([data.content], { type: "text/plain" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = data.filename || "transcript.txt";
          a.click();
        }
      },
      onExportSrt: async () => {
        const res = await fetch(`${API_BASE}/api/export/srt`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_id: v.task_id }),
        });
        if (res.ok) {
          const data = await res.json();
          const blob = new Blob([data.content], { type: "text/plain" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = data.filename || "transcript.srt";
          a.click();
        }
      },
      onExportJson: async (stage: string) => {
        const res = await fetch(`${API_BASE}/api/export/json`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_id: v.task_id, stage }),
        });
        if (res.ok) {
          const data = await res.json();
          const blob = new Blob([data.content], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = data.filename || `${stage}.json`;
          a.click();
        }
      },
      onDownloadAudio: () => {
        if (!detailStage.audioUrl) return;
        const a = document.createElement("a");
        a.href = detailStage.audioUrl;
        a.download = "audio.wav";
        a.click();
      },
    } : undefined;

    return (
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => { setSelectedVideo(null); detailStage.reset(); }}
            className="px-3 py-1.5 bg-zinc-200 hover:bg-zinc-300 rounded-lg text-sm transition-colors"
          >
            返回
          </button>
          <div className="flex-1 min-w-0">
            <h2 className="text-xl font-semibold truncate">{v.title || v.filename}</h2>
            <div className="flex items-center gap-3 text-xs text-zinc-500 mt-1">
              <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[v.status] || "bg-zinc-300 text-zinc-400"}`}>
                {STATUS_LABELS[v.status] || v.status}
              </span>
              <span>{v.filename}</span>
              <span>时长 {formatDuration(v.duration)}</span>
              {v.processing_duration != null && (
                <span>处理耗时 {formatDuration(v.processing_duration)}</span>
              )}
              <span>{formatDate(v.created_at)}</span>
            </div>
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => handleReprocess(v.task_id)}
              className="px-3 py-1.5 bg-yellow-50 hover:bg-yellow-100 text-yellow-600 rounded-lg text-xs font-medium transition-colors"
            >
              重新处理
            </button>
            <button
              onClick={() => setDeleteConfirm(v.task_id)}
              className="px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-xs font-medium transition-colors"
            >
              删除
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          {[
            { label: "转录片段", value: v.transcript_segments },
            { label: "章节数", value: v.chapters_count },
            { label: "知识点", value: v.concepts_count },
            { label: "博客", value: v.blog ? "有" : "无" },
          ].map((s) => (
            <div key={s.label} className="bg-zinc-50 border border-zinc-200 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-zinc-800">{s.value}</div>
              <div className="text-xs text-zinc-500">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Unified stage viewer with export */}
        {v.status !== "completed" ? (
          <div className="text-center py-20 text-zinc-400">
            <div className="text-4xl mb-4">⏳</div>
            <p className="text-lg">视频正在处理中...</p>
            <p className="text-sm mt-2">状态: {STATUS_LABELS[v.status] || v.status}</p>
          </div>
        ) : (
          <StageViewer
            videoId={v.task_id}
            filename={v.filename}
            duration={v.duration}
            stageData={detailStage.stageData}
            audioUrl={detailStage.audioUrl}
            activeTab={assetDetailTab}
            onTabChange={setAssetDetailTab}
            showExport={true}
            blogMarkdown={v.blog?.markdown}
            blogId={v.blog?.id}
            exportHandlers={detailExportHandlers}
            onRegenerate={v.status === "completed" ? () => { setRegenerateDialogVideoId(v.task_id); setRegeneratePresetId(presetId); } : undefined}
            regenerating={regenerating}
          />
        )}
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <header className="border-b border-zinc-200 px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-6">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Video2TechBlog</h1>
            <p className="text-xs text-zinc-500">
              将视频、音频或链接转化为可发表的文章
            </p>
          </div>
          <nav className="flex gap-1 ml-4">
            <button
              onClick={() => { setView("upload"); if (phase === "done") setPhase("upload"); }}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                view === "upload"
                  ? "bg-zinc-900 text-white"
                  : "text-zinc-500 hover:text-zinc-700 hover:bg-zinc-100"
              }`}
            >
              上传
            </button>
            <button
              onClick={() => { setView("assets"); setSelectedVideo(null); detailStage.reset(); }}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                view === "assets"
                  ? "bg-zinc-900 text-white"
                  : "text-zinc-500 hover:text-zinc-700 hover:bg-zinc-100"
              }`}
            >
              资产
            </button>
          </nav>
        </div>
        <button
          onClick={() => setShowPromptSettings(true)}
          className="p-2 hover:bg-zinc-100 rounded-lg transition-colors"
          title="提示词设置"
        >
          <svg className="w-5 h-5 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </header>

      {/* Prompt Settings Modal */}
      <PromptSettings open={showPromptSettings} onClose={() => setShowPromptSettings(false)} />
      <PresetManager
        open={showPresetManager}
        onClose={() => setShowPresetManager(false)}
        onPresetsChanged={() => window.dispatchEvent(new Event("presets-refresh"))}
      />

      {/* Regenerate dialog with preset selection */}
      {regenerateDialogVideoId && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setRegenerateDialogVideoId(null)}>
          <div className="bg-white border border-zinc-200 rounded-xl p-6 max-w-md w-full mx-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">重新生成博客</h3>
            <div className="mb-4">
              <label className="block text-sm font-medium text-zinc-700 mb-2">选择提示词预设</label>
              <PresetSelector
                value={regeneratePresetId}
                onChange={setRegeneratePresetId}
                onManageClick={() => setShowPresetManager(true)}
              />
            </div>
            <p className="text-xs text-zinc-500 mb-4">
              将使用所选预设的提示词重新生成博客，保留已有的转录、章节和知识数据。
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setRegenerateDialogVideoId(null)}
                className="px-4 py-2 bg-zinc-200 hover:bg-zinc-300 rounded-lg text-sm transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => handleRegenerate(regenerateDialogVideoId, regeneratePresetId)}
                className="px-4 py-2 bg-sky-500 hover:bg-sky-600 rounded-lg text-sm font-medium text-white transition-colors"
              >
                确认生成
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setDeleteConfirm(null)}>
          <div className="bg-white border border-zinc-200 rounded-xl p-6 max-w-md w-full mx-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-2">确认删除</h3>
            <p className="text-sm text-zinc-500 mb-1">
              此操作将永久删除以下内容：
            </p>
            <ul className="text-sm text-zinc-600 list-disc list-inside mb-4">
              <li>原始上传文件（视频/音频/链接缓存）</li>
              <li>提取的音频</li>
              <li>转录文本、章节、知识点</li>
              <li>生成的博客</li>
            </ul>
            <p className="text-xs text-zinc-400 mb-4 font-mono">{deleteConfirm}</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 bg-zinc-200 hover:bg-zinc-300 rounded-lg text-sm transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm font-medium transition-colors"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Step Sidebar (upload/processing views only) */}
        {view === "upload" && phase !== "upload" && (
          <aside className="w-72 border-r border-zinc-200 p-5 shrink-0 overflow-y-auto bg-zinc-50/50">
            <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-5">
              处理流程
            </h2>
            <ul className="relative">
              {/* Vertical connector line */}
              <div className="absolute left-[15px] top-3 bottom-3 w-px bg-zinc-200" />
              <div className="space-y-1">
                {STEPS.map((key, idx) => {
                  const s = steps[key];
                  const isActive = s?.status === "active";
                  const isCompleted = s?.status === "completed";
                  const isError = s?.status === "error";
                  const isPending = !s || s.status === "pending";

                  return (
                    <li
                      key={key}
                      className={`relative pl-10 pr-3 py-2.5 rounded-lg transition-all duration-300 ${
                        isActive ? "bg-sky-50/80" : ""
                      }`}
                    >
                      {/* Step indicator circle */}
                      <div className="absolute left-0 top-2.5 flex items-center justify-center">
                        <div
                          className={`w-[30px] h-[30px] rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 ${
                            isCompleted
                              ? "bg-emerald-500 text-white shadow-sm shadow-emerald-200"
                              : isActive
                                ? "bg-sky-400 text-white animate-pulse-ring shadow-sm shadow-sky-200"
                                : isError
                                  ? "bg-red-500 text-white shadow-sm shadow-red-200"
                                  : "bg-white border-2 border-zinc-300 text-zinc-400"
                          }`}
                        >
                          {isCompleted ? (
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          ) : isActive ? (
                            <svg className="w-4 h-4 animate-spin-slow" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                            </svg>
                          ) : isError ? (
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          ) : (
                            <span>{idx + 1}</span>
                          )}
                        </div>
                      </div>

                      {/* Step content */}
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-medium truncate ${
                            isActive ? "text-sky-600"
                            : isCompleted ? "text-zinc-500"
                            : isError ? "text-red-600"
                            : "text-zinc-400"
                          }`}>
                            {STEP_LABELS[key]}
                          </span>
                          {isActive && s.progressPct > 0 && (
                            <span className="ml-auto text-xs font-mono font-semibold text-sky-400 tabular-nums">
                              {s.progressPct}%
                            </span>
                          )}
                          {isCompleted && (
                            <span className="ml-auto text-xs font-mono font-semibold text-emerald-600 tabular-nums">
                              ✓
                            </span>
                          )}
                        </div>

                        {/* Active step detail */}
                        {isActive && s.message && (
                          <p className="text-xs text-zinc-500 mt-1 truncate">{s.message}</p>
                        )}

                        {/* Active step progress bar */}
                        {isActive && s.progressPct > 0 && (
                          <div className="mt-2 w-full bg-sky-100 rounded-full h-1.5 overflow-hidden">
                            <div
                              className="animate-shimmer h-1.5 rounded-full transition-all duration-500 ease-out"
                              style={{ width: `${s.progressPct}%` }}
                            />
                          </div>
                        )}

                        {/* Completed step detail */}
                        {isCompleted && s.message && (
                          <p className="text-xs text-emerald-600/70 mt-0.5">{s.message}</p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </div>
            </ul>
          </aside>
        )}

        {/* Content Area */}
        <main className="flex-1 overflow-y-auto p-6">
          {/* ASSETS VIEW */}
          {view === "assets" && !selectedVideo && renderAssetList()}
          {view === "assets" && selectedVideo && renderAssetDetail()}

          {/* UPLOAD VIEW */}
          {view === "upload" && phase === "upload" && (
            <div className="max-w-2xl mx-auto mt-20">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold mb-2">上传内容</h2>
                <p className="text-zinc-500">
                  支持视频文件、音频文件或媒体链接（YouTube/Bilibili 等）。
                  系统将自动转录语音，并生成可发表的博客。
                </p>
              </div>

              {/* Preset selector */}
              <div className="flex items-center justify-center gap-2 mb-4">
                <span className="text-sm text-zinc-500">提示词预设:</span>
                <PresetSelector
                  value={presetId}
                  onChange={setPresetId}
                  onManageClick={() => setShowPresetManager(true)}
                />
              </div>

              {/* Mode switcher */}
              <div className="flex justify-center gap-2 mb-6">
                <button
                  onClick={() => { setUploadMode("file"); setError(""); }}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    uploadMode === "file"
                      ? "bg-sky-400 text-white"
                      : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                  }`}
                >
                  文件上传
                </button>
                <button
                  onClick={() => { setUploadMode("url"); setError(""); }}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    uploadMode === "url"
                      ? "bg-sky-400 text-white"
                      : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                  }`}
                >
                  链接输入
                </button>
              </div>

              {uploadMode === "file" ? (
                <div
                  onDrop={handleDrop}
                  onDragOver={(e) => e.preventDefault()}
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed border-zinc-300 rounded-xl p-12 text-center cursor-pointer
                    hover:border-sky-400 hover:bg-sky-400/5 transition-colors"
                >
                  {uploading ? (
                    <div>
                      <div className="w-full bg-zinc-200 rounded-full h-2 mb-4">
                        <div
                          className="bg-sky-400 h-2 rounded-full transition-all"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                      <p className="text-zinc-400">上传中... {uploadProgress}%</p>
                    </div>
                  ) : (
                    <div>
                      <div className="text-4xl mb-3">+</div>
                      <p className="text-zinc-400">点击或拖拽视频/音频文件到此处</p>
                      <p className="text-xs text-zinc-400 mt-2">
                        支持 MP4/MOV/AVI/MKV 视频，MP3/WAV/M4A/AAC/FLAC 等音频
                      </p>
                    </div>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/*,audio/*"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                </div>
              ) : (
                <form onSubmit={handleUrlSubmit} className="space-y-4">
                  <div className="border-2 border-dashed border-zinc-300 rounded-xl p-8">
                    <label className="block text-sm font-medium text-zinc-700 mb-2">
                      媒体链接
                    </label>
                    <input
                      type="url"
                      placeholder="粘贴视频或音频链接（YouTube/Bilibili/抖音/播客 RSS 等）"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      className="w-full bg-zinc-50 border border-zinc-300 rounded-lg px-4 py-3 text-sm text-zinc-800 placeholder-zinc-500 focus:outline-none focus:border-sky-400"
                      autoFocus
                    />
                    <p className="text-xs text-zinc-400 mt-2">
                      链接将由 yt-dlp 下载音频轨道后转录。部分平台可能需要登录，详见 FAQ。
                    </p>
                  </div>
                  <button
                    type="submit"
                    disabled={urlSubmitting || !urlInput.trim()}
                    className="w-full px-4 py-3 bg-sky-400 hover:bg-sky-400 disabled:bg-zinc-300 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
                  >
                    {urlSubmitting ? "提交中..." : "开始处理"}
                  </button>
                </form>
              )}

              {error && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">
                  {error}
                </div>
              )}
            </div>
          )}

          {view === "upload" && phase === "processing" && (
            <div className="max-w-4xl mx-auto">
              {/* Header card */}
              <div className="bg-white border border-zinc-200 rounded-xl shadow-sm p-6 mb-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-sky-100 flex items-center justify-center">
                      <svg className="w-5 h-5 text-sky-400 animate-spin-slow" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                      </svg>
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-zinc-800">
                        {currentStepLabel || "准备中..."}
                      </h2>
                      {activeStep && steps[activeStep]?.message && (
                        <p className="text-sm text-zinc-500 mt-0.5">{steps[activeStep].message}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-mono text-zinc-500 bg-zinc-100 px-2.5 py-1 rounded-md">
                      {formatElapsed(elapsed)}
                    </span>
                    <button
                      onClick={handleCancel}
                      className="px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-sm font-medium transition-colors"
                    >
                      终止
                    </button>
                  </div>
                </div>

                {/* Overall progress bar */}
                <div className="w-full bg-zinc-100 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="animate-shimmer h-2.5 rounded-full transition-all duration-500 ease-out"
                    style={{ width: `${overallPct}%` }}
                  />
                </div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-xs text-zinc-500">
                    {completedSteps}/{STEPS.length} 步骤完成
                  </span>
                  <span className="text-xs font-mono font-semibold text-sky-400 tabular-nums">
                    {overallPct}%
                  </span>
                </div>
              </div>

              {/* Live transcript */}
              {transcript && (
                <section className="mb-6 animate-fade-in-up">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                    实时转录
                  </h3>
                  <div className="bg-zinc-50 border border-zinc-200 rounded-xl p-4 max-h-64 overflow-y-auto shadow-sm">
                    <pre className="text-sm text-zinc-700 whitespace-pre-wrap font-mono leading-relaxed">
                      {transcript.slice(-3000)}
                    </pre>
                  </div>
                </section>
              )}

              {/* Chapters */}
              {chapters.length > 0 && (
                <section className="mb-6 animate-fade-in-up">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    章节结构
                  </h3>
                  <div className="bg-white border border-zinc-200 rounded-xl p-4 shadow-sm">
                    <ol className="space-y-2">
                      {chapters.map((ch, i) => (
                        <li key={i} className="flex items-start gap-3 text-sm">
                          <span className="flex-none w-6 h-6 rounded-full bg-zinc-100 text-zinc-500 text-xs font-semibold flex items-center justify-center mt-0.5">
                            {i + 1}
                          </span>
                          <div>
                            <span className="font-medium text-zinc-800">{ch.title as string}</span>
                            <span className="text-zinc-400 ml-2 text-xs font-mono">
                              {ch.start_time as number}s – {ch.end_time as number}s
                            </span>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                </section>
              )}

              {/* Knowledge extraction */}
              {Object.keys(knowledge).length > 0 && (
                <section className="mb-6 animate-fade-in-up">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    知识提取
                  </h3>
                  <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                    {(
                      ["concepts", "frameworks", "methods", "tools", "papers", "code_examples", "insights"] as const
                    ).map((cat) => {
                      const items = knowledge[cat] as string[] | undefined;
                      if (!items || items.length === 0) return null;
                      return (
                        <div key={cat} className="bg-white border border-zinc-200 rounded-xl p-3 shadow-sm">
                          <h4 className="text-xs font-semibold text-zinc-500 uppercase mb-1.5">{cat}</h4>
                          <ul className="space-y-0.5">
                            {items.map((item, i) => (
                              <li key={i} className="text-sm text-zinc-700">{item}</li>
                            ))}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

              {/* Live blog output */}
              {blogMd && (
                <section className="mb-6 animate-fade-in-up">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
                    实时博客输出
                  </h3>
                  <div className="bg-white border border-zinc-200 rounded-xl p-5 max-h-[70vh] overflow-y-auto shadow-sm">
                    <MarkdownRenderer content={blogMd} />
                  </div>
                </section>
              )}
            </div>
          )}

          {view === "upload" && phase === "done" && taskId && (
            <div className="max-w-5xl mx-auto">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-semibold mb-1">处理完成</h2>
                  <p className="text-sm text-zinc-500">
                    查看并导出各阶段的结果
                  </p>
                </div>
                <button
                  onClick={() => { setPhase("upload"); setTaskId(null); doneStage.reset(); }}
                  className="px-4 py-2 bg-zinc-200 hover:bg-zinc-300 rounded-lg text-sm transition-colors"
                >
                  新建任务
                </button>
              </div>

              <StageViewer
                videoId={taskId}
                stageData={doneStage.stageData}
                audioUrl={doneStage.audioUrl}
                activeTab={activeTab}
                onTabChange={setActiveTab}
                showExport
                blogMarkdown={blogMd}
                blogId={blogId}
                exportHandlers={{
                  onExportMd: handleExportMd,
                  onExportTxt: handleExportTxt,
                  onExportSrt: handleExportSrt,
                  onExportJson: handleExportJson,
                  onDownloadAudio: handleDownloadAudio,
                }}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
