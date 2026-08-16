import math

import pytest

from modules.automotive.navigation import (
    compensated_capture_pan,
    pose_delta,
    pose_quality_error,
    pose_quality_warning,
    target_pose_error,
)


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


def test_pose_quality_warns_without_rejecting_limited_amcl_localization():
    pose = {"position_stddev_m": 0.18, "yaw_stddev_rad": math.radians(10)}

    assert pose_quality_error(pose) is None
    assert pose_quality_warning(pose) == "Précision AMCL limitée (±18 cm, ±10°)"
    assert pose_quality_error({"position_stddev_m": 0.08, "yaw_stddev_rad": 0.1}) is None


def test_pose_quality_rejects_localization_too_uncertain_for_repeatable_capture():
    error = pose_quality_error({"position_stddev_m": 1.2, "yaw_stddev_rad": math.radians(70)})

    assert error == (
        "Localisation AMCL insuffisante pour une inspection reproductible "
        "(±120 cm, ±70°). Relocalisez le rover avant d'enregistrer ou photographier ce point"
    )


def test_pose_delta_normalizes_yaw():
    distance, yaw_delta = pose_delta(
        {"x": 0.0, "y": 0.0, "yaw": math.radians(179)},
        {"x": 0.03, "y": 0.04, "yaw": math.radians(-179)},
    )

    assert distance == pytest.approx(0.05)
    assert math.degrees(yaw_delta) == pytest.approx(2.0)


def test_target_pose_error_measures_learned_position_and_normalizes_heading():
    distance, yaw_error = target_pose_error(
        {"x": 1.0, "y": 2.0, "yaw": math.radians(-175)},
        {"x": 0.91, "y": 2.12, "yaw": math.radians(175)},
    )

    assert distance == pytest.approx(0.15)
    assert math.degrees(yaw_error) == pytest.approx(10.0)
