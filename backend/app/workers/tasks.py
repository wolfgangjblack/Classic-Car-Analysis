import json
import logging
import os
import shutil
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import get_settings
from ..deps import get_db_session
from ..models.db import Job, JobStatus
from ..services.agent_service import AgentService
from ..services.downloader import VideoDownloader
from ..services.valuation_service import ValuationService
from ..services.video_service import VideoService
from ..services.vision_service import VisionService

logger = logging.getLogger(__name__)


def add_log_entry(
    job_id: str,
    phase: str,
    status: str,
    message: str,
    duration_ms: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
):
    """Add a log entry for a job"""
    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            logs = json.loads(job.logs) if job.logs else []
            entry: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
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


def update_job_status(
    job_id: str,
    status: str,
    progress: Optional[int] = None,
    current_step: Optional[str] = None,
    error: Optional[str] = None,
):
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
                job.started_at = datetime.now(timezone.utc)
            if status in [JobStatus.COMPLETE.value, JobStatus.FAILED.value]:
                job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def update_job_results(
    job_id: str,
    summary: Optional[str] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[str] = None,
    cost: Optional[float] = None,
    condition_report: Optional[str] = None,
    condition_score: Optional[float] = None,
    market_value_low: Optional[float] = None,
    market_value_high: Optional[float] = None,
    bid_range_low: Optional[float] = None,
    bid_range_high: Optional[float] = None,
    valuation_notes: Optional[str] = None,
):
    """Update job with results. Only updates fields that are not None."""
    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            if summary is not None:
                job.summary = summary
            if make is not None:
                job.make = make
            if model is not None:
                job.model = model
            if year is not None:
                job.year = year
            if cost is not None:
                job.cost = cost
            if condition_report is not None:
                job.condition_report = condition_report
            if condition_score is not None:
                job.condition_score = condition_score
            if market_value_low is not None:
                job.market_value_low = market_value_low
            if market_value_high is not None:
                job.market_value_high = market_value_high
            if bid_range_low is not None:
                job.bid_range_low = bid_range_low
            if bid_range_high is not None:
                job.bid_range_high = bid_range_high
            if valuation_notes is not None:
                job.valuation_notes = valuation_notes
            db.commit()
    finally:
        db.close()


class PhaseTimer:
    """Context manager for timing phases and logging"""

    def __init__(self, job_id: str, phase: str, message: str):
        self.job_id = job_id
        self.phase = phase
        self.message = message
        self.start_time: Optional[float] = None
        self.details: dict[str, Any] = {}

    def __enter__(self):
        self.start_time = time.time()
        add_log_entry(self.job_id, self.phase, "started", f"Starting: {self.message}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)
        if exc_type is None:
            add_log_entry(
                self.job_id,
                self.phase,
                "completed",
                f"Completed: {self.message}",
                duration_ms=duration_ms,
                details=self.details if self.details else None,
            )
        else:
            error_details = {
                "error_type": exc_type.__name__,
                "error_message": str(exc_val),
                "traceback": traceback.format_exc(),
            }
            if self.details:
                error_details.update(self.details)
            add_log_entry(
                self.job_id,
                self.phase,
                "failed",
                f"Failed: {self.message} - {str(exc_val)}",
                duration_ms=duration_ms,
                details=error_details,
            )
        return False

    def add_detail(self, key: str, value):
        self.details[key] = value


def _run_vision_and_valuation(job_id, frames_dir, vehicle_info, current_cost):
    """
    Shared logic for vision analysis and market valuation phases.
    Returns (condition_report_json, condition_score, valuation_result, total_cost).
    """
    cost = current_cost
    condition_report_json = None
    condition_score = 0.0
    valuation_result = None

    # --- Vision Analysis ---
    update_job_status(job_id, JobStatus.VISION_ANALYSIS.value, 60, "Analyzing vehicle condition from frames")

    with PhaseTimer(job_id, "vision_analysis", "Vision-based condition analysis") as timer:
        vision_service = VisionService()
        condition = vision_service.analyze_vehicle_condition(frames_dir, vehicle_info)

        evidence_mapping = condition.get_evidence_frame_paths()
        if evidence_mapping:
            settings = get_settings()
            evidence_dest = settings.evidence_dir / job_id
            evidence_dest.mkdir(parents=True, exist_ok=True)
            copied = {}
            for idx, src_path in evidence_mapping.items():
                dest_name = f"evidence_{idx:03d}.jpg"
                dest_path = evidence_dest / dest_name
                try:
                    shutil.copy2(src_path, str(dest_path))
                    copied[idx] = dest_name
                except Exception as e:
                    logger.warning("Failed to copy evidence frame %s: %s", src_path, e)

            for category in ("good", "bad"):
                for obs in condition.observations.get(category, []):
                    if isinstance(obs, dict):
                        idx = obs.get("image_index", 0)
                        if idx in copied:
                            obs["evidence_frame"] = copied[idx]

        condition_report_json = json.dumps(condition.to_dict())
        condition_score = condition.overall_score
        cost += condition.cost

        timer.add_detail("condition_score", condition_score)
        timer.add_detail("good_observations", len(condition.observations.get("good", [])))
        timer.add_detail("bad_observations", len(condition.observations.get("bad", [])))
        timer.add_detail("images_analyzed", condition.images_analyzed)
        timer.add_detail("evidence_frames_copied", len(evidence_mapping))
        timer.add_detail("cost", condition.cost)
        timer.add_detail("overall_assessment", condition.overall_assessment)

    vision_summary_addendum = ""
    if condition.overall_assessment:
        vision_summary_addendum = (
            f"\n\nVisual Condition Assessment (from video frames):\n"
            f"Overall Score: {condition_score}/5\n"
            f"{condition.overall_assessment}"
        )
        good_obs = condition.observations.get("good", [])
        bad_obs = condition.observations.get("bad", [])
        if good_obs:
            items = [o["text"] if isinstance(o, dict) else o for o in good_obs[:5]]
            vision_summary_addendum += "\nPositive: " + "; ".join(items)
        if bad_obs:
            items = [o["text"] if isinstance(o, dict) else o for o in bad_obs[:5]]
            vision_summary_addendum += "\nIssues: " + "; ".join(items)

    update_job_results(
        job_id,
        condition_report=condition_report_json,
        condition_score=condition_score,
        cost=cost,
    )

    if vision_summary_addendum:
        db = get_db_session()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.summary:
                job.summary = job.summary.rstrip() + vision_summary_addendum
                db.commit()
        finally:
            db.close()

    # --- Market Valuation ---
    make = vehicle_info.get("make", "")
    model = vehicle_info.get("model", "")
    year = vehicle_info.get("year", "")

    if make and model:
        update_job_status(job_id, JobStatus.VALUATION.value, 80, "Looking up market value")

        try:
            with PhaseTimer(job_id, "valuation", "Market valuation and bid calculation") as timer:
                valuation_service = ValuationService()
                valuation_result = valuation_service.evaluate(
                    make=make,
                    model=model,
                    year=year,
                    condition_score=condition_score,
                    condition_summary=condition.overall_assessment,
                )
                cost += valuation_result.cost

                timer.add_detail("market_value_low", valuation_result.market_value_low)
                timer.add_detail("market_value_high", valuation_result.market_value_high)
                timer.add_detail("bid_range_low", valuation_result.bid_range_low)
                timer.add_detail("bid_range_high", valuation_result.bid_range_high)
                timer.add_detail("cost", valuation_result.cost)

            update_job_results(
                job_id,
                market_value_low=valuation_result.market_value_low,
                market_value_high=valuation_result.market_value_high,
                bid_range_low=valuation_result.bid_range_low,
                bid_range_high=valuation_result.bid_range_high,
                valuation_notes=valuation_result.valuation_notes,
                cost=cost,
            )
        except Exception as e:
            add_log_entry(
                job_id,
                "valuation",
                "failed",
                f"Market valuation failed (non-fatal): {str(e)}",
                details={"error_type": type(e).__name__, "traceback": traceback.format_exc()},
            )
            logger.warning("Valuation failed (non-fatal): %s", e)
    else:
        add_log_entry(job_id, "valuation", "warning", "Skipping valuation: make/model not identified from transcript")

    return condition_report_json, condition_score, valuation_result, cost


def _run_pipeline(job_id: str, video_path: str, progress_base: int = 5, progress_scale: float = 0.45):
    """
    Shared pipeline: video processing -> transcript analysis -> vision -> valuation.
    Called by both process_video_task and process_url_task after the video file is available.
    """
    total_start = time.time()

    try:
        update_job_status(job_id, JobStatus.PROCESSING_VIDEO.value, progress_base, "Starting video processing")

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
                scaled_progress = int(progress_base + (progress * progress_scale))
                update_job_status(job_id, status, scaled_progress, desc)

        with PhaseTimer(job_id, "video_processing", "Video processing pipeline") as timer:
            result = video_service.process_video(video_path, video_progress)
            transcript_path = result.transcript_json_path
            frames_dir = result.frames_dir
            timer.add_detail("transcript_path", transcript_path)
            timer.add_detail("captioned_video", result.captioned_video_path)
            timer.add_detail("duration_seconds", result.duration_seconds)
            timer.add_detail("frames_dir", frames_dir)

        try:
            with open(transcript_path, "r") as f:
                transcript_data = json.load(f)
                transcript_text = (
                    transcript_data.get("text", "") if isinstance(transcript_data, dict) else str(transcript_data)
                )
                truncated = transcript_text[:8000] if len(transcript_text) > 8000 else transcript_text
                add_log_entry(
                    job_id,
                    "transcript",
                    "info",
                    "Transcript generated",
                    details={
                        "transcript_text": truncated,
                        "total_length": len(transcript_text),
                    },
                )
        except Exception as e:
            add_log_entry(job_id, "transcript", "warning", f"Could not read transcript: {str(e)}")

        update_job_status(job_id, JobStatus.ANALYZING.value, 40, "Analyzing transcript")

        with PhaseTimer(job_id, "ai_analysis", "AI transcript analysis") as timer:
            agent_service = AgentService()

            def agent_progress(step, progress):
                if step == "processing_chunks":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 45, "Processing transcript chunks")
                elif step == "generating_summary":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 52, "Generating summary")
                elif step == "complete":
                    update_job_status(job_id, JobStatus.ANALYZING.value, 58, "Transcript analysis complete")

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
            cost=cost,
        )

        condition_report_json, condition_score, valuation_result, cost = _run_vision_and_valuation(
            job_id, frames_dir, vehicle_info, cost
        )

        complete_details = {
            "total_cost": cost,
            "vehicle": vehicle_info,
            "condition_score": condition_score,
        }
        if valuation_result:
            complete_details["bid_range"] = {
                "low": valuation_result.bid_range_low,
                "high": valuation_result.bid_range_high,
            }
            complete_details["market_value"] = {
                "low": valuation_result.market_value_low,
                "high": valuation_result.market_value_high,
            }

        total_duration = int((time.time() - total_start) * 1000)
        add_log_entry(
            job_id,
            "complete",
            "success",
            "Processing completed successfully",
            duration_ms=total_duration,
            details=complete_details,
        )

        update_job_status(job_id, JobStatus.COMPLETE.value, 100, "Complete")

    except Exception as e:
        total_duration = int((time.time() - total_start) * 1000)
        add_log_entry(
            job_id,
            "error",
            "failed",
            f"Processing failed: {str(e)}",
            duration_ms=total_duration,
            details={"error_type": type(e).__name__, "traceback": traceback.format_exc()},
        )
        update_job_status(job_id, JobStatus.FAILED.value, error=str(e))
        raise


def process_video_task(job_id: str):
    """Background task to process an uploaded video."""
    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        video_path = job.source_path
        add_log_entry(
            job_id, "init", "info", "Starting processing for uploaded video", details={"video_path": video_path}
        )
    finally:
        db.close()

    _run_pipeline(job_id, video_path, progress_base=5, progress_scale=0.45)


def process_url_task(job_id: str):
    """Background task to process a video URL."""
    settings = get_settings()

    db = get_db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        url = job.source_path
        add_log_entry(job_id, "init", "info", "Starting processing for URL", details={"url": url})
    finally:
        db.close()

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

    _run_pipeline(job_id, video_path, progress_base=12, progress_scale=0.38)
