import json
import logging
import re
from typing import Optional, Tuple
from dataclasses import dataclass

from openai import OpenAI

from ..exceptions import ValuationError
from .retry import openai_retry

logger = logging.getLogger(__name__)


@dataclass
class ValuationResult:
    market_value_low: float
    market_value_high: float
    bid_range_low: float
    bid_range_high: float
    valuation_notes: str
    sources: list
    cost: float = 0.0


class ValuationEngine:
    """Looks up market value via OpenAI web search and calculates bid range."""

    CONDITION_MULTIPLIERS = {
        5.0: (0.95, 1.05),
        4.0: (0.80, 0.95),
        3.0: (0.60, 0.80),
        2.0: (0.40, 0.60),
        1.0: (0.25, 0.45),
    }

    INPUT_COST_PER_TOKEN = 2.50 / 1e6
    OUTPUT_COST_PER_TOKEN = 10.0 / 1e6
    SEARCH_COST_PER_CALL = 0.025

    def __init__(self, model: str = "gpt-4o", client: Optional[OpenAI] = None):
        self.model = model
        self._client = client

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            from ..deps import get_openai_client
            self._client = get_openai_client()
        return self._client

    def _get_condition_multiplier(self, score: float) -> Tuple[float, float]:
        """Interpolate condition multiplier from the score."""
        if score >= 5.0:
            return self.CONDITION_MULTIPLIERS[5.0]
        if score <= 1.0:
            return self.CONDITION_MULTIPLIERS[1.0]

        lower = int(score)
        upper = lower + 1
        frac = score - lower

        low_mult = self.CONDITION_MULTIPLIERS[float(lower)]
        high_mult = self.CONDITION_MULTIPLIERS[float(upper)]

        return (
            low_mult[0] + frac * (high_mult[0] - low_mult[0]),
            low_mult[1] + frac * (high_mult[1] - low_mult[1]),
        )

    @openai_retry
    def lookup_market_value(
        self,
        make: str,
        model: str,
        year: str,
        condition_summary: str = "",
    ) -> Tuple[float, float, str, list, float]:
        """
        Search the web for current market value using OpenAI Responses API.

        Returns:
            (market_value_low, market_value_high, notes, sources, cost)
        """
        vehicle_str = f"{year} {make} {model}"
        query = (
            f"What is the current market value and price range for a {vehicle_str} classic car? "
            f"Look up Hagerty, Bring a Trailer, Hemmings, and Kelley Blue Book for recent sales data. "
            f"Provide a realistic low and high price range in USD based on recent auction results and listings. "
            f"Return your answer as JSON with these exact keys:\n"
            f'{{"market_value_low": <number>, "market_value_high": <number>, '
            f'"notes": "<explanation of sources and how you arrived at the range>", '
            f'"recent_sales": ["<sale 1 description>", "<sale 2 description>"]}}'
        )

        logger.info("Searching web for market value of %s", vehicle_str)

        response = self.client.responses.create(
            model=self.model,
            input=query,
            tools=[{"type": "web_search"}],
        )

        result_text = ""
        sources = []
        search_calls = 0

        for item in response.output:
            if item.type == "web_search_call":
                search_calls += 1
            elif item.type == "message":
                for content_block in item.content:
                    if content_block.type == "output_text":
                        result_text = content_block.text
                        if hasattr(content_block, "annotations"):
                            for ann in content_block.annotations:
                                if hasattr(ann, "url"):
                                    sources.append(
                                        {
                                            "url": ann.url,
                                            "title": getattr(ann, "title", ""),
                                        }
                                    )

        token_cost = (
            response.usage.input_tokens * self.INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * self.OUTPUT_COST_PER_TOKEN
        )
        cost = token_cost + (search_calls * self.SEARCH_COST_PER_CALL)

        logger.info("Web search complete. %d searches performed. Cost: $%.4f", search_calls, cost)

        parsed = self._parse_valuation_response(result_text)

        return (
            parsed["market_value_low"],
            parsed["market_value_high"],
            parsed["notes"],
            sources,
            cost,
        )

    def _parse_valuation_response(self, text: str) -> dict:
        """Extract market value data from the response."""
        try:
            json_match = re.search(r"\{[^{}]*\"market_value_low\"[^{}]*\}", text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        numbers = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", text)
        values = []
        for n in numbers:
            try:
                values.append(float(n.replace(",", "")))
            except ValueError:
                continue

        values = [v for v in values if v >= 1000]

        if len(values) >= 2:
            return {
                "market_value_low": min(values),
                "market_value_high": max(values),
                "notes": text[:500],
                "recent_sales": [],
            }

        if len(values) == 1:
            val = values[0]
            return {
                "market_value_low": val * 0.8,
                "market_value_high": val * 1.2,
                "notes": text[:500],
                "recent_sales": [],
            }

        return {
            "market_value_low": 0,
            "market_value_high": 0,
            "notes": f"Could not extract pricing. Raw response: {text[:500]}",
            "recent_sales": [],
        }

    def calculate_bid_range(
        self,
        market_value_low: float,
        market_value_high: float,
        condition_score: float,
    ) -> Tuple[float, float]:
        """
        Calculate a starting bid range based on market value and condition.

        Higher condition scores yield bids closer to market value.
        """
        if market_value_low <= 0 or market_value_high <= 0:
            return (0, 0)

        low_mult, high_mult = self._get_condition_multiplier(condition_score)

        midpoint = (market_value_low + market_value_high) / 2

        bid_low = round(midpoint * low_mult, -2)
        bid_high = round(midpoint * high_mult, -2)

        return (max(bid_low, 0), max(bid_high, 0))

    def evaluate(
        self,
        make: str,
        model: str,
        year: str,
        condition_score: float,
        condition_summary: str = "",
    ) -> ValuationResult:
        """
        Full valuation pipeline: web search + bid calculation.
        """
        mv_low, mv_high, notes, sources, cost = self.lookup_market_value(
            make, model, year, condition_summary
        )

        bid_low, bid_high = self.calculate_bid_range(mv_low, mv_high, condition_score)

        source_text = ""
        if sources:
            source_text = "\n\nSources:\n" + "\n".join(
                f"- {s.get('title', 'Unknown')}: {s['url']}" for s in sources[:10]
            )

        return ValuationResult(
            market_value_low=mv_low,
            market_value_high=mv_high,
            bid_range_low=bid_low,
            bid_range_high=bid_high,
            valuation_notes=notes + source_text,
            sources=sources,
            cost=cost,
        )
