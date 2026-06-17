from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey, text
from datetime import datetime, timezone
import enum
from ..config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    EXTRACTING_KNOWLEDGE = "extracting_knowledge"
    GENERATING_BLOG = "generating_blog"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Video(Base):
    __tablename__ = "videos"
    id = Column(String(36), primary_key=True)
    title = Column(String(512), default="")
    filename = Column(String(512), default="")
    duration = Column(Float, default=0.0)
    processing_duration = Column(Float, nullable=True)
    status = Column(String(32), default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False)
    start_time = Column(Float, default=0.0)
    end_time = Column(Float, default=0.0)
    text = Column(Text, default="")
    speaker = Column(String(64), default="speaker")


class Topic(Base):
    __tablename__ = "topics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False)
    title = Column(String(512), default="")
    summary = Column(Text, default="")
    start_time = Column(Float, default=0.0)
    end_time = Column(Float, default=0.0)
    importance_score = Column(Float, default=0.0)


class Concept(Base):
    __tablename__ = "concepts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    name = Column(String(256), default="")
    type = Column(String(64), default="")
    description = Column(Text, default="")


class Blog(Base):
    __tablename__ = "blogs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False)
    title = Column(String(512), default="")
    abstract = Column(Text, default="")
    markdown = Column(Text, default="")
    html = Column(Text, default="")
    quality_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class StageResult(Base):
    __tablename__ = "stage_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False)
    stage = Column(String(64), nullable=False)
    data_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add processing_duration column if it doesn't exist (for existing databases)
        try:
            await conn.execute(text("ALTER TABLE videos ADD COLUMN processing_duration FLOAT"))
        except Exception:
            pass  # Column already exists
