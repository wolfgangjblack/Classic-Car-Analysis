import os
import re
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp

from ..exceptions import DownloadError


class VideoDownloader:
    """Service for downloading videos from URLs"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        url: str,
        job_id: str,
        progress_callback: Optional[callable] = None
    ) -> Tuple[str, str]:
        """
        Download video from YouTube or direct URL.

        Args:
            url: Video URL (YouTube, Vimeo, direct link, etc.)
            job_id: Job ID to use as filename prefix
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of (local_path, original_title)
        """
        output_template = str(self.output_dir / f"{job_id}.%(ext)s")

        ydl_opts = {
            # Ensure we get video WITH audio - critical for transcription
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }

        if progress_callback:
            def progress_hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        progress_callback("downloading", percent)
                elif d['status'] == 'finished':
                    progress_callback("download_complete", 100)

            ydl_opts['progress_hooks'] = [progress_hook]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                title = info.get('title', 'Unknown')

                if not os.path.exists(filename):
                    for ext in ['.mp4', '.webm', '.mkv', '.mov']:
                        potential = str(self.output_dir / f"{job_id}{ext}")
                        if os.path.exists(potential):
                            filename = potential
                            break

                return filename, title

        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(f"Failed to download video: {str(e)}") from e
        except Exception as e:
            raise DownloadError(f"Download error: {str(e)}") from e

    def is_youtube_url(self, url: str) -> bool:
        """Check if URL is a YouTube URL"""
        youtube_patterns = [
            r'(youtube\.com/watch\?v=)',
            r'(youtu\.be/)',
            r'(youtube\.com/embed/)',
            r'(youtube\.com/v/)',
        ]
        return any(re.search(pattern, url) for pattern in youtube_patterns)

    def is_supported_url(self, url: str) -> bool:
        """Check if URL is supported by yt-dlp"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                ydl.extract_info(url, download=False)
                return True
        except Exception:
            return False


def download_video(url: str, output_dir: str, job_id: str) -> Tuple[str, str]:
    """
    Convenience function to download a video.

    Args:
        url: Video URL
        output_dir: Directory to save the video
        job_id: Job ID for filename

    Returns:
        Tuple of (local_path, original_title)
    """
    downloader = VideoDownloader(output_dir)
    return downloader.download(url, job_id)
