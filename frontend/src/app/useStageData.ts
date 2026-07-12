"use client";

import { useState, useCallback, useEffect, useRef } from "react";

const API_BASE = "http://localhost:8001";

export type TabKey = "video" | "audio" | "transcript" | "chapters" | "knowledge" | "blog";

export const TAB_LABELS: Record<TabKey, string> = {
  video: "视频",
  audio: "音频",
  transcript: "转录",
  chapters: "章节",
  knowledge: "知识",
  blog: "博客",
};

export const TAB_ICONS: Record<TabKey, string> = {
  video: "🎬",
  audio: "♫",
  transcript: "✎",
  chapters: "☰",
  knowledge: "★",
  blog: "✍",
};

const STAGE_KEYS: TabKey[] = ["audio", "transcript", "chapters", "knowledge"];

export interface StageDataState {
  stageData: Record<string, Record<string, unknown>>;
  audioUrl: string | null;
  loading: boolean;
}

/**
 * Unified hook for fetching stage data (audio, transcript, chapters, knowledge)
 * and audio blob for a given video ID.
 *
 * Used by both the "done" phase viewer and the asset detail view.
 */
export function useStageData() {
  const [stageData, setStageData] = useState<Record<string, Record<string, unknown>>>({});
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const blobUrlRef = useRef<string | null>(null);

  // Clean up blob URL on unmount
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, []);

  const fetchStageData = useCallback(async (videoId: string) => {
    setLoading(true);
    setStageData({});
    setAudioUrl(null);
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }

    // Fetch all stages in parallel
    const promises = STAGE_KEYS.map((stage) =>
      fetch(`${API_BASE}/api/stage/${videoId}/${stage}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => ({ stage, data: d?.data ?? null }))
        .catch(() => ({ stage, data: null }))
    );

    // Fetch audio blob
    const audioPromise = fetch(`${API_BASE}/api/audio/${videoId}`)
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          blobUrlRef.current = url;
          return url;
        }
        return null;
      })
      .catch(() => null);

    const [results, aUrl] = await Promise.all([Promise.all(promises), audioPromise]);

    const newStageData: Record<string, Record<string, unknown>> = {};
    for (const { stage, data } of results) {
      if (data) newStageData[stage] = data;
    }

    setStageData(newStageData);
    setAudioUrl(aUrl);
    setLoading(false);
  }, []);

  const reset = useCallback(() => {
    setStageData({});
    setAudioUrl(null);
    setLoading(false);
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
  }, []);

  return { stageData, audioUrl, loading, fetchStageData, reset, setStageData, setAudioUrl };
}
