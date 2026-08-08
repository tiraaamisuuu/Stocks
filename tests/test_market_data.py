from __future__ import annotations

from paperalpha.market_data import _parse_news_record


def test_news_parser_keeps_only_articles_related_to_ticker() -> None:
    relevant = {
        "title": "Example Corp raises guidance",
        "publisher": "Newswire",
        "link": "https://example.test/story",
        "providerPublishTime": 1_767_268_800,
        "relatedTickers": ["ABC", "SPY"],
    }
    unrelated = {**relevant, "relatedTickers": ["XYZ"]}

    parsed = _parse_news_record(relevant, "ABC")

    assert parsed is not None
    assert parsed.publisher == "Newswire"
    assert parsed.url == "https://example.test/story"
    assert _parse_news_record(unrelated, "ABC") is None
