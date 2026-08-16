"""
Contrôleur Pan-Tilt pour les servos ST3215 (bus série Waveshare).

Les servos ST3215 sont des servomoteurs "intelligents" sur bus TTL : on leur
envoie une position cible en "unités servo" (0-4095 sur 360°), et ils gèrent
eux-mêmes la boucle de régulation. L'ESP32 Waveshare fait l'intermédiaire :
depuis la Pi, on envoie un ordre de haut niveau en degrés via UART, et le
firmware ESP32 traduit vers le bus ST3215.

Commande JSON utilisée (firmware UGV Waveshare) :

    {"T":133,"X":<pan_deg>,"Y":<tilt_deg>,"SPD":<speed>,"ACC":<accel>}

Conventions :
- pan  > 0 : caméra tourne vers la droite
- tilt > 0 : caméra lève le nez
"""

from __future__ import annotations

import logging
import threading
import time

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
        speed: int = 1500,
        accel: int = 80,
    ) -> None:
        self._link = link
        self.pan_range = pan_range
        self.tilt_range = tilt_range
        self.speed = int(speed)
        self.accel = int(accel)
        self._pan = 0.0
        self._tilt = 0.0
        self._measured_pan: float | None = None
        self._measured_tilt: float | None = None
        self._feedback_at = 0.0
        self._feedback_condition = threading.Condition()

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
        """Position mesuree si disponible, sinon derniere consigne connue."""
        with self._feedback_condition:
            if self._measured_pan is not None and self._measured_tilt is not None:
                return (self._measured_pan, self._measured_tilt)
        return (self._pan, self._tilt)

    @property
    def commanded_position(self) -> tuple[float, float]:
        return (self._pan, self._tilt)

    @property
    def feedback_age_s(self) -> float | None:
        with self._feedback_condition:
            return time.monotonic() - self._feedback_at if self._feedback_at else None

    def update_feedback(self, feedback: dict) -> None:
        """Met a jour les angles reels retournes par les servos ST3215."""
        try:
            pan = float(feedback["pan"])
            tilt = float(feedback["tilt"])
        except (KeyError, TypeError, ValueError):
            return
        with self._feedback_condition:
            self._measured_pan = pan
            self._measured_tilt = tilt
            self._feedback_at = time.monotonic()
            self._feedback_condition.notify_all()

    def wait_until_reached(
        self,
        pan_deg: float,
        tilt_deg: float,
        *,
        tolerance_deg: float = 1.5,
        timeout_s: float = 3.0,
    ) -> tuple[float, float]:
        """Attend la position mesuree et refuse une simple consigne non verifiee."""
        deadline = time.monotonic() + timeout_s
        with self._feedback_condition:
            while time.monotonic() < deadline:
                age = time.monotonic() - self._feedback_at if self._feedback_at else None
                if (
                    age is not None
                    and age <= 0.5
                    and self._measured_pan is not None
                    and self._measured_tilt is not None
                    and abs(self._measured_pan - pan_deg) <= tolerance_deg
                    and abs(self._measured_tilt - tilt_deg) <= tolerance_deg
                ):
                    return self._measured_pan, self._measured_tilt
                self._feedback_condition.wait(
                    timeout=min(0.1, max(0.0, deadline - time.monotonic()))
                )
        age = self.feedback_age_s
        if age is None or age > 0.5:
            raise RuntimeError("Retour de position pan-tilt indisponible")
        measured = self.position
        raise RuntimeError(
            "Pan-tilt hors position "
            f"(mesure {measured[0]:.1f}°/{measured[1]:.1f}°, "
            f"cible {pan_deg:.1f}°/{tilt_deg:.1f}°)"
        )

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
