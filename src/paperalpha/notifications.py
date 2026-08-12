from __future__ import annotations

import argparse
import json
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from paperalpha.config import NOTIFICATION_CONFIG_PATH, initialize_runtime_files


class NotificationError(RuntimeError):
    """Raised when a notification cannot be delivered."""


@dataclass(frozen=True)
class NtfyConfig:
    server_url: str
    topic: str
    token: str = ""

    @property
    def topic_url(self) -> str:
        return f"{self.server_url.rstrip('/')}/{quote(self.topic, safe='-_')}"


def create_notification_config(
    path: str | Path = NOTIFICATION_CONFIG_PATH,
    *,
    server_url: str = "https://ntfy.sh",
    topic: str | None = None,
    token: str = "",
) -> NtfyConfig:
    config = NtfyConfig(
        server_url=server_url.rstrip("/"),
        topic=topic or f"paperalpha-{secrets.token_urlsafe(24)}",
        token=token,
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    return config


def load_notification_config(
    path: str | Path = NOTIFICATION_CONFIG_PATH,
) -> NtfyConfig:
    target = Path(path)
    if not target.exists():
        raise NotificationError(
            f"Notification configuration was not found at {target}. "
            "Run 'paperalpha-notify setup' first."
        )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return NtfyConfig(
            server_url=str(payload["server_url"]).rstrip("/"),
            topic=str(payload["topic"]),
            token=str(payload.get("token") or ""),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NotificationError(f"Invalid notification configuration: {exc}") from exc


class NtfyNotifier:
    def __init__(self, config: NtfyConfig) -> None:
        self.config = config

    def send(
        self,
        title: str,
        message: str,
        *,
        priority: str = "default",
        tags: tuple[str, ...] = (),
        click_url: str = "",
    ) -> None:
        headers = {
            "Title": title,
            "Priority": priority,
            "Tags": ",".join(tags),
            "Content-Type": "text/plain; charset=utf-8",
        }
        if click_url:
            headers["Click"] = click_url
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        request = Request(
            self.config.topic_url,
            data=message.encode("utf-8"),
            headers={key: value for key, value in headers.items() if value},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=15) as response:  # noqa: S310 - configured endpoint
                    if response.status >= 300:
                        raise NotificationError(
                            f"Notification server returned HTTP {response.status}."
                        )
                    return
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise NotificationError(f"Notification delivery failed after 3 attempts: {last_error}")


class ConsoleNotifier:
    def send(
        self,
        title: str,
        message: str,
        *,
        priority: str = "default",
        tags: tuple[str, ...] = (),
        click_url: str = "",
    ) -> None:
        del priority, tags, click_url
        print(f"{title}: {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure PaperAlpha iPhone notifications.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("setup", help="Create a private ntfy topic configuration.")
    setup.add_argument("--server", default="https://ntfy.sh", help="ntfy server URL.")
    setup.add_argument("--topic", default=None, help="Topic name; omit to generate a secret one.")
    setup.add_argument("--token", default="", help="Optional access token for a private server.")
    setup.add_argument("--config", default=str(NOTIFICATION_CONFIG_PATH))
    test = subparsers.add_parser("test", help="Send a test notification.")
    test.add_argument("--config", default=str(NOTIFICATION_CONFIG_PATH))
    args = parser.parse_args()
    initialize_runtime_files()

    if args.command == "setup":
        config = create_notification_config(
            args.config,
            server_url=args.server,
            topic=args.topic,
            token=args.token,
        )
        print("Notification configuration created.")
        print(f"Server: {config.server_url}")
        print(f"Topic:  {config.topic}")
        print("Treat the topic like a password; do not post it publicly.")
        print("Install ntfy on the iPhone, add this server, and subscribe to this exact topic.")
        return

    notifier = NtfyNotifier(load_notification_config(args.config))
    notifier.send(
        "PaperAlpha test",
        "Notifications are connected. Alerts are simulated paper trades only.",
        priority="high",
        tags=("white_check_mark", "chart_with_upwards_trend"),
    )
    print("Test notification sent.")


if __name__ == "__main__":
    main()
