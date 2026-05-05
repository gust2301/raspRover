"""
Contrôleur de patrouille autonome.

Comportement :
  - Avance en continu jusqu'à détection d'obstacle (ultrason + vision).
  - Keepalive moteur toutes les 0.4 s (watchdog MotorController = 1 s).
  - À la détection d'un obstacle :
      * Gauche uniquement  → tourne droite
      * Droite uniquement  → tourne gauche
      * Centre / frontal   → recul + tourne (alternance G/D, angle aléatoire)
  - Reprend l'avance immédiatement après l'évitement.

Evitement anti-boucle :
  - Direction : alterne gauche/droite à chaque obstacle frontal.
  - Angle     : aléatoire entre _TURN_FRONT_MIN et _TURN_FRONT_MAX.
    → Le robot ne refait jamais exactement le même chemin.

Détection de blocage :
  - Après _STUCK_SCAN_THRESHOLD évitements rapides, scan pan-tilt
    pour trouver la sortie la plus dégagée.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import random
import time
from collections.abc import Awaitable, Callable
from enum import Enum

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SPEED = 0.3  # vitesse d'avance (0-1)
_TURN_SPEED = 0.42  # vitesse de rotation
_OBSTACLE_CM = 40.0  # seuil ultrason (cm)
_POLL = 0.05  # intervalle de surveillance (s)

# Rotation latérale (obstacle gauche ou droite)
_TURN_LATERAL = 0.75  # s

# Rotation frontale : angle aléatoire entre MIN et MAX
# À ~100 °/s cela donne ~60° à 160° → trajectoires imprévisibles, pas de cercles
_TURN_FRONT_MIN = 0.60  # s (~60°)
_TURN_FRONT_MAX = 1.60  # s (~160°)

_REVERSE_FRONT = 0.4  # recul avant rotation frontale (s)
_TURN_PAUSE = 0.15  # pause moteurs entre phases (s)

# Keepalive : MotorController coupe après watchdog_s=1 s sans commande
_MOTOR_KEEPALIVE = 0.4  # s

# Vision : délai court avant activation (laisse 2-3 frames de vote se stabiliser)
# Ne pas mettre trop long : à vitesse 0.3, chaque seconde = ~15 cm parcourus
_VISION_WARMUP = 0.3  # s

# Détection de blocage → scan pan-tilt
_MIN_FREE_SECS = 1.5
_STUCK_SCAN_THRESHOLD = 3

# Auto-enregistrement vidéo sur incident
_AUTO_RECORD_DURATION = 15.0  # secondes d'enregistrement par incident
_AUTO_RECORD_COOLDOWN = 30.0  # délai minimum entre deux enregistrements (s)

# Détection humaine pendant la patrouille
_HUMAN_DETECT_PAUSE = 4.0  # s d'arrêt moteurs pour suivre + capturer
_HUMAN_CAPTURE_COOLDOWN = 45.0  # délai minimum entre deux captures humaines (s)
_HUMAN_TRACK_KP_PAN = 40.0  # gain P pan (même valeur que TrackerController)
_HUMAN_TRACK_KP_TILT = 30.0  # gain P tilt
_HUMAN_TRACK_DEAD_ZONE = 0.05  # zone morte normalisée

_SCAN_ANGLES = (-50, 0, 50)
_SCAN_SETTLE = 0.6
_SCAN_READ_SECS = 0.5


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
    Patrouille autonome : avance librement, évite les obstacles.

    Parameters
    ----------
    motors       : MotorController
    ultrasonic   : UltrasonicSensor | None
    vision       : VisionObstacleDetector | None
    pantilt      : PanTiltController | None  (scan de déblocage)
    speed        : float  vitesse d'avance (0-1)
    obstacle_cm  : float  seuil ultrason (cm)
    step_duration, scan_with_pantilt, stuck_timeout : ignorés (rétrocompat)
    """

    def __init__(
        self,
        motors,
        ultrasonic=None,
        vision=None,
        pantilt=None,
        human_detector=None,
        speed: float = _SPEED,
        obstacle_cm: float = _OBSTACLE_CM,
        step_duration: float = 0.7,
        scan_with_pantilt: bool = False,
        stuck_timeout: float = 0.0,
        on_incident: Callable[[str, str, str], int] | None = None,
        on_auto_record: Callable[[str, int], Awaitable[None]] | None = None,
        on_capture_photo: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._motors = motors
        self._ultrasonic = ultrasonic
        self._vision = vision
        self._pantilt = pantilt
        self._human_detector = human_detector
        self.speed = speed
        self.obstacle_cm = obstacle_cm
        self._on_incident = on_incident
        self._on_auto_record = on_auto_record
        self._on_capture_photo = on_capture_photo

        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._state: PatrolState = PatrolState.IDLE
        self._avoidance_count: int = 0  # alternance G/D
        self._short_move_count: int = 0  # compteur blocage
        self._last_turn_dir = None  # Direction | None — conservé entre évitements
        self._last_record_ts: float = 0.0  # timestamp du dernier auto-enregistrement
        self._last_human_capture_ts: float = 0.0  # timestamp de la dernière capture humaine

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
        self._last_turn_dir = None
        self._last_record_ts = 0.0
        self._last_human_capture_ts = 0.0
        self._task = asyncio.create_task(self._run(loop))
        if self._on_incident:
            self._on_incident(
                "patrol_start", "info", f"speed={self.speed:.2f} obstacle_cm={self.obstacle_cm:.0f}"
            )
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
        if self._on_incident:
            self._on_incident("patrol_stop", "info", None)
        log.info("Patrouille arrêtée")

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------

    async def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        from modules.control.motor_controller import Direction

        try:
            while True:
                # ── Avance ────────────────────────────────────────────
                self._state = PatrolState.FORWARD
                spd = self.speed
                await loop.run_in_executor(
                    None, lambda s=spd: self._motors.from_direction(Direction.FORWARD, s)
                )
                log.info("Patrol: FORWARD (vitesse=%.2f)", spd)

                t_free_start = time.monotonic()
                obstacle = await self._monitor_until_obstacle(loop, Direction.FORWARD, spd)

                # ── Évitement ─────────────────────────────────────────
                if obstacle:
                    free_secs = time.monotonic() - t_free_start
                    self._state = PatrolState.AVOIDING
                    await loop.run_in_executor(None, self._motors.stop)
                    log.info("Patrol: OBSTACLE — %s (libre=%.1fs)", obstacle, free_secs)

                    # Journal + auto-enregistrement
                    incident_id = -1
                    if self._on_incident:
                        incident_id = self._on_incident(
                            "obstacle",
                            "warning",
                            f"{obstacle} après {free_secs:.1f}s de déplacement libre",
                        )
                    self._trigger_auto_record(incident_id)

                    if free_secs < _MIN_FREE_SECS:
                        self._short_move_count += 1
                        log.info(
                            "Patrol: mouvement court, compteur blocage=%d/%d",
                            self._short_move_count,
                            _STUCK_SCAN_THRESHOLD,
                        )
                    else:
                        self._short_move_count = 0

                    if self._short_move_count >= _STUCK_SCAN_THRESHOLD and self._pantilt:
                        log.warning("Patrol: BLOQUÉ → scan pan-tilt")
                        self._state = PatrolState.STUCK
                        if self._on_incident:
                            self._on_incident(
                                "patrol_stuck", "critical", f"count={self._short_move_count}"
                            )
                        self._short_move_count = 0
                        best_dir = await self._pantilt_scan(loop, Direction)
                        if best_dir is not None:
                            dur = random.uniform(_TURN_FRONT_MIN, _TURN_FRONT_MAX)
                            await self._turn(loop, best_dir, dur, "sortie scan")
                    else:
                        await self._avoid(loop, Direction, obstacle, free_secs)

        except asyncio.CancelledError:
            await loop.run_in_executor(None, self._motors.stop)
            self._state = PatrolState.IDLE
            raise

    # ------------------------------------------------------------------
    # Auto-enregistrement
    # ------------------------------------------------------------------

    def _trigger_auto_record(self, incident_id: int) -> None:
        """Démarre un enregistrement automatique si le cooldown est passé."""
        if self._on_auto_record is None:
            return
        now = time.monotonic()
        if now - self._last_record_ts < _AUTO_RECORD_COOLDOWN:
            return
        self._last_record_ts = now
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
        path = f"/tmp/auto_video_{ts}.mp4"
        asyncio.create_task(self._on_auto_record(path, incident_id))
        log.info("Patrol: auto-enregistrement démarré → %s", path)

    # ------------------------------------------------------------------
    # Détection humaine pendant la patrouille
    # ------------------------------------------------------------------

    async def _handle_human_pause(self, loop: asyncio.AbstractEventLoop) -> None:
        """Arrête le robot, suit la personne avec le pan-tilt, capture une photo, reprend."""
        log.info("Patrol: humain détecté → pause %.1fs + tracking", _HUMAN_DETECT_PAUSE)
        self._last_human_capture_ts = time.monotonic()

        await loop.run_in_executor(None, self._motors.stop)

        incident_id = -1
        if self._on_incident:
            incident_id = self._on_incident(
                "human_detected_patrol",
                "warning",
                "Personne détectée pendant la patrouille",
            )
        self._trigger_human_capture(incident_id)

        # Suivi pan-tilt pendant la pause
        t_end = time.monotonic() + _HUMAN_DETECT_PAUSE
        while time.monotonic() < t_end:
            if self._pantilt and self._human_detector:
                target = self._human_detector.best_target
                if target:
                    cx, cy, _ = target
                    pan, tilt = self._pantilt.position
                    error_x = cx - 0.5
                    error_y = cy - 0.5
                    new_pan = (
                        pan + _HUMAN_TRACK_KP_PAN * error_x
                        if abs(error_x) > _HUMAN_TRACK_DEAD_ZONE
                        else pan
                    )
                    new_tilt = (
                        tilt - _HUMAN_TRACK_KP_TILT * error_y
                        if abs(error_y) > _HUMAN_TRACK_DEAD_ZONE
                        else tilt
                    )
                    if new_pan != pan or new_tilt != tilt:
                        try:
                            await loop.run_in_executor(
                                None, lambda p=new_pan, t=new_tilt: self._pantilt.goto(p, t)
                            )
                        except Exception as exc:  # noqa: BLE001
                            log.debug("Patrol human track goto error: %s", exc)
            await asyncio.sleep(_POLL)

        if self._pantilt:
            try:
                await loop.run_in_executor(None, self._pantilt.center)
            except Exception as exc:  # noqa: BLE001
                log.debug("Patrol human track center error: %s", exc)

    def _trigger_human_capture(self, incident_id: int) -> None:
        """Déclenche une capture photo de la personne détectée."""
        if self._on_capture_photo is None:
            return
        asyncio.create_task(self._on_capture_photo(incident_id))
        log.info("Patrol: capture photo humaine déclenchée (incident=%d)", incident_id)

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
        Rafraîchit la commande moteur toutes les _MOTOR_KEEPALIVE secondes.

        Vision : activée après _VISION_WARMUP secondes (vote stabilisé).
        Zones gauche et droite seulement — l'ultrason gère le centre.
        """
        t_start = time.monotonic()
        t_last_keepalive = t_start

        while True:
            now = time.monotonic()
            elapsed = now - t_start

            # ── Keepalive moteur ──────────────────────────────────────
            if now - t_last_keepalive >= _MOTOR_KEEPALIVE:
                await loop.run_in_executor(
                    None,
                    lambda d=fwd_direction, s=fwd_speed: self._motors.from_direction(d, s),
                )
                t_last_keepalive = now

            # ── Ultrason (frontal) ────────────────────────────────────
            if self._ultrasonic:
                r = self._ultrasonic.reading
                cm = r.front.distance_cm
                if (cm is not None and cm < self.obstacle_cm) or (cm is None and r.front.obstacle):
                    us_str = f"{cm:.0f}cm" if cm is not None else "proche"
                    log.info("Patrol US: obstacle %s après %.1fs", us_str, elapsed)
                    return f"ultrason {us_str}"

            # ── Vision latérale G/D (après warmup) ───────────────────
            # Centre volontairement ignoré : l'ultrason le couvre.
            # Warmup court (0.3 s) pour laisser le vote se stabiliser
            # sans risquer de percuter un obstacle non vu pendant trop longtemps.
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

            # ── Détection humaine (tracking automatique + capture) ────
            if self._human_detector and self._human_detector.person_detected:
                now_h = time.monotonic()
                if now_h - self._last_human_capture_ts >= _HUMAN_CAPTURE_COOLDOWN:
                    await self._handle_human_pause(loop)
                    # Reprise immédiate : renvoie la commande moteur
                    await loop.run_in_executor(
                        None,
                        lambda d=fwd_direction, s=fwd_speed: self._motors.from_direction(d, s),
                    )
                    t_last_keepalive = time.monotonic()

            await asyncio.sleep(_POLL)

    # ------------------------------------------------------------------
    # Évitement directionnel
    # ------------------------------------------------------------------

    def _next_turn_dir(self, Direction, consecutive: bool = False):
        """
        consecutive=True  → déplacement court avant l'obstacle : garder la même
                            direction (ne pas revenir en arrière) + angle max.
        consecutive=False → déplacement suffisant : alterner G/D normalement.
        """
        if consecutive and self._last_turn_dir is not None:
            log.info(
                "Patrol avoid: mouvement court → même direction %s (pas d'alternance)",
                self._last_turn_dir.value,
            )
            return self._last_turn_dir
        self._avoidance_count += 1
        d = Direction.LEFT if self._avoidance_count % 2 == 0 else Direction.RIGHT
        self._last_turn_dir = d
        return d

    async def _avoid(
        self,
        loop: asyncio.AbstractEventLoop,
        Direction,
        obstacle: str,
        free_secs: float = 999.0,
    ) -> None:
        consecutive = free_secs < _MIN_FREE_SECS

        if obstacle.startswith("vision:left"):
            self._last_turn_dir = Direction.RIGHT
            await self._turn(loop, Direction.RIGHT, _TURN_LATERAL, "obstacle gauche → droite")

        elif obstacle.startswith("vision:right"):
            self._last_turn_dir = Direction.LEFT
            await self._turn(loop, Direction.LEFT, _TURN_LATERAL, "obstacle droite → gauche")

        else:
            # Frontal
            turn_dir = self._next_turn_dir(Direction, consecutive)
            # Déplacement court → angle maximum pour sortir du coin sans demi-tour
            duration = (
                _TURN_FRONT_MAX if consecutive else random.uniform(_TURN_FRONT_MIN, _TURN_FRONT_MAX)
            )
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
        # Surveille l'ultrason pendant la rotation : stoppe dès qu'un obstacle
        # est très proche (robot en train de pousser contre un mur).
        t_end = time.monotonic() + duration
        while time.monotonic() < t_end:
            if self._ultrasonic:
                r = self._ultrasonic.reading
                cm = r.front.distance_cm
                if cm is not None and cm < self.obstacle_cm * 0.5:
                    log.info("Patrol turn: obstacle proche (%.0f cm) → rotation écourtée", cm)
                    break
            await asyncio.sleep(_POLL)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)

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
        # Phase recul — durée fixe, pas de check capteur (obstacle est devant)
        await loop.run_in_executor(
            None, lambda s=spd: self._motors.from_direction(Direction.BACKWARD, s)
        )
        await asyncio.sleep(_REVERSE_FRONT)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)
        # Phase rotation — stoppe si l'US détecte quelque chose de très proche
        await loop.run_in_executor(
            None, lambda d=turn_dir: self._motors.from_direction(d, _TURN_SPEED)
        )
        t_end = time.monotonic() + duration
        while time.monotonic() < t_end:
            if self._ultrasonic:
                r = self._ultrasonic.reading
                cm = r.front.distance_cm
                if cm is not None and cm < self.obstacle_cm * 0.5:
                    log.info(
                        "Patrol reverse+turn: obstacle proche (%.0f cm) → rotation écourtée", cm
                    )
                    break
            await asyncio.sleep(_POLL)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(_TURN_PAUSE)

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
            return Direction.RIGHT

        best_angle = max(scores, key=lambda a: scores[a])
        best_score = scores[best_angle]
        log.info("Patrol scan: meilleure direction angle=%d° score=%.1f", best_angle, best_score)

        if best_score < self.obstacle_cm * 0.5:
            # Toutes directions bloquées : alternance G/D
            self._avoidance_count += 1
            return Direction.LEFT if self._avoidance_count % 2 == 0 else Direction.RIGHT

        if best_angle < -10:
            return Direction.LEFT
        if best_angle > 10:
            return Direction.RIGHT
        return None
