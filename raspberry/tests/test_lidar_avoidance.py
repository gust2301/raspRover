from __future__ import annotations

from modules.control.lidar_avoidance import (
    AvoidanceAction,
    AvoidanceDecision,
    LidarAvoidancePlanner,
    ZoneDanger,
    ZoneStats,
)


def _clear_zones() -> dict[str, ZoneStats]:
    return {
        name: ZoneStats(name, 150.0, 180.0, 8, ZoneDanger.CLEAR)
        for name in (
            "front",
            "front_right",
            "right",
            "rear_right",
            "rear",
            "rear_left",
            "left",
            "front_left",
        )
    }


def test_clear_front_interrupts_turn_hysteresis(monkeypatch):
    planner = LidarAvoidancePlanner(min_decision_duration_ms=1200)
    zones = _clear_zones()
    planner._last_action = AvoidanceAction.TURN_LEFT
    planner._last_change_ts = 10.0
    decision = AvoidanceDecision(AvoidanceAction.CLEAR, "avant libre", zones=zones)
    monkeypatch.setattr("modules.control.lidar_avoidance.time.monotonic", lambda: 10.2)

    stabilized = planner._stabilize(decision, zones)

    assert stabilized.action == AvoidanceAction.CLEAR
