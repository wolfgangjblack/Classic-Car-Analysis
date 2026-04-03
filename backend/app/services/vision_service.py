import os
from typing import Dict, Optional

from openai import OpenAI

from ..config import get_settings
from ..core.vision_analyzer import ConditionResult, VisionAnalyzer
from ..deps import get_openai_client


class VisionService:
    """Service wrapper for vision-based condition analysis."""

    def __init__(self, client: Optional[OpenAI] = None):
        self.settings = get_settings()
        self._client = client
        self._analyzer: Optional[VisionAnalyzer] = None

    @property
    def analyzer(self) -> VisionAnalyzer:
        if self._analyzer is None:
            prompt_path = os.path.join(str(self.settings.agent_prompts_dir), "visionConditionAgent.txt")
            self._analyzer = VisionAnalyzer(
                model=self.settings.vision_model,
                max_frames=self.settings.max_vision_frames,
                prompt_path=prompt_path,
                client=self._client or get_openai_client(),
            )
        return self._analyzer

    def analyze_vehicle_condition(self, frames_dir: str, vehicle_info: Dict[str, str]) -> ConditionResult:
        return self.analyzer.analyze_frames(frames_dir, vehicle_info)


def get_vision_service() -> VisionService:
    return VisionService()
