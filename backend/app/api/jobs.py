import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.db import Job, JobStatus, get_engine, create_session_factory
from ..models.schemas import JobResponse, JobDetailResponse, JobListResponse, JobLogsResponse, LogEntry


router = APIRouter()


def get_db():
    """Dependency to get database session"""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    SessionLocal = create_session_factory(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
        "cost": job.cost or 0.0
    }


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

    db.delete(job)
    db.commit()

    return {"message": "Job deleted", "id": job_id}
