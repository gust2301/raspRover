"""
Capteur ultrason HC-SR04 — mesure de distance en continu.

Câblage :
  VCC  → 5 V
  GND  → GND
  TRIG → GPIO23  (sortie)
  ECHO → GPIO24  (entrée, signal 5 V → diviseur résistif → 3.3 V)

Le capteur est géré dans un thread de fond qui rafraîchit la mesure
toutes les POLL_INTERVAL_S secondes. L'accès à la dernière valeur
est thread-safe via SensorReading (dataclass immuable).

Compatibilité Pi 5 : gpiozero avec le backend lgpio (RP1 GPIO chip).
Si gpiozero/lgpio est absent (ex : CI), le module bascule en mode
simulation et retourne des distances fictives sans erreur.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import GPIO — dégradé si absent (CI, dev PC)
# ---------------------------------------------------------------------------

try:
    from gpiozero import DistanceSensor  # type: ignore[import-not-found]
    from gpiozero.pins.lgpio import LGPIOFactory  # type: ignore[import-not-found]

    _GPIO_AVAILABLE = True
except ImportError:
    _GPIO_AVAILABLE = False
    log.warning("gpiozero/lgpio absent — UltrasonicSensor en mode simulation")


# ---------------------------------------------------------------------------
# Résultat d'une mesure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorReading:
    """Résultat d'une mesure ultrason."""

    distance_cm: float | None  # None si timeout ou erreur
    obstacle: bool  # True si distance < seuil configuré
    error: str | None  # Message d'erreur, None si OK


_NO_READING = SensorReading(distance_cm=None, obstacle=False, error="non démarré")


# ---------------------------------------------------------------------------
# Capteur
# ---------------------------------------------------------------------------


class UltrasonicSensor:
    """
    Gère un HC-SR04 dans un thread de fond.

    Parameters
    ----------
    trig_pin : int
        Numéro de pin BCM pour TRIG (défaut 23).
    echo_pin : int
        Numéro de pin BCM pour ECHO (défaut 24).
    obstacle_threshold_cm : float
        Distance en cm en dessous de laquelle on signale un obstacle (défaut 20).
    max_distance_m : float
        Portée maximale déclarée à gpiozero (défaut 4 m).
    poll_interval_s : float
        Intervalle entre deux mesures (défaut 0.2 s = 5 Hz).
    """

    def __init__(
        self,
        trig_pin: int = 23,
        echo_pin: int = 24,
        obstacle_threshold_cm: float = 20.0,
        max_distance_m: float = 4.0,
        poll_interval_s: float = 0.2,
    ) -> None:
        self.trig_pin = trig_pin
        self.echo_pin = echo_pin
        self.obstacle_threshold_cm = obstacle_threshold_cm
        self.max_distance_m = max_distance_m
        self.poll_interval_s = poll_interval_s

        self._lock = threading.Lock()
        self._latest: SensorReading = _NO_READING
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._sensor: object | None = None  # instance gpiozero

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Démarre le thread de polling."""
        if self._thread and self._thread.is_alive():
            return

        if _GPIO_AVAILABLE:
            try:
                factory = LGPIOFactory()
                self._sensor = DistanceSensor(
                    echo=self.echo_pin,
                    trigger=self.trig_pin,
                    max_distance=self.max_distance_m,
                    pin_factory=factory,
                )
                log.info(
                    "HC-SR04 initialisé — TRIG=GPIO%d ECHO=GPIO%d seuil=%.0f cm",
                    self.trig_pin,
                    self.echo_pin,
                    self.obstacle_threshold_cm,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("Impossible d'initialiser le HC-SR04 : %s", exc)
                self._sensor = None
        else:
            self._sensor = None

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="ultrasonic-poll")
        self._thread.start()

    def stop(self) -> None:
        """Arrête le thread et libère le GPIO."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sensor is not None:
            try:
                self._sensor.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            self._sensor = None
        log.info("UltrasonicSensor arrêté")

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @property
    def reading(self) -> SensorReading:
        """Dernière mesure disponible (thread-safe)."""
        with self._lock:
            return self._latest

    def to_dict(self) -> dict:
        """Sérialise la dernière mesure pour l'API."""
        r = self.reading
        return {
            "distance_cm": r.distance_cm,
            "obstacle": r.obstacle,
            "sensor_error": r.error,
        }

    # ------------------------------------------------------------------
    # Boucle de polling (thread de fond)
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_s):
            reading = self._measure()
            with self._lock:
                self._latest = reading

    def _measure(self) -> SensorReading:
        """Effectue une mesure et retourne un SensorReading."""
        # Mode simulation (pas de GPIO)
        if self._sensor is None:
            if not _GPIO_AVAILABLE:
                import math
                import time as _t

                sim_cm = 50.0 + 30.0 * math.sin(_t.time() * 0.5)
                return SensorReading(
                    distance_cm=round(sim_cm, 1),
                    obstacle=sim_cm < self.obstacle_threshold_cm,
                    error=None,
                )
            return SensorReading(distance_cm=None, obstacle=False, error="GPIO non disponible")

        try:
            dist_m = self._sensor.distance  # type: ignore[union-attr]

            if dist_m is None or dist_m >= self.max_distance_m:
                # Hors portée — gpiozero retourne max_distance en cas de timeout
                return SensorReading(
                    distance_cm=None, obstacle=False, error="hors portée / timeout"
                )

            dist_cm = round(dist_m * 100, 1)
            obstacle = dist_cm < self.obstacle_threshold_cm
            return SensorReading(distance_cm=dist_cm, obstacle=obstacle, error=None)

        except Exception as exc:  # noqa: BLE001
            return SensorReading(distance_cm=None, obstacle=False, error=str(exc))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> UltrasonicSensor:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
