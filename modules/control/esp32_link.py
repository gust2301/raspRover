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
    T=131 Reset servos (optionnel)

La classe est thread-safe : un verrou protège les écritures série concurrentes.
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

    Usage typique :

        link = ESP32Link(port="/dev/ttyAMA0")
        link.open()
        link.send({"T": 1, "L": 0.3, "R": 0.3})
        link.close()

    Ou comme context manager :

        with ESP32Link("/dev/ttyAMA0") as link:
            link.send({"T": 1, "L": 0.3, "R": 0.3})
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
        """
        Ouvre le port (série natif ou URL pyserial).

        Accepte aussi bien un chemin matériel classique
        (``/dev/ttyAMA0``, ``/dev/ttyUSB0``, ``COM3``) qu'une URL pyserial :

        - ``socket://localhost:9999`` pour parler à l'émulateur ESP32
        - ``loop://`` pour les tests unitaires (boucle interne)
        - ``rfc2217://host:port`` pour un port série distant

        Idempotent.
        """
        if self._ser and self._ser.is_open:
            return
        log.info("Ouverture du port %s @ %d bauds", self.port, self.baudrate)
        # serial_for_url accepte les chemins natifs ET les URL (socket://, loop://…)
        self._ser = serial.serial_for_url(
            self.port,
            baudrate=self.baudrate,
            timeout=self.timeout_s,
        )
        # Laisser l'ESP32 (ou l'émulateur) initialiser son buffer.
        time.sleep(0.3)
        try:
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except (serial.SerialException, AttributeError, NotImplementedError):
            # Certaines URL (socket://, loop://) n'implémentent pas ces méthodes.
            pass

    def close(self) -> None:
        """Arrête proprement le robot puis ferme la liaison."""
        if not self._ser:
            return
        try:
            self.emergency_stop()
        except Exception:  # noqa: BLE001 — on ferme de toute façon
            log.warning("Impossible d'envoyer emergency_stop avant close()")
        if self._ser.is_open:
            self._ser.close()
        log.info("Port série %s fermé", self.port)

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
        """
        Sérialise ``payload`` en JSON compact + newline, et l'envoie à l'ESP32.
        Thread-safe.
        """
        if not self.is_open:
            raise LinkNotOpenError(
                "ESP32Link.send() appelé alors que le port n'est pas ouvert. "
                "Appelez .open() d'abord."
            )
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("ascii")
        with self._lock:
            try:
                assert self._ser is not None  # pour mypy
                self._ser.write(line)
                self._ser.flush()
                self.stats.bytes_sent += len(line)
                self.stats.commands_sent += 1
                log.debug("TX → %s", line.rstrip())
            except serial.SerialException as exc:
                self.stats.last_error = str(exc)
                log.error("Erreur d'écriture série : %s", exc)
                raise

    def emergency_stop(self) -> None:
        """Arrêt immédiat : moteurs à zéro via T=0, puis T=1 L=0 R=0 par sécurité."""
        try:
            self.send({"T": CMD_EMERGENCY_STOP})
        finally:
            # Double filet : certains firmwares ignorent T=0, T=1 fonctionne toujours.
            self.send({"T": CMD_SPEED_CTRL, "L": 0.0, "R": 0.0})

    def request_feedback(self, timeout_s: Optional[float] = None) -> dict:
        """
        Demande un retour d'état à l'ESP32 (batterie, IMU, position…).

        Retourne le dict JSON reçu. Lève :class:`ESP32TimeoutError` si rien
        n'est reçu dans le délai imparti.
        """
        if not self.is_open:
            raise LinkNotOpenError("Port non ouvert")
        assert self._ser is not None
        deadline = time.time() + (timeout_s if timeout_s is not None else self.timeout_s)
        with self._lock:
            # Vider le buffer d'entrée avant la requête pour ne pas lire
            # une ancienne trame.
            try:
                self._ser.reset_input_buffer()
            except (serial.SerialException, AttributeError, NotImplementedError):
                pass
            # Envoyer la requête en gardant le verrou (pour que la réponse
            # ne soit pas consommée par un autre thread).
            line_out = (json.dumps({"T": CMD_REQUEST_FEEDBACK}) + "\n").encode("ascii")
            self._ser.write(line_out)
            self._ser.flush()
            self.stats.bytes_sent += len(line_out)
            self.stats.commands_sent += 1

            while time.time() < deadline:
                # read_until est plus fiable que read(1) sur socket:// et marche
                # aussi sur serial natif. Retourne b"" si timeout sans newline.
                raw = self._ser.read_until(b"\n", size=4096)
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    log.debug("Ligne non-JSON ignorée : %r", line)
                    continue
        raise ESP32TimeoutError(
            f"Pas de réponse de l'ESP32 après {timeout_s or self.timeout_s}s"
        )
