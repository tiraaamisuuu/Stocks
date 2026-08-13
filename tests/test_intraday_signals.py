from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd

from paperalpha.domain import PaperPosition
from paperalpha.intraday_signals import IntradayExitConfig, evaluate_intraday_exit


def _position(opened_at: datetime) -> PaperPosition:
    return PaperPosition(
        id="position-1",
        ticker="TEST",
        budget=150,
        shares=1.5,
        cash=0,
        entry_price=100,
        opened_at=opened_at,
        session_date=opened_at.date().isoformat(),
    )


def _snapshots(now: datetime, prices: list[float]) -> pd.DataFrame:
    start = now - timedelta(minutes=len(prices) - 1)
    return pd.DataFrame(
        {
            "captured_at": [start + timedelta(minutes=index) for index in range(len(prices))],
            "price": prices,
            "market_value": prices,
            "pnl": [price - 100 for price in prices],
        }
    )


def test_hard_stop_is_immediate() -> None:
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    decision = evaluate_intraday_exit(
        _position(now - timedelta(minutes=2)),
        _snapshots(now, [100, 99, 96.9]),
        now,
        IntradayExitConfig(),
    )

    assert decision is not None
    assert decision.code == "HARD_STOP"


def test_take_profit_is_immediate() -> None:
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    decision = evaluate_intraday_exit(
        _position(now - timedelta(minutes=2)),
        _snapshots(now, [100, 103, 105.1]),
        now,
        IntradayExitConfig(),
    )

    assert decision is not None
    assert decision.code == "TAKE_PROFIT"


def test_trailing_stop_waits_for_minimum_hold() -> None:
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    prices = [100, 101, 102.5, 102, 101.5, 100.8]
    position = _position(now - timedelta(minutes=5))

    assert (
        evaluate_intraday_exit(position, _snapshots(now, prices), now, IntradayExitConfig()) is None
    )
    decision = evaluate_intraday_exit(
        replace(position, opened_at=now - timedelta(minutes=15)),
        _snapshots(now, prices),
        now,
        IntradayExitConfig(),
    )
    assert decision is not None
    assert decision.code == "TRAILING_STOP"


def test_reversal_requires_loss_and_recent_drop() -> None:
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    prices = [101, 101, 101, 101, 100.8, 100.5, 99.4]
    decision = evaluate_intraday_exit(
        _position(now - timedelta(minutes=20)),
        _snapshots(now, prices),
        now,
        IntradayExitConfig(),
    )

    assert decision is not None
    assert decision.code == "MOMENTUM_REVERSAL"


def test_stale_snapshot_does_not_trigger() -> None:
    now = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)
    stale = _snapshots(now - timedelta(minutes=10), [100, 95])

    assert (
        evaluate_intraday_exit(
            _position(now - timedelta(minutes=20)), stale, now, IntradayExitConfig()
        )
        is None
    )
