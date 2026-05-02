"""
Contrôleur de patrouille autonome.

Comportement :
  - Avance en continu jusqu'à détection d'obstacle (pas de limite de durée).
  - Surveillance ultrason + caméra 3 zones toutes les 50 ms pendant le mouvement.
  - À la détection d'un obstacle :
      * Gauche uniquement  → tourne droite
      * Droite uniquement  → tourne gauche
      * Centre / frontal   → recul + tourne (alternance G/D)
  - Reprend l'avance immédiatement après l'évitement.

Pas de « steps » ni de SCANNING bloquant : le mouvement est fluide.
"""

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
_TURN_SPEED = 0.42  # vitesse de rotation
_OBSTACLE_CM = 40.0  # seuil ultrason (cm)
_POLL = 0.05  # intervalle de surveillance pendant l'avance (s)

_TURN_LATERAL = 0.75  # rotation pour obstacle latéral (s)
_TURN_FRONT = 0.90  # rotation pour obstacle frontal (s)
_REVERSE_FRONT = 0.4  # recul avant rotation frontale (s)

_TURN_PAUSE = 0.15  # pause moteurs entre phases (s)


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------


class PatrolState(str, Enum):
    IDLE = "idle"
    FORWARD = "forward"
    AVOIDING = "avoiding"
    STUCK = "stuck"  # gardé pour compatibilité UI, non utilisé en automatique


# ---------------------------------------------------------------------------
# Contrôleur
# ---------------------------------------------------------------------------


class PatrolController:
    """
    Patrouille autonome : avance librement, évite les obstacles détectés.

    Parameters
    ----------
    motors       : MotorController
    ultrasonic   : UltrasonicSensor | None
    vision       : VisionObstacleDetector | None
    pantilt      : ignoré (gardé pour compatibilité)
    speed        : float  vitesse d'avance (0-1)
    obstacle_cm  : float  seuil ultrason déclenchant l'évitement (cm)
    step_duration: ignoré
    scan_with_pantilt : ignoré
    stuck_timeout: ignoré (pas de limite de durée en avance libre)
    """

    def __init__(
        self,
        motors,
        ultrasonic=None,
        vision=None,
        pantilt=None,
        speed: float = _SPEED,
        obstacle_cm: float = _OBSTACLE_CM,
        step_duration: float = 0.7,
        scan_with_pantilt: bool = False,
        stuck_timeout: float = 0.0,
    ) -> None:
        self._motors = motors
        self._ultrasonic = ultrasonic
        self._vision = vision
        self.speed = speed
        self.obstacle_cm = obstacle_cm

        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._state: PatrolState = PatrolState.IDLE
        self._avoidance_count: int = 0

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
        self._avoidance_count = 0
        self._task = asyncio.create_task(self._run(loop))
        log.info("Patrouille démarrée (speed=%.2f obstacle_cm=%.0f)", self.speed, self.obstacle_cm)

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
                # ── Avance en continu ──────────────────────────────────
                self._state = PatrolState.FORWARD
                spd = self.speed
                await loop.run_in_executor(
                    None, lambda s=spd: self._motors.from_direction(Direction.FORWARD, s)
                )
                log.info("Patrol: FORWARD (vitesse=%.2f)", spd)

                # Surveillance obstacle pendant l'avance
                obstacle = await self._monitor_until_obstacle(loop)

                # ── Évitement ─────────────────────────────────────────
                if obstacle:
                    self._state = PatrolState.AVOIDING
                    await loop.run_in_executor(None, self._motors.stop)
                    log.info("Patrol: OBSTACLE — %s", obstacle)
                    await self._avoid(loop, Direction, obstacle)
                    # Reprend l'avance au prochain tour de boucle

        except asyncio.CancelledError:
            await loop.run_in_executor(None, self._motors.stop)
            self._state = PatrolState.IDLE
            raise

    # ------------------------------------------------------------------
    # Surveillance pendant l'avance
    # ------------------------------------------------------------------

    async def _monitor_until_obstacle(self, loop: asyncio.AbstractEventLoop) -> str | None:
        """
        Surveille les capteurs toutes les _POLL secondes.
        Retourne une description de l'obstacle dès qu'il est détecté, ou None si annulé.
        """
        t_start = time.monotonic()
        while True:
            # — Ultrason (priorité haute) —
            if self._ultrasonic:
                r = self._ultrasonic.reading
                cm = r.front.distance_cm
                if (cm is not None and cm < self.obstacle_cm) or (cm is None and r.front.obstacle):
                    us_str = f"{cm:.0f}cm" if cm else "proche"
                    log.info(
                        "Patrol US: obstacle frontal %s après %.1fs",
                        us_str,
                        time.monotonic() - t_start,
                    )
                    return f"ultrason {us_str}"

            # — Vision 3 zones (priorité basse) —
            if self._vision:
                zones = self._vision.zones
                left = zones.get("left", False)
                center = zones.get("center", False)
                right = zones.get("right", False)

                if center:
                    log.info("Patrol cam: obstacle CENTRE après %.1fs", time.monotonic() - t_start)
                    return "vision:center"
                if left and right:
                    log.info("Patrol cam: obstacle G+D après %.1fs", time.monotonic() - t_start)
                    return "vision:center"
                if left:
                    log.info("Patrol cam: obstacle GAUCHE après %.1fs", time.monotonic() - t_start)
                    return "vision:left"
                if right:
                    log.info("Patrol cam: obstacle DROITE après %.1fs", time.monotonic() - t_start)
                    return "vision:right"

            await asyncio.sleep(_POLL)

    # ------------------------------------------------------------------
    # Évitement directionnel
    # ------------------------------------------------------------------

    def _next_turn_dir(self, Direction):
        """Alterne gauche/droite pour les évitements frontaux."""
        self._avoidance_count += 1
        return Direction.LEFT if self._avoidance_count % 2 == 0 else Direction.RIGHT

    async def _avoid(
        self,
        loop: asyncio.AbstractEventLoop,
        Direction,
        obstacle: str,
    ) -> None:
        if obstacle.startswith("vision:left"):
            # Obstacle à gauche → tourne droite
            await self._turn(loop, Direction.RIGHT, _TURN_LATERAL, "obstacle gauche → droite")

        elif obstacle.startswith("vision:right"):
            # Obstacle à droite → tourne gauche
            await self._turn(loop, Direction.LEFT, _TURN_LATERAL, "obstacle droite → gauche")

        else:
            # Obstacle frontal (ultrason ou centre caméra) → recul + tourne
            turn_dir = self._next_turn_dir(Direction)
            await self._reverse_and_turn(loop, Direction, turn_dir, obstacle)

    async def _turn(
        self,
        loop: asyncio.AbstractEventLoop,
        turn_dir,
        duration: float,
        reason: str,
    ) -> None:
        log.info("Patrol avoid: rotation %s %.2fs | %s", turn_dir.value, duration, reason)
        await loop.run_in_executor(
            None, lambda d=turn_dir: self._motors.from_direction(d, _TURN_SPEED)
        )
        await asyncio.sleep(duration)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)

    async def _reverse_and_turn(
        self,
        loop: asyncio.AbstractEventLoop,
        Direction,
        turn_dir,
        reason: str,
    ) -> None:
        log.info(
            "Patrol avoid: recul %.2fs + rotation %s %.2fs | %s",
            _REVERSE_FRONT,
            turn_dir.value,
            _TURN_FRONT,
            reason,
        )
        spd = self.speed
        await loop.run_in_executor(
            None, lambda s=spd: self._motors.from_direction(Direction.BACKWARD, s)
        )
        await asyncio.sleep(_REVERSE_FRONT)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)
        await loop.run_in_executor(
            None, lambda d=turn_dir: self._motors.from_direction(d, _TURN_SPEED)
        )
        await asyncio.sleep(_TURN_FRONT)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)
