from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NewsItem:
    title: str
    published_at: datetime | None = None
    url: str = ""
    publisher: str = ""
    summary: str = ""
    sentiment: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ListedSecurity:
    ticker: str
    name: str
    exchange: str


@dataclass(frozen=True)
class EquitySnapshot:
    ticker: str
    name: str = ""
    exchange: str = ""
    price: float | None = None
    market_cap: float | None = None
    average_volume_3m: float | None = None
    return_52w: float | None = None
    distance_50d: float | None = None
    distance_200d: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    eps_ttm: float | None = None
    eps_forward: float | None = None
    analyst_rating: float | None = None
    earnings_at: datetime | None = None


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str = ""
    sector: str = ""
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchScan:
    analyses: tuple[TickerAnalysis, ...]
    directory_count: int
    eligible_count: int
    deep_count: int
    generated_at: datetime
    mode: str


@dataclass(frozen=True)
class TickerAnalysis:
    ticker: str
    price: float
    score: float
    signal_strength: float
    factor_scores: dict[str, float]
    metrics: dict[str, float]
    headlines: tuple[NewsItem, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def rationale(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score": self.score,
            "signal_strength": self.signal_strength,
            "factor_scores": self.factor_scores,
            "metrics": self.metrics,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SessionInfo:
    state: str
    label: str
    market_open: datetime | None
    market_close: datetime | None
    next_open: datetime | None


@dataclass(frozen=True)
class PaperPosition:
    id: str
    ticker: str
    budget: float
    shares: float
    cash: float
    entry_price: float
    opened_at: datetime
    session_date: str
    status: str = "OPEN"
    exit_price: float | None = None
    closed_at: datetime | None = None
    pnl: float | None = None
    return_pct: float | None = None
    rationale: dict[str, Any] = field(default_factory=dict)

    @property
    def invested(self) -> float:
        return self.shares * self.entry_price
