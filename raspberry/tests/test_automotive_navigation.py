import math

import pytest

from modules.automotive.navigation import compensated_capture_pan


def test_capture_pan_compensates_robot_heading_with_opposite_pan_direction():
    pan, yaw_error = compensated_capture_pan(
        target_yaw=math.radians(90),
        current_yaw=math.radians(10),
        learned_pan=5.0,
        pan_range=(-90.0, 90.0),
    )

    assert math.degrees(yaw_error) == pytest.approx(80.0)
    assert pan == pytest.approx(-75.0)


def test_capture_pan_normalizes_heading_across_pi_boundary():
    pan, yaw_error = compensated_capture_pan(
        target_yaw=math.radians(-175),
        current_yaw=math.radians(175),
        learned_pan=0.0,
        pan_range=(-90.0, 90.0),
    )

    assert math.degrees(yaw_error) == pytest.approx(10.0)
    assert pan == pytest.approx(-10.0)


def test_capture_pan_rejects_unreachable_camera_angle():
    pan, yaw_error = compensated_capture_pan(
        target_yaw=math.radians(120),
        current_yaw=0.0,
        learned_pan=0.0,
        pan_range=(-90.0, 90.0),
    )

    assert math.degrees(yaw_error) == pytest.approx(120.0)
    assert pan is None
