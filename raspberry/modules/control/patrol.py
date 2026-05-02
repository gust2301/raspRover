"""Contrôleur de patrouille autonome avec évitement d'obstacles."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SPEED = 0.3  # vitesse d'avance (0-1)
_TURN_SPEED = 0.4  # vitesse de rotation
_OBSTACLE_CM = 40.0  # distance de déclenchement de l'évitement (cm)
_TURN_DURATION = 0.8  # durée de la rotation (secondes)
_LOOP_INTERVAL = 0.1  # intervalle de la boucle principale (secondes)


# ---------------------------------------------------------------------------
# État
# ---------------------------------------------------------------------------


class PatrolState(str, Enum):
    IDLE = "idle"
    FORWARD = "forward"
    AVOIDING = "avoiding"


# ---------------------------------------------------------------------------
# Contrôleur
# ---------------------------------------------------------------------------


class PatrolController:
    """
    Patrouille autonome : le robot avance et esquive les obstacles.

    Parameters
    ----------
    motors : MotorController
    ultrasonic : UltrasonicSensor | None
    vision : VisionObstacleDetector | None
    speed : float
        Vitesse d'avance normalisée (0-1).
    obstacle_cm : float
        Distance en cm en dessous de laquelle esquiver.
    turn_duration : float
        Durée de la rotation d'évitement (secondes).
    """

    def __init__(
        self,
        motors,
        ultrasonic=None,
        vision=None,
        speed: float = _SPEED,
        obstacle_cm: float = _OBSTACLE_CM,
        turn_duration: float = _TURN_DURATION,
    ) -> None:
        self._motors = motors
        self._ultrasonic = ultrasonic
        self._vision = vision
        self.speed = speed
        self.obstacle_cm = obstacle_cm
        self.turn_duration = turn_duration
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._state: PatrolState = PatrolState.IDLE

    # ------------------------------------------------------------------
    # Propriétés
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def state(self) -> PatrolState:
        return self._state

    def to_dict(self) -> dict:
        return {"patrol_active": self.active, "patrol_state": self._state.value}

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    async def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self.active:
            return
        self._task = asyncio.create_task(self._run(loop))
        log.info("Patrouille démarrée")

    async def stop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._state = PatrolState.IDLE
        await loop.run_in_executor(None, self._motors.stop)
        log.info("Patrouille arrêtée")

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------

    async def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        from modules.control.motor_controller import Direction

        try:
            while True:
                if self._obstacle_detected():
                    self._state = PatrolState.AVOIDING
                    # Arrêt + pause
                    await loop.run_in_executor(None, self._motors.stop)
                    await asyncio.sleep(0.2)
                    # Tourne à droite
                    spd = _TURN_SPEED
                    dur = self.turn_duration
                    await loop.run_in_executor(
                        None,
                        lambda s=spd: self._motors.from_direction(Direction.RIGHT, s),
                    )
                    await asyncio.sleep(dur)
                    await loop.run_in_executor(None, self._motors.stop)
                    await asyncio.sleep(0.2)
                else:
                    self._state = PatrolState.FORWARD
                    spd = self.speed
                    await loop.run_in_executor(
                        None,
                        lambda s=spd: self._motors.from_direction(Direction.FORWARD, s),
                    )

                await asyncio.sleep(_LOOP_INTERVAL)

        except asyncio.CancelledError:
            await loop.run_in_executor(None, self._motors.stop)
            self._state = PatrolState.IDLE
            raise

    # ------------------------------------------------------------------
    # Détection d'obstacle
    # ------------------------------------------------------------------

    def _obstacle_detected(self) -> bool:
        """Obstacle devant ? Combine ultrason ET vision."""
        us_detected = False
        if self._ultrasonic is not None:
            r = self._ultrasonic.reading
            if r.front.distance_cm is not None:
                us_detected = r.front.distance_cm < self.obstacle_cm
            else:
                us_detected = r.front.obstacle

        vis_detected = self._vision.obstacle if self._vision is not None else False

        return us_detected or vis_detected
