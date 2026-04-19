"""
Couche basse : communication JSON-UART avec l'ESP32 du RaspRover.

Le firmware Waveshare UGV utilise un protocole JSON line-delimited (\n) sur UART
à 115200 bauds. Chaque commande est un objet JSON compact sur une ligne, du type :

    {"T":1,"L":0.3,"R":0.3}\n

où le champ ``T`` identifie le type de commande. Les codes ``T`` utilisés ici :

    T=0   Emergency stop (toutes sorties à zéro)
    T=1   Commande vitesse différentielle (L/R, chacun dans [-0.5, 0.5])
    T=13  Contrôle position Pan-Tilt (X=pan°, Y=tilt°)
    T=126 Demande feedback (batterie, IMU) — optionnel
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pyserial est requis. Installez-le avec : pip install pyserial"
    ) from exc

from .exceptions import ESP32TimeoutError, LinkNotOpenError

log = logging.getLogger(__name__)


# --- Codes de commande du firmware Waveshare UGV -----------------------------
CMD_EMERGENCY_STOP = 0
CMD_SPEED_CTRL = 1
CMD_PANTILT_CTRL = 13
CMD_REQUEST_FEEDBACK = 126


@dataclass
class LinkStats:
    """Compteurs utiles pour le debug / la supervision."""

    bytes_sent: int = 0
    commands_sent: int = 0
    last_error: Optional[str] = None


class ESP32Link:
    """
    Liaison série bas niveau vers l'ESP32 Waveshare.

    Usage :

        with ESP32Link("/dev/ttyAMA0") as link:
            link.send({"T": 1, "L": 0.3, "R": 0.3})

    Accepte aussi les URL pyserial (socket://, loop://, rfc2217://) pour
    les tests sans matériel.
    """

    def __init__(
        self,
        port: str = "/dev/ttyAMA0",
        baudrate: int = 115200,
        timeout_s: float = 1.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self.stats = LinkStats()

    # -- Gestion de cycle de vie ---------------------------------------------

    def open(self) -> None:
        """Ouvre le port (série natif ou URL pyserial). Idempotent."""
        if self._ser and self._ser.is_open:
            return
        log.info("Ouverture du port %s @ %d bauds", self.port, self.baudrate)
        self._ser = serial.serial_for_url(
            self.port, baudrate=self.baudrate, timeout=self.timeout_s
        )
        time.sleep(0.3)
        try:
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except (serial.SerialException, AttributeError, NotImplementedError):
            pass

    def close(self) -> None:
        """Arrête proprement le robot puis ferme la liaison."""
        if not self._ser:
            return
        try:
            self.emergency_stop()
        except Exception:  # noqa: BLE001
            log.warning("Impossible d'envoyer emergency_stop avant close()")
        if self._ser.is_open:
            self._ser.close()
        log.info("Port %s fermé", self.port)

    def __enter__(self) -> "ESP32Link":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    # -- API publique --------------------------------------------------------

    def send(self, payload: dict[str, Any]) -> None:
        """Sérialise ``payload`` en JSON + \\n et l'envoie à l'ESP32 (thread-safe)."""
        if not self.is_open:
            raise LinkNotOpenError(
                "ESP32Link.send() sans port ouvert. Appelez .open() d'abord."
            )
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("ascii")
        with self._lock:
            try:
                assert self._ser is not None
                self._ser.write(line)
                self._ser.flush()
                self.stats.bytes_sent += len(line)
                self.stats.commands_sent += 1
                log.debug("TX -> %s", line.rstrip())
            except serial.SerialException as exc:
                self.stats.last_error = str(exc)
                log.error("Erreur d'ecriture serie : %s", exc)
                raise

    def emergency_stop(self) -> None:
        """Arret immediat : T=0 puis T=1 L=0 R=0 par securite."""
        try:
            self.send({"T": CMD_EMERGENCY_STOP})
        finally:
            self.send({"T": CMD_SPEED_CTRL, "L": 0.0, "R": 0.0})

    def request_feedback(self, timeout_s: Optional[float] = None) -> dict:
        """
        Envoie {"T":126} et attend la reponse JSON de l'ESP32.

        Retourne le dict recu. Leve ESP32TimeoutError en cas de timeout.
        """
        if not self.is_open:
            raise LinkNotOpenError("Port non ouvert")
        assert self._ser is not None

        effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
        result: Optional[dict] = None

        with self._lock:
            # 1) purger le buffer d'entree
            try:
                self._ser.reset_input_buffer()
            except (serial.SerialException, AttributeError, NotImplementedError):
                pass

            # 2) envoyer la requete (sans repasser par send() pour ne pas
            #    reprendre le verrou)
            line_out = (
                json.dumps({"T": CMD_REQUEST_FEEDBACK}, separators=(",", ":"))
                + "\n"
            ).encode("ascii")
            self._ser.write(line_out)
            self._ser.flush()
            self.stats.bytes_sent += len(line_out)
            self.stats.commands_sent += 1
            log.debug("TX -> %s", line_out.rstrip())

            # 3) lire jusqu'a une ligne JSON valide ou timeout
            deadline = time.time() + effective_timeout
            while time.time() < deadline:
                raw = self._ser.read_until(b"\n", size=4096)
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                try:
                    result = json.loads(line)
                    log.debug("RX <- %s", line)
                    break
                except json.JSONDecodeError:
                    log.debug("Ligne non-JSON ignoree : %r", line)
                    continue

        if result is None:
            raise ESP32TimeoutError(
                f"Pas de reponse de l'ESP32 apres {effective_timeout}s"
            )
        return result
