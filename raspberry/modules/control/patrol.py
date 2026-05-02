"""Contrôleur de patrouille autonome avec évitement d'obstacles."""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SPEED = 0.3  # vitesse d'avance (0-1)
_TURN_SPEED = 0.4  # vitesse de rotation
_OBSTACLE_CM = 40.0  # distance de déclenchement de l'évitement (cm)
_TURN_DURATION = 0.8  # durée de la rotation d'évitement normale (secondes)
_LOOP_INTERVAL = 0.1  # intervalle de la boucle principale (secondes)

# Détection de blocage (angle mort)
_STUCK_TIMEOUT = 3.5  # secondes en FORWARD sans obstacle détecté → coincé
_STUCK_REVERSE_DUR = 0.5  # recul avant de tourner quand coincé (secondes)
_STUCK_TURN_DUR = 1.2  # rotation plus longue quand coincé (secondes)


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------


class PatrolState(str, Enum):
    IDLE = "idle"
    FORWARD = "forward"
    AVOIDING = "avoiding"  # obstacle détecté par capteur / vision
    STUCK = "stuck"  # coincé dans un angle mort


# ---------------------------------------------------------------------------
# Contrôleur
# ---------------------------------------------------------------------------


class PatrolController:
    """
    Patrouille autonome : le robot avance et esquive les obstacles.

    Trois sources de déclenchement d'évitement :
    1. Ultrason (HC-SR04) — obstacle dans le cône frontal
    2. Vision (OpenCV) — obstacle détecté par caméra
    3. Stuck detection — robot bloqué dans un angle mort (aucun capteur ne voit)

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
        Durée de la rotation d'évitement normale (secondes).
    stuck_timeout : float
        Durée en FORWARD sans obstacle détecté avant de considérer le robot coincé.
    """

    def __init__(
        self,
        motors,
        ultrasonic=None,
        vision=None,
        speed: float = _SPEED,
        obstacle_cm: float = _OBSTACLE_CM,
        turn_duration: float = _TURN_DURATION,
        stuck_timeout: float = _STUCK_TIMEOUT,
    ) -> None:
        self._motors = motors
        self._ultrasonic = ultrasonic
        self._vision = vision
        self.speed = speed
        self.obstacle_cm = obstacle_cm
        self.turn_duration = turn_duration
        self.stuck_timeout = stuck_timeout

        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._state: PatrolState = PatrolState.IDLE

        # Suivi du blocage
        self._forward_since: float | None = None  # timestamp entrée en FORWARD
        self._avoidance_count: int = 0  # alternance gauche/droite

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
        self._forward_since = None
        self._avoidance_count = 0
        self._task = asyncio.create_task(self._run(loop))
        log.info("Patrouille démarrée (stuck_timeout=%.1fs)", self.stuck_timeout)

    async def stop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._state = PatrolState.IDLE
        self._forward_since = None
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
                    # ── Évitement classique (obstacle détecté par capteur/vision) ──
                    self._forward_since = None
                    self._state = PatrolState.AVOIDING
                    await self._do_avoidance(loop, Direction)
                else:
                    now = time.monotonic()

                    if self._state != PatrolState.FORWARD:
                        # On vient d'entrer en FORWARD — démarrer le chrono
                        self._forward_since = now
                        self._state = PatrolState.FORWARD

                    # ── Détection de blocage (angle mort) ──
                    if (
                        self._forward_since is not None
                        and (now - self._forward_since) > self.stuck_timeout
                    ):
                        elapsed = now - self._forward_since
                        self._forward_since = None
                        self._state = PatrolState.STUCK
                        log.warning(
                            "Robot coincé (%.1fs en FORWARD sans obstacle détecté) → évitement angle mort",
                            elapsed,
                        )
                        await self._do_stuck_avoidance(loop, Direction)
                    else:
                        # ── Avance normalement ──
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
    # Manœuvres d'évitement
    # ------------------------------------------------------------------

    async def _do_avoidance(self, loop: asyncio.AbstractEventLoop, Direction) -> None:
        """Évitement standard : stop → tourne (alternance G/D)."""
        turn_dir = self._next_turn_direction(Direction)
        dur = self.turn_duration

        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.2)
        await loop.run_in_executor(
            None, lambda d=turn_dir, s=_TURN_SPEED: self._motors.from_direction(d, s)
        )
        await asyncio.sleep(dur)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.15)
        log.debug("Évitement classique — direction=%s dur=%.2fs", turn_dir.value, dur)

    async def _do_stuck_avoidance(self, loop: asyncio.AbstractEventLoop, Direction) -> None:
        """Évitement angle mort : recul → tourne plus longtemps (alternance G/D)."""
        turn_dir = self._next_turn_direction(Direction)
        rev_dur = _STUCK_REVERSE_DUR
        turn_dur = _STUCK_TURN_DUR

        # Recul
        await loop.run_in_executor(
            None, lambda s=self.speed: self._motors.from_direction(Direction.BACKWARD, s)
        )
        await asyncio.sleep(rev_dur)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.2)

        # Rotation longue
        await loop.run_in_executor(
            None, lambda d=turn_dir, s=_TURN_SPEED: self._motors.from_direction(d, s)
        )
        await asyncio.sleep(turn_dur)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.2)
        log.warning(
            "Évitement angle mort — recul=%.2fs rotation=%s dur=%.2fs",
            rev_dur,
            turn_dir.value,
            turn_dur,
        )

    def _next_turn_direction(self, Direction):
        """Alterne gauche / droite à chaque évitement pour ne pas tourner en rond."""
        self._avoidance_count += 1
        return Direction.LEFT if self._avoidance_count % 2 == 0 else Direction.RIGHT

    # ------------------------------------------------------------------
    # Détection d'obstacle (capteurs)
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
