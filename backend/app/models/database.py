from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey, Boolean, text
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
    # Source type: video / audio / url — records how the task was created
    source_type = Column(String(32), default="video")
    # Original URL when source_type == "url"; empty for file uploads
    source_url = Column(String(1024), default="")
    # Prompt preset used for blog generation (nullable = use default)
    preset_id = Column(Integer, nullable=True)
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


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    id = Column(String(64), primary_key=True)  # e.g. "segment_chapters", "generate_blog_system"
    name = Column(String(128), default="")
    description = Column(Text, default="")
    template = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PromptPreset(Base):
    """Named prompt presets for blog generation."""
    __tablename__ = "prompt_presets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    system_prompt = Column(Text, default="")
    user_prompt = Column(Text, default="")
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add columns if they don't exist (for existing databases)
        try:
            await conn.execute(text("ALTER TABLE videos ADD COLUMN processing_duration FLOAT"))
        except Exception:
            pass  # Column already exists
        try:
            await conn.execute(text("ALTER TABLE videos ADD COLUMN source_type VARCHAR(32) DEFAULT 'video'"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE videos ADD COLUMN source_url VARCHAR(1024) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE videos ADD COLUMN preset_id INTEGER"))
        except Exception:
            pass

    # Seed default preset if none exist
    async with async_session() as db:
        from sqlalchemy import select, func
        count_result = await db.execute(select(func.count()).select_from(PromptPreset))
        if count_result.scalar() == 0:
            from ..pipeline.nodes import DEFAULT_TEMPLATES
            default_sys = DEFAULT_TEMPLATES.get("generate_blog_system", {}).get("template", "")
            default_user = DEFAULT_TEMPLATES.get("generate_blog_user", {}).get("template", "")
            db.add(PromptPreset(
                name="默认",
                description="系统内置的默认博客生成提示词",
                system_prompt=default_sys,
                user_prompt=default_user,
                is_default=True,
            ))
            await db.commit()
