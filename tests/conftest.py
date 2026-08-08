from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from paperalpha.domain import TickerAnalysis


def synthetic_history(
    *,
    start: float = 100.0,
    daily_return: float = 0.001,
    volatility: float = 0.002,
    rows: int = 180,
    seed: int = 7,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = daily_return + rng.normal(0, volatility, rows)
    close = start * np.cumprod(1 + returns)
    dates = pd.bdate_range("2025-01-02", periods=rows, tz="UTC")
    return pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.0005, rows)),
            "High": close * 1.005,
            "Low": close * 0.995,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_400_000, rows),
        },
        index=dates,
    )


@pytest.fixture
def rising_history() -> pd.DataFrame:
    return synthetic_history(daily_return=0.002, volatility=0.001, seed=1)


@pytest.fixture
def falling_history() -> pd.DataFrame:
    return synthetic_history(daily_return=-0.0015, volatility=0.001, seed=2)


@pytest.fixture
def analysis() -> TickerAnalysis:
    return TickerAnalysis(
        ticker="TEST",
        price=100.0,
        score=72.0,
        signal_strength=68.0,
        factor_scores={
            "momentum": 75.0,
            "trend": 70.0,
            "news": 50.0,
            "risk": 60.0,
            "volume": 55.0,
            "trader": 50.0,
        },
        metrics={"return_20d": 0.05},
    )
