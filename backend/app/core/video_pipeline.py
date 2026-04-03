import logging
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Optional

import cv2
from openai import OpenAI

from ..exceptions import VideoProcessingError
from .retry import openai_retry
from .video_classes import SegmentTimestamp, TranscriptData, VideoProcessingResult, WordTimestamp

logger = logging.getLogger(__name__)


class VideoProcessingPipeline:
    def __init__(
        self,
        output_dir: str = "processed_videos",
        model_size: str = "medium",
        extract_frames_interval: int = 5,
        subtitle_style: str = (
            "FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2"
        ),
        use_openai_whisper: bool = True,
        client: Optional[OpenAI] = None,
    ):
        """
        Initialize the video processing pipeline

        Args:
            output_dir: Base directory for all outputs
            model_size: Whisper model size (ignored when using OpenAI API)
            extract_frames_interval: Interval in seconds for extracting frames
            subtitle_style: FFmpeg subtitle styling
            use_openai_whisper: If True, use OpenAI's Whisper API (more reliable)
            client: Shared OpenAI client (falls back to deps.get_openai_client)
        """
        self.output_dir = output_dir
        self.model_size = model_size
        self.extract_frames_interval = extract_frames_interval
        self.subtitle_style = subtitle_style
        self.use_openai_whisper = use_openai_whisper
        self.whisper_model = None
        self._client = client

        os.makedirs(output_dir, exist_ok=True)
        self.transcript_dir = os.path.join(output_dir, "transcripts")
        self.frames_dir = os.path.join(output_dir, "frames")
        self.captioned_dir = os.path.join(output_dir, "captioned")
        self.audio_dir = os.path.join(output_dir, "audio")

        os.makedirs(self.transcript_dir, exist_ok=True)
        os.makedirs(self.frames_dir, exist_ok=True)
        os.makedirs(self.captioned_dir, exist_ok=True)
        os.makedirs(self.audio_dir, exist_ok=True)

    @property
    def client(self) -> OpenAI:
        """Shared OpenAI client for Whisper API."""
        if self._client is None:
            from ..deps import get_openai_client

            self._client = get_openai_client()
        return self._client

    def _load_model(self):
        """Lazy-load the local Whisper model when needed"""
        if self.whisper_model is None:
            import whisper

            self.whisper_model = whisper.load_model(self.model_size)
        return self.whisper_model

    def extract_audio(self, video_path: str, audio_path: str) -> str:
        """Extract audio from video using ffmpeg"""
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)

        command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",  # No video
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            audio_path,
        ]

        logger.info("Extracting audio from %s", video_path)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise VideoProcessingError(f"FFmpeg audio extraction timed out for {video_path}")

        if result.returncode != 0:
            logger.error("FFmpeg stderr: %s", result.stderr)
            raise VideoProcessingError(f"FFmpeg audio extraction failed: {result.stderr[:500]}")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Failed to create audio file at {audio_path}")

        # Validate the audio file has actual content
        file_size = os.path.getsize(audio_path)
        logger.info("Extracted audio file size: %d bytes", file_size)

        if file_size < 1000:  # Less than 1KB is likely empty/corrupt
            raise VideoProcessingError(
                f"Audio extraction produced empty file ({file_size} bytes). Video may not have audio track."
            )

        return audio_path

    def transcribe_audio(self, audio_path: str) -> TranscriptData:
        """Transcribe audio using Whisper (OpenAI API or local model)"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found at {audio_path}")

        if self.use_openai_whisper:
            return self._transcribe_with_openai(audio_path)
        else:
            return self._transcribe_with_local_whisper(audio_path)

    @openai_retry
    def _transcribe_with_openai(self, audio_path: str) -> TranscriptData:
        """Transcribe using OpenAI's Whisper API"""
        logger.info("Transcribing with OpenAI Whisper API: %s", audio_path)
        client = self.client

        # Get file size to check if we need to handle large files
        file_size = os.path.getsize(audio_path)
        logger.info("Audio file size: %.2f MB", file_size / (1024 * 1024))

        # OpenAI Whisper API limit is 25MB
        if file_size > 25 * 1024 * 1024:
            logger.warning("Audio file is larger than 25MB, may need to chunk")

        with open(audio_path, "rb") as audio_file:
            # Use verbose_json to get timestamps
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )

        # Convert OpenAI response to our TranscriptData format
        segments = []
        if hasattr(result, "segments") and result.segments:
            for segment in result.segments:
                words = None
                if hasattr(result, "words") and result.words:
                    # Filter words that belong to this segment
                    segment_words = [w for w in result.words if w.start >= segment.start and w.end <= segment.end]
                    if segment_words:
                        words = [WordTimestamp(word=w.word, start=w.start, end=w.end) for w in segment_words]

                segments.append(SegmentTimestamp(text=segment.text, start=segment.start, end=segment.end, words=words))

        transcript = TranscriptData(segments=segments, text=result.text if hasattr(result, "text") else "")

        logger.info("OpenAI Whisper transcription complete. Text length: %d", len(transcript.text))
        return transcript

    def _transcribe_with_local_whisper(self, audio_path: str) -> TranscriptData:
        """Transcribe using local Whisper model"""
        logger.info("Transcribing with local Whisper model: %s", audio_path)
        model = self._load_model()
        result = model.transcribe(audio_path, word_timestamps=True)

        transcript = TranscriptData(
            segments=[
                SegmentTimestamp(
                    text=segment["text"],
                    start=segment["start"],
                    end=segment["end"],
                    words=[
                        WordTimestamp(word=word["word"], start=word["start"], end=word["end"])
                        for word in segment.get("words", [])
                    ]
                    if "words" in segment
                    else None,
                )
                for segment in result["segments"]
            ],
            text=result["text"],
        )

        return transcript

    @staticmethod
    def format_timestamp(seconds):
        """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)"""
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        seconds_val = seconds % 60
        milliseconds = int((seconds_val - int(seconds_val)) * 1000)

        return f"{hours:02d}:{minutes:02d}:{int(seconds_val):02d},{milliseconds:03d}"

    @staticmethod
    def format_timestamp_readable(seconds):
        """Convert seconds to readable timestamp format (HH:MM:SS.mmm)"""
        td = timedelta(seconds=seconds)
        minutes, seconds = divmod(td.seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{td.microseconds // 1000:03d}"

    def create_subtitle_file(self, transcript: TranscriptData, output_srt_path: str) -> str:
        """Create an SRT subtitle file with words appearing as they're spoken"""
        segments = transcript.segments

        with open(output_srt_path, "w", encoding="utf-8") as srt_file:
            subtitle_index = 1

            for segment in segments:
                if segment.words:
                    word_groups = []
                    current_group = []
                    current_start = None

                    for word in segment.words:
                        if current_start is None:
                            current_start = word.start

                        current_group.append(word)

                        if len(current_group) >= 4:
                            word_groups.append({"start": current_start, "end": word.end, "words": current_group})
                            current_group = []
                            current_start = None

                    if current_group:
                        word_groups.append(
                            {"start": current_start, "end": current_group[-1].end, "words": current_group}
                        )

                    for group in word_groups:
                        start_time = group["start"]
                        end_time = group["end"]

                        start_formatted = self.format_timestamp(start_time)
                        end_formatted = self.format_timestamp(end_time)

                        text = " ".join(
                            w.word
                            for w in group["words"]  # type: ignore[attr-defined]
                        )

                        srt_file.write(f"{subtitle_index}\n")
                        srt_file.write(f"{start_formatted} --> {end_formatted}\n")
                        srt_file.write(f"{text.strip()}\n\n")

                        subtitle_index += 1

        return output_srt_path

    def add_subtitles_to_video(self, video_path: str, subtitle_path: str, output_path: str) -> Optional[str]:
        """Add subtitles to video using FFmpeg"""
        if not os.path.exists(subtitle_path):
            logger.warning("Subtitle file not found: %s", subtitle_path)
            return None

        escaped_path = subtitle_path.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"subtitles='{escaped_path}':force_style='{self.subtitle_style}'",
            "-c:a",
            "copy",
            output_path,
        ]

        try:
            subprocess.run(command, check=True, capture_output=True, timeout=300)
            return output_path
        except subprocess.TimeoutExpired:
            logger.warning("Subtitle burning timed out for %s", video_path)
            return None
        except subprocess.CalledProcessError as e:
            logger.warning("Failed to add subtitles to video: %s", e)
            logger.debug("Stderr: %s", e.stderr.decode() if e.stderr else "N/A")
            return None

    def save_transcript_formats(self, transcript: TranscriptData, json_path: str, txt_path: str) -> tuple[str, str]:
        """Save transcript in both JSON and human-readable formats"""
        with open(json_path, "w", encoding="utf-8") as json_file:
            json_content = transcript.model_dump_json(indent=2)
            json_file.write(json_content)

        with open(txt_path, "w", encoding="utf-8") as txt_file:
            for segment in transcript.segments:
                start_formatted = self.format_timestamp_readable(segment.start)
                end_formatted = self.format_timestamp_readable(segment.end)

                txt_file.write(f"[{start_formatted} - {end_formatted}] {segment.text.strip()}\n")

                if segment.words:
                    for word in segment.words:
                        word_start = self.format_timestamp_readable(word.start)
                        word_end = self.format_timestamp_readable(word.end)
                        txt_file.write(f"    [{word_start} - {word_end}] {word.word.strip()}\n")

                    txt_file.write("\n")

        return json_path, txt_path

    def extract_keyframes(self, video_path: str, output_dir: str) -> tuple[str, float]:
        """Extract frames at regular intervals"""
        os.makedirs(output_dir, exist_ok=True)

        video = cv2.VideoCapture(video_path)
        if not video.isOpened():
            raise VideoProcessingError(f"Could not open video file: {video_path}")

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps

        frames_to_extract = []
        for time_pos in range(0, int(duration), self.extract_frames_interval):
            frames_to_extract.append(int(time_pos * fps))

        for i, frame_idx in enumerate(frames_to_extract):
            video.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = video.read()
            if ret:
                time_pos_sec = frame_idx / fps
                formatted_time = self.format_timestamp_readable(time_pos_sec)
                output_path = os.path.join(
                    output_dir, f"frame_{time_pos_sec:.3f}_{formatted_time.replace(':', '-')}.jpg"
                )
                cv2.imwrite(output_path, frame)

        video.release()
        return output_dir, duration

    def process_video(self, video_path: str, progress_callback=None) -> VideoProcessingResult:
        """Process a video, create captioned version, save transcript and extract frames"""
        video_path = os.path.abspath(video_path)

        filename = Path(video_path).stem.replace(" ", "_").replace("-", "_")
        file_extension = Path(video_path).suffix

        audio_path = os.path.join(self.audio_dir, f"{filename}.wav")
        subtitle_path = os.path.join(self.transcript_dir, f"{filename}.srt")
        json_path = os.path.join(self.transcript_dir, f"{filename}.json")
        txt_path = os.path.join(self.transcript_dir, f"{filename}.txt")
        captioned_video_path = os.path.join(self.captioned_dir, f"{filename}_captioned{file_extension}")
        video_frames_dir = os.path.join(self.frames_dir, filename)

        if progress_callback:
            progress_callback("extracting_audio", 10)
        logger.info("Extracting audio from %s", video_path)
        self.extract_audio(video_path, audio_path)

        if progress_callback:
            progress_callback("transcribing", 30)
        logger.info("Transcribing audio with word-level timestamps")
        transcript = self.transcribe_audio(audio_path)

        if progress_callback:
            progress_callback("saving_transcript", 60)
        logger.info("Saving transcript data")
        self.save_transcript_formats(transcript, json_path, txt_path)

        if progress_callback:
            progress_callback("creating_subtitles", 70)
        logger.info("Creating subtitle file")
        self.create_subtitle_file(transcript, subtitle_path)

        if progress_callback:
            progress_callback("adding_subtitles", 80)
        logger.info("Adding subtitles to create captioned video")
        captioned_result = self.add_subtitles_to_video(video_path, subtitle_path, captioned_video_path)
        captioned_video_path_out: Optional[str] = captioned_video_path
        if not captioned_result:
            captioned_video_path_out = None
            logger.warning("Skipping captioned video (subtitle burning failed)")

        if progress_callback:
            progress_callback("extracting_frames", 90)
        logger.info("Extracting frames at %d second intervals", self.extract_frames_interval)
        frames_dir, duration = self.extract_keyframes(video_path, video_frames_dir)

        result = VideoProcessingResult(
            video_path=video_path,
            captioned_video_path=captioned_video_path_out,
            audio_path=audio_path,
            transcript_json_path=json_path,
            transcript_txt_path=txt_path,
            frames_dir=video_frames_dir,
            duration_seconds=duration,
        )

        if progress_callback:
            progress_callback("complete", 100)

        logger.info(
            "Video processing complete. Captioned=%s, Transcript=%s, Frames=%s",
            captioned_video_path,
            json_path,
            video_frames_dir,
        )

        return result

    def batch_process(self, video_paths: list[str]) -> list[VideoProcessingResult]:
        """Process multiple videos in batch"""
        results = []
        for video_path in video_paths:
            try:
                result = self.process_video(video_path)
                results.append(result)
            except Exception as e:
                logger.error("Error processing %s: %s", video_path, e)
        return results
