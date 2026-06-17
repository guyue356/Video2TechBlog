# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Video2TechBlog converts technical videos into publishable blog articles. Users upload a video; the system extracts audio, transcribes speech (faster-whisper), segments chapters and extracts knowledge (DeepSeek LLM), then generates a Markdown blog post with real-time SSE streaming progress.

## Commands

### One-click start (Windows)
```powershell
.\start.ps1
```
Prerequisites: Conda, Node.js, ffmpeg. Creates conda env `video2techblog` (Python 3.10) automatically.

### Manual start
```bash
# Backend (port 8000)
cd backend && conda activate video2techblog && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (port 3000)
cd frontend && npm install && npm run dev
```

### Frontend scripts
```bash
cd frontend
npm run dev      # dev server
npm run build    # production build
npm run lint     # eslint
```

## Architecture

### Monorepo layout
- `backend/` — Python FastAPI async server + SQLite database + AI pipeline
- `frontend/` — Next.js 16 (App Router) + React 19 + Tailwind CSS 4, single-page app
- `storage/` — runtime data (videos/, audio/, output/, app.db), gitignored

### Backend (`backend/app/`)

**Pipeline** (`pipeline/nodes.py`): 5 sequential async steps, NOT LangGraph despite PRD mentions:
1. `extract_audio` — ffmpeg subprocess, WAV 16kHz mono
2. `transcribe` — faster-whisper large-v3 on CPU (int8), runs in thread executor
3. `segment_chapters` — DeepSeek LLM via raw `urllib.request` HTTP (not the openai SDK)
4. `extract_knowledge` — DeepSeek LLM, returns structured JSON (concepts, frameworks, methods, tools, papers, code_examples, insights)
5. `generate_blog` — DeepSeek LLM with streaming, emits chunks as SSE events for real-time typing

Each step emits SSE events through `sse_manager` (in-memory per-task asyncio.Queue).

**Database** (`models/database.py`): SQLAlchemy async + aiosqlite. Tables: videos, transcripts, topics, concepts, blogs, stage_results. DB file: `storage/app.db`.

**API** (`main.py`): All routes in one file. Key endpoints: POST `/api/upload`, GET `/api/videos`, GET `/api/task/{id}/stream` (SSE), GET `/api/stage/{id}/{stage}`, POST `/api/export/{format}`.

**Config** (`config.py`): Hardcoded constants. LLM uses `DEEPSEEK_API_KEY` from `.env`.

### Frontend (`frontend/src/app/`)

Entire UI is a single `page.tsx` component (1300+ lines, "use client"). Two views: upload (drag-drop + SSE progress + tabbed results) and assets (video list + detail). No routing, no external state library — all useState/useRef.

`MarkdownRenderer.tsx` uses react-markdown + remark-gfm + rehype-highlight.

### Key design decisions
- LLM calls use `urllib.request` directly, not the `openai` pip package (listed in requirements but unused)
- ffmpeg is located at `D:\hsj\Github\ffmpeg\bin\ffmpeg.exe` with fallback paths in `nodes.py`
- Frontend communicates with backend at `http://localhost:8000` (hardcoded `API_BASE` in page.tsx)
- CORS configured for `http://localhost:3000` only

## Environment

`backend/.env` required:
- `DEEPSEEK_API_KEY` — DeepSeek API key (required)
- `WHISPER_LANGUAGE` — defaults to `zh`
