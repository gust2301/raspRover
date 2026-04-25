"""
Contrôleur Pan-Tilt pour les servos ST3215 (bus série Waveshare).

Les servos ST3215 sont des servomoteurs "intelligents" sur bus TTL : on leur
envoie une position cible en "unités servo" (0-4095 sur 360°), et ils gèrent
eux-mêmes la boucle de régulation. L'ESP32 Waveshare fait l'intermédiaire :
depuis la Pi, on envoie un ordre de haut niveau en degrés via UART, et le
firmware ESP32 traduit vers le bus ST3215.

Commande JSON utilisée (firmware UGV Waveshare) :

    {"T":13,"X":<pan_deg>,"Y":<tilt_deg>,"SPD":<speed>,"ACC":<accel>}

Conventions :
- pan  > 0 : caméra tourne vers la droite
- tilt > 0 : caméra lève le nez
"""

from __future__ import annotations

import logging

from .esp32_link import CMD_PANTILT_CTRL, ESP32Link
from .exceptions import InvalidParameterError

log = logging.getLogger(__name__)


class PanTiltController:
    """
    Pilote les 2 servos ST3215 du module Pan-Tilt.

    Parameters
    ----------
    link : ESP32Link
        Liaison série ouverte vers l'ESP32.
    pan_range, tilt_range : tuple[float, float]
        Limites angulaires autorisées (degrés). Toute commande hors plage
        est clampée.
    speed, accel : int
        Vitesse (0-4096) et accélération (0-255) du mouvement, transmises à
        chaque commande. Plus petits = mouvements plus doux (utile pour les
        enregistrements vidéo stables).
    """

    def __init__(
        self,
        link: ESP32Link,
        pan_range: tuple[float, float] = (-90.0, 90.0),
        tilt_range: tuple[float, float] = (-45.0, 60.0),
        speed: int = 600,
        accel: int = 50,
    ) -> None:
        self._link = link
        self.pan_range = pan_range
        self.tilt_range = tilt_range
        self.speed = int(speed)
        self.accel = int(accel)
        self._pan = 0.0
        self._tilt = 0.0

    # -- API publique --------------------------------------------------------

    def goto(
        self,
        pan_deg: float | None = None,
        tilt_deg: float | None = None,
        speed: int | None = None,
        accel: int | None = None,
    ) -> None:
        """
        Déplace la caméra vers une position absolue (en degrés).

        Si un des deux angles est ``None``, la dernière valeur connue est conservée.
        """
        pan = self._pan if pan_deg is None else self._clamp_pan(pan_deg)
        tilt = self._tilt if tilt_deg is None else self._clamp_tilt(tilt_deg)

        payload = {
            "T": CMD_PANTILT_CTRL,
            "X": round(pan, 2),
            "Y": round(tilt, 2),
            "SPD": speed if speed is not None else self.speed,
            "ACC": accel if accel is not None else self.accel,
        }
        self._link.send(payload)
        self._pan = pan
        self._tilt = tilt
        log.debug("pantilt.goto(pan=%.1f°, tilt=%.1f°)", pan, tilt)

    def nudge(self, d_pan: float = 0.0, d_tilt: float = 0.0, **kwargs) -> None:
        """Déplacement relatif par rapport à la position courante."""
        self.goto(self._pan + d_pan, self._tilt + d_tilt, **kwargs)

    def center(self) -> None:
        """Recentre la caméra à (0°, 0°)."""
        self.goto(0.0, 0.0)

    # -- État ---------------------------------------------------------------

    @property
    def position(self) -> tuple[float, float]:
        """Dernière position commandée (pan, tilt) en degrés."""
        return (self._pan, self._tilt)

    # -- Utilitaires --------------------------------------------------------

    def _clamp_pan(self, v: float) -> float:
        if v != v:
            raise InvalidParameterError("pan NaN")
        lo, hi = self.pan_range
        if v < lo or v > hi:
            log.info("Pan %.1f° clampé dans [%.1f, %.1f]", v, lo, hi)
        return max(lo, min(hi, float(v)))

    def _clamp_tilt(self, v: float) -> float:
        if v != v:
            raise InvalidParameterError("tilt NaN")
        lo, hi = self.tilt_range
        if v < lo or v > hi:
            log.info("Tilt %.1f° clampé dans [%.1f, %.1f]", v, lo, hi)
        return max(lo, min(hi, float(v)))
