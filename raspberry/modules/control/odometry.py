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

    def _run(self) -> None:
        consecutive_errors = 0
        while not self._closed.is_set():
            started = time.monotonic()
            succeeded = False
            try:
                feedback = self._link.request_feedback(
                    timeout_s=min(0.25, max(0.08, self._period * 0.8)),
                    command_type=CMD_REQUEST_BASE_FEEDBACK,
                )
                if not self._valid_feedback(feedback):
                    raise ValueError("retour encodeur incomplet")
                self._publish(feedback)
                if self._on_feedback is not None:
                    self._on_feedback(feedback)
                consecutive_errors = 0
                succeeded = True
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                if consecutive_errors == 1 or consecutive_errors % 50 == 0:
                    log.warning("Retour encodeur ESP32 indisponible: %s", exc)
            retry_period = (
                self._period
                if succeeded
                else min(1.0, self._period * (2 ** min(consecutive_errors, 3)))
            )
            remaining = retry_period - (time.monotonic() - started)
            self._closed.wait(max(0.0, remaining))

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=1.0)
        self._socket.close()
