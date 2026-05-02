"""
Contrôleur de patrouille autonome — scan L/C/D + évitement directionnel.

Boucle principale :
  SCANNING  → analyse ultrason + caméra 3 zones (+ sweep pan-tilt si dispo)
  FORWARD   → avance par étapes, surveillance US en continu
  AVOIDING  → évitement directionnel (gauche, centre, droite)
  STUCK     → recul + rotation si angle mort persistant

Logs complets à chaque cycle :
  US=Xcm cam[L=obs C=clear R=clear] → avoid_right | raison: obstacle caméra gauche
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

_SPEED = 0.3  # vitesse d'avance
_TURN_SPEED = 0.42  # vitesse de rotation
_OBSTACLE_CM = 40.0  # seuil ultrason (cm)
_STEP_DURATION = 0.7  # durée d'une étape d'avance (s)
_TURN_SHORT = 0.75  # rotation latérale (obstacle G ou D)
_TURN_CENTER = 0.9  # rotation frontale (obstacle centre ou les deux)
_REVERSE_DUR = 0.45  # recul avant rotation (obstacle centre)
_SCAN_PAUSE = 0.08  # pause entre scan et mouvement (s)
_LOOP_POLL = 0.05  # intervalle de polling pendant l'avance (s)

# Pan-tilt scan
_PAN_ANGLE = 28  # degrés de rotation caméra pour le scan
_PAN_SETTLE = 0.35  # temps de stabilisation après rotation caméra (s)

# Anti-blocage angle mort
_STUCK_TIMEOUT = 3.5  # s en FORWARD sans obstacle → coincé
_STUCK_REVERSE = 0.5  # recul quand coincé
_STUCK_TURN = 1.2  # rotation longue quand coincé


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------


class PatrolState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    FORWARD = "forward"
    AVOIDING = "avoiding"
    STUCK = "stuck"


# ---------------------------------------------------------------------------
# Résultat de scan
# ---------------------------------------------------------------------------


class _ScanResult:
    __slots__ = ("us_cm", "us_obstacle", "left", "center", "right", "decision", "reason")

    def __init__(
        self,
        us_cm: float | None,
        us_obstacle: bool,
        left: bool,
        center: bool,
        right: bool,
    ) -> None:
        self.us_cm = us_cm
        self.us_obstacle = us_obstacle
        self.left = left
        self.center = center
        self.right = right
        self.decision, self.reason = self._decide()

    def _decide(self) -> tuple[str, str]:
        us_cm = self.us_cm
        us_str = f"{us_cm:.0f}cm" if us_cm is not None else "N/A"

        if self.us_obstacle:
            return "avoid_center", f"ultrason frontal {us_str}"
        if self.center and self.left and self.right:
            return "avoid_center", "obstacle partout (caméra)"
        if self.center:
            return "avoid_center", "obstacle caméra centre"
        if self.left and self.right:
            return "avoid_center", "obstacle caméra gauche+droite"
        if self.left:
            return "avoid_right", "obstacle caméra gauche"
        if self.right:
            return "avoid_left", "obstacle caméra droite"
        return "forward", "voie libre"

    def log_str(self) -> str:
        us_str = f"{self.us_cm:.0f}cm" if self.us_cm is not None else "N/A"
        sl = "obs" if self.left else "ok"
        sc = "obs" if self.center else "ok"
        sr = "obs" if self.right else "ok"
        return f"US={us_str} cam[L={sl} C={sc} R={sr}] → {self.decision} | {self.reason}"


# ---------------------------------------------------------------------------
# Contrôleur
# ---------------------------------------------------------------------------


class PatrolController:
    """
    Patrouille autonome avec scan directionnel.

    Parameters
    ----------
    motors       : MotorController
    ultrasonic   : UltrasonicSensor | None
    vision       : VisionObstacleDetector | None
    pantilt      : PanTiltController | None  — scan caméra L/C/D si disponible
    speed        : float   vitesse d'avance (0-1)
    obstacle_cm  : float   seuil ultrason déclenchant l'évitement (cm)
    step_duration: float   durée d'une étape d'avance (s)
    scan_with_pantilt : bool  effectuer un sweep caméra avant d'avancer
    stuck_timeout: float   durée FORWARD sans obstacle → angle mort (s)
    """

    def __init__(
        self,
        motors,
        ultrasonic=None,
        vision=None,
        pantilt=None,
        speed: float = _SPEED,
        obstacle_cm: float = _OBSTACLE_CM,
        step_duration: float = _STEP_DURATION,
        scan_with_pantilt: bool = False,
        stuck_timeout: float = _STUCK_TIMEOUT,
    ) -> None:
        self._motors = motors
        self._ultrasonic = ultrasonic
        self._vision = vision
        self._pantilt = pantilt
        self.speed = speed
        self.obstacle_cm = obstacle_cm
        self.step_duration = step_duration
        self.scan_with_pantilt = scan_with_pantilt and pantilt is not None
        self.stuck_timeout = stuck_timeout

        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._state: PatrolState = PatrolState.IDLE

        self._forward_since: float | None = None
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
        self._forward_since = None
        self._avoidance_count = 0
        self._task = asyncio.create_task(self._run(loop))
        log.info(
            "Patrouille démarrée — speed=%.2f step=%.1fs stuck=%.1fs pantilt_scan=%s",
            self.speed,
            self.step_duration,
            self.stuck_timeout,
            self.scan_with_pantilt,
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
        self._forward_since = None
        await loop.run_in_executor(None, self._motors.stop)
        if self._pantilt:
            try:
                await loop.run_in_executor(None, self._pantilt.center)
            except Exception:  # noqa: BLE001
                pass
        log.info("Patrouille arrêtée")

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------

    async def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        from modules.control.motor_controller import Direction

        try:
            while True:
                # ── SCAN ──────────────────────────────────────────────
                self._state = PatrolState.SCANNING
                scan = await self._do_scan(loop)
                log.info("Patrol scan: %s", scan.log_str())

                # ── DÉCISION ──────────────────────────────────────────
                if scan.decision == "avoid_center":
                    self._forward_since = None
                    self._state = PatrolState.AVOIDING
                    await self._avoid_center(loop, Direction)

                elif scan.decision == "avoid_right":
                    self._forward_since = None
                    self._state = PatrolState.AVOIDING
                    await self._avoid_lateral(loop, Direction, Direction.RIGHT, scan.reason)

                elif scan.decision == "avoid_left":
                    self._forward_since = None
                    self._state = PatrolState.AVOIDING
                    await self._avoid_lateral(loop, Direction, Direction.LEFT, scan.reason)

                else:
                    # Voie libre → avance d'une étape
                    now = time.monotonic()
                    if self._forward_since is None:
                        self._forward_since = now

                    # Détection d'angle mort (FORWARD trop long sans obstacle)
                    if (now - self._forward_since) > self.stuck_timeout:
                        elapsed = now - self._forward_since
                        self._forward_since = None
                        self._state = PatrolState.STUCK
                        log.warning(
                            "Patrol: STUCK détecté (%.1fs FORWARD sans obstacle) → recul",
                            elapsed,
                        )
                        await self._avoid_stuck(loop, Direction)
                    else:
                        self._state = PatrolState.FORWARD
                        await self._step_forward(loop, Direction)

        except asyncio.CancelledError:
            await loop.run_in_executor(None, self._motors.stop)
            self._state = PatrolState.IDLE
            raise

    # ------------------------------------------------------------------
    # Scan directionnel
    # ------------------------------------------------------------------

    async def _do_scan(self, loop: asyncio.AbstractEventLoop) -> _ScanResult:
        """Analyse ultrason + caméra 3 zones (avec sweep pan-tilt si activé)."""
        # Ultrason
        us_cm: float | None = None
        us_obstacle = False
        if self._ultrasonic:
            r = self._ultrasonic.reading
            us_cm = r.front.distance_cm
            if us_cm is not None:
                us_obstacle = us_cm < self.obstacle_cm
            else:
                us_obstacle = r.front.obstacle

        # Vision — sweep pan-tilt ou lecture des zones courantes
        left = center = right = False

        if self._vision:
            if self.scan_with_pantilt and self._pantilt:
                zones = await self._pantilt_scan(loop)
            else:
                zones = self._vision.zones
            left = zones.get("left", False)
            center = zones.get("center", False)
            right = zones.get("right", False)

        return _ScanResult(us_cm, us_obstacle, left, center, right)

    async def _pantilt_scan(self, loop: asyncio.AbstractEventLoop) -> dict[str, bool]:
        """
        Sweep caméra gauche → centre → droite.
        Retourne les zones obstacles combinées.
        """
        collected: dict[str, dict[str, bool]] = {}

        for pan_deg, key in [
            (-_PAN_ANGLE, "look_left"),
            (0, "look_center"),
            (_PAN_ANGLE, "look_right"),
        ]:
            # Pan
            await loop.run_in_executor(
                None,
                lambda p=pan_deg: self._pantilt.goto(p, None),  # type: ignore[union-attr]
            )
            # Attente image fraîche
            ts_before = self._vision.last_update_ts  # type: ignore[union-attr]
            deadline = time.monotonic() + _PAN_SETTLE + 0.3
            while time.monotonic() < deadline:
                if self._vision.last_update_ts > ts_before:  # type: ignore[union-attr]
                    break
                await asyncio.sleep(0.05)

            collected[key] = dict(self._vision.zones)  # type: ignore[union-attr]

        # Retour au centre
        await loop.run_in_executor(None, self._pantilt.center)  # type: ignore[union-attr]

        # Interprétation :
        # Quand on regarde à gauche, la zone "center" du frame = zone gauche du robot
        # Quand on regarde à droite, la zone "center" du frame = zone droite du robot
        lk = collected.get("look_left", {})
        ck = collected.get("look_center", {})
        rk = collected.get("look_right", {})

        left = lk.get("center", False) or lk.get("left", False)
        center = ck.get("center", False) or (ck.get("left", False) and ck.get("right", False))
        right = rk.get("center", False) or rk.get("right", False)

        log.debug(
            "Pan-tilt scan: look_left=%s look_center=%s look_right=%s → L=%s C=%s R=%s",
            lk,
            ck,
            rk,
            left,
            center,
            right,
        )
        return {"left": left, "center": center, "right": right}

    # ------------------------------------------------------------------
    # Avance par étapes
    # ------------------------------------------------------------------

    async def _step_forward(self, loop: asyncio.AbstractEventLoop, Direction) -> None:
        """
        Avance pendant step_duration secondes.
        Surveille l'ultrason et la zone centre toutes les _LOOP_POLL secondes.
        Stoppe immédiatement si obstacle détecté (urgence).
        """
        await asyncio.sleep(_SCAN_PAUSE)
        spd = self.speed
        await loop.run_in_executor(
            None, lambda s=spd: self._motors.from_direction(Direction.FORWARD, s)
        )

        start = time.monotonic()
        emergency = None

        while (time.monotonic() - start) < self.step_duration:
            # Check ultrason en temps réel
            if self._ultrasonic:
                r = self._ultrasonic.reading
                cm = r.front.distance_cm
                if (cm is not None and cm < self.obstacle_cm) or r.front.obstacle:
                    emergency = f"ultrason urgence {cm:.0f}cm" if cm else "ultrason urgence"
                    break
            # Check zone centre caméra
            if self._vision and self._vision.zones.get("center"):
                emergency = "vision centre urgence"
                break
            await asyncio.sleep(_LOOP_POLL)

        await loop.run_in_executor(None, self._motors.stop)

        if emergency:
            log.warning("Patrol: arrêt urgence pendant avance — %s", emergency)
            # Reset forward_since pour forcer une nouvelle décision au prochain scan
            self._forward_since = None

    # ------------------------------------------------------------------
    # Manœuvres d'évitement
    # ------------------------------------------------------------------

    def _next_turn_dir(self, Direction):
        """Alterne gauche/droite pour éviter de tourner en rond."""
        self._avoidance_count += 1
        return Direction.LEFT if self._avoidance_count % 2 == 0 else Direction.RIGHT

    async def _avoid_center(self, loop: asyncio.AbstractEventLoop, Direction) -> None:
        """Obstacle frontal ou des deux côtés : recul + rotation."""
        turn_dir = self._next_turn_dir(Direction)
        log.info(
            "Patrol avoid_center: recul %.2fs + rotation %s %.2fs",
            _REVERSE_DUR,
            turn_dir.value,
            _TURN_CENTER,
        )
        await loop.run_in_executor(
            None, lambda s=self.speed: self._motors.from_direction(Direction.BACKWARD, s)
        )
        await asyncio.sleep(_REVERSE_DUR)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.15)
        await loop.run_in_executor(
            None,
            lambda d=turn_dir: self._motors.from_direction(d, _TURN_SPEED),
        )
        await asyncio.sleep(_TURN_CENTER)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.15)

    async def _avoid_lateral(
        self,
        loop: asyncio.AbstractEventLoop,
        Direction,
        turn_dir,
        reason: str,
    ) -> None:
        """Obstacle latéral : stop + rotation courte vers le côté libre."""
        log.info(
            "Patrol avoid_lateral: → %s %.2fs | %s",
            turn_dir.value,
            _TURN_SHORT,
            reason,
        )
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.15)
        await loop.run_in_executor(
            None, lambda d=turn_dir: self._motors.from_direction(d, _TURN_SPEED)
        )
        await asyncio.sleep(_TURN_SHORT)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.15)

    async def _avoid_stuck(self, loop: asyncio.AbstractEventLoop, Direction) -> None:
        """Angle mort : recul long + rotation plus ample (alternance G/D)."""
        turn_dir = self._next_turn_dir(Direction)
        log.warning(
            "Patrol avoid_stuck: recul %.2fs + rotation %s %.2fs",
            _STUCK_REVERSE,
            turn_dir.value,
            _STUCK_TURN,
        )
        await loop.run_in_executor(
            None, lambda s=self.speed: self._motors.from_direction(Direction.BACKWARD, s)
        )
        await asyncio.sleep(_STUCK_REVERSE)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.2)
        await loop.run_in_executor(
            None, lambda d=turn_dir: self._motors.from_direction(d, _TURN_SPEED)
        )
        await asyncio.sleep(_STUCK_TURN)
        await loop.run_in_executor(None, self._motors.stop)
        await asyncio.sleep(0.2)
