"""Transmission du retour encodeur ESP32 vers le noeud ROS 2 d'odometrie."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Callable

from .esp32_link import CMD_REQUEST_BASE_FEEDBACK, ESP32Link

log = logging.getLogger(__name__)


class EncoderFeedbackPublisher:
    """Interroge le chassis et publie ses mesures physiques sur UDP.

    Le firmware Waveshare retourne ``L``/``R`` en m/s et ``odl``/``odr`` en
    centimetres cumules. Le socket UDP constitue la frontiere entre le service
    Python de la Pi (proprietaire de l'UART) et ROS 2 dans le conteneur.
    """

    def __init__(
        self,
        link: ESP32Link,
        host: str = "127.0.0.1",
        port: int = 7667,
        frequency_hz: float = 10.0,
        on_feedback: Callable[[dict], None] | None = None,
    ) -> None:
        if frequency_hz <= 0:
            raise ValueError("frequency_hz doit etre strictement positif")
        self._link = link
        self._address = (host, int(port))
        self._period = 1.0 / float(frequency_hz)
        self._on_feedback = on_feedback
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._closed = threading.Event()
        self._feedback_lock = threading.Lock()
        self._latest_feedback: dict | None = None
        self._latest_feedback_at = 0.0
        self._sequence = 0
        self._thread = threading.Thread(
            target=self._run, name="EncoderFeedbackPublisher", daemon=True
        )
        self._thread.start()

    @staticmethod
    def _valid_feedback(feedback: dict) -> bool:
        try:
            for key in ("L", "R", "odl", "odr"):
                float(feedback[key])
        except (KeyError, TypeError, ValueError):
            return False
        return True

    def _publish(self, feedback: dict) -> None:
        with self._feedback_lock:
            self._latest_feedback = dict(feedback)
            self._latest_feedback_at = time.monotonic()
        self._sequence += 1
        payload = {
            "left_speed_m_s": float(feedback["L"]),
            "right_speed_m_s": float(feedback["R"]),
            "left_distance_cm": float(feedback["odl"]),
            "right_distance_cm": float(feedback["odr"]),
            "timestamp": time.time(),
            "sequence": self._sequence,
        }
        self._socket.sendto(
            json.dumps(payload, separators=(",", ":")).encode("ascii"), self._address
        )

    @property
    def latest_feedback(self) -> dict | None:
        """Dernière télémétrie reçue, sans nouvelle transaction UART."""
        with self._feedback_lock:
            if time.monotonic() - self._latest_feedback_at > max(1.0, self._period * 5):
                return None
            return dict(self._latest_feedback) if self._latest_feedback is not None else None

    def _run(self) -> None:
        """Lit l'UART en continu sans bloquer les commandes moteur.

        L'ancien code gardait le verrou série jusqu'à 250 ms pour chaque requête
        T=130. Les commandes de pilotage attendaient derrière ce verrou. Ici la
        requête est une simple écriture et ce thread est l'unique lecteur UART.
        """
        next_request = 0.0
        consecutive_errors = 0
        while not self._closed.is_set():
            now = time.monotonic()
            try:
                if now >= next_request:
                    self._link.send({"T": CMD_REQUEST_BASE_FEEDBACK})
                    next_request = now + self._period

                line = self._link.read_line(timeout_s=min(0.1, self._period))
                if not line:
                    continue
                try:
                    feedback = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("Ligne UART non JSON ignorée: %r", line)
                    continue
                if isinstance(feedback, dict) and self._valid_feedback(feedback):
                    self._publish(feedback)
                    if self._on_feedback is not None:
                        self._on_feedback(feedback)
                    consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                if consecutive_errors == 1 or consecutive_errors % 50 == 0:
                    log.warning("Retour encodeur ESP32 indisponible: %s", exc)
                self._closed.wait(min(0.2, self._period))

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=1.0)
        self._socket.close()
