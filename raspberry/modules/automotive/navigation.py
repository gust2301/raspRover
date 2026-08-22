"""Navigation helpers for repeatable automotive inspection captures."""

from __future__ import annotations

import math

WARNING_POSITION_STDDEV_M = 0.12
WARNING_YAW_STDDEV_RAD = math.radians(8.0)
LOST_POSITION_STDDEV_M = 0.20
LOST_YAW_STDDEV_RAD = math.radians(15.0)
INSPECTION_POSITION_TOLERANCE_M = 0.05
INSPECTION_YAW_TOLERANCE_RAD = math.radians(3.0)
INSPECTION_STABLE_POSITION_DELTA_M = 0.025
INSPECTION_STABLE_YAW_DELTA_RAD = math.radians(3.0)


def compensated_capture_pan(
    *,
    target_yaw: float,
    current_yaw: float,
    learned_pan: float,
    pan_range: tuple[float, float],
) -> tuple[float | None, float]:
    """Return a camera pan preserving the learned world-facing capture angle.

    ROS yaw is positive to the left while the rover pan controller is positive
    to the right, hence the subtraction. ``None`` means that the pan axis cannot
    compensate the remaining robot heading error without exceeding its limits.
    """
    yaw_error = math.atan2(
        math.sin(float(target_yaw) - float(current_yaw)),
        math.cos(float(target_yaw) - float(current_yaw)),
    )
    capture_pan = float(learned_pan) - math.degrees(yaw_error)
    pan_min, pan_max = pan_range
    if capture_pan < pan_min or capture_pan > pan_max:
        return None, yaw_error
    return capture_pan, yaw_error


def pose_quality_error(pose: dict) -> str | None:
    """Refuse a capture whose map pose cannot reproduce the learned viewpoint."""
    try:
        position_stddev = float(pose["position_stddev_m"])
        yaw_stddev = float(pose["yaw_stddev_rad"])
    except (KeyError, TypeError, ValueError):
        return "Qualité de localisation AMCL indisponible"
    if not math.isfinite(position_stddev) or not math.isfinite(yaw_stddev):
        return "Qualité de localisation AMCL invalide"
    if position_stddev > LOST_POSITION_STDDEV_M or yaw_stddev > LOST_YAW_STDDEV_RAD:
        return (
            "Localisation AMCL insuffisante pour une inspection reproductible "
            f"(±{position_stddev * 100:.0f} cm, ±{math.degrees(yaw_stddev):.0f}°). "
            "Relocalisez le rover avant d'enregistrer ou photographier ce point"
        )
    return None


def pose_quality_warning(pose: dict) -> str | None:
    """Describe limited AMCL precision without blocking a stable capture."""
    try:
        position_stddev = float(pose["position_stddev_m"])
        yaw_stddev = float(pose["yaw_stddev_rad"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(position_stddev) or not math.isfinite(yaw_stddev):
        return None
    if position_stddev > WARNING_POSITION_STDDEV_M or yaw_stddev > WARNING_YAW_STDDEV_RAD:
        return (
            "Estimation AMCL indicative "
            f"(±{position_stddev * 100:.0f} cm, ±{math.degrees(yaw_stddev):.0f}°)"
        )
    return None


def pose_delta(first: dict, second: dict) -> tuple[float, float]:
    """Return translation and normalized heading changes between two poses."""
    distance = math.hypot(
        float(second["x"]) - float(first["x"]), float(second["y"]) - float(first["y"])
    )
    yaw_delta = math.atan2(
        math.sin(float(second["yaw"]) - float(first["yaw"])),
        math.cos(float(second["yaw"]) - float(first["yaw"])),
    )
    return distance, abs(yaw_delta)


def target_pose_error(target: dict, pose: dict) -> tuple[float, float]:
    """Return the rover translation and heading error from a learned point."""
    distance = math.hypot(
        float(target["x"]) - float(pose["x"]),
        float(target["y"]) - float(pose["y"]),
    )
    yaw_error = math.atan2(
        math.sin(float(target.get("yaw", 0.0)) - float(pose.get("yaw", 0.0))),
        math.cos(float(target.get("yaw", 0.0)) - float(pose.get("yaw", 0.0))),
    )
    return distance, yaw_error
