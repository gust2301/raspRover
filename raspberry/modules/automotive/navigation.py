"""Navigation helpers for repeatable automotive inspection captures."""

from __future__ import annotations

import math

WARNING_POSITION_STDDEV_M = 0.12
WARNING_YAW_STDDEV_RAD = math.radians(8.0)
LOST_POSITION_STDDEV_M = 0.20
LOST_YAW_STDDEV_RAD = math.radians(15.0)
# Tolérances d'arrivée AMCL. Desserrées par rapport aux tolérances Nav2
# elles-mêmes (nav2_goal_xy_tolerance_m, nav2_goal_yaw_tolerance_rad) : les
# valeurs précédentes (5 cm / 3°) étaient plus strictes que ce que Nav2 vise,
# ce qui rejetait en boucle des arrivées que Nav2 considérait pourtant
# atteintes et déclenchait ses comportements de récupération (spin sur
# place) près d'un obstacle proche du point appris.
INSPECTION_POSITION_TOLERANCE_M = 0.08
INSPECTION_YAW_TOLERANCE_RAD = math.radians(6.0)
INSPECTION_STABLE_POSITION_DELTA_M = 0.025
INSPECTION_STABLE_YAW_DELTA_RAD = math.radians(3.0)

# Recalage visuel OAK-D avant capture (voir _align_to_vehicle dans server.py).
VEHICLE_ALIGN_TOLERANCE_RAD = math.radians(5.0)
VEHICLE_ALIGN_MAX_CORRECTION_RAD = math.radians(15.0)


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


def vehicle_bearing_rad(x_mm: float, z_mm: float) -> float:
    """Chassis-relative bearing to an OAK-D spatial detection.

    Same convention as the person-following bearing in FollowMeController:
    positive is to the right, since the OAK-D Lite is fixed to the chassis
    (not on the pan-tilt bracket) — rotating the chassis directly changes it.
    """
    return math.atan2(float(x_mm), float(z_mm))


def vehicle_alignment_needed(
    bearing_rad: float, *, tolerance_rad: float = VEHICLE_ALIGN_TOLERANCE_RAD
) -> bool:
    """True when the detected vehicle is far enough off-axis to warrant a nudge."""
    return abs(bearing_rad) > tolerance_rad


def vehicle_alignment_out_of_range(
    bearing_rad: float, *, limit_rad: float = VEHICLE_ALIGN_MAX_CORRECTION_RAD
) -> bool:
    """True when the bearing is too large to correct automatically in place."""
    return abs(bearing_rad) > limit_rad


def vehicle_alignment_turn_speed(bearing_rad: float, *, minimum: float, maximum: float) -> float:
    """Small proportional in-place turn command, mirroring FollowMeController."""
    return min(maximum, max(minimum, 0.10 + abs(float(bearing_rad)) * 0.18))
