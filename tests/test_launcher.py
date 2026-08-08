from __future__ import annotations

import socket

from launcher import _available_port


def test_launcher_falls_back_when_preferred_port_is_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        busy_port = int(occupied.getsockname()[1])

        selected = _available_port(busy_port)

    assert selected != busy_port
    assert 0 < selected <= 65_535
