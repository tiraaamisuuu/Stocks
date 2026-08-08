from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from paperalpha.domain import NewsItem
from paperalpha.sentiment import FinancialNewsSentiment
from paperalpha.trader_signals import PublicTraderSignals


def test_sentiment_uses_recency_and_excludes_future_headlines() -> None:
    analyzer = FinancialNewsSentiment()
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    items = [
        NewsItem("Company beats estimates and raises guidance", now - timedelta(hours=1)),
        NewsItem("Company downgraded after weak results", now - timedelta(days=8)),
        NewsItem("Future fraud probe", now + timedelta(hours=1)),
    ]

    score, scored = analyzer.score_items(items, as_of=now)

    assert score > 0
    assert len(scored) == 2
    assert all(item.title != "Future fraud probe" for item in scored)


def test_trader_signal_is_point_in_time(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    pd.DataFrame(
        [
            {
                "ticker": "ABC",
                "disclosed_at": "2026-01-01T12:00:00Z",
                "actor": "Published buyer",
                "side": "buy",
                "notional_usd": 100_000,
                "source_url": "https://example.test/one",
            },
            {
                "ticker": "ABC",
                "disclosed_at": "2026-02-01T12:00:00Z",
                "actor": "Future seller",
                "side": "sell",
                "notional_usd": 1_000_000,
                "source_url": "https://example.test/two",
            },
        ]
    ).to_csv(path, index=False)

    scores, counts = PublicTraderSignals(path).scores(
        ["ABC"], as_of=datetime(2026, 1, 15, tzinfo=UTC)
    )

    assert counts["ABC"] == 1
    assert scores["ABC"] > 0
