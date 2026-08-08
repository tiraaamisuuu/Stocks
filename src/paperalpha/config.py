from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "PaperAlpha"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    DATA_DIR = USER_DATA_DIR
    STATE_DIR = USER_DATA_DIR
else:
    USER_DATA_DIR = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"
    STATE_DIR = PROJECT_ROOT / "state"

REPORT_DIR = STATE_DIR / "reports"
DEFAULT_DB_PATH = STATE_DIR / "paperalpha.db"
YFINANCE_CACHE_DIR = STATE_DIR / "yfinance-cache"
DEFAULT_TRADER_SIGNALS_PATH = DATA_DIR / "trader_signals.csv"
UNIVERSE_CACHE_PATH = STATE_DIR / "us_listed_stocks.csv"


def initialize_runtime_files() -> None:
    """Create writable state and seed the disclosure CSV for packaged builds."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not IS_FROZEN or DEFAULT_TRADER_SIGNALS_PATH.exists():
        return
    bundled_signals = BUNDLE_ROOT / "data" / "trader_signals.csv"
    if bundled_signals.exists():
        shutil.copyfile(bundled_signals, DEFAULT_TRADER_SIGNALS_PATH)


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
    "momentum": 0.16,
    "trend": 0.12,
    "market": 0.08,
    "quality": 0.13,
    "value": 0.09,
    "analyst": 0.08,
    "news": 0.11,
    "risk": 0.09,
    "setup": 0.05,
    "liquidity": 0.04,
    "volume": 0.03,
    "event": 0.01,
    "trader": 0.01,
}

PRICE_ONLY_FACTOR_WEIGHTS = {
    "momentum": 0.28,
    "trend": 0.21,
    "market": 0.14,
    "risk": 0.16,
    "setup": 0.10,
    "liquidity": 0.06,
    "volume": 0.05,
}

MIN_HISTORY_ROWS = 200
NEWS_LIMIT_PER_TICKER = 10
MAX_CUSTOM_SCAN_SIZE = 100
DEFAULT_DEEP_SCAN_SIZE = 80
MAX_DEEP_SCAN_SIZE = 150
MAX_NEWS_CANDIDATES = 35
SCREENER_PAGE_SIZE = 250
MAX_SCREENER_RESULTS = 5_000
