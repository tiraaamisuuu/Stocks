from __future__ import annotations

import re
from dataclasses import replace
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from paperalpha.backtest import walk_forward_backtest
from paperalpha.config import (
    APP_NAME,
    DEFAULT_DB_PATH,
    DEFAULT_DEEP_SCAN_SIZE,
    DEFAULT_TRADER_SIGNALS_PATH,
    DEFAULT_UNIVERSE,
    FACTOR_WEIGHTS,
    MAX_CUSTOM_SCAN_SIZE,
    MAX_DEEP_SCAN_SIZE,
    REPORT_DIR,
    initialize_runtime_files,
)
from paperalpha.market_clock import MarketClock
from paperalpha.market_data import MarketDataError, YahooMarketData
from paperalpha.monitor import PositionMonitor
from paperalpha.reporting import SessionReporter
from paperalpha.research import ResearchEngine
from paperalpha.sentiment import FinancialNewsSentiment
from paperalpha.storage import PortfolioStore
from paperalpha.trader_signals import PublicTraderSignals

initialize_runtime_files()


def _parse_tickers(value: str) -> tuple[list[str], list[str]]:
    candidates = value.replace(",", " ").split()
    symbols: list[str] = []
    invalid: list[str] = []
    for candidate in candidates:
        symbol = candidate.upper().strip()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,13}", symbol):
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
      .pa-muted {color:#91A4BA; max-width:820px;}
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
def cached_market_scan(
    include_news: bool,
    min_price: float,
    min_average_volume: int,
    min_market_cap: int,
    deep_scan_size: int,
):
    return resources()[3].scan_market(
        include_news=include_news,
        min_price=min_price,
        min_average_volume=min_average_volume,
        min_market_cap=min_market_cap,
        deep_scan_size=deep_scan_size,
    )


@st.cache_data(ttl=900, show_spinner=False)
def cached_history(tickers: tuple[str, ...], period: str):
    return resources()[0].daily_history(list(tickers), period=period)


market_data, store, clock, engine, monitor = resources()
session = clock.session_info()

st.markdown('<div class="pa-kicker">EXPLAINABLE PAPER TRADING</div>', unsafe_allow_html=True)
st.markdown('<div class="pa-hero">Find a signal. Test the thesis.</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="pa-muted">PaperAlpha screens the US stock market using price action, '
    "fundamentals, analyst expectations, risk, liquidity, news, and public disclosures—then "
    "measures the paper idea instead of pretending it was a certainty.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Research setup")
    budget = st.number_input("Paper budget (USD)", min_value=25.0, value=10_000.0, step=250.0)
    universe_mode = st.selectbox(
        "Stock universe",
        ("Full US market", "Starter universe", "Custom tickers"),
        help="Full market uses the current Nasdaq Trader directory and a two-stage scan.",
    )
    ticker_text = ""
    min_price = 3.0
    min_average_volume = 500_000
    min_market_cap = 300_000_000
    deep_scan_size = DEFAULT_DEEP_SCAN_SIZE
    if universe_mode == "Full US market":
        st.caption(
            "NASDAQ, NYSE, NYSE American, Arca, Cboe BZX, and IEX stocks; "
            "ETFs and test issues excluded."
        )
        with st.expander("Eligibility and scan depth"):
            min_price = st.number_input(
                "Minimum share price", min_value=1.0, max_value=100.0, value=3.0, step=1.0
            )
            min_average_volume = st.number_input(
                "Minimum 3-month average volume",
                min_value=50_000,
                max_value=10_000_000,
                value=500_000,
                step=50_000,
            )
            min_market_cap_m = st.number_input(
                "Minimum market cap (USD millions)",
                min_value=50,
                max_value=100_000,
                value=300,
                step=50,
            )
            min_market_cap = int(min_market_cap_m * 1_000_000)
            deep_scan_size = st.slider(
                "Deep-analysis candidates",
                min_value=20,
                max_value=MAX_DEEP_SCAN_SIZE,
                value=DEFAULT_DEEP_SCAN_SIZE,
                step=10,
            )
    elif universe_mode == "Starter universe":
        ticker_text = ", ".join(DEFAULT_UNIVERSE)
        st.caption(ticker_text)
    else:
        ticker_text = st.text_area(
            "Ticker symbols",
            value=", ".join(DEFAULT_UNIVERSE),
            height=125,
            help=f"Comma- or space-separated symbols; 2–{MAX_CUSTOM_SCAN_SIZE} tickers.",
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

symbols, invalid = _parse_tickers(ticker_text) if ticker_text else ([], [])
if invalid:
    st.sidebar.error(f"Invalid ticker symbols: {', '.join(invalid)}")

if scan_clicked:
    if universe_mode == "Full US market":
        with st.spinner(
            "Screening the full US directory, then deeply analysing the strongest candidates…"
        ):
            try:
                cached_market_scan.clear()
                scan_result = cached_market_scan(
                    include_news,
                    float(min_price),
                    int(min_average_volume),
                    int(min_market_cap),
                    int(deep_scan_size),
                )
                st.session_state["analysis"] = list(scan_result.analyses)
                st.session_state["research_scan"] = scan_result
                st.session_state["scan_symbols"] = [
                    item.ticker for item in scan_result.analyses[:20]
                ]
            except Exception as exc:
                st.error(f"The scan could not finish: {exc}")
    elif invalid or not 2 <= len(symbols) <= MAX_CUSTOM_SCAN_SIZE:
        st.error(f"Enter between 2 and {MAX_CUSTOM_SCAN_SIZE} valid ticker symbols.")
    else:
        with st.spinner(f"Deeply scoring {len(symbols)} stocks and reading recent headlines…"):
            try:
                cached_scan.clear()
                analyses = cached_scan(tuple(symbols), include_news)
                st.session_state["analysis"] = analyses
                st.session_state["research_scan"] = None
                st.session_state["scan_symbols"] = [item.ticker for item in analyses[:20]]
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
        research_scan = st.session_state.get("research_scan")
        if research_scan:
            st.caption(
                f"Directory: {research_scan.directory_count:,} stocks · "
                f"eligible: {research_scan.eligible_count:,} · "
                f"deeply analysed: {research_scan.deep_count:,}"
            )
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
                position = store.open_position(
                    replace(pick, price=live_price),
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
        factor_chart = go.Figure(
            go.Bar(
                x=factor_frame["Score"],
                y=factor_frame["Factor"],
                orientation="h",
                marker_color="#42D39A",
                hovertemplate="%{y}: %{x:.1f}<extra></extra>",
            )
        )
        factor_chart.update_layout(
            height=430,
            margin={"l": 10, "r": 10, "t": 10, "b": 10},
            xaxis={"range": [0, 100], "title": "Factor score"},
            yaxis={"autorange": "reversed", "title": None},
            template="plotly_dark",
            showlegend=False,
        )
        st.plotly_chart(factor_chart, use_container_width=True)
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
                    "120d return": item.metrics["return_120d"],
                    "vs market (60d)": item.metrics["relative_return_60d"],
                    "20d volatility": item.metrics["volatility_20d"],
                    "RSI (14)": item.metrics["rsi_14"],
                    "Forward P/E": item.metrics.get("forward_pe"),
                    "Revenue growth": item.metrics.get("revenue_growth"),
                    "ROE": item.metrics.get("return_on_equity"),
                    "Analyst upside": item.metrics.get("analyst_upside"),
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
                "120d return": st.column_config.NumberColumn(format="percent"),
                "vs market (60d)": st.column_config.NumberColumn(format="percent"),
                "20d volatility": st.column_config.NumberColumn(format="percent"),
                "Revenue growth": st.column_config.NumberColumn(format="percent"),
                "ROE": st.column_config.NumberColumn(format="percent"),
                "Analyst upside": st.column_config.NumberColumn(format="percent"),
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
            },
        )

        with st.expander(f"{pick.ticker} model inputs"):
            model_inputs = pd.DataFrame(
                [
                    {"Metric": key.replace("_", " ").title(), "Value": value}
                    for key, value in sorted(pick.metrics.items())
                ]
            )
            st.dataframe(model_inputs, hide_index=True, use_container_width=True)

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
        "This panel refreshes once per minute while the page is open. Run the background monitor "
        "for unattended tracking."
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
        "round-trip costs. The test uses the technical sleeve only: this free setup has no "
        "point-in-time archive for fundamentals, analyst revisions, news, or disclosures."
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
                    "Ticker": position.ticker,
                    "Status": position.status,
                    "Opened": position.opened_at,
                    "Budget": position.budget,
                    "Entry": position.entry_price,
                    "Exit": position.exit_price,
                    "P/L": position.pnl,
                    "Return %": position.return_pct,
                }
                for position in all_positions
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
        "Each comparable feature is scored against the other stocks in the deep-analysis set using "
        "a robust median/MAD transform. A score of 70 means stronger relative evidence than 50; it "
        "does not mean a 70% chance of profit."
    )
    factor_descriptions = {
        "momentum": "5/20/60/120-session returns",
        "trend": "20/50/200-day averages and MACD",
        "market": "SPY-relative returns, beta, and market regime",
        "quality": "growth, margins, ROE, cash flow, leverage, liquidity",
        "value": "forward/trailing earnings yield and book yield",
        "analyst": "consensus rating, target upside, and coverage",
        "news": "time-decayed ticker-linked headline sentiment",
        "risk": "volatility, downside risk, ATR, drawdown, beta, short float",
        "setup": "RSI and Bollinger-position entry quality",
        "liquidity": "dollar volume and Amihud illiquidity",
        "volume": "recent volume confirmation",
        "event": "proximity to the next earnings event",
        "trader": "dated public buy/sell disclosures",
    }
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Factor": factor.title(),
                    "Weight": weight,
                    "What is measured": factor_descriptions[factor],
                }
                for factor, weight in FACTOR_WEIGHTS.items()
            ]
        ),
        hide_index=True,
        use_container_width=True,
        column_config={"Weight": st.column_config.NumberColumn(format="percent")},
    )
    st.warning(
        "More inputs do not automatically create predictive accuracy. Validate changes with "
        "walk-forward and out-of-sample tests; current fundamentals and analyst data are not used "
        "in the historical test because a point-in-time archive is not available."
    )
    st.info(
        "Free Yahoo data is intended for personal research and may be delayed. Replace the provider "
        "adapter with a licensed point-in-time feed before relying on serious research or execution."
    )
