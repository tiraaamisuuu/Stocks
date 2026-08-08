from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from paperalpha.config import MIN_HISTORY_ROWS
from paperalpha.scoring import rank_tickers


@dataclass(frozen=True)
class BacktestResult:
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict[str, float]


def walk_forward_backtest(
    histories: dict[str, pd.DataFrame],
    *,
    initial_cash: float = 10_000,
    hold_days: int = 5,
    transaction_cost_bps: float = 5,
) -> BacktestResult:
    """Backtest price factors with next-session execution and fixed holding periods.

    The signal uses closes through day t. Entry is at day t+1's open and exit is
    at a later open, preventing same-close execution and obvious look-ahead bias.
    News and public-disclosure signals are neutral because point-in-time archives
    are not available from the credential-free provider.
    """
    if initial_cash <= 0:
        raise ValueError("Initial cash must be positive.")
    if hold_days < 1:
        raise ValueError("Holding period must be at least one session.")

    usable = {
        ticker: frame.sort_index()
        for ticker, frame in histories.items()
        if len(frame) >= MIN_HISTORY_ROWS + hold_days + 2
    }
    if len(usable) < 2:
        raise ValueError("At least two tickers with enough shared history are required.")
    shared_dates = sorted(set.intersection(*(set(frame.index) for frame in usable.values())))
    if len(shared_dates) < MIN_HISTORY_ROWS + hold_days + 2:
        raise ValueError("The tickers do not have enough overlapping sessions.")

    cash = float(initial_cash)
    cost_rate = transaction_cost_bps / 10_000
    trades: list[dict[str, object]] = []
    curve = [{"date": shared_dates[MIN_HISTORY_ROWS - 1], "equity": cash}]
    signal_index = MIN_HISTORY_ROWS - 1
    while signal_index + hold_days + 1 < len(shared_dates):
        signal_date = shared_dates[signal_index]
        entry_date = shared_dates[signal_index + 1]
        exit_date = shared_dates[signal_index + hold_days + 1]
        windows = {
            ticker: frame.loc[:signal_date]
            for ticker, frame in usable.items()
            if signal_date in frame.index and len(frame.loc[:signal_date]) >= MIN_HISTORY_ROWS
        }
        ranking = rank_tickers(windows)
        if not ranking:
            signal_index += hold_days
            continue
        pick = ranking[0]
        frame = usable[pick.ticker]
        entry_price = _execution_price(frame.loc[entry_date])
        exit_price = _execution_price(frame.loc[exit_date])
        gross_return = exit_price / entry_price - 1
        net_return = (1 - cost_rate) * (1 + gross_return) * (1 - cost_rate) - 1
        start_cash = cash
        cash *= 1 + net_return
        trades.append(
            {
                "signal_date": signal_date,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "ticker": pick.ticker,
                "score": pick.score,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_return": gross_return,
                "net_return": net_return,
                "starting_equity": start_cash,
                "ending_equity": cash,
            }
        )
        curve.append({"date": exit_date, "equity": cash})
        signal_index += hold_days + 1

    trades_frame = pd.DataFrame(trades)
    curve_frame = pd.DataFrame(curve).set_index("date")
    metrics = _performance_metrics(trades_frame, curve_frame, initial_cash)
    return BacktestResult(trades_frame, curve_frame, metrics)


def _execution_price(row: pd.Series) -> float:
    value = row.get("Open", row["Close"])
    if pd.isna(value) or float(value) <= 0:
        value = row["Close"]
    return float(value)


def _performance_metrics(
    trades: pd.DataFrame, curve: pd.DataFrame, initial_cash: float
) -> dict[str, float]:
    if trades.empty:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "trade_count": 0.0,
        }
    total_return = float(curve["equity"].iloc[-1] / initial_cash - 1)
    elapsed_days = max(1, (pd.Timestamp(curve.index[-1]) - pd.Timestamp(curve.index[0])).days)
    annualized = (1 + total_return) ** (365.25 / elapsed_days) - 1 if total_return > -1 else -1.0
    returns = trades["net_return"].astype(float)
    periods_per_year = 252 / max(
        1.0, float((trades["exit_date"] - trades["entry_date"]).dt.days.mean())
    )
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(periods_per_year))
        if float(returns.std(ddof=0)) > 0
        else 0.0
    )
    rolling_max = curve["equity"].cummax()
    max_drawdown = float((curve["equity"] / rolling_max - 1).min())
    return {
        "total_return": total_return,
        "annualized_return": float(annualized),
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "win_rate": float((returns > 0).mean()),
        "trade_count": float(len(trades)),
    }
