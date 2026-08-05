from __future__ import annotations

import json
import socket

import pytest

from modules.control.odometry import OdometryCommandPublisher


def test_odometry_command_publisher_sends_compact_udp_payload():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    publisher = OdometryCommandPublisher(port=receiver.getsockname()[1])
    try:
        publisher.publish(0.25, -0.5)
        raw, _ = receiver.recvfrom(2048)
    finally:
        publisher.close()
        receiver.close()

    payload = json.loads(raw)
    assert payload["left"] == pytest.approx(0.25)
    assert payload["right"] == pytest.approx(-0.5)
    assert isinstance(payload["timestamp"], float)
