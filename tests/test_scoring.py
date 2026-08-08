from __future__ import annotations

import math

import pandas as pd
import pytest

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
    with pytest.raises(ValueError, match="At least 70"):
        price_metrics(rising_history.head(30))


def test_weights_must_sum_to_one(
    rising_history: pd.DataFrame, falling_history: pd.DataFrame
) -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        rank_tickers(
            {"UP": rising_history, "DOWN": falling_history},
            factor_weights={"momentum": 0.5},
        )
