from __future__ import annotations

import pytest

from paperalpha.market_data import (
    YahooMarketData,
    _load_company_profile,
    _parse_equity_snapshot,
    _parse_news_record,
)


def test_news_parser_keeps_only_articles_related_to_ticker() -> None:
    relevant = {
        "title": "Example Corp raises guidance",
        "publisher": "Newswire",
        "link": "https://example.test/story",
        "providerPublishTime": 1_767_268_800,
        "relatedTickers": ["ABC", "SPY"],
    }
    unrelated = {**relevant, "relatedTickers": ["XYZ"]}

    parsed = _parse_news_record(relevant, "ABC")

    assert parsed is not None
    assert parsed.publisher == "Newswire"
    assert parsed.url == "https://example.test/story"
    assert _parse_news_record(unrelated, "ABC") is None


def test_equity_snapshot_normalises_percentages_and_rating() -> None:
    snapshot = _parse_equity_snapshot(
        {
            "symbol": "ABC",
            "quoteType": "EQUITY",
            "longName": "ABC Corp",
            "regularMarketPrice": 25,
            "marketCap": 2_000_000_000,
            "averageDailyVolume3Month": 1_500_000,
            "fiftyTwoWeekChangePercent": 24.0,
            "fiftyDayAverageChangePercent": 0.08,
            "averageAnalystRating": "1.8 - Buy",
            "earningsTimestampStart": 1_800_000_000,
        }
    )

    assert snapshot is not None
    assert snapshot.return_52w == pytest.approx(0.24)
    assert snapshot.distance_50d == pytest.approx(0.08)
    assert snapshot.analyst_rating == pytest.approx(1.8)
    assert snapshot.earnings_at is not None


def test_company_profile_derives_cash_flow_yield_and_target_upside(monkeypatch) -> None:
    class FakeTicker:
        def get_info(self):
            return {
                "longName": "Example Corp",
                "sector": "Technology",
                "marketCap": 1_000,
                "freeCashflow": 50,
                "currentPrice": 100,
                "targetMeanPrice": 120,
                "debtToEquity": 75,
            }

    monkeypatch.setattr("paperalpha.market_data.yf.Ticker", lambda _symbol: FakeTicker())
    profile = _load_company_profile("ABC")

    assert profile is not None
    assert profile.sector == "Technology"
    assert profile.metrics["free_cash_flow_yield"] == pytest.approx(0.05)
    assert profile.metrics["analyst_upside"] == pytest.approx(0.20)
    assert profile.metrics["debt_to_equity"] == pytest.approx(0.75)


def test_equity_screen_pages_and_intersects_official_symbols(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("paperalpha.market_data.YFINANCE_CACHE_DIR", tmp_path)
    monkeypatch.setattr("paperalpha.market_data.yf.set_tz_cache_location", lambda _path: None)

    def fake_screen(_query, *, offset, size, **_kwargs):
        symbols = ["KEEP", "DROP"] if offset == 0 else ["SECOND"]
        return {
            "total": 251,
            "quotes": [
                {
                    "symbol": symbol,
                    "quoteType": "EQUITY",
                    "regularMarketPrice": 10,
                    "marketCap": 1_000_000_000,
                    "averageDailyVolume3Month": 1_000_000,
                }
                for symbol in symbols
            ],
        }

    monkeypatch.setattr("paperalpha.market_data.yf.screen", fake_screen)
    provider = YahooMarketData()
    snapshots = provider.screen_us_equities(allowed_symbols={"KEEP", "SECOND"}, max_results=500)

    assert set(snapshots) == {"KEEP", "SECOND"}
