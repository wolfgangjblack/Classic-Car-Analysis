import os
import subprocess
import whisper
import cv2
from pathlib import Path
from datetime import timedelta
from utils.video_classes import WordTimestamp, SegmentTimestamp, TranscriptData, VideoProcessingResult

class VideoProcessingPipeline:
    def __init__(
        self, 
        output_dir="processed_videos", 
        model_size="medium", 
        extract_frames_interval=5,
        subtitle_style="FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2"):
        """
        Initialize the video processing pipeline
        
        Args:
            output_dir: Base directory for all outputs
            model_size: Whisper model size ("tiny", "base", "small", "medium", "large")
            extract_frames_interval: Interval in seconds for extracting frames
            subtitle_style: FFmpeg subtitle styling
        """
        self.output_dir = output_dir
        self.model_size = model_size
        self.extract_frames_interval = extract_frames_interval
        self.subtitle_style = subtitle_style
        self.whisper_model = None
    
        # Create base directory structure
        os.makedirs(output_dir, exist_ok=True)
        self.transcript_dir = os.path.join(output_dir, "transcripts")
        self.frames_dir = os.path.join(output_dir, "frames")
        self.captioned_dir = os.path.join(output_dir, "captioned")
        self.audio_dir = os.path.join(output_dir, "audio")
        
        os.makedirs(self.transcript_dir, exist_ok=True)
        os.makedirs(self.frames_dir, exist_ok=True)
        os.makedirs(self.captioned_dir, exist_ok=True)
        os.makedirs(self.audio_dir, exist_ok=True)
    
    def _load_model(self):
        """Lazy-load the Whisper model when needed"""
        if self.whisper_model is None:
            
            self.whisper_model = whisper.load_model(self.model_size)
        return self.whisper_model
    
    def extract_audio(self, video_path, audio_path):
        """Extract audio from video using ffmpeg"""

        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        
        command = [
            "ffmpeg", "-i", video_path, 
            "-ar", "16000", "-ac", "1", 
            "-c:a", "pcm_s16le", audio_path
        ]
        
        subprocess.run(command, check=True)
        
        # Verify the file was created
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Failed to create audio file at {audio_path}")
        
        return audio_path
    
    def transcribe_audio(self, audio_path):
        """Transcribe audio using Whisper with word-level timestamps"""
        # Verify the audio file exists before attempting to transcribe
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found at {audio_path}")
        
        # Load the model
        model = self._load_model()
        
        # Transcribe with word timestamps
        result = model.transcribe(audio_path, word_timestamps=True)
        
        # Convert to our data model
        transcript = TranscriptData(
            segments=[
                SegmentTimestamp(
                    text=segment["text"],
                    start=segment["start"],
                    end=segment["end"],
                    words=[
                        WordTimestamp(
                            word=word["word"],
                            start=word["start"],
                            end=word["end"]
                        ) for word in segment.get("words", [])
                    ] if "words" in segment else None
                ) for segment in result["segments"]
            ],
            text=result["text"]
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
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{td.microseconds//1000:03d}"
    
    def create_subtitle_file(self, transcript, output_srt_path):
        """Create an SRT subtitle file with words appearing as they're spoken"""
        segments = transcript.segments
        
        with open(output_srt_path, 'w', encoding='utf-8') as srt_file:
            subtitle_index = 1
            
            for segment in segments:
                if segment.words:
                    # Group words into manageable chunks
                    word_groups = []
                    current_group = []
                    current_start = None
                    
                    for word in segment.words:
                        if current_start is None:
                            current_start = word.start
                        
                        current_group.append(word)
                        
                        # Create a new group after every 3-5 words or if silence is detected
                        if len(current_group) >= 4:
                            word_groups.append({
                                "start": current_start,
                                "end": word.end,
                                "words": current_group
                            })
                            current_group = []
                            current_start = None
                    
                    # Add any remaining words
                    if current_group:
                        word_groups.append({
                            "start": current_start,
                            "end": current_group[-1].end,
                            "words": current_group
                        })
                    
                    # Create subtitles for each word group
                    for group in word_groups:
                        start_time = group["start"]
                        end_time = group["end"]
                        
                        # Format times for SRT (HH:MM:SS,mmm)
                        start_formatted = self.format_timestamp(start_time)
                        end_formatted = self.format_timestamp(end_time)
                        
                        # Create subtitle text
                        text = " ".join(word.word for word in group["words"])
                        
                        # Write to SRT file
                        srt_file.write(f"{subtitle_index}\n")
                        srt_file.write(f"{start_formatted} --> {end_formatted}\n")
                        srt_file.write(f"{text.strip()}\n\n")
                        
                        subtitle_index += 1
        
        return output_srt_path
    
    def add_subtitles_to_video(self, video_path, subtitle_path, output_path):
        """Add subtitles to video using FFmpeg"""
        command = [
            "ffmpeg", "-i", video_path,
            "-vf", f"subtitles={subtitle_path}:force_style='{self.subtitle_style}'",
            "-c:a", "copy", output_path
        ]
        
        subprocess.run(command, check=True)
        return output_path
    
    def save_transcript_formats(self, transcript, json_path, txt_path):
        """Save transcript in both JSON and human-readable formats"""
        # Save as JSON
        with open(json_path, 'w', encoding='utf-8') as json_file:
            json_content = transcript.model_dump_json(indent=2)
            json_file.write(json_content)
        
        # Save as formatted text
        with open(txt_path, 'w', encoding='utf-8') as txt_file:
            for segment in transcript.segments:
                start_formatted = self.format_timestamp_readable(segment.start)
                end_formatted = self.format_timestamp_readable(segment.end)
                
                txt_file.write(f"[{start_formatted} - {end_formatted}] {segment.text.strip()}\n")
                
                # Include word-level timestamps if available
                if segment.words:
                    for word in segment.words:
                        word_start = self.format_timestamp_readable(word.start)
                        word_end = self.format_timestamp_readable(word.end)
                        txt_file.write(f"    [{word_start} - {word_end}] {word.word.strip()}\n")
                    
                    txt_file.write("\n")
        
        return json_path, txt_path
    
    def extract_keyframes(self, video_path, output_dir):
        """Extract frames at regular intervals"""
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Open video
        video = cv2.VideoCapture(video_path)
        if not video.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
        
        # Get video properties
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        
        # Calculate frames to extract
        frames_to_extract = []
        for time_pos in range(0, int(duration), self.extract_frames_interval):
            frames_to_extract.append(int(time_pos * fps))
        
        # Extract frames
        for i, frame_idx in enumerate(frames_to_extract):
            video.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = video.read()
            if ret:
                time_pos = frame_idx / fps
                formatted_time = self.format_timestamp_readable(time_pos)
                # Use a filename format that's easy to parse back to timestamp
                output_path = os.path.join(output_dir, f"frame_{time_pos:.3f}_{formatted_time.replace(':', '-')}.jpg")
                cv2.imwrite(output_path, frame)
        
        video.release()
        return output_dir, duration
    
    def process_video(self, video_path):
        """Process a video, create captioned version, save transcript and extract frames"""
        # Convert to absolute paths
        video_path = os.path.abspath(video_path)
        
        # Get filename without extension
        filename = Path(video_path).stem.replace(' ', '_').replace('-', '_')
        file_extension = Path(video_path).suffix
        
        # Define output paths
        audio_path = os.path.join(self.audio_dir, f"{filename}.wav")
        subtitle_path = os.path.join(self.transcript_dir, f"{filename}.srt")
        json_path = os.path.join(self.transcript_dir, f"{filename}.json")
        txt_path = os.path.join(self.transcript_dir, f"{filename}.txt")
        captioned_video_path = os.path.join(self.captioned_dir, f"{filename}_captioned{file_extension}")
        video_frames_dir = os.path.join(self.frames_dir, filename)
        
        # 1. Extract audio
        print(f"Extracting audio from {video_path}...")
        self.extract_audio(video_path, audio_path)
        
        # 2. Transcribe with timestamps
        print("Transcribing audio with word-level timestamps (this may take a while)...")
        transcript = self.transcribe_audio(audio_path)
        
        # 3. Save transcript in different formats
        print("Saving transcript data...")
        self.save_transcript_formats(transcript, json_path, txt_path)
        
        # 4. Create subtitle file
        print("Creating subtitle file...")
        self.create_subtitle_file(transcript, subtitle_path)
        
        # 5. Add subtitles to video
        print(f"Adding subtitles to create captioned video...")
        self.add_subtitles_to_video(video_path, subtitle_path, captioned_video_path)
        
        # 6. Extract keyframes
        print(f"Extracting frames at {self.extract_frames_interval} second intervals...")
        frames_dir, duration = self.extract_keyframes(video_path, video_frames_dir)
        
        # 7. Create and return the result object
        result = VideoProcessingResult(
            video_path=video_path,
            captioned_video_path=captioned_video_path,
            audio_path=audio_path,
            transcript_json_path=json_path,
            transcript_txt_path=txt_path,
            frames_dir=video_frames_dir,
            duration_seconds=duration
        )
        
        print(f"Video processing complete. Results:")
        print(f"- Captioned video: {captioned_video_path}")
        print(f"- Transcript JSON: {json_path}")
        print(f"- Transcript TXT: {txt_path}")
        print(f"- Extracted frames: {video_frames_dir}")
        
        return result
    
    def batch_process(self, video_paths):
        """Process multiple videos in batch"""
        results = []
        for video_path in video_paths:
            try:
                result = self.process_video(video_path)
                results.append(result)
            except Exception as e:
                print(f"Error processing {video_path}: {e}")
        return results
