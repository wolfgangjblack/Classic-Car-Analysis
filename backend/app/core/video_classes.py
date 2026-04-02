from pydantic import BaseModel
from typing import List, Optional


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float


class SegmentTimestamp(BaseModel):
    text: str
    start: float
    end: float
    words: Optional[List[WordTimestamp]] = None


class TranscriptData(BaseModel):
    segments: List[SegmentTimestamp]
    text: str


class VideoProcessingResult(BaseModel):
    video_path: str
    captioned_video_path: Optional[str] = None
    audio_path: Optional[str] = None
    transcript_json_path: Optional[str] = None
    transcript_txt_path: Optional[str] = None
    frames_dir: Optional[str] = None
    duration_seconds: Optional[float] = None

    class Config:
        arbitrary_types_allowed = True
