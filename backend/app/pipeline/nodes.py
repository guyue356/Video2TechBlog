import os, json, asyncio, subprocess, functools

from ..config import (
    VIDEOS_DIR, AUDIO_DIR, OUTPUT_DIR,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE,
    WHISPER_LANGUAGE, AUDIO_SAMPLE_RATE
)
from .sse_manager import sse_manager


class CancelledError(Exception):
    pass


def _run_in_thread(func, *args):
    """Run a blocking function in a thread executor (Python 3.8 compatible)."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, functools.partial(func, *args))

_whisper_model = None


_whisper_available = True
try:
    from faster_whisper import WhisperModel  # noqa
except ImportError:
    _whisper_available = False


def _get_whisper():
    global _whisper_model, _whisper_available
    if not _whisper_available:
        return None
    if _whisper_model is None:
        import os as _os
        _os.environ.setdefault("HF_HUB_OFFLINE", "0")
        try:
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE, device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )
        except Exception as e:
            print(f"WhisperModel init failed: {e}")
            _whisper_available = False
            return None
    return _whisper_model


def _llm_call_sync(messages, max_tokens=4096):
    import urllib.request
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _llm_stream_sync(messages, max_tokens=4096):
    import urllib.request
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
            except (json.JSONDecodeError, KeyError, IndexError):
                continue


def _ffmpeg_extract(video_path, audio_path, sample_rate):
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
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
                ffmpeg_path = p
                break
    if ffmpeg_path is None:
        return None, None
    ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe" if os.name == "nt" else "ffprobe")
    result = subprocess.run(
        [ffmpeg_path, "-y", "-i", str(video_path), "-vn", "-acodec", "pcm_s16le",
         "-ar", str(sample_rate), "-ac", "1", str(audio_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
    duration_out = subprocess.check_output(
        [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        text=True
    ).strip() or "0"
    return float(duration_out), audio_path


def _whisper_transcribe(audio_path, language):
    model = _get_whisper()
    if model is None:
        return None, None, None
    segments_gen, info = model.transcribe(
        audio_path, beam_size=5, language=language, vad_filter=True
    )
    transcript_parts = []
    seg_list = []
    for seg in segments_gen:
        transcript_parts.append(
            f"[{seg.start:.1f}s-{seg.end:.1f}s] {seg.text.strip()}"
        )
        seg_list.append({
            "start": seg.start, "end": seg.end, "text": seg.text.strip()
        })
    full_text = "\n".join(transcript_parts)
    return full_text, seg_list, info.language


async def extract_audio(state):
    task_id = state["task_id"]
    video_path = state["video_path"]
    await sse_manager.emit(task_id, "step_start",
        {"step": "extract_audio", "message": "Extracting audio from video..."})
    audio_filename = f"{task_id}.wav"
    audio_path = AUDIO_DIR / audio_filename
    await sse_manager.emit(task_id, "step_progress",
        {"step": "extract_audio", "progress_pct": 10, "detail": "Searching for ffmpeg..."})

    duration, extracted_path = await _run_in_thread(
        _ffmpeg_extract, video_path, audio_path, AUDIO_SAMPLE_RATE
    )

    if duration is None:
        raise RuntimeError(
            "ffmpeg not found. Please install ffmpeg: "
            "https://ffmpeg.org/download.html — "
            "Windows: download and add to PATH, or use 'winget install ffmpeg'"
        )

    await sse_manager.emit(task_id, "step_result",
        {"step": "extract_audio", "audio_path": str(audio_path), "duration": duration})
    state["audio_path"] = str(audio_path)
    state["duration"] = duration
    return state


async def transcribe(state):
    task_id = state["task_id"]
    audio_path = state["audio_path"]
    duration = state.get("duration", 0)
    # Convert empty string to None for auto language detection
    language = WHISPER_LANGUAGE if WHISPER_LANGUAGE else None
    lang_display = language.upper() if language else "Auto"
    await sse_manager.emit(task_id, "step_start",
        {"step": "transcribe",
         "message": f"Transcribing audio with Whisper ({WHISPER_DEVICE.upper()}, {WHISPER_MODEL_SIZE}, {lang_display})..."})

    # Stream segments from thread via queue for real-time progress
    seg_queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    error_holder = [None]
    lang_holder = [None]

    def _transcribe_worker():
        try:
            model = _get_whisper()
            if model is None:
                error_holder[0] = RuntimeError(
                    "Whisper model could not be loaded. "
                    "Install faster-whisper: pip install faster-whisper"
                )
                return
            segments_gen, info = model.transcribe(
                audio_path, beam_size=5, language=language, vad_filter=True
            )
            lang_holder[0] = info.language
            for seg in segments_gen:
                seg_data = {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                loop.call_soon_threadsafe(seg_queue.put_nowait, seg_data)
        except Exception as e:
            error_holder[0] = e
        finally:
            loop.call_soon_threadsafe(seg_queue.put_nowait, None)

    # Start worker thread
    worker_task = asyncio.ensure_future(_run_in_thread(_transcribe_worker))

    # Consume segments and emit progress in real-time
    transcript_parts = []
    seg_list = []
    while True:
        seg = await seg_queue.get()
        if seg is None:
            break
        transcript_parts.append(f"[{seg['start']:.1f}s-{seg['end']:.1f}s] {seg['text']}")
        seg_list.append(seg)
        # Emit progress every 10 segments
        if len(seg_list) % 10 == 0:
            pct = min(95, int(seg["end"] / duration * 100)) if duration > 0 else 50
            await sse_manager.emit(task_id, "step_progress",
                {"step": "transcribe", "progress_pct": pct,
                 "detail": f"{seg['end']:.0f}s / {duration:.0f}s"})

    # Wait for worker thread to finish
    await worker_task

    if error_holder[0] is not None:
        raise error_holder[0]

    full_text = "\n".join(transcript_parts)
    language = lang_holder[0]

    await sse_manager.emit(task_id, "step_result",
        {"step": "transcribe", "transcript": full_text,
         "segments": seg_list, "language": language,
         "progress_pct": 100, "detail": f"{len(seg_list)} segments"})
    state["transcript"] = full_text
    state["segments"] = seg_list
    return state


async def segment_chapters(state):
    task_id = state["task_id"]
    transcript = state["transcript"]
    await sse_manager.emit(task_id, "step_start",
        {"step": "segment_chapters", "message": "Identifying chapters..."})
    prompt = (
        "You are an expert technical content analyst. "
        "Below is a transcript of a technical video. "
        "Identify the logical chapter structure. For each chapter, provide:\n"
        "1. A title (concise, in Chinese)\n"
        "2. A one-sentence summary in Chinese\n"
        "3. The approximate time range (start-end seconds)\n"
        "4. An importance_score (1-10)\n\n"
        "Return ONLY valid JSON array. "
        'Example: [{"title": "Title", "summary": "Summary", '
        '"start_time": 0, "end_time": 120, "importance_score": 8}]\n\n'
        f"Transcript:\n{transcript[:30000]}"
    )
    await sse_manager.emit(task_id, "step_progress",
        {"step": "segment_chapters", "progress_pct": 50,
         "detail": "Analyzing transcript..."})
    resp = await _run_in_thread(
        _llm_call_sync, [{"role": "user", "content": prompt}]
    )
    try:
        json_str = resp.strip()
        if json_str.startswith("```"):
            json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        chapters = json.loads(json_str)
    except (json.JSONDecodeError, IndexError):
        chapters = [{
            "title": "Full Content", "summary": "Complete transcript",
            "start_time": 0, "end_time": state.get("duration", 0),
            "importance_score": 5
        }]
    await sse_manager.emit(task_id, "step_result",
        {"step": "segment_chapters", "chapters": chapters})
    state["chapters"] = chapters
    return state


async def extract_knowledge(state):
    task_id = state["task_id"]
    transcript = state["transcript"]
    await sse_manager.emit(task_id, "step_start",
        {"step": "extract_knowledge", "message": "Extracting knowledge..."})
    prompt = (
        "You are a Knowledge Reconstruction Engine. "
        "Extract structured knowledge from this technical transcript.\n"
        "Return ONLY valid JSON with these keys:\n"
        '  "concepts": [list of key technical concepts],\n'
        '  "frameworks": [list of frameworks/tools mentioned],\n'
        '  "methods": [list of methods/techniques],\n'
        '  "tools": [list of tools/libraries],\n'
        '  "papers": [list of papers referenced],\n'
        '  "code_examples": [list of code snippets or patterns],\n'
        '  "insights": [key insights or conclusions]\n'
        f"Transcript:\n{transcript[:30000]}"
    )
    await sse_manager.emit(task_id, "step_progress",
        {"step": "extract_knowledge", "progress_pct": 50,
         "detail": "Analyzing knowledge..."})
    resp = await _run_in_thread(
        _llm_call_sync, [{"role": "user", "content": prompt}]
    )
    try:
        json_str = resp.strip()
        if json_str.startswith("```"):
            json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        knowledge = json.loads(json_str)
    except (json.JSONDecodeError, IndexError):
        knowledge = {
            "concepts": [], "frameworks": [], "methods": [],
            "tools": [], "papers": [], "code_examples": [], "insights": []
        }
    await sse_manager.emit(task_id, "step_result",
        {"step": "extract_knowledge", "knowledge": knowledge})
    state["knowledge"] = knowledge
    return state


async def generate_blog(state):
    task_id = state["task_id"]
    transcript = state["transcript"]
    chapters = state.get("chapters", [])
    knowledge = state.get("knowledge", {})
    await sse_manager.emit(task_id, "step_start",
        {"step": "generate_blog", "message": "Generating technical blog..."})
    chapter_titles = "\n".join(
        [f"## {c['title']}" for c in chapters[:10]]
    )
    knowledge_str = json.dumps(knowledge, ensure_ascii=False, indent=2)[:8000]
    system_prompt = (
        "You are a senior technical writer. "
        "Write a publication-ready technical blog in Chinese. "
        "The output must be well-structured Markdown with:\n"
        "1. A compelling title (H1)\n"
        "2. An abstract/summary section\n"
        "3. Well-organized chapters based on the chapter structure provided\n"
        "4. Key technical concepts explained clearly\n"
        "5. Practical code examples where applicable\n"
        "6. A conclusion / key takeaways section\n"
        "Use proper Markdown formatting (headings, bold, code blocks, lists). "
        "Make it engaging and technically accurate."
    )
    user_prompt = (
        f"Chapter structure:\n{chapter_titles}\n\n"
        f"Extracted knowledge:\n{knowledge_str}\n\n"
        f"Full transcript:\n{transcript[:40000]}\n\n"
        "Generate the complete technical blog in Markdown format."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    # Run streaming LLM in a thread, emit SSE events from async side
    blog_md = ""
    chunk_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _stream_to_queue():
        try:
            for chunk in _llm_stream_sync(messages):
                loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)
        finally:
            loop.call_soon_threadsafe(chunk_queue.put_nowait, None)

    stream_task = asyncio.ensure_future(_run_in_thread(_stream_to_queue))

    while True:
        chunk = await chunk_queue.get()
        if chunk is None:
            break
        blog_md += chunk
        # Dynamic progress based on content length (estimate ~5000 chars for full blog)
        pct = min(95, int(len(blog_md) / 50))
        await sse_manager.emit(task_id, "step_progress",
            {"step": "generate_blog", "progress_pct": pct, "detail": chunk})

    await stream_task

    blog_title = ""
    for line in blog_md.split("\n"):
        if line.startswith("# "):
            blog_title = line[2:].strip()
            break
    await sse_manager.emit(task_id, "step_result",
        {"step": "generate_blog", "markdown": blog_md, "title": blog_title})
    state["blog_markdown"] = blog_md
    state["blog_title"] = blog_title
    return state


async def run_pipeline(task_id, video_path, on_status_change=None, is_cancelled=None):
    state = {"task_id": task_id, "video_path": video_path}
    steps = [
        (extract_audio, "extracting_audio", "extract_audio"),
        (transcribe, "transcribing", "transcribe"),
        (segment_chapters, "segmenting", "segment_chapters"),
        (extract_knowledge, "extracting_knowledge", "extract_knowledge"),
        (generate_blog, "generating_blog", "generate_blog"),
    ]
    for node, status, step_name in steps:
        if is_cancelled and is_cancelled():
            raise CancelledError(f"Task {task_id} cancelled before {step_name}")
        if on_status_change:
            await on_status_change(status)
        try:
            state = await node(state)
        except CancelledError:
            raise
        except Exception as e:
            await sse_manager.emit(task_id, "step_error",
                {"step": step_name, "message": str(e)[:500]})
            raise
    return state
