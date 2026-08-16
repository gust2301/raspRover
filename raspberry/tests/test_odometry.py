from __future__ import annotations

import json
import math
import socket

import pytest

from modules.control.encoder_kinematics import EncoderIntegrator, WheelSample
from modules.control.odometry import EncoderFeedbackPublisher


class FeedbackLink:
    def request_feedback(self, **_kwargs) -> dict:
        return {"T": 1001, "L": 0.25, "R": -0.5, "odl": 12, "odr": -7}


def sample(
    sequence: int,
    timestamp: float,
    left_speed: float,
    right_speed: float,
    left_distance: float,
    right_distance: float,
) -> WheelSample:
    return WheelSample(
        left_speed,
        right_speed,
        left_distance,
        right_distance,
        timestamp,
        sequence,
    )


def test_encoder_feedback_publisher_sends_measured_udp_payload():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    publisher = EncoderFeedbackPublisher(
        FeedbackLink(),
        port=receiver.getsockname()[1],
        frequency_hz=20.0,  # type: ignore[arg-type]
    )
    try:
        raw, _ = receiver.recvfrom(2048)
    finally:
        publisher.close()
        receiver.close()

    payload = json.loads(raw)
    assert payload["left_speed_m_s"] == pytest.approx(0.25)
    assert payload["right_speed_m_s"] == pytest.approx(-0.5)
    assert payload["left_distance_cm"] == pytest.approx(12)
    assert payload["right_distance_cm"] == pytest.approx(-7)
    assert payload["sequence"] >= 1


def test_encoder_integrator_tracks_straight_physical_motion():
    odometry = EncoderIntegrator(0.172)
    odometry.update(sample(1, 10.0, 0.2, 0.2, 1.0, 1.0))
    for index in range(1, 11):
        distance = 1.0 + 0.02 * index
        odometry.update(sample(index + 1, 10.0 + index * 0.1, 0.2, 0.2, distance, distance))

    assert odometry.x == pytest.approx(0.2, abs=0.015)
    assert odometry.y == pytest.approx(0.0, abs=0.002)
    assert odometry.yaw == pytest.approx(0.0, abs=0.002)


def test_encoder_integrator_tracks_measured_rotation_not_motor_commands():
    odometry = EncoderIntegrator(0.172)
    odometry.update(sample(1, 1.0, -0.1, 0.1, 0.0, 0.0))
    for index in range(1, 11):
        odometry.update(
            sample(
                index + 1,
                1.0 + index * 0.1,
                -0.1,
                0.1,
                -0.01 * index,
                0.01 * index,
            )
        )

    assert odometry.x == pytest.approx(0.0, abs=0.01)
    assert odometry.y == pytest.approx(0.0, abs=0.01)
    assert odometry.yaw == pytest.approx(0.2 / 0.172, abs=math.radians(6))


def test_encoder_integrator_rejects_firmware_counter_reset():
    odometry = EncoderIntegrator(0.172)
    odometry.update(sample(1, 1.0, 0.0, 0.0, 4.0, 4.0))
    assert not odometry.update(sample(2, 1.1, 0.0, 0.0, 0.0, 0.0))
    assert odometry.x == 0.0
