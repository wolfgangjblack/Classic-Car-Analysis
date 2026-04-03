import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Database
    database_url: str = Field(default="sqlite:///./data/jobs.db", alias="DATABASE_URL")

    # Paths
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    agent_prompts_dir: Path = Field(default=Path("./agent_prompts"), alias="AGENT_PROMPTS_DIR")

    # Video Processing
    whisper_model_size: str = Field(default="medium", alias="WHISPER_MODEL_SIZE")
    frame_extract_interval: int = Field(default=5, alias="FRAME_EXTRACT_INTERVAL")

    # Vision Analysis
    vision_model: str = Field(default="gpt-4o", alias="VISION_MODEL")
    max_vision_frames: int = Field(default=10, alias="MAX_VISION_FRAMES")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Limits
    max_upload_size_mb: int = Field(default=500, alias="MAX_UPLOAD_SIZE_MB")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed_videos"

    @property
    def transcripts_dir(self) -> Path:
        return self.processed_dir / "transcripts"

    @property
    def evidence_dir(self) -> Path:
        return self.processed_dir / "evidence"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    def ensure_directories(self):
        """Create all required directories"""
        dirs = [
            self.data_dir,
            self.videos_dir,
            self.processed_dir,
            self.transcripts_dir,
            self.evidence_dir,
            self.results_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def configure_logging() -> None:
    """Set up root logging based on the LOG_LEVEL environment variable."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
