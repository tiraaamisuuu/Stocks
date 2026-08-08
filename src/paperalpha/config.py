from __future__ import annotations

from pathlib import Path

APP_NAME = "PaperAlpha"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = PROJECT_ROOT / "state"
REPORT_DIR = STATE_DIR / "reports"
DEFAULT_DB_PATH = STATE_DIR / "paperalpha.db"
YFINANCE_CACHE_DIR = STATE_DIR / "yfinance-cache"
DEFAULT_TRADER_SIGNALS_PATH = DATA_DIR / "trader_signals.csv"

# A deliberately liquid, cross-sector US large-cap research universe. Users can
# replace it in the dashboard; it is not presented as a list of recommendations.
DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "AVGO",
    "JPM",
    "V",
    "XOM",
    "WMT",
    "COST",
    "AMD",
    "CRM",
    "LLY",
]

FACTOR_WEIGHTS = {
    "momentum": 0.30,
    "trend": 0.20,
    "news": 0.20,
    "risk": 0.15,
    "volume": 0.10,
    "trader": 0.05,
}

MIN_HISTORY_ROWS = 70
NEWS_LIMIT_PER_TICKER = 10
MAX_SCAN_SIZE = 30
