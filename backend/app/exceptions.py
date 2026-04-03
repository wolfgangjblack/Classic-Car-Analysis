"""Custom exception hierarchy for the Classic Car Analysis pipeline."""


class CarAnalysisError(Exception):
    """Base exception for all pipeline errors."""


class VideoProcessingError(CarAnalysisError):
    """Raised when video processing (audio extraction, frame extraction) fails."""


class TranscriptionError(CarAnalysisError):
    """Raised when audio transcription fails."""


class DownloadError(CarAnalysisError):
    """Raised when video download from a URL fails."""


class AgentError(CarAnalysisError):
    """Raised when an AI agent call or pipeline step fails."""


class VisionAnalysisError(CarAnalysisError):
    """Raised when GPT-4o vision condition analysis fails."""


class ValuationError(CarAnalysisError):
    """Raised when market valuation lookup or bid calculation fails."""
