from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from paperalpha.storage import PortfolioStore


def test_position_lifecycle_and_profit_calculation(tmp_path, analysis) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    opened_at = datetime(2026, 1, 5, 15, tzinfo=UTC)

    position = store.open_position(analysis, 1_050, opened_at=opened_at)
    assert position.shares == 10
    assert position.cash == 50
    assert position.invested == 1_000

    store.record_snapshot(position.id, 110, captured_at=opened_at + timedelta(minutes=5))
    snapshots = store.snapshots(position.id)
    assert list(snapshots["market_value"]) == [1_050, 1_150]
    assert list(snapshots["pnl"]) == [0, 100]

    closed = store.close_position(position.id, 112, closed_at=opened_at + timedelta(hours=6))
    assert closed.status == "CLOSED"
    assert closed.pnl == 120
    assert closed.return_pct == pytest.approx(120 / 1_050 * 100)
    assert store.positions("OPEN") == []


def test_fractional_position_invests_the_budget(tmp_path, analysis) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    position = store.open_position(analysis, 25, fractional_shares=True)

    assert position.shares == 0.25
    assert position.cash == 0


def test_whole_share_budget_validation(tmp_path, analysis) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    with pytest.raises(ValueError, match="cannot buy one share"):
        store.open_position(analysis, 25, fractional_shares=False)
