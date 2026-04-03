import os
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..deps import get_db
from ..models.db import Job, JobStatus, SourceType
from ..models.schemas import JobResponse, URLSubmission

router = APIRouter()


@router.post("/upload", response_model=JobResponse)
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a video file for processing"""
    settings = get_settings()

    valid_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in valid_extensions:
        raise HTTPException(
            status_code=400, detail=f"Invalid file type. Supported types: {', '.join(valid_extensions)}"
        )

    job_id = str(uuid.uuid4())
    video_filename = f"{job_id}{file_ext}"
    video_path = settings.videos_dir / video_filename

    settings.videos_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    job = Job(
        id=job_id,
        source_type=SourceType.UPLOAD.value,
        source_path=str(video_path),
        original_filename=file.filename,
        status=JobStatus.PENDING.value,
        progress=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

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


@router.post("/url", response_model=JobResponse)
async def submit_url(background_tasks: BackgroundTasks, submission: URLSubmission, db: Session = Depends(get_db)):
    """Submit a YouTube or video URL for processing"""
    url = submission.url

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL format")

    job_id = str(uuid.uuid4())

    job = Job(
        id=job_id,
        source_type=SourceType.URL.value,
        source_path=url,
        original_filename=url,
        status=JobStatus.PENDING.value,
        progress=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from ..workers.tasks import process_url_task

    background_tasks.add_task(process_url_task, job_id)

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
