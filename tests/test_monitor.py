from __future__ import annotations

from datetime import UTC, date, datetime

from paperalpha.monitor import PositionMonitor
from paperalpha.reporting import SessionReporter
from paperalpha.storage import PortfolioStore


class FakeMarketData:
    def latest_price(self, ticker: str) -> float:
        return 105.0

    def session_close(self, ticker: str, session_date: date) -> float:
        return 110.0


class FakeClock:
    def session_bounds(self, session_date: str):
        return (
            datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
            datetime(2026, 1, 5, 21, 0, tzinfo=UTC),
        )


def test_monitor_updates_then_closes_and_reports(tmp_path, analysis) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    position = store.open_position(
        analysis,
        1_000,
        opened_at=datetime(2026, 1, 5, 15, tzinfo=UTC),
    )
    monitor = PositionMonitor(
        store,
        FakeMarketData(),
        FakeClock(),
        SessionReporter(tmp_path / "reports"),
    )

    update_events = monitor.update_once(datetime(2026, 1, 5, 16, tzinfo=UTC))
    assert any("Updated TEST" in event for event in update_events)

    close_events = monitor.update_once(datetime(2026, 1, 5, 22, tzinfo=UTC))
    closed = store.get_position(position.id)
    assert closed is not None and closed.status == "CLOSED"
    assert closed.pnl == 100
    assert any("Closed TEST" in event for event in close_events)
    assert (tmp_path / "reports" / "2026-01-05.json").exists()
