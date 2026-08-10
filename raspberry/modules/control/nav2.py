"""Safe UDP boundary between the ROS 2 Nav2 container and motor control."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


class Nav2MotorBridge:
    """Accept Nav2 wheel commands only while an API-authorized mission is active."""

    def __init__(
        self,
        drive: Callable[[float, float], None],
        stop: Callable[[], None],
        *,
        motor_port: int = 7668,
        command_port: int = 7669,
        timeout_s: float = 0.6,
    ) -> None:
        self._drive = drive
        self._stop = stop
        self._motor_port = motor_port
        self._command_port = command_port
        self._timeout_s = timeout_s
        self._enabled = False
        self._received_command = False
        self._closed = threading.Event()
        self._last_command = 0.0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("127.0.0.1", motor_port))
        self._socket.settimeout(0.1)
        self._thread = threading.Thread(target=self._run, name="Nav2MotorBridge", daemon=True)
        self._thread.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._last_command = time.monotonic()
        self._received_command = False
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._stop()

    def follow_waypoints(self, waypoints: list[dict[str, float]]) -> None:
        self.enable()
        self._send_command({"action": "follow_waypoints", "waypoints": waypoints})

    def set_initial_pose(self, pose: dict[str, float]) -> None:
        """Send the localization seed repeatedly while the ROS bridge starts."""
        payload = {"action": "set_initial_pose", "pose": pose}
        for _attempt in range(3):
            self._send_command(payload)
            time.sleep(0.2)

    def cancel(self) -> None:
        self._send_command({"action": "cancel"})
        self.disable()

    def close(self) -> None:
        self.disable()
        self._closed.set()
        self._thread.join(timeout=1.0)
        self._socket.close()

    def _send_command(self, payload: dict) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(json.dumps(payload).encode(), ("127.0.0.1", self._command_port))

    def _run(self) -> None:
        stopped_for_timeout = False
        while not self._closed.is_set():
            try:
                raw, _ = self._socket.recvfrom(2048)
            except OSError as exc:
                if not isinstance(exc, socket.timeout):
                    return
                timed_out = time.monotonic() - self._last_command > self._timeout_s
                if self._enabled and self._received_command and timed_out:
                    if not stopped_for_timeout:
                        self._stop()
                        stopped_for_timeout = True
                    self._enabled = False
                continue

            if not self._enabled:
                continue
            try:
                command = json.loads(raw)
                left = max(-1.0, min(1.0, float(command["left"])))
                right = max(-1.0, min(1.0, float(command["right"])))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                log.warning("Commande moteur Nav2 UDP invalide")
                continue
            self._last_command = time.monotonic()
            self._received_command = True
            stopped_for_timeout = False
            self._drive(left, right)
