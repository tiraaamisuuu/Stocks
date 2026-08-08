from __future__ import annotations

from dataclasses import replace
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from paperalpha.backtest import walk_forward_backtest
from paperalpha.config import (
    APP_NAME,
    DEFAULT_DB_PATH,
    DEFAULT_TRADER_SIGNALS_PATH,
    DEFAULT_UNIVERSE,
    REPORT_DIR,
)
from paperalpha.market_clock import MarketClock
from paperalpha.market_data import MarketDataError, YahooMarketData
from paperalpha.monitor import PositionMonitor
from paperalpha.reporting import SessionReporter
from paperalpha.research import ResearchEngine
from paperalpha.sentiment import FinancialNewsSentiment
from paperalpha.storage import PortfolioStore
from paperalpha.trader_signals import PublicTraderSignals


def _parse_tickers(value: str) -> tuple[list[str], list[str]]:
    import re

    candidates = value.replace(",", " ").split()
    symbols: list[str] = []
    invalid: list[str] = []
    for candidate in candidates:
        symbol = candidate.upper().strip()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,9}", symbol):
            invalid.append(candidate)
        elif symbol not in symbols:
            symbols.append(symbol)
    return symbols, invalid


st.set_page_config(page_title=APP_NAME, page_icon="📈", layout="wide")
st.markdown(
    """
    <style>
      .block-container {max-width: 1240px; padding-top: 2.25rem;}
      .pa-kicker {color:#42D39A; font-size:.78rem; font-weight:800; letter-spacing:.14em;}
      .pa-hero {font-size:3rem; line-height:1.02; font-weight:800; margin:.25rem 0 .65rem;}
      .pa-muted {color:#91A4BA; max-width:760px;}
      .pa-card {background:linear-gradient(135deg,#13243A,#0E1929); border:1px solid #253850;
                border-radius:16px; padding:1.15rem 1.25rem; margin:.5rem 0 1rem;}
      .pa-ticker {color:#42D39A; font-size:2.4rem; font-weight:850;}
      .pa-pill {display:inline-block; border:1px solid #2D4B5C; border-radius:999px;
                padding:.28rem .7rem; color:#B8C8D9; font-size:.8rem;}
      div[data-testid="stMetric"] {background:#101C2D; border:1px solid #213650;
                padding:.8rem 1rem; border-radius:12px;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def resources():
    market_data = YahooMarketData()
    store = PortfolioStore(DEFAULT_DB_PATH)
    clock = MarketClock()
    reporter = SessionReporter(REPORT_DIR)
    engine = ResearchEngine(
        market_data,
        FinancialNewsSentiment(),
        PublicTraderSignals(DEFAULT_TRADER_SIGNALS_PATH),
    )
    monitor = PositionMonitor(store, market_data, clock, reporter)
    return market_data, store, clock, engine, monitor


@st.cache_data(ttl=900, show_spinner=False)
def cached_scan(tickers: tuple[str, ...], include_news: bool):
    return resources()[3].scan(list(tickers), include_news=include_news)


@st.cache_data(ttl=900, show_spinner=False)
def cached_history(tickers: tuple[str, ...], period: str):
    return resources()[0].daily_history(list(tickers), period=period)


market_data, store, clock, engine, monitor = resources()
session = clock.session_info()

st.markdown('<div class="pa-kicker">EXPLAINABLE PAPER TRADING</div>', unsafe_allow_html=True)
st.markdown('<div class="pa-hero">Find a signal. Test the thesis.</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="pa-muted">PaperAlpha ranks a liquid stock universe from price action, '
    "risk, volume, news tone, and point-in-time public disclosures—then measures the "
    "idea instead of pretending it was a certainty.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Research setup")
    budget = st.number_input("Paper budget (USD)", min_value=25.0, value=10_000.0, step=250.0)
    ticker_text = st.text_area(
        "Ticker universe",
        value=", ".join(DEFAULT_UNIVERSE),
        height=125,
        help="Comma- or space-separated US ticker symbols; 2–30 tickers.",
    )
    fractional = st.toggle("Allow fractional shares", value=False)
    include_news = st.toggle("Include current news tone", value=True)
    scan_clicked = st.button("Run research scan", type="primary", use_container_width=True)
    st.divider()
    status_icon = "🟢" if session.state == "open" else "🟠"
    st.caption(f"{status_icon} {session.label}")
    if session.market_close and session.state == "open":
        close_london = session.market_close.astimezone(ZoneInfo("Europe/London"))
        st.caption(f"Closes {close_london:%H:%M %Z}")
    elif session.next_open:
        next_london = session.next_open.astimezone(ZoneInfo("Europe/London"))
        st.caption(f"Next open {next_london:%a %d %b, %H:%M %Z}")
    st.caption("Educational research only · delayed/free data")

symbols, invalid = _parse_tickers(ticker_text)
if invalid:
    st.sidebar.error(f"Invalid ticker symbols: {', '.join(invalid)}")

if scan_clicked:
    if invalid or not 2 <= len(symbols) <= 30:
        st.error("Enter between 2 and 30 valid ticker symbols.")
    else:
        with st.spinner(f"Scoring {len(symbols)} stocks and reading recent headlines…"):
            try:
                cached_scan.clear()
                st.session_state["analysis"] = cached_scan(tuple(symbols), include_news)
                st.session_state["scan_symbols"] = symbols
            except Exception as exc:
                st.error(f"The scan could not finish: {exc}")

pick_tab, live_tab, lab_tab, reports_tab, method_tab = st.tabs(
    ["Paper pick", "Live book", "Model lab", "Reports", "Method"]
)

with pick_tab:
    analyses = st.session_state.get("analysis", [])
    if not analyses:
        st.info("Set a budget and run the research scan to generate a paper pick.")
    else:
        pick = analyses[0]
        shares = budget / pick.price if fractional else int(budget // pick.price)
        cash = max(0.0, budget - shares * pick.price)
        st.markdown(
            f'<div class="pa-card"><span class="pa-pill">TOP-RANKED PAPER IDEA</span>'
            f'<div class="pa-ticker">{pick.ticker}</div>'
            f"<div>Highest composite score in this scan—not a promise of a positive return.</div></div>",
            unsafe_allow_html=True,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reference price", f"${pick.price:,.2f}")
        c2.metric("Model score", f"{pick.score:.1f} / 100")
        c3.metric("Signal strength", f"{pick.signal_strength:.0f} / 100")
        c4.metric("Paper order", f"{shares:,.4f}" if fractional else f"{shares:,.0f} shares")
        st.caption(
            f"Estimated unused cash: ${cash:,.2f}. The entry is repriced when the paper trade starts."
        )

        if session.state != "open":
            st.warning(
                "The exchange is not open, so PaperAlpha will not fabricate an executable entry. "
                "Run the app during the next session to start tracking this idea."
            )
        if st.button(
            f"Start ${budget:,.0f} paper trade in {pick.ticker}",
            type="primary",
            disabled=session.state != "open",
        ):
            try:
                live_price = market_data.latest_price(pick.ticker)
                live_pick = replace(pick, price=live_price)
                position = store.open_position(
                    live_pick,
                    budget,
                    fractional_shares=fractional,
                )
                st.success(
                    f"Opened {position.shares:,.6g} paper shares of {position.ticker} "
                    f"at ${position.entry_price:,.2f}."
                )
            except (MarketDataError, ValueError) as exc:
                st.error(str(exc))

        st.subheader("Why it ranked first")
        factor_frame = pd.DataFrame(
            {"Factor": list(pick.factor_scores), "Score": list(pick.factor_scores.values())}
        ).sort_values("Score", ascending=False)
        st.bar_chart(factor_frame.set_index("Factor"), horizontal=True, color="#42D39A")
        with st.expander("Risk flags and data gaps", expanded=bool(pick.warnings)):
            if pick.warnings:
                for warning in pick.warnings:
                    st.write(f"• {warning}")
            else:
                st.write("No automatic flags were raised.")

        st.subheader("Full ranking")
        ranking = pd.DataFrame(
            [
                {
                    "Rank": index,
                    "Ticker": item.ticker,
                    "Score": item.score,
                    "Price": item.price,
                    "20d return": item.metrics["return_20d"],
                    "20d volatility": item.metrics["volatility_20d"],
                    "RSI (14)": item.metrics["rsi_14"],
                }
                for index, item in enumerate(analyses, start=1)
            ]
        )
        st.dataframe(
            ranking,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Price": st.column_config.NumberColumn(format="$%.2f"),
                "20d return": st.column_config.NumberColumn(format="percent"),
                "20d volatility": st.column_config.NumberColumn(format="percent"),
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
            },
        )

        if pick.headlines:
            st.subheader(f"Recent {pick.ticker} headlines")
            for headline in pick.headlines[:6]:
                tone = (
                    "positive"
                    if headline.sentiment > 0.15
                    else "negative"
                    if headline.sentiment < -0.15
                    else "neutral"
                )
                title = f"[{headline.title}]({headline.url})" if headline.url else headline.title
                source = f" · {headline.publisher}" if headline.publisher else ""
                st.markdown(f"{title}  \n`{tone} {headline.sentiment:+.2f}`{source}")

with live_tab:
    st.caption(
        "This panel refreshes once per minute while the page is open. Run the background monitor for unattended tracking."
    )

    @st.fragment(run_every="60s")
    def live_book():
        events = monitor.update_once()
        for event in events:
            st.toast(event)
        positions = store.positions(status="OPEN")
        if not positions:
            st.info("There are no open paper positions.")
            return
        for position in positions:
            snapshots = store.snapshots(position.id)
            latest = (
                float(snapshots["price"].iloc[-1]) if not snapshots.empty else position.entry_price
            )
            pnl = position.shares * latest + position.cash - position.budget
            pnl_pct = pnl / position.budget * 100
            with st.container(border=True):
                left, middle, right = st.columns([2, 1, 1])
                left.subheader(position.ticker)
                left.caption(f"{position.shares:,.6g} shares · entry ${position.entry_price:,.2f}")
                middle.metric("Latest", f"${latest:,.2f}")
                right.metric("Unrealized P/L", f"${pnl:,.2f}", f"{pnl_pct:+.2f}%")
                if len(snapshots) >= 2:
                    chart = go.Figure()
                    chart.add_trace(
                        go.Scatter(
                            x=snapshots["captured_at"],
                            y=snapshots["market_value"],
                            mode="lines",
                            name="Portfolio value",
                            line={"color": "#42D39A", "width": 2},
                        )
                    )
                    chart.add_hline(y=position.budget, line_dash="dot", line_color="#91A4BA")
                    chart.update_layout(
                        height=280,
                        margin={"l": 5, "r": 5, "t": 10, "b": 5},
                        xaxis_title=None,
                        yaxis_title="USD",
                        template="plotly_dark",
                        showlegend=False,
                    )
                    st.plotly_chart(chart, use_container_width=True)

    live_book()
    st.code("paperalpha-monitor --interval 60", language="bash")
    st.caption(
        "Keep that command running in a terminal for unattended tracking and automatic close reports."
    )

with lab_tab:
    st.subheader("Walk-forward test")
    st.write(
        "Signals use information through one close, enter at the next session's open, and include "
        "round-trip costs. News and trader factors stay neutral because this free setup does not "
        "have point-in-time archives for them."
    )
    hold_days = st.slider("Holding period (sessions)", 1, 20, 5)
    costs = st.slider("Transaction cost (basis points per side)", 0, 25, 5)
    if st.button("Run 2-year walk-forward test"):
        test_symbols = tuple(st.session_state.get("scan_symbols", symbols))
        if len(test_symbols) < 2:
            st.error("Select at least two tickers first.")
        else:
            with st.spinner("Walking forward through historical sessions…"):
                try:
                    histories = cached_history(test_symbols, "2y")
                    result = walk_forward_backtest(
                        histories,
                        initial_cash=budget,
                        hold_days=hold_days,
                        transaction_cost_bps=costs,
                    )
                    st.session_state["backtest"] = result
                except Exception as exc:
                    st.error(f"Backtest failed: {exc}")
    result = st.session_state.get("backtest")
    if result:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total return", f"{result.metrics['total_return']:+.1%}")
        m2.metric("Annualized", f"{result.metrics['annualized_return']:+.1%}")
        m3.metric("Max drawdown", f"{result.metrics['max_drawdown']:.1%}")
        m4.metric("Win rate", f"{result.metrics['win_rate']:.1%}")
        st.line_chart(result.equity_curve, color="#42D39A")
        with st.expander("Backtest trades"):
            st.dataframe(result.trades, hide_index=True, use_container_width=True)
        st.warning("A backtest describes this sample; it does not establish future accuracy.")

with reports_tab:
    all_positions = store.positions()
    if not all_positions:
        st.info("Completed and open paper positions will appear here.")
    else:
        report_frame = pd.DataFrame(
            [
                {
                    "Ticker": p.ticker,
                    "Status": p.status,
                    "Opened": p.opened_at,
                    "Budget": p.budget,
                    "Entry": p.entry_price,
                    "Exit": p.exit_price,
                    "P/L": p.pnl,
                    "Return %": p.return_pct,
                }
                for p in all_positions
            ]
        )
        st.dataframe(report_frame, hide_index=True, use_container_width=True)
        st.download_button(
            "Download position ledger (CSV)",
            report_frame.to_csv(index=False).encode("utf-8"),
            file_name="paperalpha-position-ledger.csv",
            mime="text/csv",
        )

with method_tab:
    st.subheader("What the score means")
    st.write(
        "Each price-based feature is compared with the other stocks in the selected universe using "
        "a robust median/MAD transform. A score of 70 means stronger relative evidence than 50; it "
        "does not mean a 70% chance of profit."
    )
    st.markdown(
        """
| Factor | Weight | What is measured |
|---|---:|---|
| Momentum | 30% | 5-, 20-, and 60-session adjusted returns |
| Trend | 20% | Price vs. 20-day average and 20- vs. 50-day average |
| News | 20% | Time-decayed sentiment from recent headlines |
| Risk | 15% | Realized volatility and current 60-day drawdown |
| Volume | 10% | Recent volume confirmation of price direction |
| Public traders | 5% | Time-decayed, disclosure-available buy/sell records |
        """
    )
    st.info(
        "Free Yahoo data is intended for personal research and may be delayed. Replace the provider "
        "adapter with a licensed feed before relying on real-time execution."
    )
