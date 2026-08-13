from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from paperalpha.domain import PaperPosition


@dataclass(frozen=True)
class IntradayExitConfig:
    hard_stop_pct: float = 3.0
    take_profit_pct: float = 5.0
    trailing_activation_pct: float = 2.0
    trailing_drawdown_pct: float = 1.5
    reversal_lookback_minutes: int = 5
    reversal_drop_pct: float = 1.25
    reversal_max_return_pct: float = -0.5
    minimum_hold_minutes: int = 10
    max_snapshot_age_minutes: int = 3


@dataclass(frozen=True)
class ExitDecision:
    code: str
    reason: str
    price: float
    return_pct: float
    peak_return_pct: float
    drawdown_pct: float
    momentum_pct: float | None = None


def evaluate_intraday_exit(
    position: PaperPosition,
    snapshots: pd.DataFrame,
    now: datetime,
    config: IntradayExitConfig,
) -> ExitDecision | None:
    if snapshots.empty:
        return None

    frame = snapshots.copy()
    frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True)
    frame = frame.sort_values("captured_at")
    latest = frame.iloc[-1]
    latest_at = latest["captured_at"].to_pydatetime()
    if now.tzinfo is None:
        now = now.replace(tzinfo=latest_at.tzinfo)
    if now - latest_at > timedelta(minutes=config.max_snapshot_age_minutes):
        return None

    price = float(latest["price"])
    current_return = (price / position.entry_price - 1) * 100
    peak_price = max(float(frame["price"].max()), position.entry_price)
    peak_return = (peak_price / position.entry_price - 1) * 100
    drawdown = (price / peak_price - 1) * 100

    if current_return <= -config.hard_stop_pct:
        return ExitDecision(
            "HARD_STOP",
            f"hard stop reached ({current_return:+.2f}% from entry)",
            price,
            current_return,
            peak_return,
            drawdown,
        )

    if current_return >= config.take_profit_pct:
        return ExitDecision(
            "TAKE_PROFIT",
            f"take-profit reached ({current_return:+.2f}% from entry)",
            price,
            current_return,
            peak_return,
            drawdown,
        )

    held_for = now - position.opened_at
    if held_for < timedelta(minutes=config.minimum_hold_minutes):
        return None

    if peak_return >= config.trailing_activation_pct and drawdown <= -config.trailing_drawdown_pct:
        return ExitDecision(
            "TRAILING_STOP",
            f"trailing stop after a {peak_return:+.2f}% peak and {drawdown:+.2f}% pullback",
            price,
            current_return,
            peak_return,
            drawdown,
        )

    cutoff = pd.Timestamp(now - timedelta(minutes=config.reversal_lookback_minutes))
    earlier = frame.loc[frame["captured_at"] <= cutoff]
    if earlier.empty:
        return None
    reference_price = float(earlier.iloc[-1]["price"])
    momentum = (price / reference_price - 1) * 100
    if momentum <= -config.reversal_drop_pct and current_return <= config.reversal_max_return_pct:
        return ExitDecision(
            "MOMENTUM_REVERSAL",
            f"five-minute reversal ({momentum:+.2f}%) with trade at {current_return:+.2f}%",
            price,
            current_return,
            peak_return,
            drawdown,
            momentum,
        )
    return None
