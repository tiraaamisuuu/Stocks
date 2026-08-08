from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timezone

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from paperalpha.domain import NewsItem


class FinancialNewsSentiment:
    """Fast, inspectable headline sentiment with finance-specific vocabulary."""

    def __init__(self) -> None:
        self.analyzer = SentimentIntensityAnalyzer()
        self.analyzer.lexicon.update(
            {
                "beats": 2.2,
                "beat estimates": 2.4,
                "upgrade": 2.0,
                "upgraded": 2.0,
                "outperform": 1.8,
                "record revenue": 2.2,
                "guidance raised": 2.3,
                "buyback": 1.4,
                "misses": -2.2,
                "missed estimates": -2.4,
                "downgrade": -2.0,
                "downgraded": -2.0,
                "underperform": -1.8,
                "guidance cut": -2.3,
                "investigation": -1.5,
                "probe": -1.4,
                "fraud": -3.0,
                "recall": -1.7,
            }
        )

    def score_items(
        self,
        items: list[NewsItem],
        *,
        as_of: datetime | None = None,
        half_life_hours: float = 36.0,
    ) -> tuple[float, tuple[NewsItem, ...]]:
        now = as_of or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        weighted_total = 0.0
        weight_total = 0.0
        scored: list[NewsItem] = []
        for item in items:
            text = f"{item.title}. {item.summary}".strip()
            sentiment = float(self.analyzer.polarity_scores(text)["compound"])
            scored_item = replace(item, sentiment=sentiment)
            scored.append(scored_item)

            age_hours = 0.0
            if item.published_at is not None:
                published = item.published_at
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                age_hours = max(0.0, (now - published).total_seconds() / 3600)
            weight = math.exp(-math.log(2) * age_hours / half_life_hours)
            weighted_total += sentiment * weight
            weight_total += weight

        aggregate = weighted_total / weight_total if weight_total else 0.0
        return float(max(-1.0, min(1.0, aggregate))), tuple(scored)
