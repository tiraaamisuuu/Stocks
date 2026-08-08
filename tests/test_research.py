from __future__ import annotations

from datetime import UTC, datetime

from paperalpha.domain import CompanyProfile, EquitySnapshot, ListedSecurity
from paperalpha.research import ResearchEngine
from paperalpha.sentiment import FinancialNewsSentiment


class FakeDirectory:
    def listed_stocks(self):
        return {
            f"S{index}": ListedSecurity(f"S{index}", f"Stock {index}", "NASDAQ")
            for index in range(30)
        }


class FakeMarketData:
    def __init__(self, history):
        self.history = history

    def screen_us_equities(self, **_kwargs):
        return {
            f"S{index}": EquitySnapshot(
                f"S{index}",
                price=10 + index,
                market_cap=1_000_000_000 + index,
                average_volume_3m=1_000_000 + index,
                return_52w=index / 100,
                distance_50d=index / 1_000,
                distance_200d=index / 1_000,
                forward_pe=10 + index,
                analyst_rating=2.0,
            )
            for index in range(30)
        }

    def daily_history(self, tickers, period="1y"):
        return {ticker: self.history for ticker in tickers}

    def company_profiles(self, tickers):
        return {
            ticker: CompanyProfile(ticker, metrics={"revenue_growth": 0.1}) for ticker in tickers
        }

    def news(self, _ticker, _count):
        return []


class FakeTraderSignals:
    def scores(self, tickers, *, as_of):
        return ({ticker: 0.0 for ticker in tickers}, {ticker: 0 for ticker in tickers})


def test_full_market_scan_reports_each_screening_stage(rising_history) -> None:
    engine = ResearchEngine(
        FakeMarketData(rising_history),
        FinancialNewsSentiment(),
        FakeTraderSignals(),
        FakeDirectory(),
    )

    result = engine.scan_market(
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        include_news=False,
        deep_scan_size=20,
    )

    assert result.directory_count == 30
    assert result.eligible_count == 30
    assert result.deep_count == 20
    assert len(result.analyses) == 20
