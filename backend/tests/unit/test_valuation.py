"""Tests for backend/app/core/valuation.py -- pure logic methods."""

import pytest

from app.core.valuation import ValuationEngine


@pytest.fixture
def engine():
    return ValuationEngine(model="gpt-4o")


# --- _get_condition_multiplier ---

def test_condition_multiplier_score_5(engine):
    assert engine._get_condition_multiplier(5.0) == (0.95, 1.05)


def test_condition_multiplier_score_1(engine):
    assert engine._get_condition_multiplier(1.0) == (0.25, 0.45)


def test_condition_multiplier_interpolation(engine):
    low, high = engine._get_condition_multiplier(3.5)
    # Between score 3 (0.60, 0.80) and score 4 (0.80, 0.95), at 50%
    assert abs(low - 0.70) < 0.001
    assert abs(high - 0.875) < 0.001


def test_condition_multiplier_clamp_high(engine):
    assert engine._get_condition_multiplier(6.0) == (0.95, 1.05)


def test_condition_multiplier_clamp_low(engine):
    assert engine._get_condition_multiplier(0.5) == (0.25, 0.45)


# --- calculate_bid_range ---

def test_calculate_bid_range_excellent(engine):
    bid_low, bid_high = engine.calculate_bid_range(40000, 60000, 5.0)
    midpoint = 50000
    # Score 5: 0.95 * 50000 = 47500, 1.05 * 50000 = 52500
    assert bid_low == 47500
    assert bid_high == 52500


def test_calculate_bid_range_poor(engine):
    bid_low, bid_high = engine.calculate_bid_range(40000, 60000, 1.0)
    midpoint = 50000
    # Score 1: 0.25 * 50000 = 12500, 0.45 * 50000 = 22500
    assert bid_low == 12500
    assert bid_high == 22500


def test_calculate_bid_range_zero_market(engine):
    assert engine.calculate_bid_range(0, 0, 4.0) == (0, 0)
    assert engine.calculate_bid_range(-1000, 5000, 4.0) == (0, 0)


# --- _parse_valuation_response ---

def test_parse_valuation_json_response(engine):
    text = 'Here is the data: {"market_value_low": 25000, "market_value_high": 45000, "notes": "Based on recent sales", "recent_sales": []}'
    result = engine._parse_valuation_response(text)
    assert result["market_value_low"] == 25000
    assert result["market_value_high"] == 45000


def test_parse_valuation_dollar_amounts(engine):
    text = "Recent sales show prices between $25,000 and $50,000 for this model."
    result = engine._parse_valuation_response(text)
    assert result["market_value_low"] == 25000
    assert result["market_value_high"] == 50000


def test_parse_valuation_single_dollar(engine):
    text = "The average price is around $30,000."
    result = engine._parse_valuation_response(text)
    assert result["market_value_low"] == 30000 * 0.8
    assert result["market_value_high"] == 30000 * 1.2


def test_parse_valuation_no_prices(engine):
    text = "I could not find any pricing information for this vehicle."
    result = engine._parse_valuation_response(text)
    assert result["market_value_low"] == 0
    assert result["market_value_high"] == 0
    assert "Could not extract" in result["notes"]


def test_parse_valuation_filters_small_values(engine):
    text = "Listed at $500 deposit and final price of $35,000."
    result = engine._parse_valuation_response(text)
    # $500 is filtered out (< $1000), only $35,000 remains -> single value path
    assert result["market_value_low"] == 35000 * 0.8
    assert result["market_value_high"] == 35000 * 1.2
