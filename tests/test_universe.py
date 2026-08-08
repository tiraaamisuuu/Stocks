from __future__ import annotations

from datetime import timedelta

from paperalpha.domain import ListedSecurity
from paperalpha.universe import NasdaqSymbolDirectory, parse_symbol_directory

NASDAQ_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
GOOD|Good Corp Common Stock|Q|N|N|100|N|N
FUND|Index Tracker ETF|G|N|N|100|Y|N
TEST|Test Security|Q|Y|N|100|N|N
WARRW|Example Corp Warrant|S|N|N|100|N|N
File Creation Time: 0808202618:00|||||||
"""

OTHER_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Common Stock|N|BRK.B|N|100|N|BRK.B
PREF|Example Depositary Shares representing Preferred Stock|N|PREF|N|100|N|PREF
File Creation Time: 0808202618:00|||||||
"""


def test_symbol_directory_keeps_stocks_and_normalises_share_classes() -> None:
    securities = parse_symbol_directory(NASDAQ_SAMPLE, OTHER_SAMPLE)

    assert set(securities) == {"GOOD", "BRK-B"}
    assert securities["BRK-B"].exchange == "NYSE"


def test_symbol_directory_uses_its_cache(tmp_path, monkeypatch) -> None:
    directory = NasdaqSymbolDirectory(tmp_path / "universe.csv", max_age=timedelta(days=1))
    responses = iter((NASDAQ_SAMPLE * 300, OTHER_SAMPLE * 300))
    monkeypatch.setattr(directory, "_download", lambda _url: next(responses))

    # Repeated samples still collapse by ticker, so lower the plausibility guard for this unit test.
    monkeypatch.setattr(
        "paperalpha.universe.parse_symbol_directory",
        lambda _nasdaq, _other: {
            f"T{index}": ListedSecurity(f"T{index}", f"Stock {index}", "NASDAQ")
            for index in range(1_001)
        },
    )
    first = directory.listed_stocks()
    monkeypatch.setattr(directory, "_download", lambda _url: (_ for _ in ()).throw(OSError()))
    second = directory.listed_stocks()

    assert len(first) == 1_001
    assert set(second) == set(first)
