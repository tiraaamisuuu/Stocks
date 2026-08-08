from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from paperalpha.config import MAX_SCAN_SIZE, NEWS_LIMIT_PER_TICKER
from paperalpha.domain import NewsItem, TickerAnalysis
from paperalpha.market_data import YahooMarketData
from paperalpha.scoring import rank_tickers
from paperalpha.sentiment import FinancialNewsSentiment
from paperalpha.trader_signals import PublicTraderSignals


class ResearchEngine:
    def __init__(
        self,
        market_data: YahooMarketData,
        sentiment: FinancialNewsSentiment,
        trader_signals: PublicTraderSignals,
    ) -> None:
        self.market_data = market_data
        self.sentiment = sentiment
        self.trader_signals = trader_signals

    def scan(
        self,
        tickers: list[str],
        *,
        as_of: datetime | None = None,
        include_news: bool = True,
    ) -> list[TickerAnalysis]:
        symbols = list(dict.fromkeys(ticker.upper().strip() for ticker in tickers if ticker.strip()))
        if len(symbols) < 2:
            raise ValueError("Choose at least two tickers for a meaningful cross-sectional ranking.")
        if len(symbols) > MAX_SCAN_SIZE:
            raise ValueError(f"A scan is limited to {MAX_SCAN_SIZE} tickers to protect the free data feed.")

        moment = as_of or datetime.now(timezone.utc)
        histories = self.market_data.daily_history(symbols, period="1y")
        if len(histories) < 2:
            raise RuntimeError("The market-data provider returned fewer than two usable tickers.")

        trader_scores, trader_counts = self.trader_signals.scores(symbols, as_of=moment)
        news_scores: dict[str, float] = {}
        headlines: dict[str, tuple[NewsItem, ...]] = {}
        if include_news:
            with ThreadPoolExecutor(max_workers=min(6, len(histories))) as executor:
                futures = {
                    executor.submit(self.market_data.news, ticker, NEWS_LIMIT_PER_TICKER): ticker
                    for ticker in histories
                }
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        items = future.result()
                    except Exception:
                        items = []
                    aggregate, scored = self.sentiment.score_items(items, as_of=moment)
                    news_scores[ticker] = aggregate
                    headlines[ticker] = scored

        return rank_tickers(
            histories,
            news_scores=news_scores,
            headlines=headlines,
            trader_scores=trader_scores,
            trader_counts=trader_counts,
        )
