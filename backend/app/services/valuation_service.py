from ..config import get_settings
from ..core.valuation import ValuationEngine, ValuationResult


class ValuationService:
    """Service wrapper for market valuation and bid price calculation."""

    def __init__(self):
        self.settings = get_settings()
        self._engine = None

    @property
    def engine(self) -> ValuationEngine:
        if self._engine is None:
            self._engine = ValuationEngine(model=self.settings.vision_model)
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
