"""Tests for backend/app/workers/tasks.py -- _run_vision_and_valuation orchestration."""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Base, Job, JobStatus, SourceType
from app.core.vision_analyzer import ConditionResult
from app.core.valuation import ValuationResult


@pytest.fixture
def pipeline_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
        created_at=datetime.utcnow(),
    )
    pipeline_db.add(job)
    pipeline_db.commit()
    pipeline_db.refresh(job)
    return job


def _mock_condition_result(tmp_path):
    """Create a ConditionResult with real temp frame files."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
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


def test_vision_and_valuation_happy_path(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    valuation = _mock_valuation_result()
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}

    evidence_dir = tmp_path / "evidence"
    mock_settings = MagicMock()
    mock_settings.evidence_dir = evidence_dir

    with patch("app.workers.tasks.get_db_session", return_value=pipeline_db), \
         patch("app.workers.tasks.VisionService") as mock_vs, \
         patch("app.workers.tasks.ValuationService") as mock_vals, \
         patch("app.workers.tasks.get_settings", return_value=mock_settings):

        mock_vs.return_value.analyze_vehicle_condition.return_value = condition
        mock_vals.return_value.evaluate.return_value = valuation

        from app.workers.tasks import _run_vision_and_valuation
        cr_json, score, val_result, cost = _run_vision_and_valuation(
            pipeline_job.id, str(tmp_path / "frames"), vehicle_info, 0.002
        )

    pipeline_db.refresh(pipeline_job)
    assert pipeline_job.condition_score == 4.2
    assert pipeline_job.condition_report is not None
    report = json.loads(pipeline_job.condition_report)
    assert report["overall_score"] == 4.2
    assert pipeline_job.market_value_low == 30000
    assert pipeline_job.bid_range_high == 48000
    assert cost == pytest.approx(0.002 + 0.08 + 0.03)


def test_valuation_failure_non_fatal(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}

    mock_settings = MagicMock()
    mock_settings.evidence_dir = tmp_path / "evidence"

    with patch("app.workers.tasks.get_db_session", return_value=pipeline_db), \
         patch("app.workers.tasks.VisionService") as mock_vs, \
         patch("app.workers.tasks.ValuationService") as mock_vals, \
         patch("app.workers.tasks.get_settings", return_value=mock_settings):

        mock_vs.return_value.analyze_vehicle_condition.return_value = condition
        mock_vals.return_value.evaluate.side_effect = RuntimeError("API unavailable")

        from app.workers.tasks import _run_vision_and_valuation
        cr_json, score, val_result, cost = _run_vision_and_valuation(
            pipeline_job.id, str(tmp_path / "frames"), vehicle_info, 0.002
        )

    pipeline_db.refresh(pipeline_job)
    assert pipeline_job.condition_score == 4.2
    assert pipeline_job.market_value_low is None
    assert val_result is None


def test_valuation_skipped_no_make(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "", "model": "", "year": "1956"}

    mock_settings = MagicMock()
    mock_settings.evidence_dir = tmp_path / "evidence"

    with patch("app.workers.tasks.get_db_session", return_value=pipeline_db), \
         patch("app.workers.tasks.VisionService") as mock_vs, \
         patch("app.workers.tasks.ValuationService") as mock_vals, \
         patch("app.workers.tasks.get_settings", return_value=mock_settings):

        mock_vs.return_value.analyze_vehicle_condition.return_value = condition

        from app.workers.tasks import _run_vision_and_valuation
        cr_json, score, val_result, cost = _run_vision_and_valuation(
            pipeline_job.id, str(tmp_path / "frames"), vehicle_info, 0.002
        )

    mock_vals.return_value.evaluate.assert_not_called()
    assert val_result is None


def test_evidence_frames_copied(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}

    evidence_dir = tmp_path / "evidence"
    mock_settings = MagicMock()
    mock_settings.evidence_dir = evidence_dir

    with patch("app.workers.tasks.get_db_session", return_value=pipeline_db), \
         patch("app.workers.tasks.VisionService") as mock_vs, \
         patch("app.workers.tasks.ValuationService") as mock_vals, \
         patch("app.workers.tasks.get_settings", return_value=mock_settings):

        mock_vs.return_value.analyze_vehicle_condition.return_value = condition
        mock_vals.return_value.evaluate.return_value = _mock_valuation_result()

        from app.workers.tasks import _run_vision_and_valuation
        _run_vision_and_valuation(
            pipeline_job.id, str(tmp_path / "frames"), vehicle_info, 0.002
        )

    job_evidence_dir = evidence_dir / pipeline_job.id
    assert job_evidence_dir.exists()
    evidence_files = list(job_evidence_dir.glob("evidence_*.jpg"))
    assert len(evidence_files) >= 1


def test_vision_summary_appended(pipeline_db, pipeline_job, tmp_path):
    condition = _mock_condition_result(tmp_path)
    vehicle_info = {"make": "Ford", "model": "Thunderbird", "year": "1956"}

    mock_settings = MagicMock()
    mock_settings.evidence_dir = tmp_path / "evidence"

    with patch("app.workers.tasks.get_db_session", return_value=pipeline_db), \
         patch("app.workers.tasks.VisionService") as mock_vs, \
         patch("app.workers.tasks.ValuationService") as mock_vals, \
         patch("app.workers.tasks.get_settings", return_value=mock_settings):

        mock_vs.return_value.analyze_vehicle_condition.return_value = condition
        mock_vals.return_value.evaluate.return_value = _mock_valuation_result()

        from app.workers.tasks import _run_vision_and_valuation
        _run_vision_and_valuation(
            pipeline_job.id, str(tmp_path / "frames"), vehicle_info, 0.002
        )

    pipeline_db.refresh(pipeline_job)
    assert "Visual Condition Assessment" in pipeline_job.summary
    assert "4.2" in pipeline_job.summary
    assert "Paint looks great" in pipeline_job.summary
