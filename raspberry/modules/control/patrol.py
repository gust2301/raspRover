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

from modules.control.lidar_avoidance import (
    AvoidanceAction,
    AvoidanceDecision,
    LidarAvoidancePlanner,
)

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

_REVERSE_FRONT = 0.7  # recul avant rotation frontale (s)
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
_HUMAN_CAPTURE_COOLDOWN = 45.0  # délai minimum entre deux captures humaines (s)
_HUMAN_POLL = 0.5  # intervalle de vérification de la détection humaine (s)

_SCAN_ANGLES = (-50, 0, 50)
_SCAN_SETTLE = 0.6
_SCAN_READ_SECS = 0.5

# LIDAR_ONLY : séquences d'échappement engagées pour éviter avant/arrière et toupie.
_LIDAR_REVERSE_COMMIT_S = 0.65
_LIDAR_ESCAPE_TURN_S = 0.90
_LIDAR_MAX_TURN_S = 1.40
_LIDAR_TURN_PAUSE_S = 0.30
_LIDAR_SCAN_PULSE_S = 0.55


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------


class PatrolState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    FORWARD = "forward"
    AVOIDING = "avoiding"
    TURNING_LEFT = "turning_left"
    TURNING_RIGHT = "turning_right"
    BACKING_UP = "backing_up"
    STOPPED = "stopped"
    STUCK = "stuck"


class NavigationMode(str, Enum):
    LEGACY = "LEGACY"
    LIDAR_ONLY = "LIDAR_ONLY"
    HYBRID = "HYBRID"


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
        lidar=None,
        vision=None,
        pantilt=None,
        human_detector=None,
        navigation_mode: str = NavigationMode.HYBRID.value,
        speed: float = _SPEED,
        obstacle_cm: float = _OBSTACLE_CM,
        step_duration: float = 0.7,
        scan_with_pantilt: bool = False,
        stuck_timeout: float = 0.0,
        lidar_stop_cm: float = 32.0,
        lidar_warning_cm: float = 65.0,
        lidar_safe_cm: float = 110.0,
        turn_clearance_cm: float = 55.0,
        rear_clearance_cm: float = 50.0,
        min_decision_duration_ms: int = 1200,
        patrol_forward_speed: float | None = None,
        patrol_turn_speed: float = _TURN_SPEED,
        scan_zone_min_points: int = 2,
        on_incident: Callable[[str, str, str], int] | None = None,
        on_auto_record: Callable[[str, int], Awaitable[None]] | None = None,
        on_capture_photo: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._motors = motors
        self._ultrasonic = ultrasonic
        self._lidar = lidar
        self._vision = vision
        self._pantilt = pantilt
        self._human_detector = human_detector
        try:
            self.navigation_mode = NavigationMode(navigation_mode.upper())
        except ValueError:
            self.navigation_mode = NavigationMode.HYBRID
        self.speed = patrol_forward_speed if patrol_forward_speed is not None else speed
        self.obstacle_cm = obstacle_cm
        self.patrol_turn_speed = patrol_turn_speed
        self._lidar_planner = LidarAvoidancePlanner(
            stop_cm=lidar_stop_cm,
            warning_cm=lidar_warning_cm,
            safe_cm=lidar_safe_cm,
            turn_clearance_cm=turn_clearance_cm,
            rear_clearance_cm=rear_clearance_cm,
            min_decision_duration_ms=min_decision_duration_ms,
            scan_zone_min_points=scan_zone_min_points,
        )
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
        self._human_detection_latched = False
        self._last_decision: str = "idle"
        self._last_decision_reason: str = ""
        self._maneuver_action: AvoidanceAction | None = None
        self._maneuver_started_ts: float = 0.0
        self._forced_turn: AvoidanceAction | None = None
        self._forced_turn_until: float = 0.0
        self._turn_pause_until: float = 0.0
        self._last_escape_turn = AvoidanceAction.TURN_RIGHT
        self._scan_turn = AvoidanceAction.TURN_RIGHT

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
        return {
            "patrol_active": self.active,
            "patrol_state": self._state.value,
            "navigation_mode": self.navigation_mode.value,
            "patrol_decision": self._last_decision,
            "patrol_decision_reason": self._last_decision_reason,
        }

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
        self._human_detection_latched = False
        self._maneuver_action = None
        self._forced_turn = None
        self._forced_turn_until = 0.0
        self._turn_pause_until = 0.0
        self._task = asyncio.create_task(self._run(loop))
        if self._on_incident:
            self._on_incident(
                "patrol_start",
                "info",
                (
                    f"mode={self.navigation_mode.value} speed={self.speed:.2f} "
                    f"obstacle_cm={self.obstacle_cm:.0f}"
                ),
            )
        log.info(
            "Patrouille demarree (mode=%s speed=%.2f obstacle_cm=%.0f)",
            self.navigation_mode.value,
            self.speed,
            self.obstacle_cm,
        )

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

        human_task = asyncio.create_task(self._human_capture_loop())
        try:
            if self.navigation_mode is NavigationMode.LIDAR_ONLY and self._lidar is not None:
                await self._run_lidar_only(loop, Direction)
                return

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
            human_task.cancel()
            try:
                await human_task
            except asyncio.CancelledError:
                pass
            await loop.run_in_executor(None, self._motors.stop)
            self._state = PatrolState.IDLE
            raise

    async def _run_lidar_only(self, loop: asyncio.AbstractEventLoop, Direction) -> None:
        log.info("Patrol LIDAR_ONLY: boucle intelligente 360 demarree")
        keepalive_ts = 0.0
        while True:
            decision = self._lidar_planner.decide(self._lidar.snapshot)
            decision = self._guard_lidar_decision(decision, time.monotonic())
            self._last_decision = decision.action.value
            self._last_decision_reason = decision.reason
            now = time.monotonic()

            if decision.action == AvoidanceAction.STOP:
                self._state = PatrolState.STOPPED
                await loop.run_in_executor(None, self._motors.stop)
                log.warning("Patrol LIDAR_ONLY: STOP - %s", decision.reason)
                await asyncio.sleep(0.25)
                continue

            if decision.action == AvoidanceAction.SCAN_ROTATE:
                self._state = PatrolState.SCANNING
                await loop.run_in_executor(
                    None,
                    lambda: self._motors.from_direction(
                        Direction.RIGHT, self.patrol_turn_speed * 0.45
                    ),
                )
                keepalive_ts = now
                await asyncio.sleep(0.25)
                continue

            if decision.action == AvoidanceAction.BACK_UP:
                self._state = PatrolState.BACKING_UP
                if self._rear_blocked():
                    await loop.run_in_executor(None, self._motors.stop)
                    self._last_decision = AvoidanceAction.STOP.value
                    self._last_decision_reason = "obstacle arrière, recul interdit"
                    await asyncio.sleep(_POLL)
                    continue
                await loop.run_in_executor(
                    None,
                    lambda: self._motors.from_direction(Direction.BACKWARD, self.speed * 0.65),
                )
                keepalive_ts = now
                await asyncio.sleep(_POLL)
                continue

            if decision.action == AvoidanceAction.TURN_LEFT:
                self._state = PatrolState.TURNING_LEFT
                await loop.run_in_executor(
                    None,
                    lambda: self._motors.from_direction(Direction.LEFT, self.patrol_turn_speed),
                )
                keepalive_ts = now
                await asyncio.sleep(_POLL)
                continue

            if decision.action == AvoidanceAction.TURN_RIGHT:
                self._state = PatrolState.TURNING_RIGHT
                await loop.run_in_executor(
                    None,
                    lambda: self._motors.from_direction(Direction.RIGHT, self.patrol_turn_speed),
                )
                keepalive_ts = now
                await asyncio.sleep(_POLL)
                continue

            if decision.action == AvoidanceAction.ARC_LEFT:
                self._state = PatrolState.AVOIDING
                await loop.run_in_executor(
                    None,
                    lambda: self._motors.arc(self.speed * 0.65, -0.28),
                )
                keepalive_ts = now
                await asyncio.sleep(_POLL)
                continue

            if decision.action == AvoidanceAction.ARC_RIGHT:
                self._state = PatrolState.AVOIDING
                await loop.run_in_executor(
                    None,
                    lambda: self._motors.arc(self.speed * 0.65, 0.28),
                )
                keepalive_ts = now
                await asyncio.sleep(_POLL)
                continue

            self._state = PatrolState.FORWARD
            speed = (
                self.speed * 0.7 if decision.action == AvoidanceAction.SLOW_FORWARD else self.speed
            )
            if now - keepalive_ts >= _MOTOR_KEEPALIVE:
                await loop.run_in_executor(
                    None,
                    lambda s=speed: self._motors.from_direction(Direction.FORWARD, s),
                )
                keepalive_ts = now
            await asyncio.sleep(_POLL)

    def _guard_lidar_decision(self, decision: AvoidanceDecision, now: float) -> AvoidanceDecision:
        """Engage les manœuvres LIDAR assez longtemps sans sacrifier le STOP sécurité.

        Un recul est toujours suivi d'une rotation franche. Les rotations sont
        plafonnées et séparées par une pause, ce qui empêche le rover de rester
        en marche avant/arrière ou de tourner indéfiniment sur place.
        """
        if decision.action == AvoidanceAction.STOP:
            self._remember_maneuver(decision.action, now)
            self._forced_turn = None
            return decision

        if now < self._turn_pause_until:
            return self._override_decision(decision, AvoidanceAction.STOP, "pause de réévaluation")

        if self._forced_turn is not None:
            if now < self._forced_turn_until:
                return self._override_decision(
                    decision, self._forced_turn, "rotation engagée après recul"
                )
            self._forced_turn = None
            self._turn_pause_until = now + _LIDAR_TURN_PAUSE_S
            self._remember_maneuver(AvoidanceAction.STOP, now)
            return self._override_decision(decision, AvoidanceAction.STOP, "fin rotation engagée")

        if self._maneuver_action == AvoidanceAction.BACK_UP:
            elapsed = now - self._maneuver_started_ts
            if elapsed < _LIDAR_REVERSE_COMMIT_S:
                return self._override_decision(
                    decision, AvoidanceAction.BACK_UP, "recul engagé anti-oscillation"
                )
            turn = self._choose_escape_turn(decision)
            self._forced_turn = turn
            self._forced_turn_until = now + _LIDAR_ESCAPE_TURN_S
            self._last_escape_turn = turn
            self._remember_maneuver(turn, now)
            return self._override_decision(decision, turn, "sortie latérale après recul")

        if decision.action == AvoidanceAction.BACK_UP:
            self._remember_maneuver(decision.action, now)
            return decision

        if decision.action == AvoidanceAction.SCAN_ROTATE:
            if self._maneuver_action != AvoidanceAction.SCAN_ROTATE:
                self._scan_turn = (
                    AvoidanceAction.TURN_LEFT
                    if self._scan_turn == AvoidanceAction.TURN_RIGHT
                    else AvoidanceAction.TURN_RIGHT
                )
                self._remember_maneuver(AvoidanceAction.SCAN_ROTATE, now)
            if now - self._maneuver_started_ts >= _LIDAR_SCAN_PULSE_S:
                self._turn_pause_until = now + _LIDAR_TURN_PAUSE_S
                self._remember_maneuver(AvoidanceAction.STOP, now)
                return self._override_decision(decision, AvoidanceAction.STOP, "pause après scan")
            return self._override_decision(decision, self._scan_turn, "impulsion de scan alternée")

        turning = decision.action in (
            AvoidanceAction.TURN_LEFT,
            AvoidanceAction.TURN_RIGHT,
            AvoidanceAction.ARC_LEFT,
            AvoidanceAction.ARC_RIGHT,
        )
        if turning and self._maneuver_action == decision.action:
            if now - self._maneuver_started_ts >= _LIDAR_MAX_TURN_S:
                self._turn_pause_until = now + _LIDAR_TURN_PAUSE_S
                self._remember_maneuver(AvoidanceAction.STOP, now)
                return self._override_decision(
                    decision, AvoidanceAction.STOP, "rotation maximale atteinte"
                )
        elif self._maneuver_action != decision.action:
            self._remember_maneuver(decision.action, now)
        return decision

    def _choose_escape_turn(self, decision: AvoidanceDecision) -> AvoidanceAction:
        zones = decision.zones or {}
        left_score = sum(zones[name].score for name in ("front_left", "left") if name in zones)
        right_score = sum(zones[name].score for name in ("front_right", "right") if name in zones)
        if abs(left_score - right_score) < 20.0:
            return (
                AvoidanceAction.TURN_LEFT
                if self._last_escape_turn == AvoidanceAction.TURN_RIGHT
                else AvoidanceAction.TURN_RIGHT
            )
        return AvoidanceAction.TURN_LEFT if left_score > right_score else AvoidanceAction.TURN_RIGHT

    def _remember_maneuver(self, action: AvoidanceAction, now: float) -> None:
        self._maneuver_action = action
        self._maneuver_started_ts = now

    @staticmethod
    def _override_decision(
        decision: AvoidanceDecision, action: AvoidanceAction, reason: str
    ) -> AvoidanceDecision:
        return AvoidanceDecision(
            action=action,
            reason=f"{reason} ({decision.reason})",
            front_cm=decision.front_cm,
            target_angle_deg=decision.target_angle_deg,
            confidence=decision.confidence,
            zones=decision.zones,
        )

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

    async def _human_capture_loop(self) -> None:
        """Tâche de fond : surveille la détection humaine tout au long de la patrouille.

        Tourne en parallèle du patrol loop principal — ne touche pas aux moteurs.
        Déclenche une capture photo + incident dès qu'une personne est détectée,
        quelle que soit la phase de patrouille (avance, évitement, scan).
        """
        while True:
            await asyncio.sleep(_HUMAN_POLL)
            if not self._human_detector:
                continue
            now = time.monotonic()
            if not self._should_capture_human(self._human_detector.person_detected, now):
                continue
            incident_id = -1
            if self._on_incident:
                try:
                    incident_id = self._on_incident(
                        "human_detected_patrol",
                        "warning",
                        "Personne détectée pendant la patrouille",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Patrol human incident error: %s", exc)
            self._trigger_human_capture(incident_id)
            log.info("Patrol: personne détectée → photo déclenchée (incident=%d)", incident_id)

    def _should_capture_human(self, detected: bool, now: float) -> bool:
        """Capture once per encounter, with a cooldown between distinct encounters."""
        if not detected:
            self._human_detection_latched = False
            return False
        if self._human_detection_latched:
            return False
        self._human_detection_latched = True
        if now - self._last_human_capture_ts < _HUMAN_CAPTURE_COOLDOWN:
            return False
        self._last_human_capture_ts = now
        return True

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
            if self._uses_lidar():
                decision = self._lidar_planner.decide(self._lidar.snapshot)
                if decision.action == AvoidanceAction.STOP:
                    log.warning("Patrol LIDAR: stop securite - %s", decision.reason)
                    return f"lidar:stop:{decision.reason}"
                if decision.action == AvoidanceAction.CLEAR:
                    pass
                elif decision.action in (AvoidanceAction.ARC_LEFT, AvoidanceAction.ARC_RIGHT):
                    steering = -0.32 if decision.action == AvoidanceAction.ARC_LEFT else 0.32
                    await loop.run_in_executor(
                        None,
                        lambda s=fwd_speed, st=steering: self._motors.arc(s, st),
                    )
                    t_last_keepalive = now
                elif decision.action == AvoidanceAction.TURN_LEFT:
                    log.info("Patrol LIDAR: obstacle - %s", decision.reason)
                    return f"lidar:left:{decision.reason}"
                elif decision.action == AvoidanceAction.TURN_RIGHT:
                    log.info("Patrol LIDAR: obstacle - %s", decision.reason)
                    return f"lidar:right:{decision.reason}"

            # ── Ultrason (frontal) ────────────────────────────────────
            if self._ultrasonic and self.navigation_mode is not NavigationMode.LIDAR_ONLY:
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
                depth_zones = getattr(self._vision, "depth_zones", {})
                if depth_zones.get("center", False):
                    log.info("Patrol OAK: obstacle 3D CENTRE après %.1fs", elapsed)
                    return "depth:center"
                if depth_zones.get("left", False) and depth_zones.get("right", False):
                    return "depth:center"
                if depth_zones.get("left", False):
                    return "depth:left"
                if depth_zones.get("right", False):
                    return "depth:right"

            if (
                self._vision
                and elapsed >= _VISION_WARMUP
                and self.navigation_mode is not NavigationMode.LIDAR_ONLY
            ):
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

    def _uses_lidar(self) -> bool:
        return self._lidar is not None and self.navigation_mode in (
            NavigationMode.LIDAR_ONLY,
            NavigationMode.HYBRID,
        )

    def _rear_blocked(self) -> bool:
        """Fail-safe directionnel utilisé avant et pendant chaque recul."""
        if self._lidar is not None:
            rear_cm = self._lidar.snapshot.rear_distance_cm
            if rear_cm is not None and rear_cm < self._lidar_planner.rear_clearance_cm:
                return True
        return bool(self._ultrasonic and self._ultrasonic.reading.rear.obstacle)

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

        if obstacle.startswith("lidar:stop"):
            log.warning("Patrol avoid: LIDAR indisponible, arret de securite")
            await loop.run_in_executor(None, self._motors.stop)
            await asyncio.sleep(0.5)

        elif obstacle.startswith("lidar:left"):
            self._last_turn_dir = Direction.LEFT
            front_cm = self._lidar.snapshot.front_distance_cm if self._lidar else None
            duration = 0.85 if front_cm is not None and front_cm < self.obstacle_cm else 0.55
            await self._turn(loop, Direction.LEFT, duration, obstacle)

        elif obstacle.startswith("lidar:right"):
            self._last_turn_dir = Direction.RIGHT
            front_cm = self._lidar.snapshot.front_distance_cm if self._lidar else None
            duration = 0.85 if front_cm is not None and front_cm < self.obstacle_cm else 0.55
            await self._turn(loop, Direction.RIGHT, duration, obstacle)

        elif obstacle.startswith("vision:left"):
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
        # Phase recul — surveille continuellement le secteur arrière.
        if self._rear_blocked():
            log.warning("Patrol avoid: recul annulé, obstacle arrière")
            await loop.run_in_executor(None, self._motors.stop)
            return
        await loop.run_in_executor(
            None, lambda s=spd: self._motors.from_direction(Direction.BACKWARD, s)
        )
        reverse_end = time.monotonic() + _REVERSE_FRONT
        while time.monotonic() < reverse_end:
            if self._rear_blocked():
                log.warning("Patrol avoid: obstacle arrière détecté pendant le recul")
                break
            await asyncio.sleep(_POLL)
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
