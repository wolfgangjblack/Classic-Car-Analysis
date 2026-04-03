import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from app.deps import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.db import Base, Job, JobStatus, SourceType
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True, scope="session")
def _mock_heavy_imports():
    """Prevent cv2/whisper/yt_dlp from being needed during test imports."""
    mods = {}
    for mod_name in ("cv2", "whisper", "yt_dlp"):
        if mod_name not in sys.modules:
            mods[mod_name] = sys.modules[mod_name] = MagicMock()
    yield
    for mod_name, mod in mods.items():
        if sys.modules.get(mod_name) is mod:
            del sys.modules[mod_name]


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    SessionFactory = sessionmaker(bind=db_engine)
    session = SessionFactory()
    yield session
    session.close()


@pytest.fixture
def test_client(db_engine, tmp_path):
    """TestClient that shares the same in-memory DB via StaticPool."""
    SessionFactory = sessionmaker(bind=db_engine)

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    mock_settings = MagicMock()
    mock_settings.evidence_dir = tmp_path / "evidence"
    mock_settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    mock_settings.videos_dir = tmp_path / "videos"
    mock_settings.videos_dir.mkdir(parents=True, exist_ok=True)
    mock_settings.data_dir = tmp_path
    mock_settings.database_url = "sqlite:///:memory:"

    with (
        patch("app.api.jobs.get_settings", return_value=mock_settings),
        patch("app.api.videos.get_settings", return_value=mock_settings),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_job(db_session):
    """Factory fixture to insert Job rows into the shared test DB."""

    def _create(
        status=JobStatus.COMPLETE.value,
        source_type=SourceType.URL.value,
        source_path="https://youtube.com/watch?v=test",
        original_filename="Test Video",
        make="Ford",
        model="Thunderbird",
        year="1956",
        summary="Test summary",
        condition_report=None,
        condition_score=None,
        market_value_low=None,
        market_value_high=None,
        bid_range_low=None,
        bid_range_high=None,
        valuation_notes=None,
        cost=0.05,
        logs=None,
        error=None,
    ):
        job = Job(
            id=str(uuid.uuid4()),
            source_type=source_type,
            source_path=source_path,
            original_filename=original_filename,
            status=status,
            progress=100 if status == JobStatus.COMPLETE.value else 0,
            created_at=datetime.now(timezone.utc),
            make=make,
            model=model,
            year=year,
            summary=summary,
            condition_report=condition_report,
            condition_score=condition_score,
            market_value_low=market_value_low,
            market_value_high=market_value_high,
            bid_range_low=bid_range_low,
            bid_range_high=bid_range_high,
            valuation_notes=valuation_notes,
            cost=cost,
            logs=logs,
            error=error,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        return job

    return _create
