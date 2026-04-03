"""Tests for backend/app/workers/tasks.py -- _run_vision_and_valuation orchestration."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db import Base, Job, JobStatus, SourceType
from app.core.vision_analyzer import ConditionResult
from app.core.valuation import ValuationResult


@pytest.fixture
def pipeline_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def pipeline_job(pipeline_db):
    job = Job(
        id=str(uuid.uuid4()),
        source_type=SourceType.URL.value,
        source_path="https://youtube.com/watch?v=test",
        original_filename="Test Video",
        status=JobStatus.ANALYZING.value,
        progress=58,
        summary="Existing transcript summary",
        make="Ford",
        model="Thunderbird",
        year="1956",
        cost=0.002,
        created_at=datetime.now(timezone.utc),
    )
    pipeline_db.add(job)
    pipeline_db.commit()
    pipeline_db.refresh(job)
    return job


def _mock_condition_result(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(exist_ok=True)
    frame_paths = []
    for i in range(3):
        p = frames_dir / f"frame_{i:03d}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0" + bytes(100))
        frame_paths.append(str(p))

    return ConditionResult(
        observations={
            "good": [
                {"text": "Paint looks great", "image_index": 1, "area": "exterior_paint"},
                {"text": "Clean interior", "image_index": 3, "area": "interior_seats"},
            ],
            "bad": [
                {"text": "Minor scratch on bumper", "image_index": 2, "area": "chrome_trim"},
            ],
        },
        area_scores={
            "exterior_paint": {"score": 5, "notes": "Excellent"},
            "body_panels": {"score": 4, "notes": "Good"},
            "chrome_trim": {"score": 3, "notes": "Minor scratch"},
        },
        overall_score=4.2,
        overall_assessment="Very good condition overall.",
        images_analyzed=3,
        exterior_images_found=2,
        interior_images_found=1,
        frame_paths=frame_paths,
        cost=0.08,
    )


def _mock_valuation_result():
    return ValuationResult(
        market_value_low=30000,
        market_value_high=55000,
        bid_range_low=35000,
        bid_range_high=48000,
        valuation_notes="Based on recent BaT sales",
        sources=[{"url": "https://example.com", "title": "BaT"}],
        cost=0.03,
    )


def _run_with_patches(pipeline_db, job_id, frames_dir, vehicle_info, cost, condition, valuation=None, valuation_error=None, tmp_path=None):
    """Helper that patches all external deps and runs _run_vision_and_valuation."""
    from app.workers.tasks import _run_vision_and_valuation

    mock_settings = MagicMock()
    mock_settings.evidence_dir = (tmp_path or Path("/tmp")) / "evidence"

    with patch("app.workers.tasks.get_db_session", return_value=pipeline_db), \
         patch("app.workers.tasks.VisionService") as mock_vs, \
         patch("app.workers.tasks.ValuationService") as mock_vals, \
         patch("app.workers.tasks.get_settings", return_value=mock_settings):

        mock_vs.return_value.analyze_vehicle_condition.return_value = condition
        if valuation_error:
            mock_vals.return_value.evaluate.side_effect = valuation_error
        elif valuation:
            mock_vals.return_value.evaluate.return_value = valuation

        result = _run_vision_and_valuation(job_id, frames_dir, vehicle_info, cost)
        return result, mock_vals


def test_vision_and_valuation_happy_path(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    valuation = _mock_valuation_result()
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}
    job_id = pipeline_job.id

    (cr_json, score, val_result, cost), _ = _run_with_patches(
        pipeline_db, job_id, str(tmp_path / "frames"), vehicle_info, 0.002,
        condition, valuation=valuation, tmp_path=tmp_path,
    )

    pipeline_db.expire_all()
    job = pipeline_db.query(Job).filter(Job.id == job_id).first()
    assert job.condition_score == 4.2
    assert job.condition_report is not None
    report = json.loads(job.condition_report)
    assert report["overall_score"] == 4.2
    assert job.market_value_low == 30000
    assert job.bid_range_high == 48000
    assert cost == pytest.approx(0.002 + 0.08 + 0.03)


def test_valuation_failure_non_fatal(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}
    job_id = pipeline_job.id

    (cr_json, score, val_result, cost), _ = _run_with_patches(
        pipeline_db, job_id, str(tmp_path / "frames"), vehicle_info, 0.002,
        condition, valuation_error=RuntimeError("API unavailable"), tmp_path=tmp_path,
    )

    pipeline_db.expire_all()
    job = pipeline_db.query(Job).filter(Job.id == job_id).first()
    assert job.condition_score == 4.2
    assert job.market_value_low is None
    assert val_result is None


def test_valuation_skipped_no_make(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "", "model": "", "year": "1956"}
    job_id = pipeline_job.id

    (cr_json, score, val_result, cost), mock_vals = _run_with_patches(
        pipeline_db, job_id, str(tmp_path / "frames"), vehicle_info, 0.002,
        condition, tmp_path=tmp_path,
    )

    mock_vals.return_value.evaluate.assert_not_called()
    assert val_result is None


def test_evidence_frames_copied(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}
    job_id = pipeline_job.id

    _run_with_patches(
        pipeline_db, job_id, str(tmp_path / "frames"), vehicle_info, 0.002,
        condition, valuation=_mock_valuation_result(), tmp_path=tmp_path,
    )

    evidence_dir = tmp_path / "evidence" / job_id
    assert evidence_dir.exists()
    evidence_files = list(evidence_dir.glob("evidence_*.jpg"))
    assert len(evidence_files) >= 1


def test_vision_summary_appended(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}
    job_id = pipeline_job.id

    _run_with_patches(
        pipeline_db, job_id, str(tmp_path / "frames"), vehicle_info, 0.002,
        condition, valuation=_mock_valuation_result(), tmp_path=tmp_path,
    )

    pipeline_db.expire_all()
    job = pipeline_db.query(Job).filter(Job.id == job_id).first()
    assert "Visual Condition Assessment" in job.summary
    assert "4.2" in job.summary
    assert "Paint looks great" in job.summary
