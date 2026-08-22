"""Pure helpers for building safe Nav2 patrol plans."""

from __future__ import annotations

import math


def add_return_home(
    waypoints: list[dict[str, float]],
    home: dict[str, float],
    *,
    enabled: bool = True,
    minimum_distance_m: float = 0.15,
) -> tuple[list[dict[str, float]], bool]:
    """Append the starting pose unless the route already ends at home."""
    route = [dict(waypoint) for waypoint in waypoints]
    if not enabled:
        return route, False
    home_waypoint = {
        "x": float(home["x"]),
        "y": float(home["y"]),
        "yaw": float(home.get("yaw", 0.0)),
    }
    if route:
        distance = math.hypot(
            route[-1]["x"] - home_waypoint["x"], route[-1]["y"] - home_waypoint["y"]
        )
        if distance < minimum_distance_m:
            return route, False
    route.append(home_waypoint)
    return route, True
