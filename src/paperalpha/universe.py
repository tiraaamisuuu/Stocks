from __future__ import annotations

import csv
import re
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

from paperalpha.config import DEFAULT_UNIVERSE, UNIVERSE_CACHE_PATH
from paperalpha.domain import ListedSecurity

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

_EXCLUDED_NAME_PARTS = (
    " warrant",
    " warrants",
    " right",
    " rights",
    " unit",
    " units",
    " preferred",
    " preference",
    " depositary share representing",
    " bond",
    " debenture",
    " notes due",
    " note due",
    "% note",
    " exchange traded note",
)


def _normalise_symbol(value: str) -> str:
    symbol = value.upper().strip().replace(".", "-")
    return symbol if re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,13}", symbol) else ""


def _looks_like_stock(name: str) -> bool:
    lowered = f" {name.lower()}"
    return not any(part in lowered for part in _EXCLUDED_NAME_PARTS)


def parse_symbol_directory(nasdaq_text: str, other_text: str) -> dict[str, ListedSecurity]:
    """Parse Nasdaq Trader's live symbol-directory files into Yahoo-style symbols."""
    securities: dict[str, ListedSecurity] = {}

    for row in csv.DictReader(StringIO(nasdaq_text), delimiter="|"):
        raw_symbol = str(row.get("Symbol") or "")
        if raw_symbol.startswith("File Creation Time"):
            continue
        name = str(row.get("Security Name") or "").strip()
        symbol = _normalise_symbol(raw_symbol)
        if (
            symbol
            and row.get("Test Issue") == "N"
            and row.get("ETF") == "N"
            and row.get("NextShares", "N") != "Y"
            and row.get("Financial Status", "N") == "N"
            and _looks_like_stock(name)
        ):
            securities[symbol] = ListedSecurity(symbol, name, "NASDAQ")

    exchange_names = {
        "A": "NYSE American",
        "N": "NYSE",
        "P": "NYSE Arca",
        "V": "IEX",
        "Z": "Cboe BZX",
    }
    for row in csv.DictReader(StringIO(other_text), delimiter="|"):
        raw_symbol = str(row.get("ACT Symbol") or "")
        if raw_symbol.startswith("File Creation Time"):
            continue
        name = str(row.get("Security Name") or "").strip()
        symbol = _normalise_symbol(raw_symbol)
        exchange = exchange_names.get(str(row.get("Exchange") or ""), "US exchange")
        if (
            symbol
            and row.get("Test Issue") == "N"
            and row.get("ETF") == "N"
            and _looks_like_stock(name)
        ):
            securities[symbol] = ListedSecurity(symbol, name, exchange)

    return securities


class NasdaqSymbolDirectory:
    """Current US-listed stock universe with a local, stale-on-error cache."""

    def __init__(
        self,
        cache_path: Path = UNIVERSE_CACHE_PATH,
        *,
        max_age: timedelta = timedelta(hours=18),
    ) -> None:
        self.cache_path = Path(cache_path)
        self.max_age = max_age

    def listed_stocks(self, *, force_refresh: bool = False) -> dict[str, ListedSecurity]:
        if not force_refresh and self._cache_is_fresh():
            cached = self._read_cache()
            if cached:
                return cached

        try:
            nasdaq_text = self._download(NASDAQ_LISTED_URL)
            other_text = self._download(OTHER_LISTED_URL)
            securities = parse_symbol_directory(nasdaq_text, other_text)
            if len(securities) < 1_000:
                raise RuntimeError("The symbol directory returned an implausibly small universe.")
            self._write_cache(securities)
            return securities
        except Exception:
            cached = self._read_cache()
            if cached:
                return cached
            return {
                ticker: ListedSecurity(ticker, ticker, "US exchange") for ticker in DEFAULT_UNIVERSE
            }

    def _cache_is_fresh(self) -> bool:
        if not self.cache_path.exists():
            return False
        modified = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=UTC)
        return datetime.now(UTC) - modified <= self.max_age

    def _read_cache(self) -> dict[str, ListedSecurity]:
        if not self.cache_path.exists():
            return {}
        try:
            with self.cache_path.open(encoding="utf-8", newline="") as handle:
                rows = csv.DictReader(handle)
                return {
                    row["ticker"]: ListedSecurity(
                        ticker=row["ticker"],
                        name=row.get("name", ""),
                        exchange=row.get("exchange", ""),
                    )
                    for row in rows
                    if row.get("ticker")
                }
        except (OSError, csv.Error, KeyError):
            return {}

    def _write_cache(self, securities: dict[str, ListedSecurity]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("ticker", "name", "exchange"))
            writer.writeheader()
            for security in sorted(securities.values(), key=lambda item: item.ticker):
                writer.writerow(
                    {
                        "ticker": security.ticker,
                        "name": security.name,
                        "exchange": security.exchange,
                    }
                )
        temporary.replace(self.cache_path)

    @staticmethod
    def _download(url: str) -> str:
        request = Request(url, headers={"User-Agent": "PaperAlpha/0.2 educational research"})
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS URLs
            return response.read().decode("utf-8-sig")
