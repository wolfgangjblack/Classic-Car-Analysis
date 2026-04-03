from typing import Optional

from openai import OpenAI

from ..config import get_settings
from ..core.valuation import ValuationEngine, ValuationResult
from ..deps import get_openai_client


class ValuationService:
    """Service wrapper for market valuation and bid price calculation."""

    def __init__(self, client: Optional[OpenAI] = None):
        self.settings = get_settings()
        self._client = client
        self._engine: Optional[ValuationEngine] = None

    @property
    def engine(self) -> ValuationEngine:
        if self._engine is None:
            self._engine = ValuationEngine(
                model=self.settings.vision_model,
                client=self._client or get_openai_client(),
            )
        return self._engine

    def evaluate(
        self,
        make: str,
        model: str,
        year: str,
        condition_score: float,
        condition_summary: str = "",
    ) -> ValuationResult:
        return self.engine.evaluate(make, model, year, condition_score, condition_summary)


def get_valuation_service() -> ValuationService:
    return ValuationService()
