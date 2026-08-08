from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from paperalpha.backtest import walk_forward_backtest
from paperalpha.market_clock import MarketClock


def test_market_clock_recognizes_weekend_and_session() -> None:
    clock = MarketClock()

    weekend = clock.session_info(datetime(2026, 8, 8, 15, tzinfo=UTC))
    regular_session = clock.session_info(datetime(2026, 8, 10, 15, tzinfo=UTC))

    assert weekend.state == "closed"
    assert weekend.next_open is not None
    assert regular_session.state == "open"
    assert regular_session.market_close is not None


def test_walk_forward_execution_occurs_after_signal(
    rising_history: pd.DataFrame, falling_history: pd.DataFrame
) -> None:
    result = walk_forward_backtest(
        {"UP": rising_history, "DOWN": falling_history},
        initial_cash=10_000,
        hold_days=5,
        transaction_cost_bps=5,
    )

    assert not result.trades.empty
    assert (result.trades["signal_date"] < result.trades["entry_date"]).all()
    assert (result.trades["entry_date"] < result.trades["exit_date"]).all()
    assert set(result.trades["ticker"]) == {"UP"}
    assert result.metrics["trade_count"] == len(result.trades)
