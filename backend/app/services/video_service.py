from pathlib import Path
from typing import Callable, Optional

from openai import OpenAI

from ..config import get_settings
from ..core.video_pipeline import VideoProcessingPipeline
from ..deps import get_openai_client


class VideoService:
    """Service wrapper for video processing pipeline"""

    def __init__(self, client: Optional[OpenAI] = None):
        self.settings = get_settings()
        self._client = client
        self._pipeline = None

    @property
    def pipeline(self) -> VideoProcessingPipeline:
        """Lazy-load the video processing pipeline"""
        if self._pipeline is None:
            self._pipeline = VideoProcessingPipeline(
                output_dir=str(self.settings.processed_dir),
                model_size=self.settings.whisper_model_size,
                extract_frames_interval=self.settings.frame_extract_interval,
                use_openai_whisper=True,
                client=self._client or get_openai_client(),
            )
        return self._pipeline

    def process_video(self, video_path: str, progress_callback: Optional[Callable] = None):
        """
        Process a video file.

        Args:
            video_path: Path to the video file
            progress_callback: Optional callback for progress updates

        Returns:
            VideoProcessingResult
        """
        return self.pipeline.process_video(video_path, progress_callback)

    def get_transcript_path(self, video_path: str) -> str:
        """Get the expected transcript path for a video"""
        filename = Path(video_path).stem.replace(" ", "_").replace("-", "_")
        return str(self.settings.transcripts_dir / f"{filename}.json")


def get_video_service() -> VideoService:
    """Get video service instance"""
    return VideoService()
