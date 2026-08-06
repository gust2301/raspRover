from __future__ import annotations

from modules.control.lidar_avoidance import AvoidanceAction, AvoidanceDecision
from modules.control.patrol import PatrolController


def _decision(action: AvoidanceAction) -> AvoidanceDecision:
    return AvoidanceDecision(action=action, reason="test")


def _controller() -> PatrolController:
    return PatrolController(motors=None, navigation_mode="LIDAR_ONLY")


def test_back_up_is_committed_then_forces_a_side_turn():
    patrol = _controller()

    first = patrol._guard_lidar_decision(_decision(AvoidanceAction.BACK_UP), 10.0)
    premature_clear = patrol._guard_lidar_decision(_decision(AvoidanceAction.CLEAR), 10.2)
    escape = patrol._guard_lidar_decision(_decision(AvoidanceAction.CLEAR), 10.7)
    committed_turn = patrol._guard_lidar_decision(_decision(AvoidanceAction.CLEAR), 11.0)

    assert first.action == AvoidanceAction.BACK_UP
    assert premature_clear.action == AvoidanceAction.BACK_UP
    assert escape.action in (AvoidanceAction.TURN_LEFT, AvoidanceAction.TURN_RIGHT)
    assert committed_turn.action == escape.action


def test_continuous_turn_is_stopped_for_reevaluation():
    patrol = _controller()
    turn = _decision(AvoidanceAction.TURN_LEFT)

    assert patrol._guard_lidar_decision(turn, 20.0).action == AvoidanceAction.TURN_LEFT
    assert patrol._guard_lidar_decision(turn, 21.0).action == AvoidanceAction.TURN_LEFT
    stopped = patrol._guard_lidar_decision(turn, 21.5)

    assert stopped.action == AvoidanceAction.STOP
    assert "rotation maximale" in stopped.reason


def test_scan_rotation_uses_pulses_and_alternates_direction():
    patrol = _controller()
    scan = _decision(AvoidanceAction.SCAN_ROTATE)

    first = patrol._guard_lidar_decision(scan, 30.0)
    pause = patrol._guard_lidar_decision(scan, 30.6)
    second = patrol._guard_lidar_decision(scan, 31.0)

    assert first.action in (AvoidanceAction.TURN_LEFT, AvoidanceAction.TURN_RIGHT)
    assert pause.action == AvoidanceAction.STOP
    assert second.action in (AvoidanceAction.TURN_LEFT, AvoidanceAction.TURN_RIGHT)
    assert second.action != first.action
