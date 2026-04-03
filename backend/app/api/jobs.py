import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..deps import get_db
from ..models.db import Job, JobStatus, SourceType
from ..models.schemas import JobDetailResponse, JobListResponse, JobLogsResponse, JobResponse, LogEntry

router = APIRouter()


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List all jobs with optional filtering"""
    query = db.query(Job)

    if status:
        query = query.filter(Job.status == status)

    total = query.count()
    jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()

    return JobListResponse(
        jobs=[
            JobResponse(
                id=j.id,
                source_type=j.source_type,
                original_filename=j.original_filename,
                status=j.status,
                progress=j.progress,
                current_step=j.current_step,
                created_at=j.created_at,
                started_at=j.started_at,
                completed_at=j.completed_at,
                error=j.error
            )
            for j in jobs
        ],
        total=total
    )


def parse_logs(logs_json: str) -> list:
    """Parse logs JSON string into list of LogEntry"""
    if not logs_json:
        return []
    try:
        logs_data = json.loads(logs_json)
        return [LogEntry(**log) for log in logs_data]
    except (json.JSONDecodeError, TypeError):
        return []


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get detailed job information"""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetailResponse(
        id=job.id,
        source_type=job.source_type,
        original_filename=job.original_filename,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        summary=job.summary,
        make=job.make,
        model=job.model,
        year=job.year,
        condition_report=job.condition_report,
        condition_score=job.condition_score,
        market_value_low=job.market_value_low,
        market_value_high=job.market_value_high,
        bid_range_low=job.bid_range_low,
        bid_range_high=job.bid_range_high,
        valuation_notes=job.valuation_notes,
        cost=job.cost or 0.0,
        logs=parse_logs(job.logs)
    )


@router.get("/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(job_id: str, db: Session = Depends(get_db)):
    """Get processing logs for a job"""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobLogsResponse(
        job_id=job.id,
        logs=parse_logs(job.logs)
    )


@router.get("/{job_id}/summary")
async def get_job_summary(job_id: str, db: Session = Depends(get_db)):
    """Get job summary only"""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETE.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not complete. Current status: {job.status}"
        )

    return {
        "id": job.id,
        "make": job.make,
        "model": job.model,
        "year": job.year,
        "summary": job.summary,
        "condition_report": job.condition_report,
        "condition_score": job.condition_score,
        "market_value_low": job.market_value_low,
        "market_value_high": job.market_value_high,
        "bid_range_low": job.bid_range_low,
        "bid_range_high": job.bid_range_high,
        "valuation_notes": job.valuation_notes,
        "cost": job.cost or 0.0,
    }


@router.get("/{job_id}/evidence/{filename}")
async def get_evidence_frame(job_id: str, filename: str, db: Session = Depends(get_db)):
    """Serve an evidence frame image for a job"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    safe_filename = Path(filename).name
    if safe_filename != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    settings = get_settings()
    frame_path = settings.evidence_dir / job_id / safe_filename
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Evidence frame not found")

    return FileResponse(
        str(frame_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Retry a failed job by resetting it and re-queuing processing"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Only failed jobs can be retried. Current status: {job.status}",
        )

    job.status = JobStatus.PENDING.value
    job.progress = 0
    job.current_step = None
    job.error = None
    job.started_at = None
    job.completed_at = None
    job.logs = None
    job.summary = None
    job.condition_report = None
    job.condition_score = None
    job.market_value_low = None
    job.market_value_high = None
    job.bid_range_low = None
    job.bid_range_high = None
    job.valuation_notes = None
    job.cost = 0.0
    db.commit()

    settings = get_settings()
    evidence_path = settings.evidence_dir / job_id
    if evidence_path.exists():
        shutil.rmtree(str(evidence_path), ignore_errors=True)

    if job.source_type == SourceType.URL.value:
        from ..workers.tasks import process_url_task
        background_tasks.add_task(process_url_task, job_id)
    else:
        from ..workers.tasks import process_video_task
        background_tasks.add_task(process_video_task, job_id)

    return JobResponse(
        id=job.id,
        source_type=job.source_type,
        original_filename=job.original_filename,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
    )


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Delete or cancel a job"""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in [JobStatus.PENDING.value, JobStatus.DOWNLOADING.value]:
        job.status = JobStatus.CANCELLED.value
        db.commit()
        return {"message": "Job cancelled", "id": job_id}

    settings = get_settings()
    evidence_path = settings.evidence_dir / job_id
    if evidence_path.exists():
        shutil.rmtree(str(evidence_path), ignore_errors=True)

    db.delete(job)
    db.commit()

    return {"message": "Job deleted", "id": job_id}
