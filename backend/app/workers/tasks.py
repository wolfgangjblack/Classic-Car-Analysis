import os
import json
import time
import traceback
from datetime import datetime
from pathlib import Path

from ..config import get_settings
from ..models.db import Job, JobStatus, get_engine, create_session_factory
from ..services.downloader import VideoDownloader
from ..services.video_service import VideoService
from ..services.agent_service import AgentService


def get_db_session():
    """Get a new database session"""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    SessionLocal = create_session_factory(engine)
    return SessionLocal()


def add_log_entry(job_id: str, phase: str, status: str, message: str, duration_ms: int = None, details: dict = None):
    """Add a log entry for a job"""
    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            logs = json.loads(job.logs) if job.logs else []
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "phase": phase,
                "status": status,
                "message": message,
            }
            if duration_ms is not None:
                entry["duration_ms"] = duration_ms
            if details:
                entry["details"] = details
            logs.append(entry)
            job.logs = json.dumps(logs)
            db.commit()
    finally:
        db.close()


def update_job_status(job_id: str, status: str, progress: int = None, current_step: str = None, error: str = None):
    """Update job status in database"""
    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if progress is not None:
                job.progress = progress
            if current_step is not None:
                job.current_step = current_step
            if error is not None:
                job.error = error
            if status == JobStatus.PROCESSING_VIDEO.value and job.started_at is None:
                job.started_at = datetime.utcnow()
            if status in [JobStatus.COMPLETE.value, JobStatus.FAILED.value]:
                job.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def update_job_results(job_id: str, summary: str, make: str, model: str, year: str, cost: float):
    """Update job with results"""
    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.summary = summary
            job.make = make
            job.model = model
            job.year = year
            job.cost = cost
            db.commit()
    finally:
        db.close()


class PhaseTimer:
    """Context manager for timing phases and logging"""
    def __init__(self, job_id: str, phase: str, message: str):
        self.job_id = job_id
        self.phase = phase
        self.message = message
        self.start_time = None
        self.details = {}

    def __enter__(self):
        self.start_time = time.time()
        add_log_entry(self.job_id, self.phase, "started", f"Starting: {self.message}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)
        if exc_type is None:
            add_log_entry(
                self.job_id, self.phase, "completed",
                f"Completed: {self.message}",
                duration_ms=duration_ms,
                details=self.details if self.details else None
            )
        else:
            error_details = {
                "error_type": exc_type.__name__,
                "error_message": str(exc_val),
                "traceback": traceback.format_exc()
            }
            if self.details:
                error_details.update(self.details)
            add_log_entry(
                self.job_id, self.phase, "failed",
                f"Failed: {self.message} - {str(exc_val)}",
                duration_ms=duration_ms,
                details=error_details
            )
        return False

    def add_detail(self, key: str, value):
        self.details[key] = value


def process_video_task(job_id: str):
    """Background task to process an uploaded video."""
    settings = get_settings()
    total_start = time.time()

    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        video_path = job.source_path
        add_log_entry(job_id, "init", "info", f"Starting processing for uploaded video", 
                     details={"video_path": video_path})
    finally:
        db.close()

    try:
        update_job_status(job_id, JobStatus.PROCESSING_VIDEO.value, 5, "Starting video processing")

        video_service = VideoService()
        phase_times = {}

        def video_progress(step, progress):
            status_map = {
                "extracting_audio": (JobStatus.PROCESSING_VIDEO.value, "Extracting audio"),
                "transcribing": (JobStatus.TRANSCRIBING.value, "Transcribing audio"),
                "saving_transcript": (JobStatus.TRANSCRIBING.value, "Saving transcript"),
                "creating_subtitles": (JobStatus.PROCESSING_VIDEO.value, "Creating subtitles"),
                "adding_subtitles": (JobStatus.PROCESSING_VIDEO.value, "Adding subtitles to video"),
                "extracting_frames": (JobStatus.PROCESSING_VIDEO.value, "Extracting frames"),
                "complete": (JobStatus.PROCESSING_VIDEO.value, "Video processing complete"),
            }
            if step in status_map:
                status, desc = status_map[step]
                scaled_progress = int(5 + (progress * 0.45))
                update_job_status(job_id, status, scaled_progress, desc)

        with PhaseTimer(job_id, "video_processing", "Video processing pipeline") as timer:
            result = video_service.process_video(video_path, video_progress)
            transcript_path = result.transcript_json_path
            timer.add_detail("transcript_path", transcript_path)
            timer.add_detail("captioned_video", result.captioned_video_path)
            timer.add_detail("duration_seconds", result.duration_seconds)

        # Log the transcript content
        transcript_text = ""
        try:
            with open(transcript_path, 'r') as f:
                transcript_data = json.load(f)
                transcript_text = transcript_data.get('text', '') if isinstance(transcript_data, dict) else str(transcript_data)
                add_log_entry(job_id, "transcript", "info", "Transcript generated",
                             details={"transcript_text": transcript_text[:8000] if len(transcript_text) > 8000 else transcript_text,
                                     "total_length": len(transcript_text)})
        except Exception as e:
            add_log_entry(job_id, "transcript", "warning", f"Could not read transcript: {str(e)}")

        update_job_status(job_id, JobStatus.ANALYZING.value, 55, "Analyzing transcript")

        with PhaseTimer(job_id, "ai_analysis", "AI transcript analysis") as timer:
            agent_service = AgentService()

            def agent_progress(step, progress):
                if step == "processing_chunks":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 60, "Processing transcript chunks")
                elif step == "generating_summary":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 85, "Generating summary")
                elif step == "complete":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 95, "Analysis complete")

            agent_service.process_transcript(transcript_path, agent_progress)

            transcript_name = os.path.basename(transcript_path)
            summary = agent_service.get_summary(transcript_name)
            cost = agent_service.get_cost(transcript_name)
            vehicle_info = agent_service.extract_vehicle_info(transcript_name)
            
            timer.add_detail("cost", cost)
            timer.add_detail("vehicle_info", vehicle_info)
            timer.add_detail("summary", summary)

        update_job_results(
            job_id,
            summary=summary,
            make=vehicle_info.get("make"),
            model=vehicle_info.get("model"),
            year=vehicle_info.get("year"),
            cost=cost
        )

        total_duration = int((time.time() - total_start) * 1000)
        add_log_entry(job_id, "complete", "success", "Processing completed successfully",
                     duration_ms=total_duration,
                     details={"total_cost": cost, "vehicle": vehicle_info, "summary": summary})

        update_job_status(job_id, JobStatus.COMPLETE.value, 100, "Complete")

    except Exception as e:
        total_duration = int((time.time() - total_start) * 1000)
        add_log_entry(job_id, "error", "failed", f"Processing failed: {str(e)}",
                     duration_ms=total_duration,
                     details={"error_type": type(e).__name__, "traceback": traceback.format_exc()})
        update_job_status(job_id, JobStatus.FAILED.value, error=str(e))
        raise


def process_url_task(job_id: str):
    """Background task to process a video URL."""
    settings = get_settings()
    total_start = time.time()

    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        url = job.source_path
        add_log_entry(job_id, "init", "info", f"Starting processing for URL",
                     details={"url": url})
    finally:
        db.close()

    try:
        update_job_status(job_id, JobStatus.DOWNLOADING.value, 2, "Downloading video")

        with PhaseTimer(job_id, "download", "Video download") as timer:
            downloader = VideoDownloader(str(settings.videos_dir))

            def download_progress(step, progress):
                if step == "downloading":
                    scaled = int(2 + (progress * 0.08))
                    update_job_status(job_id, JobStatus.DOWNLOADING.value, scaled, f"Downloading: {progress}%")
                elif step == "download_complete":
                    update_job_status(job_id, JobStatus.DOWNLOADING.value, 10, "Download complete")

            video_path, title = downloader.download(url, job_id, download_progress)
            timer.add_detail("video_path", video_path)
            timer.add_detail("title", title)

        db = get_db_session()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.source_path = video_path
                job.original_filename = title
                db.commit()
        finally:
            db.close()

        update_job_status(job_id, JobStatus.PROCESSING_VIDEO.value, 12, "Starting video processing")

        video_service = VideoService()

        def video_progress(step, progress):
            status_map = {
                "extracting_audio": (JobStatus.PROCESSING_VIDEO.value, "Extracting audio"),
                "transcribing": (JobStatus.TRANSCRIBING.value, "Transcribing audio"),
                "saving_transcript": (JobStatus.TRANSCRIBING.value, "Saving transcript"),
                "creating_subtitles": (JobStatus.PROCESSING_VIDEO.value, "Creating subtitles"),
                "adding_subtitles": (JobStatus.PROCESSING_VIDEO.value, "Adding subtitles to video"),
                "extracting_frames": (JobStatus.PROCESSING_VIDEO.value, "Extracting frames"),
                "complete": (JobStatus.PROCESSING_VIDEO.value, "Video processing complete"),
            }
            if step in status_map:
                status, desc = status_map[step]
                scaled_progress = int(12 + (progress * 0.38))
                update_job_status(job_id, status, scaled_progress, desc)

        with PhaseTimer(job_id, "video_processing", "Video processing pipeline") as timer:
            result = video_service.process_video(video_path, video_progress)
            transcript_path = result.transcript_json_path
            timer.add_detail("transcript_path", transcript_path)
            timer.add_detail("captioned_video", result.captioned_video_path)
            timer.add_detail("duration_seconds", result.duration_seconds)

        # Log the transcript content
        transcript_text = ""
        try:
            with open(transcript_path, 'r') as f:
                transcript_data = json.load(f)
                transcript_text = transcript_data.get('text', '') if isinstance(transcript_data, dict) else str(transcript_data)
                add_log_entry(job_id, "transcript", "info", "Transcript generated",
                             details={"transcript_text": transcript_text[:8000] if len(transcript_text) > 8000 else transcript_text,
                                     "total_length": len(transcript_text)})
        except Exception as e:
            add_log_entry(job_id, "transcript", "warning", f"Could not read transcript: {str(e)}")

        update_job_status(job_id, JobStatus.ANALYZING.value, 55, "Analyzing transcript")

        with PhaseTimer(job_id, "ai_analysis", "AI transcript analysis") as timer:
            agent_service = AgentService()

            def agent_progress(step, progress):
                if step == "processing_chunks":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 60, "Processing transcript chunks")
                elif step == "generating_summary":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 85, "Generating summary")
                elif step == "complete":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 95, "Analysis complete")

            agent_service.process_transcript(transcript_path, agent_progress)

            transcript_name = os.path.basename(transcript_path)
            summary = agent_service.get_summary(transcript_name)
            cost = agent_service.get_cost(transcript_name)
            vehicle_info = agent_service.extract_vehicle_info(transcript_name)
            
            timer.add_detail("cost", cost)
            timer.add_detail("vehicle_info", vehicle_info)
            timer.add_detail("summary", summary)

        update_job_results(
            job_id,
            summary=summary,
            make=vehicle_info.get("make"),
            model=vehicle_info.get("model"),
            year=vehicle_info.get("year"),
            cost=cost
        )

        total_duration = int((time.time() - total_start) * 1000)
        add_log_entry(job_id, "complete", "success", "Processing completed successfully",
                     duration_ms=total_duration,
                     details={"total_cost": cost, "vehicle": vehicle_info, "summary": summary})

        update_job_status(job_id, JobStatus.COMPLETE.value, 100, "Complete")

    except Exception as e:
        total_duration = int((time.time() - total_start) * 1000)
        add_log_entry(job_id, "error", "failed", f"Processing failed: {str(e)}",
                     duration_ms=total_duration,
                     details={"error_type": type(e).__name__, "traceback": traceback.format_exc()})
        update_job_status(job_id, JobStatus.FAILED.value, error=str(e))
        raise
