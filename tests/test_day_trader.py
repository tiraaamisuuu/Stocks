from __future__ import annotations

from datetime import UTC, date, datetime

from paperalpha.day_trader import DailyPaperTrader, PaperDayConfig
from paperalpha.domain import ResearchScan
from paperalpha.market_clock import MarketClock
from paperalpha.monitor import PositionMonitor
from paperalpha.reporting import SessionReporter
from paperalpha.storage import PortfolioStore


class FakeResearchEngine:
    def __init__(self, analysis):
        self.analysis = analysis
        self.scans = 0

    def scan_market(self, *, as_of, include_news, deep_scan_size):
        del include_news, deep_scan_size
        self.scans += 1
        return ResearchScan(
            analyses=(self.analysis,),
            directory_count=5_000,
            eligible_count=2_000,
            deep_count=1,
            generated_at=as_of,
            mode="Full US market",
        )


class FakeMarketData:
    def latest_price(self, ticker: str) -> float:
        del ticker
        return 101.0

    def session_close(self, ticker: str, session_date: date) -> float:
        del ticker, session_date
        return 104.0


class RecordingNotifier:
    def __init__(self):
        self.messages = []

    def send(self, title, message, **kwargs):
        self.messages.append((title, message, kwargs))


def test_paper_day_prepares_buys_and_closes_with_notifications(tmp_path, analysis) -> None:
    engine = FakeResearchEngine(analysis)
    market_data = FakeMarketData()
    store = PortfolioStore(tmp_path / "portfolio.db")
    clock = MarketClock()
    notifier = RecordingNotifier()
    monitor = PositionMonitor(
        store,
        market_data,
        clock,
        SessionReporter(tmp_path / "reports"),
    )
    trader = DailyPaperTrader(
        engine=engine,
        market_data=market_data,
        store=store,
        clock=clock,
        monitor=monitor,
        notifier=notifier,
        config=PaperDayConfig(budget=1_000, prepare_minutes=120),
    )

    premarket = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    at_open = datetime(2026, 8, 12, 13, 31, tzinfo=UTC)
    after_close = datetime(2026, 8, 12, 20, 5, tzinfo=UTC)

    prepare_events = trader.step(premarket)
    buy_events = trader.step(at_open)
    close_events = trader.step(after_close)

    assert engine.scans == 1
    assert any("Prepared TEST" in event for event in prepare_events)
    assert any("Paper BUY TEST" in event for event in buy_events)
    assert any("Closed TEST" in event for event in close_events)
    position = store.positions()[0]
    assert position.status == "CLOSED"
    assert position.entry_price == 101
    assert position.exit_price == 104
    assert any(title.startswith("PaperAlpha watchlist") for title, *_ in notifier.messages)
    assert any(title == "PAPER BUY · TEST" for title, *_ in notifier.messages)
    assert any(title == "PAPER SELL · TEST" for title, *_ in notifier.messages)
    assert trader.session_complete(after_close)


def test_paper_day_does_not_duplicate_existing_session_position(tmp_path, analysis) -> None:
    engine = FakeResearchEngine(analysis)
    market_data = FakeMarketData()
    store = PortfolioStore(tmp_path / "portfolio.db")
    clock = MarketClock()
    notifier = RecordingNotifier()
    existing = store.open_position(
        analysis,
        1_000,
        opened_at=datetime(2026, 8, 12, 13, 31, tzinfo=UTC),
    )
    trader = DailyPaperTrader(
        engine=engine,
        market_data=market_data,
        store=store,
        clock=clock,
        monitor=PositionMonitor(
            store,
            market_data,
            clock,
            SessionReporter(tmp_path / "reports"),
        ),
        notifier=notifier,
        config=PaperDayConfig(),
    )

    trader.step(datetime(2026, 8, 12, 14, 0, tzinfo=UTC))

    assert [position.id for position in store.positions()] == [existing.id]
