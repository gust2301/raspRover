"""
Contrôleur de tracking P — suit la personne détectée en Pan-Tilt.

Algorithme :
  error_x = cx - 0.5   (>0 → personne à droite → pan+)
  error_y = cy - 0.5   (>0 → personne en bas   → tilt-)
  new_pan  = pan  + Kp_pan  * error_x
  new_tilt = tilt - Kp_tilt * error_y

Zone morte : |error| < DEAD_ZONE → pas de mouvement.
Pas de cible depuis RECENTER_TIMEOUT s → recentrage automatique.

Mode exclusif : ne jamais démarrer pendant une patrouille (géré dans server.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

_LOOP_INTERVAL = 0.15  # s — période de contrôle
_DEAD_ZONE = 0.05  # zone morte normalisée [0,1]
_KP_PAN = 40.0  # gain P pan (degrés / unité normalisée)
_KP_TILT = 30.0  # gain P tilt
_RECENTER_TIMEOUT = 3.0  # s sans cible → recentrage

_AUTO_RECORD_DURATION = 15.0  # durée de l'enregistrement auto (s)
_AUTO_RECORD_COOLDOWN = 30.0  # intervalle min entre deux enregistrements (s)
_DETECT_COOLDOWN = 10.0  # intervalle min entre deux incidents person_detected (s)


class TrackerController:
    """
    Suit la personne détectée par HumanDetector en ajustant le Pan-Tilt.

    Parameters
    ----------
    pantilt : PanTiltController
    detector : HumanDetector
    on_incident : callable(type, severity, details) -> int | None
    on_auto_record : async callable(mp4_path, incident_id) | None
    """

    def __init__(
        self,
        pantilt,
        detector,
        on_incident: Callable[[str, str, str], int] | None = None,
        on_auto_record: Callable[[str, int], Awaitable[None]] | None = None,
    ) -> None:
        self._pantilt = pantilt
        self._detector = detector
        self._on_incident = on_incident
        self._on_auto_record = on_auto_record
        self._task: asyncio.Task | None = None
        self._active = False
        self._last_target_ts: float = 0.0
        self._last_record_ts: float = 0.0
        self._last_detect_ts: float = 0.0
        self._was_detected: bool = False

    @property
    def active(self) -> bool:
        return self._active

    def to_dict(self) -> dict:
        return {"tracker_active": self._active}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._active:
            return
        self._active = True
        self._last_target_ts = time.monotonic()
        self._was_detected = False
        self._task = loop.create_task(self._loop())
        log.info(
            "TrackerController démarré (Kp_pan=%.1f Kp_tilt=%.1f dz=%.2f)",
            _KP_PAN,
            _KP_TILT,
            _DEAD_ZONE,
        )

    def stop(self) -> None:
        self._active = False
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("TrackerController arrêté")

    # ------------------------------------------------------------------
    # Boucle de contrôle
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        recentered = False

        while self._active:
            await asyncio.sleep(_LOOP_INTERVAL)

            target = self._detector.best_target
            pan, tilt = self._pantilt.position

            if target is None:
                # Personne vient de disparaître
                if self._was_detected:
                    self._was_detected = False
                    self._fire_incident("person_lost", "info", "Personne perdue de vue")

                if not recentered and (time.monotonic() - self._last_target_ts > _RECENTER_TIMEOUT):
                    try:
                        await loop.run_in_executor(None, self._pantilt.center)
                    except Exception as exc:  # noqa: BLE001
                        log.debug("TrackerController center error: %s", exc)
                    recentered = True
                continue

            self._last_target_ts = time.monotonic()
            recentered = False

            # Première détection (ou après une perte)
            if not self._was_detected:
                self._was_detected = True
                incident_id = self._fire_incident(
                    "person_detected", "warning", "Personne détectée par la caméra"
                )
                self._trigger_auto_record(loop, incident_id)

            cx, cy, _weight = target
            error_x = cx - 0.5
            error_y = cy - 0.5

            new_pan = pan
            new_tilt = tilt

            if abs(error_x) > _DEAD_ZONE:
                new_pan = pan + _KP_PAN * error_x

            if abs(error_y) > _DEAD_ZONE:
                new_tilt = tilt - _KP_TILT * error_y

            if new_pan != pan or new_tilt != tilt:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda p=new_pan, t=new_tilt: self._pantilt.goto(p, t),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.debug("TrackerController goto error: %s", exc)

    # ------------------------------------------------------------------
    # Helpers incidents / enregistrement
    # ------------------------------------------------------------------

    def _fire_incident(self, inc_type: str, severity: str, details: str) -> int | None:
        """Log un incident avec cooldown pour éviter le spam."""
        now = time.monotonic()
        if inc_type == "person_detected" and now - self._last_detect_ts < _DETECT_COOLDOWN:
            return None
        if inc_type == "person_detected":
            self._last_detect_ts = now

        if self._on_incident is None:
            return None
        try:
            return self._on_incident(inc_type, severity, details)
        except Exception as exc:  # noqa: BLE001
            log.warning("TrackerController incident error: %s", exc)
            return None

    def _trigger_auto_record(
        self, loop: asyncio.AbstractEventLoop, incident_id: int | None
    ) -> None:
        if self._on_auto_record is None:
            return
        now = time.monotonic()
        if now - self._last_record_ts < _AUTO_RECORD_COOLDOWN:
            return
        self._last_record_ts = now
        import datetime

        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
        path = f"/tmp/tracker_video_{ts}.mp4"
        loop.create_task(self._on_auto_record(path, incident_id or 0))
