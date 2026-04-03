import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, inspect
from sqlalchemy import text as sa_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING_VIDEO = "processing_video"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    VISION_ANALYSIS = "vision_analysis"
    VALUATION = "valuation"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default=JobStatus.PENDING.value)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Results
    transcript_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    make: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    year: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Vision condition assessment
    condition_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    condition_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Market valuation
    market_value_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_value_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid_range_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid_range_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valuation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cost tracking
    cost: Mapped[float] = mapped_column(Float, default=0.0)

    # Error info
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Processing logs (JSON array of log entries)
    logs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def get_engine(database_url: str):
    """Create database engine"""
    return create_engine(database_url, connect_args={"check_same_thread": False})


def create_session_factory(engine):
    """Create session factory"""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(database_url: str):
    """Initialize database and create tables, migrating existing schema if needed."""
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)

    _migrate_add_columns(engine)
    return engine


def _migrate_add_columns(engine):
    """Add new columns to existing tables that were created before schema updates."""
    new_columns = {
        "jobs": [
            ("condition_report", "TEXT"),
            ("condition_score", "REAL"),
            ("market_value_low", "REAL"),
            ("market_value_high", "REAL"),
            ("bid_range_low", "REAL"),
            ("bid_range_high", "REAL"),
            ("valuation_notes", "TEXT"),
        ]
    }

    inspector = inspect(engine)
    with engine.connect() as conn:
        for table, columns in new_columns.items():
            existing = {col["name"] for col in inspector.get_columns(table)}
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
            conn.commit()
