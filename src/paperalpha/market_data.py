from __future__ import annotations

import math
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import yfinance as yf

from paperalpha.config import MAX_SCREENER_RESULTS, SCREENER_PAGE_SIZE, YFINANCE_CACHE_DIR
from paperalpha.domain import CompanyProfile, EquitySnapshot, NewsItem


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

        results: dict[str, pd.DataFrame] = {}
        failures: list[str] = []
        for start in range(0, len(symbols), 40):
            chunk = symbols[start : start + 40]
            try:
                raw = yf.download(
                    chunk,
                    period=period,
                    interval="1d",
                    auto_adjust=True,
                    repair=True,
                    group_by="ticker",
                    # Reliability is preferable to timezone-cache races on Windows.
                    threads=False,
                    progress=False,
                    timeout=25,
                    multi_level_index=True,
                )
            except Exception as exc:  # preserve usable chunks on partial provider failure
                failures.append(str(exc))
                continue
            results.update(_split_download(raw, chunk))

        if not results and failures:
            raise MarketDataError(f"Yahoo Finance history request failed: {failures[0]}")
        return results

    def screen_us_equities(
        self,
        *,
        min_price: float = 3.0,
        min_average_volume: int = 500_000,
        min_market_cap: int = 300_000_000,
        allowed_symbols: set[str] | None = None,
        max_results: int = MAX_SCREENER_RESULTS,
    ) -> dict[str, EquitySnapshot]:
        """Page through every liquid US equity matching the coarse eligibility rules."""
        query = yf.EquityQuery(
            "and",
            [
                yf.EquityQuery("eq", ["region", "us"]),
                yf.EquityQuery("gte", ["intradayprice", float(min_price)]),
                yf.EquityQuery("gte", ["avgdailyvol3m", int(min_average_volume)]),
                yf.EquityQuery("gte", ["intradaymarketcap", int(min_market_cap)]),
            ],
        )
        snapshots: dict[str, EquitySnapshot] = {}
        total = max_results
        for offset in range(0, min(total, max_results), SCREENER_PAGE_SIZE):
            try:
                response = yf.screen(
                    query,
                    offset=offset,
                    size=min(SCREENER_PAGE_SIZE, max_results - offset),
                    sortField="avgdailyvol3m",
                    sortAsc=False,
                )
            except Exception as exc:
                if snapshots:
                    break
                raise MarketDataError(f"Yahoo Finance equity screen failed: {exc}") from exc
            total = min(int(response.get("total") or 0), max_results)
            records = response.get("quotes") or []
            if not records:
                break
            for record in records:
                snapshot = _parse_equity_snapshot(record)
                if snapshot is None:
                    continue
                if allowed_symbols is not None and snapshot.ticker not in allowed_symbols:
                    continue
                snapshots[snapshot.ticker] = snapshot
        return snapshots

    def company_profiles(self, tickers: Iterable[str]) -> dict[str, CompanyProfile]:
        symbols = list(
            dict.fromkeys(symbol.upper().strip() for symbol in tickers if symbol.strip())
        )
        profiles: dict[str, CompanyProfile] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(symbols) or 1)) as executor:
            futures = {executor.submit(_load_company_profile, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    profile = future.result()
                except Exception:
                    continue
                if profile is not None:
                    profiles[symbol] = profile
        return profiles

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
        symbol = ticker.upper()
        try:
            records = yf.Search(symbol, news_count=count).news or []
        except Exception:
            try:
                records = yf.Ticker(symbol).get_news(count=count, tab="news") or []
            except Exception:
                return []

        items: list[NewsItem] = []
        for record in records:
            item = _parse_news_record(record, symbol)
            if item is not None:
                items.append(item)
        return items


def _nested_url(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("url") or "")
    return ""


def _split_download(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
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
            cleaned = _clean_frame(frame)
            if not cleaned.empty:
                results[symbol] = cleaned
        except (KeyError, TypeError, ValueError):
            continue
    return results


def _number(value: object, *, scale: float = 1.0) -> float | None:
    try:
        number = float(value) / scale
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return number if math.isfinite(number) else None


def _epoch(value: object) -> datetime | None:
    number = _number(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _analyst_rating(value: object) -> float | None:
    match = re.match(r"\s*([1-5](?:\.\d+)?)", str(value or ""))
    return _number(match.group(1)) if match else None


def _parse_equity_snapshot(record: object) -> EquitySnapshot | None:
    if not isinstance(record, dict) or str(record.get("quoteType") or "").upper() != "EQUITY":
        return None
    ticker = str(record.get("symbol") or "").upper().strip()
    if not ticker:
        return None
    return EquitySnapshot(
        ticker=ticker,
        name=str(record.get("longName") or record.get("shortName") or ""),
        exchange=str(record.get("fullExchangeName") or record.get("exchange") or ""),
        price=_number(record.get("regularMarketPrice")),
        market_cap=_number(record.get("marketCap")),
        average_volume_3m=_number(record.get("averageDailyVolume3Month")),
        return_52w=_number(record.get("fiftyTwoWeekChangePercent"), scale=100),
        distance_50d=_number(record.get("fiftyDayAverageChangePercent")),
        distance_200d=_number(record.get("twoHundredDayAverageChangePercent")),
        trailing_pe=_number(record.get("trailingPE")),
        forward_pe=_number(record.get("forwardPE")),
        price_to_book=_number(record.get("priceToBook")),
        eps_ttm=_number(record.get("epsTrailingTwelveMonths")),
        eps_forward=_number(record.get("epsForward")),
        analyst_rating=_analyst_rating(record.get("averageAnalystRating")),
        earnings_at=_epoch(record.get("earningsTimestampStart") or record.get("earningsTimestamp")),
    )


def _load_company_profile(ticker: str) -> CompanyProfile | None:
    info = yf.Ticker(ticker).get_info()
    if not isinstance(info, dict) or not info:
        return None
    market_cap = _number(info.get("marketCap"))
    free_cash_flow = _number(info.get("freeCashflow"))
    current_price = _number(info.get("currentPrice") or info.get("regularMarketPrice"))
    target_price = _number(info.get("targetMeanPrice"))
    metrics = {
        "revenue_growth": _number(info.get("revenueGrowth")),
        "earnings_growth": _number(info.get("earningsGrowth")),
        "return_on_equity": _number(info.get("returnOnEquity")),
        "operating_margin": _number(info.get("operatingMargins")),
        "gross_margin": _number(info.get("grossMargins")),
        "debt_to_equity": _number(info.get("debtToEquity"), scale=100),
        "current_ratio": _number(info.get("currentRatio")),
        "free_cash_flow_yield": (
            free_cash_flow / market_cap
            if free_cash_flow is not None and market_cap and market_cap > 0
            else None
        ),
        "beta_fundamental": _number(info.get("beta")),
        "analyst_upside": (
            target_price / current_price - 1
            if target_price is not None and current_price and current_price > 0
            else None
        ),
        "analyst_count": _number(info.get("numberOfAnalystOpinions")),
        "institutional_ownership": _number(info.get("heldPercentInstitutions")),
        "short_float": _number(info.get("shortPercentOfFloat")),
    }
    return CompanyProfile(
        ticker=ticker,
        name=str(info.get("longName") or info.get("shortName") or ticker),
        sector=str(info.get("sector") or ""),
        metrics={key: value for key, value in metrics.items() if value is not None},
    )


def _parse_news_record(record: object, ticker: str) -> NewsItem | None:
    content = record.get("content", record) if isinstance(record, dict) else {}
    if not isinstance(content, dict):
        return None
    related = content.get("relatedTickers")
    if related and ticker.upper() not in {str(symbol).upper() for symbol in related}:
        return None
    title = str(content.get("title") or "").strip()
    if not title:
        return None

    published = _parse_timestamp(
        content.get("pubDate") or content.get("displayTime") or content.get("providerPublishTime")
    )
    provider = content.get("provider") or content.get("publisher") or {}
    publisher = provider.get("displayName", "") if isinstance(provider, dict) else str(provider)
    url = (
        _nested_url(content.get("canonicalUrl"))
        or _nested_url(content.get("clickThroughUrl"))
        or _nested_url(content.get("link"))
    )
    return NewsItem(
        title=title,
        published_at=published,
        url=url,
        publisher=publisher,
        summary=str(content.get("summary") or content.get("description") or ""),
    )


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
