from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from paperalpha.config import (
    DEFAULT_DB_PATH,
    DEFAULT_DEEP_SCAN_SIZE,
    DEFAULT_TRADER_SIGNALS_PATH,
    NOTIFICATION_CONFIG_PATH,
    REPORT_DIR,
    initialize_runtime_files,
)
from paperalpha.domain import TickerAnalysis
from paperalpha.intraday_signals import IntradayExitConfig, evaluate_intraday_exit
from paperalpha.market_clock import MarketClock
from paperalpha.market_data import MarketDataError, YahooMarketData
from paperalpha.monitor import PositionMonitor
from paperalpha.notifications import NtfyNotifier, load_notification_config
from paperalpha.reporting import SessionReporter
from paperalpha.research import ResearchEngine
from paperalpha.sentiment import FinancialNewsSentiment
from paperalpha.storage import PortfolioStore
from paperalpha.trader_signals import PublicTraderSignals


class Notifier(Protocol):
    def send(
        self,
        title: str,
        message: str,
        *,
        priority: str = "default",
        tags: tuple[str, ...] = (),
        click_url: str = "",
    ) -> None: ...


@dataclass(frozen=True)
class PaperDayConfig:
    budget: float = 1_000.0
    budget_gbp: float | None = None
    fractional_shares: bool = False
    include_news: bool = True
    deep_scan_size: int = DEFAULT_DEEP_SCAN_SIZE
    prepare_minutes: int = 120
    dashboard_url: str = ""
    exit_rules: IntradayExitConfig = IntradayExitConfig()


class DailyPaperTrader:
    """Run one transparent buy-at-open/sell-at-close paper experiment."""

    def __init__(
        self,
        *,
        engine: ResearchEngine,
        market_data: YahooMarketData,
        store: PortfolioStore,
        clock: MarketClock,
        monitor: PositionMonitor,
        notifier: Notifier,
        config: PaperDayConfig,
    ) -> None:
        self.engine = engine
        self.market_data = market_data
        self.store = store
        self.clock = clock
        self.monitor = monitor
        self.notifier = notifier
        self.config = config
        self.candidate: TickerAnalysis | None = None
        self.prepared_for: date | None = None

    def step(self, now: datetime | None = None) -> list[str]:
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        session = self.clock.session_info(moment)
        target_open = session.market_open or session.next_open
        events: list[str] = []

        if target_open is not None:
            target_date = target_open.date()
            if self.prepared_for != target_date:
                self.candidate = None
                self.prepared_for = None
            until_open = target_open - moment
            if self.candidate is None and timedelta(0) <= until_open <= timedelta(
                minutes=self.config.prepare_minutes
            ):
                self._prepare(target_date, moment)
                events.append(f"Prepared {self.candidate.ticker} for {target_date}.")

        if session.state == "open" and session.market_open is not None:
            session_date = session.market_open.date().isoformat()
            todays_positions = [
                position
                for position in self.store.positions()
                if position.session_date == session_date
            ]
            if not todays_positions:
                if self.candidate is None or self.prepared_for != session.market_open.date():
                    self._prepare(session.market_open.date(), moment)
                position = self._open_paper_position(moment)
                events.append(
                    f"Paper BUY {position.ticker}: {position.shares:,.6g} shares "
                    f"at ${position.entry_price:,.2f}."
                )

        before = {position.id: position.status for position in self.store.positions(status="OPEN")}
        monitor_events = self.monitor.update_once(moment)
        events.extend(monitor_events)
        for position_id in before:
            position = self.store.get_position(position_id)
            if position is not None and position.status == "CLOSED":
                self.notifier.send(
                    f"PAPER SELL - {position.ticker}",
                    f"ACTION: SELL. Official market-close exit at ${position.exit_price:,.2f}. "
                    f"P/L ${position.pnl:,.2f} ({position.return_pct:+.2f}%). "
                    "No real order was placed.",
                    priority="high",
                    tags=("checkered_flag", "chart_with_upwards_trend"),
                    click_url=self.config.dashboard_url,
                )

        if session.state == "open":
            events.extend(self._apply_intraday_exit_rules(moment))
        return events

    def session_complete(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        session = self.clock.session_info(moment)
        if session.state != "after_hours" or session.market_open is None:
            return False
        session_date = session.market_open.date().isoformat()
        positions = [
            position for position in self.store.positions() if position.session_date == session_date
        ]
        return bool(positions) and all(position.status == "CLOSED" for position in positions)

    def _prepare(self, session_date: date, moment: datetime) -> None:
        scan = self.engine.scan_market(
            as_of=moment,
            include_news=self.config.include_news,
            deep_scan_size=self.config.deep_scan_size,
        )
        if not scan.analyses:
            raise RuntimeError("The research scan returned no paper-trade candidates.")
        self.candidate = scan.analyses[0]
        self.prepared_for = session_date
        pick = self.candidate
        self.notifier.send(
            f"WAIT - PaperAlpha watchlist - {pick.ticker}",
            f"ACTION: WAIT. Pre-market candidate for {session_date}: {pick.ticker} at the latest reference "
            f"price ${pick.price:,.2f}; score {pick.score:.1f}/100 and signal strength "
            f"{pick.signal_strength:.0f}/100. WAIT for the separate paper BUY alert after open.",
            tags=("eyes", "mag"),
            click_url=self.config.dashboard_url,
        )

    def _open_paper_position(self, moment: datetime):
        if self.candidate is None:
            raise RuntimeError("A candidate must be prepared before opening a paper position.")
        live_price = self.market_data.latest_price(self.candidate.ticker)
        budget, budget_description = self._paper_budget()
        analysis = replace(self.candidate, price=live_price)
        position = self.store.open_position(
            analysis,
            budget,
            opened_at=moment,
            fractional_shares=self.config.fractional_shares,
        )
        self.notifier.send(
            f"PAPER BUY - {position.ticker}",
            f"ACTION: BUY. Simulated entry: {position.shares:,.6g} shares at "
            f"${position.entry_price:,.2f}; "
            f"paper budget {budget_description}. Hold for today's experiment until the "
            "official close. No real order was placed.",
            priority="high",
            tags=("large_green_circle", "chart_with_upwards_trend"),
            click_url=self.config.dashboard_url,
        )
        return position

    def _paper_budget(self) -> tuple[float, str]:
        if self.config.budget_gbp is None:
            return self.config.budget, f"${self.config.budget:,.2f}"
        gbp_usd = self.market_data.latest_price("GBPUSD=X")
        usd_budget = self.config.budget_gbp * gbp_usd
        return (
            usd_budget,
            f"£{self.config.budget_gbp:,.2f} (${usd_budget:,.2f} at GBP/USD {gbp_usd:.4f})",
        )

    def _apply_intraday_exit_rules(self, moment: datetime) -> list[str]:
        events: list[str] = []
        for position in self.store.positions(status="OPEN"):
            decision = evaluate_intraday_exit(
                position,
                self.store.snapshots(position.id),
                moment,
                self.config.exit_rules,
            )
            if decision is None:
                continue
            closed = self.store.close_position(position.id, decision.price, closed_at=moment)
            self.monitor.reporter.write(
                position.session_date,
                [
                    item
                    for item in self.store.positions(status="CLOSED")
                    if item.session_date == position.session_date
                ],
            )
            self.notifier.send(
                f"PAPER SELL - {closed.ticker}",
                f"ACTION: SELL. {decision.reason.capitalize()}. Simulated exit "
                f"${closed.exit_price:,.2f}; P/L ${closed.pnl:+,.2f} "
                f"({closed.return_pct:+.2f}%). No real order was placed.",
                priority="high",
                tags=("red_circle", "chart_with_downwards_trend"),
                click_url=self.config.dashboard_url,
            )
            events.append(
                f"Paper SELL {closed.ticker} at ${closed.exit_price:,.2f}: "
                f"{decision.code}; P/L ${closed.pnl:+,.2f}."
            )
        return events


def build_day_trader(args: argparse.Namespace) -> DailyPaperTrader:
    market_data = YahooMarketData()
    store = PortfolioStore(args.db)
    clock = MarketClock()
    reporter = SessionReporter(REPORT_DIR)
    monitor = PositionMonitor(store, market_data, clock, reporter)
    engine = ResearchEngine(
        market_data,
        FinancialNewsSentiment(),
        PublicTraderSignals(DEFAULT_TRADER_SIGNALS_PATH),
    )
    notifier = NtfyNotifier(load_notification_config(args.notification_config))
    return DailyPaperTrader(
        engine=engine,
        market_data=market_data,
        store=store,
        clock=clock,
        monitor=monitor,
        notifier=notifier,
        config=PaperDayConfig(
            budget=args.budget if args.budget is not None else 1_000.0,
            budget_gbp=args.budget_gbp,
            fractional_shares=args.fractional,
            include_news=not args.no_news,
            deep_scan_size=args.deep_scan_size,
            prepare_minutes=args.prepare_minutes,
            dashboard_url=args.dashboard_url,
            exit_rules=IntradayExitConfig(
                hard_stop_pct=args.stop_loss_pct,
                take_profit_pct=args.take_profit_pct,
                trailing_activation_pct=args.trailing_activation_pct,
                trailing_drawdown_pct=args.trailing_drawdown_pct,
                reversal_lookback_minutes=args.reversal_lookback_minutes,
                reversal_drop_pct=args.reversal_drop_pct,
                minimum_hold_minutes=args.minimum_hold_minutes,
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one automated, notification-backed PaperAlpha paper-trading day."
    )
    budget_group = parser.add_mutually_exclusive_group()
    budget_group.add_argument("--budget", type=float, default=None, help="Paper budget in USD.")
    budget_group.add_argument("--budget-gbp", type=float, help="Paper budget in GBP.")
    parser.add_argument("--fractional", action="store_true", help="Allow fractional paper shares.")
    parser.add_argument("--no-news", action="store_true", help="Skip current headline sentiment.")
    parser.add_argument("--deep-scan-size", type=int, default=DEFAULT_DEEP_SCAN_SIZE)
    parser.add_argument("--prepare-minutes", type=int, default=120)
    parser.add_argument("--stop-loss-pct", type=float, default=3.0)
    parser.add_argument("--take-profit-pct", type=float, default=5.0)
    parser.add_argument("--trailing-activation-pct", type=float, default=2.0)
    parser.add_argument("--trailing-drawdown-pct", type=float, default=1.5)
    parser.add_argument("--reversal-lookback-minutes", type=int, default=5)
    parser.add_argument("--reversal-drop-pct", type=float, default=1.25)
    parser.add_argument("--minimum-hold-minutes", type=int, default=10)
    parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds.")
    parser.add_argument("--dashboard-url", default="", help="Optional URL opened from alerts.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--notification-config", default=str(NOTIFICATION_CONFIG_PATH))
    parser.add_argument("--once", action="store_true", help="Run one state-machine step and exit.")
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Stay online after the closing report and prepare again on the next market day.",
    )
    args = parser.parse_args()
    if args.budget is not None and args.budget <= 0:
        parser.error("--budget must be positive.")
    if args.budget_gbp is not None and args.budget_gbp <= 0:
        parser.error("--budget-gbp must be positive.")
    if args.interval < 15:
        parser.error("--interval must be at least 15 seconds.")
    if (
        min(
            args.stop_loss_pct,
            args.take_profit_pct,
            args.trailing_activation_pct,
            args.trailing_drawdown_pct,
            args.reversal_drop_pct,
        )
        <= 0
    ):
        parser.error("Intraday percentage thresholds must be positive.")
    if args.reversal_lookback_minutes < 2 or args.minimum_hold_minutes < 2:
        parser.error("Intraday time windows must be at least 2 minutes.")

    initialize_runtime_files()
    trader = build_day_trader(args)
    trader.notifier.send(
        "PaperAlpha runner online",
        "The laptop is connected. Today's actions are simulated paper trades only.",
        tags=("computer", "white_check_mark"),
        click_url=args.dashboard_url,
    )
    while True:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            events = trader.step()
            for event in events or ["Waiting for the next paper-trading event."]:
                print(f"[{timestamp}] {event}", flush=True)
        except (MarketDataError, RuntimeError) as exc:
            print(f"[{timestamp}] {exc}", flush=True)
        if args.once or (not args.continuous and trader.session_complete()):
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
