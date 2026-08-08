from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


class PublicTraderSignals:
    """Point-in-time signal store for lawful public disclosures."""

    REQUIRED_COLUMNS = {
        "ticker",
        "disclosed_at",
        "actor",
        "side",
        "notional_usd",
        "source_url",
    }

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)

    def load(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame(columns=sorted(self.REQUIRED_COLUMNS))
        frame = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(frame.columns)
        if missing:
            raise ValueError(f"Trader signal CSV is missing: {', '.join(sorted(missing))}")
        frame = frame.copy()
        frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
        frame["side"] = frame["side"].astype(str).str.lower().str.strip()
        frame["disclosed_at"] = pd.to_datetime(frame["disclosed_at"], utc=True, errors="coerce")
        frame["notional_usd"] = pd.to_numeric(frame["notional_usd"], errors="coerce").fillna(0)
        return frame.dropna(subset=["disclosed_at"])

    def scores(
        self,
        tickers: list[str],
        *,
        as_of: datetime | None = None,
        half_life_days: float = 60.0,
    ) -> tuple[dict[str, float], dict[str, int]]:
        moment = as_of or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        moment_stamp = pd.Timestamp(moment)
        frame = self.load()
        frame = frame[frame["disclosed_at"] <= moment_stamp]

        output: dict[str, float] = {}
        counts: dict[str, int] = {}
        for ticker in tickers:
            rows = frame[frame["ticker"] == ticker.upper()]
            total = 0.0
            for row in rows.itertuples(index=False):
                direction = 1.0 if row.side == "buy" else -1.0 if row.side == "sell" else 0.0
                age_days = max(0.0, (moment_stamp - row.disclosed_at).total_seconds() / 86400)
                recency = math.exp(-math.log(2) * age_days / half_life_days)
                size = min(3.0, math.log1p(max(0.0, float(row.notional_usd)) / 10_000))
                total += direction * recency * size
            output[ticker.upper()] = math.tanh(total / 3.0)
            counts[ticker.upper()] = len(rows)
        return output, counts
