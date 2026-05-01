"""
Capteur ultrason HC-SR04 via Arduino Uno (USB série).

L'Arduino envoie une ligne JSON toutes les 200 ms sur le port USB :
  {"distance_cm": 45.3, "obstacle": false}
  {"distance_cm": null, "obstacle": false, "error": "timeout"}

Ce module lit ce flux en arrière-plan et expose la dernière mesure
via la propriété `reading` (thread-safe).

Câblage Arduino Uno :
  HC-SR04 TRIG → Pin 9
  HC-SR04 ECHO → Pin 10
  HC-SR04 VCC  → 5V   (pas de pont diviseur nécessaire)
  HC-SR04 GND  → GND
  Arduino USB  → Pi USB (/dev/ttyACM0 ou /dev/ttyUSB0)
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import pyserial — dégradé si absent (CI)
# ---------------------------------------------------------------------------

try:
    import serial  # type: ignore[import-not-found]
    import serial.tools.list_ports  # type: ignore[import-not-found]

    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False
    log.warning("pyserial absent — UltrasonicSensor en mode simulation")


# ---------------------------------------------------------------------------
# Résultat d'une mesure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorReading:
    """Résultat d'une mesure ultrason."""

    distance_cm: float | None  # None si timeout ou erreur
    obstacle: bool
    error: str | None


_NO_READING = SensorReading(distance_cm=None, obstacle=False, error="non démarré")

# Ports USB à tester dans l'ordre (Linux)
_CANDIDATE_PORTS = ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0", "/dev/ttyUSB1"]


def _auto_detect_port() -> str | None:
    """Détecte automatiquement le port série de l'Arduino."""
    if not _SERIAL_AVAILABLE:
        return None
    # Priorité aux ports connus
    for port in _CANDIDATE_PORTS:
        try:
            s = serial.Serial(port, timeout=0.1)
            s.close()
            log.info("Arduino détecté sur %s", port)
            return port
        except (serial.SerialException, OSError):
            continue
    # Fallback : cherche dans les ports listés
    for info in serial.tools.list_ports.comports():
        if "ACM" in info.device or "USB" in info.device:
            log.info("Arduino détecté via comports : %s", info.device)
            return info.device
    return None


# ---------------------------------------------------------------------------
# Capteur
# ---------------------------------------------------------------------------


class UltrasonicSensor:
    """
    Lit le flux JSON de l'Arduino Uno en arrière-plan.

    Parameters
    ----------
    port : str | None
        Port série (ex: '/dev/ttyACM0'). None = auto-détection.
    baudrate : int
        Vitesse série (doit correspondre au sketch Arduino, défaut 9600).
    obstacle_threshold_cm : float
        Seuil obstacle en cm (défaut 20). Utilisé uniquement si l'Arduino
        n'envoie pas le champ 'obstacle' (compatibilité).
    """

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 9600,
        obstacle_threshold_cm: float = 20.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.obstacle_threshold_cm = obstacle_threshold_cm

        self._lock = threading.Lock()
        self._latest: SensorReading = _NO_READING
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._serial: object | None = None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Ouvre le port série et démarre le thread de lecture."""
        if self._thread and self._thread.is_alive():
            return

        resolved_port = self.port or _auto_detect_port()

        if resolved_port and _SERIAL_AVAILABLE:
            try:
                self._serial = serial.Serial(resolved_port, self.baudrate, timeout=1.0)
                # Vide le buffer de démarrage de l'Arduino
                self._serial.reset_input_buffer()  # type: ignore[union-attr]
                log.info("Arduino HC-SR04 connecté sur %s (%d baud)", resolved_port, self.baudrate)
            except Exception as exc:  # noqa: BLE001
                log.error("Impossible d'ouvrir %s : %s", resolved_port, exc)
                self._serial = None
        else:
            self._serial = None
            if not _SERIAL_AVAILABLE:
                log.info("Mode simulation (pyserial absent)")
            else:
                log.warning("Aucun port Arduino trouvé — mode simulation")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="ultrasonic-serial"
        )
        self._thread.start()

    def stop(self) -> None:
        """Arrête le thread et ferme le port série."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._serial is not None:
            try:
                self._serial.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            self._serial = None
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
    # Boucle de lecture série (thread de fond)
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            reading = self._read_one()
            with self._lock:
                self._latest = reading

    def _read_one(self) -> SensorReading:
        # Mode simulation (pas de serial)
        if self._serial is None:
            if not _SERIAL_AVAILABLE:
                import math
                import time

                sim_cm = 50.0 + 30.0 * math.sin(time.time() * 0.5)
                return SensorReading(
                    distance_cm=round(sim_cm, 1),
                    obstacle=sim_cm < self.obstacle_threshold_cm,
                    error=None,
                )
            self._stop_event.wait(0.2)
            return SensorReading(
                distance_cm=None, obstacle=False, error="port série non disponible"
            )

        try:
            raw = self._serial.readline()  # type: ignore[union-attr]
            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                return SensorReading(distance_cm=None, obstacle=False, error="pas de données")

            data = json.loads(line)
            dist = data.get("distance_cm")
            dist_f = float(dist) if dist is not None else None
            obstacle = bool(
                data.get("obstacle", dist_f is not None and dist_f < self.obstacle_threshold_cm)
            )
            err = data.get("error")
            return SensorReading(distance_cm=dist_f, obstacle=obstacle, error=err)

        except json.JSONDecodeError:
            log.debug("Ligne série invalide ignorée : %r", line if "line" in dir() else "?")
            return self._latest  # conserve la dernière valeur valide
        except Exception as exc:  # noqa: BLE001
            log.error("Erreur lecture série : %s", exc)
            return SensorReading(distance_cm=None, obstacle=False, error=str(exc))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> UltrasonicSensor:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
