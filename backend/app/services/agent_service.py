import os
import json
from pathlib import Path
from typing import Optional, Dict, Callable

from openai import OpenAI

from ..config import get_settings
from ..deps import get_openai_client
from ..core.agents import AgentPipeline


class AgentService:
    """Service wrapper for agent pipeline"""

    def __init__(self, client: Optional[OpenAI] = None):
        self.settings = get_settings()
        self._client = client
        self._pipeline = None

    @property
    def pipeline(self) -> AgentPipeline:
        """Lazy-load the agent pipeline"""
        if self._pipeline is None:
            self._pipeline = AgentPipeline(
                agents_dir=str(self.settings.agent_prompts_dir),
                client=self._client or get_openai_client(),
            )
        return self._pipeline

    def process_transcript(
        self,
        transcript_path: str,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Process a transcript and generate summary.

        Args:
            transcript_path: Path to the transcript JSON file
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with processing results
        """
        result = self.pipeline.process_transcript(
            transcript_path,
            parallel=True,
            return_results=True,
            progress_callback=progress_callback
        )
        return result

    def get_summary(self, transcript_name: str) -> Optional[str]:
        """Get summary for a transcript"""
        return self.pipeline.summaries.get(transcript_name)

    def get_cost(self, transcript_name: str) -> float:
        """Get processing cost for a transcript"""
        if transcript_name in self.pipeline.data:
            return self.pipeline.data[transcript_name].get('token_costs', 0.0)
        return 0.0

    def extract_vehicle_info(self, transcript_name: str) -> Dict:
        """
        Extract vehicle information from processing results.

        Returns:
            Dictionary with make, model, year
        """
        if transcript_name not in self.pipeline.data:
            return {"make": None, "model": None, "year": None}

        results = self.pipeline.data[transcript_name].get('processing_results', {})

        make = None
        model = None
        year = None

        if 'basicAgent' in results:
            basic_data = results['basicAgent']
            if 'make' in basic_data and basic_data['make']:
                makes = [m for m in basic_data['make'] if m]
                if makes:
                    make = makes[0]
            if 'model' in basic_data and basic_data['model']:
                models = [m for m in basic_data['model'] if m]
                if models:
                    model = models[0]
            if 'year' in basic_data and basic_data['year']:
                years = [y for y in basic_data['year'] if y]
                if years:
                    year = years[0]

        return {"make": make, "model": model, "year": year}

    def save_summary(self, transcript_name: str, output_dir: str) -> str:
        """
        Save summary to file.

        Returns:
            Path to saved summary file
        """
        os.makedirs(output_dir, exist_ok=True)

        summary = self.get_summary(transcript_name)
        cost = self.get_cost(transcript_name)

        output_path = os.path.join(output_dir, f"{transcript_name}_summary.txt")

        with open(output_path, 'w') as f:
            f.write(summary or "No summary available")
            f.write(f"\n\n{'='*50}\nToken Cost: ${cost:.6f}")

        return output_path


def get_agent_service() -> AgentService:
    """Get agent service instance"""
    return AgentService()
