from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from paperalpha.config import (
    DEFAULT_DEEP_SCAN_SIZE,
    MAX_CUSTOM_SCAN_SIZE,
    MAX_DEEP_SCAN_SIZE,
    MAX_NEWS_CANDIDATES,
    NEWS_LIMIT_PER_TICKER,
)
from paperalpha.domain import EquitySnapshot, NewsItem, ResearchScan, TickerAnalysis
from paperalpha.market_data import YahooMarketData
from paperalpha.scoring import pre_screen_candidates, rank_tickers
from paperalpha.sentiment import FinancialNewsSentiment
from paperalpha.trader_signals import PublicTraderSignals
from paperalpha.universe import NasdaqSymbolDirectory


class ResearchEngine:
    def __init__(
        self,
        market_data: YahooMarketData,
        sentiment: FinancialNewsSentiment,
        trader_signals: PublicTraderSignals,
        symbol_directory: NasdaqSymbolDirectory | None = None,
    ) -> None:
        self.market_data = market_data
        self.sentiment = sentiment
        self.trader_signals = trader_signals
        self.symbol_directory = symbol_directory or NasdaqSymbolDirectory()

    def scan(
        self,
        tickers: list[str],
        *,
        as_of: datetime | None = None,
        include_news: bool = True,
    ) -> list[TickerAnalysis]:
        """Deep-scan a user-selected universe."""
        symbols = list(
            dict.fromkeys(ticker.upper().strip() for ticker in tickers if ticker.strip())
        )
        if len(symbols) < 2:
            raise ValueError(
                "Choose at least two tickers for a meaningful cross-sectional ranking."
            )
        if len(symbols) > MAX_CUSTOM_SCAN_SIZE:
            raise ValueError(
                f"A custom scan is limited to {MAX_CUSTOM_SCAN_SIZE} tickers to protect the free feed."
            )
        return self._deep_rank(symbols, as_of=as_of, include_news=include_news)

    def scan_market(
        self,
        *,
        as_of: datetime | None = None,
        include_news: bool = True,
        min_price: float = 3.0,
        min_average_volume: int = 500_000,
        min_market_cap: int = 300_000_000,
        deep_scan_size: int = DEFAULT_DEEP_SCAN_SIZE,
    ) -> ResearchScan:
        """Screen the full live US directory, then deeply rank the strongest candidates."""
        if not 20 <= deep_scan_size <= MAX_DEEP_SCAN_SIZE:
            raise ValueError(f"Deep scan size must be between 20 and {MAX_DEEP_SCAN_SIZE}.")
        moment = as_of or datetime.now(UTC)
        listed = self.symbol_directory.listed_stocks()
        snapshots = self.market_data.screen_us_equities(
            min_price=min_price,
            min_average_volume=min_average_volume,
            min_market_cap=min_market_cap,
            allowed_symbols=set(listed),
        )
        if len(snapshots) < 2:
            raise RuntimeError("The broad-market screen returned fewer than two eligible stocks.")
        candidates = pre_screen_candidates(snapshots, limit=deep_scan_size)
        analyses = self._deep_rank(
            candidates,
            as_of=moment,
            include_news=include_news,
            snapshots=snapshots,
        )
        return ResearchScan(
            analyses=tuple(analyses),
            directory_count=len(listed),
            eligible_count=len(snapshots),
            deep_count=len(analyses),
            generated_at=moment,
            mode="Full US market",
        )

    def _deep_rank(
        self,
        symbols: list[str],
        *,
        as_of: datetime | None,
        include_news: bool,
        snapshots: dict[str, EquitySnapshot] | None = None,
    ) -> list[TickerAnalysis]:
        moment = as_of or datetime.now(UTC)
        download_symbols = [*symbols]
        if "SPY" not in download_symbols:
            download_symbols.append("SPY")
        downloaded = self.market_data.daily_history(download_symbols, period="1y")
        benchmark = downloaded.get("SPY")
        histories = {ticker: downloaded[ticker] for ticker in symbols if ticker in downloaded}
        if len(histories) < 2:
            raise RuntimeError("The market-data provider returned fewer than two usable tickers.")

        usable_snapshots = {
            ticker: snapshot
            for ticker, snapshot in (snapshots or {}).items()
            if ticker in histories
        }
        profiles = self.market_data.company_profiles(histories)
        trader_scores, trader_counts = self.trader_signals.scores(list(histories), as_of=moment)

        # Establish a price/fundamental shortlist before spending requests on headlines.
        preliminary = rank_tickers(
            histories,
            benchmark=benchmark,
            snapshots=usable_snapshots,
            profiles=profiles,
            trader_scores=trader_scores,
            trader_counts=trader_counts,
            as_of=moment,
        )
        news_pool = [item.ticker for item in preliminary[:MAX_NEWS_CANDIDATES]]
        news_scores: dict[str, float] = {}
        headlines: dict[str, tuple[NewsItem, ...]] = {}
        if include_news:
            news_scores, headlines = self._news_signals(news_pool, moment)

        return rank_tickers(
            histories,
            benchmark=benchmark,
            snapshots=usable_snapshots,
            profiles=profiles,
            news_scores=news_scores,
            headlines=headlines,
            trader_scores=trader_scores,
            trader_counts=trader_counts,
            as_of=moment,
        )

    def _news_signals(
        self, symbols: list[str], as_of: datetime
    ) -> tuple[dict[str, float], dict[str, tuple[NewsItem, ...]]]:
        news_scores: dict[str, float] = {}
        headlines: dict[str, tuple[NewsItem, ...]] = {}
        with ThreadPoolExecutor(max_workers=min(6, len(symbols) or 1)) as executor:
            futures = {
                executor.submit(self.market_data.news, ticker, NEWS_LIMIT_PER_TICKER): ticker
                for ticker in symbols
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    items = future.result()
                except Exception:
                    items = []
                aggregate, scored = self.sentiment.score_items(items, as_of=as_of)
                news_scores[ticker] = aggregate
                headlines[ticker] = scored
        return news_scores, headlines
