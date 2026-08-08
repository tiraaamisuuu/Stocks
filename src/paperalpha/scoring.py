from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from paperalpha.config import FACTOR_WEIGHTS, MIN_HISTORY_ROWS
from paperalpha.domain import NewsItem, TickerAnalysis

RAW_FACTORS = ("momentum", "trend", "risk", "volume")


def rsi(close: pd.Series, periods: int = 14) -> float:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / periods, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / periods, adjust=False).mean()
    if loss.empty or pd.isna(loss.iloc[-1]):
        return 50.0
    if float(loss.iloc[-1]) == 0:
        return 100.0
    relative_strength = float(gain.iloc[-1] / loss.iloc[-1])
    return 100 - (100 / (1 + relative_strength))


def price_metrics(frame: pd.DataFrame) -> dict[str, float]:
    """Compute point-in-time features using only rows in ``frame``."""
    if frame.empty or len(frame) < MIN_HISTORY_ROWS or "Close" not in frame:
        raise ValueError(f"At least {MIN_HISTORY_ROWS} daily rows are required.")

    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < MIN_HISTORY_ROWS:
        raise ValueError(f"At least {MIN_HISTORY_ROWS} valid closes are required.")
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    volume = pd.to_numeric(
        frame.get("Volume", pd.Series(index=frame.index, dtype=float)), errors="coerce"
    )

    latest = float(close.iloc[-1])
    return_5d = float(latest / close.iloc[-6] - 1)
    return_20d = float(latest / close.iloc[-21] - 1)
    return_60d = float(latest / close.iloc[-61] - 1)
    sma_20 = float(close.tail(20).mean())
    sma_50 = float(close.tail(50).mean())
    volatility_20d = float(returns.tail(20).std(ddof=0) * math.sqrt(252))
    rolling_peak = close.tail(60).cummax()
    current_drawdown = float((close.tail(60) / rolling_peak - 1).iloc[-1])

    recent_volume = float(volume.tail(5).mean()) if volume.notna().any() else 0.0
    base_volume = float(volume.tail(20).mean()) if volume.notna().any() else 0.0
    volume_ratio = recent_volume / base_volume if base_volume > 0 else 1.0

    # Raw features are cross-sectionally scaled below. The risk feature is higher
    # for lower realised volatility and shallower current drawdown.
    raw_momentum = 0.20 * return_5d + 0.45 * return_20d + 0.35 * return_60d
    raw_trend = 0.60 * (latest / sma_20 - 1) + 0.40 * (sma_20 / sma_50 - 1)
    raw_risk = -volatility_20d + current_drawdown * 0.50
    raw_volume = math.copysign(abs(math.log(max(volume_ratio, 1e-6))), return_5d)

    return {
        "price": latest,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "return_60d": return_60d,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "rsi_14": rsi(close),
        "volatility_20d": volatility_20d,
        "current_drawdown": current_drawdown,
        "volume_ratio": volume_ratio,
        "raw_momentum": raw_momentum,
        "raw_trend": raw_trend,
        "raw_risk": raw_risk,
        "raw_volume": raw_volume,
    }


def _robust_scores(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    series = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan)
    median = float(series.median())
    mad = float((series - median).abs().median())
    scale = 1.4826 * mad
    if not math.isfinite(scale) or scale < 1e-12:
        scale = float(series.std(ddof=0))
    if not math.isfinite(scale) or scale < 1e-12:
        return {key: 50.0 for key in values}
    z_scores = (series.fillna(median) - median) / scale
    return {key: float(50 + 50 * math.tanh(float(z) / 2)) for key, z in z_scores.items()}


def rank_tickers(
    histories: Mapping[str, pd.DataFrame],
    *,
    news_scores: Mapping[str, float] | None = None,
    headlines: Mapping[str, tuple[NewsItem, ...]] | None = None,
    trader_scores: Mapping[str, float] | None = None,
    trader_counts: Mapping[str, int] | None = None,
    factor_weights: Mapping[str, float] | None = None,
) -> list[TickerAnalysis]:
    weights = dict(factor_weights or FACTOR_WEIGHTS)
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6):
        raise ValueError("Factor weights must sum to 1.0.")

    computed: dict[str, dict[str, float]] = {}
    rejected: dict[str, str] = {}
    for ticker, history in histories.items():
        symbol = ticker.upper()
        try:
            computed[symbol] = price_metrics(history)
        except (ValueError, KeyError) as exc:
            rejected[symbol] = str(exc)

    factor_scores: dict[str, dict[str, float]] = {ticker: {} for ticker in computed}
    for factor in RAW_FACTORS:
        cross_section = _robust_scores(
            {ticker: metrics[f"raw_{factor}"] for ticker, metrics in computed.items()}
        )
        for ticker, value in cross_section.items():
            factor_scores[ticker][factor] = value

    news_scores = news_scores or {}
    headlines = headlines or {}
    trader_scores = trader_scores or {}
    trader_counts = trader_counts or {}
    analyses: list[TickerAnalysis] = []
    for ticker, metrics in computed.items():
        news_raw = float(max(-1, min(1, news_scores.get(ticker, 0.0))))
        trader_raw = float(max(-1, min(1, trader_scores.get(ticker, 0.0))))
        factors = factor_scores[ticker]
        factors["news"] = 50 + 50 * news_raw
        factors["trader"] = 50 + 50 * trader_raw
        total = sum(weights[name] * factors[name] for name in weights)

        values = np.array(list(factors.values()), dtype=float)
        agreement = 1 - min(1.0, float(values.std(ddof=0)) / 35)
        distance = min(1.0, abs(total - 50) / 25)
        news_coverage = 1.0 if headlines.get(ticker) else 0.0
        trader_coverage = 1.0 if trader_counts.get(ticker, 0) else 0.0
        data_coverage = (4 + news_coverage + trader_coverage) / 6
        strength = 25 + 30 * agreement + 25 * distance + 20 * data_coverage

        warnings: list[str] = []
        if not headlines.get(ticker):
            warnings.append("No usable recent headlines; news factor is neutral.")
        if not trader_counts.get(ticker, 0):
            warnings.append("No point-in-time public trader disclosures; trader factor is neutral.")
        if metrics["rsi_14"] >= 70:
            warnings.append("RSI is above 70, which can indicate an overextended move.")

        public_metrics = {
            key: value for key, value in metrics.items() if not key.startswith("raw_")
        }
        analyses.append(
            TickerAnalysis(
                ticker=ticker,
                price=metrics["price"],
                score=round(float(total), 2),
                signal_strength=round(float(min(95, strength)), 2),
                factor_scores={key: round(float(value), 2) for key, value in factors.items()},
                metrics={key: float(value) for key, value in public_metrics.items()},
                headlines=headlines.get(ticker, ()),
                warnings=tuple(warnings),
            )
        )

    return sorted(analyses, key=lambda item: (item.score, item.signal_strength), reverse=True)
