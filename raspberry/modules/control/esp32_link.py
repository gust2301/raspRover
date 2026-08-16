"""
Couche basse : communication JSON-UART avec l'ESP32 du RaspRover.

Le firmware Waveshare UGV utilise un protocole JSON line-delimited (\n) sur UART
à 115200 bauds. Chaque commande est un objet JSON compact sur une ligne, du type :

    {"T":1,"L":0.3,"R":0.3}\n

où le champ ``T`` identifie le type de commande. Les codes ``T`` utilisés ici :

    T=0   Emergency stop (toutes sorties à zéro)
    T=1   Commande vitesse différentielle (L/R, chacun dans [-0.5, 0.5])
    T=126 Demande IMU / informations de statut
    T=130 Demande feedback châssis
    T=133 Contrôle position Pan-Tilt (X=pan°, Y=tilt°)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyserial est requis. Installez-le avec : pip install pyserial") from exc

from .exceptions import ESP32TimeoutError, LinkNotOpenError

log = logging.getLogger(__name__)


# --- Codes de commande du firmware Waveshare UGV -----------------------------
CMD_EMERGENCY_STOP = 0
CMD_SPEED_CTRL = 1
CMD_REQUEST_IMU = 126
CMD_REQUEST_BASE_FEEDBACK = 130
CMD_PANTILT_CTRL = 133
CMD_SERIAL_FEEDBACK = 131
CMD_SERIAL_ECHO = 143
CMD_MM_TYPE_SET = 900
FEEDBACK_TYPES = {1001, CMD_REQUEST_IMU, CMD_REQUEST_BASE_FEEDBACK}


@dataclass
class LinkStats:
    """Compteurs utiles pour le debug / la supervision."""

    bytes_sent: int = 0
    commands_sent: int = 0
    last_error: str | None = None


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
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._read_buffer = bytearray()
        self.stats = LinkStats()

    # -- Gestion de cycle de vie ---------------------------------------------

    def open(self) -> None:
        """Ouvre le port (série natif ou URL pyserial). Idempotent."""
        if self._ser and self._ser.is_open:
            return
        log.info("Ouverture du port %s @ %d bauds", self.port, self.baudrate)
        self._ser = serial.serial_for_url(self.port, baudrate=self.baudrate, timeout=self.timeout_s)
        time.sleep(0.3)
        try:
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
            self._read_buffer.clear()
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

    def __enter__(self) -> ESP32Link:
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
            raise LinkNotOpenError("ESP32Link.send() sans port ouvert. Appelez .open() d'abord.")
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

    def configure_platform(self, main_type: int, module_type: int = 2) -> None:
        """Configure les constantes chassis et le module dans le firmware.

        ``main_type`` vaut 1 pour RaspRover, 2 pour UGV Rover et 3 pour UGV
        Beast. ``module_type=2`` active notamment le retour mesure pan/tilt.
        """
        if main_type not in {1, 2, 3}:
            raise ValueError("main_type ESP32 invalide")
        if module_type not in {0, 1, 2}:
            raise ValueError("module_type ESP32 invalide")
        self.send({"T": CMD_MM_TYPE_SET, "main": main_type, "module": module_type})

    def request_feedback(
        self,
        timeout_s: float | None = None,
        command_type: int | None = None,
    ) -> dict:
        """
        Envoie une requete de feedback JSON et attend la reponse de l'ESP32.

        Par defaut, essaie d'abord ``T=130`` (feedback châssis), puis ``T=126``
        (IMU / statut) pour rester compatible avec plusieurs firmwares Waveshare.
        Retourne le dict recu. Leve ESP32TimeoutError en cas de timeout.
        """
        if not self.is_open:
            raise LinkNotOpenError("Port non ouvert")
        assert self._ser is not None

        effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
        command_types = (
            [command_type]
            if command_type is not None
            else [CMD_REQUEST_BASE_FEEDBACK, CMD_REQUEST_IMU]
        )
        last_error: ESP32TimeoutError | None = None

        for cmd_type in command_types:
            result: dict | None = None
            with self._lock:
                try:
                    self._ser.reset_input_buffer()
                except (serial.SerialException, AttributeError, NotImplementedError):
                    pass

                line_out = (json.dumps({"T": cmd_type}, separators=(",", ":")) + "\n").encode(
                    "ascii"
                )
                self._ser.write(line_out)
                self._ser.flush()
                self.stats.bytes_sent += len(line_out)
                self.stats.commands_sent += 1
                log.debug("TX -> %s", line_out.rstrip())

                deadline = time.time() + effective_timeout
                while time.time() < deadline:
                    raw = self._ser.read_until(b"\n", size=4096)
                    if not raw:
                        continue
                    line = raw.decode("ascii", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        log.debug("Ligne non-JSON ignoree : %r", line)
                        continue
                    if not isinstance(candidate, dict):
                        log.debug("Message non-dict ignore : %r", candidate)
                        continue
                    msg_type = candidate.get("T")
                    if msg_type not in FEEDBACK_TYPES and not self._looks_like_feedback(candidate):
                        log.debug("Message JSON ignore (pas un feedback) : %s", line)
                        continue
                    result = candidate
                    log.debug("RX <- %s", line)
                    break

            if result is not None:
                return result
            last_error = ESP32TimeoutError(
                f"Pas de reponse de l'ESP32 apres {effective_timeout}s avec T={cmd_type}"
            )

        assert last_error is not None
        raise last_error

    def set_serial_feedback(self, enabled: bool) -> None:
        """Active ou coupe le feedback serie continu (T=131)."""
        self.send({"T": CMD_SERIAL_FEEDBACK, "cmd": 1 if enabled else 0})

    def set_serial_echo(self, enabled: bool) -> None:
        """Active ou coupe l'echo serie des commandes recues (T=143)."""
        self.send({"T": CMD_SERIAL_ECHO, "cmd": 1 if enabled else 0})

    def read_line(self, timeout_s: float | None = None) -> str | None:
        """Lit une ligne complète sans perdre les fragments reçus sur timeout."""
        if not self.is_open:
            raise LinkNotOpenError("Port non ouvert")
        assert self._ser is not None
        deadline = time.monotonic() + (self.timeout_s if timeout_s is None else timeout_s)
        with self._read_lock:
            previous_timeout = self._ser.timeout
            try:
                while True:
                    newline = self._read_buffer.find(b"\n")
                    if newline >= 0:
                        raw = bytes(self._read_buffer[:newline])
                        del self._read_buffer[: newline + 1]
                        return raw.decode("ascii", errors="replace").rstrip("\r")

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._ser.timeout = min(0.05, remaining)
                    waiting = int(getattr(self._ser, "in_waiting", 0) or 0)
                    chunk = self._ser.read(max(1, min(waiting, 4096)))
                    if chunk:
                        self._read_buffer.extend(chunk)
                        if len(self._read_buffer) > 65536:
                            self._read_buffer.clear()
                            log.warning("Buffer UART vidé: aucune fin de ligne détectée")
            finally:
                self._ser.timeout = previous_timeout

    @staticmethod
    def _looks_like_feedback(candidate: dict[str, Any]) -> bool:
        # Le firmware Waveshare envoie 'v' pour la tension (pas 'voltage')
        # Exemple réel : {'T':1001,'L':0,'R':0,'r':0,'p':0,'v':11,'pan':0,'tilt':0}
        return any(
            key in candidate
            for key in (
                "v",
                "voltage",
                "odl",
                "odr",
                "x",
                "y",
                "yaw",
                "imu",
                "roll",
                "pitch",
                "pan",
                "tilt",
            )
        )
