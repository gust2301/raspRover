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

Détection de blocage :
  - Si le robot enchaîne plusieurs évitements rapides sans progresser
    (_STUCK_SCAN_THRESHOLD évitements avec < _MIN_FREE_SECS de libre entre eux),
    un scan pan-tilt est déclenché pour trouver la direction la plus dégagée.
  - Le scan pan-tilt ne se déclenche que sur blocage, jamais en avance libre.

Pas de « steps » ni de SCANNING systématique : le mouvement est fluide.
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

# Vision : confirmation par ultrason avant d'agir sur la zone centre
# Si l'US voit plus loin que ce seuil, la vision centre est ignorée (faux positif probable)
_VISION_US_CONFIRM_CM = 90.0  # cm

# Détection de blocage → scan pan-tilt
_MIN_FREE_SECS = 1.5  # seuil de « progression réelle » (secondes de libre)
_STUCK_SCAN_THRESHOLD = 3  # évitements rapides consécutifs avant scan pan-tilt
_SCAN_ANGLES = (-50, 0, 50)  # angles pan pour le scan (°) : gauche / centre / droite
_SCAN_SETTLE = 0.6  # temps de stabilisation servo avant lecture (s)
_SCAN_READ_SECS = 0.5  # durée de lecture des capteurs par position (s)


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
    pantilt      : PanTiltController | None  (utilisé pour le scan de déblocage)
    speed        : float  vitesse d'avance (0-1)
    obstacle_cm  : float  seuil ultrason déclenchant l'évitement (cm)
    step_duration: ignoré
    scan_with_pantilt : ignoré (scan déclenché automatiquement sur blocage)
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
        self._pantilt = pantilt
        self.speed = speed
        self.obstacle_cm = obstacle_cm

        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._state: PatrolState = PatrolState.IDLE
        self._avoidance_count: int = 0

        # Compteur de blocage pour le scan pan-tilt
        self._short_move_count: int = 0  # évitements rapides consécutifs

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
        self._short_move_count = 0
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

                t_free_start = time.monotonic()

                # Surveillance obstacle pendant l'avance
                obstacle = await self._monitor_until_obstacle(loop)

                # ── Évitement ─────────────────────────────────────────
                if obstacle:
                    free_secs = time.monotonic() - t_free_start
                    self._state = PatrolState.AVOIDING
                    await loop.run_in_executor(None, self._motors.stop)
                    log.info(
                        "Patrol: OBSTACLE — %s (libre=%.1fs)",
                        obstacle,
                        free_secs,
                    )

                    # Suivi de blocage : progression courte → incrémente le compteur
                    if free_secs < _MIN_FREE_SECS:
                        self._short_move_count += 1
                        log.info(
                            "Patrol: mouvement court (%.1fs), compteur blocage=%d/%d",
                            free_secs,
                            self._short_move_count,
                            _STUCK_SCAN_THRESHOLD,
                        )
                    else:
                        if self._short_move_count:
                            log.info(
                                "Patrol: progression ok (%.1fs), reset compteur blocage",
                                free_secs,
                            )
                        self._short_move_count = 0

                    # Si bloqué trop souvent → scan pan-tilt pour trouver une sortie
                    if self._short_move_count >= _STUCK_SCAN_THRESHOLD and self._pantilt:
                        log.warning(
                            "Patrol: BLOQUÉ (%d évitements rapides) → scan pan-tilt",
                            self._short_move_count,
                        )
                        self._state = PatrolState.STUCK
                        self._short_move_count = 0
                        best_dir = await self._pantilt_scan(loop, Direction)
                        if best_dir is not None:
                            await self._turn(loop, best_dir, _TURN_FRONT, "sortie scan pan-tilt")
                    else:
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

                # Centre : si l'ultrason voit loin, la vision est probablement un faux positif
                # (sol, reflet, JPEG artifact…). On ne la prend en compte que si l'US
                # est trop proche pour être fiable ou confirme un obstacle proche.
                if center and self._ultrasonic:
                    r2 = self._ultrasonic.reading
                    cm2 = r2.front.distance_cm
                    if cm2 is not None and cm2 > _VISION_US_CONFIRM_CM:
                        center = False  # US dit voie libre → ignore vision center

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

    # ------------------------------------------------------------------
    # Scan pan-tilt (uniquement en cas de blocage)
    # ------------------------------------------------------------------

    async def _pantilt_scan(self, loop: asyncio.AbstractEventLoop, Direction):
        """
        Balaye les angles pan (gauche / centre / droite) et évalue chaque direction.
        Retourne Direction.LEFT, Direction.RIGHT, ou None (si centre dégagé).

        Appelé UNIQUEMENT lorsque le robot est bloqué (_short_move_count dépassé).
        """
        log.info("Patrol scan: balayage pan-tilt %s", _SCAN_ANGLES)
        scores: dict[int, float] = {}  # angle → score de dégagement (plus haut = plus libre)

        for angle in _SCAN_ANGLES:
            # Oriente le pan (tilt à 0° pour ne pas fausser l'ultrason)
            try:
                await loop.run_in_executor(None, lambda a=angle: self._pantilt.goto(a, 0.0))
            except Exception as exc:  # noqa: BLE001
                log.warning("Patrol scan: erreur goto(%d): %s", angle, exc)
                continue

            await asyncio.sleep(_SCAN_SETTLE)

            # Lecture sur _SCAN_READ_SECS
            t0 = time.monotonic()
            us_readings: list[float] = []
            vision_clears: list[bool] = []

            while time.monotonic() - t0 < _SCAN_READ_SECS:
                if self._ultrasonic:
                    r = self._ultrasonic.reading
                    cm = r.front.distance_cm
                    if cm is not None:
                        us_readings.append(cm)

                if self._vision:
                    zones = self._vision.zones
                    vision_clears.append(not zones.get("center", False))

                await asyncio.sleep(_POLL)

            # Score = distance US moyenne (si dispo), sinon fraction de frames libres
            if us_readings:
                score = sum(us_readings) / len(us_readings)
            elif vision_clears:
                score = (sum(vision_clears) / len(vision_clears)) * 300.0
            else:
                score = 0.0

            log.info(
                "Patrol scan: angle=%d° → score=%.1f (us=%d lectures, vis=%d frames)",
                angle,
                score,
                len(us_readings),
                len(vision_clears),
            )
            scores[angle] = score

        # Recentre la caméra
        try:
            await loop.run_in_executor(None, self._pantilt.center)
        except Exception as exc:  # noqa: BLE001
            log.warning("Patrol scan: erreur recentrage: %s", exc)

        if not scores:
            log.warning("Patrol scan: aucune mesure — évitement par défaut")
            return Direction.RIGHT

        best_angle = max(scores, key=lambda a: scores[a])
        best_score = scores[best_angle]
        log.info("Patrol scan: meilleure direction angle=%d° score=%.1f", best_angle, best_score)

        if best_score < self.obstacle_cm * 0.5:
            # Même la meilleure direction est très encombrée
            log.warning("Patrol scan: toutes directions bloquées (score max=%.1f)", best_score)
            # On recule et tourne quand même
            return Direction.LEFT if self._avoidance_count % 2 == 0 else Direction.RIGHT

        if best_angle < -10:
            return Direction.LEFT
        if best_angle > 10:
            return Direction.RIGHT
        return None  # centre dégagé → pas de rotation, reprend l'avance

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
