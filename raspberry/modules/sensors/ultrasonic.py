"""
2x HC-SR04 (avant + arrière) via Arduino Uno (USB série).

L'Arduino envoie une ligne JSON toutes les ~200 ms :
  {"front_cm":45.3,"front_ok":true,"rear_cm":120.0,"rear_ok":true,
   "obstacle_front":false,"obstacle_rear":false}

Ce module lit ce flux en arrière-plan et expose la dernière mesure
via la propriété `reading` (thread-safe).

Câblage Arduino Uno :
  Avant  : TRIG → pin 9  / ECHO → pin 10
  Arrière: TRIG → pin 7  / ECHO → pin 8
  VCC → 5V  /  GND → GND  (pas de pont diviseur nécessaire)
  Arduino USB → Pi USB (/dev/ttyACM0 ou /dev/ttyUSB0)
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

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
# Structures de données
# ---------------------------------------------------------------------------

_CANDIDATE_PORTS = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"]


@dataclass(frozen=True)
class SingleReading:
    """Résultat d'un capteur individuel."""

    distance_cm: float | None  # None si timeout
    obstacle: bool
    ok: bool  # False si hors portée / timeout


@dataclass(frozen=True)
class SensorReading:
    """Résultat combiné des deux capteurs avant + arrière."""

    front: SingleReading = field(default_factory=lambda: SingleReading(None, False, False))
    rear: SingleReading = field(default_factory=lambda: SingleReading(None, False, False))
    error: str | None = None

    @property
    def obstacle(self) -> bool:
        """True si au moins un capteur détecte un obstacle."""
        return self.front.obstacle or self.rear.obstacle

    @property
    def distance_cm(self) -> float | None:
        """Distance minimale valide entre les deux capteurs (ou None)."""
        vals = [s.distance_cm for s in (self.front, self.rear) if s.distance_cm is not None]
        return min(vals) if vals else None


_NO_READING = SensorReading(error="non démarré")


# ---------------------------------------------------------------------------
# Auto-détection du port Arduino
# ---------------------------------------------------------------------------


def _auto_detect_port() -> str | None:
    if not _SERIAL_AVAILABLE:
        return None
    for port in _CANDIDATE_PORTS:
        try:
            s = serial.Serial(port, timeout=0.1)
            s.close()
            log.info("Arduino détecté sur %s", port)
            return port
        except (serial.SerialException, OSError):
            continue
    for info in serial.tools.list_ports.comports():
        if "ACM" in info.device or "USB" in info.device:
            log.info("Arduino détecté via comports : %s", info.device)
            return info.device
    return None


# ---------------------------------------------------------------------------
# Capteur principal
# ---------------------------------------------------------------------------


class UltrasonicSensor:
    """
    Lit le flux JSON de l'Arduino Uno (2 capteurs) en arrière-plan.

    Parameters
    ----------
    port : str | None
        Port série. None = auto-détection.
    baudrate : int
        Vitesse série (défaut 9600, doit correspondre au sketch).
    obstacle_threshold_cm : float
        Seuil obstacle en cm (défaut 20).
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
        if self._thread and self._thread.is_alive():
            return

        resolved_port = self.port or _auto_detect_port()

        if resolved_port and _SERIAL_AVAILABLE:
            try:
                self._serial = serial.Serial(resolved_port, self.baudrate, timeout=1.0)
                self._serial.reset_input_buffer()  # type: ignore[union-attr]
                log.info(
                    "Arduino 2xHC-SR04 connecté sur %s (%d baud)", resolved_port, self.baudrate
                )
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
    # Accès aux données
    # ------------------------------------------------------------------

    @property
    def reading(self) -> SensorReading:
        with self._lock:
            return self._latest

    def to_dict(self) -> dict:
        """Sérialise pour l'API WebSocket et REST."""
        r = self.reading
        return {
            "front_cm": r.front.distance_cm,
            "rear_cm": r.rear.distance_cm,
            "obstacle_front": r.front.obstacle,
            "obstacle_rear": r.rear.obstacle,
            "obstacle": r.obstacle,
            # Compat champ unique utilisé par le frontend
            "distance_cm": r.distance_cm,
            "sensor_error": r.error,
        }

    # ------------------------------------------------------------------
    # Boucle de lecture
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            reading = self._read_one()
            with self._lock:
                self._latest = reading

    def _read_one(self) -> SensorReading:
        # Mode simulation
        if self._serial is None:
            if not _SERIAL_AVAILABLE:
                import math
                import time

                t = time.time()
                front_cm = 50.0 + 30.0 * math.sin(t * 0.5)
                rear_cm = 80.0 + 20.0 * math.sin(t * 0.3 + 1.0)
                return SensorReading(
                    front=SingleReading(
                        round(front_cm, 1),
                        front_cm < self.obstacle_threshold_cm,
                        True,
                    ),
                    rear=SingleReading(
                        round(rear_cm, 1),
                        rear_cm < self.obstacle_threshold_cm,
                        True,
                    ),
                )
            self._stop_event.wait(0.2)
            return SensorReading(error="port série non disponible")

        try:
            raw = self._serial.readline()  # type: ignore[union-attr]
            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                return self._latest  # conserve la dernière valeur

            data = json.loads(line)
            return self._parse(data)

        except json.JSONDecodeError:
            return self._latest  # ligne corrompue → on garde l'ancienne
        except Exception as exc:  # noqa: BLE001
            log.error("Erreur lecture série : %s", exc)
            return SensorReading(error=str(exc))

    def _parse(self, data: dict) -> SensorReading:
        """Convertit un dict JSON Arduino en SensorReading."""
        thr = self.obstacle_threshold_cm

        front_cm_raw = data.get("front_cm")
        rear_cm_raw = data.get("rear_cm")

        front_cm = float(front_cm_raw) if front_cm_raw is not None else None
        rear_cm = float(rear_cm_raw) if rear_cm_raw is not None else None

        front_ok = bool(data.get("front_ok", front_cm is not None))
        rear_ok = bool(data.get("rear_ok", rear_cm is not None))

        obs_front = bool(data.get("obstacle_front", front_cm is not None and front_cm < thr))
        obs_rear = bool(data.get("obstacle_rear", rear_cm is not None and rear_cm < thr))

        return SensorReading(
            front=SingleReading(distance_cm=front_cm, obstacle=obs_front, ok=front_ok),
            rear=SingleReading(distance_cm=rear_cm, obstacle=obs_rear, ok=rear_ok),
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> UltrasonicSensor:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
