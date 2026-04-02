"""Tests for backend/app/api/jobs.py -- all job endpoints."""

import json
from unittest.mock import patch

import pytest

from app.models.db import JobStatus, SourceType
from app.api.jobs import parse_logs


# --- parse_logs (unit, called by endpoints) ---

def test_parse_logs_invalid_json():
    assert parse_logs("not json") == []
    assert parse_logs("") == []
    assert parse_logs(None) == []


def test_parse_logs_valid():
    logs = json.dumps([{"timestamp": "2025-01-01", "phase": "init", "status": "info", "message": "start"}])
    result = parse_logs(logs)
    assert len(result) == 1
    assert result[0].phase == "init"


# --- GET /api/jobs ---

def test_list_jobs_with_data(test_client, sample_job):
    sample_job(original_filename="Job A")
    sample_job(original_filename="Job B")
    sample_job(original_filename="Job C")

    resp = test_client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["jobs"]) == 3


def test_list_jobs_filter_status(test_client, sample_job):
    sample_job(status=JobStatus.COMPLETE.value)
    sample_job(status=JobStatus.FAILED.value, error="boom")
    sample_job(status=JobStatus.COMPLETE.value)

    resp = test_client.get("/api/jobs?status=complete")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


# --- GET /api/jobs/{id} ---

def test_get_job_detail(test_client, sample_job):
    job = sample_job(
        condition_report='{"overall_score": 4.5}',
        condition_score=4.5,
        market_value_low=30000,
        market_value_high=50000,
        bid_range_low=28000,
        bid_range_high=47000,
    )
    resp = test_client.get(f"/api/jobs/{job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["make"] == "Ford"
    assert data["condition_score"] == 4.5
    assert data["market_value_low"] == 30000
    assert data["bid_range_high"] == 47000


def test_get_job_not_found(test_client):
    resp = test_client.get("/api/jobs/nonexistent-id")
    assert resp.status_code == 404


# --- GET /api/jobs/{id}/logs ---

def test_get_job_logs(test_client, sample_job):
    logs_data = json.dumps([
        {"timestamp": "2025-01-01T00:00:00", "phase": "download", "status": "completed", "message": "Done", "duration_ms": 5000}
    ])
    job = sample_job(logs=logs_data)
    resp = test_client.get(f"/api/jobs/{job.id}/logs")
    assert resp.status_code == 200
    assert len(resp.json()["logs"]) == 1
    assert resp.json()["logs"][0]["phase"] == "download"


# --- GET /api/jobs/{id}/summary ---

def test_get_job_summary_complete(test_client, sample_job):
    job = sample_job(status=JobStatus.COMPLETE.value, summary="Great car", market_value_low=25000)
    resp = test_client.get(f"/api/jobs/{job.id}/summary")
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Great car"
    assert resp.json()["market_value_low"] == 25000


def test_get_job_summary_not_complete(test_client, sample_job):
    job = sample_job(status=JobStatus.ANALYZING.value)
    resp = test_client.get(f"/api/jobs/{job.id}/summary")
    assert resp.status_code == 400


# --- GET /api/jobs/{id}/evidence/{filename} ---

def test_evidence_frame_served(test_client, sample_job, tmp_path):
    job = sample_job()
    evidence_dir = tmp_path / "evidence" / job.id
    evidence_dir.mkdir(parents=True)
    img_data = b"\xff\xd8\xff\xe0fake-jpeg-data"
    (evidence_dir / "evidence_001.jpg").write_bytes(img_data)

    resp = test_client.get(f"/api/jobs/{job.id}/evidence/evidence_001.jpg")
    assert resp.status_code == 200
    assert resp.content == img_data
    assert resp.headers["content-type"] == "image/jpeg"


def test_evidence_frame_path_traversal(test_client, sample_job):
    job = sample_job()
    resp = test_client.get(f"/api/jobs/{job.id}/evidence/../../etc/passwd")
    assert resp.status_code == 400


def test_evidence_frame_missing_file(test_client, sample_job):
    job = sample_job()
    resp = test_client.get(f"/api/jobs/{job.id}/evidence/nonexistent.jpg")
    assert resp.status_code == 404


# --- POST /api/jobs/{id}/retry ---

def test_retry_failed_job(test_client, sample_job):
    job = sample_job(
        status=JobStatus.FAILED.value,
        error="Something broke",
        summary="Old summary",
        cost=0.05,
    )

    with patch("app.api.jobs.shutil.rmtree"):
        resp = test_client.post(f"/api/jobs/{job.id}/retry")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["progress"] == 0
    assert data["error"] is None


def test_retry_non_failed_job(test_client, sample_job):
    job = sample_job(status=JobStatus.COMPLETE.value)
    resp = test_client.post(f"/api/jobs/{job.id}/retry")
    assert resp.status_code == 400


def test_retry_url_vs_upload(test_client, sample_job):
    url_job = sample_job(
        status=JobStatus.FAILED.value,
        source_type=SourceType.URL.value,
        error="fail",
    )
    upload_job = sample_job(
        status=JobStatus.FAILED.value,
        source_type=SourceType.UPLOAD.value,
        source_path="/app/data/videos/test.mp4",
        error="fail",
    )

    with patch("app.api.jobs.shutil.rmtree"):
        resp1 = test_client.post(f"/api/jobs/{url_job.id}/retry")
        resp2 = test_client.post(f"/api/jobs/{upload_job.id}/retry")

    assert resp1.status_code == 200
    assert resp2.status_code == 200


# --- DELETE /api/jobs/{id} ---

def test_delete_complete_job(test_client, sample_job):
    job = sample_job(status=JobStatus.COMPLETE.value)
    resp = test_client.delete(f"/api/jobs/{job.id}")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Job deleted"

    resp2 = test_client.get(f"/api/jobs/{job.id}")
    assert resp2.status_code == 404


def test_delete_pending_job(test_client, sample_job):
    job = sample_job(status=JobStatus.PENDING.value)
    resp = test_client.delete(f"/api/jobs/{job.id}")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Job cancelled"

    resp2 = test_client.get(f"/api/jobs/{job.id}")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "cancelled"
