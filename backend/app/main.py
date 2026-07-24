import asyncio, json, uuid, aiofiles, re as _re, os, time
from typing import Optional, Set, List, Dict
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Query, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, update
from sse_starlette.sse import EventSourceResponse

from .config import VIDEOS_DIR, AUDIO_DIR, OUTPUT_DIR
from .models.database import (
    async_session, init_db, Video, Transcript, Topic, Concept, Blog, StageResult, PromptTemplate, PromptPreset, TaskStatus
)
from .models.schemas import (
    TaskResponse, TaskStatusResponse, BlogResponse,
    ConceptResponse, TopicResponse, ExportRequest, ExportResponse,
    StageResultResponse, VideoListItem, VideoDetailResponse,
    PromptTemplateResponse, PromptUpdateRequest,
    PromptPresetResponse, PromptPresetCreateRequest, PromptPresetUpdateRequest,
    RegenerateBlogRequest,
)
from .pipeline.nodes import run_pipeline, generate_blog_only, DEFAULT_TEMPLATES, CancelledError
from .pipeline.sse_manager import sse_manager
from .pipeline.sources import (
    SourceAdapter, VideoFileAdapter, AudioFileAdapter, UrlAdapter, get_adapter
)

# Track cancelled task IDs
_cancelled_tasks: Set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Video2TechBlog", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_asr_provider(provider: Optional[str]) -> str:
    value = (provider or "whisper").strip().lower()
    return value if value in {"whisper", "mimo"} else "whisper"


def _adapter_for_video(video: Video) -> SourceAdapter:
    """Rebuild a source adapter for an uploaded, persisted task."""
    source_type = video.source_type or "video"

    if source_type == "video":
        suffix = Path(video.filename or "").suffix.lower()
        candidates = []
        if suffix:
            candidates.append(VIDEOS_DIR / f"{video.id}{suffix}")
        candidates.extend(VIDEOS_DIR.glob(f"{video.id}.*"))
        video_path = next((path for path in candidates if path.is_file()), None)
        if video_path is None:
            raise FileNotFoundError("Video file not found on disk")
        return VideoFileAdapter(str(video_path))

    if source_type == "audio":
        suffix = Path(video.filename or "").suffix.lower()
        candidates = []
        if suffix:
            candidates.append(AUDIO_DIR / f"{video.id}_raw{suffix}")
        candidates.extend(AUDIO_DIR.glob(f"{video.id}_raw.*"))
        candidates.append(AUDIO_DIR / f"{video.id}.wav")
        audio_path = next((path for path in candidates if path.is_file()), None)
        if audio_path is None:
            raise FileNotFoundError("Audio file not found on disk")
        return AudioFileAdapter(
            str(audio_path), original_filename=video.filename or ""
        )

    if source_type == "url":
        if not video.source_url:
            raise FileNotFoundError("Original URL not recorded")
        return UrlAdapter(video.source_url, audio_only=True)

    raise ValueError(f"Unknown source type: {source_type}")


async def _run_pipeline_task(task_id: str, adapter: SourceAdapter,
                            system_prompt=None, user_prompt=None,
                            asr_provider: str = "whisper"):
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == task_id))
        video = result.scalar_one_or_none()
        if not video:
            return

        async def update_status(status: str):
            video.status = status
            await db.commit()

        def is_cancelled():
            return task_id in _cancelled_tasks

        start_time = time.time()

        try:
            video.status = TaskStatus.EXTRACTING_AUDIO.value
            await db.commit()

            state = await run_pipeline(task_id, adapter, on_status_change=update_status,
                                       is_cancelled=is_cancelled,
                                       system_prompt=system_prompt, user_prompt=user_prompt,
                                       asr_provider=asr_provider)

            for seg in state.get("segments", []):
                t = Transcript(
                    video_id=task_id,
                    start_time=seg["start"],
                    end_time=seg["end"],
                    text=seg["text"],
                )
                db.add(t)

            for ch in state.get("chapters", []):
                topic = Topic(
                    video_id=task_id,
                    title=ch.get("title", ""),
                    summary=ch.get("summary", ""),
                    start_time=ch.get("start_time", 0),
                    end_time=ch.get("end_time", 0),
                    importance_score=ch.get("importance_score", 5),
                )
                db.add(topic)

            knowledge = state.get("knowledge", {})
            for concept_type in ["concepts", "frameworks", "methods", "tools",
                                 "papers", "code_examples", "insights"]:
                for item in knowledge.get(concept_type, []):
                    c = Concept(
                        video_id=task_id,
                        name=item if isinstance(item, str) else str(item),
                        type=concept_type,
                    )
                    db.add(c)

            # Persist full stage results as JSON blobs
            stage_results = [
                ("audio", {
                    "audio_path": state.get("audio_path", ""),
                    "duration": state.get("duration", 0),
                }),
                ("transcript", {
                    "asr_provider": state.get("asr_provider", "whisper"),
                    "transcript": state.get("transcript", ""),
                    "segments": state.get("segments", []),
                }),
                ("chapters", {
                    "chapters": state.get("chapters", []),
                }),
                ("knowledge", state.get("knowledge", {})),
            ]

            blog_md = state.get("blog_markdown", "")
            blog_title = state.get("blog_title", "")

            abstract = ""
            for line in blog_md.split("\n"):
                clean = line.strip()
                if clean and not clean.startswith("#") and len(clean) > 20:
                    abstract = clean[:200]
                    break

            import mistune
            blog_html = mistune.html(blog_md)

            blog = Blog(
                video_id=task_id,
                title=blog_title,
                abstract=abstract,
                markdown=blog_md,
                html=blog_html,
            )
            db.add(blog)

            stage_results.append(("blog", {
                "markdown": blog_md,
                "title": blog_title,
                "html": blog_html,
            }))

            # If the adapter supplied a title (e.g. yt-dlp video title) and the
            # blog generation didn't produce one, fall back to it.
            suggested = state.get("suggested_title", "")
            final_title = blog_title or video.title or suggested or video.filename
            video.title = final_title
            video.duration = state.get("duration", 0)
            video.processing_duration = time.time() - start_time
            video.status = TaskStatus.COMPLETED.value
            await db.commit()

            # Persist stage results in a separate session to isolate failures
            try:
                async with async_session() as db2:
                    for stage_name, stage_data in stage_results:
                        sr = StageResult(
                            video_id=task_id,
                            stage=stage_name,
                            data_json=json.dumps(stage_data, ensure_ascii=False),
                        )
                        db2.add(sr)
                    await db2.commit()
            except Exception:
                pass

            await sse_manager.emit(task_id, "complete", {"blog_id": blog.id if blog else 0})

        except CancelledError:
            video.processing_duration = time.time() - start_time
            video.status = TaskStatus.CANCELLED.value
            await db.commit()
            await sse_manager.emit(task_id, "cancelled",
                {"message": "Task cancelled by user"})
        except Exception as e:
            video.processing_duration = time.time() - start_time
            video.status = TaskStatus.FAILED.value
            await db.commit()
            await sse_manager.emit(task_id, "step_error",
                {"step": "pipeline", "message": str(e)[:500]})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...),
                      preset_id: Optional[int] = Form(None)):
    """Unified upload endpoint for both video and audio files.

    Detects the source type from the file's content type and routes to the
    appropriate adapter. Video files are stored under VIDEOS_DIR; audio files
    under AUDIO_DIR with a ``_raw`` suffix until normalized to WAV.
    """
    task_id = str(uuid.uuid4())
    content_type = (file.content_type or "").lower()
    filename = file.filename or "upload"

    # Decide source type from MIME prefix
    if content_type.startswith("audio/") or _has_audio_ext(filename):
        source_type = "audio"
        ext = Path(filename).suffix.lower() or ".wav"
        raw_path = AUDIO_DIR / f"{task_id}_raw{ext}"
        save_path = raw_path
    else:
        # Default to video for video/* or unknown content types (backward compat)
        source_type = "video"
        ext = Path(filename).suffix.lower() or ".mp4"
        save_path = VIDEOS_DIR / f"{task_id}{ext}"

    async with aiofiles.open(save_path, "wb") as f:
        while chunk := await file.read(1024 * 1024 * 10):
            await f.write(chunk)

    async with async_session() as db:
        video = Video(
            id=task_id,
            filename=filename,
            status="pending",
            source_type=source_type,
            preset_id=preset_id,
        )
        db.add(video)
        await db.commit()

    return TaskResponse(task_id=task_id, status="pending",
                        message=f"{source_type.capitalize()} uploaded, waiting to start")


def _has_audio_ext(filename: str) -> bool:
    """Heuristic: treat common audio extensions as audio even if the browser
    reports a generic content type."""
    audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma",
                  ".opus", ".aiff", ".aif"}
    return Path(filename).suffix.lower() in audio_exts


from pydantic import BaseModel, HttpUrl  # noqa: E402

class UrlUploadRequest(BaseModel):
    url: HttpUrl
    audio_only: bool = True
    preset_id: Optional[int] = None

@app.post("/api/upload/url")
async def upload_url(req: UrlUploadRequest = Body(...)):
    """Save a URL (YouTube/Bilibili/etc.) as a task that can be started later."""
    task_id = str(uuid.uuid4())
    url = str(req.url)

    async with async_session() as db:
        video = Video(
            id=task_id,
            filename=url,
            status="pending",
            source_type="url",
            source_url=url,
            preset_id=req.preset_id,
        )
        db.add(video)
        await db.commit()

    return TaskResponse(task_id=task_id, status="pending",
                        message="URL submitted, waiting to start")


class StartTaskRequest(BaseModel):
    asr_provider: str = "whisper"


@app.post("/api/task/{task_id}/start")
async def start_task(task_id: str, req: StartTaskRequest = Body(...),
                     background_tasks: BackgroundTasks = None):
    """Start a previously uploaded task exactly once."""
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == task_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        if video.status != TaskStatus.PENDING.value:
            return JSONResponse(
                {"error": f"Task cannot be started from status: {video.status}"},
                status_code=409,
            )

        try:
            adapter = _adapter_for_video(video)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        claimed = await db.execute(
            update(Video)
            .where(Video.id == task_id, Video.status == TaskStatus.PENDING.value)
            .values(
                status=TaskStatus.EXTRACTING_AUDIO.value,
                processing_duration=None,
            )
        )
        if claimed.rowcount != 1:
            await db.rollback()
            return JSONResponse({"error": "Task has already been started"}, status_code=409)
        await db.commit()
        preset_id = video.preset_id

    _cancelled_tasks.discard(task_id)
    sse_manager.remove(task_id)
    sse_manager.get_queue(task_id)
    system_prompt, user_prompt = await _resolve_preset_prompts(preset_id)
    asr_provider = _normalize_asr_provider(req.asr_provider)
    background_tasks.add_task(
        _run_pipeline_task, task_id, adapter, system_prompt, user_prompt, asr_provider
    )
    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.EXTRACTING_AUDIO.value,
        message="Processing started",
    )


@app.post("/api/task/{task_id}/cancel")
async def cancel_task(task_id: str):
    _cancelled_tasks.add(task_id)
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == task_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        video.status = TaskStatus.CANCELLED.value
        await db.commit()
    return {"ok": True, "task_id": task_id, "status": "cancelled"}


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == task_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        return TaskStatusResponse(
            task_id=video.id, status=video.status,
            title=video.title, duration=video.duration,
            created_at=video.created_at
        )


@app.get("/api/task/{task_id}/stream")
async def task_stream(task_id: str):
    queue = sse_manager.get_queue(task_id)

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"], ensure_ascii=False)
                }
                if event["event"] in ("complete", "step_error"):
                    break
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}

    return EventSourceResponse(event_generator())


@app.get("/api/task/{task_id}/events")
async def get_task_events(task_id: str):
    events = sse_manager.get_events(task_id)
    return {"task_id": task_id, "events": events}


@app.get("/api/videos")
async def list_videos(
    search: str = Query("", description="Search by title or filename"),
    status: str = Query("", description="Filter by status"),
):
    async with async_session() as db:
        q = select(Video).order_by(Video.created_at.desc())
        if status:
            q = q.where(Video.status == status)
        result = await db.execute(q)
        videos = result.scalars().all()

        items = []
        for v in videos:
            if search and search.lower() not in (v.title or "").lower() and search.lower() not in (v.filename or "").lower():
                continue
            blog_result = await db.execute(
                select(func.count(Blog.id)).where(Blog.video_id == v.id)
            )
            has_blog = (blog_result.scalar() or 0) > 0
            items.append(VideoListItem(
                task_id=v.id, title=v.title or v.filename,
                filename=v.filename, status=v.status,
                duration=v.duration, processing_duration=v.processing_duration,
                has_blog=has_blog,
                source_type=v.source_type or "video",
                source_url=v.source_url or "",
                created_at=v.created_at,
            ))
        return items


@app.get("/api/videos/{video_id}")
async def get_video_detail(video_id: str):
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == video_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Video not found"}, status_code=404)

        blog_result = await db.execute(
            select(Blog).where(Blog.video_id == video_id).order_by(Blog.id.desc())
        )
        blog = blog_result.scalar_one_or_none()
        blog_resp = None
        if blog:
            blog_resp = BlogResponse(
                id=blog.id, video_id=blog.video_id, title=blog.title,
                abstract=blog.abstract, markdown=blog.markdown,
                html=blog.html, quality_score=blog.quality_score,
                created_at=blog.created_at,
            )

        seg_count = (await db.execute(
            select(func.count(Transcript.id)).where(Transcript.video_id == video_id)
        )).scalar() or 0

        ch_count = (await db.execute(
            select(func.count(Topic.id)).where(Topic.video_id == video_id)
        )).scalar() or 0

        conc_count = (await db.execute(
            select(func.count(Concept.id)).where(Concept.video_id == video_id)
        )).scalar() or 0

        return VideoDetailResponse(
            task_id=video.id, title=video.title or video.filename,
            filename=video.filename, status=video.status,
            duration=video.duration, processing_duration=video.processing_duration,
            source_type=video.source_type or "video",
            source_url=video.source_url or "",
            created_at=video.created_at,
            blog=blog_resp, transcript_segments=seg_count,
            chapters_count=ch_count, concepts_count=conc_count,
        )


@app.delete("/api/videos/{video_id}")
async def delete_video(video_id: str):
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == video_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Video not found"}, status_code=404)

        source_type = video.source_type or "video"
        source_url = video.source_url or ""

        for model in [Transcript, Topic, Concept, Blog, StageResult]:
            rows = await db.execute(select(model).where(model.video_id == video_id))
            for row in rows.scalars().all():
                await db.delete(row)

        await db.delete(video)
        await db.commit()

    # Clean up source files based on source type
    video_exts = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"]
    audio_raw_exts = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma",
                      ".opus", ".aiff", ".aif"]

    if source_type == "video":
        for ext in video_exts:
            p = VIDEOS_DIR / f"{video_id}{ext}"
            if p.exists():
                os.remove(p)
    elif source_type == "audio":
        # Raw uploaded audio files are stored with _raw suffix
        for ext in audio_raw_exts:
            p = AUDIO_DIR / f"{video_id}_raw{ext}"
            if p.exists():
                os.remove(p)
    # URL source: no raw file to clean (yt-dlp output already renamed to {id}.wav)

    # Always clean the normalized WAV
    audio_path = AUDIO_DIR / f"{video_id}.wav"
    if audio_path.exists():
        os.remove(audio_path)

    return {"ok": True, "deleted": video_id}


@app.post("/api/videos/{video_id}/reprocess")
async def reprocess_video(video_id: str, background_tasks: BackgroundTasks = None):
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == video_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Video not found"}, status_code=404)

        source_type = video.source_type or "video"
        source_url = video.source_url or ""

        # Reconstruct the adapter from the stored source info
        adapter: SourceAdapter
        if source_type == "video":
            video_path = None
            for ext in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"]:
                p = VIDEOS_DIR / f"{video_id}{ext}"
                if p.exists():
                    video_path = str(p)
                    break
            if not video_path:
                return JSONResponse({"error": "Video file not found on disk"}, status_code=404)
            adapter = VideoFileAdapter(video_path)
        elif source_type == "audio":
            # Original raw audio may have been deleted after normalization;
            # reuse the normalized WAV if available, otherwise fail gracefully.
            wav_path = AUDIO_DIR / f"{video_id}.wav"
            if not wav_path.exists():
                return JSONResponse({"error": "Audio file not found on disk"}, status_code=404)
            adapter = AudioFileAdapter(str(wav_path), original_filename=video.filename or "")
        elif source_type == "url":
            if not source_url:
                return JSONResponse({"error": "Original URL not recorded"}, status_code=404)
            adapter = UrlAdapter(source_url, audio_only=True)
        else:
            return JSONResponse({"error": f"Unknown source type: {source_type}"}, status_code=400)

        for model in [Transcript, Topic, Concept, Blog, StageResult]:
            rows = await db.execute(select(model).where(model.video_id == video_id))
            for row in rows.scalars().all():
                await db.delete(row)

        video.status = TaskStatus.PENDING.value
        video.title = ""
        video.duration = 0
        await db.commit()

    background_tasks.add_task(_run_pipeline_task, video_id, adapter)
    return TaskResponse(task_id=video_id, status="pending",
                        message="Re-processing started")


@app.get("/api/blog/{video_id}")
async def get_blog(video_id: str):
    async with async_session() as db:
        result = await db.execute(
            select(Blog).where(Blog.video_id == video_id).order_by(Blog.id.desc())
        )
        blog = result.scalar_one_or_none()
        if not blog:
            return JSONResponse({"error": "Blog not found"}, status_code=404)
        return BlogResponse(
            id=blog.id, video_id=blog.video_id, title=blog.title,
            abstract=blog.abstract, markdown=blog.markdown,
            html=blog.html, quality_score=blog.quality_score,
            created_at=blog.created_at
        )


# ─── Prompt Template APIs ─────────────────────────────────────────────────────

@app.get("/api/prompts", response_model=List[PromptTemplateResponse])
async def get_prompt_templates():
    """List all prompt templates (DB entries merged with defaults)."""
    templates: Dict[str, PromptTemplateResponse] = {}

    # Fill defaults first
    for tid, tdef in DEFAULT_TEMPLATES.items():
        templates[tid] = PromptTemplateResponse(
            id=tid, name=tdef["name"],
            template=tdef["template"], description=tdef["description"],
        )

    # Override with DB entries
    async with async_session() as db:
        result = await db.execute(select(PromptTemplate))
        for row in result.scalars().all():
            templates[row.id] = PromptTemplateResponse(
                id=row.id, name=row.name or row.id,
                template=row.template, description=row.description or "",
            )

    return list(templates.values())


@app.get("/api/prompts/{template_id}", response_model=PromptTemplateResponse)
async def get_prompt_template(template_id: str):
    """Get a single prompt template."""
    async with async_session() as db:
        result = await db.execute(
            select(PromptTemplate).where(PromptTemplate.id == template_id)
        )
        row = result.scalar_one_or_none()
        if row:
            return PromptTemplateResponse(
                id=row.id, name=row.name or row.id,
                template=row.template, description=row.description or "",
            )

    # Fallback to defaults
    default = DEFAULT_TEMPLATES.get(template_id)
    if not default:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    return PromptTemplateResponse(
        id=template_id, name=default["name"],
        template=default["template"], description=default["description"],
    )


@app.put("/api/prompts/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(template_id: str, req: PromptUpdateRequest):
    """Create or update a prompt template."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(
            select(PromptTemplate).where(PromptTemplate.id == template_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.template = req.template
            row.updated_at = now
        else:
            # Use default metadata if available
            default = DEFAULT_TEMPLATES.get(template_id, {})
            row = PromptTemplate(
                id=template_id,
                name=default.get("name", template_id),
                description=default.get("description", ""),
                template=req.template,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        await db.commit()
        await db.refresh(row)

    return PromptTemplateResponse(
        id=row.id, name=row.name,
        template=row.template, description=row.description,
    )


# ─── Blog Regeneration API ────────────────────────────────────────────────────


# ─── Prompt Presets CRUD ─────────────────────────────────────────────────────

@app.get("/api/presets", response_model=List[PromptPresetResponse])
async def list_presets():
    """List all prompt presets."""
    async with async_session() as db:
        result = await db.execute(select(PromptPreset).order_by(PromptPreset.id))
        rows = result.scalars().all()
        return [
            PromptPresetResponse(
                id=r.id, name=r.name, description=r.description,
                system_prompt=r.system_prompt, user_prompt=r.user_prompt,
                is_default=r.is_default,
                created_at=r.created_at, updated_at=r.updated_at,
            ) for r in rows
        ]


@app.post("/api/presets", response_model=PromptPresetResponse)
async def create_preset(req: PromptPresetCreateRequest):
    """Create a new prompt preset."""
    async with async_session() as db:
        # If marking as default, clear other defaults first
        if req.is_default:
            await db.execute(
                PromptPreset.__table__.update().where(PromptPreset.is_default == True).values(is_default=False)
            )
        preset = PromptPreset(
            name=req.name, description=req.description,
            system_prompt=req.system_prompt, user_prompt=req.user_prompt,
            is_default=req.is_default,
        )
        db.add(preset)
        await db.commit()
        await db.refresh(preset)
        return PromptPresetResponse(
            id=preset.id, name=preset.name, description=preset.description,
            system_prompt=preset.system_prompt, user_prompt=preset.user_prompt,
            is_default=preset.is_default,
            created_at=preset.created_at, updated_at=preset.updated_at,
        )


@app.put("/api/presets/{preset_id}", response_model=PromptPresetResponse)
async def update_preset(preset_id: int, req: PromptPresetUpdateRequest):
    """Update a prompt preset."""
    async with async_session() as db:
        result = await db.execute(select(PromptPreset).where(PromptPreset.id == preset_id))
        preset = result.scalar_one_or_none()
        if not preset:
            return JSONResponse({"error": "Preset not found"}, status_code=404)
        if req.name is not None:
            preset.name = req.name
        if req.description is not None:
            preset.description = req.description
        if req.system_prompt is not None:
            preset.system_prompt = req.system_prompt
        if req.user_prompt is not None:
            preset.user_prompt = req.user_prompt
        if req.is_default is not None:
            if req.is_default:
                await db.execute(
                    PromptPreset.__table__.update().where(PromptPreset.is_default == True).values(is_default=False)
                )
            preset.is_default = req.is_default
        preset.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(preset)
        return PromptPresetResponse(
            id=preset.id, name=preset.name, description=preset.description,
            system_prompt=preset.system_prompt, user_prompt=preset.user_prompt,
            is_default=preset.is_default,
            created_at=preset.created_at, updated_at=preset.updated_at,
        )


@app.delete("/api/presets/{preset_id}")
async def delete_preset(preset_id: int):
    """Delete a prompt preset. Cannot delete the current default."""
    async with async_session() as db:
        result = await db.execute(select(PromptPreset).where(PromptPreset.id == preset_id))
        preset = result.scalar_one_or_none()
        if not preset:
            return JSONResponse({"error": "Preset not found"}, status_code=404)
        if preset.is_default:
            return JSONResponse({"error": "Cannot delete the default preset"}, status_code=400)
        await db.delete(preset)
        await db.commit()
        return {"ok": True}

async def _resolve_preset_prompts(preset_id):
    """Load system_prompt and user_prompt from a preset ID. Returns (None, None) if not found."""
    if preset_id is None:
        return None, None
    async with async_session() as db:
        result = await db.execute(select(PromptPreset).where(PromptPreset.id == preset_id))
        preset = result.scalar_one_or_none()
        if not preset:
            return None, None
        return preset.system_prompt, preset.user_prompt


async def _regenerate_blog_task(video_id: str, system_prompt=None, user_prompt=None):
    """Background task: regenerate blog from existing stage results."""
    import mistune
    async with async_session() as db:
        # Load existing stage results
        sr_result = await db.execute(
            select(StageResult).where(StageResult.video_id == video_id)
            .order_by(StageResult.id.desc())
        )
        stage_map: Dict[str, StageResult] = {}
        for sr in sr_result.scalars().all():
            if sr.stage not in stage_map:
                stage_map[sr.stage] = sr

        transcript_sr = stage_map.get("transcript")
        chapters_sr = stage_map.get("chapters")
        knowledge_sr = stage_map.get("knowledge")

        if not transcript_sr:
            return

        transcript_data = json.loads(transcript_sr.data_json)
        transcript = transcript_data.get("transcript", "")
        chapters_data = json.loads(chapters_sr.data_json) if chapters_sr else {}
        chapters = chapters_data.get("chapters", [])
        knowledge = json.loads(knowledge_sr.data_json) if knowledge_sr else {}

        # Update video status
        result = await db.execute(select(Video).where(Video.id == video_id))
        video = result.scalar_one_or_none()
        if not video:
            return
        video.status = TaskStatus.GENERATING_BLOG.value
        await db.commit()

    try:
        state = await generate_blog_only(video_id, transcript, chapters, knowledge,
                                        system_prompt=system_prompt, user_prompt=user_prompt)
        blog_md = state.get("blog_markdown", "")
        blog_title = state.get("blog_title", "")

        abstract = ""
        for line in blog_md.split("\n"):
            clean = line.strip()
            if clean and not clean.startswith("#") and len(clean) > 20:
                abstract = clean[:200]
                break

        blog_html = mistune.html(blog_md)

        async with async_session() as db:
            # Delete old blog entries for this video
            old_blogs = await db.execute(select(Blog).where(Blog.video_id == video_id))
            for old in old_blogs.scalars().all():
                await db.delete(old)

            blog = Blog(
                video_id=video_id, title=blog_title, abstract=abstract,
                markdown=blog_md, html=blog_html,
            )
            db.add(blog)

            # Update stage_results blog entry
            old_blog_sr = await db.execute(
                select(StageResult).where(
                    StageResult.video_id == video_id,
                    StageResult.stage == "blog",
                )
            )
            for old_sr in old_blog_sr.scalars().all():
                await db.delete(old_sr)

            sr = StageResult(
                video_id=video_id, stage="blog",
                data_json=json.dumps({
                    "markdown": blog_md, "title": blog_title, "html": blog_html,
                }, ensure_ascii=False),
            )
            db.add(sr)

            result = await db.execute(select(Video).where(Video.id == video_id))
            video = result.scalar_one_or_none()
            if video:
                video.title = blog_title or video.title
                video.status = TaskStatus.COMPLETED.value
            await db.commit()

        await sse_manager.emit(video_id, "complete", {"blog_id": blog.id if blog else 0})

    except Exception as e:
        async with async_session() as db:
            result = await db.execute(select(Video).where(Video.id == video_id))
            video = result.scalar_one_or_none()
            if video:
                video.status = TaskStatus.FAILED.value
                await db.commit()
        await sse_manager.emit(video_id, "step_error",
            {"step": "generate_blog", "message": str(e)[:500]})


@app.post("/api/videos/{video_id}/regenerate-blog")
async def regenerate_blog(video_id: str, background_tasks: BackgroundTasks, req: Optional[RegenerateBlogRequest] = None):
    """Regenerate ONLY the blog post from existing transcript/chapters/knowledge."""
    async with async_session() as db:
        result = await db.execute(select(Video).where(Video.id == video_id))
        video = result.scalar_one_or_none()
        if not video:
            return JSONResponse({"error": "Video not found"}, status_code=404)

        # Check that stage results exist
        sr_result = await db.execute(
            select(StageResult).where(
                StageResult.video_id == video_id,
                StageResult.stage == "transcript",
            )
        )
        if not sr_result.scalar_one_or_none():
            return JSONResponse({"error": "No transcript found. Run full pipeline first."}, status_code=400)

        video.status = TaskStatus.GENERATING_BLOG.value
        await db.commit()

    # Resolve preset prompts
    preset_id = req.preset_id if req else None
    system_prompt, user_prompt = await _resolve_preset_prompts(preset_id)
    background_tasks.add_task(_regenerate_blog_task, video_id, system_prompt, user_prompt)
    return TaskResponse(task_id=video_id, status="generating_blog",
                        message="Blog regeneration started")


@app.post("/api/export/md")
async def export_markdown(req: ExportRequest):
    async with async_session() as db:
        result = await db.execute(
            select(Blog).where(Blog.video_id == req.video_id).order_by(Blog.id.desc())
        )
        blog = result.scalar_one_or_none()
        if not blog:
            return JSONResponse({"error": "Blog not found"}, status_code=404)
        filename = f"{blog.title or 'blog'}.md"
        out_path = OUTPUT_DIR / filename
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            await f.write(blog.markdown)
        return ExportResponse(filename=filename, content=blog.markdown)


@app.get("/api/concepts")
async def get_concepts(video_id: str = ""):
    async with async_session() as db:
        q = select(Concept)
        if video_id:
            q = q.where(Concept.video_id == video_id)
        result = await db.execute(q)
        concepts = result.scalars().all()
        return [
            ConceptResponse(id=c.id, video_id=c.video_id, name=c.name,
                           type=c.type, description=c.description or "")
            for c in concepts
        ]


@app.get("/api/topics")
async def get_topics(video_id: str = ""):
    async with async_session() as db:
        q = select(Topic)
        if video_id:
            q = q.where(Topic.video_id == video_id)
        result = await db.execute(q)
        topics = result.scalars().all()
        return [
            TopicResponse(id=t.id, video_id=t.video_id, title=t.title,
                         summary=t.summary, importance_score=t.importance_score)
            for t in topics
        ]


@app.get("/api/stage/{video_id}/{stage}")
async def get_stage_result(video_id: str, stage: str):
    async with async_session() as db:
        result = await db.execute(
            select(StageResult).where(
                StageResult.video_id == video_id,
                StageResult.stage == stage,
            ).order_by(StageResult.id.desc())
        )
        sr = result.scalar_one_or_none()
        if not sr:
            return JSONResponse({"error": "Stage result not found"}, status_code=404)
        data = json.loads(sr.data_json)
        return StageResultResponse(video_id=video_id, stage=stage, data=data)


@app.get("/api/transcripts/{video_id}")
async def get_transcripts(video_id: str):
    async with async_session() as db:
        result = await db.execute(
            select(Transcript).where(Transcript.video_id == video_id)
            .order_by(Transcript.start_time)
        )
        segments = result.scalars().all()
        return [
            {"id": s.id, "video_id": s.video_id, "start_time": s.start_time,
             "end_time": s.end_time, "text": s.text, "speaker": s.speaker}
            for s in segments
        ]


@app.get("/api/audio/{video_id}")
async def serve_audio(video_id: str):
    audio_path = AUDIO_DIR / f"{video_id}.wav"
    if not audio_path.exists():
        return JSONResponse({"error": "Audio not found"}, status_code=404)
    return FileResponse(str(audio_path), media_type="audio/wav",
                        filename=f"{video_id}.wav")


@app.get("/api/video/{video_id}")
async def serve_video(video_id: str):
    """Serve the original video file."""
    # Find video file with any common extension
    for ext in [".mp4", ".mkv", ".avi", ".mov", ".webm"]:
        video_path = VIDEOS_DIR / f"{video_id}{ext}"
        if video_path.exists():
            media_type = {
                ".mp4": "video/mp4",
                ".mkv": "video/x-matroska",
                ".avi": "video/x-msvideo",
                ".mov": "video/quicktime",
                ".webm": "video/webm",
            }.get(ext, "video/mp4")
            return FileResponse(str(video_path), media_type=media_type,
                                filename=f"{video_id}{ext}")
    return JSONResponse({"error": "Video not found"}, status_code=404)


@app.post("/api/export/srt")
async def export_srt(req: ExportRequest):
    async with async_session() as db:
        result = await db.execute(
            select(Transcript).where(Transcript.video_id == req.video_id)
            .order_by(Transcript.start_time)
        )
        segments = result.scalars().all()
        if not segments:
            return JSONResponse({"error": "No transcript found"}, status_code=404)

        def fmt_ts(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        lines = []
        for i, seg in enumerate(segments, 1):
            lines.append(str(i))
            lines.append(f"{fmt_ts(seg.start_time)} --> {fmt_ts(seg.end_time)}")
            lines.append(seg.text)
            lines.append("")
        content = "\n".join(lines)
        filename = f"{req.video_id}_transcript.srt"
        out_path = OUTPUT_DIR / filename
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return ExportResponse(filename=filename, content=content)


@app.post("/api/export/txt")
async def export_txt(req: ExportRequest):
    async with async_session() as db:
        result = await db.execute(
            select(Transcript).where(Transcript.video_id == req.video_id)
            .order_by(Transcript.start_time)
        )
        segments = result.scalars().all()
        if not segments:
            return JSONResponse({"error": "No transcript found"}, status_code=404)

        lines = []
        for seg in segments:
            lines.append(f"[{seg.start_time:.1f}s-{seg.end_time:.1f}s] {seg.text}")
        content = "\n".join(lines)
        filename = f"{req.video_id}_transcript.txt"
        out_path = OUTPUT_DIR / filename
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return ExportResponse(filename=filename, content=content)


@app.post("/api/export/json")
async def export_json(req: ExportRequest):
    async with async_session() as db:
        q = select(StageResult).where(StageResult.video_id == req.video_id)
        if req.stage:
            q = q.where(StageResult.stage == req.stage)
        result = await db.execute(q.order_by(StageResult.id.desc()))
        sr = result.scalar_one_or_none()
        if not sr:
            return JSONResponse({"error": "No data found"}, status_code=404)
        content = sr.data_json
        filename = f"{req.video_id}_{sr.stage}.json"
        out_path = OUTPUT_DIR / filename
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return ExportResponse(filename=filename, content=content)
