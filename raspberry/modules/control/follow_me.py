"""Safe OAK-D spatial person following for inspection-area teaching."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class FollowMeController:
    """Follow one fresh OAK person target while recording the SLAM trail.

    The controller never commands reverse motion. A missing target, stale pose,
    unavailable LIDAR or obstacle veto always produces an immediate motor stop.
    """

    def __init__(
        self,
        motors,
        oak,
        lidar,
        pose_provider: Callable[[], dict[str, Any] | None],
        *,
        target_distance_m: float = 0.75,
        distance_deadband_m: float = 0.10,
        minimum_motor_command: float = 0.14,
        max_forward_speed: float = 0.30,
        max_turn_speed: float = 0.30,
        obstacle_stop_cm: float = 40.0,
        side_stop_cm: float = 28.0,
        align_deadband_deg: float = 6.0,
        pivot_only_deg: float = 48.0,
        target_smoothing: float = 0.45,
        trail_spacing_m: float = 0.30,
        trail_yaw_spacing_deg: float = 20.0,
    ) -> None:
        self._motors = motors
        self._oak = oak
        self._lidar = lidar
        self._pose_provider = pose_provider
        self.target_distance_m = max(0.55, float(target_distance_m))
        self.distance_deadband_m = max(0.05, float(distance_deadband_m))
        self.minimum_motor_command = max(0.10, min(float(minimum_motor_command), 0.20))
        self.max_forward_speed = max(
            self.minimum_motor_command, min(float(max_forward_speed), 0.30)
        )
        self.max_turn_speed = max(self.minimum_motor_command, min(float(max_turn_speed), 0.30))
        self.obstacle_stop_cm = max(30.0, float(obstacle_stop_cm))
        self.side_stop_cm = max(25.0, float(side_stop_cm))
        self.align_deadband_rad = math.radians(max(5.0, float(align_deadband_deg)))
        self.pivot_only_rad = math.radians(
            max(math.degrees(self.align_deadband_rad) + 5.0, float(pivot_only_deg))
        )
        self.target_smoothing = max(0.1, min(float(target_smoothing), 1.0))
        self.trail_spacing_m = max(0.10, float(trail_spacing_m))
        self.trail_yaw_spacing_rad = math.radians(max(5.0, float(trail_yaw_spacing_deg)))
        self._task: asyncio.Task | None = None
        self._active = False
        self._state = "idle"
        self._reason = ""
        self._target_distance: float | None = None
        self._target_angle: float | None = None
        self._trail: list[dict[str, float]] = []

    @property
    def active(self) -> bool:
        return self._active

    def to_dict(self) -> dict[str, Any]:
        return {
            "follow_me_active": self._active,
            "follow_me_state": self._state,
            "follow_me_reason": self._reason,
            "follow_me_target_distance_m": self._target_distance,
            "follow_me_target_angle_deg": (
                round(math.degrees(self._target_angle), 1)
                if self._target_angle is not None
                else None
            ),
            "follow_me_trail": list(self._trail),
            "follow_me_trail_count": len(self._trail),
        }

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._active:
            return
        self._trail = []
        self._active = True
        self._state = "waiting_person"
        self._reason = "Placez-vous devant le rover"
        self._task = loop.create_task(self._run())
        log.info("Follow Me démarré")

    async def stop(self) -> None:
        self._active = False
        task = self._task
        self._task = None
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self._motors.stop)
        self._state = "idle"
        self._reason = ""
        self._target_distance = None
        self._target_angle = None
        log.info("Follow Me arrêté")

    async def _run(self) -> None:
        try:
            while self._active:
                await self._step()
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Follow Me interrompu")
            self._active = False
            self._state = "error"
            self._reason = str(exc)
        finally:
            await asyncio.to_thread(self._motors.stop)

    async def _step(self) -> None:
        target = self._oak.person_target
        if target is None or target.z_mm <= 0:
            self._target_distance = None
            self._target_angle = None
            await self._stop_for("waiting_person", "Personne perdue — rover arrêté")
            return

        distance_m = target.z_mm / 1000.0
        angle_rad = math.atan2(float(target.x_mm), float(target.z_mm))
        alpha = self.target_smoothing
        if self._target_distance is not None and self._target_angle is not None:
            distance_m = alpha * distance_m + (1.0 - alpha) * self._target_distance
            angle_rad = alpha * angle_rad + (1.0 - alpha) * self._target_angle
        self._target_distance = round(distance_m, 3)
        self._target_angle = angle_rad

        hazard = self._safety_veto(angle_rad)
        if hazard:
            await self._stop_for("obstacle", hazard)
            self._record_pose()
            return

        angle_abs = abs(angle_rad)
        distance_error = distance_m - self.target_distance_m
        aligned = angle_abs <= self.align_deadband_rad
        too_far = distance_error > self.distance_deadband_m

        if aligned and not too_far:
            await self._stop_for("target_reached", "Distance de suivi atteinte")
            self._record_pose()
            return

        turn = 0.0
        if not aligned:
            turn = min(
                self.max_turn_speed,
                max(self.minimum_motor_command, angle_abs * 0.55),
            )
            if angle_rad < 0.0:
                turn = -turn

        forward = 0.0
        if too_far and angle_abs < self.pivot_only_rad:
            speed = min(
                self.max_forward_speed,
                max(self.minimum_motor_command, 0.12 + distance_error * 0.22),
            )
            # Le pivot domine à mesure que le désalignement grandit, pour ne
            # pas foncer de travers ; en dessous du seuil de pivot pur, le
            # rover avance donc en tournant au lieu de s'arrêter pour pivoter.
            blend = max(0.0, 1.0 - (angle_abs / self.pivot_only_rad) ** 1.5)
            forward = speed * blend

        if turn and forward:
            await asyncio.to_thread(self._motors.drive, forward + turn, forward - turn)
        elif turn:
            await asyncio.to_thread(self._motors.drive, turn, -turn)
        else:
            steering = max(-0.65, min(0.65, angle_rad / math.radians(20.0)))
            await asyncio.to_thread(self._motors.arc, forward, steering)

        if turn > 0.0:
            self._state = "turning_right"
        elif turn < 0.0:
            self._state = "turning_left"
        else:
            self._state = "following"
        self._reason = "Alignement sur la personne" if turn else "Suivi de la personne"

        self._record_pose()

    async def _stop_for(self, state: str, reason: str) -> None:
        await asyncio.to_thread(self._motors.stop)
        self._state = state
        self._reason = reason

    def _safety_veto(self, angle_rad: float) -> str | None:
        snapshot = self._lidar.snapshot
        if not snapshot.connected:
            return "LIDAR indisponible — rover arrêté"
        if (
            snapshot.front_distance_cm is not None
            and snapshot.front_distance_cm < self.obstacle_stop_cm
        ):
            return f"Obstacle devant à {snapshot.front_distance_cm:.0f} cm"
        if angle_rad < -self.align_deadband_rad:
            if (
                snapshot.left_distance_cm is not None
                and snapshot.left_distance_cm < self.side_stop_cm
            ):
                return f"Obstacle à gauche à {snapshot.left_distance_cm:.0f} cm"
        if angle_rad > self.align_deadband_rad:
            if (
                snapshot.right_distance_cm is not None
                and snapshot.right_distance_cm < self.side_stop_cm
            ):
                return f"Obstacle à droite à {snapshot.right_distance_cm:.0f} cm"

        depth_zones = self._oak.depth_zones
        if depth_zones.get("center"):
            return "Obstacle bas détecté devant par l’OAK"
        if angle_rad < 0.0 and depth_zones.get("left"):
            return "Obstacle bas détecté à gauche par l’OAK"
        if angle_rad > 0.0 and depth_zones.get("right"):
            return "Obstacle bas détecté à droite par l’OAK"
        return None

    def _record_pose(self) -> None:
        pose = self._pose_provider()
        if not pose:
            return
        try:
            updated_at = float(pose.get("updated_at", 0.0))
            point = {name: float(pose[name]) for name in ("x", "y", "yaw")}
        except (KeyError, TypeError, ValueError):
            return
        if not all(math.isfinite(value) for value in point.values()):
            return
        if updated_at and time.time() - updated_at > 2.0:
            return
        if self._trail:
            previous = self._trail[-1]
            distance = math.hypot(point["x"] - previous["x"], point["y"] - previous["y"])
            yaw_delta = abs(
                math.atan2(
                    math.sin(point["yaw"] - previous["yaw"]),
                    math.cos(point["yaw"] - previous["yaw"]),
                )
            )
            if distance < self.trail_spacing_m and yaw_delta < self.trail_yaw_spacing_rad:
                return
        self._trail.append(point)
        if len(self._trail) > 2000:
            self._trail.pop(0)
