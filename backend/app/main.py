import asyncio, json, uuid, aiofiles, re as _re, os, time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sse_starlette.sse import EventSourceResponse

from .config import VIDEOS_DIR, AUDIO_DIR, OUTPUT_DIR
from .models.database import (
    async_session, init_db, Video, Transcript, Topic, Concept, Blog, StageResult, TaskStatus
)
from .models.schemas import (
    TaskResponse, TaskStatusResponse, BlogResponse,
    ConceptResponse, TopicResponse, ExportRequest, ExportResponse,
    StageResultResponse, VideoListItem, VideoDetailResponse
)
from .pipeline.nodes import run_pipeline, CancelledError
from .pipeline.sse_manager import sse_manager

# Track cancelled task IDs
_cancelled_tasks: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Video2TechBlog", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _run_pipeline_task(task_id: str, video_path: str):
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

            state = await run_pipeline(task_id, video_path, on_status_change=update_status, is_cancelled=is_cancelled)

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

            video.title = blog_title or video.filename
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
async def upload_video(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    task_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix or ".mp4"
    video_path = VIDEOS_DIR / f"{task_id}{ext}"
    async with aiofiles.open(video_path, "wb") as f:
        while chunk := await file.read(1024 * 1024 * 10):
            await f.write(chunk)

    async with async_session() as db:
        video = Video(id=task_id, filename=file.filename, status="pending")
        db.add(video)
        await db.commit()

    background_tasks.add_task(_run_pipeline_task, task_id, str(video_path))
    return TaskResponse(task_id=task_id, status="pending",
                        message="Video uploaded, processing started")


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

        for model in [Transcript, Topic, Concept, Blog, StageResult]:
            rows = await db.execute(select(model).where(model.video_id == video_id))
            for row in rows.scalars().all():
                await db.delete(row)

        await db.delete(video)
        await db.commit()

    for ext in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"]:
        p = VIDEOS_DIR / f"{video_id}{ext}"
        if p.exists():
            os.remove(p)

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

        video_path = None
        for ext in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"]:
            p = VIDEOS_DIR / f"{video_id}{ext}"
            if p.exists():
                video_path = str(p)
                break
        if not video_path:
            return JSONResponse({"error": "Video file not found on disk"}, status_code=404)

        for model in [Transcript, Topic, Concept, Blog, StageResult]:
            rows = await db.execute(select(model).where(model.video_id == video_id))
            for row in rows.scalars().all():
                await db.delete(row)

        video.status = TaskStatus.PENDING.value
        video.title = ""
        video.duration = 0
        await db.commit()

    background_tasks.add_task(_run_pipeline_task, video_id, video_path)
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


@app.post("/api/export/html")
async def export_html(req: ExportRequest):
    async with async_session() as db:
        result = await db.execute(
            select(Blog).where(Blog.video_id == req.video_id).order_by(Blog.id.desc())
        )
        blog = result.scalar_one_or_none()
        if not blog:
            return JSONResponse({"error": "Blog not found"}, status_code=404)
        import mistune
        html_body = blog.html or mistune.html(blog.markdown)
        html_content = (
            "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            f"<title>{blog.title or 'Blog'}</title>\n"
            "<style>body{max-width:800px;margin:0 auto;padding:2rem;"
            "font-family:system-ui,sans-serif;line-height:1.8;color:#1a1a1a;}"
            "pre{background:#f4f4f4;padding:1rem;border-radius:6px;overflow-x:auto;}"
            "code{font-family:monospace;font-size:0.9em;}"
            "img{max-width:100%%;}</style>\n</head>\n<body>\n"
            f"{html_body}\n</body>\n</html>"
        )
        filename = f"{blog.title or 'blog'}.html"
        out_path = OUTPUT_DIR / filename
        async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
            await f.write(html_content)
        return ExportResponse(filename=filename, content=html_content)


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
