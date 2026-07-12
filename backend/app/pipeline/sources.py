"""Source adapters: normalize any input (video file / audio file / URL) into a
standard 16kHz mono WAV file that the downstream pipeline can consume.

This is the single convergence point for multi-source input support. The
pipeline's later stages (transcribe / segment / knowledge / blog) only depend
on the WAV file produced here and are agnostic to the original source.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

from ..config import AUDIO_DIR, AUDIO_SAMPLE_RATE, YTDLP_COOKIES_PATH
from .sse_manager import sse_manager


def _find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg executable. Reuses the same lookup order as nodes.py."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is not None:
        return ffmpeg_path
    search_paths = [
        r"D:\hsj\Github\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"D:\tools\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for p in search_paths:
        p = os.path.normpath(p)
        if os.path.exists(p):
            return p
    return None


def _ffprobe_duration(ffprobe_path: str, media_path: str) -> float:
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
            text=True,
        ).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


class SourceAdapter(ABC):
    """Base class. Each subclass knows how to turn one kind of input into a
    WAV file at ``AUDIO_DIR/{task_id}.wav``.

    Subclasses must implement :meth:`to_wav` and return
    ``(wav_path, duration_seconds, suggested_title)``.
    """

    source_type: str = "video"

    @abstractmethod
    async def to_wav(self, task_id: str) -> Tuple[Path, float, str]:
        """Produce the standard WAV file for the pipeline.

        Returns:
            (wav_path, duration_seconds, suggested_title)
        """
        raise NotImplementedError


class VideoFileAdapter(SourceAdapter):
    """Extract audio from an uploaded video file using ffmpeg -vn."""

    source_type = "video"

    def __init__(self, video_path: str):
        self.video_path = Path(video_path)

    async def to_wav(self, task_id: str) -> Tuple[Path, float, str]:
        await sse_manager.emit(task_id, "step_start", {
            "step": "extract_audio",
            "message": "Extracting audio from video...",
        })
        await sse_manager.emit(task_id, "step_progress", {
            "step": "extract_audio", "progress_pct": 10,
            "detail": "Searching for ffmpeg...",
        })

        ffmpeg_path = _find_ffmpeg()
        if ffmpeg_path is None:
            raise RuntimeError(
                "ffmpeg not found. Please install ffmpeg: "
                "https://ffmpeg.org/download.html"
            )

        audio_path = AUDIO_DIR / f"{task_id}.wav"
        result = subprocess.run(
            [ffmpeg_path, "-y", "-i", str(self.video_path), "-vn",
             "-acodec", "pcm_s16le", "-ar", str(AUDIO_SAMPLE_RATE),
             "-ac", "1", str(audio_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")

        ffprobe_path = os.path.join(
            os.path.dirname(ffmpeg_path),
            "ffprobe.exe" if os.name == "nt" else "ffprobe",
        )
        duration = _ffprobe_duration(ffprobe_path, str(audio_path))

        await sse_manager.emit(task_id, "step_result", {
            "step": "extract_audio",
            "audio_path": str(audio_path),
            "duration": duration,
        })
        return audio_path, duration, ""


class AudioFileAdapter(SourceAdapter):
    """Re-encode an uploaded audio file into the standard WAV format."""

    source_type = "audio"

    def __init__(self, audio_path: str, original_filename: str = ""):
        self.audio_path = Path(audio_path)
        self.original_filename = original_filename

    async def to_wav(self, task_id: str) -> Tuple[Path, float, str]:
        await sse_manager.emit(task_id, "step_start", {
            "step": "extract_audio",
            "message": "Normalizing audio to 16kHz mono WAV...",
        })
        await sse_manager.emit(task_id, "step_progress", {
            "step": "extract_audio", "progress_pct": 30,
            "detail": "Converting audio format...",
        })

        ffmpeg_path = _find_ffmpeg()
        if ffmpeg_path is None:
            raise RuntimeError(
                "ffmpeg not found. Please install ffmpeg: "
                "https://ffmpeg.org/download.html"
            )

        # If the raw file already meets our spec we could skip re-encoding,
        # but always re-encoding guarantees a consistent WAV container.
        wav_path = AUDIO_DIR / f"{task_id}.wav"
        result = subprocess.run(
            [ffmpeg_path, "-y", "-i", str(self.audio_path),
             "-acodec", "pcm_s16le", "-ar", str(AUDIO_SAMPLE_RATE),
             "-ac", "1", str(wav_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")

        ffprobe_path = os.path.join(
            os.path.dirname(ffmpeg_path),
            "ffprobe.exe" if os.name == "nt" else "ffprobe",
        )
        duration = _ffprobe_duration(ffprobe_path, str(wav_path))

        # Clean up the raw uploaded audio to save disk space
        try:
            if self.audio_path != wav_path and self.audio_path.exists():
                os.remove(self.audio_path)
        except OSError:
            pass

        await sse_manager.emit(task_id, "step_result", {
            "step": "extract_audio",
            "audio_path": str(wav_path),
            "duration": duration,
        })
        return wav_path, duration, ""


class UrlAdapter(SourceAdapter):
    """Download audio from a URL using yt-dlp and convert to WAV."""

    source_type = "url"

    def __init__(self, url: str, audio_only: bool = True):
        self.url = url
        self.audio_only = audio_only

    async def to_wav(self, task_id: str) -> Tuple[Path, float, str]:
        await sse_manager.emit(task_id, "step_start", {
            "step": "extract_audio",
            "message": f"Downloading from URL: {self.url}",
        })
        await sse_manager.emit(task_id, "step_progress", {
            "step": "extract_audio", "progress_pct": 20,
            "detail": "Fetching media info...",
        })

        try:
            import yt_dlp  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "yt-dlp is required for URL input. "
                "Install it with: pip install yt-dlp"
            ) from e

        wav_path = AUDIO_DIR / f"{task_id}.wav"
        raw_template = str(AUDIO_DIR / f"{task_id}_raw.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best" if self.audio_only else "best",
            "outtmpl": raw_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
            "postprocessor_args": ["-ar", str(AUDIO_SAMPLE_RATE), "-ac", "1"],
        }
        if YTDLP_COOKIES_PATH and os.path.exists(YTDLP_COOKIES_PATH):
            ydl_opts["cookiefile"] = YTDLP_COOKIES_PATH

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
        except Exception as e:
            raise RuntimeError(f"yt-dlp download failed: {str(e)[:300]}")

        title = (info.get("title") or "") if isinstance(info, dict) else ""
        duration = float(info.get("duration") or 0) if isinstance(info, dict) else 0.0

        # yt-dlp writes the final WAV to raw_template with .wav extension
        produced = AUDIO_DIR / f"{task_id}_raw.wav"
        if not produced.exists():
            # Fall back: scan for any {task_id}_raw.* produced by yt-dlp
            candidates = list(AUDIO_DIR.glob(f"{task_id}_raw.*"))
            if candidates:
                produced = candidates[0]
            else:
                raise RuntimeError(
                    "yt-dlp finished but no output file was found"
                )

        # Rename to the canonical path the pipeline expects
        if produced != wav_path:
            shutil.move(str(produced), str(wav_path))

        # Probe duration if yt-dlp didn't report it
        if duration <= 0:
            ffmpeg_path = _find_ffmpeg()
            if ffmpeg_path:
                ffprobe_path = os.path.join(
                    os.path.dirname(ffmpeg_path),
                    "ffprobe.exe" if os.name == "nt" else "ffprobe",
                )
                duration = _ffprobe_duration(ffprobe_path, str(wav_path))

        await sse_manager.emit(task_id, "step_result", {
            "step": "extract_audio",
            "audio_path": str(wav_path),
            "duration": duration,
        })
        return wav_path, duration, title


def get_adapter(source_type: str, **kwargs) -> SourceAdapter:
    """Factory: pick the right adapter by source type.

    Args:
        source_type: one of "video" / "audio" / "url"
        **kwargs: constructor arguments for the adapter
    """
    mapping = {
        "video": VideoFileAdapter,
        "audio": AudioFileAdapter,
        "url": UrlAdapter,
    }
    cls = mapping.get(source_type)
    if cls is None:
        raise ValueError(f"Unknown source_type: {source_type}")
    return cls(**kwargs)
