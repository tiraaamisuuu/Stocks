from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from paperalpha.config import YFINANCE_CACHE_DIR
from paperalpha.domain import NewsItem


class MarketDataError(RuntimeError):
    """Raised when a provider cannot return usable market data."""


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    cleaned = frame.copy()
    cleaned.columns = [str(column).title() for column in cleaned.columns]
    if "Close" not in cleaned:
        return pd.DataFrame()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")].sort_index()
    return cleaned.dropna(subset=["Close"])


class YahooMarketData:
    """Credential-free Yahoo Finance adapter for educational/personal research.

    Yahoo data may be delayed. Keeping access behind this adapter makes replacing
    it with a licensed real-time feed straightforward.
    """

    def __init__(self) -> None:
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))

    def daily_history(self, tickers: Iterable[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        symbols = list(
            dict.fromkeys(symbol.upper().strip() for symbol in tickers if symbol.strip())
        )
        if not symbols:
            return {}

        try:
            raw = yf.download(
                symbols,
                period=period,
                interval="1d",
                auto_adjust=True,
                repair=True,
                group_by="ticker",
                # yfinance's first timezone-cache write can race across download
                # workers on Windows, so reliability wins over a small speed-up.
                threads=False,
                progress=False,
                timeout=20,
                multi_level_index=True,
            )
        except Exception as exc:  # provider failures should not crash the UI
            raise MarketDataError(f"Yahoo Finance history request failed: {exc}") from exc

        results: dict[str, pd.DataFrame] = {}
        if raw is None or raw.empty:
            return results

        for symbol in symbols:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    level_zero = raw.columns.get_level_values(0)
                    level_one = raw.columns.get_level_values(1)
                    if symbol in level_zero:
                        frame = raw[symbol]
                    elif symbol in level_one:
                        frame = raw.xs(symbol, axis=1, level=1)
                    else:
                        continue
                else:
                    frame = raw
                frame = _clean_frame(frame)
                if not frame.empty:
                    results[symbol] = frame
            except (KeyError, TypeError, ValueError):
                continue
        return results

    def intraday_history(
        self,
        ticker: str,
        *,
        period: str = "1d",
        interval: str = "1m",
    ) -> pd.DataFrame:
        try:
            frame = yf.Ticker(ticker.upper()).history(
                period=period,
                interval=interval,
                auto_adjust=False,
                prepost=False,
                repair=True,
                timeout=15,
            )
        except Exception as exc:
            raise MarketDataError(f"Could not load intraday data for {ticker}: {exc}") from exc
        return _clean_frame(frame)

    def latest_price(self, ticker: str) -> float:
        intraday = self.intraday_history(ticker)
        if not intraday.empty:
            return float(intraday["Close"].iloc[-1])

        daily = self.daily_history([ticker], period="5d").get(ticker.upper(), pd.DataFrame())
        if daily.empty:
            raise MarketDataError(f"No price is available for {ticker}.")
        return float(daily["Close"].iloc[-1])

    def session_close(self, ticker: str, session_date: date) -> float:
        """Return the unadjusted official close for a completed session."""
        try:
            frame = yf.Ticker(ticker.upper()).history(
                start=session_date.isoformat(),
                end=(session_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                repair=True,
                timeout=15,
            )
        except Exception as exc:
            raise MarketDataError(
                f"Could not load the {session_date} close for {ticker}: {exc}"
            ) from exc
        cleaned = _clean_frame(frame)
        if cleaned.empty:
            raise MarketDataError(f"No official close is available for {ticker} on {session_date}.")
        return float(cleaned["Close"].iloc[-1])

    def news(self, ticker: str, count: int = 10) -> list[NewsItem]:
        try:
            records = yf.Ticker(ticker.upper()).get_news(count=count, tab="news") or []
        except Exception:
            return []

        items: list[NewsItem] = []
        for record in records:
            content = record.get("content", record) if isinstance(record, dict) else {}
            if not isinstance(content, dict):
                continue
            title = str(content.get("title") or "").strip()
            if not title:
                continue

            published = _parse_timestamp(
                content.get("pubDate")
                or content.get("displayTime")
                or content.get("providerPublishTime")
            )
            provider = content.get("provider") or {}
            publisher = (
                provider.get("displayName", "") if isinstance(provider, dict) else str(provider)
            )
            url = _nested_url(content.get("canonicalUrl")) or _nested_url(
                content.get("clickThroughUrl")
            )
            items.append(
                NewsItem(
                    title=title,
                    published_at=published,
                    url=url,
                    publisher=publisher,
                    summary=str(content.get("summary") or content.get("description") or ""),
                )
            )
        return items


def _nested_url(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("url") or "")
    return ""


def _parse_timestamp(value: object) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            stamp = pd.to_datetime(value, unit="s", utc=True)
        else:
            stamp = pd.to_datetime(value, utc=True)
        return stamp.to_pydatetime()
    except (TypeError, ValueError, OverflowError):
        return None
