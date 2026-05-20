"""Stable 360-degree LIDAR patrol decisions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from modules.sensors.lidar import LidarSnapshot, _angle_delta

log = logging.getLogger(__name__)


class AvoidanceAction(str, Enum):
    CLEAR = "clear"
    SLOW_FORWARD = "slow_forward"
    ARC_LEFT = "arc_left"
    ARC_RIGHT = "arc_right"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    BACK_UP = "back_up"
    SCAN_ROTATE = "scan_rotate"
    STOP = "stop"


class ZoneDanger(str, Enum):
    UNKNOWN = "unknown"
    CLEAR = "clear"
    WARNING = "warning"
    DANGER = "danger"


@dataclass(frozen=True)
class ZoneSpec:
    name: str
    center_deg: float
    width_deg: float


@dataclass(frozen=True)
class ZoneStats:
    name: str
    min_cm: float | None
    avg_cm: float | None
    points: int
    danger: ZoneDanger

    @property
    def score(self) -> float:
        if self.points <= 0 or self.min_cm is None or self.avg_cm is None:
            return 0.0
        return min(self.avg_cm, 300.0) * 0.65 + min(self.min_cm, 300.0) * 0.35

    @property
    def safe(self) -> bool:
        return self.danger == ZoneDanger.CLEAR

    @property
    def blocked(self) -> bool:
        return self.danger in (ZoneDanger.DANGER, ZoneDanger.UNKNOWN)


@dataclass(frozen=True)
class AvoidanceDecision:
    action: AvoidanceAction
    reason: str
    front_cm: float | None = None
    target_angle_deg: float = 0.0
    confidence: float = 0.0
    zones: dict[str, ZoneStats] | None = None


_ZONE_SPECS: tuple[ZoneSpec, ...] = (
    ZoneSpec("front", 0.0, 60.0),
    ZoneSpec("front_right", 45.0, 50.0),
    ZoneSpec("right", 90.0, 60.0),
    ZoneSpec("rear_right", 135.0, 50.0),
    ZoneSpec("rear", 180.0, 70.0),
    ZoneSpec("rear_left", 225.0, 50.0),
    ZoneSpec("left", 270.0, 60.0),
    ZoneSpec("front_left", 315.0, 50.0),
)


class LidarAvoidancePlanner:
    """Chooses stable patrol actions from a corrected 360-degree LIDAR scan."""

    def __init__(
        self,
        stop_cm: float = 32.0,
        warning_cm: float = 65.0,
        safe_cm: float = 110.0,
        turn_clearance_cm: float = 55.0,
        rear_clearance_cm: float = 50.0,
        min_decision_duration_ms: int = 1200,
        scan_zone_min_points: int = 2,
        switch_margin_cm: float = 25.0,
        **_: float,
    ) -> None:
        self.stop_cm = float(stop_cm)
        self.warning_cm = float(warning_cm)
        self.safe_cm = float(safe_cm)
        self.turn_clearance_cm = float(turn_clearance_cm)
        self.rear_clearance_cm = float(rear_clearance_cm)
        self.min_decision_duration_s = max(0.0, float(min_decision_duration_ms) / 1000.0)
        self.scan_zone_min_points = int(scan_zone_min_points)
        self.switch_margin_cm = float(switch_margin_cm)
        self._last_action = AvoidanceAction.STOP
        self._last_turn_action: AvoidanceAction | None = None
        self._last_change_ts = 0.0

    def decide(self, snapshot: LidarSnapshot) -> AvoidanceDecision:
        if not snapshot.connected:
            return AvoidanceDecision(AvoidanceAction.STOP, snapshot.error or "lidar indisponible")
        if not snapshot.points:
            return AvoidanceDecision(AvoidanceAction.STOP, "scan lidar vide")

        zones = self.scan_zones(snapshot)
        raw_decision = self._decide_from_zones(zones)
        decision = self._stabilize(raw_decision, zones)
        self._remember(decision)
        self._log_decision(decision, zones)
        return decision

    def scan_zones(self, snapshot: LidarSnapshot) -> dict[str, ZoneStats]:
        return {spec.name: self._zone_stats(snapshot, spec) for spec in _ZONE_SPECS}

    def _decide_from_zones(self, zones: dict[str, ZoneStats]) -> AvoidanceDecision:
        front = zones["front"]
        front_left = zones["front_left"]
        front_right = zones["front_right"]
        left = zones["left"]
        right = zones["right"]
        rear = zones["rear"]
        rear_left = zones["rear_left"]
        rear_right = zones["rear_right"]

        if front.min_cm is not None and front.min_cm <= self.stop_cm:
            return AvoidanceDecision(
                AvoidanceAction.STOP,
                f"danger frontal immediat {front.min_cm:.0f}cm",
                front.min_cm,
                zones=zones,
                confidence=1.0,
            )

        if self._last_action in (
            AvoidanceAction.TURN_LEFT,
            AvoidanceAction.TURN_RIGHT,
            AvoidanceAction.ARC_LEFT,
            AvoidanceAction.ARC_RIGHT,
        ) and self._turn_side_too_close(left, right):
            side = "gauche" if left.min_cm and left.min_cm <= self.stop_cm else "droite"
            cm = left.min_cm if side == "gauche" else right.min_cm
            return AvoidanceDecision(
                AvoidanceAction.STOP,
                f"danger lateral {side} {cm:.0f}cm",
                front.min_cm,
                zones=zones,
                confidence=1.0,
            )

        if (
            front.safe
            and front_left.danger != ZoneDanger.DANGER
            and front_right.danger != ZoneDanger.DANGER
        ):
            return AvoidanceDecision(
                AvoidanceAction.CLEAR,
                f"avant libre {self._fmt_zone(front)}",
                front.min_cm,
                zones=zones,
                confidence=0.15,
            )

        if front.danger == ZoneDanger.WARNING and front_left.safe and front_right.safe:
            target = self._choose_turn_side(zones, allow_current=True)
            action = AvoidanceAction.ARC_LEFT if target == "left" else AvoidanceAction.ARC_RIGHT
            return AvoidanceDecision(
                action,
                f"obstacle moyen devant {self._fmt_zone(front)}, arc vers {target}",
                front.min_cm,
                -35.0 if target == "left" else 35.0,
                zones=zones,
                confidence=0.45,
            )

        left_clear = self._turn_clear("left", zones)
        right_clear = self._turn_clear("right", zones)

        if left.blocked and right_clear:
            return self._turn_decision("right", zones, "gauche occupee")
        if right.blocked and left_clear:
            return self._turn_decision("left", zones, "droite occupee")
        if left_clear or right_clear:
            target = self._choose_turn_side(zones)
            if target == "left" and left_clear:
                return self._turn_decision("left", zones, "avant bloque")
            if target == "right" and right_clear:
                return self._turn_decision("right", zones, "avant bloque")

        rear_open = self._corridor_clear((rear, rear_left, rear_right), self.rear_clearance_cm)
        if rear_open:
            return AvoidanceDecision(
                AvoidanceAction.BACK_UP,
                f"avant et cotes bloques, recul possible {self._fmt_zone(rear)}",
                front.min_cm,
                180.0,
                zones=zones,
                confidence=0.75,
            )

        return AvoidanceDecision(
            AvoidanceAction.SCAN_ROTATE,
            "toutes zones bloquees, rotation lente de scan",
            front.min_cm,
            zones=zones,
            confidence=1.0,
        )

    def _stabilize(
        self,
        decision: AvoidanceDecision,
        zones: dict[str, ZoneStats],
    ) -> AvoidanceDecision:
        now = time.monotonic()
        if now - self._last_change_ts >= self.min_decision_duration_s:
            return decision
        if decision.action == AvoidanceAction.STOP:
            return decision
        if self._last_action == decision.action:
            return decision
        if self._last_action in (
            AvoidanceAction.TURN_LEFT,
            AvoidanceAction.TURN_RIGHT,
            AvoidanceAction.ARC_LEFT,
            AvoidanceAction.ARC_RIGHT,
        ) and self._action_still_safe(self._last_action, zones):
            return AvoidanceDecision(
                self._last_action,
                f"maintien anti-oscillation ({decision.reason})",
                decision.front_cm,
                -35.0 if "LEFT" in self._last_action.name else 35.0,
                decision.confidence,
                zones,
            )
        return decision

    def _remember(self, decision: AvoidanceDecision) -> None:
        if decision.action == self._last_action:
            return
        self._last_action = decision.action
        self._last_change_ts = time.monotonic()
        if decision.action in (
            AvoidanceAction.TURN_LEFT,
            AvoidanceAction.TURN_RIGHT,
            AvoidanceAction.ARC_LEFT,
            AvoidanceAction.ARC_RIGHT,
        ):
            self._last_turn_action = decision.action

    def _zone_stats(self, snapshot: LidarSnapshot, spec: ZoneSpec) -> ZoneStats:
        distances = [
            p.distance_mm / 10.0
            for p in snapshot.points
            if abs(_angle_delta(p.angle_deg, spec.center_deg)) <= spec.width_deg / 2.0
        ]
        if len(distances) < self.scan_zone_min_points:
            return ZoneStats(spec.name, None, None, len(distances), ZoneDanger.UNKNOWN)
        min_cm = min(distances)
        avg_cm = sum(distances) / len(distances)
        if min_cm <= self.stop_cm:
            danger = ZoneDanger.DANGER
        elif min_cm <= self.warning_cm or avg_cm <= self.warning_cm:
            danger = ZoneDanger.WARNING
        else:
            danger = ZoneDanger.CLEAR
        return ZoneStats(spec.name, min_cm, avg_cm, len(distances), danger)

    def _turn_clear(self, side: str, zones: dict[str, ZoneStats]) -> bool:
        if side == "left":
            return self._corridor_clear(
                (zones["front_left"], zones["left"]), self.turn_clearance_cm
            )
        return self._corridor_clear((zones["front_right"], zones["right"]), self.turn_clearance_cm)

    def _corridor_clear(self, stats: tuple[ZoneStats, ...], clearance_cm: float) -> bool:
        for stat in stats:
            if stat.points < self.scan_zone_min_points or stat.min_cm is None:
                return False
            if stat.min_cm < clearance_cm:
                return False
        return True

    def _choose_turn_side(self, zones: dict[str, ZoneStats], allow_current: bool = False) -> str:
        left_score = zones["front_left"].score + zones["left"].score
        right_score = zones["front_right"].score + zones["right"].score
        if allow_current and self._last_turn_action:
            current_side = "left" if "LEFT" in self._last_turn_action.name else "right"
            current_score = left_score if current_side == "left" else right_score
            other_score = right_score if current_side == "left" else left_score
            if other_score - current_score < self.switch_margin_cm:
                return current_side
        return "left" if left_score >= right_score else "right"

    def _turn_decision(
        self,
        side: str,
        zones: dict[str, ZoneStats],
        reason: str,
    ) -> AvoidanceDecision:
        if side == "left":
            action = AvoidanceAction.TURN_LEFT
            target_angle = -55.0
            detail = f"G={self._fmt_zone(zones['left'])} AV-G={self._fmt_zone(zones['front_left'])}"
        else:
            action = AvoidanceAction.TURN_RIGHT
            target_angle = 55.0
            detail = (
                f"D={self._fmt_zone(zones['right'])} AV-D={self._fmt_zone(zones['front_right'])}"
            )
        return AvoidanceDecision(
            action,
            f"{reason}, rotation {side} ({detail})",
            zones["front"].min_cm,
            target_angle,
            0.65,
            zones,
        )

    def _action_still_safe(self, action: AvoidanceAction, zones: dict[str, ZoneStats]) -> bool:
        if action in (AvoidanceAction.TURN_LEFT, AvoidanceAction.ARC_LEFT):
            return self._turn_clear("left", zones)
        if action in (AvoidanceAction.TURN_RIGHT, AvoidanceAction.ARC_RIGHT):
            return self._turn_clear("right", zones)
        if action == AvoidanceAction.CLEAR:
            return zones["front"].safe
        if action == AvoidanceAction.BACK_UP:
            return self._corridor_clear(
                (zones["rear"], zones["rear_left"], zones["rear_right"]),
                self.rear_clearance_cm,
            )
        return False

    def _turn_side_too_close(self, left: ZoneStats, right: ZoneStats) -> bool:
        return (left.min_cm is not None and left.min_cm <= self.stop_cm) or (
            right.min_cm is not None and right.min_cm <= self.stop_cm
        )

    def _fmt_zone(self, stat: ZoneStats) -> str:
        if stat.min_cm is None or stat.avg_cm is None:
            return f"{stat.name}=unknown points={stat.points}"
        return (
            f"{stat.name}=min:{stat.min_cm:.0f} avg:{stat.avg_cm:.0f} "
            f"pts:{stat.points} danger:{stat.danger.value}"
        )

    def _log_decision(self, decision: AvoidanceDecision, zones: dict[str, ZoneStats]) -> None:
        zone_text = " ".join(self._fmt_zone(z) for z in zones.values())
        log.info(
            "Patrol LIDAR zones: %s | action=%s reason=%s",
            zone_text,
            decision.action.value,
            decision.reason,
        )
