from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from paperalpha.domain import PaperPosition, TickerAnalysis

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    budget REAL NOT NULL CHECK (budget > 0),
    shares REAL NOT NULL CHECK (shares > 0),
    cash REAL NOT NULL CHECK (cash >= 0),
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    opened_at TEXT NOT NULL,
    session_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
    exit_price REAL,
    closed_at TEXT,
    pnl REAL,
    return_pct REAL,
    rationale_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT NOT NULL REFERENCES positions(id),
    captured_at TEXT NOT NULL,
    price REAL NOT NULL CHECK (price > 0),
    market_value REAL NOT NULL,
    pnl REAL NOT NULL,
    UNIQUE(position_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_snapshots_position_time ON snapshots(position_id, captured_at);
"""


class PortfolioStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def open_position(
        self,
        analysis: TickerAnalysis,
        budget: float,
        *,
        opened_at: datetime | None = None,
        fractional_shares: bool = False,
    ) -> PaperPosition:
        if budget <= 0:
            raise ValueError("Budget must be greater than zero.")
        if analysis.price <= 0:
            raise ValueError("Entry price must be greater than zero.")

        shares = (
            budget / analysis.price if fractional_shares else float(int(budget // analysis.price))
        )
        if shares <= 0:
            raise ValueError(
                f"The budget cannot buy one share of {analysis.ticker} at ${analysis.price:,.2f}. "
                "Enable fractional shares or increase the budget."
            )
        if fractional_shares:
            shares = round(shares, 6)
        cash = max(0.0, budget - shares * analysis.price)
        moment = opened_at or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        position = PaperPosition(
            id=str(uuid.uuid4()),
            ticker=analysis.ticker,
            budget=float(budget),
            shares=shares,
            cash=cash,
            entry_price=analysis.price,
            opened_at=moment,
            session_date=moment.date().isoformat(),
            rationale=analysis.rationale(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO positions (
                    id, ticker, budget, shares, cash, entry_price, opened_at,
                    session_date, status, rationale_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    position.id,
                    position.ticker,
                    position.budget,
                    position.shares,
                    position.cash,
                    position.entry_price,
                    position.opened_at.isoformat(),
                    position.session_date,
                    json.dumps(position.rationale),
                ),
            )
        self.record_snapshot(position.id, position.entry_price, captured_at=moment)
        return position

    def record_snapshot(
        self,
        position_id: str,
        price: float,
        *,
        captured_at: datetime | None = None,
    ) -> None:
        if price <= 0:
            raise ValueError("Snapshot price must be greater than zero.")
        position = self.get_position(position_id)
        if position is None:
            raise KeyError(f"Unknown position: {position_id}")
        moment = captured_at or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        market_value = position.shares * price + position.cash
        pnl = market_value - position.budget
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO snapshots
                    (position_id, captured_at, price, market_value, pnl)
                VALUES (?, ?, ?, ?, ?)
                """,
                (position_id, moment.isoformat(), price, market_value, pnl),
            )

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        *,
        closed_at: datetime | None = None,
    ) -> PaperPosition:
        if exit_price <= 0:
            raise ValueError("Exit price must be greater than zero.")
        position = self.get_position(position_id)
        if position is None:
            raise KeyError(f"Unknown position: {position_id}")
        if position.status == "CLOSED":
            return position
        moment = closed_at or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        pnl = position.shares * exit_price + position.cash - position.budget
        return_pct = pnl / position.budget * 100
        self.record_snapshot(position_id, exit_price, captured_at=moment)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE positions
                   SET status = 'CLOSED', exit_price = ?, closed_at = ?, pnl = ?, return_pct = ?
                 WHERE id = ?
                """,
                (exit_price, moment.isoformat(), pnl, return_pct, position_id),
            )
        closed = self.get_position(position_id)
        if closed is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("Position vanished after it was closed.")
        return closed

    def get_position(self, position_id: str) -> PaperPosition | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM positions WHERE id = ?", (position_id,)
            ).fetchone()
        return _position_from_row(row) if row else None

    def positions(self, status: str | None = None) -> list[PaperPosition]:
        query = "SELECT * FROM positions"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status.upper(),)
        query += " ORDER BY opened_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_position_from_row(row) for row in rows]

    def snapshots(self, position_id: str) -> pd.DataFrame:
        with self._connect() as connection:
            frame = pd.read_sql_query(
                """
                SELECT captured_at, price, market_value, pnl
                  FROM snapshots
                 WHERE position_id = ?
                 ORDER BY captured_at
                """,
                connection,
                params=(position_id,),
                parse_dates=["captured_at"],
            )
        return frame


def _position_from_row(row: sqlite3.Row) -> PaperPosition:
    return PaperPosition(
        id=row["id"],
        ticker=row["ticker"],
        budget=float(row["budget"]),
        shares=float(row["shares"]),
        cash=float(row["cash"]),
        entry_price=float(row["entry_price"]),
        opened_at=datetime.fromisoformat(row["opened_at"]),
        session_date=row["session_date"],
        status=row["status"],
        exit_price=float(row["exit_price"]) if row["exit_price"] is not None else None,
        closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
        pnl=float(row["pnl"]) if row["pnl"] is not None else None,
        return_pct=float(row["return_pct"]) if row["return_pct"] is not None else None,
        rationale=json.loads(row["rationale_json"]),
    )
