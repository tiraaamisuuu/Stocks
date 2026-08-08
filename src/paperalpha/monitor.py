from __future__ import annotations

import argparse
import time
from collections import defaultdict
from datetime import datetime, timezone

from paperalpha.config import DEFAULT_DB_PATH, REPORT_DIR
from paperalpha.market_clock import MarketClock
from paperalpha.market_data import MarketDataError, YahooMarketData
from paperalpha.reporting import SessionReporter
from paperalpha.storage import PortfolioStore


class PositionMonitor:
    def __init__(
        self,
        store: PortfolioStore,
        market_data: YahooMarketData,
        clock: MarketClock,
        reporter: SessionReporter,
    ) -> None:
        self.store = store
        self.market_data = market_data
        self.clock = clock
        self.reporter = reporter

    def update_once(self, now: datetime | None = None) -> list[str]:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        events: list[str] = []
        newly_closed_dates: set[str] = set()

        for position in self.store.positions(status="OPEN"):
            bounds = self.clock.session_bounds(position.session_date)
            if bounds is None:
                events.append(f"Skipped {position.ticker}: {position.session_date} is not a market session.")
                continue
            market_open, market_close = bounds
            try:
                if moment >= market_close:
                    close = self.market_data.session_close(
                        position.ticker, datetime.fromisoformat(position.session_date).date()
                    )
                    closed = self.store.close_position(
                        position.id,
                        close,
                        closed_at=market_close,
                    )
                    newly_closed_dates.add(position.session_date)
                    events.append(
                        f"Closed {closed.ticker} at ${close:,.2f}: "
                        f"P/L ${closed.pnl:,.2f} ({closed.return_pct:+.2f}%)."
                    )
                elif moment >= market_open:
                    price = self.market_data.latest_price(position.ticker)
                    self.store.record_snapshot(position.id, price, captured_at=moment)
                    pnl = position.shares * price + position.cash - position.budget
                    events.append(f"Updated {position.ticker} at ${price:,.2f}: P/L ${pnl:,.2f}.")
            except MarketDataError as exc:
                events.append(str(exc))

        closed_by_date: dict[str, list] = defaultdict(list)
        for position in self.store.positions(status="CLOSED"):
            if position.session_date in newly_closed_dates:
                closed_by_date[position.session_date].append(position)
        for session_date, positions in closed_by_date.items():
            json_path, _ = self.reporter.write(session_date, positions)
            events.append(f"Wrote end-of-day report: {json_path}")
        return events


def build_monitor(db_path=DEFAULT_DB_PATH) -> PositionMonitor:
    return PositionMonitor(
        store=PortfolioStore(db_path),
        market_data=YahooMarketData(),
        clock=MarketClock(),
        reporter=SessionReporter(REPORT_DIR),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Track PaperAlpha positions and close them at the bell.")
    parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Update once and exit.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the SQLite portfolio.")
    args = parser.parse_args()
    if args.interval < 15:
        parser.error("--interval must be at least 15 seconds.")

    monitor = build_monitor(args.db)
    while True:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        events = monitor.update_once()
        if events:
            for event in events:
                print(f"[{timestamp}] {event}", flush=True)
        else:
            print(f"[{timestamp}] No open position needed an update.", flush=True)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

