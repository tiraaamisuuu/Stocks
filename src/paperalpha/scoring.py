from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from paperalpha.config import FACTOR_WEIGHTS, MIN_HISTORY_ROWS
from paperalpha.domain import CompanyProfile, EquitySnapshot, NewsItem, TickerAnalysis

PRICE_FACTORS = ("momentum", "trend", "market", "risk", "setup", "liquidity", "volume")
PROFILE_FIELDS = (
    "revenue_growth",
    "earnings_growth",
    "return_on_equity",
    "operating_margin",
    "gross_margin",
    "debt_to_equity",
    "current_ratio",
    "free_cash_flow_yield",
    "analyst_upside",
    "analyst_count",
    "institutional_ownership",
    "short_float",
)


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


def _return(close: pd.Series, sessions: int) -> float:
    return float(close.iloc[-1] / close.iloc[-sessions - 1] - 1)


def _benchmark_features(close: pd.Series) -> tuple[float, float]:
    return_60d = _return(close, 60)
    sma_200 = float(close.tail(200).mean())
    trend = float(close.iloc[-1] / sma_200 - 1)
    returns = close.pct_change().dropna()
    volatility = float(returns.tail(20).std(ddof=0) * math.sqrt(252))
    # 0 is defensive/bearish and 1 is risk-on. Smooth inputs avoid a brittle switch.
    regime = 0.5 + 0.25 * math.tanh(trend * 8) + 0.25 * math.tanh(return_60d * 6)
    return max(0.0, min(1.0, regime)), volatility


def price_metrics(
    frame: pd.DataFrame,
    *,
    benchmark: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Compute point-in-time features using only rows in ``frame``."""
    if frame.empty or len(frame) < MIN_HISTORY_ROWS or "Close" not in frame:
        raise ValueError(f"At least {MIN_HISTORY_ROWS} daily rows are required.")

    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < MIN_HISTORY_ROWS:
        raise ValueError(f"At least {MIN_HISTORY_ROWS} valid closes are required.")
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    volume = pd.to_numeric(
        frame.get("Volume", pd.Series(index=frame.index, dtype=float)), errors="coerce"
    ).reindex(close.index)

    latest = float(close.iloc[-1])
    return_5d = _return(close, 5)
    return_20d = _return(close, 20)
    return_60d = _return(close, 60)
    return_120d = _return(close, 120)
    sma_20 = float(close.tail(20).mean())
    sma_50 = float(close.tail(50).mean())
    sma_200 = float(close.tail(200).mean())
    volatility_20d = float(returns.tail(20).std(ddof=0) * math.sqrt(252))
    volatility_60d = float(returns.tail(60).std(ddof=0) * math.sqrt(252))
    negative_returns = returns.tail(60).clip(upper=0)
    downside_volatility = float(negative_returns.std(ddof=0) * math.sqrt(252))
    rolling_peak = close.tail(120).cummax()
    drawdown_series = close.tail(120) / rolling_peak - 1
    current_drawdown = float(drawdown_series.iloc[-1])
    max_drawdown_120d = float(drawdown_series.min())

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_histogram = float((macd.iloc[-1] - macd_signal.iloc[-1]) / latest)

    close_std_20 = float(close.tail(20).std(ddof=0))
    bollinger_z = (latest - sma_20) / close_std_20 if close_std_20 > 0 else 0.0
    rsi_14 = rsi(close)

    high = pd.to_numeric(frame.get("High", close), errors="coerce").reindex(close.index)
    low = pd.to_numeric(frame.get("Low", close), errors="coerce").reindex(close.index)
    true_range = pd.concat(
        [(high - low).abs(), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr_14_pct = float(true_range.tail(14).mean() / latest)

    recent_volume = float(volume.tail(5).mean()) if volume.notna().any() else 0.0
    base_volume = float(volume.tail(20).mean()) if volume.notna().any() else 0.0
    volume_ratio = recent_volume / base_volume if base_volume > 0 else 1.0
    dollar_volume = close * volume
    average_dollar_volume_20d = (
        float(dollar_volume.tail(20).mean()) if dollar_volume.notna().any() else 0.0
    )
    amihud_illiquidity = float(
        (returns.reindex(dollar_volume.index).abs() / dollar_volume.replace(0, np.nan))
        .tail(20)
        .mean()
        * 1_000_000_000
    )
    if not math.isfinite(amihud_illiquidity):
        amihud_illiquidity = 0.0

    beta_60d = 1.0
    correlation_60d = 0.0
    relative_return_20d = return_20d
    relative_return_60d = return_60d
    relative_return_120d = return_120d
    regime_score = 0.5
    benchmark_volatility = volatility_20d
    if benchmark is not None and not benchmark.empty and "Close" in benchmark:
        benchmark_close = pd.to_numeric(benchmark["Close"], errors="coerce").dropna()
        if len(benchmark_close) >= MIN_HISTORY_ROWS:
            aligned = pd.concat(
                [returns.rename("asset"), benchmark_close.pct_change().rename("market")],
                axis=1,
                join="inner",
            ).dropna()
            recent = aligned.tail(60)
            market_variance = float(recent["market"].var(ddof=0))
            if market_variance > 0:
                beta_60d = float(recent["asset"].cov(recent["market"], ddof=0) / market_variance)
            if len(recent) > 2:
                correlation_60d = float(recent["asset"].corr(recent["market"]))
            relative_return_20d = return_20d - _return(benchmark_close, 20)
            relative_return_60d = return_60d - _return(benchmark_close, 60)
            relative_return_120d = return_120d - _return(benchmark_close, 120)
            regime_score, benchmark_volatility = _benchmark_features(benchmark_close)

    raw_momentum = 0.10 * return_5d + 0.25 * return_20d + 0.35 * return_60d + 0.30 * return_120d
    raw_trend = (
        0.30 * (latest / sma_20 - 1)
        + 0.25 * (sma_20 / sma_50 - 1)
        + 0.30 * (sma_50 / sma_200 - 1)
        + 0.15 * macd_histogram
    )
    beta_penalty = max(0.0, beta_60d - 1.0) * (1 - regime_score) * 0.08
    raw_market = (
        0.25 * relative_return_20d
        + 0.45 * relative_return_60d
        + 0.30 * relative_return_120d
        - beta_penalty
    )
    raw_risk = (
        -0.45 * volatility_20d
        - 0.20 * volatility_60d
        - 0.20 * downside_volatility
        + 0.10 * current_drawdown
        - 0.05 * atr_14_pct
    )
    raw_setup = -abs(rsi_14 - 55) / 50 - 0.15 * max(0.0, abs(bollinger_z) - 1.5)
    raw_liquidity = math.log1p(max(0.0, average_dollar_volume_20d)) - math.log1p(
        max(0.0, amihud_illiquidity)
    )
    raw_volume = math.copysign(abs(math.log(max(volume_ratio, 1e-6))), return_20d)

    return {
        "price": latest,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "return_60d": return_60d,
        "return_120d": return_120d,
        "relative_return_60d": relative_return_60d,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "macd_histogram": macd_histogram,
        "rsi_14": rsi_14,
        "bollinger_z": bollinger_z,
        "atr_14_pct": atr_14_pct,
        "volatility_20d": volatility_20d,
        "volatility_60d": volatility_60d,
        "downside_volatility_60d": downside_volatility,
        "current_drawdown": current_drawdown,
        "max_drawdown_120d": max_drawdown_120d,
        "volume_ratio": volume_ratio,
        "average_dollar_volume_20d": average_dollar_volume_20d,
        "amihud_illiquidity": amihud_illiquidity,
        "beta_60d": beta_60d,
        "correlation_60d": correlation_60d,
        "market_regime": regime_score,
        "benchmark_volatility_20d": benchmark_volatility,
        "raw_momentum": raw_momentum,
        "raw_trend": raw_trend,
        "raw_market": raw_market,
        "raw_risk": raw_risk,
        "raw_setup": raw_setup,
        "raw_liquidity": raw_liquidity,
        "raw_volume": raw_volume,
    }


def _robust_scores(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    series = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan)
    series = series.dropna()
    if series.empty:
        return {}
    median = float(series.median())
    mad = float((series - median).abs().median())
    scale = 1.4826 * mad
    if not math.isfinite(scale) or scale < 1e-12:
        scale = float(series.std(ddof=0))
    if not math.isfinite(scale) or scale < 1e-12:
        return {key: 50.0 for key in series.index}
    z_scores = (series - median) / scale
    return {str(key): float(50 + 50 * math.tanh(float(z) / 2)) for key, z in z_scores.items()}


def _component_factor(
    metrics: Mapping[str, Mapping[str, float]],
    components: Mapping[str, float],
) -> dict[str, float]:
    component_scores: dict[str, dict[str, float]] = {}
    for component, direction in components.items():
        values = {
            ticker: float(values[component]) * direction
            for ticker, values in metrics.items()
            if component in values and math.isfinite(float(values[component]))
        }
        component_scores[component] = _robust_scores(values)

    result: dict[str, float] = {}
    weight = 1 / len(components)
    for ticker in metrics:
        result[ticker] = sum(
            weight * component_scores[component].get(ticker, 50.0) for component in components
        )
    return result


def _snapshot_metrics(snapshot: EquitySnapshot, as_of: datetime) -> dict[str, float]:
    metrics: dict[str, float] = {}
    values = {
        "market_cap": snapshot.market_cap,
        "screen_average_volume_3m": snapshot.average_volume_3m,
        "screen_return_52w": snapshot.return_52w,
        "screen_distance_50d": snapshot.distance_50d,
        "screen_distance_200d": snapshot.distance_200d,
        "trailing_pe": snapshot.trailing_pe,
        "forward_pe": snapshot.forward_pe,
        "price_to_book": snapshot.price_to_book,
        "analyst_rating": snapshot.analyst_rating,
    }
    metrics.update({key: float(value) for key, value in values.items() if value is not None})
    if snapshot.trailing_pe and snapshot.trailing_pe > 0:
        metrics["trailing_earnings_yield"] = 1 / snapshot.trailing_pe
    if snapshot.forward_pe and snapshot.forward_pe > 0:
        metrics["forward_earnings_yield"] = 1 / snapshot.forward_pe
    if snapshot.price_to_book and snapshot.price_to_book > 0:
        metrics["book_yield"] = 1 / snapshot.price_to_book
    if snapshot.eps_ttm is not None and snapshot.eps_forward is not None:
        denominator = max(abs(snapshot.eps_ttm), 0.10)
        metrics["forward_eps_growth"] = max(
            -3.0, min(3.0, (snapshot.eps_forward - snapshot.eps_ttm) / denominator)
        )
    if snapshot.earnings_at is not None:
        moment = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
        days = (snapshot.earnings_at - moment.astimezone(UTC)).total_seconds() / 86_400
        if days >= -1:
            metrics["days_to_earnings"] = max(0.0, days)
            metrics["event_safety"] = min(1.0, max(0.0, days / 21))
    return metrics


def pre_screen_candidates(
    snapshots: Mapping[str, EquitySnapshot],
    *,
    limit: int,
) -> list[str]:
    """Balanced coarse ranking used before expensive history/profile requests."""
    metrics: dict[str, dict[str, float]] = {}
    for ticker, snapshot in snapshots.items():
        values = _snapshot_metrics(snapshot, datetime.now(UTC))
        if snapshot.price and snapshot.average_volume_3m:
            values["screen_liquidity"] = math.log1p(snapshot.price * snapshot.average_volume_3m)
        metrics[ticker] = values

    components = {
        "screen_return_52w": 1.0,
        "screen_distance_50d": 1.0,
        "screen_distance_200d": 1.0,
        "forward_eps_growth": 1.0,
        "forward_earnings_yield": 1.0,
        "analyst_rating": -1.0,
        "screen_liquidity": 1.0,
    }
    scores = _component_factor(metrics, components)
    return sorted(scores, key=lambda ticker: (scores[ticker], ticker), reverse=True)[:limit]


def rank_tickers(
    histories: Mapping[str, pd.DataFrame],
    *,
    benchmark: pd.DataFrame | None = None,
    snapshots: Mapping[str, EquitySnapshot] | None = None,
    profiles: Mapping[str, CompanyProfile] | None = None,
    news_scores: Mapping[str, float] | None = None,
    headlines: Mapping[str, tuple[NewsItem, ...]] | None = None,
    trader_scores: Mapping[str, float] | None = None,
    trader_counts: Mapping[str, int] | None = None,
    factor_weights: Mapping[str, float] | None = None,
    as_of: datetime | None = None,
) -> list[TickerAnalysis]:
    weights = dict(factor_weights or FACTOR_WEIGHTS)
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6):
        raise ValueError("Factor weights must sum to 1.0.")
    unknown_factors = set(weights) - set(FACTOR_WEIGHTS)
    if unknown_factors:
        raise ValueError(f"Unknown factors: {', '.join(sorted(unknown_factors))}")

    moment = as_of or datetime.now(UTC)
    snapshots = snapshots or {}
    profiles = profiles or {}
    computed: dict[str, dict[str, float]] = {}
    for ticker, history in histories.items():
        symbol = ticker.upper()
        try:
            metrics = price_metrics(history, benchmark=benchmark)
        except (ValueError, KeyError):
            continue
        if symbol in snapshots:
            metrics.update(_snapshot_metrics(snapshots[symbol], moment))
        if symbol in profiles:
            metrics.update(profiles[symbol].metrics)
        computed[symbol] = metrics

    factor_scores: dict[str, dict[str, float]] = {ticker: {} for ticker in computed}
    for factor in PRICE_FACTORS:
        cross_section = _robust_scores(
            {ticker: metrics[f"raw_{factor}"] for ticker, metrics in computed.items()}
        )
        for ticker in computed:
            factor_scores[ticker][factor] = cross_section.get(ticker, 50.0)

    fundamental_components = {
        "quality": {
            "revenue_growth": 1.0,
            "earnings_growth": 1.0,
            "forward_eps_growth": 1.0,
            "return_on_equity": 1.0,
            "operating_margin": 1.0,
            "gross_margin": 1.0,
            "free_cash_flow_yield": 1.0,
            "debt_to_equity": -1.0,
            "current_ratio": 1.0,
        },
        "value": {
            "forward_earnings_yield": 1.0,
            "trailing_earnings_yield": 1.0,
            "book_yield": 1.0,
        },
        "analyst": {
            "analyst_rating": -1.0,
            "analyst_upside": 1.0,
            "analyst_count": 1.0,
        },
        "event": {"event_safety": 1.0},
    }
    for factor, components in fundamental_components.items():
        scores = _component_factor(computed, components)
        for ticker in computed:
            factor_scores[ticker][factor] = scores.get(ticker, 50.0)

    # Short crowding and high fundamental beta modestly temper the price-risk score.
    supplemental_risk = _component_factor(computed, {"short_float": -1.0, "beta_fundamental": -1.0})
    for ticker in computed:
        factor_scores[ticker]["risk"] = 0.8 * factor_scores[ticker][
            "risk"
        ] + 0.2 * supplemental_risk.get(ticker, 50.0)

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

        values = np.array([factors[name] for name in weights], dtype=float)
        agreement = 1 - min(1.0, float(values.std(ddof=0)) / 35)
        distance = min(1.0, abs(total - 50) / 25)
        profile_coverage = sum(field in metrics for field in PROFILE_FIELDS) / len(PROFILE_FIELDS)
        snapshot_coverage = (
            sum(
                key in metrics
                for key in (
                    "forward_earnings_yield",
                    "trailing_earnings_yield",
                    "book_yield",
                    "analyst_rating",
                    "forward_eps_growth",
                    "event_safety",
                )
            )
            / 6
        )
        data_coverage = (
            0.57
            + 0.22 * profile_coverage
            + 0.10 * snapshot_coverage
            + 0.08 * bool(headlines.get(ticker))
            + 0.03 * bool(trader_counts.get(ticker, 0))
        )
        strength = 20 + 30 * agreement + 20 * distance + 30 * data_coverage

        warnings: list[str] = []
        if not headlines.get(ticker):
            warnings.append("No usable recent headlines; news factor is neutral.")
        if not trader_counts.get(ticker, 0):
            warnings.append("No point-in-time public trader disclosures; trader factor is neutral.")
        if ticker not in profiles:
            warnings.append(
                "Detailed company fundamentals were unavailable; missing inputs are neutral."
            )
        if metrics["rsi_14"] >= 70:
            warnings.append("RSI is above 70, which can indicate an overextended move.")
        if metrics["average_dollar_volume_20d"] < 10_000_000:
            warnings.append(
                "Average dollar volume is below $10m; spread and fill risk may be higher."
            )
        if 0 <= metrics.get("days_to_earnings", 99) <= 5:
            warnings.append("Earnings are due within five days; overnight event risk is elevated.")
        if metrics.get("debt_to_equity", 0) > 2:
            warnings.append("Debt-to-equity is above 2.0; leverage risk is elevated.")
        if metrics.get("short_float", 0) > 0.15:
            warnings.append(
                "More than 15% of float is short, increasing crowding and squeeze risk."
            )

        public_metrics = {
            key: float(value)
            for key, value in metrics.items()
            if not key.startswith("raw_") and math.isfinite(float(value))
        }
        analyses.append(
            TickerAnalysis(
                ticker=ticker,
                price=metrics["price"],
                score=round(float(total), 2),
                signal_strength=round(float(min(95, strength)), 2),
                factor_scores={key: round(float(value), 2) for key, value in factors.items()},
                metrics=public_metrics,
                headlines=headlines.get(ticker, ()),
                warnings=tuple(warnings),
            )
        )

    return sorted(analyses, key=lambda item: (item.score, item.signal_strength), reverse=True)
