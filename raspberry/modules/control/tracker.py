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

log = logging.getLogger(__name__)

_LOOP_INTERVAL = 0.15  # s — période de contrôle
_DEAD_ZONE = 0.05  # zone morte normalisée [0,1]
_KP_PAN = 40.0  # gain P pan (degrés / unité normalisée)
_KP_TILT = 30.0  # gain P tilt
_RECENTER_TIMEOUT = 3.0  # s sans cible → recentrage


class TrackerController:
    """
    Suit la personne détectée par HumanDetector en ajustant le Pan-Tilt.

    Parameters
    ----------
    pantilt : PanTiltController
    detector : HumanDetector
    """

    def __init__(self, pantilt, detector) -> None:
        self._pantilt = pantilt
        self._detector = detector
        self._task: asyncio.Task | None = None
        self._active = False
        self._last_target_ts: float = 0.0

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
                if not recentered and (time.monotonic() - self._last_target_ts > _RECENTER_TIMEOUT):
                    try:
                        await loop.run_in_executor(None, self._pantilt.center)
                    except Exception as exc:  # noqa: BLE001
                        log.debug("TrackerController center error: %s", exc)
                    recentered = True
                continue

            self._last_target_ts = time.monotonic()
            recentered = False

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
