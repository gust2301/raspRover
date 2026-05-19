"""Stable LIDAR obstacle-avoidance decisions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from modules.sensors.lidar import LidarSnapshot, _angle_delta

log = logging.getLogger(__name__)


class AvoidanceAction(str, Enum):
    CLEAR = "clear"
    ARC_LEFT = "arc_left"
    ARC_RIGHT = "arc_right"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    STOP = "stop"


@dataclass(frozen=True)
class AvoidanceDecision:
    action: AvoidanceAction
    reason: str
    front_cm: float | None = None
    target_angle_deg: float = 0.0
    confidence: float = 0.0


class LidarAvoidancePlanner:
    """Chooses smooth, hysteresis-based avoidance actions from a LIDAR scan."""

    def __init__(
        self,
        caution_cm: float = 90.0,
        danger_cm: float = 45.0,
        clear_cm: float = 115.0,
        front_fov_deg: float = 55.0,
        hold_s: float = 1.2,
        switch_margin_cm: float = 35.0,
    ) -> None:
        self.caution_cm = float(caution_cm)
        self.danger_cm = float(danger_cm)
        self.clear_cm = float(clear_cm)
        self.front_fov_deg = float(front_fov_deg)
        self.hold_s = float(hold_s)
        self.switch_margin_cm = float(switch_margin_cm)
        self._last_action = AvoidanceAction.CLEAR
        self._last_turn_sign = 0
        self._last_change_ts = 0.0

    def decide(self, snapshot: LidarSnapshot) -> AvoidanceDecision:
        if not snapshot.connected:
            return AvoidanceDecision(AvoidanceAction.STOP, snapshot.error or "lidar indisponible")
        if not snapshot.points:
            return AvoidanceDecision(AvoidanceAction.STOP, "scan lidar vide")

        front = self._sector_min(snapshot, 0.0, self.front_fov_deg)
        left = self._sector_score(snapshot, -70.0, 80.0)
        right = self._sector_score(snapshot, 70.0, 80.0)
        now = time.monotonic()

        if front is None or front >= self.clear_cm:
            decision = AvoidanceDecision(AvoidanceAction.CLEAR, "avant degage", front)
        else:
            preferred_sign = -1 if left >= right else 1
            score_gap = abs(left - right)
            held_sign = self._last_turn_sign
            if held_sign and now - self._last_change_ts < self.hold_s:
                held_score = left if held_sign < 0 else right
                preferred_score = left if preferred_sign < 0 else right
                if preferred_score - held_score < self.switch_margin_cm:
                    preferred_sign = held_sign

            target_angle = -45.0 if preferred_sign < 0 else 45.0
            side_label = "gauche" if preferred_sign < 0 else "droite"

            if front <= self.danger_cm:
                action = AvoidanceAction.TURN_LEFT if preferred_sign < 0 else AvoidanceAction.TURN_RIGHT
                reason = f"obstacle frontal reel {front:.0f}cm, rotation vers zone libre {side_label}"
            else:
                action = AvoidanceAction.ARC_LEFT if preferred_sign < 0 else AvoidanceAction.ARC_RIGHT
                reason = f"obstacle leger {front:.0f}cm, correction vers {side_label}"

            decision = AvoidanceDecision(
                action=action,
                reason=f"{reason} (G={left:.0f}cm D={right:.0f}cm ecart={score_gap:.0f})",
                front_cm=front,
                target_angle_deg=target_angle,
                confidence=min(1.0, max(0.0, (self.clear_cm - front) / self.clear_cm)),
            )

        self._remember(decision, now)
        return decision

    def _remember(self, decision: AvoidanceDecision, now: float) -> None:
        if decision.action == self._last_action:
            return
        self._last_action = decision.action
        self._last_change_ts = now
        if decision.action in (AvoidanceAction.ARC_LEFT, AvoidanceAction.TURN_LEFT):
            self._last_turn_sign = -1
        elif decision.action in (AvoidanceAction.ARC_RIGHT, AvoidanceAction.TURN_RIGHT):
            self._last_turn_sign = 1
        log.info("LIDAR avoidance: %s - %s", decision.action.value, decision.reason)

    def _sector_min(self, snapshot: LidarSnapshot, center: float, width: float) -> float | None:
        distances = [
            p.distance_mm / 10.0
            for p in snapshot.points
            if abs(_angle_delta(p.angle_deg, center)) <= width / 2.0
        ]
        return min(distances) if distances else None

    def _sector_score(self, snapshot: LidarSnapshot, center: float, width: float) -> float:
        distances = [
            min(p.distance_mm / 10.0, self.clear_cm * 2.0)
            for p in snapshot.points
            if abs(_angle_delta(p.angle_deg, center)) <= width / 2.0
        ]
        if not distances:
            return 0.0
        distances.sort()
        sample = distances[: max(1, len(distances) // 4)]
        return sum(sample) / len(sample)

