import os
import json
import base64
import glob
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from openai import OpenAI


@dataclass
class ConditionResult:
    observations: Dict[str, List[str]]
    area_scores: Dict[str, Dict]
    overall_score: float
    overall_assessment: str
    images_analyzed: int
    exterior_images_found: int
    interior_images_found: int
    cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "observations": self.observations,
            "area_scores": self.area_scores,
            "overall_score": self.overall_score,
            "overall_assessment": self.overall_assessment,
            "images_analyzed": self.images_analyzed,
            "exterior_images_found": self.exterior_images_found,
            "interior_images_found": self.interior_images_found,
        }


class VisionAnalyzer:
    AREA_WEIGHTS = {
        "exterior_paint": 1.5,
        "body_panels": 1.5,
        "chrome_trim": 1.5,
        "wheels_tires": 1.5,
        "glass": 1.0,
        "interior_seats": 1.0,
        "dashboard": 1.0,
        "carpet_headliner": 1.0,
    }

    INPUT_COST_PER_TOKEN = 2.50 / 1e6
    OUTPUT_COST_PER_TOKEN = 10.0 / 1e6

    def __init__(
        self,
        model: str = "gpt-4o",
        max_frames: int = 10,
        prompt_path: Optional[str] = None,
    ):
        self.model = model
        self.max_frames = max_frames
        self.prompt_path = prompt_path
        self._client = None
        self._prompt_template = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self._client = OpenAI(api_key=api_key)
        return self._client

    @property
    def prompt_template(self) -> str:
        if self._prompt_template is None:
            if self.prompt_path and os.path.exists(self.prompt_path):
                with open(self.prompt_path, "r") as f:
                    self._prompt_template = f.read()
            else:
                self._prompt_template = self._default_prompt()
        return self._prompt_template

    def _default_prompt(self) -> str:
        return (
            "You are an expert classic car appraiser. Analyze these images of a vehicle "
            "and assess its condition. Vehicle: {vehicle_info}. "
            "Return JSON with area_scores, observations, overall_score, and overall_assessment."
        )

    def select_frames(self, frames_dir: str) -> List[str]:
        """Select evenly-spaced frames from the directory."""
        if not os.path.isdir(frames_dir):
            raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

        frame_files = sorted(
            glob.glob(os.path.join(frames_dir, "*.jpg"))
            + glob.glob(os.path.join(frames_dir, "*.jpeg"))
            + glob.glob(os.path.join(frames_dir, "*.png"))
        )

        if not frame_files:
            raise ValueError(f"No image files found in {frames_dir}")

        if len(frame_files) <= self.max_frames:
            return frame_files

        step = len(frame_files) / self.max_frames
        selected = []
        for i in range(self.max_frames):
            idx = int(i * step)
            selected.append(frame_files[idx])
        return selected

    def encode_frame(self, frame_path: str) -> str:
        """Encode a single frame to base64."""
        with open(frame_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def build_messages(
        self, frames: List[str], vehicle_info: Dict[str, str]
    ) -> List[dict]:
        """Build the multi-image chat message for GPT-4o."""
        vehicle_str = f"{vehicle_info.get('year', 'Unknown')} {vehicle_info.get('make', 'Unknown')} {vehicle_info.get('model', 'Unknown')}"
        system_prompt = self.prompt_template.replace("{vehicle_info}", vehicle_str)

        content_parts = [
            {
                "type": "text",
                "text": (
                    f"I have {len(frames)} images extracted from a video of this {vehicle_str}. "
                    f"Please analyze every image carefully for condition assessment."
                ),
            }
        ]

        for i, frame_path in enumerate(frames):
            b64 = self.encode_frame(frame_path)
            ext = os.path.splitext(frame_path)[1].lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": "high",
                    },
                }
            )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_parts},
        ]

    def _parse_response(self, raw_text: str) -> dict:
        """Extract JSON from the model response, handling markdown fences."""
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    def _compute_overall_score(self, area_scores: Dict[str, Dict]) -> float:
        """Weighted average of visible area scores."""
        total_weight = 0.0
        weighted_sum = 0.0
        for area, data in area_scores.items():
            score = data.get("score", 0)
            if score > 0:
                w = self.AREA_WEIGHTS.get(area, 1.0)
                weighted_sum += score * w
                total_weight += w
        if total_weight == 0:
            return 0.0
        return round(weighted_sum / total_weight, 2)

    def analyze_frames(
        self, frames_dir: str, vehicle_info: Dict[str, str]
    ) -> ConditionResult:
        """
        Run the full vision analysis pipeline.

        Args:
            frames_dir: Path to directory containing extracted frames
            vehicle_info: Dict with make, model, year keys

        Returns:
            ConditionResult with scores, observations, and cost
        """
        frames = self.select_frames(frames_dir)
        print(f"Selected {len(frames)} frames for vision analysis")

        messages = self.build_messages(frames, vehicle_info)

        print(f"Sending {len(frames)} images to {self.model} for condition analysis...")
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=2000,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        raw = completion.choices[0].message.content
        cost = (
            completion.usage.prompt_tokens * self.INPUT_COST_PER_TOKEN
            + completion.usage.completion_tokens * self.OUTPUT_COST_PER_TOKEN
        )

        print(f"Vision analysis complete. Cost: ${cost:.4f}")

        parsed = self._parse_response(raw)

        area_scores = parsed.get("area_scores", {})
        overall = self._compute_overall_score(area_scores)
        if parsed.get("overall_score", 0) > 0:
            overall = parsed["overall_score"]

        return ConditionResult(
            observations=parsed.get("observations", {"good": [], "bad": []}),
            area_scores=area_scores,
            overall_score=overall,
            overall_assessment=parsed.get("overall_assessment", ""),
            images_analyzed=parsed.get("images_analyzed", len(frames)),
            exterior_images_found=parsed.get("exterior_images_found", 0),
            interior_images_found=parsed.get("interior_images_found", 0),
            cost=cost,
        )
