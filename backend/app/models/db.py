import uuid
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, Text, DateTime, Enum as SQLEnum
from sqlalchemy.orm import declarative_base, sessionmaker
from enum import Enum

Base = declarative_base()


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING_VIDEO = "processing_video"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_type = Column(String, nullable=False)
    source_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)
    status = Column(String, default=JobStatus.PENDING.value)
    progress = Column(Integer, default=0)
    current_step = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Results
    transcript_path = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    make = Column(String, nullable=True)
    model = Column(String, nullable=True)
    year = Column(String, nullable=True)

    # Cost tracking
    cost = Column(Float, default=0.0)

    # Error info
    error = Column(Text, nullable=True)

    # Processing logs (JSON array of log entries)
    logs = Column(Text, nullable=True)


def get_engine(database_url: str):
    """Create database engine"""
    return create_engine(database_url, connect_args={"check_same_thread": False})


def create_session_factory(engine):
    """Create session factory"""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(database_url: str):
    """Initialize database and create tables"""
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    return engine
