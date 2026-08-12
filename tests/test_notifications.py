from __future__ import annotations

import json

import pytest

from paperalpha.notifications import (
    NotificationError,
    NtfyConfig,
    NtfyNotifier,
    create_notification_config,
    load_notification_config,
)


def test_notification_config_generates_private_topic_and_round_trips(tmp_path) -> None:
    path = tmp_path / "notifications.json"
    created = create_notification_config(path)
    loaded = load_notification_config(path)

    assert created == loaded
    assert created.topic.startswith("paperalpha-")
    assert len(created.topic) > 30
    assert created.topic not in path.read_text(encoding="utf-8").splitlines()[0]


def test_invalid_notification_config_is_rejected(tmp_path) -> None:
    path = tmp_path / "notifications.json"
    path.write_text(json.dumps({"topic": "missing-server"}), encoding="utf-8")

    with pytest.raises(NotificationError, match="Invalid notification configuration"):
        load_notification_config(path)


def test_ntfy_notifier_posts_utf8_message(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("paperalpha.notifications.urlopen", fake_urlopen)
    notifier = NtfyNotifier(NtfyConfig("https://ntfy.example", "secret-topic", "token"))
    notifier.send(
        "PAPER BUY · TEST",
        "Simulated £10 message",
        priority="high",
        tags=("chart",),
        click_url="https://dashboard.example",
    )

    request = captured["request"]
    assert request.full_url == "https://ntfy.example/secret-topic"
    assert request.data.decode("utf-8") == "Simulated £10 message"
    assert request.headers["Priority"] == "high"
    assert request.headers["Authorization"] == "Bearer token"
    assert captured["timeout"] == 15
