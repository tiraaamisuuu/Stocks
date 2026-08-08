from __future__ import annotations

import math

import pandas as pd
import pytest

from paperalpha.domain import CompanyProfile, EquitySnapshot
from paperalpha.scoring import price_metrics, rank_tickers


def test_price_metrics_capture_direction(
    rising_history: pd.DataFrame, falling_history: pd.DataFrame
) -> None:
    rising = price_metrics(rising_history)
    falling = price_metrics(falling_history)

    assert rising["return_20d"] > 0
    assert falling["return_20d"] < 0
    assert rising["raw_momentum"] > falling["raw_momentum"]
    assert 0 <= rising["rsi_14"] <= 100
    assert math.isfinite(rising["volatility_20d"])


def test_rank_tickers_prefers_stronger_price_action(
    rising_history: pd.DataFrame, falling_history: pd.DataFrame
) -> None:
    ranked = rank_tickers({"UP": rising_history, "DOWN": falling_history})

    assert [item.ticker for item in ranked] == ["UP", "DOWN"]
    assert ranked[0].score > 50 > ranked[1].score
    assert ranked[0].factor_scores["momentum"] > ranked[1].factor_scores["momentum"]


def test_short_history_is_rejected(rising_history: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="At least 200"):
        price_metrics(rising_history.head(30))


def test_weights_must_sum_to_one(
    rising_history: pd.DataFrame, falling_history: pd.DataFrame
) -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        rank_tickers(
            {"UP": rising_history, "DOWN": falling_history},
            factor_weights={"momentum": 0.5},
        )


def test_fundamental_and_analyst_inputs_change_factor_attribution(
    rising_history: pd.DataFrame, falling_history: pd.DataFrame
) -> None:
    snapshots = {
        "UP": EquitySnapshot(
            "UP",
            forward_pe=12,
            trailing_pe=14,
            price_to_book=2,
            analyst_rating=1.5,
            eps_ttm=4,
            eps_forward=5,
        ),
        "DOWN": EquitySnapshot(
            "DOWN",
            forward_pe=45,
            trailing_pe=50,
            price_to_book=12,
            analyst_rating=4,
            eps_ttm=4,
            eps_forward=3,
        ),
    }
    profiles = {
        "UP": CompanyProfile(
            "UP",
            metrics={
                "revenue_growth": 0.25,
                "earnings_growth": 0.30,
                "return_on_equity": 0.35,
                "operating_margin": 0.30,
                "gross_margin": 0.60,
                "debt_to_equity": 0.20,
                "current_ratio": 2.0,
                "free_cash_flow_yield": 0.06,
                "analyst_upside": 0.25,
                "analyst_count": 20,
            },
        ),
        "DOWN": CompanyProfile(
            "DOWN",
            metrics={
                "revenue_growth": -0.10,
                "earnings_growth": -0.20,
                "return_on_equity": 0.02,
                "operating_margin": 0.03,
                "gross_margin": 0.10,
                "debt_to_equity": 2.5,
                "current_ratio": 0.6,
                "free_cash_flow_yield": -0.04,
                "analyst_upside": -0.20,
                "analyst_count": 2,
            },
        ),
    }

    ranked = rank_tickers(
        {"UP": rising_history, "DOWN": falling_history},
        snapshots=snapshots,
        profiles=profiles,
    )

    assert ranked[0].factor_scores["quality"] > ranked[1].factor_scores["quality"]
    assert ranked[0].factor_scores["value"] > ranked[1].factor_scores["value"]
    assert ranked[0].factor_scores["analyst"] > ranked[1].factor_scores["analyst"]
