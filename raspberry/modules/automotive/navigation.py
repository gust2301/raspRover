"""Navigation helpers for repeatable automotive inspection captures."""

from __future__ import annotations

import math


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
