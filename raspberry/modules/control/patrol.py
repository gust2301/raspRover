"""
Contrôleur de patrouille autonome.

Comportement :
  - Avance en continu jusqu'à détection d'obstacle (pas de limite de durée).
  - Surveillance ultrason + caméra zones G/D toutes les 50 ms.
  - À la détection d'un obstacle :
      * Gauche uniquement  → tourne droite
      * Droite uniquement  → tourne gauche
      * Centre / frontal   → recul + tourne (direction choisie intelligemment)
  - Reprend l'avance immédiatement après l'évitement.

Navigation intelligente sans lidar (dead reckoning) :
  - Estime le cap courant à partir de la durée des rotations.
  - Mémorise les N derniers caps parcourus.
  - Choisit toujours la direction de rotation qui explore le cap
    le plus éloigné des caps déjà visités → évite de revenir sur ses pas.

Détection de blocage :
  - Après _STUCK_SCAN_THRESHOLD évitements rapides consécutifs,
    déclenche un scan pan-tilt pour trouver la sortie la plus dégagée.
"""

from __future__ import annotations

import asyncio
import logging
import random
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
_TURN_FRONT = 0.90  # rotation pour obstacle frontal (s) — durée de base
_TURN_FRONT_JITTER = 0.35  # ±variation aléatoire (s) — brise la périodicité
_REVERSE_FRONT = 0.4  # recul avant rotation frontale (s)

_TURN_PAUSE = 0.15  # pause moteurs entre phases (s)

# Keepalive moteur : le MotorController coupe les moteurs après watchdog_s (1 s)
# si aucune commande n'est reçue. On renouvelle la commande FORWARD avant l'expiry.
_MOTOR_KEEPALIVE = 0.4  # s (watchdog = 1 s → on rafraîchit à 0.4 s)

# Vision latérale (zones G/D uniquement — l'US gère le centre)
_VISION_WARMUP = 1.5  # s avant d'activer la vision après FORWARD (vote stabilisé)

# Dead reckoning — estimation du cap courant
# Vitesse angulaire estimée à _TURN_SPEED. Calibrer en observant les rotations :
# si le robot tourne de ~90° en 0.90 s → 100 °/s. Ajuster selon le modèle.
_TURN_DEG_PER_SEC = 100.0  # °/s à _TURN_SPEED (approximation, calibrable)
_HEADING_HISTORY_SIZE = 8  # nombre de caps récents mémorisés
# Seuil d'égalité : si les deux candidats ont un score < _TIE_THRESHOLD degrés
# d'écart, on choisit aléatoirement pour briser les boucles périodiques.
_TIE_THRESHOLD = 20.0  # °

# Détection de blocage → scan pan-tilt
_MIN_FREE_SECS = 1.5  # seuil de « progression réelle » (s)
_STUCK_SCAN_THRESHOLD = 3  # évitements rapides consécutifs avant scan pan-tilt
_SCAN_ANGLES = (-50, 0, 50)  # angles pan pour le scan (°)
_SCAN_SETTLE = 0.6  # stabilisation servo avant lecture (s)
_SCAN_READ_SECS = 0.5  # durée de lecture des capteurs par position (s)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _angular_dist(a: float, b: float) -> float:
    """Distance angulaire minimale entre deux caps (0–180°)."""
    diff = abs(a - b) % 360
    return min(diff, 360.0 - diff)


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------


class PatrolState(str, Enum):
    IDLE = "idle"
    FORWARD = "forward"
    AVOIDING = "avoiding"
    STUCK = "stuck"


# ---------------------------------------------------------------------------
# Contrôleur
# ---------------------------------------------------------------------------


class PatrolController:
    """
    Patrouille autonome avec dead reckoning : avance librement, évite les
    obstacles en choisissant toujours la direction la moins explorée.

    Parameters
    ----------
    motors       : MotorController
    ultrasonic   : UltrasonicSensor | None
    vision       : VisionObstacleDetector | None
    pantilt      : PanTiltController | None  (scan de déblocage)
    speed        : float  vitesse d'avance (0-1)
    obstacle_cm  : float  seuil ultrason déclenchant l'évitement (cm)
    step_duration, scan_with_pantilt, stuck_timeout : ignorés (rétrocompat)
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

        # Dead reckoning
        self._heading: float = 0.0  # cap estimé (0-360°, arbitraire)
        self._heading_history: list[float] = []

        # Compteur de blocage
        self._short_move_count: int = 0

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
        self._heading = 0.0
        self._heading_history = []
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

                # Enregistre le cap actuel avant de partir
                self._record_heading()

                await loop.run_in_executor(
                    None, lambda s=spd: self._motors.from_direction(Direction.FORWARD, s)
                )
                log.info(
                    "Patrol: FORWARD cap=%.0f° (vitesse=%.2f)",
                    self._heading,
                    spd,
                )

                t_free_start = time.monotonic()
                obstacle = await self._monitor_until_obstacle(loop, Direction.FORWARD, spd)

                # ── Évitement ─────────────────────────────────────────
                if obstacle:
                    free_secs = time.monotonic() - t_free_start
                    self._state = PatrolState.AVOIDING
                    await loop.run_in_executor(None, self._motors.stop)
                    log.info(
                        "Patrol: OBSTACLE — %s (libre=%.1fs cap=%.0f°)",
                        obstacle,
                        free_secs,
                        self._heading,
                    )

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

                    if self._short_move_count >= _STUCK_SCAN_THRESHOLD and self._pantilt:
                        log.warning(
                            "Patrol: BLOQUÉ (%d évitements rapides) → scan pan-tilt",
                            self._short_move_count,
                        )
                        self._state = PatrolState.STUCK
                        self._short_move_count = 0
                        best_dir = await self._pantilt_scan(loop, Direction)
                        if best_dir is not None:
                            await self._turn(loop, best_dir, _TURN_FRONT, "sortie scan")
                    else:
                        await self._avoid(loop, Direction, obstacle)

        except asyncio.CancelledError:
            await loop.run_in_executor(None, self._motors.stop)
            self._state = PatrolState.IDLE
            raise

    # ------------------------------------------------------------------
    # Surveillance pendant l'avance
    # ------------------------------------------------------------------

    async def _monitor_until_obstacle(
        self,
        loop: asyncio.AbstractEventLoop,
        fwd_direction,
        fwd_speed: float,
    ) -> str | None:
        """
        Surveille les capteurs toutes les _POLL secondes.
        Rafraîchit la commande moteur toutes les _MOTOR_KEEPALIVE secondes
        pour éviter l'arrêt par le watchdog du MotorController (timeout 1 s).
        """
        t_start = time.monotonic()
        t_last_keepalive = t_start

        while True:
            now = time.monotonic()
            elapsed = now - t_start

            # ── Keepalive moteur ──────────────────────────────────
            if now - t_last_keepalive >= _MOTOR_KEEPALIVE:
                await loop.run_in_executor(
                    None,
                    lambda d=fwd_direction, s=fwd_speed: self._motors.from_direction(d, s),
                )
                t_last_keepalive = now

            # ── Ultrason (priorité haute — gère le centre) ────────
            if self._ultrasonic:
                r = self._ultrasonic.reading
                cm = r.front.distance_cm
                if (cm is not None and cm < self.obstacle_cm) or (cm is None and r.front.obstacle):
                    us_str = f"{cm:.0f}cm" if cm is not None else "proche"
                    log.info("Patrol US: obstacle frontal %s après %.1fs", us_str, elapsed)
                    return f"ultrason {us_str}"

            # ── Vision latérale G/D ───────────────────────────────
            # Ignorée pendant _VISION_WARMUP (vote stabilisé, pas de lag caméra).
            # Centre intentionnellement ignoré : l'ultrason le couvre mieux.
            if self._vision and elapsed >= _VISION_WARMUP:
                zones = self._vision.zones
                left = zones.get("left", False)
                right = zones.get("right", False)

                if left and right:
                    log.info("Patrol cam: obstacle G+D après %.1fs", elapsed)
                    return "vision:center"
                if left:
                    log.info("Patrol cam: obstacle GAUCHE après %.1fs", elapsed)
                    return "vision:left"
                if right:
                    log.info("Patrol cam: obstacle DROITE après %.1fs", elapsed)
                    return "vision:right"

            await asyncio.sleep(_POLL)

    # ------------------------------------------------------------------
    # Dead reckoning — suivi de cap
    # ------------------------------------------------------------------

    def _record_heading(self) -> None:
        """Mémorise le cap courant dans l'historique des caps explorés."""
        self._heading_history.append(self._heading)
        if len(self._heading_history) > _HEADING_HISTORY_SIZE:
            self._heading_history.pop(0)

    def _apply_turn(self, turn_dir, duration: float) -> None:
        """Met à jour l'estimation de cap après une rotation."""
        delta = _TURN_DEG_PER_SEC * duration
        if turn_dir.value == "right":
            self._heading = (self._heading + delta) % 360.0
        else:
            self._heading = (self._heading - delta) % 360.0

    def _best_turn_dir(self, Direction, duration: float):
        """
        Choisit la direction de rotation qui explore le cap le moins visité.

        Score = distance angulaire minimale aux caps déjà mémorisés.
        On maximise ce score (cap candidat le plus éloigné de l'historique).

        Si les deux candidats sont proches en score (< _TIE_THRESHOLD°),
        on choisit aléatoirement pour briser les boucles périodiques
        (sinon le robot tourne toujours du même côté et fait des cercles).
        """
        delta = _TURN_DEG_PER_SEC * duration
        h_right = (self._heading + delta) % 360.0
        h_left = (self._heading - delta) % 360.0

        if not self._heading_history:
            # Premier évitement : choix aléatoire pour ne pas créer de biais
            return random.choice([Direction.LEFT, Direction.RIGHT])

        def score(h: float) -> float:
            return min(_angular_dist(h, prev) for prev in self._heading_history)

        s_right = score(h_right)
        s_left = score(h_left)

        # Bris d'égalité aléatoire quand les scores sont trop proches
        if abs(s_right - s_left) < _TIE_THRESHOLD:
            chosen = random.choice([Direction.LEFT, Direction.RIGHT])
        else:
            chosen = Direction.RIGHT if s_right > s_left else Direction.LEFT

        log.info(
            "Patrol heading: cap=%.0f° | →droite %.0f°(%.0f°) →gauche %.0f°(%.0f°) | %s",
            self._heading,
            h_right,
            s_right,
            h_left,
            s_left,
            chosen.value,
        )
        return chosen

    # ------------------------------------------------------------------
    # Évitement directionnel
    # ------------------------------------------------------------------

    async def _avoid(self, loop: asyncio.AbstractEventLoop, Direction, obstacle: str) -> None:
        if obstacle.startswith("vision:left"):
            await self._turn(loop, Direction.RIGHT, _TURN_LATERAL, "obstacle gauche → droite")
        elif obstacle.startswith("vision:right"):
            await self._turn(loop, Direction.LEFT, _TURN_LATERAL, "obstacle droite → gauche")
        else:
            # Obstacle frontal : direction intelligente + durée variée pour briser
            # toute périodicité (évite que le robot refasse exactement le même chemin)
            jitter = random.uniform(-_TURN_FRONT_JITTER, _TURN_FRONT_JITTER)
            duration = max(0.4, _TURN_FRONT + jitter)
            turn_dir = self._best_turn_dir(Direction, duration)
            await self._reverse_and_turn(loop, Direction, turn_dir, duration, obstacle)

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
        self._apply_turn(turn_dir, duration)

    async def _reverse_and_turn(
        self,
        loop: asyncio.AbstractEventLoop,
        Direction,
        turn_dir,
        duration: float,
        reason: str,
    ) -> None:
        log.info(
            "Patrol avoid: recul %.2fs + rotation %s %.2fs | %s",
            _REVERSE_FRONT,
            turn_dir.value,
            duration,
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
        await asyncio.sleep(duration)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)
        self._apply_turn(turn_dir, duration)

    # ------------------------------------------------------------------
    # Scan pan-tilt (uniquement en cas de blocage)
    # ------------------------------------------------------------------

    async def _pantilt_scan(self, loop: asyncio.AbstractEventLoop, Direction):
        """
        Balaye les angles pan et évalue chaque direction.
        Retourne Direction.LEFT, Direction.RIGHT, ou None (centre dégagé).
        Appelé UNIQUEMENT lorsque le robot est bloqué.
        """
        log.info("Patrol scan: balayage pan-tilt %s", _SCAN_ANGLES)
        scores: dict[int, float] = {}

        for angle in _SCAN_ANGLES:
            try:
                await loop.run_in_executor(None, lambda a=angle: self._pantilt.goto(a, 0.0))
            except Exception as exc:  # noqa: BLE001
                log.warning("Patrol scan: erreur goto(%d): %s", angle, exc)
                continue

            await asyncio.sleep(_SCAN_SETTLE)

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

            if us_readings:
                score = sum(us_readings) / len(us_readings)
            elif vision_clears:
                score = (sum(vision_clears) / len(vision_clears)) * 300.0
            else:
                score = 0.0

            log.info(
                "Patrol scan: angle=%d° → score=%.1f (us=%d, vis=%d)",
                angle,
                score,
                len(us_readings),
                len(vision_clears),
            )
            scores[angle] = score

        try:
            await loop.run_in_executor(None, self._pantilt.center)
        except Exception as exc:  # noqa: BLE001
            log.warning("Patrol scan: erreur recentrage: %s", exc)

        if not scores:
            log.warning("Patrol scan: aucune mesure — best_turn_dir par défaut")
            return self._best_turn_dir(Direction, _TURN_FRONT)

        best_angle = max(scores, key=lambda a: scores[a])
        best_score = scores[best_angle]
        log.info("Patrol scan: meilleure direction angle=%d° score=%.1f", best_angle, best_score)

        if best_score < self.obstacle_cm * 0.5:
            log.warning("Patrol scan: toutes directions bloquées → best_turn_dir")
            return self._best_turn_dir(Direction, _TURN_FRONT)

        if best_angle < -10:
            return Direction.LEFT
        if best_angle > 10:
            return Direction.RIGHT
        return None  # centre dégagé → reprend l'avance sans tourner
