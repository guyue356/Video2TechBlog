from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str = ""

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    title: str = ""
    duration: float = 0.0
    created_at: Optional[datetime] = None

class BlogResponse(BaseModel):
    id: int
    video_id: str
    title: str
    abstract: str
    markdown: str
    html: str
    quality_score: float
    created_at: Optional[datetime] = None

class ConceptResponse(BaseModel):
    id: int
    video_id: str
    name: str
    type: str
    description: str

class TopicResponse(BaseModel):
    id: int
    video_id: str
    title: str
    summary: str
    importance_score: float

class ExportRequest(BaseModel):
    video_id: str
    stage: str = ""

class ExportResponse(BaseModel):
    filename: str
    content: str

class StageResultResponse(BaseModel):
    video_id: str
    stage: str
    data: dict

class VideoListItem(BaseModel):
    task_id: str
    title: str
    filename: str
    status: str
    duration: float
    processing_duration: Optional[float] = None
    has_blog: bool
    created_at: Optional[datetime] = None

class VideoDetailResponse(BaseModel):
    task_id: str
    title: str
    filename: str
    status: str
    duration: float
    processing_duration: Optional[float] = None
    created_at: Optional[datetime] = None
    blog: Optional[BlogResponse] = None
    transcript_segments: int = 0
    chapters_count: int = 0
    concepts_count: int = 0
